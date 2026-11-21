"""Cold-start -> Empirical Bayes -> ML admission & scholarship probability estimator.

Computes an honest, calibrated percentage chance (`1..95%` for competitive routes, `100%`
for `AUTOMATIC_ON_ADMISSION` benefits) from four layers:
1. Published / regime base selectivity priors ($p_0$).
2. Student academic, coursework, language, and experience margins above minimum bars.
3. Similarity to PII-free 3rd-party LinkedIn winner cohorts (`WinnerCohortProfile`).
4. Empirical Bayes Beta-Binomial shrinkage (1..49 outcomes) and logistic calibration (50+
   outcomes) over anonymised `OutcomeCalibrationRecord` rows.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from django.db.models import Q

from apps.accounts.schemas import AcademicRecord, StudentProfileSnapshot
from apps.funding.eligibility import _normalize_scale, _split_scale
from apps.funding.evaluation import ApplicantConditionFact, AwardCandidateFacts, CandidateFacts
from apps.funding.grouping import funds
from apps.funding.models import (
    FundingOpportunity,
    OutcomeCalibrationRecord,
    Program,
    ProgramStatement,
    RecommendationCandidate,
)
from apps.funding.transcript_eligibility import (
    evaluate_program_statement,
    parse_scholarship_status_statement,
    ungraduated_degree_completion,
)
from apps.mailbox.models import MailSignal
from apps.portals.models import Application
from apps.research.models import WinnerCohortProfile
from apps.tenancy.context import current_tenant_id, tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency

_RULE_BASED_COUNTRIES = frozenset({"DE", "AT", "CH", "IT", "BE", "NL"})
_SELECTIVE_COHORT_COUNTRIES = frozenset(
    {"FR", "SE", "FI", "NO", "DK", "IE", "GB", "SG", "JP", "KR"}
)

_SELECTIVE_STATEMENT_RE = re.compile(
    r"\b(?:highly\s+selective|competitive\s+admission|limited\s+(?:number\s+of\s+)?places"
    r"|numerus\s+clausus|entrance\s+exam(?:ination)?|selection\s+interview"
    r"|gre\b|gmat\b|first[- ]class\s+honours|top\s+\d+\s*%)\b",
    re.IGNORECASE,
)


def _stmt_text(s: ProgramStatement | tuple[str, str]) -> str:
    if isinstance(s, tuple):
        return str(s[1] if len(s) > 1 else "")
    return str(getattr(s, "text", "") or "")


def _stmt_kind(s: ProgramStatement | tuple[str, str]) -> str:
    if isinstance(s, tuple):
        return str(s[0] if len(s) > 0 else "")
    return str(getattr(s, "kind", "") or "")


_HIGH_GPA_THRESHOLDS: Mapping[str, float] = {
    "gpa 4.0": 3.3,
    "5.0": 4.0,
    "10.0": 8.0,
    "20.0": 15.0,
    "30.0": 26.0,
    "100": 80.0,
    "110": 100.0,
}


def _is_high_gpa_bar(req_gpa: tuple[float, str] | None) -> bool:
    if req_gpa is None:
        return False
    val, scale = req_gpa
    if scale == "german 1-5":
        return val <= 2.0
    threshold = _HIGH_GPA_THRESHOLDS.get(scale)
    return threshold is not None and val >= threshold


_APPROX_EUR_PER_UNIT: Mapping[str, Decimal] = {
    "EUR": Decimal("1.00"),
    "GBP": Decimal("1.17"),
    "CHF": Decimal("1.05"),
    "USD": Decimal("0.92"),
    "CAD": Decimal("0.68"),
    "AUD": Decimal("0.60"),
    "NZD": Decimal("0.55"),
    "SGD": Decimal("0.68"),
    "BND": Decimal("0.68"),
    "DKK": Decimal("0.134"),
    "SEK": Decimal("0.088"),
    "NOK": Decimal("0.086"),
    "PLN": Decimal("0.23"),
    "CZK": Decimal("0.040"),
    "RON": Decimal("0.20"),
    "HUF": Decimal("0.0025"),
    "ISK": Decimal("0.0067"),
    "TRY": Decimal("0.027"),
    "AZN": Decimal("0.54"),
    "GEL": Decimal("0.34"),
    "KZT": Decimal("0.0019"),
    "UZS": Decimal("0.000072"),
    "JPY": Decimal("0.0060"),
    "KRW": Decimal("0.00068"),
    "CNY": Decimal("0.13"),
    "HKD": Decimal("0.12"),
    "TWD": Decimal("0.029"),
    "MYR": Decimal("0.21"),
    "THB": Decimal("0.027"),
    "IDR": Decimal("0.000058"),
    "VND": Decimal("0.000037"),
    "INR": Decimal("0.011"),
    "PKR": Decimal("0.0033"),
    "AED": Decimal("0.25"),
    "SAR": Decimal("0.25"),
    "QAR": Decimal("0.25"),
    "KWD": Decimal("3.00"),
    "BHD": Decimal("2.44"),
    "OMR": Decimal("2.39"),
}


def _is_high_tuition_amount(amount: Decimal, currency: str) -> bool:
    curr = (currency or "EUR").strip().upper()
    eur_factor = _APPROX_EUR_PER_UNIT.get(curr)
    if eur_factor is None:
        return False
    return (amount * eur_factor) >= Decimal("10000")


def is_selective_candidate(
    candidate: CandidateFacts,
    *,
    statements: Sequence[ProgramStatement | tuple[str, str]] = (),
    winner_cohort: WinnerCohortProfile | None = None,
) -> bool:
    """Determine dynamically whether a programme candidate is selective based on its
    funding competition, admission bars, competency statements, and cohort profile."""
    if any(
        b.accessibility in ("COMPETITIVE", "CAPACITY_LIMITED")
        for b in candidate.benefits
    ):
        return True
    req_gpa = _extract_required_gpa_bar(candidate.applicant_conditions, statements)
    if _is_high_gpa_bar(req_gpa):
        return True
    req_cefr = _extract_required_cefr(candidate.applicant_conditions, statements)
    if req_cefr in ("C1", "C2"):
        return True
    if any(_SELECTIVE_STATEMENT_RE.search(_stmt_text(s)) for s in statements):
        return True
    if (
        winner_cohort is not None
        and winner_cohort.research_signal_rate is not None
        and float(winner_cohort.research_signal_rate) >= 0.40
    ):
        return True
    acad = candidate.dimension_scores.get("ACADEMIC_FIT", Decimal("0"))
    res = candidate.dimension_scores.get("RESEARCH_FIT", Decimal("0"))
    has_high_tuition = any(
        c.kind == "TUITION" and _is_high_tuition_amount(c.amount, c.currency)
        for c in candidate.cost_components
    )
    return bool(acad >= Decimal("90") and res >= Decimal("90") and has_high_tuition)


_POST_ADMISSION_CONDITION_RE = re.compile(
    r"\b(?:unconditional\s+(?:offer|admission)|admission\s+(?:offer|letter)"
    r"|offer\s+of\s+admission|letter\s+of\s+acceptance|accepted\s+(?:to|at|by)\s+a\s+university"
    r"|university\s+admission\s+required\s+first|post[- ]admission)\b",
    re.IGNORECASE,
)

_POST_ADMISSION_GOV_SCHOLARSHIP_RE = re.compile(
    r"\b(?:post[- ]admission\s+(?:government\s+|state\s+|external\s+|national\s+)?scholarship"
    r"|admission[- ]contingent\s+(?:government\s+|state\s+)?scholarship"
    r"|home[- ]government\s+post[- ]admission\s+scholarship"
    r"|(?:state|government)\s+program(?:me)?\s+for\s+study\s+abroad"
    r"|d[öo]vl[əe]t\s+proqram[ıi]?)\b",
    re.IGNORECASE,
)

#: Positive correlation between university admission and winning an admission-contingent
#: post-admission scholarship where an unconditional admission offer from an eligible
#: foreign university is the primary hurdle.
POST_ADMISSION_GOV_CORRELATION: float = 0.75


def is_post_admission_gov_scholarship(
    name: str = "",
    holder_domain: str = "",
    country_code: str = "",
    home_country: str = "",
    *,
    applicant_conditions: Sequence[object] = (),
) -> bool:
    """Return True if the scholarship is dynamically identified as an admission-contingent
    (post-admission) home-government or external sponsorship scheme."""
    for cond in applicant_conditions:
        quote = str(getattr(cond, "quote", "") or "")
        rule_text = str(getattr(cond, "rule_text", "") or "")
        val = str(getattr(cond, "value", "") or "")
        if _POST_ADMISSION_CONDITION_RE.search(f"{quote} {rule_text} {val}"):
            return True
    if _POST_ADMISSION_GOV_SCHOLARSHIP_RE.search(name or ""):
        return True
    if (
        country_code
        and home_country
        and country_code.strip().upper() == home_country.strip().upper()
    ):
        return True
    return False


def post_admission_gov_conditional_pct(
    *,
    admit_chance_pct: int | None = None,
    candidate: CandidateFacts | None = None,
) -> int:
    """Dynamic conditional approval probability (%) for a post-admission scholarship
    once the student holds an admission offer, scaled by the selectivity of the offer."""
    if admit_chance_pct is not None:
        if admit_chance_pct <= 25:
            return 85
        if admit_chance_pct <= 55:
            return 75
        return 70
    if candidate is not None and is_selective_candidate(candidate):
        return 85
    return 75


_AWARD_FAMILY_BASE_PRIORS: Mapping[str, float] = {
    "GOVERNMENT_SCHOLARSHIP": 0.12,
    "MULTILATERAL": 0.08,
    "PRIVATE_FOUNDATION": 0.15,
    "AFFINITY_OR_DIASPORA": 0.22,
    "INDUSTRIAL_SPONSORSHIP": 0.18,
    "UNIVERSITY_WIDE": 0.20,
    "DEPARTMENT_OR_PROGRAM": 0.28,
    "TUITION_WAIVER": 0.30,
    "STIPEND_OR_ASSISTANTSHIP": 0.22,
    "RESEARCH_ECOSYSTEM_PATHWAY": 0.25,
    "RELOCATION_HOUSING_INSURANCE_TRAVEL": 0.35,
}

_DECIDED_OUTCOMES = frozenset(
    {
        Application.Outcome.ADMITTED,
        Application.Outcome.ADMITTED_CONDITIONAL,
        Application.Outcome.REJECTED,
    }
)
_WON_OUTCOMES = frozenset(
    {
        Application.Outcome.ADMITTED,
        Application.Outcome.ADMITTED_CONDITIONAL,
    }
)
_SEPARATE_AWARD_ROUTES = frozenset(
    {
        "STUDENT_APPLIES_SEPARATELY",
        "HOME_GOVERNMENT_NOMINATES",
        "AUTOMATIC_ON_ADMISSION",
    }
)

_FEATURE_KEYS = (
    "base_prior",
    "gpa_margin",
    "coursework_alignment",
    "language_margin",
    "experience_alignment",
    "winner_similarity",
)

_CEFR_RANK: Mapping[str, int] = {
    "A1": 0,
    "A2": 0,
    "B1": 1,
    "B2": 2,
    "C1": 3,
    "C2": 4,
}


@dataclass(frozen=True)
class ProbabilityEstimate:
    """Estimated admission or scholarship probability (`1..100`) and its calibration vector."""

    chance_pct: int
    features: dict[str, float]


def _logit(p: float) -> float:
    clamped = max(0.005, min(0.995, p))
    return math.log(clamped / (1.0 - clamped))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _clamp_competitive_pct(prob: float) -> int:
    return max(1, min(95, int(round(prob * 100.0))))


def _parse_float(raw: str) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", raw)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def _extract_required_gpa_bar(
    conditions: Sequence[ApplicantConditionFact],
    statements: Sequence[ProgramStatement | tuple[str, str]],
) -> tuple[float, str] | None:
    """Extract a stated minimum grade value and normalized scale from conditions or statements."""
    for cond in conditions:
        if cond.key == "PRIOR_DEGREE_GRADE" and cond.value:
            val_str, inline_scale = _split_scale(cond.value)
            val = _parse_float(val_str)
            scale = _normalize_scale(inline_scale)
            if val is not None and scale:
                return val, scale
    texts = [
        *(
            f"{getattr(c, 'value', '')} {getattr(c, 'rule_text', '')} "
            f"{getattr(c, 'description', '')}"
            for c in conditions
        ),
        *(_stmt_text(s) for s in statements),
    ]
    for txt in texts:
        m = re.search(
            r"(?:minimum|at least|gpa(?:\s+of)?)\s+(\d+(?:[.,]\d+)?)\s*"
            r"(?:/\s*(4\.0|5\.0|10(?:\.0)?|20(?:\.0)?|30(?:\.0)?|100|110)|%)",
            txt,
            re.IGNORECASE,
        )
        if m:
            val = float(m.group(1).replace(",", "."))
            raw_scale = m.group(2) or "100"
            scale = _normalize_scale(raw_scale)
            if scale:
                return val, scale
    return None


def _normalized_gpa_margin(
    records: Sequence[AcademicRecord],
    *,
    required_bar: tuple[float, str] | None = None,
) -> float:
    """Return a normalized GPA margin in `[-1.0, 1.0]` relative to `required_bar` or midpoint."""
    if not records:
        return 0.0
    scores: list[float] = []
    req_val, req_scale = required_bar if required_bar is not None else (None, "")
    for rec in records:
        val = _parse_float(rec.grade)
        if val is None:
            continue
        _, inline_scale = _split_scale(rec.grade)
        scale = _normalize_scale(rec.grading_scale or inline_scale)
        if scale == "german 1-5":
            bar = req_val if (req_val is not None and req_scale == scale) else 2.5
            span = max(0.4, bar - 1.0)
            scores.append(max(-1.0, min(1.0, (bar - val) / span)))
        else:
            bounds = {
                "gpa 4.0": (3.0, 4.0, 0.3),
                "5.0": (3.7, 5.0, 0.4),
                "10.0": (7.5, 10.0, 0.5),
                "20.0": (14.0, 20.0, 1.0),
                "30.0": (24.0, 30.0, 1.0),
                "100": (75.0, 100.0, 5.0),
                "110": (95.0, 110.0, 3.0),
            }.get(scale)
            if bounds is not None:
                default_bar, max_grade, min_span = bounds
                bar = req_val if (req_val is not None and req_scale == scale) else default_bar
                span = max(min_span, max_grade - bar)
                scores.append(max(-1.0, min(1.0, (val - bar) / span)))
    if not scores:
        return 0.0
    return round(max(scores), 4)


def _extract_required_cefr(
    conditions: Sequence[ApplicantConditionFact],
    statements: Sequence[ProgramStatement | tuple[str, str]],
) -> str:
    """Return the highest CEFR level (`B1..C2`) stated in conditions or statements, or `'B2'`."""
    best_rank = _CEFR_RANK["B2"]
    best_label = "B2"
    texts = [
        *(
            f"{getattr(c, 'value', '')} {getattr(c, 'rule_text', '')} "
            f"{getattr(c, 'description', '')}"
            for c in conditions
            if getattr(c, "key", "") == "LANGUAGE"
            or getattr(c, "condition_type", "") == "LANGUAGE"
        ),
        *(_stmt_text(s) for s in statements if _stmt_kind(s) == "LANGUAGE"),
    ]
    for txt in texts:
        for cefr, rank in _CEFR_RANK.items():
            if re.search(rf"\b{cefr}\b", txt, re.IGNORECASE) and rank > best_rank:
                best_rank = rank
                best_label = cefr
    return best_label


def _score_to_cefr_rank(lvl: str) -> float | None:
    """Map a CEFR string or test-specific numeric score in `lvl` to a CEFR rank (`1.0..4.0`)."""
    upper = lvl.upper()
    if "C2" in upper:
        return 4.0
    if "C1" in upper:
        return 3.0
    if "B2" in upper:
        return 2.0
    if "B1" in upper:
        return 1.0

    m = re.search(r"(\d+(?:\.\d+)?)", upper)
    if not m:
        return None
    score = float(m.group(1))

    if "TDN" in upper or "TESTDAF" in upper:
        if score >= 5.0:
            return 3.0
        if score >= 4.0:
            return 2.0
        if score >= 3.0:
            return 1.0
        return None

    if "DUOLINGO" in upper or "DET" in upper or (120 < score <= 160):
        if score >= 145:
            return 4.0
        if score >= 125:
            return 3.0
        if score >= 100:
            return 2.0
        if score >= 75:
            return 1.0
        return None

    if "PTE" in upper:
        if score >= 85:
            return 4.0
        if score >= 76:
            return 3.0
        if score >= 59:
            return 2.0
        if score >= 43:
            return 1.0
        return None

    if any(tok in upper for tok in ("CAMBRIDGE", "CAE", "CPE", "FCE")) or (160 < score <= 230):
        if score >= 200:
            return 4.0
        if score >= 180:
            return 3.0
        if score >= 160:
            return 2.0
        if score >= 140:
            return 1.0
        return None

    if 8.0 <= score <= 9.0 or 110 <= score <= 120:
        return 4.0
    if 7.0 <= score < 8.0 or 95 <= score < 110:
        return 3.0
    if 6.0 <= score < 7.0 or 72 <= score < 95:
        return 2.0
    if 5.0 <= score < 6.0 or 42 <= score < 72:
        return 1.0
    return None


def _language_margin(
    profile: StudentProfileSnapshot,
    *,
    required_cefr: str = "B2",
    today: date | None = None,
) -> float:
    """Return a language readiness margin in `[-0.35, 0.50]` relative to `required_cefr`."""
    req_rank = _CEFR_RANK.get(required_cefr.upper(), _CEFR_RANK["B2"])
    ref_date = today if today is not None else date.today()
    best_student_rank: float | None = None
    best_is_verified: bool = False
    for ev in profile.language_evidence:
        rank = _score_to_cefr_rank(ev.level)
        if rank is None:
            continue
        ev_type = str(getattr(ev, "evidence_type", "") or "").upper()
        avail = getattr(ev, "available_by", None)
        is_pending = (
            ev_type in ("ATTESTED", "OTHER")
            or (isinstance(avail, date) and avail > ref_date)
            or (
                ev_type == "DEGREE"
                and ungraduated_degree_completion(profile, ref_date) is not None
            )
        )
        is_verified = not is_pending
        if (
            best_student_rank is None
            or rank > best_student_rank
            or (rank == best_student_rank and is_verified and not best_is_verified)
        ):
            best_student_rank = rank
            best_is_verified = is_verified
    if best_student_rank is None:
        return 0.0
    diff = best_student_rank - float(req_rank)
    if diff >= 2.0:
        margin = 0.50
    elif diff >= 1.0:
        margin = 0.35
    elif diff >= 0.0:
        margin = 0.15
    else:
        return -0.25
    return round(margin * 0.5, 4) if not best_is_verified else margin


def _experience_alignment(
    profile: StudentProfileSnapshot,
    conditions: Sequence[ApplicantConditionFact] = (),
) -> float:
    """Compute research, work-experience, and leadership alignment in `[-0.4, 1.0]`."""
    experiences = profile.experience or ()
    has_research = any(
        exp.kind == "RESEARCH"
        or "publish" in exp.summary.casefold()
        or "journal" in exp.summary.casefold()
        for exp in experiences
    )
    has_leadership = any(
        exp.kind in ("LEADERSHIP", "VOLUNTEERING") for exp in experiences
    )
    work_months = sum(exp.months for exp in experiences if exp.kind == "WORK")
    total_months = sum(exp.months for exp in experiences)

    req_work_months = 0.0
    for cond in conditions:
        if (
            (cond.key == "WORK_EXPERIENCE" or cond.condition_type == "WORK_EXPERIENCE")
            and cond.comparable_value is not None
            and (cond.comparable_unit or "MONTHS") == "MONTHS"
        ):
            req_work_months = max(req_work_months, float(cond.comparable_value))

    score = 0.0
    if has_research:
        score += 0.45
    if has_leadership:
        score += 0.15
    if req_work_months > 0:
        if total_months >= req_work_months * 1.5:
            score += 0.40
        elif total_months >= req_work_months:
            score += 0.20
        else:
            score -= 0.35
    elif work_months >= 24 or total_months >= 24:
        score += 0.30
    elif work_months >= 12 or total_months >= 12:
        score += 0.15
    return round(max(-0.4, min(1.0, score)), 4)


def _winner_archetype_similarity(
    profile: StudentProfileSnapshot,
    cohort: WinnerCohortProfile | None,
) -> float:
    """Compute similarity in `[-1.0, 1.0]` between a student and a `WinnerCohortProfile`."""
    if cohort is None or cohort.sample_size < 2:
        return 0.0

    score = 0.0
    total_weight = 0.0

    # 1. Prior degree field overlap (weight 0.45)
    if cohort.prior_degree_fields:
        total_weight += 0.45
        student_fields = {
            rec.field.strip().casefold() for rec in profile.academic_history if rec.field.strip()
        }
        if profile.target_field.strip():
            student_fields.add(profile.target_field.strip().casefold())
        cohort_fields = {str(k).casefold(): int(v) for k, v in cohort.prior_degree_fields.items()}
        matched_count = 0
        for sf in student_fields:
            for cf, cnt in cohort_fields.items():
                if sf in cf or cf in sf:
                    matched_count = max(matched_count, cnt)
        if matched_count > 0:
            share = matched_count / max(1, cohort.sample_size)
            score += 0.45 * min(1.0, 0.4 + share * 1.2)
        else:
            score -= 0.45 * 0.6

    # 2. Origin country representation (weight 0.20)
    if cohort.origin_country_counts:
        total_weight += 0.20
        nat_count = int(cohort.origin_country_counts.get(profile.nationality, 0))
        if nat_count > 0:
            score += 0.20 * min(1.0, 0.5 + (nat_count / max(1, cohort.sample_size)) * 2.0)
        else:
            score -= 0.20 * 0.25

    # 3. Work experience quartile alignment (weight 0.20)
    if cohort.work_experience_months_median is not None:
        total_weight += 0.20
        student_months = sum(exp.months for exp in (profile.experience or ()))
        p25 = cohort.work_experience_months_p25 or 0
        med = cohort.work_experience_months_median
        if student_months >= med:
            score += 0.20 * 0.9
        elif student_months >= p25:
            score += 0.20 * 0.4
        elif med >= 12 and student_months == 0:
            score -= 0.20 * 0.6

    # 4. Research signal alignment (weight 0.15)
    if cohort.research_signal_rate is not None:
        total_weight += 0.15
        rate = float(cohort.research_signal_rate)
        has_research = any(
            exp.kind == "RESEARCH"
            or "publish" in exp.summary.casefold()
            or "journal" in exp.summary.casefold()
            for exp in (profile.experience or ())
        )
        if has_research and rate >= 0.25:
            score += 0.15 * 1.0
        elif not has_research and rate >= 0.60:
            score -= 0.15 * 0.7

    if total_weight <= 0.0:
        return 0.0
    return round(max(-1.0, min(1.0, score / total_weight)), 4)


def _row_weight(
    row: OutcomeCalibrationRecord,
    *,
    target_program_id: UUID | None = None,
    target_opportunity_id: UUID | None = None,
    student_origin_country: str = "",
    current_year: int | None = None,
) -> float:
    """Compute calibration weight combining source reliability, exactness, recency, and origin."""
    w = 0.75 if row.outcome_source == Application.OutcomeSource.PERSON else 1.0
    is_exact = (
        (target_program_id is not None and row.program_id == target_program_id)
        or (target_opportunity_id is not None and row.opportunity_id == target_opportunity_id)
        or (target_program_id is None and target_opportunity_id is None)
    )
    if not is_exact:
        w *= 0.25
    if current_year is not None and row.intake_year is not None:
        age = max(0, min(10, current_year - int(row.intake_year)))
        w *= 0.85**age
    if (
        student_origin_country
        and row.origin_country
        and row.origin_country.upper() == student_origin_country.upper()
    ):
        w *= 1.35
    return w


def _calibrate_with_outcomes(
    cold_prob: float,
    features: Mapping[str, float],
    calibration_rows: Sequence[OutcomeCalibrationRecord],
    *,
    target_program_id: UUID | None = None,
    target_opportunity_id: UUID | None = None,
    student_origin_country: str = "",
    current_year: int | None = None,
) -> float:
    """Apply Phase 2 Empirical Bayes (`< 50` exact rows) or Phase 3 logistic (`50+` exact rows)."""
    n = len(calibration_rows)
    if n == 0:
        return cold_prob

    row_weights = [
        _row_weight(
            r,
            target_program_id=target_program_id,
            target_opportunity_id=target_opportunity_id,
            student_origin_country=student_origin_country,
            current_year=current_year,
        )
        for r in calibration_rows
    ]
    weighted_n = sum(row_weights)
    weighted_wins = sum(w for r, w in zip(calibration_rows, row_weights, strict=False) if r.won)
    exact_count = sum(
        1
        for r in calibration_rows
        if (target_program_id is not None and r.program_id == target_program_id)
        or (target_opportunity_id is not None and r.opportunity_id == target_opportunity_id)
        or (target_program_id is None and target_opportunity_id is None)
    )

    # Phase 2: Beta-Binomial shrinkage centered on base_prior so delta_logit is applied once
    if exact_count < 50:
        base_prior = max(0.01, min(0.95, float(features.get("base_prior", cold_prob))))
        kappa = 10.0
        alpha_0 = base_prior * kappa
        beta_0 = (1.0 - base_prior) * kappa
        eb_base = (alpha_0 + weighted_wins) / (alpha_0 + beta_0 + weighted_n)
        delta_logit = _logit(cold_prob) - _logit(base_prior)
        return _sigmoid(_logit(eb_base) + delta_logit)

    # Phase 3: Calibrated logistic model fitted via weighted gradient steps on outcome records
    weights = {k: 0.0 for k in _FEATURE_KEYS}
    bias = _logit(max(0.05, min(0.95, weighted_wins / max(1.0, weighted_n))))
    lr = 0.25
    l2 = 0.05
    for _ in range(80):
        grad_b = 0.0
        grad_w = {k: 0.0 for k in _FEATURE_KEYS}
        for row, w in zip(calibration_rows, row_weights, strict=False):
            fv = row.feature_vector or {}
            z = bias + sum(weights[k] * float(fv.get(k, 0.0)) for k in _FEATURE_KEYS)
            pred = _sigmoid(z)
            err = w * (pred - (1.0 if row.won else 0.0))
            grad_b += err
            for k in _FEATURE_KEYS:
                grad_w[k] += err * float(fv.get(k, 0.0))
        bias -= lr * (grad_b / max(1.0, weighted_n))
        for k in _FEATURE_KEYS:
            weights[k] -= lr * ((grad_w[k] / max(1.0, weighted_n)) + l2 * weights[k])

    z_student = bias + sum(weights[k] * float(features.get(k, 0.0)) for k in _FEATURE_KEYS)
    ml_prob = _sigmoid(z_student)
    # Blend 80% calibrated logistic + 20% cold-start prior for stability
    return 0.80 * ml_prob + 0.20 * cold_prob


def estimate_program_admission_chance(
    program: Program,
    facts: CandidateFacts,
    profile: StudentProfileSnapshot,
    *,
    statements: Sequence[ProgramStatement] = (),
    winner_cohort: WinnerCohortProfile | None = None,
    calibration_rows: Sequence[OutcomeCalibrationRecord] = (),
    today: date | None = None,
) -> ProbabilityEstimate:
    """Estimate a student's admission probability (`1..95%`) for a recommended `Program`."""
    name_lower = program.name.casefold()
    if (
        program.provision_type == Program.ProvisionType.JOINT
        or "erasmus mundus" in name_lower
        or "emjm" in name_lower
    ):
        base_prior = 0.08
    elif is_selective_candidate(
        facts, statements=statements, winner_cohort=winner_cohort
    ):
        base_prior = 0.18
    elif program.country_code in _RULE_BASED_COUNTRIES:
        base_prior = 0.55
    elif program.country_code in _SELECTIVE_COHORT_COUNTRIES:
        base_prior = 0.30
    else:
        base_prior = 0.40

    stmt_evals = (
        tuple(
            evaluate_program_statement(s.text, profile, kind=s.kind)
            for s in statements
            if not (
                profile.funding_dependency == "OPTIONAL"
                and parse_scholarship_status_statement(s.text) is not None
            )
        )
        if statements
        else ()
    )
    if any(ev.outcome in ("FAILED", "BORDERLINE") for ev in stmt_evals):
        coursework_alignment = -1.0
    elif any(ev.outcome == "SATISFIED" for ev in stmt_evals):
        coursework_alignment = 1.0
    else:
        has_matching_course = any(
            course.title
            for rec in profile.academic_history
            for course in rec.courses
        )
        coursework_alignment = 0.4 if has_matching_course else 0.0

    req_gpa = _extract_required_gpa_bar(facts.applicant_conditions, statements)
    req_cefr = _extract_required_cefr(facts.applicant_conditions, statements)
    gpa_margin = _normalized_gpa_margin(profile.academic_history, required_bar=req_gpa)
    lang_margin = _language_margin(profile, required_cefr=req_cefr, today=today)
    exp_align = _experience_alignment(profile, facts.applicant_conditions)
    winner_sim = _winner_archetype_similarity(profile, winner_cohort)

    features: dict[str, float] = {
        "base_prior": round(base_prior, 4),
        "gpa_margin": gpa_margin,
        "coursework_alignment": coursework_alignment,
        "language_margin": lang_margin,
        "experience_alignment": exp_align,
        "winner_similarity": winner_sim,
    }

    log_odds = (
        _logit(base_prior)
        + 0.70 * gpa_margin
        + 0.65 * coursework_alignment
        + 0.35 * lang_margin
        + 0.25 * exp_align
        + 0.55 * winner_sim
    )
    cold_prob = _sigmoid(log_odds)
    ref_year = today.year if today is not None else date.today().year
    final_prob = _calibrate_with_outcomes(
        cold_prob,
        features,
        calibration_rows,
        target_program_id=program.id,
        student_origin_country=profile.nationality,
        current_year=ref_year,
    )
    return ProbabilityEstimate(
        chance_pct=_clamp_competitive_pct(final_prob),
        features=features,
    )


def estimate_scholarship_chance(
    award: FundingOpportunity,
    facts: AwardCandidateFacts,
    profile: StudentProfileSnapshot,
    *,
    winner_cohort: WinnerCohortProfile | None = None,
    calibration_rows: Sequence[OutcomeCalibrationRecord] = (),
    today: date | None = None,
) -> ProbabilityEstimate:
    """Estimate a student's scholarship win probability (`1..95%`, or `100%` if automatic)."""
    ref_year = today.year if today is not None else date.today().year
    route = (facts.route or award.route or "").upper()
    if route == "AUTOMATIC_ON_ADMISSION":
        return ProbabilityEstimate(
            chance_pct=100,
            features={
                "base_prior": 1.0,
                "gpa_margin": _normalized_gpa_margin(profile.academic_history),
                "coursework_alignment": 0.0,
                "language_margin": _language_margin(profile, today=today),
                "experience_alignment": _experience_alignment(profile),
                "winner_similarity": 0.0,
            },
        )

    base_prior = _AWARD_FAMILY_BASE_PRIORS.get(award.family, 0.15)
    if award.family == "GOVERNMENT_SCHOLARSHIP" and is_post_admission_gov_scholarship(
        award.name,
        award.holder_domain,
        award.country_code or "",
        profile.nationality,
        applicant_conditions=facts.applicant_conditions,
    ):
        base_prior = 0.65
    req_gpa = _extract_required_gpa_bar(facts.applicant_conditions, ())
    req_cefr = _extract_required_cefr(facts.applicant_conditions, ())
    gpa_margin = _normalized_gpa_margin(profile.academic_history, required_bar=req_gpa)
    lang_margin = _language_margin(profile, required_cefr=req_cefr, today=today)
    exp_align = _experience_alignment(profile, facts.applicant_conditions)
    winner_sim = _winner_archetype_similarity(profile, winner_cohort)

    has_courses = any(
        course.title for rec in profile.academic_history for course in rec.courses
    )
    coursework_alignment = 0.25 if has_courses else 0.0

    features: dict[str, float] = {
        "base_prior": round(base_prior, 4),
        "gpa_margin": gpa_margin,
        "coursework_alignment": coursework_alignment,
        "language_margin": lang_margin,
        "experience_alignment": exp_align,
        "winner_similarity": winner_sim,
    }

    log_odds = (
        _logit(base_prior)
        + 0.80 * gpa_margin
        + 0.25 * coursework_alignment
        + 0.35 * lang_margin
        + 0.50 * exp_align
        + 0.65 * winner_sim
    )
    cold_prob = _sigmoid(log_odds)
    final_prob = _calibrate_with_outcomes(
        cold_prob,
        features,
        calibration_rows,
        target_opportunity_id=award.id,
        student_origin_country=profile.nationality,
        current_year=ref_year,
    )
    return ProbabilityEstimate(
        chance_pct=_clamp_competitive_pct(final_prob),
        features=features,
    )


def joint_admission_and_funding_chance_pct(
    admit_chance_pct: int,
    award_chance_pcts: Sequence[int],
    *,
    correlation: float = 0.0,
) -> int | None:
    """Joint probability P(admit and funded) when >=1 selective scholarship applies.

    Combines selective scholarship win probabilities via
    ``P(any award) = 1 - prod(1 - p_i)`` and interpolates between independent
    ``P(admit) * P(any award)`` and the Fréchet-Hoeffding upper bound
    ``min(P(admit), P(any award))`` by ``correlation in [0, 1]``, clamped to
    ``[1, min(admit_chance_pct, round(P(any award) * 100))]``. Returns ``None``
    when no selective scholarship applies.
    """
    valid = [pct for pct in award_chance_pcts if 1 <= pct <= 100]
    if not valid:
        return None
    p_admit = max(0.01, min(0.95, admit_chance_pct / 100.0))
    p_no_award = 1.0
    for pct in valid:
        p_no_award *= 1.0 - (pct / 100.0)
    p_any_award = 1.0 - p_no_award
    rho = max(0.0, min(1.0, correlation))
    indep = p_admit * p_any_award
    upper = min(p_admit, p_any_award)
    joint = (1.0 - rho) * indep + rho * upper
    cap = min(admit_chance_pct, max(1, round(p_any_award * 100)))
    return max(1, min(cap, round(joint * 100)))


_CCTLD_TO_COUNTRY: Mapping[str, str] = {
    "uk": "GB",
    "edu": "US",
    "de": "DE",
    "at": "AT",
    "ch": "CH",
    "it": "IT",
    "fr": "FR",
    "pl": "PL",
    "cz": "CZ",
    "hu": "HU",
    "nl": "NL",
    "se": "SE",
    "fi": "FI",
    "no": "NO",
    "dk": "DK",
    "be": "BE",
    "es": "ES",
    "pt": "PT",
    "ie": "IE",
    "ee": "EE",
    "lt": "LT",
    "lv": "LV",
    "ro": "RO",
    "bg": "BG",
    "hr": "HR",
    "si": "SI",
    "sk": "SK",
    "gr": "GR",
    "cy": "CY",
    "lu": "LU",
    "mt": "MT",
    "is": "IS",
    "tr": "TR",
    "jp": "JP",
    "kr": "KR",
    "cn": "CN",
    "sg": "SG",
    "bn": "BN",
    "vn": "VN",
    "id": "ID",
    "in": "IN",
    "pk": "PK",
    "sa": "SA",
    "ae": "AE",
    "qa": "QA",
    "kw": "KW",
    "bh": "BH",
    "ca": "CA",
    "au": "AU",
    "nz": "NZ",
    "az": "AZ",
    "ge": "GE",
}


def infer_country_from_url(source_url: str) -> str:
    """Infer an ISO-3166 alpha-2 country code from an official university URL's TLD."""
    if not source_url:
        return ""
    try:
        host = (urlsplit(source_url).hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return ""
    if not host or "." not in host:
        return ""
    tld = host.rsplit(".", 1)[-1]
    return _CCTLD_TO_COUNTRY.get(tld, "")


def estimate_named_program_chance(
    program_name: str,
    country_code: str,
    profile: StudentProfileSnapshot | None,
    *,
    source_url: str = "",
    calibration_rows: Sequence[OutcomeCalibrationRecord] = (),
    today: date | None = None,
) -> ProbabilityEstimate:
    """Admission estimate (`1..95%`) for a student-named programme (no DB reads)."""
    resolved_country = (country_code or infer_country_from_url(source_url)).strip().upper()
    name_lower = program_name.casefold()
    if "erasmus mundus" in name_lower or "emjm" in name_lower:
        base_prior = 0.08
    elif resolved_country in _RULE_BASED_COUNTRIES:
        base_prior = 0.55
    elif resolved_country in _SELECTIVE_COHORT_COUNTRIES:
        base_prior = 0.30
    else:
        base_prior = 0.40

    ref_year = today.year if today is not None else date.today().year
    if profile is None:
        features = {
            "base_prior": round(base_prior, 4),
            "gpa_margin": 0.0,
            "coursework_alignment": 0.0,
            "language_margin": 0.0,
            "experience_alignment": 0.0,
            "winner_similarity": 0.0,
        }
        final_prob = _calibrate_with_outcomes(
            base_prior,
            features,
            calibration_rows,
            current_year=ref_year,
        )
        return ProbabilityEstimate(
            chance_pct=_clamp_competitive_pct(final_prob),
            features=features,
        )

    gpa_margin = _normalized_gpa_margin(profile.academic_history)
    lang_margin = _language_margin(profile, today=today)
    exp_align = _experience_alignment(profile)
    has_courses = any(
        course.title for rec in profile.academic_history for course in rec.courses
    )
    coursework_alignment = 0.4 if has_courses else 0.0
    features = {
        "base_prior": round(base_prior, 4),
        "gpa_margin": gpa_margin,
        "coursework_alignment": coursework_alignment,
        "language_margin": lang_margin,
        "experience_alignment": exp_align,
        "winner_similarity": 0.0,
    }
    log_odds = (
        _logit(base_prior)
        + 0.70 * gpa_margin
        + 0.65 * coursework_alignment
        + 0.35 * lang_margin
        + 0.25 * exp_align
    )
    cold_prob = _sigmoid(log_odds)
    final_prob = _calibrate_with_outcomes(
        cold_prob,
        features,
        calibration_rows,
        student_origin_country=profile.nationality,
        current_year=ref_year,
    )
    return ProbabilityEstimate(
        chance_pct=_clamp_competitive_pct(final_prob),
        features=features,
    )


def _is_decided_or_expired_waitlist(
    outcome: str, *, intake_year: int | None, current_year: int
) -> bool:
    if outcome in _DECIDED_OUTCOMES:
        return True
    return (
        outcome == Application.Outcome.WAITLISTED
        and intake_year is not None
        and intake_year < current_year
    )


def _extract_snapshot_meta(snap: object) -> tuple[int | None, str]:
    """Return `(intake_year, origin_country)` from a `StudentProfileVersion.snapshot` dict."""
    if not isinstance(snap, Mapping):
        return None, ""
    intake_year: int | None = None
    raw_year = snap.get("target_intake_year")
    if isinstance(raw_year, int) and not isinstance(raw_year, bool):
        intake_year = int(raw_year)
    else:
        raw_date = snap.get("intended_intake")
        if isinstance(raw_date, str) and len(raw_date) >= 4 and raw_date[:4].isdigit():
            intake_year = int(raw_date[:4])
        elif isinstance(raw_date, date):
            intake_year = raw_date.year
    origin_country = ""
    raw_nat = snap.get("nationality")
    if isinstance(raw_nat, str) and len(raw_nat.strip()) == 2:
        origin_country = raw_nat.strip().upper()
    return intake_year, origin_country


def _bundled_funding_outcome_for_application(
    app: Application, *, intake_year: int | None = None, current_year: int | None = None
) -> tuple[str, str]:
    """Return `(funding_outcome, outcome_source)` for a programme card's bundled scholarship."""
    ref_year = current_year if current_year is not None else date.today().year
    if _is_decided_or_expired_waitlist(
        app.funding_outcome, intake_year=intake_year, current_year=ref_year
    ):
        return app.funding_outcome, (
            app.funding_outcome_source or app.outcome_source or Application.OutcomeSource.PERSON
        )
    ev = app.outcome_evidence
    if (
        ev is not None
        and ev.sender_authenticated
        and (ev.decision_reading or {}).get("measured") is True
        and _is_decided_or_expired_waitlist(
            ev.funding_outcome, intake_year=intake_year, current_year=ref_year
        )
    ):
        return ev.funding_outcome, Application.OutcomeSource.MAIL
    signals = MailSignal.objects.filter(
        application=app,
        trusted=True,
        sender_authenticated=True,
    ).exclude(funding_outcome="").order_by("-received_at")
    for sig in signals:
        if (sig.decision_reading or {}).get("measured") is True and _is_decided_or_expired_waitlist(
            sig.funding_outcome, intake_year=intake_year, current_year=ref_year
        ):
            return sig.funding_outcome, Application.OutcomeSource.MAIL
    return "", ""


def purge_student_outcome_calibration_records(
    *, tenant_id: UUID, student_id: UUID
) -> int:
    """Delete all `OutcomeCalibrationRecord` rows derived from one student's applications."""
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        app_ids = list(
            Application.objects.filter(student_id=student_id).values_list("id", flat=True)
        )
    if not app_ids:
        return 0
    qs = OutcomeCalibrationRecord.objects.filter(
        Q(application_id__in=app_ids) | Q(source_application_id__in=app_ids)
    )
    if not qs.exists():
        return 0
    deleted, _ = qs.delete()
    return deleted


def _sync_bundled_scholarship_calibrations(
    app: Application,
    cand: RecommendationCandidate,
    *,
    awards_for_run: Sequence[RecommendationCandidate],
    intake_year: int | None,
    origin_country: str,
    ref_year: int,
) -> set[UUID]:
    """Upsert `OutcomeCalibrationRecord` rows for bundled scholarships on a programme application
    and return the set of derived calibration record IDs synced."""
    bundled_outcome, bundled_source = _bundled_funding_outcome_for_application(
        app, intake_year=intake_year, current_year=ref_year
    )
    if not _is_decided_or_expired_waitlist(
        bundled_outcome, intake_year=intake_year, current_year=ref_year
    ):
        return set()

    derived_cal_ids: set[UUID] = set()
    synced_opp_ids: set[UUID] = set()
    won_flag = bundled_outcome in _WON_OUTCOMES

    for aw_cand in awards_for_run:
        aw_card = aw_cand.funding_card if isinstance(aw_cand.funding_card, Mapping) else {}
        aw_route = str(aw_card.get("route") or "")
        if (
            aw_cand.opportunity_id is None
            or aw_route in _SEPARATE_AWARD_ROUTES
            or aw_cand.estimated_chance_pct is None
            or not bool(aw_cand.calibration_features)
            or not funds(aw_cand, cand)
        ):
            continue
        derived_id = uuid5(app.id, f"award:{aw_cand.opportunity_id}")
        OutcomeCalibrationRecord.objects.update_or_create(
            application_id=derived_id,
            defaults={
                "source_application_id": app.id,
                "program_id": None,
                "opportunity_id": aw_cand.opportunity_id,
                "country_code": aw_cand.country_code or cand.country_code or "",
                "origin_country": origin_country,
                "family": str(aw_card.get("family") or ""),
                "route": aw_route or "PART_OF_PROGRAM_APPLICATION",
                "outcome_source": bundled_source,
                "intake_year": intake_year,
                "predicted_chance_pct": aw_cand.estimated_chance_pct,
                "feature_vector": dict(aw_cand.calibration_features),
                "won": won_flag,
            },
        )
        synced_opp_ids.add(aw_cand.opportunity_id)
        derived_cal_ids.add(derived_id)

    if cand.program_id is None:
        return derived_cal_ids
    prog_row = (
        Program.objects.filter(id=cand.program_id)
        .values("institution_id", "country_code")
        .first()
    )
    att_filter = Q(program_id=cand.program_id) | Q(programs__id=cand.program_id)
    if prog_row and prog_row.get("institution_id"):
        att_filter |= Q(
            scope_type="INSTITUTION",
            institution_id=prog_row["institution_id"],
        )
    attached_opps = (
        FundingOpportunity.objects.filter(att_filter, served=True)
        .exclude(route__in=_SEPARATE_AWARD_ROUTES)
        .distinct()
    )
    for att_opp in attached_opps:
        if att_opp.id in synced_opp_ids:
            continue
        opp_country = (
            att_opp.country_code
            or cand.country_code
            or (prog_row.get("country_code") if prog_row else "")
            or ""
        )
        if (
            att_opp.internationals_included == "NO"
            and origin_country
            and origin_country != opp_country
        ):
            continue
        derived_id = uuid5(app.id, f"award:{att_opp.id}")
        OutcomeCalibrationRecord.objects.update_or_create(
            application_id=derived_id,
            defaults={
                "source_application_id": app.id,
                "program_id": None,
                "opportunity_id": att_opp.id,
                "country_code": opp_country,
                "origin_country": origin_country,
                "family": att_opp.family or "",
                "route": att_opp.route or "PART_OF_PROGRAM_APPLICATION",
                "outcome_source": bundled_source,
                "intake_year": intake_year,
                "predicted_chance_pct": (
                    cand.estimated_funded_chance_pct or cand.estimated_chance_pct or 25
                ),
                "feature_vector": dict(cand.calibration_features),
                "won": won_flag,
            },
        )
        synced_opp_ids.add(att_opp.id)
        derived_cal_ids.add(derived_id)

    return derived_cal_ids


def sync_outcome_calibration_records(
    *, tenant_id: UUID | None = None, today: date | None = None
) -> int:
    """Sync decided non-redacted `Application` outcomes into shared `OutcomeCalibrationRecord`.

    Runs in `runtime_engine`. Upserts `OutcomeCalibrationRecord` for:
    1. Programme and standalone scholarship `Application` rows with `outcome in _DECIDED_OUTCOMES`
       (or `WAITLISTED` from a past intake cycle).
    2. Bundled scholarships (`PART_OF_PROGRAM_APPLICATION` / `UNIVERSITY_NOMINATES`) funded on a
       programme `Application` when `Application.funding_outcome` or an authenticated, measured
       `MailSignal.funding_outcome` records the scholarship decision.
    Deletes any calibration row whose student was erased (`redact_student`), whose outcome
    was cleared, or whose `Application` row was removed.
    """
    full_sweep = tenant_id is None and current_tenant_id() is None
    if tenant_id is not None:
        tenant_ids = [tenant_id]
    elif (ambient := current_tenant_id()) is not None:
        tenant_ids = [ambient]
    else:
        tenant_ids = list(Agency.objects.values_list("id", flat=True))

    ref_year = today.year if today is not None else date.today().year
    upserted = 0
    all_seen_app_ids: set[UUID] = set()
    for tid in tenant_ids:
        with tenant_scope(tid), tenant_transaction(tid):
            tenant_app_ids = set(Application.objects.values_list("id", flat=True))
            all_seen_app_ids.update(tenant_app_ids)
            apps = list(
                Application.objects.filter(candidate__isnull=False).select_related(
                    "candidate__run__profile_version",
                    "outcome_evidence",
                )
            )
            run_ids = {
                app.candidate.run_id
                for app in apps
                if app.candidate is not None and app.candidate.run_id is not None
            }
            awards_by_run: dict[UUID, list[RecommendationCandidate]] = {}
            if run_ids:
                for aw_cand in RecommendationCandidate.objects.filter(
                    run_id__in=run_ids,
                    opportunity_id__isnull=False,
                ):
                    awards_by_run.setdefault(aw_cand.run_id, []).append(aw_cand)

            tenant_active_cal_ids: set[UUID] = set()
            for app in apps:
                cand = app.candidate
                active_cal_ids: set[UUID] = set()
                intake_year: int | None = None
                origin_country = ""
                if cand is not None and cand.run_id is not None:
                    intake_year, origin_country = _extract_snapshot_meta(
                        cand.run.profile_version.snapshot
                    )

                if (
                    cand is not None
                    and _is_decided_or_expired_waitlist(
                        app.outcome, intake_year=intake_year, current_year=ref_year
                    )
                    and cand.estimated_chance_pct is not None
                    and bool(cand.calibration_features)
                ):
                    funding_card = (
                        cand.funding_card if isinstance(cand.funding_card, Mapping) else {}
                    )
                    OutcomeCalibrationRecord.objects.update_or_create(
                        application_id=app.id,
                        defaults={
                            "source_application_id": app.id,
                            "program_id": cand.program_id,
                            "opportunity_id": cand.opportunity_id,
                            "country_code": cand.country_code or "",
                            "origin_country": origin_country,
                            "family": str(funding_card.get("family") or ""),
                            "route": str(
                                funding_card.get("route")
                                or ("OPPORTUNITY" if cand.opportunity_id else "PROGRAM")
                            ),
                            "outcome_source": app.outcome_source or "",
                            "intake_year": intake_year,
                            "predicted_chance_pct": cand.estimated_chance_pct,
                            "feature_vector": dict(cand.calibration_features),
                            "won": app.outcome in _WON_OUTCOMES,
                        },
                    )
                    active_cal_ids.add(app.id)
                    tenant_active_cal_ids.add(app.id)
                    upserted += 1

                # Sync bundled scholarship outcomes recorded on a programme card
                if (
                    cand is not None
                    and cand.program_id is not None
                    and cand.opportunity_id is None
                    and bool(cand.calibration_features)
                ):
                    bundled_ids = _sync_bundled_scholarship_calibrations(
                        app,
                        cand,
                        awards_for_run=awards_by_run.get(cand.run_id, ()),
                        intake_year=intake_year,
                        origin_country=origin_country,
                        ref_year=ref_year,
                    )
                    active_cal_ids.update(bundled_ids)
                    tenant_active_cal_ids.update(bundled_ids)
                    upserted += len(bundled_ids)

                stale_qs = OutcomeCalibrationRecord.objects.filter(
                    Q(application_id=app.id) | Q(source_application_id=app.id)
                )
                if active_cal_ids:
                    stale_qs = stale_qs.exclude(application_id__in=active_cal_ids)
                if stale_qs.exists():
                    stale_qs.delete()

            # Clean up any calibration rows belonging to tenant applications whose candidate was
            # unlinked (`candidate=None`)
            if tenant_app_ids:
                unlinked_qs = OutcomeCalibrationRecord.objects.filter(
                    Q(application_id__in=tenant_app_ids)
                    | Q(source_application_id__in=tenant_app_ids)
                )
                if tenant_active_cal_ids:
                    unlinked_qs = unlinked_qs.exclude(application_id__in=tenant_active_cal_ids)
                if unlinked_qs.exists():
                    unlinked_qs.delete()

    if full_sweep:
        orphan_qs = OutcomeCalibrationRecord.objects.exclude(
            source_application_id__in=all_seen_app_ids
        ).exclude(application_id__in=all_seen_app_ids)
        if orphan_qs.exists():
            orphan_qs.delete()
    return upserted
