import pytest

from apps.documents.research_fit.judge import (
    Alignment,
    AlignmentReading,
    is_strong,
    judge_alignment,
)


@pytest.fixture(autouse=True)
def _second_family_allowed(settings):
    """Most of this module tests the cross-vendor split, so it is switched on.

    The default is OFF, and that default has its own test below: the anchor
    text is the student's own work, and a caller passing a client is not the
    decision (PR #114 review).
    """
    settings.LETTER_JUDGE_SECOND_FAMILY = True


class _Response:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.output_parsed = parsed
        self.output = []
        self.stop_reason = stop_reason

    @property
    def parsed_output(self):
        # The real Anthropic client exposes the parsed payload as
        # parsed_output (apps/documents/derive.py::_claude_reading), not
        # output_parsed -- that name is the OpenAI Responses API's. One
        # double answers both shapes so the Claude reading path is exercised
        # against the attribute it actually reads in production.
        return self.output_parsed


class _Scripted:
    def __init__(self, *parsed):
        self.responses = [p if isinstance(p, _Response) else _Response(p) for p in parsed]
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _reading(strength):
    return AlignmentReading(strength=strength, excerpt="legged locomotion")


def test_two_of_three_strong_is_strong():
    parser = _Scripted(_reading("strong"), _reading("weak"))
    claude = _Scripted(_reading("strong"))
    out = judge_alignment(
        parser=parser,
        claude=claude,
        student_id="s",
        anchor_text="gait control for quadrupeds",
        sentence="We work on legged locomotion.",
    )
    assert out.readings == 3 and is_strong(out)
    assert (
        parser.calls[0]["text_format"] is AlignmentReading and parser.calls[0]["store"] is False
    )
    assert claude.calls[0]["output_format"] is AlignmentReading
    assert "DATA" in parser.calls[0]["input"][0]["content"]


def test_one_of_three_strong_is_not_strong():
    parser = _Scripted(_reading("strong"), _reading("none"))
    claude = _Scripted(_reading("weak"))
    out = judge_alignment(
        parser=parser, claude=claude, student_id="s", anchor_text="a", sentence="b"
    )
    assert not is_strong(out)


def test_a_weak_majority_proposes_nothing():
    parser = _Scripted(_reading("weak"), _reading("weak"))
    claude = _Scripted(_reading("weak"))
    out = judge_alignment(
        parser=parser, claude=claude, student_id="s", anchor_text="a", sentence="b"
    )
    assert not is_strong(out)


def test_a_lost_reading_is_dropped_and_two_survivors_decide():
    parser = _Scripted(_reading("strong"), _Response(None))
    claude = _Scripted(_reading("strong"))
    out = judge_alignment(
        parser=parser, claude=claude, student_id="s", anchor_text="a", sentence="b"
    )
    assert out.readings == 2 and is_strong(out)


def test_fewer_than_two_readings_never_decides():
    parser = _Scripted(_Response(None), _Response(None))
    claude = _Scripted(_reading("strong"))
    out = judge_alignment(
        parser=parser, claude=claude, student_id="s", anchor_text="a", sentence="b"
    )
    assert out.readings == 1 and not is_strong(out)


class _Boom(Exception):
    """Stands for a model SDK's transport errors (e.g. openai.APIConnectionError,
    anthropic's APIConnectionError): plain Exception subclasses, not
    ValueError/ValidationError, that a reading must drop rather than raise (D11)."""


class _RaisingClient:
    def parse(self, **kwargs):
        raise _Boom("network down")


def test_a_transport_failure_from_openai_drops_that_reading_not_the_call():
    # If _openai_reading narrows its except back to (ValidationError, ValueError),
    # _Boom propagates and judge_alignment raises instead of degrading.
    claude = _Scripted(_reading("strong"))
    out = judge_alignment(
        parser=_RaisingClient(), claude=claude, student_id="s", anchor_text="a", sentence="b"
    )
    assert out.readings == 1 and not is_strong(out)


def test_a_transport_failure_from_claude_drops_that_reading_not_the_call():
    # If _claude_reading narrows its except back to (ValidationError, ValueError),
    # _Boom propagates and judge_alignment raises instead of degrading.
    parser = _Scripted(_reading("strong"), _reading("strong"))
    out = judge_alignment(
        parser=parser, claude=_RaisingClient(), student_id="s", anchor_text="a", sentence="b"
    )
    assert out.readings == 2 and is_strong(out)


def test_a_response_missing_stop_reason_is_dropped_not_accepted():
    """claude_parsed_or_none (audit #9) defaults a missing stop_reason to
    None, not "end_turn" -- tighter than the inline copy this replaced, which
    treated a response with no stop_reason attribute at all as complete."""

    class _NoStopReason:
        parsed_output = _reading("strong")

    class _NoStopReasonClient:
        def parse(self, **kwargs):
            return _NoStopReason()

    parser = _Scripted(_reading("strong"), _reading("strong"))
    out = judge_alignment(
        parser=parser,
        claude=_NoStopReasonClient(),
        student_id="s",
        anchor_text="a",
        sentence="b",
    )

    assert out.readings == 2  # the Claude reading was dropped, not counted


def test_no_claude_means_two_openai_readings():
    parser = _Scripted(_reading("strong"), _reading("strong"))
    out = judge_alignment(
        parser=parser, claude=None, student_id="s", anchor_text="a", sentence="b"
    )
    assert out == Alignment(strength="strong", readings=2, excerpt="legged locomotion")


def test_the_second_family_is_withheld_unless_the_setting_says_otherwise(settings) -> None:
    """`anchor_text` is the student's own fact text -- strictly more
    identifying than the letter `check_written_requirements` already gates."""
    import config.settings.base as base

    assert base.LETTER_JUDGE_SECOND_FAMILY is False, "the shipped default must be off"
    settings.LETTER_JUDGE_SECOND_FAMILY = False
    parser = _Scripted(_reading("strong"), _reading("strong"))
    claude = _Scripted(_reading("strong"))
    alignment = judge_alignment(
        parser=parser,
        claude=claude,
        student_id="s1",
        anchor_text="A gait controller built with Maria O'Brien at Univ. of Texas at Austin",
        sentence="We work on legged locomotion.",
    )
    assert claude.calls == []
    assert alignment.readings == 2
