# CV extraction, measured on nine documents

Run 2026-08-31 against `OPENAI_EXTRACTION_MODEL` (`gpt-5.6-luna`) on the
`claude/cv-engine-finish` branch. 63 model calls.

The earlier note (`2026-08-30-extraction-non-determinism.md`) measured **one**
CV and concluded the problem was drift in `ingestion._extract_claims`. That is
true and it is not the biggest problem. On a corpus of nine, most uploads do
not survive validation at all.

## Method

**Corpus.** Six academic CVs published by UPenn Career Services as samples
(cancer biology, chemistry, communication, economics, electrical engineering,
human development), two Harvard College résumé examples, and this repo's own
`tests/documents/fixtures/europass_api.pdf` as a near-empty edge case.
UPenn redacts the person to the literal strings `NAME`, `ADDRESS`, `PHONE`, so
the corpus carries no living person's contact details -- deliberate: a folder of
strangers' PII is not an acceptable price for a test corpus, and these are real
documents in real formats regardless. The PDFs are **not committed**; the fetch
URLs are in this file's history and the harness took them from
`careerservices.upenn.edu` and `careerservices.fas.harvard.edu`.

**Harness.** `extract_text` once per document (deterministic, pypdf), then
`_extract_claims` three times off that one frozen string. Entries matched
across runs by the identity keys `verification._CategorySpec` already
defines -- institution+degree, employer+title, thesis title, publication
title. Two configurations: the model's default, and `reasoning={"effort":
"high"}`.

**What this measures and what it does not.** Validity (does the output satisfy
`CVContent`), stability (do repeat runs agree), and a groundedness proxy (does
an extracted string appear anywhere in the source text). It does **not**
measure accuracy: no answer key was written, so "the extractor read this CV
correctly" is unproven. That is the next measurement, and it is second in line
because a document that yields nothing has no accuracy to assess.

## Result 1 -- 59% of runs produce nothing

| Document | usable (default) | usable (high effort) |
| --- | --- | --- |
| CV-cancer-bio | **0/3** | **0/3** |
| CV-chemistry | 2/3 | 2/3 |
| CV-communication | **0/3** | 1/3 |
| CV-economics | 1/3 | 1/3 |
| CV-electrical-engineering | 2/3 | 2/3 |
| CV-human-development | 3/3 | 1/3 |
| Harvard-CS résumé | 1/3 | 2/3 |
| Harvard-Eng résumé | 2/3 | 2/3 |
| Europass fixture | **0/3** | 2/3 |
| **total** | **11/27 (41%)** | **13/27 (48%)** |

A failed run is not a degraded run. `_extract_claims` returns nothing, so the
upload writes **zero facts** and the student sees an empty ledger.

## Result 2 -- one required field causes most of it

Counting the first validation error of each failure (the harness truncates the
message, so this undercounts multi-error failures):

| Cause | default | high effort |
| --- | --- | --- |
| `country` is not an ISO 3166-1 code | 9 | 8 |
| a required string arrived empty | 1 | 3 |
| date outside 1900-2100 | 0 | 3 |

The rejected country codes: `NY`, `CT`, `MA` (US states), `UK` (the common
non-code; ISO says `GB`), and `UQ`, `TQ`, `EJ`, `AA`, `HQ`, `PZ` (nothing at
all).

The cause is structural, not a prompt failure. A US academic CV prints
"Philadelphia, PA" and never names a country, because every reader knows it.
`EducationEntry.country` and `.city` are **required**, so the model must emit
something, and it does. `CountryCode` then correctly refuses the invention and
takes the entire document down with it.

This is the defect the research side already diagnosed and wrote down in
`2026-08-30-claims-merge-and-money-evidence-design.md`: *a required field with
no "not applicable" makes the model invent a value.* `MoneyClaim.currency` was
the same bug. Nobody had connected it to the CV schema.

## Result 3 -- reasoning effort is not the lever

52% failures against 59%, inside the noise of N=27. Worse, high effort
produced the impossible dates the default run did not: `0200-01-01`,
`0527-01-01`, `0820-01-01` -- the same garbled-token class the earlier note
found as `0944-09-01`, which `CVDate` now catches. Drift did not improve
either (chemistry: 41 of 145 comparable fields at high effort, 20 of 136 at
default).

Whatever fixes this, it is not a model setting. Recorded so nobody spends a
day on it again.

## Result 4 -- drift is wrong facts, not formatting

Where extraction succeeded, repeat runs disagreed on up to **98 of 457**
comparable fields (human-development). A sample, each pair from two runs of
one document off byte-identical input:

| Field | Run A | Run B |
| --- | --- | --- |
| `experience.start_date` | 2000-09-01 | 2020-01-01 |
| `education.start_date` | 2020-08-01 | 2008-08-01 |
| `experience.unpaid` | true | false |
| `publications.self_author_index` | null | 0 |
| `education.country` | US | MA |
| `education.city` | "Cambridge, MA" | "Cambridge" |

The first two are twenty-year and twelve-year errors that no verdict catches:
the fact ledger stores them, `verify_against_facts` compares the claim to the
fact it came from, and both agree. `unpaid` decides which section a Rhodes CV
files a job under. `self_author_index` decides which name is bolded as the
applicant.

## Result 5 -- the four new prompt clauses land

The clauses added on this branch (thesis title under education, class rank,
`is_presentation`, referees) were unmeasured when written. On the documents
that extracted at all:

| Document | thesis | class rank | presentations | referees |
| --- | --- | --- | --- | --- |
| chemistry | 2/2 degrees | 1/2 | 4 of 10 publications | 0 |
| human-development | 3/4 degrees | 0/4 | 11 of 29 publications | 3 |
| economics | 0/1 | 0/1 | 0 | 0 |
| Harvard-Eng | 0/1 | 0/1 | 0 | 0 |

The zeros are correct abstention -- those documents state no thesis and no
rank. The presentation split matches the documents' own "Conference
Presentations" sections. Consistent with the earlier finding that ruled fields
hold; this is that finding on eight more documents.

## What follows

Ordered by measured effect, not by elegance.

1. **Make `country` and `city` optional on every entry model.** They are the
   single largest cause of total extraction failure, and a CV that does not
   state a country must be allowed to say so. The existing gap interview
   already asks about null fields, so the value is recoverable without a new
   surface. Expect the 59% to fall close to zero; re-measure to confirm rather
   than assume.
2. **Take dates away from the model.** Have it return the string it read
   ("September 2020") and parse that in Python. A parser cannot emit the year
   0200. This removes the only failure class that survives a human's reading
   of the draft, because "Sep 2000" looks plausible on a page.
3. **Then re-measure, with an answer key.** Validity and stability are now
   measured; accuracy is not. Nine documents, hand-keyed, is a day's work and
   it is what turns "we think it reads CVs correctly" into a number.
4. **Only then** decide whether the remaining drift needs repeat-run voting.
   It may be small once 1 and 2 land, and voting is a per-upload cost that
   should be paid only against a measured need.

The harness lives in this session's scratch directory, not the repo: it calls
a private function and hard-codes paths. If step 3 happens, it becomes a real
fixture-backed test with the corpus fetched by a script.

---

# Re-measured, same day, after the two changes

Same nine documents, same harness, three runs each.

| | before | after dates | after dates + place |
| --- | --- | --- | --- |
| usable runs | 11/27 (41%) | 13/27 (48%) | **26/27 (96%)** |
| documents extracting in all three runs | 1 | 2 | **8 of 9** |
| date failures | 3 (at high effort) | **0** | **0** |
| `country` failures | 9 | 4 of 4 sampled | **0** |

The one remaining failure is `europass-sample.pdf` -- the near-empty fixture,
67 characters of text -- where the model returned an empty `degree_as_awarded`.
A document with nothing in it is the right thing to fail on, and it is not a CV.

**The diagnosis was right and the ordering was right.** Two schema changes, no
voting, no grounding rule, no model change: a written date parsed in Python
(`apps/documents/dates.py`) and a place the document need not state. Both are
the same defect -- *a required field with no way to say "not applicable" makes
the model invent a value* -- which the research side had already written down
about `MoneyClaim.currency` and nobody had carried across.

## What this exposes

Drift was always there; failures were hiding it. With every document now
extracting, the numbers are visible and they are not small:

| Document | fields compared | fields disagreeing |
| --- | --- | --- |
| CV-communication | 384 | 77 (20%) |
| CV-cancer-bio | 315 | 75 (24%) |
| CV-electrical-engineering | 232 | 41 (18%) |
| CV-human-development | 443 | 37 (8%) |
| CV-economics | 179 | 33 (18%) |
| Harvard-CS résumé | 132 | 3 (2%) |

Read `entry_drift` in the raw results with caution: an entry is identified by
its name fields, so a title that varies slightly reads as an entry appearing in
one run and not another. It overstates. `field_drift` is the honest column.

So the question the next measurement has to answer is no longer "does anything
come out" but "is what comes out right, and is it the same twice". That needs
the answer key this run still does not have. Voting and grounding were designed
for exactly this and were deliberately not built yet -- they are a per-upload
cost, and they should be paid against a measured need rather than an inferred
one.

---

# Accuracy, against a hand-written answer key

The measurement the two schema fixes above could not make. 8 documents, 2 runs
each, every entry and every date compared against a key.

## The corpus had to change first

The six UPenn CVs **cannot be keyed for accuracy**: every date in them is
redacted to `20XX` (25-77 occurrences each, zero real years) and two redact
every publication title to `TITLE`. They measure structure and stability well
and accuracy not at all.

Worth correcting in the earlier section: the alarming drift pairs quoted there
-- `2000-09-01` vs `2020-01-01`, `2020-08-01` vs `2008-08-01` -- both come from
UPenn documents, so the model was guessing at a placeholder rather than
misreading a real date. The underlying defect is still real (the `0944` case
came from a genuine "September 2020" on a real CV) but this corpus exaggerated
its size.

The accuracy set is therefore: the two Harvard résumés, which are not redacted,
keyed by hand from their own text; and six synthetic CVs whose key is exact by
construction, one per format family -- English month names, German tabular with
WS/SS semesters, US seasons with month-first numerics, Turkish day-first
numerics with a service gap, abbreviated months with a thesis and a class rank,
and bare years.

## Scored at the precision the page states

A first pass scored 29% on dates, and the key was wrong: it asserted
`2023-06-30` where the document said only "Jun. 2023", so the extractor's
`2023-06-01` was marked wrong for choosing a different convention for the same
month. Keys now carry precision (`"2023-06"`, `"2019"`, `"2015-09-02"`) and are
compared by prefix. Scoring a convention is not scoring a reading.

## Result

| | before the fixes | after |
| --- | --- | --- |
| entries found | 60/60 (100%) | 59/60 (98%) |
| dates correct | 64/120 (53%) | **118/118 (100%)** |
| names correct | 16/16 | 16/16 |
| languages correct | 16/16 | 16/16 |
| over-extraction | 2 | 2 |

The 53% was our own bug, not the model's. `WithJsonSchema` was missing, so
pydantic told the model `"format": "date"` -- ISO only -- while the prompt told
it to copy the date as printed. The model obeyed the schema and emitted null
wherever ISO was impossible: every date on a CV writing `15/09/2014`, and every
date on a range writing `June - Aug 2025`. `parse_cv_date` never saw them.

The one missing entry is Hartford High School on the Harvard engineering
résumé, dropped in one run of two. The document names the school and a year and
no qualification at all, so there is nothing to put in `degree_as_awarded` --
the honest ambiguity in the set, and the only one.

The two "extra" entries are one military-service line extracted as employment.
Over-extraction, not fabrication, and arguably correct.

## What 100% here does and does not mean

It means: every format in the enumeration is read correctly, twice, and the
enumeration covers what these eight documents print.

It does not mean the enumeration is complete. Six of the eight documents are
mine, so they can only contain formats I thought of -- a real CV can print a
shape this table has never seen, and the honest next step is to grow the set
with real documents rather than to trust the number. The finite-representation
argument holds (formats are enumerable, and enumerating them closed the class);
what is not yet proven is that the enumeration is finished.

Still unmeasured: publications, awards and skills are not keyed, and no
document in the accuracy set has more than one publication. The `2019 - 2023`
case is scored correct at year precision but stores an invented month, so the
rendered CV prints "Mar 2019" for a page that said "2019" -- fixing that needs
the schema to carry date precision, which is a larger change than these two.
