"""What a platform operator may do, and nothing an agency may.

Runs inside a web request on the platform agency's host, as `runtime_web`:
`app.tenant_id` is the platform's, so research_resolutionitem's policies admit
SELECT and UPDATE and nothing else. On any other agency's host the same code
finds zero rows -- `get` raises DoesNotExist and the view answers 404.

The operator is recorded in AuditEvent (tenant-scoped, under the platform
agency, which erasure reaches), never on the item -- plan "Corrections" 4. So
"a different operator from any who parked it" and the per-operator daily cap
are both answered from AuditEvent. Callers must be inside
`tenant_scope(<platform>)`, which the request already is.

Nothing here may read a catalogue table: `runtime_web` holds no grant on one.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.funding.models import AuditEvent
from apps.research.models import ResolutionItem
from apps.tenancy.models import Membership

from .kinds import KINDS, resolution_for
from .priority import PackCounter, QueueRow, no_pack_count, rows

DECIDED = "resolution.decided"
PARKED = "resolution.parked"
#: Both spend the operator's attention, so both count against the cap.
_COUNTED = (DECIDED, PARKED)
_LIVE = (ResolutionItem.State.OPEN, ResolutionItem.State.PARKED)


class DecisionRefused(ValueError):
    pass


def decisions_today(operator: Membership, *, now: datetime) -> int:
    # UTC midnight. django.utils.timezone.utc was removed in Django 5.0.
    start = datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)
    return AuditEvent.objects.filter(
        actor=operator, event__in=_COUNTED, created_at__gte=start
    ).count()


def _require_under_cap(operator: Membership, now: datetime) -> None:
    if decisions_today(operator, now=now) >= settings.RESOLUTION_DAILY_CAP_PER_OPERATOR:
        raise DecisionRefused("daily cap reached")


def _parked_by(item_id: UUID) -> set[UUID | None]:
    return set(
        AuditEvent.objects.filter(event=PARKED, object_id=item_id).values_list(
            "actor_id", flat=True
        )
    )


def listing(
    operator: Membership, *, now: datetime, pack_count: PackCounter = no_pack_count
) -> list[QueueRow]:
    """The live items this operator may still answer today, in priority order.

    An item this operator parked is someone else's now, so it is left out."""
    remaining = settings.RESOLUTION_DAILY_CAP_PER_OPERATOR - decisions_today(operator, now=now)
    if remaining <= 0:
        return []
    mine = AuditEvent.objects.filter(event=PARKED, actor=operator).values_list(
        "object_id", flat=True
    )
    live = ResolutionItem.objects.filter(state__in=_LIVE).exclude(id__in=list(mine))
    return rows(live, pack_count=pack_count)[:remaining]


def waiting_for_the_applier() -> int:
    return ResolutionItem.objects.filter(state=ResolutionItem.State.DECIDED).count()


def open_item(item_id: UUID, operator: Membership, *, now: datetime) -> ResolutionItem:
    """Stamps `opened_at` once. An opened item no longer expires unanswered."""
    item = ResolutionItem.objects.get(id=item_id)
    if item.opened_at is None:
        ResolutionItem.objects.filter(id=item_id, opened_at__isnull=True).update(opened_at=now)
        item.opened_at = now
    return item


@transaction.atomic
def decide(
    item_id: UUID, operator: Membership, data: dict[str, object], *, now: datetime
) -> ResolutionItem:
    """Record an answer for `apply_resolutions` to write back.

    Raises ResolutionItem.DoesNotExist for an item that is not live (or not
    visible), DecisionRefused for everything else a person must be told."""
    item = ResolutionItem.objects.select_for_update().get(id=item_id, state__in=_LIVE)
    if operator.id in _parked_by(item.id):
        raise DecisionRefused("you parked this; it needs a second operator")
    _require_under_cap(operator, now)
    spec = KINDS[item.kind]
    try:
        resolution = resolution_for(
            item.kind, data, evidence=spec.evidence.model_validate(item.evidence)
        )
    except ValidationError as error:
        raise DecisionRefused(
            f"not an answer to this question: {error.error_count()} error(s)"
        ) from error
    item.state = ResolutionItem.State.DECIDED
    item.resolution = resolution.model_dump(mode="json")
    item.decided_at = now
    item.apply_error = ""
    item.save(update_fields=["state", "resolution", "decided_at", "apply_error"])
    AuditEvent.objects.create(actor=operator, event=DECIDED, object_id=item.id)
    return item


@transaction.atomic
def park(item_id: UUID, operator: Membership, *, now: datetime | None = None) -> ResolutionItem:
    """ "I don't know" (spec 11): parks the item for a second operator."""
    item = ResolutionItem.objects.select_for_update().get(id=item_id, state__in=_LIVE)
    _require_under_cap(operator, now or timezone.now())
    item.state = ResolutionItem.State.PARKED
    item.save(update_fields=["state"])
    AuditEvent.objects.create(actor=operator, event=PARKED, object_id=item.id)
    return item
