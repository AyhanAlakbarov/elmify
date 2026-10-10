from uuid import uuid4

import pytest

from apps.documents.drafts import create_draft
from apps.documents.models import DocumentDraft
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.documents.storage import (
    DocumentStoreRefused,
    InvalidFilename,
    document_key,
    store_document,
)
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership

pytestmark = pytest.mark.django_db


def _content():
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Example U",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )


def _approved_draft(agency, student):
    draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
    DocumentDraft.objects.filter(id=draft.id).update(status=DocumentDraft.Status.APPROVED)
    draft.refresh_from_db()
    return draft


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def test_document_key_is_tenant_first_under_the_evidence_bucket_prefix():
    tenant_id, student_id, draft_id = uuid4(), uuid4(), uuid4()
    key = document_key(
        tenant_id=tenant_id, student_id=student_id, draft_id=draft_id, filename="cv-v1.pdf"
    )
    assert key == (
        f"tenants/{tenant_id}/students/{student_id}/documents/{draft_id}/cv-v1.pdf"
    )
    assert key.startswith(f"tenants/{tenant_id}/")


@pytest.mark.parametrize("filename", ["../escape.pdf", "a/b.pdf", "", "x" * 101, "sp ace.pdf"])
def test_document_key_rejects_a_hostile_filename(filename):
    with pytest.raises(InvalidFilename):
        document_key(
            tenant_id=uuid4(), student_id=uuid4(), draft_id=uuid4(), filename=filename
        )


def test_store_document_derives_the_key_from_the_active_tenant(
    agency_a, django_user_model, fake_store
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "s1")
        draft = _approved_draft(agency_a, student)
        key = store_document(
            draft=draft, filename="cv-v1.pdf", content=b"%PDF-1.4 test", store=fake_store
        )
        assert key.startswith(f"tenants/{agency_a.id}/")
        assert fake_store.get(key) == b"%PDF-1.4 test"


def test_store_document_refuses_an_unapproved_draft(agency_a, django_user_model, fake_store):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "s2")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        with pytest.raises(DocumentStoreRefused):
            store_document(
                draft=draft, filename="cv-v1.pdf", content=b"%PDF-1.4", store=fake_store
            )


def test_store_document_refuses_a_tenant_mismatch(
    agency_a, agency_b, django_user_model, fake_store
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "s3")
        draft = _approved_draft(agency_a, student)
    with tenant_scope(agency_b.id):
        with pytest.raises(DocumentStoreRefused):
            store_document(
                draft=draft, filename="cv-v1.pdf", content=b"%PDF-1.4", store=fake_store
            )


@pytest.mark.django_db(transaction=True)
def test_student_downloads_their_own_approved_document(
    client, domain_a, agency_a, user_a, membership_a, fake_store, monkeypatch
):
    from apps.documents import storage

    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, membership_a)
        key = store_document(
            draft=draft, filename="cv-v1.pdf", content=b"%PDF-1.4 mine", store=fake_store
        )
    client.force_login(user_a)
    response = client.get(f"/documents/{draft.id}/cv-v1.pdf", HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 mine"
    assert response["Content-Type"] == "application/pdf"
    assert key  # the stored key is what was served


@pytest.mark.django_db(transaction=True)
def test_a_student_cannot_download_another_students_document(
    client, domain_a, agency_a, user_a, membership_a, django_user_model, fake_store, monkeypatch
):
    from apps.documents import storage

    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    with tenant_scope(agency_a.id):
        other = _student(agency_a, django_user_model, "s4")
        draft = _approved_draft(agency_a, other)
        store_document(
            draft=draft, filename="cv-v1.pdf", content=b"%PDF-1.4 theirs", store=fake_store
        )
    client.force_login(user_a)
    response = client.get(f"/documents/{draft.id}/cv-v1.pdf", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_an_unassigned_counselor_cannot_download(
    client,
    domain_a,
    agency_a,
    counselor_user,
    counselor_membership,
    membership_a,
    fake_store,
    monkeypatch,
):
    from apps.documents import storage
    from tests.conftest import verify_mfa_session

    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, membership_a)
        store_document(
            draft=draft, filename="cv-v1.pdf", content=b"%PDF-1.4", store=fake_store
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    assert (
        client.get(f"/documents/{draft.id}/cv-v1.pdf", HTTP_HOST=domain_a.host).status_code == 404
    )
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a, active=True
        )
    assert (
        client.get(f"/documents/{draft.id}/cv-v1.pdf", HTTP_HOST=domain_a.host).status_code == 200
    )


@pytest.mark.django_db(transaction=True)
def test_an_unapproved_document_is_never_served(
    client, domain_a, agency_a, user_a, membership_a, fake_store, monkeypatch
):
    from apps.documents import storage

    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    with tenant_scope(agency_a.id):
        draft = create_draft(student=membership_a, kind=DocumentDraft.Kind.CV, content=_content())
        fake_store.put(
            document_key(
                tenant_id=agency_a.id,
                student_id=membership_a.id,
                draft_id=draft.id,
                filename="cv-v1.pdf",
            ),
            b"%PDF-1.4 leaked",
        )
    client.force_login(user_a)
    assert (
        client.get(f"/documents/{draft.id}/cv-v1.pdf", HTTP_HOST=domain_a.host).status_code == 404
    )


@pytest.mark.django_db(transaction=True)
def test_a_document_from_another_tenant_is_invisible(
    client, domain_a, domain_b, agency_b, user_a, membership_a, django_user_model, fake_store,
    monkeypatch,
):
    from apps.documents import storage

    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    with tenant_scope(agency_b.id):
        other = _student(agency_b, django_user_model, "s5")
        draft = _approved_draft(agency_b, other)
    client.force_login(user_a)
    assert (
        client.get(f"/documents/{draft.id}/cv-v1.pdf", HTTP_HOST=domain_a.host).status_code == 404
    )
