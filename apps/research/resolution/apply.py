"""Write each decided answer back to the catalog, then delete the item.

Runs ONLY from `manage.py apply_resolutions`, as `runtime_engine` or the table
owner: `runtime_web` holds no grant on any catalogue table (funding/0049), so
doing this in the console's request would be `permission denied` at best --
and under a role with the grant but no write policy, legal SQL matching zero
rows (CLAUDE.md failure mode 1). The command checks the role before it starts.

One transaction per item, and the write-back inside it in a savepoint: one
refused write-back rolls back only its own partial writes, never another
item's, and the item itself still goes back to OPEN with the reason. Every
transition leaves an AuditEvent under the platform agency (AuditEvent is FORCE
RLS, so the GUC is set even for the owner).

A HOST_UNREACHABLE paste fetches the pasted page BEFORE its transaction opens:
a vendor call is seconds of network, and `fetch_page` writes the FetchAttempt
billing trail, which a rolled-back savepoint would otherwise erase along with
the credits it records.

Plan: docs/superpowers/plans/2026-09-25-human-resolution-queue.md, Task 7.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from django.db import transaction
from pydantic import BaseModel

from apps.funding.models import (
    AuditEvent,
    FundingOpportunity,
    OfficialSource,
    OfficialSourceSnapshot,
)
from apps.research.discovery import canonicalize_url
from apps.research.fetch import fetch_page
from apps.research.fetch.types import SERVED, FetchedPage
from apps.research.funding_reader import _FAMILY, review_funding
from apps.research.hosts import registrable_domain
from apps.research.models import (
    HostProfile,
    MovedPage,
    Organisation,
    RegisterEntry,
    ResolutionItem,
    ResolvedVia,
)
from apps.research.register import record_organisation
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

from .kinds import (
    KINDS,
    AwardDisputedEvidence,
    AwardDisputedResolution,
    HostUnreachableEvidence,
    HostUnreachableResolution,
    KindOrCountryEvidence,
    KindOrCountryResolution,
    SiteUnknownEvidence,
    SiteUnknownResolution,
)
from .platform import platform_agency
from .writers import AWARD_VOCABULARIES

APPLIED = "resolution.applied"
REOPENED = "resolution.reopened"
EXPIRED = "resolution.expired"

#: The FundingOpportunity columns an AWARD_DISPUTED "accept" may set -- the
#: fields with a closed vocabulary (plan Task 8), read from the writer's own
#: table so the two cannot drift. Anything else in a decision is refused
#: rather than written: the resolution schema checks a value against the
#: item's evidence, and this checks the evidence names a column.
_AWARD_FIELDS = frozenset(AWARD_VOCABULARIES)

_AWARD_NOTES = {"not_an_award": "not an award", "third_party": "third party's money"}

_OPEN_ENTRY = (RegisterEntry.Resolution.UNRESOLVED, RegisterEntry.Resolution.CONFLICT)


@dataclass
class ApplyReport:
    applied: int = 0
    reopened: int = 0
    lines: list[str] = field(default_factory=list)


class Refused(Exception):
    """The write-back cannot be made as decided; the item goes back to OPEN."""


@dataclass(frozen=True)
class _Prepared:
    """What was fetched for an item before its transaction opened."""

    pages: dict[str, FetchedPage] = field(default_factory=dict)


Writeback = Callable[[ResolutionItem, Any, Any, datetime, _Prepared], str]


# --- SITE_UNKNOWN -----------------------------------------------------------


def _site_unknown(
    item: ResolutionItem,
    evidence: SiteUnknownEvidence,
    resolution: SiteUnknownResolution,
    now: datetime,
    _prepared: _Prepared,
) -> str:
    entry = RegisterEntry.objects.filter(
        register=evidence.register, external_key=evidence.external_key
    ).first()
    if entry is None:
        raise Refused("the register row is gone")
    if entry.resolution not in _OPEN_ENTRY:
        raise Refused(f"the register row was answered meanwhile: now {entry.resolution}")
    rows = RegisterEntry.objects.filter(pk=entry.pk, resolution__in=_OPEN_ENTRY)
    if resolution.option in {"not_a_funder", "does_not_exist"}:
        reason = resolution.option.upper()
        written = rows.update(
            resolution=RegisterEntry.Resolution.REFUSED, refused_reason=reason,
            resolved_via="", unresolved_reason="", organisation=None,
        )
        if written != 1:
            raise Refused("the register row could not be written")
        return reason
    host = (urlsplit(resolution.url).hostname or "").lower()
    domain = registrable_domain(host)
    if not domain:
        raise Refused(f"{host or resolution.url!r} has no registrable domain to key on")
    held = (
        Organisation.objects.filter(domains__registrable_domain=domain)
        .values_list("status", flat=True).first()
    )
    if held == Organisation.Status.REJECTED:
        raise Refused(f"{domain} belongs to a rejected organisation")
    try:
        org = record_organisation(
            domain=domain, name=entry.name, names=evidence.names,
            kind=entry.kind or "UNSTATED",
            country_code=entry.country_code or evidence.country_code,
            status=Organisation.Status.REGISTERED, found_via=f"HUMAN:{item.id}",
            identifiers=(("HUMAN", f"{evidence.register}:{evidence.external_key}"),),
        )
    except ValueError as error:
        raise Refused(str(error)) from error
    # A person vouching for the pairing is what REGISTERED means (spec 6.1);
    # record_organisation never moves an existing row's status, so upgrade here.
    changed: list[str] = []
    if org.status == Organisation.Status.CANDIDATE:
        org.status = Organisation.Status.REGISTERED
        changed.append("status")
    if not org.official_website:
        org.official_website = resolution.url
        changed.append("official_website")
    if changed:
        org.save(update_fields=changed)
    written = rows.update(
        resolution=RegisterEntry.Resolution.RESOLVED, resolved_via=ResolvedVia.HUMAN,
        unresolved_reason="", refused_reason="", organisation=org,
    )
    if written != 1:
        raise Refused("the register row could not be written")
    return f"bound to {org.primary_domain}"


# --- AWARD_DISPUTED ---------------------------------------------------------


def _award_disputed(
    item: ResolutionItem,
    evidence: AwardDisputedEvidence,
    resolution: AwardDisputedResolution,
    now: datetime,
    _prepared: _Prepared,
) -> str:
    row = FundingOpportunity.objects.filter(canonical_key=evidence.canonical_key).first()
    if row is None:
        raise Refused("the award row is gone")
    claims = list(row.evidence_claims.select_related("snapshot"))
    latest = (
        OfficialSourceSnapshot.objects.filter(source_id__in={c.source_id for c in claims})
        .order_by("-retrieved_at").values_list("sha256", flat=True).first()
    )
    # The operator judged the quotes of one page version. review_funding binds
    # the review to the claims' snapshot; if either that or the page's latest
    # version is another, the decision is about text that is no longer the page's.
    bound = {c.snapshot.sha256 for c in claims if c.snapshot is not None}
    if latest != evidence.snapshot_sha256 or bound != {evidence.snapshot_sha256}:
        raise Refused("the page changed since this was decided")
    if resolution.option == "accept":
        unknown = set(resolution.fields) - _AWARD_FIELDS
        if unknown:
            raise Refused(f"not a column an operator may set: {', '.join(sorted(unknown))}")
        for name, value in resolution.fields.items():
            setattr(row, name, value)
        changed = list(resolution.fields)
        if "kind" in resolution.fields and row.scope_type != "HOLDER":
            row.family = _FAMILY[resolution.fields["kind"]]
            changed.append("family")
        if changed:
            row.save(update_fields=changed)
        note = resolution.note
    else:
        note = "; ".join(filter(None, (_AWARD_NOTES[resolution.option], resolution.note)))
    try:
        review_funding(row, accepted=resolution.option == "accept", note=note, now=now)
    except ValueError as error:
        # The suspension guard (and the no-quote guards): its message is the
        # operator's reason, verbatim.
        raise Refused(str(error)) from error
    return resolution.option


# --- HOST_UNREACHABLE -------------------------------------------------------


def _host_unreachable(
    item: ResolutionItem,
    evidence: HostUnreachableEvidence,
    resolution: HostUnreachableResolution,
    now: datetime,
    prepared: _Prepared,
) -> str:
    if resolution.option == "closed":
        host = evidence.host.lower()
        profile, _ = HostProfile.objects.get_or_create(host=host)
        profile.retired_at = now
        profile.save(update_fields=["retired_at", "updated_at"])
        bare = host.removeprefix("www.")
        rejected = (
            Organisation.objects.filter(primary_domain__in={host, bare})
            .exclude(status=Organisation.Status.REJECTED)
            .update(
                status=Organisation.Status.REJECTED,
                rejected_reason=Organisation.RejectedReason.UNREACHABLE,
            )
        )
        return f"retired{' and rejected' if rejected else ''}"
    page = prepared.pages.get(resolution.url)
    if page is None:
        raise Refused(f"{resolution.url} was not fetched before applying")
    if page.outcome not in SERVED:
        raise Refused(f"the ladder still cannot open {resolution.url}: {page.outcome}")
    try:
        from_url = canonicalize_url(evidence.url)
        to_url = canonicalize_url(page.final_url)
    except ValueError as error:
        raise Refused(f"cannot record the move: {error}") from error
    if from_url == to_url:
        return "opens again at the same address"
    MovedPage.objects.update_or_create(from_url=from_url, defaults={"to_url": to_url})
    # "A source that genuinely moved hosts is a catalog fix -- update
    # canonical_url -- which is a human decision, recorded" (CLAUDE.md). When
    # the new address is already a source of its own, both stay and the
    # MovedPage says which replaced which.
    repointed = 0
    if not OfficialSource.objects.filter(canonical_url=to_url).exists():
        repointed = OfficialSource.objects.filter(
            canonical_url__in={evidence.url, from_url}
        ).update(canonical_url=to_url)
    return f"moved to {to_url}{' (source repointed)' if repointed else ''}"


def _prepare(item: ResolutionItem) -> _Prepared:
    """The one network call an applier makes, outside any transaction."""
    if item.kind != ResolutionItem.Kind.HOST_UNREACHABLE or not item.resolution:
        return _Prepared()
    if item.resolution.get("option") != "paste":
        return _Prepared()
    url = str(item.resolution.get("url", ""))
    return _Prepared(pages={url: fetch_page(url, require_origin=url)})


# --- KIND_OR_COUNTRY_UNSURE -------------------------------------------------


def _kind_or_country(
    item: ResolutionItem,
    evidence: KindOrCountryEvidence,
    resolution: KindOrCountryResolution,
    now: datetime,
    _prepared: _Prepared,
) -> str:
    org = Organisation.objects.filter(primary_domain=evidence.primary_domain).first()
    if org is None:
        raise Refused(f"no organisation {evidence.primary_domain} any more")
    if org.status == Organisation.Status.REJECTED:
        raise Refused(f"{org.primary_domain} was rejected meanwhile ({org.rejected_reason})")
    if resolution.option == "not_an_organisation":
        org.status = Organisation.Status.REJECTED
        org.rejected_reason = Organisation.RejectedReason.NOT_AN_ORGANISATION
        org.save(update_fields=["status", "rejected_reason"])
        return "rejected"
    changed = ["funds_students", "classified_at", "classified_by", "classifier_confidence"]
    org.funds_students = resolution.funds_students
    org.classified_at = now
    org.classified_by = "HUMAN"
    org.classifier_confidence = 1.0
    if org.status != Organisation.Status.REGISTERED:
        # A register vouched a REGISTERED row's kind and country; the
        # classifier's own rule keeps them, and so does a person's.
        org.kind = resolution.kind
        org.country_code = resolution.country_code
        changed += ["kind", "country_code"]
    org.save(update_fields=changed)
    return "classified"


_WRITEBACKS: dict[str, Writeback] = {
    "SITE_UNKNOWN": _site_unknown,
    "AWARD_DISPUTED": _award_disputed,
    "HOST_UNREACHABLE": _host_unreachable,
    "KIND_OR_COUNTRY_UNSURE": _kind_or_country,
}


def _audit(event: str, object_id: UUID) -> None:
    AuditEvent.objects.create(event=event, object_id=object_id)


def apply_decided(*, now: datetime) -> ApplyReport:
    report = ApplyReport()
    platform = platform_agency()
    decided = ResolutionItem.objects.filter(state=ResolutionItem.State.DECIDED)
    for item_id in decided.order_by("decided_at").values_list("id", flat=True):
        unlocked = ResolutionItem.objects.filter(id=item_id, state="DECIDED").first()
        if unlocked is None:
            continue
        prepared = _prepare(unlocked)
        with transaction.atomic(), tenant_scope(platform.id):
            set_local_tenant(platform.id)
            item = (
                ResolutionItem.objects.select_for_update()
                .filter(id=item_id, state=ResolutionItem.State.DECIDED).first()
            )
            if item is None:
                continue
            spec = KINDS[item.kind]
            evidence: BaseModel = spec.evidence.model_validate(item.evidence)
            try:
                resolution = spec.resolution.model_validate(
                    item.resolution, context={"evidence": evidence}
                )
                with transaction.atomic():
                    outcome = _WRITEBACKS[item.kind](item, evidence, resolution, now, prepared)
            except Exception as error:  # every refusal reopens the item, loudly
                why = str(error) if isinstance(error, Refused) else (
                    f"{type(error).__name__}: {error}"
                )
                item.state, item.resolution, item.decided_at = "OPEN", None, None
                item.apply_error = why[:200]
                item.save(update_fields=["state", "resolution", "decided_at", "apply_error"])
                _audit(REOPENED, item.id)
                report.reopened += 1
                report.lines.append(f"reopened {item.kind} {item.subject_key}: {why}"[:300])
                continue
            seconds = (
                int((item.decided_at - item.opened_at).total_seconds())
                if item.opened_at and item.decided_at else None
            )
            took = f"{seconds}s" if seconds is not None else "unopened"
            report.lines.append(
                f"applied {item.kind} {item.subject_key}: {outcome}"
                f" (opened to decided: {took})"
            )
            _audit(APPLIED, item.id)
            item.delete()
            report.applied += 1
    return report


def expire_unopened(*, now: datetime) -> int:
    """Delete OPEN items nobody opened within RESOLUTION_EXPIRY_DAYS. A writer
    re-files one, with fresh evidence, if its question is still live."""
    platform = platform_agency()
    with transaction.atomic(), tenant_scope(platform.id):
        set_local_tenant(platform.id)
        stale = list(
            ResolutionItem.objects.select_for_update().filter(
                state=ResolutionItem.State.OPEN, opened_at__isnull=True, expires_at__lte=now
            ).values_list("id", flat=True)
        )
        for item_id in stale:
            _audit(EXPIRED, item_id)
        ResolutionItem.objects.filter(id__in=stale).delete()
    return len(stale)


def known_organisations(country_code: str) -> int:
    """The corridor share's denominator: organisations the catalogue holds in
    a country, rejected ones excluded. Engine-side -- a catalogue read."""
    return (
        Organisation.objects.filter(country_code=country_code)
        .exclude(status=Organisation.Status.REJECTED).count()
    )
