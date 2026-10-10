"""Deadline urgency and roadmap stage pill (D14). Db-free."""

from datetime import timedelta

from django.utils import timezone

from apps.concierge.models import RoadmapItem

Urgency = RoadmapItem.DeadlineUrgency


def _item(*, days_from_now: int, state: str = "PENDING") -> RoadmapItem:
    return RoadmapItem(
        stage=RoadmapItem.Stage.DOCUMENTS,
        state=state,
        deadline=timezone.now() + timedelta(days=days_from_now),
    )


def test_deadline_urgency_thresholds():
    assert _item(days_from_now=-1).deadline_urgency == Urgency.OVERDUE
    assert _item(days_from_now=3).deadline_urgency == Urgency.DUE_SOON
    assert _item(days_from_now=14).deadline_urgency == Urgency.DUE_SOON
    assert _item(days_from_now=15).deadline_urgency == Urgency.SCHEDULED
    # A finished item is never urgent, however old its deadline.
    assert _item(days_from_now=-30, state="DONE").deadline_urgency == Urgency.SCHEDULED
