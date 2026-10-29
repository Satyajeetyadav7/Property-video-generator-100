"""Streamlit web app for the AI Property Video Generator.

Run locally:  streamlit run app.py
Deploy:       main file = app.py (see README / packages.txt for ffmpeg)
"""
import tempfile
from pathlib import Path

import streamlit as st

from propvideo import audio
from propvideo.models import InputError, property_from_dict
from propvideo.render import FORMATS, Composer, Theme, hex_to_rgb
from propvideo.script import BASE_DURATION, build_template_script, check_scenes
from propvideo.video import SetupError, encode_mp4, ensure_ffmpeg

st.set_page_config(page_title="AI Property Video Generator", page_icon="🏠", layout="wide")
st.title("🏠 AI Property Video Generator")
st.caption("Enter property details, upload 4-8 photos, get a promo video.")

left, right = st.columns([1, 1])

with left:
    name = st.text_input("Property name *", "Skyline Residency")
    location = st.text_input("Location", "Whitefield, Bengaluru")
    c1, c2 = st.columns(2)
    price = c1.text_input("Price", "₹78,50,000")
    ptype = c2.text_input("Property type", "2-BHK Apartment")
    features = st.text_area("Key features (one per line, max 5)",
                            "Two spacious bedrooms\nModular kitchen\nEast-facing balcony\nClubhouse and swimming pool")
    contact = st.text_input("Contact details", "+91 98765 43210 | hello@example-realty.com")
    cta = st.text_input("Call to action", "Book a site visit today")
    files = st.file_uploader("Photos * (jpg/png/webp, 4-8 recommended)",
                             type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    st.caption("Tip: name files like kitchen.jpg or bedroom.jpg so each feature gets the matching photo.")

with right:
    fmt = st.selectbox("Video format", list(FORMATS), format_func=lambda k: f"{k} {FORMATS[k][0]}x{FORMATS[k][1]}")
    accent = st.color_picker("Accent colour", "#F26B21")
    music = st.checkbox("Background music", True)
    narrate = st.checkbox("Voice narration (needs a TTS engine on the server)", False)
    go = st.button("Generate video", type="primary", use_container_width=True)

    if go:
        try:
            ensure_ffmpeg()
            with tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                paths = []
                for i, f in enumerate(files):
                    p = tmpdir / f"{i:02d}_{Path(f.name).name}"
                    p.write_bytes(f.getvalue())
                    paths.append(str(p))
                prop = property_from_dict({
                    "name": name, "location": location, "price": price, "property_type": ptype,
                    "features": features.splitlines(), "contact": contact, "cta": cta, "images": paths,
                }, base_dir=tmpdir)
                for w in prop.warnings:
                    st.warning(w)

                scenes = build_template_script(prop)
                for p_ in check_scenes(scenes, prop):
                    st.warning(p_)

                clips = [None] * len(scenes)
                if narrate:
                    clips, notes = audio.synthesize_narration([s.narration for s in scenes], tmpdir)
                    for n in notes:
                        st.info(n)
                    for sc, clip in zip(scenes, clips):
                        if clip is not None:
                            sc.duration = max(BASE_DURATION[sc.kind], len(clip) / audio.SR + 0.95)

                size, fps = FORMATS[fmt], 24
                composer = Composer(scenes, size, fps, Theme(accent=hex_to_rgb(accent)))
                narr = [(composer.starts[i] + 0.35, c) for i, c in enumerate(clips) if c is not None]
                wav = None
                if music or narr:
                    wav = tmpdir / "mix.wav"
                    audio.write_wav(wav, audio.mix_track(composer.total, audio.make_music(composer.total) if music else None, narr))

                bar = st.progress(0, text="Rendering video...")
                out = tmpdir / "property_video.mp4"
                encode_mp4(composer.frames(), size, fps, out, wav, composer.frame_count,
                           lambda d, t: bar.progress(min(1.0, d / max(1, t)), text=f"Rendering {d}/{t} frames"))
                bar.empty()
                data = out.read_bytes()
            st.session_state["video"] = data
        except (InputError, SetupError) as exc:
            st.error(str(exc))
        except Exception as exc:  # keep the app alive, show a readable message
            st.error(f"Unexpected error: {type(exc).__name__}: {exc}")

    if "video" in st.session_state:
        st.video(st.session_state["video"])
        st.download_button("Download MP4", st.session_state["video"], "property_video.mp4", "video/mp4",
                           use_container_width=True)
