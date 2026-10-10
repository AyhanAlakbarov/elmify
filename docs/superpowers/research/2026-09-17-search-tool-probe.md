# Search tools for funding discovery — analysed, then probed

**Question.** Which web-search providers help us find funding opportunities we do not already have,
how should each be used, and is combining them worth it? Prompted by a pasted claim that Tavily
"falls to SEO trash", Exa's "dense vector embeddings" find hidden gems, and Perplexity's deep
research is a "multi-hop reasoning agent".

**Method.** Two parts. (1) Each provider's own current documentation and terms were read live on
2026-09-16 (Tavily, Exa, Brave, Firecrawl, Perplexity). (2) On 2026-09-17, 20 queries covering all
nine P1-3 funding families (`phased requirements.md` §P1-3) plus the two later families
(`AFFINITY_OR_DIASPORA`, `PRIVATE_FOUNDATION`) were run against the four providers we hold live keys
for, each in two shapes: **A**, as the product wires search today (plain query, repo aggregator
exclusions); **B**, the way that provider's docs say to use it (Tavily: advanced depth + country
boost + 150-domain aggregator denylist; Exa: describe-the-page phrasing + denylist + `userLocation`;
Brave: inline Goggle discarding aggregators and boosting institutional hosts + `country`; Firecrawl:
`location` + `-site:` exclusions). 160 calls, ~3,000 result URLs, 862 distinct hosts. Every host was
classified once by `OPENAI_EXTRACTION_MODEL` into university / research institute / government
agency / foundation / company / multilateral / aggregator / news / social / other, with a
`funds_students` flag. **ORIGIN** below means a host that itself awards or administers money to
students; **AGGREGATOR** a site listing other people's awards; **NOISE** everything else.

**What this does and does not measure — read before the numbers.** It measures *where a provider's
results point*, at host level. A university host counts as ORIGIN even if the particular page holds
no award; whether a page holds an award is the funding reader's job (`apps/research/funding_judge.py`),
not the search tool's. One run, no repetition — the repo has seen ±2/16 run-to-run variance on
Tavily. Host classes are one model pass, not hand-checked. Perplexity was not run: its key has no
credit (`insufficient_quota`). SerpApi timed out and is Google-derived, which the terms review
already rules out. Nothing here was persisted into the product; the raw result files live in the
session scratchpad and are deliberately **not committed** — for Brave and Exa, a committed list of
their results would itself be the storage their terms forbid. The handful of hostnames named below
are illustrative examples only.

Cost of the probe: ~60 Tavily credits (of 1,000 free/month), ~40 Firecrawl credits (of 1,000 free),
about $0.70 on Exa, $0.20 on Brave, one model pass over 862 hosts.

## 1. The five claims, checked

| claim | verdict |
|---|---|
| Tavily is keyword/SERP-based on Google/Bing | **Unverifiable.** Its terms admit "making queries on third-party public web indexes"; no document names one. |
| Exa is a neural index of curated links | **Refuted.** Exa's own crawl, "1.4 trillion URLs"; `neural`/`keyword` modes no longer exist — routing is internal to `auto`. |
| Exa `findSimilar` is the superpower | **Deprecated.** No reference page, no price; Exa points new list-building at `/agent/runs` and Websets. |
| Tavily supports wildcard TLDs in `include_domains` | **Contradictory docs.** Best-practices shows `*.com`; the Aug-2026 changelog says wildcards are unsupported. |
| Tavily falls to SEO trash | **Refuted for aggregators, true for volume.** Tavily's aggregator share was the *lowest* of the four (8–10%). Its problem is different: fewest results (143 of 400 possible as wired), slowest (4.5–6 s median), fewest unique hosts. |
| Perplexity deep research is a multi-hop agent | **Confirmed by its docs**, not by us: one `sonar-deep-research` request ran 21 searches for $0.82 in Perplexity's own sample. Not run here. |

## 2. Headline numbers

Per run (20 queries each; ORIGIN / AGGREGATOR / NOISE are shares of returned URLs):

| run | URLs | ORIGIN | AGGREGATOR | NOISE | distinct ORIGIN hosts | median ms |
|---|---|---|---|---|---|---|
| Tavily A (as wired) | 143 | 50% | 10% | 40% | 57 | 4,510 |
| Tavily B | 233 | 69% | 8% | 23% | 135 | 5,957 |
| Exa A | 400 | **79%** | 8% | 12% | 169 | 1,255 |
| Exa B | 400 | 76% | 12% | 12% | 158 | 1,230 |
| Brave A | 397 | 49% | **33%** | 18% | 112 | 1,435 |
| Brave B (Goggles) | 374 | 76% | 14% | 9% | 159 | 1,376 |
| Firecrawl A | 400 | 42% | 19% | **39%** | 126 | 1,725 |
| Firecrawl B | 400 | 60% | 15% | 25% | **178** | 2,242 |

Coverage of distinct ORIGIN hosts, both techniques pooled:

| providers | ORIGIN hosts | unique to that provider |
|---|---|---|
| Tavily alone | 165 | 36 |
| Exa alone | 254 | **132** |
| Brave alone | 209 | 84 |
| Firecrawl alone | 213 | 55 |
| Tavily + Firecrawl (terms-clean today) | 260 | — |
| Tavily + Firecrawl + Brave | 375 | — |
| all four | **507** | — |

Three things the table says:

1. **Combining providers is worth it, measured.** Tavily alone reaches 165 funding-relevant hosts;
   all four reach 507 — three times as many. The repo's 2026-08-30 finding that Brave/Exa added
   nothing over Tavily was made on 16 university-root pages with host-scoped queries; it does not
   transfer to open-web opportunity discovery, and this is the measurement that says so.
2. **The technique layer is worth more than the choice of provider** for three of the four. Brave
   +27 points ORIGIN share (Goggles alone took aggregators from 33% to 14%), Tavily +19, Firecrawl
   +18. Exa is already there as wired (A ≈ B). Whatever is built must carry that layer —
   aggregator denylist, geographic boost, institutional-host boost — as vendor-neutral code.
3. **Exa is the strongest single index for this job and the weakest contract.** Most ORIGIN hosts,
   most unique hosts (132 that no other provider returned), best on the home-country side (42
   Azerbaijani and 74 Turkish ORIGIN results against Tavily's 9 and 30). Its terms bar reproducing
   anything "obtained from or through the Services" without written permission.

## 3. Each tool

### Tavily — the one we hold, used at a fraction of its surface

*What it is for.* A search engine built for agents: one call does search, fetch, filter and rank,
returning up to 20 URLs with snippets. Four endpoints: `/search` (open web), `/map` (enumerate a
known host's URLs, 1 credit per 10 pages), `/crawl` (map + extract), `/extract`.

*How its docs say to use it for our job.* Short agent-style queries, one topic per call;
`search_depth=advanced` for long-tail coverage (2 credits); `country` to boost a geography —
Azerbaijan, Türkiye and every priority country are in the enum; `language` /
`filter_by_language` for local-language pages; `include_domains` (300 max) with
`include_domains_mode=boost|filter` — under `filter` a registrable domain matches all its
subdomains, which is the lever for graduate schools on their own hosts; `exclude_domains` (150 max)
for aggregators; `exact_match` for a named scheme. There is **no** `site:` operator. `/map` then
`/extract` is the documented way to go from a known university to its funding pages.

*What the product does.* `apps/research/search.py` sends `query`, `max_results` and 23
`exclude_domains`. No `include_domains`, no depth, no country, no language, and it asks for 25
results against a hard maximum of 20.

*Terms.* The only provider whose restricted object ("Services") is defined to exclude "Output", and
whose Output definition names "links" — so keeping a URL is permitted by structure. Two costs: §9.2
takes a perpetual licence over every query string (queries must stay profile-free, and today's
queries are), and §3.2(xvi) plus §6.6 restrict automated decisions affecting individuals — an open
legal question already recorded in `CLAUDE.md`.

*Price.* 1,000 free credits/month; $0.008/credit pay-as-you-go; basic 1 credit, advanced 2.
Dev keys 100 requests/minute.

*What the probe showed.* As wired: half of what comes back is ORIGIN, but it returned only 143 URLs
where others returned 400, took 4.5 s a call, and found 4 of the 60 known hosts. With the
documented technique: 69% ORIGIN, 135 hosts, 13 known — but 6 s a call. Lowest aggregator leak of
the four in both shapes. Its noise is not SEO farms; it is off-topic officialdom (US city
governments, a hospital foundation) that a `country` boost did not suppress. It uniquely surfaced a
few Turkish foundations (`kumevakfi.org`, `abdiibrahimvakfi.org`) and `jeanmonnet.org.tr`.

### Exa — the strongest index, the hardest contract

*What it is for.* A programmatic web index (1.4T URLs) for agents: natural-language query in,
ranked URLs plus optional page text out. Three instruments: `/search` (with `category: "company"`
for organisation homepages, `includeDomains` with subdomain wildcards, `includeText`, date filters,
`userLocation`, up to 100 results); `/contents` with `subpages` to crawl a known institution;
Websets / `/agent/runs` for criteria-verified entity enumeration ("every foundation funding Turkish
master's students abroad", each candidate returned with `satisfied: yes/no/unclear` per criterion).

*How its docs say to use it.* Describe the page you want, not the keywords: "An official page from
a university, ministry or foundation describing this funding for international master's students:
…". The old "Here is a …:" link-prediction phrasing and `use_autoprompt` are gone from the docs.

*Terms.* No defined term for API results at all, and §4.2(a) bars reproducing "any information
contained on, or obtained from or through, the Services" absent written permission. The repo's
reading: even a bare URL may not be kept. No automated-decision clause.

*Price.* $7 per 1,000 requests up to 10 results, $1 per 1,000 extra results; deep modes from
$12/1k; Websets on a separate plan.

*What the probe showed.* 79% ORIGIN as wired — the technique layer bought it nothing, which is the
"dense embeddings" claim landing where it should: the index already prefers the institution's own
page. 254 ORIGIN hosts, 132 unique, 22 of 60 known hosts. On the home-country side it alone
returned `bolashak.gov.kz`, `dp.edu.az`, `addf.gov.az`, `diaspor.gov.az`, `balassieducation.hu` —
government scholarship bodies in exactly the class the landscape research says has no index.

### Brave — an independent index whose raw output is the aggregator problem, and whose Goggles fix it

*What it is for.* Brave's own 30-billion-page index as ranked URLs, plus verticals (`discussions`,
`faq`, `news`) and an LLM-context endpoint. The distinctive instrument is **Goggles**: a plain-text
re-ranking language — `$discard,site=mastersportal.com`, `.edu.tr$boost=3`,
`/scholarship$boost=2` — passed inline or hosted. `site:` and `intitle:` work in the query;
`country` covers TR, IN, ID but not AZ, PK, VN, GE, KZ, UZ.

*How its docs say to use it.* Scope with `site:` to enumerate a university's subdomains; target a
market with `country`/`search_lang`; page 10 × 20 deep; discard the aggregator layer with a Goggle
and boost institutional host patterns.

*Terms.* "Search Results" means "any outputs from calls made to the API"; the customer may not
"store, cache, or create a database of Search Results, in whole or in part" beyond transient
operation. Storage rights exist only through an Enterprise Order Form. No automated-decision clause.

*Price.* $5 per 1,000 requests, $5 free credit/month, card required.

*What the probe showed.* As wired, a third of results were aggregators — `mastersportal.com` 19
times, `scholars4dev.com` 9 — the SEO-trash problem in the pasted text is Brave's, not Tavily's.
With one inline Goggle: aggregators 14%, ORIGIN 76%, +47 hosts, and 84 hosts no other provider
returned. One of 20 Goggle queries failed with HTTP 422 (a long rule set on a long query; hosting
the Goggle would remove that). Uniquely surfaced a run of Turkish foundations (`vkv.org.tr`,
`mev.org.tr`, `anadoluvakfi.org.tr`, `insanvakfi.org.tr`) and `pncu.gov.pk`, `mea.gov.in`.

### Firecrawl — a scraper with a search endpoint, and the most hosts in a single run

*What it is for.* "Convert any website into LLM-friendly data": `/search` (web/news/images, with
`location`, a `pdf` category, and optional inline scraping), `/map` (up to 100,000 URLs from a
root, subdomains included, 1 credit per call), `/crawl`, `/extract` (a JSON schema across URLs),
and `/agent` (search + navigate with a schema, research preview).

*How its docs say to use it.* Search then scrape as two steps; `location` for a market; the `pdf`
category for decrees and calls; `/map` then `/crawl allowSubdomains` to enumerate an institution;
`/extract` over a ministry page to pull a named list of funders.

*Terms.* No definitions section; silent on output retention; no automated-decision clause. Silence
is not permission, but it is not Brave's or Exa's prohibition either.

*Price.* Credits shared across endpoints; 1,000 free; search 1 credit per 10 results (v2 pricing
page), scrape/crawl 1 per page.

*What the probe showed.* As wired it is the noisiest: 39% NOISE, because its search returns social
media (`facebook.com` 32, `youtube.com` 22, `instagram.com` 20). With `location` and `-site:`
exclusions: 60% ORIGIN and **178** distinct hosts — the most of any single run — including the
Max Planck institutes (`mpic.de`, `mpie.de`, `mpipriv.de`), `cyber-valley.de`, `hertie-school.org`,
and Turkish foundations `darussafaka.org`, `tyev.org`.

### Perplexity — not run; what its docs say

Two products under one key. The **Search API** (`POST /search`) is ranked results with no model in
the loop — up to 5 queries per request, `country`, `search_language_filter`, a 20-entry domain
allow/deny list where a root domain matches all subdomains. **Sonar** wraps the same search in a
model answer; `sonar-deep-research` self-plans a sweep (Perplexity's sample: 21 searches, 194k
reasoning tokens, $0.82 per request) with an async endpoint. Perplexity's own rule: hard
constraints in parameters, not prose, and never read URLs out of the JSON answer — take them from
`search_results`. Sonar chat completions sunset **27 September 2026** in favour of the Agent API.

*Terms.* The Search API Addendum withdraws Output ownership and lets Perplexity retain queries and
results; the AUP bars high-risk automated decisions and adds a blanket EU-AI-Act clause; queries
may not contain personal data. *Price.* Prepaid credits, no free tier; the repo's key is empty.

*Where it would fit.* Not as an engine seam. As an owner-launched enumeration sweep — "every state
scholarship body in Kazakhstan" — whose report a human reads and whose URLs the pipeline then
fetches from origin. The 2026-09-13 design already schedules two such runs.

### The free registries — not search engines, and terms-clean

Measured live 2026-09-16, one call each. These enumerate organisations directly; the engine then
fetches each one's own site. **Wikidata** (CC0, SPARQL, class × country × official website P856):
253 Turkish universities, 241 with a website; 61 Azerbaijani universities, 76 government agencies,
36 research institutes — and funders no search query would frame (Heydar Aliyev Foundation, the
diaspora support fund, the Ministry of Youth and Sports). **DEQAR** (PDDL, accredited EHEA HEIs
with `website_link`): TR 234, KZ 170, GE 83, AM 73, AZ 13 — the cleanest list of private and
foundation universities ROR lacks. **ROR** (CC0): the baseline; 52 AZ education records, 153 TR
funder-typed. **crt.sh** (certificate transparency, no licence published): `%.metu.edu.tr` →
235 distinct hostnames (`ceng.`, `ims.`, `ncc.`, `apply.ncc.`) — the most complete free list of a
university's sub-units, returned as hostnames that still need a fetch and a classifier. **Common
Crawl CDX**: 36 METU hosts in the first page, heavily rate-limited. **Türkiye's VGM foundation
register** exposes a "Burs Veren Vakıflar" (scholarship-giving foundations) filter — as a web form,
no API — and is almost certainly the single largest list of the *vakıf* funders that §5 shows the
search providers splitting between them. Rate ceilings, not terms, are the constraint (Wikidata
60 s per 60 s, ROR 2,000 per 5 min, Common Crawl 24-hour IP blocks).

## 4. By funding family

ORIGIN share, technique A | B:

| family | Tavily | Exa | Brave | Firecrawl |
|---|---|---|---|---|
| Government scholarship | 70% \| 79% | 80% \| 66% | 44% \| 89% | 42% \| 54% |
| Multilateral (Erasmus Mundus) | 0% \| 50% | 35% \| 45% | 25% \| 20% | 40% \| 30% |
| Industrial sponsorship | 43% \| 54% | 25% \| 50% | 38% \| 70% | 25% \| 42% |
| University-wide | 29% \| 76% | 90% \| 90% | 48% \| 82% | 35% \| 57% |
| Department / programme | 40% \| 57% | 92% \| 82% | 29% \| 59% | 32% \| 57% |
| Tuition waiver | 41% \| 79% | 88% \| 82% | 57% \| 90% | 35% \| 80% |
| Stipend / assistantship | 90% \| 70% | 95% \| 95% | 74% \| 82% | 60% \| 65% |
| Relocation, housing, travel | 40% \| 59% | 80% \| 85% | 65% \| 85% | 45% \| 80% |
| Research-ecosystem pathway | 90% \| 0% | 95% \| 90% | 90% \| 90% | 60% \| 75% |
| Affinity / diaspora | 0% \| 69% | 85% \| 75% | 40% \| 70% | 50% \| 60% |
| Private foundation | 53% \| 72% | 92% \| 82% | 50% \| 78% | 55% \| 68% |

Two rows to read: **Multilateral** is weak everywhere, and should be — Erasmus Mundus is not a
search problem; the EACEA project API returns all 415 EMJM projects in one POST
(`apps/research/seeds.py:107-123`). **Research-ecosystem pathway** collapses to 0% on Tavily B,
where the `country=germany` boost pulled results away from the Max Planck hosts that Tavily A
found at 90% — a boost is not a filter, and on a query already anchored to an institution it can
hurt.

## 5. The home-country side — where the hidden gems actually were

Six of the 20 queries asked from the student's side: Azerbaijani or Turkish state programmes,
BP/SOCAR sponsorship, diaspora funds, Turkish foundations (*vakıf*). All four providers found the
core set — `studyinazerbaijan.edu.az`, `edu.gov.az`, `meb.gov.tr`, `tubitak.gov.tr`, `ytb.gov.tr`,
`tev.org.tr`, `vgm.gov.tr`. Beyond it, the finds were **split**: no provider returned more than a
third of the Turkish private foundations the four collectively surfaced, and the Azerbaijani
government bodies came almost entirely from one. This is the concrete shape of "combining brings
value": the three families the landscape research says have no index anywhere (home-country
outbound, foundations, employers) are exactly where the providers' indexes overlap least.

## 6. What this means for the design

- **Search finds hosts; the reader finds awards.** The pipeline already has this shape —
  `EntityExpansionSource` takes an organisation host and walks its own pages — and the probe
  confirms it is the right one: ORIGIN share is a host-level property, and a page-level award is
  the funding judge's decision. A second or third index plugs in as another organisation supplier,
  not as a source of facts.
- **Build the technique layer once, vendor-neutral.** Aggregator denylist (the repo's 23 plus the
  ~80 used here), geographic boost, institutional-host boost, and deep pagination. It is worth
  +18 to +27 points on three providers and costs nothing per call.
- **Terms decide the roster, and routing does not dissolve them.** Read against each contract's
  definitions, for an engine that holds the provider response in memory, takes one URL, fetches
  the origin and persists only what the origin returned: **Brave** — a returned URL is "any
  output from calls made to the API"; the persisted `final_url` is the same text, so the
  definition catches it "in part" unless the owner adopts the position that it is the origin's
  report of where *our* request landed. The clean route is the Enterprise Order Form. **Exa** —
  §4.2(a) bars reproducing "any information … obtained from or through the Services" and offers
  no transient-use language; the route is written permission, which can simply be asked for.
  **Firecrawl** — undefined; "Services" is a catch-all, and its search rides an *unnamed upstream
  index* whose terms are not passed through — if that is Google-derived the repo's rule fails on
  that alone. Needs written confirmation before it is treated as settled. **Perplexity Search API**
  — a URL is expressly "Output" we do not own, but nothing bars storing it; safer than Brave/Exa,
  still a legal read. **Tavily and the registries need no routing.** One architecture arguably
  escapes the barred definitions — use Brave/Exa only to pick a *host*, then re-derive the URL from
  a clean source and persist only that — and it is named here so nobody rediscovers it as a clever
  fix: the audit trail would then record a cause that was not the cause. That is provenance
  laundering, not a posture to adopt without counsel.
- **The order the evidence supports.** Registries first — Wikidata, DEQAR-minus-ROR, VGM, crt.sh
  are free, clean, and already hold more of each class than any result set here. Then Tavily's
  open-web mode (country + language + denylist, no `include_domains`) measured against the gold
  sets those registries define. Only if that recall is poor, spend on Exa / Brave / the
  enumeration agents — with the terms decision taken first, and this time for a reason that bears
  on the three classes. If registries plus Tavily open-web reach ~90% of gold, the barred
  providers are moot a second time.
- **Fix the wiring regardless.** `max_results=25` against a cap of 20; no `search_depth`; no
  `country`; no `exclude_domains` beyond 23 hosts. Tavily B is the same key and the same terms as
  Tavily A and found 2.4× the hosts.


### The method, written without a vendor

The techniques that recur across every provider surveyed, which is what the design should be
written in so a provider can be swapped: registrable-domain sweep (scope to a parent domain so
every subdomain matches); geography + language steering with the query written in the target
language; aggregator and register denylist; boost-not-filter over trusted hosts; entity-category
retrieval (find organisations by what they are); describe-the-entity phrasing; map / enumerate a
known host, reduce to distinct hosts, classify; registers first, then search only for the
set-difference; hub-page harvesting (a ministry page lists its bodies — take the outbound links one
hop out); name-to-site resolution for URL-less registries; one topic per call with constraints in
parameters, not prose; deep pagination for the long tail; recency windows for the live cycle;
criteria-verified enumeration agents whose list a human reads before the engine fetches; and
transient triage — read the snippet in memory to decide whether to fetch, persist nothing from the
provider object.

## 7. Not answered here

Page-level precision (needs fetch + reader over the hosts found); run-to-run variance; recall
against a real known-answer set (the 60 known hosts used here span Korea and China fixtures the
queries never targeted, so "24 of 60" is a sanity check, not recall); local-language queries (2 of
20 were Turkish, none Azerbaijani); Perplexity; whether a `/map`-then-read pass over the 507 hosts
yields awards at a rate that justifies the fetch cost.
