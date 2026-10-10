"""What an award IS: `(organisation, page, heading, kind)`.

The holder-axis plan keyed an award on `(holder domain, kind)`, so a ministry's
dozens of schemes collapsed into one row whose quotes came from several of them
and a student saw one. A "find all" engine that cannot count DAAD's programmes
is not finding all.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
section 8.7 and decision-log row 4.
"""

from apps.research.funding_judge import FundingVerdicts, Line, awards, line_outcomes
from tests.research.conftest import verdict


def _reading(*verdicts) -> FundingVerdicts:
    return FundingVerdicts(verdicts=verdicts)

MASTERS = "The Masters Scholarship covers full tuition for one year."
FELLOWSHIP = "The Research Fellowship pays a monthly stipend of 1,200 EUR."
SECOND_LINE = "It is renewable once on satisfactory progress."

TWO_HEADINGS = (
    Line("Masters Scholarship", ""),
    Line(MASTERS, "Masters Scholarship"),
    Line("Research Fellowship", ""),
    Line(FELLOWSHIP, "Research Fellowship"),
)

ONE_HEADING = (
    Line("Masters Scholarship", ""),
    Line(MASTERS, "Masters Scholarship"),
    Line(SECOND_LINE, "Masters Scholarship"),
)


def test_two_awards_under_two_headings_on_one_page_are_two_decisions():
    """Measured shape: an agency page lists several schemes of one kind, each
    under its own heading. Grouped by (kind, scope) they become one row whose
    quotes come from two different awards -- and a student sees one."""
    readings = [_reading(verdict(1), verdict(3))] * 3
    result = awards(line_outcomes(TWO_HEADINGS, readings))

    assert len(result.decisions) == 2
    assert {d.heading for d in result.decisions} == {
        "Masters Scholarship",
        "Research Fellowship",
    }
    # And each decision carries only its own award's sentence.
    by_heading = {d.heading: d for d in result.decisions}
    assert by_heading["Masters Scholarship"].quotes == (MASTERS,)
    assert by_heading["Research Fellowship"].quotes == (FELLOWSHIP,)


def test_one_award_spanning_several_lines_under_one_heading_stays_one_decision():
    """The other half: the grouping must not shatter a multi-line award, which
    is what the verbosity finding (2026-09-22 hand-sample) is about."""
    readings = [_reading(verdict(1), verdict(2))] * 3
    result = awards(line_outcomes(ONE_HEADING, readings))

    assert len(result.decisions) == 1
    (decision,) = result.decisions
    assert decision.heading == "Masters Scholarship"
    assert decision.quotes == (MASTERS, SECOND_LINE)


def test_two_kinds_under_one_heading_are_still_two_decisions():
    """Heading is added to the key, it does not replace it. A page that
    describes a tuition waiver and a paid placement under one heading is still
    describing two different things."""
    readings = [
        _reading(verdict(1), verdict(2, kind="I7_PAID_PLACEMENT"))
    ] * 3
    result = awards(line_outcomes(ONE_HEADING, readings))

    assert len(result.decisions) == 2
    assert {d.heading for d in result.decisions} == {"Masters Scholarship"}
    assert {d.kind for d in result.decisions} == {
        "I2_PROGRAMME_ATTACHED",
        "I7_PAID_PLACEMENT",
    }


def test_the_models_six_word_name_is_not_part_of_identity():
    """`name` is a label a model chose and it varies between reads; a heading is
    the site's own structure. Keying on the name would make a re-read of an
    unchanged page mint a second row."""
    readings = [
        _reading(verdict(1, name="Masters Scholarship")),
        _reading(verdict(1, name="Master's scholarship award")),
        _reading(verdict(1, name="Masters Scholarship")),
    ]
    result = awards(line_outcomes(ONE_HEADING, readings))
    assert len(result.decisions) == 1
