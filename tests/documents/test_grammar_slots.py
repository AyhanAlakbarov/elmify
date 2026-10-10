import pytest

from apps.documents.derive import Candidate
from apps.documents.grammar_questions import SLOT_BAR, read_slots, slot_questions
from apps.research.decisions import Answer

pytestmark = pytest.mark.django_db


def _candidates():
    return (
        Candidate(text="Your CV may not exceed two pages.", heading="Application documents",
                  europass=False),
        Candidate(text="Short CV (max. 2 pages) from this academic supervisor.",
                  heading="References", europass=False),
        Candidate(text="The motivation letter must be at most 800 words.",
                  heading="Application documents > Motivation letter", europass=False),
    )


def _answers(script):
    """script: {question_id: (value, confidence)}; anything unscripted answers
    'no' or the neutral option, so a test names only the questions it is about."""

    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        answers = {}
        for qid, question in questions.items():
            if qid in script:
                value, confidence = script[qid]
            else:
                options = getattr(question, "options", None)
                value, confidence = (False if options is None else options[-1]), 0.99
            answers[qid] = Answer(id=qid, value=value, confidence=confidence,
                                  probabilities={str(value): confidence},
                                  model="jev-1.13.0", provider="typesafe")
        return answers

    return call


def test_one_question_per_sentence_per_slot():
    questions = slot_questions(_candidates())
    assert set(questions) == {
        f"{i}:{slot}"
        for i in range(3)
        for slot in ("document", "operation", "third_party", "conditional", "subset")
    }


def test_every_question_points_at_its_sentence_with_inspect():
    """Jev's own guidance: a question points at a named part of a structured
    state with a backtick path; "the sentence with id 2" in prose is the
    indirection their jaggedness page warns against (§3.1a)."""
    questions = slot_questions(_candidates())
    assert questions["0:document"].inspect == "`sentences[0]`"
    assert questions["2:operation"].inspect == "`sentences[2]`"
    assert "id" not in questions["2:operation"].question


def test_the_operation_choice_offers_form_and_naming_and_describes_every_option():
    """Task 9 projects `form` and `naming`; an operation the first request never
    offers is one no page can ever state. A tolerance is described as a topic,
    so its figures are never asked a bound."""
    question = slot_questions(_candidates())["0:operation"]
    assert {"form", "naming"} <= set(question.options)
    assert set(question.criteria) == set(question.options)
    assert "tolerance" in question.criteria["topic"]["what"]


def test_a_condition_and_a_subset_are_two_questions_ored_in_code():
    """One condition per Noul (the vendor's first rule). 'Non-EU applicants
    must…' is a subset; 'if you have work experience…' is a condition; either
    alone makes the rule conditional."""
    slots = read_slots(_candidates()[:1], client=_answers({
        "0:document": ("cv", 0.98), "0:operation": ("style", 0.95),
        "0:subset": (True, 0.9),
    }))
    assert slots[0].conditional is True


def test_the_state_carries_each_sentence_under_its_heading():
    """A bare sentence is where wrong attributions came from: 'no longer than
    two pages' means nothing once its heading is gone (spec §5.1)."""
    from apps.documents.grammar_questions import slot_state

    state = slot_state(_candidates())
    assert state["sentences"][2]["heading"] == "Application documents > Motivation letter"
    assert state["sentences"][2]["text"] == "The motivation letter must be at most 800 words."


def test_a_cv_page_limit_fills_both_slots():
    slots = read_slots(_candidates()[:1], client=_answers({
        "0:document": ("cv", 0.98), "0:operation": ("limit", 0.95),
        "0:third_party": (False, 0.97), "0:conditional": (False, 0.99),
    }))
    assert (slots[0].document, slots[0].operation) == ("cv", "limit")
    assert slots[0].third_party is False


def test_a_supervisors_cv_is_marked_third_party():
    """Measured 2026-09-12 on the Swiss Government Excellence Scholarships' real
    page: the engine derived max_pages=2 for the STUDENT from a sentence about
    the host professor's CV. The fabrication check could not catch it -- '2'
    really is in the sentence. Only attribution was wrong."""
    slots = read_slots(_candidates()[1:2], client=_answers({
        "0:document": ("cv", 0.93), "0:operation": ("limit", 0.91),
        "0:third_party": (True, 0.88), "0:conditional": (False, 0.95),
    }))
    assert slots[0].third_party is True


# <!-- fix round 1, finding 4: pack() has no direct test -->
def test_pack_with_empty_input_returns_no_chunks():
    from apps.documents.grammar_questions import pack

    assert pack([], lambda items: ({"n": list(items)}, {})) == []


def test_pack_splits_on_the_chunk_ceiling_packs_an_oversized_item_alone_and_keeps_order():
    """A toy `build` renders items as one JSON string apiece, so the token
    estimate is controlled directly: tiny items alone drive the CHUNK-count
    ceiling, and one deliberately huge item drives TOKEN_TARGET -- it must
    ride alone rather than being silently merged, dropped or truncated."""
    from apps.documents.grammar_questions import CHUNK, pack

    def build(items):
        return ({"n": list(items)}, {})

    # CHUNK ceiling: plenty of tiny items never approach TOKEN_TARGET, so
    # only the CHUNK-count limit can be what splits them.
    tiny = [f"item-{i}" for i in range(CHUNK + 5)]
    chunks = pack(tiny, build)
    assert [len(c) for c in chunks] == [CHUNK, 5]
    # Order kept, nothing dropped or duplicated.
    assert [x for c in chunks for x in c] == tiny

    # An oversized item -- its own request already exceeds TOKEN_TARGET --
    # is packed alone rather than merged with its neighbour or truncated.
    oversized = "x" * 150_000
    items = [oversized, "small-1", "small-2"]
    chunks = pack(items, build)
    assert chunks[0] == [oversized]
    assert [x for c in chunks for x in c] == items


# <!-- fix round 1, finding 1: controller ruling, fail safe -->
def test_a_low_confidence_scope_answer_reads_as_true():
    """`bool(answers[...].value)` alone discards confidence, so a False answer
    at 0.55 -- barely above a coin flip -- would read as a confident 'this is
    the applicant's own document' / 'this rule is unconditional'. Below
    SLOT_BAR, third_party and conditional must fail safe to True: an
    over-applied rule is a note a human can dismiss, but a wrongly-attributed
    or wrongly-unconditional rule ships silently."""
    slots = read_slots(_candidates()[:1], client=_answers({
        "0:document": ("cv", 0.98), "0:operation": ("limit", 0.95),
        "0:third_party": (False, 0.55), "0:conditional": (False, 0.55),
    }))
    assert slots[0].third_party is True
    assert slots[0].conditional is True


def test_a_sentence_below_the_bar_keeps_its_confidence_for_the_note():
    slots = read_slots(_candidates()[:1], client=_answers({
        "0:document": ("cv", 0.51), "0:operation": ("limit", 0.42),
        "0:third_party": (False, 0.9), "0:conditional": (False, 0.9),
    }))
    assert slots[0].operation_confidence == pytest.approx(0.42)
    assert slots[0].operation_confidence < SLOT_BAR


# <!-- controller ruling C1: the brief's "chunk at 200, assert max(seen) <= 200"
# is replaced. One sentence's own request already measures ~1,283 estimated
# tokens (five questions per sentence, each carrying the shared criteria
# dicts), so 200 sentences would be ~256k tokens against decisions.
# MAX_STATE_TOKENS = 32_000. The packer bounds every request by estimated
# tokens (TOKEN_TARGET), not a fixed sentence count; CHUNK stays as the hard
# upper bound Task 6 imports. -->
def test_a_long_page_is_chunked_by_tokens_rather_than_truncated():
    """§3.1 item 4: irrelevant state costs accuracy, and MAX_STATE_TOKENS is
    hard. A page whose requests would exceed it must be asked in parts --
    never cut, which is how a page that partly read looked like a page that
    said nothing."""
    from apps.research.decisions import MAX_STATE_TOKENS, _estimate_tokens

    many = tuple(
        Candidate(text=f"Rule number {i} about the CV.", heading="Documents", europass=False)
        for i in range(50)
    )
    seen = []

    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        sentences = state["sentences"]
        seen.append(sentences)
        assert _estimate_tokens(state, questions) <= MAX_STATE_TOKENS
        answers = {}
        for local, sentence in enumerate(sentences):
            # Derive every answer from the sentence's OWN text at its LOCAL
            # position -- never a constant -- so a chunk that silently
            # reordered or misnumbered a sentence answers wrongly for it.
            number = int(sentence["text"].split()[2])
            odd = number % 2 == 1
            answers[f"{local}:document"] = Answer(
                id=f"{local}:document", value="cv", confidence=0.9,
                probabilities={}, model="m", provider="p")
            answers[f"{local}:operation"] = Answer(
                id=f"{local}:operation", value="limit", confidence=0.9,
                probabilities={}, model="m", provider="p")
            answers[f"{local}:third_party"] = Answer(
                id=f"{local}:third_party", value=odd, confidence=0.95,
                probabilities={}, model="m", provider="p")
            answers[f"{local}:conditional"] = Answer(
                id=f"{local}:conditional", value=False, confidence=0.95,
                probabilities={}, model="m", provider="p")
            answers[f"{local}:subset"] = Answer(
                id=f"{local}:subset", value=False, confidence=0.95,
                probabilities={}, model="m", provider="p")
        return answers

    slots = read_slots(many, client=call)
    assert len(slots) == 50
    # Enough candidates to force more than one request, and every request that
    # was actually made cleared the assertion inside `call` above.
    assert len(seen) > 1
    # Never truncated: every sentence sent across every request round-trips
    # (each request's own state re-numbers its sentences from 0, so the
    # count -- not the id values -- is what proves nothing was dropped).
    assert sum(len(chunk) for chunk in seen) == 50
    # <!-- fix round 1, finding 2: the chunk-to-page id mapping -->
    # Every slot lands at the global page index it belongs to, in order,
    # with none dropped or duplicated across chunk boundaries.
    assert [s.index for s in slots] == list(range(50))
    # Each slot's third_party traces back to ITS OWN sentence's number, not a
    # neighbour's -- the case a chunk boundary or a local-index mix-up would
    # silently get wrong.
    for slot in slots:
        assert slot.third_party == (slot.index % 2 == 1)


# 2026-10-08: the conditional question had no definitions, so an ordering
# instruction ("starting with the earliest", "beginnend mit dem Schulabschluss")
# read as a condition -- live, all three order sentences of the oldest-first
# probe came back conditional, and a conditional rule waits on the student's
# facts instead of applying. Both answers are defined, ordering on the false side.
def test_the_conditional_question_says_an_ordering_instruction_is_not_a_condition():
    candidates = (Candidate(text="List your education starting with the earliest.",
                            heading="", europass=False),)
    conditional = slot_questions(candidates)["0:conditional"]

    true = str(conditional.criteria["true"]).lower()
    false = str(conditional.criteria["false"]).lower()
    assert "if you" in true
    assert "starting with the earliest" in false
    assert "beginnend mit" in false


# Same day, same probe: with `conditional` defined, the flag still fired from
# `subset`, whose plain "no" came back at 0.54-0.84 -- under SLOT_BAR, so the
# fail-safe read it as "yes" on every sentence, "Your CV may not exceed two
# pages." included. Defining both answers is what lets a "no" clear the bar.
def test_the_subset_question_defines_every_applicant_and_some_applicants():
    candidates = (Candidate(text="Your CV may not exceed two pages.",
                            heading="", europass=False),)
    subset = slot_questions(candidates)["0:subset"]

    assert "every applicant" in str(subset.criteria["false"]).lower()
    assert "your cv may not exceed two pages" in str(subset.criteria["false"]).lower()
    assert "only" in str(subset.criteria["true"]).lower()


# Live 2026-10-08: "Please list your work experience with the most recent
# position first." read subset=no at only 0.63 -- "your work experience" can
# sound like "applicants who have some". Naming a CV SECTION is not naming a
# GROUP of applicants, and the definition says so.
def test_the_subset_question_says_a_cv_section_is_not_a_group_of_applicants():
    candidates = (Candidate(text="List your work experience, most recent first.",
                            heading="", europass=False),)
    subset = slot_questions(candidates)["0:subset"]

    false = str(subset.criteria["false"]).lower()
    assert "section of the cv" in false
    assert "list your publications, newest first" in false
