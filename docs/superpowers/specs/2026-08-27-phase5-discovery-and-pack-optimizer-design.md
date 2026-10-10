# Phase 5 — Automated Discovery Engine + Competitiveness/Pack Optimizer (Design)

**Status:** design approved in conversation 2026-08-26/27. Discovery is built from this document.
The competitiveness/odds calculation and the past-winner analysis are designed here and **built
last** — see the build order in §1.

**Requirements covered:** `phased requirements.md` §7.1–§7.7 (discovery), P1-3, P1-4, P1-6, P1-7
(pack), §3.3 deterministic-scoring boundary, §3.4 egress conduct, §6.1 personal data, §9 no outcome
promises.

**Why one document for two subsystems.** Discovery and pack optimization are separate subsystems
sharing only the catalog. They are designed together because the optimizer needs facts
(`awards_per_cycle`, `applicants_per_cycle`, published grade rules) that only exist if *discovery
extracts them at fetch time*. Designing discovery alone would ship an extraction schema missing the
optimizer's inputs and force a re-fetch of every page. The interface between them is §4.

---

## 1. Scope

**In scope, built now — Subsystem A (Discovery).** `DiscoveryQuery` → lead sources → dedupe →
existing fetch/snapshot/extract chain → catalog rows.

**Designed now, BUILT LAST — Subsystem B (Competitiveness + pack).** `CompetitivenessFacts`,
per-target grade-equivalence rules, deterministic tier resolution, and budget-capped portfolio
allocation. **The entire odds/competitiveness calculation is postponed to the final increment by
user decision 2026-08-27.** It is designed here only so discovery extracts the right fields (§4);
no part of it is implemented until every earlier increment is done.

**Postponed to the same final increment — data about past winners.** Awardee-profile tracing,
LinkedIn or any social profile retrieval, OpenAlex/ORCID trajectory reconstruction, and
consultant-recorded readings of individual past awardees. §4 keeps `CompetitivenessFacts` open for
it (a later `awardee_profile_tier` field) so adding it does not reopen this design.

### Build order

| # | Increment | Status |
|---|---|---|
| 1 | Discovery engine (§2) — seed adapters, entity expansion, `CatalogWriter`, `ExtractedClaims` schema bump | **build now** |
| 2 | Discovery wiring — `dispatch.py`/SQS, views, recommendation-run integration | later |
| 3 | Competitiveness + pack optimizer (§3) — odds, tiers, grade rules, reach allocation | **last** |
| 4 | Past-winner analysis — folds into `CompetitivenessFacts.awardee_profile_tier` | **last, with #3** |

Increment 1 must not implement any part of §3 beyond extracting and storing the §4 fields. Those
fields are inert until #3: nothing reads them, nothing scores on them, and no tier is computed.

**Also out of scope.** Wiring discovery to views, SQS or the recommendation run. Discovery ships as
a management command (§2.7). `dispatch.py` integration is a later change and the stage boundaries in
§2.2 are drawn so it needs no rewrite.

**Phase gate lifted by the owner 2026-09-25** (`2026-09-25-tailored-programme-finding-design.md`, T18); the text below is history. **Phase gate, unchanged.** §7 requires the manual consultant procedure to have produced a recorded
Section 3.5 baseline over one admissions cycle before automated discovery serves students. Nothing
here changes that. This subsystem is built and validated in shadow mode (§6) meanwhile.

---

## 2. Subsystem A — Discovery engine

### 2.1 Source survey (evidence, 2026-08-26)

Coverage is severely lopsided, which drives the whole lead-source design. Measured, not assumed:

| Corridor | Best official seed | Access | Tier |
|---|---|---|---|
| Germany | DAAD International Programmes | **Public JSON API**, unauthenticated, faceted, `limit`/`offset`; 1,571 English-taught master's; host serves **no robots.txt** | 1 |
| Germany (funding) | DAAD scholarship database | HTML only; stable `?detail=<numeric id>` records | 2 |
| EU-wide | EACEA Erasmus Mundus catalogue | HTML, Drupal, permissive robots | 2 |
| Korea | Study in Korea | `Allow: /` except `/Sims/`; sitemap published; `.do` list pages | 2 |
| France | Campus France "Taught in English" (~1,600 programmes) | Angular SPA; data endpoint not discoverable from static HTML; needs browser rendering (§7.4 permits) | 3 |
| Japan | JASSO / Study in Japan | No robots.txt, no structured catalogue; school search + a **PDF** list | 4 |
| China | CampusChina | **HTTP 412 to plain requests** — blocked | 4 |
| Pan-EU institutions | DEQAR (accredited institutions/programmes) | **HTTP 403** — free but requires registration | — |

DAAD API endpoint, verified working:
`https://www2.daad.de/deutschland/studienangebote/international-programmes/api/solr/en/search.json?limit=&offset=&degree[]=2`
Returns `courses[]` (id, courseName, academy, city, languages, programmeDuration, tuitionFees,
applicationDeadline, subject, `financialSupport`, `structuredResearch`, link), `numResults`, and a
`filter` facet block.

**Consequence.** Seed adapters cover Germany and Korea cheaply, France at medium cost, and Japan and
China not at all. Search is not "the long tail" as §7.2 assumed — for JP/CN it is the *only* source.

### 2.2 Lead sources

One `LeadSource` protocol, three implementations. The interface is justified by having three real
implementations on day one, not by speculation.

```
LeadSource.find(query: DiscoveryQuery) -> Iterable[ResearchLead]
```

`ResearchLead` already exists (`apps/research/discovery.py`) with `canonical_url`, `source_type`,
`funding_family`, `evidence_strength`, `visibility`, `can_route_research`, `can_support_claim`. It is
reused unchanged.

**(a) `SeedCatalogueSource`** — one adapter per catalogue, each mapping the catalogue's own record
shape to `ResearchLead` plus a provisional `Institution`/`Program` identity. Build order: DAAD
International Programmes (API), Study in Korea, EACEA, DAAD scholarship database. Campus France
deferred behind browser rendering. CampusChina is **not** built — a 412 is a refusal, and §7.4
forbids bypassing it without written approval; it becomes a `ConsultantResearchTask`.

**(b) `SearchSource`** — one provider behind the interface, rate-limited via `apps.ratelimit
.rate_limited()`, returning candidate URLs only. Constrained to an allowlist of official domains at
the query boundary where the provider supports it.

**(c) `EntityExpansionSource`** — see §2.3. This is the hidden-gems finder and the most important of
the three.

**Provider evidence (probe, 2026-08-26, SerpAPI/Google, 15 queries, free tier).** Caveat recorded
honestly: the probe's "official" classifier used a TLD regex that misclassified some aggregators
(`stage-etudiant.fr`), so per-class means are optimistic; rank positions and named hosts are sound.

- Long-tail official (JP/CN/KR/FR): 5/5 queries returned an official source, first hit at **rank 1**
  for all five — including `i.kyoto-u.ac.jp`, `tsinghua.edu.cn`, `english.ucas.ac.cn`.
- Hidden gems: 8/8 queries returned a genuinely official research-ecosystem source —
  `mattertolife.maxplanckschools.org`, `cbs.riken.jp`, `ims.riken.jp`, `ihep.cas.cn`, `anso.org.cn`,
  `helmholtz-hzi.de`, `s.u-tokyo.ac.jp`, `research-in-bavaria.de`.
- Aggregator noise ~1.6–1.9 per 10 results, trivially removed by a domain blocklist.
- The JP/CN seed gap is therefore coverable by general search.

**Provider comparison (docs, 2026-08-26):**

| | Cost/1k | Domain filter | Language filter | Storage terms |
|---|---|---|---|---|
| Exa | $7 | `includeDomains`, **1,200 entries, wildcard subdomains** | none (`userLocation` only) | no anti-storage clause found |
| Perplexity Search | ~$1/1k effective ($5 per request, ≤5 queries/request) | domain + ISO country | country only | structured results, no model answer |
| Tavily | $5–8 | `include_domains` (300) | `language` + strict `filter_by_language` | ToS §6.5 retains Customer *Input* for training; §3.2 bars competing products |
| Brave | $5 | limited | limited | storage needs a rights-granting plan; free tier removed Feb 2026 |
| SerpAPI (Google proxy) | ~$10/1k | via query operators | via query params | probe vehicle only — a key already existed on a free 250/month plan |

SerpAPI was not a candidate; it was the probe vehicle, because a key already existed and Google's
index is the coverage ceiling any provider is measured against. Its per-query cost and its status as
a proxy for another engine's results keep it out of the product path.

**Decision — provider.** Exa is the design's primary: 1,200-entry `includeDomains` with wildcard
subdomains (`*.tu-berlin.de`) enforces "official sources only" *at the search boundary* rather than
by post-filtering, and neural retrieval suits §2.3's entity queries. Perplexity Search is the named
fallback on cost. **Tavily is rejected** — §6.5 lets it retain and train on Customer Input, and
discovery queries derived from a student profile are §6.1 personal data; proving every query string
is profile-free is an ongoing obligation, not a one-time check.

**Decision — no search-level language filter.** §7.2 asks discovery to be constrained to the
student's teaching languages. Page language ≠ teaching language: a German-language `tu-berlin.de`
page routinely describes an English-taught master's, so filtering by page language silently drops
correct programmes. Teaching language is enforced where it already is — `extraction.py`'s
`TeachingLanguageClaim` with a cited excerpt, then `_teaching_language_gate`. Tavily's best feature
is one this product must not use.

**Environment note.** `PERPLEXITY_API_KEY` exists but returns `insufficient_quota`.
`SERPAPI_API_KEY` exists on a free plan (250/month) and funded the probe. Exa needs a new key.

### 2.3 Hidden gems — entity expansion, not query cleverness

The probe's key finding: **every gem that surfaced was an institution- or centre-level page.** The
query aimed at an individual opportunity ("funded master thesis position professor lab stipend
Japan") was the worst result in the set — first official hit at rank 6, Reddit and Facebook above
it. Professor-level funded slots are not published as indexable pages, and no provider will find
them.

This matches P1-3 exactly: those are evidence strength 4, "ecosystem clue requiring deeper
research", which stay internal until upgraded by primary evidence.

So `EntityExpansionSource` works in two steps:

1. **Discover the research organisation**, not the funding — Max Planck, RIKEN, CAS, Helmholtz, CNRS
   and their institutes, doctoral schools and graduate schools. Search is good at this.
2. **Enumerate that organisation's own official pages** via its sitemap and known funding/admissions
   paths, and feed those into the normal chain.

Leads from step 1 that are not yet corroborated enter as `evidence_strength="ECOSYSTEM_CLUE"`, which
`ResearchLead.from_url` already maps to `visibility="INTERNAL"`, `can_support_claim=False`. They are
upgraded only when step 2 produces a primary source.

This makes the gem finder largely provider-independent, which materially weakens the case for paying
for any single provider.

### 2.4 Pipeline

```
DiscoveryQuery
  -> LeadSource.find()            (a) seed  (b) search  (c) entity expansion
  -> canonicalize_url + dedupe    existing discovery.py helpers
  -> fetch_official_source()      existing egress.py — validated, private-net blocked, domain leases
  -> persist_snapshot()           existing snapshot.py — digest + stored bytes
  -> extract_claims()             existing extraction.py — schema-constrained, cited excerpts
  -> CatalogWriter                NEW — the only new stage that touches the DB
```

Every stage is a pure function over a dataclass boundary; only `CatalogWriter` does I/O beyond the
existing egress/storage primitives. Nothing in the Phase 1 chain is modified.

### 2.5 `CatalogWriter` — the one genuinely new component

Upserts `Institution` / `Program` / `FundingOpportunity` (shared platform evidence, §9 — **not**
tenant-scoped) and their `OfficialEvidenceClaim` rows.

**Hard rule — catalogues route, they do not claim.** DAAD, Campus France and EACEA are catalogues.
Under §7.2 an aggregator may route research to an official source but may not support a claim.
Therefore `tuitionFees: "No tuition fees"` from the DAAD API **must not** become an
`EvidenceClaim`. Catalogue records seed `Program`/`Institution` *identity* and yield the official
programme URL; every claim is then extracted from that official page through the normal chain. Taking
the shortcut would reintroduce precisely the aggregator-sourced-claim failure §7.2 exists to prevent
— the same class of error the 2026-08-22 letter research already produced once.

**Dedupe.** URL canonicalization (existing) plus `(institution, normalized programme name, degree
level)` matching. **No pgvector in this increment.** §7.5 says Phase 5 *may* add vector search; it is
not required, and a new Postgres extension for a problem exact matching has not yet failed to solve
is unjustified. Revisit when measured duplicate rates justify it.

**Freshness (§7.1), per claim class:**

| Claim class | Window |
|---|---|
| Institution identity, degree type, programme existence | 365 d |
| Teaching language, duration, programme structure | 180 d |
| Tuition and fees | 90 d |
| Deadlines, application windows, funding amounts | 30 d |

Past its window a cached claim is revalidated or dropped; it never enters recommendation evidence
(§7.1). `is_stale()` and `refresh_snapshot()` already exist and are reused.

### 2.6 Conduct, cost, rate control

- §3.4 egress rules bind unchanged: URL validation, private-network blocking, per-domain leases
  (`DomainLease`), bounded concurrency, backoff. Scale does not relax them.
- Search provider is a §3.4 egress destination. Its results are untrusted data, never evidence, and
  the technique that produced each lead is recorded in snapshot lineage (§7.2, §7.4).
- **Per-tenant and per-user rate limiting via `apps.ratelimit.rate_limited()` lands in the same
  change as the calling path** — CLAUDE.md, non-negotiable. A discovery path without one has no cost
  circuit-breaker.
- Background discovery gets a bounded budget separate from student-triggered research and degrades
  to cached results rather than exceeding it (§7.6).
- Blocked sources (CampusChina's 412, DEQAR's 403, anti-bot refusals) become
  `ConsultantResearchTask` rows. A blocked source is never silently dropped (§7.4).
- No stealth retrieval, no fingerprint evasion, no proxy rotation. §3.4 prohibits it and §7.4 allows
  it only per source class after written security/legal approval that does not exist.

### 2.7 Runnable surface

`manage.py discover --field <f> --country <CC> [--level MASTER] [--languages en,de] [--max-leads N]
[--dry-run]`

Real network, real catalog writes, no views and no queue. This is what makes "does the engine find
good funding in Japan?" answerable this week.

### 2.8 Instrument discovery — a second query mode (added 2026-08-27)

Everything above finds **programmes** and the funding attached to them. It does not find **national
and state scholarship instruments** — DAAD's own schemes, Eiffel, MEXT, GKS, CSC, Chevening,
Commonwealth, Türkiye Bursları, Stipendium Hungaricum, the Heydar Aliyev grant, Erasmus Mundus.
Those are exactly the instruments that make a floor reachable for a mid-grade student
(`2026-08-27-instrument-landscape-synthesis.md`), and without them the portfolio's widening ladder
has nothing to draw on.

**This is a second query mode of the same engine, not a second engine.** The `LeadSource` protocol,
the egress rules, the domain leases, the catalogue hop, the snapshot/extract chain and the
`CatalogWriter` are all unchanged. Two things differ:

| | Programme mode | Instrument mode |
|---|---|---|
| Query key | field + destination + level | **destination country, field-agnostic** |
| Writes | `Institution` + `Program` + claims | `FundingOpportunity` + tracks + `BenefitRule` + claims |
| Matched to a student | at query time, by field | **afterwards, by nationality rule** — an instrument is discovered once and serves everyone it matches |

`DiscoveryQuery` therefore gains a mode. Everything else composes.

**Seed index.** Instruments are enumerated by official index portals, not found one page at a time.
The 2026-08-27 sweep recorded which pages actually enumerate:

| Country / body | Index portal |
|---|---|
| Germany | `funding-guide.de` / the DAAD scholarship database (stable `?detail=` URLs) |
| France | `campusfrance.org` scholarship directory |
| Japan | `studyinjapan.go.jp` scholarships section |
| South Korea | `studyinkorea.go.kr` GKS notice board, `niied.go.kr` |
| China | `campuschina.org` |
| UK | `chevening.org`, `cscuk.fcdo.gov.uk` |
| Turkey | `turkiyeburslari.gov.tr`, `ytb.gov.tr` |
| Hungary | `stipendiumhungaricum.hu` |
| Azerbaijan | `studyinazerbaijan.edu.az`, `edu.gov.az` |
| Georgia | `mes.gov.ge`, `iec.gov.ge` — no open inbound scheme; crawl universities instead |
| Russia | `education-in-russia.com` plus embassy pages |
| EU | the Erasmus Mundus catalogue on `erasmus-plus.ec.europa.eu` / `eacea.ec.europa.eu` |

The EACEA catalogue adapter already exists, and the DAAD scholarship database is already on the
seed build order — so two of the twelve are in hand.

**Coverage, not relevance.** Instruments are swept per destination country on a schedule, not per
student query. A student's accessible set is then computed from the stored nationality rules.

**Structural cases the schema must represent**, all found in the sweep: a country with no open
inbound scheme (Georgia); a scheme with no central calendar, administered by overseas offices
(Russia, and the decentralised deadlines of DAAD, CSC, MEXT and Erasmus Mundus); a scheme with no
applicant-facing portal at all (Eiffel); four-digit agency codes linking university, track and
central record (CSC); and a per-nationality cap tied to the compatriot applicant pool (Erasmus
Mundus's 10% rule).

**Build order.** Instrument mode is a **separate increment**, after the programme increment ships —
folding it into a plan that has already been written and independently reviewed would invalidate
that review and mix two testable deliverables. The one part that cannot wait is the **extraction
contract**: the track structure, nationality-eligibility rule, per-nationality quota and
`DECENTRALISED` date marker must enter the schema bump alongside the other fields, because adding
them after the catalog is populated means re-fetching every page.

---

## 3. Subsystem B — Competitiveness and pack optimization (design only, BUILT LAST)

> Nothing in this section is implemented in the discovery increment. It is written now solely to
> pin the extraction contract in §4. Postponed to the final increment by user decision 2026-08-27,
> together with the past-winner analysis.

### 3.1 The gap this closes

Nothing today models a student's realistic chance. `CandidateFacts` carries
`confirmed_eligibility_failure` (binary, *formal* eligibility) and `evidence_confidence` (quality of
evidence, not odds). So an 80-GPA student against a highly selective excellence scholarship passes
all ten hard gates, scores well on affordability, and gets recommended — consuming a ~150 CHF
application fee on a near-lottery. That is the failure this subsystem prevents.

Already built and reused unchanged: `funding_dependency: MANDATORY|IMPORTANT|OPTIONAL`,
`strategy: BALANCED|FUNDING_FIRST`, `application_budget: Money` (`apps/accounts/schemas.py:112`),
and `_mandatory_funding_route_gate` (`apps/funding/evaluation.py:245`).

### 3.2 `CompetitivenessFacts`

Extracted at discovery time (§4), resolved deterministically.

```
awards_per_cycle:        int | None          # cited
applicants_per_cycle:    int | None          # cited
published_minimum_grade: GradeThreshold|None # cited, in the TARGET's own scale
selectivity_signals:     tuple[CitedExcerpt, ...]
consultant_tier:         Tier | None         # human fallback
# reserved, deferred: awardee_profile_tier
```

**The model's job stops at extraction.** §3.3 (2026-08-14) makes the model a parser that "supplies
anchored qualitative judgements with cited excerpts" and computes no eligibility, weights,
thresholds or ordering. So:

- **Allowed:** pull published numbers; find and *quote* a selectivity sentence ("awarded to
  exceptional candidates ranking at the top of their cohort") as a cited excerpt.
- **Forbidden:** deciding what tier that implies, and emitting any probability. An LLM odds estimate
  is uncalibrated, unfalsifiable, varies per run and cannot be audited.

Deterministic `competitiveness_tier()` resolves in priority order: hard numbers → published minimum
grade → cited signals → consultant tier → `UNKNOWN`. `evaluation.py` stays what its docstring claims:
pure Decimal logic, no I/O.

**Base rate ≠ personal probability.** 200 awards against 8,000 applicants is a base rate. Presenting
it as the student's odds is wrong and violates §9's prohibition on promising outcomes. The product
shows tier + base rate + reason, **never a personalised percentage**. This also sidesteps calibration
entirely, for which there is no data and will not be for years.

### 3.3 Grade equivalence — per target, never a universal formula

**Decision (user, 2026-08-27): use each target's own stated conversion rule. Do not build the
Bavarian formula as platform-wide machinery.**

Reasoning: the modified Bavarian formula converts to the *German* scale, which is meaningful only
when the target is German and a category error otherwise — an Azerbaijani 80 becomes a German 2.22
that nobody in Zurich or Kyoto will use. What decides the outcome is the target's published rule. And
P1-4 requires every material claim to trace to an official source; a platform-invented universal
formula is exactly the unsourced inference the requirements forbid elsewhere.

So a grade-equivalence rule is a **per-target extracted fact with a citation**, structurally
identical to `BenefitRule` (`apps/funding/models.py:526`): `rule_text`, a scope
(GLOBAL/COUNTRY/PROGRAM), and an M2M to `OfficialEvidenceClaim`. Reuse that shape.

- **Bavarian formula's place:** one country's published rule, for German targets, cited to the KMK —
  it genuinely *is* the stated rule there (uni-assist and nearly every public German university).
  `1 + 3 × (Nmax − Nd) / (Nmax − Nmin)`, where `Nmin` is the **minimum passing** grade, not the
  bottom of the scale. Most common implementation error.
- **Preferred over any formula** where available: class rank / percentile from the transcript, or an
  institution's published ECTS grading table (the 2015 ECTS Users' Guide replaced the old A–E
  percentile bands with actual per-cohort distributions).
- **No stated rule → `NOT_COMPARABLE`**, falling through to consultant tier or `UNKNOWN`. Never
  fabricate a conversion. Same discipline as P1-6 keeping ambiguous opportunities internal.
- **Not built:** institutional prestige weighting. Committees do it informally, but it is unciteable
  by construction and encoding "your university isn't good enough" is a fairness and reputational
  problem the product does not need.

**Schema change required.** `AcademicRecord` needs `min_pass` and `max_achievable` alongside the
existing free-text `grading_scale` — most stated rules need the source scale to apply. Comparison is
**per candidate**, not one band stored at intake.

### 3.4 Portfolio allocation under budget

**Decision: cap budget share, disclose odds.** The application budget is treated as a portfolio, not
a queue.

- **Rule:** at most `floor(paid_slots / 3)` slots, and never fewer than 1 where any reach candidate
  qualifies, may go to `REACH` candidates; the remainder must go to realistically-attainable ones.
  A student affording 3 paid applications gets 1 reach; 6 gets 2. Stated as a rule rather than a
  range so the allocation is testable and not a per-run judgement.
- Every reach is labelled with why it is a reach, per P1-7's requirement to disclose material
  weaknesses.
- Preserves upside — people do win these — while making it impossible to spend the whole budget on
  lotteries.
- Rejected alternatives: *rank lower only* (a fully-funded long shot still outranks realistic options
  under `FUNDING_FIRST` — the exact failure); *hard-gate below a threshold* (excludes real winners,
  and makes the platform rather than the student the one who decided not to try).
- `UNKNOWN` competitiveness is not treated as `REACH`; it is disclosed as unknown. Absence of
  published data is not evidence of selectivity.

Interaction with existing rules: hard gates and `FUNDING_FIRST` pool membership (P1-7) are unchanged.
Allocation applies to the *paid* applications ordering — "paid applications in priority order until
reaching the student's approved budget" — which is where fees are actually spent. Fee-free fully
funded opportunities under funding-first mode do not consume budget and are unaffected.

---

## 4. The interface between the subsystems

The reason both are designed together. **Discovery must extract these at fetch time or the optimizer
cannot work without a full re-fetch:**

| Field | Source | Consumer |
|---|---|---|
| `awards_per_cycle`, `applicants_per_cycle` | funder pages, **annual reports and selection statistics** | `competitiveness_tier()` |
| `published_minimum_grade` (+ its scale) | funder/programme eligibility pages | grade rule matching |
| `selectivity_signals` (cited excerpts) | eligibility prose | tier fallback |
| grade-equivalence `rule_text` + scope | institution/programme admissions pages | §3.3 |
| `application_fee` amount + currency | programme application pages | budget allocation |

Annual reports are the underused source here: DAAD, Erasmus Mundus and most national programmes
publish applicant and award counts by country and discipline. That is the denominator, it is citable
under P1-4, and it is what makes a tier defensible without touching any individual's data.

`ExtractedClaims` (`apps/research/extraction.py`) gains these fields in the discovery increment, with
`schema_version` bumped. They may be `None`; the optimizer treats absence as `UNKNOWN`, never as a
value.

---

## 5. Constraints honoured

| Constraint | How |
|---|---|
| §3.3 deterministic scoring | Model parses and quotes; all tiers, thresholds and ordering computed in `evaluation.py` |
| §3.4 egress | Existing `egress.py` unchanged; search provider registered as an egress destination |
| §3.4/§7.4 no evasion | CampusChina 412 and DEQAR 403 escalate to consultants; no stealth, no proxies |
| §6.1 personal data | No profiles of non-users processed; awardee analysis deferred entirely (§1) |
| §7.1 freshness | Per-claim-class windows (§2.5); stale claims never reach a pack |
| §7.2 aggregators | Catalogues route, never claim (§2.5); search results are leads only |
| §7.5 storage | No vector DB this increment; exact matching until measured to fail |
| §7.6 cost | `rate_limited()` in the same change; bounded background budget |
| P1-4 official sources | Every claim, including grade rules, traces to a cited official source |
| §9 no outcome promises | Tier + base rate + reason; never a personalised probability |

---

## 6. Validation

**Discovery.** Per-stage unit tests (pure functions, no I/O). One integration test per seed adapter
against a recorded fixture. Freshness-window tests proving a stale claim cannot enter a pack.
Lineage tests proving the producing technique is recorded per lead.

**Shadow mode (§7.7).** Run automated discovery alongside the manual procedure; it does not serve
students until it meets the Section 3.5 precision, recall, official-claim-support and
verified-funded-lift baselines. The manual procedure stays the fallback for any corridor where it
has not.

**Optimizer.** Golden-case tests, starting with the one that motivated it: a mid-GPA student against
a highly selective award must not consume the application budget on it, and the reach cap must hold
under both `BALANCED` and `FUNDING_FIRST`.

**Probe scoring, corrected.** The 2026-08-26 probe's TLD-regex classifier over-counted official
sources. Any repeat scores against an explicit allowlist of known-official hosts plus a manual read
of the top 3 — a country TLD says nothing about whether a site is official.

---

## 7. Open items

1. **Terms of use** for each seed catalogue not yet read end-to-end. `robots.txt` was checked for
   every host; §7.4 requires respecting *published access terms* too. Blocking for each seed adapter,
   cheap per source.
2. **Exa API key** not yet provisioned. Given §2.3's finding that gem-finding is largely
   provider-independent, a head-to-head against SerpAPI/Perplexity is lower value than it appeared;
   proceed with the interface and decide on measured cost.
3. **Campus France** SPA data endpoint needs one browser-rendered probe to locate.
4. **DEQAR registration** — free, would supply accredited-institution identity across the EHEA.
5. **Awardee-profile layer and the odds calculation itself** — both postponed to the final
   increment (§1 build order, rows 3 and 4). The awardee layer slots into `CompetitivenessFacts` as
   `awardee_profile_tier` when taken up. Until then no tier is computed anywhere and the §4 fields
   sit unread.
