"""The grammar's second request: which value, for the operation the first found.

Only the operations a page actually states get value questions, which is why
this is a second request rather than one huge one -- the 48 format examples ride
on the few sentences that are format rules, and `state` plus questions stays
inside `decisions.MAX_STATE_TOKENS` (32k, controller ruling C1).

**A number is found by code, never chosen by a model** (addendum 2026-09-26
§6.1). `letter_terms.figures_on_line` finds every figure a sentence prints with
the unit word beside it, and one Choice per figure says what the figure IS -- a
cap, a floor, an approximation, or not a limit at all. The number a rule carries
is always that figure. A range is a floor and a cap, two units are two caps, and
nothing here combines figures: which of two caps wins is `resolve_conflicts`'
question, on the safer side. A figure whose bound is a NOTE_BOUNDS member
(a section's length, another statement's) is a topic carrying the sentence.

**Packing (controller ruling C1).** `read_values` groups SLOTS, not the whole
page's candidates, through `grammar_questions.pack`, and `value_state` /
`value_questions` build every id from the LOCAL position within that group
(`enumerate(slots)`), never from `slot.index`. So a request's state carries
only the sentences its own questions are about -- a page with hundreds of
sentences never ships the other chunks' text in a request that has nothing to
ask about them. `slot.index` still selects the right candidate to read
(`candidates[slot.index]`) and still names the sentence a produced `Rule`
belongs to; only the question/answer *keys* are local to the request.
"""

from __future__ import annotations

import csv
import logging
import pathlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.research.decisions import Answer, Choice, DecisionBudget, Noul, Question

from .constraints import _INCLUDE_TARGETS, _ORDER_TARGETS, _SECTIONS
from .grammar import (
    _IMPLAUSIBLE_CAP,
    _IMPLAUSIBLE_MAX,
    BOUNDS,
    CONDITION_KINDS,
    FORM_VALUES,
    FORMAT_VERDICTS,
    NAMING_VALUES,
    NOTE_BOUNDS,
    REFEREE_FIELDS,
    STYLE_VALUES,
    UNITS,
    Rule,
    RuleOperation,
    Slotted,
    limit_sink,
    sink_for,
)
from .grammar_questions import SLOT_BAR, AskFn, _ask, pack
from .letter_terms import figures_on_line

if TYPE_CHECKING:
    # Annotation only -- derive.py imports this module (Task 10).
    from .derive import Candidate

logger = logging.getLogger(__name__)

_EVAL = pathlib.Path(__file__).resolve().parents[2] / "docs" / "research" / "cv-format-eval.csv"

#: Spec §6.1: `none` at >= 0.6 means no limit. A figure answered `not_a_limit`
#: that surely is dropped with no note -- a year or a count of referees is not
#: something a student needs to read about. Less sure, the doubt is a note.
_NOT_A_LIMIT_BAR = 0.6

#: Both directions in words. Until 2026-10-08 this question offered two bare
#: labels and the order slot's only example was "in reverse chronological
#: order", so nothing taught what a page asking for OLDEST first says -- and
#: a CV built newest-first against that page is wrong in every row. Literal
#: reading: "chronological" with no reversing word is oldest first.
_DIRECTION_CRITERIA: dict[str, object] = {
    "chronological": {
        "what": "Oldest first: the earliest entry at the top, the most recent last.",
        "examples": ["in chronological order", "starting with the earliest",
                     "beginning with your secondary school",
                     "in chronologischer Reihenfolge, beginnend mit dem Schulabschluss"],
    },
    "reverse_chronological": {
        "what": "Newest first: the most recent entry at the top.",
        "examples": ["in reverse chronological order", "most recent first",
                     "starting with your current position",
                     "in umgekehrt chronologischer Reihenfolge", "antichronologisch"],
    },
}

#: Question id suffix per referee field. `referee_email` because the field name
#: is long for an answer key; the stored record uses the field name itself.
_REFEREE_QUESTIONS: dict[str, str] = {
    "count": "referee_count",
    "kind": "referee_kind",
    "mode": "referee_mode",
    "institutional_email_required": "referee_email",
    "due": "referee_due",
}

_REFEREE_QUESTION_TEXT: dict[str, str] = {
    "count": "How many reference letters does the sentence require?",
    "kind": "From what kind of referee?",
    "mode": "How does each letter reach the programme?",
    "institutional_email_required": "Must the referee write from an institutional email "
                                    "address?",
    "due": "When are the letters due?",
}

#: Every option defined in words: the 2026-10-08 probes showed an undefined
#: question answers under the bar, and an unsure referee answer writes nothing.
_REFEREE_CRITERIA: dict[str, dict[str, object]] = {
    "count": {
        "ONE": {"what": "Exactly one letter.", "examples": ["one letter of recommendation"]},
        "TWO": {"what": "Exactly two letters.",
                "examples": ["two reference letters", "zwei Empfehlungsschreiben"]},
        "THREE_OR_MORE": {"what": "Three or more letters.",
                          "examples": ["three letters of recommendation"]},
        "NONE_REQUIRED": {"what": "The page says no reference letter is needed.",
                          "examples": ["Letters of recommendation are not required."]},
        "NOT_STATED": {"what": "The sentence gives no number."},
    },
    "kind": {
        "ACADEMIC": {"what": "From a teacher, professor or supervisor.",
                     "examples": ["from academic referees", "from a university professor"]},
        "PROFESSIONAL": {"what": "From an employer or work supervisor.",
                         "examples": ["from your current employer"]},
        "EITHER": {"what": "Academic or professional, the applicant chooses.",
                   "examples": ["academic or professional referees"]},
        "NOT_STATED": {"what": "The sentence does not say from whom."},
    },
    "mode": {
        "UPLOAD_GENERIC": {"what": "The student uploads one letter that is accepted as it is.",
                           "examples": ["Upload two signed letters of recommendation."]},
        "UPLOAD_ADDRESSED": {"what": "The student uploads a letter written and addressed to "
                                     "this programme.",
                             "examples": ["The letter must be addressed to the selection "
                                          "committee of this programme."]},
        "PORTAL_INVITE": {"what": "The student enters the referee's email address and the "
                                  "referee uploads the letter or fills a form.",
                          "examples": ["Your referees will receive an email with a link to "
                                       "upload their reference."]},
        "REFEREE_SENDS": {"what": "The referee emails or posts the letter directly.",
                          "examples": ["Referees must send their letters directly to the "
                                       "admissions office."]},
        "NOT_STATED": {"what": "The sentence does not say how the letter arrives."},
    },
    "institutional_email_required": {
        "YES": {"what": "The referee must use an institutional address.",
                "examples": ["from an institutional email address, not a private one"]},
        "NO": {"what": "The page says a private address is accepted."},
        "NOT_STATED": {"what": "The sentence does not say."},
    },
    "due": {
        "WITH_APPLICATION": {"what": "Due with the application, by its deadline.",
                             "examples": ["Submit the letters with your application.",
                                          "Die Empfehlungsschreiben sind mit der Bewerbung "
                                          "hochzuladen."]},
        "BEFORE_DEADLINE": {"what": "A separate referee deadline, stated as a date.",
                            "examples": ["References must arrive by 15 January 2027."]},
        "NOT_STATED": {"what": "The sentence gives no timing."},
    },
}

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
    "Januar|Februar|März|Juni|Juli|Oktober|Dezember"
)
#: A date as a page writes it. ponytail: English and German month names and the
#: numeric forms only; a page writing its date otherwise gets no date option, and
#: its BEFORE_DEADLINE record carries no date -- shown, never guessed.
_DATE = re.compile(
    rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\.?\s+(?:{_MONTHS})\.?,?\s+\d{{4}}"
    rf"|(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[./]\d{1,2}[./]\d{2,4})\b",
    re.IGNORECASE,
)


def _referee_questions(i: int, where: str, text: str) -> dict[str, Question]:
    """The five referee questions, and the date question when the sentence
    prints a date. Asked of every reference-letter sentence, whatever its slot's
    operation, because a sentence states these facts while being about
    something else ("Two letters, uploaded by your referees by 15 January")."""
    questions: dict[str, Question] = {
        f"{i}:{suffix}": Choice(
            inspect=where, question=_REFEREE_QUESTION_TEXT[field],
            options=REFEREE_FIELDS[field], criteria=_REFEREE_CRITERIA[field],
        )
        for field, suffix in _REFEREE_QUESTIONS.items()
    }
    dates = tuple(dict.fromkeys(m.group(0) for m in _DATE.finditer(text)))
    if dates:
        questions[f"{i}:referee_due_date"] = Choice(
            inspect=where, question="which date is the referees' deadline, if any?",
            options=(*dates, "none"),
        )
    return questions


def _referee_drafts(answers: Mapping[str, Answer], i: int) -> list[_Draft]:
    """One `referee` draft per field answered at the bar with a stated value.
    NOT_STATED and an unsure answer write nothing: the catalogue reads a missing
    field as not stated, which is the truth about both."""
    drafts: list[_Draft] = []
    for field, suffix in _REFEREE_QUESTIONS.items():
        answer = answers.get(f"{i}:{suffix}")
        if answer is None or answer.value == "NOT_STATED" or answer.confidence < SLOT_BAR:
            continue
        detail = ""
        if field == "due" and answer.value == "BEFORE_DEADLINE":
            date = answers.get(f"{i}:referee_due_date")
            if date is not None and date.value != "none" and date.confidence >= SLOT_BAR:
                detail = str(date.value)
        drafts.append(_Draft("referee", (field, str(answer.value)), answer.confidence,
                             detail=detail))
    return drafts


#: `cv` defined, the sections left to their names. Measured live 2026-10-08:
#: undefined, "education and work experience in chronological order" came back
#: `education` at 0.51 and "Der Lebenslauf ... chronologisch" `cv` at 0.79-0.82,
#: under the bar, so a whole-CV order never applied.
_ORDER_TARGET_CRITERIA: dict[str, object] = {
    "cv": {
        "what": "The whole CV, or more than one section at once.",
        "examples": ["A curriculum vitae in reverse chronological order.",
                     "List your education and work experience in chronological order.",
                     "Der Lebenslauf ist in chronologischer Reihenfolge zu verfassen."],
    },
}

_BOUND_CRITERIA: dict[str, object] = {
    "maximum": {
        "what": "The most the document may be: a cap.",
        "examples": ["no more than 800 words", "maximal zwei DIN-A4-Seiten",
                     "the 500 in 300–500 words"],
    },
    "minimum": {
        "what": "The least the document must be: a floor.",
        "examples": ["at least 500 words", "mindestens 2.800 Zeichen",
                     "the 300 in 300–500 words"],
    },
    "approximate": {
        "what": "A length the page gives as approximate: around, about, roughly.",
        "examples": ["approximately one A4 page", "around 1,000 words"],
    },
    "section_limit": {
        "what": "A length of one part, section or answer of the document, not of the whole.",
        "examples": ["the 400 in 'three parts of 400 words each'",
                     "Each answer may be up to 250 words."],
    },
    "another_statement": {
        "what": "A length of a different, additional statement in the same application.",
        "examples": ["the 250 in 'in addition, a statement of 250 words on your research'"],
    },
    "not_a_limit": {
        "what": "Not a length of this document: a year, a date, a count of documents "
                "or referees, a percentage, a fee, a font size.",
        "examples": ["the 2027 intake", "two letters of recommendation", "10 percent"],
    },
}

_UNIT_CRITERIA: dict[str, object] = {
    "pages": {"what": "Pages or sheets.", "examples": ["two pages", "zwei DIN-A4-Seiten", "2枚"]},
    "words": {"what": "Words.", "examples": ["800 words", "1 000 mots", "500 Wörter"]},
    "characters": {"what": "Characters or signs, with or without spaces.",
                   "examples": ["3,500 characters", "2.800 Zeichen", "800字"]},
    "megabytes": {"what": "Megabytes (MB) of the file's size.",
                  "examples": ["under 2MB", "The PDF file must not exceed 10 MB"]},
    "other": {"what": "Anything else: kilobytes, lines, minutes, percent, or no unit at all."},
}

#: Criteria because the common real sentence says nothing about spaces, and
#: counting them is the stricter reading of a cap -- so silence answers yes.
_SPACES_CRITERIA: dict[str, object] = {
    "true": {"what": "Spaces are counted, or the sentence does not mention spaces at all.",
             "examples": ["3,500 characters including spaces", "1,500 characters",
                          "2.000 Zeichen inkl. Leerzeichen"]},
    "false": {"what": "The sentence says spaces are not counted.",
              "examples": ["4,000 characters without spaces", "2.000 Zeichen ohne Leerzeichen",
                           "3 000 caractères hors espaces"]},
}


#: A font name as a page prints it: capitalised words, optionally several
#: ("Times New Roman", "Liberation Sans"), optionally with a digit ("Arial 11").
#: Code finds the candidates and the Choice picks one, so a font nobody wrote
#: cannot be chosen -- the same rule as a number. A closed list is impossible
#: here: a page may legitimately name any font.
_FONT_NAME = re.compile(r"\b[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,3}\b")
#: Words that are capitalised at the start of a sentence or in a heading and are
#: certainly not fonts. Additive and deliberately short: a wrong entry costs one
#: option in a Choice that also offers `none`, never a rule.
_NOT_A_FONT = frozenset({
    "The", "Use", "Your", "Please", "All", "Applicants", "CV", "Europass", "A", "An",
    "It", "We", "Documents", "Application", "Letter", "Motivation", "This", "Note",
})


def font_candidates(text: str) -> tuple[str, ...]:
    """Every plausible font name the sentence prints, in order, deduplicated.

    A capitalised run is trimmed of the leading words that are certainly not a
    font ("Use Times New Roman" -> "Times New Roman"), never discarded whole:
    the regex consumes the run, so a skipped run is a font nobody can pick.
    """
    found: list[str] = []
    for match in _FONT_NAME.finditer(text):
        words = match.group().split()
        while words and words[0] in _NOT_A_FONT:
            words.pop(0)
        name = " ".join(words)
        if len(name) >= 4 and name not in found:
            found.append(name)
    return tuple(found)


#: Line-spacing WORDS a page states instead of a number ("double-spaced",
#: "einzeilig"), mapped to the multiplier the module already knows (fix round
#: 1, finding 6). Additive and deliberately short, like `_NOT_A_FONT`: a
#: missing word costs an option the sentence's own printed figure or the
#: vendor's `none`/`not_stated` escape still covers, never a wrong rule.
_SPACING_WORDS: dict[str, str] = {
    "single": "1.0", "single-spaced": "1.0", "einzeilig": "1.0", "einfach": "1.0",
    "double": "2.0", "double-spaced": "2.0", "doppelt": "2.0", "doppelzeilig": "2.0",
    "one-and-a-half": "1.5", "one and a half": "1.5", "anderthalbzeilig": "1.5",
}


def spacing_candidates(text: str) -> tuple[str, ...]:
    """Every line-spacing value the sentence could mean, as code finds it: a
    figure `figures_on_line` printed on the line, or one of the small set of
    spacing words (fix round 1, finding 6). Numbers come from the page, never
    from a fixed ("1.0", "1.5", "2.0") menu offered whether or not the page
    said any of them -- "1.15" is a real page value that menu could not name.
    """
    found: list[str] = [str(figure.number) for figure in figures_on_line(text)]
    lowered = text.casefold()
    for word, value in _SPACING_WORDS.items():
        if word in lowered and value not in found:
            found.append(value)
    return tuple(dict.fromkeys(found))


#: The eval sheet's own outcome vocabulary, mapped to the grammar's -- and
#: only the two that map cleanly (controller ruling C10). `europass` rows are
#: LEFT OUT entirely: the sheet does not say whether each is required or
#: preferred ("We recommend using the template provided by europass" is
#: labelled `europass` beside rows that really do mandate it), and teaching a
#: recommendation as `europass_required` is exactly the PII-shipping mistake
#: this grammar exists to stop. `unapplied`, `constraint`, `include`, `order`
#: and `emphasise` are outcomes of OTHER operations in the same sheet and are
#: not format verdicts at all, so they are left out rather than mapped.
_EVAL_OUTCOME: dict[str, str] = {
    "standard": "any",
    "none": "not_a_format_rule",
}


def _format_examples() -> dict[str, dict[str, object]]:
    """The eval sheet's unambiguous rows as criteria examples.

    Real sentences, with the verdict a person confirmed. Only `standard` (-> `any`)
    and `none` (-> `not_a_format_rule`) are unambiguous enough to teach: negation
    ("no need to use the Europass format") and a stated choice both land as
    `any`, which is what the keyword rule got wrong at 61% (spec of 2026-09-13).
    A row labelled `europass` is never used as an example of `europass_required`.
    """
    criteria: dict[str, dict[str, object]] = {
        verdict: {"examples": []} for verdict in FORMAT_VERDICTS
    }
    criteria["europass_required"]["what"] = (
        "The applicant's own CV must be in the Europass format or template."
    )
    criteria["europass_preferred"]["what"] = (
        "Europass is recommended, suggested or offered for the applicant's own CV, "
        "but another format is allowed."
    )
    criteria["any"]["what"] = "No format is imposed on the applicant's own CV."
    criteria["other_template"]["what"] = (
        "A template or form OTHER than Europass is required -- the funder's own, "
        "a named tabular form, a downloadable file."
    )
    criteria["not_a_format_rule"]["what"] = (
        "The sentence states no rule about the FORM of the applicant's own CV."
    )
    if _EVAL.exists():
        with _EVAL.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                verdict = _EVAL_OUTCOME.get(row["outcome"], "")
                if verdict in criteria and len(criteria[verdict]["examples"]) < 8:  # type: ignore[arg-type]
                    criteria[verdict]["examples"].append(row["sentence"][:400])  # type: ignore[attr-defined]
    else:
        # Fix round 1, finding 8: this used to degrade silently to no examples
        # at all -- a format Choice with an empty `criteria["examples"]` list
        # still asks its question, so a missing file costs accuracy nobody
        # would notice was missing. Loud, once, at import, naming the path.
        logger.warning("cv-format-eval.csv not found at %s; FORMAT_EXAMPLES has no examples",
                       _EVAL)
    return criteria


FORMAT_EXAMPLES = _format_examples()


def _asks_values(slot: Slotted) -> bool:
    return slot.document != "other" and not _below_bar(slot)


def _asks_referee(slot: Slotted) -> bool:
    """A sentence confidently about a reference letter is asked the referee
    questions whatever its operation. Measured live 2026-10-08: the slot reader
    could not settle what OPERATION four of six reference sentences performed
    (student_action, form, other), and a below-bar operation skipped every
    value question -- while the document itself read at 0.99-1.0."""
    return slot.document == "reference_letter" and slot.document_confidence >= SLOT_BAR


def value_state(
    candidates: Sequence[Candidate], slots: Sequence[Slotted]
) -> dict[str, object]:
    """The sentences these slots reference, and under each length sentence the
    figures code found -- indexed LOCALLY to this request (controller ruling
    C1), never by `slot.index` into the whole page's candidates.

    A figure is shown as code found it -- the number and the unit word printed
    after it -- so each bound question points at one figure by path
    (`sentences[3].figures[1]`), never "the second number" in prose (§3.1a).
    """
    limits = {i for i, s in enumerate(slots) if s.operation == "limit" and _asks_values(s)}
    sentences: list[dict[str, object]] = []
    for i, slot in enumerate(slots):
        candidate = candidates[slot.index]
        entry: dict[str, object] = {"id": str(i), "heading": candidate.heading,
                                    "text": candidate.text}
        if i in limits:
            entry["figures"] = [
                {"figure": str(f.number), "unit_as_printed": f.unit}
                for f in figures_on_line(candidate.text)
            ]
        sentences.append(entry)
    return {"sentences": sentences}


def value_questions(
    candidates: Sequence[Candidate], slots: Sequence[Slotted]
) -> dict[str, Question]:
    """One question set per sentence, for the operation its slot found.

    A sentence whose slots are below the bar, or whose document is `other`, gets
    no value question at all: there is nothing to ask a value for. Every id is
    keyed by LOCAL position within `slots` (controller ruling C1), matching
    `value_state`.
    """
    questions: dict[str, Question] = {}
    for i, slot in enumerate(slots):
        where = f"`sentences[{i}]`"
        text = candidates[slot.index].text
        if _asks_referee(slot):
            # Before the bar check, on purpose: see _asks_referee.
            questions.update(_referee_questions(i, where, text))
            if slot.conditional:
                questions[f"{i}:condition"] = Choice(
                    inspect=where, question="what is the condition about?",
                    options=CONDITION_KINDS,
                )
        if not _asks_values(slot):
            continue
        if slot.operation == "limit":
            # Every question below is asked for every figure: a figure's unit
            # and bound are in the same response, so none can wait for another.
            # Tokens, never a call.
            for k in range(len(figures_on_line(text))):
                at = f"`sentences[{i}].figures[{k}]`"
                questions[f"{i}:figure:{k}:bound"] = Choice(
                    inspect=at, options=BOUNDS, criteria=_BOUND_CRITERIA,
                    question="Is this figure a limit on the document's length, and which kind?",
                    focus="Read the figure inside its sentence: a range states two "
                          "figures, a floor and a cap.",
                )
                questions[f"{i}:figure:{k}:unit"] = Choice(
                    inspect=at, question="What is this figure counted in?",
                    options=(*UNITS, "other"), criteria=_UNIT_CRITERIA,
                )
                if slot.document == "cv":
                    # Only the CV picks a key by it (max_chars_incl/excl_spaces);
                    # the letter's cap is measured with spaces and its floor
                    # without -- each the stricter reading -- so it never asks.
                    questions[f"{i}:figure:{k}:spaces"] = Noul(
                        inspect=at, question="Does this count of characters include spaces?",
                        criteria=_SPACES_CRITERIA,
                    )
        elif slot.operation == "format":
            questions[f"{i}:format"] = Choice(
                inspect=where, question="what does it require about the FORM of the document?",
                options=FORMAT_VERDICTS, criteria=FORMAT_EXAMPLES,
            )
            questions[f"{i}:format_noul"] = Noul(
                inspect=where, question="does it require the Europass CV format?",
            )
            questions[f"{i}:format_applicant"] = Choice(
                inspect=where, question=(
                    "reading it from the applicant's side -- what must the "
                    "applicant submit?"
                ),
                options=FORMAT_VERDICTS, criteria=FORMAT_EXAMPLES,
            )
        elif slot.operation == "language":
            # Set-valued, not one Choice. Eiffel's R-072 says "CV in French or
            # English" and render._check_language has taken a list since, so a
            # Choice here would pick one and silently forbid the other. Code
            # finds the names the sentence prints; one Noul per name asks
            # whether it is allowed, and every yes is a value.
            for name, code in language_candidates(text):
                questions[f"{i}:language:{code}"] = Noul(
                    inspect=where, question=(
                        "does it allow the document to be written in "
                        f"{name}?"
                    ),
                )
        elif slot.operation == "style":
            questions[f"{i}:style"] = Choice(
                inspect=where, question="Which presentation rule does it state?",
                # `other` is the escape the vendor asks for; it has no sink and
                # becomes `unapplied`, which is what a style we do not know is.
                options=(*STYLE_VALUES, "other"),
            )
            # The three sub-values, asked unconditionally. A detail question
            # cannot wait for the style answer -- they are in one response --
            # and asking all three costs tokens, never an extra call. Only the
            # one the chosen style needs is read.
            numbers = tuple(dict.fromkeys(str(f.number) for f in figures_on_line(text)))
            questions[f"{i}:style_number"] = Choice(
                inspect=where, question="which number does it state, if any?",
                options=(*numbers, "none") if numbers else ("none", "not_stated"),
            )
            spacings = spacing_candidates(text)
            questions[f"{i}:style_spacing"] = Choice(
                inspect=where, question="what line spacing does it require, if any?",
                options=(*spacings, "none") if spacings else ("none", "not_stated"),
            )
            fonts = font_candidates(text)
            questions[f"{i}:style_font"] = Choice(
                inspect=where, question="which font does it name, if any?",
                options=(*fonts, "none") if fonts else ("none", "not_stated"),
            )
        elif slot.operation in ("form", "naming"):
            questions[f"{i}:{slot.operation}"] = Choice(
                inspect=where, question=_TARGET_QUESTION[slot.operation],
                options=_TARGET_OPTIONS[slot.operation],
            )
        elif slot.operation in ("include", "order", "emphasise"):
            questions[f"{i}:{slot.operation}"] = Choice(
                inspect=where, question=_TARGET_QUESTION[slot.operation],
                options=_TARGET_OPTIONS[slot.operation],
                criteria=_ORDER_TARGET_CRITERIA if slot.operation == "order" else {},
            )
            if slot.operation == "order":
                questions[f"{i}:order_direction"] = Choice(
                    inspect=where, question="in which direction?",
                    options=("chronological", "reverse_chronological"),
                    criteria=_DIRECTION_CRITERIA,
                )
        if slot.conditional:
            questions[f"{i}:condition"] = Choice(
                inspect=where, question="what is the condition about?", options=CONDITION_KINDS,
            )
    return questions


def read_values(
    candidates: Sequence[Candidate],
    slots: Sequence[Slotted],
    *,
    language: str = "",
    budget: DecisionBudget | None = None,
    client: AskFn | None = None,
    record: bool = True,
) -> tuple[Rule, ...]:
    """The typed rules and notes for one page. Packed by estimated tokens
    (controller ruling C1), never by a fixed sentence count.

    One sentence may yield several rules -- a range, two units, a note beside
    the rules that cleared the bar -- each carrying its sentence and `figure`.

    **Only slots that ask a real value question are packed at all** (fix
    round 1, finding 7). A `topic`/`student_action` slot's value IS its
    sentence, verbatim, with no question asked of anyone; a below-bar or
    `other`-document slot needs no answer either. Sending those along in a
    chunk anyway used to cost real tokens for nothing -- `value_state` put a
    full sentence entry in the request for every slot the chunk carried,
    whether or not any question referenced it, so a page with one length
    sentence and a hundred topic sentences packed all hundred-and-one into
    the same growing request. Those slots are answered directly, with no
    request at all; `Rule.index` still names the sentence globally either way.
    """
    def _build(sub: Sequence[Slotted]) -> tuple[object, Mapping[str, Question]]:
        return value_state(candidates, sub), value_questions(candidates, sub)

    rules: list[Rule] = []
    asked: list[Slotted] = []
    for slot in slots:
        if value_questions(candidates, (slot,)):
            asked.append(slot)
        else:
            rules.extend(_rules_for(candidates, slot, {}, 0))

    for chunk in pack(asked, _build):
        answers = _ask(
            value_state(candidates, chunk), value_questions(candidates, chunk),
            decision="D6.values", language=language, budget=budget, record=record,
            client=client,
        )
        for i, slot in enumerate(chunk):
            rules.extend(_rules_for(candidates, slot, answers, i))
    return tuple(rules)


def _below_bar(slot: Slotted) -> bool:
    return min(slot.document_confidence, slot.operation_confidence) < SLOT_BAR


@dataclass(frozen=True)
class _Draft:
    """One rule before its scope is settled: a figure, or the one value a
    non-limit operation states."""

    operation: RuleOperation
    value: object
    confidence: float
    note: str = ""
    unit: str = ""
    bound: str = ""
    detail: str = ""
    figure: int | None = None
    excl_spaces: bool = False


def _rules_for(
    candidates: Sequence[Candidate], slot: Slotted, answers: Mapping[str, Answer], i: int
) -> tuple[Rule, ...]:
    """`i` is this slot's LOCAL position in the request that produced `answers`
    (controller ruling C1) -- it names the answer keys, never the sentence:
    the sentence and the produced `Rule.index` both come from `slot.index`."""
    candidate = candidates[slot.index]

    if slot.document == "other" and slot.document_confidence >= SLOT_BAR:
        # Fees, deadlines, transcripts. Not this reader's business, and not a
        # note either -- a note on every unrelated sentence is noise that hides
        # the notes that matter.
        return ()
    # Controller ruling C3: a conditional sentence is ALWAYS a note, never
    # applied -- addendum §6.6 says a conditional rule binds no student until
    # the student's own facts are compared. `condition` still carries the
    # kind the vendor named (or "other" when no question was asked or
    # answered), so a later re-derivation sweep knows what to compare against.
    condition = ""
    if slot.conditional:
        chosen = answers.get(f"{i}:condition")
        condition = str(chosen.value) if chosen else "other"
    referee = _referee_drafts(answers, i) if _asks_referee(slot) else []

    if _below_bar(slot):
        unsure = Rule(
            index=slot.index, document=slot.document, operation=slot.operation, value=None,
            sentence=candidate.text, heading=candidate.heading, note="unsure",
            confidence=min(slot.document_confidence, slot.operation_confidence),
            probabilities=(("document", slot.document_confidence),
                           ("operation", slot.operation_confidence)),
        )
        return (unsure, *_settled(slot, candidate, referee, condition))

    if slot.operation == "limit":
        drafts = _limit_drafts(candidate, slot, answers, i)
    elif slot.operation == "language":
        drafts = _language_drafts(answers, i)
    else:
        value, unit, detail, confidence, note = _value(candidate, slot, answers, i)
        drafts = [_Draft(slot.operation, value, confidence, note, unit=unit, detail=detail)]

    return _settled(slot, candidate, [*drafts, *referee], condition)


def _settled(
    slot: Slotted, candidate: Candidate, drafts: Sequence[_Draft], condition: str
) -> tuple[Rule, ...]:
    """Each draft as a rule, with the scope notes its slot puts on it."""
    rules: list[Rule] = []
    for draft in drafts:
        note = draft.note
        # Fix round 1, finding 2: third_party is a PERMANENT exclusion (never
        # the applicant's own document); conditional is provisional, awaiting
        # the student's own facts (addendum §6.6). Checked in this order so a
        # sentence that is both is noted "third_party", never "conditional".
        # A referee fact is ABOUT the referee's letter by definition -- the
        # third_party exclusion is about whose document a rule binds, and would
        # otherwise drop every fact about how the referee's letter arrives.
        if not note and slot.third_party and draft.operation != "referee":
            note = "third_party"
        if not note and slot.conditional:
            note = "conditional"
        if not note and not _has_sink(slot.document, draft):
            note = "unapplied"
        rules.append(Rule(
            index=slot.index, document=slot.document, operation=draft.operation,
            value=draft.value, sentence=candidate.text, heading=candidate.heading,
            unit=draft.unit, bound=draft.bound, detail=draft.detail, figure=draft.figure,
            excl_spaces=draft.excl_spaces,
            confidence=draft.confidence, note=note, condition=condition,
        ))
    return tuple(rules)


def _has_sink(document: str, draft: _Draft) -> bool:
    if draft.operation == "limit":
        return bool(limit_sink(document, draft.bound, draft.unit, excl_spaces=draft.excl_spaces))
    return bool(sink_for(document, draft.operation, draft.unit or draft.value))


def _limit_drafts(
    candidate: Candidate, slot: Slotted, answers: Mapping[str, Answer], i: int
) -> list[_Draft]:
    """One draft per figure the sentence states as a length, at most one topic
    for the figures that are a section's or another statement's length, and at
    most one note for the figures it could not settle and one for what no sink
    holds.

    Nothing here combines figures. There is no min() of a range: "300-500 words"
    is a floor and a cap, and "3,500 characters (approximately 500 words)" is
    two caps (addendum §6.1). The number is always the figure code found.
    """
    drafts: list[_Draft] = []
    doubt: float | None = None
    no_sink_unit = False
    noted = False
    for k, figure in enumerate(figures_on_line(candidate.text)):
        bound = answers.get(f"{i}:figure:{k}:bound")
        unit = answers.get(f"{i}:figure:{k}:unit")
        if bound is None or unit is None:
            continue
        if bound.value == "not_a_limit":
            if bound.confidence < _NOT_A_LIMIT_BAR:
                doubt = bound.confidence if doubt is None else min(doubt, bound.confidence)
            continue
        if bound.value in NOTE_BOUNDS:
            if bound.confidence < SLOT_BAR:
                doubt = bound.confidence if doubt is None else min(doubt, bound.confidence)
                continue
            if not noted:
                # Addendum §6.5: a section's length or another statement's.
                # Kept as ONE topic carrying its sentence, whatever the unit, so
                # the letter writer reads it and the document carries it;
                # nothing enforces it (§10). Never a cap or a floor.
                noted = True
                drafts.append(_Draft("topic", candidate.text, bound.confidence,
                                     bound=str(bound.value), figure=k))
            continue
        confidence = min(bound.confidence, unit.confidence)
        if confidence < SLOT_BAR:
            doubt = confidence if doubt is None else min(doubt, confidence)
            continue
        if unit.value not in UNITS:
            # A length in a unit nothing holds: kilobytes, lines, minutes.
            no_sink_unit = True
            continue
        if not _plausible(figure.number, str(bound.value), str(unit.value)):
            continue
        spaces = answers.get(f"{i}:figure:{k}:spaces")
        excluded = (
            unit.value == "characters" and spaces is not None
            and spaces.value is False and spaces.confidence >= SLOT_BAR
        )
        drafts.append(_Draft(
            "limit", figure.number, confidence, unit=str(unit.value), bound=str(bound.value),
            figure=k, excl_spaces=excluded,
        ))
    if doubt is not None:
        drafts.append(_Draft("limit", None, doubt, "unsure"))
    if no_sink_unit or not drafts:
        # A length sentence that yields no length -- "keep it short", or every
        # figure a year -- still stated a requirement. Shown, never dropped.
        drafts.append(_Draft("limit", None, slot.operation_confidence, "unapplied"))
    return drafts


def _plausible(number: int | float, bound: str, unit: str) -> bool:
    """derive.py's two plausibility bands, unchanged: a cap below the smallest
    any programme states, or any figure above the largest, is a misread digit.
    Only that figure drops; the default applies in its place."""
    key = "chars" if unit == "characters" else unit
    if number > _IMPLAUSIBLE_MAX[key]:
        logger.warning("ignoring an implausible %s %s of %s on a programme page",
                       key, bound, number)
        return False
    if bound != "minimum" and number < _IMPLAUSIBLE_CAP[key]:
        logger.warning("ignoring an implausible %s cap of %s on a programme page", key, number)
        return False
    return True


def _language_drafts(answers: Mapping[str, Answer], i: int) -> list[_Draft]:
    """One applied draft for the languages accepted AT THE BAR, plus one
    `unsure` note per language the sentence named as allowed but whose
    confidence did not clear the bar (fix round 1, finding 3).

    A below-bar yes must not silently vanish -- its own `unsure` note keeps it
    visible -- and it must not drag the accepted draft's own confidence down
    with it: the old code folded every truthy answer, at any confidence, into
    one `min()`, so one shaky "yes" on a language nobody should read as
    allowed could report the whole rule as unsure even though the languages
    that DID clear the bar were confident.
    """
    accepted: list[tuple[str, float]] = []
    below_bar: list[tuple[str, float]] = []
    for key, answer in answers.items():
        if not key.startswith(f"{i}:language:") or not answer.value:
            continue
        code = key.rsplit(":", 1)[1]
        (accepted if answer.confidence >= SLOT_BAR else below_bar).append(
            (code, answer.confidence)
        )
    drafts: list[_Draft] = []
    if accepted:
        codes = sorted(code for code, _ in accepted)
        # A list where the page named several, a bare string where it named
        # one: _check_language reads both, and a one-item list would change
        # nothing except how the rule reads to a person.
        value: object = codes if len(codes) > 1 else codes[0]
        drafts.append(_Draft("language", value, min(confidence for _, confidence in accepted)))
    for code, confidence in below_bar:
        drafts.append(_Draft("language", None, confidence, "unsure"))
    if not accepted and not below_bar:
        drafts.append(_Draft("language", None, 0.0, "unapplied"))
    return drafts


def _value(
    candidate: Candidate, slot: Slotted, answers: Mapping[str, Answer], i: int
) -> tuple[object, str, str, float, str]:
    """The typed value, its unit, its detail, its confidence, and a note if it
    cannot stand. Every operation but `limit` (`_limit_drafts`) and `language`
    (`_language_drafts`), each of which may yield more than one draft."""
    if slot.operation == "format":
        return _format_value(answers, i)
    if slot.operation == "order":
        target = answers.get(f"{i}:order")
        direction = answers.get(f"{i}:order_direction")
        if target is None or direction is None:
            return None, "", "", 0.0, "unapplied"
        confidence = min(target.confidence, direction.confidence)
        return ((str(target.value), str(direction.value)), "", "", confidence,
                "" if confidence >= SLOT_BAR else "unsure")
    if slot.operation == "style":
        return _style_value(answers, i)
    if slot.operation in ("include", "emphasise", "form", "naming"):
        answer = answers.get(f"{i}:{slot.operation}")
        if answer is None:
            return None, "", "", 0.0, "unapplied"
        return (str(answer.value), "", "", answer.confidence,
                "" if answer.confidence >= SLOT_BAR else "unsure")
    if slot.operation in ("topic", "student_action"):
        # The value IS the sentence, verbatim. No question is asked, because
        # there is nothing closed to choose from -- and nothing open is invented.
        return candidate.text, "", "", slot.operation_confidence, ""
    # `other` at the bar: a real requirement with no handler (spec §6.5).
    return None, "", "", slot.operation_confidence, "unapplied"


#: Which sub-value question each style value reads. A style not here needs none:
#: `photo_forbidden` is the whole rule.
_STYLE_DETAIL: dict[str, str] = {
    "font_family": "style_font",
    "font_size_minimum": "style_number",
    "line_spacing": "style_spacing",
    "margins": "style_number",
}


def _style_value(answers: Mapping[str, Answer], i: int) -> tuple[object, str, str, float, str]:
    """The style rule and, where it has one, the value it names.

    A style whose detail question came back `none` or `not_stated` is a rule the
    sentence did not finish stating -- "use a legible font" names no font -- and
    it is `unapplied` rather than a rule with an empty value, which nothing
    downstream could act on.
    """
    chosen = answers.get(f"{i}:style")
    if chosen is None:
        return None, "", "", 0.0, "unapplied"
    value = str(chosen.value)
    needs = _STYLE_DETAIL.get(value)
    if needs is None:
        return (value, "", "", chosen.confidence,
                "" if chosen.confidence >= SLOT_BAR else "unsure")
    detail_answer = answers.get(f"{i}:{needs}")
    detail = str(detail_answer.value) if detail_answer else "none"
    if detail in ("none", "not_stated"):
        return value, "", "", chosen.confidence, "unapplied"
    confidence = min(chosen.confidence, detail_answer.confidence if detail_answer else 1.0)
    return value, "", detail, confidence, "" if confidence >= SLOT_BAR else "unsure"


def _format_value(answers: Mapping[str, Answer], i: int) -> tuple[object, str, str, float, str]:
    """Three phrasings in one request; act when two of three agree AT THE BAR
    (spec §6.2). Anything less is the `phrasing` note, and the CV renders `any`.

    A Noul and a Choice on the same question are not guaranteed to agree
    (TypeSafe's own docs), which is exactly why their agreement is information.
    `europass_required` and `europass_preferred` are different verdicts, not an
    agreement: reading them as one is how a recommendation became a mandate.
    """
    choice = answers.get(f"{i}:format")
    noul = answers.get(f"{i}:format_noul")
    applicant = answers.get(f"{i}:format_applicant")
    if choice is None or noul is None or applicant is None:
        return None, "", "", 0.0, "unapplied"
    votes = [
        (str(choice.value), choice.confidence),
        ("europass_required" if noul.value else "not_europass", noul.confidence),
        (str(applicant.value), applicant.confidence),
    ]
    at_bar = Counter(verdict for verdict, confidence in votes if confidence >= SLOT_BAR)
    agreed, count = at_bar.most_common(1)[0] if at_bar else ("", 0)
    if count < 2 or agreed not in FORMAT_VERDICTS:
        return str(choice.value), "", "", choice.confidence, "phrasing"
    confidence = min(c for verdict, c in votes if verdict == agreed and c >= SLOT_BAR)
    return agreed, "", "", confidence, ""


_TARGET_QUESTION = {
    "include": "Which piece of information must the document contain?",
    "order": "Which section must be ordered?",
    "emphasise": "Which section must be foregrounded?",
    "form": "What kind of text must the letter be?",
    "naming": "Must, may or must not the letter name a prospective supervisor?",
}

#: Each with `none`: the vendor's rule is an escape option whenever the list
#: may not cover the input, and a directive forced onto the wrong field is
#: worse than one marked unapplied. `none` has no sink, so it falls through
#: to `unapplied` with the sentence kept.
_TARGET_OPTIONS: dict[str, tuple[str, ...]] = {
    "include": (*_INCLUDE_TARGETS, "none"),
    "order": (*_ORDER_TARGETS, "none"),
    "emphasise": (*_SECTIONS, "none"),
    "form": (*FORM_VALUES, "none"),
    "naming": (*NAMING_VALUES, "none"),
}

#: Language NAMES as a page prints them, to the ISO 639-1 code the `language`
#: constraint key and `ApplicationPrompt.document_language` use. A seed only:
#: plan 2 replaces it with vocabulary.csv's `language_names` rows in all
#: fourteen languages, and the lookup below is the seam that does not change.
#: A name missing here costs a language the sentence allowed -- never a wrong
#: one -- so it degrades to a tighter rule a person sees, not a looser one.
_LANGUAGE_NAMES: dict[str, str] = {
    "english": "en", "englisch": "en", "anglais": "en", "inglés": "en", "ingilizce": "en",
    "german": "de", "deutsch": "de", "allemand": "de", "almanca": "de",
    "french": "fr", "français": "fr", "französisch": "fr", "francais": "fr",
    "spanish": "es", "español": "es", "espagnol": "es",
    "portuguese": "pt", "português": "pt",
    "italian": "it", "italiano": "it",
    "dutch": "nl", "nederlands": "nl",
    "russian": "ru", "русский": "ru",
    "turkish": "tr", "türkçe": "tr",
    "chinese": "zh", "中文": "zh",
    "japanese": "ja", "日本語": "ja",
    "korean": "ko", "한국어": "ko",
}


def language_candidates(text: str) -> tuple[tuple[str, str], ...]:
    """Every language name the sentence prints, as (name, code), deduplicated.

    Code finds them so the Nouls that follow are about languages the page named,
    never a list of every language we know: asking thirteen Nouls on a sentence
    that names one is thirteen chances to say yes to a language nobody allowed.
    """
    lowered = text.casefold()
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, code in _LANGUAGE_NAMES.items():
        if name in lowered and code not in seen:
            seen.add(code)
            found.append((name, code))
    return tuple(found)
