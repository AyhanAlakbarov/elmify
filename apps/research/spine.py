"""Pool -> facts -> evaluate -> pack: the path from the catalogue to a student.

The two halves of this engine were never joined. The reader wrote
`FundingOpportunity` rows nothing read; the evaluator and `build_pack` were
reached from tests only; the one live path that made a pack fetched
`https://official.example.test/program.json` and hard-coded `eligible=True`.
This module is the join, and `research.services.handle_research_message` is its
one caller.

**Every failure here is published, never swallowed** (P1-7). An empty pool, a
row that will not translate, a missing rate table and a profile too thin to
decide on all end in a pack that says so in a sentence a student reads. "We
found nothing" and "we did not look" are indistinguishable from the outside,
and the second one is the bug.

Spec sections 10.1-10.3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.evaluation import (
    AwardCandidateFacts,
    CandidateFacts,
    evaluate_award,
)
from apps.funding.facts import award_facts, program_facts
from apps.funding.fx import RateTable
from apps.funding.models import (
    BenefitRule,
    CostComponent,
    FundingBenefit,
    FundingOpportunity,
    FundingOpportunityProgram,
    OfficialEvidenceClaim,
    Program,
)
from apps.funding.pack import Pack, build_pack
from apps.funding.pool import candidate_pool

logger = logging.getLogger(__name__)

#: How many catalogue rows one student's evaluation may consider. Bounded
#: because the pool query is a `name__icontains` today, and an unbounded pool is
#: an unbounded evaluation. Cell selection replaces the query and should revisit
#: the number with it (spec 10.1).
POOL_LIMIT = 50


@dataclass
class SpineResult:
    pack: Pack
    #: (program_id or award_id, the catalog row) for everything packed, so the
    #: caller can write a `RecommendationCandidate` pointing at its source.
    programs: dict[str, Program] = field(default_factory=dict)
    awards: dict[str, FundingOpportunity] = field(default_factory=dict)
    #: program_id / award_id -> the ORIGIN url a claim about it rests on.
    #: Provenance comes from the origin or it is not provenance: a candidate
    #: whose evidence url was synthesised from a canonical_key showed the
    #: student "https://program:<uuid>" under the label "Official source".
    origins: dict[str, str] = field(default_factory=dict)
    #: Rows that could not be translated. Counted and named -- one bad row never
    #: fails a pack, and never disappears from it either.
    degraded: tuple[str, ...] = ()
    #: Candidates whose own eligibility a human must judge. The caller opens a
    #: TENANT-SCOPED task for each: a question about one student's eligibility
    #: belongs to that student's agency, while catalog questions are the
    #: platform's alone (spec 11).
    review: tuple[str, ...] = ()
    #: Bodies the pool left out while their verdict is computed (spec §7.1).
    pending_bodies: tuple[UUID, ...] = ()


def _empty(reason: str) -> SpineResult:
    return SpineResult(pack=Pack(fee_free=(), paid=(), awards=(), excluded=(), empty_reason=reason))


def build_student_pack(
    profile: StudentProfileSnapshot | None,
    *,
    rates: RateTable | None,
    today: date,
) -> SpineResult:
    """Everything between a student's profile and a pack they can act on."""
    if profile is None:
        # A MinimalProfile carries a field, an intake, a budget and nothing
        # else. The gates decide on nationality, academic history and language
        # evidence, so widening one into a full snapshot would mean inventing
        # exactly the facts the engine is about to reason from.
        return _empty(
            "This student's profile is the short form. A full consultation "
            "(nationality, academic history, languages) is needed before "
            "funding can be matched."
        )
    if rates is None:
        # Deliberately loud. `parse_ecb_daily` and `parse_cbar_daily` exist and
        # have no production caller, so nothing loads a rate table on a
        # deployed worker yet. Costs and budgets are compared in a base
        # currency, and a made-up table would produce a confident wrong gap.
        logger.warning("no exchange-rate table available; publishing an empty pack")
        return _empty(
            "No exchange-rate table is loaded, so costs in different currencies "
            "cannot be compared yet. Your pack will be built as soon as one is."
        )

    pool = candidate_pool(profile, limit=POOL_LIMIT)
    if not pool.programs and not pool.awards:
        empty = _empty(pool.empty_reason)
        empty.pending_bodies = pool.pending_bodies
        return empty

    origins = _origins(pool.programs, pool.awards)

    program_ids = [program.id for program in pool.programs]
    costs_by_program: dict[object, list[CostComponent]] = {}
    for cost in CostComponent.objects.filter(program_id__in=program_ids):
        costs_by_program.setdefault(cost.program_id, []).append(cost)

    # The money a programme's OWN page states: the served PROGRAM-scope rows
    # `write_funding_decision` wrote against it. That is what
    # `CandidateFacts.benefits` means (spec 10.2, and the programme card's
    # "the funding attached", 10.4). A HOLDER award is NOT this -- it is an
    # application of its own and never a discount on a programme (pool.py,
    # owner 2026-09-19).
    #
    # INSTITUTION scope is deliberately excluded. Those rows anchor to the
    # institution rather than the programme, and CLAUDE.md holds an open check
    # on them -- an INSTITUTION-scope row's origin is not yet verified against
    # `institution.official_website`. A university-wide waiver read off the
    # wrong host would cut the gap of every programme that institution offers,
    # in one row, so it waits for that check rather than riding in on this one.
    attached_by_program: dict[object, list[object]] = {}
    routes: dict[object, str] = {}
    durations: dict[object, int | None] = {}
    for program_id, opportunity_id, route, months in FundingOpportunityProgram.objects.filter(
        program_id__in=program_ids,
        opportunity__scope_type="PROGRAM",
        opportunity__served=True,
        # The same total test as the pool's, for the same reason: the quote is
        # the marker, because a suspension naming no intake leaves
        # `suspended_for` blank and is still a suspension.
        opportunity__suspension_quote="",
    ).values_list(
        "program_id", "opportunity_id", "opportunity__route", "opportunity__duration_months"
    ):
        attached_by_program.setdefault(program_id, []).append(opportunity_id)
        routes[opportunity_id] = route
        durations[opportunity_id] = months

    award_ids = [award.id for award in pool.awards]
    benefits_by_opportunity: dict[object, list[FundingBenefit]] = {}
    for benefit in FundingBenefit.objects.filter(
        opportunity_id__in=[*award_ids, *routes]
    ):
        benefits_by_opportunity.setdefault(benefit.opportunity_id, []).append(benefit)
    rules_by_benefit: dict[object, list[BenefitRule]] = {}
    for rule in BenefitRule.objects.filter(
        benefit_id__in=[b.id for group in benefits_by_opportunity.values() for b in group]
    ):
        rules_by_benefit.setdefault(rule.benefit_id, []).append(rule)

    programs: dict[str, Program] = {}
    program_candidates: list[CandidateFacts] = []
    degraded: list[str] = []
    for program in pool.programs:
        benefits = tuple(
            benefit
            for opportunity_id in attached_by_program.get(program.id, ())
            for benefit in benefits_by_opportunity.get(opportunity_id, ())
        )
        try:
            facts = program_facts(
                program,
                costs=tuple(costs_by_program.get(program.id, ())),
                benefits=benefits,
                rules=tuple(
                    rule for benefit in benefits for rule in rules_by_benefit.get(benefit.id, ())
                ),
                routes=routes,
                durations=durations,
            )
        # Defence in depth, and deliberately broad. Reaching this from the
        # pool is impossible today -- `program_country_iso3166_alpha2` and
        # `program_duration_months_range` refuse the two obvious bad rows at the
        # database, so anything that survived INSERT survives translation
        # (measured 2026-09-23; both raised IntegrityError before the translator
        # was reached). It stays because the catalogue's constraints are the
        # first line and this is the second: the day a column is added without a
        # matching check, this is what stops one row emptying a pack.
        except Exception as error:  # noqa: BLE001 - one bad row never fails a pack
            logger.warning("programme %s could not be translated: %s", program.id, error)
            degraded.append(f"{program.name}: {error}")
            continue
        programs[facts.program_id] = program
        program_candidates.append(facts)

    awards: dict[str, FundingOpportunity] = {}
    award_candidates: list[AwardCandidateFacts] = []
    for award in pool.awards:
        benefits = tuple(benefits_by_opportunity.get(award.id, ()))
        rules = tuple(
            rule for benefit in benefits for rule in rules_by_benefit.get(benefit.id, ())
        )
        try:
            award_fact = award_facts(award, benefits=benefits, rules=rules)
        except Exception as error:  # noqa: BLE001 - same rule as above
            logger.warning("award %s could not be translated: %s", award.id, error)
            degraded.append(f"{award.name}: {error}")
            continue
        awards[award_fact.award_id] = award
        award_candidates.append(award_fact)

    pack = build_pack(
        profile,
        program_candidates,
        rates,
        awards=award_candidates,
        today=today,
    )

    # A POSSIBLY_ELIGIBLE_REVIEW outcome is work for a human, NOT a hold on the
    # student's pack: publication stays un-gated by counsellor review (phased
    # requirements section 38).
    #
    # Programmes are read off the pack rather than evaluated again: anything
    # not ELIGIBLE is already in `excluded` carrying its own outcome, so a third
    # `evaluate` per programme bought nothing. (This list was empty by
    # construction until 2026-09-23, when programmes stopped being passed
    # `rules=()` -- a programme carried no applicant condition, so nothing could
    # ever be undecidable about one.)
    review = [
        item.program_id
        for item in pack.excluded
        if item.reason_code == "POSSIBLY_ELIGIBLE_REVIEW"
    ]
    # Awards are not: a review-outcome award is PACKED, not excluded, so it
    # appears nowhere the pack already records.
    review += [
        item.award_id
        for item in award_candidates
        if evaluate_award(profile, item, today=today).outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    ]

    return SpineResult(
        pack=pack,
        programs=programs,
        awards=awards,
        origins=origins,
        degraded=tuple(degraded),
        review=tuple(review),
        pending_bodies=pool.pending_bodies,
    )


def _origins(
    programs: tuple[Program, ...], awards: tuple[FundingOpportunity, ...]
) -> dict[str, str]:
    """The official page each catalogue row's claims were verified against.

    Two queries, one per side. An earlier version of this docstring claimed
    that while the code ran `.first()` inside the loop -- up to `POOL_LIMIT`
    queries a side, and a comment asserting a property the code does not have
    is worse than no comment.

    The fallback is still a REAL address -- the institution's own website, or
    the holder organisation's registered domain -- never a string built out of
    an internal key. A row with neither gets no entry, and its candidate is
    skipped rather than shown a URL nobody can follow.
    """
    found: dict[str, str] = {}
    # `evidence_claims` is a many-to-many, so the row id comes back through the
    # reverse accessor rather than off the claim.
    by_program = dict(
        OfficialEvidenceClaim.objects.filter(program__in=programs)
        .values_list("program", "source__canonical_url")
    )
    for program in programs:
        url = by_program.get(program.id)
        if url is None and program.institution is not None:
            url = program.institution.official_website or None
        if url:
            found[str(program.id)] = url

    by_award = dict(
        OfficialEvidenceClaim.objects.filter(fundingopportunity__in=awards)
        .values_list("fundingopportunity", "source__canonical_url")
    )
    for award in awards:
        url = by_award.get(award.id)
        if url is None and award.organisation is not None:
            url = award.organisation.official_website or (
                f"https://{award.organisation.primary_domain}"
            )
        if url:
            found[str(award.id)] = url
    return found
