"""Task 10: a requirement no column can type is written to, then checked."""

from typing import Any

import pytest

from apps.documents.letter_schemas import LetterContent, LetterUnit
from apps.documents.letter_verification import RequirementVerdicts, check_written_requirements


@pytest.fixture(autouse=True)
def _second_family_allowed(settings):
    """Most of this module tests the two-family logic, so it is switched on.

    The default is OFF and is asserted by its own two tests below: a student's
    letter does not reach a second model vendor because a caller passed a
    client (branch security review).
    """
    settings.LETTER_JUDGE_SECOND_FAMILY = True


_REQUIREMENTS = (
    {"text": "Write in the third person.", "source_url": "u"},
    {"text": "Explain your choice of supervisor.", "source_url": "u"},
)


def _content() -> LetterContent:
    return LetterContent(
        language="en",
        units=(LetterUnit(archetype="WHY_PROGRAMME", text="I am applying because of the lab."),),
    )


class _Reading:
    """A parsed response, in the shape each SDK hands its caller back."""

    def __init__(self, verdicts: RequirementVerdicts) -> None:
        self.output_parsed = verdicts
        self.parsed_output = verdicts
        self.stop_reason = "end_turn"
        self.status = "completed"


class _Fake:
    def __init__(self, *answers: bool | None) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.seen: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> object:
        self.seen.append(kwargs)
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        if answer is None:  # refused, cut off or off-schema
            return _Refusal()
        return _Reading(
            RequirementVerdicts.model_validate(
                {
                    "verdicts": [
                        {"index": index, "satisfied": answer}
                        for index in range(len(_REQUIREMENTS))
                    ]
                }
            )
        )


class _Refusal:
    output_parsed = None
    parsed_output = None
    stop_reason = "max_tokens"
    status = "incomplete"


def _check(parser: _Fake, claude: _Fake | None, requirements=_REQUIREMENTS) -> tuple[str, ...]:
    return check_written_requirements(
        _content(), requirements, parser=parser, claude=claude, actor_id="student-1"
    )


def test_a_unanimous_no_names_the_requirement() -> None:
    """Indexes, not sentences: two requirements can carry the same text."""
    assert _check(_Fake(False), _Fake(False)) == (0, 1)


def test_one_reading_saying_yes_is_enough_to_pass() -> None:
    """The bar is unanimity to BLOCK: a regeneration costs a call, and a
    disagreed requirement is not evidence the letter breaks it."""
    assert _check(_Fake(False), _Fake(True)) == ()
    assert _check(_Fake(False, True), _Fake(False)) == ()


def test_no_requirements_makes_no_model_call() -> None:
    parser = _Fake(False)
    assert _check(parser, _Fake(False), requirements=()) == ()
    assert parser.calls == 0


def test_a_reading_that_learned_nothing_leaves_the_survivors_to_decide() -> None:
    assert _check(_Fake(None), _Fake(False)) == (0, 1)


def test_nothing_is_reported_when_nothing_survives() -> None:
    """This check adds evidence; it never manufactures it."""
    assert _check(_Fake(None), _Fake(None)) == ()


def test_the_second_family_is_optional_and_its_absence_is_not_a_verdict() -> None:
    parser = _Fake(False)
    assert _check(parser, None) != ()
    assert parser.calls == 2


def test_the_requirement_text_travels_as_data_and_never_as_instructions() -> None:
    parser = _Fake(True)
    _check(parser, None)
    for call in parser.seen:
        developer = [m for m in call["input"] if m["role"] == "developer"]
        assert developer and all(
            "third person" not in message["content"] for message in developer
        )
        user = [m for m in call["input"] if m["role"] == "user"]
        assert any("third person" in message["content"] for message in user)


def test_every_call_is_capped_and_identified_without_naming_the_student() -> None:
    parser, claude = _Fake(True), _Fake(True)
    _check(parser, claude)
    for call in parser.seen:
        assert call["max_output_tokens"] <= 2_000 and call["store"] is False
        assert call["safety_identifier"] != "student-1"
    for call in claude.seen:
        assert call["max_tokens"] <= 8_000
        assert call["metadata"]["user_id"] != "student-1"


@pytest.mark.parametrize("index", [7, -1])
def test_a_verdict_for_an_index_nobody_asked_about_decides_nothing(index: int) -> None:
    class _Stray(_Fake):
        def parse(self, **kwargs: Any) -> object:
            self.calls += 1
            return _Reading(
                RequirementVerdicts.model_validate(
                    {"verdicts": [{"index": index, "satisfied": False}]}
                )
            )

    assert _check(_Stray(False), None) == ()


class _Partial(_Fake):
    """A reading that answers only the index it is given."""

    def __init__(self, index: int, satisfied: bool) -> None:
        super().__init__(satisfied)
        self.index = index

    def parse(self, **kwargs: Any) -> object:
        self.calls += 1
        return _Reading(
            RequirementVerdicts.model_validate(
                {"verdicts": [{"index": self.index, "satisfied": self.answers[0]}]}
            )
        )


def test_a_reading_that_stayed_silent_is_not_counted_as_agreeing() -> None:
    """Unanimity means every surviving reading said no, not "nobody said yes".

    One partial answer would otherwise spend the regeneration and then refuse
    the letter, on the strength of a single reading.
    """
    assert check_written_requirements(
        _content(),
        _REQUIREMENTS,
        parser=_Partial(0, False),
        claude=_Partial(1, False),
        actor_id="student-1",
    ) == ()


def test_a_reading_that_answers_one_index_twice_is_dropped() -> None:
    class _Contradictory(_Fake):
        def parse(self, **kwargs: Any) -> object:
            self.calls += 1
            return _Reading(
                RequirementVerdicts.model_validate(
                    {
                        "verdicts": [
                            {"index": 0, "satisfied": False},
                            {"index": 0, "satisfied": True},
                        ]
                    }
                )
            )

    # Dropped, so the one consistent reading decides -- not cancelled by it.
    assert check_written_requirements(
        _content(),
        (_REQUIREMENTS[0],),
        parser=_Contradictory(False),
        claude=_Fake(False),
        actor_id="student-1",
    ) == (0,)


def test_the_judge_sees_the_whole_letter() -> None:
    """A requirement about the date, the addressee or the language is judged
    against evidence that has to contain the answer."""
    parser = _Fake(True)
    check_written_requirements(
        LetterContent(
            language="de",
            header_block="Musterstadt, 22. September 2026",
            units=(
                LetterUnit(
                    archetype="WHY_PROGRAMME", text="Ich bewerbe mich.", answers_question="q1"
                ),
            ),
        ),
        _REQUIREMENTS,
        parser=parser,
        claude=None,
        actor_id="student-1",
    )
    payload = str(parser.seen[0]["input"][1]["content"])
    assert "Musterstadt" in payload and '"de"' in payload and "q1" in payload


def test_a_students_letter_does_not_reach_a_second_vendor_by_default(settings) -> None:
    """The setting is the decision, not the caller passing a client.

    Branch security review: this check would be the first path on which a
    student's own text leaves the platform to the second model family, which
    reads only programme pages everywhere else.
    """
    import config.settings.base as base

    assert base.LETTER_JUDGE_SECOND_FAMILY is False, "the shipped default must be off"
    settings.LETTER_JUDGE_SECOND_FAMILY = False
    claude = _Fake(False)
    _check(_Fake(False), claude)
    assert claude.calls == 0


def test_the_second_family_is_used_once_the_decision_is_recorded(settings) -> None:
    settings.LETTER_JUDGE_SECOND_FAMILY = True
    claude = _Fake(True)
    assert _check(_Fake(False), claude) == ()
    assert claude.calls == 1


def test_a_reading_that_judged_nothing_does_not_silence_the_others() -> None:
    """PR review: an empty verdict list is schema-valid and passed the
    consistency check, so it counted as a survivor -- and unanimity then
    failed at every index, disabling the whole check for the letter."""

    class _Empty(_Fake):
        def parse(self, **kwargs: Any) -> object:
            self.calls += 1
            return _Reading(RequirementVerdicts.model_validate({"verdicts": []}))

    assert _check(_Empty(False), _Fake(False)) == (0, 1)
