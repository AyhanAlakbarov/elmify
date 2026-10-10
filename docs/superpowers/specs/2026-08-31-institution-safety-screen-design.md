# The institution-safety screen — how a register becomes a gate

**Date:** 2026-08-31. **Status: design, no code written.** Closes the research series that runs from
`2026-08-31-open-admission-synthesis.md` through the four register recons, the coverage measurement,
`2026-08-31-register-open-questions-closed.md` and `2026-08-31-three-remaining-gaps.md`. Every number
quoted here was measured in one of those files on 2026-08-31; nothing is re-derived and nothing new
is claimed.

**The screen answers three questions and refuses a fourth.** Has this institution's quality been
judged by somebody with standing; may it lawfully enrol an international student; will the degree be
recognised where the student comes home to. It does **not** answer what the programme costs or who it
admits — except in the United States, and there only the admissions half.

**Two things in this design are not optional and are not obvious.** A register row is a statement
about a *subject that may be smaller than an institution* (Türkiye), and a register *negative* means
something different in every country (coverage runs 98% to 6%). Both are schema decisions. Getting
either wrong is not a bug that surfaces in tests — it is a product that quietly libels universities.

---

## 1. What is being built, in one paragraph

Eleven government registers are fetched on their own cadences into an evidence chain that already
exists, reduced to rows in **one new table**, and read by **one new function** that takes an
institution, the student's home country and the destination and returns a verdict per axis with the
provenance and the date attached. No model reads a register. No register row is a boolean.

The screen is half of a pair, and the dependency is stated in
`2026-08-31-screen-coverage-measurement.md` §7 and nowhere else: **the screen says an institution is
real; the extraction pipeline on `claude/claims-merge-money-design` says what it costs and who it
admits. Neither is usable alone.**

## 2. The five axes, and why they must never merge into one flag

The handoff names three jobs registers do. Working through the eleven registers produced five,
because Australia and Canada each answer a question the other three jobs do not cover.

| axis | the question | who answers it |
|---|---|---|
| `QUALITY_ASSURED` | has a body with standing judged this provider | DEQAR, NZQA category, KHDA/UQAIB stars, IEQAS, DAPIP |
| `MAY_ENROL_INTERNATIONAL` | may it lawfully take our student | UK sponsor register, CRICOS, DLI, NZQA Code signatory, SEVP, CAA status |
| `RECOGNISED_AT_HOME` | will the home country count the degree | anabin, China MoE reference list, YÖK exclusions |
| `MAY_AWARD_OWN_DEGREE` | whose degree does the student actually receive | TEQSA provider category, OfS (per provider, bulk unconfirmed) |
| `WORK_RIGHTS_AFTER_STUDY` | does the qualification carry post-study work | DLI `PGWP`, UK `Status` track record |

**These are orthogonal and the counterexamples are real, not hypothetical.**

- **CRICOS**: 1,486 of 1,554 providers are private colleges. Membership means *may enrol overseas
  students* and says nothing about quality. A screen that merges the axes clears all 1,486.
- **NZQA**: nine providers rated Category 3 or 4 — the regulator's own "Not Yet Confident" and "Not
  Confident" judgements — **may still recruit international students**. `MAY_ENROL_INTERNATIONAL` is
  clear; `QUALITY_ASSURED` is not. One flag cannot hold both.
- **Canada**: a P3 / curriculum-licensing programme passes every accreditation gate and fails
  `WORK_RIGHTS_AFTER_STUDY` outright.
- **Türkiye**: an institute inside the University of Houston fails `RECOGNISED_AT_HOME` for a Turkish
  student while the parent university passes every other axis for everyone.

Merging is the single most likely design failure here, because every register hands you something
that *looks* like a pass/fail column, and four of the five axes are individually cheap to compute.

## 3. Data model

### 3.1 The change to `Institution` — three columns, one of them load-bearing

`apps/funding/models.py::Institution` gains:

```python
class Kind(models.TextChoices):
    INSTITUTION = "INSTITUTION"
    CAMPUS = "CAMPUS"
    UNIT = "UNIT"          # an institute, centre or chair inside a parent

kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.INSTITUTION)
parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                           related_name="subunits")
ror_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
```

**`parent`/`kind` exist because of one finding and only one.** YÖK's 41-institution exclusion list
names *institutes, centres and chairs inside otherwise reputable universities* — a named institute
within the University of Houston, a research chair at Deakin
(`2026-08-31-three-remaining-gaps.md` §2). Every one of the eleven registers is institution- or
campus-keyed. A screen keyed the same way **cannot express the exclusion at all**, in one of our two
launch markets. This is why it is a schema decision and why it is being taken before any code: adding
a self-FK later means backfilling every listing row that was written against the wrong grain.

A self-FK on the existing table, not a new `ScreenSubject` table. A unit is an institution for every
purpose the rest of the codebase has — it has a name, a country, and `Program.institution` pointing at
one is correct, not a leak. A unit with no site of its own carries the parent's
`official_website`, which the existing HTTPS check accepts.

**`ror_id` is the canonical identity handle**, and it is free: `deqar-institutions.csv` carries an
`identifiers_all` column with a ROR ID on **3,664 of 9,018 rows**, public domain, refreshed daily.
This is the same handle `2026-08-28-funding-led-discovery-design.md` reserves for increment 4 and
that `2026-08-30-claims-merge-and-money-evidence-design.md` names as the general answer to
name-variant forking. **The screen and the money branch want the same column; write it once.**

Identity resolution is confirmed cross-cutting, not a European detail:
`Most-Recent-Cohorts-Institution.csv::ACCREDAGENCY` is a **name string** populated for all 6,273 US
rows, Korea's IEQAS list prints institution names in uppercase, and CRICOS carries a trading name
next to an institution name. Blank `ror_id` is the normal case and must never be treated as a
mismatch.

### 3.2 `RegisterListing` — the one new gate table

```python
class RegisterListing(models.Model):
    class Axis(models.TextChoices):
        QUALITY_ASSURED = "QUALITY_ASSURED"
        MAY_ENROL_INTERNATIONAL = "MAY_ENROL_INTERNATIONAL"
        RECOGNISED_AT_HOME = "RECOGNISED_AT_HOME"
        MAY_AWARD_OWN_DEGREE = "MAY_AWARD_OWN_DEGREE"
        WORK_RIGHTS_AFTER_STUDY = "WORK_RIGHTS_AFTER_STUDY"

    class Verdict(models.TextChoices):
        CLEAR = "CLEAR"            # the register says yes
        QUALIFIED = "QUALIFIED"    # the register defers, or grades it low
        EXCLUDED = "EXCLUDED"      # the register says no, by name

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE,
                                    related_name="register_listings")
    #: Provenance. The register file we fetched, digested and archived. PROTECT:
    #: a listing whose snapshot is gone is an unsourced assertion.
    snapshot = models.ForeignKey("OfficialSourceSnapshot", on_delete=models.PROTECT)
    axis = models.CharField(max_length=30, choices=Axis.choices)
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    #: The publisher's own word, verbatim: "Details", "H +/-", "Category 3",
    #: "Probationary Sponsor", "X", "(LICENSURE REVOKED)", "★★★★★".
    #: Never normalised away -- the verdict is our reading, this is theirs.
    raw_value = models.CharField(max_length=200)
    #: Whose question this answers. "" = everyone. "TR" = Turkish students only.
    audience_country = models.CharField(max_length=2, blank=True, default="")
    #: The register's own as-of date, NOT when we fetched it. KHDA's stars are
    #: 2022; IEQAS is 2026-03-03; CRICOS is monthly. Staleness is a property of
    #: the publication, not of our job schedule.
    as_of = models.DateField()
    #: Cohort-dated rules. Canada's P3 exclusion binds by programme START date
    #: (same-province agreements on or before 2024-05-15, cross-province on or
    #: before 2023-01-31). Null on both = applies to every cohort.
    applies_from = models.DateField(null=True, blank=True)
    applies_until = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("institution", "axis", "audience_country", "snapshot"),
                name="register_listing_subject_axis_audience_uniq",
            ),
        ]
```

Four properties of this table are deliberate.

**`raw_value` is kept verbatim and the verdict is separate.** Every register uses its own vocabulary
and three of them are not binary: Canada's `PGWP` is `Yes` 495 / `No` 589 / **`Details` 358** — a
quarter of the register refusing to answer at row level; anabin rates `H+` / `H +/-` / `H -`; NZQA
grades 1–4; the CAA publishes `A` 103 / `X` 55 / `T` 1 plus 24 titles carrying "(LICENSURE REVOKED)".
Collapsing those into a boolean at ingest destroys the only thing that can be shown to a student, and
misclassifies about a third of Canadian institutions on its own.

**`audience_country` is what makes recognition expressible.** Recognition is a relation between an
institution and a home country, not a property of the institution. YÖK's exclusions are `TR`-only.
anabin's H-ratings are `DE`-only. DEQAR's quality reports are for everyone. Without this column the
same table would have to be either wrong for Turkish students or wrong for everyone else.

**It is a projection, not a ledger** — the same rule and the same reason as `ProgramCompetency`: the
archived snapshot is the record of what the register said, and this table is the queryable read of
it. Re-ingesting a register replaces its rows. There is no `supersedes` here because there is one on
`OfficialSourceSnapshot`.

**There is no `UNKNOWN` verdict.** Absence of a row is unknown, and §4 is entirely about what absence
means.

### 3.3 `RegisterCoverage` — the table that stops the screen libelling people

```python
class RegisterCoverage(models.Model):
    snapshot = models.ForeignKey("OfficialSourceSnapshot", on_delete=models.PROTECT)
    axis = models.CharField(max_length=30, choices=RegisterListing.Axis.choices)
    country_code = models.CharField(max_length=2)
    listed = models.PositiveIntegerField()    # institutions the register knows of
    cleared = models.PositiveIntegerField()   # of those, verdict CLEAR
```

Roughly 131 rows per register refresh. It exists because
`2026-08-31-screen-coverage-measurement.md` §3 measured the thing nobody was looking for: screenable
as a share of DEQAR-listed runs **Hungary 98%, Cyprus 98%, Croatia 96%, Indonesia 96%** down through
**England 37%** to **Ukraine 6% (707 listed, 41 screenable)**.

> In Hungary, an institution with no current QA report is a real signal — nearly all its peers have
> one. In Ukraine it is close to meaningless. A screen that renders "not verified" identically in
> both cases will libel Ukrainian universities and flatter English ones.

Storing coverage separately, rather than deriving it by counting listings, is what lets us ingest
listings only for institutions the catalog actually references while still knowing the denominator.
We are not creating 9,018 `Institution` rows to be able to render one honest negative.

### 3.4 Where register-supplied *values* go — nowhere new

The US supplies facts, not gates: `ADM_RATE` (usable on **1,910 of 6,273** rows), `ACCREDAGENCY`
(6,273 of 6,273), `CONTROL` (**2,325 for-profit**, the largest of the three sectors), `HIGHDEG`
(1,982 award graduate degrees), `MD_EARN_WNE_P10`.

These are not listings. They go through the machinery that already exists — an
`OfficialEvidenceClaim` attached to the `Institution` via `InstitutionEvidenceClaim`, quoting the CSV
row, citing the snapshot. Nothing new is built, and a Scorecard figure carries the same provenance a
programme page's figure does. The only difference from the existing path is that the reader is a CSV
field access rather than a model call, which is a strengthening, not a weakening.

**Correct the claim the handoff carries forward.** `2026-08-31-screen-coverage-measurement.md`'s
amendment says a country may supply "selectivity and cost" directly. The cost half was closed
negatively the same day in `2026-08-31-register-open-questions-closed.md` §6: Scorecard's
`TUITIONFEE_IN`/`TUITIONFEE_OUT` are **undergraduate**, `TUITIONFEE_PROG` is occupational-school
programme cost, `TUITFTE` is an accounting figure, and the field-of-study file's 38,621 master's rows
carry **debt and earnings, no price column at all**. So: **the model must allow a register to supply
either, and no register supplies master's price today.** `DEBT_ALL_STGP_ANY_MDN` at `CREDLEV=5` is a
borrower-only federal-loan median and **must never be rendered as a cost**.

Two cautions that belong in the reader, not in a comment somewhere:

- **`ADM_RATE` is blank or suppressed on 4,363 of 6,273 rows**, and open-enrolment institutions
  frequently report none *because* they admit everyone. Absence here is weakly correlated with the
  opposite of selectivity. Never infer.
- **`deqar-institutions.csv::country` must be parsed as a quoted CSV field.** "Korea, South" splits on
  its own comma and a naive reader invents two countries — this is the whole explanation of the
  `Korea` / `South` pair in the blind-spot count.

## 4. What a negative means — the rendering contract

Four distinct absences, which the product must not conflate:

1. **Explicitly excluded.** The register names it: CAA's 24 "(LICENSURE REVOKED)" titles, TEQSA's
   three unregistered entities, NZQA Category 4, MEXT's two schools over the 5% dropout criterion,
   YÖK's 41. `verdict=EXCLUDED`. **This is the only kind of negative that may be shown as a negative.**
2. **Qualified.** `PGWP=Details`, `Probationary Sponsor`, `Subject To Action Plan` (15 sponsors
   today), NZQA Category 3, anabin `H +/-`. Shown with the publisher's own word and a link, never as
   a fail.
3. **Listed but not cleared.** Georgia: 83 institutions listed, 60 with reports, **8 screenable** —
   because 1,247 of 1,274 report rows are NCEQE's and NCEQE's EQAR renewal was rejected, not lapsed.
   Russia is the identical case via AKKORK, 33 institutions. This is a *filter*, not a blackout, and
   it is exactly what `RegisterCoverage` is for.
4. **Not listed at all.** Every register in the series declares its own incompleteness, in its own
   words: anabin's *"keine Gewähr … für Vollständigkeit"*, EQAR's *"the Original Documents represent
   the only formally valid representation"*, canada.ca's *"Not all programs offered by a DLI are
   eligible for a PGWP."*

**The rule.** Carry the country's coverage rate alongside every negative, or show no negatives. And
in student-facing language: **the screen clears providers, never qualifications.** A DLI flagged
PGWP-eligible is not a promise about the student's programme; an anabin H+ is not a promise the
degree is recognised; a DEQAR report is not a promise the programme is accredited.

## 5. Reading the screen

`apps/research/screen.py` (new), one function, no class:

```python
def screen_institution(institution, *, home_country, destination_country, cohort_start=None)
        -> ScreenResult
```

Returns, per axis, the verdict plus `raw_value`, `as_of`, the publisher, the snapshot for citation,
and the country's coverage rate — or `None` for "no register we hold answers this axis here", which
is the honest answer for most of the world and must be rendered as such.

`audience_country` filters to `""` or `home_country`. `cohort_start` filters
`applies_from`/`applies_until`, which is what makes Canada's P3 exclusion correct rather than
categorical — for our population, all starting in the future, it resolves to categorical anyway.

Three things the screen refuses to compute, and the in-product language for each:

- **Azerbaijan.** Recognition is *nostrifikasiya* through TKTA, case by case, resolved only after
  graduation. There is no list to pre-clear against and there will not be one. Say so; never imply a
  clear.
  *Corrected 2026-09-26 (institution provenance gate spec §9.6):* TKTA does publish two negative
  lists as JSON -- not-recognised universities (`/api/not-recognized-universities`) and
  high-refusal universities (`/api/rejected-universities`) -- though still no list of recognised
  institutions.
- **Türkiye.** YÖK operates a per-institution e-Devlet query, not an enumerable list. Gate partially
  by ranking band at the year of enrolment; below the bands it is individual assessment.
- **China as a destination.** Authorisation to enrol international students is administered per
  institution and not published as a list. Case-by-case, like Azerbaijan.

## 6. Ingest — one adapter shape, eleven configurations

A frozen config dataclass per register in `apps/research/registers.py`, in the shape of
`seeds.py::HtmlCatalogue`: the adapter is configuration, not code, and adding a country is filling
one in.

```python
@dataclass(frozen=True)
class Register:
    slug: str
    publisher: str              # -> OfficialSource.publisher, source_type=REGULATOR
    url: str                    # or a resolver, see the UK note below
    jurisdiction: str           # ISO-3166 alpha-2 of the authority
    axes: tuple[str, ...]       # which of the five this file answers
    audience_country: str = ""  # "" unless the register speaks for one country's students
    cadence: timedelta          # what "stale" means for THIS publisher
    licence: str                # "PDDL", "OGL-3.0", "CC-BY-2.5", "CC-BY-4.0", "unverified", …
    transport: str = "plain"    # "plain" | "browser"
    parse: Callable[[bytes], Iterable[ParsedRow]]
```

Every fetch goes through `egress.py::fetch_official_source` (which runs `validate_public_url` on
every redirect hop) or, for `transport="browser"`, `render_via_browser_service` behind
`LocalEgressProxy` — the rules in `CLAUDE.md`'s web-fetching section apply unchanged, and
`BrowserDesiredCount` moving off 0 is part of this work, not a separate task.

**`refresh.py::OffSiteRedirect` applies here too.** A register is an `OfficialSource` the catalog
vouches for; an off-site redirect from a government host must fail before `persist_snapshot`, not
become shared-catalog rows every tenant reads. Origin comparison — scheme + host — not whole-URL
equality, for the reason that file already records.

### 6.1 The eleven, with what each costs

| register | route | licence | cadence | axes | notes that will otherwise be rediscovered |
|---|---|---|---|---|---|
| **DEQAR** | 4 daily CSVs at `backend.deqar.eu/static/daily-csv/` — 9,018 institutions, 149,229 reports, 107 agencies | **PDDL** (metadata); reports are the agency's, CC-BY-SA-4.0 by default | daily | quality | No token for the bulk files. Clear only on a report from an agency whose `deqar-agencies.csv::is_registered` reads `Registered` (60 of 78). Store metadata, **link** the PDFs, never mirror them |
| **anabin** | `GET /api/public/institution` with a MongoDB-style server-side `filter` — one market per request | **Impressum bars database storage** — see §7 | monthly is ample | recognition (`DE`) | `limit≤1000`; `limit=100000` → 503; bursts 503 and clear in ~2 min. Gate value is `institutionType.status.nameShort`. **A 200 proves nothing on this host** — invented paths return 200 HTML. Assert the four fields read and fail hard rather than write a partial refresh |
| **UK sponsor register** | resolve the CSV from `gov.uk/api/content/...`'s `details.attachments[]` — 1,308 rows | **OGL v3.0** | ~every business day | enrol, work-rights | The asset URL is content-hashed per revision; **never hard-code it**. `Status` is a three-level ladder (Track Record 302 / Sponsor 939 / Probationary 67). `Immigration Compliance = "Subject To Action Plan"` is live regulatory action, 15 today. One row *per route* — dedupe on name |
| **Canada DLI** | one 430 KB JSON at `canada.ca/content/dam/ircc/documents/json/dli/dli-full-list.json` — 1,442 rows, 1,119 institutions | **unverified**; site terms apply — resolve before ingesting | unpublished | enrol, work-rights | `PGWP` is tri-valued. `Grad Program` is a clean boolean (103 institutions PAL/TAL-exempt). A `/content/dam/` asset behind a JS page: fetch defensively |
| **CRICOS** | `data.gov.au` dataset `e5ae7059-…`, four CSVs — 1,554 providers | **CC-BY 2.5 AU** | monthly, **with XLSX snapshots back to July 2021** | enrol | 96% private. Membership is not a quality signal; `Institution Type` is. The snapshot archive answers "was this provider licensed when the student enrolled" — the one register that can |
| **TEQSA National Register** | `teqsa.gov.au/national-register` — **browser transport only** | unverified | irregular | award-own-degree | **144 of 219 providers are not self-accrediting.** Also publishes unsuccessful applications and three unregistered entities (published 2021-12-21, page updated 2024-01-16), with TEQSA's own disclaimer that it makes no breach finding |
| **NZQA** | `nzqa.govt.nz/providers/results.do`, **8 queries** (4 categories × signatory yes/no) reconstruct the mapping over 3,363 organisations | **CC-BY 4.0** | irregular | quality, enrol | Category and COP status are filters, not columns. Nine Category 3–4 providers may still recruit — two axes, one register |
| **UAE CAA** | one HTML table — 159 institutions | **unverified** (© asserted) | irregular | quality, enrol | 103 active / 55 inactive / 1 on probation, and **24 titles carry "(LICENSURE REVOKED)"** — the only register that keeps its graveyard published by name |
| **UAE KHDA** | `web.khda.gov.ae/en/Education-Directory/Higher-Education` — 34 free-zone providers | **unverified** | stars dated **2022** | quality | **The chain is missing its intermediate.** Fetch `http://secure.globalsign.com/cacert/gsrsaovsslca2018.crt` from the leaf's own AIA URI, append to the CA bundle, verify properly. **Never `verify=False`.** 18 of 34 unrated; carry the 2022 date on every star |
| **Korea IEQAS** | one page, no pagination — 184 certified, 43 "Excellent" | unverified | annual, **as-of 2026-03-03** | quality | Non-certification is itself a visa signal — certified universities get relaxed screening. Names print uppercase: an identity-resolution problem, not a data problem |
| **Japan MEXT** | `mext.go.jp/a_menu/koutou/ryugaku/1412692_00005.htm` — a page with a PDF companion | unverified | annual | quality | 改善指導対象校, with a published criterion: international withdrawals over **5%** in one year. **Two institutions** — Tokyo Fukushi (6.2%), Nagoya Management Junior College (7.4%), on April 2023–March 2024 data. Three consecutive years → 在籍管理非適正校, may no longer accept international students at all; that tier begins FY2027. **The designation date is a Japanese era year and was never converted** — read it off the page |
| **US Scorecard** | `Most-Recent-Cohorts-Institution.zip`, 23.5 MB, **no key** | **unverified** — US federal works are ordinarily public domain but the page was not read for a statement | annual (`Last-Modified` 2026-06-09) | facts, not gates (§3.4) | The REST API 403s without a key; the bulk file does not need one |
| **US DAPIP** | one `POST https://ope.ed.gov/dapip/api/downloadFiles/accreditationDataFiles` with `{"CSVChecked": true, "ExcelChecked": false}` → 3.6 MB zip | unverified | generated on request | quality | 44,954 institutions, 64,598 accreditation records, **89,532 accreditation actions with dates and justifications** — accreditation history including terminations. The host is `ope.ed.gov`, **not** `surveys.ope.ed.gov`; that mistake is what produced the earlier 404s. Probing is safe here: a 404 is a real 404 |
| **US SEVP** | `studyinthestates.dhs.gov/school-search`, Drupal view with GET filters, **browser transport only** | unverified | continuous | enrol | **No bulk export.** ~50 state-scoped queries, the same shape as NZQA's eight. Certification is **per campus** |
| **Ireland** | 27 named providers scraped from `qqi.ie/trusted-ireland-reports` | unverified | grows until end of 2026 | enrol | **Do not build on the ILEP** — frozen at 2025-06-20 and being retired. A stale clear is worse than no clear. **Ireland stays a consultant check** |

Two whole-table facts. **Four government hosts refuse a plain `curl` and answer a browser** —
`ice.gov` and `studyinthestates.dhs.gov` with a 403, `moj.go.jp/isa` with a 403 that was a user-agent
block, `teqsa.gov.au` with no response at all — and one (`jsj.moe.gov.cn`) resolves **IPv6-only**,
which an IPv4 worker cannot reach at all. That is a deployment constraint that would otherwise be
found in production, and it is why `transport` is a field on the config rather than a per-source
discovery. And
**seven of the fifteen routes carry no verified licence**; §7 is where that is dealt with rather
than left to whoever writes the adapter.

### 6.2 The signal that is not a row: what changed since last time

Leg A4 — a properly accredited institution losing its licence mid-degree — is answered by *diffing*,
not by storing history. The UK register publishes daily and the CAA and TEQSA publish their
revocations by name; CRICOS keeps 50 monthly snapshots. At ingest, compare against the superseded
snapshot and raise a `ConsultantResearchTask` when a listing an active student depends on moves from
`CLEAR`. An alert, not an archive: the product need is that somebody is told, and
`OfficialSourceSnapshot.supersedes` already holds the history for anyone who asks later.

## 7. Terms, and the one decision that overrides them

**Owner decision, 2026-08-31: anabin will be stored despite its Impressum.** The clause is not
ambiguous — it names *Einspeicherung, Verarbeitung bzw. Wiedergabe von Inhalten in Datenbanken*,
requires prior written consent, and permits only non-commercial personal copies. This design records
the decision, does not re-argue it, and carries two things forward:

- **Store the four gate fields only** (`nameShort`, `nameGerman`, `country.nameShort`,
  `institutionType.status.nameShort`) — about 2.5 MB for the whole corpus against ~120 MB fetched, of
  which 14% is HTML prose in `institutionType.comment` that no gate reads. Smaller, faster, and less
  of a content database.
- **Asking KMK for written consent is a work item** (§9), not a blocker.

For everything else the rule from the seed-source review stands unchanged: **an adapter is not
written for a host whose terms cannot be established — it becomes a `ConsultantResearchTask`.** That
is what put DAAD out of scope and it applies identically to the seven unverified routes above. The
two clean cases are the model: DEQAR's PDDL and the UK's OGL v3.0 need nothing but attribution.

## 8. Security and tenancy

**Register data is shared-catalog data, and the `ProgramCompetency` rule applies verbatim.** Every
tenant reads these tables, so writes are RLS-restricted to the `catalog_ingestion` role — the
migration shape is `apps/funding/migrations/0021_program_competency_rls.py`, and
`tests/tenancy/test_database_isolation.py::_SHARED_TABLES` gains the two new tables.

**But the cross-tenant hazard that rule exists for is absent here, and that is worth pinning rather
than assuming.** `ProgramCompetency` is dangerous because a model interprets a third party's page
into a table every tenant reads. **No model reads a register.** These are structured government files
parsed by field access. Pin it with a test in the shape of
`tests/concierge/test_roadmap.py::test_no_payment_or_portal_automation_call`: `apps/research/registers.py`
imports no LLM client, and nothing in the register path calls `extraction.py`. When somebody later
proposes "just have the model read the TEQSA page", that test is the argument.

Three residual hazards that are real:

- **A register is still third-party bytes.** `raw_value` is capped at 200 characters, is never
  rendered as markup, and is not a URL. Names go through the same escaping every catalog string does.
- **The KHDA CA-bundle fix must not degrade into `verify=False`.** It is one appended intermediate
  fetched from the leaf's own AIA URI; the fix is a bundle, and a code review that sees `verify=False`
  on this path should reject it.
- **No URL is register-supplied and then fetched.** The registers carry institution websites (CRICOS,
  anabin, CAA); those are leads for the discovery pipeline and go through `validate_public_url` like
  any other, never straight into `OfficialSource.canonical_url`.

## 9. How a country is added

The deliverable this design exists to produce. Six steps, in order, and step 2 is the one that gets
skipped.

1. **Say which axes the country's registers answer.** Not "does it have a register" — which of the
   five. Most countries answer one or two, and which one changes what the screen may claim. A country
   answering none is a valid outcome: China as a destination, Azerbaijan for recognition.
2. **Recon before designing against it**, in the format of the four recon docs: access route, HTTP
   status, byte count, row count, authentication, cadence, **terms**, and *what an absence from it
   means*. Measured, not described — every wrong belief in this series came from a page rather than a
   file, and four of them were corrected by fetching the file.
3. **Resolve the terms.** Open licence → build. Unverified → establish it or the country becomes a
   consultant check. This is a gate, not a note.
4. **Fill in one `Register` config.** If the country needs code rather than configuration, that is a
   signal the adapter shape is wrong, not that the country is special — SEVP's paginated walk and
   NZQA's eight queries both fit as a `parse` callable.
5. **Measure coverage and write the `RegisterCoverage` rows**, then decide that country's
   negative-rendering policy from the rate. Below roughly 50% — England, Italy, Ukraine — show no
   negatives at all.
6. **Record what is still unknown**, by name, in the recon doc. Every file in this series ends with a
   "not established here" section, and that is why the gaps were findable at all.

## 10. Work items

In dependency order. The first three are the design's own prerequisites.

1. **`Institution.ror_id`, `kind`, `parent`** — one migration, shared with the money branch's
   increment 4. Nothing else here is safe to build first.
2. **`RegisterListing` + `RegisterCoverage` + RLS migration + the no-LLM test.**
3. **DEQAR adapter.** PDDL, daily, largest corpus, and it delivers the ROR crosswalk that item 1
   wants. The reference implementation for the other ten.
4. **UK sponsor register** — cheapest real signal in the whole screen: OGL, daily, 1,308 rows, three
   axes' worth of information in seven columns.
5. **US Scorecard + DAPIP.** Selectivity for 1,910 institutions and accreditation history for 44,954,
   in two files. Scorecard writes evidence claims (§3.4), DAPIP writes listings.
6. **CRICOS, TEQSA, NZQA, DLI** — the four destinations DEQAR cannot see at all (US 4 screenable of
   286 listed, Canada 3, Australia 2, New Zealand 0). Without these those destinations have no gate.
7. **anabin**, on the §7 decision, storing four fields.
8. **CAA, KHDA, IEQAS, MEXT.**
9. **YÖK, primary-sourced.** `yok.gov.tr/ogrenci` 404s; `denklik.yok.gov.tr` responds 200 and was
   never explored. **None of the 41 institutions and none of the named sub-units may be encoded from
   the Turkish news and consultancy sites they currently come from.** The structural finding is
   usable; the list is not. Until this lands, `kind=UNIT` has no rows — which is fine, and is not a
   reason to drop the column.
10. **Malaysia (MQA)** — unexamined and a plausible market. Run §9 against it end to end; it is also
    the test of whether §9 is a real runbook.
11. **Smaller and dated:** the OfS degree-awarding-powers CSV (route currently an email address);
    Ireland's TrustEd list, re-read when the ILEP ceases at the end of 2026; whether UQAIB has
    published a round after 2022; the SEVP paginated walk; asking KMK for anabin consent.

## 11. Decisions recorded, not re-argued

- **Russia is excluded as a study destination and retained as a scholarship funder.** Visa and
  political risk on top of the QA gap — a business judgement, not something the data decides. Russian
  institutions never enter the screen; Russian schemes stay in `PROMPT-government-inbound-sweep.md`.
- **anabin is stored** (§7).
- **No single launch country.** Cover every country the screen can reach, one at a time. The Germany
  convergence in both research runs came from the brief's affordability framing, not from the
  mechanism: the screen returns **5,027 institutions across 131 countries and Germany is 9% of them,
  fourth behind Spain's 1,018**.
- **Germany is the only tuition-free public floor**, and now by measurement rather than by absence of
  checking — Norway was closed negatively on `studyinnorway.no` ("must normally pay tuition fees"),
  and its NOK 170,368/year permit requirement alone exceeds Germany's €11,904 blocked account.

## 12. Not established here

- **Whether any market besides Türkiye excludes sub-institutional units.** One was checked and it was
  the one that turned out to matter. `kind=UNIT` is designed for a sample of one.
- **The threshold at which a coverage rate suppresses negatives.** §9 step 5 says roughly 50%; the
  number has not been tested against anything.
- **Whether the `Register` config shape survives contact with SEVP and Ireland**, the two routes that
  are walks rather than files.
- **How a listing is matched to an `Institution` when `ror_id` is blank**, which is most of the world
  outside DEQAR. Name matching is the fallback and it is the known-hard part; the US
  `ACCREDAGENCY`-to-accreditor join is the same problem in miniature and is a good first test.
- **Licences for seven of the fifteen routes** (§6.1), each of which is a §9 step-3 gate rather than
  an engineering task.
