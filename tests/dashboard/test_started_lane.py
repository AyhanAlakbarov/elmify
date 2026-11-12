"""P1-11: replacing a pack item never changes the student's application on it."""

import pytest
from django.utils import timezone

from apps.funding.services import current_pack, replace_candidate
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate

from .conftest import add_card

pytestmark = pytest.mark.django_db
NOW = timezone.now()


def test_replacing_a_candidate_leaves_its_started_paid_card_untouched(
    agency_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(
            agency_a, membership_a, programme, started_at=NOW, fee_state="PAID",
            fee_paid_source="STUDENT", fee_paid_at=NOW,
        )
        before = Application.objects.filter(id=card.id).values().get()
        spare = make_db_candidate(agency_a, programme.run, program_name="M.Sc. Physics")

        replace_candidate(current_pack(membership_a), programme.id, spare.id, membership_a)

        assert Application.objects.filter(id=card.id).values().get() == before
