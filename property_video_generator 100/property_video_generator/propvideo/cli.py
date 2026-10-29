"""Command-line interface: ``python generate_video.py --input sample/property.json``."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path

from . import audio
from .models import InputError, Property, collect_images_from_dir, load_property, property_from_dict
from .render import FORMATS, Composer, Theme, contact_sheet, hex_to_rgb
from .script import (BASE_DURATION, build_template_script, check_scenes, refine_with_llm,
                     scenes_to_json)
from .video import SetupError, encode_mp4, ensure_ffmpeg


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="generate_video.py",
        description="Turn property details and photos into a short promotional MP4.",
    )
    p.add_argument("-i", "--input", help="property JSON file (see sample/property.json)")
    p.add_argument("--interactive", action="store_true", help="answer prompts instead of using a JSON file")
    p.add_argument("--images-dir", help="use every image in this folder (overrides 'images' in the JSON)")
    p.add_argument("-o", "--output", default="output/property_video.mp4", help="MP4 path to write")
    p.add_argument("--format", choices=FORMATS, default="landscape",
                   help="landscape 1280x720, vertical 720x1280 (Reels/Shorts), square 1080x1080")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--accent", default="#F26B21", help="accent colour as hex")
    p.add_argument("--narrate", action="store_true", help="add a spoken voice-over (needs a local TTS engine)")
    p.add_argument("--no-music", action="store_true", help="do not add generated background music")
    p.add_argument("--ai", action="store_true",
                   help="let an LLM reword the voice-over (needs ANTHROPIC_API_KEY; output is fact-checked)")
    p.add_argument("--debug", action="store_true", help="show full tracebacks")
    return p


def _ask(label: str, required: bool = False) -> str:
    while True:
        value = input(f"{label}{' *' if required else ''}: ").strip()
        if value or not required:
            return value
        print("  This one is required.")


def interactive_property() -> Property:
    print("Enter the property details (press Enter to skip optional fields).\n")
    data = {
        "name": _ask("Property name", True),
        "location": _ask("Location"),
        "price": _ask("Price (e.g. ₹78,50,000)"),
        "property_type": _ask("Property type (e.g. 2-BHK apartment)"),
        "features": _ask("Key features, separated by commas"),
        "contact": _ask("Contact details"),
        "cta": _ask("Call-to-action text (e.g. Book a site visit today)"),
    }
    folder = _ask("Folder containing the photos (or leave blank to list files)")
    if folder:
        data["images"] = collect_images_from_dir(Path(folder).expanduser())
    else:
        data["images"] = [s.strip() for s in _ask("Image paths, separated by commas", True).split(",") if s.strip()]
    return property_from_dict(data, base_dir=Path.cwd())


def _progress(done: int, total: int) -> None:
    pct = 100 * done // max(1, total)
    print(f"\r  rendering frames: {done}/{total} ({pct}%)", end="", flush=True)


def run(args: argparse.Namespace) -> int:
    ensure_ffmpeg()
    if args.interactive:
        prop = interactive_property()
    elif args.input:
        prop = load_property(args.input, args.images_dir)
    else:
        raise InputError("Give a property file with --input FILE.json, or use --interactive. See --help.")

    try:
        theme = Theme(accent=hex_to_rgb(args.accent))
    except ValueError as exc:
        raise InputError(f"--accent: {exc}") from exc
    if not 10 <= args.fps <= 60:
        raise InputError("--fps must be between 10 and 60.")

    for w in prop.warnings:
        print(f"  warning: {w}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    # 1. script
    scenes = build_template_script(prop)
    if args.ai:
        scenes, ai_notes = refine_with_llm(scenes, prop)
        notes += ai_notes
    problems = check_scenes(scenes, prop)
    if problems:  # should never happen with the template; surfaced rather than hidden
        notes += [f"fact-check: {p}" for p in problems]

    # 2. narration (scene length follows the speech so nothing is cut off)
    clips: list = [None] * len(scenes)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        if args.narrate:
            clips, tts_notes = audio.synthesize_narration([s.narration for s in scenes], tmpdir)
            notes += tts_notes
            for sc, clip in zip(scenes, clips):
                if clip is not None:
                    sc.duration = max(BASE_DURATION[sc.kind], len(clip) / audio.SR + 0.95)

        # 3. layout + audio
        size = FORMATS[args.format]
        print(f"Building {len(scenes)} scenes at {size[0]}x{size[1]}...")
        composer = Composer(scenes, size, args.fps, theme)
        narr_clips = [(composer.starts[i] + 0.35, c) for i, c in enumerate(clips) if c is not None]
        audio_path = None
        if not args.no_music or narr_clips:
            music = None if args.no_music else audio.make_music(composer.total)
            audio_path = tmpdir / "mix.wav"
            audio.write_wav(audio_path, audio.mix_track(composer.total, music, narr_clips))

        # 4. render + export
        t0 = time.time()
        encode_mp4(composer.frames(), size, args.fps, out, audio_path, composer.frame_count, _progress)
        print()

    # 5. extras: preview sheet + script for transparency
    preview = out.with_suffix(".preview.jpg")
    contact_sheet(composer, preview)
    script_path = out.with_suffix(".script.json")
    script_path.write_text(json.dumps(scenes_to_json(scenes), indent=2, ensure_ascii=False), encoding="utf-8")

    for n in notes:
        print(f"  note: {n}")
    print(f"\nDone in {time.time() - t0:.1f}s: {composer.total:.1f}s video")
    print(f"  video:   {out}")
    print(f"  preview: {preview}")
    print(f"  script:  {script_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except InputError as exc:
        print(f"\nInput problem: {exc}", file=sys.stderr)
        return 2
    except SetupError as exc:
        print(f"\nSetup problem: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:  # last resort: readable message instead of a traceback
        if args.debug:
            raise
        print(f"\nUnexpected error: {type(exc).__name__}: {exc}\n(re-run with --debug for details)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
