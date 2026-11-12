# Version 2 of the settle spike: sharper questions and a third reader — 2026-10-03

Same 443 lines as `2026-10-03-settle-second-reader-language-translation.md`. Changed: eight
narrower questions, each with written true/false boundaries (money paid to the student vs costs
covered for them; nationality, level and requirement rules split out of "who may apply"; "not
available" covering abolished calls), given to the key, to Jev (as Noul `criteria`) and to DeepSeek.
Added: Gemini 3.5 Flash (reasoning low, no logprobs) as a third reader. Spend ≈ $2.4 (key $0.93,
DeepSeek ≈ $0.08, Gemini ≈ $1.3). The run stopped when the OpenRouter key reached its $10 limit
(HTTP 402); Gemini answered 363 of 443 lines, and its rows are scored on those lines only.

## Results

**Sharper questions cut key disagreement from 4.4% to 0.9%** of answers (97 of 2,215 → 32 of 3,544):
most of version 1's "missed facts" were the question's ambiguity, not the readers'.

All 443 lines, 203 true "yes" facts:

| Policy | says yes | wrong | yes-precision | yes-recall (v1) |
|---|---|---|---|---|
| Jev ≥ 0.95 | 92 | 0 | 1.000 | 45% (29%) |
| DeepSeek ≥ 0.95 | 133 | 1 | 0.992 | 65% (52%) |
| A: Jev ≥ 0.8 and DeepSeek ≥ 0.95 | 119 | 0 | 1.000 | 59% (45%) |
| B: Jev ≥ 0.5 and DeepSeek ≥ 0.95 | 128 | 1 | 0.992 | 63% (49%) |

The 363 lines all three readers answered, 155 true "yes" facts:

| Policy | says yes | wrong | yes-precision | yes-recall |
|---|---|---|---|---|
| A | 89 | 0 | 1.000 | 57% |
| B | 97 | 1 | 0.990 | 62% |
| C: A, else Jev ≥ 0.5 and DeepSeek yes and Gemini yes | 117 | 2 | 0.983 | 74% |
| D: A, else Gemini yes and (Jev ≥ 0.5 or DeepSeek yes) | 138 | 5 | 0.964 | 86% |
| Gemini alone | 148 | 10 | 0.932 | 89% |

By language under C: Azerbaijani 36/36 right, 75% kept; Turkish 50/50, 85%; Russian 16/16, 62%;
English 13/15, 59%. **Russian is where the two cheap readers fail** (A and B keep 23%); the third
reader lifts it to 62% (C) at no error. Both of C's errors are English lines.

Under C, 924 of 3,544 items (26%) are not settled by the two cheap readers and would go to the third.

## What it shows

1. **Question design is the largest lever measured so far**: written true/false boundaries took the
   two-reader policy from ~49% to ~63% of facts kept at ~99% precision, with no added cost.
2. **A third reader on the unsettled quarter adds about 12 points** (62% → 74%) at 98.3% precision in
   this run; letting it outvote a cheap reader (D) adds more but costs precision (96.4%).
3. Gemini 3.5 Flash is liberal on its own (93% precision) — useful as a confirming third vote, not as
   a sole reader. A stronger third reader was not tested (the budget ran out).
4. Still not shown: 1 wrong in 100 with confidence. 117 accepted "yes" facts with 2 errors is
   consistent with ~95–99.5%.

## Caveats

- Same pages as version 1, so question wording was tuned on the data it is scored on; plan 1 must
  tune on one half and score on the other.
- Gemini's 80 missing lines are not random (the budget ran out mid-run).
- Small per-language "yes" counts: az 48, tr 59, ru 26, en 22.
