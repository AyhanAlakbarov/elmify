# Tool capabilities we pay for and were not using — audit of 2026-09-18

Owner asked, after Exa's neural search found in one $0.02 call the programme-level hidden gems the
design planned to crawl for, whether the same oversight existed elsewhere. It did. Method: each
vendor's *current* documentation (not memory), then a live call wherever a claim was cheap to test.
Costs below are what the calls actually billed. Nothing from any provider response was stored.

## 1. Exa — the largest gap, and it is the tool we rank highest

| capability | measured | what it changes |
|---|---|---|
| **Neural search with a descriptive query** | 24 results, $0.021: ChEMoinformatics+ grants page, KU Leuven TCCM scholarships, TU Braunschweig AI for Molecular Sciences, Padua, ITMO, Utrecht fee-support pages | field-neighbour expansion at query time; programme pages that *mention money* |
| **`includeDomains=[university]`** | `tum.de`: 25 results, $0.022 — FIM Exclusive Scholarship, Linde/MDSI Master's Scholarship, programme fee/aid pages. `metu.edu.tr`: three fully funded MSc positions at PETE, DEIE scholarship PDF, IPS, ACHIEVE project | **per-institution hidden gems without a crawl** — replaces the host-inventory route as the first pass; inventory becomes the fallback |
| **`findSimilar`** | marked deprecated in the spec, **live**: 10 results, $0.007, the ChEMoinformatics+ partner and listing neighbourhood | "more like this programme" for a card, at a third of a search's price |
| `/contents` `highlights` | one query-relevant sentence per result, in the same call | the transient triage that decides which pages the expensive reader reads |
| `/contents` `subpages` + `subpageTarget` | works, $0.001 for five — but on the test site followed *external* partner links | usable only with our own on-host filter |
| untested and relevant | `summary` (vendor text — triage only), `text.includeSections`, `maxAgeHours`/livecrawl, `startPublishedDate` (recency leg), modes `fast`/`deep`, Websets | measure when the recency and completeness legs are built |

## 2. Brave

- **Goggles can be passed inline** ("URL or inline definition") — the "Goggle hosting" open item was
  never real. Closed.
- `extra_snippets=true`: up to five extra excerpts per result — triage without a fetch.
- `freshness` (`pd/pw/pm/py` or a date range): the recency leg for calls and deadlines.
- `result_filter=web` already in use; `discussions`/`faq` verticals per the spec, unmeasured.

## 3. Tavily

- **Extract costs 1 credit per 5 basic URLs**, not 1 per page: tier 2 in the design was priced 5× too high.
- `time_range` / `topic` (recency), `include_domains`, `auto_parameters`.
- `crawl` with `instructions` and `selectPaths`, `map` at 1 credit per 10 pages — a paid inventory
  alternative to crt.sh + `/map`.
- Extract with `query` + `chunks_per_source` **returned no chunks in two calls** (basic and advanced,
  snake_case REST). Either the parameter shape differs from the SDK docs or the feature needs a
  different endpoint — confirm before designing on it.

## 4. Firecrawl

- Proxy modes are now `basic | enhanced | auto`; **enhanced and auto-escalation cost +0** — tier 3 is
  1 credit per page, not "paid stealth credits".
- **`changeTracking` in `git-diff` mode is free** — a page-change detector for the freshness cadence
  that the design was going to build from content hashes.
- `maxAge` serves a recent cached copy without a fetch; ZDR is +1 credit; `json` extraction +4 (a
  vendor LLM reading the page — not adopted: reading stays in-house and quote-verified).
- Batch scrape with webhooks for the background stage.

## 5. Diffbot — the second-largest gap

**Enhance by name resolves the names the lexical resolver could not.** Ten names, 25 credits each,
of which seven had failed lexical resolution today:

| name | Enhance returned | right? | confidence |
|---|---|---|---|
| Bilim ve Sanat Vakfı | `bisav.org.tr` | ✓ | 0.29 |
| Toplum ve Hukuk Araştırmaları Vakfı | `tohav.org.tr` | ✓ | 0.43 |
| İstanbul Eğitim ve Kültür Vakfı | `istek.org.tr` | ✓ | 0.16 |
| Türkiye Sosyal Tarih Araştırma Vakfı | `tustav.org` | ✓ | 0.31 |
| საქართველოს ახალგაზრდა იურისტთა ასოციაცია (Georgian script) | `gyla.ge` | ✓ | 0.33 |
| Georgian Young Lawyers' Association | `gyla.ge` | ✓ | 0.54 |
| Cusanuswerk | `cusanuswerk.de` | ✓ | 0.46 |
| Türkiye Üçüncü Sektör Vakfı | a TÜSEV campaign site | ✗ adjacent | 0.19 |
| Wau Holland Stiftung | `wau-holland-stiftung.de` | ✗ by the truth set; plausibly theirs | 0.35 |
| Stiftung Gustav Werner und Haus am Berg | no match | — | — |

**7 of 10, six of them syllabic acronyms in Turkish and a Georgian-script name** — exactly the class
§4.13b said no lexical rule reaches. Country is reliable; **categories are not** (Cusanuswerk →
"Software Companies"), so Enhance is a resolver, not a classifier. Confidence is low across the board,
so its answer goes through the same title check as any other candidate. Free tier: 400 entities a
month, 5 calls a minute — right-sized for the *unresolved residue*, not for bulk.

## 6. The model calls — half the reader's cost is on the table

- **OpenAI Batch API: 50% discount, 24-hour window, higher rate limits.** Stage 2 of the on-demand
  search (reader in the background) and the classifier are batch-shaped. **Flex** (`service_tier:
  "flex"`) bills at Batch rates on synchronous calls for non-urgent work, with caching discounts on
  top; needs a long client timeout.
- **OpenAI prompt caching is automatic at ≥ 1,024-token prefixes**, exact-prefix, `prompt_cache_key`
  routes to the same machine; the doc's example model bills cached input at a quarter of the price.
  The judge reads each chunk three times with two OpenAI phrasings: put the frozen instruction and
  the chunk *first* and vary only the tail, or the second phrasing never hits the cache.
- **Anthropic Message Batches: 50%**; prompt caching via `cache_control` with reads at about a tenth
  of the input price. The judge's Claude reading is one of three per chunk — the chunk is the
  cacheable prefix. The judge model is `claude-sonnet-5` ($2 / $10 per MTok).
- Anthropic's server-side `web_search` / `web_fetch` tools exist and would be a fifth index. Not
  adopted: no depth control and unmeasured; recorded so it is a decision, not an omission.

Neither batching nor caching is used anywhere in `apps/` today (grep: no `batches`, no
`cache_control`, no `prompt_cache_key`).

## 7. Scrapling — "all features on" now has a definition

From the installed package: `solve_cloudflare`, `block_webrtc`, `hide_canvas`, `real_chrome`,
`google_search` (referer), `dns_over_https`, `locale`/`timezone_id`, `network_idle`, `wait_selector`,
`block_ads`, `disable_resources`, `user_data_dir` (session persistence), `cdp_url`, `page_action`.
The CLAUDE.md constraints stand: `block_webrtc=True` always, downloads and service workers blocked,
inside the secret-free browser task behind the egress proxy, never against a portal.

## 8. SerpApi

Nothing new: Baidu and Naver engines as decided; transient yardstick.

## What this changes in the design (applied to the 2026-09-18 spec the same day)

1. Per-institution hidden gems: Exa `includeDomains` first, inventory second — measured, not "untested".
2. Fetch tiers repriced: Tavily Extract 0.2 credit/page; Firecrawl tier 3 at 1 credit with `proxy: "auto"`.
3. Freshness: Firecrawl `changeTracking` (free) and Brave/Exa date filters for the recency leg.
4. Resolution ladder gains a step before the human queue: **Diffbot Enhance on the unresolved residue**,
   confidence-gated, title-checked, within the free allowance.
5. Stage 2 of the on-demand search runs through **Batch/Flex with prompt caching** — roughly half the
   reader's model cost — and the judge's prompts are reordered so the shared chunk is the cached prefix.
6. Brave `extra_snippets` and Exa `highlights` are the triage inputs; Goggle passed inline.
7. `findSimilar` is live and cheap; "more like this programme" on a card is one call.

Open: Tavily extract chunks (shape unconfirmed); Exa `subpages` on-host filtering; whether Diffbot's
confidence threshold can be set from these ten alone (no — measure on the next fifty unresolved).
