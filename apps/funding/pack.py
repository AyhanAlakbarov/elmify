from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.affordability import AffordabilityResult, calculate_affordability
from apps.funding.conditions import (
    closed_route_reasons,
    return_service_disclosures,
)
from apps.funding.evaluation import (
    AwardCandidateFacts,
    CandidateFacts,
    EvaluationScores,
    evaluate,
    evaluate_award,
)
from apps.funding.fx import RateTable, convert

if TYPE_CHECKING:
    from apps.funding.card import AwardCard

PackOrdering = Literal["SCHOLARSHIP_FIRST", "PARALLEL_OR_UNIVERSITY_FIRST"]


@dataclass(frozen=True)
class RankedCandidate:
    program_id: str
    scores: EvaluationScores | None
    affordability: AffordabilityResult
    tradeoffs: tuple[str, ...]


@dataclass(frozen=True)
class PackedApplication:
    program_id: str
    #: Payable as-is, in ``application_fee_currency`` — not the comparison currency.
    application_fee: Decimal
    application_fee_currency: str
    #: What this programme still costs the student after every funding route
    #: they can actually use, in `gap_currency`. Carried here because the
    #: evaluator has already computed it -- reading it back meant ranking twice.
    gap: Decimal
    gap_currency: str
    ordering: PackOrdering
    ordering_reason: str


@dataclass(frozen=True)
class ExcludedCandidate:
    program_id: str
    reason_code: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PackedAward:
    """A scholarship the student applies for, as its own application.

    **An award is an application, not a discount** (owner decision 2026-09-19).
    Its money is deliberately NOT subtracted from any programme's cost: counting
    money not yet won understates the gap by exactly the amount at risk, which
    is the amount that decides whether the student can go at all.
    """

    award_id: str
    name: str
    holder_name: str
    deadline: date | None
    ordering: PackOrdering
    ordering_reason: str
    #: Details the readings split on, shown beside the award (spec 8.6). Never
    #: filtered on, and never silently dropped: a served award whose caveat was
    #: lost presents a model's coin-flip as a fact.
    unconfirmed: tuple[str, ...]
    card: AwardCard | None = None


@dataclass(frozen=True)
class Pack:
    fee_free: tuple[PackedApplication, ...]
    paid: tuple[PackedApplication, ...]
    #: Award applications. A second list rather than more entries in the first
    #: two, because those are partitioned by an application FEE and an award
    #: does not charge one -- folding awards in would make "fee_free" mean two
    #: different things.
    awards: tuple[PackedAward, ...]
    excluded: tuple[ExcludedCandidate, ...]
    #: Why the pool was empty, when it was. P1-7: a short pack always says so.
    #: Set by the spine's own empty-pack path -- `build_pack` never runs on an
    #: empty pool, so it has nothing to say here.
    empty_reason: str = ""


def rank_candidates(
    profile: StudentProfileSnapshot, candidates: Sequence[CandidateFacts], rates: RateTable
) -> tuple[RankedCandidate, ...]:
    evaluated: list[tuple[CandidateFacts, EvaluationScores, AffordabilityResult]] = []
    for candidate in candidates:
        outcome = evaluate(profile, candidate, rates)
        if outcome.outcome != "ELIGIBLE":
            continue
        assert outcome.scores is not None
        evaluated.append(
            (candidate, outcome.scores, calculate_affordability(profile, candidate, rates))
        )

    if not evaluated:
        return ()

    # "weaker fit" disclosure compares soft-fit only, excluding AFFORDABILITY: a
    # funding-first pick can legitimately have the higher blended overall score
    # purely because it is more affordable, which is the tradeoff being disclosed,
    # not evidence that its underlying program fit is actually stronger.
    def soft_fit(scores: EvaluationScores) -> Decimal:
        fit_scores = [d.score for d in scores.dimensions if d.dimension != "AFFORDABILITY"]
        if not fit_scores:
            return Decimal("0")
        return sum(fit_scores, Decimal("0")) / Decimal(len(fit_scores))

    best_soft_fit = max(soft_fit(scores) for _, scores, _ in evaluated)

    if profile.strategy == "FUNDING_FIRST":
        ordered = sorted(evaluated, key=lambda item: (item[2].gap, -item[1].overall))
    else:
        ordered = sorted(evaluated, key=lambda item: -item[1].overall)

    ranked = []
    for candidate, scores, affordability in ordered:
        # "tradeoffs" is now everything the student must be told before accepting this
        # candidate, not only the fit comparison: a shut scheme and a bond both belong.
        tradeoffs = (
            *closed_route_reasons(profile, candidate),
            *return_service_disclosures(profile, candidate),
        )
        if soft_fit(scores) < best_soft_fit:
            tradeoffs = ("weaker fit than another recommended candidate", *tradeoffs)
        ranked.append(
            RankedCandidate(
                program_id=candidate.program_id,
                scores=scores,
                affordability=affordability,
                tradeoffs=tradeoffs,
            )
        )
    return tuple(ranked)


def _ordering_for(candidate: CandidateFacts) -> tuple[PackOrdering, str]:
    deadline = candidate.application_deadline
    scholarship_deadline = candidate.scholarship_decision_deadline
    if (
        scholarship_deadline is not None
        and deadline is not None
        and scholarship_deadline <= deadline
    ):
        return (
            "SCHOLARSHIP_FIRST",
            "the scholarship decision is due before the university fee deadline, so paying "
            "the fee is deferred until the scholarship decision arrives",
        )
    return (
        "PARALLEL_OR_UNIVERSITY_FIRST",
        "official timelines do not prove the scholarship decision arrives safely before the "
        "university fee deadline",
    )


def _award_ordering(
    award: AwardCandidateFacts, earliest_fee_deadline: date | None
) -> tuple[PackOrdering, str]:
    """Same question `_ordering_for` asks of a programme, from the award's side.

    `_ordering_for` is untouched: it reads a CandidateFacts and an award is not
    one. The rule is the same and so is the wording -- if the scholarship
    decides first, paying a fee can wait for it.
    """
    deadline = award.evidence.deadline
    if (
        deadline is not None
        and earliest_fee_deadline is not None
        and deadline <= earliest_fee_deadline
    ):
        return (
            "SCHOLARSHIP_FIRST",
            "the scholarship decision is due before the university fee deadline, so paying "
            "the fee is deferred until the scholarship decision arrives",
        )
    return (
        "PARALLEL_OR_UNIVERSITY_FIRST",
        "official timelines do not prove the scholarship decision arrives safely before the "
        "university fee deadline",
    )


def build_pack(
    profile: StudentProfileSnapshot,
    candidates: Sequence[CandidateFacts],
    rates: RateTable,
    *,
    awards: Sequence[AwardCandidateFacts] = (),
    today: date | None = None,
) -> Pack:
    by_id = {candidate.program_id: candidate for candidate in candidates}
    ranked = rank_candidates(profile, candidates, rates)
    ranked_ids = {item.program_id for item in ranked}

    excluded: list[ExcludedCandidate] = []
    for candidate in candidates:
        if candidate.program_id in ranked_ids:
            continue
        outcome = evaluate(profile, candidate, rates)
        excluded.append(
            ExcludedCandidate(
                program_id=candidate.program_id,
                reason_code=outcome.outcome,
                reasons=outcome.reasons,
            )
        )

    fee_free: list[PackedApplication] = []
    paid: list[PackedApplication] = []
    budget_remaining = convert(
        profile.application_budget.amount,
        profile.application_budget.currency,
        rates.base,
        rates,
    )
    for item in ranked:
        candidate = by_id[item.program_id]
        fee = item.affordability.application_fee
        currency = item.affordability.application_fee_currency
        ordering, reason = _ordering_for(candidate)
        # The fee is quoted in the destination's currency and the budget in the student's,
        # so budgeting compares them in the base currency while the packed figure stays
        # the amount actually payable.
        fee_in_base = convert(fee, currency, rates.base, rates)
        packed = PackedApplication(
            candidate.program_id,
            fee,
            currency,
            item.affordability.gap,
            item.affordability.currency,
            ordering,
            reason,
        )
        if fee == 0:
            fee_free.append(packed)
        elif fee_in_base <= budget_remaining:
            paid.append(packed)
            budget_remaining -= fee_in_base
        else:
            excluded.append(
                ExcludedCandidate(
                    program_id=candidate.program_id,
                    reason_code="APPLICATION_BUDGET_EXCEEDED",
                    reasons=("the application fee would exceed the remaining application budget",),
                )
            )

    # Awards are evaluated and packed AFTER the programme budget arithmetic
    # above, and touch none of it: `budget_remaining` is an application-fee
    # budget and an award charges no fee. The programme half of this function
    # is byte-for-byte what it was.
    earliest_fee_deadline = min(
        (
            candidate.application_deadline
            for candidate in candidates
            if candidate.application_deadline is not None
        ),
        default=None,
    )
    packed_awards: list[PackedAward] = []
    for award in awards:
        outcome = evaluate_award(profile, award, today=today or date.today())
        if outcome.outcome in ("NOT_ELIGIBLE", "ELIGIBLE_BELOW_FIT_BAR"):
            # P1-7: visible with the reason, never a silently short pack.
            excluded.append(
                ExcludedCandidate(
                    program_id=award.award_id,
                    reason_code=outcome.outcome,
                    reasons=outcome.reasons,
                )
            )
            continue
        ordering, reason = _award_ordering(award, earliest_fee_deadline)
        packed_awards.append(
            PackedAward(
                award_id=award.award_id,
                name=award.name,
                holder_name=award.holder_name,
                deadline=award.evidence.deadline,
                ordering=ordering,
                ordering_reason=reason,
                unconfirmed=award.unconfirmed,
                card=award.card,
            )
        )

    return Pack(
        fee_free=tuple(fee_free),
        paid=tuple(paid),
        awards=tuple(packed_awards),
        excluded=tuple(excluded),
    )
