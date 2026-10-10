from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.audit.models import DeletionRequest
from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents import storage
from apps.documents.models import DocumentDraft
from apps.portals.models import Application, ApplicationStep, DeviceAction
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card
from tests.portals.test_ext_api import _pair

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack  # the fixture, shared with the dashboard tests
PDF = b"%PDF-1.7 passport scan"


@pytest.fixture
def bucket(monkeypatch, fake_store):
    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    return fake_store


def _promoted(agency, student, bucket, *, state="AVAILABLE", scan="NO_THREATS_FOUND"):
    document = register(agency.id, student.id, kind="PASSPORT")
    key = storage.upload_key(
        tenant_id=agency.id, student_id=student.id, document_id=document.id, version="abc"
    )
    bucket.put(key, PDF)
    DocumentVersion.objects.filter(id=document.id).update(
        state=state, scan_result=scan, promoted_key=key, content_type="application/pdf"
    )
    return document


def _named(agency, student, document, *, expires_in=timedelta(minutes=15)):
    application = Application.objects.create(tenant=agency, student=student, program_id=uuid4())
    DeviceAction.objects.create(
        tenant=agency, membership=student, application=application,
        kind=DeviceAction.Kind.OPEN_UPLOAD_PAGE,
        payload={"application_id": str(application.id), "document_id": str(document.id),
                 "source": "upload"},
        expires_at=timezone.now() + expires_in,
    )
    return application


def _get(client, domain, token, document_id):
    return client.get(
        f"/ext/documents/{document_id}", HTTP_HOST=domain.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_a_named_promoted_upload_is_streamed_as_an_inert_attachment(
    client, agency_a, domain_a, membership_a, bucket
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        document = _promoted(agency_a, membership_a, bucket)
        _named(agency_a, membership_a, document)
    response = _get(client, domain_a, token, document.id)
    assert response.status_code == 200
    assert response.content == PDF
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == f'attachment; filename="passport-{document.id}.pdf"'
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "sandbox; default-src 'none'"


def test_a_document_named_by_the_latest_packet_is_served(
    client, agency_a, domain_a, membership_a, bucket
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        document = _promoted(agency_a, membership_a, bucket)
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )
        ApplicationStep.objects.create(
            tenant=agency_a, application=application, sequence=1, kind="PACKET",
            detail={"uploads": [{"upload_id": str(document.id)}]},
        )
    assert _get(client, domain_a, token, document.id).status_code == 200


@pytest.mark.parametrize(
    "case",
    ["unnamed", "expired", "quarantined", "checking", "blocked", "rejected", "theirs", "absent"],
)
def test_every_refusal_is_a_404(
    client, agency_a, domain_a, membership_a, user_b, bucket, case
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        if case == "theirs":
            other = Membership.objects.create(
                tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
            )
            document = _promoted(agency_a, other, bucket)
            _named(agency_a, other, document)
        elif case == "quarantined":
            document = register(agency_a.id, membership_a.id, kind="PASSPORT")
            DocumentVersion.objects.filter(id=document.id).update(
                state="AVAILABLE", scan_result="NO_THREATS_FOUND"
            )
            _named(agency_a, membership_a, document)
        else:
            state = {
                "blocked": "BLOCKED", "rejected": "REJECTED_ACTIVE_CONTENT", "checking": "CHECKING"
            }.get(case, "AVAILABLE")
            document = _promoted(
                agency_a, membership_a, bucket, state=state,
                scan="THREATS_FOUND" if case == "blocked" else "NO_THREATS_FOUND",
            )
            if case in ("expired", "blocked", "rejected", "checking"):
                _named(agency_a, membership_a, document,
                       expires_in=timedelta(minutes=-1 if case == "expired" else 15))
    document_id = uuid4() if case == "absent" else document.id
    assert _get(client, domain_a, token, document_id).status_code == 404


def test_no_token_is_401_and_a_locked_student_is_403(
    client, agency_a, domain_a, membership_a, bucket
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        document = _promoted(agency_a, membership_a, bucket)
        _named(agency_a, membership_a, document)
    assert client.get(f"/ext/documents/{document.id}", HTTP_HOST=domain_a.host).status_code == 401
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
        )
    assert _get(client, domain_a, token, document.id).status_code in (401, 403)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("named_by", ["action", "packet"])
def test_the_route_reads_behind_the_policy(
    client, agency_a, domain_a, membership_a, user_a, bucket, named_by, rls_enforced_orm
) -> None:
    """Every read the route makes -- the upload, the action, the packet step -- is legal SQL
    that returns nothing without the GUC, which would make every request a quiet 404."""
    from tests.portals.test_ext_rls import _paired

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        document = _promoted(agency_a, membership_a, bucket)
        if named_by == "action":
            _named(agency_a, membership_a, document)
        else:
            application = Application.objects.create(
                tenant=agency_a, student=membership_a, program_id=uuid4()
            )
            ApplicationStep.objects.create(
                tenant=agency_a, application=application, sequence=1, kind="PACKET",
                detail={"uploads": [{"upload_id": str(document.id)}]},
            )
    token = _paired(client, user_a, domain_a)
    response = _get(client, domain_a, token, document.id)
    assert response.status_code == 200
    assert response.content == PDF


def test_a_promoted_key_outside_the_documents_own_prefix_is_never_read(
    client, agency_a, domain_a, membership_a, user_b, bucket
) -> None:
    """Defence in depth: only the worker writes promoted_key, but the route still reads only
    under this document's own uploads/ prefix."""
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        theirs = _promoted(agency_a, other, bucket)
        document = _promoted(agency_a, membership_a, bucket)
        DocumentVersion.objects.filter(id=document.id).update(
            promoted_key=DocumentVersion.objects.get(id=theirs.id).promoted_key
        )
        _named(agency_a, membership_a, document)
    assert _get(client, domain_a, token, document.id).status_code == 404


def _rendered_draft(agency, student, bucket, *, filename="cv-standard.pdf"):
    draft = DocumentDraft.objects.create(
        tenant=agency, student=student, kind=DocumentDraft.Kind.CV, version=1, content={},
        status=DocumentDraft.Status.APPROVED, rendered_filename=filename,
    )
    bucket.put(
        storage.document_key(
            tenant_id=agency.id, student_id=student.id, draft_id=draft.id, filename=filename
        ),
        PDF,
    )
    return draft


def test_a_draft_submitted_from_the_documents_page_is_served(
    client, agency_a, domain_a, user_a, membership_a, bucket, pack
) -> None:
    programme, _award = pack
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme, kit_requirements=["A CV"])
        draft = _rendered_draft(agency_a, membership_a, bucket)
    client.force_login(user_a)
    submitted = client.post(
        "/student/documents/submit/",
        {"application_id": application.id, "document_id": draft.id, "source": "draft"},
        HTTP_HOST=domain_a.host,
    )
    assert submitted.status_code == 302
    client.logout()
    response = _get(client, domain_a, token, draft.id)
    assert response.status_code == 200
    assert response.content == PDF
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == f'attachment; filename="cv-{draft.id}.pdf"'
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "sandbox; default-src 'none'"


def test_a_draft_named_by_the_latest_packet_is_served(
    client, agency_a, domain_a, membership_a, bucket
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        draft = _rendered_draft(agency_a, membership_a, bucket)
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )
        ApplicationStep.objects.create(
            tenant=agency_a, application=application, sequence=1, kind="PACKET",
            detail={"documents": [{"draft_id": str(draft.id), "filename": "cv-standard.pdf"}]},
        )
    assert _get(client, domain_a, token, draft.id).status_code == 200


@pytest.mark.parametrize("case", ["theirs", "unnamed", "named_as_upload", "unrendered"])
def test_every_draft_refusal_is_a_404(
    client, agency_a, domain_a, membership_a, user_b, bucket, case
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        owner = membership_a
        if case == "theirs":
            owner = Membership.objects.create(
                tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
            )
        draft = _rendered_draft(agency_a, owner, bucket)
        if case == "unrendered":
            DocumentDraft.objects.filter(id=draft.id).update(rendered_filename="")
        if case != "unnamed":
            # Named by MY action even for "theirs": only the owner filter refuses it.
            application = Application.objects.create(
                tenant=agency_a, student=membership_a, program_id=uuid4()
            )
            DeviceAction.objects.create(
                tenant=agency_a, membership=membership_a, application=application,
                kind=DeviceAction.Kind.OPEN_UPLOAD_PAGE,
                payload={"application_id": str(application.id), "document_id": str(draft.id),
                         "source": "upload" if case == "named_as_upload" else "draft"},
                expires_at=timezone.now() + timedelta(minutes=15),
            )
    assert _get(client, domain_a, token, draft.id).status_code == 404
