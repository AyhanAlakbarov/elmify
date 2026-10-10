import pytest

from apps.documents.grammar import Rule
from apps.documents.grammar_questions import PageFacts
from apps.documents.letter_shape import LetterShape
from apps.documents.rule_sinks import letter_field, to_letter_shape

_URL = "https://example.test/apply"


def _rule(index, operation, value, **kw):
    return Rule(index=index, document=kw.pop("document", "motivation_letter"),
                operation=operation, value=value,
                sentence=kw.pop("sentence", f"sentence {index}"),
                confidence=kw.pop("confidence", 0.95), **kw)


def test_a_word_limit_lands_on_max_words():
    shape = to_letter_shape((_rule(0, "limit", 800, unit="words"),), source_url=_URL)
    assert shape.max_words == 800
    assert shape.is_stated("max_words") is True


def test_a_page_limit_and_a_character_limit_land_on_their_own_fields():
    shape = to_letter_shape((
        _rule(0, "limit", 2, unit="pages"),
        _rule(1, "limit", 4000, unit="characters"),
    ), source_url=_URL)
    assert (shape.max_pages, shape.max_chars) == (2.0, 4000)


def test_a_range_is_a_floor_and_a_cap_never_the_floor_as_the_cap():
    """"300-500 words" -- the measured defect: a verdict held one length, so
    every range lost its floor."""
    sentence = "Submit a personal statement (300-500 words)."
    shape = to_letter_shape((
        _rule(0, "limit", 300, unit="words", bound="minimum", sentence=sentence),
        _rule(0, "limit", 500, unit="words", bound="maximum", sentence=sentence),
    ), source_url=_URL)
    assert (shape.min_words, shape.max_words) == (300, 500)
    assert shape.sources["min_words"]["text"] == sentence


def test_a_character_floor_lands_on_min_chars():
    """Kassel rejects a letter under 2,800 characters (addendum §6.2)."""
    shape = to_letter_shape(
        (_rule(0, "limit", 2800, unit="characters", bound="minimum"),), source_url=_URL
    )
    assert shape.min_chars == 2800


def test_two_caps_in_two_units_are_both_kept():
    """"3,500 characters (approximately 500 words)" is two caps."""
    sentence = "3,500 characters (approximately 500 words)."
    shape = to_letter_shape((
        _rule(0, "limit", 3500, unit="characters", bound="maximum", sentence=sentence),
        _rule(0, "limit", 500, unit="words", bound="approximate", sentence=sentence),
    ), source_url=_URL)
    assert (shape.max_chars, shape.max_words) == (3500, 500)


def test_a_character_cap_counted_without_spaces_is_held_as_the_stricter_inclusive_cap():
    shape = to_letter_shape(
        (_rule(0, "limit", 3000, unit="characters", bound="maximum", excl_spaces=True),),
        source_url=_URL,
    )
    assert shape.max_chars == 3000


def test_a_page_floor_is_a_written_requirement_and_a_floor_without_spaces_is_min_chars():
    """A floor in pages has no column and nothing measures one, so it reaches the
    writer unenforced. A character floor is always checked without spaces (the
    stricter reading), so "2,000 characters without spaces" is min_chars as stated."""
    shape = to_letter_shape((
        _rule(0, "limit", 1, unit="pages", bound="minimum", sentence="At least one page."),
        _rule(1, "limit", 2000, unit="characters", bound="minimum", excl_spaces=True,
              sentence="At least 2,000 characters without spaces."),
    ), source_url=_URL)
    assert [w["text"] for w in shape.written_requirements] == ["At least one page."]
    assert shape.min_chars == 2000


@pytest.mark.parametrize("bound,sentence", [
    ("", "An exceedance of more than 10 percent is not accepted."),
    ("section_limit", "Three parts of 400 words each."),
    ("another_statement", "A 250-word statement on your research interests."),
])
def test_what_no_sink_can_enforce_is_carried_as_a_written_requirement(bound, sentence):
    """Addendum §6.5: recorded as notes, not yet enforced -- the writer reads
    them and the document carries them. A tolerance lands here as a topic,
    never as a limit."""
    shape = to_letter_shape(
        (_rule(0, "topic", sentence, bound=bound, sentence=sentence),), source_url=_URL
    )
    assert shape.written_requirements == ({"text": sentence, "source_url": _URL},)
    assert (shape.max_words, shape.min_words, shape.max_chars, shape.max_pages) == (
        None, None, None, None
    )


def test_one_sentence_with_two_note_figures_is_one_written_requirement():
    sentence = "Three parts of 400 words each, within a 10 percent tolerance."
    shape = to_letter_shape((
        _rule(0, "topic", sentence, bound="section_limit", figure=0, sentence=sentence),
        _rule(0, "topic", sentence, bound="section_limit", figure=1, sentence=sentence),
    ), source_url=_URL)
    assert len(shape.written_requirements) == 1


def test_an_implausible_cap_is_dropped_and_the_default_applies():
    """_IMPLAUSIBLE_CAP, moved verbatim from derive: a six-word cap is a misread
    digit, and acting on it blocks every letter with nobody to see why."""
    shape = to_letter_shape((_rule(0, "limit", 6, unit="words"),), source_url=_URL)
    assert shape.max_words is None


def test_an_implausible_floor_is_dropped():
    shape = to_letter_shape(
        (_rule(0, "limit", 50_000, unit="words", bound="minimum"),), source_url=_URL
    )
    assert shape.min_words is None


def test_the_letters_language_is_a_shape_field_with_its_sentence():
    """Addendum §6.4: the `language` operation writes document_language."""
    shape = to_letter_shape(
        (_rule(0, "language", "de", sentence="Das Motivationsschreiben ist auf Deutsch."),),
        source_url=_URL,
    )
    assert shape.document_language == "de"
    assert shape.sources["document_language"]["text"] == "Das Motivationsschreiben ist auf Deutsch."


def test_a_letter_allowed_in_several_languages_takes_english_when_allowed():
    shape = to_letter_shape((_rule(0, "language", ["de", "en"]),), source_url=_URL)
    assert shape.document_language == "en"


def test_form_resolves_to_the_safer_side_with_the_frontier_paths_own_rule():
    """FORMAL_LETTER over ESSAY: it keeps the prose (derive._form_decision's
    rule, now shared from letter_shape so the two paths cannot disagree)."""
    shape = to_letter_shape((
        _rule(0, "form", "essay", sentence="Write an essay."),
        _rule(1, "form", "formal_letter", sentence="Address it to the committee."),
    ), source_url=_URL)
    assert shape.form == "FORMAL_LETTER"
    assert shape.sources["form"]["text"] == "Address it to the committee."


def test_a_portal_form_alone_is_a_portal_form():
    shape = to_letter_shape((_rule(0, "form", "portal_form"),), source_url=_URL)
    assert shape.form == "PORTAL_FORM"


def test_naming_forbidden_wins_and_required_needs_every_sentence():
    assert to_letter_shape((
        _rule(0, "naming", "invited"), _rule(1, "naming", "forbidden"),
    ), source_url=_URL).naming == "FORBIDDEN"
    assert to_letter_shape((
        _rule(0, "naming", "required"), _rule(1, "naming", "invited"),
    ), source_url=_URL).naming == "INVITED"
    assert to_letter_shape((_rule(0, "naming", "required"),), source_url=_URL).naming == "REQUIRED"


def test_document_required_track_and_portfolio_come_from_the_page():
    shape = to_letter_shape(
        (_rule(0, "limit", 800, unit="words", sentence="Motivation letter, 800 words."),),
        source_url=_URL,
        page=PageFacts(letter_required="REQUIRED", track="research", portfolio_led=True),
    )
    assert shape.document_required == "REQUIRED"
    assert shape.sources["document_required"]["text"] == "Motivation letter, 800 words."
    assert (shape.track, shape.portfolio_led) == ("research", True)


def test_document_required_with_no_letter_sentence_to_witness_it_stays_unstated():
    """A flag with no sentence is a decision nobody can check (spec §6.4)."""
    shape = to_letter_shape(
        (_rule(0, "limit", 800, unit="words", document="reference_letter"),),
        source_url=_URL, page=PageFacts(letter_required="NOT_REQUIRED"),
    )
    assert shape.document_required == "UNSTATED"


def test_a_topic_becomes_a_written_requirement_carrying_its_sentence():
    """The letter's one free slot. It reaches the engine labelled as data with
    its source, exactly as a ProgramStatement does -- a subject, never an
    instruction (spec §6.1)."""
    shape = to_letter_shape(
        (_rule(0, "topic", "Explain your career plans.",
               sentence="Explain your career plans after graduation."),),
        source_url=_URL,
    )
    assert shape.written_requirements[0]["text"] == "Explain your career plans after graduation."
    assert shape.written_requirements[0]["source_url"] == _URL


def test_a_student_action_is_the_students_and_never_the_engines():
    shape = to_letter_shape(
        (_rule(0, "student_action", "sign it by hand",
               sentence="The letter must be signed by hand."),),
        source_url=_URL,
    )
    assert shape.student_actions[0]["text"] == "The letter must be signed by hand."


def test_a_template_the_letter_must_use_is_a_student_action():
    shape = to_letter_shape(
        (_rule(0, "format", "other_template", sentence="Use the form provided."),),
        source_url=_URL,
    )
    assert shape.student_actions[0]["text"] == "Use the form provided."


def test_a_reference_letter_rule_is_a_student_action_not_a_shape():
    """A reference letter binds the referee. For the applicant it is one action
    -- obtain it -- and it must never set the motivation letter's length."""
    shape = to_letter_shape(
        (_rule(0, "limit", 1, unit="pages", document="reference_letter",
               sentence="References must be one page."),),
        source_url=_URL,
    )
    assert shape.max_pages is None
    assert shape.student_actions[0]["text"] == "References must be one page."


def test_a_style_rule_reaches_the_shape_field_it_names():
    shape = to_letter_shape((
        _rule(0, "style", "signed_declaration"),
        _rule(1, "style", "handwritten"),
        _rule(2, "style", "font_size_minimum", detail="12"),
        _rule(3, "style", "line_spacing", detail="1.5"),
        _rule(4, "style", "margins", detail="2.5", sentence="Margins of 2.5cm on all sides."),
    ), source_url=_URL)
    assert shape.signed_declaration is True and shape.handwritten is True
    assert (shape.font_min_pt, shape.line_spacing, shape.margins_cm) == (12, 1.5, 2.5)


def test_a_font_size_or_margin_outside_the_frontier_paths_range_is_dropped():
    """LetterVerdict bounded font_min_pt to 4..40 and margins_cm to 0.1..10; the
    grammar keeps both bounds rather than trusting a picked number more."""
    shape = to_letter_shape((
        _rule(0, "style", "font_size_minimum", detail="400"),
        _rule(1, "style", "margins", detail="25", sentence="Margins of 25cm on all sides."),
    ), source_url=_URL)
    assert (shape.font_min_pt, shape.margins_cm) == (None, None)


# Fix round 1.


def test_an_unsupported_line_spacing_is_a_written_requirement_not_silence():
    """Finding 1: LetterShape has no field for 1.15 (Task 6 deliberately offers
    it as a candidate spacing_candidates finds), so it must not vanish."""
    sentence = "Use 1.15 line spacing."
    shape = to_letter_shape(
        (_rule(0, "style", "line_spacing", detail="1.15", sentence=sentence),), source_url=_URL
    )
    assert shape.line_spacing is None
    assert shape.written_requirements == ({"text": sentence, "source_url": _URL},)


@pytest.mark.parametrize("style,detail,sentence", [
    ("font_size_minimum", "400", "Use at least 400pt font."),
    ("margins", "25", "Margins of 25cm on all sides."),
])
def test_an_out_of_range_font_or_margin_is_a_written_requirement_not_silence(
    style, detail, sentence
):
    """Finding 1: the range check drops the field, never the sentence."""
    shape = to_letter_shape(
        (_rule(0, "style", style, detail=detail, sentence=sentence),), source_url=_URL
    )
    assert (shape.font_min_pt, shape.margins_cm) == (None, None)
    assert shape.written_requirements == ({"text": sentence, "source_url": _URL},)


@pytest.mark.parametrize("sentence,expected", [
    ("Margins of 1 inch on all sides.", None),
    ("Margins of 2.5 cm on all sides.", 2.5),
    ("Margins of 25 mm on all sides.", 2.5),
    ("Use adequate margins.", None),
])
def test_a_margin_maps_to_centimetres_only_when_the_sentence_names_cm_or_mm(
    sentence, expected
):
    """Finding 2: an inch or an unstated unit read as a centimetre is a
    narrower margin than the page asked for -- the unsafe direction."""
    detail = "1" if "inch" in sentence else ("2.5" if "cm" in sentence else "25")
    shape = to_letter_shape(
        (_rule(0, "style", "margins", detail=detail, sentence=sentence),), source_url=_URL
    )
    assert shape.margins_cm == expected
    if expected is None:
        assert shape.written_requirements == ({"text": sentence, "source_url": _URL},)


@pytest.mark.django_db
def test_a_letter_page_floor_is_marked_unapplied_before_this_module_sees_it():
    """Finding 3: a letter page floor is `unapplied` at grammar_values time
    (the same `limit_sink` check `_letter_limit` also carries as a fallback),
    so it never reaches `letter_field` applied. It surfaces through
    `to_notes`, not through `to_letter_shape`'s written_requirements."""
    from apps.documents.derive import Candidate
    from apps.documents.grammar import Slotted
    from apps.documents.grammar_values import read_values
    from apps.documents.rule_sinks import to_notes
    from apps.research.decisions import Answer

    def _client(script):
        def call(state, questions, *, decision, language="", budget=None, record=True,
                 client=None):
            return {
                qid: Answer(id=qid, value=script[qid][0], confidence=script[qid][1],
                            probabilities={}, model="jev-1.13.0", provider="typesafe")
                for qid in questions
            }
        return call

    sentence = "The letter must be at least one page long."
    candidates = (Candidate(text=sentence, heading="", europass=False),)
    slots = (Slotted(index=0, document="motivation_letter", document_confidence=0.97,
                     operation="limit", operation_confidence=0.95,
                     third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_client({
        "0:figure:0:bound": ("minimum", 0.95), "0:figure:0:unit": ("pages", 0.97),
    }))
    assert [(r.value, r.bound, r.note) for r in rules] == [(1, "minimum", "unapplied")]

    shape = to_letter_shape(rules, source_url=_URL)
    assert shape.max_pages is None
    assert shape.written_requirements == ()

    notes = to_notes(rules, source_url=_URL)
    assert len(notes) == 1
    assert notes[0].key == "unapplied"
    assert sentence in notes[0].rule_text


def test_every_stated_field_records_where_it_came_from():
    shape = to_letter_shape((_rule(0, "limit", 800, unit="words",
                                   sentence="At most 800 words."),), source_url=_URL)
    assert shape.sources["max_words"]["text"] == "At most 800 words."
    assert shape.sources["max_words"]["source_url"] == _URL


def test_a_note_sets_no_field():
    shape = to_letter_shape(
        (_rule(0, "limit", 800, unit="words", note="unsure"),), source_url=_URL
    )
    assert shape.max_words is None
    assert shape.sources == {}


def test_a_page_with_no_letter_rule_is_an_empty_shape():
    assert to_letter_shape((), source_url=_URL) == LetterShape()


@pytest.mark.parametrize("family", ["Arial; } body { display:none", "Arial\n"])
def test_a_font_family_that_is_not_plain_latin_text_is_dropped(family):
    """The one field that is not a closed list. Never interpolate it into CSS
    unvalidated -- Django's autoescaping does not neutralise ';' or '{' inside
    a CSS value. fullmatch, not match: `$` matches before a trailing newline."""
    shape = to_letter_shape(
        (_rule(0, "style", "font_family", detail=family),), source_url=_URL,
    )
    assert shape.font_family is None


def test_letter_field_is_what_the_gate_scores():
    """Task 11 scores the 77-sentence eval through this function, so the gate
    measures the projection that ships."""
    assert letter_field(_rule(0, "limit", 500, unit="words", bound="minimum")) == (
        "min_words", 500
    )
    assert letter_field(_rule(0, "naming", "forbidden")) == ("naming", "forbidden")
    assert letter_field(_rule(0, "limit", 500, unit="words", note="unsure")) is None


# Controller rulings on this task.


@pytest.mark.parametrize("pages", [0.5, 1.5])
def test_a_page_figure_is_never_truncated_to_an_integer(pages):
    """C8: 1.5 pages stays 1.5, and half a page never becomes 0 -- a cap of 0
    reads as "no bound stated" in more than one place downstream."""
    shape = to_letter_shape((_rule(0, "limit", pages, unit="pages"),), source_url=_URL)
    assert shape.max_pages == pages


def test_words_and_characters_are_whole_numbers():
    """C8: a word or character figure is an int, never a float in an int column."""
    field, value = letter_field(_rule(0, "limit", 800, unit="words"))
    assert (field, value, type(value)) == ("max_words", 800, int)


def test_an_essay_sentence_and_a_portal_sentence_never_make_a_portal_form():
    """C9: PORTAL_FORM only when portal_form is the ONLY form the page states --
    a wrongly assumed form drops the letter's prose entirely."""
    shape = to_letter_shape((
        _rule(0, "form", "essay", sentence="Write an essay."),
        _rule(1, "form", "portal_form", sentence="Answer in the online form."),
    ), source_url=_URL)
    assert shape.form == "FORMAL_LETTER"


def test_a_lone_essay_is_an_essay_in_the_shapes_own_case():
    """The grammar's values are lowercase; LetterShape's are uppercase."""
    shape = to_letter_shape((_rule(0, "form", "essay", sentence="An essay."),), source_url=_URL)
    assert (shape.form, shape.sources["form"]["text"]) == ("ESSAY", "An essay.")


@pytest.mark.parametrize("operation,value", [
    ("form", "none"), ("form", "FORMAL_LETTER"), ("naming", "none"), ("naming", "REQUIRED"),
])
def test_a_form_or_naming_value_outside_the_grammars_list_sets_nothing(operation, value):
    shape = to_letter_shape((_rule(0, operation, value),), source_url=_URL)
    assert shape == LetterShape()


@pytest.mark.parametrize("note", ["conditional", "third_party"])
def test_a_conditional_or_third_party_rule_is_never_a_shape_field(note):
    """C3: a note, never a field -- not even the witness for document_required."""
    shape = to_letter_shape(
        (_rule(0, "limit", 800, unit="words", note=note),),
        source_url=_URL, page=PageFacts(letter_required="REQUIRED"),
    )
    assert shape.max_words is None and shape.document_required == "UNSTATED"


@pytest.mark.parametrize("detail,expected", [("2", 2.0), ("1", 1.0), ("1.5", 1.5)])
def test_a_line_spacing_the_page_prints_as_a_whole_number_is_kept(detail, expected):
    """spacing_candidates offers the figure as printed, so "2" arrives, not "2.0"."""
    shape = to_letter_shape((_rule(0, "style", "line_spacing", detail=detail),), source_url=_URL)
    assert shape.line_spacing == expected


def test_a_fractional_minimum_font_size_rounds_up_never_down():
    """A minimum of 10.5pt held as 10 would let a letter under the page's minimum through."""
    shape = to_letter_shape(
        (_rule(0, "style", "font_size_minimum", detail="10.5"),), source_url=_URL
    )
    assert shape.font_min_pt == 11


def test_two_caps_on_one_field_keep_the_smaller_and_its_sentence():
    shape = to_letter_shape((
        _rule(0, "limit", 800, unit="words", sentence="At most 800 words."),
        _rule(1, "limit", 600, unit="words", sentence="Keep it under 600 words."),
    ), source_url=_URL)
    assert shape.max_words == 600
    assert shape.sources["max_words"]["text"] == "Keep it under 600 words."


def test_both_paths_resolve_with_the_same_functions():
    """The frontier judge re-imports the moved rules rather than keeping a copy."""
    from apps.documents import derive, letter_shape

    assert derive._form_decision is letter_shape._form_decision
    assert derive._naming_decision is letter_shape._naming_decision
    assert derive._SAFE_FONT_FAMILY is letter_shape._SAFE_FONT_FAMILY


def test_a_letter_length_in_a_unit_nothing_measures_reaches_the_writer():
    shape = to_letter_shape(
        (_rule(0, "limit", 3, unit="minutes", sentence="A three-minute video."),),
        source_url=_URL,
    )
    assert [w["text"] for w in shape.written_requirements] == ["A three-minute video."]


# 2026-10-08: a referee fact is a record on the programme, never a second copy
# of the sentence among the student's actions.
_REF = "Two letters of recommendation, uploaded by your referees by 15 January 2027."


def test_a_referee_rule_is_a_record_and_not_a_second_student_action():
    from apps.documents.rule_sinks import to_notes, to_referee

    rules = (
        _rule(0, "student_action", _REF, document="reference_letter", sentence=_REF),
        _rule(0, "referee", ("count", "TWO"), document="reference_letter", sentence=_REF),
        _rule(0, "referee", ("due", "BEFORE_DEADLINE"), document="reference_letter",
              sentence=_REF, detail="15 January 2027"),
        _rule(0, "referee", ("mode", "PORTAL_INVITE"), document="reference_letter",
              sentence=_REF, note="conditional", condition="track"),
    )

    shape = to_letter_shape(rules, source_url=_URL)
    assert [a["text"] for a in shape.student_actions] == [_REF]
    assert to_notes(rules, source_url=_URL) == ()
    assert to_referee(rules, source_url=_URL) == (
        {"field": "count", "value": "TWO", "date": "", "conditional": False,
         "condition": "", "rule_text": _REF, "source_url": _URL},
        {"field": "due", "value": "BEFORE_DEADLINE", "date": "15 January 2027",
         "conditional": False, "condition": "", "rule_text": _REF, "source_url": _URL},
        {"field": "mode", "value": "PORTAL_INVITE", "date": "", "conditional": True,
         "condition": "track", "rule_text": _REF, "source_url": _URL},
    )
