from uuid import uuid4

import pytest
from pypdf import PdfReader

from apps.documents.constraints import ConstraintRule, Enforcement
from apps.documents.cv_evidence import (
    annotate_readings_with_targets,
    apply_cv_evidence,
    match_reading_target,
)
from apps.documents.europass import europass_payload
from apps.documents.evidence.readings import UsableBullet, UsableReading
from apps.documents.render import (
    PreflightBlocked,
    render_cv,
    without_banned_content,
)
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    PersonalInformation,
    ResearchEntry,
)


def _base_cv(**overrides) -> CVContent:
    base = dict(
        personal_information=PersonalInformation(
            full_name="Jane Doe", email="jane@example.com"
        ),
        education=(
            EducationEntry(
                degree_as_awarded="MSc Chemistry",
                institution_original="University of Strasbourg",
                city="Strasbourg",
                country="FR",
                start_date="2023-09-01",
                end_date="2025-06-01",
                thesis_title="AZIMUTH: Machine Learning for Catalyst Discovery",
            ),
        ),
        experience=(
            ExperienceEntry(
                employer="EPFL",
                group="Schwaller Lab",
                title="Research Intern",
                start_date="2025-02-01",
                end_date="2025-07-01",
                bullets=("Built reaction data pipeline.",),
            ),
        ),
        research=(
            ResearchEntry(
                thesis_title="AZIMUTH: Machine Learning for Catalyst Discovery",
                institution="University of Strasbourg",
                start_date="2024-09-01",
                end_date="2025-06-01",
            ),
        ),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )
    base.update(overrides)
    return CVContent(**base)


def _reading(**overrides) -> UsableReading:
    defaults = dict(
        source="github",
        url="https://github.com/0rkhann/MicroKatc",
        document_id=None,
        summary="A kinetic solver for microkinetic modelling.",
        kind="project",
        names=("MicroKatc",),
        first_commit="2024-08-01",
        last_commit="2025-02-01",
        bullets=(
            UsableBullet("Implemented stiff ODE integration.", ("ODE",), "supported"),
            UsableBullet("Unverified speed claim.", ("fast",), "rejected"),
        ),
        repo="0rkhann/MicroKatc",
        methods="Microkinetic modelling with stiff ODE solvers.",
        outcomes="Validated across 12 catalytic cycles.",
        owner_type="User",
        owner_name="Orkhan",
        commits=15,
    )
    defaults.update(overrides)
    return UsableReading(**defaults)


def test_org_repo_matches_experience_entry_and_appends_supported_bullets_only():
    cv = _base_cv()
    org_reading = _reading(
        repo="schwaller-lab/rxn-pipeline",
        owner_type="Organization",
        owner_name="Schwaller Lab",
        commits=5,
        names=(),
        bullets=(
            UsableBullet("Built reaction data pipeline.", ("pipeline",), "supported"),
            UsableBullet("Benchmarked 4 transformer tokenizers.", ("4",), "supported"),
            UsableBullet("Added SMILES augmentation.", ("SMILES",), "supported"),
            UsableBullet("Rejected claim.", ("none",), "rejected"),
        ),
    )
    assert match_reading_target(org_reading, cv) == ("experience", 0)
    updated, fixes = apply_cv_evidence(cv, (org_reading,))
    # Duplicate bullet skipped; at most 2 supported bullets added; rejected skipped.
    assert updated.experience[0].bullets == (
        "Built reaction data pipeline.",
        "Benchmarked 4 transformer tokenizers.",
        "Added SMILES augmentation.",
    )
    assert updated.projects == ()
    assert fixes == (
        {
            "kind": "added_from_github",
            "reading": "github:schwaller-lab/rxn-pipeline",
            "target": "experience:0",
        },
    )


def test_thesis_pdf_wins_over_thesis_repo_on_research_target_and_shared_thesis_is_one_target():
    cv = _base_cv()
    repo_reading = _reading(
        source="github",
        repo="0rkhann/azimuth",
        names=("AZIMUTH: Machine Learning for Catalyst Discovery",),
        methods="Repo methods.",
        outcomes="Repo outcomes.",
    )
    pdf_reading = _reading(
        source="pdf",
        url=None,
        repo="",
        document_id=uuid4(),
        names=("AZIMUTH: Machine Learning for Catalyst Discovery",),
        methods="PDF thesis methods.",
        outcomes="PDF thesis outcomes.",
    )
    # Education and research share the same thesis_title -> still 1 target ("research", 0)
    assert match_reading_target(repo_reading, cv) == ("research", 0)
    assert match_reading_target(pdf_reading, cv) == ("research", 0)

    updated, fixes = apply_cv_evidence(cv, (repo_reading, pdf_reading))
    assert updated.research[0].methods == "PDF thesis methods."
    assert updated.research[0].outcomes == "PDF thesis outcomes."
    assert updated.projects == ()
    assert fixes[0]["kind"] == "added_from_pdf"


def test_unmatched_project_becomes_side_project_and_renders_across_variants():
    import io

    cv = _base_cv()
    side = _reading()
    updated, fixes = apply_cv_evidence(cv, (side,))
    assert len(updated.projects) == 1
    assert updated.projects[0].title == "MicroKatc"
    assert updated.projects[0].bullets == ("Implemented stiff ODE integration.",)
    assert fixes == (
        {
            "kind": "added_from_github",
            "reading": "github:0rkhann/microkatc",
            "target": "projects",
        },
    )

    annotated = annotate_readings_with_targets((side,), cv)
    assert annotated[0].matched_target == "projects"

    for variant in ("STANDARD", "GERMAN_TABULAR", "EUROPASS"):
        artifact = render_cv(updated, variant=variant)
        assert artifact.pdf_bytes is not None
        text = "".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(artifact.pdf_bytes)).pages
        )
        assert "MicroKatc" in text
        assert "Implemented stiff ODE integration" in text

    payload = europass_payload(updated)
    titles = [p["title"] for p in payload["profile"]["projects"]]
    assert titles == [
        "AZIMUTH: Machine Learning for Catalyst Discovery",
        "MicroKatc",
    ]


def test_hyperlinks_ban_strips_and_checks_project_url():
    cv = _base_cv()
    updated, _ = apply_cv_evidence(cv, (_reading(),))
    assert updated.projects[0].url == "https://github.com/0rkhann/MicroKatc"

    rule = ConstraintRule(
        rule_id="R-017",
        key="prohibited_content",
        value=["hyperlinks"],
        enforcement=Enforcement.BINDING,
        rule_text="No hyperlinks.",
    )
    with pytest.raises(PreflightBlocked):
        render_cv(updated, variant="STANDARD", constraints=(rule,))

    cleaned = without_banned_content(updated, (rule,))
    assert cleaned.projects[0].url is None
    artifact = render_cv(cleaned, variant="STANDARD", constraints=(rule,))
    assert artifact.pdf_bytes is not None
