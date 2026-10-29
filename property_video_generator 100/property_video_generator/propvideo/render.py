"""Frame rendering: Ken Burns motion, text overlays and transitions, all with Pillow."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .script import Scene

FORMATS = {"landscape": (1280, 720), "vertical": (720, 1280), "square": (1080, 1080)}
TRANSITION = 0.6
KB_ZOOM = 0.12          # Ken Burns zoom amount
OVERSAMPLE = 1.3        # base image is kept larger than the frame so crops stay sharp

_FONT_PATHS = {
    "bold": ["/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
             "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
    "regular": ["/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf",
                "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "DejaVuSans.ttf", "arial.ttf", "Arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"],
}
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def load_font(kind: str, size: int):
    key = (kind, size)
    if key not in _font_cache:
        for candidate in _FONT_PATHS[kind]:
            try:
                _font_cache[key] = ImageFont.truetype(candidate, size)
                break
            except OSError:
                continue
        else:  # no TrueType font found: Pillow's built-in font still works
            _font_cache[key] = ImageFont.load_default(size=size)
    return _font_cache[key]


@dataclass
class Theme:
    accent: tuple[int, int, int] = (242, 107, 33)
    navy: tuple[int, int, int] = (27, 42, 87)
    white: tuple[int, int, int] = (255, 255, 255)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"colour must look like #F26B21, got '{value}'")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _ease(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and draw.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text: str, kind: str, size: int, max_w: int, max_lines: int):
    """Shrink the font until the text fits; ellipsise as a last resort."""
    s = size
    min_size = int(size * 0.55)
    while True:
        font = load_font(kind, s)
        lines = _wrap(draw, text, font, max_w)
        fits = len(lines) <= max_lines and all(draw.textlength(l, font=font) <= max_w for l in lines)
        if fits or s <= min_size:
            break
        s = int(s * 0.92)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.") + "…"
    return font, lines


class Layer:
    """An RGB picture plus an 'L' mask; drawing helpers write to both so alpha stays clean."""

    def __init__(self, size):
        self.rgb = Image.new("RGB", size, (0, 0, 0))
        self.mask = Image.new("L", size, 0)
        self.d_rgb = ImageDraw.Draw(self.rgb)
        self.d_mask = ImageDraw.Draw(self.mask)

    def text(self, xy, text, font, color, anchor="la"):
        self.d_rgb.text(xy, text, font=font, fill=color, anchor=anchor)
        self.d_mask.text(xy, text, font=font, fill=255, anchor=anchor)

    def rounded(self, box, radius, color, alpha=255):
        self.d_rgb.rounded_rectangle(box, radius, fill=color)
        self.d_mask.rounded_rectangle(box, radius, fill=alpha)

    def rect(self, box, color, alpha=255):
        self.d_rgb.rectangle(box, fill=color)
        self.d_mask.rectangle(box, fill=alpha)

    def vgradient(self, y0, y1, a0, a1, color=(0, 0, 0)):
        W = self.mask.size[0]
        for y in range(y0, y1):
            a = int(a0 + (a1 - a0) * (y - y0) / max(1, y1 - y0 - 1))
            self.d_rgb.line([(0, y), (W, y)], fill=color)
            self.d_mask.line([(0, y), (W, y)], fill=a)


def _paste(frame: Image.Image, layer: Layer, k: float = 1.0, dy: int = 0) -> None:
    mask = layer.mask
    if k < 1.0:
        mask = mask.point([int(v * k) for v in range(256)])
    frame.paste(layer.rgb, (0, dy), mask)


class SceneRenderer:
    def __init__(self, scene: Scene, size: tuple[int, int], theme: Theme, index: int, total: int):
        self.scene, self.theme = scene, theme
        self.W, self.H = size
        self.s = min(self.W, self.H) / 720
        self.zoom_in = index % 2 == 0
        self.pan_dir = 1 if index % 3 != 1 else -1
        self.base = self._load_base()
        self.static, self.text = self._build_layers(index, total)

    # -- background -------------------------------------------------------
    def _load_base(self) -> Image.Image:
        with Image.open(self.scene.image.path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
        target = (int(self.W * OVERSAMPLE), int(self.H * OVERSAMPLE))
        base = ImageOps.fit(im, target, Image.LANCZOS)
        if self.scene.kind == "cta":
            base = base.filter(ImageFilter.GaussianBlur(10 * self.s))
        return base

    def _background(self, p: float) -> Image.Image:
        z = 1 + KB_ZOOM * _ease(p) if self.zoom_in else 1 + KB_ZOOM * (1 - _ease(p))
        bw, bh = self.base.size
        cw, ch = bw / z, bh / z
        pan = self.pan_dir * (2 * p - 1) * 0.8
        cx = bw / 2 + pan * (bw - cw) / 2
        cy = bh / 2
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        return self.base.resize((self.W, self.H), Image.BILINEAR, box=box)

    # -- overlays ---------------------------------------------------------
    def _build_layers(self, index: int, total: int):
        W, H, s, th, sc = self.W, self.H, self.s, self.theme, self.scene
        static, text = Layer((W, H)), Layer((W, H))
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        margin = int(W * 0.07)
        max_w = W - 2 * margin

        if sc.kind == "title":
            static.vgradient(0, H, 110, 190)
            font, lines = _fit(probe, sc.headline, "bold", int(66 * s), max_w, 3)
            sub_font, sub_lines = _fit(probe, sc.sub, "regular", int(30 * s), max_w, 2) if sc.sub else (None, [])
            line_h = int(font.size * 1.25)
            block = len(lines) * line_h + (int(30 * s) + len(sub_lines) * int(sub_font.size * 1.4) if sub_lines else 0)
            y = int(H * 0.52 - block / 2)
            for ln in lines:
                text.text((W // 2, y), ln, font, th.white, "ma")
                y += line_h
            text.rect((W // 2 - int(50 * s), y + int(8 * s), W // 2 + int(50 * s), y + int(14 * s)), th.accent)
            y += int(34 * s)
            for ln in sub_lines:
                text.text((W // 2, y), ln, sub_font, (235, 235, 235), "ma")
                y += int(sub_font.size * 1.4)

        elif sc.kind == "price":
            static.vgradient(0, H, 150, 190)
            font, lines = _fit(probe, sc.headline, "bold", int(84 * s), max_w - int(80 * s), 2)
            label = load_font("regular", int(26 * s))
            text.text((W // 2, int(H * 0.30)), "PRICE", label, (235, 235, 235), "ma")
            line_h = int(font.size * 1.25)
            widest = max(probe.textlength(l, font=font) for l in lines)
            pad = int(36 * s)
            top = int(H * 0.30) + int(52 * s)
            box = (W / 2 - widest / 2 - pad, top, W / 2 + widest / 2 + pad, top + len(lines) * line_h + pad)
            text.rounded(box, int(24 * s), th.accent)
            y = top + pad // 2
            for ln in lines:
                text.text((W // 2, y), ln, font, th.white, "ma")
                y += line_h
            if sc.sub:
                sub_font, sub_lines = _fit(probe, sc.sub, "regular", int(28 * s), max_w, 2)
                y = int(box[3] + 36 * s)
                for ln in sub_lines:
                    text.text((W // 2, y), ln, sub_font, (235, 235, 235), "ma")
                    y += int(sub_font.size * 1.4)

        elif sc.kind == "cta":
            static.vgradient(0, H, 120, 120)
            font, lines = _fit(probe, sc.headline, "bold", int(54 * s), int(max_w * 0.8), 3)
            contact_lines: list[str] = []
            if sc.sub:
                for part in sc.sub.replace("\n", "|").split("|"):
                    contact_lines += [p for p in [part.strip()] if p]
            cfont = load_font("regular", int(30 * s))
            line_h = int(font.size * 1.25)
            clh = int(cfont.size * 1.6)
            card_h = len(lines) * line_h + int(60 * s) + len(contact_lines) * clh + int(60 * s)
            card_w = int(max_w * 0.9)
            x0, y0 = (W - card_w) // 2, int((H - card_h) / 2)
            text.rounded((x0, y0, x0 + card_w, y0 + card_h), int(28 * s), th.navy, 225)
            y = y0 + int(36 * s)
            for ln in lines:
                text.text((W // 2, y), ln, font, th.white, "ma")
                y += line_h
            text.rect((W // 2 - int(50 * s), y + int(6 * s), W // 2 + int(50 * s), y + int(12 * s)), th.accent)
            y += int(36 * s)
            for ln in contact_lines:
                f2, wrapped = _fit(probe, ln, "regular", int(30 * s), card_w - int(60 * s), 2)
                for w_line in wrapped:
                    text.text((W // 2, y), w_line, f2, (240, 240, 240), "ma")
                    y += int(f2.size * 1.6)

        else:  # feature / gallery: lower-third
            static.vgradient(int(H * 0.45), H, 0, 215)
            font, lines = _fit(probe, sc.headline, "bold", int(52 * s), max_w, 2)
            sub_font, sub_lines = _fit(probe, sc.sub, "regular", int(28 * s), max_w, 1) if sc.sub else (None, [])
            line_h = int(font.size * 1.25)
            block = len(lines) * line_h + (int(sub_font.size * 1.5) if sub_lines else 0)
            y = H - int(70 * s) - block
            text.rect((margin, y - int(26 * s), margin + int(64 * s), y - int(20 * s)), th.accent)
            for ln in lines:
                text.text((margin, y), ln, font, th.white)
                y += line_h
            for ln in sub_lines:
                text.text((margin, y + int(4 * s)), ln, sub_font, (225, 225, 225))
            if sc.kind == "feature":
                badge = load_font("bold", int(20 * s))
                static.rounded((margin, int(34 * s), margin + int(200 * s), int(34 * s) + int(40 * s)), int(20 * s), th.accent, 235)
                static.text((margin + int(100 * s), int(54 * s)), f"HIGHLIGHT {index}", badge, th.white, "mm")
        return static, text

    # -- output -----------------------------------------------------------
    def render(self, local_t: float, duration: float) -> Image.Image:
        p = local_t / duration if duration else 0
        frame = self._background(max(0.0, min(1.0, p)))
        _paste(frame, self.static, k=_ease(local_t / 0.4))
        k = _ease((local_t - 0.15) / 0.6)
        _paste(frame, self.text, k=k, dy=int((1 - k) * 36 * self.s))
        return frame


class Composer:
    """Lays scenes on a timeline (with overlapping transitions) and yields frames."""

    def __init__(self, scenes: list[Scene], size: tuple[int, int], fps: int, theme: Theme):
        self.scenes, self.size, self.fps, self.theme = scenes, size, fps, theme
        n = len(scenes)
        self.starts, t = [], 0.0
        for sc in scenes:
            self.starts.append(t)
            t += sc.duration - TRANSITION
        self.total = t + TRANSITION if n else 0.0
        highlight = 0
        self.renderers = []
        for i, sc in enumerate(scenes):
            if sc.kind == "feature":
                highlight += 1
            self.renderers.append(SceneRenderer(sc, size, theme, highlight if sc.kind == "feature" else i, n))

    @property
    def frame_count(self) -> int:
        return int(math.ceil(self.total * self.fps))

    def frame(self, t: float) -> Image.Image:
        W, H = self.size
        t = min(t, self.total - 1e-6)
        active = [i for i, sc in enumerate(self.scenes) if self.starts[i] <= t < self.starts[i] + sc.duration]
        if not active:
            active = [len(self.scenes) - 1]
        i = active[0]
        img = self.renderers[i].render(t - self.starts[i], self.scenes[i].duration)
        if len(active) > 1:
            j = active[1]
            nxt = self.renderers[j].render(t - self.starts[j], self.scenes[j].duration)
            a = _ease((t - self.starts[j]) / TRANSITION)
            if i % 2 == 0:                                   # cross-fade
                img = Image.blend(img, nxt, a)
            else:                                            # push-slide
                canvas = Image.new("RGB", (W, H))
                shift = int(a * W)
                canvas.paste(img, (-shift, 0))
                canvas.paste(nxt, (W - shift, 0))
                img = canvas
        # fade from/to black at the very start and end
        edge = min(t / 0.4, (self.total - t) / 0.6, 1.0)
        if edge < 1.0:
            img = Image.blend(Image.new("RGB", (W, H)), img, max(0.0, edge))
        # thin progress bar
        d = ImageDraw.Draw(img)
        d.rectangle((0, H - int(6 * min(W, H) / 720), int(W * t / self.total), H), fill=self.theme.accent)
        return img

    def frames(self):
        for n in range(self.frame_count):
            yield self.frame(n / self.fps)


def contact_sheet(composer: Composer, path: Path, thumb_w: int = 420) -> None:
    """Save one thumbnail per scene as a quick visual preview."""
    W, H = composer.size
    th = int(thumb_w * H / W)
    cols = min(3, len(composer.scenes))
    rows = math.ceil(len(composer.scenes) / cols)
    sheet = Image.new("RGB", (cols * (thumb_w + 8) + 8, rows * (th + 8) + 8), (24, 28, 40))
    for k, sc in enumerate(composer.scenes):
        t = composer.starts[k] + min(sc.duration - 0.3, 2.4)
        thumb = composer.frame(t).resize((thumb_w, th), Image.LANCZOS)
        sheet.paste(thumb, (8 + (k % cols) * (thumb_w + 8), 8 + (k // cols) * (th + 8)))
    sheet.save(path, quality=90)
