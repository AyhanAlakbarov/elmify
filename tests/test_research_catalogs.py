"""The rule catalogs are data, and nothing read them.

`docs/research/*.csv` hold 212 researched rules that CLAUDE.md tells every
session to consult before researching CV or letter conventions, and several are
cited by ID from code (`S-010`, `S-011`, `S-013`, `S-026`). They were edited
only by hand, so a broken row was invisible until someone tried to read it.

That is not hypothetical. Amending two rules on 2026-09-15 by string
substitution inserted un-doubled `"` inside an already-quoted field, which
split S-035 into 19 columns and S-038 into 51, silently, with the rule text
scattered across them. The file still looked fine in a diff.
"""

import csv
from pathlib import Path

import pytest

CATALOGS = {
    "cv-rules.csv": "R",
    "cv-style-rules.csv": "S",
    "letter-rules.csv": "L",
}
HEADER = [
    "ID",
    "Rule",
    "Applies to",
    "Scope",
    "Binding or advisory",
    "Source (tier)",
    "Source URL [provenance]",
    "Verified for cycle",
    "Confidence",
]
RESEARCH = Path(__file__).resolve().parents[1] / "docs" / "research"


def _rows(name: str) -> list[list[str]]:
    with (RESEARCH / name).open(newline="") as handle:
        return list(csv.reader(handle))


@pytest.mark.parametrize("name,prefix", CATALOGS.items())
def test_every_rule_row_has_exactly_the_declared_columns(name: str, prefix: str) -> None:
    header, *rows = _rows(name)
    assert header == HEADER, name
    malformed = [
        (row[0] if row else "<empty>", len(row)) for row in rows if len(row) != len(HEADER)
    ]
    assert not malformed, f"{name}: rows with the wrong column count: {malformed}"


@pytest.mark.parametrize("name,prefix", CATALOGS.items())
def test_rule_ids_are_unique_and_correctly_prefixed(name: str, prefix: str) -> None:
    ids = [row[0] for row in _rows(name)[1:]]
    assert ids == sorted(set(ids), key=ids.index), f"{name}: duplicate rule id"
    wrong = [rule_id for rule_id in ids if not rule_id.startswith(f"{prefix}-")]
    assert not wrong, f"{name}: ids must start with {prefix}-: {wrong}"


@pytest.mark.parametrize("name,prefix", CATALOGS.items())
def test_no_rule_states_nothing(name: str, prefix: str) -> None:
    """A row whose Rule or ID is blank is a split row wearing a valid shape:
    the column count can survive a bad edit that moved the text elsewhere."""
    empty = [row[0] for row in _rows(name)[1:] if not row[0].strip() or not row[1].strip()]
    assert not empty, f"{name}: rows with no id or no rule text: {empty}"
