from uuid import uuid4

import pytest

from apps.portals.challenge import Challenge
from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

CHALLENGE = Challenge(
    kind="hcaptcha",
    site_key="k",
    page_url="https://apply.example.edu/personal",
    response_selector="textarea[name='h-captcha-response']",
)


def _application(agency, student):
    from apps.portals.models import Application, PortalForm

    # form_key varies: PortalForm has a unique (portal_host, form_key)
    # constraint and these helpers are called more than once per test.
    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_the_service_is_tried_before_the_consultant(agency_a, membership_a):
    from apps.concierge.models import RoadmapItem
    from apps.portals.resolve import resolve_challenge

    class Solving:
        def solve(self, challenge, *, application):
            return "token-1"

    session = FakePortalSession()
    with tenant_scope(agency_a.id):
        # ServiceResolver is stubbed here, so the per-portal approval flag is
        # not in play -- that gate has its own test in test_resolve_service.py.
        assert resolve_challenge(
            session, CHALLENGE, application=_application(agency_a, membership_a), service=Solving()
        ) is True

        assert session.values[CHALLENGE.response_selector] == "token-1"
        # RoadmapItem is tenant-scoped and its manager requires tenant
        # context even for .exists(), so this stays inside the scope.
        assert not RoadmapItem.objects.exists()


def test_a_failed_service_falls_back_to_a_scoped_consultant_task(agency_a, membership_a):
    from apps.concierge.models import RoadmapItem
    from apps.portals.models import Application
    from apps.portals.resolve import ConsultantResolver, resolve_challenge

    class Failing:
        def solve(self, challenge, *, application):
            return None

    session = FakePortalSession()
    session.values["#name"] = "Ada Byron"
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        assert resolve_challenge(
            session,
            CHALLENGE,
            application=application,
            service=Failing(),
            consultant=ConsultantResolver(),
        ) is False

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_CHALLENGE
        assert application.exception_item.stage == RoadmapItem.Stage.PORTAL_EXCEPTION
        # Completed form state is preserved: nothing cleared the page and
        # nothing reset the application's steps.
        assert session.values["#name"] == "Ada Byron"
