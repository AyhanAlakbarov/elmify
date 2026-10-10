# Discovery by role: registries first, four indexes each at its best side

Builds on `2026-09-13-institution-programme-funding-search-design.md` (one loop, four lead routes,
one reader) and `2026-08-28-funding-led-discovery-design.md` (tiers 0–3). Evidence:
`docs/superpowers/research/2026-09-17-search-tool-probe.md` (four providers probed live, 862 hosts
classified) and the provider surveys behind it. Supersedes one sentence of `CLAUDE.md`'s "Search
providers" section — "Brave, Exa … fail there" — on the strength of written permission from both,
which §8 requires to be filed before any code reads their keys.

## 1. Why this exists

The platform's promise is a personalised pack: every scholarship a student could hold, and the
programmes each one attaches to. `phased requirements.md` §P1-3 names nine funding families;
`FundingFamily` carries eleven. The landscape research found that three of them — home-country
outbound schemes, private foundations, employer sponsorship — have **no index anywhere**, and that
the awards students most want (automatic on admission, ~45–55% of the best) sit inside programme
pages no funding-shaped URL reaches.

The 2026-09-13 design kept search as a "bounded R4 tip-off" because the one measurement said Brave
and Exa added nothing over Tavily. That measurement re-found 16 known university roots under
host-scoped queries — a solved set. The 2026-09-17 probe asked the open question instead, across
every family: Tavily alone reaches 165 funding-relevant hosts, four indexes reach 507, and the
three no-index families are exactly where the indexes overlap least. Each index also has one
thing it does better than the others, measured, and each has one failure mode a technique layer
removes. This design uses each for its best side and nothing else, and puts the free registries
in front of all of them.

## 2. What "best" means here

- **Complete where enumerable, measured everywhere, honest per student.** "All funding in a
  country" is not a target any design can hit — Germany holds roughly 25,000 foundations,
  Hochschulkompass keeps ~23,000 master's programmes behind a search-only surface, and a
  departmental stipend in a chair's PDF is enumerable by nobody. Splitting it into three claims
  makes each one true: national schemes and Erasmus Mundus are finite and can be **complete**;
  university-wide awards are complete **relative to an institution list**; programme-attached and
  foundation awards get a **measured recall** against a known-answer set and never a completeness
  claim. What the student experiences is the optimizer's no-floor signal (2026-08-28), and a
  student holding eight funded options is not harmed by a missing ninth.
- **The one target that is both bounded and student-independent: free-to-apply options.** Owner
  policy 2026-09-17 — if applying costs nothing, the option is included for every student who has
  not excluded its country, because §2.1 of the portfolio design makes a fee consume budget and
  nothing else, so a zero-fee option can never be crowded out. That makes the free-to-apply
  universe **the same set for everyone**: discovered once into the shared catalog, complete, and
  checkable against a known-answer set. Per-student sweeps are then needed only where the fee
  budget binds.
- **The denominator is holders, not awards.** Registries list organisations; **no register
  anywhere lists the awards.** Every award in every family comes from the funding reader over a
  holder's own pages (§4.8), and that step's yield — measured once so far at 2 served of 69 rows —
  is what decides whether this design delivers a pack or a list of websites.
- **Every result is a pointer to an origin we then read.** Search finds hosts; the funding reader
  (`apps/research/funding_judge.py`) finds money on the host's own pages. No provider text becomes
  a fact. This is the 2026-08-28 rule ("leads, never facts") and the probe confirms it is the right
  unit: origin share is a property of hosts, award existence is a property of pages.
- **A second index is paid for only by its novel hosts.** Dedupe against one organisation
  register keyed by domain, so combining providers costs their set-difference, not their sum.
- **Vendor-neutral method.** Aggregator denylist, geography and language steering, institutional
  boost, deep pagination, transient triage — worth +18 to +27 points on three of four providers in
  the probe — live in our code behind one protocol, so a provider can be added or switched off on
  a tally.

## 3. Scope

**In:** the organisation register and its host key; the technique layer and provider protocol;
adapters for Exa, Brave, Tavily and Firecrawl in their assigned roles; registry enumerators
(Wikidata, DEQAR, ROR, EACEA project API, Türkiye VGM); host inventory (crt.sh, `/map`); hub-page
harvesting; the query planner by country × family; budgets; measurement gates; the terms record.

**In the funding reader, because §4.9–§4.11 change it:** the eligibility-key vocabulary and its
per-row writing; the named cases added to the closed question (fee discounts, application-fee
waivers, income-tested brackets, a language course as the only support); `money_form: DISCOUNT`;
and the option card's remaining fields — amount, period, duration, deadline — which have columns
and no writer today. This design does not change how the reader *decides* (three readings, two
model families, agreement gate): that is sub-project 5's, unchanged.

**Already built, and consuming what this produces — not redefined here.** The personalised pack
is the product's point and is the half that exists. `apps/funding/evaluation.py` gates eligibility
against the student's profile (teaching language, language evidence, applicant conditions, closed
routes, duration category) and scores the fit dimensions; `apps/funding/affordability.py` computes
the funding gap per candidate; `apps/funding/pack.py::rank_candidates` orders on
`profile.strategy` — `FUNDING_FIRST` sorts by gap, otherwise by blended fit — and discloses
"weaker fit than another recommended candidate", bonds and shut schemes as tradeoffs;
`_ordering_for` decides `SCHOLARSHIP_FIRST` against `PARALLEL_OR_UNIVERSITY_FIRST`;
`apps/funding/explanations.py` writes the "why" from those structured facts;
`apps/funding/services.py` lets a student reject, replace and name a programme. Their designs are
`2026-08-14-llm-scored-recommendations-design.md` and `2026-08-27-risk-aware-portfolio-design.md`.

**Which is exactly why this design exists.** That machinery currently ranks over a catalog holding
20 programmes and two servable awards. It is starved, not wrong. This document owns the supply
side and two seams into the demand side — the option card it must be handed (§4.10) and the
coverage state it must render when a cell is thin (§5). It does not change how options are scored
or ordered; a change there is a change to those two designs.

**Out:** the risk-aware optimizer's unbuilt half (bands, correlation groups, the floor recursion);
portal automation; anything student-facing beyond the two seams above — an option's visibility is
still decided by evidence strength on the reader's side, never by where a host came from.
Perplexity (deferred, §13). Aggregators as sources (rejected, §12).

## 4. Architecture — the same loop, with a register in front and roles behind R4

```
registries (R1) ──┐
host inventory (R2) ─┼─► Organisation register (host key) ─► set-difference ─► search (R4, by role)
hub harvesting ───┘            ▲                                                    │
                               └──────────── new host ◄── fetch origin ◄── URL ◄────┘
                                                  │
                                       classify (kind, country, funds_students)
                                                  │
                                    EntityExpansionSource / reader over its pages
                                                  │
                                            awards (funding judge)
```

### 4.1 The Organisation register

The one object every route needs and none has: a shared-catalog table of organisations keyed by
**registrable domain** (Public Suffix List, so `metu.edu.tr`, `ox.ac.uk` and `edu.gov.az` key
correctly — the probe's crude two-label rule got `edu.tr` wrong). Fields: `registrable_domain`
(unique), `name`, `kind` — `HEI`, `HEI_UNIT` (with `parent`), `FUNDER_GOVERNMENT`,
`FUNDER_FOUNDATION`, `FUNDER_EMPLOYER`, `MULTILATERAL`, `INFRASTRUCTURE` (a host that is not an
organisation: `mail.`, `vpn.`, a CDN) — `country_code`, `official_website`, `status` —
`REGISTERED` (came from a register), `CANDIDATE` (came from search, inventory or a hub page;
fetched and classified; not vouched by any register), `REJECTED` — `found_via` (list of route tags,
§4.6), `first_seen`, `last_verified`. External ids in `OrganisationIdentifier(scheme, value)` with
the `InstitutionIdentifier` scheme vocabulary plus `WIKIDATA` and `EACEA_PIC`.

Shared catalog, like `ProgramStatement`: no tenant column, readable by every tenant, writable only
by the `catalog_ingestion` role; joins `_SHARED_TABLES` in `tests/tenancy/test_database_isolation.py`.
`funding.Institution` is unchanged — it stays the catalog's HEI row, created only by
`write_catalog_entry`; an `Organisation` of kind `HEI` gets a nullable link to it when the catalog
writes one. The 2026-09-07 identifier design declined a candidate table; this design needs one
because the denominator and the dedupe key are the same object, and without it every provider
result costs a fetch and no set-difference can be computed. **Status affects spend and dedupe,
never student visibility** — a `CANDIDATE` funder's awards reach a student on the reader's
evidence rules exactly as a `REGISTERED` one's do.

### 4.2 Registries first (R1, extended)

Enumerators, each a `LeadSource`-shaped adapter writing `Organisation(REGISTERED)` rows:

| register | what it enumerates | measured | licence |
|---|---|---|---|
| Wikidata SPARQL, class × country × P856 | HEIs, ministries, agencies, foundations with official websites | **re-measured 2026-09-17:** TR 229 universities with a website (253 before filtering, 216 excluding dissolved, 366 if the class is widened to higher-education institution); AZ 35. Also funders no search query would frame (Heydar Aliyev Foundation, the diaspora fund) | CC0 |
| DEQAR (daily CSV / Connect API) | EHEA HEIs that carry at least one external quality-assurance report, with `website_link` and ETER id | **verified live 2026-09-17** (`?country=<ISO2>`): TR 234, KZ 170, GE 83, AZ 13 | PDDL |
| ROR v2 | research/education/funding organisations with a stable id; `domains:` lookup resolves a host to an org | **verified live 2026-09-17** (`types:education`): TR 239, AZ 52 | CC0 |
| EACEA project API (`POST ec.europa.eu/programmes/service/search/project/search`, both action codes) | every EMJM with coordinator and partners | 415 projects, 118 with a programme website | Europa reuse notice (see 2026-09-14 EMJM spec §2.2) |
| Diffbot Knowledge Graph (measured 2026-09-17) | organisations whose entity record mentions a scholarship, as a complementary index with an entity bias rather than a ranking bias | one `isNonProfit:true` + `location.country.name` + `description:"<local scholarship word>"` query per country per cycle: on Germany it added **24 funders to the sweep's 353 (+7%)**, including a federal programme and ZEIT-Stiftung that four search engines missed. 28% precision, so every hit still goes through §4.7 and the reader. **Never a spine** — the graph holds 193,523 German nonprofits and no funding signal beyond that keyword | explicit commercial grant, no storage clause; free tier 400 entities/month at 5 calls/min |
| Türkiye VGM register, "Burs Veren Vakıflar" | scholarship-giving foundations — the largest single list of the *vakıf* class the probe saw split across four indexes | web form, no API; one Scrapling pass, then §4.5 resolution | public register; terms to record on first read |

**No register here is an accreditation list, and the differences between them are the point.** Each
asserts something different about an institution, so a count from one is not a denominator for
another (all figures measured 2026-09-17):

| | what membership means | Türkiye | Azerbaijan |
|---|---|---|---|
| **YÖK** (national register) | **legal authorisation to operate** — the actual accreditation authority | **208** (129 state, 78 *vakıf*, 4 *vakıf* vocational) | n/a |
| DEQAR | has been externally reviewed by a registered QA agency | 234 | **13** |
| ROR | is a research or education organisation with a persistent id | 239 | 52 |
| Wikidata | **someone wrote it down** — crowd-sourced, includes dissolved institutions | 229 with a website | 35 |

Two consequences. **Azerbaijan is the warning case:** DEQAR holds 13 against a sector of roughly
fifty, so DEQAR-minus-ROR is a usable gold set for Türkiye and near-useless for Azerbaijan, and
§7's gold sets must say which country they can actually score. **And Wikidata's count is a
function of the question asked** — 229 universities with a website, 253 unfiltered, 216 once
dissolved institutions are excluded, 366 if the class widens from *university* to *higher-education
institution*. The register therefore produces `CANDIDATE` rows, never `REGISTERED` ones, unless a
national register or DEQAR vouches for the same domain; the class, the dissolved-filter and the
website requirement are pinned in the adapter and quoted in its docstring, because an unpinned
class is a silently moving denominator.

**The national registers are the authority and mostly lack an API.** YÖK publishes its list as a
web page and its terms are not established (2026-09-16 scout); Azerbaijan's TKTA publishes no
list. So they are read by hand into a small curated file per country, versioned like
`docs/research/institution-identifiers.csv`, and that file — not Wikidata — is what promotes a
domain to `REGISTERED`. Sourcing an accreditation claim from a crowd-sourced register would be the
same defect as sourcing a funding claim from an aggregator.

Set-differences are also the gold sets (§7): DEQAR minus ROR, Wikidata minus ROR.

### 4.3 Host inventory (R2, made concrete)

For every `HEI` in the register: crt.sh `%.<domain>` (235 distinct hosts for METU; no published
terms — one query per domain, cached, never faster than one per second) and Firecrawl `/map` with
`includeSubdomains` (one credit per call, up to 100,000 URLs; Tavily `/map` is the alternate).
Reduce to distinct hosts; `INFRASTRUCTURE` by pattern (`mail.`, `vpn.`, `webmail.`, `sso.`, `cdn.`,
`ns1.`); the rest fetched and classified (§4.7) into `HEI_UNIT` with `parent`. DNS brute-force
stays on the forbidden list (2026-08-28 design). Brave `site:<domain> intitle:enstitü` is the
fallback sweep only for domains where crt.sh returns fewer than ten names.

### 4.4 Search, by role (R4, role-routed)

Only for the set-difference, and only where the family has no index:

| family (and side) | route | tool and its documented shape |
|---|---|---|
| Government scholarship, **home-country outbound** (AZ, TR, KZ, GE, UZ …); Private foundation; Industrial sponsorship; Affinity / diaspora | **Exa primary** | `/search` `type: auto`, describe-the-entity query ("An official page from a ministry, foundation or company describing funding for <country> students' master's abroad: …"), `excludeDomains` = denylist, **`numResults: 100`**. **No `category`** — the ablation below measured `"company"` at −2.7 pts. Probe: 79% origin as wired, 132 unique hosts, best on AZ/TR. |
| same families | **Brave second index** | hosted Goggle (`$discard` denylist, `$boost` `.edu.`/`.ac.`/`.gov.`/`uni-`/`universit`/`stiftung`/`vakf`, `/scholarship`, `/burs`), `result_filter=web`, `count=20` × `offset` until the first empty `results`, plus one `discussions`+`faq` call per query for forum-named funders. **No `country`, no `search_lang`** — measured −8 local funders in Indonesia and inert respectively. Probe: aggregators 33% → 14% with one inline Goggle, 84 unique hosts. |
| same families, local-language leg | **Tavily** | query written in az/tr/ru, `search_depth: advanced`, `exclude_domains` denylist, `max_results: 20`. **Never `language` or `filter_by_language`** — measured −1.0 and −2.3 pts; write the query in the local language instead of asking the provider to filter for it. The August measurement found local queries a strict subset of English; the probe's Turkish queries surfaced foundations. Kept as a measured leg under the switch-off rule. |
| Government scholarship, **destination side** (DE, NL, SE, FR, HU, IT …) | registries + study-in portals (R1/R3) | search only for the gap, Tavily open-web — **no `country`**, per the ablation below. |
| Multilateral | **no search** | EACEA API (§4.2). Probe: 0–50% origin on every index — the wrong tool. |
| University-wide, department/programme, tuition waiver, stipend/assistantship, relocation, research-ecosystem pathway | **no search** | these attach to hosts we hold: inventory (§4.3) then the reader. Search here only as the §4.3 fallback. |

Three phrasings per (country, family): Exa's describe-the-entity, Brave's keyword, Tavily's
local-language. **Constraints in parameters, never in prose** (every provider's own guidance);
one topic per call; Tavily's query cap 1,500 chars; every query profile-free (§8).

**The engines are not a pool, and one of them does not decay** (measured 2026-09-17,
`research/2026-09-17-cell-saturation-measurement.md`). Across 99 queries in one cell, first-discoverer
counts were Exa 147, Brave 100, Tavily 84, Firecrawl 22 — and Exa's per-batch contribution barely
moved (124, 63, 45, 43, 45, 38, 34, 42, 42) while Brave fell 81 → 11 and Tavily 62 → 5. So a sweep
**drops the decaying engines early and keeps Exa running**; the per-route tally decides when, per
cell, rather than a fixed rule.

**Required configuration — measured, not inferred** (`research/2026-09-17-search-capability-ablation.md`:
one-flag-at-a-time on a 377-funder German answer key, then the same flags across Germany, Türkiye,
Azerbaijan and Indonesia scored on funders based in that country). An earlier version of this
section named four capabilities as the obvious unused wins. **Three of them are measured losses**,
and the corrections matter more than the additions:

| capability | verdict | evidence |
|---|---|---|
| **Result depth** — Brave `offset` 0–9 until `more_results_available` is false; Exa `numResults: 100` | **ON, and the only large win** | Brave 3→10 pages: +47% / +68% / +27% / +104% local funders (DE/TR/AZ/ID). Exa 25→100: ×3.4 / ×2.0 / ×1.7 / ×2.2 |
| **Query written in the local language** | **ON, and run English as a second pass** | local beat English on local funders in all four countries (union 110/62, 80/54, 22/14, 84/50); Exa in Germany 84 against 16. English still adds a unique 5–35 |
| Tavily `language` / `filter_by_language` | **OFF** | −1.0 pt on the German key, and −2.3 with `filter_by_language`; harmful in 3 of 4 countries (−3, +1, −2, −7). It narrows the pool rather than re-ranking it |
| Exa `category: "company"` | **OFF** | −2.7 pts. Its entity pipeline is tuned to businesses and misses foundations. `category: "publication"` is worse: 0.5% |
| Brave `country` | **OFF** | +0 / −1 / +0 / **−8** local funders; inert at best, and in Indonesia it destroyed eight |
| Brave `search_lang` | **OFF — measurably inert** | Jaccard of the result sets with and without: 1.000, 0.985, 1.000, 1.000 |
| Firecrawl `categories: ["pdf"]` | ON, small and a distinct channel | +1.3 pts; funder calls and decrees are PDFs |
| Exa `includeText` | OFF | −0.8 pt; narrows like every other filter |

So the rule an adapter encodes is short: **go as deep as the provider allows, ask in the local
language, and set no filters except the aggregator denylist.** `language`, `country` and category
filters are country-dependent *and* measured neutral-to-harmful even where they exist, which is why
the configuration needs no per-country enum knowledge. **No single configuration exceeded 18%
recall** on the German key, which the 99-query sweep itself built — coverage is query volume ×
depth, never one well-configured call.

This also refutes `research/2026-08-30-search-recall-measurement.md`'s conclusion that
local-language queries are "a strict subset of English on every provider". That held for re-finding
16 known root pages under `include_domains`; it does not hold for open-web discovery of local
organisations, where local-language queries win in every country tested.

**Firecrawl's free tier returns HTTP 429 at `limit=50`**, so its depth is unavailable without a paid
plan, and it was the weakest first-discoverer of the four (22 of 353).

### 4.5 Hub harvesting and name-to-site resolution

Ministry, agency and embassy pages already list the bodies we want (`edu.gov.az/az/announcements`,
`ytb.gov.tr`, YÖK, VGM, `hanoi.mfa.gov.az`). Firecrawl `/extract` with a closed JSON schema
(`{organisations: [{name, kind, url?}]}`) over a page **we name**, one hop out
(`allowExternalLinks`), then Tavily `exact_match` with the quoted name to resolve URL-less entries
to their own site. Firecrawl is used here only on pages we chose, never to discover (§8).

### 4.6 The technique layer and the provider protocol

One `SearchProvider` protocol — `search(SearchRequest) -> Iterable[str]` returning URLs only —
behind the existing `LeadSource`; `EntityExpansionSource.search` retyped from `SearchSource` to the
protocol (the 2026-08-28 plan, never done). `SearchRequest` carries `query`, `country_code`,
`language`, `phrasing`, `max_results`, `denylist`; each adapter maps it to its parameters and
**reads only `url`** from the response. Shared in `apps/research/domains.py`:
`AGGREGATOR_DOMAINS` (the 23 held today plus the ~80 the probe needed — `mastersportal`,
`scholars4dev`, `scholarshiproar`, `findamasters`, `educations.com`, `topuniversities`, `edumap.az`,
`xaricdetehsil.net`, social media …), a country steering table carrying **the query language and nothing else** — no
Tavily enum name, no Brave code, no Exa ISO-2, because the ablation measured every one of those
filters neutral-to-harmful and the local language belongs in the query text instead — institutional
boost patterns, per-provider result caps (Tavily 20, Brave 20 × offset, Exa 100). Provenance: `found_via` =
`R4_SEARCH:exa` / `:brave` / `:tavily` / `R1:deqar` / `R2:crtsh` / `HUB:firecrawl`, so §7's tallies
are per route and per provider. Transient triage: a snippet may be read in memory to decide whether
to fetch; nothing from the response is persisted. **This discipline stands even though Exa and
Brave now permit storage** — it keeps the audit model one shape, keeps the Firecrawl and Perplexity
questions moot, and costs nothing.

Tavily wiring fixed in the same increment: `max_results` 25 → 20, `search_depth`, `country`,
`language`, denylist from `AGGREGATOR_DOMAINS`.

### 4.7 Classification of a new host

Fetch the origin (`validate_public_url` on every hop, existing egress), `readable_text` of the
homepage labelled as data, one `OPENAI_EXTRACTION_MODEL` call with a closed schema
(`kind`, `country_code`, `funds_students`, `confidence`), `max_output_tokens` capped, cached by
domain, `rate_limited("org-classify", …)` per run. The probe's one pass over 862 hosts was adequate
at host level; §7 gates it on a hand-checked sample before counts are trusted. A host the model
marks `INFRASTRUCTURE` or `funds_students=false` with high confidence is stored (so it is never
fetched twice) and never read.


### 4.8 From family to award — where each opportunity actually comes from

The categories are the repo's, not this document's: the eleven `FundingFamily` values in
`apps/funding/models.py` (the nine of `phased requirements.md` §P1-3 plus `AFFINITY_OR_DIASPORA`
and `PRIVATE_FOUNDATION`, added 2026-08-29 with their defining comment), and the seven
institution-side kinds the reader can write, `I1_UNIVERSITY_WIDE` … `I7_PAID_PLACEMENT`
(`apps/research/funding_judge.py`). The 2026-08-28 funding-led design's decision record names the
two families "nothing else indexes": nationality-keyed and home-origin outbound schemes. Benefits
(`FundingBenefit.Kind`: tuition, stipend, assistantship, housing, insurance, travel, relocation)
and scope (`OpportunityScope`) are what the reader records, not discovery categories.

For every family: where the **holder** comes from, which **pages** the reader reads, and which
**kinds** the reader can write. The award column is the reader in every row but one.

| `FundingFamily` | holder comes from | pages read | award comes from (reader kinds) |
|---|---|---|---|
| `GOVERNMENT_SCHOLARSHIP` — destination-side instruments | the funders already named in `SEED_FUNDERS`; Wikidata government agencies (R1); study-in portals as pointers (R3) | the funder's own scheme pages | reader; `COUNTRY`-scope rows |
| `GOVERNMENT_SCHOLARSHIP` — home-origin outbound (one of the two un-indexed families) | Wikidata ministries and agencies (R1); hub pages (§4.5); Exa + Brave (R4); origin-side aggregators as tip-offs per the 2026-08-28 decision record | ministry and agency announcement pages, decrees, PDFs | reader; recency legs for new calls |
| `MULTILATERAL` | **EACEA project API — 415 programmes** | consortium programme pages | **the register is the list**: `I5_FUNDED_DUAL_DEGREE` attaches to every EMJM **for the intakes inside its funded period only** (the project record's dates); past it the programme may continue without scholarship — ChEMoinformatics+'s page says so for 2026–2028, dated 15/10/2025 — and only the page decides (funder spec §3.5); the reader adds programme-specific terms |
| `INDUSTRIAL_SPONSORSHIP` (employer and bonding relationship, per the model comment) | no register; Exa + Brave (R4); hub pages | employer scholarship pages; university partner-funding pages | reader; `I7_PAID_PLACEMENT` where a placement is the money |
| `UNIVERSITY_WIDE` | DEQAR, Wikidata, ROR (R1) | the institution's funding and international pages via inventory (§4.3) | reader → `I1_UNIVERSITY_WIDE` |
| `DEPARTMENT_OR_PROGRAM` | the same institutions; `HEI_UNIT` rows from inventory (§4.3) | **programme pages themselves** — the 2026-08-28 design records that programme-scoped funding is invisible to path triage; `run_discovery` already runs the line judge over programme pages, and inventory must feed those pages, not only `FUNDING_PATH_TERMS` matches | reader → `I2_PROGRAMME_ATTACHED` |
| `TUITION_WAIVER` | the same institutions | fees, admissions and programme pages | reader → `I1`/`I2` with a `TUITION` benefit |
| `STIPEND_OR_ASSISTANTSHIP` | the same institutions; `HEI_UNIT` graduate schools and institutes | graduate-school and institute pages | reader → `I3_STIPEND_OR_ASSISTANTSHIP` |
| `RELOCATION_HOUSING_INSURANCE_TRAVEL` | the same institutions; national student-service agencies via Wikidata | student-services pages | reader → `I6_RELOCATION_HOUSING_TRAVEL` |
| `RESEARCH_ECOSYSTEM_PATHWAY` | research institutes from ROR / Wikidata / OpenAlex (R1) | institute pages for students and theses | reader → `I4_RESEARCH_PATHWAY` |
| `AFFINITY_OR_DIASPORA` (eligibility keyed to descent, not citizenship — the other un-indexed family, nationality-keyed) | Wikidata diaspora and community bodies (R1); Exa + Brave (R4); origin-side aggregators as tip-offs | the body's own pages | reader; `GLOBAL` or `COUNTRY` scope |
| `PRIVATE_FOUNDATION` (endowments with their own agenda, per the model comment) | **VGM scholarship-giving list** for Türkiye (R1); Wikidata foundations; GLEIF; Exa + Brave (R4) | the foundation's own pages | reader |

What this table makes explicit: the registries and the search roles above decide **which pages
are read**; the reader decides **what is an award**. A holder found and never read yields nothing,
and a holder read with a poor judge yields little — which is why §7's page-level yield gate runs
before any corridor is scaled, and why the reader's precision work (`2026-09-14-funding-reader-
precision-design.md`) is on the critical path of this design, not beside it.

### 4.9 Completeness decisions, 2026-09-17 — what `I1`–`I7` leave out, and eligibility as a way to fund

`I1`–`I7` are complete for the money an institution or programme awards, nominates for, or
attaches to a place (the `POINTER` test is *who the student applies to*, not who owns the money).
Read against the pages the probe and the Task 10 run actually saw, six things do not fit cleanly,
and one axis is missing. Owner decision 2026-09-17: eligibility-keyed awards — need-based,
women-in-STEM, refugee, disability, talent and the like — **are ways a student funds a degree and
must be found and recorded**, not treated as a footnote on an award's page.

| gap | decision |
|---|---|
| Conditional fee discounts (early payment, upfront payment, alumni or progression from the same institution, partner-institution) | in scope; named explicitly in the reader's closed question so a reader does not skip them as "not an award"; `money_form` gains `DISCOUNT`. Lands in `I1` or `I2`. |
| Application-fee and deposit waivers | in scope; named in the question; `FundingBenefit.Kind` gains `APPLICATION_FEE`. Lands in `I1`. |
| Income-tested fee brackets applied through the university (Italy's ISEE contribution and no-tax area; regional DSU grants applied via the university) | in scope as `I1`, never `POINTER` — the student applies through the institution; one named case in the reader's known-answer set, because a reader can send it either way today. |
| Free or subsidised language / preparatory course before the master's | in scope; when it is the only support on a page it is its own `I1`/`I6` row, not an `extras: LANGUAGE_YEAR` flag on nothing. |
| Mobility money inside the degree (Erasmus+ KA131, PROMOS, Nordplus) | **out (owner decision 2026-09-17).** Admission awards only: the platform finds money a student secures by applying to a master's. The exchange-award exclusion stands. |
| Student work rights, on-campus jobs, instalment plans | out, recorded: cost offsets and financing, not funding. The consultation asks about them (`idea_v2.md`); the catalog does not carry them. |

**Eligibility is a third axis, shared across sub-projects.** `phased requirements.md` §P1-3
classifies by family and evidence strength; the reader records eligibility only as
`nationality_shape` and `internationals_included`; the inbound census (sub-project 2) already
carries `eligibility_keys` = `CITIZENSHIP / RESIDENCE / DESCENT / REGION / AFFINITY / OPEN` with
an `AND`/`OR` combinator. This design adopts that field as **sub-project 1's shared vocabulary**
and extends it with the closed set the owner asked for: `NEED` (income-tested), `GENDER`,
`REFUGEE_OR_DISPLACED`, `DISABILITY`, `TALENT` (sports, arts), `FIELD` (discipline-restricted),
`AGE`, `PRIOR_INSTITUTION` (alumni, progression, partner), `EMPLOYMENT` (employer- or
sector-linked). The reader writes `eligibility_keys` on every `I1`–`I7` row with the quoted
sentence; the pack filters on it against the student's profile; `OPEN` is stated, never assumed
from silence (`UNSTATED` stays available). Nothing here changes student visibility — evidence
strength still decides that.

Two consequences for the rest of this design. **Search (§4.4) gets a fourth phrasing set,
eligibility-keyed** — "scholarship for women in engineering master's <country>", "need-based
funding international master's <country>", "scholarship for refugee students master's <country>"
— run for the launch corridors on the no-index families, budgeted separately (about 60 extra
Exa + Brave calls per corridor) and tallied by novelty like the recency leg. **Registries (§4.2)
add the funders that exist *because of* an eligibility key**: Wikidata classes for women's and
disability foundations, UNHCR's DAFI and university sanctuary schemes for refugees, national
sports and arts foundations — each a holder whose pages the reader then reads.

### 4.10 The option card — the contract between discovery and the pack (owner decision 2026-09-17)

The pack shows a student **options to pick from**, each with the facts that decide whether it
funds their degree, and a "why we chose this for you". The option card is the fixed set of facts
an option must carry **before the pack may show it**; everything else is a detail the student can
open. It is the contract in three directions: the reader must write it, search and registries
must find pages that can fill it, and the pack refuses to display an option that lacks it.

**Scholarship card.** Amount and period (`FundingBenefit.amount`, `currency`, `period`); duration;
what it covers (tuition / living / extras); the student's eligibility result **per key**
(`eligible` / `excluded` / `priority`, each with the quoted rule from `BenefitRule`); deadline,
intake and cycle status (a date, *decentralised / published per target*, or *stated but not read
reliably* with the sentence — the P1-9 amendment's three states) **and whose deadline it is** — a
deadline is a rule per condition (nationality, residence, EU/non-EU, scholarship vs self-funded,
nomination vs direct, round), and the card shows the one that applies to this student, or says that
theirs was not read (funder spec §3.5.8); route (automatic on admission,
considered with admission, separate application, nomination); obligations (return home, work in
host, serve funder, repay on breach); **timing** — whether the money can be applied for *before
arrival* (so it counts towards a visa's proof of funds) or only *after arrival and local
registration* (Germany's municipal stipends, France's CAF housing subsidy): `PRE_ARRIVAL /
POST_ARRIVAL / EITHER / UNSTATED`; and the deadline's **cycle** — `ANNUAL_FIXED / ROLLING /
WITH_ADMISSION_CYCLE / ONE_OFF / UNSTATED` — because a date without its cycle cannot be carried to
next year's intake (both added 2026-09-18 after external review; written by increment 6 with amount
and deadline); and **verification for the student's intake** — `OPEN / UPCOMING / CLOSED_FOR_INTAKE / SUSPENDED / ENDED /
UNVERIFIED`, computed by a pure function from dated evidence on the organisation's own pages or the
one application page they link to (funder spec §3.5, owner decisions 2026-09-18): **only `OPEN` and
`UPCOMING` awards are shown as options** — `UPCOMING` with its projected window and the past cycles it
rests on, as a dated roadmap item; `SUSPENDED` appears only as a note on a programme card the student
already has, with the quote; the coverage line says *"N found, M verified for your intake"*. **Programme card.** Tuition and fees (`CostComponent`),
teaching language, duration, and the funding attached to it. **On both:** cost after funding — the
gap — the **required documents**, an **effort estimate**, and the "why for you". Published minimum
grade is shown when a page states it, in the target's own scale, marked *unknown* otherwise; never
converted (`phased requirements.md` §6.1).

**Effort, because the student prunes on it (owner decision 2026-09-17).** Student time is not a
budget in the optimizer and will not become one; it is displayed, and the student excludes what they
will not carry — `reject_candidate` / `replace_candidate` / `consider_named_program` already do that.
The estimate is split in two, because the halves mean different things: **what we do**, computed from
`len(FieldMap.entries)` for a portal whose form we have learned, and **what only you can do** — the
documents you must still obtain, plus the moments `apps/portals/escalation.py` already enumerates
(`MISSING_FACT`, `PERSONAL_ATTESTATION`, `APPLICANT_MFA`, `UNSOLVED_CHALLENGE`,
`AMBIGUOUS_DECISION`, `PORTAL_ERROR`), plus Next per page and Submit. It carries one of three
confidence states — **measured** from `ApplicationStep` timestamps once we have run that portal,
**class estimate** for a portal family we have not, **unknown** for one we have never seen — and the
living-cost rule applies unchanged: lean realistic, never present a floor as an expectation, because
an underestimated effort figure produces a student who abandons halfway.

`required_documents` is the field this costs us: it exists on `ExtractedClaims`
(`apps/research/extraction.py`) in the programme-extraction path but **not in the funding judge's
schema**, which stops at kind, scope, route, money form, coverage and obligations. Increment 6 adds
it.

**"Why for you" is rendered, never reasoned.** It is built from the card's facts plus the
optimizer's reasons — the option's band, its role as floor or reach under the fee budget, which
eligibility keys matched — by `apps/funding/explanations.py`, which already "explains only the
supplied structured facts". No model judgement enters it; every sentence points at a quoted rule.

**Consequences.** The reader (sub-project 5) must write the whole card, not `kind` / `route` /
`money_form` alone — amount, period, duration, deadline and the eligibility rules with their quotes
are columns with no writer today (2026-09-15 audit). Discovery's inventory (§4.3) must feed the
pages those facts live on — the fees tab, the admission page, the scholarship page, the one linked
PDF — as the 2026-09-13 design's §4.2 page set already says. Registries and search are measured
(§7) not only on hosts found but on **cards filled**: an award whose page states no amount or no
deadline is a `CANDIDATE` the pack cannot show, and the tally says so.

**The catalog is the cache.** Discovery writes each card once into the shared catalog; every pack
reads it; nothing is searched per student. Freshness is §6's cadence plus a deadline window: a
card whose deadline is within 60 days is re-read before it is shown, because a stale deadline is
the one fact that costs the student an application.

### 4.11 Living cost — a per-city range, researched once (owner decisions 2026-09-17)

The pack cannot say whether an award funds a degree without saying what the degree costs to live
through, and that is the fact most easily used to mislead. `idea_v2.md` §D (amended 2026-09-17)
holds the product rule; this section holds how discovery produces it.

**No per-student search, and no per-city search at query time.** Housing is the only component
that genuinely varies by city, and both of its honest sources are pages we already read or can
list once. A city is researched **once**, cached in the shared catalog, and refreshed annually on
the academic year and on each visa-norm revision.

| component | varies by | source | how it is obtained |
|---|---|---|---|
| Visa financial-proof norm | country | ministry / mission pages | already in `DestinationPolicy`, verified 2026-08-27 |
| Dorm rent — the realistic low end | city | the public student-housing body's own rate card: Studierendenwerk (57 in Germany), CROUS (26 regions), DUWO/SSH, SSSB | a register of ~60–100 hosts across the launch destinations, read once a year |
| Shared room / flat-share — the middle | city | the university's own cost-of-living page; where it publishes none, the national student survey (DSW Sozialerhebung, OVE) | the cost page is part of the programme's page set (§4.3) |
| Food, transport, utilities, insurance, semester fee | mostly country; fee per institution | national student rates; the institution's fees page | already in the page set |
| Private-market rent | city | listing sites | **never** — the average consumer budget `idea_v2.md` §D rules out, and their terms forbid it |

**The range.** Low end = the student-housing body's published rent (Berlin: €250–€450). Middle =
what a student secures unaided. The low end may never be shown without its access reality in the
same breath — waiting list, application window, and where the system allocates that way, a
lottery. **Display leans low; the affordability decision does not:** the funding gap and every
"can this student afford it" is computed on the middle figure, with the subsidised case shown
beside it as what the gap becomes if the room is obtained. No recommendation rests on winning a
housing lottery.

**Data.** A shared `CityCost` row per city — three Berlin universities share one Berlin row, so a
figure cannot drift between them — with one component per kind carrying `amount_low`,
`amount_high`, `currency`, `period`, `basis` (`VISA_NORM`, `INSTITUTION_ESTIMATE`,
`STUDENT_HOUSING_RATE`, `NATIONAL_STUDENT_SURVEY`), `access_note`, `cycle_year`, and the quoted
evidence for **each end**. `CostComponent` gains the same low/high and basis so a programme-level
figure is expressible the same way. `Program` gains a city reference. A component with no primary
evidence for that city is rendered **incomplete**, never inferred from another city, and an
option's card (§4.10) shows the gap as a range.

**Measured, not assumed.** §7 adds a gate: on a hand-checked sample of 20 launch cities, every
range's low end matches the housing body's current rate card and every end carries its quote —
because a plausible-looking cost range is the one error in this system a student cannot detect.

### 4.12 The schematic sweep — country × family × eligibility key, to an economic stop

**Measured 2026-09-17 and it changed this design** (`research/2026-09-17-cell-saturation-measurement.md`).
One cell — Germany × `PRIVATE_FOUNDATION` — with vocabulary the model generated itself across twelve
German term families, 99 queries and 396 calls for about $6, returned **353 German funding
organisations, 116 of them foundations**. The cell **did not saturate**: after two batches the rate
settled at 15–27 new funders per eleven queries and stayed there, batch 6 finding more than batch 3,
and the late arrivals were real long-tail bodies no register lists — `bwstiftung.de`,
`schleyer-stiftung.de`, `studienstiftungsaar.de`, and three that exist *because of* an eligibility
key (`stiftung-frauenforschung.de`, `stiftung-fuer-juedische-studien.de`, `szloma-albam-stiftung.de`).

So the sweep, not the register, is the spine for the families §4.8 marks as having no index. A cell
is **(country, family, eligibility keys, language)**. For each: the model generates query vocabulary
from the family's definition in the country's own language plus English; the engines run in their
§4.4 roles at full configuration; the harness counts **new origin hosts per batch** and each engine's
first-discoverer share.

**The stopping rule is economic, not exhaustive, because there is no exhaustion point.** Precision
does decay — the share of a batch that was a real German funder fell from 54% to about 27% — so a
sweep stops when the **cost per new verified award** exceeds what the option is worth to a student,
with the plateau rate and the precision decay as its two inputs. A cell's output is therefore its
**curve**, not a completeness claim: "we swept this cell to N queries, the plateau was R new funders
per batch at P precision, and here is the spend." That is a statement a counsellor can act on and a
student can be told.

**Index depth selects the route, and it is a prior we already hold.** Recall generalises across
countries; **precision does not**, and precision sets the reading budget. Share of returned domains
that are a funder based in the country: Germany **61%**, Türkiye 40%, Indonesia 26–46%,
**Azerbaijan 10–17%** — so Azerbaijan costs five to six times more reading per funder found, and its
English queries returned 37 funders of which only **6** were Azerbaijani. Azerbaijan also yielded
just 22 local funders across six configurations, with depth buying only ×1.7: there is no hundredth
Azerbaijani funder page to rank. **Where the index is thin the sweep is not the spine**, and the
route switches to the national register, ministry and agency hub pages (§4.5), hand-curation, and
Diffbot's entity graph, which held 2,596 Azerbaijani nonprofits against the 22 search surfaced. The
selector is each country's measurable index depth — the ROR, Wikidata and Diffbot counts already
recorded for 46 countries in `research/2026-09-17-search-tool-probe.md` and §4.2 — never a
per-country hand-tune. §4.7's classifier is therefore mandatory before the reader in a thin-index
country: without it, 85% of the reading budget is spent on foreign hosts that merely rank.

**What a sweep can and cannot claim.** It can claim saturation of the *indexes*, per cell, with
evidence. It cannot claim saturation of the world: DAAD's database is terms-blocked and
Hochschulkompass is search-only, so if their contents are not published elsewhere no sweep reaches
them. Search and registers close different holes — which is why §4.2 stays, demoted from spine to
denominator.

**Reading is the binding constraint, and §5's free-to-apply rule is what orders it.** 353 funders at
up to nine model calls a page is the expensive half against $2 of searching. The sweep therefore
produces a queue, and the queue is read **free-to-apply first**, because those options are worth
including for every student who has not excluded the country.

### 4.13 The roster, settled 2026-09-17 — one table, so it is not re-derived

Every source, its role, the configuration measured best, its terms standing and its ceiling. Each
row's evidence is one of the three notes: `research/2026-09-17-search-tool-probe.md` (four-provider
probe), `…-cell-saturation-measurement.md` (99-query plateau), `…-search-capability-ablation.md`
(flag ablation, four countries, regional engines).

| source | role | configuration that measured best | terms | ceiling / cost |
|---|---|---|---|---|
| **Exa** | primary index for the no-register families; best single performer | `type: auto`, **`numResults: 100`**, describe-the-entity phrasing, **local-language query**, aggregator denylist. **Not** `category: "company"` (−2.7 pts), **not** `includeText`. Every response carries `costDollars` — meter the per-cycle ceiling on **billed cost returned by the API**, never on an estimate | written permission, condition: no competing-search training | credits, not a plan: ≈$0.097/call at 100 results ($7/1k requests + $1/1k per result beyond 10), $10 free monthly; needs a per-cycle ceiling. The 25 QPS unlock costs $1,000 in 30 days and buys nothing this sweep needs |
| **Brave** | independent second index; the deepest per query | **`offset` 0–9**, stopping on the first **empty `results` array** — `more_results_available` is *not present in the response* (measured 2026-09-18, paid plan; do not gate the loop on it). A real German foundation query exhausted at offset 5 (110 results, 76 distinct hosts), so budget **~6 requests per query, not 10**. Hosted Goggle discarding aggregators and boosting institutional hosts, local-language query. **Not** `country`, **not** `search_lang` | written permission, same condition | prepaid Search plan: $5 per 1,000 requests, $5 free credit monthly, 50 rps (the free tier's 1 rps cannot carry a deep sweep). **Not** the Answers plan — we read only URLs |
| **Tavily** | name-to-site resolution for URL-less registers; `/map` for host inventory; a *decaying* local-language discovery leg the per-route tally drops early (62 → 5 first-discoverers across 99 queries) | `exact_match` with the quoted name; **`search_depth: basic`** — advanced costs 2 credits and measured **5× worse at resolution** (§4.13a). **Not** `language`, **never** `filter_by_language` | clean by structure ("Services" excludes "Output") | 1,000 credits/mo free and **advanced halves that to 500 calls**; §9.2 takes a perpetual licence over query text, so queries stay profile-free |
| **Firecrawl** | **the research fetch path** — scrape, crawl, map, change tracking, the cheap JSON first read (funder spec §4, owner decision 2026-09-18); PDF search channel | `/scrape` with `proxy: "auto"`, `changeTracking`, explicit `maxAge`; `/crawl` with `includePaths`; `/map` with `includeSubdomains`; `/extract` with a closed schema on hub pages; `categories: ["pdf"]` on search | fetch-side questions (retention, robots, TDM) rest with the vendor — owner decision 2026-09-18; `/search` for discovery stays off: unnamed upstream index | 1 credit/page, JSON +4; Standard $83/mo = 100k credits, 25 concurrent; free tier **429s at `limit=50`** on search and was the weakest first-discoverer (22 of 353) |
| **Diffbot** | standing per-country entity query; a graph, not an index | one `type:Organization isNonProfit:true` + `location.country.name` + `description:"<local scholarship word>"` per country per cycle. `categories` is the better axis than description keywords; `similarTo` is a refinement tool (5–19 rows), never an enumerator; `regex`/`strict` on name return HTTP 500/400 | explicit commercial grant, no storage clause, **no effective date** — re-read before each use. `type:Organization` enforced in code because the graph holds people | 400 entities/mo free at 5 calls/min; 25 credits per entity |
| **Baidu** (via SerpApi) | China only | `engine=baidu` — +7 institutions from 3 searches at **76% precision**, the highest measured | owner decision 2026-09-17; **built on SerpApi's free tier, owner decision 2026-09-18, with no Legal Shield** — the Shield starts at Production ($150/mo, verified 2026-09-18) and a reseller cannot grant rights to indexes it resells; remedies in §13 | 250 searches/mo free |
| **Naver** (via SerpApi) | Korea only | `engine=naver&where=web` — +5 Korean funders including two foundations | same; Naver's own developer API is the direct contract to prefer once its terms are read on the cited host (`developers.naver.com` refused the 2026-09-18 fetch) | same |
| **SerpApi / Google** | **transient yardstick only** | count what the clean engines missed, then discard the list | cannot grant rights to indexes it resells | **no host may enter the catalog because Google via SerpApi pointed at it**; a test asserts no `OfficialSource` carries a Google-derived `found_via` (`R4_SEARCH:google`). Baidu and Naver write `R4_SEARCH:baidu` / `:naver` — the engine — with the reseller recorded once in §8 |
| Wikidata, ROR, OpenAlex, DEQAR, EACEA API, VGM, crt.sh, Common Crawl | the denominator, and the spine where the web is small | §4.2 | CC0 / PDDL / open notice; crt.sh publishes none | no key; rate ceilings are the constraint |

**Rejected, with the reason, so they are not proposed again:** Perplexity (Search API overlaps Exa
and Brave; deep research costs $0.82/request against $2 for a 99-query sweep; Sonar sunset
27 Sept 2026); **Yandex** (0 new funders in Azerbaijan — a deeper regional index is not more of what
we seek); **Seznam** (small web, the Azerbaijan case); **Coc Coc** (Vietnam's web is large and openly
indexed — 70 Vietnamese funders from Brave and Exa, Google added one); Mojeek (no binding contract
located); Google Custom Search JSON API (closed to new customers, shutdown 1 Jan 2027 — re-verified
2026-09-18); aggregators as sources (§12). **Added 2026-09-18**
(`research/2026-09-18-vendor-per-axis-proposal-review.md`): **Tavily `include_answer` as label
enrichment** — an LLM-written answer, unverifiable against the page, so it fails the
quote-beside-every-fact rule and rests a product decision on Tavily *Output*; the labels it would
fill are already in `LineVerdict` from origin bytes. **Diffbot as the holder-axis enumerator** — its
ontology has no field for a nonprofit's subtype, religion, politics, profession or government
status (`categories` is a business taxonomy: Cusanuswerk → "Software Companies"); 28% precision,
400 entities/month. **Crawl4AI** — a fifth fetcher for the job four tiers cover.

**The five measured rules the configuration rests on.** (1) **Depth is the only capability that
reliably wins** and it needs no per-country enum. (2) **Write the query in the local language; never
ask a provider to filter by language.** (3) **Set no `country` filter** — inert at best, −8 local
funders in Indonesia. (4) **Precision, not recall, varies by country** — 61% in Germany, 10–17% in
Azerbaijan — and it sets the reading budget and the route. (5) **A regional engine pays only where
the national web is large *and* partly out of the global indexes' reach.**

#### 4.13a Tavily depth, measured 2026-09-18 — advanced is worse at the job Tavily has

`search_depth: advanced` was carried into the roster from Tavily's own guidance, not from a
measurement, and the roster had meanwhile changed Tavily's job from open-web discovery to
**name-to-site resolution**. Depth is a ranking improvement over a long tail; resolution reads one
result. So the question was whether we were paying double for a capability the job never uses.

**Method.** 30 German foundations whose official website Wikidata records (CC0, so a name→site pair
is public fact and not a provider artifact), each resolved *by name* with basic and with advanced,
scored on whether the returned registrable domain equals the recorded one.

| | correct |
|---|---|
| basic | **10 / 30** |
| advanced | **2 / 30** |

The two disagreed on 17 of 30, and the mechanism is legible rather than noisy: **advanced returns
the Wikipedia article instead of the organisation's own site** — Björn-Steiger-Stiftung, Deutsche
Stiftung Denkmalschutz, Bremer Heimstiftung, Claussen-Simon-Stiftung, Care-for-Rare all resolved
correctly on basic and to `wikipedia.org` on advanced. That is advanced doing exactly what it is
built to do, re-ranking toward comprehensive authoritative pages, which is the wrong direction when
the question is "what is this organisation's own website?"

**So: basic, for resolution.** Half the credits and five times the accuracy. Depth for Tavily's
*discovery* leg remains unmeasured; basic is the default there too until it is, because the cost is
certain and the benefit is not.

**The gate, measured the same day on a fresh account: FAILED.** 25 of the same names, both arms
`basic` with the denylist, varying only `exact_match`: **6/25 with it, 6/25 without** — 7/25 once a
truth-set artefact is corrected (Wikidata lists Carl Friedrich von Siemens Stiftung under two
domains; both arms returned the real one). Same band as round 1's 10/30, so neither the denylist nor
`exact_match` moves it. `exact_match` is neutral rather than harmful: the arms traded wins (it found
`die-bibel.de` and `denkmalschutz.de` where plain found a shop and a magazine; plain found
`krupp-stiftung.de` and `caritasstiftung-stuttgart.de` where it found the villa and a directory) and
their union is still 9/25.

**Search top-1 is not a resolution mechanism, at any depth, with any flag.** And the misses are not
noise a denylist can absorb — they are *adjacent* organisations: Carl-Zeiss-Stiftung →
`schott.com` (its own company), Krupp → `villahuegel.de` (its own villa), Care-for-Rare →
`lmu-klinikum.de` (its host clinic), Stiftung Gustav Werner → `diakonie-in-stuttgart.de`. A
fetch-and-check-the-name-appears verification would pass every one of those, so that is **not** the
fix either.

What the misses share instead: **the true domain is almost always the name slugified** —
`steiger-stiftung.de`, `bremer-heimstiftung.de`, `nikolaus-koch-stiftung.de`, `kind-hoerstiftung.de`,
`defa-stiftung.de`, `stiftung-demokratie-saarland.de`, `care-for-rare.org`. So the candidate fix is
deterministic: ask for the top 10, pick the result whose registrable domain matches the name's
tokens, otherwise return *unresolved* — an honest gap instead of a confident wrong site. And before
any search, ask Wikidata (P856) and ROR, which are free, CC0, and where this truth set came from.
**Measure the slug rule on the same 25 names before it enters an adapter** (~25 credits); it is an
open item in §13.

**Standing rule until that passes:** `resolve()` output is a *candidate* for classification (§4.7),
never a trusted site, and no URL-less register is ingested through it. That binds harder, not
softer, for the Türkiye VGM register that motivated it: this sample was German, Latin-script and
well covered by Wikidata; Turkish foundation names were not tested.

**The slug rule, measured the same day on the same 25 names — it works, and rank was the whole
problem.** One Tavily call each (`basic`, `max_results: 10`, denylist) plus one free ROR query;
TOP1 is scored on the *same responses*, so the comparison is exact.

| selector | correct | confident-wrong | unresolved |
|---|---|---|---|
| TOP1 — the failed configuration | 3 | 22 | — |
| **SLUG** — first of the top 10 whose domain lexically matches the name | **20** | **3** | 2 |
| ROR top hit's website | 7 | 17 | 1 |
| ROR-if-it-matches, else SLUG | 13 | 10 | 2 |

(SLUG was 19/4 as printed; `steiger-stiftung.com` is the same foundation's English site — verified by
title — so the truth set, not the resolver, was wrong there. An organisation can own two registrable
domains; the register keys on one, and the twin arrives as a second `CANDIDATE` row for §4.7 to merge.)

Four things this settles:

1. **The right site is in the top 10 for 22 of 25 names. Rank 1 is the wrong selector; a lexical
   match is the right one.** Same responses, 12% → 80%. Depth was never the lever — *selection* was.
2. **The three confident-wrongs are two rule defects and one hard case.** `bund.de` for the
   Bundesstiftung matched a 4-character domain token inside the *generic* name token
   "bundesstiftung" — rule (b) must test against distinctive tokens only. `zeiss.com` for
   Carl-Zeiss-Stiftung and `klosterlehnin.de` for the Diakonissenhaus each matched one token when a
   better candidate matched more — so **score every candidate by matched distinctive tokens and take
   the best, ties by rank**, instead of the first match in rank order. Both fixes are deterministic.
3. **The two unresolved are correct abstentions** — Stiftung Gustav Werner has no lexical link to
   `bruderhausdiakonie.de`, and that is exactly the case that must come back *unresolved* rather
   than confidently wrong.
4. **ROR is not a foundation register, and its fuzzy `query` is dangerous.** It returned a
   plausible research organisation for 24 of 25 names — `beethoven.de` for Ernst-Barlach-Haus,
   `robert-koch-stiftung.de` for Nikolaus-Koch-Stiftung — and a one-token lexical check let
   Robert-Koch through. Gating ROR and preferring it made the combined arm *worse* (13/10). This is
   §4.2's own warning bitten: a register is a denominator only for the population it actually
   enumerates. **Wikidata P856 first** (it is where these 80 foundations came from in one query;
   untestable on this sample only because it *is* the truth), **ROR only for research
   organisations, and never its fuzzy top hit without the same best-score check.**

**Resolver design, adopted:** Wikidata P856 → search top 10, best lexical score over distinctive
name tokens, else *unresolved*. `TavilyProvider.candidates(name)` returns the top 10 URLs; selection
lives beside the register writer, not in the adapter. **Remaining gate before VGM:** one 25-credit
re-run with the best-score selector and the rule-(b) fix (expect ≥ 22/25, confident-wrong ≤ 1), then
25 Turkish foundation names — this sample was Latin-script German, and Turkish is where it ships.

**The remaining gate, run twice more the same day — German passes, Turkish does not, and the
Turkish failure is structural.** Same method; two selector versions; truth corrected where a page
title proved the resolver right and Wikidata wrong (`co-berlin.org` *is* C/O Berlin, `.info` is
dead; `hrantdink.org` is the Hrant Dink Foundation's homepage, Wikidata points at its award site).

| sample, selector | correct | confident-wrong | unresolved |
|---|---|---|---|
| German 25, first lexical match (v1) | 20 | 3 | 2 |
| German 25, best score (v1 rules) | **23** | **0** | 2 |
| German 25, tiered evidence (v2) | 22 | 1 | 2 |
| Turkish 25, first lexical match (v1) | 12 | 6 | 7 |
| Turkish 25, tiered evidence (v2) | **11** | **3** | **11** |

Three findings, in order of consequence:

1. **German is settled at 22–23 / 0–1 / 2 across two rule versions.** The one v2 wrong is a rule
   defect with a one-line fix: the "token + one generic word equals the label" promotion admitted a
   *city* (`caritas` + `stuttgart`) and outranked the true site's org-word bonus; it must admit
   org-type words only (`stiftung`, `vakfı`). Wau Holland went unresolved when the 3-letter-prefix
   rule was dropped as unsafe — an accepted loss.
2. **Turkish is a different population and the resolver must be graded differently there.**
   German names carry a surname and resolve to the slugified name; Turkish names are common
   vocabulary — *Science and Art Foundation*, *Society and Law Research Foundation* — and resolve to
   **syllabic acronyms** (`bisav`, `tohav`, `tusev`, `istek`, `tustav`, `alikev`) that no lexical rule
   reaches. Those five must come back *unresolved*, and v2's tightening (a lone short common word is
   not evidence) is what stopped impostors taking them: confident-wrong fell 6 → 3 while unresolved
   rose 7 → 11. **44% unresolved is the honest shape of Turkish, not a defect to tune away.** Two of
   the three remaining wrongs are adjacent organisations the lexical layer cannot separate
   (`inonu.edu.tr`, the university, for İnönü Vakfı; `kansersavascilari.org` for Kanserle Savaş
   Vakfı, where two matched common words beat one word plus the org-word); the third is a suffix tie
   (`tema.org` over `tema.org.tr`) that a ccTLD preference settles.
3. **Tavily's top 10 varies between identical calls** — `ferdizeyrekvakfi.org` was in the ten on one
   run and absent the next; `alikev.org` moved to rank 1. One or two cases per 25 is the noise floor;
   do not read a single-case delta between runs as a rule effect.

**What separates the Turkish impostors is the origin, and the fix costs no credits.** Every
confident-wrong above has a page `<title>` that does *not* name the organisation — `İnönü
Üniversitesi`, not İnönü Vakfı — while every correct answer's does, and this is stricter than the
"name appears somewhere on the page" check §4.13a rejected: Villa Hügel's title is not
"Alfried Krupp…-Stiftung". So the resolver's third step is **fetch the chosen candidate through the
existing egress and accept only if its `<title>` / `og:site_name` matches the name at tier ≥ 2**;
otherwise unresolved. Deterministic, origin-verified (the repo's provenance rule applied to
resolution), and one free fetch per name. **Gate before VGM: measure title verification on both
25s** (zero provider credits, ~50 origin fetches); expected outcome is Turkish confident-wrong → 0
with unresolved unchanged, and German unchanged.

**Standing decision:** the resolver ships German-grade — Wikidata P856 → top 10 → tiered lexical
best-match → *unresolved* — and for Türkiye its output is a candidate until title verification is
measured. The URL-less VGM register is read only after that.

**Title verification, measured 2026-09-18 — as first designed it caught nothing; with one more
condition it catches exactly the class that was left.** Selector v3 plus "the homepage `<title>` /
`og:site_name` contains one distinctive word of the name", runner-up gets one try; ~50 credits to
re-obtain the candidate lists (never stored) and ~50 free origin fetches.

| sample | select v3 | + title, one-word rule | impostors rejected by title |
|---|---|---|---|
| German 25 | 22 / 1 / 2 | 19 / 0 / 6 | **0** |
| Turkish 25 | 12 / 4 / 9 | 9 / 2 / 14 | **0** |

(correct / confident-wrong / unresolved; truth corrected as above.) The one-word rule rejected **no
impostor in either sample**: every remaining impostor is an *adjacent* organisation whose title
contains the shared word — "Kanser Savaşçıları" for Kanserle Savaş Vakfı, "ZEISS" for
Carl-Zeiss-Stiftung. That is the lexical problem one level up, not a check on it. The drop in
correct answers came from my harness, not the rule: it skipped verification for tier-1 selections
(three true German sites, one Turkish) instead of verifying them, and five of fifty selections
failed to fetch.

**Org-type agreement is the discriminator.** A zero-credit probe of the twenty ambiguous pairs, each
title fetched and both rules applied side by side:

| title rule | accepts right | accepts **wrong** | rejects right | rejects wrong |
|---|---|---|---|---|
| A — one distinctive word (as run) | 8 | **3** | 1 | 2 |
| B — A **and** the title names the same *kind* of organisation | 8 | **1** | 1 | 4 |

The name says *Vakfı* and the title says *Derneği* (an association) or *Üniversitesi* or nothing —
that rejects `kansersavascilari.org`, `zeiss.com` ("Solutions to shape the future | ZEISS") and
`villahuegel.de`, and accepts `hrantdink.org` ("Anasayfa - Hrant Dink Vakfı") and
`ismetinonu.org.tr` ("İnönü Vakfı, İsmet İnönü …"). The one impostor B still accepts is `tema.org`
(Tubular Exchanger Manufacturers Association): the name "TEMA" carries no org-type word, so there
is nothing to agree on — only the ccTLD tiebreak or the true site being in the ten saves it, and
the ten varies between calls. The one true site B rejects, `die-bibel.de`, has a title that does
not name the society; unresolved is the right answer for it.

**Fetch failure is a real cost, ~10%, and it is the hosts, not the harness.** Five of fifty
selections and six of the twenty probe pairs did not answer within 25 s; every one was re-tried
with curl while `zeit-stiftung.de`, `tev.org.tr` and `example.com` answered in under a second.
Two Turkish institutional hosts (`inonu.edu.tr`, `tskgv.org.tr`) serve **broken certificate chains**
(`ssl_verify_result 20`); four (`barlach-haus.de`, `caritas.de`, `caritasstiftung-stuttgart.de`,
`ttgv.org.tr`) return no HTTP response at all from this vantage point. The product egress will fail
them identically. **A failed fetch is *unresolved*, never accepted**, and Türkiye needs the retry
queue more than Germany does.

**One more selector defect, and it is the exact-label promotion.** "The label *is* a single name
token" was meant for `tema`, `kent`; it also fires for a shared brand word — `caritas.de` (national
Caritas, outranking the Stuttgart foundation), `vakifbank.com.tr` (the bank, for its publishing
arm), `inonu.edu.tr` — one right against three wrong. It is demoted to tier 1, which under the rule
below means it is always title-gated and always loses to a candidate carrying the name's org-word.

**Resolver design v4 — the last version before it becomes code:**
Wikidata P856 → Tavily top 10 (`basic`, denylist) → tiered lexical score (initials / full slug = 3;
two distinctive tokens, or one token + the name's org-word forming the label = 2; one token ≥ 6
chars, or the label equal to one token = 1; +0.5 org-word in label, +0.25 country ccTLD) → **every
selection below tier 3 is fetched through the existing egress and accepted only if the title (a)
names the same kind of organisation and (b) contains a distinctive token, the acronym, or the name
slug** → otherwise, and on any fetch failure, *unresolved*. Expected on these samples: German
≈ 22 / 0 / 3, Turkish ≈ 10 / 1 / 14 — and every expectation so far has been wrong in one direction,
so **v4 is measured once (~50 credits) before it enters an adapter.** Turkish syllabic acronyms
(`bisav`, `tohav`, `tusev`, `istek`, `alikev`) stay unresolved by design; their answer is a
URL-carrying register or a person.

**v4, measured 2026-09-18 — it passes, and it is the design that enters code.** Same 25 + 25, ~50
credits; truth corrected as above.

| sample | select (v4 lexical) | **v4 = select + title with org-type agreement** |
|---|---|---|
| German 25 | 23 / 0 / 2 | **20 / 0 / 5** |
| Turkish 25 | 11 / 4 / 10 | **12 / 1 / 12** |

Confident-wrong: **0 and 1**. The title step did exactly what the probe predicted — it rejected
"Kanser Savaşçıları" (*Derneği* against *Vakfı*) and the runner-up `kanservakfi.com` was accepted,
the run's one rescue; it rejected `barlach-museen.de` ("Ernst Barlach Museen", a different body); it
turned `inonu.edu.tr` and `vakifbank.com.tr` into *unresolved* rather than wrong. The cost landed
where the fetch-failure measurement said it would: two true German sites are unresolved because
their hosts do not answer (`barlach-haus.de`, `caritasstiftung-stuttgart.de` — unreachable to curl
too), and `die-bibel.de` because its title does not name the society. Prediction was 22/0/3 and
10/1/14; reality 20/0/5 and 12/1/12 — wrong in one direction on each, as every prediction today has
been, which is the argument for having run it.

**The one remaining wrong is a class, not a bug: a single-word name.** "TEMA" carries no kind-word
to agree on, so `tema.org` (Tubular Exchanger Manufacturers Association) passes both the lexical
tier and the title check; only the ccTLD tiebreak separates it from `tema.org.tr`, and only when the
true site is in the ten. **Rule: a one-token name is never resolved from search alone** — it needs
a register, the ccTLD match, or a person. Tier-3 (initials / full slug) otherwise ships unverified,
and that saved `tskgv.org.tr` and `ttgv.org.tr`, both correct and both unreachable.

**Adopted.** Wikidata P856 → Tavily top 10 (`basic`, denylist) → tiered lexical score → title check
with org-type agreement for every pick below tier 3 → *unresolved* on mismatch, on fetch failure,
and for one-token names. Unresolved is 20% German / 48% Turkish and is the honest shape; a retry
queue recovers the transient half of the fetch failures, a URL-carrying register or a person the rest.

#### 4.13b Acceptance test on held-out scripts, 2026-09-18 — **FAIL**, and what it taught

Owner directive (2026-09-18): the engine must be general across any country, script and funding
family; per-country numbers are *development* scores. So the resolver was generalised **from
principle, before any hold-out was drawn** — `unidecode` romanisation with a symmetric fold; the
organisation-kind vocabulary pulled from Wikidata labels and aliases in 26 languages (976 words,
16 kinds) instead of hand-typed German/Turkish lists; language-agnostic morphology tolerance
(*vakfı* ≈ *vakıf*); one-token names requiring the country ccTLD — then frozen, and 25 Georgian
(21 in Georgian script) and 25 Kazakh (13 Kazakh, 2 Russian, 10 English) organisations were drawn
from Wikidata in item order, unseen until scored.

| sample | role | select | **v5 = select + title(kind)** | v4 hand-tuned, for reference |
|---|---|---|---|---|
| German 25 | dev | 17 / 4 / 4 | **15 / 4 / 6** | 20 / 0 / 5 |
| Turkish 25 | dev | 11 / 4 / 10 | **10 / 1 / 14** | 12 / 1 / 12 |
| **Georgian 25** | **hold-out** | 6 / 4 / 15 | **5 / 3 / 17** | — |
| **Kazakh 25** | **hold-out** | 1 / 11 / 13 | **1 / 11 / 13** | — |

(correct / confident-wrong / unresolved.) **The generalised resolver is not general.** Turkish held;
German lost what the hand lists knew; Georgian mostly abstained; Kazakh was confidently wrong 11
times in 25. Every cause is structural, and every one is a design rule rather than a tuning:

1. **The kind vocabulary was 16 kinds; the world has ~50.** *Embassy*, *federation*, *club*,
   *consulate*, *commission*, *society*, *academy* were absent, so "embassy" counted as a
   *distinctive* token and matched **directories** — `embassypages.com`, `embassies.info`,
   `embassy-finder.com`, `embassy-worldwide.com` — nine of Kazakhstan's eleven wrongs. Rule: the
   kind list is enumerated from Wikidata's organisation subclass tree, not chosen by hand; **and a
   candidate whose label is nothing but kind words is a directory, never an organisation**
   (`embassies.info`, `stiftungen.de`, `vakiflar.gov.tr`) — a structural denylist, not a typed one.
2. **Country and city names must be generic, from a source.** `qazaqstan.tv` twice for embassies
   (the country name as a "distinctive" token), `samtredia.gov.ge` (a municipality) for FC
   Samtredia, `visitberlin.de` for C/O Berlin. v4 knew *Türkiye*, *Berlin*, *Stuttgart* because
   I typed them; v5 knew none. Rule: country labels and demonyms in every language, and the
   country's settlements, come from Wikidata (P17 → P31 city), never from a list.
3. **Compounds.** *Bundesstiftung* is not in any lemma list, so its stem "bundes" matched
   `bundestag.de` (accepted — the title contains the "acronym"). Rule: a token that *ends with* a
   kind word is a kind word.
4. **Domains are very often acronyms of the ENGLISH name, whatever script the organisation
   writes in.** Georgian's 17 unresolved are `gyla.ge` (Georgian Young Lawyers' Association),
   `idfi.ge`, `gmu.ge`, `bsma.edu.ge`, `tesau.edu.ge`, `geostm.ge` — none derivable from the
   Georgian name, all derivable from the English one by the initials rule already in place. Rule:
   **resolve with every name variant the register or Wikidata supplies** (native, English,
   Russian), and score the union. This is the largest single gain available and costs nothing.
5. **Some truths are unreachable by name, and the correct output is *unresolved*.** Wikidata
   gives an embassy the parent ministry's domain (`esteri.it`, `mzv.cz`); no name→site mechanism
   reaches that and none should try. Seventeen of the Kazakh 25 were foreign embassies — a
   property of drawing "organisations with a website" blind, and a fair stress test: an embassy
   *is* a scholarship hub (§4.5), and its site is the ministry's. The failure here was not
   missing `esteri.it`; it was confidently returning a directory instead of abstaining.
6. **Provider variance is larger than one rule's effect.** Two of German's five losses
   (`bodensee-stiftung.org`, `euronatur.org`, both tier 3 in v4) were simply absent from this
   run's ten. Any per-run comparison of two rule versions on 25 names is inside the noise unless
   the candidate lists are held fixed across versions — which the retention rule forbids
   persisting, so **A/B two selectors in the same process on the same responses**, as the earlier
   runs did, and never across runs.

**What survived the hold-out unchanged:** the shape — deterministic evidence over a top-10 beats
rank; verify at the origin; abstain — and the title check with kind agreement, which rejected
`istanbul.edu.tr` for İstanbul Eğitim ve Kültür Vakfı, `iset.ge` (a school) for its parent
university's commission, and `hivresearch.org` for a US Army institute, and made no false
rejection that a reachable, self-naming site could have avoided.

**Standing decisions.** (a) v5 is **not** adopted; the resolver's *requirements* are now the six
rules above plus v4's tiers, and the next version is measured on a **fresh** hold-out (Uzbek,
Indonesian or Vietnamese — a script or morphology not yet seen), never on Georgia or Kazakhstan
again, which are now development data. (b) No further tuning runs until page-level yield (§7a) is
measured: the resolver is one seam of the register path, and the decisive number for the whole
design is still owed. (c) `Organisation` gains **`names: ArrayField`** — every label the register or
Wikidata supplies — because rule 4 needs them at resolution time and §4.7's classifier will want
them too.

#### 4.13c Page-level yield on funder hosts, measured 2026-09-18 — **2 served in 58 hosts, neither a funder**

The funding reader (`funding_judge.py` on `claude/programme-funding-reader`, run unmodified and
pure, no database) over 58 hosts that today's discovery produced for DE, TR, AZ, GE, KZ: per country
a systematic 8 from discovery output as-is (tier A) and up to 4 whose domain carries a funding word
(tier B, a stated stand-in for the unbuilt classifier). Homepage plus up to three on-host funding
pages each, shell-checked and read exactly as `pipeline._fund_page` reads; "served" is
`write_funding_decision`'s own gate. 88 pages, **399 model calls, 102 minutes.**

| | hosts | fetched | pages | calls | **served** | agreed-unserved | **unagreed** | abstained |
|---|---|---|---|---|---|---|---|---|
| all | 58 | 48 | 88 | 399 | **2** | 0 | **45** | 5 |

Both served awards are **university money on non-funder hosts**: `ua.edu` (a US university that
fell into the Kazakh query's results — "Merit and competitive aid") and `master-and-more.at` (an
Austrian study portal's page on *Leistungsstipendien*). **Every foundation read served nothing:**
Cusanuswerk (10 pointers, 2 unagreed), SBB-Stipendien (18 pointers, 3 unagreed), Studienfonds OWL,
Begabtenstiftung Informatik (4 unagreed), bw-stipendium (4 unagreed), Carina-Stiftung, Anadolu Vakfı,
Abdi İbrahim Vakfı, oilfund.az, bekaiafund.org. Zero errors; abstention 5 — again not the constraint.

**Diagnosis — the reader has no word for a funder's award, so it cannot serve one.** Its kind
vocabulary is seven institution-side families (`I1_UNIVERSITY_WIDE` … `I7_PAID_PLACEMENT`) and its
scope vocabulary ends in `POINTER`, "money a student gets by applying elsewhere" — which is exactly
what a foundation's own scholarship page is under that menu. A foundation award therefore lands as
a *pointer* (never served) or as *unagreed* (the two families argue over a kind that does not fit).
That is why the two funders with the richest scholarship pages produced the most pointers. The
reader was built for §4.8's institution side and does its job there; §4.9's funder-side families
have no entry. **This is a schema finding, not a tuning one, and it is the decisive number: today,
discovering a funder cannot produce a card.**

Also measured on the way: **8 of 58 hosts refused by our egress** — 3 bot-blocks (HTTP 403, two
news sites and `bm.ge`), 2 that answer a browser-like request, 1 server error, **Georgia's education
ministry on a broken TLS chain**, 1 timeout. Stealth fetching would recover the first two classes
(5 of 8) and none of the rest; the owner's 2026-09-15 decision retired Scrapling in favour of the
vendor fetch path, so the 403 class routes through Tavily `extract`, and TLS/5xx are *unreachable*
for retry. Cost of a text-heavy page: 10–15 minutes and up to 36 calls. And `pointers` are
discovery signal thrown away: one Turkish aggregator page named 31 funders.

**Decisions recorded 2026-09-18 (owner asked for them plainly):**
1. **Stop widening discovery; give the reader the funder-side kinds first**, then re-run this exact
   host list unchanged. That re-run is the measurement that proves the diagnosis.
2. **Pointers become leads** into the `Organisation` register.
3. **Disagreement rule:** a third reading breaks ties on `offered`; everything else unagreed goes
   to the human queue.
4. **The human queue is one component** — feeds: unresolved names, unagreed awards, unreachable
   hosts; `ConsultantResearchTask` exists for blocked fetches and is listed on no screen; owner
   decides whose queue it is.
5. Resolver knowledge as data (Wikidata kinds, places, English name variants), one fresh-script test.
6. Classifier before any corridor is swept at scale.

**A practical finding about the meter:** `GET /usage` **lags** — it read 790/1000 before this work,
during it, and after the account had already started refusing calls. It cannot be used as a
pre-flight budget check, which is how these two runs consumed the rest of the cycle.

**The discipline that survives every terms position**, and is kept regardless: only a URL is read
from any provider response; the origin is fetched and validated; nothing from a provider object is
persisted (§4.6). What lands in the catalog is what the institution's own server returned.

## 5. Aiming by demand cells — how a student's profile reaches discovery without reaching a provider

**The student never prompts discovery; the student's cell does.** A `DemandCell` is a bucket of
students with the same needs: destination set (a country list, or "anywhere in Europe"), discipline
bucket (the 28-value middle tier the 2026-08-28 design adopted), level, teaching languages, the
eligibility keys the student *holds* (§4.9), and funding need (`FULL` — can attend only with a
scholarship — or `PARTIAL`). No personal fact survives into it. It is a function over the profile;
whether it is also a table is implementation.

Why it must be this shape and not "search for this student": Tavily §9.2 takes a perpetual licence
over every query string and Perplexity forbids personal data in queries — the 2026-08-27 design's
profile-free rule is an ongoing obligation; the catalog is shared, so no tenant may steer what
every tenant reads; and an award discovered once serves everyone in its cell — the instrument-mode
rule, "discovered once, matched afterwards by rule".

**The loop.**

1. Consultation → structured profile and desires (built; `idea_v2.md`).
2. Profile → `DemandCell`. The one step where a model reads the profile: free-text field to the
   28 buckets, circumstances to eligibility keys, budget to funding need. Output is closed
   vocabulary; a test asserts no profile field reaches any query the planner emits (§8).
3. Pack = the optimizer over the catalog, filtered by the student's eligibility keys, ranked by
   desires — fully-funded-first or balanced fit, duration mandatory or weighted, industry or
   research goal. **Desires are ranking inputs, never discovery inputs.** The one desire that
   widens discovery is destination openness, and it does so only by widening the cell.
   **A free-to-apply option is not personalised at all**: by §2's owner policy it belongs to every
   student who has not excluded its country, so it is swept and read **once** into the shared
   catalog and merely filtered per student. Cells exist to aim the *paid* half of discovery, where
   the fee budget binds and the student must choose.
4. The optimizer's two honest outcomes — no floor found, budget unspent — aggregate per cell into
   the coverage instrument the 2026-08-28 design specifies and the 2026-09-15 audit records as
   unbuilt. Aiming priority of a cell = active students in it × its thinness.
5. Discovery runs per cell with templated queries built from cell vocabulary only — country,
   discipline bucket, the eligibility-keyed phrasings of §4.9 — registries first (§4.2), then the
   role-routed search (§4.4), then inventory of the hosts found (§4.3).
6. A student whose cell is thin triggers a **bounded cell sweep**: the same profile-free queries,
   capped at 40 provider calls and one inventory pass, run within minutes. Until it lands, the
   pack shows the cell's coverage state — *visited, N awards* / *visited, none found* / *unknown* —
   and never "no funding" (2026-09-13 design, test 3).
7. A new card reaches every student in a matching cell at the next pack refresh.

**Corridor order — a priority ordering, never a classification.** No country is "an origin" or "a
destination": every country is a destination for some student, and the split belongs to a demand
cell. Vietnam makes the point — it appears below as a launch *origin*, and it holds at least 70
funders offering inbound master's money to international students (`fulbright.edu.vn`,
`buv.edu.vn`, `cfvg.org`, `bkfund.vn` and a long university tail), which an Indian, Pakistani or
Nigerian student in a matching cell should see. Priority, then: Azerbaijan and Türkiye home-side;
Germany, Netherlands, Sweden, Hungary, France, Italy destination-side — then Caucasus / Central
Asia, then India, Pakistan, Vietnam, Indonesia, **each as both**. Within a cell: registries (free) → inventory of every registered HEI
(crt.sh free; `/map` one credit each) → search for the no-index families → hub harvesting of the
ministry and agency hosts the search found. Country is an **aiming term for organisation
discovery** (a funder is of a country) and stays an output for programme discovery; that resolves
the design/code conflict the 2026-09-15 audit recorded — `DiscoveryQuery.country_code` reaching
the query text is correct for the organisation path and wrong for the programme path, and the two
paths get separate query types.

## 6. Freshness

Registries re-enumerated monthly (DEQAR daily CSV, Wikidata, ROR) — diff, not replace. Inventory
per HEI quarterly. Search sweeps per corridor once per admissions cycle plus a recency-windowed
pass (Tavily `time_range`, Brave `freshness`, Exa `startPublishedDate`) monthly in the
announcement season for newly announced schemes — measurable only by novelty and precision, never
recall, and tallied as its own route. **Re-verification is its own cadence** (funder spec §3.5.4): monthly, weekly in an organisation's
announcement season, daily within 14 days of a known deadline, on the evidence pages only, with
change tracking making an unchanged page cost one credit and no reading.

## 7. Measurement — gates before scale

Gold sets, all free: **institutions** — DEQAR minus ROR for TR, AZ, KZ, GE (AZ: 45 in WHED vs 13 in
DEQAR is itself a "registers disagree" set); **Turkish funders** — the VGM scholarship-giving list;
**outbound funders** — the ~30 official hosts in the origin-side research (`htp.edu.az`,
`bolashak.gov.kz`, `iec.gov.ge`, `el-yurt.uz` …); **sub-units** — crt.sh host lists per university.

Metrics, per route and provider: **awards per page fetched** — the headline, because reading is the
binding constraint; **cost per new verified award**, which is the sweep's stopping rule (§4.12);
the **plateau rate and precision decay** per cell, recorded as its curve rather than as a coverage
claim; **in-country precision** — the share of returned domains that are a funder based in that
country, measured at 61% for Germany and 10–17% for Azerbaijan, which is what sets a cell's reading
budget and what tells a thin-index country to switch route (§4.12); host recall against gold; novel hosts (found by this route only);
aggregator leak; **cards filled** — of the awards a route surfaces, how many carry the §4.10 card the pack
can show; classifier accuracy on a 100-host hand-checked sample (≥ 95% on `kind` before any
count is quoted); **page-level yield** — of 50 `CANDIDATE` funder hosts and 50 registered HEIs, how many produce a
served award through the reader, per family — **the decisive number**, measured before the sweep
is scaled past two corridors; variance over
three runs of the same sweep (the repo has seen ±2/16).

Switch-off rule (2026-09-13 §7, kept): a route or provider that finds nothing the others miss
across two destinations is disabled and the tally says so. The harness extends
`scripts/search_recall.py` with a fixture shape that carries no host (open-web, not
`include_domains`) and matches on registrable domain.

### 7a. Readiness ledger, 2026-09-18 — what is measured, what is owed, and what each blocks

Read before starting any increment. "Measured" means a number with a recorded method in this repo;
"owed" means the spec relies on it and no such record exists.

| gate | status | number | blocks | cost to close |
|---|---|---|---|---|
| Provider roster, depth, negative flags | **measured** | ablation note; Brave +47–104%, Exa ×1.7–3.4; filters −1 to −8 | — | — |
| Paid depth live, per-call cost | **measured** 09-18 | Exa `costDollars` = $0.097; Brave exhausts ~offset 5; `more_results_available` absent | — | — |
| Registrable-domain key | **measured** | tldextract offline on `edu.tr`/`ac.uk`/`gov.az` | — | — |
| Name→site resolution | **measured; acceptance FAILED** 09-18 | dev DE 20/0/5, TR 12/1/12 (v4); held-out GE 5/3/17, **KZ 1/11/13** (§4.13b) | increment 5 / VGM; `Organisation.names` | six general rules (§4.13b) then a **fresh** hold-out (UZ/ID/VN), ~25 credits |
| Name→site resolution, residue | **measured** 09-18 | Diffbot Enhance 7/10 on names lexical rules cannot reach (`research/2026-09-18-tool-capability-oversights.md`) | resolution ladder step 3a | confidence threshold on the next 50 |
| Fetch-failure rate of origin hosts | **measured** 09-18 | ~10%; 2 TR hosts with broken cert chains | resolver, reader | retry-queue policy (design line) |
| Register coverage in thin corridors | **measured** 09-18 (rough) | Wikidata foundations with site: DE hundreds, **AZ 16, KZ 6, GE 7** | increment 3 expectations | — (recorded) |
| Saturation plateau | measured on **one dense cell, pre-depth config** | 15–27 new per 11 queries, 99 queries, $6 | increment 9's stopping rule | re-run at depth ≈ $13; a thin AZ cell ≈ $10 |
| Provider result variance | observed | 1–2 of 25 per repeat call | §7 tallies must be cumulative across cycles, not per run | design line |
| **Page-level yield** — awards served per host read | **measured on both, 09-16 and 09-18: effectively zero on funders** | **2 served / 69 rows / 497 EACEA leads**, 15 h, both families live — `docs/superpowers/2026-09-16-funding-reader-precision-run.md` on branch `claude/programme-funding-reader` (the reader is not on this branch; §7a's earlier "no recorded measurement" was wrong). Its finding: the constraint is **inter-family disagreement** (53 unagreed, 17 on whether the page offers funding at all), not abstention | scaling past two corridors; increments 6–7 | 58 funder hosts, five countries: **2 served, both university money on non-funder hosts; 45 unagreed** (§4.13c). Cause is the reader's kind vocabulary, which has no funder-side entry |
| Classifier accuracy (§4.7) | **owed — not built** | gate ≥ 95% on `kind`, 100 hand-checked hosts | every `Organisation.kind`; the sweep's placeholder kind | prompt + 100-host key ≈ $3 before the build |
| Cards filled (§4.10) | owed | of awards surfaced, how many carry amount/deadline/eligibility | increment 6 | follows yield |
| Three-run variance of a sweep | owed | repo has seen ±2/16 | trust in any coverage number | 3× one cell |
| Cost ceiling enforcement | owed (design) | Exa: `costDollars`; Brave: request count; Tavily: **local counter — `/usage` lags** | increment 2 | plan task |
| Goggle hosting | **closed 09-18** | Brave accepts the Goggle inline; nothing to host | none | — |
| Terms filing (Exa/Brave permission letters; Firecrawl upstream; Diffbot effective date) | owed | — | increment 2 (keys read in production) | `docs/legal/`, a request |

**Order that follows from the ledger.** Page-level yield first — it is the one number that can
make the rest of discovery moot, it needs no new code (the reader exists), and it can be run today
on hosts this session already verified. Then the classifier's 100-host check, because the register's
`kind` column is only as good as it. Then the AZ resolution sample and the thin-cell plateau, because
the launch corridor is the least-measured one. Increments 1–2 of the plan can proceed in parallel
with all three; increments 3–5 should not scale past a test corridor until yield is known.

## 8. Legitimacy, security, cost

**Terms record** — one row per provider, filed before its key is read in production:

| provider | status | artifact | condition |
|---|---|---|---|
| Tavily | clean by definition ("Services" excludes "Output"; Output includes "links") | ToS 4 May 2026, quoted in the 2026-08-30 synthesis | §9.2 perpetual licence over query text → every query profile-free; §3.2(xvi)/§6.6 ADM clauses as recorded in `CLAUDE.md` |
| Exa | **written permission** (owner correspondence, 2026-09-17) | to file: `docs/legal/2026-09-provider-permissions.md`, redacted | no use of Output to train a competing search model — we do not |
| Brave | **written permission** (owner correspondence, 2026-09-17) | same file | same condition |
| Firecrawl | **the fetch path; owner decision 2026-09-18: retention, robots and TDM questions rest with the vendor** | funder spec §4 | `/search` for discovery stays off — unnamed upstream index; PDF category channel only |
| Perplexity | deferred (§13) | — | Addendum: Output not owned; queries retained; no personal data in queries |
| Wikidata, ROR, OpenAlex | CC0 | — | — |
| DEQAR | PDDL metadata; report PDFs CC-BY-SA, never mirrored | 2026-09-11 DEQAR design | — |
| crt.sh, Common Crawl | no grant / limited service licence over crawled bytes | — | one query per domain per second, cached |
| SerpApi (Baidu and Naver only) | **owner decision 2026-09-18: free tier, no Legal Shield** | `serpapi.com/pricing`, `/us-legal-shield`, read 2026-09-18 | resells indexes it cannot grant rights to; the Shield applies from Production ($150/mo) only; the Google engine never writes a catalog row; Naver's own API preferred once read |

`CLAUDE.md`'s provider section is amended in the increment that files the permissions: the
sentence ruling Exa and Brave out becomes "permitted in writing, condition: no competing-search
training", and the "never persist a provider result object" rule stays as engineering discipline.

**Security.** Every discovered URL walks the existing egress (`validate_public_url` per hop,
content-type and size caps, `looks_unrendered`). Classifier input is origin bytes, labelled as
data; output schema-constrained; tokens capped; per-run rate limit. No student data ever forms a
query (Tavily §9.2, Perplexity 2.3): queries are built from country and family vocabulary only,
and a test asserts the planner's output contains no profile field.

**Cost, launch corridors (AZ + TR home-side, six destination countries), per cycle.** Search: 5
no-index families × 3 phrasings × ~8 country contexts ≈ **120 queries per index**, priced at
§4.13's settled depth — which is where the money goes. Exa: 120 calls at `numResults: 100`,
**$0.097 each** — confirmed by the API's own `costDollars` field on a live call, 2026-09-18 — ≈
**$11.60**. Brave: `offset` pagination makes each query several requests, but a real funder query
exhausts around offset 5 rather than 9 (measured, same date), so 120 queries ≈ 780 requests at $5
per 1,000 ≈ **$3.90**. Tavily: 120 advanced (240 credits of the 1,000 free).
Inventory: ~500 registered HEIs × 1 Firecrawl `/map` credit (500 of 1,000 free) + crt.sh free.
Classification: ~1,500 new hosts × one capped model call (~$3–5). Resolution: ~400 VGM/Wikidata
names × 1 Tavily credit. Registries: free. **Total ≈ $19–21 per cycle at launch scale, against $15
of free monthly credit (Exa $10, Brave $5) — so roughly $4–6 billed.** An earlier draft of this
line said "well under $20" on $1.80 of search; it was written before §4.13 settled the depth
configuration, and depth is the whole cost. Rate ceilings (Wikidata 5 parallel, ROR 2,000 per
5 min, Common Crawl 24-hour IP blocks) are still the real constraint — Brave's prepaid Search plan
lifts its own to 50 rps — and the sweep is paced to them.

## 9. Data

**New tables**, all shared catalog (`catalog_ingestion` writes, every tenant reads, added to
`_SHARED_TABLES` in `tests/tenancy/test_database_isolation.py`):

- `Organisation`, `OrganisationIdentifier` — §4.1, keyed on registrable domain.
- `CityCost` and its components — §4.11, one row per city, each component carrying
  `amount_low`/`amount_high`, `currency`, `period`, `basis`, `access_note`, `cycle_year` and the
  quoted evidence for **each end**.
- `CellCoverage` — §5, the aggregate of the optimizer's no-floor and underspend outcomes per
  demand cell, plus each cell's last-swept timestamp. Tenant-scoped, not shared: it counts a
  tenant's own students.

**Changed:** `FundingOpportunity` gains `eligibility_keys` (§4.9) and accepts `DISCOUNT` in
`money_form`; `FundingBenefit.Kind` gains `APPLICATION_FEE`; `BenefitRule` is written for the
card's eligibility, amount, duration and deadline rules, each with its quote (columns exist, no
writer today); `CostComponent` gains `amount_low`/`amount_high` and `basis`; `Program` gains a
city reference; `domains.py` gains the denylist and steering tables; `found_via` gains the
per-route vocabulary of §4.6.

**Unchanged:** `Institution` (still written only by `write_catalog_entry`), `OfficialSource`,
`OfficialSourceSnapshot` and the evidence-claim tables; the reader's decision procedure. Nothing
from a provider response is stored beyond the URL that was fetched and its `found_via` tag.

## 10. Increments

1. **Register and key.** `Organisation` + identifiers; registrable-domain utility on the Public
   Suffix List (one small dependency, justified by `edu.tr`/`ac.uk`/`gov.az`); dedupe; RLS test.
2. **Technique layer and protocol.** `SearchProvider`; `AGGREGATOR_DOMAINS`; steering tables;
   Exa and Brave adapters; hosted Goggle committed to the repo; Tavily adapter fixed;
   `EntityExpansionSource` retyped. Terms record filed; `CLAUDE.md` amended.
3. **Registries.** Wikidata, DEQAR, ROR, EACEA API enumerators; VGM one-off.
4. **Inventory.** crt.sh + `/map`; infrastructure patterns; unit classifier; `HEI_UNIT` rows.
5. **Hub harvesting.** Firecrawl `/extract` on named pages; `exact_match` resolution.
6. **The card the reader owes.** `eligibility_keys` and its vocabulary; the named cases in the
   closed question; `DISCOUNT` and `APPLICATION_FEE`; amount, period, duration, deadline, **timing and cycle**
   (§4.10, 2026-09-18) written with their quotes into `FundingBenefit`/`BenefitRule`. Gated on the §7 cards-filled
   tally — this is sub-project 5's work carrying this design's decisions, and the option card
   cannot be shown before it lands.
7. **City cost.** The student-housing register per launch destination; `CityCost`; the cost page
   added to the programme page set; the 20-city hand-check. Blocks nothing upstream but blocks
   any pack that states a funding gap.
8. **Demand cells and coverage.** Profile → cell (the one model read); the no-profile test;
   `CellCoverage` aggregated from the optimizer's two outcomes; the coverage state the pack
   renders; the bounded cell sweep at its 40-call cap.
9. **The sweep harness.** Cell definition; model-generated vocabulary per cell; per-batch
   new-host and first-discoverer accounting; the economic stopping rule with the measured plateau
   as its starting input; free-to-apply read-ordering of the queue.
10. **Harness and gates.** Open-web fixture shape; gold sets; tallies; the 100-host classifier
   check; page-level yield on 50 hosts; three-run variance. Then the per-corridor sweep command.
11. **Deferred.** Perplexity Search API probe; Exa Websets and `/agent/runs` criteria-verified
    enumeration, both untested; Diffbot's free tier against the two hypotheses in
    `research/2026-09-17-diffbot-perplexity-recon.md`; Firecrawl `/search` once its terms are
    confirmed.

Increments 1–5 are discovery and can land in order. **6 and 7 are the ones that decide whether a
student sees anything**: without 6 the catalog holds hosts and kinds but no showable card, and
without 7 no gap can be stated. 8 needs the optimizer, which is designed and unbuilt
(`2026-08-27-risk-aware-portfolio-design.md`), so its first half — profile → cell and the
no-profile test — can land early and its second half waits.

## 11. Testing

Adapters against recorded responses (no network in the default run); protocol conformance (only
`url` read); denylist and steering tables; registrable-domain edge cases (`edu.tr`, `ac.uk`,
`gov.az`, `co.uk`, IDNs); dedupe across providers; planner output contains no profile field;
classifier schema `extra="forbid"` and token cap; `Organisation` as a shared table under
`rls_enforced_orm` (every tenant reads, only `catalog_ingestion` writes); `live`-marked tests: one
call per provider and per registry, asserting the shape and one known host.

## 12. Alternatives considered

- **Fan out to every index on every query.** What the probe did: 4× cost, no denominator, and
  most of the union is hosts a register already holds.
- **Registries plus Tavily only.** Cheapest and terms-trivial, but Tavily alone misses two-thirds of
  hosts and is weakest exactly on the home-country side; with permission in hand there is no
  reason to accept that.
- **Exa alone as "the best index".** Brave still returned 84 hosts Exa did not; single-index blind
  spots are measured, not hypothetical.
- **Aggregators as sources.** Their own terms, and the repo's rule that a catalogue page can never
  support a claim; hub harvesting of *official* directory pages covers the legitimate half of what
  they offer.
- **Provenance laundering** (barred index picks the host, clean source re-derives the URL). Moot
  now for Exa and Brave; named so it is never adopted for a provider that has not said yes.

## 13. Open items

- **`EntityExpansionSource.search` is still typed `SearchSource`.** §4.6 calls for the protocol,
  and the retype is blocked on `find` calling `dataclasses.replace` with three `SearchSource`
  fields the protocol does not carry (`name`, `source_type`, `evidence_strength`). Doing it needs
  `find` restructured to compose a `SearchRequest`, which belongs with the sweep harness that will
  be its first provider-passing caller. Left typed and commented rather than adapted around, because
  a shim that makes a protocol look like a concrete class is how the seam stops meaning anything.
- **The free-to-apply policy makes document generation a batch job, and every limit on that path
  is shaped for an interactive one.** §2 includes every zero-fee option for every student who has
  not excluded its country, so a student's application count is bounded by the catalog, not by
  their budget — forty free options is an ordinary outcome, not a pathological one. The document
  engine's ceilings were all set against a person clicking a button:
  `generation._CV_GENERATION_RATE_LIMIT` is 10 an hour ("generous for a real student"),
  `ingestion._INGESTION_RATE_LIMIT` is 5 an hour, `tailoring._RATE_LIMIT` is 20.
  **Nothing is broken today** — `document_worker.py:161` calls `generate_cv(student=..., programme=None)`,
  so production makes exactly one generic CV per request and `tailor_skills` has no production
  caller at all. The decision falls due the moment the pack drives generation.

  **The decision is not what number to raise the limit to.** It is whether a document is
  per-programme at all. Per-programme tailoring over forty free options is forty model calls and
  forty drafts a human must approve (`ConsentEvent`, §38) — the approval queue breaks before the
  rate limiter does. The cheaper shape is already half-built: render dispatches on **format
  variant** (standard / Europass / funder template), most free options state no CV requirement, and
  `read_and_derive` records which ones do. Generate per variant; tailor only where the programme's
  own page asked for something. Then the limits never bind.

  **Ceiling set, owner 2026-09-18 — and it needs no new limit, because rendering is free.**
  Generation produces one `CVContent`; `render.py` then dispatches it onto a variant
  (`STANDARD`, `EUROPASS`, `GERMAN_TABULAR`, `FUNDER_TEMPLATE`, `FIELD_MAPPED`) with **no model
  call**. Forty programmes wanting five different formats is therefore *one* generation and forty
  renders, not forty generations. Only tailoring makes a generation per-programme, and it is
  worth spending only where the programme's own page actually stated a CV requirement — which
  `read_and_derive` already records, and which most free-to-apply options do not.

  So the realistic ceiling per pack refresh is **one base CV plus at most five tailored
  regenerations**, comfortably under the existing `_CV_GENERATION_RATE_LIMIT` of 10 an hour, which
  therefore stays unchanged. Should the worker ever drive generation in bulk, the counter to
  replace is the *hourly interactive* one — in front of a queue an hourly counter is a schedule,
  not a guard — with a per-student daily budget.

  **`_INGESTION_RATE_LIMIT` 5 → 15, done** (`apps/documents/ingestion.py`): the upload ceiling was
  set against abuse and never against onboarding, where CV, transcript, two certificates and a
  passport is five documents before the student has done anything unusual.


- ~~Name-to-site resolution~~ **closed 2026-09-18: v4 measured German 20/0/5, Turkish 12/1/12 and
  adopted** (§4.13a). Still owed for it: an Azerbaijani 25 (Latin and Cyrillic names, "Fondu") before
  the AZ corridor is swept — Wikidata holds only ~16 AZ foundations with a website, so the resolver
  carries nearly the whole load there; the retry queue for unreachable hosts (~10%); and the VGM
  register's terms and read tool (§4.2 still says Scrapling; the 2026-09-15 fetch-path decision
  replaced it — use the vendor extract path).
- **Perplexity**: unmeasured (no credit); its distinctive sweep overlaps Exa Agent; Sonar sunsets
  27 Sept 2026. Probe its Search API (~$5) as a possible fifth index after §7's tallies show where
  coverage is thin. Never an engine seam.
- **Firecrawl's upstream index** is unnamed; if Google-derived, `/search` fails the repo's rule on
  that alone. Confirmation requested.
- **Exa Websets** pricing and whether its criteria evaluations beat describe-the-entity `/search`
  for funders — an owner-launched probe.
- **Diffbot `similarTo`**: feeding a known funder and asking the graph for similar organisations is
  the one operation neither a search index nor a register offers. Untested; ~250 entities of the
  monthly free allowance remain.
- ~~Page-level yield unmeasured~~ **measured 2026-09-18: 2 served in 58 funder hosts, neither a funder** (§4.13c).
  The reader has no kind for a funder's award. Funder-side kinds first, then the same 58 hosts again.
- ~~Mobility money inside the degree~~ **closed 2026-09-17: out.** Admission awards only — money a
  student secures by applying to a master's. Sub-project 5's exchange-award exclusion stands.
- **A second saturation cell**: the plateau was measured on one dense cell in one country. A thin
  cell — Azerbaijani outbound schemes — may have a different shape, and the stopping rule's
  threshold rests on both.
- ~~Re-run the German cell at full provider configuration~~ **done 2026-09-17**: the ablation found
  depth is the only large win and the filters are losses, so the plateau's floor rises with depth
  alone. Re-running the 99-query sweep at Brave 10 pages and Exa 100 results is still owed, to put
  a number on the corrected plateau.
- **Regional engines, settled 2026-09-17 in three parts** (`research/2026-09-17-search-capability-ablation.md`
  §§6–7). A regional engine pays where the national web is **large and partly out of the global
  indexes' reach** — Baidu added 7 Chinese institutions from three searches at **76% precision**, the
  highest measured here, and Naver added 5 Korean funders including two foundations. It pays nothing
  where the web is merely **small** (Yandex: 0 in Azerbaijan), and nothing where the web is large and
  openly indexed (Google via SerpApi: +2 in China, +1 in Korea, against Brave and Exa's 130 and 69).
  **Adopt Baidu and Naver via SerpApi — owner decision 2026-09-17** (we train no competing search
  model). One factual note for §8's terms record: SerpApi's §13 shield covers *collection* and
  explicitly not *use*, and applies only to recurring plans **other than Free, Starter and
  Developer** — so on today's Free plan there is no shield, and a recurring paid plan is what
  activates it. **Skip Seznam and Coc Coc**: both are the "no marginal value" case, Czechia because
  its web is small and Vietnam because its web is large and openly indexed — measured, the global
  engines returned **70 Vietnamese funders** on Vietnamese queries and Google added one
  (`research/2026-09-17-search-capability-ablation.md` §8).
- ~~A regional index where the global ones are thin~~ **closed 2026-09-17: refuted for thin webs.** Yandex via
  SerpApi on Azerbaijani-language queries added **zero** Azerbaijani funders over the four-engine
  baseline, and Google added one. A deeper regional index is not more of what we seek; Azerbaijan's
  constraint is the size of its web. There is no Yandex-equivalent for South Asia or Latin America
  either — Google holds 95–98% there and is the local index — and the measurement says a marginal
  engine is worth ~0–1 organisations where the underlying web is small. **The thin-index route is
  for small-web countries, not for large developing markets**: Indonesia returned 55 local funders
  and India carries 17,254 HEIs in Wikidata. Evidence: `research/2026-09-17-search-capability-ablation.md` §6.
- **Student effort as a portfolio term**: deliberately not added. If displayed effort plus the
  student's own exclusions prove insufficient — a pack nobody executes — it becomes an amendment to
  `2026-08-27-risk-aware-portfolio-design.md`, not to this design.
- **Azerbaijani-language queries**: none run yet; the local-language leg is measured, not assumed.
- **`Organisation` vs `Institution`**: kept separate here; folding the catalog HEI row into the
  register is a later decision once both exist.
- **Goggle hosting**: Brave fetches a Goggle from a public URL, which the repository does not
  provide by itself. Increment 2 either serves the committed file from a public path we control or
  uses Brave's inline rule sets (three per query, no hosting, and the shape that returned HTTP 422
  once in the probe on a long rule set). The choice and the URL are recorded when it lands.
- **Vendor-per-axis proposal reviewed 2026-09-18** (`research/2026-09-18-vendor-per-axis-proposal-review.md`):
  changes nothing in the architecture. Two knobs owed a measurement before adoption — Exa `*.domain`
  for the per-institution pass, Brave boolean phrasing with a different-script check — and two dropped
  with reasons (Tavily `prefer` mode; a fixed Brave-first-on-government rule, whose general form is
  the per-cell tally, which must then be keyed by family). **Baidu and Naver were in the roster and
  not in the build plan**; the register plan's Task 11 adds them via SerpApi's free tier by owner
  decision, with the no-shield position stated in §4.13 and §8. Open: Naver's own API terms (the
  host refused the fetch); the Production tier if exposure grows.
- **External review (Gemini Pro, 2026-09-18) — what was taken, what was already so, what was
  declined**; detail in `research/2026-09-18-vendor-per-axis-proposal-review.md` § External review.
  Taken: `timing` and `cycle` on the card (§4.10, increment 6). Owed measurements: **(a)** the
  recall the agreement rule spends — the 58-host re-run now reports `noise` (one reading alone) and
  disputed-on-`offered` counts, with 30 noise lines hand-checked; if a material share are real
  awards, the fix is a *targeted binary re-ask* of the other model family on that line before it is
  discarded — never a single-extractor design, because verification catches fabrication and not
  omission, and the measured coverage gain came from the union of three reads; **(b)** on the 45
  unagreed awards of §4.13c, one reading by a stronger model (`claude-opus-5`) on the disputed
  fields only — how many resolve, at what cost — *before* anyone proposes amending the 3.3 decision
  (third reading on `offered` only); **(c)** PI- and lab-level postings ("funding for two master's
  students this autumn") as a page class: on ten registered universities, how many the
  per-institution Exa pass finds versus a `startPublishedDate` recency query, and whether EURAXESS
  lists any at master's level (its terms unread). Such postings expire — the card needs a short
  shelf life, not the 60-day deadline rule. **(d)** `harvest.content_digest` prefers `<main>`
  unconditionally while `readable_text` learned to distrust a shell `<main>` (`_MAIN_SHARE`, the
  15% Türkiye Bursları case); on such a page the digest covers the shell and a real change outside
  it goes unread — align the two. **Owner decisions, same evening:** **(e)** `robots.txt` and
  text-and-data-mining reservations are **not checked by us** — the vendor that fetches (Firecrawl)
  carries that question, and every question about it goes to the vendor. The concern was raised
  (DSM Directive Art. 4; a Cloudflare challenge as a signal) and the owner decided. One fact stands
  beside the decision so it is not misread: the position is fully true only for pages the vendor
  fetches from *its* addresses — a page our own egress or our own browser fetches is fetched by us —
  which is one more reason for a single vendor fetch path (below). **(f)** Aggregators: **fetch
  everything.** Commercial aggregator pages are read for organisation *names only* through the
  pointer→lead mechanism (funder spec §3.2) and the hub-harvesting extractor (§4.5); nothing from
  them is ever provenance, and the search-time denylist stays for that reason. Still owed: the
  measurement — names from one aggregator page that resolve to organisations the register lacks. Already so, recorded so it is not re-raised:
  the change detector hashes readable content with boilerplate stripped, not bytes
  (`harvest.content_digest`, plus Firecrawl `changeTracking`); the human queue never blocks the
  pipeline (unserved is a state, items expire, dedupe is cross-tenant); deadline states and the
  60-day re-read exist (§4.10, §6); ROR/Wikidata ids are the join (`OrganisationIdentifier`).
