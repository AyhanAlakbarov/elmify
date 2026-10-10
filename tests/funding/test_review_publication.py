import pytest
from django.db import DatabaseError, transaction

from apps.funding.models import AuditEvent, PackCandidate, PackVersion
from apps.funding.services import PublicationBlocked, auto_publish_pack
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.funding.conftest import make_db_candidate, make_run


@pytest.fixture
def run(agency_a, membership_a):
    return make_run(agency_a, membership_a)


@pytest.fixture
def candidate(agency_a, run):
    return make_db_candidate(agency_a, run, program_name="MSc Chemistry", funding_gap="500.00")


@pytest.mark.django_db
def test_auto_publish_sets_published_at_and_run_state(agency_a, run, candidate):
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        published = auto_publish_pack(pack)
        assert published.published_at is not None
        run.refresh_from_db()
        assert run.state == run.State.PUBLISHED


@pytest.mark.django_db
def test_auto_publish_records_an_actorless_audit_event(agency_a, run, candidate):
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        auto_publish_pack(pack)
        event = AuditEvent.objects.get(event="pack.published", object_id=pack.id)
        assert event.actor_id is None


@pytest.mark.django_db
def test_superseded_pack_cannot_be_auto_published(agency_a, run, candidate):
    """Once a newer version of a run's pack is published, the old version it
    superseded must never be publishable again."""
    with tenant_scope(agency_a.id):
        pack_v1 = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack_v1, candidate=candidate)
        pack_v2 = PackVersion.objects.create(run=pack_v1.run, version=pack_v1.version + 1)
        auto_publish_pack(pack_v2)
        stale_pack_v1 = PackVersion.objects.get(id=pack_v1.id)
        assert stale_pack_v1.superseded_at is not None
        with pytest.raises(PublicationBlocked, match="superseded"):
            auto_publish_pack(stale_pack_v1)


@pytest.mark.django_db
def test_auto_publish_supersedes_an_already_published_sibling(agency_a, run, candidate):
    """Publishing a revision must supersede a prior version even if that prior
    version was already published itself (not just still a draft) — the
    supersede query used to only match published_at__isnull=True siblings."""
    with tenant_scope(agency_a.id):
        pack_v1 = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack_v1, candidate=candidate)
        auto_publish_pack(pack_v1)

        pack_v2 = PackVersion.objects.create(run=pack_v1.run, version=pack_v1.version + 1)
        auto_publish_pack(pack_v2)

        stale_pack_v1 = PackVersion.objects.get(id=pack_v1.id)
        assert stale_pack_v1.superseded_at is not None


@pytest.mark.django_db
def test_audit_event_cannot_be_updated(agency_a, counselor_membership):
    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.create(
            tenant=agency_a,
            actor=counselor_membership,
            event="pack.published",
            object_id=counselor_membership.id,
        )
        event.event = "rewritten"
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                event.save(update_fields=["event"])


@pytest.mark.django_db
def test_audit_event_cannot_be_deleted(agency_a, counselor_membership):
    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.create(
            tenant=agency_a,
            actor=counselor_membership,
            event="pack.published",
            object_id=counselor_membership.id,
        )
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                event.delete()


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_review_page_shows_the_published_pack_without_an_approval_form(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a, run, candidate
):
    from tests.conftest import verify_mfa_session

    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        auto_publish_pack(pack)
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)

    response = client.get(f"/counselor/runs/{run.id}/approve/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert b'name="action" value="approve"' not in response.content
    assert b"MSc Chemistry" in response.content


@pytest.mark.django_db(transaction=True)
def test_review_page_404s_for_a_counselor_not_assigned_to_the_run_student(
    client, agency_a, domain_a, counselor_user, counselor_membership, run, candidate
):
    """P1-13 requires assignment-scoped counselor access by default. Packs now
    auto-publish within milliseconds of a run finishing, so with no assignment
    check this page would be reachable by any counselor in the tenant for
    every run — this pins that a counselor with no active CounselorAssignment
    to the run's student is refused."""
    from tests.conftest import verify_mfa_session

    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        auto_publish_pack(pack)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)

    response = client.get(f"/counselor/runs/{run.id}/approve/", HTTP_HOST=domain_a.host)

    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_review_page_200s_for_a_counselor_assigned_to_the_run_student(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a, run, candidate
):
    from tests.conftest import verify_mfa_session

    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        auto_publish_pack(pack)
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)

    response = client.get(f"/counselor/runs/{run.id}/approve/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
