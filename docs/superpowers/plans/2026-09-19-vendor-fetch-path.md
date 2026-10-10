# Vendor Fetch Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Research pages are fetched through a cost-aware ladder — our own client first, then scrape.do or Firecrawl in an order chosen by whether we are on free quota or a paid plan — with the vendor's per-request cost recorded per host and a per-sweep credit budget that stops a sweep before a surprise bill.

**Architecture:** One new module, `apps/research/vendors.py`, holds two thin vendor clients (Firecrawl `/v2/scrape`, scrape.do GET), a `SweepBudget`, and `fetch_via_vendors(url)` which walks the ladder for the configured mode and returns the same `FetchResult` every caller already consumes. `discovery.retrieve_official_source` — the one seam `reader.py` and `program_rules.py` call — hands a refused or JavaScript-only page to that function instead of the retired browser tier. Every vendor body is HTML (or text) so `readable_text`, `content_digest` and `persist_snapshot` run unchanged; the only downstream change is a `fetched_via` label on `FetchResult` and on the snapshot row.

**Tech Stack:** Python 3.12, Django, urllib3 (already a dependency; no vendor SDK), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` §4, in particular §4.1b (economics) and §4.1c (free vs paid). §4.1b/§4.1c are being committed by the vendor-search session on `claude/program-page-reader`; the rules this plan implements are copied verbatim below so the plan stands alone.

## Global Constraints

- **Dollars, not credits, compare vendors.** Firecrawl Standard $83 / 100k = $0.00083 a credit; scrape.do Hobby $29 / 250k = $0.000116 a credit. Both figures are constants in code, labelled with the plan they assume.
- **Quota mode is the near-term default** (`FETCH_VENDOR_MODE=quota`): our client → scrape.do datacenter → scrape.do `render=true&super=true` → Firecrawl `proxy: "auto"` → `UNREACHABLE`. Firecrawl's credits are spent on ordinary pages only as the last rung, because both accounts hold 1,000 free credits and nothing else competes for scrape.do's.
- **Paid mode** (`FETCH_VENDOR_MODE=paid`, the day a Firecrawl plan is bought): our client → Firecrawl `proxy: "auto"` with `changeTracking` → scrape.do `render=true&super=true` → `UNREACHABLE`. No cheap scrape.do rung: "a host that beat `proxy: "auto"` has already beaten one vendor's own escalation; scrape.do's cheap tiers recovered 0 of 3 such hosts."
- **`Scrape.do-Request-Cost` is authoritative.** Per-domain multipliers of 10–200 credits are applied server-side with no request-time signal. Record the header per host, never a tariff.
- **Firecrawl reports no credits in its response.** Charge by tariff: 1 per scrape, +4 with a `json` format; 0 on a vendor-side failure (measured 2026-09-19: 710 credits before and after a DNS failure); 1 when the envelope is 200 but `metadata.statusCode` ≥ 400 (their docs).
- **A per-sweep credit budget per vendor.** Exceeding it raises and the sweep stops; the caller decides. Defaults from settings, overridable per sweep.
- **`europa.eu` never reaches a vendor.** Student PII travels that path; `apps/documents/europass.py` keeps its pinned-address client. A test asserts it.
- **Every vendor final URL runs through `validate_public_url` and must be HTTPS**, exactly as the plain tier's redirect hops do. A vendor is an untrusted sender of a URL that becomes provenance.
- **No silent fallbacks.** A vendor rung skipped for a missing key is logged at WARNING with the vendor's name; the combined failure reason names each rung's error class. Third-party text never enters a reason string (it lands in a 200-character column consultants read).
- **Bodies stay HTML.** Firecrawl is asked for `html` (its cleaned HTML) plus `markdown` and `changeTracking`; scrape.do for `output=raw`. `readable_text` and `content_digest` are the extraction layer in both modes — the owner's rule: "local extraction covers the rest".
- **Never `ruff format` this repo** (toolchain memory). `uv run ruff check` and `uv run mypy` are the gates, plus `uv run pytest`.
- **Test database per worktree:** run pytest with `POSTGRES_DB=tehsil_fetch_path`.

---

## File Structure

| file | responsibility |
|---|---|
| `apps/research/vendors.py` (new) | `USD_PER_CREDIT`, `VendorUnavailable`, `FetchBudgetExhausted`, `VendorFetch`, `SweepBudget`, `firecrawl_scrape`, `scrape_do_fetch`, `record_host_cost`, `fetch_via_vendors`, `never_vendored` |
| `apps/research/models.py` (modify) | `HostFetchCost` |
| `apps/research/migrations/0003_hostfetchcost.py` (new, number per `ls`) | the table |
| `apps/research/egress.py` (modify) | `FetchResult.fetched_via` |
| `apps/research/discovery.py` (modify) | `retrieve_official_source` hands refused/JS pages to `fetch_via_vendors` |
| `apps/research/snapshot.py` (modify) | `persist_snapshot` writes `fetched_via` |
| `apps/funding/models.py` + `apps/funding/migrations/00NN_snapshot_fetched_via.py` | `OfficialSourceSnapshot.fetched_via` |
| `config/settings/base.py` (modify) | `FIRECRAWL_API_KEY`, `SCRAPE_DO_API_KEY`, `FETCH_VENDOR_MODE`, `FETCH_SWEEP_CREDITS` |
| `apps/research/management/commands/fetch_ladder.py` (new) | run the ladder over URLs, print tier and cost per host — the §4.5 gate tool |
| `tests/research/test_vendors.py` (new), `tests/research/test_discovery.py` (modify), `tests/research/test_snapshot.py` (modify), `tests/research/test_fetch_ladder.py` (new) | |

---

### Task 1: Budget and cost constants

**Files:**
- Create: `apps/research/vendors.py`
- Test: `tests/research/test_vendors.py`

**Interfaces:**
- Produces: `USD_PER_CREDIT: dict[str, float]`, `FetchBudgetExhausted(RuntimeError)`, `SweepBudget(credits: Mapping[str, int])` with `.spend(vendor: str, credits: int) -> None`, `.spent: dict[str, int]`, `.usd() -> float`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/test_vendors.py
import pytest

from apps.research.vendors import USD_PER_CREDIT, FetchBudgetExhausted, SweepBudget


def test_a_sweep_budget_stops_at_its_cap_per_vendor() -> None:
    budget = SweepBudget(credits={"SCRAPE_DO": 30, "FIRECRAWL": 5})

    budget.spend("SCRAPE_DO", 25)
    with pytest.raises(FetchBudgetExhausted):
        budget.spend("SCRAPE_DO", 25)  # a 25-credit residential fetch after a 25-credit one
    budget.spend("FIRECRAWL", 5)  # the other vendor's cap is separate

    assert budget.spent == {"SCRAPE_DO": 25, "FIRECRAWL": 5}


def test_a_budget_reports_dollars_not_credits() -> None:
    """Credits are not comparable across vendors; dollars are (spec §4.1b)."""
    budget = SweepBudget(credits={"SCRAPE_DO": 1_000, "FIRECRAWL": 1_000})
    budget.spend("SCRAPE_DO", 25)
    budget.spend("FIRECRAWL", 1)

    assert budget.usd() == pytest.approx(25 * USD_PER_CREDIT["SCRAPE_DO"] + USD_PER_CREDIT["FIRECRAWL"])
    assert USD_PER_CREDIT["FIRECRAWL"] / USD_PER_CREDIT["SCRAPE_DO"] == pytest.approx(7.16, abs=0.01)


def test_an_unknown_vendor_is_refused_not_ignored() -> None:
    with pytest.raises(KeyError):
        SweepBudget(credits={"SCRAPE_DO": 1}).spend("TAVILY", 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd .worktrees/fetch-path && POSTGRES_DB=tehsil_fetch_path uv run pytest tests/research/test_vendors.py -v`
Expected: FAIL, `ModuleNotFoundError: apps.research.vendors`

- [ ] **Step 3: Minimal implementation**

```python
# apps/research/vendors.py
"""The vendor fetch path: scrape.do and Firecrawl behind one ladder.

Spec §4 (2026-09-18 fetch tiers), §4.1b (economics) and §4.1c (quota vs paid).
Dollars compare vendors, credits do not: Firecrawl is 7x dearer per credit and
still the default once a plan is bought, because its free changeTracking skips
a $0.35 reader run. Until then quota binds, so scrape.do fetches ordinary pages.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Firecrawl Standard $83 / 100k credits; scrape.do Hobby $29 / 250k. Plans the
#: owner priced on 2026-09-19 -- change both together when a plan is bought.
USD_PER_CREDIT: dict[str, float] = {"FIRECRAWL": 83 / 100_000, "SCRAPE_DO": 29 / 250_000}


class FetchBudgetExhausted(RuntimeError):
    """The sweep's credit cap for one vendor would be exceeded."""


class SweepBudget:
    """Credits a sweep may spend, per vendor.

    The cap is checked after the vendor reports the cost, because scrape.do's
    per-domain multiplier (10-200 credits) is only known from the response
    header. So one surprise lands, is recorded, and stops the next fetch.
    # ponytail: post-hoc check; reserve-then-settle if one 200-credit call ever matters.
    """

    def __init__(self, *, credits: Mapping[str, int]) -> None:
        self.caps = dict(credits)
        self.spent: dict[str, int] = dict.fromkeys(self.caps, 0)

    def spend(self, vendor: str, credits: int) -> None:
        cap = self.caps[vendor]
        if self.spent[vendor] + credits > cap:
            raise FetchBudgetExhausted(
                f"{vendor}: {self.spent[vendor]} + {credits} credits exceeds the sweep cap {cap}"
            )
        self.spent[vendor] += credits

    def usd(self) -> float:
        return sum(USD_PER_CREDIT[vendor] * credits for vendor, credits in self.spent.items())
```

- [ ] **Step 4: Run to verify pass** — same command, expected 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/research/vendors.py tests/research/test_vendors.py
git commit -m "research: a per-sweep credit budget priced in dollars"
```

---

### Task 2: `FetchResult.fetched_via` and the snapshot label

**Files:**
- Modify: `apps/research/egress.py:60-66`
- Modify: `apps/research/snapshot.py:54-71`
- Modify: `apps/funding/models.py` (`OfficialSourceSnapshot`, after `discovery_technique`)
- Create: `apps/funding/migrations/00NN_snapshot_fetched_via.py` (Django writes it)
- Test: `tests/research/test_snapshot.py`

**Interfaces:**
- Produces: `FetchResult(..., fetched_via: str = "EGRESS")`; `OfficialSourceSnapshot.fetched_via` CharField(20, default `"EGRESS"`).

- [ ] **Step 1: Failing test** (append to `tests/research/test_snapshot.py`, reusing that file's existing `source`/`store` fixtures — read the file first and copy the fixture names it uses)

```python
def test_a_snapshot_records_which_tier_fetched_it(source, store) -> None:
    fetch = FetchResult("https://official.example/p", (), "text/html", b"<p>x</p>", fetched_via="SCRAPE_DO")

    result = persist_snapshot(source=source, fetch=fetch, store=store, admissions_cycle="2026/27")

    assert result.snapshot.fetched_via == "SCRAPE_DO"


def test_the_default_tier_label_is_our_own_client() -> None:
    assert FetchResult("https://a.example/", (), "text/html", b"").fetched_via == "EGRESS"
```

- [ ] **Step 2: Run** — expected FAIL, `unexpected keyword argument 'fetched_via'`.

- [ ] **Step 3: Implement**

`egress.py`:
```python
@dataclass(frozen=True)
class FetchResult:
    final_url: str
    redirects: tuple[str, ...]
    content_type: str
    body: bytes
    browser_required: bool = False
    #: Which tier produced the body: EGRESS (our client), SCRAPE_DO, FIRECRAWL.
    #: Provenance for the snapshot -- a vendor's HTML is its rendering, not origin bytes.
    fetched_via: str = "EGRESS"
```

`apps/funding/models.py`, inside `OfficialSourceSnapshot` after `discovery_technique`:
```python
    fetched_via = models.CharField(max_length=20, default="EGRESS")
```

`snapshot.py`, in the `create(...)` call: add `fetched_via=fetch.fetched_via,` and to `SnapshotResult` nothing (callers read the row).

Then: `POSTGRES_DB=tehsil_fetch_path uv run python manage.py makemigrations funding -n snapshot_fetched_via`

- [ ] **Step 4: Run** `tests/research/test_snapshot.py` — PASS; also `uv run python manage.py makemigrations --check`.

- [ ] **Step 5: Commit**

```bash
git add apps/research/egress.py apps/research/snapshot.py apps/funding/models.py apps/funding/migrations/00NN_snapshot_fetched_via.py tests/research/test_snapshot.py
git commit -m "research: every snapshot says which tier fetched it"
```

---

### Task 3: The scrape.do client

**Files:**
- Modify: `apps/research/vendors.py`
- Test: `tests/research/test_vendors.py`

**Interfaces:**
- Produces: `VendorUnavailable(SourceBlocked)`, `VendorFetch(result: FetchResult, vendor: str, credits: int, remaining_credits: int | None, change_status: str | None, markdown: str | None)`, `scrape_do_fetch(url, *, api_key, http=urllib3.request, render=False, residential=False, timeout=120) -> VendorFetch`.
- `http` has urllib3's `request(method, url, *, fields=..., headers=..., body=..., timeout=..., retries=...)` shape and returns an object with `.status`, `.headers` (Mapping), `.data` (bytes).

- [ ] **Step 1: Failing tests**

```python
from types import SimpleNamespace

from apps.research.egress import SourceBlocked, UnsafeTarget
from apps.research.vendors import VendorUnavailable, scrape_do_fetch


def _response(status: int, body: bytes = b"", **headers: str) -> SimpleNamespace:
    return SimpleNamespace(status=status, data=body, headers={"Content-Type": "text/html; charset=utf-8", **headers})


def test_scrape_do_returns_html_with_the_cost_the_header_says(monkeypatch) -> None:
    """The header is authoritative: a per-domain multiplier makes a 1-credit call cost 200."""
    seen: dict = {}

    def http(method, url, *, fields, timeout, retries):
        seen.update(fields)
        return _response(
            200, b"<p>ok</p>",
            **{"Scrape.do-Request-Cost": "200", "Scrape.do-Remaining-Credits": "800",
               "Scrape.do-Resolved-Url": "https://official.example/final"},
        )

    monkeypatch.setattr("apps.research.vendors.validate_public_url", lambda url: None)
    fetched = scrape_do_fetch("https://official.example/p", api_key="k", http=http)

    assert seen["url"] == "https://official.example/p"
    assert seen["output"] == "raw" and "render" not in seen and "super" not in seen
    assert fetched.credits == 200 and fetched.remaining_credits == 800
    assert fetched.result.final_url == "https://official.example/final"
    assert fetched.result.fetched_via == "SCRAPE_DO"
    assert fetched.result.content_type == "text/html"


def test_scrape_do_residential_render_sets_both_flags(monkeypatch) -> None:
    seen: dict = {}

    def http(method, url, *, fields, timeout, retries):
        seen.update(fields)
        return _response(200, b"<p>ok</p>", **{"Scrape.do-Request-Cost": "25"})

    monkeypatch.setattr("apps.research.vendors.validate_public_url", lambda url: None)
    scrape_do_fetch("https://official.example/p", api_key="k", http=http, render=True, residential=True)

    assert seen["render"] == "true" and seen["super"] == "true"


@pytest.mark.parametrize("status", [401, 429, 502, 510])
def test_scrape_do_own_failures_are_vendor_unavailable_and_free(status) -> None:
    with pytest.raises(VendorUnavailable) as info:
        scrape_do_fetch("https://official.example/p", api_key="k", http=lambda *a, **k: _response(status))
    assert f"HTTP {status}" in str(info.value)


def test_a_target_error_is_source_blocked_and_still_charged(monkeypatch) -> None:
    """scrape.do bills a 404 from the target (their status-code table)."""
    monkeypatch.setattr("apps.research.vendors.validate_public_url", lambda url: None)
    with pytest.raises(SourceBlocked) as info:
        scrape_do_fetch("https://official.example/p", api_key="k",
                        http=lambda *a, **k: _response(404, **{"Scrape.do-Request-Cost": "1"}))
    assert "HTTP 404" in str(info.value) and info.value.credits == 1


def test_a_vendor_final_url_is_validated_like_our_own_redirects() -> None:
    """A vendor is an untrusted sender of a URL that becomes provenance."""
    with pytest.raises(UnsafeTarget):
        scrape_do_fetch("https://official.example/p", api_key="k",
                        http=lambda *a, **k: _response(200, b"x", **{"Scrape.do-Resolved-Url": "https://10.0.0.7/"}))
```

Note `SourceBlocked.credits`: define a `ChargedFailure(SourceBlocked)` carrying `credits` so the ladder can still record and budget a paid failure.

- [ ] **Step 2: Run** — FAIL on import.

- [ ] **Step 3: Implement** (append to `vendors.py`)

```python
import logging
from dataclasses import dataclass

import urllib3

from .discovery import canonicalize_url
from .egress import FetchResult, SourceBlocked, UnsafeTarget, validate_public_url

logger = logging.getLogger(__name__)

SCRAPE_DO_URL = "https://api.scrape.do/"
#: scrape.do's own failures, none charged (their status-code table, read 2026-09-19):
#: 401 no credits / suspended, 429 concurrency, 502 "please try again", 510 client cancelled.
_SCRAPE_DO_OWN = {401, 429, 502, 510}


class VendorUnavailable(SourceBlocked):
    """The vendor itself refused or failed -- not the target. Never charged."""


class ChargedFailure(SourceBlocked):
    """The target failed through the vendor and the vendor billed it anyway."""

    def __init__(self, message: str, *, credits: int) -> None:
        super().__init__(message)
        self.credits = credits


@dataclass(frozen=True)
class VendorFetch:
    result: FetchResult
    vendor: str
    credits: int
    remaining_credits: int | None = None
    change_status: str | None = None
    markdown: str | None = None


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    value = headers.get(name)
    return int(value) if value and value.isdigit() else None


def _provenance_url(candidate: str) -> str:
    """Validate a URL a vendor reported as final, exactly as our redirect hops are."""
    validate_public_url(candidate)  # private address, userinfo -> UnsafeTarget
    if not candidate.startswith("https://"):
        raise UnsafeTarget(candidate)
    return canonicalize_url(candidate)


def scrape_do_fetch(
    url: str,
    *,
    api_key: str,
    http=urllib3.request,
    render: bool = False,
    residential: bool = False,
    timeout: float = 120,
) -> VendorFetch:
    """One scrape.do GET. ``output=raw``: our readable_text is the extractor
    (their markdown converts <head> too -- measured 2026-09-19)."""
    fields = {"token": api_key, "url": url, "output": "raw"}
    if render:
        fields["render"] = "true"
    if residential:
        fields["super"] = "true"
    response = http("GET", SCRAPE_DO_URL, fields=fields, timeout=timeout, retries=False)
    headers = response.headers
    credits = _int_header(headers, "Scrape.do-Request-Cost") or 0
    if response.status in _SCRAPE_DO_OWN:
        raise VendorUnavailable(f"scrape.do answered HTTP {response.status}")
    if response.status >= 400:
        raise ChargedFailure(f"source returned HTTP {response.status}", credits=credits)
    final_url = _provenance_url(headers.get("Scrape.do-Resolved-Url") or url)
    content_type = (headers.get("Content-Type") or "").split(";", 1)[0]
    return VendorFetch(
        result=FetchResult(final_url, (), content_type, response.data, fetched_via="SCRAPE_DO"),
        vendor="SCRAPE_DO",
        credits=credits or 1,
        remaining_credits=_int_header(headers, "Scrape.do-Remaining-Credits"),
    )
```

Note: urllib3's `HTTPResponse.headers` is an `HTTPHeaderDict`, case-insensitive `.get`; the fake in tests is a plain dict with exact names — fine because the code uses the documented casing.

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Commit** `git commit -m "research: the scrape.do client records the cost the header says"`

---

### Task 4: The Firecrawl client

**Files:**
- Modify: `apps/research/vendors.py`
- Test: `tests/research/test_vendors.py`

**Interfaces:**
- Produces: `firecrawl_scrape(url, *, api_key, http=urllib3.request, change_tracking=True, json_format: dict | None = None, timeout=120) -> VendorFetch`.

- [ ] **Step 1: Failing tests**

```python
import json

from apps.research.vendors import firecrawl_scrape


def _fc(payload: dict, status: int = 200) -> SimpleNamespace:
    return SimpleNamespace(status=status, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})


def test_firecrawl_asks_for_html_markdown_and_free_change_tracking(monkeypatch) -> None:
    seen: dict = {}

    def http(method, url, *, body, headers, timeout, retries):
        seen.update(json.loads(body))
        return _fc({"success": True, "data": {
            "html": "<main><p>ok</p></main>", "markdown": "ok",
            "changeTracking": {"changeStatus": "same", "previousScrapeAt": None, "visibility": "visible", "diff": None},
            "metadata": {"sourceURL": "https://official.example/p", "url": "https://official.example/p/", "statusCode": 200, "contentType": "text/html"},
        }})

    monkeypatch.setattr("apps.research.vendors.validate_public_url", lambda url: None)
    fetched = firecrawl_scrape("https://official.example/p", api_key="k", http=http)

    assert seen["url"] == "https://official.example/p" and seen["proxy"] == "auto"
    assert {f["type"] if isinstance(f, dict) else f for f in seen["formats"]} == {"html", "markdown", "changeTracking"}
    assert seen["parsers"] == [{"type": "pdf"}]
    assert fetched.credits == 1 and fetched.change_status == "same"
    assert fetched.result.body == b"<main><p>ok</p></main>" and fetched.result.content_type == "text/html"
    assert fetched.result.final_url == "https://official.example/p/" and fetched.result.fetched_via == "FIRECRAWL"


def test_a_json_read_costs_four_more_credits(monkeypatch) -> None:
    monkeypatch.setattr("apps.research.vendors.validate_public_url", lambda url: None)
    ok = {"success": True, "data": {"html": "<p>x</p>", "markdown": "x", "json": {"a": 1},
          "metadata": {"sourceURL": "https://o.example/", "url": "https://o.example/", "statusCode": 200}}}
    fetched = firecrawl_scrape("https://o.example/", api_key="k", http=lambda *a, **k: _fc(ok),
                               json_format={"schema": {"type": "object"}, "prompt": "p"})
    assert fetched.credits == 5


def test_a_pdf_arrives_as_text_when_firecrawl_parsed_it(monkeypatch) -> None:
    monkeypatch.setattr("apps.research.vendors.validate_public_url", lambda url: None)
    ok = {"success": True, "data": {"html": None, "markdown": "Curriculum Vitae template",
          "metadata": {"sourceURL": "https://o.example/cv.pdf", "url": "https://o.example/cv.pdf", "statusCode": 200, "contentType": "application/pdf"}}}
    fetched = firecrawl_scrape("https://o.example/cv.pdf", api_key="k", http=lambda *a, **k: _fc(ok))
    assert fetched.result.content_type == "text/plain" and fetched.result.body == b"Curriculum Vitae template"


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_firecrawl_own_failures_are_vendor_unavailable_and_free(status) -> None:
    with pytest.raises(VendorUnavailable):
        firecrawl_scrape("https://o.example/", api_key="k", http=lambda *a, **k: _fc({"success": False, "error": "x"}, status))


def test_a_target_404_inside_a_200_envelope_is_charged_one_credit(monkeypatch) -> None:
    monkeypatch.setattr("apps.research.vendors.validate_public_url", lambda url: None)
    gone = {"success": True, "data": {"html": "", "markdown": "", "metadata": {"sourceURL": "https://o.example/", "url": "https://o.example/", "statusCode": 404}}}
    with pytest.raises(ChargedFailure) as info:
        firecrawl_scrape("https://o.example/", api_key="k", http=lambda *a, **k: _fc(gone))
    assert info.value.credits == 1
```

- [ ] **Step 2: Run** — FAIL on import.

- [ ] **Step 3: Implement**

```python
import json

FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"
#: Tariff, because the response carries no credit count (API reference, 2026-09-19).
_FIRECRAWL_SCRAPE_CREDITS = 1
_FIRECRAWL_JSON_CREDITS = 4


def firecrawl_scrape(
    url: str,
    *,
    api_key: str,
    http=urllib3.request,
    change_tracking: bool = True,
    json_format: dict | None = None,
    timeout: float = 120,
) -> VendorFetch:
    """One Firecrawl /v2/scrape. HTML body so the local extractor runs unchanged;
    markdown kept for the reader that wants it; changeTracking is free."""
    formats: list[object] = ["html", "markdown"]
    if change_tracking:
        formats.append({"type": "changeTracking", "modes": ["git-diff"]})
    if json_format:
        formats.append({"type": "json", **json_format})
    payload = {
        "url": url,
        "formats": formats,
        "proxy": "auto",
        "parsers": [{"type": "pdf"}],
        "onlyMainContent": True,
        "blockAds": True,
        "removeBase64Images": True,
        "timeout": int(timeout * 1000),
    }
    response = http(
        "POST", FIRECRAWL_SCRAPE_URL, body=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=timeout + 10, retries=False,
    )
    if response.status != 200:
        raise VendorUnavailable(f"firecrawl answered HTTP {response.status}")
    envelope = json.loads(response.data)
    data = envelope.get("data") or {}
    metadata = data.get("metadata") or {}
    credits = _FIRECRAWL_SCRAPE_CREDITS + (_FIRECRAWL_JSON_CREDITS if json_format else 0)
    status = metadata.get("statusCode")
    if not envelope.get("success") or (isinstance(status, int) and status >= 400):
        raise ChargedFailure(f"source returned HTTP {status}", credits=credits)
    final_url = _provenance_url(str(metadata.get("url") or metadata.get("sourceURL") or url))
    html = data.get("html")
    if html:
        body, content_type = html.encode(), "text/html"
    else:  # a PDF or office file their parser turned into text
        body, content_type = (data.get("markdown") or "").encode(), "text/plain"
    tracking = data.get("changeTracking") or {}
    return VendorFetch(
        result=FetchResult(final_url, (), content_type, body, fetched_via="FIRECRAWL"),
        vendor="FIRECRAWL",
        credits=credits,
        change_status=tracking.get("changeStatus"),
        markdown=data.get("markdown"),
    )
```

- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "research: the Firecrawl client, html body, free changeTracking, tariff credits"`

---

### Task 5: Per-host cost table

**Files:**
- Modify: `apps/research/models.py`
- Create: `apps/research/migrations/000N_hostfetchcost.py` (Django writes it)
- Modify: `apps/research/vendors.py` (`record_host_cost`)
- Test: `tests/research/test_vendors.py`

**Interfaces:**
- Produces: `HostFetchCost(host, vendor, fetches, credits_total, credits_last, credits_max, remaining_credits, updated_at)` unique on `(host, vendor)`; `record_host_cost(fetch: VendorFetch | ChargedFailure, *, host: str) -> HostFetchCost`.

- [ ] **Step 1: Failing test**

```python
import pytest

from apps.research.models import HostFetchCost
from apps.research.vendors import record_host_cost


@pytest.mark.django_db
def test_host_cost_keeps_last_max_and_total_per_vendor() -> None:
    ok = VendorFetch(result=FetchResult("https://x.example/", (), "text/html", b"", fetched_via="SCRAPE_DO"),
                     vendor="SCRAPE_DO", credits=1, remaining_credits=999)
    surprise = VendorFetch(result=ok.result, vendor="SCRAPE_DO", credits=200, remaining_credits=799)

    record_host_cost(ok, host="x.example")
    row = record_host_cost(surprise, host="x.example")

    assert (row.fetches, row.credits_total, row.credits_last, row.credits_max, row.remaining_credits) == (2, 201, 200, 200, 799)


@pytest.mark.django_db
def test_a_charged_failure_is_recorded_too() -> None:
    row = record_host_cost(ChargedFailure("source returned HTTP 404", credits=1), host="gone.example", vendor="SCRAPE_DO")
    assert (row.fetches, row.credits_total) == (1, 1)
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement**

`models.py`:
```python
class HostFetchCost(models.Model):
    """What a vendor charged us per host. scrape.do applies per-domain multipliers
    (10-200 credits) server-side with no request-time signal; the response header
    is the only authority, so it is recorded here and read before a sweep."""

    host = models.CharField(max_length=253)
    vendor = models.CharField(max_length=20)
    fetches = models.PositiveIntegerField(default=0)
    credits_total = models.PositiveIntegerField(default=0)
    credits_last = models.PositiveIntegerField(default=0)
    credits_max = models.PositiveIntegerField(default=0)
    remaining_credits = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("host", "vendor"), name="host_fetch_cost_uniq")]
```

`vendors.py`:
```python
from django.db import transaction
from django.db.models import F

from .models import HostFetchCost


def record_host_cost(fetch: VendorFetch | ChargedFailure, *, host: str, vendor: str | None = None) -> HostFetchCost:
    name = vendor or getattr(fetch, "vendor", None)
    if name is None:
        raise ValueError("a charged failure needs its vendor named")
    credits = fetch.credits
    remaining = getattr(fetch, "remaining_credits", None)
    with transaction.atomic():
        row, _ = HostFetchCost.objects.get_or_create(host=host, vendor=name)
        row.fetches = F("fetches") + 1
        row.credits_total = F("credits_total") + credits
        row.credits_last = credits
        row.credits_max = max(row.credits_max, credits)
        if remaining is not None:
            row.remaining_credits = remaining
        row.save()
        row.refresh_from_db()
    return row
```

Then `POSTGRES_DB=tehsil_fetch_path uv run python manage.py makemigrations research -n hostfetchcost`. **Check RLS:** `HostFetchCost` is not tenant data (a host's price), like `DomainLease`; confirm `tests/tenancy/test_database_isolation.py::_SHARED_TABLES` lists `research_domainlease` and add `research_hostfetchcost` beside it if that list is asserted.

- [ ] **Step 4: Run** `tests/research/test_vendors.py tests/tenancy/test_database_isolation.py` — PASS.
- [ ] **Step 5: Commit** `git commit -m "research: the price each vendor charged, per host"`

---

### Task 6: Settings and the ladder

**Files:**
- Modify: `config/settings/base.py:116`
- Modify: `apps/research/vendors.py` (`never_vendored`, `LADDERS`, `fetch_via_vendors`)
- Test: `tests/research/test_vendors.py`

**Interfaces:**
- Produces: settings `FIRECRAWL_API_KEY`, `SCRAPE_DO_API_KEY`, `FETCH_VENDOR_MODE` (`"quota"` default), `FETCH_SWEEP_CREDITS` (`{"SCRAPE_DO": 500, "FIRECRAWL": 100}`); `never_vendored(url) -> None` raising `UnsafeTarget` for `europa.eu`; `fetch_via_vendors(url, *, mode=None, budget=None, firecrawl=firecrawl_scrape, scrape_do=scrape_do_fetch, record=record_host_cost) -> FetchResult`.

- [ ] **Step 1: Failing tests**

```python
from apps.research.vendors import LADDERS, fetch_via_vendors, never_vendored


def test_europa_eu_never_reaches_a_vendor() -> None:
    """Student PII travels that path on our pinned-address client (europass.py)."""
    for url in ("https://europa.eu/x", "https://europass.europa.eu/api/y"):
        with pytest.raises(UnsafeTarget):
            never_vendored(url)
    never_vendored("https://europa.example/")  # a lookalike is not the guarded host


def test_quota_mode_spends_scrape_do_first_and_firecrawl_last() -> None:
    assert [(v, r, s) for v, r, s in LADDERS["quota"]] == [
        ("SCRAPE_DO", False, False), ("SCRAPE_DO", True, True), ("FIRECRAWL", False, False)]
    assert [(v, r, s) for v, r, s in LADDERS["paid"]] == [
        ("FIRECRAWL", False, False), ("SCRAPE_DO", True, True)]


def _ok(vendor: str, credits: int = 1) -> VendorFetch:
    return VendorFetch(result=FetchResult("https://o.example/", (), "text/html", b"<p>x</p>", fetched_via=vendor),
                       vendor=vendor, credits=credits)


def test_the_ladder_stops_at_the_first_rung_that_reads(settings) -> None:
    settings.SCRAPE_DO_API_KEY, settings.FIRECRAWL_API_KEY = "s", "f"
    calls: list[tuple] = []
    recorded: list = []

    def scrape_do(url, *, api_key, render=False, residential=False, **_):
        calls.append(("SCRAPE_DO", render, residential))
        if not render:
            raise SourceBlocked("source returned HTTP 403")
        return _ok("SCRAPE_DO", 25)

    result = fetch_via_vendors("https://o.example/", mode="quota", scrape_do=scrape_do,
                               firecrawl=lambda *a, **k: calls.append(("FIRECRAWL",)),
                               record=lambda f, *, host, vendor=None: recorded.append((host, f.credits)))

    assert calls == [("SCRAPE_DO", False, False), ("SCRAPE_DO", True, True)]
    assert result.fetched_via == "SCRAPE_DO" and recorded == [("o.example", 25)]


def test_a_missing_key_skips_the_rung_loudly_and_all_failures_name_their_class(settings, caplog) -> None:
    settings.SCRAPE_DO_API_KEY, settings.FIRECRAWL_API_KEY = "", "f"

    def firecrawl(url, *, api_key, **_):
        raise VendorUnavailable("firecrawl answered HTTP 502")

    with pytest.raises(SourceBlocked) as info:
        fetch_via_vendors("https://o.example/", mode="quota", firecrawl=firecrawl, record=lambda *a, **k: None)

    assert "SCRAPE_DO: no key" in caplog.text
    assert str(info.value) == "all vendor tiers failed: SCRAPE_DO skipped (no key); FIRECRAWL VendorUnavailable"


def test_the_budget_stops_the_sweep_after_a_surprise(settings) -> None:
    settings.SCRAPE_DO_API_KEY = "s"
    budget = SweepBudget(credits={"SCRAPE_DO": 100, "FIRECRAWL": 0})
    scrape_do = lambda url, *, api_key, **_: _ok("SCRAPE_DO", 200)  # noqa: E731

    with pytest.raises(FetchBudgetExhausted):
        fetch_via_vendors("https://o.example/", mode="quota", budget=budget, scrape_do=scrape_do, record=lambda *a, **k: None)


def test_a_charged_failure_is_recorded_and_budgeted_then_the_ladder_continues(settings) -> None:
    settings.SCRAPE_DO_API_KEY, settings.FIRECRAWL_API_KEY = "s", "f"
    budget = SweepBudget(credits={"SCRAPE_DO": 100, "FIRECRAWL": 10})
    recorded: list = []

    def scrape_do(url, *, api_key, render=False, residential=False, **_):
        raise ChargedFailure("source returned HTTP 404", credits=1)

    result = fetch_via_vendors("https://o.example/", mode="quota", budget=budget, scrape_do=scrape_do,
                               firecrawl=lambda *a, **k: _ok("FIRECRAWL"),
                               record=lambda f, *, host, vendor=None: recorded.append((vendor or f.vendor, f.credits)))

    assert result.fetched_via == "FIRECRAWL"
    assert recorded == [("SCRAPE_DO", 1), ("SCRAPE_DO", 1), ("FIRECRAWL", 1)]
    assert budget.spent == {"SCRAPE_DO": 2, "FIRECRAWL": 1}
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement**

`config/settings/base.py`, after `SEARCH_API_KEY`:
```python
#: The vendor fetch path (funder spec §4.1b/§4.1c). "quota" while both accounts are
#: on free credits; flip to "paid" the day a Firecrawl plan is bought.
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
SCRAPE_DO_API_KEY = os.getenv("SCRAPE_DO_API_KEY", "")
FETCH_VENDOR_MODE = os.getenv("FETCH_VENDOR_MODE", "quota")
#: Per-sweep credit caps per vendor. Half of scrape.do's free 1,000; a tenth of Firecrawl's.
FETCH_SWEEP_CREDITS = {
    "SCRAPE_DO": int(os.getenv("FETCH_SWEEP_CREDITS_SCRAPE_DO", "500")),
    "FIRECRAWL": int(os.getenv("FETCH_SWEEP_CREDITS_FIRECRAWL", "100")),
}
```

`vendors.py`:
```python
from collections.abc import Callable
from urllib.parse import urlsplit

from django.conf import settings

#: (vendor, render, residential). Quota: scrape.do's credits are the ones nothing else
#: competes for, so ordinary pages spend them; Firecrawl is the last rung because a hard
#: failure there costs 0 and it still recovered 6 of 9 refused hosts on 2026-09-19.
#: Paid: Firecrawl first (free changeTracking pays for 420 fetches), then straight to
#: scrape.do's residential browser -- its cheap tiers recovered 0 of 3 such hosts.
LADDERS: dict[str, tuple[tuple[str, bool, bool], ...]] = {
    "quota": (("SCRAPE_DO", False, False), ("SCRAPE_DO", True, True), ("FIRECRAWL", False, False)),
    "paid": (("FIRECRAWL", False, False), ("SCRAPE_DO", True, True)),
}
_KEY_SETTING = {"SCRAPE_DO": "SCRAPE_DO_API_KEY", "FIRECRAWL": "FIRECRAWL_API_KEY"}


def never_vendored(url: str) -> None:
    host = (urlsplit(url).hostname or "").casefold()
    if host == "europa.eu" or host.endswith(".europa.eu"):
        raise UnsafeTarget(f"{host} is fetched only by our own pinned-address client")


def fetch_via_vendors(
    url: str,
    *,
    mode: str | None = None,
    budget: SweepBudget | None = None,
    firecrawl: Callable[..., VendorFetch] = firecrawl_scrape,
    scrape_do: Callable[..., VendorFetch] = scrape_do_fetch,
    record: Callable[..., object] = record_host_cost,
) -> FetchResult:
    """Walk the configured ladder; return the first body that reads.

    Every rung's outcome is recorded (cost per host) and budgeted, including a
    charged failure. Raises SourceBlocked naming each rung's error class when
    none reads -- that is the pipeline's UNREACHABLE.
    """
    never_vendored(url)
    host = urlsplit(url).hostname or ""
    ladder = LADDERS[mode or settings.FETCH_VENDOR_MODE]
    reasons: list[str] = []
    for vendor, render, residential in ladder:
        api_key = getattr(settings, _KEY_SETTING[vendor], "")
        if not api_key:
            logger.warning("%s: no key, rung skipped for %s", vendor, host)
            reasons.append(f"{vendor} skipped (no key)")
            continue
        try:
            if vendor == "SCRAPE_DO":
                fetched = scrape_do(url, api_key=api_key, render=render, residential=residential)
            else:
                fetched = firecrawl(url, api_key=api_key)
        except ChargedFailure as error:
            record(error, host=host, vendor=vendor)
            if budget is not None:
                budget.spend(vendor, error.credits)
            reasons.append(f"{vendor} {type(error).__name__}")
            continue
        except SourceBlocked as error:  # VendorUnavailable and plain refusals: free
            reasons.append(f"{vendor} {type(error).__name__}")
            continue
        record(fetched, host=host)
        if budget is not None:
            budget.spend(vendor, fetched.credits)
        return fetched.result
    raise SourceBlocked("all vendor tiers failed: " + "; ".join(reasons))
```

- [ ] **Step 4: Run** the whole test file — PASS. `uv run ruff check apps/research/vendors.py` and `uv run mypy apps/research/vendors.py` clean.
- [ ] **Step 5: Commit** `git commit -m "research: the vendor ladder -- quota or paid order, every rung recorded and budgeted"`

---

### Task 7: The seam — `retrieve_official_source` hands refused pages to the vendors

**Files:**
- Modify: `apps/research/discovery.py:250-264`
- Modify: `tests/research/test_discovery.py:95-143`

**Interfaces:**
- Produces: `retrieve_official_source(url, *, plain_fetch=fetch_official_source, vendors=fetch_via_vendors) -> FetchResult`. The `browser_render` parameter is removed; `render_via_browser_service` stays defined (its own tests still pass) until the deletion plan.

- [ ] **Step 1: Rewrite the three tests**

```python
from apps.research.vendors import fetch_via_vendors  # noqa: F401  (documents the default)


def test_vendors_run_only_after_our_client_is_refused_or_reports_javascript() -> None:
    for failure in (BrowserRequired("javascript-dependent source"), SourceBlocked("source returned HTTP 403")):
        calls: list[str] = []

        def plain_fetch(_url: str, **_kwargs: object) -> FetchResult:
            calls.append("plain")
            raise failure

        def vendors(url: str) -> FetchResult:
            calls.append("vendors")
            assert url == "https://official.example/program"
            return FetchResult(url, (), "text/html", b"vendored", fetched_via="SCRAPE_DO")

        result = retrieve_official_source("https://official.example/program", plain_fetch=plain_fetch, vendors=vendors)

        assert calls == ["plain", "vendors"] and result.fetched_via == "SCRAPE_DO"


def test_a_shell_page_from_our_client_goes_to_the_vendors() -> None:
    shell = FetchResult("https://official.example/program", (), "text/html", b"<div id=app></div>", browser_required=True)
    result = retrieve_official_source("https://official.example/program",
                                      plain_fetch=lambda url, **_: shell,
                                      vendors=lambda url: FetchResult(url, (), "text/html", b"<p>rendered</p>", fetched_via="FIRECRAWL"))
    assert result.body == b"<p>rendered</p>"


def test_vendors_do_not_run_for_a_plain_fetch_success() -> None:
    result = retrieve_official_source("https://official.example/program",
                                      plain_fetch=lambda url, **_kwargs: FetchResult(url, (), "text/html", b"plain"),
                                      vendors=lambda _url: (_ for _ in ()).throw(AssertionError("vendors should not run")))
    assert result.body == b"plain" and result.fetched_via == "EGRESS"


def test_retrieval_requires_https() -> None:
    with pytest.raises(ValueError):
        retrieve_official_source("http://official.example/program",
                                 plain_fetch=lambda url, **_kwargs: (_ for _ in ()).throw(BrowserRequired("js")),
                                 vendors=lambda _url: FetchResult("", (), "text/html", b""))
```

- [ ] **Step 2: Run** — FAIL (`unexpected keyword argument 'vendors'`).

- [ ] **Step 3: Implement**

```python
def retrieve_official_source(
    url: str,
    *,
    plain_fetch: Callable[..., FetchResult] = fetch_official_source,
    vendors: Callable[[str], FetchResult] | None = None,
) -> FetchResult:
    """Our own client first (free, 49 of 58 hosts), then the vendor ladder.

    A refusal (SourceBlocked) and a JavaScript shell both go to the vendors; what
    the vendors cannot read raises SourceBlocked naming every rung, which the
    pipeline records as UNREACHABLE. The browser tier is retired for this path
    (funder spec §4, increment 3).
    """
    canonical_url = canonicalize_url(url)
    try:
        result = plain_fetch(canonical_url, require_https=True)
    except (BrowserRequired, SourceBlocked):
        result = None
    if result is not None and not result.browser_required:
        return result
    if vendors is None:
        from .vendors import fetch_via_vendors  # Django settings and a model; imported late

        vendors = fetch_via_vendors
    return vendors(canonical_url)
```

Check `grep -rn "browser_render=" apps/ tests/` and update any other caller (`discover.py` management command passes `render_via_browser_service` into `run(...)`, not into this function — read it and leave it if so).

- [ ] **Step 4: Run** `tests/research/test_discovery.py tests/research/test_reader.py tests/documents/test_program_rules.py` — PASS.
- [ ] **Step 5: Commit** `git commit -m "research: a refused or JavaScript page goes to the vendor ladder, not the browser tier"`

---

### Task 8: The gate tool — `manage.py fetch_ladder`

**Files:**
- Create: `apps/research/management/commands/fetch_ladder.py`
- Test: `tests/research/test_fetch_ladder.py`

**Interfaces:**
- Consumes: `retrieve_official_source`, `SweepBudget`, `HostFetchCost`, `settings.FETCH_SWEEP_CREDITS`.
- Produces: `manage.py fetch_ladder URL [URL ...] [--mode quota|paid] [--urls-file PATH]` printing one line per host: `host  tier  bytes  credits` and a footer with per-vendor credits and dollars.

- [ ] **Step 1: Failing test**

```python
from io import StringIO

import pytest
from django.core.management import call_command

from apps.research.egress import FetchResult, SourceBlocked


@pytest.mark.django_db
def test_fetch_ladder_prints_tier_and_cost_per_host(monkeypatch) -> None:
    def retrieve(url, *, vendors):
        if "dead" in url:
            raise SourceBlocked("all vendor tiers failed: SCRAPE_DO SourceBlocked; FIRECRAWL VendorUnavailable")
        return FetchResult(url, (), "text/html", b"<p>ok</p>", fetched_via="SCRAPE_DO")

    monkeypatch.setattr("apps.research.management.commands.fetch_ladder.retrieve_official_source", retrieve)
    out = StringIO()

    call_command("fetch_ladder", "https://a.example/", "https://dead.example/", mode="quota", stdout=out)

    text = out.getvalue()
    assert "a.example" in text and "SCRAPE_DO" in text
    assert "dead.example" in text and "UNREACHABLE" in text
    assert "USD" in text
```

- [ ] **Step 2: Run** — FAIL (unknown command).

- [ ] **Step 3: Implement**

```python
"""Run the fetch ladder over URLs and print what each host cost -- the §4.5 gate.

Read-only against the catalog: nothing is persisted except HostFetchCost rows,
which is the point. Use it before a corridor sweep to see the residue and after
one to see the bill.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.research.discovery import retrieve_official_source
from apps.research.egress import SourceBlocked
from apps.research.vendors import FetchBudgetExhausted, SweepBudget, fetch_via_vendors


class Command(BaseCommand):
    help = "Fetch each URL through the ladder; print tier, bytes and credits per host."

    def add_arguments(self, parser) -> None:
        parser.add_argument("urls", nargs="*")
        parser.add_argument("--urls-file", type=Path)
        parser.add_argument("--mode", choices=("quota", "paid"), default=None)

    def handle(self, *args, **options) -> None:
        urls = list(options["urls"])
        if options["urls_file"]:
            urls += [line.strip() for line in options["urls_file"].read_text().splitlines() if line.strip()]
        mode = options["mode"] or settings.FETCH_VENDOR_MODE
        budget = SweepBudget(credits=settings.FETCH_SWEEP_CREDITS)
        self.stdout.write(f"mode={mode}  caps={budget.caps}")
        for url in urls:
            host = urlsplit(url).hostname or url
            try:
                result = retrieve_official_source(
                    url, vendors=lambda u: fetch_via_vendors(u, mode=mode, budget=budget)
                )
            except FetchBudgetExhausted as error:
                self.stdout.write(f"{host}  BUDGET  {error}")
                break
            except SourceBlocked as error:
                self.stdout.write(f"{host}  UNREACHABLE  {error}")
                continue
            self.stdout.write(f"{host}  {result.fetched_via}  {len(result.body)} bytes")
        self.stdout.write(f"credits spent {budget.spent}  USD {budget.usd():.4f}")
```

- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "research: fetch_ladder -- the ladder over a list of hosts, with the bill"`

---

### Task 9: Validation, docs, the live gate

**Files:**
- Modify: `CLAUDE.md` (Web-fetching banner: one paragraph on quota/paid mode and `fetch_ladder`)
- Modify: `.env.example` if one exists (`grep -l FIRECRAWL .env.example`): add the four names with empty values.

- [ ] **Step 1: Full validation**

```bash
cd .worktrees/fetch-path
POSTGRES_DB=tehsil_fetch_path uv run pytest -q
uv run ruff check apps tests config
uv run mypy apps config
uv run python manage.py makemigrations --check
uv run bandit -c pyproject.toml -r apps config -q
```
All clean, or fix.

- [ ] **Step 2: Live gate (only if the keys are exported in this shell — never read the env files)**

```bash
POSTGRES_DB=tehsil_fetch_path uv run python manage.py fetch_ladder --mode quota \
  https://globed.eu/how-to-apply/ https://www.daad.de/en/ https://mischolarship.com/
```
Expected: globed via `EGRESS` (tier zero), DAAD via `SCRAPE_DO` at 1 credit, mischolarship via `SCRAPE_DO` at 25 credits or `UNREACHABLE`; footer under 30 credits. Record the printed lines in the commit message. If the keys are not in the shell, say so in the report and leave the gate unrun.

- [ ] **Step 3: CLAUDE.md paragraph**, in the Web-fetching banner after the sentence ending "own egress only for `europa.eu`":

> Built 2026-09-19 (`apps/research/vendors.py`): the ladder runs in two orders chosen by `FETCH_VENDOR_MODE`. **`quota`** (default, both accounts on free credits): our client → scrape.do datacenter → scrape.do residential+browser → Firecrawl. **`paid`** (the day a Firecrawl plan is bought): our client → Firecrawl (`proxy: "auto"`, free `changeTracking`) → scrape.do residential+browser. Dollars decide, not credits: scrape.do is 7x cheaper per credit, so its 25-credit tier is $0.0029. Every rung's cost is recorded per host in `HostFetchCost` from `Scrape.do-Request-Cost` (per-domain multipliers up to 200 credits, no request-time signal) and a `SweepBudget` stops a sweep at its cap. `manage.py fetch_ladder` runs the ladder over hosts and prints the bill. `europa.eu` never reaches a vendor (`never_vendored`, tested).

- [ ] **Step 4: Commit** `git commit -m "docs: the fetch ladder's two modes and the bill"`

---

## Self-Review

**Spec coverage.** §4.1 scrape (T4), changeTracking (T4, status surfaced, not yet acted on — the reader's `content_digest` remains the change check; wiring `change_status == "same"` to skip the reader is the reader plan's job), scrape.do tier and header authority (T3, T5), §4.1b rules 1–3 (T6 ladder order, T5 cost record, T1 budget), §4.1c quota/paid flip (T6 settings), §4.2 UNREACHABLE = all tiers failed (T6 reason string, T7 propagation), §4.3 `fetched_via` label and final-URL validation (T2, T3, T4), europa.eu exclusion (T6), §4.5 gate tool (T8, T9). **Not in this plan, on purpose:** `/crawl`, `/map`, `/extract` (they replace the link walker and are the caller's plan), the §4.4 JSON-read measurement (needs the reader plan's harness; `firecrawl_scrape(json_format=...)` is ready for it), Tavily Extract removal, the browser-tier deletion.

**Type consistency.** `VendorFetch.credits: int`, `ChargedFailure.credits: int`; `record(fetch, *, host, vendor=None)` everywhere; `fetch_via_vendors` returns `FetchResult`; `retrieve_official_source(url, *, plain_fetch, vendors)`.

**Placeholder scan.** None. Migration numbers are `ls`-determined at execution, stated as such.

## Execution Handoff

Inline execution in this session (owner asked for the build; autonomy applies).
