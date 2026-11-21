# CV Stage 4.1: requirement list and merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one typed requirement list per application (CV and letter items with origin, force, display sentence and a `pending` state) and replace `constraints.resolve_rules`' precedence with the §6.4 merge, so render and the list agree; the reader keeps each reading of an unclear sentence; Europass never receives content a ban forbids, soft bans included.

**Architecture:** A new pure module, `apps/documents/requirement_list.py`, holds the item model, the "Stricter means" table, `merge` (steps 1-7) and `build_requirements`. `resolve_rules` becomes `build_requirements(...).cv_rules()`, so every existing render caller gets the new merge with no signature change. Step 8 lives in `render.py` (`without_banned_content`, applied inside `europass_content` so the Europass cache key hashes what is sent). The two readers (`derive.py` judge path, `rule_sinks.to_notes` grammar path) save readings on `undecided` rules through one optional `ConstraintRule.readings` field. Part B adds the §8 grammar keys.

**Tech Stack:** Python 3.14, Django 5.2, pydantic 2.13 (`Field(exclude_if=...)`), pytest + pytest-django, ruff (lint only), mypy.

**Spec:** `docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md` §6.3–§6.4 (plus §8 for Part B).

## Global Constraints

- Work in a worktree off the Stage 1 branch: `git -C /home/orkhan/Desktop/cv-engine-design worktree add /home/orkhan/Desktop/cv-stage-4-1 -b claude/cv-stage-4-1-requirements claude/cv-engine-quality-design`. Every git command below uses `git -C /home/orkhan/Desktop/cv-stage-4-1` (the shell's cwd resets to another checkout). `W=/home/orkhan/Desktop/cv-stage-4-1` in commands below means that path.
- Lint is `uv run ruff check .` only. Never run `ruff format` (it rewrites hundreds of untouched files and turns this repo's except-tuples into invalid Python).
- Types: `uv run mypy apps config`. Tests: `uv run pytest -q tests/documents tests/funding` (each checkout gets its own test database automatically).
- No migration: this step adds no model field and no table. `uv run python manage.py makemigrations --check --dry-run` must print "No changes detected". Never hand-edit `uv.lock` or an applied migration.
- No new table, so no RLS work. If a task seems to need one, stop: `.claude/rules/row-level-security.md` (ENABLE+FORCE, tenant guards, redaction entries, an `rls_enforced_orm` test) applies, and that belongs to step 4.2.
- Page text is data. An item's `sentence` is for display only; nothing in this step puts page text into any model prompt or writer instruction, and no step may add a path that does (§6.6; `.claude/rules/llm-ai-security.md`).
- Every page-derived rule stays `ADVISORY_HIGH_RISK` when stored (`rule_sinks.py`, `derive.py`). Force: `BINDING` → strict, `ADVISORY_HIGH_RISK` and `ADVISORY_STYLE` → soft. `ai_use_policy`, `undecided`, `unapplied` are always for-information and render at most `ADVISORY_HIGH_RISK`.
- A merged rule carries the strongest enforcement of every rule it came from (step 7), losers included. `BINDING` > `ADVISORY_HIGH_RISK` > `ADVISORY_STYLE`.
- Theirs = programme page, scholarship (FUNDER scope), institution (INSTITUTION scope). Ours = UNIVERSAL, TRACK, COUNTRY and code-held style rules. Theirs-first order: programme, scholarship, institution.
- Commit with an explicit pathspec, never `git add -A` or `git add .`. New files are added by name. Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never push to `master`; the PR targets `claude/cv-engine-quality-design` (or master once Stage 1 merges), opened by the owner's instruction only.
- Line numbers below are from `claude/cv-engine-quality-design` at `44cb7c11`. Re-find by the quoted text if they drift.
- **Before Task 1, bring the Stage 1 branch up to date with master** (it is many commits behind, including the 2026-10-14 instructions split, PR #206): `git -C /home/orkhan/Desktop/cv-engine-design merge origin/master`, resolve, run the gates, and commit the merge there; then create the worktree above. After the split, the project notes Task 13 edits live in `.claude/rules/llm-ai-security.md`, not `CLAUDE.md`; `tests/test_instruction_files.py` (PR #208) fails if `CLAUDE.md` grows back.

## Review Focus

Most likely to bite first. Each one's test is named in the owning task.

1. **A disputed limit on somebody else's CV becomes the student's stricter rule.** `derive.outcomes` appends `"third_party"` to `disputed` only when something *agreed* has to be withheld (derive.py:818-822). A sentence like "Short CV (max. 2 pages) from this academic supervisor." where the readings disagree (2 vs 3) agrees on nothing, so it carries no `third_party` marker, and saved readings would turn it into `max_pages=2` for the student. Readings are therefore suppressed on `elsewhere`, not on the marker. Tests: Task 2 `test_a_third_party_line_saves_no_readings`; Task 6 `test_a_third_party_reading_never_becomes_an_item`.
2. **The Europass cache key stops hashing what is sent.** If the bans are applied in the render but not in the digest, two programmes (one banning hyperlinks, one not) share one cached europa.eu PDF. The strip therefore sits inside `europass_content`, and `europass_render.render_and_store` passes the same resolved rules. Test: Task 9 `test_the_cache_key_tells_a_programme_banning_links_from_one_that_does_not`.
3. **A soft page rule now changes a value the Europass gate relied on.** Theirs beat ours, so a page's `date_of_issue_required=False` now beats a UNIVERSAL BINDING `True` (it used to be refused). The force stays BINDING (step 7), and every seeded BINDING rule is FUNDER (theirs), where "required beats not stated" keeps the gate firing. Tests: Task 8 `test_an_advisory_programme_rule_cannot_displace_a_binding_one` (rewritten to FUNDER), `test_a_page_rule_beats_a_binding_universal_one_and_keeps_its_force`, and the unchanged `test_a_derived_rule_cannot_unlock_the_europass_pii_egress`.
4. **Stored rows change shape.** A `readings: null` key in every dumped rule would make `rederive_rules` report every programme as changed and break every test comparing stored dicts. The field is excluded from the dump when absent. Tests: Task 1 `test_a_rule_without_readings_dumps_exactly_as_before`, Task 3 `test_a_note_without_readings_dumps_exactly_as_before`.
5. **The same `PAGE-<n>` line on two different pages.** Step 1 discards every unclear rule on a third-party line, keyed by line number. Line numbers restart per page, so a scholarship page's line 4 must never discard the programme page's line 4 once step 4.7 adds scholarship page rules. Discards are keyed by (origin, line). Test: Task 6 `test_a_third_party_line_on_one_page_does_not_discard_the_same_line_of_another`.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `apps/documents/constraints.py` | Modify | Three new keys; `SavedReadings`; `ConstraintRule.readings`; `resolve_rules` delegates to the list |
| `apps/documents/derive.py` | Modify | Judge path saves each reading's value on `undecided` rules |
| `apps/documents/rule_sinks.py` | Modify | Grammar path saves readings (`to_notes`); Part B projections for `cv_scope`, `cv_start`, entries |
| `apps/documents/requirement_list.py` | Create | Item model, "Stricter means" table, `merge` (steps 1-7), `build_requirements` |
| `apps/documents/render.py` | Modify | Step 8 `without_banned_content` inside `europass_content`; Part B `photo_required` checker |
| `apps/documents/europass_render.py` | Modify | Cache key hashes the same banned-content-stripped payload |
| `apps/documents/grammar.py` | Modify (Part B) | `photo_required` sink, `cv_scope`/`cv_start` style values, `entries` unit |
| `apps/documents/grammar_values.py` | Modify (Part B) | `cv_start_last_years` reads its number; per-figure section question for `entries` |
| `tests/funding/test_program_cv_format.py` | Modify | Readings round-trip; malformed readings raise |
| `tests/documents/test_derive.py` | Modify | Judge readings |
| `tests/documents/test_rule_sinks_cv.py` | Modify | Grammar readings; Part B projections |
| `tests/documents/test_requirement_list.py` | Create | Model and builder (pure) |
| `tests/documents/test_catalog_rules.py` | Modify | Table coverage, one case per table row, merge steps, resolve_rules behaviour, two tests rewritten on purpose |
| `tests/documents/test_render.py` | Modify | Step 8; one test rewritten on purpose; Part B photo checker |
| `tests/documents/test_europass_render.py` | Modify | Cache key |
| `tests/documents/test_grammar_values.py` | Modify (Part B) | New style values and the entries unit |
| `tests/documents/test_grammar_types.py` | Modify (Part B) | The `UNITS` pin gains `entries` |
| `.claude/rules/llm-ai-security.md` | Modify (Task 13, owner approval first) | The enforcement paragraph matches the new merge |

---

# Part A: the list and who wins

### Task 1: Saved readings on a stored rule, and the three new keys

**Files:**
- Modify: `apps/documents/constraints.py:11-59` (`_CONSTRAINT_KEYS`), `:125-138` (`ConstraintRule`)
- Test: `tests/funding/test_program_cv_format.py` (append at end, after line 147)

**Interfaces:**
- Produces: `SavedReadings(key: _CONSTRAINT_KEYS, values: tuple[object, ...])` (1-10 values); `ConstraintRule.readings: SavedReadings | None = None`, dumped only when set, allowed only on `key == "undecided"`; `CONSTRAINT_KEYS` gains `"photo_required"`, `"cv_scope"`, `"cv_start"`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests.** Append to `tests/funding/test_program_cv_format.py`:

```python
_UNDECIDED = {
    "rule_id": "PAGE-0-max_pages", "key": "undecided", "value": "max_pages",
    "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "Two or three pages.",
    "source_url": "", "scope": "PROGRAMME",
    "readings": {"key": "max_pages", "values": [2, 3]},
}


def test_an_undecided_rules_readings_round_trip(program_factory):
    """Spec 2026-10-12 §6.4 step 2: the reader saves what each reading said."""
    program = program_factory()
    program.cv_constraints = [_UNDECIDED]
    program.save(update_fields=["cv_constraints"])
    program.refresh_from_db()
    [rule] = rules_from_program(program)
    assert (rule.readings.key, rule.readings.values) == ("max_pages", (2, 3))
    assert rule.model_dump(mode="json") == _UNDECIDED


@pytest.mark.parametrize(
    "bad",
    [
        {"key": "nope", "values": [2]},
        {"key": "max_pages", "values": []},
        {"key": "max_pages", "values": [2], "why": "extra"},
    ],
)
def test_malformed_readings_raise_rather_than_being_skipped(program_factory, bad):
    program = program_factory()
    program.cv_constraints = [_UNDECIDED | {"readings": bad}]
    program.save(update_fields=["cv_constraints"])
    with pytest.raises(ValidationError):
        rules_from_program(program)


def test_readings_on_a_rule_that_is_not_undecided_raise(program_factory):
    program = program_factory()
    program.cv_constraints = [_UNDECIDED | {"key": "max_pages", "value": 2}]
    program.save(update_fields=["cv_constraints"])
    with pytest.raises(ValidationError):
        rules_from_program(program)


def test_a_rule_without_readings_dumps_exactly_as_before():
    """Review focus 4: no `readings: null` in rows written from now on."""
    from apps.documents.constraints import ConstraintRule

    rule = ConstraintRule(rule_id="P-1", key="max_pages", value=2,
                          enforcement="BINDING", rule_text="Two pages.")
    assert set(rule.model_dump(mode="json")) == {
        "rule_id", "key", "value", "enforcement", "rule_text", "source_url", "scope",
    }


@pytest.mark.parametrize("key", ["photo_required", "cv_scope", "cv_start"])
def test_the_section_8_keys_are_constraint_keys(key):
    from apps.documents.constraints import CONSTRAINT_KEYS

    assert key in CONSTRAINT_KEYS
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest -q tests/funding/test_program_cv_format.py` → FAIL: `ValidationError ... readings: Extra inputs are not permitted` on the round trip, and `assert 'photo_required' in frozenset(...)` on the keys.

- [ ] **Step 3: Add the keys.** In `apps/documents/constraints.py`, replace lines 57-59:

```python
    "max_chars_excl_spaces",
    "font",
]
```

with:

```python
    "max_chars_excl_spaces",
    "font",
    #: Spec 2026-10-12 §8. `photo_required` is read apart from photo_allowed,
    #: which stores "required" and "allowed" alike as True. `cv_scope` is
    #: "complete" or "relevant_only"; `cv_start` is {"milestone":
    #: "upper_secondary" | "first_degree" | None, "years": int | None}.
    "photo_required",
    "cv_scope",
    "cv_start",
]
```

- [ ] **Step 4: Add `SavedReadings` and the field.** Insert directly above `class ConstraintRule(BaseModel):` (line 125):

```python
class SavedReadings(BaseModel):
    """What each reading of an unclear sentence said, kept on its `undecided`
    rule (spec 2026-10-12 §6.4 step 2) so the requirement list can take the
    stricter reading without re-reading the page.

    `key` is the constraint key the readings disagreed about; `values` holds
    every value any reading gave for it, in the order first seen. Only ever
    on an `undecided` rule (ConstraintRule._readings_only_on_undecided).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: _CONSTRAINT_KEYS
    values: tuple[object, ...] = Field(min_length=1, max_length=10)


```

Then replace the last line of `ConstraintRule` (line 138, `    scope: _SCOPE = ""`) with:

```python
    scope: _SCOPE = ""
    #: Each reading's value, on an `undecided` rule only. Left out of the dump
    #: when absent, so every row written before this field (and every rule
    #: that has none) serialises exactly as it did.
    readings: SavedReadings | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def _readings_only_on_undecided(self) -> ConstraintRule:
        if self.readings is not None and self.key != "undecided":
            raise ValueError("only an undecided rule carries readings")
        return self
```

- [ ] **Step 5: Run them and see them pass.** `uv run pytest -q tests/funding/test_program_cv_format.py tests/documents/test_constraints.py tests/documents/test_rule_sinks_cv.py::test_every_constraint_key_has_its_own_rule_id` → PASS (the last one proves the three keys keep distinct 20-character `PAGE-999-` ids).

- [ ] **Step 6: Commit.**

```bash
git -C $W commit -m "feat(cv): undecided rules can carry each reading; three section 8 keys" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/constraints.py tests/funding/test_program_cv_format.py
```

### Task 2: The judge path saves each reading

**Files:**
- Modify: `apps/documents/derive.py:43-50` (import), `:671-686` (`Outcome`), `:747-758` and `:828-833` (`outcomes`), `:867-884` (`_surfaced`), `:925-926` and `:953-954` (`decide`)
- Test: `tests/documents/test_derive.py` (append at end, after line 1354)

**Interfaces:**
- Consumes: `SavedReadings` (Task 1).
- Produces: `Outcome.readings: tuple[tuple[str, tuple[object, ...]], ...]` (per disputed constraint key; empty on a third-party line); `_surfaced(index, key, value, candidate, source_url, readings: tuple[object, ...] = ()) -> ConstraintRule`; every `undecided` rule `decide()` writes for a disputed constraint key carries `readings`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/documents/test_derive.py` (it already defines `_sample`, `_PAGES`, `_SRC` at lines 780-798):

```python
# --- spec 2026-10-12 §6.4 step 2: an unclear sentence keeps its readings -------


def test_an_undecided_rule_saves_what_each_reading_said():
    samples = [_sample(rules=[(0, "max_pages", 2)]), _sample(rules=[(0, "max_pages", 3)]),
               _sample(rules=[(0, "max_pages", 3)])]
    [rule] = decide((_PAGES,), samples, source_url=_SRC).rules
    assert (rule.key, rule.value) == ("undecided", "max_pages")
    assert (rule.readings.key, rule.readings.values) == ("max_pages", (2, 3))


def test_a_choice_inside_one_reading_saves_both_values():
    choice = Candidate(text="Your CV in German or English.", heading="", europass=False)
    samples = [_sample(rules=[(0, "language", "de"), (0, "language", "en")]),
               _sample(rules=[(0, "language", "de")]), _sample(rules=[(0, "language", "de")])]
    [rule] = decide((choice,), samples, source_url=_SRC).rules
    assert rule.readings.values == ("de", "en")


def test_a_third_party_line_saves_no_readings():
    """Review focus 1. The readings disagree, so nothing AGREED is withheld and
    no `third_party` marker is written -- but the sentence is still about the
    supervisor's CV, and its two pages must never become the student's."""
    supervisor = Candidate(text="Short CV (max. 2 pages) from this academic supervisor.",
                           heading="", europass=False, third_party=True)
    samples = [_sample(rules=[(0, "max_pages", 2)]), _sample(rules=[(0, "max_pages", 3)]),
               _sample(rules=[(0, "max_pages", 2)])]
    assert [r.readings for r in decide((supervisor,), samples, source_url=_SRC).rules] == [None]


def test_a_dispute_that_is_not_a_constraint_saves_no_readings():
    samples = [
        _sample(directives=[(0, "include", "education.ects_credits", None)]),
        _sample(directives=[(0, "emphasise", "experience", None)]),
        _sample(directives=[(0, "include", "education.ects_credits", None)]),
    ]
    [rule] = decide((_PAGES,), samples, source_url=_SRC).rules
    assert (rule.value, rule.readings) == ("directive", None)
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest -q tests/documents/test_derive.py -k "reading or third_party_line or not_a_constraint"` → FAIL: `AttributeError: 'NoneType' object has no attribute 'key'` (no readings saved yet).

- [ ] **Step 3: Import.** In the `from .constraints import (` block (lines 43-50) add `SavedReadings,` after `Enforcement,`.

- [ ] **Step 4: The outcome carries readings.** In `Outcome` replace

```python
    directive: tuple[str, str | None, str | None] | None = None
    disputed: tuple[str, ...] = ()
```

with

```python
    directive: tuple[str, str | None, str | None] | None = None
    disputed: tuple[str, ...] = ()
    #: Per disputed constraint key, every value any reading gave (spec
    #: 2026-10-12 §6.4 step 2). Empty on a third-party or unjudged line: a
    #: reading about someone else's document is never a stricter reading of
    #: the applicant's.
    readings: tuple[tuple[str, tuple[object, ...]], ...] = ()
```

- [ ] **Step 5: Collect the values.** In `outcomes`, replace

```python
        rule_votes: dict[str, list[object]] = defaultdict(list)
        for s in samples:
```

with

```python
        rule_votes: dict[str, list[object]] = defaultdict(list)
        said: dict[str, list[object]] = defaultdict(list)
        for s in samples:
```

and replace

```python
                rule_votes[key].append(values[0] if len(values) == 1 else ("CHOICE",))
```

with

```python
                rule_votes[key].append(values[0] if len(values) == 1 else ("CHOICE",))
                # A choice's values are each a reading: "two or three pages"
                # read stricter is two.
                said[key].extend(v for v in values if v not in said[key])
```

- [ ] **Step 6: Attach them to an undecided outcome.** Replace

```python
        if disputed:
            result[i] = Outcome(
                kind="undecided", format_action=format_action, format_required=format_required,
                constraints=tuple(agreed_rules), directive=directive, disputed=tuple(disputed),
            )
            continue
```

with

```python
        if disputed:
            # `elsewhere`, not "third_party" in disputed: that marker is only
            # added when something AGREED had to be withheld, and a disputed
            # limit on a supervisor's CV sentence agrees on nothing.
            readings = () if elsewhere else tuple(
                (key, tuple(said[key])) for key in disputed if said.get(key)
            )
            result[i] = Outcome(
                kind="undecided", format_action=format_action, format_required=format_required,
                constraints=tuple(agreed_rules), directive=directive, disputed=tuple(disputed),
                readings=readings,
            )
            continue
```

(`unjudged` outcomes, built just above, keep the default `()`.)

- [ ] **Step 7: Write them on the rule.** Replace the `_surfaced` signature

```python
def _surfaced(
    index: int, key: str, value: str, candidate: Candidate, source_url: str
) -> ConstraintRule:
```

with

```python
def _surfaced(
    index: int, key: str, value: str, candidate: Candidate, source_url: str,
    readings: tuple[object, ...] = (),
) -> ConstraintRule:
```

and inside it replace

```python
        source_url=source_url,
        scope="PROGRAMME",
    )


def decide(
```

with

```python
        source_url=source_url,
        scope="PROGRAMME",
        # `value` names the disputed constraint key whenever readings exist:
        # outcomes() keys them by the same disputed entry.
        readings=(
            SavedReadings.model_validate({"key": value, "values": readings})
            if readings else None
        ),
    )


def decide(
```

- [ ] **Step 8: Pass them in both `decide` paths.** Replace (abstain, lines 925-926)

```python
            rules=tuple(_surfaced(i, "undecided", value, candidates[i], source_url)
                        for i, value in unsettled),
```

with

```python
            rules=tuple(
                _surfaced(i, "undecided", value, candidates[i], source_url,
                          readings=dict(per[i].readings).get(value, ()))
                for i, value in unsettled
            ),
```

and replace (line 953-954)

```python
        for item in o.disputed:
            rules.append(_surfaced(i, "undecided", item, candidates[i], source_url))
```

with

```python
        for item in o.disputed:
            rules.append(_surfaced(i, "undecided", item, candidates[i], source_url,
                                   readings=dict(o.readings).get(item, ())))
```

- [ ] **Step 9: Run and see them pass.** `uv run pytest -q tests/documents/test_derive.py` → PASS (the existing `test_two_disputes_on_one_sentence_are_two_rules_with_distinct_ids` still compares only `(key, value)`).

- [ ] **Step 10: Commit.**

```bash
git -C $W commit -m "feat(cv): the judge saves each reading of an unclear sentence" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/derive.py tests/documents/test_derive.py
```

### Task 3: The grammar path saves readings

**Files:**
- Modify: `apps/documents/rule_sinks.py:26` (import), `:367-449` (`to_notes`)
- Test: `tests/documents/test_rule_sinks_cv.py` (append at end, after line 536)

**Interfaces:**
- Consumes: `SavedReadings` (Task 1), `to_constraint_rules` (unchanged).
- Produces: `_READABLE_NOTES = frozenset({"unsure", "conflict"})`; `_reading(rule: Rule) -> tuple[str, object] | None`; `to_notes` attaches `readings` to an `unsure` or `conflict` note on a CV rule whose value projects onto a key. `rederive_rules` gets this for free (it calls `to_notes`).

- [ ] **Step 1: Write the failing tests.** Append to `tests/documents/test_rule_sinks_cv.py` (its `_rule` helper is at line 22):

```python
# --- spec 2026-10-12 §6.4 step 2: a note keeps what its rule would have written --


def test_an_unsure_cv_rule_saves_the_value_it_would_have_written():
    [note] = to_notes((_rule(0, "style", "photo_forbidden", note="unsure"),), source_url=_URL)
    assert (note.key, note.readings.key, note.readings.values) == (
        "undecided", "photo_allowed", (False,))


def test_two_figures_of_one_unsure_sentence_pool_their_readings():
    [note] = to_notes((
        _rule(0, "limit", 2, unit="pages", bound="maximum", note="unsure"),
        _rule(0, "limit", 3, unit="pages", bound="maximum", note="unsure"),
    ), source_url=_URL)
    assert note.readings.values == (2, 3)


def test_a_third_party_valueless_or_letter_note_saves_no_readings():
    notes = to_notes((
        _rule(0, "limit", 2, unit="pages", note="third_party"),
        _rule(1, "limit", None, note="unsure"),
        _rule(2, "limit", 2, unit="pages", note="unsure", document="motivation_letter"),
    ), source_url=_URL)
    assert [n.readings for n in notes] == [None, None, None]


def test_a_note_without_readings_dumps_exactly_as_before():
    """Review focus 4: rederive_rules compares dumped rows to decide 'changed'."""
    [note] = to_notes((_rule(1, "limit", None, note="unsure"),), source_url=_URL)
    assert "readings" not in note.model_dump(mode="json")
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest -q tests/documents/test_rule_sinks_cv.py -k readings` → FAIL: `AttributeError: 'NoneType' object has no attribute 'key'`.

- [ ] **Step 3: Import.** Replace line 26

```python
from .constraints import ConstraintRule, Enforcement, _quote, check_directive_shape
```

with

```python
from .constraints import (
    ConstraintRule,
    Enforcement,
    SavedReadings,
    _quote,
    check_directive_shape,
)
```

- [ ] **Step 4: Add the projection helper.** Insert directly above `def to_notes(`:

```python
#: The note kinds whose rule still carries the value a reading gave: below the
#: bar (`unsure`) or one side of a contradiction (`conflict`). A third-party or
#: conditional note binds nobody, so its value is never a reading (spec
#: 2026-10-12 §6.4 step 1).
_READABLE_NOTES = frozenset({"unsure", "conflict"})


def _reading(rule: Rule) -> tuple[str, object] | None:
    """The key and value this CV note would have written at the bar, or None.

    Projected by `to_constraint_rules` itself, on a copy with the note
    cleared, so a saved reading can never disagree with what the same rule
    writes once it is applied.
    """
    if rule.document != "cv" or rule.value is None:
        return None
    projected = to_constraint_rules((replace(rule, note=""),), source_url="")
    return (projected[0].key, projected[0].value) if projected else None


```

- [ ] **Step 5: Pool readings per note.** In `to_notes`, replace the docstring's last paragraph and the two accumulator lines

```python
    One sentence gets one note per kind -- its figures share the quote, so a
    second would say the same thing twice.
    """
    built: list[ConstraintRule] = []
    seen: set[tuple[int, str]] = set()
    font_seen = False
```

with

```python
    One sentence gets one note per kind -- its figures share the quote, so a
    second would say the same thing twice. Its readings are pooled instead:
    an `unsure` or `conflict` note on a CV rule saves every value its rules
    would have written (`_reading`), so the requirement list can take the
    stricter reading (spec 2026-10-12 §6.4 step 2).
    """
    built: dict[tuple[int, str], ConstraintRule] = {}
    said: dict[tuple[int, str], tuple[str, list[object]]] = {}
    font_seen = False
```

and replace the loop's tail (lines 437-449)

```python
        if (rule.index, kind) in seen:
            continue
        seen.add((rule.index, kind))
        built.append(ConstraintRule(
            rule_id=f"PAGE-{rule.index}-{kind[:9]}",
            key="unapplied" if kind == "unapplied" else "undecided",
            value=f"{rule.document}:{rule.operation}",
            enforcement=Enforcement.ADVISORY_HIGH_RISK,
            rule_text=_quote(rule.sentence),
            source_url=source_url,
            scope="PROGRAMME",
        ))
    return tuple(built)
```

with

```python
        slot = (rule.index, kind)
        reading = _reading(rule) if kind in _READABLE_NOTES else None
        if reading is not None:
            key, value = reading
            pooled = said.setdefault(slot, (key, []))
            # One key per note: a second key on the same sentence is a
            # different question, and its own note would be a different kind.
            if pooled[0] == key and value not in pooled[1]:
                pooled[1].append(value)
        if slot in built:
            continue
        built[slot] = ConstraintRule(
            rule_id=f"PAGE-{rule.index}-{kind[:9]}",
            key="unapplied" if kind == "unapplied" else "undecided",
            value=f"{rule.document}:{rule.operation}",
            enforcement=Enforcement.ADVISORY_HIGH_RISK,
            rule_text=_quote(rule.sentence),
            source_url=source_url,
            scope="PROGRAMME",
        )
    return tuple(
        note.model_copy(update={"readings": SavedReadings.model_validate(
            {"key": said[slot][0], "values": said[slot][1]}
        )}) if slot in said else note
        for slot, note in built.items()
    )
```

- [ ] **Step 6: Run and see them pass.** `uv run pytest -q tests/documents/test_rule_sinks_cv.py tests/documents/test_rederive_rules.py tests/documents/test_derive_grammar.py` → PASS.

- [ ] **Step 7: Commit.**

```bash
git -C $W commit -m "feat(cv): grammar notes keep the value each unclear rule would have written" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/rule_sinks.py tests/documents/test_rule_sinks_cv.py
```

### Task 4: The requirement list's model

**Files:**
- Create: `apps/documents/requirement_list.py`
- Create: `tests/documents/test_requirement_list.py`

**Interfaces:**
- Consumes: `CONSTRAINT_KEYS`, `QUOTE_MAX_CHARS`, `ConstraintRule` (constraints.py).
- Produces: `Document = Literal["cv", "letter"]`; `Origin = Literal["programme", "scholarship", "institution", "ours"]`; `Force = Literal["strict", "soft", "info"]`; `ItemState` (§6.8's ten states plus `"pending"`); `THEIRS: tuple[Origin, ...]`; `DIRECTIVE_ACTIONS`; `LETTER_FIELD_KEYS`; `REQUIREMENT_KEYS: frozenset[str]`; `Requirement` (frozen pydantic: `key, value, document, origin, force, rule, contributors, sentence, source_url, ask, conflict, relevance_only, state`); `RequirementList(items)` with `for_document(document)`, `conflicts() -> dict[str, tuple[Requirement, ...]]`, `cv_rules() -> tuple[ConstraintRule, ...]`; `Contribution(rule, origin, document="cv", rank=0)` frozen dataclass.

- [ ] **Step 1: Write the failing tests.** Create `tests/documents/test_requirement_list.py`:

```python
"""The requirement list's model and builder (spec 2026-10-12 §6.3). Pure: no
database, no model call -- programmes and catalog rows are stand-ins."""

from dataclasses import fields

import pytest
from pydantic import ValidationError

from apps.documents.constraints import ConstraintRule, Enforcement
from apps.documents.letter_shape import _SHAPE_TO_KEY, LetterShape
from apps.documents.requirement_list import LETTER_FIELD_KEYS, Requirement, RequirementList


def test_an_item_starts_pending_and_round_trips_through_json():
    rule = ConstraintRule(rule_id="P-1", key="max_pages", value=2,
                          enforcement=Enforcement.ADVISORY_HIGH_RISK, rule_text="Two pages.")
    listed = RequirementList(items=(
        Requirement(key="max_pages", value=2, document="cv", origin="programme",
                    force="soft", rule=rule, contributors=("P-1",), sentence="Two pages."),
        Requirement(key="order", value=["cv", "chronological"], document="cv",
                    origin="programme", force="soft"),
    ))
    assert listed.items[0].state == "pending"
    assert RequirementList.model_validate_json(listed.model_dump_json()) == listed


def test_an_item_key_outside_the_closed_lists_is_refused():
    with pytest.raises(ValidationError):
        Requirement(key="nobel_prize", document="cv", origin="programme", force="soft")


def test_the_letter_field_keys_are_exactly_the_letter_shapes_own_fields():
    """A LetterShape field added without an item key would never reach the list."""
    not_items = {"sources", "written_requirements", "student_actions", "track",
                 "portfolio_led", *_SHAPE_TO_KEY}
    assert set(LETTER_FIELD_KEYS) == {f.name for f in fields(LetterShape)} - not_items


def test_the_cv_projection_and_the_conflict_groups():
    rule = ConstraintRule(rule_id="P-1", key="language", value="de",
                          enforcement=Enforcement.ADVISORY_HIGH_RISK, rule_text="German.")
    listed = RequirementList(items=(
        Requirement(key="language", value="de", document="cv", origin="programme",
                    force="soft", rule=rule, conflict="language"),
        Requirement(key="max_words", value=800, document="letter", origin="programme",
                    force="strict"),
    ))
    assert listed.cv_rules() == (rule,)
    assert list(listed.conflicts()) == ["language"]
    assert [i.key for i in listed.for_document("letter")] == ["max_words"]
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest -q tests/documents/test_requirement_list.py` → FAIL: `ModuleNotFoundError: No module named 'apps.documents.requirement_list'`.

- [ ] **Step 3: Create the module.** Write `apps/documents/requirement_list.py`:

```python
"""The requirement list: every CV and letter requirement for one application,
gathered and merged before anything is written.

Spec: docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md §6.3-§6.4.

Pure. Nothing here reads the database or calls a model: `build_requirements`
takes what its caller loaded, `merge` applies §6.4 steps 1-7, and
`RequirementList.cv_rules` projects the CV items back onto the ConstraintRule
tuple render already reads -- `constraints.resolve_rules` is that projection,
so render and the list cannot disagree. Step 8, the privacy check before
europa.eu, is render.py's (`without_banned_content`), reading the projection.

A page's sentence rides on an item for DISPLAY only (`sentence`). Nothing in
this module puts it anywhere a writer reads: the typed key and value are the
instruction, and page text is shared by every tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constraints import (
    CONSTRAINT_KEYS,
    QUOTE_MAX_CHARS,
    ConstraintRule,
)

Document = Literal["cv", "letter"]
Origin = Literal["programme", "scholarship", "institution", "ours"]
Force = Literal["strict", "soft", "info"]
#: Spec §6.8's states. Every item starts `pending`; build step 4.5 sets the rest.
ItemState = Literal[
    "pending", "applied", "translated", "left_out", "waiting_for_you", "not_fully_met",
    "choose_what_to_drop", "not_possible_yet", "official_template", "for_information",
    "temporary_error",
]

#: Theirs, in theirs-first order: the programme's own page, then the
#: scholarship, then our research about the university (spec §6.3).
THEIRS: tuple[Origin, ...] = ("programme", "scholarship", "institution")

DIRECTIVE_ACTIONS: tuple[str, ...] = ("include", "order", "emphasise")

#: The LetterShape fields that are an item of their own. The five length fields
#: arrive as constraint keys through `letter_shape.constraints_from_shape`, and
#: `sources`, `written_requirements`, `student_actions`, `track` and
#: `portfolio_led` are not requirements. Pinned to LetterShape by test.
LETTER_FIELD_KEYS: tuple[str, ...] = (
    "document_required", "form", "signed_declaration", "naming", "font_family", "font_min_pt",
    "line_spacing", "margins_cm", "file_bundle", "handwritten", "document_language",
)

REQUIREMENT_KEYS: frozenset[str] = frozenset(
    CONSTRAINT_KEYS
    | set(DIRECTIVE_ACTIONS)
    | {"cv_format", "competency", "written_requirement", "student_action"}
    | set(LETTER_FIELD_KEYS)
)


class Requirement(BaseModel):
    """One item on an application's requirement list (spec §6.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    value: object = None
    document: Document
    origin: Origin
    force: Force
    #: The rule this item projects onto for render: the rule that supplied the
    #: value, carrying the merged value and the strongest contributor's
    #: enforcement. None for a directive, the format, a competency and a letter
    #: field, which render reads elsewhere.
    rule: ConstraintRule | None = None
    #: The rule_id of every rule merged into this item, the supplier first.
    contributors: tuple[str, ...] = ()
    #: The page's own sentence and URL, for display only (spec §6.6).
    sentence: str = Field(default="", max_length=QUOTE_MAX_CHARS)
    source_url: str = Field(default="", max_length=2048)
    #: An unclear sentence about a personal item: asked of the student (step 2).
    ask: bool = False
    #: Non-empty on every side of a requirement no one CV can meet; the value
    #: names the clash ("language", "photo_required+photo_allowed"). Build step
    #: 4.5 makes two versions or shows the student the choice (step 6).
    conflict: str = ""
    #: A COMPETENCY statement: ranks relevance (spec §7.2), never passes or fails.
    relevance_only: bool = False
    state: ItemState = "pending"

    @model_validator(mode="after")
    def _closed_key(self) -> Requirement:
        if self.key not in REQUIREMENT_KEYS:
            raise ValueError(f"{self.key!r} is not a requirement key")
        return self


class RequirementList(BaseModel):
    """One application's list. Saved on the draft by build step 4.2."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[Requirement, ...] = ()

    def for_document(self, document: Document) -> tuple[Requirement, ...]:
        return tuple(item for item in self.items if item.document == document)

    def conflicts(self) -> dict[str, tuple[Requirement, ...]]:
        """Each irreconcilable clash and its sides, for step 6."""
        grouped: dict[str, list[Requirement]] = {}
        for item in self.items:
            if item.conflict:
                grouped.setdefault(item.conflict, []).append(item)
        return {name: tuple(sides) for name, sides in grouped.items()}

    def cv_rules(self) -> tuple[ConstraintRule, ...]:
        """The CV's items as the rules render checks: what resolve_rules returns."""
        return tuple(
            item.rule for item in self.items if item.document == "cv" and item.rule is not None
        )


@dataclass(frozen=True)
class Contribution:
    """One stored rule, before merging: where it came from and its scope rank."""

    rule: ConstraintRule
    origin: Origin
    document: Document = "cv"
    #: Ours only: the catalog scope's index in constraints._SCOPE_ORDER, -1 for
    #: a style rule the engine holds in code, which any catalog rule outranks.
    rank: int = 0
```

- [ ] **Step 4: Run and see them pass.** `uv run pytest -q tests/documents/test_requirement_list.py` → 4 passed. `uv run ruff check apps/documents/requirement_list.py tests/documents/test_requirement_list.py` → All checks passed.

- [ ] **Step 5: Commit.**

```bash
git -C $W add apps/documents/requirement_list.py tests/documents/test_requirement_list.py
git -C $W commit -m "feat(cv): the requirement list's typed item model" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/requirement_list.py tests/documents/test_requirement_list.py
```

### Task 5: The "Stricter means" table and its coverage test

**Files:**
- Modify: `apps/documents/requirement_list.py` (imports; append after `Contribution`)
- Test: `tests/documents/test_catalog_rules.py` (append at end, after line 599)

**Interfaces:**
- Consumes: `_MULTI_KEYS` (constraints.py:76).
- Produces: `Irreconcilable(ValueError)`; `_COMBINE: dict[str, Callable[[list[Any]], object]]` (rows `lower, higher, per_section_lower, union, forbid_wins, required_wins, common_language, complete_wins, earliest_start, first`); `_OTHER_ROWS = {"info", "all_kept", "one_direction", "format"}`; `MERGE: dict[str, str]` covering exactly `REQUIREMENT_KEYS`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/documents/test_catalog_rules.py`:

```python
# --- spec 2026-10-12 §6.4: who wins ------------------------------------------


def test_every_key_and_directive_action_has_a_row_in_the_stricter_table():
    """Spec §6.4: a key the system can read with no row is a rule nobody
    decided how to merge. Adding a key to CONSTRAINT_KEYS fails here first."""
    from apps.documents.constraints import CONSTRAINT_KEYS
    from apps.documents.requirement_list import (
        _COMBINE,
        _OTHER_ROWS,
        DIRECTIVE_ACTIONS,
        MERGE,
        REQUIREMENT_KEYS,
    )

    assert set(CONSTRAINT_KEYS) | set(DIRECTIVE_ACTIONS) <= set(MERGE)
    assert set(MERGE) == REQUIREMENT_KEYS
    assert set(MERGE.values()) <= set(_COMBINE) | _OTHER_ROWS


def test_no_language_in_common_cannot_be_combined():
    from apps.documents.requirement_list import _COMBINE, Irreconcilable

    with pytest.raises(Irreconcilable):
        _COMBINE["common_language"](["de", ["fr", "en"]])
    assert _COMBINE["common_language"]([["fr", "en"], "en"]) == "en"
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest -q tests/documents/test_catalog_rules.py -k "stricter_table or language_in_common"` → FAIL: `ImportError: cannot import name '_COMBINE'`.

- [ ] **Step 3: Widen the imports.** Replace the import lines of `requirement_list.py` (from `from dataclasses import dataclass` through the closing `)` of the constraints import) with:

```python
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constraints import (
    _MULTI_KEYS,
    CONSTRAINT_KEYS,
    QUOTE_MAX_CHARS,
    ConstraintRule,
)
```

- [ ] **Step 4: Append the table** after the `Contribution` class:

```python


class Irreconcilable(ValueError):
    """Theirs state values no one CV can meet (spec §6.4 step 6)."""


# --- the "Stricter means" table (spec §6.4) ----------------------------------


def _lower(values: list[Any]) -> object:
    return min(values)


def _higher(values: list[Any]) -> object:
    return max(values)


def _per_section_lower(values: list[Any]) -> object:
    merged: dict[str, int] = {}
    for value in values:
        for section, limit in dict(value).items():
            merged[section] = min(int(limit), merged.get(section, int(limit)))
    return merged


def _union(values: list[Any]) -> object:
    combined: list[object] = []
    for value in values:
        combined.extend(item for item in value if item not in combined)
    return combined


def _forbid_wins(values: list[Any]) -> object:
    return not any(value is False for value in values)


def _required_wins(values: list[Any]) -> object:
    return any(value is True for value in values)


def _common_language(values: list[Any]) -> object:
    accepted = [value if isinstance(value, list) else [value] for value in values]
    common = [code for code in accepted[0] if all(code in other for other in accepted[1:])]
    if not common:
        raise Irreconcilable("no language every source accepts")
    return common if len(common) > 1 else common[0]


def _complete_wins(values: list[Any]) -> object:
    return "complete" if "complete" in values else "relevant_only"


def _earliest_start(values: list[Any]) -> object:
    milestones = {value.get("milestone") for value in values}
    milestone = next((m for m in ("upper_secondary", "first_degree") if m in milestones), None)
    years = max((value["years"] for value in values if value.get("years")), default=None)
    return {"milestone": milestone, "years": years}


def _first(values: list[Any]) -> object:
    return values[0]


_COMBINE: dict[str, Callable[[list[Any]], object]] = {
    "lower": _lower,
    "higher": _higher,
    "per_section_lower": _per_section_lower,
    "union": _union,
    "forbid_wins": _forbid_wins,
    "required_wins": _required_wins,
    "common_language": _common_language,
    "complete_wins": _complete_wins,
    "earliest_start": _earliest_start,
    "first": _first,
}

#: Rows handled outside `_COMBINE`: each contribution its own item (`info`,
#: `all_kept`), one item per direction per section (`one_direction`), and the
#: format, which keeps today's order instead of strictness (`format`).
_OTHER_ROWS = frozenset({"info", "all_kept", "one_direction", "format"})

#: Every requirement key and the row of the table that merges it. A test fails
#: when a key exists without a row (spec §6.4, last paragraph).
MERGE: dict[str, str] = {
    "max_pages": "lower",
    "max_bytes": "lower",
    "no_unexplained_gaps": "lower",
    "max_words": "lower",
    "max_chars_incl_spaces": "lower",
    "max_chars_excl_spaces": "lower",
    "min_final_page_fill": "higher",
    "min_words": "higher",
    "min_chars_excl_spaces": "higher",
    "max_entries_per_section": "per_section_lower",
    "required_fields": "union",
    "prohibited_content": "union",
    "photo_allowed": "forbid_wins",
    "date_of_birth_allowed": "forbid_wins",
    "photo_required": "required_wins",
    "signature_required": "required_wins",
    "date_of_issue_required": "required_wins",
    "language": "common_language",
    "cv_scope": "complete_wins",
    "cv_start": "earliest_start",
    "font": "first",
    "ai_use_policy": "info",
    # One item per sentence: the quote is the rule (constraints._MULTI_KEYS).
    **dict.fromkeys(_MULTI_KEYS, "info"),
    "include": "all_kept",
    "emphasise": "all_kept",
    "order": "one_direction",
    "cv_format": "format",
    "competency": "info",
    "written_requirement": "all_kept",
    "student_action": "all_kept",
    **dict.fromkeys(LETTER_FIELD_KEYS, "first"),
}
```

- [ ] **Step 5: Run and see them pass.** `uv run pytest -q tests/documents/test_catalog_rules.py -k "stricter_table or language_in_common"` → 2 passed.

- [ ] **Step 6: Commit.**

```bash
git -C $W commit -m "feat(cv): the stricter-means table, one row per readable key" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/requirement_list.py tests/documents/test_catalog_rules.py
```

### Task 6: `merge`, steps 1 to 7

**Files:**
- Modify: `apps/documents/requirement_list.py` (imports; append after `MERGE`)
- Test: `tests/documents/test_catalog_rules.py` (append at end)

**Interfaces:**
- Consumes: `Contribution`, `MERGE`, `_COMBINE`, `Irreconcilable` (Tasks 4-5), `PageDirective`, `Enforcement`.
- Produces: `STRICTER_READING_KEYS`, `ASK_KEYS` (frozensets); `CONTRADICTIONS`, `FLOOR_ABOVE_CAP` (the step 5 pairs, listed in code); `merge(contributions: Sequence[Contribution], directives: Sequence[tuple[PageDirective, Origin]] = ()) -> tuple[Requirement, ...]`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/documents/test_catalog_rules.py`:

```python
def _page_rule(rule_id, key, value, enforcement="ADVISORY_HIGH_RISK", **extra):
    return ConstraintRule.model_validate({
        "rule_id": rule_id, "key": key, "value": value, "enforcement": enforcement,
        "rule_text": f"{rule_id}: the page's sentence.", **extra,
    })


def _merged(*pairs, directives=()):
    """merge() over (rule, origin) pairs; ours carry their scope's rank."""
    from apps.documents.constraints import _SCOPE_ORDER
    from apps.documents.requirement_list import Contribution, merge

    contributions = [
        Contribution(rule=rule, origin=origin,
                     rank=_SCOPE_ORDER.index(rule.scope) if origin == "ours" else 0)
        for rule, origin in pairs
    ]
    return merge(contributions, directives)


@pytest.mark.parametrize(
    ("key", "programme", "scholarship", "stricter"),
    [
        ("max_pages", 3, 2, 2),
        ("max_bytes", 2_000_000, 10_000_000, 2_000_000),
        ("no_unexplained_gaps", 3, 1, 1),
        ("min_final_page_fill", 0.2, 0.5, 0.5),
        ("max_entries_per_section", {"experience": 3, "awards": 5}, {"experience": 2},
         {"experience": 2, "awards": 5}),
        ("required_fields", ["sex"], ["sex", "citizenship"], ["sex", "citizenship"]),
        ("prohibited_content", [], ["hyperlinks"], ["hyperlinks"]),
        ("photo_allowed", True, False, False),
        ("photo_required", True, False, True),
        ("date_of_birth_allowed", True, False, False),
        ("signature_required", False, True, True),
        ("date_of_issue_required", True, False, True),
        ("language", ["en", "fr"], "fr", "fr"),
        ("cv_scope", "relevant_only", "complete", "complete"),
        ("cv_start", {"milestone": "first_degree", "years": None},
         {"milestone": "upper_secondary", "years": 10},
         {"milestone": "upper_secondary", "years": 10}),
        ("font", "Arial 11", "Times New Roman", "Arial 11"),
        ("max_words", 1000, 800, 800),
        ("max_chars_incl_spaces", 4000, 5000, 4000),
        ("max_chars_excl_spaces", 3000, 3500, 3000),
        ("min_words", 300, 500, 500),
        ("min_chars_excl_spaces", 2000, 1500, 2000),
    ],
)
def test_between_programme_and_scholarship_the_stricter_value_wins(
    key, programme, scholarship, stricter
):
    """One case per value row of the §6.4 table. The info, directive and
    format rows have their own tests below."""
    items = _merged(
        (_page_rule("P-1", key, programme), "programme"),
        (_page_rule("F-1", key, scholarship, "BINDING"), "scholarship"),
    )
    winners = [i for i in items if i.key == key and i.force != "info"]
    assert [i.value for i in winners] == [stricter]


@pytest.mark.parametrize("key", ["ai_use_policy", "undecided", "unapplied"])
def test_a_for_information_key_keeps_every_rule_and_never_refuses(key):
    items = _merged(
        (_page_rule("P-1", key, "PROHIBITS", "BINDING"), "programme"),
        (_page_rule("F-1", key, "REQUIRES_DISCLOSURE"), "scholarship"),
    )
    assert [(i.force, i.rule.enforcement) for i in items] == [
        ("info", Enforcement.ADVISORY_HIGH_RISK), ("info", Enforcement.ADVISORY_HIGH_RISK),
    ]


def test_a_second_font_from_theirs_is_for_information():
    items = _merged(
        (_page_rule("P-1", "font", "Arial 11"), "programme"),
        (_page_rule("F-1", "font", "Times New Roman"), "scholarship"),
    )
    assert [(i.value, i.force) for i in items] == [("Arial 11", "soft"),
                                                   ("Times New Roman", "info")]


def test_no_language_in_common_is_a_conflict_with_both_sides_kept():
    items = _merged(
        (_page_rule("P-1", "language", "de"), "programme"),
        (_page_rule("F-1", "language", "fr"), "scholarship"),
    )
    assert [(i.value, i.conflict) for i in items] == [("de", "language"), ("fr", "language")]


def _directive(action, target, value=None):
    from apps.documents.constraints import PageDirective

    return PageDirective(action=action, target=target, value=value,
                         rule_text=f"{action} {target}", source_url="")


def test_include_and_emphasise_directives_are_all_kept_theirs_first():
    items = _merged(directives=(
        (_directive("emphasise", "research"), "scholarship"),
        (_directive("include", "education.ects_credits"), "programme"),
        (_directive("emphasise", "experience"), "programme"),
        (_directive("include", "education.ects_credits"), "scholarship"),
    ))
    assert [(i.key, i.value, i.origin) for i in items] == [
        ("include", "education.ects_credits", "programme"),
        ("emphasise", "experience", "programme"),
        ("emphasise", "research", "scholarship"),
    ]


def test_two_orders_for_one_section_are_a_conflict():
    items = _merged(directives=(
        (_directive("order", "cv", "chronological"), "programme"),
        (_directive("order", "cv", "reverse_chronological"), "scholarship"),
    ))
    assert len(items) == 2
    assert {i.conflict for i in items} == {"order:cv"}


def test_the_cv_format_is_not_merged_by_strictness():
    from apps.documents.requirement_list import MERGE

    assert MERGE["cv_format"] == "format"


def test_theirs_beat_ours_even_when_theirs_is_soft():
    items = _merged(
        (_page_rule("C-1", "max_pages", 1, "ADVISORY_STYLE", scope="COUNTRY"), "ours"),
        (_page_rule("P-1", "max_pages", 3), "programme"),
    )
    assert [(i.value, i.rule.rule_id) for i in items] == [(3, "P-1")]


def test_among_ours_the_more_specific_scope_still_wins():
    items = _merged(
        (_page_rule("C-1", "max_pages", 3, "ADVISORY_STYLE", scope="COUNTRY"), "ours"),
        (_page_rule("U-1", "max_pages", 1, "ADVISORY_STYLE", scope="UNIVERSAL"), "ours"),
    )
    assert [(i.value, i.rule.rule_id) for i in items] == [(3, "C-1")]


def test_a_merged_rule_carries_the_strongest_force_of_its_contributors():
    """Step 7: whichever rule supplied the value. The scholarship's BINDING
    three pages lose to the page's advisory two, and the two stay BINDING."""
    items = _merged(
        (_page_rule("P-1", "max_pages", 2), "programme"),
        (_page_rule("F-1", "max_pages", 3, "BINDING"), "scholarship"),
    )
    assert [(i.value, i.rule.rule_id, i.force, i.rule.enforcement) for i in items] == [
        (2, "P-1", "strict", Enforcement.BINDING),
    ]
    assert items[0].contributors == ("P-1", "F-1")


def test_a_scholarship_requiring_a_date_of_birth_against_a_page_ban_is_a_conflict():
    """Step 5: SISGP's R-079 against a programme page forbidding it."""
    items = _merged(
        (_page_rule("R-079", "required_fields", ["sex", "date_of_birth"], "BINDING"),
         "scholarship"),
        (_page_rule("P-1", "date_of_birth_allowed", False), "programme"),
    )
    assert {i.conflict for i in items} == {"required_fields+date_of_birth_allowed"}


def test_an_include_directive_against_a_page_ban_is_a_conflict():
    items = _merged(
        (_page_rule("F-1", "date_of_birth_allowed", False), "scholarship"),
        directives=((_directive("include", "personal.date_of_birth"), "programme"),),
    )
    assert {i.conflict for i in items} == {"include+date_of_birth_allowed"}


def test_a_country_ban_loses_to_a_scholarship_requirement_on_another_key():
    """Step 5's ours case: R-032 (no date of birth in GB) is ours, so SISGP's
    required date of birth stands and no conflict is raised."""
    items = _merged(
        (_page_rule("R-079", "required_fields", ["date_of_birth"], "BINDING"), "scholarship"),
        (_page_rule("R-032", "date_of_birth_allowed", False, scope="COUNTRY"), "ours"),
    )
    assert [(i.key, i.conflict) for i in items] == [("required_fields", "")]


def test_a_required_photo_against_a_forbidden_one_is_a_conflict():
    items = _merged(
        (_page_rule("P-1", "photo_required", True), "programme"),
        (_page_rule("F-1", "photo_allowed", False), "scholarship"),
    )
    assert all(i.conflict == "photo_required+photo_allowed" for i in items)


def test_a_letter_floor_above_its_cap_is_a_conflict():
    from apps.documents.requirement_list import Contribution, merge

    items = merge([
        Contribution(rule=_page_rule("S-1", "min_words", 900), origin="programme",
                     document="letter"),
        Contribution(rule=_page_rule("S-2", "max_words", 800), origin="scholarship",
                     document="letter"),
    ])
    assert all(i.conflict == "min_words+max_words" for i in items)


def _undecided(rule_id, value, readings=None):
    return _page_rule(rule_id, "undecided", value,
                      **({"readings": readings} if readings else {}))


def test_an_unclear_limit_takes_the_stricter_reading():
    items = _merged((_undecided("PAGE-0-max_pages", "max_pages",
                                {"key": "max_pages", "values": [3, 2]}), "programme"))
    assert [(i.key, i.value, i.force) for i in items] == [("max_pages", 2, "soft")]


def test_an_unclear_personal_item_is_asked_not_guessed():
    items = _merged((_undecided("PAGE-1-photo_allo", "photo_allowed",
                                {"key": "photo_allowed", "values": [True, False]}),
                     "programme"))
    assert [(i.key, i.ask, i.value) for i in items] == [("photo_allowed", True, None)]
    # Render still reports the quote, never a decided photo rule.
    assert items[0].rule.key == "undecided"


def test_an_unclear_rule_without_saved_readings_is_for_information():
    items = _merged((_undecided("PAGE-2-max_pages", "max_pages"), "programme"))
    assert [(i.key, i.force) for i in items] == [("undecided", "info")]


def test_an_unclear_format_stays_for_information():
    items = _merged((_undecided("PAGE-3-cv_format", "cv_format"), "programme"))
    assert [(i.key, i.force) for i in items] == [("undecided", "info")]


def test_a_third_party_reading_never_becomes_an_item():
    """Step 1, with readings on the same line (review focus 1): the
    supervisor's two pages must not become the student's. The sentence itself
    is still shown, for information (owner, 2026-10-14: a skipped sentence is
    silent, so it is never dropped)."""
    items = _merged(
        (_undecided("PAGE-4-max_pages", "max_pages",
                    {"key": "max_pages", "values": [2, 3]}), "programme"),
        (_undecided("PAGE-4-third_par", "third_party"), "programme"),
        (_undecided("PAGE-5-unjudged", "unjudged"), "programme"),
    )
    assert [(i.key, i.value, i.force) for i in items] == [
        ("undecided", "third_party", "info"),
        ("undecided", "unjudged", "info"),
    ]


def test_a_third_party_line_on_one_page_does_not_discard_the_same_line_of_another():
    """Review focus 5: line numbers restart on every page."""
    items = _merged(
        (_undecided("PAGE-4-third_par", "third_party"), "scholarship"),
        (_undecided("PAGE-4-max_pages", "max_pages",
                    {"key": "max_pages", "values": [2]}), "programme"),
    )
    assert [(i.key, i.value) for i in items] == [
        ("undecided", "third_party"),
        ("max_pages", 2),
    ]
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest -q tests/documents/test_catalog_rules.py -k "not draft and not seed"` → the new tests FAIL: `ImportError: cannot import name 'merge'`.

- [ ] **Step 3: Widen the imports.** Replace the import lines again with:

```python
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constraints import (
    _MULTI_KEYS,
    CONSTRAINT_KEYS,
    QUOTE_MAX_CHARS,
    ConstraintRule,
    Enforcement,
    PageDirective,
)
```

- [ ] **Step 4: Append the merge** after `MERGE`:

```python

#: Step 2: the keys an unclear sentence is read stricter on -- limits and bans.
STRICTER_READING_KEYS: frozenset[str] = frozenset({
    "max_pages", "max_bytes", "no_unexplained_gaps", "max_entries_per_section",
    "min_final_page_fill", "prohibited_content", "max_words", "max_chars_incl_spaces",
    "max_chars_excl_spaces", "min_words", "min_chars_excl_spaces",
})
#: Step 2: the keys an unclear sentence is asked of the student about.
ASK_KEYS: frozenset[str] = frozenset({
    "photo_allowed", "photo_required", "date_of_birth_allowed", "signature_required",
    "required_fields",
})

_STRENGTH = {
    Enforcement.ADVISORY_STYLE: 0, Enforcement.ADVISORY_HIGH_RISK: 1, Enforcement.BINDING: 2,
}
_FORCE: dict[Enforcement, Force] = {
    Enforcement.BINDING: "strict",
    Enforcement.ADVISORY_HIGH_RISK: "soft",
    Enforcement.ADVISORY_STYLE: "soft",
}

#: An undecided rule about somebody else's document, or a line no reading
#: judged (step 1). derive._surfaced writes the first as value "third_party"
#: or "unjudged"; rule_sinks.to_notes writes the id tail "-third_par".
_DISCARDED_VALUES = frozenset({"third_party", "unjudged"})
_DISCARDED_TAILS = ("-third_par", "-unjudged")
_LINE = re.compile(r"^PAGE-(\d+)-")


def _line(rule: ConstraintRule) -> str | None:
    match = _LINE.match(rule.rule_id)
    return match[1] if match else None


def _is_discarded(rule: ConstraintRule) -> bool:
    return rule.key == "undecided" and (
        rule.value in _DISCARDED_VALUES or rule.rule_id.endswith(_DISCARDED_TAILS)
    )


def _strongest(group: Iterable[Contribution]) -> Enforcement:
    return max((c.rule.enforcement for c in group), key=_STRENGTH.__getitem__)


def _item(
    supplier: Contribution, value: object, group: Sequence[Contribution], *, conflict: str = ""
) -> Requirement:
    """The merged item: `supplier`'s rule, carrying the merged value and the
    strongest force of every rule it came from (step 7)."""
    enforcement = _strongest(group)
    rule = supplier.rule.model_copy(update={"value": value, "enforcement": enforcement})
    return Requirement(
        key=rule.key, value=value, document=supplier.document, origin=supplier.origin,
        force=_FORCE[enforcement], rule=rule,
        contributors=(rule.rule_id, *(c.rule.rule_id for c in group if c is not supplier)),
        sentence=rule.rule_text, source_url=rule.source_url, conflict=conflict,
    )


def _info(c: Contribution) -> Requirement:
    """A for-information item: shown, never refusing (spec §6.4 table)."""
    enforcement = min(c.rule.enforcement, Enforcement.ADVISORY_HIGH_RISK, key=_STRENGTH.__getitem__)
    rule = c.rule.model_copy(update={"enforcement": enforcement})
    return Requirement(
        key=rule.key, value=rule.value, document=c.document, origin=c.origin, force="info",
        rule=rule, contributors=(rule.rule_id,), sentence=rule.rule_text,
        source_url=rule.source_url,
    )


def _from_undecided(c: Contribution) -> Contribution | Requirement:
    """Step 2: an unclear sentence, by what its saved readings are about."""
    readings = c.rule.readings
    if readings is None:
        # Written before readings were saved, or about the format, a directive
        # or a condition: for information until `manage.py rederive_rules`.
        return _info(c)
    if readings.key in ASK_KEYS:
        return Requirement(
            key=readings.key, document=c.document, origin=c.origin, force="soft",
            rule=c.rule, contributors=(c.rule.rule_id,), sentence=c.rule.rule_text,
            source_url=c.rule.source_url, ask=True,
        )
    if readings.key in STRICTER_READING_KEYS:
        value = _COMBINE[MERGE[readings.key]](list(readings.values))
        rule = c.rule.model_copy(update={"key": readings.key, "value": value, "readings": None})
        return Contribution(rule=rule, origin=c.origin, document=c.document, rank=c.rank)
    return _info(c)


def _merge_key(group: list[Contribution]) -> list[Requirement]:
    """Steps 3, 4 and 7 for one (document, key)."""
    theirs = sorted(
        (c for c in group if c.origin != "ours"), key=lambda c: THEIRS.index(c.origin)
    )
    if not theirs:
        # Among our own rules today's scope order stands: the more specific
        # wins, and within one scope the last in rule_id order.
        winner = max(enumerate(group), key=lambda pair: (pair[1].rank, pair[0]))[1]
        return [_item(winner, winner.rule.value, group)]
    row = MERGE[theirs[0].rule.key]
    if row == "first":
        # The first stated by theirs applies; every later one is for information.
        first, *rest = theirs
        kept = [c for c in group if all(c is not later for later in rest)]
        return [_item(first, first.rule.value, kept), *(_info(c) for c in rest)]
    try:
        value = _COMBINE[row]([c.rule.value for c in theirs])
    except Irreconcilable:
        key = theirs[0].rule.key
        return [_item(c, c.rule.value, [c], conflict=key) for c in theirs]
    supplier = next((c for c in theirs if c.rule.value == value), theirs[0])
    return [_item(supplier, value, group)]


def _directive_items(directives: Sequence[tuple[PageDirective, Origin]]) -> list[Requirement]:
    """`include` and `emphasise` all kept in theirs-first order; two `order`
    directions for one section are a conflict (step 6)."""
    ordered = sorted(directives, key=lambda pair: THEIRS.index(pair[1]))
    items: list[Requirement] = []
    seen: set[tuple[str, str, str | None]] = set()
    directions: dict[str, set[str | None]] = {}
    for directive, _origin in ordered:
        if directive.action == "order":
            directions.setdefault(directive.target, set()).add(directive.value)
    for directive, origin in ordered:
        identity = (directive.action, directive.target, directive.value)
        if identity in seen:
            continue
        seen.add(identity)
        clash = directive.action == "order" and len(directions[directive.target]) > 1
        items.append(Requirement(
            key=directive.action,
            value=[directive.target, directive.value] if directive.action == "order"
            else directive.target,
            document="cv", origin=origin, force="soft",
            sentence=directive.rule_text, source_url=directive.source_url,
            conflict=f"order:{directive.target}" if clash else "",
        ))
    return items


def _listed(name: str) -> Callable[[object], bool]:
    return lambda value: isinstance(value, list) and name in value


def _is(expected: object) -> Callable[[object], bool]:
    return lambda value: value is expected or value == expected


#: Step 5: pairs of items on different keys no one CV can both satisfy.
CONTRADICTIONS: tuple[tuple[str, Callable[[object], bool], str, Callable[[object], bool]], ...] = (
    ("photo_required", _is(True), "photo_allowed", _is(False)),
    ("required_fields", _listed("photo_url"), "photo_allowed", _is(False)),
    ("required_fields", _listed("date_of_birth"), "date_of_birth_allowed", _is(False)),
    ("include", _is("personal.photo_url"), "photo_allowed", _is(False)),
    ("include", _is("personal.date_of_birth"), "date_of_birth_allowed", _is(False)),
)
#: Step 5's other shape: a floor above a cap on the same document.
FLOOR_ABOVE_CAP: tuple[tuple[str, str], ...] = (
    ("min_words", "max_words"),
    ("min_chars_excl_spaces", "max_chars_excl_spaces"),
    ("min_chars_excl_spaces", "max_chars_incl_spaces"),
)


def _contradicts(a: Requirement, b: Requirement) -> bool:
    if any(
        a.key == a_key and b.key == b_key and a_holds(a.value) and b_holds(b.value)
        for a_key, a_holds, b_key, b_holds in CONTRADICTIONS
    ):
        return True
    return any(
        a.key == floor and b.key == cap
        and isinstance(a.value, int | float) and isinstance(b.value, int | float)
        and a.value > b.value
        for floor, cap in FLOOR_ABOVE_CAP
    )


def _settle_cross_key(items: list[Requirement]) -> list[Requirement]:
    """Step 5. Against ours, theirs win and our item goes; between theirs,
    both sides are marked for step 6."""
    dropped: set[int] = set()
    marked: dict[int, str] = {}
    live = [i for i, item in enumerate(items) if item.force != "info" and not item.ask]
    for i in live:
        for j in live:
            a, b = items[i], items[j]
            if i == j or a.document != b.document or not _contradicts(a, b):
                continue
            if a.origin == "ours" and b.origin != "ours":
                dropped.add(i)
            elif b.origin == "ours" and a.origin != "ours":
                dropped.add(j)
            else:
                marked[i] = marked[j] = f"{a.key}+{b.key}"
    return [
        items[i].model_copy(update={"conflict": marked[i]}) if i in marked else items[i]
        for i in range(len(items)) if i not in dropped
    ]


def merge(
    contributions: Sequence[Contribution],
    directives: Sequence[tuple[PageDirective, Origin]] = (),
) -> tuple[Requirement, ...]:
    """Spec §6.4 steps 1-7, in order. Step 8 is render's."""
    # Step 1: readings about someone else, or lines no reading judged, never
    # become rules -- nor does any other unclear rule on the same line of the
    # same page (review focus 5: keyed by origin, since line numbers restart).
    # The marker itself is kept as a for-information item, so the sentence is
    # still shown (owner, 2026-10-14: a skipped sentence is silent).
    elsewhere = {
        (c.origin, _line(c.rule)) for c in contributions if _is_discarded(c.rule)
    }
    items: list[Requirement] = []
    grouped: dict[tuple[str, str], list[Contribution]] = {}
    for c in contributions:
        if c.rule.key == "undecided":
            if _is_discarded(c.rule):
                items.append(_info(c))
                continue
            if (c.origin, _line(c.rule)) in elsewhere:
                continue
            settled = _from_undecided(c)
            if isinstance(settled, Requirement):
                items.append(settled)
                continue
            c = settled
        if MERGE[c.rule.key] == "info":
            items.append(_info(c))
            continue
        grouped.setdefault((c.document, c.rule.key), []).append(c)
    for group in grouped.values():
        items.extend(_merge_key(group))
    items.extend(_directive_items(directives))
    return tuple(_settle_cross_key(items))
```

- [ ] **Step 5: Run and see them pass.** `uv run pytest -q tests/documents/test_catalog_rules.py -k "stricter or information or font or language or directive or order or format or theirs or ours or force or conflict or unclear or third_party or country_ban"` → all PASS. `uv run ruff check apps/documents/requirement_list.py` → All checks passed.

- [ ] **Step 6: Commit.**

```bash
git -C $W commit -m "feat(cv): merge requirements by who wins (spec 6.4 steps 1-7)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/requirement_list.py tests/documents/test_catalog_rules.py
```

### Task 7: `build_requirements`, the pure builder

**Files:**
- Modify: `apps/documents/requirement_list.py` (imports; `_ORIGIN_BY_SCOPE` after `THEIRS`; append after `merge`)
- Test: `tests/documents/test_requirement_list.py` (append)

**Interfaces:**
- Consumes: `_SCOPE_ORDER`, `_scope_matches`, `_quote`, `rules_from_program`, `directives_from_program` (constraints.py); `letter_shape.constraints_from_shape` (imported inside the function, so render's import graph does not grow); `merge` (Task 6).
- Produces: `build_requirements(program: Any, opportunity: Any = None, *, catalog: Iterable[Any] = (), track: str = "", style_rules: Sequence[ConstraintRule] = (), letter_shape: LetterShape | None = None, document_language: str = "en", competencies: Sequence[str] = ()) -> RequirementList`. Raises `pydantic.ValidationError` on a malformed stored rule or directive.

- [ ] **Step 1: Write the failing tests.** In `tests/documents/test_requirement_list.py` add `from types import SimpleNamespace` after `from dataclasses import fields`, and change the last import to `from apps.documents.requirement_list import LETTER_FIELD_KEYS, Requirement, RequirementList, build_requirements` (wrapped in parentheses, one name per line, if it passes 100 columns). Then append:

```python
def _programme(**overrides):
    base = dict(
        cv_constraints=[], cv_directives=[], cv_format_requirement="any",
        cv_format_source_url="", country_code="DE", academic_track="taught",
        institution=SimpleNamespace(canonical_key="de:tum"),
    )
    return SimpleNamespace(**(base | overrides))


def _row(rule_id, scope_kind, scope_values, key, value, enforcement="BINDING"):
    return SimpleNamespace(
        rule_id=rule_id, scope_kind=scope_kind, scope_values=scope_values, key=key,
        value=value, enforcement=enforcement, rule_text=f"{rule_id} says so.", source_url="",
    )


def test_catalog_scopes_land_as_theirs_or_ours():
    catalog = [
        _row("C-1", "COUNTRY", ["DE"], "photo_allowed", True, "ADVISORY_STYLE"),
        _row("I-1", "INSTITUTION", ["de:tum"], "ai_use_policy", "PROHIBITS",
             "ADVISORY_HIGH_RISK"),
        _row("F-1", "FUNDER", ["daad"], "max_pages", 3),
    ]
    funder = SimpleNamespace(canonical_key="daad", cv_format_requirement="")
    listed = build_requirements(_programme(), funder, catalog=catalog, track="taught")
    origins = {item.contributors[0]: item.origin for item in listed.items if item.contributors}
    assert origins == {"C-1": "ours", "I-1": "institution", "F-1": "scholarship"}


def test_the_format_is_the_funders_then_the_programmes():
    programme = _programme(cv_format_requirement="europass_required",
                           cv_format_source_url="https://tum.example/apply")
    funder = SimpleNamespace(canonical_key="rhodes", cv_format_requirement="funder_template")
    [own] = [i for i in build_requirements(programme).items if i.key == "cv_format"]
    [theirs] = [i for i in build_requirements(programme, funder).items if i.key == "cv_format"]
    assert (own.value, own.origin, own.force) == ("europass_required", "programme", "strict")
    assert (theirs.value, theirs.origin) == ("funder_template", "scholarship")


def test_the_letter_part_is_its_own_document():
    """A 1-page letter limit never becomes the CV's (spec §6.3)."""
    shape = LetterShape(
        max_pages=1.0, form="FORMAL_LETTER",
        sources={"max_pages": {"text": "One page.", "source_url": "u"},
                 "form": {"text": "A formal letter.", "source_url": "u"}},
        written_requirements=({"text": "Say why this programme.", "source_url": "u"},),
        student_actions=({"text": "Sign it by hand.", "source_url": "u"},),
    )
    listed = build_requirements(_programme(), letter_shape=shape)
    letter = {(i.key, i.force) for i in listed.for_document("letter")}
    assert letter == {("max_pages", "strict"), ("form", "strict"),
                      ("written_requirement", "soft"), ("student_action", "info")}
    assert all(rule.key != "max_pages" for rule in listed.cv_rules())


def test_competencies_rank_relevance_only_and_never_reach_render():
    listed = build_requirements(_programme(), competencies=("Linear algebra.",))
    [item] = [i for i in listed.items if i.key == "competency"]
    assert (item.relevance_only, item.force, item.rule) == (True, "info", None)
    assert listed.cv_rules() == ()


def test_a_style_rule_held_in_code_loses_to_any_catalog_rule():
    style = ConstraintRule(rule_id="S-022", key="min_final_page_fill", value=0.2,
                           enforcement=Enforcement.ADVISORY_STYLE, rule_text="Fill it.",
                           scope="UNIVERSAL")
    catalog = [_row("U-9", "UNIVERSAL", [], "min_final_page_fill", 0.3, "ADVISORY_STYLE")]
    listed = build_requirements(_programme(), catalog=catalog, style_rules=(style,))
    assert [(r.rule_id, r.value) for r in listed.cv_rules()] == [("U-9", 0.3)]


def test_a_malformed_stored_directive_raises_rather_than_being_skipped():
    with pytest.raises(ValidationError):
        build_requirements(_programme(cv_directives=[{"action": "exclude", "target": "x"}]))
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest -q tests/documents/test_requirement_list.py` → FAIL: `ImportError: cannot import name 'build_requirements'`.

- [ ] **Step 3: Final imports.** Replace the import lines with:

```python
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constraints import (
    _MULTI_KEYS,
    _SCOPE_ORDER,
    CONSTRAINT_KEYS,
    QUOTE_MAX_CHARS,
    ConstraintRule,
    Enforcement,
    PageDirective,
    _quote,
    _scope_matches,
    directives_from_program,
    rules_from_program,
)

if TYPE_CHECKING:
    from .letter_shape import LetterShape
```

- [ ] **Step 4: The scope-to-origin map.** Insert right after the `THEIRS` line:

```python

#: A catalog scope's origin. INSTITUTION and FUNDER are theirs; the rest are ours.
_ORIGIN_BY_SCOPE: dict[str, Origin] = {
    "UNIVERSAL": "ours", "TRACK": "ours", "COUNTRY": "ours",
    "INSTITUTION": "institution", "FUNDER": "scholarship",
}
```

- [ ] **Step 5: Append the builder** after `merge`:

```python


# --- the builder (spec §6.3) --------------------------------------------------


def _catalog_contributions(
    catalog: Iterable[Any], *, program: Any, opportunity: Any, track: str
) -> list[Contribution]:
    contributions: list[Contribution] = []
    for row in catalog:
        if not _scope_matches(row, program=program, opportunity=opportunity, track=track):
            continue
        rule = ConstraintRule.model_validate({
            "rule_id": row.rule_id, "key": row.key, "value": row.value,
            "enforcement": row.enforcement, "rule_text": row.rule_text,
            "source_url": row.source_url, "scope": row.scope_kind,
        })
        contributions.append(Contribution(
            rule=rule, origin=_ORIGIN_BY_SCOPE[row.scope_kind],
            rank=_SCOPE_ORDER.index(row.scope_kind),
        ))
    return contributions


def _format_item(program: Any, opportunity: Any) -> list[Requirement]:
    """The CV format, never merged by strictness: the funder's, else the
    programme's (render.select_render_variant's order; the country's tabular
    layout is ours and stays render's)."""
    funder = str(getattr(opportunity, "cv_format_requirement", "") or "")
    own = str(getattr(program, "cv_format_requirement", "") or "")
    if funder:
        origin: Origin = "scholarship"
        value, url = funder, ""
    elif own:
        origin, value = "programme", own
        url = str(getattr(program, "cv_format_source_url", "") or "")
    else:
        return []
    return [Requirement(
        key="cv_format", value=value, document="cv", origin=origin,
        force="info" if value == "any" else "strict", source_url=url,
    )]


def _letter_parts(
    shape: LetterShape, document_language: str
) -> tuple[list[Contribution], list[Requirement]]:
    """The letter's lengths as contributions (they merge by the table) and its
    other stated fields, written requirements and student actions as items."""
    from .letter_shape import constraints_from_shape

    contributions = [
        Contribution(rule=rule, origin="programme", document="letter")
        for rule in constraints_from_shape(shape, document_language=document_language)
    ]
    items: list[Requirement] = []
    for name in LETTER_FIELD_KEYS:
        if not shape.is_stated(name):
            continue
        source = shape.sources.get(name, {})
        items.append(Requirement(
            key=name, value=getattr(shape, name), document="letter", origin="programme",
            force="strict", sentence=_quote(source.get("text", "")),
            source_url=source.get("source_url", ""),
        ))
    cited: tuple[tuple[str, tuple[dict[str, str], ...], Force], ...] = (
        ("written_requirement", shape.written_requirements, "soft"),
        ("student_action", shape.student_actions, "info"),
    )
    for key, sentences, force in cited:
        items.extend(
            Requirement(
                key=key, document="letter", origin="programme", force=force,
                sentence=_quote(entry.get("text", "")),
                source_url=entry.get("source_url", ""),
            )
            for entry in sentences
        )
    return contributions, items


def build_requirements(
    program: Any,
    opportunity: Any = None,
    *,
    catalog: Iterable[Any] = (),
    track: str = "",
    style_rules: Sequence[ConstraintRule] = (),
    letter_shape: LetterShape | None = None,
    document_language: str = "en",
    competencies: Sequence[str] = (),
) -> RequirementList:
    """One application's requirement list, from what the caller loaded (§6.3).

    `catalog` is every CatalogRule row in rule_id order -- the merge keeps the
    last same-scope rule, so the order is load-bearing. `style_rules` are our
    own rules held in code (render._UNIVERSAL_RULES). `competencies` are the
    programme's COMPETENCY statement texts, kept for relevance only.
    Raises pydantic.ValidationError on a malformed stored rule or directive,
    as rules_from_program does: a rule we cannot parse is one we cannot keep.
    """
    contributions = [
        *(Contribution(rule=rule, origin="ours", rank=-1) for rule in style_rules),
        *_catalog_contributions(catalog, program=program, opportunity=opportunity, track=track),
    ]
    directives: list[tuple[PageDirective, Origin]] = []
    if program is not None:
        contributions.extend(
            Contribution(rule=rule, origin="programme") for rule in rules_from_program(program)
        )
        directives.extend((d, "programme") for d in directives_from_program(program))
    letter_items: list[Requirement] = []
    if letter_shape is not None:
        letter_rules, letter_items = _letter_parts(letter_shape, document_language)
        contributions.extend(letter_rules)
    return RequirementList(items=(
        *merge(contributions, directives),
        *_format_item(program, opportunity),
        *letter_items,
        *(
            Requirement(
                key="competency", document="cv", origin="programme", force="info",
                sentence=_quote(text), relevance_only=True,
            )
            for text in competencies
        ),
    ))
```

- [ ] **Step 6: Run and see them pass.** `uv run pytest -q tests/documents/test_requirement_list.py` → 10 passed. `uv run ruff check apps/documents/requirement_list.py tests/documents/test_requirement_list.py && uv run mypy apps config` → clean.

- [ ] **Step 7: Commit.**

```bash
git -C $W commit -m "feat(cv): build one requirement list per application (spec 6.3)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/requirement_list.py tests/documents/test_requirement_list.py
```

### Task 8: `resolve_rules` returns the list's CV rules

**Files:**
- Modify: `apps/documents/constraints.py:250-259` (`_SCOPE_ORDER` comment), `:308-373` (`resolve_rules`)
- Test: `tests/documents/test_catalog_rules.py:495-511` and `:533-551` (rewritten on purpose), plus new tests appended

**Interfaces:**
- Consumes: `build_requirements` (Task 7, imported inside the function: `requirement_list` imports `constraints`).
- Produces: `resolve_rules(program, opportunity, *, content) -> tuple[ConstraintRule, ...]`, unchanged signature, now `build_requirements(...).cv_rules()`. Our code-held style rules are not passed (render's `_with_universal_rules` still appends S-022 wherever the key is unset), so every existing `== ()` assertion holds.

- [ ] **Step 1: Rewrite two tests on purpose and add the behaviour tests.** In `tests/documents/test_catalog_rules.py` replace lines 495-511 (`test_an_advisory_programme_rule_cannot_displace_a_binding_one`) with:

```python
def test_an_advisory_programme_rule_cannot_displace_a_binding_one():
    """Rewritten on purpose 2026-10-14 (spec §6.4). R-010 is a FUNDER rule, as
    seeded, so it is theirs and "required beats not stated" keeps it. The old
    version used a UNIVERSAL R-010; under "theirs beat ours" a page rule now
    beats that one by design -- see the next test."""
    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=["daad"],
        key="date_of_issue_required",
        value=True,
        enforcement="BINDING",
    )
    programme = _programme("DE", constraints=[_derived("date_of_issue_required", False)])

    resolved = resolve_rules(programme, _opportunity("daad"), content=_taught_content())

    kept = [r for r in resolved if r.key == "date_of_issue_required"]
    assert [r.rule_id for r in kept] == ["R-010"]
    assert kept[0].enforcement == Enforcement.BINDING
    assert kept[0].value is True


def test_a_page_rule_beats_a_binding_universal_one_and_keeps_its_force():
    """Theirs beat ours (spec §6.4 step 3), and the merged rule keeps the
    strongest enforcement of the rules it came from (step 7)."""
    _rule(rule_id="R-010", scope_kind=CatalogRule.ScopeKind.UNIVERSAL, scope_values=[],
          key="date_of_issue_required", value=True, enforcement="BINDING")
    programme = _programme("DE", constraints=[_derived("date_of_issue_required", False)])

    resolved = resolve_rules(programme, None, content=_taught_content())

    assert [(r.rule_id, r.value, r.enforcement) for r in resolved] == [
        ("PAGE-0", False, Enforcement.BINDING),
    ]
```

Replace lines 533-551 (`test_a_binding_programme_rule_still_replaces_a_binding_catalog_one`) with:

```python
def test_a_binding_programme_rule_no_longer_replaces_a_stricter_binding_funder_one():
    """Rewritten on purpose 2026-10-14; it was
    test_a_binding_programme_rule_still_replaces_a_binding_catalog_one. Between
    theirs the stricter value wins (spec §6.4 step 4), not the more specific
    source: a programme saying no date of issue is needed cannot remove the
    funder's requirement for one."""
    _rule(
        rule_id="R-010",
        scope_kind=CatalogRule.ScopeKind.FUNDER,
        scope_values=["daad"],
        key="date_of_issue_required",
        value=True,
        enforcement="BINDING",
    )
    curated = _derived("date_of_issue_required", False)
    curated |= {"rule_id": "R-999", "enforcement": "BINDING"}
    programme = _programme("DE", constraints=[curated])

    resolved = resolve_rules(programme, _opportunity("daad"), content=_taught_content())

    assert [(r.rule_id, r.value) for r in resolved if r.key == "date_of_issue_required"] == [
        ("R-010", True),
    ]
```

Append at the end of the file:

```python
def test_theirs_beat_ours_through_resolve_rules_even_when_theirs_is_soft():
    _rule(rule_id="R-023", scope_kind=CatalogRule.ScopeKind.TRACK, scope_values=["taught"],
          key="max_pages", value=2, enforcement="ADVISORY_STYLE")
    programme = _programme("DE", constraints=[_derived("max_pages", 3, "Up to three pages.")])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert [(r.rule_id, r.value) for r in resolved if r.key == "max_pages"] == [("PAGE-0", 3)]


def test_a_soft_page_limit_under_a_binding_funder_one_is_enforced_as_binding():
    _rule(rule_id="R-012", scope_kind=CatalogRule.ScopeKind.FUNDER, scope_values=["daad"],
          key="max_pages", value=3)
    programme = _programme("DE", constraints=[_derived("max_pages", 2, "Two pages.")])
    resolved = resolve_rules(programme, _opportunity("daad"), content=_taught_content())
    assert [(r.rule_id, r.value, r.enforcement) for r in resolved] == [
        ("PAGE-0", 2, Enforcement.BINDING),
    ]


def test_an_unclear_programme_limit_reaches_render_as_its_stricter_reading():
    programme = _programme("DE", constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "undecided", "value": "max_pages",
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "Two or three pages.",
        "readings": {"key": "max_pages", "values": [3, 2]},
    }])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert [(r.rule_id, r.key, r.value, r.enforcement, r.readings) for r in resolved] == [
        ("PAGE-0-max_pages", "max_pages", 2, Enforcement.ADVISORY_HIGH_RISK, None),
    ]


def test_a_third_party_sentence_reaches_render_only_as_information():
    programme = _programme("DE", constraints=[
        {"rule_id": "PAGE-4-max_pages", "key": "undecided", "value": "max_pages",
         "enforcement": "ADVISORY_HIGH_RISK",
         "rule_text": "Short CV (max. 2 pages) from this academic supervisor.",
         "readings": {"key": "max_pages", "values": [2, 3]}},
        {"rule_id": "PAGE-4-third_par", "key": "undecided", "value": "third_party",
         "enforcement": "ADVISORY_HIGH_RISK",
         "rule_text": "Short CV (max. 2 pages) from this academic supervisor."},
    ])
    resolved = resolve_rules(programme, None, content=_taught_content())
    assert [(r.key, r.value, r.enforcement) for r in resolved] == [
        ("undecided", "third_party", Enforcement.ADVISORY_HIGH_RISK)
    ]


def test_a_for_information_rule_never_refuses_a_cv():
    """An ai_use_policy row seeded BINDING by mistake still cannot block."""
    _rule(rule_id="L-041", scope_kind=CatalogRule.ScopeKind.INSTITUTION,
          scope_values=["gb:university of cambridge"], key="ai_use_policy",
          value="PROHIBITS", enforcement="BINDING")
    cambridge = _programme(country_code="GB")
    cambridge.institution.canonical_key = "gb:university of cambridge"
    cambridge.institution.save(update_fields=["canonical_key"])

    resolved = resolve_rules(cambridge, None, content=_taught_content())

    assert [r.enforcement for r in resolved] == [Enforcement.ADVISORY_HIGH_RISK]
    render_cv(_taught_content(), variant="STANDARD", constraints=resolved)
```

- [ ] **Step 2: Run and see the new and rewritten ones fail.** `uv run pytest -q tests/documents/test_catalog_rules.py` → FAIL on `test_a_page_rule_beats_a_binding_universal_one_and_keeps_its_force` (old code keeps R-010), `test_a_binding_programme_rule_no_longer_replaces...` (old code returns R-999), `test_theirs_beat_ours...` passes already, `test_an_unclear_programme_limit...` (returns the undecided rule unchanged), `test_a_third_party_sentence_reaches_render_only_as_information` (returns two rules), `test_a_for_information_rule_never_refuses_a_cv` (BINDING), `test_a_soft_page_limit_under_a_binding_funder_one...` (ADVISORY).

- [ ] **Step 3: Replace the merge.** In `apps/documents/constraints.py` replace the whole of `resolve_rules` (lines 308-373) with:

```python
def resolve_rules(program: Any, opportunity: Any, *, content: Any) -> tuple[ConstraintRule, ...]:
    """The rules that apply to one programme-and-scholarship pair: the CV half
    of its requirement list (spec 2026-10-12 §6.4), so render and the list
    agree by construction.

    Theirs (the programme's page, the funder, the institution) beat ours (the
    universal, track and country rules), even when theirs is soft; among
    theirs the stricter value wins per key; among ours the more specific scope
    wins, as before. A merged rule carries the strongest enforcement of every
    rule it came from, so a page sentence can never lower a BINDING rule's
    enforcement -- the PII boundary render._blocked_by_content_only_rules
    stands on. `opportunity=None` means a self-funded, direct application.

    Our style rules held in code (render._UNIVERSAL_RULES) are not passed:
    render appends them itself wherever nothing here set the key.
    """
    from apps.funding.models import CatalogRule

    from .requirement_list import build_requirements

    # order_by is load-bearing, not cosmetic: the merge keeps the last rule
    # seen at a given scope rank, so two same-scope rules setting the same key
    # would otherwise resolve by Postgres row order.
    return build_requirements(
        program,
        opportunity,
        catalog=CatalogRule.objects.order_by("rule_id"),
        track=resolve_track(program, content),
    ).cv_rules()
```

and insert these two lines directly above line 250 (`#: Least specific first. A later scope's rule replaces an earlier one for the`), leaving the rest of that comment unchanged:

```python
#: Ranks OUR rules only since 2026-10-14; theirs merge by strictness
#: (requirement_list.merge).
```

- [ ] **Step 4: Run and see them pass.** `uv run pytest -q tests/documents/test_catalog_rules.py tests/documents/test_academic_track.py tests/documents/test_derive.py tests/documents/test_rule_sinks_cv.py` → PASS. `test_programme_constraints_win_over_every_catalog_scope` (line 204) and `test_a_derived_rule_cannot_unlock_the_europass_pii_egress` (line 553) pass unchanged.

- [ ] **Step 5: Commit.**

```bash
git -C $W commit -m "feat(cv): resolve_rules is the requirement list's CV half" \
  -m "Two tests rewritten on purpose: theirs beat ours, and between theirs the stricter value wins." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/constraints.py tests/documents/test_catalog_rules.py
```

### Task 9: Step 8, nothing banned reaches europa.eu

**Files:**
- Modify: `apps/documents/render.py:983-999` (`europass_content`, new `without_banned_content` above it), `:1015` (`render_cv_with_warnings`)
- Modify: `apps/documents/europass_render.py:22`, `:120`
- Test: `tests/documents/test_render.py:1129-1157` (rewritten on purpose) and appended tests; `tests/documents/test_europass_render.py` (append)

**Interfaces:**
- Consumes: `resolve_rules` (Task 8).
- Produces: `without_banned_content(content: CVContent, constraints: tuple[ConstraintRule, ...]) -> CVContent` (strips `photo_url` on any `photo_allowed=False`, `date_of_birth` on any `date_of_birth_allowed=False`, `orcid`/`linkedin_url`/`github_url`/`website_url` and every publication `doi` on `prohibited_content ∋ "hyperlinks"`, whatever the enforcement); `europass_content(content, directives, *, today=None, constraints=())`. Only the `EUROPASS_API` variant passes constraints in this step; step 4.4 widens it to every variant.

- [ ] **Step 1: Rewrite one test on purpose.** In `tests/documents/test_render.py` replace lines 1129-1157 (`test_no_network_call_when_a_binding_content_rule_already_blocks`) with:

```python
def test_no_network_call_when_a_binding_content_rule_already_blocks(monkeypatch):
    """A strict content-only rule code cannot apply (a required field the
    student has not given) blocks before any egress. Rewritten on purpose
    2026-10-14: it used a BINDING photo ban, which spec §6.4 step 8 now
    applies to the content first -- so that render is no longer blocked
    (test_a_strict_ban_code_can_apply_no_longer_stops_the_send)."""
    from apps.documents import render as render_module

    monkeypatch.setattr(
        render_module, "render_europass_pdf", lambda content, **_: pytest.fail("network")
    )
    rule = ConstraintRule(
        rule_id="R-079",
        key="required_fields",
        value=["citizenship"],
        enforcement=Enforcement.BINDING,
        rule_text="SISGP: citizenship is a fixed template field.",
        source_url="",
    )
    with pytest.raises(PreflightBlocked):
        render_cv(
            _content(),
            variant="EUROPASS_API",
            constraints=(rule,),
            allow_network=True,
        )
```

- [ ] **Step 2: Write the failing tests.** Append to `tests/documents/test_render.py`:

```python
# --- spec 2026-10-12 §6.4 step 8: the privacy check before europa.eu ----------


def _sent(monkeypatch):
    """Capture the content handed to europa.eu, answering with the genuine fixture."""
    from apps.documents import render as render_module

    genuine = pathlib.Path("tests/documents/fixtures/europass_api.pdf").read_bytes()
    sent = []

    def _capture(content, **_):
        sent.append(content)
        return genuine

    monkeypatch.setattr(render_module, "render_europass_pdf", _capture)
    return sent


def _with_dob_and_links():
    content = _content(photo_url="https://example.org/photo.jpg")
    personal = content.personal_information.model_copy(update={
        "date_of_birth": date(2000, 1, 1), "github_url": "https://github.com/jane",
        "orcid": "0000-0002-1825-0097",
    })
    return content.model_copy(update={"personal_information": personal})


def _ban(key, value, enforcement=Enforcement.ADVISORY_HIGH_RISK):
    return ConstraintRule(rule_id=f"PAGE-0-{key}"[:20], key=key, value=value,
                          enforcement=enforcement, rule_text="The page's sentence.")


def test_a_soft_page_ban_cannot_let_personal_data_reach_europa_eu(monkeypatch):
    sent = _sent(monkeypatch)
    render_cv_with_warnings(
        _with_dob_and_links(), variant="EUROPASS_API", allow_network=True,
        constraints=(_ban("date_of_birth_allowed", False), _ban("photo_allowed", False),
                     _ban("prohibited_content", ["hyperlinks"])),
    )
    [personal] = [content.personal_information for content in sent]
    assert (personal.date_of_birth, personal.photo_url, personal.github_url, personal.orcid) == (
        None, None, None, None)


def test_a_strict_ban_code_can_apply_no_longer_stops_the_send(monkeypatch):
    sent = _sent(monkeypatch)
    artifact = render_cv(
        _content(photo_url="https://example.org/photo.jpg"), variant="EUROPASS_API",
        constraints=(_ban("photo_allowed", False, Enforcement.BINDING),), allow_network=True,
    )
    assert artifact.variant == "EUROPASS_API"
    assert sent[0].personal_information.photo_url is None


def test_a_soft_unmet_content_rule_never_stops_a_send(monkeypatch):
    sent = _sent(monkeypatch)
    _artifact, violations = render_cv_with_warnings(
        _content(), variant="EUROPASS_API", allow_network=True,
        constraints=(_ban("required_fields", ["citizenship"]),),
    )
    assert len(sent) == 1
    assert [v.rule.key for v in violations] == ["required_fields"]


def test_a_local_render_still_reports_a_ban_rather_than_applying_it():
    """Build step 4.4 applies the bans to every variant; until then only the
    europa.eu path strips."""
    _artifact, violations = render_cv_with_warnings(
        _content(photo_url="https://example.org/photo.jpg"), variant="STANDARD",
        constraints=(_ban("photo_allowed", False),),
    )
    assert [v.detail for v in violations] == ["content includes a photo"]
```

Append to `tests/documents/test_europass_render.py`:

```python
def test_the_cache_key_tells_a_programme_banning_links_from_one_that_does_not():
    """Review focus 2. The key hashes what is SENT, and a hyperlink ban
    changes what is sent: the DOI leaves the payload."""
    from apps.documents.constraints import ConstraintRule, Enforcement
    from apps.documents.render import europass_content
    from apps.documents.schemas import PublicationEntry

    from .test_europass import _content as _cv

    content = _cv(publications=(PublicationEntry(
        authors=("Doe, J.",), self_author_index=0, title="Sparsifiers in practice",
        venue="Journal of Examples", year=2024, doi="10.1000/sparsifiers",
    ),))
    no_links = ConstraintRule(rule_id="PAGE-0-prohibited", key="prohibited_content",
                              value=["hyperlinks"], enforcement=Enforcement.ADVISORY_HIGH_RISK,
                              rule_text="No hyperlinks.")
    assert payload_hash(*europass_content(content, ())) != payload_hash(
        *europass_content(content, (), constraints=(no_links,))
    )
```

- [ ] **Step 3: Run and see them fail.** `uv run pytest -q tests/documents/test_render.py -k "europa_eu or ban or send" tests/documents/test_europass_render.py -k "banning_links"` → FAIL: the soft ban test sees a date of birth, `test_a_strict_ban_code_can_apply...` raises `PreflightBlocked`, the cache test raises `TypeError: europass_content() got an unexpected keyword argument 'constraints'`.

- [ ] **Step 4: Add the strip and route it.** In `apps/documents/render.py` replace `europass_content` (lines 983-999) with:

```python
def without_banned_content(
    content: CVContent, constraints: tuple[ConstraintRule, ...]
) -> CVContent:
    """Spec 2026-10-12 §6.4 step 8: the bans code can apply exactly, applied
    whatever their enforcement, so a soft rule cannot let personal data out.

    The photo, the date of birth and hyperlinks (contact links and DOIs).
    Every other content-only key -- a cap, a required field, a gap, a date of
    issue -- needs the student's facts or a choice, so it stays a check that
    _blocked_by_content_only_rules runs on what this returns.
    """
    def banned(key: str, value: object) -> bool:
        return any(
            rule.key == key and (
                rule.value == value
                or (isinstance(rule.value, list) and value in rule.value)
            )
            for rule in constraints
        )

    personal: dict[str, object] = {}
    if banned("photo_allowed", False):
        personal["photo_url"] = None
    if banned("date_of_birth_allowed", False):
        personal["date_of_birth"] = None
    links = banned("prohibited_content", "hyperlinks")
    if links:
        personal |= {"orcid": None, "linkedin_url": None, "github_url": None, "website_url": None}
    update: dict[str, object] = {}
    if personal:
        update["personal_information"] = content.personal_information.model_copy(update=personal)
    if links:
        update["publications"] = tuple(
            pub.model_copy(update={"doi": None}) for pub in content.publications
        )
    return content.model_copy(update=update) if update else content


def europass_content(
    content: CVContent,
    directives: tuple[PageDirective, ...],
    *,
    today: date | None = None,
    constraints: tuple[ConstraintRule, ...] = (),
) -> tuple[CVContent, bool]:
    """What EUROPASS_API sends: the funnel's content, and whether its experience
    runs oldest first. One function because two places need the same answer --
    the render, and the cache key (europass_render.payload_hash), which must
    hash what is sent or two programmes asking different orders share a PDF.
    `constraints` are applied by `without_banned_content`, so the key also
    tells a programme that bans hyperlinks from one that does not.
    """
    clean = apply_directives(
        reverse_chronological(
            without_future_starts(
                without_duplicated_posts(hygienic_content(content)), today or date.today()
            )
        ),
        directives,
    )
    return (
        without_banned_content(clean, constraints),
        "experience" in _oldest_first_sections(directives),
    )
```

and replace line 1015

```python
    clean, _ = europass_content(content, directives, today=today)
```

with

```python
    # Step 8 strips banned content only on the path that sends it to
    # europa.eu; every other variant still reports the rule (build step 4.4
    # applies the bans to every variant).
    clean, _ = europass_content(
        content, directives, today=today,
        constraints=constraints if variant == "EUROPASS_API" else (),
    )
```

- [ ] **Step 5: The cache key hashes the same content.** In `apps/documents/europass_render.py` replace line 22 with `from .constraints import directives_from_program, resolve_rules` and line 120

```python
    digest = payload_hash(*europass_content(content, directives))
```

with

```python
    # The same rules render_draft resolves, so the key hashes the content
    # without_banned_content leaves -- what is actually sent.
    constraints = resolve_rules(draft.programme, draft.funding_opportunity, content=content)
    digest = payload_hash(*europass_content(content, directives, constraints=constraints))
```

- [ ] **Step 6: Run and see them pass.** `uv run pytest -q tests/documents/test_render.py tests/documents/test_europass_render.py tests/documents/test_europass.py` → PASS.

- [ ] **Step 7: Commit.**

```bash
git -C $W commit -m "feat(cv): bans are applied before any europa.eu payload, soft ones included" \
  -m "One test rewritten on purpose: a BINDING photo ban is now applied, not a block." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/render.py apps/documents/europass_render.py \
     tests/documents/test_render.py tests/documents/test_europass_render.py
```

---

# Part B: the §8 grammar keys

Separate tasks, each its own review: they change what the decision provider is asked (new options on a measured surface). Part A does not depend on them; the keys and table rows already exist from Tasks 1 and 5. `cv_language` and `cv_signature` need no change: the grammar's `language` operation already writes `language` (`grammar._cv_sink`) and the `signature_required` style already writes `signature_required` (`grammar._CV_STYLE_SINK`). Live accuracy of the new options is unmeasured here; it is measured by the existing `live` grammar gate (`tests/documents/test_grammar_gate.py`), run when the owner approves the cost.

### Task 10: `photo_required` has its own key and checker

**Files:**
- Modify: `apps/documents/grammar.py:171-186` (`_CV_STYLE_SINK` and its comment)
- Modify: `apps/documents/render.py:675` (new checker above `_check_date_of_birth`), `:879` (`_CHECKERS`), `:896-907` (`_CONTENT_ONLY_KEYS`)
- Test: `tests/documents/test_rule_sinks_cv.py`, `tests/documents/test_render.py` (append)

**Interfaces:**
- Produces: `sink_for("cv", "style", "photo_required") == "photo_required"`; `_check_photo_required(rule, content, artifact) -> str | None`; `photo_required` is content-only, so a strict unmet one blocks the Europass send.

- [ ] **Step 1: Write the failing tests.** Append to `tests/documents/test_rule_sinks_cv.py`:

```python
def test_a_required_photo_is_its_own_key():
    """Spec 2026-10-12 §8: no longer `unapplied`."""
    [rule] = to_constraint_rules((_rule(0, "style", "photo_required"),), source_url=_URL)
    assert (rule.key, rule.value) == ("photo_required", True)
```

Append to `tests/documents/test_render.py`:

```python
def test_a_required_photo_that_is_missing_is_reported():
    _artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_ban("photo_required", True),))
    assert [v.detail for v in violations] == ["content has no photo"]


def test_a_strict_required_photo_that_is_missing_stops_the_send(monkeypatch):
    from apps.documents import render as render_module

    monkeypatch.setattr(
        render_module, "render_europass_pdf", lambda content, **_: pytest.fail("network")
    )
    with pytest.raises(PreflightBlocked):
        render_cv(_content(), variant="EUROPASS_API", allow_network=True,
                  constraints=(_ban("photo_required", True, Enforcement.BINDING),))
```

- [ ] **Step 2: Run and see them fail.** `uv run pytest -q tests/documents/test_rule_sinks_cv.py -k required_photo tests/documents/test_render.py -k required_photo` → FAIL: `ValueError: not enough values to unpack` (no rule written) and `['no pre-flight check for 'photo_required'']`.

- [ ] **Step 3: The sink.** In `apps/documents/grammar.py` replace lines 171-177

```python
#: `photo_required` is deliberately absent (fix round 1, finding 2, controller
#: ruling): `render._check_photo` only fires on `photo_allowed=False`, so
#: mapping `photo_required` onto that key would name a sink nothing requires
#: a photo from -- an applied-looking rule that enforces nothing. It returns
#: "" (unapplied) instead. Every other key here lacking a pre-flight checker
#: stays, by the same ruling: a loud "no pre-flight check" is acceptable.
_CV_STYLE_SINK: dict[str, str] = {
```

with

```python
#: `photo_required` has its own key (spec 2026-10-12 §8) and its own checker,
#: render._check_photo_required. It used to return "" (unapplied) because the
#: only photo key, photo_allowed, stores "required" and "allowed" alike as
#: True. Every key here lacking a pre-flight checker stays, by the fix-round-1
#: ruling: a loud "no pre-flight check" is acceptable.
_CV_STYLE_SINK: dict[str, str] = {
    "photo_required": "photo_required",
```

- [ ] **Step 4: The checker.** In `apps/documents/render.py` insert above `def _check_date_of_birth(`:

```python
def _check_photo_required(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Spec 2026-10-12 §8: a page requiring a photo. The engine never supplies
    one; build step 4.3 asks the student for it."""
    if rule.value is True and not content.personal_information.photo_url:
        return "content has no photo"
    return None


```

In `_CHECKERS` add `    "photo_required": _check_photo_required,` after the `"photo_allowed": _check_photo,` line, and in `_CONTENT_ONLY_KEYS` add `        "photo_required",` after `        "photo_allowed",`.

- [ ] **Step 5: Run and see them pass.** `uv run pytest -q tests/documents/test_rule_sinks_cv.py tests/documents/test_render.py tests/documents/test_grammar_types.py tests/documents/test_grammar_values.py` → PASS.

- [ ] **Step 6: Commit.**

```bash
git -C $W commit -m "feat(cv): a page can require a photo (spec 8)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/grammar.py apps/documents/render.py \
     tests/documents/test_rule_sinks_cv.py tests/documents/test_render.py
```

### Task 11: `cv_scope` and `cv_start` are read from the page

**Files:**
- Modify: `apps/documents/grammar.py:126-135` (`STYLE_VALUES`), `:178-186` (`_CV_STYLE_SINK`)
- Modify: `apps/documents/grammar_values.py:1021-1026` (`_STYLE_DETAIL`)
- Modify: `apps/documents/rule_sinks.py:163-182` (`_STYLE_VALUE`), `:273-276` (`to_constraint_rules`), new `_cv_start_years` above `page_rule_id` (line 294), `:428-433` (`to_notes`)
- Test: `tests/documents/test_grammar_values.py`, `tests/documents/test_rule_sinks_cv.py` (append)

**Interfaces:**
- Produces: style values `cv_complete`, `cv_relevant_only` → `cv_scope` `"complete"`/`"relevant_only"`; `cv_start_upper_secondary`, `cv_start_first_degree` → `cv_start {"milestone": ..., "years": None}`; `cv_start_last_years` + `style_number` → `cv_start {"milestone": None, "years": n}` with `n` a whole number 1-60, otherwise an `unapplied` note. No letter sink for any of them.

- [ ] **Step 1: Write the failing tests.** Append to `tests/documents/test_grammar_values.py`:

```python
@pytest.mark.parametrize(("style", "value"),
                         [("cv_complete", "complete"), ("cv_relevant_only", "relevant_only")])
def test_how_much_history_a_cv_holds_is_the_cv_scope_key(style, value):
    from apps.documents.rule_sinks import to_constraint_rules

    candidates, slots = _one("Your CV must list your complete history.", "cv", "style")
    rules = read_values(candidates, slots, client=_script({"0:style": (style, 0.93)}))
    assert [(r.key, r.value) for r in to_constraint_rules(rules, source_url="u")] == [
        ("cv_scope", value)]


@pytest.mark.parametrize(("style", "number", "value"), [
    ("cv_start_upper_secondary", None, {"milestone": "upper_secondary", "years": None}),
    ("cv_start_first_degree", None, {"milestone": "first_degree", "years": None}),
    ("cv_start_last_years", "10", {"milestone": None, "years": 10}),
])
def test_where_a_cv_starts_is_the_cv_start_key(style, number, value):
    from apps.documents.rule_sinks import to_constraint_rules

    candidates, slots = _one("Only list the last 10 years.", "cv", "style")
    answers = {"0:style": (style, 0.93)} | ({"0:style_number": (number, 0.95)} if number else {})
    rules = read_values(candidates, slots, client=_script(answers))
    assert [(r.key, r.value) for r in to_constraint_rules(rules, source_url="u")] == [
        ("cv_start", value)]


def test_the_scope_and_start_have_no_letter_sink():
    for style in ("cv_complete", "cv_relevant_only", "cv_start_upper_secondary",
                  "cv_start_first_degree", "cv_start_last_years"):
        assert sink_for("motivation_letter", "style", style) == ""
```

Append to `tests/documents/test_rule_sinks_cv.py`:

```python
def test_a_start_point_with_no_whole_count_of_years_is_an_unapplied_note():
    bad = (_rule(0, "style", "cv_start_last_years", detail="2.5"),)
    assert to_constraint_rules(bad, source_url=_URL) == ()
    assert [n.key for n in to_notes(bad, source_url=_URL)] == ["unapplied"]
```

- [ ] **Step 2: Run and see them fail.** `uv run pytest -q tests/documents/test_grammar_values.py -k "cv_scope or cv_start or scope_and_start" tests/documents/test_rule_sinks_cv.py -k start_point` → FAIL: the style Choice has no such option (the script answer is outside `options`) and `to_constraint_rules` writes nothing.

- [ ] **Step 3: Grammar values and sinks.** In `apps/documents/grammar.py` replace

```python
    "no_gaps", "no_hyperlinks",
)
```

with

```python
    "no_gaps", "no_hyperlinks",
    # Spec 2026-10-12 §8: how much of the history a CV must hold, and from
    # when. `cv_start_last_years` reads its number through `style_number`.
    "cv_complete", "cv_relevant_only",
    "cv_start_upper_secondary", "cv_start_first_degree", "cv_start_last_years",
)
```

and replace

```python
    "no_gaps": "no_unexplained_gaps",
    "no_hyperlinks": "prohibited_content",
}
```

with

```python
    "no_gaps": "no_unexplained_gaps",
    "no_hyperlinks": "prohibited_content",
    "cv_complete": "cv_scope",
    "cv_relevant_only": "cv_scope",
    "cv_start_upper_secondary": "cv_start",
    "cv_start_first_degree": "cv_start",
    "cv_start_last_years": "cv_start",
}
```

- [ ] **Step 4: The number for the last-years start.** In `apps/documents/grammar_values.py` replace

```python
    "line_spacing": "style_spacing",
    "margins": "style_number",
}
```

with

```python
    "line_spacing": "style_spacing",
    "margins": "style_number",
    "cv_start_last_years": "style_number",
}
```

- [ ] **Step 5: The projections.** In `apps/documents/rule_sinks.py` replace

```python
    # The one token render._check_prohibited_content knows.
    "no_hyperlinks": ["hyperlinks"],
}
```

with

```python
    # The one token render._check_prohibited_content knows.
    "no_hyperlinks": ["hyperlinks"],
    # Spec 2026-10-12 §8. `cv_start_last_years` is built from its number
    # (`_cv_start_years`), so it is deliberately not here.
    "cv_complete": "complete",
    "cv_relevant_only": "relevant_only",
    "cv_start_upper_secondary": {"milestone": "upper_secondary", "years": None},
    "cv_start_first_degree": {"milestone": "first_degree", "years": None},
}
```

In `to_constraint_rules` replace

```python
        if rule.operation == "style":
            # A flag style is its polarity; a detail style (font family, point
            # size) is the value the sentence printed, which `detail` carries.
            value = _STYLE_VALUE.get(str(rule.value), rule.detail or rule.value)
```

with

```python
        if rule.operation == "style" and rule.value == "cv_start_last_years":
            years = _cv_start_years(rule.detail)
            if years is None:
                continue
            value: object = {"milestone": None, "years": years}
        elif rule.operation == "style":
            # A flag style is its polarity; a detail style (font family, point
            # size) is the value the sentence printed, which `detail` carries.
            value = _STYLE_VALUE.get(str(rule.value), rule.detail or rule.value)
```

Insert above `def page_rule_id(`:

```python
def _cv_start_years(detail: str) -> int | None:
    """The years in "your last 10 years", or None when the picked number is
    not a whole count from 1 to 60 -- a misread is no rule, never a guess."""
    try:
        years = float(detail)
    except ValueError:
        return None
    return int(years) if years.is_integer() and 1 <= years <= 60 else None


```

In `to_notes` replace

```python
            is_cv_student_action = rule.document == "cv" and rule.operation == "student_action"
            if is_other_template:
                kind = "undecided"
            elif is_cv_floor or is_cv_student_action or is_extra_font or is_bad_directive:
```

with

```python
            is_cv_student_action = rule.document == "cv" and rule.operation == "student_action"
            # A start-point whose years are no whole count: to_constraint_rules
            # writes nothing for it, so its sentence must land here.
            is_bad_start = (
                is_cv and rule.operation == "style" and rule.value == "cv_start_last_years"
                and _cv_start_years(rule.detail) is None
            )
            if is_other_template:
                kind = "undecided"
            elif (is_cv_floor or is_cv_student_action or is_extra_font or is_bad_directive
                  or is_bad_start):
```

- [ ] **Step 6: Run and see them pass.** `uv run pytest -q tests/documents/test_grammar_values.py tests/documents/test_rule_sinks_cv.py tests/documents/test_grammar_types.py tests/documents/test_rule_sinks_letter.py` → PASS.

- [ ] **Step 7: Commit.**

```bash
git -C $W commit -m "feat(cv): read how much history a CV holds and where it starts (spec 8)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/grammar.py apps/documents/grammar_values.py apps/documents/rule_sinks.py \
     tests/documents/test_grammar_values.py tests/documents/test_rule_sinks_cv.py
```

### Task 12: A per-section item cap folds into `max_entries_per_section`

**Files:**
- Modify: `apps/documents/grammar.py:87` (`UNITS`), `:156`, `:167` (plausibility bands), `:187-192` (`_CV_LIMIT_SINK`)
- Modify: `apps/documents/grammar_values.py:375-379` (`_BOUND_CRITERIA["maximum"]`), `:410-411` (`_UNIT_CRITERIA`), `:631` (section question), `:918-925` (`_limit_drafts`)
- Modify: `apps/documents/rule_sinks.py:77-80` (`_bucket`), `:277` (`to_constraint_rules`)
- Test: `tests/documents/test_grammar_types.py:207-215` (the `UNITS` pin, updated on purpose), `tests/documents/test_grammar_values.py`, `tests/documents/test_rule_sinks_cv.py`

**Interfaces:**
- Produces: unit `entries` (CV only); per figure question `"{i}:figure:{k}:section"` (`_SECTIONS` + `"none"`), read only when the unit is `entries`; `Rule.detail` holds the section; `max_entries_per_section {section: n}`; caps on different sections never contradict in `resolve_conflicts`. Spelled-out numbers ("three") are not figures (`letter_terms.figures_on_line`), so only digit caps are read, as for every limit.

- [ ] **Step 1: Update the pin and write the failing tests.** In `tests/documents/test_grammar_types.py` line 210 replace

```python
    assert set(UNITS) == {"pages", "words", "characters", "megabytes"}
```

with

```python
    # `entries` added on purpose 2026-10-14 (spec §8, the planned cv_item_cap).
    assert set(UNITS) == {"pages", "words", "characters", "megabytes", "entries"}
```

Append to `tests/documents/test_grammar_values.py`:

```python
def test_a_count_of_entries_in_a_section_is_max_entries_per_section():
    from apps.documents.rule_sinks import to_constraint_rules

    candidates, slots = _one("List at most 3 publications.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("entries", 0.95),
        "0:figure:0:section": ("publications", 0.94),
    }))
    assert [(r.key, r.value) for r in to_constraint_rules(rules, source_url="u")] == [
        ("max_entries_per_section", {"publications": 3})]


def test_a_count_of_entries_in_no_section_is_unapplied():
    candidates, slots = _one("List at most 3 items.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("entries", 0.95),
    }))
    assert [(r.operation, r.note) for r in rules] == [("limit", "unapplied")]


def test_an_unsure_section_is_a_note_not_a_cap():
    candidates, slots = _one("List at most 3 publications.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("entries", 0.95),
        "0:figure:0:section": ("publications", 0.4),
    }))
    assert [r.note for r in rules] == ["unsure"]


def test_a_letter_has_no_entries_sink():
    assert limit_sink("motivation_letter", "maximum", "entries") == ""
    assert limit_sink("cv", "maximum", "entries") == "max_entries_per_section"
```

Append to `tests/documents/test_rule_sinks_cv.py`:

```python
def test_caps_on_two_sections_do_not_contradict_each_other():
    from apps.documents.rule_sinks import resolve_conflicts

    rules = resolve_conflicts((
        _rule(0, "limit", 3, unit="entries", bound="maximum", detail="publications"),
        _rule(1, "limit", 5, unit="entries", bound="maximum", detail="experience"),
    ))
    assert all(r.applied for r in rules)
    assert [r.value for r in to_constraint_rules(rules, source_url=_URL)] == [
        {"publications": 3}, {"experience": 5}]
```

- [ ] **Step 2: Run and see them fail.** `uv run pytest -q tests/documents/test_grammar_types.py tests/documents/test_grammar_values.py -k "entries or units" tests/documents/test_rule_sinks_cv.py -k two_sections` → FAIL (`entries` not in `UNITS`; no sink).

- [ ] **Step 3: The unit.** In `apps/documents/grammar.py` replace line 87

```python
UNITS: tuple[str, ...] = ("pages", "words", "characters", "megabytes")
```

with

```python
#: `entries` is a count of items in one CV section ("at most three
#: publications"), the CV's max_entries_per_section (spec 2026-10-12 §8, the
#: planned `cv_item_cap`); its section is asked per figure. The letter has none.
UNITS: tuple[str, ...] = ("pages", "words", "characters", "megabytes", "entries")
```

replace line 156 with

```python
_IMPLAUSIBLE_CAP = {"words": 50, "chars": 200, "pages": 0.25, "megabytes": 0.1, "entries": 1}
```

replace line 167 with

```python
_IMPLAUSIBLE_MAX = {
    "words": 20_000, "chars": 100_000, "pages": 20, "megabytes": 100, "entries": 50,
}
```

and in `_CV_LIMIT_SINK` add `    "entries": "max_entries_per_section",` after `    "megabytes": "max_bytes",`.

- [ ] **Step 4: The questions.** In `apps/documents/grammar_values.py`:

Replace

```python
        "examples": ["no more than 800 words", "maximal zwei DIN-A4-Seiten",
                     "the 500 in 300–500 words"],
```

with

```python
        "examples": ["no more than 800 words", "maximal zwei DIN-A4-Seiten",
                     "the 500 in 300–500 words", "the 3 in 'list at most three publications'"],
```

Replace

```python
    "megabytes": {"what": "Megabytes (MB) of the file's size.",
                  "examples": ["under 2MB", "The PDF file must not exceed 10 MB"]},
```

with

```python
    "megabytes": {"what": "Megabytes (MB) of the file's size.",
                  "examples": ["under 2MB", "The PDF file must not exceed 10 MB"]},
    "entries": {"what": "Items in one section of the CV: positions, publications, awards.",
                "examples": ["list at most three publications",
                             "no more than 5 work experience entries"]},
```

Replace (in `value_questions`, line 631)

```python
                if slot.document == "cv":
                    # Only the CV picks a key by it (max_chars_incl/excl_spaces);
```

with

```python
                if slot.document == "cv":
                    # Read only when the unit comes back `entries`; asked
                    # unconditionally because both are in one response.
                    questions[f"{i}:figure:{k}:section"] = Choice(
                        inspect=at, question="Which CV section does this count limit, if any?",
                        options=(*_SECTIONS, "none"),
                    )
                    # Only the CV picks a key by it (max_chars_incl/excl_spaces);
```

In `_limit_drafts` replace

```python
        spaces = answers.get(f"{i}:figure:{k}:spaces")
```

with

```python
        section = ""
        if unit.value == "entries":
            picked = answers.get(f"{i}:figure:{k}:section")
            if picked is None or picked.value == "none":
                # A count of entries in no section the CV has: shown, unapplied.
                no_sink_unit = True
                continue
            if picked.confidence < SLOT_BAR:
                doubt = picked.confidence if doubt is None else min(doubt, picked.confidence)
                continue
            section = str(picked.value)
        spaces = answers.get(f"{i}:figure:{k}:spaces")
```

and replace

```python
            figure=k, excl_spaces=excluded,
        ))
```

with

```python
            figure=k, excl_spaces=excluded, detail=section,
        ))
```

- [ ] **Step 5: The projection.** In `apps/documents/rule_sinks.py` `_bucket`, replace

```python
        side = "floor" if rule.bound == "minimum" else "cap"
        # <!-- reconciled 2026-09-26 -->
        return (rule.document, rule.operation, rule.unit, side, rule.excl_spaces)
```

with

```python
        side = "floor" if rule.bound == "minimum" else "cap"
        # A count of entries is per section: three publications and five posts
        # do not contradict each other.
        unit = f"entries:{rule.detail}" if rule.unit == "entries" else rule.unit
        # <!-- reconciled 2026-09-26 -->
        return (rule.document, rule.operation, unit, side, rule.excl_spaces)
```

and in `to_constraint_rules` replace

```python
        elif key == "max_bytes" and isinstance(rule.value, int | float):
```

with

```python
        elif key == "max_entries_per_section" and isinstance(rule.value, int | float):
            # One section per sentence figure; resolve_rules combines sections.
            value = {rule.detail: math.floor(rule.value)}
        elif key == "max_bytes" and isinstance(rule.value, int | float):
```

- [ ] **Step 6: Run and see them pass.** `uv run pytest -q tests/documents/test_grammar_types.py tests/documents/test_grammar_values.py tests/documents/test_rule_sinks_cv.py tests/documents/test_rule_sinks_letter.py tests/documents/test_derive_grammar.py` → PASS.

- [ ] **Step 7: Commit.**

```bash
git -C $W commit -m "feat(cv): a page's per-section item cap reaches max_entries_per_section (spec 8)" \
  -m "The UNITS pin gains entries on purpose." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- apps/documents/grammar.py apps/documents/grammar_values.py apps/documents/rule_sinks.py \
     tests/documents/test_grammar_types.py tests/documents/test_grammar_values.py \
     tests/documents/test_rule_sinks_cv.py
```

### Task 13: The project notes match the new merge, and the gates

**Files:**
- Modify: `.claude/rules/llm-ai-security.md` after the master merge (the bullet "**A programme rule may not lower a key's enforcement.**", in "LLM/AI security"; on master after the instructions split it lives in `.claude/rules/llm-ai-security.md:248-260`)

**Interfaces:** none.

- [ ] **Step 1: Ask the owner first.** Per `~/.config/ai_rules/rules/artifacts.md`, `CLAUDE.md` and `.claude/rules/*` change only with the owner's explicit approval. Show the owner the replacement below; if they decline, skip Steps 2-3 and say so in the PR body.

- [ ] **Step 2: Replace the bullet** with:

```markdown
- **A merged rule carries the strongest enforcement of the rules it came from.** Since
  2026-10-14 `resolve_rules` is the CV half of the requirement list
  (`apps/documents/requirement_list.py`, spec 2026-10-12 §6.4): theirs (programme page,
  FUNDER, INSTITUTION) beat ours (UNIVERSAL, TRACK, COUNTRY) even when theirs is soft;
  between theirs the stricter value wins per key; and the merged rule keeps the strongest
  enforcement of every contributor, losers included. **This is a PII boundary, not tidiness**:
  `render.py::_blocked_by_content_only_rules` inspects BINDING rules only, and every seeded
  BINDING rule is FUNDER, where "required beats not stated" keeps a page sentence from
  removing a funder's requirement. A page CAN now beat one of OUR BINDING rules on value
  (theirs beat ours); it keeps the BINDING enforcement. Before any europa.eu payload,
  `render.without_banned_content` strips the photo, date of birth and hyperlinks a ban names,
  whatever its enforcement, so a soft rule cannot let data out. Pinned by
  `tests/documents/test_catalog_rules.py` (`test_a_derived_rule_cannot_unlock_the_europass_pii_egress`,
  `test_an_advisory_programme_rule_cannot_displace_a_binding_one`) and
  `tests/documents/test_render.py::test_a_soft_page_ban_cannot_let_personal_data_reach_europa_eu`.
```

- [ ] **Step 3: Commit (only with approval).**

```bash
git -C $W commit -m "docs: the enforcement rule describes the requirement-list merge" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- .claude/rules/llm-ai-security.md
```

- [ ] **Step 4: Run every gate and keep the output.**

```bash
cd $W && uv run ruff check . \
  && uv run mypy apps config \
  && uv run python manage.py check \
  && uv run python manage.py makemigrations --check --dry-run \
  && uv run pytest -q tests/documents tests/funding
```

Expected: ruff "All checks passed!", mypy "Success", check "System check identified no issues", makemigrations "No changes detected", pytest all passed. Then `git -C $W status --short` shows nothing uncommitted.

## What later steps consume

- **4.2 (trigger, scholarship on the draft, rate limit):** `build_requirements(program, opportunity, catalog=CatalogRule.objects.order_by("rule_id"), track=resolve_track(program, content), style_rules=render._UNIVERSAL_RULES, letter_shape=shape_from_prompt(prompt) or None, document_language=prompt.document_language, competencies=<COMPETENCY ProgramStatement texts>)`; saves `RequirementList.model_dump(mode="json")` on the new `DocumentDraft.requirements` (KEEP on erasure) and per-item `state` on `requirement_states` (REDACTED); `Requirement.sentence`/`source_url` are programme data only. Reads `RequirementList.model_validate` back.
- **4.3 (questions first):** items with `ask=True` (photo, date of birth, signature, required fields), `required_fields` and `photo_required` values, `include` items (`value` = `_INCLUDE_TARGETS` field), `cv_start` `{"milestone": "upper_secondary"}` (a school-leaving entry to ask for); sets `state="waiting_for_you"`.
- **4.4 (writing to the list):** `RequirementList.for_document("cv")` typed keys/values only (never `sentence`): `include`/`order`/`emphasise` items, `max_entries_per_section`, `cv_scope`, `cv_start`, `font`; extends `render.without_banned_content` to every variant (drop the `variant == "EUROPASS_API"` condition in `render_cv_with_warnings`); switches render's directive source from `directives_from_program` to the list's directive items; owns the "no statement text reaches any writer prompt" test and "`relevant_only` cannot lower a BINDING rule".
- **4.5 (fitting and checking):** `Requirement.force` (strict/soft/info), `RequirementList.conflicts()` (step 6: two versions or the student chooses), `Requirement.state` values from `ItemState`, `cv_format` item (`force="strict"` → "handled by the official template").
- **4.6 (the page):** every item's `sentence`, `source_url`, `origin`, `force`, `state`, `conflict`; `relevance_only` items listed apart.
- **4.7 (scholarship pages and templates):** adds `FundingOpportunity.cv_constraints`/`cv_directives` and feeds them to `build_requirements` as `Contribution(rule, origin="scholarship")` and `(PageDirective, "scholarship")` pairs; the (origin, line) discard key in `merge` already separates its `PAGE-<n>` lines.
- **4.8 (translation):** sets `state="translated"`; no new list field.
- **4.9 (letter reads the list):** `RequirementList.for_document("letter")`: the five length keys (merged by the table), `LETTER_FIELD_KEYS` items, `written_requirement` (soft) and `student_action` (info) items.
- **4.10 (staying current):** a digest of `RequirementList.model_dump_json()`; `ConstraintRule.readings` lets `manage.py rederive_rules` turn pre-readings `undecided` rules from for-information into stricter readings or questions.

## Self-review

- **Spec coverage, §6.3:** typed key/value (`REQUIREMENT_KEYS`), document, origin, force, display sentence + URL, state defaulting to `pending` (Task 4); sources: programme constraints/directives/format, catalog by scope with INSTITUTION and FUNDER as theirs, code-held style rules, the letter shape for a cycle, COMPETENCY statements as relevance-only (Task 7). The scholarship's own page rules are 4.7 (§2 build order); the FUNDER catalog rows and the funder's format stand in for "scholarship" until then.
- **Spec coverage, §6.4:** step 1 (Task 6, discard by value, id tail and same line per origin; Task 2 suppresses readings at the source), step 2 (Tasks 1-3 save readings; Task 6 stricter / ask / info), step 3 (Task 6 `_merge_key`, ours keep scope order), step 4 (Task 5 table, one test per value row in Task 6), step 5 (`CONTRADICTIONS`, `FLOOR_ABOVE_CAP`, listed in code), step 6 (marker only: `Requirement.conflict`, acted on in 4.5), step 7 (`_strongest`), step 8 (Task 9 for the europa.eu path; all variants in 4.4). Every `CONSTRAINT_KEYS` key and directive action has a row, enforced by test (Task 5).
- **Spec §12 tests not in this step:** "no statement text reaches any writer prompt" is 4.4's (this step changes no writer); "the list round-trips on the draft" is 4.2's (no draft field yet; Task 4 tests the JSON round trip); "`FundingOpportunity.cv_constraints` round-trips" is 4.7's.
- **Where the code contradicts the spec or the repo notes (decided here, flagged for review):** `test_an_advisory_programme_rule_cannot_displace_a_binding_one` (test_catalog_rules.py:495) fails under "theirs beat ours" because its R-010 is UNIVERSAL, so it is rewritten too, not only the one at :533; the :533 test would still pass unchanged (its R-010 is UNIVERSAL too), so its rewrite moves R-010 to FUNDER to test what the spec says. `test_no_network_call_when_a_binding_content_rule_already_blocks` (test_render.py:1129) must be rewritten because step 8 applies the photo ban first. The project note "a hand-curated BINDING programme rule still replaces a BINDING catalog one" stops being true (Task 13 updates it). "A skipped sentence is silent" still holds: step 1 keeps a third-party or unjudged line as one for-information item (owner, 2026-10-14), and only the readings on that line are kept out of the rules. `europass.py:618-625` drops `dateOfBirth` and sends no photo today, so step 8's photo/date-of-birth strip is protection for when they are mapped; DOIs are what it changes now. derive.py:818-822 adds the `third_party` marker only when something agreed (review focus 1).
- **Assumptions an owner may overturn:** an unclear `language` or `date_of_issue_required` sentence is for-information (spec names only limits, bans and personal items); `written_requirement` is soft and `student_action` is for-information; a `format` item of `any` is for-information; a soft page rule beating one of our BINDING rules becomes strict (step 7 read literally).
- **Placeholder scan:** searched the plan for TBD, TODO, "similar to", "add validation", "handle edge cases": none. Every code step carries its code.
- **Type consistency:** `Contribution.rank` is `int` everywhere (`-1` for code-held style rules); `Requirement.value` for `order` is `[target, direction]` in both `_directive_items` and the Task 4 test; `SavedReadings.values` is `tuple[object, ...]`, dumped as a list, read back as a tuple in Tasks 1-3; `merge` returns `tuple[Requirement, ...]`, `build_requirements` returns `RequirementList`, `resolve_rules` still returns `tuple[ConstraintRule, ...]`.
- **Trial run:** the code in Tasks 1-12 was applied to a scratch copy outside both checkouts: `ruff check apps` and `mypy apps config` were clean; every pure test above passed (requirement list 10, merge 44, readers 7, render 7, cache key 1, grammar 13); across the non-database tests of the touched modules, 278 passed and the only 2 failures were the two tests this plan rewrites on purpose (`test_no_network_call...`, the `UNITS` pin). The database tests (`resolve_rules`, `program_factory`) were not run: no database was touched.
