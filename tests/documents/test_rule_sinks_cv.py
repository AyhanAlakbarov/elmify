from datetime import date
from types import SimpleNamespace

import pytest

from apps.documents.constraints import Enforcement, resolve_rules
from apps.documents.grammar import Rule
from apps.documents.rule_sinks import (
    cv_limit_key,
    format_decision,
    to_constraint_rules,
    to_directives,
    to_notes,
)
from apps.funding.models import CatalogRule, Program

pytestmark = pytest.mark.django_db

_URL = "https://example.test/apply"


def _rule(index, operation, value, **kw):
    return Rule(index=index, document=kw.pop("document", "cv"), operation=operation,
                value=value, sentence=kw.pop("sentence", f"sentence {index}"),
                confidence=kw.pop("confidence", 0.95), **kw)


def test_a_page_limit_becomes_max_pages_as_an_advisory_rule():
    rules = to_constraint_rules(
        (_rule(0, "limit", 2, unit="pages", sentence="No more than two pages."),),
        source_url=_URL,
    )
    assert (rules[0].key, rules[0].value) == ("max_pages", 2)
    assert rules[0].enforcement is Enforcement.ADVISORY_HIGH_RISK
    assert rules[0].rule_text == "No more than two pages."
    assert rules[0].source_url == _URL


def test_a_word_limit_and_a_character_limit_reach_their_own_keys():
    rules = to_constraint_rules((
        _rule(0, "limit", 800, unit="words"),
        _rule(1, "limit", 4000, unit="characters"),
    ), source_url=_URL)
    assert {r.key for r in rules} == {"max_words", "max_chars_incl_spaces"}


# <!-- amended 2026-09-26: addendum §6.1, per-figure bounds -->
def test_a_character_cap_counted_without_spaces_reaches_its_own_key():
    rules = to_constraint_rules(
        (_rule(0, "limit", 3000, unit="characters", bound="maximum", excl_spaces=True),),
        source_url=_URL,
    )
    assert rules[0].key == "max_chars_excl_spaces"


def test_an_approximate_figure_is_a_cap():
    rules = to_constraint_rules(
        (_rule(0, "limit", 2, unit="pages", bound="approximate"),), source_url=_URL
    )
    assert (rules[0].key, rules[0].value) == ("max_pages", 2)


def test_a_range_on_a_cv_is_its_cap_plus_an_unapplied_note_for_its_floor():
    """Addendum §6.1: every figure is its own decision. The CV has no floor key,
    so the floor is stated and unapplied -- never read as the cap, never dropped."""
    rules = (
        _rule(0, "limit", 1, unit="pages", bound="minimum", sentence="One to two pages."),
        _rule(0, "limit", 2, unit="pages", bound="maximum", sentence="One to two pages."),
    )
    assert [(r.key, r.value) for r in to_constraint_rules(rules, source_url=_URL)] == [
        ("max_pages", 2)
    ]
    assert [(n.key, n.rule_text) for n in to_notes(rules, source_url=_URL)] == [
        ("unapplied", "One to two pages.")
    ]
    assert cv_limit_key(rules[0]) == ""


def test_two_uncertain_figures_in_one_sentence_are_one_note():
    """The quote is the note; two figures of one sentence share it."""
    notes = to_notes((
        _rule(0, "limit", 1, unit="pages", bound="minimum", note="unsure",
              sentence="One or two pages."),
        _rule(0, "limit", 2, unit="pages", bound="maximum", note="unsure",
              sentence="One or two pages."),
    ), source_url=_URL)
    assert len(notes) == 1


def test_a_style_rule_becomes_the_key_it_names_with_the_right_polarity():
    """`photo_forbidden` is photo_allowed=False. Writing it as True would
    silently invert a funder's rule."""
    rules = to_constraint_rules((
        _rule(0, "style", "photo_forbidden"),
        _rule(1, "style", "signature_required"),
        _rule(2, "style", "date_of_birth_forbidden"),
    ), source_url=_URL)
    by_key = {r.key: r.value for r in rules}
    assert by_key["photo_allowed"] is False
    assert by_key["signature_required"] is True
    assert by_key["date_of_birth_allowed"] is False


def test_a_language_rule_becomes_the_language_key():
    rules = to_constraint_rules((_rule(0, "language", "en"),), source_url=_URL)
    assert (rules[0].key, rules[0].value) == ("language", "en")


def test_a_directive_carries_its_action_target_and_sentence():
    directives = to_directives((
        _rule(0, "include", "education.ects_credits", sentence="State your ECTS credits."),
        _rule(1, "order", ("cv", "reverse_chronological")),
        _rule(2, "emphasise", "research"),
    ), source_url=_URL)
    assert directives[0] == {
        "action": "include", "target": "education.ects_credits", "value": None,
        "rule_text": "State your ECTS credits.", "source_url": _URL,
    }
    assert directives[1]["value"] == "reverse_chronological"
    assert directives[2]["action"] == "emphasise"


def test_every_directive_validates_against_the_read_side_schema():
    """check_directive_shape is shared by the write side and the read side so
    the two can never drift. A directive that would fail on read must fail here."""
    from apps.documents.constraints import PageDirective

    directives = to_directives((_rule(0, "include", "education.thesis_title"),), source_url=_URL)
    assert PageDirective.model_validate(directives[0]).target == "education.thesis_title"


def test_a_note_becomes_an_undecided_rule_carrying_the_sentence():
    notes = to_notes(
        (_rule(0, "limit", None, note="unsure", sentence="Keep it short."),), source_url=_URL
    )
    assert notes[0].key == "undecided"
    assert notes[0].rule_text == "Keep it short."
    assert notes[0].enforcement is Enforcement.ADVISORY_HIGH_RISK


def test_an_unapplied_note_uses_the_unapplied_key():
    notes = to_notes(
        (_rule(0, "other", None, note="unapplied", sentence="List publications in APA style."),),
        source_url=_URL,
    )
    assert notes[0].key == "unapplied"


def test_two_notes_on_one_sentence_survive_resolve_rules(program_factory):
    """constraints._MULTI_KEYS slots undecided and unapplied by rule_id, so two
    quotes must both reach the student. A shared id would silently drop one."""
    notes = to_notes((
        _rule(0, "limit", None, note="unsure", sentence="Keep it short."),
        _rule(1, "format", None, note="phrasing", sentence="We suggest Europass."),
    ), source_url=_URL)
    assert len({n.rule_id for n in notes}) == 2
    program = program_factory(
        academic_track="taught", cv_constraints=[n.model_dump(mode="json") for n in notes]
    )
    resolved = resolve_rules(program, None, content=None)
    assert sum(r.key in ("undecided", "unapplied") for r in resolved) == 2


def test_the_format_switch_is_the_agreed_verdict():
    value, confidence = format_decision((_rule(0, "format", "europass_required"),))
    assert value == Program.CVFormatRequirement.EUROPASS_REQUIRED
    assert confidence == Program.CVFormatConfidence.EXTRACTED


def test_a_preferred_verdict_is_its_own_value():
    value, _ = format_decision((_rule(0, "format", "europass_preferred"),))
    assert value == Program.CVFormatRequirement.EUROPASS_PREFERRED


def test_a_page_with_no_format_rule_is_any_and_extracted():
    """A served page that states no format rule states no format rule. That is
    a result, not an abstention (spec §5.3)."""
    value, confidence = format_decision(())
    assert value == Program.CVFormatRequirement.ANY
    assert confidence == Program.CVFormatConfidence.EXTRACTED


def test_an_undecided_format_note_writes_any_and_undecided():
    value, confidence = format_decision(
        (_rule(0, "format", "europass_required", note="phrasing"),)
    )
    assert value == Program.CVFormatRequirement.ANY
    assert confidence == Program.CVFormatConfidence.UNDECIDED


def test_other_template_never_renders_a_template_the_engine_does_not_know():
    value, confidence = format_decision((_rule(0, "format", "other_template"),))
    assert value == Program.CVFormatRequirement.ANY
    assert confidence == Program.CVFormatConfidence.UNDECIDED


def test_a_third_party_format_rule_never_reaches_the_switch():
    """Measured 2026-09-14: two of three readings attributed 'Short CV (max. 2
    pages) from this academic supervisor' to the applicant."""
    value, _ = format_decision(
        (_rule(0, "format", "europass_required", note="third_party"),)
    )
    assert value == Program.CVFormatRequirement.ANY


def test_a_letter_rule_is_not_a_cv_constraint():
    assert to_constraint_rules(
        (_rule(0, "limit", 800, unit="words", document="motivation_letter"),), source_url=_URL
    ) == ()


# <!-- controller ruling C5, 2026-09-26: a real candidate sentence can be
# 1,935 characters and must not raise -- it is clipped, like derive._quote. -->
def test_a_long_sentence_is_clipped_rather_than_rejected():
    long_sentence = "A" * 1935
    rules = to_constraint_rules(
        (_rule(0, "limit", 2, unit="pages", sentence=long_sentence),), source_url=_URL
    )
    assert len(rules[0].rule_text) <= 1000
    assert rules[0].rule_text.endswith("[...]")


# <!-- controller ruling C6, 2026-09-26: an applied other_template format rule
# sets any + UNDECIDED in format_decision, but the sentence itself must still
# reach the student -- CLAUDE.md "Closed 2026-09-13". -->
def test_an_other_template_format_rule_is_an_undecided_note():
    notes = to_notes(
        (_rule(0, "format", "other_template",
               sentence="You must use SI's provided template for CV 2026/2027."),),
        source_url=_URL,
    )
    assert len(notes) == 1
    assert notes[0].key == "undecided"
    assert notes[0].rule_text == "You must use SI's provided template for CV 2026/2027."


# <!-- controller ruling C7, 2026-09-26: sink_for makes a CV student_action
# "applied" (student_actions), but nothing else here writes it anywhere. -->
def test_a_cv_student_action_is_an_unapplied_note():
    notes = to_notes(
        (_rule(0, "student_action", "rename_file",
               sentence="Upload your CV as SURNAME_CV.pdf."),),
        source_url=_URL,
    )
    assert len(notes) == 1
    assert notes[0].key == "unapplied"
    assert notes[0].rule_text == "Upload your CV as SURNAME_CV.pdf."


# <!-- task 8 fix round 1, finding 1 (PII boundary): a Europass action only
# when every applied CV format value is that same Europass value and no other
# format sentence is unsettled. Anything else is any + UNDECIDED. -->
@pytest.mark.parametrize("note", ["phrasing", "unsure", "conflict", "conditional"])
def test_europass_beside_an_unsettled_format_sentence_is_any_and_undecided(note):
    value, confidence = format_decision((
        _rule(0, "format", "europass_required", sentence="A Europass CV is required."),
        _rule(1, "format", "europass_required", note=note, sentence="We suggest Europass."),
    ))
    assert (value, confidence) == (
        Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.UNDECIDED
    )


@pytest.mark.parametrize("other", ["other_template", "any", "europass_preferred"])
def test_europass_beside_a_different_applied_verdict_is_any_and_undecided(other):
    """format_decision is the last gate before egress: it must hold even when
    resolve_conflicts never ran over the rules it is handed."""
    value, confidence = format_decision((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", other),
    ))
    assert (value, confidence) == (
        Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.UNDECIDED
    )


def test_a_third_party_format_note_does_not_unsettle_the_applicants_europass_rule():
    value, confidence = format_decision((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "europass_preferred", note="third_party",
              sentence="Your referee's CV should be in Europass."),
    ))
    assert (value, confidence) == (
        Program.CVFormatRequirement.EUROPASS_REQUIRED, Program.CVFormatConfidence.EXTRACTED
    )


# <!-- task 8 fix round 1, finding 5 -->
def test_a_not_a_format_rule_value_never_moves_the_switch():
    value, confidence = format_decision((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "not_a_format_rule"),
    ))
    assert (value, confidence) == (
        Program.CVFormatRequirement.EUROPASS_REQUIRED, Program.CVFormatConfidence.EXTRACTED
    )


# <!-- task 8 fix round 1, finding 2: font_family and font_size_minimum share
# the `font` key, and resolve_rules keeps the last of a key. -->
def test_a_second_font_rule_is_an_unapplied_note_not_a_colliding_key():
    rules = (
        _rule(0, "style", "font_family", detail="Arial", sentence="Use Arial."),
        _rule(1, "style", "font_size_minimum", detail="11",
              sentence="Font size at least 11 pt."),
    )
    constraints = to_constraint_rules(rules, source_url=_URL)
    assert [(c.key, c.value, c.rule_text) for c in constraints] == [
        ("font", "Arial", "Use Arial.")
    ]
    notes = to_notes(rules, source_url=_URL)
    assert [(n.key, n.rule_text) for n in notes] == [("unapplied", "Font size at least 11 pt.")]


# <!-- task 8 fix round 1, finding 4 -->
@pytest.mark.parametrize("rule", [
    _rule(0, "order", ("cv", "none"), sentence="Order it somehow."),
    _rule(0, "order", "education", sentence="Order it somehow."),
    _rule(0, "include", "education.astrology", sentence="Order it somehow."),
])
def test_a_malformed_directive_is_an_unapplied_note_never_a_crash_or_a_drop(rule):
    assert to_directives((rule,), source_url=_URL) == ()
    notes = to_notes((rule,), source_url=_URL)
    assert [(n.key, n.rule_text) for n in notes] == [("unapplied", "Order it somehow.")]


# <!-- task 8 fix round 1, finding 6 -->
def test_a_long_sentence_is_clipped_in_notes_and_directives():
    long_sentence = "A" * 1935
    notes = to_notes(
        (_rule(0, "limit", None, note="unsure", sentence=long_sentence),), source_url=_URL
    )
    directives = to_directives(
        (_rule(0, "include", "education.thesis_title", sentence=long_sentence),), source_url=_URL
    )
    for text in (notes[0].rule_text, directives[0]["rule_text"]):
        assert len(text) <= 1000
        assert text.endswith("[...]")


def test_a_megabytes_cap_becomes_max_bytes_held_the_stricter_way():
    """Task 11 (§11 gate 7). A decimal megabyte, the smaller byte count: a file
    that passes ours passes the page's under either reading of "MB"."""
    rules = to_constraint_rules((
        _rule(0, "limit", 2, unit="megabytes", bound="maximum"),
        _rule(1, "limit", 1.5, unit="megabytes", bound="maximum"),
    ), source_url=_URL)
    assert [(r.key, r.value) for r in rules] == [("max_bytes", 2_000_000),
                                                ("max_bytes", 1_500_000)]


def test_no_gaps_and_no_hyperlinks_reach_the_values_their_checkers_read():
    """Fix round 1, finding 1: no_gaps projects catalog_seed's own
    GERMAN_GAP_TOLERANCE_MONTHS (3), the same figure C-002 seeds for the same
    country -- never a bare 0, which read a page's "no gaps" stricter than the
    catalog's own tolerance for an ordinary summer between two degrees."""
    from apps.documents.catalog_seed import GERMAN_GAP_TOLERANCE_MONTHS
    from apps.documents.render import _check_no_unexplained_gaps, _check_prohibited_content

    rules = to_constraint_rules((
        _rule(0, "style", "no_gaps"),
        _rule(1, "style", "no_hyperlinks"),
    ), source_url=_URL)
    by_key = {r.key: r for r in rules}
    assert by_key["no_unexplained_gaps"].value == GERMAN_GAP_TOLERANCE_MONTHS
    assert by_key["prohibited_content"].value == ["hyperlinks"]
    # Each value is one its checker reads: a known token (an unknown one is
    # reported as "unrecognised"), and a month count -- checked against
    # content with no dated entries, which passes at ANY threshold, so this
    # only pins the token-lookup half; the threshold itself is pinned below
    # against real dated content.
    linked = SimpleNamespace(personal_information=SimpleNamespace(links=["https://x.test"]),
                             publications=[], education=[], experience=[], research=[],
                             timeline=[])
    assert _check_prohibited_content(by_key["prohibited_content"], linked, None) == (
        "content includes prohibited hyperlinks"
    )
    assert _check_no_unexplained_gaps(by_key["no_unexplained_gaps"], linked, _PDF) is None


#: The gap checker reads the artifact's variant: a gap statement counts as
#: coverage only where the CV prints it. A PDF variant, as render_cv passes.
_PDF = SimpleNamespace(variant="STANDARD")


def _gapped_cv(gap_start: date, gap_end: date):
    """CVContent with one education span ending gap_start and one experience
    span beginning gap_end -- exactly what _check_no_unexplained_gaps reads."""
    from apps.documents.render import CVContent, EducationEntry, ExperienceEntry
    from apps.documents.schemas import PersonalInformation

    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="j@example.test"),
        education=(EducationEntry(
            degree_as_awarded="BSc", institution_original="Example University",
            city="Berlin", country="DE",
            start_date=date(gap_start.year - 3, 9, 1), end_date=gap_start,
        ),),
        experience=(ExperienceEntry(
            employer="Employer", title="Intern", start_date=gap_end,
            end_date=date(gap_end.year + 1, 6, 30), bullets=("Did the work.",),
        ),),
        research=(), publications=(), awards=(), skills=(), languages=(),
        document_language="en", references=(),
    )


def test_a_de_page_saying_no_gaps_is_held_to_catalog_seeds_own_tolerance():
    """Fix round 1, finding 1 (TDD). C-002 seeds a 3-month tolerance for
    Germany; a programme page's own "no gaps" statement must be read against
    the SAME figure, through the real path: rule_sinks projects the page rule,
    resolve_rules picks between it and the country seed, and render's real
    checker reads whatever resolve_rules hands it.

    A 30 June -> 1 September gap (an ordinary summer) must NOT be flagged; a
    five-month gap must be."""
    from apps.documents.catalog_seed import GERMAN_GAP_TOLERANCE_MONTHS
    from apps.documents.render import _check_no_unexplained_gaps

    CatalogRule.objects.create(
        rule_id="C-002", scope_kind=CatalogRule.ScopeKind.COUNTRY, scope_values=["DE"],
        key="no_unexplained_gaps", value=GERMAN_GAP_TOLERANCE_MONTHS,
        enforcement="ADVISORY_HIGH_RISK",
        rule_text="uni-assist: do not leave out any period.",
        source_url="https://www.uni-assist.de/", verified_for_cycle="current site, 2026",
        confidence="high",
    )
    page_rules = to_constraint_rules(
        (_rule(0, "style", "no_gaps", sentence="Please ensure your CV has no gaps."),),
        source_url=_URL,
    )

    from apps.funding.models import Institution

    institution = Institution.objects.create(
        canonical_key="inst:de-gap-test", name="Test University", country_code="DE",
        official_website="https://university.example.test",
    )
    programme = Program.objects.create(
        institution=institution, canonical_key="prog:de-gap-test", name="MSc Test",
        campus_name="Main", city="Berlin", country_code="DE", location_key="de:berlin",
        degree_level="MASTER", teaching_languages=["English"], duration_months=12,
        academic_track="taught",
        cv_constraints=[r.model_dump(mode="json") for r in page_rules],
    )

    resolved = resolve_rules(programme, None, content=None)
    gap_rules = [r for r in resolved if r.key == "no_unexplained_gaps"]
    assert len(gap_rules) == 1
    gap_rule = gap_rules[0]
    assert gap_rule.value == GERMAN_GAP_TOLERANCE_MONTHS

    ordinary_summer = _gapped_cv(date(2021, 6, 30), date(2021, 9, 1))
    assert _check_no_unexplained_gaps(gap_rule, ordinary_summer, _PDF) is None

    five_month_gap = _gapped_cv(date(2021, 1, 31), date(2021, 6, 30))
    detail = _check_no_unexplained_gaps(gap_rule, five_month_gap, _PDF)
    assert detail is not None
    assert "month gap" in detail


# Final review item 1: a below-bar slot guessed `other` is still a note, and a
# note about Europass unsettles the switch whatever the slot guessed.
def test_an_unsure_note_guessed_other_is_kept_as_a_note():
    notes = to_notes((
        _rule(0, "format", None, document="other", note="unsure",
              sentence="Europass CV is not accepted."),
    ), source_url=_URL)
    assert [(n.key, n.rule_text) for n in notes] == [
        ("undecided", "Europass CV is not accepted."),
    ]


def test_an_applied_other_rule_is_still_not_a_note():
    assert to_notes((_rule(0, "topic", None, document="other"),), source_url=_URL) == ()


def test_an_unsure_europass_sentence_guessed_other_unsettles_the_switch():
    """The reproduced pair: an applied Europass requirement beside a below-bar
    "not accepted" the slot guessed was about something else."""
    value, confidence = format_decision((
        _rule(0, "format", "europass_required", sentence="CV in Europass format."),
        _rule(1, "format", None, document="other", note="unsure", confidence=0.6,
              sentence="Europass CV is not accepted."),
    ))
    assert value == Program.CVFormatRequirement.ANY
    assert confidence == Program.CVFormatConfidence.UNDECIDED


@pytest.mark.parametrize(("document", "operation", "note"), [
    ("letter", "topic", "unsure"),
    ("cv", "include", "unapplied"),
    ("other", "other", "conflict"),
])
def test_any_unsettled_europass_sentence_unsettles_the_switch(document, operation, note):
    value, confidence = format_decision((
        _rule(0, "format", "europass_required", sentence="CV in Europass format."),
        _rule(1, operation, None, document=document, note=note,
              sentence="Please use the EUROPASS template if you can."),
    ))
    assert (value, confidence) == (
        Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.UNDECIDED,
    )


def test_a_third_party_europass_note_still_unsettles_nothing():
    value, confidence = format_decision((
        _rule(0, "format", "europass_required", sentence="CV in Europass format."),
        _rule(1, "topic", None, document="other", note="third_party",
              sentence="Your supervisor's Europass CV."),
    ))
    assert confidence == Program.CVFormatConfidence.EXTRACTED


# Final review item 5: the two character keys share their first nine letters.
def test_both_character_keys_on_one_sentence_get_distinct_rule_ids():
    rules = to_constraint_rules((
        _rule(0, "limit", 3000, unit="characters", bound="maximum", figure=0),
        _rule(0, "limit", 2800, unit="characters", bound="maximum", figure=1,
              excl_spaces=True),
    ), source_url=_URL)
    assert {r.key for r in rules} == {"max_chars_incl_spaces", "max_chars_excl_spaces"}
    assert len({r.rule_id for r in rules}) == 2


@pytest.mark.parametrize("index", [0, 99, 999])
def test_every_constraint_key_has_its_own_rule_id(index):
    import typing

    from apps.documents.constraints import _CONSTRAINT_KEYS
    from apps.documents.rule_sinks import page_rule_id

    keys = typing.get_args(_CONSTRAINT_KEYS)
    ids = {page_rule_id(index, key) for key in keys}
    assert len(ids) == len(keys)
    assert max(len(i) for i in ids) <= 20
