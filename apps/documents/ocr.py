"""The seam: the page inventory, Azure for the scanned pages, and the quality gate.

The inventory (ocr/read_pages.py) runs where the upload is parsed safely -- in production an AWS
Lambda function (settings.OCR_FUNCTION_NAME, ocr/Dockerfile) invoked with the upload's key, in
subnets with no route to the internet; locally and in tests the same program runs as a child
process of this one: bytes on stdin, JSON on stdout, no secret in its environment. It reads text
layers and measures scans. Every "image" page is then read by Azure Document Intelligence
(azure_layout.py) and gated on Azure's own output; spec 2026-10-03-transcript-reader-redesign
section 4, 4.1 and 5. This module is the only place that knows which transport; the reader's
tests replace `inventory` and `read_inventory` wholesale.

The child-process posture is the pypdf path's, and it is a choice for development only: a
same-user process can read /proc/<parent>/environ whatever environment it was handed. Production
never runs the parser beside the app's secrets.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import subprocess  # nosec B404 -- a fixed argv and no shell; the upload travels as stdin data
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Self

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from apps.concierge.documents import DocumentUnavailable
from apps.concierge.models import DocumentVersion

from .azure_layout import AzureLayout, AzurePage, analyze_layout
from .file_rules import FileRule
from .ocr_errors import OcrUnavailable, PageRefused

logger = logging.getLogger(__name__)

#: The page inventory function's own Timeout (infra/template.yaml, OcrFunction): the inventory
#: measured well under a second a page; 60 s covers a cold start. Far under the scan queue's 900 s
#: visibility timeout, so a slow read is never redelivered while it is still running.
_TIMEOUT_SECONDS = 60


#: (left, top, right, bottom), each a fraction of the page.
Box = tuple[float, float, float, float]


def _box(polygon: Sequence[float], width: float, height: float) -> Box | None:
    """The polygon's axis-aligned bounding box as fractions of its page. A rotated photo's
    polygon is not a rectangle; its extremes still contain the cell."""
    if len(polygon) < 8 or not width or not height:
        return None
    xs, ys = polygon[0::2], polygon[1::2]
    return (
        round(min(xs) / width, 4),
        round(min(ys) / height, 4),
        round(max(xs) / width, 4),
        round(max(ys) / height, 4),
    )


class OcrPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The page's text lines outside any table, in reading order.
    lines: tuple[str, ...]
    #: Each table as rows of cell text; a cell that spans rows or columns fills its own
    #: top-left slot and leaves the rest blank.
    tables: tuple[tuple[tuple[str, ...], ...], ...]
    #: Same shape as `tables`: Azure's confidence for each cell (the lowest of its words), None for
    #: a blank cell and for every text-layer cell -- the document's own text has no reader doubt.
    cell_confidence: tuple[tuple[tuple[float | None, ...], ...], ...] = ()
    #: Same shape again: where each cell sits on its page, as fractions of the page's width and
    #: height, so nothing downstream needs the page's unit. None for a blank cell and every
    #: text-layer cell (no reader doubt, so nothing to show the student).
    cell_regions: tuple[tuple[tuple[Box | None, ...], ...], ...] = ()
    #: The page's width / height as Azure measured it: a crop rendered in another frame (an
    #: EXIF or /Rotate turn of 90 degrees) is refused instead of cutting the wrong area.
    page_aspect: float | None = None
    #: How far Azure found the text turned clockwise, in degrees: a page photographed upside down
    #: or sideways still gives an upright crop (the parser turns it back).
    page_angle: float | None = None
    source: Literal["text_layer", "azure"] = "text_layer"
    #: The Azure API version that produced this page; "" for a text-layer page.
    api_version: str = ""


class InventoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    source: Literal["text_layer", "image"]
    scan_ppi: float | None
    lines: tuple[str, ...]
    tables: tuple[tuple[tuple[str, ...], ...], ...]


class _Refusal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    page: int


class _Output(BaseModel):
    """Exactly one of a non-empty `pages` or a `refused` reason -- never neither, never both.

    `{}` and `{"pages": []}` would otherwise validate and the reader would return an empty
    tuple: an empty transcript with no refusal, which OcrUnavailable exists to prevent. A crash
    or a program that answers with nothing to say is unavailable, never quietly empty.
    """

    model_config = ConfigDict(extra="forbid")

    pages: tuple[InventoryPage, ...] = ()
    refused: _Refusal | None = None

    @model_validator(mode="after")
    def _exactly_one_answer(self) -> Self:
        if bool(self.pages) == (self.refused is not None):
            raise ValueError("answer must carry a non-empty pages or a refused reason, not both")
        return self


def _child_env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",  # nosec B108 -- the engine writes nothing there; it wants a HOME to exist
    }


#: The quality gate's starting floors (spec section 5); spec section 9 gate 3 sets them on degraded
#: pages. Text height: the earlier gate's measured floor, 12 px (SPbU's 10 px lines read 0%).
GATE_MIN_TEXT_PX = 12.0
#: Mean word confidence below which a page is refused as unreadable (Veryfi's review line, 0.8).
GATE_UNREADABLE_BELOW = 0.80
#: A word within this fraction of the page's width or height of an edge "touches" it;
#: this many touching words mean the page was cut off.
GATE_EDGE_FRACTION = 0.005
GATE_EDGE_WORDS = 3


def _height(polygon: tuple[float, ...]) -> float:
    """The word box's own height: point 0 to point 3 (x0,y0,x1,y1,x2,y2,x3,y3), so a sideways
    photo's word is measured across, not along its length."""
    return float(math.hypot(polygon[0] - polygon[6], polygon[1] - polygon[7]))


def _gate(page: AzurePage, scan_ppi: float | None) -> str | None:
    """The refusal reason for one Azure-read page, or None."""
    words = page.words
    # a PDF page is in inches: its pixel height needs the scan's ppi
    to_px = 1.0 if page.unit == "pixel" else scan_ppi
    if to_px is not None:
        heights = sorted(
            _height(w.polygon) * to_px for w in words if len(w.content) >= 3 and len(w.polygon) == 8
        )
        if heights and heights[len(heights) // 2] < GATE_MIN_TEXT_PX:
            return "text_too_small"
    if sum(w.confidence for w in words) / len(words) < GATE_UNREADABLE_BELOW:
        return "unreadable"
    dx, dy = page.width * GATE_EDGE_FRACTION, page.height * GATE_EDGE_FRACTION
    touching = sum(
        1
        for w in words
        if w.polygon
        and (
            min(w.polygon[0::2]) <= dx
                or max(w.polygon[0::2]) >= page.width - dx
            or min(w.polygon[1::2]) <= dy
            or max(w.polygon[1::2]) >= page.height - dy
        )
    )
    return "cut_off" if touching >= GATE_EDGE_WORDS else None


def _azure_page(layout: AzureLayout, page: AzurePage) -> OcrPage:
    tables: list[tuple[tuple[str, ...], ...]] = []
    confidences: list[tuple[tuple[float | None, ...], ...]] = []
    regions: list[tuple[tuple[Box | None, ...], ...]] = []
    in_tables: set[int] = set()
    for table in layout.tables:
        first = table.boundingRegions[0].pageNumber if table.boundingRegions else None
        # A table spanning pages carries a region per cell: each cell belongs to its own page.
        mine = [
            cell
            for cell in table.cells
            if (cell.boundingRegions[0].pageNumber if cell.boundingRegions else first)
            == page.pageNumber
        ]
        if not mine:
            continue
        top = min(cell.rowIndex for cell in mine)
        rows = max(cell.rowIndex for cell in mine) - top + 1
        grid = [[""] * table.columnCount for _ in range(rows)]
        conf: list[list[float | None]] = [[None] * table.columnCount for _ in range(rows)]
        boxes: list[list[Box | None]] = [[None] * table.columnCount for _ in range(rows)]
        for cell in mine:
            text = " ".join(cell.content.split())
            r = cell.rowIndex - top
            grid[r][cell.columnIndex] = text
            found = [
                w.confidence
                for w in page.words
                for span in cell.spans
                if span.offset <= w.span.offset < span.offset + span.length
            ]
            for span in cell.spans:
                in_tables.update(range(span.offset, span.offset + span.length))
            conf[r][cell.columnIndex] = min(found) if found and text else None
            if text and cell.boundingRegions:
                # `mine` holds only this page's cells, so `page` is the cell's own page.
                boxes[r][cell.columnIndex] = _box(
                    cell.boundingRegions[0].polygon, page.width, page.height
                )
        tables.append(tuple(tuple(row) for row in grid))
        confidences.append(tuple(tuple(row) for row in conf))
        regions.append(tuple(tuple(row) for row in boxes))
    lines = tuple(
        line.content
        for line in page.lines
        if line.content.strip() and not any(span.offset in in_tables for span in line.spans)
    )
    return OcrPage(
        lines=lines,
        tables=tuple(tables),
        cell_confidence=tuple(confidences),
        cell_regions=tuple(regions),
        page_aspect=round(page.width / page.height, 4) if page.width and page.height else None,
        page_angle=page.angle,
        source="azure",
        api_version=settings.AZURE_DI_API_VERSION,
    )


@dataclass(frozen=True)
class PageRead:
    """One inventoried page after reading: its page, the gate's refusal, or blank."""

    number: int
    page: OcrPage | None = None
    refusal: str | None = None
    #: Azure found no words: a blank back page, skipped rather than refused (plan 2).
    blank: bool = False


def inventory(document: DocumentVersion, content: bytes) -> tuple[InventoryPage, ...]:
    """The upload's pages as the isolated parser found them, before anything is billed."""
    if settings.OCR_FUNCTION_NAME:
        raw = _invoke(document.object_key, _scanned_version(document))
    else:
        raw = _run_child(content)
    try:
        output = _Output.model_validate_json(raw)
    except ValidationError as error:
        raise OcrUnavailable("unparseable output") from error
    if output.refused is not None:
        raise PageRefused(output.refused.reason, output.refused.page)
    return output.pages


def read_inventory(
    content: bytes,
    pages: tuple[InventoryPage, ...],
    *,
    locale: str | None = None,
    analyze: Callable[..., AzureLayout] = analyze_layout,
) -> tuple[PageRead, ...]:
    """Each inventoried page read: text-layer pages as they are, image pages through Azure and the
    gate. Only image pages are sent -- as the original bytes, with Azure's own page selector."""
    image_pages = [page for page in pages if page.source == "image"]
    read: dict[int, PageRead] = {}
    if image_pages:
        is_pdf = content.startswith(b"%PDF")  # the same sniff as the upload gate and the inventory
        selector = ",".join(str(p.number) for p in image_pages) if is_pdf else None
        layout = analyze(content, pages=selector, locale=locale)
        by_number = {page.pageNumber: page for page in layout.pages}
        for inventoried in image_pages:
            azure_page = by_number.get(inventoried.number)
            if azure_page is None and not is_pdf and len(pages) == 1 and layout.pages:
                azure_page = layout.pages[0]  # a bare image is one page, whatever Azure numbers it
            if azure_page is None:
                raise OcrUnavailable(f"Azure returned no page {inventoried.number}")
            if not azure_page.words:
                read[inventoried.number] = PageRead(inventoried.number, blank=True)
                continue
            reason = _gate(azure_page, inventoried.scan_ppi)
            read[inventoried.number] = (
                PageRead(inventoried.number, refusal=reason)
                if reason is not None
                else PageRead(inventoried.number, page=_azure_page(layout, azure_page))
            )
    return tuple(
        read[p.number]
        if p.source == "image"
        else PageRead(p.number, page=OcrPage(lines=p.lines, tables=p.tables, source="text_layer"))
        for p in pages
    )


def _lambda_client() -> Any:
    """Indirection for tests only. One attempt, never a retry: a retried invocation is a second
    full read of the same transcript, billed. The read timeout outlasts the function's own."""
    config = Config(
        read_timeout=_TIMEOUT_SECONDS + 30, connect_timeout=10, retries={"total_max_attempts": 1}
    )
    return boto3.client("lambda", config=config)


def _scanned_version(document: DocumentVersion) -> str:
    """The version the function may read. The key's latest version is whatever the
    still-valid upload form last wrote, which nobody scanned, so there is no default."""
    if not document.scanned_version:
        raise OcrUnavailable("no scanned version")
    return document.scanned_version


#: A timeout, memory blow-up or crash on this one file, or the parser's own "object is larger"
#: refusal; any other function error (env, permissions, import) is the deployment, i.e. an outage.
_JOB_ERROR_TYPES = frozenset(
    {"Sandbox.Timedout", "Runtime.OutOfMemory", "Runtime.ExitError", "ValueError"}
)


def _invoke(key: str, version: str, op: str = "", body: dict[str, Any] | None = None) -> bytes:
    try:
        event = body if body is not None else (
            {"key": key, "version_id": version} | ({"op": op} if op else {})
        )
        response = _lambda_client().invoke(
            FunctionName=settings.OCR_FUNCTION_NAME, Payload=json.dumps(event).encode()
        )
        # A botocore exception can surface here too (a dropped connection mid-stream), not
        # only from invoke() itself -- both must land as OcrUnavailable, never raw.
        payload: bytes = response["Payload"].read()
    except (BotoCoreError, ClientError) as error:
        raise OcrUnavailable(type(error).__name__) from error
    if "FunctionError" in response:
        # The error's type only: its message and stack trace can quote the document's text.
        error_type = json.loads(payload or b"{}").get("errorType", response["FunctionError"])
        logger.warning("OcrFunctionError error=%s", error_type)
        raise OcrUnavailable(
            f"function error {error_type}",
            kind="job" if error_type in _JOB_ERROR_TYPES else "outage",
        )
    return payload


def _run_child(content: bytes, *flags: str) -> bytes:
    try:
        # argv is two paths from settings and a fixed flag, never the upload
        done = subprocess.run(  # nosec B603
            [settings.OCR_PYTHON, str(settings.BASE_DIR / "ocr" / "read_pages.py"), *flags],
            input=content,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            env=_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        # This file outran the child, as Sandbox.Timedout on Lambda: the next file may not.
        raise OcrUnavailable(type(error).__name__, kind="job") from error
    except OSError as error:  # no interpreter to run: down for every file
        raise OcrUnavailable(type(error).__name__) from error
    if done.returncode != 0:
        # The exception's name only: a traceback's message can quote the document's text.
        last = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        logger.warning("OcrCrashed exit=%s error=%s", done.returncode, last[0].split(":")[0])
        # This file crashed the child, as Runtime.ExitError on Lambda.
        raise OcrUnavailable(f"exit {done.returncode}", kind="job")
    return done.stdout


class UploadVerdict(BaseModel):
    """ocr/read_pages.py::inspect's answer: the type the bytes are (None: not one of the three),
    and every kind of active content a PDF carries."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["application/pdf", "image/jpeg", "image/png"] | None
    active_content: tuple[str, ...]
    #: The digest of the bytes judged. The worker copies only bytes with this digest, so a
    #: verdict can never be carried over to bytes it was not about.
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def inspect_upload(document: DocumentVersion, content: bytes) -> UploadVerdict:
    """The upload check, run where the OCR runs: the isolated function (the key, never the
    bytes), or locally the same child with --inspect. Anything but a valid answer is
    OcrUnavailable -- an unchecked file is never treated as a clean one."""
    if settings.OCR_FUNCTION_NAME:
        raw = _invoke(document.object_key, _scanned_version(document), op="inspect")
    else:
        raw = _run_child(content, "--inspect")
    try:
        return UploadVerdict.model_validate_json(raw)
    except ValidationError as error:
        raise OcrUnavailable("unparseable output") from error


#: Enough for a printed digit to read clearly, far under the parser's page-size refusal.
CROP_DPI = 150


def crop_cells(
    document: DocumentVersion,
    page: int,
    boxes: Sequence[Box],
    *,
    aspect: float | None = None,
    angle: float | None = None,
) -> list[bytes]:
    """A PNG of each box on page `page` (1-based) of an upload, cut where uploads are parsed
    (transcript plan 3a): the upload is untrusted bytes and is never rendered in this process.
    Anything but one PNG per box is OcrUnavailable."""
    if document.state != "AVAILABLE":
        raise OcrUnavailable("upload no longer available")
    request: dict[str, Any] = {
        "op": "crop", "page": page, "boxes": [list(box) for box in boxes], "dpi": CROP_DPI
    }
    if aspect is not None:
        request["aspect"] = aspect
    if angle is not None:
        request["angle"] = angle
    if settings.OCR_FUNCTION_NAME:
        raw = _invoke(
            "", "", body={
                **request, "key": document.object_key, "version_id": _scanned_version(document)
            },
        )
    else:
        from .storage import read_upload

        try:
            content = read_upload(document)
        except (DocumentUnavailable, KeyError) as error:
            raise OcrUnavailable(type(error).__name__) from error
        envelope = {**request, "inline": base64.b64encode(content).decode()}
        raw = _run_child(json.dumps(envelope).encode(), "--crop")
    try:
        crops = [base64.b64decode(crop, validate=True) for crop in json.loads(raw)["crops"]]
    except (ValueError, KeyError, TypeError) as error:
        raise OcrUnavailable("unparseable output") from error
    if len(crops) != len(boxes) or not all(crop.startswith(b"\x89PNG") for crop in crops):
        raise OcrUnavailable("unparseable output")
    return crops


@dataclass(frozen=True)
class Part:
    upload: DocumentVersion | None = None  # read by the parser from its scanned version
    own: bytes = b""  # our generated document, sent inline
    #: The 1-based pages of this file to take, in order; None for all (a transcript merge
    #: takes each file's live TranscriptPage numbers).
    pages: tuple[int, ...] | None = None


class Prepared(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["application/pdf", "image/jpeg", "image/png"] | None = None
    sha256: str = ""
    body: bytes = b""
    refused: str = ""


#: Inline parts are our own documents (the request itself is capped at 6 MB), and the most the
#: parser hands back: a target above it is shrunk to it, not refused unshrunk.
INLINE_MAX = 4_000_000


def prepare_files(parts: Sequence[Part], target: FileRule) -> Prepared:
    """Plan 4: one file meeting `target`, built where untrusted files are parsed.
    Uploads travel as their scanned version's key; our own documents inline."""
    target_json = {
        "format": target.format,
        "max_bytes": target.max_bytes,
        "one_file": target.one_file,
    }
    if sum(len(p.own) for p in parts) > INLINE_MAX:
        return Prepared(refused="too_large")
    if settings.OCR_FUNCTION_NAME:
        if any(p.upload is not None and p.upload.state != "AVAILABLE" for p in parts):
            return Prepared(refused="unreadable")
        event_parts = [
            {
                **(
                    {"key": p.upload.object_key, "version_id": _scanned_version(p.upload)}
                    if p.upload is not None
                    else {"inline": base64.b64encode(p.own).decode()}
                ),
                **({"pages": list(p.pages)} if p.pages is not None else {}),
            }
            for p in parts
        ]
        raw = _invoke(
            "", "", body={"op": "prepare", "parts": event_parts, "target": target_json}
        )
    else:
        # Locally the child gets every part inline: the promoted copy is the same
        # bytes the scan cleared (promote_upload copies only the verdict's digest).
        from .storage import read_upload

        try:
            inline = [read_upload(p.upload) if p.upload is not None else p.own for p in parts]
        except (DocumentUnavailable, KeyError) as error:
            raise OcrUnavailable(type(error).__name__) from error
        envelope = {
            "parts": [
                {
                    "inline": base64.b64encode(b).decode(),
                    **({"pages": list(p.pages)} if p.pages is not None else {}),
                }
                for b, p in zip(inline, parts, strict=True)
            ],
            "target": target_json,
        }
        raw = _run_child(json.dumps(envelope).encode(), "--prepare")
    try:
        answer = json.loads(raw)
        if "refused" in answer:
            return Prepared(refused=str(answer["refused"]))
        body = base64.b64decode(answer["body"])
        if hashlib.sha256(body).hexdigest() != answer["sha256"]:
            raise OcrUnavailable("digest mismatch")
        if len(body) > INLINE_MAX:
            return Prepared(refused="too_large_to_return")
        if answer["content_type"] is None:
            raise OcrUnavailable("unparseable output")
        return Prepared(
            content_type=answer["content_type"],
            sha256=answer["sha256"],
            body=body,
        )
    except (ValueError, KeyError, TypeError, ValidationError) as error:
        raise OcrUnavailable("unparseable output") from error


class Flattened(BaseModel):
    """ocr/read_pages.py::flatten's answer (spec 2026-10-12 §5.3)."""

    model_config = ConfigDict(extra="forbid")

    #: Base64 of the image-only PDF, or None for an image upload (sent as it is).
    image_pdf: str | None = None
    pages: int = Field(ge=1)
    #: Each page's visible text, for a born-digital PDF's cross-check; () for an image.
    visible: tuple[str, ...] = ()

    def body(self, original: bytes) -> bytes:
        if not self.image_pdf:
            return original
        try:
            return base64.b64decode(self.image_pdf, validate=True)
        except ValueError as error:  # binascii.Error: an answer that is not base64 is no answer
            raise OcrUnavailable("unparseable output") from error


class _FlattenOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_pdf: str | None = None
    pages: int = 0
    visible: tuple[str, ...] = ()
    refused: _Refusal | None = None

    @model_validator(mode="after")
    def _exactly_one_answer(self) -> Self:
        if (self.pages > 0) == (self.refused is not None):
            raise ValueError("answer must carry pages or a refused reason, not both")
        return self


def flatten(document: DocumentVersion, content: bytes, *, max_pages: int) -> Flattened:
    """A diploma's or certificate's pages as pictures, through the isolated parser."""
    if settings.OCR_FUNCTION_NAME:
        raw = _invoke("", "", body={
            "key": document.object_key, "version_id": _scanned_version(document),
            "op": "flatten", "max_pages": max_pages,
        })
    else:
        raw = _run_child(content, "--flatten", str(max_pages))
    try:
        output = _FlattenOutput.model_validate_json(raw)
    except ValidationError as error:
        raise OcrUnavailable("unparseable output") from error
    if output.refused is not None:
        raise PageRefused(output.refused.reason, output.refused.page)
    return Flattened(image_pdf=output.image_pdf, pages=output.pages, visible=output.visible)
