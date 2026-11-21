"""Stage 3 (spec 2026-10-12 §5): automatic quality fixes."""

from datetime import date

import pytest
from django.utils import timezone

from apps.documents.cv_fixes import (
    FULL_TITLE,
    SOFT_SKILL,
    THESIS_PLACEMENT,
    abbreviated_degree,
    abbreviated_institution,
    drop_soft_skills,
    full_title_for,
    full_titles,
    is_soft_skill,
    is_thesis_title,
    keep_wording,
    place_theses,
    stamp_from_ledger,
    subject_of,
)
from apps.documents.models import VerifiedFact
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    PersonalInformation,
    SkillEntry,
)
from apps.documents.verification import fact_payload
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

EXP = VerifiedFact.Category.EXPERIENCE
SKILL = VerifiedFact.Category.SKILL
EDU = VerifiedFact.Category.EDUCATION


def _cv(**over):
    fields = dict(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="MSc Chemoinformatics",
                institution_original="University of Strasbourg",
                start_date=date(2024, 9, 1),
                end_date=date(2026, 6, 30),
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
    fields.update(over)
    return CVContent(**fields)


def _post(**over):
    fields = dict(
        employer="EPFL",
        title="Research Intern",
        start_date=date(2025, 6, 1),
        end_date=date(2025, 9, 1),
        bullets=("Benchmarked the models for the group and wrote the report.",),
    )
    fields.update(over)
    return ExperienceEntry(**fields)


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _fact(student, category, payload, *, tier=VerifiedFact.SourceTier.STUDENT_STATEMENT):
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=tier,
        source_ref="upload:test",
        confirmed_by=student,
        confirmed_at=timezone.now(),
        created_by=student,
    )


def test_reworded_bullets_are_restored_from_the_ledger(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp-b")
        fact = _fact(student, EXP, fact_payload(_post(), category=EXP))
        reworded = _cv(experience=(_post(bullets=("Spearheaded benchmarking.",)),))
        stamped = stamp_from_ledger(reworded, [fact])
    assert stamped.experience[0].bullets == (
        "Benchmarked the models for the group and wrote the report.",
    )


def test_an_invented_skill_heading_is_replaced_by_the_ledgers(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp-s")
        fact = _fact(student, SKILL, {"name": "Python", "category": None})
        renamed = _cv(skills=(SkillEntry(name="python", category="Core Competencies"),))
        stamped = stamp_from_ledger(renamed, [fact])
    assert stamped.skills[0].category is None


def test_an_entry_with_two_matching_facts_is_left_alone(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp-2")
        payload = fact_payload(_post(), category=EXP)
        facts = [
            _fact(student, EXP, payload),
            _fact(student, EXP, {**payload, "bullets": ["Other line."]}),
        ]
        content = _cv(experience=(_post(bullets=("Model's line.",)),))
        assert stamp_from_ledger(content, facts).experience[0].bullets == ("Model's line.",)


@pytest.mark.parametrize(
    "name, kind, soft",
    [
        ("Teamwork", None, True),
        ("Team-work", None, True),
        ("Excellent communication skills", None, True),
        ("Problem solving", None, True),
        ("Time-management", None, True),
        ("Organisational skills", None, True),
        ("Analytical ability", None, True),
        ("Communication protocols (TCP/IP)", None, False),
        ("Team Foundation Server", None, False),
        ("LEED (Leadership in Energy and Environmental Design)", None, False),
        ("Networking", None, False),
        ("Project management", None, False),
        ("Leadership", "technique", False),
    ],
)
def test_the_soft_skill_list(name, kind, soft):
    assert is_soft_skill(name, kind) is soft


def test_soft_skills_are_left_out_and_listed():
    content = _cv(skills=(SkillEntry(name="Python"), SkillEntry(name="Teamwork")))
    kept, fixes = drop_soft_skills(content, [], frozenset())
    assert [s.name for s in kept.skills] == ["Python"]
    [fix] = fixes
    assert (fix.fix, fix.original, fix.changed, fix.undone) == (SOFT_SKILL, "Teamwork", "", False)


def test_a_put_back_skill_stays_and_is_listed_as_undone():
    content = _cv(skills=(SkillEntry(name="Teamwork"),))
    kept, fixes = drop_soft_skills(content, [], frozenset({subject_of(SOFT_SKILL, "Teamwork")}))
    assert [s.name for s in kept.skills] == ["Teamwork"]
    assert fixes[0].undone is True


def test_a_skill_a_document_vouches_for_is_never_left_out(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "soft-auth")
        fact = _fact(
            student,
            SKILL,
            {"name": "Leadership"},
            tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        )
        kept, fixes = drop_soft_skills(
            _cv(skills=(SkillEntry(name="Leadership"),)), [fact], frozenset()
        )
    assert [s.name for s in kept.skills] == ["Leadership"] and fixes == ()


@pytest.mark.parametrize(
    "title, thesis",
    [
        ("Master’s Thesis", True),
        ("Master Thesis", True),
        ("MSc Thesis", True),
        ("Bachelor's thesis work", True),
        ("Thesis", True),
        ("Final Year Project", True),
        ("Master's thesis student", False),
        ("Thesis Supervisor", False),
        ("Research Intern", False),
    ],
)
def test_is_thesis_title(title, thesis):
    assert is_thesis_title(title) is thesis


def _thesis_post(**over):
    fields = dict(
        employer="University of Strasbourg",
        title="Master's Thesis",
        project="AZIMUTH: a map of chemical space",
        supervisor="Prof. Varnek",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
    )
    fields.update(over)
    return _post(**fields)


def test_the_thesis_is_copied_under_its_degree_and_the_post_stays():
    content, [fix] = place_theses(_cv(experience=(_thesis_post(),)), frozenset())
    degree = content.education[0]
    assert (degree.thesis_title, degree.supervisor) == (
        "AZIMUTH: a map of chemical space",
        "Prof. Varnek",
    )
    assert content.experience[0].title == "Master's Thesis"
    assert fix.fix == THESIS_PLACEMENT and fix.where == "education[0]"


def test_a_degree_naming_another_thesis_is_left_alone():
    cv = _cv(experience=(_thesis_post(),))
    cv = cv.model_copy(
        update={
            "education": (
                cv.education[0].model_copy(
                    update={"thesis_title": "Something else", "supervisor": "Dr. X"}
                ),
            )
        }
    )
    content, fixes = place_theses(cv, frozenset())
    assert content.education[0].thesis_title == "Something else" and fixes == ()


def test_two_candidate_degrees_place_nothing():
    cv = _cv(experience=(_thesis_post(),))
    other = cv.education[0].model_copy(update={"institution_original": "ETH Zurich"})
    content, fixes = place_theses(
        cv.model_copy(update={"education": (*cv.education, other)}).model_copy(
            update={"experience": (_thesis_post(employer="Elsewhere"),)}
        ),
        frozenset(),
    )
    assert fixes == ()


@pytest.mark.parametrize(
    "degree, flagged",
    [
        ("B.Sc. of Chem. Eng.", True),
        ("BSc", True),
        ("Bakalavr", True),
        ("Lisans, Kimya Müh.", True),
        ("Бакалавр, прикл. математика", True),
        ("MSc. of Complex Systems Chemistry (CSC)", False),
        ("M.Sc. Informatik", False),
        ("Dipl.-Ing. Maschinenbau", False),
        ("Licence Génie Chimique", False),
        ("Ph.D. in Chemoinformatics", False),
    ],
)
def test_abbreviated_degree(degree, flagged):
    assert abbreviated_degree(degree) is flagged


@pytest.mark.parametrize(
    "institution, flagged",
    [
        ("UFAZ", True),
        ("İTÜ", True),
        ("ODTÜ (METU)", True),
        ("Univ. of Strasbourg", True),
        ("ADA University", False),
        ("ETH Zurich", False),
        ("St. Petersburg State University", False),
        ("J. W. Goethe-Universität", False),
    ],
)
def test_abbreviated_institution(institution, flagged):
    assert abbreviated_institution(institution) is flagged


def _diploma(student, title, *, institution="UFAZ", end="2023-06-30"):
    return _fact(
        student,
        EDU,
        {
            "degree_as_awarded": title,
            "institution_original": institution,
            "end_date": end,
        },
        tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
    )


def test_the_full_title_comes_only_from_a_matching_document(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "full")
        right = _diploma(student, "Bachelor of Science in Chemical Engineering")
        wrong_place = _diploma(student, "Bachelor of Chemistry and English", institution="BDU")
        facts = [right, wrong_place]
    assert full_title_for("B.Sc. of Chem. Eng.", "UFAZ", 2023, facts) == (
        "Bachelor of Science in Chemical Engineering"
    )
    assert full_title_for("B.Sc. of Chem. Eng.", "UFAZ", 2021, facts) is None
    assert full_title_for("B.Sc. of Mech. Eng.", "UFAZ", 2023, facts) is None


def test_two_matching_documents_choose_nothing(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "full2")
        facts = [
            _diploma(student, "Bachelor of Chemical Engineering"),
            _diploma(student, "Bachelor of Chemistry Engineering"),
        ]
    assert full_title_for("B.Sc. of Chem. Eng.", "UFAZ", 2023, facts) is None


def test_an_overlong_document_title_is_refused(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "full3")
        facts = [_diploma(student, "Bachelor of Chemical Engineering " + "x" * 200)]
    assert full_title_for("B.Sc. of Chem. Eng.", "UFAZ", 2023, facts) is None


def test_full_titles_replace_and_list_the_change(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "full4")
        diploma = _diploma(student, "Bachelor of Science in Chemical Engineering")
        abbreviated = EducationEntry(
            degree_as_awarded="B.Sc. of Chem. Eng.",
            institution_original="UFAZ",
            end_date=date(2023, 6, 30),
        )
        content, [fix] = full_titles(_cv(education=(abbreviated,)), [diploma], frozenset())
    assert content.education[0].degree_as_awarded == "Bachelor of Science in Chemical Engineering"
    assert (fix.fix, fix.original) == (FULL_TITLE, "B.Sc. of Chem. Eng.")


def test_no_document_prints_the_title_as_written():
    abbreviated = EducationEntry(
        degree_as_awarded="B.Sc. of Chem. Eng.",
        institution_original="UFAZ",
        end_date=date(2023, 6, 30),
    )
    content, fixes = full_titles(_cv(education=(abbreviated,)), [], frozenset())
    assert content.education[0].degree_as_awarded == "B.Sc. of Chem. Eng." and fixes == ()


def test_keeping_a_verb_fix_writes_a_confirmed_superseding_fact(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "keep")
        post = _post(bullets=("A tool for the lab.", "Wrote the report."))
        fact = _fact(student, EXP, fact_payload(post, category=EXP))
        row = keep_wording(
            student=student,
            original="A tool for the lab.",
            changed="Built a tool for the lab.",
        )
        assert row is not None and row.supersedes_id == fact.id
        assert row.payload["bullets"] == ["Built a tool for the lab.", "Wrote the report."]
        assert row.confirmed_by_id == student.id and row.source_ref == "cv-fix:S-026"
        assert AuditEvent.objects.filter(event="fact.cv_fix_kept", object_id=row.id).exists()


def test_keeping_a_line_no_fact_holds_writes_nothing(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "keep-none")
        assert keep_wording(student=student, original="Gone.", changed="Built gone.") is None


def test_thesis_title_regex_is_linear_time_on_repeated_prefixes():
    import time

    from apps.documents.cv_fixes import is_thesis_title

    start = time.perf_counter()
    assert is_thesis_title("graduation " * 40 + "not-a-thesis") is False
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05
    assert is_thesis_title("Master's graduation thesis project") is True
