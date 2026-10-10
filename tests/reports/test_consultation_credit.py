from decimal import Decimal

import pytest

from apps.concierge.models import ServiceEngagement
from apps.reports.models import ConsultationPayment
from apps.reports.services import ReportBlocked, apply_consultation_credit
from apps.tenancy.context import tenant_scope


@pytest.mark.django_db
def test_consultation_credit_applies_once(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        payment = ConsultationPayment.objects.create(
            tenant=agency_a,
            student=membership_a,
            amount="49.00",
            currency="USD",
            status="PAID",
        )
        engagement = ServiceEngagement.objects.create(
            tenant=agency_a,
            student=membership_a,
            platform_fee="199.00",
            currency="USD",
        )
        # Refresh so amount/platform_fee are real Decimals (as they would be
        # for objects loaded via a query), not the raw strings .create() kept.
        payment.refresh_from_db()
        engagement.refresh_from_db()
        apply_consultation_credit(payment, engagement)
        engagement.refresh_from_db()
        payment.refresh_from_db()
        assert engagement.credit_amount == Decimal("49.00")
        assert payment.credited_engagement_id == engagement.id

        with pytest.raises(ReportBlocked):
            apply_consultation_credit(payment, engagement)


@pytest.mark.django_db(transaction=True)
def test_concurrent_credit_applications_spend_it_once(agency_a, membership_a):
    """Two threads racing the same payment: exactly one wins, one is blocked."""
    import threading

    from django.db import connections

    with tenant_scope(agency_a.id):
        payment = ConsultationPayment.objects.create(
            tenant=agency_a,
            student=membership_a,
            amount="49.00",
            currency="USD",
            status="PAID",
        )
        engagements = [
            ServiceEngagement.objects.create(
                tenant=agency_a, student=membership_a, platform_fee="199.00", currency="USD"
            )
            for _ in range(2)
        ]
        payment.refresh_from_db()
        for engagement in engagements:
            engagement.refresh_from_db()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt(engagement: ServiceEngagement) -> None:
        try:
            with tenant_scope(agency_a.id):
                barrier.wait(timeout=5)
                apply_consultation_credit(payment, engagement)
                outcomes.append("applied")
        except ReportBlocked:
            outcomes.append("blocked")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=attempt, args=(e,)) for e in engagements]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(outcomes) == ["applied", "blocked"]
    with tenant_scope(agency_a.id):
        credited = [
            e
            for e in ServiceEngagement.objects.filter(id__in=[e.id for e in engagements])
            if e.credit_amount
        ]
    assert len(credited) == 1
