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

from apps.research.egress import SourceBlocked, UnsafeTarget, fetch_json_api, start_json_operation

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
    #: Optional in Azure's schema; a word without one is read but never gated on geometry.
    polygon: tuple[float, ...] = ()
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
    boundingRegions: tuple[AzureRegion, ...] = ()


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
                result = body.get("analyzeResult")
                if not result:
                    raise OcrUnavailable("Azure answered succeeded with no result")
                return AzureLayout.model_validate(result)
            if status not in ("notStarted", "running"):
                raise OcrUnavailable(f"Azure analyze {status or 'ended without a status'}")
    except (SourceBlocked, UnsafeTarget) as error:
        # The exception's own text only: it carries a status code, never the request headers.
        raise OcrUnavailable(f"Azure unreachable: {error}") from error
    except ValidationError as error:
        raise OcrUnavailable("Azure answered outside the layout schema") from error
    except ValueError as error:  # a 200 whose body is not JSON (JSONDecodeError)
        raise OcrUnavailable("Azure answered with an unreadable body") from error
    raise OcrUnavailable("Azure analyze timed out")
