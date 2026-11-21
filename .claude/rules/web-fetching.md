---
paths:
  - "apps/research/**"
  - "tests/research/**"
  - "apps/documents/europass.py"
  - "apps/documents/research_fit/**"
  - "tests/documents/research_fit/**"
  - "apps/watch/**"
---

## Web fetching

**Every research page fetch goes through one seam: `apps/research/fetch.fetch_page`.** It walks a
ladder of vendor rungs — Firecrawl, then scrape.do, then the Internet Archive — and never our own
egress. Tavily is not a rung: it lost the fallback-vendor role to scrape.do on 2026-09-19 and keeps
`/search` (`SearchSource`, `tavily_site_search`), `/map` and name-to-site resolution. One operator
command, `pool_cv_corpus`, still reads pages through Tavily `/extract`/`/crawl`, outside this seam. `robots.txt`/TDM
reservations and content retention are the fetching vendor's questions, not ours (owner decision
2026-09-18); aggregator pages are fetched for organisation names only, never as provenance. Design:
`docs/superpowers/specs/2026-09-22-fetch-engine-design.md`. The tier order and the cost measurements
behind it:
`docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` §4.

**The funnel, 2026-09-23.** Finding a programme's requirements pages is five stages, cheapest
first — the page's own document links, `/map` + D2 rank + `/crawl`, Tavily's guided `/map`,
Firecrawl `/agent`, then the recorded outcome — and `apps/research/sitejob.py` owns the order.
**Every stage returns URLs only**; each is fetched through the ladder and `require_origin`-checked,
which is what makes `/agent`'s open-web search safe rather than any vendor flag
(`strictConstrainToURLs` confines it to *exactly* the seeds and makes it useless). **The trap:
`GET /v2/crawl/{id}/errors` is read on every crawl and is not optional** — `completed == total`
on every finished crawl because failed pages are excluded from both counters, so a crawl read
from its status alone reports a perfect run over a site it half-read.

| rung | call | bought when | cost |
|---|---|---|---|
| 1 | Firecrawl `POST /v2/scrape` — `formats: ["markdown", "links", "html"]` plus `changeTracking`, a PDF parser at `FETCH_PDF_MAX_PAGES`, `blockAds`, `skipTlsVerification`, `onlyMainContent: False`, **no `proxy`** (deprecated; `auto` is the default and escalates to the enhanced proxy on 401/403/429 at no extra charge) | always, unless the host profile starts higher | 1 credit — **a PDF costs one per parsed page** (`firecrawl.py`: `credits = page_count`) |
| 2 | rung 1 plus `actions` (wait, scroll, wait) | rung 1 returned a **shell** | a browser-minute |
| 3 | scrape.do `render=false&super=false` | rung 1 got no document | 1 credit |
| 4 | scrape.do `render=true&super=true`, `sessionId` fixed per host | **only** an escalating failure — see the two questions below | 25 credits |
| 5 | the retry queue: a `FetchAttempt` row carrying `retry_after`, replayed by `manage.py retry_due_fetches` | rungs 1–4 all failed; three rounds, then rung 6 | free — **a `DISABLED` schedule; see below** |
| 6 | the Internet Archive capture (`web.archive.org/web/<ts>id_/<url>`), fetched through scrape.do | the three retry rounds are spent | scrape.do's |
| 7 | a person | — | **the ladder does not do this.** `fetch_page` deliberately never calls `record_blocked_source`: that row is tenant-scoped under FORCE RLS and the catalog read runs **tenantless**, where `current_tenant_id()` raises, so a bare call would crash every catalog read of a blocked page. The discovery pipeline turns a BLOCKED/UNREACHABLE/UNREADABLE refusal into one HOST_UNREACHABLE resolution-queue item (`resolution/writers.py::file_host_unreachable`); every other refusal goes to the run's `degraded` list. |

**Rung 5 of the fetch ladder has a schedule, and it stays off.** `manage.py retry_due_fetches` runs
from `RetryDueFetchesRule` in `infra/template.yaml`, still `State: DISABLED`. It shipped disabled
because `WorkerTaskDefinition` ran as `runtime`, which `HostProfile`/`FetchAttempt`'s write policy
did not name — so the reschedule `UPDATE` matched zero rows in silence (failure mode 1) and the
first `fetch_page` died on "new row violates row-level security policy". That reason is gone
(2026-09-25): the worker now runs as `runtime_engine`, the role those policies name. It stays
`DISABLED` for a different reason — `retry_due_fetches`'s own docstring says a successful retry
persists no snapshot, re-runs no reader and closes no task, so the caller that originally needed
the page still fetches and pays for it again. Enabled on a six-hour schedule, that spends vendor
credits every run for a result nothing downstream receives. Enable when a retry hands its
delivered page to the caller that needed it.

**`Outcome` has twelve members — eleven terminal plus `RETRY_SCHEDULED` — and `fetch_page` returns
every one of them rather than raising.** That is the reason the engine exists. Before it, a blocked
fetch and a page that genuinely states nothing arrived at the reader as the same thing, and this
file records the repo meeting that failure twice (the markdown body, and the JS shells). A refusal
now carries the rung that earned it, the reason, and the whole attempt trail. Only a programming
error leaves `fetch_page`.

**The one place values become exceptions again is `discovery.retrieve_official_source`, and it is
the boundary on purpose.** All eight callers of it predate the engine and are written against a
raised `SourceBlocked`, so an unserved outcome becomes one there — a refusal returned to them
instead would arrive as an *empty success*, the worst failure documented in this file. New code
calls `fetch_page` and reads `page.outcome`. What the translation collapses — which rung answered,
what it cost, whether a retry is already scheduled — survives on the `FetchAttempt` rows.
`UNCHANGED` is served, not refused: Firecrawl builds it from the same payload as a `FETCHED` page,
body and all, and the reader's digest short-circuit needs those bytes.

**Every `fetch_page` call writes a `FetchAttempt` — on every rung — and every terminal one writes a
`HostProfile`, and both tables are writable only by `runtime_engine`** (`runtime_engine_write`,
repointed from `catalog_ingestion` by `apps/funding/migrations/0049_catalog_grants.py`). Until
2026-09-25 that role could not log in, so every fetching command ran under
`DATABASE_ROLE=migration`; that stopgap is over — every worker task definition runs as
`runtime_engine`. Under `runtime_web` the first rung fails with `permission denied`, on purpose: a
student-facing fetch queues to the worker. **No superuser test sees the RLS half of this; the
`role_connection` fixture does.**

**`HostProfile` remembers only expensive rungs, and only ever downward.** Success at rung 3 or 4
writes `start_rung`; success at rung 1 or 2 *resets* it to 1. A memory that can only entrench a cost
is a tariff, not a memory — so a host with `start_rung > 1` and a `last_probe_at` older than
`FETCH_REPROBE_DAYS` is tried once from rung 1 first. A `BLOCKED` outcome sets a cool-off that
doubles from six hours and stops at a week; anything carrying bytes clears it.

**Social hosts are a third path, and the rule reversed on 2026-09-24.** They were not fetched at
all; they are to be read through **Browser Use** (decided 2026-09-24; not built, nothing in `apps/` calls it) (`browser-use.com`, remote browsers on the vendor's
own infrastructure, $0.02/browser-hour, agents at model cost + 20%). **Owner decision, taken on
their lawyer's advice** — Meta's terms §3.2(3) still forbid automated access "without our prior
permission", and Browser Use's own Terms bar "data mining, robots, scraping", place compliance
solely on the customer and carry an indemnity; the owner took counsel with those clauses stated.
The advice moved, not our reading of the terms. What did **not** change, because none of it rested
on the terms:

- **A social post is a pointer, never provenance.** `facebook.com`, `instagram.com`, `x.com`,
  `linkedin.com`, `bsky.app` stay on `AGGREGATOR_DOMAINS`, so `is_catalogue` still refuses them as
  catalog rows. They give a **name and a link**; the origin is fetched and verified; the claim
  cites the origin.
- **Nothing about a person is ingested** — commenters, reactors, followers and subscriber lists
  are discarded at the boundary.
- **No vendor is ever pointed at a portal.** Browser Use reads public pages, exactly as Firecrawl
  and scrape.do do. `apps/portals/` still hands a CAPTCHA to a human, because that rule is about
  circumventing an access control on an authenticated system and was never about cost or terms of
  fetching (see `.claude/rules/portals.md`, "Application automation").

Master design §6.4 carries the full record, including the superseded text.

**What lands in `FetchedPage.body` is HTML, and that is not a preference.** Firecrawl is asked for
html alongside markdown (rung 1, above) with `onlyMainContent: False`, and the **html** is
what becomes the body at `content_type="text/html"`. Three consumers parse markup off that body —
`harvest.anchors` (every `HtmlCatalogue` in `seeds.py`, and the aggregator hop in `harvest.py`),
`reader.readable_text` and `harvest.content_digest` — and
markdown has no `<a href>` and no `<main>`. Shipped once as markdown, it cost: EACEA and
DAAD yielded **zero leads in silence** (the run reports success, `blocked` equal to the lead count),
every AGGREGATOR lead became "no official programme link", and `content_sha256` was permanently
empty, so the unchanged-page short-circuit never fired — **six model calls per `read_program_page`,
every run**, which is the opposite of what `changeTracking` was bought for. The whole suite passed,
because every test stub returned HTML. `onlyMainContent` must stay **False**: anchor harvesting reads
exactly the navigation links it strips, and `readable_text` does its own main-content narrowing
anyway. Both formats cost the same one credit; only the JSON format adds 4.

**scrape.do reports the URL it landed on, in `scrape.do-resolved-url`, and that is what
`final_url` is.** Redirection is left on, the header is read through the existing case-insensitive
lookup, run through `validate_public_url`, and **absent is a failure, never a fallback to the
requested URL** — the same rule Firecrawl's `metadata.url` gets, for the same reason: falling back
asserts "it did not move" on the one response carrying no evidence for it, which is exactly what
`reader.require_same_origin` then checks. So that guard compares two real origins on both tiers. The initial status is still read, for
the log only. **The limit, exactly:** for HTTP redirects the resolved URL is the landed location;
for a meta-refresh or a JS navigation under `render=true` it is *plausibly* the browser's final
location — undocumented, unmeasured, and not to be written down as closed.

**A vendor failure answers one of two different questions, and the router acts on which.** Both
`VendorUnavailable` and `ChargedFailure` carry `escalate`. *"This host beat us"* — Firecrawl's
HTTP 200 + `success: false` ("all scraping engines failed"), a relayed 403, its own 408 — earns the
25-credit residue tier, because that is what the residue tier is for. *"Not now"* — an outer 429, a
5xx, a dropped connection, a 402 — does not: the host was never asked, so a second vendor answers a
question about **us**. Firecrawl's free tier is 10 requests/minute and a `discover` sweep paces per
**domain**, so 58 distinct hosts go out at 30–60/minute; before this, most of that sweep 429'd and
**every 429 spent 25 credits on a page Firecrawl would have served for 1 a minute later**. The
provider now backs off and retries instead, reusing `egress._backoff_seconds` / `_RETRY_ATTEMPTS`
(`Retry-After` honoured) rather than a second implementation, and the message says "vendor
throttled, retry later" because `pipeline.py` reports it verbatim in the run's degraded list. A dead link is
the same mistake from the other end: Firecrawl bills 1 credit for a target 404, and **scrape.do's
published billing counts 2XX, 400, 404 and 410 as *successful* requests**, so escalating one costs
1 + 25 credits and returns a 404 page. 404 and 410 do not escalate; 403, 401, 429 and 5xx do.

**A sweep's credit ceiling is checked AFTER the vendor reports the cost, so it is an alarm and not
a guard.** scrape.do's per-domain multiplier (10–200 credits) is applied server-side and is not
knowable before the request, so `SweepBudget.spend` records the overspend and the *next* rung's
`check` is what stops the ladder — one surprise lands, once per sweep rather than once per page.
**The control that cannot be outrun is configuration, not code: a per-key credit spend limit set in
each vendor's dashboard** (`docs/runbooks/deploy.md`). It survives a bug in `SweepBudget`; nothing
in the codebase does. Every figure the ladder uses is a setting with an env override
(`FETCH_SWEEP_CREDITS`, `FETCH_MAX_RETRIES`, `FETCH_RETRY_HOURS`, `FETCH_REPROBE_DAYS`,
`FETCH_PDF_MAX_PAGES`, `FETCH_ARCHIVE_MAX_AGE_DAYS`, `FETCH_BUDGET_RETRY_HOURS`).

Four things keep a first-party transport instead of a vendor, each for its own reason:

- **`apps/documents/europass.py` (europa.eu).** It POSTs a student's name, date of birth,
  education and employment history in a four-call stateful cookie/XSRF session — not a page a
  fetcher scrapes once. Its transport resolves the host, then connects to the *validated address*
  with `assert_hostname`/`server_hostname` pinned and `redirect=False`, closing the
  DNS-rebinding window on the one path carrying student PII. No vendor session could carry this,
  and none is asked to.
  **`fetched_via="EGRESS"` — the label that names our own client — is held to this one host by two
  tests** in `tests/research/test_fetch_ladder.py`: no page *carrying bytes* leaves the ladder
  labelled EGRESS (the refusals are labelled EGRESS on purpose — `FETCHED_VIA` admits no "nobody",
  and a page with no bytes has no provenance to lie about), and only four code sites in `apps/` may
  mint the label at all, checked by an `ast` walk over every assignment, annotated assignment and
  call keyword named `fetched_via` — not a regex, which a reviewer showed passing on the same label
  spelled with single quotes. Its one residual gap: an *indirect* assignment through a module
  constant (`fetched_via = _SOME_LABEL` where `_SOME_LABEL = "EGRESS"` is defined elsewhere) is
  invisible to it, because the walk only inspects the expression written at the `fetched_via` site,
  never a name's definition elsewhere in the file. Both structural and runtime halves are needed:
  `snapshot.persist_snapshot` copies `fetch.fetched_via` onto the snapshot row unexamined, so a new
  first-party rung would inherit `FetchResult`'s default and write a true-looking provenance row
  that no downstream assertion could catch.
- **`egress.fetch_json_api`.** Contracted APIs carrying our own keys — not content a vendor
  should see or bill for extracting.
- **`egress.fetch_data_file`.** **XML sitemaps** (`search.sitemap_urls`), RDAP answers (`rdap.py`), register
  CSV/XLSX files (`provenance_job.py`) and the Wayback availability probe (`fetch/archive.py`).
  Firecrawl hands back markdown or its own processed HTML, and neither is a data
  file; scrape.do's `output=markdown` does the same and cannot be told not to. A file meant to be
  parsed as data is fetched as bytes, not read as a page. The sitemap case is measured, and its
  failure mode is worth knowing because it is not the obvious one: Firecrawl's `html` for
  `globed.eu/sitemap_index.xml` is a **browser-viewer wrapper** — the XML declaration turned into an
  HTML comment and the root wrapped in `<html><body>`. It does not fail to parse. It parses with
  root tag `html`, so `search._sitemap`'s index hop never fires, it returns the child sitemap
  *files* as if they were content URLs, the funding-path filter drops every one of them, and
  `EntityExpansionSource` yields **zero programme URLs per organisation while reporting success**.
  Never unwrap a vendor's markup and never ask for `rawHtml` to get around this; fetch the bytes.
  (PDFs are the opposite case and stay with Firecrawl: its `html` holds the document's own parsed
  text — measured on the Rhodes CV template, 1 credit — so a PDF never reaches scrape.do at all.)
- **`apps/documents/evidence/github.py` (api.github.com).** The CV evidence refresh's client
  (`docs/superpowers/specs/2026-10-14-cv-evidence-github-and-pdf-reading-design.md` §5.3, §7.1).
  Not `egress.fetch_json_api`: that returns no response headers, and the rate-limit handling
  reads `x-ratelimit-remaining`, `x-ratelimit-reset` and `retry-after` off every answer, a 403
  included, and the tree request sends and reads an `etag`; nor raw bytes, which `repo.py`
  downloads for a notebook or README that GraphQL cut. Each repo is read with two GraphQL
  queries (`RepoOverview`, `RepoFiles`) and one REST tree; file paths travel as GraphQL
  variables, never in query text. Safe first-party because the host is a constant: every path
  is built in the package, every `owner/name` GitHub returns passes `sources._is_safe_segment`,
  the login passes `github.LOGIN`, a branch or raw path is `quote()`d, and `GitHub._url` refuses
  any path that does not start with a single `/`, so the token only ever reaches api.github.com.
  `GITHUB_TOKEN` is sent to this host only and never logged; no token, no request. Like every
  fetch here, it is never pointed at a portal.

Five more outbound paths are data sources rather than fetches, and are listed here because
they are outbound and deliberately not vendor traffic:

- **Every EMJM, and who awards it → the EACEA project API.** A JSON API, not a page to
  scrape. **It is the complete EMJM list, not a supplement:** every EMJM is an EU-funded
  project, so the funder's own project records are the authoritative catalogue. Measured
  2026-09-14 and re-measured 2026-09-15: **415 projects — 166 under the 2021-2027 action
  code, 249 under 2014-2020** — 2,026 participation rows and 576 distinct organisations.
  Per organisation it carries name, country, city, **EU-PIC** and website, which answers
  the question the HTML catalogue cannot: **which universities award a joint programme**.
  For scale, `seed:eacea`'s HTML catalogue yields 169 leads.
  **The catalogue is still what the pipeline harvests today** (`pipeline.py::default_sources`
  registers `EACEA_ERASMUS_MUNDUS` and nothing else), and it is not redundant — it links to
  each consortium's own site, which is the origin a claim must come from, where the API
  gives the roster. `manage.py enumerate_eacea` (build item 7, `apps/research/eacea.py`) now
  writes every project and a PIC-first partner binding into the register; matching a project
  to a `Program` row is still a person's job. It is operator-run and read-only toward the
  network, and anything that *schedules* it must first put the fetch behind
  `LocalEgressProxy`. Its project keys come from a live capture (2026-10-05,
  `tests/research/fixtures/eacea_emjm_page.json`, 385cade3); the module docstring that still
  calls them placeholders is stale. A wrong project key yields zero projects, which the gate
  reads as `listed != printed`.
  - The endpoint is **`POST https://ec.europa.eu/programmes/service/search/project/search`**,
    and it answers **200 to plain `curl`** — no browser, no session, no token.
  - **The 403 is two URL families, not a platform that refuses us.** Re-measured 2026-09-14:
    `erasmus-plus.ec.europa.eu/projects/search/details/<id>` returns 403 (still true, and
    why `seeds.py` stopped harvesting it), `/projects/search` returns 200, and the API
    above returns 200. The second family:
    `webgate.ec.europa.eu/eyp/valor/api` 403s on every path and is a base string the
    page concatenates at runtime, never the host actually called.
  - **The filter field is `projectLevel3`.** `level3` and `actionType` are accepted,
    silently ignored, and return the whole corpus — 341,611 projects on 2026-09-15, a
    full-corpus fetch that looks exactly like a successful filtered query. The two action
    codes are `43690363` (2021-2027) and `31046261` (2014-2020), and **both are needed**.
    Assert the total against the hundreds, never the hundreds of thousands.
  - **Persisting this is permitted, and that does not generalise.** EACEA's terms govern
    uploading and point retrieval at the Commission's open-reuse notice. The
    never-persist-a-provider-result rule below governs *search providers*, and is kept on
    merits rather than terms. Do not carry either rule onto the other.
- **Korean programmes → an anonymous XLSX; Korean institutions → a keyed JSON API.** Two
  data.go.kr datasets, both KOGL (free, 이용허락범위 제한 없음), and the split between them is
  the whole point — **neither file is served from where its catalogue card lives.**
  Spec'd and measured 2026-08-28, **not built**: no adapter in `apps/` reads `data.go.kr`.
  Full detail and the field lists:
  `docs/superpowers/specs/2026-08-28-funding-led-discovery-design.md` §"Korea".
  - **Programmes — dataset `#15139338`.** data.go.kr holds only metadata (제공형태
    *기관자체에서 다운로드*); the file itself is served by 대학알리미 (`academyinfo.go.kr`) as
    `학교별 교육편제단위 정보_20241007기준.xlsx` to an **anonymous GET, no key**. School →
    college → department/major → degree level. **55,228 rows over 1,880 institutions**, of
    which **12,169 live master's-bearing rows across 1,185 institutions** — the largest
    single supplier in the build by an order of magnitude.
  - **Institutions — dataset `#15107736`.** Its file download 404s anonymously; the Open API
    (`api.data.go.kr/openapi/tn_pubr_public_univ_info_api`) needs a service key and is the
    only route. Seventeen fields, and **`홈페이지주소` is the institution website** — which is
    exactly what `ror.py` looks up from ROR, so Korea's frame comes direct
    and current with no ROR join. Registration also escapes the 50,000-row grid ceiling; it
    buys nothing for the programme list, which is already anonymous.
  - **49.1% of the programme rows are dead, and they look alive.** 27,124 of 55,228 are
    폐과 — abolished departments the dataset keeps for statistical disclosure, warned about
    in its own 기타 유의사항 and repeated inside the workbook on sheet row 2. `학과상태`
    partitions them: eight live values (기존, 신설, 변경[신설]…) against four 폐지 values. An
    adapter that ignores the field emits a catalogue half-full of departments nobody
    recruits for, each as claim-capable-looking as a live one.
  - **`학위과정` is a comma-separated multi-value string, not an enum.** Eleven raw values
    (`석사`, `석사, 박사`, `석사,박사, 석박사통합`, `학석사통합`, `전문기술석사`…) with
    inconsistent spacing after the comma. Substring match; equality against `'석사'` silently
    drops the **8,117** rows where master's is bundled with a doctoral track.
  - The file is dated `20241007` against a stated 수시/자동갱신 cycle, so it lags. Official and
    current are different properties.
- **Wikidata SPARQL → `apps/research/wikidata.py`.** CC0, operator-run
  (`manage.py enumerate_wikidata`), read through `egress.fetch_json_api` with the SPARQL JSON
  content type named explicitly (`accept=`). It writes `CANDIDATE` only and never vouches: a
  crowd-sourced count is never a denominator, so its lists are `is_denominator=no`. The query
  pins class, the P576 dissolution filter and P856 website, and the module docstring quotes
  them. `WIKIDATA_USER_AGENT` carries a contact because Wikimedia's User-Agent policy throttles
  or refuses a generic client. Its row bounds were set from spec §6.2's 229 and have **not**
  been tightened against a live count (egress blocked 2026-09-26).
  **Build item 8 reads it two more ways, from the same module:** the entity API
  (`wikidata.find_item`) as the name→site resolver's first stop — an exact label or alias in
  the right country (P17), not dissolved (P576, including an undated `somevalue`), and only when
  exactly one item passes; a fuzzy top hit is never a match — and the query service
  (`wikidata.sparql`) for the resolver's vocabulary (`manage.py build_resolver_vocabulary`,
  committed under `apps/research/resolver_data/`). **Those files do not exist yet**: the build is
  owed to the first environment with Wikidata egress, and until then `resolve_register` refuses
  with `VocabularyMissing` and the committed-data tests skip.
- **The resolver's residue → Diffbot Enhance** (`apps/research/providers/diffbot.py`). One
  homepage URL per name, `type=Organization` only, nothing else read or kept; 400 entities a
  month metered on `RegisterEntry.diffbot_asked_at`, which only `--write` records — so
  `resolve_register --diffbot` needs `--write`, and `--write` is off until the resolver's
  fresh-script hold-out passes (`RESOLVER_WRITES_ENABLED`). Its terms carry no effective date, so
  both `resolve_register --diffbot` and `resolver_gate --diffbot` refuse unless
  `DIFFBOT_TERMS_READ_ON` is within 31 days; they were **not** re-read when this was built
  (`docs/legal/2026-09-provider-terms.md`).
- **ROR v2 → `apps/research/ror.py`.** CC0, an exact `domains:` lookup and a country × type
  enumeration only — never a name lookup's top hit ("the fuzzy top hit is sometimes a
  different organisation", spec §6.2). The `domains:` lookup is live in the provenance gate
  (`provenance_job.check_body`). The enumeration half (build item 7, Task 11) is **not built**,
  gated on `manage.py ror_gate` showing ≥ 95% website agreement on the 58 yield hosts.

All of these are operator-run and read-only toward the network; anything that *schedules* them must
first put the call behind `LocalEgressProxy`, the same rule the EACEA bullet states.

- **LLM calls → the OpenAI and Anthropic SDKs** (`OPENAI_EXTRACTION_MODEL`,
  `ANTHROPIC_JUDGE_MODEL` in `config/settings/base.py`). Not a fetching concern.

History of the deleted research-browser tier — why it existed, the Fargate user-namespace measurement (2026-08-26) and the `/proc/<pid>/environ` proof: `docs/superpowers/specs/2026-08-26-browser-isolation-design.md`. The Fargate fact that still binds the portal tier is in `.claude/rules/portals.md`.

### Search providers: what may be kept

Live search is built (`search.SearchSource`, the providers in `apps/research/providers/`). Its terms question
is settled; the rules that keep it settled are not self-enforcing.

- **Exa and Brave are permitted, under written permission carrying one condition: no
  competing-search training.** Owner, 2026-09-17. Both were previously barred here by their own
  definitions — Brave's ToS defines "Search Results" as "**any outputs from calls made to the API**",
  barred "in whole or in part", and Exa §4.2(a) bars reproducing anything "obtained from or through
  the Services". That reading was correct against the public terms and is now superseded by the
  grant, not by a re-reading. **The condition is the live constraint:** their output may not train a
  competing search index. So no embedding corpus, no learned reranker, no derived index built from
  provider results — the day someone proposes "we could train a ranker on what Exa returns", this
  line is why the answer is no.
- **The retention prohibition is lifted; the discipline is kept anyway.** With storage permitted,
  "never persist a provider result object" is no longer a terms requirement — and it stays, on
  merits. Only a URL is read from any provider response; the origin is then fetched and validated;
  nothing from a provider object is persisted. A snippet is a vendor's rendering of someone else's
  page, it goes stale silently, and a SERP cache is a second source of truth for a question the
  origin already answers. Keep it because it is right, not because a contract said so.
- **Provenance comes from the origin, never the provider.** What lands in `OfficialSource.canonical_url`
  is a URL *we* fetched and verified against the institution's own server; the snapshot, digest and
  `final_url` are all origin-derived. The provider was a pointer, and a pointer is not retained as a
  provider artifact. **This one was never a terms rule**, so nothing about the Exa/Brave grant
  touches it. The clauses themselves are quoted in `docs/legal/2026-09-provider-terms.md`; Exa's
  `/search` restricted to an institution's domain is the research-fit site search
  (`apps/research/providers/exa.py`).
- **Tavily's terms are still the cleanest and it keeps its jobs, but it is no longer "the provider".**
  Its restrictions attach to "the Services", which it defines to exclude "Output", so its retention
  is permitted by structure rather than by silence. Its jobs are listed at the top of this file. Provider *choice* is now settled by
  measurement instead: **the roster lives in
  `docs/superpowers/specs/2026-09-17-role-routed-discovery-design.md` §4.13**, one table with each
  source's role, its measured-best configuration, its terms standing and its ceiling. Read it before
  adding, swapping or re-proposing a provider — it also records what was **rejected and why**
  (Perplexity, Yandex, Seznam, Coc Coc, Mojeek, Google Custom Search), which is the part that
  otherwise gets re-derived. Google-derived indexes remain unusable as a source of catalog rows:
  SerpApi cannot grant rights to indexes it resells, so Google via SerpApi is a transient yardstick
  only. Baidu and Naver via SerpApi are the roster's one recorded exception (owner decisions
  2026-09-17 and 2026-09-18: free tier, no legal shield — §4.13 and §8 carry the position).
  **Still true of any index whose terms have not been read: definitions decide this question, not
  caching clauses.**
- **Tavily §3.2(xvi) forbids** using Output "to make automated decisions without human oversight that
  have a significant adverse impact on individual rights in high-risk areas". Education is not
  enumerated there, which is the leg this rests on. **Owner position, 2026-10-08: the clause does not
  apply** ("we are not in the dangerous zone"). Do not re-raise it as a blocker.

  What this note used to say — that every recommendation is counselor-reviewed — is false, and was
  false when written. `phased requirements.md` §38 publishes the pool and pack to the student
  immediately, *deliberately* un-gated by counselor review, because a gate would add a day of
  latency for a check the agents already perform. `apps/funding/services.py` says the same in its
  own words: "No counselor approval, no `Approval` row". So for recommendations, the "agent decides
  unaided" case this clause is about is not hypothetical — it is what ships.

  Human oversight is real, but it sits **downstream** of recommendation, at the two places §38 puts
  it: document approval (`apps/documents/approval.py`, recorded as `ConsentEvent`), and application
  execution, where the agent escalates to a consultant on six triggers — `MISSING_FACT`,
  `PERSONAL_ATTESTATION`, `APPLICANT_MFA`, `UNSOLVED_CHALLENGE`, `AMBIGUOUS_DECISION`, `PORTAL_ERROR`
  (`apps/portals/escalation.py`). A compliance argument may rest on those. It may not rest on a
  counselor gate over recommendations, because there isn't one.

  Read the clause before proposing any further unaided-agent feature.

Evidence, provider comparison and the adjudication of two conflicting research runs:
`docs/superpowers/research/2026-08-30-live-search-synthesis.md`.
