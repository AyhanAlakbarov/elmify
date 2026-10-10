"""The device-action queue: deliver once, expire fast, keep no payload.

Nothing in this plan produces an action. The producers arrive with the mailbox
(plan 4) and owner decisions 5, 6 and 7. The queue ships first because plan 3's
extension polls it, and an empty queue is a testable contract while a missing
route is not.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.tenancy.models import Membership

from .models import Application, DeviceAction

#: Fifteen minutes. A verification link the student did not act on is better
#: re-issued than left live, and the dashboard is where they are standing.
ACTION_TTL = timedelta(minutes=15)


def queue_action(
    membership: Membership,
    kind: str,
    payload: dict[str, object],
    *,
    application: Application | None = None,
    ttl: timedelta = ACTION_TTL,
) -> DeviceAction:
    """Queue one action, live for ``ttl``.

    ACTION_TTL assumes a student already at the dashboard. A producer with no
    such student standing by -- the mailbox sweep (plan 4), which runs once an
    hour with nobody watching -- passes a longer ``ttl`` instead; every other
    caller keeps the short, foreground-appropriate default.
    """
    return DeviceAction.objects.create(
        tenant_id=membership.tenant_id,
        membership=membership,
        application=application,
        kind=kind,
        payload=payload,
        expires_at=timezone.now() + ttl,
    )


def pending_actions(membership: Membership) -> list[DeviceAction]:
    """This student's undelivered, unexpired actions -- marked delivered.

    Delivered once, not repeatedly: the payload is a credential, so handing it
    out on every poll would keep it in flight for as long as the student leaves
    the dashboard open.
    """
    now = timezone.now()
    actions = list(
        DeviceAction.objects.filter(
            membership=membership,
            delivered_at__isnull=True,
            completed_at__isnull=True,
            expires_at__gt=now,
        ).order_by("created_at")
    )
    if actions:
        DeviceAction.objects.filter(pk__in=[action.pk for action in actions]).update(
            delivered_at=now
        )
    return actions


def complete_action(action: DeviceAction) -> None:
    """Close an action and drop its payload.

    Takes no outcome: what happened belongs in the §5.5 trail as an
    ApplicationStep, which the route writes. A second copy on the action would
    be a second thing to erase.
    """
    DeviceAction.objects.filter(pk=action.pk).update(completed_at=timezone.now(), payload={})
    action.refresh_from_db()
