"""Referee planner input wiring and WP3 document regression tests."""

from datetime import date

import pytest

from apps.documents.constraints import ConstraintRule, Enforcement
from apps.documents.funder_templates.australia_awards import australia_awards_fields
from apps.documents.funder_templates.sisgp import render_sisgp
from apps.documents.gaps.answers import answer_questions
from apps.documents.gaps.models import GapQuestion, Kind
from apps.documents.generation import _preserve_clean_sections
from apps.documents.models import Referee, VerifiedFact
from apps.documents.referee_views import _facts, application_needs
from apps.documents.render import content_warnings, render_cv
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    PersonalInformation,
    ProjectEntry,
)
from apps.documents.verification import ClaimVerdict
from apps.funding.models import RecommendationCandidate
from apps.tenancy.context import tenant_scope
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack


def _records(*pairs, text="At least one academic letter; use an institutional email."):
    return [
        {
            "field": f,
            "value": v,
            "date": "",
            "conditional": False,
            "condition": "",
            "rule_text": text,
            "source_url": "https://imperial.ac.uk/apply",
        }
        for f, v in pairs
    ]


def test_application_needs_forwards_min_academic_and_webmail_blocked(
    agency_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(
            referee_requirements=_records(
                ("count", "TWO"),
                ("kind", "EITHER"),
                ("mode", "PORTAL_INVITE"),
                ("institutional_email_required", "YES"),
            )
        )
        programme.refresh_from_db()
        card = add_card(agency_a, membership_a, programme)
        rows = application_needs(membership_a, [card])
    assert len(rows) == 1
    _app, _need, app_need = rows[0]
    assert app_need.min_academic == 1
    assert app_need.institutional_email is True
    assert app_need.webmail_blocked is False

    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(
            referee_requirements=_records(
                ("count", "TWO"),
                ("kind", "EITHER"),
                ("mode", "PORTAL_INVITE"),
                ("institutional_email_required", "YES"),
                text="At least one academic letter; webmail addresses are not accepted.",
            )
        )
        programme.refresh_from_db()
        card.refresh_from_db()
        hard_rows = application_needs(membership_a, [card])
    assert hard_rows[0][2].webmail_blocked is True


def test_referee_facts_wires_role_archetype_and_shared_work_score(
    agency_a, membership_a
):
    from django.utils import timezone

    now = timezone.now()
    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.RESEARCH,
            payload={
                "thesis_title": "Catalyst Discovery",
                "institution": "ADA University",
                "supervisor": "Prof. Aliyev",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:res1",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        ref = Referee.objects.create(
            tenant=agency_a,
            student=membership_a,
            title="Prof.",
            name="Aliyev",
            institution="ADA University",
            agreed_requests=3,
            institutional_email=True,
        )
        facts = _facts([ref], student=membership_a)
    assert len(facts) == 1
    assert facts[0].role_archetype == "research_supervisor"
    assert facts[0].shared_work_score >= 1


def test_preserve_clean_sections_keeps_projects_on_retry():
    base = CVContent(
        personal_information=PersonalInformation(
            full_name="Jane Doe", email="jane@example.com"
        ),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="University A",
            ),
        ),
        experience=(),
        research=(),
        projects=(
            ProjectEntry(
                title="MicroKatc",
                bullets=("Implemented stiff ODE integration.",),
            ),
        ),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )
    second = base.model_copy(update={"projects": ()})
    bad_verdict = ClaimVerdict(
        claim_path="education[0].degree_as_awarded",
        claim_text="PhD",
        verdict="UNSUPPORTED",
        fact_id=None,
    )
    merged = _preserve_clean_sections(base, (bad_verdict,), second, ())
    assert len(merged.projects) == 1
    assert merged.projects[0].title == "MicroKatc"


def test_content_warnings_forwards_europass_api_variant_and_templates_render_score_only():
    cv = CVContent(
        personal_information=PersonalInformation(
            full_name="Jane Doe", email="jane@example.com"
        ),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="University A",
                start_date=None,
                end_date="2024-06-01",
            ),
            EducationEntry(
                degree_as_awarded="MSc",
                institution_original="University B",
                start_date="2024-09-01",
                end_date="2026-06-01",
            ),
        ),
        experience=(
            ExperienceEntry(
                employer="Org A",
                title="Intern",
                start_date=None,
                end_date=None,
                bullets=("Did research.",),
            ),
            ExperienceEntry(
                employer="Org B",
                title="Engineer",
                start_date="2025-01-01",
                end_date="2025-06-01",
                bullets=("Built system.",),
            ),
        ),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(
            LanguageEntry(
                language="English",
                cefr_level="C1",
                test_name=None,
                test_score="IELTS 7.5",
            ),
        ),
        document_language="en",
    )
    rule = ConstraintRule(
        rule_id="R-099",
        key="date_of_issue_required",
        value=True,
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="Include date of issue.",
    )
    warnings = content_warnings(cv, (rule,), variant="EUROPASS_API", today=date(2026, 10, 1))
    assert any(w.rule.key == "date_of_issue_required" for w in warnings)

    # Undated entries sort cleanly in SISGP and Australia Awards without TypeError
    sisgp_artifact = render_sisgp(cv)
    assert sisgp_artifact.pdf_bytes is not None
    aa_data = australia_awards_fields(cv, today=date(2026, 10, 1))
    assert aa_data["work_experience"][0]["organisation_name"] == "Org B"

    # test_score renders even when test_name is None in STANDARD and EUROPASS templates
    for variant in ("STANDARD", "EUROPASS"):
        artifact = render_cv(cv, variant=variant)
        assert artifact.pdf_bytes is not None


def test_gap_answer_normalizes_doi_url_and_routes_non_doi_url(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        pub1 = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.PUBLICATION,
            payload={"title": "Paper One", "year": 2025},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:pub1",
            created_by=membership_a,
        )
        pub2 = VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.PUBLICATION,
            payload={"title": "Paper Two", "year": 2025},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:pub2",
            created_by=membership_a,
        )
        q1 = GapQuestion(
            kind=Kind.MISSING_PUBLICATION_DETAIL,
            fact_id=pub1.id,
            payload_key="doi",
            prompt="DOI?",
            evidence="Paper One",
        )
        q2 = GapQuestion(
            kind=Kind.MISSING_PUBLICATION_DETAIL,
            fact_id=pub2.id,
            payload_key="doi",
            prompt="DOI?",
            evidence="Paper Two",
        )
        written = answer_questions(
            (
                (q1, "https://doi.org/10.1021/acs.jctc.5b00123"),
                (q2, "https://arxiv.org/abs/2501.00001"),
            ),
            student=membership_a,
        )
    by_supersedes = {f.supersedes_id: f.payload for f in written}
    assert by_supersedes[pub1.id]["doi"] == "10.1021/acs.jctc.5b00123"
    assert by_supersedes[pub2.id]["url"] == "https://arxiv.org/abs/2501.00001"
    assert "doi" not in by_supersedes[pub2.id]
