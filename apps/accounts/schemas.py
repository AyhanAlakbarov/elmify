from collections.abc import Callable, Hashable, Mapping
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
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
    """

    model_config = _PROFILE_CONFIG

    title: str = Field(min_length=1, max_length=200)
    ects: Decimal | None = Field(default=None, ge=0, le=100, max_digits=6, decimal_places=2)
    grade: str | None = Field(default=None, max_length=50)
    in_progress: bool = False


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


class ProfileConstraint(BaseModel):
    model_config = _PROFILE_CONFIG

    kind: Literal["DURATION", "LOCATION", "LANGUAGE", "FIELD", "OTHER"]
    value: str = Field(min_length=1, max_length=200)


EvaluationDimension = Literal[
    "ACADEMIC_FIT",
    "PROGRAM_FIT",
    "CAREER_FIT",
    "AFFORDABILITY",
    "DURATION",
    "MOBILITY_FIT",
    "RESEARCH_FIT",
]

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
    #: The after-the-master's question (spec 3.2 question 7). WORK_ABROAD weights
    #: post-study work rights; RETURN_HOME makes return-bonded awards acceptable;
    #: PHD weights research tracks.
    career_intent: Literal["WORK_ABROAD", "RETURN_HOME", "PHD", "UNDECIDED"]
    application_budget: Money
    funding_dependency: Literal["MANDATORY", "IMPORTANT", "OPTIONAL"]
    #: What the student can cover per year for tuition and living. Required
    #: unless funding is MANDATORY (see validate_profile_relationships).
    self_funding_capacity: Money | None = None
    strategy: Literal["BALANCED", "FUNDING_FIRST"]
    duration_preference: Literal["ONE_YEAR", "TWO_YEAR", "NONE"] = "NONE"
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
        else:
            valid_duration = not justifications
        if not valid_duration:
            raise PydanticCustomError(
                "profile_duration_combination",
                "invalid duration preference combination",
                {"target": "duration_preference"},
            )
        if self.funding_dependency != "MANDATORY" and self.self_funding_capacity is None:
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
