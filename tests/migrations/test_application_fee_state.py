"""portals/0038 sets every existing card's fee state from its candidate's fee
copy. portals_application and funding_recommendationcandidate are FORCE RLS
and the migration sets no app.tenant_id, so it lifts FORCE around its UPDATE
(the concierge/0016 pattern) and the test checks FORCE is back afterwards."""

from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.funding.models import RecommendationCandidate
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_run

BEFORE = {"portals": "0036_reference_letter_slots"}
AFTER = {"portals": "0038_application_fee_state_backfill"}


def _migrate(selected: dict[str, str]) -> None:
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in selected]
    executor.migrate([*targets, *selected.items()])


def _state(application_id) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT fee_state FROM portals_application WHERE id = %s", [application_id])
        return cursor.fetchone()[0]


def _forced(table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", [table])
        return cursor.fetchone()[0]


@pytest.mark.django_db(transaction=True)
def test_existing_cards_take_their_fee_state_from_their_candidate(agency_a, membership_a):
    run = make_run(agency_a, membership_a)
    cards = {}
    try:
        with tenant_scope(agency_a.id):
            for name, fee in (("paid", "75.00"), ("free", "0.00"), ("silent", None)):
                candidate = make_db_candidate(agency_a, run, program_name=name)
                RecommendationCandidate.objects.filter(id=candidate.id).update(
                    application_fee=fee
                )
                cards[name] = Application.objects.create(
                    tenant=agency_a, student=membership_a, program_id=uuid4(),
                    candidate=candidate,
                ).id
            cards["none"] = Application.objects.create(
                tenant=agency_a, student=membership_a, program_id=uuid4(), name="Offer"
            ).id

        _migrate(BEFORE)  # drops the columns; the rows stay
        _migrate(AFTER)   # adds them at UNKNOWN, then backfills

        assert {name: _state(card) for name, card in cards.items()} == {
            "paid": "OPEN", "free": "NONE", "silent": "UNKNOWN", "none": "UNKNOWN",
        }
        assert _forced("portals_application") and _forced("funding_recommendationcandidate")
    finally:
        _migrate({})
        with tenant_scope(agency_a.id):
            Application.objects.filter(student=membership_a).delete()
