"""What a platform operator may do: list, open, decide, park -- within a daily cap.

The operator is recorded in AuditEvent under the platform agency, never on the
item (plan "Corrections" 4). Most of these run as the test superuser; the last
two run the ORM behind a real NOBYPASSRLS role, because the superuser bypasses
the platform policy and would pass them for the wrong reason (CLAUDE.md).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.funding.models import AuditEvent
from apps.research.models import ResolutionItem
from apps.research.resolution.operator import (
    DecisionRefused,
    decide,
    decisions_today,
    listing,
    open_item,
    park,
)
from apps.research.resolution.priority import rows
from apps.research.resolution.writers import file_item
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db

_HOST = {"host": "shut.test", "url": "https://shut.test/p", "trail": []}


def _item(subject="host:shut.test", **facts):
    return file_item("HOST_UNREACHABLE", subject, {**_HOST, "host": subject[5:]}, **facts)


def test_deciding_records_the_resolution_and_the_operator_in_audit(platform, operator) -> None:
    item = _item()
    with tenant_scope(platform.id):
        decide(item.id, operator, {"option": "closed"}, now=timezone.now())
        event = AuditEvent.objects.get(object_id=item.id, event="resolution.decided")
    item.refresh_from_db()
    assert item.state == "DECIDED" and item.resolution == {"option": "closed", "url": ""}
    assert item.decided_at is not None
    assert event.actor_id == operator.id and event.tenant_id == platform.id


def test_a_parked_item_needs_a_second_operator(platform, operator, second_operator) -> None:
    item = _item()
    with tenant_scope(platform.id):
        park(item.id, operator)
        assert AuditEvent.objects.filter(
            object_id=item.id, event="resolution.parked", actor=operator
        ).exists()
        with pytest.raises(DecisionRefused, match="second operator"):
            decide(item.id, operator, {"option": "closed"}, now=timezone.now())
        assert item.id not in {row.item.id for row in listing(operator, now=timezone.now())}
        assert item.id in {row.item.id for row in listing(second_operator, now=timezone.now())}
        decide(item.id, second_operator, {"option": "closed"}, now=timezone.now())
    item.refresh_from_db()
    assert item.state == "DECIDED"


def test_the_daily_cap_bounds_both_listing_and_deciding(settings, platform, operator) -> None:
    settings.RESOLUTION_DAILY_CAP_PER_OPERATOR = 2
    items = [_item(f"host:h{i}.test") for i in range(3)]
    now = timezone.now()
    with tenant_scope(platform.id):
        assert len(listing(operator, now=now)) == 2
        decide(items[0].id, operator, {"option": "closed"}, now=now)
        park(items[1].id, operator, now=now)
        assert decisions_today(operator, now=now) == 2
        assert listing(operator, now=now) == []
        with pytest.raises(DecisionRefused, match="daily cap"):
            decide(items[2].id, operator, {"option": "closed"}, now=now)
        with pytest.raises(DecisionRefused, match="daily cap"):
            park(items[2].id, operator, now=now)
    assert ResolutionItem.objects.get(id=items[2].id).state == "OPEN"


def test_a_click_outside_the_closed_question_is_refused(platform, operator) -> None:
    item = _item()
    with tenant_scope(platform.id), pytest.raises(DecisionRefused):
        decide(item.id, operator, {"option": "delete_everything"}, now=timezone.now())
    item.refresh_from_db()
    assert item.state == "OPEN"
    with tenant_scope(platform.id):
        assert not AuditEvent.objects.filter(object_id=item.id).exists()


def test_a_decided_item_cannot_be_decided_or_parked_again(platform, operator,
                                                          second_operator) -> None:
    item = _item()
    with tenant_scope(platform.id):
        decide(item.id, operator, {"option": "closed"}, now=timezone.now())
        with pytest.raises(ResolutionItem.DoesNotExist):
            decide(item.id, second_operator, {"option": "closed"}, now=timezone.now())
        with pytest.raises(ResolutionItem.DoesNotExist):
            park(item.id, second_operator)


def test_opening_stamps_once(platform, operator) -> None:
    item = _item()
    first = timezone.now()
    with tenant_scope(platform.id):
        open_item(item.id, operator, now=first)
        open_item(item.id, operator, now=first + timedelta(minutes=5))
    item.refresh_from_db()
    assert item.opened_at == first


def test_pack_counts_are_not_computed_until_task_13(platform, operator) -> None:
    """Pack counts are Task 13's. Until then the listing says so -- never 0."""
    _item()
    with tenant_scope(platform.id):
        found = listing(operator, now=timezone.now())
    assert found and all(row.packs is None for row in found)


def test_the_sort_is_packs_then_registered_then_oldest(django_assert_num_queries) -> None:
    now = timezone.now()
    old_candidate = _item("host:a.test", country_code="TR")
    new_registered = _item("host:b.test", registered=True)
    old_registered = _item("host:c.test", registered=True)
    blocking = _item("host:d.test")
    ResolutionItem.objects.filter(id=old_candidate.id).update(created_at=now - timedelta(days=3))
    ResolutionItem.objects.filter(id=old_registered.id).update(created_at=now - timedelta(days=2))
    items = list(ResolutionItem.objects.all())
    packs = {blocking.id: 4}
    # D3: sorted from the item's own columns. Zero queries is the proof that
    # nothing here reaches the catalogue, which runtime_web cannot read.
    with django_assert_num_queries(0):
        ordered = rows(items, pack_count=lambda item: packs.get(item.id))
    assert [row.item.id for row in ordered] == [
        blocking.id, old_registered.id, new_registered.id, old_candidate.id
    ]
    assert ordered[-1].country_code == "TR"
    assert [row.packs for row in ordered] == [4, None, None, None]


@pytest.fixture
def filed(db):
    """Committed as the superuser BEFORE `rls_enforced_orm` swaps the role
    (requested after this): its role has DML on every table, but the policy
    admits no INSERT but runtime_engine's. Same shape as
    tests/audit/test_identity_rls.py."""
    return _item()


@pytest.mark.django_db(transaction=True)
def test_the_listing_behind_a_real_nobypassrls_role(
    platform, operator, agency_a, filed, rls_enforced_orm
) -> None:
    """The ORM path, not only the raw policy: under agency A's GUC the manager
    returns nothing and a decision finds no row; under the platform's the
    operator lists, opens and decides it."""
    with tenant_transaction(agency_a.id):
        assert ResolutionItem.objects.count() == 0
        with pytest.raises(ResolutionItem.DoesNotExist):
            ResolutionItem.objects.select_for_update().get(id=filed.id)
    now = timezone.now()
    with tenant_scope(platform.id), tenant_transaction(platform.id):
        assert ResolutionItem.objects.count() == 1
        assert [row.item.id for row in listing(operator, now=now)] == [filed.id]
        open_item(filed.id, operator, now=now)
        decide(filed.id, operator, {"option": "closed"}, now=now)
    with tenant_transaction(platform.id):
        assert ResolutionItem.objects.get().state == "DECIDED"


@pytest.mark.django_db(transaction=True)
def test_an_agency_cannot_decide_behind_the_real_policy(
    platform, operator, agency_a, filed, rls_enforced_orm
) -> None:
    with tenant_scope(platform.id), tenant_transaction(agency_a.id):
        with pytest.raises(ResolutionItem.DoesNotExist):
            decide(filed.id, operator, {"option": "closed"}, now=timezone.now())
    with tenant_transaction(platform.id):
        assert ResolutionItem.objects.get().state == "OPEN"
