"""The Azure Layout client: one analyze, polled to the end, every failure unavailable."""

import base64
import json

import pytest

from apps.documents.azure_layout import AzureLayout, analyze_layout
from apps.documents.ocr_errors import OcrUnavailable
from apps.research.egress import SourceBlocked, UnsafeTarget

_RESULT = {
    "status": "succeeded",
    "analyzeResult": {
        "content": "Physics 6 BA",
        "pages": [{
            "pageNumber": 1, "width": 1654, "height": 2339, "unit": "pixel",
            "words": [{"content": "Physics", "polygon": [1, 1, 9, 1, 9, 5, 1, 5],
                       "confidence": 0.99,
                       "span": {"offset": 0, "length": 7}}],
            "lines": [{"content": "Physics 6 BA", "polygon": [1, 1, 30, 1, 30, 5, 1, 5]}],
        }],
        "tables": [{
            "rowCount": 1, "columnCount": 3,
            "boundingRegions": [{"pageNumber": 1, "polygon": [0] * 8}],
            "cells": [{"rowIndex": 0, "columnIndex": 0, "content": "Physics",
                       "spans": [{"offset": 0, "length": 7}]}],
        }],
    },
}


@pytest.fixture(autouse=True)
def _configured(settings):
    settings.AZURE_DI_ENDPOINT = "https://tehsil.cognitiveservices.azure.com"
    settings.AZURE_DI_KEY = "test-key"
    settings.AZURE_DI_API_VERSION = "2024-11-30"


def _start_ok(calls):
    def start(url, *, payload, headers):
        calls.append((url, payload, headers))
        return "https://tehsil.cognitiveservices.azure.com/op/1"
    return start


def test_sends_base64_with_the_pinned_version_and_returns_the_layout():
    calls, polls = [], iter([{"status": "running"}, _RESULT])
    layout = analyze_layout(b"%PDF-1.7 x", pages="2,3", locale="az", start=_start_ok(calls),
                            poll=lambda url, *, params, headers: next(polls), sleep=lambda s: None)
    url, payload, headers = calls[0]
    assert "prebuilt-layout:analyze" in url and "api-version=2024-11-30" in url
    assert "pages=2%2C3" in url or "pages=2,3" in url
    assert "locale=az" in url
    assert payload == {"base64Source": base64.b64encode(b"%PDF-1.7 x").decode()}
    assert headers == {"Ocp-Apim-Subscription-Key": "test-key"}
    assert isinstance(layout, AzureLayout) and layout.pages[0].words[0].confidence == 0.99


def test_a_failed_operation_is_unavailable():
    with pytest.raises(OcrUnavailable, match="failed"):
        analyze_layout(b"x", start=_start_ok([]), poll=lambda url, **k: {"status": "failed"},
                       sleep=lambda s: None)


def test_an_operation_that_never_finishes_is_unavailable():
    with pytest.raises(OcrUnavailable, match="timed out"):
        analyze_layout(b"x", start=_start_ok([]), poll=lambda url, **k: {"status": "running"},
                       sleep=lambda s: None)


def test_a_refused_start_is_unavailable_and_never_quotes_the_key():
    def start(url, *, payload, headers):
        raise SourceBlocked("api returned HTTP 429")
    with pytest.raises(OcrUnavailable) as caught:
        analyze_layout(b"x", start=start, poll=lambda url, **k: _RESULT, sleep=lambda s: None)
    assert "test-key" not in str(caught.value)


def test_no_endpoint_configured_is_unavailable(settings):
    settings.AZURE_DI_ENDPOINT = ""
    with pytest.raises(OcrUnavailable, match="not configured"):
        analyze_layout(b"x", start=_start_ok([]), poll=lambda url, **k: _RESULT,
                       sleep=lambda s: None)


def test_a_private_endpoint_is_unavailable_never_a_raw_value_error(settings):
    settings.AZURE_DI_ENDPOINT = "https://10.0.0.1"
    with pytest.raises(OcrUnavailable) as caught:
        analyze_layout(b"x", poll=lambda url, **k: _RESULT, sleep=lambda s: None)
    assert "test-key" not in str(caught.value)


def test_an_unsafe_target_from_start_is_unavailable():
    def start(url, *, payload, headers):
        raise UnsafeTarget("private address")
    with pytest.raises(OcrUnavailable):
        analyze_layout(b"x", start=start, poll=lambda url, **k: _RESULT, sleep=lambda s: None)


def test_an_answer_outside_the_schema_is_unavailable():
    bad = {"status": "succeeded", "analyzeResult": {"pages": [{"pageNumber": "x"}]}}
    with pytest.raises(OcrUnavailable, match="schema"):
        analyze_layout(b"x", start=_start_ok([]), poll=lambda url, **k: bad, sleep=lambda s: None)


def test_a_malformed_poll_body_is_unavailable():
    def poll(url, **k):
        raise json.JSONDecodeError("x", "", 0)
    with pytest.raises(OcrUnavailable):
        analyze_layout(b"x", start=_start_ok([]), poll=poll, sleep=lambda s: None)


@pytest.mark.parametrize(
    "body", [{"status": "succeeded"}, {"status": "succeeded", "analyzeResult": None}]
)
def test_succeeded_without_a_result_is_unavailable(body):
    with pytest.raises(OcrUnavailable, match="no result"):
        analyze_layout(b"x", start=_start_ok([]), poll=lambda url, **k: body, sleep=lambda s: None)


def test_a_canceled_operation_fails_at_once_not_after_the_timeout():
    polls = []

    def poll(url, **k):
        polls.append(1)
        return {"status": "canceled"}
    with pytest.raises(OcrUnavailable, match="canceled"):
        analyze_layout(b"x", start=_start_ok([]), poll=poll, sleep=lambda s: None)
    assert len(polls) == 1
