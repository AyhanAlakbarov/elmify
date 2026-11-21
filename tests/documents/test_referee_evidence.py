"""Tests for referee_evidence: matching a student's CV, transcript courses,
co-authored papers, and GitHub/PDF readings to a specific professor."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.documents.evidence.readings import UsableBullet, UsableReading
from apps.documents.models import Referee, VerifiedFact
from apps.documents.referee_evidence import (
    extract_supervisor_name_and_title,
    group_matches,
    institution_matches,
    person_matches,
    referee_angle,
    shared_work_for_referee,
)


def test_person_matches_handles_honorifics_initials_and_rejects_different_given_name() -> None:
    assert person_matches("Prof. Philippe Schwaller", "Philippe Schwaller")
    assert person_matches("Prof. Philippe Schwaller", "P. Schwaller")
    assert person_matches("Prof. Philippe Schwaller", "Schwaller, P.")
    assert person_matches("Prof. Philippe Schwaller", "Schwaller, Philippe")
    assert person_matches("Prof. Philippe Schwaller", "Dr. Schwaller")
    assert not person_matches("Prof. Philippe Schwaller", "Anna Schwaller")
    assert not person_matches("Prof. Philippe Schwaller", "Philippe Aliyev")


def test_person_matches_transliterations_particles_compound_names_and_co_supervisors() -> None:
    # Azerbaijani, Turkish, German, Nordic, and Cyrillic transliterations
    assert person_matches("Prof. Rauf Əliyev", "Rauf Aliyev")
    assert person_matches("Rauf Aliyev", "Prof. R. Əliyev")
    assert person_matches("Rauf Aliyev", "Rauf Eliyev")
    assert person_matches("Rauf Aliyev", "Проф. Рауф Алиев")
    assert person_matches("Prof. Şahin Məmmədov", "Shahin Mammadov")
    assert person_matches("Shahin Mammadov", "Sahin Memmedov")
    assert person_matches("Prof. Çingiz Quliyev", "Chingiz Guliyev")
    assert person_matches("Prof. Jürgen Müller", "Juergen Mueller")
    assert person_matches("Prof. Jürgen Müller", "Jurgen Muller")
    assert person_matches("Prof. Søren Østergaard", "Soren Ostergaard")

    # Nobiliary particles, hyphenated surnames, concatenated initials, patronymics, reversed order
    assert person_matches("Prof. Jan van der Waals", "Prof. van der Waals")
    assert person_matches("Prof. Jan van der Waals", "Waals, J. van der")
    assert person_matches("Prof. Jan van der Waals", "van der Waals, Jan")
    assert person_matches("Prof. Maria Garcia-Lopez", "M. Garcia-Lopez")
    assert person_matches("Prof. Maria Garcia-Lopez", "Garcia-Lopez, M.")
    assert person_matches("Prof. Jean-Pierre Sauvage", "JP Sauvage")
    assert person_matches("Prof. Rauf Aliyev", "Əliyev Rauf Məmməd oğlu")
    assert person_matches("Prof. Rauf Aliyev", "Aliyev Rauf")
    assert person_matches("Prof. Rauf Aliyev", "Aliyev R. M.")

    # Co-supervisors & affiliation annotations
    co_sup = "Supervised by Prof. Philippe Schwaller (EPFL) and Dr. Rocío Mercado"
    assert person_matches("Philippe Schwaller", co_sup)
    assert person_matches("Rocio Mercado", co_sup)
    assert person_matches("Philippe Schwaller", "Prof. Philippe Schwaller, EPFL")
    assert extract_supervisor_name_and_title(co_sup) == ("Prof.", "Philippe Schwaller")


def test_institution_matches_handles_acronyms_and_rejects_generic_words() -> None:
    assert institution_matches("Baku Higher Oil School", "BHOS")
    assert institution_matches("BHOS", "Baku Higher Oil School (BHOS)")
    assert institution_matches("PASHA Bank", "PASHA Bank OJSC")
    assert not institution_matches("Baku State University", "ADA University")


def test_group_matches_recognises_lab_group_and_github_org_names() -> None:
    assert group_matches("Prof. Philippe Schwaller", "EPFL | Prof. Philippe Schwaller's group")
    assert group_matches("Prof. Philippe Schwaller", "Schwaller Lab")
    assert group_matches("Prof. Philippe Schwaller", "schwallergroup")
    assert not group_matches("Prof. Philippe Schwaller", "Other Lab")


@pytest.mark.django_db
def test_shared_work_matches_cv_thesis_lab_post_publication_github_pdf_and_courses(
    agency_a, membership_a
) -> None:
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        referee = Referee.objects.create(
            tenant=agency_a,
            student=membership_a,
            title="Prof.",
            name="Philippe Schwaller",
            institution="EPFL",
            relationship="Taught me Molecular Machine Learning and supervised my reaction thesis.",
        )
        now = timezone.now()
        edu = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "degree_english": "BSc Chemical Engineering",
                "institution_english": "EPFL",
                "grade_native": "5.7/6.0",
                "thesis_title": "Transformer Models for Reaction Yield Prediction",
                "supervisor": "Prof. P. Schwaller",
                "courses": [
                    {
                        "title": "Molecular Machine Learning",
                        "grade": "6.0/6.0",
                        "credits": "6",
                        "status": "COMPLETED",
                    },
                    {
                        "title": "Linear Algebra",
                        "grade": "5.5/6.0",
                        "credits": "6",
                        "status": "COMPLETED",
                    },
                ],
                "courses_unconfirmed": [
                    {
                        "title": "Molecular Modelling Seminar",
                        "grade": "6.0/6.0",
                        "credits": "4",
                        "status": "COMPLETED",
                    }
                ],
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="transcript",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        exp = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "employer": "EPFL",
                "title": "Undergraduate Research Assistant",
                "group": "Schwaller Group",
                "project": "MicroKatc Reaction Screening",
                "start_date": "2025-06-01",
                "end_date": "2025-09-01",
                "bullets": ["Built an active-learning pipeline over 12,000 catalytic runs."],
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        pub = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.PUBLICATION,
            payload={
                "authors": ["Orkhan Abdullayev", "Schwaller, P."],
                "title": "Active Learning for Yield Prediction",
                "venue": "Digital Discovery",
                "year": 2026,
                "doi": "10.1039/d6dd00001a",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="doi:10.1039/d6dd00001a",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        unrelated_pub = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.PUBLICATION,
            payload={
                "authors": ["Orkhan Abdullayev", "Anna Schwaller"],
                "title": "Unrelated Paper With Different Given Name",
                "venue": "J. Other",
                "year": 2025,
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )

    github_reading = UsableReading(
        source="github",
        url="https://github.com/schwallergroup/MicroKatc",
        document_id=None,
        summary="Bayesian optimization over Mordred descriptors for catalytic yields.",
        kind="research",
        names=("MicroKatc Reaction Screening",),
        first_commit="2025-06-03",
        last_commit="2025-08-29",
        bullets=(
            UsableBullet(
                text="Implemented FABO dimensionality reduction across 60 random seeds.",
                evidence=("src/feature_selection/fabo.py",),
                verdict="supported",
            ),
            UsableBullet(
                text="Rejected claim that must never appear.",
                evidence=(),
                verdict="rejected",
            ),
        ),
        repo="schwallergroup/MicroKatc",
        owner_type="Organization",
        owner_name="Schwaller Group",
        commits=42,
    )
    pdf_reading = UsableReading(
        source="pdf",
        url=None,
        document_id=None,
        summary="BSc thesis report evaluating transformer tokenizers on USPTO subsets.",
        kind="thesis",
        names=("Transformer Models for Reaction Yield Prediction",),
        first_commit=None,
        last_commit=None,
        bullets=(
            UsableBullet(
                text="Benchmarked fine-tuned RXNFP embeddings against Morgan fingerprints.",
                evidence=("Section 4.2",),
                verdict="supported",
            ),
        ),
        methods="Fine-tuned BERT reaction encoders",
        outcomes="Improved R2 by 0.14 on held-out catalysts",
    )

    items = shared_work_for_referee(
        referee,
        facts=[edu, exp, pub, unrelated_pub],
        readings=[github_reading, pdf_reading],
    )
    kinds = [item.kind for item in items]
    assert kinds == ["research", "experience", "publication", "github", "pdf", "coursework"]

    summaries = "\n".join(item.summary for item in items)
    all_bullets = "\n".join(b for item in items for b in item.bullets)

    assert "Transformer Models for Reaction Yield Prediction" in summaries
    assert "Undergraduate Research Assistant (MicroKatc Reaction Screening)" in summaries
    assert "Co-authored paper: Active Learning for Yield Prediction" in summaries
    assert "Unrelated Paper With Different Given Name" not in summaries
    assert "GitHub repository: schwallergroup/MicroKatc — 42 commits" in summaries
    assert "Implemented FABO dimensionality reduction across 60 random seeds." in all_bullets
    assert "Rejected claim that must never appear." not in all_bullets
    assert "Thesis/report PDF: Transformer Models for Reaction Yield Prediction" in summaries
    assert "Methods: Fine-tuned BERT reaction encoders" in all_bullets
    assert "Coursework: Molecular Machine Learning (grade 6.0/6.0, 6 credits)" in summaries
    assert "Linear Algebra" not in summaries
    assert "Molecular Modelling Seminar" not in summaries
    assert referee_angle(referee, items) == (
        "Research supervision, co-authored publication, and independent inquiry"
    )


@pytest.mark.django_db
def test_shared_work_handles_professional_employer_course_codes_acronyms_and_awards(
    agency_a, membership_a
) -> None:
    from apps.tenancy.context import tenant_scope

    now = timezone.now()
    with tenant_scope(agency_a.id):
        prof_ref = Referee.objects.create(
            tenant=agency_a,
            student=membership_a,
            name="Farid Mammadov",
            title="Mr.",
            institution="PASHA Bank",
            kind=Referee.Kind.PROFESSIONAL,
            relationship="Managed my risk analytics team.",
        )
        acad_ref = Referee.objects.create(
            tenant=agency_a,
            student=membership_a,
            name="Rauf Əliyev",
            title="Prof.",
            institution="BHOS",
            kind=Referee.Kind.ACADEMIC,
            relationship="Taught CS224N and NLP, and advised my Best Thesis Award.",
        )
        exp_fact = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "employer": "PASHA Bank OJSC",
                "title": "Credit Risk Data Analyst",
                "start_date": "2024-02",
                "end_date": "2025-08",
                "bullets": ["Automated PD backtesting in Python across 180k retail loans."],
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        edu_fact = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "degree_english": "BSc Computer Engineering",
                "institution_english": "Baku Higher Oil School",
                "grade_native": "94/100",
                "courses": [
                    {"title": "CS224N: Deep Learning", "grade": "A", "credits": "6"},
                    {"title": "Statistical NLP", "grade": "A+", "credits": "5"},
                ],
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="transcript",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        award_fact = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.AWARD,
            payload={
                "name": "Best Thesis Award",
                "issuer": "Baku Higher Oil School",
                "year": "2025",
                "description": "Ranked 1st among 85 graduating projects.",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )

    prof_items = shared_work_for_referee(prof_ref, facts=[exp_fact, edu_fact, award_fact])
    assert [i.kind for i in prof_items] == ["experience"]
    assert "Credit Risk Data Analyst, PASHA Bank OJSC, 2024-02–2025-08" in prof_items[0].summary
    assert referee_angle(prof_ref, prof_items) == (
        "Workplace performance, delivery under responsibility, and professional impact"
    )

    acad_items = shared_work_for_referee(acad_ref, facts=[exp_fact, edu_fact, award_fact])
    assert [i.kind for i in acad_items] == ["coursework", "coursework", "award"]
    acad_summaries = "\n".join(i.summary for i in acad_items)
    assert "CS224N: Deep Learning (grade A, 6 credits)" in acad_summaries
    assert "Statistical NLP (grade A+, 5 credits)" in acad_summaries
    assert "Award: Best Thesis Award, Baku Higher Oil School, 2025" in acad_summaries


def test_international_names_scripts_patronymics_and_institutions() -> None:
    # 1. Short Vietnamese/Indian/Chinese surnames that overlap with European particles
    assert person_matches("Prof. Minh Le", "Le, Minh")
    assert person_matches("Prof. Minh Le", "Dr. M. Le")
    assert not person_matches("Prof. Minh Le", "Prof. Minh Tran")
    assert person_matches("Prof. Subhashis De", "Dr. S. De")
    assert not person_matches("Prof. Subhashis De", "Dr. Subhashis Roy")
    assert person_matches("Prof. Bowen Du", "Bowen Du")
    assert person_matches("Prof. Quang Do", "Do, Q.")
    assert person_matches("Prof. Jimmy Ba", "Ba, J.")
    assert person_matches("Prof. Yulun Ma", "Dr. Y. Ma")

    # 2. East Asian & Hungarian family-name-first rotation
    assert person_matches("Prof. Min-jun Kim", "Prof. Kim Min-jun")
    assert person_matches("Prof. Min-jun Kim", "Kim Min Jun")
    assert person_matches("Prof. Wei Zhang", "Zhang Wei")
    assert person_matches("Prof. János Kovács", "Kovács János")

    # 3. Hispanic & Portuguese dual/compound surnames
    assert person_matches("Prof. Carlos García López", "Prof. Carlos García")
    assert person_matches("Prof. Carlos García López", "García López, Carlos")
    assert person_matches("Prof. Carlos García López", "Dra. C. García-López")

    # 4. Slavic patronymics & Ukrainian/Polish/Russian surname transliterations
    assert person_matches("Prof. Olena Kovalenko", "Prof. Olena Petrivna Kovalenko")
    assert person_matches("Prof. Sergey Ivanov", "Ivanov, Sergey Ivanovich")
    assert person_matches("Prof. Andrii Kovalskyi", "Dr. Andriy Kovalsky")
    assert person_matches("Prof. Łukasz Wiśniewski", "Dr. Lukasz Wisniewski")

    # 5. Arabic / Persian / South Asian transliteration pairs
    assert person_matches("Prof. Mohammed Al-Mansour", "Dr. Muhammad al-Mansur")
    assert person_matches("Prof. Hossein Zadeh", "Dr. Hussain Zada")

    # 6. Global city-independent institution disambiguation
    assert not institution_matches("University of Tokyo", "Tokyo Institute of Technology")
    assert not institution_matches("University of Warsaw", "Warsaw University of Technology")
    assert not institution_matches("Istanbul University", "Istanbul Technical University")
    assert not institution_matches("Cairo University", "American University in Cairo")
    assert institution_matches(
        "University of Warsaw",
        "Warsaw University, Faculty of Mathematics and Informatics",
    )
    assert institution_matches(
        "Middle East Technical University",
        "METU, Department of Computer Engineering",
    )
    assert institution_matches("Stanford University", "Stanford")
