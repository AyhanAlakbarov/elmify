"""The short queue of things the extension should do next.

Nothing writes to it in this plan: the producers are the mailbox connection
(plan 4) and owner decisions 5, 6 and 7. What this plan owns is the shape --
above all that a completed action stops carrying its payload, because a portal
verification URL is a bearer credential for the student's portal account.
"""

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_a_completed_action_keeps_no_payload(agency_a, membership_a) -> None:
    from apps.portals.actions import complete_action, queue_action
    from apps.portals.models import DeviceAction

    with tenant_scope(agency_a.id):
        action = queue_action(
            membership_a,
            DeviceAction.Kind.OPEN_VERIFICATION_URL,
            {"url": "https://apply.example.edu/verify?t=secret"},
        )
        complete_action(action)
        action.refresh_from_db()

    assert action.payload == {}
    assert action.completed_at is not None


def test_pending_actions_exclude_delivered_completed_and_expired(agency_a, membership_a) -> None:
    from datetime import timedelta

    from apps.portals.actions import pending_actions, queue_action
    from apps.portals.models import DeviceAction

    with tenant_scope(agency_a.id):
        live = queue_action(membership_a, DeviceAction.Kind.TYPE_CODE, {"code": "123456"})
        expired = queue_action(membership_a, DeviceAction.Kind.TYPE_CODE, {"code": "999999"})
        DeviceAction.objects.filter(pk=expired.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        first = pending_actions(membership_a)
        second = pending_actions(membership_a)

    assert [a.id for a in first] == [live.id]
    assert second == []  # delivered once


def test_one_student_never_sees_another_s_actions(agency_a, membership_a, user_b) -> None:
    from apps.portals.actions import pending_actions, queue_action
    from apps.portals.models import DeviceAction
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        queue_action(other, DeviceAction.Kind.TYPE_CODE, {"code": "123456"})

        assert pending_actions(membership_a) == []


def test_a_caller_may_widen_the_default_ttl(agency_a, membership_a) -> None:
    """The 15-minute default assumes the student is already at the dashboard.

    An action a background sweep queues has no such student standing by, so
    its producer must be able to ask for a longer window -- default unchanged
    for every caller that doesn't.
    """
    from datetime import timedelta

    from apps.portals.actions import ACTION_TTL, queue_action
    from apps.portals.models import DeviceAction

    with tenant_scope(agency_a.id):
        default = queue_action(membership_a, DeviceAction.Kind.TYPE_CODE, {"code": "111111"})
        widened = queue_action(
            membership_a,
            DeviceAction.Kind.TYPE_CODE,
            {"code": "222222"},
            ttl=timedelta(hours=1, minutes=30),
        )

    default_life = default.expires_at - default.created_at
    widened_life = widened.expires_at - widened.created_at
    assert abs(default_life - ACTION_TTL) < timedelta(seconds=5)
    assert abs(widened_life - timedelta(hours=1, minutes=30)) < timedelta(seconds=5)


def test_every_new_column_is_classified_for_erasure() -> None:
    from apps.audit.redaction import KEEP, REDACT

    keep = set(KEEP["portals.DeviceAction"])
    redact = set(REDACT["portals.DeviceAction"].fields)
    assert keep | redact == {
        "kind",
        "payload",
        "created_at",
        "delivered_at",
        "completed_at",
        "expires_at",
    }
