from datetime import date
from uuid import uuid4

import pytest
from django.contrib.messages import get_messages
from django.template.loader import render_to_string
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.models import DocumentDraft
from apps.documents.views import page_context
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.portals.models import DeviceAction
from apps.portals.pairing import issue_pairing_code, redeem_pairing_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack  # the fixture, shared with the dashboard tests
PAGE = "/student/documents/"
SUBMIT = "/student/documents/submit/"


def _available(agency, student, kind):
    """Scanned clean, checked and promoted (Task 14): what the extension can fetch."""
    document = register(agency.id, student.id, kind=kind)
    DocumentVersion.objects.filter(id=document.id).update(
        state="AVAILABLE", scan_result="NO_THREATS_FOUND", content_type="application/pdf",
        promoted_key=f"tenants/{agency.id}/students/{student.id}/uploads/{document.id}/abc",
    )
    return document


def _draft(agency, student, kind, programme_id, version=1, rendered="cv-standard.pdf"):
    return DocumentDraft.objects.create(
        tenant=agency, student=student, kind=kind, version=version, content={},
        status=DocumentDraft.Status.APPROVED, programme_id=programme_id,
        rendered_filename=rendered,
    )


def _signal(agency, student, application, *, tier="METADATA", provider_id="m-1", **fields):
    connection, _ = MailboxConnection.objects.get_or_create(
        tenant=agency, membership=student, provider="MICROSOFT",
        defaults={"address": f"{student.id}@o.test", "tier": tier},
    )
    return MailSignal.objects.create(
        tenant=agency, connection=connection, provider_message_id=provider_id,
        sender_domain="tum.de", received_at=timezone.now(), application=application, **fields,
    )


def _other_student(agency, user_b):
    return Membership.objects.create(tenant=agency, user=user_b, role=Membership.Role.STUDENT)


def _submit(client, domain, application_id, document_id, source="upload"):
    return client.post(
        SUBMIT,
        {"application_id": application_id, "document_id": document_id, "source": source},
        HTTP_HOST=domain.host,
    )


def test_the_table_has_a_column_per_application_and_a_row_per_document(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, kit_requirements=["Passport copy"]
        )
        _available(agency_a, membership_a, "PASSPORT")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f'<th scope="col" id="application-{application.id}">M.Sc. Informatics</th>' in body
    assert '<th scope="row">Passport' in body
    assert "Submit document to M.Sc. Informatics" in body
    assert "dashboard/documents.js" in body
    assert 'type="radio" name="kind" value="CV" checked' in body
    assert 'id="upload-file"' in body


def test_submit_document_queues_the_upload_page_for_that_application(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        passport = _available(agency_a, membership_a, "PASSPORT")
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    response = _submit(client, domain_a, application.id, passport.id)
    assert response["Location"] == PAGE
    with tenant_scope(agency_a.id):
        action = DeviceAction.objects.get(application=application)
    assert action.kind == DeviceAction.Kind.OPEN_UPLOAD_PAGE
    assert action.payload == {
        "application_id": str(application.id), "document_id": str(passport.id), "source": "upload",
    }


def test_submit_document_without_a_portal_says_why(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, portal=False)
        passport = _available(agency_a, membership_a, "PASSPORT")
    client.force_login(user_a)
    response = _submit(client, domain_a, application.id, passport.id)
    assert "application portal" in str(list(get_messages(response.wsgi_request))[0])


def test_submitting_another_students_document_is_404(
    client, agency_a, domain_a, user_a, membership_a, user_b, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        other = _other_student(agency_a, user_b)
        theirs = _available(agency_a, other, "PASSPORT")
        quarantined = register(agency_a.id, membership_a.id, kind="PASSPORT")
        # Clean but still being checked: nothing the extension could fetch.
        checking = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=checking.id).update(
            state="CHECKING", scan_result="NO_THREATS_FOUND"
        )
        their_application = add_card(agency_a, other, programme)
        mine = _available(agency_a, membership_a, "DIPLOMA")
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    for document in (theirs, quarantined, checking):
        assert _submit(client, domain_a, application.id, document.id).status_code == 404
    # My own usable document to someone else's application.
    assert _submit(client, domain_a, their_application.id, mine.id).status_code == 404
    assert _submit(client, domain_a, uuid4(), uuid4()).status_code == 404
    assert _submit(client, domain_a, "not-a-uuid", mine.id).status_code == 404
    with tenant_scope(agency_a.id):
        assert not DeviceAction.objects.exists()


def test_submitting_an_expired_document_id_is_404(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """An id that was the student's and no longer exists (the row is gone)."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        gone = _available(agency_a, membership_a, "PASSPORT")
        gone_id = gone.id
        gone.delete()
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    assert _submit(client, domain_a, application.id, gone_id).status_code == 404


def test_a_checking_upload_is_refused_even_when_forged(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """Task 14 carry: the service refuses a CHECKING entry, not just the page."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, kit_requirements=["Passport"])
        checking = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=checking.id).update(
            state="CHECKING", scan_result="NO_THREATS_FOUND"
        )
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    assert _submit(client, domain_a, application.id, checking.id).status_code == 404
    with tenant_scope(agency_a.id):
        assert not DeviceAction.objects.exists()


def test_a_certified_copy_cell_offers_no_submit_and_refuses_a_forged_one(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """F13: nothing records certification, so an uncertified upload never fills it."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, kit_requirements=["Certified copy of passport"]
        )
        passport = _available(agency_a, membership_a, "PASSPORT")
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "certified copy needed" in body
    assert "Submit document to" not in body
    assert _submit(client, domain_a, application.id, passport.id).status_code == 404
    with tenant_scope(agency_a.id):
        assert not DeviceAction.objects.exists()


def test_an_approved_draft_goes_to_its_own_programmes_application(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        letter = _draft(
            agency_a, membership_a, DocumentDraft.Kind.MOTIVATION_LETTER, programme.program_id
        )
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    response = _submit(client, domain_a, application.id, letter.id, "draft")
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        action = DeviceAction.objects.get(application=application)
    assert action.payload["source"] == "draft"


def test_a_draft_for_another_programme_is_404(
    client, agency_a, domain_a, user_a, membership_a, pack, program_factory
) -> None:
    """F20, §5.6: a TUM letter or a TUM-tailored CV never goes to another application."""
    programme, _award = pack
    kth = program_factory(name="M.Sc. Machine Learning")
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        kth_letter = _draft(agency_a, membership_a, DocumentDraft.Kind.MOTIVATION_LETTER, kth.id)
        kth_cv = _draft(agency_a, membership_a, DocumentDraft.Kind.CV, kth.id)
        # A letter for no programme is for no application.
        loose_letter = _draft(
            agency_a, membership_a, DocumentDraft.Kind.MOTIVATION_LETTER, None, version=2
        )
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    for draft in (kth_letter, kth_cv, loose_letter):
        assert _submit(client, domain_a, application.id, draft.id, "draft").status_code == 404
    # The right id under the wrong source is not the same document.
    assert _submit(client, domain_a, application.id, kth_cv.id, "upload").status_code == 404
    with tenant_scope(agency_a.id):
        assert not DeviceAction.objects.exists()


def test_the_expiry_of_a_passport_is_saved(client, agency_a, domain_a, user_a, membership_a):
    with tenant_scope(agency_a.id):
        passport = _available(agency_a, membership_a, "PASSPORT")
    client.force_login(user_a)
    client.post(
        f"/student/documents/{passport.id}/expiry/", {"expires_on": "2031-05-01"},
        HTTP_HOST=domain_a.host,
    )
    passport.refresh_from_db()
    assert passport.expires_on == date(2031, 5, 1)


def test_expiry_of_another_students_or_an_expired_document_is_404(
    client, agency_a, domain_a, user_a, membership_a, user_b
) -> None:
    with tenant_scope(agency_a.id):
        theirs = _available(agency_a, _other_student(agency_a, user_b), "PASSPORT")
        gone = _available(agency_a, membership_a, "PASSPORT")
        gone_id = gone.id
        gone.delete()
    client.force_login(user_a)
    for document_id in (theirs.id, gone_id):
        response = client.post(
            f"/student/documents/{document_id}/expiry/", {"expires_on": "2031-05-01"},
            HTTP_HOST=domain_a.host,
        )
        assert response.status_code == 404
    theirs.refresh_from_db()
    assert theirs.expires_on is None


def test_an_upload_being_checked_reads_checking_and_offers_no_submit(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, kit_requirements=["Passport copy"])
        document = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=document.id).update(
            state="CHECKING", scan_result="NO_THREATS_FOUND"
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "checking…" in body
    assert "Submit document to" not in body


def test_a_rejected_upload_says_what_to_do(client, agency_a, domain_a, user_a, membership_a):
    with tenant_scope(agency_a.id):
        document = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=document.id).update(state="REJECTED_ACTIVE_CONTENT")
    client.force_login(user_a)
    page = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "save it again as a plain PDF (Print → Save as PDF)" in page


def test_an_unread_message_can_be_told_which_document_it_asked_for(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        signal = _signal(agency_a, membership_a, application)
    client.force_login(user_a)
    client.post(
        f"/student/documents/requests/{signal.id}/", {"kind": "TRANSCRIPT"},
        HTTP_HOST=domain_a.host,
    )
    signal.refresh_from_db()
    assert (signal.label, signal.document_name) == ("DOCUMENT_REQUEST", "Transcript")


def test_naming_another_students_or_an_expired_message_is_404(
    client, agency_a, domain_a, user_a, membership_a, user_b, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        other = _other_student(agency_a, user_b)
        theirs = _signal(agency_a, other, add_card(agency_a, other, programme))
        gone = _signal(agency_a, membership_a, add_card(agency_a, membership_a, programme))
        gone_id = gone.id
        gone.delete()
    client.force_login(user_a)
    for signal_id in (theirs.id, gone_id):
        response = client.post(
            f"/student/documents/requests/{signal_id}/", {"kind": "TRANSCRIPT"},
            HTTP_HOST=domain_a.host,
        )
        assert response.status_code == 404
    theirs.refresh_from_db()
    assert theirs.label == ""


def test_content_tier_mail_awaiting_classification_is_not_offered_for_naming(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """F23: an unlabelled content-tier message is not unreadable, just not read yet."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        signal = _signal(
            agency_a, membership_a, add_card(agency_a, membership_a, programme), tier="CONTENT"
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Messages we could not read" not in body
    response = client.post(
        f"/student/documents/requests/{signal.id}/", {"kind": "TRANSCRIPT"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 404


def test_the_counselor_view_carries_no_student_only_action(
    agency_a, membership_a, pack, rf
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, kit_requirements=["Passport"])
        _available(agency_a, membership_a, "PASSPORT")
        _signal(agency_a, membership_a, application)
        DocumentDraft.objects.create(
            tenant=agency_a, student=membership_a, kind=DocumentDraft.Kind.CV, version=1,
            content={}, status=DocumentDraft.Status.DRAFT,
        )
        student_html = render_to_string(
            "student/_documents.html", page_context(membership_a, counselor_view=False),
            request=rf.get("/"),
        )
        html = render_to_string(
            "student/_documents.html", page_context(membership_a, counselor_view=True),
            request=rf.get("/"),
        )
    for action in ("/student/documents/", "data-api-post", "Submit document to"):
        assert action in student_html
        assert action not in html
    assert f"/counselor/students/{membership_a.id}/uploads/" in html


def test_queue_upload_itself_refuses_a_document_its_cell_does_not_hold(
    agency_a, membership_a, pack
) -> None:
    """The service, not only the view: every caller of queue_upload is gated."""
    from apps.portals.applications import ApplicationRefused, queue_upload

    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, kit_requirements=["Passport"])
        checking = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=checking.id).update(
            state="CHECKING", scan_result="NO_THREATS_FOUND"
        )
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
        with pytest.raises(ApplicationRefused) as refused:
            queue_upload(application, document_id=checking.id, source="upload", actor=membership_a)
    assert refused.value.reason == "document_unusable"


def test_an_unrendered_approved_draft_offers_no_submit_and_a_forged_one_is_refused(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """packets.py's rule: a draft still rendering has nothing the extension could fetch."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, kit_requirements=["A CV"])
        cv = _draft(agency_a, membership_a, DocumentDraft.Kind.CV, None, rendered="")
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Submit document to" not in body
    assert _submit(client, domain_a, application.id, cv.id, "draft").status_code == 404
    with tenant_scope(agency_a.id):
        assert not DeviceAction.objects.exists()


def test_a_withdrawn_application_has_no_column_and_takes_no_document(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, kit_requirements=["Passport"],
            outcome="WITHDRAWN",
        )
        passport = _available(agency_a, membership_a, "PASSPORT")
        redeem_pairing_code(issue_pairing_code(membership_a), "install-1")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f"application-{application.id}" not in body
    assert _submit(client, domain_a, application.id, passport.id).status_code == 404
    with tenant_scope(agency_a.id):
        assert not DeviceAction.objects.exists()


def _cells(student, application):
    from apps.documents.table import table_for

    signals = MailSignal.objects.filter(application=application).select_related("connection")
    table = table_for(student, [application], signals)
    return {row.kind: row.cells[0] for row in table.rows}


@pytest.mark.parametrize(
    ("tier", "trusted", "counts"),
    [("CONTENT", False, False), ("CONTENT", True, True), ("METADATA", False, True)],
)
def test_only_a_vouched_document_request_adds_a_requirement(
    agency_a, membership_a, pack, tier, trusted, counts
) -> None:
    """Trusted mail, or a message the student named themselves; never a stranger's say-so."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _signal(
            agency_a, membership_a, application, tier=tier, trusted=trusted,
            label="DOCUMENT_REQUEST", document_name="Certified copy of transcript",
        )
        cells = _cells(membership_a, application)
    assert cells["TRANSCRIPT"] == ("certified copy needed" if counts else "not needed")


def test_an_untrusted_request_never_turns_a_real_cell_certified_and_is_noted(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, kit_requirements=["Transcript"])
        _signal(
            agency_a, membership_a, application, tier="CONTENT", trusted=False,
            label="DOCUMENT_REQUEST", document_name="Certified copy of transcript",
        )
        assert _cells(membership_a, application)["TRANSCRIPT"] == "missing"
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    # The kind we recognised, never the stranger's own wording (Task 15 minor).
    assert "M.Sc. Informatics: Transcript (unverified)" in body
    assert "Certified copy of transcript" not in body


def test_an_untrusted_request_naming_no_known_kind_shows_no_wording(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _signal(
            agency_a, membership_a, application, tier="CONTENT", trusted=False,
            label="DOCUMENT_REQUEST", document_name="Pay 500 EUR to IBAN DE00 now",
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "M.Sc. Informatics: a document (unverified)" in body
    assert "IBAN" not in body


def test_a_message_whose_classification_gave_up_can_be_named(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """F23's other half: content-tier mail nothing could classify is the student's to name."""
    from apps.mailbox.sync import MAX_CLASSIFY_ATTEMPTS

    programme, _award = pack
    with tenant_scope(agency_a.id):
        signal = _signal(
            agency_a, membership_a, add_card(agency_a, membership_a, programme),
            tier="CONTENT", classify_attempts=MAX_CLASSIFY_ATTEMPTS,
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Messages we could not read" in body
    client.post(
        f"/student/documents/requests/{signal.id}/", {"kind": "TRANSCRIPT"},
        HTTP_HOST=domain_a.host,
    )
    signal.refresh_from_db()
    assert signal.label == "DOCUMENT_REQUEST"
    # The student named it, so it counts like a metadata-tier one.
    with tenant_scope(agency_a.id):
        assert _cells(membership_a, signal.application)["TRANSCRIPT"] == "missing"
