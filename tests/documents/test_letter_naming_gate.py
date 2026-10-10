"""Task 9: when the page forbids naming, a name that resolves blocks."""

import pytest

from apps.documents.letter_gates import GateCode, check_naming_forbidden, run_letter_gates
from apps.documents.letter_schemas import LetterContent, LetterUnit


def _content(text: str) -> LetterContent:
    return LetterContent(
        language="en", units=(LetterUnit(archetype="WHY_PROGRAMME", text=text),)
    )


_NAMES_A_PROFESSOR = _content(
    "I want to work with Professor Jane Roe in the Robotics Group at Example University."
)
_NAMES_A_CITY = _content("I studied in New York before applying to this programme.")


def test_a_named_professor_blocks_when_the_page_forbids_naming() -> None:
    violations = check_naming_forbidden(
        _NAMES_A_PROFESSOR,
        naming="FORBIDDEN",
        institution_names=frozenset({"Example University"}),
        research_names=frozenset({"Professor Jane Roe", "Robotics Group"}),
    )
    assert [v.code for v in violations] == [GateCode.NAMING_FORBIDDEN] * 3


def test_nothing_blocks_when_the_page_does_not_forbid_naming() -> None:
    for naming in ("INVITED", "REQUIRED", "UNSTATED"):
        assert (
            check_naming_forbidden(
                _NAMES_A_PROFESSOR,
                naming=naming,
                institution_names=frozenset(),
                research_names=frozenset({"Professor Jane Roe"}),
            )
            == ()
        )


def test_an_unrelated_capitalised_phrase_does_not_block() -> None:
    """A city is a proper noun and not a name of the target institution."""
    assert (
        check_naming_forbidden(
            _NAMES_A_CITY,
            naming="FORBIDDEN",
            institution_names=frozenset({"Example University"}),
            research_names=frozenset(),
        )
        == ()
    )


def test_the_match_ignores_case_and_reports_the_letter_s_own_wording() -> None:
    violations = check_naming_forbidden(
        _content("My work follows the ROBOTICS GROUP closely."),
        naming="FORBIDDEN",
        institution_names=frozenset(),
        research_names=frozenset({"Robotics Group"}),
    )
    assert len(violations) == 1
    assert "ROBOTICS GROUP" in violations[0].detail


def test_the_gate_runs_inside_run_letter_gates() -> None:
    violations = run_letter_gates(
        _NAMES_A_PROFESSOR,
        forbidden_names=frozenset(),
        questions=[],
        header_block_required=False,
        document_language="en",
        naming="FORBIDDEN",
        institution_names=frozenset({"Example University"}),
        research_names=frozenset({"Professor Jane Roe"}),
    )
    assert GateCode.NAMING_FORBIDDEN in {v.code for v in violations}


def test_run_letter_gates_keeps_working_without_the_new_arguments() -> None:
    """Every existing caller passes neither; the gate must default to silent."""
    violations = run_letter_gates(
        _NAMES_A_PROFESSOR,
        forbidden_names=frozenset(),
        questions=[],
        header_block_required=False,
        document_language="en",
    )
    assert GateCode.NAMING_FORBIDDEN not in {v.code for v in violations}


@pytest.mark.django_db
def test_the_names_come_from_the_programme_we_already_hold() -> None:
    """The gate resolves against catalog rows, never a hand-kept list."""
    from apps.documents.letters import _target_names
    from apps.funding.models import ApplicationPrompt

    from .conftest import make_program

    programme = make_program()
    prompt = ApplicationPrompt.objects.create(
        programme=programme,
        cycle="2027",
        source_url="https://stub.example.test/apply",
        confidence=0.0,
        source=ApplicationPrompt.Source.EXTRACTED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        document_language="en",
    )
    institutions, research = _target_names(prompt)
    assert institutions == frozenset({"Stub University"})
    assert research == frozenset()


def _blocked(text: str, *, institutions=frozenset(), research=frozenset()) -> list[str]:
    return [
        v.detail
        for v in check_naming_forbidden(
            _content(text),
            naming="FORBIDDEN",
            institution_names=frozenset(institutions),
            research_names=frozenset(research),
        )
    ]


def test_an_ordinary_proper_noun_from_the_page_is_not_a_name() -> None:
    """The first version harvested every capitalised phrase from the
    statements, so "I enclose my Curriculum Vitae" was blocked with no exit."""
    from apps.documents.letter_gates import names_worth_guarding

    statement = "Applicants must submit a Curriculum Vitae and a Motivation Letter in English."
    assert names_worth_guarding(statement) == set()
    assert names_worth_guarding("The programme starts in the Winter Semester.") == set()


def test_a_sentence_opening_on_the_university_does_not_mint_a_name() -> None:
    from apps.documents.letter_gates import names_worth_guarding

    assert names_worth_guarding("The University welcomes applications.") == set()
    assert _blocked("The University I attended taught me statistics.") == []


def test_a_named_group_survives_its_connectors_and_its_diacritics() -> None:
    from apps.documents.letter_gates import names_worth_guarding

    statement = "Research happens at the Institute for Artificial Intelligence."
    assert names_worth_guarding(statement) == {"Institute for Artificial Intelligence"}
    assert names_worth_guarding("The Müller Lab studies robotics.") == {"Müller Lab"}
    assert _blocked("I admire the Müller Lab.", research={"Müller Lab"})


def test_an_institution_name_matches_however_the_sentence_carries_it() -> None:
    """Phrase equality could not see the commonest shape of a real name."""
    assert _blocked(
        "I want to study at the Technical University of Munich.",
        institutions={"Technical University of Munich"},
    )
    assert _blocked("Sorbonne is where I want to be.", institutions={"Sorbonne"})
    assert _blocked("I studied in New York.", institutions={"Technical University of Munich"}) == []


def test_a_name_broken_by_a_line_break_still_blocks() -> None:
    """Model prose wraps, and the name is the same name."""
    assert _blocked("I follow the Robotics\nGroup closely.", research={"Robotics Group"})


def test_the_salutation_is_scanned_with_the_units() -> None:
    """"Dear Professor Jane Roe," is the first place a do-not-name rule looks."""
    violations = check_naming_forbidden(
        LetterContent(
            language="en",
            header_block="Dear Professor Jane Roe,",
            units=(LetterUnit(archetype="WHY_PROGRAMME", text="I am applying."),),
        ),
        naming="FORBIDDEN",
        institution_names=frozenset(),
        research_names=frozenset({"Professor Jane Roe"}),
    )
    assert [v.unit_archetype for v in violations] == ["HEADER_BLOCK"]


def test_a_title_abbreviation_does_not_break_the_name() -> None:
    """PR review: "Prof. Dr. Jane Roe" -- the dominant German form -- guarded
    nothing, because each period closed a one-word run and "Jane Roe" is not
    title-led."""
    from apps.documents.letter_gates import names_worth_guarding

    sentence = "Please contact Prof. Dr. Jane Roe before applying."
    assert names_worth_guarding(sentence) == {"Prof. Dr. Jane Roe"}
    assert _blocked(sentence, research={"Prof. Dr. Jane Roe"})


def test_a_sentence_that_really_ends_does_not_glue_onto_the_next() -> None:
    """Only a title abbreviates this way, so the period rule cannot run two
    sentences together."""
    from apps.documents.letter_gates import capitalised_phrases

    assert capitalised_phrases("I met Jane Roe. The University welcomed me.") == ["Jane Roe"]
    # And a title at a real sentence end keeps the next sentence's name apart.
    assert capitalised_phrases("Write to Prof. Roe. The Robotics Group replies.") == [
        "Prof. Roe",
        "Robotics Group",
    ]
