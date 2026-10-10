import pytest

from apps.documents.constraints import ConstraintRule, Enforcement
from apps.documents.overrides import OverrideRefused, record_override, resolve_violations
from apps.documents.render import ConstraintViolation
from apps.funding.models import ConstraintOverride
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _rule(enforcement, rule_id="R-032"):
    return ConstraintRule(
        rule_id=rule_id,
        key="photo_allowed",
        value=False,
        enforcement=enforcement,
        rule_text="US admissions offices commonly discard CVs containing photographs",
        source_url="https://example.org/r-032",
    )


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def test_advisory_style_dropped_silently(agency_a, django_user_model, program_factory):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "o1")
        violation = ConstraintViolation(_rule(Enforcement.ADVISORY_STYLE), "detail")
        assert resolve_violations((violation,), student=student, programme=program_factory()) == ()


def test_advisory_high_risk_survives_until_overridden(
    agency_a, django_user_model, program_factory
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "o2")
        program = program_factory()
        violation = ConstraintViolation(_rule(Enforcement.ADVISORY_HIGH_RISK), "detail")
        assert resolve_violations((violation,), student=student, programme=program) == (violation,)
        record_override(
            student=student, programme=program, violation=violation, decided_by=student
        )
        assert resolve_violations((violation,), student=student, programme=program) == ()


def test_binding_violation_is_never_droppable(agency_a, django_user_model, program_factory):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "o3")
        program = program_factory()
        violation = ConstraintViolation(_rule(Enforcement.BINDING), "detail")
        with pytest.raises(OverrideRefused):
            record_override(
                student=student, programme=program, violation=violation, decided_by=student
            )
        assert resolve_violations((violation,), student=student, programme=program) == (violation,)


def test_override_records_risk_text_verbatim(agency_a, django_user_model, program_factory):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "o4")
        violation = ConstraintViolation(_rule(Enforcement.ADVISORY_HIGH_RISK), "detail")
        override = record_override(
            student=student, programme=program_factory(), violation=violation, decided_by=student
        )
        assert override.risk_text_shown == violation.rule.rule_text


def test_a_counselor_cannot_accept_a_risk_for_the_student(
    agency_a, django_user_model, program_factory
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "o5")
        counselor_user = django_user_model.objects.create(username="o5c")
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR, active=True
        )
        violation = ConstraintViolation(_rule(Enforcement.ADVISORY_HIGH_RISK), "detail")
        with pytest.raises(OverrideRefused):
            record_override(
                student=student,
                programme=program_factory(),
                violation=violation,
                decided_by=counselor,
            )


def test_recording_twice_replaces_rather_than_duplicates(
    agency_a, django_user_model, program_factory
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "o6")
        program = program_factory()
        first = record_override(
            student=student,
            programme=program,
            violation=ConstraintViolation(_rule(Enforcement.ADVISORY_HIGH_RISK), "d1"),
            decided_by=student,
        )
        second = record_override(
            student=student,
            programme=program,
            violation=ConstraintViolation(_rule(Enforcement.ADVISORY_HIGH_RISK), "d2"),
            decided_by=student,
        )
        assert first.id == second.id
        assert (
            ConstraintOverride.objects.filter(
                student=student, programme=program, rule_id="R-032"
            ).count()
            == 1
        )


def test_override_never_travels_to_a_different_programme(
    agency_a, django_user_model, program_factory
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "o7")
        program_us = program_factory(country_code="US", location_key="us:boston")
        program_de = program_factory(country_code="DE", location_key="de:berlin")
        violation = ConstraintViolation(_rule(Enforcement.ADVISORY_HIGH_RISK), "detail")
        record_override(
            student=student, programme=program_us, violation=violation, decided_by=student
        )
        assert resolve_violations((violation,), student=student, programme=program_de) == (
            violation,
        )


def test_override_never_travels_to_a_different_rule(
    agency_a, django_user_model, program_factory
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "o8")
        program = program_factory()
        record_override(
            student=student,
            programme=program,
            violation=ConstraintViolation(_rule(Enforcement.ADVISORY_HIGH_RISK, "R-032"), "d"),
            decided_by=student,
        )
        other = ConstraintViolation(_rule(Enforcement.ADVISORY_HIGH_RISK, "R-041"), "d")
        assert resolve_violations((other,), student=student, programme=program) == (other,)
