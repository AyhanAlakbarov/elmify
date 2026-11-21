from datetime import date
from uuid import uuid4

import pytest
from django.contrib.messages import get_messages
from django.template.loader import render_to_string
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.models import CvFixRevert, DocumentDraft, VerifiedFact
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


def _available(agency, student, kind, **mode):
    """Scanned clean, checked and promoted (Task 14): what the extension can fetch."""
    document = register(agency.id, student.id, kind=kind, **mode)
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
    assert '<label for="upload-kind">' in body


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


def test_holding_a_diploma_offers_replace_or_add_another_and_counts_several(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """Plan 4b Task 6: Replace is the default; "Add another" keeps the first."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme, kit_requirements=["Your diplomas."])
        passport = _available(agency_a, membership_a, "PASSPORT")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'value="ADD" data-kind="DIPLOMA"' not in body  # no diploma held yet
    with tenant_scope(agency_a.id):
        bachelor = _available(agency_a, membership_a, "DIPLOMA")
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert (
        f'<input type="radio" name="mode" value="REPLACE" data-kind="DIPLOMA" '
        f'data-replaces="{bachelor.id}" checked>' in body
    )
    assert 'value="ADD" data-kind="DIPLOMA"' in body
    assert "Add another (e.g. a second degree)" in body
    # A dual national holds two passports (owner 2026-10-13): offered, never the default.
    assert 'value="ADD" data-kind="PASSPORT">' in body and "a second passport" in body
    assert f'data-replaces="{passport.id}"' in body
    assert "2 held" not in body
    with tenant_scope(agency_a.id):
        master = _available(agency_a, membership_a, "DIPLOMA")
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "uploaded (2 held)" in body
    assert f'data-replaces="{master.id}"' in body and f'data-replaces="{bachelor.id}"' in body


def test_a_student_holding_two_theses_is_offered_add_preselected(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    """A third thesis or report must be able to add: the page marks Add the default."""
    with tenant_scope(agency_a.id):
        first = _available(agency_a, membership_a, "THESIS_OR_REPORT", mode="ADD")
        second = _available(agency_a, membership_a, "THESIS_OR_REPORT", mode="ADD")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'value="ADD" data-kind="THESIS_OR_REPORT" data-default' in body
    assert "Add another (e.g. a project report)" in body
    assert f'data-replaces="{first.id}"' in body and f'data-replaces="{second.id}"' in body


@pytest.mark.parametrize("prepared", ["READY", "CANNOT_FIT", None])
def test_a_merged_cell_offers_one_submit_only_when_the_merge_is_ready(
    client, agency_a, domain_a, user_a, membership_a, pack, prepared
) -> None:
    """Fix M4 and round 2: under "all diplomas as one PDF", one Submit only when the merged
    file exists to be sent; otherwise each diploma keeps its own Submit, each sendable."""
    from apps.documents.ocr import Prepared
    from apps.documents.table import sendable
    from apps.portals.prepare import prepare_documents
    from tests.portals.test_prepare import _fake_pdf, _Store

    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(
            agency_a, membership_a, programme, kit_requirements=["Your diplomas."],
            kit_file_rules=[{"document": "DIPLOMA", "field": "combine", "value": "ONE_FILE"}],
        )
        diplomas = [_available(agency_a, membership_a, "DIPLOMA", mode="ADD") for _ in range(2)]
        if prepared is not None:
            transform = _fake_pdf if prepared == "READY" else (
                lambda *_: Prepared(refused="pages"))
            [row] = prepare_documents(application, transform=transform, store=_Store())
            assert (row.slot, row.state) == ("DIPLOMA", prepared)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    if prepared == "READY":
        assert "uploaded (2 held, sent as one file)" in body
        assert body.count("Submit document") == 1
    else:
        assert "uploaded (2 held)" in body and "sent as one file" not in body
        assert body.count("Submit document") == 2
        for diploma in diplomas:
            assert f'name="document_id" value="{diploma.id}"' in body
            with tenant_scope(agency_a.id):
                assert sendable(application, document_id=diploma.id, source="upload")


def test_recommendation_letters_default_to_add_another(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    """Fix I1: the page marks Add another as the letter's default; documents.js checks it."""
    with tenant_scope(agency_a.id):
        letter = _available(agency_a, membership_a, "REFERENCE_LETTER")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'value="ADD" data-kind="REFERENCE_LETTER" data-default' in body
    assert "Add another (e.g. a letter from another referee)" in body
    assert f'data-replaces="{letter.id}"' in body


def test_the_upload_form_asks_original_or_translation_for_a_transcript(
    agency_a, membership_a, rf
):
    """Onboarding plan task 5: the page never sent `role`, and every transcript upload
    from it was refused 400 invalid_role (transcript_pages._transcript_upload)."""
    with tenant_scope(agency_a.id):
        html = render_to_string(
            "student/_documents.html", page_context(membership_a, counselor_view=False),
            request=rf.get("/"),
        )
    assert 'name="role" value="ORIGINAL"' in html
    assert 'name="role" value="TRANSLATION"' in html
    for language in ("az", "tr", "ru"):
        assert f'<option value="{language}">' in html


def test_the_upload_script_sends_the_transcripts_role_and_language():
    """A static guard on the one script that builds the upload request: it must send
    `role` (and `language` for an original) when the kind is a transcript."""
    from pathlib import Path

    script = (Path(__file__).resolve().parents[2] / "static/dashboard/documents.js").read_text()
    assert "body.role" in script
    assert "body.language" in script
    assert "invalid_role" in script


CHANGES = "/student/documents/cv-changes/"


def _changed_degree(student):
    old = VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload={
            "degree_as_awarded": "BSc",
            "institution_original": "UFAZ",
            "city": "Baku",
        },
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:first",
        confirmed_by=student,
        confirmed_at=timezone.now(),
        created_by=student,
    )
    new = VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload={**old.payload, "city": "Sumqayit"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:second",
        supersedes=old,
        created_by=student,
    )
    return old, new


def test_a_changed_value_is_shown_old_beside_new_and_not_in_the_confirm_list(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _, new = _changed_degree(membership_a)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Changed since your last CV" in body
    assert "city Baku → Sumqayit" in body
    assert f'name="accept" value="{new.id}" checked' in body
    assert str(new.id) not in body.split('id="facts-heading"')[1]


def test_an_unticked_change_keeps_the_old_value_through_the_page(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        old, new = _changed_degree(membership_a)
    client.force_login(user_a)
    response = client.post(CHANGES, {"shown": [str(new.id)]}, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        tip = VerifiedFact.objects.get(supersedes=new)
    assert tip.payload["city"] == "Baku" and tip.confirmed_by_id == membership_a.id


def test_a_ticked_change_is_confirmed_through_the_page(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _, new = _changed_degree(membership_a)
    client.force_login(user_a)
    client.post(
        CHANGES,
        {"shown": [str(new.id)], "accept": [str(new.id)]},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(agency_a.id):
        new.refresh_from_db()
    assert new.confirmed_by_id == membership_a.id


def test_a_malformed_id_is_404(client, agency_a, domain_a, user_a, membership_a) -> None:
    client.force_login(user_a)
    response = client.post(CHANGES, {"shown": ["not-a-uuid"]}, HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_the_counselor_sees_the_changes_but_no_form(agency_a, membership_a, rf) -> None:
    with tenant_scope(agency_a.id):
        _changed_degree(membership_a)
        html = render_to_string(
            "student/_documents.html",
            page_context(membership_a, counselor_view=True),
            request=rf.get("/"),
        )
    assert "city Baku → Sumqayit" in html
    assert CHANGES not in html
    assert 'name="accept"' not in html


FIXES = "/student/documents/cv-fixes/"
_FIX = {
    "fix": "soft_skill",
    "subject": "f" * 64,
    "where": "skills",
    "original": "Teamwork",
    "changed": "",
    "undone": False,
}


def _cv_draft(agency, student, fixes):
    return DocumentDraft.objects.create(
        tenant=agency,
        student=student,
        kind=DocumentDraft.Kind.CV,
        version=1,
        content={},
        status=DocumentDraft.Status.DRAFT,
        applied_fixes=fixes,
    )


def test_the_page_lists_what_we_changed(client, agency_a, domain_a, user_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(
            agency_a,
            membership_a,
            [
                _FIX,
                {
                    **_FIX,
                    "fix": "verb_opener",
                    "subject": "a" * 64,
                    "original": "A tool for the lab.",
                    "changed": "Built a tool for the lab.",
                },
            ],
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "What we changed" in body
    assert "Left out: Teamwork" in body
    assert "A tool for the lab. → Built a tool for the lab." in body


def test_undo_and_apply_again(client, agency_a, domain_a, user_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX])
    client.force_login(user_a)
    client.post(FIXES, {"subject": "f" * 64, "action": "undo"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert CvFixRevert.objects.filter(student=membership_a, subject="f" * 64).exists()
    client.post(FIXES, {"subject": "f" * 64, "action": "redo"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert not CvFixRevert.objects.filter(student=membership_a).exists()


def test_a_subject_the_latest_draft_does_not_list_is_404(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX])
    client.force_login(user_a)
    response = client.post(
        FIXES, {"subject": "9" * 64, "action": "undo"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404


def test_the_counselor_sees_the_list_without_buttons(agency_a, membership_a, rf) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX])
        html = render_to_string(
            "student/_documents.html",
            page_context(membership_a, counselor_view=True),
            request=rf.get("/"),
        )
    assert "Left out: Teamwork" in html and FIXES not in html


def test_keep_this_wording_through_the_page(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        fact = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={"employer": "EPFL", "title": "Intern", "bullets": ["A tool for the lab."]},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:t",
            confirmed_by=membership_a,
            confirmed_at=timezone.now(),
            created_by=membership_a,
        )
        _cv_draft(
            agency_a,
            membership_a,
            [
                {
                    **_FIX,
                    "fix": "verb_opener",
                    "subject": "a" * 64,
                    "original": "A tool for the lab.",
                    "changed": "Built a tool for the lab.",
                }
            ],
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'value="keep"' in body
    client.post(FIXES, {"subject": "a" * 64, "action": "keep"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.get(supersedes=fact).payload["bullets"] == [
            "Built a tool for the lab."
        ]


def test_keep_is_refused_for_a_fix_that_is_not_wording(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _cv_draft(agency_a, membership_a, [_FIX])
    client.force_login(user_a)
    assert (
        client.post(
            FIXES, {"subject": "f" * 64, "action": "keep"}, HTTP_HOST=domain_a.host
        ).status_code
        == 404
    )


def test_warning_lines_read_the_stored_details():
    from types import SimpleNamespace

    from apps.documents.views import warning_lines

    draft = SimpleNamespace(
        render_warnings=[
            {"detail": "the page states: Please sign the CV.", "key": "unapplied"},
            {"detail": "final page carries 9% of an average page", "key": "min_final_page_fill"},
        ]
    )
    assert warning_lines(draft) == [
        "the page states: Please sign the CV.",
        "final page carries 9% of an average page",
    ]


def test_a_redacted_draft_has_no_warning_lines():
    """redact_student writes {} into a JSONField (redaction._empty_value)."""
    from types import SimpleNamespace

    from apps.documents.views import warning_lines

    assert warning_lines(SimpleNamespace(render_warnings={})) == []
    assert warning_lines(SimpleNamespace(render_warnings=[{"no_detail": 1}, "junk"])) == []


@pytest.mark.django_db
def test_page_context_attaches_warning_lines_to_each_draft(agency_a, membership_a):
    from apps.documents.drafts import create_draft
    from apps.documents.models import DocumentDraft
    from apps.documents.views import page_context
    from apps.tenancy.context import tenant_scope

    from .test_render import _content

    with tenant_scope(agency_a.id):
        draft = create_draft(student=membership_a, kind=DocumentDraft.Kind.CV, content=_content())
        DocumentDraft.objects.filter(id=draft.id).update(
            render_warnings=[{"detail": "the page states: Sign it."}]
        )
        drafts = page_context(membership_a, counselor_view=False)["drafts"]
    assert [d.warning_lines for d in drafts] == [["the page states: Sign it."]]


def test_left_out_entries_read_only_well_formed_left_out_fixes():
    from types import SimpleNamespace

    from apps.documents.views import left_out_entries

    good = {"kind": "left_out", "section": "awards", "item": "Chess prize (2018)",
            "item_digest": "a" * 64, "reason": "not related to this programme"}
    draft = SimpleNamespace(applied_fixes=[good, {"kind": "reworded"}, "junk"])
    assert left_out_entries(draft) == [good]
    assert left_out_entries(SimpleNamespace(applied_fixes={})) == []


@pytest.mark.django_db
def test_only_the_counsellor_view_carries_notes(agency_a, membership_a, monkeypatch):
    from apps.documents import views
    from apps.documents.drafts import create_draft
    from apps.documents.models import DocumentDraft
    from apps.tenancy.context import tenant_scope

    from .test_render import _content

    monkeypatch.setattr(views, "counsellor_notes",
                        lambda student, drafts: {d.id: ["a note"] for d in drafts})
    with tenant_scope(agency_a.id):
        create_draft(student=membership_a, kind=DocumentDraft.Kind.CV, content=_content())
        staff = views.page_context(membership_a, counselor_view=True)["drafts"]
        own = views.page_context(membership_a, counselor_view=False)["drafts"]
    assert [d.counsellor_notes for d in staff] == [["a note"]]
    assert [d.counsellor_notes for d in own] == [[]]




