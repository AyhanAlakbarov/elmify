import re
import zipfile
from io import BytesIO
from xml.dom import minidom

import pytest
from pypdf import PdfReader, PdfWriter

from apps.documents.hygiene import (
    normalize_text,
    scrub_docx_metadata,
    scrub_pdf_metadata,
    to_ascii_punctuation,
)


@pytest.mark.parametrize(
    ("label", "raw", "expected"),
    [
        ("zero_width_space", "Lead​ership", "Leadership"),
        ("soft_hyphen", "Uni­versity", "University"),
        ("bidi_override", "safe‮txt", "safetxt"),
        ("non_breaking_space", "5 years", "5 years"),
        ("non_breaking_hyphen", "TU‑Delft", "TU-Delft"),
        ("mojibake_apostrophe", "Bachelorâ€™s", "Bachelor’s"),
        ("mojibake_accent", "UniversitÃ© Paris", "Université Paris"),
        ("control_character", "Team\x07 lead", "Team lead"),
    ],
)
def test_normalize_text_cleans(label: str, raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_normalize_text_collapses_crlf_blank_lines_and_trailing_spaces() -> None:
    """CRLF must not defeat the "[ \\t]+\\n" and "\\n{3,}" collapse passes."""
    raw = "Education\r\n\r\n\r\n\r\nMSc Physics   \r\nTU Delft\r\n"
    assert normalize_text(raw) == "Education\n\nMSc Physics\nTU Delft"


def test_normalize_text_treats_lone_cr_as_line_break() -> None:
    """A lone CR (old Mac-style line ending) becomes a newline, not nothing --
    joining ``Line A`` and ``Line B`` into one word would be worse than the
    stray character it replaces."""
    assert normalize_text("Line A\rLine B") == "Line A\nLine B"


@pytest.mark.parametrize(
    "text",
    ["Łódź", "Aygün", "Češka", "2020–2024", "Café", "Bachelor’s degree", "“Summa”"],
)
def test_normalize_text_preserves_meaningful_characters(text: str) -> None:
    """Diacritics, non-Latin letters, en dashes and typographic quotes are content."""
    assert normalize_text(text) == text


def test_normalize_text_collapses_blank_lines_and_trims() -> None:
    assert normalize_text("Header   \n\n\n\nBody\n") == "Header\n\nBody"


def test_normalize_text_handles_empty() -> None:
    assert normalize_text("") == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bachelor’s", "Bachelor's"),
        ("“Summa”", '"Summa"'),
        ("2020–2024", "2020-2024"),
        ("Wait for it…", "Wait for it..."),
        ("−5", "-5"),
        ("«Summa»", '"Summa"'),
        ("", ""),
    ],
)
def test_to_ascii_punctuation_folds_typography(raw: str, expected: str) -> None:
    assert to_ascii_punctuation(raw) == expected


def test_to_ascii_punctuation_preserves_letters() -> None:
    """Only punctuation folds. Names must never be transliterated."""
    assert to_ascii_punctuation("Aygün Łódź") == "Aygün Łódź"


def _pdf_with_metadata() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata(
        {"/Producer": "SecretLib 9.2", "/Creator": "tehsil-agent", "/Author": "Orkhan"}
    )
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_scrub_pdf_metadata_removes_document_info() -> None:
    scrubbed = scrub_pdf_metadata(_pdf_with_metadata())
    reader = PdfReader(BytesIO(scrubbed))
    assert not reader.metadata
    # The reader API alone already let an XMP defect ship once (see
    # test_scrub_pdf_metadata_removes_xmp below) -- assert on the raw bytes
    # too, so a regression of the same shape can actually fail this test.
    assert b"Orkhan" not in scrubbed


_XMP_MARKER = b"SecretLib-XMP-Marker"


def _pdf_with_xmp() -> bytes:
    """PDF carrying a real XMP metadata stream, not just a document info dict.

    ``add_metadata`` (used by ``_pdf_with_metadata``) never creates an XMP
    packet, so a test built on it can't tell a working XMP scrub from a
    no-op. This fixture writes an actual ``/Metadata`` stream containing a
    marker so the assertion can check for its absence in the raw bytes.
    """
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.xmp_metadata = (
        b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/">'
        b"<pdf:Producer>" + _XMP_MARKER + b"</pdf:Producer>"
        b"</rdf:Description></rdf:RDF></x:xmpmeta>\n"
        b'<?xpacket end="w"?>'
    )
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_scrub_pdf_metadata_removes_xmp() -> None:
    scrubbed = scrub_pdf_metadata(_pdf_with_xmp())
    assert PdfReader(BytesIO(scrubbed)).xmp_metadata is None
    # The reader API alone is not proof: pypdf's writer serializes every
    # object in its table regardless of whether the catalog still points at
    # it, so the marker must also be gone from the raw output bytes.
    assert _XMP_MARKER not in scrubbed


def test_scrub_pdf_metadata_preserves_pages() -> None:
    scrubbed = scrub_pdf_metadata(_pdf_with_metadata())
    assert len(PdfReader(BytesIO(scrubbed)).pages) == 1


def test_scrub_pdf_metadata_rejects_non_pdf() -> None:
    with pytest.raises(ValueError, match="not a readable PDF"):
        scrub_pdf_metadata(b"this is not a pdf")


def _docx_with_metadata() -> bytes:
    """Minimal OOXML package carrying identifying document properties."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
        archive.writestr("word/document.xml", "<w:document>CURRICULUM VITAE</w:document>")
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:creator>Orkhan</dc:creator></cp:coreProperties>",
        )
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0"?><Properties '
            'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Application>SecretWriter</Application></Properties>",
        )
    return buffer.getvalue()


def test_scrub_docx_metadata_removes_identifying_values() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_metadata())
    with zipfile.ZipFile(BytesIO(scrubbed)) as archive:
        assert b"Orkhan" not in archive.read("docProps/core.xml")
        assert b"SecretWriter" not in archive.read("docProps/app.xml")


def test_scrub_docx_metadata_keeps_every_part() -> None:
    original = _docx_with_metadata()
    scrubbed = scrub_docx_metadata(original)
    with zipfile.ZipFile(BytesIO(original)) as before, zipfile.ZipFile(BytesIO(scrubbed)) as after:
        assert sorted(after.namelist()) == sorted(before.namelist())


def test_scrub_docx_metadata_preserves_document_body() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_metadata())
    with zipfile.ZipFile(BytesIO(scrubbed)) as archive:
        assert b"CURRICULUM VITAE" in archive.read("word/document.xml")
        assert archive.testzip() is None


def test_scrub_docx_metadata_rejects_non_docx() -> None:
    with pytest.raises(ValueError, match="not a readable DOCX"):
        scrub_docx_metadata(b"this is not a docx")


_IMAGE_BYTES = bytes(range(256)) * 4  # arbitrary binary content, not valid PNG


def _docx_with_editing_history() -> bytes:
    """OOXML package carrying rsid revision-save IDs and author/initials
    values in the parts phased requirements.md 4.2.3 names: document.xml,
    settings.xml (the <w:rsids> block), comments.xml (tracked-change/comment
    authors) and a binary media part that must round-trip untouched."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p w:rsidR="00A1B2C3" w:rsidRDefault="00D4E5F6">'
            "<w:r><w:t>CURRICULUM VITAE</w:t></w:r>"
            "</w:p></w:body></w:document>",
        )
        archive.writestr(
            "word/settings.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'w:rsidRoot="00112233">'
            "<w:rsids>"
            '<w:rsid w:val="00A1B2C3"/><w:rsid w:val="00D4E5F6"/>'
            "</w:rsids>"
            "</w:settings>",
        )
        archive.writestr(
            "word/comments.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:comment w:id="0" w:author="Orkhan" w:initials="OA">'
            "<w:p><w:r><w:t>note</w:t></w:r></w:p>"
            "</w:comment></w:comments>",
        )
        archive.writestr(
            "word/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:style w:type="paragraph" w:styleId="Normal">'
            '<w:rsid w:val="00BADBAD"/>'
            "</w:style>"
            "</w:styles>",
        )
        archive.writestr("word/media/image1.png", _IMAGE_BYTES)
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:creator>Orkhan</dc:creator>"
            "</cp:coreProperties>",
        )
        # docProps/core.xml is already wiped wholesale by _EMPTY_DOCPROPS, so
        # a <cp:lastModifiedBy> there would trivially disappear regardless of
        # whether _strip_editing_history runs. Put it in a part that goes
        # through the strip path instead, so the test actually exercises the
        # regex.
        archive.writestr(
            "customXml/item1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<root xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">'
            "<cp:lastModifiedBy>Orkhan</cp:lastModifiedBy>"
            "</root>",
        )
    return buffer.getvalue()


def _read_part(scrubbed: bytes, name: str) -> bytes:
    """Decompressed bytes of one zip member -- not the compressed archive
    stream, which DEFLATE does not preserve literal substrings in, and not a
    parser view either, since parser-level assertions have hidden a real
    defect in this module before."""
    with zipfile.ZipFile(BytesIO(scrubbed)) as archive:
        return archive.read(name)


def test_scrub_docx_metadata_removes_rsid_attributes() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_editing_history())
    document_xml = _read_part(scrubbed, "word/document.xml")
    assert b"00A1B2C3" not in document_xml
    assert b"00D4E5F6" not in document_xml
    assert b'w:rsidR="' not in document_xml
    assert b'w:rsidRDefault="' not in document_xml


def test_scrub_docx_metadata_removes_element_form_rsid() -> None:
    """Element-form rsids (<w:rsid w:val="..."/> as a child of <w:style>) are
    a separate case from the attribute form: the attribute after w:rsid here
    is w:val, not w:rsidR-shaped, so the attribute-sweep regex never fires."""
    scrubbed = scrub_docx_metadata(_docx_with_editing_history())
    styles_xml = _read_part(scrubbed, "word/styles.xml")
    assert b"00BADBAD" not in styles_xml
    assert b"<w:rsid " not in styles_xml


def test_scrub_docx_metadata_removes_rsids_block_and_root() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_editing_history())
    settings_xml = _read_part(scrubbed, "word/settings.xml")
    assert b"<w:rsids>" not in settings_xml
    assert b'w:rsidRoot="00112233"' not in settings_xml
    assert b"00112233" not in settings_xml


def test_scrub_docx_metadata_blanks_author_and_initials() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_editing_history())
    comments_xml = _read_part(scrubbed, "word/comments.xml")
    assert b"Orkhan" not in comments_xml
    assert b"OA" not in comments_xml
    # The attribute itself must survive (empty), or the XML schema breaks.
    assert b'w:author=""' in comments_xml
    assert b'w:initials=""' in comments_xml


def test_scrub_docx_metadata_removes_last_modified_by() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_editing_history())
    item1_xml = _read_part(scrubbed, "customXml/item1.xml")
    assert b"<cp:lastModifiedBy>" not in item1_xml
    assert b"Orkhan" not in item1_xml


def test_scrub_docx_metadata_preserves_body_text_byte_for_byte() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_editing_history())
    with zipfile.ZipFile(BytesIO(scrubbed)) as archive:
        document_xml = archive.read("word/document.xml")
    assert b"CURRICULUM VITAE" in document_xml
    text_only = re.sub(rb"<[^>]+>", b"", document_xml)
    assert text_only == b"CURRICULUM VITAE"


def test_scrub_docx_metadata_with_editing_history_keeps_every_part() -> None:
    original = _docx_with_editing_history()
    scrubbed = scrub_docx_metadata(original)
    with zipfile.ZipFile(BytesIO(original)) as before, zipfile.ZipFile(BytesIO(scrubbed)) as after:
        assert sorted(after.namelist()) == sorted(before.namelist())


def test_scrub_docx_metadata_output_is_valid_zip_and_wellformed_xml() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_editing_history())
    with zipfile.ZipFile(BytesIO(scrubbed)) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            if name.endswith(".xml"):
                minidom.parseString(archive.read(name))


def test_scrub_docx_metadata_leaves_binary_parts_untouched() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_editing_history())
    with zipfile.ZipFile(BytesIO(scrubbed)) as archive:
        assert archive.read("word/media/image1.png") == _IMAGE_BYTES


# --- script-required joiners must survive (vendored Layer A) ------------------
# normalize_text's own docstring promises names "in any script survive
# unchanged". Before the vendored cleaner it stripped U+200C/U+200D
# unconditionally, which silently rewrote Persian and Devanagari words and
# broke emoji ZWJ sequences -- for exactly the international applicants this
# product serves.

def test_persian_zwnj_is_load_bearing_and_survives():
    assert normalize_text("می‌خواهم") == "می‌خواهم"


def test_devanagari_zwnj_is_load_bearing_and_survives():
    assert normalize_text("क्‌ष") == "क्‌ष"


def test_emoji_zwj_sequence_is_not_split_into_separate_people():
    assert normalize_text("👨‍👩‍👧") == "👨‍👩‍👧"


def test_zero_width_space_between_letters_is_still_stripped():
    """The load-bearing exemption is joiners in script context, not ZWSP."""
    assert normalize_text("Jane​Doe") == "JaneDoe"


def test_tag_characters_are_stripped():
    """U+E0000-E007F encodes arbitrary ASCII invisibly -- the prose smuggling
    channel our hand-rolled table never covered."""
    smuggled = "".join(chr(0xE0000 + ord(c)) for c in "hidden")
    assert normalize_text(f"Jane{smuggled} Doe") == "Jane Doe"


def test_lone_variation_selector_is_stripped():
    assert normalize_text("Jane️ Doe") == "Jane Doe"
