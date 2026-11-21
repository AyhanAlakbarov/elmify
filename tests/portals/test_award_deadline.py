"""Award-card deadline resolution from stored cycle verification (CV step 4.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.accounts.schemas import AcademicRecord, Money, StudentProfileSnapshot
from apps.documents import document_worker
from apps.documents.document_queue import DocumentWorkMessage
from apps.funding.models import (
    EvidenceClaim,
    FundingCycleVerification,
    FundingFamily,
    FundingOpportunity,
    OpportunityScope,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.portals.award_deadline import award_deadline
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope

_WEIGHTS = {
    "ACADEMIC_FIT": Decimal("0.5"),
    "AFFORDABILITY": Decimal("0.2"),
    "DURATION": Decimal("0.1"),
    "MOBILITY_FIT": Decimal("0.1"),
    "RESEARCH_FIT": Decimal("0.1"),
}


def _profile_snapshot(*, intake: date, nationality: str, residence: str | None = None) -> dict:
    snap = StudentProfileSnapshot.model_validate(
        {
            "academic_history": (
                AcademicRecord(
                    institution="Example University",
                    country_code="AZ",
                    qualification="Bachelor of Science",
                    field="Computer Science",
                    grade="3.8",
                    grading_scale="4.0 GPA",
                    completed_on=date(2025, 6, 1),
                ),
            ),
            "target_field": "Computer Science",
            "nationality": nationality,
            "country_of_residence": residence or nationality,
            "intended_intake": intake,
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
            "weights": dict(_WEIGHTS),
        }
    )
    return snap.model_dump(mode="json")


def _award() -> FundingOpportunity:
    return FundingOpportunity.objects.create(
        canonical_key=f"funder:{uuid4()}",
        name=f"Award {uuid4().hex[:6]}",
        family=FundingFamily.PRIVATE_FOUNDATION,
        scope_type=OpportunityScope.GLOBAL,
    )


def _award_card(
    agency,
    student,
    *,
    intake: date = date(2027, 9, 1),
    nationality: str = "AZ",
    deadline: datetime | None = None,
) -> Application:
    award = _award()
    with tenant_scope(agency.id):
        next_version = StudentProfileVersion.objects.filter(student=student).count() + 1
        version = StudentProfileVersion.objects.create(
            tenant=agency,
            student=student,
            version=next_version,
            schema_version=3,
            snapshot=_profile_snapshot(intake=intake, nationality=nationality),
        )
        run = RecommendationRun.objects.create(tenant=agency, profile_version=version)
        claim = EvidenceClaim.objects.create(
            tenant=agency,
            source_url="https://daad.example.edu/epos",
            claim="Award claim",
            last_checked_at=timezone.now(),
        )
        candidate = RecommendationCandidate.objects.create(
            tenant=agency,
            run=run,
            evidence=claim,
            opportunity=award,
            program_name=award.name,
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
        )
        return Application.objects.create(
            tenant=agency,
            student=student,
            program_id=award.id,
            candidate=candidate,
            deadline=deadline,
            cv_status=Application.CVStatus.MADE,
        )


def _programme_card(agency, student, program_factory) -> Application:
    programme = program_factory()
    with tenant_scope(agency.id):
        next_version = StudentProfileVersion.objects.filter(student=student).count() + 1
        version = StudentProfileVersion.objects.create(
            tenant=agency,
            student=student,
            version=next_version,
            schema_version=3,
            snapshot=_profile_snapshot(intake=date(2027, 9, 1), nationality="AZ"),
        )
        run = RecommendationRun.objects.create(tenant=agency, profile_version=version)
        claim = EvidenceClaim.objects.create(
            tenant=agency,
            source_url="https://uni.example.edu/msc-cs",
            claim="Programme claim",
            last_checked_at=timezone.now(),
        )
        candidate = RecommendationCandidate.objects.create(
            tenant=agency,
            run=run,
            evidence=claim,
            program=programme,
            program_name=programme.name,
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
        )
        return Application.objects.create(
            tenant=agency,
            student=student,
            program_id=programme.id,
            candidate=candidate,
            cv_status=Application.CVStatus.MADE,
        )


def _cycle_row(
    opportunity: FundingOpportunity, year: int, *, deadlines: list[list[str]]
) -> FundingCycleVerification:
    entry = {
        "step": "0",
        "url": "https://funder.example/award",
        "sha256": "a" * 64,
        "at": "2026-09-20",
        "archived": False,
        "captured_at": "",
        "offered": "YES",
        "applies_to": str(year),
        "intake_year": year,
        "stated_on": "2026-09-01",
        "deadlines": deadlines,
        "quote": "Application deadline stated on official call page.",
        "agreement": "AGREED",
    }
    return FundingCycleVerification.objects.create(
        opportunity=opportunity,
        intake_start_year=year,
        state=FundingCycleVerification.State.OPEN,
        evidence=[entry],
    )


def _run_capture(card: Application) -> None:
    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="capture_requirements",
            kind="KIT",
            tenant_id=card.tenant_id,
            student_id=card.student_id,
            application_id=card.id,
        )
    )


def test_an_award_card_gets_its_intakes_deadline(agency_a, membership_a):
    card = _award_card(agency_a, membership_a, intake=date(2027, 9, 1), nationality="AZ")
    assert card.candidate is not None and card.candidate.opportunity is not None
    _cycle_row(
        card.candidate.opportunity,
        2027,
        deadlines=[["2027-01-15", "15 January 2027", "ALL"]],
    )
    assert award_deadline(card) == datetime(2027, 1, 15, tzinfo=UTC)


def test_a_deadline_for_other_applicants_only_is_not_used(agency_a, membership_a):
    card = _award_card(agency_a, membership_a, intake=date(2027, 9, 1), nationality="AZ")
    assert card.candidate is not None and card.candidate.opportunity is not None
    _cycle_row(
        card.candidate.opportunity,
        2027,
        deadlines=[["2026-11-30", "30 Nov (EU)", "APPLICANT_CLASS:EU"]],
    )
    assert award_deadline(card) is None


def test_no_stored_cycle_row_means_no_deadline(agency_a, membership_a):
    card = _award_card(agency_a, membership_a)
    assert award_deadline(card) is None


def test_a_programme_card_has_no_stored_deadline_yet(agency_a, membership_a, program_factory):
    card = _programme_card(agency_a, membership_a, program_factory)
    assert award_deadline(card) is None


def test_capture_writes_the_deadline_only_when_the_card_has_none(agency_a, membership_a):
    unset_card = _award_card(agency_a, membership_a, deadline=None)
    assert unset_card.candidate is not None and unset_card.candidate.opportunity is not None
    _cycle_row(
        unset_card.candidate.opportunity,
        2027,
        deadlines=[["2027-01-15", "15 January 2027", "ALL"]],
    )
    _run_capture(unset_card)
    with tenant_scope(agency_a.id):
        unset_card.refresh_from_db()
    assert unset_card.deadline == datetime(2027, 1, 15, tzinfo=UTC)

    preset_card = _award_card(
        agency_a, membership_a, deadline=datetime(2027, 2, 1, tzinfo=UTC)
    )
    assert preset_card.candidate is not None and preset_card.candidate.opportunity is not None
    _cycle_row(
        preset_card.candidate.opportunity,
        2027,
        deadlines=[["2027-01-15", "15 January 2027", "ALL"]],
    )
    _run_capture(preset_card)
    with tenant_scope(agency_a.id):
        preset_card.refresh_from_db()
    assert preset_card.deadline == datetime(2027, 2, 1, tzinfo=UTC)
