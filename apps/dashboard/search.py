"""One search box over the student's own dashboard (`/student/search/?q=`).

Read-only, and it reads exactly what the student's screens already read -- the
same functions, so a result can never show something its page would not:

- programmes and funding: `funding.views._pack_context` (the pack and the other
  options, with the provenance gate the Programmes page applies);
- applications: `board_for` (the cards on Home);
- documents: `documents.views.page_context` (the documents table and CV drafts);
- messages: `concierge.views.messages_context` (counsellor thread and mail).

All of it is tenant-side rows the worker wrote. Nothing here touches a catalogue
table, which the web role has no grant on (CLAUDE.md, "the catalogue boundary is
a GRANT"); `tests/dashboard/test_search.py` pins that with `reads_no_catalogue`.

Matching is plain: every word of the query must appear (case-insensitive) in a
result's text. No ranking model, no index -- the student's data is small.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from apps.tenancy.models import Membership

if TYPE_CHECKING:
    from apps.funding.models import PackCandidate, RecommendationCandidate

MIN_QUERY = 2
MAX_QUERY = 100
PER_KIND = 25


@dataclass(frozen=True)
class Result:
    kind: str
    title: str
    detail: str
    url: str


@dataclass(frozen=True)
class Group:
    kind: str
    results: tuple[Result, ...]


def terms(query: str) -> tuple[str, ...]:
    """The lower-cased words of a query, or () when it is too short to search."""
    cleaned = " ".join(query.split())[:MAX_QUERY]
    if len(cleaned) < MIN_QUERY:
        return ()
    return tuple(word.casefold() for word in cleaned.split(" "))


def matches(words: tuple[str, ...], *texts: object) -> bool:
    haystack = " ".join(str(text) for text in texts if text).casefold()
    return bool(words) and all(word in haystack for word in words)


_PAGES = (
    ("Home", "Your applications, deadlines and what needs you now", "/student/"),
    ("Programmes & funding", "Your pack and other options", "/student/recommendation/"),
    ("Documents", "Uploads, CV and what each application needs", "/student/documents/"),
    ("Messages", "Your counsellor and mail from universities", "/student/messages/"),
    ("Settings", "Profile, mailbox, browser extension and account", "/student/settings/"),
    ("Profile", "Your consultation answers", "/student/profile/"),
    ("Mailbox", "The inbox we watch for university replies", "/student/settings/mailbox/"),
    (
        "Browser extension",
        "The browsers that fill your applications",
        "/student/settings/extension/",
    ),
    ("Account", "Leave and delete your data", "/student/settings/account/"),
)


def _programmes(student: Membership, words: tuple[str, ...]) -> list[Result]:
    from apps.funding.views import _pack_context

    context = _pack_context(student)
    pool = cast("list[PackCandidate]", context["pool"])
    in_pack = [member.candidate for member in pool]
    others = list(cast("Iterable[RecommendationCandidate]", context["considered"]))
    out: list[Result] = []
    for where, candidates in (("In your pack", in_pack), ("Other options", others)):
        for candidate in candidates:
            if not matches(
                words, candidate.program_name, candidate.institution_name, candidate.country_code
            ):
                continue
            is_award = candidate.opportunity_id is not None
            place = " · ".join(p for p in (candidate.institution_name, candidate.country_code) if p)
            out.append(
                Result(
                    kind="Funding" if is_award else "Programmes",
                    title=candidate.program_name,
                    detail=" · ".join(p for p in (where, place) if p),
                    url=f"/student/recommendation/#candidate-{candidate.id}",
                )
            )
    return out


def _applications(student: Membership, words: tuple[str, ...]) -> list[Result]:
    from .board import board_for

    out = []
    for card in board_for(student).cards:
        if matches(
            words, card.title, card.institution, card.country, card.column.value, *card.missing
        ):
            out.append(
                Result(
                    kind="Applications",
                    title=card.title,
                    detail=" · ".join(
                        p for p in (card.column.value, card.institution, card.country) if p
                    ),
                    url=f"/student/applications/#card-{card.application_id}",
                )
            )
    return out


def _documents(student: Membership, words: tuple[str, ...]) -> list[Result]:
    from apps.documents.views import page_context

    context = page_context(student, counselor_view=False)
    table = context["table"]
    out = []
    for row in table.rows:  # type: ignore[attr-defined]
        states = sorted({str(cell) for cell in row.cells})
        if matches(words, row.label, *states):
            out.append(
                Result(
                    kind="Documents",
                    title=row.label,
                    detail=", ".join(states) if states else "",
                    url="/student/documents/",
                )
            )
    for draft in context["drafts"]:  # type: ignore[attr-defined]
        label = f"CV version {draft.version}"
        if matches(words, label, "cv", "curriculum vitae", draft.get_status_display()):
            out.append(
                Result(
                    kind="Documents",
                    title=label,
                    detail=draft.get_status_display(),
                    url="/student/documents/",
                )
            )
    return out


def _messages(student: Membership, words: tuple[str, ...]) -> list[Result]:
    from apps.concierge.views import messages_context

    context = messages_context(student)
    out = []
    for message in context["conversation"]:  # type: ignore[attr-defined]
        if matches(words, message.body):
            who = "You" if message.sender_id == message.student_id else "Counsellor"
            body = " ".join(message.body.split())
            out.append(
                Result(
                    kind="Messages",
                    title=body[:90] + ("…" if len(body) > 90 else ""),
                    detail=f"{who}, {message.created_at:%d %b %H:%M}",
                    url="/student/messages/",
                )
            )
    for title, rows in context["mail_groups"]:  # type: ignore[attr-defined]
        for row in rows:
            signal = row.signal
            if matches(
                words, signal.sender_domain, signal.document_name, signal.offered_programme, title
            ):
                out.append(
                    Result(
                        kind="Messages",
                        title=f"Mail from {signal.sender_domain}",
                        detail=" · ".join(
                            p for p in (title, signal.document_name, signal.offered_programme) if p
                        ),
                        url="/student/messages/#messages",
                    )
                )
    return out


def search(student: Membership, query: str) -> tuple[Group, ...]:
    """Results grouped by kind, in the order the sidebar lists the pages."""
    words = terms(query)
    if not words:
        return ()
    found = [
        *_applications(student, words),
        *_programmes(student, words),
        *_documents(student, words),
        *_messages(student, words),
        *(
            Result(kind="Pages", title=title, detail=detail, url=url)
            for title, detail, url in _PAGES
            if matches(words, title, detail)
        ),
    ]
    order = ("Applications", "Programmes", "Funding", "Documents", "Messages", "Pages")
    return tuple(
        Group(kind, tuple(r for r in found if r.kind == kind)[:PER_KIND])
        for kind in order
        if any(r.kind == kind for r in found)
    )
