"""An over-budget programme is written into the pool with its rank and copies,
never into the pack (lanes spec §7.8, §7.9)."""

from decimal import Decimal

import pytest

from apps.funding.models import CostComponent, PackCandidate, RecommendationCandidate
from apps.research.services import handle_research_message
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import EUR_RATES
from tests.funding.test_spine import _catalogue, _message, _run

pytestmark = pytest.mark.django_db(transaction=True)


def test_an_over_budget_programme_is_kept_in_the_pool_with_its_rank(agency_a, membership_a):
    silent, _ = _catalogue(with_award=False)
    dear, _ = _catalogue(with_award=False, program_name="MSc Computer Science Plus")
    CostComponent.objects.create(
        program=dear, kind="APPLICATION_FEE", amount=Decimal("600"), currency="EUR",
        period="ONE_OFF",
    )
    run = _run(agency_a, membership_a)  # make_profile's budget: 500.00 USD

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        kept = RecommendationCandidate.objects.get(run=run, program=dear)
        packed = RecommendationCandidate.objects.get(run=run, program=silent)

        assert not PackCandidate.objects.filter(pack_version=pack, candidate=kept).exists()
        assert PackCandidate.objects.filter(pack_version=pack, candidate=packed).exists()
        assert kept.state == RecommendationCandidate.State.VISIBLE
        assert (kept.application_fee, kept.application_fee_currency) == (Decimal("600.00"), "EUR")
        assert kept.provenance_reason_code == packed.provenance_reason_code
        assert kept.institution_name == "Example University"
        assert {kept.rank, packed.rank} == {1, 2}
        # No fee stated is "not known", never 0.00 (spec §7.4).
        assert (packed.application_fee, packed.application_fee_currency) == (None, "")
