from uuid import uuid4

from apps.documents.letter_gates import (
    GateCode,
    check_claim_coverage,
    check_duplicates_paired_document,
    check_duplicates_sibling_answers,
    check_first_person_plural,
    check_generic_paragraph,
    check_header_block_missing,
    check_language_mismatch,
    check_prompt_requirement_unmet,
    check_storyline_drift,
    check_wrong_institution,
    run_letter_gates,
)
from apps.documents.letter_schemas import (
    ClaimKind,
    LetterClaim,
    LetterContent,
    LetterUnit,
    Storyline,
)


def _unit(text, claims=()):
    return LetterUnit(archetype="WHY_PROGRAMME", text=text, claims=claims)


def test_sentence_with_digit_and_no_covering_claim_flagged():
    text = "I completed 120 ECTS credits during my degree."
    violations = check_claim_coverage(_unit(text))
    assert any(v.code == GateCode.UNDECLARED_ASSERTION for v in violations)


def test_sentence_with_digit_covered_by_claim_not_flagged():
    text = "I completed 120 ECTS credits during my degree."
    claim = LetterClaim(
        text=text,
        span_start=0,
        span_end=len(text),
        kind=ClaimKind.FACTUAL,
        fact_id=__import__("uuid").uuid4(),
    )
    violations = check_claim_coverage(_unit(text, claims=(claim,)))
    assert violations == ()


def test_sentence_with_capitalised_multiword_phrase_flagged():
    text = "I studied at Example University before applying here."
    violations = check_claim_coverage(_unit(text))
    assert any(v.code == GateCode.UNDECLARED_ASSERTION for v in violations)


def test_plain_narrative_sentence_not_flagged():
    text = "I have always been curious about how systems fail under pressure."
    violations = check_claim_coverage(_unit(text))
    assert violations == ()


def test_soft_lowercase_claim_not_flagged_stated_ceiling():
    # "I supervised a research group" -- no digit, no date, no capitalised
    # multi-word phrase -- escapes by design (spec's stated ceiling).
    text = "I supervised a research group for two semesters."
    violations = check_claim_coverage(_unit(text))
    assert violations == ()


def test_later_sentence_uncovered_while_earlier_identical_sentence_is_covered():
    # Two sentences, byte-identical, so the loop's cursor must advance past
    # the first match -- a naive `text.index(sentence)` (no cursor) would
    # find the first occurrence again and wrongly treat the second sentence
    # as covered too.
    sentence = "I visited Example University."
    text = f"{sentence} {sentence}"
    claim = LetterClaim(
        text=sentence, span_start=0, span_end=len(sentence), kind=ClaimKind.FACTUAL, fact_id=uuid4()
    )
    violations = check_claim_coverage(_unit(text, claims=(claim,)))
    assert len(violations) == 1
    assert violations[0].detail == sentence


def test_interpretive_claim_does_not_cover_a_triggering_sentence():
    # INTERPRETIVE carries no id by design (letter_verification.py's
    # _classify auto-SUPPORTS it) -- it must not be able to cover a sentence
    # that reads as a factual assertion (proper noun + date) just by
    # spanning it.
    text = "I completed a research fellowship at Stanford University in 2021."
    claim = LetterClaim(text=text, span_start=0, span_end=len(text), kind=ClaimKind.INTERPRETIVE)
    violations = check_claim_coverage(_unit(text, claims=(claim,)))
    assert any(v.code == GateCode.UNDECLARED_ASSERTION for v in violations)


def test_acronym_led_institution_flagged_when_uncovered():
    text = "I am applying to TU Munich for the upcoming semester."
    violations = check_claim_coverage(_unit(text))
    assert any(v.code == GateCode.UNDECLARED_ASSERTION for v in violations)


def test_wrong_institution_flagged():
    content = LetterContent(
        language="en",
        units=(_unit("I am excited to join Wrong University's programme"),),
    )
    violations = check_wrong_institution(
        content, forbidden_names=frozenset({"Wrong University"})
    )
    assert any(v.code == GateCode.WRONG_INSTITUTION for v in violations)


def test_correct_institution_not_flagged():
    content = LetterContent(
        language="en", units=(_unit("I am excited to join Example University's programme"),)
    )
    violations = check_wrong_institution(
        content, forbidden_names=frozenset({"Wrong University"})
    )
    assert violations == ()


def test_unanswered_question_flagged():
    content = LetterContent(
        language="en",
        units=(LetterUnit(archetype="WHY_PROGRAMME", text="text", answers_question="q1"),),
    )
    questions = [
        {"id": "q1", "text": "Why this programme?"},
        {"id": "q2", "text": "Why this country?"},
    ]
    violations = check_prompt_requirement_unmet(content, questions=questions)
    assert len(violations) == 1
    assert violations[0].code == GateCode.PROMPT_REQUIREMENT_UNMET
    assert "q2" in violations[0].detail


def test_multiple_missing_questions_produce_one_violation_each():
    content = LetterContent(language="en", units=())
    questions = [
        {"id": "q1", "text": "Why this programme?"},
        {"id": "q2", "text": "Why this country?"},
        {"id": "q3", "text": "Why now?"},
    ]
    violations = check_prompt_requirement_unmet(content, questions=questions)
    assert len(violations) == 3
    assert all(v.code == GateCode.PROMPT_REQUIREMENT_UNMET for v in violations)
    assert {v.detail for v in violations} == {
        "unanswered: q1",
        "unanswered: q2",
        "unanswered: q3",
    }


def test_all_questions_answered_no_violation():
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="WHY_PROGRAMME", text="text", answers_question="q1"),
            LetterUnit(archetype="WHY_COUNTRY", text="text", answers_question="q2"),
        ),
    )
    questions = [{"id": "q1", "text": "x"}, {"id": "q2", "text": "y"}]
    assert check_prompt_requirement_unmet(content, questions=questions) == ()


def test_duplicate_paired_documents_flagged():
    shared_text = "I have always been drawn to systems that fail predictably under load."
    content_a = LetterContent(language="en", units=(_unit(shared_text),))
    content_b = LetterContent(language="en", units=(_unit(shared_text),))
    violations = check_duplicates_paired_document(content_a, content_b, threshold=0.5)
    assert any(v.code == GateCode.DUPLICATES_PAIRED_DOCUMENT for v in violations)


def test_distinct_paired_documents_not_flagged():
    content_a = LetterContent(
        language="en", units=(_unit("I want to study robotics because of my thesis work."),)
    )
    content_b = LetterContent(
        language="en", units=(_unit("My leadership experience shapes how I mentor others."),)
    )
    violations = check_duplicates_paired_document(content_a, content_b, threshold=0.5)
    assert violations == ()


def test_header_block_missing_when_required():
    content = LetterContent(language="en", header_block=None, units=(_unit("text"),))
    violations = check_header_block_missing(content, required=True)
    assert any(v.code == GateCode.HEADER_BLOCK_MISSING for v in violations)


def test_header_block_present_not_flagged():
    content = LetterContent(
        language="en",
        header_block="Example University -- MSc Computer Science",
        units=(_unit("text"),),
    )
    assert check_header_block_missing(content, required=True) == ()


def test_header_block_not_required_never_flagged():
    content = LetterContent(language="en", header_block=None, units=(_unit("text"),))
    assert check_header_block_missing(content, required=False) == ()


def test_language_mismatch_declared_language_differs():
    content = LetterContent(language="fr", units=(_unit("Ceci est une lettre"),))
    violations = check_language_mismatch(content, document_language="en")
    assert any(v.code == GateCode.LANGUAGE_MISMATCH for v in violations)


def test_language_match_not_flagged():
    content = LetterContent(language="en", units=(_unit("This is a letter"),))
    assert check_language_mismatch(content, document_language="en") == ()


def test_korean_script_ratio_below_half_flagged():
    content = LetterContent(
        language="ko",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="This is mostly English text with 안녕 only two Korean characters.",
            ),
        ),
    )
    violations = check_language_mismatch(content, document_language="ko")
    assert any(v.code == GateCode.LANGUAGE_MISMATCH for v in violations)


def test_generic_paragraph_with_no_grounded_claim_flagged():
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME", text="I am passionate about learning.", claims=()
            ),
        ),
    )
    violations = check_generic_paragraph(content)
    assert any(v.code == GateCode.GENERIC_PARAGRAPH for v in violations)


def test_generic_paragraph_with_sourced_claim_not_flagged():
    claim = LetterClaim(
        text="the robotics lab",
        span_start=0,
        span_end=16,
        kind=ClaimKind.SOURCED,
        source_url="https://tum.de/robotics",
    )
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME", text="I want to join the robotics lab.", claims=(claim,)
            ),
        ),
    )
    assert check_generic_paragraph(content) == ()


def test_opening_and_closing_exempt_from_generic_paragraph_check():
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="OPENING", text="Dear Admissions Committee,", claims=()),
            LetterUnit(archetype="CLOSING", text="Thank you for your consideration.", claims=()),
        ),
    )
    assert check_generic_paragraph(content) == ()


# --- 2026-09-14 amendment ---------------------------------------------------


def test_why_programme_needs_a_sourced_claim_not_only_a_factual_one():
    factual = LetterClaim(
        text="my thesis", span_start=0, span_end=9, kind=ClaimKind.FACTUAL, fact_id=uuid4()
    )
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME", text="my thesis leads me here.", claims=(factual,)
            ),
        ),
    )
    violations = check_generic_paragraph(content)
    assert any(v.code == GateCode.GENERIC_PARAGRAPH and "SOURCED" in v.detail for v in violations)


def test_sibling_answers_that_repeat_each_other_are_flagged():
    text = "I will lead the national data office and expand it across every region."
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="CAREER_PLAN_RETURN", answers_question="Q2", text=text),
            LetterUnit(archetype="CAREER_PLAN_RETURN", answers_question="Q3", text=text),
        ),
    )
    violations = check_duplicates_sibling_answers(content)
    assert any(
        v.code == GateCode.DUPLICATES_SIBLING_ANSWER and "Q2" in v.detail and "Q3" in v.detail
        for v in violations
    )


def test_sibling_check_ignores_a_continuous_letter():
    content = LetterContent(language="en", units=(_unit("same text"), _unit("same text")))
    assert check_duplicates_sibling_answers(content) == ()


def test_leadership_answer_written_as_we_is_flagged():
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="LEADERSHIP_EXAMPLE",
                text="We planned it, we ran it, and our team delivered it.",
            ),
        ),
    )
    assert any(v.code == GateCode.FIRST_PERSON_PLURAL for v in check_first_person_plural(content))


def test_leadership_answer_written_as_i_is_not_flagged():
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="LEADERSHIP_EXAMPLE",
                text="I proposed the change and my team adopted it; we shipped it in May.",
            ),
        ),
    )
    assert check_first_person_plural(content) == ()


def test_storyline_drift_when_anchors_are_unused():
    a, b = uuid4(), uuid4()
    storyline = Storyline(theme="t", theme_kind="PROBLEM", anchors=(a, b), future="f")
    content = LetterContent(language="en", units=(_unit("no anchors used"),), storyline=storyline)
    violations = check_storyline_drift(content, storyline=storyline)
    assert any(v.code == GateCode.STORYLINE_DRIFT for v in violations)


def test_no_storyline_means_no_drift_check():
    content = LetterContent(language="en", units=(_unit("x"),))
    assert check_storyline_drift(content, storyline=None) == ()


def test_run_letter_gates_aggregates_violations_from_multiple_checks():
    content = LetterContent(
        language="en",
        header_block=None,
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME", text="I am passionate about learning.", claims=()
            ),
        ),
    )
    violations = run_letter_gates(
        content,
        forbidden_names=frozenset(),
        questions=[],
        header_block_required=True,
        document_language="en",
        paired_content=None,
        storyline=None,
    )
    codes = {v.code for v in violations}
    assert GateCode.HEADER_BLOCK_MISSING in codes
    assert GateCode.GENERIC_PARAGRAPH in codes


def test_run_letter_gates_clean_letter_has_no_violations():
    claim = LetterClaim(
        text="the robotics lab",
        span_start=21,
        span_end=37,
        kind=ClaimKind.SOURCED,
        source_url="https://tum.de/robotics",
    )
    content = LetterContent(
        language="en",
        header_block="Example University -- MSc Robotics",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="I want to join the robotics lab.",
                claims=(claim,),
                answers_question="q1",
            ),
        ),
    )
    violations = run_letter_gates(
        content,
        forbidden_names=frozenset(),
        questions=[{"id": "q1", "text": "Why this programme?"}],
        header_block_required=True,
        document_language="en",
        paired_content=None,
        storyline=None,
    )
    assert violations == ()
