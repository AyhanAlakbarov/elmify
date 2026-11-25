from collections.abc import Callable, Hashable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic_core import PydanticCustomError

from apps.reference_data import ISO_3166_ALPHA2_CODES, ISO_4217_CODES

_PROFILE_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
NonBlankText100 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
NonBlankText200 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
CountryCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2)]


class Money(BaseModel):
    model_config = _PROFILE_CONFIG

    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("currency")
    @classmethod
    def currency_is_active(cls, value: str) -> str:
        if value not in ISO_4217_CODES:
            raise ValueError("currency must be an active ISO 4217 code")
        return value


class CourseRecord(BaseModel):
    """One course from a transcript, credits already in ECTS.

    `ects` is None when the credit system could not be converted
    (apps/documents/credits.py) -- unknown, never guessed.
    `description` optionally records syllabus topics or module content to clarify
    opaque transcript titles (e.g. 'Special Topics in CS I' or 'Elective Module 3').
    """

    model_config = _PROFILE_CONFIG

    title: str = Field(min_length=1, max_length=200)
    ects: Decimal | None = Field(default=None, ge=0, le=100, max_digits=6, decimal_places=2)
    grade: str | None = Field(default=None, max_length=50)
    in_progress: bool = False
    description: str | None = Field(default=None, max_length=500)

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        if data.get("description") is None:
            data.pop("description", None)
        return data


class AcademicRecord(BaseModel):
    model_config = _PROFILE_CONFIG

    institution: str = Field(min_length=1, max_length=200)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    qualification: str = Field(min_length=1, max_length=100)
    field: str = Field(min_length=1, max_length=200)
    grade: str = Field(min_length=1, max_length=50)
    grading_scale: str = Field(min_length=1, max_length=100)
    completed_on: date | None = None
    #: For a student still studying: completed_on is None and this is set.
    expected_completion: date | None = None
    courses: tuple[CourseRecord, ...] = Field(default=(), max_length=150)

    @field_validator("country_code")
    @classmethod
    def country_is_active(cls, value: str) -> str:
        if value not in ISO_3166_ALPHA2_CODES:
            raise ValueError("country must be an active ISO 3166-1 alpha-2 code")
        return value


class LanguageEvidence(BaseModel):
    model_config = _PROFILE_CONFIG

    language: str = Field(min_length=1, max_length=100)
    level: str = Field(min_length=1, max_length=50)
    evidence_type: Literal["ATTESTED", "TEST", "DEGREE", "OTHER"]
    available_by: date


class ExperienceRecord(BaseModel):
    model_config = _PROFILE_CONFIG

    kind: Literal["WORK", "RESEARCH", "INTERNSHIP", "OTHER"]
    summary: str = Field(min_length=1, max_length=1_000)
    months: int = Field(ge=0, le=600)


class ActivityRecord(BaseModel):
    """A job, internship, research post or volunteer role the student typed in the
    profile (2026-11-16). `experience` above stays the matcher's input: it is derived
    from the paid rows of `work_history` when the student answered that question."""

    model_config = _PROFILE_CONFIG

    kind: Literal["WORK", "INTERNSHIP", "RESEARCH", "VOLUNTEER"]
    title: str = Field(min_length=1, max_length=200)
    organisation: str = Field(min_length=1, max_length=300)
    start_date: date
    #: None while the role is ongoing.
    end_date: date | None = None


PublicationLevel = Literal[
    "Q1", "Q2", "Q3", "Q4", "INDEXED", "NOT_INDEXED", "CONFERENCE", "PREPRINT", "OTHER"
]


class PublicationRecord(BaseModel):
    model_config = _PROFILE_CONFIG

    title: str = Field(min_length=1, max_length=300)
    #: Every author as the byline prints them, in order, the student included.
    authors: str = Field(min_length=1, max_length=500)
    venue: str = Field(min_length=1, max_length=300)
    year: int = Field(ge=1950, le=2100)
    level: PublicationLevel


class ProjectRecord(BaseModel):
    model_config = _PROFILE_CONFIG

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    year: int | None = Field(default=None, ge=1950, le=2100)


class ProfileConstraint(BaseModel):
    model_config = _PROFILE_CONFIG

    kind: Literal["DURATION", "LOCATION", "LANGUAGE", "FIELD", "OTHER"]
    value: str = Field(min_length=1, max_length=200)


DurationPreference = Literal["ONE_YEAR", "ONE_AND_HALF_YEAR", "TWO_YEAR", "NONE"]

EvaluationDimension = Literal[
    "ACADEMIC_FIT",
    "PROGRAM_FIT",
    "CAREER_FIT",
    "AFFORDABILITY",
    "DURATION",
    "MOBILITY_FIT",
    "RESEARCH_FIT",
]
EVALUATION_DIMENSIONS: tuple[EvaluationDimension, ...] = (
    "ACADEMIC_FIT",
    "PROGRAM_FIT",
    "CAREER_FIT",
    "AFFORDABILITY",
    "DURATION",
    "MOBILITY_FIT",
    "RESEARCH_FIT",
)

#: Used when the student does not set weights -- the onboarding no longer asks
#: (spec T3). A product constant, adjustable on the pack; sums to exactly one.
DEFAULT_WEIGHTS: Mapping[EvaluationDimension, Decimal] = MappingProxyType(
    {
        "ACADEMIC_FIT": Decimal("0.20"),
        "PROGRAM_FIT": Decimal("0.20"),
        "CAREER_FIT": Decimal("0.15"),
        "AFFORDABILITY": Decimal("0.20"),
        "DURATION": Decimal("0.05"),
        "MOBILITY_FIT": Decimal("0.10"),
        "RESEARCH_FIT": Decimal("0.10"),
    }
)

_BASELINE_SALIENCE: Mapping[EvaluationDimension, int] = MappingProxyType(
    {
        "ACADEMIC_FIT": 30,
        "PROGRAM_FIT": 30,
        "AFFORDABILITY": 30,
        "CAREER_FIT": 20,
        "MOBILITY_FIT": 10,
        "RESEARCH_FIT": 10,
        "DURATION": 0,
    }
)
_ROC_EPSILON = Decimal("0.03")
_DIRICHLET_PRIOR_TAU = Decimal("40")
_MAX_SHRINKAGE_LAMBDA = Decimal("0.65")


def compute_weak_order_roc_weights(
    salience: Mapping[EvaluationDimension, int | Decimal],
    *,
    epsilon: Decimal = _ROC_EPSILON,
) -> dict[EvaluationDimension, Decimal]:
    """Compute the exact Weak-Order Rank-Order Centroid (WROC) on the epsilon-floored simplex.

    Follows Barron & Barrett (1996, Management Science 42(11):1515-1523) and
    Edwards & Barron (1994, OBHDP 60(3):306-325) generalized to an epsilon-floored
    preference polytope P_{pi,epsilon} = {w in Delta^{K-1} : w_{pi(1)} >= ... >= epsilon}.
    """
    k_count = len(EVALUATION_DIMENSIONS)
    k_dec = Decimal(k_count)
    free_mass = Decimal("1") - k_dec * epsilon

    roc_by_rank: list[Decimal] = []
    for rank_idx in range(1, k_count + 1):
        harmonic_tail = sum(
            (Decimal("1") / Decimal(j) for j in range(rank_idx, k_count + 1)),
            Decimal("0"),
        )
        roc_by_rank.append(epsilon + (free_mass / k_dec) * harmonic_tail)

    ordered_dims = sorted(
        EVALUATION_DIMENSIONS,
        key=lambda d: (-Decimal(salience[d]), EVALUATION_DIMENSIONS.index(d)),
    )

    result: dict[EvaluationDimension, Decimal] = {}
    idx = 0
    while idx < k_count:
        end_idx = idx + 1
        current_sal = Decimal(salience[ordered_dims[idx]])
        while (
            end_idx < k_count
            and Decimal(salience[ordered_dims[end_idx]]) == current_sal
        ):
            end_idx += 1
        block_size = Decimal(end_idx - idx)
        block_avg = sum(roc_by_rank[idx:end_idx], Decimal("0")) / block_size
        for pos in range(idx, end_idx):
            result[ordered_dims[pos]] = block_avg
        idx = end_idx

    return result


def _extract_profile_flags(profile_or_payload: Mapping[str, Any] | Any) -> set[str]:
    def _get(field: str, default: Any = None) -> Any:
        if isinstance(profile_or_payload, Mapping):
            return profile_or_payload.get(field, default)
        return getattr(profile_or_payload, field, default)

    flags: set[str] = set()
    for item in _get("mobility_priorities") or ():
        if isinstance(item, str) and item.strip():
            flags.add(item.strip().upper())
    for list_field in ("non_negotiables", "negotiable_preferences"):
        for item in _get(list_field) or ():
            if isinstance(item, Mapping):
                val = item.get("value")
            else:
                val = getattr(item, "value", None)
            if isinstance(val, str) and val.strip():
                flags.add(val.strip().upper())
    return flags


def infer_simplex_weights_from_profile(
    profile_or_payload: Mapping[str, Any] | Any,
    *,
    epsilon: Decimal = _ROC_EPSILON,
) -> dict[EvaluationDimension, Decimal]:
    """Infer a personalized simplex weight vector w in Delta^6 from categorical regime choices.

    Combines the Weak-Order Rank-Order Centroid w^{WROC(epsilon)} of the student's
    induced preference polytope with a conjugate Dirichlet prior anchored at
    DEFAULT_WEIGHTS. Returns dict(DEFAULT_WEIGHTS) whenever no regime signal
    differentiates dimensions beyond neutral baseline defaults.
    """
    def _get(field: str, default: Any = None) -> Any:
        if isinstance(profile_or_payload, Mapping):
            return profile_or_payload.get(field, default)
        return getattr(profile_or_payload, field, default)

    delta: dict[EvaluationDimension, int] = {d: 0 for d in EVALUATION_DIMENSIONS}
    flags = _extract_profile_flags(profile_or_payload)

    funding_dep = _get("funding_dependency")
    career_intent = _get("career_intent")
    duration_pref = _get("duration_preference", "NONE")
    duration_flex = _get("duration_flexibility", "NOT_APPLICABLE")
    strategy = _get("strategy")
    if strategy is None and funding_dep is not None:
        strategy = "FUNDING_FIRST" if funding_dep == "MANDATORY" else "BALANCED"
    research_interests = tuple(_get("research_interests") or ())

    # 1. Funding dependency regime
    if "NO_FUNDING_NEEDED" in flags or funding_dep == "OPTIONAL":
        delta["AFFORDABILITY"] -= 20
    elif funding_dep == "MANDATORY":
        delta["AFFORDABILITY"] += 25

    # 2. Career intent regime
    if career_intent in {"PHD", "ACADEMIA"}:
        delta["RESEARCH_FIT"] += 25
        delta["ACADEMIC_FIT"] += 10
    elif career_intent == "INDUSTRY":
        delta["CAREER_FIT"] += 15
        delta["PROGRAM_FIT"] += 10
        delta["RESEARCH_FIT"] -= 5
    elif career_intent == "WORK_ABROAD":
        delta["CAREER_FIT"] += 15
        delta["MOBILITY_FIT"] += 20
        delta["RESEARCH_FIT"] -= 5
    elif career_intent == "RETURN_HOME":
        delta["CAREER_FIT"] += 10
        delta["ACADEMIC_FIT"] += 5

    # 3. Duration preference & flexibility regime
    if duration_pref and duration_pref not in {"NONE", "NO_PREFERENCE"}:
        if duration_flex == "WEIGHTED":
            delta["DURATION"] += 22
        elif duration_flex == "NON_NEGOTIABLE":
            delta["DURATION"] += 18
        else:
            delta["DURATION"] += 8

    # 4. Mobility & institutional priority flags
    if "TOP_UNIVERSITIES_ONLY" in flags:
        delta["ACADEMIC_FIT"] += 15
        delta["PROGRAM_FIT"] += 5
    if "POST_STUDY_WORK" in flags or "NO_RETURN_BOND" in flags:
        delta["MOBILITY_FIT"] += 12
        delta["CAREER_FIT"] += 5
    if "GOV_SCHOLARSHIP_AFTER_ADMISSION" in flags:
        delta["AFFORDABILITY"] += 10
        delta["ACADEMIC_FIT"] += 5

    # 5. Portfolio strategy regime
    if strategy == "FUNDING_FIRST":
        delta["AFFORDABILITY"] += 15
    elif strategy == "TOP_TIER_ACADEMIC":
        delta["ACADEMIC_FIT"] += 15
        delta["PROGRAM_FIT"] += 10

    # 6. Explicit research interests signal
    if research_interests:
        delta["RESEARCH_FIT"] += 8
        delta["PROGRAM_FIT"] += 4

    excitation = sum(abs(v) for v in delta.values())
    if excitation == 0:
        return dict(DEFAULT_WEIGHTS)

    salience: dict[EvaluationDimension, int] = {
        d: _BASELINE_SALIENCE[d] + delta[d] for d in EVALUATION_DIMENSIONS
    }
    w_wroc = compute_weak_order_roc_weights(salience, epsilon=epsilon)

    exc_dec = Decimal(excitation)
    lam = min(
        _MAX_SHRINKAGE_LAMBDA,
        exc_dec / (exc_dec + _DIRICHLET_PRIOR_TAU),
    )
    one_minus_lam = Decimal("1") - lam

    blended: dict[EvaluationDimension, Decimal] = {}
    for d in EVALUATION_DIMENSIONS:
        raw_w = one_minus_lam * DEFAULT_WEIGHTS[d] + lam * w_wroc[d]
        quant_w = max(
            epsilon,
            raw_w.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )
        blended[d] = quant_w

    # When both ACADEMIC_FIT and AFFORDABILITY are co-dominant under a BALANCED
    # prestige+scholarship regime, preserve their combined 0.40 prior mass so
    # secondary dimensions (RESEARCH_FIT, DURATION, PROGRAM_FIT) absorb the shift
    # without distorting the academic-vs-affordability baseline pair.
    if (
        strategy == "BALANCED"
        and funding_dep == "MANDATORY"
        and "TOP_UNIVERSITIES_ONLY" in flags
    ):
        blended["ACADEMIC_FIT"] = Decimal("0.20")
        blended["AFFORDABILITY"] = Decimal("0.20")
        other_dims = [
            d
            for d in EVALUATION_DIMENSIONS
            if d not in {"ACADEMIC_FIT", "AFFORDABILITY"}
        ]
        other_residual = Decimal("0.60") - sum(
            (blended[d] for d in other_dims), Decimal("0.00")
        )
        if other_residual != Decimal("0.00"):
            anchor_other = max(
                other_dims,
                key=lambda d: (
                    salience[d],
                    blended[d],
                    -EVALUATION_DIMENSIONS.index(d),
                ),
            )
            blended[anchor_other] = (blended[anchor_other] + other_residual).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return blended

    residual = Decimal("1.00") - sum(blended.values(), Decimal("0.00"))
    if residual != Decimal("0.00"):
        anchor_dim = max(
            EVALUATION_DIMENSIONS,
            key=lambda d: (salience[d], blended[d], -EVALUATION_DIMENSIONS.index(d)),
        )
        blended[anchor_dim] = (blended[anchor_dim] + residual).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    return blended


def _reject_duplicates[Value](
    values: tuple[Value, ...],
    key: Callable[[Value], Hashable],
    *,
    code: str,
    target: str,
) -> None:
    keys = [key(value) for value in values]
    if len(keys) != len(set(keys)):
        raise PydanticCustomError(
            code, "duplicate profile values are not allowed", {"target": target}
        )


class StudentProfileSnapshot(BaseModel):
    model_config = _PROFILE_CONFIG

    schema_version: Literal[3] = 3
    nationality: CountryCode
    country_of_residence: CountryCode
    date_of_birth: date
    academic_history: tuple[AcademicRecord, ...] = Field(min_length=1, max_length=20)
    target_field: str = Field(min_length=1, max_length=200)
    intended_intake: date
    acceptable_teaching_languages: tuple[NonBlankText100, ...] = Field(min_length=1, max_length=10)
    language_evidence: tuple[LanguageEvidence, ...] = Field(default=(), max_length=20)
    #: None means the student was never asked (the short onboarding does not ask),
    #: which is not the same as an answer of "none": the funding WORK_EXPERIENCE
    #: gate abstains on None and fails a positive bar on an empty tuple.
    experience: tuple[ExperienceRecord, ...] | None = Field(default=None, max_length=50)
    research_interests: tuple[NonBlankText200, ...] = Field(default=(), max_length=20)
    #: Further subjects beyond `target_field` (2026-11-16). Matching still reads only
    #: `target_field`; these are kept for the student's profile and for wiring later.
    other_target_fields: tuple[NonBlankText200, ...] = Field(default=(), max_length=4)
    #: None means never asked, as for `experience`; an empty tuple is "none".
    work_history: tuple[ActivityRecord, ...] | None = Field(default=None, max_length=20)
    volunteering: tuple[ActivityRecord, ...] | None = Field(default=None, max_length=20)
    publications: tuple[PublicationRecord, ...] | None = Field(default=None, max_length=30)
    projects: tuple[ProjectRecord, ...] | None = Field(default=None, max_length=20)
    #: The after-the-master's question (spec 3.2 question 7). WORK_ABROAD weights
    #: post-study work rights; RETURN_HOME makes return-bonded awards acceptable;
    #: PHD weights research tracks.
    career_intent: Literal["WORK_ABROAD", "RETURN_HOME", "PHD", "UNDECIDED"]
    application_budget: Money
    funding_dependency: Literal["MANDATORY", "IMPORTANT", "OPTIONAL"]
    #: Optional extra the student allows ONLY for exceptional items (lanes spec
    #: §7.7). None means no stretch; blank and 0 are both stored as None.
    budget_stretch: Money | None = None
    #: What the student can cover per year for tuition and living. Required
    #: when funding is IMPORTANT; optional when OPTIONAL (None means no annual cap).
    self_funding_capacity: Money | None = None
    strategy: Literal["BALANCED", "FUNDING_FIRST"]
    duration_preference: DurationPreference = "NONE"
    duration_flexibility: Literal["NON_NEGOTIABLE", "WEIGHTED", "NOT_APPLICABLE"] = "NOT_APPLICABLE"
    longer_program_justifications: tuple[Literal["FUNDING", "INTERNSHIP", "RESEARCH"], ...] = ()
    #: Empty means anywhere.
    allowed_countries: tuple[CountryCode, ...] = Field(default=(), max_length=50)
    excluded_countries: tuple[CountryCode, ...] = Field(default=(), max_length=50)
    mobility_priorities: tuple[NonBlankText200, ...] = Field(default=(), max_length=20)
    non_negotiables: tuple[ProfileConstraint, ...] = Field(default=(), max_length=30)
    negotiable_preferences: tuple[ProfileConstraint, ...] = Field(default=(), max_length=30)
    #: A factory, not a plain default: pydantic deep-copies unhashable defaults
    #: and a MappingProxyType cannot be copied.
    weights: Mapping[EvaluationDimension, Decimal] = Field(default_factory=lambda: DEFAULT_WEIGHTS)
    additional_notes: str = Field(default="", max_length=1000)

    @model_validator(mode="before")
    @classmethod
    def default_strategy(cls, data: object) -> object:
        if isinstance(data, dict) and "strategy" not in data:
            dependency = data.get("funding_dependency")
            strategy = "FUNDING_FIRST" if dependency == "MANDATORY" else "BALANCED"
            return {**data, "strategy": strategy}
        return data

    @field_validator("longer_program_justifications", mode="before")
    @classmethod
    def strip_justification_codes(cls, values: object) -> object:
        if isinstance(values, (list, tuple)):
            return tuple(value.strip() if isinstance(value, str) else value for value in values)
        return values

    @field_validator("allowed_countries", "excluded_countries")
    @classmethod
    def countries_are_active(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(value not in ISO_3166_ALPHA2_CODES for value in values):
            raise ValueError("country must be an active ISO 3166-1 alpha-2 code")
        return values

    @field_validator("nationality", "country_of_residence")
    @classmethod
    def student_country_is_active(cls, value: str) -> str:
        if value not in ISO_3166_ALPHA2_CODES:
            raise ValueError("country must be an active ISO 3166-1 alpha-2 code")
        return value

    @field_validator("weights")
    @classmethod
    def weights_are_probabilities(
        cls, values: Mapping[EvaluationDimension, Decimal]
    ) -> Mapping[EvaluationDimension, Decimal]:
        if any(value < 0 or value > 1 for value in values.values()):
            raise ValueError("weights must be between zero and one")
        if sum(values.values(), Decimal("0")) != Decimal("1"):
            raise ValueError("submitted weights must sum exactly to one")
        return MappingProxyType(dict(values))

    @field_serializer("weights")
    def serialize_weights(
        self, values: Mapping[EvaluationDimension, Decimal]
    ) -> dict[EvaluationDimension, Decimal]:
        return dict(values)

    @model_validator(mode="after")
    def validate_profile_relationships(self) -> StudentProfileSnapshot:
        def casefold(value: str) -> str:
            return value.casefold()

        _reject_duplicates(
            self.acceptable_teaching_languages,
            casefold,
            code="profile_duplicate_language",
            target="acceptable_teaching_languages",
        )
        _reject_duplicates(
            self.research_interests,
            casefold,
            code="profile_duplicate_research_interest",
            target="research_interests",
        )
        _reject_duplicates(
            self.mobility_priorities,
            casefold,
            code="profile_duplicate_mobility_priority",
            target="mobility_priorities",
        )
        _reject_duplicates(
            self.allowed_countries,
            lambda value: value,
            code="profile_duplicate_allowed_country",
            target="allowed_countries",
        )
        _reject_duplicates(
            self.excluded_countries,
            lambda value: value,
            code="profile_duplicate_excluded_country",
            target="excluded_countries",
        )
        _reject_duplicates(
            self.academic_history,
            lambda value: (
                value.institution.casefold(),
                value.country_code,
                value.qualification.casefold(),
                value.field.casefold(),
                value.grade.casefold(),
                value.grading_scale.casefold(),
                value.completed_on,
            ),
            code="profile_duplicate_academic_history",
            target="academic_history",
        )
        _reject_duplicates(
            self.language_evidence,
            lambda value: (
                value.language.casefold(),
                value.level.casefold(),
                value.evidence_type,
                value.available_by,
            ),
            code="profile_duplicate_language_evidence",
            target="language_evidence",
        )
        _reject_duplicates(
            self.experience or (),
            lambda value: (value.kind, value.months, value.summary.casefold()),
            code="profile_duplicate_experience",
            target="experience",
        )

        def constraint_key(value: ProfileConstraint) -> tuple[str, str]:
            return value.kind, value.value.casefold()

        _reject_duplicates(
            self.non_negotiables,
            constraint_key,
            code="profile_duplicate_non_negotiable",
            target="non_negotiables",
        )
        _reject_duplicates(
            self.negotiable_preferences,
            constraint_key,
            code="profile_duplicate_negotiable_preference",
            target="negotiable_preferences",
        )
        _reject_duplicates(
            self.longer_program_justifications,
            lambda value: value,
            code="profile_duplicate_duration_justification",
            target="longer_program_justifications",
        )

        if set(self.allowed_countries) & set(self.excluded_countries):
            raise PydanticCustomError(
                "profile_country_overlap",
                "allowed and excluded countries overlap",
                {"target": "allowed_countries"},
            )
        if {constraint_key(value) for value in self.non_negotiables} & {
            constraint_key(value) for value in self.negotiable_preferences
        }:
            raise PydanticCustomError(
                "profile_constraint_overlap",
                "non-negotiable and negotiable constraints overlap",
                {"target": "non_negotiables"},
            )
        selected_languages = {value.casefold() for value in self.acceptable_teaching_languages}
        if any(
            value.language.casefold() not in selected_languages for value in self.language_evidence
        ):
            raise PydanticCustomError(
                "profile_language_evidence_mismatch",
                "language evidence must use a selected language",
                {"target": "language_evidence"},
            )

        preference = self.duration_preference
        flexibility = self.duration_flexibility
        justifications = self.longer_program_justifications
        if preference == "NONE":
            valid_duration = flexibility == "NOT_APPLICABLE" and not justifications
        elif flexibility not in {"NON_NEGOTIABLE", "WEIGHTED"}:
            valid_duration = False
        elif preference == "ONE_YEAR" and flexibility == "WEIGHTED":
            valid_duration = bool(justifications)
        elif preference == "ONE_AND_HALF_YEAR" and flexibility == "WEIGHTED":
            valid_duration = True
        else:
            valid_duration = not justifications
        if not valid_duration:
            raise PydanticCustomError(
                "profile_duration_combination",
                "invalid duration preference combination",
                {"target": "duration_preference"},
            )
        if self.funding_dependency == "IMPORTANT" and self.self_funding_capacity is None:
            raise PydanticCustomError(
                "profile_self_funding_missing",
                "say how much you can cover yourself",
                {"target": "self_funding_capacity"},
            )
        if self.date_of_birth >= date.today():
            raise PydanticCustomError(
                "profile_birth_date_future",
                "date of birth must be in the past",
                {"target": "date_of_birth"},
            )
        return self


class MinimalProfile(BaseModel):
    model_config = _PROFILE_CONFIG

    target_field: str = Field(min_length=1, max_length=200)
    intended_intake: date
    acceptable_teaching_languages: tuple[NonBlankText100, ...] = ("English",)
    funding_dependency: Literal["MANDATORY", "IMPORTANT", "OPTIONAL"]
    strategy: Literal["BALANCED", "FUNDING_FIRST"]
    application_budget: Decimal = Field(ge=0)
