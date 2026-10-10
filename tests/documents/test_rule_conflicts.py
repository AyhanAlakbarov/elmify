from apps.documents.grammar import Rule
from apps.documents.rule_sinks import resolve_conflicts


def _rule(index, operation, value, **kw):
    return Rule(index=index, document=kw.pop("document", "cv"), operation=operation,
                value=value, sentence=kw.pop("sentence", f"sentence {index}"),
                confidence=kw.pop("confidence", 0.95), **kw)


def test_two_page_limits_keep_the_tighter_one_and_note_both():
    """The page and its PDF disagree. A person is not asked; the safer value
    applies and both sentences are on the document (spec §6.3)."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages", sentence="no more than two pages"),
        _rule(1, "limit", 3, unit="pages", sentence="up to three pages"),
    ))
    applied = [r for r in resolved if r.applied]
    notes = [r for r in resolved if r.note == "conflict"]
    assert [r.value for r in applied] == [2]
    assert {r.sentence for r in notes} == {"no more than two pages", "up to three pages"}


def test_two_floors_keep_the_larger_one():
    """A floor's safe side is the other way round: shipping under a stated
    minimum is a rejection (HBKU, M-091)."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 300, unit="words", bound="minimum", document="motivation_letter"),
        _rule(1, "limit", 500, unit="words", bound="minimum", document="motivation_letter"),
    ))
    assert [r.value for r in resolved if r.applied] == [500]
    assert sum(r.note == "conflict" for r in resolved) == 2


def test_a_range_is_a_floor_and_a_cap_not_a_conflict():
    resolved = resolve_conflicts((
        _rule(0, "limit", 300, unit="words", bound="minimum", figure=0,
              document="motivation_letter"),
        _rule(0, "limit", 500, unit="words", bound="maximum", figure=1,
              document="motivation_letter"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0
    assert sorted(r.value for r in resolved if r.applied) == [300, 500]


def test_a_word_limit_and_a_page_limit_are_not_a_conflict():
    """Different units are different keys downstream (max_words vs max_pages),
    so both stand."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages"),
        _rule(1, "limit", 800, unit="words"),
    ))
    assert sorted(r.value for r in resolved if r.applied) == [2, 800]


def test_a_cap_in_each_unit_from_one_sentence_is_not_a_conflict():
    resolved = resolve_conflicts((
        _rule(0, "limit", 3500, unit="characters", bound="maximum", figure=0,
              document="motivation_letter"),
        _rule(0, "limit", 500, unit="words", bound="approximate", figure=1,
              document="motivation_letter"),
    ))
    assert sorted(r.value for r in resolved if r.applied) == [500, 3500]


def test_one_sentences_two_caps_in_one_unit_resolve_and_keep_their_figures():
    """'At most two pages, ideally one' -- an approximation is read as a cap, so
    the smaller applies; each note names its own figure, so the two notes stay
    two rules downstream."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages", bound="maximum", figure=0),
        _rule(0, "limit", 1, unit="pages", bound="approximate", figure=1),
    ))
    assert [r.value for r in resolved if r.applied] == [1]
    assert {(r.index, r.figure) for r in resolved if r.note == "conflict"} == {(0, 0), (0, 1)}


def test_a_decimal_page_cap_is_a_number_like_any_other():
    resolved = resolve_conflicts((
        _rule(0, "limit", 1.5, unit="pages"),
        _rule(1, "limit", 2, unit="pages"),
    ))
    assert [r.value for r in resolved if r.applied] == [1.5]


def test_a_cv_cap_with_and_without_spaces_are_two_keys():
    resolved = resolve_conflicts((
        # <!-- reconciled 2026-09-26: the spaces reading is Rule.excl_spaces -->
        _rule(0, "limit", 4000, unit="characters", excl_spaces=True),
        _rule(1, "limit", 4500, unit="characters"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0


def test_two_format_verdicts_that_differ_fall_back_to_any():
    """`any` is the no-egress default. A page that contradicts itself about
    Europass must not resolve to the one action that moves student data."""
    resolved = resolve_conflicts((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "any"),
    ))
    applied = [r for r in resolved if r.applied]
    assert [r.value for r in applied] == ["any"]
    assert sum(r.note == "conflict" for r in resolved) == 2


def test_two_europass_verdicts_that_differ_apply_nothing_and_never_crash():
    """No sentence stated `any`, so no rule carries it: the conflict notes are
    all that is left, and format_decision reads them as any + UNDECIDED."""
    resolved = resolve_conflicts((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "europass_preferred"),
    ))
    assert [r for r in resolved if r.applied] == []
    assert sum(r.note == "conflict" for r in resolved) == 2


def test_two_language_rules_that_differ_do_not_crash_on_a_list():
    resolved = resolve_conflicts((
        _rule(0, "language", ["en", "fr"]),
        _rule(1, "language", "de"),
    ))
    assert [r for r in resolved if r.applied] == []
    assert sum(r.note == "conflict" for r in resolved) == 2


def test_two_identical_values_are_not_a_conflict():
    resolved = resolve_conflicts((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "europass_required"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0
    assert sum(r.applied for r in resolved) == 2


def test_the_same_operation_on_different_documents_is_not_a_conflict():
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages", document="cv"),
        _rule(1, "limit", 1, unit="pages", document="motivation_letter"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0


def test_a_rule_already_carrying_a_note_never_joins_a_conflict():
    """A note is not at the bar, so it cannot contradict anything -- and
    counting it would turn one uncertain sentence into two notes."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages"),
        _rule(1, "limit", 3, unit="pages", note="third_party"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0
    assert [r.value for r in resolved if r.applied] == [2]


def test_two_include_directives_on_different_fields_are_both_applied():
    """`include` is set-valued: a page may require three fields. Only a
    single-valued operation can contradict itself."""
    resolved = resolve_conflicts((
        _rule(0, "include", "education.ects_credits"),
        _rule(1, "include", "education.thesis_title"),
    ))
    assert sum(r.applied for r in resolved) == 2


def test_two_topics_are_both_kept():
    resolved = resolve_conflicts((
        _rule(0, "topic", "why this programme", document="motivation_letter"),
        _rule(1, "topic", "your career plans", document="motivation_letter"),
    ))
    assert sum(r.applied for r in resolved) == 2


# <!-- task 8 fix round 1, finding 5: not_a_format_rule is not a verdict -->
def test_not_a_format_rule_never_joins_a_format_dispute():
    resolved = resolve_conflicts((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "not_a_format_rule"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0
    assert [r.value for r in resolved if r.applied] == ["europass_required", "not_a_format_rule"]
