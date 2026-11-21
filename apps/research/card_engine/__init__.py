"""The card-reader engine: one question-set interface over one reader stack (verified-catalog §5).

A question set (funding, application routes §3.4, file rules §3.5) declares closed questions; the
engine puts them to the reader stack over one section of a page and returns typed decisions, each
with a byte-exact quote and where on the page it sits. Code finds the candidates (slice 1,
`apps.research.candidates`); a reader may only point. Nothing here parses a value, groups awards or
stores anything: that is the question set's and the caller's.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from apps.research.candidates import Candidates, Line

#: The values a reader may give without a quote: absence needs no evidence (§5.1, "a yes/no is
#: phrased so that yes means the thing is present"; "every Choice has not_stated or none").
UNQUOTED = frozenset({"no", "not_stated", "none"})
#: A proposal's only value: the answer is the quote itself (§5, "a model may only point").
PROPOSAL = ("quote",)


@dataclass(frozen=True)
class Question:
    """One closed question, English, one property (§5.1). `options` is the closed vocabulary;
    `unquoted` are the options that state an absence and so carry no quote."""

    id: str
    text: str
    options: tuple[str, ...]
    criteria: str = ""
    unquoted: frozenset[str] = UNQUOTED

    def __post_init__(self) -> None:
        if not self.id or not self.text.strip():
            raise ValueError("a question needs an id and text")
        if len(set(self.options)) != len(self.options) or not self.options:
            raise ValueError(f"{self.id}: options must be distinct and non-empty")
        if self.options != PROPOSAL and not set(self.options) & self.unquoted:
            raise ValueError(f"{self.id}: a closed question needs an absence option (§5.1)")


def yes_no(qid: str, text: str, criteria: str = "") -> Question:
    return Question(qid, text, ("yes", "no"), criteria)


def link(qid: str, text: str, section: Section, criteria: str = "") -> Question:
    """A link-candidate question: the answer is one of the section's link keys, or `none`."""
    return Question(qid, text, (*section.links, "none"), criteria)


def proposal(qid: str, text: str, criteria: str = "") -> Question:
    """Ask the readers to point at every span that states something; code keeps the quotes."""
    return Question(qid, text, PROPOSAL, criteria)


_LINK_KEY = re.compile(r"^k[0-9]+$")


@dataclass(frozen=True)
class Link:
    text: str
    url: str


@dataclass(frozen=True)
class Section:
    """What a reader sees: an award's lines with their context lines, headings and links, or the
    whole page. `lang` is the page's language; nothing is translated (§5.3)."""

    title: str
    lang: str
    lines: tuple[Line, ...]
    links: Mapping[str, Link] = field(default_factory=dict)  # "k1" -> Link

    def __post_init__(self) -> None:
        # Link keys become a link question's options and so travel outside the untrusted
        # wrapper, unscreened: page text must never be able to name one.
        if bad := [key for key in self.links if not _LINK_KEY.fullmatch(key)]:
            raise ValueError(f"link keys must look like k1, k2, ...: {len(bad)} do not")

    def texts(self) -> frozenset[str]:
        """Every piece of page text a reader would see -- what D8 must have screened."""
        parts = {self.title}
        for item in self.links.values():
            parts.update((item.text, item.url))  # a URL reaches the reader too
        for line in self.lines:
            parts.update((line.text, line.header, line.heading))
        return frozenset(p for p in parts if p)


@dataclass(frozen=True)
class Quote:
    text: str
    where: str  # "L3.text", "L3.header", "L3.heading", "title" or a link key "k2"


def locate(quote: str, section: Section) -> Quote | None:
    """Where `quote` sits, byte for byte, or None. No normalisation of any kind: a quote that
    differs from the page in whitespace, case or Unicode form is not on the page (§5).

    A quote whose stripped text is under 2 characters ("", " ", "\n", "a") is not evidence and is
    never located; whitespace inside an otherwise valid quote is kept and matched as given.
    A link answer's evidence is its anchor text, never its URL: only `Link.text` is searched,
    although the URL is shown to readers (`Section.texts`)."""
    if len(quote.strip()) < 2:
        return None
    for n, line in enumerate(section.lines):
        for part in ("text", "header", "heading"):
            if quote in getattr(line, part):
                return Quote(quote, f"L{n}.{part}")
    if quote in section.title:
        return Quote(quote, "title")
    for key, item in section.links.items():
        if quote in item.text:
            return Quote(quote, key)
    return None


@dataclass(frozen=True)
class ReaderAnswer:
    """What one reader said. `value` None means it gave no usable answer; `dropped` says why:
    `missing` (absent, or answered more than once), `off_vocabulary`, `quote_not_on_page`,
    `quote_not_on_link` (a link answer whose quote is not in that link's anchor text) or
    `rate_limited` (the decider was never called)."""

    value: str | None
    quote: Quote | None = None
    dropped: str = ""


Status = Literal["agreed", "decided", "unresolved"]


@dataclass(frozen=True)
class Decision:
    """`agreed`: both cheap readers gave the same value. `decided`: they did not, and the deciding
    reader answered. `unresolved`: it did not either -- the caller hunts, then holds (§5.5)."""

    question: str
    status: Status
    value: str | None
    quote: Quote | None
    answers: Mapping[str, ReaderAnswer]  # reader name -> what it said, the decider only if asked


@dataclass(frozen=True)
class Call:
    """One attempt, or a refused one (`rate_limited`: no call, no cost). Never the prompt or the
    answer: counts, cost and time only."""

    reader: str
    model: str
    attempt: int
    ok: bool
    #: "" when ok; "extra_ids" (ok, but the reply answered ids that were not asked and they were
    #: ignored); else "off_schema", "truncated", "refusal", "not_configured", "failed:<Type>",
    #: "failed:http_<n>", "failed:provider_error", or "rate_limited" (no call was made)
    reason: str
    cost_usd: float | None  # the vendor's own figure; None when it reported none or is unpriced
    latency_s: float


@dataclass(frozen=True)
class Limit:
    """The `apps.ratelimit.rate_limited` bucket every model call is counted in."""

    bucket: str
    actor_id: UUID | int
    limit: int
    window_seconds: int


class QuestionSet(Protocol):
    """What a question set declares. The engine never knows which one it reads.

    A question refers to page text by key (c3, L4), never by embedding page text in
    `Question.text` or `criteria`: those travel outside the untrusted wrapper and are not
    screened by D8. Question ids must be unique within `proposals()` and within `questions()`."""

    name: str
    version: str
    criteria: str  # the set's definitions, sent with every call (§5.2.1)

    def proposals(self, section: Section) -> Sequence[Question]: ...

    def questions(
        self, section: Section, candidates: Candidates, proposed: Mapping[str, tuple[Quote, ...]]
    ) -> Sequence[Question]: ...
