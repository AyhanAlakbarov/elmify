from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.db import connection
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.audit.deletion import DeletionBlocked, advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.concierge.documents import register
from apps.documents import storage
from apps.documents.storage import delete_student_documents
from apps.funding.models import PackVersion, RecommendationRun
from apps.reports.models import ConsultationReport
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _approved_request(agency, student):
    RetentionPolicy.objects.create(tenant=agency, version=1, effective_at=timezone.now())
    request = DeletionRequest.objects.create(tenant=agency, student=student, state="REQUESTED")
    advance_deletion(request, "RETENTION_REVIEW")
    advance_deletion(request, "APPROVED")
    return request


def test_execute_purges_only_that_students_prefix(agency_a, django_user_model, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_documents",
        lambda *, tenant_id, student_id: calls.append((tenant_id, student_id)) or 0,
    )
    # advance_deletion destroys portal credentials on this same path. Unpatched,
    # it builds a real secretsmanager client, which needs an ambient AWS region --
    # so this passes on a laptop with ~/.aws/config and fails in CI, which has none.
    monkeypatch.setattr("apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_mailbox_tokens", lambda **kw: 0)
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "del1")
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")
    assert calls == [(agency_a.id, student.id)]


def test_a_storage_failure_leaves_the_request_unexecuted(
    agency_a, django_user_model, monkeypatch
):
    def _boom(**_kwargs):
        raise RuntimeError("S3 is having a day")

    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", _boom)
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "del2")
        request = _approved_request(agency_a, student)
        with pytest.raises(RuntimeError):
            advance_deletion(request, "EXECUTED")
        request.refresh_from_db()
        assert request.state == "APPROVED"


def test_executing_a_deletion_destroys_the_students_portal_credentials(
    agency_a, django_user_model, monkeypatch
):
    """CLAUDE.md's Phase 3 rule: erasure ships with storage. This is the test
    that makes "we will remember to delete the secrets" into something
    enforced."""
    from apps.audit import deletion

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kwargs: 0)
    destroyed = []
    monkeypatch.setattr(
        deletion,
        "delete_student_portal_credentials",
        lambda **kwargs: destroyed.append(kwargs) or 1,
    )
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kwargs: 0)
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "del4")
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")
    assert destroyed == [{"tenant_id": agency_a.id, "student_id": student.id}]


def test_executing_a_deletion_destroys_the_students_mailbox_grants(
    agency_a, django_user_model, monkeypatch
):
    """Same rule, third secret: apps/mailbox/secrets.py holds the OAuth refresh
    token, and it must not outlive the student who granted it."""
    from apps.audit import deletion

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kwargs: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kwargs: 0)
    destroyed = []
    monkeypatch.setattr(
        deletion,
        "delete_student_mailbox_tokens",
        lambda **kwargs: destroyed.append(kwargs) or 2,
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "del4b")
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")
    assert destroyed == [{"tenant_id": agency_a.id, "student_id": student.id}]


def test_a_credential_deletion_failure_leaves_the_request_unexecuted(
    agency_a, django_user_model, monkeypatch
):
    """Same rule the document purge already follows: a storage failure must not
    record an erasure that did not happen."""
    from apps.audit import deletion

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kwargs: 0)
    monkeypatch.setattr(
        deletion,
        "delete_student_portal_credentials",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secretsmanager down")),
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "del5")
        request = _approved_request(agency_a, student)
        with pytest.raises(RuntimeError):
            advance_deletion(request, "EXECUTED")
        request.refresh_from_db()
        assert request.state == "APPROVED"


def test_earlier_states_never_touch_storage(agency_a, django_user_model, monkeypatch):
    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_documents",
        lambda **_kwargs: pytest.fail("storage touched before EXECUTED"),
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "del3")
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        with pytest.raises(DeletionBlocked):
            advance_deletion(request, "DENIED")  # APPROVED -> DENIED is not a transition


def test_delete_student_documents_removes_every_version_across_pages(agency_a):
    """Versioning is on, so deleting the current version is not erasure.

    Real UUIDs, because the function now reads the student's DocumentVersion
    rows to find their quarantined uploads as well; it has none here, so the
    listing under test is still the artefact prefix's.
    """
    tenant_id, student_id = agency_a.id, uuid4()
    prefix = f"tenants/{tenant_id}/students/{student_id}/"
    client = MagicMock()
    client.list_object_versions.side_effect = [
        {
            "Versions": [{"Key": f"{prefix}documents/d/cv.pdf", "VersionId": "v1"}],
            "DeleteMarkers": [],
            "IsTruncated": True,
            "NextKeyMarker": f"{prefix}documents/d/cv.pdf",
            "NextVersionIdMarker": "v1",
        },
        {
            "Versions": [{"Key": f"{prefix}documents/d/cv.pdf", "VersionId": "v0"}],
            "DeleteMarkers": [{"Key": f"{prefix}documents/d/old.pdf", "VersionId": "dm1"}],
            "IsTruncated": False,
        },
    ]
    deleted = delete_student_documents(tenant_id=tenant_id, student_id=student_id, client=client)
    assert deleted == 3
    assert client.delete_objects.call_count == 2
    first_prefix = client.list_object_versions.call_args_list[0].kwargs["Prefix"]
    assert first_prefix == prefix


def test_delete_student_documents_handles_an_empty_prefix(agency_a):
    client = MagicMock()
    client.list_object_versions.return_value = {"IsTruncated": False}
    assert (
        delete_student_documents(tenant_id=agency_a.id, student_id=uuid4(), client=client) == 0
    )
    client.delete_objects.assert_not_called()


class _FakeS3:
    """Enough of a versioned bucket to answer a listing and record erasures."""

    def __init__(self, objects: dict[str, list[str]]) -> None:
        self._objects = objects
        self.erased: list[tuple[str, str]] = []

    def list_object_versions(self, *, Bucket, Prefix, **_markers):  # noqa: N803
        return {
            "Versions": [
                {"Key": key, "VersionId": version}
                for key, versions in self._objects.items()
                if key.startswith(Prefix)
                for version in versions
            ],
            "IsTruncated": False,
        }

    def delete_objects(self, *, Bucket, Delete):  # noqa: N803
        self.erased.extend((entry["Key"], entry["VersionId"]) for entry in Delete["Objects"])


def test_erasure_removes_the_students_quarantined_upload(
    agency_a, django_user_model, monkeypatch
):
    """The uploaded CV is the most personal artefact here, and it is NOT under
    the student's own prefix: register() puts it at quarantine/{tenant}/{doc}.
    Before this branch nothing was ever written there, so an erasure that
    scanned only tenants/{tenant}/students/{student}/ recorded EXECUTED over a
    CV still sitting in the bucket -- a false compliance record.

    Driven through advance_deletion rather than the storage call, because what
    is under test is that the erasure PATH covers both prefixes.
    """
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "del-quarantine")
        sibling = _student(agency_a, django_user_model, "del-sibling")
        upload = register(agency_a.id, student.id)
        siblings_upload = register(agency_a.id, sibling.id)
        artefact = f"tenants/{agency_a.id}/students/{student.id}/documents/d/cv-standard.pdf"
        fake = _FakeS3(
            {
                upload.object_key: ["v2", "v1"],
                siblings_upload.object_key: ["v1"],
                artefact: ["v1"],
            }
        )
        monkeypatch.setattr(storage.boto3, "client", lambda *_a, **_kw: fake)
        # advance_deletion also destroys portal and mailbox secrets on this
        # path; unpatched, delete_student_mailbox_tokens unconditionally
        # tries both providers against a real secretsmanager client (it has
        # no PortalForm-style DB list to fall back to empty).
        monkeypatch.setattr("apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0)
        monkeypatch.setattr("apps.audit.deletion.delete_student_mailbox_tokens", lambda **kw: 0)
        request = _approved_request(agency_a, student)

        advance_deletion(request, "EXECUTED")

    assert (upload.object_key, "v1") in fake.erased
    assert (upload.object_key, "v2") in fake.erased  # versioning: the marker is not enough
    assert (artefact, "v1") in fake.erased
    # Erasure is one person's, not the agency's.
    assert not any(key == siblings_upload.object_key for key, _ in fake.erased)
    request.refresh_from_db()
    assert request.state == "EXECUTED"


def test_delete_student_documents_sets_tenant_guc_before_reading_uploads(
    agency_a, django_user_model, monkeypatch
):
    """Pins the fix's mechanism, not the RLS gap itself.

    concierge_documentversion is FORCE ROW LEVEL SECURITY keyed on the
    Postgres app.tenant_id GUC, but the test database role is NOT the
    NOBYPASSRLS production role -- it enforces nothing, so a test that only
    checked the erasure's outcome would pass identically whether or not
    set_local_tenant ever ran. What is provably testable here is the
    mechanism: that delete_student_documents calls set_local_tenant with the
    right tenant, inside an open transaction (set_local_tenant itself raises
    TransactionManagementError otherwise -- this is what actually exercises
    that), before it reads DocumentVersion. This does NOT prove RLS lets the
    query through in production; it proves the GUC-setting step the RLS gap
    was missing is now unconditionally on the erasure path.

    Called with no ambient tenant_scope at all, the way
    apps.documents.document_worker calls tenant-scoped work -- the previous
    code relied on wrapping the read in its own `with tenant_scope(...)`,
    which is exactly what left the Postgres GUC unset regardless of what an
    ambient scope did or didn't do.
    """
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "del-guc")
        upload = register(agency_a.id, student.id)

    seen: list[tuple[object, bool]] = []
    real_set_local_tenant = storage.set_local_tenant

    def _spy(tenant_id):
        seen.append((tenant_id, connection.in_atomic_block))
        return real_set_local_tenant(tenant_id)

    monkeypatch.setattr(storage, "set_local_tenant", _spy)
    client = MagicMock()
    client.list_object_versions.return_value = {"IsTruncated": False}
    delete_student_documents(tenant_id=agency_a.id, student_id=student.id, client=client)

    assert seen == [(agency_a.id, True)]
    # The GUC-scoped read found the row it was for: the quarantined key was
    # among the prefixes purged, not silently skipped.
    prefixes = [call.kwargs["Prefix"] for call in client.list_object_versions.call_args_list]
    assert upload.object_key in prefixes


def test_an_empty_object_key_never_becomes_a_bucket_wide_prefix(
    agency_a, django_user_model, monkeypatch
):
    """An empty object_key used as a prefix matches every object in the bucket
    -- every tenant's -- deleted by a routine asked to erase one student.
    register() always sets the column, so this guards a row that should not
    exist; the cost of being wrong about that is unrecoverable."""
    monkeypatch.setattr(storage, "set_local_tenant", lambda tenant_id: None)
    monkeypatch.setattr(
        storage.DocumentVersion.objects,
        "filter",
        lambda **kwargs: SimpleNamespace(values_list=lambda *a, **k: ["", "tenants/x/real-key"]),
    )
    client = MagicMock()
    client.list_object_versions.return_value = {"IsTruncated": False}

    with tenant_scope(agency_a.id):
        storage.delete_student_documents(
            tenant_id=agency_a.id, student_id=uuid4(), client=client
        )

    prefixes = [call.kwargs["Prefix"] for call in client.list_object_versions.call_args_list]
    assert "" not in prefixes
    assert "tenants/x/real-key" in prefixes


def _consultation_report(agency, student, object_key):
    """The FK chain a ConsultationReport reaches its student through.

    Matches apps/audit/redaction.py's REDACT subject path exactly:
    pack_version__run__profile_version__student_id.
    """
    profile_version = StudentProfileVersion.objects.create(
        tenant=agency, student=student, version=1, schema_version=1, snapshot={}
    )
    run = RecommendationRun.objects.create(tenant=agency, profile_version=profile_version)
    pack_version = PackVersion.objects.create(tenant=agency, run=run, version=1)
    return ConsultationReport.objects.create(
        tenant=agency,
        pack_version=pack_version,
        object_key=object_key,
        s3_version_id="v1",
        sha256="a" * 64,
    )


def test_delete_student_documents_purges_the_students_consultation_report(
    agency_a, django_user_model
):
    """ConsultationReport.object_key sits under NEITHER prefix this function
    already purges: apps/reports/services.py::generate_report writes to
    tenants/{tenant}/reports/{pack_id}/{digest}.html, not the student prefix
    and not a DocumentVersion row.

    This matters because the key is reconstructible even after redaction:
    sha256, s3_version_id and the pack_version FK are all KEEP-class and
    survive apps/audit/redaction.py, and the key is built from exactly
    tenant_id + pack.id + digest -- all of which survive. Emptying the
    column removes our ability to FIND the object, not anyone's ability to
    read it, so it must be purged here, by exact key, before redaction runs.
    """
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "report-student")
        report = _consultation_report(
            agency_a, student, "tenants/x/reports/pack-1/deadbeef.html"
        )

    client = MagicMock()
    client.list_object_versions.return_value = {"IsTruncated": False}
    delete_student_documents(tenant_id=agency_a.id, student_id=student.id, client=client)

    prefixes = [call.kwargs["Prefix"] for call in client.list_object_versions.call_args_list]
    assert report.object_key in prefixes


def test_delete_student_documents_does_not_purge_another_students_report(
    agency_a, django_user_model
):
    """Erasure is one person's, not the agency's -- same guarantee the
    quarantine-upload test above pins for DocumentVersion."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "report-student-2")
        sibling = _student(agency_a, django_user_model, "report-sibling")
        _consultation_report(agency_a, sibling, "tenants/x/reports/pack-2/cafebabe.html")

    client = MagicMock()
    client.list_object_versions.return_value = {"IsTruncated": False}
    delete_student_documents(tenant_id=agency_a.id, student_id=student.id, client=client)

    prefixes = [call.kwargs["Prefix"] for call in client.list_object_versions.call_args_list]
    assert "tenants/x/reports/pack-2/cafebabe.html" not in prefixes


def test_erasure_reaches_a_promoted_upload(agency_a):
    """No new deletion code: the student prefix the purge already walks holds uploads/."""
    from apps.documents.storage import upload_key

    tenant_id, student_id, document_id = agency_a.id, uuid4(), uuid4()
    key = upload_key(tenant_id=tenant_id, student_id=student_id, document_id=document_id,
                     version="abc")
    assert key.startswith(f"tenants/{tenant_id}/students/{student_id}/")
    client = MagicMock()
    client.list_object_versions.return_value = {
        "Versions": [{"Key": key, "VersionId": "v1"}], "DeleteMarkers": [], "IsTruncated": False,
    }
    delete_student_documents(tenant_id=tenant_id, student_id=student_id, client=client)
    deleted = client.delete_objects.call_args_list[0].kwargs["Delete"]["Objects"]
    assert {"Key": key, "VersionId": "v1"} in deleted
