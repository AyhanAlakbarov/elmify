"""The shared condition engine: who a published funding route is open to.

Moved out of `evaluation.py` on 2026-09-23 with **no behaviour change** -- the
41 evaluator tests passed untouched across the move, which is what makes it a
move rather than a rewrite.

It lives on its own because two different fact types now ask it the same
questions: a programme pairing (`evaluation.CandidateFacts`) and a holder award
(`evaluation.AwardCandidateFacts`). Nothing here names either of them. The
candidate parameter is structural -- anything carrying `benefits`,
`applicant_conditions`, `return_service` and the three scope keys answers -- so
the engine cannot grow a branch per fact type, which is how one rule quietly
becomes two that disagree.

The models themselves stay in `evaluation.py` and are imported here only under
TYPE_CHECKING: at runtime this module reads attributes and builds a
`ConditionTriple`, so it needs no class, and that is what keeps the two modules
from importing each other.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import ValidationError

from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.eligibility import ConditionTriple, Decision, Key, Operator, decide

if TYPE_CHECKING:
    from apps.funding.evaluation import (
        ApplicantConditionFact,
        BenefitFact,
        ReturnServiceFact,
    )


class HasFundingRoutes(Protocol):
    """What the engine needs of a candidate, and nothing else.

    Deliberately structural. A `CandidateFacts` and an `AwardCandidateFacts`
    satisfy it without either module knowing about the other, and a third fact
    type would too.
    """

    @property
    def program_id(self) -> str: ...
    @property
    def program_country_code(self) -> str: ...
    @property
    def location_key(self) -> str: ...
    @property
    def benefits(self) -> tuple[BenefitFact, ...]: ...
    @property
    def applicant_conditions(self) -> tuple[ApplicantConditionFact, ...]: ...
    @property
    def return_service(self) -> tuple[ReturnServiceFact, ...]: ...


#: The six pre-vocabulary condition types, each mapped to its vocabulary key and
#: the operator that type means. A legacy row carries no operator of its own
#: (ApplicantConditionFact.operator defaults to "") and takes it from here --
#: AGE_CAP states a maximum age, so it maps to LTE, not the GTE that would read
#: it as a floor and decide the opposite of what the row says the moment AGE
#: becomes decidable (Task 12). Do not re-flip this: it has been a bespoke branch
#: once already and the fix was to make it data, not to special-case it again.
#: Corrected 2026-09-20 (Task 6 fix round 1): a blanket GTE default had stood
#: unchecked on the other five keys -- NEED (a means test is a ceiling, per spec
#: 2.1: LTE) and AFFINITY/GUARANTOR/LANGUAGE (none states a number, so PRESENT is
#: their form, matching a legacy LANGUAGE row's "no level stated" case) were all
#: wrong. Must equal apps.funding.migrations.0042_condition_type_to_key._KEYS --
#: not imported from it (a migration must never depend on live application code
#: a later edit could change), so
#: test_the_legacy_operator_table_agrees_with_the_migrations_backfill is what
#: keeps the two from drifting apart silently again.
_LEGACY_KEYS: dict[str, tuple[str, str]] = {
    "WORK_EXPERIENCE": ("WORK_EXPERIENCE", "GTE"),
    "AGE_CAP": ("AGE", "LTE"),
    "MEANS_TEST": ("NEED", "LTE"),
    "AFFILIATION": ("AFFINITY", "PRESENT"),
    "LANGUAGE": ("LANGUAGE", "PRESENT"),
    "GUARANTOR": ("GUARANTOR", "PRESENT"),
}

#: The only legacy types whose comparable_value denominates a number at all --
#: BenefitRule.comparable_value is DB-CHECK-constrained to NULL for LANGUAGE,
#: AFFILIATION and GUARANTOR. A test or a hand-built fact is not bound by that
#: constraint, so the fallback below restricts itself here too, rather than
#: synthesising a number (e.g. "24") for a key it means nothing to -- that number
#: does not identify itself as a language, and this is Finding 1's second half.
_NUMERIC_LEGACY_TYPES = frozenset({"WORK_EXPERIENCE", "AGE_CAP", "MEANS_TEST"})


def _as_triple(condition: ApplicantConditionFact) -> ConditionTriple:
    legacy_key, legacy_operator = _LEGACY_KEYS.get(condition.condition_type, ("OTHER", "GTE"))
    key = condition.key or legacy_key
    # Explicit wins: a legacy row has no operator of its own, so the table
    # applies; an operator a row already states -- legacy condition_type or
    # not -- is a deliberate statement worth honouring, not a contradiction to
    # detect. No writer produces a legacy row with its own operator today, so
    # this is a contract for when one might, not a case being silently allowed.
    operator = condition.operator or legacy_operator
    value = condition.value
    # Only a genuinely legacy row -- no key of its own -- falls back to
    # comparable_value, and only for the three types that denominate a number.
    # condition_type is required and closed to the six legacy names, so every
    # new-vocabulary row must also carry one as meaningless filler (the shared
    # test factory picks WORK_EXPERIENCE); gating on condition_type alone would
    # synthesise a fabricated value (e.g. "24") for a GENDER/CITIZENSHIP/... row
    # that stated no value of its own -- the same defect Finding 1 closed for
    # LANGUAGE, one key over.
    if not condition.key and not value and condition.condition_type in _NUMERIC_LEGACY_TYPES:
        value = str(condition.comparable_value) if condition.comparable_value is not None else ""
    unit = condition.comparable_unit if key == "WORK_EXPERIENCE" else None
    # key/operator are plain str on ApplicantConditionFact (they may be an unvalidated
    # legacy value) but ConditionTriple's fields are closed Literals; pydantic validates
    # the actual value at construction (raising ValidationError on anything outside the
    # vocabulary) regardless of this cast, which only satisfies the static type.
    return ConditionTriple(
        key=cast(Key, key), operator=cast(Operator, operator), value=value, unit=unit,
        quote=condition.rule_text,
    )


def _decision_for(
    condition: ApplicantConditionFact, profile: StudentProfileSnapshot
) -> Decision:
    # The one seam: a malformed row (an out-of-vocabulary key/operator, a value
    # over 200 characters, an empty rule_text) makes ConditionTriple's own
    # validation raise, and this module escalates rather than guesses everywhere
    # else -- one caught exception here does that for every caller (both
    # _unmet_conditions and unevaluable_condition_reasons go through this
    # function), instead of a guard duplicated at each of them.
    try:
        triple = _as_triple(condition)
    except ValidationError:
        return Decision(
            "UNDECIDABLE",
            f"funding route {condition.benefit_id}: this condition could not be read "
            "(its key, operator or value falls outside the closed vocabulary)",
        )
    return decide(triple, profile)


def _unmet_conditions(
    benefit: BenefitFact, candidate: HasFundingRoutes, profile: StudentProfileSnapshot
) -> tuple[ApplicantConditionFact, ...]:
    """Conditions on this route the profile shows the student does not meet.

    FAILED only. UNDECIDABLE is not a soft fail -- evaluate() picks those up and
    routes the candidate to review rather than filtering it out silently.
    """
    return tuple(
        condition
        for condition in candidate.applicant_conditions
        if condition.benefit_id == benefit.id
        and _decision_for(condition, profile).outcome == "FAILED"
    )


def closed_route_reasons(
    profile: StudentProfileSnapshot, candidate: HasFundingRoutes
) -> tuple[str, ...]:
    """Every route shut by a condition the student demonstrably does not meet.

    "No viable verified funding route exists" is true but useless: it tells a student
    nothing they can act on, and hides that the bar was two years of experience rather
    than their grades. Each string names the scheme and quotes the published condition.
    """
    return tuple(
        f"funding route {condition.benefit_id} is closed by its "
        # A new-vocabulary row's key is the true label; condition_type is only
        # ever a deprecated-alias filler for such a row (it has no OTHER member
        # to fall back to), so naming it here would print the wrong bar.
        f"{condition.key or condition.condition_type} condition: {condition.rule_text}"
        for benefit in candidate.benefits
        for condition in _unmet_conditions(benefit, candidate, profile)
    )


def benefit_applies(
    benefit: BenefitFact, candidate: HasFundingRoutes, profile: StudentProfileSnapshot
) -> bool:
    # Conditions are checked before scope: a route the student cannot enter does not
    # apply to them no matter where it is published. Both the mandatory-funding hard
    # gate and affordability's buckets call this, so the guard lands once.
    if _unmet_conditions(benefit, candidate, profile):
        return False
    if benefit.scope_type == "GLOBAL":
        return True
    if benefit.scope_type == "NATIONALITY":
        return benefit.nationality_code == profile.nationality
    if benefit.scope_type == "COUNTRY":
        return benefit.country_code == candidate.program_country_code
    if benefit.scope_type == "CITY":
        return benefit.location_key == candidate.location_key
    return benefit.program_id == candidate.program_id


def open_routes(profile: StudentProfileSnapshot, candidate: HasFundingRoutes) -> set[str]:
    """Ids of the funding routes still available to this student.

    Anything said about a route that is already shut -- by scope, or by a condition
    the student does not meet -- is noise: a consultant task for a scheme they were
    never in, or a bond warning on an award they cannot take.
    """
    return {
        benefit.id
        for benefit in candidate.benefits
        if benefit.is_current and benefit_applies(benefit, candidate, profile)
    }


def unevaluable_condition_reasons(
    profile: StudentProfileSnapshot, candidate: HasFundingRoutes
) -> tuple[str, ...]:
    """Conditions on still-open routes that no profile field can decide.

    The reason comes from the decider, which names the field the profile lacks,
    so a consultant is told what to ask rather than that something was unclear.
    """
    routes = open_routes(profile, candidate)
    return tuple(
        f"{decision.reason} (funding route {condition.benefit_id}): {condition.rule_text}"
        for condition in candidate.applicant_conditions
        if condition.benefit_id in routes
        and (decision := _decision_for(condition, profile)).outcome == "UNDECIDABLE"
    )


def return_service_disclosures(
    profile: StudentProfileSnapshot, candidate: HasFundingRoutes
) -> tuple[str, ...]:
    """A bonded award is a different product, and the student must be told before
    accepting it. Only for routes that actually apply -- warning about a bond on a
    scheme the student cannot use would push them off an unbonded candidate.
    """
    routes = open_routes(profile, candidate)
    return tuple(
        f"funding route {obligation.benefit_id} is bonded: it commits you to "
        f"{obligation.months} months of return service after graduation \u2014 "
        f"{obligation.rule_text}"
        for obligation in candidate.return_service
        if obligation.benefit_id in routes
    )


# --- Conditions with no route to scope them to --------------------------------
#
# The four functions above scope by funding route, because a PROGRAMME carries
# many of them and a condition on a scheme the student cannot enter is noise. An
# AWARD is one route -- itself -- so there is nothing to scope by, and running
# an award's conditions through `open_routes` drops every one of them: the award
# has no BenefitFact until a page states an amount, so the route set is empty
# and the conditions vanish silently.
#
# These two are the same engine one level down, over a plain list of conditions.
# Both paths go through `_decision_for`, so a malformed row escalates identically
# whichever asked.


def failed_conditions(
    profile: StudentProfileSnapshot, conditions: Sequence[ApplicantConditionFact]
) -> tuple[str, ...]:
    """Conditions this student demonstrably does not meet. FAILED only."""
    return tuple(
        f"{condition.key or condition.condition_type}: {condition.rule_text}"
        for condition in conditions
        if _decision_for(condition, profile).outcome == "FAILED"
    )


def undecidable_conditions(
    profile: StudentProfileSnapshot, conditions: Sequence[ApplicantConditionFact]
) -> tuple[str, ...]:
    """Conditions no profile field can decide, each naming the field it needs.

    UNDECIDABLE is not a soft FAILED: passing it silently offers something that
    may be shut, failing it silently hides something that may be open. It
    becomes a consultant's task with the funder's own sentence attached.
    """
    return tuple(
        f"{decision.reason}: {condition.rule_text}"
        for condition in conditions
        if (decision := _decision_for(condition, profile)).outcome == "UNDECIDABLE"
    )
