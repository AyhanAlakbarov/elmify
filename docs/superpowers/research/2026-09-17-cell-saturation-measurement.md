# Does a schematic search sweep reach "all"? One cell, measured

**Question.** The discovery design assumed search has a recall ceiling that more queries cannot
lift, and that registers are therefore load-bearing. The owner disputed it: with several engines, a
funding taxonomy and a harness, why not sweep country × subcategory systematically? This measures
the disagreement on one cell instead of arguing it.

**Cell.** Germany × `PRIVATE_FOUNDATION` — endowments and *Stiftungen* awarding money to
international master's students. Chosen as the densest plausible cell in the family with no register
anywhere.

**Method.** `OPENAI_EXTRACTION_MODEL` generated the query vocabulary itself from the family's
definition — 61 German and 38 English queries across twelve term families it named (*Stiftung*,
*Studienstiftung*, *Begabtenförderung*, *Förderwerk*, *Studienförderung*, *Bildungsfonds*,
*Stiftungsverzeichnis*, *Bundesverband Deutscher Stiftungen*, confessional, political, industry and
regional foundations). That generation step is itself the harness component under test. Queries were
interleaved German/English and run in nine batches of eleven across Tavily, Exa, Brave and
Firecrawl, recording **new distinct registrable domains per batch**. 396 provider calls, 9 transport
errors. All 1,067 resulting domains were then classified once by the same model — kind,
`funds_students`, and whether the organisation is German/DACH — so the curve could be recomputed on
real funders rather than raw hosts. Cost: roughly $2 of paid calls (Exa ~$0.73, Brave ~$1.49),
about 200 Tavily and 99 Firecrawl credits from their free tiers, and 14 classification calls —
call it **$6 and under two hours**. Nothing was persisted into the product.

## The curve

| batch | queries | new domains | new funders | **new German funders** | new foundations | share of batch that is a German funder |
|---|---|---|---|---|---|---|
| 0 | 11 | 272 | 150 | **146** | 34 | 54% |
| 1 | 22 | 126 | 58 | **49** | 21 | 39% |
| 2 | 33 | 119 | 39 | **32** | 11 | 27% |
| 3 | 44 | 127 | 24 | **18** | 10 | 14% |
| 4 | 55 | 82 | 27 | **24** | 5 | 29% |
| 5 | 66 | 106 | 29 | **25** | 12 | 24% |
| 6 | 77 | 84 | 32 | **27** | 10 | 32% |
| 7 | 88 | 89 | 17 | **15** | 9 | 17% |
| 8 | 99 | 62 | 18 | **17** | 4 | 27% |

Totals: 1,067 domains; 394 that fund students; **353 German or DACH funders**; 116 foundations or
church bodies that fund. The mix of the 1,067: 254 universities, 207 aggregators (which the
denylist had already excluded by name — these are ones it did not know), 184 foundations, 124 other,
117 companies, 67 news, 59 government, 23 research institutes, 14 social, 11 church, 7 multilateral.

## What it settles

**1. The cell did not saturate. It plateaued.** After the first two batches the rate settles at
15–27 new German funders per eleven queries and stays there — batch 6 found more than batch 3.
Extrapolating the plateau, 500 queries in this one cell would plausibly reach 800–1,000 funders.
**The prior assumption — that more queries buy nothing — is refuted for this cell.** A stopping rule
of "run until nothing new arrives" has no point to stop at.

**2. The late arrivals are real, and they are exactly the long tail no register lists.** The 23
foundations first seen in batches 6–8 include `bwstiftung.de`, `schleyer-stiftung.de`,
`rag-stiftung.de`, `studienstiftungsaar.de`, `mitteldeutsche-stiftung.de`, `breuerstiftung.de`,
`duerr-stiftung.de`, `sportstiftung-nrw.de`, and three that exist *because of* an eligibility key —
`stiftung-frauenforschung.de`, `stiftung-fuer-juedische-studien.de`, `szloma-albam-stiftung.de`.
This is the class §4.9 was written for, and search is the only route to it.

**3. Precision decays even though recall does not.** The share of each batch that is a German funder
falls from 54% to about 27%. So late queries keep finding, but each costs more per useful find. The
stopping rule must therefore be **economic**, not exhaustive: stop when the cost per new *verified*
award exceeds the option's worth. The plateau rate and the precision decay are its two inputs.

**4. The engines are not interchangeable, and one of them does not decay.** First-discoverer counts
for the 353: **Exa 147, Brave 100, Tavily 84, Firecrawl 22**. Exa's per-batch contribution barely
moves across the whole run (124, 63, 45, 43, 45, 38, 34, 42, 42) while Brave falls 81 → 11 and
Tavily 62 → 5. So a sweep should drop the decaying engines early and keep Exa running — the opposite
of treating them as a pool.

**5. Reading, not searching, is the binding constraint.** 353 funders at up to nine model calls per
page is the expensive half; the search that found them cost $2. Which of the 353 to read first is
the real question, and the owner's free-to-apply policy answers it.

## What this measurement is NOT — the sweep was under-configured

**Every figure above is a floor, not a ceiling,** because roughly a third of each provider's usable
surface was left switched off. Recorded precisely so the next run is not a repeat:

| provider | used | left unused, and why it matters |
|---|---|---|
| **Tavily** | `max_results=20`, `search_depth=advanced`, `country=germany`, `exclude_domains` | **`language:"de"` + `filter_by_language`** — the docs state ranking is optimised when the query language matches this parameter, and every German query ran without it; `include_domains_mode:"boost"` over a seed host list; `exact_match` for named foundations; `/map` and `/crawl` with `instructions` |
| **Exa** | `numResults=50`, `type=auto`, `excludeDomains`, `userLocation=DE` | **`category:"company"`** — the entity-matching pipeline built to return organisation homepages, i.e. precisely this job (note it constrains `excludeDomains`, so it needs its own denylist strategy); `numResults=100`, double the yield per call; `deep`/`deep-reasoning` types; `/contents` with `subpages`+`subpageTarget`; **Websets** and **`/agent/runs`** criteria-verified enumeration, both untested |
| **Brave** | `count=20`, `offset` 0–2, `country=DE`, inline Goggle | **`offset` 3–9 — 70% of Brave's depth unused**, 60 results taken of 200 available, and `query.more_results_available` never read as the stop signal; **`search_lang=de`** unset; `extra_snippets` for triage; `discussions,faq`; `/llm/context`; a hosted Goggle rather than inline (inline threw one HTTP 422 in the earlier probe) |
| **Firecrawl** | `limit=20`, `location=Germany` | **`categories:["pdf"]`** — foundation calls, decrees and annual reports are PDFs, a whole channel unopened; `country`; higher `limit`; `scrapeOptions:{formats:["links"]}` for outbound links per hit; `/map`, `/extract`, `/agent` |

Brave at full depth is 3.3× the results per query and Exa at `numResults=100` is 2×, before counting
`category:"company"`, the German language parameter or the PDF channel. **The plateau is therefore
almost certainly higher than 15–27 per eleven queries**, which strengthens rather than weakens the
owner's position.

Other limits: one cell, one country, one run — no variance estimate, and the plateau shape may
differ in a thin cell such as Azerbaijani outbound schemes. Host classification is a single model
pass, unaudited. And **a funder found is not an award served**: none of the 353 has been read, so the
page-level yield gate in the design's §7 is still the number that decides whether any of this
reaches a student.
