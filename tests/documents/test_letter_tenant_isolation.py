import pytest

from apps.documents.models import NarrativeInput
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def test_narrative_input_scoped_to_active_tenant(agency_a, agency_b, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lti1")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        NarrativeInput.objects.create(
            student=student, kind=NarrativeInput.Kind.RESEARCH_PLAN, text="x",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
        )
    with tenant_scope(agency_b.id):
        assert NarrativeInput.objects.count() == 0


def test_application_prompt_is_not_tenant_scoped_like_program(program_factory):
    """ApplicationPrompt follows Program's precedent (not tenant-scoped --
    it's a fact about the programme, shared across tenants), confirmed here
    so a future change to Program's tenancy model surfaces a failure here
    too, not silently."""
    from apps.funding.models import ApplicationPrompt, Program

    tenancy_models = __import__("apps.tenancy.models", fromlist=["TenantScopedModel"])
    assert not issubclass(Program, tenancy_models.TenantScopedModel)
    assert not issubclass(ApplicationPrompt, tenancy_models.TenantScopedModel)
