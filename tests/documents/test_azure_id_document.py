import pytest

from apps.documents import azure_layout
from apps.documents.ocr_errors import OcrUnavailable

RESULT = {
    "content": "PASSPORT ...",
    "pages": [{"pageNumber": 1, "width": 8.5, "height": 11, "unit": "inch",
               "words": [{"content": "BAKU", "confidence": 0.99,
                          "span": {"offset": 0, "length": 4}}]}],
    "documents": [{
        "docType": "idDocument.passport", "confidence": 0.99,
        "fields": {
            "PlaceOfBirth": {"type": "string", "valueString": "BAKU", "content": "BAKU",
                             "confidence": 0.98, "spans": [{"offset": 0, "length": 4}]},
            "MachineReadableZone": {"type": "object", "content": "P<AZE...", "confidence": 0.99,
                                    "valueObject": {"Sex": {"type": "string",
                                                            "valueString": "F"}}},
        },
    }],
}


@pytest.fixture
def configured(settings):
    settings.AZURE_DI_ENDPOINT = "https://di.example.com"
    settings.AZURE_DI_KEY = "key"


def test_an_id_document_is_read_with_the_id_model(configured):
    started = {}

    def start(url, *, payload, headers):
        started["url"] = url
        return "https://di.example.com/op/1"

    result = azure_layout.analyze_id_document(
        b"%PDF-1.7", pages="1-4", start=start,
        poll=lambda *a, **k: {"status": "succeeded", "analyzeResult": RESULT},
        sleep=lambda s: None,
    )
    assert "prebuilt-idDocument:analyze" in started["url"] and "pages=1-4" in started["url"]
    passport = result.documents[0]
    assert passport.docType == "idDocument.passport"
    assert passport.fields["PlaceOfBirth"].text() == "BAKU"
    assert passport.fields["MachineReadableZone"].valueObject["Sex"].text() == "F"


def test_an_unconfigured_reader_is_unavailable(settings):
    settings.AZURE_DI_ENDPOINT = ""
    with pytest.raises(OcrUnavailable):
        azure_layout.analyze_id_document(b"x", pages="1-4")


def test_the_layout_reader_still_reads_layout(configured):
    started = {}

    def start(url, *, payload, headers):
        started["url"] = url
        return "op"

    azure_layout.analyze_layout(
        b"x", start=start, poll=lambda *a, **k: {"status": "succeeded",
                                                  "analyzeResult": {"content": ""}},
        sleep=lambda s: None,
    )
    assert "prebuilt-layout:analyze" in started["url"]
