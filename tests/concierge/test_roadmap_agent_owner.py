# tests/concierge/test_roadmap_agent_owner.py
from datetime import timedelta

import pytest
from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from apps.concierge.models import RoadmapItem
from apps.tenancy.context import tenant_scope


def _deadline():
    return timezone.now() + timedelta(days=14)


@pytest.mark.django_db
def test_a_counselor_owned_item_is_unchanged(agency_a, membership_a, counselor_membership):
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.DOCUMENTS,
            owner=counselor_membership,
            deadline=_deadline(),
        )
    assert item.owner_kind == RoadmapItem.OwnerKind.HUMAN
    assert item.owner == counselor_membership


@pytest.mark.django_db
def test_the_agent_can_own_an_item_without_a_membership(agency_a, membership_a):
    """§5.2 requires showing the owner of an agent-held step. This must not
    require a synthetic Membership row -- see the spec's Decision 2."""
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.PORTAL_EXCEPTION,
            owner=None,
            owner_kind=RoadmapItem.OwnerKind.AGENT,
            deadline=_deadline(),
        )
    assert item.owner is None
    assert item.owner_kind == RoadmapItem.OwnerKind.AGENT


@pytest.mark.django_db(transaction=True)
def test_an_unowned_item_is_not_silently_an_agent_item(agency_a, membership_a):
    """Nullable owner without the discriminator would make 'nobody owns this'
    and 'the agent owns this' the same row. The constraint forbids the first."""
    with tenant_scope(agency_a.id):
        with pytest.raises(IntegrityError, match="roadmapitem_owner_kind_matches_owner"):
            with transaction.atomic():
                RoadmapItem.objects.create(
                    tenant=agency_a,
                    student=membership_a,
                    stage=RoadmapItem.Stage.DOCUMENTS,
                    owner=None,
                    owner_kind=RoadmapItem.OwnerKind.HUMAN,
                    deadline=_deadline(),
                )


@pytest.mark.django_db(transaction=True)
def test_an_agent_item_cannot_also_carry_a_person(agency_a, membership_a, counselor_membership):
    with tenant_scope(agency_a.id):
        with pytest.raises(IntegrityError, match="roadmapitem_owner_kind_matches_owner"):
            with transaction.atomic():
                RoadmapItem.objects.create(
                    tenant=agency_a,
                    student=membership_a,
                    stage=RoadmapItem.Stage.DOCUMENTS,
                    owner=counselor_membership,
                    owner_kind=RoadmapItem.OwnerKind.AGENT,
                    deadline=_deadline(),
                )
