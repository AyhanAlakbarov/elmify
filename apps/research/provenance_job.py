"""provenance_check: gather evidence, decide, record (institution provenance
gate spec §7.1).

Its own worker job, outside any tenant transaction, one body at a time: a
register load is minutes of HTTP and must never sit inside the transaction
`handle_research_message` holds (CLAUDE.md records the same cost for
`read_and_derive`). Nothing here opens a transaction around a fetch -- the
only ones are the lease grab in `ensure_country_loaded`, `record_list`'s per
row write and `record_verdict`, all short and all between fetches. Pack
building only READS what this writes. Only bodies in play are checked --
programme evidence domains, HOLDER-award holders and bodies recorded for a
named programme -- because vouching can cost ~21 vendor fetches a body and the
register holds thousands of bodies no student is shown. A body with no verdict
row is `not_evaluated`.

A verdict is for one (body, registrable domain) pair, never a body (ruling
2026-09-28): a list row recognises the body `record_list` bound it to by the
row's own website, and `decide()` uses a recognition only when it binds the
domain being judged -- so a body's domains A and B can stand differently.
The pairs in play are each programme's `evidence_domain`, each HOLDER award's
`holder_domain` and the domain of a named programme's verified URL.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.funding.models import FundingOpportunity, Program, RecommendationCandidate
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .blocking import MillRow, body_page_texts, content_facts, mill_hit, read_mill_list
from .egress import FetchResult, SourceBlocked, UnsafeTarget, fetch_data_file, fetch_json_api
from .fetch import fetch_page
from .fetch.types import FetchedPage
from .hosts import is_hosting_platform, is_institutional_url, registrable_domain
from .models import (
    Organisation,
    OrganisationDomain,
    ProvenanceVerdict,
    RegisterEntry,
    RegisterEntryPartner,
)
from .provenance import (
    ContentHit,
    Decision,
    Facts,
    RdapResult,
    Reason,
    Recognition,
    Verdict,
    _taken_over,
    decide,
    record_verdict,
)
from .rdap import load_bootstrap, registration_date
from .recognition import (
    ProvenanceSource,
    ensure_country_loaded,
    government_zone,
    list_recognitions,
    load_register,
    read_sources,
    register_country,
    register_state,
    ror_recognitions,
    site_identity,
    verify_register_origins,
)
from .register import record_organisation
from .ror import ror_facts
from .schemas import ResearchMessage
from .storage import S3ObjectStore
from .vouch import find_vouch

logger = logging.getLogger(__name__)

NAMED_TAG = "NAMED_PROGRAM"
_SOON = timedelta(days=1)
_UNCONFIRMED_RETRY = timedelta(days=7)
_RETRY_SOON = frozenset({Reason.LOOKUP_FAILED, Reason.REGISTER_NOT_LOADED, Reason.NOT_EVALUATED})


@dataclass
class Deps:
    """Every outbound path, injectable. One per run: `run_id` keys the Jev
    limit, and the source and mill files and the recogniser map are read once
    per run, never per body."""

    fetch: Callable[..., FetchedPage] = fetch_page
    fetch_file: Callable[..., FetchResult] = fetch_data_file
    ror_call: Callable[..., dict[str, object]] = fetch_json_api
    jev_post: Callable[..., dict[str, object]] = fetch_json_api
    load: Callable[..., object] = load_register
    store: Any = None
    sources: tuple[ProvenanceSource, ...] = field(default_factory=read_sources)
    mill_rows: tuple[MillRow, ...] = field(default_factory=read_mill_list)
    #: RECOGNISED domain -> (reason code, body), read at the first vouch of the
    #: run: a domain recognised later in the same run vouches from the next run.
    recognisers: dict[str, tuple[str, UUID]] | None = None
    bootstrap: dict[str, str] | None = None
    bootstrap_failed: bool = False
    run_id: UUID = field(default_factory=uuid4)

    def object_store(self) -> Any:
        if self.store is None:
            self.store = S3ObjectStore()
        return self.store

    def recognisers_for(self, organisation: Organisation) -> dict[str, str]:
        """Every RECOGNISED domain but this body's own: a body never vouches for itself."""
        if self.recognisers is None:
            self.recognisers = {
                domain: (reason, body)
                for domain, reason, body in ProvenanceVerdict.objects.filter(
                    verdict=Verdict.RECOGNISED
                ).values_list("domain", "reason_code", "organisation_id")
            }
        return {
            domain: reason
            for domain, (reason, body) in self.recognisers.items()
            if body != organisation.id
        }

    def rdap(self, domain: str) -> RdapResult:
        if self.bootstrap is None and not self.bootstrap_failed:
            try:
                self.bootstrap = load_bootstrap(fetch=self.fetch_file)
            except (SourceBlocked, UnsafeTarget, ValueError) as error:
                logger.warning("IANA's RDAP bootstrap unreachable: %s", error)
                self.bootstrap_failed = True
        if self.bootstrap is None:
            return RdapResult("failed", detail="IANA's RDAP bootstrap was unreachable")
        return registration_date(domain, self.bootstrap, fetch=self.fetch_file)


def next_check(decision: Decision, now: datetime) -> datetime | None:
    # A proven body is proven once (spec §4.1, owner 2026-10-03): no timer
    # re-checks it. BLOCKED is never re-checked either. Only UNCONFIRMED retries.
    if decision.verdict in (Verdict.BLOCKED, Verdict.RECOGNISED):
        return None
    # no_register waits on a register being shipped, not on a load: daily
    # retries would only re-learn that none exists.
    if decision.reason_code == Reason.NO_REGISTER:
        return now + timedelta(days=settings.PROVENANCE_CYCLE_DAYS)
    return now + (_SOON if decision.reason_code in _RETRY_SOON else _UNCONFIRMED_RETRY)


def _binds(found: tuple[Recognition, ...], domain: str) -> bool:
    """Whether a recognition `decide()` could use binds this body's own domain."""
    return not is_hosting_platform(domain) and any(r.bound_domain == domain for r in found)


def check_body(
    organisation: Organisation, domain: str, *, now: datetime, deps: Deps
) -> ProvenanceVerdict:
    """Judge exactly `domain`, one of `organisation`'s registrable domains."""
    sources, mill_rows = deps.sources, deps.mill_rows
    previous = ProvenanceVerdict.objects.filter(domain=domain).first()
    ror = ror_facts(domain, call=deps.ror_call)
    lookup_failed = ror.lookup_failed
    # Operating country from evidence only -- a list's row or ROR -- never
    # from the page (spec §5.2). The ccTLD only picks WHICH register to load
    # (ruling I3); the register's own website field is still what admits.
    load_country = register_country(organisation.country_code or ror.country_code, domain)

    identity: str | None = None

    def unread(recognition: Recognition) -> bool:
        """Granted without reading the site: a bare zone, a funder-list partner row
        (a lapsed partner's printed website proves nothing about today's site), or a
        register row bound by ROR."""
        return recognition.reason in (Reason.GOVERNMENT_ZONE, Reason.FUNDER_LIST) or (
            recognition.reason == Reason.REGISTER and recognition.admitted_via == "ror"
        )

    def identity_ok(found: tuple[Recognition, ...]) -> bool:
        """The homepage check, run at most once per check_body. A ROR-bound row
        has no organisation, so its own name is passed in."""
        nonlocal identity, lookup_failed
        if identity is None:
            row_names = [
                name
                for r in found if r.admitted_via == "ror" and r.identifier
                for name in RegisterEntry.objects.filter(
                    register=r.source_slug, external_key=r.identifier[1]
                ).values_list("name", flat=True)
            ] + [
                name
                for r in found if r.reason == Reason.FUNDER_LIST and r.identifier
                for name in RegisterEntryPartner.objects.filter(
                    organisation=organisation, entry__register=r.source_slug,
                    listed_identifier=r.identifier[1], listed_domain=domain,
                ).values_list("listed_name", flat=True)
            ]
            identity = site_identity(organisation, domain, fetch=deps.fetch, names=row_names)
            lookup_failed |= identity == "lookup_failed"
        return identity == "verified"

    def settle(found: tuple[Recognition, ...]) -> tuple[Recognition, ...]:
        """Keep an unread recognition only once the homepage names the body, so
        `_binds` and the vouch gate never count one that is not confirmed."""
        if not any(unread(r) for r in found) or identity_ok(found):
            return found
        if identity == "lookup_failed":
            # Nothing was read, so nothing is decided about the site: drop them
            # and let decide() report lookup_failed.
            return tuple(r for r in found if not unread(r))
        # Read, and it names someone else: unbind, so decide() says
        # no_domain_binding, never "not checked".
        return tuple(replace(r, bound_domain="") if unread(r) else r for r in found)

    tried: set[object] = set()

    def recognitions() -> tuple[tuple[Recognition, ...], bool]:
        verify_register_origins(
            organisation, domain, sources, now=now, fetch=deps.fetch, tried=tried
        )
        found, unverified = list_recognitions(
            organisation, sources, domain=domain, require_register_origin=True
        )
        zone = government_zone(domain)
        by_ror = ror_recognitions(ror, domain, sources)
        return settle((*found, *by_ror, *((zone,) if zone else ()))), unverified

    def load(country: str) -> str:
        return ensure_country_loaded(
            country, now=now, cycle=timedelta(days=settings.PROVENANCE_CYCLE_DAYS),
            sources=sources, load=deps.load, fetch=deps.fetch, fetch_file=deps.fetch_file,
            store=deps.object_store(),
        )

    found, unverified = recognitions()
    state = "not_loaded"
    if not _binds(found, domain):
        loaded = load(load_country)
        lookup_failed |= loaded == "failed"
        if loaded == "ok":
            found, unverified = recognitions()
            state = register_state(load_country, sources)
        elif loaded == "none":
            # No register shipped for this country, or no country at all:
            # waiting would be forever (mit.edu, unibo.it, measured).
            state = "no_register"

    mill = mill_hit(domain, rows=mill_rows, register_countries=set())
    if mill is not None:
        # Only a register of the MILL ROW's country overrides it (spec §5.4
        # rule 1), so that register is loaded first: whether the override
        # applies must never depend on which register happened to be loaded
        # already (Task 4 review, I2). Register rows binding THIS domain only.
        mill_load = load(mill.country_code)
        found, unverified = recognitions()
        mill = mill_hit(
            domain, rows=mill_rows,
            register_countries={
                r.country_code for r in found
                if r.reason == Reason.REGISTER and r.bound_domain == domain and r.country_code
            },
        ) or mill
        if not mill.overridden and mill_load in ("failed", "busy"):
            # BLOCKED is never re-checked (next_check), so an override that an
            # unreadable register could still give must not become permanent.
            decision = Decision(
                Verdict.UNCONFIRMED,
                Reason.LOOKUP_FAILED if mill_load == "failed" else Reason.REGISTER_NOT_LOADED,
                domain,
                {"mill": {"source": mill.source, "revision": mill.revision,
                          "country_code": mill.country_code, "overridden": False},
                 "mill_register": mill_load},
            )
            return _record(organisation, domain, decision, now, deps)
    blocked = mill is not None and not mill.overridden

    # A homepage that was read and names someone else is not rescued by a vouch
    # link: the vouch runs only when the identity check did not run or could not read.
    if (
        not blocked and not _binds(found, domain) and not is_hosting_platform(domain)
        and identity in (None, "lookup_failed")
    ):
        vouch = find_vouch(domain, deps.recognisers_for(organisation), fetch=deps.fetch)
        lookup_failed |= vouch.failed
        if vouch.vouch_url:
            found = (
                *found,
                Recognition(
                    reason=Reason.VOUCHED_BY_LINK, bound_domain=domain,
                    vouch_url=vouch.vouch_url, admitted_via=vouch.recogniser_domain,
                ),
            )

    hits: tuple[ContentHit, ...] = ()
    if blocked:
        # decide() blocks on the mill whatever the page says: no Jev spend.
        content_status, content_detail = "skipped", "mill_list"
    else:
        hits, content_status, content_detail = content_facts(
            body_page_texts(organisation, domain, store=deps.object_store()),
            run_id=deps.run_id, post=deps.jev_post,
        )
    rdap = (
        deps.rdap(domain) if not blocked and _binds(found, domain)
        else RdapResult("skipped", detail="not recognised")
    )
    decision = decide(
        Facts(
            domain=domain, recognitions=found, unverified_list_row=unverified, mill=mill,
            content_hits=hits, content_checks=content_status,
            content_checks_detail=content_detail, rdap=rdap,
            # The row is this domain's, so its first binding is this domain's
            # (Task 4 review, M5); another domain's date lives on another row.
            first_bound_at=previous.first_bound_at if previous is not None else None,
            register_state=state, lookup_failed=lookup_failed,
            was_vouched=previous is not None and previous.reason_code == Reason.VOUCHED_BY_LINK,
        )
    )
    if identity is not None:
        decision.evidence["site_identity"] = identity
    return _record(organisation, domain, decision, now, deps)


def _record(
    organisation: Organisation, domain: str, decision: Decision, now: datetime, deps: Deps
) -> ProvenanceVerdict:
    # A recogniser downgraded mid-run stops vouching for bodies judged after it.
    if deps.recognisers is not None and decision.verdict != Verdict.RECOGNISED:
        deps.recognisers.pop(domain, None)
    return record_verdict(
        organisation, domain, verdict=decision.verdict, reason_code=decision.reason_code,
        evidence=decision.evidence, now=now, next_check_at=next_check(decision, now),
    )


def bodies_in_play() -> QuerySet[OrganisationDomain]:
    """The (body, domain) pairs in play, as the OrganisationDomain rows naming them."""
    evidence_domains = Program.objects.exclude(evidence_domain="").values("evidence_domain")
    holder_domains = (
        FundingOpportunity.objects.filter(scope_type="HOLDER")
        .exclude(holder_domain="")
        .values("holder_domain")
    )
    return (
        OrganisationDomain.objects.filter(
            Q(registrable_domain__in=evidence_domains)
            | Q(registrable_domain__in=holder_domains)
            # The domain the counsellor's verified URL sits on, tagged on its
            # own row (check_named_url): a named URL on a body's second domain
            # puts that domain in play, not the body's primary.
            | Q(found_via__contains=[NAMED_TAG])
        )
        .exclude(organisation__status=Organisation.Status.REJECTED)
        .select_related("organisation")
    )


def due(now: datetime) -> QuerySet[OrganisationDomain]:
    """Pairs with no verdict yet, or whose next check has come. BLOCKED and
    RECOGNISED (next_check_at NULL) never come due."""
    not_due = ProvenanceVerdict.objects.filter(
        Q(next_check_at__isnull=True) | Q(next_check_at__gt=now)
    ).values("domain")
    return bodies_in_play().exclude(registrable_domain__in=not_due)


def check_pending(body_ids: Iterable[UUID], *, now: datetime, deps: Deps) -> Counter[str]:
    """A pack build's pending bodies, checked now rather than at the daily
    recheck (spec §7.1, ruling I4). Every DUE domain of each given body is
    checked, not only the (body, domain) pairs the pack was waiting on; a pair
    not yet due -- a register_not_loaded one re-checked minutes ago -- waits
    for its own next_check_at."""
    return run_checks(due(now).filter(organisation_id__in=list(body_ids)), now=now, deps=deps)


def run_checks(
    pairs: QuerySet[OrganisationDomain], *, now: datetime, deps: Deps
) -> Counter[str]:
    tally: Counter[str] = Counter()
    for pair in pairs.order_by("registrable_domain"):
        try:
            verdict = check_body(pair.organisation, pair.registrable_domain, now=now, deps=deps)
            tally[verdict.reason_code] += 1
        except Exception:  # noqa: BLE001 - one pair never stops the batch; logged by name
            # Nothing is recorded: a crash is our bug, not a failed lookup.
            logger.exception("provenance check failed for %s", pair.registrable_domain)
            tally["error"] += 1
    return tally


def screen_recognised(*, now: datetime, deps: Deps) -> Counter[str]:
    """The free yearly screen of RECOGNISED pairs: RDAP and the mill list only,
    no page fetch. A pair that looks taken over or mill-listed gets the full
    `check_body`, which decides (a mill row's own register still overrides); a
    clean one is only marked screened. A failed lookup changes nothing and the
    row is retried next run, never downgraded. No transaction spans an RDAP call."""
    tally: Counter[str] = Counter()
    cutoff = now - timedelta(days=settings.PROVENANCE_RECOGNISED_SCREEN_DAYS)
    rows = (
        ProvenanceVerdict.objects.filter(verdict=Verdict.RECOGNISED, checked_at__lte=cutoff)
        .exclude(organisation__status=Organisation.Status.REJECTED)
        .select_related("organisation")
        .order_by("checked_at")[: settings.PROVENANCE_RECOGNISED_SCREEN_MAX]
    )
    for row in list(rows):
        try:
            rdap = deps.rdap(row.domain)
            flagged = _taken_over(
                Facts(domain=row.domain, rdap=rdap, first_bound_at=row.first_bound_at)
            ) or mill_hit(row.domain, rows=deps.mill_rows, register_countries=set()) is not None
            if flagged:
                tally[check_body(row.organisation, row.domain, now=now, deps=deps).reason_code] += 1
            elif rdap.status in ("ok", "skipped"):
                ProvenanceVerdict.objects.filter(pk=row.pk).update(checked_at=now)
                tally["screened"] += 1
            else:
                tally["rdap_failed"] += 1
        except Exception:  # noqa: BLE001 - one pair never stops the batch; logged by name
            logger.exception("recognised screen failed for %s", row.domain)
            tally["error"] += 1
    return tally


def check_named_url(
    source_url: str, program_name: str, *, now: datetime, deps: Deps
) -> tuple[UUID | None, str]:
    """The verdict for the body behind a counsellor-verified URL (spec §7.4).

    The site is the URL a person verified, never one chosen by name (§5.2):
    `program_name` is only logged. The domain is tagged NAMED on the body and on
    its own OrganisationDomain row, so `bodies_in_play` re-checks it."""
    domain = registrable_domain(source_url)
    if not domain or is_hosting_platform(domain):
        return None, Reason.NO_DOMAIN_BINDING
    if not is_institutional_url(source_url, domain):
        return None, Reason.EVIDENCE_OFF_DOMAIN
    # The body's name is unknown here: a programme's name is not an
    # institution's, so a new body is labelled by its domain.
    organisation = record_organisation(
        domain=domain, name=domain, kind="INSTITUTION", country_code="", found_via=NAMED_TAG
    )
    pair = OrganisationDomain.objects.get(registrable_domain=domain)
    if NAMED_TAG not in pair.found_via:
        pair.found_via = [*pair.found_via, NAMED_TAG]
        pair.save(update_fields=["found_via"])
    if organisation.status == Organisation.Status.REJECTED:
        # Never checked (bodies_in_play) and never admitted (the pool).
        return organisation.id, Reason.NO_DOMAIN_BINDING
    # A verdict not yet due is the daily recheck's (due()): resolving a second
    # programme on the same site spends no vendor fetch.
    current = (
        ProvenanceVerdict.objects.filter(domain=domain)
        .filter(Q(next_check_at__isnull=True) | Q(next_check_at__gt=now))
        .values_list("reason_code", flat=True)
        .first()
    )
    if current is not None:
        return organisation.id, current
    logger.info("named-programme check: %s on %s", program_name[:120], domain)
    return organisation.id, check_body(organisation, domain, now=now, deps=deps).reason_code


def check_named_program(
    message: ResearchMessage,
    *,
    check: Callable[[str, str], tuple[UUID | None, str]] | None = None,
) -> None:
    """Worker side of a named programme: read the candidate, compute the
    verdict OUTSIDE any tenant transaction (a check is minutes of HTTP, spec
    §7.1), then write the tenant copy the web reads (§7.4)."""
    if message.candidate_id is None:
        raise ValueError("a named-programme check needs a candidate")
    with tenant_scope(message.tenant_id), tenant_transaction(message.tenant_id):
        # A named candidate only: never overwrite a catalogue candidate's code,
        # and never check the pending placeholder before a counsellor has
        # resolved it to a verified URL.
        row = (
            RecommendationCandidate.objects.filter(
                id=message.candidate_id, run_id=message.run_id,
                state=RecommendationCandidate.State.VISIBLE,
                program__isnull=True, opportunity__isnull=True,
            )
            .values_list("evidence__source_url", "program_name")
            .first()
        )
    if row is None:
        logger.warning("named-programme check: no named candidate %s", message.candidate_id)
        return
    source_url, name = row
    body_id, code = (
        check(source_url, name)
        if check is not None
        else check_named_url(source_url, name, now=timezone.now(), deps=Deps())
    )
    with tenant_scope(message.tenant_id), tenant_transaction(message.tenant_id):
        RecommendationCandidate.objects.filter(id=message.candidate_id).update(
            provenance_reason_code=code, provenance_body_id=body_id
        )
