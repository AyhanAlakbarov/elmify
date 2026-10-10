# Transcript Reader on Azure — Plan 1 of 4: the Reader Swap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PaddleOCR with Azure Document Intelligence (Layout) for scanned pages and photos, read born-digital PDF pages from their own text layer, keep all file parsing in the secretless Lambda, and flag low-confidence credit and grade cells — while everything downstream (Jev questions, checks, storage, the summary screen) keeps working unchanged.

**Architecture:** The OCR Lambda (`ocr/read_pages.py`) becomes a small *inventory* parser: it counts PDF pages, measures each scanned page's resolution, and reads text-layer pages with `pdfplumber`. It never runs a model. The document worker (`apps/documents/ocr.py::read_pages`) invokes it exactly as today, then sends the original bytes of every page that needs reading to Azure (`apps/documents/azure_layout.py`), runs the quality gate on Azure's own output, and returns the same `OcrPage` shape the reader already consumes — now carrying a confidence per table cell. `transcript.py` carries those confidences through its row cutting and adds a `low_confidence` highlight for a course row whose credit or grade cell Azure was unsure of.

**Tech Stack:** Django 5.2 / Python 3.14 app; the parser on Python 3.12 (`ocr/`, its own `uv.lock`) with `pypdfium2` (already a dependency), `pdfplumber`, `pillow`; Azure Document Intelligence REST `prebuilt-layout`, API version `2024-11-30`, called through `apps/research/egress.py`; AWS Lambda container image; CloudFormation (`infra/template.yaml`).

**Spec:** `docs/superpowers/specs/2026-10-03-transcript-reader-redesign-design.md` — this plan covers §4 (the reader, launch gate, version pin, outage rule), §4.1 (isolation), §5 (the quality gate's reasons that do not need pages-as-slots), §6.3's low-confidence flag, and §10's `ocr/` and `ocr.py` lines.

**Not in this plan** (later plans, same spec): plan 2 — a transcript as a set of pages (storage reshape, per-page retakes, translation-page selection, the 50-page paid-cycle allowance, payment first, HEIC, re-uploads); plan 3 — the point–letter check, page completeness, the confirm screen's data and student-entered values; plan 4 — the audit. This plan keeps `TranscriptReading` one-to-one with one upload, exactly as on master.

## Global Constraints

- Work in `/home/orkhan/Desktop/transcript-redesign` (branch `claude/transcript-reader-redesign`). The shell's cwd resets between calls: prefix commands with `cd /home/orkhan/Desktop/transcript-redesign &&` and use `git -C /home/orkhan/Desktop/transcript-redesign` for git.
- Test database: `POSTGRES_DB=tehsil_transcript` on every app pytest run.
- Never run `ruff format` (lint-only gate). Gates after every task: `uv run ruff check .`, `uv run mypy apps config`, `POSTGRES_DB=tehsil_transcript uv run pytest -q`, `uv run python manage.py makemigrations --check --dry-run`; when `ocr/` changed: `uv sync --project ocr --frozen && uv run --project ocr pytest ocr -q`; when `infra/` changed: `uv run pytest tests/infra -q`.
- **No generative model writes a stored value**: Azure is an OCR service; its text is copied, never rewritten. Jev still only picks.
- **The worker never parses an uploaded file**: it reads bytes from the evidence bucket and forwards them to Azure; counting pages, measuring resolution and reading text layers happen in the Lambda only (spec §4.1).
- **Launch gate**: `settings.TRANSCRIPT_AZURE_ENABLED` (default `False`) — no transcript bytes reach Azure while it is off (spec §4).
- **The Azure API version is pinned** in `settings.AZURE_DI_API_VERSION = "2024-11-30"` and recorded on every page the reader returns (spec §4).
- **No silent fallback reader**: Azure unavailable raises `OcrUnavailable` (retried by the worker's existing redelivery, dead-lettered to `READ_FAILED`) — never a different engine.
- Keys only from the environment; `AZURE_DI_KEY` never appears in a log line, an exception message or a test fixture value.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A PDF mixing text-layer pages and scanned pages** — the text pages must be read from the layer and only the scanned ones billed to Azure (Task 4 test `test_mixed_pdf_sends_only_scanned_pages_to_azure`).
2. **A text layer that looks fine but is garbage** — pdfminer's `(cid:NN)` glyph codes or U+FFFD replacement characters must route the page to Azure, never into the reading (Task 3 test `test_cid_codes_fail_the_text_layer_check`).
3. **Azure returning `failed`, timing out, or answering 429** — must surface as `OcrUnavailable`, never as an empty transcript (Task 2 tests).
4. **A blank credit cell with no confidence** — must not be flagged as low confidence and must not crash the min() (Task 5 test `test_blank_cells_carry_no_confidence_and_raise_no_flag`).
5. **A row dropped by personal-data minimisation** — the confidence grid must stay aligned with the kept rows, or a flag lands on the wrong course (Task 5 test `test_confidences_stay_aligned_when_a_row_is_dropped`).

---

### Task 1: An egress call that starts an asynchronous operation

Azure's analyze call answers `202 Accepted` with an empty body and an `Operation-Location` header; `fetch_json_api` requires a JSON body and returns no headers. Add one sibling under the same egress rules.

**Files:**
- Modify: `apps/research/egress.py` (after `fetch_json_api`, ~line 580)
- Test: `tests/research/test_egress_operation.py`

**Interfaces:**
- Produces: `start_json_operation(url: str, *, payload: Mapping[str, object], headers: Mapping[str, str], transport: Callable[..., Response] = _request) -> str` — POSTs JSON, requires status 202, returns the `Operation-Location` header after `validate_public_url` accepts it as `https` on the **same host** as `url`; raises `SourceBlocked` otherwise.

- [ ] **Step 1: Write the failing tests**

```python
"""start_json_operation: the one egress call that answers 202 and a polling URL."""

import pytest

from apps.research import egress
from apps.research.egress import SourceBlocked, start_json_operation


class _Resp:
    def __init__(self, status, headers):
        self.status, self.headers = status, headers

    def read(self, amount, decode_content=True):
        return b""

    def release_conn(self):
        pass


def _transport(status, headers, seen):
    def send(target, path, *, method, body, extra_headers, **kwargs):
        seen.append((target.host, path, method, body, extra_headers))
        return _Resp(status, headers)

    return send


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(egress.socket, "getaddrinfo", lambda host, port: [(0, 0, 0, "", ("20.50.1.1", port))])


def test_returns_the_operation_location_on_202():
    seen = []
    location = start_json_operation(
        "https://tehsil.cognitiveservices.azure.com/x:analyze?api-version=2024-11-30",
        payload={"base64Source": "QUJD"},
        headers={"Ocp-Apim-Subscription-Key": "k"},
        transport=_transport(202, {"Operation-Location": "https://tehsil.cognitiveservices.azure.com/op/1"}, seen),
    )
    assert location == "https://tehsil.cognitiveservices.azure.com/op/1"
    assert seen[0][2] == "POST" and seen[0][4]["Content-Type"] == "application/json"


def test_any_other_status_is_blocked():
    with pytest.raises(SourceBlocked, match="HTTP 400"):
        start_json_operation(
            "https://tehsil.cognitiveservices.azure.com/x", payload={}, headers={},
            transport=_transport(400, {}, []),
        )


def test_a_location_on_another_host_is_refused():
    with pytest.raises(SourceBlocked, match="another host"):
        start_json_operation(
            "https://tehsil.cognitiveservices.azure.com/x", payload={}, headers={},
            transport=_transport(202, {"Operation-Location": "https://evil.example/op"}, []),
        )


def test_a_missing_location_is_refused():
    with pytest.raises(SourceBlocked, match="no Operation-Location"):
        start_json_operation(
            "https://tehsil.cognitiveservices.azure.com/x", payload={}, headers={},
            transport=_transport(202, {}, []),
        )
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/research/test_egress_operation.py -q`
Expected: FAIL — `ImportError: cannot import name 'start_json_operation'`

- [ ] **Step 3: Implement**

Add to `apps/research/egress.py`, after `fetch_json_api`:

```python
def start_json_operation(
    url: str,
    *,
    payload: Mapping[str, object],
    headers: Mapping[str, str],
    transport: Callable[..., Response] = _request,
) -> str:
    """POST a JSON body to an API that answers 202 and a URL to poll (Azure's analyze call).

    Same rules as fetch_json_api -- HTTPS only, the private-network block, Host pinned, no
    redirect -- and one more: the polling URL must stay on the host that was called, so a
    tampered response cannot point the next request (which carries the same key) elsewhere.
    """
    target = validate_public_url(url)
    if target.scheme != "https":
        raise UnsafeTarget(url)
    parsed = urlsplit(url)
    sent: dict[str, str] = {
        **{k: v for k, v in dict(headers).items() if k.casefold() != "host"},
        "Host": target.host,
        "Content-Type": "application/json",
    }
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    body = json.dumps(payload, sort_keys=True).encode()
    try:
        response = transport(target, path, method="POST", body=body, extra_headers=sent)
    except urllib3.exceptions.HTTPError as error:
        raise SourceBlocked(f"{type(error).__name__}: {error}") from error
    try:
        if response.status != 202:
            raise SourceBlocked(f"api returned HTTP {response.status}")
        location = _header(response.headers, "Operation-Location")
        if not location:
            raise SourceBlocked("api answered 202 with no Operation-Location")
        polled = validate_public_url(location)
        if polled.scheme != "https" or polled.host != target.host:
            raise SourceBlocked("Operation-Location points at another host")
        return location
    finally:
        response.release_conn()
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/research/test_egress_operation.py tests/research -q -k egress`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/research/egress.py tests/research/test_egress_operation.py
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(egress): start an asynchronous API operation and return its polling URL

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The Azure Layout client

**Files:**
- Create: `apps/documents/ocr_errors.py` (moves `OcrUnavailable` and `PageRefused` out of `ocr.py`, so `ocr.py` and `azure_layout.py` can both import them without a cycle; `ocr.py` re-exports both, so every existing `from apps.documents.ocr import OcrUnavailable, PageRefused` keeps working)
- Create: `apps/documents/azure_layout.py`
- Modify: `apps/documents/ocr.py` (delete the two class bodies; add `from .ocr_errors import OcrUnavailable, PageRefused  # noqa: F401 - re-exported`)
- Modify: `config/settings/base.py` (beside `OCR_FUNCTION_NAME`, ~line 135)
- Test: `tests/documents/test_azure_layout.py`

**Interfaces:**
- Consumes: `start_json_operation` (Task 1), `egress.fetch_json_api(url, params={}, headers=...)` for polling.
- Produces:
  - Pydantic models (all `extra="ignore"`, because Azure's answer carries far more than we read): `AzureWord(content: str, polygon: tuple[float, ...], confidence: float)`, `AzureLine(content: str, polygon: tuple[float, ...])`, `AzureCell(rowIndex: int, columnIndex: int, content: str, spans: tuple[AzureSpan, ...])`, `AzureSpan(offset: int, length: int)`, `AzureTable(rowCount: int, columnCount: int, cells: tuple[AzureCell, ...], boundingRegions: tuple[AzureRegion, ...])`, `AzureRegion(pageNumber: int, polygon: tuple[float, ...])`, `AzurePage(pageNumber: int, width: float, height: float, unit: str, words: tuple[AzureWord, ...], lines: tuple[AzureLine, ...])` (each word also has `span: AzureSpan`), `AzureLayout(content: str, pages: tuple[AzurePage, ...], tables: tuple[AzureTable, ...])`.
  - `analyze_layout(content: bytes, *, pages: str | None = None, locale: str | None = None, start=start_json_operation, poll=fetch_json_api, sleep=time.sleep) -> AzureLayout` — raises `OcrUnavailable` (from `apps.documents.ocr_errors`) on any failure.
  - `AzureLine` also carries `spans: tuple[AzureSpan, ...] = ()` — Task 4 uses it to tell table text from free lines.
  - Settings: `AZURE_DI_ENDPOINT` (env, default `""`), `AZURE_DI_KEY` (env, default `""`), `AZURE_DI_API_VERSION = "2024-11-30"`, `TRANSCRIPT_AZURE_ENABLED` (env `"1"` → `True`, default `False`).

- [ ] **Step 1: Write the failing tests**

```python
"""The Azure Layout client: one analyze, polled to the end, every failure unavailable."""

import base64

import pytest
from django.conf import settings

from apps.documents import azure_layout
from apps.documents.azure_layout import AzureLayout, analyze_layout
from apps.documents.ocr_errors import OcrUnavailable
from apps.research.egress import SourceBlocked

_RESULT = {
    "status": "succeeded",
    "analyzeResult": {
        "content": "Physics 6 BA",
        "pages": [{
            "pageNumber": 1, "width": 1654, "height": 2339, "unit": "pixel",
            "words": [{"content": "Physics", "polygon": [1, 1, 9, 1, 9, 5, 1, 5], "confidence": 0.99,
                       "span": {"offset": 0, "length": 7}}],
            "lines": [{"content": "Physics 6 BA", "polygon": [1, 1, 30, 1, 30, 5, 1, 5]}],
        }],
        "tables": [{"rowCount": 1, "columnCount": 3, "boundingRegions": [{"pageNumber": 1, "polygon": [0] * 8}],
                    "cells": [{"rowIndex": 0, "columnIndex": 0, "content": "Physics", "spans": [{"offset": 0, "length": 7}]}]}],
    },
}


@pytest.fixture(autouse=True)
def _configured(settings):
    settings.AZURE_DI_ENDPOINT = "https://tehsil.cognitiveservices.azure.com"
    settings.AZURE_DI_KEY = "test-key"
    settings.AZURE_DI_API_VERSION = "2024-11-30"


def _start_ok(calls):
    def start(url, *, payload, headers):
        calls.append((url, payload, headers))
        return "https://tehsil.cognitiveservices.azure.com/op/1"
    return start


def test_sends_base64_with_the_pinned_version_and_returns_the_layout():
    calls, polls = [], iter([{"status": "running"}, _RESULT])
    layout = analyze_layout(b"%PDF-1.7 x", pages="2,3", locale="az", start=_start_ok(calls),
                            poll=lambda url, *, params, headers: next(polls), sleep=lambda s: None)
    url, payload, headers = calls[0]
    assert "prebuilt-layout:analyze" in url and "api-version=2024-11-30" in url
    assert "pages=2%2C3" in url or "pages=2,3" in url
    assert "locale=az" in url
    assert payload == {"base64Source": base64.b64encode(b"%PDF-1.7 x").decode()}
    assert headers == {"Ocp-Apim-Subscription-Key": "test-key"}
    assert isinstance(layout, AzureLayout) and layout.pages[0].words[0].confidence == 0.99


def test_a_failed_operation_is_unavailable():
    with pytest.raises(OcrUnavailable, match="failed"):
        analyze_layout(b"x", start=_start_ok([]), poll=lambda url, **k: {"status": "failed"},
                       sleep=lambda s: None)


def test_an_operation_that_never_finishes_is_unavailable():
    with pytest.raises(OcrUnavailable, match="timed out"):
        analyze_layout(b"x", start=_start_ok([]), poll=lambda url, **k: {"status": "running"},
                       sleep=lambda s: None)


def test_a_refused_start_is_unavailable_and_never_quotes_the_key():
    def start(url, *, payload, headers):
        raise SourceBlocked("api returned HTTP 429")
    with pytest.raises(OcrUnavailable) as caught:
        analyze_layout(b"x", start=start, poll=lambda url, **k: _RESULT, sleep=lambda s: None)
    assert "test-key" not in str(caught.value)


def test_no_endpoint_configured_is_unavailable(settings):
    settings.AZURE_DI_ENDPOINT = ""
    with pytest.raises(OcrUnavailable, match="not configured"):
        analyze_layout(b"x", start=_start_ok([]), poll=lambda url, **k: _RESULT, sleep=lambda s: None)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_azure_layout.py -q`
Expected: FAIL — `ModuleNotFoundError: apps.documents.azure_layout`

- [ ] **Step 3: Add the settings**

In `config/settings/base.py`, directly after the `OCR_*` block:

```python
#: Azure Document Intelligence, the transcript reader for scanned pages and photos (spec
#: 2026-10-03-transcript-reader-redesign §4). The key only from the environment; the endpoint is
#: the EU resource's https URL. The API version is pinned: a newer one is adopted only after the
#: eval harness is re-run on it, and every page read records it.
AZURE_DI_ENDPOINT = os.getenv("AZURE_DI_ENDPOINT", "")
AZURE_DI_KEY = os.getenv("AZURE_DI_KEY", "")
AZURE_DI_API_VERSION = "2024-11-30"
#: Launch gate (spec §4): no transcript reaches Azure until Microsoft's data-processing terms are
#: reviewed and this is set to 1. Checked in apps/documents/transcript.py before the upload is opened.
TRANSCRIPT_AZURE_ENABLED = os.getenv("TRANSCRIPT_AZURE_ENABLED", "") == "1"
```

- [ ] **Step 4: Move the two exceptions, then implement the client**

Create `apps/documents/ocr_errors.py` holding the `PageRefused` and `OcrUnavailable` classes exactly as they are in `apps/documents/ocr.py` today (docstrings included), delete them from `ocr.py`, and import them back there with `from .ocr_errors import OcrUnavailable, PageRefused  # noqa: F401 - re-exported`. Run `POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_ocr.py -q` — still green.

Create `apps/documents/azure_layout.py`:

```python
"""Azure Document Intelligence, prebuilt-layout: the reader for scanned pages and photos.

An OCR service, not a generative model: it returns the characters it recognised, each word with a
polygon and a confidence, and tables as cells (spec 2026-10-03-transcript-reader-redesign §4). It
is called through apps/research/egress.py like every contracted API, so the private-network block,
HTTPS-only and the size cap apply. One analyze per call, polled until it ends. Any failure is
OcrUnavailable -- never an empty layout, and never another reader in its place.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from urllib.parse import urlencode

from django.conf import settings
from pydantic import BaseModel, ConfigDict, ValidationError

from apps.research.egress import SourceBlocked, fetch_json_api, start_json_operation

from .ocr_errors import OcrUnavailable

#: ponytail: a three-page transcript measured 3-12 s; 60 polls of up to 2 s is two minutes before
#: the worker gives up and the message is redelivered. Raise with evidence of slower answers.
_MAX_POLLS = 60
_POLL_SECONDS = 2.0

_IGNORE = ConfigDict(extra="ignore", frozen=True)


class AzureSpan(BaseModel):
    model_config = _IGNORE
    offset: int
    length: int


class AzureWord(BaseModel):
    model_config = _IGNORE
    content: str
    polygon: tuple[float, ...]
    confidence: float
    span: AzureSpan


class AzureLine(BaseModel):
    model_config = _IGNORE
    content: str
    polygon: tuple[float, ...]
    spans: tuple[AzureSpan, ...] = ()


class AzurePage(BaseModel):
    model_config = _IGNORE
    pageNumber: int
    width: float
    height: float
    unit: str
    words: tuple[AzureWord, ...] = ()
    lines: tuple[AzureLine, ...] = ()


class AzureRegion(BaseModel):
    model_config = _IGNORE
    pageNumber: int
    polygon: tuple[float, ...]


class AzureCell(BaseModel):
    model_config = _IGNORE
    rowIndex: int
    columnIndex: int
    content: str = ""
    rowSpan: int = 1
    columnSpan: int = 1
    spans: tuple[AzureSpan, ...] = ()


class AzureTable(BaseModel):
    model_config = _IGNORE
    rowCount: int
    columnCount: int
    cells: tuple[AzureCell, ...]
    boundingRegions: tuple[AzureRegion, ...] = ()


class AzureLayout(BaseModel):
    model_config = _IGNORE
    content: str = ""
    pages: tuple[AzurePage, ...] = ()
    tables: tuple[AzureTable, ...] = ()


def analyze_layout(
    content: bytes,
    *,
    pages: str | None = None,
    locale: str | None = None,
    start: Callable[..., str] = start_json_operation,
    poll: Callable[..., dict[str, object]] = fetch_json_api,
    sleep: Callable[[float], None] = time.sleep,
) -> AzureLayout:
    """`pages` is Azure's own selector ("2,3"), so a PDF's text-layer pages are never billed."""
    if not settings.AZURE_DI_ENDPOINT or not settings.AZURE_DI_KEY:
        raise OcrUnavailable("Azure Document Intelligence is not configured")
    query = {"api-version": settings.AZURE_DI_API_VERSION}
    if pages:
        query["pages"] = pages
    if locale:
        query["locale"] = locale
    url = (
        f"{settings.AZURE_DI_ENDPOINT.rstrip('/')}/documentintelligence/documentModels/"
        f"prebuilt-layout:analyze?{urlencode(query)}"
    )
    headers = {"Ocp-Apim-Subscription-Key": settings.AZURE_DI_KEY}
    try:
        operation = start(
            url, payload={"base64Source": base64.b64encode(content).decode()}, headers=headers
        )
        for _ in range(_MAX_POLLS):
            sleep(_POLL_SECONDS)
            body = poll(operation, params={}, headers=headers)
            status = body.get("status")
            if status == "succeeded":
                return AzureLayout.model_validate(body.get("analyzeResult") or {})
            if status == "failed":
                raise OcrUnavailable("Azure analyze failed")
    except SourceBlocked as error:
        # The exception's own text only: it carries a status code, never the request headers.
        raise OcrUnavailable(f"Azure unreachable: {error}") from error
    except ValidationError as error:
        raise OcrUnavailable("Azure answered outside the layout schema") from error
    raise OcrUnavailable("Azure analyze timed out")
```

- [ ] **Step 5: Run to verify they pass, then lint and type-check**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_azure_layout.py -q && uv run ruff check apps/documents/azure_layout.py && uv run mypy apps/documents/azure_layout.py`
Expected: 5 passed; no lint or type errors. (If mypy rejects the `pydantic` field names in camelCase as style, they are Azure's wire names — keep them; ruff's `N815` may need a per-file `# noqa: N815` on those lines if the repo enables it.)

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/ocr_errors.py apps/documents/ocr.py apps/documents/azure_layout.py config/settings/base.py tests/documents/test_azure_layout.py
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): the Azure Layout client -- pinned version, polled, every failure unavailable

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The Lambda becomes an inventory parser

The program keeps its two entry points (Lambda handler, child process) and its gate on scanned-PDF resolution, and drops PaddleOCR. Its answer becomes an inventory: per page, either the text layer's lines and tables or a note that the page must be read from its image.

**Files:**
- Modify (rewrite): `ocr/read_pages.py`
- Modify: `ocr/pyproject.toml`, `ocr/uv.lock` (regenerated), `ocr/Dockerfile`
- Modify (rewrite): `ocr/test_read_pages.py`
- Modify: `.github/workflows/ci.yml` (the `ocr-image` job's smoke command, line ~122)

**Interfaces:**
- Produces, on stdout / as the Lambda response, exactly one of:
  - `{"pages": [{"number": int, "source": "text_layer" | "image", "scan_ppi": float | null, "lines": [str], "tables": [[[str]]]}]}` — `lines`/`tables` empty for `"image"` pages;
  - `{"refused": {"reason": "unreadable" | "too_many_pages" | "page_too_large" | "low_resolution", "page": int}}`.
- `text_layer_usable(lines: list[str], tables: list[list[list[str]]]) -> bool` (module function, unit-tested).

- [ ] **Step 1: Check the licence of the one new dependency**

Run: `curl -s https://raw.githubusercontent.com/jsvine/pdfplumber/stable/LICENSE.txt | head -3`
Expected: the MIT licence header. If it is not MIT, stop and report — the spec forbids copyleft parsers (PyMuPDF was ruled out as AGPL).

- [ ] **Step 2: Replace the dependencies**

`ocr/pyproject.toml` `dependencies` becomes:

```toml
dependencies = [
    "pdfplumber==0.11.10",
    "pillow>=11,<12",
    "pypdfium2==5.14.0",
]
```

and the `description` becomes `"Transcript page inventory, run as a child process or a Lambda (apps/documents/ocr.py)"`. Then:

Run: `cd /home/orkhan/Desktop/transcript-redesign && uv lock --project ocr`
Expected: `ocr/uv.lock` rewritten; no `paddle*` or `opencv*` package left in it (`grep -c paddle ocr/uv.lock` prints `0`).

- [ ] **Step 3: Write the failing tests**

Replace `ocr/test_read_pages.py` with:

```python
"""The page inventory: counting, the scan-resolution gate, the text-layer path, the handler.

Runs in the OCR venv (`uv run --project ocr pytest ocr`). The app's own suite skips it, because
pdfplumber exists only in the OCR venv.
"""

import io
from pathlib import Path

import pytest

pdfplumber = pytest.importorskip("pdfplumber")

import pypdfium2  # noqa: E402
import read_pages as rp  # noqa: E402
from PIL import Image  # noqa: E402


def _scanned_pdf(ppi, pages=1):
    images = [Image.new("RGB", (int(8.27 * ppi), int(11.69 * ppi)), "white") for _ in range(pages)]
    buffer = io.BytesIO()
    images[0].save(buffer, format="PDF", resolution=ppi, save_all=True, append_images=images[1:])
    return buffer.getvalue()


def _png(size=(1654, 2339)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_an_image_upload_is_one_image_page():
    assert rp.inventory(_png()) == {"pages": [{"number": 1, "source": "image", "scan_ppi": None, "lines": [], "tables": []}]}


def test_a_scanned_pdf_page_is_an_image_page_with_its_resolution():
    out = rp.inventory(_scanned_pdf(300))
    [page] = out["pages"]
    assert page["source"] == "image" and round(page["scan_ppi"]) == 300


def test_a_low_resolution_scan_is_refused_before_anything_is_read():
    assert rp.inventory(_scanned_pdf(120)) == {"refused": {"reason": "low_resolution", "page": 1}}


def test_too_many_pages_is_refused():
    assert rp.inventory(_scanned_pdf(200, pages=rp.MAX_PAGES + 1))["refused"]["reason"] == "too_many_pages"


def test_garbage_bytes_are_unreadable():
    assert rp.inventory(b"%PDF-not really") == {"refused": {"reason": "unreadable", "page": 1}}


def test_an_oversized_image_is_refused():
    assert rp.inventory(_png(size=(10_000, 6_000)))["refused"]["reason"] == "page_too_large"


def test_cid_codes_fail_the_text_layer_check():
    assert not rp.text_layer_usable(["(cid:12)(cid:15)(cid:20) " * 30], [])


def test_replacement_characters_fail_the_text_layer_check():
    assert not rp.text_layer_usable(["Organic Chemistry �� " * 30], [])


def test_too_little_text_fails_the_text_layer_check():
    assert not rp.text_layer_usable(["Page 1"], [])


def test_a_clean_text_layer_passes():
    rows = [["Code", "Course", "ECTS", "Grade"]] + [[f"CHM{i}", "Organic Chemistry", "6", "AA"] for i in range(20)]
    assert rp.text_layer_usable(["Transcript of Records"], [rows])


def test_handler_reads_the_named_key_from_its_own_bucket(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")

    class _S3:
        def get_object(self, Bucket, Key, Range):
            assert (Bucket, Key) == ("evidence", "quarantine/t/d")
            return {"Body": io.BytesIO(_png())}

    out = rp.handler({"key": "quarantine/t/d"}, None, s3=_S3())
    assert out["pages"][0]["source"] == "image"
```

Add one test that builds a real text-layer PDF. pdfplumber cannot write PDFs, so commit a fixture made once with the app's own `weasyprint`:

Run:
```bash
cd /home/orkhan/Desktop/transcript-redesign && mkdir -p ocr/fixtures && uv run python - <<'EOF'
from weasyprint import HTML
rows = "".join(f"<tr><td>CHM{i}</td><td>Organic Chemistry {i}</td><td>6</td><td>AA</td></tr>" for i in range(1, 21))
HTML(string=f"<h1>Transcript of Records</h1><table><tr><th>Code</th><th>Course</th><th>ECTS</th><th>Grade</th></tr>{rows}</table>").write_pdf("ocr/fixtures/text_transcript.pdf")
EOF
```

and the test:

```python
def test_a_born_digital_pdf_is_read_from_its_text_layer():
    data = (Path(__file__).parent / "fixtures" / "text_transcript.pdf").read_bytes()
    [page] = rp.inventory(data)["pages"]
    assert page["source"] == "text_layer"
    assert any("Organic Chemistry 7" in " ".join(row) for table in page["tables"] for row in table)
```

- [ ] **Step 4: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && uv sync --project ocr && uv run --project ocr pytest ocr -q`
Expected: FAIL — `AttributeError: module 'read_pages' has no attribute 'inventory'`

- [ ] **Step 5: Rewrite `ocr/read_pages.py`**

```python
"""A transcript upload's page inventory -- the one place an uploaded file is parsed.

Two entry points, one answer. In production `handler` is an AWS Lambda function (ocr/Dockerfile)
that the document worker invokes with the key of a GuardDuty-cleared upload; it reads that object
itself (a synchronous invocation carries at most 6 MB, an upload up to 10 MB). Locally and in tests
the same file runs as a child process: the upload's bytes on stdin, the answer on stdout.

It runs no model. It counts a PDF's pages, refuses a scan too coarse to read before anything is
paid for, and reads a born-digital page's own text layer with pdfplumber; every other page is
marked "image" and the worker sends it to Azure Document Intelligence
(spec 2026-10-03-transcript-reader-redesign §4, §4.1). The point of running here and not in the
worker: the process that parses an untrusted file holds no secret and no route to the internet.

usage: python read_pages.py < upload  |  Lambda: read_pages.handler
"""

from __future__ import annotations

import io
import json
import os
import sys

import pdfplumber
import pypdfium2
import pypdfium2.raw as pdfium_c
from PIL import Image

#: ponytail: one transcript is a handful of pages; plan 2's per-cycle allowance (50) is the real
#: bound once it lands. A longer file is refused, never truncated.
MAX_PAGES = 20
MAX_BYTES = 10_000_000
#: A page whose image would exceed this is refused before anything reads it (a 10 MB file can
#: declare a 200-inch page; a PNG can declare 50,000 x 50,000 pixels).
MAX_PIXELS = 50_000_000
#: Kept from the PaddleOCR gate, measured on .superpowers/ocr-eval: Mersin's 127-129 ppi scan read
#: 0% on every engine, every scan that read well was 200-400 ppi.
MIN_SCAN_PPI = 150
#: A text layer shorter than this is a cover or a scan with a stray caption, not a transcript.
MIN_TEXT_CHARS = 200


class Refused(Exception):
    def __init__(self, reason: str, page: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.page = page


def text_layer_usable(lines: list[str], tables: list[list[list[str]]]) -> bool:
    """Exact text only: a layer with unmapped glyphs is worse than no layer.

    pdfminer writes a glyph it cannot map to Unicode as "(cid:NN)"; a broken ToUnicode map gives
    U+FFFD. Either sends the page to Azure as an image.
    """
    text = " ".join(lines) + " " + " ".join(cell for table in tables for row in table for cell in row)
    if len(text.strip()) < MIN_TEXT_CHARS:
        return False
    return "(cid:" not in text and "�" not in text


def scan_ppi(page: pypdfium2.PdfPage) -> float | None:
    """The lowest resolution of any image covering half the page's width or more (area-based)."""
    found = []
    for image in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3):
        left, bottom, right, top = image.get_bounds()
        if right - left < page.get_width() / 2:
            continue
        px_width, px_height = image.get_px_size()
        found.append(((px_width * px_height) / ((right - left) * (top - bottom) / 72**2)) ** 0.5)
    return min(found) if found else None


def _image_page() -> dict:
    return {"number": 1, "source": "image", "scan_ppi": None, "lines": [], "tables": []}


def _pdf(data: bytes) -> list[dict]:
    try:
        document = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError:
        raise Refused("unreadable", 1) from None
    if len(document) > MAX_PAGES:
        raise Refused("too_many_pages", len(document))
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as plumbed:
        for number, (page, plumbed_page) in enumerate(zip(document, plumbed.pages), start=1):
            width, height = page.get_size()
            if width * height * (200 / 72) ** 2 > MAX_PIXELS:
                raise Refused("page_too_large", number)
            tables = [
                [[" ".join((cell or "").split()) for cell in row] for row in table]
                for table in plumbed_page.extract_tables()
            ]
            lines = [line for line in (plumbed_page.extract_text() or "").splitlines() if line.strip()]
            if text_layer_usable(lines, tables):
                pages.append({"number": number, "source": "text_layer", "scan_ppi": None,
                              "lines": lines, "tables": tables})
                continue
            ppi = scan_ppi(page)
            if ppi is not None and ppi < MIN_SCAN_PPI:
                raise Refused("low_resolution", number)
            pages.append({"number": number, "source": "image", "scan_ppi": ppi, "lines": [], "tables": []})
    return pages


def inventory(data: bytes) -> dict:
    try:
        if data.startswith(b"%PDF"):
            pages = _pdf(data)
        else:
            Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # pillow's own decompression-bomb guard
            try:
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
            except Image.DecompressionBombError:
                raise Refused("page_too_large", 1) from None
            except (OSError, ValueError):
                raise Refused("unreadable", 1) from None
            if width * height > MAX_PIXELS:
                raise Refused("page_too_large", 1)
            pages = [_image_page()]
    except Refused as refusal:
        return {"refused": {"reason": refusal.reason, "page": refusal.page}}
    return {"pages": pages}


def handler(event: dict, context: object, s3=None) -> dict:  # noqa: ANN001 - a boto3 client
    """Read the one cleared upload the worker names. The bucket is this function's own
    configuration, so a caller chooses which upload is read, never which bucket."""
    if s3 is None:
        import boto3

        s3 = boto3.client("s3")
    body = s3.get_object(
        Bucket=os.environ["DOCUMENT_BUCKET"], Key=event["key"], Range=f"bytes=0-{MAX_BYTES}"
    )["Body"].read()
    if len(body) > MAX_BYTES:
        return {"refused": {"reason": "unreadable", "page": 1}}
    return inventory(body)


if __name__ == "__main__":
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    print(json.dumps(inventory(data) if len(data) <= MAX_BYTES else
                     {"refused": {"reason": "unreadable", "page": 1}}))
```

Before replacing the handler, read the current one (`sed -n '/^def handler/,$p' ocr/read_pages.py`) and keep anything it does beyond the above (for example how it reports an object missing) — the replacement must not lose a behaviour the current tests pin.

- [ ] **Step 6: Simplify the Dockerfile**

In `ocr/Dockerfile`: delete the `dnf install` line, the `ENV PADDLE_PDX_CACHE_HOME=... OPENCV_IO_MAX_IMAGE_PIXELS=...` line (keep `HOME=/tmp` as `ENV HOME=/tmp`), both `RUN python read_pages.py --bake` lines and `ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`. Replace the header comment's "~3 GB of PaddlePaddle and model weights" with "the page inventory: pdfplumber and pypdfium2, no model". Keep the base images, their digests, `COPY read_pages.py ./` and `CMD ["read_pages.handler"]`.

In `.github/workflows/ci.yml`, replace the `ocr-image` job's smoke command with:

```yaml
            --entrypoint python tehsil-ocr:ci -c "import io, read_pages as rp; from PIL import Image; b = io.BytesIO(); Image.new('RGB', (800, 1100), 'white').save(b, format='PNG'); out = rp.inventory(b.getvalue()); assert out['pages'][0]['source'] == 'image', out; print('inventory', out)"
```

- [ ] **Step 7: Run to verify they pass**

Run: `cd /home/orkhan/Desktop/transcript-redesign && uv run --project ocr pytest ocr -q && uv run bandit -c pyproject.toml -r ocr/read_pages.py && docker build --platform linux/amd64 --provenance=false -t tehsil-ocr:local ocr/`
Expected: all ocr tests pass; bandit clean; the image builds (if Docker is unavailable locally, record that and rely on CI's `ocr-image` job).

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add ocr .github/workflows/ci.yml
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(ocr): the Lambda becomes a page inventory -- text layers read, scans measured, no model

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The seam — inventory, then Azure for image pages, then the gate

**Files:**
- Modify: `apps/documents/ocr.py`
- Modify: `config/settings/base.py` (remove `OCR_MODEL_HOME`)
- Modify (rewrite the engine-dependent parts): `tests/documents/test_ocr.py`

**Interfaces:**
- Consumes: the inventory answer (Task 3), `analyze_layout` / `AzureLayout` (Task 2).
- Produces:
  - `OcrPage` gains: `source: Literal["text_layer", "azure"]`, `api_version: str` (`""` for text layer), `cell_confidence: tuple[tuple[tuple[float | None, ...], ...], ...]` — same shape as `tables`, `None` for a blank cell or a text-layer cell. `script` and `skew` stay (`skew` is `0.0`; Azure handles tilt).
  - `read_pages(document: DocumentVersion, content: bytes, *, locale: str | None = None, analyze=analyze_layout) -> tuple[OcrPage, ...]`.
  - `PageRefused.reason` gains `text_too_small`, `unreadable`, `cut_off`, `not_a_transcript` from the Azure gate; it keeps `low_resolution`, `too_many_pages`, `page_too_large` from the inventory.
  - Module constants (starting values, calibrated by spec §9 gate 3): `GATE_MIN_TEXT_PX = 12`, `GATE_UNREADABLE_BELOW = 0.80`, `GATE_EDGE_FRACTION = 0.005`, `GATE_EDGE_WORDS = 3`.

- [ ] **Step 1: Write the failing tests**

Keep the transport tests in `tests/documents/test_ocr.py` that exercise `_invoke` and `_run_child` (Lambda errors, crashes, unparseable output) but change their canned answers to the inventory shape; delete the test that ran the real PaddleOCR engine. Add:

```python
from apps.documents.azure_layout import AzureLayout

_INVENTORY_IMAGE = {"pages": [{"number": 1, "source": "image", "scan_ppi": None, "lines": [], "tables": []}]}


def _layout(*, word_height=30, confidence=0.98, near_edge=0, tables=True, width=1654, height=2339, unit="pixel"):
    words = [{"content": f"w{i}", "confidence": confidence, "span": {"offset": i, "length": 1},
              "polygon": [100, 100 + 40 * i, 200, 100 + 40 * i, 200, 100 + 40 * i + word_height, 100, 100 + 40 * i + word_height]}
             for i in range(20)]
    words += [{"content": "edge", "confidence": 0.9, "span": {"offset": 99, "length": 1},
               "polygon": [0, 500, 50, 500, 50, 530, 0, 530]} for _ in range(near_edge)]
    lines = [{"content": "Organic Chemistry 6 AA", "polygon": [100, 100, 600, 100, 600, 130, 100, 130],
              "spans": [{"offset": 0, "length": 2}]},
             {"content": "Baku State University", "polygon": [100, 50, 600, 50, 600, 80, 100, 80],
              "spans": [{"offset": 50, "length": 5}]}]
    cells = [{"rowIndex": 0, "columnIndex": 0, "content": "Organic Chemistry", "spans": [{"offset": 0, "length": 1}]},
             {"rowIndex": 0, "columnIndex": 1, "content": "6", "spans": [{"offset": 1, "length": 1}]},
             {"rowIndex": 0, "columnIndex": 2, "content": "", "spans": []}]
    return AzureLayout.model_validate({
        "content": "x" * 100,
        "pages": [{"pageNumber": 1, "width": width, "height": height, "unit": unit, "words": words, "lines": lines}],
        "tables": [{"rowCount": 1, "columnCount": 3, "cells": cells,
                    "boundingRegions": [{"pageNumber": 1, "polygon": [90, 90, 700, 90, 700, 140, 90, 140]}]}] if tables else [],
    })


def test_an_image_page_is_read_by_azure_with_cell_confidence(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    [page] = read_pages(_DOCUMENT, b"\x89PNG", analyze=lambda content, **k: _layout())
    assert page.source == "azure" and page.api_version == "2024-11-30"
    assert page.tables == (("Organic Chemistry", "6", ""),)
    assert page.cell_confidence[0][0][1] == 0.98 and page.cell_confidence[0][0][2] is None
    assert page.lines == ("Baku State University",)  # the table's own line is not a free line


def test_text_layer_pages_never_reach_azure(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [{"number": 1, "source": "text_layer", "scan_ppi": None,
                                                    "lines": ["Transcript"], "tables": [[["CHM1", "6"]]]}]})
    def never(content, **k):
        raise AssertionError("a text-layer page was sent to Azure")
    [page] = read_pages(_DOCUMENT, b"%PDF", analyze=never)
    assert page.source == "text_layer" and page.cell_confidence == (((None, None),),)


def test_mixed_pdf_sends_only_scanned_pages_to_azure(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [
        {"number": 1, "source": "text_layer", "scan_ppi": None, "lines": ["Transcript"], "tables": [[["A", "1"]]]},
        {"number": 2, "source": "image", "scan_ppi": 300.0, "lines": [], "tables": []},
    ]})
    asked = []
    def analyze(content, **kwargs):
        asked.append(kwargs["pages"])
        layout = _layout()
        return layout.model_copy(update={"pages": (layout.pages[0].model_copy(update={"pageNumber": 2}),),
                                         "tables": (layout.tables[0].model_copy(update={"boundingRegions": (layout.tables[0].boundingRegions[0].model_copy(update={"pageNumber": 2}),)}),)})
    pages = read_pages(_DOCUMENT, b"%PDF", analyze=analyze)
    assert asked == ["2"] and [p.source for p in pages] == ["text_layer", "azure"]


@pytest.mark.parametrize("layout,reason", [
    (dict(word_height=8), "text_too_small"),
    (dict(confidence=0.5), "unreadable"),
    (dict(near_edge=3), "cut_off"),
])
def test_the_gate_refuses_a_page_on_azures_own_output(tmp_path, monkeypatch, layout, reason):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    with pytest.raises(PageRefused) as refused:
        read_pages(_DOCUMENT, b"\x89PNG", analyze=lambda content, **k: _layout(**layout))
    assert (refused.value.reason, refused.value.page) == (reason, 1)


def test_a_document_with_no_table_anywhere_is_not_a_transcript(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    with pytest.raises(PageRefused) as refused:
        read_pages(_DOCUMENT, b"\x89PNG", analyze=lambda content, **k: _layout(tables=False))
    assert refused.value.reason == "not_a_transcript"


def test_a_scanned_pdf_measures_text_height_in_its_own_pixels(tmp_path, monkeypatch):
    # Azure reports PDF pages in inches: 0.05 in at 300 ppi is 15 px (passes); at 200 ppi 10 px (refused).
    for ppi, refused in ((300.0, False), (200.0, True)):
        _answering(tmp_path, monkeypatch, {"pages": [{"number": 1, "source": "image", "scan_ppi": ppi, "lines": [], "tables": []}]})
        layout = lambda content, **k: _layout(word_height=0.05, width=8.27, height=11.69, unit="inch")
        if refused:
            with pytest.raises(PageRefused, match="text_too_small"):
                read_pages(_DOCUMENT, b"%PDF", analyze=layout)
        else:
            read_pages(_DOCUMENT, b"%PDF", analyze=layout)
```

(The `_layout` polygon numbers are in the page's unit: pass `word_height=0.05` for inches; the edge words at x=0 count as touching the edge in either unit.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_ocr.py -q`
Expected: FAIL — `TypeError: read_pages() got an unexpected keyword argument 'analyze'`

- [ ] **Step 3: Implement**

In `apps/documents/ocr.py`:

1. Replace the module docstring's first paragraph with: the seam runs the page inventory (Lambda or child, unchanged transports), reads every `"image"` page with Azure Document Intelligence (`azure_layout.py`), and gates the result; spec 2026-10-03-transcript-reader-redesign §4, §4.1, §5.
2. Extend `OcrPage`:

```python
class OcrPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: Literal["latin", "cyrillic"]
    skew: float
    lines: tuple[str, ...]
    tables: tuple[tuple[tuple[str, ...], ...], ...]
    #: Same shape as `tables`: Azure's confidence for each cell (the lowest of its words), None for
    #: a blank cell and for every text-layer cell -- the document's own text has no reader doubt.
    cell_confidence: tuple[tuple[tuple[float | None, ...], ...], ...] = ()
    source: Literal["text_layer", "azure"] = "text_layer"
    #: The Azure API version that produced this page; "" for a text-layer page.
    api_version: str = ""
```

3. Replace `_Output` with an inventory model:

```python
class _InventoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    source: Literal["text_layer", "image"]
    scan_ppi: float | None
    lines: tuple[str, ...]
    tables: tuple[tuple[tuple[str, ...], ...], ...]


class _Output(BaseModel):
    """Exactly one of a non-empty `pages` or a `refused` reason -- never neither, never both."""

    model_config = ConfigDict(extra="forbid")

    pages: tuple[_InventoryPage, ...] = ()
    refused: _Refusal | None = None

    @model_validator(mode="after")
    def _exactly_one_answer(self) -> Self:
        if bool(self.pages) == (self.refused is not None):
            raise ValueError("answer must carry a non-empty pages or a refused reason, not both")
        return self
```

4. Remove the `PADDLE_*` and `OPENCV_*` entries from `_child_env()` (keep `PATH` and `HOME`), and delete `OCR_MODEL_HOME` from `config/settings/base.py` (grep for any other use first: `grep -rn OCR_MODEL_HOME apps config tests`).
5. Add the gate constants and helpers, and rewrite `read_pages`:

```python
#: The quality gate's starting floors (spec §5); spec §9 gate 3 sets them on degraded pages.
#: Text height: the old PaddleOCR gate's measured floor, 12 px (SPbU's 10 px lines read 0%).
GATE_MIN_TEXT_PX = 12.0
#: Mean word confidence below which a page is refused as unreadable (Veryfi's review line, 0.8).
GATE_UNREADABLE_BELOW = 0.80
#: A word within this fraction of the page's width or height of an edge "touches" it;
#: this many touching words mean the page was cut off.
GATE_EDGE_FRACTION = 0.005
GATE_EDGE_WORDS = 3


def _height(polygon: tuple[float, ...]) -> float:
    ys = polygon[1::2]
    return max(ys) - min(ys)


def _gate(page: AzurePage, scan_ppi: float | None) -> str | None:
    """The refusal reason for one Azure-read page, or None."""
    words = page.words
    if not words:
        return "unreadable"
    to_px = 1.0 if page.unit == "pixel" else scan_ppi
    if to_px is not None:
        heights = sorted(_height(word.polygon) * to_px for word in words if len(word.content) >= 3)
        if heights and heights[len(heights) // 2] < GATE_MIN_TEXT_PX:
            return "text_too_small"
    if sum(word.confidence for word in words) / len(words) < GATE_UNREADABLE_BELOW:
        return "unreadable"
    dx, dy = page.width * GATE_EDGE_FRACTION, page.height * GATE_EDGE_FRACTION
    touching = sum(
        1 for word in words
        if min(word.polygon[0::2]) <= dx or max(word.polygon[0::2]) >= page.width - dx
        or min(word.polygon[1::2]) <= dy or max(word.polygon[1::2]) >= page.height - dy
    )
    return "cut_off" if touching >= GATE_EDGE_WORDS else None


def _script(text: str) -> Literal["latin", "cyrillic"]:
    cyrillic = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    letters = sum(1 for ch in text if ch.isalpha())
    return "cyrillic" if letters and cyrillic / letters > 0.5 else "latin"


def _azure_page(layout: AzureLayout, page: AzurePage) -> OcrPage:
    word_at = {word.span.offset: word for word in page.words}
    tables, confidences = [], []
    in_tables: set[int] = set()
    for table in layout.tables:
        if not table.boundingRegions or table.boundingRegions[0].pageNumber != page.pageNumber:
            continue
        grid = [[""] * table.columnCount for _ in range(table.rowCount)]
        conf: list[list[float | None]] = [[None] * table.columnCount for _ in range(table.rowCount)]
        for cell in table.cells:
            grid[cell.rowIndex][cell.columnIndex] = " ".join(cell.content.split())
            found = [
                word.confidence
                for span in cell.spans
                for offset, word in word_at.items()
                if span.offset <= offset < span.offset + span.length
            ]
            for span in cell.spans:
                in_tables.update(range(span.offset, span.offset + span.length))
            conf[cell.rowIndex][cell.columnIndex] = min(found) if found and grid[cell.rowIndex][cell.columnIndex] else None
        tables.append(tuple(tuple(row) for row in grid))
        confidences.append(tuple(tuple(row) for row in conf))
    lines = tuple(
        line.content for line in page.lines
        if line.content.strip()
        and not any(span.offset in in_tables for span in line.spans)
    )
    return OcrPage(
        script=_script(" ".join(word.content for word in page.words)),
        skew=0.0,
        lines=lines,
        tables=tuple(tables),
        cell_confidence=tuple(confidences),
        source="azure",
        api_version=settings.AZURE_DI_API_VERSION,
    )


def read_pages(
    document: DocumentVersion,
    content: bytes,
    *,
    locale: str | None = None,
    analyze: Callable[..., AzureLayout] = analyze_layout,
) -> tuple[OcrPage, ...]:
    """Every page's lines and tables, or PageRefused for a page the gate will not read.

    The inventory runs where the file is parsed safely (Lambda or child); only its "image" pages
    are sent to Azure -- as the original bytes, with Azure's own page selector -- so a PDF's
    text-layer pages are never billed and the worker never parses the file itself.
    """
    raw = _invoke(document.object_key) if settings.OCR_FUNCTION_NAME else _run_child(content)
    try:
        output = _Output.model_validate_json(raw)
    except ValidationError as error:
        raise OcrUnavailable("unparseable output") from error
    if output.refused is not None:
        raise PageRefused(output.refused.reason, output.refused.page)
    image_pages = [page for page in output.pages if page.source == "image"]
    read: dict[int, OcrPage] = {}
    if image_pages:
        selector = None if content[:4] != b"%PDF" else ",".join(str(p.number) for p in image_pages)
        layout = analyze(content, pages=selector, locale=locale)
        by_number = {page.pageNumber: page for page in layout.pages}
        for inventoried in image_pages:
            page = by_number.get(inventoried.number) or (layout.pages[0] if selector is None and layout.pages else None)
            if page is None:
                raise OcrUnavailable(f"Azure returned no page {inventoried.number}")
            reason = _gate(page, inventoried.scan_ppi)
            if reason is not None:
                raise PageRefused(reason, inventoried.number)
            read[inventoried.number] = _azure_page(layout, page)
    pages = tuple(
        read[page.number] if page.source == "image" else OcrPage(
            script=_script(" ".join(page.lines)),
            skew=0.0,
            lines=page.lines,
            tables=page.tables,
            cell_confidence=tuple(tuple(tuple(None for _ in row) for row in table) for table in page.tables),
            source="text_layer",
        )
        for page in output.pages
    )
    if not any(page.tables for page in pages):
        raise PageRefused("not_a_transcript", 1)
    return pages
```

Add the imports this needs (`Callable` from `collections.abc`; `AzureLayout`, `AzurePage`, `analyze_layout` from `.azure_layout`). There is no import cycle: both modules take the exceptions from `ocr_errors.py` (Task 2).

Update `PageRefused`'s docstring (now in `ocr_errors.py`) list of reasons to: `low_resolution, too_many_pages, page_too_large, unreadable, text_too_small, cut_off, not_a_transcript`.

- [ ] **Step 4: Run to verify they pass**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_ocr.py tests/documents/test_azure_layout.py -q && uv run mypy apps/documents/ocr.py apps/documents/azure_layout.py`
Expected: PASS; no type errors.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/ocr.py apps/documents/ocr_errors.py config/settings/base.py tests/documents/test_ocr.py
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): inventory, then Azure for scanned pages only, then the gate on Azure's own output

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The reader carries cell confidence and flags doubtful credits and grades

**Files:**
- Modify: `apps/documents/transcript.py` (`Highlight.kind`, `_minimised`, `_Cut`, `_course_rows`, `read_transcript`)
- Modify: `config/settings/base.py` (one setting)
- Test: `tests/documents/test_transcript.py` (add tests; update helpers that build `OcrPage`)

**Interfaces:**
- Consumes: `OcrPage.cell_confidence` (Task 4).
- Produces:
  - `Highlight.kind` gains `"low_confidence"` (scope `"row"`, `ref` the row index) — the summary screen already renders highlights by kind and scope; JSON storage needs no migration.
  - `settings.TRANSCRIPT_LOW_CONFIDENCE_BELOW = 0.8` (spec §6.3's starting floor; §9 gate 5 tunes it).
  - `read_transcript` refuses with `TranscriptReadingDisabled` when `settings.TRANSCRIPT_AZURE_ENABLED` is off, checked right after the Jev gate and before the upload is opened; `read_pages` is called with `locale=None` (plan 2 passes the student's stated language).

- [ ] **Step 1: Write the failing tests**

In `tests/documents/test_transcript.py`, open the Azure gate beside the Jev gate in the existing autouse fixture:

```python
@pytest.fixture(autouse=True)
def _jev_launch_gate_open(settings):
    """...(existing docstring)... TRANSCRIPT_AZURE_ENABLED is opened for the same reason."""
    settings.TRANSCRIPT_JEV_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True
```

Then add, using the module's own `_read`, `HEADER` and `_jev` (which answers columns by header name and every row as a course):

```python
def _azure_page(rows, confidences, *, lines=LINES, source="azure"):
    return OcrPage(
        script="latin", skew=0.0, lines=tuple(lines),
        tables=(tuple(tuple(row) for row in rows),),
        cell_confidence=(tuple(tuple(c) for c in confidences),),
        source=source, api_version="2024-11-30" if source == "azure" else "",
    )


def _flagged(reading):
    by_index = {row.index: row.title for row in reading.rows}
    return sorted(by_index[int(h.ref)] for h in reading.doubts if h.kind == "low_confidence")


def test_a_doubtful_credit_flags_its_row(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("CHEM101", "Organic Chemistry I", "6", "91"), ("PHY101", "Physics", "5", "80")],
        [(0.99,) * 4, (0.99, 0.99, 0.62, 0.99), (0.99, 0.99, 0.97, 0.98)],
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == ["Organic Chemistry I"]


def test_a_doubtful_grade_flags_its_row_too(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("PHY101", "Physics", "5", "80")],
        [(0.99,) * 4, (0.99, 0.99, 0.99, 0.41)],
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == ["Physics"]


def test_a_doubtful_title_alone_raises_no_flag(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("PHY101", "Physics", "5", "80")],
        [(0.99,) * 4, (0.99, 0.30, 0.99, 0.99)],
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == []


def test_blank_cells_carry_no_confidence_and_raise_no_flag(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("CHEM400", "Thesis", "", "")],
        [(0.99,) * 4, (0.99, 0.99, None, None)],
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == []


def test_confidences_stay_aligned_when_a_row_is_dropped(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("", "Student name: Aysel Mammadova", "", ""), ("PHY101", "Physics", "5", "80")],
        [(0.99,) * 4, (0.40, 0.40, None, None), (0.99, 0.99, 0.55, 0.99)],
    )
    reading = _read(agency_a, membership_a, fake_store, page, names=frozenset({"aysel", "mammadova"}))
    assert _flagged(reading) == ["Physics"]


def test_text_layer_cells_are_never_flagged(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("PHY101", "Physics", "5", "80")],
        [(None,) * 4, (None,) * 4], source="text_layer",
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == []


def test_transcript_reading_is_refused_until_the_azure_launch_gate_is_on(
    agency_a, membership_a, fake_store, settings
):
    settings.TRANSCRIPT_AZURE_ENABLED = False
    with tenant_scope(agency_a.id):
        document = _document(agency_a, membership_a, fake_store)
    with patch("apps.documents.transcript.read_pages") as ocr:
        with pytest.raises(TranscriptReadingDisabled, match="TRANSCRIPT_AZURE_ENABLED"):
            read_transcript(document=document, names=frozenset(), store=fake_store)
    ocr.assert_not_called()
```

If `"Student name: Aysel Mammadova"` is not dropped by `_minimised` (check `_PERSONAL_LABEL`: `"student name"` is not in it, but `"name\s*:"` at line start is only for `^\s*(?:student\s+)?name\s*:` — the cell starts with "Student name:", which matches), adjust the cell text to one the existing tests show being dropped (see `test_a_label_row_drops_the_value_row_below_it_including_a_birth_date`).

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript.py -q -k "doubtful or blank_cells or aligned or text_layer_cells or azure_launch_gate"`
Expected: FAIL — `low_confidence` is not a valid `Highlight.kind`.

- [ ] **Step 3: Implement**

In `config/settings/base.py`, after `TRANSCRIPT_AZURE_ENABLED`:

```python
#: A course row's credit or grade cell below this Azure confidence is asked about on the summary
#: screen (spec §6.3). Starting value: below 0.8 flagged 71-100% of Azure's wrong lines in the
#: eval harness; spec §9 gate 5 tunes it on real transcripts.
TRANSCRIPT_LOW_CONFIDENCE_BELOW = 0.8
```

In `apps/documents/transcript.py`:

1. Add `"low_confidence"` to `Highlight.kind`'s `Literal`, and extend its docstring: "or a credit or grade cell the reader was unsure of".
2. `_minimised` returns a third value, the confidence grids filtered exactly like the tables:

```python
def _minimised(pages: tuple[OcrPage, ...], names: frozenset[str]) -> tuple[
    list[str], list[list[list[str]]], list[list[list[float | None]]]
]:
    # (the `pages = _normalised(pages)`, `names = ...` and free-line loop above stay as they are)
    tables: list[list[list[str]]] = []
    confidences: list[list[list[float | None]]] = []
    for page in pages:
        page_conf = page.cell_confidence or tuple(
            tuple(tuple(None for _ in row) for row in table) for table in page.tables
        )
        for table, table_conf in zip(page.tables, page_conf, strict=True):
            kept: list[list[str]] = []
            kept_conf: list[list[float | None]] = []
            drop_next = False
            for row, row_conf in zip(table, table_conf, strict=True):
                labelled = any(_has_label(cell) for cell in row)
                should_drop = drop_next or labelled or _names_in(" ".join(row), names)
                drop_next = labelled
                if should_drop:
                    continue
                kept.append([_ID_NUMBER.sub("#", _DATE.sub("#", cell)) for cell in row])
                kept_conf.append(list(row_conf))
            if kept:
                tables.append(kept)
                confidences.append(kept_conf)
    return lines, tables, confidences
```

(`_normalised(pages)` rebuilds pages — make it pass `cell_confidence`, `source` and `api_version` through unchanged; read it at line ~215 and add those fields to the copy it makes.)

3. `_Cut` gains `confs: list[float | None]` and a method:

```python
    def doubtful(self, kinds: tuple[str, ...], below: float) -> bool:
        return any(
            (conf := self.confs[self.where[kind]]) is not None and conf < below
            for kind in kinds
            if kind in self.where
        )
```

4. `_course_rows(tables, kinds, confidences)` passes `[table_conf[r][position] for position in group]` alongside each row's cells (`zip(table, table_conf)` over rows).
5. In `read_transcript`: right after the existing `TRANSCRIPT_JEV_ENABLED` check, add

```python
    if not settings.TRANSCRIPT_AZURE_ENABLED:
        # Spec 2026-10-03-transcript-reader-redesign §4: no real transcript reaches Azure until
        # Microsoft's data-processing terms are reviewed. Same handling as the Jev gate above.
        raise TranscriptReadingDisabled(
            "transcript reading is off: TRANSCRIPT_AZURE_ENABLED is not set"
        )
```

then `lines, tables, confidences = _minimised(read_pages(document, content), names)`, `cut = _course_rows(tables, kinds, confidences)`, and in the row loop, after the existing empty-title check:

```python
        if kind == "course" and row.doubtful(("credits", "grade"), settings.TRANSCRIPT_LOW_CONFIDENCE_BELOW):
            doubts[Highlight(kind="low_confidence", scope="row", ref=str(i))] = None
```

6. Update existing tests that construct `OcrPage` without `cell_confidence`: the field defaults to `()` and `_minimised` fills `None`s, so they should pass unchanged — run them to confirm.

- [ ] **Step 4: Run to verify they pass**

Run: `cd /home/orkhan/Desktop/transcript-redesign && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript.py tests/documents/test_transcript_checks.py tests/documents/test_transcript_worker.py tests/accounts -q && uv run mypy apps config`
Expected: PASS. If `tests/documents/test_transcript_worker.py` fails because the worker test settings leave `TRANSCRIPT_AZURE_ENABLED` off, set it on in that module's existing settings fixture next to `TRANSCRIPT_JEV_ENABLED`.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add apps/documents/transcript.py config/settings/base.py tests/documents
git -C /home/orkhan/Desktop/transcript-redesign commit -m "feat(documents): flag a course whose credit or grade the reader was unsure of; Azure launch gate

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Infrastructure — the key, the endpoint, a smaller Lambda

**Files:**
- Modify: `infra/template.yaml` (new secret near `TypesafeApiKeySecret` ~line 1251; the execution role's secret list ~line 1310; `DocumentWorkerTaskDefinition` environment/secrets ~line 2085; `OcrFunction` ~line 2164; a new `AzureDocumentIntelligenceEndpoint` parameter)
- Modify: `tests/infra/test_template.py` (the OCR-function tests ~line 1489)
- Modify: `docs/runbooks/deploy.md` (one paragraph)

**Interfaces:**
- Produces: `AzureDocumentIntelligenceKeySecret` (populated out of band, like the other vendor keys); the document worker receives `AZURE_DI_ENDPOINT` (environment, from the parameter) and `AZURE_DI_KEY` (secret); `TRANSCRIPT_AZURE_ENABLED` is **not** set in the template — turning it on is the owner's decision after the DPA review (spec §4).

- [ ] **Step 1: Write the failing tests**

In `tests/infra/test_template.py`, add:

```python
def test_the_document_worker_gets_the_azure_key_as_a_secret_and_never_the_launch_gate(template: Template) -> None:
    container = template.resource("DocumentWorkerTaskDefinition")["Properties"]["ContainerDefinitions"][0]
    secrets = {s["Name"]: s["ValueFrom"] for s in container["Secrets"]}
    env = {e["Name"]: e["Value"] for e in container["Environment"]}
    assert secrets["AZURE_DI_KEY"] == {"Ref": "AzureDocumentIntelligenceKeySecret"}
    assert env["AZURE_DI_ENDPOINT"] == {"Ref": "AzureDocumentIntelligenceEndpoint"}
    assert "TRANSCRIPT_AZURE_ENABLED" not in env  # the owner turns it on after the DPA review


def test_the_page_inventory_function_is_small(template: Template) -> None:
    function = template.resource("OcrFunction")["Properties"]
    assert function["MemorySize"] <= 2048 and function["Timeout"] <= 120
```

and in the existing `test_transcript_ocr_is_a_function_from_its_own_image`, replace any assertion on `MemorySize == 10240` or `Timeout == 720` with the new values. Keep every test about the function holding no secret, reading only cleared uploads, and having no route out — they still hold.

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/transcript-redesign && uv run pytest tests/infra/test_template.py -q -k "azure or inventory or ocr"`
Expected: FAIL — `KeyError: 'AZURE_DI_KEY'`

- [ ] **Step 3: Edit the template**

- Add a parameter: `AzureDocumentIntelligenceEndpoint: { Type: String, Default: "", Description: "https URL of the EU Document Intelligence resource (transcript reader)" }`.
- Add, beside `TypesafeApiKeySecret`:

```yaml
  # Azure Document Intelligence, the transcript reader for scanned pages and photos
  # (spec 2026-10-03-transcript-reader-redesign §4). Populate out of band. Reading stays off
  # until TRANSCRIPT_AZURE_ENABLED is set after Microsoft's data-processing terms are reviewed.
  AzureDocumentIntelligenceKeySecret:
    Type: AWS::SecretsManager::Secret
    Properties:
      Description: Azure Document Intelligence key (populate out-of-band)
```

- Add `- !Ref AzureDocumentIntelligenceKeySecret` to the same execution-role secret list that holds `TypesafeApiKeySecret`.
- In `DocumentWorkerTaskDefinition`: environment `- Name: AZURE_DI_ENDPOINT` / `Value: !Ref AzureDocumentIntelligenceEndpoint`; secret `- Name: AZURE_DI_KEY` / `ValueFrom: !Ref AzureDocumentIntelligenceKeySecret`. Update the comment above `OCR_FUNCTION_NAME` to "The page inventory is invoked, never run here (apps/documents/ocr.py)".
- `OcrFunction`: `MemorySize: 1024`, `Timeout: 60`. Update `apps/documents/ocr.py`'s `_TIMEOUT_SECONDS` to `60` and its comment (the inventory measured well under a second a page; 60 s covers a cold start).

Run cfn-lint the way CI does (read `.github/workflows/ci.yml` for the exact command) on the template.

- [ ] **Step 4: The runbook**

Add to `docs/runbooks/deploy.md` under the secrets section: create the Document Intelligence resource in an EU region (S0 tier), store its key in `AzureDocumentIntelligenceKeySecret`, pass its endpoint as the `AzureDocumentIntelligenceEndpoint` parameter, and leave `TRANSCRIPT_AZURE_ENABLED` unset until the owner records the DPA review.

- [ ] **Step 5: Run to verify they pass**

Run: `cd /home/orkhan/Desktop/transcript-redesign && uv run pytest tests/infra -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add infra/template.yaml tests/infra/test_template.py docs/runbooks/deploy.md apps/documents/ocr.py
git -C /home/orkhan/Desktop/transcript-redesign commit -m "infra: the Azure key and endpoint reach the document worker; the page inventory runs small

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The live check, the spec pointer, and the full gate

**Files:**
- Modify: `tests/documents/test_transcript_live.py`
- Modify: `docs/superpowers/specs/2026-09-25-tailored-programme-finding-design.md` (one pointer line at the top of §3.1's OCR paragraphs)
- Modify: `CLAUDE.md` only if it names PaddleOCR as the transcript reader (grep first)

- [ ] **Step 1: The live test reads through Azure**

Read `tests/documents/test_transcript_live.py`. Make its sample run with `TRANSCRIPT_AZURE_ENABLED = True`, `AZURE_DI_ENDPOINT`/`AZURE_DI_KEY` taken from `~/.config/tehsil_agent/ocr.env` (skip with a clear reason when absent), and the real child-process inventory (`OCR_FUNCTION_NAME = ""`, `OCR_PYTHON` the OCR venv's interpreter). Assert at least five course rows, every page's `source` reported, and print the number of `low_confidence` highlights. Use only the published samples already used by that test — never the owner's real transcript.

- [ ] **Step 2: Run it**

Run: `cd /home/orkhan/Desktop/transcript-redesign && set -a && . ~/.config/tehsil_agent/ocr.env && . ~/.config/tehsil_agent/openrouter.env && set +a && POSTGRES_DB=tehsil_transcript uv run pytest tests/documents/test_transcript_live.py -m live -s -q`
Expected: PASS, printing rows read and flags raised. Paste the printed lines into the commit message. If either key file is missing, report it and stop — do not fake the run.

- [ ] **Step 3: The pointer in the older spec**

At the start of the "**OCR first (owner, 2026-09-25).**" paragraph in `2026-09-25-tailored-programme-finding-design.md` §3.1, add one line: "**Superseded for reading by `2026-10-03-transcript-reader-redesign-design.md` (2026-10-05): Azure Document Intelligence and the PDF's own text layer, the Lambda kept as a page inventory.**"

- [ ] **Step 4: The full gate**

Run:
```bash
cd /home/orkhan/Desktop/transcript-redesign && uv run ruff check . && uv run mypy apps config && POSTGRES_DB=tehsil_transcript uv run pytest -q && uv run python manage.py makemigrations --check --dry-run && uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py && uv sync --project ocr --frozen && uv run --project ocr pytest ocr -q && uv run pip-audit && uv export --project ocr --frozen --no-hashes --no-dev -o /tmp/ocr-req.txt && uv run pip-audit -r /tmp/ocr-req.txt --no-deps --disable-pip
```
Expected: every command clean. `grep -rn -i "paddle" apps config ocr tests infra .github` prints nothing except historical prose in docs.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/transcript-redesign add tests/documents/test_transcript_live.py docs/superpowers/specs/2026-09-25-tailored-programme-finding-design.md CLAUDE.md
git -C /home/orkhan/Desktop/transcript-redesign commit -m "test(documents): a live read through Azure and the text layer; the older spec points here

<paste the live test's printed lines>

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
