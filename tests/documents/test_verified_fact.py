import pytest
from django.db import IntegrityError, transaction

from apps.documents.models import VerifiedFact
from apps.tenancy.context import TenantContextMissing, tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def test_verified_fact_created_within_tenant_scope(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "s1")
        fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"institution_original": "TU Berlin", "degree_as_awarded": "MSc"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="transcript-upload-001",
            created_by=student,
        )
        assert fact.supersedes is None
        assert VerifiedFact.objects.filter(student=student).count() == 1


def test_verified_fact_requires_tenant_context(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "s2")
    with pytest.raises(TenantContextMissing):
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.SKILL,
            payload={"skill": "Python"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="consult-002",
            created_by=student,
        )


def test_verified_fact_supersession_chain(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "s3")
        original = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"grade_native": "3.5"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="consult-003",
            created_by=student,
        )
        corrected = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"grade_native": "3.8"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="transcript-upload-004",
            supersedes=original,
            created_by=student,
        )
        assert corrected.supersedes_id == original.id
        # Never updated in place: the original row is untouched.
        original.refresh_from_db()
        assert original.payload == {"grade_native": "3.5"}


def test_cross_tenant_student_rejected_by_save_guard(agency_a, agency_b, django_user_model):
    """TenantScopedModel.save() catches this before the FK is attempted."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "s4")
    with tenant_scope(agency_b.id):
        with pytest.raises(ValueError):
            VerifiedFact.objects.create(
                tenant=agency_a,
                student=student,
                category=VerifiedFact.Category.SKILL,
                payload={"skill": "Rust"},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="consult-005",
                created_by=student,
            )


@pytest.mark.django_db(transaction=True)
def test_cross_tenant_student_rejected_by_composite_fk(agency_a, agency_b, django_user_model):
    """The database refuses it too, even when save()'s guard is bypassed.

    This is the test that proves the composite (tenant_id, student_id) FK from
    0002_tenant_guards is really there: a raw INSERT with agency_b's tenant_id
    and agency_a's student must fail on the constraint, not succeed.
    """
    from uuid import uuid4

    from django.db import connection

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "s5")
    with connection.cursor() as cursor, pytest.raises(IntegrityError), transaction.atomic():
        cursor.execute(
            """
            INSERT INTO documents_verifiedfact
                (id, tenant_id, student_id, category, payload, source_tier,
                 source_ref, created_at, created_by_id)
            VALUES (%s, %s, %s, 'SKILL', '{}'::jsonb, 'STUDENT_STATEMENT', 'x', now(), %s)
            """,
            [uuid4(), agency_b.id, student.id, student.id],
        )


def test_identity_facts_round_trip(agency_a, django_user_model):
    """A name read off a document is a fact like any other -- unconfirmed
    until a human checks it, and invisible to generation until then."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "identity-fact-1")
        fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Leyla Mammadova"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=None,
            created_by=student,
        )
        fact.refresh_from_db()
        assert fact.category == "IDENTITY"
        assert fact.payload == {"full_name": "Leyla Mammadova"}
        assert fact.confirmed_by_id is None


def test_a_referee_fact_can_actually_be_written(agency_a, django_user_model):
    """The category CHECK constraint spells the categories out rather than
    referencing the enum, so adding one to the enum alone leaves every
    uploaded CV with referees failing at the database."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ref1")
        fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.REFERENCE,
            payload={"name": "Prof. Ada Byron", "email": "ada@example.com"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            created_by=student,
        )
    assert fact.category == "REFERENCE"
