from datetime import date
from decimal import Decimal
from typing import get_args
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.accounts.schemas import (
    AcademicRecord,
    Money,
    ProfileConstraint,
    StudentProfileSnapshot,
)
from apps.funding.evaluation import (
    ApplicantConditionFact,
    ApplicantConditionType,
    BenefitFact,
    CandidateFacts,
    CostLineItem,
    ReturnServiceFact,
)
from apps.funding.fx import RateTable
from apps.funding.models import (
    EvidenceClaim,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Agency, Membership

EUR_RATES = RateTable(
    base="EUR",
    rates={
        "EUR": Decimal("1"),
        "USD": Decimal("1.0850"),
        "INR": Decimal("94.5000"),
        "AZN": Decimal("1.8450"),
    },
    source="TEST",
    retrieved_on=date(2026, 8, 14),
)

_BASE_DIMENSION_SCORES = {
    "ACADEMIC_FIT": Decimal("90"),
    "PROGRAM_FIT": Decimal("90"),
    "CAREER_FIT": Decimal("90"),
    "DURATION": Decimal("90"),
    "MOBILITY_FIT": Decimal("90"),
    "RESEARCH_FIT": Decimal("90"),
}

_BASE_WEIGHTS = {
    "ACADEMIC_FIT": Decimal("0.2"),
    "PROGRAM_FIT": Decimal("0.2"),
    "CAREER_FIT": Decimal("0.1"),
    "AFFORDABILITY": Decimal("0.2"),
    "DURATION": Decimal("0.1"),
    "MOBILITY_FIT": Decimal("0.1"),
    "RESEARCH_FIT": Decimal("0.1"),
}


def make_profile(**overrides: object) -> StudentProfileSnapshot:
    payload: dict[str, object] = {
        "academic_history": (
            AcademicRecord(
                institution="Example University",
                country_code="US",
                qualification="Bachelor of Science",
                field="Computer Science",
                grade="3.8",
                grading_scale="4.0 GPA",
                completed_on=date(2025, 6, 1),
            ),
        ),
        "target_field": "Computer Science",
        "nationality": "AZ",
        "country_of_residence": "AZ",
        "intended_intake": date(2027, 9, 1),
        "acceptable_teaching_languages": ("English",),
        "language_evidence": (),
        "experience": (),
        "research_interests": (),
        "career_intent": "WORK_ABROAD",
        "date_of_birth": date(2000, 1, 1),
        "self_funding_capacity": Money(amount=Decimal("10000"), currency="EUR"),
        "application_budget": Money(amount=Decimal("500.00"), currency="USD"),
        "funding_dependency": "OPTIONAL",
        "strategy": "BALANCED",
        "duration_preference": "NONE",
        "duration_flexibility": "NOT_APPLICABLE",
        "longer_program_justifications": (),
        "allowed_countries": (),
        "excluded_countries": (),
        "mobility_priorities": (),
        "non_negotiables": (),
        "negotiable_preferences": (),
        "weights": dict(_BASE_WEIGHTS),
    }
    payload.update(overrides)
    return StudentProfileSnapshot.model_validate(payload)


def make_candidate(**overrides: object) -> CandidateFacts:
    payload: dict[str, object] = {
        "program_id": "program-1",
        "institution_id": "institution-1",
        "program_country_code": "DE",
        "excluded_nationalities": (),
        "location_key": "DE-BERLIN",
        "city": "Berlin",
        "field_of_study": "Computer Science",
        "teaching_languages": ("English",),
        "duration_months": 12,
        "language_evidence_required": False,
        "language_evidence_deadline": None,
        "application_deadline": date(2027, 1, 15),
        "scholarship_decision_deadline": None,
        "deadline_is_viable": True,
        "confirmed_eligibility_failure": False,
        "evidence_confidence": "HIGH",
        "cost_components": (
            CostLineItem(kind="TUITION", amount=Decimal("0.00"), currency="EUR", period="ANNUAL"),
        ),
        "benefits": (),
        "dimension_scores": dict(_BASE_DIMENSION_SCORES),
    }
    payload.update(overrides)
    return CandidateFacts.model_validate(payload)


def make_constraint(kind: str, value: str) -> ProfileConstraint:
    return ProfileConstraint(kind=kind, value=value)


def make_cost(
    kind: str, amount: str, currency: str = "EUR", period: str = "ANNUAL"
) -> CostLineItem:
    return CostLineItem(kind=kind, amount=Decimal(amount), currency=currency, period=period)


def make_benefit(
    kind: str = "STIPEND",
    *,
    id: str = "benefit-1",
    amount: str | None = "1000.00",
    currency: str | None = "EUR",
    period: str = "ANNUAL",
    scope_type: str = "GLOBAL",
    country_code: str | None = None,
    nationality_code: str | None = None,
    location_key: str | None = None,
    program_id: str | None = None,
    accessibility: str = "ORDINARY",
    eligibility_confidence: str = "VERIFIED",
    is_current: bool = True,
    repayable_share: str = "0",
) -> BenefitFact:
    return BenefitFact(
        id=id,
        kind=kind,
        amount=Decimal(amount) if amount is not None else None,
        currency=currency,
        period=period,
        scope_type=scope_type,
        country_code=country_code,
        nationality_code=nationality_code,
        location_key=location_key,
        program_id=program_id,
        accessibility=accessibility,
        eligibility_confidence=eligibility_confidence,
        is_current=is_current,
        repayable_share=Decimal(repayable_share),
    )


#: The six pre-vocabulary types ApplicantConditionFact.condition_type still accepts.
_LEGACY_CONDITION_TYPES = get_args(ApplicantConditionType)


def make_applicant_condition(
    condition_type: str = "WORK_EXPERIENCE",
    *,
    benefit_id: str = "benefit-1",
    comparable_value: str | None = "24",
    comparable_unit: str | None = None,
    rule_text: str = "at least two years of professional work experience",
    operator: str = "",
    value: str = "",
) -> ApplicantConditionFact:
    # `condition_type` doubles as the caller's shorthand for the shared vocabulary's
    # `key` (apps.funding.eligibility.Key, e.g. "CITIZENSHIP"). ApplicantConditionFact's
    # own condition_type field is still restricted to the six legacy values, so a
    # non-legacy value goes in `key` instead and condition_type keeps a harmless
    # default -- it is a deprecated alias once `key` is set.
    # `operator` defaults to "" (mirroring the field default), not "GTE": a
    # legacy call must leave it empty so _as_triple's fallback to _LEGACY_KEYS's
    # per-type operator actually fires (AGE_CAP -> LTE) -- pinning it to "GTE"
    # here would silently mask that for every test built through this helper.
    is_legacy = condition_type in _LEGACY_CONDITION_TYPES
    return ApplicantConditionFact(
        benefit_id=benefit_id,
        condition_type=condition_type if is_legacy else "WORK_EXPERIENCE",
        key="" if is_legacy else condition_type,
        comparable_value=Decimal(comparable_value) if comparable_value is not None else None,
        comparable_unit=comparable_unit,
        rule_text=rule_text,
        operator=operator,
        value=value,
    )


def make_return_service(
    *,
    benefit_id: str = "benefit-1",
    months: int = 24,
    rule_text: str = "return home for at least two years after the programme",
) -> ReturnServiceFact:
    return ReturnServiceFact(benefit_id=benefit_id, months=months, rule_text=rule_text)


@pytest.fixture
def profile() -> StudentProfileSnapshot:
    return make_profile()


def make_run(agency: Agency, student: Membership) -> RecommendationRun:
    with tenant_scope(agency.id):
        next_version = StudentProfileVersion.objects.filter(student=student).count() + 1
        profile_version = StudentProfileVersion.objects.create(
            student=student, version=next_version, snapshot={}
        )
        return RecommendationRun.objects.create(profile_version=profile_version)


def make_db_candidate(
    agency: Agency,
    run: RecommendationRun,
    *,
    program_name: str = "MSc Chemistry",
    funding_gap: str = "0.00",
    currency: str = "EUR",
    eligible: bool = True,
    state: str = RecommendationCandidate.State.VISIBLE,
    evidence_confidence: str = "MEDIUM",
) -> RecommendationCandidate:
    with tenant_scope(agency.id):
        evidence = EvidenceClaim.objects.create(
            source_url=f"https://official.example.test/{uuid4()}",
            claim="Official source confirms funding.",
            last_checked_at=timezone.now(),
        )
        return RecommendationCandidate.objects.create(
            run=run,
            evidence=evidence,
            program_name=program_name,
            funding_gap=Decimal(funding_gap),
            evidence_confidence=evidence_confidence,
            currency=currency,
            eligible=eligible,
            state=state,
        )


def make_published_pack(
    agency: Agency, run: RecommendationRun, candidates: tuple[RecommendationCandidate, ...]
) -> PackVersion:
    with tenant_scope(agency.id):
        pack = PackVersion.objects.create(run=run, version=1, published_at=timezone.now())
        for candidate in candidates:
            PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        RecommendationRun.objects.filter(id=run.id).update(state=RecommendationRun.State.PUBLISHED)
        return pack


# institution_factory / program_factory moved to tests/conftest.py: Institution
# and Program are shared-catalog models, not funding-app-internal scaffolding,
# and other test directories (tests/documents) need them too.
