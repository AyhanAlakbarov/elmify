"""Track must come from the programme, not from how content was bucketed.

The defect these pin was found by rendering a real applicant's CV: four
research positions in academic groups (Varnek, Schwaller, Pollice, Bo). The
schema forced each into `research` or `experience`, and `bool(content.research)`
then decided the track -- so the same body of work resolved max_pages=3 when one
position was filed as research and max_pages=2 when all four were filed as
experience. Nobody made that choice, and it changed what the engine enforced.
"""

from datetime import date

import pytest

from apps.documents.catalog_seed import SEED_RULES
from apps.documents.constraints import resolve_rules, resolve_track
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    PersonalInformation,
    ResearchEntry,
)
from apps.funding.models import CatalogRule, Institution, Program

pytestmark = pytest.mark.django_db


def _content(**over):
    kw: dict = dict(
        personal_information=PersonalInformation(full_name="A B", email="a@example.test"),
        education=(
            EducationEntry(
                degree_as_awarded="MSc",
                institution_original="UNISTRA",
                city="Strasbourg",
                country="FR",
                start_date=date(2024, 9, 1),
            ),
        ),
        research=(),
        experience=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(LanguageEntry(language="English", cefr_level="C1"),),
        document_language="en",
    )
    kw.update(over)
    return CVContent(**kw)


def _position(supervisor=None):
    return ExperienceEntry(
        employer="University of Strasbourg",
        title="Master's Thesis",
        supervisor=supervisor,
        city="Strasbourg",
        country="FR",
        start_date=date(2026, 1, 1),
        bullets=("Hierarchical GTM for ultra-large chemical space visualization.",),
    )


def _thesis():
    return ResearchEntry(
        thesis_title="AZIMUTH",
        supervisor="Prof. Alexandre Varnek",
        institution="UNISTRA",
        city="Strasbourg",
        country="FR",
        start_date=date(2026, 1, 1),
    )


def _programme(track=""):
    institution = Institution.objects.create(
        canonical_key=f"inst-track-{track or 'none'}",
        name="FAU Erlangen-Nuernberg",
        country_code="DE",
        official_website="https://www.fau.eu/",
    )
    return Program.objects.create(
        institution=institution,
        canonical_key=f"prog-track-{track or 'none'}",
        name="MSc Chemistry",
        campus_name="Erlangen",
        city="Erlangen",
        country_code="DE",
        location_key="de:erlangen",
        degree_level="MASTER",
        academic_track=track,
        teaching_languages=["English"],
        duration_months=24,
    )


def _seed_track_rules():
    for row in (r for r in SEED_RULES if r["scope_kind"] == "TRACK"):
        CatalogRule.objects.create(**row)


def test_an_experience_entry_can_name_its_supervisor():
    """A research position is both a post and a project. `research` has no
    employer/title/bullets and `experience` had no supervisor, so neither
    bucket could hold one faithfully and coherent work got split in two."""
    entry = _position(supervisor="Prof. Alexandre Varnek")
    assert entry.supervisor == "Prof. Alexandre Varnek"
    assert _position().supervisor is None


def test_the_programme_decides_the_track_not_the_content_bucketing():
    programme = _programme(track=Program.AcademicTrack.RESEARCH)
    everything_in_experience = _content(experience=(_position("Prof. Varnek"),))
    assert resolve_track(programme, everything_in_experience) == "research"


def test_an_explicit_taught_track_wins_over_a_research_entry():
    programme = _programme(track=Program.AcademicTrack.TAUGHT)
    assert resolve_track(programme, _content(research=(_thesis(),))) == "taught"


def test_the_content_heuristic_still_applies_when_the_programme_is_silent():
    """Unchanged behaviour where nothing is known: a programme whose track has
    not been established falls back to the old signal rather than defaulting
    every research applicant to the taught page limit."""
    programme = _programme()
    assert resolve_track(programme, _content(research=(_thesis(),))) == "research"
    assert resolve_track(programme, _content(experience=(_position(),))) == "taught"
    assert resolve_track(None, _content(research=(_thesis(),))) == "research"


def test_moving_a_position_between_sections_no_longer_changes_the_page_limit():
    """The regression this whole change exists for. Same four positions, same
    programme; only the bucket differs."""
    _seed_track_rules()
    programme = _programme(track=Program.AcademicTrack.RESEARCH)

    as_research = _content(research=(_thesis(),), experience=(_position("Prof. Varnek"),))
    as_experience = _content(experience=(_position("Prof. Varnek"), _position("Prof. Schwaller")))

    def _max_pages(content):
        rules = resolve_rules(programme, None, content=content)
        return [r.value for r in rules if r.key == "max_pages"]

    assert _max_pages(as_research) == _max_pages(as_experience) == [3]
