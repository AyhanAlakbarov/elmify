from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from pydantic import ValidationError

from apps.documents.constraints import rules_from_program
from apps.funding.models import ConstraintOverride, Program
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def test_program_defaults_to_any_unverified(program_factory):
    program = program_factory()
    assert program.cv_format_requirement == Program.CVFormatRequirement.ANY
    assert program.cv_format_confidence == Program.CVFormatConfidence.UNVERIFIED
    assert program.cv_constraints == []


def test_program_cv_constraints_round_trip_into_rules(program_factory):
    program = program_factory()
    program.cv_constraints = [
        {
            "rule_id": "R-078",
            "key": "max_entries_per_section",
            "value": {"experience": 3},
            "enforcement": "BINDING",
            "rule_text": "ineligible if altered",
            "source_url": "https://example.org",
        }
    ]
    program.save(update_fields=["cv_constraints"])
    program.refresh_from_db()
    rules = rules_from_program(program)
    assert [rule.rule_id for rule in rules] == ["R-078"]


def test_invalid_stored_rule_raises_rather_than_being_skipped(program_factory):
    program = program_factory()
    program.cv_constraints = [{"rule_id": "R-1", "key": "nope"}]
    program.save(update_fields=["cv_constraints"])
    with pytest.raises(ValidationError):
        rules_from_program(program)


def test_rules_from_program_default_empty_list_yields_empty_tuple(program_factory):
    program = program_factory()
    assert rules_from_program(program) == ()


def test_constraint_override_created_and_read_back(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory()
        override = ConstraintOverride.objects.create(
            student=membership_a,
            programme=program,
            rule_id="R-032",
            decided_by=membership_a,
            risk_text_shown="US admissions offices commonly discard CVs with photographs",
        )
    override.refresh_from_db()
    assert override.rule_id == "R-032"
    assert override.tenant_id == agency_a.id
    assert override.programme_id == program.id


def test_duplicate_decision_rejected_by_unique_constraint(agency_a, membership_a, program_factory):
    with tenant_scope(agency_a.id):
        program = program_factory()
        ConstraintOverride.objects.create(
            student=membership_a,
            programme=program,
            rule_id="R-032",
            decided_by=membership_a,
            risk_text_shown="x",
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ConstraintOverride.objects.create(
                student=membership_a,
                programme=program,
                rule_id="R-032",
                decided_by=membership_a,
                risk_text_shown="y",
            )


def test_decision_unique_constraint_scoped_to_full_quadruple(
    agency_a, membership_a, program_factory, django_user_model
):
    """The unique index is on the full (tenant, student, programme, rule_id)
    quadruple, not a narrower prefix of it: a different student, or a
    different programme, for the same rule must not collide."""
    with tenant_scope(agency_a.id):
        program = program_factory()
        other_program = program_factory()
        other_student = _student(agency_a, django_user_model, "other-student")
        ConstraintOverride.objects.create(
            student=membership_a,
            programme=program,
            rule_id="R-032",
            decided_by=membership_a,
            risk_text_shown="x",
        )
        ConstraintOverride.objects.create(
            student=other_student,
            programme=program,
            rule_id="R-032",
            decided_by=membership_a,
            risk_text_shown="x",
        )
        ConstraintOverride.objects.create(
            student=membership_a,
            programme=other_program,
            rule_id="R-032",
            decided_by=membership_a,
            risk_text_shown="x",
        )
        assert ConstraintOverride.objects.count() == 3


@pytest.mark.django_db(transaction=True)
def test_cross_tenant_student_rejected_by_composite_fk(
    agency_a, agency_b, membership_a, program_factory
):
    """The database refuses a raw INSERT linking agency_b's override to
    agency_a's student, even though the ORM save() guard is bypassed."""
    with tenant_scope(agency_a.id):
        program = program_factory()
    with connection.cursor() as cursor, pytest.raises(IntegrityError), transaction.atomic():
        cursor.execute(
            """
            INSERT INTO funding_constraintoverride
                (id, tenant_id, student_id, programme_id, rule_id, decided_by_id,
                 risk_text_shown, created_at)
            VALUES (%s, %s, %s, %s, 'R-032', %s, 'x', now())
            """,
            [uuid4(), agency_b.id, membership_a.id, program.id, membership_a.id],
        )
