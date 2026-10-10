from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.conditions import benefit_applies
from apps.funding.evaluation import BenefitFact, CandidateFacts
from apps.funding.fx import RateTable, convert, round_money


def _normalize_to_program_total(amount: Decimal, period: str, duration_months: int) -> Decimal:
    if period == "MONTHLY":
        return amount * Decimal(duration_months)
    if period == "ANNUAL":
        return round_money(amount * Decimal(duration_months) / Decimal(12))
    return amount  # ONE_OFF and FULL_PROGRAM already describe a single program-total charge


@dataclass(frozen=True)
class CostItem:
    kind: str
    program_total: Decimal


@dataclass(frozen=True)
class BenefitItem:
    id: str
    kind: str
    program_total: Decimal
    bucket: str


@dataclass(frozen=True)
class AffordabilityResult:
    currency: str
    baseline_cost: Decimal
    covered: Decimal
    gap: Decimal
    conditional_savings: Decimal
    application_fee: Decimal
    #: The fee is an obligation payable in the destination's own currency, so unlike
    #: every other figure here it is NOT expressed in ``currency``. Converting it and
    #: presenting the result as the amount due is how a student underfunds a visa
    #: financial requirement. Falls back to ``currency`` when there is no fee at all.
    application_fee_currency: str
    cost_items: tuple[CostItem, ...]
    benefit_items: tuple[BenefitItem, ...]
    #: Provenance of every conversion above, so a figure is never shown without the rate
    #: table that produced it.
    rates_source: str
    rates_retrieved_on: date


def _bucket_for(
    benefit: BenefitFact, candidate: CandidateFacts, profile: StudentProfileSnapshot
) -> str:
    if not benefit.is_current or not benefit_applies(benefit, candidate, profile):
        return "EXCLUDED"
    if benefit.accessibility == "EMERGENCY":
        return "EXCLUDED"
    if benefit.eligibility_confidence not in {"VERIFIED", "LIKELY"}:
        return "EXCLUDED"
    if benefit.accessibility == "CAPACITY_LIMITED":
        return "CONDITIONAL"
    return "BASELINE"


def calculate_affordability(
    profile: StudentProfileSnapshot, candidate: CandidateFacts, rates: RateTable
) -> AffordabilityResult:
    application_fee = Decimal("0.00")
    application_fee_currency: str | None = None
    cost_items: list[CostItem] = []
    for component in candidate.cost_components:
        total = _normalize_to_program_total(
            component.amount, component.period, candidate.duration_months
        )
        cost_items.append(
            CostItem(
                kind=component.kind,
                program_total=convert(total, component.currency, rates.base, rates),
            )
        )
        if component.kind == "APPLICATION_FEE":
            if application_fee_currency is None:
                application_fee_currency = component.currency
            # One program has one application fee, so this conversion is the identity in
            # practice; it only keeps the accumulator coherent if a candidate ever carries
            # several fee components quoted in different currencies.
            application_fee += convert(total, component.currency, application_fee_currency, rates)

    baseline_cost = sum(
        (item.program_total for item in cost_items if item.kind != "APPLICATION_FEE"),
        Decimal("0.00"),
    )

    covered = Decimal("0.00")
    conditional_savings = Decimal("0.00")
    benefit_items: list[BenefitItem] = []
    for benefit in candidate.benefits:
        bucket = _bucket_for(benefit, candidate, profile)
        if benefit.amount is None or benefit.currency is None:
            total = Decimal("0.00")
        else:
            total = _normalize_to_program_total(
                benefit.amount, benefit.period, candidate.duration_months
            )
            total = convert(total, benefit.currency, rates.base, rates)
        benefit_items.append(
            BenefitItem(id=benefit.id, kind=benefit.kind, program_total=total, bucket=bucket)
        )
        # A repayable award is not coverage (design §2). The item keeps the gross figure
        # -- that is what the funder awards, and a student comparing offers needs it --
        # while only the unrepayable part reduces the gap.
        countable = round_money(total * (Decimal("1") - benefit.repayable_share))
        if bucket == "BASELINE":
            covered += countable
        elif bucket == "CONDITIONAL":
            conditional_savings += countable

    gap = max(baseline_cost - covered, Decimal("0.00"))

    return AffordabilityResult(
        currency=rates.base,
        baseline_cost=baseline_cost,
        covered=covered,
        gap=gap,
        conditional_savings=conditional_savings,
        application_fee=application_fee,
        application_fee_currency=application_fee_currency or rates.base,
        cost_items=tuple(cost_items),
        benefit_items=tuple(benefit_items),
        rates_source=rates.source,
        rates_retrieved_on=rates.retrieved_on,
    )
