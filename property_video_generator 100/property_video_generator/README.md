# AI Property Video Generator

Turns property details and 4-8 photos into a short, ready-to-share MP4 (opening title, feature scenes,
price scene, closing enquiry card) with no manual video editing.

```
python generate_video.py --input sample/property.json --output output/sample_video.mp4
```

A finished example is in `output/sample_video.mp4` (27 s, 1280x720, with background music), next to a
`.preview.jpg` contact sheet of every scene and a `.script.json` showing the exact text used.

## Setup

Requirements: Python 3.10+ and **ffmpeg** on your PATH.

```bash
# ffmpeg: macOS `brew install ffmpeg` | Ubuntu `sudo apt install ffmpeg` | Windows `winget install ffmpeg`
pip install -r requirements.txt        # Pillow + numpy
python sample/make_sample_images.py    # only needed if sample/images is missing
python generate_video.py -i sample/property.json
```

## Web app (Streamlit)

```bash
pip install -r requirements.txt
streamlit run app.py
```
To deploy on Streamlit Community Cloud: push this folder to GitHub, set the main file to `app.py`.
`packages.txt` installs ffmpeg (and espeak-ng for narration) on the server.

## Usage

| Goal | Command |
|---|---|
| From a JSON file | `python generate_video.py -i sample/property.json -o output/video.mp4` |
| Answer prompts (a simple form) | `python generate_video.py --interactive` |
| Use every photo in a folder | `python generate_video.py -i sample/property.json --images-dir ~/photos/flat12` |
| Vertical for Reels/Shorts | `--format vertical` (also `square`, default `landscape`) |
| Spoken voice-over | `--narrate` (needs a local TTS engine, see below) |
| Brand colour / no music | `--accent "#1B2A57"` / `--no-music` |
| LLM-reworded voice-over | `--ai` (needs `ANTHROPIC_API_KEY`, see below) |

### Input format (`sample/property.json`)

Only `name` and at least one readable image are required. Everything else is optional.

```json
{
  "name": "Skyline Residency", "location": "Whitefield, Bengaluru",
  "price": "₹78,50,000",            // text as you want it shown, or a number (formatted as ₹78,50,000)
  "property_type": "2-BHK Apartment",
  "features": ["Two spacious bedrooms", "Modular kitchen"],   // first 5 are used
  "contact": "+91 98765 43210 | hello@example-realty.com",
  "cta": "Book a site visit today",
  "images": [{"path": "images/02_living_room.jpg", "caption": "Living room"}, "images/03_kitchen.jpg"]
}
```

Image paths are relative to the JSON file. Captions are optional and are also used to match photos to features.

### Output

`output/<name>.mp4` (H.264 + AAC, plays anywhere, `faststart` for web/WhatsApp), `<name>.preview.jpg`
(one thumbnail per scene, the quick preview) and `<name>.script.json` (all text, per scene).

## How it works

1. **Validate** (`models.py`): required fields, readable images; problems the tool can work around become
   warnings, the rest stop with a plain-language message (exit code 2) instead of a traceback.
2. **Write the script** (`script.py`): deterministic template logic builds the storyboard
   (title -> up to 5 feature scenes -> optional gallery -> price -> enquiry) plus a voice-over line per scene.
   Each feature is paired with the best-matching photo by comparing words in the feature text with the
   photo's caption and filename ("Modular kitchen" -> `kitchen.jpg`); unmatched features take the next unused photo.
3. **Fact check**: every number and capitalised name in the on-screen text and voice-over must appear in the
   supplied input, otherwise it is reported. This runs on template text and on any LLM text.
4. **Render** (`render.py`): Pillow draws each frame: Ken Burns zoom/pan, gradient scrims, wrapped and auto-shrunk
   text (so long names never overflow), animated text entrance, alternating cross-fade / push-slide transitions,
   fades at the ends, and a progress bar.
5. **Audio** (`audio.py`): original background music is synthesised in code (no licensed files); optional
   narration clips are laid on the timeline and each scene is lengthened to fit its speech.
6. **Export** (`video.py`): frames are piped to ffmpeg.

### Graceful handling

| Situation | Behaviour |
|---|---|
| Image missing / corrupt / wrong type | skipped with a warning; stops only if none are usable |
| < 4 photos | warning, shorter video; 1 photo works |
| > 8 photos / > 5 features | extras ignored, with a warning |
| No price / location / contact / features | that scene or text is left out; features missing -> photo gallery |
| Very long text | font shrinks, then ellipsis |
| Bad JSON, bad colour, ffmpeg missing | readable message, exit code 2 / 3 |

## What AI is used, and how it is checked

- **Default: no AI model.** A rule-based template writer is used on purpose: it is fast, free, offline, and cannot
  invent facts, which matters for listings. It only reuses supplied text. The only wording not taken from the input
  is connective phrasing ("Highlights include...") and, if you give no `cta`, the generic "Book a visit today".
- **Optional `--ai`:** sends the supplied facts and the draft voice-over lines to an Anthropic model
  (`claude-sonnet-5-5`) and asks for smoother wording using only those facts. Each returned line is run through the
  same fact checker and **discarded in favour of the template line** if it adds a number or name not in the input,
  or if the call fails. Only text is sent; no images, no personal data beyond the listing fields you supplied.
  Set `ANTHROPIC_API_KEY` in your environment (never commit it) and `pip install anthropic`.
- **Narration (`--narrate`)** uses a local engine, not a cloud service: `espeak-ng`/`espeak` (Linux),
  `say` (macOS), or any command via `PVG_TTS_CMD`, for example
  `PVG_TTS_CMD='mytts --out {out} --text {text}'` (the tool replaces `{out}` and `{text}`).
  Rupee amounts are read naturally ("78.5 lakh rupees"). With no engine found, you get a clear note and the video is
  made with captions and music.

### Libraries / services used

Pillow (frames, text), numpy (music and audio mixing), ffmpeg (H.264/AAC encoding), Poppins/DejaVu fonts if installed
on the machine (falls back to Pillow's default font), optional `anthropic` SDK, optional local TTS. Sample photos are
**synthetic illustrations** generated by `sample/make_sample_images.py`; the sample listing is invented. No real
customer data, passwords or keys are in this project.

## Tests

```bash
pip install pytest && python -m pytest -q     # 11 tests: validation, matching, fact check, end-to-end CLI
```

## Limitations and next steps

- Quality tested here: the default path (template script, music, captions, all three aspect ratios) and narration
  mixing with a stand-in TTS command. Not run in this environment: a real speech engine and the `--ai` call
  (no engine or API key available), so test those on your machine first.
- `espeak` voices sound robotic; for production use a cloud/neural TTS through `PVG_TTS_CMD`.
- Photo-to-feature matching is keyword based; it needs captions or descriptive filenames to beat plain ordering.
- English only; the fact checker flags numbers and capitalised names, it cannot judge adjectives
  ("spacious") that are not in the input.
- Rendering is CPU-only Python: about 12 s for a 27 s 720p video. Larger resolutions or longer videos scale linearly.
- Next steps: web form (Streamlit), batch mode over a CSV of listings, logo/watermark support, per-room auto-captioning with a vision model.
