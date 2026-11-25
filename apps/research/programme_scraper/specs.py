"""Data contracts and question sets for the programme scraper."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from apps.research.candidates import Candidates, Line
from apps.research.card_engine import (
    Decision,
    Question,
    Quote,
    Section,
    yes_no,
)

ScrapeStage = Literal["gate_and_money", "deep_documents", "full"]


@dataclass(frozen=True)
class ProgrammeSublinks:
    """Up to one top-scoring same-domain sub-page URL per missing information slot."""

    tuition_and_fees: str = ""
    admissions_and_eligibility: str = ""
    documents_and_checklist: str = ""
    scholarships_and_funding: str = ""

    def as_tuple(self, *, stage: ScrapeStage = "full") -> tuple[str, ...]:
        ordered = [
            self.tuition_and_fees,
            self.admissions_and_eligibility,
            self.scholarships_and_funding,
        ]
        if stage in ("deep_documents", "full"):
            ordered.append(self.documents_and_checklist)
        seen: list[str] = []
        for u in ordered:
            if u and u not in seen:
                seen.append(u)
        return tuple(seen)


@dataclass(frozen=True)
class CostComponentSpec:
    kind: Literal["TUITION", "APPLICATION_FEE"]
    amount: Decimal
    currency: str
    period: str
    audience: Literal["INTERNATIONAL", "EU_DOMESTIC", "ALL"]
    quote: Quote
    source_url: str
    from_structured: bool = False


@dataclass(frozen=True)
class EligibilitySpec:
    kind: Literal["LANGUAGE", "GRADE", "ECTS", "DEADLINE", "AGE"]
    label: str
    value: str
    quote: Quote
    source_url: str
    audience: Literal["INTERNATIONAL", "EU_DOMESTIC", "ALL"] = "ALL"


@dataclass(frozen=True)
class DocumentStatementSpec:
    kind: Literal["DOCUMENT", "FORMAT", "COMPETENCY", "LANGUAGE", "OTHER"]
    requirement: Literal["REQUIRED", "DESIRED"]
    label: str
    text: str
    quote: Quote
    source_url: str


@dataclass(frozen=True)
class InstitutionBaseProfile:
    """Reusable institution-wide defaults extracted once per university domain."""

    domain: str
    tuition_by_category: Mapping[str, CostComponentSpec] = field(default_factory=dict)
    default_tuition: CostComponentSpec | None = None
    application_fee: CostComponentSpec | None = None
    language_requirements: tuple[EligibilitySpec, ...] = ()
    default_deadline: EligibilitySpec | None = None
    document_statements: tuple[DocumentStatementSpec, ...] = ()
    base_lines: tuple[Line, ...] = ()
    base_line_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProgrammeBundle:
    """Merged multi-page `Section` and per-line `source_url` provenance map."""

    section: Section
    line_sources: tuple[str, ...]
    page_urls: tuple[str, ...]


@dataclass(frozen=True)
class ProgrammeScrapeResult:
    """Complete structured output from Tier 0 AST + Tier 1/2 Reader refinement."""

    duration_months: int | None
    teaching_languages: tuple[str, ...]
    costs: tuple[CostComponentSpec, ...]
    eligibility: tuple[EligibilitySpec, ...]
    statements: tuple[DocumentStatementSpec, ...]
    cv_format: str = "any"
    cv_format_source_url: str = ""
    letter_required: str = "unknown"
    cv_constraints: tuple[dict[str, object], ...] = ()
    cv_directives: tuple[dict[str, object], ...] = ()
    file_rules: tuple[dict[str, object], ...] = ()
    referee_requirements: tuple[dict[str, object], ...] = ()
    portfolio_led: bool = False
    fee_category_ref: str = ""
    unresolved_slots: frozenset[str] = frozenset()
    high_risk_flags: frozenset[str] = frozenset()
    decisions: tuple[Decision, ...] = ()
    cost_usd: float = 0.0


@dataclass
class ProgrammeQuestionSet:
    """Tier 1 closed question set asked only for slots that Tier 0 marks unresolved or high-risk."""

    unresolved_slots: frozenset[str]
    high_risk_flags: frozenset[str]
    name: str = "programme-facts"
    version: str = "v1"
    criteria: str = (
        "Answer from the section only. Prefer figures that apply to international / non-EU "
        "Master's applicants when the page states separate tracks."
    )

    def proposals(self, section: Section) -> Sequence[Question]:
        return ()

    def questions(
        self,
        section: Section,
        candidates: Candidates,
        proposed: Mapping[str, tuple[Quote, ...]],
    ) -> Sequence[Question]:
        qs: list[Question] = []
        if "tuition" in self.unresolved_slots and candidates.amounts:
            amt_keys = tuple(candidates.amounts.keys())
            qs.append(
                Question(
                    id="tuition_amount",
                    text=(
                        "Which candidate amount states the tuition fee for international / "
                        "non-EU Master's students?"
                    ),
                    options=(*amt_keys, "not_stated"),
                    criteria=(
                        "Pick the candidate key (m1, m2, ...) for international/non-EU tuition, "
                        "or general tuition if unsplit. Do not pick an application fee or stipend."
                    ),
                )
            )
            qs.append(
                Question(
                    id="tuition_period",
                    text="What period does that tuition fee cover?",
                    options=(
                        "ANNUAL",
                        "SEMESTER",
                        "TRIMESTER",
                        "QUARTER",
                        "TERM",
                        "PER_ECTS",
                        "PER_CREDIT",
                        "FULL_PROGRAM",
                        "MONTHLY",
                        "not_stated",
                    ),
                )
            )
        if "conditional_free_tuition" in self.high_risk_flags:
            qs.append(
                yes_no(
                    "tuition_free_all_internationals",
                    "Is tuition waived or free for ALL international non-EU students without "
                    "requiring a partner university agreement or selective scholarship?",
                    "yes: every admitted non-EU student pays zero tuition. no: only EU/EEA, "
                    "partner-university exchange students, or selective winners are exempt.",
                )
            )
        if (
            "application_fee" in self.unresolved_slots
            or "ambiguous_application_fee" in self.high_risk_flags
        ) and candidates.amounts:
            amt_keys = tuple(candidates.amounts.keys())
            qs.append(
                Question(
                    id="application_fee_amount",
                    text=(
                        "Which candidate amount states the one-off application or processing "
                        "fee for international / non-EU Master's applicants?"
                    ),
                    options=(*amt_keys, "not_stated"),
                    criteria=(
                        "Pick the candidate key (m1, m2, ...) for the international/non-EU "
                        "application fee, or general application fee if unsplit. Do not pick "
                        "tuition or a stipend."
                    ),
                )
            )
        if (
            "deadline" in self.unresolved_slots
            or "ambiguous_deadline" in self.high_risk_flags
        ) and candidates.dates:
            date_keys = tuple(candidates.dates.keys())
            qs.append(
                Question(
                    id="application_deadline_date",
                    text=(
                        "Which candidate date states the application deadline for "
                        "international / non-EU Master's applicants?"
                    ),
                    options=(*date_keys, "not_stated"),
                    criteria=(
                        "Pick the candidate key (d1, d2, ...) for the international/non-EU "
                        "application deadline, or the general deadline if unsplit."
                    ),
                )
            )
        if "min_gpa" in self.unresolved_slots or "ambiguous_min_gpa" in self.high_risk_flags:
            grade_keys = tuple(
                k for k, r in candidates.requirements.items() if r.value.kind == "grade"
            ) or tuple(candidates.requirements.keys())
            if grade_keys:
                qs.append(
                    Question(
                        id="minimum_gpa_bar",
                        text=(
                            "Which candidate requirement states the mandatory minimum GPA or "
                            "prior-degree grade threshold for admission?"
                        ),
                        options=(*grade_keys, "not_stated"),
                        criteria=(
                            "Pick the candidate requirement key (r1, r2, ...) stating the "
                            "minimum required grade/GPA for international Master's admission."
                        ),
                    )
                )
        if "ielts_bar" in self.unresolved_slots or "ambiguous_ielts_bar" in self.high_risk_flags:
            lang_keys = tuple(
                k
                for k, r in candidates.requirements.items()
                if r.value.kind in ("language_test", "cefr")
            ) or tuple(candidates.requirements.keys())
            if lang_keys:
                qs.append(
                    Question(
                        id="minimum_language_bar",
                        text=(
                            "Which candidate requirement states the minimum English / teaching "
                            "language proficiency score (IELTS, TOEFL, or CEFR) for admission?"
                        ),
                        options=(*lang_keys, "not_stated"),
                        criteria=(
                            "Pick the candidate requirement key (r1, r2, ...) stating the "
                            "mandatory minimum language score for this Master's track."
                        ),
                    )
                )
        if (
            "scholarship_suspended" in self.high_risk_flags
            or "scholarship_suspended" in self.unresolved_slots
        ):
            qs.append(
                yes_no(
                    "scholarship_intake_suspended",
                    "Is the scholarship or programme intake suspended, paused, or closed "
                    "for the upcoming academic cycle?",
                    "yes: intake or scholarship is suspended/paused/not offered. "
                    "no: intake is active and accepting applications.",
                )
            )
        return tuple(qs)


__all__ = [
    "CostComponentSpec",
    "DocumentStatementSpec",
    "EligibilitySpec",
    "InstitutionBaseProfile",
    "ProgrammeBundle",
    "ProgrammeQuestionSet",
    "ProgrammeScrapeResult",
    "ProgrammeSublinks",
    "Quote",
    "ScrapeStage",
]
