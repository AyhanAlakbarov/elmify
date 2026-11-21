"""The two relevance tables behind a NOBYPASSRLS role (CLAUDE.md: the test
superuser bypasses RLS, so only rls_enforced_orm proves anything)."""

from uuid import uuid4

import pytest

from apps.documents.models import CVItemChoice, CVRelevanceAnswer
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def rows_a(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username=f"rel-{uuid4().hex[:8]}")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        answer = CVRelevanceAnswer.objects.create(
            student=student, requirements_digest="r" * 64, item_digest="i" * 64,
            question_version="cv-relevance-1", answer="unrelated", chance=0.95,
            unrelated=0.95, model="typesafe/jev-1.13",
        )
        choice = CVItemChoice.objects.create(
            student=student, program_id=uuid4(), section="awards", item_digest="i" * 64,
        )
    return answer, choice


def test_another_tenant_sees_neither_table(rows_a, agency_b, rls_enforced_orm):
    answer, choice = rows_a
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert not CVRelevanceAnswer._base_manager.filter(id=answer.id).exists()
        assert not CVItemChoice._base_manager.filter(id=choice.id).exists()
        assert CVItemChoice._base_manager.filter(id=choice.id).update(section="skills") == 0


def test_the_owning_tenant_reads_its_rows(rows_a, rls_enforced_orm):
    answer, choice = rows_a
    with tenant_scope(answer.tenant_id), tenant_transaction(answer.tenant_id):
        assert CVRelevanceAnswer.objects.filter(id=answer.id).exists()
        assert CVItemChoice.objects.filter(id=choice.id).exists()
