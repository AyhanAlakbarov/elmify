"""EvidenceReading behind FORCE row-level security, as the runtime role sees it.

The suite's own role bypasses RLS, so isolation and erasure are only proven
behind rls_enforced_orm (tests/conftest.py), which repoints Django's default
connection at a NOBYPASSRLS role. Fixtures are committed as the superuser first.
"""

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.documents.models import EvidenceReading
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction


def _write(tenant_id, student_id, repo):
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        EvidenceReading.objects.create(
            tenant_id=tenant_id, student_id=student_id, source_kind="github", repo=repo,
            changed_at=timezone.now(), reader_version=1, read_at=timezone.now(),
            reading={"summary": "A solver."},
        )


def _count(tenant_id):
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        return EvidenceReading.objects.count()


@pytest.fixture
def approved_erasure(agency_a, membership_a):
    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    with tenant_scope(agency_a.id):
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
    return request


@pytest.mark.django_db(transaction=True)
def test_a_reading_is_invisible_to_another_tenant_and_without_the_setting(
    agency_a, agency_b, membership_a, rls_enforced_orm
):
    _write(agency_a.id, membership_a.id, "0rkhann/MicroKatc")
    assert _count(agency_a.id) == 1
    assert _count(agency_b.id) == 0
    with tenant_scope(agency_a.id):
        assert EvidenceReading.objects.count() == 0  # no app.tenant_id: the policy hides it


@pytest.mark.django_db
def test_a_reading_cannot_name_another_tenants_student(agency_a, membership_b):
    with pytest.raises(IntegrityError), tenant_scope(agency_a.id), transaction.atomic():
        EvidenceReading.objects.create(
            tenant=agency_a, student=membership_b, source_kind="github", repo="x/y",
            changed_at=timezone.now(), reader_version=1, read_at=timezone.now(), reading={},
        )


@pytest.mark.django_db
def test_one_reading_per_repo_and_the_shape_of_each_kind(agency_a, membership_a):
    _write(agency_a.id, membership_a.id, "0rkhann/MicroKatc")
    with pytest.raises(IntegrityError), tenant_scope(agency_a.id), transaction.atomic():
        _write(agency_a.id, membership_a.id, "0rkhann/MicroKatc")
    with pytest.raises(IntegrityError), tenant_scope(agency_a.id), transaction.atomic():
        EvidenceReading.objects.create(  # a pdf reading must point at its upload
            tenant=agency_a, student=membership_a, source_kind="pdf", repo="",
            changed_at=timezone.now(), reader_version=1, read_at=timezone.now(), reading={},
        )


@pytest.mark.django_db(transaction=True)
def test_erasing_a_student_deletes_their_readings_under_row_level_security(
    agency_a, membership_a, approved_erasure, rls_enforced_orm, monkeypatch
):
    """Two rows on purpose: redaction empties `repo` before the delete, and two
    emptied rows must not collide on the one-reading-per-repo constraint."""
    from apps.audit import deletion

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    _write(agency_a.id, membership_a.id, "0rkhann/a")
    _write(agency_a.id, membership_a.id, "0rkhann/b")

    with tenant_scope(agency_a.id):
        deletion.advance_deletion(approved_erasure, "EXECUTED")

    assert _count(agency_a.id) == 0


def test_final_12_erasing_a_student_forgets_their_refresh_cache_state(
    agency_a, membership_a, approved_erasure, monkeypatch
):
    """The typed login sits under the 7-day unknown-login key; erasure removes it."""
    from django.core.cache import cache

    from apps.audit import deletion
    from apps.documents.evidence import refresh

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    cache.set(refresh._UNKNOWN_KEY.format(membership_a.id), "0rkhann")
    cache.set(refresh._DONE_KEY.format(membership_a.id), True)

    with tenant_scope(agency_a.id):
        deletion.advance_deletion(approved_erasure, "EXECUTED")

    assert refresh.unknown_login(membership_a.id) == ""
    assert cache.get(refresh._DONE_KEY.format(membership_a.id)) is None
