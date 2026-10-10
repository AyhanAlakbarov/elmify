"""Task 8: the shape becomes rules, and a formal letter gets its own template."""

import csv
from pathlib import Path
from typing import cast

import pytest
from django.template.loader import render_to_string

from apps.documents.letter_defaults import defaults_for
from apps.documents.letter_render import (
    FORMALITIES,
    SHIPPED_FONTS,
    formality_for,
    letter_context,
    reader_for,
    render_letter,
    select_letter_variant,
)
from apps.documents.letter_schemas import LetterContent, LetterUnit
from apps.documents.letter_shape import (
    LetterShape,
    NotGeneratable,
    constraints_from_shape,
    target_word_count,
    validate_shape_bounds,
)
from apps.documents.render import PreflightBlocked

_RULES = Path(__file__).resolve().parents[2] / "docs/research/letter-shape-rules.csv"


def _content(text: str = "Because of the robotics lab.", language: str = "en") -> LetterContent:
    return LetterContent(
        language=language, units=(LetterUnit(archetype="WHY_PROGRAMME", text=text),)
    )


def test_the_shape_becomes_binding_rules_carrying_their_sentence() -> None:
    shape = LetterShape(
        max_words=500,
        min_words=300,
        max_chars=3000,
        max_pages=2.0,
        sources={
            "max_words": {"text": "no more than 500 words", "source_url": "u"},
            "min_words": {"text": "at least 300 words", "source_url": "u"},
        },
    )
    rules = {rule.key: rule for rule in constraints_from_shape(shape)}
    assert rules["max_words"].value == 500
    assert rules["max_words"].rule_text == "no more than 500 words"
    assert rules["max_words"].enforcement == "BINDING"
    assert rules["min_words"].value == 300
    # Every bound letter_render can measure becomes a rule, not only the two
    # the page happened to source: max_chars maps to the inclusive key.
    assert rules["max_chars_incl_spaces"].value == 3000
    assert rules["max_pages"].value == 2.0


def test_a_bound_with_no_page_sentence_does_not_claim_one() -> None:
    """A stored bound nobody sourced must not read as a quote from the page."""
    (rule,) = constraints_from_shape(LetterShape(max_words=500))
    assert "500" in rule.rule_text
    assert rule.source_url == ""


def test_a_formal_shape_selects_the_formal_template() -> None:
    assert select_letter_variant("CONTINUOUS_LETTER", form="FORMAL_LETTER") == "LETTER_FORMAL"
    assert select_letter_variant("CONTINUOUS_LETTER", form="ESSAY") == "LETTER_PDF"
    assert select_letter_variant("CONTINUOUS_LETTER") == "LETTER_PDF"


def test_a_form_never_overrides_a_structure_that_is_not_a_letter() -> None:
    """PORTAL_FORM and the prescribed research form have no salutation to add."""
    assert select_letter_variant("SHORT_ANSWER_SET", form="FORMAL_LETTER") == "FIELD_MAPPED"
    assert (
        select_letter_variant("PRESCRIBED_RESEARCH_FORM", form="FORMAL_LETTER")
        == "TWO_SECTION_FORM"
    )


def test_a_floor_blocks_a_short_letter_with_the_pages_sentence() -> None:
    shape = LetterShape(
        min_words=300, sources={"min_words": {"text": "at least 300 words", "source_url": "u"}}
    )
    with pytest.raises(PreflightBlocked, match="at least 300 words"):
        render_letter(
            _content(),
            structure="CONTINUOUS_LETTER",
            constraints=constraints_from_shape(shape),
            shape=shape,
        )


def test_a_font_we_do_not_ship_blocks_rather_than_substitutes() -> None:
    shape = LetterShape(font_family="Garamond Pro")
    assert "Garamond Pro" not in SHIPPED_FONTS
    with pytest.raises(PreflightBlocked, match="Garamond Pro"):
        render_letter(_content(), structure="CONTINUOUS_LETTER", shape=shape)


def test_the_two_fonts_every_other_page_asks_for_are_honoured() -> None:
    """"Times New Roman, 12pt" is the commonest published letter rule, and it
    blocked every render until the image shipped the metric-compatible faces
    (owner decision, 2026-09-23). The originals are Monotype's and cannot be
    embedded in a PDF we distribute; Liberation's metrics are identical, which
    is what a page cap is measured in."""
    for family, generic in (("Times New Roman", "serif"), ("Arial", "sans-serif")):
        assert SHIPPED_FONTS[family] == generic
        artifact = render_letter(
            _content(), structure="CONTINUOUS_LETTER", shape=LetterShape(font_family=family)
        )
        assert artifact.pdf_bytes
        html = _letter_html(LetterShape(font_family=family, form="FORMAL_LETTER"))
        assert f'"{family}", {generic}' in html


def test_the_default_letter_font_names_what_it_gets() -> None:
    """Not "Helvetica": with Liberation in the image fontconfig maps that onto
    Liberation Sans, and every words-per-page figure was measured on DejaVu."""
    html = _letter_html(LetterShape())
    assert '"DejaVu Sans", sans-serif' in html


def _letter_html(shape: LetterShape, language: str = "en") -> str:
    """The formal template with the context render_letter builds.

    These assertions are about the rendered CSS; going through render_letter
    would drag PDF generation into a template test. Template SELECTION has its
    own test above.
    """
    return render_to_string(
        "documents/letter_formal.html",
        {
            "content": _content(language=language),
            **letter_context(
                shape,
                formality=formality_for(language, "ADMISSIONS"),
                addressee="Admissions Committee",
                place_and_date="Strasbourg, 19 September 2026",
                applicant_name="A Student",
            ),
        },
    )


def test_spacing_and_margins_reach_the_rendered_css() -> None:
    shape = LetterShape(line_spacing=2.0, margins_cm=2.5, font_min_pt=12)
    html = _letter_html(shape)
    assert "line-height: 2.0" in html and "margin: 2.5cm" in html and "12pt" in html


def test_a_language_with_no_formality_row_falls_back_to_essay() -> None:
    """Never borrow another language's salutation (spec section 6)."""
    shape = LetterShape(form="FORMAL_LETTER")
    artifact = render_letter(
        _content(language="tr"),
        structure="CONTINUOUS_LETTER",
        shape=shape,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    assert artifact.variant == "LETTER_PDF"
    html = _letter_html(shape, language="tr")
    assert "Dear members" not in html and "ATENTAMENTE" not in html


def test_a_row_missing_either_formula_falls_back_like_a_missing_row() -> None:
    """Half a formal letter is what the fallback exists to avoid.

    Portuguese has a sourced closing and no sourced salutation; Spanish lost
    its salutation when "Presente" turned out to be the last line of UNAM's
    ADDRESSEE block, not an opening. Both must render as essays, not as a
    letter that opens with nothing.
    """
    for language in ("es", "pt"):
        assert FORMALITIES[language].closing
        assert not FORMALITIES[language].complete
        assert formality_for(language, "ADMISSIONS") is None
        artifact = render_letter(
            _content(language=language),
            structure="CONTINUOUS_LETTER",
            shape=LetterShape(form="FORMAL_LETTER"),
            funder_kind="UNIVERSITY_ADMISSION",
        )
        assert artifact.variant == "LETTER_PDF"


def test_a_visa_letter_never_opens_with_an_admissions_salutation() -> None:
    """M-084's reader is the visa office, never the university."""
    assert reader_for("IMMIGRATION_AUTHORITY") == ""
    assert reader_for("GOVERNMENT_SCHOLARSHIP") == ""
    assert reader_for("UNIVERSITY_ADMISSION") == "ADMISSIONS"
    assert formality_for("en", reader_for("IMMIGRATION_AUTHORITY")) is None
    artifact = render_letter(
        _content(),
        structure="CONTINUOUS_LETTER",
        shape=LetterShape(form="FORMAL_LETTER"),
        funder_kind="IMMIGRATION_AUTHORITY",
    )
    assert artifact.variant == "LETTER_PDF"


def test_the_sender_block_reaches_the_formal_letter() -> None:
    """letter_gates BLOCKS a letter for omitting it; the template dropped it."""
    html = render_to_string(
        "documents/letter_formal.html",
        {
            "content": LetterContent(
                language="en",
                header_block="Ada Lovelace | Baku | ada@example.com",
                units=(LetterUnit(archetype="WHY_PROGRAMME", text="I am applying."),),
            ),
            **letter_context(
                LetterShape(form="FORMAL_LETTER"),
                formality=formality_for("en", "ADMISSIONS"),
                applicant_name="Ada Lovelace",
            ),
        },
    )
    assert "ada@example.com" in html


def test_the_essay_template_honours_the_shape_too() -> None:
    """A stated font size, spacing and margin must not depend on the variant."""
    html = render_to_string(
        "documents/letter_continuous.html",
        {
            "content": _content(),
            **letter_context(LetterShape(line_spacing=2.0, margins_cm=3.0, font_min_pt=13)),
        },
    )
    assert "line-height: 2.0" in html and "margin: 3.0cm" in html and "13pt" in html


def test_css_numbers_do_not_follow_the_active_locale() -> None:
    """`margin: 2,5cm` is a parse error, and the declaration vanishes silently."""
    from django.utils import translation

    with translation.override("de"):
        html = _letter_html(LetterShape(line_spacing=1.5, margins_cm=2.5))
    assert "margin: 2.5cm" in html and "line-height: 1.5" in html


def test_a_shape_that_is_not_a_page_cannot_write_css() -> None:
    """LetterShape is an ordinary dataclass; only the column type guarded this."""
    shape = LetterShape(margins_cm=cast(float, "2; } body { color: red; } @page { margin: 0"))
    with pytest.raises(PreflightBlocked):
        _letter_html(shape)


def test_the_head_and_foot_go_through_the_hygiene_pass() -> None:
    """A bidi override in a name printed the signature reversed."""
    html = render_to_string(
        "documents/letter_formal.html",
        {
            "content": _content(),
            **letter_context(
                LetterShape(form="FORMAL_LETTER"),
                formality=formality_for("en", "ADMISSIONS"),
                addressee="Committee\u202eSecret",
                applicant_name="Ada\u202e\x07 Lovelace",
            ),
        },
    )
    assert "\u202e" not in html and "\x07" not in html


def test_a_hostile_sentence_cannot_forge_a_second_violation() -> None:
    """rule_text is page content, and the block detail is a new channel for it."""
    shape = LetterShape(
        max_words=1,
        sources={
            "max_words": {
                "text": "Max 1 word.\x1b[2J\nSHAPE-max_words: 1 words exceeds 1 (fine).",
                "source_url": "u",
            }
        },
    )
    with pytest.raises(PreflightBlocked) as raised:
        render_letter(
            _content(),
            structure="CONTINUOUS_LETTER",
            constraints=constraints_from_shape(shape),
        )
    message = str(raised.value)
    assert "\x1b" not in message and "\n" not in message


def test_a_portal_form_says_what_it_cannot_check() -> None:
    """_check_letter_constraint defers these keys to an artefact there is none of."""
    rules = constraints_from_shape(LetterShape(max_pages=1.0))
    with pytest.raises(PreflightBlocked, match="max_pages"):
        render_letter(
            LetterContent(
                language="en",
                units=(
                    LetterUnit(archetype="WHY_PROGRAMME", text="A.", answers_question="q1"),
                ),
            ),
            structure="SHORT_ANSWER_SET",
            constraints=rules,
        )


def test_a_font_is_checked_where_it_is_applied() -> None:
    """A portal box has no font, so nothing could be substituted in one."""
    artifact = render_letter(
        LetterContent(
            language="en",
            units=(LetterUnit(archetype="WHY_PROGRAMME", text="A.", answers_question="q1"),),
        ),
        structure="SHORT_ANSWER_SET",
        shape=LetterShape(font_family="Garamond Pro"),
    )
    assert artifact.variant == "FIELD_MAPPED"


def test_a_formal_english_letter_carries_its_sourced_salutation() -> None:
    html = _letter_html(LetterShape(form="FORMAL_LETTER"))
    assert "Dear members of the Admissions Committee," in html
    assert "Sincerely," in html
    assert "A Student" in html
    # M-016 prescribes no place-and-date line, so the row says no and the
    # template must not print one.
    assert "Strasbourg" not in html


def test_every_formality_formula_is_quoted_from_the_rule_it_cites() -> None:
    """The check that catches an invented salutation.

    The plan for this task proposed five rows whose formulas were nowhere in
    the rules they cited (and one, "de", cited an Ireland visa rule). A
    formality row may only carry wording its own M- rule states.

    What it does NOT catch, stated so nobody reads it as more (review 3): a
    substring check cannot tell a prescribed formula from the rule's own
    commentary about formulas, and it cannot tell that the rule is about the
    row's language. It catches invention, not misattribution -- which is the
    defect "Presente" turned out to be.
    """
    rules = {row["ID"]: row["Rule"] for row in csv.DictReader(_RULES.open(encoding="utf-8"))}
    for language, formality in FORMALITIES.items():
        assert formality.source in rules, f"{language} cites unknown rule {formality.source}"
        text = rules[formality.source]
        for formula in (formality.salutation, formality.closing):
            if formula:
                assert formula in text, f"{language}: {formula!r} is not in {formality.source}"


def test_a_page_cap_no_letter_can_meet_is_refused_before_the_model_call() -> None:
    """Residual (e) from Task 7, widened: ANY cap below one page blocks every
    letter, because the page count it is compared against is an integer."""
    for pages in (0, 0.5, 0.9):
        with pytest.raises(NotGeneratable, match="pages"):
            validate_shape_bounds(LetterShape(max_pages=pages))


def test_a_floor_that_does_not_fit_the_page_cap_is_refused() -> None:
    """No word count satisfies both, and every candidate cost a model call."""
    with pytest.raises(NotGeneratable, match="does not fit"):
        validate_shape_bounds(LetterShape(min_words=900, max_pages=1.0))


def test_the_target_respects_a_page_cap() -> None:
    row = defaults_for(country_code="US", track="taught", portfolio_led=False,
                       funder_kind="UNIVERSITY_ADMISSION")
    assert row.word_target > 600
    assert target_word_count(LetterShape(max_pages=1.0), row) <= 600


def test_every_branch_of_the_target_is_held_by_the_character_cap() -> None:
    """Fix round 4's clamp was reachable from two branches of three."""
    row = defaults_for(country_code="DE", track="taught", portfolio_led=False,
                       funder_kind="UNIVERSITY_ADMISSION")
    assert target_word_count(LetterShape(max_words=500, max_chars=2000), row) <= 2000 // 6


def test_bounds_that_leave_room_for_no_words_are_refused() -> None:
    row = defaults_for(country_code="DE", track="taught", portfolio_led=False,
                       funder_kind="UNIVERSITY_ADMISSION")
    with pytest.raises(NotGeneratable, match="0 words"):
        target_word_count(LetterShape(max_chars=5), row)


def test_a_word_bound_is_not_enforced_in_a_script_that_has_no_words() -> None:
    """text.split() returns 1 for a page of Japanese, so an 800-word floor
    became a rule no Japanese letter could ever satisfy."""
    shape = LetterShape(min_words=800, max_chars=2000)
    keys = {rule.key for rule in constraints_from_shape(shape, document_language="ja")}
    assert keys == {"max_chars_incl_spaces"}
    assert "min_words" in {
        rule.key for rule in constraints_from_shape(shape, document_language="en")
    }


def test_a_one_page_cap_is_aimed_at_per_template() -> None:
    """The formal template spends a sixth of its first page on head and foot.

    Re-review: one words-per-page figure served both templates, and aiming at
    600 under a one-page formal cap rendered two pages -- the defect the
    figure was added to fix.
    """
    row = defaults_for(country_code="US", track="taught", portfolio_led=False,
                       funder_kind="UNIVERSITY_ADMISSION")
    essay = target_word_count(LetterShape(max_pages=1.0), row)
    formal = target_word_count(LetterShape(max_pages=1.0, form="FORMAL_LETTER"), row)
    assert formal < essay <= 616
    assert formal <= 499


def test_a_page_cap_is_floored_the_way_the_checker_reads_it() -> None:
    """`_check_max_pages` compares int(value), so 1.5 pages IS one page."""
    row = defaults_for(country_code="US", track="taught", portfolio_led=False,
                       funder_kind="UNIVERSITY_ADMISSION")
    assert target_word_count(LetterShape(max_pages=1.5), row) == target_word_count(
        LetterShape(max_pages=1.0), row
    )


def test_the_page_refusal_fires_inside_the_band_it_is_for() -> None:
    """A floor of 750 words under one page has no satisfying letter.

    The old figure (800 words to a page) was above every ceiling ever
    measured, so this refusal never fired at all (re-review). 617-720 is still
    an unrefusable band, because a refusal has to be certain and the densest
    page measured held 701.
    """
    with pytest.raises(NotGeneratable, match="does not fit"):
        validate_shape_bounds(LetterShape(min_words=750, max_pages=1.0))


def test_a_script_variant_keeps_its_exemption() -> None:
    """zh-Hans is storable, and matching the whole string dropped every one."""
    keys = {
        rule.key
        for rule in constraints_from_shape(
            LetterShape(min_words=800, max_chars=2000), document_language="zh-Hans"
        )
    }
    assert keys == {"max_chars_incl_spaces"}


def test_a_formality_row_is_found_whatever_the_case_of_the_language() -> None:
    """check_language_mismatch passes "EN" against "en", so this must too."""
    assert formality_for("EN", "ADMISSIONS") is not None


def test_two_answers_for_one_portal_question_block_rather_than_vanish() -> None:
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="WHY_PROGRAMME", text="First answer.", answers_question="q1"),
            LetterUnit(archetype="WHY_PROGRAMME", text="Second answer.", answers_question="q1"),
        ),
    )
    with pytest.raises(PreflightBlocked, match="q1"):
        render_letter(content, structure="SHORT_ANSWER_SET")


def _instructions(shape: LetterShape, language: str = "ja") -> str:
    from apps.documents.letters import _shape_instructions

    row = defaults_for(country_code="JP", track="taught", portfolio_led=False,
                       funder_kind="UNIVERSITY_ADMISSION")
    return _shape_instructions(shape, row, language)


def test_a_script_with_no_word_unit_is_never_told_a_word_floor() -> None:
    """Round 2 moved the TARGET to characters and left the floor in words."""
    text = _instructions(LetterShape(min_words=800, max_chars=1000))
    assert "characters" in text and "800 words" not in text


def test_a_character_target_is_refused_at_zero_like_a_word_target() -> None:
    with pytest.raises(NotGeneratable, match="0 characters"):
        _instructions(LetterShape(max_chars=1))


def test_the_script_check_reads_a_subtag_the_way_the_exemption_does() -> None:
    """The values newly exempted from word bounds kept their script check."""
    from apps.documents.letter_gates import GateCode, check_language_mismatch

    for language in ("ja", "ja-JP", "zh-Hans"):
        violations = check_language_mismatch(
            LetterContent(
                language=language,
                units=(LetterUnit(archetype="WHY_PROGRAMME", text="Written in English."),),
            ),
            document_language=language,
        )
        assert [v.code for v in violations] == [GateCode.LANGUAGE_MISMATCH]


def test_the_page_refusal_knows_the_formal_template_holds_less() -> None:
    with pytest.raises(NotGeneratable, match="does not fit"):
        validate_shape_bounds(LetterShape(min_words=700, max_pages=1.0, form="FORMAL_LETTER"))


def test_a_structure_with_no_template_is_answered_not_raised() -> None:
    """CONSORTIUM_SPECIFIC and VIDEO are legal structures generate_letter refuses."""
    from apps.documents.letter_render import renders_formal_letter

    assert renders_formal_letter("CONSORTIUM_SPECIFIC", "FORMAL_LETTER") is False
    assert renders_formal_letter("CONTINUOUS_LETTER", "FORMAL_LETTER") is True


def test_an_answer_to_a_question_the_portal_never_asked_blocks() -> None:
    content = LetterContent(
        language="en",
        units=(LetterUnit(archetype="WHY_PROGRAMME", text="An answer.", answers_question="q9"),),
    )
    with pytest.raises(PreflightBlocked, match="q9"):
        render_letter(content, structure="SHORT_ANSWER_SET", questions=[{"id": "q1"}])


def test_a_shape_value_css_drops_silently_is_refused() -> None:
    """nan, inf and a negative point size all rendered, and CSS drops each."""
    for shape in (
        LetterShape(margins_cm=float("nan")),
        LetterShape(line_spacing=float("inf")),
        LetterShape(font_min_pt=-5),
    ):
        with pytest.raises(PreflightBlocked, match="positive number"):
            _letter_html(shape)
