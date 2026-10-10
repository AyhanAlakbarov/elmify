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

It also runs the upload check (`inspect`): the type the bytes are and any active content a PDF
carries (dashboard spec §6, "Upload safety"), before the worker promotes an upload out of
quarantine.

usage: python read_pages.py < upload  |  python read_pages.py --inspect < upload  |
       Lambda: read_pages.handler (`op: inspect` for the upload check)
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys

import pdfplumber
import pypdfium2
import pypdfium2.raw as pdfium_c
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

#: ponytail: one transcript is a handful of pages; plan 2's per-cycle allowance (50) is the real
#: bound once it lands. A longer file is refused, never truncated.
MAX_PAGES = 20
MAX_BYTES = 10_000_000
#: A page whose image would exceed this is refused before anything reads it (a 10 MB file can
#: declare a 200-inch page; a PNG can declare 50,000 x 50,000 pixels).
MAX_PIXELS = 50_000_000
#: Kept from the earlier gate, measured on .superpowers/ocr-eval: Mersin's 127-129 ppi scan read
#: 0% on every engine, every scan that read well was 200-400 ppi.
MIN_SCAN_PPI = 150
#: Azure rejects an image with a side over 10,000 px or under 50 px (HTTP 400).
AZURE_MAX_SIDE = 10_000
AZURE_MIN_SIDE = 50
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
    cells = (cell for table in tables for row in table for cell in row)
    text = " ".join(lines) + " " + " ".join(cells)
    if len(text.strip()) < MIN_TEXT_CHARS:
        return False
    return "(cid:" not in text and "�" not in text


def scan_ppi(page: pypdfium2.PdfPage) -> float | None:
    """The lowest resolution of any image covering half the page's width or more (area-based)."""
    found = []
    for image in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3):
        left, bottom, right, top = image.get_bounds()
        if right - left < page.get_width() / 2 or top - bottom <= 0:
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
        # two parsers disagreeing means a truncated read: refuse, never zip it short
        if len(plumbed.pages) != len(document):
            raise Refused("unreadable", 1)
        both = zip(document, plumbed.pages, strict=True)
        for number, (page, plumbed_page) in enumerate(both, start=1):
            width, height = page.get_size()
            if width * height * (200 / 72) ** 2 > MAX_PIXELS:
                raise Refused("page_too_large", number)
            # a blank born-digital page (no characters, no picture) is skipped, never billed
            if not plumbed_page.chars and not any(
                page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3)
            ):
                continue
            found = plumbed_page.find_tables()
            tables = [
                [[" ".join((cell or "").split()) for cell in row] for row in table.extract()]
                for table in found
            ]
            # `lines` is the text outside any table; usability still judges the whole page
            boxes = [t.bbox for t in found]

            def outside(obj, boxes=boxes) -> bool:  # noqa: ANN001 - a pdfplumber object
                if "x0" not in obj:
                    return True
                x, y = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
                return not any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes)

            def split(text: str | None) -> list[str]:
                return [line for line in (text or "").splitlines() if line.strip()]

            lines = split(plumbed_page.filter(outside).extract_text())
            whole = split(plumbed_page.extract_text())
            # No table found (e.g. a borderless one): the rows would arrive as loose lines, so
            # the page goes to Azure, which reads tables from the image.
            if tables and text_layer_usable(whole, tables):
                pages.append({"number": number, "source": "text_layer", "scan_ppi": None,
                              "lines": lines, "tables": tables})
                continue
            ppi = scan_ppi(page)
            if ppi is not None and ppi < MIN_SCAN_PPI:
                raise Refused("low_resolution", number)
            pages.append(
                {"number": number, "source": "image", "scan_ppi": ppi, "lines": [], "tables": []}
            )
    if not pages:
        raise Refused("unreadable", 1)  # every page was blank
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
            if max(width, height) > AZURE_MAX_SIDE:
                raise Refused("page_too_large", 1)
            if min(width, height) < AZURE_MIN_SIDE:
                raise Refused("low_resolution", 1)
            pages = [_image_page()]
    except Refused as refusal:
        return {"refused": {"reason": refusal.reason, "page": refusal.page}}
    return {"pages": pages}


#: The three types an upload may be, by the file's own first bytes. The filename and the type the
#: browser declared are the client's to choose, so neither is ever read.
ALLOWED_TYPES = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)
#: A key whose presence is active content: a script, an embedded file, rich media, an XFA form.
_ACTIVE_KEYS = {
    "/JS": "/JS",
    "/JavaScript": "/JavaScript",
    "/EmbeddedFiles": "/EmbeddedFiles",
    "/EF": "/EmbeddedFile",
    "/RichMediaContent": "/RichMedia",
    "/XFA": "/XFA",
}
#: A key whose value makes it active: an action that runs a script or a program, an embedded
#: file stream, a rich-media annotation.
_ACTIVE_VALUES = {
    ("/S", "/JavaScript"): "/JavaScript",
    ("/S", "/Launch"): "/Launch",
    ("/Type", "/EmbeddedFile"): "/EmbeddedFile",
    ("/Subtype", "/RichMedia"): "/RichMedia",
}
_VALUE_KEYS = frozenset(key for key, _ in _ACTIVE_VALUES)
#: Actions that are ordinary on a click -- a link, a form's submit button -- and active content
#: when a trigger runs them with no click: an /OpenAction, or an /AA entry. Each reaches out of
#: the document (a URL, a remote file, a form post, imported data), so one that fires on open
#: or on a page view is a beacon. Named with the trigger, only when a trigger reaches them.
_TRIGGERED_ONLY = frozenset({"/SubmitForm", "/ImportData", "/GoToR", "/URI"})
#: The two triggers, named alongside whatever they run. An /OpenAction that only shows a page
#: (what a signed diploma carries) runs nothing and is not named.
_TRIGGERS = ("/OpenAction", "/AA")
#: ponytail: a walk past this many objects is refused rather than finished; a 10 MB file can
#: declare millions. Raise it if a real document is refused for size alone.
MAX_OBJECTS = 100_000
#: ponytail: the actions one trigger may run through /Next before the PDF is refused. Real
#: documents chain one or two; raise it if a real one is refused for this alone.
MAX_ACTIONS = 1_000


def inspect(data: bytes) -> dict:
    """The upload check (dashboard spec §6, "Upload safety"): the type the bytes are, and every
    kind of active content a PDF carries. Reads only; a PDF is never rewritten, because
    rewriting breaks a signed one (Azerbaijan's TMIS e-diplomas verify byte for byte).

    pypdf, not pdfium: pdfium can run a document's open action but cannot report one.
    """
    kind = next((name for magic, name in ALLOWED_TYPES if data.startswith(magic)), None)
    active = sorted(_active_content(data)) if kind == "application/pdf" else []
    # The digest of exactly the bytes judged: the worker copies only bytes with this digest.
    return {"type": kind, "active_content": active, "sha256": hashlib.sha256(data).hexdigest()}


def _active_content(data: bytes) -> set[str]:
    """Walk every object reachable from the trailer; nothing is executed or decompressed for
    its own sake. Fails closed: a PDF that cannot be parsed or decrypted is named, so it is
    refused, never passed."""
    found: set[str] = set()
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            return {"/Encrypt"}
        seen: set[tuple[int, int]] = set()
        stack: list[tuple[object, str]] = [(reader.trailer, "")]
        while stack:
            node, trigger = stack.pop()
            if isinstance(node, IndirectObject):
                if (node.idnum, node.generation) in seen:
                    continue
                seen.add((node.idnum, node.generation))
                if len(seen) > MAX_OBJECTS:
                    return found | {"/TooManyObjects"}
                node = node.get_object()
            if isinstance(node, DictionaryObject):
                for key, value in node.items():
                    named = _ACTIVE_KEYS.get(key)
                    if named is None and key in _VALUE_KEYS:
                        # `/S 7 0 R` naming /Launch is the same action as `/S /Launch`.
                        target = _resolved(value)
                        if isinstance(target, NameObject):
                            named = _ACTIVE_VALUES.get((key, target))
                    if named:
                        found.update({named, trigger} - {""})
                    if key in _TRIGGERS and (kinds := _triggered(key, value)):
                        found.update({*kinds, key})
                    stack.append((value, key if key in _TRIGGERS else trigger))
            elif isinstance(node, ArrayObject):
                stack.extend((item, trigger) for item in node)
    except Exception:
        # Not swallowed: whatever pypdf raises on a malformed file, the answer is "refuse".
        return found | {"/Unreadable"}
    return found


def _resolved(value: object) -> object:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _triggered(trigger: str, value: object) -> set[str]:
    """The _TRIGGERED_ONLY kinds among the actions `trigger` runs by itself: the action an
    /OpenAction names (not a destination array, which only shows a page), or every action in
    an /AA dictionary, and each one's /Next chain. Nothing else is followed -- a page an
    /OpenAction shows is not run by it, so the links on that page stay clicks."""
    value = _resolved(value)
    if not isinstance(value, DictionaryObject):
        return set()
    actions: list[object] = list(value.values()) if trigger == "/AA" else [value]
    kinds: set[str] = set()
    # Each action is followed once, so a /Next loop ends and every sibling is still reached;
    # a chain past the cap is refused, never answered from the part read so far.
    visited: set[object] = set()
    while actions:
        entry = actions.pop()
        identity = (
            (entry.idnum, entry.generation) if isinstance(entry, IndirectObject) else id(entry)
        )
        if identity in visited:
            continue
        if len(visited) >= MAX_ACTIONS:
            return kinds | {"/TooManyObjects"}
        visited.add(identity)
        action = _resolved(entry)
        if not isinstance(action, DictionaryObject):
            continue
        kind = _resolved(dict.get(action, "/S"))
        if isinstance(kind, NameObject) and kind in _TRIGGERED_ONLY:
            kinds.add(str(kind))
        following = dict.get(action, "/Next")
        if isinstance(_resolved(following), ArrayObject):
            actions.extend(_resolved(following))
        elif following is not None:
            actions.append(following)
    return kinds


def handler(event: dict, context: object, s3=None) -> dict:  # noqa: ANN001 - a boto3 client
    """Read the one cleared upload the worker names. The bucket is this function's own
    configuration, so a caller chooses which upload is read, never which bucket.

    The event carries the object key and the version GuardDuty scanned; `op: inspect` runs the
    upload check instead of the page inventory."""
    version = event.get("version_id")
    if not version:
        # The latest version is whatever the still-valid upload form wrote last, which nobody
        # scanned. Only the version GuardDuty scanned -- the worker names it -- is ever read.
        raise ValueError("no version_id: only the scanned version of an upload is read")
    if s3 is None:
        import boto3

        s3 = boto3.client("s3")
    body = s3.get_object(
        Bucket=os.environ["DOCUMENT_BUCKET"],
        Key=event["key"],
        VersionId=version,
        Range=f"bytes=0-{MAX_BYTES}",
    )["Body"].read()
    if len(body) > MAX_BYTES:
        # a crash is OCR being unavailable, never an empty transcript
        raise ValueError("object is larger than a transcript")
    if event.get("op") == "inspect":
        return inspect(body)
    return inventory(body)


if __name__ == "__main__":
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    if sys.argv[1:] == ["--inspect"]:
        if len(data) > MAX_BYTES:
            # as the Lambda: an oversized upload is the check not answering, never a verdict
            raise SystemExit("ValueError: object is larger than a transcript")
        print(json.dumps(inspect(data)))
    else:
        print(json.dumps(inventory(data) if len(data) <= MAX_BYTES else
                         {"refused": {"reason": "unreadable", "page": 1}}))
