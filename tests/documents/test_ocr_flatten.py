import base64
import json

import pytest
from django.conf import settings

from apps.documents import ocr
from apps.documents.ocr_errors import OcrUnavailable, PageRefused


class _Doc:
    object_key = "quarantine/t/d"
    scanned_version = "v1"


def _child_answer(monkeypatch, answer):
    seen = {}

    def run_child(content, *flags):
        seen["flags"] = flags
        return json.dumps(answer).encode()

    monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "")
    monkeypatch.setattr(ocr, "_run_child", run_child)
    return seen


def test_flatten_asks_the_child_for_the_capped_pictures(monkeypatch):
    seen = _child_answer(monkeypatch, {"image_pdf": base64.b64encode(b"%PDF-flat").decode(),
                                       "pages": 2, "visible": ["a", "b"]})
    flat = ocr.flatten(_Doc(), b"%PDF-orig", max_pages=4)
    assert seen["flags"] == ("--flatten", "4")
    assert flat.pages == 2 and flat.visible == ("a", "b")
    assert flat.body(b"%PDF-orig") == b"%PDF-flat"


def test_an_image_upload_keeps_its_own_bytes(monkeypatch):
    _child_answer(monkeypatch, {"image_pdf": None, "pages": 1, "visible": []})
    assert ocr.flatten(_Doc(), b"\x89PNG", max_pages=4).body(b"\x89PNG") == b"\x89PNG"


def test_a_refusal_is_named_and_garbage_is_unavailable(monkeypatch):
    _child_answer(monkeypatch, {"refused": {"reason": "page_too_large", "page": 2}})
    with pytest.raises(PageRefused):
        ocr.flatten(_Doc(), b"%PDF", max_pages=4)
    _child_answer(monkeypatch, {"pages": 0})
    with pytest.raises(OcrUnavailable):
        ocr.flatten(_Doc(), b"%PDF", max_pages=4)


def test_the_function_gets_the_key_the_op_and_the_cap(monkeypatch):
    sent = {}
    monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "elmify-transcript-ocr")
    monkeypatch.setattr(ocr, "_invoke", lambda key, version, op="", body=None: sent.update(
        body) or json.dumps({"image_pdf": None, "pages": 1, "visible": []}).encode())
    ocr.flatten(_Doc(), b"", max_pages=2)
    assert sent == {"key": "quarantine/t/d", "version_id": _Doc.scanned_version,
                    "op": "flatten", "max_pages": 2}


def test_an_image_pdf_that_is_not_base64_is_unavailable(monkeypatch):
    _child_answer(monkeypatch, {"image_pdf": "not base64!!", "pages": 1, "visible": ["a"]})
    flat = ocr.flatten(_Doc(), b"%PDF", max_pages=4)
    with pytest.raises(OcrUnavailable):
        flat.body(b"%PDF")
