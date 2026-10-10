from io import StringIO

import pytest
from django.core.management import call_command

from apps.documents.models import NarrativeInput
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _row(student, entity):
    return NarrativeInput.objects.create(
        student=student, kind=NarrativeInput.Kind.RESEARCH_FIT, proposed_by="ENGINE",
        text=f"{entity} leads the chair.",
        provenance={
            "program_id": "p", "sentence": f"{entity} leads the chair.", "entity": entity,
            "source_url": "https://www.tum.de/x", "page_digest": "d" * 64,
            "kind": "named_person", "rung": 1, "anchor_fact_id": None, "judgement": "strong",
            "topic_hash": "t", "cost_usd": 0.0, "provider": "exa",
        },
    )


def test_takedown_reaches_every_tenant_and_leaves_an_event(
    agency_a, agency_b, membership_a, membership_b
):
    with tenant_scope(agency_a.id):
        hit_a = _row(membership_a, "Prof. Dr. A. Schmidt")
        keep_a = _row(membership_a, "Chair of Robotics")
    with tenant_scope(agency_b.id):
        hit_b = _row(membership_b, "Prof. Dr. A. Schmidt")
    out = StringIO()
    call_command("research_fit_takedown", name="A. Schmidt", stdout=out)
    with tenant_scope(agency_a.id):
        hit_a.refresh_from_db()
        keep_a.refresh_from_db()
        assert hit_a.provenance is None and "removed" in hit_a.text
        assert keep_a.provenance["entity"] == "Chair of Robotics"
        assert AuditEvent.objects.filter(
            event="document.research_fit.takedown", object_id=hit_a.id
        ).exists()
    with tenant_scope(agency_b.id):
        hit_b.refresh_from_db()
        assert hit_b.provenance is None
    assert f"{agency_a.id}: 1 rows" in out.getvalue() and f"{agency_b.id}: 1 rows" in out.getvalue()


def test_dry_run_changes_nothing(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        hit = _row(membership_a, "Prof. Dr. A. Schmidt")
    call_command("research_fit_takedown", name="Schmidt", dry_run=True, stdout=StringIO())
    with tenant_scope(agency_a.id):
        hit.refresh_from_db()
        assert hit.provenance is not None
