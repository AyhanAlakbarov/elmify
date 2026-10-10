"""One live read of a sample transcript: the real page inventory (child process), the real Azure
Document Intelligence and the real Jev, nothing mocked but the storage and the limiter.

Never a real person's transcript (spec T19): an official sample or specimen, from
TRANSCRIPT_SAMPLE. Skips without it, without the OCR interpreter, without Azure keys
(~/.config/tehsil_agent/ocr.env) or without OPENROUTER_API_KEY.
"""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from django.conf import settings
from django.test import override_settings

from apps.documents import ocr
from apps.documents.transcript import academic_record, check_gates, read_from_pages
from apps.documents.transcript_checks import highlights, key_numbers

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif("TRANSCRIPT_SAMPLE" not in os.environ, reason="no sample transcript"),
    pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="no OPENROUTER_API_KEY"),
    pytest.mark.skipif(
        not (os.environ.get("AZURE_DI_ENDPOINT") and os.environ.get("AZURE_DI_KEY")),
        reason="no AZURE_DI_ENDPOINT / AZURE_DI_KEY (source ~/.config/tehsil_agent/ocr.env)",
    ),
    pytest.mark.skipif(not Path(settings.OCR_PYTHON).exists(), reason="no OCR interpreter"),
]


@override_settings(
    TRANSCRIPT_JEV_ENABLED=True,
    TRANSCRIPT_AZURE_ENABLED=True,
    OCR_FUNCTION_NAME="",
    AZURE_DI_ENDPOINT=os.environ.get("AZURE_DI_ENDPOINT", ""),
    AZURE_DI_KEY=os.environ.get("AZURE_DI_KEY", ""),
    JEV_API_KEY=os.environ.get("OPENROUTER_API_KEY", ""),
    OPENROUTER_API_KEY=os.environ.get("OPENROUTER_API_KEY", ""),
)
def test_a_sample_transcript_reads_into_courses():
    # TRANSCRIPT_JEV_ENABLED is enabled here, explicitly, only for this official sample --
    # never for a real student's transcript (spec 3.1 launch gate) until TypeSafe's DPA is
    # accepted and OpenRouter's terms are reviewed.
    content = Path(os.environ["TRANSCRIPT_SAMPLE"]).read_bytes()
    document = SimpleNamespace(object_key="live-transcript-check")
    pages: list[ocr.OcrPage] = []
    real = ocr.read_inventory

    def spy(*args: Any, **kwargs: Any) -> tuple[ocr.PageRead, ...]:
        reads = real(*args, **kwargs)
        pages.extend(read.page for read in reads if read.page is not None)
        return reads

    check_gates()
    with patch("apps.documents.ocr.read_inventory", side_effect=spy):
        reads = ocr.read_inventory(
            content, ocr.inventory(document, content), locale=None  # type: ignore[arg-type]
        )
    assert all(read.refusal is None for read in reads), [read.refusal for read in reads]
    reading = read_from_pages(tuple(pages), frozenset())
    record = academic_record(reading.content)
    flags = highlights(reading)
    print(
        record["institution"],
        len(record["courses"]),
        key_numbers(reading).model_dump(mode="json"),
        [highlight.model_dump() for highlight in flags],
    )
    print("sources", [page.source for page in pages])
    print("low_confidence", sum(highlight.kind == "low_confidence" for highlight in flags))
    assert len(record["courses"]) >= 5
    assert pages and all(page.source in ("text_layer", "azure") for page in pages)
