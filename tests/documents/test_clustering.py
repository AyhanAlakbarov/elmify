from apps.documents.clustering import (
    CORE_ELIGIBLE_ARCHETYPES,
    cluster_key,
    is_reusable,
    units_to_regenerate,
    word_limit_band,
)
from apps.funding.models import ApplicationPrompt


def _prompt(**overrides):
    # No `constraints` attribute: the real ApplicationPrompt (Task 2) has no such
    # field (PF-4). Word/char limits come from `questions[]` only.
    class _Stub:
        structure = overrides.get("structure", ApplicationPrompt.Structure.CONTINUOUS_LETTER)
        archetypes = overrides.get("archetypes", ["WHY_PROGRAMME", "ACADEMIC_PREPARATION"])
        document_language = overrides.get("document_language", "en")
        questions = overrides.get("questions", [])

    return _Stub()


def test_word_limit_band_is_prefixed_by_structure():
    band_letter = word_limit_band(
        _prompt(
            structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
            questions=[{"max_words": 500}],
        )
    )
    band_short = word_limit_band(
        _prompt(
            structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET,
            questions=[{"max_words": 500}],
        )
    )
    # same word count, different structure -> never cluster together
    assert band_letter != band_short


def test_two_engineering_programmes_same_cluster_key():
    key_a = cluster_key(_prompt(), discipline="Computer Science", scholarship_present=False)
    key_b = cluster_key(_prompt(), discipline="Computer Science", scholarship_present=False)
    assert is_reusable(key_a, key_b)


def test_different_discipline_different_cluster():
    key_a = cluster_key(_prompt(), discipline="Computer Science", scholarship_present=False)
    key_b = cluster_key(_prompt(), discipline="Robotics and AI", scholarship_present=False)
    assert not is_reusable(key_a, key_b)


def test_short_answer_and_long_letter_never_cluster_even_at_same_word_count():
    key_letter = cluster_key(
        _prompt(structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER),
        discipline="CS",
        scholarship_present=False,
    )
    key_short = cluster_key(
        _prompt(structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET),
        discipline="CS",
        scholarship_present=False,
    )
    assert not is_reusable(key_letter, key_short)


def test_units_to_regenerate_excludes_core_eligible():
    archetypes = ("PERSONAL_BACKGROUND", "WHY_PROGRAMME", "OPENING", "ACADEMIC_PREPARATION")
    regenerated = units_to_regenerate(archetypes)
    assert "WHY_PROGRAMME" in regenerated and "OPENING" in regenerated
    assert "PERSONAL_BACKGROUND" not in regenerated
    assert "ACADEMIC_PREPARATION" not in regenerated


def test_unrecognised_archetype_defaults_to_regenerated():
    assert "SOME_NEW_ARCHETYPE" not in CORE_ELIGIBLE_ARCHETYPES
    assert "SOME_NEW_ARCHETYPE" in units_to_regenerate(("SOME_NEW_ARCHETYPE",))


# --- PF-4: limits derive from questions[] only (no `constraints` field exists) ---


def test_word_limit_summed_across_questions():
    band = word_limit_band(_prompt(questions=[{"max_words": 150}, {"max_words": 200}]))
    assert band == f"{ApplicationPrompt.Structure.CONTINUOUS_LETTER}:MEDIUM"  # 350 words


def test_word_count_boundary_short_medium():
    assert word_limit_band(_prompt(questions=[{"max_words": 300}])).endswith(":SHORT")
    assert word_limit_band(_prompt(questions=[{"max_words": 301}])).endswith(":MEDIUM")


def test_word_count_boundary_medium_long():
    assert word_limit_band(_prompt(questions=[{"max_words": 800}])).endswith(":MEDIUM")
    assert word_limit_band(_prompt(questions=[{"max_words": 801}])).endswith(":LONG")


def test_falls_back_to_char_limit_when_no_max_words():
    band = word_limit_band(_prompt(questions=[{"max_chars_incl_spaces": 6001}]))
    assert band.endswith(":LONG")


def test_unknown_band_when_no_limit_present():
    assert word_limit_band(_prompt(questions=[])).endswith(":UNKNOWN")


def test_invalid_question_values_ignored():
    questions = [
        {"max_words": "250"},
        {"max_words": 0},
        {"max_words": 200},
        {"max_words": 150},
    ]
    band = word_limit_band(_prompt(questions=questions))
    assert band.endswith(":MEDIUM")  # 200 + 150 = 350; the string and the zero are ignored
