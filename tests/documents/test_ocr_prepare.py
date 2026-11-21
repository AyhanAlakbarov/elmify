import io

import pytest
from PIL import Image

from apps.documents.file_rules import FileRule
from apps.documents.ocr import Part, prepare_files
from apps.documents.ocr_errors import OcrUnavailable


def _png():
    out = io.BytesIO()
    Image.new("RGB", (800, 1100), "white").save(out, "PNG")
    return out.getvalue()


def test_our_own_document_goes_inline_and_comes_back_as_a_pdf(settings):
    settings.OCR_FUNCTION_NAME = ""
    result = prepare_files([Part(own=_png())], FileRule(format="PDF"))
    assert result.content_type == "application/pdf" and result.body.startswith(b"%PDF")


def test_a_lambda_event_names_uploads_by_key_and_scanned_version(settings, monkeypatch):
    settings.OCR_FUNCTION_NAME = "ocr"
    sent = {}

    def invoke(key, version, op="", body=None):
        sent.update(body)
        return b'{"refused": "too_large"}'

    monkeypatch.setattr("apps.documents.ocr._invoke", invoke)
    upload = type(
        "U", (), {"object_key": "quarantine/a", "scanned_version": "v9", "state": "AVAILABLE"}
    )()
    result = prepare_files([Part(upload=upload), Part(own=b"%PDF-1.7")], FileRule(max_bytes=1))
    assert sent["parts"][0] == {"key": "quarantine/a", "version_id": "v9"}
    assert "inline" in sent["parts"][1] and result.refused == "too_large"


def _answer(settings, monkeypatch, **fields):
    import base64
    import hashlib
    import json

    settings.OCR_FUNCTION_NAME = "ocr"
    body = fields.pop("raw", b"%PDF-1.7 x")
    answer = {
        "content_type": "application/pdf",
        "sha256": hashlib.sha256(body).hexdigest(),
        "body": base64.b64encode(body).decode(),
    } | fields
    monkeypatch.setattr(
        "apps.documents.ocr._invoke", lambda *a, **k: json.dumps(answer).encode()
    )
    return prepare_files([Part(own=b"%PDF-1.7")], FileRule())


def test_a_body_over_the_return_cap_is_refused(settings, monkeypatch):
    result = _answer(settings, monkeypatch, raw=b"x" * 5_000_000)
    assert result.refused == "too_large_to_return" and result.body == b""


def test_a_body_without_a_type_is_unavailable(settings, monkeypatch):
    with pytest.raises(OcrUnavailable):
        _answer(settings, monkeypatch, content_type=None)


def test_a_type_outside_the_three_is_unavailable(settings, monkeypatch):
    with pytest.raises(OcrUnavailable):
        _answer(settings, monkeypatch, content_type="text/html")


def test_a_digest_mismatch_is_unavailable(settings, monkeypatch):
    with pytest.raises(OcrUnavailable):
        _answer(settings, monkeypatch, sha256="0" * 64)


def test_an_unreadable_upload_is_unavailable_locally(settings, monkeypatch):
    from apps.concierge.documents import DocumentUnavailable

    settings.OCR_FUNCTION_NAME = ""

    def boom(_upload):
        raise DocumentUnavailable("gone")

    monkeypatch.setattr("apps.documents.storage.read_upload", boom)
    with pytest.raises(OcrUnavailable):
        prepare_files([Part(upload=object())], FileRule())


def test_an_upload_part_that_is_not_available_is_unreadable_in_lambda_mode(settings, monkeypatch):
    settings.OCR_FUNCTION_NAME = "ocr"
    monkeypatch.setattr(
        "apps.documents.ocr._invoke", lambda *a, **k: pytest.fail("invoked the function")
    )
    upload = type("U", (), {"object_key": "q/a", "scanned_version": "v9", "state": "CHECKING"})()
    assert prepare_files([Part(upload=upload)], FileRule()).refused == "unreadable"


def test_a_part_s_page_selection_reaches_the_function_and_the_child(settings, monkeypatch):
    """Plan 4b Task 6 fix M1: a transcript merge sends each file's live pages only."""
    settings.OCR_FUNCTION_NAME = "ocr"
    sent = {}

    def invoke(key, version, op="", body=None):
        sent.update(body)
        return b'{"refused": "too_large"}'

    monkeypatch.setattr("apps.documents.ocr._invoke", invoke)
    upload = type(
        "U", (), {"object_key": "quarantine/a", "scanned_version": "v9", "state": "AVAILABLE"}
    )()
    prepare_files([Part(upload=upload, pages=(2,)), Part(own=b"%PDF-1.7", pages=(1,))],
                  FileRule(format="PDF", one_file=True))
    assert sent["parts"][0] == {"key": "quarantine/a", "version_id": "v9", "pages": [2]}
    assert sent["parts"][1]["pages"] == [1]

    settings.OCR_FUNCTION_NAME = ""
    result = prepare_files([Part(own=_png(), pages=(1,)), Part(own=_png())],
                           FileRule(format="PDF", one_file=True))
    assert result.content_type == "application/pdf"
    assert prepare_files([Part(own=_png(), pages=(2,))], FileRule(format="PDF")).refused == (
        "unreadable"
    )
