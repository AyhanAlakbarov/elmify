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

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast

from apps.accounts.schemas import EvaluationDimension, StudentProfileSnapshot
from apps.funding.card import award_card
from apps.funding.evaluation import (
    _UPSTREAM_DIMENSIONS,
    ApplicantConditionFact,
    AwardCandidateFacts,
    BenefitFact,
    CandidateFacts,
    CostLineItem,
    ReturnServiceFact,
    duration_category,
)
from apps.funding.fx import round_money
from apps.funding.models import (
    BenefitRule,
    CostComponent,
    FundingBenefit,
    FundingOpportunity,
    Program,
    ProgramStatement,
)
from apps.funding.regions import REGIONS
from apps.funding.transcript_eligibility import (
    evaluate_program_statement,
    is_coursework_or_credit_statement,
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

_PCT_WAIVER_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
_ACADEMIC_MONTHS_PER_YEAR_RE = re.compile(
    r"\b([89]|1[01])\s+(?:academic\s+)?months?\s+(?:per|a|each)\s+(?:academic\s+)?year\b",
    re.IGNORECASE,
)


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
    span_months = min(award_months, programme_months)
    if benefit.period == "MONTHLY":
        m_acad = _ACADEMIC_MONTHS_PER_YEAR_RE.search(
            f"{benefit.description} {benefit.amount_quote} {benefit.amount_text}"
        )
        if m_acad:
            acad_m = int(m_acad.group(1))
            effective_months = (span_months // 12) * acad_m + min(span_months % 12, acad_m)
        else:
            effective_months = span_months
        total = round_money(benefit.amount * Decimal(effective_months))
    else:
        total = round_money((benefit.amount / Decimal(12)) * Decimal(span_months))
    return total, benefit.currency, "FULL_PROGRAM"


def _tuition_total(
    costs: Sequence[CostComponent], programme_months: int
) -> tuple[Decimal, str] | None:
    """Single-currency total tuition cost over the programme's length, or None."""
    from apps.funding.affordability import _normalize_to_program_total

    tuition_costs = [c for c in costs if c.kind == "TUITION"]
    if not tuition_costs:
        return None
    currencies = {c.currency for c in tuition_costs if c.currency}
    if len(currencies) != 1:
        return None
    currency = next(iter(currencies))
    total = sum(
        (
            _normalize_to_program_total(cost.amount, cost.period, programme_months)
            for cost in tuition_costs
        ),
        Decimal("0.00"),
    )
    return (round_money(total), currency) if total > 0 else None


def _benefit_facts(
    benefits: Sequence[FundingBenefit],
    routes: Mapping[object, str] | None = None,
    *,
    durations: Mapping[object, int | None] | None = None,
    programme_months: int | None = None,
    tuition_levels: Mapping[object, str] | None = None,
    tuition_total: tuple[Decimal, str] | None = None,
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
        if amount is None and benefit.kind == "TUITION" and tuition_total is not None:
            t_level = (tuition_levels or {}).get(benefit.opportunity_id)
            if t_level == "FULL":
                amount, currency, period = tuition_total[0], tuition_total[1], "FULL_PROGRAM"
            elif benefit.amount_bound in ("", "EXACT") and (
                t_level == "PARTIAL" or "%" in (benefit.amount_text or "")
            ):
                m_pct = _PCT_WAIVER_RE.search(f"{benefit.amount_text} {benefit.description}")
                if m_pct:
                    pct = Decimal(m_pct.group(1))
                    if Decimal(0) < pct <= Decimal(100):
                        amount = round_money(tuition_total[0] * pct / Decimal(100))
                        currency = tuition_total[1]
                        period = "FULL_PROGRAM"
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
        or (rule.kind == BenefitRule.Kind.ELIGIBILITY and bool(rule.key))
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


def _nationality_condition(
    award: FundingOpportunity,
    published: Sequence[ApplicantConditionFact] = (),
    *,
    country_code: str = "",
) -> tuple[ApplicantConditionFact, ...]:
    """A shape with no list: a condition nothing can decide, never an empty set.

    The reader records THAT a page restricts by nationality (`nationality_shape`)
    and not WHICH countries. An empty country list would read as "matches
    nobody" and quietly shut every route; a list guessed from the holder's own
    country would be worse. Undecidable is the honest answer, and it reaches a
    consultant with the award's own words.

    When `internationals_included == "NO"`, the page explicitly excludes
    international students; if the award's domestic `country_code` is known,
    it restricts `CITIZENSHIP` to that country, and if unknown it yields an
    undecidable `CITIZENSHIP` condition for consultant review.

    A shape the readings split on is blanked to UNSTATED and named in
    `unconfirmed`, so it never gets here -- turning a disagreement into an
    eligibility bar is the silent exclusion tiered agreement exists to prevent.
    """
    if any(condition.key == "CITIZENSHIP" for condition in published):
        return ()
    if award.internationals_included == "NO":
        clean_cc = (country_code or "").strip().upper()
        return (
            ApplicantConditionFact(
                benefit_id=str(award.id),
                condition_type="WORK_EXPERIENCE",
                key="CITIZENSHIP",
                operator="IN",
                value=clean_cc,
                rule_text=(
                    f"{award.holder_name or award.name} excludes international students "
                    f"(domestic {clean_cc} applicants only)."
                    if clean_cc
                    else (
                        f"{award.holder_name or award.name} excludes international students; "
                        "the domestic country was not recorded, so a consultant must confirm it."
                    )
                ),
            ),
        )
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
    pays_for_program_ids: frozenset[str] = frozenset(),
    country_code: str = "",
    evidence: Evidence | None = None,
) -> AwardCandidateFacts:
    """One served HOLDER award, as the gates read it.

    `benefits` and `rules` are the award's own rows, fetched by the caller, and
    so are the links `scheme_pays_for` reads: the programme ids it names and
    its country (the holder's, for a HOLDER award -- the page's own proxy).
    """
    published = _condition_facts(rules)
    default_evidence = Evidence(
        offered="NO" if award.suspension_quote else "YES",
        applies_to=award.suspended_for or "UNSTATED",
        contrary_intake=award.suspended_for,
    )
    return AwardCandidateFacts(
        award_id=str(award.id),
        name=award.name,
        holder_name=award.holder_name,
        organisation_id=str(award.organisation_id) if award.organisation_id else "",
        money_form=award.money_form,
        route=award.route,
        unconfirmed=tuple(part for part in award.unconfirmed.split(";") if part),
        benefits=_benefit_facts(benefits),
        applicant_conditions=(
            *published,
            *_nationality_condition(award, published, country_code=country_code),
        ),
        return_service=_return_service_facts(rules),
        # An UNAGREED row is not evidence a student acts on -- P1-6's gate
        # excludes LOW before a candidate ever enters a pack's pool. A row
        # agreed on existence with a detail unconfirmed is NOT low: that is
        # exactly what tiered agreement decided to keep showing.
        evidence_confidence="LOW" if award.agreement != "AGREED" else "MEDIUM",
        # Uses the caller-provided FundingCycleVerification evidence when
        # present, falling back to Step-0 evidence on the opportunity row.
        evidence=evidence if evidence is not None else default_evidence,
        coverage_is_unstated=not benefits,
        card=award_card(award, benefits),
        scope=award.scope_type,
        institution_id=str(award.institution_id) if award.institution_id else "",
        country_code=country_code,
        pays_for_program_ids=pays_for_program_ids,
    )


_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "degree",
        "for",
        "from",
        "in",
        "into",
        "ma",
        "master",
        "masters",
        "meng",
        "msc",
        "of",
        "on",
        "or",
        "program",
        "programme",
        "studies",
        "the",
        "to",
        "with",
    }
)


def _subject_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) >= 2 and token not in _STOP_WORDS
    )


def _phrase_in_text(text_cf: str, phrase: str) -> bool:
    cleaned = phrase.strip().casefold()
    if not cleaned:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(cleaned)}(?![a-z0-9])", text_cf))


def score_program_fit(
    program: Program,
    profile: StudentProfileSnapshot,
    *,
    statements: Sequence[ProgramStatement] = (),
    today: date | None = None,
) -> dict[EvaluationDimension, Decimal]:
    """Deterministic, zero-query fit scoring across `_UPSTREAM_DIMENSIONS`."""
    from apps.accounts.field_taxonomy import resolve_field_taxonomy

    program_name_cf = program.name.casefold()
    program_tokens = _subject_tokens(program.name)
    target_tokens = _subject_tokens(profile.target_field)
    resolution = resolve_field_taxonomy(profile.target_field, profile.research_interests)
    canonical_matches = any(
        _phrase_in_text(program_name_cf, title)
        or (_subject_tokens(title) and _subject_tokens(title) <= program_tokens)
        for title in resolution.canonical_degree_titles
    )
    preferred_match = any(
        _phrase_in_text(program_name_cf, kw) for kw in resolution.preferred_track_keywords
    )
    secondary_match = any(
        _phrase_in_text(program_name_cf, kw) for kw in resolution.secondary_track_keywords
    )
    parent_match = any(
        _phrase_in_text(program_name_cf, parent) for parent in resolution.parent_fields
    )

    if not target_tokens:
        program_fit = _NEUTRAL
    elif (
        _phrase_in_text(program_name_cf, profile.target_field)
        or target_tokens <= program_tokens
        or canonical_matches
        or (parent_match and preferred_match)
    ):
        if resolution.is_ambiguous_or_interdisciplinary:
            if preferred_match:
                program_fit = Decimal("95")
            elif secondary_match:
                program_fit = Decimal("82")
            else:
                program_fit = Decimal("90")
        else:
            program_fit = Decimal("90")
    elif parent_match and secondary_match:
        program_fit = Decimal("80")
    elif parent_match:
        program_fit = Decimal("70")
    else:
        overlap = len(target_tokens & program_tokens)
        if overlap == 0:
            program_fit = Decimal("40")
        else:
            program_fit = Decimal("60") + round_money(
                Decimal("30") * Decimal(overlap) / Decimal(len(target_tokens))
            )

    prior_token_sets: list[frozenset[str]] = []
    for record in profile.academic_history:
        prior_res = resolve_field_taxonomy(record.field)
        prior_token_sets.append(_subject_tokens(record.field))
        for syn in (*prior_res.canonical_degree_titles, *prior_res.parent_fields):
            prior_token_sets.append(_subject_tokens(syn))
    prior_tokens = frozenset().union(*prior_token_sets) if prior_token_sets else frozenset()

    expanded_target_tokens = frozenset().union(
        target_tokens,
        *(_subject_tokens(t) for t in resolution.canonical_degree_titles),
        *(_subject_tokens(p) for p in resolution.parent_fields),
    )
    prog_res = resolve_field_taxonomy(program.name)
    expanded_program_tokens = frozenset().union(
        program_tokens,
        *(_subject_tokens(t) for t in prog_res.canonical_degree_titles),
        *(_subject_tokens(p) for p in prog_res.parent_fields),
    )
    if prior_tokens and (
        prior_tokens & expanded_program_tokens or prior_tokens & expanded_target_tokens
    ):
        academic_fit = Decimal("85")
    else:
        academic_fit = Decimal("65")
    taught = {lang.casefold() for lang in program.teaching_languages}
    accepted = {lang.casefold() for lang in profile.acceptable_teaching_languages}
    evidenced = {item.language.casefold() for item in profile.language_evidence}
    if taught & (accepted | evidenced):
        academic_fit = min(Decimal("95"), academic_fit + Decimal("5"))

    if statements:
        subject_outcomes = [
            evaluate_program_statement(
                stmt.text,
                profile,
                kind=stmt.kind,
                as_of=today,
                only_coursework=True,
            ).outcome
            for stmt in statements
            if stmt.requirement == "REQUIRED"
            and stmt.kind in ("COMPETENCY", "LANGUAGE", "OTHER")
            and is_coursework_or_credit_statement(stmt.text)
        ]
        if subject_outcomes:
            if "FAILED" in subject_outcomes:
                academic_fit = max(Decimal("0"), academic_fit - Decimal("15"))
            elif any(o in ("BORDERLINE", "CONDITIONAL_BRIDGE") for o in subject_outcomes):
                academic_fit = max(Decimal("0"), academic_fit - Decimal("5"))
            elif all(o == "SATISFIED" for o in subject_outcomes):
                academic_fit = min(Decimal("95"), academic_fit + Decimal("5"))

    if profile.career_intent == "PHD":
        is_research = (
            getattr(program, "academic_track", "") == "research" or "research" in program_tokens
        )
        career_fit = Decimal("90") if is_research else Decimal("75")
    elif program_fit >= Decimal("60"):
        has_experience = bool(profile.experience and any(r.months > 0 for r in profile.experience))
        career_fit = Decimal("85") if has_experience else Decimal("80")
    else:
        career_fit = Decimal("50")

    category = duration_category(program.duration_months)
    if profile.duration_preference == "NONE" or category == profile.duration_preference:
        duration_score = Decimal("90")
    elif profile.duration_flexibility == "WEIGHTED":
        justifications = set(profile.longer_program_justifications or ())
        has_research_track = (
            getattr(program, "academic_track", "") == "research" or "research" in program_tokens
        )
        has_internship_track = bool(
            program_tokens
            & {
                "internship",
                "industrial",
                "industry",
                "placement",
                "applied",
                "coop",
                "practicum",
            }
        )
        if category == "TWO_YEAR" and (
            ("RESEARCH" in justifications and has_research_track)
            or ("INTERNSHIP" in justifications and has_internship_track)
        ):
            duration_score = Decimal("85")
        else:
            duration_score = Decimal("65")
    else:
        duration_score = Decimal("40")

    _post_study_work_countries = frozenset(REGIONS["EEA"].countries) | {
        "CH", "GB", "CA", "AU", "NZ", "US", "JP", "KR", "SG", "AE", "TW",
    }
    priorities = {item.casefold() for item in profile.mobility_priorities}
    country_cf = program.country_code.casefold()
    city_cf = (program.city or "").casefold()
    if (
        program.country_code in profile.allowed_countries
        or country_cf in priorities
        or (city_cf and city_cf in priorities)
        or (
            "post_study_work" in priorities
            and program.country_code in _post_study_work_countries
        )
    ):
        mobility_fit = Decimal("90")
    elif not profile.allowed_countries and not profile.mobility_priorities:
        mobility_fit = Decimal("80")
    else:
        mobility_fit = Decimal("65")

    if not profile.research_interests and not resolution.is_ambiguous_or_interdisciplinary:
        research_fit = Decimal("80")
    elif profile.research_interests:
        interest_tokens = frozenset().union(
            *(_subject_tokens(interest) for interest in profile.research_interests)
        )
        target_only_res = resolve_field_taxonomy(profile.target_field)
        target_family = {
            profile.target_field.casefold(),
            *(p.casefold() for p in target_only_res.parent_fields),
            *(t.casefold() for t in target_only_res.canonical_degree_titles),
            *(k.casefold() for k in resolution.preferred_track_keywords),
        }
        shares_domain = any(
            bool(
                target_family
                & {
                    interest.casefold(),
                    *(p.casefold() for p in int_res.parent_fields),
                    *(t.casefold() for t in int_res.canonical_degree_titles),
                }
            )
            for interest in profile.research_interests
            for int_res in (resolve_field_taxonomy(interest),)
        )
        if interest_tokens & program_tokens:
            research_fit = Decimal("90") if preferred_match else Decimal("85")
        elif (
            resolution.is_ambiguous_or_interdisciplinary
            and preferred_match
            and (
                interest_tokens
                & frozenset(_subject_tokens(" ".join(resolution.preferred_track_keywords)))
            )
        ):
            research_fit = Decimal("85")
        elif (
            program_fit >= Decimal("85")
            and not secondary_match
            and (interest_tokens & target_tokens or shares_domain)
        ):
            research_fit = Decimal("75")
        else:
            research_fit = Decimal("50")
    else:
        if preferred_match:
            research_fit = Decimal("90")
        elif secondary_match:
            research_fit = Decimal("75")
        else:
            research_fit = Decimal("80")

    return {
        "ACADEMIC_FIT": academic_fit,
        "PROGRAM_FIT": program_fit,
        "CAREER_FIT": career_fit,
        "DURATION": duration_score,
        "MOBILITY_FIT": mobility_fit,
        "RESEARCH_FIT": research_fit,
    }


def program_facts(
    program: Program,
    *,
    costs: Sequence[CostComponent],
    benefits: Sequence[FundingBenefit],
    rules: Sequence[BenefitRule],
    routes: Mapping[object, str] | None = None,
    durations: Mapping[object, int | None] | None = None,
    tuition_levels: Mapping[object, str] | None = None,
    profile: StudentProfileSnapshot | None = None,
    statements: Sequence[ProgramStatement] = (),
    today: date | None = None,
    application_deadline: date | None = None,
    scholarship_decision_deadline: date | None = None,
) -> CandidateFacts:
    """One catalog programme as `CandidateFacts`, with nothing invented.

    `CandidateFacts` is unchanged by this slice, so today's HARD_GATES and their
    tests are untouched. The rejected alternative was an optional `program_id`
    on one shared fact type, which needs an `if` in every programme gate -- and
    a gate that silently skips is worse than a crash in this repo.
    """
    scores = (
        score_program_fit(program, profile, statements=statements, today=today)
        if profile is not None
        else {dimension: _NEUTRAL for dimension in _UPSTREAM_DIMENSIONS}
    )
    confirmed_failure = False
    if profile is not None and statements:
        for stmt in statements:
            if stmt.requirement != "REQUIRED" or stmt.kind not in (
                "COMPETENCY",
                "LANGUAGE",
                "OTHER",
            ):
                continue
            # Option A1: coursework and transcript-credit rules adjust ACADEMIC_FIT and display
            # course-by-course on the applicant pane, never silently hard-excluding a
            # programme when a transcript is partial or uses non-standard course titles.
            # Unambiguous non-course hard bars (GPA, IELTS/TOEFL, work experience,
            # graduation cutoff/recency) set `confirmed_eligibility_failure` when FAILED,
            # even when they appear inside a compound statement that also mentions coursework.
            if (
                evaluate_program_statement(
                    stmt.text,
                    profile,
                    kind=stmt.kind,
                    as_of=today,
                    include_coursework=False,
                ).outcome
                == "FAILED"
            ):
                confirmed_failure = True
                break

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
        # The catalogue holds NO deadline columns (CLAUDE.md); when a verified
        # DEADLINE claim or scholarship cycle date was read off the page and
        # supplied by the spine, it is carried here without inventing a date.
        application_deadline=application_deadline,
        scholarship_decision_deadline=scholarship_decision_deadline,
        deadline_is_viable=(
            True
            if application_deadline is None or today is None
            else application_deadline >= today
        ),
        confirmed_eligibility_failure=confirmed_failure,
        evidence_confidence="MEDIUM",
        cost_components=tuple(
            CostLineItem(
                kind=cast(Any, cost.kind),
                amount=cost.amount,
                currency=cost.currency,
                period=cast(Any, cost.period),
            )
            for cost in costs
        ),
        benefits=_benefit_facts(
            benefits,
            routes,
            durations=durations,
            programme_months=program.duration_months,
            tuition_levels=tuition_levels,
            tuition_total=_tuition_total(costs, program.duration_months),
        ),
        applicant_conditions=_condition_facts(rules),
        return_service=_return_service_facts(rules),
        dimension_scores=scores,
    )
