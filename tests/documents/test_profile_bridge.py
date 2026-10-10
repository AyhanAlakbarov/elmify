import pytest

from apps.accounts.models import StudentProfileVersion
from apps.documents.models import VerifiedFact
from apps.documents.profile_bridge import bridge_profile_to_facts
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _record(institution="Example University", qualification="BSc", grade="1.7"):
    return {
        "institution": institution,
        "country_code": "DE",
        "qualification": qualification,
        "field": "Computer Science",
        "grade": grade,
        "grading_scale": "German 1.0-5.0",
        "completed_on": "2024-06-30",
    }


def _language(language="German", level="C1"):
    return {
        "language": language,
        "level": level,
        "evidence_type": "TEST",
        "available_by": "2026-01-01",
    }


def _snapshot(*, records=None, languages=None):
    return {
        "schema_version": 3,
        "nationality": "DE",
        "country_of_residence": "DE",
        "academic_history": records if records is not None else [_record()],
        "target_field": "Computer Science",
        "intended_intake": "2027-09-01",
        "acceptable_teaching_languages": ["English"],
        "language_evidence": languages if languages is not None else [],
        "experience": [],
        "research_interests": [],
        "career_intent": "PHD",
        "date_of_birth": "2000-01-01",
        "application_budget": {"amount": "10000.00", "currency": "EUR"},
        "funding_dependency": "IMPORTANT",
        "self_funding_capacity": {"amount": "10000", "currency": "EUR"},
        "strategy": "BALANCED",
        "duration_preference": "TWO_YEAR",
        "duration_flexibility": "WEIGHTED",
        "allowed_countries": [],
        "excluded_countries": [],
        "mobility_priorities": [],
        "non_negotiables": [],
        "negotiable_preferences": [],
        "weights": {},
    }


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _profile(student, snapshot, version):
    return StudentProfileVersion.objects.create(
        student=student, version=version, schema_version=3, snapshot=snapshot
    )


def test_bridge_creates_unconfirmed_student_statement_facts(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b1")
        _profile(student, _snapshot(languages=[_language()]), 1)
        facts = bridge_profile_to_facts(student)
        assert len(facts) == 2
        assert all(fact.confirmed_by is None for fact in facts)
        assert all(
            fact.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT for fact in facts
        )
        assert {fact.category for fact in facts} == {
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.LANGUAGE,
        }


def test_bridge_is_idempotent_on_an_unchanged_profile(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b2")
        _profile(student, _snapshot(languages=[_language()]), 1)
        bridge_profile_to_facts(student)
        assert bridge_profile_to_facts(student) == ()
        assert VerifiedFact.objects.filter(student=student).count() == 2


def test_bridge_supersedes_only_the_record_that_changed(agency_a, django_user_model):
    """Two entries, one edited: the other must be left completely alone."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b3")
        first = _record(institution="First University", qualification="BA")
        second = _record(institution="Second University", qualification="BSc")
        _profile(student, _snapshot(records=[first, second]), 1)
        created = bridge_profile_to_facts(student)
        assert len(created) == 2

        edited = {**second, "grade": "1.3"}
        _profile(student, _snapshot(records=[first, edited]), 2)
        second_run = bridge_profile_to_facts(student)

        assert len(second_run) == 1
        assert second_run[0].payload["institution_original"] == "Second University"
        assert second_run[0].supersedes_id == created[1].id
        # the untouched record is still a chain tip
        created[0].refresh_from_db()
        assert not VerifiedFact.objects.filter(supersedes=created[0]).exists()


def test_bridge_supersedes_a_changed_language_entry(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b4")
        _profile(student, _snapshot(languages=[_language(level="B2")]), 1)
        created = bridge_profile_to_facts(student)
        _profile(student, _snapshot(languages=[_language(level="C1")]), 2)
        second_run = bridge_profile_to_facts(student)
        assert len(second_run) == 1
        assert second_run[0].category == VerifiedFact.Category.LANGUAGE
        assert second_run[0].payload["cefr_level"] == "C1"
        language_fact = next(
            fact for fact in created if fact.category == VerifiedFact.Category.LANGUAGE
        )
        assert second_run[0].supersedes_id == language_fact.id


def test_bridge_with_no_profile_is_a_no_op(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b5")
        assert bridge_profile_to_facts(student) == ()


def test_bridged_facts_are_invisible_to_generation(agency_a, django_user_model):
    from apps.documents.verification import generatable_facts

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b6")
        _profile(student, _snapshot(), 1)
        bridge_profile_to_facts(student)
        assert list(generatable_facts(student)) == []
