"""Storyboard + voice-over script writer.

Default path is deterministic template logic that only reuses the supplied facts.
An optional LLM pass (``--ai``) may reword the voice-over, but every sentence it
returns is checked against the input facts and discarded if it adds anything new.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict

from .models import ImageRef, Property

MAX_GALLERY_EXTRA = 2

BASE_DURATION = {"title": 4.0, "feature": 4.0, "gallery": 3.2, "price": 3.5, "cta": 4.5}


@dataclass
class Scene:
    kind: str            # title | feature | gallery | price | cta
    image: ImageRef
    headline: str
    sub: str = ""
    narration: str = ""
    duration: float = 4.0

    def text_blob(self) -> str:
        # ". " keeps each field a separate sentence for the capitalised-name check
        return ". ".join(p for p in (self.headline, self.sub, self.narration) if p)


# ---------------------------------------------------------------- template writer

_FEATURE_LINES = [
    "Highlights include {f}.",
    "You will also find {f}.",
    "Plus, {f}.",
    "Do not miss {f}.",
    "And of course, {f}.",
]


def _decap(text: str) -> str:
    """Lower-case the first letter for mid-sentence use, unless it starts an acronym/proper form."""
    first = text.split(" ", 1)[0]
    if len(first) > 1 and (first[1:].upper() == first[1:] or any(c.isdigit() for c in first)):
        return text
    return text[0].lower() + text[1:]


def _cap(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


_STOP = {"and", "the", "with", "for", "all", "our", "your", "has", "have"}


def _tokens(text: str) -> set[str]:
    """Lower-case word stems (plural 's' removed) used for feature-to-photo matching."""
    return {re.sub(r"s$", "", w) for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2} - _STOP


def assign_images(features: list[str], pool: list[ImageRef]) -> list[ImageRef]:
    """Pair each feature with a photo: keyword match first, then unused photos in order."""
    chosen: list[ImageRef | None] = [None] * len(features)
    taken: set[int] = set()
    scores = []
    for fi, feat in enumerate(features):
        ft = _tokens(feat)
        for ii, img in enumerate(pool):
            overlap = len(ft & (_tokens(img.caption or "") | _tokens(img.path.stem)))
            if overlap:
                scores.append((overlap, fi, ii))
    for _, fi, ii in sorted(scores, key=lambda s: (-s[0], s[1], s[2])):
        if chosen[fi] is None and ii not in taken:
            chosen[fi], _ = pool[ii], taken.add(ii)
    free = [ii for ii in range(len(pool)) if ii not in taken]
    cycle = 0
    for fi in range(len(features)):
        if chosen[fi] is None:
            if free:
                ii = free.pop(0)
                taken.add(ii)
            else:                       # more features than photos: reuse photos
                ii = cycle % len(pool)
                cycle += 1
            chosen[fi] = pool[ii]
    return chosen  # type: ignore[return-value]


def build_template_script(prop: Property) -> list[Scene]:
    imgs = prop.images
    scenes: list[Scene] = []

    # 1. opening title
    sub_bits = [b for b in (prop.property_type, prop.location) if b]
    intro = f"Introducing {prop.name}"
    if prop.property_type and prop.location:
        intro += f", a {_decap(prop.property_type)} in {prop.location}."
    elif prop.property_type:
        intro += f", a {_decap(prop.property_type)}."
    elif prop.location:
        intro += f", in {prop.location}."
    else:
        intro += "."
    scenes.append(Scene("title", imgs[0], prop.name, "  |  ".join(sub_bits), intro))

    # 2. feature scenes: each feature gets the photo that best matches it (by caption/file name),
    #    otherwise the next unused photo
    pool = imgs[1:] or imgs
    chosen = assign_images(prop.features, pool)
    for i, (feat, img) in enumerate(zip(prop.features, chosen)):
        scenes.append(Scene(
            "feature", img, _cap(feat), img.caption or "",
            _FEATURE_LINES[i % len(_FEATURE_LINES)].format(f=_decap(feat)),
        ))

    # 3. leftover photos become gallery scenes so every supplied image can appear
    leftover = [im for im in pool if not any(im is c for c in chosen)]
    for img in leftover[: MAX_GALLERY_EXTRA if prop.features else 4]:
        headline = img.caption or prop.name
        sub = "" if img.caption else (prop.location or "")
        scenes.append(Scene("gallery", img, headline, sub, f"{img.caption}." if img.caption else ""))

    # 4. price
    if prop.price:
        sub = "  |  ".join(b for b in (prop.property_type, prop.location) if b)
        scenes.append(Scene("price", imgs[0], prop.price, sub, f"Priced at {prop.price}."))

    # 5. closing call to action
    cta = prop.cta or "Book a visit today"
    narr = f"{_cap(cta.rstrip('.!'))}."
    if prop.contact:
        narr += f" Contact {prop.contact}."
    scenes.append(Scene("cta", imgs[-1] if len(imgs) > 1 else imgs[0], cta, prop.contact or "", narr))

    for s in scenes:
        s.duration = BASE_DURATION[s.kind]
    return scenes


# ---------------------------------------------------------------- grounding check

_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_ALLOWED_CAPS = {"i", "a"}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(text)}


def ungrounded_terms(text: str, facts: str) -> list[str]:
    """Numbers and capitalised names in ``text`` that do not appear in ``facts``."""
    problems = [f"number {n}" for n in sorted(_numbers(text) - _numbers(facts))]
    fact_words = set(re.findall(r"[a-z]+", facts.lower()))
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = re.findall(r"[A-Za-z][A-Za-z'’-]*", sentence)
        for w in words[1:]:
            if w[0].isupper() and w.lower() not in fact_words and w.lower() not in _ALLOWED_CAPS:
                problems.append(f"name '{w}'")
    return problems


def check_scenes(scenes: list[Scene], prop: Property) -> list[str]:
    facts = prop.facts_text()
    report = []
    for i, s in enumerate(scenes, 1):
        bad = ungrounded_terms(s.text_blob(), facts)
        if bad:
            report.append(f"Scene {i} ({s.kind}) contains terms not in the input: {', '.join(bad)}")
    return report


# ---------------------------------------------------------------- optional LLM pass

def refine_with_llm(scenes: list[Scene], prop: Property, model: str = "claude-sonnet-5-5") -> tuple[list[Scene], list[str]]:
    """Reword the voice-over with an LLM, keeping only lines that pass the grounding check."""
    notes: list[str] = []
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return scenes, ["--ai requested but ANTHROPIC_API_KEY is not set; using template script."]
    try:
        import anthropic
    except ImportError:
        return scenes, ["--ai requested but the 'anthropic' package is not installed; using template script."]

    facts = {
        "name": prop.name, "location": prop.location, "price": prop.price,
        "type": prop.property_type, "features": prop.features,
        "contact": prop.contact, "cta": prop.cta,
    }
    prompt = (
        "You write short voice-over lines for a real-estate promo video.\n"
        "Rewrite each draft line to sound natural and warm, at most 18 words.\n"
        "STRICT RULES: use only facts in FACTS. Do not add numbers, names, amenities, "
        "distances, or claims that are not in FACTS. Keep any number exactly as written.\n"
        f"FACTS: {json.dumps(facts, ensure_ascii=False)}\n"
        f"DRAFT LINES: {json.dumps([s.narration for s in scenes], ensure_ascii=False)}\n"
        "Return ONLY a JSON array of strings, one per draft line, same order and length."
    )
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(model=model, max_tokens=800,
                                      messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        lines = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        if not isinstance(lines, list) or len(lines) != len(scenes):
            raise ValueError("model returned the wrong number of lines")
    except Exception as exc:  # network, auth, parse errors: fall back, never crash
        return scenes, [f"LLM step failed ({type(exc).__name__}: {exc}); using template script."]

    allowed = prop.facts_text()
    kept = 0
    for scene, new in zip(scenes, lines):
        new = str(new).strip()
        bad = ungrounded_terms(new, allowed)
        if not new or len(new.split()) > 30:
            continue
        if bad:
            notes.append(f"Rejected LLM line for scene '{scene.kind}' (not grounded: {', '.join(bad)}).")
            continue
        scene.narration = new
        kept += 1
    notes.append(f"LLM reworded {kept} of {len(scenes)} voice-over lines; the rest kept the template wording.")
    return scenes, notes


def scenes_to_json(scenes: list[Scene]) -> list[dict]:
    out = []
    for s in scenes:
        d = asdict(s)
        d["image"] = str(s.image.path)
        out.append(d)
    return out
