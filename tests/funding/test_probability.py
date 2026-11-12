from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.accounts.schemas import (
    AcademicRecord,
    CourseRecord,
    ExperienceRecord,
    StudentProfileSnapshot,
)
from apps.audit.redaction import redact_student
from apps.funding.evaluation import CandidateFacts
from apps.funding.facts import award_facts, program_facts
from apps.funding.models import (
    EvidenceClaim,
    FundingOpportunity,
    Institution,
    OutcomeCalibrationRecord,
    Program,
    ProgramStatement,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.probability import (
    estimate_program_admission_chance,
    estimate_scholarship_chance,
    sync_outcome_calibration_records,
)
from apps.funding.validity import Evidence
from apps.portals.models import Application
from apps.portals.outcome import correct_outcome
from apps.research.models import WinnerCohortProfile
from apps.research.register import record_organisation
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.funding.conftest import make_profile, make_run

pytestmark = pytest.mark.django_db(transaction=True)


def _make_program(
    *, country_code: str = "DE", provision_type: str = "SINGLE", name: str = "MSc CS"
) -> Program:
    inst = None
    provider_text = "Consortium"
    if provision_type == "SINGLE":
        inst = Institution.objects.create(
            canonical_key=f"inst:{uuid4()}",
            name="Test University",
            country_code=country_code,
            official_website="https://uni.example.org",
        )
        provider_text = ""
    return Program.objects.create(
        institution=inst,
        canonical_key=f"prog:{uuid4()}",
        name=name,
        campus_name="Main",
        city="City",
        country_code=country_code,
        location_key=f"{country_code}-CITY",
        degree_level="MASTER",
        provision_type=provision_type,
        provider_text=provider_text,
        teaching_languages=["English"],
        duration_months=24,
    )


def _make_candidate_facts(program: Program) -> CandidateFacts:
    return program_facts(program, costs=(), benefits=(), rules=())


def test_program_base_selectivity_and_coursework_margin() -> None:
    de_program = _make_program(country_code="DE", provision_type="SINGLE", name="MSc Chemistry")
    emjm_program = _make_program(
        country_code="FR",
        provision_type="JOINT",
        name="Erasmus Mundus Joint Master ChEMoinformatics+",
    )
    stmt = ProgramStatement(
        program=de_program,
        kind=ProgramStatement.Kind.COMPETENCY,
        requirement=ProgramStatement.Requirement.REQUIRED,
        label="Subject Credit Requirement",
        text="Applicants must have at least 30 ECTS in Chemistry.",
    )

    strong_profile: StudentProfileSnapshot = make_profile(
        academic_history=(
            AcademicRecord(
                institution="Baku State University",
                country_code="AZ",
                qualification="Bachelor of Science",
                field="Chemistry",
                grade="3.9",
                grading_scale="4.0",
                completed_on=dt.date(2025, 6, 1),
                courses=(
                    CourseRecord(title="Organic Chemistry", ects=Decimal("15")),
                    CourseRecord(title="Physical Chemistry", ects=Decimal("15")),
                    CourseRecord(title="Analytical Chemistry", ects=Decimal("10")),
                ),
            ),
        ),
    )
    borderline_profile: StudentProfileSnapshot = make_profile(
        academic_history=(
            AcademicRecord(
                institution="Baku State University",
                country_code="AZ",
                qualification="Bachelor of Science",
                field="Chemistry",
                grade="2.5",
                grading_scale="4.0",
                completed_on=dt.date(2025, 6, 1),
                courses=(
                    CourseRecord(title="General Chemistry", ects=Decimal("15")),
                    CourseRecord(title="Biotechnology Seminar", ects=Decimal("15")),
                ),
            ),
        ),
    )

    de_facts = _make_candidate_facts(de_program)
    emjm_facts = _make_candidate_facts(emjm_program)

    strong_de = estimate_program_admission_chance(
        de_program, de_facts, strong_profile, statements=(stmt,)
    )
    borderline_de = estimate_program_admission_chance(
        de_program, de_facts, borderline_profile, statements=(stmt,)
    )
    strong_emjm = estimate_program_admission_chance(
        emjm_program, emjm_facts, strong_profile, statements=()
    )

    assert 1 <= strong_de.chance_pct <= 95
    assert 1 <= borderline_de.chance_pct <= 95
    assert strong_de.chance_pct > borderline_de.chance_pct
    assert strong_de.chance_pct > strong_emjm.chance_pct
    assert (
        strong_de.features["coursework_alignment"]
        > borderline_de.features["coursework_alignment"]
    )
    assert strong_de.features["gpa_margin"] > borderline_de.features["gpa_margin"]


def test_winner_cohort_similarity_shifts_probability() -> None:
    program = _make_program(
        country_code="FR",
        provision_type="JOINT",
        name="ChEMoinformatics+",
    )
    facts = _make_candidate_facts(program)
    cohort = WinnerCohortProfile.objects.create(
        program_id=program.id,
        target_kind=WinnerCohortProfile.TargetKind.PROGRAM,
        target_name=program.name,
        holder_name="University of Strasbourg",
        country_code="FR",
        sample_size=20,
        origin_country_counts={"AZ": 6, "IT": 8, "PK": 6},
        prior_degree_fields={"chemistry": 14, "cheminformatics": 6},
        prior_degree_levels={"BACHELOR": 18, "MASTER": 2},
        work_experience_months_p25=6,
        work_experience_months_median=12,
        work_experience_months_p75=24,
        research_signal_rate=Decimal("0.7500"),
    )

    matched_profile = make_profile(
        nationality="AZ",
        academic_history=(
            AcademicRecord(
                institution="Baku State University",
                country_code="AZ",
                qualification="Bachelor of Science",
                field="Chemistry",
                grade="3.8",
                grading_scale="4.0",
                completed_on=dt.date(2025, 6, 1),
            ),
        ),
        experience=(
            ExperienceRecord(kind="RESEARCH", summary="Published QSAR paper in journal", months=14),
        ),
    )
    mismatched_profile = make_profile(
        nationality="BR",
        academic_history=(
            AcademicRecord(
                institution="USP",
                country_code="BR",
                qualification="Bachelor of Arts",
                field="History",
                grade="2.9",
                grading_scale="4.0",
                completed_on=dt.date(2025, 6, 1),
            ),
        ),
        experience=(),
    )

    est_matched = estimate_program_admission_chance(
        program, facts, matched_profile, winner_cohort=cohort
    )
    est_mismatched = estimate_program_admission_chance(
        program, facts, mismatched_profile, winner_cohort=cohort
    )

    assert est_matched.features["winner_similarity"] > est_mismatched.features["winner_similarity"]
    assert est_matched.chance_pct > est_mismatched.chance_pct


def test_automatic_on_admission_award_and_competitive_clamping() -> None:
    org = record_organisation(
        domain="daad.de",
        name="DAAD",
        kind="NATIONAL_GOVERNMENT",
        country_code="DE",
        found_via="REGISTER",
    )
    competitive_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}",
        name="DAAD Scholarship",
        holder="NATIONAL_GOVERNMENT",
        holder_domain="daad.de",
        holder_name="DAAD",
        family="GOVERNMENT_SCHOLARSHIP",
        organisation=org,
        scope_type="HOLDER",
        route="SEPARATE_APPLICATION",
        money_form="GRANT",
        tuition="NONE",
        living="FULL",
        agreement="AGREED",
        served=True,
    )
    auto_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}",
        name="Automatic Merit Waiver",
        holder="PRIVATE_FOUNDATION",
        holder_domain="daad.de",
        holder_name="DAAD",
        family="TUITION_WAIVER",
        organisation=org,
        scope_type="HOLDER",
        route="AUTOMATIC_ON_ADMISSION",
        money_form="FEE_WAIVER",
        tuition="FULL",
        living="NONE",
        agreement="AGREED",
        served=True,
    )

    profile = make_profile()
    comp_facts = award_facts(
        competitive_opp,
        benefits=(),
        rules=(),
        country_code="DE",
        evidence=Evidence(offered="YES", applies_to="2027-2028"),
    )
    auto_facts = award_facts(
        auto_opp,
        benefits=(),
        rules=(),
        country_code="DE",
        evidence=Evidence(offered="YES", applies_to="2027-2028"),
    )

    comp_est = estimate_scholarship_chance(competitive_opp, comp_facts, profile)
    auto_est = estimate_scholarship_chance(auto_opp, auto_facts, profile)

    assert 1 <= comp_est.chance_pct <= 95
    assert auto_est.chance_pct == 100


def test_empirical_bayes_and_logistic_calibration_update_from_outcomes() -> None:
    program = _make_program(
        country_code="FR",
        provision_type="JOINT",
        name="Selective Consortium Master",
    )
    facts = _make_candidate_facts(program)
    profile = make_profile()

    cold = estimate_program_admission_chance(program, facts, profile, calibration_rows=())

    eb_rows = [
        OutcomeCalibrationRecord.objects.create(
            application_id=uuid4(),
            program=program,
            country_code="FR",
            route="PROGRAM",
            predicted_chance_pct=cold.chance_pct,
            feature_vector=cold.features,
            won=(i < 18),
        )
        for i in range(20)
    ]
    eb_est = estimate_program_admission_chance(program, facts, profile, calibration_rows=eb_rows)
    assert eb_est.chance_pct > cold.chance_pct

    OutcomeCalibrationRecord.objects.all().delete()
    ml_rows: list[OutcomeCalibrationRecord] = []
    for i in range(60):
        high = i >= 30
        ml_rows.append(
            OutcomeCalibrationRecord.objects.create(
                application_id=uuid4(),
                program=program,
                country_code="FR",
                route="PROGRAM",
                predicted_chance_pct=65 if high else 15,
                feature_vector={
                    "base_prior": 0.30,
                    "gpa_margin": 0.90 if high else -0.60,
                    "coursework_alignment": 1.0 if high else -1.0,
                    "language_margin": 0.50 if high else 0.0,
                    "winner_similarity": 0.80 if high else -0.40,
                },
                won=high,
            )
        )

    strong_profile = make_profile(
        academic_history=(
            AcademicRecord(
                institution="Uni",
                country_code="AZ",
                qualification="BSc",
                field="Computer Science",
                grade="3.95",
                grading_scale="4.0",
                completed_on=dt.date(2025, 6, 1),
            ),
        ),
    )
    weak_profile = make_profile(
        academic_history=(
            AcademicRecord(
                institution="Uni",
                country_code="AZ",
                qualification="BSc",
                field="Computer Science",
                grade="2.1",
                grading_scale="4.0",
                completed_on=dt.date(2025, 6, 1),
            ),
        ),
    )
    ml_strong = estimate_program_admission_chance(
        program, facts, strong_profile, calibration_rows=ml_rows
    )
    ml_weak = estimate_program_admission_chance(
        program, facts, weak_profile, calibration_rows=ml_rows
    )
    assert ml_strong.chance_pct > ml_weak.chance_pct


def test_sync_outcome_calibration_records_upserts_updates_and_deletes_on_redaction(
    agency_a, membership_a
) -> None:
    program = _make_program(country_code="DE", name="MSc Data Science")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        run: RecommendationRun = make_run(agency_a, membership_a)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://uni.example.org/ds",
            claim="MSc Data Science",
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            program=program,
            program_name=program.name,
            country_code="DE",
            degree_level="MASTER",
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
            estimated_chance_pct=62,
            calibration_features={
                "base_prior": 0.55,
                "gpa_margin": 0.4,
                "coursework_alignment": 1.0,
                "language_margin": 0.2,
                "winner_similarity": 0.0,
            },
        )
        app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=program.id,
            candidate=cand,
            state=Application.State.SUBMITTED,
        )
        correct_outcome(app, Application.Outcome.ADMITTED, actor=membership_a)

    synced = sync_outcome_calibration_records(tenant_id=agency_a.id)
    assert synced == 1
    rec = OutcomeCalibrationRecord.objects.get(application_id=app.id)
    assert rec.won is True
    assert rec.predicted_chance_pct == 62
    assert rec.program_id == program.id

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        correct_outcome(app, Application.Outcome.REJECTED, actor=membership_a)

    sync_outcome_calibration_records(tenant_id=agency_a.id)
    rec.refresh_from_db()
    assert rec.won is False

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        redact_student(tenant_id=agency_a.id, student_id=membership_a.id)
        cand.refresh_from_db()
        assert cand.estimated_chance_pct is None
        assert cand.calibration_features == {}

    sync_outcome_calibration_records(tenant_id=agency_a.id)
    assert not OutcomeCalibrationRecord.objects.filter(application_id=app.id).exists()


def test_bundled_scholarship_outcome_syncs_separately_and_purges_on_deletion(
    agency_a, membership_a
) -> None:
    """B1, B2, B4, I4: A programme card with a bundled scholarship records both outcomes."""
    from django.core.management import call_command

    from apps.funding.probability import purge_student_outcome_calibration_records
    from apps.portals.outcome import record_from_portal

    program = _make_program(country_code="FR", provision_type="JOINT", name="EMJM Chemoinformatics")
    org = record_organisation(
        domain="emjm.example.org",
        name="Erasmus Mundus Consortium",
        kind="PRIVATE_FOUNDATION",
        country_code="FR",
        found_via="REGISTER",
    )
    opp = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}",
        name="EMJM Full Scholarship",
        holder="PRIVATE_FOUNDATION",
        holder_domain="emjm.example.org",
        holder_name="Erasmus+",
        family="MULTILATERAL",
        organisation=org,
        scope_type="HOLDER",
        route="PART_OF_PROGRAM_APPLICATION",
        money_form="GRANT",
        tuition="FULL",
        living="FULL",
        agreement="AGREED",
        served=True,
    )

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        run: RecommendationRun = make_run(agency_a, membership_a)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://emjm.example.org/apply",
            claim="EMJM Chemoinformatics",
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        prog_cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            program=program,
            program_name=program.name,
            country_code="FR",
            degree_level="MASTER",
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
            estimated_chance_pct=28,
            calibration_features={
                "base_prior": 0.08,
                "gpa_margin": 0.6,
                "coursework_alignment": 1.0,
                "language_margin": 0.35,
                "experience_alignment": 0.45,
                "winner_similarity": 0.5,
            },
        )
        award_cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            opportunity=opp,
            program_name=opp.name,
            country_code="FR",
            degree_level="MASTER",
            funding_gap=Decimal("0.00"),
            funding_gap_is_placeholder=True,
            currency="EUR",
            eligible=True,
            funds_program_ids=[program.id],
            funding_card={
                "scope": "PROGRAM",
                "family": "MULTILATERAL",
                "route": "PART_OF_PROGRAM_APPLICATION",
            },
            estimated_chance_pct=19,
            calibration_features={
                "base_prior": 0.08,
                "gpa_margin": 0.6,
                "coursework_alignment": 0.25,
                "language_margin": 0.35,
                "experience_alignment": 0.45,
                "winner_similarity": 0.5,
            },
        )
        app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=program.id,
            candidate=prog_cand,
            state=Application.State.SUBMITTED,
        )
        # Portal records admitted to programme, rejected for bundled scholarship
        assert record_from_portal(
            app,
            Application.Outcome.ADMITTED,
            funding_outcome=Application.Outcome.REJECTED,
        )

    call_command("sync_outcome_calibration", tenant_id=agency_a.id)

    prog_rec = OutcomeCalibrationRecord.objects.get(application_id=app.id)
    assert prog_rec.program_id == program.id
    assert prog_rec.won is True
    assert prog_rec.outcome_source == "PORTAL"
    assert prog_rec.predicted_chance_pct == 28

    award_rec = OutcomeCalibrationRecord.objects.get(
        source_application_id=app.id,
        opportunity_id=opp.id,
    )
    assert award_rec.won is False
    assert award_rec.family == "MULTILATERAL"
    assert award_rec.route == "PART_OF_PROGRAM_APPLICATION"
    assert award_rec.outcome_source == "PORTAL"
    assert award_rec.predicted_chance_pct == 19
    assert award_cand.id is not None

    # Person correction overwrites both outcomes
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        correct_outcome(
            app,
            Application.Outcome.ADMITTED,
            actor=membership_a,
            funding_outcome=Application.Outcome.ADMITTED,
        )
    sync_outcome_calibration_records(tenant_id=agency_a.id)
    award_rec.refresh_from_db()
    assert award_rec.won is True
    assert award_rec.outcome_source == "PERSON"

    # Purging on student deletion removes both the programme row and the bundled scholarship row
    deleted = purge_student_outcome_calibration_records(
        tenant_id=agency_a.id,
        student_id=membership_a.id,
    )
    assert deleted == 2
    assert not OutcomeCalibrationRecord.objects.filter(source_application_id=app.id).exists()


def test_named_program_resolution_computes_cold_start_chance(
    agency_a, membership_a, monkeypatch
) -> None:
    """B5: resolve_named_program computes cold-start chance_pct and calibration_features."""
    from apps.funding.models import PackVersion
    from apps.funding.services import consider_named_program, resolve_named_program

    monkeypatch.setattr("apps.funding.services._queue_named_check", lambda *a, **kw: None)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        run: RecommendationRun = make_run(agency_a, membership_a)
        pack = PackVersion.objects.create(
            tenant=agency_a,
            run=run,
            version=1,
        )
        named = consider_named_program(
            pack,
            "Erasmus Mundus Joint Master in Quantum Technologies",
            actor=membership_a,
        )
        assert named.estimated_chance_pct is None
        resolved = resolve_named_program(
            named,
            eligible=True,
            reason="Verified official programme page",
            source_url="https://quantum-emjm.example.eu/programme",
            actor=membership_a,
        )
        assert resolved.estimated_chance_pct is not None
        assert 1 <= resolved.estimated_chance_pct <= 95
        assert resolved.calibration_features["base_prior"] == 0.08
        assert "experience_alignment" in resolved.calibration_features


def test_second_pass_audit_fixes_mail_funding_eb_language_waitlist_and_origin(
    agency_a, membership_a
) -> None:
    """Verify B1-B5, I1-I4, and G1 from the second-pass outcome & probability audit."""
    from django.template.loader import render_to_string

    from apps.dashboard.board import Column, FundingLine
    from apps.dashboard.board import build_card as _unused_build_card  # noqa: F401
    from apps.funding.probability import _calibrate_with_outcomes, _score_to_cefr_rank
    from apps.mailbox.decision_reader import DecisionReading
    from apps.mailbox.models import MailboxConnection, MailSignal
    from apps.portals.outcome import record_from_mail

    # B5: Test-specific numeric score mapping (Duolingo 115 is B2=2.0, not TOEFL 115 C2=4.0)
    assert _score_to_cefr_rank("Duolingo 115") == 2.0
    assert _score_to_cefr_rank("DET 130") == 3.0
    assert _score_to_cefr_rank("TOEFL 115") == 4.0
    assert _score_to_cefr_rank("PTE 65") == 2.0
    assert _score_to_cefr_rank("TestDaF TDN 4") == 2.0
    assert _score_to_cefr_rank("TestDaF TDN 5") == 3.0
    assert _score_to_cefr_rank("Cambridge 185") == 3.0

    # B3: Empirical Bayes centers prior on base_prior so 1 matching row does not double delta_logit
    features = {"base_prior": 0.30, "gpa_margin": 0.8}
    cold_prob = 0.60
    single_row = OutcomeCalibrationRecord(
        application_id=uuid4(),
        outcome_source="MAIL",
        predicted_chance_pct=60,
        feature_vector=features,
        won=False,
    )
    post_loss = _calibrate_with_outcomes(cold_prob, features, [single_row])
    assert post_loss < cold_prob

    # B1 + I1 + I4 + G1 + B4: Separate mail scholarship decision, expired waitlist, origin_country,
    # and orphan cleanup
    from apps.accounts.models import StudentProfileVersion

    program = _make_program(country_code="DE", name="MSc Robotics")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        pv = StudentProfileVersion.objects.create(
            student=membership_a,
            version=99,
            snapshot={"intended_intake": "2027-09-01", "nationality": "AZ"},
        )
        run = RecommendationRun.objects.create(profile_version=pv)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://tum.example.de/robotics",
            claim="MSc Robotics",
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            program=program,
            program_name=program.name,
            country_code="DE",
            degree_level="MASTER",
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
            estimated_chance_pct=62,
            calibration_features={
                "base_prior": 0.55,
                "gpa_margin": 0.5,
                "coursework_alignment": 1.0,
                "language_margin": 0.35,
                "experience_alignment": 0.3,
                "winner_similarity": 0.0,
            },
        )
        app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=program.id,
            candidate=cand,
            state=Application.State.SUBMITTED,
        )
        conn = MailboxConnection.objects.create(
            tenant=agency_a,
            membership=membership_a,
            provider="GOOGLE",
            address="student@example.test",
        )
        sig1 = MailSignal.objects.create(
            tenant=agency_a,
            connection=conn,
            provider_message_id="msg-1",
            sender_domain="tum.de",
            received_at=dt.datetime(2026, 10, 10, tzinfo=dt.UTC),
            application=app,
            trusted=True,
            sender_authenticated=True,
        )
        # Email 1: admission recorded by person
        correct_outcome(app, Application.Outcome.ADMITTED, actor=membership_a)
        assert app.outcome_source == "PERSON"
        assert app.funding_outcome == ""

        # Email 2: separate authenticated email announces bundled scholarship result only
        sig2 = MailSignal.objects.create(
            tenant=agency_a,
            connection=conn,
            provider_message_id="msg-2",
            sender_domain="tum.de",
            received_at=dt.datetime(2026, 10, 15, tzinfo=dt.UTC),
            application=app,
            trusted=True,
            sender_authenticated=True,
        )
        changed = record_from_mail(
            app,
            sig2,
            DecisionReading(
                is_decision=True,
                outcome="",
                funding_outcome="REJECTED",
                other_programme_offered=False,
                measured=True,
            ),
        )
        assert "funding_outcome" in changed
        app.refresh_from_db()
        assert app.outcome == "ADMITTED"
        assert app.outcome_source == "PERSON"
        assert app.funding_outcome == "REJECTED"
        assert app.funding_outcome_source == "MAIL"
        assert sig1.id is not None

        # I4: Waitlisted application from a past intake cycle is synced as won=False
        app.outcome = Application.Outcome.WAITLISTED
        app.save(update_fields=["outcome"])

    # Sync with today in 2026 (before 2027 intake): waitlisted is still open, so 0 rows synced
    sync_outcome_calibration_records(tenant_id=agency_a.id, today=dt.date(2026, 10, 29))
    assert not OutcomeCalibrationRecord.objects.filter(application_id=app.id).exists()

    # Sync with today in 2028 (after 2027 intake): expired waitlist is synced as won=False
    sync_outcome_calibration_records(tenant_id=agency_a.id, today=dt.date(2028, 2, 1))
    cal_rec = OutcomeCalibrationRecord.objects.get(application_id=app.id)
    assert cal_rec.won is False
    assert cal_rec.origin_country == "AZ"
    assert cal_rec.intake_year == 2027

    # B4: Unlinking candidate (`candidate=None`) and re-syncing cleans up the calibration row
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        Application.objects.filter(id=app.id).update(candidate=None)
    sync_outcome_calibration_records(tenant_id=agency_a.id, today=dt.date(2028, 2, 1))
    assert not OutcomeCalibrationRecord.objects.filter(application_id=app.id).exists()

    # B2: _card.html renders the bundled scholarship decision selector when card.funding
    from apps.dashboard.board import Card

    dummy_card = Card(
        application_id=uuid4(),
        title="MSc Robotics",
        institution="TUM",
        country="DE",
        column=Column.SUBMITTED,
        created_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        deadline=None,
        days_left=None,
        documents=(1, 1),
        answers=(1, 1),
        funding=(
            FundingLine(
                name="TUM Merit Scholarship",
                covers="tuition: full",
                amounts="1000 EUR/month",
            ),
        ),
        funding_outcome_line="",
        gap="",
        fee=None,
        fee_currency="",
        badges=(),
        missing=(),
        outcome_line="",
        offer=None,
        button=None,
        has_portal=True,
        portal_url="https://tum.de/portal",
        kit_url="",
        documents_url="/student/documents/",
        outcome_url="/student/applications/123/outcome/",
        remove_url="",
        portal_record_url="",
        outcome="",
        conditions=(),
        is_award=False,
    )
    rendered = render_to_string(
        "student/_card.html",
        {
            "card": dummy_card,
            "outcome_choices": Application.Outcome.choices,
            "read_only": False,
        },
    )
    assert 'name="funding_outcome"' in rendered
    assert "Scholarship decision" in rendered


def test_conditionally_affordable_vs_self_funded_card_wording(
    agency_a,
    membership_a,
) -> None:
    """R1: When a student cannot afford study without a scholarship, show P(admit and funded);
    when the student can afford study themselves and selective funding applies, show both."""
    from django.template.loader import render_to_string

    from apps.dashboard.board import board_for
    from apps.funding.models import EvidenceClaim, PackCandidate, PackVersion
    from apps.funding.probability import joint_admission_and_funding_chance_pct
    from apps.portals.models import Application

    assert joint_admission_and_funding_chance_pct(60, [25]) == 15
    assert joint_admission_and_funding_chance_pct(60, [25, 20]) == 24
    assert joint_admission_and_funding_chance_pct(60, []) is None

    prog_unaffordable = _make_program(country_code="DE", name="MSc Unaffordable Without Award")
    prog_affordable = _make_program(country_code="DE", name="MSc Self-Affordable With Award")
    prog_plain = _make_program(country_code="FR", name="MSc Plain No Selective Award")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        run: RecommendationRun = make_run(agency_a, membership_a)
        run.state = RecommendationRun.State.PUBLISHED
        run.save(update_fields=["state"])
        pack = PackVersion.objects.create(tenant=agency_a, run=run, version=1)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://tum.de/msc",
            claim="MSc",
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        # 1) Student cannot afford study without scholarship (funding_condition set)
        cand_unaffordable = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            program=prog_unaffordable,
            program_name=prog_unaffordable.name,
            country_code="DE",
            degree_level="MASTER",
            funding_gap=Decimal("20000.00"),
            self_funded=Decimal("2000.00"),
            funding_condition="Affordable only if you win DAAD Scholarship.",
            currency="EUR",
            eligible=True,
            estimated_chance_pct=60,
            estimated_funded_chance_pct=15,
        )
        # 2) Student can afford study himself (self_funded covers gap, no funding_condition),
        #    and selective funding also applies
        cand_affordable = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            program=prog_affordable,
            program_name=prog_affordable.name,
            country_code="DE",
            degree_level="MASTER",
            funding_gap=Decimal("10000.00"),
            self_funded=Decimal("10000.00"),
            funding_condition="",
            currency="EUR",
            eligible=True,
            estimated_chance_pct=60,
            estimated_funded_chance_pct=15,
        )
        # 3) Plain programme with no selective scholarship
        cand_plain = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            evidence=ev,
            program=prog_plain,
            program_name=prog_plain.name,
            country_code="FR",
            degree_level="MASTER",
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
            estimated_chance_pct=70,
            estimated_funded_chance_pct=None,
        )
        for cand in (cand_unaffordable, cand_affordable, cand_plain):
            PackCandidate.objects.create(tenant=agency_a, pack_version=pack, candidate=cand)
            Application.objects.create(
                tenant=agency_a,
                student=membership_a,
                program_id=cand.program_id,
                candidate=cand,
            )

        # Verify pack candidate template rendering (_candidate.html)
        html_unaffordable = render_to_string(
            "student/_candidate.html",
            {"candidate": cand_unaffordable, "applied": set(), "recognition_notes": {}},
        )
        assert (
            "We estimate that there is an ~15% chance of admission and funding"
            in html_unaffordable
        )
        assert "~60%" not in html_unaffordable

        html_affordable = render_to_string(
            "student/_candidate.html",
            {"candidate": cand_affordable, "applied": set(), "recognition_notes": {}},
        )
        assert (
            "We estimate that there is an ~60% chance (~15% with admission and funding)"
            in html_affordable
        )

        html_plain = render_to_string(
            "student/_candidate.html",
            {"candidate": cand_plain, "applied": set(), "recognition_notes": {}},
        )
        assert "We estimate that there is an ~70% chance</p>" in html_plain

        # Verify board cards (board_for)
        board = board_for(membership_a)
        by_title = {c.title: c for c in board.open_cards}
        assert (
            by_title[prog_unaffordable.name].chance_line
            == "We estimate that there is an ~15% chance of admission and funding"
        )
        assert (
            by_title[prog_affordable.name].chance_line
            == "We estimate that there is an ~60% chance (~15% with admission and funding)"
        )
        assert (
            by_title[prog_plain.name].chance_line
            == "We estimate that there is an ~70% chance"
        )


def test_extension_portal_outcome_endpoint(
    client,
    agency_a,
    domain_a,
    membership_a,
) -> None:
    """G2: POST /ext/applications/<id>/outcome records portal decisions via device token."""
    import json

    from apps.portals import pairing as pairing_module
    from apps.portals.models import Application, ApplicationStep, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.tum.de",
        form_key=f"tum-{uuid4()}",
        form_url="https://apply.tum.de/status",
    )
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            state=Application.State.SUBMITTED,
        )
        code = pairing_module.issue_pairing_code(membership_a, passwords_allowed=True)

    pair_resp = client.post(
        "/ext/pair",
        data=json.dumps({"code": code, "installation_id": "ext-outcome-1"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )
    assert pair_resp.status_code == 201
    token = pair_resp.json()["token"]

    url = f"/ext/applications/{app.id}/outcome"

    # Unauthenticated request is refused 401
    unauth = client.post(
        url,
        data=json.dumps({"outcome": "ADMITTED"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )
    assert unauth.status_code == 401

    # Invalid outcome value is refused 400
    bad = client.post(
        url,
        data=json.dumps({"outcome": "BOGUS"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert bad.status_code == 400
    assert bad.json() == {"error": "invalid_outcome"}

    # Valid portal outcome + funding_outcome records both and writes a STATUS step
    ok = client.post(
        url,
        data=json.dumps(
            {
                "outcome": "ADMITTED",
                "funding_outcome": "REJECTED",
                "portal_state": "Admission granted; scholarship not awarded",
            }
        ),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["recorded"] is True
    assert body["outcome"] == "ADMITTED"
    assert body["funding_outcome"] == "REJECTED"

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        app.refresh_from_db()
        assert app.outcome == "ADMITTED"
        assert app.outcome_source == Application.OutcomeSource.PORTAL
        assert app.funding_outcome == "REJECTED"
        assert app.funding_outcome_source == Application.OutcomeSource.PORTAL
        step = ApplicationStep.objects.get(id=body["step_id"])
        assert step.kind == ApplicationStep.Kind.STATUS
        assert step.detail["source"] == "portal_outcome"
        assert step.detail["recorded"] is True


def test_post_deadline_outcome_checkin_sweep(
    agency_a,
    membership_a,
    counselor_membership,
) -> None:
    """R3: Applications past their deadline by >=14 days that were submitted/confirmed
    and still have no outcome trigger a one-time MONITORING check-in notification."""
    from apps.concierge.models import Notification, RoadmapItem
    from apps.portals.models import Application, PortalForm
    from apps.portals.reminders import send_due_outcome_checkins_for_tenant
    from apps.tenancy.models import CounselorAssignment

    now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.UTC)
    form = PortalForm.objects.create(
        portal_host="apply.ethz.ch",
        form_key=f"eth-{uuid4()}",
        form_url="https://apply.ethz.ch/status",
    )

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a,
            counselor=counselor_membership,
            student=membership_a,
            active=True,
        )
        # 1) Submitted application 15 days past deadline with no outcome -> should fire
        due_app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            name="MSc Computer Science",
            state=Application.State.SUBMITTED,
            deadline=now - dt.timedelta(days=15),
        )
        # 2) Still PREPARING 15 days past deadline -> never submitted, should NOT fire
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            name="MSc Unsubmitted",
            state=Application.State.PREPARING,
            deadline=now - dt.timedelta(days=15),
        )
        # 3) Submitted but already has an outcome -> should NOT fire
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            name="MSc Decided",
            state=Application.State.SUBMITTED,
            deadline=now - dt.timedelta(days=15),
            outcome=Application.Outcome.ADMITTED,
        )

    assert send_due_outcome_checkins_for_tenant(agency_a.id, now=now) == 1

    with tenant_scope(agency_a.id):
        student_notifs = list(
            Notification.objects.filter(
                recipient=membership_a,
                roadmap_item__stage=RoadmapItem.Stage.MONITORING,
            )
        )
        assert len(student_notifs) == 1
        assert student_notifs[0].application_id == due_app.id
        assert "Have you heard back" in student_notifs[0].message

        counselor_notifs = list(
            Notification.objects.filter(
                recipient=counselor_membership,
                roadmap_item__stage=RoadmapItem.Stage.MONITORING,
            )
        )
        assert len(counselor_notifs) == 1
        assert counselor_notifs[0].application_id == due_app.id

    # Idempotent: a second sweep sends nothing while the first check-in is open
    assert send_due_outcome_checkins_for_tenant(agency_a.id, now=now) == 0


def test_audit_pass3_checkin_verification_collision_followup_no_deadline_and_auto_ack(
    agency_a,
    membership_a,
) -> None:
    """B1, I3, G1, B4:
    - B1: A VERIFICATION notification on Stage.MONITORING does not block post-deadline check-in.
    - I3: If the +14d check-in is acknowledged without an outcome, a second follow-up fires at +45d,
      and no third check-in fires after that.
    - G1: An application with `deadline=None` and `started_at <= now - 45d` receives a check-in.
    - B4: Recording an outcome auto-acknowledges open check-in notifications and marks their
      RoadmapItem DONE.
    """
    from apps.concierge.models import Notification, RoadmapItem
    from apps.concierge.services import acknowledge_notification
    from apps.portals.models import Application, PortalForm
    from apps.portals.outcome import correct_outcome
    from apps.portals.reminders import send_due_outcome_checkins_for_tenant

    now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.UTC)
    form = PortalForm.objects.create(
        portal_host="apply.tum.de",
        form_key=f"tum-{uuid4()}",
        form_url="https://apply.tum.de/status",
    )

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        app_with_verif = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            name="MSc Informatics",
            state=Application.State.SUBMITTED,
            deadline=now - dt.timedelta(days=16),
        )
        # B1: Pre-existing VERIFICATION alert on Stage.MONITORING
        Notification.raise_card(
            student=membership_a,
            recipient=membership_a,
            owner=membership_a,
            stage=RoadmapItem.Stage.MONITORING,
            deadline=now + dt.timedelta(days=5),
            application=app_with_verif,
            message=(
                "tum.de asked you to confirm your email address. "
                "Open the message in your inbox and use its link."
            ),
        )
        # G1: No-deadline submitted application started 46 days ago
        no_deadline_app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            name="MSc Robotics (Rolling)",
            state=Application.State.SUBMITTED,
            deadline=None,
            started_at=now - dt.timedelta(days=46),
        )

    # Both should fire (B1 + G1)
    assert send_due_outcome_checkins_for_tenant(agency_a.id, now=now) == 2

    # I3: Acknowledge the first check-in on app_with_verif without recording an outcome
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        first_checkin = Notification.objects.get(
            application=app_with_verif,
            message__startswith="Have you heard back from ",
        )
        acknowledge_notification(first_checkin)

    # At +20d (< 45d), follow-up does not fire yet
    later_20d = now + dt.timedelta(days=5)
    assert send_due_outcome_checkins_for_tenant(agency_a.id, now=later_20d) == 0

    # At +46d (>= 45d past deadline), the second follow-up check-in fires once
    later_46d = now + dt.timedelta(days=31)
    assert send_due_outcome_checkins_for_tenant(agency_a.id, now=later_46d) == 1

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        checkins = list(
            Notification.objects.filter(
                application=app_with_verif,
                message__startswith="Have you heard back from ",
            ).order_by("created_at")
        )
        assert len(checkins) == 2
        assert checkins[1].acknowledged_at is None
        # B4: Recording an outcome auto-acknowledges the open check-in notification
        correct_outcome(
            app_with_verif,
            Application.Outcome.REJECTED,
            actor=membership_a,
        )
        checkins[1].refresh_from_db()
        assert checkins[1].acknowledged_at is not None
        assert checkins[1].roadmap_item.state == RoadmapItem.State.DONE

        # Also test that even if outcome weren't set and 2nd check-in were acknowledged,
        # a 3rd check-in never fires
        no_dl_checkin = Notification.objects.get(
            application=no_deadline_app,
            message__startswith="Have you heard back from ",
        )
        acknowledge_notification(no_dl_checkin)

    later_100d = now + dt.timedelta(days=60)
    assert send_due_outcome_checkins_for_tenant(agency_a.id, now=later_100d) == 1
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        for n in Notification.objects.filter(
            application=no_deadline_app,
            message__startswith="Have you heard back from ",
        ):
            acknowledge_notification(n)
    assert (
        send_due_outcome_checkins_for_tenant(
            agency_a.id, now=later_100d + dt.timedelta(days=60)
        )
        == 0
    )


def test_audit_pass3_portal_outcome_standalone_award_and_board_midflight_funding(
    agency_a,
    membership_a,
) -> None:
    """B2 & B5:
    - B2: `record_from_portal` on a standalone scholarship card (`candidate.opportunity_id != None`)
      accepts `funding_outcome` and writes it to `Application.outcome`.
    - B5: When a programme's admission is still undecided (`outcome == ""`), a won or rejected
      scholarship (`funding_outcome` or linked scholarship `Application.outcome`) updates the
      programme card's live `chance_line`.
    """
    from apps.accounts.models import StudentProfileVersion
    from apps.dashboard.board import _chance_line
    from apps.funding.models import (
        EvidenceClaim,
        FundingOpportunity,
        RecommendationCandidate,
        RecommendationRun,
    )
    from apps.portals.models import Application
    from apps.portals.outcome import record_from_portal

    prog = _make_program(country_code="DE", name="MSc Data Engineering")
    opp = FundingOpportunity.objects.create(
        canonical_key=f"opp:{uuid4()}",
        name=f"DAAD-{uuid4()}",
        scope_type="COUNTRY",
        country_code="DE",
        family="GOVERNMENT_SCHOLARSHIP",
        route="STUDENT_APPLIES_SEPARATELY",
        served=True,
    )

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        pv = StudentProfileVersion.objects.create(
            student=membership_a,
            version=101,
            snapshot={"intended_intake": "2027-09-01", "nationality": "AZ"},
        )
        run = RecommendationRun.objects.create(profile_version=pv)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://www.tum.de/msc",
            claim="Official",
            last_checked_at=dt.datetime.now(dt.UTC),
        )
        award_cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            opportunity_id=opp.id,
            evidence=ev,
            program_name=opp.name,
            country_code="DE",
            funding_gap=Decimal("0"),
            currency="EUR",
            eligible=True,
            state=RecommendationCandidate.State.VISIBLE,
            estimated_chance_pct=25,
        )
        award_app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=opp.id,
            candidate=award_cand,
            name=opp.name,
        )
        # B2: Extension posts funding_outcome="ADMITTED" on a standalone scholarship card
        assert record_from_portal(award_app, funding_outcome="ADMITTED") is True
        award_app.refresh_from_db()
        assert award_app.outcome == "ADMITTED"
        assert award_app.outcome_source == Application.OutcomeSource.PORTAL

        prog_cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            program_id=prog.id,
            evidence=ev,
            program_name=prog.name,
            country_code="DE",
            funding_gap=Decimal("0"),
            self_funded=Decimal("10000"),
            funding_card={"needs_selective_funding": False},
            currency="EUR",
            eligible=True,
            state=RecommendationCandidate.State.VISIBLE,
            estimated_chance_pct=65,
            estimated_funded_chance_pct=20,
        )
        prog_app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=prog.id,
            candidate=prog_cand,
            name=prog.name,
        )
        # Before scholarship decision: shows both 65% and 20% funded
        line_initial = _chance_line(
            prog_app, prog_cand, awards=[award_cand], mandatory=False
        )
        assert (
            line_initial
            == "We estimate that there is an ~65% chance (~20% with admission and funding)"
        )

        # Linked scholarship won while programme admission still pending -> funded_pct == 65%
        line_won = _chance_line(
            prog_app,
            prog_cand,
            awards=[award_cand],
            mandatory=False,
            linked_award_outcomes=("ADMITTED",),
        )
        assert (
            line_won
            == "We estimate that there is an ~65% chance (~65% with admission and funding)"
        )

        # Linked scholarship rejected while programme admission still pending -> drops funded part
        line_lost = _chance_line(
            prog_app,
            prog_cand,
            awards=[award_cand],
            mandatory=False,
            linked_award_outcomes=("REJECTED",),
        )
        assert line_lost == "We estimate that there is an ~65% chance"


def test_audit_pass3_attached_program_scholarship_calibration_and_named_program_url() -> None:
    """B3, I1, I2:
    - I1: `infer_country_from_url` and `estimate_named_program_chance` infer country from URL ccTLD.
    - I2: `joint_admission_and_funding_chance_pct` supports positive correlation and caps at
      `min(admit_chance_pct, round(P(any award) * 100))`.
    """
    from apps.funding.probability import (
        estimate_named_program_chance,
        infer_country_from_url,
        joint_admission_and_funding_chance_pct,
    )

    assert infer_country_from_url("https://www.tum.de/en/studies") == "DE"
    assert infer_country_from_url("https://www.ox.ac.uk/admissions") == "GB"
    assert infer_country_from_url("https://www.mit.edu/academics") == "US"

    est_de = estimate_named_program_chance(
        "MSc Informatics", "", None, source_url="https://www.tum.de/msc"
    )
    est_gb = estimate_named_program_chance(
        "MSc Computer Science", "", None, source_url="https://www.ox.ac.uk/msc"
    )
    # Rule-based DE prior (55%) > selective cohort GB prior (30%)
    assert est_de.chance_pct == 55
    assert est_gb.chance_pct == 30

    # I2: Positive correlation increases joint probability toward min(admit, award)
    indep = joint_admission_and_funding_chance_pct(60, [25], correlation=0.0)
    corr = joint_admission_and_funding_chance_pct(60, [25], correlation=0.5)
    full_corr = joint_admission_and_funding_chance_pct(60, [25], correlation=1.0)
    assert indep == 15
    assert corr is not None and 15 < corr <= 25
    assert full_corr == 25


def test_audit_pass3_sync_attached_program_scholarship_without_award_candidate(
    agency_a,
    membership_a,
) -> None:
    """B3: `sync_outcome_calibration_records` records an `OutcomeCalibrationRecord` for a
    `PROGRAM`-scoped attached scholarship when `app.funding_outcome` is decided on the
    programme card, even when the scholarship has no separate `RecommendationCandidate` row."""
    from apps.accounts.models import StudentProfileVersion
    from apps.funding.models import (
        EvidenceClaim,
        FundingOpportunity,
        OutcomeCalibrationRecord,
        RecommendationCandidate,
        RecommendationRun,
    )
    from apps.funding.probability import sync_outcome_calibration_records
    from apps.portals.models import Application

    prog = _make_program(country_code="NL", name="MSc Aerospace Engineering")
    att_opp = FundingOpportunity.objects.create(
        canonical_key=f"opp:{uuid4()}",
        name=f"Justus & Louise-{uuid4()}",
        scope_type="PROGRAM",
        program=prog,
        country_code=None,
        institution=None,
        family="UNIVERSITY_WIDE",
        route="PART_OF_PROGRAM_APPLICATION",
        tuition="FULL",
        living="FULL",
        served=True,
    )

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        pv = StudentProfileVersion.objects.create(
            student=membership_a,
            version=102,
            snapshot={"intended_intake": "2027-09-01", "nationality": "AZ"},
        )
        run = RecommendationRun.objects.create(profile_version=pv)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://www.tudelft.nl/msc",
            claim="Official",
            last_checked_at=dt.datetime.now(dt.UTC),
        )
        prog_cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            program_id=prog.id,
            evidence=ev,
            program_name=prog.name,
            country_code="NL",
            funding_gap=Decimal("0"),
            currency="EUR",
            eligible=True,
            state=RecommendationCandidate.State.VISIBLE,
            estimated_chance_pct=50,
            estimated_funded_chance_pct=12,
            calibration_features={
                "base_prior": 0.5,
                "gpa_margin": 0.2,
                "coursework_alignment": 0.4,
                "language_margin": 0.2,
                "experience_alignment": 0.1,
                "winner_similarity": 0.0,
            },
        )
        app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=prog.id,
            candidate=prog_cand,
            name=prog.name,
            outcome=Application.Outcome.ADMITTED,
            outcome_source=Application.OutcomeSource.PERSON,
            funding_outcome=Application.Outcome.REJECTED,
            funding_outcome_source=Application.OutcomeSource.PERSON,
        )

    sync_outcome_calibration_records(tenant_id=agency_a.id)
    cal = OutcomeCalibrationRecord.objects.filter(
        source_application_id=app.id,
        opportunity_id=att_opp.id,
    ).first()
    assert cal is not None
    assert cal.won is False
    assert cal.family == "UNIVERSITY_WIDE"
    assert cal.route == "PART_OF_PROGRAM_APPLICATION"


def test_audit_pass4_blank_outcome_does_not_block_portal_and_card_template_preselects(
    agency_a,
    membership_a,
) -> None:
    """Audit Pass 4 (B1–B3, I1, G1):
    - B2: Recording `funding_outcome` while `outcome=""` via `correct_outcome` leaves `outcome`
      open to a subsequent `record_from_portal` admission decision.
    - B3: `templates/student/_card.html` pre-selects `card.outcome` and `card.funding_outcome`
      and renders the scholarship dropdown when `card.has_bundled_funding` is True even if
      `card.funding` is empty.
    - I1 & G1: An admitted application with `estimated_funded_chance_pct` and `funding_outcome=""`
      receives a `+45d` post-deadline check-in, and recording `funding_outcome` via portal
      auto-acknowledges the open check-in notification.
    """
    from django.template.loader import render_to_string

    from apps.accounts.models import StudentProfileVersion
    from apps.concierge.models import Notification
    from apps.dashboard.board import Card, Column
    from apps.funding.models import (
        EvidenceClaim,
        RecommendationCandidate,
        RecommendationRun,
    )
    from apps.portals.models import Application
    from apps.portals.outcome import correct_outcome, record_from_portal
    from apps.portals.reminders import send_due_outcome_checkins_for_tenant

    now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.UTC)
    prog = _make_program(country_code="DE", name="MSc Systems Engineering")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        pv = StudentProfileVersion.objects.create(
            student=membership_a,
            version=103,
            snapshot={"intended_intake": "2027-09-01", "nationality": "AZ"},
        )
        run = RecommendationRun.objects.create(profile_version=pv)
        ev = EvidenceClaim.objects.create(
            tenant=agency_a,
            source_url="https://www.tum.de/systems",
            claim="Official",
            last_checked_at=now,
        )
        cand = RecommendationCandidate.objects.create(
            tenant=agency_a,
            run=run,
            program_id=prog.id,
            evidence=ev,
            program_name=prog.name,
            country_code="DE",
            funding_gap=Decimal("0"),
            currency="EUR",
            eligible=True,
            state=RecommendationCandidate.State.VISIBLE,
            estimated_chance_pct=60,
            estimated_funded_chance_pct=18,
        )
        app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=prog.id,
            candidate=cand,
            name=prog.name,
            state=Application.State.SUBMITTED,
            deadline=now - dt.timedelta(days=46),
        )
        # B2: Student records funding_outcome="ADMITTED" while admission outcome is still ""
        correct_outcome(app, "", actor=membership_a, funding_outcome="ADMITTED")
        app.refresh_from_db()
        assert app.outcome == ""
        assert app.funding_outcome == "ADMITTED"

        # Later, portal reports admission decision -> must NOT be blocked by blank PERSON outcome!
        assert record_from_portal(app, outcome="ADMITTED") is True
        app.refresh_from_db()
        assert app.outcome == "ADMITTED"
        assert app.outcome_source == Application.OutcomeSource.PORTAL
        assert app.funding_outcome == "ADMITTED"

        # Reset funding_outcome="" to test I1 (+45d check-in for missing bundled outcome)
        app.funding_outcome = ""
        app.funding_outcome_source = ""
        app.save(update_fields=["funding_outcome", "funding_outcome_source"])

    # I1: Admitted application with missing bundled funding_outcome at +46d triggers check-in
    assert send_due_outcome_checkins_for_tenant(agency_a.id, now=now) == 1

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        checkin = Notification.objects.get(
            application=app,
            message__startswith="Have you heard back from ",
        )
        assert checkin.acknowledged_at is None
        # G1: Recording funding_outcome-only via portal auto-acknowledges the check-in
        assert record_from_portal(app, funding_outcome="REJECTED") is True
        checkin.refresh_from_db()
        assert checkin.acknowledged_at is not None

    # B3: _card.html pre-selects outcome & funding_outcome and shows scholarship select when
    # has_bundled_funding=True even with funding=()
    rendered = render_to_string(
        "student/_card.html",
        {
            "card": Card(
                application_id=app.id,
                title=prog.name,
                institution="TUM",
                country="DE",
                column=Column.SUBMITTED,
                created_at=now,
                deadline=now,
                days_left=0,
                documents=(1, 1),
                answers=(1, 1),
                funding=(),
                funding_outcome_line="Scholarship: not awarded — from your portal",
                gap="",
                fee=None,
                fee_currency="",
                badges=(),
                missing=(),
                outcome_line="Admitted — from your portal",
                offer=None,
                button=None,
                has_portal=True,
                portal_url="https://www.tum.de/systems",
                kit_url="/kit",
                documents_url="/docs",
                outcome_url="/outcome",
                remove_url="",
                portal_record_url="",
                outcome="ADMITTED",
                conditions=(),
                funding_outcome="REJECTED",
                has_bundled_funding=True,
            ),
            "outcome_choices": Application.Outcome.choices,
            "read_only": False,
        },
    )
    assert 'name="funding_outcome"' in rendered
    assert '<option value="ADMITTED" selected>' in rendered
    assert '<option value="REJECTED" selected>' in rendered






