"""The 30-card hand check: a seeded sample, and a score that fails loudly."""

import csv

import pytest
from django.core.management import CommandError, call_command

_FIELDS = ("page_url", "award", "field", "state", "value", "quote")


def _cards(path, awards):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        writer.writeheader()
        for index in range(awards):
            for field in ("amount", "duration"):
                writer.writerow({
                    "page_url": f"https://h{index}.test/", "award": f"Award {index}",
                    "field": field, "state": "FILLED", "value": "v", "quote": "q",
                })


def _mark(path, verdicts):
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for row, verdict in zip(rows, verdicts, strict=True):
        row["correct"] = verdict
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_the_sample_is_seeded_and_takes_whole_cards(tmp_path):
    cards, one, two = tmp_path / "cards.csv", tmp_path / "a.csv", tmp_path / "b.csv"
    _cards(cards, 50)
    for out in (one, two):
        call_command("card_check", sample=str(cards), count=30, seed=13, out=str(out))
    assert one.read_text() == two.read_text()
    rows = list(csv.DictReader(one.open(encoding="utf-8")))
    assert len({row["award"] for row in rows}) == 30 and len(rows) == 60
    assert all(row["correct"] == "" for row in rows)


def test_the_score_passes_at_ninety_percent_with_no_wrong_amount(tmp_path):
    cards, check = tmp_path / "cards.csv", tmp_path / "check.csv"
    _cards(cards, 10)
    call_command("card_check", sample=str(cards), count=10, seed=1, out=str(check))
    rows = list(csv.DictReader(check.open(encoding="utf-8")))
    _mark(check, ["no" if row["field"] == "duration" and row["award"] == "Award 3" else "yes"
                  for row in rows])
    call_command("card_check", score=str(check))   # 19 of 20, no amount wrong


def test_one_wrong_amount_fails_the_gate_whatever_the_rate(tmp_path):
    cards, check = tmp_path / "cards.csv", tmp_path / "check.csv"
    _cards(cards, 10)
    call_command("card_check", sample=str(cards), count=10, seed=1, out=str(check))
    rows = list(csv.DictReader(check.open(encoding="utf-8")))
    _mark(check, ["no" if row["field"] == "amount" and row["award"] == "Award 3" else "yes"
                  for row in rows])
    with pytest.raises(CommandError, match="wrong amount"):
        call_command("card_check", score=str(check))


def test_an_unmarked_row_fails_the_score(tmp_path):
    cards, check = tmp_path / "cards.csv", tmp_path / "check.csv"
    _cards(cards, 3)
    call_command("card_check", sample=str(cards), count=3, seed=1, out=str(check))
    with pytest.raises(CommandError, match="unmarked"):
        call_command("card_check", score=str(check))
