"""Plan 4, Task 7: the kit and Fill Packet serve prepared files, and a route serves them."""

import hashlib
import os

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import storage
from apps.documents.ocr import Prepared
from apps.portals import packets
from apps.portals.models import ApplicationStep, DeviceAction, PreparedDocument
from apps.portals.prepare import prepare_documents
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment, Membership
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.dashboard.test_counselor_board import paused  # noqa: F401 -- a fixture
from tests.portals.test_ext_api import _pair
from tests.portals.test_ext_document import PDF, _get, _promoted
from tests.portals.test_kit import _application, _approved_cv
from tests.portals.test_prepare import _r

pytestmark = pytest.mark.django_db
PREPARED = b"%PDF-prepared"


def _fake_pdf(parts, rule):
    return Prepared(
        content_type="application/pdf", sha256=hashlib.sha256(PREPARED).hexdigest(), body=PREPARED
    )


@pytest.fixture
def bucket(monkeypatch, fake_store):
    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    monkeypatch.setattr(storage, "read_draft", lambda draft, filename: b"%PDF-cv")
    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron",
                                                      "personal.city": "London"}
    )
    return fake_store


def _prepared(application, store, *rules, transform=_fake_pdf):
    application.kit_file_rules = list(rules)
    application.save(update_fields=["kit_file_rules"])
    return prepare_documents(application, transform=transform, store=store)


@pytest.fixture
def prepared_cv_application(agency_a, membership_a, bucket):
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a)
        application = _application(agency_a, membership_a)
        _prepared(application, bucket, _r("CV", "max_bytes", 2_000_000))
        yield application


def test_a_ready_prepared_cv_replaces_the_original_in_the_packet(prepared_cv_application):
    [document] = packets.mint_packet(prepared_cv_application).documents
    assert document.prepared_id is not None and document.kind == "CV"
    assert document.draft_id is None
    assert document.download_path.startswith("/prepared/")
    step = ApplicationStep.objects.get(application=prepared_cv_application, kind="PACKET")
    assert step.detail["documents"][0]["prepared_id"] == str(document.prepared_id)


def _slots(application, *slots):
    from apps.portals.models import FieldMap

    FieldMap.objects.filter(portal_form=application.portal_form).update(slots=[
        {"selector": selector, "kind": kind, "variant": "ANY", "degree": None, "sure": True}
        for selector, kind in slots
    ])


def test_a_ready_prepared_cv_goes_into_the_learned_cv_box(prepared_cv_application):
    """Merge of plan 4 with master's slots: the prepared copy is paired like its draft."""
    _slots(prepared_cv_application, ("#cv", "CV"))
    [document] = packets.mint_packet(prepared_cv_application).documents
    assert (document.selector, document.kind) == ("#cv", "CV")
    assert document.prepared_id is not None and document.draft_id is None


def test_a_ready_bundle_is_the_only_document_no_upload_beside_it(
    agency_a, membership_a, bucket
):
    """A READY whole-application bundle already holds every document: a held upload a
    learned box would take is neither sent beside it nor made servable."""
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a)
        diploma = _diploma_upload(agency_a, membership_a, bucket)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["A CV.", "Your diploma."]
        _slots(application, ("#cv", "CV"), ("#diploma", "DIPLOMA"))
        _prepared(application, bucket, _r("EVERY_DOCUMENT", "combine", "ONE_FILE"))
        packet = packets.mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
    [document] = packet.documents
    assert document.kind == "EVERY_DOCUMENT" and document.prepared_id is not None
    assert packet.choices == ()
    assert step.detail["uploads"] == []
    assert str(diploma.id) not in str(step.detail)


def _diploma_packet(agency, membership, bucket, *, prepared, newer=False):
    """A DIPLOMA upload paired to a learned #diploma box, prepared to a size rule or not,
    and optionally a newer DIPLOMA upload after the preparation (the copy is then stale)."""
    with tenant_scope(agency.id):
        upload = _diploma_upload(agency, membership, bucket)
        application = _application(agency, membership)
        application.kit_requirements = ["Your diploma."]
        _slots(application, ("#diploma", "DIPLOMA"))
        if prepared:
            _prepared(application, bucket, _r("DIPLOMA", "max_bytes", 2_000_000))
        if newer:
            upload = _diploma_upload(agency, membership, bucket)
        packet = packets.mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
    [document] = packet.documents
    return upload, document, step


def test_a_packet_upload_with_a_current_prepared_copy_attaches_the_copy(
    agency_a, membership_a, bucket
):
    """Coordinator ruling on merge concern 1: the slot gets the prepared copy, served through
    the student's own prepared route; the original is neither named nor servable."""
    upload, document, step = _diploma_packet(agency_a, membership_a, bucket, prepared=True)
    assert document.selector == "#diploma" and document.kind == "DIPLOMA"
    assert document.prepared_id is not None and document.upload_id is None
    assert document.download_path == reverse(
        "portals-prepared-download", args=[document.prepared_id, document.filename]
    )
    assert step.detail["uploads"] == []
    assert step.detail["documents"][0]["prepared_id"] == str(document.prepared_id)


def test_a_merged_copy_covering_two_diploma_boxes_is_attached_once(
    agency_a, membership_a, bucket, monkeypatch
):
    """Two degrees, two diplomas, two learned diploma boxes, one READY "all diplomas as one
    PDF" copy listing both: the packet carries the merge exactly once and neither original."""
    monkeypatch.setattr(packets, "verified_values", lambda student: {
        "identity.full_name": "Ada Byron",
        "education.1.institution": "ADA University",
        "education.2.institution": "TU Munich",
    })
    with tenant_scope(agency_a.id):
        bachelor = _diploma_upload(agency_a, membership_a, bucket)
        master = _diploma_upload(agency_a, membership_a, bucket)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["Your diplomas."]
        from apps.portals.models import FieldMap

        FieldMap.objects.filter(portal_form=application.portal_form).update(slots=[
            {"selector": "#diploma-1", "kind": "DIPLOMA", "variant": "ANY", "degree": 1,
             "sure": True},
            {"selector": "#diploma-2", "kind": "DIPLOMA", "variant": "ANY", "degree": 2,
             "sure": True},
        ])
        [merged] = _prepared(application, bucket, _r("DIPLOMA", "combine", "ONE_FILE"))
        assert merged.state == PreparedDocument.State.READY
        assert {s["id"] for s in merged.sources} == {str(bachelor.id), str(master.id)}
        packet = packets.mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
    named = [*packet.documents, *packet.choices]
    assert [item.prepared_id for item in named] == [merged.id]
    assert all(item.upload_id is None for item in named)
    assert step.detail["uploads"] == []
    assert str(bachelor.id) not in str(step.detail) and str(master.id) not in str(step.detail)


def test_a_packet_upload_with_no_prepared_copy_attaches_the_original(
    agency_a, membership_a, bucket
):
    upload, document, step = _diploma_packet(agency_a, membership_a, bucket, prepared=False)
    assert (document.upload_id, document.prepared_id) == (upload.id, None)
    assert step.detail["uploads"] == [{"upload_id": str(upload.id)}]


def test_a_packet_upload_newer_than_its_prepared_copy_attaches_the_original(
    agency_a, membership_a, bucket
):
    upload, document, _step = _diploma_packet(
        agency_a, membership_a, bucket, prepared=True, newer=True
    )
    assert (document.upload_id, document.prepared_id) == (upload.id, None)


def test_the_packet_s_prepared_upload_reaches_its_student_only(
    client, agency_a, domain_a, user_a, user_b, membership_a, bucket
):
    """The extension fetches it with the student's own session; another student is a 404."""
    _upload, document, _step = _diploma_packet(agency_a, membership_a, bucket, prepared=True)
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
    client.force_login(user_a)
    response = client.get(document.download_path, HTTP_HOST=domain_a.host)
    assert response.status_code == 200 and response.content == PREPARED
    client.force_login(user_b)
    assert client.get(document.download_path, HTTP_HOST=domain_a.host).status_code == 404


def test_a_cannot_fit_cv_keeps_the_original_with_its_reason(agency_a, membership_a, bucket):
    """A refused slot still shows the original, and says why."""
    with tenant_scope(agency_a.id):
        draft = _approved_cv(agency_a, membership_a)
        application = _application(agency_a, membership_a)
        _prepared(application, bucket, _r("CV", "max_bytes", 2_000_000),
                  transform=lambda *_: Prepared(refused="pages"))
        [document] = packets.build_kit(application).documents
    assert (document.draft_id, document.prepared_id, document.note) == (draft.id, None, "pages")


def test_a_cannot_fit_bundle_falls_back_to_the_originals_with_its_reason(
    agency_a, membership_a, bucket
):
    """Review Focus 5."""
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["A CV."]
        _prepared(application, bucket, _r("EVERY_DOCUMENT", "combine", "ONE_FILE"),
                  transform=lambda *_: Prepared(refused="signed"))
        packet = packets.mint_packet(application)
    documents = packet.documents
    assert {d.kind for d in documents} >= {"CV"}
    assert all(d.prepared_id is None for d in documents)
    # Final review I1: no original carries the bundle's reason. The packet says the bundle
    # failed once, in `notes` (plan 4b final review I1/M5), so no CV repeats it.
    assert [d.note for d in documents] == [""]
    assert [(n.kind, n.note) for n in packet.notes] == [("EVERY_DOCUMENT", "signed")]


def _owner_url(application):
    row = PreparedDocument.objects.get(application=application)
    return row, reverse("portals-prepared-download", args=[row.id, row.filename])


def test_the_prepared_route_serves_only_the_owner_a_current_ready_file(
    client, agency_a, domain_a, user_a, user_b, membership_a, prepared_cv_application
):
    row, url = _owner_url(prepared_cv_application)
    Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)

    client.force_login(user_a)
    response = client.get(url, HTTP_HOST=domain_a.host)
    assert response.status_code == 200 and response.content == PREPARED
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert response["Content-Disposition"].startswith("attachment")
    assert client.get(url + "x", HTTP_HOST=domain_a.host).status_code == 404  # wrong name

    client.force_login(user_b)
    assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404

    client.force_login(user_a)
    prepared_cv_application.kit_file_rules = [_r("CV", "max_bytes", 1_000_000)]  # stale now
    prepared_cv_application.save(update_fields=["kit_file_rules"])
    assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404


def _diploma_upload(agency, membership, bucket):
    upload = _promoted(agency, membership, bucket)
    from apps.concierge.models import DocumentVersion

    DocumentVersion.objects.filter(id=upload.id).update(kind="DIPLOMA")
    return DocumentVersion.objects.get(id=upload.id)


def _open_upload_action(agency, membership, application, upload):
    DeviceAction.objects.create(
        tenant=agency, membership=membership, application=application,
        kind=DeviceAction.Kind.OPEN_UPLOAD_PAGE,
        payload={"application_id": str(application.id), "document_id": str(upload.id),
                 "source": "upload"},
        expires_at=__import__("django.utils.timezone", fromlist=["now"]).now()
        + __import__("datetime").timedelta(minutes=15),
    )


@pytest.mark.parametrize("prepared", [True, False])
def test_the_extension_upload_route_serves_the_prepared_version_when_there_is_one(
    client, agency_a, domain_a, membership_a, bucket, prepared
):
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        upload = _diploma_upload(agency_a, membership_a, bucket)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["Your diploma."]
        if prepared:
            _prepared(application, bucket, _r("DIPLOMA", "max_bytes", 2_000_000))
        _open_upload_action(agency_a, membership_a, application, upload)
    response = _get(client, domain_a, token, upload.id)
    assert response.status_code == 200
    assert response.content == (PREPARED if prepared else PDF)
    assert response["X-Content-Type-Options"] == "nosniff"


def test_either_diploma_of_a_merged_pair_serves_the_one_merged_pdf(
    client, agency_a, domain_a, membership_a, bucket
):
    """Plan 4b Task 6: under "all diplomas as one PDF" the extension attaches the merge."""
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        bachelor = _diploma_upload(agency_a, membership_a, bucket)
        master = _diploma_upload(agency_a, membership_a, bucket)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["Your diplomas."]
        [row] = _prepared(application, bucket, _r("DIPLOMA", "combine", "ONE_FILE"))
        assert row.slot == "DIPLOMA"
        _open_upload_action(agency_a, membership_a, application, master)
    response = _get(client, domain_a, token, master.id)
    assert response.status_code == 200 and response.content == PREPARED
    assert bachelor.id != master.id


@pytest.mark.django_db(transaction=True)
def test_the_kit_documents_read_no_catalogue_behind_the_web_role(
    agency_a, prepared_cv_application, web_role_orm
):
    # the rows were committed by the fixture before web_role_orm swapped the connection
    with tenant_transaction(agency_a.id), reads_no_catalogue():
        [document] = packets._kit_documents(
            prepared_cv_application, packets.current_prepared(prepared_cv_application)
        )
    assert document.prepared_id is not None


def test_a_ready_row_whose_object_is_missing_is_a_404(
    client, domain_a, user_a, prepared_cv_application, bucket
):
    row, url = _owner_url(prepared_cv_application)
    del bucket._data[row.object_key]
    client.force_login(user_a)
    assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404


def test_the_answers_page_says_why_in_words(
    client, agency_a, domain_a, counselor_membership, membership_a, bucket
):
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a)
        application = _application(agency_a, membership_a)
        _prepared(application, bucket, _r("CV", "max_bytes", 2_000_000),
                  transform=lambda *_: Prepared(refused="signed"))
    html = _kit_html(client, domain_a, counselor_membership, application)
    assert "digitally signed" in html and "signed<" not in html and ">signed" not in html
    assert 'class="doc-note"' in html


def test_a_document_with_no_note_renders_no_note_element(
    client, domain_a, counselor_membership, prepared_cv_application
):
    html = _kit_html(client, domain_a, counselor_membership, prepared_cv_application)
    assert "doc-note" not in html


def test_every_reason_has_a_sentence_and_an_unknown_one_is_generic():
    from apps.portals.prepare import NOTE_TEXT, note_text

    assert all(text and "_" not in text for text in NOTE_TEXT.values())
    assert note_text("brand_new_code") and "brand_new_code" not in note_text("brand_new_code")


SIGNED = "digitally signed"
BUNDLE = "all your documents in one PDF"


def _kit_html(client, domain, counselor, application):
    """The kit as its one reader sees it: the assigned counsellor's read-only answers page
    (the student has no kit page since #192)."""
    with tenant_scope(application.tenant_id):
        CounselorAssignment.objects.get_or_create(
            tenant_id=application.tenant_id, counselor=counselor, student=application.student
        )
    client.force_login(counselor.user)
    verify_mfa_session(client, counselor.user)
    response = client.get(
        f"/counselor/students/{application.student_id}/applications/{application.id}/answers/",
        HTTP_HOST=domain.host,
    )
    assert response.status_code == 200
    return response.content.decode()


@pytest.mark.parametrize("with_cv", [True, False])
def test_a_refused_bundle_is_one_kit_line_and_never_blames_the_cv(
    client, agency_a, domain_a, counselor_membership, membership_a, bucket, with_cv
):
    """Final review I1: CV + signed diploma under EVERY_DOCUMENT ONE_FILE, refused
    `signed`. The kit says so once, above the documents -- with or without a CV."""
    with tenant_scope(agency_a.id):
        if with_cv:
            _approved_cv(agency_a, membership_a)
        _diploma_upload(agency_a, membership_a, bucket)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["A CV.", "Your diploma."]
        application.save(update_fields=["kit_requirements"])  # the view re-reads the row
        _prepared(application, bucket, _r("EVERY_DOCUMENT", "combine", "ONE_FILE"),
                  transform=lambda *_: Prepared(refused="signed"))
        kit = packets.build_kit(application)
    assert BUNDLE in kit.bundle_note and SIGNED in kit.bundle_note
    assert kit.bundle_note.index(BUNDLE) < kit.bundle_note.index(SIGNED)
    assert [SIGNED in d.note_text for d in kit.documents] == ([False] if with_cv else [])
    html = _kit_html(client, domain_a, counselor_membership, application)
    assert html.count(SIGNED) == 1 and BUNDLE in html
    documents = html[html.index("<h2>Documents</h2>"):]
    assert documents.index(BUNDLE) < documents.index(
        "cv-standard.pdf" if with_cv else "No approved document")


def test_a_prepared_upload_with_a_note_is_listed_under_the_documents(
    client, agency_a, domain_a, counselor_membership, membership_a, bucket
):
    """Final review I2: a signed diploma under a DIPLOMA size rule reaches the kit."""
    with tenant_scope(agency_a.id):
        _diploma_upload(agency_a, membership_a, bucket)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["Your diploma."]
        _prepared(application, bucket, _r("DIPLOMA", "max_bytes", 2_000_000),
                  transform=lambda *_: Prepared(refused="signed"))
        kit = packets.build_kit(application)
    assert [(n.label, SIGNED in n.note_text) for n in kit.upload_notes] == [("Diploma", True)]
    assert kit.bundle_note == ""
    html = _kit_html(client, domain_a, counselor_membership, application)
    assert "Diploma<p class=\"doc-note\">" in html and SIGNED in html


def test_a_prepared_upload_without_a_note_is_not_listed(agency_a, membership_a, bucket):
    with tenant_scope(agency_a.id):
        _diploma_upload(agency_a, membership_a, bucket)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["Your diploma."]
        _prepared(application, bucket, _r("DIPLOMA", "max_bytes", 2_000_000))
        assert packets.build_kit(application).upload_notes == ()


def test_removing_a_card_after_preparation_removes_its_prepared_rows(
    prepared_cv_application, membership_a
):
    """Final review C1: the prepared copy no longer PROTECTs its application."""
    from django.core.cache import cache

    from apps.portals.applications import remove_application
    from apps.portals.models import Application

    cache.clear()
    application_id = prepared_cv_application.id
    assert PreparedDocument.objects.filter(application_id=application_id).exists()
    remove_application(prepared_cv_application, actor=membership_a)
    assert not Application.objects.filter(id=application_id).exists()
    assert not PreparedDocument.objects.filter(application_id=application_id).exists()


def test_every_note_code_has_a_sentence_in_each_panel_language():
    """The panel keys its sentences n_<code>; a code missing there shows the generic one."""
    from pathlib import Path

    from apps.portals.prepare import NOTE_TEXT

    source = (Path(__file__).resolve().parents[2] / "extension/src/panel/i18n.ts").read_text()
    assert [code for code in NOTE_TEXT if source.count(f"  n_{code}: ") != 4] == []


# --- Task 4b-4: counsellors view prepared files inline; no download is offered ---


@pytest.fixture
def assigned(agency_a, membership_a, counselor_membership, prepared_cv_application):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        row = PreparedDocument.objects.get(application=prepared_cv_application)
    return row, reverse("portals-prepared-view", args=[row.id])


def test_an_assigned_counsellor_views_the_file_inline_and_cannot_cache_it(
    client, domain_a, counselor_user, assigned
):
    _row, url = assigned
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.get(url, HTTP_HOST=domain_a.host)
    assert response.status_code == 200 and response.content == PREPARED
    assert response["Content-Disposition"].startswith("inline")
    assert "attachment" not in response["Content-Disposition"]
    assert response["Cache-Control"] == "no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    csp = "default-src 'none'; img-src 'self'; object-src 'self'; frame-ancestors 'none'"
    assert response["Content-Security-Policy"] == csp


def test_everyone_else_gets_a_404_from_the_view_route(
    client, agency_a, agency_b, domain_a, user_a, user_b, membership_a, prepared_cv_application,
    assigned,
):
    _row, url = assigned
    other = get_user_model().objects.create_user(username="counselor-unassigned")
    other_in_b = get_user_model().objects.create_user(username="counselor-b")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=other, role=Membership.Role.COUNSELOR)
    Membership._base_manager.bulk_create(  # save() refuses a cross-tenant create
        [Membership(tenant=agency_b, user=other_in_b, role=Membership.Role.COUNSELOR)]
    )
    for who, host in ((other, domain_a), (user_a, domain_a)):
        client.force_login(who)  # unassigned, other tenant, the student
        if not client.session.get("otp_device_id"):
            verify_mfa_session(client, who)
        assert client.get(url, HTTP_HOST=host.host).status_code == 404
    # No membership here at all: the tenancy middleware answers a plain, object-independent 403.
    client.force_login(other_in_b)
    assert client.get(url, HTTP_HOST=domain_a.host).status_code == 403
    client.logout()
    assert client.get(url, HTTP_HOST=domain_a.host).status_code in (302, 404)


def test_a_stale_row_is_a_404_for_the_counsellor(
    client, domain_a, counselor_user, prepared_cv_application, assigned
):
    _row, url = assigned
    prepared_cv_application.kit_file_rules = [_r("CV", "max_bytes", 1_000_000)]
    prepared_cv_application.save(update_fields=["kit_file_rules"])
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404


def test_the_counsellor_board_lists_the_file_with_view_and_no_download(
    client, domain_a, counselor_user, assigned, membership_a
):
    row, url = assigned
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    html = client.get(
        reverse("counselor-student-board", args=[membership_a.id]), HTTP_HOST=domain_a.host
    ).content.decode()
    assert f'href="{url}"' in html and ">View<" in html
    assert reverse("portals-prepared-download", args=[row.id, row.filename]) not in html


@pytest.mark.extension
def test_chromium_renders_the_view_routes_headers_as_a_pdf_not_a_download(
    client, domain_a, counselor_user, assigned
):
    """Serve the route's own bytes and headers from a plain server; Chromium (the full build,
    which has the PDF viewer -- the headless shell has none) must open it, not download it."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    sync_api = pytest.importorskip("playwright.sync_api")
    _row, url = assigned
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    served = client.get(url, HTTP_HOST=domain_a.host)
    headers = {k: served[k] for k in ("Content-Disposition", "X-Content-Type-Options",
                                      "Cache-Control", "Content-Security-Policy")}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(served.content)))
            self.end_headers()
            self.wfile.write(served.content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="chromium", headless=True)
            except Exception as error:  # browser not installed on this machine
                if os.environ.get("CI"):
                    pytest.fail(f"full chromium cannot launch under CI: {error}")
                pytest.skip(f"full chromium unavailable: {error}")
            page = browser.new_page()
            downloads = []
            page.on("download", lambda d: downloads.append(d))
            page.goto(f"http://127.0.0.1:{server.server_port}/view")
            page.wait_for_timeout(1000)
            assert page.evaluate("document.contentType") == "application/pdf"
            assert downloads == []
            browser.close()
    finally:
        server.shutdown()


# --- fix round 1 ---


def test_an_unassigned_owner_or_ended_assignment_gets_a_404(
    client, agency_a, domain_a, membership_a, counselor_membership, counselor_user,
    prepared_cv_application, assigned,
):
    """A PLATFORM_ADMIN is no longer here: Elmify staff view any student's file, recorded
    (owner decision 2026-10-11, tests/portals/test_staff_file_access.py)."""
    _row, url = assigned
    owner = get_user_model().objects.create_user(username="owner-a")
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.filter(counselor=counselor_membership).update(active=False)
        Membership.objects.create(tenant=agency_a, user=owner, role=Membership.Role.OWNER)
    for who in (owner, counselor_user):
        client.force_login(who)
        verify_mfa_session(client, who)
        assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404


def test_every_prepared_document_has_a_human_label():
    from apps.documents.file_rules import DRAFT_DOCUMENTS, UPLOAD_DOCUMENTS

    assert packets.prepared_label("EVERY_DOCUMENT") == "Combined application file"
    for document in {*DRAFT_DOCUMENTS, *UPLOAD_DOCUMENTS, "EVERY_DOCUMENT"}:
        label = packets.prepared_label(document)
        assert label != "EVERY_DOCUMENT" and "_" not in label


@pytest.mark.extension
def test_the_upload_form_sends_replace_or_add_another_for_the_chosen_kind(
    client, agency_a, domain_a, user_a, membership_a, bucket
):
    """Plan 4b Task 6: documents.js shows Replace / Add another only for a kind with a
    choice, and posts what was chosen. The page's own HTML, the real script."""
    from pathlib import Path

    sync_api = pytest.importorskip("playwright.sync_api")
    with tenant_scope(agency_a.id):
        diploma = _diploma_upload(agency_a, membership_a, bucket)
    client.force_login(user_a)
    html = client.get("/student/documents/", HTTP_HOST=domain_a.host).content.decode()
    script = Path("static/dashboard/documents.js").read_text()
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:  # browser not installed on this machine
            if os.environ.get("CI"):
                pytest.fail(f"chromium cannot launch under CI: {error}")
            pytest.skip(f"chromium unavailable: {error}")
        page = browser.new_page()
        page.set_content(html)
        page.evaluate("""() => { window.sent = [];
            window.fetch = (url, init) => { window.sent.push(JSON.parse(init.body));
                return Promise.resolve({status: 400, json: () => Promise.resolve({})}); }; }""")
        page.add_script_tag(content=script)
        modes = page.locator("fieldset[data-modes]")
        assert modes.is_hidden()  # CV: nothing held, no choice
        page.select_option("#upload-kind", "DIPLOMA")
        assert modes.is_visible()
        assert page.locator(f'input[data-replaces="{diploma.id}"]').is_checked()
        page.set_input_files("#upload-file", files=[
            {"name": "d.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.click("form[data-upload] button[type=submit]")
        page.check('input[value="ADD"][data-kind="DIPLOMA"]')
        page.click("form[data-upload] button[type=submit]")
        page.select_option("#upload-kind", "PASSPORT")
        assert modes.is_hidden()
        page.click("form[data-upload] button[type=submit]")
        page.wait_for_function("window.sent.length === 3")
        assert page.evaluate("window.sent") == [
            {"kind": "DIPLOMA", "mode": "REPLACE", "replaces": str(diploma.id)},
            {"kind": "DIPLOMA", "mode": "ADD"},
            {"kind": "PASSPORT"},
        ]
        browser.close()


@pytest.mark.extension
def test_the_upload_form_defaults_letters_to_add_and_explains_a_stale_replace(
    client, agency_a, domain_a, user_a, membership_a, bucket
):
    """Fix I1 and M5: a letter defaults to Add another; a refusal the student can act on is a
    sentence, never the code."""
    from pathlib import Path

    from apps.concierge.models import DocumentVersion

    sync_api = pytest.importorskip("playwright.sync_api")
    with tenant_scope(agency_a.id):
        letter = _promoted(agency_a, membership_a, bucket)
        DocumentVersion.objects.filter(id=letter.id).update(kind="REFERENCE_LETTER")
    client.force_login(user_a)
    html = client.get("/student/documents/", HTTP_HOST=domain_a.host).content.decode()
    script = Path("static/dashboard/documents.js").read_text()
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:  # browser not installed on this machine
            if os.environ.get("CI"):
                pytest.fail(f"chromium cannot launch under CI: {error}")
            pytest.skip(f"chromium unavailable: {error}")
        page = browser.new_page()
        page.set_content(html)
        page.evaluate("""() => { window.sent = [];
            window.fetch = (url, init) => { window.sent.push(JSON.parse(init.body));
                return Promise.resolve({status: 400,
                    json: () => Promise.resolve({error: "replace_which"})}); }; }""")
        page.add_script_tag(content=script)
        page.select_option("#upload-kind", "REFERENCE_LETTER")
        assert page.locator('input[value="ADD"][data-kind="REFERENCE_LETTER"]').is_checked()
        page.set_input_files("#upload-file", files=[
            {"name": "l.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.click("form[data-upload] button[type=submit]")
        page.wait_for_function("window.sent.length === 1")
        assert page.evaluate("window.sent") == [{"kind": "REFERENCE_LETTER", "mode": "ADD"}]
        status = page.locator('form[data-upload] [role="status"]')
        status.filter(has_text="reload").wait_for()
        assert status.text_content() == (
            "You now have more than one of these documents \u2014 reload the page and "
            "choose which one to replace."
        )
        browser.close()


def test_the_active_content_sentence_says_the_file_is_sent_as_uploaded():
    from apps.portals.prepare import NOTE_TEXT

    assert NOTE_TEXT["active_content"] == (
        "This file contains active content (scripts or links that run on opening), "
        "so we did not change it; it is sent as you uploaded it."
    )


# --- Plan 4b final review fixes ---

TOO_LARGE = "too large to read clearly"


def _documents_html(client, domain, user):
    client.force_login(user)
    response = client.get("/student/documents/", HTTP_HOST=domain.host)
    assert response.status_code == 200
    return response.content.decode()


def _row(html, label):
    start = html.index(f'<th scope="row">{label}')
    return html[start:html.index("</tr>", start)]


def test_i1_an_upload_note_reaches_the_students_documents_page_and_the_packet(
    client, agency_a, domain_a, user_a, membership_a, bucket
):
    """A signed diploma under a DIPLOMA 2 MB rule: CANNOT_FIT "signed"."""
    with tenant_scope(agency_a.id):
        _diploma_upload(agency_a, membership_a, bucket)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["Your diploma."]
        application.save(update_fields=["kit_requirements"])
        _prepared(application, bucket, _r("DIPLOMA", "max_bytes", 2_000_000),
                  transform=lambda *_: Prepared(refused="signed"))
        packet = packets.mint_packet(application)
        step = ApplicationStep.objects.get(application=application, kind="PACKET")
    assert packet.documents == ()
    assert [(n.kind, n.note) for n in packet.notes] == [("DIPLOMA", "signed")]
    assert step.detail["notes"] == [{"kind": "DIPLOMA", "note": "signed"}]
    html = _documents_html(client, domain_a, user_a)
    diploma = _row(html, "Diploma")
    assert SIGNED in diploma and 'class="doc-note"' in diploma
    assert ">signed<" not in html and "signed</" not in html.replace(SIGNED, "")


def test_i1_a_refused_bundle_is_one_line_per_application_column_and_one_packet_note(
    client, agency_a, domain_a, user_a, membership_a, bucket
):
    """EVERY_DOCUMENT ONE_FILE refused too_large, no approved CV draft."""
    with tenant_scope(agency_a.id):
        _diploma_upload(agency_a, membership_a, bucket)
        first, second = (_application(agency_a, membership_a) for _ in range(2))
        for application in (first, second):
            application.kit_requirements = ["Your diploma."]
            application.save(update_fields=["kit_requirements"])
            _prepared(application, bucket, _r("EVERY_DOCUMENT", "combine", "ONE_FILE"),
                      transform=lambda *_: Prepared(refused="too_large"))
        packet = packets.mint_packet(first)
    assert packet.documents == ()
    assert [(n.kind, n.note) for n in packet.notes] == [("EVERY_DOCUMENT", "too_large")]
    html = _documents_html(client, domain_a, user_a)
    bundle = _row(html, "Combined application file")
    assert bundle.count(BUNDLE) == 2 and bundle.count(TOO_LARGE) == 2
    assert html.count(BUNDLE) == 2 and "too_large" not in html


def test_i1_a_document_page_with_nothing_prepared_has_no_note_and_no_bundle_row(
    client, domain_a, user_a, prepared_cv_application
):
    html = _documents_html(client, domain_a, user_a)
    assert "doc-note" not in html and "Combined application file" not in html


def test_m5_the_refused_bundle_line_says_upload_separately_once(
    agency_a, membership_a, bucket
):
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a)
        application = _application(agency_a, membership_a)
        application.kit_requirements = ["A CV."]
        _prepared(application, bucket, _r("EVERY_DOCUMENT", "combine", "ONE_FILE"),
                  transform=lambda *_: Prepared(refused="too_large"))
        line = packets.build_kit(application).bundle_note
    assert line.index(BUNDLE) < line.index(TOO_LARGE)
    assert line.lower().count("separately") == 1 and line.count("Upload") == 1


def test_m5_every_bundle_reason_has_a_clause_in_each_panel_language():
    from pathlib import Path

    from apps.portals.prepare import BUNDLE_REASON

    assert all("separately" not in text and "Upload" not in text
               for text in BUNDLE_REASON.values())
    source = (Path(__file__).resolve().parents[2] / "extension/src/panel/i18n.ts").read_text()
    assert [code for code in BUNDLE_REASON if source.count(f"  nb_{code}: ") != 4] == []


def test_m4_a_paused_students_prepared_files_are_neither_viewable_nor_listed(
    client, domain_a, counselor_user, assigned, membership_a, paused  # noqa: F811
):
    _row_, url = assigned
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    assert client.get(url, HTTP_HOST=domain_a.host).status_code == 404
    html = client.get(
        reverse("counselor-student-board", args=[membership_a.id]), HTTP_HOST=domain_a.host
    ).content.decode()
    assert paused in html  # the board itself still renders, read-only
    assert "Prepared files" not in html and url not in html


@pytest.fixture
def noted_cv_application(agency_a, membership_a, bucket):
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a)
        application = _application(agency_a, membership_a)
        _prepared(application, bucket, _r("CV", "max_bytes", 2_000_000),
                  transform=lambda *_: Prepared(refused="signed"))
        yield application


@pytest.mark.django_db(transaction=True)
def test_i1_the_documents_page_notes_read_no_catalogue_behind_the_web_role(
    agency_a, noted_cv_application, web_role_orm
):
    with tenant_transaction(agency_a.id), reads_no_catalogue():
        cells, bundles = packets.document_notes([noted_cv_application])
    assert [SIGNED in s for s in cells[("CV", noted_cv_application.id)]] == [True]
    assert bundles == {}
