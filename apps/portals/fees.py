"""The application fee's state (lanes spec §3.2, §7.4).

One writer for "paid", shared by the student's button and a trusted receipt
email (apps/mailbox/actions.py), so a separate module that imports neither.
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction

from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.tenancy.models import Membership

from .models import Application

#: The states a fee can be marked paid from. An unknown fee can still have been paid.
PAYABLE = (Application.FeeState.OPEN, Application.FeeState.UNKNOWN)


def fee_state_for(candidate: RecommendationCandidate | None) -> str:
    """A new card's fee state from the candidate's copy. No copy (an award, a
    named programme, an accepted offer, a programme stating no fee) is UNKNOWN."""
    fee = candidate.application_fee if candidate is not None else None
    if fee is None:
        return Application.FeeState.UNKNOWN
    return Application.FeeState.NONE if fee == 0 else Application.FeeState.OPEN


def mark_fee_paid(
    application: Application, *, source: str, at: datetime, actor: Membership | None
) -> bool:
    """PAID, if the fee was OPEN or UNKNOWN; False otherwise.

    One conditional UPDATE, not read-then-write: two tabs pressing at once
    both pass any check made on a stale row, and only the database can let
    exactly one of them through.
    """
    with transaction.atomic():
        updated = Application.objects.filter(id=application.id, fee_state__in=PAYABLE).update(
            fee_state=Application.FeeState.PAID, fee_paid_at=at, fee_paid_source=source
        )
        if not updated:
            return False
        AuditEvent.objects.create(
            actor=actor, event="application.fee_paid", object_id=application.id
        )
    application.refresh_from_db(fields=["fee_state", "fee_paid_at", "fee_paid_source"])
    return True
