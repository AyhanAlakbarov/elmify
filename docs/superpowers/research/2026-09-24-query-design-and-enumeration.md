# Query design and organisation enumeration — what we ask, what the engines want, and what the register already knows

**Date:** 2026-09-24. **Trigger:** the owner's reading of the first live Türkiye sweeps and the
Websets probe — "we have designed the prompt/text in a wrong way and are using the search engines
poorly." This note checks that reading against the vendors' own documentation, the entity-set-expansion
literature, and a denominator we did not have before. It measures; it does not decide. The design
conversation follows it.

**What it does not re-derive.** The provider roster (`2026-09-17-role-routed-discovery-design.md`
§4.13), the capability ablation (`2026-09-17-search-capability-ablation.md`), the saturation cell
(`2026-09-17-cell-saturation-measurement.md`) and the Diffbot/Perplexity recon stand. Perplexity is
rejected there and stays rejected; Exa `findSimilar` is recorded deprecated in `2026-09-17-search-tool-probe.md` — **but live on 2026-09-24**: `POST /findSimilar` answered 200 with 10 results for $0.007, 2 of them peer foundations; the master spec §6.4a records it as a rung-3 "more like this body" source.

---

## 1. What we actually send today

Three query builders, none written from the vendor's guidance:

| path | code | query sent |
|---|---|---|
| discovery / hidden gems | `search.SearchSource.query_text` | `"{field} {degree} {country} official funding scholarship"` — a keyword bag, to Tavily `basic` |
| hidden gems, organisation half | `search.EntityExpansionSource.find` | `"{field} research institute graduate school"`, to the same Tavily source, then a sitemap walk of each host for `FUNDING_PATH_TERMS`, ten URLs per host |
| sweep, local pass | `domains.STEERING[cc].funder_query` | e.g. `"Türkiye'de yüksek lisans bursu veren vakıflar ve kurumlar"` |
| sweep, English pass | `sweep_organisations._ENGLISH_TEMPLATE` | `"An official page from a ministry, foundation or company in {country} describing the scholarships it awards for master's study"` |

Each sweep pass is **one query per provider at `numResults=100`** (Exa) or ten pages of twenty (Brave).
Two passes, two providers, four calls per country. The saturation cell ran 99 queries on one cell and
did not saturate; the sweep runs two and is described in its own docstring as "a probe, not a sweep".

**What came back (sweep #2, TR, `tehsil_sweep_tr2`):** 447 URLs seen, 214 novel registrable domains,
72 on `.tr`. Of those 72, hand-labelled: 14 government, 10 university, 28 foundation/other, **20 noise**
— 15 newspapers (`hurriyet`, `sabah`, `milliyet`, `cumhuriyet`, `star`, `yeniakit`…) and 5 scholarship
blogs. By provider: Exa 113 URLs / 49 `.tr` / 13 labelled noise; Brave 132 / 39 / 10. The 142 non-`.tr`
domains are worse — `scribd.com`, `windows.net`, `memurlar.net`, `finans7.com`, a recipe site — with
about fifteen real foundations on `.org` among them (`abdiibrahimvakfi`, `kumevakfi`, `cenanvakfi`,
`gayevakfi`, `incivakfi`, `yucelkulturvakfi`, `tdv`, `turgev`…). Foundation hosts across all 214:
roughly thirty.

**Why the newspapers.** Every query above is a *topic* query — it describes what a page is *about*
("foundations that give master's scholarships"). The pages most about that topic are lists and
articles: newspapers publishing "burs veren vakıflar" round-ups, blogs, aggregators. A foundation's own
page is not *about* foundations giving scholarships; it says "Vakfımız her yıl … öğrenciye burs
vermektedir — Burs Başvurusu". Both engines returned exactly what was asked for.

## 2. What the engines say they want

### Exa (neural)

Exa's own agent-facing guidance (`exa-labs/exa-mcp-server`, `skills/search/references/searching.md`,
fetched 2026-09-24) and its search docs:

- *"Exa uses vector embeddings, not keywords. It finds pages semantically similar to your query. It does
  not … validate that results meet your criteria. You are describing a target page, and Exa returns the
  nearest neighbors in embedding space."*
- *"Describe the target page itself, not the fact you're seeking."* Natural grammatical phrasing;
  word order changes results and can be used for coverage.
- **`numResults`: 5 for a named entity, 10 for precise filters, 15 for broad discovery. "Never use
  numResults above 25. If you need more coverage, run more queries with different angles at n=10-15
  rather than one query at n=50."**
- *"Query diversity … genuinely different angles, not just synonym swaps."*
- `category:company` — the endpoint reference: *"The `people` and `company` categories have improved
  quality for finding people profiles and company pages"*; those two categories **do not support
  `excludeDomains`** or published-date filters (400 on violation). `excludeDomains` otherwise takes
  up to 1,200 entries. `includeText`/`excludeText` are deprecated.
- Search types: `auto` ~1 s; `deep` / `deep-lite` / `deep-reasoning` run *"a research process rather
  than a single retrieval pass"* with **`additional_queries` (1–10, deep types only)** used
  *"alongside the main query for broader results"*, and `output_schema` + `system_prompt` on every
  type (object schemas ≤ 2 levels, ≤ 10 properties; grounding with citations and confidence per
  field). `numResults` maximum 100 on every type.
- Pricing (exa.ai/pricing, 2026-09-24): **$7 / 1k requests** for `instant`/`fast`/`auto`, base
  covers 10 results, **$1 / 1k additional results**; `deep-lite` and `deep` **$12 / 1k**,
  `deep-reasoning` $15 / 1k; contents $1 / 1k pages; free tier $10 / month. So our 100-result `auto`
  call is $0.097 (as §13 records); a `deep` call with ten `additional_queries` and 100 results is
  ~$0.102; ten `auto` calls at 10 results are $0.07.
- Exa's own benchmark against Brave (exa.ai/versus/brave, 2026-08-02, 605 company queries, code at
  `github.com/exa-labs/benchmarks`): **Company Search R@1 61.8% vs 35.9%**. Vendor-run; cited as the
  vendor's claim about itself, which is what the engineering rule permits.

**Where our code contradicts this.** One query at 100 results is the anti-pattern the vendor names.
The ablation's "25→100 multiplied local funders ×1.7–3.4" and the vendor's "never above 25" are not in
conflict: depth per query helps, and breadth of angles helps more — the saturation cell is the
measurement of breadth (99 queries, no plateau). We bought depth and skipped breadth. The
`category: company` −2.7 on the German key was measured with `excludeDomains` on the same call, which
Exa now rejects for that category; the Websets run below used the Companies entity and found
foundations without difficulty, so the earlier result is worth re-measuring with client-side
exclusion, which `is_catalogue` already does.

### Brave (keyword)

From `api-dashboard.search.brave.com` (query docs, operators, Goggles; 2026-09-24):

- `q` **≤ 400 characters and ≤ 50 words.** Operators live inside `q`: `site:`, `-site:`, `intitle:`,
  `inbody:`, `filetype:`, `lang:`, `loc:`, quoted phrases, `-term`. The recommended order is broad
  (`site`, `lang`) then narrow (`intitle`, `inbody`).
- Pagination `count` ≤ 20, `offset` ≤ 9; docs say check `more_results_available` — our adapter records
  that the field is absent in practice and stops on the first empty page. Both stand.
- **Goggles can be passed inline** in the `goggles` query parameter (`$boost=3,site=dev.to`, rules
  separated by `%0A`), up to three per request; hosting on GitHub/Gist and registering at
  `search.brave.com/goggles/create` is the *other* option, not the only one. `brave.py`'s comment that
  the Goggle waits on hosting is wrong; `tehsil-funders.goggle` can ship today, inline.
- A keyword engine matches terms, so the useful query is the vocabulary a foundation's own scholarship
  page contains — `intitle:vakfı "burs başvurusu"`, `inbody:"yüksek lisans" burs vakfı -haber` — not
  a sentence describing the page.

### Tavily

Unchanged: resolution and inventory (roster §4.13a). Not a discovery engine; the sweep command already
excludes it.

## 3. The denominator we did not have

**Türkiye.** The Directorate General of Foundations' register, `vgm.gov.tr/vakif-sorgulama`, carries a
scholarship filter. Rendered 2026-09-24 (the page is client-side; a plain GET returns "YÜKLENİYOR"):

- all foundations: **6,857**
- `IsGrant=true` ("burs veren vakıflar"): **4,076**

Each row: name, address, district/city, phone/fax, e-tebligat, **e-mail**. No website column — but of
the twelve rows on page one, eight carry an own-domain e-mail (`1870vakfi.org`, `yekuv.org`,
`vakif1972.org.tr`, `1923.com.tr`, `tohum13yildiz.com`…) and four are Gmail/Hotmail. So roughly
two-thirds of the register resolves to a host with no search call at all, and the rest is
`TavilyProvider.candidates()`'s job.

Against that: the sweep found ~30 foundations; the Websets run, 13 all-green of 310 analysed at 25
minutes. **Search-led discovery reached under 1% of the register**, and the register's own filter
already asserts the one fact the classifier exists to establish. The owner's rule — the register is the
denominator, never the reading queue — holds unchanged: 4,076 × ~$0.35 a host through the reader is
~$1,400, which is what the gate in §6 is for.

**Germany.** `foerdermittelkompass.reflecta.org` exposes a `grant_providers` API: **1,938 providers**,
eighteen typed `provider_type` values (`private_foundation`, `political_foundation`,
`industry_chamber`, `state_ministry`, `municipality`, `lottery_fund`…), website, region, `grants_count`;
bearer-token auth, licence and price unstated. Not a substitute for the 377-funder key, and the licence
is unread — recorded as a candidate register, not a source.

## 4. Criteria-verified enumeration, measured on Websets

Owner-run in the dashboard on 2026-09-24, Companies entity, query *"foundations and companies in
Türkiye that award scholarships for master's study"*, four criteria (foundation-or-company-in-Türkiye;
awards master's scholarships; awards money directly to students; is the administering organisation,
not a site describing it), count 25.

- **25 minutes in: 310 candidates analysed, 13 all-green matches, 26 rows shown** (rows with any
  "Unclear" cell are not matches). Zero newspapers among the 26. Six overlap our 72 `.tr` hosts
  (`tog`, `elginkan`, `tev`, `gev`, `tmkv`, `hanvakfi`); several of the rest are in our 214 on `.org`;
  around a dozen are new (TÜRGEV, İSOV, Hüsnü Özyeğin, İbrahim Çeçen, TESYEV, Mehmetçik, Şule Yüksel
  Şenler, ARDEV…). Universities appear with "Unclear" on *awards money directly*; IC Holding appears
  through İbrahim Çeçen Vakfı with "Unclear" on scholarships. The government half is excluded by
  criterion 1 as written.
- **Billing:** the dashboard shows *10 credits per match, 2 per enrichment row*; non-matches cost 0.
  Public plan figures (websets.exa.ai/billing and third-party summaries, 2026-09-24; the docs FAQ
  carries no prices): **Pro $449 / month, 100,000 credits → $0.045 per verified match**. The API
  *"requires a paid Websets plan; Search API credits and Websets credits are separate"* — measured
  by us: `GET /websets/v0/websets` → 401 on the free plan.
- **API shape** (`exa.ai/docs/websets/api/websets/searches/create-a-search`): `criteria` ≤ **5**;
  `entity` company/person/article/research_paper/custom; **`scope: [{source: import, id}]`** — *"Limit
  the search to specific sources (existing imports). Any results found within these sources matching
  the search criteria will be included"*; **`exclude: [{source: import|webset, id}]`** — *"Any results
  found within these sources will be omitted"*; **`recall: true`** — *"an estimate of how many total
  relevant results could exist for this search"*. Imports are CSV with a URL column, ≤ 50 MB.

Three consequences, each a design lever rather than a decision:

1. **`scope` over an import is the judge role.** Upload the 4,076 (or whatever a register yields), run
   the criteria, pay 10 credits per host that passes. If half pass, ~$92 for a verified,
   website-carrying list of every scholarship foundation in Türkiye. That is a classifier we do not
   build, priced per *match*, on a list the register vouched for.
2. **`exclude` over an import is the set-difference, server-side.** Upload the register; a discovery
   search then returns only what the register lacks — the exact question the sweep asks, without the
   sweep.
3. **`recall: true` is a saturation estimate for free.** The stop rule §6.7 says a sweep must report
   is something the vendor will estimate before we spend.

Not measured: throughput on an import of thousands (the discovery search did 310 in 25 minutes);
whether `scope` verification bills identically to discovery; enterprise pricing.

**Exa Agent API** (`exa.ai/docs/reference/agent`): async runs that *"fan out many searches across
different angles, read and condense the pages behind them"*, verify *"each candidate against your
criteria"*, and return `output.structured` against a JSON `outputSchema` with `maxItems`. Fixed-effort
pricing **minimal $0.012 · low $0.025 · medium $0.10 · high $0.50 · xhigh $1.00 per request**, plus
$0.005 per search call in metered modes. No published result ceiling or latency. Untested by us; it
is the "query expansion + verification" mechanism at a per-run price rather than a plan.

## 5. What the enumeration literature adds

Entity set expansion (SetExpan, arXiv 1910.08192; language-model probing, arXiv 2004.13897; GenExpan,
arXiv 2304.03531): start from seeds, expand iteratively, and **stop when the set has not grown for three
consecutive iterations** or reaches a target size; evaluate as MAP@K against a ground-truth set. Two
things carry over directly. The stop rule is the one §6.7 asks for and phrases as "plateau R per
batch". And the evaluation is only defined *against a ground truth* — which is what §3 supplies and
what every measurement to date has lacked outside Germany.

## 6. What this means for the three flows

Findings, stated as what would change; the decision is the design conversation's.

**The sweep.** Breadth, not depth: per (country × family) a *set* of angled queries at 10–15 results,
generated per §6.7 from the family's vocabulary in the local language — phrased as the target page
phrases itself ("Vakfımız … burs başvurusu", "Stiftung … Stipendium für Masterstudierende … bewerben"),
not as a topic. On Brave, operators and the inline Goggle. Stop by the no-growth rule; report
first-discoverer per angle so dead angles are dropped per cell, which is what the saturation cell
showed works. Exa `deep` with ten `additional_queries` is one call per family that does the fan-out
vendor-side for ~$0.10; worth one live measurement before writing the generator.

**Hidden gems.** `EntityExpansionSource`'s search half is redundant once the register holds the
organisations; the sitemap walk is the part that finds programmes, and it should start from register
rows — `OrganisationDomain` — not from a Tavily query. The programme-page walk itself (sitemap vs
Firecrawl `/map` vs Exa site search) is unmeasured and is measurable on the ~30 foundations we hold.

**The classifier (§6.6).** For a country with a register carrying the purpose, the classifier's
question is already answered for the names, and what remains is *verify at the origin* — which is
Websets `scope` at $0.045 per pass, or our reader. For a flat country (Germany's DENIC, no
`gov.de`) and for hosts arriving by pointer routes, a classifier is still needed; the Websets output
is the labelled set its ≥95% gate wanted.

## 7. Open, in one place

- Websets `scope` throughput and billing on an import of thousands — one API call on a Pro plan.
- ~~Exa `deep` + `additional_queries` on one Turkish family — ~$0.10, one call.~~ **Measured the same
  day, $0.029 billed:** ten page-voiced angles in one `deep` call at `numResults: 100` returned 27
  results / 16 registrable domains, 10 on `.tr`, 0 denylisted, 4 novel against the sweep's 214 (one
  real foundation, `insanvakfi.org.tr`). `deep` synthesises a small set; it does not union the
  angles. The fan-out is ours to build.
- `category: company` re-measured with client-side exclusion — the −2.7 may be an artefact.
- Fördermittelkompass licence; VGM's own reuse terms (a `.gov.tr` register, not yet read).
- Registers for AZ, KZ, GE, UZ — the same question as VGM, one country at a time.
