"""Two cost CSVs join on content digest; the comparison never hides what it cannot price."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.research.cost_compare import COST_COLUMNS, compare, write_cost_csv


def _row(digest, usd, *, served=1, unpriced=0, openai_input=100):
    row = dict.fromkeys(COST_COLUMNS, "0")
    row.update(
        host="h.test", final_url=f"https://h.test/{digest}", content_sha256=digest,
        tier="standard", usd=f"{usd:.6f}", served=str(served), unpriced=str(unpriced),
        openai_input=str(openai_input),
    )
    return row


def test_pages_join_on_their_content_digest_and_unmatched_ones_are_counted():
    result = compare([_row("a", 0.10), _row("b", 0.20)], [_row("a", 0.05), _row("c", 0.01)])
    assert (result.matched, result.only_before, result.only_after) == (1, 1, 1)
    assert result.usd_before == pytest.approx(0.10)
    assert result.usd_after == pytest.approx(0.05)
    assert result.median_ratio == pytest.approx(0.5)


def test_verdicts_and_tokens_are_summed_over_matched_pages_only():
    result = compare(
        [_row("a", 0.1, served=2, openai_input=10), _row("b", 0.1, served=5)],
        [_row("a", 0.1, served=1, openai_input=4)],
    )
    assert result.verdicts_before["served"] == 2 and result.verdicts_after["served"] == 1
    assert result.tokens_before["openai_input"] == 10 and result.tokens_after["openai_input"] == 4


def test_unpriced_readings_are_named_in_the_report():
    result = compare([_row("a", 0.1, unpriced=3)], [_row("a", 0.05)])
    assert any("unpriced" in line for line in result.lines())


def test_a_saving_is_reported_as_a_share():
    lines = compare([_row("a", 0.2)], [_row("a", 0.1)]).lines()
    assert any("saving=50.0%" in line for line in lines)


def test_the_command_prints_the_comparison_and_the_noise_floor(tmp_path):
    before, after, repeat = (tmp_path / name for name in ("b.csv", "a.csv", "r.csv"))
    write_cost_csv(before, [_row("a", 0.2, served=2)])
    write_cost_csv(after, [_row("a", 0.1, served=2)])
    write_cost_csv(repeat, [_row("a", 0.2, served=1)])
    out = StringIO()
    call_command(
        "funding_cost_compare", str(before), str(after), repeat=str(repeat), stdout=out
    )
    text = out.getvalue()
    assert "saving=50.0%" in text
    assert "noise floor" in text and "served=2->1" in text



def test_repeated_digests_and_zero_cost_pages_are_counted_not_hidden():
    result = compare(
        [_row("a", 0.0), _row("a", 0.3), _row("b", 0.2)], [_row("a", 0.1), _row("b", 0.1)]
    )
    assert (result.duplicates, result.unratioed, result.matched) == (1, 1, 2)
    text = "\n".join(result.lines())
    assert "1 rows repeat a digest" in text and "1 cost $0 before" in text
