import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from propvideo import audio  # noqa: E402
from propvideo.models import InputError, format_price, property_from_dict  # noqa: E402
from propvideo.script import build_template_script, check_scenes, ungrounded_terms  # noqa: E402


@pytest.fixture()
def images(tmp_path):
    paths = []
    for name in ["exterior", "living_room", "kitchen", "bedroom", "balcony"]:
        p = tmp_path / f"{name}.png"
        Image.new("RGB", (400, 300), (120, 140, 160)).save(p)
        paths.append(str(p))
    return paths


def base(imgs, **over):
    data = {
        "name": "Test Heights", "location": "Pune", "price": 5000000,
        "property_type": "3-BHK Apartment",
        "features": ["Modular kitchen", "Private terrace", "Gym"],
        "contact": "+91 90000 11111", "cta": "Call now", "images": imgs,
    }
    data.update(over)
    return data


def test_price_formatting_uses_indian_grouping():
    assert format_price(7850000) == "₹78,50,000"
    assert format_price("$450,000") == "$450,000"


def test_missing_name_is_an_input_error(images):
    with pytest.raises(InputError, match="name"):
        property_from_dict(base(images, name=""))


def test_no_usable_images_is_an_input_error(tmp_path):
    with pytest.raises(InputError, match="No usable images"):
        property_from_dict(base([], images=[str(tmp_path / "nope.jpg")]))


def test_corrupt_image_is_skipped_with_warning(images, tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_text("not an image")
    prop = property_from_dict(base(images, images=[*images, str(bad)]))
    assert len(prop.images) == len(images)
    assert any("bad.jpg" in w for w in prop.warnings)


def test_missing_optional_fields_only_warn(images):
    prop = property_from_dict(base(images, price=None, contact=None, features=[], location=None))
    scenes = build_template_script(prop)
    kinds = [s.kind for s in scenes]
    assert "price" not in kinds and kinds[0] == "title" and kinds[-1] == "cta"
    assert len(prop.warnings) >= 4


def test_feature_photo_matching_by_filename(images):
    prop = property_from_dict(base(images, features=["Modular kitchen", "Cosy bedroom"]))
    scenes = [s for s in build_template_script(prop) if s.kind == "feature"]
    assert scenes[0].image.path.stem == "kitchen"
    assert scenes[1].image.path.stem == "bedroom"


def test_template_script_adds_no_new_facts(images):
    prop = property_from_dict(base(images))
    assert check_scenes(build_template_script(prop), prop) == []


def test_grounding_check_catches_invented_facts():
    facts = "Test Heights Pune 3-BHK Apartment Modular kitchen"
    assert ungrounded_terms("Only 2 km from the Metro station.", facts)
    assert ungrounded_terms("A modular kitchen in Pune.", facts) == []


def test_speakable_price():
    assert "78.5 lakh rupees" in audio.speakable("Priced at ₹78,50,000.")


def test_music_has_right_length_and_range():
    m = audio.make_music(5.0)
    assert len(m) == 5 * audio.SR and abs(m).max() <= 0.61


def test_cli_end_to_end_and_bad_input_exit_code(tmp_path):
    out = tmp_path / "v.mp4"
    sample = ROOT / "sample" / "property.json"
    r = subprocess.run([sys.executable, str(ROOT / "generate_video.py"), "-i", str(sample), "-o", str(out),
                        "--fps", "10"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert out.stat().st_size > 10_000

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"location": "x"}))
    r = subprocess.run([sys.executable, str(ROOT / "generate_video.py"), "-i", str(bad), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "name" in r.stderr and "Traceback" not in r.stderr
