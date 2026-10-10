# The fetch engine — any website we encounter, ending in one of eleven outcomes

Design, 2026-09-22. Owner decisions the same day: **both vendors are paid** (Firecrawl Standard,
scrape.do Hobby — written as configuration, not code, because the tier will rise with investment);
Firecrawl `/agent` is used as the **navigator** — it finds pages, our reader verifies them (decision
delegated to this brainstorm and taken here, §7.4); an Internet Archive capture counts as evidence for
**twelve months**; and the goal is stated plainly — *fetch any website we encounter*, with no silent
dead end.

> **Amended 2026-09-23** after the owner's review of the typed-decisions design. Owner decisions:
> **`/agent` may search the open web on its own** — only URLs are kept from it, and every page is
> re-fetched and verified by us, the rule CLAUDE.md already grants Exa and Brave (§7.4); **no
> person waits in the pipeline** — rung 7 and the "not found" outcome are ledger rows, never gates
> (§4, §7.6); and page-finding is a **funnel, cheapest first, each stage scored on the corpus**,
> with Tavily's guided map as a candidate stage before the navigator (§7.0, §7.3a). Two corrections
> from Firecrawl's own `/agent` page the same day: `urls` only seeds the agent, and `maxCredits`
> defaults to 2,500 (§7.4). The budget is per vendor, as master already has it (§9.1).

Supersedes the fetch half of `2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md`
§4 (§4.0–§4.1c; §4.1d stays, amended in one place — §3 below) and the fetch increments of
`docs/superpowers/plans/2026-09-19-vendor-fetch-path-and-deletion.md`. Every vendor capability named
here was read from `docs.firecrawl.dev` and `scrape.do/documentation` on 2026-09-22 (§4.1d of the
older spec lists the pages); re-read them before executing any plan built on this document.

## 1. Why this exists

The research readers — programme pages for CV rules, funder pages for awards, registers for
organisations — depend on one thing none of them controls: that the page can be fetched. Measured
2026-09-19, our own honest client read 49 of 58 hosts; Firecrawl recovered six more; scrape.do one;
two were dead. That is a ladder, and it worked, but it lived in three places (an egress client, a
vendor plan, a spec section) with no memory between fetches, no closed set of outcomes, and a
routing rule that contradicted itself (§4.1d item 1 of the older spec). "Found nothing" and "could
not look" were the same row — the failure mode CLAUDE.md records this repo meeting twice.

The engine makes fetching one seam with one ladder, a memory per host, a closed set of outcomes,
and cost that is bounded in layers. It uses both vendors to the full because the owner is paying
for them; it builds nothing a vendor already sells.

## 2. Scope and non-scope

**In:** every research fetch — programme pages, funder pages, register and hub pages, linked
documents (PDF, DOCX, XLSX, PPTX, ZIP), the labelled corpus's pages, and the monthly refresh of all
of them. Site-level discovery (inventory, crawl, navigation) and page-level fetching. Cost control,
provenance, and the outcome trail.

**Out, unchanged from earlier decisions:** `apps/documents/europass.py` (student PII; own egress,
pinned address, never a vendor); `egress.fetch_json_api` and the contracted APIs behind it (our keys
never travel through a vendor); every portal (`apps/portals/`, and the glass-box extension that
replaces it — the agent acts as an authenticated applicant there, and `phased requirements.md` §2
and §3.4 forbid circumventing access controls); the readers themselves (extraction and quote
verification are unchanged and downstream of this engine).

## 3. The seam

```python
fetch_page(url, *, purpose="read", tag=None, require_origin=None, budget=None) -> FetchedPage
```

`retrieve_official_source(url)` keeps its name and signature and delegates to `fetch_page`, so its
callers (`reader`, `program_rules`, `pipeline`, `seeds`, `fetch_ladder` on master, 2026-09-23) do not
change shape.

- `purpose="read"` (default): the reader will read it, or it will be re-checked on a cadence. Firecrawl
  first, `changeTracking` on.
- `purpose="bytes"`: the origin's own untouched bytes must be defensible — a snapshot digest, a
  dispute. scrape.do with `transparentResponse=true`, no extraction. **This amends §4.1d item 1 of the
  older spec:** with both plans paid, "one-shot fetches go to scrape.do" is no longer a rule; what
  remains of it is this purpose. The by-hand reads that build the labelled corpus use neither — they
  run through the session's own tools, by design (corpus spec, independence of labelling).
- `tag`: the change-tracking scope. Defaults to the admissions cycle `persist_snapshot` already writes
  to `OfficialSourceSnapshot.admissions_cycle`; a monitor (§8) uses the same value.
- `require_origin`: when set, the final URL must share scheme and host with it or the outcome is
  `OFF_SITE` — `require_same_origin` as today, applied *before* any bytes are persisted or read.
- `budget`: the sweep's `SweepBudget` (§9); absent means the single-fetch default.

`FetchedPage` extends today's `FetchResult` (`final_url`, `redirects`, `content_type`, `body`,
`browser_required`) with: `markdown` (what every reader reads from now on, for every artifact kind),
`outcome` (§6), `fetched_via`, `rung`, `credits`, `status_code`, `change_status`, `captured_at` (archive
only), `page_count` / `total_pages` (documents), `screenshot` (only when taken, §7.5), and `attempts`
— the trail, one record per vendor call.

**The digest is over `markdown`, not `body`.** Firecrawl's `rawHtml` is its own rendering and varies
between fetches of an unchanged page (measured 2026-09-18: 189,682 vs 422,515 bytes for FAU). The
vendor's `changeStatus` is the first opinion on "unchanged"; `content_sha256` over `markdown` stays
the second, as §4.1 of the older spec already required. `body` keeps its meaning for HTML (the
vendor's raw HTML, for `readable_text` and the DOM object) and carries the raw document bytes only
under `purpose="bytes"`.

## 4. The ladder

Walked top to bottom. A rung is *tried* only on the condition in its third column; the ladder
*stops* at the first rung that returns a usable document. **Usable** means: the vendor returned a
document, its content type is in the existing allowlist, its size is under the existing 10 MiB cap,
and it is not a shell — the reader's own rule, fewer than 1,500 readable characters while the raw
HTML is 20,000 bytes or more.

| rung | call | tried when | catches |
|---|---|---|---|
| 1 | Firecrawl `POST /v2/scrape`: `formats: ["markdown", "links", "rawHtml", {"type": "changeTracking", "tag": <tag>}]`, `parsers: [{"type": "pdf", "maxPages": FETCH_PDF_MAX_PAGES, "pageMarkers": true}]`, `skipTlsVerification: true`, `blockAds: true`, `onlyMainContent: true`, `timeout` from the host profile. `proxy` is **not passed** (deprecated; `auto` is the default and escalates to enhanced on 401/403/429 at no extra charge). `location` is **not passed** unless the profile says the host is geo-gated. | always first, unless the host profile's `start_rung` is higher (§5) | plain and JavaScript pages, PDF / DOCX / XLSX / PPTX / EPUB / CSV by URL, broken TLS chains, http-only hosts, and every 401/403/429 the enhanced proxy passes |
| 2 | rung 1 plus `actions: [{"type": "wait", "milliseconds": 3000}, {"type": "scroll", "direction": "down"}, {"type": "wait", "milliseconds": 2000}]` and `waitFor` from the profile | rung 1 returned a **shell** | lazy-loaded and client-rendered content; 2 credits per browser-minute |
| 3 | scrape.do `GET` with `render=false&super=false`, `disableRedirection=true` (redirects followed by us, hop by hop, each validated — §10), `geoCode` from the profile when geo-gated, `timeout` from the profile | rung 1 returned **no document** (network, 5xx, timeout), or a 401/403/429 survived the enhanced proxy | timeouts and TLS a different network passes; soft blocks; 1 credit |
| 4 | scrape.do `render=true&super=true`, `sessionId` fixed for the sweep on this host (a residential address that changes between pages re-triggers the challenge this rung exists to pass), `waitSelector` / `customWait` and `playWithBrowser` scroll from the profile, `blockResources` left on | rung 3 failed, or rung 2 was still a shell | the antibot residue (measured 1 host in 58) and applications that need a real browser on a residential address; 25 credits |
| 5 | **retry queue** — a `FetchAttempt` row with outcome `RETRY_SCHEDULED` and `retry_after`; `manage.py retry_due_fetches` re-enters the ladder at the host's `start_rung` | rungs 1–4 all failed | outages, rate-limit windows, deploys. Network class: +24 h, +48 h, +96 h. Block class: +6 h, +24 h, +48 h. Paced through the existing `DomainLease`; a due retry whose host is still inside `blocked_until` (§5) is rescheduled to that time, not spent. Three attempts, then rung 6 |
| 6 | **archive** — `https://archive.org/wayback/available?url=<url>&timestamp=<now>` (fetched through rung 3) names the closest capture; if its timestamp is within `FETCH_ARCHIVE_MAX_AGE_DAYS`, the capture is fetched as `https://web.archive.org/web/<ts>id_/<url>` (the `id_` flag returns the original bytes without the archive's toolbar) through rungs 1 then 3; the original URL inside the archive URL must satisfy `require_same_origin` with the requested one | retries exhausted | sites that block *us* specifically — DAAD refuses our connections, Sciences Po answers 403; both were recovered from captures dated 2026-06-25 and 2026-02-01 on 2026-09-15 |
| 7 | **recorded for a person** — `record_blocked_source` writes a `ConsultantResearchTask` whose reason names the outcome and whose trail is the `FetchAttempt` rows for the URL; a ledger row nothing waits on (owner decision 2026-09-23) | no fresh capture (`archive_stale(<date>)`), or `UNREADABLE` after rung 4, or `OFF_SITE`, or `DEAD` from a catalog row | everything else — and a person sees the screenshot (§7.5) |

Three rules make it "any website":

1. **Nothing is a dead end without a recorded reason.** Every vendor call writes a `FetchAttempt`;
   every terminal outcome names the rung it died on and why.
2. **A rung is skipped only because the host profile learned it was useless last time**, never
   because a heuristic guessed. The first rung is the classifier: one 1-credit call answers what a
   page-type predictor would have to guess.
3. **The origin's answer is final where it is an answer.** A 404 or 410 from the origin is `DEAD` at
   rung 1 — a different proxy would not change it (Firecrawl escalates on 401/403/429 only, for the
   same reason). A 200 with fewer than 1,000 bytes, or carrying a challenge marker ("Just a moment",
   "Enable JavaScript and cookies to continue"), is a **block**, not a document — measured 2026-09-19
   on mischolarship.com, which returned 200 and 469 bytes of nothing at rung 3 and was billed 1 credit.

## 5. Host memory — `HostProfile`

One shared-catalog row per host (lowercased, IDNA-encoded), read before every fetch and written after
every outcome:

| field | meaning | written when |
|---|---|---|
| `start_rung` (1–4, default 1) | where the ladder begins for this host | success at rung 3 or 4 sets it to that rung; success at 1 or 2 resets it to 1 — only *expensive* rungs are remembered |
| `needs_render`, `needs_residential` | rung-4 memory, readable by a person | success at rung 4 |
| `geo_code` (2 letters), `languages` | set only when a page was measured geo-gated or language-negotiated | by hand, from the ledger (§4 rung 7); never by the pipeline |
| `wait_selector`, `custom_wait_ms`, `timeout_ms` | rung-2/4 tuning | by hand; `timeout_ms` raised automatically after a timeout that a longer wait then passed |
| `vendor_options` (JSON, closed keys: `showFrames`, `setCookies`) | the rare knobs — requirements inside an iframe, a consent cookie | by hand |
| `last_success_rung`, `last_success_at`, `last_probe_at` | what worked, when; when rung 1 was last tried | every success; every probe |
| `blocked_until` | do not try before | a `BLOCKED` outcome: +6 h, doubling per consecutive block, capped at 7 days |
| `robots_blocked_paths` (JSON list) | what the site's `robots.txt` refused a crawl | every crawl's `robotsBlocked[]` |
| `credits_30d`, `attempts_30d` | the per-host cost ledger the scrape.do multiplier warning asks for | every attempt, rolled nightly |

**Six of those columns are not in the table plan 1 shipped** (2026-09-24): `needs_render`,
`needs_residential`, `vendor_options`, `robots_blocked_paths`, `credits_30d` and `attempts_30d`.
Each needs a reader that plan 1 does not build — `needs_render`/`needs_residential` were written
only as `page.rung >= 4` beside `start_rung = page.rung`, three columns holding one fact;
`vendor_options` needs `showFrames`/`setCookies` reaching `scrapedo.scrape`; `robots_blocked_paths`
needs the crawl of §7.3; and the ledger pair needs both a per-host cost check and the nightly
roller its name implies, without which they are lifetime totals wearing a 30-day name. They come
back with their readers, in plan 2's own migration. The schema is free until the first real
database (CLAUDE.md, "Migrations: squash once"), which is why cutting them now cost a migration
edit and nothing else.

**Re-probe.** A host with `start_rung > 1` and `last_probe_at` older than `FETCH_REPROBE_DAYS` is tried
once from rung 1 before its remembered rung. A host that got easier stops paying rung-4 prices; a
host that did not costs one wasted credit a month.

## 6. Outcomes — the closed set

| outcome | meaning | `OfficialSourceSnapshot.retrieval_status` | downstream |
|---|---|---|---|
| `FETCHED` | a usable document | `CURRENT` | the reader runs |
| `FETCHED_PARTIAL` | usable, but the PDF was cut at `maxPages` (`total_pages > page_count`), or `readable_text` overflowed its cap | `CURRENT`, `render_status` suffixed `:PARTIAL`; the attempt row carries both page counts | the reader runs; the rule provenance shows "read N of M pages" |
| `UNCHANGED` | `changeStatus == "same"` for this `tag` | no new snapshot | the reader is skipped — this is the saving that pays for everything else |
| `ARCHIVED` | a capture ≤ `FETCH_ARCHIVE_MAX_AGE_DAYS` old, same origin | `CURRENT`, `render_status = "ARCHIVE:<capture date>"` | the reader runs; every rule derived carries the capture date |
| `UNREADABLE` | a shell after rung 4 | `unreadable = True` (existing flag) | rung 7 |
| `BLOCKED` | 401/403/429 or a challenge at every rung; retries exhausted | `BLOCKED` | rung 6 |
| `UNREACHABLE` | no document at every rung; retries exhausted | `FAILED` | rung 6 |
| `DEAD` | the origin answered 404 or 410 | `FAILED` | rung 7 when the URL came from the catalog; dropped when it came from discovery |
| `OFF_SITE` | the final URL left the required origin | `FAILED`; no bytes persisted | rung 7 — a moved site is a catalog fix, made by a person |
| `INVALID` | `validate_public_url` refused the URL or a hop | no snapshot | logged; rung 7 when the URL came from the catalog |
| `BUDGET` | the sweep's budget, a vendor's remaining-credit floor, or a 402 stopped the call before it was made | no snapshot | the sweep stops; a `RETRY_SCHEDULED` row for the next budget window |

`RETRY_SCHEDULED` is the one intermediate state and never reaches a caller. Every outcome carries
`fetched_via`, `rung`, `credits`, the validated `final_url`, and the trail — so a caller can always
tell "found nothing" from "could not look", by construction.

## 7. Site jobs — what "the crawler" is

Most of the crawler is a vendor call. Our code owns the order, the stop rule, the residue, and the
four programme-level outcomes.

### 7.0 The funnel — cheapest first, URLs only, every stage scored (amended 2026-09-23)

Finding the pages that carry a programme's requirements is a funnel of five stages. **Every stage
returns only URLs**; each is fetched through the ladder (§4) and must satisfy `require_origin`
against the institution's site or the named funder's, so no vendor's reading of a page is ever
kept, whichever stage found it — the search-provider rule CLAUDE.md already states.

| stage | what | cost per programme | runs |
|---|---|---|---|
| 1 | the programme page, every **document** it links (PDF, DOCX, ZIP — `links` from rung 1) and every file a rule names (typed-decisions §6.6); HTML links are stage 2's, so this stage is bounded by the page's own document links, never by a hop count | 2–4 ¢ | always |
| 2 | `/map` ranked by D2 (typed-decisions §4), the top 25 crawled (§7.1–7.3) | ≈ 2 ¢ | always |
| 3 | **Tavily `/map` with `instructions`** — a guided walk of the site returning URLs and nothing else (§7.3a) | 5–8 ¢ for 50 URLs | on miss |
| 4 | Firecrawl `/agent` with the brief of §7.4, capped at `FETCH_AGENT_MAX_CREDITS` | ≤ 25 ¢ | on miss |
| 5 | the programme's outcome is recorded as **not found** with everything searched (§7.6) | — | on miss |

Costs at Firecrawl Standard and Tavily pay-as-you-go, read 2026-09-22 and 2026-09-23.

**The stop rule.** A stage that finds the programme's **documents-list page** — a page D3 triages
as `documents-list` on which D4 selects at least one CV or letter requirement — and whose linked
documents have then been read, ends the search; a page that merely mentions a CV once does not.
Reading never stops: every page a stage finds is read in full. The rule decides only whether the
dearer stages are paid for. `FETCH_NAVIGATOR_POLICY` (§9.1) flips stages 3–4 from `on_miss` to
`always`; the corpus flips it, by running them on programmes that counted as found and counting
the rules the crawl missed. Each stage is scored on the corpus's exact-URL labels by itself, so a
stage that never finds a page the earlier ones missed is removed, not kept for comfort. A false
stop — a page triaged `documents-list` that the corpus says is not the programme's — is counted by
the corpus beside the misses, because the stop rule is only as good as D3's `documents-list` kind.

### 7.1 Inventory — `/map`

`POST /v2/map` with `search` set to the caller's term list (CV / résumé / application / documents /
requirements, in the site's languages — one list per reader, owned by the caller, never widened
inside the engine), `includeSubdomains: true`, `ignoreQueryParameters: true`, `limit: 500`, and
`ignoreCache: true` at the start of a cycle (Firecrawl caches sitemaps for seven days). **1 credit per
call whatever it returns.** An unfiltered map is the fallback when the filtered one returns nothing
— measured 2026-09-15, the filter can return zero for a site the unfiltered call maps at 76.

### 7.2 Rank

D2 of the typed-decisions design ranks the map — one closed question over the URL list, *which page
most likely states the documents an applicant must submit?* — with URL terms from that design's §8.1
additive vocabulary, the `links` array each fetched page returns (free, part of rung 1), and depth
from the landing page as tie-breakers. (Amended 2026-09-23; the 2026-09-22 text said "no model" and
the typed-decisions design assigned D2 the same day.) The rank decides the crawl's `includePaths` and the order of residue
fetches; it is what the corpus's *location precision* score measures.

### 7.3 Crawl — `/crawl`

`POST /v2/crawl` bounded on purpose:

- `includePaths`: **one short RE2 pattern per term** (Firecrawl's own guidance; a long alternation
  is rejected or slow), from the ranked term list; `excludePaths` for news, events, staff, login.
- **`crawlEntireDomain: true`.** The default follows children only, and a requirements page is
  usually a *sibling* of the programme page (`/msc-ai/` and `/application/documents/`). Without this
  the crawl never reaches the most common location the 2026-09-15 site survey found.
- `allowSubdomains: true` (admissions.*, apply.*); `allowExternalLinks: true` for the one-hop linked
  PDF on a CDN or a funder's site (external *homepages* are skipped by Firecrawl and reported as
  `EXTERNAL_LINK`).
- `maxDiscoveryDepth: 2`, `limit: FETCH_CRAWL_LIMIT` (25) per host per sweep, `sitemap: "include"`
  (`skip` misses PDFs listed only in the sitemap), `ignoreQueryParameters: true`.
- `scrapeOptions` exactly as rung 1, `changeTracking` included, so every crawled page is also a
  baseline for §8.
- `maxConcurrency` from configuration; **1 for corpus runs** (§13), because Firecrawl documents that
  crawl results vary between runs of the same configuration.
- `delay` from the profile for a host whose `robots.txt` names a crawl-delay.

Then **`GET /v2/crawl/{id}/errors`**, always. The status counters cannot say anything failed —
`completed == total` on every finished crawl because failed pages are excluded from both. `errors[]`
(network, timeout) and `robotsBlocked[]` are the only record; each URL in `errors[]` enters the
per-URL ladder at rung 3, each in `robotsBlocked[]` is written to the profile and never fetched by
any tier. A page the site answered with 404 is in `data`, not `errors`, with `metadata.statusCode`.

Credits: 1 per page, plus 1 per PDF page, so a host's ceiling is `limit × (1 + FETCH_PDF_MAX_PAGES)`
in the worst case and the sweep budget (§9) is checked against it before the job is submitted.
Firecrawl's own pre-flight rejects a `limit` the balance cannot cover with a 402.

### 7.3a Guided map — Tavily `/map` with `instructions` (candidate stage, 2026-09-23)

Read on 2026-09-23 from `docs.tavily.com`: `POST /map` takes `url`, `instructions` ("natural
language instructions for the crawler"), `max_depth` 1–5, `max_breadth` ≤ 500, `limit` (default
50), `select_paths` / `select_domains` / `exclude_paths` / `exclude_domains`, `allow_external`
(default true), and returns `results`, **a list of URLs** and nothing else. Two credits per ten
successful pages with instructions, one without; $0.008 a credit pay-as-you-go, $0.005 on the
Growth plan. The key is `SEARCH_API_KEY`, which `apps/research/providers/tavily.py` already holds.

The instruction is one sentence built from the same slots as the navigator's brief (§7.4): the
programme, its degree level and intake, the site's language and that language's words for CV and
motivation letter, and what to find — pages or files listing the documents an applicant must
submit, requirements on their length, language, format or template, guidelines and FAQ.
`select_domains` names the institution's and the funder's domains; `limit` is
`FETCH_GUIDED_MAP_LIMIT` (50).

**Two things the documentation does not say, so the corpus measures them before this stage keeps
its place:** how the instructions steer the walk, and whether PDF and document links appear in
`results`. It is a candidate because it is roughly a tenth of `/agent`'s price, returns the pointer
shape the funnel wants, and Tavily's terms are the cleanest on file (CLAUDE.md). If the hard subset
shows it finds what `/agent` finds, `/agent` drops to last resort; if it finds nothing the crawl
missed, it goes.

### 7.4 Navigator — `/agent` (amended 2026-09-23)

Runs under `FETCH_NAVIGATOR_POLICY` — on miss by default (§7.0). `POST /v2/agent` with:

- **`urls: [<landing page>, <site root>]`** as seeds. Read on 2026-09-23 from Firecrawl's `/agent`
  page: `urls` is "an optional list of URLs to focus the extraction" and the agent **can still use
  web search and navigate beyond those sites**; `strictConstrainToURLs: true` confines it to
  *exactly* the URLs given, which makes it useless for finding anything. So there is no "stay on
  the official site" setting, and the 2026-09-22 text that assumed one was wrong. **Owner decision
  2026-09-23: the agent may search the open web on its own.** What makes that safe is the funnel's
  rule, not a vendor flag: only URLs are taken from its answer, every one is fetched through the
  ladder and must pass `require_origin` against the institution's or the funder's site, and
  nothing else it produced is stored — the standing CLAUDE.md rule for Exa and Brave, whose
  upstream indexes we have likewise not read.
- **`prompt`** — the brief, one template with slots, under 10,000 characters: the programme's
  name, degree level, institution and intake year; the site's language(s) and, in them, the words
  for CV, résumé and motivation letter from the typed-decisions design's §8.1 vocabulary; **what
  to find** — pages or files listing the documents an applicant must submit, requirements on their
  length, language, format or template, application guidelines, FAQ; **where to prefer** — the
  institution's own domains and subdomains, then the named funder's, never aggregators or news;
  **what to return** — the URLs only, each with a `kind` (`documents_list`, `cv_guideline`,
  `letter_guideline`, `template`, `faq`, `other`) and a one-line `why`; and the instruction
  **not** to summarise the requirements, because we read them ourselves. Firecrawl's own note:
  "more specific prompts often use fewer credits."
- **`schema`**: `{pages: [{url, kind, why}]}`. **`effort: "low"`**. **`maxCredits:
  FETCH_AGENT_MAX_CREDITS`** (300) — **set explicitly**, because the documented default is
  **2,500** credits a run, about $2 at Standard. A webhook when one exists.

**Its answer is discarded.** The URLs in `data` and, where the trace exposes them, the URLs it
visited are deduplicated and fetched through the ladder; Firecrawl says the trace is "not a
page-by-page archive", so they are leads to confirm, never facts. Billing is dynamic — "most runs
consume a few hundred credits"; failed runs are free; five free runs a day — which at Standard is
twenty to forty cents, and why it runs on miss unless the corpus says otherwise.

**Why this and not an in-house navigator.** The owner's standing rule is buy before build. The
in-house harnessed agent approved on 2026-09-15 existed to *find pages*; `/agent` finds pages. What
it cannot do — be the source of a rule — it is never asked to do. The corpus (`docs/superpowers/specs/2026-09-23-labelled-corpus-design.md`) scores
it on the hard subset beside §7.3a; the in-house navigator is built only if that score says both
miss pages a person finds. Recorded as reversed by measurement, not by taste.

### 7.5 Screenshots

`formats` gains `screenshot` on exactly two occasions: the final attempt before rung 7, and rung 4
(scrape.do `screenShot=true`). The image goes to the evidence bucket under the snapshot's existing
`screenshot_object_key`, so whoever reads the ledger row later sees what the engine saw.

### 7.6 The four outcomes per programme

Each with evidence, never a bare label:

| outcome | evidence |
|---|---|
| **found** | the rules, each with its page, quote and (for documents) page number |
| **no CV required** | the sentence that says so, verified on the page like any other quote |
| **blocked or unreadable** | the trail — every rung, every reason, the screenshot |
| **not found** | what was searched: the map, the crawl's page list, the guided map's URLs, the navigator's leads — recorded on the programme, a ledger row nothing waits on (owner decision 2026-09-23) |

## 8. Refresh — one monitor per admissions cycle

`/v2/monitor` is the monthly change check. It is on the free plan and there is no per-monitor fee;
each check pays 1 credit per page scraped.

- **Targets:** a `scrape` target for every URL that yielded a rule; a `crawl` target per site with the
  same `includePaths` and `limit` as §7.3, so a *new* requirements page — not a change to any known
  URL — is reported as `new`. Up to 50 targets per monitor, so a site with more is split; monitors
  are named `<cycle>:<host>[:n]`.
- **Schedule:** cron `0 6 1 * *` (monthly, spread by Firecrawl across monitors). `retentionDays: 365`,
  one cycle.
- **Goal and judge: off (2026-09-23).** The reader a changed page wakes now costs about a tenth of
  a cent (typed-decisions §10), less than the 1-credit vendor judge that would decide whether to
  wake it, so `judgeEnabled: false` and every `changed` page is re-read. The typed-decisions
  design's D7 was removed the same day for the same reason.
- **What each status does:** `same` → nothing; `changed` → the reader; `new` → the
  ladder, then the reader; `removed` → a catalog review row; `error` → the per-URL ladder.
- **Delivery:** `monitor.page` and `monitor.check.completed` webhooks, HMAC-verified (§10), once a
  public HTTPS endpoint exists. Until then — nothing is deployed — `manage.py poll_monitor_checks`
  reads `GET /v2/monitor/{id}/checks` on the same 6-hour EventBridge rule as `retry_due_fetches`;
  polling costs no credits.
- **Budget:** the create call returns `estimatedCreditsPerMonth`; a monitor is created only if the
  sum across the cycle's monitors fits `FIRECRAWL_MONTHLY_CREDITS` minus the sweep reserve. A check
  skipped for credits is `skipped_no_credits`, not a failure, and resumes when credits do; the
  poller logs it as a budget event.

## 9. Cost

### 9.1 Configuration — one block, env-overridable, defaults are Standard + Hobby

In `config/settings/base.py`, beside `SEARCH_API_KEY`:

| setting | default | meaning |
|---|---|---|
| `FIRECRAWL_API_KEY`, `SCRAPEDO_API_KEY`, `FIRECRAWL_WEBHOOK_SECRET` | *(env only, no default)* | absent key → the provider raises at call time, never degrades silently |
| `FIRECRAWL_CONCURRENCY` | 25 | Standard's concurrent browsers; sizes `maxConcurrency` on crawl and batch |
| `FIRECRAWL_SCRAPE_RPM`, `FIRECRAWL_CRAWL_RPM` | 500, 100 | Standard's limits; size a sweep's pacing |
| `FIRECRAWL_MONTHLY_CREDITS` | 100,000 | Standard; the monitor budget check |
| `SCRAPEDO_CONCURRENCY`, `SCRAPEDO_MONTHLY_CREDITS` | 10, 250,000 | Hobby |
| `FETCH_SWEEP_CREDITS` | `{FIRECRAWL: 100, SCRAPE_DO: 500}` | per sweep, **per vendor** — a credit is not a unit across vendors (7.16×); master's shape, kept by the plan's reconciliation of 2026-09-23, raised by env when the paid tiers are bought |
| `FETCH_PDF_MAX_PAGES` | 60 | rung 1 `maxPages` |
| `FETCH_CRAWL_LIMIT` | 25 | pages per host per sweep |
| `FETCH_AGENT_MAX_CREDITS` | 300 | per `/agent` run |
| `FETCH_ARCHIVE_MAX_AGE_DAYS` | 365 | owner decision 2026-09-22 |
| `FETCH_REPROBE_DAYS` | 30 | §5 |
| `FETCH_NAVIGATOR_POLICY` | `on_miss` | §7.0: `on_miss` or `always` for stages 3–4; the corpus decides |
| `FETCH_GUIDED_MAP_LIMIT` | 50 | §7.3a; its key is the existing `SEARCH_API_KEY` (Tavily) |

Plan prices, for the record (read 2026-09-22): Firecrawl Standard $83/month billed yearly, $99
monthly, 100k credits, 25 browsers, extra credits 2,000 per $5; scrape.do Hobby $29/month, 250k
credits, 10 concurrent. Growth ($333–399, 500k, 50 browsers) and Pro ($99, 1.25M, 50 concurrent) are
the next tier — a change to five numbers above and nothing else.

### 9.2 The layers, outermost first

1. **Firecrawl's per-key spend limit** (credits per month, set in their dashboard, enforced by them)
   at the corridor budget. It survives a bug in our accounting; nothing below does.
2. **`FETCH_SWEEP_CREDITS` per sweep and per vendor**, held in the sweep's process. Checked *before* every call; a
   call that would exceed it is `BUDGET`, never a 402 we cannot read. A sweep runs in one task, so a
   process-local counter is exact for it; across tasks the key limit is the guarantee.
3. **Remaining-credit floors** — `Scrape.do-Remaining-Credits` on every response, Firecrawl's
   credit-usage endpoint at sweep start. Below the floor, `BUDGET`.
4. **Per-host ledger** — `credits_30d` in the profile. A host over its expected multiple of the sweep
   average is logged, and the scrape.do per-domain surcharge (10–200 credits, server-side, no
   request-time signal) is caught here. Read in full on 2026-09-22: every surcharged domain is
   e-commerce, SERP, social or classifieds — none of our population — so this is a guard, not an
   expectation.
5. **Per-call caps** — `maxPages`, crawl `limit`, agent `maxCredits`, the monitor's
   `estimatedCreditsPerMonth`.

### 9.3 Idempotency and back-pressure

- Every attempt carries an `x-request-id` (the `FetchAttempt` id). Firecrawl answers 409
  (`duplicate_request` / `request_in_flight`) for a repeat, so a retry after a client-side timeout
  cannot be charged twice. scrape.do has no equivalent; its failed requests are free, so the exposure
  there is one successful duplicate, logged by the ledger.
- A 429 from either vendor backs off exponentially (1 s, 2 s, 4 s … 60 s) and never counts as a
  block. `metadata.concurrencyLimited` with a long `concurrencyQueueDurationMs` halves the batch
  size for the rest of the sweep. **No distributed semaphore:** the vendors queue over-limit work
  themselves, and a counter shared across ECS tasks would be a second implementation of what they
  already enforce.
- Monthly reconciliation: `sum(FetchAttempt.credits)` against the credit-usage endpoint; a gap over
  5% is logged as a defect in our accounting, not a vendor's.

## 10. Safety — restated, nothing relaxed

Every vendor result is untrusted exactly as the page it came from was.

- `validate_public_url` on the final URL of every fetch. **Amended 2026-09-22, measured:** scrape.do
  follows a redirect chain for one credit and names the final URL in `Scrape.do-Resolved-Url`;
  disabling redirection costs one credit per hop and the standard `Location` header is not passed
  through. Hop-by-hop validation existed because *our* network was fetching; the vendor's hops run
  on the vendor's network, and provenance needs the *recorded* URL to be public and on the required
  origin — which validating the resolved URL gives. Firecrawl reports its own final URL in
  `metadata.url`, validated the same way. A final URL that resolves inside the VPC, or carries
  credentials, is `INVALID`.
- `require_same_origin` where the caller demands provenance (`require_origin`), before any bytes are
  persisted — an off-site final URL is `OFF_SITE`, and its bytes reach neither the model nor the
  evidence bucket.
- The existing content-type allowlist and 10 MiB cap apply to vendor bodies. `markdown` is capped at
  the reader's own limit with the overflow warning it already emits.
- `checkPromptInjection: true` on every `json`-format read (§4.4 of the older spec). The reader's
  "content is data, not instructions" labelling is unchanged and still the real defence.
- Keys and the webhook secret from the environment only; never a settings default. Webhooks:
  `X-Firecrawl-Signature` is HMAC-SHA256 of the raw body; verified with `hmac.compare_digest`; 401 on
  mismatch; 2xx within 10 s; Firecrawl retries three times at 1 / 5 / 15 minutes.
- **No vendor ever fetches europa.eu, a contracted API, or a portal.** A test asserts that every
  `FetchAttempt` host is outside those sets, and that `fetched_via == "EGRESS"` occurs only for
  `europa.eu`.
- Screenshots and DOM objects go to the evidence bucket under the snapshot, with the retention the
  bucket already has.
- `robots.txt`: respected by Firecrawl's crawl and not switchable (`ignoreRobotsTxt` is
  Enterprise-only); the profile records what it refused. On single-page fetches it is the vendor's
  question, as CLAUDE.md records the owner deciding on 2026-09-18.

## 11. Data

Two new tables, both **shared catalog** — they describe the web, not a person — under the RLS
pattern of `apps/funding/migrations/0030_program_awarding_institutions_rls.py`: `ENABLE ROW LEVEL
SECURITY`, `shared_catalog_select`, `catalog_ingestion_write`, written by the same role that writes
`OfficialSourceSnapshot` today. Per CLAUDE.md, verify the policies against the `runtime_connection`
fixture, not the test role.

- **`research.HostProfile`** — §5's fields; `host` is the primary key.
- **`research.FetchAttempt`** — `id` (UUID, doubles as `x-request-id`), `url`, `host` (FK), `purpose`,
  `rung`, `vendor` (`FIRECRAWL | SCRAPE_DO | ARCHIVE | EGRESS`), `params` (the request options, keys
  redacted), `status_code`, `content_type`, `byte_size`, `credits`, `duration_ms`, `outcome`,
  `reason`, `final_url`, `sha256`, `change_status`, `captured_at`, `page_count`, `total_pages`,
  `retry_after`, `attempt_no`, `sweep_id`, `created_at`. Indexes on `(url, created_at)` and `(outcome, retry_after)`.

Existing snapshot fields are **reused, not duplicated**: `retrieval_status` ← §6's mapping;
`render_status` ← `FIRECRAWL:1 | FIRECRAWL:2 | SCRAPEDO:3 | SCRAPEDO:4 | ARCHIVE:<date>`;
`discovery_technique` ← `MAP | CRAWL | AGENT | LINK | SEED`; `screenshot_object_key` ← §7.5;
`unreadable` ← `UNREADABLE`. `redirect_chain` keeps every hop as today.

`ConsultantResearchTask` is unchanged. One defect in `record_blocked_source` is fixed on the way,
because the engine depends on it: `get_or_create(url, state=OPEN, defaults={"reason"})` keeps the
*first* reason forever (OPEN observation 2026-09-16). The engine updates `reason` to the latest
outcome on every call; the trail holds the history.

## 12. Capability coverage — every documented capability, placed

**Used.**

| capability | where |
|---|---|
| Firecrawl scrape: `markdown`, `links`, `rawHtml`, `changeTracking` (git-diff, tagged), PDF parser (`maxPages`, `pageMarkers`, OCR `auto`), DOCX/XLSX/PPTX/EPUB/CSV by URL, `skipTlsVerification`, `blockAds`, `onlyMainContent`, `timeout`, `waitFor`, `actions` (wait, scroll), `proxy` default `auto`, `metadata.url` / `statusCode` / `numPages` / `totalPages` / `concurrencyLimited`, `warning` | rungs 1–2, §3, §9.3 |
| `screenshot` format; scrape.do `screenShot` | §7.5 |
| `parsers: []` (base64, 1 credit flat) | a PDF's bytes for a digest without paying per page |
| images through `/scrape` and `/parse` (1 credit) | **measured 2026-09-22, and the result is two-faced**: a clean text image is OCR'd (Turkish exact; Russian 75% of words; Azerbaijani 86%; Georgian unreadable), but a *photograph* of a sign came back as a model-written **caption** — `![A wooden sign with ... "SiGARA İÇMEK YASAKTIR" ...]()` — a paraphrase that happens to quote the text. Which mode fires is not ours to choose. So an image is fetched at rung 1 like any artifact and its markdown is stored, but **a rule is never derived from it until §15's OCR trigger fires**; until then an image that reads as rule-bearing is a note on the document with the image itself (typed-decisions §6.4) |
| `/v2/parse` (upload, 50 MB) | ZIP members via `zipfile`; the corpus's local files |
| `/v2/map` (`search`, `sitemap`, `includeSubdomains`, `ignoreQueryParameters`, `ignoreCache`, `limit`) | §7.1 |
| `/v2/crawl` (`includePaths`, `excludePaths`, `crawlEntireDomain`, `allowSubdomains`, `allowExternalLinks`, `maxDiscoveryDepth`, `limit`, `sitemap`, `ignoreQueryParameters`, `delay`, `maxConcurrency`, `scrapeOptions`, `webhook`), `GET /crawl/{id}/errors` | §7.3 |
| `/v2/batch/scrape` | re-reading a known URL list with `changeTracking` outside the monitor cadence (a deadline-week re-check) |
| `/v2/monitor` (`scrape` and `crawl` targets, cron, `goal`; `judgeEnabled` off — §8; `retentionDays`, `estimatedCreditsPerMonth`, checks API, `monitor.page` / `monitor.check.completed`) | §8 |
| `/v2/agent` (`urls` as seeds, its own web search, `prompt`, schema, `maxCredits` set explicitly, `effort`, trace and snapshots, webhook) | §7.4 |
| Tavily `/map` with `instructions` (URLs only) | §7.3a, candidate |
| webhooks + `X-Firecrawl-Signature`; credit-usage endpoints; per-key spend limits; `x-request-id`; 402 / 409 / 429 semantics | §9, §10 |
| scrape.do: `render`, `super`, `geoCode`, `sessionId`, `waitSelector`, `customWait`, `playWithBrowser`, `blockResources`, `transparentResponse`, `disableRedirection`, `timeout`, async API (its own 30% concurrency pool), `Scrape.do-Request-Cost`, `Scrape.do-Remaining-Credits`, free-on-failure | rungs 3–4, `purpose="bytes"`, batch residue, §9 |
| Internet Archive availability API and `id_` raw captures | rung 6 |

**Off, each with the reason.**

| capability | reason |
|---|---|
| `summary`, `question`, `highlights`, `onlyCleanContent`, `changeTracking` `json` mode, `branding` / `product` / `menu` | a vendor model choosing or rewriting text is a reading we cannot verify by code; the schema-bound `json` read of §4.4 is the one model read this path allows, and it is quote-verified |
| Firecrawl `/search` and the developer-index search as *discovery* | the upstream index's terms have not been read; `/agent`'s own search is allowed since 2026-09-23 under the URLs-only rule (§7.4), which is the same standing Exa and Brave have |
| `/extract` | superseded by `/agent` per Firecrawl; billed at 15 tokens per credit; the hub-harvest role is measured against crawl + JSON read before it keeps anything |
| `location` by default; custom `headers`; `mobile`; `profile`; `redactPII`; `zeroDataRetention`; `lockdown`; `maxAge` / `minAge` / `storeInCache`; crawl `prompt`; `ignoreRobotsTxt` / `robotsUserAgent`; `threatProtection` / `auditMetadata` | per host only / a browser identity would undo the vendor's own / no logins / no PII on this path / cache irrelevant and never a cost lever (cached scrapes still cost 1 credit) / nondeterministic configuration / Enterprise-only and never / Enterprise |
| PDF `pages` and `blocks` | free, but `pageMarkers` already gives the page number a quote needs; `blocks` (bounding boxes) is for highlight overlays nothing here draws |
| scrape.do `output=markdown`, `returnJSON`, `showFrames`, `showWebsocketRequests`, `customHeaders` / `extraHeaders` / `forwardHeaders`, `setCookies`, `pureCookies`, `regionalGeoCode`, `device`, `width` / `height`, `fullScreenShot`, `particularScreenShot`, proxy mode, deprecated `callback` | its markdown converts `<head>` (measured); iframes and consent cookies only through `vendor_options` when a host is measured to need them; no header or identity games; we are not a browser |
| Firecrawl MCP server, keyless tier, playground, CSV agent batches | not a production surface |

## 13. Testing and the gates

- **Unit:** every provider module takes an injected transport, as the 2026-09-19 plan already had it;
  the ladder is tested with a scripted vendor that answers each rung in turn, asserting the rung
  order, the outcome, the credits, and that no call is made past a `BUDGET`.
- **Negative controls:** a test that a stubbed 200-with-469-bytes is a block, not `FETCHED`; that a
  404 is `DEAD` at rung 1 with exactly one attempt; that an off-site hop is `OFF_SITE` with no
  snapshot; that `europa.eu` never reaches a vendor.
- **RLS:** both tables verified through `runtime_connection` — the test role bypasses RLS and
  proves nothing (CLAUDE.md).
- **Live gate, `-m live`:** a fixed hard-host list — the nine hosts our client refused on
  2026-09-19, the three shell pages (Türkiye Bursları, Sciences Po, JASSO), DAAD PRIME, a PDF over
  60 pages, a ZIP with a `.docx` inside, one geo-gated page — asserting the outcome **class** per host
  and a credit **ceiling** per outcome (`FETCHED` ≤ 1 + PDF pages; `BLOCKED` ≤ 1 + 1 + 25 + retries;
  `ARCHIVED` ≤ 3), never content. Runs deliberately, excluded by `addopts = "-m 'not live'"`.
- **Corpus:** the labelled corpus's live discovery gate (`docs/superpowers/specs/2026-09-23-labelled-corpus-design.md`) scores found-on-any-of-N runs,
  N recorded, with `maxConcurrency: 1` — because crawl results vary between runs and set equality
  has failed three designs on this repo already.

## 14. What this replaces, and what is deleted

Carried over unchanged from the 2026-09-19 plan: the deletion of `fetch_official_source` and its
redirect loop, `render_with_scrapling`, `browser_fetch_options`, `render_via_browser_service`,
`apps/research/browser_server.py`, every `Browser*` resource in `infra/template.yaml`, the Dockerfile
`browser` stage, and `scrapling[fetchers]` from `pyproject.toml` — with the same three exceptions
(europass's `_request`, `fetch_json_api`, and `LocalEgressProxy`, which leaves with the portal
deletion). `readable_text` keeps its section selection: it reads the vendor's `rawHtml` for HTML and
the two bugs recorded on 2026-09-22 (the 24k cut, the dropped "REQUIRED DOCUMENTS" block) are fixed
in it, not around it.

Superseded text stays in place as the record, marked: §4.0–§4.1c of the older spec, and §4.1d item 1
as amended in §3 above.

## 15. Deliberately not built, with the trigger that would build it

| not built | trigger |
|---|---|
| a distributed concurrency semaphore | measured 429 storms across concurrent ECS tasks that the vendors' own queueing does not absorb |
| the in-house harnessed navigator | the corpus's hard subset shows both `/agent` and the guided map (§7.3a) missing pages a person finds |
| keeping `/agent`'s structured answer as an unverified hint for the human queue | a person in the resolution queue asks for it |
| a second archive source (archive.today) | a host that matters has no Wayback capture within the window |
| **reading a rule out of an image.** Measured 2026-09-22 on the same images, same prompt ("transcribe verbatim, do not describe"): **Claude Sonnet 5 and `gpt-5.6-luna` both transcribed two photographs of Turkish signs verbatim** — including a handwritten line under one — and read a clean render at 100% of characters in Chinese, Korean, Russian and Turkish and 98–100% in Georgian and Armenian, the two scripts Firecrawl's OCR cannot. They disagreed once, on small background text (`KADIKÖY` vs `KARŞIYAKA BELEDİYESİ`). AWS Textract is out on its own quotas page (English, French, German, Italian, Portuguese, Spanish; Latin characters only — read 2026-09-22). **Design when built:** the image is the snapshot; two vision readings from the two families the judge already uses, plus Firecrawl's OCR markdown as a free third; a sentence is a candidate rule only where it appears verbatim (Unicode-normalised) in **at least two of the three** — code-checked agreement standing in for "verified against origin bytes", since the origin is pixels; every rule carries `source_kind=image` and the object key; a sentence only one reading produced is a note on the document with the image (typed-decisions §6.4). Same limit as the judge: two model families share biases, and a unanimous wrong reading never abstains. **Candidates to measure before adding any of them, when the trigger fires:** a Chinese OCR or vision model as a third, differently-trained reading (Qwen3-VL or DeepSeek-OCR through an API; PaddleOCR self-hosted as the deterministic option — no key for any of these exists on this machine today, so none was measured); Google Cloud Vision `DOCUMENT_TEXT_DETECTION` as a deterministic verifier with per-line confidence. Adopted only if the corpus's images show the two-of-three rule abstaining too often. | the labelled corpus records a CV rule that exists **only** in an image (a ministry's announcement poster). The site survey to date found rules in HTML, PDF, DOCX and ZIP — none in images — so this is a measured absence, not an oversight |
| per-host language negotiation beyond `languages` in the profile | a page measured to serve different requirements by `Accept-Language` |
| a UI over `HostProfile` | the owner console needs it; until then `manage.py` and the admin |

## 16. Open questions

- **Internet Archive terms for automated retrieval at this volume.** Rung 6 runs only for hosts that
  block us — tens of fetches a cycle, not thousands — and the owner's 2026-09-18 position is that
  `robots.txt` and TDM are the fetching vendor's question. Here the vendor fetches the archive on our
  instruction, so the question is ours to ask once; it does not block the engine.
- **Firecrawl's DPA.** The free plan has none; paid self-serve plans are not stated either way. No
  personal data travels this path, so it is not required for it; it becomes a question the day any
  fetch carries a student's data, which no design permits.
- **`/agent` in Research Preview.** Its pricing "is subject to change"; the ceiling is
  `FETCH_AGENT_MAX_CREDITS` and the per-key spend limit. Re-read its page before the plan that wires
  it. **2026-09-23:** its page was re-read (§7.4) and its open-web search is permitted under the
  URLs-only rule; still Research Preview.
- **Firecrawl's image handling is undocumented and two-faced** (§12): OCR for clean text images
  (measured 2026-09-22: Chinese, Japanese, Russian and Turkish at 100% of characters, Korean 96%,
  Georgian unreadable), a model caption for photographs, with nothing in the request that selects
  one. Until they document it, image markdown is a hint and never a rule source on its own — it is
  the free third reading in §15's two-of-three rule.
- **The Sciences Po archive capture of 2026-09-15 could not be reproduced on 2026-09-22.** The
  availability API found nothing under four URL forms while the CDX index answered "Temporarily
  Offline" throughout; DAAD's 2026-06-25 capture *was* reproduced, under the bare `host/path` form
  only. Whether Sciences Po's capture exists under another URL, or the index was degraded, is
  unknown; the live gate accepts `BLOCKED` for that host until it is.

## 17. Implementation plans

Two, in order; the corpus spec proceeds in parallel and uses the first the day it lands:

1. **Engine core** — the seam, rungs 1–7, `HostProfile` and `FetchAttempt` with their RLS
   migration, the configuration block, `retry_due_fetches`, the `record_blocked_source` fix, the
   unit and live gates, and the deletion of the old fetch path. Every reader gains the outcome trail
   without changing.
2. **Site jobs and refresh** — the funnel (§7.0): map, D2 rank, crawl and its errors endpoint, the
   guided map, the navigator with its brief and policy, the stop rule and the four programme
   outcomes as ledger rows; monitors per cycle, `poll_monitor_checks`, and the webhook receiver behind a
   feature flag until a public endpoint exists.

## 18. What merging the engine core changes for an existing caller

Written at the close of plan 1 (2026-09-24), in the spec rather than in a session file, because a
merge note is only useful to whoever reads the code afterwards. Three things a reviewer will
otherwise read wrongly.

**`research_fit`'s `unreadable` → `fetch_failed` RESTORES master's labelling; it is not a change.**
`pages.fetch_page` catches everything `retrieve_official_source` raises and returns `fetch_failed`,
and on master `fetch_page` already raised, so a refused fetch was already `fetch_failed` there.
Tasks 1–8 briefly broke that — the engine returns refusals as values, so a refusal arrived as a
page the shell check then labelled `unreadable` — and Task 9 put it back by keeping
`retrieve_official_source` a raising boundary. The distinction is load-bearing for the counselor:
`unreadable` and `off_domain` mean the page was reached and the citation is stale, `fetch_failed`
means it was never read. **This error has been made once already and corrected. Do not "fix" it a
second time by describing the restoration as a regression.**

**`FetchBudgetExhausted` reaching `pipeline.py` files a consultant task per remaining lead.** It
subclasses `SourceBlocked`, and the sweep loop's `except (SourceBlocked, DomainBusy, ValueError)`
calls `_open_task` and continues — so a budget exhausted mid-sweep queues a human on every lead
left in the run, each with a reason that names the budget rather than the host. This is
**pre-existing on master** and is not introduced here; what changed is where it originates. It now
comes from `fetch_page`'s `BUDGET` outcome one layer further out, which also means the
`FetchAttempt` row carries a `retry_after` the old path had nowhere to put. `manage.py fetch_ladder`
catches `FetchBudgetExhausted` *before* `SourceBlocked` and ends the sweep, which is what
`pipeline.py` should eventually do too; deciding that is a sweep-shape question and belongs to plan
2, not here.

**A successful rung-5 retry discards the page.** `retry_due_fetches` re-enters the ladder and stops
at the fetched page: no snapshot is persisted, no reader is re-run, no consultant task is closed.
The retry warms the `HostProfile` and closes the ledger row, and the caller that originally needed
the page fetches and pays for it again. This is owed work, documented deliberately rather than
fixed: delivering the page means deciding whose `OfficialSource` the retry's snapshot belongs to —
a provenance question (CLAUDE.md, "Decision B vouches for the SOURCE ROW, not the BYTES") — and the
worker runs with no tenant and no knowledge of which caller's read the original fetch was serving.
It must not settle that alone. Note that the cost of leaving it is currently zero: the rule that
would run the worker ships `DISABLED` (§ the runbook's "The catalog_ingestion role the fetch engine needs"), so no retry runs at all.
