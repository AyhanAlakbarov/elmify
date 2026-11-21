"""Spec §5.1 (S-026): a bullet that does not start with what the student did
gets one opening from a fixed list, in front of the student's own words.

Code decides everything except one choice. It finds the line, filters the
openings, attaches the chosen one and refuses an over-long result. Jev only
picks which allowed opening fits the line, or leave_unchanged (Task 5 adds
that call). The opening verb IS a claim -- "Built" and "Used" say different
things about the same line -- so the openings Jev may pick are capped by code
at the strength the student's own words in the same entry already show.

English only (MVP): S-026's sources are English-language guides, and German,
French and Turkish lines rightly open with a noun or end with the verb
(docs/research/2026-10-12-cv-engine/section-2-refined.md §4).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

from apps.ratelimit import rate_limited
from apps.research.decisions import (
    Choice,
    Client,
    DecisionsUnavailable,
    ask,
    provider_for,
)

from .cv_fixes import VERB_OPENER, AppliedFix, subject_of
from .letter_terms import detect_language
from .schemas import CVContent

logger = logging.getLogger(__name__)

MAX_BULLETS = 30
#: Bullet's own max_length (schemas.py).
_MAX_BULLET = 500

DECISION = "cv_verb_opener"
#: Part of every cache key: changing the question or the list re-asks.
QUESTION_VERSION = "v1"
LEAVE = "leave_unchanged"
#: Below this an answer is doubt, and doubt keeps the line (spec §5.1).
BAR = 0.9
_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 3600
_CACHE_SECONDS = 30 * 24 * 3600

_QUESTION = (
    "This is one line from the work-experience section of a CV. Which opening, put in "
    "front of the line exactly as it stands, says what the applicant did without "
    "claiming more than the line itself says? Choose leave_unchanged if the line names "
    "an award, a course, a topic or a title rather than work the applicant did, or if "
    "every opening would claim more than the line says."
)


@dataclass(frozen=True)
class Opener:
    id: str
    past: str
    present: str
    #: 1 says the student was involved; 2 that they did it; 3 that they led it.
    strength: int


OPENERS: tuple[Opener, ...] = (
    Opener("worked_on", "Worked on", "Work on", 1),
    Opener("contributed_to", "Contributed to", "Contribute to", 1),
    Opener("assisted_with", "Assisted with", "Assist with", 1),
    Opener("used", "Used", "Use", 1),
    Opener("studied", "Studied", "Study", 1),
    Opener("developed", "Developed", "Develop", 2),
    Opener("implemented", "Implemented", "Implement", 2),
    Opener("built", "Built", "Build", 2),
    Opener("wrote", "Wrote", "Write", 2),
    Opener("tested", "Tested", "Test", 2),
    Opener("designed", "Designed", "Design", 2),
    Opener("led", "Led", "Lead", 3),
    Opener("managed", "Managed", "Manage", 3),
    Opener("coordinated", "Coordinated", "Coordinate", 3),
    Opener("supervised", "Supervised", "Supervise", 3),
)
BY_ID = {opener.id: opener for opener in OPENERS}

#: Words that, in the entry's own title or bullets, unlock a strength (§5.1: a
#: stronger verb only when the student's text already uses one of equal strength).
_STRENGTH_FORMS: dict[int, frozenset[str]] = {
    2: frozenset({
        "develop", "developed", "developing", "develops", "implement", "implemented",
        "implementing", "build", "built", "building", "builds", "write", "wrote", "written",
        "writing", "test", "tested", "testing", "design", "designed", "designing", "designs",
        "created", "engineered", "programmed", "coded", "constructed", "authored",
        "benchmarked", "trained", "deployed",
    }),
    3: frozenset({
        "lead", "led", "leading", "leads", "manage", "managed", "managing", "manages",
        "manager", "coordinate", "coordinated", "coordinating", "coordinator", "supervise",
        "supervised", "supervising", "supervisor", "headed", "directed", "chaired",
    }),
}

#: Base forms of verbs a CV line commonly opens with. A line opening with one
#: of these, its -s/-es form, an irregular past below, or any -ed word is
#: already a verb line.
_VERB_BASES = frozenset({
    "achieve", "add", "administer", "advise", "analyse", "analyze", "apply", "assess",
    "assist", "attend", "automate", "build", "calculate", "chair", "choose", "coach", "code",
    "collaborate", "collect", "compile", "complete", "compute", "conduct", "configure",
    "construct", "contribute", "convert", "coordinate", "create", "curate", "debug",
    "define", "deliver", "demonstrate", "deploy", "design", "develop", "direct", "draft",
    "edit", "engineer", "establish", "evaluate", "examine", "execute", "expand", "explore",
    "extract", "facilitate", "find", "fix", "gather", "generate", "give", "guide", "handle",
    "help", "identify", "implement", "improve", "increase", "integrate", "interview",
    "investigate", "lead", "learn", "maintain", "manage", "measure", "mentor", "migrate",
    "model", "monitor", "optimise", "optimize", "organise", "organize", "perform", "plan",
    "prepare", "present", "process", "produce", "program", "propose", "prototype",
    "publish", "reduce", "refactor", "report", "represent", "research", "review", "run",
    "scale", "set", "simulate", "solve", "speak", "streamline", "study", "supervise",
    "support", "synthesise", "synthesize", "teach", "test", "train", "translate", "tutor",
    "use", "validate", "visualise", "visualize", "volunteer", "win", "work", "write",
})
_IRREGULAR_PAST = frozenset({
    "built", "chose", "drew", "found", "gave", "held", "kept", "led", "made", "met", "ran",
    "saw", "set", "spoke", "taught", "took", "won", "wrote", "began", "brought", "did",
    "got", "put", "read", "sold", "sent", "spent", "understood", "oversaw", "undertook",
})
#: Openings a prefix cannot make grammatical, or would change the claim of:
#: "we" -> solo work, duty phrases, and prepositions.
_NOT_PREFIXABLE = frozenset({
    "we", "our", "my", "us", "responsible", "duties", "tasks", "in", "on", "at", "for",
    "with", "as", "during", "under", "from", "by", "to",
})
#: First words lower-cased after an opening. Everything else keeps its case,
#: because a capital is often a name ("Python scripts", "PyTorch models").
_LOWERCASE_FIRST = frozenset({
    "a", "an", "the", "this", "these", "those", "one", "two", "three", "four", "five",
    "several", "multiple", "various", "some", "each", "all", "both", "new", "over", "more",
})
_NOMINAL_ENDINGS = ("ment", "tion", "sion", "ance", "ence", "ing", "ysis")

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_LABEL = re.compile(r"^[^:]{1,30}:\s")
_FIRST_PERSON = re.compile(r"I\s+([A-Za-z][A-Za-z'-]*)(.*)$", re.DOTALL)


def _is_verb(word: str) -> bool:
    w = word.casefold()
    return (
        w in _VERB_BASES
        or w in _IRREGULAR_PAST
        or w.endswith("ed")
        or (w.endswith("es") and w[:-2] in _VERB_BASES)
        or (w.endswith("s") and w[:-1] in _VERB_BASES)
    )


def needs_opener(bullet: str) -> bool:
    text = bullet.strip()
    first = _WORD.match(text)
    if first is None or _LABEL.match(text):
        return False
    word = first.group().casefold()
    return word != "i" and word not in _NOT_PREFIXABLE and not _is_verb(word)


def without_first_person(bullet: str) -> str | None:
    """'I built X' -> 'Built X'. Deletes the pronoun and adds nothing: the line
    already said the student did it."""
    match = _FIRST_PERSON.match(bullet.strip())
    if match is None or not _is_verb(match.group(1)):
        return None
    verb = match.group(1)
    return verb[0].upper() + verb[1:] + match.group(2)


def allowed_openers(entry_text: str) -> tuple[str, ...]:
    words = {word.casefold() for word in _WORD.findall(entry_text)}
    strength = max(
        (level for level, forms in _STRENGTH_FORMS.items() if words & forms), default=1
    )
    return tuple(opener.id for opener in OPENERS if opener.strength <= strength)


def compose(bullet: str, opener_id: str, *, present: bool) -> str | None:
    """The opening plus the student's line. Only the first letter's case can
    change; None when the result would exceed a Bullet's limit."""
    opener = BY_ID[opener_id]
    text = bullet.strip()
    first = _WORD.match(text)
    word = first.group().casefold() if first else ""
    lower = word in _LOWERCASE_FIRST or word.endswith(_NOMINAL_ENDINGS)
    tail = text[0].lower() + text[1:] if lower else text
    new = f"{opener.present if present else opener.past} {tail}"
    return new if len(new) <= _MAX_BULLET else None


@dataclass(frozen=True)
class Flagged:
    subject: str
    text: str
    allowed: tuple[str, ...]
    present: bool


def is_english(content: CVContent) -> bool:
    if (content.document_language or "en").split("-")[0].strip().casefold() != "en":
        return False
    return detect_language(" ".join(b for e in content.experience for b in e.bullets)) == "en"


def flagged_bullets(content: CVContent) -> tuple[Flagged, ...]:
    if not is_english(content):
        return ()
    found: list[Flagged] = []
    for entry in content.experience:
        allowed = allowed_openers(" ".join((entry.title, *entry.bullets)))
        for bullet in entry.bullets:
            if needs_opener(bullet):
                found.append(
                    Flagged(
                        subject_of(VERB_OPENER, bullet),
                        bullet,
                        allowed,
                        entry.end_date is None,
                    )
                )
    return tuple(found[:MAX_BULLETS])


def _question(item: Flagged, key: str) -> Choice:
    return Choice(
        question=_QUESTION,
        options=(*item.allowed, LEAVE),
        criteria={
            **{oid: f"Start the line with '{BY_ID[oid].past}'." for oid in item.allowed},
            LEAVE: "Keep the line exactly as written.",
        },
        inspect=f"`bullets.{key}`",
    )


def _cache_key(student_id: UUID, item: Flagged) -> str:
    digest = hashlib.sha256(
        f"{QUESTION_VERSION}\x00{item.text}\x00{','.join(item.allowed)}".encode()
    ).hexdigest()
    return f"cv-verb:{student_id}:{digest}"


def choose_openers(
    items: Sequence[Flagged], *, student_id: UUID, client: Client | None = None
) -> dict[str, str]:
    """subject -> opener id for every line Jev placed an allowed opening on with
    confidence. Anything else -- doubt, leave_unchanged, the gate off, the
    limiter, an unavailable provider -- keeps the line as written.

    Jev sees each bullet's text and nothing else: no name, no employer, no other
    line. record=False: DecisionRecord is shared-catalog data, and this state is
    one student's text (decisions.ask's own rule).
    """
    if not items or not settings.CV_VERB_JEV_ENABLED or provider_for(DECISION) != "typesafe":
        return {}
    chosen: dict[str, str] = {}
    todo: list[Flagged] = []
    for item in items:
        hit = cache.get(_cache_key(student_id, item))
        if hit is None:
            todo.append(item)
        elif hit != LEAVE:
            chosen[item.subject] = hit
    if not todo:
        return chosen
    if rate_limited("cv-verb", student_id, limit=_RATE_LIMIT, window_seconds=_RATE_WINDOW_SECONDS):
        logger.info("cv verb openers rate limited: %d lines left as written", len(todo))
        return chosen
    try:
        answers = ask(
            {"bullets": {f"b{n}": item.text for n, item in enumerate(todo)}},
            {f"b{n}": _question(item, f"b{n}") for n, item in enumerate(todo)},
            decision=DECISION,
            record=False,
            client=client,
        )
    except DecisionsUnavailable as error:
        logger.warning(
            "cv verb openers unavailable (%s): %d lines left as written",
            error.kind,
            len(todo),
        )
        return chosen
    for n, item in enumerate(todo):
        answer = answers[f"b{n}"]
        value = (
            str(answer.value)
            if answer.confidence >= BAR and answer.value in item.allowed
            else LEAVE
        )
        cache.set(_cache_key(student_id, item), value, _CACHE_SECONDS)
        if value != LEAVE:
            chosen[item.subject] = value
    return chosen


def verb_fixes(
    content: CVContent,
    *,
    student_id: UUID,
    undone: frozenset[str],
    client: Client | None = None,
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Apply §5.1 to every experience bullet. 'I <verb>' is fixed by code; a
    flagged line gets Jev's opening when Jev chose one; every other line is
    untouched. An undone fix is listed and not applied."""
    if not is_english(content):
        return content, ()
    items = flagged_bullets(content)
    chosen = choose_openers(items, student_id=student_id, client=client)
    by_text = {item.text: item for item in items}
    experience, fixes = [], []
    for i, entry in enumerate(content.experience):
        bullets: list[str] = []
        for j, bullet in enumerate(entry.bullets):
            new = without_first_person(bullet)
            item = by_text.get(bullet)
            if new is None and item is not None and item.subject in chosen:
                new = compose(bullet, chosen[item.subject], present=entry.end_date is None)
            if new is None or new == bullet:
                bullets.append(bullet)
                continue
            subject = subject_of(VERB_OPENER, bullet)
            was_undone = subject in undone
            fixes.append(
                AppliedFix(
                    VERB_OPENER,
                    subject,
                    f"experience[{i}].bullets[{j}]",
                    bullet,
                    new,
                    undone=was_undone,
                )
            )
            bullets.append(bullet if was_undone else new)
        experience.append(entry.model_copy(update={"bullets": tuple(bullets)}))
    return content.model_copy(update={"experience": tuple(experience)}), tuple(fixes)
