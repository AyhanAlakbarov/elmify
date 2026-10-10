# The held-out acceptance country: KOREA

Sealed 2026-09-22, **before** any rule, prompt or term row was edited in response to it.
Task 12, step 3 of `2026-09-19-letter-shape-tailoring`.

## Why this exists

Every per-language number the eval sheet produces (`docs/research/letter-shape-eval.csv`,
run by `tests/documents/test_letter_derive.py::test_the_judge_reads_every_language_in_the_eval_sheet`)
is a **development score**. The sheet was built from the same `M-` catalog the engine's
defaults, terms and phrasings were built from, so a good score on it says the engine
agrees with itself.

This file names one country whose pages nothing in this branch has read, in a script the
eval sheet does not train on. It is read **once**, at the end, by a human, against the real
pages. That number is the acceptance score, and it is the only one that answers "does this
work on a programme nobody prepared for".

## The country, and why it is the honest choice

**Korea.** Three properties, each of which the sheet lacks:

- **Script.** The eval sheet holds `en`, `de`, `fr`, `es`, `pt` and one `zh` row. No Hangul
  appears in it, and `letter_terms.csv` gives `ko` an entirely character-based unit
  vocabulary — so the length arithmetic's Latin-script exemptions (`counts_characters`) are
  exercised here for the first time against a real page.
- **Convention.** The Korean shape is two documents (학업계획서, a study plan, and
  자기소개서, a self-introduction), not one letter. Nothing in the engine's defaults table
  is keyed to Korea, so `COUNTRY_SYSTEM` resolves it by fallback — which is exactly the
  "a page the research never saw" case §10 says the design must survive.
- **A measure the schema cannot type.** The one Korean rule the catalog already holds
  (M-080, SNU Dream Together Master) states a **3000-byte** cap. `LetterVerdict` has
  `words`, `characters` and `pages` and no bytes, and the eval sheet carries that sentence
  as an `expected_field=none` row precisely because nobody has decided what it should do.
  Korea is where that decision gets made against a real page rather than in the abstract.

**M-080's own page is excluded from the acceptance set**, because the catalog already
carries it and the sheet quotes it. The acceptance read must be pages this branch has not
seen.

## The pages

Checked 2026-09-22: each returned HTTP 200 to a plain `curl -L`. Deeper document-requirement
paths under these hosts were not fixed in advance on purpose — a human follows each entry
point to the graduate-admissions document list for the intake current at acceptance time,
because these paths are re-cut every cycle and a 404 in this file would be worse than a
starting point.

| # | Institution | Entry point |
|---|---|---|
| 1 | KAIST, international graduate admissions | https://admission.kaist.ac.kr/intl-graduate/ |
| 2 | Yonsei University, admissions | https://admission.yonsei.ac.kr/ |
| 3 | Seoul National University, Office of International Affairs | https://oia.snu.ac.kr/ |

Re-checked 2026-09-23, before any acceptance read: all three still answer 200. KAIST's
document list is one hop in, at `/intl-graduate/Admission` (its own "Eligibility
Requirements" page hangs off that). Yonsei's index returns no links to a plain client -- its
admissions navigation is rendered client-side, so that page is the browser tier's to fetch,
and the acceptance read must record it as such rather than as a page stating nothing. SNU's
graduate document list was not reachable from the OIA entry point in one hop; `admission.snu.ac.kr`
is the portal to follow.

## How it is read, once

1. Fetch each programme's own application-documents page and archive it, exactly as
   `read_program_page` would.
2. Run the shape derivation over it (`derive_page_rules` → `decide_letter_shape`).
3. A **human** compares the derived `LetterShape` field by field against the page, and
   records three numbers per page: fields derived correctly, fields missed, fields derived
   **wrongly**.

**The bar, fixed here and not afterwards:** zero wrongly-derived caps and zero missed
`naming=FORBIDDEN` across the three pages. A miss is a coverage result and is reported; a
wrong cap is a failure of the acceptance run.

## What may not happen

Nothing in this file may be edited in response to a bad acceptance result. If the engine
reads Korea badly, the finding is recorded, the fix is made, and the acceptance is re-run
on a **different** held-out country — Japan, Saudi Arabia and Russia are the remaining
candidates, and each is unread by this branch for the same reasons Korea was.
