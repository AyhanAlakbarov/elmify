"""A form that has drifted must not stop an application, and must not be
invisible afterwards."""

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
MOVED = [
    ENTRIES[0],
    {
        "profile_field": "personal.city",
        "action": {"selector": "#town", "method": "fill", "arguments": ["%value%"]},
    },
]
VALUES = {"identity.full_name": "Ada Byron", "personal.city": "London"}


class DriftingSession(FakePortalSession):
    """Every selector works except #city, which no longer resolves."""

    def act(self, action, variables):
        from apps.portals.engine import ActFailed

        if action.selector == "#city":
            raise ActFailed("#city: no element matched")
        super().act(action, variables)


def _fixtures(agency, student):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key="personal-details",
        form_url="https://apply.example.edu/personal",
        review_required=False,
    )
    field_map = FieldMap.objects.create(portal_form=form, version=1, entries=ENTRIES)
    application = Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )
    return form, field_map, application


def test_a_selector_miss_relearns_and_finishes(agency_a, membership_a):
    from apps.portals.models import FieldMap
    from apps.portals.recovery import fill_with_recovery

    session = DriftingSession()
    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)

        def relearn():
            return FieldMap.objects.create(portal_form=form, version=2, entries=MOVED)

        replacement = fill_with_recovery(
            session, application, field_map, VALUES, relearn=relearn
        )

        assert replacement.version == 2
        # Both fields end up filled, and the one that worked first time was
        # not typed twice.
        assert session.values == {"#name": "Ada Byron", "#town": "London"}
        # One FILL step per pass, naming exactly what that pass typed against
        # the map version it typed with. Neither overstates: the second pass
        # skipped the field the first one already got in.
        assert [
            (step.detail["field_map_version"], step.detail["filled"])
            for step in application.steps.filter(kind="FILL").order_by("sequence")
        ] == [(1, ["identity.full_name"]), (2, ["personal.city"])]


def test_the_recovery_names_both_field_map_versions(agency_a, membership_a):
    """§5.2 wants site changes to create review tasks rather than guesses. The
    spec satisfies that by recording, so the record has to be enough to review
    from: which portal, which page, what was replaced and by what."""
    from apps.portals.models import FieldMap, RecoveryEvent
    from apps.portals.recovery import fill_with_recovery

    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)
        fill_with_recovery(
            DriftingSession(),
            application,
            field_map,
            VALUES,
            relearn=lambda: FieldMap.objects.create(
                portal_form=form, version=2, entries=MOVED
            ),
        )

        event = RecoveryEvent.objects.get()
        assert event.kind == RecoveryEvent.Kind.SELECTOR_MISS
        assert event.portal_form_id == form.id
        assert event.replaced_field_map_id == field_map.id
        assert event.replacement_field_map.version == 2
        assert event.detail["profile_field"] == "personal.city"


def test_recovery_never_escalates_and_never_blocks(agency_a, membership_a):
    """The whole point of design point 5: a changed form is not a human's
    problem until re-learning it has also failed."""
    from apps.concierge.models import Notification
    from apps.portals.models import Application, FieldMap
    from apps.portals.recovery import fill_with_recovery

    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)
        fill_with_recovery(
            DriftingSession(),
            application,
            field_map,
            VALUES,
            relearn=lambda: FieldMap.objects.create(
                portal_form=form, version=2, entries=MOVED
            ),
        )

        application.refresh_from_db()
        assert application.state == Application.State.PREPARING
        assert not Notification.objects.exists()
        assert application.steps.filter(kind="RECOVERY").count() == 1


def test_a_second_miss_after_relearning_gives_up(agency_a, membership_a):
    """One re-learn, not a loop. A form we cannot map twice in a row is a
    portal error, and each attempt costs a full learn pass."""
    from apps.portals.fill import FillInterrupted
    from apps.portals.models import FieldMap
    from apps.portals.recovery import fill_with_recovery

    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)

        with pytest.raises(FillInterrupted) as raised:
            fill_with_recovery(
                DriftingSession(),
                application,
                field_map,
                VALUES,
                relearn=lambda: FieldMap.objects.create(
                    portal_form=form, version=2, entries=ENTRIES
                ),
            )

    # after_relearn is what lets prepare_application tell "nothing works on a
    # map learned seconds ago" apart from ordinary drift.
    assert raised.value.after_relearn is True


def test_the_relearn_supersedes_the_old_map_for_every_later_student(
    agency_a, membership_a
):
    """The cost thesis: a re-learn is paid once per form version, not once per
    application. If the old map stayed current, the next student would pay for
    the same drift again.

    The fake supersedes, exactly as the real learn_form does. Without that this
    passed for the wrong reason -- current_for orders by -version, so the new
    map would win even if nothing were ever superseded.
    """
    from apps.portals.models import FieldMap
    from apps.portals.recovery import fill_with_recovery

    def relearn(form):
        FieldMap.current_for(form, None).supersede()
        return FieldMap.objects.create(portal_form=form, version=2, entries=MOVED)

    with tenant_scope(agency_a.id):
        form, field_map, application = _fixtures(agency_a, membership_a)
        fill_with_recovery(
            DriftingSession(),
            application,
            field_map,
            VALUES,
            relearn=lambda: relearn(form),
        )

        field_map.refresh_from_db()
        assert field_map.superseded_at is not None
        assert FieldMap.current_for(form, None).version == 2
