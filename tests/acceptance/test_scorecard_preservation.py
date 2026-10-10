"""Regenerating the scorecard must not delete its hand-written half. Db-free.

docs/validation/phase1-scorecard.md is a hybrid: render_markdown() produces the
metric tables at the top, and everything from the first `---` rule onward is
written by hand (the "Approved-requirement traceability" table and the two
narrative sections). --output used to truncate the file to the generated half,
silently destroying ~95 lines of acceptance evidence -- on the one day someone
runs a real go/no-go. See docs/runbooks/shadow-pilot.md sequencing step 2.
"""

from scripts.evaluate_phase1 import preserved_tail

HAND_WRITTEN = """---

## What this document does and does not prove

**Proven:** the acceptance-gate machinery.

## Approved-requirement traceability

| Requirement | Proof mechanism | Status |
|---|---|---|
| P1-2 Worldwide hybrid discovery | tests/research/test_discovery.py | PASS (retrieval primitives) |
"""


def test_hand_written_tail_survives_regeneration(tmp_path):
    scorecard = tmp_path / "phase1-scorecard.md"
    scorecard.write_text("# Phase 1 acceptance scorecard\n\n| old | table |\n\n" + HAND_WRITTEN)

    tail = preserved_tail(scorecard)

    assert "Approved-requirement traceability" in tail
    assert "P1-2 Worldwide hybrid discovery" in tail
    assert tail.lstrip("\n").startswith("---")


def test_generated_tables_above_the_rule_are_dropped(tmp_path):
    scorecard = tmp_path / "phase1-scorecard.md"
    scorecard.write_text("# Phase 1 acceptance scorecard\n\n| stale | metrics |\n\n" + HAND_WRITTEN)

    tail = preserved_tail(scorecard)

    assert "stale" not in tail


def test_missing_file_has_no_tail(tmp_path):
    assert preserved_tail(tmp_path / "does-not-exist.md") == ""


def test_file_without_the_rule_has_no_tail(tmp_path):
    scorecard = tmp_path / "phase1-scorecard.md"
    scorecard.write_text("# Phase 1 acceptance scorecard\n\n| only | generated |\n")

    assert preserved_tail(scorecard) == ""


def test_table_separators_are_not_mistaken_for_the_rule(tmp_path):
    """`|---|---|` inside a generated table must not be read as the boundary."""
    scorecard = tmp_path / "phase1-scorecard.md"
    scorecard.write_text("| Metric | Value |\n|---|---|\n| Precision | 1.0 |\n\n" + HAND_WRITTEN)

    tail = preserved_tail(scorecard)

    assert "Precision" not in tail
    assert "Approved-requirement traceability" in tail
