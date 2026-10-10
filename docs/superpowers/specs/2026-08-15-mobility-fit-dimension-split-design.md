# MOBILITY_FIT Dimension Split — Design

Status: draft, pending review
Date: 2026-08-15
Related: [LLM-Scored Recommendations](2026-08-14-llm-scored-recommendations-design.md) (see `## Open` → "`LOCATION` is split-natured — RESOLVED")

## Decision

`LOCATION` is retired as an `EvaluationDimension`. Country matching stays exactly as it is
today — a deterministic hard gate, not a scored dimension. A new dimension, `MOBILITY_FIT`,
replaces it as the upstream-supplied slot for judging the student's `mobility_priorities`
free text against a program.

This is a data-contract rename, not new scoring logic. No dimension in this codebase
currently calls a model — `ACADEMIC_FIT`, `PROGRAM_FIT`, `CAREER_FIT`, and `RESEARCH_FIT`
are all still placeholder values supplied via `CandidateFacts.dimension_scores`, pending the
LLM-scoring pipeline described in the related spec. `MOBILITY_FIT` follows the identical
pattern; building the actual model call is separate, larger work affecting all `*_FIT`
dimensions together, not scoped here.

## Why country doesn't become a scored dimension

`_country_preference_gate` (`apps/funding/evaluation.py:230-238`) already fully excludes any
candidate outside `allowed_countries` or inside `excluded_countries`, before scoring ever
runs. Every candidate that reaches `score_dimensions` has already passed this check. Adding a
second, *scored* representation of the same binary fact would be redundant — there is no
graduated signal left to weight once the gate has run.

## Changes

**`apps/accounts/schemas.py:87-95`** — `EvaluationDimension` Literal: `"LOCATION"` →
`"MOBILITY_FIT"`.

`ProfileConstraint.kind` (`apps/accounts/schemas.py:83`) also contains a `"LOCATION"` value,
for free-text non-negotiable/preference constraints (e.g. "Paris", "Urban"), consumed by
`_constraint_satisfied` (`apps/funding/evaluation.py:203`). This is an unrelated concept and
is untouched by this change.

**`apps/funding/evaluation.py`**
- `_UPSTREAM_DIMENSIONS` (line 38): `LOCATION` → `MOBILITY_FIT`. `CandidateFacts.dimension_scores`
  continues to require this key unconditionally — upstream-supplied, same as `RESEARCH_FIT`,
  regardless of whether it ends up applicable for a given profile.
- `applicable_dimensions()` (lines 308-320): move `MOBILITY_FIT` out of the always-on base
  set. Add it conditionally, mirroring the existing `RESEARCH_FIT` pattern:
  ```python
  if profile.mobility_priorities:
      dimensions.add("MOBILITY_FIT")
  ```
- `_country_preference_gate` and `HARD_GATES`: unchanged.

**Tests** — mechanical rename of the `EvaluationDimension` key (`"LOCATION"` →
`"MOBILITY_FIT"`) in `weights`/`dimension_scores` dicts only:
- `tests/funding/conftest.py`
- `tests/funding/test_ranking.py`
- `tests/funding/test_hard_gates.py` (lines 168, 185 — dimension_scores/weights dicts; lines
  82, 92 use the unrelated `ProfileConstraint` `"LOCATION"` and stay as-is)
- `tests/accounts/test_profile_versions.py:76` (weights dict; line 69's `ProfileConstraint`
  `"LOCATION"` stays as-is)

## Schema versioning

`StudentProfileSnapshot.schema_version` (`Literal[2]`) is not bumped. It is a tag field with
no version-dispatch logic anywhere in this codebase; renaming the `weights` dict's accepted
key is a breaking wire-format change either way (old `"LOCATION"` weight now fails Pydantic
validation instead of being silently ignored), and there is no migration machinery to plug a
version bump into. This matches how every other Literal addition/removal in this Phase-1
codebase has been handled — no per-field version gating precedent exists.

## Out of scope

- Building the actual LLM-scoring pipeline (model call, level-to-score mapping, citation
  verification) for `MOBILITY_FIT` or any other `*_FIT` dimension.
- Any change to the country hard gate, `ProfileConstraint`, or the other three residual items
  tracked in the multi-currency money design spec.
