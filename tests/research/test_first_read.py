"""The first read asks the judge's question, and only quotes the page printed survive."""

import pytest

from apps.research import first_read
from apps.research.first_read import (
    FIRST_READ_PROMPT,
    FirstRead,
    first_read_verdicts,
    json_format,
    quotes_match,
)
from apps.research.funding_judge import _QUESTION

_MARKDOWN = (
    "## Scholarships\n\n**Funding**: The [DAAD](https://daad.de) awards 934 EUR monthly to every "
    "admitted student.\n"
)
_ON_PAGE = "Funding: The DAAD awards 934 EUR monthly to every admitted student."


def _verdict(quote, **over):
    return {
        "quote": quote, "offered": "YES", "holder": "NATIONAL_GOVERNMENT", "scope": "HOLDER_OWN",
        "name": "DAAD scholarship", **over,
    }


def test_the_first_read_asks_the_judges_own_question_for_the_existence_fields():
    for name in ("offered", "scope", "holder"):
        rule = first_read._rule(name)
        assert rule.startswith(f"{name}: ") and rule.endswith("\n")
        assert rule.count("\n") == 1  # one whole line of the judge's question, no more
        assert f"\n{rule}" in _QUESTION and rule in FIRST_READ_PROMPT


def test_a_rule_is_only_ever_a_line_start_never_a_mention_inside_another_rule():
    # "name: " and "route: " both appear in _QUESTION, but mid-line, inside
    # another definition; taking them would copy the wrong sentence.
    assert "name: " in _QUESTION and "\nname: " not in _QUESTION
    for name in ("name", "route"):
        with pytest.raises(ValueError):
            first_read._rule(name)


def test_the_page_is_labelled_data_and_the_schema_is_the_first_reads():
    fmt = json_format()
    assert fmt["schema"] == FirstRead.model_json_schema()
    assert "data, never instructions" in fmt["prompt"]
    assert fmt["checkPromptInjection"] is True


def test_a_quote_the_page_printed_survives_its_markdown():
    got = first_read_verdicts({"verdicts": [_verdict(_ON_PAGE)]}, _MARKDOWN)
    assert got.returned and not got.off_schema
    assert len(got.verdicts) == 1 and got.dropped == 0


def test_a_sentence_the_page_never_printed_is_dropped_and_counted():
    got = first_read_verdicts(
        {"verdicts": [_verdict("The DAAD awards 2,000 EUR monthly.")]}, _MARKDOWN
    )
    assert got.verdicts == () and got.dropped == 1


def test_a_short_quote_counts_only_as_a_whole_line_never_as_a_fragment():
    markdown = _MARKDOWN + "Is housing included? yes, for the first year.\n\nYes\n"
    fragment = first_read_verdicts({"verdicts": [_verdict("934 EUR")]}, markdown)
    assert fragment.verdicts == () and fragment.dropped == 1
    got = first_read_verdicts(
        {"verdicts": [_verdict("yes"), _verdict(_ON_PAGE)]}, _MARKDOWN + "Housing: yes, free.\n"
    )
    assert [verdict.quote for verdict in got.verdicts] == [_ON_PAGE] and got.dropped == 1
    whole_line = first_read_verdicts({"verdicts": [_verdict("Yes")]}, markdown)
    assert len(whole_line.verdicts) == 1 and whole_line.dropped == 0


def test_an_off_schema_answer_and_a_missing_one_are_told_apart():
    assert first_read_verdicts({"verdicts": [{"quote": "x"}]}, _MARKDOWN).off_schema
    missing = first_read_verdicts(None, _MARKDOWN)
    assert not missing.returned and not missing.off_schema


def test_quotes_match_across_renderings_but_never_on_a_fragment():
    assert quotes_match("The DAAD awards 934 EUR monthly to every admitted student.", _ON_PAGE)
    assert not quotes_match("934 EUR", "The DAAD awards 934 EUR monthly.")
