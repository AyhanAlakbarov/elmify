# Discovery audit, 2026-09-15: coverage, and the four dashboard fields

Status: audit note. Records what the discovery engine finds today, whether it can find "all possible
fundings", and where nationality, degree stage, GPA and deadline stand — in code, in a spec, or
nowhere. Amendments it produces: a dated §4.6 in
`specs/2026-09-13-institution-programme-funding-search-design.md`, and a dated block under P1-9 in
`phased requirements.md`. Every claim below was checked against the files named; nothing is inferred
from a docstring alone.

## 1. Does the engine find all possible fundings? No — and it cannot yet say what it misses.

**Wired today (two sources).** `apps/research/pipeline.py::default_sources` registers exactly the
EACEA Erasmus Mundus seed catalogue (`seeds.py::EACEA_ERASMUS_MUNDUS`, always on) and
`search.py::EntityExpansionSource` (search → organisation → sitemap → `FUNDING_PATH_TERMS` triage),
which runs only when `SEARCH_API_KEY` is set. `SearchSource` alone is deliberately not a source: a
live run returned 8 of 10 content farms marked as able to support a claim.

**Built or specified, not wired.** The DAAD International Programmes API (1,571 English-taught
master's; terms unverified, deliberately not written), `GrantDatabaseSource`, `OrganisationFrame`
(ROR), `RegistrySource`, `CertificateTransparencySource` — none of those modules exist. The funding
reader with its own vocabulary and three-run agreement gate (§4.3 of the 2026-09-13 spec) is not
built. The inbound government census is a human research method with no CSV on disk. Instrument mode
(MEXT, GKS, CSC, Chevening, Türkiye Bursları as national schemes) has no `DiscoveryQuery.mode`. The
DEQAR / WHED registers are wired but feed the institution safety screen, not lead discovery.

**The load-bearing gap.** `run_discovery` is reachable only from `manage.py discover`. The
student-facing path (`research/dispatch.py` → SQS → `services.py::handle_research_message`) still
fetches the placeholder `https://official.example.test/program.json`. Discovery and recommendation
are not connected. The 2026-08-27 design records this as intended ("later"); it is now the item on
which every dashboard column depends.

**Recorded coverage limits, all measured.** Institution sitemaps are a weak spine (2 of 5 usable);
path triage cannot see programme-attached money stated off a funding-shaped URL (~45% of the best
automatic-on-admission awards); sitemaps cannot see a separate graduate-school subdomain; search has
no denominator and the union of four providers over 128 queries added zero recall; no supplier exists
for Japan or China; Opintopolku, DAAD, Hochschulkompass and GEPRIS are blocked by terms;
campuschina.org and EACEA detail pages by technique. The end-to-end yield of the one wired source:
169 consortium sites → 494 leads → 9 catalog rows. The coverage instrument the design relies on
(no-floor and underspend rates per destination × discipline) does not exist, so coverage is neither
achieved nor measurable today.

**One implementation drift worth fixing.** `DiscoveryQuery.country_code` is required and reaches the
search query text (`search.py::query_text`), while the 2026-08-28 funding-led design decided "country
is an output, never a filter". `discover.py` makes `--country` mandatory. Either the design or the
code is wrong; the design's reasoning still holds.

## 2. The four fields: where each one is

The structural fact: `research/catalog.py::write_catalog_entry` persists extracted facts as
free-text strings in `OfficialEvidenceClaim.claim` tagged with a `ClaimClass`. Only institution,
programme name, country, degree level, teaching languages and duration become columns. Everything
`claim_rows` does not emit is extracted, paid for, and dropped.

| Field | Extracted from the page? | Emitted to the catalog? | Stored as a column? | Student side |
|---|---|---|---|---|
| Nationality / citizenship eligibility | yes — `NationalityEligibilityClaim` (`BLOC` / `COUNTRY_LIST` / `BILATERAL_PAIR` / `OPEN`, countries, quota) | **no** — `claim_rows` never emits it; only a free-text `ELIGIBILITY` criterion survives | **no** — `BenefitRule.Scope` has no `NATIONALITY`, though `evaluation.BenefitScope` assumes one | `StudentProfileSnapshot.nationality`, ISO-validated |
| Degree stage — the funding's level | n/a | n/a | `Program.degree_level`, **`MASTER` only**, DB-checked; a scholarship spanning master's + PhD cannot be represented | — |
| Degree stage — what the applicant must hold | only as `EligibilityCriterionClaim(kind="DEGREE")` prose | as prose | **no** | `AcademicRecord` |
| GPA threshold and scale | yes — `GradeThresholdClaim(minimum, scale)` "in the target's own scale, never converted"; `GradeEquivalenceRuleClaim` quotes the target's own conversion rule | **no** — neither is emitted | **no** — no `minimum_grade`/`grade_scale`; `BenefitRule.ConditionType` has no `GRADE`, so a grade bar cannot close a route | `AcademicRecord.grade` + `grading_scale`; CV `grade_native`/`grade_scale`/`grade_conversion` |
| Application deadline / intake / cycle | yes — `KeyDateClaim(kind, on, decentralised)` with `INTAKE_START`; the year-fabrication guard drops unreadable parses | yes — **as a string** `"APPLICATION_DEADLINE: 2026-12-01 — <quote>"` | **no** date column anywhere; no `cycle_year`/`opens`/`closes` | — |

Consumers already exist and are unfed: `CandidateFacts.excluded_nationalities`,
`application_deadline`, `deadline_is_viable` drive the nationality hard gate and the
scholarship-before-fee ordering in `funding/pack.py` — and **nothing in the codebase constructs a
`CandidateFacts`**. There is no catalog → candidate resolver.

**GPA conversion is absent on purpose and stays absent.** `CLAUDE.md`: grades are stored as awarded,
with the scale, never converted. The dashboard therefore shows the requirement in the target's own
scale beside the student's grade in theirs — `2.5 (German 1–5)` next to `3.4 (US 4.0)` — with the
target's own quoted equivalence rule when the page states one. There is no normalised number to
sort on, and building one is a modelling decision for when there is data to take it against.

## 3. What a dashboard row needs, in order of cost

1. **Emit what is already extracted** (cheap, one file): `claim_rows` gains rows for
   `nationality_eligibility`, `published_minimum_grade` and `grade_equivalence_rules`. Prose, but
   present, and it stops paying for facts it throws away.
2. **Structured columns** (the real fix; §4.6 amendment):
   - `FundingOpportunity.degree_levels` (multi-value: `MASTER`, `PHD`, …) — a scholarship's level
     is not the programme's; `Program.degree_level` stays `MASTER`.
   - `BenefitRule.Scope.NATIONALITY` plus a country-list table with `list_source` (`VERBATIM` or
     `BLOC:<list>@<version>`), matching the census CSV shape already specified.
   - `BenefitRule.ConditionType.GRADE` carrying `minimum`, `scale`, and the quoted equivalence rule.
   - `FundingOpportunity` / `Program` key dates: `kind`, `on` (nullable), `decentralised`,
     `unreadable_quote` — a **three-state** render (date / decentralised / stated-but-unread), because
     32% of parsed years were fabricated and a silent null hides that.
   - `cycle_year`, `opens`, `closes`, `status` (`LIVE`/`CLOSED`/`SUSPENDED`/`UNKNOWN`) as the census
     already defines them.
   - A per-claim-class freshness window enforced on read (deadlines 30 d), so a stale deadline is
     rendered stale, not current.
3. **The producer**: a catalog → `CandidateFacts` resolver, and `run_discovery` wired to the
   recommendation run. Without this a column has rows from one seed catalogue and nothing else.
4. **`EXPLAINABLE_FIELDS`** (`funding/explanations.py`) must admit `key_dates`,
   `nationality_eligibility` and `published_minimum_grade`, or the explanation hides three of four.
5. **A renderer.** `templates/` does not exist; every dashboard view returns a context dict into a
   test stub. The column is greenfield presentation work under `spec-to-site-orchestrator`.

## 4. What this note does not decide

Whether to build the funding reader before or after the structured columns; whether Japan and China
get a supplier or a manual census; and the pricing of the DAAD API terms question. Those belong to the
2026-09-13 spec's phase plan.
