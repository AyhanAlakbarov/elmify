# The funding search engine — master design

**Status:** consolidation, 2026-09-22. One document to implement from. It gathers every decision
made across the seven discovery/fetch/reader specs and their three unmerged successors, resolves
the places where they disagree (§17 — latest dated owner decision wins, each delta named), and
leaves the source documents in place as the record of *why*. Where this document and a source
disagree, this document governs; where this document is silent, the source stands.

**Sources consolidated.** On `master`: `2026-08-27-phase5-discovery-and-pack-optimizer-design.md`
(§2 only — the optimizer half is out of scope here), `2026-08-28-funding-led-discovery-design.md`,
`2026-09-13-inbound-government-search-design.md`, `2026-09-13-institution-programme-funding-search-design.md`,
`2026-09-17-role-routed-discovery-design.md`, `2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md`.
On `claude/fetch-spec-refresh`: `2026-09-22-fetch-engine-design.md`. On `claude/reader-holder-axis`:
`2026-09-14-funding-reader-precision-design.md` (also PR #104), `2026-09-14-emjm-partner-source-design.md`,
`2026-09-19-coverage-driven-funding-engine-design.md`, `2026-09-19-recommendation-spine-design.md`,
`2026-09-19-eligibility-vocabulary-and-register-amendment-design.md`. Plus the measurement notes
under `docs/superpowers/research/2026-09-17-*` and `2026-09-18-*`, and `CLAUDE.md`'s "Web fetching"
and "Search providers" sections.

**Why a new document rather than the last one.** The 2026-09-19 coverage-driven design consolidated
the *branches* and mapped where each nuance lived; the 2026-09-22 fetch-engine design consolidated
the *fetch* half. Neither is a single implementable statement of the whole pipeline, and three of
the fetch decisions made on 2026-09-22 (both vendors paid, no own-client tier, `/agent` as
navigator) are not reflected in the reader- and discovery-side documents that still describe the
older ladder. This document is that statement.

---

## 1. Goal

Find **every funding a master's applicant could plausibly obtain** — by the sixteen holder types of
§5 — for **any country, any script, any family**; show each as a card whose every fact is a sentence
quoted from the holder's own page; and be honest about what has not been looked at. Three promises,
each measurable:

1. **Complete where the space is closed, estimated where it is open, never silent.** National
   schemes, intergovernmental bodies, embassies, political foundations and the registered
   institutions are finite lists and are enumerated to 100%; private foundations, employers and
   diaspora bodies get a capture–recapture estimate of the unseen, labelled as an estimate (§5, §15).
2. **A served fact is correct 95–100% of the time on the labels a student acts on** (owner target
   2026-09-14). Anything short goes to a human or is shown as *unconfirmed* beside its sentence;
   nothing uncertain is shown as certain (§8.6, §11).
3. **"Found nothing" and "could not look" are never the same row.** Every fetch ends in one of a
   closed set of outcomes with a trail (§7.4); every cell reports what it has read against what it
   knows exists (§15).

The product this feeds is the personalised pack (`apps/funding/pack.py`, `evaluation.py`,
`affordability.py`, `explanations.py` — built, and today ranking over a near-empty catalog). This
document owns the **supply side** and the two seams into the pack: the option card the reader must
fill (§10.4) and the coverage state the pack must render (§10.6).

## 2. Scope

**In.** The organisation register and its engines; the search roster and technique layer; name→site
resolution; host classification; the fetch engine (single-page fetch, site jobs, refresh, cost); the
funding reader (three readings, two model families, holder axis, tiered agreement, eligibility
triples, cycle fields); cycle verification; the pool → gates → pack spine for awards and programmes;
the human resolution queue; demand cells and on-demand search; data, cost, terms, security,
measurement gates and build order for all of the above.

**Out, and where it lives.** The competitiveness/odds calculation and past-winner analysis (phase 5
§3, built last); the risk-aware optimizer's unbuilt half (`2026-08-27-risk-aware-portfolio-design.md`);
living cost per city (`CityCost`, role-routed §4.11 — a pack-side dependency, referenced in §10.4);
the CV-rules reader (`reader.py`, `derive.py`), which *shares* the fetch engine of §7 and nothing
else; `apps/documents/europass.py` (student PII, its own pinned transport — never a vendor); every
portal path (`apps/portals/`, the glass-box extension); the DEQAR/WHED *accreditation screen*
(deleted 2026-09-14 — `CLAUDE.md` holds the record; DEQAR returns here only as an enumerator, §6.2).

## 3. Principles — the rules every layer obeys

1. **The catalog is about the world; the pack is about a person.** World facts are gathered once,
   cost money, and are shared by every tenant under the shared-catalog RLS pattern; the per-student
   filter is cheap and private. **No personal fact enters the catalog path.**
2. **The origin is the only evidence.** Registers, aggregators, channels, search snippets, vendor
   summaries and pointers yield *names* and *timing*; a fact is a verbatim sentence fetched from the
   body's own site, verified against the page, stored with its URL, snapshot digest and date.
3. **Only a URL is read from any search provider.** No snippet, title or score is persisted. Exa and
   Brave now permit storage; the discipline stands on merit — one audit shape, no second source of
   truth. A snippet may be read *in memory* to decide whether to fetch (transient triage).
4. **Know the denominator.** Every count of found things is reported against the size of the space
   it was found in — exact where closed, estimated where open, labelled either way.
5. **Three values, never two.** An eligibility condition is satisfied, failed or undecidable; a
   cycle is open, upcoming or unverified; a fetch found, could not look, or was refused. Passing
   silently what cannot be decided offers a shut route; failing it silently hides an open one.
6. **Measure before adopting.** A source, vendor or knob enters a plan after a holds-and-generalises
   check against lists we already hold; per-country scores are development scores and acceptance is
   a blind hold-out on a different script (owner rule 2026-09-18).
7. **Nothing names a scheme, funder, country, channel or page in code.** Lists, cells, cadences,
   vocabularies and terms postures are data rows with a source URL and a verified-on date.
8. **Buy before build.** A capability a vendor sells is used to the full; our code owns the order,
   the vocabulary, the residue and the outcomes (owner's standing rule, restated 2026-09-22).
9. **Every model call follows the repo baseline:** untrusted text labelled as data, schema-constrained
   output (`extra="forbid"`), capped `max_output_tokens`, `store=False`, and a per-tenant/per-user
   `rate_limited()` in the same change that wires the call.
10. **Nothing is a dead end without a recorded reason,** and nothing uncertain reaches a student as
    certain.

**Country is data, never a branch** (added 2026-09-23 — the owner's constraint: every rule in this
document must hold for any country, not for the ones it was measured on). Every rule here is written
over the cell abstraction and closed vocabularies — holder type, family, eligibility key, route
outcome. Anything that varies by country is a **row**: a register URL, a closed list, a query
language, the per-country precision figure that sets the route (§6.3 rule 4). Nothing is
`if country == X`. When a country turns out to publish a list, the subcategory moves engines *by
data* (§5); when it publishes none, the list is read by hand into a versioned file (§6.2). The
measurements in this document — Germany's 377-funder key, the 58 hosts, the ten-country subnational
check — are **calibration** for those rules, never their scope. A rule that only holds for the
countries it was measured on is a bug, and the fix is to find the general rule the measurement was a
case of.

## 4. Architecture

```
Layer 0  the funding space         cells = holder type × host country × home country × level
Layer 1  enumerate the bodies      closed lists · registers · search by role · inventory · hubs · pointers
           └─ Organisation register (one body, several domains) ─ resolver ─ classifier
Layer 2  fetch                     one seam, seven rungs, host memory, eleven outcomes, site jobs, refresh
Layer 3  read                      lines → three readings, two families → tiered agreement → awards, triples, cycle facts
Layer 4  verify                    cycle_validity over dated evidence; the evidence ladder; cadence; withdrawal
Layer 5  serve                     pool = cell selection → facts → gates → pack (programmes and awards) → card
           └─ human resolution queue (site unknown · award disputed · host unreachable · kind unsure)
           └─ demand cells, on-demand search, coverage line
```

Every stage below is a `LeadSource` or a pure function plugged into the existing pipeline
(`apps/research/pipeline.py::run_discovery`, `default_sources`); nothing bypasses `RunBudget`,
`PacedFetch`/`DomainLease`, `validate_public_url`, `persist_snapshot` or the evidence bucket.

## 5. Layer 0 — the funding space

A **cell** is `holder type × host country × home country × level`. Countries are ISO 3166-1 alpha-2
or `ANY`; level is `MASTER` until a second exists. Cells are rows (`FundingCell`, shared catalog),
never code. A body sits in the cells its awards can fund; an award sits in one or more cells; a
student selects cells from their profile (§10.1).

**A cell is not a sweep pass, and this document used one word for both** (corrected 2026-09-23; §6.7
read `(country, family, eligibility keys, language)` and §6.3 `(country, family)`, neither matching
the tuple above). They are two objects with different jobs, and conflating them multiplies the
sweep's cost by axes it does not have:

- **The cell is the accounting unit** — the tuple above, keyed by **holder type**, the thing
  `FundingCell` stores, `§10.1` selects a pool from and `§10.6` reports coverage against.
- **The sweep pass is the search plan** — keyed by `(host country, family)`, so one pass covers
  several cells (sixteen holder types collapse onto eleven families, and the query vocabulary is
  generated from *the family's* definition). Inside a pass, **phrasing set and language are loops,
  not axes**: four phrasing sets, local language then English (§6.3).
- **Home country is not a sweep axis and eligibility keys are not either.** A German foundation's
  page does not change according to who is reading it, so both enter as *eligibility keys* — one of
  the four phrasing sets, ~60 extra calls a corridor (§6.3), and a filter applied to what comes
  back. Promoting either to an axis multiplies every pass by the size of a vocabulary, for pages
  that would have been returned anyway.

**The sixteen holder types** (closed literal in `funding_judge._HOLDERS` / `models._HOLDER_VALUES`;
also `Organisation.kind`, §6.1): `NATIONAL_GOVERNMENT` · `SUBNATIONAL_GOVERNMENT` ·
`POLITICAL_FOUNDATION` · `RELIGIOUS` · `PRIVATE_FOUNDATION` · `EMPLOYER` · `INTERGOVERNMENTAL` ·
`REGIONAL_FUND` · `EMBASSY_BILATERAL` · `DIASPORA_AFFINITY` · `PROFESSIONAL_BODY` · `BANK_OR_LENDER` ·
`ALUMNI` · `INSTITUTION` · `RESEARCH_INSTITUTE` · `UNSTATED`. Each maps to one of the eleven
`FundingFamily` values through `_FAMILY_BY_HOLDER`.

**`RESEARCH_INSTITUTE` is an owner decision (2026-09-19) that was never built** (corrected
2026-09-23; this line used to say "added 2026-09-19"). Measured against every branch that has ever
existed: the value appears in no code file, `_HOLDERS` and `_HOLDER_VALUES` hold fifteen, and the
eligibility-vocabulary plan's Step 3 — three one-line edits, mapping it to
`RESEARCH_ECOSYSTEM_PATHWAY` — is still an unchecked box. Until it lands the judge labels Max Planck,
Fraunhofer, Helmholtz, Leibniz, TÜBİTAK's institutes and CNRS as `INSTITUTION` or `UNSTATED`, and the
strongest single signal in the search probe — research-ecosystem pathway at **Exa 95/90, Brave
90/90** — is aimed at a holder the judge cannot emit. See §19.

**Universes, and the engine each gets** (assignment is data; a subcategory moves engines per country
when a country turns out to publish a list):

| universe | holder types | engine | "all bodies" |
|---|---|---|---|
| closed | national government, intergovernmental, regional fund, embassy/bilateral (one per home×host pair), political foundation, subnational government, institution (the registers), alumni (derived from institutions), **research institute** (added to this row 2026-09-23 — it was in no row; the umbrella bodies publish their institute lists, and the probe's evidence for the family is the institution-side pattern, so it takes the institution route: register, then the domain-restricted Exa call of §6.4a) | closed-list (§6.2) | yes, checkable |
| mostly closed | professional body, bank/lender | register + closed-list | mostly |
| mixed | religious | closed-list + register + open-tail | partly |
| open | private foundation, diaspora/affinity, employer | register + open-tail (§6.3–6.6) | **estimated** (§15) |

**Out by owner decision, recorded so nobody searches for them again:** mobility money inside a
degree (Erasmus+ KA131, PROMOS, Nordplus — 2026-09-17); essay prizes, hackathons, competition awards
(2026-09-18); student work rights, on-campus jobs, instalment plans; exchange and non-degree study;
doctoral-only; undergraduate-only; awards stated only on an aggregator. **In by owner decision
2026-09-17:** conditional fee discounts (`money_form: DISCOUNT`), application-fee and deposit waivers
(`FundingBenefit.Kind.APPLICATION_FEE`), income-tested fee brackets applied through the university
(`I1`, never a pointer), a free or subsidised language/preparatory year when it is the only support
on a page (its own `I1`/`I6` row).

**The free-to-apply rule (owner policy 2026-09-17).** If applying costs nothing, the option belongs to
every student who has not excluded its country — a zero-fee option cannot be crowded out of a fee
budget. So the free-to-apply universe is **one set for everyone**: swept and read once into the
shared catalog, complete, checked against a known-answer set, and **read first** in every queue
(§6.7). Per-student aiming is needed only where the fee budget binds.

## 6. Layer 1 — enumerating the bodies

### 6.1 The Organisation register — the one object every route needs

Shared-catalog tables, written by the `catalog_ingestion` role only, readable by every tenant, added
to `_SHARED_TABLES` in `tests/tenancy/test_database_isolation.py`, RLS verified through
`runtime_connection` (the test role bypasses RLS and proves nothing — `CLAUDE.md`).

- **`Organisation`**: `primary_domain` (unique; display and default key), `name`, `names`
  (ArrayField — every label the register or Wikidata supplies, in every language; the resolver needs
  them), `kind` = **the holder vocabulary of §5** (one taxonomy — a funder's kind *is* its holder
  type; a university is `INSTITUTION`; a faculty is `INSTITUTION` with `parent` set), `country_code`
  (its home; the countries it funds are derived from its awards' cells), `official_website`, `status`
  — `REGISTERED` (a national register, DEQAR or a curated national file vouched for the domain) /
  `CANDIDATE` (search, inventory, a hub page or a pointer found it; fetched and classified; vouched by
  no register) / `REJECTED` with `rejected_reason ∈ {INFRASTRUCTURE, NOT_A_FUNDER, DOES_NOT_EXIST,
  UNREACHABLE}` — `found_via` (list of route tags, §6.4), `first_seen`, `last_verified`; **read state**
  `last_read_at`, `pages_read`, `pages_unreadable` (latest-state fields, not a history table);
  **cadence** `cadence`, `cadence_open_month`, `cadence_deadline_month`, `cadence_source`,
  `cadence_verified_for_cycle` (curated, sourced, expiring — §9.2).
- **`OrganisationDomain`** (`organisation` FK PROTECT, `registrable_domain` unique, `found_via`,
  `first_seen`): **one organisation, several domains.** ROR returned `bwstiftung.de` for the foundation
  whose scholarship lives on `bw-stipendium.de`; under a one-domain key those never join.
  `record_organisation` looks up *any* domain first; a new domain attaches to an existing organisation
  only when they share an `OrganisationIdentifier` — never on a name match alone.
- **`OrganisationIdentifier(scheme, value)`**: the `InstitutionIdentifier` scheme vocabulary plus
  `WIKIDATA`, `ROR`, `EACEA_PIC`; the join across sources and the merge mechanism.
- **Key: registrable domain on the Public Suffix List** (`apps/research/hosts.py::registrable_domain`,
  built) — `metu.edu.tr`, `ox.ac.uk`, `edu.gov.az` key correctly; a two-label rule got `edu.tr` wrong.
- `funding.Institution` is unchanged (still written only by `write_catalog_entry`); an `Organisation`
  of kind `INSTITUTION` gets a nullable link to it. `FundingOpportunity.organisation` is a real FK
  (PROTECT, null=True), backfilled from the string `holder_domain`; the scope-shape constraint for
  `HOLDER` requires the FK; the string column is dropped once a test asserts every `HOLDER` row has it.

**Status affects spend and dedupe, never student visibility.** A `CANDIDATE` funder's awards reach a
student on the reader's evidence rules exactly as a `REGISTERED` one's do.

### 6.2 Closed lists and registers — the spine and the denominator

**Closed-list engine.** One sourced row per list (`registers.py`'s "one frozen config per register"
shape, extended from institutions to every closed subcategory): the URL that publishes it, verified-on
date, country and subcategory covered, the bodies it names. Completeness = bodies known ÷ list size;
a list past its verified-on date raises re-check priority like a stale cadence. National registers
that publish no API (YÖK as a web page with unestablished terms; Azerbaijan's TKTA publishes no list of recognised institutions, only two negative lists as JSON -- corrected 2026-09-26, provenance gate spec §9.6)
are read by hand into a versioned file per country (like `docs/research/institution-identifiers.csv`)
and that file — not Wikidata — is what promotes a domain to `REGISTERED`.

**Register enumerators**, each a `LeadSource`-shaped adapter writing `Organisation` rows:

| register | enumerates | licence | notes (measured, dated) |
|---|---|---|---|
| Wikidata SPARQL, class × country × P856 | HEIs, ministries, agencies, foundations, diaspora bodies, women's/disability/sports/arts foundations | CC0 | writes `CANDIDATE` only — crowd-sourced, includes dissolved bodies; class, dissolved-filter and website requirement pinned in the adapter and quoted in its docstring (TR 229 universities with a site, 366 if the class widens). Also the resolver's first stop (P856) |
| DEQAR (Connect API `?country=<ISO2>`; the daily CSV is 103 MB and 375 MB peak RSS — per-country lookups, never the whole file) | externally reviewed EHEA HEIs with `website_link`, `identifiers_all` (EU-PIC, Erasmus Charter), `closure_date`, `historic_relationships` | PDDL (report PDFs CC-BY-SA, never mirrored) | TR 234, KZ 170, GE 83, **AZ 13 against ~50 real** — thin in the launch corridor. Read through `egress.fetch_data_file`, a first-party transport |
| ROR v2 (`types:education`, `funder`, `facility`, `nonprofit`, `government`, `company`; `domains:` lookup) | research/education/funding organisations with a stable id and website | CC0 | TR 239, AZ 52; CN 5,708. Returned Cusanuswerk, TEV, Studienstiftung, Visegrad Fund, DAAD with websites. **A lookup with verification, never "take the first row"** — the fuzzy top hit is sometimes a different organisation. **Gate before it enters a plan:** run against the 58 yield hosts and the pointer names; record the share known, exact-name share, website-matches-held-domain share |
| EACEA project API (`POST ec.europa.eu/programmes/service/search/project/search`, filter `projectLevel3`, action codes `43690363` + `31046261`) | every EMJM with coordinator and partners: name, country, city, PIC, website | Europa reuse notice (Terms of Use govern uploading) | 415 projects, 576 organisations, 78% with a website. **Assert `total` ≪ 341,601** — `level3`/`actionType` are silently ignored and return the whole corpus. Partner binding by EU-PIC (primary, 72% on this population) then registrable domain, walking `succeeded by` up to four hops; 461/576 bound, 6 to a human, closed-with-no-successor and non-degree-awarding bodies bind nothing (`2026-09-14-emjm-partner-source-design.md`). `I5_FUNDED_DUAL_DEGREE` attaches from the register **only for intakes inside the project's funded period**; past it only the page decides |
| Türkiye VGM "Burs Veren Vakıflar" (`vgm.gov.tr/vakif-sorgulama/vakif-sorgulama?IsGrant=true`) | scholarship-giving foundations — **the purpose is on the register**, so rung 1 of the ladder below | public `.gov.tr` register; reuse terms **unread** (open, §19) | **Rendered 2026-09-24: 4,076 with `IsGrant=true` of 6,857 foundations in all.** Client-side page (a plain GET returns "YÜKLENİYOR"; read through the vendor path, never a scraped view); page size 50; no API. Columns: name, address, district/city, phone/fax, e-tebligat, **e-mail** — **no website column**, but eight of the twelve rows on page one carry an own-domain address (`1870vakfi.org`, `yekuv.org`, `vakif1972.org.tr`…), so roughly two-thirds resolve by §6.5's rung 0 with no call, and the free-mail rest go to the name resolver. Against it: the 2026-09-24 search sweep held ~30 foundations and Websets 13 all-green — **search reached under 1% of the register** (`2026-09-24-query-design-and-enumeration.md` §3). Adapter: read the count first and assert it against the thousands, never the millions; a page count that moves by more than 10% between monthly diffs is a queue item, not a silent overwrite |
| Germany — BZSt **Zuwendungsempfängerregister** (`bzst.de`, online since January 2024) | every organisation entitled to issue donation receipts — non-profit corporations, public bodies, parties — **searchable by tax-privileged purpose and by region** | public federal register; terms unread | Rung 2 for Germany: names and purposes, **no website field yet** ("in later versions … their internet address", per the BZSt overview), so every row goes to §6.5's name resolver. The federal **Stiftungsregister** at the Bundesamt für Justiz opens **1 January 2028** and is mandatory for every legal-capacity foundation — the future rung 1; until then `foerdermittelkompass.reflecta.org`'s typed `grant_providers` API (1,938 providers, eighteen `provider_type` values, website per row; bearer token, **licence unread**) is a candidate directory, not a source. Found 2026-09-24; nothing here is built |
| programme registers where a country publishes one | Korea data.go.kr #15139338 (KOGL; `학위과정` contains 석사 → 19,118 rows, **12,169 live** after the `학과상태` filter — 49% of rows are abolished departments) + #15107736 (institution websites); Finland `konfo-backend` (1,285 master's; **blocked on terms** pending one email to Opetushallitus); Australia CRICOS, France ONISEP, Italy Universitaly, Spain RUCT, Netherlands Studiekeuze, Poland RAD-on — terms checked per register before use | per register | a registry row is `AGGREGATOR`: it routes and seeds identity, liveness is confirmed at the origin page, never from the row. Enumeration ceilings (NSF 3,000, NIH 9,999 offset, Korea 50,000-row grid) force slicing, asserted by fixture |
| ANR (French EUR/IdEx graduate schools) | the one confirmed master's-funding grant database | Licence Ouverte v2.0 | `GrantDatabaseSource` (`ECOSYSTEM_CLUE` leads); CORDIS and KAKEN **dropped** — no master's instrument |
| Diffbot Knowledge Graph | one `type:Organization isNonProfit:true` + country + `description:"<local scholarship word>"` query per country per cycle | explicit commercial grant, no storage clause, **no effective date — re-read before each use** | +24 German funders on 353 (+7%) at **28% precision**; **never a spine, never the holder enumerator** (its ontology has no nonprofit subtype). `Enhance` by name is the resolver's residue step (§6.5) |

**No register is an accreditation list, and the differences are the point.** YÖK asserts legal
authorisation (208), DEQAR external review (234), ROR a persistent id (239), Wikidata that someone
wrote it down (229). A count from one is not a denominator for another. Set-differences are the gold
sets (§15): DEQAR minus ROR, Wikidata minus ROR — usable for Türkiye, near-useless for Azerbaijan.

**A closed list is a floor, never a ceiling.** The open-tail engine (§6.3) runs in every cell
regardless of how complete the list looks.

**The register ladder — four rungs per (country, family), and the rung is a row, never a branch
(owner decision 2026-09-24, on the query-design research).** Every route below feeds the same
chain — resolve names to hosts (§6.5), classify (§6.6), expand programmes (§6.4a) — and what differs
by country is only where the *names* come from and how honestly coverage can be stated:

1. **A register carrying the purpose** (VGM's `IsGrant=true`): names *and* the fact the classifier
   exists to establish. Coverage is `bodies known ÷ register size`, and the reader's gate (§6.3's
   "the list is the denominator, never the reading queue") still applies — 4,076 hosts through the
   reader is ~$1,400; through the classifier, ~$4 (§6.6).
2. **A register without the purpose** (a charity commission, a tax-status list such as BZSt's, a
   state foundation directory): names only; the classifier supplies the fact. More names, same
   mechanism, classifier spend in the tens of dollars per country at Jev prices.
3. **Umbrella bodies and hubs** (§6.4): national foundation associations' member lists, ministries'
   and funders' own "where else to look" pages. Partial, but every name is real.
4. **Search only** (§6.3, §6.7): the family has no list in that country — companies almost
   everywhere, foundations in some places. The output is a **curve**, never a total.

**The coverage line names the rung** (§10.6): "94% of a purpose-filtered register" and "stopped
when three batches found nothing new" are different claims, and a search-only country must not read
as complete as Türkiye. **The register survey is owed per corridor country** (§19): which rung each
launch country reaches for each family, with URL, reuse terms and whether rows carry a website or an
e-mail. Found so far (2026-09-24, one research pass, partial): Türkiye rung 1 (VGM); Germany rung 2
now (BZSt) and rung 1 from 2028 (Stiftungsregister); Kazakhstan's `publicreg.myafsa.com` lists
AIFC-registered foundations only, not a national register; Azerbaijan, Georgia, Uzbekistan, the
Netherlands, Sweden, France, Hungary, Italy, Indonesia, Vietnam, India and Pakistan unsurveyed.
Umbrella directories to check first: Philea's member list, ECFI's atlas and the Centre Français des
Fondations' list of national networks, each naming the association per country.

### 6.3 Search, by role — only for the set-difference

Search runs **only** for the families with no index, and only after the register has been diffed
against, so a second index is paid for by its novel hosts alone.

| family (side) | route | shape |
|---|---|---|
| private foundation; industrial sponsorship (**the residue after its rung-2 employer list**, row below); affinity/diaspora (**keyed `(host country, home language)`**, row below) | **Exa primary** | `/search` `type: auto`, **a set of page-voiced queries per pass, each at `numResults` 10–15, one angle per query** (amended 2026-09-24 — see the phrasing block below; this row said one describe-the-entity query at `numResults: 100`, which is the shape Exa's own guidance names as the anti-pattern: *"never use numResults above 25 … run more queries with different angles at n=10-15"*), in the **local language** then English, `excludeDomains` = `AGGREGATOR_DOMAINS`; every response carries `costDollars` — meter on that. **Not** `includeText` (deprecated). `category: company` is **owed a re-measurement** with client-side exclusion — the −2.7 was measured with `excludeDomains` on the same call, which Exa now rejects for that category (400), and the 2026-09-24 Websets run found *vakıf* foundations through its Companies entity without difficulty |
| same families | **Brave second index** | `offset` 0–9 stopping on the first **empty `results`** (`more_results_available` is absent — do not gate on it; a real query exhausts ~offset 5, budget ~6 requests), Goggle **inline** (`$discard` aggregators; `$boost` `.edu.`/`.ac.`/`.gov.`/`uni-`/`universit`/`stiftung`/`vakf`, `/scholarship`, `/burs`), `result_filter=web`, one `discussions`+`faq` call per query. **Not** `country` (−8 in Indonesia), **not** `search_lang` (inert) |
| same families, local-language leg | Tavily | a *decaying* discovery leg (62 → 5 first-discoverers over 99 queries) the per-route tally drops early; `search_depth: basic`; **never** `language` / `filter_by_language` |
| government scholarship **home-country outbound** (decision 35, 2026-09-24 — this family sat in the Exa-primary row above, contradicting §5's universe table, which has national government *closed*) | **closed list first, for every country**: the outbound schemes of any one country are a handful of named programmes run by one or two ministries or agencies — YLSY and MEB for Türkiye, Bolashak, El-Yurt Umidi, Azerbaijan's State Program — so each is a rung-1 row (scheme, agency, page), with the ministry's page harvested as a hub (§6.4). Where the agency publishes no list (Azerbaijan's TKTA, §6.2) the row is read by hand, as institutions already are. **Search runs only as the rung-4 novelty check** — one page-voiced angle set per cycle, tallied; a hit not on the list is a queue item that *extends the list*, never a served row on its own | the list is the denominator and is expected to be complete; the coverage line reports `schemes known ÷ schemes listed` |
| **employer / industrial sponsorship** (decision 36, 2026-09-24 — the family had no denominator at all) | **two halves, two rungs.** Corporate *foundations* (Sabancı Vakfı, Koç, Bosch Stiftung) sit in the foundation registers and take that family's ladder. Direct corporate scholarships — a company page with no foundation behind it — take **the country's largest-employer lists as rung 2**: the stock-exchange listing, the chamber of industry's ranking (ISO 500 in Türkiye, DAX/MDAX and the IHK lists, KASE, NSE, IDX), one sourced row per list per country. Then **your professional-body rule applied to employers**: enumerate the top *N*, **one domain-restricted Exa call each** (~$0.022; 500 companies ≈ $11) for a *"scholarship / burs / Stipendium / bursary for students"* page, **read only on a positive hit**, never walk the site. *N* is per country and set by the tally — concentrated corporate giving (Türkiye, Korea, India) is carried by a short list; where the giving arm is a registered foundation (Germany) the list adds little and the tally says so. Brave leads Exa on this family (70% vs 50%) for the rung-4 residue | `bodies known` counts the list, `bodies read` counts the positive hits; the sweep pays only for what neither half held |
| **affinity / diaspora** (decision 37, 2026-09-24) | **keyed `(host country, home language)`, never a country row** — a diaspora body is by definition in one country and speaking another's: an Azerbaijani student association in Germany is found by a German-hosted pass written in Azerbaijani, a Vietnamese one in France by a French-hosted pass in Vietnamese. Bodies from Wikidata's class × host country, the page-voiced angle set in the home language (*"… diasporası / dərnəyi — təqaüd"*), pointers from the embassy's and ministry's pages. Exa primary; the same rung-4 tally | the pass is one row per `(host, home language)` pair in the corridor, which is the corridor table itself |
| government scholarship **destination side** | registries + study-in portals; Tavily open-web only for the gap | — |
| multilateral — **EMJM** | **no search** — the EACEA API, which is the complete list because every EMJM is an EU-funded project and the funder's own records are authoritative | 0–50% origin on every index |
| multilateral — **everything else**, and **regional funds** (corrected 2026-09-23) | **no search, and no route either — this is a gap.** `REGIONAL_FUND` maps to `MULTILATERAL` and so inherits the EACEA-only route: Visegrad Fund, Nordic Council of Ministers, EEA Grants and the Black Sea Trust reach a student through nothing. One **global, cell-tagged** closed list covers both — every body enters with the home × host cells it funds, so a student's pool selects from it by cell (§5), and the same list serves a Nigerian applicant (AfDB, Mastercard Foundation) and an Azerbaijani one (IsDB) with no per-corridor copy (§6.2, build item 7); see §19 | — |
| subnational government (found and decided 2026-09-23; **measured the same day across ten countries — the block below this table**) | **Destination-side, for every country, by one rule.** Subnational bodies are enumerated wherever they exist (Wikidata's subnational-agency class is global; the state education ministry is a hub, §6.4). Each body's money is then classified on **three closed questions — two the reader already answers, one derived from them** — does it fund master's students at all; is it *incoming* (for students coming to the region) or *outbound* (for the region's own students going elsewhere); is it gated on residence or nationality — and those answers gate reading and serving, **never a hand-written country verdict**. Outbound money is home-side and serves a student *from* that region; resident-gated money derives `EXCLUDED` unless the student's residence matches. The ten-country check calibrated the three questions and found the incoming, ungated set small (Italy's DSU agencies, Belgium's communities, a few Austrian programmes) — which sizes the launch work, not the rule | closed-list + hubs; the reader's three answers are the gate |
| professional body · bank/lender · alumni (found 2026-09-23) | **§5 and this table disagree, and this table silently wins** because it routes by *family*: all three map to `PRIVATE_FOUNDATION` and so get open-web search, while §5 assigns them register + closed-list / "derived from institutions". **Alumni is settled by §5 as written** — one association per HEI, reached by the §6.4a domain call that already runs, never by open-web search. **Professional bodies and banks: decided 2026-09-23 — per-country registers** (a chamber of engineers, a central bank's list of licensed lenders) are the denominator and slot into build item 7's per-country closed lists. **With one rule the owner attached: the list is the denominator, never the reading queue.** A licensed-lender register is hundreds of banks and almost none fund students, so reading each one's site is the reader's money spent on obvious non-funders. A body from these two registers is read only on a cheap positive signal — it already appears as a `POINTER` on a page the reader met (§6.4, free), or one domain-restricted Exa call (§6.4a, $0.022) returns a scholarship, bursary or education-programme page on its own host. No signal → `bodies known` counts it, `bodies read` does not, and the coverage line stays honest about the difference. **The rule is universal; the register is a row per country** (§6.2): a central bank's licensed-institution list exists in effectively every jurisdiction, professional-body registers in most, and a country that publishes neither is read by hand into the versioned per-country file, as institutions already are — never a country-specific branch | the list gives the denominator; the gate keeps the reader off the share that funds nothing |
| university-wide, programme-attached, waiver, stipend, relocation, research pathway | **no open-web *sweep*** — a topic query for programmes returns content farms — **but two open-web calls are permitted, and both are page-voiced** (amended 2026-09-24): the tap's field-aimed query (§10.5 step 2) and the cell-level programme pass of §6.4a item 5, each carrying only what §10.5's Exa/Brave allow-list permits. And **one domain-restricted Exa call per institution is the FIRST pass, not a fallback** (§6.4a, measured $0.022; ~$44 per 2,000-institution corridor), then inventory, then the reader | corrected 2026-09-23: this row previously said "no search … search only as the §6.4 fallback", contradicting §6.4a. §6.4a governs — sitemaps expose programme pages at only 2 of 5 major universities and a widened path regex measured *worse*, so crawling first is the expensive way to reach what one call surfaces |
| China / Korea | **Baidu / Naver via SerpApi** (owner decisions 2026-09-17/18: free tier, no Legal Shield) | `engine=baidu` +7 institutions at 76% precision; `engine=naver&where=web` +5 funders. Added for a country only where the national web is **large and partly outside the global indexes' reach**; measured out: Yandex (0 in AZ), Seznam, Coc Coc, Google via SerpApi (+1–2). Naver's own API preferred once its terms are read on `developers.naver.com` |

**Subnational money, checked across ten countries (2026-09-23, owner's request).** One open-web pass
per country, English or local language, asking where state-level money for master's students is
published and who may receive it. Three shapes came back, and only one of them is destination money
for our students:

| country | what exists at state/region level | incoming international eligible? | where published |
|---|---|---|---|
| **Italy** | regional DSU right-to-study scholarships (ARDSU, ADiSU, EDISU, ERSU…): tuition exemption, housing, meals, stipend; regions hold exclusive competence | **yes** — ISEE + merit, internationals explicitly admitted | each regional agency's site; **ANDISU** (the national association) lists them all — a closed list |
| **Belgium** | Master Mind (Flanders, €10,225 + fee waiver), WBI Master grants (Wallonia-Brussels) — the country's "national" scholarships are community-level because education is | **yes** | `studyinflanders.be`, `studyinbelgium.be` — the study-in portals the destination route already reads |
| Austria | Land Niederösterreich scholarships; Land Steiermark co-funds "Go Styria" (Uni Graz, SEE research stays) | partly — small, mostly research stays | Land sites; `grants.at` aggregates |
| Switzerland | cantons own the entire grant system; master's is eligible under the intercantonal harmonisation | **no** — residents only; "if you reside in Switzerland only to study you have no entitlement" (`ch.ch`) | cantonal offices, `swissuniversities.ch` |
| France | Région Sud PRAME (€125/week), Auvergne-Rhône-Alpes mobility bourse, Île-de-France, Grand Est | **no as destination money** — outbound mobility for students already enrolled in the region | regional council sites, Euroguidance |
| Spain | Navarra (up to ~€90k for master's abroad), Catalonia AGAUR mobility, others | **no as destination money** — for the community's own residents going out | community sites; `uniscopio.com` aggregates |
| Germany | nothing state-level for incoming master's surfaced; Deutschlandstipendium is federal + university co-funded; Landesgraduiertenförderung is doctoral | — | — |
| Netherlands, Sweden, Hungary | nothing at province / region / county level; regions hold health, transport and development, not student aid | — | — |

**What follows for the route — a rule for any country, with the table as its calibration.** The three
shapes above are not ten facts about ten countries; they are the **closed vocabulary** a subnational
award falls into anywhere — *incoming*, *outbound*, *resident-gated* — and the reader already carries
the keys that decide it (the `CITIZENSHIP` and `RESIDENCE` conditions the judge emits, §8.5; the holder label — and note `applies_to` is the intake period, not direction, so incoming-vs-outbound is **derived, not read**: a `RESIDENCE` or `PRIOR_INSTITUTION` condition naming the region while the money funds study outside it; that derivation is one owed reader rule, §19 — and the condition
labels). So the rule is: enumerate subnational bodies wherever Wikidata and the state-ministry hubs
find them; classify each award on those three questions in the reader's own pass; **read and serve on
the answers, never on a hand-written verdict per country** — a verdict is what this table is, and it
is calibration, not the gate. Three consequences that hold everywhere. **Outbound regional money is
home-side money**: it serves a student *from* that region (a Catalan or Navarrese applicant abroad),
so it is written to the catalog in the region's *home* cells, and a page listing it beside incoming
schemes must not be read as incoming — the phrasing differs by language ("résidant en région",
"residencia fiscal", "Wohnsitz im Kanton"), which is exactly why this is the reader's three-readings
job and not a keyword. **A resident-gated award derives `EXCLUDED`, never `UNCONFIRMED`**, unless the
student's residence matches — a cantonal grant that reads as "possibly eligible" reaches every
student's pack as a false option, the worst outcome §8.8 exists to prevent. **And a country nobody has
checked gets the same treatment, not silence**: its bodies are enumerated, their awards classified,
and the coverage line reports what was found. The ten-country table sizes the launch work — one
adapter that matters, ANDISU's DSU-agency list; Belgium already reached via the study-in portals — it
does not bound the design. Sources: `swissuniversities.ch/en/service/scholarships-for-study-abroad/more-information/cantonal-grants`,
`ch.ch/en/school-and-education/higher-education/grants-and-student-loans/`,
`vlaanderen.be/en/study-grant-for-higher-education`, `studyinflanders.be/scholarships/master-mind-scholarships`,
`studyinbelgium.be/en/master-wbi-grants`, `dsu.toscana.it/borsa-di-studio`, `andisu.it`,
`unimi.it/en/study/financial-support/regional-scholarships`, `maregionsud.fr/vos-aides/detail/aide-a-la-mobilite-internationale-etudiante-prame-etudes`,
`euroguidance-france.org/financer-sa-mobilite/bourses-regionales/`, `gff-noe.at/stipendien/`,
`wu.ac.at/en/students/my-program/masters-student-guide/grants-and-scholarships`,
`uniscopio.com/becas/becas-comunidades-autonomas/`, `imasterhoy.com/ayudas-y-becas-autonomicas-para-cursar-masteres-fuera-de-espana/`.

**Four phrasing sets per (country, family):** Exa's describe-the-entity, Brave's keyword, Tavily's
local-language, and the eligibility-keyed set ("scholarship for women in engineering master's
<country>", need-based, refugee — ~60 extra Exa + Brave calls per corridor, tallied by novelty).
English runs as a second pass (adds a unique 5–35 after local). **Constraints in parameters, never in
prose; one topic per call; Tavily's 1,500-character cap.**

**The page-voiced rule (owner decision 2026-09-24; `2026-09-24-query-design-and-enumeration.md`
§1–2).** Every query this engine sent before this date was a *topic* query — "foundations that give
master's scholarships in Türkiye" — and both indexes returned the pages most *about* that topic:
newspaper round-ups, blogs, aggregators (20 of 72 Turkish hosts in the 2026-09-24 sweep). A
foundation's own page is not about foundations; it says *"Vakfımız her yıl … öğrenciye burs
vermektedir — Burs Başvurusu."* Exa's guidance is the same sentence from the vendor's side:
*"describe the target page itself, not the fact you're seeking."* So a query is written **as the
target page writes itself**, and a pass is a **set of angles**, not one query:

- **Organisation angles** (one query each, local language, `numResults` 10–15 on Exa): the
  scholarship-application page (*"burs başvurusu, başvuru koşulları, son başvuru tarihi"*), the
  eligibility page, the season announcement (*"2026–2027 burs başvuruları başladı"*), the funder's
  about-page in the first person (*"Unsere Stiftung vergibt Stipendien für Masterstudierende"*), the
  FAQ, the PDF call. Each angle reaches a different page of the same body, which is what makes the
  set-difference per angle informative.
- **Programme angles** (§6.4a item 5): the programme page (*"MSc Chemistry — admission requirements,
  tuition fees and scholarships for international applicants — apply by"*), the fees-and-funding tab,
  the departmental scholarship page, the graduate-school call. Field, level, teaching language and
  destination are the only attributes carried — §10.5's allow-list, never a person.
- **Brave gets the same vocabulary as terms, not a sentence**: `intitle:vakfı "burs başvurusu"`,
  `inbody:"yüksek lisans" burs -haber -gazete`, `lang:` only where the ablation shows it inert
  rather than harmful, the Goggle **inline** in the `goggles` parameter (no hosting; three per
  request), `q` ≤ 400 characters / 50 words.
- **The generator** (§6.7) writes the angle set per (country, family) from the family's definition,
  *in the voice of the page*, with the angle list above as its closed input and Exa's "genuinely
  different angles, not synonym swaps" as its rule; word order is a free second sample. A
  hand-written `STEERING.funder_query` row is the interim, one angle where a set is owed.
  **Its output is data, not a prompt**: every generated angle set is stored as versioned rows keyed
  `(country, family, language, angle)` with the model and date that wrote it, so a sweep is
  reproducible, a dead angle is visible in the per-angle tally, and an operator can read what was
  asked. The generator is one schema-constrained call per (country, family) — `rate_limited`,
  `extra="forbid"`, capped — and carries no student attribute; the programme-angle set per cell is
  the same shape keyed `(field, level, language, angle)`.

**The engineered query — the recipe, so "max success" is a specification and not a hope.** For an
embedding index the query is a *paraphrase of the page we want to land on*, written the way that
page opens, and the closer the paraphrase the nearer the neighbour. Seven levers, each measured or
vendor-stated:

1. **Voice.** First-person institutional (*"Vakfımız"*, *"Unsere Stiftung"*, *"Our MSc in
   Chemistry"*), never third-person description (*"foundations that give"* — a topic, which lands on
   lists).
2. **Structure cues.** Name the headings the target page carries — *admission requirements, tuition
   fees, scholarships, application deadline, how to apply* — because those words are on the page and
   not on the article about it.
3. **Language of the page, not of the searcher — and every language the country's pages are
   written in** (decision 38, 2026-09-24). A German-taught programme's page is German; an
   English-taught one at the same university is English; a Turkish foundation's is Turkish — and a
   Kazakh funder's is, more often than not, Russian. **The language loop takes every official and
   administrative language of the country from Wikidata (P37), plus English**, never one language
   per country: `STEERING`'s single `language` column was right for Türkiye and wrong for
   Kazakhstan, Uzbekistan (Latin, Cyrillic, Russian), Georgia, India, Pakistan, Indonesia, Belgium
   and Switzerland — most of the corridor. The per-language yield in the tally decides which
   languages keep running per (country, family). Field and kind words come from the per-language
   vocabulary (§6.5's Wikidata rule), never translated by the generator.
4. **One angle per query, one or two sentences.** A long query is a blend of pages and returns the
   average; the application page, the eligibility page, the announcement, the about-page, the FAQ
   and the PDF call are six queries.
5. **Cell attributes as words, never as filters** — field (with its local name), level (*MSc,
   M.Sc., Master, Yüksek Lisans*), teaching language (*"taught in English"*); the sweep's
   organisation pass adds the country as an aiming word; the programme pass does not (§6.4a item 5).
   No provider `country`, `search_lang` or `category` parameter — every one measured harmful or
   inert, and `category: company` owed its re-measurement.
6. **Time in words.** *"2027 intake"*, *"Bewerbungsfrist 2027"*, *"2026–2027 burs başvuruları"* —
   Exa's own guidance encodes dates semantically; a freshness angle finds this season's call, and
   `startPublishedDate` stays the recency-windowed pass's tool (§6.7), not the discovery query's.
7. **Nothing negative in the text.** An embedding cannot subtract; aggregators are `excludeDomains`
   on Exa, `-site:` / `$discard` on Brave, and the classifier catches the rest.

The organisation query for a Turkish foundation therefore reads, in one of its six angles, as:
*"Vakfımız her yıl yüksek lisans öğrencilerine burs vermektedir. Burs başvurusu, başvuru koşulları ve
son başvuru tarihi 2026–2027."* The programme query for a chemistry cell, in one of its angles:
*"Our M.Sc. in Chemistry, taught in English — admission requirements, tuition fees and scholarships
for international applicants, application deadline for the 2027 intake."* Both are stored rows;
neither names a person, a school or an employer.
- **Depth and breadth are not in conflict.** The ablation's "25→100 multiplies local funders
  ×1.7–3.4" measured depth *per query*; the saturation cell measured breadth *across queries* (99
  queries, no plateau); the 2026-09-24 sweep bought the first and skipped the second. Breadth first,
  depth where an angle keeps yielding at offset 5+.

**The five measured rules the configuration rests on** (`2026-09-17-search-capability-ablation.md`,
`-search-tool-probe.md`, `-cell-saturation-measurement.md`): (1) **depth is the only capability that
reliably wins** — Brave 3→10 pages +47/+68/+27/+104% local funders (DE/TR/AZ/ID), Exa 25→100
×3.4/2.0/1.7/2.2; (2) **write the query in the local language; never ask a provider to filter by
language**; (3) **no `country` filter**; (4) **precision, not recall, varies by country** — 61% Germany,
40% Türkiye, 26–46% Indonesia, **10–17% Azerbaijan** — and precision sets the reading budget and the
route: where the index is thin the sweep is not the spine and the route switches to the national
register, hub pages, hand curation and Diffbot; (5) **a regional engine pays only where the national
web is large and partly out of reach.** No single configuration exceeded 18% recall on a 377-funder
key — coverage is query volume × depth, never one good call. **The engines are not a pool:** Exa's
per-batch novelty held (124, 63, 45, 43, 45, 38, 34, 42, 42) while Brave fell 81→11 and Tavily 62→5, so
a sweep drops decaying engines by the per-cell tally, keyed by `(family, provider)`.

**Rejected, with the reason, so they are not re-proposed:** Perplexity (overlaps Exa/Brave; Sonar
sunset 27 Sept 2026), Yandex, Seznam, Coc Coc, Mojeek (no binding contract), Google Custom Search
JSON API (closed to new customers, ends 1 Jan 2027), Gemini grounding (its terms forbid "using Links
to identify destination pages for crawling"), Firecrawl `/search` for discovery (unnamed upstream
index — PDF category channel only), Tavily `include_answer` as label enrichment (vendor text, not
quote-verifiable), Diffbot as holder enumerator, Crawl4AI, aggregators as sources, provenance
laundering, Tavily `include_domains` in `prefer` mode, a fixed Brave-first-on-government rule.
**"Exa primary" is a default, not a finding, and the per-family numbers say so** (added 2026-09-23).
The probe's origin-share table has Brave ahead of Exa on **industrial sponsorship (70% vs 50%)** and
**destination-side government (89% vs 66%)**, while Exa leads private foundation, diaspora and every
institution-side family. The table above labels the searched families "Exa primary" (home-side government left that row on 2026-09-24, decision 35); what
actually decides is the `(family, provider)` first-discoverer tally of §6.7, **keyed per family** —
a tally keyed per cell or per corridor would average Brave's industrial lead away. Read "primary" as
the engine that starts, never the engine that stays.

**Owed one measurement each before adoption:** Exa `*.domain` wildcard vs bare hostname (~$0.05),
Brave boolean `OR` phrasing with a different-script check; **`category: company` with client-side
exclusion** (the −2.7 above may be an artefact of a now-rejected parameter pairing); **Websets
`scope` over an import** (below).

**Exa `type: deep` with ten `additional_queries` — measured 2026-09-24, and it is not the fan-out
(owner-approved, billed $0.029).** Ten page-voiced Turkish foundation angles in one `deep` call at
`numResults: 100` returned **27 results, 18 hosts, 16 registrable domains** — not the union of ten
angles at up to 100, but a small synthesised set; 10 of 16 on `.tr`, zero denylisted hosts returned
(`excludeDomains` held), **4 novel against the 214-domain sweep, one of them a real foundation**
(`insanvakfi.org.tr`) and three noise. So `deep` collapses breadth rather than delivering it: ten
`auto` calls at 10 results each ($0.07) can return up to 100 URLs where `deep` returned 27 for
$0.029. **The angle generator is ours to build; `deep` is not adopted for discovery.** Its
`output_schema` synthesis may still have a use the reader can measure (§8.9's cheap first read), and
that is a different question.

**Exa Websets — measured 2026-09-24, owner-run, and it is the comparator, not a dependency.**
Companies entity, four criteria, count 25, on the Turkish foundation family: **310 candidates
analysed, 13 all-green matches, 26 rows, zero newspapers, 25 minutes**; billed *10 credits per
match, 2 per enrichment row, non-matches free*; Pro **$449 / month for 100,000 credits → $0.045 per
verified match**; **API on paid plans only** (`GET /websets/v0/websets` → 401 on the free plan). The
API shape that matters (`create-a-search`): `criteria` ≤ 5; **`scope: [{source: import}]`** verifies
the criteria over a list *we* upload and bills only what passes — the judge role; **`exclude:
[{source: import}]`** is the register set-difference done server-side; **`recall: true`** returns an
estimate of how many matches exist before spend — a saturation figure for free. Not adopted, because
the classifier below does the judge role at ~25× less per host with no plan; kept as the **paid
fallback if Jev fails its gate** and as the labelled set that gate needs. `/agent/runs` (fixed effort
$0.012–$1.00 per run, `outputSchema`, per-candidate criteria verification, no published result
ceiling) stays untested.

### 6.4 Host inventory, hub harvesting, pointers — and why no channel and no tip

**Per registered HEI — the first pass is one Exa call, not a crawl.** `includeDomains=[its domain]`
with the descriptive funding query ($0.022; `tum.de` → FIM and Linde/MDSI scholarships,
`metu.edu.tr` → three fully funded MSc positions and a departmental PDF). Host inventory — crt.sh
`%.<domain>` (one query per domain per second, cached; 235 hosts for METU) plus Firecrawl `/map`
`includeSubdomains` (1 credit; unfiltered map as the fallback when the `search`-filtered one returns
zero) — is the **fallback**; `INFRASTRUCTURE` by pattern (`mail.`, `vpn.`, `sso.`, `cdn.`, `ns1.`),
the rest classified (§6.6) into `INSTITUTION` units with `parent`. DNS brute-force stays forbidden.
Inventory must feed **programme pages themselves**, not only `FUNDING_PATH_TERMS` matches —
programme-scoped money is invisible to path triage (~45% of automatic-on-admission awards sit off any
funding-shaped URL). Programme rows are assembled from a **page set** of one origin: programme page,
fees/funding tab, admission page, cost-of-living page, one linked PDF.

**Hub harvesting.** Ministry, agency and embassy pages list the bodies we want (`edu.gov.az`,
`ytb.gov.tr`, YÖK, VGM, embassy education pages). A hub page **we name** is fetched through §7 and read
with a closed schema `{organisations: [{name, kind, url?}]}` — our own extractor over `readable_text`
(the reference pattern), with Firecrawl's `json` format as the cheaper first read *once §8.9's gate
has measured it*; `/extract` is off (superseded by `/agent` per Firecrawl, 15 tokens per credit).
URL-less names go to the resolver (§6.5). One hop out only.

**Pointers become leads (built 2026-09-18).** Every third party's money a reader meets on any page
(`scope=POINTER`) writes a `ResearchLead` with `found_via=POINTER:<host>` into the register. One
Turkish page named 31 funders the reader used to discard. **Aggregators: fetch everything, names
only, never provenance** (owner 2026-09-18): commercial aggregator pages are read through this
mechanism and the hub extractor; the search-time denylist stays for provenance.

**Social hosts: reversed 2026-09-24, owner decision on their lawyer's advice.** They *are* read
now, through **Browser Use** (`browser-use.com`), as a pointer source like any other. The former
rule and its reasoning are kept below because the reasoning was sound and only the legal premise
moved — Meta's terms §3.2(3) still forbid automated access *"without our prior permission"*, and the
owner's counsel advised on 2026-09-24 that reading public pages through that vendor is available to
this company. **That advice, not a re-reading of the terms, is what changed.** The record, so nobody
re-derives it: Browser Use's own Terms of Service bar *"data mining, robots, scraping, or similar
data gathering"* under User Conduct, place compliance *"solely"* on the customer, and carry an
indemnity for *"your violation of any rights of another"*; the owner took that advice with those
clauses stated. The former rule read: *social hosts are not fetched at all — Meta's and X's terms
forbid automated collection explicitly, and unlike `robots.txt` (not ours to honour) or a TDM
reservation (the vendor's question) that is a published access term, which this repo has treated as
binding since 2026-08-28.*

**Three things the reversal does NOT change**, because none of them rested on the terms:

- **A social post is a POINTER, never provenance.** `facebook.com`, `instagram.com`, `x.com`,
  `linkedin.com` and `bsky.app` stay on `AGGREGATOR_DOMAINS`, so `is_catalogue` still refuses them
  as catalog rows. They contribute a **name and a link**, the origin is then fetched and verified,
  and a claim cites the origin. This is the aggregator rule applied to a different transport.
- **Nothing about a person is ingested.** Commenters, reactors, followers and subscriber lists are
  discarded at the boundary, as §6.4's channel design already requires.
- **An embassy that announces only on Facebook stops being "out of reach and counted as unseen"** —
  which was the whole cost of the old rule, and is now the whole benefit of lifting it.

**Channels and feeds — not built, and nothing human replaces them (decision 2026-09-22).** Telegram channels, local aggregator feeds, mailing lists and Facebook groups
that post scholarships for one nation's students are a real surface, and **nothing has measured that
they reach a scheme the other routes miss.** Once a scheme is known, §9.3 already watches its own page
weekly in announcement season and daily near a deadline, so a channel's only unique contribution is
*earlier notice of a scheme nobody has yet* — plausible exactly where the web is thin (a one-off
embassy quota posted on Facebook and nowhere else), which is also where the whole route is hardest to
justify per adapter. So this stays in §18 with a gate rather than in the build order: run
`PROMPT-new-opportunity-surfaces.md` Parts A–C for two launch countries and read two numbers — the
share of names a channel yields that **no other route found**, and the **median lead time** of a
channel post over the origin's own announcement. A channel that yields nothing new and leads by
nothing is noise with a terms risk attached.

**The design each adapter would take, recorded so the gate does not have to re-derive it:** one
adapter per transport (RSS/Atom, sitemap `lastmod`, Telegram's official API for public channels only —
never a scraped web view and never a user account impersonating a member, a mailing-list archive) and
one *row* per channel carrying country, language, operator kind, subcategories, machine-readable
route, **terms posture** and a verified-on date; a channel whose terms cannot be established is not
read. A channel may contribute a body's **name and a URL it links to**, and **timing** as a *trigger*
for re-verifying the cell it names — never an eligibility claim, an amount or a deadline (third-party
paraphrase), and nothing about a person (commenters, forwarders and subscriber lists are discarded at
ingest). The decisive test is the research prompt's own: *a post that links to the official source is
usable as a tip-off; a post that only paraphrases is not.*

**What covers the gap meanwhile is a machine, not a person: pointers (built 2026-09-18).** Every page
the reader already reads gives up the names of every *other* funder it mentions, and one Turkish page
named 31. That is the tip-off mechanism — a page is a curator, a channel is a curator, and the page is
the one whose terms are settled, whose output is already quote-verified, and which costs nothing
extra because the fetch is already paid for. Hub harvesting is the same idea aimed deliberately: a
ministry or embassy page *is* the local list those channels repost from, one hop closer to the origin.

**No counsellor types anything into this engine, and no design here may make one.** An earlier draft of
this section proposed a human tip route — a counsellor pasting a name or a link — as the substitute
for channel adapters. **Rejected 2026-09-22, owner's objection, and the objection is right on three
counts.** It is friction on the wrong party: an agency buys this product to stop doing exactly that
work, so a coverage route that depends on their data entry sells the problem back to them. It is
unmeasurable: a tip yields no denominator, so a family "covered by tips" can never report the
`bodies known ÷ list size` or the estimated-unseen number §15 requires, and the coverage line would
be a guess wearing a number. And it would be the first place the platform's own promise inverts —
§9 already refuses a counsellor in the cycle-verification loop on the owner's instruction that *the
system verifies by its own*; a human input at the discovery end contradicts that at the other end of
the same pipeline.

So a scheme that exists on no page any route can reach is **out of reach, and is reported as such**
(the estimated-unseen figure, §15), never quietly backfilled by a person. That is the honest position
and it is also the cheaper one: the day channels are worth having, the gate above says so and an
adapter is built — machine, terms-checked, measurable.

**The one human input that stays is the student's own, and it is not data entry.** R5 **affiliation
lookup** (owner 2026-09-18): the consultation already asks a student for their employer, prior
university, home region, faith community, professional body and bank — facts about themselves, on a
form they are already filling — and the engine then looks *those organisations* up by public name
(register first, then the resolver; never a personal fact in a query). It is not a tip route: the
student answers a question about their life, and the machine does every step after it. Their awards
land in the shared catalog while the student's link to them stays tenant-private, and these queue
items are top priority because they block a real pack.

### 6.4a Programme enumeration — the other half of a pack, in one place

Everything above enumerates **bodies that hold money**. A pack also needs **programmes**, and a
student picks a programme first: a pack is programme applications plus award applications (§10.3).
That half is described across §6.2 (registers), §6.4 (inventory) and §8 (the page set) and is
gathered here because it is a separate enumeration with its own denominator, and because the last
full discovery run wrote **zero catalog rows** — no single page carries a whole programme row.

Per registered institution, in order, stopping when a route yields the programme index:

1. **A national programme register where the country publishes one** (§6.2) — complete for that
   country, and the only route with an exact denominator. A registry row is an `AGGREGATOR`: it seeds
   identity and routes to the institution's own page, and liveness is confirmed at the origin, never
   from the row (Korea's file carries 49% abolished departments that look exactly as live).
2. **One Exa call restricted to the institution's domain** with a descriptive query for the field
   (measured $0.022; it surfaced departmental and unit pages a crawl reaches only by enumerating).
   This is the first pass, not the fallback, and it is the same call that finds programme-attached
   money — one call answers both questions.
3. **Sitemap, then `/map`, then the crawl** (§7.5) — the fallback. Measured weak as a spine: 2 of 5
   major universities expose programme detail pages in a sitemap, a funded graduate school on its own
   subdomain is invisible to the parent's sitemap, and a widened path regex made results *worse* (0
   matches against 128 on Sorbonne; housing and parental-leave pages on TUM). Path shape is a CMS
   artefact, not a semantic signal.
4. **Funder-side seeds** — the EACEA API for every EMJM (§6.2) and ANR's graduate schools; these find
   funded programmes *before* the university publishes a page.
5. **One open-web embedding pass per cell attribute set, page-voiced** (owner 2026-09-24 — the
   "hidden gems" route, re-based). Exa `type: auto`, the programme angles of §6.3's page-voiced
   block, `numResults` 10–15 per angle, `excludeDomains` = `AGGREGATOR_DOMAINS`; Brave the same
   vocabulary as terms with the inline Goggle. **The query carries field, level and teaching
   language** — the cell attributes §10.5's Exa/Brave allow-list permits, and nothing that names a
   person, an employer or a school with a field; the profile → cell step is the one place a model
   reads the profile. **Country is not in the cell-level query** (decision 20, §6.7: an aiming term
   for organisations, an *output* for programmes, asserted by test) — a hidden gem is precisely a
   funded programme in a country the student had not aimed at, and the host's country is read off
   the origin afterwards and filtered against the student's cells. **At the tap, the student's own
   stated destinations may appear as words** (§10.5 step 2 — the student chose them; that is what
   D.6's allow-list meant by "destination countries"), never as a provider `country` parameter.
   Field enters in the page's language — ISCED-F labels per language from Wikidata (*Chemistry /
   Chemie / Kimya / Chimie*), the way §6.5 takes kind words — and the intake year is an angle of
   its own (*"Bewerbung für das Wintersemester 2027/28"*), because Exa encodes dates semantically
   and a programme page names its intake. It runs twice: as the tap's stage-1 field-aimed query
   (per student, deduped against the register before any fetch) and as a **cell-level pass** whose
   results serve everyone in the cell (§10.5 step 5). **A hit is a page, and a page becomes a
   programme only through an institution the register vouches for:** a hit on a host bound to a
   registered HEI (DEQAR, ROR, Wikidata, a national register — §6.2) seeds that origin's page set
   (below); a hit on a host bound to nothing is classified (§6.6) and, if `INSTITUTION` or
   `RESEARCH_INSTITUTE`, becomes a **`SITE_UNVOUCHED` queue item** (§11) — never student-facing
   until a person or a register confirms it. That is `CLAUDE.md`'s provenance guard, owed before any
   production run carries a search key, and this item is the run that makes it due. **What this
   replaces:** `EntityExpansionSource`'s search half — *"{field} research institute graduate
   school"* on the Tavily leg — is retired; its **sitemap walk is kept and re-aimed at register
   rows** (`OrganisationDomain`, verified funders and institutions), which is the half that finds
   programme pages. The three programme-page mechanisms — sitemap walk, Firecrawl `/map`, the
   domain-restricted Exa call of item 2 — are **measured against each other on the ~30 Turkish
   foundations already held** before one is preferred; item 2 is the first pass until then.

**The same two steps for every family — find the body, then read its own pages — and what varies is
two inputs (owner 2026-09-24).** The 2026-08-27 premise survives every measurement since: a gem is
a body's own page, never an indexable "position", so the route is *bodies from the ladder → that
body's pages*, with the open-web page-voiced pass (item 5) only for bodies no rung holds. Per family
the ladder rung supplies the bodies and the **angle vocabulary** says what step 2 looks for; the
mechanism order is the same everywhere — **domain-restricted Exa call first ($0.022), sitemap and
`/map` as fallback, crawl last** — except where the owner's read gate says a body is not walked at all.

| holder types | bodies come from (§6.2 rung) | step 2 looks for (the angle vocabulary, per language) | not this |
|---|---|---|---|
| `INSTITUTION`, `RESEARCH_INSTITUTE` | HEI registers (DEQAR, ROR, Wikidata, national), umbrella institute lists (Max Planck, Helmholtz, TÜBİTAK, CNRS) — rung 1–3 | programme page; fees-and-funding tab; admission page; departmental scholarship page; graduate-school call; *"fully funded MSc position"* | professor-level funded slots — not indexable (08-27 probe, rank 6 behind Reddit); reached only as `ECOSYSTEM_CLUE` |
| `PRIVATE_FOUNDATION`, `POLITICAL_FOUNDATION`, `RELIGIOUS` | foundation and charity registers (rung 1 where the purpose is on it — VGM; rung 2 — BZSt), umbrella associations (rung 3), the page-voiced sweep (rung 4) | scholarship-application page; eligibility page; season announcement; first-person about-page; FAQ; PDF call | a news round-up naming the foundation — a pointer, never the page |
| `NATIONAL_GOVERNMENT`, `SUBNATIONAL_GOVERNMENT`, `EMBASSY_BILATERAL` | closed lists and hub pages (ministries, agencies, study-in portals) — rung 1; subnational bodies from Wikidata's class | scheme page; the year's call; the study-in portal's scholarship section; the embassy's education page | an embassy announcing only on social — the pointer route's job (§6.4), never a walk of `facebook.com` |
| `EMPLOYER` | corporate foundations through the foundation registers; direct corporate scholarships through **the largest-employer lists as rung 2** (stock exchange, chamber of industry — decision 36), then the sweep for the residue, plus pointers from pages the reader met | *"scholarship programme / bursary / sponsorship for students"* page; CSR or foundation arm — **one domain call per listed company, read only on a positive hit** | the company's whole site — never walked; the page set only after the hit |
| `PROFESSIONAL_BODY`, `BANK_OR_LENDER` | per-country registers as the **denominator** (rung 2) | **only on a signal**: a `POINTER` already met, or one domain-restricted call returning a scholarship, bursary or education-programme page | never walked (owner 2026-09-23): hundreds of bodies, almost none fund students — `bodies known` counts them, `bodies read` does not |
| `INTERGOVERNMENTAL`, `REGIONAL_FUND` | the global cell-tagged closed list (§19) — rung 1 by construction | each body's scheme page and call | search — measured 0–50% origin on every index |
| `DIASPORA_AFFINITY` | Wikidata's class × **host** country, the sweep keyed `(host country, home language)` (decision 37), pointers from embassy and ministry pages | scholarship page; membership-conditioned award page — the angle set written in the **home** language on a host-country pass | a country row — a diaspora body has two countries, and one-country steering finds neither |
| `ALUMNI` | derived from institutions — one association per HEI, reached by the institution's own domain call | the association's scholarship page | open-web search (§5: settled) |

**Exa `findSimilar` is live, and it is a rung-3 source, not a gem finder — measured 2026-09-24.**
The 09-17 probe recorded it deprecated; the 09-18 audit and this call say otherwise: `POST
/findSimilar` on `tev.org.tr/burslar` with `excludeSourceDomain`, **HTTP 200, 10 results, $0.007**.
Of the ten hosts: two peer foundations (`yetev.org.tr`, `ted.org.tr`), three university units, TEV's
own application portal on another domain, and four aggregator, news and donation-platform hosts. So
**20–30% peer bodies per call**, at a third of a search's price — worth running once per *verified*
funder as "more like this body", every hit through `is_catalogue` and the classifier like any other
URL, and tallied as its own `(family, provider="exa:findSimilar")` first-discoverer row so it is
dropped where it stops paying. Not a programme-page finder: it neighbours *sites*, not pages within
one.

**A programme row is assembled from a page set of one origin** — programme page, fees/funding tab,
admission page, cost-of-living page, one linked PDF brochure — with `require_same_origin` on every
page in the set and extraction run over the *set*, not one page (`pipeline._HeldPage` already holds
pages across a run). Identity comes from the register, else the programme URL. **Field is a tag, not
a query**: one cached read per programme at ingestion writes ISCED-F-derived `tags`, the profile gets
the same tags, and matching is tag overlap plus the existing fit dimensions — the case-folded
substring test on `Program.name` becomes one signal, never the gate (gate: 50 programme names
hand-mapped, ≥ 90% agreement). **Coverage is reported per destination × discipline as
`visited / partial / unknown` from the first run**, and an unreadable page set is recorded
`unreadable`, never as "no funding".

**The known-answer set is the yardstick and the first real catalog content:**
`docs/research/programme-funding-known-answers.csv`, ~50 real programme-attached awards built by two
blind research runs and verified against the official page. The crawl must reach each through a route
whose trail names **no scheme and no programme**; a hit whose logged query names it fails.

### 6.5 Name→site resolution — v4, general rules, and what stays unresolved

**Rung 0 — the e-mail domain, free (added 2026-09-24).** A register row that carries an own-domain
e-mail (`iletisim@1870vakfi.org`, `yekuv@yekuv.org`, `vakif1972@vakif1972.org.tr`) resolves to that
registrable domain with no call: it is the organisation naming its own host. A free-mail address
(`gmail.com`, `hotmail.com`, `outlook.com`, `yahoo.com`, `yandex.*`, `mail.ru` and the list
`FREE_MAIL_DOMAINS` pins) resolves nothing and the name goes to the chain below. Roughly two-thirds
of VGM's rows carry an own-domain address. A rung-0 host is still a `CANDIDATE` — the classifier
(§6.6) confirms what lives there — and a domain shared by more than one register row is a queue item,
never a merge (§6.1's "never on a name" applies to an e-mail domain too).

**Adopted (measured 2026-09-18, German 20/0/5, Turkish 12/1/12 — correct / confident-wrong /
unresolved):** Wikidata P856 → Tavily top 10 (`basic`, denylist; **`search_depth: advanced` measured
5× worse at resolution** — it returns the Wikipedia article) → tiered lexical score over distinctive
name tokens (initials / full slug = 3; two distinctive tokens, or one token + the name's org-word
forming the label = 2; one token ≥ 6 chars or label = one token = 1; +0.5 org-word in label, +0.25
country ccTLD; **best score, ties by rank** — rank 1 was the whole problem, 12% → 80%) → every pick
below tier 3 is fetched through §7 and accepted only if its `<title>`/`og:site_name` (a) names the
same *kind* of organisation and (b) contains a distinctive token, the acronym or the slug → otherwise,
on any fetch failure, and for any **one-token name**, *unresolved*. Selection lives beside the register
writer, not in the adapter; `TavilyProvider.candidates(name)` returns URLs only.

**The blind hold-out failed (Georgian 5/3/17, Kazakh 1/11/13) and set six requirements, all data-not-rules:**
(1) the organisation-kind vocabulary is enumerated from Wikidata's subclass tree (~50 kinds, 26+
languages), and **a candidate whose label is nothing but kind words is a directory, never an
organisation** (`embassies.info`, `stiftungen.de`); (2) country labels, demonyms and settlements come
from Wikidata (P17 → P31 city), never a typed list; (3) a token that *ends with* a kind word is a kind
word (*Bundesstiftung*); (4) **resolve with every name variant the register or Wikidata supplies**
(native, English, Russian) and score the union — Georgian domains are acronyms of the English name;
(5) some truths are unreachable by name (an embassy on its ministry's domain) and *unresolved* is the
correct output; (6) provider variance is 1–2 in 25 per repeat call — A/B two selectors in one process
on the same responses, never across runs. The next version is measured on a **fresh** hold-out (Uzbek,
Indonesian or Vietnamese), never Georgia or Kazakhstan again.

**Residue:** Diffbot `Enhance` by name (7/10 on the syllabic-acronym and Georgian-script names no
lexical rule reaches; confidence 0.16–0.54, so its answer takes the same title check; 400 entities a
month sizes it to the residue). What is still unresolved is a **`SITE_UNKNOWN`** queue item (§11).
Unresolved is 20% German / 48% Turkish and **is the honest shape**, not a defect to tune away.

### 6.6 Classification of a new host — Jev, gated (amended 2026-09-24)

**The classifier is TypeSafe Jev** (`apps/documents/research_fit/jev.py`'s transport; owner decision
2026-09-24, on cost and on the shape of the question), **with the frontier classifier this section
used to specify as the abstain path.** **Before any fetch, the registry-verified suffix answers for
free** (`domains.verified_kind`, built in PR #128 and unused): `.gov.tr`, `.edu.tr`, `.ac.uk`,
`.go.id` and the rest of `VERIFIED_SECOND_LEVEL` are allocated only against documents the registrar
checked, so a host under one carries its `kind` with no model call — the classifier runs on the
ambiguous tail (`.org.tr`, `.de`, `.com`) and `funds_students` still has to be read off the page for
every host. Then: fetch the origin through §7; `readable_text` of the homepage
(plus the one scholarship-path page if the sitemap or `/map` yields it) labelled as data, capped at
6,000 tokens; one Jev call asking the same **closed questions** every country gets — `kind` as a
*choice* over §5's sixteen holder types, `funds_students` as a *decision*, `country_code` as a
*choice* over ISO codes — each answer with Jev's own probability. **Each choice carries a one-line
plain-words definition** (the `_KIND_CRITERIA` shape `jev.py` already uses: *"a private foundation:
an endowed non-profit that awards money from its own funds"*; *"funds students: awards money
directly to individual students for degree study — not grants to institutions, not research
funding"*), because a typed model decides against the criteria it is handed and an undefined label
is a coin toss in a different script. Definitions are data beside the sixteen kinds, one set for
every country. A page under `readable_text`'s 1,500-character floor is `unreadable` (§7.4) and is
never classified — a shell is not a `funds_students=false`. Cached by domain;
`rate_limited("org-classify", …)` per run. **Abstain rule:** any answer below a pinned probability
(`ORG_CLASSIFY_MIN_P`, 0.8 until the gate says otherwise) routes the host to one
`OPENAI_EXTRACTION_MODEL` call with the same schema, so a thin reading never becomes a wrong
`kind`. A host marked `REJECTED` (reason `INFRASTRUCTURE`, `AGGREGATOR`, `FREE_MAIL_ONLY`) or
`funds_students=false` above the threshold is stored so it is never fetched twice and never read.
**Mandatory before the reader everywhere**, not only in thin-index countries — the register ladder
(§6.2) now delivers thousands of names per country, and the classifier is what keeps the reader off
the ones that fund nothing.

**Cost, which is the decision.** Jev: 64k context, **$0.04 per million input tokens, output free**
(TypeSafe's published price; `jev.py` records $0.042). A homepage is 1–3k tokens → ~$0.0001 a host;
**the whole VGM register is ≈ $0.40 in model and ≈ $3.40 in Firecrawl fetches, about $4**, against
≈ $92 through Websets `scope` on a $449/month plan and ≈ $4–12 through the frontier classifier
alone. So the classifier is no longer a cost term; the fetch is.

**Gate — before any count is quoted, and before Jev replaces anything:** ≥ 95% on `kind` **and** on
`funds_students` over a labelled set of at least 100 hosts spanning **at least two scripts** (Latin
plus one of Turkish-with-diacritics, Cyrillic, Georgian, Arabic-script Urdu), because whether Jev
reads the corridor languages as well as English is a fact to measure, not to assume. The labelled set
exists already: the 26 Websets rows with their per-criterion verdicts, the 72 hand-labelled Turkish
hosts of the 2026-09-24 sweep, and the ~30 foundations held on `.org` — Websets' output is a
vendor model's opinion, so those labels are checked by a person before they grade anything. Report
abstain rate beside accuracy; a classifier that abstains on 40% of hosts has moved the cost back to
the frontier model, and the gate must say so. **Not built**; `TYPESAFE_API_KEY` exists in settings
and in no environment yet, and Jev's DPA question (`jev.py`) does not arise here — an organisation's
homepage is not student text.

**What Jev cannot do, so nothing above claims it:** find a host (discovery is the register and the
sweep), or read an award (a `LineVerdict` carries amounts, deadlines, conditions and a quote — §8's
job, unchanged). If the gate fails, **Websets `scope` over an import is the paid fallback** (§6.3),
already measured, at $0.045 per host that passes.

### 6.7 The sweep — cells, an economic stop, and the reading queue

One dense cell measured (Germany × private foundation, 99 queries, 396 calls, ≈ $2–6 as the two notes
record it): **353 German funders, 116 foundations, and no saturation** — 15–27 new per eleven queries
with batch 6 finding more than batch 3, the late arrivals being real long-tail bodies no register
lists. So for the open families **the sweep, not the register, is the spine**, and its output is a
**curve, not a completeness claim**: "swept to N queries, plateau R per batch at precision P, spend S".

For each sweep pass `(host country, family)` — **not per cell; see §5's correction**, where phrasing
set, language and eligibility keys are loops inside the pass rather than axes of it: **the register
ladder runs first** (§6.2 — the pass begins with every name the country's rungs 1–3 supply, resolved
and classified, so the sweep is paid for by its set-difference against a real denominator, never
against an empty register); then the model generates the **angle set** — page-voiced queries per
§6.3's rule — from the family's definition in **every official and administrative language of the
country (Wikidata P37) plus English**, the yield per language tallied (decision 38); engines run in
their §6.3 roles, **breadth first** (each angle at `numResults` 10–15; depth on an angle only while
it keeps yielding); the harness counts **new origin hosts per batch** and each engine's
first-discoverer share by `(family, provider)`, **and per angle**, so a dead angle is dropped the way
a decaying engine is — **where `family` is the host's *classified* family (§6.6), not the pass that
found it**: a foundation pass that surfaces a ministry and two universities (as the 2026-09-24 TR
sweep did) gets no credit for them, or the tally rewards the pass for noise. **Two stop rules, whichever fires first** (amended 2026-09-24): the economic
one — *cost per new verified award exceeds what the option is worth to a student* (inputs: plateau
rate, precision decay) — and the set-expansion literature's — **no new verified host for three
consecutive batches** (SetExpan / GenExpan's stopping condition, the plateau made mechanical). Where
the index is thin (§6.3 rule 4) the route switches before the sweep is scaled. **The 2026-09-24
Türkiye sweep is the calibration of what this paragraph used to permit:** two queries per provider at
100 results, no register first, 72% precision on the `.tr` leg and under 1% of the register reached.

**Reading is the binding constraint** (353 funders × up to nine model calls a page against $2 of
searching), so the sweep produces a **queue**, read free-to-apply first (§5), then by student demand,
cell thinness and announcement season (§9.3). Corridor order is a priority, never a classification:
Azerbaijan and Türkiye home-side; Germany, Netherlands, Sweden, Hungary, France, Italy destination-side;
then Caucasus/Central Asia; then India, Pakistan, Vietnam, Indonesia — **each as both** origin and
destination. Country is an **aiming term for organisation discovery** and stays an **output** for
programme discovery (no `LeadSource` receives it for programmes; asserted by test). Registries
re-enumerated monthly by diff; inventory per HEI quarterly; search sweeps per corridor once per
admissions cycle plus a recency-windowed pass (Tavily `time_range`, Brave `freshness`, Exa
`startPublishedDate`) monthly in announcement season.

## 7. Layer 2 — the fetch engine

**Vendor-only (owner decision 2026-09-18 evening). The paid plans are not yet bought — they will be
when the startup is funded (owner, 2026-09-22).** Until then: the ladder order below stands unchanged
on the free tiers (measurement-scale work sits inside 6% of either quota — 09-18 §4.1c), the
configuration defaults are the **free-tier** numbers (Firecrawl 1,000 credits, scrape.do's measured
1,000; buying Standard + Hobby is a change to five numbers in `config/settings/base.py` and nothing
else), the per-key spend limit and the USD sweep budget protect that quota, and the three volume
features — monitors (§7.6), the navigator (§7.5) and any corridor-scale sweep (§6.7) — **wait for the
plans**. Our own egress fetches research pages for nobody. The Scrapling tier, `browser_server.py`, every `Browser*`
resource and `LocalEgressProxy`'s research role are retired (deleted by PR #103; `LocalEgressProxy`
leaves with the portal deletion). First-party transports that **stay**: `europass.py`'s `_request`
(student PII, pinned address, DNS-rebinding guard), `egress.fetch_json_api` (contracted APIs — Exa,
Brave, Tavily, Diffbot, SerpApi, Wikidata, ROR, DEQAR Connect, EACEA — our keys never travel through a
vendor), `egress.fetch_data_file` (register CSVs, JSON, sitemaps — machine files, never a page a
reader reads). A test asserts every `FetchAttempt` host is outside the never-vendored set and that
`fetched_via == "EGRESS"` occurs only for `europa.eu`. **No fetch vendor is ever pointed at a
portal** — there the agent acts as an authenticated applicant and `phased requirements.md` §2/§3.4
forbid circumventing access controls; that rule is legal, not a cost.

### 7.1 The seam

```python
fetch_page(url, *, purpose="read", tag=None, require_origin=None, budget=None) -> FetchedPage
```

`retrieve_official_source(url)` keeps its signature and delegates (PR #103 already does this from
`apps/research/fetch/`). `purpose="read"` (default): Firecrawl first, `changeTracking` on.
`purpose="bytes"`: the origin's untouched bytes must be defensible (a snapshot digest, a dispute) —
scrape.do with `transparentResponse=true`. `tag`: the change-tracking scope, defaulting to
`OfficialSourceSnapshot.admissions_cycle`. `require_origin`: `require_same_origin` (scheme + host,
never the whole URL) applied **before** any bytes are persisted or read. `budget`: the sweep's budget.

`FetchedPage` extends `FetchResult` with `markdown`, `outcome`, `fetched_via`, `rung`, `credits`,
`cost_usd`, `status_code`, `change_status`, `captured_at`, `page_count`/`total_pages`, `screenshot`,
`attempts`. **The digest is over `markdown`, not `body`** — Firecrawl's `rawHtml` is its own rendering
and varies between fetches of an unchanged page (189,682 vs 422,515 bytes for FAU). HTML readers keep
`readable_text(rawHtml)` with its section selection; document readers (PDF/DOCX/XLSX/PPTX/ZIP members
via `/v2/parse` + `zipfile`) read the vendor markdown with `pageMarkers`.

### 7.2 The ladder — seven rungs, stops at the first usable document

*Usable* = a document, content type in the existing allowlist, under the 10 MiB cap, and **not a
shell** (fewer than 1,500 readable characters at ≥ 20,000 raw bytes; a 200 under 1,000 bytes or
carrying "Just a moment" / "Enable JavaScript and cookies" is a **block**, not a document —
mischolarship.com returned 200 and 469 bytes and was billed 1 credit).

| rung | call | tried when |
|---|---|---|
| 1 | Firecrawl `POST /v2/scrape`: `formats: ["markdown","links","rawHtml",{"type":"changeTracking","tag":<tag>}]`, `parsers: [{"type":"pdf","maxPages": FETCH_PDF_MAX_PAGES,"pageMarkers": true}]`, `skipTlsVerification: true`, `blockAds`, `onlyMainContent`, `timeout` from the host profile; `proxy` not passed (`auto` is the default and escalates to enhanced on 401/403/429 at +0); `location` only when the profile says geo-gated | always first unless `start_rung` > 1 |
| 2 | rung 1 + `actions: [wait 3000, scroll down, wait 2000]` and `waitFor` from the profile (2 credits per browser-minute) | rung 1 returned a **shell** |
| 3 | scrape.do `GET` `render=false&super=false`, `geoCode` when geo-gated, `timeout` from the profile; provenance from the **`scrape.do-resolved-url` header (absent → raise)**, validated by `validate_public_url` — the `disableRedirection` hop-by-hop guard was removed after the live run showed the residential proxy sees a Cloudflare bounce first (PR #103) | rung 1 returned **no document** (network, 5xx, timeout), or a 401/403/429 survived the enhanced proxy |
| 4 | scrape.do `render=true&super=true`, `sessionId` fixed per host per sweep, `waitSelector`/`customWait`/`playWithBrowser` scroll from the profile, `screenShot=true` (25 credits = $0.0029 — under 1% of one reader run) | rung 3 failed, or rung 2 was still a shell |
| 5 | **retry queue** — `FetchAttempt(outcome=RETRY_SCHEDULED, retry_after)`; `manage.py retry_due_fetches` re-enters at the host's `start_rung`. Network class +24 h / +48 h / +96 h; block class +6 h / +24 h / +48 h; three attempts; paced through `DomainLease`; a due retry inside `blocked_until` is rescheduled, not spent | rungs 1–4 failed |
| 6 | **archive** — `archive.org/wayback/available` names the closest capture; if within `FETCH_ARCHIVE_MAX_AGE_DAYS` (365, owner 2026-09-22) fetch `web.archive.org/web/<ts>id_/<url>` through rungs 1 then 3; the URL inside the archive URL must satisfy `require_same_origin` | retries exhausted (DAAD and Sciences Po were recovered this way) |
| 7 | **human** — `record_blocked_source` writes a `ResolutionItem` (`HOST_UNREACHABLE`, §11) whose reason names the outcome and whose trail is the `FetchAttempt` rows, with the screenshot | no fresh capture, or `UNREADABLE` after rung 4, or `OFF_SITE`, or `DEAD` from a catalog row |

**Failure classification (measured live, PR #103):** outer 429/5xx/transport → back off (1 s … 60 s)
and retry Firecrawl, never a block; outer 402 → stop the sweep (`BUDGET`); other non-200 outer →
never escalate; target 404/410 → `DEAD` at rung 1, exactly one attempt; target 401/403/429/5xx and
outer 408 → escalate. Firecrawl hard failures charge nothing; a 403/404 costs 1 credit; scrape.do
failures are free. Every attempt carries an `x-request-id` (the `FetchAttempt` id) so a client-side
timeout cannot be charged twice (Firecrawl answers 409). **No distributed semaphore**: the vendors
queue over-limit work themselves.

### 7.3 Host memory — `HostProfile`

One shared-catalog row per host (lowercased, IDNA): `start_rung` (only *expensive* rungs are
remembered — success at 3 or 4 sets it, success at 1 or 2 resets it), `needs_render`,
`needs_residential`, `geo_code`, `languages`, `wait_selector`, `custom_wait_ms`, `timeout_ms`,
`vendor_options` (closed keys `showFrames`, `setCookies`), `last_success_rung`, `last_success_at`,
`last_probe_at`, `blocked_until` (+6 h doubling per consecutive block, capped at 7 days),
`robots_blocked_paths`, `credits_30d`, `cost_usd_30d`, `attempts_30d`. **Re-probe:** a host with
`start_rung > 1` and `last_probe_at` older than `FETCH_REPROBE_DAYS` (30) is tried once from rung 1.
A rung is skipped only because the profile learned it was useless, never because a heuristic guessed.
(`HostFetchCost` on `claude/reader-holder-axis` folds into this table.)

### 7.4 Outcomes — the closed set

| outcome | meaning | `OfficialSourceSnapshot.retrieval_status` | downstream |
|---|---|---|---|
| `FETCHED` | usable document | `CURRENT` | the reader |
| `FETCHED_PARTIAL` | PDF cut at `maxPages`, or `readable_text` overflowed | `CURRENT`, `render_status` `:PARTIAL` | reader; provenance shows "read N of M pages" |
| `UNCHANGED` | `changeStatus == "same"` for this `tag` | no new snapshot | **reader skipped — the saving that pays for everything** |
| `ARCHIVED` | capture ≤ 365 days, same origin | `CURRENT`, `render_status = "ARCHIVE:<date>"` | reader; every rule carries the capture date |
| `UNREADABLE` | shell after rung 4 | `unreadable = True` | rung 7 |
| `BLOCKED` | 401/403/429 or challenge at every rung; retries exhausted | `BLOCKED` | rung 6 |
| `UNREACHABLE` | no document at every rung; retries exhausted | `FAILED` | rung 6 |
| `DEAD` | origin answered 404/410 | `FAILED` | rung 7 for a catalog URL; dropped for a discovery URL |
| `OFF_SITE` | final URL left the required origin | `FAILED`; **no bytes persisted** | rung 7 — a moved site is a catalog fix by a person |
| `INVALID` | `validate_public_url` refused the URL or a hop | none | logged; rung 7 for a catalog URL |
| `BUDGET` | sweep budget, remaining-credit floor or 402 stopped the call before it was made | none | sweep stops; `RETRY_SCHEDULED` for the next window |

`RETRY_SCHEDULED` is the one intermediate state and never reaches a caller. Every outcome carries
`fetched_via`, `rung`, `credits`, `cost_usd`, the validated `final_url` and the trail.

### 7.5 Site jobs — what "the crawler" is

Most of it is a vendor call; our code owns the order, the vocabulary (**per reader** — the funding
reader's `_FUNDING_TERMS`/`FUNDING_PATH_TERMS` + the cycle vocabulary of §9.2; the CV reader's own;
never widened inside the engine), the residue and the outcomes.

- **Inventory** `POST /v2/map` — `search` = the caller's term list in the site's languages,
  `includeSubdomains: true`, `ignoreQueryParameters: true`, `limit: 500`, `ignoreCache: true` at the
  start of a cycle; unfiltered map as the fallback. 1 credit whatever it returns.
- **Rank** — URL terms, then each fetched page's `links` (free), then depth from the landing page. No
  model.
- **Crawl** `POST /v2/crawl` — one short RE2 `includePaths` pattern per term; `excludePaths` news,
  events, staff, login; **`crawlEntireDomain: true`** (a requirements page is a *sibling* of the
  programme page); `allowSubdomains: true`; `allowExternalLinks: true` (the one-hop PDF on a CDN);
  `maxDiscoveryDepth: 2`; `limit: FETCH_CRAWL_LIMIT` (25) per host per sweep (15 for a cycle-verification
  crawl); `sitemap: "include"`; `scrapeOptions` exactly as rung 1; `maxConcurrency` from configuration
  (**1 for corpus runs** — results vary between runs); `delay` when `robots.txt` names a crawl-delay.
  Then **`GET /v2/crawl/{id}/errors`, always** — the status counters cannot say anything failed;
  `errors[]` enter the per-URL ladder at rung 3, `robotsBlocked[]` are written to the profile and
  never fetched by any tier. Ceiling per host `limit × (1 + FETCH_PDF_MAX_PAGES)`, checked against
  the budget before submission.
- **Navigator** `POST /v2/agent` (after the plans are bought) — only when crawl + ranked residue produced no rule-bearing page;
  `urls: [site root, landing page]` (its own web search reaches an unread index — off), a fixed
  per-reader prompt asking for *the pages* that state funding / application-document requirements,
  schema `{pages: [{url, why}]}`, `maxCredits: FETCH_AGENT_MAX_CREDITS` (300), `effort: "low"`. **Its
  answer is discarded**; the URLs in it and in the trace are fetched through the ladder as leads to
  confirm. Never runs on a programme the crawl already served. The in-house harnessed navigator is
  built only if the labelled corpus's hard subset shows `/agent` missing pages a person finds.
- **Screenshots** — on the final attempt before rung 7 and at rung 4, to the evidence bucket under
  `screenshot_object_key`, so the person in the queue sees what the engine saw.
- **The four outcomes per programme or organisation, each with evidence:** *found* (rules/awards
  with page, quote, page number) · *none stated* (the sentence that says so, verified) · *blocked or
  unreadable* (the trail, the screenshot) · *not found* (what was searched: map, crawl list, residue,
  navigator leads). Reading is rolled up **per organisation**: *read completely on date X, N pages,
  M unreadable, at rungs T* — the "known but unread" state the scheduler needs.

### 7.6 Refresh

> **Superseded for programme pages, 2026-09-26.** The refresh cadence for programme pages is the
> institution provenance gate spec's §10: once per programme per cycle after it opens (twice for
> two intakes), again when it enters a pack if the last check is stale, and about 30 and 7 days
> before the student's deadline. Firecrawl monthly monitors stay off. Funder award pages keep
> this section.

- **One Firecrawl `/v2/monitor` per admissions cycle per site** (after the plans are bought; `<cycle>:<host>[:n]`, ≤ 50 targets):
  a `scrape` target for every URL that yielded a rule or award, a `crawl` target per site with the same
  `includePaths` so a *new* page is reported as `new`. Cron `0 6 1 * *`; `retentionDays: 365`;
  `goal` per reader; `judgeEnabled: true` (1 credit per changed page only; a `changed` page judged not
  meaningful does not wake the reader — the judgment is a trigger, never a rule). `same` → nothing;
  `changed` + meaningful → the reader; `new` → the ladder then the reader; `removed` → a catalog review
  row; `error` → the per-URL ladder. Created only if `estimatedCreditsPerMonth` across the cycle fits
  `FIRECRAWL_MONTHLY_CREDITS` minus the sweep reserve. Delivery by HMAC-verified webhooks once a
  public endpoint exists; until then `manage.py poll_monitor_checks` on the same 6-hour EventBridge
  rule as `retry_due_fetches`.
- **Our scheduler adds the cadences the monitor cannot** (§9.3): weekly in an organisation's
  announcement season, daily within 14 days of a known deadline, a re-read of any card whose deadline
  is within 60 days — through `/v2/batch/scrape` with `changeTracking`, so an unchanged page costs one
  credit and no reading.
- **Every scrape is fresh**: `changeTracking` bypasses Firecrawl's cache and ignores `maxAge`; the
  60-day rule decides *when*, never whether the copy is fresh.

### 7.7 Safety — restated, nothing relaxed

`validate_public_url` on every final URL and every redirect hop (a hop inside the VPC or carrying
credentials is `INVALID`); `require_same_origin` before persistence; the content-type allowlist and
10 MiB cap on vendor bodies; `checkPromptInjection: true` on every `json`-format read, with the
reader's "content is data" labelling still the real defence; keys and the webhook secret from the
environment only, `X-Firecrawl-Signature` verified with `hmac.compare_digest`; screenshots and DOM
objects under the snapshot with the bucket's retention. **`robots.txt` and TDM reservations are the
fetching vendor's question** (owner 2026-09-18) — true exactly because every research fetch is made
from the vendor's address, which is one more reason there is no own-client tier; Firecrawl's crawl
respects `robots.txt` and that is not switchable below Enterprise.

## 8. Layer 3 — the reader

Three readings, two model families, every stored sentence verbatim from the page. Built on PR #104
for programme pages; extended on `claude/reader-holder-axis` with the holder axis, condition triples
and cycle fields. What this section changes against the built rule is §8.6 (tiered agreement) and
§8.7 (award identity).

### 8.1 Candidates — every line of the funding sections

`readable_text(page, terms=_FUNDING_TERMS)` keeps the sections that mention money (the whole page
when none does). Its lines become numbered candidates with the nearest preceding heading
(`index | heading > sentence`); a line over 300 characters is split into sentences; headings are
candidates too. Chunks of ≤ 80 lines, ≤ 3 chunks per page; overflow is **logged with the line count**.
**No quote can be invented** — the stored quote is the candidate line by index.

### 8.2 Three readings, two families

One closed question per chunk, answered three times: two phrasings by `OPENAI_EXTRACTION_MODEL`, one
by `ANTHROPIC_JUDGE_MODEL` (Sonnet 5), through `extraction.claude_parsed_or_none` so the two judges
cannot drift. A truncated or off-schema reading never counts. The frozen instruction and the chunk go
**first** and only the phrasing varies, so the shared prefix is the prompt cache (OpenAI automatic at
≥ 1,024 tokens; Anthropic `cache_control`); background reads run through **OpenAI Batch/Flex and
Anthropic Message Batches** (50%). `pipeline._fund_page` pays for all `3 × chunks` calls before the
first; `discover --funding` refuses to start without `ANTHROPIC_API_KEY`.

### 8.3 What a reading says about a line

For every line that states money, a fee reduction, a paid position or in-kind support for a
student, or states that none is available:

| field | values | class |
|---|---|---|
| `offered` | `YES` / `NO` | **existence** |
| `holder` | the sixteen types of §5 | **existence** |
| `scope` | `HOLDER` (the page's owner is the award's holder — decided from `Organisation` when the host is registered, from title/`og:site_name` otherwise) / `PROGRAM` / `PROGRAMS` / `INSTITUTION` / `POINTER` | **existence** |
| `kind` | `HOLDER` awards carry the family; `I1_UNIVERSITY_WIDE` … `I7_PAID_PLACEMENT` for institution-side money | detail |
| `family` | the eleven `FundingFamily` values | detail |
| `route` | `AUTOMATIC_ON_ADMISSION` / considered with admission / student applies separately / `INSTITUTION_NOMINATES` / home government nominates / `JOINT_SELECTION` | detail |
| `money_form` | `GRANT` / `FEE_WAIVER` / `SUBSIDY` / `LOAN` / `FORGIVABLE_LOAN` / `DISCOUNT` / `MIXED` / `UNSTATED` | detail |
| `tuition`, `living` | `NONE` / `PARTIAL` / `FULL` / `UNSTATED` | detail (majority) |
| `extras`, `obligation` | closed sets (travel, insurance, housing, language_year, visa; return_home, work_in_host, serve_funder, repay_on_breach) | detail (union) |
| `conditions` | `ConditionTriple(key, operator, value, unit, quote)` — the vocabulary of §8.5 | detail, **per condition** |
| `nationality_shape`, `internationals_included` | coarse summaries the pool can index on | detail |
| `applies_to`, `stated_on`, `deadline`, `deadline_for` | the intake as written, an ISO date the line carries, an ISO deadline, the condition *as written* (`"non-EU citizens"`, `"round 2"`, `ALL`) — all inside the quoted line, so quote verification covers them | detail (§9) |
| `timing` | `PRE_ARRIVAL` / `POST_ARRIVAL` / `EITHER` / `UNSTATED` | detail (card) |
| `cycle` | `ANNUAL_FIXED` / `ROLLING` / `WITH_ADMISSION_CYCLE` / `ONE_OFF` / `UNSTATED` | detail (card) |
| `amount`, `currency`, `period`, `duration`, `required_documents` | as written | detail (card; columns exist, writer is build item 13) |
| `contact` | an **office** e-mail address or contact-page URL, as printed, on the holder's own registrable domain; read only where `route` is not `AUTOMATIC_ON_ADMISSION` (§9.2, added 2026-09-25) | detail (card) |
| `name` | ≤ 6 words, a label | — |

Labels describe **the award the line belongs to, read with the whole listing as context**; `UNSTATED`
means the listing nowhere states it. `POINTER` = money obtained by applying to a body outside this
page; money this page's owner awards, nominates for, or that comes with a place is attached, whoever
funds it — an EU-funded Erasmus Mundus scholarship the consortium awards is `I5` at `PROGRAM` scope.

### 8.4 Agreement per line

With three surviving readings, `y` = `YES` votes, `k` = `NO` votes: `y + k ≤ 1` → noise, counted;
`y = 0, k ≥ 2` → negation, joins its award (§9.2); `y = 3` → decided per field (§8.6); `y = 2` or
`y = 1, k ≥ 1` → **one fourth reading on `offered` only** (owner 2026-09-18), then decided or
disputed on `offered`. Fewer than three readings → the chunk is `ABSTAINED`, nothing served, the
lines at least one reading called funding go to the queue. A reading that answers twice for one line
is one vote whose labels agree with nothing.

### 8.5 The eligibility vocabulary — one closed list, one decider per key

`apps/funding/eligibility.py` (built on `claude/reader-holder-axis`): keys `CITIZENSHIP`,
`RESIDENCE`, `DESCENT`, `FIELD`, `PRIOR_DEGREE`, `PRIOR_INSTITUTION`, **`GRADE`** (a numeric bar on a
named grading scale — built as `TALENT`; **renamed by owner decision 2026-09-22** while zero rows
exist, one migration on an empty table), **`TALENT`** (sports or arts talent, a label form, `PRESENT`
— the 2026-09-17 meaning, restored), `WORK_EXPERIENCE`, `LANGUAGE`, `AGE`, `GENDER`, `NEED`,
`REFUGEE_OR_DISPLACED`, `DISABILITY`, `EMPLOYMENT`, `AFFINITY`, `GUARANTOR`, `OPEN`, `OTHER`;
operators `IN`, `NOT_IN`, `EQ`, `GTE`, `LTE`, `PRESENT`; value forms country set (ISO codes or a named
region expanded through the sourced `REGIONS` table — an unknown region is `OTHER`, never guessed),
number with unit, enum/bool/label. `UNSTATED` is not a key: a page that states nothing writes no row.
`REGION` is a value form, not a key; `LEVEL` is `PRIOR_DEGREE`. **The same rows serve programmes'
admission conditions** (`BenefitRule` with `benefit` null and `program` set; constraint
`benefit_rule_target_present`, at-least-one). `decide(condition, profile) → SATISFIED | FAILED |
UNDECIDABLE` with a naming reason; a key the profile does not carry is `UNDECIDABLE`, never `FAILED`;
`FIELD` no-match is `UNDECIDABLE` ("engineering" does not exclude "robotics"); grades are never
converted. The consultation adds `date_of_birth` and `gender` (optional, *prefer not to say*);
`DISABILITY`, `REFUGEE_OR_DISPLACED`, `NEED`, `DESCENT` stay review-only until a product decision
(Art. 9 data: separate explicit consent, keys not narrative, excluded from every prompt and query,
in the erasure field set).

### 8.6 Tiered agreement — the serve rule (owner 2026-09-19; the existence set confirmed 2026-09-22; amends PR #104's strict rule)

- **Existence fields gate whether an award is shown at all**: exactly **`offered`, `holder`, `scope`**
  must be unanimous across the three readings (after the fourth-reading tie-break on `offered`), the
  quote must be on the page, and the line must state a benefit or a money form in *some* reading.
  "Never show money the page does not offer" is untouched, and served still needs Claude's agreement.
- **A disputed detail or condition makes that field `UNCONFIRMED`, not the award.** The award is
  shown with the field marked unconfirmed beside its quoted sentence; the pool **never filters on an
  unconfirmed field**; an unconfirmed condition falls to the undecidable branch (an operator's queue
  item, never a hidden award). Three readings agree on a condition when they agree on `(key, operator,
  value)`. This is the `route`/`money_form` decision the 2026-09-19 gate surfaced: ten awards decided
  on five known funders, none shown, all split on `route` and `money_form`, none on `holder`.
- **`served` is set only by the writer**, when: existence agreed; the lead is a vouched catalogue lead
  or a `HOLDER` page (`can_support_claim`, `one_programme_per_site`); no `REJECTED` review stands for
  this page version (`reviewed_sha256`); and — once §9 lands — the cycle state is `OPEN` or `UPCOMING`.
  An operator's `ACCEPTED` review (`manage.py funding_review`, built) is the other way a row becomes
  served, bound to the page version.
- **Withdrawal:** when a page is re-read and an award whose *only* source is that page is not among the
  read's decisions, the row is `WITHDRAWN`, `served=False`, quotes kept. A vaguer read of *another*
  page may not unserve a clearly stated award. (The unserve sweep for rows nothing re-reads is owed —
  §19.)

### 8.7 What an award is

Identity is **`(organisation, page, the heading the quote sits under, kind)`** — the site's own
structure, stable across reads. `(holder domain, kind)` collapsed a ministry's dozens of schemes into
one row; a "find all" engine that cannot count DAAD's programmes is not finding all. A list page that
names many awards is a directory and takes the pointer route. Coverage (`tuition`, `living`) is the
majority over the group's verdicts; `extras`/`obligation` are unioned; `name` is the first agreed line's.

### 8.8 The precision target and its measurement

Owner target: **95–100% on the labels a student acts on**. Measured so far: the reader on 497 EACEA
leads served 2 of 69 rows, 32 `UNAGREED`, 8 `ABSTAINED`, 5 `AGREED`
(`docs/superpowers/2026-09-16-funding-reader-precision-run.md`, PR #104 — 32 disagreement rows
hand-sampled: one real schema gap, "applications closed"/navigational mentions have no state; and a
structural finding, verbosity lowers a stated award's odds because one weak line taints a multi-line
group — parked as conservative); over 58 funder hosts, 2 served, neither a funder, 45 unagreed —
the holder axis is the fix and is built; after it, 10 decided / 0 shown on five known funders —
tiered agreement is the fix. **Gates:** re-run the same 58 hosts unchanged after each change and report
`awards shown ÷ awards found`, `noise` and disputed-on-`offered` counts with 30 noise lines
hand-checked (if a material share are real awards, the fix is a targeted binary re-ask of the other
family on that line — never a single-extractor design); one `claude-opus-5` reading on the disputed
fields of the 45 unagreed awards, cost recorded, *before* anyone proposes amending the tie-break rule;
**30 served cards hand-checked against their pages before the first pack (≥ 90%, zero false
eligibility), repeated every 200 served awards**, with the quoted sentence shown beside every fact.

### 8.9 The cheap first read — measured before it decides anything

Firecrawl's `json` format (+4 credits, ≈ $0.004 a page on Standard, `checkPromptInjection: true`)
returning a `LineVerdict`-shaped schema with quotes, verified mechanically against the same call's
markdown, run side by side with the judge over the same 58 hosts (≈ 530 credits). Outcome (a)
precision ≥ the judge's → it is the first pass and the judge runs only where a fact reaches a student
or the two disagree; (b) below → it is triage deciding which pages the judge reads; (c) poor →
recorded, the judge stays alone. An 84× cut on the term that dominates every cost table; **not adopted
until measured.**

## 9. Layer 4 — cycle verification

**The owner's requirement (2026-09-18):** the system verifies by itself and a student sees only awards
verified for their intake; no counsellor in this loop. An award a page still describes is not thereby
open — ChEMoinformatics+'s page says "about 20 Erasmus Mundus scholarships" and, dated 15/10/2025, that
the 2026–2028 intake is *without* scholarship.

### 9.1 States — `cycle_validity` (`apps/funding/validity.py`, built; a pure function, never a model)

Order of evaluation `SUSPENDED` → `ENDED` → `OPEN` → `CLOSED_FOR_INTAKE` → `UPCOMING` → else `UNVERIFIED`.

- **`OPEN`**: existence agreed; a **dated** statement inside the cycle window (twelve months before
  the intake) names the intake as open, **or** a stated deadline lies in the future and before the
  intake; no later-dated statement contradicts it.
- **`UPCOMING`**: the window has not opened and the scheme is **verified to recur** — two consecutive
  past cycles with dated calls, or the page stating it runs every year and naming the month; the
  projected window (the last observed cycle's months) falls before the intake; no dated suspension.
  Shown as *"expected to open March 2027 (opened 3 March 2026 and 4 March 2025); deadline usually
  mid-May"*, a dated roadmap item with a reminder. A first-year scheme with no history stays
  `UNVERIFIED` — projecting a cadence for it would be the guess this layer forbids.
- **`CLOSED_FOR_INTAKE`**, **`SUSPENDED`** (a dated or intake-scoped `NO` wins for that intake, shown
  only as a note on a programme card the student already has, with the quote), **`ENDED`**,
  **`UNVERIFIED`**. **Only `OPEN` and `UPCOMING` are shown as options.** *Interim rule until the
  ladder below is built* (spine spec): hide only what is known shut (`SUSPENDED`, `ENDED`, a passed
  deadline); `UNVERIFIED` enters the pool flagged and never the recommended pack — the same function,
  more evidence, tightens automatically.

### 9.2 Evidence — own site plus one hop, never further

Recurrence rests on **three general sources, the same for every scheme, family and country**:
observed consecutive cycles on the organisation's own pages; the same page as the Wayback Machine
captured it in earlier years (read once, cached for good); the register's `cadence` row — a sourced,
expiring fact (recurrence evidence while verified within the last cycle, a hint afterwards). A dated
suspension always wins over history. **The ladder**, each step only when the previous found nothing
decisive: 0 own pages already read (the judge's `applies_to`/`stated_on`/`deadline`, ~$0) → 1 site
crawl on the **cycle vocabulary** (call, apply, deadline, news, announcement and their local forms —
`bewerbung`, `frist`, `ausschreibung`; `başvuru`, `son tarih`, `duyuru`; `müraciət`, `elan` — plus the
current, next and previous two years' tokens; `limit: 15`; a page reaches the reader only if its
markdown mentions the award's name or a year token — string matching, no model) → 1b Wayback captures
of the call page from the previous two cycles → 1c register cadence → 2 one hop to the apply/portal
link from the crawl's `links`, fetched as a single page → 3 one Exa call with
`includeDomains: [<registrable domain>]`, "<award name> <year> call for applications deadline" in the
local language, `numResults: 10`; Brave `site:` only if Exa returns nothing. **Negations join their
award**: a `NO` line groups with the award of the same `(kind, scope)`; the more specific `NO` (naming
an intake or dated) wins for that intake; a `YES` for another intake is its own decision; equal
specificity → disputed on `offered`. Intakes normalise to a start year (`2026-2028`, `2026/27`,
`2026` → 2026) by one tested helper; the latest date wins a contradiction.

**Whose deadline?** A deadline is a rule per condition, not a date: DAAD sets one per country of
origin; universities give non-EU applicants an earlier date; nomination schemes carry an **internal**
university deadline; calls run in rounds. `deadline_for` is recorded as written and normalised by a
small mapper to `ALL`, `NATIONALITY:<ISO2|region>`, `RESIDENCE:<…>`, `APPLICANT_CLASS: EU | NON_EU |
DOMESTIC | INTERNATIONAL`, `FUNDING: SCHOLARSHIP | SELF_FUNDED`, `ROUTE: NOMINATION | DIRECT`,
`ROUND:<n>`, anything unmapped kept as `OTHER:<text>` and shown (country and region names from
Wikidata labels — data, never a typed table). The pack selects the most specific condition the student
satisfies, falling back to `ALL`; when a condition exists for the student's group and its date was not
read, the card says so rather than showing the general date. For `INSTITUTION_NOMINATES` awards the
ladder also runs over the *institution's* pages for the internal deadline; not found → *"the university
sets an earlier internal deadline — not stated on its pages"*, never an invented margin.
`cycle_validity` selects the student's deadline before deciding.

**A nomination award tells the student whom to write to, not only that they cannot apply
(added 2026-09-25).** France Excellence / Eiffel is the shape: Campus France takes no applications,
the student asks the host institution's international office to put them forward. The same pass
that looks for the internal deadline records `contact` (§8.3) — an office address or contact page,
quote-verified on the institution's own origin like every other field. **Office only: an address
the quoted line attributes to a named person is not stored**, because a person's address is
personal data about someone who is not our user; the card falls back to the office's contact-page
URL, and with neither it says *"ask the international office — no contact printed on its pages"*.
In the Application Kit (glass-box spec, "The Application Kit") such an award becomes an **`EMAIL`
step** — *"send this to `<contact>` before `<internal deadline>`"* — whose body is drafted from
verified facts only and is a document like any other: the student approves it (`ConsentEvent`)
before the send button exists. Sending stays the student-owned mailbox design's rule — a person
presses Send in their own client, the platform sends nothing — and **its draft-in-your-own-mailbox
decision (2026-09-25) is what the step actually does**: on a tier-3 mailbox connection one press puts the
finished e-mail, attachments included, into the student's own mailbox as a draft, because a
`mailto:` link cannot carry an attachment and this e-mail has two. A `mailto:` plus a
download-and-attach checklist is the fallback, not the design. The step's read-back is the institution's reply arriving in the filtered mailbox, which
already admits the pack's institutions; no reply by the internal deadline minus seven days puts
the award on the reminder ladder. `HOME_GOVERNMENT_NOMINATES` uses the same step with the home
ministry's office as `contact`.

### 9.3 Cadence, expiry, cost

> **Superseded for programme pages, 2026-09-26.** The refresh cadence for programme pages is the
> institution provenance gate spec's §10: once per programme per cycle after it opens (twice for
> two intakes), again when it enters a pack if the last check is stale, and about 30 and 7 days
> before the student's deadline. Firecrawl monthly monitors stay off. Funder award pages keep
> this section.

Monthly by default; **weekly** in the two months before last cycle's call date; **daily** within 14
days of a known deadline; **weekly from one month before a projected opening**; an `OPEN` award closes
itself at its deadline and becomes `UPCOMING` for the next intake when it recurs; an `UPCOMING` award
with no call **45 days past the projected date** degrades to `UNVERIFIED`, the pack version bumps and
the student is told. Every check goes through `changeTracking` (one credit, no reading, on an
unchanged page). **Data:** `FundingCycleVerification` per `(opportunity, intake_start_year)`: `state`,
`evidence` (quotes with `source`, `stated_on`, `deadline`, `deadline_for`), `projected_open`,
`projected_deadline`, `cycles_observed`, `verified_at`, `next_check_at`, `ladder_step`, **`cost_usd`**
(Firecrawl credits × plan rate, scrape.do's cost header, model tokens at list price, Exa
`costDollars` — recorded, never estimated). `FundingOpportunity` gains `suspended_for`,
`suspension_quote`, `WITHDRAWN`. Estimated cost: $0.15–0.40 per scholarship per cycle where the ladder
runs, ~$0 where the page states its own call, ~$0.05 after §8.9 passes; a 2,000-organisation corridor
$300–800 per cycle today. The sweep report prints **cost per verified scholarship** from `cost_usd`.

**Gate before any student sees a validity:** a truth set of ~40 organisations across AZ, TR, DE, NL,
SE, FR, HU, IT labelled by hand from their own sites, plus Wayback historical cases; a known-answer
row per state pinned in tests (ChEMoinformatics+ for `SUSPENDED`; a March–May scheme evaluated in
September with two past calls for `UPCOMING`; a first-year scheme for `UNVERIFIED`); ≥ 10
conditional-deadline rows; **precision on `OPEN` and on `UPCOMING` each ≥ 95%**; of last cycle's
projections, the share whose call opened within 45 days; zero `OPEN`/`UPCOMING` awards whose own
pages contradict them. Named pages are rows, never logic.

## 10. Layer 5 — serving

### 10.1 The pool — cell selection

The profile selects its cells — every holder type × the hosts it has not excluded × its `nationality`
and `country_of_residence` (descent is not collected — a descent-keyed award reaches only the
undecidable branch until the consultation asks) × its level — and the pool is the served awards and
catalog programmes in those cells plus the cells' coverage. Bounded, deterministic, and it **never
reads a row whose `served` is false**. Interim query until `FundingCell` exists: `target_field` +
`excluded_countries` + `intended_intake` over programmes and served `HOLDER` awards — replaced, not
extended. A *preference* is a pool filter; a *non-negotiable* is a hard gate; `allowed_countries` is
a gate already, so the pool applies only `excluded_countries` and the field.

### 10.2 Two fact types, one condition engine

`CandidateFacts` (a programme and the money attached to it — unchanged, so today's `HARD_GATES` and
their 41 evaluator tests are untouched) and `AwardCandidateFacts` (a standalone award: catalog row,
holder, benefits, conditions, deadline per condition, intake evidence — no programme). The condition
logic (`_unmet_conditions`, `unevaluable_condition_reasons`, `open_routes`, `closed_route_reasons`,
`_return_service_disclosures`) moves to a module both import; `_unmet_conditions` is the `FAILED`
filter over `decide`, `unevaluable_condition_reasons` the `UNDECIDABLE` filter. Rejected: an optional
`program_id` on `CandidateFacts` (a gate that silently skips is the failure this repo treats as worse
than a crash) and a generic `Applicable` protocol. Translators `program_facts` and `award_facts`
(`apps/funding/facts.py`) are pure and **refuse to invent**: no benefit → no coverage, never a
zero-cost assumption; no condition → no bar; a country-list shape with no list → an undecidable
condition carrying the award's quote; `UNAGREED` → confidence `LOW`; no deadline → the intake gate
decides.

### 10.3 Gates and the pack

Award gates: conditions the student demonstrably fails; `cycle_validity` on the award's evidence
(passing `str(profile.intended_intake.year)` and `intake_starts_on`); the selected deadline still
reachable; evidence confidence not `LOW`. `build_pack` gains a second list: **award applications are
their own entries with their own deadlines and sentences, and an award's money is never counted as
coverage against a programme's cost** (owner 2026-09-19 — it is an application, not a discount). An
award whose decision lands before a university fee deadline is `SCHOLARSHIP_FIRST` for that programme.
`handle_research_message` keeps its message seam and `select_for_update` and becomes pool → facts →
evaluate → `build_pack` → `RecommendationCandidate` rows (now with a FK to the catalog row) → publish;
the placeholder fetch and `OfficialFixture` path go. `POSSIBLY_ELIGIBLE_REVIEW` opens a
tenant-scoped `ConsultantResearchTask` — a question about **one student's own eligibility**, which
belongs to that student's agency, never a question about the shared catalog (those are the platform's
alone, §11) — and the option appears in the pool flagged; publication stays un-gated by counsellor
review (§38). Failure paths: an empty pool publishes an empty pack **with the sentence
saying why**; an untranslatable row is skipped, counted and named; every-candidate-excluded publishes
the excluded list with reasons.

### 10.4 The option card — the contract between discovery and the pack

The fixed set of facts an option must carry **before the pack may show it**; the reader must write
it, discovery must find pages that fill it, the pack refuses an option without it.

**Scholarship card:** amount and period, duration, what it covers (tuition / living / extras), the
student's eligibility result **per key** (`eligible` / `excluded` / `priority` / `unconfirmed`, each
with its quoted rule), deadline **and whose deadline it is** (a date, *decentralised*, or *stated but
not read* — three states, never a silent null), route, obligations, `timing`, `cycle`, and the
verification state for the student's intake with its evidence. **Programme card:** tuition and fees
(`CostComponent`), teaching language, duration, and the funding attached. **Both:** cost after funding
as a range (the gap — computed on the *middle* living-cost figure, with the subsidised case beside it;
`CityCost` per city, researched once, is the pack-side dependency of role-routed §4.11), required
documents, an effort estimate split into *what we do* and *what only you can do* with a confidence
state, published minimum grade in the target's own scale (never converted), and the "why for you" —
**rendered, never reasoned**, by `apps/funding/explanations.py` from the card's facts and the
optimizer's reasons. Discovery is measured on **cards filled**, not hosts found: an award whose page
states no amount or deadline is a `CANDIDATE` the pack cannot show, and the tally says so.

### 10.5 Demand cells, on-demand search, the per-provider query rule

**The catalog is the cache**: each card is written once and every pack reads it. **And the catalog is
empty**, so (owner 2026-09-18) tapping "search" runs discovery for that student and stores everything
found in the shared catalog. Those are not two modes with a switch between them, and **the earlier
wording — "nothing is searched per student", then "for now, search anyway" — read as if someone would
one day flip one.** Nobody would have: neither a fill threshold nor a "catalog is ready" flag was ever
defined, and defining one means picking a number nothing measures. The convergence is mechanical
instead, in step 2 below.

**The tap, in order** (amended 2026-09-23):

1. **The catalog serves first, always.** Pool → facts → gates → `build_pack` → the coverage line,
   before any provider call. Nobody waits on a search to see what is already known.
2. **Stage 1 always runs the field-aimed query**, and it is the one thing a tap does that a sweep
   cannot — a sweep is profile-free by contract (§6.7) and cannot ask for one student's field. Exa
   neural + Brave on a descriptive query built from the student's cell attributes, Tavily only for
   name→site, Exa `/contents` `highlights` and Brave `extra_snippets` as transient triage; programme
   rows written; the pack assembled with a *reading in progress* state on funding. **Every hit is
   deduped against the register by registrable domain before anything is fetched.** On a warm cell the
   calls come back mostly known: search spend, no fetch, no read. **That dedupe is the convergence** —
   "catalog-first as it fills" is a consequence of it, never a mode anyone turns on.
3. **Stage 2 reads only what is new or changed** — a host absent from the register, or a page whose
   `content_sha256` moved (Firecrawl's free `changeTracking` answers the second without a read,
   §7.6). The reader runs in triage order through Batch/Flex, each served award bumps the pack
   version, and the student is notified when the pack is complete or the budget is spent. R5
   affiliation lookups run here at top priority.
4. **A cell past its economic stop (§6.7) drops stage 1 to a recency-windowed query** — Tavily
   `time_range` / Brave `freshness` / Exa `startPublishedDate`, 5–10 calls. Freshness runs on the
   funder's clock (announcement season, intake year), never on the student's tap, so this is the
   sweep's own stop rule read per cell rather than a second rule with its own threshold.
5. **A thin pack is a cell's problem and never a bigger tap.** Budget spent with the pack still thin
   raises `CellCoverage` (§10.6) and the cell's aiming priority; a student whose cell is thin also
   triggers a **bounded cell sweep** (the same profile-free cell queries, ≤ 40 calls, one inventory
   pass) whose results serve everyone in the cell. A per-student wallet cannot close a per-cell gap —
   a platform-paid sweep and the closed-list read can.

**Tailoring the tap's query to the student — one rule, applied to the twenty-two consultation
answers (owner 2026-09-24; `apps/accounts/consultation.py`).** An embedding index returns the
nearest neighbour to the query *text*, and every word pulls the neighbourhood. A funder's or a
programme's page is written for everyone, so **a student's answer enters the query only if the
target page would print it**; an answer the page would not print does not sharpen the search, it
drags it toward the pages that *do* print those words (a budget figure lands on loan blogs, a career
goal on job boards). Three bins, and the bin is decided per key, never per student:

| bin | consultation keys | how it enters |
|---|---|---|
| **query words** — the page prints them | `target_field` + `research_interests` (the sub-field angle: *"M.Sc. in Sustainable Chemistry"* — the highest-value tailoring, because a hidden gem is a niche programme whose name *is* the interest); level; `acceptable_teaching_languages` (*"taught in English"*, and the language loop); `funding_dependency` + `strategy` (the money-form vocabulary the page prints — *fully funded, full scholarship, tuition waiver, stipend* for a student who can attend only with an award; *fee discount, partial scholarship* otherwise — and the order the angles run in); `intended_intake` (*"2027 intake"*); `duration_preference` (*"one-year master's"*, printed as *"2 years, 120 ECTS"*); `career_intent = research` adds the research-pathway angle (*"fully funded MSc position, research assistantship"*); **`allowed_countries` at the tap only**, as words (§6.4a item 5) | slot-filling of the stored angle rows — **deterministic, no model writes a per-student prompt**: a model reading the profile to compose query text is the one path by which a personal fact reaches vendor-licensed query text, and it is also unreproducible. The one model read stays profile → cell |
| **output filters** — the reader extracts the fact, the gate applies it | `application_budget`, `excluded_countries`, `duration_flexibility`, `longer_program_justifications`, `mobility_priorities`, `weights`, `non_negotiables`, `negotiable_preferences`; `academic_history`, `experience`, `language_evidence` (thresholds the page prints as *"IELTS 6.5"* are read by the reader and gated in the pool, never searched for) | `pool.py` and the gates (§10.1, §10.3); never a query word |
| **never anywhere** | `nationality` in a per-student tap (it runs only in the cell-level eligibility-keyed sweep, never tied to one student — the rule above); a name, an employer's or school's name with a field; every Art. 9 key (D.1); the R5 affiliations, which are looked up by the organisation's public name alone (§6.4) | — |

**What "max success" means, so tailoring is measured and not assumed:** new verified programmes
and awards **that pass the student's gates, per dollar** — tallied per angle in the tap, against the
cell-level generic pass that always runs first and whose results are already catalogued and free.
A tailored angle that finds nothing the cell pass did not is dropped by the same tally that drops a
dead engine; the sub-field and money-form angles are the ones expected to earn their place, and the
duration and career angles the ones expected to be dropped. **Over-tailoring is the failure mode**:
a narrow query in a thin index returns fewer pages, not better ones, so the generic pass is never
replaced by the tailored one — the tailored angles are additive spend on the residue.

**The budget is a wallet, not a rate** (owner 2026-09-23). **$50 is what one student's search costs
across one admission cycle** — a depleting budget keyed `(student, intended_intake)`, drawn down by
every tap in that cycle — **and never what a single tap may spend.** Read as a per-tap ceiling it
would have meant $100 a student a day at two taps and bounded a cycle not at all; as a wallet it is
the same shape as the revenue, which is also per student per cycle.

The per-tap numbers survive, as blast radius rather than as the budget:

- **Stage 1 stays latency-bound** — ≤ 3 minutes, **≤ 40 provider calls, ≤ 30 pages, no reader calls**.
- **One tap may not drain the cycle.** Recommended, owner's word owed: a tap spends at most **half the
  remaining wallet**. Deadlines cluster and awards announce in season, so a student who searches in
  September must still have budget in February; a wallet emptied on the first tap is the failure mode.
- **Two taps a day is no longer a cost control** — the wallet is — and stays as latency and abuse
  control, beside the pack-command limiter (20/min).
- **The reader-page cap is a runaway backstop, never a second ceiling, and it is derived**: above
  `remaining wallet ÷ cheapest per-page read`, or it binds before the money does and quietly becomes
  the ceiling. Against a full $50 wallet that threshold is $0.167 a page, putting the backstop at
  **300**; today's ~$0.35 a host clears it and ~$0.18 through Batch/Flex (§13) clears it by 8%, which
  is not margin worth trusting. **Whatever changes what a page costs to read re-derives it**, and two
  such changes are in flight: §8.9's cheap first read (an 84× cut on the dominant term if it passes)
  and TypeSafe Jev as the classifier (`apps/documents/research_fit/jev.py`; $0.042 per million input
  tokens, output free — about two orders of magnitude under the frontier classifier, ≈ $0.0005 to
  classify ~60 sentences).

**What the dedupe saves is fetch and reading, and once reading is cheap that is the small half.**
An earlier draft of this section claimed a warm-cell tap "costs the wallet nothing". It does not, and
the reason matters: step 2 skips the *fetch and the read*, but **the provider calls fire either way** —
the query has to be asked before anything can be deduped against what it returned. Priced on the
roster's measured figures (§4.13: Exa $0.097 at 100 results, Brave $0.005 × ~6 a query, Firecrawl
$0.00083 a page), a tap spending ~38 of its 40 calls is ≈ **$0.59 of search**, ≈ $0.05 of fetch, and —
with a classifier-priced read at ~$0.001 a page — ≈ $0.06 of reading. **Search is about 85% of a tap.**

**So the cost has inverted, and most of this document's cost machinery is aimed at the old dominant
term.** §6.7's "reading is the binding constraint", the reading queue, the economic stop and §4's
per-corridor reading budget were all set when a page cost ~$0.35 to read — 420× a fetch and several
times a search call. **The crossover is ≈ $0.015 a page:** above it reading dominates and those rules
hold as written; below it search does, and they are optimising the cheap term. A classifier-priced
read sits an order of magnitude below the crossover, so **whether they still hold is a live question
(§19), not a settled one** — and it turns on how much of a read a classifier can actually do, since
Jev cannot generate text and the `LineVerdict` a page owes carries amounts, deadlines, conditions and
a quote.

**The consequence for the rule above: step 4 is the only step that saves real money in that regime**,
because it is the only one that stops a provider call being made. Its trigger therefore deserves more
weight than "past the economic stop" gives it — a mature cell plausibly should not search on a tap at
all, only on the funder's schedule, with the tap serving the catalog and saying so.

Every tap logs provider and model spend against its pack version and against the cycle wallet. **A
tenant's exposure is arithmetic rather than an open question** — active students × $50 a cycle, a
unit cost to set against what a student is charged. A per-tenant daily ceiling survives only as a
runaway guard for many wallets draining at once, not as the thing that bounds the bill.

**Whose budget fills a shared catalog is open (§19).** Every host a tap reads lands in the shared
catalog and serves every later student in that cell, so a student's wallet pays to build a platform
asset and **the first student in a cell pays for everyone after them**. Three shapes: (a) accept it,
treating the wallet as blast radius rather than cost accounting; (b) split it, the wallet buying
search and aiming while the platform pays for reads; (c) charge the wallet only for hosts the catalog
lacked — which is (a), because the dedupe already means that. **(a) is the recommendation**, and its
mitigation is a thing that has to be true anyway: the closed universe and the free-to-apply set are
platform-swept and read before the first student arrives (§5, §6.2, build order §16), so a pioneer is
rare by construction. Where that sweep has not happened, the earliest students spend their cycle's
budget rediscovering DAAD, and nothing in this section rescues them.

**What a query may carry, per provider (test-asserted allow-list):** **Tavily — profile-free, always**
(its §9.2 takes a perpetual licence over query text); **Exa and Brave — non-identifying academic
attributes only**: target field and interests, level, teaching languages, destination countries,
nationality *as a cell attribute*; **never** a name, an employer's or school's name together with a
field, or any Art. 9 key. Eligibility-keyed phrasings run only as cell-level sweeps, never tied to one
student's tap. The one place a model reads the profile is profile → cell.

### 10.6 The coverage line

*"N found in your cells; M verified for your intake; K cells still thin — researching."* Never "no
funding". `CellCoverage` (tenant-scoped — it counts a tenant's own students) aggregates the optimizer's
two honest outcomes — no floor after every widening, budget unspent — per cell × discipline bucket
(the 28-value middle tier of Korea's classification, adopted as a starting point); aiming priority of a
cell = active students × thinness. There is no serve flag and no closed corridor.

## 11. The human resolution queue — the platform's, never a B2B client's

**Owner decision 2026-09-22, superseding 09-18 §5.1 and §5.4:** every question about the shared
catalog is **displayed to and resolved by the platform (the master agency) only**. Agencies never see
each other, and never see this queue; the platform sees everyone and everything. So there is no
counsellor-dashboard listing, no per-tenant slice of the backlog, and the "trust catch" of 09-18 §5.4
dissolves — the only hand that writes to the shared catalog is the platform's, exactly as
`manage.py funding_review` is operator-only by construction today. The one human question that stays
with an agency is about its *own* student (`POSSIBLY_ELIGIBLE_REVIEW`, §10.3), because it concerns
that student and nothing shared.

One model, `ResolutionItem` (generalising the catalog-side use of `ConsultantResearchTask`, which is
migrated into it for that use and retired for it): `kind`, `subject`, `evidence`, `ask` (one closed
question, rendered), `options`, `priority`, `expires_at` (30 days unopened), `resolved_by` (a platform
operator), `resolution`, `state`. **A platform table, outside tenant RLS** — readable and writable only
by the operator role, like the owner console's own tables; never `shared_catalog_select`, so no tenant
can list it. Listed on the **owner console** (`/owner/`, where `deletion_console` already lives),
highest priority first; frontend by Aykhan against this behaviour; the operator never leaves the panel
to research; "I don't know" always parks the item for a second operator.

**The item carries nothing about a person, and that is a rule, not a nicety.** An item's subject is a
host, an organisation or an award — never a student, a membership or a tenant id. "Which student's
pack does this block?" is answered **at read time** by counting live packs against the item's subject
through the tenant tables, so the number lives in a query and never in a row. Two reasons, and the
second is the harder one: a platform table sits outside tenant RLS, so a student pointer in it is a
personal datum in a place `advance_deletion`'s erasure sweep does not reach (the same shape as
`documents.EuropassRenderCache`, which `CLAUDE.md` records as surviving erasures because nothing
linked it back); and the cross-tenant read that computes the priority is the platform's own, sanctioned
because the answer is a count and not a person (`CLAUDE.md`'s rule 1 for crossing tenants). A test
asserts the model declares no FK to `Membership`, `Pseudonym` or any tenant-scoped table.

| kind | the operator sees | one click | written back, permanently, with an `AuditEvent` |
|---|---|---|---|
| `SITE_UNKNOWN` | the names; top 3 candidate sites with titles | pick one · paste a URL · not a funder · does not exist | `Organisation.official_website`, `names +=`, `status=REGISTERED`, `OrganisationIdentifier(source=HUMAN)`; a reject with reason; never asked again |
| `AWARD_DISPUTED` | the quotes; **only the disputed fields**, each as a choice | grant / waiver / loan / mixed per field · not an award · third party's money | `review_funding(accepted, note)` bound to `sha256`; the chosen values on the row |
| `HOST_UNREACHABLE` | "we could not open X" with the trail and screenshot | paste the page URL · closed / dead | the URL fetched and read; or `Organisation.status=REJECTED`, reason `UNREACHABLE` |
| `KIND_OR_COUNTRY_UNSURE` | homepage title, the classifier's guess and confidence | kind · country · not an organisation | `Organisation.kind`, `country_code`, human-verified |
| `SITE_UNVOUCHED` (added 2026-09-24, §6.4a item 5) | a programme page found by open-web search on a host **no register binds** — the page title, the classifier's `INSTITUTION`/`RESEARCH_INSTITUTE` verdict and confidence, the closest register candidates by name | it is this registered institution · a real institution no register lists · not an institution | `OrganisationIdentifier(source=HUMAN)` binding it, or `status=REGISTERED` with reason `HUMAN_VOUCHED`, or `REJECTED`; **until written back, nothing from that host reaches a pack** — this is `CLAUDE.md`'s provenance guard as a queue kind rather than a flag |

**The robustness ladder runs before anything is queued:** the holder axis and `HOLDER` scope → the
fourth reading on `offered` → resolution with every name variant and the six general rules → Diffbot
Enhance on the residue → the fetch ladder and retry queue → **dedupe across tenants** (registrable
domain for organisations, `canonical_key` for awards, host for reachability — one resolution serves
every agency, and the platform sees the duplicates the agencies cannot) → priority (computed at read
time: items blocking the most live packs first, whichever tenants'; then registered hosts, then
candidates) → a daily cap per operator (default 20). Target **under one host in ten per corridor reaching a person**,
measured and shown on the console. **Gate:** thirty items worked by one operator with a stopwatch —
median < 60 s, zero needing outside research, every resolution provably absent from the next run's
queue.

## 12. Data — one summary

**New, shared catalog** (`ENABLE ROW LEVEL SECURITY`, `shared_catalog_select`,
`catalog_ingestion_write`, the pattern of `apps/funding/migrations/0030_program_awarding_institutions_rls.py`;
added to `_SHARED_TABLES`; verified through `runtime_connection`): `Organisation`,
`OrganisationDomain`, `OrganisationIdentifier` (§6.1); `FundingCell` (§5); `HostProfile`,
`FetchAttempt` (§7.3–7.4; `FetchAttempt` indexes `(url, created_at)`, `(outcome, retry_after)`;
`params` with keys redacted); `FundingCycleVerification` (§9.3); the closed-list and channel rows
(§6.2, §6.4); `REGIONS` (§8.5). **New, platform-only (outside tenant RLS, operator role only):**
`ResolutionItem` (§11 — write-backs go to shared tables through `catalog_ingestion`). **New,
tenant-scoped:** `CellCoverage` (§10.6).

**Changed:** `FundingOpportunity` — `holder`, `organisation` FK, `scope` gains `HOLDER`, `money_form`
gains `DISCOUNT`, `eligibility_keys`/conditions through `BenefitRule`, `degree_levels`, `timing`,
`cycle`, `suspended_for`, `suspension_quote`, `WITHDRAWN`, the five review columns (built), key dates
with three render states; `FundingBenefit.Kind` gains `APPLICATION_FEE`; `BenefitRule` — `key`
(the vocabulary), `operator`, `value`, nullable `benefit`, `Scope.NATIONALITY` with `status`
(`ELIGIBLE`/`EXCLUDED`/`PRIORITY`) and `list_source`, `ConditionType.GRADE` with `minimum`, `scale`;
`LineVerdict` — `holder`, `conditions`, `applies_to`, `stated_on`, `deadline`, `deadline_for`;
`OfficialSourceSnapshot` — `fetched_via` (`FIRECRAWL | SCRAPE_DO | ARCHIVE | EGRESS`), `retrieval_status`
per §7.4, `render_status`, `discovery_technique` (`MAP | CRAWL | AGENT | LINK | SEED`),
`screenshot_object_key`, `unreadable`, `content_sha256` over markdown; `ResearchLead.found_via` gains
`POINTER:<host>` and the per-route vocabulary; `Program` gains a city reference and `tags`;
`CostComponent` gains `amount_low`/`amount_high`/`basis`; `RecommendationCandidate` gains a FK to its
catalog row; `StudentProfileSnapshot` schema 3 (`date_of_birth`, `gender`, `intended_intake`,
affiliations). **Unchanged:** `Institution`, `OfficialSource`, the evidence-claim tables, the reader's
decision procedure, `AuditEvent`.

**The `catalog_ingestion` role exists and is not a blocker — corrected 2026-09-22 against the code.**
`apps/funding/migrations/0006_official_snapshots.py` creates it (`CREATE ROLE catalog_ingestion
NOLOGIN`, guarded by a `pg_roles` check) and every shared-catalog migration since writes its
`catalog_ingestion_write` policy against it. Catalog writes run today under `DATABASE_ROLE=migration`,
or as `SET ROLE catalog_ingestion`; `manage.py discover` says exactly that in its own error message,
and `apps/funding/models.py` raises rather than reporting a write that silently matched nothing under
the runtime role. What does **not** exist is a `DATABASE_ROLE=catalog_ingestion` *connection* option
(`config/settings/database.py` accepts `runtime|migration`) and a login role to go with it — a
least-privilege refinement, worth having before a scheduled sweep runs unattended, and **not a
prerequisite for any table in this document.** Every new shared table below simply carries the same
two policies as `0030`.

## 13. Cost — every ceiling in one place

| layer | ceiling | where enforced |
|---|---|---|
| search | Exa per-cycle ceiling metered on `costDollars` (≈ $0.097 per 100-result call); Brave request count ($5 / 1,000, ~6 per query); Tavily a **local counter** (`/usage` lags and cannot pre-flight); SerpApi 250/month; Diffbot 400 entities/month; launch corridors ≈ $19–21 per cycle against $15 free | provider adapters, `RunBudget` |
| fetch | Firecrawl **per-key spend limit** in their dashboard (survives a bug in our accounting); **one per-sweep ceiling in USD** (`FETCH_SWEEP_BUDGET_USD`, computed from each vendor's cost signal — Firecrawl credits × plan rate, `Scrape.do-Request-Cost` × plan rate), checked *before* every call → `BUDGET`, never a 402 we cannot read; remaining-credit floors (`Scrape.do-Remaining-Credits`, Firecrawl credit-usage at sweep start); per-host `cost_usd_30d` (catches scrape.do's server-side 10–200× domain multipliers, none of which are our population); per-call caps `FETCH_PDF_MAX_PAGES` 60, `FETCH_CRAWL_LIMIT` 25, `FETCH_AGENT_MAX_CREDITS` 300, monitor `estimatedCreditsPerMonth` ≤ `FIRECRAWL_MONTHLY_CREDITS` − reserve; monthly reconciliation of `sum(FetchAttempt.cost_usd)` against the vendors' usage endpoints (> 5% gap is our defect). Plans: **free tiers today** (1,000 credits each; `FIRECRAWL_MONTHLY_CREDITS`/`SCRAPEDO_MONTHLY_CREDITS` default to those); Firecrawl Standard $83/100k and scrape.do Hobby $29/250k when funded — five numbers in `config/settings/base.py`, env-overridable | `fetch_page`, `SweepBudget` |
| classify | Jev ~$0.0001 a host (§6.6) plus one Firecrawl fetch ≈ $0.00083 — **the fetch is the cost**; a whole purpose-filtered register (VGM, 4,076) ≈ $4; abstains go to the frontier classifier at ~$0.001–0.003 a host, so `abstain rate × register size` is the term to watch; `rate_limited("org-classify")` per run; Websets `scope` as the paid fallback at $0.045 per passing host on a $449/month plan | the classifier, `SweepBudget` |
| reader | ≤ 9 calls a page (+ tie-breaks) paid up front; extraction budget `1 + 9` per lead; per-programme/`rate_limited`; ~$0.35 per host, halved by Batch/Flex and caching; a page re-read only on a changed digest | `pipeline._fund_page` |
| verification | `cost_usd` per verification; $0.15–0.40 per scholarship per cycle → ~$0.05 | `FundingCycleVerification` |
| per student, per cycle | **$50 per student per admission cycle** — a depleting wallet keyed `(student, intended_intake)`, and the budget (§10.5, owner 2026-09-23). Tenant exposure = active students × $50 a cycle | `services.py` |
| per tap | blast radius, not budget: stage 1 ≤ 40 provider calls, ≤ 30 pages, ≤ 3 min, no reader; ≤ **half the remaining wallet** (recommended, §19); runaway page backstop **derived, not fixed** — above `remaining ÷ cheapest per-page read`, so 300 against a full wallet and re-derived when a page gets cheaper; 2 taps per student per day and the pack-command limiter 20/min as latency and abuse control; a per-tenant daily ceiling only as a runaway guard | `services.py`, `apps/ratelimit.py` |
| corridor | 2,000 organisations × 2–3 pages = 5,000 pages per pass; reading $300–800 per cycle; the sweep stops at the economic rule (§6.7) | the sweep harness |

## 14. Legitimacy, terms, security

**Terms record — one row per provider, filed in `docs/legal/` before its key is read in production**
(the folder does not exist yet):

| provider | standing | condition |
|---|---|---|
| Exa, Brave | **written permission** (owner correspondence 2026-09-17) | their output trains no competing search index — so no embedding corpus, learned reranker or derived index from provider results, ever |
| Tavily | clean by structure ("Services" excludes "Output") | §9.2 perpetual licence over query text → profile-free queries; §3.2(xvi) (automated decisions in high-risk areas) is an **open legal question**, not settled — and recommendations *are* un-gated by counsellor review (§38); human oversight sits downstream at document approval and application execution |
| Firecrawl, scrape.do | the fetch path; **retention, robots and TDM rest with the vendor** (owner 2026-09-18) | `/search` off for discovery; Firecrawl's DPA is not required while no personal data travels this path |
| Diffbot | explicit commercial grant, no storage clause, **no effective date** | re-read before each use |
| SerpApi (Baidu, Naver only) | free tier, **no Legal Shield** (owner 2026-09-18) | `R4_SEARCH:google` is never written — a test asserts no `OfficialSource` carries it; Naver's own API preferred once read |
| Wikidata, ROR, OpenAlex | CC0 | — |
| DEQAR | PDDL metadata; report PDFs CC-BY-SA, never mirrored | — |
| EACEA project API | Europa reuse notice | assert the filter |
| ANR / Korea / Finland / China MOE | Licence Ouverte / KOGL / **blocked pending one email** / no licence published — build anyway (owner 2026-08-28) | — |
| crt.sh, Common Crawl | no grant | one query per domain per second, cached |
| Internet Archive | terms for automated retrieval at this volume — **ours to ask once**; tens of fetches a cycle | — |
| social hosts | Meta's and X's terms forbid automated collection — a published access term, therefore binding | **not fetched**; a scheme announced only there is counted as unseen (§6.4), never routed to a person |
| Telegram | public channels through the official API only | never a scraped view or an impersonating account |

**Retrieval policy (owner 2026-08-28, unchanged):** `robots.txt` is not a constraint on retrieval;
**published access terms remain binding** — no adapter for a host whose terms cannot be established.
Attribution is a live risk only for our own address, which no longer fetches research pages.

**Security.** Every discovered URL walks the ladder's checks (§7.7); classifier and reader input is
origin bytes labelled as data; every model output schema-constrained and token-capped; per-tenant/
per-user `rate_limited()` on every model-calling path; no student data forms a query beyond §10.5's
allow-list; Art. 9 keys never reach a prompt, a query or a counsellor except as the one word the
student chose; shared tables written by `catalog_ingestion` only; the never-vendored set tested; the
webhook receiver behind a feature flag until a public HTTPS endpoint exists.

## 15. Measurement — gates before scale, and the numbers every layer reports

**Per cell, stored and printed by the sweep:** bodies known ÷ list size (closed); **estimated unseen**
(open — two independent routes on one cell, the capture–recapture estimate, labelled a floor on the
gap); bodies read ÷ bodies known; awards shown ÷ awards found (what tiered agreement and verification
withhold, and why); **cost per verified award**. Recall = bodies found × awards read per body × awards
agreed — none of the three a feeling. Plus, per route and provider: awards per page fetched (the
headline), plateau rate and precision decay, in-country precision, host recall against gold, novel
hosts, aggregator leak, cards filled, three-run variance (the repo has seen ±2/16 — tallies are
cumulative across cycles, never per run).

**Gold sets, all free:** DEQAR − ROR for TR, AZ, KZ, GE; the VGM list; the ~30 official outbound
hosts (`htp.edu.az`, `bolashak.gov.kz`, `iec.gov.ge`, `el-yurt.uz` …); crt.sh host lists per
university; `docs/research/programme-funding-known-answers.csv` (~50 programme-attached awards, found
blind — a hit whose trail names the scheme fails); the inbound census's twenty hard schemes.

**Readiness ledger (measured / owed):**

| gate | status |
|---|---|
| provider roster, depth, negative flags; paid depth per-call cost; registrable-domain key | **measured** |
| name→site resolution | v4 measured and adopted; **acceptance on a fresh script owed** (~25 credits) |
| fetch ladder end to end | **measured** 58 hosts: 49 / +6 / +1 / 2 dead; live gate 5/5 (PR #103) |
| page-level yield | measured three times, all ≈ zero, each with its diagnosed cause; **the 58-host re-run after tiered agreement is owed** |
| cheap first read vs judge (§8.9) | owed (≈ 530 credits) |
| classifier ≥ 95% on 100 hosts | owed (≈ $3) |
| cards filled | owed; follows yield |
| cycle verification ≥ 95% precision on `OPEN`/`UPCOMING` | owed; truth set unbuilt |
| 30-card hand check | owed; before the first pack |
| saturation plateau at full depth; a thin cell (AZ) | owed (≈ $13 + $10) |
| channels yield and lead time; aggregator names-per-page yield | owed |
| Exa wildcard; Brave `OR`; Diffbot confidence threshold on the next 50 | owed |
| terms filing (`docs/legal/`) | owed — blocks reading Exa/Brave keys in production |

**Order the ledger dictates:** yield after tiered agreement first (it can make the rest moot and needs
no new code); the classifier's 100-host check before any `Organisation.kind` is trusted; the AZ
resolution sample and thin-cell plateau before the launch corridor is swept; nothing scales past a
test corridor until yield is known.

**Testing shape, every layer:** adapters against recorded responses, no network in the default run;
protocol conformance (only `url` read); a scripted vendor answering each rung in turn (rung order,
outcome, credits, no call past `BUDGET`); negative controls (200-with-469-bytes is a block; a 404 is
`DEAD` with one attempt; an off-site hop is `OFF_SITE` with no snapshot; `europa.eu` never reaches a
vendor); planner output contains no profile field beyond the allow-list; RLS through
`runtime_connection`; table-driven eligibility (one row per key × outcome); every "when absent"
translator case; the spine end to end for one student; `live`-marked tests (one call per provider and
registry; the fixed hard-host fetch list asserting outcome **class** and credit **ceiling**, never
content; `maxConcurrency: 1` for corpus runs). Recall is printed and recorded, never asserted by a test.

## 16. What exists, and the build order

**Built, where** (as of 2026-09-22): on `master` — the EACEA HTML seed, `EntityExpansionSource`, the
Tavily `SearchSource`, `RunBudget`/`DomainLease`/`PacedFetch`, `validate_public_url`,
`require_same_origin`, `looks_unrendered`, `readable_text` with section selection, `content_digest`,
`ConsultantResearchTask`, `AGGREGATOR`/`CATALOGUE_DOMAINS`, `FUNDING_PATH_TERMS`, the evaluator, pack
and explanations. **PR #104** (`claude/programme-funding-reader`, green, mergeable): the reader — lines,
three readings, two families, agreement, `funding_review`, migrations 0034–0036. **PR #103**
(`claude/vendor-fetch`, mergeable): the fetch seam `apps/research/fetch/`, Firecrawl and scrape.do
providers, `SweepBudget`, `manage.py fetch_ladder`, the browser tier deleted, five live tests.
**`claude/reader-holder-axis`** (156 ahead / 86 behind, no PR): the holder axis, pointers → leads, the
fourth reading, cache-friendly prompt order, `validity.py` (pure function), `eligibility.py` with
`decide` and `ConditionTriple` on `LineVerdict`, `BenefitRule` widened, `hosts.py::registrable_domain`,
and a `vendors.py` with a quota-mode ladder that **this document retires** (§17). **Spec only:** the
register and providers, closed lists, inventory, hubs, channels, classifier, the fetch engine's rungs
5–7 / `HostProfile` / `FetchAttempt` / site jobs / monitors, the verification ladder, the spine,
cells, the queue, on-demand search.

**The first slice, and it is the only one that should become a plan right now.** Items **0, 2, 3 and
4** (item 1 is optional, above) are a single vertical cut — **one real student receives one real award, end to end, from what is already
built** — and nothing in them is speculative supply-side work. They are the shortest path to the
question that has never been answered in this repo: *does a served award reach a pack at all?* Today
the reader writes rows nothing reads, and the evaluator ranks over a near-empty catalog with no
production caller; items 0–4 join those two halves and make every later gate meaningful, because a
coverage number over a pipeline with no consumer measures nothing. **Plan 1 is items 0, 2, 3 and 4
and stops there** (`docs/superpowers/plans/2026-09-22-funding-engine-slice-1.md`). Everything from item 5 on is supply-side breadth behind measured gates, and each gate's
result should be read before the next plan is written — the alternative is fifteen items planned
against numbers that do not exist yet.

**Order** (each item ships something measurable; gates inline):

0. **One lineage.** Merge PR #104 and PR #103; bring `claude/reader-holder-axis` to `master` (the
   holder axis, validity, eligibility, hosts — dropping its `vendors.py` and `HostFetchCost` in
   favour of PR #103's seam). Plans are written against `master` only after this.
1. *(Was: create the `catalog_ingestion` role — **deleted, it already exists**, §12.)* Optional and
   cheap whenever a scheduled sweep first runs unattended: a `DATABASE_ROLE=catalog_ingestion`
   connection option plus a login role, so an ingestion run is not a `migration`-credentialled one.
   Nothing else in this order waits on it.
2. The Organisation register — `Organisation`, `OrganisationDomain`, `OrganisationIdentifier`,
   `record_organisation`, the `FundingOpportunity.organisation` FK and backfill (register plan
   Tasks 1–3 as amended by §6.1).
3. Tiered agreement (§8.6) and award identity (§8.7) in `funding_judge.py`/`funding_reader.py`.
   **Gate:** the 58-host re-run — `awards shown ÷ found`, noise and disputed counts, 30 noise lines
   hand-checked.
4. The spine — `pool.py` (interim query), `facts.py`, award gates, the second pack list,
   `handle_research_message` replaced. **Gate:** one student end to end; the interim validity rule.
5. Fetch engine core — rungs 5–7, `HostProfile`, `FetchAttempt`, the outcome set, the configuration
   block, the USD sweep budget, `retry_due_fetches`, `record_blocked_source` updating `reason`
   (09-16 defect), the negative controls and live hard-host gate.
6. Technique layer and providers — **built 2026-09-24 as PR #128** (`claude/search-providers`:
   `SearchProvider`, `AGGREGATOR_DOMAINS`, `STEERING`, Exa, Brave, Tavily, per-provider keys,
   `sweep.py`, `manage.py sweep_organisations`); still owed from this item: the terms record in
   `docs/legal/`, Baidu/Naver, the inline Goggle actually passed (the file is committed and
   `goggle_url` waits on hosting it does not need — pass it inline), and **the page-voiced angle set
   replacing the one `numResults: 100` query** (§6.3). **Gate:** Exa wildcard, Brave `OR`, Exa
   `deep` + `additional_queries`, and `category: company` with client-side exclusion measured
   before they ship.
6a. **The register ladder for Türkiye, end to end** (added 2026-09-24; the cheapest complete proof
   of §6.2–§6.6 and it needs no plan bought): the VGM adapter (`IsGrant=true`, count asserted),
   rung-0 e-mail resolution with `FREE_MAIL_DOMAINS`, the name resolver for the rest, and the Jev
   classifier over all 4,076 (≈ $4). **Gate:** the classifier's ≥ 95% two-script gate (§6.6) on the
   labelled set that already exists; then `bodies known ÷ 4,076` on the coverage line. Nothing in
   this item searches. **TypeSafe sign-up was unavailable on 2026-09-24** (owner: "they have
   problems"), so the item is built with the classifier behind one seam and the frontier path —
   §6.6's abstain route — running first over the register (≈ $4–12 at frontier prices, still
   trivial); Jev drops in behind the same seam and takes the gate when a key exists. The gate's
   labelled set and the coverage line do not wait on it.
   Resumed 2026-09-25 from page 225 with `--start-page`: pages 225–339 read (1,388 rows seen, 567
   resolved, 821 unresolved, 527 organisations new, 40 already held; $0.0971 of Firecrawl). **The
   whole register, from the coverage-only call, which is the authority:** `bodies known ÷ listed:
   1,417/4,028` — 4,028 unique register rows of the 4,076 the page prints (4,048 rows were seen
   across the runs; the difference is rows sharing an e-tebligat id or a name — 110 rows carry no id
   and are keyed on their name), 1,417 distinct organisations bound to an entry by rung 0 (1,522
   bindings across those bodies, 38% of the register, not the two-thirds page 1 suggested — free-mail
   addresses are the majority; `register_coverage` counts distinct organisations now, not entries,
   since a branch office or a second e-mail can bind two entries to the same body), `classified: 49`,
   `funds_students: 49`. The 49 classified bodies now exclude the register-vouched rows the
   homepage read as not funding students, which return `contradicts_register` and stay askable
   instead of being cached as non-funders forever (100 such rows were reset on 2026-09-25 in the
   local database; no production database exists).
7. Enumerators — closed lists for two launch countries (gate: 100% enumerated, read states recorded);
   **the country-less intergovernmental and regional-fund list** (global and cell-tagged, never sized to one corridor — World Bank, IsDB, ADB, AfDB, IDB, Commonwealth, Mastercard Foundation, Visegrad Fund, Nordic Council, EEA Grants,
   OPEC Fund, UNESCO, Aga Khan; §19, the one family with no route today, and cheap enough to do
   first); Wikidata, ROR (gate first), the EACEA API + EMJM partner binding, **the register survey
   per corridor country and one rung-2 adapter (BZSt) as the second proof of the ladder**, curated
   national files; Exa per-HEI first pass; crt.sh + `/map` inventory.
8. The resolver as specified (§6.5) with `names`, the six data rules, Diffbot residue. **Gate:** a
   fresh-script hold-out.
9. Site jobs and refresh — map, rank, crawl + errors, the four programme outcomes, the flagged
   webhook receiver; **the navigator, monitors per cycle and `poll_monitor_checks` once the plans are
   bought** (the code can land behind the same flag).
10. The sweep harness — register ladder first, the page-voiced **angle-set generator** per (country,
    family), `(family, provider, angle)` first-discoverer tally, **both stop rules** (economic; three
    batches without a new verified host), free-to-apply ordering; **hidden gems re-based**:
    `EntityExpansionSource`'s Tavily search half retired, its sitemap walk re-aimed at
    `OrganisationDomain` rows, and the three programme-page mechanisms measured against each other
    on the held Turkish foundations (§6.4a item 5). **Gate:** a second saturation cell (AZ), and a
    Türkiye re-sweep *after* item 6a that reports set-difference against the 4,076, not against an
    empty register. Corridor-scale runs wait for the plans; measurement-scale runs fit the free
    tiers.
11. The verification ladder (§9.2), `FundingCycleVerification` with `cost_usd`, cadence scheduling,
    withdrawal. **Gate:** the truth set at ≥ 95%; the interim validity rule retires.
12. The resolution queue — `ResolutionItem` as a platform-only table, the four kinds, the **owner
    console** listing, write-backs, cross-tenant dedupe, priority and per-operator cap; the
    catalog-side `ConsultantResearchTask` uses migrated. **Gate:** thirty items under a stopwatch.
13. The card the reader owes — amount, period, duration, deadline, `timing`, `cycle`,
    `required_documents` written with quotes into `FundingBenefit`/`BenefitRule`; `degree_levels`,
    `NATIONALITY` scope rows, `GRADE`, key dates. **Gate:** cards filled; the 30-card hand check.
14. Demand cells and on-demand search — profile → cell, `CellCoverage`, the coverage line, the
    two-stage tap with its per-provider allow-list test, the bounded cell sweep, R5 affiliation lookup,
    consultation schema 3 (D.1).
15. Beside any of the above once the reader is stable: Batch/Flex and prompt caching (D.4); the cheap
    first read gate (§8.9); field tags at ingestion (D.5, gate 50 names ≥ 90%); `CityCost`
    (pack-side); the `content_digest` / `_MAIN_SHARE` alignment. **The channel gate** (§6.4) is run
    here as a measurement; its adapters are built only if it passes (§18).

## 17. Decision log — where the sources disagreed, and what governs

Resolved by the latest dated owner decision; each delta is named so it is not re-derived.

| # | topic | superseded | governs |
|---|---|---|---|
| 1 | fetch ladder order | 09-18 §4.1b–c and `reader-holder-axis` `vendors.py`: **own client first**, then `FETCH_VENDOR_MODE` `quota` (scrape.do first while on free tiers) / `paid` | 09-22: **vendor-only; Firecrawl first; no mode switch; no own-client tier** (§7), written for both plans bought — plans pending per row 24, order unchanged meanwhile. PR #103 already ships Firecrawl-first and vendor-only; the quota ladder and `HostFetchCost` are dropped in build item 0 |
| 2 | fallback vendor | 09-18: Tavily Extract; 09-19 coverage spec Layer 2 still says so | scrape.do took that job 2026-09-19; Tavily keeps **resolution and `/map` only** |
| 3 | serve rule | 09-14 / PR #104: every decided field unanimous; a true majority of the total for coverage | 09-19 **tiered agreement** (§8.6): existence unanimous, details `UNCONFIRMED`. PR #104 ships the strict rule; item 3 amends it |
| 4 | award identity | holder-axis plan Task 4: `(holder domain, kind)` | 09-19 §6.3: `(organisation, page, heading, kind)` |
| 5 | scope value name | 09-18 `HOLDER_OWN` | `HOLDER` as built |
| 6 | `Organisation.kind` | register plan: seven values incl. `INFRASTRUCTURE` | one taxonomy = the holder vocabulary; infrastructure hosts are `status=REJECTED, reason INFRASTRUCTURE` (§6.1 — reconciliation, not in any source) |
| 7 | `Organisation` domain key | register plan: `registrable_domain unique` | 09-19: `primary_domain` + `OrganisationDomain`, plural |
| 8 | eligibility keys | 09-17 §4.9 / 09-18 §3.1 lists; `REGION`, `LEVEL`; `UNSTATED` as a key | 09-19 eligibility spec (§8.5) is authoritative |
| 9 | cells | 09-17 §5 `DemandCell` (destination × discipline × level × languages × keys × need) | 09-19 Layer 0 cell for supply and coverage (§5); discipline, languages and keys are per-student filters and Exa query attributes; `CellCoverage` aggregates per cell × discipline bucket (§10.6 — reconciliation) |
| 10 | profile in queries | 09-17 §8: never, blanket test | 09-18 D.6: per-provider allow-list (§10.5) |
| 11 | aggregators | 08-28, 09-17: never a source | 09-18: fetch everything, names only, never provenance (§6.4) |
| 12 | hub harvesting tool | 09-17 §4.5, 09-18: Firecrawl `/extract` | 09-22: `/extract` off; crawl + our closed-schema read, Firecrawl `json` once §8.9 measures it |
| 13 | Firecrawl `/agent` | 09-18: off, dearest way to read | 09-22: **on as navigator only**, bounded, answer discarded (§7.5) |
| 14 | `maxAge` | 09-18 §4.1 asked for it | gone — `changeTracking` bypasses the cache; every scrape is fresh |
| 15 | retry schedule | 09-18: three tries over seven days | 09-22 rung 5 schedule (§7.2) |
| 16 | scrape.do redirects | 09-22 rung 3: `disableRedirection`, hop by hop | PR #103 live run: `scrape.do-resolved-url` header (§7.2) |
| 17 | budget unit | PR #103 per-vendor credits (`FETCH_SWEEP_CREDITS`); 09-22 Firecrawl-credit units at 7:1 | **USD** per sweep, from each vendor's cost signal (§13 — reconciliation; dollars compare vendors, and every other ledger is in dollars) |
| 18 | cost table on `HostFetchCost` | reader-holder-axis | `HostProfile.cost_usd_30d` + `FetchAttempt.cost_usd` |
| 19 | robots / TDM | 08-28: not consulted by us; 09-13: "as the discovery design treats them" | 09-18: the vendor's question, and the reason there is no own-client tier (§7.7) |
| 20 | country as a filter | phase 5: required; 08-28: never | 09-17 §5: aiming term for organisations, output for programmes (§6.7) |
| 21 | live search per student | 09-19 "deliberately not built: a live per-student search with **no shared catalog**" | compatible with 09-18 D.6, which stores everything in the shared catalog (§10.5) |
| 22 | `I0` | the external brief named an `I0` kind | no `I0`: a `HOLDER` award's `kind` is the family |

**Four decisions taken by the owner on 2026-09-22, on this document:**

| # | question | decision | where |
|---|---|---|---|
| 23 | which fields must be unanimous before an award is shown | **`offered`, `holder`, `scope`** — exactly those three; every other label may show as `UNCONFIRMED` beside its quote | §8.6 |
| 24 | are the vendor plans bought | **not yet; they will be when the startup is funded.** Ladder order unchanged on free tiers; free-tier defaults; monitors, navigator and corridor-scale sweeps wait for the plans | §7, §7.5, §7.6, §13, §16 |
| 25 | the `TALENT` key naming | **rename the grade bar to `GRADE` now**, while zero rows exist; `TALENT` returns to its 09-17 meaning (sports/arts) | §8.5 |
| 26 | who resolves catalog questions, and who sees whom | **the platform only.** Agencies never see each other and never see the queue; the master agency sees everything. Supersedes 09-18 §5.1 (counsellor dashboard) and §5.4 (the trust catch) | §11, §12, §16 |
| 27 | may a human feed names into discovery | **no.** No counsellor types anything into this engine: it is friction on the party paying us to remove it, it yields no denominator, and it contradicts §9's "the system verifies by its own". Pointers and hub harvesting are the machine equivalent; an unreachable scheme is reported as unseen. The student's own consultation answers (R5) are not a tip route. Supersedes this document's own first draft and the 08-29 "human channel" ranking in `2026-08-28-funding-led-discovery-design.md` | §6.4, §18 |

**Two decisions taken by the owner on 2026-09-23, on this document:**

| # | question | decision | where |
|---|---|---|---|
| 28 | what the budget is a budget *for* | **$50 is one student's search budget for one admission cycle** — a depleting wallet keyed `(student, intended_intake)` — **not a per-tap ceiling**, which is how the $15 it replaces had been written and how it was first re-drafted here. The distinction is the whole decision: per tap, two taps a day is $100 per student per day and a cycle is bounded by nothing; per cycle, tenant exposure is active students × $50 and matches how the revenue arrives. Per-tap numbers survive as blast radius — stage 1 unchanged and latency-bound, a tap capped at half the remaining wallet (recommended), and the reader-page cap demoted to a **derived** runaway backstop above `remaining ÷ cheapest per-page read` (300 against a full wallet; re-derived by §8.9's cheap first read or Jev as classifier). The old pairing was incoherent either way: 60 pages × $0.35 capped a tap at ~$21 whatever the dollar figure said | §10.5, §13, §19 |
| 29 | what a tap does when the catalog already holds the student's cells | **it always serves the catalog first and always runs the field-aimed query, deduped against the register by registrable domain before any fetch; only new or digest-changed hosts are read.** No fill threshold, no catalog-is-ready flag, no mode switch — the dedupe *is* the convergence D.6 promised. A cell past its economic stop drops to a recency-windowed query on the funder's clock; a thin pack raises `CellCoverage`, never the tap's budget. Supersedes the apparent conflict between "nothing is searched per student" and 09-18 D.6's "for now, search anyway" — neither was ever going to be switched off, because nothing defined when | §10.5, §10.6, §6.7 |

**Five decisions taken by the owner on 2026-09-24, on the query-design research
(`2026-09-24-query-design-and-enumeration.md`):**

| # | question | decision | where |
|---|---|---|---|
| 30 | the shape of a search pass | **breadth, page-voiced**: a set of angled queries per (country, family), each written as the target page writes itself, at `numResults` 10–15 on Exa and as terms with operators on Brave — never one topic query at 100. Supersedes §6.3's Exa row as written 2026-09-22 and the 2026-09-24 sweep's `_ENGLISH_TEMPLATE` / one `STEERING` query per country. The ablation's depth finding stands per query; the saturation cell's breadth finding governs the pass | §6.3, §6.7 |
| 31 | where organisations come from | **the register ladder first, search for the remainder**: purpose-filtered register → unfiltered register → umbrella bodies and hubs → search-only, per (country, family), each a row; the coverage line names the rung. VGM's `IsGrant=true` (4,076 of 6,857) is rung 1 for Turkish foundations; search had reached under 1% of it | §6.2, §6.5 (rung 0), §10.6 |
| 32 | the classifier | **TypeSafe Jev, gated at ≥ 95% on two scripts, with the frontier model as the abstain path** — ~$0.0001 a host, ≈ $4 for the VGM register, against Websets `scope` at $0.045 a passing host on $449/month. **Websets is the measured comparator and the paid fallback if the gate fails, not a dependency.** Supersedes §6.6 (frontier-only) and §18's "Exa Websets: owner-launched probe first" — the probe ran 2026-09-24 | §6.6, §6.3, §13, §18 |
| 33 | hidden gems | **from the register outward, and by embedding on the open web for programmes**: `EntityExpansionSource`'s Tavily search half retired, its sitemap walk re-aimed at `OrganisationDomain` rows; one page-voiced open-web Exa/Brave pass per cell attribute set (field, level, teaching language — §10.5's allow-list, never a person) at the tap and at cell level; the three programme-page mechanisms measured against each other before one is preferred. Reconciles §6.3's "no open-web search" row with §10.5 step 2, which always ran one. **And reconciles decision 20 with D.6's allow-list, which disagreed on country:** the cell-level programme query carries no country (a hidden gem is a funded programme where the student was not looking; the host's country is read off the origin and filtered), while a student's tap may name their *own stated* destinations as words. A programme hit on a host no register vouches for is a `SITE_UNVOUCHED` queue item, never student-facing — `CLAUDE.md`'s provenance guard, due with this item | §6.4a item 5, §6.3, §11 |
| 34 | what "best" means for the engine | **as much funding as possible, measured against a denominator** — recall is stated per rung; a search-only country reports a curve, never a total. The register survey per corridor country is therefore the first supply-side item after the Türkiye proof | §6.2, §16 item 6a, §19 |

**Four more decisions, 2026-09-24, from the per-family audit — each a general rule noticed in
Türkiye, none a Turkish branch:**

| # | question | decision | where |
|---|---|---|---|
| 35 | home-side government scholarships | **closed list first, everywhere** — a country's outbound schemes are a handful of named programmes per agency, so each is a rung-1 row with the ministry page harvested as a hub; search runs only as the rung-4 novelty check, and a hit off the list extends the list through the queue. Resolves the contradiction between §5 (closed) and §6.3's first row (Exa primary) | §6.3, §5 |
| 36 | employers, which had no denominator | **two halves**: corporate foundations through the foundation registers; direct corporate scholarships through **the country's largest-employer lists as rung 2** (stock exchange, chamber of industry), one domain-restricted call per company, **read only on a positive hit** — the professional-body read gate applied to employers. *N* per country is set by the tally | §6.3, §6.4a |
| 37 | diaspora and affinity bodies | **keyed `(host country, home language)`, never a country row** — the pass runs on the host country's web in the home country's language; one row per corridor pair | §6.3, §6.4a |
| 38 | the language loop | **every official and administrative language of the country from Wikidata P37, plus English** — never one language per country; per-language yield tallied. `STEERING.language` is superseded by that lookup; the row keeps the hand-written angle until the generator lands | §6.3 (the recipe, lever 3), §6.7 |
| 39 | a nomination award says "you don't apply here" and stops | **`contact` on the card, an `EMAIL` kit step**: office address or contact page quote-verified on origin, never a named person's address; the e-mail is drafted from verified facts, approved by the student like any document, and **prepared as a draft in the student's own mailbox in one press** — attachments included, which `mailto:` cannot carry (the mailbox design's draft tier); `mailto:` + a download-and-attach checklist is the fallback. Read back as the reply in the filtered mailbox (owner 2026-09-25) | §8.3, §9.2 |

## 18. Deliberately not built, with the trigger that would build it

| not built | trigger |
|---|---|
| an in-house harnessed navigator | the corpus's hard subset shows `/agent` missing pages a person finds |
| a distributed concurrency semaphore | measured 429 storms across ECS tasks the vendors' queueing does not absorb |
| a second archive source (archive.today) | a host that matters has no Wayback capture within 365 days |
| **channel and feed adapters** (Telegram, RSS, local aggregator feeds, mailing lists) — §6.4 | the two-country gate returns names no other route found **and** a real median lead time over the origin. Until then pointers and hub harvesting carry the need, and the residue is reported as unseen, never filled in by a person |
| **a human tip route** (a counsellor pasting a name or a link) | never — rejected 2026-09-22 (§6.4): friction on the party paying us to remove it, no denominator, and it contradicts §9's "the system verifies by its own" at the other end of the same pipeline |
| a rules engine or DSL for eligibility; grade-scale conversion; fuzzy field matching in the gate | never (plain conditionals per key; conversion is one-way; matching is Exa at query time and tags in the catalog) |
| a history table for read state | someone needs "what did we read last month" |
| Diffbot as an enumerator; Perplexity; Anthropic server-side `web_search` | a §15 tally shows a thin family the roster cannot reach; each is an owner-launched probe first |
| **Exa Websets as a dependency** (probed 2026-09-24, §6.3) | the Jev classifier fails its two-script gate (§6.6) — then `scope` over an imported register at $0.045 a passing host is the judge; or a §15 tally shows a family where its `recall` estimate and criteria search beat the angle-set sweep on new verified hosts per dollar. A $449/month plan is bought for a measured reason, never to see what it finds |
| Exa `/agent/runs` as an enumerator | untested; the same trigger as Websets, at per-run pricing ($0.012–$1.00) rather than a plan |
| a UI over `HostProfile` | the owner console needs it |
| student effort as a portfolio term | a pack nobody executes — then an amendment to the portfolio design, not this one |
| a serve flag or closed corridor | never — the coverage line is the honest answer |
| any new UI beyond the queue listing | — |

## 19. Open questions

- **`RESEARCH_INSTITUTE` is specified, decided and not built** (§5, corrected 2026-09-23). The
  eligibility-vocabulary plan's Step 3 is the fix — three one-line edits in `funding_judge.py`,
  `models.py` and `funding_reader.py`. It touches `funding_reader.py`, which
  `claude/funding-slice-1-audit-fixes` is editing, so it lands after that branch, never beside it
  (owner 2026-09-23: applied by this session once that branch merges).
- **Subnational government — decided and measured 2026-09-23** (§6.3, ten-country table). Destination-
  side, but the eligible set is Italy's regional DSU agencies plus a few Austrian Land programmes;
  Belgium is already reached through the study-in portals; the rest is resident-gated, outbound-only
  or absent. Still owed: the **ANDISU** list adapter for Italy (build item 7); the direction rule — incoming vs
  outbound is derived from a `RESIDENCE` or `PRIOR_INSTITUTION` condition naming the region while the
  money funds study elsewhere, because no reader label carries direction today; and the reader rule
  that a resident-gated award derives `EXCLUDED` rather than `UNCONFIRMED`.
- **Professional bodies and banks — decided 2026-09-23** (§6.3). Per-country registers give the
  denominator; a body is read only on a pointer or a positive domain-restricted Exa call, so the
  reader never runs across a whole licensed-lender list. Owed: naming the register per launch country
  (chamber and association registers; the central bank's licensed-lender list) in build item 7.
- **Nothing enumerates a multilateral funder that is not an EMJM, or a regional fund** (§6.3,
  corrected 2026-09-23). "The
  EACEA API is the complete list" holds for Erasmus Mundus and for nothing else, and `default_sources`
  wires `EACEA_ERASMUS_MUNDUS` alone. So the World Bank's Joint Japan/World Bank scholarship, the
  **Islamic Development Bank** (Azerbaijan is a member state), the ADB–Japan programme, Commonwealth
  Scholarships, the OPEC Fund, UNESCO and the Aga Khan Foundation reach a student through no route at
  all. For the launch corridors these are not edge cases. **The fix is a hand-curated, global,
  cell-tagged closed list, not search** — each body carries the home × host cells it funds, so one
  list serves every corridor and is never sized to the launch ones; they are a known, finite and
  stable set, which is exactly the shape a
  closed list is for, and §5's universe table already assigns `INTERGOVERNMENTAL` to the closed-list
  engine. What was missing is that the build order's closed lists are *per launch country*, and an
  intergovernmental body belongs to no country.
- **Does "reading is the binding constraint" survive a classifier-priced read?** (§6.7, §10.5.) The
  reading queue, the sweep's economic stop and the per-corridor reading budget were all set against
  ~$0.35 a page. The crossover where search overtakes reading is ≈ $0.015 a page, and a classifier
  sits an order of magnitude below it. What decides this is not the price but **how much of a read a
  classifier can do** — Jev cannot generate text, and a `LineVerdict` carries amounts, deadlines,
  conditions and a quote — so the blended per-page cost, not the classifier's list price, is the
  number these rules should be re-checked against once that integration lands.
- **Two things the cycle wallet leaves open** (§10.5). First, whether **one tap may spend at most half
  the remaining wallet** — the recommendation, so a September search still leaves money for a February
  announcement; any rule will do except none, because a wallet emptied on the first tap is the failure
  mode. Second, and the real one: **whose budget pays to fill a shared catalog.** Every host a tap
  reads serves every later student in that cell, so the first student in a cell subsidises the rest.
  The recommendation is to accept that rather than split the accounting, **conditional on the closed
  universe and free-to-apply set being swept before the first student** — which §16 already orders,
  and which is the assumption the whole wallet figure rests on.
- **The register survey per corridor country** (§6.2's ladder, decision 34): for each of AZ, KZ, GE,
  UZ, DE, NL, SE, FR, HU, IT, ID, VN, IN, PK and each family, which rung exists — URL, maintainer,
  purpose filter, website or e-mail per row, API or form, reuse terms. One research pass on
  2026-09-24 found Germany's BZSt register (rung 2, no website field) and the 2028 federal
  Stiftungsregister, and that Kazakhstan's public foundation list covers the AIFC only; the rest is
  unsurveyed. VGM's own reuse terms are unread too, and it is the first adapter.
- **Jev's language coverage and abstain rate** (§6.6) — the two numbers the gate reports before Jev
  replaces anything; `TYPESAFE_API_KEY` exists in no environment yet.
- **Two search measurements owed before the angle-set generator is written** (§6.3): `category:
  company` with client-side exclusion (was the −2.7 a parameter-pairing artefact?), and the three
  programme-page mechanisms against each other on the held Turkish foundations (§6.4a item 5). Exa
  `deep` was measured 2026-09-24 and is not the fan-out (§6.3).
- Whether an unattended sweep should connect as `catalog_ingestion` rather than `migration` (§12) —
  a least-privilege refinement, not a blocker.
- Internet Archive terms at rung 6's volume — ours to ask once.
- Firecrawl's DPA — becomes a question the day any fetch carries a student's data, which no design
  permits; `/agent` is in Research Preview and its pricing "is subject to change".
- Naver's own developer API terms (`developers.naver.com` refused the fetch); SerpApi Production if
  exposure grows.
- Tavily §3.2(xvi) against an un-gated recommendation — an open legal question, listed with §10's
  privacy items.
- An unserve sweep for a withdrawn award whose page nothing re-reads; INSTITUTION-scope origin
  checked against `institution.official_website` (both pre-existing, PR #104 limits).
- The page that produced the DAAD PRIME `europass_preferred`/`any` flip is not recorded — the CV
  reader's live check needs a second page that derives a value (shared fetch-engine concern).
- Telegram's application credential; whether the consultation asks for descent.
- Whether `HOLDER` scope needs the classifier's `kind` to be reliable on unregistered hosts, or the
  page title suffices — answered by the 58-host re-run.
- The date the vendor plans are bought — it flips five settings and unblocks §7.5, §7.6 and
  corridor-scale sweeps; nothing else in this document changes on that day.
