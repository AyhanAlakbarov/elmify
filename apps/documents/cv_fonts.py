"""Which face a CV is set in, and which faces a rendered PDF actually embeds.

Spec: docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md §3.5.
Every face named here is a system font installed from a Debian package
(Dockerfile, ci.yml): render._RefusingFetcher refuses every file and URL
load, so a font that is not installed silently falls back to another face
with different letter widths -- and page counts gate BINDING max_pages.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader

from .constraints import ConstraintRule
from .schemas import CVContent

#: fonts-sil-charis 6.200 in Debian trixie names its family "Charis SIL".
DEFAULT_FAMILY = "Charis SIL"


def embedded_font_names(pdf_bytes: bytes) -> frozenset[str]:
    """The BaseFont names a PDF embeds, without the subset prefix ("ABCDEF+")."""
    names: set[str] = set()
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        resources = page.get("/Resources")
        fonts = resources.get_object().get("/Font") if resources is not None else None
        if fonts is None:
            continue
        for ref in fonts.get_object().values():
            base = str(ref.get_object().get("/BaseFont", "")).lstrip("/")
            if base:
                names.add(base.split("+", 1)[-1])
    return frozenset(names)


#: A font a programme names -> the installed, licensed face with the same
#: letter widths (so page limits measure the same document). Georgia is
#: absent on purpose: Gelasio has no Debian package (checked 2026-10-13).
LOOKALIKE: dict[str, str] = {
    "times new roman": "Liberation Serif",
    "times": "Liberation Serif",
    "arial": "Liberation Sans",
    "helvetica": "Liberation Sans",
    "calibri": "Carlito",
    "cambria": "Caladea",
    "garamond": "EB Garamond",
    "verdana": "DejaVu Sans",
}

#: The student-alphabet codepoints (Azerbaijani/Turkish letters, Russian
#: Cyrillic block) each look-alike LACKS. A static table: nothing reads font
#: files at render time. tests/documents/test_cv_fonts.py checks it against
#: the installed files, so a wrong entry fails CI. Liberation and DejaVu lack
#: none of them.
_AZ_TR = "ƏəĞğİıŞşÇçÖöÜü"
ALPHABET: frozenset[int] = frozenset(
    {ord(c) for c in _AZ_TR} | set(range(0x400, 0x500))
)
LACKS: dict[str, tuple[tuple[int, int], ...]] = {
    "Carlito": ((0x476, 0x476), (0x487, 0x487)),
    "Caladea": ((0x18F, 0x18F), (0x259, 0x259), (0x400, 0x4FF)),
    "EB Garamond": (
        (0x18F, 0x18F), (0x259, 0x259), (0x460, 0x461), (0x464, 0x48F),
        (0x492, 0x4AD), (0x4B2, 0x4CF), (0x4E0, 0x4E1), (0x4F6, 0x4FF),
    ),
}
#: Same-style Liberation face to fall back to.
REPLACEMENT: dict[str, str] = {
    "Carlito": "Liberation Sans",
    "Caladea": "Liberation Serif",
    "EB Garamond": "Liberation Serif",
}

DEFAULT_PT = 11.0
_SIZE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d)?)\s*(?:pt|points?)?\b", re.IGNORECASE)
_SIZE_WORDS = re.compile(
    r"\b(?:font\s+size|size|minimum|maximum|min|max|font|at\s+least|points?)\b",
    re.IGNORECASE,
)


def _missing(face: str, text: str) -> list[str]:
    ranges = LACKS.get(face, ())
    return sorted({c for c in text if any(lo <= ord(c) <= hi for lo, hi in ranges)})


@dataclass(frozen=True)
class FontChoice:
    family: str
    pt: float
    note: str | None = None


def parse_font_rule(value: object) -> tuple[str | None, float | None]:
    """Split a page's printed font detail into (family, point size)."""
    text = str(value or "").strip()
    match = _SIZE.search(text)
    size = float(match.group(1)) if match else None
    family = _SIZE_WORDS.sub("", _SIZE.sub("", text)).strip(" ,;:-") or None
    return family, size


def choose_font(rule: ConstraintRule | None, content: CVContent) -> FontChoice:
    """The face and size a CV renders in (spec 3.5).

    The family is only ever a value from LOOKALIKE or DEFAULT_FAMILY: the
    rule's text is third-party page content and goes into a <style> block,
    so it is looked up, never copied.
    """
    if rule is None:
        return FontChoice(DEFAULT_FAMILY, DEFAULT_PT)
    named, size = parse_font_rule(rule.value)
    ok = size is not None and 9.0 <= size <= 14.0
    pt = size if ok and size is not None else DEFAULT_PT
    size_note = (
        f"programme names size {size:g} pt, outside 9-14 pt; ignored, the CV keeps {pt:g} pt"
        if size is not None and not ok
        else None
    )
    if named is None:
        return FontChoice(DEFAULT_FAMILY, pt, size_note)
    # "Arial or Times New Roman": the first alternative we have a face for.
    alternatives = re.split(r"\s+or\s+|\s+and\s+|[,/&]", named, flags=re.IGNORECASE)
    named = next((a.strip() for a in alternatives if a.strip().casefold() in LOOKALIKE), named)
    face = LOOKALIKE.get(named.casefold())
    if face is None:
        return FontChoice(
            DEFAULT_FAMILY,
            pt,
            f"programme names {named!r}; no licensed look-alike is installed, "
            f"so the CV keeps {DEFAULT_FAMILY}",
        )
    missing = _missing(face, content.model_dump_json())
    if missing:
        replacement = REPLACEMENT[face]
        return FontChoice(
            replacement,
            pt,
            f"programme names {named!r}; its look-alike {face} lacks "
            f"{' '.join(missing[:8])}, so the CV uses {replacement}",
        )
    return FontChoice(face, pt, size_note)
