"""prepare_application: fill, verify, stop. It must never submit."""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db

ENTRIES = [
    {
        "profile_field": "identity.full_name",
        "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
    },
    {
        "profile_field": "personal.city",
        "action": {"selector": "#city", "method": "fill", "arguments": ["%value%"]},
    },
]


def _application_with_map(agency, student, *, entries=None):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"personal-details-{uuid4()}",
        form_url="https://apply.example.edu/personal",
        review_required=False,
    )
    FieldMap.objects.create(portal_form=form, version=1, entries=entries or ENTRIES)
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_a_complete_application_reaches_ready_to_submit(
    agency_a, membership_a, monkeypatch
):
    from apps.portals import services
    from apps.portals.models import Application

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    session = FakePortalSession()
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, session)

        application.refresh_from_db()
        assert application.state == Application.State.READY_TO_SUBMIT
        assert session.values == {"#name": "Ada Byron", "#city": "London"}
        assert session.visited == ["https://apply.example.edu/personal"]


def test_preparing_makes_no_llm_call(agency_a, membership_a, monkeypatch):
    """The cost thesis, asserted where it is spent. A prepare that observes is
    a prepare that costs $0.76 per student instead of per form version."""
    from apps.portals import services

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    session = FakePortalSession()
    with tenant_scope(agency_a.id):
        services.prepare_application(_application_with_map(agency_a, membership_a), session)

    assert session.observe_calls == 0


def test_a_missing_verified_fact_escalates_and_names_the_field(
    agency_a, membership_a, monkeypatch
):
    from apps.concierge.models import Notification
    from apps.portals import services
    from apps.portals.models import Application

    monkeypatch.setattr(
        services, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    session = FakePortalSession()
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, session)

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_MISSING_FACT
        assert "personal.city" in Notification.objects.get().message
        # Nothing was typed: a half-filled form on a real portal is worse than
        # one never started.
        assert session.values == {}


def test_a_read_back_mismatch_escalates_as_a_portal_error(
    agency_a, membership_a, monkeypatch
):
    """The page holding something other than what we typed is not something to
    retry -- it means a selector resolved somewhere unexpected."""
    from apps.portals import services
    from apps.portals.models import Application

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )

    class Diverging(FakePortalSession):
        def read_value(self, selector):
            return "something else" if selector == "#city" else super().read_value(selector)

    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, Diverging())

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR


def test_the_first_application_on_a_portal_gets_a_review_task(
    agency_a, membership_a, counselor_membership, monkeypatch
):
    from apps.concierge.models import RoadmapItem
    from apps.portals import services
    from apps.portals.models import Application
    from apps.tenancy.models import CounselorAssignment

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application_with_map(agency_a, membership_a)
        application.portal_form.review_required = True
        application.portal_form.save(update_fields=["review_required"])

        services.prepare_application(application, FakePortalSession())

        application.refresh_from_db()
        assert application.state == Application.State.READY_TO_SUBMIT
        assert RoadmapItem.objects.filter(owner=counselor_membership).exists()


def test_the_audit_trail_records_the_versions_used(agency_a, membership_a, monkeypatch):
    """§5.5: profile and document versions used, form answers, agent actions."""
    from apps.portals import services

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, FakePortalSession())

        kinds = list(application.steps.order_by("sequence").values_list("kind", flat=True))
        assert kinds == ["FILL", "READ_BACK"]
        fill_step = application.steps.get(kind="FILL")
        assert fill_step.detail["field_map_version"] == 1
        assert fill_step.detail["filled"] == ["identity.full_name", "personal.city"]
        # The answers themselves are audit evidence and belong here; the
        # student's values never reach FieldMap, which is the shared table.
        assert fill_step.detail["values"]["personal.city"] == "London"


def _session_that_raises(exception):
    """A session whose act() raises, so the fill path can be pointed at any
    exception the learn or engine layers can produce."""

    class Raising(FakePortalSession):
        def act(self, action, variables):
            raise exception

    return Raising()


def _page_controlled_failures():
    """(exception, the page-controlled substring its message carries).

    PIILeak names the selector observe() returned; OffDomain names the host the
    page navigated to. An escalation detail reaches a Notification and a log
    line, so neither string may be interpolated into one.
    """
    from apps.portals.engine import OffDomain
    from apps.portals.learn import PIILeak

    return [
        (
            PIILeak("learned action for #evil-from-the-page contains a student value"),
            "#evil-from-the-page",
        ),
        (
            OffDomain("expected apply.example.edu, page is on evil.example.test"),
            "evil.example.test",
        ),
    ]


@pytest.mark.parametrize("index", [0, 1])
def test_a_security_relevant_failure_escalates_instead_of_killing_the_worker(
    agency_a, membership_a, monkeypatch, index
):
    """Both were reachable and neither was caught: PIILeak from relearn(),
    OffDomain from every session call. An uncaught one stranded the application
    in PREPARING with no exception_item and nobody notified -- exactly what the
    six-trigger surface exists to prevent."""
    from apps.concierge.models import Notification
    from apps.portals import services
    from apps.portals.models import Application

    error, page_controlled = _page_controlled_failures()[index]
    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, _session_that_raises(error))

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR
        assert application.exception_item is not None
        assert page_controlled not in Notification.objects.get().message


def test_an_unanticipated_crash_escalates_and_is_still_re_raised(agency_a, membership_a):
    """Escalate AND re-raise. Not escalating leaves the application in PREPARING
    with no exception_item, which is the failure the six triggers exist to
    prevent; swallowing the exception would delete the SQS message on this
    delivery as if the work had succeeded.

    Deliberately NOT claiming this reaches the DLQ: escalate() moves the state,
    so the redelivery hits handle_portal_message's state check and the message
    is deleted rather than accumulating receives. That is the design working.
    """
    from contextlib import contextmanager

    from apps.concierge.models import Notification
    from apps.portals import worker
    from apps.portals.models import Application
    from apps.portals.schemas import PortalMessage

    @contextmanager
    def exploding(_application):
        raise RuntimeError("chrome died holding <script>from the page</script>")
        yield  # pragma: no cover -- never reached

    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)
        message = PortalMessage(
            kind="prepare_application", tenant_id=agency_a.id, application_id=application.id
        )

        with pytest.raises(RuntimeError):
            worker.handle_portal_message(message, session_factory=exploding)

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR
        assert application.exception_item is not None
        assert "<script>" not in Notification.objects.get().message


class _StuckSession(FakePortalSession):
    """Nothing on this page can be typed into, before or after a re-learn."""

    def __init__(self, elements=None):
        super().__init__(elements=elements)
        self.acts = 0

    def act(self, action, variables):
        from apps.portals.engine import ActFailed

        self.acts += 1
        raise ActFailed(f"{action.selector}: no element matched")


def test_a_partially_filled_form_records_what_was_typed(
    agency_a, membership_a, monkeypatch
):
    """The audit trail of what went into someone's live application. The
    exception carries a count -- "after 1 field(s)" -- and already_correct's
    skips break even the reconstruction from entry order, so the field names and
    their values have to be recorded from error.filled before escalating."""
    from apps.portals import services
    from apps.portals.engine import ActFailed
    from apps.portals.models import Application

    class OneFieldWorks(FakePortalSession):
        def act(self, action, variables):
            if action.selector == "#city":
                raise ActFailed("#city: no element matched")
            super().act(action, variables)

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)
        # The re-learn then fails (observe() maps nothing), which used to
        # discard the record of the first pass entirely.
        services.prepare_application(application, OneFieldWorks())

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR
        fill_step = application.steps.get(kind="FILL")
        assert fill_step.detail["filled"] == ["identity.full_name"]
        assert fill_step.detail["values"] == {"identity.full_name": "Ada Byron"}


def test_a_resumed_fill_records_only_what_it_typed(agency_a, membership_a, monkeypatch):
    """After a resume, already_correct skips whatever the portal's own draft
    still holds. Recording every entry in the map would claim the platform typed
    fields it deliberately left alone."""
    from apps.portals import services

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    session = FakePortalSession()
    # The portal's own persisted draft: #name is already correct on arrival.
    session.values["#name"] = "Ada Byron"
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        services.prepare_application(application, session)

        fill_step = application.steps.get(kind="FILL")
        assert fill_step.detail["filled"] == ["personal.city"]
        assert fill_step.detail["values"] == {"personal.city": "London"}


def test_a_stall_on_a_freshly_relearned_map_reaches_a_consultant(
    agency_a, membership_a, monkeypatch
):
    """§5.1's stall heuristic, wired where its premise is actually true: a
    second interrupted fill on a map learned seconds ago, with no challenge
    marker on the page. That is a challenge nobody recognises, not a portal
    error, so it goes to PORTAL_EXCEPTION rather than into the PORTAL_ERROR
    bucket where real portal failures live."""
    from apps.concierge.models import RoadmapItem
    from apps.portals import services
    from apps.portals.models import Application, FieldMap

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)
        monkeypatch.setattr(
            services,
            "learn_form",
            lambda *args, **kwargs: FieldMap.objects.create(
                portal_form=application.portal_form, version=2, entries=ENTRIES
            ),
            raising=False,
        )
        import apps.portals.learn as learn_module

        monkeypatch.setattr(
            learn_module,
            "learn_form",
            lambda *args, **kwargs: FieldMap.objects.create(
                portal_form=application.portal_form, version=2, entries=ENTRIES
            ),
        )

        services.prepare_application(application, _StuckSession())

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_CHALLENGE
        assert application.exception_item.stage == RoadmapItem.Stage.PORTAL_EXCEPTION
        # Nothing was typed on either pass, so there is no FILL step to write --
        # an empty one is noise in a trail whose job is naming what was typed.
        assert not application.steps.filter(kind="FILL").exists()


def test_a_first_miss_is_still_an_ordinary_portal_error(agency_a, membership_a, monkeypatch):
    """The stall heuristic must not swallow ordinary drift. One miss with no
    re-learn behind it is a PORTAL_ERROR, exactly as before."""
    from apps.portals import services
    from apps.portals.models import Application

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)

        import apps.portals.learn as learn_module

        def exploding_learn(*args, **kwargs):
            raise learn_module.UnmappedField("no usable action for personal.city")

        monkeypatch.setattr(learn_module, "learn_form", exploding_learn)
        services.prepare_application(application, _StuckSession())

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR


def test_a_failure_on_session_teardown_does_not_undo_a_finished_prepare(
    agency_a, membership_a, monkeypatch
):
    """The `with` in handle_portal_message raises on context-manager *exit* too
    -- _LoopThread.close()'s join timeout, browser teardown -- long after
    prepare_application returned. An unconditional escalate there would flip a
    READY_TO_SUBMIT application to BLOCKED_PORTAL_ERROR, notify a consultant
    about nothing, and (for an application that had already escalated) replace
    its exception_item and orphan the first RoadmapItem."""
    from contextlib import contextmanager

    from apps.concierge.models import Notification, RoadmapItem
    from apps.portals import services, worker
    from apps.portals.models import Application
    from apps.portals.schemas import PortalMessage

    monkeypatch.setattr(
        services,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )

    @contextmanager
    def dies_on_exit(_application):
        yield FakePortalSession()
        raise RuntimeError("browser teardown timed out")

    with tenant_scope(agency_a.id):
        application = _application_with_map(agency_a, membership_a)
        message = PortalMessage(
            kind="prepare_application", tenant_id=agency_a.id, application_id=application.id
        )

        with pytest.raises(RuntimeError):
            worker.handle_portal_message(message, session_factory=dies_on_exit)

        application.refresh_from_db()
        assert application.state == Application.State.READY_TO_SUBMIT
        assert application.exception_item is None
        assert not RoadmapItem.objects.exists()
        assert not Notification.objects.exists()
