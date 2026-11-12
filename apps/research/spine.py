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
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any
from uuid import UUID

from django.db.models import Q

from apps.accounts.schemas import StudentProfileSnapshot
from apps.documents.referee_needs import needs_for
from apps.funding.conditions import unevaluable_condition_reasons
from apps.funding.cycle_evidence import deadline_student, to_evidence
from apps.funding.evaluation import (
    AwardCandidateFacts,
    CandidateFacts,
    _strip_undecidable_secondary_routes,
    evaluate_award,
    needs_selective_funding,
    scheme_pays_for,
    schemes_paying_for,
)
from apps.funding.facts import award_facts, program_facts
from apps.funding.fx import RateTable, UnconvertibleCurrency, convert
from apps.funding.models import (
    BenefitRule,
    CostComponent,
    FundingBenefit,
    FundingCycleVerification,
    FundingOpportunity,
    FundingOpportunityProgram,
    Institution,
    OfficialEvidenceClaim,
    OutcomeCalibrationRecord,
    Program,
    ProgramEvidenceClaim,
    ProgramStatement,
)
from apps.funding.pack import Pack, build_pack
from apps.funding.pool import candidate_pool
from apps.funding.probability import (
    POST_ADMISSION_GOV_CORRELATION,
    ProbabilityEstimate,
    estimate_program_admission_chance,
    estimate_scholarship_chance,
    is_post_admission_gov_scholarship,
    joint_admission_and_funding_chance_pct,
    post_admission_gov_conditional_pct,
)
from apps.funding.regions import REGIONS
from apps.funding.transcript_eligibility import (
    _parse_iso_or_human_date,
    evaluate_program_statement,
    is_coursework_or_credit_statement,
    is_program_scholarship_suspended_for_intake,
    parse_scholarship_status_statement,
)
from apps.funding.validity import (
    Evidence,
    cycle_validity,
    default_intake_start_for_country,
    intake_matches_target,
    intake_start_years,
    select_deadline,
)
from apps.research.cycle_verification import cadence_of
from apps.research.hosts import registrable_domain
from apps.research.models import Organisation, OrganisationDomain, WinnerCohortProfile

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
    #: program_id / award_id -> ProbabilityEstimate (chance_pct and calibration features).
    probabilities: dict[str, ProbabilityEstimate] = field(default_factory=dict)
    #: program_id -> ISO deadline string when known from catalogue evidence.
    program_deadlines: dict[str, str] = field(default_factory=dict)
    #: program_id / award_id -> the facts the evaluator decided on, so the
    #: publisher can copy what the scholarship page shows (candidate_details).
    program_facts: dict[str, CandidateFacts] = field(default_factory=dict)
    award_facts: dict[str, AwardCandidateFacts] = field(default_factory=dict)


def _empty(reason: str) -> SpineResult:
    return SpineResult(pack=Pack(fee_free=(), paid=(), awards=(), excluded=(), empty_reason=reason))


@dataclass
class _AttachedOpportunities:
    by_program: dict[object, list[object]] = field(default_factory=dict)
    suspended_by_program: dict[object, list[FundingOpportunity]] = field(default_factory=dict)
    routes: dict[object, str] = field(default_factory=dict)
    durations: dict[object, int | None] = field(default_factory=dict)
    tuition_levels: dict[object, str] = field(default_factory=dict)
    by_id: dict[object, FundingOpportunity] = field(default_factory=dict)

    def add_active(self, program_id: object, opp: FundingOpportunity) -> None:
        prog_opps = self.by_program.setdefault(program_id, [])
        if opp.id not in prog_opps:
            prog_opps.append(opp.id)
        self.routes[opp.id] = opp.route
        self.durations[opp.id] = opp.duration_months
        self.tuition_levels[opp.id] = opp.tuition
        self.by_id[opp.id] = opp

    def add_or_suspend(self, program_id: object, opp: FundingOpportunity) -> None:
        if opp.suspension_quote:
            self.suspended_by_program.setdefault(program_id, []).append(opp)
            return
        self.add_active(program_id, opp)


def _program_deadline_candidates(
    programs: tuple[Program, ...], nationality: str
) -> dict[object, list[tuple[int, date]]]:
    program_ids = [program.id for program in programs]
    student_nat = nationality.upper()
    is_eea_student = student_nat in REGIONS["EEA"].countries
    prog_country_by_id = {p.id: (p.country_code or "").upper() for p in programs}
    deadlines_by_program: dict[object, list[tuple[int, date]]] = {}
    for prog_id, claim_text in ProgramEvidenceClaim.objects.filter(
        program_id__in=program_ids,
        evidence_claim__claim_class=OfficialEvidenceClaim.ClaimClass.DEADLINE,
    ).values_list("program_id", "evidence_claim__claim"):
        stripped_claim = claim_text.removeprefix("Application deadline:").strip()
        head, _, tail = stripped_claim.partition(": ")
        parsed_d = _parse_iso_or_human_date(head.strip())
        if parsed_d is None:
            continue
        prog_country = prog_country_by_id.get(prog_id, "")
        is_domestic_or_eea = (
            student_nat == prog_country
            or (
                (not prog_country or prog_country in REGIONS["EEA"].countries)
                and is_eea_student
            )
        )
        lower_tail = tail.casefold()
        mentions_non_eu = any(
            k in lower_tail
            for k in (
                "non-eu",
                "non-eea",
                "visa",
                "third-country",
                "international",
                "overseas",
            )
        )
        cleaned_for_eu = re.sub(
            r"\bnon[-\s]*(?:eu\s*/\s*eea|eu|eea|domestic)\b", "", lower_tail
        )
        mentions_eu = any(
            k in cleaned_for_eu
            for k in (
                "eu/eea",
                "eu / eea",
                "eu citizens",
                "eea citizens",
                "domestic",
                "home student",
            )
        )
        if mentions_non_eu and not mentions_eu:
            priority = 0 if not is_domestic_or_eea else 2
        elif mentions_eu and not mentions_non_eu:
            priority = 0 if is_domestic_or_eea else 2
        else:
            priority = 1
        deadlines_by_program.setdefault(prog_id, []).append((priority, parsed_d))
    return deadlines_by_program


def _collect_attached_opportunities(
    programs: tuple[Program, ...],
) -> _AttachedOpportunities:
    program_ids = [program.id for program in programs]
    attached = _AttachedOpportunities()
    join_pairs = list(
        FundingOpportunityProgram.objects.filter(
            program_id__in=program_ids,
            opportunity__scope_type__in=("PROGRAM", "INSTITUTION"),
        )
        .filter(
            Q(opportunity__served=True, opportunity__suspension_quote="")
            | Q(
                opportunity__scope_type="PROGRAM",
                opportunity__agreement="AGREED",
                opportunity__suspension_quote__gt="",
            )
        )
        .values_list("program_id", "opportunity_id")
    )
    joined_opps_by_id = (
        {
            opp.id: opp
            for opp in FundingOpportunity.objects.filter(
                id__in={opp_id for _, opp_id in join_pairs}
            )
        }
        if join_pairs
        else {}
    )
    for join_prog_id, join_opp_id in join_pairs:
        opp = joined_opps_by_id.get(join_opp_id)
        if opp is not None:
            attached.add_or_suspend(join_prog_id, opp)

    for opp in FundingOpportunity.objects.filter(
        program_id__in=program_ids,
        scope_type="PROGRAM",
    ).filter(
        Q(served=True, suspension_quote="")
        | Q(agreement="AGREED", suspension_quote__gt="")
    ):
        if opp.program_id is not None:
            attached.add_or_suspend(opp.program_id, opp)

    programs_by_institution: dict[UUID, list[UUID]] = {}
    for program in programs:
        if program.institution_id is not None:
            programs_by_institution.setdefault(program.institution_id, []).append(program.id)
    if not programs_by_institution:
        return attached

    institution_domains = {
        inst_id: registrable_domain(website)
        for inst_id, website in Institution.objects.filter(
            id__in=programs_by_institution
        ).values_list("id", "official_website")
    }
    primary_domains = {d for d in institution_domains.values() if d}
    org_ids_by_domain: dict[str, UUID] = {}
    domains_by_org_id: dict[UUID, set[str]] = {}
    if primary_domains:
        matched_org_ids = list(
            OrganisationDomain.objects.filter(
                registrable_domain__in=primary_domains
            ).values_list("organisation_id", flat=True)
        )
        if matched_org_ids:
            for org_id, reg_dom in OrganisationDomain.objects.filter(
                organisation_id__in=matched_org_ids
            ).values_list("organisation_id", "registrable_domain"):
                org_ids_by_domain[reg_dom] = org_id
                domains_by_org_id.setdefault(org_id, set()).add(reg_dom)

    inst_opportunities = list(
        FundingOpportunity.objects.filter(
            institution_id__in=programs_by_institution,
            scope_type="INSTITUTION",
            served=True,
            suspension_quote="",
        ).prefetch_related("evidence_claims__source")
    )
    for opp in inst_opportunities:
        if opp.institution_id is None:
            continue
        expected_domain = institution_domains.get(opp.institution_id, "")
        allowed_domains: set[str] = {expected_domain} if expected_domain else set()
        if expected_domain and expected_domain in org_ids_by_domain:
            allowed_domains |= domains_by_org_id.get(
                org_ids_by_domain[expected_domain], set()
            )
        claim_urls = [
            claim.source.canonical_url
            for claim in opp.evidence_claims.all()
            if claim.source_id
        ]
        if not (
            allowed_domains
            and claim_urls
            and all(registrable_domain(url) in allowed_domains for url in claim_urls)
        ):
            continue
        for prog_id in programs_by_institution.get(opp.institution_id, ()):
            attached.add_active(prog_id, opp)
    return attached


def _program_coursework_warnings(
    program: Program,
    prog_stmts: Sequence[ProgramStatement],
    profile: StudentProfileSnapshot,
    *,
    today: date,
) -> tuple[str, ...]:
    prog_warnings: list[str] = []
    if prog_stmts:
        cw_outcomes = [
            evaluate_program_statement(
                stmt.text,
                profile,
                kind=stmt.kind,
                as_of=today,
                only_coursework=True,
            ).outcome
            for stmt in prog_stmts
            if stmt.requirement == "REQUIRED"
            and stmt.kind in ("COMPETENCY", "LANGUAGE", "OTHER")
            and is_coursework_or_credit_statement(stmt.text)
        ]
        if "FAILED" in cw_outcomes:
            prog_warnings.append(
                "Coursework prerequisite check needed: verify your transcript credits "
                "against this programme's subject requirements"
            )
        elif any(o in ("BORDERLINE", "CONDITIONAL_BRIDGE") for o in cw_outcomes):
            prog_warnings.append(
                "Coursework prerequisites may require conditional bridge modules or "
                "transcript verification"
            )
    if (
        program.referee_requirements
        and profile.experience is not None
        and len(profile.experience) == 0
    ):
        ref_need = needs_for(program.referee_requirements)
        if ref_need.kind is not None and ref_need.kind.value == "PROFESSIONAL_ONLY":
            prog_warnings.append(
                "Referee check needed: this programme requires professional referees, "
                "and no work experience is recorded on your profile"
            )
    if program.portfolio_led:
        prog_warnings.append(
            "Portfolio required: this programme requires an artistic, design, or "
            "architectural portfolio at application"
        )
    return tuple(prog_warnings)


def _estimate_pack_probabilities(
    profile: StudentProfileSnapshot,
    *,
    rates: RateTable,
    today: date,
    programs: dict[str, Program],
    awards: dict[str, FundingOpportunity],
    prog_facts_by_id: dict[str, CandidateFacts],
    award_facts_by_id: dict[str, AwardCandidateFacts],
    award_candidates: Sequence[AwardCandidateFacts],
    statements_by_program: dict[object, list[ProgramStatement]],
    attached_schemes: dict[str, tuple[str, ...]],
    attached_selective_opps_by_program: dict[
        str, list[tuple[FundingOpportunity, AwardCandidateFacts]]
    ],
) -> tuple[dict[str, ProbabilityEstimate], dict[str, int | None]]:
    all_prog_uuids = [programs[pid].id for pid in prog_facts_by_id if pid in programs]
    all_award_uuids = list(
        {
            *(awards[aid].id for aid in award_facts_by_id if aid in awards),
            *(
                att_opp.id
                for pid in prog_facts_by_id
                for att_opp, _ in attached_selective_opps_by_program.get(pid, ())
            ),
        }
    )
    winner_cohorts_by_prog: dict[UUID, WinnerCohortProfile] = (
        {
            wc.program_id: wc
            for wc in WinnerCohortProfile.objects.filter(program_id__in=all_prog_uuids)
            if wc.program_id is not None
        }
        if all_prog_uuids
        else {}
    )
    winner_cohorts_by_opp: dict[UUID, WinnerCohortProfile] = (
        {
            wc.opportunity_id: wc
            for wc in WinnerCohortProfile.objects.filter(
                opportunity_id__in=all_award_uuids
            )
            if wc.opportunity_id is not None
        }
        if all_award_uuids
        else {}
    )
    cal_by_prog: dict[UUID, list[OutcomeCalibrationRecord]] = {}
    cal_by_prog_country: dict[str, list[OutcomeCalibrationRecord]] = {}
    if all_prog_uuids:
        for cal_row in OutcomeCalibrationRecord.objects.filter(
            program_id__in=all_prog_uuids
        ):
            if cal_row.program_id is not None:
                cal_by_prog.setdefault(cal_row.program_id, []).append(cal_row)
        cand_countries = {
            programs[pid].country_code
            for pid in prog_facts_by_id
            if pid in programs and programs[pid].country_code
        }
        if cand_countries:
            for cal_row in OutcomeCalibrationRecord.objects.filter(
                program_id__isnull=False,
                country_code__in=cand_countries,
            )[:500]:
                if cal_row.country_code:
                    cal_by_prog_country.setdefault(cal_row.country_code, []).append(cal_row)

    cal_by_opp: dict[UUID, list[OutcomeCalibrationRecord]] = {}
    cal_by_award_family: dict[str, list[OutcomeCalibrationRecord]] = {}
    if all_award_uuids:
        for cal_row in OutcomeCalibrationRecord.objects.filter(
            opportunity_id__in=all_award_uuids
        ):
            if cal_row.opportunity_id is not None:
                cal_by_opp.setdefault(cal_row.opportunity_id, []).append(cal_row)
        cand_families = {
            *(
                awards[aid].family
                for aid in award_facts_by_id
                if aid in awards and awards[aid].family
            ),
            *(
                att_opp.family
                for pid in prog_facts_by_id
                for att_opp, _ in attached_selective_opps_by_program.get(pid, ())
                if att_opp.family
            ),
        }
        if cand_families:
            for cal_row in OutcomeCalibrationRecord.objects.filter(
                opportunity_id__isnull=False,
                family__in=cand_families,
            )[:500]:
                if cal_row.family:
                    cal_by_award_family.setdefault(cal_row.family, []).append(cal_row)

    def _cal_rows(exact: list[Any], pool: list[Any], attr: str, item_id: Any) -> tuple[Any, ...]:
        if len(exact) >= 10:
            return tuple(exact)
        return (*exact, *[r for r in pool if getattr(r, attr) != item_id][:40])

    probabilities: dict[str, ProbabilityEstimate] = {}
    for pid, facts_obj in prog_facts_by_id.items():
        prog_obj = programs.get(pid)
        if prog_obj is None:
            continue
        probabilities[pid] = estimate_program_admission_chance(
            prog_obj,
            facts_obj,
            profile,
            statements=tuple(statements_by_program.get(prog_obj.id, ())),
            winner_cohort=winner_cohorts_by_prog.get(prog_obj.id),
            calibration_rows=_cal_rows(
                cal_by_prog.get(prog_obj.id, []),
                cal_by_prog_country.get(prog_obj.country_code, []),
                "program_id",
                prog_obj.id,
            ),
            today=today,
        )
    eligible_award_candidates: list[AwardCandidateFacts] = []
    for aw_facts_obj in award_candidates:
        aid = aw_facts_obj.award_id
        aw_obj = awards.get(aid)
        if aw_obj is None:
            continue
        aw_outcome = evaluate_award(profile, aw_facts_obj, today=today).outcome
        if aw_outcome in ("NOT_ELIGIBLE", "ELIGIBLE_BELOW_FIT_BAR"):
            continue
        eligible_award_candidates.append(aw_facts_obj)
        probabilities[aid] = estimate_scholarship_chance(
            aw_obj,
            aw_facts_obj,
            profile,
            winner_cohort=winner_cohorts_by_opp.get(aw_obj.id),
            calibration_rows=_cal_rows(
                cal_by_opp.get(aw_obj.id, []),
                cal_by_award_family.get(aw_obj.family, []),
                "opportunity_id",
                aw_obj.id,
            ),
            today=today,
        )

    funded_probabilities: dict[str, int | None] = {}
    for pid, prog_facts in prog_facts_by_id.items():
        admit_est = probabilities.get(pid)
        if admit_est is None:
            continue
        selective_award_pcts: list[int] = []
        full_cover_award_pcts: list[int] = []
        seen_award_ids: set[str] = set()
        prog_full_schemes = set(attached_schemes.get(pid, ())) | set(
            schemes_paying_for(profile, prog_facts, award_candidates, today=today)
        )
        for aw_facts in eligible_award_candidates:
            aid = aw_facts.award_id
            aw_obj = awards.get(aid)
            aw_est = probabilities.get(aid)
            if (
                aw_est is not None
                and (aw_facts.route or "").upper() != "AUTOMATIC_ON_ADMISSION"
                and scheme_pays_for(aw_facts, prog_facts, home_country=profile.nationality)
            ):
                selective_award_pcts.append(aw_est.chance_pct)
                if (
                    (aw_obj is not None and aw_obj.tuition == "FULL" and aw_obj.living == "FULL")
                    or aw_facts.name in prog_full_schemes
                ):
                    full_cover_award_pcts.append(aw_est.chance_pct)
                seen_award_ids.add(aid)
        for att_opp, att_fact in attached_selective_opps_by_program.get(pid, ()):
            if att_fact.award_id in seen_award_ids:
                continue
            att_est = estimate_scholarship_chance(
                att_opp,
                att_fact,
                profile,
                winner_cohort=winner_cohorts_by_opp.get(att_opp.id),
                calibration_rows=_cal_rows(
                    cal_by_opp.get(att_opp.id, []),
                    cal_by_award_family.get(att_opp.family, []),
                    "opportunity_id",
                    att_opp.id,
                ),
                today=today,
            )
            selective_award_pcts.append(att_est.chance_pct)
            if (
                (att_opp.tuition == "FULL" and att_opp.living == "FULL")
                or att_opp.name in prog_full_schemes
            ):
                full_cover_award_pcts.append(att_est.chance_pct)
            seen_award_ids.add(att_fact.award_id)
        effective_prog_facts = _strip_undecidable_secondary_routes(
            profile,
            prog_facts,
            rates,
            schemes=tuple(prog_full_schemes),
            today=today,
        )
        all_awards_by_name = {
            aw.name: aw
            for aw in (
                *award_candidates,
                *(att_fact for _, att_fact in attached_selective_opps_by_program.get(pid, ())),
            )
        }
        has_post_admit_gov = any(
            (
                is_post_admission_gov_scholarship(
                    aw.name,
                    country_code=aw.country_code,
                    home_country=profile.nationality,
                    applicant_conditions=aw.applicant_conditions,
                )
                if (aw := all_awards_by_name.get(name)) is not None
                else is_post_admission_gov_scholarship(name, home_country=profile.nationality)
            )
            for name in prog_full_schemes
        )
        if has_post_admit_gov:
            gov_cond_pct = post_admission_gov_conditional_pct(
                admit_chance_pct=admit_est.chance_pct, candidate=prog_facts
            )
            if gov_cond_pct not in full_cover_award_pcts:
                full_cover_award_pcts.append(gov_cond_pct)
            if gov_cond_pct not in selective_award_pcts:
                selective_award_pcts.append(gov_cond_pct)
        needs_sel = needs_selective_funding(profile, effective_prog_facts, today=today)
        effective_award_pcts = (
            full_cover_award_pcts
            if (needs_sel and full_cover_award_pcts)
            else selective_award_pcts
        )
        if not effective_award_pcts and needs_sel:
            effective_award_pcts.append(25)
        funded_probabilities[pid] = joint_admission_and_funding_chance_pct(
            admit_est.chance_pct,
            effective_award_pcts,
            correlation=POST_ADMISSION_GOV_CORRELATION if has_post_admit_gov else 0.0,
        )
    return probabilities, funded_probabilities


def build_student_pack(
    profile: StudentProfileSnapshot | None,
    *,
    rates: RateTable | None,
    today: date,
    excluded_program_ids: Collection[UUID] = (),
    excluded_opportunity_ids: Collection[UUID] = (),
    submitted_external_opportunity_ids: Collection[UUID] = (),
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

    try:
        convert(
            profile.application_budget.amount, profile.application_budget.currency,
            rates.base, rates,
        )
    except UnconvertibleCurrency:
        logger.warning(
            "no %s rate for budget currency %s; publishing an empty pack",
            rates.source, profile.application_budget.currency,
        )
        return _empty(
            "Your budget's currency has no exchange rate yet, so application fees "
            "cannot be compared against it. Your pack will be built as soon as one is."
        )

    pool = candidate_pool(profile, limit=POOL_LIMIT)
    if excluded_program_ids or excluded_opportunity_ids:
        pool = replace(
            pool,
            programs=tuple(p for p in pool.programs if p.id not in excluded_program_ids),
            awards=tuple(a for a in pool.awards if a.id not in excluded_opportunity_ids),
        )
    if not pool.programs and not pool.awards:
        empty = _empty(pool.empty_reason)
        empty.pending_bodies = pool.pending_bodies
        return empty

    origins = _origins(pool.programs, pool.awards)

    program_ids = [program.id for program in pool.programs]
    costs_by_program: dict[object, list[CostComponent]] = {}
    for cost in CostComponent.objects.filter(program_id__in=program_ids):
        costs_by_program.setdefault(cost.program_id, []).append(cost)
    statements_by_program: dict[object, list[ProgramStatement]] = {}
    for stmt in ProgramStatement.objects.filter(
        program_id__in=program_ids,
        requirement=ProgramStatement.Requirement.REQUIRED,
        kind__in=(
            ProgramStatement.Kind.COMPETENCY,
            ProgramStatement.Kind.LANGUAGE,
            ProgramStatement.Kind.OTHER,
        ),
    ):
        statements_by_program.setdefault(stmt.program_id, []).append(stmt)

    deadlines_by_program = _program_deadline_candidates(pool.programs, profile.nationality)
    attached = _collect_attached_opportunities(pool.programs)
    attached_by_program = attached.by_program
    suspended_opps_by_program = attached.suspended_by_program
    routes = attached.routes
    durations = attached.durations
    tuition_levels = attached.tuition_levels
    attached_opps_by_id = attached.by_id

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

    verifications_by_opportunity = {
        row.opportunity_id: row
        for row in FundingCycleVerification.objects.filter(
            opportunity_id__in=[*award_ids, *routes],
            intake_start_year=profile.intended_intake.year,
        )
    }
    student_deadline_profile = deadline_student(
        profile.nationality, profile.country_of_residence
    )

    def _cycle_evidence_for(opp: FundingOpportunity) -> Evidence | None:
        verification = verifications_by_opportunity.get(opp.id)
        if verification is None or not (
            verification.evidence
            or verification.page_removed
            or verification.projection_lapsed
        ):
            return None
        raw_evidence = to_evidence(
            verification.evidence,
            target_year=profile.intended_intake.year,
            cadence=cadence_of(opp),
            page_removed=verification.page_removed,
            lapsed=verification.projection_lapsed,
        )
        selected_deadline = select_deadline(raw_evidence, student_deadline_profile)
        if selected_deadline is not None:
            raw_evidence = replace(raw_evidence, deadline=selected_deadline.date)
        if opp.suspension_quote and raw_evidence.offered == "YES":
            raw_evidence = replace(
                raw_evidence,
                offered="NO",
                applies_to=opp.suspended_for or "UNSTATED",
                contrary_intake=opp.suspended_for,
            )
        return raw_evidence

    target_intake_str = str(profile.intended_intake.year)

    def _is_program_scholarship_shut_for_intake(
        program_id: object, money_form: str
    ) -> bool:
        for stmt in statements_by_program.get(program_id, ()):
            if is_program_scholarship_suspended_for_intake(
                stmt.text, target_intake_str, money_form=money_form
            ):
                return True
        for susp_opp in suspended_opps_by_program.get(program_id, ()):
            parsed = parse_scholarship_status_statement(susp_opp.suspension_quote)
            if parsed is not None:
                _status_kind, parsed_applies_to = parsed
                if is_program_scholarship_suspended_for_intake(
                    susp_opp.suspension_quote,
                    target_intake_str,
                    money_form=money_form,
                ):
                    if (
                        parsed_applies_to == "UNSTATED"
                        and susp_opp.suspended_for
                        and not intake_matches_target(
                            susp_opp.suspended_for, target_intake_str
                        )
                    ):
                        continue
                    return True
                continue
            if susp_opp.suspended_for:
                if not intake_matches_target(
                    susp_opp.suspended_for, target_intake_str
                ):
                    continue
            else:
                quote_years = intake_start_years(susp_opp.suspension_quote)
                if quote_years and not intake_matches_target(
                    susp_opp.suspension_quote, target_intake_str
                ):
                    continue
            if (
                money_form == "FEE_WAIVER"
                and susp_opp.money_form == "GRANT"
                and "waiver" not in susp_opp.suspension_quote.lower()
            ):
                continue
            return True
        return False

    def _is_cycle_shut(opp: FundingOpportunity, *, country_code: str = "") -> bool:
        verification = verifications_by_opportunity.get(opp.id)
        if verification is not None and verification.state in ("SUSPENDED", "ENDED"):
            return True
        evidence = _cycle_evidence_for(opp)
        if evidence is None:
            return False
        intake_start = (
            profile.intended_intake
            if profile.intended_intake.month <= 6
            else default_intake_start_for_country(
                country_code or opp.country_code or "",
                profile.intended_intake.year,
                today=today,
            )
        )
        validity = cycle_validity(
            evidence,
            student=student_deadline_profile,
            target_intake=target_intake_str,
            today=today,
            intake_starts_on=intake_start,
        )
        if validity in ("SUSPENDED", "ENDED"):
            return True
        deadline = select_deadline(evidence, student_deadline_profile)
        return bool(
            deadline is not None and deadline.date is not None and deadline.date < today
        )

    programs: dict[str, Program] = {}
    program_ids_by_str: dict[str, object] = {
        str(program.id): program.id for program in pool.programs
    }
    program_candidates: list[CandidateFacts] = []
    attached_schemes: dict[str, tuple[str, ...]] = {}
    attached_selective_names: dict[str, tuple[str, ...]] = {}
    attached_selective_opps_by_program: dict[
        str, list[tuple[FundingOpportunity, AwardCandidateFacts]]
    ] = {}
    attached_review_by_program: dict[str, list[str]] = {}
    coursework_warnings: dict[str, tuple[str, ...]] = {}
    program_deadlines: dict[str, str] = {}
    degraded: list[str] = []
    for program in pool.programs:
        active_opp_ids = tuple(
            opp_id
            for opp_id in attached_by_program.get(program.id, ())
            if opp_id not in excluded_opportunity_ids
            and (opp_obj := attached_opps_by_id.get(opp_id)) is not None
            and not (
                opp_obj.route != "AUTOMATIC_ON_ADMISSION"
                and opp_obj.agreement in ("UNAGREED", "ABSTAINED", "WITHDRAWN")
            )
            and not _is_cycle_shut(opp_obj, country_code=program.country_code)
            and not (
                opp_obj.internationals_included == "NO"
                and profile.nationality != program.country_code
            )
            and not (
                opp_obj.scope_type == "PROGRAM"
                and _is_program_scholarship_shut_for_intake(
                    program.id, opp_obj.money_form
                )
            )
        )
        benefits = tuple(
            benefit
            for opportunity_id in active_opp_ids
            for benefit in benefits_by_opportunity.get(opportunity_id, ())
        )
        prog_deadline_candidates = deadlines_by_program.get(program.id, [])
        app_deadline: date | None = None
        if prog_deadline_candidates:
            best_prio = min(p for p, _ in prog_deadline_candidates)
            if best_prio <= 1:
                same_prio = [
                    d for p, d in prog_deadline_candidates if p == best_prio
                ]
                upcoming = [d for d in same_prio if d >= today]
                app_deadline = min(upcoming) if upcoming else max(same_prio)
        if app_deadline is not None:
            program_deadlines[str(program.id)] = app_deadline.isoformat()
        prog_stmts = tuple(statements_by_program.get(program.id, ()))
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
                tuition_levels=tuition_levels,
                profile=profile,
                statements=prog_stmts,
                today=today,
                application_deadline=app_deadline,
                scholarship_decision_deadline=None,
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
        if prog_warnings := _program_coursework_warnings(
            program, prog_stmts, profile, today=today
        ):
            coursework_warnings[facts.program_id] = prog_warnings

        full_scheme_names: list[str] = []
        selective_opp_names: list[str] = []
        eligible_schol_deadlines: list[date] = []
        ineligible_selective_benefit_ids: set[str] = set()
        for opp_id in active_opp_ids:
            attached_opp = attached_opps_by_id.get(opp_id)
            if attached_opp is None:
                continue
            opp_ev = _cycle_evidence_for(attached_opp)
            opp_benefits = tuple(benefits_by_opportunity.get(attached_opp.id, ()))
            if attached_opp.route == "AUTOMATIC_ON_ADMISSION" or not attached_opp.name:
                if opp_ev is not None and opp_ev.deadline is not None:
                    eligible_schol_deadlines.append(opp_ev.deadline)
                continue
            if (
                attached_opp.internationals_included == "NO"
                and profile.nationality != program.country_code
            ):
                ineligible_selective_benefit_ids.update(str(b.id) for b in opp_benefits)
                continue
            opp_rules = tuple(
                rule for b in opp_benefits for rule in rules_by_benefit.get(b.id, ())
            )
            try:
                opp_fact = award_facts(
                    attached_opp,
                    benefits=opp_benefits,
                    rules=opp_rules,
                    pays_for_program_ids=frozenset({facts.program_id}),
                    country_code=program.country_code,
                    evidence=opp_ev,
                )
            except Exception as error:  # noqa: BLE001 - one bad row never fails a pack
                logger.warning(
                    "attached opportunity %s could not be translated: %s",
                    attached_opp.id,
                    error,
                )
                degraded.append(f"{attached_opp.name}: {error}")
                ineligible_selective_benefit_ids.update(str(b.id) for b in opp_benefits)
                continue
            opp_outcome = evaluate_award(profile, opp_fact, today=today).outcome
            if opp_outcome not in ("ELIGIBLE", "POSSIBLY_ELIGIBLE_REVIEW"):
                ineligible_selective_benefit_ids.update(str(b.id) for b in opp_benefits)
                continue
            if opp_ev is not None and opp_ev.deadline is not None:
                eligible_schol_deadlines.append(opp_ev.deadline)
            if opp_outcome == "POSSIBLY_ELIGIBLE_REVIEW":
                attached_review_by_program.setdefault(facts.program_id, []).append(
                    str(attached_opp.id)
                )
            if (
                attached_opp.tuition == "FULL"
                and attached_opp.living == "FULL"
                and attached_opp.name not in full_scheme_names
            ):
                full_scheme_names.append(attached_opp.name)
            if opp_benefits and attached_opp.name not in selective_opp_names:
                selective_opp_names.append(attached_opp.name)
                attached_selective_opps_by_program.setdefault(facts.program_id, []).append(
                    (attached_opp, opp_fact)
                )
        fact_updates: dict[str, object] = {}
        if eligible_schol_deadlines:
            fact_updates["scholarship_decision_deadline"] = min(eligible_schol_deadlines)
        if ineligible_selective_benefit_ids:
            fact_updates["benefits"] = tuple(
                b for b in facts.benefits if b.id not in ineligible_selective_benefit_ids
            )
            fact_updates["applicant_conditions"] = tuple(
                c
                for c in facts.applicant_conditions
                if c.benefit_id not in ineligible_selective_benefit_ids
            )
        if fact_updates:
            facts = facts.model_copy(update=fact_updates)
        program_candidates.append(facts)
        if full_scheme_names:
            attached_schemes[facts.program_id] = tuple(full_scheme_names)
        if selective_opp_names:
            attached_selective_names[facts.program_id] = tuple(selective_opp_names)

    # What each award can pay for, as the page groups it (grouping.funds): its
    # own programme list and its country -- the holder's for a HOLDER award.
    # Read here so award_facts stays pure; gate 10 reads them (owner, 2026-10-24).
    pays_for: dict[object, set[str]] = {}
    for opportunity_id, program_id in FundingOpportunityProgram.objects.filter(
        opportunity_id__in=award_ids
    ).values_list("opportunity_id", "program_id"):
        pays_for.setdefault(opportunity_id, set()).add(str(program_id))
    organisations_by_id = {
        org.id: org
        for org in Organisation.objects.filter(
            id__in=[award.organisation_id for award in pool.awards if award.organisation_id]
        )
    }
    holder_country = {org_id: org.country_code for org_id, org in organisations_by_id.items()}

    awards: dict[str, FundingOpportunity] = {}
    award_candidates: list[AwardCandidateFacts] = []
    submitted_award_deadlines: dict[str, date] = {}
    for award in pool.awards:
        if award.organisation_id is not None and award.organisation_id in organisations_by_id:
            award.organisation = organisations_by_id[award.organisation_id]
        benefits = tuple(benefits_by_opportunity.get(award.id, ()))
        rules = tuple(
            rule for benefit in benefits for rule in rules_by_benefit.get(benefit.id, ())
        )
        linked = pays_for.get(award.id, set())
        if award.program_id is not None:
            linked.add(str(award.program_id))
        country = award.country_code or (
            holder_country.get(award.organisation_id, "")
            if award.scope_type == "HOLDER" and award.organisation_id is not None
            else ""
        )
        cycle_evidence = _cycle_evidence_for(award)
        if award.id in submitted_external_opportunity_ids and cycle_evidence is not None:
            sel_dl = select_deadline(cycle_evidence, student_deadline_profile)
            orig_dl = (
                sel_dl.date
                if sel_dl is not None and sel_dl.date is not None
                else cycle_evidence.deadline
            )
            if orig_dl is not None and orig_dl < today:
                submitted_award_deadlines[str(award.id)] = orig_dl
                cycle_evidence = replace(cycle_evidence, deadline=None, deadlines=())
        if linked and all(
            (prog_uuid := program_ids_by_str.get(prog_id_str)) is not None
            and _is_program_scholarship_shut_for_intake(prog_uuid, award.money_form)
            for prog_id_str in linked
        ):
            if cycle_evidence is None:
                cycle_evidence = Evidence(
                    offered="NO",
                    applies_to=target_intake_str,
                    contrary_intake=target_intake_str,
                )
            elif cycle_evidence.offered == "YES":
                cycle_evidence = replace(
                    cycle_evidence,
                    offered="NO",
                    applies_to=target_intake_str,
                    contrary_intake=target_intake_str,
                )
        try:
            award_fact = award_facts(
                award,
                benefits=benefits,
                rules=rules,
                pays_for_program_ids=frozenset(linked),
                country_code=country or "",
                evidence=cycle_evidence,
            )
        except Exception as error:  # noqa: BLE001 - same rule as above
            logger.warning("award %s could not be translated: %s", award.id, error)
            degraded.append(f"{award.name}: {error}")
            continue
        awards[award_fact.award_id] = award
        award_candidates.append(award_fact)

    prog_facts_by_id = {cf.program_id: cf for cf in program_candidates}
    award_facts_by_id = {af.award_id: af for af in award_candidates}
    probabilities, funded_probabilities = _estimate_pack_probabilities(
        profile,
        rates=rates,
        today=today,
        programs=programs,
        awards=awards,
        prog_facts_by_id=prog_facts_by_id,
        award_facts_by_id=award_facts_by_id,
        award_candidates=award_candidates,
        statements_by_program=statements_by_program,
        attached_schemes=attached_schemes,
        attached_selective_opps_by_program=attached_selective_opps_by_program,
    )

    pack = build_pack(
        profile,
        program_candidates,
        rates,
        awards=award_candidates,
        attached_schemes=attached_schemes,
        attached_selective_names=attached_selective_names,
        probabilities={
            pid: probabilities[pid].chance_pct
            for pid in prog_facts_by_id
            if pid in probabilities
        },
        funded_probabilities=funded_probabilities,
        coursework_warnings=coursework_warnings,
        award_probabilities={
            aid: probabilities[aid].chance_pct
            for aid in award_facts_by_id
            if aid in probabilities
        },
        today=today,
    )

    # Counted and named, never silent: a programme the rate table cannot price
    # is left out of this pack, and a person sees which one and why.
    degraded += [
        f"{programs[item.program_id].name}: no exchange rate ({item.reasons[0]})"
        for item in pack.excluded
        if item.reason_code == "NO_EXCHANGE_RATE"
    ]

    # A POSSIBLY_ELIGIBLE_REVIEW outcome is work for a human, NOT a hold on the
    # student's pack: publication stays un-gated by counsellor review (phased
    # requirements section 38).
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
    packed_prog_ids = {
        app.program_id
        for app in (*pack.fee_free, *pack.paid, *pack.fee_not_known, *pack.over_budget)
    }
    for packed_prog_id in packed_prog_ids:
        for rev_opp_id in attached_review_by_program.get(packed_prog_id, ()):
            if rev_opp_id not in review:
                review.append(rev_opp_id)
        raw_facts = prog_facts_by_id.get(packed_prog_id)
        if (
            raw_facts is not None
            and packed_prog_id not in review
            and not attached_review_by_program.get(packed_prog_id)
            and unevaluable_condition_reasons(profile, raw_facts, today=today)
        ):
            review.append(packed_prog_id)

    if submitted_award_deadlines:
        pack = replace(
            pack,
            awards=tuple(
                replace(
                    aw,
                    deadline=submitted_award_deadlines.get(aw.award_id, aw.deadline),
                )
                for aw in pack.awards
            ),
        )

    return SpineResult(
        pack=pack,
        programs=programs,
        awards=awards,
        origins=origins,
        degraded=tuple(degraded),
        review=tuple(review),
        pending_bodies=pool.pending_bodies,
        probabilities=probabilities,
        program_deadlines=program_deadlines,
        program_facts={facts.program_id: facts for facts in program_candidates},
        award_facts={facts.award_id: facts for facts in award_candidates},
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
