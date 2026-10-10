import pytest
from django.core.management import call_command

from apps.funding.models import ApplicationPrompt

pytestmark = pytest.mark.django_db


def _fixture(**overrides):
    base = {
        "lookup": {"canonical_key": "daad-epos-cs"},
        "cycle": "2027/28",
        "source_url": "https://daad.de/en/studying-in-germany/scholarships/",
        "confidence": 1.0,
        "verified_for_cycle": "2027",
        "funder_kind": ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP,
        "structure": ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        "archetypes": ["WHY_PROGRAMME", "WHY_COUNTRY", "CAREER_PLAN_RETURN"],
        "questions": [],
        "programme_evidence": {},
        "document_language": "en",
        "header_block_required": False,
    }
    base.update(overrides)
    return base


def test_loader_creates_verified_prompt_for_mapped_programme(program_factory, monkeypatch):
    program = program_factory(canonical_key="daad-epos-cs")
    from apps.funding import letter_prompt_fixtures

    monkeypatch.setitem(letter_prompt_fixtures.LETTER_PROMPT_FIXTURES, "daad-epos-cs", _fixture())
    call_command("load_application_prompts")
    prompt = ApplicationPrompt.objects.get(programme=program)
    assert prompt.source == ApplicationPrompt.Source.VERIFIED
    assert prompt.structure == ApplicationPrompt.Structure.CONTINUOUS_LETTER


def test_loader_updates_existing_verified_row_for_same_cycle(program_factory, monkeypatch):
    program = program_factory(canonical_key="daad-epos-cs")
    ApplicationPrompt.objects.create(
        programme=program,
        cycle="2027/28",
        source_url="",
        confidence=0.5,
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP,
        structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET,
        archetypes=[],
        questions=[],
        programme_evidence={},
        document_language="en",
    )
    from apps.funding import letter_prompt_fixtures

    monkeypatch.setitem(
        letter_prompt_fixtures.LETTER_PROMPT_FIXTURES,
        "daad-epos-cs",
        _fixture(source_url="https://daad.de", archetypes=["WHY_PROGRAMME"]),
    )
    call_command("load_application_prompts")
    assert ApplicationPrompt.objects.filter(programme=program, cycle="2027/28").count() == 1
    assert (
        ApplicationPrompt.objects.get(programme=program).structure
        == ApplicationPrompt.Structure.CONTINUOUS_LETTER
    )


def test_loader_skips_a_fixture_whose_programme_is_missing(monkeypatch, capsys):
    """PF-18: Program.objects.get() with zero matches must be skipped with a
    clear stderr line naming the missing lookup, never raise."""
    from apps.funding import letter_prompt_fixtures

    monkeypatch.setitem(
        letter_prompt_fixtures.LETTER_PROMPT_FIXTURES,
        "nope",
        _fixture(lookup={"canonical_key": "no-such-programme"}, cycle="2027"),
    )
    call_command("load_application_prompts")  # must not raise
    err = capsys.readouterr().err
    assert "nope" in err
    assert "no-such-programme" in err
    assert not ApplicationPrompt.objects.exists()


def test_loader_fails_loudly_on_an_ambiguous_lookup_and_still_loads_the_rest(
    program_factory, institution_factory, monkeypatch, capsys
):
    """PF-18: canonical_key alone isn't unique on Program (only the
    (institution, canonical_key, location_key) triple is), so two programmes
    sharing one under different institutions makes .get() raise
    MultipleObjectsReturned. The loader must name the key and how many
    candidates matched, never silently pick one, and must not abort the
    fixtures after it."""
    program_factory(canonical_key="ambiguous-key", institution=institution_factory())
    program_factory(canonical_key="ambiguous-key", institution=institution_factory())
    good_program = program_factory(canonical_key="daad-epos-cs")
    from apps.funding import letter_prompt_fixtures

    monkeypatch.setitem(
        letter_prompt_fixtures.LETTER_PROMPT_FIXTURES,
        "ambiguous",
        _fixture(lookup={"canonical_key": "ambiguous-key"}, cycle="2027"),
    )
    monkeypatch.setitem(
        letter_prompt_fixtures.LETTER_PROMPT_FIXTURES, "daad-epos-cs", _fixture()
    )
    call_command("load_application_prompts")  # must not raise
    err = capsys.readouterr().err
    assert "ambiguous" in err
    assert "ambiguous-key" in err
    assert "2" in err
    assert not ApplicationPrompt.objects.filter(programme__canonical_key="ambiguous-key").exists()
    assert ApplicationPrompt.objects.filter(programme=good_program).exists()


def test_loader_derives_immigration_true_for_immigration_authority_funder_kind(
    program_factory, monkeypatch
):
    program = program_factory(canonical_key="daad-epos-cs")
    from apps.funding import letter_prompt_fixtures

    monkeypatch.setitem(
        letter_prompt_fixtures.LETTER_PROMPT_FIXTURES,
        "daad-epos-cs",
        _fixture(funder_kind=ApplicationPrompt.FunderKind.IMMIGRATION_AUTHORITY),
    )
    call_command("load_application_prompts")
    assert ApplicationPrompt.objects.get(programme=program).immigration is True


def test_loader_derives_immigration_false_for_non_immigration_funder_kind(
    program_factory, monkeypatch
):
    program = program_factory(canonical_key="daad-epos-cs")
    from apps.funding import letter_prompt_fixtures

    monkeypatch.setitem(
        letter_prompt_fixtures.LETTER_PROMPT_FIXTURES,
        "daad-epos-cs",
        _fixture(funder_kind=ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP),
    )
    call_command("load_application_prompts")
    assert ApplicationPrompt.objects.get(programme=program).immigration is False
