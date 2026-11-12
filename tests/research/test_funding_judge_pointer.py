"""Spec 2026-09-27 §4.7: a pointer names a BODY, copied from its own line."""

from apps.research.funding_judge import (
    _QUESTION,
    FundingVerdicts,
    Line,
    LineVerdict,
    PointerLead,
    awards,
    line_outcomes,
)

LINE = Line("Students may also apply for the Ministry of Culture's MyStart scholarship.", "Funding")


def _pointer(funder: str) -> LineVerdict:
    return LineVerdict(
        line=0, offered="YES", kind="I1_UNIVERSITY_WIDE", scope="POINTER",
        internationals_included="UNSTATED", nationality_shape="UNSTATED",
        route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT", tuition="UNSTATED",
        living="UNSTATED", holder="NATIONAL_GOVERNMENT", name="MyStart scholarship",
        funder=funder,
    )


def _read(*funders: str) -> tuple[PointerLead, ...]:
    readings = [FundingVerdicts(verdicts=(_pointer(f),)) for f in funders]
    return awards(line_outcomes((LINE,), readings)).pointer_leads


def test_the_body_a_pointer_names_is_copied_from_its_line() -> None:
    (lead,) = _read("Ministry of Culture", "Ministry of Culture", "Ministry of Culture")
    assert lead == PointerLead(
        quote=LINE.text, name="MyStart scholarship", holder="NATIONAL_GOVERNMENT",
        funder="Ministry of Culture",
    )


def test_a_funder_no_reading_copied_from_the_line_is_dropped() -> None:
    """A paraphrase is a name the page never printed; the resolver would search
    for it as if it had."""
    (lead,) = _read(
        "Azerbaijan Ministry of Culture", "Azerbaijan Ministry of Culture",
        "Ministry of Culture of Azerbaijan",
    )
    assert lead.funder == ""


def test_the_most_common_copy_wins_among_copies_on_the_line() -> None:
    (lead,) = _read("Ministry of Culture", "Ministry of Culture", "the Ministry")
    assert lead.funder == "Ministry of Culture"


def test_the_question_asks_for_the_funder_only_on_pointer_lines() -> None:
    assert "funder: on a POINTER line only" in _QUESTION
