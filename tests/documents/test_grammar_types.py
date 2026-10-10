import pytest

from apps.documents.constraints import (
    _CONSTRAINT_KEYS,
    _INCLUDE_TARGETS,
    _ORDER_DIRECTIONS,
    _ORDER_TARGETS,
    _SECTIONS,
)
from apps.documents.grammar import (
    BOUNDS,
    CONDITION_KINDS,
    DOCUMENTS,
    FORM_VALUES,
    FORMAT_VERDICTS,
    NAMING_VALUES,
    NOTE_BOUNDS,
    OPERATIONS,
    SINKS,
    STYLE_VALUES,
    UNITS,
    Rule,
    limit_sink,
    sink_for,
)


def test_every_cv_sink_is_a_real_constraint_key_or_directive_action():
    """The grammar may only ever produce a rule something downstream reads.
    A sink that names nothing is a rule that is silently never applied -- the
    exact failure `unapplied` exists to make visible."""
    import typing

    keys = set(typing.get_args(_CONSTRAINT_KEYS))
    for operation in ("limit", "language", "format", "style"):
        for value in {"limit": (2,), "language": ("en",), "format": FORMAT_VERDICTS,
                      "style": STYLE_VALUES}[operation]:
            sink = sink_for("cv", operation, value)
            assert sink in keys | {"cv_format_requirement", ""}, (operation, value, sink)
    for bound in BOUNDS:
        for unit in (*UNITS, "other"):
            for excluded in (False, True):
                sink = limit_sink("cv", bound, unit, excl_spaces=excluded)
                assert sink in keys | {""}, (bound, unit, excluded, sink)


def test_every_directive_operation_names_a_closed_target():
    assert sink_for("cv", "include", "education.thesis_title") == "cv_directives"
    # An order value is the (target, direction) pair grammar_values builds.
    assert sink_for("cv", "order", ("publications", "reverse_chronological")) == "cv_directives"
    assert sink_for("cv", "order", ("cv", "none")) == ""
    assert sink_for("cv", "order", "publications") == ""
    assert sink_for("cv", "emphasise", "research") == "cv_directives"
    # A target outside the closed list has no sink and becomes `unapplied`.
    assert sink_for("cv", "include", "education.astrology") == ""


def test_every_letter_sink_is_a_real_letter_shape_field():
    from dataclasses import fields

    from apps.documents.letter_shape import LetterShape

    names = {f.name for f in fields(LetterShape)}
    for operation, value in (("style", "signed_declaration"),
                             ("topic", "why this programme"),
                             ("student_action", "sign it by hand"),
                             ("form", "formal_letter"), ("naming", "forbidden")):
        sink = sink_for("motivation_letter", operation, value)
        assert sink in names, (operation, value, sink)
    # Fix round 1, finding 4: a bare number is not a unit, so it names no
    # sink -- never the old silent "max_pages" fallback.
    assert sink_for("motivation_letter", "limit", 800) == ""
    for bound in BOUNDS:
        for unit in (*UNITS, "other"):
            sink = limit_sink("motivation_letter", bound, unit)
            assert sink in names | {""}, (bound, unit, sink)


def test_a_reference_letter_rule_never_binds_the_applicants_documents():
    """A reference letter is the referee's. For the applicant it is an action --
    obtain it -- and nothing else (spec §6.1)."""
    assert sink_for("reference_letter", "limit", 2) == "student_actions"
    assert sink_for("reference_letter", "format", "europass_required") == "student_actions"
    assert limit_sink("reference_letter", "maximum", "pages") == "student_actions"


@pytest.mark.parametrize(
    ("document", "bound", "unit", "sink"),
    [
        ("motivation_letter", "maximum", "words", "max_words"),
        # "approximately one A4 page" is read as a cap, as decide_letter_shape reads it.
        ("motivation_letter", "approximate", "pages", "max_pages"),
        ("motivation_letter", "maximum", "characters", "max_chars"),
        ("motivation_letter", "minimum", "words", "min_words"),
        ("motivation_letter", "minimum", "characters", "min_chars"),
        # No column holds a page floor and nothing measures one.
        ("motivation_letter", "minimum", "pages", ""),
        ("cv", "maximum", "pages", "max_pages"),
        ("cv", "maximum", "characters", "max_chars_incl_spaces"),
        # No CV checker measures a floor: a CV floor is `unapplied`, shown and counted.
        ("cv", "minimum", "pages", ""),
        ("cv", "not_a_limit", "pages", ""),
        # A note bound is a topic, never a length.
        ("motivation_letter", "section_limit", "words", ""),
        ("motivation_letter", "another_statement", "words", ""),
        ("cv", "maximum", "other", ""),
        # Task 11 (§11 gate 7): a file's size. The letter has no size field.
        ("cv", "maximum", "megabytes", "max_bytes"),
        ("motivation_letter", "maximum", "megabytes", ""),
        ("reference_letter", "minimum", "words", "student_actions"),
    ],
)
def test_a_figure_lands_on_the_sink_its_bound_and_unit_name(document, bound, unit, sink):
    assert limit_sink(document, bound, unit) == sink


def test_a_cv_character_cap_without_spaces_has_its_own_key():
    assert limit_sink("cv", "maximum", "characters", excl_spaces=True) == "max_chars_excl_spaces"
    # The letter has one character cap, measured WITH spaces: a cap read that way
    # is the stricter one, so the letter never needs the page's convention.
    assert limit_sink("motivation_letter", "maximum", "characters", excl_spaces=True) == "max_chars"


def test_the_operations_are_the_closed_list_the_spec_names():
    assert set(OPERATIONS) == {
        "limit", "language", "format", "include", "order", "emphasise", "style",
        "topic", "student_action", "form", "naming", "other",
    }


def test_form_and_naming_land_on_the_letters_own_fields_and_never_the_cv():
    """The frontier path types both (derive.LetterVerdict); the grammar may not
    lose them (addendum §6.3). A value outside the closed list has no sink."""
    assert set(FORM_VALUES) == {"essay", "formal_letter", "portal_form"}
    assert set(NAMING_VALUES) == {"required", "invited", "forbidden"}
    for value in FORM_VALUES:
        assert sink_for("motivation_letter", "form", value) == "form"
        assert sink_for("cv", "form", value) == ""
    for value in NAMING_VALUES:
        assert sink_for("motivation_letter", "naming", value) == "naming"
        assert sink_for("cv", "naming", value) == ""
    assert sink_for("motivation_letter", "form", "none") == ""
    assert sink_for("motivation_letter", "naming", "none") == ""


def test_the_documents_are_the_closed_list_the_spec_names():
    assert set(DOCUMENTS) == {"cv", "motivation_letter", "reference_letter", "other"}


def test_the_bounds_are_the_closed_list_the_addendum_names():
    assert BOUNDS == (
        "maximum", "minimum", "approximate", "section_limit", "another_statement", "not_a_limit",
    )
    assert NOTE_BOUNDS == frozenset({"section_limit", "another_statement"})
    assert "tolerance" not in BOUNDS


def test_a_rule_records_the_sentence_and_the_confidence_that_produced_it():
    rule = Rule(index=3, document="cv", operation="limit", value=2, unit="pages",
                confidence=0.93, sentence="Your CV may not exceed two pages.",
                heading="Application documents")
    assert rule.applied is True
    assert rule.note == ""


def test_a_rule_carries_its_bound_and_which_figure_it_was():
    """One sentence may state several figures -- '300-500 words' is a floor and
    a cap -- so a rule says which figure it is and which way it binds."""
    rule = Rule(index=2, document="motivation_letter", operation="limit", value=300,
                unit="words", bound="minimum", figure=0, confidence=0.93,
                sentence="The letter should be 300–500 words.")
    assert (rule.bound, rule.figure, rule.applied) == ("minimum", 0, True)
    # A rule no figure produced says so, and spaces are a boolean the
    # per-figure Noul answered -- never a string in `detail`.
    plain = Rule(index=0, document="cv", operation="style", value="photo_forbidden",
                 sentence="No photo.")
    assert (plain.figure, plain.excl_spaces, plain.detail) == (None, False, "")
    counted = Rule(index=1, document="cv", operation="limit", value=4000, unit="characters",
                   bound="maximum", figure=0, excl_spaces=True,
                   sentence="At most 4,000 characters without spaces.")
    assert limit_sink("cv", counted.bound, counted.unit,
                      excl_spaces=counted.excl_spaces) == "max_chars_excl_spaces"


def test_a_style_rule_carries_its_own_sub_value():
    """`font_family` and `font_size_minimum` name a value the sentence prints;
    without somewhere to put it the style value alone says 'a font rule' and
    nothing about which font."""
    rule = Rule(index=0, document="motivation_letter", operation="style",
                value="font_family", detail="Times New Roman", confidence=0.9,
                sentence="Use Times New Roman.")
    assert rule.detail == "Times New Roman"


def test_a_rule_below_the_bar_is_a_note_and_is_not_applied():
    rule = Rule(index=3, document="cv", operation="limit", value=2, unit="pages",
                confidence=0.40, sentence="Keep it short.", heading="", note="unsure")
    assert rule.applied is False


def test_the_condition_kinds_are_what_the_student_ledger_can_answer():
    assert set(CONDITION_KINDS) == {
        "nationality", "degree_level", "work_experience", "track", "other"
    }


def test_units_and_sections_are_not_invented_here():
    from apps.documents import grammar

    assert set(UNITS) == {"pages", "words", "characters", "megabytes"}
    # Fix round 1, finding 6: the original compared _SECTIONS to itself, a
    # tautology that would pass even if grammar.py shadowed the import with
    # its own list. Compare the module's OWN bound name instead.
    assert set(grammar._SECTIONS) == set(_SECTIONS)
    assert "education.thesis_title" in _INCLUDE_TARGETS


def test_the_grammar_names_no_sink_outside_the_real_sets_and_sinks_is_exact():
    """Fix round 1, finding 3. Walks every document x operation x value the
    closed lists allow (both `sink_for` and `limit_sink`), and checks two
    things: every non-empty sink named is a REAL place downstream can read it
    (a constraint key, a CV directive action, a LetterShape field, or the
    ApplicationPrompt column the letter's language actually lives on), and
    `SINKS` -- what a caller uses to validate a sink -- is exactly the set the
    grammar can produce. Not a superset that would hide a typo (a sink nothing
    ever names); not a subset that would reject a real one."""
    import typing
    from dataclasses import fields as dc_fields

    from apps.documents.letter_shape import LetterShape
    from apps.funding.models import ApplicationPrompt

    constraint_keys = set(typing.get_args(_CONSTRAINT_KEYS))
    letter_fields = {f.name for f in dc_fields(LetterShape)}
    prompt_fields = {f.name for f in ApplicationPrompt._meta.get_fields()}
    assert "document_language" in prompt_fields

    real_sinks = (
        constraint_keys
        | letter_fields
        | {
            "document_language", "cv_directives", "cv_format_requirement",
            "student_actions", "written_requirements", "form", "naming", "",
        }
    )

    per_operation_values: dict[str, tuple[object, ...]] = {
        "limit": UNITS,
        "language": ("en",),
        "format": FORMAT_VERDICTS,
        # A value outside the closed target list ("education.astrology") has
        # no sink and is covered by "" already reachable elsewhere below.
        "include": tuple(_INCLUDE_TARGETS),
        "order": tuple((t, d) for t in _ORDER_TARGETS for d in _ORDER_DIRECTIONS),
        "emphasise": tuple(_SECTIONS),
        # STYLE_VALUES already carries photo_required and single_file_bundle
        # (fix round 1, finding 2): both are style values with no sink now.
        "style": STYLE_VALUES,
        "topic": ("why this programme",),
        "student_action": ("sign it by hand",),
        "form": FORM_VALUES,
        "naming": NAMING_VALUES,
        "other": ("anything",),
    }
    assert set(per_operation_values) == set(OPERATIONS)

    # "" is a member of SINKS too (the unapplied marker), so it is collected
    # like any other sink rather than filtered out.
    seen: set[str] = set()
    for document in DOCUMENTS:
        for operation in OPERATIONS:
            for value in per_operation_values[operation]:
                sink = sink_for(document, operation, value)
                assert sink in real_sinks, (document, operation, value, sink)
                seen.add(sink)
        for bound in BOUNDS:
            for unit in (*UNITS, "other"):
                for excluded in (False, True):
                    sink = limit_sink(document, bound, unit, excl_spaces=excluded)
                    assert sink in real_sinks, (document, bound, unit, excluded, sink)
                    seen.add(sink)

    assert seen == SINKS


def test_the_plausibility_bands_moved_rather_than_forked():
    """The letter judge and the grammar read one definition, so a band tuned
    for one can never silently diverge from the other."""
    from apps.documents import derive, grammar

    assert derive._IMPLAUSIBLE_CAP is grammar._IMPLAUSIBLE_CAP
    assert derive._IMPLAUSIBLE_MAX is grammar._IMPLAUSIBLE_MAX
