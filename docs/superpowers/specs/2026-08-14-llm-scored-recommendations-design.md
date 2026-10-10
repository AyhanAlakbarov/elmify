# LLM-Scored Recommendations — Design

Status: draft, pending review
Date: 2026-08-14
Related: [Multi-Currency Money Handling](2026-08-14-multi-currency-money-design.md)

## Decision

A reasoning model supplies the qualitative dimension judgements. Deterministic code owns
everything else. This was taken to the LLM Council on 2026-08-14 (conversation
`9a1c627a`); four models were unanimous, and Option D — a model producing a holistic score
or ranking directly — was rejected outright.

`phased requirements.md` §3.3 was amended on 2026-08-14 to state this boundary explicitly
rather than leaving it to engineering interpretation.

## The boundary

The operational test: **if the model is removed and replaced with the persisted score
records, the entire arithmetic path must execute identically.**

Deterministic code owns:

- The 8 eligibility gates, run before any model call, at zero model cost.
- `AFFORDABILITY` and `DURATION`, computed with `Decimal` over structured facts.
- Weight validation and redistribution (`redistribute_weights`, must sum to exactly 1).
- The mapping from rubric level to integer score.
- The weighted sum, the 80/60 threshold comparisons, tie-breaking, and final ordering.

The model owns:

- Bounded, schema-constrained, citation-backed judgements on `ACADEMIC_FIT`,
  `PROGRAM_FIT`, `CAREER_FIT`, `RESEARCH_FIT`.

## The model emits levels, not numbers

The model must **not** emit a scalar. It emits an anchored ordinal level per dimension,
plus a verbatim cited excerpt and a short rationale:

| Level | Mapped score |
| --- | --- |
| `NO_EVIDENCE` | 0 |
| `WEAK` | 40 |
| `ADEQUATE` | 60 |
| `STRONG` | 80 |
| `EXCEPTIONAL` | 100 |

Versioned deterministic code performs the mapping. Rationale:

- A model cannot reliably distinguish 83.7 from 81.2 on the same program. Emitting a scalar
  manufactures precision that does not exist.
- Calibration drift across model versions becomes a discrete, testable event (a level
  changed) rather than a distribution shift.
- The model stays structurally outside the arithmetic layer.

`NO_EVIDENCE` is a required, first-class outcome. A model that confabulates a middling score
for a page containing no relevant evidence is the most dangerous failure mode, because a
plausible-looking 60 passes human review unchallenged.

## Citation verification

Every cited excerpt returned by the model must exist verbatim in the hashed source text.
Verification is a string match; on failure the entire payload is rejected and the candidate
is routed to consultant review.

This eliminates hallucinated citations and a large class of prompt injection with one
mechanical check. `ExtractedClaims` in `apps/research/extraction.py` already carries
`supporting_excerpt_offsets`, so the machinery exists and should be reused rather than
rebuilt.

## Cost control: ceiling prune, not top-K

A naive top-K prefilter — rank survivors by the deterministic dimensions, model-score only
the top K — is unsound. Because ranking uses per-student weights, it silently discards
programs that are excellent academic or career matches merely because they are average on
affordability, and it does this most aggressively to the students who weighted affordability
lowest.

Replace it with an admissible optimistic bound:

1. Compute the deterministic dimensions for every survivor of the 8 hard gates.
2. Compute each survivor's **score ceiling**: its actual deterministic contributions plus,
   for each unscored qualitative dimension, `weight × 100`.
3. **Lossless prune.** Drop any candidate whose ceiling is `< 80`, or whose actual
   deterministic score on a critical dimension is `< 60`. These cannot pass the thresholds
   regardless of what the model returns.
4. **Lossy prune, only if volume demands it.** Sort the remainder by ceiling descending and
   apply a budget cap `K`. When `K` truncates, persist a `truncated_at_k` marker recording
   the ceiling of the highest unscored candidate, and surface it to the consultant.

### The prune is gated on strategy

**The lossless prune is valid for `BALANCED` only.** `apps/funding/pack.py:71` orders
`FUNDING_FIRST` by `(gap, -overall)` and never applies the 80/60 thresholds:

```python
if profile.strategy == "FUNDING_FIRST":
    ordered = sorted(evaluated, key=lambda item: (item[2].gap, -item[1].overall))
```

Under `FUNDING_FIRST` a candidate with a ceiling of 55 can legitimately rank first if its
funding gap is smallest. Pruning on the 80 ceiling would delete the top result for exactly
the students who most depend on funding. Under `FUNDING_FIRST`, apply only the hard gates
and the budget cap — never the threshold-derived prune.

## Reproducibility by persistence, not by determinism

A pinned model name and `temperature=0` do **not** guarantee identical outputs on hosted
APIs. The reproducibility constraint is satisfied by immutable persistence: an unchanged
re-run reads records, it does not resample the model.

Cache key: `(profile_version, program_facts_hash, rubric_version, prompt_version, model_version)`.

A fit judgement is inherently pairwise (student × program), so records share nothing across
students. Caching helps re-runs for one student; it does not reduce first-run cost. Cost is
bounded by the ceiling prune, not by the cache.

### Expert freeze and override provenance

Once a consultant confirms a score it becomes an immutable, append-only record that outlives
its cache key. Consultant-corrected records carry a distinct provenance tag and are
invalidated by changes to the student profile or the program facts, but **not** by a model
version bump. A human judgement does not go stale because the model was upgraded.

## Calibration

The system uses fixed absolute thresholds (`overall >= 80`, critical `>= 60`), which makes it
sensitive to level drift: a new model version scoring uniformly harsher or looser changes
outcomes even when relative ordering is unchanged.

Pre-launch evidence required:

- **Human ceiling first.** Establish inter-rater agreement between two consultants on a gold
  set. The model is not held to a standard humans do not meet.
- **Threshold-flip rate, not mean error.** Measure how often the model's judgement changes
  the outcome across the 80/60 cutoffs relative to human consensus. Absolute score error is
  the wrong metric.
- **Abstention testing.** Pages with no relevant evidence must yield `NO_EVIDENCE`.

A model version bump requires a blocking regression run against the gold set before
promotion. Do not upgrade models during an active application cycle.

## Rollback

Track the **rank-changing override rate**: consultant overrides that move a candidate across
an 80/60 threshold. Overrides that only reword a rationale are noise and must not be counted.

If that rate crosses a limit registered before the first cohort ships, revert the failing
dimension to a deterministic fallback. The reversal is per-dimension, not all-or-nothing.

## Adversarial containment

- Untrusted-data framing in the developer message, per the established pattern at
  `apps/research/extraction.py:166`.
- One isolated call per candidate; blast radius is a single candidate.
- Strict output schema; no free-form text enters the arithmetic.
- Verbatim citation verification (above).
- **Shadow scorer.** A cheap keyword/taxonomy scorer runs in the background as a divergence
  detector, not as a ranking input. When the model scores a program highly on a dimension
  the keyword scorer scores at zero, flag it for consultant scrutiny. This is the tripwire
  against adversarial marketing copy.

Injection can move a qualitative judgement. It cannot fabricate eligibility or money, which
are gates and arithmetic.

## Student-facing presentation

- **Overall score: a number.** It is real arithmetic over the student's own stated weights.
- **Qualitative dimensions: the level plus the cited excerpt, not a number.** "Career fit:
  STRONG — *[quoted sentence about the industry placement track]*" is defensible under
  challenge; "career fit: 83.7" is not.
- **Money and duration: numbers**, in the currencies defined by the currency design.

Exact ties in `overall` remain rare despite the coarse levels, because `_affordability_score`
(`apps/funding/evaluation.py:285`) is continuous and feeds the weighted sum.

Consequence for the review UI: because levels map to discrete scores, a consultant override
moves the student-visible overall score in a visible step. The review surface must show the
resulting score change before the override is committed.

## Open

- **`LOCATION` is split-natured — RESOLVED.** Split into two dimensions. Country matching
  against `allowed_countries` / `excluded_countries` stays deterministic; `mobility_priorities`
  free text (`tuple[NonBlankText200, ...]`) is scored as its own LLM-judged dimension. Each
  half is scored by the mechanism suited to it instead of forcing one dimension through a
  single method.
- Tie-breaking beyond `-overall` is unspecified; `pack.py` currently breaks a tie on the
  value that just tied.
- Consultant review surface and P1-11 escalation behaviour are not covered here.
