from uuid import uuid4

import pytest

from apps.documents.letter_gates import (
    GateCode,
    check_ai_style,
    check_claim_coverage,
    check_cohort_overlap,
    check_declared_voice_retention,
    check_duplicates_paired_document,
    check_duplicates_sibling_answers,
    check_first_person_plural,
    check_generic_paragraph,
    check_header_block_missing,
    check_language_mismatch,
    check_prompt_requirement_unmet,
    check_storyline_drift,
    check_unit_structure,
    check_unsourced_programme_claim,
    check_wrong_institution,
    run_letter_gates,
    script_of,
    sentence_spans,
)
from apps.documents.letter_schemas import (
    ClaimKind,
    LetterClaim,
    LetterContent,
    LetterUnit,
    Storyline,
)

#: A research row verified for the letter's programme (plan 1, task 3).
VERIFIED_INPUT = uuid4()


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
        input_id=VERIFIED_INPUT,
    )
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME", text="I want to join the robotics lab.", claims=(claim,)
            ),
        ),
    )
    assert check_generic_paragraph(content, programme_input_ids=frozenset({VERIFIED_INPUT})) == ()


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


def _why_programme(*claims):
    return LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="WHY_PROGRAMME", text="my thesis leads me here.", claims=claims),
        ),
    )


def _factual():
    return LetterClaim(
        text="my thesis", span_start=0, span_end=9, kind=ClaimKind.FACTUAL, fact_id=uuid4()
    )


def test_why_programme_needs_a_sourced_claim_not_only_a_factual_one():
    violations = check_generic_paragraph(
        _why_programme(_factual()), programme_input_ids=frozenset({uuid4()})
    )
    assert any(v.code == GateCode.GENERIC_PARAGRAPH and v.blocking for v in violations)


def test_a_url_only_sourced_claim_no_longer_satisfies_why_programme():
    url_only = LetterClaim(
        text="my thesis", span_start=0, span_end=9, kind=ClaimKind.SOURCED,
        source_url="https://made-up.example/page",
    )
    violations = check_generic_paragraph(
        _why_programme(_factual(), url_only), programme_input_ids=frozenset({uuid4()})
    )
    assert any(v.code == GateCode.GENERIC_PARAGRAPH and v.blocking for v in violations)


def test_a_sourced_claim_citing_a_verified_input_satisfies_why_programme():
    verified = uuid4()
    cited = LetterClaim(
        text="my thesis", span_start=0, span_end=9, kind=ClaimKind.SOURCED,
        source_url="https://www.tum.de/robotics", input_id=verified,
    )
    assert check_generic_paragraph(
        _why_programme(_factual(), cited), programme_input_ids=frozenset({verified})
    ) == ()


def test_with_nothing_verified_why_programme_is_a_warning_not_a_block():
    violations = check_generic_paragraph(_why_programme(_factual()))
    assert violations and all(not v.blocking for v in violations)
    assert "not specific to this programme" in violations[0].detail


def test_a_letter_with_no_facts_is_a_warning_not_a_block():
    content = LetterContent(
        language="en",
        units=(LetterUnit(archetype="CAREER_GOALS", text="I want to build tools.", claims=()),),
    )
    violations = check_generic_paragraph(content, has_facts=False)
    assert violations and all(not v.blocking for v in violations)
    assert check_generic_paragraph(content, has_facts=True)[0].blocking


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
        input_id=VERIFIED_INPUT,
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
        programme_input_ids=frozenset({VERIFIED_INPUT}),
        storyline=None,
    )
    assert violations == ()


# --- Plan 1, task 1: sentence splitting for every letter script ---


def test_latin_sentences_split_as_before():
    assert [s for s, _, _ in sentence_spans("I studied. I built! Why? Done.")] == [
        "I studied.", "I built!", "Why?", "Done.",
    ]


def test_a_version_number_is_not_a_sentence_end():
    assert [s for s, _, _ in sentence_spans("I used Python 3.11 daily. Then I left.")] == [
        "I used Python 3.11 daily.", "Then I left.",
    ]


def test_japanese_and_chinese_sentences_split_without_a_space():
    assert [s for s, _, _ in sentence_spans("研究をしました。次に進みます。")] == [
        "研究をしました。", "次に進みます。",
    ]
    assert [s for s, _, _ in sentence_spans("我学习了。你呢？好！")] == [
        "我学习了。", "你呢？", "好！",
    ]


def test_arabic_question_mark_and_armenian_full_stop_end_sentences():
    assert len(sentence_spans("هل درست؟ نعم درست.")) == 2
    assert len(sentence_spans("Ես սովորել եմ։ Հետո աշխատել եմ։")) == 2


def test_spans_point_at_their_own_text_in_cjk():
    text = "研究をしました。次に進みます。"
    for sentence, start, end in sentence_spans(text):
        assert text[start:end] == sentence


def test_no_empty_trailing_sentence_after_a_final_cjk_stop():
    assert [s for s, _, _ in sentence_spans("研究をしました。")] == ["研究をしました。"]


# --- Plan 1, task 2: script check for every letter script ---


def _letter_in(language, text):
    return LetterContent(
        language=language, units=(LetterUnit(archetype="WHY_FIELD", text=text, claims=()),)
    )


@pytest.mark.parametrize(
    ("language", "native"),
    [
        ("ru", "Я изучала машинное обучение в университете."),
        ("uk", "Я вивчала машинне навчання в університеті."),
        ("bg", "Учих машинно обучение в университета."),
        ("el", "Σπούδασα μηχανική μάθηση στο πανεπιστήμιο."),
        ("ar", "درست تعلم الآلة في الجامعة."),
        ("hy", "Ես սովորել եմ մեքենայական ուսուցում համալսարանում։"),
        ("ka", "მე ვსწავლობდი მანქანურ სწავლებას უნივერსიტეტში."),
    ],
)
def test_a_letter_in_its_own_script_passes_and_in_english_fails(language, native):
    assert check_language_mismatch(_letter_in(language, native), document_language=language) == ()
    english = _letter_in(language, "I studied machine learning at the university.")
    assert any(
        v.code == GateCode.LANGUAGE_MISMATCH
        for v in check_language_mismatch(english, document_language=language)
    )


def test_a_russian_letter_quoting_english_names_still_passes():
    text = (
        "Я работала с библиотекой PyTorch в лаборатории Robotics Lab и хочу продолжить "
        "исследования в области обучения с подкреплением в вашей программе."
    )
    assert check_language_mismatch(_letter_in("ru", text), document_language="ru") == ()


@pytest.mark.parametrize("language", ["sr", "kk", "az", "tr", "de"])
def test_two_script_and_latin_languages_have_no_script_check(language):
    assert script_of(language) is None


def _letter(*archetypes):
    return LetterContent(
        language="en",
        header_block=None,
        units=tuple(LetterUnit(archetype=a, text="A sentence.") for a in archetypes),
    )


def test_an_archetype_split_into_several_units_is_flagged():
    # Measured live 2026-09-25: six requested archetypes came back as 21
    # one-claim units, three of them OPENING -- a list, not a letter.
    violations = check_unit_structure(
        _letter("OPENING", "OPENING", "WHY_PROGRAMME"),
        archetypes=("OPENING", "WHY_PROGRAMME"),
    )
    assert [(v.code, v.unit_archetype) for v in violations] == [
        (GateCode.UNIT_STRUCTURE, "OPENING")
    ]


def test_an_archetype_nobody_asked_for_is_flagged():
    violations = check_unit_structure(
        _letter("WHY_PROGRAMME", "PERSONAL_BACKGROUND"), archetypes=("WHY_PROGRAMME",)
    )
    assert [(v.code, v.unit_archetype) for v in violations] == [
        (GateCode.UNIT_STRUCTURE, "PERSONAL_BACKGROUND")
    ]


def test_one_unit_per_requested_archetype_is_not_flagged():
    assert check_unit_structure(
        _letter("OPENING", "WHY_PROGRAMME"), archetypes=("OPENING", "WHY_PROGRAMME")
    ) == ()


def test_no_requested_archetypes_means_no_structure_check():
    # A short-answer set is keyed by question, not archetype.
    assert check_unit_structure(_letter("A", "A"), archetypes=()) == ()


def test_run_letter_gates_checks_unit_structure_when_given_archetypes():
    violations = run_letter_gates(
        _letter("OPENING", "OPENING"),
        forbidden_names=frozenset(),
        questions=[],
        header_block_required=False,
        document_language="en",
        archetypes=("OPENING",),
    )
    assert GateCode.UNIT_STRUCTURE in {v.code for v in violations}


def _one(archetype, text, claims=()):
    return LetterContent(
        language="en",
        units=(LetterUnit(archetype=archetype, text=text, claims=claims),),
    )


_INVENTED = "I would use the programme's module focused on free-energy methods."


def test_a_programme_offering_with_no_sourced_claim_is_flagged():
    # Measured live 2026-09-25: the student WANTED to learn free-energy methods;
    # the letter said the programme had a module on them. No digit, date or
    # capital letter, so the coverage gate never looked at it.
    violations = check_unsourced_programme_claim(_one("OPENING", _INVENTED))
    assert [(v.code, v.unit_archetype) for v in violations] == [
        (GateCode.UNSOURCED_PROGRAMME_CLAIM, "OPENING")
    ]


def test_a_sourced_claim_covering_the_sentence_clears_it():
    claim = LetterClaim(
        text="module focused on free-energy methods",
        span_start=0,
        span_end=len(_INVENTED),
        kind=ClaimKind.SOURCED,
        source_url="https://example.edu/modules",
        input_id=VERIFIED_INPUT,
    )
    assert check_unsourced_programme_claim(
        _one("WHY_PROGRAMME", _INVENTED, (claim,)), programme_input_ids=frozenset({VERIFIED_INPUT})
    ) == ()


def test_a_url_only_sourced_claim_does_not_vouch_for_the_programme():
    # Plan 1: a SOURCED claim carrying only a URL is a link the model could
    # make up; only a research row verified for this programme vouches.
    claim = LetterClaim(
        text="module focused on free-energy methods",
        span_start=0,
        span_end=len(_INVENTED),
        kind=ClaimKind.SOURCED,
        source_url="https://made-up.example/modules",
    )
    assert check_unsourced_programme_claim(
        _one("WHY_PROGRAMME", _INVENTED, (claim,)), programme_input_ids=frozenset({VERIFIED_INPUT})
    )


def test_a_student_fact_does_not_vouch_for_the_programme():
    claim = LetterClaim(
        text="free-energy methods",
        span_start=0,
        span_end=len(_INVENTED),
        kind=ClaimKind.DECLARED,
        input_id=uuid4(),
    )
    assert check_unsourced_programme_claim(_one("WHY_PROGRAMME", _INVENTED, (claim,)))


def test_the_applicants_own_past_is_not_a_programme_claim():
    text = "My thesis supervisor ran a computational chemistry lab."
    assert check_unsourced_programme_claim(_one("ACADEMIC_PREPARATION", text)) == ()


def test_a_laboratory_as_a_place_is_not_a_programme_claim():
    # Measured live 2026-09-25, a career sentence.
    text = "I want research in which screening informs what is tested in the laboratory."
    assert check_unsourced_programme_claim(_one("CAREER_PLAN_RETURN", text)) == ()


# --- Plan 1, final review fixes ---


@pytest.mark.parametrize(
    ("archetype", "text"),
    [
        ("CAREER_PLAN_RETURN",
         "I plan to return home and join the faculty of chemistry at my university as a lecturer."),
        ("HOME_COUNTRY_CONTRIBUTION",
         "I will train supervisors in my home ministry's research group."),
    ],
)
def test_the_applicants_future_at_home_is_not_a_programme_claim(archetype, text):
    assert check_unsourced_programme_claim(
        _one(archetype, text), programme_input_ids=frozenset({VERIFIED_INPUT})
    ) == ()


def test_with_nothing_verified_a_programme_word_is_a_warning_not_a_block():
    text = "I am looking for supervisors who work on catalysis, which my degree did not cover."
    violations = check_unsourced_programme_claim(_one("WHY_PROGRAMME", text))
    assert violations and all(not v.blocking for v in violations)


def test_with_research_verified_an_unsourced_programme_word_still_blocks():
    violations = check_unsourced_programme_claim(
        _one("WHY_PROGRAMME", _INVENTED), programme_input_ids=frozenset({VERIFIED_INPUT})
    )
    assert violations and all(v.blocking for v in violations)


def test_an_invisible_mark_after_a_terminal_still_ends_the_sentence():
    # A right-to-left mark (U+200F) or zero-width space (U+200B) after the
    # terminal is invisible, and hygiene strips it -- so the split must not
    # depend on it, or the sentence count changes across hygiene.
    assert len(sentence_spans("هل تعلم؟‏ نعم درست.")) == 2
    assert len(sentence_spans("First.​ Second.")) == 2


@pytest.mark.parametrize(
    "bad_text",
    [
        "I want to delve into distributed consensus protocols.",
        "This project was a pivotal moment in my academic journey.",
        "It not only improved throughput but also reduced tail latency.",
        "I built a demand forecaster, highlighting the need for better priors.",
        "The model failed on sparse nodes\u2014so I rewrote the solver.",
        "This result stands as a testament to our calibration pipeline.",
        "It is not just a solver, it is a framework for control.",
        "Dies unterstreicht die Bedeutung einer sauberen Kalibrierung.",
        "Hiermit bewerbe ich mich um einen Studienplatz.",
        "Ce résultat souligne l'importance de la méthode.",
        "Это подчеркивает важность точной модели.",
        "Bu çalışma veri kalitesinin önemini vurgulamaktadır.",
        (
            "I rewrote the state estimator in C++. "
            "Overall, this experience taught me how to debug sensor fusion."
        ),
        (
            "The implementation of the optimization configuration improved "
            "stabilization, convergence, effectiveness, and transformation."
        ),
        (
            "One two three four five six seven eight nine ten eleven. "
            "One two three four five six seven eight nine ten twelve. "
            "One two three four five six seven eight nine ten eleven. "
            "One two three four five six seven eight nine ten twelve."
        ),
    ],
)
def test_check_ai_style_flags_stock_words_trailers_em_dashes_and_uniform_lengths(bad_text):
    violations = check_ai_style(_one("ACADEMIC_PREPARATION", bad_text))
    assert [(v.code, v.unit_archetype) for v in violations] == [
        (GateCode.AI_STYLE, "ACADEMIC_PREPARATION")
    ]


def test_check_ai_style_passes_varied_plain_prose():
    good_text = (
        "My first solver diverged under packet loss. "
        "When I inspected the trace across twelve nodes, I think the fixed timeout "
        "assumed symmetric round-trip delays that our radio link could never guarantee. "
        "Replacing that bound with an adaptive window cut dropped frames in half. "
        "The open question is how to prove liveness when clocks drift."
    )
    assert check_ai_style(_one("ACADEMIC_PREPARATION", good_text)) == ()


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("de", "Ich möchte das Wahlpflichtmodul zur Robotik am Lehrstuhl besuchen."),
        ("fr", "Je souhaite rejoindre cette équipe de recherche du parcours robotique."),
        ("tr", "Programdaki seçmeli ders ve araştırma grubu çalışmama doğrudan uyuyor."),
        ("ru", "Эта исследовательская группа и кафедра ведут работы по управлению."),
    ],
)
def test_multilingual_programme_offering_terms_are_flagged_when_unsourced(lang, text):
    content = LetterContent(
        language=lang,
        units=(LetterUnit(archetype="WHY_PROGRAMME", text=text, claims=()),),
    )
    violations = check_unsourced_programme_claim(
        content, programme_input_ids=frozenset({VERIFIED_INPUT})
    )
    assert [(v.code, v.unit_archetype, v.blocking) for v in violations] == [
        (GateCode.UNSOURCED_PROGRAMME_CLAIM, "WHY_PROGRAMME", True)
    ]


def test_short_answer_set_with_two_why_programme_units_requires_sourced_in_at_least_one():
    verified = uuid4()
    sourced = LetterClaim(
        text="the robotics lab",
        span_start=0,
        span_end=16,
        kind=ClaimKind.SOURCED,
        source_url="https://tum.de/robotics",
        input_id=verified,
    )
    factual = _factual()
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                answers_question="q1",
                text="the robotics lab matches my thesis.",
                claims=(sourced,),
            ),
            LetterUnit(
                archetype="WHY_PROGRAMME",
                answers_question="q2",
                text="my thesis prepared me for this specialization.",
                claims=(factual,),
            ),
        ),
    )
    assert (
        check_generic_paragraph(content, programme_input_ids=frozenset({verified})) == ()
    )


@pytest.mark.parametrize(
    "bad_text",
    [
        "My meticulous work will bolster the group's research.",
        "I took a deep dive into the intricate web of distributed consensus.",
        "The vibrant community and palpable camaraderie fostered my growth.",
        "Zusammenfassend lässt sich sagen, dass dieses Studium mein Ziel ergänzt.",
        "C'est avec un vif intérêt que je soumets ma candidature à votre master.",
        "Je suis fermement persuadé que cette formation répond à mon projet.",
        "В заключение следует отметить, что программа соответствует моим целям.",
        "Sonuç olarak belirtmek gerekirse bu program hedeflerimle örtüşmektedir.",
    ],
)
def test_check_ai_style_catches_expanded_register_and_multilingual_tells(bad_text):
    violations = check_ai_style(_one("WHY_PROGRAMME", bad_text))
    assert any(
        v.code == GateCode.AI_STYLE
        and v.blocking is True
        and v.subcode == "stock_phrase"
        for v in violations
    )


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        (
            "de",
            (
                "Die Untersuchung der Optimierung und Implementierung zur Verbesserung der "
                "Zuverlässigkeit und Geschwindigkeit erfordert eine Evaluierung der Skalierbarkeit "
                "und Sicherheit in der Modellierung und Verarbeitung."
            ),
        ),
        (
            "fr",
            (
                "L'évaluation de l'optimisation et l'implémentation pour l'amélioration de la "
                "fiabilité et la modélisation du développement permettent la structuration de "
                "l'organisation et la transformation."
            ),
        ),
    ],
)
def test_check_ai_style_catches_multilingual_nominalization_density(lang, text):
    content = LetterContent(
        language=lang,
        units=(LetterUnit(archetype="ACADEMIC_PREPARATION", text=text, claims=()),),
    )
    violations = check_ai_style(content)
    assert any(
        v.code == GateCode.AI_STYLE
        and v.blocking is True
        and v.subcode == "nominalization_density"
        for v in violations
    )


def test_check_ai_style_catches_three_consecutive_uniform_sentences():
    # Three 13-word sentences followed by a 6-word sentence: overall max-min is 7 (>5),
    # so only the consecutive-3-sentence burstiness rule catches the flat run.
    text = (
        "During my bachelor thesis I built a finite volume solver for compressible flows. "
        "Testing the boundary conditions on unstructured meshes exposed a severe "
        "pressure oscillation mode. "
        "Adding a flux limiter around shock waves stabilized the residual across every run. "
        "That fix left one question."
    )
    violations = check_ai_style(_one("ACADEMIC_PREPARATION", text))
    assert any(
        v.code == GateCode.AI_STYLE
        and v.blocking is True
        and v.subcode == "consecutive_similar_length"
        for v in violations
    )


def test_check_declared_voice_retention_warns_when_all_salient_words_erased():
    inp_id = uuid4()
    raw_input = (
        "My grandmother's bakery in Ganja ran on a wood-firedbrick oven whose flue "
        "draft collapsed every winter."
    )
    erased_text = (
        "Early exposure to small-scale domestic food production challenges motivated "
        "my interest in thermal engineering."
    )
    preserved_text = (
        "Watching the wood-firedbrick oven in our Ganja bakery lose flue draft each "
        "winter sparked my interest in thermal flow."
    )
    erased_claim = LetterClaim(
        text=erased_text,
        span_start=0,
        span_end=len(erased_text),
        kind=ClaimKind.DECLARED,
        input_id=inp_id,
    )
    preserved_claim = LetterClaim(
        text=preserved_text,
        span_start=0,
        span_end=len(preserved_text),
        kind=ClaimKind.DECLARED,
        input_id=inp_id,
    )
    v_erased = check_declared_voice_retention(
        _one("PERSONAL_BACKGROUND", erased_text, (erased_claim,)),
        declared_input_texts={inp_id: raw_input},
    )
    assert len(v_erased) == 1
    assert v_erased[0].code == GateCode.AI_STYLE
    assert v_erased[0].blocking is False
    assert v_erased[0].subcode == "declared_voice_missing"

    v_preserved = check_declared_voice_retention(
        _one("PERSONAL_BACKGROUND", preserved_text, (preserved_claim,)),
        declared_input_texts={inp_id: raw_input},
    )
    assert v_preserved == ()


def test_check_cohort_overlap_blocks_paragraph_reusing_cohort_sentences():
    shared = "I want to join the Distributed Systems Group to study fault-tolerant consensus."
    other = "My thesis tested Raft under asymmetric network partitions."
    cohort = frozenset({shared.casefold()})
    content = _one("WHY_PROGRAMME", f"{shared} {other}")
    violations = check_cohort_overlap(content, cohort_sentences=cohort)
    assert len(violations) == 1
    assert violations[0].code == GateCode.GENERIC_PARAGRAPH
    assert violations[0].blocking is True
    assert violations[0].subcode == "cohort_overlap"




