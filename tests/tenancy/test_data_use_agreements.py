from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.funding.models import RecommendationRun
from apps.tenancy.context import tenant_scope

PURPOSES = {"EVALUATION", "PRODUCT_IMPROVEMENT", "MODEL_TRAINING"}
CATEGORIES = {
    "STRUCTURED_PROFILE_FACTS",
    "RECOMMENDATION_DECISIONS",
    "APPLICATION_OUTCOMES",
    "DOCUMENT_STRUCTURE",
}
REVIEW_STATES = {"NOT_REVIEWED", "APPROVED", "REJECTED"}


def _agreement_model():
    from apps.tenancy.models import AgencyDataUseAgreementVersion

    return AgencyDataUseAgreementVersion


@pytest.fixture
def agreement(agency_a, membership_a):
    model = _agreement_model()
    with tenant_scope(agency_a.id):
        return model.objects.create(
            agreement_id=uuid4(),
            version=1,
            agreement_reference="DPA-2026-001",
            permitted_purposes=["EVALUATION"],
            eligible_categories=["STRUCTURED_PROFILE_FACTS"],
            lawful_basis_review_state="NOT_REVIEWED",
            effective_at=timezone.now(),
            created_by=membership_a,
        )


def _assert_constraint(sql: str, params: list[object], name: str) -> None:
    with pytest.raises(IntegrityError) as caught, transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
    assert caught.value.__cause__.diag.constraint_name == name


def _invalid_agreement_insert(agreement, **overrides) -> tuple[str, list[object]]:
    values = {
        "id": uuid4(),
        "tenant_id": agreement.tenant_id,
        "agreement_id": uuid4(),
        "version": 1,
        "agreement_reference": "invalid-probe",
        "permitted_purposes": '["EVALUATION"]',
        "eligible_categories": '["STRUCTURED_PROFILE_FACTS"]',
        "lawful_basis_review_state": "NOT_REVIEWED",
        "effective_at": agreement.effective_at,
        "revoked_at": None,
        "created_by_id": agreement.created_by_id,
        "created_at": timezone.now(),
    }
    values.update(overrides)
    return (
        """
        INSERT INTO public.tenancy_agencydatauseagreementversion
            (id, tenant_id, agreement_id, version, agreement_reference,
             permitted_purposes, eligible_categories, lawful_basis_review_state,
             effective_at, revoked_at, created_by_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
        """,
        list(values.values()),
    )


@pytest.mark.django_db
def test_agreement_versions_are_unique_per_tenant_and_agreement(
    agency_a, membership_a, agreement
) -> None:
    model = _agreement_model()
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError):
        with transaction.atomic():
            model.objects.create(
                agreement_id=agreement.agreement_id,
                version=1,
                agreement_reference="duplicate",
                permitted_purposes=["EVALUATION"],
                eligible_categories=["STRUCTURED_PROFILE_FACTS"],
                lawful_basis_review_state="APPROVED",
                effective_at=timezone.now(),
                created_by=membership_a,
            )


def test_agreement_choice_contracts_are_exact() -> None:
    model = _agreement_model()
    assert set(model.ReviewState.values) == REVIEW_STATES
    assert {
        value for value, _label in model._meta.get_field("lawful_basis_review_state").choices
    } == REVIEW_STATES


@pytest.mark.django_db
@pytest.mark.parametrize("review_state", sorted(REVIEW_STATES))
def test_all_agreement_allowlists_round_trip(agency_a, membership_a, review_state) -> None:
    model = _agreement_model()
    with tenant_scope(agency_a.id):
        created = model.objects.create(
            agreement_id=uuid4(),
            version=1,
            agreement_reference=f"all-values-{review_state}",
            permitted_purposes=sorted(PURPOSES),
            eligible_categories=sorted(CATEGORIES),
            lawful_basis_review_state=review_state,
            effective_at=timezone.now(),
            created_by=membership_a,
        )
        stored = model.objects.get(id=created.id)
    assert set(stored.permitted_purposes) == PURPOSES
    assert set(stored.eligible_categories) == CATEGORIES
    assert stored.lawful_basis_review_state == review_state


@pytest.mark.django_db
def test_agreement_rejects_cross_tenant_creator(agency_a, membership_b, agreement) -> None:
    with tenant_scope(agency_a.id):
        sql, params = _invalid_agreement_insert(agreement, created_by_id=membership_b.id)
        _assert_constraint(sql, params, "data_use_agreement_creator_tenant_fk")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("version", 0, "data_use_agreement_version_positive"),
        (
            "lawful_basis_review_state",
            "UNKNOWN",
            "data_use_agreement_review_state_valid",
        ),
        (
            "permitted_purposes",
            "[]",
            "data_use_agreement_purposes_nonempty_array",
        ),
        (
            "permitted_purposes",
            "{}",
            "data_use_agreement_purposes_nonempty_array",
        ),
        (
            "permitted_purposes",
            '["ADVERTISING"]',
            "data_use_agreement_purposes_allowed",
        ),
        (
            "eligible_categories",
            "[]",
            "data_use_agreement_categories_nonempty_array",
        ),
        (
            "eligible_categories",
            "{}",
            "data_use_agreement_categories_nonempty_array",
        ),
        (
            "eligible_categories",
            '["RAW_DOCUMENTS"]',
            "data_use_agreement_categories_allowed",
        ),
    ],
)
def test_agreement_database_constraints(agreement, column, value, constraint) -> None:
    sql, params = _invalid_agreement_insert(agreement, **{column: value})
    _assert_constraint(sql, params, constraint)


@pytest.mark.django_db
def test_agreement_chronology_is_database_enforced(agreement) -> None:
    sql, params = _invalid_agreement_insert(
        agreement, revoked_at=agreement.effective_at - timedelta(seconds=1)
    )
    _assert_constraint(sql, params, "data_use_agreement_chronology")


@pytest.mark.django_db
@pytest.mark.parametrize("statement", ["UPDATE", "DELETE"])
def test_agreement_history_is_append_only_for_table_owner(agency_a, agreement, statement) -> None:
    sql = (
        "UPDATE public.tenancy_agencydatauseagreementversion "
        "SET agreement_reference = 'changed' WHERE id = %s"
        if statement == "UPDATE"
        else "DELETE FROM public.tenancy_agencydatauseagreementversion WHERE id = %s"
    )
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, [agreement.id])
    model = _agreement_model()
    with tenant_scope(agency_a.id):
        assert model.objects.get(id=agreement.id).agreement_reference == "DPA-2026-001"


@pytest.mark.django_db
def test_agreement_metadata_has_no_processing_side_effect(agreement) -> None:
    model = _agreement_model()
    field_names = {field.name for field in model._meta.get_fields()}
    assert not field_names & {"eligible", "processing_enabled", "training_enabled"}
    assert RecommendationRun._base_manager.count() == 0
