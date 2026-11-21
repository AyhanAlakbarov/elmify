"""Tier 0 AST fact extractors and candidate currency helpers."""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Literal

from apps.research.candidates import Amount, Candidates, Date, Found, Line, Requirement, find_all
from apps.research.candidates.amounts import find_amounts
from apps.research.candidates.who import find_requirements
from apps.research.card_engine import Quote, locate

from .patterns import (
    _APPLICATION_FEE_RE,
    _APS_LINE_RE,
    _CATEGORY_REF_RE,
    _CHRONO_RE,
    _CLAUSE_SPLIT_RE,
    _CONDITIONAL_GUARD_RE,
    _CV_LINE_RE,
    _CV_MAX_PAGES_RE,
    _CV_NO_GAPS_RE,
    _CV_SIGNED_RE,
    _DEADLINE_CONTEXT_RE,
    _DOB_FORBIDDEN_RE,
    _ECTS_DURATION_RE,
    _EU_DOMESTIC_RE,
    _EUROPASS_PREF_RE,
    _EUROPASS_REQ_RE,
    _FEE_HEADING_RE,
    _FILE_MB_RE,
    _FREE_TUITION_RE,
    _GRE_GMAT_LINE_RE,
    _HEADER_CURRENCY_RE,
    _LANGUAGE_NAMES,
    _LETTER_LINE_RE,
    _LETTER_OPTIONAL_RE,
    _NON_EU_RE,
    _NON_TUITION_COST_RE,
    _NOT_REQUIRED_RE,
    _PDF_FORMAT_RE,
    _PHOTO_FORBIDDEN_RE,
    _PHOTO_REQUIRED_RE,
    _PORTFOLIO_LINE_RE,
    _RANGE_PROSE_RE,
    _REFEREE_ACADEMIC_RE,
    _REFEREE_COUNT_RE,
    _REFEREE_INST_EMAIL_RE,
    _REFEREE_LINE_RE,
    _REVERSE_CHRONO_RE,
    _SCHOLARSHIP_LINK_RE,
    _SEMESTER_CONTRIB_RE,
    _SINGLE_PDF_BUNDLE_RE,
    _TEACHING_CONTEXT_RE,
    _THIRD_PARTY_RE,
    _TRANSCRIPT_LINE_RE,
    _TUITION_WORD_RE,
    _WORD_NUM,
)
from .specs import (
    CostComponentSpec,
    DocumentStatementSpec,
    EligibilitySpec,
    InstitutionBaseProfile,
    ProgrammeBundle,
    ProgrammeScrapeResult,
)

logger = logging.getLogger(__name__)


_PERIOD_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "PER_ECTS",
        ("per ects", "/ects", "each ects", "pro ects", "par crédit ects", "per credit ects"),
    ),
    ("PER_CREDIT", ("per credit", "/credit", "each credit", "per unit")),
    ("SEMESTER", ("per semester", "/semester", "each semester", "pro semester", "semestral")),
    ("MONTHLY", ("per month", "/month", "monthly", "monatlich", "par mois")),
    (
        "FULL_PROGRAM",
        (
            "full programme",
            "full program",
            "entire programme",
            "entire program",
            "total programme",
            "total program",
            "per programme",
            "per program",
            "total tuition",
            "for the 2-year",
            "for the two-year",
        ),
    ),
)


def _period_from_context(context: str) -> str:
    low = context.lower()
    for period, keywords in _PERIOD_KEYWORDS:
        if any(w in low for w in keywords):
            return period
    return "ANNUAL"


def _normalize_tuition_amount_and_period(
    amount: Decimal, raw_period: str
) -> tuple[Decimal, str]:
    if raw_period == "PER_ECTS":
        # 1 full-time academic year = 60 ECTS
        return amount * Decimal(60), "ANNUAL"
    if raw_period == "SEMESTER":
        # Convert semester tuition to annual for CostComponent (which uses Period choices)
        return amount * Decimal(2), "ANNUAL"
    return amount, raw_period


def _audience_from_context(context: str) -> Literal["INTERNATIONAL", "EU_DOMESTIC", "ALL"]:
    if _NON_EU_RE.search(context):
        return "INTERNATIONAL"
    if _EU_DOMESTIC_RE.search(context):
        return "EU_DOMESTIC"
    return "ALL"



def _span_distance(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def _amount_audience_on_line(
    line: Line,
    amt: Amount,
    *,
    from_header: bool = False,
) -> Literal["INTERNATIONAL", "EU_DOMESTIC", "ALL"]:
    """Resolve the audience (`INTERNATIONAL`, `EU_DOMESTIC`, or `ALL`) for a specific `amt`
    on `line`. When a prose sentence contains both EU and Non-EU figures on the same line
    (e.g. 'EUR 2,500 for EU students and EUR 15,000 for non-EU students'), resolves by the
    local clause and character distance to `(amt.start, amt.end)`."""
    # Check cell/dl `line.header` first (more specific than section `line.heading`)
    if line.header:
        hdr_non_eu = bool(_NON_EU_RE.search(line.header))
        hdr_eu = bool(_EU_DOMESTIC_RE.search(line.header))
        if hdr_non_eu and not hdr_eu:
            return "INTERNATIONAL"
        if hdr_eu and not hdr_non_eu:
            return "EU_DOMESTIC"

    target_text = line.header if from_header else line.text
    non_eu_matches = list(_NON_EU_RE.finditer(target_text))
    eu_matches = [
        m
        for m in _EU_DOMESTIC_RE.finditer(target_text)
        if not any(ne.start() <= m.end() and m.start() <= ne.end() for ne in non_eu_matches)
    ]
    if non_eu_matches and not eu_matches:
        return "INTERNATIONAL"
    if eu_matches and not non_eu_matches:
        return "EU_DOMESTIC"
    if non_eu_matches and eu_matches:
        # 1. Check the local clause containing `amt.start..amt.end`
        pos = 0
        for m_sep in _CLAUSE_SPLIT_RE.finditer(target_text):
            clause = target_text[pos : m_sep.start()]
            if pos <= amt.start < m_sep.end():
                c_non_eu = bool(_NON_EU_RE.search(clause))
                c_eu = bool(_EU_DOMESTIC_RE.search(clause))
                if c_non_eu and not c_eu:
                    return "INTERNATIONAL"
                if c_eu and not c_non_eu:
                    return "EU_DOMESTIC"
                break
            pos = m_sep.end()
        else:
            clause = target_text[pos:]
            if pos <= amt.start:
                c_non_eu = bool(_NON_EU_RE.search(clause))
                c_eu = bool(_EU_DOMESTIC_RE.search(clause))
                if c_non_eu and not c_eu:
                    return "INTERNATIONAL"
                if c_eu and not c_non_eu:
                    return "EU_DOMESTIC"

        # 2. Fall back to character-distance proximity to `(amt.start, amt.end)`
        min_non_eu = min(
            _span_distance(amt.start, amt.end, m.start(), m.end()) for m in non_eu_matches
        )
        min_eu = min(_span_distance(amt.start, amt.end, m.start(), m.end()) for m in eu_matches)
        if min_non_eu <= min_eu:
            return "INTERNATIONAL"
        return "EU_DOMESTIC"

    return _audience_from_context(f"{line.heading} | {line.header} | {line.text}")


def _is_application_fee_for_amount(line: Line, amt: Amount, *, from_header: bool = False) -> bool:
    """Return True if `amt` on `line` is an application/processing fee rather than tuition."""
    if line.header and _APPLICATION_FEE_RE.search(line.header) and not (
        _TUITION_WORD_RE.search(line.header)
    ):
        return True
    if (
        not line.header
        and _APPLICATION_FEE_RE.search(line.heading)
        and not _TUITION_WORD_RE.search(line.heading)
    ):
        return True
    target_text = line.header if from_header else line.text
    app_matches = list(_APPLICATION_FEE_RE.finditer(target_text))
    if not app_matches:
        return False
    tuition_matches = list(_TUITION_WORD_RE.finditer(target_text))
    if not tuition_matches:
        return True
    min_app = min(_span_distance(amt.start, amt.end, m.start(), m.end()) for m in app_matches)
    min_tui = min(_span_distance(amt.start, amt.end, m.start(), m.end()) for m in tuition_matches)
    return min_app < min_tui


def _candidates_with_header_currency(lines: Sequence[Line]) -> Candidates:
    """Return `find_all(lines)` augmented with synthesized `Amount` candidates for any
    structured `<table>`/`<dl>` line whose `line.header` carries the currency (e.g.
    `Annual Tuition (EUR)`) and whose `line.text` carries a bare number (`15,000`)."""
    base = find_all(lines)
    lines_with_amounts = {fa.line for fa in base.amounts.values() if not fa.from_header}
    extra_amounts: dict[str, Found[Amount]] = dict(base.amounts)
    for line_idx, line in enumerate(lines):
        if line_idx in lines_with_amounts or not line.header:
            continue
        m_hdr_curr = _HEADER_CURRENCY_RE.search(line.header)
        if not m_hdr_curr or not re.search(r"\d", line.text):
            continue
        curr_tok = m_hdr_curr.group(1)
        for synth in find_amounts(f"{curr_tok} {line.text}"):
            if synth.low is not None and synth.currency:
                num_match = re.search(r"\d[\d.,\s]*", line.text)
                verbatim_txt = num_match.group(0).strip() if num_match else line.text.strip()
                key = f"m{len(extra_amounts) + 1}"
                extra_amounts[key] = Found(
                    line=line_idx,
                    value=replace(
                        synth,
                        text=verbatim_txt,
                        start=num_match.start() if num_match else 0,
                        end=num_match.end() if num_match else len(line.text),
                    ),
                    from_header=False,
                )
    if len(extra_amounts) == len(base.amounts):
        return base
    return replace(base, amounts=extra_amounts)


def _detect_fee_category_ref(
    lines: Sequence[Line], sources: Sequence[str], primary_url: str
) -> str:
    for idx, line in enumerate(lines):
        if primary_url and sources[idx] != primary_url:
            continue
        m = _CATEGORY_REF_RE.search(f"{line.header} {line.text}")
        if m:
            return m.group(1).upper()
    return ""


def _extract_duration_months(lines: Sequence[Line], candidates: Candidates) -> int | None:
    for found_dur in candidates.durations.values():
        dur = found_dur.value
        if dur.months is not None and 6 <= dur.months <= 60:
            return dur.months
        if dur.unit == "semesters" and dur.count is not None and 1 <= dur.count <= 10:
            return dur.count * 6
    for line in lines:
        m_ects = _ECTS_DURATION_RE.search(f"{line.header} {line.text}")
        if m_ects:
            ects_val = int(m_ects.group(1) or m_ects.group(2))
            return 24 if ects_val == 120 else (18 if ects_val == 90 else 12)
    return None


def _extract_teaching_languages(lines: Sequence[Line]) -> list[str]:
    langs_found: list[str] = []
    for line in lines:
        ctx = f"{line.heading} {line.header} {line.text}"
        is_lang_header = bool(
            line.header
            and re.search(
                r"\b(?:language|sprache|langue|lingua)\b",
                line.header,
                re.IGNORECASE,
            )
            and not re.search(
                r"\b(?:requirement|proficiency|certificate|test|score)\b",
                line.header,
                re.IGNORECASE,
            )
        )
        if _TEACHING_CONTEXT_RE.search(ctx) or is_lang_header:
            for lang_name, lang_re in _LANGUAGE_NAMES:
                if lang_re.search(line.text) and lang_name not in langs_found:
                    langs_found.append(lang_name)
    return langs_found


def extract_tier0_programme_facts(
    bundle: ProgrammeBundle,
    *,
    base_profile: InstitutionBaseProfile | None = None,
) -> ProgrammeScrapeResult:
    """Tier 0 deterministic AST & 2D table coordinate extractor ($0.00 LLM cost).

    Extracts unambiguous tuition, application fee, duration, teaching languages,
    hard eligibility (IELTS/TOEFL/CEFR/GPA/ECTS/deadlines), and required document
    statements, while flagging ambiguous or high-risk conditional slots for Tier 1/2.
    """
    section = bundle.section
    lines = section.lines
    sources = bundle.line_sources
    candidates = _candidates_with_header_currency(lines)

    # 1. Detect cross-page fee/tuition category reference on the primary page
    primary_url = bundle.page_urls[0] if bundle.page_urls else ""
    fee_category_ref = _detect_fee_category_ref(lines, sources, primary_url)

    # 2. Duration in months
    duration_months = _extract_duration_months(lines, candidates)

    # 3. Teaching languages
    langs_found = _extract_teaching_languages(lines)

    # 4. Tuition & Application Fees (with 2D Table Header + Cross-Page Category Resolution)
    tuition_specs: list[CostComponentSpec] = []
    app_fee_specs: list[CostComponentSpec] = []
    high_risk_flags: set[str] = set()
    unresolved_slots: set[str] = set()
    has_range_tuition = False

    for found_amt in candidates.amounts.values():
        amt: Amount = found_amt.value
        if amt.low is None or not amt.currency:
            continue
        line_idx = found_amt.line
        line = lines[line_idx]
        src_url = sources[line_idx] if line_idx < len(sources) else primary_url
        context = f"{line.heading} | {line.header} | {line.text}"
        is_structured = bool(line.header)

        # Ignore scholarship/stipend lines and living-cost / deposit estimates
        is_schol_heading = _SCHOLARSHIP_LINK_RE.search(f"{line.heading} {line.header}")
        if is_schol_heading and not _TUITION_WORD_RE.search(f"{line.header} {line.text}"):
            continue
        if _NON_TUITION_COST_RE.search(f"{line.header} {line.text}") and not (
            _TUITION_WORD_RE.search(line.text)
        ):
            continue

        amt_audience = _amount_audience_on_line(line, amt, from_header=found_amt.from_header)

        if _is_application_fee_for_amount(line, amt, from_header=found_amt.from_header):
            if amt.low == amt.high and amt.bound is None:
                quote = locate(amt.text, section) or Quote(amt.text, f"L{line_idx}.text")
                app_fee_specs.append(
                    CostComponentSpec(
                        kind="APPLICATION_FEE",
                        amount=amt.low,
                        currency=amt.currency,
                        period="ONE_OFF",
                        audience=amt_audience,
                        quote=quote,
                        source_url=src_url,
                        from_structured=is_structured,
                    )
                )
            continue

        # Ignore German/French semester union contributions (Semesterbeitrag / CVEC) unless the cell
        # itself explicitly names tuition fees
        is_semester_contrib = _SEMESTER_CONTRIB_RE.search(f"{line.header} {line.text}")
        if is_semester_contrib and not _TUITION_WORD_RE.search(line.text):
            continue

        cat_pattern = (
            rf"\b(?:category|band|tier|tariff)\s+{re.escape(fee_category_ref)}\b"
            if fee_category_ref
            else ""
        )
        matches_cat = bool(cat_pattern and re.search(cat_pattern, context, re.IGNORECASE))
        has_fee_heading = bool(_FEE_HEADING_RE.search(f"{line.heading} {line.header}"))
        if (
            _TUITION_WORD_RE.search(context)
            or has_fee_heading
            or "Schema.org Offer" in line.header
            or matches_cat
        ):
            # If the programme specified a fee category (e.g. Category B) and this row names
            # a DIFFERENT category (e.g. Category A or C), skip it!
            row_cat_match = _CATEGORY_REF_RE.search(f"{line.header} {line.text}")
            if (
                fee_category_ref
                and row_cat_match
                and row_cat_match.group(1).upper() != fee_category_ref
            ):
                continue

            # Range or bound amounts in prose (e.g. "Tuition ranges from EUR 2,500 to EUR 15,000"
            # or "up to EUR 15,000") are not single deterministic tuition figures; defer to exact
            # table/prose figures or Tier 1/2 readers.
            if (
                (amt.high is not None and amt.low != amt.high)
                or amt.bound is not None
                or (not is_structured and _RANGE_PROSE_RE.search(line.text))
            ):
                has_range_tuition = True
                continue

            raw_period = _period_from_context(context)
            if raw_period == "PER_CREDIT":
                # Non-ECTS per-credit fee (e.g. US credit hours): defer to Tier 1/2 rather than
                # misrecording 1 credit's price as the full annual tuition.
                unresolved_slots.add("tuition")
                continue
            amount_val, norm_period = _normalize_tuition_amount_and_period(amt.low, raw_period)

            quote = locate(amt.text, section) or Quote(amt.text, f"L{line_idx}.text")
            tuition_specs.append(
                CostComponentSpec(
                    kind="TUITION",
                    amount=amount_val,
                    currency=amt.currency,
                    period=norm_period,
                    audience=amt_audience,
                    quote=quote,
                    source_url=src_url,
                    from_structured=is_structured,
                )
            )

    # Check for explicit tuition-free statements when no positive international tuition was found
    if not any(t.audience in ("INTERNATIONAL", "ALL") for t in tuition_specs):
        for idx, line in enumerate(lines):
            context = f"{line.heading} | {line.header} | {line.text}"
            m_free = _FREE_TUITION_RE.search(line.text)
            if m_free:
                src_url = sources[idx] if idx < len(sources) else primary_url
                quote = locate(m_free.group(0), section) or Quote(m_free.group(0), f"L{idx}.text")
                free_aud = _audience_from_context(context)
                if _CONDITIONAL_GUARD_RE.search(context) or free_aud == "EU_DOMESTIC":
                    high_risk_flags.add("conditional_free_tuition")
                    unresolved_slots.add("tuition")
                else:
                    tuition_specs.append(
                        CostComponentSpec(
                            kind="TUITION",
                            amount=Decimal("0.00"),
                            currency="EUR",
                            period="ANNUAL",
                            audience=free_aud,
                            quote=quote,
                            source_url=src_url,
                            from_structured=bool(line.header),
                        )
                    )
                break

    # Inherit from InstitutionBaseProfile when international/general tuition or app fee is missing
    has_intl_or_all = any(t.audience in ("INTERNATIONAL", "ALL") for t in tuition_specs)
    if not has_intl_or_all and base_profile is not None:
        if fee_category_ref and fee_category_ref in base_profile.tuition_by_category:
            tuition_specs.append(base_profile.tuition_by_category[fee_category_ref])
        elif base_profile.default_tuition is not None:
            tuition_specs.append(base_profile.default_tuition)
    if not app_fee_specs and base_profile is not None and base_profile.application_fee is not None:
        app_fee_specs.append(base_profile.application_fee)

    # Select canonical tuition (prefer INTERNATIONAL, else ALL; prefer 2D structured over prose)
    selected_costs: list[CostComponentSpec] = []
    intl_tuition = [t for t in tuition_specs if t.audience == "INTERNATIONAL"]
    all_tuition = [t for t in tuition_specs if t.audience == "ALL"]
    chosen_tuition_pool = intl_tuition or all_tuition
    if chosen_tuition_pool:
        structured_pool = [t for t in chosen_tuition_pool if t.from_structured]
        preferred_pool = structured_pool or chosen_tuition_pool
        distinct_amounts = {(t.amount, t.currency) for t in preferred_pool}
        if len(distinct_amounts) > 1:
            unresolved_slots.add("tuition")
        selected_costs.append(preferred_pool[0])
    else:
        unresolved_slots.add("tuition")
        if has_range_tuition:
            high_risk_flags.add("range_tuition")

    if app_fee_specs:
        intl_app = [a for a in app_fee_specs if a.audience == "INTERNATIONAL"]
        all_app = [a for a in app_fee_specs if a.audience == "ALL"]
        selected_costs.append((intl_app or all_app or app_fee_specs)[0])

    # 5. Hard Eligibility (Language tests, CEFR, Grade/GPA, Deadlines — from text, header, and
    #    header+cell pairs when a <table> or <dl> splits the test/GPA name and score)
    eligibility_specs: list[EligibilitySpec] = []
    seen_elig: set[tuple[str, str]] = set()

    def _record_req(req: Requirement, line_idx: int, quote_str: str) -> None:
        src_url = sources[line_idx] if line_idx < len(sources) else primary_url
        quote = locate(quote_str, section) or Quote(quote_str, f"L{line_idx}.text")
        if req.kind == "language_test" and req.test and req.score is not None:
            key = ("LANGUAGE", f"{req.test}:{req.score}")
            if key not in seen_elig:
                seen_elig.add(key)
                eligibility_specs.append(
                    EligibilitySpec(
                        kind="LANGUAGE",
                        label=req.test,
                        value=str(req.score),
                        quote=quote,
                        source_url=src_url,
                    )
                )
        elif req.kind == "cefr" and req.cefr:
            key = ("LANGUAGE", f"CEFR:{req.cefr}")
            if key not in seen_elig:
                seen_elig.add(key)
                eligibility_specs.append(
                    EligibilitySpec(
                        kind="LANGUAGE",
                        label="CEFR",
                        value=req.cefr,
                        quote=quote,
                        source_url=src_url,
                    )
                )
        elif req.kind == "grade" and req.score is not None:
            scale_str = f"/{req.scale}" if req.scale is not None else ""
            val_str = f"{req.score}{scale_str}"
            key = ("GRADE", val_str)
            if key not in seen_elig:
                seen_elig.add(key)
                eligibility_specs.append(
                    EligibilitySpec(
                        kind="GRADE",
                        label="Minimum Grade / GPA",
                        value=val_str,
                        quote=quote,
                        source_url=src_url,
                    )
                )

    for found_req in candidates.requirements.values():
        _record_req(found_req.value, found_req.line, found_req.value.text)

    for line_idx, line in enumerate(lines):
        if not line.header:
            continue
        header_parts = [p.strip() for p in line.header.split("|") if p.strip()]
        probe_strings = [
            *(f"{part} {line.text}" for part in header_parts),
            re.sub(r"[|:]", " ", f"{line.header} {line.text}"),
        ]
        for probe in probe_strings:
            for req in find_requirements(probe):
                _record_req(req, line_idx, line.text)

    # Deadlines from candidates.dates
    deadline_specs: list[EligibilitySpec] = []
    for found_date in candidates.dates.values():
        d: Date = found_date.value
        line_idx = found_date.line
        line = lines[line_idx]
        context = f"{line.heading} | {line.header} | {line.text}"
        if not _DEADLINE_CONTEXT_RE.search(context):
            continue
        if d.month is None:
            continue
        src_url = sources[line_idx] if line_idx < len(sources) else primary_url
        quote = locate(d.text, section) or Quote(d.text, f"L{line_idx}.text")
        if d.year is not None:
            resolved_year = d.year
        else:
            from apps.funding.validity import intake_start_years

            ctx_years = intake_start_years(context)
            today_dt = dt.date.today()
            default_intake_yr = today_dt.year + 1 if today_dt.month >= 6 else today_dt.year
            intake_yr = min(ctx_years) if ctx_years else default_intake_yr
            resolved_year = intake_yr - 1 if d.month >= 9 else intake_yr
        iso_str = f"{resolved_year:04d}-{d.month:02d}-{d.day or 1:02d}"
        deadline_specs.append(
            EligibilitySpec(
                kind="DEADLINE",
                label="Application Deadline",
                value=iso_str,
                quote=quote,
                source_url=src_url,
                audience=_audience_from_context(context),
            )
        )
    if deadline_specs:
        intl_dl = [dl for dl in deadline_specs if dl.audience == "INTERNATIONAL"]
        all_dl = [dl for dl in deadline_specs if dl.audience == "ALL"]
        eligibility_specs.append((intl_dl or all_dl or deadline_specs)[0])
    elif base_profile is not None and base_profile.default_deadline is not None:
        eligibility_specs.append(base_profile.default_deadline)

    if not any(e.kind == "LANGUAGE" for e in eligibility_specs) and base_profile is not None:
        eligibility_specs.extend(base_profile.language_requirements)

    # 6. Required Documents, CV format, Motivation Letter, and Referee rules
    statements: list[DocumentStatementSpec] = []
    seen_stmt_texts: set[str] = set()
    cv_format = "any"
    cv_format_source_url = ""
    letter_required = "unknown"
    cv_constraints: list[dict[str, object]] = []
    seen_cv_keys: set[str] = set()
    cv_directives: list[dict[str, object]] = []
    seen_directives: set[tuple[str, str]] = set()
    file_rules: list[dict[str, object]] = []
    seen_file_rules: set[tuple[str, str]] = set()
    referee_reqs: list[dict[str, object]] = []
    portfolio_led = False

    def _add_cv_constraint(key: str, val: object, line_text: str, s_url: str, l_idx: int) -> None:
        if key in seen_cv_keys:
            return
        seen_cv_keys.add(key)
        cv_constraints.append(
            {
                "rule_id": f"PAGE-{l_idx}-{key}"[:20],
                "key": key,
                "value": val,
                "enforcement": "ADVISORY_HIGH_RISK",
                "rule_text": line_text[:1000],
                "source_url": s_url,
                "scope": "PROGRAMME",
            }
        )

    def _add_file_rule(
        doc_kind: str, field_name: str, val: object, line_text: str, s_url: str
    ) -> None:
        key = (doc_kind, field_name)
        if key in seen_file_rules:
            return
        seen_file_rules.add(key)
        file_rules.append(
            {
                "document": doc_kind,
                "field": field_name,
                "value": val,
                "conditional": False,
                "condition": "",
                "rule_text": line_text[:1000],
                "source_url": s_url,
            }
        )

    def _add_stmt(
        kind: Literal["DOCUMENT", "FORMAT", "COMPETENCY", "LANGUAGE", "OTHER"],
        req_level: Literal["REQUIRED", "DESIRED"],
        label: str,
        line_obj: Line,
        idx: int,
    ) -> None:
        norm = " ".join(line_obj.text.casefold().split())
        if norm in seen_stmt_texts or len(line_obj.text) < 4:
            return
        seen_stmt_texts.add(norm)
        src_url = sources[idx] if idx < len(sources) else primary_url
        eff_label = (
            f"{label} ({line_obj.header})"
            if line_obj.header and line_obj.header.lower() not in label.lower()
            else label
        )[:200]
        q = locate(line_obj.text, section) or Quote(line_obj.text, f"L{idx}.text")
        statements.append(
            DocumentStatementSpec(
                kind=kind,
                requirement=req_level,
                label=eff_label,
                text=line_obj.text[:1000],
                quote=q,
                source_url=src_url,
            )
        )

    for idx, line in enumerate(lines):
        combined_line = f"{line.header} {line.text}"
        src_url = sources[idx] if idx < len(sources) else primary_url
        is_third_party = bool(_THIRD_PARTY_RE.search(combined_line))

        if _CV_LINE_RE.search(combined_line):
            if not is_third_party:
                if _EUROPASS_REQ_RE.search(combined_line):
                    cv_format = "europass_required"
                    cv_format_source_url = src_url
                elif _EUROPASS_PREF_RE.search(combined_line) and cv_format == "any":
                    cv_format = "europass_preferred"
                    cv_format_source_url = src_url
                elif not cv_format_source_url:
                    cv_format_source_url = src_url

                m_pages = _CV_MAX_PAGES_RE.search(combined_line)
                if m_pages:
                    raw_p = int(m_pages.group(1) or m_pages.group(2))
                    if 1 <= raw_p <= 20:
                        _add_cv_constraint("max_pages", raw_p, line.text, src_url, idx)

                m_mb = _FILE_MB_RE.search(combined_line)
                if m_mb:
                    mb_val = float(m_mb.group(1))
                    if 0.1 <= mb_val <= 100:
                        bytes_val = int(mb_val * 1_000_000)
                        _add_cv_constraint("max_bytes", bytes_val, line.text, src_url, idx)
                        _add_file_rule("CV", "max_bytes", bytes_val, line.text, src_url)

                if _PHOTO_FORBIDDEN_RE.search(combined_line):
                    _add_cv_constraint("photo_allowed", False, line.text, src_url, idx)
                elif _PHOTO_REQUIRED_RE.search(combined_line):
                    _add_cv_constraint("photo_required", True, line.text, src_url, idx)

                if _DOB_FORBIDDEN_RE.search(combined_line):
                    _add_cv_constraint("date_of_birth_allowed", False, line.text, src_url, idx)
                if _CV_SIGNED_RE.search(combined_line):
                    _add_cv_constraint("signature_required", True, line.text, src_url, idx)
                if _CV_NO_GAPS_RE.search(combined_line):
                    _add_cv_constraint("no_unexplained_gaps", 2, line.text, src_url, idx)

                if (
                    _REVERSE_CHRONO_RE.search(combined_line)
                    and ("order", "cv") not in seen_directives
                ):
                    seen_directives.add(("order", "cv"))
                    cv_directives.append(
                        {
                            "action": "order",
                            "target": "cv",
                            "value": "reverse_chronological",
                            "rule_text": line.text[:1000],
                            "source_url": src_url,
                        }
                    )
                elif _CHRONO_RE.search(combined_line) and ("order", "cv") not in seen_directives:
                    seen_directives.add(("order", "cv"))
                    cv_directives.append(
                        {
                            "action": "order",
                            "target": "cv",
                            "value": "chronological",
                            "rule_text": line.text[:1000],
                            "source_url": src_url,
                        }
                    )

                if _PDF_FORMAT_RE.search(combined_line):
                    _add_file_rule("CV", "format", "PDF", line.text, src_url)

            _add_stmt("DOCUMENT", "REQUIRED", "Curriculum Vitae (CV)", line, idx)

        if _LETTER_LINE_RE.search(combined_line):
            if _NOT_REQUIRED_RE.search(combined_line):
                if letter_required == "unknown":
                    letter_required = "not_requested"
            else:
                is_opt = bool(_LETTER_OPTIONAL_RE.search(combined_line))
                if letter_required == "unknown" or not is_opt:
                    letter_required = "optional" if is_opt else "required"
                if _PDF_FORMAT_RE.search(combined_line):
                    _add_file_rule("MOTIVATION_LETTER", "format", "PDF", line.text, src_url)
                m_mb_let = _FILE_MB_RE.search(combined_line)
                if m_mb_let:
                    mb_val = float(m_mb_let.group(1))
                    if 0.1 <= mb_val <= 100:
                        _add_file_rule(
                            "MOTIVATION_LETTER",
                            "max_bytes",
                            int(mb_val * 1_000_000),
                            line.text,
                            src_url,
                        )
                _add_stmt(
                    "DOCUMENT",
                    "DESIRED" if is_opt else "REQUIRED",
                    "Motivation Letter",
                    line,
                    idx,
                )

        if _REFEREE_LINE_RE.search(combined_line):
            if _NOT_REQUIRED_RE.search(combined_line):
                if not any(r.get("field") == "count" for r in referee_reqs):
                    referee_reqs.append(
                        {
                            "field": "count",
                            "value": "NONE_REQUIRED",
                            "date": "",
                            "conditional": False,
                            "condition": "",
                            "rule_text": line.text[:500],
                            "source_url": src_url,
                        }
                    )
            else:
                m_cnt = _REFEREE_COUNT_RE.search(combined_line)
                cnt_val = _WORD_NUM.get(m_cnt.group(1).lower(), "TWO") if m_cnt else "TWO"
                if not any(r.get("field") == "count" for r in referee_reqs):
                    referee_reqs.append(
                        {
                            "field": "count",
                            "value": cnt_val,
                            "date": "",
                            "conditional": False,
                            "condition": "",
                            "rule_text": line.text[:500],
                            "source_url": src_url,
                        }
                    )
                if _REFEREE_ACADEMIC_RE.search(combined_line) and not any(
                    r.get("field") == "kind" for r in referee_reqs
                ):
                    referee_reqs.append(
                        {
                            "field": "kind",
                            "value": "ACADEMIC",
                            "date": "",
                            "conditional": False,
                            "condition": "",
                            "rule_text": line.text[:500],
                            "source_url": src_url,
                        }
                    )
                if _REFEREE_INST_EMAIL_RE.search(combined_line) and not any(
                    r.get("field") == "institutional_email_required" for r in referee_reqs
                ):
                    referee_reqs.append(
                        {
                            "field": "institutional_email_required",
                            "value": "YES",
                            "date": "",
                            "conditional": False,
                            "condition": "",
                            "rule_text": line.text[:500],
                            "source_url": src_url,
                        }
                    )
                _add_stmt("DOCUMENT", "REQUIRED", "Reference Letters", line, idx)

        if _TRANSCRIPT_LINE_RE.search(combined_line):
            if _PDF_FORMAT_RE.search(combined_line):
                _add_file_rule("TRANSCRIPT", "format", "PDF", line.text, src_url)
            _add_stmt("DOCUMENT", "REQUIRED", "Academic Transcripts", line, idx)

        if _SINGLE_PDF_BUNDLE_RE.search(combined_line):
            _add_file_rule("EVERY_DOCUMENT", "combine", "ONE_FILE", line.text, src_url)
            _add_file_rule("EVERY_DOCUMENT", "format", "PDF", line.text, src_url)
            m_mb_all = _FILE_MB_RE.search(combined_line)
            if m_mb_all:
                mb_val = float(m_mb_all.group(1))
                if 0.1 <= mb_val <= 100:
                    _add_file_rule(
                        "EVERY_DOCUMENT", "max_bytes", int(mb_val * 1_000_000), line.text, src_url
                    )

        if _PORTFOLIO_LINE_RE.search(combined_line):
            portfolio_led = True
            _add_stmt("DOCUMENT", "REQUIRED", "Portfolio", line, idx)

        if _APS_LINE_RE.search(combined_line):
            _add_stmt("DOCUMENT", "REQUIRED", "APS Certificate", line, idx)

        if _GRE_GMAT_LINE_RE.search(combined_line):
            is_opt = bool(_LETTER_OPTIONAL_RE.search(combined_line))
            _add_stmt(
                "COMPETENCY",
                "DESIRED" if is_opt else "REQUIRED",
                "GRE / GMAT",
                line,
                idx,
            )

        from apps.funding.transcript_eligibility import (
            is_scraper_competency_statement,
            parse_scholarship_status_statement,
            parse_subject_pool_rule,
        )

        if parse_scholarship_status_statement(line.text) is not None:
            _add_stmt("OTHER", "REQUIRED", "Scholarship / Funding Status", line, idx)

        if is_scraper_competency_statement(line.text):
            label_comp = (
                "Subject Credit Requirement"
                if parse_subject_pool_rule(line.text) is not None
                else "Academic Admission Requirement"
            )
            _add_stmt("COMPETENCY", "REQUIRED", label_comp, line, idx)
        elif line.header and parse_subject_pool_rule(f"{line.header}: {line.text}") is not None:
            table_stmt_text = f"{line.header}: {line.text}"[:1000]
            norm_tbl = " ".join(table_stmt_text.casefold().split())
            if norm_tbl not in seen_stmt_texts:
                seen_stmt_texts.add(norm_tbl)
                q_tbl = locate(line.text, section) or Quote(line.text, f"L{idx}.text")
                statements.append(
                    DocumentStatementSpec(
                        kind="COMPETENCY",
                        requirement="REQUIRED",
                        label=f"Subject Credit Requirement ({line.header})"[:200],
                        text=table_stmt_text,
                        quote=q_tbl,
                        source_url=src_url,
                    )
                )

    for elig in eligibility_specs:
        if elig.kind in ("LANGUAGE", "GRADE", "ECTS"):
            stmt_kind: Literal["LANGUAGE", "COMPETENCY"] = (
                "LANGUAGE" if elig.kind == "LANGUAGE" else "COMPETENCY"
            )
            stmt_text = elig.quote.text[:1000]
            norm_elig = " ".join(stmt_text.casefold().split())
            if norm_elig not in seen_stmt_texts:
                seen_stmt_texts.add(norm_elig)
                statements.append(
                    DocumentStatementSpec(
                        kind=stmt_kind,
                        requirement="REQUIRED",
                        label=elig.label,
                        text=stmt_text,
                        quote=elig.quote,
                        source_url=elig.source_url,
                    )
                )

    if not statements and base_profile is not None and base_profile.document_statements:
        statements.extend(base_profile.document_statements)

    return ProgrammeScrapeResult(
        duration_months=duration_months,
        teaching_languages=tuple(langs_found),
        costs=tuple(selected_costs),
        eligibility=tuple(eligibility_specs),
        statements=tuple(statements),
        cv_format=cv_format,
        cv_format_source_url=cv_format_source_url,
        letter_required=letter_required,
        cv_constraints=tuple(cv_constraints),
        cv_directives=tuple(cv_directives),
        file_rules=tuple(file_rules),
        referee_requirements=tuple(referee_reqs),
        portfolio_led=portfolio_led,
        fee_category_ref=fee_category_ref,
        unresolved_slots=frozenset(unresolved_slots),
        high_risk_flags=frozenset(high_risk_flags),
    )




__all__ = [
    "_amount_audience_on_line",
    "_audience_from_context",
    "_candidates_with_header_currency",
    "_is_application_fee_for_amount",
    "_period_from_context",
    "_span_distance",
    "extract_tier0_programme_facts",
]
