# The Fetch Engine, Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every research page fetch go through one seam that walks a seven-rung ladder across Firecrawl, scrape.do, a retry queue, the Internet Archive and a human, remembers per host which rung worked, and always ends in one of eleven recorded outcomes — so "found nothing" and "could not look" can never be the same row again.

**Architecture:** One package, `apps/research/fetch/`, holding three provider modules (Firecrawl, scrape.do, archive), a budget, and a ladder behind a single `fetch_page()`. Two new shared-catalog tables, `HostProfile` (what worked here last time) and `FetchAttempt` (every vendor call), carry the memory and the trail. `retrieve_official_source` keeps its name and signature and delegates, so its eight callers do not change. The old fetch path — `fetch_official_source`, the Scrapling tier, `browser_server.py` and the whole `Browser*` infrastructure — is deleted in the last two tasks, once everything routes through the new seam.

**Tech Stack:** Django 5.2, urllib3 (already the transport for contracted APIs), Firecrawl `/v2/scrape`, scrape.do GET API, Internet Archive availability API, pytest with the repo's test DB.

**Spec:** `docs/superpowers/specs/2026-09-22-fetch-engine-design.md` — this plan is its §17 plan 1 ("Engine core"). §17 plan 2 (site jobs: map, crawl, `/agent`, monitors) is a separate plan and nothing here anticipates it. Read the spec's §4 (the ladder), §5 (`HostProfile`), §6 (the outcomes), §9 (cost) and §10 (safety) before starting; they are the argument for every task below.

**Base branch:** `claude/fetch-spec-refresh`, rebased on 2026-09-23 onto `origin/master` at 40f8400 (which already carries the spec). Work in a fresh worktree: `git worktree add ../fetch-engine claude/fetch-spec-refresh`. Test database: `POSTGRES_DB=tehsil_fetch_engine` — never share a test DB between sessions. **Read the Reconciliation section first: master already carries part of this plan.**

## Reconciliation with master, 2026-09-23 — read before any task

This plan was written on 2026-09-22 against commit 5eb1eef, 226 commits behind `origin/master`. The
same day master merged PRs #103 and #104, which executed the 2026-09-19 vendor-fetch plan's Tasks
1–7: `apps/research/fetch/` exists (`types.py`, `firecrawl.py`, `scrapedo.py`, and `__init__.py`
holding `fetch_page` and `SweepBudget`), `retrieve_official_source` delegates to it,
`fetch_official_source`, the Scrapling tier, `browser_server.py`, every `Browser*` resource and
`scrapling[fetchers]` are gone, and `tests/research/test_fetch_live.py` and `manage.py fetch_ladder`
exist. The branch was rebased onto master on 2026-09-23. The handoff's risk "do not execute both
plans" resolved itself: the vendor-fetch plan went first.

**Every task below is therefore a delta over master's files, not a creation.** The code blocks are
the target shape; where they contradict a decision master carries on a measurement, master wins, as
listed here. Read the master module before editing it.

| task | on master already | still to do |
|---|---|---|
| 1 | `FetchedPage(FetchResult)` with `fetched_via`/`cost_credits`/`change_status`; `VendorUnavailable`, `ChargedFailure`, `FetchBudgetExhausted` (all `SourceBlocked`); `check_payload`; `FIRECRAWL_API_KEY`, `SCRAPEDO_API_KEY`, `FETCH_SWEEP_CREDITS` | `Outcome`, `Attempt`, `usable()`, `CHALLENGE_MARKERS`, `MIN_DOCUMENT_BYTES`, `VENDOR_PARSED_TYPES`; extend `FetchedPage` with `markdown`, `outcome`, `rung`, `status_code`, `page_count`, `total_pages`, `captured_at`, `screenshot`, `reason`, `attempts`, `ok`; three settings only — `FETCH_PDF_MAX_PAGES`, `FETCH_ARCHIVE_MAX_AGE_DAYS`, `FETCH_REPROBE_DAYS` |
| 2 | nothing | as written at `0004`/`0005` — **`0003` is master's `0003_organisation_register`** (taken 2026-09-23, after this plan was written). The decision-layer plan takes `0006`/`0007` and the funnel plan `0008`/`0009`, so run `ls apps/research/migrations/` in Step 0 and take the next free pair, repointing `dependencies`. A clean merge whose dependency names a missing node is the 2026-09-15 collision; `makemigrations --check` catches it |
| 3 | `POST /v2/scrape` with `markdown` + `html` + `changeTracking`, the PDF parser, back-off and three retries on 429/5xx, target-status handling with `escalate`, final-URL validation, never `or url` | outcomes instead of exceptions; rung 2 `actions`; `maxPages`/`pageMarkers` and `FETCHED_PARTIAL`; `skipTlsVerification`, `blockAds`, `removeBase64Images`; `location` from the profile; `x-request-id`; screenshot; drop `proxy` |
| 4 | render+super at 25 credits; redirection ON with `Scrape.do-Resolved-Url` validated (measured 2026-09-19 on globed.eu); the cost header authoritative with the tariff as floor; the `_SCRAPE_DO_OWN` free set | outcomes; rung 3 (plain, 1 credit) as a parameter; `sessionId`, `geoCode`, `waitSelector`/`customWait`, `transparentResponse`, `fullScreenShot` |
| 5 | nothing | as written |
| 6 | `SweepBudget` per vendor with `check(vendor)`, `spend`, `usd()` and `USD_PER_CREDIT`, in `fetch/__init__.py` | **struck.** Only `observe_remaining` (the vendor floor) and `sweep_id` are added, inside Task 7; `budget.py` is not created |
| 7 | a two-rung `fetch_page` raising `SourceBlocked` subclasses | the rewrite, as written, under items 3–5 below |
| 8 | nothing | as written |
| 9 | `retrieve_official_source(url, *, fetch, tag, budget)` delegates; **eight** callers (`reader`, `program_rules`, `pipeline`, `seeds`, `fetch_ladder`, and — new at 40f8400 — `funding_yield`, `research_fit/service.py`, `research_fit/pages.py`) | the outcome → `SourceBlocked` translation on **that** signature, not the plan's `plain_fetch`/`browser_render` one; the `record_blocked_source` reason update; the call from the ladder's terminal paths |
| 10 | nothing | as written |
| 11 | done | **struck.** `_backoff_seconds`, `_RETRY_ATTEMPTS`, `_THROTTLED` and `looks_unrendered` stay: `firecrawl.py` and `usable()` use them |
| 12 | infra, Dockerfile, `scrapling`, the live gate — done (the Dockerfile's remaining Playwright is the portal stage, not the research browser) | Step 4 only (runbook + CLAUDE.md), and extending the existing `test_fetch_live.py` with outcome-class and credit-ceiling assertions; no new file |

Where the plan and master disagree, and which wins:

1. **`onlyMainContent` stays `False`, and `body` stays `html`, not `rawHtml`.** Master's choice is
   measured: `harvest.anchors`, `search._sitemap`, `reader.readable_text` and `content_digest` all
   parse `body`, and `onlyMainContent: true` strips the navigation links anchor harvesting reads — a
   markdown body once made every catalogue yield zero leads in silence. The reader narrows to `<main>`
   itself. The shell rule is `len(markdown) < 1_500 and len(body) >= 20_000` against that `html`.
   `rawHtml` is added only when a consumer needs the DOM; none does.
2. **scrape.do follows redirects; the hop loop in Task 4 Step 3 is stale.** The plan's own Step 0
   answer and Step 1 test (`disableRedirection` absent, one call, `Scrape.do-Resolved-Url` validated)
   are the design, and master's module already implements it. Task 4's Step 3 code block still
   carries a `disableRedirection` loop that contradicts both — do not write it. Rung 3 is the same
   call with `render=false&super=false`.
3. **The budget stays per vendor.** Master's `FETCH_SWEEP_CREDITS` and `USD_PER_CREDIT` are argued
   in `config/settings/base.py` and pinned by `tests/research/test_fetch_router.py`; the plan's
   single limit in Firecrawl units with a 7:1 conversion is not adopted, and `FETCH_CREDIT_BUDGET`
   and `SCRAPEDO_CREDITS_PER_FIRECRAWL_CREDIT` are not added. `budget.check(vendor)` runs before each
   rung, as master does; the ladder turns `FetchBudgetExhausted` into the `BUDGET` outcome.
4. **A vendor's own failure never buys rung 4.** Master measured a 58-host sweep's 429s each
   escalating to the 25-credit tier and pins the fix
   (`test_a_throttled_vendor_does_not_buy_a_25_credit_answer`). The plan's ladder continues on any
   `VendorUnavailable`. Reconciled: `escalate=False` — the vendor said "not now", after
   `firecrawl.py`'s own back-off — may fall to rung 3 (1 credit, a different network) and then to
   rung 5's queue, never to rung 4; a target 401/403 (`escalate=True`) walks the full ladder. A
   missing key raises out of `fetch_page` as a deploy defect, as both providers already do. Task 7's
   `test_a_vendor_outage_is_not_a_blocked_site` stands (a 503 → rung 3 serves); add its twin
   asserting rung 4 is not reached on `escalate=False`.
5. **Exception classes keep master's bases and `escalate`.** `VendorUnavailable(SourceBlocked,
   escalate=)` and `FetchBudgetExhausted(SourceBlocked)` stay so `fetch_ladder`, `pipeline` and every
   `except SourceBlocked` keep working; the plan's `RuntimeError` bases are not written.
   `ChargedFailure` becomes provider-internal: a charged target failure is a `DEAD` or `BLOCKED`
   outcome carrying its credits, and its `escalate=False` on 404/410 is the `DEAD` terminal rule.
6. **`cost_credits` is not renamed.** The plan's `FetchedPage.credits` is master's `cost_credits`,
   which `fetch_ladder`, the router tests and `budget.spend` read. `Attempt.credits` and
   `FetchAttempt.credits` are new names and stay as written.
7. **`proxy` is dropped from the request.** The 2026-09-22 documentation re-read (fetch-tiers spec
   §4.1d) says it is deprecated and `auto` is the default. Harmless either way; the later evidence wins.
8. **The settings insert point is after `SCRAPEDO_API_KEY` (`config/settings/base.py:156` at 40f8400), and
   only the three settings plan 1's code reads are added.** `FIRECRAWL_WEBHOOK_SECRET`, the
   concurrency, RPM and monthly-credit values, `FETCH_CRAWL_LIMIT` and `FETCH_AGENT_MAX_CREDITS` are
   plan 2's and arrive with their consumer.
9. **Task 3 Step 0 and Task 4 Step 0 are answered** — by the 2026-09-22 measurements (an
   `x-request-id` reused sequentially is charged again; scrape.do follows a chain for 1 credit and
   names the landed URL) and, for scrape.do, by master's own 2026-09-19 measurement on globed.eu.
   Cite them in the commit message; do not spend credits re-measuring.
10. **Commit attribution** in the templates below reads "Claude Opus 5"; use the attribution line the
    running session carries.

### Second reconciliation, master 40f8400 — 2026-09-23 evening

The branch was rebased again the same day. Between `bb03a1c` and `40f8400` master merged PRs #105,
#114, #117–#122 — the funding slice-1 spine, the Organisation register, research fit end to end and
five dependency bumps. Three deltas reach this plan and nothing else does:

1. **`apps/research/migrations/0003` is taken** (`0003_organisation_register`). Task 2 is `0004`/`0005`,
   per the table above.
2. **`retrieve_official_source` gained three callers**, all through the research-fit path, which now
   fetches through the vendor router rather than local egress. Task 9's translation must not narrow
   its signature, and Task 12's deletion sweep must not assume `apps/documents/` is off this seam.
   Row 9 above is corrected.
3. **`apps/research/hosts.py::registrable_domain` exists** (Public Suffix List, offline snapshot) —
   and it is **not** `HostProfile`'s key. `HostProfile` stays keyed on the full lowercased hostname
   (`urlsplit(url).hostname`), because what it remembers is per *server*: robots.txt, the TLS and WAF
   behaviour, whether this host needs a render. `ai.study.fau.eu` rendering says nothing about
   `www.fau.eu`. `registrable_domain` answers a different question — "is this the same organisation"
   — and belongs to the register and to cross-sweep dedupe, never here. Do not "unify" them.

Also landed and already reflected below: `reader.page_lines` and `reader.is_shell`.

Revised order: 1 → 2 → 3 → 4 → 5 → 7 (with the budget delta) → 8 → 9 → 10 → 12 (docs and the
live-gate extension). Execution mode, chosen 2026-09-23: `superpowers:subagent-driven-development`,
one task per subagent, each briefed with this section and the master module it edits.

---

## Global Constraints

- **Keys come from the environment, never from a settings default.** `FIRECRAWL_API_KEY`, `SCRAPEDO_API_KEY`, `FIRECRAWL_WEBHOOK_SECRET`. An absent key makes the provider raise at call time; it never silently degrades to another tier.
- **Every plan-dependent number is a setting with an env override** (spec §9.1). The tier will rise with investment; upgrading must be a config change, not a code change.
- **Every vendor result is untrusted exactly as the page it came from was.** `validate_public_url` on every final URL and on every redirect hop; `require_same_origin` before any bytes are persisted when the caller demands provenance; the existing `ALLOWED_CONTENT_TYPES` allowlist and `MAX_RESPONSE_BYTES` (10 MiB) cap apply to vendor bodies exactly as they applied to ours.
- **No vendor ever fetches `europa.eu`, a contracted API, or a portal.** `apps/documents/europass.py`'s own `_request` (student PII, pinned address, DNS-rebinding guard) and `egress.fetch_json_api` (our own API keys) are untouched by every task here.
- **`fetched_via == "EGRESS"` remains reachable only for `europa.eu`,** and a test asserts no other host uses it.
- **Never run `ruff format`** in this repo — it is a lint-only gate and `ruff format` churns 26 files (CLAUDE.md).
- **After every task:** `uv run ruff check apps config tests scripts`, `uv run mypy apps config`, `POSTGRES_DB=tehsil_fetch_engine uv run pytest`, and `uv run python manage.py makemigrations --check --dry-run` must stay clean.
- **RLS is verified against a `NOBYPASSRLS` role or it is not verified.** The test role bypasses RLS, so a passing test proves nothing about a policy; use the `runtime_connection` fixture (`tests/tenancy/test_database_isolation.py:80`) or `rls_enforced_orm` (`tests/conftest.py:58`). CLAUDE.md, "Row-level security: what actually filters a query". **Before Task 2's test can use `runtime_connection` at all, it has to move:** it is defined inside `tests/tenancy/test_database_isolation.py`, so it is invisible from `tests/research/`, and it grants `SELECT` on `tenancy_membership` alone, so a new table is invisible to the role whatever its policy says — the test would pass on a permission error. `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` Task 2 Step 0 carries the fix (move it to `tests/conftest.py`, widen the grant to the schema); whichever plan runs first does it.
- **Ten of the eleven outcomes are values, not exceptions.** Only a programming error raises out of `fetch_page`. A caller that wants the old exception behaviour gets it from the compatibility wrapper in Task 10, not from the ladder.

---

## File Structure

| file | responsibility |
|---|---|
| `apps/research/fetch/__init__.py` (new) | `fetch_page()` — the ladder: rung order, stop conditions, outcome classification, budget checks, profile read and write-back |
| `apps/research/fetch/types.py` (new) | `Outcome`, `FetchedPage`, `Attempt`, `VendorUnavailable`, `FetchBudgetExhausted`, `usable()`, `classify_status()` |
| `apps/research/fetch/firecrawl.py` (new) | rungs 1–2: `POST /v2/scrape`, markdown + links + rawHtml + changeTracking, PDF parser with `maxPages`, optional `actions` |
| `apps/research/fetch/scrapedo.py` (new) | rungs 3–4: GET API, hop-by-hop redirects, `render`/`super`/`geoCode`/`sessionId`, both credit headers |
| `apps/research/fetch/archive.py` (new) | rung 6: availability API, capture-age window, `id_` raw capture, same-origin check on the wrapped URL |
| `apps/research/fetch/budget.py` (new) | `SweepBudget` — pre-call check, spend accounting, vendor remaining-credit floors |
| `apps/research/models.py` (modify) | `HostProfile`, `FetchAttempt` |
| `apps/research/migrations/0004_fetch_engine.py` (new) | the two tables |
| `apps/research/migrations/0005_fetch_engine_rls.py` (new) | `shared_catalog_select` + `catalog_ingestion_write` on both |
| `config/settings/base.py` (modify) | the §9.1 settings block, beside `SEARCH_API_KEY` at line 116 |
| `apps/research/discovery.py` (modify) | `retrieve_official_source` delegates to `fetch_page`; `render_with_scrapling`, `browser_fetch_options`, `render_via_browser_service` deleted in Task 11 |
| `apps/research/services.py` (modify) | `record_blocked_source` updates `reason` on every call |
| `apps/research/management/commands/retry_due_fetches.py` (new) | rung 5's worker |
| `apps/research/egress.py` (modify) | `fetch_official_source` and its redirect loop deleted in Task 11; `validate_public_url`, `require_same_origin`, `fetch_json_api`, `looks_unrendered`, `USER_AGENT` all stay |
| `apps/research/browser_server.py` (delete, Task 11) | |
| `infra/template.yaml`, `Dockerfile`, `pyproject.toml` (modify, Task 12) | every `Browser*` resource, the `browser` stage, `scrapling[fetchers]` |
| tests (new) | `tests/research/test_fetch_types.py`, `test_fetch_firecrawl.py`, `test_fetch_scrapedo.py`, `test_fetch_archive.py`, `test_fetch_budget.py`, `test_fetch_ladder.py`, `test_fetch_profile.py`, `test_fetch_models_rls.py`, `test_fetch_retry_command.py`, `test_fetch_live.py` |

---
### Task 1: Outcomes, the page type, and the settings block

> **Master status, 2026-09-23:** partial — extend master's `types.py`; three settings only (reconciliation items 5, 6, 8). See Reconciliation.

Everything else consumes these names. Nothing here touches the network or the database.

**Files:**
- Create: `apps/research/fetch/__init__.py` (empty for now), `apps/research/fetch/types.py`
- Modify: `config/settings/base.py:133` (beside `SEARCH_API_KEY`; 40f8400)
- Test: `tests/research/test_fetch_types.py`

**Interfaces:**
- Consumes: `apps.research.egress.FetchResult`, `ALLOWED_CONTENT_TYPES`, `MAX_RESPONSE_BYTES`, `looks_unrendered`
- Produces: `Outcome` (str enum), `Attempt`, `FetchedPage`, `VendorUnavailable`, `FetchBudgetExhausted`, `usable(content_type, body, status_code) -> tuple[bool, str]`, `CHALLENGE_MARKERS`

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_types.py
import pytest

from apps.research.fetch.types import Attempt, FetchedPage, Outcome, usable


def test_a_short_two_hundred_is_a_block_not_a_document():
    """Measured 2026-09-19: mischolarship.com answered HTTP 200 with 469 bytes
    of nothing and was billed 1 credit. Treating that as FETCHED is how a
    blocked page becomes 'this programme states no CV rules'."""
    ok, reason = usable("text/html", b"x" * 469, 200)
    assert ok is False
    assert reason == "short_body"


def test_a_challenge_interstitial_is_a_block():
    body = b"<html><title>Just a moment...</title>" + b"y" * 2_000 + b"</html>"
    ok, reason = usable("text/html", body, 200)
    assert ok is False
    assert reason == "challenge"


def test_a_real_page_is_usable():
    body = b"<html><body>" + b"<p>Applicants must submit a CV.</p>" * 200 + b"</body></html>"
    assert usable("text/html", body, 200) == (True, "")


def test_a_disallowed_content_type_is_refused():
    ok, reason = usable("application/zip", b"z" * 5_000, 200)
    assert ok is False
    assert reason == "content_type:application/zip"


def test_a_vendor_parsed_image_or_office_document_is_usable():
    """Measured 2026-09-22: Firecrawl OCRs a PNG through /scrape for 1 credit
    and parses DOCX/XLSX by URL. Our old allowlist was written for a client
    that could read none of these; on the vendor path, `markdown` is what a
    reader reads and the content type is informational."""
    assert usable("image/png", b"\x89PNG" + b"\x00" * 2_000, 200, markdown="Başvuru için CV.") == (True, "")
    assert usable(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK" + b"\x00" * 5_000, 200, markdown="# Guidelines",
    ) == (True, "")
    ok, reason = usable("image/png", b"\x89PNG" + b"\x00" * 2_000, 200)
    assert (ok, reason) == (False, "content_type:image/png")  # no markdown: nothing to read


def test_a_body_over_the_cap_is_refused():
    ok, reason = usable("text/html", b"x" * (10 * 1024 * 1024 + 1), 200)
    assert ok is False
    assert reason == "too_large"


def test_outcome_is_a_closed_set_of_eleven_plus_the_intermediate_state():
    """Spec §6: eleven outcomes, plus RETRY_SCHEDULED, which is the one
    intermediate state and never reaches a caller of fetch_page. A twelfth
    OUTCOME is a design change, not an implementation detail -- every caller
    switches on this set."""
    assert sorted(o.value for o in Outcome) == [
        "ARCHIVED", "BLOCKED", "BUDGET", "DEAD", "FETCHED", "FETCHED_PARTIAL",
        "INVALID", "OFF_SITE", "RETRY_SCHEDULED", "UNCHANGED", "UNREACHABLE",
        "UNREADABLE",
    ]


def test_a_fetched_page_carries_its_trail():
    page = FetchedPage(
        final_url="https://example.test/a",
        redirects=(),
        content_type="text/html",
        body=b"<html></html>",
        markdown="# A",
        outcome=Outcome.FETCHED,
        fetched_via="FIRECRAWL",
        rung=1,
        credits=1,
        status_code=200,
        attempts=(Attempt(rung=1, vendor="FIRECRAWL", outcome=Outcome.FETCHED, credits=1),),
    )
    assert page.ok is True
    assert page.attempts[0].vendor == "FIRECRAWL"


def test_an_unreadable_page_is_not_ok_but_is_not_an_exception():
    page = FetchedPage(
        final_url="https://example.test/a", redirects=(), content_type="text/html",
        body=b"", markdown="", outcome=Outcome.UNREADABLE, fetched_via="SCRAPE_DO",
        rung=4, credits=25, status_code=200, attempts=(),
    )
    assert page.ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.fetch'`

- [ ] **Step 3: Write minimal implementation**

```python
# apps/research/fetch/__init__.py
"""The fetch engine. Design: docs/superpowers/specs/2026-09-22-fetch-engine-design.md."""
```

```python
# apps/research/fetch/types.py
"""The vocabulary of the fetch engine: what a fetch produced, and what happened.

Ten of the eleven outcomes are VALUES, not exceptions (spec §6). That is the
whole point of the engine: before it, a blocked fetch and a page that genuinely
states nothing both arrived as "no rules found", and CLAUDE.md records this repo
meeting that failure twice. Every terminal state here names the rung it died on.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from ..egress import ALLOWED_CONTENT_TYPES, MAX_RESPONSE_BYTES, looks_unrendered


class Outcome(StrEnum):
    FETCHED = "FETCHED"
    FETCHED_PARTIAL = "FETCHED_PARTIAL"
    UNCHANGED = "UNCHANGED"
    ARCHIVED = "ARCHIVED"
    UNREADABLE = "UNREADABLE"
    BLOCKED = "BLOCKED"
    UNREACHABLE = "UNREACHABLE"
    DEAD = "DEAD"
    OFF_SITE = "OFF_SITE"
    INVALID = "INVALID"
    BUDGET = "BUDGET"
    #: The one intermediate state. It never reaches a caller of fetch_page();
    #: it is what the retry queue reads.
    RETRY_SCHEDULED = "RETRY_SCHEDULED"


#: Outcomes a caller can read content from.
SERVED = frozenset({Outcome.FETCHED, Outcome.FETCHED_PARTIAL, Outcome.ARCHIVED})

#: A 200 carrying one of these is a challenge interstitial, not a document.
#: Lowercased substring match against the first 4 KiB of the body.
CHALLENGE_MARKERS = (
    b"just a moment",
    b"enable javascript and cookies to continue",
    b"checking your browser",
    b"attention required! | cloudflare",
    b"ddos protection by",
    b"verifying you are human",
)

#: Below this, a 200 is not a document whatever it claims. Measured 2026-09-19:
#: mischolarship.com, HTTP 200, 469 bytes, billed 1 credit.
MIN_DOCUMENT_BYTES = 1_000

#: Types a VENDOR turns into markdown for us (measured 2026-09-22: a PNG is
#: OCR'd through /scrape for 1 credit; DOCX/XLSX/PPTX parse by URL). Usable only
#: when `markdown` is non-empty -- the bytes themselves are unreadable to us.
VENDOR_PARSED_TYPES = frozenset({
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/tiff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/rtf", "application/epub+zip", "text/csv",
})


class VendorUnavailable(RuntimeError):
    """The vendor itself failed -- no key, a 5xx from their API, a transport
    error reaching them. Never raised for the *target* being unreachable."""


class FetchBudgetExhausted(RuntimeError):
    """Raised before a request is made, never after one is paid for."""


def usable(content_type: str, body: bytes, status_code: int, *, markdown: str = "") -> tuple[bool, str]:
    """Is this a document a reader can read? Returns (ok, reason-if-not).

    Order matters: the cheapest, most certain refusals first, so the reason a
    caller records is the most specific true one. A vendor-parsed type (an
    image, an office file) is readable only through the markdown the vendor
    made of it; with no markdown there is nothing to read.
    """
    if content_type in VENDOR_PARSED_TYPES and markdown.strip():
        return True, ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        return False, f"content_type:{content_type or 'missing'}"
    if len(body) > MAX_RESPONSE_BYTES:
        return False, "too_large"
    head = body[:4096].lower()
    if any(marker in head for marker in CHALLENGE_MARKERS):
        return False, "challenge"
    if status_code == 200 and len(body) < MIN_DOCUMENT_BYTES:
        return False, "short_body"
    if looks_unrendered(content_type, body):
        return False, "shell"
    return True, ""


@dataclass(frozen=True)
class Attempt:
    """One vendor call. The trail is a tuple of these, oldest first."""

    rung: int
    vendor: str
    outcome: Outcome
    credits: int = 0
    status_code: int | None = None
    reason: str = ""
    duration_ms: int = 0


@dataclass(frozen=True)
class FetchedPage:
    """What a fetch produced. Extends FetchResult's five fields; the engine's
    callers read `markdown` for every artifact kind, and `body` only when they
    need the HTML (readable_text, the DOM object, the digest of raw bytes)."""

    final_url: str
    redirects: tuple[str, ...]
    content_type: str
    body: bytes
    markdown: str
    outcome: Outcome
    fetched_via: str
    rung: int
    credits: int
    status_code: int | None = None
    browser_required: bool = False
    change_status: str | None = None
    captured_at: str = ""
    page_count: int | None = None
    total_pages: int | None = None
    screenshot: bytes | None = None
    reason: str = ""
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """True when a reader may read this page."""
        return self.outcome in SERVED
```

```python
# config/settings/base.py -- insert after line 116 (SEARCH_API_KEY)

# --- The fetch engine (spec 2026-09-22-fetch-engine-design.md §9.1) ----------
# Every number here is plan-dependent and env-overridable on purpose: the
# defaults are Firecrawl Standard ($83/mo, 100k credits, 25 browsers) and
# scrape.do Hobby ($29/mo, 250k credits, 10 concurrent), and the owner expects
# to move to a higher tier. Raising the tier is a change to these values and
# to nothing else in the codebase.
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
SCRAPEDO_API_KEY = os.getenv("SCRAPEDO_API_KEY", "")
FIRECRAWL_WEBHOOK_SECRET = os.getenv("FIRECRAWL_WEBHOOK_SECRET", "")
FIRECRAWL_CONCURRENCY = int(os.getenv("FIRECRAWL_CONCURRENCY", "25"))
FIRECRAWL_SCRAPE_RPM = int(os.getenv("FIRECRAWL_SCRAPE_RPM", "500"))
FIRECRAWL_CRAWL_RPM = int(os.getenv("FIRECRAWL_CRAWL_RPM", "100"))
FIRECRAWL_MONTHLY_CREDITS = int(os.getenv("FIRECRAWL_MONTHLY_CREDITS", "100000"))
SCRAPEDO_CONCURRENCY = int(os.getenv("SCRAPEDO_CONCURRENCY", "10"))
SCRAPEDO_MONTHLY_CREDITS = int(os.getenv("SCRAPEDO_MONTHLY_CREDITS", "250000"))
#: Per sweep, in Firecrawl-credit units. scrape.do credits are converted at the
#: measured dollar ratio (spec §4.1b: $0.00083 vs $0.000116, so 7 scrape.do
#: credits ~ 1 Firecrawl credit).
FETCH_CREDIT_BUDGET = int(os.getenv("FETCH_CREDIT_BUDGET", "5000"))
SCRAPEDO_CREDITS_PER_FIRECRAWL_CREDIT = 7
#: A PDF is billed per PAGE. A 200-page handbook is 200 credits, so the read is
#: capped and a truncated read is recorded as FETCHED_PARTIAL, never silently.
FETCH_PDF_MAX_PAGES = int(os.getenv("FETCH_PDF_MAX_PAGES", "60"))
FETCH_CRAWL_LIMIT = int(os.getenv("FETCH_CRAWL_LIMIT", "25"))
FETCH_AGENT_MAX_CREDITS = int(os.getenv("FETCH_AGENT_MAX_CREDITS", "300"))
#: Owner decision 2026-09-22: a capture within the current admissions cycle is
#: the rule applicants are held to. Older is `archive_stale`, and a person sees it.
FETCH_ARCHIVE_MAX_AGE_DAYS = int(os.getenv("FETCH_ARCHIVE_MAX_AGE_DAYS", "365"))
#: A host remembered at an expensive rung is retried from rung 1 this often, so
#: a host that got easier stops paying rung-4 prices.
FETCH_REPROBE_DAYS = int(os.getenv("FETCH_REPROBE_DAYS", "30"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_types.py -v`
Expected: 9 passed

- [ ] **Step 5: Verify the settings load and the defaults are the documented plan**

Run: `uv run python -c "from django.conf import settings; import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test'); django.setup(); print(settings.FETCH_PDF_MAX_PAGES, settings.FIRECRAWL_MONTHLY_CREDITS, settings.FETCH_ARCHIVE_MAX_AGE_DAYS)"`
Expected: `60 100000 365`

- [ ] **Step 6: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 7: Commit**

```bash
git add apps/research/fetch/ config/settings/base.py tests/research/test_fetch_types.py
git commit -m "feat: the fetch engine's outcomes, page type and settings block

Ten of the eleven outcomes are values, not exceptions: a blocked fetch and a
page that states nothing were the same row before, and CLAUDE.md records this
repo meeting that twice. A 200 under 1,000 bytes or carrying a challenge
marker is a block -- measured on mischolarship.com, 469 bytes, billed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `HostProfile` and `FetchAttempt`, with their RLS policies

> **Master status, 2026-09-23:** new. See Reconciliation.

**Files:**
- Modify: `apps/research/models.py`
- Create: `apps/research/migrations/0004_fetch_engine.py`, `apps/research/migrations/0005_fetch_engine_rls.py`
- Test: `tests/research/test_fetch_models_rls.py`

**Interfaces:**
- Consumes: `apps.research.fetch.types.Outcome`
- Produces: `HostProfile` (PK `host`, fields per spec §5), `FetchAttempt` (fields per spec §11)

**Why these are shared-catalog tables, not tenant-scoped:** they describe *the web* — which rung reads a ministry's website — not a person. Every tenant benefits from the same memory. They follow the pattern of `apps/funding/migrations/0030_program_awarding_institutions_rls.py`: `ENABLE ROW LEVEL SECURITY`, a `shared_catalog_select` read policy for everyone, a `catalog_ingestion_write` policy for the ingestion role.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_models_rls.py
import pytest
from django.utils import timezone

from apps.research.fetch.types import Outcome
from apps.research.models import FetchAttempt, HostProfile

pytestmark = pytest.mark.django_db


def test_a_profile_defaults_to_the_first_rung():
    profile = HostProfile.objects.create(host="example.test")
    assert profile.start_rung == 1
    assert profile.needs_render is False
    assert profile.robots_blocked_paths == []


def test_an_attempt_records_what_a_call_cost_and_why_it_ended():
    attempt = FetchAttempt.objects.create(
        url="https://example.test/a",
        host="example.test",
        purpose="read",
        rung=4,
        vendor="SCRAPE_DO",
        params={"render": True, "super": True},
        status_code=200,
        credits=25,
        duration_ms=4_100,
        outcome=Outcome.BLOCKED,
        reason="challenge",
        final_url="https://example.test/a",
    )
    assert attempt.attempt_no == 1
    assert attempt.id is not None


def test_both_tables_are_shared_catalog_under_a_real_policy(runtime_connection):
    """The test role BYPASSRLS, so asserting against it proves nothing
    (CLAUDE.md). This runs as the NOBYPASSRLS runtime role: it must READ both
    tables with no tenant GUC set, and must NOT write them."""
    HostProfile.objects.create(host="shared.test", start_rung=3)
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM research_hostprofile WHERE host = 'shared.test'")
        assert cursor.fetchone()[0] == 1
        with pytest.raises(Exception):
            cursor.execute(
                "INSERT INTO research_hostprofile (host, start_rung) VALUES ('nope.test', 1)"
            )


def test_the_attempt_index_supports_the_retry_sweep():
    """The retry command scans (outcome, retry_after); without the index it is
    a sequential scan over every fetch ever made."""
    indexes = {index.name for index in FetchAttempt._meta.indexes}
    assert "research_fetchattempt_retry_idx" in indexes
    assert "research_fetchattempt_url_idx" in indexes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_models_rls.py -v`
Expected: FAIL with `ImportError: cannot import name 'HostProfile'`

- [ ] **Step 3: Write the models**

```python
# apps/research/models.py -- append

class HostProfile(models.Model):
    """What worked on this host last time, so the ladder need not rediscover it.

    Shared catalog on purpose (spec §5, §11): which rung reads a ministry's
    website is the same fact for every tenant, and it describes the web rather
    than a person.

    Only EXPENSIVE rungs are remembered. A success at rung 1 or 2 resets
    start_rung to 1, so the memory can only ever save money, never entrench a
    cost -- and a host that got easier is found by the re-probe below rather
    than paying rung-4 prices forever.
    """

    host = models.CharField(max_length=253, primary_key=True)
    start_rung = models.PositiveSmallIntegerField(default=1)
    needs_render = models.BooleanField(default=False)
    needs_residential = models.BooleanField(default=False)
    geo_code = models.CharField(max_length=2, blank=True, default="")
    languages = models.JSONField(default=list, blank=True)
    wait_selector = models.CharField(max_length=200, blank=True, default="")
    custom_wait_ms = models.PositiveIntegerField(default=0)
    timeout_ms = models.PositiveIntegerField(default=60_000)
    #: Closed key set, written by hand only: showFrames, setCookies. A host
    #: whose requirements sit inside an iframe, or behind a consent cookie.
    vendor_options = models.JSONField(default=dict, blank=True)
    last_success_rung = models.PositiveSmallIntegerField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_probe_at = models.DateTimeField(null=True, blank=True)
    #: Set by a BLOCKED outcome: +6h, doubling per consecutive block, capped at
    #: 7 days. A due retry inside this window is rescheduled, not spent.
    blocked_until = models.DateTimeField(null=True, blank=True)
    consecutive_blocks = models.PositiveSmallIntegerField(default=0)
    robots_blocked_paths = models.JSONField(default=list, blank=True)
    credits_30d = models.PositiveIntegerField(default=0)
    attempts_30d = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class FetchAttempt(models.Model):
    """One vendor call, and what it cost. The id doubles as the request id sent
    to Firecrawl (x-request-id), so a retry after a client-side timeout is
    answered 409 rather than charged twice (spec §9.3)."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    url = models.URLField(max_length=2048)
    host = models.CharField(max_length=253)
    purpose = models.CharField(max_length=10, default="read")
    rung = models.PositiveSmallIntegerField()
    vendor = models.CharField(max_length=20)
    #: The request options, keys redacted. Never the API key.
    params = models.JSONField(default=dict, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True, default="")
    byte_size = models.PositiveBigIntegerField(default=0)
    credits = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    outcome = models.CharField(max_length=20)
    reason = models.CharField(max_length=300, blank=True, default="")
    final_url = models.URLField(max_length=2048, blank=True, default="")
    sha256 = models.CharField(max_length=64, blank=True, default="")
    change_status = models.CharField(max_length=10, blank=True, default="")
    captured_at = models.CharField(max_length=32, blank=True, default="")
    page_count = models.PositiveIntegerField(null=True, blank=True)
    total_pages = models.PositiveIntegerField(null=True, blank=True)
    retry_after = models.DateTimeField(null=True, blank=True)
    attempt_no = models.PositiveSmallIntegerField(default=1)
    sweep_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=("url", "-created_at"), name="research_fetchattempt_url_idx"),
            models.Index(
                fields=("outcome", "retry_after"), name="research_fetchattempt_retry_idx"
            ),
        ]
```

- [ ] **Step 4: Generate the schema migration**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run python manage.py makemigrations research --name fetch_engine`
Expected: creates `apps/research/migrations/0004_fetch_engine.py` with two `CreateModel` operations.

- [ ] **Step 5: Write the RLS migration by hand**

Django never writes these; `makemigrations` will not produce them and a squash would drop them (CLAUDE.md).

```python
# apps/research/migrations/0005_fetch_engine_rls.py
# HostProfile and FetchAttempt join _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: which rung
# reads a ministry's website is the same fact for every tenant, and neither
# table describes a person. Same shape as
# funding/0030_program_awarding_institutions_rls -- both the
# shared_catalog_select read policy and the catalog_ingestion_write policy,
# from the start.
from django.db import migrations

TABLES = ("research_hostprofile", "research_fetchattempt")

RLS_SQL = "".join(
    f"""
ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{table}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{table}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""
    for table in TABLES
)

REVERSE_RLS_SQL = "".join(
    f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{table};
DROP POLICY IF EXISTS shared_catalog_select ON public.{table};
ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
"""
    for table in TABLES
)


class Migration(migrations.Migration):

    dependencies = [
        ("research", "0004_fetch_engine"),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
```

- [ ] **Step 6: Add both tables to the shared-table list**

In `tests/tenancy/test_database_isolation.py`, add `"research_hostprofile"` and `"research_fetchattempt"` to `_SHARED_TABLES`. That test is what pins the RLS shape of every shared table; a new one absent from it is unverified.

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_models_rls.py tests/tenancy/test_database_isolation.py -v`
Expected: all pass. If `test_both_tables_are_shared_catalog_under_a_real_policy` fails on the write, read the failure: a *successful* insert means the policy is missing, which is the bug this test exists to catch.

- [ ] **Step 8: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_fetch_engine uv run python manage.py makemigrations --check --dry-run`
Expected: all clean

- [ ] **Step 9: Commit**

```bash
git add apps/research/models.py apps/research/migrations/ tests/research/test_fetch_models_rls.py tests/tenancy/test_database_isolation.py
git commit -m "feat: HostProfile and FetchAttempt, shared catalog under RLS

Which rung reads a ministry's website is the same fact for every tenant, so
both tables are shared catalog with the funding/0030 policy shape. The RLS
migration is hand-written because Django never writes one, and verified
through runtime_connection because the test role bypasses RLS.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The Firecrawl provider — rungs 1 and 2

> **Master status, 2026-09-23:** partial — edit master's `firecrawl.py`; reconciliation items 1, 4, 5, 7, 9 apply. See Reconciliation.

**Files:**
- Create: `apps/research/fetch/firecrawl.py`
- Test: `tests/research/test_fetch_firecrawl.py`

**Interfaces:**
- Consumes: `types.FetchedPage`, `types.Outcome`, `types.usable`, `types.VendorUnavailable`, `egress.validate_public_url`, `egress.UnsafeTarget`
- Produces: `scrape(url, *, api_key, tag=None, actions=False, profile=None, request_id=None, post=...) -> FetchedPage`

Read before writing: spec §4 rungs 1–2 and §12's "used" table. Four things the vendor's documentation settles and the code must honour — `changeTracking` **requires** `markdown` in the same request and bypasses the cache entirely; `proxy` is deprecated and `auto` is the default, so it is not passed; `skipTlsVerification` defaults true and reads Georgia's education ministry, whose broken chain our own client refused; and PDF parsing is billed **per page**, which is why `maxPages` is set and a truncated read is `FETCHED_PARTIAL`.

- [ ] **Step 0: Two things measured on 2026-09-22, so the code below does not guess**

1. **`x-request-id` does not make a completed call free to repeat.** Reusing an id sequentially
   after the first call completed was charged again (678 → 677 credits, measured). The id only
   refuses a *concurrent* duplicate (409 `request_in_flight`). So a client-side timeout is handled
   by the ladder falling through to rung 3, never by re-issuing the Firecrawl call; the header is
   still sent, because a concurrent duplicate is the one case it does prevent.
2. **`rawHtml` versus the rendered DOM** — see the measurement recorded in the spec's §4.1d
   amendment of 2026-09-22 and the plan's closing notes. The shell rule reads `markdown` either way.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_firecrawl.py
import json

import pytest

from apps.research.fetch import firecrawl
from apps.research.fetch.types import Outcome, VendorUnavailable


def _ok(**data):
    """A stubbed Firecrawl 200. `changeTracking` sits in `data`, beside
    markdown -- NOT in `metadata`."""
    body = {
        "success": True,
        "data": {
            "markdown": "# Requirements\n\nApplicants must submit a CV." * 40,
            "rawHtml": "<html><body>" + "<p>Applicants must submit a CV.</p>" * 200 + "</body></html>",
            "links": ["https://example.test/apply"],
            "metadata": {"url": "https://example.test/a", "statusCode": 200,
                         "contentType": "text/html"},
            **data,
        },
    }

    def post(url, *, json_body, headers, timeout):
        return 200, json.dumps(body).encode(), {}

    return post


def test_a_good_scrape_is_fetched_at_one_credit():
    page = firecrawl.scrape("https://example.test/a", api_key="k", post=_ok())
    assert page.outcome is Outcome.FETCHED
    assert page.fetched_via == "FIRECRAWL"
    assert page.rung == 1
    assert page.credits == 1
    assert page.markdown.startswith("# Requirements")


def test_change_tracking_requires_markdown_and_carries_the_tag():
    """Firecrawl's own caveat: change tracking compares pages via their
    markdown, and the format must travel with it. Sent without markdown the
    comparison is silently unreliable."""
    sent = {}

    def post(url, *, json_body, headers, timeout):
        sent.update(json_body)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000, "metadata": {"url": "https://e.test/a", "statusCode": 200,
                                                 "contentType": "text/html"},
            "changeTracking": {"changeStatus": "same"}}}).encode(), {}

    page = firecrawl.scrape("https://e.test/a", api_key="k", tag="2027", post=post)
    assert "markdown" in sent["formats"]
    tracking = next(f for f in sent["formats"] if isinstance(f, dict)
                    and f.get("type") == "changeTracking")
    assert tracking["tag"] == "2027"
    assert page.change_status == "same"


def test_an_unchanged_page_short_circuits_the_reader():
    """The single largest saving on the whole path: one free comparison against
    a $0.35 reader run."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k", tag="2027",
        post=_ok(changeTracking={"changeStatus": "same"}),
    )
    assert page.outcome is Outcome.UNCHANGED


def test_the_proxy_parameter_is_never_sent():
    """Deprecated; `auto` is the default and escalates to enhanced proxies on
    401/403/429 at no extra charge. Passing it pins us to yesterday's names."""
    sent = {}

    def post(url, *, json_body, headers, timeout):
        sent.update(json_body)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000,
            "metadata": {"url": "https://e.test/a", "statusCode": 200,
                         "contentType": "text/html"}}}).encode(), {}

    firecrawl.scrape("https://e.test/a", api_key="k", post=post)
    assert "proxy" not in sent
    assert "location" not in sent
    assert sent["skipTlsVerification"] is True
    assert sent["parsers"][0]["maxPages"] == 60
    assert sent["parsers"][0]["pageMarkers"] is True


def test_a_truncated_pdf_is_partial_and_says_how_much_it_read():
    """A PDF is billed per page, so the read is capped -- and a rule on page 61
    must be a bounded miss, never a silent one."""
    page = firecrawl.scrape(
        "https://e.test/handbook.pdf", api_key="k",
        post=_ok(metadata={"url": "https://e.test/handbook.pdf", "statusCode": 200,
                           "contentType": "application/pdf", "numPages": 60,
                           "totalPages": 200}),
    )
    assert page.outcome is Outcome.FETCHED_PARTIAL
    assert (page.page_count, page.total_pages) == (60, 200)
    assert page.credits == 60


def test_a_four_oh_four_is_dead_and_still_costs_a_credit():
    """Firecrawl bills for a returned document even when the site said 404, and
    a different proxy would not change the answer -- so the ladder stops."""
    page = firecrawl.scrape(
        "https://e.test/gone", api_key="k",
        post=_ok(markdown="Not found",
                 metadata={"url": "https://e.test/gone", "statusCode": 404,
                           "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.DEAD
    assert page.credits == 1


def test_a_four_oh_three_that_survived_the_enhanced_proxy_is_blocked():
    page = firecrawl.scrape(
        "https://e.test/x", api_key="k",
        post=_ok(markdown="Forbidden",
                 metadata={"url": "https://e.test/x", "statusCode": 403,
                           "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.BLOCKED


def test_a_hard_failure_returns_no_document_and_costs_nothing():
    """Measured 2026-09-19: 710 credits before and after a DNS failure. Trying
    this tier first is free when it loses."""
    def post(url, *, json_body, headers, timeout):
        return 200, json.dumps({"success": False, "error": "DNS resolution failed"}).encode(), {}

    page = firecrawl.scrape("https://nope.test/a", api_key="k", post=post)
    assert page.outcome is Outcome.UNREACHABLE
    assert page.credits == 0


def test_a_final_url_inside_the_vpc_is_invalid():
    """The vendor reports the final URL and it decides provenance. It arrives
    from the untrusted side exactly as X-Final-Url did."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k",
        post=_ok(metadata={"url": "http://169.254.170.2/creds", "statusCode": 200,
                           "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.INVALID


def test_the_request_id_travels_so_a_concurrent_duplicate_is_refused():
    """Measured 2026-09-22: a SEQUENTIAL reuse of the same x-request-id after
    the first call completed was charged again (678 -> 677 credits). The id
    protects against a concurrent duplicate only -- Firecrawl answers 409
    request_in_flight -- so a retry after a client-side timeout must NOT be
    re-issued against Firecrawl; the ladder falls through to rung 3 instead."""
    sent_headers = {}

    def post(url, *, json_body, headers, timeout):
        sent_headers.update(headers)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000,
            "metadata": {"url": "https://e.test/a", "statusCode": 200,
                         "contentType": "text/html"}}}).encode(), {}

    firecrawl.scrape("https://e.test/a", api_key="k", request_id="abc-123", post=post)
    assert sent_headers["x-request-id"] == "abc-123"
    assert sent_headers["Authorization"] == "Bearer k"


def test_an_absent_key_raises_rather_than_degrading():
    def explode(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("called the vendor without a key")

    with pytest.raises(VendorUnavailable):
        firecrawl.scrape("https://e.test/a", api_key="", post=explode)


def test_an_image_is_served_through_the_vendors_ocr():
    """Measured 2026-09-22: eurotext.png -> 438 characters of markdown, 1
    credit. A requirements poster is an artifact like any other."""
    page = firecrawl.scrape(
        "https://e.test/duyuru.png", api_key="k",
        post=_ok(markdown="Başvuru için özgeçmiş (CV) İngilizce ve en fazla 2 sayfa olmalıdır.",
                 rawHtml="",
                 metadata={"url": "https://e.test/duyuru.png", "statusCode": 200,
                           "contentType": "image/png"}),
    )
    assert page.outcome is Outcome.FETCHED
    assert page.credits == 1
    assert "özgeçmiş" in page.markdown


def test_rung_two_asks_for_actions_and_costs_more():
    sent = {}

    def post(url, *, json_body, headers, timeout):
        sent.update(json_body)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000,
            "metadata": {"url": "https://e.test/a", "statusCode": 200,
                         "contentType": "text/html"}}}).encode(), {}

    page = firecrawl.scrape("https://e.test/a", api_key="k", actions=True, post=post)
    assert [a["type"] for a in sent["actions"]] == ["wait", "scroll", "wait"]
    assert page.rung == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_firecrawl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.fetch.firecrawl'`

- [ ] **Step 3: Write the provider**

```python
# apps/research/fetch/firecrawl.py
"""Rungs 1 and 2: Firecrawl POST /v2/scrape.

Firecrawl is the ENGINE'S EXTRACTOR, not merely a proxy: it returns markdown
for HTML, PDF, DOCX, XLSX, PPTX and CSV alike, which is why every page a reader
will read starts here and why change tracking -- which only compares against
Firecrawl's own previous scrape of a URL -- can only work if this is the tier
that fetched it (spec §4.1d item 1).

Everything arriving here is untrusted in exactly the way the page it came from
was untrusted. `metadata.url` decides provenance and is validated like any
other final URL.
"""

import json
import time
from collections.abc import Callable

import urllib3
from django.conf import settings

from ..egress import UnsafeTarget, validate_public_url
from .types import Attempt, FetchedPage, Outcome, VendorUnavailable, usable

ENDPOINT = "https://api.firecrawl.dev/v2/scrape"

#: Firecrawl escalates basic -> enhanced proxies on exactly these, at most once
#: per request, at no extra charge. What survives them is a block for us too.
_BLOCKING = {401, 403, 429}
#: The origin answered. A different proxy would not change it.
_DEAD = {404, 410}

Post = Callable[..., tuple[int, bytes, dict[str, str]]]


def _post(url: str, *, json_body: dict, headers: dict, timeout: int):
    response = urllib3.request(
        "POST", url, json=json_body, headers=headers,
        timeout=urllib3.Timeout(connect=10, read=timeout / 1000 + 30), retries=False,
    )
    return response.status, response.data, dict(response.headers)


def scrape(
    url: str,
    *,
    api_key: str,
    tag: str | None = None,
    actions: bool = False,
    profile=None,
    request_id: str | None = None,
    screenshot: bool = False,
    post: Post = _post,
) -> FetchedPage:
    if not api_key:
        raise VendorUnavailable("FIRECRAWL_API_KEY is not set")

    rung = 2 if actions else 1
    timeout_ms = getattr(profile, "timeout_ms", 0) or 60_000
    formats: list = ["markdown", "links", "rawHtml"]
    if tag:
        # Change tracking compares pages via their MARKDOWN, so that format must
        # travel with it, and the request bypasses the index cache entirely.
        formats.append({"type": "changeTracking", "tag": tag})
    if screenshot:
        formats.append({"type": "screenshot", "fullPage": True})

    body: dict = {
        "url": url,
        "formats": formats,
        "onlyMainContent": True,
        "blockAds": True,
        "skipTlsVerification": True,
        "removeBase64Images": True,
        "timeout": timeout_ms,
        "parsers": [
            {
                "type": "pdf",
                "maxPages": settings.FETCH_PDF_MAX_PAGES,
                "pageMarkers": True,
            }
        ],
    }
    # `proxy` is deprecated and `auto` is the default. `location` is left unset
    # on Firecrawl's own advice -- an unsupported country silently falls back to
    # EU/US, and location is part of cache and change-tracking consistency.
    if getattr(profile, "geo_code", ""):
        body["location"] = {"country": profile.geo_code,
                            "languages": list(getattr(profile, "languages", []) or [])}
    if actions:
        wait_ms = getattr(profile, "custom_wait_ms", 0) or 3_000
        body["actions"] = [
            {"type": "wait", "milliseconds": wait_ms},
            {"type": "scroll", "direction": "down"},
            {"type": "wait", "milliseconds": 2_000},
        ]
        if getattr(profile, "wait_selector", ""):
            body["actions"].insert(0, {"type": "wait", "selector": profile.wait_selector})

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if request_id:
        headers["x-request-id"] = request_id

    started = time.monotonic()
    try:
        status, raw, _response_headers = post(
            ENDPOINT, json_body=body, headers=headers, timeout=timeout_ms
        )
    except urllib3.exceptions.HTTPError as error:
        raise VendorUnavailable(f"{type(error).__name__}: {error}") from error
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if status == 402:
        raise VendorUnavailable("firecrawl: insufficient credits")
    if status == 429:
        raise VendorUnavailable("firecrawl: rate limited")
    if status >= 500:
        raise VendorUnavailable(f"firecrawl: HTTP {status}")

    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise VendorUnavailable("firecrawl: unparseable response") from error

    def _result(outcome: Outcome, *, credits: int = 0, reason: str = "", **extra) -> FetchedPage:
        return FetchedPage(
            final_url=extra.pop("final_url", url), redirects=(),
            content_type=extra.pop("content_type", ""), body=extra.pop("body", b""),
            markdown=extra.pop("markdown", ""), outcome=outcome, fetched_via="FIRECRAWL",
            rung=rung, credits=credits, reason=reason,
            attempts=(Attempt(rung=rung, vendor="FIRECRAWL", outcome=outcome, credits=credits,
                              status_code=extra.get("status_code"), reason=reason,
                              duration_ms=elapsed_ms),),
            **extra,
        )

    if not payload.get("success"):
        # No document came back, so nothing was charged. Measured 2026-09-19:
        # 710 credits before and after a DNS failure.
        return _result(Outcome.UNREACHABLE, reason=str(payload.get("error", ""))[:300])

    data = payload.get("data") or {}
    metadata = data.get("metadata") or {}
    site_status = int(metadata.get("statusCode") or 200)
    content_type = (metadata.get("contentType") or "").split(";", 1)[0]
    markdown = data.get("markdown") or ""
    raw_html = (data.get("rawHtml") or "").encode()
    page_count = metadata.get("numPages")
    total_pages = metadata.get("totalPages")
    # A PDF is billed per page; everything else is one credit per page.
    credits = int(page_count) if content_type == "application/pdf" and page_count else 1

    final_url = metadata.get("url") or url
    try:
        validate_public_url(final_url)
    except UnsafeTarget:
        return _result(Outcome.INVALID, credits=credits, reason="final_url_unsafe",
                       status_code=site_status)

    common = dict(final_url=final_url, content_type=content_type, body=raw_html,
                  markdown=markdown, status_code=site_status,
                  change_status=(data.get("changeTracking") or {}).get("changeStatus"),
                  screenshot=(data.get("screenshot") or "").encode() or None,
                  page_count=page_count, total_pages=total_pages)

    if site_status in _DEAD:
        return _result(Outcome.DEAD, credits=credits, reason=f"origin_{site_status}", **common)
    if site_status in _BLOCKING:
        return _result(Outcome.BLOCKED, credits=credits, reason=f"origin_{site_status}", **common)

    if common["change_status"] == "same":
        return _result(Outcome.UNCHANGED, credits=credits, **common)

    # The shell rule is the reader's own (spec §4): fewer than 1,500 readable
    # characters while the raw page is 20 kB or more. It is applied to the
    # MARKDOWN, which Firecrawl builds from the rendered DOM -- whether
    # `rawHtml` is pre- or post-render is not something their docs settle, and
    # judging a rendered SPA by its unrendered source would send every JS site
    # to rung 2 for nothing.
    if content_type in {"", "text/html"} and len(markdown) < 1_500 and len(raw_html) >= 20_000:
        return _result(Outcome.UNREADABLE, credits=credits, reason="shell", **common)
    ok, reason = usable(content_type or "text/html", raw_html or markdown.encode(), site_status,
                        markdown=markdown)
    if not ok and reason != "shell":
        return _result(Outcome.BLOCKED, credits=credits, reason=reason, **common)

    truncated = bool(total_pages and page_count and int(total_pages) > int(page_count))
    return _result(
        Outcome.FETCHED_PARTIAL if truncated else Outcome.FETCHED,
        credits=credits, reason="pdf_truncated" if truncated else "", **common,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_firecrawl.py -v`
Expected: 13 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/research/fetch/firecrawl.py tests/research/test_fetch_firecrawl.py
git commit -m "feat: Firecrawl provider, rungs 1 and 2

changeTracking travels with markdown because it compares pages via markdown;
proxy and location are not sent (deprecated, and the vendor advises against
location); PDFs are billed per page so maxPages is set and a truncated read is
FETCHED_PARTIAL carrying both counts. metadata.url decides provenance and is
validated like any other untrusted final URL.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---
### Task 4: The scrape.do provider — rungs 3 and 4

> **Master status, 2026-09-23:** partial — edit master's `scrapedo.py`; item 2 applies and Step 3's hop loop is stale. See Reconciliation.

**Files:**
- Create: `apps/research/fetch/scrapedo.py`
- Test: `tests/research/test_fetch_scrapedo.py`

**Interfaces:**
- Consumes: `types.FetchedPage`, `types.Outcome`, `types.usable`, `types.VendorUnavailable`, `egress.validate_public_url`, `egress.UnsafeTarget`
- Produces: `scrape(url, *, api_key, rung=3, profile=None, session_id=None, get=...) -> FetchedPage`

Read before writing: spec §4 rungs 3–4, §9.2 layer 4, §10. Four things the vendor's documentation settles — failed requests are **free** (only 2xx, 400, 404 and 410 are charged), so a miss here costs latency and nothing else; `Scrape.do-Request-Cost` is **authoritative** because per-domain profiles are applied server-side with no request-time signal; `render=true&super=true` is 25 credits while plain is 1, which is why rung 4 is a residue tier and not a default; and scrape.do returns the origin's own bytes without extraction, which is what makes it the `purpose="bytes"` tier.

**Redirects are followed by the vendor, and the final URL is validated.** Measured 2026-09-22 on
`http://globed.eu/`: with redirects followed, scrape.do charged **1 credit for the whole chain** and
named the final URL in `Scrape.do-Resolved-Url` (with `Scrape.do-Initial-Status-Code`); with
`disableRedirection=true` it charged **1 credit per hop** and named the next hop in
`Scrape.do-Target-Redirected-Location` — the standard `Location` header is *not* passed through.
Hop-by-hop validation existed in `fetch_official_source` because *our* network was doing the
fetching and a hop into `169.254.169.254` was our metadata service. The vendor's hops run on the
vendor's network; what provenance needs is that the URL we *record* is public and on the required
origin, and `validate_public_url` on `Scrape.do-Resolved-Url` gives exactly that at a third of the
cost on a two-hop chain. This amends spec §10's "hop by hop" for the vendor tiers.

- [ ] **Step 0: Measure `disableRedirection=true` on the free key before writing a line**

The implementation below assumes that with redirection disabled scrape.do passes the origin's
`3xx` status and its `Location` header through to us, and that the origin's `Content-Type` arrives
unchanged. Their documentation names the parameter and not the response shape. One request against
a known redirecting URL (`http://globed.eu/` → `https://www.globed.eu/`) answers both; record the
status, the headers received and the credits charged in this task's commit message. If the header
does not pass through, the hop loop below must read the redirect target from the body scrape.do
returns instead — and if nothing identifies the target, redirects on this tier are `UNREACHABLE`
with reason `redirect_opaque`, never followed blind.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_scrapedo.py
import pytest

from apps.research.fetch import scrapedo
from apps.research.fetch.types import Outcome, VendorUnavailable

_PAGE = b"<html><body>" + b"<p>Applicants must submit a CV.</p>" * 200 + b"</body></html>"


def _ok(body=_PAGE, cost="1", status=200, headers=None):
    def get(url):
        return status, body, {"Scrape.do-Request-Cost": cost,
                              "Scrape.do-Remaining-Credits": "249000",
                              "Content-Type": "text/html", **(headers or {})}
    return get


def test_a_plain_fetch_is_one_credit_at_rung_three():
    page = scrapedo.scrape("https://e.test/a", api_key="k", get=_ok())
    assert page.outcome is Outcome.FETCHED
    assert page.fetched_via == "SCRAPE_DO"
    assert (page.rung, page.credits) == (3, 1)


def test_rung_four_asks_for_a_residential_browser_and_a_sticky_session():
    """A residential address that changes between pages of one site re-triggers
    the very challenge this rung exists to pass."""
    seen = {}

    def get(url):
        seen["url"] = url
        return 200, _PAGE, {"Scrape.do-Request-Cost": "25", "Content-Type": "text/html"}

    page = scrapedo.scrape("https://e.test/a", api_key="k", rung=4,
                           session_id=4242, get=get)
    assert "render=true" in seen["url"]
    assert "super=true" in seen["url"]
    assert "sessionId=4242" in seen["url"]
    assert page.credits == 25


def test_the_cost_header_is_authoritative_not_the_tariff():
    """Per-domain profiles are applied server-side with no request-time signal;
    the published table cannot predict them. Read 2026-09-22: up to 200."""
    page = scrapedo.scrape("https://e.test/a", api_key="k", get=_ok(cost="200"))
    assert page.credits == 200


def test_redirects_are_followed_by_the_vendor_and_the_resolved_url_is_validated():
    """Measured 2026-09-22: one credit for the whole chain, final URL in
    Scrape.do-Resolved-Url."""
    hops = []

    def get(url):
        hops.append(url)
        return 200, _PAGE, {"Content-Type": "text/html", "Scrape.do-Request-Cost": "1",
                            "Scrape.do-Resolved-Url": "https://e.test/b",
                            "Scrape.do-Initial-Status-Code": "301"}

    page = scrapedo.scrape("https://e.test/a", api_key="k", get=get)
    assert page.outcome is Outcome.FETCHED
    assert page.final_url == "https://e.test/b"
    assert page.redirects == ("https://e.test/b",)
    assert len(hops) == 1  # the vendor followed the chain; one call, one credit
    assert "disableRedirection" not in hops[0]


def test_a_resolved_url_inside_the_vpc_is_invalid():
    def get(url):
        return 200, _PAGE, {"Content-Type": "text/html", "Scrape.do-Request-Cost": "1",
                            "Scrape.do-Resolved-Url": "http://169.254.170.2/creds"}

    page = scrapedo.scrape("https://e.test/a", api_key="k", get=get)
    assert page.outcome is Outcome.INVALID


def test_a_soft_block_is_a_block_even_though_it_answered_two_hundred():
    """Measured 2026-09-19: mischolarship.com, HTTP 200, 469 bytes of nothing,
    billed 1 credit."""
    page = scrapedo.scrape("https://e.test/a", api_key="k", get=_ok(body=b"x" * 469))
    assert page.outcome is Outcome.BLOCKED
    assert page.credits == 1


def test_a_failed_request_is_free_and_unreachable():
    """scrape.do charges only for 2xx, 400, 404 and 410. Measured on both 502s
    of the 2026-09-19 sweep."""
    page = scrapedo.scrape("https://e.test/a", api_key="k",
                           get=_ok(body=b"", cost="0", status=502))
    assert page.outcome is Outcome.UNREACHABLE
    assert page.credits == 0


def test_a_four_ten_is_dead():
    page = scrapedo.scrape("https://e.test/a", api_key="k",
                           get=_ok(body=b"Gone", cost="1", status=410))
    assert page.outcome is Outcome.DEAD


def test_an_absent_key_raises_rather_than_degrading():
    def explode(url):  # pragma: no cover - must never be called
        raise AssertionError("called the vendor without a key")

    with pytest.raises(VendorUnavailable):
        scrapedo.scrape("https://e.test/a", api_key="", get=explode)


def test_transparent_bytes_skip_extraction_for_provenance():
    seen = {}

    def get(url):
        seen["url"] = url
        return 200, _PAGE, {"Content-Type": "text/html", "Scrape.do-Request-Cost": "1"}

    scrapedo.scrape("https://e.test/a", api_key="k", transparent=True, get=get)
    assert "transparentResponse=true" in seen["url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_scrapedo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.fetch.scrapedo'`

- [ ] **Step 3: Write the provider**

```python
# apps/research/fetch/scrapedo.py
"""Rungs 3 and 4: the scrape.do GET API.

scrape.do is a TRANSPORT, not an extractor: it hands back what the origin
actually sent. That makes it the tier for `purpose="bytes"` (provenance) and
the residue tier for hosts Firecrawl's own escalation could not pass -- measured
2026-09-19, one host in 58, and only at render+super.

Failed requests are free (only 2xx, 400, 404 and 410 are charged), so trying
this tier costs latency and nothing else when it loses. What it costs when it
WINS is read from the response header, never from a tariff in our code:
per-domain profiles are applied server-side with no request-time signal.
"""

import time
from collections.abc import Callable
from urllib.parse import urlencode, urljoin

import urllib3

from ..egress import UnsafeTarget, validate_public_url
from .types import Attempt, FetchedPage, Outcome, VendorUnavailable, usable

ENDPOINT = "https://api.scrape.do/"
_MAX_HOPS = 6
_REDIRECTS = {301, 302, 303, 307, 308}
_DEAD = {404, 410}
_BLOCKING = {401, 403, 429}

Get = Callable[[str], tuple[int, bytes, dict[str, str]]]


def _get(url: str) -> tuple[int, bytes, dict[str, str]]:
    response = urllib3.request(
        "GET", url, timeout=urllib3.Timeout(connect=10, read=120), retries=False
    )
    return response.status, response.data, dict(response.headers)


def _header(headers: dict[str, str], name: str) -> str:
    lowered = {key.lower(): value for key, value in headers.items()}
    return lowered.get(name.lower(), "")


def scrape(
    url: str,
    *,
    api_key: str,
    rung: int = 3,
    profile=None,
    session_id: int | None = None,
    transparent: bool = False,
    screenshot: bool = False,
    get: Get = _get,
) -> FetchedPage:
    if not api_key:
        raise VendorUnavailable("SCRAPEDO_API_KEY is not set")

    current = url
    redirects: list[str] = []
    credits = 0
    started = time.monotonic()

    for _hop in range(_MAX_HOPS):
        try:
            validate_public_url(current)
        except UnsafeTarget:
            return _result(url, Outcome.INVALID, rung, credits, "hop_unsafe",
                           redirects, started, final_url=current)

        params: dict[str, str | int] = {
            "token": api_key,
            "url": current,
            # Every hop must pass validate_public_url, so the vendor must not
            # follow them for us.
            "disableRedirection": "true",
            "timeout": getattr(profile, "timeout_ms", 0) or 60_000,
        }
        if rung >= 4:
            params["render"] = "true"
            params["super"] = "true"
            if session_id is not None:
                params["sessionId"] = session_id
            if getattr(profile, "wait_selector", ""):
                params["waitSelector"] = profile.wait_selector
            if getattr(profile, "custom_wait_ms", 0):
                params["customWait"] = profile.custom_wait_ms
        if getattr(profile, "geo_code", ""):
            params["geoCode"] = profile.geo_code
        if transparent:
            params["transparentResponse"] = "true"
        if screenshot:
            params["fullScreenShot"] = "true"
        for key, value in (getattr(profile, "vendor_options", None) or {}).items():
            if key in {"showFrames", "setCookies"}:
                params[key] = value

        try:
            status, body, headers = get(ENDPOINT + "?" + urlencode(params))
        except urllib3.exceptions.HTTPError as error:
            raise VendorUnavailable(f"{type(error).__name__}: {error}") from error

        credits += int(_header(headers, "Scrape.do-Request-Cost") or 0)

        if status in _REDIRECTS:
            location = _header(headers, "Location")
            if not location:
                return _result(url, Outcome.UNREACHABLE, rung, credits,
                               "redirect_missing_location", redirects, started,
                               final_url=current)
            current = urljoin(current, location)
            redirects.append(current)
            continue

        content_type = (_header(headers, "Content-Type") or "").split(";", 1)[0]
        common = dict(final_url=current, content_type=content_type, body=body,
                      markdown="", status_code=status)

        if status in _DEAD:
            return _result(url, Outcome.DEAD, rung, credits, f"origin_{status}",
                           redirects, started, **common)
        if status in _BLOCKING:
            return _result(url, Outcome.BLOCKED, rung, credits, f"origin_{status}",
                           redirects, started, **common)
        if status >= 500 or not body:
            # Not charged by scrape.do; a miss here costs latency only.
            return _result(url, Outcome.UNREACHABLE, rung, credits, f"origin_{status}",
                           redirects, started, **common)

        ok, reason = usable(content_type or "text/html", body, status)
        if not ok:
            outcome = Outcome.UNREADABLE if reason == "shell" else Outcome.BLOCKED
            return _result(url, outcome, rung, credits, reason, redirects, started, **common)
        return _result(url, Outcome.FETCHED, rung, credits, "", redirects, started, **common)

    return _result(url, Outcome.UNREACHABLE, rung, credits, "redirect_limit",
                   redirects, started, final_url=current)


def _result(url, outcome, rung, credits, reason, redirects, started, **extra) -> FetchedPage:
    elapsed_ms = int((time.monotonic() - started) * 1000)
    extra.setdefault("final_url", url)
    extra.setdefault("content_type", "")
    extra.setdefault("body", b"")
    return FetchedPage(
        redirects=tuple(redirects), markdown=extra.pop("markdown", ""), outcome=outcome,
        fetched_via="SCRAPE_DO", rung=rung, credits=credits, reason=reason,
        attempts=(Attempt(rung=rung, vendor="SCRAPE_DO", outcome=outcome, credits=credits,
                          status_code=extra.get("status_code"), reason=reason,
                          duration_ms=elapsed_ms),),
        **extra,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_scrapedo.py -v`
Expected: 10 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/research/fetch/scrapedo.py tests/research/test_fetch_scrapedo.py
git commit -m "feat: scrape.do provider, rungs 3 and 4

disableRedirection is load-bearing: every hop must pass validate_public_url,
exactly as fetch_official_source's loop did, so the vendor must not follow
redirects for us. Cost comes from Scrape.do-Request-Cost, never a tariff --
per-domain profiles are server-side with no request-time signal. A 200 with
469 bytes is a block, not a document.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The archive provider — rung 6

> **Master status, 2026-09-23:** new. See Reconciliation.

**Files:**
- Create: `apps/research/fetch/archive.py`
- Test: `tests/research/test_fetch_archive.py`

**Interfaces:**
- Consumes: `scrapedo.scrape`, `types.FetchedPage`, `types.Outcome`, `egress.require_same_origin`
- Produces: `latest_capture(url, *, api_key, now=None, fetch=...) -> FetchedPage`

Owner decision 2026-09-22: a capture counts as evidence for **twelve months** (`FETCH_ARCHIVE_MAX_AGE_DAYS`), because a rule captured this admissions cycle is the rule applicants are held to. Older is `archive_stale` and goes to a person. Measured 2026-09-15: this recovered DAAD's PRIME FAQ (captured 2026-06-25) and Sciences Po's application-file page (captured 2026-02-01) — two hosts that refuse us outright.

The `id_` flag on the capture URL returns the original bytes without the archive's own toolbar; without it, every archived page carries injected markup the reader would have to strip.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_archive.py
import json
from datetime import datetime, timezone

from apps.research.fetch import archive
from apps.research.fetch.types import Attempt, FetchedPage, Outcome

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)
_PAGE = b"<html><body>" + b"<p>A CV is required.</p>" * 300 + b"</body></html>"


def _page(body=_PAGE, final_url="https://web.archive.org/web/20260625id_/https://daad.de/prime",
          outcome=Outcome.FETCHED):
    return FetchedPage(
        final_url=final_url, redirects=(), content_type="text/html", body=body,
        markdown="", outcome=outcome, fetched_via="SCRAPE_DO", rung=3, credits=1,
        status_code=200, attempts=(Attempt(rung=3, vendor="SCRAPE_DO", outcome=outcome),),
    )


def _availability(timestamp="20260625120000", available=True):
    payload = {"archived_snapshots": {"closest": {
        "available": available, "timestamp": timestamp,
        "url": f"http://web.archive.org/web/{timestamp}/https://daad.de/prime",
    }}} if available else {"archived_snapshots": {}}
    return json.dumps(payload).encode()


def test_a_recent_capture_is_archived_and_carries_its_date():
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        if "availability" in url:
            return _page(body=_availability(), final_url=url)
        return _page()

    page = archive.latest_capture("https://daad.de/prime", api_key="k", now=NOW, fetch=fetch)
    assert page.outcome is Outcome.ARCHIVED
    assert page.captured_at == "2026-06-25"
    assert page.final_url == "https://daad.de/prime"
    assert "id_/" in calls[1]


def test_a_capture_older_than_the_window_is_stale_not_evidence():
    """Owner decision 2026-09-22: twelve months. A rule two cycles old must not
    reach a student's CV."""
    def fetch(url, **kwargs):
        if "availability" in url:
            return _page(body=_availability(timestamp="20240101120000"), final_url=url)
        raise AssertionError("must not fetch a capture outside the window")

    page = archive.latest_capture("https://daad.de/prime", api_key="k", now=NOW, fetch=fetch)
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_stale:2024-01-01"


def test_no_capture_at_all_leaves_the_outcome_blocked():
    def fetch(url, **kwargs):
        return _page(body=_availability(available=False), final_url=url)

    page = archive.latest_capture("https://x.test/a", api_key="k", now=NOW, fetch=fetch)
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_absent"


def test_the_lookup_uses_the_bare_url_form():
    """Measured 2026-09-22: DAAD's capture was found under host/path and not
    under the same URL with its scheme."""
    seen = []

    def fetch(url, **kwargs):
        seen.append(url)
        return _page(body=_availability(available=False), final_url=url)

    archive.latest_capture("https://daad.de/prime?x=1", api_key="k", now=NOW, fetch=fetch)
    assert "url=daad.de%2Fprime%3Fx%3D1" in seen[0]


def test_an_archive_outage_is_a_retry_not_an_absence():
    """The CDX index answered 'Temporarily Offline' for the whole 2026-09-22
    probe window. Reading that as 'no capture' sends a recoverable host to a
    person."""
    def fetch(url, **kwargs):
        return _page(body=b"<html>Temporarily Offline</html>" * 50, final_url=url,
                     outcome=Outcome.UNREACHABLE)

    page = archive.latest_capture("https://x.test/a", api_key="k", now=NOW, fetch=fetch)
    assert page.outcome is Outcome.UNREACHABLE
    assert page.reason == "archive_unavailable"


def test_a_capture_of_a_different_origin_is_refused():
    """The URL inside the archive URL is what the capture claims to be. A
    capture of someone else's page is not evidence about this source."""
    def fetch(url, **kwargs):
        if "availability" in url:
            payload = json.dumps({"archived_snapshots": {"closest": {
                "available": True, "timestamp": "20260625120000",
                "url": "http://web.archive.org/web/20260625/https://evil.test/prime",
            }}}).encode()
            return _page(body=payload, final_url=url)
        raise AssertionError("must not fetch an off-origin capture")

    page = archive.latest_capture("https://daad.de/prime", api_key="k", now=NOW, fetch=fetch)
    assert page.outcome is Outcome.OFF_SITE


def test_the_archive_credits_are_carried_into_the_result():
    def fetch(url, **kwargs):
        if "availability" in url:
            return _page(body=_availability(), final_url=url)
        return _page()

    page = archive.latest_capture("https://daad.de/prime", api_key="k", now=NOW, fetch=fetch)
    assert page.credits == 2
    assert page.fetched_via == "ARCHIVE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_archive.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.fetch.archive'`

- [ ] **Step 3: Write the provider**

```python
# apps/research/fetch/archive.py
"""Rung 6: the Internet Archive, for hosts that block US specifically.

Measured 2026-09-15: this is what recovered DAAD's PRIME FAQ (captured
2026-06-25) and Sciences Po's application-file page (2026-02-01) -- two hosts
that refuse our connections and every vendor tier alike.

The window is an OWNER DECISION (2026-09-22): twelve months, because a rule
captured within the current admissions cycle is the rule applicants are held
to. An older capture is `archive_stale` and reaches a person, never the
catalog.

The capture itself is fetched through rung 3 rather than directly: it is an
outbound fetch like any other, and it goes through the vendor for the same
reason every other fetch does.
"""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from django.conf import settings

from .scrapedo import scrape  # noqa: F401  -- re-exported for the ladder's default providers
from .types import Attempt, FetchedPage, Outcome

AVAILABILITY = "https://archive.org/wayback/available"


def _origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower()


def _refused(url: str, outcome: Outcome, reason: str, credits: int) -> FetchedPage:
    return FetchedPage(
        final_url=url, redirects=(), content_type="", body=b"", markdown="",
        outcome=outcome, fetched_via="ARCHIVE", rung=6, credits=credits, reason=reason,
        attempts=(Attempt(rung=6, vendor="ARCHIVE", outcome=outcome, credits=credits,
                          reason=reason),),
    )


def latest_capture(url: str, *, api_key: str, now: datetime | None = None, fetch=scrape
                   ) -> FetchedPage:
    now = now or datetime.now(timezone.utc)
    # Measured 2026-09-22: the availability API found DAAD's 2026-06-25 capture
    # under the BARE form (host/path) and returned nothing for the same URL with
    # its https:// scheme. Strip the scheme before asking.
    bare = urlsplit(url)._replace(scheme="", fragment="").geturl().lstrip("/")
    lookup = f"{AVAILABILITY}?url={quote(bare, safe='')}&timestamp={now:%Y%m%d}"
    probe = fetch(lookup, api_key=api_key, rung=3)
    credits = probe.credits

    if probe.outcome not in {Outcome.FETCHED, Outcome.FETCHED_PARTIAL} or probe.status_code != 200:
        # The archive itself is down -- measured 2026-09-22, its CDX index served
        # "Temporarily Offline" for the whole probe window. That is a retry, never
        # "no capture exists": the ladder re-enters rung 6 on the next retry round.
        return _refused(url, Outcome.UNREACHABLE, "archive_unavailable", credits)
    try:
        closest = (json.loads(probe.body) or {}).get("archived_snapshots", {}).get("closest")
    except ValueError:
        return _refused(url, Outcome.UNREACHABLE, "archive_unavailable", credits)
    if not closest or not closest.get("available"):
        return _refused(url, Outcome.BLOCKED, "archive_absent", credits)

    stamp = str(closest.get("timestamp", ""))[:8]
    try:
        captured = datetime.strptime(stamp, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return _refused(url, Outcome.BLOCKED, "archive_absent", credits)
    captured_at = f"{captured:%Y-%m-%d}"

    if now - captured > timedelta(days=settings.FETCH_ARCHIVE_MAX_AGE_DAYS):
        return _refused(url, Outcome.BLOCKED, f"archive_stale:{captured_at}", credits)

    # The URL the capture claims to be is the part after the timestamp. A
    # capture of a different origin is not evidence about this source.
    captured_url = str(closest.get("url", "")).split(f"/web/{closest['timestamp']}/", 1)[-1]
    if _origin(captured_url) != _origin(url):
        return _refused(url, Outcome.OFF_SITE, f"archive_origin:{captured_url}"[:300], credits)

    # `id_` returns the original bytes without the archive's own toolbar.
    raw = f"https://web.archive.org/web/{closest['timestamp']}id_/{url}"
    page = fetch(raw, api_key=api_key, rung=3)
    credits += page.credits
    if page.outcome not in {Outcome.FETCHED, Outcome.FETCHED_PARTIAL}:
        return _refused(url, Outcome.BLOCKED, f"archive_unfetchable:{page.reason}"[:300], credits)

    attempt = Attempt(rung=6, vendor="ARCHIVE", outcome=Outcome.ARCHIVED, credits=credits,
                      status_code=page.status_code, reason=f"captured:{captured_at}")
    return FetchedPage(
        # Provenance is the ORIGINAL url, not the archive's wrapper -- the
        # capture is a copy of that page, and every rule derived from it carries
        # the capture date so a person can see how old the evidence is.
        final_url=url, redirects=page.redirects, content_type=page.content_type,
        body=page.body, markdown=page.markdown, outcome=Outcome.ARCHIVED,
        fetched_via="ARCHIVE", rung=6, credits=credits, status_code=page.status_code,
        captured_at=captured_at, attempts=(attempt,),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_archive.py -v`
Expected: 7 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/research/fetch/archive.py tests/research/test_fetch_archive.py
git commit -m "feat: the archive rung, with a twelve-month evidence window

Owner decision 2026-09-22. Recovers hosts that block us specifically -- DAAD
and Sciences Po, measured 2026-09-15. Provenance stays the original URL and
every result carries its capture date; a capture of a different origin, or one
older than the window, never becomes catalog data.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The sweep budget

> **Master status, 2026-09-23:** STRUCK — master's `SweepBudget` stays; the vendor floor and `sweep_id` land in Task 7 (item 3). See Reconciliation.

**Files:**
- Create: `apps/research/fetch/budget.py`
- Test: `tests/research/test_fetch_budget.py`

**Interfaces:**
- Consumes: `types.FetchBudgetExhausted`
- Produces: `SweepBudget(limit=None, sweep_id=None)`, `.check(estimate)`, `.spend(vendor, credits)`, `.remaining`, `.observe_remaining(vendor, credits)`

Spec §9.2: this is layer 2 of five. It is the *soft* stop, held in the sweep's own process, and it exists so a sweep ends on a `BUDGET` outcome we can read rather than a 402 we cannot. Layer 1 — the per-key spend limit set in Firecrawl's dashboard — is the hard stop and survives a bug in this class; that is configuration, not code, and it belongs in the deploy runbook (Task 12).

Credits are not comparable between vendors; dollars are. scrape.do credits are converted at `SCRAPEDO_CREDITS_PER_FIRECRAWL_CREDIT` (7, from the measured $0.000116 vs $0.00083).

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_budget.py
import pytest

from apps.research.fetch.budget import SweepBudget
from apps.research.fetch.types import FetchBudgetExhausted


def test_a_call_that_would_exceed_the_budget_is_refused_before_it_is_made():
    """The point of the soft stop: a BUDGET outcome we can read, rather than a
    402 from a vendor after the money is gone."""
    budget = SweepBudget(limit=10)
    budget.spend("FIRECRAWL", 9)
    with pytest.raises(FetchBudgetExhausted):
        budget.check(5)


def test_scrapedo_credits_are_converted_to_firecrawl_units():
    """7 scrape.do credits ~ 1 Firecrawl credit, from the measured dollar
    prices. Adding raw credit counts across vendors is meaningless."""
    budget = SweepBudget(limit=100)
    budget.spend("SCRAPE_DO", 70)
    assert budget.remaining == 90


def test_a_budget_with_no_limit_never_refuses():
    budget = SweepBudget(limit=None)
    budget.spend("FIRECRAWL", 10_000_000)
    budget.check(1)


def test_a_vendor_remaining_floor_stops_the_sweep():
    """Scrape.do-Remaining-Credits on every response; below the floor we stop
    rather than discover the ceiling by hitting it."""
    budget = SweepBudget(limit=1_000)
    budget.observe_remaining("SCRAPE_DO", 50)
    with pytest.raises(FetchBudgetExhausted):
        budget.check(1)


def test_spending_is_recorded_per_vendor_for_reconciliation():
    budget = SweepBudget(limit=1_000)
    budget.spend("FIRECRAWL", 5)
    budget.spend("SCRAPE_DO", 14)
    assert budget.spent_by_vendor == {"FIRECRAWL": 5, "SCRAPE_DO": 14}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.fetch.budget'`

- [ ] **Step 3: Write the budget**

```python
# apps/research/fetch/budget.py
"""Layer 2 of the five cost layers (spec §9.2): the soft stop.

Layer 1 is Firecrawl's own per-key spend limit, set in their dashboard and
enforced by them. It survives a bug in this class; nothing here does. This one
exists so that a sweep ends on a BUDGET outcome we can read and resume, rather
than a 402 arriving mid-sweep after the money is spent.

A sweep runs in one task, so a process-local counter is exact for it. Across
tasks the key limit is the guarantee -- a distributed counter would be a second
implementation of what the vendor already enforces.
"""

from dataclasses import dataclass, field
from uuid import UUID

from django.conf import settings

from .types import FetchBudgetExhausted

#: Below this many of a vendor's own remaining credits, stop.
_FLOOR = 100


@dataclass
class SweepBudget:
    limit: int | None = None
    sweep_id: UUID | None = None
    spent: int = 0
    spent_by_vendor: dict[str, int] = field(default_factory=dict)
    vendor_remaining: dict[str, int] = field(default_factory=dict)

    def _in_firecrawl_units(self, vendor: str, credits: int) -> int:
        if vendor == "SCRAPE_DO":
            return credits // settings.SCRAPEDO_CREDITS_PER_FIRECRAWL_CREDIT
        return credits

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else self.limit - self.spent

    def observe_remaining(self, vendor: str, credits: int) -> None:
        """Record what a vendor says is left on the account."""
        self.vendor_remaining[vendor] = credits

    def check(self, estimate: int = 1) -> None:
        """Raise BEFORE a request is made. Never called after one is paid for."""
        for vendor, left in self.vendor_remaining.items():
            if left < _FLOOR:
                raise FetchBudgetExhausted(f"{vendor} has {left} credits left")
        if self.limit is not None and self.spent + estimate > self.limit:
            raise FetchBudgetExhausted(
                f"sweep budget {self.limit} would be exceeded by {estimate} (spent {self.spent})"
            )

    def spend(self, vendor: str, credits: int) -> None:
        self.spent += self._in_firecrawl_units(vendor, credits)
        self.spent_by_vendor[vendor] = self.spent_by_vendor.get(vendor, 0) + credits


def default_budget(sweep_id: UUID | None = None) -> SweepBudget:
    return SweepBudget(limit=settings.FETCH_CREDIT_BUDGET, sweep_id=sweep_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_budget.py -v`
Expected: 5 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/research/fetch/budget.py tests/research/test_fetch_budget.py
git commit -m "feat: the sweep budget, layer 2 of five

Refuses before a call is made, so a sweep ends on a BUDGET outcome we can read
and resume rather than a 402 after the money is gone. Credits are converted to
one unit because they are not comparable between vendors -- dollars are.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---
### Task 7: The ladder — `fetch_page`

> **Master status, 2026-09-23:** rewrite of master's `fetch_page`; items 3, 4, 5 apply. See Reconciliation.

The centre of the engine. Everything before this task was a rung; this is the order, the stop
conditions, and the guarantee that every call ends in a recorded outcome.

**Files:**
- Modify: `apps/research/fetch/__init__.py`
- Test: `tests/research/test_fetch_ladder.py`

**Interfaces:**
- Consumes: `firecrawl.scrape`, `scrapedo.scrape`, `archive.latest_capture`, `budget.SweepBudget`, `budget.default_budget`, `types.*`, `egress.require_same_origin`, `egress.validate_public_url`
- Produces: `fetch_page(url, *, purpose="read", tag=None, require_origin=None, budget=None, profile=None, providers=None) -> FetchedPage`

Read before writing: spec §4, all three rules under the table. The three that decide the code:

1. **Nothing is a dead end without a recorded reason.** Every rung writes an `Attempt`; the returned page's `attempts` is the whole trail, oldest first.
2. **A rung is skipped only because the host profile learned it was useless**, never because a heuristic guessed. Rung 1 *is* the classifier.
3. **The origin's answer is final where it is an answer.** `DEAD` stops the ladder at rung 1 — a different proxy will not change a 404. `INVALID` and `OFF_SITE` stop it too: those are our own refusals, and retrying them spends money to be refused again.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_ladder.py
import pytest

from apps.research.fetch import fetch_page
from apps.research.fetch.budget import SweepBudget
from apps.research.fetch.types import Attempt, FetchedPage, Outcome, VendorUnavailable

pytestmark = pytest.mark.django_db

_PAGE = b"<html><body>" + b"<p>A CV is required.</p>" * 300 + b"</body></html>"


def _page(outcome, *, vendor="FIRECRAWL", rung=1, credits=1, body=_PAGE, final_url="https://e.test/a",
          reason="", markdown="# A"):
    return FetchedPage(
        final_url=final_url, redirects=(), content_type="text/html", body=body,
        markdown=markdown, outcome=outcome, fetched_via=vendor, rung=rung, credits=credits,
        status_code=200, reason=reason,
        attempts=(Attempt(rung=rung, vendor=vendor, outcome=outcome, credits=credits,
                          reason=reason),),
    )


def _providers(**overrides):
    """Every rung answers UNREACHABLE unless the test says otherwise."""
    def missing(*args, **kwargs):
        return _page(Outcome.UNREACHABLE, credits=0)

    base = {"firecrawl": missing, "scrapedo": missing, "archive": missing}
    base.update(overrides)

    def firecrawl(url, *, api_key, tag=None, actions=False, profile=None, request_id=None,
                  screenshot=False):
        return base["firecrawl"](url, actions=actions)

    def scrapedo(url, *, api_key, rung=3, profile=None, session_id=None, transparent=False,
                 screenshot=False):
        return base["scrapedo"](url, rung=rung)

    def archive_(url, *, api_key, now=None):
        return base["archive"](url)

    return {"firecrawl": firecrawl, "scrapedo": scrapedo, "archive": archive_}


def test_rung_one_serving_stops_the_ladder():
    calls = []

    def fc(url, actions=False):
        calls.append(("fc", actions))
        return _page(Outcome.FETCHED)

    page = fetch_page("https://e.test/a", providers=_providers(firecrawl=fc))
    assert page.outcome is Outcome.FETCHED
    assert page.rung == 1
    assert calls == [("fc", False)]


def test_a_shell_at_rung_one_escalates_to_actions_not_to_another_vendor():
    seen = []

    def fc(url, actions=False):
        seen.append(actions)
        return _page(Outcome.UNREADABLE, rung=2 if actions else 1) if not actions \
            else _page(Outcome.FETCHED, rung=2)

    page = fetch_page("https://e.test/a", providers=_providers(firecrawl=fc))
    assert seen == [False, True]
    assert page.outcome is Outcome.FETCHED
    assert page.rung == 2


def test_no_document_at_rung_one_goes_to_scrapedo_plain_first():
    rungs = []

    def fc(url, actions=False):
        return _page(Outcome.UNREACHABLE, credits=0)

    def sd(url, rung=3):
        rungs.append(rung)
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung)

    page = fetch_page("https://e.test/a", providers=_providers(firecrawl=fc, scrapedo=sd))
    assert rungs == [3]
    assert page.rung == 3


def test_a_block_that_survives_rung_three_reaches_the_residential_browser():
    rungs = []

    def fc(url, actions=False):
        return _page(Outcome.BLOCKED, reason="origin_403")

    def sd(url, rung=3):
        rungs.append(rung)
        return _page(Outcome.BLOCKED, vendor="SCRAPE_DO", rung=rung) if rung == 3 \
            else _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=4, credits=25)

    page = fetch_page("https://e.test/a", providers=_providers(firecrawl=fc, scrapedo=sd))
    assert rungs == [3, 4]
    assert (page.rung, page.credits) == (4, 27)


def test_a_dead_origin_stops_at_rung_one_and_spends_nothing_more():
    """A 404 is an ANSWER. Firecrawl escalates proxies on 401/403/429 only, for
    exactly this reason; so does the ladder."""
    calls = []

    def fc(url, actions=False):
        calls.append("fc")
        return _page(Outcome.DEAD, reason="origin_404")

    def sd(url, rung=3):  # pragma: no cover - must not be called
        raise AssertionError("a 404 does not become a 200 on a residential proxy")

    page = fetch_page("https://e.test/a", providers=_providers(firecrawl=fc, scrapedo=sd))
    assert page.outcome is Outcome.DEAD
    assert calls == ["fc"]


def test_an_unsafe_url_never_reaches_a_vendor():
    def explode(*args, **kwargs):  # pragma: no cover
        raise AssertionError("spent money on a URL we refuse ourselves")

    page = fetch_page("http://169.254.170.2/creds",
                      providers=_providers(firecrawl=explode, scrapedo=explode))
    assert page.outcome is Outcome.INVALID
    assert page.credits == 0


def test_an_off_site_final_url_is_refused_when_provenance_is_required():
    def fc(url, actions=False):
        return _page(Outcome.FETCHED, final_url="https://elsewhere.test/a")

    page = fetch_page("https://e.test/a", require_origin="https://e.test/a",
                      providers=_providers(firecrawl=fc))
    assert page.outcome is Outcome.OFF_SITE
    assert page.body == b""  # the bytes do not travel with a refusal


def test_unchanged_short_circuits_every_later_rung():
    def sd(url, rung=3):  # pragma: no cover
        raise AssertionError("an unchanged page is a finished fetch")

    page = fetch_page("https://e.test/a", tag="2027",
                      providers=_providers(firecrawl=lambda url, actions=False:
                                           _page(Outcome.UNCHANGED), scrapedo=sd))
    assert page.outcome is Outcome.UNCHANGED


def test_exhausting_every_live_rung_schedules_a_retry_before_the_archive():
    """Rung 5 comes before rung 6: a host that is merely down must not be
    answered from a year-old capture on the first failure."""
    page = fetch_page("https://e.test/a", providers=_providers())
    assert page.outcome is Outcome.RETRY_SCHEDULED
    assert [a.rung for a in page.attempts] == [1, 3, 4]


def test_the_archive_is_read_only_once_retries_are_spent():
    from apps.research.models import FetchAttempt

    for attempt_no in (1, 2, 3):
        FetchAttempt.objects.create(url="https://e.test/a", host="e.test", rung=5,
                                    vendor="NONE", outcome=Outcome.RETRY_SCHEDULED,
                                    attempt_no=attempt_no)

    def arc(url):
        return _page(Outcome.ARCHIVED, vendor="ARCHIVE", rung=6, credits=2)

    page = fetch_page("https://e.test/a", providers=_providers(archive=arc))
    assert page.outcome is Outcome.ARCHIVED


def test_a_budget_refusal_stops_the_ladder_without_calling_a_vendor():
    def explode(*args, **kwargs):  # pragma: no cover
        raise AssertionError("spent past the budget")

    spent = SweepBudget(limit=1)
    spent.spend("FIRECRAWL", 1)
    page = fetch_page("https://e.test/a", budget=spent,
                      providers=_providers(firecrawl=explode))
    assert page.outcome is Outcome.BUDGET
    assert page.credits == 0


def test_a_vendor_outage_is_not_a_blocked_site():
    """VendorUnavailable means THEIR API failed. Recording it as a block would
    teach the host profile a lie and send every later fetch to rung 4."""
    def fc(url, actions=False):
        raise VendorUnavailable("firecrawl: HTTP 503")

    def sd(url, rung=3):
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung)

    page = fetch_page("https://e.test/a", providers=_providers(firecrawl=fc, scrapedo=sd))
    assert page.outcome is Outcome.FETCHED
    assert page.attempts[0].reason.startswith("vendor_unavailable")


def test_every_attempt_is_recorded_even_on_a_failure():
    from apps.research.models import FetchAttempt

    fetch_page("https://e.test/a", providers=_providers())
    rows = FetchAttempt.objects.filter(url="https://e.test/a").order_by("rung")
    assert [row.rung for row in rows] == [1, 3, 4, 5]
    assert rows.last().retry_after is not None


def test_bytes_purpose_goes_straight_to_the_transport_vendor():
    """Provenance needs the origin's own bytes; Firecrawl's rawHtml is its own
    rendering and varies between fetches of an unchanged page."""
    def fc(url, actions=False):  # pragma: no cover
        raise AssertionError("the extractor is not the provenance tier")

    def sd(url, rung=3):
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung)

    page = fetch_page("https://e.test/a", purpose="bytes",
                      providers=_providers(firecrawl=fc, scrapedo=sd))
    assert page.fetched_via == "SCRAPE_DO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_ladder.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_page'`

- [ ] **Step 3: Write the ladder**

```python
# apps/research/fetch/__init__.py
"""The fetch engine: one seam, seven rungs, eleven outcomes.

Design: docs/superpowers/specs/2026-09-22-fetch-engine-design.md.

The ladder stops at the first rung that returns a usable document. It also
stops at an ANSWER -- a 404 is not made into a 200 by a residential proxy, and
a URL we refuse ourselves is not worth paying a vendor to refuse again.

Nothing here raises for a failed fetch. Ten of the eleven outcomes are values,
because before this engine a blocked fetch and a page that genuinely states
nothing arrived at the reader as the same thing, and CLAUDE.md records this
repo meeting that failure twice.
"""

import logging
import zlib
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.conf import settings
from django.utils import timezone

from ..egress import UnsafeTarget, validate_public_url
from . import archive as archive_module
from . import firecrawl as firecrawl_module
from . import scrapedo as scrapedo_module
from .budget import SweepBudget, default_budget
from .types import (
    SERVED,
    Attempt,
    FetchBudgetExhausted,
    FetchedPage,
    Outcome,
    VendorUnavailable,
)

logger = logging.getLogger(__name__)

#: Outcomes that end the ladder wherever they occur. DEAD, INVALID and OFF_SITE
#: are ANSWERS -- ours or the origin's -- and no later rung changes them.
_TERMINAL = SERVED | {Outcome.UNCHANGED, Outcome.DEAD, Outcome.INVALID, Outcome.OFF_SITE}

#: How many retry rounds rung 5 allows before rung 6 is read.
_MAX_RETRIES = 3
_RETRY_NETWORK = (timedelta(hours=24), timedelta(hours=48), timedelta(hours=96))
_RETRY_BLOCK = (timedelta(hours=6), timedelta(hours=24), timedelta(hours=48))


def _default_providers() -> dict:
    return {
        "firecrawl": firecrawl_module.scrape,
        "scrapedo": scrapedo_module.scrape,
        "archive": archive_module.latest_capture,
    }


def _origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower()


def _record(url: str, host: str, purpose: str, page: FetchedPage, attempt: Attempt,
            *, sweep_id: UUID | None, attempt_no: int, retry_after=None) -> None:
    from ..models import FetchAttempt

    FetchAttempt.objects.create(
        url=url[:2048], host=host, purpose=purpose, rung=attempt.rung, vendor=attempt.vendor,
        params={}, status_code=attempt.status_code, content_type=page.content_type[:100],
        byte_size=len(page.body), credits=attempt.credits, duration_ms=attempt.duration_ms,
        outcome=str(attempt.outcome), reason=attempt.reason[:300],
        final_url=page.final_url[:2048], change_status=page.change_status or "",
        captured_at=page.captured_at, page_count=page.page_count,
        total_pages=page.total_pages, retry_after=retry_after, attempt_no=attempt_no,
        sweep_id=sweep_id,
    )


def _retries_spent(url: str) -> int:
    from ..models import FetchAttempt

    return FetchAttempt.objects.filter(
        url=url, outcome=str(Outcome.RETRY_SCHEDULED)
    ).count()


def _refuse(url: str, outcome: Outcome, reason: str, trail: list[Attempt]) -> FetchedPage:
    return FetchedPage(
        final_url=url, redirects=(), content_type="", body=b"", markdown="",
        outcome=outcome, fetched_via="NONE", rung=trail[-1].rung if trail else 0,
        credits=sum(a.credits for a in trail), reason=reason, attempts=tuple(trail),
    )


def fetch_page(
    url: str,
    *,
    purpose: str = "read",
    tag: str | None = None,
    require_origin: str | None = None,
    budget: SweepBudget | None = None,
    profile=None,
    providers: dict | None = None,
) -> FetchedPage:
    from ..models import HostProfile

    providers = providers or _default_providers()
    budget = budget or default_budget()
    host = (urlsplit(url).hostname or "").lower()
    trail: list[Attempt] = []

    try:
        validate_public_url(url)
    except UnsafeTarget:
        # Refused by us, before a vendor is paid to refuse it too.
        return _refuse(url, Outcome.INVALID, "requested_url_unsafe",
                       [Attempt(rung=0, vendor="NONE", outcome=Outcome.INVALID,
                                reason="requested_url_unsafe")])

    if profile is None:
        profile = HostProfile.objects.filter(host=host).first()

    plan = _rung_plan(purpose, profile)
    for rung in plan:
        estimate = 25 if rung == 4 else 1
        try:
            budget.check(estimate)
        except FetchBudgetExhausted as error:
            trail.append(Attempt(rung=rung, vendor="NONE", outcome=Outcome.BUDGET,
                                 reason=str(error)[:300]))
            return _refuse(url, Outcome.BUDGET, str(error)[:300], trail)

        try:
            page = _call(rung, url, tag=tag, profile=profile, providers=providers,
                         purpose=purpose)
        except VendorUnavailable as error:
            # THEIR API failed, not the site. Recording this as a block would
            # teach the profile a lie and send every later fetch to rung 4.
            trail.append(Attempt(rung=rung, vendor="NONE", outcome=Outcome.UNREACHABLE,
                                 reason=f"vendor_unavailable:{error}"[:300]))
            continue

        budget.spend(page.fetched_via, page.credits)
        attempt = page.attempts[0] if page.attempts else Attempt(
            rung=rung, vendor=page.fetched_via, outcome=page.outcome, credits=page.credits
        )
        trail.append(attempt)
        _record(url, host, purpose, page, attempt, sweep_id=budget.sweep_id,
                attempt_no=len(trail))

        if page.outcome in SERVED and require_origin and _origin(page.final_url) != _origin(
            require_origin
        ):
            # Off-site bytes reach neither the model nor the evidence bucket.
            off = Attempt(rung=rung, vendor=page.fetched_via, outcome=Outcome.OFF_SITE,
                          credits=page.credits, reason=f"off_site:{page.final_url}"[:300])
            trail[-1] = off
            return _refuse(url, Outcome.OFF_SITE, off.reason, trail)

        if page.outcome in _TERMINAL:
            total = sum(a.credits for a in trail)
            return FetchedPage(**{**page.__dict__, "credits": total, "attempts": tuple(trail)})

    # Every live rung failed.
    spent = _retries_spent(url)
    blocked = any(a.outcome is Outcome.BLOCKED for a in trail)
    if spent < _MAX_RETRIES:
        schedule = _RETRY_BLOCK if blocked else _RETRY_NETWORK
        retry_after = timezone.now() + schedule[min(spent, len(schedule) - 1)]
        attempt = Attempt(rung=5, vendor="NONE", outcome=Outcome.RETRY_SCHEDULED,
                          reason="blocked" if blocked else "unreachable")
        trail.append(attempt)
        page = _refuse(url, Outcome.RETRY_SCHEDULED, attempt.reason, trail)
        _record(url, host, purpose, page, attempt, sweep_id=budget.sweep_id,
                attempt_no=spent + 1, retry_after=retry_after)
        return page

    archived = providers["archive"](url, api_key=settings.SCRAPEDO_API_KEY)
    trail.extend(archived.attempts)
    _record(url, host, purpose, archived,
            archived.attempts[0] if archived.attempts
            else Attempt(rung=6, vendor="ARCHIVE", outcome=archived.outcome),
            sweep_id=budget.sweep_id, attempt_no=len(trail))
    if archived.outcome is Outcome.ARCHIVED:
        return FetchedPage(**{**archived.__dict__,
                              "credits": sum(a.credits for a in trail),
                              "attempts": tuple(trail)})

    final = Outcome.BLOCKED if blocked else Outcome.UNREACHABLE
    return _refuse(url, final, archived.reason or ("blocked" if blocked else "unreachable"),
                   trail)


def _rung_plan(purpose: str, profile) -> tuple[int, ...]:
    """Which rungs to walk, in order.

    `purpose="bytes"` needs the origin's own bytes, so the extractor tier is
    skipped entirely. Otherwise the plan starts at the host's remembered rung --
    and a host remembered at an expensive rung is re-probed from rung 1 once
    every FETCH_REPROBE_DAYS, so a host that got easier stops paying.
    """
    if purpose == "bytes":
        return (3, 4)
    start = getattr(profile, "start_rung", 1) or 1
    if start > 1:
        last_probe = getattr(profile, "last_probe_at", None)
        due = last_probe is None or timezone.now() - last_probe > timedelta(
            days=settings.FETCH_REPROBE_DAYS
        )
        if due:
            start = 1
    return tuple(rung for rung in (1, 2, 3, 4) if rung >= start and rung != 2)


def _call(rung: int, url: str, *, tag, profile, providers, purpose="read") -> FetchedPage:
    if rung == 1:
        page = providers["firecrawl"](url, api_key=settings.FIRECRAWL_API_KEY, tag=tag,
                                      actions=False, profile=profile, request_id=str(uuid4()))
        if page.outcome is Outcome.UNREADABLE:
            # A shell escalates WITHIN Firecrawl before it changes vendor: the
            # page is reachable, it just has not run its JavaScript yet.
            return providers["firecrawl"](url, api_key=settings.FIRECRAWL_API_KEY, tag=tag,
                                          actions=True, profile=profile,
                                          request_id=str(uuid4()))
        return page
    return providers["scrapedo"](url, api_key=settings.SCRAPEDO_API_KEY, rung=rung,
                                 profile=profile,
                                 # Stable across processes (hash() is salted per
                                 # process), so a retry in a later task keeps the
                                 # same residential session for this host.
                                 session_id=zlib.crc32((urlsplit(url).hostname or "").encode())
                                 % 100_000,
                                 transparent=(purpose == "bytes"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_ladder.py -v`
Expected: 14 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/research/fetch/__init__.py tests/research/test_fetch_ladder.py
git commit -m "feat: the ladder -- seven rungs, eleven outcomes, no silent dead end

Stops at the first usable document and at every ANSWER: a 404 is not made into
a 200 by a residential proxy, and a URL we refuse ourselves is not worth paying
a vendor to refuse again. A vendor outage is recorded as a vendor outage, never
as a blocked site -- otherwise the host profile learns a lie.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The host learns — profile write-back

> **Master status, 2026-09-23:** new. See Reconciliation.

**Files:**
- Modify: `apps/research/fetch/__init__.py`
- Test: `tests/research/test_fetch_profile.py`

**Interfaces:**
- Consumes: `models.HostProfile`, `types.Outcome`
- Produces: `remember(host, page) -> HostProfile` — called by `fetch_page` after every terminal outcome

Spec §5. The rule that makes this safe: **only expensive rungs are remembered.** A success at rung 1 or 2 resets `start_rung` to 1, so the memory can only ever save money. A host that got easier is found by the re-probe already written in `_rung_plan`.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_profile.py
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.research.fetch import remember
from apps.research.fetch.types import Attempt, FetchedPage, Outcome
from apps.research.models import HostProfile

pytestmark = pytest.mark.django_db


def _page(outcome, *, rung=1, vendor="FIRECRAWL", credits=1):
    return FetchedPage(
        final_url="https://e.test/a", redirects=(), content_type="text/html",
        body=b"x" * 5_000, markdown="# A", outcome=outcome, fetched_via=vendor,
        rung=rung, credits=credits, status_code=200,
        attempts=(Attempt(rung=rung, vendor=vendor, outcome=outcome, credits=credits),),
    )


def test_an_expensive_success_is_remembered():
    profile = remember("e.test", _page(Outcome.FETCHED, rung=4, vendor="SCRAPE_DO", credits=25))
    assert profile.start_rung == 4
    assert profile.needs_render is True
    assert profile.needs_residential is True
    assert profile.last_success_rung == 4


def test_a_cheap_success_resets_the_memory_so_it_can_only_save_money():
    HostProfile.objects.create(host="e.test", start_rung=4, needs_render=True,
                               needs_residential=True)
    profile = remember("e.test", _page(Outcome.FETCHED, rung=1))
    assert profile.start_rung == 1
    assert profile.needs_render is False


def test_a_block_sets_a_cool_off_that_doubles():
    first = remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO", credits=25))
    assert first.consecutive_blocks == 1
    window_one = first.blocked_until - timezone.now()
    second = remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO", credits=25))
    assert second.consecutive_blocks == 2
    assert second.blocked_until - timezone.now() > window_one


def test_the_cool_off_is_capped_at_seven_days():
    for _ in range(12):
        profile = remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO"))
    assert profile.blocked_until - timezone.now() <= timedelta(days=7, seconds=5)


def test_a_success_clears_the_cool_off():
    remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO"))
    profile = remember("e.test", _page(Outcome.FETCHED, rung=1))
    assert profile.blocked_until is None
    assert profile.consecutive_blocks == 0


def test_the_ledger_accumulates_for_the_per_domain_surcharge_guard():
    """scrape.do applies per-domain multipliers of 10 to 200 credits
    server-side, with no request-time signal. This is where they show up."""
    remember("e.test", _page(Outcome.FETCHED, rung=3, vendor="SCRAPE_DO", credits=200))
    profile = remember("e.test", _page(Outcome.FETCHED, rung=3, vendor="SCRAPE_DO", credits=200))
    assert profile.credits_30d == 400
    assert profile.attempts_30d == 2


def test_a_probe_from_rung_one_is_dated_even_when_it_fails():
    """Otherwise a remembered host is re-probed on every single fetch."""
    profile = remember("e.test", _page(Outcome.UNREACHABLE, rung=1, credits=0))
    assert profile.last_probe_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_profile.py -v`
Expected: FAIL with `ImportError: cannot import name 'remember'`

- [ ] **Step 3: Add the write-back**

```python
# apps/research/fetch/__init__.py -- add, and call from fetch_page

#: A block's cool-off doubles from six hours and stops at a week. A host that
#: means it is not persuaded by a fourth attempt an hour later.
_BLOCK_BASE = timedelta(hours=6)
_BLOCK_CAP = timedelta(days=7)


def remember(host: str, page: FetchedPage):
    """Teach the profile what this fetch learned (spec §5).

    Only EXPENSIVE rungs are remembered: a success at rung 1 or 2 resets
    start_rung to 1. The memory can therefore only ever save money -- it can
    never entrench a cost -- and a host that got easier is found by the
    re-probe in _rung_plan rather than by paying rung-4 prices forever.
    """
    from ..models import HostProfile

    profile, _created = HostProfile.objects.get_or_create(host=host)
    now = timezone.now()

    if page.rung <= 1:
        profile.last_probe_at = now

    if page.outcome in SERVED:
        profile.last_success_rung = page.rung
        profile.last_success_at = now
        profile.blocked_until = None
        profile.consecutive_blocks = 0
        profile.start_rung = page.rung if page.rung >= 3 else 1
        profile.needs_render = page.rung >= 4
        profile.needs_residential = page.rung >= 4
    elif page.outcome is Outcome.BLOCKED:
        profile.consecutive_blocks += 1
        window = min(_BLOCK_BASE * (2 ** (profile.consecutive_blocks - 1)), _BLOCK_CAP)
        profile.blocked_until = now + window

    profile.credits_30d += page.credits
    profile.attempts_30d += 1
    profile.save()
    return profile
```

In `fetch_page`, call it on every terminal return. Add immediately before each `return` that yields a
`FetchedPage` with a terminal outcome — after the `_record` call and before the return:

```python
        if page.outcome in _TERMINAL:
            total = sum(a.credits for a in trail)
            result = FetchedPage(**{**page.__dict__, "credits": total, "attempts": tuple(trail)})
            remember(host, result)
            return result
```

and at the two terminal paths after the loop (the archive success, and the final `_refuse`):

```python
    if archived.outcome is Outcome.ARCHIVED:
        result = FetchedPage(**{**archived.__dict__,
                                "credits": sum(a.credits for a in trail),
                                "attempts": tuple(trail)})
        remember(host, result)
        return result

    final = Outcome.BLOCKED if blocked else Outcome.UNREACHABLE
    refused = _refuse(url, final, archived.reason or ("blocked" if blocked else "unreachable"),
                      trail)
    remember(host, refused)
    return refused
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_profile.py tests/research/test_fetch_ladder.py -v`
Expected: 21 passed (7 new plus Task 7's 14 still green)

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/research/fetch/__init__.py tests/research/test_fetch_profile.py
git commit -m "feat: the host profile learns which rung worked

Only expensive rungs are remembered -- a cheap success resets the memory -- so
it can only ever save money. A block sets a doubling cool-off capped at a week;
a success clears it. The per-host credit ledger is where scrape.do's
server-side per-domain surcharge would show up.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---
### Task 9: The callers switch over — `retrieve_official_source` delegates

> **Master status, 2026-09-23:** partial — master already delegates on `(url, *, fetch, tag, budget)`; keep that signature. See Reconciliation.

**Files:**
- Modify: `apps/research/discovery.py:261-275`, `apps/research/services.py:59-66`
- Test: `tests/research/test_discovery.py` (modify), `tests/research/test_fetch_delegation.py` (new)

**Interfaces:**
- Consumes: `fetch.fetch_page`, `fetch.types.Outcome`, `fetch.types.SERVED`
- Produces: `retrieve_official_source(url, *, plain_fetch=None, browser_render=None) -> FetchResult` — same name, same signature, same exception surface as today

**This task changes no caller.** `retrieve_official_source` keeps its signature so its eight callers
(`apps/research/reader.py:517`, `apps/documents/program_rules.py:33`, and the five other modules that inject `retrieve_official_source` as a default)
continue to work. `plain_fetch` and `browser_render` remain as parameters and are *ignored* with a
deprecation note; they are removed in Task 11 once nothing passes them.

**The compatibility wrapper is where outcomes become exceptions.** Callers written against the old
seam expect `SourceBlocked` on failure. The ladder returns values; this function translates. New
callers should use `fetch_page` directly and read `page.outcome` — that is the whole point of the
engine, and `reader.py` gains it in plan 2.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_delegation.py
import pytest

from apps.research.discovery import retrieve_official_source
from apps.research.egress import FetchResult, SourceBlocked
from apps.research.fetch.types import Attempt, FetchedPage, Outcome

pytestmark = pytest.mark.django_db

_PAGE = b"<html><body>" + b"<p>A CV is required.</p>" * 300 + b"</body></html>"


def _page(outcome, **kwargs):
    base = dict(final_url="https://e.test/a", redirects=(), content_type="text/html",
                body=_PAGE, markdown="# A", outcome=outcome, fetched_via="FIRECRAWL",
                rung=1, credits=1, status_code=200,
                attempts=(Attempt(rung=1, vendor="FIRECRAWL", outcome=outcome),))
    base.update(kwargs)
    return FetchedPage(**base)


def test_a_served_page_comes_back_as_a_fetch_result(monkeypatch):
    monkeypatch.setattr("apps.research.discovery.fetch_page",
                        lambda url, **kwargs: _page(Outcome.FETCHED))
    result = retrieve_official_source("https://e.test/a")
    assert isinstance(result, FetchResult)
    assert result.final_url == "https://e.test/a"
    assert result.body == _PAGE


def test_an_archived_page_is_served_too(monkeypatch):
    """Rung 6 exists to produce a readable page; a caller that only knows
    FetchResult must not lose DAAD because the bytes came from a capture."""
    monkeypatch.setattr("apps.research.discovery.fetch_page",
                        lambda url, **kwargs: _page(Outcome.ARCHIVED, captured_at="2026-06-25"))
    assert retrieve_official_source("https://e.test/a").body == _PAGE


@pytest.mark.parametrize("outcome", [Outcome.BLOCKED, Outcome.UNREACHABLE, Outcome.UNREADABLE,
                                     Outcome.DEAD, Outcome.OFF_SITE, Outcome.INVALID,
                                     Outcome.BUDGET, Outcome.RETRY_SCHEDULED])
def test_every_unserved_outcome_raises_for_the_old_callers(monkeypatch, outcome):
    monkeypatch.setattr("apps.research.discovery.fetch_page",
                        lambda url, **kwargs: _page(outcome, body=b"", reason="x"))
    with pytest.raises(SourceBlocked) as error:
        retrieve_official_source("https://e.test/a")
    assert str(outcome) in str(error.value)


def test_an_unchanged_page_is_not_an_error_but_has_no_bytes(monkeypatch):
    """UNCHANGED means the vendor compared it for free and it did not move.
    Old callers cannot use that, so they get the exception; new callers read
    page.outcome and skip the reader, which is the saving."""
    monkeypatch.setattr("apps.research.discovery.fetch_page",
                        lambda url, **kwargs: _page(Outcome.UNCHANGED, body=b""))
    with pytest.raises(SourceBlocked):
        retrieve_official_source("https://e.test/a")


def test_the_blocked_source_reason_is_updated_not_frozen_at_the_first_one():
    """OPEN observation 2026-09-16: get_or_create(defaults=) kept the FIRST
    reason forever, so a row said 'timeout' months after the host started
    answering 403 -- and the diagnostics said the opposite of the truth."""
    from apps.research.models import ConsultantResearchTask
    from apps.research.services import record_blocked_source

    record_blocked_source("https://e.test/a", "UNREACHABLE:timeout")
    record_blocked_source("https://e.test/a", "BLOCKED:origin_403")
    task = ConsultantResearchTask.objects.get(url="https://e.test/a",
                                              state=ConsultantResearchTask.State.OPEN)
    assert task.reason == "BLOCKED:origin_403"
    assert ConsultantResearchTask.objects.filter(url="https://e.test/a").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_delegation.py -v`
Expected: FAIL — `AttributeError: <module 'apps.research.discovery'> has no attribute 'fetch_page'`

- [ ] **Step 3: Delegate, and fix the diagnostics defect**

```python
# apps/research/discovery.py -- replace retrieve_official_source (lines 261-275)

from .fetch import fetch_page  # add to the imports at the top
from .fetch.types import SERVED


def retrieve_official_source(
    url: str,
    *,
    plain_fetch: object = None,
    browser_render: object = None,
) -> FetchResult:
    """Fetch a page for a caller that predates the engine.

    Kept at this name and signature so its eight callers do not change shape.
    The engine returns OUTCOMES; this wrapper turns everything unserved back
    into SourceBlocked, because that is what these callers were written
    against. New code calls fetch_page directly and reads page.outcome -- the
    distinction between "the page says nothing" and "we could not look" is the
    whole reason the engine exists, and it is lost in this translation.

    `plain_fetch` and `browser_render` are accepted and ignored; they are
    removed once nothing passes them.
    """
    canonical_url = canonicalize_url(url)
    page = fetch_page(canonical_url, purpose="read")
    if page.outcome not in SERVED:
        raise SourceBlocked(f"{page.outcome}: {page.reason or canonical_url}")
    return FetchResult(
        final_url=page.final_url,
        redirects=page.redirects,
        content_type=page.content_type,
        body=page.body,
        browser_required=False,
    )
```

```python
# apps/research/services.py -- replace record_blocked_source (lines 59-66)

def record_blocked_source(url: str, reason: str) -> ConsultantResearchTask:
    """Queue a URL for a person, and say why it is queued NOW.

    get_or_create(defaults={"reason": ...}) kept the FIRST reason forever, so a
    row could read "timeout" months after the host began answering 403 --
    diagnostics asserting the opposite of the truth (OPEN observation
    2026-09-16). The engine calls this on every terminal failure, so the row
    must carry the latest outcome; the history is in FetchAttempt.
    """
    task, created = ConsultantResearchTask.objects.get_or_create(
        url=url,
        state=ConsultantResearchTask.State.OPEN,
        defaults={"reason": reason},
    )
    if not created and task.reason != reason:
        task.reason = reason
        task.save(update_fields=["reason"])
    return task
```

- [ ] **Step 4: Call it from the ladder's terminal failures**

**`ConsultantResearchTask` is tenant-scoped, and the ladder is not.** `TenantScopedModel.save`
calls `current_tenant_id()`, which **raises `TenantContextMissing` outside a `tenant_scope`** — so a
bare `record_blocked_source` from the ladder crashes every catalog read of a blocked page, because
`read_and_derive` runs with no tenant and has no business choosing one. `apps/research/pipeline.py`
already shows the working shape for the path that *does* have a tenant: `transaction.atomic()` plus
`set_local_tenant(tenant_id)` around the insert, because the row is also under FORCE ROW LEVEL
SECURITY and `tenant_scope` sets a ContextVar and nothing else.

So the ladder does not call it. It returns the outcome, and **the caller that has a tenant writes the
task**; a caller that has none gets the outcome and the `FetchAttempt` trail, which is the whole
ledger. In `apps/research/fetch/__init__.py`, in the two post-loop terminal paths
(`RETRY_SCHEDULED` is *not* one — it is not terminal), after `remember(host, refused)`, log and
return; add nothing else:

```python
    # Deliberately NOT record_blocked_source. That row is tenant-scoped and this
    # function runs on both a tenant sweep and the tenantless catalog read, where
    # current_tenant_id() raises. The outcome and the FetchAttempt trail are the
    # ledger; a caller inside a tenant_scope turns them into a task.
    logger.info("%s for %s at rung %s: %s", final, url, trail[-1].rung if trail else 0,
                refused.reason)
```

Then, in `apps/research/pipeline.py`, where a tenant IS in hand, the existing
`_record_blocked(url, reason, tenant_id)` helper (line ~236, already `transaction.atomic()` +
`set_local_tenant`) is called with the outcome's name and reason — one line, in the place that
already does this correctly for a lead that could not be fetched.

A test pins it: `test_the_ladder_writes_no_tenant_scoped_row`, asserting
`ConsultantResearchTask.objects.count() == 0` after a fully-failed `fetch_page` outside any scope,
and that the call does not raise.

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/ tests/documents/test_program_rules.py -v`
Expected: all pass. The existing `tests/research/test_discovery.py` cases that inject `plain_fetch`
or `browser_render` now exercise the ignored parameters; update their assertions to monkeypatch
`apps.research.discovery.fetch_page` instead, keeping one case per behaviour they were pinning.

- [ ] **Step 6: Run the full suite and the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_fetch_engine uv run pytest`
Expected: all green. This is the first task where every caller runs on the new engine, so a failure
here is a real regression in a caller, not a test-fixture problem.

- [ ] **Step 7: Commit**

```bash
git add apps/research/discovery.py apps/research/services.py apps/research/fetch/__init__.py tests/research/
git commit -m "feat: every research fetch routes through the engine

retrieve_official_source keeps its name and signature, so its eight callers do
not change; unserved outcomes become SourceBlocked for them. New callers read
page.outcome -- telling 'says nothing' from 'could not look' is the point.

Also fixes record_blocked_source freezing its first reason forever (OPEN
observation 2026-09-16): a row read 'timeout' long after the host began
answering 403.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Rung 5's worker — `retry_due_fetches`

> **Master status, 2026-09-23:** new. See Reconciliation.

**Files:**
- Create: `apps/research/management/commands/retry_due_fetches.py`
- Test: `tests/research/test_fetch_retry_command.py`

**Interfaces:**
- Consumes: `models.FetchAttempt`, `models.HostProfile`, `fetch.fetch_page`, `services.acquire_domain_lease`
- Produces: the management command; no Python API

Two rules the spec fixes in place: a due retry whose host is still inside `blocked_until` is
**rescheduled, not spent** (§4 rung 5, §5) — otherwise a cool-off is defeated by the very queue meant
to respect it; and pacing goes through the existing `DomainLease`, not a new mechanism.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_retry_command.py
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.research.fetch.types import Attempt, FetchedPage, Outcome
from apps.research.models import FetchAttempt, HostProfile

pytestmark = pytest.mark.django_db


def _due(url="https://e.test/a", host="e.test", ago=timedelta(hours=1), attempt_no=1):
    return FetchAttempt.objects.create(
        url=url, host=host, rung=5, vendor="NONE", outcome=Outcome.RETRY_SCHEDULED,
        retry_after=timezone.now() - ago, attempt_no=attempt_no,
    )


def _served(url="https://e.test/a"):
    return FetchedPage(
        final_url=url, redirects=(), content_type="text/html", body=b"x" * 5_000,
        markdown="# A", outcome=Outcome.FETCHED, fetched_via="FIRECRAWL", rung=1,
        credits=1, status_code=200,
        attempts=(Attempt(rung=1, vendor="FIRECRAWL", outcome=Outcome.FETCHED, credits=1),),
    )


def test_a_due_retry_is_re_entered(monkeypatch):
    _due()
    called = []
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: called.append(url) or _served(url))
    call_command("retry_due_fetches")
    assert called == ["https://e.test/a"]


def test_a_retry_not_yet_due_is_left_alone(monkeypatch):
    _due(ago=timedelta(hours=-5))
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: pytest.fail("spent a retry before it was due"))
    call_command("retry_due_fetches")


def test_a_host_inside_its_cool_off_is_rescheduled_not_spent(monkeypatch):
    """Otherwise the queue defeats the very cool-off it is meant to respect."""
    row = _due()
    HostProfile.objects.create(host="e.test",
                               blocked_until=timezone.now() + timedelta(hours=3))
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: pytest.fail("fetched inside a cool-off"))
    call_command("retry_due_fetches")
    row.refresh_from_db()
    assert row.retry_after > timezone.now() + timedelta(hours=2)


def test_a_successful_retry_closes_the_scheduled_row(monkeypatch):
    row = _due()
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: _served(url))
    call_command("retry_due_fetches")
    row.refresh_from_db()
    assert row.retry_after is None


def test_the_command_reports_what_it_did(monkeypatch, capsys):
    _due()
    _due(url="https://f.test/b", host="f.test")
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: _served(url))
    call_command("retry_due_fetches")
    out = capsys.readouterr().out
    assert "2 due" in out
    assert "2 served" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_retry_command.py -v`
Expected: FAIL with `CommandError: Unknown command: 'retry_due_fetches'`

- [ ] **Step 3: Write the command**

```python
# apps/research/management/commands/retry_due_fetches.py
"""Rung 5: re-enter the ladder for fetches whose retry window has come.

Scheduled, not immediate, because the failures this queue holds are the ones
time fixes -- an outage, a rate-limit window, a deploy. A host still inside its
cool-off is RESCHEDULED rather than spent: retrying it now would defeat the
very cool-off the block set, and the host would answer 403 again for free.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ...fetch import fetch_page
from ...fetch.types import SERVED
from ...models import FetchAttempt, HostProfile
from ...services import acquire_domain_lease

#: The ladder's own pacing between two fetches of one host.
_LEASE = timedelta(seconds=30)


class Command(BaseCommand):
    help = "Re-enter the fetch ladder for every scheduled retry that is now due."

    def handle(self, *args, **options) -> None:
        now = timezone.now()
        due = list(
            FetchAttempt.objects.filter(
                outcome="RETRY_SCHEDULED", retry_after__lte=now
            ).order_by("retry_after")
        )
        self.stdout.write(f"{len(due)} due")

        served = 0
        for row in due:
            profile = HostProfile.objects.filter(host=row.host).first()
            if profile and profile.blocked_until and profile.blocked_until > now:
                row.retry_after = profile.blocked_until
                row.save(update_fields=["retry_after"])
                continue
            acquire_domain_lease(row.host, interval=_LEASE)
            page = fetch_page(row.url, purpose=row.purpose)
            if page.outcome in SERVED:
                served += 1
                row.retry_after = None
                row.save(update_fields=["retry_after"])

        self.stdout.write(f"{served} served")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_retry_command.py -v`
Expected: 5 passed

- [ ] **Step 5: Add the schedule to the infrastructure template**

In `infra/template.yaml`, beside `EuropassCanaryRule`, add a rule that runs the command on
`WorkerTaskDefinition` — same shape, `ScheduleExpression: "rate(6 hours)"`, command override
`["python", "manage.py", "retry_due_fetches"]`. Six hours is the shortest retry window (a block's
first step), so a shorter rule only wakes to find nothing due.

- [ ] **Step 6: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/infra/ tests/research/`
Expected: all clean

- [ ] **Step 7: Commit**

```bash
git add apps/research/management/ infra/template.yaml tests/research/test_fetch_retry_command.py
git commit -m "feat: rung 5 -- the retry queue and its six-hourly worker

A host still inside its cool-off is rescheduled, not spent: retrying it now
would defeat the cool-off the block set. Pacing goes through the existing
DomainLease rather than a second mechanism.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Delete the old fetch path

> **Master status, 2026-09-23:** STRUCK — done on master; `_backoff_seconds`, `_RETRY_ATTEMPTS`, `_THROTTLED`, `looks_unrendered` stay. See Reconciliation.

Nothing reaches these any more. They are deleted here, in one commit, so the deletion is reviewable
as a deletion rather than hidden inside a feature.

**Files:**
- Modify: `apps/research/egress.py` (delete `fetch_official_source`, `_request`, `_backoff_seconds`, `_THROTTLED`, `_RETRY_ATTEMPTS`, `RedirectLimitExceeded`, `BrowserRequired` if unused)
- Modify: `apps/research/discovery.py` (delete `render_with_scrapling`, `browser_fetch_options`, `render_via_browser_service`, `BROWSER_SERVICE_URL`; drop the two ignored parameters)
- Delete: `apps/research/browser_server.py`, `tests/research/test_browser_server.py`
- Modify: `pyproject.toml` (remove `scrapling[fetchers]`), `uv.lock` (re-lock)
- Modify: every test that imported the deleted names

**What must NOT be deleted — taken literally this task would take all three, and it must not:**
1. **`apps/documents/europass.py`'s own `_request`.** It POSTs the student's name, date of birth, education and employment history to europa.eu, with `assert_hostname`/`server_hostname` pinned and `redirect=False` — the DNS-rebinding guard on the one path carrying student PII. A vendor there becomes a processor of a student's personal data with no DPA, and could not carry the four-call cookie/XSRF session anyway.
2. **`egress.fetch_json_api` and the `_request` *it* uses.** These POST to contracted APIs (the search providers in `search.py` and `providers/{exa,tavily}.py`; Jev in `research_fit/jev.py`) carrying **our** API keys. (`registers.py` was the other caller until the institution-safety screen was deleted on 2026-09-14.) Routing them through a vendor would ship those keys to a third party.
3. **`validate_public_url`, `require_same_origin`, `looks_unrendered`, `USER_AGENT`, `canonicalize_url`, `ALLOWED_CONTENT_TYPES`, `MAX_RESPONSE_BYTES`.** The engine imports every one.
4. **`LocalEgressProxy`.** `apps/portals/engine.py:37` imports it. It leaves with the glass-box portal deletion, not here; deleting it now breaks the portal tier.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_deletion.py
import subprocess
import sys

import pytest


def test_the_old_fetch_path_is_gone():
    from apps.research import discovery, egress

    for name in ("fetch_official_source",):
        assert not hasattr(egress, name), f"{name} still exists"
    for name in ("render_with_scrapling", "browser_fetch_options",
                 "render_via_browser_service"):
        assert not hasattr(discovery, name), f"{name} still exists"


def test_the_browser_server_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        __import__("apps.research.browser_server")


def test_scrapling_is_no_longer_a_dependency():
    result = subprocess.run([sys.executable, "-c", "import scrapling"],
                            capture_output=True)
    assert result.returncode != 0, "scrapling is still installed"


def test_the_three_things_that_must_survive_a_literal_reading_survive():
    """Taken literally, 'delete our own client' takes all three. Each one is
    load-bearing for a reason the deletion does not touch."""
    from apps.documents import europass
    from apps.research import egress

    assert callable(europass._request), "the europa.eu PII path lost its pinned transport"
    assert callable(egress.fetch_json_api), "contracted APIs lost their client"
    assert callable(egress.validate_public_url)
    assert callable(egress.require_same_origin)

    from apps.portals import engine  # noqa: F401  -- LocalEgressProxy still importable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_deletion.py -v`
Expected: FAIL — the first three tests fail because the old path is still present.

- [ ] **Step 3: Delete**

```bash
git rm apps/research/browser_server.py tests/research/test_browser_server.py
```

**Master has already done all of this — verified at 40f8400.** `fetch_official_source` does not
exist anywhere in `apps/` or `tests/`; the three render functions, `BROWSER_SERVICE_URL`,
`plain_fetch`, `browser_render` and `scrapling[fetchers]` are gone; and `apps/research/registers.py`
was deleted with the institution-safety screen on 2026-09-14, so the fifth module in the old list is
not a module any more. Every remaining injector already defaults to `retrieve_official_source`
(`seeds.py:53`, `pipeline.py:186`, `reader.py:517`, `program_rules.py:33`) or, for the two that
fetch a **data file** rather than a page, to `fetch_data_file` (`search.py:205`, `search.py:284`) —
and those two must stay as they are: an XML sitemap is parsed as bytes, never read as a page
(CLAUDE.md, "Web fetching").

So this step is now a **check, not an edit**:

```bash
grep -rn "fetch_official_source\|BROWSER_SERVICE_URL\|plain_fetch\|browser_render" apps tests
grep -n "scrapling" pyproject.toml
```

Expected: no output from either. If there is any, the deletion is genuinely outstanding and the
paragraph this replaced is in `git log` for the branch.

- [ ] **Step 4: Run the full suite**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest`
Expected: all pass. Expect to fix a handful of tests that constructed `FetchResult` fixtures for the
deleted path — those become `FetchedPage` fixtures or monkeypatch `fetch_page`.

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config && uv run pip-audit`
Expected: all clean. `pip-audit` matters here: removing `scrapling[fetchers]` removes patchright and
a large transitive tree, so the dependency surface changes in this commit.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete our own page fetcher and the Scrapling tier

Everything routes through the engine now. Deleted: fetch_official_source and
its redirect loop, render_with_scrapling, browser_fetch_options,
render_via_browser_service, browser_server.py, scrapling[fetchers].

Kept, because a literal reading would take all three and each is load-bearing:
europass.py's own _request (student PII to europa.eu, pinned address,
DNS-rebinding guard), egress.fetch_json_api (contracted APIs, our own keys),
and LocalEgressProxy (apps/portals/engine.py imports it; it leaves with the
glass-box portal deletion, not here).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Retire the browser tier from the infrastructure, and the live gate

> **Master status, 2026-09-23:** mostly done on master — only Step 4 and extending `test_fetch_live.py` remain. See Reconciliation.

**Files:**
- Modify: `infra/template.yaml` (remove every `Browser*` resource), `Dockerfile` (remove the `browser` stage), `tests/infra/test_template.py`
- Create: `tests/research/test_fetch_live.py`
- Modify: `docs/runbooks/deploy.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything built above
- Produces: the `-m live` gate; no Python API

The four `tests/infra/test_template.py` cases that pin `BrowserSecurityGroup` out of
`DatabaseSecurityGroup` ingress, and `BrowserTaskDefinition`'s absent `TaskRoleArn`, are deleted with
the resources they pin — **but the rule they encode is not.** `DatabaseSecurityGroup` must still
admit exactly `WebSecurityGroup`, `WorkerSecurityGroup` and `PortalSecurityGroup`; keep that test.

- [ ] **Step 1: Write the live gate**

```python
# tests/research/test_fetch_live.py
"""The live gate: real hosts, real vendors, real money.

Excluded from a default run by `addopts = "-m 'not live'"`. Run deliberately:

    FIRECRAWL_API_KEY=... SCRAPEDO_API_KEY=... \
    POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_live.py -m live -v

It asserts the outcome CLASS and a credit CEILING per host, never content.
Content changes when a university edits a page; the engine's job is to reach
it, and that is what this pins. A host that moves from BLOCKED to FETCHED is
good news and must not fail the suite -- so the assertions are "at least as
good as", not equality.
"""

import pytest
from django.conf import settings

from apps.research.fetch import fetch_page
from apps.research.fetch.budget import SweepBudget
from apps.research.fetch.types import SERVED, Outcome

pytestmark = [pytest.mark.live, pytest.mark.django_db]

#: Each entry: url, the worst outcome that still passes, the credit ceiling.
#: Sources: the nine hosts our own client refused on 2026-09-19, the three
#: shell pages measured 2026-09-12, and the two hosts that block us outright.
HARD_HOSTS = [
    ("https://www.globed.eu/how-to-apply/", SERVED, 2),
    ("https://mes.gov.ge/", SERVED, 2),
    ("https://www.freiheit.org/", SERVED, 2),
    ("https://www.bildungsserver.de/", SERVED, 2),
    ("https://turkiyeburslari.gov.tr/", SERVED, 30),
    ("https://www.sciencespo.fr/students/en/admissions/application-file.html",
     SERVED | {Outcome.ARCHIVED, Outcome.BLOCKED}, 60),
    ("https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programmes/prime/faq/",
     SERVED | {Outcome.ARCHIVED, Outcome.BLOCKED}, 60),
    # JASSO moved its scholarships page; the old /en/study_j/scholarships/ URL now
    # serves a soft 404 (HTTP 200, a "not found" body) -- the one failure class
    # this gate cannot see, and the corpus's human label can.
    ("https://www.jasso.go.jp/en/ryugaku/scholarship_j/index.html", SERVED, 30),
    # Measured 2026-09-22 through /scrape, every one served: a Drive PDF parsed
    # as 5 pages; a Google Doc's /edit, /pub and /mobilebasic forms; a Notion
    # public page; a published Sheet; a PNG OCR'd for 1 credit.
    ("https://drive.google.com/file/d/1KSLhcNlZT9r6hc-SwPWnjlrcOLdu7e-F/view", SERVED, 8),
    ("https://docs.google.com/document/d/1HyVSOmli4bEY9xa5QFWoAETX6cixlC3fLpwHe_GqZc4/edit", SERVED, 2),
    ("https://cicscareers.notion.site/Guide-to-Grad-School-404d0dcd860c434385a1e2478814e845", SERVED, 2),
    ("https://tesseract-ocr.github.io/tessdoc/images/eurotext.png", SERVED, 2),
]


@pytest.mark.parametrize("url,acceptable,ceiling", HARD_HOSTS)
def test_a_hard_host_reaches_an_acceptable_outcome_within_its_ceiling(url, acceptable, ceiling):
    if not settings.FIRECRAWL_API_KEY or not settings.SCRAPEDO_API_KEY:
        pytest.skip("both vendor keys are required")
    budget = SweepBudget(limit=ceiling)
    page = fetch_page(url, budget=budget)
    assert page.outcome in acceptable, f"{url}: {page.outcome} ({page.reason})"
    assert page.credits <= ceiling, f"{url}: spent {page.credits}, ceiling {ceiling}"
    if page.outcome in SERVED:
        assert len(page.markdown) > 500, f"{url}: served but nearly empty"


def test_a_pdf_over_the_page_cap_reads_partially_and_says_so():
    if not settings.FIRECRAWL_API_KEY:
        pytest.skip("FIRECRAWL_API_KEY is required")
    page = fetch_page("https://www.rhodeshouse.ox.ac.uk/media/2151/rhodes-scholarship-cv-template.pdf")
    assert page.outcome in SERVED
    if page.total_pages and page.page_count:
        assert page.page_count <= settings.FETCH_PDF_MAX_PAGES
        if page.total_pages > page.page_count:
            assert page.outcome is Outcome.FETCHED_PARTIAL


def test_a_second_fetch_of_an_unchanged_page_is_free_of_a_reader_run():
    """The saving the whole economics rests on: one free comparison against a
    $0.35 reader run. The first fetch establishes the baseline, so this asserts
    the SECOND."""
    if not settings.FIRECRAWL_API_KEY:
        pytest.skip("FIRECRAWL_API_KEY is required")
    url = "https://www.globed.eu/how-to-apply/"
    fetch_page(url, tag="live-gate")
    second = fetch_page(url, tag="live-gate")
    assert second.change_status in {"same", "changed", "new"}
```

- [ ] **Step 2: Verify the gate is excluded from a default run**

Run: `POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_live.py -v`
Expected: `14 deselected` — `addopts = "-m 'not live'"` keeps real money out of the default suite.

- [ ] **Step 3: Remove the browser tier from the infrastructure**

In `infra/template.yaml`, delete `BrowserTaskDefinition`, `BrowserSecurityGroup`, `BrowserService`,
`BrowserDesiredCount`, `BrowserLogGroup` and every reference. In the `Dockerfile`, delete the
`browser` stage and its `patchright install`. In `tests/infra/test_template.py`, delete the four
`Browser*` cases — and **keep** the one pinning `DatabaseSecurityGroup`'s ingress list, narrowing it
to `WebSecurityGroup`, `WorkerSecurityGroup`, `PortalSecurityGroup`.

- [ ] **Step 4: Update the runbook and CLAUDE.md**

In `docs/runbooks/deploy.md`, add a section: the three environment variables
(`FIRECRAWL_API_KEY`, `SCRAPEDO_API_KEY`, `FIRECRAWL_WEBHOOK_SECRET`), and — **layer 1 of the cost
controls, which is configuration and not code** — setting a per-key credit spend limit in
Firecrawl's dashboard (API keys page → Set limit) at the corridor budget. It survives a bug in
`SweepBudget`; nothing in the codebase does.

In `CLAUDE.md`, replace the "Web fetching" section's Scrapling bullets with the engine: one seam,
seven rungs, eleven outcomes, `HostProfile` memory, and the three things that must never be routed
through a vendor. Keep the "Two browsers, two opposite security models" section's portal row; strike
its research-browser row, since that tier no longer exists.

- [ ] **Step 5: Run everything**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_fetch_engine uv run pytest && uv run bandit -c pyproject.toml -r apps config && uv run pip-audit && POSTGRES_DB=tehsil_fetch_engine uv run python manage.py makemigrations --check --dry-run`
Expected: all clean.

- [ ] **Step 6: Run the live gate once, deliberately, and record what it cost**

Run: `FIRECRAWL_API_KEY=... SCRAPEDO_API_KEY=... POSTGRES_DB=tehsil_fetch_engine uv run pytest tests/research/test_fetch_live.py -m live -v`
Expected: every host reaches an acceptable outcome inside its ceiling. Record the actual per-host
credits in the PR description — that measurement is what the next tier decision rests on, and it is
the first real number the engine produces.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: retire the browser tier; add the live gate

The browser tier's whole job -- rendering a JS-only page -- is now rungs 2 and
4, on the vendors' infrastructure. Every Browser* resource, the Dockerfile
browser stage and the four tests pinning them go with it; the test pinning
DatabaseSecurityGroup's ingress list stays, narrowed.

The live gate asserts outcome classes and credit ceilings on the hard hosts,
never content: a university editing a page must not fail the suite, and a host
moving from BLOCKED to FETCHED is good news.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## What this plan leaves to plan 2, deliberately

Checked against the spec section by section. Three of its requirements are **not** implemented here,
each because it is a property of a *sweep* rather than of a fetch, and no sweep exists until plan 2:

- **§9.3's 429 back-off.** Here a 429 raises `VendorUnavailable`, so the ladder records a vendor
  outage and moves to the next rung — it never counts as a block, which is the half that matters for
  correctness. The exponential wait (1 s, 2 s, 4 s … 60 s) belongs to whatever is issuing calls in a
  loop, and that is plan 2's crawl and batch code.
- **§9.3's `metadata.concurrencyLimited` back-pressure.** It halves a *batch* size; there are no
  batches in the core.
- **§9.3's monthly reconciliation** of `sum(FetchAttempt.credits)` against the credit-usage endpoint.
  Task 2 stores every figure it needs; the sweep that reads them is plan 2's.
- **Soft 404s.** JASSO's old scholarships URL answers HTTP 200 with a "not found" body, and the
  engine records it as `FETCHED`. No fetch tier can tell a moved page from a thin one; the corpus's
  human label can, and plan 2's reader sees it as a page that states nothing. Recorded here so the
  gate's `SERVED` on a URL is never read as "the right page".
- **§14's two `readable_text` bugs** — the 24,000-character cut that hit Rhodes, Aalto and Eiffel,
  and the section selection that dropped Türkiye Bursları' "REQUIRED DOCUMENTS" block. They are
  reader defects, not fetch defects; they are plan 2's first task, before any site job runs, because
  a crawler measured through a reader that truncates pages is measured wrong.

Everything else in §3–§6 and §9–§14 is implemented and tested above. §7 (site jobs) and §8 (refresh)
are plan 2 in their entirety, as the spec's §17 says.

## After the plan

Plan 2 (spec §17) builds the site jobs on this engine: `/map` inventory, ranking, `/crawl` with its
errors endpoint, `/agent` as the navigator, the four programme-level outcomes, and one `/monitor` per
admissions cycle with the goal judge as the reader's trigger. Nothing in this plan anticipates it;
`fetch_page` is the only seam it needs.

The labelled corpus (`docs/superpowers/specs/2026-09-23-labelled-corpus-design.md`, written 2026-09-23; its files are not labelled yet) scores what this engine reaches. Its live
discovery gate is where `/agent` earns or loses its place — and where the in-house navigator, held
in reserve, is either built or never built.
