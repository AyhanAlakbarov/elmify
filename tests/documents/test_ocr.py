"""The seam: both inventory transports, Azure for image pages, and the quality gate."""

import io
import json
import sys
import textwrap
from types import SimpleNamespace

import pytest
from botocore.exceptions import ReadTimeoutError
from django.conf import settings

from apps.documents import ocr
from apps.documents.azure_layout import AzureLayout
from apps.documents.ocr import UploadVerdict, inspect_upload
from apps.documents.ocr_errors import OcrUnavailable, PageRefused

_DOCUMENT = SimpleNamespace(object_key="quarantine/tenant/document", scanned_version="v1")
_SHA = "ab" * 32
_PAGE = {"number": 1, "source": "text_layer", "scan_ppi": None, "lines": ["BSc Chemistry"], "tables": [[["6"]]]}


def every_page(document, content, *, locale=None, analyze=ocr.analyze_layout):
    """Every page, or PageRefused for the first one refused -- what the file path used to give."""
    reads = ocr.read_inventory(content, ocr.inventory(document, content), locale=locale, analyze=analyze)
    for read in reads:
        if read.refusal is not None:
            raise PageRefused(read.refusal, read.number)
    found = tuple(read.page for read in reads if read.page is not None)
    if not any(page.tables for page in found):
        raise PageRefused("not_a_transcript", 1)
    return found


def _child(tmp_path, monkeypatch, body):
    """Stand a small Python script in for ocr/read_pages.py, run by this interpreter."""
    (tmp_path / "ocr").mkdir(exist_ok=True)
    (tmp_path / "ocr" / "read_pages.py").write_text(textwrap.dedent(body))
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(settings, "OCR_PYTHON", sys.executable)
    monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "")


def _answering(tmp_path, monkeypatch, output):
    (tmp_path / "output.json").write_text(json.dumps(output))
    _child(tmp_path, monkeypatch, f"print(open({str(tmp_path / 'output.json')!r}).read())")


class _BrokenStream:
    """A Payload whose .read() fails mid-stream -- distinct from invoke() itself raising."""

    def __init__(self, error):
        self._error = error

    def read(self):
        raise self._error


class _Lambda:
    def __init__(self, payload, function_error=None, raises=None, read_raises=None):
        self.payload, self.function_error, self.raises = payload, function_error, raises
        self.read_raises = read_raises
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        if self.read_raises is not None:
            return {"Payload": _BrokenStream(self.read_raises)}
        response = {"Payload": io.BytesIO(json.dumps(self.payload).encode())}
        if self.function_error:
            response["FunctionError"] = self.function_error
        return response


def _function(monkeypatch, client):
    monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "tehsil-transcript-ocr")
    monkeypatch.setattr(ocr, "_lambda_client", lambda: client)
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: pytest.fail("ran a child"))


def test_pages_come_back_typed(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [_PAGE]})
    [read] = every_page(_DOCUMENT, b"%PDF")
    assert read.lines == ("BSc Chemistry",) and read.tables == ((("6",),),)


def test_a_refused_page_is_a_named_refusal(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"refused": {"reason": "unreadable", "page": 2}})
    with pytest.raises(PageRefused) as error:
        every_page(_DOCUMENT, b"%PDF")
    assert (error.value.reason, error.value.page) == ("unreadable", 2)


def test_a_crash_is_unavailable_never_an_empty_transcript(tmp_path, monkeypatch):
    _child(tmp_path, monkeypatch, "raise SystemExit(3)")
    with pytest.raises(OcrUnavailable):
        every_page(_DOCUMENT, b"%PDF")


def test_output_that_is_not_the_contract_is_unavailable(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [{"lines": 1}]})
    with pytest.raises(OcrUnavailable):
        every_page(_DOCUMENT, b"%PDF")


@pytest.mark.parametrize(
    "output",
    [
        {},
        {"pages": []},
        {"pages": [_PAGE], "refused": {"reason": "unreadable", "page": 1}},
    ],
)
def test_an_answer_that_is_neither_pages_nor_a_refusal_is_unavailable(
    tmp_path, monkeypatch, output
):
    """An empty transcript with no refusal, or one claiming both, is never a valid answer -- a
    crash and a program with nothing to say are both OcrUnavailable, never a silent empty read."""
    _answering(tmp_path, monkeypatch, output)
    with pytest.raises(OcrUnavailable):
        every_page(_DOCUMENT, b"%PDF")


def test_the_child_inherits_no_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_RUNTIME_PASSWORD", "hunter2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _child(
        tmp_path,
        monkeypatch,
        """
        import json, os
        page = {"number": 1, "source": "text_layer", "scan_ppi": None,
                "lines": sorted(os.environ), "tables": [[["x"]]]}
        print(json.dumps({"pages": [page]}))
        """,
    )
    [read] = every_page(_DOCUMENT, b"%PDF")
    assert "POSTGRES_RUNTIME_PASSWORD" not in read.lines and "OPENAI_API_KEY" not in read.lines
    assert {"HOME", "PATH"} <= set(read.lines)


def test_a_hung_engine_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "_TIMEOUT_SECONDS", 0.5)
    _child(tmp_path, monkeypatch, "import time; time.sleep(5)")
    with pytest.raises(OcrUnavailable):
        every_page(_DOCUMENT, b"%PDF")


def test_with_a_function_named_the_key_is_sent_never_the_bytes(monkeypatch):
    client = _Lambda({"pages": [_PAGE]})
    _function(monkeypatch, client)
    [read] = every_page(_DOCUMENT, b"%PDF the whole upload")
    assert read.lines == ("BSc Chemistry",)
    [call] = client.calls
    assert call["FunctionName"] == "tehsil-transcript-ocr"
    assert json.loads(call["Payload"]) == {"key": "quarantine/tenant/document", "version_id": "v1"}


def test_the_function_is_never_asked_for_an_unpinned_version(monkeypatch):
    """No scanned version, no read: the latest version is whatever was uploaded last."""
    client = _Lambda({"pages": [_PAGE]})
    _function(monkeypatch, client)
    unpinned = SimpleNamespace(object_key="quarantine/tenant/document", scanned_version="")
    with pytest.raises(OcrUnavailable):
        ocr.inventory(unpinned, b"%PDF")
    with pytest.raises(OcrUnavailable):
        inspect_upload(unpinned, b"%PDF")
    assert client.calls == []


def test_a_function_refusal_is_a_named_refusal(monkeypatch):
    _function(monkeypatch, _Lambda({"refused": {"reason": "low_resolution", "page": 1}}))
    with pytest.raises(PageRefused, match="low_resolution"):
        every_page(_DOCUMENT, b"%PDF")


def test_a_function_error_is_unavailable_and_its_message_is_not_logged(monkeypatch, caplog):
    error = {"errorType": "MemoryError", "errorMessage": "Ali Aliyev 01.05.2002"}
    _function(monkeypatch, _Lambda(error, function_error="Unhandled"))
    with pytest.raises(OcrUnavailable):
        every_page(_DOCUMENT, b"%PDF")
    assert "MemoryError" in caplog.text and "Aliyev" not in caplog.text


def test_a_function_that_does_not_answer_in_time_is_unavailable(monkeypatch):
    _function(monkeypatch, _Lambda(None, raises=ReadTimeoutError(endpoint_url="lambda")))
    with pytest.raises(OcrUnavailable):
        every_page(_DOCUMENT, b"%PDF")


def test_a_broken_response_stream_is_unavailable_not_a_raw_botocore_error(monkeypatch):
    """invoke() can succeed and .read() can still fail mid-stream -- both must land the
    same way, never escape raw to the worker."""
    from botocore.exceptions import ResponseStreamingError

    _function(
        monkeypatch,
        _Lambda(None, read_raises=ResponseStreamingError(error=OSError("connection reset"))),
    )
    with pytest.raises(OcrUnavailable):
        every_page(_DOCUMENT, b"%PDF")


def test_the_client_never_retries_an_invocation(monkeypatch):
    """A retry is a second full read of the same transcript, billed."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")  # on ECS the task supplies it
    client = ocr._lambda_client()
    assert client.meta.config.retries["total_max_attempts"] == 1
    assert client.meta.config.read_timeout > ocr._TIMEOUT_SECONDS


_INVENTORY_IMAGE = {"pages": [{"number": 1, "source": "image", "scan_ppi": None, "lines": [], "tables": []}]}


def _layout(*, word_height=30, confidence=0.98, near_edge=0, tables=True, width=1654, height=2339,
            unit="pixel", scale=1.0, rotated=False, no_polygon=False):
    def poly(*xy):
        return [v * scale for v in xy]

    words = [{"content": f"w{i}x", "confidence": confidence, "span": {"offset": i, "length": 1},
              "polygon": poly(100, 100 + 40 * i, 200, 100 + 40 * i, 200, 100 + 40 * i + word_height,
                              100, 100 + 40 * i + word_height)} for i in range(20)]
    words += [{"content": "edge", "confidence": 0.9, "span": {"offset": 99, "length": 1},
               "polygon": poly(0, 500, 50, 500, 50, 530, 0, 530)} for _ in range(near_edge)]
    if rotated:  # a sideways photo: a word is long in y, thin in x; its height is p0 -> p3
        for i, w in enumerate(words[:20]):
            y = 100 + 40 * i
            w["polygon"] = poly(100 + word_height, y, 100 + word_height, y + 100, 100, y + 100, 100, y)
    if no_polygon:
        for w in words[:20]:
            del w["polygon"]
    lines = [{"content": "Organic Chemistry 6 AA", "polygon": poly(100, 100, 600, 100, 600, 130, 100, 130),
              "spans": [{"offset": 0, "length": 2}]},
             {"content": "Baku State University", "polygon": poly(100, 50, 600, 50, 600, 80, 100, 80),
              "spans": [{"offset": 50, "length": 5}]}]
    cells = [{"rowIndex": 0, "columnIndex": 0, "content": "Organic Chemistry", "spans": [{"offset": 0, "length": 1}]},
             {"rowIndex": 0, "columnIndex": 1, "content": "6", "spans": [{"offset": 1, "length": 1}]},
             {"rowIndex": 0, "columnIndex": 2, "content": "", "spans": []}]
    return AzureLayout.model_validate({
        "content": "x" * 100,
        "pages": [{"pageNumber": 1, "width": width, "height": height, "unit": unit, "words": words, "lines": lines}],
        "tables": [{"rowCount": 1, "columnCount": 3, "cells": cells,
                    "boundingRegions": [{"pageNumber": 1, "polygon": poly(90, 90, 700, 90, 700, 140, 90, 140)}]}]
        if tables else [],
    })


def test_an_image_page_is_read_by_azure_with_cell_confidence(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    [page] = every_page(_DOCUMENT, b"\x89PNG", analyze=lambda content, **k: _layout())
    assert page.source == "azure" and page.api_version == "2024-11-30"
    assert page.tables == ((("Organic Chemistry", "6", ""),),)
    assert page.cell_confidence[0][0][1] == 0.98 and page.cell_confidence[0][0][2] is None
    assert page.lines == ("Baku State University",)  # the table's own line is not a free line


def test_text_layer_pages_never_reach_azure(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [{"number": 1, "source": "text_layer", "scan_ppi": None,
                                                    "lines": ["Transcript"], "tables": [[["CHM1", "6"]]]}]})

    def never(content, **k):
        raise AssertionError("a text-layer page was sent to Azure")

    [page] = every_page(_DOCUMENT, b"%PDF", analyze=never)
    assert page.source == "text_layer" and page.cell_confidence == ()


def test_mixed_pdf_sends_only_scanned_pages_to_azure(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [
        {"number": 1, "source": "text_layer", "scan_ppi": None, "lines": ["Transcript"], "tables": [[["A", "1"]]]},
        {"number": 2, "source": "image", "scan_ppi": 300.0, "lines": [], "tables": []},
    ]})
    asked = []

    def analyze(content, **kwargs):
        asked.append(kwargs["pages"])
        layout = _layout()
        table = layout.tables[0]
        region = table.boundingRegions[0].model_copy(update={"pageNumber": 2})
        return layout.model_copy(update={
            "pages": (layout.pages[0].model_copy(update={"pageNumber": 2}),),
            "tables": (table.model_copy(update={"boundingRegions": (region,)}),),
        })

    pages = every_page(_DOCUMENT, b"%PDF", analyze=analyze)
    assert asked == ["2"] and [p.source for p in pages] == ["text_layer", "azure"]


@pytest.mark.parametrize("layout,reason", [
    (dict(word_height=8), "text_too_small"),
    (dict(confidence=0.5), "unreadable"),
    (dict(near_edge=3), "cut_off"),
    (dict(word_height=8, rotated=True), "text_too_small"),
])
def test_the_gate_refuses_a_page_on_azures_own_output(tmp_path, monkeypatch, layout, reason):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    with pytest.raises(PageRefused) as refused:
        every_page(_DOCUMENT, b"\x89PNG", analyze=lambda content, **k: _layout(**layout))
    assert (refused.value.reason, refused.value.page) == (reason, 1)


def test_a_document_with_no_table_anywhere_is_not_a_transcript(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    with pytest.raises(PageRefused) as refused:
        every_page(_DOCUMENT, b"\x89PNG", analyze=lambda content, **k: _layout(tables=False))
    assert refused.value.reason == "not_a_transcript"


@pytest.mark.parametrize("ppi,refused", [(300.0, False), (200.0, True)])
def test_a_scanned_pdf_measures_text_height_in_its_own_pixels(tmp_path, monkeypatch, ppi, refused):
    # Azure reports PDF pages in inches: 0.05 in at 300 ppi is 15 px (passes); at 200 ppi 10 px.
    _answering(tmp_path, monkeypatch, {"pages": [{"number": 1, "source": "image", "scan_ppi": ppi,
                                                    "lines": [], "tables": []}]})

    def inches(content, **k):  # word_height is scaled too: 12.5 * 0.004 = 0.05 in
        return _layout(word_height=12.5, width=8.27, height=11.69, unit="inch", scale=0.004)

    if refused:
        with pytest.raises(PageRefused, match="text_too_small"):
            every_page(_DOCUMENT, b"%PDF", analyze=inches)
    else:
        every_page(_DOCUMENT, b"%PDF", analyze=inches)


def _two_page_table_layout():
    def word(i, offset, conf, y):
        return {"content": f"w{i}x", "confidence": conf, "span": {"offset": offset, "length": 1},
                "polygon": [100, y, 200, y, 200, y + 30, 100, y + 30]}

    def page(n, words, lines):
        return {"pageNumber": n, "width": 1654, "height": 2339, "unit": "pixel", "words": words, "lines": lines}

    def cell(row, col, text, offset, n):
        return {"rowIndex": row, "columnIndex": col, "content": text,
                "spans": [{"offset": offset, "length": 1}],
                "boundingRegions": [{"pageNumber": n, "polygon": [0, 0, 1, 0, 1, 1, 0, 1]}]}

    p1 = page(1, [word(0, 0, 0.91, 100), word(1, 1, 0.92, 200)] * 1 + [word(i, 10 + i, 0.99, 300 + 40 * i) for i in range(18)],
              [{"content": "Chem 6", "polygon": [0, 0, 1, 0, 1, 1, 0, 1], "spans": [{"offset": 0, "length": 2}]}])
    p2 = page(2, [word(2, 2, 0.85, 100), word(3, 3, 0.86, 200)] + [word(i, 40 + i, 0.99, 300 + 40 * i) for i in range(18)],
              [{"content": "Phys 5", "polygon": [0, 0, 1, 0, 1, 1, 0, 1], "spans": [{"offset": 2, "length": 2}]}])
    return AzureLayout.model_validate({
        "content": "x" * 100, "pages": [p1, p2],
        "tables": [{"rowCount": 4, "columnCount": 1,
                    "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 1, 0, 1, 1, 0, 1]},
                                        {"pageNumber": 2, "polygon": [0, 0, 1, 0, 1, 1, 0, 1]}],
                    "cells": [cell(0, 0, "Chem", 0, 1), cell(1, 0, "6", 1, 1),
                              cell(2, 0, "Phys", 2, 2), cell(3, 0, "5", 3, 2)]}],
    })


def test_a_table_spanning_pages_is_split_per_page(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [
        {"number": n, "source": "image", "scan_ppi": 300.0, "lines": [], "tables": []} for n in (1, 2)]})
    one, two = every_page(_DOCUMENT, b"%PDF", analyze=lambda content, **k: _two_page_table_layout())
    assert one.tables == ((("Chem",), ("6",)),) and two.tables == ((("Phys",), ("5",)),)
    assert one.cell_confidence == (((0.91,), (0.92,)),) and two.cell_confidence == (((0.85,), (0.86,)),)
    assert one.lines == () and two.lines == ()


def test_a_pdf_page_missing_from_azures_answer_is_unavailable(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [
        {"number": 2, "source": "image", "scan_ppi": 300.0, "lines": [], "tables": []}]})
    with pytest.raises(OcrUnavailable):
        every_page(_DOCUMENT, b"%PDF", analyze=lambda content, **k: _layout())


def test_a_word_without_a_polygon_is_not_gated_and_not_an_error(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    [page] = every_page(_DOCUMENT, b"\x89PNG", analyze=lambda content, **k: _layout(no_polygon=True))
    assert page.source == "azure"


_TWO_IMAGE_PAGES = {"pages": [
    {"number": 1, "source": "image", "scan_ppi": None, "lines": [], "tables": []},
    {"number": 2, "source": "image", "scan_ppi": None, "lines": [], "tables": []},
]}


def test_a_refused_page_does_not_stop_the_others_being_read(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, _TWO_IMAGE_PAGES)
    good, small = _layout(), _layout(word_height=5)
    layout = good.model_copy(update={
        "pages": (good.pages[0], small.pages[0].model_copy(update={"pageNumber": 2}))})
    pages = ocr.inventory(_DOCUMENT, b"%PDF")
    reads = ocr.read_inventory(b"%PDF", pages, analyze=lambda content, **k: layout)
    assert [r.number for r in reads] == [1, 2]
    assert reads[0].page is not None and reads[0].refusal is None
    assert (reads[1].page, reads[1].refusal) == (None, "text_too_small")


def test_an_azure_page_with_no_words_is_blank_not_refused(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    layout = _layout()
    layout = layout.model_copy(update={"pages": (layout.pages[0].model_copy(update={"words": ()}),)})
    [read] = ocr.read_inventory(b"\x89PNG", ocr.inventory(_DOCUMENT, b"\x89PNG"), analyze=lambda c, **k: layout)
    assert (read.blank, read.page, read.refusal) == (True, None, None)


def test_an_upload_whose_only_page_is_blank_is_not_a_transcript(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, _INVENTORY_IMAGE)
    layout = _layout()
    layout = layout.model_copy(update={"pages": (layout.pages[0].model_copy(update={"words": ()}),)})
    with pytest.raises(PageRefused) as refused:
        every_page(_DOCUMENT, b"\x89PNG", analyze=lambda c, **k: layout)
    assert refused.value.reason == "not_a_transcript"


def test_a_parser_refusal_still_raises(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"refused": {"reason": "too_many_pages", "page": 31}})
    with pytest.raises(PageRefused) as refused:
        ocr.inventory(_DOCUMENT, b"%PDF")
    assert (refused.value.reason, refused.value.page) == ("too_many_pages", 31)


def test_the_upload_check_sends_the_key_and_the_operation_never_the_bytes(monkeypatch):
    client = _Lambda({"type": "application/pdf", "active_content": ["/Launch"], "sha256": _SHA})
    _function(monkeypatch, client)
    verdict = inspect_upload(_DOCUMENT, b"%PDF the whole upload")
    assert verdict == UploadVerdict(
        type="application/pdf", active_content=("/Launch",), sha256=_SHA
    )
    [call] = client.calls
    assert json.loads(call["Payload"]) == {
        "key": "quarantine/tenant/document",
        "op": "inspect",
        "version_id": "v1",
    }


def test_locally_the_upload_check_is_the_same_child_with_one_flag(tmp_path, monkeypatch):
    _child(
        tmp_path,
        monkeypatch,
        """
        import json, sys
        assert sys.argv[1:] == ["--inspect"], sys.argv
        assert sys.stdin.buffer.read() == b"\\x89PNG\\r\\n\\x1a\\n"
        print(json.dumps({"type": "image/png", "active_content": [], "sha256": "ab" * 32}))
        """,
    )
    assert inspect_upload(_DOCUMENT, b"\x89PNG\r\n\x1a\n").type == "image/png"


@pytest.mark.parametrize(
    "output",
    [
        {},
        {"type": "text/html", "active_content": []},
        {"type": None},
        {"type": None, "active_content": [], "sha256": "ab" * 32, "pages": []},
        # The digest is what binds the verdict to the copied bytes: never optional.
        {"type": "image/png", "active_content": []},
        {"type": "image/png", "active_content": [], "sha256": "not-a-digest"},
    ],
)
def test_an_answer_outside_the_contract_is_unavailable_never_clean(tmp_path, monkeypatch, output):
    _answering(tmp_path, monkeypatch, output)
    with pytest.raises(OcrUnavailable):
        inspect_upload(_DOCUMENT, b"%PDF")
