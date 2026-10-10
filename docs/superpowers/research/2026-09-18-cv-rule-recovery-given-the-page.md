# Given the page that states the rule, do we derive it? 8 of 15

Measured 2026-09-18. The corpus baseline (0.00 on every metric, 2026-09-16) scores the whole
pipeline from each programme's seed URL, so it measures **discovery**. This measures the other
half: hand `read_and_derive` the exact URL a human found the rule on and compare what the engine
writes against the adjudicated answer key in `docs/research/cv-corpus-rules.csv`.

Twelve programmes, one page each, real model calls (`gpt-5.6-luna` x2 + `claude-sonnet-5`),
24 minutes. Throwaway runner, not committed.

## Result

**8 of 15 labelled rules recovered. Nothing was derived wrong** — every extra was an `undecided`
row, which is a sentence shown to a human, not a claim about the page.

| programme | labelled | got |
|---|---|---|
| amir | `europass_required` | OK |
| mathmods | `europass_required` | OK |
| we-team | `europass_required` | OK |
| europubhealth | `europass_preferred` | OK |
| emhrpp | `any` | OK |
| emjm-imaging | `max_pages=2` | OK |
| eiffel-paris-saclay | `max_pages=2` | OK |
| fulbright-nepal | `max_pages=2` | OK |
| membiomed | `europass_required`, `include(personal.date_of_birth)`, `unapplied(cv)` | **crash**, see below |
| globed | `europass_required` | fetch refused, HTTP 403 |
| i-mesc | `europass_required` | `UNDECIDED` — the readings disagreed on "Please use the Europass model." |
| sisgp | `funder_template`, `max_pages=3` | `funder_template` is never derived by design; `max_pages` abstained |

Four causes, and only the first is ours:

1. **A crash** (membiomed) — fixed, below.
2. **A host that refuses this address** (globed). The corpus row exists because a vendor fetched it.
3. **Abstention** (i-mesc, sisgp `max_pages`). The unanimity bar working as designed, costing recall.
4. **A known architectural gap** (`funder_template` needs a template module; CLAUDE.md records why
   deriving it would route every uncurated funder to `UnsupportedRenderVariant`).

## The crash: a reader block is not a sentence

`candidates()` returned **two** candidates for MEMBIOMED's how-to-apply page, and the longer was
**1,935 characters** — a whole document checklist inside one `<p>`. Both quote stores cap at 1,000
(`ConstraintRule.rule_text`, `PageDirective.rule_text`), so building the rule raised
`ValidationError` out of `derive_page_rules`; `read_and_derive` holds one transaction, so it took
the statement write with it. Three labelled rules lost, and not silently — but as an exception
rather than a recorded state.

Worse than the derivation half: `PageDirective` is re-validated on **read**
(`directives_from_program`), which `generation.py` and `gaps.py` call. An over-long quote written
before this would have been a poison row breaking CV generation, not just derivation.

**Fixed by clipping with a marker** (`derive._quote`, `constraints.QUOTE_MAX_CHARS`), not by
splitting blocks into sentences. Splitting changes what the judge is asked about on every page —
a measured surface (the 48-row gate, this corpus) — and needs a splitter that works in every
language the catalog reads. Clipping keeps the rule, keeps the bound on text a third-party page
controls, and says it was cut.

Re-measured after the fix: the page derives `europass_required` (the BINDING rule) and abstains on
the other two. **7 of 15 becomes 8 of 15** with one line of the answer key still open per below.

## The same root cause, second consequence — not fixed

That 1,935-character block contains both the CV requirement and the words "Reference letters", so
`derive._THIRD_PARTY` matches **the whole block** and withholds everything derived from it —
including `include(personal.date_of_birth)`, which is about the applicant. The guard is right about
the paragraph and wrong about the sentence.

The format rule survived only because the statement read supplies sentence-level candidates
alongside the page-line scan, and "CV : Europass format mandatory." arrived as its own candidate.
Where the statement read misses a sentence, the block-level candidate is all there is, and one
mention of a referee anywhere in the paragraph withholds it.

So sentence splitting is worth doing on its own merits — as attribution granularity, measured
against the 48-row gate, not as a fix for the length cap.
