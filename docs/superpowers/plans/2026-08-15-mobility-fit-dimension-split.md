# MOBILITY_FIT Dimension Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Retire `LOCATION` as an `EvaluationDimension` and replace it with `MOBILITY_FIT`, a dimension applied only when the student states `mobility_priorities`, with no change to the existing deterministic country hard gate.

**Architecture:** `EvaluationDimension` is a shared Literal type consumed by `StudentProfileSnapshot.weights`, `CandidateFacts.dimension_scores`, and `apps/funding/evaluation.py`'s dimension machinery. This is a rename across that shared type plus the two functions that reference the dimension name directly (`_UPSTREAM_DIMENSIONS`, `applicable_dimensions`), followed by updating every test fixture that constructs a `weights` or `dimension_scores` dict. `MOBILITY_FIT` becomes conditionally applicable, mirroring the existing `RESEARCH_FIT` pattern exactly. No model-scoring logic is added — `MOBILITY_FIT` stays an upstream-supplied placeholder value, same as the other `*_FIT` dimensions today.

**Tech Stack:** Python, Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-mobility-fit-dimension-split-design.md`

## Global Constraints

- `EvaluationDimension` no longer includes `"LOCATION"`; it includes `"MOBILITY_FIT"` in its place.
- `ProfileConstraint.kind`'s `"LOCATION"` value (a separate, unrelated free-text constraint kind) is NOT renamed and NOT removed.
- The country hard gate (`_country_preference_gate`, `HARD_GATES`) is NOT modified — country matching stays deterministic and gate-only, never a scored dimension.
- `MOBILITY_FIT` is applicable only when `profile.mobility_priorities` is non-empty (same pattern as `RESEARCH_FIT` and `profile.research_interests`).
- `StudentProfileSnapshot.schema_version` stays `Literal[2]` — do not bump it.
- `CandidateFacts.dimension_scores` continues to require exactly the six upstream dimensions (now with `MOBILITY_FIT` instead of `LOCATION`) regardless of what's applicable for any given profile — this key-set check is unconditional, same as today.

---

### Task 1: Rename `LOCATION` to `MOBILITY_FIT` in the `EvaluationDimension` type

**Files:**
- Modify: `apps/accounts/schemas.py:87-95`
- Test: `tests/accounts/test_profile_versions.py`

**Interfaces:**
- Produces: `EvaluationDimension` Literal type with `"MOBILITY_FIT"` instead of `"LOCATION"`. Task 2 and Task 3 depend on this.

- [x] **Step 1: Write the failing test**

Add to `tests/accounts/test_profile_versions.py`, after `_contracts()`. This uses the existing
`valid_phase1_profile_payload` fixture rather than constructing a full payload inline, since a
`weights` dict can only be validated as part of a complete profile:

```python
def test_weights_reject_location_and_accept_mobility_fit(
    valid_phase1_profile_payload,
) -> None:
    _, schema, _ = _contracts()

    payload = deepcopy(valid_phase1_profile_payload)
    payload["weights"] = {
        "ACADEMIC_FIT": Decimal("0.20"),
        "PROGRAM_FIT": Decimal("0.20"),
        "CAREER_FIT": Decimal("0.10"),
        "AFFORDABILITY": Decimal("0.20"),
        "DURATION": Decimal("0.10"),
        "LOCATION": Decimal("0.10"),
        "RESEARCH_FIT": Decimal("0.10"),
    }
    with pytest.raises(ValidationError):
        schema.model_validate(payload)

    payload["weights"]["MOBILITY_FIT"] = payload["weights"].pop("LOCATION")
    validated = schema.model_validate(payload)
    assert set(validated.weights) == {
        "ACADEMIC_FIT",
        "PROGRAM_FIT",
        "CAREER_FIT",
        "AFFORDABILITY",
        "DURATION",
        "MOBILITY_FIT",
        "RESEARCH_FIT",
    }
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/accounts/test_profile_versions.py::test_weights_reject_location_and_accept_mobility_fit -v`
Expected: FAIL — the second `model_validate(payload)` call (with `MOBILITY_FIT`) raises
`ValidationError` because `EvaluationDimension` does not yet accept `"MOBILITY_FIT"` as a
`weights` key.

- [x] **Step 3: Rename the Literal value**

In `apps/accounts/schemas.py`, change:

```python
EvaluationDimension = Literal[
    "ACADEMIC_FIT",
    "PROGRAM_FIT",
    "CAREER_FIT",
    "AFFORDABILITY",
    "DURATION",
    "LOCATION",
    "RESEARCH_FIT",
]
```

to:

```python
EvaluationDimension = Literal[
    "ACADEMIC_FIT",
    "PROGRAM_FIT",
    "CAREER_FIT",
    "AFFORDABILITY",
    "DURATION",
    "MOBILITY_FIT",
    "RESEARCH_FIT",
]
```

Do NOT touch `ProfileConstraint.kind` (`apps/accounts/schemas.py:83`), which also contains a
`"LOCATION"` literal value — that is a different, unrelated concept (a free-text
non-negotiable/preference constraint) and must keep `"LOCATION"` unchanged.

- [x] **Step 4: Update the existing fixture payload's weights key**

In `tests/accounts/test_profile_versions.py`, in `valid_phase1_profile_payload` (around line
76), change:

```python
            "LOCATION": "0.10",
```

to:

```python
            "MOBILITY_FIT": "0.10",
```

Leave line 69 (`"negotiable_preferences": [{"kind": "LOCATION", "value": "Urban"}]`)
unchanged — that's the unrelated `ProfileConstraint.kind` usage.

- [x] **Step 5: Run test to verify it passes**

Run: `pytest tests/accounts/test_profile_versions.py -v`
Expected: All tests PASS, including the new
`test_weights_reject_location_and_accept_mobility_fit`.

- [x] **Step 6: Commit**

```bash
git add apps/accounts/schemas.py tests/accounts/test_profile_versions.py
git commit -m "refactor: rename LOCATION to MOBILITY_FIT in EvaluationDimension"
```

---

### Task 2: Route `MOBILITY_FIT` through `_UPSTREAM_DIMENSIONS` and make it conditionally applicable

**Files:**
- Modify: `apps/funding/evaluation.py:37-39,308-320`
- Test: `tests/funding/conftest.py`

**Interfaces:**
- Consumes: `EvaluationDimension` with `"MOBILITY_FIT"` (from Task 1).
- Produces: `_UPSTREAM_DIMENSIONS` and `applicable_dimensions()` using `MOBILITY_FIT`. Task 3's
  fixture updates depend on `_UPSTREAM_DIMENSIONS` requiring `"MOBILITY_FIT"` as a
  `dimension_scores` key instead of `"LOCATION"`.

- [x] **Step 1: Write the failing test for `_UPSTREAM_DIMENSIONS`**

Add to `tests/funding/test_hard_gates.py`, after the existing imports:

```python
def test_candidate_facts_requires_mobility_fit_not_location() -> None:
    from apps.funding.evaluation import CandidateFacts

    with pytest.raises(ValidationError):
        make_candidate(
            dimension_scores={
                "ACADEMIC_FIT": Decimal("90"),
                "PROGRAM_FIT": Decimal("90"),
                "CAREER_FIT": Decimal("90"),
                "DURATION": Decimal("90"),
                "LOCATION": Decimal("90"),
                "RESEARCH_FIT": Decimal("90"),
            }
        )

    candidate = make_candidate(
        dimension_scores={
            "ACADEMIC_FIT": Decimal("90"),
            "PROGRAM_FIT": Decimal("90"),
            "CAREER_FIT": Decimal("90"),
            "DURATION": Decimal("90"),
            "MOBILITY_FIT": Decimal("90"),
            "RESEARCH_FIT": Decimal("90"),
        }
    )
    assert candidate.dimension_scores["MOBILITY_FIT"] == Decimal("90")
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/funding/test_hard_gates.py::test_candidate_facts_requires_mobility_fit_not_location -v`
Expected: FAIL — `make_candidate()`'s default `dimension_scores` (from
`tests/funding/conftest.py`'s `_BASE_DIMENSION_SCORES`, still keyed `"LOCATION"`) is used
inside the `pytest.raises` block's construction and the second `make_candidate()` call raises
because `CandidateFacts` still requires `"LOCATION"`, not `"MOBILITY_FIT"`.

- [x] **Step 3: Update `_UPSTREAM_DIMENSIONS` and `applicable_dimensions()`**

In `apps/funding/evaluation.py`, change:

```python
_UPSTREAM_DIMENSIONS: frozenset[EvaluationDimension] = frozenset(
    {"ACADEMIC_FIT", "PROGRAM_FIT", "CAREER_FIT", "DURATION", "LOCATION", "RESEARCH_FIT"}
)
```

to:

```python
_UPSTREAM_DIMENSIONS: frozenset[EvaluationDimension] = frozenset(
    {"ACADEMIC_FIT", "PROGRAM_FIT", "CAREER_FIT", "DURATION", "MOBILITY_FIT", "RESEARCH_FIT"}
)
```

Then change `applicable_dimensions()`:

```python
def applicable_dimensions(profile: StudentProfileSnapshot) -> frozenset[EvaluationDimension]:
    dimensions: set[EvaluationDimension] = {
        "ACADEMIC_FIT",
        "PROGRAM_FIT",
        "CAREER_FIT",
        "AFFORDABILITY",
        "LOCATION",
    }
    if profile.duration_preference != "NONE":
        dimensions.add("DURATION")
    if profile.research_interests:
        dimensions.add("RESEARCH_FIT")
    return frozenset(dimensions)
```

to:

```python
def applicable_dimensions(profile: StudentProfileSnapshot) -> frozenset[EvaluationDimension]:
    dimensions: set[EvaluationDimension] = {
        "ACADEMIC_FIT",
        "PROGRAM_FIT",
        "CAREER_FIT",
        "AFFORDABILITY",
    }
    if profile.duration_preference != "NONE":
        dimensions.add("DURATION")
    if profile.research_interests:
        dimensions.add("RESEARCH_FIT")
    if profile.mobility_priorities:
        dimensions.add("MOBILITY_FIT")
    return frozenset(dimensions)
```

Do NOT modify `_country_preference_gate`, `HARD_GATES`, or `_constraint_satisfied`'s
`"LOCATION"` branch (line 203) — those are unrelated to this dimension rename.

- [x] **Step 4: Update `tests/funding/conftest.py`'s base dicts**

In `tests/funding/conftest.py`, change `_BASE_DIMENSION_SCORES`:

```python
_BASE_DIMENSION_SCORES = {
    "ACADEMIC_FIT": Decimal("90"),
    "PROGRAM_FIT": Decimal("90"),
    "CAREER_FIT": Decimal("90"),
    "DURATION": Decimal("90"),
    "LOCATION": Decimal("90"),
    "RESEARCH_FIT": Decimal("90"),
}
```

to:

```python
_BASE_DIMENSION_SCORES = {
    "ACADEMIC_FIT": Decimal("90"),
    "PROGRAM_FIT": Decimal("90"),
    "CAREER_FIT": Decimal("90"),
    "DURATION": Decimal("90"),
    "MOBILITY_FIT": Decimal("90"),
    "RESEARCH_FIT": Decimal("90"),
}
```

And `_BASE_WEIGHTS`:

```python
_BASE_WEIGHTS = {
    "ACADEMIC_FIT": Decimal("0.2"),
    "PROGRAM_FIT": Decimal("0.2"),
    "CAREER_FIT": Decimal("0.1"),
    "AFFORDABILITY": Decimal("0.2"),
    "DURATION": Decimal("0.1"),
    "LOCATION": Decimal("0.1"),
    "RESEARCH_FIT": Decimal("0.1"),
}
```

to:

```python
_BASE_WEIGHTS = {
    "ACADEMIC_FIT": Decimal("0.2"),
    "PROGRAM_FIT": Decimal("0.2"),
    "CAREER_FIT": Decimal("0.1"),
    "AFFORDABILITY": Decimal("0.2"),
    "DURATION": Decimal("0.1"),
    "MOBILITY_FIT": Decimal("0.1"),
    "RESEARCH_FIT": Decimal("0.1"),
}
```

`make_profile()`'s default `mobility_priorities` is already `()` (empty tuple, line 77 of
`tests/funding/conftest.py`) — leave it as-is. This means `MOBILITY_FIT` is present in the
default `weights` dict but not applicable by default (mirrors `RESEARCH_FIT`'s existing
behavior with `research_interests=()`), so `redistribute_weights` silently excludes it via its
existing `weights.get(dim, Decimal("0"))` lookup over only the applicable set — no new code
needed for that.

- [x] **Step 5: Run test to verify it passes**

Run: `pytest tests/funding/test_hard_gates.py -v`
Expected: All tests PASS, including the new
`test_candidate_facts_requires_mobility_fit_not_location`.

- [x] **Step 6: Add a test for conditional applicability**

Add to `tests/funding/test_ranking.py`, after
`test_research_fit_dimension_is_excluded_and_redistributed_without_research_interests`:

```python
def test_mobility_fit_dimension_is_included_only_with_mobility_priorities() -> None:
    profile_without = make_profile(strategy="BALANCED", mobility_priorities=())
    profile_with = make_profile(strategy="BALANCED", mobility_priorities=("Public transport",))
    candidate = make_candidate(cost_components=())

    ranked_without = rank_candidates(profile_without, [candidate], EUR_RATES)
    ranked_with = rank_candidates(profile_with, [candidate], EUR_RATES)

    assert ranked_without[0].scores is not None
    assert "MOBILITY_FIT" not in {score.dimension for score in ranked_without[0].scores.dimensions}
    assert ranked_with[0].scores is not None
    assert "MOBILITY_FIT" in {score.dimension for score in ranked_with[0].scores.dimensions}
```

- [x] **Step 7: Run test to verify it passes**

Run: `pytest tests/funding/test_ranking.py::test_mobility_fit_dimension_is_included_only_with_mobility_priorities -v`
Expected: PASS.

- [x] **Step 8: Commit**

```bash
git add apps/funding/evaluation.py tests/funding/conftest.py tests/funding/test_ranking.py tests/funding/test_hard_gates.py
git commit -m "feat: make MOBILITY_FIT applicable only with stated mobility_priorities"
```

---

### Task 3: Rename remaining `LOCATION` dimension-score fixtures across the funding test suite

**Files:**
- Modify: `tests/funding/test_ranking.py:7-32`
- Modify: `tests/funding/test_hard_gates.py:159-194`

**Interfaces:**
- Consumes: `MOBILITY_FIT` as a required `dimension_scores` key (from Task 2). No new
  interfaces produced — this task only updates remaining fixture literals so the full suite
  passes.

- [x] **Step 1: Run the full funding test suite to find remaining failures**

Run: `pytest tests/funding/ -v`
Expected: FAIL — `tests/funding/test_ranking.py`'s `_STRONG_SCORES`, `_WEAK_SCORES`, and
`_MODEST_SCORES` module-level dicts, and `tests/funding/test_hard_gates.py`'s two inline
`dimension_scores` dicts (lines ~163-170 and ~180-187), still use `"LOCATION"` as a
`dimension_scores` key. `CandidateFacts` validation now requires `"MOBILITY_FIT"` instead,
so every test using these dicts fails with a `ValidationError`.

- [x] **Step 2: Rename `LOCATION` in `tests/funding/test_ranking.py`**

Change all three module-level dicts:

```python
_STRONG_SCORES = {
    "ACADEMIC_FIT": Decimal("95"),
    "PROGRAM_FIT": Decimal("95"),
    "CAREER_FIT": Decimal("95"),
    "DURATION": Decimal("95"),
    "LOCATION": Decimal("95"),
    "RESEARCH_FIT": Decimal("95"),
}
_WEAK_SCORES = {
    "ACADEMIC_FIT": Decimal("65"),
    "PROGRAM_FIT": Decimal("65"),
    "CAREER_FIT": Decimal("65"),
    "DURATION": Decimal("65"),
    "LOCATION": Decimal("65"),
    "RESEARCH_FIT": Decimal("65"),
}
_MODEST_SCORES = {
    "ACADEMIC_FIT": Decimal("85"),
    "PROGRAM_FIT": Decimal("85"),
    "CAREER_FIT": Decimal("85"),
    "DURATION": Decimal("85"),
    "LOCATION": Decimal("85"),
    "RESEARCH_FIT": Decimal("85"),
}
```

to:

```python
_STRONG_SCORES = {
    "ACADEMIC_FIT": Decimal("95"),
    "PROGRAM_FIT": Decimal("95"),
    "CAREER_FIT": Decimal("95"),
    "DURATION": Decimal("95"),
    "MOBILITY_FIT": Decimal("95"),
    "RESEARCH_FIT": Decimal("95"),
}
_WEAK_SCORES = {
    "ACADEMIC_FIT": Decimal("65"),
    "PROGRAM_FIT": Decimal("65"),
    "CAREER_FIT": Decimal("65"),
    "DURATION": Decimal("65"),
    "MOBILITY_FIT": Decimal("65"),
    "RESEARCH_FIT": Decimal("65"),
}
_MODEST_SCORES = {
    "ACADEMIC_FIT": Decimal("85"),
    "PROGRAM_FIT": Decimal("85"),
    "CAREER_FIT": Decimal("85"),
    "DURATION": Decimal("85"),
    "MOBILITY_FIT": Decimal("85"),
    "RESEARCH_FIT": Decimal("85"),
}
```

- [x] **Step 3: Rename `LOCATION` in `tests/funding/test_hard_gates.py`**

In `test_balanced_possibly_eligible_when_overall_below_eighty`, change:

```python
dimension_scores = (
    {
        "ACADEMIC_FIT": Decimal("50"),
        "PROGRAM_FIT": Decimal("50"),
        "CAREER_FIT": Decimal("50"),
        "DURATION": Decimal("50"),
        "LOCATION": Decimal("50"),
        "RESEARCH_FIT": Decimal("50"),
    },
)
```

to:

```python
dimension_scores = (
    {
        "ACADEMIC_FIT": Decimal("50"),
        "PROGRAM_FIT": Decimal("50"),
        "CAREER_FIT": Decimal("50"),
        "DURATION": Decimal("50"),
        "MOBILITY_FIT": Decimal("50"),
        "RESEARCH_FIT": Decimal("50"),
    },
)
```

In `test_balanced_possibly_eligible_when_a_critical_dimension_is_below_sixty`, change:

```python
    dimension_scores = {
        "ACADEMIC_FIT": Decimal("30"),
        "PROGRAM_FIT": Decimal("100"),
        "CAREER_FIT": Decimal("100"),
        "DURATION": Decimal("100"),
        "LOCATION": Decimal("100"),
        "RESEARCH_FIT": Decimal("100"),
    }
```

to:

```python
    dimension_scores = {
        "ACADEMIC_FIT": Decimal("30"),
        "PROGRAM_FIT": Decimal("100"),
        "CAREER_FIT": Decimal("100"),
        "DURATION": Decimal("100"),
        "MOBILITY_FIT": Decimal("100"),
        "RESEARCH_FIT": Decimal("100"),
    }
```

Leave `tests/funding/test_hard_gates.py:82,92` (`make_constraint("LOCATION", ...)`)
unchanged — those exercise the unrelated `ProfileConstraint.kind` non-negotiable-location
gate, not the `EvaluationDimension`.

- [x] **Step 4: Run the full funding and accounts test suites**

Run: `pytest tests/funding/ tests/accounts/ -v`
Expected: All tests PASS. This confirms no remaining `"LOCATION"`-keyed `dimension_scores` or
`weights` dict anywhere in the funding/accounts suites, and that the unrelated
`ProfileConstraint` `"LOCATION"` usages still work unchanged.

- [x] **Step 5: Grep for any remaining stray reference**

Run: `grep -rn '"LOCATION"' apps tests --include=*.py`
Expected output: only `apps/accounts/schemas.py:83` (`ProfileConstraint.kind` Literal),
`apps/funding/evaluation.py:203` (`_constraint_satisfied`'s `"LOCATION"` branch),
`tests/funding/test_hard_gates.py:82,92` (`make_constraint("LOCATION", ...)`), and
`tests/accounts/test_profile_versions.py:69` (`negotiable_preferences` payload). If anything
else appears, it was missed by this plan — stop and report it rather than editing it without
checking whether it's the `ProfileConstraint` or `EvaluationDimension` sense of "LOCATION".

- [x] **Step 6: Commit**

```bash
git add tests/funding/test_ranking.py tests/funding/test_hard_gates.py
git commit -m "test: rename remaining LOCATION dimension-score fixtures to MOBILITY_FIT"
```

---

### Task 4: Run the full test suite as a final checkpoint

**Files:**
- None modified — verification only.

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing — this task is a checkpoint, not a deliverable.

- [x] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: All tests PASS. This confirms no other module (e.g. `apps/funding/pack.py`,
`apps/funding/explanations.py`) depended on `"LOCATION"` as an `EvaluationDimension` value.

- [x] **Step 2: If anything fails, stop and report**

Do not patch a failure by re-adding `"LOCATION"` as an accepted `EvaluationDimension` value —
that would silently reintroduce the two-meanings ambiguity this plan removes. If a failure
points to an untouched consumer of the dimension name, report it; it means this plan's file
list was incomplete.
