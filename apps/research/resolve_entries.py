"""A register row's resolution, written -- or its reason (spec 6.5, 6.1).

Status is CANDIDATE for every resolver outcome. The register vouched that the
BODY exists and what kind it is; the resolver found a domain, and nothing
vouched for that pairing but our own checks. REGISTERED stays what 6.1 says it
is -- a register (or, later, an operator through item 12) vouching for the
domain -- and status governs spend and dedupe, never what a student sees.

Every write is `filter(pk=...).update(...)` with its row count checked. Under
the runtime role an UPDATE on this shared table matches zero rows and raises
nothing (the policy hides the row from writes); a resolver run under the wrong
role would otherwise report success and change nothing.

The write is also conditional on the row still being the one the resolver was
asked about: UNRESOLVED, under the same name. A run reads its queue, then
spends seconds per name on searches and fetches; in that window a list re-read
can bind the row by its own website (LISTED, EMAIL), rename it, or a person can
bind it (HUMAN). Each of those is stronger evidence than the resolver's answer,
which was an answer for a row that no longer exists in that shape -- so the
write is refused (`EntryMovedOn`) and the row is left as the other writer left
it, rather than silently overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q, QuerySet

from .hosts import registrable_domain
from .models import RegisterEntry, UnresolvedReason
from .register import record_organisation
from .resolver import Resolution

#: A fetch failure is the host's, often transient (4.13a: ~10%, broken chains,
#: no answer); a week lets the fetch engine's own retry schedule run first.
FETCH_RETRY_AFTER = timedelta(days=7)
#: One Diffbot entity per name per quarter at most.
DIFFBOT_RETRY_AFTER = timedelta(days=90)


class CatalogWriteRefused(RuntimeError):
    """A resolution matched no row -- deleted meanwhile, or the wrong database role."""


class EntryMovedOn(CatalogWriteRefused):
    """The row is still there but is no longer the UNRESOLVED row, under the
    same name, that the resolver answered for. Nothing was written but the
    Diffbot meter; the run goes on to the next name."""


@dataclass(frozen=True)
class RegisterSpec:
    """What a register vouches for every row it lists."""

    country_code: str
    kind: str


def spec_for(entry: RegisterEntry, spec: RegisterSpec) -> RegisterSpec:
    """The register's spec, with what this row itself asserts laid over it.

    A closed list asserts a country and a kind per row (the intergovernmental
    list belongs to no country at all), so the row's own value wins where it
    has one, and the register's where it is silent.
    """
    return replace(
        spec,
        country_code=entry.country_code or spec.country_code,
        kind=entry.kind or spec.kind,
    )


def due_entries(
    register: str, *, now: datetime, retry_final: bool = False
) -> QuerySet[RegisterEntry]:
    """UNRESOLVED rows never tried, or whose fetch failed over a week ago.

    CONFLICT rows are never due: an IDENTIFIER_CONFLICT is a person's
    question (item 12), and re-running the resolver asks it again unchanged.
    Nor is a row a person answered -- RESOLVED/HUMAN or REFUSED -- since
    neither is UNRESOLVED; `record_resolution` refuses to write over one too
    (`EntryMovedOn`).
    """
    unresolved = RegisterEntry.objects.filter(
        register=register, resolution=RegisterEntry.Resolution.UNRESOLVED
    )
    due = Q(resolution_attempted_at__isnull=True) | Q(
        unresolved_reason=UnresolvedReason.FETCH_FAILED,
        resolution_attempted_at__lt=now - FETCH_RETRY_AFTER,
    )
    if retry_final:
        due |= ~Q(unresolved_reason=UnresolvedReason.FETCH_FAILED)
    return unresolved.filter(due).order_by("first_seen", "external_key")


def diffbot_allowed(entry: RegisterEntry, *, now: datetime) -> bool:
    return entry.diffbot_asked_at is None or entry.diffbot_asked_at < now - DIFFBOT_RETRY_AFTER


def record_diffbot_asked(entry: RegisterEntry, *, now: datetime) -> None:
    """The monthly meter (and the 90-day rule) counts calls made, so it is
    written whatever happens to the answer -- a row that moved on meanwhile,
    or a run that stopped on its fetch budget verifying Diffbot's answer."""
    _update(entry, as_asked=False, diffbot_asked_at=now)


def _update(entry: RegisterEntry, *, as_asked: bool, **values: object) -> None:
    """One row, updated or refused loudly.

    `as_asked` narrows the UPDATE to the row as the resolver saw it; zero rows
    then means either it moved on (a SELECT still sees it, in another state)
    or it cannot be written at all -- deleted, or the wrong role.
    """
    rows = RegisterEntry.objects.filter(pk=entry.pk)
    if as_asked:
        rows = rows.filter(resolution=RegisterEntry.Resolution.UNRESOLVED, name=entry.name)
    if rows.update(**values) == 1:
        return
    if as_asked:
        now_is = (
            RegisterEntry.objects.filter(pk=entry.pk)
            .values_list("resolution", "resolved_via", "name")
            .first()
        )
        if now_is is not None and (
            now_is[0] != RegisterEntry.Resolution.UNRESOLVED or now_is[2] != entry.name
        ):
            resolution, via, name = now_is
            raise EntryMovedOn(
                f"register entry {entry.pk} ({entry.name!r}) moved on while it was being "
                f"resolved: now {resolution}{f'/{via}' if via else ''}"
                f"{f' as {name!r}' if name != entry.name else ''}; left as it is"
            )
    raise CatalogWriteRefused(
        f"register entry {entry.pk} was not updated: deleted, or not running as runtime_engine"
    )


def record_resolution(
    entry: RegisterEntry, resolution: Resolution, *, spec: RegisterSpec, now: datetime
) -> None:
    """Write one answer onto the row it answers, or refuse (see module docstring).

    `spec` is `spec_for(entry, register_spec)`: an organisation is written
    with the country and kind the list vouched for, so both must be known.
    """
    if not (spec.country_code and spec.kind):
        raise ValueError(f"register entry {entry.pk}: no country or kind to vouch for")
    if resolution.diffbot_asked:
        record_diffbot_asked(entry, now=now)
    names = list(resolution.names or (entry.name,))
    common: dict[str, object] = {"names": names, "resolution_attempted_at": now}
    with transaction.atomic():
        if not resolution.domain:
            _update(entry, as_asked=True, **common,
                    resolution=RegisterEntry.Resolution.UNRESOLVED, resolved_via="",
                    unresolved_reason=resolution.reason, organisation=None)
            return
        if not registrable_domain(resolution.domain):
            # record_organisation raises ValueError for this too; checked
            # first so the except below can only ever mean a conflict. The
            # resolver returns keyed domains only, so this is a bug, loudly.
            raise ValueError(f"'{resolution.domain}' has no registrable domain to key on")
        identifiers = (("WIKIDATA", resolution.wikidata_qid),) if resolution.wikidata_qid else ()
        try:
            with transaction.atomic():
                org = record_organisation(
                    domain=resolution.domain, name=entry.name, names=names, kind=spec.kind,
                    country_code=spec.country_code, found_via=f"RESOLVER:{resolution.via}",
                    identifiers=identifiers,
                )
        except ValueError:
            # record_organisation raises on one identifier held by two bodies
            # (register.py): a merge question for item 12, never a guess here.
            # CONFLICT, as item 7 already writes "a Wikidata id already on a
            # different body"; the reason says which conflict it is.
            _update(entry, as_asked=True, **common,
                    resolution=RegisterEntry.Resolution.CONFLICT, resolved_via="",
                    unresolved_reason=UnresolvedReason.IDENTIFIER_CONFLICT, organisation=None)
            return
        # Raising here (moved on, refused) rolls the organisation write back
        # with it: a body keyed on an answer nobody recorded is an orphan.
        _update(entry, as_asked=True, **common,
                resolution=RegisterEntry.Resolution.RESOLVED, resolved_via=resolution.via,
                unresolved_reason="", organisation=org)
