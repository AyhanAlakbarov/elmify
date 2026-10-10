from __future__ import annotations

import posixpath
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from itertools import zip_longest
from typing import Protocol
from urllib.parse import urldefrag, urlsplit, urlunsplit

from .domains import is_catalogue
from .egress import SourceBlocked
from .fetch import FetchBudgetExhausted, FetchedPage, SweepBudget, fetch_page
from .fetch.types import SERVED, Outcome


class LeadBudgetExceeded(RuntimeError):
    """One source is out of budget. It stops; the run does not (design §2.6)."""


@dataclass
class RunBudget:
    """Hard per-run ceilings that do not depend on the cache backend.

    ``apps.ratelimit.rate_limited`` is a fixed window on Django's cache (Redis/Valkey
    in production, config/settings/production.py). These counters are a separate
    ceiling that holds for one run regardless of the cache backend -- a one-shot
    ``manage.py discover`` process starts every "hourly" window fresh either way,
    so ten invocations inside the same hour would otherwise spend ten times the
    budget; rate_limited stays for the cross-process/cross-deploy case.
    """

    searches: int = 20
    fetches: int = 200
    extractions: int = 100

    def spend(self, kind: str) -> None:
        remaining = int(getattr(self, kind))
        if remaining <= 0:
            raise LeadBudgetExceeded(f"{kind} budget exhausted for this run")
        setattr(self, kind, remaining - 1)


@dataclass(frozen=True)
class LeadIdentity:
    """What a catalogue record tells us about a programme before it is fetched.

    Names and a location -- nothing else. Teaching language and duration are
    claims, not identity: §2.2 enforces teaching language on the extracted,
    cited TeachingLanguageClaim, so a catalogue's own language field must never
    become the value a hard gate reads.
    """

    institution_name: str
    country_code: str
    city: str = ""
    program_name: str = ""
    degree_level: str = "MASTER"


@dataclass(frozen=True)
class ResearchLead:
    canonical_url: str
    source_type: str
    funding_family: str
    evidence_strength: str = "DIRECT"
    visibility: str = "STUDENT_FACING"
    can_route_research: bool = True
    can_support_claim: bool = True
    discovered_by: str = ""
    identity: LeadIdentity | None = None
    #: Whether the source that produced this lead promises one programme per
    #: link. Only such leads may pool their pages' gate facts: a university host
    #: serving forty programmes must never merge one page's institution with
    #: another page's duration. Set by _tagged from the source, never by a
    #: caller -- a lead cannot promote itself, the same way from_url only ever
    #: downgrades source_type.
    one_programme_per_site: bool = False
    #: Whether the source promises that its programmes are awarded by several
    #: universities together. NOT the same claim as one_programme_per_site,
    #: which says one link is one programme: the Korea and Finland registry
    #: sources (pipeline.py) will set that while listing single-provider
    #: programmes. Set by _tagged from the source, never by a caller.
    awards_jointly: bool = False

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        source_type: str,
        funding_family: str,
        evidence_strength: str = "DIRECT",
        discovered_by: str = "",
        identity: LeadIdentity | None = None,
        one_programme_per_site: bool = False,
        awards_jointly: bool = False,
    ) -> ResearchLead:
        canonical = canonicalize_url(url)
        # The host decides, not the caller. A search hit on a catalogue is a
        # catalogue lead: it routes research and cannot support a claim (§7.2).
        if is_catalogue(urlsplit(canonical).hostname or ""):
            source_type = "AGGREGATOR"
        aggregator = source_type.upper() == "AGGREGATOR"
        ecosystem_clue = evidence_strength == "ECOSYSTEM_CLUE"
        can_support_claim = not aggregator and not ecosystem_clue
        return cls(
            canonical,
            source_type,
            funding_family,
            evidence_strength,
            "INTERNAL" if ecosystem_clue else "STUDENT_FACING",
            True,
            can_support_claim,
            discovered_by,
            identity,
            # Same condition as can_support_claim, not just `not aggregator`,
            # so the two cannot drift: a catalogue page is not one programme's
            # site whatever the source promised, and neither is an
            # ECOSYSTEM_CLUE lead, which may not support a claim either
            # (§2.5), the same exclusion _tagged applies below.
            one_programme_per_site and can_support_claim,
            awards_jointly,
        )


@dataclass(frozen=True)
class DiscoveryQuery:
    field: str
    country_code: str
    degree_level: str = "MASTER"
    teaching_languages: tuple[str, ...] = ()
    max_leads: int = 50


class LeadSource(Protocol):
    """One way of producing leads. Three real implementations, no speculation.

    ``name`` is a read-only property, not a settable attribute: every
    implementation is a frozen dataclass, and mypy refuses a frozen field
    against a settable protocol member ("expected settable variable, got
    read-only attribute").
    """

    @property
    def name(self) -> str: ...

    @property
    def one_programme_per_link(self) -> bool: ...

    @property
    def awards_jointly(self) -> bool: ...

    def find(self, query: DiscoveryQuery) -> Iterable[ResearchLead]: ...


def _trim(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def normalize_teaching_languages(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _trim(value)
        if not normalized:
            raise ValueError("teaching language cannot be empty")
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return tuple(result)


def catalog_key(namespace: str, value: str) -> str:
    normalized_namespace = _trim(namespace).casefold()
    normalized_value = _trim(value).casefold()
    if not normalized_namespace or not normalized_value:
        raise ValueError("catalog key parts cannot be empty")
    return f"{normalized_namespace}:{normalized_value}"


def location_key(*, country_code: str, city: str) -> str:
    return catalog_key(country_code, city)


_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid")


def _strip_tracking(query: str) -> str:
    return "&".join(
        pair
        for pair in query.split("&")
        if pair and not pair.split("=", 1)[0].casefold().startswith(_TRACKING_PREFIXES)
    )


def canonicalize_url(url: str) -> str:
    """The canonical identity of an official source. Credentials are not part of it.

    Rebuilt from ``hostname`` and ``port`` rather than lowercasing ``netloc``:
    userinfo is not identity, and keeping it let ``https://evil@vouched.host/x``
    pass a same-host check (``urlsplit().hostname`` drops userinfo) and then
    survive into ``ResearchLead.canonical_url``. ``validate_public_url`` refuses
    to fetch such a URL, so no claim was ever written from one -- but the string
    reached a row a person reads (``ConsultantResearchTask.url`` then, a
    resolution item's evidence or a run's degraded line now), and
    credentials in a URL are the oldest deceptive-link trick there is.
    ``hostname`` also requires a real host, which ``netloc`` did not.
    """
    without_fragment, _fragment = urldefrag(url.strip())
    parsed = urlsplit(without_fragment)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("official sources must use HTTPS")
    # hostname is already lowercased and unbracketed; IPv6 needs its brackets back.
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    path = posixpath.normpath(parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parsed.scheme, netloc, path, _strip_tracking(parsed.query), ""))


def retrieve_official_source(
    url: str,
    *,
    fetch: Callable[..., FetchedPage] | None = None,
    tag: str = "default",
    budget: SweepBudget | None = None,
) -> FetchedPage:
    """Fetch one public page through the vendor path, or RAISE.

    **This function is the boundary.** Inside `apps.research.fetch`, ten of the
    eleven outcomes are VALUES: `fetch_page` returns a refusal rather than
    raising one, so a caller can tell "this page states nothing" from "we could
    not look at this page". Outside it, all eight callers of this function
    predate the engine and are written against a raised `SourceBlocked` -- so
    here, and only here, an unserved outcome becomes an exception again. A
    refusal returned to them instead would arrive as an EMPTY SUCCESS, which on
    the reader path is CLAUDE.md's worst documented failure in this repo.

    New code calls `fetch_page` directly and reads `page.outcome`. Everything
    this translation collapses -- which rung answered, what it cost, whether a
    retry is already scheduled -- survives on the `FetchAttempt` rows the ladder
    wrote, which is where a `BUDGET` stop's `retry_after` lives too.

    `UNCHANGED` is served, not refused: firecrawl.py builds it from the same
    payload as a FETCHED page, body and all, so the host answered in full. The
    saving it exists for is the reader's own digest short-circuit, which needs
    those bytes; raising would instead file every unchanged page as a blocked
    source. An UNCHANGED page carrying NO bytes is refused, because that check
    runs before the vendor's usability rules and an empty one is possible.

    `BUDGET` keeps its own subclass. `manage.py fetch_ladder` catches
    `FetchBudgetExhausted` before `SourceBlocked` -- an exhausted budget ends
    the sweep where a blocked host only skips one line -- and every other caller
    still catches it as the `SourceBlocked` it is.

    The plain-fetch-then-browser ladder this function used to hold is gone: both
    tiers are a vendor's now, and `fetch_page` owns the order. `canonicalize_url`
    stays because a caller may hand us a URL that has never been normalised.

    **`budget` is None on the reader path, and that is not an oversight.**
    `reader.read_program_page` and `program_rules.read_and_derive` call this with
    a URL and nothing else, so no SweepBudget bounds them. What bounds them is
    `reader._READ_LIMIT` -- four reads per programme per hour, checked before the
    unchanged-page shortcut -- which caps the vendor spend at one programme's
    worth rather than a sweep's. A discovery sweep is the opposite shape (many
    hosts, one pass) and passes a SweepBudget. Wiring a budget in here means
    deciding whose it is; the per-programme limiter answers the question the
    reader path actually has.

    **A person's answer is read before any vendor is asked** (the resolution
    queue's HOST_UNREACHABLE write-backs, `resolution/apply.py`). A `MovedPage`
    for this URL means an operator found the page at a new address and the
    ladder opened it there, so the new address is fetched instead -- one hop,
    never a chain. A host an operator declared closed (`HostProfile.retired_at`)
    is refused as DEAD with no vendor call at all: that is the saving, every
    later run of every tenant.
    """
    # Lazy, like fetch/__init__.py's: this module is imported before the app
    # registry is ready.
    from .models import HostProfile, MovedPage

    canonical = canonicalize_url(url)
    moved = MovedPage.objects.filter(from_url=canonical).values_list("to_url", flat=True).first()
    if moved:
        canonical = canonicalize_url(moved)
    host = (urlsplit(canonical).hostname or "").lower()
    if HostProfile.objects.filter(host=host, retired_at__isnull=False).exists():
        raise SourceBlocked(f"DEAD: retired by an operator: {canonical}", outcome="DEAD")
    page = (fetch or fetch_page)(canonical, tag=tag, budget=budget)
    if page.outcome in SERVED or (page.outcome is Outcome.UNCHANGED and page.body):
        return page
    # The outcome travels as an attribute, which is what callers decide on;
    # it also leads the message, for the person reading a log line.
    outcome = str(page.outcome)
    message = f"{outcome}: {page.reason or canonical}"
    if page.outcome is Outcome.BUDGET:
        raise FetchBudgetExhausted(message, outcome=outcome)
    raise SourceBlocked(message, outcome=outcome)


def _tagged(
    source: LeadSource,
    query: DiscoveryQuery,
    on_degraded: Callable[[str], None] | None,
) -> Iterator[ResearchLead]:
    try:
        for lead in source.find(query):
            tagged = lead if lead.discovered_by else replace(lead, discovered_by=source.name)
            if source.one_programme_per_link and tagged.can_support_claim:
                tagged = replace(tagged, one_programme_per_site=True)
            if source.awards_jointly:
                tagged = replace(tagged, awards_jointly=True)
            yield tagged
    except (LeadBudgetExceeded, SourceBlocked):
        # Degrade, do not abort: the leads other sources already produced in
        # this round are still good (design §2.6). One catalogue's listing page
        # being down is not a reason to lose the other three sources' work.
        if on_degraded is not None:
            on_degraded(source.name)


def collect_leads(
    sources: Iterable[LeadSource],
    query: DiscoveryQuery,
    *,
    on_degraded: Callable[[str], None] | None = None,
) -> list[ResearchLead]:
    """Interleave the sources, deduplicate, and stop at the cap.

    Round-robin rather than concatenation: every source hits the network, so a
    prolific seed catalogue must not consume the whole budget before the search
    and entity-expansion sources are asked at all.
    """
    streams = [_tagged(source, query, on_degraded) for source in sources]
    result: list[ResearchLead] = []
    seen: set[str] = set()
    for row in zip_longest(*streams):
        for lead in row:
            if lead is None or lead.canonical_url in seen:
                continue
            seen.add(lead.canonical_url)
            result.append(lead)
            if len(result) >= query.max_leads:
                return result
    return result
