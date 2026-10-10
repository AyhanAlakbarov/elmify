"""Release-time document hygiene.

Implements ``phased requirements.md`` 4.2.3: strip toolchain metadata from
generated files and normalise text before rendering. Hygiene only -- nothing
here removes or obscures signals that a document was produced with AI
assistance, which 4.2 and 4.2.2 continue to prohibit.
"""

import re
import unicodedata
import zipfile
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import IndirectObject

from .vendor.text_unicode import clean_text

# Invisible-character hygiene is delegated to the vendored Layer A cleaner
# (apps/documents/vendor/text_unicode.py): it is script-aware where a flat strip
# table cannot be. U+200C/U+200D are load-bearing in Persian, Arabic and
# Devanagari and inside emoji ZWJ sequences, so removing them unconditionally --
# which this module used to do -- silently rewrote applicant names.

# The four the vendored cleaner does not cover: it handles space homoglyphs and
# the soft hyphen, but not these dashes or the line/paragraph separators.
_REPLACE_CHARS = {
    0x2011: "-",  # non-breaking hyphen
    0x2012: "-",  # figure dash
    0x2028: "\n",  # line separator
    0x2029: "\n",  # paragraph separator
}

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_MOJIBAKE_MARKERS = ("Ã", "â€", "Â")


def _repair_mojibake(text: str) -> str:
    """Repair UTF-8 bytes that were decoded as cp1252 (``Bachelorâ€™s``).

    Applies only when the whole string round-trips cleanly through
    cp1252-encode / utf-8-decode -- any character outside cp1252 aborts the
    repair and returns the input unchanged. That is not an absolute
    guarantee against corrupting correctly-encoded text: a marker character
    (``Â``/``Ã``) immediately followed by a Latin-1 symbol in U+00A0-U+00BF,
    e.g. ``Â©``, round-trips into a merged character (``©``) even though the
    input was never mojibake. Accepted as a rare, low-severity edge case.
    """
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text
    return repaired if "�" not in repaired else text


def normalize_text(text: str) -> str:
    """Return ``text`` with invisible, control and mangled characters removed.

    Letters and diacritics are never touched: applicant and institution names
    in any script survive unchanged.
    """
    if not text:
        return text
    text = _repair_mojibake(text)
    # Normalise line endings before the whitespace passes below: they match
    # "\n" directly, so a stray "\r" (CRLF or lone CR from older Mac-style
    # producers) would make both passes silently no-op. A lone "\r" becomes
    # "\n" rather than being dropped, since it is itself a line break.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    # aggressive_homoglyphs stays off: folding Cyrillic/Greek lookalikes would
    # corrupt legitimate names, which this function promises not to do.
    text, _stats = clean_text(text, aggressive_homoglyphs=False)
    text = text.translate(_REPLACE_CHARS)
    text = _CONTROL_CHARS.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Typographic punctuation folded to ASCII for destinations with a narrow
# charset -- portal form fields that mangle non-ASCII. Letters are never
# touched: folding a name would corrupt it.
_ASCII_PUNCTUATION = {
    0x2018: "'",
    0x2019: "'",
    0x201A: "'",
    0x201B: "'",
    0x201C: '"',
    0x201D: '"',
    0x201E: '"',
    0x2032: "'",  # prime
    0x2033: '"',  # double prime
    0x2013: "-",  # en dash
    0x2014: "-",  # em dash
    0x2026: "...",  # horizontal ellipsis
    0x2212: "-",  # minus sign
    0x00AB: '"',  # left guillemet
    0x00BB: '"',  # right guillemet
}


def to_ascii_punctuation(text: str) -> str:
    """Fold typographic punctuation to ASCII for narrow-charset destinations.

    Call this only for ``FIELD_MAPPED`` portal exports and funder templates
    that need it -- PDF variants keep typographic punctuation. Letters and
    diacritics are never altered.
    """
    if not text:
        return text
    return text.translate(_ASCII_PUNCTUATION)


def scrub_pdf_metadata(data: bytes) -> bytes:
    """Return ``data`` with its document info dictionary and XMP packet removed.

    Page content is untouched. Raises ``ValueError`` if the bytes are not a
    readable PDF -- failing loudly beats silently releasing an unscrubbed file.

    Deleting the ``/Metadata`` catalog key alone is not enough: pypdf's
    writer serializes every object in its table regardless of whether the
    catalog still references it, so the XMP stream's bytes would survive in
    the output. The slot is nulled out too, mirroring how pypdf's own
    ``metadata = None`` setter frees the Info dictionary's slot.
    """
    try:
        writer = PdfWriter(clone_from=BytesIO(data))
    except Exception as exc:  # pypdf raises several unrelated types here
        raise ValueError("not a readable PDF") from exc

    writer.metadata = None
    root = writer.root_object
    metadata_ref = root.raw_get("/Metadata") if "/Metadata" in root else None
    if metadata_ref is not None:
        del root["/Metadata"]
        if isinstance(metadata_ref, IndirectObject):
            # Deliberate private-API use, pinned to pypdf>=6.16,<7: this
            # mirrors pypdf's own internal `_info` setter, which frees a
            # slot in the writer's object table the same way. There is no
            # public API for "null out this indirect object" -- do not
            # "clean up" without re-checking pypdf's writer internals first.
            writer._objects[metadata_ref.idnum - 1] = None

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


_DOCX_RSIDS_BLOCK = re.compile(rb"<w:rsids>.*?</w:rsids>", re.S)
_DOCX_RSID_ELEMENT = re.compile(rb'<w:rsid\s+w:val="[^"]*"\s*/>')
_DOCX_RSID_ATTR = re.compile(rb'\s+w:rsid[A-Za-z]*="[^"]*"')
_DOCX_RSID_ROOT = re.compile(rb'\s+w:rsidRoot="[^"]*"')
_DOCX_AUTHOR = re.compile(rb'(\sw:author=")[^"]*(")')
_DOCX_INITIALS = re.compile(rb'(\sw:initials=")[^"]*(")')
_DOCX_LAST_MODIFIED = re.compile(rb"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>", re.S)


def _strip_editing_history(data: bytes) -> bytes:
    """Remove Word revision-save IDs and author names from one OOXML part.

    rsids are an optional Word optimisation for document compare and merge
    (ECMA-376); removing them does not affect rendering, and Word regenerates
    them on next save. Author values are blanked rather than deleted so the
    attributes stay schema-valid.
    """
    data = _DOCX_RSIDS_BLOCK.sub(b"", data)
    data = _DOCX_RSID_ELEMENT.sub(b"", data)
    data = _DOCX_RSID_ATTR.sub(b"", data)
    data = _DOCX_RSID_ROOT.sub(b"", data)
    data = _DOCX_AUTHOR.sub(rb"\1\2", data)
    data = _DOCX_INITIALS.sub(rb"\1\2", data)
    return _DOCX_LAST_MODIFIED.sub(b"", data)


# Well-formed but empty replacements. The parts must survive because
# _rels/.rels holds relationships pointing at them; deleting them would leave
# dangling references and an invalid package.
_EMPTY_DOCPROPS = {
    "docProps/core.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<cp:coreProperties"
        b' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        b' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        b' xmlns:dcterms="http://purl.org/dc/terms/"'
        b' xmlns:dcmitype="http://purl.org/dc/dcmitype/"'
        b' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>'
    ),
    "docProps/app.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<Properties"
        b' xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
        b' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>'
    ),
    "docProps/custom.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<Properties"
        b' xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"'
        b' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>'
    ),
}


def scrub_docx_metadata(data: bytes) -> bytes:
    """Return ``data`` with every ``docProps`` part replaced by an empty one
    and Word's editing history (rsids, author names) stripped from the rest.

    Every part and relationship is preserved so the OOXML package stays valid;
    only the identifying values are removed. Raises ``ValueError`` if the bytes
    are not a readable DOCX.
    """
    try:
        source = zipfile.ZipFile(BytesIO(data))
        if source.testzip() is not None:
            raise ValueError("not a readable DOCX")
    except zipfile.BadZipFile as exc:
        raise ValueError("not a readable DOCX") from exc

    out = BytesIO()
    with source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            replacement = _EMPTY_DOCPROPS.get(item.filename)
            if replacement is not None:
                member = replacement
            elif item.filename.endswith(".xml"):
                member = _strip_editing_history(source.read(item.filename))
            else:
                member = source.read(item.filename)
            target.writestr(item.filename, member)
    return out.getvalue()
