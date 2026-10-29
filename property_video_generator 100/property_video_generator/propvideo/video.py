"""MP4 export through the ffmpeg command line."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image


class SetupError(Exception):
    """The environment is missing something (e.g. ffmpeg)."""


def ensure_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:  # fall back to the ffmpeg binary bundled with the imageio-ffmpeg pip package
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            exe = None
    if not exe:
        raise SetupError(
            "ffmpeg was not found. Install it (macOS: brew install ffmpeg, Ubuntu: sudo apt install ffmpeg, "
            "Windows: winget install ffmpeg) and make sure it is on your PATH."
        )
    return exe


def encode_mp4(frames: Iterable[Image.Image], size: tuple[int, int], fps: int, out_path: Path,
               audio_wav: Path | None = None, total_frames: int = 0,
               on_progress: Callable[[int, int], None] | None = None) -> None:
    ffmpeg = ensure_ffmpeg()
    W, H = size
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
    if audio_wav:
        cmd += ["-i", str(audio_wav)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    if audio_wav:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-movflags", "+faststart", str(out_path)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for n, frame in enumerate(frames, 1):
            proc.stdin.write(frame.tobytes())
            if on_progress and (n % 24 == 0 or n == total_frames):
                on_progress(n, total_frames)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace").strip()
    if proc.wait() != 0:
        raise SetupError(f"ffmpeg failed while writing the video:\n{err[-600:]}")
