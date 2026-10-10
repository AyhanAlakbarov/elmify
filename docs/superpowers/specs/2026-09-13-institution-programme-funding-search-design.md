# Institution and programme funding search — finding the money attached to a programme

**Date:** 2026-09-13. **Status:** direction approved in conversation (approach A as a
build-and-measure loop, the seven lead sources, three defaults accepted); awaiting review of this
written form. **Sub-project 5** of the funding-search programme; sub-project 1 (shared data format)
and 2 (country census, `2026-09-13-inbound-government-search-design.md`) are its neighbours.

**Builds on** `2026-08-28-funding-led-discovery-design.md` (tiers 0–3, `LeadSource`, budgets,
access-terms policy) and `2026-09-12-program-page-reader-design.md` (`reader.py`). It changes the
supplier of programme pages and adds a funding reader; it does not replace either design.

## 1. Why this exists

Seven kinds of funding live at institution or programme level (`I1`–`I7` in the agreed taxonomy):
university-wide awards and fee waivers including automatic-on-admission ones; **funding attached to
one programme**; stipends and assistantships; lab and research pathways; funded dual and joint
degrees; university relocation, housing and travel support; paid placements built into a programme.
Together they are where the hidden gems are, and the research programme has never reached them:

- The leading-institutions run sampled **15–20 institutions** of thousands (ROR counts 2,106 in
  India, 239 in Türkiye), reported Pakistan absent wrongly, and found no dual degree outside
  Azerbaijan.
- The discovery engine's last full run wrote **zero catalog rows** — every invariant held and
  nothing was found — because no single page carries a whole programme row
  (`2026-08-30-discovery-shadow-run-3.md`).
- Path triage cannot see programme-attached money. `FUNDING_PATH_TERMS`
  (`apps/research/search.py:138`) keeps a URL only if it *looks* like funding, so a programme page
  whose body says *"all admitted international students receive a 50% tuition waiver"* is never
  fetched. About **45%** of the best automatic-on-admission awards state their terms off any
  funding-shaped URL — in `/admission/graduate`, in a PDF brochure, or behind a search tool that
  works only during the application window (`2026-08-29-leading-institutions-synthesis.md` §4.1).
  Widening the regex made results worse when tried (0 vs 128 matches on Sorbonne; housing and
  parental-leave pages on TUM).
- Sitemaps are a weak spine: 2 of 5 major universities exposed programme pages that way, and a
  funded graduate school on its own subdomain is invisible to the parent's sitemap.

## 2. What "best" means here

For a fixed yearly budget, the approach that **maximises the number of verified funded programmes
we can show a student where the catalog is thin, while always knowing what it has not looked at.**
Six tests, in order:

1. Recall of the hidden kind — money stated in one paragraph on one programme page.
2. Every claim citable: official page, quoted sentence, date (`phased requirements.md` P1-4).
3. Coverage measured, not assumed: unvisited is `UNKNOWN`, never "no funding".
4. Fresh every cycle at low marginal cost.
5. Legitimate: honest identification, robots and terms as the discovery design treats them, no
   evasion beyond what `CLAUDE.md` now permits (Cloudflare interstitials on public official pages).
6. Aimable and reusable: pointed at thin destination × discipline cells; eligibility recorded for
   every nationality, so a new market is a filter.

A crawler is the only option that passes test 3, because it is the only one with a denominator.
Search cannot say what it never ranked; hand research cannot reach the long tail. The alternatives
and the reasoning are recorded in the 2026-09-13 conversation and summarised in §12.

## 3. Scope

**In:** any money controlled or channelled by an institution, faculty, department or programme
that lowers the cost of a full master's degree for an international student — its own funds,
state funds it allocates (Denmark's government scholarships), industry money attached to a
programme, research-project posts open to master's students, funded places in dual/joint degrees,
paid placements, relocation/housing/travel support. Worldwide; country is an output, never a filter
(discovery design, "Scope"). Teaching language is a hard filter at ranking, not at discovery
(P1 §7.2).

**Recorded as excluded, with a reason:** non-degree and exchange awards, doctoral-only funding,
undergraduate-only, closed schemes, awards stated only on an aggregator.

**Out, handled by other sub-projects:** government schemes (sub-project 2), bloc/foundation/company
funders (3), origin-market funding (4). A programme page that *mentions* a government scheme is a
pointer to sub-project 2's row, not a new row here.

## 4. Architecture — one loop, four lead routes, one reader

```
lead routes ──► programme pages ──► funding reader ──► attachment + agreement ──► catalog
     ▲                                                                          │
     └──────────── measurement (known answers, overlap, per-route tally) ◄──────┘
```

Every stage is a `LeadSource` or a pure function plugged into the existing pipeline
(`apps/research/pipeline.py::default_sources`, `run_discovery`); nothing here bypasses `RunBudget`,
`PacedFetch`/`DomainLease`, `validate_public_url`, `persist_snapshot` or the evidence bucket.

### 4.1 Lead routes (what supplies programme pages)

| Route | Source | Yields | Terms |
|---|---|---|---|
| **R1 registers** | Official programme registers with URLs, where a country publishes one: Australia (CRICOS), France (ONISEP open data), Italy (Universitaly), Spain (RUCT), Netherlands (Studiekeuze), Poland (RAD-on), Korea (data.go.kr register), Finland (konfo API) | Complete programme list for that country | Checked per register before use; recorded in the country census as two new fields (`programme_register_url`, `programme_register_terms`) |
| **R2 institution frame + guided navigation** | ROR (CC0) gives every institution and its website; Common Crawl's index and certificate-transparency logs (crt.sh) give the host's URLs and subdomains; a model reads the homepage navigation to find the programme index (≤ 3 pages), the index yields programme pages | Programme pages where no register exists; subdomain graduate schools | ROR and Common Crawl free; crt.sh passive; per-site robots and terms as today |
| **R3 funder-side seeds** | Grant databases (360Giving, KAKEN — open licences), the EACEA Erasmus Mundus listing (169 leads, already wired), EIT-labelled programmes, industry chairs | Externally funded programmes, often before the university's page exists | Already designed as tier 0 |
| **R4 tip-offs** | Counsellors at agencies, students, the owner; Tavily English queries per destination × discipline as a bounded source for institutions with neither register nor readable navigation | Leads, never facts | Tavily: URL only is stored (live-search synthesis); human tips graded `LEAD` |

`FUNDING_PATH_TERMS` triage keeps its job for **central** scholarship pages (institution-wide
awards). It stops being the only route to a funding claim.

### 4.2 The programme row (the upstream fix)

A programme's catalog row is assembled from **several pages of the same origin**: the programme
page, its fees/funding tab, its admission page, and one PDF brochure if linked from the programme
page. `pipeline._HeldPage` already holds pages across a run; the change is that extraction runs
over the *set* for one programme, not one page. Identity comes from the register (R1) or the
programme URL (R2–R4); the origin check `require_same_origin` applies to every page in the set.

### 4.3 The funding reader

A second extractor over `reader.readable_text` output, with **its own vocabulary** — `CLAUDE.md`
forbids widening the admission one. It reads the programme page set plus the institution's central
scholarship pages and returns, per statement, the quoted sentence and:

- `scope`: `PROGRAM` (this programme only), `PROGRAMS` (a named subset), `INSTITUTION`, or
  `POINTER` (mentions a scheme owned elsewhere — government, bloc, foundation).
- `nationality_rule`: `NationalityEligibilityClaim` shape (`BLOC` / `COUNTRY_LIST` /
  `BILATERAL_PAIR` / `OPEN`) plus `internationals_included: yes / no / unstated`.
- `route`: `FundingTrackClaim.initiation` values, with `AUTOMATIC_ON_ADMISSION` first-class.
- Cost labels shared with the census: `tuition`, `living`, `extras`, `money_form`
  (`GRANT` / `FEE_WAIVER` / `SUBSIDY` / `LOAN` / `FORGIVABLE_LOAN` / `MIXED`), `obligation`.
- `kind`: `I1`–`I7`.

Every quote is verified against the page text (`reader.verified_statements`); a statement not on the
page is dropped and counted. Rate-limited per programme through `rate_limited` as
`read_program_page` is, and the model call follows the LLM baseline (data labelled as data,
`extra="forbid"`, capped tokens, `store=False`).

### 4.4 Attachment and agreement

Storage already refuses mis-attachment: `funding_opportunity_scope_shape_valid` admits exactly one
anchor per `OpportunityScope`, and `FundingOpportunity.programs` carries a named subset. What the
reader must decide is *which* scope a sentence describes, and that decision is where models
disagree. So, as the CV format work settled (`2026-09-13-format-decision-guarantee-design.md`):

- The reader runs **three times** per programme page set, in three phrasings.
- A funding row is written with **evidence strength `DIRECT`** (P1-3, student-facing) only when all
  three readings agree on `scope`, `nationality_rule.shape`, `internationals_included`, `route` and
  `money_form`, and the quote is on the page.
- Two of three agreeing writes the row with the strength the page supports but flagged
  `unagreed`, with the disagreement recorded, and it is **not served**; less than that abstains,
  visibly, as an `ECOSYSTEM_CLUE` row — never silence. P1-3 would allow `COMPETITIVE` rows to face
  students; this family gates on `DIRECT` plus agreement because a wrong funding claim reaches a
  student directly.
- A `POINTER` statement writes no funding row; it creates a cross-reference to the sub-project 2/3
  track if one exists, else a `LEAD` for that sub-project.

Only `DIRECT` rows reach a student. The phase gate's consultant review remains on top.

### 4.5 Catalog writes

Rows land in `FundingOpportunity` / `BenefitRule` / `FundingOpportunityEvidenceClaim` through the
shared-catalog write path, under the `catalog_ingestion` role. That role does not exist in
`config/settings/database.py` (`DATABASE_ROLE` accepts `runtime|migration`); adding it is a
prerequisite shared with the register adapters, not a task of this design. Until it exists, runs
archive snapshots and write nothing — the same shape the register rehearsal used.

### 4.6 Dashboard eligibility columns (amendment 2026-09-15)

Source: `docs/superpowers/2026-09-15-discovery-coverage-and-eligibility-audit.md`, which measured
that the extractor already reads nationality shape, grade threshold with scale, the target's own
grade-equivalence rule and typed key dates — and that `catalog.py::claim_rows` drops the first three
and stringifies the fourth. P1-9's 2026-09-15 amendment requires all four as structured fields. So the
catalog write path of this design carries, in addition to §4.5's rows:

- `FundingOpportunity.degree_levels` — multi-valued (`MASTER`, `PHD`, …). A scholarship's level is
  not the programme's; `Program.degree_level` stays `MASTER`.
- `BenefitRule.Scope.NATIONALITY` with a country-list table carrying `status`
  (`ELIGIBLE`/`EXCLUDED`/`PRIORITY`) and `list_source` (`VERBATIM` or `BLOC:<list>@<version>`) — the
  census's `inbound-eligibility.csv` shape, so the CSV and the table are one schema.
- `BenefitRule.ConditionType.GRADE` with `minimum`, `scale` and the quoted equivalence rule. No
  conversion, per `CLAUDE.md`.
- Key dates on the opportunity and the programme: `kind` (`APPLICATION_DEADLINE`, `INTAKE_START`,
  `DECISION_DATE`, `OFFER_REQUIRED_BY`), `on` (nullable), `decentralised`, `unreadable_quote`; plus
  `cycle_year`, `opens`, `closes`, `status`. Three render states, never a silent null.
- A per-claim-class freshness window enforced on read (deadlines 30 days), so a stale value renders
  stale.

Two prerequisites this section does not build but names: `run_discovery` wired to the recommendation
run (today the student path fetches a placeholder), and a catalog → `CandidateFacts` resolver
(today nothing constructs one). `funding/explanations.py::EXPLAINABLE_FIELDS` must admit
`key_dates`, `nationality_eligibility` and `published_minimum_grade`. Until the columns exist,
`claim_rows` should at least emit the three dropped claims as prose so the facts stop being paid for
and thrown away — a one-file change independent of this design.

## 5. Aiming and order

The optimizer's coverage signal (no-floor rate and underspend rate per destination × discipline,
discovery design "Coverage") is the long-run aiming instrument. It does not exist at launch: no
catalog, no students. Until packs exist, the crawl is ordered by three priors, and the order is a
priority, never a filter:

1. **Where Azerbaijani and Turkish students actually go** — UNESCO UIS outbound-flow tables for AZ
   and TR, fetched and stored once per year with their date.
2. **The eight researched corridors** (`2026-08-27-corridor-mechanics-synthesis.md`).
3. **Fee-charging destinations where universities control waivers** — UK, Netherlands, Sweden,
   Ireland, Australia, Canada, US, Italy. This is the owner-accepted default prior; the known-answer
   set (§7) tests it and the order changes if it is wrong.

Every destination × discipline cell reports `visited / partial / unknown` from the first run.

## 6. Freshness

`persist_snapshot` records `content_sha256`; the reader is skipped for an unchanged page, as
`read_program_page` already does. Yearly re-fetch of every known programme page set costs fetches
only; model calls occur where text changed. Each row carries `cycle_year` and `checked_on`; a row
whose page has not been re-read within the freshness window for its claim class (P1 §7.1) is not
served.

## 7. Measurement — recall is a number, not a hope

1. **Known-answer set.** ~50 real programme-attached awards across the §5 destinations, built by two
   blind deep-research runs (the `PROMPT-inbound-deep-batch.md` method adapted to programmes) plus
   verification against the official page. Stored as `docs/research/programme-funding-known-answers.csv`
   (`institution_ror`, `programme_url`, `kind`, `pattern`, `verified_on`). The crawl must reach each
   through a route with no scheme or programme name in any query or seed; a hit whose trail names it
   fails. Statuses as in the census: `PENDING / MISSED / NOT_GENERIC / NAMED_QUERY_ONLY / PASS`.
2. **Reader overlap.** Per destination cell, the crawl, run A and run B are three independent readers.
   Rows found by one reader only are listed; a cell with many single-reader rows is not saturated
   and gets another pass.
3. **Per-route tally.** `found_via` on every row (`R1`, `R2`, `R3`, `R4_TIP`, `R4_SEARCH`, `RUN_A`, `RUN_B`). A route
   that finds nothing the others miss across two destinations is switched off; a row found by one
   route only flags that route as load-bearing for similar institutions.
4. **Stopping rule.** A destination is saturated when a full pass adds no row that two other readers
   missed. Until then it stays `partial`.
5. **Silence is loud.** A page set that yields no text (JavaScript shell, image-only PDF) is recorded
   as `unreadable`, never as "no funding" — the `UnreadableSource` path already exists.

The known-answer set is also the first real catalog content, so building the yardstick is not
overhead.

## 8. Legitimacy, security, cost

- **Terms.** Robots and terms as the discovery design's retrieval policy states; per-domain leases
  (`DomainLease`, `LEASE_INTERVAL`); honest `User-Agent`. `solve_cloudflare` per `CLAUDE.md`: off in
  the product by default, per-source enable; the research machine may use it on official pages.
  No paid solving service; a CAPTCHA that needs a human is a `ConsultantResearchTask`.
- **Not built:** recursive spiders, search-result scraping, aggregator scraping as a spine, proxies,
  stealth fingerprinting — the discovery design's list stands.
- **Browser tier.** JavaScript-only sites go through `render_via_browser_service`.
  `BrowserDesiredCount` is 0 and `MaxValue` is 1; the owner accepted turning it on when such sites
  block coverage. It renders one page at a time, so those sites are the wall-clock bottleneck, not
  the code.
- **Untrusted content.** Page text is data. A page instructing the reader is recorded as text; the
  reader prompt labels the page as data and never as instructions.
- **Cost.** Roughly one to two cents of model calls per *changed* page set (three reads of ≤ 24,000
  characters each); fetches negligible. A first pass over the §5 destinations is hundreds to a few
  thousand dollars; yearly refreshes far less. `RunBudget` caps every run; the per-programme
  limiter caps abuse.

## 9. Data

Rows are catalog rows (`FundingOpportunity` and friends) — not CSVs — because this sub-project
writes the product's own database. Two CSVs support it under `docs/research/`:
`programme-funding-known-answers.csv` (§7.1) and `programme-funding-coverage.csv` (destination ×
discipline × `visited/partial/unknown` × date), regenerated by a management command. The
`found_via` set and cost labels use the same vocabulary as sub-project 1's shared format, so a
census row and a catalog row are comparable.

## 10. Increments

Each increment ships something measurable on its own.

1. **Funding from pages already fetched.** The funding reader runs over programme pages the
   pipeline already retrieves (EACEA's 169 consortium sites first). No new fetch. Measures the
   reader, not the crawl.
2. **Programme row from a page set** (§4.2) — the upstream fix that unblocked nothing last time.
3. **Known-answer set** (two deep-research runs, owner-launched) and the measurement harness.
4. **R1 registers** for destinations whose terms pass, starting with the §5 order.
5. **R2 frame + navigation**, with Common Crawl and crt.sh for URLs and subdomains.
6. **R3 seeds beyond EACEA** (360Giving, KAKEN, EIT) and **R4** (tips table; Tavily bounded).
7. **Coverage report and stopping rule**; first yearly refresh.

Increments 1–3 are the first weeks; 4–7 follow the measurement.

## 11. Testing

- Reader: fixtures of real programme pages (fetched once, stored) covering each `kind`, each
  `scope`, a `POINTER`, a negation ("no scholarships are offered for this programme"), an
  internationals-excluded award, and a JavaScript shell; a test that a quote absent from the page is
  dropped and counted.
- Agreement: three scripted readings that agree → `DIRECT`; two → internal; one → `ECOSYSTEM_CLUE`;
  a `POINTER` never writes a funding row.
- Attachment: the existing check constraint tests plus one per scope value.
- Measurement: known-answer statuses on synthetic logs, per-route tally, stopping rule.
- Live (`-m live`): one real register read, one real navigation, one real page set, one known
  answer found blind.
- Recall itself is reported, not asserted: the known-answer pass rate is printed by the command and
  recorded per run; no test hard-codes a rate.

## 12. Alternatives considered

- **Search-led (Tavily per institution and field).** Cheap, no crawl. Recall is whatever the index
  ranks; a paragraph on a low-traffic programme page is what an index buries; no denominator, so
  coverage cannot be measured. Kept as a bounded R4 source.
- **Research- and human-led.** Right for the yardstick and for blocked cells; cannot reach the long
  tail (15–20 of 2,000 institutions last time) and goes stale within a year.
- **Staged: measure before building.** Proposed and withdrawn: with build cost measured in weeks,
  the yardstick and the measurement are calibration inside the loop, not a gate before it.

## 13. Open items

- Terms and master's coverage of each R1 register — a census field, resolved per country.
- Whether Common Crawl's index lists subdomains well enough to replace crt.sh, or both are needed.
- The `catalog_ingestion` role (shared prerequisite).
- Whether the fee-charging prior holds — answered by the known-answer set.
- OCR for image-only PDFs: not built; recorded as `unreadable`.
