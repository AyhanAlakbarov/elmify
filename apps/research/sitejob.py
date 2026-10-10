# apps/research/sitejob.py
"""The funnel: find the pages that state a programme's requirements.

Design: docs/superpowers/specs/2026-09-22-fetch-engine-design.md 7.0-7.6.

Five stages, cheapest first, and **every stage returns URLs and nothing else**.
Each URL is fetched through the engine's own ladder and checked against the
institution's origin, so no vendor's reading of a page is ever kept, whichever
stage found it -- the rule CLAUDE.md already states for Exa and Brave, and the
reason the owner could permit /agent's open-web search on 2026-09-23 without
needing a vendor flag to confine it.

**Reading never stops; only paying does.** The stop rule decides whether the
dearer stages are bought. Every page a stage found is read in full either way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .harvest import anchors

__all__ = [
    "DOCUMENT_SUFFIXES",
    "Lead",
    "PageRead",
    "ProgrammeOutcome",
    "SiteJobResult",
    "Stage",
    "document_links",
    "guided_instruction",
    "navigator_brief",
    "navigator_policy",
]


class Stage(IntEnum):
    """The funnel's five stages, in the order they are paid for (spec 7.0)."""

    DOCUMENTS = 1
    MAP = 2
    GUIDED_MAP = 3
    NAVIGATOR = 4
    RECORD = 5


class ProgrammeOutcome(StrEnum):
    """The four outcomes of spec 7.6, each carrying evidence."""

    FOUND = "found"
    NO_CV_REQUIRED = "no_cv_required"
    BLOCKED = "blocked"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class Lead:
    """One URL a stage produced. `kind` and `why` are the vendor's words where
    a vendor had any; they are logged and NEVER persisted -- provenance comes
    from the origin we fetched, never from the provider that pointed at it."""

    url: str
    stage: Stage
    kind: str = ""
    why: str = ""


@dataclass(frozen=True)
class PageRead:
    """What the reader says about one fetched page.

    The funnel does not read; it asks. `requirements` is how many CV or letter
    requirement sentences the reader selected (D4), `no_cv_required` is D4's
    third Noul, and `documents` is the further document URLs the read found.
    """

    requirements: int = 0
    no_cv_required: bool = False
    documents: tuple[str, ...] = ()


class Reader(Protocol):
    def __call__(self, page: object, *, kind: str) -> PageRead: ...


@dataclass(frozen=True)
class SiteJobResult:
    """The outcome with what was searched -- never a bare label (spec 7.6)."""

    outcome: ProgrammeOutcome
    stopped_at: Stage
    leads: tuple[Lead, ...] = ()
    searched: dict[str, int] = field(default_factory=dict)
    credits: dict[str, int] = field(default_factory=dict)
    reason: str = ""


#: Lowercase and dotted, compared against a casefolded path. Without the dot,
#: `annual-report-pdf.html` is a document.
DOCUMENT_SUFFIXES = (
    ".pdf", ".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xls", ".pptx", ".zip",
)

_POLICIES = frozenset({"on_miss", "always"})


def navigator_policy() -> str:
    policy = str(settings.FETCH_NAVIGATOR_POLICY)
    if policy not in _POLICIES:
        raise ImproperlyConfigured(
            f"FETCH_NAVIGATOR_POLICY is {policy!r}; expected one of {sorted(_POLICIES)}"
        )
    return policy


def document_links(page: object, *, named_files: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Stage 1: the page's own document links, in page order, deduplicated.

    Read off the page's HTML with `harvest.anchors` rather than asking
    Firecrawl for its `links` format. The spec names `links` because it is free
    with rung 1; anchors() reads the same fact from the `html` body rung 1
    already returns (measured on the live gate: 30 anchors on globed.eu through
    Firecrawl), so requesting the format as well would be a second source of
    truth for one fact and a vendor field to keep in step.

    `named_files` is additive and comes from a rule that named a template file
    (typed-decisions 6.6): the suffix list cannot be complete -- a template is
    served from `/download?id=7` often enough -- and a wrong or missing name
    costs a fetch, never a rule.
    """
    found: list[str] = []
    for anchor in anchors(getattr(page, "body", b"")):
        absolute = urljoin(getattr(page, "final_url", ""), anchor.href)
        if not absolute.startswith(("http://", "https://")):
            continue
        path = urlsplit(absolute).path.casefold()
        named = any(name.casefold() in absolute.casefold() for name in named_files)
        if (path.endswith(DOCUMENT_SUFFIXES) or named) and absolute not in found:
            found.append(absolute)
    return tuple(found)


#: Firecrawl's documented ceiling for `prompt`. A 400 from the vendor at
#: stage 4 reads, from outside, as a programme whose pages could not be
#: found, so the brief is truncated by its own builder rather than by them.
_BRIEF_MAX = 10_000
#: How many of each list reaches the brief. A programme with sixteen site
#: languages spends the whole prompt on vocabulary and never states what to
#: find; Firecrawl's own note is that more specific prompts use fewer credits.
_SLOT_ITEMS = 12

_BRIEF = """\
Find the pages and files that state the application requirements for the \
{degree_level} programme "{programme}" at {institution}, intake {intake_year}.

The site is written in {languages}. In those languages the documents are \
called: {document_words}.

What to find: pages or files listing the documents an applicant must submit; \
requirements on a document's length, language, format or template; \
application guidelines; frequently asked questions about applying.

Where to prefer: these domains and their subdomains, in order: {domains}. \
Never an aggregator, a ranking site, a news article or a press release.

What to return: the URLs only. For each, a kind \
(documents_list, cv_guideline, letter_guideline, template, faq, other) and a \
one-line reason. Do not summarise the requirements themselves -- we read the \
pages ourselves from the institution's own server."""

_INSTRUCTION = """\
Find the pages and files listing the documents an applicant must submit for \
the {degree_level} programme "{programme}" at {institution} (intake \
{intake_year}), including requirements on their length, language, format or \
template, in {languages}, where the documents are called {document_words}"""


def _slot(values: Sequence[str]) -> str:
    return ", ".join(values[:_SLOT_ITEMS])


def navigator_brief(
    *,
    programme: str,
    degree_level: str,
    institution: str,
    intake_year: str,
    languages: Sequence[str],
    document_words: Sequence[str],
    domains: Sequence[str],
) -> str:
    """Spec 7.4's brief: one template, seven slots, under 10,000 characters.

    The last line is load-bearing. A summary is a vendor's reading of a page,
    which is the one thing this funnel refuses to keep -- and asking for it
    costs credits Firecrawl bills for, on an answer that is thrown away.
    """
    return _BRIEF.format(
        programme=programme[:200],
        degree_level=degree_level[:60],
        institution=institution[:200],
        intake_year=intake_year[:20],
        languages=_slot(languages),
        document_words=_slot(document_words),
        domains=_slot(domains),
    )[:_BRIEF_MAX]


def guided_instruction(
    *,
    programme: str,
    degree_level: str,
    institution: str,
    intake_year: str,
    languages: Sequence[str],
    document_words: Sequence[str],
    domains: Sequence[str] = (),
) -> str:
    """Spec 7.3a's instruction: the SAME slots as the brief, one sentence.

    Same slots on purpose. Two stages asking for different things cannot be
    compared on the corpus, and comparing them is the reason each stage is
    scored by itself.
    """
    del domains  # named by `select_domains` on the request, not in the sentence
    return _INSTRUCTION.format(
        programme=programme[:200],
        degree_level=degree_level[:60],
        institution=institution[:200],
        intake_year=intake_year[:20],
        languages=_slot(languages),
        document_words=_slot(document_words),
    )
