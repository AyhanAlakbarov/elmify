"""Tests for the Firecrawl JSON quote reader."""

from apps.research.engine_eval.firecrawl_reader import firecrawl_json_format, read_firecrawl
from apps.research.engine_eval.items import Item

ITEMS = [Item(id="p0l0", page="u", language="en", scheme="s", half="score",
              text="Applications close on 15 January 2027 at 14:00 CET.", heading=""),
         Item(id="p0l1", page="u", language="en", scheme="s", half="score",
              text="The programme is financed by the Government of Hungary.", heading="")]


def test_a_quote_marks_only_the_line_it_is_on():
    got = read_firecrawl(
        ITEMS,
        {
            "u": {
                "application_date": [
                    "Applications close on 15 January 2027 at 14:00 CET."
                ]
            }
        },
    )
    assert got["p0l0"]["application_date"] == 1.0
    assert got["p0l1"]["application_date"] == 0.0


def test_a_quote_not_on_any_line_marks_nothing():
    got = read_firecrawl(
        ITEMS,
        {"u": {"application_date": ["Applications close in March."]}},
    )
    assert got["p0l0"]["application_date"] == 0.0


def test_no_extract_leaves_the_page_out():
    assert read_firecrawl(ITEMS, {}) == {}


def test_the_format_asks_for_verbatim_sentences_and_screens_injection():
    fmt = firecrawl_json_format()
    assert fmt["checkPromptInjection"] is True
    assert "verbatim" in str(fmt["prompt"]).lower()
    assert set(fmt["schema"]["properties"]) >= {"application_date", "level_rule"}
