import warnings
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal

import pytest
from django.db import close_old_connections
from pydantic import ValidationError

from apps.accounts.models import StudentProfileVersion
from apps.accounts.schemas import MinimalProfile
from apps.funding.models import RecommendationRun
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.acceptance.helpers import complete_consultation, confirm_consultation


def _contracts():
    from apps.accounts.profile_versions import (
        ProfileVersionRejected,
        create_profile_version,
    )
    from apps.accounts.schemas import StudentProfileSnapshot

    return ProfileVersionRejected, StudentProfileSnapshot, create_profile_version


def test_weights_reject_location_and_accept_mobility_fit(
    valid_phase1_profile_payload,
) -> None:
    _, schema, _ = _contracts()

    payload = deepcopy(valid_phase1_profile_payload)
    payload["weights"] = {
        "ACADEMIC_FIT": Decimal("0.20"),
        "PROGRAM_FIT": Decimal("0.20"),
        "CAREER_FIT": Decimal("0.10"),
        "AFFORDABILITY": Decimal("0.20"),
        "DURATION": Decimal("0.10"),
        "LOCATION": Decimal("0.10"),
        "RESEARCH_FIT": Decimal("0.10"),
    }
    with pytest.raises(ValidationError):
        schema.model_validate(payload)

    payload["weights"]["MOBILITY_FIT"] = payload["weights"].pop("LOCATION")
    validated = schema.model_validate(payload)
    assert set(validated.weights) == {
        "ACADEMIC_FIT",
        "PROGRAM_FIT",
        "CAREER_FIT",
        "AFFORDABILITY",
        "DURATION",
        "MOBILITY_FIT",
        "RESEARCH_FIT",
    }


@pytest.fixture
def valid_phase1_profile_payload() -> dict[str, object]:
    return {
        "schema_version": 3,
        "academic_history": [
            {
                "institution": "Baku State University",
                "country_code": "AZ",
                "qualification": "BSc",
                "field": "Chemistry",
                "grade": "90",
                "grading_scale": "100",
                "completed_on": "2026-06-30",
            }
        ],
        "target_field": "Chemistry",
        "nationality": "AZ",
        "country_of_residence": "AZ",
        "intended_intake": "2027-09-01",
        "acceptable_teaching_languages": ["English"],
        "language_evidence": [
            {
                "language": "English",
                "level": "C1",
                "evidence_type": "TEST",
                "available_by": "2027-01-15",
            }
        ],
        "experience": [{"kind": "RESEARCH", "summary": "Catalysis research", "months": 12}],
        "research_interests": ["Catalysis"],
        "career_intent": "PHD",
        "date_of_birth": "2000-01-01",
        "application_budget": {"amount": "150.00", "currency": "EUR"},
        "funding_dependency": "MANDATORY",
        "strategy": "FUNDING_FIRST",
        "duration_preference": "ONE_YEAR",
        "duration_flexibility": "NON_NEGOTIABLE",
        "longer_program_justifications": [],
        "allowed_countries": ["DE", "FR"],
        "excluded_countries": ["US"],
        "mobility_priorities": ["Public transport"],
        "non_negotiables": [{"kind": "LANGUAGE", "value": "English"}],
        "negotiable_preferences": [{"kind": "LOCATION", "value": "Urban"}],
        "weights": {
            "ACADEMIC_FIT": "0.20",
            "PROGRAM_FIT": "0.20",
            "CAREER_FIT": "0.10",
            "AFFORDABILITY": "0.20",
            "DURATION": "0.10",
            "MOBILITY_FIT": "0.10",
            "RESEARCH_FIT": "0.10",
        },
    }


def test_profile_snapshot_requires_nationality_and_residence() -> None:
    from pydantic import ValidationError

    from tests.funding.conftest import make_profile

    profile = make_profile(nationality="AZ", country_of_residence="AZ")

    assert profile.schema_version == 3
    assert profile.nationality == "AZ"
    assert profile.country_of_residence == "AZ"

    with pytest.raises(ValidationError):
        make_profile(nationality="ZZ")


def test_profile_nationality_and_residence_may_differ() -> None:
    from tests.funding.conftest import make_profile

    profile = make_profile(nationality="AZ", country_of_residence="TR")

    assert profile.nationality == "AZ"
    assert profile.country_of_residence == "TR"


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": True},
        {"allowed_countries": ["ZZ"]},
        {"acceptable_teaching_languages": [" "]},
        {"acceptable_teaching_languages": ["x" * 101]},
        {"research_interests": [" "]},
        {"research_interests": ["x" * 201]},
        {"mobility_priorities": [" "]},
        {"mobility_priorities": ["x" * 201]},
        {"application_budget": {"amount": "1", "currency": "ZZZ"}},
        {"application_budget": {"amount": "-0.01", "currency": "EUR"}},
        {
            "language_evidence": [
                {
                    "language": "French",
                    "level": "C1",
                    "evidence_type": "TEST",
                    "available_by": "2027-01-15",
                }
            ]
        },
        {
            "weights": {
                "ACADEMIC_FIT": Decimal("1.1"),
                "PROGRAM_FIT": Decimal("-0.1"),
            }
        },
        {"weights": {"ACADEMIC_FIT": Decimal("0.9")}},
        {
            "weights": {
                "ACADEMIC_FIT": Decimal("0.5"),
                "ELIGIBILITY": Decimal("0.5"),
            }
        },
    ],
)
def test_profile_schema_rejects_invalid_boundary_values(
    valid_phase1_profile_payload, change
) -> None:
    _, schema, _ = _contracts()
    payload = deepcopy(valid_phase1_profile_payload)
    payload.update(change)
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


@pytest.mark.parametrize(
    ("preference", "flexibility", "justifications"),
    [
        ("ONE_YEAR", "NON_NEGOTIABLE", []),
        ("ONE_YEAR", "WEIGHTED", ["FUNDING"]),
        ("TWO_YEAR", "NON_NEGOTIABLE", []),
        ("TWO_YEAR", "WEIGHTED", []),
        ("NONE", "NOT_APPLICABLE", []),
    ],
)
def test_profile_accepts_every_duration_branch(
    valid_phase1_profile_payload, preference, flexibility, justifications
) -> None:
    _, schema, _ = _contracts()
    payload = deepcopy(valid_phase1_profile_payload)
    payload.update(
        duration_preference=preference,
        duration_flexibility=flexibility,
        longer_program_justifications=justifications,
    )
    assert schema.model_validate(payload).duration_preference == preference


@pytest.mark.parametrize(
    ("preference", "flexibility", "justifications"),
    [
        ("NONE", "WEIGHTED", []),
        ("NONE", "NON_NEGOTIABLE", []),
        ("NONE", "NOT_APPLICABLE", ["FUNDING"]),
        ("ONE_YEAR", "NOT_APPLICABLE", []),
        ("TWO_YEAR", "NOT_APPLICABLE", []),
        ("ONE_YEAR", "WEIGHTED", []),
        ("ONE_YEAR", "NON_NEGOTIABLE", ["FUNDING"]),
        ("TWO_YEAR", "NON_NEGOTIABLE", ["RESEARCH"]),
        ("TWO_YEAR", "WEIGHTED", ["INTERNSHIP"]),
    ],
)
def test_profile_rejects_invalid_duration_combinations(
    valid_phase1_profile_payload, preference, flexibility, justifications
) -> None:
    _, schema, _ = _contracts()
    payload = deepcopy(valid_phase1_profile_payload)
    payload.update(
        duration_preference=preference,
        duration_flexibility=flexibility,
        longer_program_justifications=justifications,
    )
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["acceptable_teaching_languages"].append(" english "),
        lambda p: p["research_interests"].append(" CATALYSIS "),
        lambda p: p["mobility_priorities"].append(" public TRANSPORT "),
        lambda p: p["academic_history"].append(
            {
                **deepcopy(p["academic_history"][0]),
                "institution": " baku state university ",
                "field": "CHEMISTRY",
            }
        ),
        lambda p: p["language_evidence"].append(
            {
                **deepcopy(p["language_evidence"][0]),
                "language": " english ",
                "level": " c1 ",
            }
        ),
        lambda p: p["experience"].append(
            {
                **deepcopy(p["experience"][0]),
                "summary": " CATALYSIS RESEARCH ",
            }
        ),
        lambda p: p["non_negotiables"].append({"kind": "LANGUAGE", "value": " english "}),
    ],
)
def test_profile_rejects_every_canonical_duplicate_key(
    valid_phase1_profile_payload, mutate
) -> None:
    _, schema, _ = _contracts()
    payload = deepcopy(valid_phase1_profile_payload)
    mutate(payload)
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_profile_canonicalizes_and_rejects_duplicate_justification_enum(
    valid_phase1_profile_payload,
) -> None:
    _, schema, _ = _contracts()
    payload = deepcopy(valid_phase1_profile_payload)
    payload.update(
        duration_flexibility="WEIGHTED",
        longer_program_justifications=[" FUNDING "],
    )
    validated = schema.model_validate(payload)
    assert validated.longer_program_justifications == ("FUNDING",)
    payload["longer_program_justifications"] = ["FUNDING", " FUNDING "]
    with pytest.raises(ValidationError, match="duplicate"):
        schema.model_validate(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_countries": ["DE"], "excluded_countries": [" DE "]},
        {
            "non_negotiables": [{"kind": "LANGUAGE", "value": "English"}],
            "negotiable_preferences": [{"kind": "LANGUAGE", "value": " english "}],
        },
    ],
)
def test_profile_rejects_overlap_using_duplicate_keys(valid_phase1_profile_payload, change) -> None:
    _, schema, _ = _contracts()
    payload = deepcopy(valid_phase1_profile_payload)
    payload.update(change)
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_profile_strips_top_level_and_nested_strings(
    valid_phase1_profile_payload,
) -> None:
    _, schema, _ = _contracts()
    payload = deepcopy(valid_phase1_profile_payload)
    payload["target_field"] = "  Chemistry  "
    payload["academic_history"][0]["institution"] = "  Baku State University  "
    payload["language_evidence"][0]["level"] = " C1 "
    profile = schema.model_validate(payload)
    assert profile.target_field == "Chemistry"
    assert profile.academic_history[0].institution == "Baku State University"
    assert profile.language_evidence[0].level == "C1"


def test_minimal_profile_strips_strings() -> None:
    profile = MinimalProfile.model_validate(
        {
            "target_field": " Chemistry ",
            "intended_intake": "2027-09-01",
            "acceptable_teaching_languages": [" English "],
            "funding_dependency": "MANDATORY",
            "strategy": "FUNDING_FIRST",
            "application_budget": "100",
        }
    )
    assert profile.target_field == "Chemistry"
    assert profile.acceptable_teaching_languages == ("English",)


@pytest.mark.django_db(transaction=True)
def test_profile_versions_are_allocated_atomically_from_stale_instances(
    agency_a, membership_a, valid_phase1_profile_payload
) -> None:
    _, schema, create = _contracts()
    snapshot = schema.model_validate(valid_phase1_profile_payload)

    def allocate() -> int:
        close_old_connections()
        try:
            with tenant_scope(agency_a.id):
                return create(student=membership_a, snapshot=snapshot).version
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: allocate(), range(2))) == [1, 2]


@pytest.mark.django_db
def test_existing_run_keeps_exact_profile_version(
    agency_a, membership_a, valid_phase1_profile_payload
) -> None:
    _, schema, create = _contracts()
    snapshot = schema.model_validate(valid_phase1_profile_payload)
    with tenant_scope(agency_a.id):
        first = create(student=membership_a, snapshot=snapshot)
        run = RecommendationRun.objects.create(profile_version=first)
        changed = deepcopy(valid_phase1_profile_payload)
        changed["target_field"] = "Materials Science"
        second = create(student=membership_a, snapshot=schema.model_validate(changed))
        run.refresh_from_db()
    assert second.version == first.version + 1
    assert run.profile_version_id == first.id


@pytest.mark.django_db
def test_service_revalidates_constructed_and_mutated_snapshot(
    agency_a, membership_a, valid_phase1_profile_payload
) -> None:
    rejected, schema, create = _contracts()
    payload = deepcopy(valid_phase1_profile_payload)
    unsafe = schema.model_construct(**payload)
    unsafe.academic_history.append({})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with tenant_scope(agency_a.id), pytest.raises(rejected, match="invalid profile"):
            create(student=membership_a, snapshot=unsafe)
    with tenant_scope(agency_a.id):
        assert StudentProfileVersion.objects.count() == 0
        assert RecommendationRun.objects.count() == 0


@pytest.mark.django_db
def test_service_rejects_unserializable_constructed_snapshot_without_writes(
    agency_a, membership_a, valid_phase1_profile_payload
) -> None:
    rejected, schema, create = _contracts()
    unsafe = schema.model_construct(**{**valid_phase1_profile_payload, "weights": object()})

    with tenant_scope(agency_a.id), pytest.raises(rejected, match="invalid profile"):
        create(student=membership_a, snapshot=unsafe)

    with tenant_scope(agency_a.id):
        assert StudentProfileVersion.objects.count() == 0
        assert RecommendationRun.objects.count() == 0


def test_profile_weights_are_immutable_and_round_trip_as_an_object(
    valid_phase1_profile_payload,
) -> None:
    _, schema, _ = _contracts()
    profile = schema.model_validate(valid_phase1_profile_payload)

    with pytest.raises(TypeError):
        profile.weights["ACADEMIC_FIT"] = Decimal("0")

    dumped = profile.model_dump(mode="json")
    assert dumped["weights"] == valid_phase1_profile_payload["weights"]
    assert schema.model_validate(dumped) == profile


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("change", [{"active": False}, {"role": Membership.Role.COUNSELOR}])
def test_service_reloads_membership_before_authorizing(
    agency_a, membership_a, valid_phase1_profile_payload, change
) -> None:
    rejected, schema, create = _contracts()
    stale = Membership._base_manager.get(id=membership_a.id)

    def change_membership_in_separate_transaction() -> None:
        close_old_connections()
        try:
            Membership._base_manager.filter(id=membership_a.id).update(**change)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(change_membership_in_separate_transaction).result()
    with tenant_scope(agency_a.id):
        with pytest.raises(rejected, match="active student"):
            create(
                student=stale,
                snapshot=schema.model_validate(valid_phase1_profile_payload),
            )


@pytest.mark.django_db
def test_service_normalizes_all_subject_boundary_failures(
    agency_a,
    agency_b,
    membership_a,
    membership_b,
    counselor_membership,
    valid_phase1_profile_payload,
) -> None:
    rejected, schema, create = _contracts()
    snapshot = schema.model_validate(valid_phase1_profile_payload)
    with tenant_scope(agency_a.id):
        for student in (membership_b, counselor_membership):
            with pytest.raises(rejected):
                create(student=student, snapshot=snapshot)
    with pytest.raises(rejected):
        create(student=membership_a, snapshot=snapshot)


@pytest.mark.django_db
def test_service_normalizes_deleted_subject_failure(
    agency_a, membership_a, valid_phase1_profile_payload
) -> None:
    rejected, schema, create = _contracts()
    stale = membership_a
    Membership._base_manager.filter(id=stale.id).delete()
    with tenant_scope(agency_a.id), pytest.raises(rejected):
        create(student=stale, snapshot=schema.model_validate(valid_phase1_profile_payload))


@pytest.mark.django_db(transaction=True)
def test_profile_post_cannot_redirect_subject(
    client,
    domain_a,
    user_a,
    agency_a,
    agency_b,
    membership_a,
    membership_b,
    monkeypatch,
    paid_cycle_a,
) -> None:
    monkeypatch.setattr("apps.accounts.views.dispatch_recommendation_run", lambda **_kwargs: False)
    client.force_login(user_a)
    complete_consultation(client, host=domain_a.host)
    response = client.post(
        "/student/profile/",
        {"action": "confirm", "student_id": str(membership_b.id)},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert StudentProfileVersion.objects.get().student_id == membership_a.id
    with tenant_scope(agency_b.id):
        assert StudentProfileVersion.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_profile_post_returns_controlled_400_when_version_is_rejected(
    client,
    domain_a,
    user_a,
    agency_a,
    membership_a,
    monkeypatch,
    paid_cycle_a,
) -> None:
    rejected, _, _ = _contracts()

    def reject(**_kwargs) -> None:
        raise rejected("profile subject unavailable")

    monkeypatch.setattr("apps.accounts.consultation.create_profile_version", reject)
    client.force_login(user_a)
    complete_consultation(client, host=domain_a.host)
    response = confirm_consultation(client, host=domain_a.host)

    assert response.status_code == 400
    with tenant_scope(agency_a.id):
        assert RecommendationRun.objects.count() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("membership_change", "method", "expected_status"),
    [
        ({"role": Membership.Role.COUNSELOR}, "get", 403),
        ({"role": Membership.Role.COUNSELOR}, "post", 403),
        ({"active": False}, "get", 403),
        ({"active": False}, "post", 403),
    ],
)
def test_profile_route_handles_changed_membership_without_writes(
    client,
    domain_a,
    user_a,
    agency_a,
    membership_a,
    membership_change,
    method,
    expected_status,
) -> None:
    Membership._base_manager.filter(id=membership_a.id).update(**membership_change)
    client.force_login(user_a)
    client.raise_request_exception = False

    response = getattr(client, method)(
        "/student/profile/",
        {
            "target_field": "Chemistry",
            "intended_intake": "2027-09-01",
            "acceptable_teaching_languages": "English",
            "funding_dependency": "MANDATORY",
            "strategy": "FUNDING_FIRST",
            "application_budget": "150",
        },
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == expected_status
    with tenant_scope(agency_a.id):
        assert StudentProfileVersion.objects.count() == 0
        assert RecommendationRun.objects.count() == 0
