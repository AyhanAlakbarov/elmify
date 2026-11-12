from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.accounts.schemas import EvaluationDimension, ProfileConstraint, StudentProfileSnapshot

# The condition engine lives in `conditions.py` so a holder award and a
# programme pairing ask it the same questions (spec 10.2). Re-exported here
# because this module was its address for a year and every caller -- including
# four test modules -- still names it; a move that renamed the import as well
# would have been a rewrite, and the point was that it is not.
from apps.funding.conditions import (  # noqa: F401
    _LEGACY_KEYS,
    _NUMERIC_LEGACY_TYPES,
    _as_triple,
    _decision_for,
    _unmet_conditions,
    benefit_applies,
    closed_route_reasons,
    open_routes,
    unevaluable_condition_reasons,
)
from apps.funding.eligibility import _normalize_language
from apps.funding.validity import Evidence
from apps.reference_data import ISO_3166_ALPHA2_CODES

if TYPE_CHECKING:
    from apps.funding.affordability import AffordabilityResult
    from apps.funding.card import AwardCard
    from apps.funding.fx import RateTable


def funding_gap(annual_cost: Decimal, funding_coverage: Decimal) -> Decimal:
    return max(annual_cost - funding_coverage, Decimal("0"))


_CANDIDATE_CONFIG = ConfigDict(extra="forbid", frozen=True)

CostKind = Literal[
    "TUITION", "APPLICATION_FEE", "HOUSING", "FOOD", "TRANSPORT", "UTILITIES", "INSURANCE", "OTHER"
]
BenefitKind = Literal[
    "TUITION", "STIPEND", "ASSISTANTSHIP", "HOUSING", "INSURANCE", "TRAVEL", "RELOCATION", "OTHER"
]
Period = Literal["ONE_OFF", "MONTHLY", "ANNUAL", "FULL_PROGRAM"]
BenefitScope = Literal["GLOBAL", "COUNTRY", "CITY", "PROGRAM", "NATIONALITY"]
BenefitAccessibility = Literal["ORDINARY", "CAPACITY_LIMITED", "EMERGENCY"]
BenefitConfidence = Literal["VERIFIED", "LIKELY", "UNCERTAIN"]
#: ELIGIBLE_BELOW_FIT_BAR is eligibility's absence, not its doubt: the student
#: may apply and the engine simply does not recommend it. It used to be reported
#: as POSSIBLY_ELIGIBLE_REVIEW with an empty reason list, which told a student
#: their eligibility could not be determined when it had been, and told them
#: nothing they could act on -- the uselessness closed_route_reasons' docstring
#: warns about. The pool is meant to be wider than the pack (P1-7), and these
#: are exactly the candidates that belong in the difference.
EligibilityOutcome = Literal[
    "ELIGIBLE", "ELIGIBLE_BELOW_FIT_BAR", "POSSIBLY_ELIGIBLE_REVIEW", "NOT_ELIGIBLE"
]

#: The balanced strategy's recommendation bars. Named so the check and the
#: sentence explaining it cannot drift apart.
_BALANCED_OVERALL_BAR = Decimal("80")
_BALANCED_DIMENSION_BAR = Decimal("60")

_UPSTREAM_DIMENSIONS: frozenset[EvaluationDimension] = frozenset(
    {"ACADEMIC_FIT", "PROGRAM_FIT", "CAREER_FIT", "DURATION", "MOBILITY_FIT", "RESEARCH_FIT"}
)


class CostLineItem(BaseModel):
    model_config = _CANDIDATE_CONFIG

    kind: CostKind
    amount: Decimal = Field(ge=0)
    currency: str
    period: Period


class BenefitFact(BaseModel):
    model_config = _CANDIDATE_CONFIG

    id: str
    kind: BenefitKind
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    period: Period
    scope_type: BenefitScope
    country_code: str | None = None
    nationality_code: str | None = None
    location_key: str | None = None
    program_id: str | None = None
    accessibility: BenefitAccessibility = "ORDINARY"
    eligibility_confidence: BenefitConfidence = "VERIFIED"
    is_current: bool = True
    #: The fraction of this award the student must pay back. Zero for a grant; AKF's
    #: International Scholarship Programme is half interest-free loan, and counting that
    #: half as coverage understates the gap by exactly it (design §2).
    repayable_share: Decimal = Field(default=Decimal("0"), ge=0, le=1)

    @model_validator(mode="after")
    def amount_and_currency_are_paired(self) -> BenefitFact:
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency must both be null or both present")
        return self

    @model_validator(mode="after")
    def nationality_scope_names_a_nationality(self) -> BenefitFact:
        if self.scope_type == "NATIONALITY" and self.nationality_code is None:
            raise ValueError("a NATIONALITY-scoped benefit requires nationality_code")
        return self


# ApplicantConditionType stays for the rows written before the vocabulary
# landed; `key` is what decides from here on.
ApplicantConditionType = Literal[
    "WORK_EXPERIENCE", "AGE_CAP", "MEANS_TEST", "AFFILIATION", "LANGUAGE", "GUARANTOR"
]
#: WORK_EXPERIENCE is the only condition carrying a unit, because it is the only one
#: funders publish in two of them. Chevening asks for 2,800 hours and the Swedish
#: Institute for 3,000; ADB-JSP asks for two years. None is null: a legacy row and a
#: row explicitly in months mean the same thing, and MONTHS is what the profile holds.
ComparableUnit = Literal["MONTHS", "HOURS"]


class ApplicantConditionFact(BaseModel):
    """One non-nationality condition attached to one funding route (design §4).

    Attached to a benefit, never to the programme: a condition closes the route it
    is published on. A student who fails ADB-JSP's experience bar has lost ADB-JSP,
    not the degree.
    """

    model_config = _CANDIDATE_CONFIG

    benefit_id: str
    condition_type: ApplicantConditionType
    #: The shared vocabulary (apps/funding/eligibility.py). condition_type is the
    #: pre-vocabulary name for the same thing and is mapped to a key when absent.
    key: str = ""
    #: Empty, not "GTE": a legacy row (no explicit key) takes its operator from
    #: _LEGACY_KEYS, which knows what each pre-vocabulary type means (AGE_CAP is
    #: LTE, a maximum); a new-vocabulary row (explicit key) must state its own.
    #: A single GTE default here was wrong for every key except WORK_EXPERIENCE.
    operator: str = ""
    value: str = ""
    #: Months for WORK_EXPERIENCE, years for AGE_CAP, money for MEANS_TEST, and None
    #: for AFFILIATION, which has no number to compare. The means test's currency
    #: stays on the BenefitRule row: nothing compares it until a profile carries
    #: income, and an unread field is one more thing to keep in sync.
    comparable_value: Decimal | None = Field(default=None, ge=0)
    #: Set only where the value's unit is not the default. HOURS cannot be compared to
    #: a profile that counts months without a working-hours-per-month figure no funder
    #: publishes, so an hours bar escalates rather than being converted on a guess.
    comparable_unit: ComparableUnit | None = None
    #: The funder's own sentence, carried so a closed route can be explained.
    rule_text: str


class ReturnServiceFact(BaseModel):
    """A post-award obligation, not a filter (design §4).

    ADB-JSP, Bolashak and YLSY all bind the graduate to return home. Nothing here
    excludes a candidate; a bonded award is a materially different product from an
    unbonded one and the duty this creates is disclosure, discharged in pack.py.
    """

    model_config = _CANDIDATE_CONFIG

    benefit_id: str
    months: int = Field(ge=1)
    rule_text: str


class CandidateFacts(BaseModel):
    """A flat, pre-resolved snapshot of one program + funding-opportunity pairing.

    Deliberately decoupled from the Django catalog models: qualitative fit signals
    (dimension_scores), evidence confidence, and deadline viability are resolved
    upstream (evidence pipeline / discovery) so this module stays pure Decimal
    logic with no I/O, per the plan's Task 11 boundary.
    """

    model_config = _CANDIDATE_CONFIG

    program_id: str
    institution_id: str
    program_country_code: str
    excluded_nationalities: tuple[str, ...] = ()
    location_key: str
    city: str
    field_of_study: str
    teaching_languages: tuple[str, ...]
    duration_months: int = Field(ge=1, le=60)
    language_evidence_required: bool
    language_evidence_deadline: date | None
    application_deadline: date | None
    scholarship_decision_deadline: date | None = None
    deadline_is_viable: bool
    confirmed_eligibility_failure: bool
    evidence_confidence: Literal["HIGH", "MEDIUM", "LOW"]
    cost_components: tuple[CostLineItem, ...]
    benefits: tuple[BenefitFact, ...]
    applicant_conditions: tuple[ApplicantConditionFact, ...] = ()
    return_service: tuple[ReturnServiceFact, ...] = ()
    dimension_scores: Mapping[EvaluationDimension, Decimal]

    @field_validator("program_country_code")
    @classmethod
    def program_country_is_active(cls, value: str) -> str:
        if value not in ISO_3166_ALPHA2_CODES:
            raise ValueError("country must be an active ISO 3166-1 alpha-2 code")
        return value

    @field_validator("excluded_nationalities")
    @classmethod
    def excluded_nationalities_are_active(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        # The hard gates compare these against the ISO-validated, canonically uppercase
        # profile fields with exact equality, so an unnormalized code here would defeat
        # the gate silently rather than failing.
        if any(value not in ISO_3166_ALPHA2_CODES for value in values):
            raise ValueError("nationality must be an active ISO 3166-1 alpha-2 code")
        return values

    @field_validator("dimension_scores")
    @classmethod
    def dimension_scores_cover_upstream_dimensions(
        cls, value: Mapping[EvaluationDimension, Decimal]
    ) -> dict[EvaluationDimension, Decimal]:
        if set(value) != _UPSTREAM_DIMENSIONS:
            raise ValueError(
                "dimension_scores must provide exactly the upstream-scored dimensions "
                f"{sorted(_UPSTREAM_DIMENSIONS)}"
            )
        if any(score < 0 or score > 100 for score in value.values()):
            raise ValueError("dimension scores must be between 0 and 100")
        return dict(value)


@dataclass(frozen=True)
class DimensionScore:
    dimension: EvaluationDimension
    score: Decimal
    weight: Decimal


@dataclass(frozen=True)
class EvaluationScores:
    overall: Decimal
    dimensions: tuple[DimensionScore, ...]
    critical_values: tuple[Decimal, ...]


@dataclass(frozen=True)
class RecommendationOutcome:
    outcome: EligibilityOutcome
    reasons: tuple[str, ...]
    scores: EvaluationScores | None


def duration_category(duration_months: int) -> Literal["ONE_YEAR", "TWO_YEAR"]:
    return "ONE_YEAR" if duration_months <= 12 else "TWO_YEAR"


def _teaching_language_gate(profile: StudentProfileSnapshot, candidate: CandidateFacts) -> bool:
    accepted = {_normalize_language(language) for language in profile.acceptable_teaching_languages}
    return any(
        _normalize_language(language) in accepted for language in candidate.teaching_languages
    )


def _language_evidence_gate(profile: StudentProfileSnapshot, candidate: CandidateFacts) -> bool:
    if not candidate.language_evidence_required:
        return True
    accepted = {_normalize_language(language) for language in profile.acceptable_teaching_languages}
    candidate_langs = {_normalize_language(language) for language in candidate.teaching_languages}
    target_langs = (accepted & candidate_langs) if candidate_langs else accepted
    deadline = candidate.language_evidence_deadline or candidate.application_deadline
    for evidence in profile.language_evidence:
        if _normalize_language(evidence.language) not in target_langs:
            continue
        if deadline is None or evidence.available_by <= deadline:
            return True
    return False


def _constraint_satisfied(constraint: ProfileConstraint, candidate: CandidateFacts) -> bool:
    value = constraint.value.strip().casefold()
    if constraint.kind == "LOCATION":
        return value in {
            candidate.city.casefold(),
            candidate.program_country_code.casefold(),
            candidate.location_key.casefold(),
        }
    if constraint.kind == "LANGUAGE":
        return _normalize_language(value) in {
            _normalize_language(language) for language in candidate.teaching_languages
        }
    if constraint.kind == "FIELD":
        return value in candidate.field_of_study.casefold()
    if constraint.kind == "DURATION":
        return value == str(candidate.duration_months)
    # ponytail: OTHER constraints have no structured field to check against; treat as
    # satisfied until a richer constraint taxonomy exists for this catch-all kind.
    return True


def _non_negotiables_gate(profile: StudentProfileSnapshot, candidate: CandidateFacts) -> bool:
    return all(_constraint_satisfied(c, candidate) for c in profile.non_negotiables)


def _duration_gate(profile: StudentProfileSnapshot, candidate: CandidateFacts) -> bool:
    if profile.duration_flexibility != "NON_NEGOTIABLE":
        return True
    return duration_category(candidate.duration_months) == profile.duration_preference


def _country_preference_gate(profile: StudentProfileSnapshot, candidate: CandidateFacts) -> bool:
    if candidate.program_country_code in profile.excluded_countries:
        return False
    if (
        profile.allowed_countries
        and candidate.program_country_code not in profile.allowed_countries
    ):
        return False
    return True


def _nationality_admission_gate(profile: StudentProfileSnapshot, candidate: CandidateFacts) -> bool:
    return profile.nationality not in candidate.excluded_nationalities


def _mandatory_funding_route_gate(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    *,
    today: date | None = None,
) -> bool:
    if profile.funding_dependency != "MANDATORY":
        return True
    return any(
        benefit.is_current
        and benefit.accessibility == "ORDINARY"
        and benefit.eligibility_confidence == "VERIFIED"
        and benefit_applies(benefit, candidate, profile, today=today)
        for benefit in candidate.benefits
    )


@dataclass(frozen=True)
class HardGate:
    reason: str
    passes: Callable[[StudentProfileSnapshot, CandidateFacts], bool]


HARD_GATES: tuple[HardGate, ...] = (
    HardGate(
        "no accepted-language teaching-language evidence covers this program's teaching language",
        _teaching_language_gate,
    ),
    HardGate(
        "required teaching-language evidence cannot be delivered by the applicable deadline",
        _language_evidence_gate,
    ),
    HardGate(
        "the program has a confirmed eligibility failure for this student",
        lambda profile, candidate: not candidate.confirmed_eligibility_failure,
    ),
    HardGate(
        "the application deadline is not viable",
        lambda profile, candidate: candidate.deadline_is_viable,
    ),
    HardGate(
        "official evidence confidence is below the required medium threshold",
        lambda profile, candidate: candidate.evidence_confidence != "LOW",
    ),
    HardGate("a student non-negotiable constraint is not satisfied", _non_negotiables_gate),
    HardGate(
        "the program is in a country the student excluded, or outside the countries the "
        "student allowed",
        _country_preference_gate,
    ),
    HardGate(
        "the institution does not admit applicants of the student's nationality",
        _nationality_admission_gate,
    ),
    HardGate(
        "the program duration does not match the student's non-negotiable duration preference",
        _duration_gate,
    ),
    HardGate(
        "funding is mandatory for this student and no viable verified funding route exists",
        _mandatory_funding_route_gate,
    ),
)


def _has_profile_flag(profile: StudentProfileSnapshot, flag: str) -> bool:
    target = flag.strip().upper()
    return any(
        c.kind == "OTHER" and c.value.strip().upper() == target
        for c in (*profile.non_negotiables, *profile.negotiable_preferences)
    )


def _wants_top_universities_only(profile: StudentProfileSnapshot) -> bool:
    return _has_profile_flag(profile, "TOP_UNIVERSITIES_ONLY")


def _strict_top_universities_only(profile: StudentProfileSnapshot) -> bool:
    return any(
        c.kind == "OTHER" and c.value.strip().upper() == "TOP_UNIVERSITIES_ONLY"
        for c in profile.non_negotiables
    )


def has_post_admission_gov_scholarship(profile: StudentProfileSnapshot) -> bool:
    return _has_profile_flag(profile, "GOV_SCHOLARSHIP_AFTER_ADMISSION")


def post_admission_gov_scheme_for_candidate(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    awards: Sequence[AwardCandidateFacts] = (),
    *,
    today: date | None = None,
) -> str | None:
    """Return the admission-contingent post-admission scholarship scheme name if
    the student opted into post-admission government/external funding and the
    foreign programme qualifies dynamically on fit/selectivity."""
    if not has_post_admission_gov_scholarship(profile):
        return None
    if (
        candidate.program_country_code
        and profile.nationality
        and candidate.program_country_code.upper() == profile.nationality.upper()
    ):
        return None
    from apps.funding.probability import is_selective_candidate

    acad = candidate.dimension_scores.get("ACADEMIC_FIT", Decimal("0"))
    prog = candidate.dimension_scores.get("PROGRAM_FIT", Decimal("0"))
    if not (
        is_selective_candidate(candidate)
        or (acad >= Decimal("80") and prog >= Decimal("80"))
    ):
        return None
    ref_today = today or date.today()
    for award in awards:
        if (
            award.card is not None
            and award.card.tuition == "FULL"
            and award.card.living == "FULL"
            and award.country_code
            and profile.nationality
            and award.country_code.upper() == profile.nationality.upper()
            and evaluate_award(profile, award, today=ref_today).outcome
            in ("ELIGIBLE", "POSSIBLY_ELIGIBLE_REVIEW")
        ):
            return award.name
    return "Post-Admission Government Scholarship"


def applicable_dimensions(profile: StudentProfileSnapshot) -> frozenset[EvaluationDimension]:
    unconstrained_self_funded = (
        profile.funding_dependency == "OPTIONAL" and profile.self_funding_capacity is None
    ) or (
        profile.funding_dependency in {"OPTIONAL", "IMPORTANT"}
        and _has_profile_flag(profile, "NO_FUNDING_NEEDED")
    )
    dimensions: set[EvaluationDimension] = {
        "ACADEMIC_FIT",
        "PROGRAM_FIT",
        "CAREER_FIT",
    }
    if not unconstrained_self_funded:
        dimensions.add("AFFORDABILITY")
    if profile.duration_preference != "NONE":
        dimensions.add("DURATION")
    if profile.research_interests:
        dimensions.add("RESEARCH_FIT")
    if profile.mobility_priorities:
        dimensions.add("MOBILITY_FIT")
    return frozenset(dimensions)


def redistribute_weights(
    weights: Mapping[EvaluationDimension, Decimal], applicable: frozenset[EvaluationDimension]
) -> dict[EvaluationDimension, Decimal]:
    ordered: list[EvaluationDimension] = sorted(applicable)
    kept_total = sum((weights.get(dim, Decimal("0")) for dim in ordered), Decimal("0"))
    if kept_total == 0:
        even_share = Decimal("1") / Decimal(len(ordered))
        result = {dim: even_share for dim in ordered}
    else:
        result = {dim: weights.get(dim, Decimal("0")) / kept_total for dim in ordered}
    *head, last = ordered
    result[last] = Decimal("1") - sum((result[dim] for dim in head), Decimal("0"))
    return result


def _affordability_score(affordability: AffordabilityResult) -> Decimal:
    if affordability.baseline_cost <= 0:
        return Decimal("100")
    # What the student must still find: a gap their own money covers is affordable.
    ratio = affordability.shortfall / affordability.baseline_cost
    score = (Decimal("1") - ratio) * Decimal("100")
    return max(Decimal("0"), min(Decimal("100"), score))


def score_dimensions(
    profile: StudentProfileSnapshot, candidate: CandidateFacts, affordability: AffordabilityResult
) -> EvaluationScores:
    applicable = applicable_dimensions(profile)
    weights = redistribute_weights(profile.weights, applicable)
    scores: dict[EvaluationDimension, Decimal] = dict(candidate.dimension_scores)
    scores["AFFORDABILITY"] = _affordability_score(affordability)

    if (
        "DURATION" in scores
        and profile.duration_preference == "ONE_YEAR"
        and profile.duration_flexibility == "WEIGHTED"
        and duration_category(candidate.duration_months) == "TWO_YEAR"
        and "FUNDING" in profile.longer_program_justifications
        and (affordability.covered > 0 or affordability.conditional_savings > 0)
    ):
        scores["DURATION"] = max(scores["DURATION"], Decimal("85"))

    _pref_kind_to_dim: dict[str, EvaluationDimension] = {
        "LOCATION": "MOBILITY_FIT",
        "LANGUAGE": "ACADEMIC_FIT",
        "FIELD": "PROGRAM_FIT",
        "DURATION": "DURATION",
    }
    for pref in profile.negotiable_preferences:
        dim = _pref_kind_to_dim.get(pref.kind)
        if dim is not None and dim in scores and _constraint_satisfied(pref, candidate):
            scores[dim] = min(Decimal("95"), scores[dim] + Decimal("5"))

    dimensions = tuple(
        DimensionScore(dimension=dim, score=scores[dim], weight=weights[dim])
        for dim in sorted(applicable)
    )
    overall = sum((d.score * d.weight for d in dimensions), Decimal("0"))
    critical_values = tuple(d.score for d in dimensions)
    return EvaluationScores(overall=overall, dimensions=dimensions, critical_values=critical_values)


def _below_bar_reasons(
    scores: EvaluationScores, *, strict_top: bool = False
) -> tuple[str, ...]:
    """Why an eligible candidate is not recommended, in the numbers behind it.

    "Weaker fit" on its own sends a student looking for a bar they failed
    without saying which; each sentence here names the dimension and its score.
    """
    reasons: list[str] = []
    if scores.overall < _BALANCED_OVERALL_BAR:
        reasons.append(
            f"overall fit {scores.overall:.0f} is below the {_BALANCED_OVERALL_BAR:.0f} "
            "a balanced recommendation requires"
        )
    reasons.extend(
        f"{dimension.dimension} scores {dimension.score:.0f}, below the "
        f"{_BALANCED_DIMENSION_BAR:.0f} every dimension must reach"
        for dimension in scores.dimensions
        if dimension.score < _BALANCED_DIMENSION_BAR
    )
    if strict_top:
        reasons.extend(
            f"{dimension.dimension} scores {dimension.score:.0f}, below the "
            f"{_BALANCED_OVERALL_BAR:.0f} required for top-tier programmes"
            for dimension in scores.dimensions
            if dimension.dimension in {"ACADEMIC_FIT", "PROGRAM_FIT"}
            and _BALANCED_DIMENSION_BAR <= dimension.score < _BALANCED_OVERALL_BAR
        )
    return tuple(reasons)


#: The one gate winnable funding may stand in for (`evaluate`).
_MANDATORY_FUNDING_GATE = next(
    gate for gate in HARD_GATES if gate.passes is _mandatory_funding_route_gate
)


def needs_selective_funding(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    *,
    today: date | None = None,
) -> bool:
    """True for a programme a mandatory-funding student can afford only by
    winning selective funding: it passed `evaluate` without a guaranteed route."""
    return profile.funding_dependency == "MANDATORY" and not _mandatory_funding_route_gate(
        profile, candidate, today=today
    )


def _programme_money_closes_the_gap(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    rates: RateTable,
    *,
    today: date | None = None,
) -> bool:
    """The programme's own selective funding, if all of it were won, pays what
    guaranteed money and the student's own do not. A programme with no cost
    rows never qualifies: its gap is unknown, not zero."""
    from apps.funding.affordability import calculate_affordability

    money = calculate_affordability(profile, candidate, rates, today=today)
    return (
        money.baseline_cost > 0
        and money.conditional_savings > 0
        and money.shortfall - money.conditional_savings <= 0
    )


def _strip_undecidable_secondary_routes(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    rates: RateTable,
    *,
    schemes: tuple[str, ...] = (),
    today: date | None = None,
) -> CandidateFacts:
    """When a candidate has both a clean open funding route and a secondary
    route with an undecidable condition, strip the undecidable route so it
    neither excludes the programme nor counts as unverified coverage."""
    routes = open_routes(profile, candidate, today=today)
    undecidable_route_ids = {
        condition.benefit_id
        for condition in candidate.applicant_conditions
        if condition.benefit_id in routes
        and _decision_for(condition, profile, today=today).outcome == "UNDECIDABLE"
    }
    if not undecidable_route_ids or (not (routes - undecidable_route_ids) and not schemes):
        return candidate
    clean_candidate = candidate.model_copy(
        update={
            "benefits": tuple(
                b for b in candidate.benefits if b.id not in undecidable_route_ids
            ),
            "applicant_conditions": tuple(
                c
                for c in candidate.applicant_conditions
                if c.benefit_id not in undecidable_route_ids
            ),
        }
    )
    if (
        _mandatory_funding_route_gate(profile, clean_candidate, today=today)
        or schemes
        or _programme_money_closes_the_gap(profile, clean_candidate, rates, today=today)
    ):
        return clean_candidate
    return candidate


def evaluate(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    rates: RateTable,
    *,
    schemes: tuple[str, ...] = (),
    today: date | None = None,
) -> RecommendationOutcome:
    """`schemes`: the eligible, full-cover scholarships that pay for this
    programme (`schemes_paying_for`), which the caller holds and this
    function does not."""
    gov_scheme = post_admission_gov_scheme_for_candidate(
        profile, candidate, today=today
    )
    if gov_scheme is not None and gov_scheme not in schemes:
        schemes = (*schemes, gov_scheme)
    failing = [
        gate
        for gate in HARD_GATES
        if not (
            _mandatory_funding_route_gate(profile, candidate, today=today)
            if gate is _MANDATORY_FUNDING_GATE
            else gate.passes(profile, candidate)
        )
    ]
    # Owner, 2026-10-24: a mandatory-funding student also sees a programme that
    # selective funding, if won, would pay for -- labelled conditional by the
    # pack, never counted as coverage. Only when that gate is the ONE failure.
    if failing == [_MANDATORY_FUNDING_GATE] and (
        schemes or _programme_money_closes_the_gap(profile, candidate, rates, today=today)
    ):
        failing = []
    failures = tuple(gate.reason for gate in failing)
    if failures:
        # A gate's reason is static text; the condition that shut a route is not. Append
        # it so an excluded candidate says which scheme closed and on what bar.
        return RecommendationOutcome(
            "NOT_ELIGIBLE",
            failures + closed_route_reasons(profile, candidate, today=today),
            None,
        )

    effective_candidate = _strip_undecidable_secondary_routes(
        profile, candidate, rates, schemes=schemes, today=today
    )

    from apps.funding.affordability import calculate_affordability

    affordability = calculate_affordability(profile, effective_candidate, rates, today=today)
    scores = score_dimensions(profile, effective_candidate, affordability)

    top_only = _wants_top_universities_only(profile)
    strict_top = _strict_top_universities_only(profile)
    post_admit_gov = has_post_admission_gov_scholarship(profile)
    if profile.strategy == "BALANCED" or top_only or post_admit_gov:
        selective_covers_gap = bool(
            (top_only or post_admit_gov)
            and (
                schemes
                or _programme_money_closes_the_gap(
                    profile, effective_candidate, rates, today=today
                )
            )
        )
        if selective_covers_gap:
            non_aff = [
                d.score for d in scores.dimensions if d.dimension != "AFFORDABILITY"
            ]
            avg_non_aff = (
                sum(non_aff, Decimal("0")) / Decimal(len(non_aff))
                if non_aff
                else Decimal("0")
            )
            qualifies = (
                avg_non_aff >= _BALANCED_OVERALL_BAR
                and (min(non_aff) if non_aff else Decimal("0")) >= _BALANCED_DIMENSION_BAR
            )
        else:
            qualifies = (
                scores.overall >= _BALANCED_OVERALL_BAR
                and min(scores.critical_values) >= _BALANCED_DIMENSION_BAR
            )
        if qualifies and strict_top:
            acad_score = candidate.dimension_scores.get("ACADEMIC_FIT", Decimal("0"))
            prog_score = candidate.dimension_scores.get("PROGRAM_FIT", Decimal("0"))
            qualifies = (
                acad_score >= _BALANCED_OVERALL_BAR
                and prog_score >= _BALANCED_OVERALL_BAR
            )
    else:
        # ponytail: StudentProfileSnapshot has no dedicated "required affordability
        # threshold" field. The mandatory-funding hard gate already requires a verified
        # ordinary route, or selective funding that would pay if won (above), whenever
        # funding is mandatory, so funding-first has no
        # universal per-dimension or per-gap minimum beyond hard gates (matches P1-6);
        # the remaining gap only drives ranking order, not eligibility. Revisit if a
        # concrete threshold field is ever added to the profile schema.
        qualifies = True

    # A condition no profile field can decide is neither a pass nor a fail. Passing it
    # silently offers a route that may be shut; failing it silently hides one that may
    # be open. Both are wrong, so it becomes a consultant's task.
    review_reasons = unevaluable_condition_reasons(
        profile, effective_candidate, today=today
    )
    # Review first: a bar only a human can judge is the more useful thing to
    # report about a candidate that is also merely weak.
    if review_reasons:
        return RecommendationOutcome("POSSIBLY_ELIGIBLE_REVIEW", review_reasons, scores)
    if not qualifies:
        return RecommendationOutcome(
            "ELIGIBLE_BELOW_FIT_BAR",
            _below_bar_reasons(scores, strict_top=strict_top),
            scores,
        )
    return RecommendationOutcome("ELIGIBLE", (), scores)


# --- Awards ------------------------------------------------------------------
#
# An award is an application of its own, not a discount on a programme (owner
# decision 2026-09-19). `CandidateFacts` is deliberately UNCHANGED, so today's
# HARD_GATES and their 41 tests are untouched; the rejected alternative was one
# shared fact type with an optional `program_id`, which needs an `if` in every
# programme gate, and a gate that silently skips is worse than a crash here.


@dataclass(frozen=True)
class AwardCandidateFacts:
    """One served holder award, as the award gates read it.

    A dataclass rather than a pydantic model, unlike `CandidateFacts`: every
    field is built by `facts.award_facts` from our own catalogue rows, so there
    is no untrusted input to validate, and it carries a `validity.Evidence`,
    which is itself a dataclass.

    It satisfies `conditions.HasFundingRoutes` structurally -- which is what
    lets one condition engine answer for both fact types without naming either.
    """

    award_id: str
    name: str
    holder_name: str
    organisation_id: str
    money_form: str
    route: str
    #: Decided fields the readings split on. Shown as a caveat; never filtered on.
    unconfirmed: tuple[str, ...]
    benefits: tuple[BenefitFact, ...]
    applicant_conditions: tuple[ApplicantConditionFact, ...]
    return_service: tuple[ReturnServiceFact, ...]
    evidence_confidence: Literal["HIGH", "MEDIUM", "LOW"]
    evidence: Evidence
    #: True when no benefit row states an amount. NOT the same as zero.
    coverage_is_unstated: bool
    #: The card's own fields (spec 10.4). None only for a fact built by hand in
    #: a test; award_facts always sets it.
    card: AwardCard | None = None
    #: Which programmes this award can pay for, by the same rule the page groups
    #: by (`grouping.funds`): its own programme list, its institution, or its
    #: country. Set by the spine from catalogue rows; blank links nothing.
    scope: str = "HOLDER"
    institution_id: str = ""
    country_code: str = ""
    pays_for_program_ids: frozenset[str] = frozenset()

    # `HasFundingRoutes` wants these three; an award is anchored to a holder,
    # not to a place, so its scope-matching is GLOBAL and they are blank.
    @property
    def program_id(self) -> str:
        return ""

    @property
    def program_country_code(self) -> str:
        return ""

    @property
    def location_key(self) -> str:
        return ""


def evaluate_award(
    profile: StudentProfileSnapshot,
    award: AwardCandidateFacts,
    *,
    today: date,
) -> RecommendationOutcome:
    """The four award gates, in the order a student would ask them.

    1. a condition the student demonstrably fails shuts the award;
    2. the cycle is not stated as shut;
    3. this student's own deadline is still reachable for their intake;
    4. the evidence is not LOW.

    **Gate 2 is deliberately weaker than the spec's "only OPEN and UPCOMING are
    shown", and this paragraph is the reason.** `cycle_validity` runs on step-0
    evidence only -- what the reader stored off the page. Without the evidence
    ladder there is no call history, so `UPCOMING` is unreachable and most
    awards return `UNVERIFIED`. So the gate hides an award only when the
    evidence says it is SHUT (`SUSPENDED`, `ENDED`, a passed deadline); an
    `UNVERIFIED` award enters the pool flagged and never the recommended pack.
    It tightens automatically when the ladder lands -- same function, more
    evidence. Gating hard today empties the pack for want of a crawler, which is
    the worse failure.
    """
    from apps.funding.conditions import failed_conditions, undecidable_conditions
    from apps.funding.cycle_evidence import deadline_student
    from apps.funding.validity import (
        cycle_validity,
        default_intake_start_for_country,
        select_deadline,
    )

    shut = failed_conditions(profile, award.applicant_conditions, today=today)
    if shut:
        return RecommendationOutcome("NOT_ELIGIBLE", shut, None)

    target_intake = str(profile.intended_intake.year)
    student = deadline_student(profile.nationality, profile.country_of_residence)
    validity = cycle_validity(
        award.evidence,
        student=student,
        target_intake=target_intake,
        today=today,
        intake_starts_on=default_intake_start_for_country(
            award.country_code, profile.intended_intake.year, today=today
        ),
    )
    if validity in ("SUSPENDED", "ENDED"):
        quote = award.evidence.contrary_intake or target_intake
        return RecommendationOutcome(
            "NOT_ELIGIBLE",
            (f"{award.name} is not offered for {quote} on its own page",),
            None,
        )

    deadline = select_deadline(award.evidence, student)
    if deadline is not None and deadline.date is not None and deadline.date < today:
        return RecommendationOutcome(
            "NOT_ELIGIBLE",
            (f"{award.name} closed on {deadline.date.isoformat()}",),
            None,
        )

    if award.evidence_confidence == "LOW":
        return RecommendationOutcome(
            "NOT_ELIGIBLE",
            (f"the readings did not agree that {award.name} exists as described",),
            None,
        )

    review = undecidable_conditions(profile, award.applicant_conditions, today=today)
    if review:
        return RecommendationOutcome("POSSIBLY_ELIGIBLE_REVIEW", review, None)
    return RecommendationOutcome("ELIGIBLE", (), None)


def scheme_pays_for(
    award: AwardCandidateFacts, candidate: CandidateFacts, *, home_country: str
) -> bool:
    """Whether a scholarship can pay for this programme, by the rule the page
    groups by (`apps/funding/grouping.py::funds`): its own programme list, its
    institution, its country, or anywhere. One exception: a scheme from the
    student's own country is never linked by country, because a home
    government's scheme (the State Programme, HTP) pays for study ABROAD and
    its country is the holder's, not the destination."""
    if candidate.program_id in award.pays_for_program_ids:
        return True
    if award.scope == "INSTITUTION":
        return bool(award.institution_id) and award.institution_id == candidate.institution_id
    if award.scope in ("HOLDER", "COUNTRY"):
        return (
            bool(award.country_code)
            and award.country_code != home_country
            and award.country_code == candidate.program_country_code
        )
    return award.scope == "GLOBAL"


def schemes_paying_for(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    awards: Sequence[AwardCandidateFacts],
    *,
    today: date,
) -> tuple[str, ...]:
    """The scholarships that would pay for this programme in full if won
    (owner, 2026-10-24): the student is eligible (or queued for human review on
    an undecidable bar such as an unextracted country list), the card states
    FULL tuition and FULL living, and the scheme links to the programme. Names,
    in order."""
    from apps.funding.probability import is_post_admission_gov_scholarship

    names = [
        award.name
        for award in awards
        if award.card is not None
        and award.card.tuition == "FULL"
        and award.card.living == "FULL"
        and scheme_pays_for(award, candidate, home_country=profile.nationality)
        and evaluate_award(profile, award, today=today).outcome
        in ("ELIGIBLE", "POSSIBLY_ELIGIBLE_REVIEW")
    ]
    gov_scheme = post_admission_gov_scheme_for_candidate(
        profile, candidate, awards, today=today
    )
    if gov_scheme is not None and not any(
        is_post_admission_gov_scholarship(n, home_country=profile.nationality)
        for n in names
    ):
        names.append(gov_scheme)
    return tuple(names)
