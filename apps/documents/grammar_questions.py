"""The grammar's questions, and nothing else.

Two requests per sentence set (spec §6.1): this module's `read_slots` asks who
and what, and `grammar_values.read_values` asks which value. Splitting them
keeps the 48 format examples on the few sentences that are format rules, and
keeps `state` plus questions inside `decisions.MAX_STATE_TOKENS` (32k).

Every question points at its sentence with an `inspect` path into the state
(`` `sentences[i]` ``), never a textual reference in the question's own
wording, and the state carries that sentence under its heading path -- their
own guidance, and the fix for the attribution errors a bare sentence produced.

**Controller ruling C1:** one sentence's own request already measures roughly
1,264 estimated tokens (measured 2026-09-26) -- five questions per sentence,
each carrying the shared `_DOCUMENT_CRITERIA` / `_OPERATION_CRITERIA` dicts in
full -- so a fixed 200-sentence chunk would ask for roughly 253k tokens against
a 32k ceiling and `decisions.ask` would refuse anything past about 25 sentences.
`pack` therefore groups sentences by estimated tokens (`TOKEN_TARGET`, a
headroom figure under `decisions.MAX_STATE_TOKENS`), never by a fixed count;
`CHUNK` remains only as the hard upper bound on sentences per request that
Task 6 also imports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from apps.research.decisions import (
    Answer,
    Choice,
    DecisionBudget,
    DecisionsUnavailable,
    Noul,
    Question,
    _estimate_tokens,
    ask,
)

from .grammar import DOCUMENTS, OPERATIONS, Slotted


# <!-- reconciled 2026-09-26: the grammar's seam has its own type. decisions.Client is the
# provider transport ask() calls with `model=` and `provider=`; this stands in for ask()
# itself and receives ask()'s own keywords. One alias for both let a double built for one
# pass the type check where the other is expected and fail at run time. A transport's
# required keyword-only parameters make it incompatible with this protocol, so mypy
# catches that mix-up. -->
class AskFn(Protocol):
    """Stands in for decisions.ask() in tests and measurement runs."""

    def __call__(
        self, state: object, questions: Mapping[str, Question], /, **kwargs: Any
    ) -> dict[str, Answer]: ...


# <!-- amended 2026-09-26: annotation-only import, stale item 1 -->
if TYPE_CHECKING:
    # Never at run time: derive.py imports this module (Task 10), so a
    # module-level `from .derive import Candidate` here is a circular import
    # that fails on whichever of the two loads first.
    from .derive import Candidate

#: The bar every slot must clear for a rule to be applied (spec §6.2). Below it
#: the rule is a note and the document is produced without it. §11's calibration
#: sets the shipped figure per question; this is the starting value the spec names.
SLOT_BAR = 0.85

#: Hard ceiling on sentences per request, independent of token packing. Task 6
#: imports this. `pack` below applies it in addition to `TOKEN_TARGET`, never
#: in place of it -- most pages hit the token target long before this count.
CHUNK = 200

#: Headroom under `decisions.MAX_STATE_TOKENS` (32_000) that a packed
#: request's estimate must stay under (controller ruling C1). Never raised to
#: equal MAX_STATE_TOKENS itself: `_estimate_tokens` is deliberately
#: conservative but not exact, and a request landing exactly at the ceiling
#: leaves no margin for that slack.
TOKEN_TARGET = 28_000

_DOCUMENT_CRITERIA = {
    "cv": {
        "what": "The applicant's own curriculum vitae, résumé or academic CV.",
        "examples": ["CV in the Europass CV template",
                     "Your CV may not exceed two pages.",
                     "A curriculum vitae in reverse chronological order."],
    },
    "motivation_letter": {
        "what": "The applicant's own motivation letter, statement of purpose, "
                "personal statement or cover letter.",
        "examples": ["The motivation letter must be at most 800 words.",
                     "Explain why you have chosen this programme."],
    },
    "reference_letter": {
        "what": "A letter written about the applicant by somebody else -- a "
                "referee, supervisor, employer or teacher.",
        "examples": ["Two letters of recommendation from academic referees.",
                     "Your referee must upload the reference directly."],
    },
    "other": {
        "what": "Any other document, or no document at all: transcripts, "
                "passports, language certificates, fees, deadlines.",
        "not_for": "Do not use this for a CV or a letter merely because the "
                   "sentence also mentions another document.",
    },
}

# <!-- reconciled 2026-09-26: `form` and `naming` (addendum §6.3); a tolerance is a
# topic, not a limit, so the limit/topic boundary says so in both directions -->
_OPERATION_CRITERIA = {
    "limit": {"what": "A maximum or minimum length: pages, words or characters, or "
                      "the file's size in megabytes.",
              "examples": ["no longer than two pages", "800 words maximum",
                           "Each part may have up to 400 words."],
              "not_for": "How far a stated length may be exceeded or undershot -- a "
                         "tolerance such as 'more than 10 percent over the limit'. "
                         "That is a topic."},
    "language": {"what": "Which language the document must be written in.",
                 "examples": ["The CV must be in English.", "in English or German"]},
    "format": {"what": "A required or recommended FORM or TEMPLATE for the whole "
                       "document -- Europass, the funder's own template, a tabular form.",
               "not_for": "A rule about one field, a length, or a style detail."},
    "include": {"what": "A specific piece of information the document must contain.",
                "examples": ["state your ECTS credits", "give your date of birth"]},
    "order": {"what": "The order entries must appear in, oldest first or newest first.",
              "examples": ["in reverse chronological order",
                           "in chronological order, starting with the earliest",
                           "in chronologischer Reihenfolge"]},
    "emphasise": {"what": "A section the document should foreground.",
                  "examples": ["highlight your research experience"]},
    "style": {"what": "A presentation rule: photo, signature, date, font, spacing, "
                      "margins, colour, columns, file bundling, no gaps in the "
                      "history, no hyperlinks.",
              "examples": ["A photograph is not required.", "minimum font size 11pt",
                           "Please ensure that your CV does not contain any "
                           "chronological gaps."]},
    "topic": {"what": "A subject the document must address -- a question the "
                      "programme asks, a theme it names -- or a condition on a length "
                      "that is not itself a length, such as a tolerance.",
              "examples": ["Explain your career plans after graduation.",
                           "An exceedance of the word limit by more than 10 percent "
                           "leads to exclusion."],
              "not_for": "A rule that sets the document's form, length or language."},
    "form": {"what": "What kind of text the letter is: an essay, a formal letter "
                     "addressed to someone, or answers typed into the portal's own fields.",
             "examples": ["Address your letter to the admissions committee.",
                          "Answer the questions in the online form."]},
    "naming": {"what": "Whether the letter must, may or must not name a prospective "
                       "supervisor or professor.",
               "examples": ["Please name a potential supervisor.",
                            "Do not contact or name individual professors."]},
    "student_action": {
        "what": "Something only the applicant can do: sign by hand, have it "
                "notarised or stamped, upload it under a particular filename, "
                "paste it into a portal field, have a referee send it directly.",
        "examples": ["The CV must be signed and dated by hand.",
                     "Upload as a single PDF named SURNAME_CV.pdf"],
    },
    "other": {"what": "A real requirement about this document that none of the "
                      "other answers describes."},
}


def slot_state(candidates: Sequence[Candidate]) -> dict[str, object]:
    """The sentences, each under its heading path.

    `heading` is context for the question and is never stored as a rule: only
    `text` can become a ProgramStatement or a rule_text (spec §5.1).
    """
    return {
        "sentences": [
            {"id": str(i), "heading": c.heading, "text": c.text}
            for i, c in enumerate(candidates)
        ]
    }


def slot_questions(candidates: Sequence[Candidate]) -> dict[str, Question]:
    """Five questions per sentence: which document, what operation, and three
    scopes (third_party, conditional, subset)."""
    questions: dict[str, Question] = {}
    for i in range(len(candidates)):
        # The vendor's `inspect` path, never "for the sentence with id 3" in
        # prose: indirection is a documented failure mode (research note of
        # 2026-09-23, rule 2), and the path names the part of the state exactly.
        where = f"`sentences[{i}]`"
        questions[f"{i}:document"] = Choice(
            question="Which document does this sentence state a requirement about?",
            options=DOCUMENTS, criteria=_DOCUMENT_CRITERIA, inspect=where,
            focus="Judge the sentence under its heading; the heading says which "
                  "document a list belongs to.",
        )
        questions[f"{i}:operation"] = Choice(
            question="What does this sentence require about that document?",
            options=OPERATIONS, criteria=_OPERATION_CRITERIA, inspect=where,
        )
        questions[f"{i}:third_party"] = Noul(
            question=(
                "Is the document this sentence describes somebody else's -- a "
                "referee's, supervisor's, host's or employer's -- rather than the "
                "applicant's own?"
            ),
            inspect=where,
            # Criteria because a real sentence showed the need (the vendor's
            # rule: add them only then). Measured 2026-09-12 on the Swiss
            # Government Excellence Scholarships' page.
            criteria={
                "true": {"what": "The CV or letter belongs to a referee, supervisor, "
                                 "host professor, employer or recommender.",
                         "examples": ["Short CV (max. 2 pages) from this academic "
                                      "supervisor.",
                                      "Your referee must upload the reference directly."]},
                "false": {"what": "The document is the applicant's own.",
                          "examples": ["Your CV may not exceed two pages."]},
            },
        )
        # Two Nouls, not one with an `or`: the vendor's first rule is one
        # condition per question, and code ORs them.
        questions[f"{i}:conditional"] = Noul(
            question="Does this sentence state a condition that must hold for the "
                     "requirement to apply?",
            inspect=where,
            # Criteria because a real reading showed the need (2026-10-08): with
            # none, "starting with the earliest" read as a condition, so every
            # oldest-first order sentence waited on the student's facts instead
            # of applying. An ordering or starting point is part of the rule.
            criteria={
                "true": {"what": "The requirement applies only if something about the "
                                 "applicant or the application is true.",
                         "examples": ["If you have work experience, list it first.",
                                      "Applicants with a foreign degree must add a "
                                      "Europass CV."]},
                "false": {"what": "The requirement applies to every CV or letter; an "
                                  "order, a starting point or a format is part of the "
                                  "rule, not a condition.",
                          "examples": ["List your education starting with the earliest.",
                                       "Der Lebenslauf ist chronologisch, beginnend mit "
                                       "dem Schulabschluss.",
                                       "Your CV may not exceed two pages."]},
            },
        )
        questions[f"{i}:subset"] = Noul(
            question="Does this requirement apply only to some applicants rather than "
                     "to every applicant?",
            inspect=where,
            # Criteria for the same reason as `conditional` (2026-10-08): with
            # none, a plain "no" came back at 0.54-0.84, under SLOT_BAR, and
            # _scope's fail-safe made every sentence on a page conditional.
            criteria={
                "true": {"what": "The sentence names a group of applicants it applies "
                                 "to, and only to them.",
                         "examples": ["International applicants only: add a Europass CV.",
                                      "Applicants to the research track must list "
                                      "their publications."]},
                "false": {"what": "The sentence addresses every applicant, or names no "
                                  "group at all. Naming a section of the CV (your work "
                                  "experience, your publications) is not naming a group of "
                                  "applicants.",
                          "examples": ["Your CV may not exceed two pages.",
                                       "List your education starting with the earliest.",
                                       "List your publications, newest first."]},
            },
        )
    return questions


def pack[T](
    items: Sequence[T],
    build: Callable[[Sequence[T]], tuple[object, Mapping[str, Question]]],
) -> list[list[T]]:
    """Group items into chunks whose (state, questions) request stays at or
    under `TOKEN_TARGET`, and never more than `CHUNK` items regardless of
    tokens (controller ruling C1). `build` renders a candidate sub-list into
    the exact (state, questions) pair a real request would send, so the
    estimate this uses matches what `decisions.ask` will actually see.

    An item whose own request already exceeds the target is packed alone --
    `ask()` then refuses it loudly (`ValueError`, over `MAX_STATE_TOKENS`)
    rather than this function truncating it away. Generic over `T` and over
    `build` so Task 6 and Task 9 reuse it for their own requests over the
    same sentences.
    """
    # ponytail: re-estimates the whole growing chunk on every append, so this
    # is O(n^2) in chunk size. Fine at catalogue page sizes (hundreds of
    # sentences per page); switch to an incremental estimate if a caller ever
    # packs thousands of items in one call.
    chunks: list[list[T]] = []
    current: list[T] = []
    for item in items:
        grown = [*current, item]
        if current and (
            len(grown) > CHUNK or _estimate_tokens(*build(grown)) > TOKEN_TARGET
        ):
            chunks.append(current)
            current = [item]
        else:
            current = grown
    if current:
        chunks.append(current)
    return chunks


# <!-- fix round 1, finding 1: controller ruling, fail safe -->
def _scope(answer: Answer) -> bool:
    """A scope Noul (third_party, conditional, subset) reads as True whenever
    its own value is True, OR its confidence never cleared SLOT_BAR. A `False`
    at 0.55 is barely a coin flip, and `bool(answer.value)` alone would read
    it as a confident 'no' -- attributing a third party's document to the
    applicant, or applying a rule that was actually conditional, silently. An
    over-applied rule survives as a dismissible note; a wrongly-attributed or
    wrongly-unconditional one does not, so uncertainty here fails toward the
    safer reading."""
    return bool(answer.value) or answer.confidence < SLOT_BAR


def read_slots(
    candidates: Sequence[Candidate],
    *,
    language: str = "",
    budget: DecisionBudget | None = None,
    client: AskFn | None = None,
    record: bool = True,
) -> tuple[Slotted, ...]:
    """Who and what, for every sentence. Chunked by estimated tokens, never
    truncated (controller ruling C1)."""
    slotted: list[Slotted] = []
    offset = 0
    for chunk in pack(candidates, lambda sub: (slot_state(sub), slot_questions(sub))):
        answers: dict[str, Answer] = _ask(
            slot_state(chunk), slot_questions(chunk), decision="D6.slots",
            language=language, budget=budget, record=record, client=client,
        )
        for i in range(len(chunk)):
            document = answers[f"{i}:document"]
            operation = answers[f"{i}:operation"]
            slotted.append(Slotted(
                index=offset + i,
                document=str(document.value),  # type: ignore[arg-type]
                document_confidence=document.confidence,
                operation=str(operation.value),  # type: ignore[arg-type]
                operation_confidence=operation.confidence,
                third_party=_scope(answers[f"{i}:third_party"]),
                conditional=(
                    _scope(answers[f"{i}:conditional"])
                    or _scope(answers[f"{i}:subset"])
                ),
            ))
        offset += len(chunk)
    return tuple(slotted)


# <!-- amended 2026-09-26: typed for mypy --strict, stale item 2 -->
def _ask(
    state: object,
    questions: Mapping[str, Question],
    *,
    client: AskFn | None = None,
    **kwargs: Any,
) -> dict[str, Answer]:
    """One seam so both request modules inject the same test double."""
    if client is not None:
        return client(state, questions, **kwargs)
    return ask(state, questions, **kwargs)


@dataclass(frozen=True)
class PageFacts:
    """What one page states about the letter as a whole, not in one sentence.

    The frontier path typed these three per line (LetterVerdict.document_required,
    .track, .portfolio_required); addendum §6.3 forbids losing them. They are
    properties of the page -- a letter is required by a documents list, not by a
    sentence about the letter's length -- so they are asked once, over the page.
    """

    letter_required: str = "UNSTATED"  # REQUIRED | NOT_REQUIRED | UNSTATED
    track: str = ""  # research | taught | ""
    portfolio_led: bool = False


_PAGE_WHERE = "`sentences`"


def page_questions() -> dict[str, Question]:
    """Three questions over the whole page, each with an escape.

    Wording is a first draft for spec §11 gate 12's ablation, like every other
    question in this module.
    """
    return {
        "letter_required": Choice(
            question="Does this page require the applicant to submit a motivation "
                     "letter, statement of purpose, personal statement or cover letter?",
            options=("required", "not_required", "unstated"),
            inspect=_PAGE_WHERE,
            criteria={
                "required": {
                    "what": "The page lists the letter among the documents the applicant "
                            "must submit, or says it must be submitted.",
                    "examples": ["Motivation letter (max. 2 pages)",
                                 "Please upload your statement of purpose."],
                },
                "not_required": {
                    "what": "The page says the letter is not required, optional or not "
                            "accepted.",
                    "examples": ["A motivation letter is not required.",
                                 "No cover letter is needed."],
                },
                "unstated": {"what": "The page does not say whether a letter is required."},
            },
        ),
        "track": Choice(
            question="Is this programme research-based -- a thesis or project under a "
                     "supervisor the applicant identifies -- or taught?",
            options=("research", "taught", "unstated"),
            inspect=_PAGE_WHERE,
            criteria={
                "research": {"what": "Admission depends on a research proposal or on "
                                     "naming a supervisor.",
                             "examples": ["Identify a potential supervisor in your "
                                          "statement of intent."]},
                "taught": {"what": "A coursework programme; nothing asks for a "
                                   "supervisor or a research proposal."},
                "unstated": {"what": "The page does not say."},
            },
        ),
        "portfolio": Noul(
            question="Does the page require the applicant to submit a portfolio of their "
                     "own creative or professional work?",
            inspect=_PAGE_WHERE,
        ),
    }


def read_page_facts(
    candidates: Sequence[Candidate],
    slots: Sequence[Slotted],
    *,
    language: str = "",
    budget: DecisionBudget | None = None,
    client: AskFn | None = None,
    record: bool = True,
) -> PageFacts:
    """The page's letter-level facts, or none when the page has no letter of the applicant's.

    Asked only when some sentence is the applicant's own letter at the bar --
    the only lines the frontier path typed these from -- so a CV-only page costs
    no request. The questions are about the whole page, so the state is the
    whole candidate listing, packed by estimated tokens like every other request
    here (controller ruling C1): one request on an ordinary page, several on a
    long one, whose answers `_page_facts` combines.
    """
    if not any(
        s.document == "motivation_letter" and not s.third_party
        and s.document_confidence >= SLOT_BAR
        for s in slots
    ):
        return PageFacts()
    questions = page_questions()
    return _page_facts([
        _ask(
            slot_state(chunk), questions, decision="D6.page",
            language=language, budget=budget, record=record, client=client,
        )
        for chunk in pack(candidates, lambda sub: (slot_state(sub), questions))
    ])


#: The three ids `page_questions()` always returns. Named here, rather than
#: re-derived from `page_questions()` on every call, only because `_page_facts`
#: must check for them before it can trust `a[qid]` -- see the docstring below.
_PAGE_QUESTION_IDS = ("letter_required", "track", "portfolio")


def _page_facts(chunks: Sequence[Mapping[str, Answer]]) -> PageFacts:
    """One page's facts from one request per chunk, each answer only at the bar.

    A chunk that cannot see the documents list answers `unstated`, which is
    silence, not a vote. Among the votes the frontier path's own safer sides
    hold: one REQUIRED wins (derive._document_required_decision -- a letter
    left out is a rejection), research beats taught, and a portfolio stated
    anywhere is stated.

    Fix round 1, finding 5: a chunk missing one of the three answers (an
    `AskFn` that skips a question, never `decisions.ask` itself, which already
    raises for this) is a provider failure, exactly as `decisions.ask` treats a
    skipped answer -- never a bare KeyError with no `kind` for the caller to
    act on.
    """
    for chunk in chunks:
        missing = [qid for qid in _PAGE_QUESTION_IDS if qid not in chunk]
        if missing:
            raise DecisionsUnavailable(f"the page questions were not answered: {missing}")

    def at_bar(qid: str, values: tuple[object, ...]) -> set[str]:
        return {
            str(a[qid].value) for a in chunks
            if a[qid].confidence >= SLOT_BAR and a[qid].value in values
        }

    required = at_bar("letter_required", ("required", "not_required"))
    track = at_bar("track", ("research", "taught"))
    return PageFacts(
        letter_required=(
            "REQUIRED" if "required" in required
            else "NOT_REQUIRED" if required else "UNSTATED"
        ),
        track="research" if "research" in track else "taught" if track else "",
        portfolio_led=bool(at_bar("portfolio", (True,))),
    )
