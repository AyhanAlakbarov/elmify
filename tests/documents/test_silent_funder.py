from apps.documents.letter_defaults import defaults_for
from apps.documents.letter_shape import LetterShape, constraints_from_shape, target_word_count
from apps.documents.silent_funder import apply_silent_funder_defaults
from apps.funding.models import ApplicationPrompt


def test_every_funder_kind_has_a_default_row():
    """Every funder kind gets a non-empty default, through the real function --

    not through the dict `apply_silent_funder_defaults` no longer reads. CONSORTIUM
    is the one deliberate exception: it fails closed rather than getting a default.
    """
    for choice, _label in ApplicationPrompt.FunderKind.choices:
        result = apply_silent_funder_defaults(funder_kind=choice)
        if choice == ApplicationPrompt.FunderKind.CONSORTIUM:
            assert result["archetypes"] == ()
        else:
            assert result["archetypes"]


def test_government_scholarship_defaults():
    result = apply_silent_funder_defaults(
        funder_kind=ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP
    )
    assert "WHY_COUNTRY" in result["archetypes"]
    assert "CAREER_PLAN_RETURN" in result["archetypes"]
    assert result["structure"] == ApplicationPrompt.Structure.CONTINUOUS_LETTER


def test_immigration_authority_keeps_short_answer_set_structure():
    result = apply_silent_funder_defaults(
        funder_kind=ApplicationPrompt.FunderKind.IMMIGRATION_AUTHORITY
    )
    assert result["structure"] == ApplicationPrompt.Structure.SHORT_ANSWER_SET


def test_the_default_length_is_a_target_and_never_a_bound():
    """A funder who published nothing imposed no limit.

    So this returns no constraint at all: the only column `_create_inferred`
    could have stored one in is `letter_max_words`, which
    `constraints_from_shape` reads as BINDING -- a length we chose blocking a
    render. What an inferred prompt stores is no bound, and the same
    `defaults_for` row `generate_letter` recomputes aims the model instead.
    """
    kind = ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION
    assert "constraints" not in apply_silent_funder_defaults(funder_kind=kind)
    row = defaults_for(country_code="", track="taught", portfolio_led=False, funder_kind=kind)
    shape = LetterShape()
    assert constraints_from_shape(shape) == ()
    assert target_word_count(shape, row, "en") == row.word_target


def test_header_block_always_required_by_default():
    result = apply_silent_funder_defaults(
        funder_kind=ApplicationPrompt.FunderKind.RESEARCH_SUPERVISOR
    )
    assert result["header_block_required"] is True


def test_consortium_kind_gets_no_default_archetypes():
    result = apply_silent_funder_defaults(funder_kind=ApplicationPrompt.FunderKind.CONSORTIUM)
    assert result["archetypes"] == ()
