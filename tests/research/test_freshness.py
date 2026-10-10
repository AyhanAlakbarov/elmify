from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.research.schemas import ResearchMessage
from apps.research.snapshot import is_stale


def test_snapshot_becomes_stale_after_freshness_window() -> None:
    checked_at = timezone.now() - timedelta(days=31)

    assert is_stale(checked_at, now=checked_at + timedelta(days=30, seconds=1)) is True
    assert is_stale(checked_at, now=checked_at + timedelta(days=29)) is False


def test_revalidation_message_rejects_a_missing_or_ambiguous_target() -> None:
    with pytest.raises(ValueError):
        ResearchMessage(kind="revalidate_source", tenant_id=uuid4(), run_id=uuid4())
    with pytest.raises(ValueError):
        ResearchMessage(
            kind="revalidate_source",
            tenant_id=uuid4(),
            run_id=uuid4(),
            source_id=uuid4(),
            snapshot_id=uuid4(),
        )

