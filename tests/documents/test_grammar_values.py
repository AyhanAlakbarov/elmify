import pytest

from apps.documents.derive import Candidate
from apps.documents.grammar import Slotted, limit_sink, sink_for
from apps.documents.grammar_values import FORMAT_EXAMPLES, read_values, value_questions, value_state
from apps.research.decisions import Answer

pytestmark = pytest.mark.django_db


def _script(script):
    """Answers from the script; anything unscripted answers 'nothing here', so a
    test states only the questions it is about."""

    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        answers = {}
        for qid, question in questions.items():
            if qid in script:
                value, confidence = script[qid]
            else:
                value, confidence = _neutral(question), 0.99
            answers[qid] = Answer(id=qid, value=value, confidence=confidence,
                                  probabilities={str(value): confidence},
                                  model="jev-1.13.0", provider="typesafe")
        return answers

    return call


def _neutral(question):
    options = getattr(question, "options", None)
    if options is None:
        return False
    for neutral in ("not_a_limit", "none", "other", "any", "not_a_format_rule", "NOT_STATED"):
        if neutral in options:
            return neutral
    return options[0]


def _one(text, document, operation, **slot):
    """One sentence and its settled slots, for the tests written after the amendment."""
    candidates = (Candidate(text=text, heading="", europass=False),)
    slots = (Slotted(index=0, document=document, document_confidence=0.97,
                     operation=operation, operation_confidence=0.95,
                     third_party=slot.get("third_party", False),
                     conditional=slot.get("conditional", False)),)
    return candidates, slots


def test_a_style_sentence_is_asked_for_its_sub_values_in_the_same_request():
    """The style value and its detail cannot be two requests: the detail
    question would have to know which style was chosen, and that answer is in
    the same response. So every detail question is asked unconditionally and
    only the one the chosen style needs is read -- tokens, not calls."""
    candidates = (Candidate(text="Use Times New Roman at 11pt.", heading="", europass=False),)
    slots = (Slotted(index=0, document="motivation_letter", document_confidence=0.95,
                     operation="style", operation_confidence=0.92, third_party=False,
                     conditional=False),)
    questions = value_questions(candidates, slots)
    assert {"0:style", "0:style_number", "0:style_spacing", "0:style_font"} <= set(questions)
    assert questions["0:style_number"].options == ("11", "none")


def test_a_font_family_is_picked_from_the_names_the_sentence_prints():
    from apps.documents.grammar_values import font_candidates

    assert font_candidates("Use Times New Roman at 11pt.") == ("Times New Roman",)
    assert font_candidates("Any legible font is fine.") == ()
    candidates = (Candidate(text="Use Times New Roman at 11pt.", heading="", europass=False),)
    slots = (Slotted(index=0, document="motivation_letter", document_confidence=0.95,
                     operation="style", operation_confidence=0.92, third_party=False,
                     conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("font_family", 0.94), "0:style_font": ("Times New Roman", 0.96),
    }))
    assert (rules[0].value, rules[0].detail) == ("font_family", "Times New Roman")


def test_a_minimum_font_size_is_picked_from_the_numbers_on_the_page():
    candidates = (Candidate(text="Use Times New Roman at 11pt.", heading="", europass=False),)
    slots = (Slotted(index=0, document="motivation_letter", document_confidence=0.95,
                     operation="style", operation_confidence=0.92, third_party=False,
                     conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("font_size_minimum", 0.93), "0:style_number": ("11", 0.97),
    }))
    assert (rules[0].value, rules[0].detail) == ("font_size_minimum", "11")


def test_a_margin_keeps_its_decimal():
    """The old digit finder read "2,5 cm" as 25: a 25 cm margin on a page 21 cm wide."""
    candidates, slots = _one("Margins of 2,5 cm on every side.", "motivation_letter", "style")
    assert value_questions(candidates, slots)["0:style_number"].options == ("2.5", "none")
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("margins", 0.93), "0:style_number": ("2.5", 0.95),
    }))
    assert (rules[0].value, rules[0].detail) == ("margins", "2.5")


# <!-- fix round 1, finding 6 -->
def test_line_spacing_options_come_from_the_page_not_a_fixed_menu():
    """The old options list was a fixed ("1.0", "1.5", "2.0", "none") menu
    offered whether or not the page said any of them -- "1.15" is a real page
    value that menu had no room for."""
    candidates, slots = _one("Use 1.15 line spacing.", "motivation_letter", "style")
    assert "1.15" in value_questions(candidates, slots)["0:style_spacing"].options
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("line_spacing", 0.93), "0:style_spacing": ("1.15", 0.96),
    }))
    assert (rules[0].value, rules[0].detail) == ("line_spacing", "1.15")


def test_only_the_operations_present_get_value_questions():
    """The 48 format examples ride on format sentences only -- that is why the
    slots and the values are two requests (spec §6.1). A limit sentence gets,
    per figure, a bound, a unit and -- on the CV, where it picks a key --
    whether spaces count."""
    candidates, slots = _one("Your CV may not exceed two pages.", "cv", "limit")
    assert set(value_questions(candidates, slots)) == {
        "0:figure:0:bound", "0:figure:0:unit", "0:figure:0:spaces",
    }


def test_a_sentence_allowing_two_languages_yields_both():
    """Eiffel's R-072: 'CV in French or English'. render._check_language has
    taken a list since, so a Choice picking one would silently forbid the
    other -- and a CV in the forbidden one is a rejected application."""
    from apps.documents.grammar_values import language_candidates

    assert {c for _, c in language_candidates("CV in French or English.")} == {"fr", "en"}
    candidates = (Candidate(text="CV in French or English.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.97, operation="language",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:language:fr": (True, 0.96), "0:language:en": (True, 0.97),
    }))
    assert rules[0].value == ["en", "fr"]


def test_a_sentence_allowing_one_language_yields_a_bare_string():
    """A one-item list would change nothing except how the rule reads to a
    person, and _check_language keeps a bare string's exact meaning."""
    candidates = (Candidate(text="The CV must be in English.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.97, operation="language",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({"0:language:en": (True, 0.98)}))
    assert rules[0].value == "en"


# <!-- fix round 1, finding 3 -->
def test_a_language_named_below_the_bar_is_an_unsure_note_not_a_dragged_confidence():
    """A language answered yes below the bar must not silently vanish (it gets
    its own 'unsure' note, kept visible) and must not drag the accepted
    language's own reported confidence down with it."""
    candidates = (Candidate(text="CV in English or, if unavoidable, Spanish.", heading="",
                            europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.97, operation="language",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:language:en": (True, 0.97), "0:language:es": (True, 0.5),
    }))
    applied = [r for r in rules if not r.note]
    unsure = [r for r in rules if r.note == "unsure"]
    assert len(applied) == 1
    assert (applied[0].value, applied[0].confidence) == ("en", 0.97)
    assert len(unsure) == 1


def test_a_language_the_sentence_names_but_forbids_is_not_a_value():
    candidates = (Candidate(text="German is not accepted; write in English.", heading="",
                            europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.97, operation="language",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:language:de": (False, 0.94), "0:language:en": (True, 0.97),
    }))
    assert rules[0].value == "en"


def test_a_page_limit_is_a_figure_code_found():
    candidates, slots = _one("Your CV may not exceed two pages.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.96), "0:figure:0:unit": ("pages", 0.98),
    }))
    assert (rules[0].value, rules[0].unit, rules[0].bound) == (2, "pages", "maximum")
    assert rules[0].applied is True


def test_a_limit_sentence_with_no_figure_is_unapplied_and_nothing_can_be_invented():
    """The same principle as verified_statements, now structural: no figure on
    the page means no figure question at all, so there is nothing a provider
    could answer with a number nobody wrote."""
    candidates, slots = _one("Keep the CV short.", "cv", "limit")
    assert set(value_questions(candidates, slots)) == set()
    rules = read_values(candidates, slots, client=_script({}))
    assert [(r.value, r.note) for r in rules] == [(None, "unapplied")]


def test_a_range_is_a_floor_and_a_cap_never_the_floor_as_the_cap():
    """Addendum §6.1. Measured 2026-09-25: every floor and range lost its floor,
    because a verdict held one length."""
    candidates, slots = _one("The motivation letter should be 300–500 words.",
                             "motivation_letter", "limit")
    assert value_state(candidates, slots)["sentences"][0]["figures"] == [
        {"figure": "300", "unit_as_printed": "words"},
        {"figure": "500", "unit_as_printed": "words"},
    ]
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("minimum", 0.93), "0:figure:0:unit": ("words", 0.97),
        "0:figure:1:bound": ("maximum", 0.95), "0:figure:1:unit": ("words", 0.98),
    }))
    assert [(r.value, r.unit, r.bound, r.figure, r.applied) for r in rules] == [
        (300, "words", "minimum", 0, True), (500, "words", "maximum", 1, True),
    ]
    assert [limit_sink(r.document, r.bound, r.unit) for r in rules] == ["min_words", "max_words"]


def test_a_figure_in_each_unit_is_two_caps():
    text = "The letter may have at most 3,500 characters (approximately 500 words)."
    candidates, slots = _one(text, "motivation_letter", "limit")
    # The letter's one character cap is measured with spaces, so it is not asked.
    assert "0:figure:0:spaces" not in value_questions(candidates, slots)
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.94), "0:figure:0:unit": ("characters", 0.97),
        "0:figure:1:bound": ("approximate", 0.91), "0:figure:1:unit": ("words", 0.96),
    }))
    assert [(r.value, r.unit, r.bound) for r in rules] == [
        (3500, "characters", "maximum"), (500, "words", "approximate"),
    ]
    assert {limit_sink(r.document, r.bound, r.unit) for r in rules} == {"max_chars", "max_words"}


@pytest.mark.parametrize(
    ("text", "number", "bound"),
    [
        ("Die Begründung umfasst maximal zwei DIN-A4-Seiten.", 2, "maximum"),  # TUM
        ("Approximately one A4 page.", 1, "approximate"),  # ETH
    ],
)
def test_a_limit_written_as_a_word_is_a_figure(text, number, bound):
    candidates, slots = _one(text, "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": (bound, 0.93), "0:figure:0:unit": ("pages", 0.97),
    }))
    assert [(r.value, r.unit, r.bound) for r in rules] == [(number, "pages", bound)]


def test_a_space_grouped_thousand_is_the_figure_and_its_stray_part_is_never_offered():
    """Sciences Po, measured 2026-09-25. Fix round 1, finding 1: the stray part
    ("1") is no longer offered as its own figure at all, so there is only one
    figure to ask about -- unlike "maximal 1 500 mots", where the stray part
    (500) is a plausible word count on its own and a plausibility band alone
    could not have been trusted to catch it."""
    candidates, slots = _one("Votre lettre de motivation doit aborder en maximum 1 000 mots.",
                             "motivation_letter", "limit")
    assert value_state(candidates, slots)["sentences"][0]["figures"] == [
        {"figure": "1000", "unit_as_printed": "mots"},
    ]
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("words", 0.97),
    }))
    assert [(r.value, r.unit, r.applied) for r in rules] == [(1000, "words", True)]


def test_a_number_word_far_from_a_unit_is_never_asked_about():
    candidates, slots = _one("One of the documents is a motivation letter of 500 words.",
                             "motivation_letter", "limit")
    questions = value_questions(candidates, slots)
    assert "0:figure:0:bound" in questions and "0:figure:1:bound" not in questions
    assert value_state(candidates, slots)["sentences"][0]["figures"] == [
        {"figure": "500", "unit_as_printed": "words"},
    ]


# <!-- review focus 1 -->
def test_a_year_is_offered_and_not_a_limit_writes_nothing():
    """Code must not decide a year is not a length -- the sentence does. So the
    figure is asked about, and the grammar never writes it when the answer is
    not_a_limit."""
    candidates, slots = _one("Letters for the 2027 intake may not exceed 800 words.",
                             "motivation_letter", "limit")
    assert "0:figure:0:bound" in value_questions(candidates, slots)
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("not_a_limit", 0.96),
        "0:figure:1:bound": ("maximum", 0.95), "0:figure:1:unit": ("words", 0.97),
    }))
    assert [(r.value, r.unit, r.bound, r.figure) for r in rules] == [(800, "words", "maximum", 1)]


def test_a_figure_below_the_bar_is_one_note_beside_the_rules_that_cleared_it():
    candidates, slots = _one("At most 800 words, ideally around 600.",
                             "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("words", 0.97),
        "0:figure:1:bound": ("approximate", 0.55), "0:figure:1:unit": ("words", 0.90),
    }))
    assert [(r.value, r.note) for r in rules] == [(800, ""), (None, "unsure")]


def test_a_character_floor_is_kept_as_a_floor():
    """Kassel: a letter under 2,800 characters is rejected (addendum §6.2)."""
    candidates, slots = _one("Das Motivationsschreiben muss mindestens 2.800 Zeichen umfassen.",
                             "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("minimum", 0.94), "0:figure:0:unit": ("characters", 0.97),
    }))
    assert [(r.value, r.unit, r.bound, r.applied) for r in rules] == [
        (2800, "characters", "minimum", True),
    ]
    assert limit_sink("motivation_letter", "minimum", "characters") == "min_chars"


def test_a_cv_floor_has_no_sink_and_is_unapplied_with_its_sentence():
    candidates, slots = _one("The CV must be at least two pages long.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("minimum", 0.94), "0:figure:0:unit": ("pages", 0.97),
        "0:figure:0:spaces": (True, 0.9),
    }))
    assert [(r.value, r.bound, r.note) for r in rules] == [(2, "minimum", "unapplied")]
    assert rules[0].sentence == "The CV must be at least two pages long."


def test_a_cv_character_cap_that_leaves_out_spaces_says_so():
    candidates, slots = _one("The CV may not exceed 4,000 characters without spaces.",
                             "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("characters", 0.97),
        "0:figure:0:spaces": (False, 0.92),
    }))
    assert (rules[0].value, rules[0].excl_spaces, rules[0].detail) == (4000, True, "")
    assert limit_sink("cv", rules[0].bound, rules[0].unit,
                      excl_spaces=rules[0].excl_spaces) == "max_chars_excl_spaces"


def test_a_character_count_not_clearly_without_spaces_is_read_with_them():
    """Counting spaces is the stricter reading of a cap, so doubt lands there."""
    candidates, slots = _one("The CV may not exceed 4,000 characters.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("characters", 0.97),
        "0:figure:0:spaces": (False, 0.60),
    }))
    assert (rules[0].value, rules[0].excl_spaces) == (4000, False)


@pytest.mark.parametrize(
    ("text", "bound"),
    [
        ("Each part of the statement may have up to 400 words.", "section_limit"),
        ("In addition, submit a statement of 250 words on your research interests.",
         "another_statement"),
    ],
)
def test_what_no_sink_can_enforce_reaches_the_writer_as_a_topic(text, bound):
    """Addendum §6.5: recorded, not yet enforced. The sentence reaches the letter
    writer and the document carries it; its figure never becomes a length."""
    candidates, slots = _one(text, "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": (bound, 0.93), "0:figure:0:unit": ("words", 0.97),
    }))
    assert [(r.operation, r.value, r.bound, r.figure, r.applied) for r in rules] == [
        ("topic", text, bound, 0, True),
    ]
    assert sink_for("motivation_letter", "topic", text) == "written_requirements"


# <!-- review focus 5 -->
def test_a_limit_in_a_language_with_no_unit_words_still_reaches_a_rule_or_a_note():
    """Kazakh is not seeded in letter_terms, so the finder offers the figure with no
    unit printed beside it, and the unit Choice supplies one. A confident unit lands
    a cap; an unsure one keeps the sentence as an `unsure` note -- never silence."""
    text = "Мотивациялық хат 500 сөзден аспауы тиіс."
    candidates, slots = _one(text, "motivation_letter", "limit")
    sure = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.93), "0:figure:0:unit": ("words", 0.95),
    }))
    assert [(r.value, r.unit, r.bound, r.note) for r in sure] == [(500, "words", "maximum", "")]
    unsure = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.93), "0:figure:0:unit": ("words", 0.40),
    }))
    assert len(unsure) == 1 and unsure[0].note == "unsure"


def test_a_tolerance_lands_as_a_topic_and_never_as_a_limit():
    """'More than 10 percent' is no length of the document: the sentence is a
    topic by operation, no figure of it is asked a bound, and nothing reaches a
    cap or a floor."""
    text = "An exceedance of the word limit by more than 10 percent leads to exclusion."
    candidates, slots = _one(text, "motivation_letter", "topic")
    assert set(value_questions(candidates, slots)) == set()
    rules = read_values(candidates, slots, client=_script({}))
    assert [(r.operation, r.value, r.bound, r.applied) for r in rules] == [
        ("topic", text, "", True),
    ]


@pytest.mark.parametrize(
    ("operation", "value", "options"),
    [
        ("form", "formal_letter", ("essay", "formal_letter", "portal_form", "none")),
        ("naming", "forbidden", ("required", "invited", "forbidden", "none")),
    ],
)
def test_form_and_naming_are_a_choice_over_their_closed_values(operation, value, options):
    """Addendum §6.3: the frontier path types both, so the grammar asks both.
    `none` is the vendor's escape and has no sink, so it is `unapplied`."""
    candidates, slots = _one("Address the letter to the committee; do not name a professor.",
                             "motivation_letter", operation)
    assert value_questions(candidates, slots)[f"0:{operation}"].options == options
    rules = read_values(candidates, slots, client=_script({f"0:{operation}": (value, 0.94)}))
    assert [(r.operation, r.value, r.applied) for r in rules] == [(operation, value, True)]
    unset = read_values(candidates, slots, client=_script({f"0:{operation}": ("none", 0.94)}))
    assert unset[0].note == "unapplied"


def test_the_format_verdict_asks_three_phrasings_in_one_request():
    """Owner decision 2026-09-22, kept at the ordinary bar on 2026-09-23: three
    phrasings cost tokens in one request and no extra call, and their agreement
    is information because a Noul and a Choice on one question are not
    guaranteed to agree (spec §3.1 item 7)."""
    candidates = (Candidate(text="CV in the Europass CV template", heading="", europass=True),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.99, operation="format",
                     operation_confidence=0.97, third_party=False, conditional=False),)
    questions = value_questions(candidates, slots)
    assert {"0:format", "0:format_noul", "0:format_applicant"} <= set(questions)


def test_two_of_three_phrasings_agreeing_acts():
    candidates = (Candidate(text="CV in the Europass CV template", heading="", europass=True),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.99, operation="format",
                     operation_confidence=0.97, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:format": ("europass_required", 0.94),
        "0:format_noul": (True, 0.93),
        "0:format_applicant": ("europass_required", 0.60),
    }))
    assert rules[0].value == "europass_required"
    assert rules[0].applied is True


def test_three_phrasings_disagreeing_is_a_phrasing_note():
    candidates = (Candidate(text="We recommend the Europass model.", heading="", europass=True),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.99, operation="format",
                     operation_confidence=0.97, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:format": ("europass_required", 0.91),
        "0:format_noul": (False, 0.88),
        "0:format_applicant": ("europass_preferred", 0.90),
    }))
    assert rules[0].note == "phrasing"
    assert rules[0].applied is False


def test_a_third_party_sentence_is_never_applied_to_the_applicant():
    candidates, slots = _one("Short CV (max. 2 pages) from this academic supervisor.",
                             "cv", "limit", third_party=True)
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.97), "0:figure:0:unit": ("pages", 0.98),
        "0:figure:0:spaces": (True, 0.9),
    }))
    assert rules[0].note == "third_party"
    assert rules[0].applied is False


def test_a_conditional_sentence_asks_what_the_condition_is_about():
    candidates = (Candidate(text="Non-EU applicants must also submit a signed CV.",
                            heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.95, operation="style",
                     operation_confidence=0.9, third_party=False, conditional=True),)
    questions = value_questions(candidates, slots)
    assert "0:condition" in questions
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("signature_required", 0.93),
        "0:condition": ("nationality", 0.95),
    }))
    assert rules[0].condition == "nationality"
    # <!-- controller ruling C3: a conditional rule is never applied until the
    # student's own facts are compared (addendum §6.6) -->
    assert rules[0].applied is False


# <!-- fix round 1, finding 2 -->
def test_a_sentence_both_conditional_and_third_party_is_noted_third_party():
    """third_party is a PERMANENT exclusion (never the applicant's own
    document); conditional is provisional, re-evaluable once the student's
    facts are compared (addendum §6.6). When a sentence is both, the
    permanent exclusion must win, not the provisional one."""
    candidates, slots = _one(
        "Non-EU applicants: short CV (max. 2 pages) from this academic supervisor.",
        "cv", "limit", third_party=True, conditional=True,
    )
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.97), "0:figure:0:unit": ("pages", 0.98),
        "0:figure:0:spaces": (True, 0.9), "0:condition": ("nationality", 0.95),
    }))
    assert rules[0].note == "third_party"
    assert rules[0].condition == "nationality"
    assert rules[0].applied is False


def test_a_condition_we_cannot_evaluate_is_a_note_not_a_rule_for_everyone():
    candidates, slots = _one(
        "Applicants in exceptional circumstances may submit three pages.",
        "cv", "limit", conditional=True,
    )
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("pages", 0.95),
        "0:figure:0:spaces": (True, 0.9), "0:condition": ("other", 0.88),
    }))
    assert rules[0].note == "conditional"
    assert rules[0].applied is False


def test_an_operation_with_no_sink_is_unapplied_and_keeps_its_sentence():
    candidates = (Candidate(text="List your publications in APA style.", heading="",
                            europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.96, operation="other",
                     operation_confidence=0.91, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({}))
    assert rules[0].note == "unapplied"
    assert rules[0].sentence == "List your publications in APA style."


def test_a_slot_below_the_bar_is_an_unsure_note():
    candidates = (Candidate(text="Keep it professional.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.52, operation="style",
                     operation_confidence=0.41, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({}))
    assert rules[0].note == "unsure"
    assert rules[0].probabilities != ()


def test_a_sentence_about_no_document_yields_nothing_at_all():
    """`other` at the bar is not a note: the page said something about fees or
    deadlines and this reader has no business with it."""
    candidates = (Candidate(text="The application fee is 75 EUR.", heading="", europass=False),)
    slots = (Slotted(index=0, document="other", document_confidence=0.98, operation="other",
                     operation_confidence=0.97, third_party=False, conditional=False),)
    assert read_values(candidates, slots, client=_script({})) == ()


# <!-- controller ruling C1 -->
def test_a_long_page_is_packed_into_several_requests_each_mapped_back_correctly():
    """`read_values` packs by `grammar_questions.pack`, never by a fixed-size
    slice of the whole slot list, and each request's state carries only that
    request's own sentences -- never every candidate on the page. 250 forces a
    split on `CHUNK` (200) alone, before token packing even applies."""
    from apps.research.decisions import MAX_STATE_TOKENS, _estimate_tokens

    n = 250
    # Each cap starts at 100: _IMPLAUSIBLE_CAP["words"] is 50, and a smaller
    # number would be dropped as an implausible cap rather than read back.
    candidates = tuple(
        Candidate(text=f"The CV may not exceed {100 + i} words.", heading="", europass=False)
        for i in range(n)
    )
    slots = tuple(
        Slotted(index=i, document="cv", document_confidence=0.97, operation="limit",
               operation_confidence=0.95, third_party=False, conditional=False)
        for i in range(n)
    )
    request_sizes: list[int] = []

    def client(state, questions, *, decision, language="", budget=None, record=True,
               client=None):
        assert _estimate_tokens(state, questions) <= MAX_STATE_TOKENS
        request_sizes.append(len(state["sentences"]))
        answers = {}
        for qid in questions:
            if qid.endswith(":bound"):
                answers[qid] = Answer(id=qid, value="maximum", confidence=0.96,
                                      probabilities={"maximum": 0.96}, model="jev-1.13.0",
                                      provider="typesafe")
            elif qid.endswith(":unit"):
                answers[qid] = Answer(id=qid, value="words", confidence=0.97,
                                      probabilities={"words": 0.97}, model="jev-1.13.0",
                                      provider="typesafe")
        return answers

    rules = read_values(candidates, slots, client=client)
    assert len(request_sizes) > 1, "250 sentences must not fit in one request"
    # Every sentence's own request carried only itself -- once, across all requests.
    assert sum(request_sizes) == n
    assert len(rules) == n
    for i, rule in enumerate(rules):
        # The figure and sentence came from THIS slot, never a neighbour's --
        # the hazard a shared global index (instead of a per-request local one)
        # would silently create once a page needs more than one request.
        assert rule.value == 100 + i
        assert rule.sentence == candidates[i].text


# <!-- controller ruling C10 -->
def test_no_example_teaches_a_recommendation_as_europass_required():
    """The eval sheet's `europass` outcome conflates "must use Europass" with
    "we recommend the Europass template", so its rows are left out of the
    examples entirely (see grammar_values._EVAL_OUTCOME). This is the guard: a
    seed carrying a soft word must never end up under `europass_required`."""
    examples = " ".join(str(e) for e in FORMAT_EXAMPLES["europass_required"]["examples"]).lower()
    for soft in ("recommend", "suggest", "preferred", "empfehlen", "advisable"):
        assert soft not in examples


# <!-- fix round 1, finding 7 -->
def test_a_page_with_many_topic_sentences_and_one_limit_sends_one_small_request():
    """A `topic` sentence's value IS its sentence, verbatim -- no question is
    ever asked about it -- so it must never ride along in a packed request's
    state just because it shares a chunk with a sentence that IS asked
    something. Fifty such sentences beside one real limit sentence must still
    send exactly one small request, for the limit sentence alone."""
    limit_candidate = Candidate(text="Your CV may not exceed two pages.", heading="",
                                europass=False)
    topic_candidates = tuple(
        Candidate(text=f"Explain topic number {i}.", heading="", europass=False)
        for i in range(50)
    )
    candidates = (limit_candidate, *topic_candidates)
    slots = (
        Slotted(index=0, document="cv", document_confidence=0.97, operation="limit",
               operation_confidence=0.95, third_party=False, conditional=False),
        *(
            Slotted(index=i + 1, document="motivation_letter", document_confidence=0.95,
                   operation="topic", operation_confidence=0.93, third_party=False,
                   conditional=False)
            for i in range(50)
        ),
    )
    request_sizes: list[int] = []

    def client(state, questions, *, decision, language="", budget=None, record=True,
               client=None):
        request_sizes.append(len(state["sentences"]))
        answers = {}
        for qid in questions:
            if qid.endswith(":bound"):
                answers[qid] = Answer(id=qid, value="maximum", confidence=0.96,
                                      probabilities={"maximum": 0.96}, model="jev-1.13.0",
                                      provider="typesafe")
            elif qid.endswith(":unit"):
                answers[qid] = Answer(id=qid, value="pages", confidence=0.97,
                                      probabilities={"pages": 0.97}, model="jev-1.13.0",
                                      provider="typesafe")
        return answers

    rules = read_values(candidates, slots, client=client)
    assert request_sizes == [1]
    limit_rules = [r for r in rules if r.operation == "limit"]
    topic_rules = [r for r in rules if r.operation == "topic"]
    assert [(r.value, r.unit, r.bound) for r in limit_rules] == [(2, "pages", "maximum")]
    assert len(topic_rules) == 50


# <!-- fix round 1, finding 8 -->
def test_a_missing_eval_sheet_is_logged_not_silent(monkeypatch, caplog, tmp_path):
    """The old code silently produced empty examples when cv-format-eval.csv
    was missing. That must be loud, once, and name the path checked."""
    import logging

    from apps.documents import grammar_values

    monkeypatch.setattr(grammar_values, "_EVAL", tmp_path / "missing.csv")
    with caplog.at_level(logging.WARNING):
        examples = grammar_values._format_examples()
    assert examples["any"]["examples"] == []
    assert any("missing.csv" in record.getMessage() for record in caplog.records)


# <!-- task 8 fix round 1, finding 3: an order value is a (target, direction)
# pair, and sink_for must read it as one or every real order rule is unapplied. -->
def test_an_order_sentence_becomes_a_directive_end_to_end():
    from apps.documents.rule_sinks import to_directives

    candidates, slots = _one("List your education in reverse chronological order.", "cv", "order")
    rules = read_values(candidates, slots, client=_script({
        "0:order": ("education", 0.96), "0:order_direction": ("reverse_chronological", 0.95),
    }))
    assert rules[0].note == ""
    assert to_directives(rules, source_url="https://example.test/apply") == ({
        "action": "order", "target": "education", "value": "reverse_chronological",
        "rule_text": "List your education in reverse chronological order.",
        "source_url": "https://example.test/apply",
    },)


# Task 11, §11 gate 7: the grammar grew a `megabytes` unit and two style values,
# because catalogued rules a page states (R-048, R-060, R-082; R-010, R-017)
# reached a CV checker no slot could name.
def test_a_file_size_cap_is_a_megabytes_limit_and_a_kilobyte_misread_is_dropped():
    candidates, slots = _one("The CV must be a PDF under 2MB.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("megabytes", 0.96),
    }))
    assert [(r.value, r.unit, r.applied) for r in rules] == [(2, "megabytes", True)]
    assert limit_sink("cv", "maximum", "megabytes") == "max_bytes"
    # The letter has no size field: the same figure there is `unapplied`, shown.
    candidates, slots = _one("The letter must be a PDF under 2MB.", "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("megabytes", 0.96),
    }))
    assert [(r.value, r.note) for r in rules] == [(2, "unapplied")]
    # "300 KB" answered as megabytes is 300 MB: above the band, so no cap at all.
    candidates, slots = _one("Your CV file may not exceed 300 KB.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("megabytes", 0.9),
    }))
    assert [(r.operation, r.note) for r in rules] == [("limit", "unapplied")]


@pytest.mark.parametrize(
    ("value", "sink"),
    [("no_gaps", "no_unexplained_gaps"), ("no_hyperlinks", "prohibited_content")],
)
def test_a_gap_or_hyperlink_rule_is_a_cv_style_with_its_checkers_key(value, sink):
    candidates, slots = _one("Please ensure that your CV does not contain any gaps.",
                             "cv", "style")
    rules = read_values(candidates, slots, client=_script({"0:style": (value, 0.93)}))
    assert [(r.value, r.applied) for r in rules] == [(value, True)]
    assert sink_for("cv", "style", value) == sink
    # Neither has a letter sink: on a letter it is `unapplied`, never a field.
    assert sink_for("motivation_letter", "style", value) == ""


# 2026-10-08: the order direction was two bare labels and the slot's one example
# was "in reverse chronological order", so nothing taught what an OLDEST-first
# page says. Both options are defined in words, with English and German phrasings.
def test_the_order_direction_defines_oldest_first_and_newest_first():
    candidates, slots = _one(
        "List your education in chronological order, starting with the earliest.", "cv", "order"
    )
    direction = value_questions(candidates, slots)["0:order_direction"]

    oldest = str(direction.criteria["chronological"]).lower()
    newest = str(direction.criteria["reverse_chronological"]).lower()
    assert "oldest" in oldest and "starting with the earliest" in oldest
    assert "chronologischer reihenfolge" in oldest
    assert "most recent" in newest and "umgekehrt" in newest


# Live probe, 2026-10-08: with the direction defined, the blocker moved to the
# section. "List your education and work experience in chronological order"
# came back `education` at 0.51 and "Der Lebenslauf ... chronologisch" `cv`
# at 0.79-0.82 -- under the bar, so the rule never applied. `cv` is defined as
# the whole CV or several sections at once.
def test_the_order_section_defines_cv_as_the_whole_cv_or_several_sections():
    candidates, slots = _one(
        "List your education and work experience in chronological order.", "cv", "order"
    )
    section = value_questions(candidates, slots)["0:order"]

    whole = str(section.criteria["cv"]).lower()
    assert "whole cv" in whole and "more than one section" in whole
    assert "education and work experience" in whole
    assert "lebenslauf" in whole



# 2026-10-08, owner-approved with the student-dashboard session: a reference
# letter sentence is asked five closed questions -- how many letters, from whom,
# how they reach the programme, whether an institutional address is required,
# and when they are due -- and each confident answer becomes one `referee`
# rule. The sentence keeps its own operation and sink besides.
_REFERENCE = ("Two letters of recommendation from academic referees, uploaded by the "
              "referees through the portal by 15 January 2027.")


def test_a_reference_letter_sentence_is_asked_the_five_referee_questions():
    candidates, slots = _one(_REFERENCE, "reference_letter", "student_action")
    questions = value_questions(candidates, slots)

    assert questions["0:referee_count"].options == (
        "ONE", "TWO", "THREE_OR_MORE", "NONE_REQUIRED", "NOT_STATED")
    assert questions["0:referee_kind"].options == (
        "ACADEMIC", "PROFESSIONAL", "EITHER", "NOT_STATED")
    assert questions["0:referee_mode"].options == (
        "UPLOAD_GENERIC", "UPLOAD_ADDRESSED", "PORTAL_INVITE", "REFEREE_SENDS", "NOT_STATED")
    assert questions["0:referee_email"].options == ("YES", "NO", "NOT_STATED")
    assert questions["0:referee_due"].options == (
        "WITH_APPLICATION", "BEFORE_DEADLINE", "NOT_STATED")
    assert "15 January 2027" in questions["0:referee_due_date"].options
    assert "the student enters the referee" in str(
        questions["0:referee_mode"].criteria["PORTAL_INVITE"]).lower()


def test_a_cv_sentence_is_asked_no_referee_question():
    candidates, slots = _one("Your CV may not exceed two pages.", "cv", "limit")
    assert not [q for q in value_questions(candidates, slots) if "referee" in q]


def test_confident_referee_answers_become_referee_rules_even_on_a_third_party_slot():
    """A reference letter IS somebody else's document, so the slot is usually
    third_party -- that exclusion is about whose CV a rule binds, and must not
    swallow the facts about how the referee's letter arrives."""
    candidates, slots = _one(_REFERENCE, "reference_letter", "student_action", third_party=True)
    rules = read_values(candidates, slots, client=_script({
        "0:referee_count": ("TWO", 0.96), "0:referee_kind": ("ACADEMIC", 0.95),
        "0:referee_mode": ("PORTAL_INVITE", 0.93), "0:referee_email": ("NOT_STATED", 0.97),
        "0:referee_due": ("BEFORE_DEADLINE", 0.92),
        "0:referee_due_date": ("15 January 2027", 0.95),
    }))
    referee = sorted((r.value, r.detail, r.note) for r in rules if r.operation == "referee")

    assert referee == [
        (("count", "TWO"), "", ""),
        (("due", "BEFORE_DEADLINE"), "15 January 2027", ""),
        (("kind", "ACADEMIC"), "", ""),
        (("mode", "PORTAL_INVITE"), "", ""),
    ]


def test_an_unsure_or_unstated_referee_answer_writes_nothing():
    candidates, slots = _one(_REFERENCE, "reference_letter", "student_action")
    rules = read_values(candidates, slots, client=_script({
        "0:referee_count": ("TWO", 0.6), "0:referee_mode": ("NOT_STATED", 0.99),
    }))
    assert not [r for r in rules if r.operation == "referee"]


def test_a_conditional_referee_answer_is_kept_with_its_condition():
    """'Scholarship applicants also need ...': the route matters, so the rule
    is kept and marked rather than applied to everyone or dropped."""
    candidates, slots = _one(_REFERENCE, "reference_letter", "student_action", conditional=True)
    rules = read_values(candidates, slots, client=_script({
        "0:referee_count": ("ONE", 0.95), "0:condition": ("other", 0.9),
    }))
    (rule,) = [r for r in rules if r.operation == "referee"]
    assert (rule.value, rule.note, rule.condition) == (("count", "ONE"), "conditional", "other")


def test_referee_questions_need_only_the_document_not_the_operation():
    """Live 2026-10-08: four of six reference sentences were never asked, because
    the slot reader could not decide what OPERATION a reference sentence is
    (student_action, form, other) and a below-bar operation skipped every value
    question. Whether a sentence is about a reference letter is all the referee
    questions need."""
    candidates = (Candidate(text=_REFERENCE, heading="", europass=False),)
    slots = (Slotted(index=0, document="reference_letter", document_confidence=0.99,
                     operation="other", operation_confidence=0.6,
                     third_party=True, conditional=False),)

    assert "0:referee_count" in value_questions(candidates, slots)
    rules = read_values(candidates, slots, client=_script({"0:referee_count": ("TWO", 0.97)}))
    assert [(r.operation, r.value, r.note) for r in rules] == [
        ("other", None, "unsure"), ("referee", ("count", "TWO"), "")]


def test_the_due_question_knows_the_german_with_the_application():
    """Live 2026-10-08: "... sind mit der Bewerbung hochzuladen." came back with
    no due value -- the only WITH_APPLICATION example was English."""
    candidates, slots = _one(_REFERENCE, "reference_letter", "student_action")
    due = value_questions(candidates, slots)["0:referee_due"]
    assert "mit der bewerbung" in str(due.criteria["WITH_APPLICATION"]).lower()
