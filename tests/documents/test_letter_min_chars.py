import pytest

from apps.documents.constraints import Enforcement
from apps.documents.letter_defaults import defaults_for
from apps.documents.letter_render import _check_letter_constraint
from apps.documents.letter_shape import (
    LetterShape,
    NotGeneratable,
    apply_derived_shape,
    constraints_from_shape,
    shape_from_prompt,
    target_word_count,
    validate_shape_bounds,
)
from apps.documents.letters import _shape_instructions

from .conftest import make_program

_URL = "https://x.example/p"


def _row():
    return defaults_for(
        country_code="GB", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )


@pytest.mark.django_db
def test_a_character_floor_lands_on_the_prompt_and_round_trips():
    program = make_program(country_code="DE")
    shape = LetterShape(
        min_chars=2800,
        sources={"min_chars": {"text": "mindestens 2.800 Zeichen", "source_url": _URL}},
    )
    prompt = apply_derived_shape(program, "2027", shape, source_url=_URL)
    assert prompt.letter_min_chars == 2800
    assert shape_from_prompt(prompt) == shape


def test_a_character_floor_is_a_binding_rule_measured_without_spaces():
    (rule,) = constraints_from_shape(LetterShape(min_chars=2800))
    assert (rule.key, rule.value, rule.enforcement) == (
        "min_chars_excl_spaces", 2800, Enforcement.BINDING,
    )


def test_the_floor_blocks_a_letter_short_of_it_and_never_counts_spaces():
    """2,800 characters WITH spaces is 2,100 without: under the floor. Counting
    spaces here would pass a letter the page rejects."""
    (rule,) = constraints_from_shape(LetterShape(min_chars=2800))
    assert _check_letter_constraint(rule, text="abc " * 700) is not None
    assert _check_letter_constraint(rule, text="abcd " * 700) is None


def test_a_floor_above_the_cap_is_refused_before_any_model_call():
    with pytest.raises(NotGeneratable, match="characters"):
        validate_shape_bounds(LetterShape(min_chars=3000, max_chars=2000))


def test_the_word_target_carries_enough_characters_for_the_floor():
    """A target the floor then blocks is a model call paid for and thrown away --
    the defect letter_shape.py's clamps exist to prevent. 4.76 is this engine's
    measured non-space characters per word."""
    assert target_word_count(LetterShape(min_chars=2800), _row()) * 4.76 >= 2800


def test_the_writer_is_told_the_floor():
    text = _shape_instructions(LetterShape(min_chars=2800), _row())
    assert "at least 2800 characters, not counting spaces" in text


# Fix round 1, finding 1: validate_shape_bounds let three kinds of
# unsatisfiable character floor through, because it only ever read
# shape.min_words -- which stays None when a page states nothing but a
# character floor -- rather than the word floor that floor implies.


def test_a_character_floor_above_an_unreachable_word_cap_is_refused():
    """2,800 non-space characters implies a floor of about 589 words
    (ceil(2800 / 4.76), the same conversion target_word_count aims at), which
    a 400-word cap cannot hold. Before this fix, validate_shape_bounds only
    ever compared shape.min_words (None here) against max_words and passed."""
    with pytest.raises(NotGeneratable, match="words exceeds"):
        validate_shape_bounds(LetterShape(min_chars=2800, max_words=400))


def test_a_character_floor_whose_with_spaces_target_exceeds_the_cap_is_refused():
    """2,800 characters WITHOUT spaces is numerically under a 3,000-character
    cap (measured WITH spaces), so the simple min_chars > max_chars check does
    not catch it -- but writing 2,800 non-space characters takes about 3,529
    characters with spaces (the 6 / 4.76 ratio target_word_count's own aim
    uses), which the stated cap cannot hold."""
    with pytest.raises(NotGeneratable, match="characters with spaces"):
        validate_shape_bounds(LetterShape(min_chars=2800, max_chars=3000))


def test_a_character_floor_above_what_a_page_cap_holds_is_refused():
    """min_chars vs max_pages was never checked at all before this fix. A
    floor of 5,000 characters implies about 1,051 words, and no one-page cap
    (720 words at most, the ESSAY default) holds that many."""
    with pytest.raises(NotGeneratable, match="does not fit"):
        validate_shape_bounds(LetterShape(min_chars=5000, max_pages=1.0))


def test_a_satisfiable_character_floor_alongside_other_bounds_is_accepted():
    """One combination that clears all three cross-checks above: the implied
    word floor (169) sits comfortably inside both the word cap and what the
    page cap holds, so nothing is refused."""
    validate_shape_bounds(LetterShape(min_chars=800, max_words=600, max_pages=2.0))


def test_the_floor_never_counts_any_whitespace_not_just_a_plain_space():
    """Fix round 1, finding 7: _check_letter_constraint used to strip only
    " ", so a tab or newline still counted toward the floor. "a\\tb\\n" has 4
    characters and only 2 non-whitespace ones -- under a floor of 4 -- but the
    old check saw stripped_len == 4 and wrongly passed it."""
    (rule,) = constraints_from_shape(LetterShape(min_chars=4))
    assert _check_letter_constraint(rule, text="ab\tcd\n") is None
    assert _check_letter_constraint(rule, text="a\tb\n") is not None
