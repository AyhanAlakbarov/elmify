import pytest

from apps.funding.models import ApplicationPrompt, Program

pytestmark = pytest.mark.django_db


def test_program_letter_required_defaults_unknown(program_factory):
    program = program_factory()
    assert program.letter_required == Program.LetterRequired.UNKNOWN


def test_application_prompt_created_for_programme(program_factory):
    program = program_factory()
    prompt = ApplicationPrompt.objects.create(
        programme=program, cycle="2027/28", source_url="https://daad.de/epos",
        confidence=1.0, verified_for_cycle="2027", source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        archetypes=["WHY_PROGRAMME", "WHY_COUNTRY", "CAREER_PLAN_RETURN"],
        questions=[], programme_evidence={}, document_language="en",
    )
    assert prompt.programme_id == program.id
    assert "WHY_COUNTRY" in prompt.archetypes


def test_application_prompt_pairing_is_self_referential(program_factory):
    program = program_factory()
    sop = ApplicationPrompt.objects.create(
        programme=program, cycle="2027", source_url="", confidence=0.9,
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.TWO_STATEMENTS,
        archetypes=["ACADEMIC_PREPARATION"], questions=[], programme_evidence={},
        document_language="en",
    )
    phs = ApplicationPrompt.objects.create(
        programme=program, cycle="2027", source_url="", confidence=0.9,
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.TWO_STATEMENTS,
        archetypes=["PERSONAL_BACKGROUND"], questions=[], programme_evidence={},
        document_language="en",
        paired_with=sop,
    )
    assert phs.paired_with_id == sop.id
