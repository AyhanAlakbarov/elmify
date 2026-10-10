import pytest

from apps.portals import applications as applications_module
from apps.portals.applications import add_application, record_portal
from apps.portals.models import Application, PortalForm
from apps.portals.route_snapshot import RouteSnapshot, read_snapshot, snapshot_from_portal
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch):
    monkeypatch.setattr(applications_module, "enqueue_document_work", lambda *_a, **_k: None)


def test_the_agency_fallback_is_one_apply_step_on_the_recorded_portal() -> None:
    form = PortalForm(portal_host="apply.tum.de", form_key="/x", form_url="https://apply.tum.de/x")
    snapshot = RouteSnapshot.model_validate(snapshot_from_portal(form))
    assert snapshot.source == "AGENCY"
    assert [(s.position, s.purpose, s.channel, s.portal_url) for s in snapshot.steps] == [
        (1, "APPLY", "PORTAL", "https://apply.tum.de/x")
    ]


def test_a_card_without_a_portal_has_no_snapshot(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=candidate.id, actor=membership_a)
        assert card.route_snapshot == {}
        assert read_snapshot(card) is None


def test_recording_a_portal_fills_the_snapshot(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=candidate.id, actor=membership_a)
        record_portal(card, "https://apply.tum.de/msc", actor=membership_a)
        card.refresh_from_db()
        snapshot = read_snapshot(card)
    assert snapshot is not None
    assert snapshot.steps[0].portal_url == "https://apply.tum.de/msc"


def test_a_card_reusing_a_known_portal_gets_its_snapshot(
    agency_a, membership_a, user_b, program_factory
) -> None:
    from apps.funding.models import RecommendationCandidate
    from apps.tenancy.models import Membership

    program = program_factory()
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(program_id=program.id)
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        first = add_application(student=membership_a, candidate_id=candidate.id, actor=membership_a)
        record_portal(first, "https://apply.tum.de/msc", actor=membership_a)
    run_b = make_run(agency_a, other)
    candidate_b = make_db_candidate(agency_a, run_b, program_name="MSc Chemistry")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=candidate_b.id).update(program_id=program.id)
    make_published_pack(agency_a, run_b, (candidate_b,))
    with tenant_scope(agency_a.id):
        second = add_application(student=other, candidate_id=candidate_b.id, actor=other)
        snapshot = read_snapshot(second)
    assert snapshot is not None and snapshot.steps[0].portal_url == "https://apply.tum.de/msc"


def test_an_unreadable_snapshot_reads_as_none(agency_a, membership_a) -> None:
    card = Application(route_snapshot={"source": "nonsense"})
    assert read_snapshot(card) is None
