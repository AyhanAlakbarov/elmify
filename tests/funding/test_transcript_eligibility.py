"""Tests for extracting programme/scholarship eligibility rules and checking them
against the student's profile and transcript courses (`apps/funding/transcript_eligibility.py`,
`apps/funding/requirements.py`, `apps/funding/eligibility.py`,
`apps/research/programme_scraper.py`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounts.schemas import (
    AcademicRecord,
    CourseRecord,
    ExperienceRecord,
    LanguageEvidence,
    Money,
    StudentProfileSnapshot,
)
from apps.funding import models as catalog
from apps.funding.eligibility import ConditionTriple, decide
from apps.funding.requirements import NOT_YET_CHECKED, program_requirements
from apps.funding.transcript_eligibility import (
    convert_bavarian_to_us_gpa,
    convert_grade_to_bavarian,
    convert_to_german_bavarian_grade,
    evaluate_program_statement,
    evaluate_subject_pool_rule,
    is_failing_or_withdrawn_grade,
    normalize_transcript_courses,
    parse_subject_pool_rule,
)
from apps.research.programme_scraper import (
    build_programme_bundle,
    extract_tier0_programme_facts,
    persist_programme_scrape,
)


def _lang(
    language: str,
    level: str,
    *,
    evidence_type: str = "TEST",
    available_by: dt.date = dt.date(2025, 1, 1),
) -> LanguageEvidence:
    return LanguageEvidence(
        language=language,
        level=level,
        evidence_type=evidence_type,  # type: ignore[arg-type]
        available_by=available_by,
    )


def _exp(kind: str, months: int) -> ExperienceRecord:
    return ExperienceRecord(
        kind=kind,  # type: ignore[arg-type]
        summary=f"{kind} experience",
        months=months,
    )


def _make_profile(
    courses: tuple[CourseRecord, ...] = (),
    *,
    field: str = "Computer Science",
    qualification: str = "Bachelor of Science",
    country_code: str = "AZ",
    grade: str = "3.6",
    grading_scale: str = "4.0",
    completed_on: dt.date | None = None,
    expected_completion: dt.date | None = None,
    language_evidence: tuple[LanguageEvidence, ...] = (),
    experience: tuple[ExperienceRecord, ...] | None = (),
) -> StudentProfileSnapshot:
    return StudentProfileSnapshot(
        nationality="AZ",
        country_of_residence="AZ",
        date_of_birth=dt.date(2002, 5, 15),
        target_field=field,
        intended_intake=dt.date(2027, 9, 1),
        acceptable_teaching_languages=("English", "German"),
        career_intent="WORK_ABROAD",
        application_budget=Money(amount=Decimal("500"), currency="EUR"),
        funding_dependency="MANDATORY",
        strategy="FUNDING_FIRST",
        academic_history=(
            AcademicRecord(
                institution="Baku State University",
                country_code=country_code,
                qualification=qualification,
                field=field,
                grade=grade,
                grading_scale=grading_scale,
                completed_on=completed_on,
                expected_completion=expected_completion,
                courses=courses,
            ),
        ),
        language_evidence=language_evidence,
        experience=experience,
    )


def test_single_bucket_theoretical_cs_satisfied_and_shows_counted_courses() -> None:
    profile = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("8"), grade="A"),
            CourseRecord(title="Computability and Complexity Theory", ects=Decimal("6"), grade="B"),
            CourseRecord(title="Discrete Mathematics", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Mathematical Logic", ects=Decimal("6"), grade="B+"),
            # Unrelated systems course must NOT be counted toward Theoretical CS
            CourseRecord(title="Operating Systems", ects=Decimal("6"), grade="A"),
        )
    )
    ev = evaluate_program_statement(
        "Applicants must have completed at least 30 ECTS in Theoretical Computer Science.",
        profile,
    )
    assert ev.outcome == "SATISFIED"
    assert ev.completed_definite_ects == Decimal("32")
    assert "Met (Theoretical Computer Science) — counted 32 / 30 ECTS:" in ev.status_text
    assert "Automata and Formal Languages (6 ECTS)" in ev.status_text
    assert "Algorithms and Data Structures (8 ECTS)" in ev.status_text
    assert "Operating Systems" not in ev.status_text


def test_borderline_omnibus_course_lifts_to_borderline_interval_never_failed() -> None:
    profile = _make_profile(
        courses=(
            CourseRecord(title="Automata Theory", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Discrete Mathematics", ects=Decimal("6"), grade="B"),
            CourseRecord(title="Mathematical Logic", ects=Decimal("6"), grade="A"),
            # Omnibus introductory course (borderline for Theoretical CS)
            CourseRecord(title="Foundations of Informatics I", ects=Decimal("8"), grade="A"),
        )
    )
    ev = evaluate_program_statement(
        "Minimum of 30 ECTS in Theoretical Computer Science.",
        profile,
    )
    assert ev.outcome == "BORDERLINE"
    assert ev.completed_definite_ects == Decimal("24")
    assert ev.completed_possible_ects == Decimal("32")
    assert "counted 24–32 of 30 ECTS" in ev.status_text
    assert "borderline: Foundations of Informatics I (8 ECTS)" in ev.status_text


def test_in_progress_course_yields_conditional_in_progress_verdict() -> None:
    profile = _make_profile(
        courses=(
            CourseRecord(title="Automata Theory", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Discrete Mathematics", ects=Decimal("6"), grade="B"),
            CourseRecord(title="Computability Theory", ects=Decimal("6"), grade="A"),
            CourseRecord(
                title="Formal Verification and Model Checking",
                ects=Decimal("6"),
                grade=None,
                in_progress=True,
            ),
        )
    )
    ev = evaluate_program_statement(
        "At least 30 ECTS in Theoretical Computer Science.",
        profile,
    )
    assert ev.outcome == "IN_PROGRESS"
    assert ev.completed_definite_ects == Decimal("24")
    assert ev.in_progress_ects == Decimal("6")
    assert "Conditional (in progress" in ev.status_text
    assert "24 / 30 ECTS completed" in ev.status_text
    assert "+ 6 ECTS in progress: Formal Verification and Model Checking (6 ECTS)" in ev.status_text


def test_failed_withdrawn_and_retaken_courses_are_filtered_and_deduplicated() -> None:
    assert is_failing_or_withdrawn_grade("F") is True
    assert is_failing_or_withdrawn_grade("W") is True
    assert is_failing_or_withdrawn_grade("не зачтено") is True
    assert is_failing_or_withdrawn_grade("kəsr") is True
    assert is_failing_or_withdrawn_grade("başarısız") is True
    assert is_failing_or_withdrawn_grade("nicht bestanden") is True
    assert is_failing_or_withdrawn_grade("5.0", "1.0-5.0") is True
    assert is_failing_or_withdrawn_grade("5.0", "5.0") is False  # 5 on 5-point scale is A!
    assert is_failing_or_withdrawn_grade("2", "5.0") is True
    assert is_failing_or_withdrawn_grade("45", "100") is True
    assert is_failing_or_withdrawn_grade("P") is False
    assert is_failing_or_withdrawn_grade("зачтено") is False
    assert is_failing_or_withdrawn_grade("bestanden") is False

    profile = _make_profile(
        courses=(
            # Failed first attempt + passed retake -> must count 6 ECTS once, not 12!
            CourseRecord(title="Linear Algebra", ects=Decimal("6"), grade="F"),
            CourseRecord(title="Linear Algebra (Retake)", ects=Decimal("6"), grade="B+"),
            # Passed course retaken for grade improvement -> must count 6 ECTS once!
            CourseRecord(title="Probability Theory", ects=Decimal("6"), grade="C"),
            CourseRecord(title="Probability Theory (Repeat)", ects=Decimal("6"), grade="A"),
            # Sequence courses I and II must stay distinct (12 ECTS total)
            CourseRecord(title="Mathematical Analysis I", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Mathematical Analysis II", ects=Decimal("6"), grade="B"),
            # Withdrawn course -> 0 ECTS
            CourseRecord(title="Differential Equations", ects=Decimal("6"), grade="W"),
            # Pass/Fail passed course -> counts 6 ECTS
            CourseRecord(title="Numerical Methods", ects=Decimal("6"), grade="Pass"),
        )
    )
    norm = normalize_transcript_courses(profile)
    assert len(norm) == 5
    ev = evaluate_program_statement("At least 30 ECTS in Mathematics.", profile)
    assert ev.outcome == "SATISFIED"
    assert ev.completed_definite_ects == Decimal("30")


def test_conjunctive_buckets_do_not_double_count_shared_courses() -> None:
    """Discrete Mathematics matches both Mathematics and Theoretical CS.
    If the student only has 18 ECTS total (6 Math + 6 TCS + 6 shared Discrete Math),
    a requirement of '12 ECTS in Theoretical CS AND 12 ECTS in Mathematics' must FAIL
    because Discrete Math (6 ECTS) cannot be counted 100% in both buckets (12 + 12 = 24 > 18)!"""
    profile = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Linear Algebra", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Discrete Mathematics", ects=Decimal("6"), grade="A"),
        )
    )
    ev = evaluate_program_statement(
        "At least 12 ECTS in Theoretical Computer Science and at least 12 ECTS in Mathematics.",
        profile,
    )
    assert ev.outcome == "FAILED"
    assert ev.completed_definite_ects == Decimal("18")

    # Adding 6 ECTS of Calculus brings total to 24 ECTS (12 TCS + 12 Math) -> SATISFIED!
    profile_pass = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Linear Algebra", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Discrete Mathematics", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Calculus I", ects=Decimal("6"), grade="A"),
        )
    )
    ev_pass = evaluate_program_statement(
        "At least 12 ECTS in Theoretical Computer Science and at least 12 ECTS in Mathematics.",
        profile_pass,
    )
    assert ev_pass.outcome == "SATISFIED"


def test_combined_pool_with_subfloors_allows_subfloor_in_parent_pool() -> None:
    profile = _make_profile(
        courses=(
            CourseRecord(title="Calculus I", ects=Decimal("10"), grade="A"),
            CourseRecord(title="Linear Algebra", ects=Decimal("10"), grade="A"),
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("10"), grade="A"),
            CourseRecord(title="Operating Systems", ects=Decimal("10"), grade="A"),
            CourseRecord(title="Database Systems", ects=Decimal("10"), grade="A"),
            CourseRecord(title="Software Engineering", ects=Decimal("10"), grade="A"),
        )
    )
    ev = evaluate_program_statement(
        "At least 60 ECTS across Mathematics and Computer Science, "
        "of which at least 18 ECTS must be in Mathematics.",
        profile,
    )
    assert ev.outcome == "SATISFIED"
    assert "counted 60 / 60 ECTS" in ev.status_text
    assert "counted 20 / 18 ECTS" in ev.status_text


def test_named_topic_checklist_flags_missing_topic_even_when_ects_met() -> None:
    profile = _make_profile(
        courses=(
            CourseRecord(title="Linear Algebra I", ects=Decimal("10"), grade="A"),
            CourseRecord(title="Calculus and Real Analysis", ects=Decimal("10"), grade="A"),
        )
    )
    ev = evaluate_program_statement(
        "At least 18 ECTS in Mathematics (covering Linear Algebra, Calculus, and Probability).",
        profile,
    )
    assert ev.outcome == "BORDERLINE"
    assert ev.missing_topics == ("Probability",)
    assert "missing named topics: Probability" in ev.status_text


def test_conditional_bridging_deficit_allowance() -> None:
    profile = _make_profile(
        courses=(
            CourseRecord(title="Automata Theory", ects=Decimal("8"), grade="A"),
            CourseRecord(title="Algorithms", ects=Decimal("8"), grade="A"),
            CourseRecord(title="Discrete Mathematics", ects=Decimal("8"), grade="A"),
        )
    )
    ev = evaluate_program_statement(
        "At least 30 ECTS in Theoretical Computer Science. Applicants missing up to 10 ECTS "
        "may complete bridging modules during the first year.",
        profile,
    )
    assert ev.outcome == "CONDITIONAL_BRIDGE"
    assert "6 ECTS deficit within 10 ECTS make-up limit" in ev.status_text


def test_multilingual_course_titles_az_tr_ru_de_match_theoretical_cs() -> None:
    profile = _make_profile(
        courses=(
            # Azerbaijani
            CourseRecord(title="Diskret riyaziyyat", ects=Decimal("6"), grade="əla"),
            CourseRecord(
                title="Alqoritmlər və verilənlər strukturu", ects=Decimal("6"), grade="əla"
            ),
            # Russian
            CourseRecord(title="Автоматы и формальные языки", ects=Decimal("6"), grade="отлично"),
            # Turkish
            CourseRecord(title="Hesaplama Kuramı ve Karmaşıklık", ects=Decimal("6"), grade="AA"),
            # German
            CourseRecord(title="Mathematische Logik", ects=Decimal("6"), grade="1.3"),
        )
    )
    ev = evaluate_program_statement(
        "At least 30 ECTS in Theoretical Computer Science.",
        profile,
    )
    assert ev.outcome == "SATISFIED"
    assert ev.completed_definite_ects == Decimal("30")


def test_non_ects_units_cats_and_us_credits_and_course_counts() -> None:
    rule_cats = parse_subject_pool_rule("At least 40 CATS credits in Mathematics.")
    assert rule_cats is not None
    assert rule_cats.buckets[0].min_ects == Decimal("20.00")

    rule_us = parse_subject_pool_rule("Minimum of 12 US semester credits in Computer Science.")
    assert rule_us is not None
    assert rule_us.buckets[0].min_ects == Decimal("24.00")

    profile = _make_profile(
        courses=(
            CourseRecord(title="Probability and Statistics", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Econometrics", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Time Series Analysis", ects=Decimal("6"), grade="B"),
        )
    )
    ev = evaluate_program_statement("At least 3 courses in Statistics.", profile)
    assert ev.outcome == "SATISFIED"
    assert "counted 3 / 3 courses" in ev.status_text


def test_total_degree_ects_and_german_bavarian_grade_and_ielts_exact_score() -> None:
    # 1. Total degree credits (180 vs 240 ECTS)
    profile_180 = _make_profile(
        courses=tuple(
            CourseRecord(title=f"Course {i}", ects=Decimal("30"), grade="A") for i in range(6)
        ),
        grade="3.5",
        grading_scale="4.0",
        language_evidence=(_lang("English", "IELTS 6.0"),),
    )
    ev_180 = evaluate_program_statement(
        "A Bachelor's degree worth at least 180 ECTS.", profile_180
    )
    assert ev_180.outcome == "SATISFIED"
    assert "counted 180 / 180 total ECTS" in ev_180.status_text

    ev_240 = evaluate_program_statement(
        "A 4-year Bachelor's degree of at least 240 ECTS.", profile_180
    )
    assert ev_240.outcome == "FAILED"
    assert "counted 180 / 240 total ECTS" in ev_240.status_text

    # 2. Modified Bavarian Formula conversion (3.5/4.0 -> 1.75 -> ~1.8 German grade <= 2.5)
    assert convert_to_german_bavarian_grade(
        Decimal("3.5"), Decimal("4.0"), Decimal("2.0")
    ) == Decimal("1.8")
    ev_de = evaluate_program_statement("German grade of 2.5 or better.", profile_180)
    assert ev_de.outcome == "SATISFIED"
    assert "Bavarian grade" in ev_de.status_text

    # 3. Exact IELTS 6.0 vs required IELTS 6.5 (both are CEFR B2, must FAIL!)
    ev_ielts = evaluate_program_statement(
        "IELTS 6.5 overall.", profile_180, kind="LANGUAGE"
    )
    assert ev_ielts.outcome == "FAILED"
    assert "counted IELTS 6.0 against required IELTS 6.5" in ev_ielts.status_text

    # And `eligibility.decide` also fails IELTS 6.0 against English IELTS 6.5!
    dec_ielts = decide(
        ConditionTriple(
            key="LANGUAGE",
            operator="GTE",
            value="English IELTS 6.5",
            quote="Requires English IELTS 6.5.",
        ),
        profile_180,
    )
    assert dec_ielts.outcome == "FAILED"

    # 4. IELTS per-band subscore check (overall 7.0 >= 6.5, but subscore 5.5 < 6.0 -> FAILED)
    profile_subscore = _make_profile(
        language_evidence=(
            _lang("English", "IELTS 7.0 (L:7.5, R:7.5, W:5.5, S:7.0)"),
        )
    )
    ev_sub = evaluate_program_statement(
        "IELTS 6.5 overall with no band below 6.0.", profile_subscore, kind="LANGUAGE"
    )
    assert ev_sub.outcome == "FAILED"
    assert "lowest subscore 5.5 is below required 6.0" in ev_sub.status_text

    # 5. GRE waived by GPA >= 3.5 and Work Experience excluding internships
    ev_gre = evaluate_program_statement(
        "GRE Quantitative score of at least 164 "
        "(waived for applicants with a GPA of 3.5 or higher).",
        profile_180,
    )
    assert ev_gre.outcome == "SATISFIED"
    assert "Met via GPA waiver" in ev_gre.status_text

    profile_exp = _make_profile(
        experience=(
            _exp("WORK", 18),
            _exp("INTERNSHIP", 12),
        )
    )
    ev_work = evaluate_program_statement(
        "At least 2 years of professional work experience.", profile_exp
    )
    assert ev_work.outcome == "FAILED"
    expected_work = (
        "counted 18 / 24 months of professional work experience "
        "(excluding 12 months of internship)"
    )
    assert expected_work in ev_work.status_text


@pytest.mark.django_db
def test_end_to_end_scrape_persist_and_program_requirements_shows_counted_by_us() -> None:
    """Real caller integration test: scrape HTML with a 30 ECTS Theoretical CS requirement,
    persist via `persist_programme_scrape`, and verify `program_requirements(prog, cycle, profile)`
    replaces `NOT_YET_CHECKED` with our course-by-course counted verdict."""
    html = (
        "<html><body>"
        "<h2>Admission Requirements</h2>"
        "<p>Applicants must hold a Bachelor's degree in Computer Science and have completed "
        "at least 30 ECTS in Theoretical Computer Science.</p>"
        "<p>Language proficiency: IELTS 6.5 overall with no band below 6.0.</p>"
        "</body></html>"
    )
    bundle = build_programme_bundle([("https://uni.example.de/msc-cs", html)])
    result = extract_tier0_programme_facts(bundle)
    assert any(s.label == "Subject Credit Requirement" for s in result.statements)

    inst = catalog.Institution.objects.create(
        canonical_key="institution:uni-example-de",
        name="Example TU",
        country_code="DE",
        official_website="https://uni.example.de",
    )
    prog = catalog.Program.objects.create(
        institution=inst,
        canonical_key="program:uni-example-de:msc-cs",
        name="M.Sc. Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="de:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    persist_programme_scrape(
        prog,
        result,
        pages_by_url={"https://uni.example.de/msc-cs": html},
    )

    # Without profile, status remains NOT_YET_CHECKED
    unchecked = program_requirements(prog, cycle="2027")
    assert all(item.status == NOT_YET_CHECKED for item in unchecked.applicant)

    # With student profile, status shows exact courses counted by us
    profile = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("8"), grade="A"),
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("8"), grade="A"),
            CourseRecord(title="Computability and Complexity", ects=Decimal("8"), grade="A"),
            CourseRecord(title="Discrete Mathematics", ects=Decimal("6"), grade="B+"),
        ),
        language_evidence=(_lang("English", "IELTS 7.0"),),
    )
    checked = program_requirements(prog, cycle="2027", profile=profile)
    statuses = [item.status for item in checked.applicant]
    assert any(
        "Met (Theoretical Computer Science) — counted 30 / 30 ECTS:" in s
        and "Automata and Formal Languages (8 ECTS)" in s
        for s in statuses
    )
    assert any("Met — counted IELTS 7.0 against required IELTS 6.5." in s for s in statuses)


def test_bug1_disjunctive_or_subject_buckets_do_not_require_both() -> None:
    """Bug 1: 'At least 20 ECTS in Theoretical CS or at least 20 ECTS in Mathematics'
    must be evaluated with OR semantics, not AND."""
    profile = _make_profile(
        courses=(
            CourseRecord(title="Linear Algebra", ects=Decimal("8"), grade="A"),
            CourseRecord(title="Calculus I", ects=Decimal("6"), grade="A"),
            CourseRecord(title="Differential Equations", ects=Decimal("6"), grade="A"),
        )
    )
    stmt = (
        "At least 20 ECTS in Theoretical Computer Science "
        "or at least 20 ECTS in Mathematics."
    )
    rule = parse_subject_pool_rule(stmt)
    assert rule is not None
    assert rule.combinator == "OR"
    assert len(rule.buckets) == 2

    ev = evaluate_program_statement(stmt, profile)
    assert ev.outcome == "SATISFIED"
    assert " OR " in ev.status_text
    assert "Met (Mathematics) — counted 20 / 20 ECTS" in ev.status_text


def test_bug2_trailing_verbs_subject_first_german_dative_and_multi_bucket_topics() -> None:
    """Bug 2: Trailing verbs ('are required'), subject-first table phrasings
    ('Theoretical Computer Science: at least 30 ECTS'), German dative
    ('Mindestens 30 ECTS in Theoretischer Informatik'), and multi-bucket parenthetical
    topic lists must all parse cleanly into canonical buckets."""
    r1 = parse_subject_pool_rule("At least 30 ECTS in Bioinformatics are required.")
    assert r1 is not None
    assert r1.buckets[0].subject_label == "Bioinformatics"
    assert r1.buckets[0].subject_keys == ("CUSTOM:bioinformatics",)

    r1b = parse_subject_pool_rule(
        "At least 30 ECTS in Theoretical Computer Science are required."
    )
    assert r1b is not None
    assert r1b.buckets[0].subject_keys == ("THEORETICAL_CS",)

    r2 = parse_subject_pool_rule("Theoretical Computer Science: at least 30 ECTS")
    assert r2 is not None
    assert r2.buckets[0].subject_keys == ("THEORETICAL_CS",)
    assert r2.buckets[0].min_ects == Decimal("30")

    r3 = parse_subject_pool_rule("Mindestens 30 ECTS in Theoretischer Informatik.")
    assert r3 is not None
    assert r3.buckets[0].subject_keys == ("THEORETICAL_CS",)

    r4 = parse_subject_pool_rule(
        "At least 18 ECTS in Mathematics (Linear Algebra, Calculus) "
        "and 12 ECTS in Computer Science."
    )
    assert r4 is not None
    assert len(r4.buckets) == 2
    assert r4.buckets[0].subject_keys == ("MATHEMATICS",)
    assert r4.buckets[0].required_topics == ("Linear Algebra", "Calculus")
    assert r4.buckets[1].subject_keys == ("COMPUTER_SCIENCE",)


def test_bug3_broad_parent_bucket_does_not_starve_narrow_child_bucket() -> None:
    """Bug 3: When 'Computer Science' (broad parent) is listed BEFORE
    'Theoretical Computer Science' (narrow child), shared Theoretical CS courses must
    satisfy the narrower child bucket first before filling the remaining parent deficit."""
    profile = _make_profile(
        courses=(
            # 6 ECTS exclusive to general CS (Systems)
            CourseRecord(title="Operating Systems", ects=Decimal("6"), grade="1.3"),
            # 24 ECTS of Theoretical CS (also valid for general CS)
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("6"), grade="1.3"),
            CourseRecord(title="Complexity Theory", ects=Decimal("6"), grade="1.3"),
            CourseRecord(title="Computability and Logic", ects=Decimal("6"), grade="1.3"),
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("6"), grade="1.3"),
        )
    )
    stmt = (
        "At least 18 ECTS in Computer Science and "
        "at least 12 ECTS in Theoretical Computer Science."
    )
    ev = evaluate_program_statement(stmt, profile)
    assert ev.outcome == "SATISFIED"
    assert "Met (Computer Science) — counted 18 / 18 ECTS" in ev.status_text
    assert "Met (Theoretical Computer Science) — counted 12 / 12 ECTS" in ev.status_text


def test_bug4_language_evidence_type_available_by_and_moi_degree_waiver() -> None:
    """Bug 4: `LanguageEvidence.evidence_type`, `available_by`, and `DEGREE` MOI waivers
    must be respected."""
    # 1. Self-attested IELTS score -> IN_PROGRESS (official certificate required)
    prof_attested = _make_profile(
        language_evidence=(
            _lang("English", "IELTS 7.0", evidence_type="ATTESTED"),
        )
    )
    ev_att = evaluate_program_statement(
        "IELTS 6.5 overall.", prof_attested, kind="LANGUAGE", as_of=dt.date(2026, 10, 1)
    )
    assert ev_att.outcome == "IN_PROGRESS"
    assert "self-attested; official test certificate required" in ev_att.status_text

    # 2. Planned future test before intended intake -> IN_PROGRESS
    prof_future = _make_profile(
        language_evidence=(
            _lang("English", "IELTS 7.0", evidence_type="TEST", available_by=dt.date(2027, 3, 1)),
        )
    )
    ev_fut = evaluate_program_statement(
        "IELTS 6.5 overall.", prof_future, kind="LANGUAGE", as_of=dt.date(2026, 10, 1)
    )
    assert ev_fut.outcome == "IN_PROGRESS"
    assert "planned by 2027-03-01" in ev_fut.status_text

    # 3. Planned test AFTER intended intake (2027-09-01) -> FAILED
    prof_late = _make_profile(
        language_evidence=(
            _lang("English", "IELTS 7.0", evidence_type="TEST", available_by=dt.date(2027, 11, 1)),
        )
    )
    ev_late = evaluate_program_statement(
        "IELTS 6.5 overall.", prof_late, kind="LANGUAGE", as_of=dt.date(2026, 10, 1)
    )
    assert ev_late.outcome == "FAILED"
    assert "after intended intake 2027-09-01" in ev_late.status_text

    # 4. Non-anglophone country (AZ) with completed English MOI degree (`evidence_type="DEGREE"`)
    prof_moi = _make_profile(
        country_code="AZ",
        completed_on=dt.date(2025, 6, 15),
        language_evidence=(
            _lang("English", "C1", evidence_type="DEGREE"),
        ),
    )
    ev_moi = evaluate_program_statement(
        "IELTS 6.5 overall, or a prior degree with English as the medium of instruction.",
        prof_moi,
        kind="LANGUAGE",
        as_of=dt.date(2026, 10, 1),
    )
    assert ev_moi.outcome == "SATISFIED"
    assert "Medium of Instruction waiver" in ev_moi.status_text

    # 5. `evidence_type="DEGREE"` does NOT satisfy an IELTS/TOEFL bar without an MOI waiver
    ev_no_moi = evaluate_program_statement(
        "IELTS 6.5 overall required.",
        prof_moi,
        kind="LANGUAGE",
        as_of=dt.date(2026, 10, 1),
    )
    assert ev_no_moi.outcome == "IN_PROGRESS"
    assert "not an official test certificate" in ev_no_moi.status_text

    # 6. Prior-degree English waiver (`evidence_type="DEGREE"`) applies only upon graduation
    prof_deg_ungrad = prof_moi.model_copy(
        update={
            "academic_history": (
                AcademicRecord(
                    institution="Example University",
                    country_code="AZ",
                    qualification="BSc",
                    field="Computer Science",
                    grade="3.7",
                    grading_scale="4.0",
                    completed_on=None,
                    expected_completion=dt.date(2027, 6, 15),
                ),
            )
        }
    )
    ev_deg_ungrad = evaluate_program_statement(
        "IELTS 6.5 overall, or a prior degree with English as the medium of instruction.",
        prof_deg_ungrad,
        kind="LANGUAGE",
        as_of=dt.date(2026, 10, 1),
    )
    assert ev_deg_ungrad.outcome == "IN_PROGRESS"
    assert "upon graduation" in ev_deg_ungrad.status_text

    # 7. With empty `language_evidence`, a non-Anglophone degree does not auto-qualify,
    # while an Anglophone degree qualifies upon graduation.
    prof_non_anglo_no_lang = prof_moi.model_copy(update={"language_evidence": ()})
    assert (
        evaluate_program_statement(
            "IELTS 6.5 overall, or a prior degree with English as the medium of instruction.",
            prof_non_anglo_no_lang,
            kind="LANGUAGE",
            as_of=dt.date(2026, 10, 1),
        ).outcome
        == "UNDECIDABLE"
    )
    prof_anglo_ungrad = prof_deg_ungrad.model_copy(
        update={
            "academic_history": (
                AcademicRecord(
                    institution="University of Manchester",
                    country_code="GB",
                    qualification="BSc",
                    field="Computer Science",
                    grade="3.7",
                    grading_scale="4.0",
                    completed_on=None,
                    expected_completion=dt.date(2027, 6, 15),
                ),
            ),
            "language_evidence": (),
        }
    )
    assert (
        evaluate_program_statement(
            "IELTS 6.5 overall, or a prior degree with English as the medium of instruction.",
            prof_anglo_ungrad,
            kind="LANGUAGE",
            as_of=dt.date(2026, 10, 1),
        ).outcome
        == "IN_PROGRESS"
    )


def test_bug5_french_20_italian_30_and_composite_failing_grades_filtered() -> None:
    """Bug 5: French 20-point (<10), Italian 30-point (<18), and composite failing grade strings
    ('F (0.0)', 'FF - Kaldı', 'W (Withdrawn)') must be recognized as failing/withdrawn."""
    assert is_failing_or_withdrawn_grade("F (0.0)", "4.0")
    assert is_failing_or_withdrawn_grade("FF - Kaldı", "4.0")
    assert is_failing_or_withdrawn_grade("W (Withdrawn)", "4.0")
    assert is_failing_or_withdrawn_grade("8.5", "20")
    assert not is_failing_or_withdrawn_grade("12.0", "20")
    assert is_failing_or_withdrawn_grade("16", "30")
    assert not is_failing_or_withdrawn_grade("28", "30")


def test_bug6_graduation_cutoff_date_and_recency_window() -> None:
    """Bug 6: Graduation cutoff dates ('degree must be completed by 2027-07-01') and
    graduation recency windows ('graduated no more than 3 years ago') are checked against
    `AcademicRecord.completed_on` and `expected_completion`."""
    prof_expected_ok = _make_profile(expected_completion=dt.date(2027, 6, 15))
    ev_ok = evaluate_program_statement(
        "The Bachelor's degree must be completed by 2027-07-01.", prof_expected_ok
    )
    assert ev_ok.outcome == "IN_PROGRESS"
    assert "on or before 2027-07-01 cutoff" in ev_ok.status_text

    prof_expected_late = _make_profile(expected_completion=dt.date(2027, 8, 15))
    ev_late = evaluate_program_statement(
        "The Bachelor's degree must be completed by 1 July 2027.", prof_expected_late
    )
    assert ev_late.outcome == "FAILED"
    assert "after 2027-07-01 cutoff" in ev_late.status_text

    prof_old_grad = _make_profile(completed_on=dt.date(2020, 6, 1))
    ev_rec_fail = evaluate_program_statement(
        "Applicants must have graduated no more than 3 years ago.",
        prof_old_grad,
        as_of=dt.date(2026, 10, 1),
    )
    assert ev_rec_fail.outcome == "FAILED"
    assert "exceeds" in ev_rec_fail.status_text or "vs. 3-year limit" in ev_rec_fail.status_text

    prof_recent_grad = _make_profile(completed_on=dt.date(2025, 6, 1))
    ev_rec_ok = evaluate_program_statement(
        "Applicants must have graduated no more than 3 years ago.",
        prof_recent_grad,
        as_of=dt.date(2026, 10, 1),
    )
    assert ev_rec_ok.outcome == "SATISFIED"


def test_item_c_us_quarter_hours_and_ru_zet_in_subject_pool_rules() -> None:
    """Item C: `US_QUARTER_HOUR` (45/year -> 4/3 ECTS) and `RU_ZET` (60/year -> 1.0 ECTS)
    convert stated credit rules to ECTS cleanly."""
    r_qh = parse_subject_pool_rule(
        "At least 15 US quarter hours in Theoretical Computer Science."
    )
    assert r_qh is not None
    assert r_qh.buckets[0].min_ects == Decimal("20.00")

    r_zet = parse_subject_pool_rule("At least 30 ЗЕТ in Theoretical Computer Science.")
    assert r_zet is not None
    assert r_zet.buckets[0].min_ects == Decimal("30.00")


def test_item_b1_course_description_resolves_opaque_and_borderline_titles() -> None:
    """Item B1: When a course has an opaque title ('Special Topics in CS I' or
    'Elective Module 3'), its optional `description` upgrades it from `BORDERLINE`/`UNRELATED`
    to `DEFINITE` and satisfies named-topic checklists."""
    profile_without_desc = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("18"), grade="1.3"),
            CourseRecord(
                title="Special Topics in Computer Science I", ects=Decimal("6"), grade="1.3"
            ),
            CourseRecord(title="Elective Module 3", ects=Decimal("6"), grade="1.3"),
        )
    )
    ev_without = evaluate_program_statement(
        "At least 30 ECTS in Theoretical Computer Science (including Complexity Theory).",
        profile_without_desc,
    )
    assert ev_without.outcome == "FAILED"

    profile_with_desc = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("18"), grade="1.3"),
            CourseRecord(
                title="Special Topics in Computer Science I",
                ects=Decimal("6"),
                grade="1.3",
                description="Computational complexity theory, NP-completeness, and reductions.",
            ),
            CourseRecord(
                title="Elective Module 3",
                ects=Decimal("6"),
                grade="1.3",
                description="Formal verification, model checking, and temporal logic.",
            ),
        )
    )
    ev_with = evaluate_program_statement(
        "At least 30 ECTS in Theoretical Computer Science (including Complexity Theory).",
        profile_with_desc,
    )
    assert ev_with.outcome == "SATISFIED"
    assert ev_with.completed_definite_ects == Decimal("30")
    assert "Special Topics in Computer Science I (6 ECTS)" in ev_with.status_text
    assert "Elective Module 3 (6 ECTS)" in ev_with.status_text


def test_item_a1_program_facts_adjusts_academic_fit_and_gates_only_hard_non_course_bars() -> None:
    """Item A1: `program_facts` adjusts `ACADEMIC_FIT` on subject-pool rules without setting
    `confirmed_eligibility_failure=True`, while unambiguous non-course hard bars (like IELTS/GPA)
    set `confirmed_eligibility_failure=True` when `FAILED`."""
    from apps.funding.facts import program_facts

    prog = catalog.Program(
        name="M.Sc. Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="de:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    stmt_tcs = catalog.ProgramStatement(
        program=prog,
        kind="COMPETENCY",
        requirement="REQUIRED",
        text="At least 30 ECTS in Theoretical Computer Science.",
        label="Subject Credit Requirement",
    )
    stmt_ielts = catalog.ProgramStatement(
        program=prog,
        kind="LANGUAGE",
        requirement="REQUIRED",
        text="IELTS 6.5 overall.",
        label="Language Requirement",
    )

    # 1. Student short on Theoretical CS (12 / 30 ECTS), but meets IELTS (7.0 >= 6.5):
    # `confirmed_eligibility_failure` remains False (no silent hard-exclusion on course titles),
    # while `ACADEMIC_FIT` is penalized by -15 (from 90 to 75).
    prof_short_tcs = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("12"), grade="A"),
        ),
        language_evidence=(_lang("English", "IELTS 7.0"),),
    )
    facts_short = program_facts(
        prog,
        costs=(),
        benefits=(),
        rules=(),
        profile=prof_short_tcs,
        statements=(stmt_tcs, stmt_ielts),
    )
    assert facts_short.confirmed_eligibility_failure is False
    assert facts_short.dimension_scores["ACADEMIC_FIT"] == Decimal("75")

    # 2. Student satisfies Theoretical CS (30 / 30 ECTS) and IELTS (7.0 >= 6.5):
    # `ACADEMIC_FIT` gets +5 bonus (from 90 to 95).
    prof_full_tcs = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("15"), grade="A"),
            CourseRecord(title="Algorithms and Complexity Theory", ects=Decimal("15"), grade="A"),
        ),
        language_evidence=(_lang("English", "IELTS 7.0"),),
    )
    facts_full = program_facts(
        prog,
        costs=(),
        benefits=(),
        rules=(),
        profile=prof_full_tcs,
        statements=(stmt_tcs, stmt_ielts),
    )
    assert facts_full.confirmed_eligibility_failure is False
    assert facts_full.dimension_scores["ACADEMIC_FIT"] == Decimal("95")

    # 3. Student fails unambiguous non-course bar (IELTS 6.0 < 6.5):
    # `confirmed_eligibility_failure` becomes True.
    prof_fail_ielts = _make_profile(
        courses=(
            CourseRecord(title="Automata and Formal Languages", ects=Decimal("30"), grade="A"),
        ),
        language_evidence=(_lang("English", "IELTS 6.0"),),
    )
    facts_fail_ielts = program_facts(
        prog,
        costs=(),
        benefits=(),
        rules=(),
        profile=prof_fail_ielts,
        statements=(stmt_tcs, stmt_ielts),
    )
    assert facts_fail_ielts.confirmed_eligibility_failure is True


# ---------------------------------------------------------------------------
# Pass 2: Bugs A–F & Brainstorm Items 1 & 2
# ---------------------------------------------------------------------------


def test_pass2_bug_a_combined_pool_does_not_double_count_subfloor_ects() -> None:
    stmt = (
        "At least 60 ECTS in Computer Science and Mathematics combined, "
        "thereof at least 20 ECTS in Mathematics."
    )
    rule = parse_subject_pool_rule(stmt)
    assert rule is not None
    assert rule.pool_min_ects == Decimal("60")

    prof = _make_profile(
        courses=(
            CourseRecord(title="Linear Algebra", ects=Decimal("25"), grade="A"),
            CourseRecord(title="Operating Systems", ects=Decimal("35"), grade="A"),
        ),
    )
    ev = evaluate_subject_pool_rule(rule, normalize_transcript_courses(prof))
    assert ev.outcome == "SATISFIED"
    # Must report 60 / 60 ECTS (the combined pool), NOT 85 / 80 ECTS (pool + sub-floor)
    assert ev.completed_definite_ects == Decimal("60")
    assert ev.required_ects == Decimal("60")


def test_pass2_bug_b_multiple_language_evidence_entries_pick_best_outcome() -> None:
    # Student has an old failed IELTS 6.0 first and a newer passing IELTS 7.0 second
    prof = _make_profile(
        language_evidence=(
            _lang("English", "IELTS 6.0", evidence_type="TEST"),
            _lang("English", "IELTS 7.0", evidence_type="TEST"),
        ),
    )
    ev = evaluate_program_statement(
        "Minimum IELTS 6.5 or TOEFL iBT 95 required.",
        prof,
    )
    assert ev.outcome == "SATISFIED"
    assert "IELTS 7.0" in ev.status_text


def test_pass2_bug_c_multiple_academic_records_and_partial_transcript_in_program_facts() -> None:
    from apps.funding.facts import program_facts

    # 1. Multiple degrees: student has a low first degree (2.8/4.0) and a high BSc (3.7/4.0)
    rec_low = AcademicRecord(
        institution="State College",
        country_code="US",
        qualification="Bachelor of Arts",
        field="History",
        grade="2.8",
        grading_scale="4.0",
    )
    rec_high = AcademicRecord(
        institution="Tech University",
        country_code="US",
        qualification="Bachelor of Science",
        field="Computer Science",
        grade="3.7",
        grading_scale="4.0",
    )
    prof = StudentProfileSnapshot(
        nationality="AZ",
        country_of_residence="AZ",
        date_of_birth=dt.date(2002, 5, 15),
        target_field="Computer Science",
        intended_intake=dt.date(2027, 9, 1),
        acceptable_teaching_languages=("English", "German"),
        career_intent="WORK_ABROAD",
        application_budget=Money(amount=Decimal("500"), currency="EUR"),
        funding_dependency="MANDATORY",
        strategy="FUNDING_FIRST",
        academic_history=(rec_low, rec_high),
        language_evidence=(),
        experience=(),
    )
    ev = evaluate_program_statement("Minimum GPA of 3.2 on a 4.0 scale.", prof)
    assert ev.outcome == "SATISFIED"
    assert "3.7 / 4.0" in ev.status_text

    # 2. Partial transcript against "Bachelor's degree with 180 ECTS" does not hard-exclude
    prog = catalog.Program(
        name="MSc Data Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="de:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    stmt_180 = catalog.ProgramStatement(
        program=prog,
        kind="COMPETENCY",
        requirement="REQUIRED",
        text="A Bachelor's degree with at least 180 ECTS credits.",
        label="Degree Credits",
    )
    prof_partial = _make_profile(
        courses=(
            CourseRecord(title="Linear Algebra", ects=Decimal("30"), grade="A"),
        ),
    )
    facts = program_facts(
        prog,
        costs=(),
        benefits=(),
        rules=(),
        profile=prof_partial,
        statements=(stmt_180,),
    )
    assert facts.confirmed_eligibility_failure is False


def test_pass2_bug_d_and_f_compound_statement_evaluates_all_clauses_conjunctively() -> None:
    stmt = (
        "Applicants need at least 30 ECTS in Computer Science, "
        "a minimum GPA of 3.0 on a 4.0 scale, and IELTS 6.5."
    )
    # 1. All 3 satisfied -> SATISFIED
    prof_ok = _make_profile(
        courses=(
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("30"), grade="A"),
        ),
        grade="3.5",
        grading_scale="4.0",
        language_evidence=(_lang("English", "IELTS 7.0"),),
    )
    ev_ok = evaluate_program_statement(stmt, prof_ok)
    assert ev_ok.outcome == "SATISFIED"
    assert "30 / 30 ECTS" in ev_ok.status_text
    assert "3.5 / 4.0" in ev_ok.status_text
    assert "IELTS 7.0" in ev_ok.status_text

    # 2. Coursework & GPA satisfied, but IELTS 6.0 (< 6.5) -> FAILED
    prof_fail_lang = _make_profile(
        courses=(
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("30"), grade="A"),
        ),
        grade="3.5",
        grading_scale="4.0",
        language_evidence=(_lang("English", "IELTS 6.0"),),
    )
    ev_fail = evaluate_program_statement(stmt, prof_fail_lang)
    assert ev_fail.outcome == "FAILED"
    assert "30 / 30 ECTS" in ev_fail.status_text
    assert "6.5" in ev_fail.status_text

    # 3. Compound degree credits + subject credits: both clauses evaluated
    stmt_deg_and_subj = (
        "A Bachelor's degree with 180 ECTS including at least 30 ECTS in Mathematics."
    )
    prof_deg_ok = _make_profile(
        courses=(
            CourseRecord(title="Linear Algebra and Calculus", ects=Decimal("30"), grade="A"),
            CourseRecord(title="Software Engineering", ects=Decimal("90"), grade="A"),
            CourseRecord(title="Operating Systems", ects=Decimal("60"), grade="A"),
        ),
    )
    ev_deg_ok = evaluate_program_statement(stmt_deg_and_subj, prof_deg_ok)
    assert ev_deg_ok.outcome == "SATISFIED"
    assert "180 / 180 total ECTS" in ev_deg_ok.status_text
    assert "30 / 30 ECTS" in ev_deg_ok.status_text


def test_pass2_bug_e_and_uk_honours_and_incomplete_transcript_hint() -> None:
    # 1. Percentage bar ("at least 75%") against 4.0 GPA scale (3.5/4.0 -> ~1.8 Bavarian vs 2.5)
    prof_us = _make_profile(
        grade="3.5",
        grading_scale="4.0",
    )
    ev_pct = evaluate_program_statement("Minimum average grade of 75% required.", prof_us)
    assert ev_pct.outcome == "SATISFIED"

    # 2. German Note bar ("2,5 or better") against Italian 110 scale (105/110 -> ~1.3 Bavarian)
    prof_it = _make_profile(
        grade="105",
        grading_scale="110",
    )
    ev_de = evaluate_program_statement(
        "A Bachelor's degree with a German grade of 2,5 or better.",
        prof_it,
    )
    assert ev_de.outcome == "SATISFIED"
    assert "105/110" in ev_de.status_text

    # 3. UK Honours bar ("Upper Second-Class (2:1) Honours")
    ev_uk_ok = evaluate_program_statement(
        "A minimum of an Upper Second-Class (2:1) Honours degree.",
        prof_us,
    )
    assert ev_uk_ok.outcome == "SATISFIED"
    assert "Upper Second-Class Honours (2:1)" in ev_uk_ok.status_text

    prof_low = _make_profile(
        grade="2.3",
        grading_scale="4.0",
    )
    ev_uk_fail = evaluate_program_statement(
        "A minimum of an Upper Second-Class (2:1) Honours degree.",
        prof_low,
    )
    assert ev_uk_fail.outcome == "FAILED"

    # 4. Incomplete transcript hint when 0 < total_transcript_ects < 60
    prof_incomplete = _make_profile(
        courses=(
            CourseRecord(title="Automata Theory", ects=Decimal("6"), grade="A"),
        ),
    )
    ev_incomplete = evaluate_program_statement(
        "At least 30 ECTS in Theoretical Computer Science.",
        prof_incomplete,
    )
    assert ev_incomplete.outcome == "FAILED"
    assert "only 6 total ECTS are currently listed on your transcript" in ev_incomplete.status_text


# ---------------------------------------------------------------------------
# Pass 3: Bugs 1–7 & Improvements 1–3
# ---------------------------------------------------------------------------


def test_pass3_bug1_compound_statement_separates_coursework_fit_from_hard_bar_failure() -> None:
    from apps.funding.facts import program_facts

    prog = catalog.Program(
        name="MSc Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="de:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    stmt_compound = catalog.ProgramStatement(
        program=prog,
        kind="COMPETENCY",
        requirement="REQUIRED",
        text=(
            "Applicants need at least 30 ECTS in Computer Science, "
            "a minimum GPA of 3.0 on a 4.0 scale, and IELTS 6.5."
        ),
        label="Admission Requirements",
    )

    # 1. Student meets 30 ECTS in CS (30/30), but fails GPA (2.1 < 3.0) and IELTS (5.5 < 6.5):
    # `confirmed_eligibility_failure` MUST be True because the non-course hard bars failed!
    prof_fail_hard = _make_profile(
        courses=(
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("30"), grade="A"),
        ),
        grade="2.1",
        grading_scale="4.0",
        language_evidence=(_lang("English", "IELTS 5.5"),),
    )
    facts_fail_hard = program_facts(
        prog,
        costs=(),
        benefits=(),
        rules=(),
        profile=prof_fail_hard,
        statements=(stmt_compound,),
    )
    assert facts_fail_hard.confirmed_eligibility_failure is True

    # 2. Student meets 30 ECTS in CS (30/30) and GPA (3.5/4.0), while IELTS is not yet on profile:
    # `confirmed_eligibility_failure` is False AND `ACADEMIC_FIT` still gets the +5 bonus.
    prof_untested_lang = _make_profile(
        courses=(
            CourseRecord(title="Algorithms and Data Structures", ects=Decimal("30"), grade="A"),
        ),
        grade="3.5",
        grading_scale="4.0",
        language_evidence=(),
    )
    facts_untested = program_facts(
        prog,
        costs=(),
        benefits=(),
        rules=(),
        profile=prof_untested_lang,
        statements=(stmt_compound,),
    )
    assert facts_untested.confirmed_eligibility_failure is False
    assert facts_untested.dimension_scores["ACADEMIC_FIT"] == Decimal("95")


def test_pass3_bug2_and_impr2_three_bucket_comma_lists_and_semester_credit_hours() -> None:
    stmt_3 = (
        "Applicants must have completed at least 18 ECTS in Theoretical Computer Science, "
        "at least 18 ECTS in Mathematics, and at least 12 ECTS in Computer Science."
    )
    rule = parse_subject_pool_rule(stmt_3)
    assert rule is not None
    assert len(rule.buckets) == 3
    assert [b.min_ects for b in rule.buckets] == [Decimal("18"), Decimal("18"), Decimal("12")]

    # Semester credit hours (15 semester credit hours = 30 ECTS)
    rule_sch = parse_subject_pool_rule(
        "At least 15 semester credit hours in Mathematics."
    )
    assert rule_sch is not None
    assert rule_sch.buckets[0].min_ects == Decimal("30.00")


def test_pass3_bug3_cefr_tokens_in_language_level_do_not_corrupt_ielts_or_toefl() -> None:
    # 1. "C1 (IELTS 7.0)" and "IELTS 7.0 (CEFR C1)" must extract 7.0, not "1" from "C1"
    prof_c1_prefix = _make_profile(
        language_evidence=(_lang("English", "C1 (IELTS 7.0)"),),
    )
    ev1 = evaluate_program_statement(
        "Minimum IELTS 6.5 (at least 6.0 in each band).",
        prof_c1_prefix,
    )
    assert ev1.outcome == "SATISFIED"

    prof_c1_suffix = _make_profile(
        language_evidence=(_lang("English", "IELTS 7.0 (CEFR C1)"),),
    )
    ev2 = evaluate_program_statement(
        "Minimum IELTS 6.5 (at least 6.0 in each band).",
        prof_c1_suffix,
    )
    assert ev2.outcome == "SATISFIED"

    # 2. Subscore failure with "at least 6.0 in each band" phrasing
    prof_sub_fail = _make_profile(
        language_evidence=(_lang("English", "IELTS 7.0 (L 7.5, R 7.5, W 5.5, S 7.5)"),),
    )
    ev_sub_fail = evaluate_program_statement(
        "Minimum IELTS 6.5 (at least 6.0 in each band).",
        prof_sub_fail,
    )
    assert ev_sub_fail.outcome == "FAILED"

    # 3. `decide()` in `apps/funding/eligibility.py` with "C1 (TOEFL iBT 100)"
    prof_toefl = _make_profile(
        language_evidence=(_lang("English", "C1 (TOEFL iBT 100)"),),
    )
    dec = decide(
        ConditionTriple(
            key="LANGUAGE",
            operator="GTE",
            value="English TOEFL 95",
            quote="TOEFL iBT 95",
        ),
        prof_toefl,
    )
    assert dec.outcome == "SATISFIED"


def test_pass3_bug4_combined_pool_includes_parent_courses_and_degree_preface_skipped() -> None:
    # 1. Combined pool `counted_courses` includes both Math (25 ECTS) and CS (35 ECTS) courses
    rule = parse_subject_pool_rule(
        "At least 60 ECTS in Computer Science and Mathematics combined, "
        "thereof at least 20 ECTS in Mathematics."
    )
    assert rule is not None
    prof = _make_profile(
        courses=(
            CourseRecord(title="Linear Algebra", ects=Decimal("25"), grade="A"),
            CourseRecord(title="Operating Systems", ects=Decimal("35"), grade="A"),
        ),
    )
    ev = evaluate_subject_pool_rule(rule, normalize_transcript_courses(prof))
    assert ev.outcome == "SATISFIED"
    assert {c.title for c in ev.counted_courses} == {"Linear Algebra", "Operating Systems"}

    # 2. "At least 180 ECTS in a Bachelor's degree, including at least 30 ECTS in Mathematics"
    stmt_deg_comma = (
        "At least 180 ECTS in a Bachelor's degree, including at least 30 ECTS in Mathematics."
    )
    prof_deg = _make_profile(
        courses=(
            CourseRecord(title="Linear Algebra", ects=Decimal("30"), grade="A"),
            CourseRecord(title="Operating Systems", ects=Decimal("90"), grade="A"),
            CourseRecord(title="Databases", ects=Decimal("60"), grade="A"),
        ),
    )
    ev_deg = evaluate_program_statement(stmt_deg_comma, prof_deg)
    assert ev_deg.outcome == "SATISFIED"


def test_pass3_bug5_gre_waiver_checks_scale_and_evaluates_mandatory_gpa_clause() -> None:
    # 1. 55% on a 100-point scale must NOT trigger a 3.5/4.0 GPA waiver for GRE
    prof_55_pct = _make_profile(grade="55", grading_scale="100")
    ev_no_waiver = evaluate_program_statement(
        "GRE Quantitative score of at least 160 "
        "(waived for applicants with a GPA of at least 3.5).",
        prof_55_pct,
    )
    assert ev_no_waiver.outcome == "UNDECIDABLE"

    # 2. Mandatory GPA clause alongside GRE requirement is still evaluated
    prof_low_gpa = _make_profile(grade="2.5", grading_scale="4.0")
    ev_mand_gpa = evaluate_program_statement(
        "Minimum GPA of 3.2 on a 4.0 scale and GRE Quantitative score of at least 160.",
        prof_low_gpa,
    )
    assert ev_mand_gpa.outcome == "FAILED"
    assert "Not met — counted GPA/grade 2.5 / 4.0" in ev_mand_gpa.status_text


def test_pass3_bug6_and_7_scraper_table_and_competency_extraction_and_impr1_3() -> None:
    # 1. Scraper extracts table-row subject credit requirement and UK Honours / work experience
    html = """
    <html><body>
      <h2>Admission Requirements</h2>
      <table>
        <tr><th>Theoretical Computer Science</th><td>at least 30 ECTS</td></tr>
      </table>
      <p>Applicants must hold an Upper Second-Class (2:1) Honours degree.</p>
      <p>At least 2 years of relevant professional work experience.</p>
    </body></html>
    """
    bundle = build_programme_bundle([("https://uni.example.edu/msc", html)])
    res = extract_tier0_programme_facts(bundle)
    stmt_texts = [s.text for s in res.statements if s.kind == "COMPETENCY"]
    assert any("Theoretical Computer Science: at least 30 ECTS" in t for t in stmt_texts)
    assert any("Upper Second-Class (2:1) Honours" in t for t in stmt_texts)
    assert any("2 years of relevant professional work experience" in t for t in stmt_texts)

    # 2. Improvement 3: Korean 4.5 GPA scale converts via Bavarian formula
    prof_kr = _make_profile(grade="4.2", grading_scale="4.5", country_code="KR")
    ev_kr = evaluate_program_statement("German grade of 2.0 or better.", prof_kr)
    assert ev_kr.outcome == "SATISFIED"

    # 3. Improvement 1: Shared in-progress courses split across sibling buckets without hoarding
    rule_shared = parse_subject_pool_rule(
        "At least 12 ECTS in Theoretical Computer Science and at least 12 ECTS in Mathematics."
    )
    assert rule_shared is not None
    prof_ip_shared = _make_profile(
        courses=(
            CourseRecord(
                title="Automata Theory",
                ects=Decimal("12"),
                grade=None,
                in_progress=True,
            ),
            CourseRecord(
                title="Discrete Mathematics and Graph Theory",
                ects=Decimal("12"),
                grade=None,
                in_progress=True,
            ),
        ),
    )
    ev_ip = evaluate_subject_pool_rule(rule_shared, normalize_transcript_courses(prof_ip_shared))
    assert ev_ip.outcome == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Pass 4: System-to-System GPA / Grade Conversion (Bugs 1–5)
# ---------------------------------------------------------------------------


def test_pass4_bug1_and_2_range_prose_scales_and_composite_grade_strings() -> None:
    # 1. Range scale "0-100" and "1-100" against US 4.0 GPA bar (85/100 -> ~1.9 Bavarian <= 2.5)
    prof_0_100 = _make_profile(grade="85", grading_scale="0-100", country_code="AZ")
    ev1 = evaluate_program_statement("Minimum GPA of 3.0 on a 4.0 scale.", prof_0_100)
    assert ev1.outcome == "SATISFIED"
    assert "Bavarian" in ev1.status_text

    # 2. Explicit passing floor in range "60-100" vs "50-100":
    # 75 on "60-100" has Bavarian 1 + 3*(100-75)/(100-60) = 2.9, while on "50-100" it is 2.5
    assert convert_grade_to_bavarian("75", "60-100") == Decimal("2.9")
    assert convert_grade_to_bavarian("75", "50-100") == Decimal("2.5")

    # 3. Prose scale "out of 100" and composite grade "16.45/20.0 (Highest Honors)"
    prof_fr = _make_profile(
        grade="16.45/20.0 (Highest Honors)",
        grading_scale="0-20",
        country_code="FR",
    )
    ev_fr = evaluate_program_statement("German grade of 2.3 or better.", prof_fr)
    assert ev_fr.outcome == "SATISFIED"
    assert "16.45" in ev_fr.status_text

    prof_out_of_100 = _make_profile(grade="88/100", grading_scale="out of 100")
    ev_out = evaluate_program_statement("Minimum GPA of 3.2 on a 4.0 scale.", prof_out_of_100)
    assert ev_out.outcome == "SATISFIED"


def test_pass4_bug3_bidirectional_german_and_uk_honours_to_us_gpa_and_pct() -> None:
    # 1. German inverted grade 1.7 on "1.0-5.0" satisfies US 3.0/4.0 GPA bar and 75% bar
    prof_de_good = _make_profile(grade="1.7", grading_scale="1.0-5.0", country_code="DE")
    ev_de_to_us = evaluate_program_statement("Minimum GPA of 3.0 on a 4.0 scale.", prof_de_good)
    assert ev_de_to_us.outcome == "SATISFIED"
    assert "1.7/1.0-5.0" in ev_de_to_us.status_text

    ev_de_to_pct = evaluate_program_statement(
        "Minimum average grade of 75% required.", prof_de_good
    )
    assert ev_de_to_pct.outcome == "SATISFIED"

    # 2. German inverted grade 3.3 on "1.0-5.0" FAILS US 3.0/4.0 GPA bar (2.5 Bavarian)
    prof_de_low = _make_profile(grade="3.3", grading_scale="1.0-5.0", country_code="DE")
    ev_de_fail = evaluate_program_statement("Minimum GPA of 3.0 on a 4.0 scale.", prof_de_low)
    assert ev_de_fail.outcome == "FAILED"

    # 3. UK Honours ("First-Class Honours" and "2:1") satisfy US 3.0/4.0 GPA bar and German 2.5 bar
    prof_uk_21 = _make_profile(
        grade="Upper Second-Class Honours (2:1)",
        grading_scale="UK Honours",
        country_code="GB",
    )
    ev_uk_to_us = evaluate_program_statement("Minimum GPA of 3.0 on a 4.0 scale.", prof_uk_21)
    assert ev_uk_to_us.outcome == "SATISFIED"

    ev_uk_to_de = evaluate_program_statement("German grade of 2.5 or better.", prof_uk_21)
    assert ev_uk_to_de.outcome == "SATISFIED"

    # 4. Inverse helper `convert_bavarian_to_us_gpa`
    assert convert_bavarian_to_us_gpa(Decimal("1.0")) == Decimal("4.00")
    assert convert_bavarian_to_us_gpa(Decimal("2.5")) == Decimal("3.00")
    assert convert_bavarian_to_us_gpa(Decimal("4.0")) == Decimal("2.00")


def test_pass4_bug4_country_aware_uk_pct_swiss_6_dutch_10_chinese_and_az_100() -> None:
    # 1. UK 65% (country_code="GB", solid 2:1 -> 2.0 Bavarian) satisfies US 3.0/4.0 GPA bar (2.5)
    # and continental 75% bar (2.5 Bavarian)
    prof_uk_65 = _make_profile(grade="65", grading_scale="0-100", country_code="GB")
    assert convert_grade_to_bavarian("65", "0-100", country_code="GB") == Decimal("2.0")
    ev_uk_65_gpa = evaluate_program_statement("Minimum GPA of 3.0 on a 4.0 scale.", prof_uk_65)
    assert ev_uk_65_gpa.outcome == "SATISFIED"
    ev_uk_65_pct = evaluate_program_statement(
        "Minimum average grade of 75% required.", prof_uk_65
    )
    assert ev_uk_65_pct.outcome == "SATISFIED"

    # 2. Swiss 1.0-6.0 scale (6.0 best, 4.0 pass): 5.2/6.0 -> 2.2 Bavarian <= 2.5
    prof_ch = _make_profile(grade="5.2", grading_scale="1.0-6.0", country_code="CH")
    assert convert_grade_to_bavarian("5.2", "1.0-6.0", country_code="CH") == Decimal("2.2")
    ev_ch = evaluate_program_statement("Minimum GPA of 3.0 on a 4.0 scale.", prof_ch)
    assert ev_ch.outcome == "SATISFIED"

    # 3. Dutch 10.0 scale (country_code="NL"): 7.5/10 -> 2.0 Bavarian <= 2.5
    prof_nl = _make_profile(grade="7.5", grading_scale="10", country_code="NL")
    assert convert_grade_to_bavarian("7.5", "10", country_code="NL") == Decimal("2.0")
    ev_nl = evaluate_program_statement("Minimum GPA of 3.0 on a 4.0 scale.", prof_nl)
    assert ev_nl.outcome == "SATISFIED"

    # 4. Chinese 100-point scale (min_pass=60) and Azerbaijani 100-point scale (min_pass=51)
    assert convert_grade_to_bavarian("80", "100", country_code="CN") == Decimal("2.5")
    assert convert_grade_to_bavarian("50", "100", country_code="AZ") == Decimal("5.0")


def test_pass4_bug5_letter_grade_bars_and_letter_grade_records() -> None:
    # 1. Programme requires "Minimum average grade of B+ or better" (3.3 / 4.0)
    prof_a_minus = _make_profile(grade="A-", grading_scale="A-F", country_code="US")
    ev_ok = evaluate_program_statement(
        "Applicants must have a minimum average grade of B+ or better.",
        prof_a_minus,
    )
    assert ev_ok.outcome == "SATISFIED"
    assert "3.7 / 4.0" in ev_ok.status_text

    prof_b = _make_profile(grade="B", grading_scale="A-F", country_code="US")
    ev_fail = evaluate_program_statement(
        "Applicants must have a minimum average grade of B+ or better.",
        prof_b,
    )
    assert ev_fail.outcome == "FAILED"

    # 2. Student with letter grade "A-" satisfies German grade 2.5 bar (~1.5 Bavarian)
    ev_letter_to_de = evaluate_program_statement("German grade of 2.5 or better.", prof_a_minus)
    assert ev_letter_to_de.outcome == "SATISFIED"


def test_pass5_bug1_and_5_turkish_yuksek_lisans_degree_abbrs_and_same_scale_aliases() -> None:
    from apps.funding.eligibility import _degree_level

    # 1. Turkish "Yüksek Lisans" resolves to MASTER (not BACHELOR via substring "lisans")
    assert _degree_level("Yüksek Lisans") == "MASTER"
    assert _degree_level("Tezli Yüksek Lisans") == "MASTER"
    assert _degree_level("Lisans") == "BACHELOR"

    # 2. Bounded degree abbreviations and AZ/RU titles
    assert _degree_level("BA in Economics") == "BACHELOR"
    assert _degree_level("BS in Computer Science") == "BACHELOR"
    assert _degree_level("BEng in Mechanical Engineering") == "BACHELOR"
    assert _degree_level("LLB") == "BACHELOR"
    assert _degree_level("MA in History") == "MASTER"
    assert _degree_level("MS in Data Science") == "MASTER"
    assert _degree_level("MEng") == "MASTER"
    assert _degree_level("MBA") == "MASTER"
    assert _degree_level("LLM") == "MASTER"
    assert _degree_level("PhD in Physics") == "DOCTORATE"
    assert _degree_level("DPhil") == "DOCTORATE"
    assert _degree_level("Bakalavr") == "BACHELOR"
    assert _degree_level("Magistr") == "MASTER"
    assert _degree_level("Бакалавр") == "BACHELOR"
    assert _degree_level("Магистр") == "MASTER"
    assert _degree_level("Специалист") == "MASTER"
    assert _degree_level("Кандидат наук") == "DOCTORATE"

    # 3. Same-scale GRADE decision handles range/prose scale strings and composite grades
    prof_tr_ms = _make_profile(
        qualification="Yüksek Lisans",
        field="Computer Engineering",
        grade="88/100 (High Honor)",
        grading_scale="0-100",
        country_code="TR",
    )
    dec_deg = decide(
        ConditionTriple(key="PRIOR_DEGREE", operator="GTE", value="MASTER", quote="Master's"),
        prof_tr_ms,
    )
    assert dec_deg.outcome == "SATISFIED"

    dec_grade = decide(
        ConditionTriple(key="GRADE", operator="GTE", value="80 on 100", quote="min 80/100"),
        prof_tr_ms,
    )
    assert dec_grade.outcome == "SATISFIED"


def test_pass5_bug2_prior_degree_field_does_not_match_aspirational_target_field() -> None:
    # Student has a Bachelor's in History, but wants to pivot into a Master's in Computer Science
    prof_pivot = StudentProfileSnapshot(
        nationality="AZ",
        country_of_residence="AZ",
        date_of_birth=dt.date(2002, 5, 15),
        target_field="Computer Science",
        intended_intake=dt.date(2027, 9, 1),
        acceptable_teaching_languages=("English", "German"),
        career_intent="WORK_ABROAD",
        application_budget=Money(amount=Decimal("500"), currency="EUR"),
        funding_dependency="MANDATORY",
        strategy="FUNDING_FIRST",
        academic_history=(
            AcademicRecord(
                institution="Baku State University",
                country_code="AZ",
                qualification="Bachelor of Arts",
                field="History",
                grade="90",
                grading_scale="100",
                completed_on=dt.date(2024, 6, 30),
            ),
        ),
        language_evidence=(),
        experience=(),
    )
    ev = evaluate_program_statement(
        "Applicants must hold a Bachelor's degree in Computer Science or Mathematics.",
        prof_pivot,
    )
    assert ev.outcome == "BORDERLINE"
    assert "History" in ev.status_text

    # Student with a prior degree in Informatics satisfies Computer Science via taxonomy
    prof_cs = _make_profile(field="Informatics")
    ev_cs = evaluate_program_statement(
        "Applicants must hold a Bachelor's degree in Computer Science or Mathematics.",
        prof_cs,
    )
    assert ev_cs.outcome == "SATISFIED"
    assert "Informatics" in ev_cs.status_text


def test_pass5_bug3_not_stated_scale_inference_and_transcript_course_average_fallback() -> None:
    # 1. `grading_scale="not stated"` with `grade="86"` and `country_code="AZ"` infers 100 scale
    prof_unstated_scale = _make_profile(
        grade="86",
        grading_scale="not stated",
        country_code="AZ",
    )
    ev_scale = evaluate_program_statement(
        "Minimum GPA of 3.0 on a 4.0 scale.", prof_unstated_scale
    )
    assert ev_scale.outcome == "SATISFIED"

    # 2. Both `grade="not stated"` and `grading_scale="not stated"` fall back to ECTS-weighted
    # average of passing completed transcript courses
    prof_unstated_both = _make_profile(
        courses=(
            CourseRecord(title="Algorithms", ects=Decimal("6"), grade="90"),
            CourseRecord(title="Operating Systems", ects=Decimal("6"), grade="86"),
        ),
        grade="not stated",
        grading_scale="not stated",
        country_code="AZ",
    )
    ev_avg = evaluate_program_statement(
        "Minimum average grade of 85% required.", prof_unstated_both
    )
    assert ev_avg.outcome == "SATISFIED"
    assert "88" in ev_avg.status_text


def test_pass5_bug4_country_aware_course_pass_fail_uk_45_cn_55_az_50_and_composite() -> None:
    # 1. UK 45% (Third-Class pass >= 40%) is preserved as passing course credit
    assert is_failing_or_withdrawn_grade("45%", "0-100", country_code="GB") is False
    assert is_failing_or_withdrawn_grade("38%", "0-100", country_code="GB") is True

    # 2. Chinese 55/100 (< 60 pass floor) and Azerbaijani 50/100 (< 51 pass floor) are failing
    assert is_failing_or_withdrawn_grade("55", "100", country_code="CN") is True
    assert is_failing_or_withdrawn_grade("62", "100", country_code="CN") is False
    assert is_failing_or_withdrawn_grade("50", "100", country_code="AZ") is True
    assert is_failing_or_withdrawn_grade("51", "100", country_code="AZ") is False

    # 3. Swiss 3.5 (< 4.0 pass floor) and Dutch 5.0 (< 5.5 pass floor) are failing
    assert is_failing_or_withdrawn_grade("3.5", "1.0-6.0", country_code="CH") is True
    assert is_failing_or_withdrawn_grade("4.0", "1.0-6.0", country_code="CH") is False
    assert is_failing_or_withdrawn_grade("5.0", "10", country_code="NL") is True
    assert is_failing_or_withdrawn_grade("5.5", "10", country_code="NL") is False

    # 4. Composite course grades ("45/100", "8.5/20", "5.0 (mangelhaft)") are detected as failing,
    # while US "1.0" (D) on 4.0 GPA scale is preserved as a passing single course
    assert is_failing_or_withdrawn_grade("45/100", None) is True
    assert is_failing_or_withdrawn_grade("8.5/20", None) is True
    assert is_failing_or_withdrawn_grade("5.0 (mangelhaft)", "German 1-5") is True
    assert is_failing_or_withdrawn_grade("1.0", "4.0", country_code="US") is False


def test_pass5_bug6_toefl_subscores_and_pte_duolingo_cambridge_testdaf_dsh() -> None:
    # 1. TOEFL overall meets bar (96 >= 92), but Speaking section (19 < 22) fails subscore bar
    prof_toefl_sub_fail = _make_profile(
        language_evidence=(
            _lang("English", "TOEFL iBT 96 (R:26, L:25, S:19, W:26)"),
        )
    )
    ev_toefl_sub = evaluate_program_statement(
        "English proficiency: TOEFL iBT 92 with at least 22 in each section.",
        prof_toefl_sub_fail,
    )
    assert ev_toefl_sub.outcome == "FAILED"
    assert "lowest section 19 is below required 22" in ev_toefl_sub.status_text

    # 2. Combined IELTS + TOEFL bar: IELTS subscore 6.0 does not falsely trigger on TOEFL 96
    ev_combined = evaluate_program_statement(
        "IELTS 6.5 (no band below 6.0) or TOEFL iBT 92.",
        prof_toefl_sub_fail,
    )
    assert ev_combined.outcome == "SATISFIED"

    # 3. PTE Academic and Duolingo English Test direct and cross-test CEFR checks
    prof_pte = _make_profile(
        language_evidence=(_lang("English", "PTE Academic 68"),)
    )
    assert (
        evaluate_program_statement("Minimum PTE Academic 65.", prof_pte).outcome == "SATISFIED"
    )
    assert (
        evaluate_program_statement("English at CEFR B2 level required.", prof_pte).outcome
        == "SATISFIED"
    )

    prof_duo = _make_profile(
        language_evidence=(_lang("English", "Duolingo 130"),)
    )
    assert (
        evaluate_program_statement("Duolingo English Test 120 or higher.", prof_duo).outcome
        == "SATISFIED"
    )

    # 4. German TestDaF TDN 4 and DSH-2
    prof_de = _make_profile(
        language_evidence=(_lang("German", "TestDaF TDN 4 (4x4)"),)
    )
    assert (
        evaluate_program_statement("German language proficiency: TestDaF TDN 4.", prof_de).outcome
        == "SATISFIED"
    )
    assert (
        evaluate_program_statement("German proficiency: DSH-2 or equivalent.", prof_de).outcome
        == "SATISFIED"
    )


def test_pass6_seams_degree_level_language_availability_unstated_decide_grade_and_total_ects() -> (
    None
):
    # 1. Prior-degree level check in Step 8: BSc in CS fails "Master's degree in Computer Science"
    prof_bsc_cs = _make_profile(qualification="Bachelor of Science", field="Computer Science")
    ev_phd_req = evaluate_program_statement(
        "Applicants must hold a Master's degree in Computer Science.",
        prof_bsc_cs,
    )
    assert ev_phd_req.outcome == "FAILED"
    assert "below required Master degree" in ev_phd_req.status_text

    # Standalone degree-level statement without "in <field>"
    assert (
        evaluate_program_statement(
            "Applicants must hold a Bachelor's degree or equivalent.", prof_bsc_cs
        ).outcome
        == "SATISFIED"
    )
    assert (
        evaluate_program_statement(
            "Applicants must hold a Master's degree or equivalent.", prof_bsc_cs
        ).outcome
        == "FAILED"
    )

    # 2. `decide(key="LANGUAGE")` rejects test results arriving after `intended_intake`,
    # and `_evaluate_language_statement` accepts native / MOI degree evidence on CEFR bars
    prof_late_lang = _make_profile(
        language_evidence=(
            _lang("English", "IELTS 7.5", available_by=dt.date(2028, 1, 15)),
        )
    )
    dec_late = decide(
        ConditionTriple(key="LANGUAGE", operator="GTE", value="English B2", quote="English B2"),
        prof_late_lang,
    )
    assert dec_late.outcome == "FAILED"
    assert "after intended intake" in dec_late.reason

    prof_moi_deg = _make_profile(
        completed_on=dt.date(2025, 6, 15),
        language_evidence=(
            _lang("English", "Medium of instruction", evidence_type="DEGREE"),
        ),
    )
    assert (
        evaluate_program_statement("English proficiency at CEFR C1.", prof_moi_deg).outcome
        == "SATISFIED"
    )

    # 3. `decide(key="GRADE")` resolves `grading_scale="not stated"` and `grade="not stated"`
    prof_unstated = _make_profile(
        courses=(
            CourseRecord(title="Algorithms", ects=Decimal("6"), grade="90"),
            CourseRecord(title="Databases", ects=Decimal("6"), grade="86"),
        ),
        grade="not stated",
        grading_scale="not stated",
        country_code="AZ",
    )
    dec_unstated = decide(
        ConditionTriple(key="GRADE", operator="GTE", value="85 on 100", quote="min 85/100"),
        prof_unstated,
    )
    assert dec_unstated.outcome == "SATISFIED"

    # 4. Wider `_TOTAL_DEGREE_CREDITS_RE` matches "Bachelor's degree in CS with at least 180 ECTS"
    # and standalone "minimum of 180 ECTS credits"
    prof_180 = _make_profile(
        courses=(
            CourseRecord(title="Year 1 & 2 Modules", ects=Decimal("90"), grade="88"),
            CourseRecord(title="Year 3 Modules & Thesis", ects=Decimal("90"), grade="90"),
        )
    )
    assert (
        evaluate_program_statement(
            "Bachelor's degree in Computer Science with at least 180 ECTS.", prof_180
        ).outcome
        == "SATISFIED"
    )
    assert (
        evaluate_program_statement(
            "Applicants must have completed a minimum of 180 ECTS credits.", prof_180
        ).outcome
        == "SATISFIED"
    )


def test_pass7_scholarship_status_statements_and_tier0_scraper() -> None:
    from apps.funding.transcript_eligibility import (
        is_program_scholarship_suspended_for_intake,
        parse_scholarship_status_statement,
    )
    from apps.research.programme_scraper import (
        build_programme_bundle,
        extract_tier0_programme_facts,
    )

    # 1. ChEMoinformatics+ exact sentence and date-stamp safety
    chemo_text = (
        "Updated 15/10/2025: The recruitment of the 2027-2029 student intake "
        "will be without scholarship."
    )
    parsed_chemo = parse_scholarship_status_statement(chemo_text)
    assert parsed_chemo == ("NO_SCHOLARSHIP", "2027-2029")
    assert is_program_scholarship_suspended_for_intake(chemo_text, 2027) is True
    assert is_program_scholarship_suspended_for_intake(chemo_text, 2025) is False

    # 2. Self-funded only, multi-intake ("2026 and 2027"), and open-ended ("from 2027 onwards")
    self_funded_text = (
        "Applications for the 2027/2028 intake are open to self-funded students only."
    )
    assert is_program_scholarship_suspended_for_intake(self_funded_text, 2027) is True
    assert is_program_scholarship_suspended_for_intake(self_funded_text, 2028) is False

    multi_text = "No scholarships will be offered for the 2026 and 2027 intakes."
    assert is_program_scholarship_suspended_for_intake(multi_text, 2026) is True
    assert is_program_scholarship_suspended_for_intake(multi_text, 2027) is True
    assert is_program_scholarship_suspended_for_intake(multi_text, 2028) is False

    onwards_text = "From 2027 onwards, the programme will run without scholarship."
    assert is_program_scholarship_suspended_for_intake(onwards_text, 2026) is False
    assert is_program_scholarship_suspended_for_intake(onwards_text, 2027) is True
    assert is_program_scholarship_suspended_for_intake(onwards_text, 2029) is True

    # 3. Full scholarship suspended while consortium tuition waivers remain offered
    partial_text = (
        "No Erasmus Mundus scholarships are available for the 2027-2029 intake; "
        "however, consortium tuition waivers are offered."
    )
    parsed_partial = parse_scholarship_status_statement(partial_text)
    assert parsed_partial == ("NO_FULL_SCHOLARSHIP", "2027-2029")
    assert (
        is_program_scholarship_suspended_for_intake(
            partial_text, 2027, money_form="GRANT"
        )
        is True
    )
    assert (
        is_program_scholarship_suspended_for_intake(
            partial_text, 2027, money_form="FEE_WAIVER"
        )
        is False
    )

    # 4. Pending EACEA grant renewal
    pending_text = (
        "Erasmus Mundus scholarships for the 2027-2029 intake are subject to EACEA grant renewal."
    )
    parsed_pending = parse_scholarship_status_statement(pending_text)
    assert parsed_pending == ("PENDING_RENEWAL", "2027-2029")
    assert is_program_scholarship_suspended_for_intake(pending_text, 2027) is False

    # 5. Applicant requirements pane evaluation (`include_coursework=True`)
    prof_mandatory = _make_profile().model_copy(
        update={"funding_dependency": "MANDATORY"}
    )
    prof_optional = _make_profile().model_copy(
        update={"funding_dependency": "OPTIONAL"}
    )

    ev_fail = evaluate_program_statement(
        chemo_text, prof_mandatory, include_coursework=True
    )
    assert ev_fail.outcome == "FAILED"
    assert "2027-2029 intake is without scholarship" in ev_fail.status_text

    ev_opt = evaluate_program_statement(
        chemo_text, prof_optional, include_coursework=True
    )
    assert ev_opt.outcome == "BORDERLINE"
    assert "2027-2029 intake is without scholarship" in ev_opt.status_text

    ev_other_intake = evaluate_program_statement(
        "The recruitment of the 2025-2027 student intake was without scholarship.",
        prof_mandatory,
        include_coursework=True,
    )
    assert ev_other_intake.outcome == "SATISFIED"

    ev_partial = evaluate_program_statement(
        partial_text, prof_mandatory, include_coursework=True
    )
    assert ev_partial.outcome == "BORDERLINE"
    assert "only partial / tuition waivers are offered" in ev_partial.status_text

    ev_pending = evaluate_program_statement(
        pending_text, prof_mandatory, include_coursework=True
    )
    assert ev_pending.outcome == "BORDERLINE"
    assert "pending external grant renewal" in ev_pending.status_text

    # 6. Tier-0 programme scraper extracts the scholarship status notice as a ProgramStatement
    bundle = build_programme_bundle(
        [
            (
                "https://masterchemoinfo.u-strasbg.fr/scholarships/",
                "<html><body><h2>Scholarship</h2><p>The recruitment of the 2027-2029 "
                "student intake will be without scholarship.</p></body></html>",
            )
        ]
    )
    facts = extract_tier0_programme_facts(bundle)
    assert any(
        s.kind == "OTHER"
        and s.label == "Scholarship / Funding Status"
        and "without scholarship" in s.text
        for s in facts.statements
    )

    # 7. Erasmus Mundus 12-month residency rule
    rule_12m = (
        "Partner Country applicants must not have resided or carried out their main activity "
        "(studies, training or work) for more than a total of 12 months over the last 5 years "
        "in any Programme Country (12-month rule)."
    )
    ev_12m_ok = evaluate_program_statement(
        rule_12m, prof_mandatory, include_coursework=True
    )
    assert ev_12m_ok.outcome == "SATISFIED"
    assert "no disqualifying Programme Country residence" in ev_12m_ok.status_text

    prof_eu_resident = _make_profile().model_copy(
        update={"nationality": "AZ", "country_of_residence": "DE"}
    )
    ev_12m_flag = evaluate_program_statement(
        rule_12m, prof_eu_resident, include_coursework=True
    )
    assert ev_12m_flag.outcome == "BORDERLINE"
    assert "12-month residency rule" in ev_12m_flag.status_text
    assert "DE" in ev_12m_flag.status_text

    # 8. Dual-track Non-EU / visa-requiring vs. EU/EEA application deadlines
    from datetime import date

    dual_dl_text = (
        "Non-EU applicants requiring a visa must apply by 1 March 2027; "
        "EU/EEA citizens may apply until 15 July 2027."
    )
    ev_non_eu_late = evaluate_program_statement(
        dual_dl_text,
        prof_mandatory,
        as_of=date(2027, 5, 1),
        include_coursework=False,
    )
    assert ev_non_eu_late.outcome == "FAILED"
    assert "2027-03-01" in ev_non_eu_late.status_text

    prof_eu_cit = _make_profile().model_copy(update={"nationality": "FR"})
    ev_eu_open = evaluate_program_statement(
        dual_dl_text,
        prof_eu_cit,
        as_of=date(2027, 5, 1),
        include_coursework=False,
    )
    assert ev_eu_open.outcome == "SATISFIED"
    assert "2027-07-15" in ev_eu_open.status_text


def test_pass8_degree_graduation_and_english_medium_waiver_rules() -> None:
    """Degree-based language proficiency waivers (`evidence_type="DEGREE"`) apply only
    upon graduation across all countries/institutions; `DEGREE` does not satisfy strict
    official-test requirements (`IELTS 6.5`) without an MOI waiver."""
    today = dt.date(2026, 10, 30)

    # 1. Ungraduated student with `evidence_type="DEGREE"`: `IN_PROGRESS` in
    # transcript_eligibility and `UNDECIDABLE` in eligibility.decide() ("upon graduation")
    prof_deg_ungrad = _make_profile(
        completed_on=None,
        expected_completion=dt.date(2027, 6, 15),
        language_evidence=(
            _lang("English", "C1", evidence_type="DEGREE"),
        ),
    )
    ev_ungrad_cefr = evaluate_program_statement(
        "English proficiency at CEFR C1.", prof_deg_ungrad, as_of=today
    )
    assert ev_ungrad_cefr.outcome == "IN_PROGRESS"
    assert "upon graduation" in ev_ungrad_cefr.status_text

    ev_ungrad_moi = evaluate_program_statement(
        "IELTS 6.5 or prior degree taught in English (Medium of Instruction).",
        prof_deg_ungrad,
        as_of=today,
    )
    assert ev_ungrad_moi.outcome == "IN_PROGRESS"
    assert "upon graduation" in ev_ungrad_moi.status_text

    dec_ungrad = decide(
        ConditionTriple(key="LANGUAGE", operator="GTE", value="English B2", quote="English B2"),
        prof_deg_ungrad,
        today=today,
    )
    assert dec_ungrad.outcome == "UNDECIDABLE"
    assert "upon graduation" in dec_ungrad.reason

    # 2. Graduated student (`completed_on <= today`) with `evidence_type="DEGREE"`:
    # qualifies for MOI waiver and CEFR bars, but NOT when a strict IELTS score is required
    # without an MOI waiver.
    prof_deg_grad = _make_profile(
        completed_on=dt.date(2025, 6, 15),
        language_evidence=(_lang("English", "C1", evidence_type="DEGREE"),),
    )
    ev_grad_moi = evaluate_program_statement(
        "IELTS 6.5 or prior degree taught in English (Medium of Instruction).",
        prof_deg_grad,
        as_of=today,
    )
    assert ev_grad_moi.outcome == "SATISFIED"

    dec_grad_cefr = decide(
        ConditionTriple(key="LANGUAGE", operator="GTE", value="English B2", quote="English B2"),
        prof_deg_grad,
        today=today,
    )
    assert dec_grad_cefr.outcome == "SATISFIED"

    ev_strict_test = evaluate_program_statement(
        "Applicants must submit IELTS 6.5 or TOEFL iBT 90.",
        prof_deg_grad,
        as_of=today,
    )
    assert ev_strict_test.outcome == "IN_PROGRESS"
    assert "not an official test certificate" in ev_strict_test.status_text

    dec_strict_test = decide(
        ConditionTriple(
            key="LANGUAGE",
            operator="GTE",
            value="English IELTS 6.5",
            quote="Applicants must submit IELTS 6.5.",
        ),
        prof_deg_grad,
        today=today,
    )
    assert dec_strict_test.outcome == "UNDECIDABLE"
    assert "not an official ielts test certificate" in dec_strict_test.reason.casefold()

    # Self-attested C1 does not satisfy an explicit IELTS 6.5 ConditionTriple in decide()
    prof_attested = _make_profile(
        language_evidence=(_lang("English", "C1", evidence_type="ATTESTED"),),
    )
    dec_attested_test = decide(
        ConditionTriple(
            key="LANGUAGE",
            operator="GTE",
            value="English IELTS 6.5",
            quote="Applicants must submit IELTS 6.5.",
        ),
        prof_attested,
        today=today,
    )
    assert dec_attested_test.outcome == "UNDECIDABLE"

    # Cross-test concordance: TOEFL 72 (~IELTS 6.0) fails IELTS 6.5 even though both are CEFR B2
    prof_toefl_72 = _make_profile(
        language_evidence=(_lang("English", "TOEFL iBT 72", evidence_type="TEST"),),
    )
    assert (
        decide(
            ConditionTriple(
                key="LANGUAGE",
                operator="GTE",
                value="English IELTS 6.5",
                quote="IELTS 6.5 required.",
            ),
            prof_toefl_72,
            today=today,
        ).outcome
        == "FAILED"
    )
    assert (
        evaluate_program_statement(
            "Minimum IELTS 6.5 required.", prof_toefl_72, as_of=today
        ).outcome
        == "FAILED"
    )

    # Unstated GPA scale inference for 10.0 and 5.0 scales and non-US/AZ 4.0 scales
    from apps.funding.transcript_eligibility import _infer_unstated_scale

    assert _infer_unstated_scale(Decimal("8.4"), "IN") == "10.0"
    assert _infer_unstated_scale(Decimal("4.5"), "PL") == "5.0"
    assert _infer_unstated_scale(Decimal("3.7"), "JP") == "4.0"










