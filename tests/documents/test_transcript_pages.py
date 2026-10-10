# tests/documents/test_transcript_pages.py
"""An upload is read once into pages; the allowance is charged once; retakes replace one slot."""

import hashlib
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import StudentCycle
from apps.documents.models import TranscriptPage, TranscriptReading, TranscriptUpload
from apps.documents.ocr import InventoryPage, OcrPage, PageRead
from apps.documents.ocr_errors import OcrUnavailable, PageRefused
from apps.documents.transcript import check_gates as real_check_gates
from apps.documents.transcript_pages import (
    MAX_ATTEMPTS,
    _reserve,
    assemble,
    delay,
    is_english,
    process_upload,
    read_upload,
)
from apps.research.decisions import DecisionsUnavailable
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG" + b"\x00" * 64
TABLE = (("Course", "ECTS", "Grade"), ("Organic Chemistry", "6", "A"))


def _page(*, tables=(TABLE,), lines=("Transcript of Records",)):
    return OcrPage(lines=lines, tables=tables, source="azure", api_version="2024-11-30")


def _inv(*numbers, source="image"):
    return tuple(
        InventoryPage(number=n, source=source, scan_ppi=300.0, lines=(), tables=()) for n in numbers
    )


def _upload(agency, membership, cycle, *, content=PNG, **fields):
    document = register(agency.id, membership.id, kind="TRANSCRIPT")
    with tenant_scope(agency.id):
        _scanned_clean(document)
        upload = TranscriptUpload.objects.create(
            student=membership, cycle=cycle, document=document,
            role=fields.pop("role", "ORIGINAL"), **fields,
        )
    return upload, content


def _scanned_clean(document):
    """open_document reads only what GuardDuty passed."""
    document.state = "AVAILABLE"
    document.save(update_fields=["state"])


def _run(agency, upload, content, *, inventory, reads):
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=inventory) as inv,
        patch("apps.documents.transcript_pages.read_inventory", return_value=reads) as read,
    ):
        done = read_upload(agency.id, upload.id)
    return done, inv, read


def _live(agency, cycle):
    with tenant_scope(agency.id):
        return list(
            TranscriptPage.objects.filter(cycle=cycle, superseded_at__isnull=True)
            .order_by("slot").values_list("slot", "state", "refusal", "retakes")
        )


def test_an_upload_is_read_into_pages_and_charged_once(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    reads = (PageRead(1, page=_page()), PageRead(2, refusal="cut_off"))
    assert _run(agency_a, upload, content, inventory=_inv(1, 2), reads=reads)[0] is True
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0), (2, "REFUSED", "cut_off", 0)]
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (upload.state, upload.pages_counted, paid_cycle_a.pages_used) == ("READ", 2, 2)
        stored = TranscriptPage.objects.get(slot=1)
        assert OcrPage.model_validate(stored.page) == _page()


def test_a_second_run_reads_nothing_and_charges_nothing(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, upload, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    done, inv, read = _run(agency_a, upload, content, inventory=_inv(1), reads=())
    assert (inv.call_count, read.call_count) == (0, 0)
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 1


def test_the_allowance_boundary(agency_a, membership_a, paid_cycle_a):
    with tenant_scope(agency_a.id):
        StudentCycle.objects.filter(id=paid_cycle_a.id).update(pages_used=48)
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    done, _, read = _run(agency_a, upload, content, inventory=_inv(1, 2, 3), reads=())
    assert done is False and read.call_count == 0
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal, upload.refusal_page) == (
            "REFUSED", "allowance_exceeded", 2,
        )
    second, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"2")
    reads = (PageRead(1, page=_page()), PageRead(2, page=_page()))
    assert _run(agency_a, second, content, inventory=_inv(1, 2), reads=reads)[0] is True
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 50


def test_the_same_file_twice_is_charged_once_and_adds_no_slot(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    again, _ = _upload(agency_a, membership_a, paid_cycle_a)
    done, inv, _ = _run(agency_a, again, content, inventory=_inv(1), reads=())
    assert done is True and inv.call_count == 0
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0)]
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        again.refresh_from_db()
        assert (paid_cycle_a.pages_used, again.pages_counted, again.file_sha256) == (
            1, None, hashlib.sha256(content).hexdigest(),
        )


def test_a_retake_replaces_its_slot_and_counts(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, refusal="unreadable")))
    retake, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"r",
                              mode="RETAKE", retake_slot=2)
    assert _run(agency_a, retake, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))[0]
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0), (2, "READ", "", 1)]


def test_a_retake_must_be_one_page(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, refusal="cut_off"),))
    retake, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"r",
                              mode="RETAKE", retake_slot=1)
    assert _run(agency_a, retake, content, inventory=_inv(1, 2), reads=())[0] is False
    with tenant_scope(agency_a.id):
        retake.refresh_from_db()
        assert (retake.state, retake.refusal) == ("REFUSED", "retake_one_page")


def test_replace_supersedes_every_live_page(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, page=_page())))
    new, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"n", mode="REPLACE")
    _run(agency_a, new, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0)]


def test_add_appends_after_the_last_slot(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    second, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"2")
    _run(agency_a, second, content, inventory=_inv(1), reads=(PageRead(1, page=_page(tables=())),))
    assert [slot for slot, *_ in _live(agency_a, paid_cycle_a)] == [1, 2]


def test_a_first_upload_with_no_table_is_not_a_transcript(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, upload, content, inventory=_inv(1), reads=(PageRead(1, page=_page(tables=())),))
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("REFUSED", "not_a_transcript")
    assert _live(agency_a, paid_cycle_a) == []


def test_a_blank_page_is_skipped(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, upload, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, blank=True)))
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0), (2, "SKIPPED", "", 0)]


def test_a_translations_original_language_pages_are_skipped(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a, role="TRANSLATION")
    azerbaijani = _page(lines=("Fənnin adı Qiymət Kredit Məmmədova Əliyev Şəki",),
                        tables=((("Kimya", "6", "Əla"),),))
    _run(agency_a, upload, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, page=azerbaijani)))
    with tenant_scope(agency_a.id):
        skipped = TranscriptPage.objects.get(slot=2)
        assert (skipped.state, skipped.skipped_because, skipped.page) == (
            "SKIPPED", "original_language", None,
        )


@pytest.mark.parametrize(("content", "reason"), [
    (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16, "heic"),
    (b"PK\x03\x04docx", "unsupported_file"),
    (b"%PDF" + b"\x00" * 10_000_001, "unsupported_file"),
])
def test_a_file_the_reader_cannot_take_is_refused_before_the_parser(
    agency_a, membership_a, paid_cycle_a, content, reason,
):
    upload, _ = _upload(agency_a, membership_a, paid_cycle_a)
    done, inv, _ = _run(agency_a, upload, content, inventory=(), reads=())
    assert done is False and inv.call_count == 0
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("REFUSED", reason)


def test_a_parser_refusal_refuses_the_upload(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch(
            "apps.documents.transcript_pages.inventory",
            side_effect=PageRefused("low_resolution", 3),
        ),
    ):
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal, upload.refusal_page) == (
            "REFUSED", "low_resolution", 3,
        )


def test_azure_down_delays_and_never_double_charges(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=OcrUnavailable("down")),
    ):
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (upload.state, upload.attempts, paid_cycle_a.pages_used) == ("DELAYED", 1, 1)
        assert upload.next_attempt_at > timezone.now()
        TranscriptUpload.objects.filter(id=upload.id).update(next_attempt_at=timezone.now())
    _run(agency_a, upload, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 1


def test_a_delayed_upload_waits_for_its_time(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    delay(agency_a.id, upload.id, reason="test")
    done, inv, _ = _run(agency_a, upload, content, inventory=_inv(1), reads=())
    assert done is False and inv.call_count == 0


def test_delays_end_in_failure(agency_a, membership_a, paid_cycle_a):
    upload, _ = _upload(agency_a, membership_a, paid_cycle_a)
    for _ in range(MAX_ATTEMPTS):
        delay(agency_a.id, upload.id, reason="test")
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("FAILED", "reader_unavailable")


@override_settings(TRANSCRIPT_TENANT_DAILY_AZURE_PAGES=1)
def test_the_tenant_daily_ceiling_delays_rather_than_reads(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    second, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"2")
    done, _, read = _run(agency_a, second, content, inventory=_inv(1), reads=())
    assert done is False and read.call_count == 0
    with tenant_scope(agency_a.id):
        second.refresh_from_db()
        assert second.state == "DELAYED"


def test_a_closed_launch_gate_fails_the_upload_at_once(agency_a, membership_a, paid_cycle_a):
    from apps.documents.transcript import TranscriptReadingDisabled

    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    gate = patch(
        "apps.documents.transcript_pages.check_gates",
        side_effect=TranscriptReadingDisabled("off"),
    )
    with gate:
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("FAILED", "reading_off")


ENGLISH_TRANSLATION = OcrPage(
    lines=("Baku State University", "Bakı Dövlət Universiteti", "Transcript of Records",
           "Student: Aysel Məmmədova", "Lecturer: Prof. Əliyev Rəşid Şükür oğlu"),
    tables=((("Course", "Credits", "Grade"), ("General Chemistry", "6", "A"),
             ("Organic Chemistry", "6", "B"), ("Mathematics I", "5", "A")),),
    source="azure", api_version="2024-11-30",
)
CERTIFICATION = _page(
    lines=("I, Leyla Hüseynova, certified translator, certify that this is a true translation.",
           "Notary: Elçin Məmmədov, Baku, Azerbaijan. Seal and signature."),
    tables=(),
)
TURKISH = OcrPage(
    lines=("Not Döküm Belgesi", "Öğrenci No 2154321", "Bolum Kimya Muhendisligi"),
    tables=((("Ders Kodu", "Ders Adı", "Kredi", "Başarı Notu"),
             ("CHE101", "Genel Kimya", "4", "AA"), ("MAT119", "Matematik I", "4", "BA"),
             ("CHE201", "Organik Kimya", "3", "CB")),),
    source="azure", api_version="2024-11-30",
)
TURKISH_ASCII = _page(
    lines=("Ders Adi", "Kredi", "Ogrenci Belgesi"),
    tables=((("Ders Adı", "Kredi", "Başarı Notu"), ("Genel Kimya", "4", "AA")),),
)


def test_english_is_told_from_azerbaijani_turkish_and_russian():
    assert is_english(ENGLISH_TRANSLATION)
    assert is_english(CERTIFICATION)
    assert not is_english(TURKISH)
    assert not is_english(TURKISH_ASCII)
    assert not is_english(_page(
        lines=("Fənnin adı", "Kredit", "Qiymət"), tables=((("Kimya", "6", "Əla"),),)))
    assert not is_english(_page(lines=("Наименование дисциплины Оценка Кредиты",), tables=()))


def test_a_double_tap_while_the_first_is_delayed_is_charged_once(
    agency_a, membership_a, paid_cycle_a,
):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=OcrUnavailable("x")),
    ):
        assert read_upload(agency_a.id, first.id) is False
    second, _ = _upload(agency_a, membership_a, paid_cycle_a)
    assert _run(agency_a, second, content, inventory=_inv(1), reads=())[0] is True
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        second.refresh_from_db()
        assert (paid_cycle_a.pages_used, second.state, second.pages_counted) == (1, "READ", None)
        TranscriptUpload.objects.filter(id=first.id).update(next_attempt_at=timezone.now())
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0)]
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 1


def test_a_claim_leases_the_upload(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory") as read,
    ):
        def concurrent(*args, **kwargs):
            # a redelivery arriving mid-read finds the upload leased, so it does nothing
            assert read_upload(agency_a.id, upload.id) is False
            return (PageRead(1, page=_page()),)

        read.side_effect = concurrent
        assert read_upload(agency_a.id, upload.id) is True
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0)]


def test_a_failed_upload_gives_its_pages_back(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1, 2)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=OcrUnavailable("x")),
    ):
        read_upload(agency_a.id, upload.id)
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 2
    for _ in range(MAX_ATTEMPTS - 1):
        delay(agency_a.id, upload.id, reason="test")
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (upload.state, upload.pages_counted, paid_cycle_a.pages_used) == ("FAILED", None, 0)


def test_a_read_upload_is_returned_true_even_while_its_assembly_waits(
    agency_a, membership_a, paid_cycle_a,
):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, upload, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    delay(agency_a.id, upload.id, reason="jev down")
    assert _run(agency_a, upload, content, inventory=_inv(1), reads=())[0] is True


def test_an_unavailable_document_fails_the_upload(agency_a, membership_a, paid_cycle_a):
    from apps.concierge.documents import DocumentUnavailable

    upload, _ = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch(
            "apps.documents.transcript_pages.open_document",
            side_effect=DocumentUnavailable("x"),
        ),
        patch("apps.documents.transcript_pages.check_gates"),
    ):
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("FAILED", "document_unavailable")


def test_a_storage_error_delays_the_upload(agency_a, membership_a, paid_cycle_a):
    from botocore.exceptions import ClientError

    upload, _ = _upload(agency_a, membership_a, paid_cycle_a)
    error = ClientError({"Error": {"Code": "500"}}, "GetObject")
    with (
        patch("apps.documents.transcript_pages.open_document", side_effect=error),
        patch("apps.documents.transcript_pages.check_gates"),
    ):
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.attempts) == ("DELAYED", 1)


def test_a_retake_with_no_retakes_left_is_refused_before_it_is_charged(
    agency_a, membership_a, paid_cycle_a,
):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1, 2),
         reads=(PageRead(1, page=_page()), PageRead(2, refusal="cut_off")))
    for n in range(2):
        retake, content = _upload(agency_a, membership_a, paid_cycle_a,
                                  content=PNG + bytes([n]), mode="RETAKE", retake_slot=2)
        _run(agency_a, retake, content, inventory=_inv(1), reads=(PageRead(1, refusal="cut_off"),))
    third, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"3",
                             mode="RETAKE", retake_slot=2)
    assert _run(agency_a, third, content, inventory=_inv(1), reads=())[0] is False
    with tenant_scope(agency_a.id):
        third.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (third.state, third.refusal, paid_cycle_a.pages_used) == (
            "REFUSED", "retakes_used", 4,
        )


def test_replacing_with_the_same_file_keeps_the_pages(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    again, _ = _upload(agency_a, membership_a, paid_cycle_a, mode="REPLACE")
    _run(agency_a, again, content, inventory=_inv(1), reads=())
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0)]


def test_replacing_with_a_file_an_earlier_replace_superseded_keeps_its_pages(
    agency_a, membership_a, paid_cycle_a,
):
    x, content_x = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, x, content_x, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    y, content_y = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"y", mode="REPLACE")
    _run(agency_a, y, content_y, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    x2, _ = _upload(agency_a, membership_a, paid_cycle_a, mode="REPLACE")
    assert _run(agency_a, x2, content_x, inventory=_inv(1), reads=(PageRead(1, page=_page()),))[0]
    with tenant_scope(agency_a.id):
        assert list(TranscriptPage.objects.filter(
            cycle=paid_cycle_a, superseded_at__isnull=True).values_list("upload_id", flat=True)
        ) == [x2.id]


def test_a_read_upload_whose_assembly_keeps_failing_stays_charged(
    agency_a, membership_a, paid_cycle_a,
):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, upload, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    for _ in range(MAX_ATTEMPTS):
        delay(agency_a.id, upload.id, reason="jev down")
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (upload.state, paid_cycle_a.pages_used) == ("FAILED", 1)
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 0)]


def test_every_route_into_failed_refunds_the_unread_charge(agency_a, membership_a, paid_cycle_a):
    from apps.concierge.documents import DocumentUnavailable

    with tenant_scope(agency_a.id):
        StudentCycle.objects.filter(id=paid_cycle_a.id).update(pages_used=5)
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1, 2, 3)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=OcrUnavailable("x")),
    ):
        read_upload(agency_a.id, upload.id)
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 8
        TranscriptUpload.objects.filter(id=upload.id).update(next_attempt_at=timezone.now())
    with (
        patch(
            "apps.documents.transcript_pages.open_document",
            side_effect=DocumentUnavailable("x"),
        ),
        patch("apps.documents.transcript_pages.check_gates"),
    ):
        assert read_upload(agency_a.id, upload.id) is False
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (upload.state, upload.pages_counted, paid_cycle_a.pages_used) == ("FAILED", None, 5)


def test_capital_headers_still_tell_the_original_language():
    azerbaijani = _page(lines=("FƏNNİN ADI", "TƏLƏBƏNİN ADI: Aysel"),
                        tables=((("FƏNNİN ADI", "KREDİT", "QİYMƏT"), ("Kimya", "6", "Əla")),))
    turkish = _page(lines=("ÖĞRENCİ BELGESİ",),
                    tables=((("DERSİN ADI", "KREDİSİ", "HARF NOTU"), ("Kimya", "6", "AA")),))
    decomposed = _page(lines=("Ders Adı Kredi O\u0308g\u0306renci",), tables=())
    assert not is_english(azerbaijani)
    assert not is_english(turkish)
    assert not is_english(decomposed)


def test_a_file_read_between_the_check_and_the_lock_is_not_charged_again(
    agency_a, membership_a, paid_cycle_a,
):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    second, _ = _upload(agency_a, membership_a, paid_cycle_a)
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=second.id).update(
            file_sha256=hashlib.sha256(content).hexdigest()
        )
    assert _reserve(agency_a.id, second.id, 1) is True
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 1


def test_finishing_a_vanished_upload_does_nothing(agency_a):
    from uuid import uuid4

    from apps.documents.transcript_pages import _finish

    _finish(agency_a.id, uuid4(), "FAILED", "reading_off")


def test_a_twin_waiting_on_a_failed_upload_fails_with_it(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=OcrUnavailable("x")),
    ):
        read_upload(agency_a.id, first.id)
    twin, _ = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, twin, content, inventory=_inv(1), reads=())
    for _ in range(MAX_ATTEMPTS):
        delay(agency_a.id, first.id, reason="test")
    with tenant_scope(agency_a.id):
        twin.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (twin.state, twin.refusal, paid_cycle_a.pages_used) == (
            "FAILED", "reader_unavailable", 0,
        )


@pytest.fixture(autouse=True)
def _gates_open():
    """assemble checks the gates itself; the tests of the gates below put the real one back."""
    with patch("apps.documents.transcript_pages.check_gates") as gates:
        yield gates


def _reading():
    from datetime import date

    from apps.documents.transcript import Reading, Row, TranscriptContent, TranscriptCourse

    return Reading(
        content=TranscriptContent(
            institution="Baku State University", country_code="AZ", qualification="BSc",
            field="Chemistry", credit_unit="ECTS",
            courses=(TranscriptCourse(title="Organic Chemistry I", credits=6, status="COMPLETED"),),
            expected_completion=date(2027, 6, 30),
        ),
        rows=(Row(0, "course", "Organic Chemistry I", "6", "91", "COMPLETED"),),
        total_credits_line=None,
        doubts=(),
    )


def _read_all(agency, membership, cycle, *uploads):
    """Write pages for each (fields, reads) without assembling."""
    made = []
    for n, (fields, reads) in enumerate(uploads):
        upload, content = _upload(agency, membership, cycle, content=PNG + bytes([n]), **fields)
        _run(agency, upload, content, inventory=_inv(*range(1, len(reads) + 1)), reads=reads)
        made.append(upload)
    return made


def test_a_reading_is_assembled_from_live_pages_in_slot_order(
    agency_a, membership_a, paid_cycle_a
):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a,
                         ({}, (PageRead(1, page=_page()), PageRead(2, page=_page(lines=("p2",))))))
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, upload.id)
    pages = read.call_args.args[0]
    assert [page.lines for page in pages] == [("Transcript of Records",), ("p2",)]
    with tenant_scope(agency_a.id):
        reading = TranscriptReading.objects.get(document=upload.document)
        upload.refresh_from_db()
        assert (reading.cycle_id, upload.assembled) == (paid_cycle_a.id, True)


def test_a_page_waiting_for_its_retake_holds_the_reading_back(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a,
                         ({}, (PageRead(1, page=_page()), PageRead(2, refusal="cut_off"))))
    with patch("apps.documents.transcript_pages.read_from_pages") as read:
        assemble(agency_a.id, upload.id)
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        assert not TranscriptReading.objects.exists()


def test_a_page_out_of_retakes_no_longer_holds_it_back(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a,
                         ({}, (PageRead(1, page=_page()), PageRead(2, refusal="cut_off"))))
    with tenant_scope(agency_a.id):
        TranscriptPage.objects.filter(slot=2).update(retakes=2)
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, upload.id)
    assert len(read.call_args.args[0]) == 1


def test_an_upload_still_reading_holds_it_back_but_an_abandoned_one_does_not(
    agency_a, membership_a, paid_cycle_a
):
    [read_one] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"x")  # PENDING forever
    busy, _ = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"y")
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=busy.id).update(state="READING")
    with patch("apps.documents.transcript_pages.read_from_pages") as read:
        assemble(agency_a.id, read_one.id)
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=busy.id).update(state="REFUSED")
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, read_one.id)
    read.assert_called_once()


def test_once_a_translation_is_read_only_translation_pages_are_used(
    agency_a, membership_a, paid_cycle_a
):
    original, translation = _read_all(
        agency_a, membership_a, paid_cycle_a,
        ({}, (PageRead(1, page=_page(lines=("original",))),)),
        ({"role": "TRANSLATION"}, (PageRead(1, page=_page(lines=("translation",))),)),
    )
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, translation.id)
    assert [page.lines for page in read.call_args.args[0]] == [("translation",)]


def test_jev_down_after_pages_are_written_delays_the_assembly_only(
    agency_a, membership_a, paid_cycle_a
):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    down = DecisionsUnavailable("down")
    with patch("apps.documents.transcript_pages.read_from_pages", side_effect=down):
        assemble(agency_a.id, upload.id)
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.assembled, upload.attempts) == ("READ", False, 1)


def test_a_double_tap_twin_assembles_from_the_cycles_pages(agency_a, membership_a, paid_cycle_a):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    twin, _ = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, twin, content, inventory=_inv(1), reads=())
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read:
        assemble(agency_a.id, twin.id)
    assert len(read.call_args.args[0]) == 1


def test_process_upload_reads_then_assembles_and_a_rerun_does_neither(
    agency_a, membership_a, paid_cycle_a
):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)) as inv,
        patch("apps.documents.transcript_pages.read_inventory",
              return_value=(PageRead(1, page=_page()),)),
        patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()) as read,
    ):
        process_upload(agency_a.id, upload.id)
        process_upload(agency_a.id, upload.id)
    assert (inv.call_count, read.call_count) == (1, 1)
    with tenant_scope(agency_a.id):
        assert TranscriptReading.objects.count() == 1
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 1


@override_settings(DECISIONS_PROVIDER={"default": "adapter:openai"})
def test_assembly_refuses_a_provider_that_is_not_typesafe(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    with (
        patch("apps.documents.transcript_pages.check_gates", real_check_gates),
        patch("apps.documents.transcript_pages.read_from_pages") as read,
    ):
        process_upload(agency_a.id, upload.id)
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.assembled, upload.attempts) == ("READ", False, 1)
        assert not TranscriptReading.objects.exists()


def test_assembly_waits_while_the_jev_launch_gate_is_closed(
    agency_a, membership_a, paid_cycle_a, settings
):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    settings.TRANSCRIPT_JEV_ENABLED = False
    with (
        patch("apps.documents.transcript_pages.check_gates", real_check_gates),
        patch("apps.documents.transcript_pages.read_from_pages") as read,
    ):
        process_upload(agency_a.id, upload.id)
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.assembled, upload.attempts) == ("READ", False, 0)
        assert upload.next_attempt_at > timezone.now()
        assert not TranscriptReading.objects.exists()


def test_a_cycle_is_not_stranded_when_the_upload_it_waited_for_fails(
    agency_a, membership_a, paid_cycle_a
):
    [first] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    busy, _ = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"y")
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=busy.id).update(
            state="DELAYED", attempts=MAX_ATTEMPTS - 1
        )
    with patch("apps.documents.transcript_pages.read_from_pages") as read:
        assemble(agency_a.id, first.id)  # B is busy: assembled with no reading
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        first.refresh_from_db()
        assert first.assembled is True and not TranscriptReading.objects.exists()
    delay(agency_a.id, busy.id, reason="test")  # B runs out of attempts: FAILED
    with tenant_scope(agency_a.id):
        busy.refresh_from_db()
        first.refresh_from_db()
        assert (busy.state, first.assembled) == ("FAILED", False)
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()):
        process_upload(agency_a.id, first.id)
    with tenant_scope(agency_a.id):
        assert TranscriptReading.objects.filter(document=first.document).count() == 1


def test_a_refused_upload_also_reopens_the_assembly_it_blocked(
    agency_a, membership_a, paid_cycle_a
):
    [first] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    busy, content = _upload(agency_a, membership_a, paid_cycle_a, content=b"GIF89a")
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=busy.id).update(state="READING")
    assemble(agency_a.id, first.id)
    with patch("apps.documents.transcript_pages.open_document", return_value=content):
        from apps.documents.transcript_pages import _finish

        _finish(agency_a.id, busy.id, "REFUSED", "unsupported_file")
    with tenant_scope(agency_a.id):
        first.refresh_from_db()
        assert first.assembled is False


def test_a_concurrent_assembly_cannot_write_a_second_reading(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))

    def other_run_finishes_first(*args, **kwargs):
        with tenant_scope(agency_a.id):
            TranscriptUpload.objects.filter(id=upload.id).update(assembled=True)
        return _reading()

    with patch(
        "apps.documents.transcript_pages.read_from_pages", side_effect=other_run_finishes_first
    ):
        assemble(agency_a.id, upload.id)
    with tenant_scope(agency_a.id):
        assert not TranscriptReading.objects.exists()


def test_a_failing_upload_reopens_the_waiter_not_its_own_pageless_twin(
    agency_a, membership_a, paid_cycle_a
):
    [first] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    busy, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"y")
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=busy.id).update(
            state="DELAYED", attempts=MAX_ATTEMPTS - 1, pages_counted=1, file_sha256="d" * 64
        )
        twin = TranscriptUpload.objects.create(
            student=membership_a, cycle=paid_cycle_a, role="ORIGINAL", state="READ",
            assembled=True, file_sha256="d" * 64,
            document=register(agency_a.id, membership_a.id, kind="TRANSCRIPT"),
        )
    assemble(agency_a.id, first.id)  # B busy: A assembled with no reading
    delay(agency_a.id, busy.id, reason="test")  # B FAILED, which fails its twin too
    with tenant_scope(agency_a.id):
        first.refresh_from_db()
        twin.refresh_from_db()
        assert (twin.state, first.assembled) == ("FAILED", False)
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()):
        process_upload(agency_a.id, first.id)
    with tenant_scope(agency_a.id):
        assert TranscriptReading.objects.filter(document=first.document).count() == 1


# --- final-review fixes -------------------------------------------------------------------


def test_a_first_photo_the_gate_refuses_waits_for_its_retake(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    reads = (PageRead(1, refusal="text_too_small"),)
    assert _run(agency_a, upload, content, inventory=_inv(1), reads=reads)[0] is True
    assert _live(agency_a, paid_cycle_a) == [(1, "REFUSED", "text_too_small", 0)]
    retake, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"r",
                              mode="RETAKE", retake_slot=1)
    assert _run(agency_a, retake, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))[0]
    assert _live(agency_a, paid_cycle_a) == [(1, "READ", "", 1)]


def test_a_pdf_whose_table_page_is_refused_keeps_both_pages(agency_a, membership_a, paid_cycle_a):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    reads = (PageRead(1, refusal="cut_off"), PageRead(2, page=_page(tables=())))
    assert _run(agency_a, upload, content, inventory=_inv(1, 2), reads=reads)[0] is True
    assert _live(agency_a, paid_cycle_a) == [(1, "REFUSED", "cut_off", 0), (2, "READ", "", 0)]
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert upload.state == "READ"


def test_a_stranded_upload_is_reopened_although_an_older_upload_has_a_reading(
    agency_a, membership_a, paid_cycle_a
):
    a, content_a = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"a")
    [b] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    with patch("apps.documents.transcript_pages.read_from_pages", return_value=_reading()):
        assemble(agency_a.id, b.id)
    c, _ = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"c")
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=c.id).update(state="DELAYED", attempts=MAX_ATTEMPTS - 1)
    _run(agency_a, a, content_a, inventory=_inv(1),
         reads=(PageRead(1, page=_page(lines=("a",))),))
    with patch("apps.documents.transcript_pages.read_from_pages") as read:
        assemble(agency_a.id, a.id)  # C is busy: A assembled with no reading
    read.assert_not_called()
    delay(agency_a.id, c.id, reason="test")  # C runs out of attempts: FAILED
    with tenant_scope(agency_a.id):
        a.refresh_from_db()
        assert a.assembled is False
    with patch(
        "apps.documents.transcript_pages.read_from_pages", return_value=_reading()
    ) as read:
        process_upload(agency_a.id, a.id)
    assert ("a",) in [page.lines for page in read.call_args.args[0]]
    with tenant_scope(agency_a.id):
        assert TranscriptReading.objects.filter(document=a.document).count() == 1


def test_an_upload_older_than_a_written_replace_is_refused_and_refunded(
    agency_a, membership_a, paid_cycle_a
):
    _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    a, content_a = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"a")
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content_a),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=OcrUnavailable("x")),
    ):
        read_upload(agency_a.id, a.id)
    b, content_b = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"b",
                           mode="REPLACE")
    _run(agency_a, b, content_b, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 3
        TranscriptUpload.objects.filter(id=a.id).update(next_attempt_at=timezone.now())
    done, _, _ = _run(agency_a, a, content_a, inventory=_inv(1),
                      reads=(PageRead(1, page=_page()),))
    assert done is False
    with tenant_scope(agency_a.id):
        a.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (a.state, a.refusal, a.pages_counted, paid_cycle_a.pages_used) == (
            "REFUSED", "replaced", None, 2,
        )
        assert list(TranscriptPage.objects.filter(
            cycle=paid_cycle_a, superseded_at__isnull=True).values_list("upload_id", flat=True)
        ) == [b.id]


def _request_erasure(agency, membership):
    from apps.audit.models import DeletionRequest

    with tenant_scope(agency.id):
        DeletionRequest.objects.create(tenant=agency, student=membership, state="REQUESTED")


def _deactivate(agency, membership):
    from apps.tenancy.models import Membership

    with tenant_scope(agency.id):
        Membership.objects.filter(id=membership.id).update(active=False)


@pytest.mark.parametrize("erase", [_request_erasure, _deactivate])
def test_nothing_is_read_for_a_student_being_erased(agency_a, membership_a, paid_cycle_a, erase):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)
    erase(agency_a, membership_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.inventory") as inv,
        patch("apps.documents.transcript_pages.read_inventory") as read,
        patch("apps.documents.transcript_pages.read_from_pages") as jev,
    ):
        process_upload(agency_a.id, upload.id)
    assert (inv.call_count, read.call_count, jev.call_count) == (0, 0, 0)
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("FAILED", "erasure_requested")


def test_no_reading_is_assembled_for_a_student_being_erased(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    _request_erasure(agency_a, membership_a)
    with patch("apps.documents.transcript_pages.read_from_pages") as jev:
        assemble(agency_a.id, upload.id)
    jev.assert_not_called()
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("FAILED", "erasure_requested")
        assert not TranscriptReading.objects.exists()


def test_pages_read_while_the_membership_ended_are_not_written(
    agency_a, membership_a, paid_cycle_a
):
    upload, content = _upload(agency_a, membership_a, paid_cycle_a)

    def azure_then_erased(*args, **kwargs):
        _deactivate(agency_a, membership_a)
        return (PageRead(1, page=_page()),)

    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=azure_then_erased),
    ):
        assert read_upload(agency_a.id, upload.id) is False
    assert _live(agency_a, paid_cycle_a) == []
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("FAILED", "erasure_requested")


def test_proper_names_and_repeated_words_do_not_make_a_page_the_original():
    metu = _page(lines=("Middle East Technical University", "Orta Doğu Teknik Üniversitesi",
                        "Fen Edebiyat Fakültesi", "Kimya Bölümü", "Transcript of Records"))
    repeated = _page(lines=("Sponsor: Kredi Bank", "Kredi Bank scholarship", "Kredi Bank award"))
    assert is_english(metu)
    assert is_english(repeated)


def test_a_twin_waiting_on_a_refused_upload_is_refused_with_it(
    agency_a, membership_a, paid_cycle_a
):
    first, content = _upload(agency_a, membership_a, paid_cycle_a)
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=OcrUnavailable("x")),
    ):
        read_upload(agency_a.id, first.id)
    twin, _ = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, twin, content, inventory=_inv(1), reads=())
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=first.id).update(next_attempt_at=timezone.now())
    _run(agency_a, first, content, inventory=_inv(1), reads=(PageRead(1, page=_page(tables=())),))
    with tenant_scope(agency_a.id):
        first.refresh_from_db()
        twin.refresh_from_db()
        assert (first.state, first.refusal) == ("REFUSED", "not_a_transcript")
        assert (twin.state, twin.refusal) == ("REFUSED", "not_a_transcript")


def test_a_reader_refusal_fails_the_assembly_at_once(agency_a, membership_a, paid_cycle_a):
    [upload] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    refused = DecisionsUnavailable("no", kind="refused")
    with patch("apps.documents.transcript_pages.read_from_pages", side_effect=refused):
        assemble(agency_a.id, upload.id)
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal, upload.attempts) == ("FAILED", "reader_refused", 0)


def test_a_replace_refuses_itself_when_a_page_was_added_after_it_was_sent(
    agency_a, membership_a, paid_cycle_a
):
    [old] = _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    b, content_b = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"b",
                           mode="REPLACE")
    c, content_c = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"c")
    _run(agency_a, c, content_c, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    reads = (PageRead(1, page=_page()), PageRead(2, page=_page()))
    assert _run(agency_a, b, content_b, inventory=_inv(1, 2), reads=reads)[0] is False
    with tenant_scope(agency_a.id):
        live = list(TranscriptPage.objects.filter(cycle=paid_cycle_a, superseded_at__isnull=True)
                    .order_by("slot").values_list("slot", "upload_id"))
        assert live == [(1, old.id), (2, c.id)]
        paid_cycle_a.refresh_from_db()
        b.refresh_from_db()
        assert (paid_cycle_a.pages_used, b.refusal) == (2, "newer_upload")


def test_a_retake_sent_before_the_replace_goes_with_it_when_the_replace_writes(
    agency_a, membership_a, paid_cycle_a
):
    _read_all(agency_a, membership_a, paid_cycle_a,
              ({}, (PageRead(1, page=_page()), PageRead(2, refusal="cut_off"))))
    r, content_r = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"r",
                           mode="RETAKE", retake_slot=2)
    b, content_b = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"b",
                           mode="REPLACE")
    _run(agency_a, r, content_r, inventory=_inv(1), reads=(PageRead(1, page=_page()),))
    assert _run(agency_a, b, content_b, inventory=_inv(1), reads=(PageRead(1, page=_page()),))[0]
    with tenant_scope(agency_a.id):
        assert list(TranscriptPage.objects.filter(cycle=paid_cycle_a, superseded_at__isnull=True)
                    .values_list("slot", "upload_id")) == [(1, b.id)]
        assert TranscriptPage.objects.get(upload=r).superseded_at is not None
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 4  # the retake was read: its charge stays


def test_a_replace_with_a_newer_upload_is_refused_before_it_is_charged(
    agency_a, membership_a, paid_cycle_a
):
    _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    b, content_b = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"b",
                           mode="REPLACE")
    _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"c", mode="RETAKE",
            retake_slot=1)
    with tenant_scope(agency_a.id):
        used = StudentCycle.objects.get(id=paid_cycle_a.id).pages_used
    done, _, read = _run(agency_a, b, content_b, inventory=_inv(1),
                         reads=(PageRead(1, page=_page()),))
    assert done is False
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        b.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (b.state, b.refusal, b.pages_counted, paid_cycle_a.pages_used) == (
            "REFUSED", "newer_upload", None, used,
        )


def test_a_replace_overtaken_while_azure_read_is_refused_and_refunded(
    agency_a, membership_a, paid_cycle_a
):
    _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    b, content_b = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"b",
                           mode="REPLACE")
    with tenant_scope(agency_a.id):
        used = StudentCycle.objects.get(id=paid_cycle_a.id).pages_used
    before = _live(agency_a, paid_cycle_a)

    def newer_arrives(*args, **kwargs):
        _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"c")
        return (PageRead(1, page=_page()),)

    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content_b),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=newer_arrives),
    ):
        assert read_upload(agency_a.id, b.id) is False
    with tenant_scope(agency_a.id):
        b.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (b.state, b.refusal, paid_cycle_a.pages_used) == ("REFUSED", "newer_upload", used)
    assert _live(agency_a, paid_cycle_a) == before


def _age(agency, upload, minutes):
    with tenant_scope(agency.id):
        TranscriptUpload.objects.filter(id=upload.id).update(
            created_at=timezone.now() - timedelta(minutes=minutes)
        )


def test_retrying_a_stalled_replace_with_the_same_file_loses_neither(
    agency_a, membership_a, paid_cycle_a
):
    _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    r1, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"r",
                          mode="REPLACE")
    # R1 got as far as being charged, then its worker died.
    with (
        patch("apps.documents.transcript_pages.open_document", return_value=content),
        patch("apps.documents.transcript_pages.check_gates"),
        patch("apps.documents.transcript_pages.inventory", return_value=_inv(1)),
        patch("apps.documents.transcript_pages.read_inventory", side_effect=KeyboardInterrupt),
        pytest.raises(KeyboardInterrupt),
    ):
        read_upload(agency_a.id, r1.id)
    r2, _ = _upload(agency_a, membership_a, paid_cycle_a, content=content, mode="REPLACE")
    done, _, _ = _run(agency_a, r2, content, inventory=_inv(1),
                      reads=(PageRead(1, page=_page()),))  # a pageless twin of R1
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(id=r1.id).update(next_attempt_at=timezone.now())
    assert _run(agency_a, r1, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))[0]
    with tenant_scope(agency_a.id):
        assert list(TranscriptPage.objects.filter(cycle=paid_cycle_a, superseded_at__isnull=True)
                    .values_list("upload_id", flat=True)) == [r1.id]


def _stalled_replace(agency, membership, cycle):
    [first] = _read_all(agency, membership, cycle, ({}, (PageRead(1, page=_page()),)))
    _age(agency, first, 120)
    r, content = _upload(agency, membership, cycle, content=PNG + b"r", mode="REPLACE")
    _age(agency, r, 30)
    return r, content


def test_a_refused_newer_upload_does_not_stop_a_replace(agency_a, membership_a, paid_cycle_a):
    r, content = _stalled_replace(agency_a, membership_a, paid_cycle_a)
    heic, heic_content = _upload(agency_a, membership_a, paid_cycle_a)
    _run(agency_a, heic, b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64,
         inventory=_inv(1), reads=())
    with tenant_scope(agency_a.id):
        assert TranscriptUpload.objects.get(id=heic.id).refusal == "heic"
    assert _run(agency_a, r, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))[0]


def test_an_abandoned_newer_upload_does_not_stop_a_replace(agency_a, membership_a, paid_cycle_a):
    r, content = _stalled_replace(agency_a, membership_a, paid_cycle_a)
    _age(agency_a, r, 60)
    never_sent, _ = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"n")
    with tenant_scope(agency_a.id):
        never_sent.document.state = "PENDING"
        never_sent.document.save(update_fields=["state"])
    _age(agency_a, never_sent, 25)
    assert _run(agency_a, r, content, inventory=_inv(1), reads=(PageRead(1, page=_page()),))[0]


def test_a_revived_charged_replace_with_a_newer_upload_is_not_read_again(
    agency_a, membership_a, paid_cycle_a
):
    _read_all(agency_a, membership_a, paid_cycle_a, ({}, (PageRead(1, page=_page()),)))
    r, content = _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"r",
                         mode="REPLACE")
    with tenant_scope(agency_a.id):
        used = StudentCycle.objects.get(id=paid_cycle_a.id).pages_used
        StudentCycle.objects.filter(id=paid_cycle_a.id).update(pages_used=used + 1)
        TranscriptUpload.objects.filter(id=r.id).update(pages_counted=1)
    _upload(agency_a, membership_a, paid_cycle_a, content=PNG + b"c")
    done, _, read = _run(agency_a, r, content, inventory=_inv(1),
                         reads=(PageRead(1, page=_page()),))
    assert done is False
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        r.refresh_from_db()
        paid_cycle_a.refresh_from_db()
        assert (r.refusal, r.pages_counted, paid_cycle_a.pages_used) == (
            "newer_upload", None, used,
        )
