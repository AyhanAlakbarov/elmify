# Inbound government funding — a search that does not miss

**Date:** 2026-09-13. **Status:** approved in conversation, section by section; awaiting review of this
written form. **Supersedes** `docs/superpowers/research/PROMPT-government-inbound-sweep.md` as the method
(that prompt's rules survive inside §5).

## 1. Why this exists

Two deep-research runs and a verification pass on the 58-country inbound prompt
(`docs/superpowers/research/2026-09-13-government-inbound-{review-1,review-2,verification,synthesis}.md`)
produced useful rows and a clear record of how a search misses things:

1. **Several countries per query.** The best-known country filled the results and the others looked
   empty. Singapore, Hong Kong, Luxembourg and Denmark were reported "nothing found" and all run
   government schemes for foreign students.
2. **Searching by label.** Schemes are called Tuition Grant, Service Obligation Scheme, Master Mind,
   Guillaume Dupaix — rarely "government scholarship".
3. **Funder blind spots.** State money handed out by universities (Denmark), aid agencies (JICA, Qatar Fund
   for Development, CyprusAid), foreign ministries, regional governments (Bavaria, Québec, Flanders).
4. **Routes outside quota documents.** Russia's equal-rights budget places for CIS citizens never appear
   in the quota a scheme search walks.
5. **Descent and residence keys** are invisible to a nationality search (EPOS is keyed on residence).
6. **Per-country numbers live on the sending side** (Pakistan's HEC publishes its 3 Heydar Aliyev places).
7. **The corpus was not read first.** Five "new" schemes were already on disk.
8. **Scope slips.** An eight-month exchange recorded as a master's scholarship.
9. **A fixed country list** omitted Saudi Arabia, Norway, Taiwan, Thailand, Egypt, Morocco, Brazil, Mexico,
   Chile, Kyrgyzstan and Belarus before anyone looked.

The design below is built to defeat each of these, and to measure whether it did.

## 2. Scope

**An opportunity is any government money that lowers the cost of a full master's degree for a
foreign student in the funding country** — full scholarships, partial stipends, fee waivers, subsidies
carrying a work or return bond, state money allocated by universities, sub-national governments and
state development agencies.

- **In:** national and sub-national governments; their ministries, agencies and development funds;
  state budget lines allocated through universities *where the page names government funding*.
- **Recorded as excluded, with a reason** (so no one searches for them again): exchange and
  non-degree study, doctoral-only, undergraduate-only, university awards from the university's own
  funds (including state-owned universities' own awards, e.g. Khalifa University), closed schemes.
- **Out, handled elsewhere:** a government funding its own citizens abroad (outbound prompt);
  intergovernmental and bloc funders such as ADB, IsDB, Erasmus Mundus (nationality-keyed research);
  corporate and foundation money (`PROMPT-industrial-sponsorship.md`).

**Country universe:** every UN member state plus territories with their own higher-education system
and scholarship bodies (Taiwan, Hong Kong, Macao, Palestine, Kosovo) — about 200. No country is dropped
before stage 1 has looked at it.

## 3. Data — four CSV files in `docs/research/`

The CSVs are the single source of truth; syntheses explain them but never hold facts the CSVs lack.
Quoting follows the existing catalogs (`cv-style-rules.csv`): every field double-quoted.

### 3.1 `inbound-country-census.csv` — one row per country

| Column | Values |
|---|---|
| `country_iso` | ISO 3166-1 alpha-2 (territories: their ISO code) |
| `country` | English short name |
| `verdict` | `YES` / `NO` / `UNKNOWN` |
| `sources_checked` | the checklist step IDs actually completed (§4.2), e.g. `S1;S2;S3;S4;S5` |
| `basis` | quote or URL behind the verdict |
| `regional_tier` | `NOT_APPLICABLE` (education is not a regional competence) / `CHECKED_NONE` / `CHECKED_FOUND` / `NOT_CHECKED` |
| `checked_on` | ISO date |

**`NO` is allowed only when** every applicable step was completed with no find, **or** an official page
states there is none (Study in Finland: "there are no governmental scholarships available"). Anything
less is `UNKNOWN`. `basis` for an exhaustive `NO` lists the steps; for a stated `NO` it quotes the page.

### 3.2 `inbound-opportunities.csv` — one row per track

| Group | Columns |
|---|---|
| Identity | `track_id` (`<ISO>-<slug>-<track>`), `country_iso`, `subnational_unit` (blank = national), `scheme_name`, `scheme_name_native`, `track` |
| Funder | `funder_body`, `funder_type`: `EDUCATION_MINISTRY` / `FOREIGN_MINISTRY` / `DEVELOPMENT_AGENCY` / `SCHOLARSHIP_AGENCY` / `DIASPORA_AGENCY` / `REGIONAL_GOVERNMENT` / `STATE_FUNDS_VIA_UNIVERSITY` |
| Degree | `full_masters`: `yes` / `no`; `exclusion_reason` (required when `no`) |
| Eligibility keys | `eligibility_keys`: `;`-separated set of `CITIZENSHIP` / `RESIDENCE` / `DESCENT` / `REGION` / `AFFINITY` / `OPEN`; `keys_combinator`: `AND` / `OR`; `eligibility_quote` |
| General conditions | `age_limit`, `work_experience`, `prior_degree_and_grade`, `language_requirement`, `field_restriction`, `not_previously_in_host` (`yes`/`no`/`unstated`), `home_nomination_required` (`yes`/`no`/`varies_by_country`) |
| Route | `route`: `DIRECT` / `NOMINATED_HOME_GOVERNMENT` / `NOMINATED_UNIVERSITY` / `HYBRID` / `AUTOMATIC_ON_ADMISSION`; `route_quote` |
| Cost | `tuition`: `none`/`partial`/`full`; `living`: `none`/`partial`/`full`; `extras`: `;`-set of `travel`/`insurance`/`housing`/`language_year`/`visa`; `amount_text` (verbatim, with currency and period); `duration`: `whole_programme`/`fixed_months`/`yearly_renewable`; `money_form`: `GRANT`/`FEE_WAIVER`/`SUBSIDY`/`LOAN`/`FORGIVABLE_LOAN`/`MIXED` |
| Obligation | `obligation`: `;`-set of `none`/`return_home`/`work_in_host`/`serve_funder`/`repay_on_breach`; `obligation_years`; `obligation_quote` |
| Places | `places_total`, `places_year`, `places_published_by`: `funder`/`sending_side`/`none` |
| Cycle | `cycle_year`, `opens`, `closes`, `status`: `LIVE`/`CLOSED`/`SUSPENDED`/`UNKNOWN` |
| Evidence | `source_url`, `grade`: `FETCHED`/`OFFICIAL_SNIPPET`/`LEAD`, `checked_on`, `found_via` (§4 step ID, `CORPUS`, `MIRROR:<source>`, `RUN_A`, `RUN_B`) |

`FORGIVABLE_LOAN` means repayable only if a condition (usually a bond) is broken — Singapore's Tuition
Grant is `SUBSIDY` + `work_in_host` 3 years + `repay_on_breach`.

### 3.3 `inbound-eligibility.csv` — one row per track × country

| Column | Values |
|---|---|
| `track_id` | from 3.2 |
| `country_iso` | the applicant's country |
| `status` | `ELIGIBLE` / `EXCLUDED` / `PRIORITY` |
| `places` | per-country places if published, else blank |
| `list_source` | `VERBATIM` (named on the scheme page) or `BLOC:<list>@<version>` (e.g. `BLOC:OIC-members@2026-09`, `BLOC:OECD-DAC@2024-25`) |
| `quote_or_url`, `checked_on` | evidence |

Every eligible-country list is expanded in full, **not only launch-market rows**, so a future market is a
filter, not a new search. Bloc lists expand from the bloc's own official membership page and record its
version so they can be refreshed. Azerbaijan and Türkiye get no dedicated columns anywhere; they are the
first filter applied.

### 3.4 `inbound-search-log.csv` — one row per query or page opened

`country_iso`, `step`, `query_or_url`, `language`, `tool` (`gptr_quick_search` / `scrapling_get` / `scrapling_fetch` / `scrapling_stealthy` / `opendataloader` / `pdftotext`),
`hits`, `opened` (URLs), `outcome` (`find` / `lead` / `nothing`), `logged_on`.

This is what makes a `NO` auditable and what §6's measurements read.

## 4. Stage 1 — the census (Claude, in session)

### 4.1 Step 0 — collect once, before any country

- **Corpus.** Grep `docs/` for every scheme already recorded; file each as a `LEAD` under its country with
  `found_via=CORPUS`. These are to be confirmed, and **do not count as found** for §6.2.
- **Mirrors — offers republished by others**, filed as `LEAD` with `found_via=MIRROR:<source>`:
  - sending governments' scholarship pages: Pakistan HEC; South Africa DHET international scholarships;
    ministries of Sri Lanka, Bangladesh, Maldives, Kenya, Nepal; plus any other sending-government list
    met during the census;
  - Azerbaijan's and Türkiye's ministries and state programme pages that republish offers to their
    citizens (origin-side synthesis sources);
  - bloc channels: ICESCO and SESRIC (OIC), Commonwealth Scholarship and Fellowship Plan, ASEAN,
    Agence universitaire de la Francophonie, EURAXESS country pages, UNESCO fellowships.

### 4.2 Per-country checklist — every step runs even after a find

| Step | Source | Targets failure (§1) |
|---|---|---|
| `S1` | The official national study-promotion portal's scholarship page | 1, 9 |
| `S2` | Funder map: education ministry; foreign ministry and its aid arm; development agency; national scholarship/exchange agency; diaspora or compatriot agency — then each body's own site | 3 |
| `S3` | Generic-term searches, **one country per query**, in the country's official language(s) and English, restricted to its government domain where one exists: "scholarship for foreign citizens", "tuition grant", "fee waiver", "stipend", "subsidy", "service obligation", plus diaspora/compatriot terms | 2, 5 |
| `S4` | The country's embassies in Baku and Ankara: education and news pages | 6 |
| `S5` | Routes outside quotas: equal-rights agreements, co-ethnic or compatriot laws, residence-permit access to state-funded places | 4, 5 |
| `S6` | Regional tier, where education is a regional competence: list the regions from an official source, then run `S1`–`S3` per region | 3 |

Rules for every step:

- **Never search by scheme name first.** A scheme name may be searched only to verify a find already
  logged by a generic step.
- An aggregator result is a pointer to open, never evidence; nothing below `LEAD` is recorded, and a
  `LEAD` never sets `ELIGIBLE` in 3.3.
- Every query and page opened is logged in 3.4.
- Verdict per §3.1.

### 4.3 Order and pacing

- Regional batches; the CSVs are written after every batch so work resumes across sessions.
- Priority: OIC member states, former Soviet states, EU/EEA, then Asia-Pacific, then the rest. Every
  country is done.
- Expected effort: 5–8 queries or fetches per country, roughly 1,200 in total, over several sessions.

## 5. Stage 2 — deep research (two models, per regional batch)

- **Who:** census `YES` and `UNKNOWN` countries. `NO` countries are not sent (see §6.4).
- **Batches of 10–12 countries**, each run independently by Claude Research and Gemini Deep Research on
  the same prompt.
- **The prompt gives:** the country list; the §3 fields and fixed labels; the rules carried over from the
  inbound prompt and this sweep — current-cycle sources (2027/28 for checks made in 2026-09), operative
  sentences quoted, full eligible-country lists expanded, per-country places including sending-side
  publications, routes outside quotas, residence and descent keys, sub-national tier, one completion line
  per country (`covered fully` / `covered partly: <gaps>` / `dropped: <reason>`), and output rows in the
  §3.2/§3.3 shape.
- **The prompt withholds the census.** A supplied list anchors the reader and is echoed back as evidence
  (run A repeated the prompt's GKS figures). Kept apart, census, model A and model B are three independent
  readings, and their overlap is the measurement in §6.1.
- **Cost control:** batches run in §4.3 priority order; stage 2 stops when §6.5 is met.

## 6. Verification and recall measurement (Claude, after each batch)

### 6.1 Merge and three-way overlap

Merge census, run A and run B on `track_id`. Count tracks found by one reader only, by two, by all
three. Many single-reader tracks means the batch is not saturated and gets another pass.

### 6.2 Known-answer check — list fixed now, each item checked in the batch containing its country

These twenty schemes are real and were hard to find. The census must reach each through a generic step
(`S1`–`S6` or a `MIRROR`), with a search-log trail containing no scheme name. `found_via=CORPUS` does not
count. The census runner already knows these names, so the check is only as good as the log: a find whose
logged query names the scheme, or which appears without a logged generic query, fails.

| # | Country | Scheme | Why it is a good test |
|---|---|---|---|
| 1 | SG | MOE Tuition Grant | Not called a scholarship; bonded |
| 2 | LU | Guillaume Dupaix International Scholarship | Foreign-ministry money via a university |
| 3 | RU | CIS equal-rights budget places | Outside any quota |
| 4 | JP | JICA Nikkei Leaders | Aid agency, descent key |
| 5 | DK | Danish Government Scholarship | Allocated by universities |
| 6 | BE | Flanders Master Mind | Regional government |
| 7 | DE | BAYHOST | Regional + nationality key |
| 8 | CA | Québec PBEEE | Provincial |
| 9 | LT | State scholarships, Lithuanian-origin track | Descent track inside a quota scheme |
| 10 | SK | International scholarship scheme | Partial, new, ESIF-funded |
| 11 | AZ | Heydar Aliyev International Education Grant | Origin country as destination |
| 12 | PK | HEC Allama Iqbal, Central Asia | Region key, non-Western destination |
| 13 | KZ | Study in Kazakhstan, ethnic Kazakhs | Descent key |
| 14 | AT | Scholarship Foundation — master's in International Relations | Historical descent key |
| 15 | CZ | Government Scholarships – Developing Countries | Short, changing country list |
| 16 | QA | Qatar Scholarships (QFFD) | Development fund |
| 17 | HU | Hungarian Diaspora Scholarship | Diaspora agency |
| 18 | KR | GKS Overseas Korean track | Sub-track inside a held scheme |
| 19 | IT | MAECI, IRE track | Citizenship + residence |
| 20 | HK | HKSAR Government Scholarship Fund — Belt and Road | Territory; research master's only |

A miss identifies the weak checklist step; that step is fixed and the affected countries re-run before
the census continues.

### 6.3 `found_via` tally

After the first two batches, count finds per step. A step that produces nothing across two batches is
removed; a track reached by only one step flags that step as load-bearing, and similar countries are
re-checked against it.

### 6.4 `NO` countries

An exhaustive `NO` (no official statement) is re-checked with fresh wording before any market launch that
depends on it, and at most 12 months after `checked_on`.

### 6.5 Publication gate and stopping rule

- A row may be **recorded** at `OFFICIAL_SNIPPET`; a row shown to a student as eligible or as a route
  requires `FETCHED` for the eligibility and route quotes.
- Every disagreement between readers is resolved by fetching the official page, in a per-batch synthesis
  under `docs/superpowers/research/`.
- **Stage 2 stops** when a full regional batch adds no track that the census and the other model both
  missed.

## 7. Existing work

The 2026-09-13 inbound files are **inputs**, not results: their schemes enter step 0 as `CORPUS` leads and
must be re-found by the census to count. Their FETCHED evidence may be reused as the verification fetch
if the page is unchanged on re-check.

## 8. Not in this design

Retrieval-terms auditing of each site, any application-side automation, per-programme (course-level)
eligibility, and the university-own-funds sweep. Each is a separate decision.
