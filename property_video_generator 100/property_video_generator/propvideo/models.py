"""Input model and validation for a property listing.

Anything the user can fix (missing name, no usable images, bad JSON) raises
``InputError`` with a plain-language message. Anything we can work around
(missing price, a broken image path) becomes a warning and the video is still made.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

MAX_IMAGES = 8
MIN_RECOMMENDED_IMAGES = 4
MAX_FEATURES = 5
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class InputError(Exception):
    """A problem with the supplied input that the user can fix."""


@dataclass
class ImageRef:
    path: Path
    caption: str | None = None


@dataclass
class Property:
    name: str
    location: str | None = None
    price: str | None = None
    property_type: str | None = None
    features: list[str] = field(default_factory=list)
    contact: str | None = None
    cta: str | None = None
    images: list[ImageRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def facts_text(self) -> str:
        """Every fact the user supplied, as one string. Used to check generated text."""
        parts = [self.name, self.location, self.price, self.property_type,
                 self.contact, self.cta, *self.features]
        parts += [i.caption for i in self.images]
        return " ".join(p for p in parts if p)


def format_price(value: Any, currency: str = "₹") -> str:
    """Numbers become '₹78,50,000' (Indian grouping); strings are used as typed."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        digits = str(abs(int(round(value))))
        if len(digits) > 3:
            head, tail = digits[:-3], digits[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            digits = ",".join(groups + [tail])
        return f"{currency}{digits}"
    return str(value).strip()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _check_image(path: Path) -> str | None:
    """Return a problem description, or None if the image is usable."""
    if not path.exists():
        return "file not found"
    if not path.is_file():
        return "not a file"
    try:
        with Image.open(path) as im:
            im.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return "not a readable image"
    return None


def collect_images_from_dir(folder: Path) -> list[str]:
    if not folder.is_dir():
        raise InputError(f"Images folder not found: {folder}")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not files:
        raise InputError(f"No images (jpg/png/webp) found in {folder}")
    return [str(p) for p in files]


def property_from_dict(data: dict, base_dir: Path | None = None) -> Property:
    if not isinstance(data, dict):
        raise InputError("Property data must be a JSON object with fields like name, location, images.")
    base_dir = base_dir or Path.cwd()
    warnings: list[str] = []

    name = _clean(data.get("name"))
    if not name:
        raise InputError("The property needs a 'name' (for example \"Skyline Residency 2-BHK\").")

    location = _clean(data.get("location"))
    if not location:
        warnings.append("No location given; the location will be left out of the video.")

    currency = _clean(data.get("currency")) or "₹"
    price = None
    if data.get("price") not in (None, ""):
        price = format_price(data["price"], currency)
    else:
        warnings.append("No price given; the price scene will be skipped.")

    contact = _clean(data.get("contact"))
    if not contact:
        warnings.append("No contact details given; the closing scene will show the call-to-action only.")

    raw_features = data.get("features") or []
    if isinstance(raw_features, str):
        raw_features = [f for f in raw_features.replace("\n", ",").split(",")]
    features = [f for f in (_clean(f) for f in raw_features) if f]
    if not features:
        warnings.append("No key features given; images will be shown as a simple gallery.")
    elif len(features) > MAX_FEATURES:
        warnings.append(f"{len(features)} features given; only the first {MAX_FEATURES} are used to keep the video short.")
        features = features[:MAX_FEATURES]

    images: list[ImageRef] = []
    raw_images = data.get("images") or []
    if isinstance(raw_images, (str, Path)):
        raw_images = [raw_images]
    for entry in raw_images:
        caption = None
        if isinstance(entry, dict):
            raw_path, caption = entry.get("path"), _clean(entry.get("caption"))
        else:
            raw_path = entry
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        problem = _check_image(path)
        if problem:
            warnings.append(f"Skipped image '{raw_path}': {problem}.")
            continue
        images.append(ImageRef(path, caption))

    if not images:
        raise InputError(
            "No usable images. Provide 4-8 photos in 'images' (jpg/png/webp) or use --images-dir. "
            + (f"{len([w for w in warnings if w.startswith('Skipped')])} image(s) were skipped; see messages above."
               if raw_images else "None were listed.")
        )
    if len(images) > MAX_IMAGES:
        warnings.append(f"{len(images)} images given; only the first {MAX_IMAGES} are used.")
        images = images[:MAX_IMAGES]
    if len(images) < MIN_RECOMMENDED_IMAGES:
        warnings.append(f"Only {len(images)} usable image(s); 4-8 gives the best result. The video will be shorter.")

    return Property(
        name=name, location=location, price=price,
        property_type=_clean(data.get("property_type")),
        features=features, contact=contact, cta=_clean(data.get("cta")),
        images=images, warnings=warnings,
    )


def load_property(path: str | Path, images_dir: str | Path | None = None) -> Property:
    path = Path(path)
    if not path.exists():
        raise InputError(f"Input file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from exc
    if images_dir:
        data["images"] = collect_images_from_dir(Path(images_dir))
    return property_from_dict(data, base_dir=path.parent)
