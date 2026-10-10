import pytest

from apps.documents.derive import Candidate
from apps.documents.grammar import Slotted
from apps.documents.grammar_questions import PageFacts, page_questions, read_page_facts
from apps.research.decisions import Answer

pytestmark = pytest.mark.django_db

_FOUND = (
    Candidate(text="Your CV may not exceed two pages.", heading="Documents", europass=False),
    Candidate(text="A motivation letter of one page.", heading="Documents", europass=False,
              letter=True),
)


def _slot(index, document, confidence=0.97, third_party=False):
    return Slotted(index=index, document=document, document_confidence=confidence,
                   operation="limit", operation_confidence=0.97,
                   third_party=third_party, conditional=False)


def _client(script, asked):
    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        asked.append(decision)
        return {
            qid: Answer(id=qid, value=script[qid][0], confidence=script[qid][1],
                        probabilities={str(script[qid][0]).lower(): script[qid][1]},
                        model="jev-1.13.0", provider="typesafe")
            for qid in questions
        }

    return call


def test_the_page_questions_have_an_escape_on_every_choice():
    questions = page_questions()
    assert set(questions) == {"letter_required", "track", "portfolio"}
    assert "unstated" in questions["letter_required"].options
    assert "unstated" in questions["track"].options


def test_a_page_with_no_applicant_letter_sentence_asks_nothing():
    """The frontier path typed these only from the applicant's own letter lines,
    so the grammar asks only then -- and a CV-only page costs no request."""
    asked: list[str] = []
    facts = read_page_facts(
        _FOUND, (_slot(0, "cv"), _slot(1, "motivation_letter", third_party=True)),
        client=_client({}, asked),
    )
    assert facts == PageFacts() and asked == []


def test_answers_at_the_bar_are_the_pages_facts():
    asked: list[str] = []
    facts = read_page_facts(
        _FOUND, (_slot(0, "cv"), _slot(1, "motivation_letter")),
        client=_client({
            "letter_required": ("required", 0.93), "track": ("research", 0.9),
            "portfolio": (True, 0.88),
        }, asked),
    )
    assert facts == PageFacts(letter_required="REQUIRED", track="research", portfolio_led=True)
    assert asked == ["D6.page"]


def test_answers_below_the_bar_are_unstated():
    asked: list[str] = []
    facts = read_page_facts(
        _FOUND, (_slot(1, "motivation_letter"),),
        client=_client({
            "letter_required": ("not_required", 0.6), "track": ("taught", 0.5),
            "portfolio": (True, 0.7),
        }, asked),
    )
    assert facts == PageFacts()


def test_a_long_page_is_asked_in_requests_under_the_ceiling_and_every_sentence_is_seen():
    """C1: the page questions ride on the whole candidate listing, and a
    listing of long sentences is packed by tokens, never sent over the ceiling.
    Every sentence reaches some request, and a letter required in one chunk
    is required for the page: the other chunks' `unstated` is silence, not
    disagreement."""
    from apps.research.decisions import MAX_STATE_TOKENS, _estimate_tokens

    filler = "This paragraph describes the campus, its libraries and its history. " * 30
    found = tuple(
        Candidate(text=f"{i}: {filler}", heading="About", europass=False) for i in range(99)
    ) + (Candidate(text="A motivation letter is required.", heading="Documents",
                   europass=False, letter=True),)
    estimates: list[int] = []
    seen: set[str] = set()

    def call(state, questions, *, decision, **kwargs):
        estimates.append(_estimate_tokens(state, questions))
        texts = {s["text"] for s in state["sentences"]}
        seen.update(texts)
        required = "A motivation letter is required." in texts
        return {
            "letter_required": Answer(
                id="letter_required", value="required" if required else "unstated",
                confidence=0.95, probabilities={}, model="m", provider="p"),
            "track": Answer(id="track", value="unstated", confidence=0.95,
                            probabilities={}, model="m", provider="p"),
            "portfolio": Answer(id="portfolio", value=False, confidence=0.95,
                                probabilities={}, model="m", provider="p"),
        }

    facts = read_page_facts(found, (_slot(99, "motivation_letter"),), client=call)
    assert len(estimates) > 1
    assert max(estimates) <= MAX_STATE_TOKENS
    assert seen == {c.text for c in found}
    assert facts.letter_required == "REQUIRED"


def test_a_page_whose_chunks_disagree_about_the_letter_is_required():
    """The frontier path's own rule (_document_required_decision): one REQUIRED
    wins -- a letter left out of an application is a rejection."""
    from apps.documents.grammar_questions import _page_facts

    def answers(required, track="unstated", portfolio=False):
        return {
            "letter_required": Answer(id="a", value=required, confidence=0.95,
                                      probabilities={}, model="m", provider="p"),
            "track": Answer(id="b", value=track, confidence=0.95,
                            probabilities={}, model="m", provider="p"),
            "portfolio": Answer(id="c", value=portfolio, confidence=0.95,
                                probabilities={}, model="m", provider="p"),
        }

    assert _page_facts([answers("not_required"), answers("required", "research")]) == PageFacts(
        letter_required="REQUIRED", track="research"
    )
    assert _page_facts([answers("not_required"), answers("unstated", "taught")]) == PageFacts(
        letter_required="NOT_REQUIRED", track="taught"
    )
    assert _page_facts([answers("unstated", "taught"), answers("unstated", "research", True)]) \
        == PageFacts(track="research", portfolio_led=True)


def test_a_chunk_missing_an_answer_raises_a_typed_provider_failure():
    """Fix round 1, finding 5: a skipped answer is a provider failure -- as
    `decisions.ask` already treats one -- never a bare KeyError with no `kind`
    for the caller to act on."""
    from apps.documents.grammar_questions import _page_facts
    from apps.research.decisions import DecisionsUnavailable

    chunk = {
        "letter_required": Answer(id="a", value="required", confidence=0.95,
                                  probabilities={}, model="m", provider="p"),
        "portfolio": Answer(id="c", value=False, confidence=0.95,
                            probabilities={}, model="m", provider="p"),
    }
    with pytest.raises(DecisionsUnavailable) as excinfo:
        _page_facts([chunk])
    assert excinfo.value.kind == "failed"
    assert "track" in str(excinfo.value)
