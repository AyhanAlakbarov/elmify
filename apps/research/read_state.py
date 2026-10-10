"""What reading each body a closed list names came to.

"100% enumerated with read states recorded" (spec 16 item 7) is two claims,
and this module is the arithmetic behind both:

- enumerated: every row is bound to an Organisation, and the row count equals
  the count the publisher prints, where it prints one;
- read state recorded: every row carries one word from a closed set saying
  what reading it came to -- including "could not look" and "not read, by
  rule" -- never a blank.

The word is DERIVED from records other code already writes (snapshots and
their `funding_read_at` / `readability`, the classifier's columns, the fetch
trail) and then stored on the entry. So the coverage line is a query, and no
number a person typed can satisfy the gate.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from django.conf import settings
from django.db.models import Max, Q, QuerySet

from apps.funding.models import OfficialSource, OfficialSourceSnapshot

from .closed_lists import has_signal
from .fetch.types import Outcome
from .models import ClosedList, FetchAttempt, Organisation, RegisterEntry


class ReadState(StrEnum):
    #: The list names a body no row holds -- the enumeration half of the gate.
    UNBOUND = "UNBOUND"
    #: Two keys named two bodies; a person decides (spec 11, build item 12).
    CONFLICT = "CONFLICT"
    #: A platform operator said the row names no funder, or no body at all
    #: (the resolution queue's SITE_UNKNOWN). An answer, so not failing: the
    #: row is decided, and there is nothing to bind or read. Detail = reason.
    REFUSED = "REFUSED"
    REJECTED = "REJECTED"
    FUNDING_READ = "FUNDING_READ"
    CLASSIFIED = "CLASSIFIED"
    #: The classifier read the homepage and would not commit. Read, undecided.
    ABSTAINED = "ABSTAINED"
    #: Fetched, and nothing could be read: a shell, a soft 404, a scan.
    UNREADABLE = "UNREADABLE"
    #: The host stopped us (blocked, unreachable, dead, off-site, retry due).
    COULD_NOT_LOOK = "COULD_NOT_LOOK"
    #: SIGNAL_ONLY and no signal: known, deliberately not read (owner 2026-09-23).
    GATED = "GATED"
    #: ENUMERATE_ONLY: the row routes other work; nothing here reads it.
    ENUMERATED = "ENUMERATED"
    #: Nothing attempted, or our own budget stopped it -- the read half of the gate.
    UNREAD = "UNREAD"


_FAILING = frozenset({ReadState.UNBOUND, ReadState.UNREAD})
_HOST_REFUSED = frozenset({
    Outcome.BLOCKED, Outcome.UNREACHABLE, Outcome.DEAD, Outcome.OFF_SITE,
    Outcome.INVALID, Outcome.RETRY_SCHEDULED,
})


@dataclass(frozen=True)
class EntryState:
    state: ReadState
    detail: str = ""


def _domains(org: Organisation) -> list[str]:
    return list(org.domains.values_list("registrable_domain", flat=True))


def _snapshots_on(org: Organisation) -> QuerySet[OfficialSourceSnapshot]:
    """Every snapshot of a page on any of the body's registrable domains --
    a hop inside its own site is still its page."""
    match = Q()
    for domain in _domains(org):
        match |= Q(publisher=domain) | Q(publisher__endswith=f".{domain}")
    if not match:
        return OfficialSourceSnapshot.objects.none()
    return OfficialSourceSnapshot.objects.filter(source__in=OfficialSource.objects.filter(match))


def _from_attempt(urls: list[str]) -> EntryState | None:
    attempt = FetchAttempt.objects.filter(url__in=urls).order_by("-created_at").first()
    if attempt is None:
        return None
    if attempt.outcome == Outcome.BUDGET:
        return EntryState(ReadState.UNREAD, "budget")
    if attempt.outcome == Outcome.UNREADABLE:
        return EntryState(ReadState.UNREADABLE, "fetch")
    if attempt.outcome in _HOST_REFUSED:
        return EntryState(ReadState.COULD_NOT_LOOK, attempt.outcome)
    return None


def _funding_state(entry: RegisterEntry, org: Organisation) -> EntryState:
    """FUNDING_READ when the entry's own scheme page was funding-read.

    A read of another page on the body's site also counts -- the reader
    follows funding links from the scheme page (pipeline.funding_links) --
    but only when this is the body's ONLY scheme on the list. A body with two
    schemes (one entry per scheme, Task 5) would otherwise read both as done
    when one page was read. Unreadable is judged on the entry's own page for
    the same reason: an unrelated shell elsewhere on the domain says nothing
    about this scheme.
    """
    snapshots = _snapshots_on(org)
    own = snapshots.filter(source__canonical_url=entry.page_url)
    read = snapshots.filter(funding_read_at__isnull=False)
    sole_scheme = not (
        RegisterEntry.objects.filter(register=entry.register, organisation=org)
        .exclude(page_url="").exclude(pk=entry.pk).exists()
    )
    if own.filter(funding_read_at__isnull=False).exists() or (sole_scheme and read.exists()):
        pages = read.values("source").distinct().count()
        return EntryState(ReadState.FUNDING_READ, f"{pages} pages")
    unreadable = (
        own.exclude(readability=OfficialSourceSnapshot.Readability.OK)
        .order_by("-retrieved_at").values_list("readability", flat=True).first()
    )
    if unreadable:
        return EntryState(ReadState.UNREADABLE, unreadable)
    return _from_attempt([entry.page_url]) or EntryState(ReadState.UNREAD)


def _classify_state(org: Organisation) -> EntryState:
    if org.classified_at is not None:
        return EntryState(ReadState.CLASSIFIED, org.classified_by)
    if org.classifier_confidence is not None:
        return EntryState(ReadState.ABSTAINED, f"{org.classifier_confidence:.2f}")
    if org.pages_unreadable:
        return EntryState(ReadState.UNREADABLE, "homepage")
    home = [f"https://{org.primary_domain}/", f"https://{org.primary_domain}"]
    return _from_attempt(home) or EntryState(ReadState.UNREAD)


def entry_read_state(entry: RegisterEntry, policy: str) -> EntryState:
    if entry.resolution == RegisterEntry.Resolution.CONFLICT:
        return EntryState(ReadState.CONFLICT)
    if entry.resolution == RegisterEntry.Resolution.REFUSED:
        return EntryState(ReadState.REFUSED, entry.refused_reason)
    if policy == ClosedList.ReadPolicy.ENUMERATE_ONLY:
        return EntryState(ReadState.ENUMERATED)
    org = entry.organisation
    if org is None:
        return EntryState(ReadState.UNBOUND, entry.resolution)
    if org.status == Organisation.Status.REJECTED:
        return EntryState(ReadState.REJECTED, org.rejected_reason)
    if policy == ClosedList.ReadPolicy.SIGNAL_ONLY and not has_signal(org):
        return EntryState(ReadState.GATED)
    if policy == ClosedList.ReadPolicy.CLASSIFY:
        return _classify_state(org)
    return _funding_state(entry, org)


def _record_body_read(org: Organisation) -> None:
    """Spec 6.1's latest-state read fields, from the same snapshots."""
    read = _snapshots_on(org).filter(funding_read_at__isnull=False)
    last = read.aggregate(last=Max("funding_read_at"))["last"]
    pages = read.values("source").distinct().count()
    if (org.last_read_at, org.pages_read) != (last, pages):
        org.last_read_at, org.pages_read = last, pages
        org.save(update_fields=["last_read_at", "pages_read"])


def record_read_states(slug: str, *, now: datetime) -> Counter[str]:
    policy = ClosedList.objects.values_list("read_policy", flat=True).get(slug=slug)
    tally: Counter[str] = Counter()
    for entry in RegisterEntry.objects.filter(register=slug).select_related("organisation"):
        found = entry_read_state(entry, policy)
        tally[found.state] += 1
        detail = found.detail[:120]
        if (entry.read_state, entry.read_state_detail) != (found.state, detail):
            entry.read_state, entry.read_state_detail, entry.read_state_at = (
                found.state, detail, now,
            )
            entry.save(update_fields=["read_state", "read_state_detail", "read_state_at"])
        if found.state == ReadState.FUNDING_READ and entry.organisation is not None:
            _record_body_read(entry.organisation)
    return tally


@dataclass(frozen=True)
class ListGate:
    slug: str
    listed: int
    printed_size: int | None
    bodies_known: int
    states: dict[str, int]
    stale: bool

    @property
    def enumerated(self) -> bool:
        return self.listed > 0 and (self.printed_size is None or self.listed == self.printed_size)

    @property
    def passed(self) -> bool:
        return self.enumerated and not any(self.states.get(state, 0) for state in _FAILING)


def list_gate(slug: str, *, now: datetime) -> ListGate:
    spec = ClosedList.objects.get(slug=slug)
    states = record_read_states(slug, now=now)
    entries = RegisterEntry.objects.filter(register=slug)
    return ListGate(
        slug=slug,
        listed=entries.count(),
        printed_size=spec.printed_size,
        bodies_known=entries.filter(organisation__isnull=False)
        .values("organisation").distinct().count(),
        states=dict(states),
        stale=now.date() - spec.verified_on > timedelta(days=settings.CLOSED_LIST_RECHECK_DAYS),
    )
