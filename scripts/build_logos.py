"""Build the Elmify logo files from the brand masters.

The brand masters set the letters as live text in Geist Bold and load the font
with an @import. That does not survive real use: an SVG shown through <img>
cannot fetch fonts, and the app's Content-Security-Policy blocks the import, so
the letters fall back to whatever sans-serif the browser has. This script
outlines the letters into paths with the same geometry as the masters, so every
file renders identically everywhere.

    uv run --with fonttools --with uharfbuzz python scripts/build_logos.py \
        path/to/Geist-Bold.ttf   (npm package geist@1.7.2, dist/fonts/geist-sans)

Writes:
  web/public/brand/*.svg, web/app/icon.svg        (marketing site)
  web/app/_components/logo-paths.ts                (inline React logo)
  static/elmify/*.svg                              (Django app)
"""

from __future__ import annotations

import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent

INK = "#0F172A"
ACCENT = "#4F46E5"
ACCENT_ON_DARK = "#818CF8"
TILE_DARK = "#1E1B4B"
TILE_LINE = "#E2E8F0"

# Geometry copied from the brand masters (font-size 1000 = 1 unit per font unit).
WORDMARK_TEXT = "elmıfy"  # dotless i: the square is the dot
WORDMARK_VIEWBOX = "31.3 -720 2835.7 876.3"
WORDMARK_TRACKING = -35
WORDMARK_DOT = (1767.1, -720, 150)
MARK_DOT = (665, -150, 150)


def _shape(font_path: Path, text: str) -> list[tuple[str, float]]:
    blob = hb.Blob.from_file_path(str(font_path))
    hb_font = hb.Font(hb.Face(blob))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf, {"kern": True, "liga": False})
    out, x = [], 0.0
    names = TTFont(font_path).getGlyphOrder()
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True):
        out.append((names[info.codepoint], x + pos.x_offset))
        x += pos.x_advance + WORDMARK_TRACKING if len(text) > 1 else pos.x_advance
    return out


def _path(font: TTFont, glyphs: list[tuple[str, float]]) -> str:
    gs = font.getGlyphSet()
    pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
    for name, x in glyphs:
        # Font units are y-up; SVG is y-down with the baseline at y=0.
        gs[name].draw(TransformPen(pen, (1, 0, 0, -1, x, 0)))
    return pen.getCommands()


def _svg(view_box: str, w: int, h: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="{view_box}" role="img" aria-label="Elmify"><title>Elmify</title>{body}</svg>\n'
    )


def build(font_path: Path) -> None:
    font = TTFont(font_path)
    word_d = _path(font, _shape(font_path, WORDMARK_TEXT))
    e_d = _path(font, _shape(font_path, "e"))
    wx, wy, ws = WORDMARK_DOT
    mx, my, ms = MARK_DOT

    def wordmark(letters: str, dot: str) -> str:
        return _svg(
            WORDMARK_VIEWBOX, 207, 64,
            f'<path d="{word_d}" fill="{letters}"/>'
            f'<rect x="{wx}" y="{wy}" width="{ws}" height="{ws}" fill="{dot}"/>',
        )

    def e_group(letters: str, dot: str, transform: str) -> str:
        return (
            f'<g transform="{transform}"><path d="{e_d}" fill="{letters}"/>'
            f'<rect x="{mx}" y="{my}" width="{ms}" height="{ms}" fill="{dot}"/></g>'
        )

    def mark(letters: str, dot: str) -> str:
        big = "translate(3.3 811.8) scale(1.1738)"
        return _svg("0 0 1000 1000", 96, 96, e_group(letters, dot, big))

    inner = "translate(230.1 669.5) scale(0.638)"
    icon_light = _svg(
        "0 0 1000 1000", 512, 512,
        f'<rect x="4" y="4" width="992" height="992" rx="221" fill="#FFFFFF" '
        f'stroke="{TILE_LINE}" stroke-width="8"/>' + e_group(INK, ACCENT, inner),
    )
    icon_dark = _svg(
        "0 0 1000 1000", 512, 512,
        f'<rect width="1000" height="1000" rx="225" fill="{TILE_DARK}"/>'
        + e_group("#FFFFFF", ACCENT_ON_DARK, inner),
    )

    files = {
        "elmify-wordmark-light.svg": wordmark(INK, ACCENT),
        "elmify-wordmark-dark.svg": wordmark("#FFFFFF", ACCENT_ON_DARK),
        "elmify-mark-light.svg": mark(INK, ACCENT),
        "elmify-mark-dark.svg": mark("#FFFFFF", ACCENT_ON_DARK),
        "elmify-icon-light.svg": icon_light,
        "elmify-icon-dark.svg": icon_dark,
    }
    brand = ROOT / "web/public/brand"
    for old in brand.glob("*.svg"):
        old.unlink()
    for name, svg in files.items():
        (brand / name).write_text(svg)
    (ROOT / "web/app/icon.svg").write_text(icon_light)

    static = ROOT / "static/elmify"
    for old in ("elmify-wordmark-on-dark.svg",):
        (static / old).unlink(missing_ok=True)
    for name in ("elmify-wordmark-light.svg", "elmify-wordmark-dark.svg", "elmify-mark-light.svg"):
        (static / name).write_text(files[name])
    (static / "favicon.svg").write_text(icon_light)

    (ROOT / "web/app/_components/logo-paths.ts").write_text(
        "// Generated by scripts/build_logos.py. Do not edit.\n"
        "export const WORDMARK = {\n"
        f'  viewBox: "{WORDMARK_VIEWBOX}",\n'
        f'  d: "{word_d}",\n'
        f"  dot: {{ x: {wx}, y: {wy}, size: {ws} }},\n"
        "};\n\n"
        "export const MARK = {\n"
        '  viewBox: "0 0 1000 1000",\n'
        '  transform: "translate(3.3 811.8) scale(1.1738)",\n'
        f'  d: "{e_d}",\n'
        f"  dot: {{ x: {mx}, y: {my}, size: {ms} }},\n"
        "};\n"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]))
