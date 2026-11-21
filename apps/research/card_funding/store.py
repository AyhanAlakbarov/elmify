"""Persist a Gen-2 funding `Card` into the shared catalogue (slice 3).

Bridges `apps.research.card_funding.card.Card` (`Track` / `AwardCard`) to
`FundingOpportunity`, `FundingOpportunityProgram`, `FundingBenefit`,
`BenefitRule`, `OfficialEvidenceClaim`, and `FundingCycleVerification` so that
awards read by `read_funding_card` / `hunt_funding_card` flow directly into
`build_student_pack` under the same verified-only, fail-closed gates.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.funding.models import (
    BenefitRule,
    BenefitRuleEvidenceClaim,
    FundingBenefit,
    FundingBenefitEvidenceClaim,
    FundingOpportunity,
    FundingOpportunityEvidenceClaim,
    FundingOpportunityProgram,
    Institution,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Period,
    Program,
)
from apps.research.candidates import Date, Duration, Intake, Requirement
from apps.research.catalog import is_non_masters_program_title
from apps.research.cycle_verification import record_read_evidence
from apps.research.discovery import ResearchLead, catalog_key
from apps.research.funding_judge import FundingDecision
from apps.research.funding_reader import FAMILY_BY_HOLDER
from apps.research.models import Organisation

from .card import AwardCard, Card, Field
from .parse import AwardDate, Benefit, Condition, Nationality

_MASTER_TARGET_LEVELS: frozenset[str] = frozenset(
    {
        "master",
        "master_among_several",
        "higher_education_general",
        "any",
        "all_levels",
        "postgraduate",
    }
)

_MONEY_FORM_MAP: dict[str, str] = {
    "grant": "GRANT",
    "fee_waiver": "FEE_WAIVER",
    "subsidy": "SUBSIDY",
    "stipend": "GRANT",
    "assistantship_or_salary": "GRANT",
    "forgivable_loan": "FORGIVABLE_LOAN",
    "loan": "LOAN",
    "mixed": "MIXED",
    "other": "OTHER",
}

_ROUTE_MAP: dict[str, str] = {
    "automatic_on_admission": "AUTOMATIC_ON_ADMISSION",
    "automatic": "AUTOMATIC_ON_ADMISSION",
    "considered_with_admission": "CONSIDERED_WITH_ADMISSION",
    "with_admission": "CONSIDERED_WITH_ADMISSION",
    "student_applies_separately": "STUDENT_APPLIES_SEPARATELY",
    "separate_application": "STUDENT_APPLIES_SEPARATELY",
    "institution_nominates": "INSTITUTION_NOMINATES",
    "home_government_nominates": "HOME_GOVERNMENT_NOMINATES",
    "home_country_nominates": "HOME_GOVERNMENT_NOMINATES",
    "employer_nominates": "INSTITUTION_NOMINATES",
    "joint_selection": "JOINT_SELECTION",
    "other": "OTHER",
}

_ROUTE_ORDER_MAP: dict[str, str] = {
    "before_admission": "PRE_ARRIVAL",
    "after_admission": "POST_ARRIVAL",
    "parallel": "EITHER",
    "with_admission": "EITHER",
    "either": "EITHER",
}

_COVERAGE_MAP: dict[str, str] = {
    "full": "FULL",
    "partial": "PARTIAL",
    "none": "NONE",
}

_PERIOD_MAP: dict[str, str] = {
    "monthly": Period.MONTHLY,
    "month": Period.MONTHLY,
    "annual": Period.ANNUAL,
    "year": Period.ANNUAL,
    "per_semester": Period.FULL_PROGRAM,
    "semester": Period.FULL_PROGRAM,
    "one_off": Period.ONE_OFF,
    "instalments": Period.FULL_PROGRAM,
    "full_programme": Period.FULL_PROGRAM,
    "total": Period.FULL_PROGRAM,
}

_BOUND_MAP: dict[str, str] = {
    "exact": "EXACT",
    "approximately": "EXACT",
    "up_to": "UP_TO",
    "range": "UP_TO",
    "at_least": "AT_LEAST",
}

_OBLIGATION_MAP: dict[str, str] = {
    "return_home": "RETURN_HOME",
    "work_in_host": "WORK_IN_HOST",
    "serve_funder": "SERVE_FUNDER",
    "repay_on_breach": "REPAY_ON_BREACH",
    "maintain_progress": "MAINTAIN_PROGRESS",
}


def _field_raw_values(award: AwardCard, field_name: str) -> tuple[object, ...]:
    cell = award.fields.get(field_name)
    if cell is None or cell.state != "shown":
        return ()
    return tuple(v.value for v in cell.values)


def _field_quotes(cell: Field | None) -> tuple[str, ...]:
    if cell is None:
        return ()
    return tuple(v.quote.text for v in cell.values if v.quote is not None and v.quote.text)


def _target_levels(award: AwardCard) -> set[str]:
    return {str(val).lower() for val in _field_raw_values(award, "target_level")}


def _money_forms(award: AwardCard) -> set[str]:
    return {str(val).lower() for val in _field_raw_values(award, "money_form")}


#: Secondary detail fields where an unconditional hold blanks the field to
#: UNSTATED and records it in `FundingOpportunity.unconfirmed` while keeping
#: the award servable (`served=True`, `agreement="AGREED"`), matching
#: `funding_judge.py`'s tiered agreement rule (spec 8.6 / decision 23).
#: Holds on core existence, support, level or eligibility fields (`*`,
#: `benefits`, `fees`, `target_level`, `nationality`, `requirements`,
#: `holder_kind`, `institution_wide`, `discontinued`, `window_closed`,
#: `tuition_level`, `living_level`) remain blocking (`served=False`).
_SECONDARY_HOLD_TO_UNCONFIRMED: dict[str, str] = {
    "funding_duration": "duration",
    "duration": "duration",
    "route_order": "timing",
    "funding_period": "cycle",
    "dates": "dates",
    "route": "route",
    "application_route": "route",
    "money_form": "money_form",
    "extras": "extras",
    "obligations": "obligations",
    "apply_here": "apply_here",
    "apply_elsewhere": "apply_elsewhere",
    "renewal_condition": "renewal_condition",
}


def _is_discontinued(award: AwardCard) -> bool:
    return "yes" in {str(val).lower() for val in _field_raw_values(award, "discontinued")}


def _has_blocking_unconditional_hold(award: AwardCard) -> bool:
    return any(
        not hold.countries and hold.field not in _SECONDARY_HOLD_TO_UNCONFIRMED
        for hold in award.holds
    )


def _unconfirmed_fields(award: AwardCard) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _SECONDARY_HOLD_TO_UNCONFIRMED[hold.field]
                for hold in award.holds
                if not hold.countries and hold.field in _SECONDARY_HOLD_TO_UNCONFIRMED
            }
        )
    )


def _has_stated_support(award: AwardCard) -> bool:
    if _field_raw_values(award, "benefits"):
        return True
    for field_name in ("tuition_level", "living_level", "tuition_coverage", "living_coverage"):
        vals = {str(val).lower() for val in _field_raw_values(award, field_name)}
        if vals & {"partial", "full"}:
            return True
    forms = _money_forms(award)
    return bool(forms - {"loan", "not_stated"})


def is_servable_award(card: Card, award: AwardCard) -> bool:
    """Whether `award` on `card` may be served to a student (verified-catalog §3.1 / §5.5).

    Enforces:
    - `card.outcome == "read"`
    - No blocking unconditional hold on core existence/support/eligibility fields
      (secondary detail holds on duration, timing, cycle, dates, route, etc.
      are recorded in `unconfirmed` and do not hide the award)
    - Not discontinued (`discontinued != "yes"`)
    - Target level includes a Master's-compatible value when stated
      (`bachelor`, `phd`, `postdoc`-only tracks are never served)
    - Not a pure loan (`money_form == {"loan"}` is never served; `"forgivable_loan"` is kept)
    - States at least one benefit, coverage level, or non-loan money form
    """
    if card.outcome != "read":
        return False
    if _has_blocking_unconditional_hold(award) or _is_discontinued(award):
        return False
    levels = _target_levels(award)
    if levels and not (levels & _MASTER_TARGET_LEVELS):
        return False
    if not levels and is_non_masters_program_title(award.name):
        return False
    forms = _money_forms(award)
    if forms and forms <= {"loan"}:
        return False
    return _has_stated_support(award)


def _money_form_code(award: AwardCard) -> str:
    forms = sorted(_money_forms(award) - {"loan", "not_stated"}) or sorted(_money_forms(award))
    if not forms:
        return "UNSTATED"
    if len(forms) == 1:
        return _MONEY_FORM_MAP.get(forms[0], "UNSTATED")
    return "MIXED"


def _route_code(award: AwardCard) -> str:
    for fname in ("route", "application_route"):
        vals = _field_raw_values(award, fname)
        if vals:
            return _ROUTE_MAP.get(str(vals[0]).lower(), "UNSTATED")
    return "UNSTATED"


def _timing_code(award: AwardCard) -> str:
    vals = _field_raw_values(award, "route_order")
    if not vals:
        return "UNSTATED"
    return _ROUTE_ORDER_MAP.get(str(vals[0]).lower(), "UNSTATED")


def _coverage_code(award: AwardCard, primary_field: str, fallback_field: str) -> str:
    for fname in (primary_field, fallback_field):
        vals = _field_raw_values(award, fname)
        if vals:
            return _COVERAGE_MAP.get(str(vals[0]).lower(), "UNSTATED")
    return "UNSTATED"


def _obligation_code(award: AwardCard, *, money_form: str) -> str:
    vals = _field_raw_values(award, "obligations")
    codes: list[str] = []
    for val in vals:
        items = val if isinstance(val, (set, frozenset, tuple, list)) else (val,)
        for item in items:
            mapped = _OBLIGATION_MAP.get(str(item).lower())
            if mapped and mapped not in codes:
                codes.append(mapped)
    if money_form == "FORGIVABLE_LOAN" and not codes:
        codes.append("SERVE_FUNDER")
    return ";".join(sorted(codes))[:80]


def _nationality_codes(award: AwardCard) -> tuple[str, str]:
    vals = [v for v in _field_raw_values(award, "nationality") if isinstance(v, Nationality)]
    if not vals:
        return "UNSTATED", "UNSTATED"
    if any(n.eligible or n.excluded for n in vals):
        return "COUNTRY_LIST", "YES"
    if any("INTERNATIONAL" in n.groups for n in vals):
        return "OPEN", "YES"
    return "UNSTATED", "UNSTATED"


def _duration_fields(
    award: AwardCard, *, program: Program | None = None
) -> tuple[str, int | None]:
    for fname in ("funding_duration", "duration"):
        cell = award.fields.get(fname)
        if cell is None or cell.state != "shown" or not cell.values:
            continue
        durations = [v.value for v in cell.values if isinstance(v.value, Duration)]
        if not durations:
            continue
        first = durations[0]
        quotes = _field_quotes(cell)
        text = (quotes[0][:40] if quotes else "") or first.text[:40]
        months = first.months
        if months is None and first.count is not None:
            if first.unit == "months":
                months = int(first.count)
            elif first.unit == "years":
                months = int(first.count * 12)
        if months is not None and not (1 <= months <= 60):
            months = None
        return text, months
    benefits = [v for v in _field_raw_values(award, "benefits") if isinstance(v, Benefit)]
    for b in benefits:
        if b.duration == "first_year_only":
            return "first year only", 12
        if (
            b.duration == "whole_programme"
            and program is not None
            and program.duration_months
            and 1 <= program.duration_months <= 60
        ):
            return "whole programme", int(program.duration_months)
    return "", None


def _benefit_kind(benefit: Benefit) -> str:
    if benefit.pays == "fee_reduction" or "tuition" in benefit.covers:
        return "TUITION"
    if "living" in benefit.covers:
        return "STIPEND"
    if "travel" in benefit.covers:
        return "TRAVEL"
    if "housing" in benefit.covers:
        return "HOUSING"
    if "insurance" in benefit.covers:
        return "INSURANCE"
    if "relocation" in benefit.covers:
        return "RELOCATION"
    if benefit.pays == "paid_to_student":
        return "STIPEND"
    return "OTHER"


def _opportunity_kind(award: AwardCard, *, inst_wide: bool, is_holder: bool) -> str:
    if is_holder:
        return "I0_HOLDER_AWARD"
    if inst_wide:
        return "I1_UNIVERSITY_WIDE"
    forms = _money_forms(award)
    if "assistantship_or_salary" in forms:
        return "I3_STIPEND_OR_ASSISTANTSHIP"
    return "I2_PROGRAMME_ATTACHED"


def _all_quotes(award: AwardCard) -> tuple[str, ...]:
    seen: list[str] = []
    if award.name_quote is not None and award.name_quote.text:
        seen.append(award.name_quote.text)
    for cell in award.fields.values():
        for quote in _field_quotes(cell):
            if quote and quote not in seen:
                seen.append(quote)
    for hold in award.holds:
        if hold.detail and hold.detail not in seen:
            seen.append(hold.detail)
    return tuple(seen) or (award.name or "Scholarship",)


def _chunk_iso_codes(codes: frozenset[str] | set[str], max_len: int = 195) -> list[str]:
    """Split ISO country codes into comma-joined chunks fitting within `max_len`."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for code in sorted(codes):
        piece_len = len(code) + (1 if current else 0)
        if current and current_len + piece_len > max_len:
            chunks.append(",".join(current))
            current = [code]
            current_len = len(code)
        else:
            current.append(code)
            current_len += piece_len
    if current:
        chunks.append(",".join(current))
    return chunks


_TEST_TO_LANGUAGE: dict[str, str] = {
    "ielts": "English",
    "toefl": "English",
    "pte": "English",
    "duolingo": "English",
    "cambridge": "English",
    "cae": "English",
    "cpe": "English",
    "fce": "English",
    "testdaf": "German",
    "dsh": "German",
    "goethe": "German",
    "ösd": "German",
    "osd": "German",
    "telc": "German",
    "delf": "French",
    "dalf": "French",
    "tcf": "French",
    "tef": "French",
    "dele": "Spanish",
    "siele": "Spanish",
    "cils": "Italian",
    "celi": "Italian",
    "plida": "Italian",
    "torfl": "Russian",
    "trki": "Russian",
    "tömer": "Turkish",
    "tomer": "Turkish",
    "yökdil": "Turkish",
    "hsk": "Chinese",
    "jlpt": "Japanese",
    "topik": "Korean",
}

_QUOTE_LANGUAGE_RE = re.compile(
    r"\b(english|german|deutsch|french|français|francais|italian|italiano|spanish|español"
    r"|dutch|nederlands|turkish|türkçe|azerbaijani|russian|русский|chinese|mandarin"
    r"|japanese|korean|arabic|portuguese|polish|swedish)\b",
    re.IGNORECASE,
)


def _infer_requirement_language(req: Requirement | None, quote: str) -> str:
    if req is not None and req.test:
        test_lower = req.test.strip().lower()
        for prefix, lang_name in _TEST_TO_LANGUAGE.items():
            if prefix in test_lower:
                return lang_name
    haystack = f"{req.text if req is not None and req.text else ''} {quote}"
    match = _QUOTE_LANGUAGE_RE.search(haystack)
    if match:
        return match.group(1)
    for prefix, lang_name in _TEST_TO_LANGUAGE.items():
        if re.search(rf"\b{re.escape(prefix)}\b", haystack, re.IGNORECASE):
            return lang_name
    return "UNSTATED_LANGUAGE"


def _create_rule_for_benefits(
    benefits: Sequence[FundingBenefit],
    *,
    key: str,
    operator: str,
    value: str,
    unit: str | None = None,
    rule_text: str,
    claims: list[OfficialEvidenceClaim],
    quote: str = "",
) -> None:
    matching = [c for c in claims if quote and c.claim == quote] or claims
    comp_unit = unit if unit in ("MONTHS", "HOURS") else None
    for benefit in benefits:
        rule = BenefitRule.objects.create(
            benefit=benefit,
            kind=BenefitRule.Kind.ELIGIBILITY,
            key=key,
            operator=operator,
            value=value[:200],
            comparable_unit=comp_unit,
            rule_text=rule_text[:4_000],
            scope_type=BenefitRule.Scope.GLOBAL,
        )
        for claim in matching:
            BenefitRuleEvidenceClaim.objects.get_or_create(
                benefit_rule=rule, evidence_claim=claim
            )


def _write_requirement_rule(
    benefits: Sequence[FundingBenefit],
    cond: Condition | Requirement,
    quote: str,
    claims: list[OfficialEvidenceClaim],
) -> None:
    if isinstance(cond, Condition):
        kind = cond.kind
        req = cond.requirement
    else:
        kind = cond.kind
        req = cond

    rule_text = (quote or (req.text if req is not None else "") or "Eligibility requirement")[
        :4_000
    ]

    if kind == "age" and req is not None and (req.age_max is not None or req.age_min is not None):
        if req.age_max is not None:
            _create_rule_for_benefits(
                benefits,
                key="AGE",
                operator="LTE",
                value=str(req.age_max),
                unit="YEARS",
                rule_text=rule_text,
                claims=claims,
                quote=quote,
            )
        if req.age_min is not None:
            _create_rule_for_benefits(
                benefits,
                key="AGE",
                operator="GTE",
                value=str(req.age_min),
                unit="YEARS",
                rule_text=rule_text,
                claims=claims,
                quote=quote,
            )
        return

    key = "OTHER"
    operator = "PRESENT"
    value = req.text[:200] if req is not None and req.text else quote[:200]
    unit: str | None = None

    if kind == "prior_degree":
        key = "PRIOR_DEGREE"
        operator = "GTE"
        value = "BACHELOR"
    elif kind == "excluded_degree":
        from apps.funding.eligibility import _degree_level

        probe = (req.text if req is not None and req.text else quote) or ""
        lvl = _degree_level(probe)
        if lvl in ("MASTER", "MS", "MSC", "MA"):
            key = "PRIOR_DEGREE"
            operator = "NOT_IN"
            value = "MASTER,DOCTORATE"
        elif lvl in ("PHD", "DOCTORATE"):
            key = "PRIOR_DEGREE"
            operator = "NOT_IN"
            value = "DOCTORATE"
        else:
            key = "OTHER"
            operator = "PRESENT"
            value = probe[:200]
    elif kind == "grade" and req is not None and req.score is not None:
        key = "GRADE"
        operator = "GTE"
        scale_part = f" {req.scale}" if req.scale is not None else ""
        value = f"{req.score}{scale_part}"[:200]
    elif kind in ("language_test", "cefr", "test_or_certificate"):
        key = "LANGUAGE"
        lang_name = _infer_requirement_language(req, quote)
        if req is not None and req.cefr:
            operator = "GTE"
            value = f"{lang_name} {req.cefr.upper()}"[:200]
        elif req is not None and req.test:
            operator = "PRESENT"
            score_part = f" {req.score}" if req.score is not None else ""
            value = f"{lang_name} {req.test}{score_part}"[:200]
        else:
            operator = "PRESENT"
            raw_text = (req.text if req is not None and req.text else quote).strip()
            value = (
                raw_text[:200]
                if lang_name == "UNSTATED_LANGUAGE"
                else f"{lang_name} {raw_text}"[:200]
            )
    elif kind == "residence_limit":
        key = "RESIDENCE"
        operator = "PRESENT"
        value = (req.text if req is not None else quote)[:200]
    elif kind in ("work_experience", "experience"):
        probe = (req.text if req is not None and req.text else quote) or ""
        m_exp = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(years?|yrs?|months?|mos?)\b", probe, re.IGNORECASE
        )
        if m_exp:
            num = float(m_exp.group(1).replace(",", "."))
            u_str = m_exp.group(2).casefold()
            months_val = int(round(num * 12)) if u_str.startswith("y") else int(round(num))
            key = "WORK_EXPERIENCE"
            operator = "GTE"
            value = str(months_val)
            unit = "MONTHS"

    _create_rule_for_benefits(
        benefits,
        key=key,
        operator=operator,
        value=value,
        unit=unit,
        rule_text=rule_text,
        claims=claims,
        quote=quote,
    )


def _write_award_benefits_and_rules(
    opportunity: FundingOpportunity,
    award: AwardCard,
    *,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    served: bool,
    checked_at: datetime,
    lead: ResearchLead | None,
) -> None:
    old_claim_ids = list(opportunity.evidence_claims.values_list("id", flat=True))
    BenefitRuleEvidenceClaim.objects.filter(benefit_rule__benefit__opportunity=opportunity).delete()
    BenefitRule.objects.filter(benefit__opportunity=opportunity).delete()
    FundingBenefitEvidenceClaim.objects.filter(benefit__opportunity=opportunity).delete()
    FundingOpportunityEvidenceClaim.objects.filter(opportunity=opportunity).delete()
    FundingBenefit.objects.filter(opportunity=opportunity).delete()
    OfficialEvidenceClaim.objects.filter(id__in=old_claim_ids).delete()

    strength = lead.evidence_strength if lead is not None else "DIRECT"
    visibility = (
        (lead.visibility if lead is not None else "STUDENT_FACING") if served else "INTERNAL"
    )
    quotes = _all_quotes(award)
    claims: list[OfficialEvidenceClaim] = []
    for quote in quotes:
        claim = OfficialEvidenceClaim.objects.create(
            source=source,
            snapshot=snapshot,
            claim=quote[:4_000],
            evidence_strength=strength,
            visibility=visibility,
            claim_class=OfficialEvidenceClaim.ClaimClass.FUNDING,
            last_checked_at=checked_at,
        )
        FundingOpportunityEvidenceClaim.objects.create(
            opportunity=opportunity, evidence_claim=claim
        )
        claims.append(claim)

    created_benefits: list[FundingBenefit] = []
    place_scoped_benefits: set[UUID] = set()
    benefits_cell = award.fields.get("benefits")
    if benefits_cell is not None and benefits_cell.state == "shown":
        for val_wrapper in benefits_cell.values:
            raw_val = val_wrapper.value
            if not isinstance(raw_val, Benefit):
                continue
            if (
                raw_val.level is not None
                and str(raw_val.level).lower() not in _MASTER_TARGET_LEVELS
            ):
                continue
            b_kind = _benefit_kind(raw_val)
            b_period = _PERIOD_MAP.get(raw_val.frequency, Period.FULL_PROGRAM)
            raw_bound = raw_val.bound or raw_val.amount.bound or "exact"
            b_bound = _BOUND_MAP.get(raw_bound, "EXACT")
            b_quote = (
                val_wrapper.quote.text
                if (val_wrapper.quote is not None and val_wrapper.quote.text)
                else raw_val.amount.text
            )
            chosen_num = (
                raw_val.amount.high
                if (raw_bound == "range" and raw_val.amount.high is not None)
                else raw_val.amount.low
            )
            currency = raw_val.amount.currency
            has_money = (
                chosen_num is not None
                and currency is not None
                and len(currency) == 3
                and currency.isupper()
            )
            amount_dec = chosen_num if has_money else None
            currency_code = currency if has_money else None
            amount_text = raw_val.amount.text[:40]
            benefit = FundingBenefit.objects.create(
                opportunity=opportunity,
                kind=b_kind,
                amount=amount_dec,
                currency=currency_code,
                period=b_period,
                description=(b_quote or opportunity.name)[:2_000],
                repayable_share=Decimal("0"),
                amount_text=amount_text,
                amount_bound=b_bound if amount_text else "",
                amount_quote=b_quote[:1_000] if amount_text else "",
            )
            for claim in claims:
                FundingBenefitEvidenceClaim.objects.get_or_create(
                    benefit=benefit, evidence_claim=claim
                )
            if not raw_val.for_all and (raw_val.places or raw_val.held_places):
                place_scoped_benefits.add(benefit.id)
                for chunk in _chunk_iso_codes(frozenset(raw_val.places)):
                    _create_rule_for_benefits(
                        (benefit,),
                        key="CITIZENSHIP",
                        operator="IN",
                        value=chunk,
                        rule_text=b_quote or opportunity.name,
                        claims=claims,
                        quote=b_quote,
                    )
                for chunk in _chunk_iso_codes(frozenset(raw_val.held_places)):
                    _create_rule_for_benefits(
                        (benefit,),
                        key="CITIZENSHIP",
                        operator="NOT_IN",
                        value=chunk,
                        rule_text=b_quote or opportunity.name,
                        claims=claims,
                        quote=b_quote,
                    )
            created_benefits.append(benefit)

    existing_kinds = {b.kind for b in created_benefits}
    if opportunity.tuition in ("PARTIAL", "FULL") and "TUITION" not in existing_kinds:
        tuition_cell = award.fields.get("tuition_level") or award.fields.get("tuition_coverage")
        t_quotes = _field_quotes(tuition_cell)
        t_quote = t_quotes[0] if t_quotes else quotes[0]
        benefit = FundingBenefit.objects.create(
            opportunity=opportunity,
            kind="TUITION",
            period=Period.FULL_PROGRAM,
            description=t_quote[:2_000],
            repayable_share=Decimal("0"),
        )
        for claim in claims:
            FundingBenefitEvidenceClaim.objects.get_or_create(benefit=benefit, evidence_claim=claim)
        created_benefits.append(benefit)

    if opportunity.living in ("PARTIAL", "FULL") and not (
        existing_kinds & {"STIPEND", "ASSISTANTSHIP"}
    ):
        living_cell = award.fields.get("living_level") or award.fields.get("living_coverage")
        l_quotes = _field_quotes(living_cell)
        l_quote = l_quotes[0] if l_quotes else quotes[0]
        benefit = FundingBenefit.objects.create(
            opportunity=opportunity,
            kind="STIPEND",
            period=Period.FULL_PROGRAM,
            description=l_quote[:2_000],
            repayable_share=Decimal("0"),
        )
        for claim in claims:
            FundingBenefitEvidenceClaim.objects.get_or_create(benefit=benefit, evidence_claim=claim)
        created_benefits.append(benefit)

    if not created_benefits:
        benefit = FundingBenefit.objects.create(
            opportunity=opportunity,
            kind="OTHER",
            period=Period.FULL_PROGRAM,
            description=quotes[0][:2_000],
            repayable_share=Decimal("0"),
        )
        for claim in claims:
            FundingBenefitEvidenceClaim.objects.get_or_create(benefit=benefit, evidence_claim=claim)
        created_benefits.append(benefit)

    unscoped_benefits = [b for b in created_benefits if b.id not in place_scoped_benefits]
    nat_targets = unscoped_benefits or created_benefits

    # 1. Nationality rules from `Nationality` values
    nat_cell = award.fields.get("nationality")
    if nat_cell is not None and nat_cell.state == "shown":
        nat_quotes = _field_quotes(nat_cell)
        nat_quote = nat_quotes[0] if nat_quotes else quotes[0]
        for val_wrapper in nat_cell.values:
            nat = val_wrapper.value
            if not isinstance(nat, Nationality):
                continue
            rule_keys = (
                ("RESIDENCE",)
                if nat.basis == "residence"
                else (("CITIZENSHIP", "RESIDENCE") if nat.basis == "both" else ("CITIZENSHIP",))
            )
            if nat.eligible:
                from apps.funding.eligibility import _all_cldr_country_codes, expand_countries

                extra_excluded: set[str] = set()
                groups_expr = ",".join(nat.groups) if nat.groups else ""
                group_expanded = (
                    expand_countries(groups_expr)
                    if groups_expr and len(groups_expr) <= 195
                    else None
                )
                joined_eligible = ",".join(sorted(nat.eligible))
                compact_iso2 = "ISO2:" + "".join(sorted(nat.eligible))
                if group_expanded is not None and frozenset(group_expanded) == nat.eligible:
                    eligible_val = groups_expr
                elif (
                    len(joined_eligible) > 195
                    and group_expanded is not None
                    and nat.eligible <= frozenset(group_expanded)
                ):
                    eligible_val = groups_expr
                    extra_excluded.update(frozenset(group_expanded) - nat.eligible)
                elif len(joined_eligible) <= 195:
                    eligible_val = joined_eligible
                elif len(compact_iso2) <= 199:
                    eligible_val = compact_iso2
                else:
                    eligible_val = "ALL_COUNTRIES"
                    extra_excluded.update(
                        (frozenset(_all_cldr_country_codes()) | nat.eligible) - nat.eligible
                    )
                if eligible_val:
                    for r_key in rule_keys:
                        _create_rule_for_benefits(
                            nat_targets,
                            key=r_key,
                            operator="IN",
                            value=eligible_val,
                            rule_text=nat_quote,
                            claims=claims,
                        )
                for chunk in _chunk_iso_codes(frozenset(extra_excluded)):
                    for r_key in rule_keys:
                        _create_rule_for_benefits(
                            nat_targets,
                            key=r_key,
                            operator="NOT_IN",
                            value=chunk,
                            rule_text=nat_quote,
                            claims=claims,
                        )
            for chunk in _chunk_iso_codes(nat.excluded):
                for r_key in rule_keys:
                    _create_rule_for_benefits(
                        nat_targets,
                        key=r_key,
                        operator="NOT_IN",
                        value=chunk,
                        rule_text=nat_quote,
                        claims=claims,
                    )

    # 2. Country-specific holds (fail-closed for applicants from held countries)
    for hold in award.holds:
        if hold.countries:
            if hold.field == "benefits" and place_scoped_benefits:
                continue
            for chunk in _chunk_iso_codes(hold.countries):
                _create_rule_for_benefits(
                    created_benefits,
                    key="CITIZENSHIP",
                    operator="NOT_IN",
                    value=chunk,
                    rule_text=hold.detail or f"Held country group ({hold.reason}): {chunk}",
                    claims=claims,
                )

    # 3. Requirement rules
    req_cell = award.fields.get("requirements")
    if req_cell is not None and req_cell.state == "shown":
        for val_wrapper in req_cell.values:
            raw_req = val_wrapper.value
            if isinstance(raw_req, (Condition, Requirement)):
                r_quote = (
                    val_wrapper.quote.text
                    if (val_wrapper.quote is not None and val_wrapper.quote.text)
                    else quotes[0]
                )
                _write_requirement_rule(created_benefits, raw_req, r_quote, claims)


def _date_iso(award_date: AwardDate) -> str:
    import calendar

    d = award_date.date
    if not isinstance(d, Date) or d.year is None or d.month is None:
        return ""
    if award_date.role == "application_period" and d.end_year and d.end_month:
        end_day = d.end_day or calendar.monthrange(d.end_year, d.end_month)[1]
        return dt.date(d.end_year, d.end_month, end_day).isoformat()
    day = d.day or calendar.monthrange(d.year, d.month)[1]
    return dt.date(d.year, d.month, day).isoformat()


def _card_applies_to_and_suspension(award: AwardCard) -> tuple[str, str, str]:
    from apps.funding.transcript_eligibility import parse_scholarship_status_statement
    from apps.funding.validity import intake_start_years

    applies_to = "UNSTATED"
    period_vals = [v for v in _field_raw_values(award, "funding_period") if isinstance(v, Intake)]
    if period_vals:
        first_p = period_vals[0]
        applies_to = (
            f"{first_p.start_year}-{first_p.end_year}"
            if first_p.end_year
            else str(first_p.start_year)
        )[:24]
    elif award.cycle is not None:
        applies_to = str(award.cycle)[:24]

    discontinued = _is_discontinued(award)
    disc_quotes = _field_quotes(award.fields.get("discontinued"))
    suspension_quote = (
        disc_quotes[0][:300]
        if (discontinued and disc_quotes)
        else ("Discontinued" if discontinued else "")
    )
    suspended_for = applies_to if (suspension_quote and applies_to != "UNSTATED") else ""
    if not suspension_quote:
        for q in _all_quotes(award):
            parsed = parse_scholarship_status_statement(q)
            if parsed is not None and parsed[0] == "NO_SCHOLARSHIP":
                suspension_quote = q[:300]
                if parsed[1] != "UNSTATED":
                    suspended_for = parsed[1][:24]
                    if applies_to == "UNSTATED":
                        applies_to = suspended_for
                elif applies_to != "UNSTATED":
                    suspended_for = applies_to
                break
    if suspension_quote and not suspended_for:
        quote_years = sorted(intake_start_years(suspension_quote))
        if quote_years:
            suspended_for = (
                f"{quote_years[0]}-{quote_years[-1]}"
                if len(quote_years) > 1
                else str(quote_years[0])
            )[:24]
            if applies_to == "UNSTATED":
                applies_to = suspended_for
    return applies_to, suspension_quote, suspended_for


def _record_card_cycle_evidence(
    opportunity: FundingOpportunity,
    award: AwardCard,
    *,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    served: bool,
    checked_at: datetime,
) -> None:
    dates_cell = award.fields.get("dates")
    deadlines: list[tuple[str, str]] = []
    if dates_cell is not None and dates_cell.state == "shown":
        for val_wrapper in dates_cell.values:
            val = val_wrapper.value
            if not isinstance(val, AwardDate):
                continue
            if val.role in ("application_deadline", "application_period"):
                iso = _date_iso(val)
                if not iso:
                    continue
                if val.places:
                    for chunk in _chunk_iso_codes(frozenset(val.places), max_len=45):
                        deadlines.append((iso, f"NATIONALITY:{chunk}"))
                else:
                    deadlines.append((iso, "ALL"))

    applies_to, suspension_quote, _ = _card_applies_to_and_suspension(award)
    discontinued = bool(suspension_quote)
    unconditional = [d for d, who in deadlines if who == "ALL"]
    stub = FundingDecision(
        heading=award.name or opportunity.name,
        kind=opportunity.kind or "I2_PROGRAMME_ATTACHED",
        scope="HOLDER_OWN" if opportunity.scope_type == "HOLDER" else opportunity.scope_type,
        offered="NO" if discontinued else "YES",
        internationals_included=opportunity.internationals_included or "UNSTATED",
        nationality_shape=opportunity.nationality_shape or "UNSTATED",
        route=opportunity.route or "UNSTATED",
        money_form=opportunity.money_form or "UNSTATED",
        holder=opportunity.holder or "INSTITUTION",
        tuition=opportunity.tuition or "UNSTATED",
        living=opportunity.living or "UNSTATED",
        extras=(),
        obligation=(),
        agreement="AGREED" if served else "UNAGREED",
        quotes=_all_quotes(award),
        name=opportunity.name,
        disputed=(),
        applies_to=applies_to,
        stated_on="UNSTATED",
        deadline=unconditional[0] if len(unconditional) == 1 else "UNSTATED",
        deadlines=tuple(deadlines),
        suspension_quote=suspension_quote,
    )
    record_read_evidence(
        opportunity,
        stub,
        url=snapshot.final_url or source.canonical_url,
        sha256=snapshot.sha256,
        at=checked_at.date(),
        today=checked_at.date(),
    )


@transaction.atomic
def write_card(
    card: Card,
    *,
    program: Program | None = None,
    institution: Institution | None = None,
    organisation: Organisation | None = None,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    lead: ResearchLead | None = None,
    now: datetime | None = None,
) -> tuple[FundingOpportunity, ...]:
    """Persist a Gen-2 `Card` into the catalogue and return the written rows.

    Requires exactly one of `program` (for programme / institution awards),
    `institution` (for university-wide awards not tied to a single `Program`),
    or `organisation` (for holder awards). Tracks that name only non-master levels
    (`bachelor`, `phd`, `postdoc`) or only `loan` money forms are never written
    (spec §3.1); tracks with unconditional holds or `discontinued == "yes"` are
    written with `served=False`.
    """
    if sum(x is not None for x in (program, institution, organisation)) != 1:
        raise ValueError(
            "write_card requires exactly one of program, institution, or organisation"
        )
    if card.outcome != "read":
        return ()

    checked_at = now or timezone.now()
    written: list[FundingOpportunity] = []
    is_holder = organisation is not None

    for track in card.tracks:
        for award in track.awards:
            levels = _target_levels(award)
            if levels and not (levels & _MASTER_TARGET_LEVELS):
                # Spec §3.1: bachelor's, doctoral or postdoctoral-only tracks are never written.
                continue
            forms = _money_forms(award)
            if forms and forms <= {"loan"}:
                # Spec §3.1: pure loans are never written.
                continue

            inst_vals = {str(v).lower() for v in _field_raw_values(award, "institution_wide")}
            inst_wide = not is_holder and (
                institution is not None
                or ("yes" in inst_vals and (program is None or program.institution_id is not None))
            )
            if inst_wide and institution is None and (
                program is None or program.institution_id is None
            ):
                continue

            served = is_servable_award(card, award) and (
                lead.can_support_claim if lead is not None else True
            )
            kind = _opportunity_kind(award, inst_wide=inst_wide, is_holder=is_holder)
            money_form = _money_form_code(award)
            route = _route_code(award)
            timing = _timing_code(award)
            tuition = _coverage_code(award, "tuition_level", "tuition_coverage")
            living = _coverage_code(award, "living_level", "living_coverage")
            nat_shape, intl_included = _nationality_codes(award)
            duration_text, duration_months = _duration_fields(award, program=program)
            obligation = _obligation_code(award, money_form=money_form)

            fallback_name = (
                organisation.name
                if organisation is not None
                else (
                    program.name
                    if program is not None
                    else (institution.name if institution is not None else "Scholarship")
                )
            )
            display_name = (award.name or track.name or fallback_name)[:80]

            applies_to, suspension_quote, suspended_for = _card_applies_to_and_suspension(award)
            blocking_holds = [
                h.field
                for h in award.holds
                if not h.countries and h.field not in _SECONDARY_HOLD_TO_UNCONFIRMED
            ]
            unconfirmed_fields = _unconfirmed_fields(award)
            all_unconditional_holds = [h.field for h in award.holds if not h.countries]
            agreement = "UNAGREED" if blocking_holds else "AGREED"

            if is_holder:
                assert organisation is not None
                holder_vals = _field_raw_values(award, "holder_kind")
                card_holder = (
                    str(holder_vals[0]).upper()
                    if holder_vals and str(holder_vals[0]).lower() != "not_stated"
                    else ""
                )
                holder_kind = organisation.kind or card_holder or "PRIVATE_FOUNDATION"
                family = FAMILY_BY_HOLDER.get(holder_kind, "PRIVATE_FOUNDATION")
                canonical_key = catalog_key(
                    "card",
                    f"HOLDER:{organisation.pk}:{source.id}:{track.name}:{award.name}",
                )
                defaults: dict[str, object] = {
                    "name": display_name,
                    "family": family,
                    "scope_type": "HOLDER",
                    "institution": None,
                    "program": None,
                    "holder": holder_kind,
                    "organisation": organisation,
                    "holder_domain": organisation.primary_domain,
                    "holder_name": organisation.name[:300],
                }
            else:
                target_inst = (
                    institution
                    if institution is not None
                    else (program.institution if program is not None else None)
                )
                scope_type = "INSTITUTION" if inst_wide else "PROGRAM"
                anchor_id = (
                    target_inst.id
                    if inst_wide and target_inst is not None
                    else (program.id if program is not None else None)
                )
                family = (
                    "UNIVERSITY_WIDE"
                    if inst_wide
                    else (
                        "STIPEND_OR_ASSISTANTSHIP"
                        if kind == "I3_STIPEND_OR_ASSISTANTSHIP"
                        else "DEPARTMENT_OR_PROGRAM"
                    )
                )
                canonical_key = catalog_key(
                    "card",
                    f"{scope_type}:{anchor_id}:{track.name}:{award.name}:{kind}",
                )
                defaults = {
                    "name": display_name,
                    "family": family,
                    "scope_type": scope_type,
                    "institution": target_inst if inst_wide else None,
                    "program": None if inst_wide else program,
                }

            if not suspension_quote and applies_to == "UNSTATED":
                existing_opp = FundingOpportunity.objects.filter(
                    canonical_key=canonical_key
                ).first()
                if existing_opp is not None and existing_opp.suspension_quote:
                    suspension_quote = existing_opp.suspension_quote
                    suspended_for = existing_opp.suspended_for
            if suspension_quote:
                served = False

            opportunity, _ = FundingOpportunity.objects.update_or_create(
                canonical_key=canonical_key,
                defaults={
                    **defaults,
                    "kind": kind,
                    "agreement": agreement,
                    "served": served,
                    "money_form": money_form,
                    "route": route,
                    "nationality_shape": nat_shape,
                    "internationals_included": intl_included,
                    "obligation": obligation,
                    "found_via": (lead.discovered_by[:60] if lead is not None else "CARD_READER"),
                    "disputed": ";".join(sorted(set(all_unconditional_holds)))[:200],
                    "unconfirmed": (
                        ";".join(unconfirmed_fields)[:200] if agreement == "AGREED" else ""
                    ),
                    "suspended_for": suspended_for,
                    "suspension_quote": suspension_quote,
                    "tuition": tuition,
                    "living": living,
                    "timing": timing,
                    "cycle": (
                        "WITH_ADMISSION_CYCLE"
                        if route in ("AUTOMATIC_ON_ADMISSION", "CONSIDERED_WITH_ADMISSION")
                        else "UNSTATED"
                    ),
                    "duration_text": duration_text,
                    "duration_months": duration_months,
                    "card_quotes": {
                        fname: cell_quotes[0][:1_000]
                        for fname, cell in award.fields.items()
                        if (cell_quotes := _field_quotes(cell))
                    },
                    "review": "",
                    "review_note": "",
                    "reviewed_at": None,
                    "reviewed_sha256": "",
                },
            )
            if not is_holder and not inst_wide and program is not None:
                FundingOpportunityProgram.objects.get_or_create(
                    opportunity=opportunity, program=program
                )
            _write_award_benefits_and_rules(
                opportunity,
                award,
                source=source,
                snapshot=snapshot,
                served=served,
                checked_at=checked_at,
                lead=lead,
            )
            _record_card_cycle_evidence(
                opportunity,
                award,
                source=source,
                snapshot=snapshot,
                served=served,
                checked_at=checked_at,
            )
            written.append(opportunity)

    return tuple(written)
