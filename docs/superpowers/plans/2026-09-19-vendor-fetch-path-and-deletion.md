# The Vendor Fetch Path, and the Deletion of Our Own — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every research page fetch go to Firecrawl, with scrape.do on the residue, and then delete our own page fetcher and the whole browser tier — so that anti-bot handling, challenge solving and JS rendering are a vendor's job and not ours.

**Architecture:** One new package, `apps/research/fetch/`, holding two provider modules and a router behind a single `fetch_page()` function. `retrieve_official_source` keeps its name and signature so no caller changes shape. Once every caller routes through it, `fetch_official_source`, the Scrapling tier, `browser_server.py` and the `Browser*` infra all go, together with the tests that pin them.

**Tech Stack:** Django 5.2, urllib3 (already the transport for contracted APIs), Firecrawl `/v2/scrape`, scrape.do GET API, pytest with the repo's test DB.

**Spec:** `docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` §4 — specifically §4.0a (the measured ladder), §4.1 (capability routing), §4.1a (scrape.do), §4.1b (economics), §4.1c (free tier vs paid), §4.3 (what is kept). This plan is increments **2 and 3** of that spec's §7, merged: increment 3 as written assumed our own plain client survived as tier zero, and the owner's decision of 2026-09-19 removes it.

**Base branch:** `claude/program-page-reader`. Work in a fresh worktree (`git worktree add ../vendor-fetch claude/program-page-reader`). Test database: `POSTGRES_DB=tehsil_vendor_fetch` — never share a test DB between sessions.

## Global Constraints

- **The three things that do NOT get deleted, and why.** Taken literally, "delete our own client" would take these with it. It must not.
  1. **`apps/documents/europass.py`'s own `_request`** — it POSTs `europass_payload(content)`, the student's name, date of birth, education, experience, languages and publications, to europa.eu. A scraping vendor there becomes a processor of a student's personal data with no DPA, and could not carry the four-call cookie/XSRF session anyway. **Untouched by this plan.**
  2. **`egress.fetch_json_api` and the `_request` it uses** — these POST to *contracted* APIs (the search providers in `search.py`; DEQAR and WHED in `registers.py`) carrying our own API keys. Those are not pages and there is nothing to un-block; routing them through scrape.do would ship our keys to a third party and breach the very terms §4.13 of the roster spec was written to respect. **Stay.**
  3. **`LocalEgressProxy`** — `apps/portals/engine.py:37` imports it. It leaves with the glass-box portal deletion (`2026-09-15-glass-box-copilot-design.md` §12), not here. Deleting it now breaks the portal tier.
- **`readable_text` keeps its section selection.** Spec increment 3 proposed deleting it because Firecrawl's `onlyMainContent` replaces it. It does not get deleted here: §4.1c's free-tier route extracts scrape.do's bytes locally, and removing the only local extractor at the moment we become vendor-dependent removes the fallback exactly when it starts to matter.
- **Every vendor-reported final URL runs through `validate_public_url`** before it becomes provenance (§4.3). A private-address or credential-carrying final URL is rejected exactly as before.
- **`fetched_via` is recorded on every fetch**: `FIRECRAWL | SCRAPE_DO | EGRESS`. `EGRESS` remains reachable only for `europa.eu`, and a test asserts no other host uses it.
- **Keys come from the environment, never from settings defaults**: `FIRECRAWL_API_KEY`, `SCRAPEDO_API_KEY`. Absent key → the provider raises at call time, never silently degrades.
- Never run `ruff format` here. After every task: `uv run ruff check apps config tests scripts`, `uv run mypy apps config`, `POSTGRES_DB=tehsil_vendor_fetch uv run pytest`.
- No migration is needed by any task in this plan. `uv run python manage.py makemigrations --check --dry-run` must stay clean.

---

## File Structure

| file | responsibility |
|---|---|
| `apps/research/fetch/__init__.py` (new) | `fetch_page()` — the router: Firecrawl, then scrape.do on failure; budget accounting; `validate_public_url` on the final URL |
| `apps/research/fetch/types.py` (new) | `FetchedPage` (extends `FetchResult` with `fetched_via`, `cost_credits`, `change_status`), `VendorUnavailable`, `FetchBudgetExhausted` |
| `apps/research/fetch/firecrawl.py` (new) | `scrape()` — `POST /v2/scrape`, markdown + changeTracking, `proxy: "auto"`, PDF parser |
| `apps/research/fetch/scrapedo.py` (new) | `scrape()` — GET API at `render=true&super=true`, records `Scrape.do-Request-Cost` |
| `config/settings/base.py` (modify) | `FIRECRAWL_API_KEY`, `SCRAPEDO_API_KEY`, `FETCH_CREDIT_BUDGET` |
| `apps/research/discovery.py` (modify, then shrink) | `retrieve_official_source` delegates to `fetch_page`; `render_with_scrapling`, `browser_fetch_options`, `render_via_browser_service` deleted in Task 6 |
| `apps/research/egress.py` (modify) | `fetch_official_source` and its redirect loop deleted in Task 6; everything else stays |
| `apps/research/browser_server.py` (delete, Task 6) | |
| `infra/template.yaml` (modify, Task 7) | every `Browser*` resource removed |
| `Dockerfile` (modify, Task 7) | `browser` stage removed |
| `pyproject.toml` (modify, Task 7) | `scrapling[fetchers]` removed |
| tests: `tests/research/test_fetch_router.py`, `test_fetch_firecrawl.py`, `test_fetch_scrapedo.py` (new); `test_discovery.py`, `test_egress.py`, `tests/infra/test_template.py` (modify); `test_browser_server.py` (delete) | |

---

### Task 1: The seam and its types

**Files:**
- Create: `apps/research/fetch/__init__.py`, `apps/research/fetch/types.py`
- Modify: `config/settings/base.py:116` (beside `SEARCH_API_KEY`)
- Test: `tests/research/test_fetch_router.py`

**Interfaces:**
- Consumes: `apps.research.egress.FetchResult`, `validate_public_url`, `SourceBlocked`
- Produces: `FetchedPage`, `VendorUnavailable`, `FetchBudgetExhausted`, and `fetch_page(url, *, providers=None, budget=None) -> FetchedPage`

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_fetch_router.py
import pytest
from apps.research.fetch.types import FetchedPage


def test_a_fetched_page_records_which_vendor_produced_it():
    """Provenance is per-fetch, not per-deployment: two pages in one sweep can come
    from different vendors and the evidence chain has to say which."""
    page = FetchedPage(
        final_url="https://example.test/a",
        redirects=(),
        content_type="text/html",
        body=b"<html></html>",
        fetched_via="FIRECRAWL",
        cost_credits=1,
    )

    assert page.fetched_via == "FIRECRAWL"
    assert page.cost_credits == 1
    assert page.change_status is None


def test_an_unknown_vendor_label_is_refused():
    """The label reaches the snapshot and a typo there is a silent provenance lie."""
    with pytest.raises(ValueError):
        FetchedPage(
            final_url="https://example.test/a", redirects=(), content_type="text/html",
            body=b"", fetched_via="FIRECRAWLL", cost_credits=1,
        )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_fetch_router.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'apps.research.fetch'`

- [ ] **Step 3: Write the types**

```python
# apps/research/fetch/types.py
"""What a vendor fetch returns, and the two ways it fails.

FetchedPage extends FetchResult rather than replacing it because every consumer
in this repo -- snapshot.py, harvest.py, reader.py, registers.py -- already
speaks FetchResult, and a parallel type would mean touching all of them to gain
three fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.research.egress import FetchResult, SourceBlocked

#: The only labels that may reach OfficialSource provenance. EGRESS survives for
#: europa.eu alone (student PII, its own pinned transport in documents/europass.py).
FETCHED_VIA = frozenset({"FIRECRAWL", "SCRAPE_DO", "EGRESS"})


class VendorUnavailable(SourceBlocked):
    """A vendor was reachable and refused, or was itself down.

    Subclasses SourceBlocked so every existing caller's except clause still
    catches it -- this plan must not change how a failed fetch propagates.
    """


class FetchBudgetExhausted(SourceBlocked):
    """The sweep's credit budget is spent. Raised before a request is made."""


@dataclass(frozen=True)
class FetchedPage(FetchResult):
    fetched_via: str = "EGRESS"
    cost_credits: int = 0
    #: Firecrawl changeTracking: new | same | changed | removed. None when the
    #: vendor did not report one -- which is not the same as "same", and a caller
    #: that treats it as "same" skips a reader run the page earned.
    change_status: str | None = None

    def __post_init__(self) -> None:
        if self.fetched_via not in FETCHED_VIA:
            raise ValueError(f"unknown fetched_via {self.fetched_via!r}")
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_fetch_router.py -v`
Expected: 2 passed

- [ ] **Step 5: Add the settings**

```python
# config/settings/base.py, beside SEARCH_API_KEY
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
SCRAPEDO_API_KEY = os.getenv("SCRAPEDO_API_KEY", "")
#: Credits one sweep may spend at scrape.do before it stops. Exists because
#: scrape.do applies per-domain multipliers of 10-200 credits server-side with no
#: request-time signal (spec 4.1a) -- a tariff in code cannot predict the bill, so
#: the budget is held against the cost header the response actually returns.
FETCH_CREDIT_BUDGET = int(os.getenv("FETCH_CREDIT_BUDGET", "5000"))
```

- [ ] **Step 6: Commit**

```bash
git add apps/research/fetch config/settings/base.py tests/research/test_fetch_router.py
git commit -m "feat: the vendor fetch seam and its result type"
```

---

### Task 2: The Firecrawl provider

**Files:**
- Create: `apps/research/fetch/firecrawl.py`
- Test: `tests/research/test_fetch_firecrawl.py`

**Interfaces:**
- Consumes: `FetchedPage`, `VendorUnavailable` from Task 1
- Produces: `firecrawl.scrape(url, *, api_key, post=...) -> FetchedPage`, where `post(url, body, headers) -> tuple[int, bytes]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/test_fetch_firecrawl.py
import json

import pytest

from apps.research.fetch import firecrawl
from apps.research.fetch.types import VendorUnavailable


def _ok(markdown="# Admission\n\nA CV is required.", url="https://example.test/a", **data):
    # changeTracking sits in `data`, beside markdown -- NOT in `metadata`.
    payload = {"success": True, "data": {
        "markdown": markdown,
        "metadata": {"url": url, "statusCode": 200},
        **data,
    }}
    return lambda *a, **k: (200, json.dumps(payload).encode())


def test_a_successful_scrape_is_labelled_and_costed():
    page = firecrawl.scrape("https://example.test/a", api_key="k", post=_ok())

    assert page.fetched_via == "FIRECRAWL"
    assert page.cost_credits == 1
    assert b"A CV is required." in page.body
    assert page.final_url == "https://example.test/a"


def test_the_vendors_final_url_is_validated_not_trusted():
    """The vendor reports where it ended up, and that value becomes
    OfficialSource.canonical_url. A private address there is provenance pointing
    inside our own VPC."""
    with pytest.raises(VendorUnavailable):
        firecrawl.scrape("https://example.test/a", api_key="k",
                         post=_ok(url="http://169.254.169.254/latest/meta-data/"))


def test_a_change_status_of_same_is_carried_through():
    """changeTracking is free and skips a $0.35 reader run -- it is the single
    largest cost lever on this path (spec 4.1b)."""
    page = firecrawl.scrape("https://example.test/a", api_key="k",
                            post=_ok(changeTracking={"changeStatus": "same"}))

    assert page.change_status == "same"


def test_a_vendor_error_raises_rather_than_returning_an_empty_page():
    """An empty body that reads as a page with no requirements is the silent
    failure this whole reader path is built to avoid."""
    fail = lambda *a, **k: (200, json.dumps({"success": False, "error": "boom"}).encode())

    with pytest.raises(VendorUnavailable):
        firecrawl.scrape("https://example.test/a", api_key="k", post=fail)


def test_a_missing_key_raises_before_any_request():
    def explode(*a, **k):
        raise AssertionError("no request may be made without a key")

    with pytest.raises(VendorUnavailable):
        firecrawl.scrape("https://example.test/a", api_key="", post=explode)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_fetch_firecrawl.py -v`
Expected: FAIL, `ImportError: cannot import name 'firecrawl'`

- [ ] **Step 3: Write the provider**

```python
# apps/research/fetch/firecrawl.py
"""Firecrawl /v2/scrape -- the default fetch tier.

Measured 2026-09-19 (spec 4.0a): recovers six of the nine hosts our own client
refused -- two 403s, two broken TLS chains, one http-only host, one connect
timeout. A hard failure costs no credits (710 before and after a DNS failure),
so trying this tier first is free when it loses; their docs add that a 403/404
does cost 1.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import urllib3

from apps.research.egress import UnsafeTarget, validate_public_url

from .types import FetchedPage, VendorUnavailable

_ENDPOINT = "https://api.firecrawl.dev/v2/scrape"
#: 1 credit. The JSON read (+4) is a separate decision measured at spec 4.4 and
#: is deliberately not requested here.
_COST = 1
Post = Callable[[str, bytes, dict[str, str]], tuple[int, bytes]]


def _post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    response = urllib3.request(
        "POST", url, body=body, headers=headers,
        timeout=urllib3.Timeout(connect=10, read=200), retries=False,
    )
    return response.status, response.data


def scrape(url: str, *, api_key: str, tag: str = "default", post: Post = _post) -> FetchedPage:
    if not api_key:
        raise VendorUnavailable("FIRECRAWL_API_KEY is not set")
    body = json.dumps({
        "url": url,
        # changeTracking bypasses the index cache, so every scrape is a fresh
        # fetch -- one credit against a reader run avoided on an unchanged page.
        "formats": ["markdown", {"type": "changeTracking", "tag": tag}],
        "proxy": "auto",
        "onlyMainContent": True,
        "parsers": [{"type": "pdf"}],
        "timeout": 120000,
    }).encode()
    try:
        status, raw = post(_ENDPOINT, body, {
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        })
    except Exception as error:  # urllib3 raises HTTPError, not OSError
        raise VendorUnavailable(f"firecrawl transport: {type(error).__name__}") from error
    try:
        document = json.loads(raw)
    except ValueError as error:
        raise VendorUnavailable(f"firecrawl returned non-JSON (HTTP {status})") from error
    if not document.get("success"):
        raise VendorUnavailable(f"firecrawl: {str(document.get('error'))[:120]}")
    data = document.get("data") or {}
    markdown = data.get("markdown") or ""
    if not markdown:
        raise VendorUnavailable("firecrawl returned no markdown")
    metadata = data.get("metadata") or {}
    final_url = str(metadata.get("url") or url)
    try:
        validate_public_url(final_url)
    except UnsafeTarget as error:
        raise VendorUnavailable(f"firecrawl final url rejected: {error}") from error
    tracking = data.get("changeTracking") or {}
    return FetchedPage(
        final_url=final_url,
        redirects=(),
        content_type="text/markdown",
        body=markdown.encode(),
        fetched_via="FIRECRAWL",
        cost_credits=_COST,
        change_status=tracking.get("changeStatus"),
    )
```

- [ ] **Step 4: Run them and watch them pass**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_fetch_firecrawl.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add apps/research/fetch/firecrawl.py tests/research/test_fetch_firecrawl.py
git commit -m "feat: firecrawl provider behind the fetch seam"
```

---

### Task 3: The scrape.do provider

**Files:**
- Create: `apps/research/fetch/scrapedo.py`
- Test: `tests/research/test_fetch_scrapedo.py`

**Interfaces:**
- Consumes: `FetchedPage`, `VendorUnavailable`
- Produces: `scrapedo.scrape(url, *, api_key, get=...) -> FetchedPage`, where `get(url) -> tuple[int, bytes, dict[str, str]]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/test_fetch_scrapedo.py
import pytest

from apps.research.fetch import scrapedo
from apps.research.fetch.types import VendorUnavailable


def _ok(body=b"<html><body>" + b"x" * 900 + b"</body></html>", cost="25", status=200):
    return lambda url: (status, body, {"Scrape.do-Request-Cost": cost})


def test_it_goes_straight_to_residential_and_browser():
    """Measured (spec 4.0a): on hosts Firecrawl has already failed, scrape.do's
    cheap tiers recovered 0 of 3, and its soft failures still charge. The ladder
    is negative value, so there is no ladder."""
    seen = {}

    def get(url):
        seen["url"] = url
        return 200, b"y" * 1000, {"Scrape.do-Request-Cost": "25"}

    scrapedo.scrape("https://example.test/a", api_key="k", get=get)

    assert "super=true" in seen["url"]
    assert "render=true" in seen["url"]


def test_the_cost_header_is_recorded_not_the_tariff():
    """scrape.do applies per-domain multipliers of 10-200 credits server-side with
    no request-time signal. The header is the only authority."""
    page = scrapedo.scrape("https://example.test/a", api_key="k", get=_ok(cost="200"))

    assert page.cost_credits == 200
    assert page.fetched_via == "SCRAPE_DO"


def test_a_thin_body_is_a_failure_not_a_page():
    """A block page returns HTTP 200 and charges. Measured: mischolarship.com came
    back 200 with 469 bytes of nothing, billed 1 credit."""
    with pytest.raises(VendorUnavailable):
        scrapedo.scrape("https://example.test/a", api_key="k", get=_ok(body=b"blocked"))


def test_a_missing_key_raises_before_any_request():
    def explode(url):
        raise AssertionError("no request may be made without a key")

    with pytest.raises(VendorUnavailable):
        scrapedo.scrape("https://example.test/a", api_key="", get=explode)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_fetch_scrapedo.py -v`
Expected: FAIL, `ImportError: cannot import name 'scrapedo'`

- [ ] **Step 3: Write the provider**

```python
# apps/research/fetch/scrapedo.py
"""scrape.do -- the residue tier, and only the residue.

Reached only when Firecrawl has already failed, and then it goes straight to
render+super (25 credits, $0.0029). Measured 2026-09-19: on hosts Firecrawl had
failed, the cheap tiers recovered 0 of 3, while a soft failure -- HTTP 200
carrying a block page -- is charged. Climbing 1 -> 5 -> 10 -> 25 costs more in
expectation than starting at the top, and being wrong at the top costs less than
the time to decide (spec 4.1b).
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

import urllib3

from apps.research.egress import UnsafeTarget, validate_public_url

from .types import FetchedPage, VendorUnavailable

_ENDPOINT = "https://api.scrape.do/"
#: Below this, a 200 is a challenge or error page rather than content.
_MIN_BODY_BYTES = 500
Get = Callable[[str], tuple[int, bytes, dict[str, str]]]


def _get(url: str) -> tuple[int, bytes, dict[str, str]]:
    response = urllib3.request(
        "GET", url, timeout=urllib3.Timeout(connect=10, read=200),
        retries=False, redirect=False,
    )
    return response.status, response.data, dict(response.headers)


def scrape(url: str, *, api_key: str, get: Get = _get) -> FetchedPage:
    if not api_key:
        raise VendorUnavailable("SCRAPEDO_API_KEY is not set")
    try:
        validate_public_url(url)
    except UnsafeTarget as error:
        raise VendorUnavailable(f"refusing to hand a non-public url to a vendor: {error}") from error
    query = urlencode({"token": api_key, "url": url, "render": "true", "super": "true"})
    try:
        status, body, headers = get(f"{_ENDPOINT}?{query}")
    except Exception as error:
        raise VendorUnavailable(f"scrape.do transport: {type(error).__name__}") from error
    cost = int(headers.get("Scrape.do-Request-Cost") or 0)
    if status != 200 or len(body) < _MIN_BODY_BYTES:
        raise VendorUnavailable(f"scrape.do returned HTTP {status} with {len(body)} bytes")
    return FetchedPage(
        final_url=url,
        redirects=(),
        content_type=headers.get("Content-Type", "text/html").split(";", 1)[0],
        body=body,
        fetched_via="SCRAPE_DO",
        cost_credits=cost,
    )
```

- [ ] **Step 4: Run them and watch them pass**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_fetch_scrapedo.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add apps/research/fetch/scrapedo.py tests/research/test_fetch_scrapedo.py
git commit -m "feat: scrape.do residue tier behind the fetch seam"
```

---

### Task 4: The router and its budget

**Files:**
- Modify: `apps/research/fetch/__init__.py`
- Test: `tests/research/test_fetch_router.py` (extend)

**Interfaces:**
- Consumes: `firecrawl.scrape`, `scrapedo.scrape`
- Produces: `fetch_page(url, *, tag="default", budget=None) -> FetchedPage`; `CreditBudget(limit)` with `.spend(n)` and `.spent`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/research/test_fetch_router.py
import pytest

from apps.research.fetch import CreditBudget, fetch_page
from apps.research.fetch.types import FetchBudgetExhausted, FetchedPage, VendorUnavailable


def _page(via, cost=1):
    return FetchedPage(final_url="https://example.test/a", redirects=(), content_type="text/html",
                       body=b"x" * 900, fetched_via=via, cost_credits=cost)


def test_firecrawl_is_tried_first_and_scrapedo_is_not_touched_when_it_wins():
    def no(*a, **k):
        raise AssertionError("scrape.do must not be called when firecrawl succeeds")

    page = fetch_page("https://example.test/a",
                      firecrawl_scrape=lambda *a, **k: _page("FIRECRAWL"), scrapedo_scrape=no)

    assert page.fetched_via == "FIRECRAWL"


def test_scrapedo_takes_over_when_firecrawl_fails():
    def boom(*a, **k):
        raise VendorUnavailable("firecrawl down")

    page = fetch_page("https://example.test/a", firecrawl_scrape=boom,
                      scrapedo_scrape=lambda *a, **k: _page("SCRAPE_DO", cost=25))

    assert page.fetched_via == "SCRAPE_DO"
    assert page.cost_credits == 25


def test_both_failing_raises_so_the_caller_records_unreachable():
    def boom(*a, **k):
        raise VendorUnavailable("nope")

    with pytest.raises(VendorUnavailable):
        fetch_page("https://example.test/a", firecrawl_scrape=boom, scrapedo_scrape=boom)


def test_the_budget_stops_the_sweep_before_a_200_credit_domain_drains_it():
    """The per-domain multiplier has no request-time signal, so the guard can only
    be held against what the response reports -- which means stopping the NEXT
    call, not the one that overspent."""
    budget = CreditBudget(limit=30)

    def boom(*a, **k):
        raise VendorUnavailable("firecrawl down")

    fetch_page("https://example.test/a", firecrawl_scrape=boom,
               scrapedo_scrape=lambda *a, **k: _page("SCRAPE_DO", cost=200), budget=budget)
    assert budget.spent == 200

    with pytest.raises(FetchBudgetExhausted):
        fetch_page("https://example.test/b", firecrawl_scrape=boom,
                   scrapedo_scrape=lambda *a, **k: _page("SCRAPE_DO", cost=25), budget=budget)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_fetch_router.py -v`
Expected: FAIL, `ImportError: cannot import name 'fetch_page'`

- [ ] **Step 3: Write the router**

```python
# apps/research/fetch/__init__.py
"""The one door every research page fetch goes through.

Firecrawl first, scrape.do on failure, nothing else. Our own client is not a
tier here: anti-bot handling, challenge solving and JS rendering are a vendor's
job (owner decision 2026-09-19), and europa.eu -- the one path carrying student
PII -- never comes through this module at all. It keeps its own pinned transport
in apps/documents/europass.py.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.conf import settings

from . import firecrawl, scrapedo
from .types import FetchBudgetExhausted, FetchedPage, VendorUnavailable

logger = logging.getLogger(__name__)

__all__ = ["CreditBudget", "FetchedPage", "VendorUnavailable", "FetchBudgetExhausted", "fetch_page"]


class CreditBudget:
    """A sweep's credit ceiling, held against what responses actually cost.

    Not a per-call price check: scrape.do's per-domain multipliers (10-200
    credits) are applied server-side and are not knowable before the request, so
    the only honest guard stops the NEXT call once the ceiling is passed.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0

    def check(self) -> None:
        if self.spent >= self.limit:
            raise FetchBudgetExhausted(f"sweep spent {self.spent} of {self.limit} credits")

    def spend(self, credits: int) -> None:
        self.spent += credits


def fetch_page(
    url: str,
    *,
    tag: str = "default",
    budget: CreditBudget | None = None,
    firecrawl_scrape: Callable[..., FetchedPage] = firecrawl.scrape,
    scrapedo_scrape: Callable[..., FetchedPage] = scrapedo.scrape,
) -> FetchedPage:
    if budget is not None:
        budget.check()
    try:
        page = firecrawl_scrape(url, api_key=settings.FIRECRAWL_API_KEY, tag=tag)
    except VendorUnavailable as first:
        logger.info("firecrawl failed for %s: %s", url, first)
        # No ladder: a host that beat proxy:"auto" has beaten one vendor's own
        # escalation already, so the cheap scrape.do tiers are negative value.
        page = scrapedo_scrape(url, api_key=settings.SCRAPEDO_API_KEY)
    if budget is not None:
        budget.spend(page.cost_credits)
    return page
```

- [ ] **Step 4: Run them and watch them pass**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_fetch_router.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add apps/research/fetch/__init__.py tests/research/test_fetch_router.py
git commit -m "feat: the fetch router, firecrawl then scrape.do, with a credit budget"
```

---

### Task 5: Point every caller at the seam

**Files:**
- Modify: `apps/research/discovery.py` (`retrieve_official_source`)
- Test: `tests/research/test_discovery.py`

**Interfaces:**
- Consumes: `fetch_page` from Task 4
- Produces: `retrieve_official_source(url, *, fetch=fetch_page) -> FetchedPage` — same name, same position, so `pipeline.py`, `seeds.py`, `services.py`, `registers.py`, `reader.py` and `documents/program_rules.py` need no change

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_discovery.py
def test_retrieve_official_source_goes_to_the_vendor_path():
    """One seam, so the six callers that already pass `retrieve=` keep working
    unchanged -- reader.py, program_rules.py, pipeline.py, seeds.py, services.py,
    registers.py."""
    from apps.research.discovery import retrieve_official_source
    from apps.research.fetch.types import FetchedPage

    called = {}

    def fake_fetch(url, **kwargs):
        called["url"] = url
        return FetchedPage(final_url=url, redirects=(), content_type="text/markdown",
                           body=b"# page", fetched_via="FIRECRAWL", cost_credits=1)

    page = retrieve_official_source("https://example.test/a", fetch=fake_fetch)

    assert called["url"] == "https://example.test/a"
    assert page.fetched_via == "FIRECRAWL"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_discovery.py::test_retrieve_official_source_goes_to_the_vendor_path -v`
Expected: FAIL, `TypeError: retrieve_official_source() got an unexpected keyword argument 'fetch'`

- [ ] **Step 3: Rewrite `retrieve_official_source`**

```python
# apps/research/discovery.py -- replaces the plain-then-browser body
def retrieve_official_source(
    url: str,
    *,
    fetch: Callable[..., FetchedPage] = fetch_page,
    tag: str = "default",
    budget: CreditBudget | None = None,
) -> FetchedPage:
    """Fetch one public page through the vendor path.

    The plain-fetch-then-browser ladder this function used to hold is gone: both
    tiers are a vendor's now, and `fetch_page` owns the order. `canonicalize_url`
    stays because a caller may hand us a URL that has never been normalised.
    """
    return fetch(canonicalize_url(url), tag=tag, budget=budget)
```

- [ ] **Step 4: Run the whole research suite**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research -v`
Expected: PASS except tests that stub `plain_fetch=`/`browser_render=`. Update each to stub `fetch=` instead — the substitution is mechanical and the assertions do not change.

- [ ] **Step 5: Commit**

```bash
git add apps/research/discovery.py tests/research
git commit -m "refactor: retrieve_official_source delegates to the vendor router"
```

---

### Task 6: Delete our own page fetcher and the browser tier

**Files:**
- Modify: `apps/research/egress.py` (delete `fetch_official_source` and its helpers)
- Modify: `apps/research/discovery.py` (delete `render_with_scrapling`, `browser_fetch_options`, `render_via_browser_service`)
- Delete: `apps/research/browser_server.py`, `tests/research/test_browser_server.py`
- Test: `tests/research/test_egress.py`

**Interfaces:**
- Consumes: nothing new
- Produces: an `egress.py` holding only `validate_public_url`, `_request`, `fetch_json_api`, `require_same_origin`, `looks_unrendered`, `LocalEgressProxy`, and the shared types

- [ ] **Step 1: Write the test that pins what must survive**

```python
# tests/research/test_egress.py
def test_the_module_still_serves_the_two_paths_that_are_not_scraping():
    """Deleting "our own client" means the PAGE fetcher. Two things keep a
    first-party transport, and both would be bugs to hand a vendor:

    - fetch_json_api POSTs to CONTRACTED apis carrying our own keys (the search
      providers, DEQAR, WHED). Routing those through scrape.do ships our keys to
      a third party and breaches the terms the roster was built to respect.
    - validate_public_url is the SSRF guard, and documents/europass.py -- the one
      path carrying a student's name, date of birth and history -- imports it for
      its own pinned transport to europa.eu.
    """
    from apps.research import egress

    assert hasattr(egress, "fetch_json_api")
    assert hasattr(egress, "validate_public_url")
    assert not hasattr(egress, "fetch_official_source")


def test_nothing_in_research_can_fetch_a_page_without_a_vendor():
    import pathlib

    source = pathlib.Path("apps/research").rglob("*.py")
    offenders = [p for p in source if "scrapling" in p.read_text().lower()]

    assert offenders == []
```

- [ ] **Step 2: Run them and watch the first fail**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/research/test_egress.py -v`
Expected: FAIL on `assert not hasattr(egress, "fetch_official_source")`

- [ ] **Step 3: Delete**

```bash
# in apps/research/egress.py delete: fetch_official_source, _THROTTLED,
# _MAX_BACKOFF_SECONDS, _RETRY_ATTEMPTS, _backoff_seconds, and
# ResponseTooLarge/RedirectLimitExceeded if the remaining callers do not raise
# them -- check with grep before removing each.
#
# KEEP USER_AGENT. _request survives for fetch_json_api, which POSTs to
# CONTRACTED apis carrying our own keys, and an identifying client is as right
# there as it was for pages. tests/research/test_egress.py::
# test_every_fetch_identifies_itself pins it and must stay green.
# in apps/research/discovery.py delete: render_with_scrapling,
# browser_fetch_options, render_via_browser_service, BROWSER_SERVICE_URL.
git rm apps/research/browser_server.py tests/research/test_browser_server.py
grep -rn "fetch_official_source\|render_with_scrapling\|render_via_browser_service" apps/ tests/
```

Every remaining hit must be fixed before the next step; there should be none.

- [ ] **Step 4: Run the full suite**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest`
Expected: all pass. `uv run ruff check apps config tests scripts` and `uv run mypy apps config` clean.

- [ ] **Step 5: Commit**

```bash
git add -A apps/research tests/research
git commit -m "refactor: delete our own page fetcher and the scrapling browser tier"
```

---

### Task 7: Delete the browser infrastructure

**Files:**
- Modify: `infra/template.yaml` — remove `BrowserImage`, `BrowserDesiredCount`, `BrowserSecurityGroup`, `BrowserNamespace`, `BrowserDiscoveryService`, `BrowserLogGroup`, `BrowserTaskDefinition`, `BrowserService`, `BrowserRenderFailureFilter`, `BrowserRenderFailureRateAlarm`, and `BROWSER_SERVICE_URL` from `WorkerTaskDefinition`
- Modify: `Dockerfile` — remove the `browser` stage and its `patchright install`
- Modify: `pyproject.toml` — remove `scrapling[fetchers]` and the comment above it
- Modify: `tests/infra/test_template.py` — delete the six browser tests, add one
- Modify: `infra/parameters/test.json`, `infra/parameters/production.json` if they carry `BrowserImage`/`BrowserDesiredCount`

**Interfaces:** none — infrastructure only.

- [ ] **Step 1: Write the replacement test**

```python
# tests/infra/test_template.py -- replaces the six Browser* tests
def test_no_browser_tier_remains(template: Template) -> None:
    """The research path is vendor-only (spec 4, owner decision 2026-09-19), so
    there is no Chromium in this account to secure. The four properties the old
    tests pinned -- no task role, its own security group, not in the database
    group, shipped stopped -- are all satisfied by the resource not existing.

    Deliberately NOT deleted: the DatabaseSecurityGroup ingress test above. Its
    list is still load-bearing for web, worker and portal.
    """
    assert [name for name in template.resources if name.startswith("Browser")] == []
    worker = template.resources["WorkerTaskDefinition"]
    env = worker["Properties"]["ContainerDefinitions"][0].get("Environment", [])
    assert [e for e in env if e["Name"] == "BROWSER_SERVICE_URL"] == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest tests/infra/test_template.py::test_no_browser_tier_remains -v`
Expected: FAIL — the `Browser*` resources are present.

- [ ] **Step 3: Delete the resources, the stage and the dependency**

```bash
# remove every Browser* block from infra/template.yaml and the BROWSER_SERVICE_URL
# entry at line ~1423; remove the `browser` stage from the Dockerfile; remove
# scrapling from pyproject.toml, then re-lock:
uv lock
grep -n "Browser\|scrapling\|patchright" infra/template.yaml Dockerfile pyproject.toml
```

- [ ] **Step 4: Delete the six superseded tests and run the suite**

Delete from `tests/infra/test_template.py`: `test_the_browser_task_has_no_role_and_no_secrets`, `test_only_the_research_worker_may_reach_the_browser`, `test_the_browser_service_ships_stopped`, `test_the_worker_is_told_where_the_browser_is`, `test_the_browser_crash_alarm_pages_on_a_single_traceback`, and the browser half of `test_the_openai_key_stays_off_the_web_and_browser_tiers` (keep the web half). Leave `test_no_payment_or_browser_submission_resources` — it pins a different thing.

Run: `POSTGRES_DB=tehsil_vendor_fetch uv run pytest`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A infra Dockerfile pyproject.toml uv.lock tests/infra
git commit -m "refactor: delete the browser task, its security group and the scrapling dependency"
```

---

### Task 8: Rewrite the record

**Files:**
- Modify: `CLAUDE.md` — the "Web fetching" section and the "Two browsers, two opposite security models" table
- Modify: `docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` §7 increments 2 and 3

**Interfaces:** none.

- [ ] **Step 1: Rewrite CLAUDE.md's Web-fetching section as record, not design**

The direction-change block becomes the section. Keep, as history with its reason: the Fargate `--no-sandbox` measurement, the `/proc/<pid>/environ` result, and why the browser task had no role — someone will propose a browser again and these are the measurements that answer it. Delete as live design: the Scrapling rules (`block_webrtc`, `solve_cloudflare`, `accept_downloads`), the two-browser table's browser column, and the `BrowserDesiredCount: 0` dormancy note.

State plainly what replaces them: research pages come from Firecrawl, then scrape.do; `europa.eu` keeps its own pinned transport because it carries student PII; contracted APIs keep `fetch_json_api` because they carry our keys.

- [ ] **Step 2: Mark increments 2 and 3 done in the spec, and record what was NOT deleted**

Add under §7 item 3: `LocalEgressProxy` survives until the glass-box portal deletion (`apps/portals/engine.py` imports it), and `readable_text`'s section selection survives on purpose — it is the local extractor the free-tier route in §4.1c depends on.

- [ ] **Step 3: Run everything one last time**

```bash
POSTGRES_DB=tehsil_vendor_fetch uv run pytest
uv run ruff check apps config tests scripts
uv run mypy apps config
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs
git commit -m "docs: the web-fetching section becomes record; increments 2 and 3 done"
```

---

## Self-Review

**Spec coverage.** §4.0/§4.0a → Tasks 5–6 (tier zero deleted, ladder replaced). §4.1 capability table → Task 2. §4.1a scrape.do → Task 3. §4.1b economics (no ladder, budget on the cost header) → Tasks 3–4. §4.1c free tier → no task needed; it is an operational choice, and `FETCH_CREDIT_BUDGET` is the control. §4.3 what is kept (`fetched_via`, final-URL validation) → Tasks 1–2. §7 increments 2 and 3 → the whole plan.

**Not covered here, deliberately:** `/crawl` replacing the link walker, `maxAge`, the reachability retry queue and its daily command (all named in increment 2). They are a separate plan — this one is the fetch path and its deletion, and a crawl-traversal change alters what gets discovered, not how a page is fetched. Splitting them keeps each independently reviewable.

**Gap found and closed during review:** increment 2 names Tavily Extract as the fallback vendor. This plan drops it, per §4.1a — scrape.do covers the same outage case and is the only tier that also covers a blocked host. Tavily keeps `/map` and name-to-site resolution, neither of which is a fetch and neither of which this plan touches.
