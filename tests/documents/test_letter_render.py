import pytest

from apps.documents.constraints import ConstraintRule, Enforcement
from apps.documents.letter_gates import check_claim_coverage
from apps.documents.letter_render import (
    hygienic_letter_content,
    render_letter,
    select_letter_variant,
)
from apps.documents.letter_schemas import ClaimKind, LetterClaim, LetterContent, LetterUnit
from apps.documents.render import ContentHygieneFailed, PreflightBlocked
from apps.funding.models import ApplicationPrompt


def test_select_letter_variant_maps_all_structures():
    assert select_letter_variant(ApplicationPrompt.Structure.SHORT_ANSWER_SET) == "FIELD_MAPPED"
    assert select_letter_variant(ApplicationPrompt.Structure.CONTINUOUS_LETTER) == "LETTER_PDF"
    assert select_letter_variant(ApplicationPrompt.Structure.TWO_STATEMENTS) == "LETTER_PDF"
    assert (
        select_letter_variant(ApplicationPrompt.Structure.PRESCRIBED_RESEARCH_FORM)
        == "TWO_SECTION_FORM"
    )


def test_short_answer_set_renders_as_field_mapped_portal_text():
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="Because of the robotics lab.",
                answers_question="q1",
            ),
            LetterUnit(
                archetype="CAREER_PLAN_RETURN",
                text="I will return to lead a research team.",
                answers_question="q2",
            ),
        ),
    )
    artifact = render_letter(content, structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET)
    assert artifact.pdf_bytes is None
    assert artifact.field_mapped == {
        "q1": "Because of the robotics lab.",
        "q2": "I will return to lead a research team.",
    }


def test_continuous_letter_renders_pdf_with_header_block():
    content = LetterContent(
        language="en",
        header_block="Example University -- MSc Computer Science",
        units=(LetterUnit(archetype="OPENING", text="Dear Admissions Committee,"),),
    )
    artifact = render_letter(content, structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER)
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(artifact.pdf_bytes))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert "Example University" in text
    assert "Dear Admissions Committee" in text


def test_two_section_form_renders_pdf():
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="ACADEMIC_PREPARATION", text="My field of study has been NLP."),
            LetterUnit(archetype="RESEARCH_PLAN", text="I propose to research transfer learning."),
        ),
    )
    artifact = render_letter(
        content, structure=ApplicationPrompt.Structure.PRESCRIBED_RESEARCH_FORM
    )
    assert artifact.pdf_bytes is not None


def test_two_section_form_is_tagged_with_its_own_variant_not_letter_pdf():
    """Fix 1: _render_pdf must report the variant it actually rendered.

    _TEMPLATE_BY_VARIANT maps both LETTER_PDF and TWO_SECTION_FORM to real
    templates; a PRESCRIBED_RESEARCH_FORM render must not come back tagged
    as LETTER_PDF, or the RenderedArtifact metadata silently misreports what
    was rendered (render.py's own UnsupportedRenderVariant docstring states
    this contract for the CV engine; letters must keep it too).
    """
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="ACADEMIC_PREPARATION", text="My field of study has been NLP."),
            LetterUnit(archetype="RESEARCH_PLAN", text="I propose to research transfer learning."),
        ),
    )
    artifact = render_letter(
        content, structure=ApplicationPrompt.Structure.PRESCRIBED_RESEARCH_FORM
    )
    assert artifact.variant == "TWO_SECTION_FORM"


def test_continuous_letter_is_tagged_letter_pdf():
    content = LetterContent(
        language="en", units=(LetterUnit(archetype="OPENING", text="Dear Committee,"),)
    )
    artifact = render_letter(content, structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER)
    assert artifact.variant == "LETTER_PDF"


def test_min_words_floor_binding_violation_blocks():
    rule = ConstraintRule(
        rule_id="L-008",
        key="min_words",
        value=50,
        enforcement=Enforcement.BINDING,
        rule_text="800 words minimum",
        source_url="",
    )
    content = LetterContent(
        language="en", units=(LetterUnit(archetype="WHY_PROGRAMME", text="Too short."),)
    )
    with pytest.raises(PreflightBlocked):
        render_letter(
            content,
            structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
            constraints=(rule,),
        )


def test_max_chars_incl_spaces_binding_violation_blocks():
    rule = ConstraintRule(
        rule_id="L-016",
        key="max_chars_incl_spaces",
        value=10,
        enforcement=Enforcement.BINDING,
        rule_text="10 char cap",
        source_url="",
    )
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="Because of the robotics lab.",
                answers_question="q1",
            ),
        ),
    )
    with pytest.raises(PreflightBlocked):
        render_letter(
            content,
            structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET,
            constraints=(rule,),
        )


def test_per_question_cap_blocks_only_the_question_that_overruns():
    """Australia GS shape: four 150-word boxes, not one 600-word document.

    q1 is inside its own cap and q2 overruns its own -- a document-level
    max_words of 600 would pass this letter while the portal truncates q2.
    """
    questions = [
        {"id": "q1", "max_words": 150},
        {"id": "q2", "max_words": 3},
    ]
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="WHY_PROGRAMME", text="Short answer.", answers_question="q1"),
            LetterUnit(
                archetype="CAREER_PLAN_RETURN",
                text="This answer runs well past its own box.",
                answers_question="q2",
            ),
        ),
    )
    with pytest.raises(PreflightBlocked, match="q2"):
        render_letter(
            content,
            structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET,
            questions=questions,
        )


def test_per_question_caps_pass_when_every_answer_is_inside_its_own_box():
    questions = [
        {"id": "q1", "max_words": 150, "max_chars_incl_spaces": 900},
        {"id": "q2", "max_words": 150, "max_chars_incl_spaces": 900},
    ]
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="Because of the robotics lab.",
                answers_question="q1",
            ),
            LetterUnit(
                archetype="CAREER_PLAN_RETURN",
                text="I will return to lead a team.",
                answers_question="q2",
            ),
        ),
    )
    artifact = render_letter(
        content, structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET, questions=questions
    )
    assert artifact.field_mapped is not None


def test_an_unanswered_question_is_not_a_cap_violation():
    """A ceiling, not a floor -- coverage is Task 6's PROMPT_REQUIREMENT_UNMET."""
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME", text="Only q1 answered.", answers_question="q1"
            ),
        ),
    )
    artifact = render_letter(
        content,
        structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET,
        questions=[{"id": "q1", "max_words": 150}, {"id": "q2", "max_words": 150}],
    )
    assert artifact.field_mapped == {"q1": "Only q1 answered."}


def test_constraint_within_limits_does_not_block():
    rule = ConstraintRule(
        rule_id="L-053",
        key="max_words",
        value=500,
        enforcement=Enforcement.BINDING,
        rule_text="less than 500 words",
        source_url="",
    )
    content = LetterContent(
        language="en", units=(LetterUnit(archetype="WHY_PROGRAMME", text="A short letter."),)
    )
    artifact = render_letter(
        content, structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER, constraints=(rule,)
    )
    assert artifact.pdf_bytes is not None


# --- Fix 2: claim-span re-anchoring after hygiene ---------------------------


def test_hygienic_letter_content_reanchors_claim_spans_after_cleaning():
    """A control character ahead of a claim shifts every later offset.

    Without re-anchoring, the claim's untouched span_start/span_end from
    generation would no longer locate the (also-cleaned) claim text inside
    the (also-cleaned) unit text -- desynchronizing check_claim_coverage's
    sentence-to-claim mapping.
    """
    claim_text = "Example University offers a strong robotics lab."
    raw_text = "\x00" + claim_text
    claim = LetterClaim(
        text=claim_text,
        span_start=1,
        span_end=1 + len(claim_text),
        kind=ClaimKind.SOURCED,
        source_url="https://example.test/robotics",
    )
    content = LetterContent(
        language="en",
        units=(LetterUnit(archetype="WHY_PROGRAMME", text=raw_text, claims=(claim,)),),
    )
    cleaned = hygienic_letter_content(content)
    cleaned_unit = cleaned.units[0]
    cleaned_claim = cleaned_unit.claims[0]
    assert "\x00" not in cleaned_unit.text
    assert cleaned_unit.text == claim_text
    # The span must be re-derived against the CLEANED text, not merely
    # shifted by a fixed offset -- it must actually locate claim_text.
    assert cleaned_unit.text[cleaned_claim.span_start : cleaned_claim.span_end] == claim_text
    assert cleaned_claim.span_start == 0
    assert cleaned_claim.span_end == len(claim_text)


def test_hygienic_letter_content_fails_closed_when_cleaning_restructures_sentences():
    """Cleaning that changes how many sentences a unit has is real content
    restructuring, not a shift -- no claim can be mapped across with
    confidence, so this must raise rather than silently mis-anchor.

    A vertical tab is whitespace to _SENTENCE_SPLIT and a control character
    to normalize_text, so removing it merges two sentences into one. This
    replaces the older "claim text no longer appears in the cleaned unit
    text" signal: spans are now re-anchored to sentence bounds rather than
    to the claim's own text, so the claim's text is no longer what locates
    it, and sentence structure is.
    """
    claim = LetterClaim(
        text="I studied at TU Munich.",
        span_start=0,
        span_end=23,
        kind=ClaimKind.SOURCED,
        source_url="https://example.test/x",
    )
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="I studied at TU Munich.\x0bI then worked in Berlin.",
                claims=(claim,),
            ),
        ),
    )
    with pytest.raises(ContentHygieneFailed):
        hygienic_letter_content(content)


#: The sentence a phrase-shaped claim supports. Its digits and its
#: capitalised phrase are what make check_claim_coverage's _has_trigger fire;
#: without a trigger the coverage assertions below would pass vacuously.
_TRIGGERING_SENTENCE = "I completed a BSc in Computer Science at TU Munich in 2021."
#: A strict, short substring of it -- the natural shape of LetterClaim.text,
#: and never equal to the whole sentence.
_PHRASE = "a BSc in Computer Science at TU Munich in 2021"


def test_hygienic_letter_content_keeps_a_phrase_claim_covering_its_whole_sentence():
    """The regression this pins: re-anchoring a claim to its own `text`
    narrowed every phrase-shaped claim's span to less than a sentence, and
    check_claim_coverage requires ENCLOSURE -- so hygiene turned a correct
    letter into a deterministic UNDECLARED_ASSERTION block that the one
    bounded retry could not clear.

    Nothing here is dirty, so cleaning is a no-op and the re-anchoring is the
    only thing that can break coverage.
    """
    unit_text = f"{_TRIGGERING_SENTENCE} I then worked on low-resource NLP."
    claim = LetterClaim(
        text=_PHRASE,
        span_start=0,
        span_end=len(_TRIGGERING_SENTENCE),
        kind=ClaimKind.SOURCED,
        source_url="https://tum.de/robotics",
    )
    content = LetterContent(
        language="en",
        units=(LetterUnit(archetype="WHY_PROGRAMME", text=unit_text, claims=(claim,)),),
    )
    assert check_claim_coverage(content.units[0]) == ()

    cleaned_unit = hygienic_letter_content(content).units[0]

    assert check_claim_coverage(cleaned_unit) == ()
    cleaned_claim = cleaned_unit.claims[0]
    assert (cleaned_claim.span_start, cleaned_claim.span_end) == (0, len(_TRIGGERING_SENTENCE))
    # The claim's own text is still a STRICT substring of what its span now
    # covers -- i.e. this is not the degenerate claim.text == unit.text case.
    assert cleaned_claim.text != unit_text[cleaned_claim.span_start : cleaned_claim.span_end]


def test_hygienic_letter_content_reanchors_a_phrase_claim_past_a_removed_character():
    """The two halves together: a strict-substring claim AND a control
    character ahead of it, so the sentence bounds genuinely move."""
    unit_text = f"{_TRIGGERING_SENTENCE} I then worked on low-resource NLP."
    claim = LetterClaim(
        text=_PHRASE,
        span_start=0,
        span_end=1 + len(_TRIGGERING_SENTENCE),
        kind=ClaimKind.SOURCED,
        source_url="https://tum.de/robotics",
    )
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="WHY_PROGRAMME", text="\x00" + unit_text, claims=(claim,)),
        ),
    )
    cleaned_unit = hygienic_letter_content(content).units[0]

    assert cleaned_unit.text == unit_text
    assert check_claim_coverage(cleaned_unit) == ()
    assert cleaned_unit.claims[0].span_end == len(_TRIGGERING_SENTENCE)


def test_two_section_form_blocks_a_unit_it_has_no_section_for():
    """letter_two_section.html renders ACADEMIC_PREPARATION and RESEARCH_PLAN
    and silently discarded everything else -- so a counselor could approve a
    letter and the PDF would be missing a paragraph of it, with no signal
    anywhere. Those two archetypes are exactly what this structure's own
    playbook (silent_funder, RESEARCH_SUPERVISOR) writes, so a third one is a
    prompt disagreeing with its structure, not an intended exclusion."""
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="ACADEMIC_PREPARATION", text="I read maths at Bonn."),
            LetterUnit(archetype="RESEARCH_PLAN", text="I will study sparse retrieval."),
            LetterUnit(archetype="CLOSING", text="Thank you for your consideration."),
        ),
    )
    with pytest.raises(PreflightBlocked) as error:
        render_letter(
            content, structure=ApplicationPrompt.Structure.PRESCRIBED_RESEARCH_FORM
        )
    assert "CLOSING" in str(error.value)


def test_two_section_form_renders_when_every_unit_has_a_section():
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="ACADEMIC_PREPARATION", text="I read maths at Bonn."),
            LetterUnit(archetype="RESEARCH_PLAN", text="I will study sparse retrieval."),
        ),
    )
    artifact = render_letter(
        content, structure=ApplicationPrompt.Structure.PRESCRIBED_RESEARCH_FORM
    )
    assert artifact.variant == "TWO_SECTION_FORM"


def _field_mapped_content():
    """One unit the portal has a box for, and one it does not. The unmapped
    unit is far longer, so a constraint measured over all units and one
    measured over only the rendered units give different answers."""
    return LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="Because of the robotics lab.",
                answers_question="q1",
            ),
            LetterUnit(archetype="OPENING", text=" ".join(["filler"] * 200)),
        ),
    )


def test_field_mapped_word_count_measures_only_what_the_portal_receives():
    """_render_field_mapped drops every unit with no answers_question, and
    the constraint check used to measure the dropped text too -- so a
    document-level word cap was being spent on words the reader never sees."""
    rule = ConstraintRule(
        rule_id="R-WORDS",
        key="max_words",
        value=50,
        enforcement=Enforcement.BINDING,
        rule_text="portal word cap",
        source_url="https://example.test/rules",
    )
    artifact = render_letter(
        _field_mapped_content(),
        structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET,
        constraints=(rule,),
    )
    assert artifact.field_mapped == {"q1": "Because of the robotics lab."}


def test_field_mapped_word_count_still_blocks_on_the_text_it_does_send():
    rule = ConstraintRule(
        rule_id="R-WORDS",
        key="max_words",
        value=2,
        enforcement=Enforcement.BINDING,
        rule_text="portal word cap",
        source_url="https://example.test/rules",
    )
    with pytest.raises(PreflightBlocked):
        render_letter(
            _field_mapped_content(),
            structure=ApplicationPrompt.Structure.SHORT_ANSWER_SET,
            constraints=(rule,),
        )
