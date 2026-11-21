"""What a reading must pass before anything is kept (CV evidence spec §7.4).

Run in the refresh while the evidence text is still in memory:

1. Quotes. Every bullet span, technique excerpt and name must be in the
   evidence after whitespace and case are normalised (reader.verified_statements'
   rule, over the whole text: README prose wraps mid-sentence). A bullet with
   no surviving span is dropped.
2. Numbers. Every number in a bullet must be in that bullet's own spans; in
   methods, outcomes and the summary, in the evidence. Known limit: numbers
   written as words, and small integers a year or version makes trivially
   present, are not caught.
3. Support. Always on (owner, 2026-10-15: TypeSafe's DPA is accepted). Jev is
   asked one closed question per surviving bullet, sent only the bullet and
   its own spans, never cached (record=False). Verdict: supported (yes at
   >= 0.9), rejected (no, unsure, or below 0.9), unchecked (the call failed or
   hit the evidence-support limit).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from uuid import UUID

from apps.ratelimit import rate_limited
from apps.research.decisions import (
    Choice,
    Client,
    DecisionBudgetExhausted,
    DecisionsUnavailable,
    StateTooLarge,
    ask,
    provider_for,
)
from apps.research.reader import normalize

from .extraction import RepoReading, Technique

logger = logging.getLogger(__name__)

SUPPORT_DECISION = "evidence_support"
SUPPORT_BAR = 0.9
SUPPORT_LIMIT = 60
SUPPORT_WINDOW_SECONDS = 3600
_QUESTION = Choice(
    question="Does this evidence support this sentence?",
    options=("yes", "no", "unsure"),
    criteria={
        "yes": "every claim in `sentence` is stated in `evidence`",
        "no": "`sentence` claims something `evidence` does not state",
        "unsure": "`evidence` neither clearly supports nor contradicts `sentence`",
    },
)
#: Digits with separators and a %, k, M or B unit: 10B, 3.88M, 92%, 1,000.
#: Not preceded by a letter, so "v2" (a version) is not a claim. A leading minus and a
#: leading-dot decimal belong to the number: "-3" is not "3", ".95" is a claim.
_NUMBER = re.compile(r"(?<![\w.])-?\.?\d++(?:[.,]\d++)*+(?:%|[kmb](?![a-z]))?", re.IGNORECASE)
_UNIT_GAP = re.compile(r"(\d)\s+(%|[kKmMbB])(?![A-Za-z])")
_EVIDENCE_AI_SLOP_RE = re.compile(
    r"\u2014"
    r"|,\s+(?:highlighting|underscoring|showcasing|demonstrating|illustrating|reflecting|"
    r"cementing|solidifying|emphasizing|emphasising|reinforcing)\b"
    r"|\b(?:delve|delves|delved|delving|tapestry|testament\s+to|pivotal\s+moment|"
    r"evolving\s+landscape|spearheaded|spearheading|underscores|underscored|underscoring|"
    r"showcases|showcased|showcasing|meticulous|meticulously|bolstered|bolstering)\b",
    re.IGNORECASE,
)


def _has_ai_slop(text: str, evidence: str = "") -> bool:
    """True when `text` introduces an em dash, participial trailer, or AI stock phrase
    not present in `evidence`."""
    for match in _EVIDENCE_AI_SLOP_RE.finditer(text):
        token = match.group(0)
        if not evidence or token.casefold() not in evidence.casefold():
            return True
    return False


def _numbers(text: str) -> set[str]:
    return {m.group(0).casefold() for m in _NUMBER.finditer(_UNIT_GAP.sub(r"\1\2", text))}


def numbers_supported(text: str, source: str) -> bool:
    """Every number `text` states also appears in `source`, unit included."""
    return _numbers(text) <= _numbers(source)


@dataclass(frozen=True)
class CheckedBullet:
    text: str
    evidence: tuple[str, ...]
    verdict: str = "unchecked"


@dataclass(frozen=True)
class Checked:
    summary: str
    kind: str
    bullets: tuple[CheckedBullet, ...]
    methods: str | None
    outcomes: str | None
    techniques: tuple[Technique, ...]
    names: tuple[str, ...]
    #: Bullets the quote or number check removed (logged, never stored).
    dropped: int

    def to_json(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "kind": self.kind,
            "bullets": [
                {"text": b.text, "evidence": list(b.evidence), "verdict": b.verdict}
                for b in self.bullets
            ],
            "methods": self.methods,
            "outcomes": self.outcomes,
            "techniques": [{"name": t.name, "excerpt": t.excerpt} for t in self.techniques],
            "names": list(self.names),
        }


def check(reading: RepoReading, evidence: str) -> Checked:
    haystack = normalize(evidence)

    def quoted(span: str) -> bool:
        key = normalize(span)
        if not key:
            return False
        # Word edges, so a span cannot start or end inside a word or a number
        # ("88M" in "3.88M", "500" in "1,500", "MIT" in "submitted").
        head = r"(?<![\w.,])" if key[0].isalnum() else ""
        tail = r"(?!\w)" if key[-1].isalnum() else ""
        return re.search(head + re.escape(key) + tail, haystack) is not None

    def kept(text: str | None) -> str | None:
        return (
            text
            if text is not None
            and numbers_supported(text, evidence)
            and not _has_ai_slop(text, evidence)
            else None
        )

    bullets: list[CheckedBullet] = []
    for bullet in reading.bullets:
        spans = tuple(span for span in bullet.evidence if quoted(span))
        # Per span, never joined: "ranked 1" + "M parameter" must not make "1M".
        if (
            spans
            and _numbers(bullet.text) <= set().union(*(_numbers(span) for span in spans))
            and not _has_ai_slop(bullet.text, evidence)
        ):
            bullets.append(CheckedBullet(text=bullet.text, evidence=spans))
    return Checked(
        summary=kept(reading.summary) or "",
        kind=reading.kind,
        bullets=tuple(bullets),
        methods=kept(reading.methods),
        outcomes=kept(reading.outcomes),
        techniques=tuple(t for t in reading.techniques if quoted(t.excerpt)),
        names=tuple(name for name in reading.names if quoted(name)),
        dropped=len(reading.bullets) - len(bullets),
    )


def _verdict(bullet: CheckedBullet, student_id: UUID, client: Client | None) -> str:
    if rate_limited(
        "evidence-support", student_id, limit=SUPPORT_LIMIT, window_seconds=SUPPORT_WINDOW_SECONDS
    ):
        return "unchecked"
    try:
        answers = ask(
            {"sentence": bullet.text, "evidence": list(bullet.evidence)},
            {"support": _QUESTION},
            decision=SUPPORT_DECISION,
            # Never cached: DecisionRecord is shared-catalog data and this is student text.
            record=False,
            client=client,
        )
    except (DecisionsUnavailable, DecisionBudgetExhausted, StateTooLarge) as error:
        logger.warning("EvidenceSupportUnchecked error=%s", type(error).__name__)
        return "unchecked"
    answer = answers["support"]
    return "supported" if answer.value == "yes" and answer.confidence >= SUPPORT_BAR else "rejected"


def support(checked: Checked, *, student_id: UUID, client: Client | None = None) -> Checked:
    """A verdict on every surviving bullet. Student text goes to Jev only: a mapping that
    routes this decision anywhere else leaves every bullet unchecked."""
    if not checked.bullets:
        return checked
    if provider_for(SUPPORT_DECISION) != "typesafe":
        logger.error("EvidenceSupportMisrouted: DECISIONS_PROVIDER does not route %s to typesafe",
                     SUPPORT_DECISION)
        return checked
    bullets = tuple(
        replace(bullet, verdict=_verdict(bullet, student_id, client)) for bullet in checked.bullets
    )
    return replace(checked, bullets=bullets)
