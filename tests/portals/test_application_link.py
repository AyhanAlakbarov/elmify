from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.portals.models import Application, ApplicationLink
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _card(tenant, student) -> Application:
    return Application.objects.create(tenant=tenant, student=student, program_id=uuid4())


def test_a_link_joins_two_cards_once(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        programme, award = _card(agency_a, membership_a), _card(agency_a, membership_a)
        ApplicationLink.objects.create(tenant=agency_a, from_app=award, to_app=programme)
        assert award.links_out.get().order == ApplicationLink.Order.LINKED_ONLY
        with pytest.raises(IntegrityError), transaction.atomic():
            ApplicationLink.objects.create(tenant=agency_a, from_app=award, to_app=programme)


def test_a_card_cannot_link_to_itself(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        card = _card(agency_a, membership_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            ApplicationLink.objects.create(tenant=agency_a, from_app=card, to_app=card)


def test_a_link_cannot_cross_tenants(agency_a, agency_b, membership_a, membership_b) -> None:
    with tenant_scope(agency_a.id):
        mine = _card(agency_a, membership_a)
    with tenant_scope(agency_b.id):
        theirs = _card(agency_b, membership_b)
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        ApplicationLink.objects.create(tenant=agency_a, from_app=mine, to_app=theirs)


def test_a_link_cannot_start_from_another_tenants_card(
    agency_a, agency_b, membership_a, membership_b
) -> None:
    with tenant_scope(agency_a.id):
        mine = _card(agency_a, membership_a)
    with tenant_scope(agency_b.id):
        theirs = _card(agency_b, membership_b)
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        ApplicationLink.objects.create(tenant=agency_a, from_app=theirs, to_app=mine)


def test_deleting_a_card_removes_its_links(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        programme, award = _card(agency_a, membership_a), _card(agency_a, membership_a)
        ApplicationLink.objects.create(tenant=agency_a, from_app=award, to_app=programme)
        programme.delete()
        assert not ApplicationLink.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_a_link_is_invisible_to_another_tenant_under_rls(
    agency_a, agency_b, membership_a, rls_enforced_orm
) -> None:
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        one, two = _card(agency_a, membership_a), _card(agency_a, membership_a)
        ApplicationLink.objects.create(tenant=agency_a, from_app=one, to_app=two)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert ApplicationLink.objects.count() == 1
    # _base_manager skips the ORM filter, so only the policy can hide the row.
    with tenant_transaction(agency_b.id):
        assert ApplicationLink._base_manager.count() == 0
