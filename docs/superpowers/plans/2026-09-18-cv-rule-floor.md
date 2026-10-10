# CV Rule Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Account for every researched CV rule — apply the ones the engine can carry, and record the rest as explicitly unapplicable — so a rule can never again sit in a CSV with nothing reading it.

**Architecture:** A manifest module holds one dict of rule ids the engine cannot express, with a reason each. A completeness test asserts every `R-*`/`S-*` id in the two research CSVs lands in exactly one of four places: `render._UNIVERSAL_RULES` (code), `catalog_seed.SEED_RULES` (scope-scoped `CatalogRule`s), cited by id somewhere in `apps/`, or the unapplicable dict. A checked-in `PENDING` list holds what has not been adjudicated yet and shrinks to empty; the test fails if an id leaves `PENDING` without arriving somewhere.

**Tech Stack:** Python 3, Django, pytest, pydantic (`ConstraintRule`).

**Spec:** `docs/superpowers/specs/2026-09-17-cv-rule-discovery-design.md` (§1 tier rules, §5 the floor)

**What kind of plan this is.** Task 1 is ordinary code. Tasks 2-8 are **adjudication**: each reads a
batch of researched rules and decides where each one belongs. The plan gives the decision procedure
and the exact form of every entry, but it does not pre-decide the 86 rules — that judgement needs the
rule's own wording and source in front of you, which is Step 1 of every task. Expect most outcomes to
be `UNAPPLICABLE`; `catalog_seed.py` puts the mappable share at about a third.

## Global Constraints

- **The universal tier is CODE, not data.** New universal rules go in `apps/documents/render.py::_UNIVERSAL_RULES`. Do not add a UNIVERSAL-scoped `CatalogRule`; `render.py`'s own comment gives the reason — a seeded rule depends on `manage.py seed_cv_rules` having been run by hand, and "a check that silently never fires is worse than no check".
- **COUNTRY-scoped rules are `ADVISORY_*`, never `BINDING`, and never `language`** (spec §1). All five existing country rules already obey this.
- **Only keys in `apps/documents/constraints.py::_CONSTRAINT_KEYS` may be used.** Never invent a key. A rule the vocabulary cannot carry goes in the unapplicable dict — that is what the dict is for, not a defeat.
- **`rule_text` is copied verbatim from the CSV's `Rule` column**, and `source_url` from its `Source URL [provenance]` column (take the URL before any trailing ` [note]`). `rule_id` max length is 20 chars.
- **Run pytest with `POSTGRES_DB=tehsil_cv_corpus`** in this worktree. The shared `test_tehsil` database gets dropped by other sessions mid-run.
- **Never `git add -A`.** Other sessions share this checkout. Commit with an explicit pathspec: `git commit <paths> -m ...`.

---

### Task 1: The manifest and the completeness test

**Files:**
- Create: `apps/documents/rule_manifest.py`
- Test: `tests/documents/test_rule_manifest.py`

**Interfaces:**
- Produces: `UNAPPLICABLE: dict[str, str]` (rule id → reason), `PENDING: frozenset[str]`, `research_rule_ids() -> dict[str, str]` (id → the CSV's "Applies to" value), `accounted_for() -> dict[str, str]` (id → bucket name). Tasks 2-8 consume all four.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_rule_manifest.py
"""Every researched CV rule is accounted for, or the build says so."""

from apps.documents.rule_manifest import PENDING, accounted_for, research_rule_ids


def test_every_research_rule_is_accounted_for_or_explicitly_pending() -> None:
    """The 126 rules in docs/research/cv-rules.csv and cv-style-rules.csv are the
    product's whole researched knowledge of how a CV should be written. A rule
    that is in neither the engine nor this manifest is invisible -- which is how
    evidence/extraction.py came to write CV prose obeying no style rule for weeks.
    """
    ids = set(research_rule_ids())
    placed = set(accounted_for())

    assert placed <= ids, f"manifest names rules no CSV has: {sorted(placed - ids)}"
    assert PENDING <= ids, f"PENDING names rules no CSV has: {sorted(PENDING - ids)}"
    unaccounted = ids - placed - PENDING
    assert not unaccounted, (
        f"{len(unaccounted)} researched rules are in no bucket and not pending: "
        f"{sorted(unaccounted)}"
    )


def test_a_pending_rule_is_not_also_accounted_for() -> None:
    """PENDING means 'not yet adjudicated'. An id in both is an adjudication
    someone forgot to finish removing from the list."""
    both = PENDING & set(accounted_for())
    assert not both, f"adjudicated but still listed pending: {sorted(both)}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents/test_rule_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.documents.rule_manifest'`

- [ ] **Step 3: Write the manifest**

```python
# apps/documents/rule_manifest.py
"""Where each researched CV rule ended up.

docs/research/cv-rules.csv (93 rules) and cv-style-rules.csv (33) are the
product's researched knowledge of how a CV should be written. Each is applied
somewhere, or named here as something the engine cannot express. Nothing is
allowed to be neither -- a rule sitting in a CSV with no reader is the failure
this module exists to make impossible.

Four places a rule may be:
  universal   -- render.py::_UNIVERSAL_RULES, applied to every render
  seeded      -- catalog_seed.SEED_RULES, a scope-scoped CatalogRule
  cited       -- implemented at its point of use and cited there by id
  unapplicable -- UNAPPLICABLE below, with the reason

`cited` is found by grepping apps/ for the id. That is deliberately generous:
it counts a rule a human named in a comment while writing the code it governs.
It cannot tell an implementation from a mention, so it is evidence that someone
considered the rule, not that the rule is enforced.
"""

from __future__ import annotations

import csv
import functools
import pathlib
import re

RESEARCH_DIR = pathlib.Path(__file__).resolve().parents[2] / "docs" / "research"
_CSVS = ("cv-rules.csv", "cv-style-rules.csv")
_RULE_ID = re.compile(r"\b[RS]-[0-9]{3}\b")
_APPS = pathlib.Path(__file__).resolve().parents[1]

#: Rules no key in _CONSTRAINT_KEYS can carry, with the reason. Filled in by
#: adjudication, one batch at a time; see the plan of 2026-09-18.
UNAPPLICABLE: dict[str, str] = {}

#: Not yet adjudicated. Shrinks to empty; the test refuses an id that leaves
#: this set without arriving in a bucket.
PENDING: frozenset[str] = frozenset()


@functools.cache
def research_rule_ids() -> dict[str, str]:
    """Every rule id in the research CSVs, mapped to its "Applies to" value."""
    out: dict[str, str] = {}
    for name in _CSVS:
        with (RESEARCH_DIR / name).open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                out[row["ID"]] = row["Applies to"]
    return out


@functools.cache
def _cited_in_code() -> frozenset[str]:
    """Rule ids named anywhere under apps/, excluding this module itself."""
    found: set[str] = set()
    for path in _APPS.rglob("*.py"):
        if path.name == "rule_manifest.py":
            continue
        found.update(_RULE_ID.findall(path.read_text(encoding="utf-8")))
    return frozenset(found)


def accounted_for() -> dict[str, str]:
    """Rule id -> the name of the bucket holding it."""
    from .catalog_seed import SEED_RULES
    from .render import _UNIVERSAL_RULES

    placed: dict[str, str] = {}
    for rule in _UNIVERSAL_RULES:
        placed[rule.rule_id] = "universal"
    for row in SEED_RULES:
        placed.setdefault(str(row["rule_id"]), "seeded")
    known = set(research_rule_ids())
    for rule_id in _cited_in_code() & known:
        placed.setdefault(rule_id, "cited")
    for rule_id, reason in UNAPPLICABLE.items():
        if not reason.strip():
            # Not an assert: bandit's B101 fails the build on one, and an
            # empty reason is exactly the silent hole this module prevents.
            raise ValueError(f"{rule_id} is unapplicable for no stated reason")
        placed.setdefault(rule_id, "unapplicable")
    return placed
```

- [ ] **Step 4: Run the test — it should now fail on the real gap**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents/test_rule_manifest.py -q`
Expected: FAIL — "86 researched rules are in no bucket and not pending" listing R-001, R-002, R-003, …

- [ ] **Step 5: Fill PENDING with exactly those 86 ids**

Replace the `PENDING` assignment in `apps/documents/rule_manifest.py`:

```python
PENDING: frozenset[str] = frozenset({
    # data-field (Task 2)
    "R-016", "R-019", "R-022", "R-034", "R-035", "R-036", "R-037", "R-038",
    "R-039", "R-041", "R-046", "R-071", "R-073", "R-076",
    # content (Task 3)
    "R-014", "R-028", "R-042", "R-051", "R-052", "R-061", "R-069", "R-084", "S-029",
    # file-output (Task 4)
    "R-013", "R-018", "R-020", "R-021", "R-043", "R-044", "R-045", "R-047",
    "R-049", "R-053", "R-067", "R-068", "R-082", "R-083",
    # typography + element (Task 5)
    "S-002", "S-003", "S-004", "S-005", "S-006", "S-012", "S-023", "S-025",
    "S-031", "S-033",
    # layout (Task 6)
    "R-003", "R-004", "R-005", "R-006", "R-011", "R-026", "R-058", "R-059",
    "R-062", "R-063", "R-065", "R-075", "R-085", "S-017", "S-018", "S-019",
    "S-020", "S-021", "S-032",
    # validation-flag (Task 7)
    "R-001", "R-002", "R-009", "R-025", "R-050", "R-054", "R-055", "R-074",
    "R-077", "R-081", "R-086", "R-087", "R-088", "R-089", "R-090", "R-091",
    "R-092", "R-093",
    # reader-evidence + structure (Task 8)
    "S-024", "S-030",
})
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents/test_rule_manifest.py -q`
Expected: PASS (2 passed)

- [ ] **Step 7: Run the wider suites the manifest touches**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents -q && uv run ruff check . && uv run mypy apps config`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git commit apps/documents/rule_manifest.py tests/documents/test_rule_manifest.py \
  -m "documents: account for every researched CV rule, or fail the build

86 of the 126 researched CV rules are cited nowhere in apps/ and seeded
nowhere -- researched, sourced, graded, and read by nothing. This manifest
makes that state impossible to reach silently: every id is in a bucket or on
an explicit PENDING list, and leaving PENDING without arriving somewhere
fails the test."
```

---

### Task 2: Adjudicate the 14 `data-field` rules

These are the likeliest to map: `_CONSTRAINT_KEYS` carries `photo_allowed`, `date_of_birth_allowed`, `required_fields`, `signature_required`, `date_of_issue_required`.

**Files:**
- Modify: `apps/documents/rule_manifest.py` (remove this batch from `PENDING`, add `UNAPPLICABLE` entries)
- Modify: `apps/documents/render.py` (`_UNIVERSAL_RULES`, for universal-scope rules)
- Modify: `apps/documents/catalog_seed.py` (`SEED_RULES`, for country/track/funder-scope rules)
- Test: `tests/documents/test_rule_manifest.py`

**Interfaces:**
- Consumes: `UNAPPLICABLE`, `PENDING` from Task 1.
- Produces: nothing new; later tasks only shrink `PENDING` further.

**Batch:** `R-016 R-019 R-022 R-034 R-035 R-036 R-037 R-038 R-039 R-041 R-046 R-071 R-073 R-076`

- [ ] **Step 1: Read all fourteen rows**

Run:
```bash
python3 - <<'PY'
import csv
want = {"R-016","R-019","R-022","R-034","R-035","R-036","R-037","R-038",
        "R-039","R-041","R-046","R-071","R-073","R-076"}
for f in ("cv-rules.csv", "cv-style-rules.csv"):
    for r in csv.DictReader(open("docs/research/" + f)):
        if r["ID"] in want:
            print(f'{r["ID"]} | scope={r["Scope"]} | {r["Binding or advisory"]}')
            print(f'   {r["Rule"]}')
            print(f'   {r["Source URL [provenance]"]}\n')
PY
```

- [ ] **Step 2: For each rule, decide its bucket**

Decide, per rule, in this order:
1. Does a key in `_CONSTRAINT_KEYS` express it exactly? If not → `UNAPPLICABLE`.
2. Is its CSV `Scope` "universal"? → `_UNIVERSAL_RULES` in `render.py`.
3. Otherwise it is country/track/funder-scoped → `SEED_RULES` in `catalog_seed.py`, obeying the tier rules in Global Constraints.

A rule that *nearly* fits a key does not fit it. "Include an ORCID where relevant" is not `required_fields` unless the rule actually mandates the field.

- [ ] **Step 3: Write the universal entries**

Append to `_UNIVERSAL_RULES` in `apps/documents/render.py`, one per qualifying rule:

```python
    ConstraintRule(
        rule_id="R-0NN",
        key="photo_allowed",
        value=False,
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="<the CSV's Rule column, verbatim>",
        source_url="<the CSV's Source URL, without any trailing [note]>",
    ),
```

- [ ] **Step 4: Write the scope-scoped entries**

Append to `SEED_RULES` in `apps/documents/catalog_seed.py`:

```python
    {
        "rule_id": "R-0NN",
        "scope_kind": "COUNTRY",
        "scope_values": ["DE"],
        "key": "photo_allowed",
        "value": True,
        "enforcement": "ADVISORY_STYLE",
        "rule_text": "<the CSV's Rule column, verbatim>",
        "source_url": "<the CSV's Source URL>",
        "verified_for_cycle": "<the CSV's Verified for cycle column>",
        "confidence": "<the CSV's Confidence column, lowercased>",
    },
```

- [ ] **Step 5: Write the unapplicable entries**

In `apps/documents/rule_manifest.py`, add to `UNAPPLICABLE` — the reason names what is missing, so a future key makes the rule findable:

```python
UNAPPLICABLE: dict[str, str] = {
    "R-0NN": "asks for a LinkedIn URL; no key carries a contact field",
}
```

- [ ] **Step 6: Remove this batch from `PENDING`**

Delete the fourteen ids and the `# data-field (Task 2)` comment from the `PENDING` set.

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS. A failure naming an id means it left `PENDING` without arriving anywhere — put it in a bucket.

- [ ] **Step 8: Commit**

```bash
git commit apps/documents/rule_manifest.py apps/documents/render.py \
  apps/documents/catalog_seed.py \
  -m "documents: adjudicate the data-field CV rules"
```

---

### Task 3: Adjudicate the 9 `content` rules

Candidate keys: `prohibited_content`, `no_unexplained_gaps`, `required_fields`, `ai_use_policy`.

**Files:** as Task 2.
**Batch:** `R-014 R-028 R-042 R-051 R-052 R-061 R-069 R-084 S-029`

- [ ] **Step 1: Read the nine rows**

```bash
python3 - <<'PY'
import csv
want = {"R-014","R-028","R-042","R-051","R-052","R-061","R-069","R-084","S-029"}
for f in ("cv-rules.csv", "cv-style-rules.csv"):
    for r in csv.DictReader(open("docs/research/" + f)):
        if r["ID"] in want:
            print(f'{r["ID"]} | scope={r["Scope"]} | {r["Binding or advisory"]}')
            print(f'   {r["Rule"]}')
            print(f'   {r["Source URL [provenance]"]}\n')
PY
```

- [ ] **Step 2: Bucket each rule** by the three-step order in Task 2 Step 2.

- [ ] **Step 3: Write the entries.** Universal rules go in `_UNIVERSAL_RULES` (`apps/documents/render.py`):

```python
    ConstraintRule(
        rule_id="R-0NN",
        key="prohibited_content",
        value=["marital status"],
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="<the CSV's Rule column, verbatim>",
        source_url="<the CSV's Source URL>",
    ),
```

Scope-scoped ones go in `SEED_RULES` (`apps/documents/catalog_seed.py`) in the dict form shown in Task 2 Step 4. Unapplicable ones go in `UNAPPLICABLE` with a reason naming what is missing.

- [ ] **Step 4: Remove the nine ids from `PENDING`.**

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit apps/documents/rule_manifest.py apps/documents/render.py \
  apps/documents/catalog_seed.py -m "documents: adjudicate the content CV rules"
```

---

### Task 4: Adjudicate the 14 `file-output` rules

Candidate keys: `max_bytes`, `max_pages`. Filename conventions ("LastnameInitials-resume.pdf") have **no key** — the corpus already recorded one as `unapplied` for that reason, so expect several `UNAPPLICABLE` entries here.

**Files:** as Task 2.
**Batch:** `R-013 R-018 R-020 R-021 R-043 R-044 R-045 R-047 R-049 R-053 R-067 R-068 R-082 R-083`

- [ ] **Step 1: Read the fourteen rows**

```bash
python3 - <<'PY'
import csv
want = {"R-013","R-018","R-020","R-021","R-043","R-044","R-045","R-047",
        "R-049","R-053","R-067","R-068","R-082","R-083"}
for f in ("cv-rules.csv", "cv-style-rules.csv"):
    for r in csv.DictReader(open("docs/research/" + f)):
        if r["ID"] in want:
            print(f'{r["ID"]} | scope={r["Scope"]} | {r["Binding or advisory"]}')
            print(f'   {r["Rule"]}')
            print(f'   {r["Source URL [provenance]"]}\n')
PY
```

- [ ] **Step 2: Bucket each rule** by the three-step order in Task 2 Step 2.

- [ ] **Step 3: Write the entries**, in the same three forms as Task 2 Steps 3-5. A size cap is `max_bytes` with an integer value:

```python
    ConstraintRule(
        rule_id="R-0NN",
        key="max_bytes",
        value=5_000_000,
        enforcement=Enforcement.BINDING,
        rule_text="<the CSV's Rule column, verbatim>",
        source_url="<the CSV's Source URL>",
    ),
```

- [ ] **Step 4: Remove the fourteen ids from `PENDING`.**

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit apps/documents/rule_manifest.py apps/documents/render.py \
  apps/documents/catalog_seed.py -m "documents: adjudicate the file-output CV rules"
```

---

### Task 5: Adjudicate the 10 `typography` and `element` rules

Candidate key: `font`, and nothing else. Point sizes, margins, section-heading style and white-space advice have no key — most of this batch is expected to be `UNAPPLICABLE`, and that is the correct outcome, not a failure.

**Files:** as Task 2.
**Batch:** `S-002 S-003 S-004 S-005 S-006 S-012 S-023 S-025 S-031 S-033`

- [ ] **Step 1: Read the ten rows**

```bash
python3 - <<'PY'
import csv
want = {"S-002","S-003","S-004","S-005","S-006","S-012","S-023","S-025","S-031","S-033"}
for f in ("cv-rules.csv", "cv-style-rules.csv"):
    for r in csv.DictReader(open("docs/research/" + f)):
        if r["ID"] in want:
            print(f'{r["ID"]} | scope={r["Scope"]} | {r["Binding or advisory"]}')
            print(f'   {r["Rule"]}')
            print(f'   {r["Source URL [provenance]"]}\n')
PY
```

- [ ] **Step 2: Bucket each rule** by the three-step order in Task 2 Step 2. A typeface mandate is `font`; a point size is not.

- [ ] **Step 3: Write the entries**, in the same three forms as Task 2 Steps 3-5. Most will be:

```python
UNAPPLICABLE = {
    "S-0NN": "an 11pt body-text target; font carries a typeface, not a size",
}
```

- [ ] **Step 4: Remove the ten ids from `PENDING`.**

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit apps/documents/rule_manifest.py apps/documents/render.py \
  apps/documents/catalog_seed.py \
  -m "documents: adjudicate the typography and element CV rules"
```

---

### Task 6: Adjudicate the 19 `layout` rules

Section order and column count are template decisions, not constraint keys — `render.py::_section_order` and the `tabular` template flag already carry the ones that are implemented. Expect mostly `UNAPPLICABLE`, and say in the reason which template mechanism owns the rule, so nobody re-implements it.

**Files:** as Task 2.
**Batch:** `R-003 R-004 R-005 R-006 R-011 R-026 R-058 R-059 R-062 R-063 R-065 R-075 R-085 S-017 S-018 S-019 S-020 S-021 S-032`

- [ ] **Step 1: Read the nineteen rows**

```bash
python3 - <<'PY'
import csv
want = {"R-003","R-004","R-005","R-006","R-011","R-026","R-058","R-059","R-062",
        "R-063","R-065","R-075","R-085","S-017","S-018","S-019","S-020","S-021","S-032"}
for f in ("cv-rules.csv", "cv-style-rules.csv"):
    for r in csv.DictReader(open("docs/research/" + f)):
        if r["ID"] in want:
            print(f'{r["ID"]} | scope={r["Scope"]} | {r["Binding or advisory"]}')
            print(f'   {r["Rule"]}')
            print(f'   {r["Source URL [provenance]"]}\n')
PY
```

- [ ] **Step 2: Bucket each rule** by the three-step order in Task 2 Step 2.

**S-032 has a prior ruling — do not re-open it.** CLAUDE.md, "The rule catalogs": S-032 (machine parsers mangle table layouts) binds nothing here, because every source for it describes corporate ATS and nothing in this platform hands a CV to a parser. Record it `UNAPPLICABLE` with that reason and the two conditions that would revive it.

- [ ] **Step 3: Write the entries**, in the same three forms as Task 2 Steps 3-5. A layout rule already carried by a template reads:

```python
UNAPPLICABLE = {
    "S-0NN": "single-column layout; owned by the template, not by a key -- "
             "render.py's variant choice decides it",
}
```

- [ ] **Step 4: Remove the nineteen ids from `PENDING`.**

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit apps/documents/rule_manifest.py apps/documents/render.py \
  apps/documents/catalog_seed.py -m "documents: adjudicate the layout CV rules"
```

---

### Task 7: Adjudicate the 18 `validation-flag` rules

These describe engine *behaviour* ("branch CV generation on funder + portal before applying any layout"), not properties of a finished CV. A behaviour rule is not a `ConstraintRule`; most belong in `UNAPPLICABLE` with a reason naming the module that owns the behaviour.

**Files:** as Task 2.
**Batch:** `R-001 R-002 R-009 R-025 R-050 R-054 R-055 R-074 R-077 R-081 R-086 R-087 R-088 R-089 R-090 R-091 R-092 R-093`

- [ ] **Step 1: Read the eighteen rows**

```bash
python3 - <<'PY'
import csv
want = {"R-001","R-002","R-009","R-025","R-050","R-054","R-055","R-074","R-077",
        "R-081","R-086","R-087","R-088","R-089","R-090","R-091","R-092","R-093"}
for f in ("cv-rules.csv", "cv-style-rules.csv"):
    for r in csv.DictReader(open("docs/research/" + f)):
        if r["ID"] in want:
            print(f'{r["ID"]} | scope={r["Scope"]} | {r["Binding or advisory"]}')
            print(f'   {r["Rule"]}')
            print(f'   {r["Source URL [provenance]"]}\n')
PY
```

- [ ] **Step 2: Bucket each rule** by the three-step order in Task 2 Step 2, with one addition: if the rule describes something the engine *does* rather than something the CV *is*, it is `UNAPPLICABLE` even when a key looks close.

- [ ] **Step 3: Write the entries**, in the same three forms as Task 2 Steps 3-5. A behaviour rule reads:

```python
UNAPPLICABLE = {
    "R-002": "describes the cv_format_requirement field itself; a schema "
             "decision already implemented, not a constraint on a CV",
}
```

- [ ] **Step 4: Remove the eighteen ids from `PENDING`.**

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents -q && uv run ruff check . && uv run mypy apps config`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit apps/documents/rule_manifest.py apps/documents/render.py \
  apps/documents/catalog_seed.py \
  -m "documents: adjudicate the validation-flag CV rules"
```

---

### Task 8: The last two rules, and close `PENDING`

**Files:**
- Modify: `apps/documents/rule_manifest.py`
- Modify: `apps/documents/render.py`, `apps/documents/catalog_seed.py` (if either rule maps)
- Test: `tests/documents/test_rule_manifest.py`

**Batch:** `S-024` (reader-evidence), `S-030` (structure)

- [ ] **Step 1: Read both rows**

```bash
python3 - <<'PY'
import csv
for f in ("cv-rules.csv", "cv-style-rules.csv"):
    for r in csv.DictReader(open("docs/research/" + f)):
        if r["ID"] in {"S-024", "S-030"}:
            print(f'{r["ID"]} | scope={r["Scope"]} | {r["Binding or advisory"]}')
            print(f'   {r["Rule"]}')
            print(f'   {r["Source URL [provenance]"]}\n')
PY
```

- [ ] **Step 2: Bucket both** by the three-step order in Task 2 Step 2, writing entries in the same three forms as Task 2 Steps 3-5.

- [ ] **Step 3: Empty `PENDING`**

```python
#: Empty, and it stays empty: the test below refuses any researched rule that
#: is in no bucket. A new rule added to either CSV lands here first.
PENDING: frozenset[str] = frozenset()
```

- [ ] **Step 4: Add the test that keeps it closed**

Append to `tests/documents/test_rule_manifest.py`:

```python
def test_nothing_is_pending_adjudication() -> None:
    """Once emptied, PENDING stays empty. A rule added to either research CSV
    fails this test until someone decides where it goes -- which is the whole
    point: the CSVs are not a place a rule can quietly rest."""
    assert not PENDING, (
        f"{len(PENDING)} rules await adjudication: {sorted(PENDING)}. "
        "Put each in a bucket -- universal, seeded, cited or UNAPPLICABLE."
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest tests/documents/test_rule_manifest.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the full suite**

Run: `POSTGRES_DB=tehsil_cv_corpus uv run pytest -q && uv run ruff check . && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config`
Expected: all pass

- [ ] **Step 7: Print the final tally for the commit message**

```bash
POSTGRES_DB=tehsil_cv_corpus DJANGO_SETTINGS_MODULE=config.settings.test uv run python -c "
import django, collections; django.setup()
from apps.documents.rule_manifest import accounted_for, research_rule_ids
print(len(research_rule_ids()), 'researched rules')
print(collections.Counter(accounted_for().values()))"
```

- [ ] **Step 8: Commit**

```bash
git commit apps/documents/rule_manifest.py apps/documents/render.py \
  apps/documents/catalog_seed.py tests/documents/test_rule_manifest.py \
  -m "documents: every researched CV rule is now accounted for

PENDING is empty and a test keeps it that way. <tally from Step 7>.
A rule added to either research CSV now fails the build until someone
decides where it goes."
```

---

## Notes for the executor

- **`UNAPPLICABLE` is not a failure bucket.** `catalog_seed.py`'s docstring estimates two thirds of these rules have no checkable key. A reason that names what is missing ("no key carries a contact field") is worth more than a forced mapping, because it is what makes the rule findable the day a key arrives.
- **Do not widen `_CONSTRAINT_KEYS` to fit a rule.** A new key means a new checker, a new render path and a new way to block a student's CV. If a batch makes a strong case for one, stop and raise it rather than adding it inside this plan.
- **Check `git status` before each commit** and use the pathspec given. Other sessions share this checkout.
