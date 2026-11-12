from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.accounts.consultation import ConsultationDraft, _priorities_from_notes
from apps.accounts.schemas import AcademicRecord, CourseRecord, StudentProfileSnapshot
from apps.documents.cv_evidence import apply_cv_evidence, match_reading_target
from apps.documents.evidence.readings import UsableBullet, UsableReading
from apps.documents.letter_schemas import Storyline
from apps.documents.letter_shape import LetterShape, target_characters
from apps.documents.models import VerifiedFact
from apps.documents.mrz import date_from_strip
from apps.documents.ocr import OcrPage
from apps.documents.research_fit.anchors import infer_fit_mode
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    PersonalInformation,
    ProjectEntry,
)
from apps.documents.text_reading import _occurrences, _pattern
from apps.documents.transcript import _minimised
from apps.funding.eligibility import ConditionTriple, decide
from apps.funding.transcript_eligibility import evaluate_program_statement
from apps.portals.packets import _fit_entry_limits
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership


def test_infer_fit_mode_returns_pivot_bridge_when_storyline_has_gap_at_rung_4() -> None:
    storyline = Storyline(
        theme="Analytical chemistry to computational chemistry",
        theme_kind="PROBLEM",
        anchors=(uuid4(),),
        gap="Transitioning from wet-lab analytical chemistry to machine learning.",
        future="Develop graph neural networks for reaction yield prediction.",
    )
    assert (
        infer_fit_mode(
            anchor_rung=4,
            anchor_text="analytical chemistry",
            sentence="analytical chemistry and molecular modelling",
            kind="group",
            storyline=storyline,
        )
        == "pivot_bridge"
    )
    assert (
        infer_fit_mode(
            anchor_rung=1,
            anchor_text="analytical chemistry",
            sentence="analytical chemistry and molecular modelling",
            kind="group",
            storyline=storyline,
        )
        == "direct"
    )


def test_cv_evidence_matches_and_enriches_existing_project_entry() -> None:
    content = CVContent(
        personal_information=PersonalInformation(
            full_name="Aysel Mammadova",
            email="aysel@example.org",
        ),
        education=(
            EducationEntry(
                institution_original="Baku State University",
                degree_as_awarded="BSc Chemistry",
                start_date=date(2020, 9, 1),
                end_date=date(2024, 6, 30),
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        projects=(
            ProjectEntry(
                title="Catalyst Yield Predictor",
                bullets=("Built a regression pipeline for reaction yield prediction.",),
            ),
        ),
        document_language="en",
    )
    reading = UsableReading(
        source="github",
        url="https://github.com/aysel/catalyst-yield-predictor",
        document_id=None,
        summary="Reaction yield predictor using RDKit descriptors.",
        kind="repo",
        names=("Catalyst Yield Predictor",),
        first_commit="2024-02-01",
        last_commit="2024-05-15",
        bullets=(
            UsableBullet(
                text="Evaluated 400 palladium-catalyzed couplings with RDKit descriptors.",
                evidence=("400 palladium-catalyzed couplings",),
                verdict="supported",
            ),
        ),
        repo="aysel/catalyst-yield-predictor",
    )
    assert match_reading_target(reading, content) == ("projects", 0)
    enriched, fixes = apply_cv_evidence(content, (reading,))
    assert len(enriched.projects) == 1
    assert enriched.projects[0].url == "https://github.com/aysel/catalyst-yield-predictor"
    assert any("400 palladium-catalyzed" in b for b in enriched.projects[0].bullets)
    assert fixes and fixes[0]["target"] == "projects:0"


def test_render_cv_html_honors_required_personal_fields_and_medium_of_instruction() -> None:
    from django.template.loader import render_to_string

    content = CVContent(
        personal_information=PersonalInformation(
            full_name="Aysel Mammadova",
            email="aysel@example.org",
            date_of_birth=date(2002, 4, 15),
            citizenship="Azerbaijani",
            sex="Female",
        ),
        education=(
            EducationEntry(
                institution_original="ADA University",
                degree_as_awarded="BSc in Computer Science",
                start_date=date(2020, 9, 1),
                end_date=date(2024, 6, 30),
                grade_native="92%",
                medium_of_instruction="English",
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )
    html_str = render_to_string(
        "documents/cv_base.html",
        {
            "content": content,
            "section_order": (),
            "include_targets": frozenset(
                {
                    "personal.date_of_birth",
                    "personal.citizenship",
                    "personal.sex",
                    "education.medium_of_instruction",
                }
            ),
            "font_family": "Liberation Serif",
            "font_pt": 11.0,
            "compact": False,
            "signature": False,
            "tabular": False,
            "experience_rows": (),
            "volunteering_rows": (),
        },
    )
    assert "2002" in html_str
    assert "Azerbaijani" in html_str
    assert "Female" in html_str
    assert "Medium of instruction: English" in html_str


def test_letter_shape_clamps_target_characters_to_small_max_characters() -> None:
    shape = LetterShape(min_chars=240, max_chars=250)
    assert target_characters(shape) == 240
    assert target_characters(shape) <= 250


def test_mrz_date_from_strip_handles_non_leap_century_feb_29() -> None:
    assert date_from_strip("000229", birth=True, today=date(1999, 1, 1)) is None
    assert date_from_strip("000229", birth=True, today=date(2026, 10, 31)) == date(2000, 2, 29)


def test_transcript_minimised_keeps_course_rows_with_national_identity_title() -> None:
    page = OcrPage(
        lines=("Transcript of Records",),
        tables=(
            (
                ("Course Code", "Course Title", "ECTS", "Grade"),
                ("POL301", "National Identity and State Building", "6", "A"),
            ),
        ),
    )
    _lines, tables, _conf, _origins = _minimised((page,), frozenset())
    assert any("National Identity and State Building" in row for row in tables[0])


def test_text_reading_occurrences_matches_azerbaijani_ordinal_and_nfd() -> None:
    import unicodedata

    from apps.documents.azure_layout import AzureLayout, AzurePage, AzureSpan, AzureWord

    text = "Təhsil müddəti: 2023-cü il."
    m = _pattern("2023").search(text)
    assert m is not None
    assert m.span() == (16, 20)

    nfd_text = unicodedata.normalize("NFD", "Azərbaycan Dövlət Universiteti")
    first_word_nfd = unicodedata.normalize("NFD", "Azərbaycan")
    layout = AzureLayout(
        content=nfd_text,
        pages=[
            AzurePage(
                pageNumber=1,
                width=8.5,
                height=11.0,
                unit="inch",
                words=[
                    AzureWord(
                        content=first_word_nfd,
                        confidence=0.99,
                        span=AzureSpan(offset=0, length=len(first_word_nfd)),
                    )
                ],
            )
        ],
    )
    nfd_hits = _occurrences("Azərbaycan", layout)
    assert len(nfd_hits) == 1
    assert nfd_hits[0][0] == 0
    assert len(nfd_hits[0][1]) == 1


def test_consultation_preserves_courses_on_edit_and_flips_negated_duration() -> None:
    draft = ConsultationDraft(
        tenant_id=uuid4(),
        membership_id=uuid4(),
        answers={
            "academic_history": [
                {
                    "institution": "Baku State University",
                    "country_code": "AZ",
                    "qualification": "BSc",
                    "field": "Chemistry",
                    "grade": "88",
                    "grading_scale": "100",
                    "completed_on": "2025-06-30",
                    "expected_completion": None,
                    "courses": [{"title": "Organic Chemistry", "ects": "6.00", "grade": "95"}],
                },
                {
                    "institution": "ADA University",
                    "country_code": "AZ",
                    "qualification": "Exchange",
                    "field": "Chemistry",
                    "grade": "90",
                    "grading_scale": "100",
                    "completed_on": "2024-06-30",
                    "expected_completion": None,
                    "courses": [],
                },
            ]
        },
    )
    updated = draft.with_answer(
        "academic_history",
        [
            {
                "institution": "Baku State University",
                "country_code": "AZ",
                "qualification": "BSc",
                "field": "Chemistry",
                "grade": "91",
                "grading_scale": "100",
                "completed_on": "2025-06-30",
                "expected_completion": None,
                "courses": [],
            }
        ],
    )
    hist = updated.answer("academic_history")
    assert isinstance(hist, list) and len(hist) == 2
    assert hist[0]["grade"] == "91"
    assert len(hist[0]["courses"]) == 1
    assert hist[0]["courses"][0]["title"] == "Organic Chemistry"

    payload: dict[str, object] = {}
    _priorities_from_notes("No 1-year master's.", payload)
    assert payload["duration_preference"] == "TWO_YEAR"
    assert payload["duration_flexibility"] == "NON_NEGOTIABLE"


def test_comma_separated_degree_fields_and_erasmus_programme_country_national() -> None:
    profile = StudentProfileSnapshot(
        nationality="DE",
        country_of_residence="FR",
        date_of_birth=date(2002, 5, 1),
        target_field="Computer Science",
        intended_intake=date(2027, 9, 1),
        acceptable_teaching_languages=("English",),
        funding_dependency="MANDATORY",
        application_budget={"amount": Decimal("200"), "currency": "EUR"},
        career_intent="WORK_ABROAD",
        academic_history=(
            AcademicRecord(
                institution="TU Munich",
                country_code="DE",
                qualification="BSc",
                field="Computer Science",
                grade="1.5",
                grading_scale="1-5",
                completed_on=date(2025, 6, 30),
                courses=(CourseRecord(title="Algorithms", ects=Decimal("10")),),
            ),
        ),
    )
    stmt_eval = evaluate_program_statement(
        "Applicants must hold a Bachelor's degree in Mathematics, Physics, or Computer Science.",
        profile,
    )
    assert stmt_eval.outcome == "SATISFIED"

    erasmus_cond = ConditionTriple(
        key="RESIDENCE",
        operator="PRESENT",
        value="12-month rule",
        quote=(
            "Must not have resided in a Programme Country "
            "for more than 12 months in last 5 years"
        ),
    )
    decision = decide(erasmus_cond, profile, today=date(2026, 10, 31))
    assert decision.outcome == "SATISFIED"


def test_fit_entry_limits_applies_stricter_description_char_cap() -> None:
    text = "First sentence is short. Second sentence makes the string much longer than forty chars."
    fitted = _fit_entry_limits(
        "narrative.motivation_letter",
        text,
        500,
        description="Maximum 40 characters and max 20 words",
    )
    assert len(fitted) <= 40


@pytest.mark.django_db
def test_gaps_suppresses_certificates_note_and_parses_1_based_author_index(
    agency_a, django_user_model
) -> None:
    from django.utils import timezone

    from apps.documents.gaps import answer_questions, gap_notes, gap_questions

    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="gap_test_student")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.CERTIFICATION,
            payload={"name": "AWS Certified Machine Learning"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:1",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        pub_fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.PUBLICATION,
            payload={
                "title": "Neural Potentials",
                "authors": ["J. Doe", "A. Mammadova"],
                "venue": "JCTC",
                "year": "2025",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="orcid:0000-0001-2345-6789:work:1",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        notes = gap_notes(student)
        assert not any("certificates" in note.text.lower() for note in notes)
        questions = gap_questions(student)
        pub_q = next(
            q
            for q in questions
            if q.fact_id == pub_fact.id and q.payload_key == "self_author_index"
        )
        written = answer_questions(((pub_q, "2"),), student=student)
        assert len(written) == 1
        assert written[0].payload["self_author_index"] == 1
