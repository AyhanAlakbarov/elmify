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

`--prepare` / `op: prepare` answers a file or one refusal (each part may name its `pages`):
unreadable (also: a part whose base64 does not decode, or pages it does not have) |
encrypted | signed | active_content | pages | too_large | image_too_large | too_large_to_return.

`--crop` / `op: crop` cuts boxes out of one page as PNGs, for the student to compare a doubtful
value with the original (transcript plan 3a): the upload is untrusted bytes and is rendered here,
never beside the app's secrets.

usage: python read_pages.py < upload  |  python read_pages.py --inspect < upload  |
       python read_pages.py --prepare < {parts, target} json  |
       python read_pages.py --flatten N < upload  |
       python read_pages.py --crop < {inline, page, boxes, dpi} json  |
       Lambda: read_pages.handler (`op: inspect` for the upload check, `op: prepare` for a
       co-pilot file, `op: flatten` for a diploma's or certificate's pictures, `op: crop` for a
       transcript cell's picture)
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import io
import json
import os
import sys
from collections.abc import Callable

import pdfplumber
import pypdfium2
import pypdfium2.raw as pdfium_c
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
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
    kind = _type(data)
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

#: A synchronous Lambda answer is capped at 6 MB and base64 grows by a third.
#: ponytail: bigger bundles need a write-only output prefix for this function.
RETURN_MAX = 4_000_000
MAX_PARTS = 20
#: Never below a 1,650 px long side (about 150 dpi on A4): past that a scan is hard to read
#: and the answer is `too_large`, not a smaller picture.
_JPEG_STEPS = ((2400, 85), (2000, 75), (1650, 70), (1650, 60), (1650, 50))
#: Pillow's own decompression-bomb guard, set once so no entry point depends on call order.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class _Refuse(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _type(data: bytes) -> str | None:
    return next((name for magic, name in ALLOWED_TYPES if data.startswith(magic)), None)


def _opened(data: bytes) -> PdfReader:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise _Refuse("encrypted")
    return reader


def _signed(data: bytes) -> bool:
    """A PDF carrying a signature: a /ByteRange in the raw bytes, /Perms, an AcroForm with
    SigFlags, or any signature field that holds a value (the signature dictionary may sit in
    a compressed object stream, where no literal /ByteRange shows)."""
    root = _opened(data).trailer["/Root"]
    if b"/ByteRange" in data or "/Perms" in root:
        return True
    form = _resolved(root.get("/AcroForm"))
    if not isinstance(form, DictionaryObject):
        return False
    if _resolved(form.get("/SigFlags")):
        return True
    seen: set[int] = set()
    stack = [(f, None) for f in _resolved(form.get("/Fields")) or []]
    while stack and len(seen) < MAX_OBJECTS:
        ref, inherited = stack.pop()
        field = _resolved(ref)
        if id(field) in seen or not isinstance(field, DictionaryObject):
            continue
        seen.add(id(field))
        kind = _resolved(field.get("/FT")) or inherited
        if kind == "/Sig" and field.get("/V") is not None:
            return True
        stack.extend((kid, kind) for kid in _resolved(field.get("/Kids")) or [])
    return False


def _check_size(width: float, height: float, scale: float = 1.0) -> None:
    if width * height * scale**2 > MAX_PIXELS:
        raise _Refuse("image_too_large")


def _image(data: bytes) -> Image.Image:
    """The image as stored, its pixel count checked from the header before anything is
    decoded."""
    image = Image.open(io.BytesIO(data))
    _check_size(*image.size)
    return image


def _flat(data: bytes) -> Image.Image:
    """An upright RGB image: EXIF orientation applied, transparency composed onto white."""
    return _rgb(ImageOps.exif_transpose(_image(data)))


def _rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        return Image.alpha_composite(white, rgba).convert("RGB")
    return image.convert("RGB")


def _jpeg(image: Image.Image, cap: int | None) -> bytes | None:
    for side, quality in _JPEG_STEPS:
        copy = image.copy()
        copy.thumbnail((side, side))
        out = io.BytesIO()
        copy.save(out, "JPEG", quality=quality, optimize=True)
        if cap is None or out.tell() <= cap:
            return out.getvalue()
    return None


def _as_pdf(data: bytes, kind: str) -> bytes:
    if kind == "application/pdf":
        return data
    out = io.BytesIO()
    _flat(data).save(out, "PDF", resolution=150)
    return out.getvalue()


def _merged(pdfs: list[bytes], pages: list[list[int] | None] | None = None) -> bytes:
    writer = PdfWriter()
    for pdf, selection in zip(pdfs, pages or [None] * len(pdfs), strict=True):
        reader = _opened(pdf)
        if selection is None:
            writer.append(reader)
            continue
        if any(not 1 <= n <= len(reader.pages) for n in selection):
            raise _Refuse("unreadable")  # the stored pages do not describe this file
        writer.append(reader, pages=[n - 1 for n in selection])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _check_embedded(writer: PdfWriter) -> None:
    """Refuse a page image whose declared size would be decoded into a huge bitmap."""
    for page in writer.pages:
        xobjects = _resolved(_resolved(page.get("/Resources", {})).get("/XObject", {}))
        for ref in xobjects.values():
            xobject = _resolved(ref)
            if xobject.get("/Subtype") == "/Image":
                _check_size(
                    _resolved(xobject.get("/Width", 0)),
                    _resolved(xobject.get("/Height", 0)),
                )


def _shrunk_pdf(pdf: bytes, cap: int) -> bytes | None:
    """Re-encode each page image down the JPEG steps until the file fits."""
    for side, quality in _JPEG_STEPS:
        writer = PdfWriter(clone_from=_opened(pdf))
        _check_embedded(writer)
        for page in writer.pages:
            for image in page.images:
                shrunk = image.image.convert("RGB")
                shrunk.thumbnail((side, side))
                image.replace(shrunk, quality=quality)
            page.compress_content_streams()
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        out = io.BytesIO()
        writer.write(out)
        if out.tell() <= cap:
            return out.getvalue()
    return None


def _answer(body: bytes, content_type: str) -> dict:
    if len(body) > RETURN_MAX:
        return {"refused": "too_large_to_return"}
    return {"content_type": content_type, "sha256": hashlib.sha256(body).hexdigest(),
            "body": base64.b64encode(body).decode()}


def _whole(part: bytes, kind: str | None, selection: list[int] | None) -> bool:
    """No selection, or one naming every page of the file in order."""
    if selection is None:
        return True
    count = len(_opened(part).pages) if kind == "application/pdf" else 1
    return selection == list(range(1, count + 1))


def prepare(parts: list[bytes], target: dict, pages: list[list[int] | None] | None = None) -> dict:
    """One file that meets `target`, or a refusal naming why (plan 4, Task 4).

    `pages`, one entry per part: the 1-based pages of that file to take, in order, or None
    for all of them (a transcript merge takes each file's live pages only; an image is one
    page). A selection that leaves out a page changes the file, so the rules for a file that
    must change apply to it.

    Refusals: unreadable | encrypted | signed | active_content | pages | too_large |
    image_too_large | too_large_to_return. Never rewrites what already fits, and never
    rewrites a signed PDF.
    """
    if len(parts) > MAX_PARTS or any(len(p) > MAX_BYTES for p in parts):
        return {"refused": "too_large"}
    kinds = [_type(p) for p in parts]
    if not parts or None in kinds:
        return {"refused": "unreadable"}
    selections = pages if pages is not None else [None] * len(parts)
    if len(selections) != len(parts):
        return {"refused": "unreadable"}
    try:
        pdfs = [p for p, k in zip(parts, kinds, strict=True) if k == "application/pdf"]
        # A PDF that opens with the empty password (owner password only) may be returned
        # as it is; one that needs a real password never.
        protected = False
        for pdf in pdfs:
            reader = PdfReader(io.BytesIO(pdf))
            if reader.is_encrypted:
                if not reader.decrypt(""):
                    return {"refused": "encrypted"}
                protected = True
        want, cap = target.get("format"), target.get("max_bytes")
        allowed = {"PDF": {"application/pdf"}, "JPG": {"image/jpeg"},
                   "PDF_OR_JPG": {"application/pdf", "image/jpeg"}}.get(want)
        for part, kind, selection in zip(parts, kinds, selections, strict=True):
            if kind != "application/pdf" and selection not in (None, [1]):
                return {"refused": "unreadable"}  # an image is one page
        whole = all(_whole(p, k, sel) for p, k, sel in zip(parts, kinds, selections, strict=True))
        if len(parts) == 1 and whole and (allowed is None or kinds[0] in allowed) and (
                cap is None or len(parts[0]) <= cap):
            return _answer(parts[0], str(kinds[0]))
        # The file must change from here on.
        if protected:
            return {"refused": "encrypted"}
        if any(_signed(p) for p in pdfs):
            return {"refused": "signed"}
        if any(_active_content(p) for p in pdfs):
            return {"refused": "active_content"}
        # A PDF stays a PDF unless JPG is demanded; an image becomes a JPEG
        # unless PDF is demanded. Several parts are always one PDF.
        if len(parts) > 1 or not whole or want == "PDF" or (
                want != "JPG" and kinds[0] == "application/pdf"):
            if len(parts) > 1 and want == "JPG":
                return {"refused": "pages"}
            merged = _merged([_as_pdf(p, str(k)) for p, k in zip(parts, kinds, strict=True)],
                             [sel if k == "application/pdf" else None
                              for k, sel in zip(kinds, selections, strict=True)])
            if len(PdfReader(io.BytesIO(merged)).pages) > MAX_PAGES:
                return {"refused": "pages"}
            fitted = merged if cap is None or len(merged) <= cap else _shrunk_pdf(merged, cap)
            if fitted is None:
                return {"refused": "too_large"}
            return _answer(fitted, "application/pdf")
        if kinds[0] == "application/pdf":
            if _has_huge_image(parts[0]):
                raise _Refuse("image_too_large")
            document = pypdfium2.PdfDocument(parts[0])
            if len(document) != 1:
                return {"refused": "pages"}
            _check_size(*document[0].get_size(), scale=150 / 72)
            image = document[0].render(scale=150 / 72).to_pil().convert("RGB")
        else:
            image = _flat(parts[0])
        jpeg = _jpeg(image, cap)
        return {"refused": "too_large"} if jpeg is None else _answer(jpeg, "image/jpeg")
    except _Refuse as refusal:
        return {"refused": refusal.reason}
    except Image.DecompressionBombError:
        return {"refused": "image_too_large"}
    except Exception:
        # A malformed part is the file not being preparable, never a crash that
        # would read as OCR being unavailable -- and the message never carries
        # the document's text.
        return {"refused": "unreadable"}


#: Spec 2026-10-12 §5.3: a diploma or certificate goes to Azure as pictures of its pages, so
#: the text any reader sees is the text a person sees. 150 dpi keeps 8 pt type above Azure's
#: 12 px floor and four A4 pages well under a Lambda's 6 MB answer.
# ponytail: one fixed resolution; raise it if a real certificate's small print reads badly.
FLATTEN_DPI = 150
#: Azure rejects a side over 10,000 px; a page that renders larger is refused, not shrunk.
MAX_SIDE_PX = AZURE_MAX_SIDE
#: A Lambda answers at most 6 MB synchronously; the base64 of the pictures plus the visible text
#: must stay under this, or the page that tips it over is refused.
MAX_ANSWER_BYTES = 5_500_000
_HIDDEN_MODES = frozenset(
    {pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE, pdfium_c.FPDF_TEXTRENDERMODE_CLIP}
)
_FILL_MODES = frozenset({0, 2, 4, 6})
_STROKE_MODES = frozenset({1, 2, 5, 6})
MIN_VISIBLE_PT = 4.0
#: A colour at or above this luminance (0.95 of white) is white on a white page.
# ponytail: the visible layer assumes a light page, so white text on a dark band is doubtful there
# (fail closed). The picture is never filtered by colour: a near-white glyph on white leaves no
# ink anyway, and white-on-dark is real text Azure must read.
_NEAR_WHITE = 0.95 * 255


def _ink_visible(getter, raw) -> bool:  # noqa: ANN001 - a pdfium colour getter and object
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if not getter(raw, *(ctypes.byref(v) for v in (r, g, b, a))):
        return True  # a pattern or shading: not a flat colour, so assume it paints
    luminance = 0.299 * r.value + 0.587 * g.value + 0.114 * b.value
    return a.value > 0 and luminance < _NEAR_WHITE


def _size_pt(raw) -> float:  # noqa: ANN001 - a pdfium text object
    """The glyphs' height on the page: font size times the vertical scale of the object's full
    matrix (text matrix x CTM), so `1 Tf 12 0 0 12 Tm` is 12 pt and `3 Tf 200 Tz` is 3 pt.
    Horizontal scaling (Tz) does not make a line taller, so it is not counted."""
    size = ctypes.c_float()
    if not pdfium_c.FPDFTextObj_GetFontSize(raw, ctypes.byref(size)):
        return MIN_VISIBLE_PT
    matrix = pdfium_c.FS_MATRIX()
    if not pdfium_c.FPDFPageObj_GetMatrix(raw, ctypes.byref(matrix)):
        return float(size.value)
    return float(size.value * (matrix.c**2 + matrix.d**2) ** 0.5)


def _shown(raw) -> bool:  # noqa: ANN001 - a pdfium text object
    """Render mode and size only: is the object drawn, at a size a picture can show? This alone
    decides what is removed before rendering."""
    return (
        pdfium_c.FPDFTextObj_GetTextRenderMode(raw) not in _HIDDEN_MODES
        and _size_pt(raw) >= MIN_VISIBLE_PT
    )


def _text_object_painted(raw) -> bool:  # noqa: ANN001 - a pdfium text object
    """`_shown` plus colour, for the visible layer: would a person see these glyphs? Outlined
    text (modes 1 and 2) counts when its stroke is visible, whatever the fill."""
    mode = pdfium_c.FPDFTextObj_GetTextRenderMode(raw)
    return _shown(raw) and (
        (mode in _FILL_MODES and _ink_visible(pdfium_c.FPDFPageObj_GetFillColor, raw))
        or (mode in _STROKE_MODES and _ink_visible(pdfium_c.FPDFPageObj_GetStrokeColor, raw))
    )


_Box = tuple[float, float, float, float]


def _inside(box: _Box, crop: _Box) -> bool:
    """Whether a box (left, bottom, right, top) overlaps the crop box; both are in user space,
    so /Rotate and an offset /MediaBox do not matter."""
    return box[2] > crop[0] and box[0] < crop[2] and box[3] > crop[1] and box[1] < crop[3]


def _object_box(raw) -> tuple[float, float, float, float]:  # noqa: ANN001
    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    pdfium_c.FPDFPageObj_GetBounds(
        raw, *(ctypes.byref(v) for v in (left, bottom, right, top))
    )
    return left.value, bottom.value, right.value, top.value


def _remove_hidden(page: pypdfium2.PdfPage) -> None:
    """Delete every top-level text object a person could not see, so the picture and the visible
    text agree by construction (a 3 pt line is legible at 150 dpi, and Azure would read it).
    ponytail: text nested in a Form XObject is not removed here -- an accepted residual, still
    filtered out of `visible` and so only ever a doubtful value; descend if one is seen."""
    crop = page.get_cropbox()
    doomed = [
        obj for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_TEXT], max_depth=1)
        if not _shown(obj.raw) or not _inside(_object_box(obj.raw), crop)
    ]
    for obj in doomed:
        page.remove_obj(obj)
    if doomed:
        page.gen_content()


def visible_text(page: pypdfium2.PdfPage) -> str:
    """The page's characters a person can see: never render mode 3 (a scanner app's OCR
    layer), white on white, a font under 4 pt, or text outside the page box -- the forms
    hidden prompt injection takes (spec 2026-10-12 §5.3.4). The rendered image, not this
    filter, is the boundary Azure reads; this is the cross-check text's own boundary, so a
    hidden figure is at worst a doubtful one. Annotations and form-field values are not read.

    Residual, accepted by ruling: text nested in a Form XObject or an annotation is neither
    removed from the picture nor, in the case of nested text, hidden here. The uploader is the
    student, who can already set any value; an injection can at most mark proven a value the
    student could type, and proven never means genuine."""
    textpage = page.get_textpage()
    crop = page.get_cropbox()
    out = []
    for index in range(pdfium_c.FPDFText_CountChars(textpage.raw)):
        char = chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, index))
        if char in "\r\n":
            out.append("\n")
        elif pdfium_c.FPDFText_IsGenerated(textpage.raw, index):
            out.append(char)  # a space pdfium inferred between words: it has no ink to judge
        elif _char_painted(textpage.raw, index, crop):
            out.append(char)
    return "".join(out)


def _char_painted(raw, index: int, crop: tuple[float, float, float, float]) -> bool:  # noqa: ANN001
    obj = pdfium_c.FPDFText_GetTextObject(raw, index)
    if obj and not _text_object_painted(obj):
        return False
    left, right, bottom, top = (ctypes.c_double() for _ in range(4))
    pdfium_c.FPDFText_GetCharBox(raw, index, *(ctypes.byref(v) for v in (left, right, bottom, top)))
    return _inside((left.value, bottom.value, right.value, top.value), crop)


def _has_huge_image(data: bytes) -> bool:
    """Any image XObject in the file -- a page's, a soft mask's, one nested in a form, a pattern
    or an annotation -- declaring more pixels than MAX_PIXELS. Read from the declared sizes,
    never decoded. A file pypdf cannot walk is refused too: nothing unchecked is rendered."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise _Refuse("encrypted")
        count = int(reader.trailer["/Size"])
        if count > MAX_OBJECTS:
            return True
        for number in range(1, count):
            node = reader.get_object(IndirectObject(number, 0, reader))
            if isinstance(node, DictionaryObject) and node.get("/Subtype") == "/Image":
                width = int(_resolved(node.get("/Width", 0)))
                height = int(_resolved(node.get("/Height", 0)))
                if width * height > MAX_PIXELS:
                    return True
    except _Refuse:
        raise
    except Exception:  # noqa: BLE001 - whatever pypdf raises, the answer is refuse
        return True
    return False


def _refused(reason: str, page: int) -> dict:
    return {"refused": {"reason": reason, "page": page}}


def flatten(data: bytes, max_pages: int) -> dict:
    """A PDF's first `max_pages` pages as an image-only PDF, plus each page's visible text.
    An image upload passes through untouched (the worker sends its own bytes).

    One page at a time is rendered and encoded, so memory holds one bitmap, never all of them;
    an embedded image, a rendered side or the answer that is too large is `page_too_large`."""
    if not data.startswith(b"%PDF"):
        checked = inventory(data)  # the size and resolution checks an image upload always gets
        if "refused" in checked:
            return checked
        return {"image_pdf": None, "pages": 1, "visible": []}
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            return _refused("encrypted", 1)
    except Exception:
        return _refused("unreadable", 1)
    try:
        document = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError:
        return _refused("unreadable", 1)
    try:
        if _has_huge_image(data):
            return _refused("page_too_large", 1)
    except _Refuse as refusal:
        return _refused(refusal.reason, 1)
    scale = FLATTEN_DPI / 72
    writer = PdfWriter()
    visible: list[str] = []
    size = 0
    for number in range(min(len(document), max_pages)):
        page = document[number]
        width, height = page.get_size()
        if (
            width * height * scale**2 > MAX_PIXELS
            or max(width, height) * scale > MAX_SIDE_PX
        ):
            return _refused("page_too_large", number + 1)
        _remove_hidden(page)
        visible.append(visible_text(page))
        picture = page.render(scale=scale).to_pil().convert("RGB")
        buffer = io.BytesIO()
        picture.save(buffer, format="PDF", resolution=FLATTEN_DPI, quality=80)
        del picture
        size += len(buffer.getvalue())
        if size * 4 // 3 + len(json.dumps(visible)) > MAX_ANSWER_BYTES:
            return _refused("page_too_large", number + 1)
        writer.append(PdfReader(buffer))
    if not visible:
        return _refused("unreadable", 1)
    merged = io.BytesIO()
    writer.write(merged)
    image_pdf = base64.b64encode(merged.getvalue()).decode()
    if len(image_pdf) + len(json.dumps(visible)) > MAX_ANSWER_BYTES:
        return _refused("page_too_large", len(visible))
    return {"image_pdf": image_pdf, "pages": len(visible), "visible": visible}


#: Each box is padded by this fraction of the page on every side, so a cell whose polygon hugs its
#: text still shows its borders.
CROP_PAD = 0.02
CROP_MAX_WIDTH = 1600
#: A cell is one line of print: this keeps every digit legible and a phone photo's crop small,
#: so a page full of doubtful rows still fits one reply.
CROP_MAX_HEIGHT = 300
#: The most one reply may carry; Lambda's own limit for a synchronous answer is 6 MB.
CROP_RETURN_MAX = RETURN_MAX
#: How far the rendered page's width/height may differ from the reader's before the two are
#: taken to be different frames (a 90-degree EXIF or /Rotate turn swaps them).
CROP_ASPECT_TOLERANCE = 0.10
#: ponytail: two cells for each doubtful row of one page; raise with a page that needs more.
MAX_CROPS = 60
CROP_DPI = (72, 300)


#: EXIF orientations that only turn a photo a quarter turn; 2, 3, 4, 5 and 7 mirror it or turn it
#: half way, which the page's shape cannot tell apart from the stored frame. Any other value
#: (0 "undefined", 9...) means nothing and is ignored, as exif_transpose ignores it.
_QUARTER_TURN_EXIF = frozenset({6, 8})
_AMBIGUOUS = "orientation ambiguous: the file mirrors the page or turns it half way"


def _close(size: tuple[float, float], aspect: float) -> bool:
    return abs(size[0] / size[1] / aspect - 1) <= CROP_ASPECT_TOLERANCE


def _page_frame(data: bytes, page: int, dpi: int, aspect: float | None) -> Image.Image:
    """The page in the frame the reader saw. When the file turns the page a quarter turn (EXIF
    6/8, /Rotate 90/270) the reader may have seen it turned or as stored; the one whose shape
    matches `aspect` is chosen from the sizes alone, and only that one is decoded. A near-square
    page fits both and is refused, as is a file that mirrors the page or turns it half way:
    no picture, never one of the wrong area."""
    candidates: list[tuple[tuple[float, float], Callable[[], Image.Image]]]
    if _type(data) == "application/pdf":
        if _has_huge_image(data):
            raise _Refuse("image_too_large")
        document = pypdfium2.PdfDocument(data)
        if not 1 <= page <= len(document):
            raise ValueError("page out of range")
        pdf_page = document[page - 1]
        width, height = pdf_page.get_size()  # as shown, /Rotate applied
        _check_size(width, height, dpi / 72)
        rotation = pdf_page.get_rotation()

        def render(*, stored: bool = False) -> Image.Image:
            if stored:
                pdf_page.set_rotation(0)
            return pdf_page.render(scale=dpi / 72).to_pil().convert("RGB")

        if rotation == 180:
            raise ValueError(_AMBIGUOUS)
        candidates = [((width, height), render)]
        if rotation:
            candidates.append(((height, width), lambda: render(stored=True)))
    else:
        if page != 1:
            raise ValueError("page out of range: an image is one page")
        image = _image(data)
        orientation = image.getexif().get(0x0112, 1)
        if orientation not in range(2, 9):
            orientation = 1
        if orientation != 1 and orientation not in _QUARTER_TURN_EXIF:
            raise ValueError(_AMBIGUOUS)
        width, height = image.size
        candidates = [((width, height), lambda: _rgb(image))]
        if orientation != 1:
            candidates.insert(
                0, ((height, width), lambda: _rgb(ImageOps.exif_transpose(image)))
            )
    if aspect is not None:
        candidates = [c for c in candidates if _close(c[0], aspect)]
        if not candidates:
            raise ValueError("orientation differs from the reader's")
        if len(candidates) > 1:
            raise ValueError(_AMBIGUOUS)
    return candidates[0][1]()


#: Image.transpose operations that undo a page read turned by k quarter turns clockwise.
_UPRIGHT = {1: Image.Transpose.ROTATE_90, 2: Image.Transpose.ROTATE_180,
            3: Image.Transpose.ROTATE_270}


def _box(box: object) -> tuple[float, float, float, float]:
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("a box is [left, top, right, bottom]")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box):
        raise ValueError("a box holds numbers")
    left, top, right, bottom = (float(v) for v in box)
    if right <= left or bottom <= top:
        raise ValueError("a box has no area")
    return left, top, right, bottom


def crop(
    data: bytes, page: int, boxes: list, dpi: int, aspect: float | None = None,
    angle: float | None = None,
) -> dict:
    """Each box (fractions of the page) cut out of page `page` (1-based) as a greyscale base64
    PNG, in box order. A box is padded by CROP_PAD and clamped to the page, then scaled to fit
    CROP_MAX_WIDTH x CROP_MAX_HEIGHT. `aspect` is the page's width/height as the reader measured
    it, and picks the frame the reader saw when the file turns the page (`_page_frame`).
    `angle` is the reader's measure of how far the text is turned clockwise: each picture is
    turned back by the nearest quarter turn, so a page photographed upside down or
    sideways still gives an upright picture. Anything malformed is a ValueError, never a
    guess."""
    if not isinstance(dpi, int) or isinstance(dpi, bool) or not CROP_DPI[0] <= dpi <= CROP_DPI[1]:
        raise ValueError("dpi out of range")
    if not isinstance(page, int) or isinstance(page, bool):
        raise ValueError("page is a number")
    if not isinstance(boxes, list) or not 1 <= len(boxes) <= MAX_CROPS:
        raise ValueError(f"between 1 and {MAX_CROPS} boxes")
    wanted = [_box(box) for box in boxes]
    if angle is not None and (
        not isinstance(angle, (int, float)) or isinstance(angle, bool) or not -180 <= angle <= 180
    ):
        raise ValueError("angle is a number of degrees between -180 and 180")
    if aspect is not None and (
        not isinstance(aspect, (int, float)) or isinstance(aspect, bool) or aspect <= 0
    ):
        raise ValueError("aspect is a positive number")
    try:
        image = _page_frame(data, page, dpi, aspect)
    except _Refuse as refusal:
        raise ValueError(refusal.reason) from refusal
    width, height = image.size
    turn = _UPRIGHT.get(round((angle or 0) / 90) % 4)
    out = []
    size = 0
    for left, top, right, bottom in wanted:
        piece = image.crop((
            max(0, int((left - CROP_PAD) * width)),
            max(0, int((top - CROP_PAD) * height)),
            min(width, int((right + CROP_PAD) * width)),
            min(height, int((bottom + CROP_PAD) * height)),
        ))
        if turn is not None:
            piece = piece.transpose(turn)
        piece = piece.convert("L")
        piece.thumbnail((CROP_MAX_WIDTH, CROP_MAX_HEIGHT))
        buffer = io.BytesIO()
        piece.save(buffer, format="PNG", optimize=True)
        out.append(base64.b64encode(buffer.getvalue()).decode())
        size += len(out[-1])
        if size > CROP_RETURN_MAX:
            raise ValueError("too_large_to_return")
    return {"crops": out}


def handler(event: dict, context: object, s3=None) -> dict:  # noqa: ANN001 - a boto3 client
    """Read the one cleared upload the worker names. The bucket is this function's own
    configuration, so a caller chooses which upload is read, never which bucket.

    The event carries the object key and the version GuardDuty scanned; `op: inspect` runs the
    upload check instead of the page inventory."""
    if event.get("op") == "prepare":
        if s3 is None:
            import boto3

            s3 = boto3.client("s3")
        parts = []
        for part in event["parts"]:
            if "inline" in part:
                try:
                    parts.append(base64.b64decode(part["inline"], validate=True))
                except ValueError:
                    return {"refused": "unreadable"}
                continue
            if not part.get("version_id"):
                raise ValueError("no version_id: only the scanned version of an upload is read")
            body = s3.get_object(
                Bucket=os.environ["DOCUMENT_BUCKET"],
                Key=part["key"],
                VersionId=part["version_id"],
                Range=f"bytes=0-{MAX_BYTES}",
            )["Body"].read()
            if len(body) > MAX_BYTES:
                return {"refused": "too_large"}
            parts.append(body)
        return prepare(parts, event["target"], [p.get("pages") for p in event["parts"]])
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
    if event.get("op") == "flatten":
        return flatten(body, int(event.get("max_pages", 4)))
    if event.get("op") == "crop":
        return crop(body, event.get("page"), event.get("boxes"), event.get("dpi"),
                    event.get("aspect"), event.get("angle"))
    return inventory(body)


if __name__ == "__main__":
    # --prepare reads several base64 parts in a JSON envelope, so its limit is wider.
    prepare_limit = MAX_PARTS * MAX_BYTES * 4 // 3 + 1_000_000
    limit = {
        "--prepare": prepare_limit,
        "--crop": MAX_BYTES * 4 // 3 + 100_000,
    }.get(" ".join(sys.argv[1:]), MAX_BYTES)
    data = sys.stdin.buffer.read(limit + 1)
    if sys.argv[1:] == ["--crop"]:
        if len(data) > limit:
            raise SystemExit("ValueError: object is larger than a transcript")
        envelope = json.loads(data)
        upload = base64.b64decode(envelope["inline"], validate=True)
        print(json.dumps(crop(upload, envelope.get("page"), envelope.get("boxes"),
                              envelope.get("dpi"), envelope.get("aspect"),
                              envelope.get("angle"))))
        raise SystemExit(0)
    if sys.argv[1:] == ["--prepare"]:
        envelope = json.loads(data)
        try:
            decoded = [base64.b64decode(p["inline"], validate=True) for p in envelope["parts"]]
        except ValueError:
            print(json.dumps({"refused": "unreadable"}))
            raise SystemExit(0)
        print(json.dumps(prepare(decoded, envelope["target"],
                                 [p.get("pages") for p in envelope["parts"]])))
        raise SystemExit(0)
    if sys.argv[1:] == ["--inspect"]:
        if len(data) > MAX_BYTES:
            # as the Lambda: an oversized upload is the check not answering, never a verdict
            raise SystemExit("ValueError: object is larger than a transcript")
        print(json.dumps(inspect(data)))
    elif sys.argv[1:2] == ["--flatten"]:
        print(json.dumps(flatten(data, int(sys.argv[2])) if len(data) <= MAX_BYTES else
                         {"refused": {"reason": "unreadable", "page": 1}}))
    else:
        print(json.dumps(inventory(data) if len(data) <= MAX_BYTES else
                         {"refused": {"reason": "unreadable", "page": 1}}))
