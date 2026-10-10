"""Catalog rows -> facts the evaluator can reason about.

Two translators, one rule between them: **what the catalogue does not say, this
module does not say either.** A missing country list becomes an undecidable
condition carrying the award's own sentence, not an empty list that matches
nobody; a missing benefit becomes no coverage, not a zero; a missing deadline
stays None, not today's date. Every one of those substitutions would put a
number or a bar in front of a student that no page ever printed, and would do
it silently -- the student never sees the value that was guessed, only the
candidate that disappeared.

**Both functions are pure: no I/O.** Rows are fetched by the caller and passed
in. That is not style -- `read_and_derive` holds one transaction open across a
fetch and two model calls, and the standing lesson from it is that I/O hidden
inside something that reads like a transformation is invisible until it is
expensive. A test asserts zero queries.

Spec section 10.2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from apps.funding.card import award_card
from apps.funding.evaluation import (
    _UPSTREAM_DIMENSIONS,
    ApplicantConditionFact,
    AwardCandidateFacts,
    BenefitFact,
    CandidateFacts,
    CostLineItem,
    ReturnServiceFact,
)
from apps.funding.fx import round_money
from apps.funding.models import (
    BenefitRule,
    CostComponent,
    FundingBenefit,
    FundingOpportunity,
    Program,
)
from apps.funding.validity import Evidence

#: Nothing in the catalogue scores qualitative fit yet, so every programme
#: enters on the same neutral figure and the ranking is decided by
#: affordability and the gates. A real score is the evidence pipeline's to
#: supply; inventing a spread here would manufacture a ranking out of nothing.
#: The dimension LIST is imported rather than restated -- CandidateFacts
#: validates that the set matches exactly, so a local copy would be a second
#: source of truth that fails at construction the day one is added.
#:
#: **Consequence, measured and deliberately left standing: a BALANCED student
#: gets no programme recommendations at all.** That strategy needs 80 overall
#: and 60 per dimension (`evaluation._BALANCED_OVERALL_BAR` /
#: `_BALANCED_DIMENSION_BAR`), and 50 across the board reaches 64. Every
#: programme comes back ELIGIBLE_BELOW_FIT_BAR with the shortfall named, so it
#: is visible rather than silent -- but the number it is measured against is a
#: placeholder, which makes the REASON honest about the score and misleading
#: about the programme. Raising the constant to clear the bar would be
#: manufacturing a pass, so the fix is upstream fit scoring, not a bigger
#: number here. FUNDING_FIRST is unaffected: it has no fit bar.
#: `tests/funding/test_spine.py` pins both halves.
_NEUTRAL = Decimal("50")


#: The one published route that pays every admitted student. Everything else --
#: selection, a nomination, a separate application, or a page that never said --
#: is money the applicant may not get, so it reaches the pack as a CONDITIONAL
#: saving and never as coverage (`affordability._bucket_for`). Treating it as
#: coverage would show every applicant the gap only the winners will have, which
#: is the same mistake as counting a HOLDER award as a discount, one scope down.
GUARANTEED_ROUTE = "AUTOMATIC_ON_ADMISSION"


def _counted(
    benefit: FundingBenefit, *, award_months: int | None, programme_months: int | None
) -> tuple[Decimal | None, str | None, str]:
    """(amount, currency, period) as the arithmetic may use them.

    A row no reader wrote (`amount_text` blank) passes through unchanged. A
    read figure counts only when the page stated it as the amount -- EXACT,
    never "up to" -- and a monthly or annual one only over a duration the
    page stated: it becomes a programme total over min(award, programme)
    months. `affordability` would otherwise multiply it by the PROGRAMME's
    length, and a one-year stipend on a two-year degree would count twice.
    """
    if not benefit.amount_text or benefit.amount is None:
        return benefit.amount, benefit.currency or None, benefit.period
    if benefit.amount_bound != "EXACT":
        return None, None, benefit.period
    if benefit.period not in ("MONTHLY", "ANNUAL"):
        return benefit.amount, benefit.currency, benefit.period
    if award_months is None or programme_months is None:
        return None, None, benefit.period
    per_month = benefit.amount if benefit.period == "MONTHLY" else benefit.amount / Decimal(12)
    total = round_money(per_month * Decimal(min(award_months, programme_months)))
    return total, benefit.currency, "FULL_PROGRAM"


def _benefit_facts(
    benefits: Sequence[FundingBenefit],
    routes: Mapping[object, str] | None = None,
    *,
    durations: Mapping[object, int | None] | None = None,
    programme_months: int | None = None,
) -> tuple[BenefitFact, ...]:
    """`routes` is opportunity id -> published route, for the programme side;
    `durations` is opportunity id -> the months the award's page states.

    Omitted, every benefit is ORDINARY -- an award's own benefits describe the
    award the student is applying FOR, so there is no second route to qualify
    them by -- and no read periodic figure is totalled, because there is no
    programme to total it over.
    """
    facts: list[BenefitFact] = []
    for benefit in benefits:
        amount, currency, period = _counted(
            benefit,
            award_months=(durations or {}).get(benefit.opportunity_id),
            programme_months=programme_months,
        )
        facts.append(
            BenefitFact(
                id=str(benefit.id),
                kind=cast(Any, benefit.kind),
                amount=amount,
                currency=currency,
                period=cast(Any, period),
                scope_type="GLOBAL",
                accessibility=(
                    "ORDINARY"
                    if routes is None or routes.get(benefit.opportunity_id) == GUARANTEED_ROUTE
                    else "CAPACITY_LIMITED"
                ),
                repayable_share=benefit.repayable_share,
            )
        )
    return tuple(facts)


def _condition_facts(rules: Sequence[BenefitRule]) -> tuple[ApplicantConditionFact, ...]:
    return tuple(
        ApplicantConditionFact(
            benefit_id=str(rule.benefit_id),
            condition_type=cast(Any, rule.condition_type or "WORK_EXPERIENCE"),
            key=rule.key,
            operator=rule.operator,
            value=rule.value,
            comparable_value=rule.comparable_value,
            comparable_unit=cast(Any, rule.comparable_unit),
            rule_text=rule.rule_text,
        )
        for rule in rules
        if rule.kind == BenefitRule.Kind.APPLICANT_CONDITION
    )


def _return_service_facts(rules: Sequence[BenefitRule]) -> tuple[ReturnServiceFact, ...]:
    return tuple(
        ReturnServiceFact(
            benefit_id=str(rule.benefit_id),
            months=int(rule.comparable_value or 0),
            rule_text=rule.rule_text,
        )
        for rule in rules
        if rule.kind == BenefitRule.Kind.RETURN_SERVICE and rule.comparable_value
    )


def _nationality_condition(award: FundingOpportunity) -> tuple[ApplicantConditionFact, ...]:
    """A shape with no list: a condition nothing can decide, never an empty set.

    The reader records THAT a page restricts by nationality (`nationality_shape`)
    and not WHICH countries. An empty country list would read as "matches
    nobody" and quietly shut every route; a list guessed from the holder's own
    country would be worse. Undecidable is the honest answer, and it reaches a
    consultant with the award's own words.

    A shape the readings split on is blanked to UNSTATED and named in
    `unconfirmed`, so it never gets here -- turning a disagreement into an
    eligibility bar is the silent exclusion tiered agreement exists to prevent.
    """
    if award.nationality_shape in ("", "UNSTATED", "OPEN"):
        return ()
    return (
        ApplicantConditionFact(
            benefit_id=str(award.id),
            condition_type="WORK_EXPERIENCE",  # deprecated filler; `key` is the label
            key="CITIZENSHIP",
            operator="IN",
            value="",
            rule_text=(
                f"{award.holder_name or award.name} restricts this award by nationality "
                f"({award.nationality_shape.replace('_', ' ').lower()}); the page's own list "
                "was not read, so a consultant must confirm it."
            ),
        ),
    )


def award_facts(
    award: FundingOpportunity,
    *,
    benefits: Sequence[FundingBenefit],
    rules: Sequence[BenefitRule],
) -> AwardCandidateFacts:
    """One served HOLDER award, as the gates read it.

    `benefits` and `rules` are the award's own rows, fetched by the caller.
    """
    published = _condition_facts(rules)
    return AwardCandidateFacts(
        award_id=str(award.id),
        name=award.name,
        holder_name=award.holder_name,
        organisation_id=str(award.organisation_id) if award.organisation_id else "",
        money_form=award.money_form,
        route=award.route,
        unconfirmed=tuple(part for part in award.unconfirmed.split(";") if part),
        benefits=_benefit_facts(benefits),
        applicant_conditions=(*published, *_nationality_condition(award)),
        return_service=_return_service_facts(rules),
        # An UNAGREED row is not evidence a student acts on -- P1-6's gate
        # excludes LOW before a candidate ever enters a pack's pool. A row
        # agreed on existence with a detail unconfirmed is NOT low: that is
        # exactly what tiered agreement decided to keep showing.
        evidence_confidence="LOW" if award.agreement != "AGREED" else "MEDIUM",
        # Step-0 evidence only: what the reader stored. There is no call
        # history without the evidence ladder, so `past_calls` is empty and
        # most awards will come back UNVERIFIED -- see the deadline gate.
        evidence=Evidence(
            offered="NO" if award.suspension_quote else "YES",
            applies_to=award.suspended_for or "UNSTATED",
            contrary_intake=award.suspended_for,
        ),
        coverage_is_unstated=not benefits,
        card=award_card(award, benefits),
    )


def program_facts(
    program: Program,
    *,
    costs: Sequence[CostComponent],
    benefits: Sequence[FundingBenefit],
    rules: Sequence[BenefitRule],
    routes: Mapping[object, str] | None = None,
    durations: Mapping[object, int | None] | None = None,
) -> CandidateFacts:
    """One catalog programme as `CandidateFacts`, with nothing invented.

    `CandidateFacts` is unchanged by this slice, so today's HARD_GATES and their
    tests are untouched. The rejected alternative was an optional `program_id`
    on one shared fact type, which needs an `if` in every programme gate -- and
    a gate that silently skips is worse than a crash in this repo.
    """
    return CandidateFacts(
        program_id=str(program.id),
        institution_id=str(program.institution_id or ""),
        program_country_code=program.country_code,
        location_key=program.location_key,
        city=program.city,
        # The catalogue has no field-of-study column; the programme's own name
        # is the only thing it prints about its subject.
        field_of_study=program.name,
        teaching_languages=tuple(program.teaching_languages),
        duration_months=program.duration_months,
        language_evidence_required=False,
        language_evidence_deadline=None,
        # The catalogue holds NO deadline columns (CLAUDE.md), so there is
        # nothing honest to put here. An unknown deadline is not a missed one:
        # viability stays True and the intake gate decides, rather than a
        # fabricated date ruling the programme out.
        application_deadline=None,
        scholarship_decision_deadline=None,
        deadline_is_viable=True,
        # Means a human or a page said no. Nothing in the catalogue says that,
        # and asserting it would exclude a candidate on evidence that does not
        # exist.
        confirmed_eligibility_failure=False,
        evidence_confidence="MEDIUM",
        cost_components=tuple(
            CostLineItem(
                kind=cast(Any, cost.kind),
                amount=cost.amount,
                currency=cost.currency,
                period=cast(Any, cost.period)
            )
            for cost in costs
        ),
        benefits=_benefit_facts(
            benefits, routes, durations=durations, programme_months=program.duration_months
        ),
        applicant_conditions=_condition_facts(rules),
        return_service=_return_service_facts(rules),
        dimension_scores={dimension: _NEUTRAL for dimension in _UPSTREAM_DIMENSIONS},
    )
