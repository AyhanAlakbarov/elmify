"""§5.1 detection and composition. Rows are section-2-refined.md §4's measured table."""

from datetime import date
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.documents import cv_verbs
from apps.documents.cv_fixes import VERB_OPENER, subject_of
from apps.documents.cv_verbs import (
    LEAVE,
    Flagged,
    allowed_openers,
    choose_openers,
    compose,
    flagged_bullets,
    needs_opener,
    verb_fixes,
    without_first_person,
)
from apps.documents.schemas import CVContent, EducationEntry, ExperienceEntry, PersonalInformation
from apps.research.decisions import Answer, DecisionsUnavailable


@pytest.mark.parametrize(
    "line, flagged",
    [
        ("A map-agnostic framework that visualizes the chemical space of the dataset.", True),
        ("Python scripts for the cleaning of the lab data.", True),
        ("The best poster award, EuChemS 2024.", True),  # flagged; Jev should leave it
        ("Development of an automated framework for the group.", True),
        ("Engineered three PyTorch-based models.", False),
        ("Maintain the group's GPU cluster.", False),
        ("Develops the evaluation pipeline.", False),
        ("Tools: Python, RDKit.", False),
        ("Advanced Python course for 40 students.", False),  # -ed: a known miss
        ("I developed three PyTorch models.", False),  # the code-only "I" fix
        ("We built a robot with the team.", False),
        ("Responsible for managing the lab inventory.", False),
        ("In collaboration with Bosch, built a test rig.", False),
        ("3 papers under review.", False),
    ],
)
def test_needs_opener(line, flagged):
    assert needs_opener(line) is flagged


def test_the_first_person_is_dropped_and_nothing_added():
    assert without_first_person("I developed three PyTorch models.") == (
        "Developed three PyTorch models."
    )
    assert without_first_person("I am a fast learner.") is None


def test_a_stronger_verb_needs_the_entrys_own_words():
    modest = allowed_openers("Research Intern Helped with the models.")
    assert "led" not in modest and "built" not in modest and "worked_on" in modest
    did = allowed_openers("Research Intern Wrote the evaluation scripts.")
    assert "built" in did and "led" not in did
    led = allowed_openers("Team Lead Managed four students.")
    assert {"led", "built", "worked_on"} <= set(led)


def test_compose_keeps_every_other_character():
    line = "A map-agnostic framework that visualizes 10B+ compounds."
    assert compose(line, "built", present=False) == (
        "Built a map-agnostic framework that visualizes 10B+ compounds."
    )
    assert compose("PyTorch models for 3.88M molecules.", "built", present=False) == (
        "Built PyTorch models for 3.88M molecules."
    )
    assert compose("Python scripts for the lab.", "wrote", present=True) == (
        "Write Python scripts for the lab."
    )
    assert compose("x" * 495, "contributed_to", present=False) is None


def _cv(bullets, end=date(2025, 9, 1), title="Research Intern"):
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="j@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="MSc Chemistry",
                institution_original="University of Strasbourg",
            ),
        ),
        experience=(
            ExperienceEntry(
                employer="EPFL",
                title=title,
                start_date=date(2025, 6, 1),
                end_date=end,
                bullets=bullets,
            ),
        ),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )


def test_only_flagged_english_lines_are_returned():
    content = _cv(
        (
            "Wrote the evaluation scripts for the group.",
            "A framework for the visualisation of chemical space.",
        )
    )
    [item] = flagged_bullets(content)
    assert item.text == "A framework for the visualisation of chemical space."
    assert "built" in item.allowed and item.present is False


def test_a_non_english_cv_gets_nothing():
    content = _cv(
        (
            "Entwicklung eines Modells für die Gruppe und der Daten.",
            "Ein Rahmenwerk für die Visualisierung der Daten.",
        )
    )
    assert flagged_bullets(content) == ()


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


def _item(
    text="A framework for the visualisation of chemical space.",
    allowed=("worked_on", "built"),
):
    return Flagged(subject=f"s-{text}", text=text, allowed=allowed, present=False)


def _jev(value, confidence=0.97, states=None):
    def call(state, questions, *, model, provider):
        if states is not None:
            states.append(state)
        return {
            qid: Answer(
                id=qid,
                value=value,
                confidence=confidence,
                probabilities={value: confidence},
                model=model,
                provider=provider,
            )
            for qid in questions
        }

    return call


@pytest.fixture
def gate_on(settings):
    settings.CV_VERB_JEV_ENABLED = True
    settings.DECISIONS_PROVIDER = {"default": "typesafe"}


def test_a_confident_allowed_answer_is_used(gate_on):
    item = _item()
    assert choose_openers([item], student_id=uuid4(), client=_jev("built")) == {
        item.subject: "built"
    }


def test_doubt_keeps_the_line(gate_on):
    item = _item()
    assert choose_openers([item], student_id=uuid4(), client=_jev(LEAVE)) == {}
    cache.clear()
    assert choose_openers([item], student_id=uuid4(), client=_jev("built", 0.6)) == {}


def test_an_answer_outside_the_allowed_list_is_refused(gate_on):
    assert choose_openers([_item()], student_id=uuid4(), client=_jev("led")) == {}


def test_jev_sees_the_bullet_text_only(gate_on):
    states = []
    choose_openers([_item()], student_id=uuid4(), client=_jev("built", states=states))
    assert states == [{"bullets": {"b0": "A framework for the visualisation of chemical space."}}]


def test_a_cached_answer_is_not_asked_again(gate_on):
    student = uuid4()
    choose_openers([_item()], student_id=student, client=_jev("built"))
    states = []
    assert choose_openers([_item()], student_id=student, client=_jev("worked_on", states=states))
    assert states == []


def test_an_unavailable_jev_leaves_every_line(gate_on):
    def down(state, questions, *, model, provider):
        raise DecisionsUnavailable("down")

    assert choose_openers([_item()], student_id=uuid4(), client=down) == {}


def test_the_gate_off_asks_nothing(settings):
    settings.CV_VERB_JEV_ENABLED = False
    states = []
    assert choose_openers([_item()], student_id=uuid4(), client=_jev("built", states=states)) == {}
    assert states == []


def test_the_limiter_stops_the_call(gate_on, monkeypatch):
    monkeypatch.setattr(cv_verbs, "rate_limited", lambda *a, **k: True)
    states = []
    assert choose_openers([_item()], student_id=uuid4(), client=_jev("built", states=states)) == {}
    assert states == []


_NOUN = "A framework for the visualisation of chemical space."
_LINES = (
    "Wrote the evaluation scripts for the group.",
    _NOUN,
    "I trained the models on the cluster.",
)


def test_verb_fixes_change_only_the_opening(gate_on):
    content, fixes = verb_fixes(
        _cv(_LINES), student_id=uuid4(), undone=frozenset(), client=_jev("built")
    )
    assert content.experience[0].bullets == (
        "Wrote the evaluation scripts for the group.",
        "Built a framework for the visualisation of chemical space.",
        "Trained the models on the cluster.",
    )
    assert [(f.where, f.original) for f in fixes] == [
        ("experience[0].bullets[1]", _NOUN),
        ("experience[0].bullets[2]", "I trained the models on the cluster."),
    ]


def test_an_undone_verb_fix_prints_the_original(gate_on):
    undone = frozenset({subject_of(VERB_OPENER, _NOUN)})
    content, fixes = verb_fixes(
        _cv(_LINES), student_id=uuid4(), undone=undone, client=_jev("built")
    )
    assert content.experience[0].bullets[1] == _NOUN
    assert fixes[0].undone is True


def test_the_i_fix_runs_with_the_gate_off(settings):
    settings.CV_VERB_JEV_ENABLED = False
    content, fixes = verb_fixes(_cv(_LINES), student_id=uuid4(), undone=frozenset())
    assert content.experience[0].bullets[1] == _NOUN
    assert content.experience[0].bullets[2] == "Trained the models on the cluster."
