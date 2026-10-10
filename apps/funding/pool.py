"""What a student is evaluated against: catalog programmes and served awards.

**This query is INTERIM and cell selection REPLACES it** (spec section 10.1).
Do not grow it into the real thing. Cell selection picks a supply cell --
destination x level x holder kind -- and asks the catalog for that cell; this
asks the catalog for "anything whose name looks like the student's field", which
is a different question that happens to return rows today. Extending it a filter
at a time produces something that is neither, and that nobody can delete.

Two rules here DO survive the replacement, and both are about what the pool may
not do:

- **It never reads an unserved row.** The serve gate is the catalog's promise
  (spec 8.6); a pool that second-guessed it would put a disputed award in front
  of a student through the back door.
- **It never narrows on a preference.** `excluded_countries` is a refusal and
  filters; `allowed_countries` is a preference and does not. The evaluator
  decides on a preference and says why, where a student can read it -- a pool
  that filtered on one would hide funding the student would have taken, with no
  reason attached anywhere.
- **It never admits a body that is not RECOGNISED** (institution provenance
  gate spec §7.2): a programme on its `evidence_domain`, a HOLDER award on its
  `holder_domain`. The filter sits in the query, before the limit, so gated
  rows never spend it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet

from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.models import FundingOpportunity, Program
from apps.research.models import Organisation, OrganisationDomain, ProvenanceVerdict
from apps.research.provenance import WAITING_REASONS, Verdict


@dataclass(frozen=True)
class PoolResult:
    programs: tuple[Program, ...]
    #: Served HOLDER awards. An award is an application of its own, never a
    #: discount on a programme (owner decision 2026-09-19).
    awards: tuple[FundingOpportunity, ...]
    #: Why the pool is empty, in words a student reads. Empty when it is not.
    #: P1-7: never a silently short pack -- "we found nothing" and "we did not
    #: look" are indistinguishable to the person waiting for a pack.
    empty_reason: str = ""
    #: Bodies left out because their verdict is not computed yet (spec §7.1).
    #: The run records them; the sweep re-runs the student when one resolves.
    pending_bodies: tuple[UUID, ...] = ()


def _pending(
    programs: QuerySet[Program], awards: QuerySet[FundingOpportunity]
) -> tuple[tuple[UUID, ...], int]:
    """(bodies whose verdict is still to come, how many rows wait on them).

    Waiting means no verdict row for the domain, or a WAITING_REASONS one. A
    row that could not be admitted whatever the verdict (evidence off its
    domain) waits on nothing, and neither does a REJECTED body's domain: no
    check will ever run for it.
    """
    settled = ProvenanceVerdict.objects.exclude(reason_code__in=WAITING_REASONS).values("domain")
    admissible = programs.filter(evidence_institutional=True).exclude(evidence_domain="")
    domains = set(
        admissible.exclude(evidence_domain__in=settled).values_list("evidence_domain", flat=True)
    ) | set(
        awards.exclude(holder_domain="")
        .exclude(holder_domain__in=settled)
        .values_list("holder_domain", flat=True)
    )
    owners = dict(
        ProvenanceVerdict.objects.filter(domain__in=domains).values_list(
            "domain", "organisation_id"
        )
    )
    owners.update(
        OrganisationDomain.objects.filter(registrable_domain__in=domains - owners.keys())
        .values_list("registrable_domain", "organisation_id")
    )
    rejected = set(
        Organisation.objects.filter(
            id__in=owners.values(), status=Organisation.Status.REJECTED
        ).values_list("id", flat=True)
    )
    waiting = {domain for domain, body in owners.items() if body not in rejected}
    rows = (
        admissible.filter(evidence_domain__in=waiting).count()
        + awards.filter(holder_domain__in=waiting).count()
    )
    return tuple(sorted({owners[domain] for domain in waiting})), rows


def candidate_pool(
    profile: StudentProfileSnapshot, *, limit: int
) -> PoolResult:
    """Programmes and served awards worth evaluating for this student.

    `limit` is required and has no default: an unbounded pool is an unbounded
    evaluation, and every caller should have had to think about the number.
    """
    programs = Program.objects.filter(name__icontains=profile.target_field)
    if profile.excluded_countries:
        programs = programs.exclude(country_code__in=profile.excluded_countries)
    awards = FundingOpportunity.objects.filter(scope_type="HOLDER", served=True)
    # Any suspension at all, on `suspension_quote` rather than a year match on
    # `suspended_for`. The quote is the marker: a suspension naming no intake
    # leaves `suspended_for` blank and is still a suspension (that field's own
    # comment on the model), so the year test said nothing about exactly the
    # case with no year to test. `funding_opportunity_served_not_suspended`
    # now makes served-and-suspended impossible at the database, so this
    # filters nothing in practice -- it is kept, and kept total rather than
    # clever, because the unserve sweep for a withdrawn award that nothing
    # re-reads is still owed (spec section 19).
    awards = awards.filter(suspension_quote="")

    pending: tuple[UUID, ...] = ()
    waiting_rows = 0
    matching_programs, matching_awards = programs, awards
    if settings.PROVENANCE_GATE_ENFORCED:
        pending, waiting_rows = _pending(programs, awards)
        # A REJECTED body is never checked again (_pending, the checker), so its
        # last RECOGNISED verdict is stale and must not keep admitting it.
        recognised = (
            ProvenanceVerdict.objects.filter(verdict=Verdict.RECOGNISED)
            .exclude(organisation__status=Organisation.Status.REJECTED)
            .values("domain")
        )
        programs = programs.filter(evidence_institutional=True, evidence_domain__in=recognised)
        awards = awards.filter(holder_domain__in=recognised)

    # Ordered by a stable key so `limit` takes the same rows on every call. Any
    # deterministic order will do here -- there is no ranking at this stage, and
    # pretending otherwise would put scoring in two places.
    chosen = tuple(programs.order_by("canonical_key")[:limit])
    chosen_awards = tuple(awards.order_by("canonical_key")[:limit])

    reason = ""
    if not chosen and not chosen_awards:
        if pending:
            # Never "no programme matches" while checks are pending (spec §7.1):
            # that is "we did not look yet", which P1-7 says must read differently.
            reason = (
                "1 programme or award is still being checked"
                if waiting_rows == 1
                else f"{waiting_rows} programmes or awards are still being checked"
            ) + " and will appear if confirmed."
        elif gated := (
            matching_programs.count() + matching_awards.count()
            if settings.PROVENANCE_GATE_ENFORCED
            else 0
        ):
            # Every match was gated out: "none matches" would be false.
            reason = (
                "1 matching programme or award is not shown because its"
                if gated == 1
                else f"{gated} matching programmes or awards are not shown because their"
            ) + " institution's recognition is not confirmed."
        else:
            countries = (
                f", excluding {', '.join(sorted(profile.excluded_countries))}"
                if profile.excluded_countries
                else ""
            )
            reason = (
                f"No programme or award in the catalogue matches {profile.target_field} "
                f"for a {profile.intended_intake.year} intake{countries}. "
                "This is what we have read so far, not a statement that none exists."
            )
    return PoolResult(
        programs=chosen, awards=chosen_awards, empty_reason=reason, pending_bodies=pending
    )
