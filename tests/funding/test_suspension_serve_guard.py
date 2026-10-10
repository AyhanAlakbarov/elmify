"""An award its own page withdrew must not reach a student.

Security audit 2026-09-23, finding 1. `served` became student-facing in this
slice, and three things had to be true for that to be safe. None of them was:
`review_funding` set `served = accepted` without looking at the suspension, the
operator queue never printed the suspension quote, and both downstream guards
missed the ordinary range and slash forms a funder writes a cycle in.
"""

import datetime as dt
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.funding.models import FundingOpportunity
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db


def _suspended_row(**overrides):
    organisation = record_organisation(
        domain="example-foundation.org", name="Example Foundation",
        kind="PRIVATE_FOUNDATION", country_code="DE", found_via="REGISTER",
    )
    fields = dict(
        canonical_key=f"read:holder:{uuid4()}",
        name="Foundation Stipend",
        family="PRIVATE_FOUNDATION",
        scope_type="HOLDER",
        holder="PRIVATE_FOUNDATION",
        holder_domain="example-foundation.org",
        holder_name="Example Foundation",
        organisation=organisation,
        agreement="AGREED",
        served=False,
        suspended_for="2026-2028",
        suspension_quote="No scholarships are offered for the 2026-2028 intakes.",
    )
    fields.update(overrides)
    return FundingOpportunity.objects.create(**fields)


@pytest.mark.django_db(transaction=True)
def test_the_database_refuses_a_served_row_that_carries_a_suspension():
    """The invariant both writers already satisfied and nothing enforced.
    `_served` needs offered == YES and `_suspension` only writes on NO, so this
    pair was impossible by construction -- until an operator's accept made it
    possible. A constraint is what makes it impossible again."""
    with pytest.raises(IntegrityError, match="funding_opportunity_served_not_suspended"):
        with transaction.atomic():
            _suspended_row(served=True)


def test_an_operator_cannot_serve_an_award_its_own_page_withdrew():
    """The operator queue lists exactly the served=False rows, which is where
    every suspension sits, and `review_funding` set served = accepted without
    reading the suspension. Accepting one published money the page denies."""
    from apps.research.funding_reader import review_funding

    row = _suspended_row()
    with pytest.raises(ValueError, match="withdrew|suspend"):
        review_funding(row, accepted=True, note="looks fine to me", now=dt.datetime.now(dt.UTC))
    row.refresh_from_db()
    assert row.served is False


def test_the_review_queue_prints_the_suspension_quote():
    """An operator who is not shown the sentence cannot be blamed for accepting
    the row. `_why` printed agreement, route and money form and never this."""
    from apps.research.management.commands.funding_review import _why

    assert "No scholarships are offered" in _why(_suspended_row())
