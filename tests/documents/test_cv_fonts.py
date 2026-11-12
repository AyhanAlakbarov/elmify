import pytest

from apps.documents.constraints import ConstraintRule, Enforcement
from apps.documents.cv_fonts import (
    DEFAULT_FAMILY,
    choose_font,
    embedded_font_names,
    parse_font_rule,
)
from apps.documents.render import render_cv, render_cv_with_warnings, render_html_to_artifact
from apps.documents.schemas import EducationEntry
from tests.documents.test_render import _content

_INSTALL_HINT = (
    "Charis SIL is not installed, so the CV rendered in a fallback face with different "
    "page counts. Install fonts-sil-charis (CI does; locally see "
    "docs/superpowers/plans/2026-10-13-cv-stage-1-layout-and-typography.md, Task 3 Step 1)."
)


def _faces(artifact):
    return embedded_font_names(artifact.pdf_bytes)


@pytest.mark.parametrize("variant", ["STANDARD", "GERMAN_TABULAR", "EUROPASS"])
def test_the_default_face_is_charis_and_nothing_else(variant):
    faces = _faces(render_cv(_content(), variant=variant))
    assert any("Charis" in face for face in faces), _INSTALL_HINT
    assert not any("DejaVu" in face or "Noto" in face for face in faces), faces


def test_every_letter_our_students_write_is_in_all_four_charis_styles():
    sample = "Ə ə Ğ ğ İ ı Ş ş Ç ç Ö ö Ü ü — Привет, Жанна Щукина — Straße — Élève, cœur"
    # regular (summary), bold (degree_as_awarded), italic (degree_english gloss)
    education = (
        EducationEntry(
            degree_as_awarded=sample, degree_english=sample + " X",
            institution_original=sample, city="Berlin", country="DE", start_date="2020-09-01",
        ),
    )
    artifact = render_cv(_content(summary=sample, education=education), variant="STANDARD")
    # bold italic has no spot in any template, so it is set by hand
    bold_italic = render_html_to_artifact(
        '<html><body style="font-family: \'Charis SIL\'; font-weight: bold; font-style: italic">'
        f"<p>{sample}</p></body></html>",
        variant="STANDARD",
    )
    faces = _faces(artifact) | _faces(bold_italic)
    assert faces and all("Charis" in f for f in faces), (faces, _INSTALL_HINT)
    four = {"Charis-SIL", "Charis-SIL-Bold", "Charis-SIL-Italic", "Charis-SIL-Bold-Italic"}
    assert faces == four, (faces, _INSTALL_HINT)


def test_default_family_is_the_installed_debian_name():
    assert DEFAULT_FAMILY == "Charis SIL"


def _font_rule(value):
    return ConstraintRule(
        rule_id="P-FONT", key="font", value=value,
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="Use Times New Roman, 12 pt.", source_url="", scope="PROGRAMME",
    )


@pytest.mark.parametrize(("value", "expected"), [
    ("Arial", ("Arial", None)),
    ("11", (None, 11.0)),
    ("Times New Roman, 12 pt", ("Times New Roman", 12.0)),
    ("Calibri 11pt", ("Calibri", 11.0)),
])
def test_parse_font_rule(value, expected):
    assert parse_font_rule(value) == expected


@pytest.mark.parametrize(("named", "face"), [
    ("Times New Roman", "Liberation Serif"), ("Arial", "Liberation Sans"),
    ("Helvetica", "Liberation Sans"), ("Calibri", "Carlito"), ("Cambria", "Caladea"),
    ("Garamond", "EB Garamond"), ("Verdana", "DejaVu Sans"),
])
def test_a_named_font_maps_to_its_licensed_lookalike(named, face):
    assert choose_font(_font_rule(named), _content()).family == face


def test_a_font_with_no_lookalike_keeps_the_default_and_says_so():
    choice = choose_font(_font_rule("Georgia"), _content())
    assert choice.family == "Charis SIL"
    assert "Georgia" in choice.note


def test_page_text_never_reaches_the_css():
    choice = choose_font(_font_rule("Arial; } body { display:none"), _content())
    assert choice.family == "Charis SIL"


def test_caladea_gives_way_to_liberation_serif_for_cyrillic():
    choice = choose_font(_font_rule("Cambria"), _content(summary="Жанна Щукина"))
    assert choice.family == "Liberation Serif"
    assert "Caladea" in choice.note and "Ж" in choice.note


@pytest.mark.parametrize(("named", "face"), [
    ("Cambria", "Liberation Serif"), ("Garamond", "Liberation Serif"),
    ("Calibri", "Carlito"),
])
def test_schwa_falls_back_only_where_the_face_lacks_it(named, face):
    choice = choose_font(_font_rule(named), _content(summary="Əli Məmmədov"))
    assert choice.family == face
    assert (choice.note is None) == (face == "Carlito")
    if choice.note:
        assert "Ə" in choice.note


@pytest.mark.parametrize(("value", "expected"), [
    ("size 12", (None, 12.0)),
    ("minimum 11 pt", (None, 11.0)),
    ("Arial, font size 12", ("Arial", 12.0)),
    ("140", (None, 140.0)),
])
def test_parse_font_rule_strips_size_words(value, expected):
    assert parse_font_rule(value) == expected


def test_an_out_of_range_size_is_ignored_and_said():
    choice = choose_font(_font_rule("Arial, 140"), _content())
    assert choice.pt == 11.0 and "140" in choice.note
    assert "outside" in choose_font(_font_rule("size 30"), _content()).note


def test_the_lacks_table_matches_the_installed_font_files():
    import subprocess

    from fontTools.ttLib import TTFont

    from apps.documents.cv_fonts import ALPHABET, LACKS, LOOKALIKE, REPLACEMENT

    for face in set(LOOKALIKE.values()) | set(REPLACEMENT.values()):
        path = subprocess.check_output(["fc-match", "-f", "%{file}", face], text=True)  # noqa: S603,S607
        cmap = TTFont(path, fontNumber=0).getBestCmap()
        actual = {cp for cp in ALPHABET if cp not in cmap}
        stated = {
            cp for lo, hi in LACKS.get(face, ()) for cp in range(lo, hi + 1) if cp in ALPHABET
        }
        assert actual == stated, (face, sorted(actual ^ stated))


def test_the_named_face_is_embedded_and_the_font_rule_passes():
    artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_font_rule("Times New Roman, 12 pt"),)
    )
    assert any("Liberation-Serif" in face for face in embedded_font_names(artifact.pdf_bytes))
    assert not [v for v in violations if v.rule.key == "font"]


def test_an_unhonoured_font_is_reported_not_blocking():
    _, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_font_rule("Georgia"),)
    )
    font = [v for v in violations if v.rule.key == "font"]
    assert font and "Georgia" in font[0].detail


def test_a_rule_naming_several_fonts_takes_the_first_one_we_have():
    choice = choose_font(_font_rule("Arial or Times New Roman, 11pt"), _content())
    assert (choice.family, choice.pt) == ("Liberation Sans", 11.0)
    assert choose_font(_font_rule("Georgia or Garamond"), _content()).family == "EB Garamond"
    assert choose_font(_font_rule("Georgia or Arial"), _content()).family == "Liberation Sans"


def _style_block(html):
    import re

    return "".join(re.findall(r"<style.*?</style>", html, re.S))


def _rendered_html(rule, content):
    from unittest import mock

    from apps.documents import render as render_module

    seen = []
    real = render_module.render_to_string
    with mock.patch.object(
        render_module, "render_to_string",
        side_effect=lambda t, c: seen.append(real(t, c)) or seen[-1],
    ):
        artifact, _ = render_cv_with_warnings(content, variant="STANDARD", constraints=(rule,))
    return seen[0], artifact


def test_a_hostile_font_rule_never_reaches_the_rendered_style_block():
    html, artifact = _rendered_html(_font_rule("Arial; } body { display:none"), _content())
    style = _style_block(html)
    assert "display:none" not in html and "display: none" not in html
    assert 'font-family: "Charis SIL"' in style
    assert any("Charis" in face for face in embedded_font_names(artifact.pdf_bytes))


def test_cyrillic_with_a_cambria_rule_embeds_liberation_serif_not_caladea():
    html, artifact = _rendered_html(_font_rule("Cambria"), _content(summary="Жанна Щукина"))
    faces = embedded_font_names(artifact.pdf_bytes)
    assert any("Liberation-Serif" in face or "LiberationSerif" in face for face in faces), faces
    assert not any("Caladea" in face for face in faces), faces
    assert "Caladea" not in html
