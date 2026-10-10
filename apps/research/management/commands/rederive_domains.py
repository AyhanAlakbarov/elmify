"""Re-key every stored registrable domain after the hosts.py fix (spec §5.6).

Operator-run once per database, idempotent, writes the catalogue (run with
DATABASE_ROLE=runtime_engine). A body keyed on a value that no longer keys to
itself -- `blogspot.com`, `github.io` -- merged unrelated publishers, and the
hosts that made it are not stored, so it cannot be split: it is deleted with
its identifiers, every link to it is cleared, and the next discovery run
re-records each publisher under its own key. No production database exists
(spec §5.6), so this touches developer and staging data only.

A HOLDER award's `organisation` link is NOT NULL by
`funding_opportunity_scope_shape_valid`, so a merged body's HOLDER awards are
never nulled: `rederive_holder_domains` runs first, and `unkey` re-points each
one to `record_organisation` for its own (now re-derived) holder domain. A
body is left in place, and named on stdout, if any of its HOLDER awards
cannot be re-keyed this way.

A secondary `OrganisationDomain` gone stale on a body whose `primary_domain`
still keys to itself is not itself a merge -- only that row is dropped, never
the body.

ponytail: a body merged under `google.com` (sites.google.com pages) still keys
to itself and is not detected; recreate such a dev database instead.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db import models, transaction

from apps.funding.models import FundingOpportunity, FundingOpportunityEvidenceClaim
from apps.research.hosts import registrable_domain
from apps.research.models import (
    Organisation,
    OrganisationDomain,
    OrganisationIdentifier,
    RegisterEntry,
    RegisterEntryPartner,
)
from apps.research.register import record_organisation


def _stale(value: str) -> bool:
    return bool(value) and registrable_domain(value) != value


def merged_organisations() -> set[UUID]:
    """Bodies whose own `primary_domain` no longer keys to itself. These were
    silently merged under the old suffix rule and are unkeyed entirely."""
    return {
        organisation_id
        for organisation_id, value in Organisation.objects.values_list("id", "primary_domain")
        if _stale(value)
    }


def stale_secondary_domain_ids(merged: set[UUID]) -> list[UUID]:
    """A secondary `OrganisationDomain` gone stale on a body that keeps its
    own key: only the row is dropped, the body stays (its primary domain,
    checked by `merged_organisations`, is the only thing that names a merge).
    """
    return [
        domain_id
        for domain_id, organisation_id, value in OrganisationDomain.objects.values_list(
            "id", "organisation_id", "registrable_domain"
        )
        if organisation_id not in merged and _stale(value)
    ]


@transaction.atomic
def unkey(organisation_id: UUID) -> str:
    """Delete a merged body. Returns "" on success, or the reason it was left
    in place: a HOLDER award whose holder_domain has no registrable domain to
    re-point it to. Nothing is written before every award is checked, so a
    body that cannot be fully re-keyed is left exactly as it was.
    """
    awards = list(
        FundingOpportunity.objects.filter(organisation_id=organisation_id, scope_type="HOLDER")
    )
    for award in awards:
        if not registrable_domain(award.holder_domain):
            return (
                f"award {award.id} holder_domain {award.holder_domain!r} "
                "has no registrable domain"
            )

    for award in awards:
        new_organisation = record_organisation(
            domain=award.holder_domain,
            name=award.holder_name or award.name,
            kind=award.holder or "UNSTATED",
            country_code="",
            found_via="REDERIVE",
        )
        FundingOpportunity.objects.filter(id=award.id).update(organisation=new_organisation)

    RegisterEntry.objects.filter(organisation_id=organisation_id).update(
        organisation=None, resolution=RegisterEntry.Resolution.UNRESOLVED, resolved_via=""
    )
    RegisterEntryPartner.objects.filter(organisation_id=organisation_id).update(
        organisation=None, disposition=RegisterEntryPartner.Disposition.NO_KEY
    )
    Organisation.objects.filter(parent_id=organisation_id).update(parent=None)
    OrganisationIdentifier.objects.filter(organisation_id=organisation_id).delete()
    OrganisationDomain.objects.filter(organisation_id=organisation_id).delete()
    Organisation.objects.filter(id=organisation_id).delete()
    return ""


def rederive_holder_domains() -> int:
    """From the page the award was read on, when one is stored."""
    changed = 0
    rows = FundingOpportunity.objects.exclude(holder_domain="").values_list("id", "holder_domain")
    for opportunity_id, holder_domain in rows:
        final_url = (
            FundingOpportunityEvidenceClaim.objects.filter(
                opportunity_id=opportunity_id, evidence_claim__snapshot__isnull=False
            )
            .values_list("evidence_claim__snapshot__final_url", flat=True)
            .first()
        )
        new = registrable_domain(final_url) if final_url else registrable_domain(holder_domain)
        if new != holder_domain:
            FundingOpportunity.objects.filter(id=opportunity_id).update(holder_domain=new)
            changed += 1
    return changed


def rederive_column(model: type[models.Model], field: str) -> int:
    """For a column whose source URL is not stored: re-key the value itself."""
    changed = 0
    for row_id, value in model._default_manager.exclude(**{field: ""}).values_list("id", field):
        if _stale(value):
            model._default_manager.filter(id=row_id).update(**{field: registrable_domain(value)})
            changed += 1
    return changed


class Command(BaseCommand):
    help = (
        "Re-key stored registrable domains after the private-suffix fix (spec §5.6). "
        "Writes the catalogue: run with DATABASE_ROLE=runtime_engine."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        # Holder domains first: a merged body's awards must carry their own
        # re-derived domain before `unkey` re-points them off that body.
        holders = rederive_holder_domains()

        merged = merged_organisations()
        stale_domain_ids = stale_secondary_domain_ids(merged)
        if stale_domain_ids:
            OrganisationDomain.objects.filter(id__in=stale_domain_ids).delete()

        unkeyed = 0
        skipped: list[str] = []
        for organisation_id in sorted(merged):
            reason = unkey(organisation_id)
            if reason:
                skipped.append(f"organisation {organisation_id}: {reason}")
            else:
                unkeyed += 1

        partners = rederive_column(RegisterEntryPartner, "listed_domain")
        contacts = rederive_column(RegisterEntry, "contact_domain")

        self.stdout.write(
            f"unkeyed {unkeyed} merged organisations; re-derived {holders} holder "
            f"domains, {partners} partner domains, {contacts} contact domains"
        )
        if stale_domain_ids:
            self.stdout.write(f"cleared {len(stale_domain_ids)} stale secondary domains")
        for line in skipped:
            self.stdout.write(f"cannot unkey {line}")
