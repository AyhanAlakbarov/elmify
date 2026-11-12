"""Plan 4, Task 6: each document an application sends, prepared to its file rules."""

import hashlib
import logging
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.documents import storage
from apps.documents.models import DocumentDraft
from apps.documents.ocr import Prepared
from apps.portals.models import Application, PreparedDocument
from apps.portals.prepare import current_prepared, file_name, jobs_for, prepare_documents
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db
PDF = b"%PDF-x"


class _Store:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[tuple[str, str]] = []
        self.fail_delete = False
        self._n = 0

    def put(self, key: str, body: bytes) -> str:
        self.objects[key] = body
        self._n += 1
        return f"v{self._n}"

    def delete_version(self, key: str, version_id: str) -> None:
        if self.fail_delete:
            raise RuntimeError("AccessDenied secret-key")
        self.deleted.append((key, version_id))
        self.objects.pop(key, None)


def _fake_pdf(parts, rule):
    return Prepared(
        content_type="application/pdf", sha256=hashlib.sha256(PDF).hexdigest(), body=PDF
    )


def _never(*_):
    raise AssertionError("the parser was called")


def _r(document, field, value):
    return {"document": document, "field": field, "value": value}


@pytest.fixture(autouse=True)
def _scope(agency_a, monkeypatch):
    monkeypatch.setattr(storage, "read_draft", lambda draft, filename: b"%PDF-cv")
    with tenant_scope(agency_a.id):
        yield


def _application(agency, student, *sentences):
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), kit_requirements=list(sentences)
    )


def _cv(agency, student):
    return DocumentDraft.objects.create(
        tenant=agency, student=student, kind=DocumentDraft.Kind.CV, version=1, content={},
        status=DocumentDraft.Status.APPROVED, rendered_filename="cv-standard.pdf",
    )


def _upload(agency, student, kind):
    document_id = uuid4()
    return DocumentVersion.objects.create(
        id=document_id, tenant=agency, student=student, object_key=f"k/{document_id}", kind=kind,
        state="AVAILABLE", content_type="application/pdf",
        promoted_key=f"tenants/{agency.id}/students/{student.id}/uploads/{document_id}/v1",
    )


@pytest.fixture
def application_with_cv(agency_a, membership_a):
    _cv(agency_a, membership_a)
    return _application(agency_a, membership_a, "A CV.")


@pytest.fixture
def application_with_diploma(agency_a, membership_a):
    _upload(agency_a, membership_a, "DIPLOMA")
    return _application(agency_a, membership_a, "Your diploma.")


@pytest.fixture
def application_with_cv_draft_and_cv_upload(agency_a, membership_a):
    _upload(agency_a, membership_a, "CV")
    _cv(agency_a, membership_a)
    return _application(agency_a, membership_a, "A CV.")


@pytest.fixture
def application_with_cv_and_diploma(agency_a, membership_a):
    _cv(agency_a, membership_a)
    _upload(agency_a, membership_a, "DIPLOMA")
    return _application(agency_a, membership_a, "A CV.", "Your diploma.")


@pytest.fixture
def application_with_cv_diploma_passport(agency_a, membership_a):
    _cv(agency_a, membership_a)
    _upload(agency_a, membership_a, "DIPLOMA")
    _upload(agency_a, membership_a, "PASSPORT")
    return _application(agency_a, membership_a, "A CV.", "Your diploma.")


def _kind_of(source):
    kind, source_id = source
    if kind == "draft":
        return DocumentDraft.objects.get(id=source_id).kind
    return DocumentVersion.objects.get(id=source_id).kind


def _replace_diploma(application):
    """What a REPLACE upload leaves once promoted: the older diploma retired."""
    from django.utils import timezone

    DocumentVersion.objects.filter(student=application.student, kind="DIPLOMA").update(
        retired_at=timezone.now()
    )
    _upload(application.tenant, application.student, "DIPLOMA")


def _two_diplomas(agency, student):
    """A bachelor's then a master's, both added (plan 4b Task 6, Review Focus 4)."""
    from datetime import timedelta

    from django.utils import timezone

    bachelor = _upload(agency, student, "DIPLOMA")
    master = _upload(agency, student, "DIPLOMA")
    now = timezone.now()
    DocumentVersion.objects.filter(id=bachelor.id).update(created_at=now - timedelta(days=2))
    DocumentVersion.objects.filter(id=master.id).update(created_at=now - timedelta(days=1))
    return bachelor, master


def test_no_rule_prepares_nothing(application_with_cv):
    assert prepare_documents(application_with_cv, transform=_never, store=_Store()) == []


def test_a_cv_cap_prepares_the_cv_under_the_student_prefix(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    [prepared] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    assert prepared.state == "READY" and prepared.slot.startswith("CV:")
    assert prepared.object_key.startswith(
        f"tenants/{application_with_cv.tenant_id}/students/{application_with_cv.student_id}/prepared/"
    )
    assert store.objects[prepared.object_key] == PDF
    assert (prepared.filename, prepared.byte_size) == ("cv-standard.pdf", len(PDF))


def test_only_the_document_the_table_holds_is_prepared(application_with_cv_draft_and_cv_upload):
    """The table sends the approved CV draft, not also the student's uploaded CV."""
    application_with_cv_draft_and_cv_upload.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    [job] = jobs_for(application_with_cv_draft_and_cv_upload)
    assert job.sources[0][0] == "draft"


def test_the_bundle_leaves_out_what_the_programme_does_not_list(
    application_with_cv_diploma_passport,
):
    """Owner 2026-10-09: only what the programme lists. Its kit_requirements name
    the CV and the diploma; the passport the student holds stays out."""
    application_with_cv_diploma_passport.kit_file_rules = [
        _r("EVERY_DOCUMENT", "combine", "ONE_FILE")
    ]
    [job] = jobs_for(application_with_cv_diploma_passport)
    assert {_kind_of(s) for s in job.sources} == {"CV", "DIPLOMA"}


def test_the_bundle_replaces_every_per_document_job(application_with_cv_and_diploma):
    application_with_cv_and_diploma.kit_file_rules = [
        _r("EVERY_DOCUMENT", "combine", "ONE_FILE"), _r("DIPLOMA", "max_bytes", 2_000_000)
    ]
    [job] = jobs_for(application_with_cv_and_diploma)
    assert job.slot == "EVERY_DOCUMENT" and job.sources[0][0] == "draft"  # the CV leads


def test_a_refusal_is_recorded_with_its_reason(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    [prepared] = prepare_documents(
        application_with_cv, transform=lambda *_: Prepared(refused="signed"), store=_Store()
    )
    assert (prepared.state, prepared.reason, prepared.object_key) == ("CANNOT_FIT", "signed", "")


def test_re_preparing_a_slot_after_its_rules_change_updates_the_row(application_with_cv):
    """The row moves to the new object and the old version is deleted."""
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    [first] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    first_digest, first_key = first.inputs_digest, first.object_key
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 1_000_000)]  # a re-read page
    [second] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    assert second.id == first.id
    assert second.inputs_digest != first_digest and second.object_key != first_key
    assert second.object_key in store.objects
    assert PreparedDocument.objects.filter(application=application_with_cv).count() == 1
    assert store.deleted == [(first_key, "v1")]
    assert second.object_version == "v2"


def test_a_slot_dropped_from_the_rules_loses_its_row_and_object(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    [first] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    application_with_cv.kit_file_rules = []  # rules re-read with no CV rule
    assert prepare_documents(application_with_cv, transform=_never, store=store) == []
    assert not PreparedDocument.objects.filter(application=application_with_cv).exists()
    assert store.deleted == [(first.object_key, "v1")]


def test_the_sweep_spares_a_row_written_after_the_run_started(application_with_cv):
    from datetime import timedelta

    from django.utils import timezone

    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    kw = {"application": application_with_cv, "tenant": application_with_cv.tenant,
          "student": application_with_cv.student, "state": "READY",
          "object_version": "vx", "inputs_digest": "d", "document": "DIPLOMA"}
    old = PreparedDocument.objects.create(slot="DIPLOMA:old", object_key="k-old", **kw)
    new = PreparedDocument.objects.create(slot="DIPLOMA:new", object_key="k-new", **kw)
    PreparedDocument.objects.filter(id=old.id).update(
        prepared_at=timezone.now() - timedelta(hours=1))
    PreparedDocument.objects.filter(id=new.id).update(
        prepared_at=timezone.now() + timedelta(hours=1))  # a concurrent run's, after our start
    prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    slots = set(PreparedDocument.objects.filter(
        application=application_with_cv).values_list("slot", flat=True))
    assert "DIPLOMA:new" in slots and "DIPLOMA:old" not in slots
    assert ("k-old", "vx") in store.deleted and ("k-new", "vx") not in store.deleted


def test_a_failed_delete_leaves_the_run_ready_and_logs_a_warning(application_with_cv, caplog):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    store.fail_delete = True
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 1_000_000)]
    with caplog.at_level(logging.WARNING, logger="apps.portals.prepare"):
        [second] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    assert second.state == "READY"
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert "secret-key" not in caplog.text and second.object_key not in caplog.text


def test_a_second_run_with_nothing_changed_does_not_call_the_parser(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    prepare_documents(application_with_cv, transform=_fake_pdf, store=_Store())
    assert prepare_documents(application_with_cv, transform=_never, store=_Store())


def test_a_parser_that_does_not_answer_stops_the_run_after_one_call(
    application_with_cv_and_diploma,
):
    """A down parser is down for every job: one call, then the run stops and says
    so (the worker stops its other applications too). Nothing is recorded."""
    from apps.documents.ocr_errors import OcrUnavailable

    calls = []

    def _down(*_):
        calls.append(1)
        raise OcrUnavailable("down")

    application = application_with_cv_and_diploma
    application.kit_file_rules = [_r("CV", "max_bytes", 2_000_000),
                                  _r("DIPLOMA", "max_bytes", 2_000_000)]
    assert len(jobs_for(application)) == 2
    with pytest.raises(OcrUnavailable):
        prepare_documents(application, transform=_down, store=_Store())
    assert len(calls) == 1
    assert not PreparedDocument.objects.filter(application=application).exists()


def test_a_job_that_times_out_is_recorded_and_the_run_goes_on(application_with_cv_and_diploma):
    from apps.documents.ocr_errors import OcrUnavailable

    application = application_with_cv_and_diploma
    application.kit_file_rules = [_r("CV", "max_bytes", 2_000_000),
                                  _r("DIPLOMA", "max_bytes", 2_000_000)]
    jobs = jobs_for(application)
    assert len(jobs) == 2
    calls = []

    def _second_times_out(parts, rule):
        calls.append(1)
        if len(calls) == 2:
            raise OcrUnavailable("function error Sandbox.Timedout", kind="job")
        return _fake_pdf(parts, rule)

    prepare_documents(application, transform=_second_times_out, store=_Store())
    rows = {r.slot: r for r in PreparedDocument.objects.filter(application=application)}
    assert len(calls) == 2 and len(rows) == 2
    assert sorted(r.state for r in rows.values()) == [
        PreparedDocument.State.CANNOT_FIT, PreparedDocument.State.READY]
    assert [r.reason for r in rows.values() if r.state == PreparedDocument.State.CANNOT_FIT] == [
        "timed_out"]


def test_an_outage_after_the_first_job_stops_the_run(application_with_cv_and_diploma):
    from apps.documents.ocr_errors import OcrUnavailable

    application = application_with_cv_and_diploma
    application.kit_file_rules = [_r("CV", "max_bytes", 2_000_000),
                                  _r("DIPLOMA", "max_bytes", 2_000_000)]
    calls = []

    def _down_second(parts, rule):
        calls.append(1)
        if len(calls) == 2:
            raise OcrUnavailable("down", kind="outage")
        return _fake_pdf(parts, rule)

    with pytest.raises(OcrUnavailable):
        prepare_documents(application, transform=_down_second, store=_Store())
    assert len(calls) == 2


def test_a_function_wide_fault_stops_the_run_through_the_real_mapping(
    application_with_cv_and_diploma, monkeypatch
):
    from apps.documents import ocr
    from apps.documents.ocr_errors import OcrUnavailable

    application = application_with_cv_and_diploma
    application.kit_file_rules = [_r("CV", "max_bytes", 2_000_000),
                                  _r("DIPLOMA", "max_bytes", 2_000_000)]
    calls = []

    class _Client:
        def invoke(self, **_):
            import io
            import json
            calls.append(1)
            return {"Payload": io.BytesIO(json.dumps({"errorType": "KeyError"}).encode()),
                    "FunctionError": "Unhandled"}

    monkeypatch.setattr(ocr, "_lambda_client", lambda: _Client())
    monkeypatch.setattr("django.conf.settings.OCR_FUNCTION_NAME", "f")
    monkeypatch.setattr("apps.portals.prepare._parts", lambda job: [ocr.Part(own=b"x")])
    with pytest.raises(OcrUnavailable):
        prepare_documents(application, transform=ocr.prepare_files, store=_Store())
    assert len(calls) == 1
    assert not PreparedDocument.objects.filter(application=application).exists()


def test_jobs_past_the_time_budget_are_left_for_the_next_trigger(
    application_with_cv_and_diploma, monkeypatch
):
    from types import SimpleNamespace

    from apps.portals import prepare

    clock = [0.0]
    monkeypatch.setattr(prepare, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []

    def _slow(parts, rule):
        calls.append(1)
        clock[0] += 10  # one parser call spends the whole budget
        return _fake_pdf(parts, rule)

    application = application_with_cv_and_diploma
    application.kit_file_rules = [_r("CV", "max_bytes", 2_000_000),
                                  _r("DIPLOMA", "max_bytes", 2_000_000)]
    prepared = prepare_documents(application, transform=_slow, store=_Store(), budget=5)
    assert len(calls) == 1 and len(prepared) == 1


def test_a_slot_written_by_another_worker_meanwhile_is_skipped_not_raised(
    application_with_cv, monkeypatch, caplog
):
    """Two workers preparing one slot: the loser's insert hits prepareddoc_one_per_slot.
    That is a race, not a bug -- logged at info, no traceback for the crash alarm."""
    import logging

    from django.db import IntegrityError

    def _race(self, **_kw):
        raise IntegrityError("prepareddoc_one_per_slot")

    monkeypatch.setattr(type(PreparedDocument.objects), "update_or_create", _race)
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    with caplog.at_level(logging.INFO):
        assert prepare_documents(application_with_cv, transform=_fake_pdf, store=store) == []
    assert "written concurrently" in caplog.text
    # The loser's own just-stored object is removed; it can never be the winner's.
    assert len(store.deleted) == 1 and store.objects == {}
    assert not [r for r in caplog.records if r.exc_info]


def test_review_focus_3_a_replaced_upload_makes_the_prepared_file_stale(application_with_diploma):
    application_with_diploma.kit_file_rules = [_r("DIPLOMA", "max_bytes", 2_000_000)]
    prepare_documents(application_with_diploma, transform=_fake_pdf, store=_Store())
    assert set(current_prepared(application_with_diploma)) == {
        job.slot for job in jobs_for(application_with_diploma)
    }
    _replace_diploma(application_with_diploma)  # a newer upload now fills the cell
    assert current_prepared(application_with_diploma) == {}


def test_names_never_guess_a_surname():
    assert file_name(
        "{surname}_CV.pdf", full_name="Aysel Məmmədova", fallback="cv-standard.pdf",
        extension=".pdf",
    ) == ("cv-standard.pdf", "name_needs_name_parts")
    assert file_name(
        "{full_name}_CV.pdf", full_name="Aysel Məmmədova", fallback="x.pdf", extension=".pdf"
    ) == ("Aysel_Memmedova_CV.pdf", "")
    assert file_name(
        "{surname}_CV.pdf", full_name="Aysel Məmmədova", fallback="x.pdf", extension=".pdf",
        surname="Məmmədova",
    ) == ("Memmedova_CV.pdf", "")
    assert file_name(
        "{surname}_CV.pdf", full_name="Lukas Weiß", fallback="x.pdf", extension=".pdf",
        surname="Weiß",
    ) == ("Weiss_CV.pdf", "")
    assert file_name(
        "{surname}_CV.pdf", full_name="Freja Sørensen", fallback="x.pdf", extension=".pdf",
        surname="Sørensen",
    ) == ("Sorensen_CV.pdf", "")


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        # No extension in the pattern: a dot in the name is not one.
        ("{full_name}", ("Aysel_M._Memmedova.pdf", "")),
        ("{full_name}_CV.PDF", ("Aysel_M._Memmedova_CV.pdf", "")),
        # A placeholder we cannot fill is never left in as text.
        ("{full_name}_{programme}.pdf", ("cv-standard.pdf", "name_unknown_placeholder")),
        # Leading dots never survive; nothing left is no name.
        ("../../x.pdf", ("x.pdf", "")),
        (".pdf", ("cv-standard.pdf", "name_unsafe")),
        # Storage refuses any name containing "..": never hand it one.
        ("a..b.pdf", ("cv-standard.pdf", "name_unsafe")),
    ],
)
def test_a_pattern_fills_only_what_it_names(pattern, expected):
    assert file_name(pattern, full_name="Aysel M. Məmmədova", fallback="cv-standard.pdf",
                     extension=".pdf") == expected


def test_a_name_that_does_not_fold_to_ascii_falls_back_rather_than_vanishing():
    """A Cyrillic name would fold to "_CV.pdf": the page's pattern, minus the name."""
    assert file_name(
        "{full_name}_CV.pdf", full_name="Айсель", fallback="cv-standard.pdf", extension=".pdf"
    ) == ("cv-standard.pdf", "name_unsafe")
    assert file_name(
        "{full_name}_CV.pdf", full_name="", fallback="cv-standard.pdf", extension=".pdf"
    ) == ("cv-standard.pdf", "name_unsafe")


@pytest.mark.django_db(transaction=True)
def test_preparation_reads_and_writes_behind_row_level_security(
    application_with_cv, rls_enforced_orm
):
    """Behind a NOBYPASSRLS role a read outside a tenant_transaction matches
    nothing (CLAUDE.md, failure mode 1): the CV would vanish from the table and
    nothing would be prepared, silently. The default test role cannot see that."""
    from apps.tenancy.db import tenant_transaction

    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    [prepared] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    assert prepared.state == "READY" and prepared.object_key in store.objects
    with tenant_transaction(application_with_cv.tenant_id):
        assert set(current_prepared(application_with_cv)) == {prepared.slot}


def _capture(sent):
    def transform(parts, rule):
        sent.append(rule.max_bytes)
        return _fake_pdf(parts, rule)
    return transform


def test_a_cap_above_what_the_parser_can_return_is_sent_as_4_mb(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 10_000_000)]
    sent: list = []
    prepare_documents(application_with_cv, transform=_capture(sent), store=_Store())
    assert sent == [4_000_000]


def test_a_cap_below_4_mb_is_sent_as_it_is(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    sent: list = []
    prepare_documents(application_with_cv, transform=_capture(sent), store=_Store())
    assert sent == [2_000_000]


def test_a_refusal_is_logged_once_without_student_values(application_with_cv, caplog):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    with caplog.at_level(logging.INFO):
        prepare_documents(application_with_cv, transform=lambda *_: Prepared(refused="too_large"),
                          store=_Store())
    lines = [r.getMessage() for r in caplog.records if "prepare.refused" in r.getMessage()]
    assert lines == [f"prepare.refused reason=too_large document=CV "
                     f"application={application_with_cv.id}"]


def test_jobs_for_names_the_file_from_the_confirmed_name_parts(agency_a, membership_a):
    from django.utils import timezone

    from apps.documents.models import VerifiedFact

    VerifiedFact.objects.create(
        student=membership_a, category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": "Aysel Məmmədova", "surname": "Məmmədova", "given_name": "Aysel"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="gap-interview",
        confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a,
    )
    _cv(agency_a, membership_a)
    application = _application(agency_a, membership_a, "A CV.")
    application.kit_file_rules = [_r("CV", "name_pattern", "{given_name}_{surname}_CV.pdf")]
    assert [j.filename for j in jobs_for(application)] == ["Aysel_Memmedova_CV.pdf"]


def test_jobs_for_takes_a_passports_given_names_as_the_given_name(agency_a, membership_a):
    """A passport read writes one IDENTITY row per key, given_names among them."""
    from django.utils import timezone

    from apps.documents.models import VerifiedFact

    for payload in ({"full_name": "Nərmin Əliyeva"}, {"surname": "ƏLIYEVA"},
                    {"given_names": "NƏRMIN"}):
        VerifiedFact.objects.create(
            student=membership_a, category=VerifiedFact.Category.IDENTITY, payload=payload,
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:00000000-0000-0000-0000-000000000001",
            confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a,
        )
    _cv(agency_a, membership_a)
    application = _application(agency_a, membership_a, "A CV.")
    application.kit_file_rules = [_r("CV", "name_pattern", "{given_name}_{surname}_CV.pdf")]
    [job] = jobs_for(application)
    assert job.filename == "NERMIN_ELIYEVA_CV.pdf"


def test_a_missing_given_name_keeps_the_fallback():
    assert file_name(
        "{given_name}_{surname}_CV.pdf", full_name="A B", fallback="x.pdf", extension=".pdf",
        surname="B",
    ) == ("x.pdf", "name_needs_name_parts")


# Several diplomas (plan 4b Task 6) --------------------------------------------


def test_review_focus_4_all_diplomas_as_one_pdf_is_one_job_oldest_first(agency_a, membership_a):
    bachelor, master = _two_diplomas(agency_a, membership_a)
    application = _application(agency_a, membership_a, "Your diplomas.")
    application.kit_file_rules = [_r("DIPLOMA", "combine", "ONE_FILE")]
    [job] = jobs_for(application)
    assert job.slot == "DIPLOMA" and job.document == "DIPLOMA"
    assert job.sources == (("upload", bachelor.id), ("upload", master.id))
    assert job.filename == "diploma.pdf" and job.rule.format == "PDF"
    seen = []

    def _transform(parts, rule):
        seen.append([part.upload.id for part in parts])
        return _fake_pdf(parts, rule)

    [row] = prepare_documents(application, transform=_transform, store=_Store())
    assert seen == [[bachelor.id, master.id]]
    assert (row.slot, row.state, row.filename) == ("DIPLOMA", "READY", "diploma.pdf")
    # The sweep keeps the merged slot: a second run prepares nothing and deletes nothing.
    store = _Store()
    assert prepare_documents(application, transform=_never, store=store) == [row]
    assert store.deleted == [] and current_prepared(application) == {"DIPLOMA": row}


def test_without_one_file_each_diploma_is_its_own_job(agency_a, membership_a):
    bachelor, master = _two_diplomas(agency_a, membership_a)
    application = _application(agency_a, membership_a, "Your diplomas.")
    application.kit_file_rules = [_r("DIPLOMA", "max_bytes", 2_000_000)]
    assert sorted(job.slot for job in jobs_for(application)) == sorted(
        [f"DIPLOMA:{bachelor.id}", f"DIPLOMA:{master.id}"]
    )


def test_the_bundle_includes_every_held_diploma_oldest_first(agency_a, membership_a):
    _cv(agency_a, membership_a)
    bachelor, master = _two_diplomas(agency_a, membership_a)
    application = _application(agency_a, membership_a, "A CV.", "Your diplomas.")
    application.kit_file_rules = [_r("EVERY_DOCUMENT", "combine", "ONE_FILE")]
    [job] = jobs_for(application)
    assert job.sources[0][0] == "draft"
    assert job.sources[1:] == (("upload", bachelor.id), ("upload", master.id))


def _transcript(agency, student, cycle, *pages):
    """A transcript upload and its TranscriptPage rows: (number, slot, live)."""
    from apps.documents.models import TranscriptPage, TranscriptUpload

    document = _upload(agency, student, "TRANSCRIPT")
    upload = TranscriptUpload.objects.create(
        student=student, cycle=cycle, document=document, role="ORIGINAL"
    )
    for number, slot, live in pages:
        TranscriptPage.objects.create(
            student=student, cycle=cycle, upload=upload, number=number, slot=slot,
            state="READ", source="azure",
            superseded_at=None if live else timezone.now(),
        )
    return document


def test_a_transcript_merge_takes_the_live_pages_in_slot_order(
    agency_a, membership_a, paid_cycle_a
):
    """Fix M1: page 1 unreadable and retaken, page 2 fine: the merge is retake p1, original
    p2 -- never the bad page, never the retake after page 2."""
    original = _transcript(agency_a, membership_a, paid_cycle_a, (1, 1, False), (2, 2, True))
    retake = _transcript(agency_a, membership_a, paid_cycle_a, (1, 1, True))
    application = _application(agency_a, membership_a, "Your transcript of records.")
    application.kit_file_rules = [_r("TRANSCRIPT", "combine", "ONE_FILE")]
    [job] = jobs_for(application)
    assert job.slot == "TRANSCRIPT"
    assert job.sources == (("upload", retake.id), ("upload", original.id))
    assert job.pages == ((1,), (2,))
    handed = []

    def _transform(parts, rule):
        handed.extend((part.upload.id, part.pages) for part in parts)
        return _fake_pdf(parts, rule)

    [row] = prepare_documents(application, transform=_transform, store=_Store())
    assert handed == [(retake.id, (1,)), (original.id, (2,))]
    assert row.sources == [{"source": "upload", "id": str(retake.id), "pages": [1]},
                           {"source": "upload", "id": str(original.id), "pages": [2]}]


def test_a_transcript_page_selection_is_part_of_the_digest(agency_a, membership_a, paid_cycle_a):
    from apps.documents.models import TranscriptPage

    original = _transcript(agency_a, membership_a, paid_cycle_a, (1, 1, True), (2, 2, True))
    _transcript(agency_a, membership_a, paid_cycle_a, (1, 3, True))
    application = _application(agency_a, membership_a, "Your transcript of records.")
    application.kit_file_rules = [_r("TRANSCRIPT", "combine", "ONE_FILE")]
    [before] = jobs_for(application)
    TranscriptPage.objects.filter(upload__document=original, number=2).update(
        superseded_at=timezone.now()
    )
    [after] = jobs_for(application)
    assert before.digest != after.digest and after.pages == ((1,), (1,))


# --- Final review fixes (plan 4b) ---


def _times_out(*_):
    from apps.documents.ocr_errors import OcrUnavailable

    raise OcrUnavailable("function error Sandbox.Timedout", kind="job")


def _age(row, delta):
    from datetime import timedelta

    PreparedDocument.objects.filter(id=row.id).update(
        prepared_at=timezone.now() - timedelta(**delta))


def test_m2_a_timed_out_slot_is_retried_after_an_hour_and_no_sooner(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    [row] = prepare_documents(application_with_cv, transform=_times_out, store=_Store())
    assert (row.state, row.reason) == ("CANNOT_FIT", "timed_out")
    _age(row, {"minutes": 50})
    assert prepare_documents(application_with_cv, transform=_never, store=_Store())
    _age(row, {"minutes": 61})
    # Still the kit's note while it waits for the next trigger.
    assert current_prepared(application_with_cv)[row.slot].reason == "timed_out"
    [again] = prepare_documents(application_with_cv, transform=_fake_pdf, store=_Store())
    assert (again.id, again.state, again.reason) == (row.id, "READY", "")


def test_m2_any_other_refusal_stays_current_however_old(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    [row] = prepare_documents(application_with_cv, transform=lambda *_: Prepared(refused="pages"),
                              store=_Store())
    _age(row, {"days": 2})
    assert prepare_documents(application_with_cv, transform=_never, store=_Store())


def test_m6_a_stale_run_never_overwrites_a_fresher_runs_row(application_with_cv):
    """A run that started before another run wrote this slot leaves that row, and removes
    only its own just-stored object -- never the fresher run's."""
    from datetime import timedelta

    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    [job] = jobs_for(application_with_cv)
    fresher = PreparedDocument.objects.create(
        application=application_with_cv, tenant=application_with_cv.tenant,
        student=application_with_cv.student, slot=job.slot, document="CV", state="READY",
        object_key="k-fresh", object_version="vf", inputs_digest="fresher-digest")
    PreparedDocument.objects.filter(id=fresher.id).update(
        prepared_at=timezone.now() + timedelta(hours=1))  # written after our run started
    store = _Store()
    assert prepare_documents(application_with_cv, transform=_fake_pdf, store=store) == []
    row = PreparedDocument.objects.get(id=fresher.id)
    assert (row.object_key, row.object_version, row.inputs_digest) == (
        "k-fresh", "vf", "fresher-digest")
    assert store.objects == {} and len(store.deleted) == 1
    assert ("k-fresh", "vf") not in store.deleted
