"""Task 11: the three requirement panes, read-only, from the catalog."""

import pytest
from django.utils import timezone

from apps.funding import models as catalog
from apps.funding.requirements import (
    ENFORCED_AT_RENDER,
    NOT_YET_CHECKED,
    WRITTEN_TO_AND_CHECKED,
    YOUR_ACTION,
    letter_kit_steps,
    program_requirements,
)


def _programme() -> catalog.Program:
    institution = catalog.Institution.objects.create(
        canonical_key="institution:requirements",
        name="Example University",
        country_code="DE",
        official_website="https://example.test",
    )
    return catalog.Program.objects.create(
        institution=institution,
        canonical_key="program:requirements",
        name="MSc Example",
        campus_name="Main Campus",
        city="Berlin",
        country_code="DE",
        location_key="de:berlin",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )


def _prompt(programme: catalog.Program) -> catalog.ApplicationPrompt:
    return catalog.ApplicationPrompt.objects.create(
        programme=programme,
        cycle="2027",
        source_url="https://example.test/apply",
        confidence=0.0,
        source=catalog.ApplicationPrompt.Source.EXTRACTED,
        funder_kind=catalog.ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=catalog.ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        document_language="en",
        letter_max_words=500,
        letter_handwritten=True,
        letter_shape_sources={
            "max_words": {
                "text": "no more than 500 words",
                "source_url": "https://example.test/apply",
            },
            "handwritten": {
                "text": "The letter must be handwritten.",
                "source_url": "https://example.test/apply",
            },
        },
        letter_written_requirements=[
            {"text": "Write in the third person.", "source_url": "https://example.test/apply"}
        ],
        letter_student_actions=[
            {"text": "Sign it in ink.", "source_url": "https://example.test/apply"}
        ],
    )


def _statement(programme: catalog.Program, text: str, kind: str) -> catalog.ProgramStatement:
    source, _ = catalog.OfficialSource.objects.get_or_create(
        canonical_url="https://example.test/programme",
        defaults={
            "publisher": "Example University",
            "source_type": catalog.OfficialSource.Type.PROGRAM,
        },
    )
    snapshot, _ = catalog.OfficialSourceSnapshot.objects.get_or_create(
        source=source,
        sha256="a" * 64,
        defaults=dict(
            s3_key="official-sources/programme",
            s3_version_id="1",
            final_url=source.canonical_url,
            redirect_chain=[],
            retrieved_at=timezone.now(),
            admissions_cycle="2027",
            content_type="text/html",
            byte_size=1,
        ),
    )
    return catalog.ProgramStatement.objects.create(
        program=programme,
        snapshot=snapshot,
        kind=kind,
        requirement=catalog.ProgramStatement.Requirement.REQUIRED,
        text=text,
        label="Example",
    )


@pytest.mark.django_db
def test_the_letter_pane_shows_each_rule_with_its_sentence_and_status() -> None:
    programme = _programme()
    _prompt(programme)
    panes = program_requirements(programme, cycle="2027")
    by_text = {item.text: item for item in panes.letter}
    assert by_text["no more than 500 words"].status == ENFORCED_AT_RENDER
    assert by_text["Write in the third person."].status == WRITTEN_TO_AND_CHECKED
    assert by_text["Sign it in ink."].status == YOUR_ACTION
    # A shape field only the applicant can perform is their action, not ours.
    assert by_text["The letter must be handwritten."].status == YOUR_ACTION
    assert all(item.source_url == "https://example.test/apply" for item in panes.letter)


@pytest.mark.django_db
def test_the_applicant_pane_carries_no_verdict_yet() -> None:
    programme = _programme()
    _statement(programme, "A degree in chemistry.", catalog.ProgramStatement.Kind.COMPETENCY)
    _statement(programme, "C1 German.", catalog.ProgramStatement.Kind.LANGUAGE)
    # A DOCUMENT statement is about the application, not about the applicant.
    _statement(programme, "Submit a CV.", catalog.ProgramStatement.Kind.DOCUMENT)
    panes = program_requirements(programme, cycle="2027")
    assert {item.status for item in panes.applicant} == {NOT_YET_CHECKED}
    assert {item.text for item in panes.applicant} == {"A degree in chemistry.", "C1 German."}
    assert all(item.statement_id for item in panes.applicant)


@pytest.mark.django_db
def test_kit_steps_are_the_same_objects_the_letter_pane_shows() -> None:
    programme = _programme()
    prompt = _prompt(programme)
    panes = program_requirements(programme, cycle="2027")
    assert letter_kit_steps(prompt) == tuple(
        item for item in panes.letter if item.status == YOUR_ACTION
    )
    assert letter_kit_steps(prompt)


@pytest.mark.django_db
def test_a_cycle_nobody_has_read_yet_has_no_letter_pane() -> None:
    programme = _programme()
    _prompt(programme)
    panes = program_requirements(programme, cycle="2028")
    assert panes.letter == ()


@pytest.mark.django_db
def test_the_cv_pane_carries_the_cv_paths_own_derivations() -> None:
    programme = _programme()
    programme.cv_format_requirement = catalog.Program.CVFormatRequirement.EUROPASS_REQUIRED
    programme.cv_format_source_url = "https://example.test/cv"
    programme.cv_constraints = [
        {
            "rule_id": "PAGE-1",
            "key": "max_pages",
            "value": 2,
            "enforcement": "ADVISORY_HIGH_RISK",
            "rule_text": "The CV must not exceed two pages.",
            "source_url": "https://example.test/cv",
        }
    ]
    programme.cv_directives = ["emphasise(research)"]
    programme.save()
    panes = program_requirements(programme, cycle="2027")
    assert [item.text for item in panes.cv] == [
        "europass_required",
        "The CV must not exceed two pages.",
        "emphasise(research)",
    ]


@pytest.mark.django_db
def test_a_field_nothing_reads_does_not_claim_to_be_enforced() -> None:
    """`document_required` and `file_bundle` are stored and acted on by nothing."""
    from apps.funding.requirements import RECORDED_NOT_ACTED_ON

    programme = _programme()
    prompt = _prompt(programme)
    prompt.letter_shape_sources = dict(prompt.letter_shape_sources) | {
        "file_bundle": {"text": "Send the CV and the letter as one PDF.", "source_url": "u"}
    }
    prompt.save(update_fields=["letter_shape_sources"])
    panes = program_requirements(programme, cycle="2027")
    by_text = {item.text: item for item in panes.letter}
    assert by_text["Send the CV and the letter as one PDF."].status == RECORDED_NOT_ACTED_ON


@pytest.mark.django_db
def test_a_stated_letter_language_is_enforced_when_the_letter_is_written() -> None:
    """letter_gates.check_language_mismatch refuses a letter in another language
    before anything is rendered, so the pane must not say "enforced at render"."""
    from apps.funding.requirements import ENFORCED_WHEN_WRITTEN

    programme = _programme()
    prompt = _prompt(programme)
    prompt.document_language = "de"
    prompt.letter_shape_sources = dict(prompt.letter_shape_sources) | {
        "document_language": {"text": "Bitte auf Deutsch.", "source_url": "u"}
    }
    prompt.save(update_fields=["document_language", "letter_shape_sources"])
    panes = program_requirements(programme, cycle="2027")
    by_text = {item.text: item for item in panes.letter}
    assert by_text["Bitte auf Deutsch."].status == ENFORCED_WHEN_WRITTEN
