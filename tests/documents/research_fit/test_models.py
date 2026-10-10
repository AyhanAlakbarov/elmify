import pytest
from django.db import IntegrityError, transaction

from apps.documents.models import NarrativeInput
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_research_fit_kind_is_accepted_by_the_check_constraint(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        row = NarrativeInput.objects.create(
            student=membership_a,
            kind=NarrativeInput.Kind.RESEARCH_FIT,
            text="The Chair of Robotics hosts master's theses on legged locomotion.",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
            provenance={"entity": "Chair of Robotics", "rung": 1},
        )
        assert NarrativeInput.objects.get(pk=row.pk).provenance["entity"] == "Chair of Robotics"


def test_provenance_is_optional(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        row = NarrativeInput.objects.create(
            student=membership_a,
            kind=NarrativeInput.Kind.RESEARCH_PLAN,
            text="x",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
        )
        assert row.provenance is None


def test_an_unknown_kind_is_still_refused(agency_a, membership_a):
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        NarrativeInput.objects.create(
            student=membership_a, kind="NOT_A_KIND", text="x",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
        )
