from datetime import timedelta

import pytest

from apps.research.models import ConsultantResearchTask
from apps.research.services import (
    DomainBusy,
    acquire_domain_lease,
    record_blocked_source,
)
from apps.tenancy.context import tenant_scope


@pytest.mark.django_db(transaction=True)
def test_domain_lease_blocks_overlapping_worker() -> None:
    acquire_domain_lease("official.test", interval=timedelta(minutes=1))
    with pytest.raises(DomainBusy):
        acquire_domain_lease("official.test", interval=timedelta(minutes=1))


@pytest.mark.django_db
def test_blocked_source_creates_one_open_consultant_task(agency_a) -> None:
    with tenant_scope(agency_a.id):
        first = record_blocked_source("https://official.test/blocked", "HTTP 403")
        second = record_blocked_source("https://official.test/blocked", "HTTP 403")
        assert first.id == second.id
        assert ConsultantResearchTask.objects.count() == 1


@pytest.mark.django_db
def test_the_blocked_source_reason_is_updated_not_frozen_at_the_first_one(agency_a) -> None:
    """get_or_create(defaults=) only consults `defaults` on CREATE, so the row
    kept the FIRST reason forever -- a task reading "timeout" months after the
    host began answering 403. This is the tenant queue now (a blocked catalogue
    host goes to the resolution queue instead), but a URL recurring across one
    agency's runs is still the common case."""
    with tenant_scope(agency_a.id):
        record_blocked_source("https://official.test/moved", "UNREACHABLE: timeout")
        record_blocked_source("https://official.test/moved", "BLOCKED: origin_403")

        task = ConsultantResearchTask.objects.get(
            url="https://official.test/moved", state=ConsultantResearchTask.State.OPEN
        )
        assert task.reason == "BLOCKED: origin_403"
        assert ConsultantResearchTask.objects.count() == 1
