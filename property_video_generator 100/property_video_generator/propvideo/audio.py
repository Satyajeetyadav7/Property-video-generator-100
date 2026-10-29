"""Audio: generated royalty-free background music and optional text-to-speech narration.

Music is synthesised with numpy (no audio files, so there is nothing to license).
Narration needs a local TTS engine: espeak-ng / espeak (Linux), `say` (macOS), or any
command given in the PVG_TTS_CMD environment variable, e.g.  PVG_TTS_CMD='mytts --out {out} --text {text}'.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from .video import ensure_ffmpeg

SR = 44100


# ---------------------------------------------------------------- music

_CHORDS = [  # C major - G - A minor - F, as note frequencies in Hz
    (261.63, 329.63, 392.00),
    (196.00, 246.94, 293.66),
    (220.00, 261.63, 329.63),
    (174.61, 220.00, 261.63),
]


def make_music(duration: float) -> np.ndarray:
    """Soft pad + gentle plucked arpeggio, mono float array in [-1, 1]."""
    n = int(duration * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    chord_len = 2.5
    for k in range(int(np.ceil(duration / chord_len))):
        a, b = int(k * chord_len * SR), min(n, int((k + 1) * chord_len * SR))
        if a >= n:
            break
        chord = _CHORDS[k % len(_CHORDS)]
        seg_t = t[a:b] - t[a]
        env = np.minimum(1, seg_t / 0.6) * np.minimum(1, (chord_len - seg_t) / 0.6).clip(0, 1)
        pad = sum(np.sin(2 * np.pi * f * seg_t) + 0.5 * np.sin(2 * np.pi * f * 2 * seg_t + 0.3) for f in chord)
        out[a:b] += 0.12 * pad * env
        # arpeggio: a pluck every 0.625 s
        for j, f in enumerate(chord * 2):
            s0 = int(j * 0.4167 * SR)
            if a + s0 >= b:
                break
            ln = min(int(0.9 * SR), b - (a + s0))
            tt = np.arange(ln) / SR
            pluck = np.sin(2 * np.pi * f * 2 * tt) * np.exp(-tt * 5.5)
            out[a + s0:a + s0 + ln] += 0.10 * pluck
    fade_in, fade_out = min(1.0, duration / 4), min(2.0, duration / 3)
    out *= np.minimum(1, t / fade_in) * np.minimum(1, (duration - t) / fade_out).clip(0, 1)
    peak = np.max(np.abs(out)) or 1.0
    return (out / peak * 0.6).astype(np.float32)


# ---------------------------------------------------------------- narration

def speakable(text: str) -> str:
    """Make amounts easier for a TTS engine to read: '₹78,50,000' -> '78.5 lakh rupees'."""
    def rupees(m: re.Match) -> str:
        value = float(m.group(1).replace(",", ""))
        if value >= 1e7:
            return f"{round(value / 1e7, 2):g} crore rupees"
        if value >= 1e5:
            return f"{round(value / 1e5, 2):g} lakh rupees"
        return f"{value:g} rupees"
    text = re.sub(r"₹\s*([\d,]+(?:\.\d+)?)", rupees, text)
    text = re.sub(r"\$\s*([\d,]+(?:\.\d+)?)", lambda m: f"{m.group(1)} dollars", text)
    return text.replace("|", ",").replace("+", "plus ")


def find_tts() -> tuple[str, str] | None:
    """Return (engine_name, command) for the first TTS engine available."""
    custom = os.environ.get("PVG_TTS_CMD")
    if custom:
        return "custom", custom
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            return exe, exe
    if shutil.which("say"):
        return "say", "say"
    return None


def _run_tts(engine: tuple[str, str], text: str, out_wav: Path) -> None:
    name, cmd = engine
    raw = out_wav.with_suffix(".raw.wav")
    if name == "custom":
        argv = [a.replace("{out}", str(raw)).replace("{text}", text) for a in shlex.split(cmd)]
    elif name == "say":
        raw = out_wav.with_suffix(".aiff")
        argv = ["say", "-o", str(raw), "--", text]
    else:
        argv = [cmd, "-s", "150", "-v", "en-us", "-w", str(raw), text]
    subprocess.run(argv, check=True, capture_output=True, timeout=60)
    subprocess.run([ensure_ffmpeg(), "-y", "-loglevel", "error", "-i", str(raw), "-ar", str(SR), "-ac", "1", str(out_wav)],
                   check=True, capture_output=True, timeout=60)
    raw.unlink(missing_ok=True)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data


def synthesize_narration(texts: list[str], workdir: Path) -> tuple[list[np.ndarray | None], list[str]]:
    """Return one clip per text (None if empty or failed) plus human-readable notes."""
    engine = find_tts()
    if engine is None:
        return [None] * len(texts), [
            "Narration requested but no text-to-speech engine was found (install espeak-ng, or set PVG_TTS_CMD). "
            "The video will have captions and background music only."
        ]
    workdir.mkdir(parents=True, exist_ok=True)
    clips: list[np.ndarray | None] = []
    notes = [f"Narration engine: {engine[0]}"]
    for i, text in enumerate(texts):
        if not text.strip():
            clips.append(None)
            continue
        wav = workdir / f"narration_{i}.wav"
        try:
            _run_tts(engine, speakable(text), wav)
            clips.append(read_wav(wav))
        except (subprocess.SubprocessError, OSError, wave.Error) as exc:
            notes.append(f"Narration failed for scene {i + 1} ({type(exc).__name__}); that scene stays silent.")
            clips.append(None)
    return clips, notes


# ---------------------------------------------------------------- mixing

def mix_track(total: float, music: np.ndarray | None, narration: list[tuple[float, np.ndarray]]) -> np.ndarray:
    n = int(total * SR)
    mix = np.zeros(n, dtype=np.float32)
    if music is not None:
        gain = 0.22 if narration else 0.5          # keep music under the voice
        mix[: min(n, len(music))] += gain * music[:n]
    for start, clip in narration:
        a = int(start * SR)
        b = min(n, a + len(clip))
        if a < n:
            mix[a:b] += 0.9 * clip[: b - a]
    peak = np.max(np.abs(mix)) if n else 0
    if peak > 0.98:
        mix *= 0.98 / peak
    return mix


def write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
