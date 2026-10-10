# Discovery shadow run 3 — there were never three SPAs

Run 2026-08-30, against `www.master-wocc.eu` and `clide.umk.pl`, after wiring the intra-site hop.
Local file store instead of S3; everything else is the production path — real fetches, real
`extract_claims` against the live Responses API, real `write_catalog_entry`.

**Headline: shadow run 2's failure taxonomy was wrong.** It recorded three JavaScript shells and
two extraction failures, from five leads. Measured directly, none of the five was a shell and none
of the extraction failures had anything to do with the pages. Two bugs blocked all five, and both
are now fixed. A third blocker is real, structural, and newly precise.

## 1. "browser required: page is a JavaScript shell" was a false positive, five times out of five

`looks_unrendered` tested the *share* of a response that is visible text, at 5%. Measured on the
five hosts:

| Lead | bytes | visible words | ratio | visible text | old verdict |
|---|---|---|---|---|---|
| `lawgid.ius.bg.ac.rs` | 305,554 | 1,027 | 0.0202 | 7,340 chars | shell |
| `www.multidiverse.eu` | 1,252,111 | 496 | 0.0024 | 3,662 chars | shell |
| `www.emjmdstepsrock.eu` | 75,101 | 570 | 0.0455 | 3,926 chars | shell |
| `…/cout-de-la-formation` | 52,995 | 425 | 0.0481 | 2,889 chars | shell |
| `…/admission-et-selection` | 51,734 | 425 | 0.0493 | 2,879 chars | shell |
| `…/inscription-administrative` | 50,903 | 416 | 0.0490 | 2,914 chars | shell |
| `clide.umk.pl/pages/home` | 9,750 | 580 | 0.3569 | 4,532 chars | rendered |

Every one of them serves ordinary readable prose — programme descriptions, fee tables, admission
steps. Three sit at 0.048–0.049, decided by the threshold rather than by the page. The 5% figure came
from one measurement, of one EACEA detail page, and generalised badly: a heavy CMS wraps real content
in enough markup to look like a shell, and a genuine shell can be small.

The question the function's own docstring asks is *"is there anything for an extractor to read at
all"*, and an absolute floor answers that. `_MIN_TEXT_RATIO` is replaced by
`_MIN_VISIBLE_WORDS = 40`. Opintopolku's captured shell carries one word and is still caught; every
row above is now fetched and read.

**Consequence: item 3 of shadow run 2's nearest-work list — "browser tier for the SPA cases" — was
aimed at a phantom.** The browser tier is still wanted (see §4), but not for these.

## 2. Extraction failed on every page, for a reason no page could change

`ExtractionFailure("structured extraction call failed") from error` discards the cause, which is why
shadow run 2 recorded `clide.umk.pl` as undiagnosed. The cause:

```
BadRequestError: Error code: 400 - Invalid JSON schema: regex lookaround is not supported.
Found at $['$defs'].AwardTermsClaim.properties.repayable_share.anyOf[1].pattern.
```

Pydantic renders a bare `Decimal` as `anyOf[number, string]`, and the string arm carries its decimal
pattern, which contains lookahead. Structured output rejects the whole request. Six fields in the
schema are `Decimal`, so **every extraction call this project has ever made against the live API
failed**, on every page, for the life of schema v2. Nothing in the test suite could see it: the
fixtures parse a canned response and never render the schema the API refuses.

Fixed by declaring the wire type as a plain number (`Number = Annotated[Decimal,
WithJsonSchema({"type": "number"})]`) — Decimal still governs validation on the way in, and the
schema subset never supported the `ge`/`le` bounds anyway. Guarded by a test that walks the generated
schema and asserts no `pattern` contains lookaround.

With the fix, `…/bourses-detudes` extracts cleanly and richly: a €1,400/month Erasmus Mundus
scholarship over 24 months, ~20 awards per year, `MULTILATERAL` with a quoted French sentence behind
it, an application deadline, and an `AUTOMATIC_ON_ADMISSION` funding track.

## 3. The hop works, and the remaining blocker is that no single page carries a whole row

The intra-site hop turned one seed lead into six: the front door plus its five funding and admissions
pages, found in the anchors of the response already in hand, at no extra fetch.

**Sitemaps could not have done this.** `www.master-wocc.eu/sitemap.xml` is a 404, as is its
`robots.txt`; `clide.umk.pl/sitemap.xml` is a 404. The 28 August design proposed reusing
`EntityExpansionSource`'s sitemap walk for exactly this, and it would have found nothing on the host
that motivated it. The hop reads anchors instead.

All six pages now fetch, pass the shell check and extract. All six are still blocked, and every one
now says **`no evidence for a catalog row`** — `resolve_program` returning `None`. What it requires
from one page: institution name, programme name, a valid country, at least one *cited* teaching
language, and a duration of 1–60 months. What the pages actually carry:

| page | institution | programme | country | duration | teaching languages |
|---|---|---|---|---|---|
| `/` (front door) | Université de Lille | Master WOCC: Contemporary Challenges… | FR | — | French, English or Spanish |
| `/candidature-et-admission/bourses-detudes` | Université de Lille | Master WOCC | FR | **24** | — |
| `/candidature-et-admission/admission-et-selection` | Université de Lille | Master WOCC | FR | — | — |

The union of the first two rows is a complete catalog row. Neither alone is one, and the pipeline
extracts and gates each page independently. The duration lives in the scholarship sentence
("1400€/mois sur 24 mois"); the teaching languages live on the programme presentation. This is not a
tuning problem: `Program.duration_months` is `NOT NULL` under a 1–60 check constraint and
`affordability.py` multiplies monthly amounts by it, so the gate is right and the row genuinely
cannot be written from either page.

**This is the next increment, and it is a design change, not a fix.** Claims from several snapshots
of one programme have to combine — `OfficialEvidenceClaim` already carries its own snapshot per
claim, so per-claim provenance survives; what is missing is a notion of "these pages describe the
same programme" (the `catalog_key` already exists) and a rule for what happens when two pages of one
site disagree. Deliberately not improvised at the end of this session.

## 4. What this changes in the nearest-work list

| Shadow run 2 said | Now |
|---|---|
| 1. Intra-site hop for seed-catalogue leads | **Done** — by anchors, not sitemaps, which do not exist on these hosts |
| 2. Diagnose `clide.umk.pl` | **Done** — not page-specific; every extraction call was failing (§2) |
| 3. Browser tier for the 3 SPA cases | **Withdrawn as stated.** None of the three was a shell. The tier is still wanted for a different reason: `clide.umk.pl` renders its whole navigation client-side, so its raw HTML carries exactly one `<a href>` and the hop finds nothing to hop to |
| 4. ROR organisation frame | Unchanged |
| **new** | **Combine claims across pages of one programme.** The only thing now standing between this pipeline and its first catalog row |

## 5. Superseded by the full run, same day

Every "n = 2 hosts" caveat below was answered by running all 169:
`docs/superpowers/research/2026-08-30-eacea-full-catalogue-run.md`. **Nine catalog rows, the first
ever written**, four of them from hopped pages. Zero `browser required` across 494 leads, which
closes §4's item 3 for good. And the "no single page carries a whole row" finding holds at
population scale, with a number on it: merging a host's pages would take 8 complete hosts to 25, and
the dominant residual gap is that a joint degree has no single institution or country to state.

## 6. Honest limits (as written before the full run)

- **Still zero rows.** Two blockers removed, one named. `write_catalog_entry`'s write path remains
  unexercised against real data.
- **n = 2 hosts, 7 leads.** The claim that "no page carries a whole row" rests on three pages of one
  consortium site plus one page of another. Cheap to widen: run the full 169.
- The `_MIN_VISIBLE_WORDS = 40` floor is calibrated between one word (Opintopolku's shell) and 416
  words (the thinnest real page measured). Nothing was measured in between, and nothing needed to be.
- `ConsultantResearchTask` is `get_or_create(url, state=OPEN)`, so a re-run **keeps the first run's
  reason**. Two of this session's readings were of stale rows before that was noticed. Worth fixing,
  or the task list will keep narrating an old diagnosis.
