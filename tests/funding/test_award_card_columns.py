"""The card's columns and the closed values the database holds them to."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.funding.models import FundingBenefit, FundingOpportunity

pytestmark = pytest.mark.django_db


def _opportunity(**fields):
    return FundingOpportunity.objects.create(
        canonical_key=f"read:{uuid4()}", name="Award", family="UNIVERSITY_WIDE",
        scope_type="GLOBAL", **fields,
    )


def test_a_row_holds_every_card_field():
    row = _opportunity(
        tuition="FULL", living="PARTIAL", timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
        duration_text="24 months", duration_months=24,
        card_quotes={"timing": "Decided before arrival."},
    )
    row.refresh_from_db()
    assert (row.tuition, row.timing, row.duration_months) == ("FULL", "PRE_ARRIVAL", 24)
    assert row.card_quotes == {"timing": "Decided before arrival."}


def test_a_row_no_reader_wrote_leaves_every_card_field_blank():
    row = _opportunity()
    assert (row.tuition, row.timing, row.cycle, row.duration_text) == ("", "", "", "")
    assert row.duration_months is None and row.card_quotes == {}


@pytest.mark.parametrize(
    "fields",
    [
        {"tuition": "HALF"}, {"living": "ALL"}, {"timing": "SOON"}, {"cycle": "BIENNIAL"},
        {"duration_months": 0}, {"duration_months": 121},
    ],
)
def test_the_database_refuses_a_value_outside_the_closed_lists(fields):
    with pytest.raises(IntegrityError), transaction.atomic():
        _opportunity(**fields)


def test_a_benefit_keeps_the_words_its_figure_was_read_from():
    award = _opportunity()
    benefit = FundingBenefit.objects.create(
        opportunity=award, kind="STIPEND", amount=Decimal("1200"), currency="EUR",
        period="MONTHLY", description="x", amount_text="€1,200", amount_bound="EXACT",
        amount_quote="Scholars receive €1,200 per month.",
    )
    benefit.refresh_from_db()
    assert (benefit.amount_text, benefit.amount_bound) == ("€1,200", "EXACT")


def test_an_amount_bound_outside_the_closed_list_is_refused():
    award = _opportunity()
    with pytest.raises(IntegrityError), transaction.atomic():
        FundingBenefit.objects.create(
            opportunity=award, kind="STIPEND", period="MONTHLY", description="x",
            amount_bound="ABOUT",
        )
