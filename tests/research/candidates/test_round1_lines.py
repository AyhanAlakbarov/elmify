import csv
from pathlib import Path

from apps.research.candidates import find_all

GOLD = (Path(__file__).resolve().parents[3] / "docs" / "research" / "gold"
        / "2026-10-04-round-1-owner-gold.csv")


def _rows(kind):
    with GOLD.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [r for r in rows if r["kind"] == kind and r["verdict"] == "correct"]


def test_every_correct_deadline_line_has_a_date_candidate():
    missing = []
    for row in _rows("deadline"):
        found = find_all([row["line_text"]])
        if not (found.dates or found.relative_dates):
            missing.append(row["line_text"])
    assert missing == []


def test_report_money_lines_without_an_amount():
    missing = [r["line_text"] for r in _rows("money") if not find_all([r["line_text"]]).amounts]
    # money lines that state coverage in words ("all expenses are covered") carry no amount;
    # this number is a ratchet: lower it when a finder improves, never raise it
    assert len(missing) <= 20, missing
