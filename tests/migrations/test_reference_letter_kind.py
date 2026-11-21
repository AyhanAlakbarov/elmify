"""concierge/0016 and portals/0034 rename the reference-letter kind RECOMMENDATION ->
REFERENCE_LETTER in every stored place: a DocumentVersion's kind and a learned box's
kind in FieldMap.slots. Both run forward and back through rows written at the old
shape. DocumentVersion is FORCE RLS and this migration sets no app.tenant_id, so the
test also checks FORCE is back on afterwards (the funding/0015 pattern)."""

import json
from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.concierge.models import DocumentVersion
from apps.portals.models import FieldMap, PortalForm
from apps.tenancy.context import tenant_scope

# documents/0028 depends on portals/0038, so it is pinned back too or the plan mixes directions.
BEFORE = {"documents": "0027_timeline_category", "concierge": "0015_documentversion_replace_or_add", "portals": "0035_extension_pairing_passwords_allowed"}
AFTER = {"documents": "0027_timeline_category", "concierge": "0016_reference_letter_kind", "portals": "0036_reference_letter_slots"}


def _migrate(selected: dict[str, str]) -> None:
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in selected]
    executor.migrate([*targets, *selected.items()])


def _stored(document_id, map_id) -> tuple[str, list[str]]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT kind FROM concierge_documentversion WHERE id = %s", [document_id])
        [kind] = cursor.fetchone()
        cursor.execute(
            "SELECT jsonb_path_query_array(slots, '$[*].kind') FROM portals_fieldmap "
            "WHERE id = %s", [map_id]
        )
        [slot_kinds] = cursor.fetchone()
    return kind, json.loads(slot_kinds) if isinstance(slot_kinds, str) else slot_kinds


def _forced() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relforcerowsecurity FROM pg_class "
            "WHERE oid = 'concierge_documentversion'::regclass"
        )
        return cursor.fetchone()[0]


@pytest.mark.django_db(transaction=True)
def test_the_reference_letter_kind_is_renamed_forward_and_back(agency_a, membership_a):
    try:
        _migrate(BEFORE)
        with tenant_scope(agency_a.id):
            letter = DocumentVersion.objects.create(
                tenant=agency_a, student=membership_a, object_key="k", kind="RECOMMENDATION"
            )
            other = DocumentVersion.objects.create(
                tenant=agency_a, student=membership_a, object_key="k2", kind="DIPLOMA"
            )
        form = PortalForm.objects.create(portal_host="apply.example.edu", form_key=str(uuid4()))
        slot = {"selector": "#s", "variant": "ANY", "degree": None, "sure": True}
        field_map = FieldMap.objects.create(
            portal_form=form, version=1,
            slots=[{**slot, "kind": "RECOMMENDATION"}, {**slot, "kind": "DIPLOMA"}],
        )

        _migrate(AFTER)
        assert _stored(letter.id, field_map.id) == ("REFERENCE_LETTER", ["REFERENCE_LETTER",
                                                                        "DIPLOMA"])
        assert _stored(other.id, field_map.id)[0] == "DIPLOMA"
        assert _forced()

        _migrate(BEFORE)
        assert _stored(letter.id, field_map.id) == ("RECOMMENDATION", ["RECOMMENDATION",
                                                                      "DIPLOMA"])
        assert _forced()
    finally:
        _migrate({})
        with tenant_scope(agency_a.id):
            DocumentVersion.objects.filter(student=membership_a).delete()
        PortalForm.objects.filter(portal_host="apply.example.edu").delete()
