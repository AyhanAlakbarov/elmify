"""The page inventory: counting, the scan-resolution gate, the text-layer path, the handler; and
the upload check (`inspect`).

Runs in the OCR venv (`uv run --project ocr pytest ocr`). The app's own suite skips it, because
pdfplumber exists only in the OCR venv.
"""

import hashlib
import io
from pathlib import Path

import pytest

pdfplumber = pytest.importorskip("pdfplumber")

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
    page = {"number": 1, "source": "image", "scan_ppi": None, "lines": [], "tables": []}
    assert rp.inventory(_png()) == {"pages": [page]}


def test_a_scanned_pdf_page_is_an_image_page_with_its_resolution():
    out = rp.inventory(_scanned_pdf(300))
    [page] = out["pages"]
    assert page["source"] == "image" and round(page["scan_ppi"]) == 300


def test_a_low_resolution_scan_is_refused_before_anything_is_read():
    assert rp.inventory(_scanned_pdf(120)) == {"refused": {"reason": "low_resolution", "page": 1}}


def test_too_many_pages_is_refused():
    out = rp.inventory(_scanned_pdf(200, pages=rp.MAX_PAGES + 1))
    assert out["refused"]["reason"] == "too_many_pages"


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
    rows = [["Code", "Course", "ECTS", "Grade"]]
    rows += [[f"CHM{i}", "Organic Chemistry", "6", "AA"] for i in range(20)]
    assert rp.text_layer_usable(["Transcript of Records"], [rows])


class _S3:
    def __init__(self, data):
        self.data, self.asked = data, []

    def get_object(self, Bucket, Key, VersionId, Range):  # noqa: N803 - boto3's own names
        self.asked.append((Bucket, Key, VersionId, Range))
        return {"Body": io.BytesIO(self.data)}


def test_handler_reads_the_named_key_from_its_own_bucket(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")
    s3 = _S3(_png())
    event = {"key": "quarantine/t/d", "version_id": "v1", "bucket": "elsewhere"}
    out = rp.handler(event, None, s3=s3)
    # The event cannot choose the bucket, and only the scanned version is ever read.
    assert s3.asked == [("evidence", "quarantine/t/d", "v1", f"bytes=0-{rp.MAX_BYTES}")]
    assert out["pages"][0]["source"] == "image"


def test_the_handler_refuses_an_object_over_the_size_cap(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")
    big = _S3(b"\x00" * (rp.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="larger"):
        rp.handler({"key": "quarantine/t/d", "version_id": "v1"}, None, s3=big)


@pytest.mark.parametrize("op", [None, "inspect"])
def test_the_lambda_never_reads_an_unpinned_version(monkeypatch, op):
    """The latest version is whatever the still-valid upload form last wrote; only the
    version GuardDuty scanned may be read, so an event without one is refused."""
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")
    s3 = _S3(b"%PDF-1.7")
    event = {"key": "quarantine/t/d"} | ({"op": op} if op else {})
    with pytest.raises(ValueError, match="version"):
        rp.handler(event, None, s3=s3)
    assert s3.asked == []


def test_a_born_digital_pdf_is_read_from_its_text_layer():
    data = (Path(__file__).parent / "fixtures" / "text_transcript.pdf").read_bytes()
    [page] = rp.inventory(data)["pages"]
    assert page["source"] == "text_layer"
    assert any("Organic Chemistry 7" in " ".join(row) for table in page["tables"] for row in table)


def test_a_text_layer_with_no_table_found_goes_to_azure_as_an_image():
    data = (Path(__file__).parent / "fixtures" / "text_borderless.pdf").read_bytes()
    with pdfplumber.open(io.BytesIO(data)) as plumbed:
        assert plumbed.pages[0].extract_tables() == []
    [page] = rp.inventory(data)["pages"]
    assert page["source"] == "image" and page["lines"] == [] and page["scan_ppi"] is None


def test_two_parsers_disagreeing_on_the_page_count_is_unreadable(monkeypatch):
    class _Plumbed:
        pages: list = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(rp.pdfplumber, "open", lambda _: _Plumbed())
    data = (Path(__file__).parent / "fixtures" / "text_transcript.pdf").read_bytes()
    assert rp.inventory(data) == {"refused": {"reason": "unreadable", "page": 1}}


def test_a_zero_height_image_object_is_skipped_not_a_division_by_zero():
    class _Image:
        def get_bounds(self):
            return (0, 100, 600, 100)

        def get_px_size(self):
            return (1000, 1000)

    class _Page:
        def get_width(self):
            return 600

        def get_objects(self, **_):
            return [_Image()]

    assert rp.scan_ppi(_Page()) is None


def test_text_layer_lines_hold_nothing_a_table_holds():
    data = (Path(__file__).parent / "fixtures" / "text_transcript_gpa.pdf").read_bytes()
    [page] = rp.inventory(data)["pages"]
    assert page["source"] == "text_layer"
    assert not any("Organic" in line for line in page["lines"])  # rows live in tables only
    assert any("Cumulative GPA 3.62" in line for line in page["lines"])


def test_an_image_side_over_azures_limit_is_page_too_large():
    refused = rp.inventory(_png(size=(10_001, 100)))["refused"]
    assert refused == {"reason": "page_too_large", "page": 1}


def test_an_image_side_under_azures_floor_is_low_resolution():
    refused = rp.inventory(_png(size=(49, 800)))["refused"]
    assert refused == {"reason": "low_resolution", "page": 1}


def _blank_pdf(then=None):
    document = rp.pypdfium2.PdfDocument.new()
    document.new_page(595, 842)
    if then is not None:
        document.import_pages(rp.pypdfium2.PdfDocument(then))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_a_blank_born_digital_page_is_skipped_and_others_keep_their_numbers():
    table_page = (Path(__file__).parent / "fixtures" / "text_transcript.pdf").read_bytes()
    out = rp.inventory(_blank_pdf(then=table_page))
    assert [p["number"] for p in out["pages"]] == [2]


def test_a_pdf_of_only_blank_pages_is_unreadable():
    assert rp.inventory(_blank_pdf()) == {"refused": {"reason": "unreadable", "page": 1}}


import pdf_fixtures  # noqa: E402


def _inspected(data):
    """inspect's answer without its digest, after checking the digest is of `data`."""
    answer = rp.inspect(data)
    assert answer.pop("sha256") == hashlib.sha256(data).hexdigest()
    return answer


@pytest.mark.parametrize("name", sorted(pdf_fixtures.ACTIVE))
def test_a_pdf_with_active_content_is_named(name):
    edit, named = pdf_fixtures.ACTIVE[name]
    assert _inspected(pdf_fixtures.written(edit)) == {
        "type": "application/pdf",
        "active_content": named,
    }


def test_a_plain_pdf_and_a_signed_looking_one_carry_none():
    """A /Sig field and an open action that only shows a page run nothing: a signed diploma
    passes, and nothing about it is touched."""
    for data in (pdf_fixtures.written(), pdf_fixtures.written(pdf_fixtures.signature_field)):
        assert _inspected(data) == {"type": "application/pdf", "active_content": []}


def test_a_pdf_nothing_can_parse_is_refused_not_passed():
    assert rp.inspect(b"%PDF-1.7\n garbage")["active_content"] == ["/Unreadable"]


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        # An HTML page the student named passport.pdf: the name is never read.
        (b"<html><body><script>alert(1)</script></body></html>", None),
        (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>', None),
        (b"MZ\x90\x00", None),
    ],
)
def test_the_type_is_read_from_the_bytes_and_only_three_pass(data, kind):
    assert _inspected(data) == {"type": kind, "active_content": []}


def test_the_lambda_inspects_the_scanned_version_and_takes_no_inventory(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")
    monkeypatch.setattr(rp, "inventory", lambda _: pytest.fail("took the page inventory"))
    data = pdf_fixtures.written(pdf_fixtures.launch)
    s3 = _S3(data)
    answer = rp.handler({"key": "quarantine/t/d", "op": "inspect", "version_id": "v1"}, None, s3=s3)
    assert s3.asked == [("evidence", "quarantine/t/d", "v1", f"bytes=0-{rp.MAX_BYTES}")]
    assert answer == {
        "type": "application/pdf",
        "active_content": ["/Launch", "/OpenAction"],
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def test_an_action_naming_its_kind_through_a_reference_is_still_named():
    """`/S 7 0 R` pointing at /Launch is the same action as `/S /Launch`."""
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    def indirect_launch(writer):
        kind = writer._add_object(NameObject("/Launch"))
        writer.root_object[NameObject("/OpenAction")] = DictionaryObject(
            {NameObject("/S"): kind, NameObject("/F"): TextStringObject("calc.exe")}
        )

    assert rp.inspect(pdf_fixtures.written(indirect_launch))["active_content"] == [
        "/Launch",
        "/OpenAction",
    ]


def test_a_link_the_reader_clicks_is_not_active_content():
    """/URI, /SubmitForm, /ImportData and /GoToR are named only when a trigger runs them."""
    assert _inspected(pdf_fixtures.written(pdf_fixtures.link_uri)) == {
        "type": "application/pdf",
        "active_content": [],
    }


def test_an_open_action_that_loops_on_itself_ends_and_runs_nothing():
    """The loop is followed once: visited actions are not popped again."""
    assert _inspected(pdf_fixtures.written(pdf_fixtures.pure_loop)) == {
        "type": "application/pdf",
        "active_content": [],
    }


def test_a_chain_longer_than_the_cap_is_refused_never_half_read(monkeypatch):
    """Past MAX_ACTIONS the answer is a refusal, never the partial set found so far."""
    data = pdf_fixtures.written(lambda writer: pdf_fixtures.long_chain(writer, 10))
    monkeypatch.setattr(rp, "MAX_ACTIONS", 5)
    assert "/TooManyObjects" in rp.inspect(data)["active_content"]
    monkeypatch.setattr(rp, "MAX_ACTIONS", 50)
    assert rp.inspect(data)["active_content"] == []
