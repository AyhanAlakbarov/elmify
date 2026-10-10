"""The one door into the Organisation register.

Every discovery route reaches the same bodies -- a national register, a hub
page, a pointer and a search all find the DAAD -- so the only interesting part
of writing a row is deciding it is the same row. That decision lives here and
nowhere else.

Lookup order, and it is the whole function:

1. `OrganisationDomain` by registrable domain -- **any** of the organisation's
   domains, not its `primary_domain`.
2. failing that, `OrganisationIdentifier` by any identifier the caller supplied;
   on a hit the new domain attaches to that organisation.
3. failing both, create.

**Never on a name.** Adjacent organisations share them -- Carl-Zeiss-Stiftung
and ZEISS, Inönü Vakfi and Inönü Üniversitesi -- and a merge made on a
coincidence is not undone by the route that made it.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
section 6.1.
"""

from __future__ import annotations

from collections.abc import Sequence

from django.db import transaction

from apps.research.hosts import registrable_domain
from apps.research.models import Organisation, OrganisationDomain, OrganisationIdentifier

#: (scheme, value) pairs, in `OrganisationIdentifier.SCHEMES`.
Identifiers = Sequence[tuple[str, str]]


def record_organisation(
    *,
    domain: str,
    name: str,
    kind: str,
    country_code: str,
    found_via: str,
    identifiers: Identifiers = (),
    names: Sequence[str] = (),
    status: str = Organisation.Status.CANDIDATE,
    rejected_reason: str = "",
) -> Organisation:
    """The organisation this domain belongs to, creating it only if it is new.

    `found_via` is one route tag, appended to the organisation's list if it is
    not already there -- the tally in section 15 counts organisations per route,
    so a weekly sweep re-recording the same body must not make it look like
    fifty-two findings.

    `status` and `rejected_reason` apply **only when the row is created**. A
    later route never overwrites them: the saving a REJECTED infrastructure host
    buys is precisely that the next sweep gets the refusal back instead of a
    fresh CANDIDATE to go and fetch.
    """
    key = registrable_domain(domain)
    if not key:
        # "" is what registrable_domain returns for an IP address, an unknown
        # suffix and an empty string. Keying on it would merge every unkeyable
        # host into one organisation -- the silent merge the Public Suffix List
        # is here to prevent -- so a caller that cannot key a host skips it.
        raise ValueError(f"'{domain}' has no registrable domain to key on")

    with transaction.atomic():
        known = (
            OrganisationDomain.objects.select_related("organisation")
            .filter(registrable_domain=key)
            .first()
        )
        if known is not None:
            return _record_again(known.organisation, found_via, name, names, identifiers)

        for scheme, value in identifiers:
            match = (
                OrganisationIdentifier.objects.select_related("organisation")
                .filter(scheme=scheme, value=value)
                .first()
            )
            if match is not None:
                organisation = match.organisation
                OrganisationDomain.objects.create(
                    organisation=organisation, registrable_domain=key, found_via=[found_via]
                )
                return _record_again(organisation, found_via, name, names, identifiers)

        organisation = Organisation.objects.create(
            primary_domain=key,
            name=name,
            names=_merged([name], names),
            kind=kind,
            country_code=country_code,
            found_via=[found_via],
            status=status,
            rejected_reason=rejected_reason,
        )
        OrganisationDomain.objects.create(
            organisation=organisation, registrable_domain=key, found_via=[found_via]
        )
        _attach_identifiers(organisation, identifiers)
        return organisation


def _record_again(
    organisation: Organisation,
    found_via: str,
    name: str,
    names: Sequence[str],
    identifiers: Identifiers,
) -> Organisation:
    """A body we already hold, reached again. Labels and route tags accumulate;
    `name`, `kind`, `status` and `primary_domain` are what the first route
    recorded and stay that way."""
    merged_names = _merged(organisation.names, [name], names)
    tags = list(organisation.found_via)
    if found_via not in tags:
        tags.append(found_via)

    if merged_names != organisation.names or tags != organisation.found_via:
        organisation.names = merged_names
        organisation.found_via = tags
        organisation.save(update_fields=["names", "found_via"])

    _attach_identifiers(organisation, identifiers)
    return organisation


def _attach_identifiers(organisation: Organisation, identifiers: Identifiers) -> None:
    for scheme, value in identifiers:
        row, _ = OrganisationIdentifier.objects.get_or_create(
            scheme=scheme, value=value, defaults={"organisation": organisation}
        )
        if row.organisation_id != organisation.pk:
            # One identifier, two organisations is a question, not a merge:
            # guessing either way silently joins or splits a register row.
            # ponytail: a plain raise, because there is nowhere to file the
            # question yet. The resolution queue (spec section 11) is where it
            # belongs once that exists; until then a caller gets a loud
            # conflict rather than a register quietly holding one id against
            # two bodies.
            raise ValueError(
                f"{scheme}:{value} is already held by organisation {row.organisation_id}, "
                f"not {organisation.pk}"
            )


def _merged(*groups: Sequence[str]) -> list[str]:
    """Every label, deduplicated, in the order they were first seen.

    A label is never a lookup key, so this list is only ever scored against --
    which is why it may hold ZEISS's name and the foundation's without harm.
    """
    seen: dict[str, None] = {}
    for label in (item for group in groups for item in group):
        if label:
            seen.setdefault(label, None)
    return list(seen)
