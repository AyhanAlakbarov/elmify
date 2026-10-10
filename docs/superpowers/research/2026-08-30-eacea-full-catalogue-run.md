# The full EACEA catalogue — nine catalog rows, and the shape of the other 125

Run 2026-08-30 against all 169 Erasmus Mundus consortium sites the EACEA listing yields, with the
intra-site hop wired and the two shadow-run-3 fixes in place. Local file store instead of S3;
everything else is the production pipeline — real fetches, real `extract_claims`, real
`write_catalog_entry`.

Run in two passes over one set of fetches: a network pass with extraction stubbed (free, and it
caches every response), then extraction and the write path replayed from that cache, so no host was
fetched twice. Cost: 595 extraction calls, 2,188,773 input and 445,127 output tokens.

**The catalog is no longer empty. Nine rows, nine institutions, nine funding opportunities, 123
evidence claims, across six countries.** The write path from extraction to `write_catalog_entry` has
now been exercised against real data for the first time.

| | |
|---|---|
| `BE` Université de Liège | EMerald — Master in Georesources Engineering |
| `FR` IMT Atlantique | MSc in Safe and Reliable Nuclear Applications |
| `IT` University of Padua | Erasmus Mundus Joint Master on Climate Change |
| `IT` Università degli Studi di Padova | CCD-STeDe |
| `NO` NTNU | Coastal and Marine Engineering and Management |
| `NO` Western Norway Univ. of Applied Sciences | Theatre SPACEs |
| `NL` IHE Delft | EM MSc in Flood Risk Management |
| `DE` Saarland University | AMASE — Advanced Materials Science and Engineering |
| `LV` Art Academy of Latvia | Service Design Strategies and Innovations |

## 1. The population, end to end

| | |
|---|---|
| Consortium sites on the listing | 169 |
| Leads after the intra-site hop | **494** (176 front doors + 318 funding/admissions pages) |
| Blocked before extraction | 39 |
| Reached extraction | 455, across 135 hosts |
| Extracted successfully | 429 |
| **Catalog rows written** | **9** |

The 39 pre-extraction blocks are ordinary internet, not defences: 14 × HTTP 403, 6 plain-`http://`
links on the EACEA listing that `canonicalize_url` refuses, 6 timeouts, 4 TLS failures, 3 × 404,
2 × 5xx, 2 other 4xx, 1 disallowed content type.

**`browser required: page is a JavaScript shell`: zero. Across all 494 leads.** Shadow run 2 reported
that verdict for three of five sites and filed "browser tier for the SPA cases" as the third-largest
piece of work. The population says the verdict was a bug, not a finding, and it is now closed.

## 2. The hop earned its place

Pages reached per host: 19 hosts yielded only their front door; the rest yielded 2–7. 318 of the 494
leads exist only because of the hop.

**Four of the nine rows were written from hopped pages** — `theatre-spaces.eu/admission`,
`floodriskmaster.org/scholarships`, `ccd-stede.eu/fees-and-fundings/erasmus-mundus-scholarship`,
`sdsi.ma/admission`. Without the hop this run writes five rows instead of nine.

## 3. What gates the other 125 hosts, measured

`resolve_program` needs institution, programme, a valid country, a cited teaching language and a
duration of 1–60 months, all from one page. Of the 429 pages that extracted:

| Required field | pages that lack it |
|---|---|
| teaching language | 343 |
| country | 291 |
| duration | 290 |
| institution | 234 |
| programme name | 11 |

Almost every page names the programme. Almost none names all five things.

**Merging a host's pages closes a fifth of the gap, and no more.** Taking the union of every
extracted page per host:

| | hosts |
|---|---|
| complete from a single page | 8 |
| complete only by union across pages | **+17** |
| still incomplete after union | 109 |
| total hosts with an extraction | 134 |

So the "combine claims across pages of one programme" increment is worth roughly **3× the current
row count** — 25 hosts instead of 8 — and is not the whole answer.

What the union still lacks, most common first: `institution, language, country` (20 hosts),
`institution, country` (20), `language` alone (16), all four (12), `country` alone (9).

**The dominant residual gap is institution and country, and that is a modelling problem, not an
extraction one.** These are *joint* master's degrees. A consortium of four universities in four
countries has no single institution and no single country to state, so its pages do not state one —
and `Program` requires exactly one of each. The catalogue could supply an identity (`LeadIdentity`
exists and `resolve_program` prefers it), but `HtmlCatalogue` deliberately reads no identity off the
listing, and for a joint degree the listing does not have one to give either.

**The forking is already visible in the nine rows.** `ccd-stede.eu` wrote twice, from its front door
and from its scholarship page, and the extractor named the same university "University of Padua" on
one and "Università degli Studi di Padova" on the other. `catalog_key` dedupes on the name, so one
programme became two institutions and two programmes. Per-host merging fixes this case; a general
answer needs a canonical institution handle, which is what increment 4's ROR frame is for.

## 4. Extraction: 20 hard failures, all schema-validation

429 of 451 pages extracted. Of the 22 that did not, 2 were a cache-key artifact of the harness and 20
were **Pydantic validation errors on the model's own output** — cross-field rules the JSON schema
cannot express, so the model can violate them and the whole response is rejected:

- **13 × `key_dates.N`: "a key date is either dated or decentralised"** — much the largest class.
- 2 × `published_selection_rate.rate` outside 0–1.
- the rest: `eligibility_criteria` unit and currency rules.

Worth a look: a schema whose validators reject one date out of six discards five good dates, an
institution, a programme name and every funding claim on the page.

**Not evidence about the pipeline:** 119 pages failed on the harness's first extraction attempt and
99 of them succeeded unchanged on retry. The first attempt discarded the cause (the same trap as
shadow run 3 §2, in the harness this time), so the failures are unattributed; the presumption is
throttling from eight concurrent workers, which the sequential pipeline would not produce. `extract_claims`
has no retry of its own, which is worth revisiting only once a cause is actually recorded.

## 5. Are the nine rows right? Mostly — and three deadlines are not

Checked 2026-08-30, read-only, against the cached responses. 123 claims: 65 offer a quotation, 58 are
derived fields carrying none.

**No fabricated facts.** Of the 65 quotations, 52 are verbatim on the page. The other 13 were flagged
by matching and then read by hand; every one is factually right. What defeated the matcher was page
rendering, not invention — `page_text` puts a table's `Language | English` on two lines, bullet
glyphs break a list mid-sentence, and `floodriskmaster.org` splits `2026` into `2` + `026` across
two elements.

**Four quotations are not literal, though their facts are.** `ccd-stede` twice carries an invented
lead-in ("The scholarship holders comply with the following conditions:") in front of a real bullet;
`theatre-spaces` renders "Proof of English language proficiency…" as "Applicants must provide proof
of…"; one `sdsi.ma` quotation splices two passages from different parts of the page behind an
ellipsis. The facts survive, but `OfficialEvidenceClaim.claim` is what a counselor reads *as the
page's own words*, and a reader who goes looking for that sentence will not find it.

**All nine durations are grounded** — every cited page states 120 ECTS, 24 months or two years.

### The deadlines are the defect

Six programmes recorded an application deadline. **Three are wrong, two of them absurdly:**

| Programme | stored | the page actually says |
|---|---|---|
| `theatre-spaces.eu` | **1558-12-01** | "the deadline set for / 1 December / 2026 at 23:59 CET" |
| `ccd-stede.eu` (scholarship) | **1515-02-15** | "FIRST CALL (15 NOVEMBER 2025 – 15 FEBRUARY 2026)" |
| `ntnu.edu` | **2025-08-30** | "Apply before / Closed to new applicants". There is no deadline. The date is the page's own render timestamp, "Sun Aug 30 16:34:36 CEST 2026" — read as a deadline, and with the year wrong as well |

The first two are the same mechanism: the year is adjacent to the day and month but not contiguous
with them, and the model emitted a year assembled from the surrounding digits — `1 December` + a lost
year, and the two `15`s of `15 NOVEMBER … 15 FEBRUARY`.

**And the citation was right while the date was wrong.** These are not uncited guesses:

```
APPLICATION_DEADLINE: 1558-12-01 — The application portal opens on 1 October,
                                   with the deadline set for 1 December 2026 at 23:59 CET.
APPLICATION_DEADLINE: 1515-02-15 — FOR CANDIDATES APPLYING TO THE FIRST CALL
                                   (15 NOVEMBER 2025 – 15 FEBRUARY 2026)
```

The quoted evidence states the correct year in both cases. Nothing compares the machine-readable date
to the sentence stored beside it, so a contradiction between a claim and its own citation is
storable. **A deterministic check — the stored year must appear in its own evidence text — catches
both, with no model involved.** `ntnu`'s is uncited (`ExtractedClaims.deadline` is the schema-v1
field, a bare `date | None` with neither evidence nor bound) and that check would not reach it; a
plausibility window would.

Contrast `duration_months`, which carries `1 <= n <= 60` in `resolve_program` *and* a database check
constraint. Dates have neither, at any layer, and a year of 1515 travelled from the model into a
`DEADLINE` claim without one thing objecting.

**This is the field a student acts on.** It is also the cheapest thing on this page to make safe.

## 5b. The rewrite, and what reading the rows by hand found

Re-ran the write path over the same 429 cached extractions after the fix, having cleared the nine
stale rows (sources and snapshots kept, so nothing was refetched and no model call was made).

**Nine rows again, and the deadlines are clean.** 15 `DEADLINE` claims, **zero with an implausible
year**. The three fabricated ones now read `date stated but not read reliably` beside the sentence
that states the date correctly, and NTNU's render-timestamp deadline is gone entirely — the uncited
schema-v1 field no longer becomes a claim. The run reported `degraded=('3 dates dropped as
unreadable',)`, so the count works end to end on real data and not just in a test.

**Reading three rows claim-by-claim found something no automated check did.** Two `FUNDING` claims
are durations wearing money:

```
Mobility subsistence allowance maximum duration: 6 SEK per MONTHS      (ccd-stede.eu)
Monthly allowance maximum duration: 24 EUR per months                  (floodriskmaster.org)
```

The facts are "6 months" and "24 months". `MoneyClaim` requires `amount`, `currency` and `period`,
so a duration gets an amount and a currency it never had — **and the ccd-stede page contains the
string "SEK" zero times.** The currency is fabricated outright.

**This is the 1515 bug one level up, and it generalises.** A required field with no "not applicable"
option makes the model invent a value to satisfy the shape: `KeyDateClaim.on` produced a year out of
day-and-month digits, and `MoneyClaim.currency` produces a currency out of nothing. The date fix
bounds one field; it does not touch the pattern.

Impact is bounded today because `_write_opportunity` persists no typed money column — the amount
stays inside `OfficialEvidenceClaim.claim` text, so `affordability.py` never multiplies it. What is
damaged is what a counselor reads, which is the same thing the deadlines damaged.

Not fixed here. The candidate shapes — make `currency` optional and reject a `MoneyClaim` without
one, or give durations their own claim rather than letting them borrow money's — are a schema
decision of the same kind as the date fork, and belong with the claims-merge increment.

## 6. Honest limits

- **Nine rows is nine rows.** Nothing here says they are *right* — no one has read the 123 claims
  against the pages they cite. That check has not been done.
- The union analysis is arithmetic over stored claims, not a run. It predicts 25 hosts; only a build
  of the merge would confirm it.
- One catalogue, one degree level, one funding family. Erasmus Mundus consortia are unusually
  multi-country, so the institution/country gap measured here is probably worse than a national
  registry's would be.
- `EXTRACTION_CALLS_PER_HOUR = 200` silently truncated the first attempt at this run at 233 of 494
  leads, reported only as `degraded=('extraction budget exhausted',)`. A full-catalogue run needs
  that raised deliberately, and the report line is easy to miss.

## 5d. The quotation rule, measured on a 38-page sample — 2026-08-31

§5b left the fabricated currency unfixed and named the shape of the fix. It is now built:
`MoneyClaim` carries an `evidence` field, and `catalog.py::_money` writes a money row only when the
quoted sentence actually contains that currency — its ISO code as a whole word, or its symbol.

**Method.** 38 pages re-extracted from the cached bodies of the 2026-08-30 run — no refetching, and
the 595-call corpus itself was not touched. The sample is mechanical, not chosen: every page whose
original extraction carried a money claim with a non-ISO currency (10), every page whose money label
named a duration (5, two overlapping the first group), and 25 pages carrying ordinary EUR claims as a
control, sampled with a fixed seed. Cost: **38 calls, 180,031 input and 54,748 output tokens**,
against 595 / 2,188,773 / 445,127 for the full run.

**1. Money now quotes itself, without exception.** 207 money claims came back across the sample and
**207 carry an evidence string — 100%**. The field was optional in the schema precisely so one bad
claim could not discard a page; the model populated it anyway, every time.

**2. The `6 SEK per MONTHS` fabrication is gone.** `ccd-stede.eu` re-extracted to three money claims,
all EUR, none a duration wearing a currency. Two are written; one is withheld because its quotation
does not name the currency.

**The second §5b case is NOT verified, and must not be reported as fixed.** `floodriskmaster.org`
was one of four pages in the sample whose extraction failed on Pydantic validation of the model's own
output — the same class of hard failure §4 measured at 20 pages. Its `24 EUR per months` claim is
therefore unmeasured here.

**3. Control loss: 59 of 159 control claims dropped (37%) — but that number is mostly the rule
working.** Decomposed:

| | claims | verdict |
|---|---|---|
| currency is not a currency (`PCT`, `SCH`) | 8 | correct — the value was never money |
| the quotation supports no amount and no currency | 41 | correct — this is the rule's whole purpose |
| **the currency is spelled out in the quotation** | **10** | **false negative** |

So the quotation rule's true cost is **10 of 159, 6.3%**. Examples: *"a monthly stipend of 1000
euros"*, *"1,400 Euros per month"*, *"33 600 Euro (1,400 Euro x 24 months)"*. These are legitimate,
correctly quoted money figures that the catalog now withholds.

**The documented upgrade trigger has fired.** `_money`'s `ponytail:` comment says to add a
currency-name map when a real source is measured losing a claim to the word-boundary rule. Ten have
been measured. **It is not added here**, deliberately: a name map reintroduces the false-positive
class that word boundaries just closed, in a subtler form — `\beuro\b` matches "the Euro area" and
"Euro" in prose about currency unions, so a fabricated EUR amount evidenced by a sentence about the
eurozone would pass. That needs its own design, its own measurement and its own review, not an
append at the end of a run. It is the natural next increment.

**A note on measuring this.** The first pass at this table reported 15 false negatives, because the
classifier used `euros?` to detect a spelled-out currency — which matches "**Euro**pean", on pages
about European joint programmes. That is the identical defect this section is reporting a fix for,
reproduced accidentally while measuring it. The corrected classifier word-boundaries the name.

**A measurement class the sample above did not separate: zero-amount claims.** 85 of the corpus's 618
money claims (13.8%) have `amount == 0`. Their sentences are the ones least likely to name a currency
at all — "no tuition fees are charged", "covered by the scholarship", "included" — because there is no
number for a currency code to sit next to. `"Tuition fees for scholarship holders: 0 EUR"` is among
them, and it is one of the most student-relevant facts a page can state; most of the other 84 are
noise like `"Accommodation: 0.00 EUR"`. The 38-page sample above was not stratified against this class,
so the measured **6.3% false-negative rate is not measured against zero-amount claims specifically**
— it may understate the quotation rule's cost for this class in particular. Open question for the next
increment; not fixed here.

## 5e. What the pooling change did to the row count — 2026-08-31

Replayed over the same 429 cached extractions, no model calls, ~6 seconds:

| | before | after |
|---|---|---|
| distinct hosts writing rows | 8 | **24** |
| `Program` rows | 9 | 27 |
| `Institution` rows | 9 | 22 |
| `OfficialEvidenceClaim` rows | 117 | **691** |

The 24 matches §3's arithmetic (8 complete from a single page, +16 completed by pooling). The two
`Program` rows over the predicted 25 are the name-variant fork §3 describes and increment 4's ROR
frame is for.

`DiscoveryReport.degraded` reads `("110 programmes' pages never stated a required gate fact", "57
dates unreadable, citations kept")`. The 110 is §3's "still incomplete after union: 109" plus one —
a runtime count from the live pipeline landing on the figure a static analysis of the corpus
produced before the code existed.

**The contradiction count is zero, and that is the interesting part.** Before the degree-level guard
below, two hosts appeared to contradict themselves on duration, and a single conflated counter
reported all 111 refusals as disagreements — which would have sent a reader hunting a data-quality
problem that does not exist. Splitting the counter exposed the 2; fixing the guard removed them.

### The two "contradictions" were never contradictions

`one_programme_per_site` promises one programme per *link*, but the pool group is per *host*, and
`FUNDING_PATH_TERMS` deliberately routes the intra-site hop at `phd`, `doctoral` and `graduate`
paths. So a vouched front door pooled with pages describing a different degree:

| host | the master's | the other degree |
|---|---|---|
| `www.ntnu.edu` | `/studies/mscomema` — 24 months | `/phd` — 36 months |
| `life.univ-cotedazur.eu` | — | `/education/phd-degree` — 36 months; a mobility-grant page — 6 months |

Neither host ever disagreed with itself. `www.eusmat.net` showed the damage plainly: its AMASE
**master's** row was written with a doctoral stipend and a "candidates with a Master's degree"
eligibility criterion, both harvested from four DocMASE **PhD** pages — a master's programme
published as requiring a master's degree.

`_names_another_degree` now refuses to pool a page whose URL path carries a degree-level word
(matched on path segments, never as a substring: `graduate` is inside `undergraduate` and
`postgraduate`, which name no other degree). After it, AMASE cites only its own two `/master/amase/`
pages, and **141 claim rows belonging to a different degree programme are gone — 832 to 691 — with
the host, `Program` and `Institution` counts unchanged.** Correctness at no cost to yield.
