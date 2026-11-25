"""Tier 1 dual-reader refinement and Tier 2 Dawid-Skene cost-sensitive arbitration."""

from __future__ import annotations

import calendar
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from apps.research.candidates import Candidates
from apps.research.card_engine import (
    Decision,
    Limit,
    Quote,
    ReaderAnswer,
    Section,
    locate,
)
from apps.research.card_engine.engine import (
    Transport,
    _ask,
    _prompt,
    read,
)
from apps.research.card_engine.readers import Stack, stack
from apps.research.card_engine.readers import call as default_call
from apps.research.card_engine.screen import Screen

from .extractors import (
    _candidates_with_header_currency,
    _normalize_tuition_amount_and_period,
    _period_from_context,
)
from .patterns import _CONDITIONAL_GUARD_RE, _EU_DOMESTIC_RE, _NON_EU_RE
from .specs import (
    CostComponentSpec,
    DocumentStatementSpec,
    EligibilitySpec,
    ProgrammeBundle,
    ProgrammeQuestionSet,
    ProgrammeScrapeResult,
)


@dataclass(frozen=True)
class DawidSkeneSlotParams:
    """Cost-sensitive Dawid-Skene parameters for a high-consequence extraction slot.

    From Proposition 1 (Dawid & Skene 1979; Kim & Ghahramani 2012):
        L(y) = ln(pi / (1 - pi)) + sum_k [ y_k ln(alpha_k / (1 - beta_k))
                                         + (1 - y_k) ln((1 - alpha_k) / beta_k) ]
        theta_low  = ln(c_judge / (c_fn - c_judge))
        theta_high = ln((c_fp - c_judge) / c_judge)
    """

    prior: float = 0.15
    sensitivities: tuple[float, ...] = (0.90, 0.90)
    specificities: tuple[float, ...] = (0.88, 0.88)
    c_fp: float = 100.0
    c_fn: float = 5.0
    c_judge: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 < self.prior < 1.0):
            raise ValueError("prior must lie strictly in (0, 1)")
        if len(self.sensitivities) != len(self.specificities) or not self.sensitivities:
            raise ValueError("sensitivities and specificities must have matching non-empty lengths")
        for alpha, beta in zip(self.sensitivities, self.specificities, strict=True):
            if not (0.0 < alpha < 1.0 and 0.0 < beta < 1.0):
                raise ValueError("sensitivities and specificities must lie strictly in (0, 1)")
            if alpha <= 1.0 - beta:
                raise ValueError("each reader must be informative: alpha > 1 - beta")
        if self.c_judge <= 0.0 or self.c_judge >= min(self.c_fp, self.c_fn):
            raise ValueError("c_judge must satisfy 0 < c_judge < min(c_fp, c_fn)")


CONDITIONAL_FREE_TUITION_PARAMS = DawidSkeneSlotParams(
    prior=0.15,
    sensitivities=(0.90, 0.90),
    specificities=(0.88, 0.88),
    c_fp=100.0,
    c_fn=5.0,
    c_judge=1.0,
)
CLEAN_FREE_TUITION_PARAMS = DawidSkeneSlotParams(
    prior=0.80,
    sensitivities=(0.90, 0.90),
    specificities=(0.88, 0.88),
    c_fp=100.0,
    c_fn=5.0,
    c_judge=1.0,
)
AMBIGUOUS_AMOUNT_SPREAD_PARAMS = DawidSkeneSlotParams(
    prior=0.20,
    sensitivities=(0.88, 0.88),
    specificities=(0.85, 0.85),
    c_fp=50.0,
    c_fn=5.0,
    c_judge=1.0,
)
APPLICATION_FEE_PARAMS = DawidSkeneSlotParams(
    prior=0.25,
    sensitivities=(0.90, 0.90),
    specificities=(0.88, 0.88),
    c_fp=40.0,
    c_fn=10.0,
    c_judge=1.0,
)
DEADLINE_PARAMS = DawidSkeneSlotParams(
    prior=0.20,
    sensitivities=(0.90, 0.90),
    specificities=(0.88, 0.88),
    c_fp=120.0,
    c_fn=15.0,
    c_judge=1.0,
)
MIN_GPA_PARAMS = DawidSkeneSlotParams(
    prior=0.25,
    sensitivities=(0.90, 0.90),
    specificities=(0.88, 0.88),
    c_fp=80.0,
    c_fn=10.0,
    c_judge=1.0,
)
IELTS_BAR_PARAMS = DawidSkeneSlotParams(
    prior=0.30,
    sensitivities=(0.90, 0.90),
    specificities=(0.88, 0.88),
    c_fp=60.0,
    c_fn=10.0,
    c_judge=1.0,
)
SCHOLARSHIP_SUSPENDED_PARAMS = DawidSkeneSlotParams(
    prior=0.15,
    sensitivities=(0.90, 0.90),
    specificities=(0.88, 0.88),
    c_fp=80.0,
    c_fn=100.0,
    c_judge=1.0,
)

SLOT_DEFAULT_PARAMS: Mapping[str, DawidSkeneSlotParams] = {
    "tuition": AMBIGUOUS_AMOUNT_SPREAD_PARAMS,
    "tuition_amount": AMBIGUOUS_AMOUNT_SPREAD_PARAMS,
    "tuition_period": AMBIGUOUS_AMOUNT_SPREAD_PARAMS,
    "conditional_free_tuition": CONDITIONAL_FREE_TUITION_PARAMS,
    "tuition_free_all_internationals": CONDITIONAL_FREE_TUITION_PARAMS,
    "application_fee": APPLICATION_FEE_PARAMS,
    "application_fee_amount": APPLICATION_FEE_PARAMS,
    "deadline": DEADLINE_PARAMS,
    "application_deadline_date": DEADLINE_PARAMS,
    "min_gpa": MIN_GPA_PARAMS,
    "minimum_gpa_bar": MIN_GPA_PARAMS,
    "ielts_bar": IELTS_BAR_PARAMS,
    "minimum_language_bar": IELTS_BAR_PARAMS,
    "scholarship_suspended": SCHOLARSHIP_SUSPENDED_PARAMS,
    "scholarship_intake_suspended": SCHOLARSHIP_SUSPENDED_PARAMS,
}

_SLOT_QUESTION_ALIASES: Mapping[str, tuple[str, ...]] = {
    "tuition": ("tuition", "tuition_amount", "tuition_period"),
    "tuition_amount": ("tuition", "tuition_amount"),
    "tuition_period": ("tuition", "tuition_period"),
    "conditional_free_tuition": ("conditional_free_tuition", "tuition_free_all_internationals"),
    "tuition_free_all_internationals": (
        "conditional_free_tuition",
        "tuition_free_all_internationals",
    ),
    "application_fee": ("application_fee", "application_fee_amount"),
    "application_fee_amount": ("application_fee", "application_fee_amount"),
    "deadline": ("deadline", "application_deadline_date"),
    "application_deadline_date": ("deadline", "application_deadline_date"),
    "min_gpa": ("min_gpa", "minimum_gpa_bar"),
    "minimum_gpa_bar": ("min_gpa", "minimum_gpa_bar"),
    "ielts_bar": ("ielts_bar", "minimum_language_bar"),
    "minimum_language_bar": ("ielts_bar", "minimum_language_bar"),
    "scholarship_suspended": ("scholarship_suspended", "scholarship_intake_suspended"),
    "scholarship_intake_suspended": ("scholarship_suspended", "scholarship_intake_suspended"),
}


@dataclass(frozen=True)
class ReaderAuditCounts:
    """Observed confusion-matrix counts for a single reader on a slot question."""

    tp: int = 0
    fn: int = 0
    tn: int = 0
    fp: int = 0


def _load_audit_counts_from_db(
    slot_name: str,
    num_readers: int = 2,
) -> tuple[ReaderAuditCounts, ...]:
    """Query audited `GoldItem` + `DecisionRecord` history for `slot_name`, returning empty
    tuple when no audited records exist or when the database is unavailable."""
    try:
        from django.db.models import Q

        from apps.research.models import DecisionRecord, GoldItem

        q_aliases = _SLOT_QUESTION_ALIASES.get(slot_name, (slot_name,))
        gold_rows = list(
            GoldItem.objects.filter(question__in=q_aliases)
            .exclude(verdict="")
            .order_by("created_at", "id")
        )
        if not gold_rows:
            return ()
        dec_rows = list(
            DecisionRecord.objects.filter(
                Q(question_id__in=q_aliases) | Q(decision__in=q_aliases),
                refused=False,
            ).order_by("created_at", "id")
        )
        if not dec_rows:
            return ()

        gold_by_sha = {g.line_sha256: g for g in gold_rows if g.line_sha256}
        by_model: dict[str, list[DecisionRecord]] = {}
        for dr in dec_rows:
            by_model.setdefault(dr.model, []).append(dr)

        counts_list: list[ReaderAuditCounts] = []
        negative_tokens = {"no", "false", "not_stated", ""}
        for _model_name, model_decs in list(by_model.items())[:num_readers]:
            tp = fn = tn = fp = 0
            for idx, dr in enumerate(model_decs):
                gold = gold_by_sha.get(dr.state_digest) or gold_rows[idx % len(gold_rows)]
                dr_val = (dr.value or "").strip()
                dr_val_low = dr_val.casefold()
                claim_val = (gold.claim or "").strip()
                is_short_claim = bool(claim_val and " " not in claim_val and len(claim_val) <= 32)
                if gold.verdict == "correct":
                    if dr_val_low in negative_tokens:
                        fn += 1
                    elif is_short_claim and dr_val != claim_val:
                        fn += 1
                    else:
                        tp += 1
                elif gold.verdict in ("wrong", "not_on_page"):
                    if gold.verdict == "not_on_page":
                        if dr_val_low in negative_tokens:
                            tn += 1
                        else:
                            fp += 1
                    else:
                        if is_short_claim:
                            if dr_val == claim_val:
                                fp += 1
                            else:
                                tn += 1
                        elif dr_val_low in negative_tokens:
                            tn += 1
                        else:
                            fp += 1
            if (tp + fn + tn + fp) > 0:
                counts_list.append(ReaderAuditCounts(tp=tp, fn=fn, tn=tn, fp=fp))
        return tuple(counts_list)
    except Exception:
        return ()


def calibrate_slot_params(
    slot_or_base: str | DawidSkeneSlotParams,
    default_or_counts: DawidSkeneSlotParams | Sequence[ReaderAuditCounts] | None = None,
    *,
    audit_counts: Sequence[ReaderAuditCounts] | None = None,
    prior_strength: float = 20.0,
) -> DawidSkeneSlotParams:
    """Calibrate per-slot reader sensitivities and specificities via Beta-Binomial conjugate
    posteriors over audited `GoldItem` + `DecisionRecord` history (or explicit `audit_counts`),
    with prior strength kappa_0 = 20.0 and informativeness guard alpha_hat + beta_hat > 1.02."""
    if isinstance(slot_or_base, DawidSkeneSlotParams):
        base = slot_or_base
        resolved_counts: Sequence[ReaderAuditCounts] = (
            audit_counts
            if audit_counts is not None
            else (
                default_or_counts
                if isinstance(default_or_counts, Sequence)
                else ()
            )
        )
    else:
        slot_name = str(slot_or_base)
        base = (
            default_or_counts
            if isinstance(default_or_counts, DawidSkeneSlotParams)
            else SLOT_DEFAULT_PARAMS.get(slot_name, CONDITIONAL_FREE_TUITION_PARAMS)
        )
        if audit_counts is not None:
            resolved_counts = audit_counts
        elif isinstance(default_or_counts, Sequence):
            resolved_counts = default_or_counts
        else:
            resolved_counts = _load_audit_counts_from_db(
                slot_name, num_readers=len(base.sensitivities)
            )

    if not resolved_counts:
        return base

    new_sens: list[float] = []
    new_spec: list[float] = []
    for idx, (alpha_0, beta_0) in enumerate(
        zip(base.sensitivities, base.specificities, strict=True)
    ):
        counts = resolved_counts[min(idx, len(resolved_counts) - 1)]
        a_sens = alpha_0 * prior_strength + counts.tp
        b_sens = (1.0 - alpha_0) * prior_strength + counts.fn
        hat_alpha = max(0.51, min(0.995, a_sens / (a_sens + b_sens)))

        a_spec = beta_0 * prior_strength + counts.tn
        b_spec = (1.0 - beta_0) * prior_strength + counts.fp
        hat_beta = max(0.51, min(0.995, a_spec / (a_spec + b_spec)))

        if hat_alpha + hat_beta <= 1.02:
            hat_alpha = alpha_0
            hat_beta = beta_0
        new_sens.append(round(hat_alpha, 4))
        new_spec.append(round(hat_beta, 4))
    return replace(base, sensitivities=tuple(new_sens), specificities=tuple(new_spec))


def slot_escalation_bounds(params: DawidSkeneSlotParams) -> tuple[float, float]:
    """Return the Bayes-optimal log-posterior-odds escalation interval (theta_low, theta_high).

    By Proposition 1, escalating to the frontier judge is Bayes-optimal iff
    theta_low < L(y) < theta_high.
    """
    theta_low = math.log(params.c_judge / (params.c_fn - params.c_judge))
    theta_high = math.log((params.c_fp - params.c_judge) / params.c_judge)
    return (theta_low, theta_high)


def slot_posterior_log_odds(
    votes: Sequence[bool],
    params: DawidSkeneSlotParams,
) -> float:
    """Compute exact Dawid-Skene posterior log-odds L(y) given binary cheap-reader votes."""
    log_odds = math.log(params.prior / (1.0 - params.prior))
    for idx, vote in enumerate(votes):
        alpha = params.sensitivities[min(idx, len(params.sensitivities) - 1)]
        beta = params.specificities[min(idx, len(params.specificities) - 1)]
        if vote:
            log_odds += math.log(alpha / (1.0 - beta))
        else:
            log_odds += math.log((1.0 - alpha) / beta)
    return log_odds


def detect_tuition_amount_spread_risk(
    decision: Decision,
    section: Section,
    candidates: Candidates | None = None,
) -> bool:
    """Return True when both cheap readers agreed on a low tuition amount in a section that
    lists another candidate amount in the same currency at least 2x higher (e.g. picking an
    EU/domestic or per-semester fee instead of the non-EU annual fee)."""
    if (
        decision.question != "tuition_amount"
        or decision.status != "agreed"
        or decision.value in (None, "not_stated")
    ):
        return False
    resolved_candidates = (
        candidates if candidates is not None else _candidates_with_header_currency(section.lines)
    )
    if decision.value not in resolved_candidates.amounts:
        return False
    chosen_found = resolved_candidates.amounts[decision.value]
    chosen_amt = chosen_found.value.low
    chosen_curr = chosen_found.value.currency
    if chosen_amt is None or chosen_amt <= Decimal("0") or not chosen_curr:
        return False
    same_curr_lows = [
        fa.value.low
        for fa in resolved_candidates.amounts.values()
        if fa.value.currency == chosen_curr
        and fa.value.low is not None
        and fa.value.low > Decimal("0")
    ]
    if len(same_curr_lows) < 2 or max(same_curr_lows) < chosen_amt * Decimal("2"):
        return False
    votes = (
        tuple(ans.value == decision.value for ans in decision.answers.values() if ans.value)
        if decision.answers
        else (True, True)
    )
    l_post = slot_posterior_log_odds(votes, AMBIGUOUS_AMOUNT_SPREAD_PARAMS)
    theta_low, theta_high = slot_escalation_bounds(AMBIGUOUS_AMOUNT_SPREAD_PARAMS)
    return theta_low < l_post < theta_high


def needs_high_risk_arbitration(
    decisions: Sequence[Decision] | ProgrammeScrapeResult,
    section: Section | None = None,
    *,
    candidates: Candidates | None = None,
) -> tuple[str, ...]:
    """Return question IDs (or unresolved/high-risk slot names when given a `ProgrammeScrapeResult`)
    that must be escalated to the frontier decider even when the two cheap readers agreed
    (`status == "agreed"`), because posterior log-odds L(y) falls inside the Bayes-optimal
    escalation band (theta_low, theta_high) under asymmetric financial/eligibility loss
    (Proposition 1)."""
    if isinstance(decisions, ProgrammeScrapeResult):
        return tuple(sorted(decisions.unresolved_slots | decisions.high_risk_flags))
    if section is None:
        return ()

    section_text = " ".join(f"{line.heading} {line.header} {line.text}" for line in section.lines)
    has_conditions = bool(
        _CONDITIONAL_GUARD_RE.search(section_text)
        or (_EU_DOMESTIC_RE.search(section_text) and _NON_EU_RE.search(section_text))
    )
    resolved_candidates = (
        candidates if candidates is not None else _candidates_with_header_currency(section.lines)
    )
    decisions_by_q = {dec.question: dec for dec in decisions}
    escalate: list[str] = []

    for dec in decisions:
        if dec.status != "agreed" or dec.value is None:
            continue

        if dec.question == "tuition_free_all_internationals" and dec.value == "yes":
            base_params = (
                CONDITIONAL_FREE_TUITION_PARAMS if has_conditions else CLEAN_FREE_TUITION_PARAMS
            )
            params = calibrate_slot_params("conditional_free_tuition", base_params)
            votes = (
                tuple(ans.value == "yes" for ans in dec.answers.values() if ans.value)
                if dec.answers
                else (True, True)
            )
            l_post = slot_posterior_log_odds(votes, params)
            theta_low, theta_high = slot_escalation_bounds(params)
            if theta_low < l_post < theta_high:
                escalate.append(dec.question)

        elif dec.question == "tuition_amount" and detect_tuition_amount_spread_risk(
            dec, section, resolved_candidates
        ):
            escalate.append(dec.question)

        elif dec.question == "tuition_period" and dec.value in ("ANNUAL", "FULL_PROGRAM"):
            amt_dec = decisions_by_q.get("tuition_amount")
            if (
                amt_dec is not None
                and amt_dec.value in resolved_candidates.amounts
                and 0 <= resolved_candidates.amounts[amt_dec.value].line < len(section.lines)
            ):
                line_idx = resolved_candidates.amounts[amt_dec.value].line
                line_obj = section.lines[line_idx]
                line_ctx = f"{line_obj.heading} | {line_obj.header} | {line_obj.text}"
                ctx_period = _period_from_context(line_ctx)
                if ctx_period not in ("ANNUAL", dec.value):
                    escalate.append(dec.question)

        elif dec.question == "application_fee_amount" and dec.value != "not_stated":
            if has_conditions or len(resolved_candidates.amounts) > 1:
                params = calibrate_slot_params("application_fee", APPLICATION_FEE_PARAMS)
                votes = (
                    tuple(ans.value == dec.value for ans in dec.answers.values() if ans.value)
                    if dec.answers
                    else (True, True)
                )
                l_post = slot_posterior_log_odds(votes, params)
                theta_low, theta_high = slot_escalation_bounds(params)
                if theta_low < l_post < theta_high:
                    escalate.append(dec.question)

        elif dec.question == "application_deadline_date" and dec.value != "not_stated":
            needs_dl_check = has_conditions or len(resolved_candidates.dates) > 1
            if needs_dl_check and dec.value in resolved_candidates.dates:
                d_line_idx = resolved_candidates.dates[dec.value].line
                if 0 <= d_line_idx < len(section.lines):
                    d_line = section.lines[d_line_idx]
                    d_ctx = f"{d_line.heading} | {d_line.header} | {d_line.text}"
                    if _NON_EU_RE.search(d_ctx) and not _EU_DOMESTIC_RE.search(d_ctx) and not (
                        _CONDITIONAL_GUARD_RE.search(d_ctx)
                    ):
                        needs_dl_check = False
            if needs_dl_check:
                params = calibrate_slot_params("deadline", DEADLINE_PARAMS)
                votes = (
                    tuple(ans.value == dec.value for ans in dec.answers.values() if ans.value)
                    if dec.answers
                    else (True, True)
                )
                l_post = slot_posterior_log_odds(votes, params)
                theta_low, theta_high = slot_escalation_bounds(params)
                if theta_low < l_post < theta_high:
                    escalate.append(dec.question)

        elif dec.question == "minimum_gpa_bar" and dec.value != "not_stated":
            grade_reqs = [
                r for r in resolved_candidates.requirements.values() if r.value.kind == "grade"
            ]
            if has_conditions or len(grade_reqs) > 1:
                params = calibrate_slot_params("min_gpa", MIN_GPA_PARAMS)
                votes = (
                    tuple(ans.value == dec.value for ans in dec.answers.values() if ans.value)
                    if dec.answers
                    else (True, True)
                )
                l_post = slot_posterior_log_odds(votes, params)
                theta_low, theta_high = slot_escalation_bounds(params)
                if theta_low < l_post < theta_high:
                    escalate.append(dec.question)

        elif dec.question == "minimum_language_bar" and dec.value != "not_stated":
            lang_reqs = [
                r
                for r in resolved_candidates.requirements.values()
                if r.value.kind in ("language_test", "cefr")
            ]
            if has_conditions or len(lang_reqs) > 1:
                params = calibrate_slot_params("ielts_bar", IELTS_BAR_PARAMS)
                votes = (
                    tuple(ans.value == dec.value for ans in dec.answers.values() if ans.value)
                    if dec.answers
                    else (True, True)
                )
                l_post = slot_posterior_log_odds(votes, params)
                theta_low, theta_high = slot_escalation_bounds(params)
                if theta_low < l_post < theta_high:
                    escalate.append(dec.question)

        elif dec.question == "scholarship_intake_suspended":
            params = calibrate_slot_params("scholarship_suspended", SCHOLARSHIP_SUSPENDED_PARAMS)
            votes = (
                tuple(ans.value == dec.value for ans in dec.answers.values() if ans.value)
                if dec.answers
                else (True, True)
            )
            l_post = slot_posterior_log_odds(votes, params)
            theta_low, theta_high = slot_escalation_bounds(params)
            if (dec.value == "yes" or has_conditions) and (theta_low < l_post < theta_high):
                escalate.append(dec.question)

    if "tuition_amount" in escalate and "tuition_period" in decisions_by_q:
        per_dec = decisions_by_q["tuition_period"]
        if per_dec.status == "agreed" and "tuition_period" not in escalate:
            escalate.append("tuition_period")

    return tuple(dict.fromkeys(escalate))


def refine_with_dual_readers(
    bundle: ProgrammeBundle,
    tier0: ProgrammeScrapeResult,
    *,
    screen: Screen,
    limit: Limit,
    readers: Stack | None = None,
    transport: Transport | None = None,
) -> ProgrammeScrapeResult:
    """Run Tier 1 dual cheap readers on unresolved/high-risk slots, plus Tier 2 risk-asymmetric
    frontier arbitration when `needs_high_risk_arbitration` triggers."""
    qset = ProgrammeQuestionSet(
        unresolved_slots=tier0.unresolved_slots,
        high_risk_flags=tier0.high_risk_flags,
    )
    candidates = _candidates_with_header_currency(bundle.section.lines)
    asked = qset.questions(bundle.section, candidates, {})
    if not asked:
        return tier0

    active_readers = readers or stack()
    active_transport: Transport = transport if transport is not None else default_call
    reading = read(
        qset,
        bundle.section,
        screen=screen,
        limit=limit,
        readers=active_readers,
        transport=active_transport,
    )
    decisions_by_id = {d.question: d for d in reading.decisions}
    extra_cost = sum(c.cost_usd or 0.0 for c in reading.calls)

    # Tier 2 Risk-Asymmetric Arbitration: escalate high-risk agreed claims to decider
    risk_qids = needs_high_risk_arbitration(
        reading.decisions, bundle.section, candidates=candidates
    )
    if risk_qids:
        risk_qs = [q for q in asked if q.id in risk_qids]
        dec_prompt = _prompt(qset, bundle.section, candidates, {}, risk_qs)
        reply, made = _ask(
            active_readers.decider,
            dec_prompt,
            risk_qs,
            limit,
            active_transport,
            first_raises=False,
        )
        extra_cost += sum(c.cost_usd or 0.0 for c in made)
        for rq in risk_qs:
            prior_dec = decisions_by_id[rq.id]
            given = (
                [a for a in reply.answers if a.id == rq.id and a.value in rq.options]
                if reply is not None
                else []
            )
            if given:
                val = given[0].value
                needs_quote = val not in rq.unquoted
                q_loc = locate(given[0].quote, bundle.section) if needs_quote else None
                if not needs_quote or q_loc is not None:
                    decisions_by_id[rq.id] = Decision(
                        question=rq.id,
                        status="decided",
                        value=val,
                        quote=q_loc,
                        answers={
                            **prior_dec.answers,
                            active_readers.decider.name: ReaderAnswer(val, q_loc),
                        },
                    )
                    continue
            # Fail-closed when frontier escalation was required by Proposition 1 but the decider
            # failed, was rate-limited, or returned an unverified quote:
            decisions_by_id[rq.id] = Decision(
                question=rq.id,
                status="unresolved",
                value=None,
                quote=None,
                answers=prior_dec.answers,
            )

    updated_costs = list(tier0.costs)
    updated_elig = list(tier0.eligibility)
    updated_statements = list(tier0.statements)
    remaining_unresolved = set(tier0.unresolved_slots)
    remaining_high_risk = set(tier0.high_risk_flags)
    primary_url = bundle.page_urls[0] if bundle.page_urls else ""

    from apps.funding.transcript_eligibility import (
        is_coursework_or_credit_statement,
        parse_scholarship_status_statement,
    )

    grade_quotes = {e.quote.text for e in tier0.eligibility if e.kind == "GRADE"}

    def _is_gpa_stmt(s: DocumentStatementSpec) -> bool:
        if s.label.startswith("Minimum Grade / GPA"):
            return True
        if s.kind == "COMPETENCY" and not is_coursework_or_credit_statement(s.text):
            if s.quote.text in grade_quotes or any(q and q in s.text for q in grade_quotes):
                return True
        return False

    def _is_susp_stmt(s: DocumentStatementSpec) -> bool:
        return s.label.startswith("Scholarship / Funding Status") or (
            parse_scholarship_status_statement(s.text) is not None
        )

    # Apply tuition_amount decision if resolved
    amt_dec = decisions_by_id.get("tuition_amount")
    per_dec = decisions_by_id.get("tuition_period")
    if amt_dec and amt_dec.value and amt_dec.status in ("agreed", "decided"):
        if amt_dec.value == "not_stated":
            updated_costs = [c for c in updated_costs if c.kind != "TUITION"]
            remaining_unresolved.discard("tuition")
        elif amt_dec.value in candidates.amounts:
            found_amt = candidates.amounts[amt_dec.value]
            amt_obj = found_amt.value
            if amt_obj.low is not None and amt_obj.currency:
                line_idx = found_amt.line
                line_obj = bundle.section.lines[line_idx]
                line_ctx = f"{line_obj.heading} | {line_obj.header} | {line_obj.text}"
                raw_per = (
                    per_dec.value
                    if (
                        per_dec
                        and per_dec.status in ("agreed", "decided")
                        and per_dec.value
                        in (
                            "ANNUAL",
                            "SEMESTER",
                            "TRIMESTER",
                            "QUARTER",
                            "TERM",
                            "PER_ECTS",
                            "PER_CREDIT",
                            "FULL_PROGRAM",
                            "MONTHLY",
                        )
                    )
                    else _period_from_context(line_ctx)
                )
                final_amt, final_per = _normalize_tuition_amount_and_period(amt_obj.low, raw_per)
                src_url = (
                    bundle.line_sources[line_idx]
                    if line_idx < len(bundle.line_sources)
                    else primary_url
                )
                q_obj = amt_dec.quote or Quote(amt_obj.text, f"L{line_idx}.text")
                updated_costs = [c for c in updated_costs if c.kind != "TUITION"]
                updated_costs.insert(
                    0,
                    CostComponentSpec(
                        kind="TUITION",
                        amount=final_amt,
                        currency=amt_obj.currency,
                        period=final_per,
                        audience="INTERNATIONAL",
                        quote=q_obj,
                        source_url=src_url,
                        from_structured=bool(bundle.section.lines[line_idx].header),
                    ),
                )
                remaining_unresolved.discard("tuition")

    free_dec = decisions_by_id.get("tuition_free_all_internationals")
    if free_dec and free_dec.status in ("agreed", "decided"):
        remaining_high_risk.discard("conditional_free_tuition")
        if free_dec.value == "yes" and free_dec.quote is not None:
            m_where = re.match(r"L(\d+)\.", free_dec.quote.where)
            free_line_idx = int(m_where.group(1)) if m_where else -1
            free_src_url = (
                bundle.line_sources[free_line_idx]
                if 0 <= free_line_idx < len(bundle.line_sources)
                else primary_url
            )
            updated_costs = [c for c in updated_costs if c.kind != "TUITION"]
            updated_costs.insert(
                0,
                CostComponentSpec(
                    kind="TUITION",
                    amount=Decimal("0.00"),
                    currency="EUR",
                    period="ANNUAL",
                    audience="INTERNATIONAL",
                    quote=free_dec.quote,
                    source_url=free_src_url,
                ),
            )
            remaining_unresolved.discard("tuition")
        elif free_dec.value == "no":
            updated_costs = [
                c
                for c in updated_costs
                if not (c.kind == "TUITION" and c.amount == Decimal("0.00"))
            ]
    elif free_dec and free_dec.status == "unresolved":
        updated_costs = [
            c
            for c in updated_costs
            if not (c.kind == "TUITION" and c.amount == Decimal("0.00"))
        ]
        remaining_unresolved.add("tuition")

    app_fee_dec = decisions_by_id.get("application_fee_amount")
    if app_fee_dec and app_fee_dec.value and app_fee_dec.status in ("agreed", "decided"):
        remaining_high_risk.discard("ambiguous_application_fee")
        if app_fee_dec.value == "not_stated":
            updated_costs = [c for c in updated_costs if c.kind != "APPLICATION_FEE"]
            remaining_unresolved.discard("application_fee")
        elif app_fee_dec.value in candidates.amounts:
            found_app = candidates.amounts[app_fee_dec.value]
            amt_obj = found_app.value
            if amt_obj.low is not None and amt_obj.currency:
                line_idx = found_app.line
                src_url = (
                    bundle.line_sources[line_idx]
                    if line_idx < len(bundle.line_sources)
                    else primary_url
                )
                q_obj = app_fee_dec.quote or Quote(amt_obj.text, f"L{line_idx}.text")
                updated_costs = [c for c in updated_costs if c.kind != "APPLICATION_FEE"]
                updated_costs.append(
                    CostComponentSpec(
                        kind="APPLICATION_FEE",
                        amount=amt_obj.low,
                        currency=amt_obj.currency,
                        period="ONE_OFF",
                        audience="INTERNATIONAL",
                        quote=q_obj,
                        source_url=src_url,
                        from_structured=bool(bundle.section.lines[line_idx].header),
                    )
                )
                remaining_unresolved.discard("application_fee")
    elif app_fee_dec and app_fee_dec.status == "unresolved":
        updated_costs = [c for c in updated_costs if c.kind != "APPLICATION_FEE"]
        remaining_unresolved.add("application_fee")

    dl_dec = decisions_by_id.get("application_deadline_date")
    if dl_dec and dl_dec.value and dl_dec.status in ("agreed", "decided"):
        remaining_high_risk.discard("ambiguous_deadline")
        remaining_unresolved.discard("deadline")
        if dl_dec.value == "not_stated":
            updated_elig = [e for e in updated_elig if e.kind != "DEADLINE"]
        elif dl_dec.value in candidates.dates:
            found_dl = candidates.dates[dl_dec.value]
            d_obj = found_dl.value
            if d_obj.month is not None:
                line_idx = found_dl.line
                src_url = (
                    bundle.line_sources[line_idx]
                    if line_idx < len(bundle.line_sources)
                    else primary_url
                )
                yr = d_obj.year or 2027
                max_day = calendar.monthrange(yr, d_obj.month)[1]
                clamped_day = min(d_obj.day or 1, max_day)
                iso_str = f"{yr:04d}-{d_obj.month:02d}-{clamped_day:02d}"
                q_obj = dl_dec.quote or Quote(d_obj.text, f"L{line_idx}.text")
                updated_elig = [e for e in updated_elig if e.kind != "DEADLINE"]
                updated_elig.append(
                    EligibilitySpec(
                        kind="DEADLINE",
                        label="Application Deadline",
                        value=iso_str,
                        quote=q_obj,
                        source_url=src_url,
                        audience="INTERNATIONAL",
                    )
                )
    elif dl_dec and dl_dec.status == "unresolved":
        updated_elig = [e for e in updated_elig if e.kind != "DEADLINE"]
        remaining_unresolved.add("deadline")

    gpa_dec = decisions_by_id.get("minimum_gpa_bar")
    if gpa_dec and gpa_dec.value and gpa_dec.status in ("agreed", "decided"):
        remaining_high_risk.discard("ambiguous_min_gpa")
        remaining_unresolved.discard("min_gpa")
        if gpa_dec.value == "not_stated":
            updated_elig = [e for e in updated_elig if e.kind != "GRADE"]
            updated_statements = [s for s in updated_statements if not _is_gpa_stmt(s)]
        elif gpa_dec.value in candidates.requirements:
            found_gpa = candidates.requirements[gpa_dec.value]
            req_gpa = found_gpa.value
            if req_gpa.kind == "grade" and req_gpa.score is not None:
                line_idx = found_gpa.line
                src_url = (
                    bundle.line_sources[line_idx]
                    if line_idx < len(bundle.line_sources)
                    else primary_url
                )
                scale_str = f"/{req_gpa.scale}" if req_gpa.scale is not None else ""
                val_str = f"{req_gpa.score}{scale_str}"
                q_obj = (
                    gpa_dec.quote
                    or locate(req_gpa.text, bundle.section)
                    or Quote(req_gpa.text, f"L{line_idx}.text")
                )
                new_gpa_elig = EligibilitySpec(
                    kind="GRADE",
                    label="Minimum Grade / GPA",
                    value=val_str,
                    quote=q_obj,
                    source_url=src_url,
                )
                updated_elig = [e for e in updated_elig if e.kind != "GRADE"]
                updated_elig.append(new_gpa_elig)
                updated_statements = [s for s in updated_statements if not _is_gpa_stmt(s)]
                stmt_text = (
                    f"{new_gpa_elig.label} ({new_gpa_elig.value}): {q_obj.text}"[:1000]
                    if new_gpa_elig.label.lower() not in q_obj.text.lower()
                    else q_obj.text[:1000]
                )
                updated_statements.append(
                    DocumentStatementSpec(
                        kind="COMPETENCY",
                        requirement="REQUIRED",
                        label=new_gpa_elig.label,
                        text=stmt_text,
                        quote=q_obj,
                        source_url=src_url,
                    )
                )
    elif gpa_dec and gpa_dec.status == "unresolved":
        updated_elig = [e for e in updated_elig if e.kind != "GRADE"]
        updated_statements = [s for s in updated_statements if not _is_gpa_stmt(s)]
        remaining_unresolved.add("min_gpa")

    lang_dec = decisions_by_id.get("minimum_language_bar")
    if lang_dec and lang_dec.value and lang_dec.status in ("agreed", "decided"):
        remaining_high_risk.discard("ambiguous_ielts_bar")
        remaining_unresolved.discard("ielts_bar")
        if lang_dec.value == "not_stated":
            updated_elig = [e for e in updated_elig if e.kind != "LANGUAGE"]
            updated_statements = [s for s in updated_statements if s.kind != "LANGUAGE"]
        elif lang_dec.value in candidates.requirements:
            found_lang = candidates.requirements[lang_dec.value]
            req_lang = found_lang.value
            line_idx = found_lang.line
            src_url = (
                bundle.line_sources[line_idx]
                if line_idx < len(bundle.line_sources)
                else primary_url
            )
            q_obj = (
                lang_dec.quote
                or locate(req_lang.text, bundle.section)
                or Quote(req_lang.text, f"L{line_idx}.text")
            )
            new_lang_elig: EligibilitySpec | None = None
            if req_lang.kind == "language_test" and req_lang.test and req_lang.score is not None:
                new_lang_elig = EligibilitySpec(
                    kind="LANGUAGE",
                    label=req_lang.test,
                    value=str(req_lang.score),
                    quote=q_obj,
                    source_url=src_url,
                )
            elif req_lang.kind == "cefr" and req_lang.cefr:
                new_lang_elig = EligibilitySpec(
                    kind="LANGUAGE",
                    label="CEFR",
                    value=req_lang.cefr,
                    quote=q_obj,
                    source_url=src_url,
                )
            if new_lang_elig is not None:
                updated_elig = [e for e in updated_elig if e.kind != "LANGUAGE"]
                updated_elig.append(new_lang_elig)
                updated_statements = [s for s in updated_statements if s.kind != "LANGUAGE"]
                stmt_text = (
                    f"{new_lang_elig.label} ({new_lang_elig.value}): {q_obj.text}"[:1000]
                    if new_lang_elig.label.lower() not in q_obj.text.lower()
                    else q_obj.text[:1000]
                )
                updated_statements.append(
                    DocumentStatementSpec(
                        kind="LANGUAGE",
                        requirement="REQUIRED",
                        label=new_lang_elig.label,
                        text=stmt_text,
                        quote=q_obj,
                        source_url=src_url,
                    )
                )
    elif lang_dec and lang_dec.status == "unresolved":
        updated_elig = [e for e in updated_elig if e.kind != "LANGUAGE"]
        updated_statements = [s for s in updated_statements if s.kind != "LANGUAGE"]
        remaining_unresolved.add("ielts_bar")

    susp_dec = decisions_by_id.get("scholarship_intake_suspended")
    if susp_dec and susp_dec.value and susp_dec.status in ("agreed", "decided"):
        remaining_unresolved.discard("scholarship_suspended")
        if susp_dec.value in ("no", "not_stated"):
            remaining_high_risk.discard("scholarship_suspended")
            updated_statements = [s for s in updated_statements if not _is_susp_stmt(s)]
        elif susp_dec.value == "yes" and susp_dec.quote is not None:
            if not any(_is_susp_stmt(s) for s in updated_statements):
                updated_statements.append(
                    DocumentStatementSpec(
                        kind="OTHER",
                        requirement="REQUIRED",
                        label="Scholarship / Funding Status",
                        text=susp_dec.quote.text[:1000],
                        quote=susp_dec.quote,
                        source_url=primary_url,
                    )
                )
    elif susp_dec and susp_dec.status == "unresolved":
        updated_statements = [s for s in updated_statements if not _is_susp_stmt(s)]
        remaining_unresolved.add("scholarship_suspended")

    return replace(
        tier0,
        costs=tuple(updated_costs),
        eligibility=tuple(updated_elig),
        statements=tuple(updated_statements),
        unresolved_slots=frozenset(remaining_unresolved),
        high_risk_flags=frozenset(remaining_high_risk),
        decisions=tuple(decisions_by_id.values()),
        cost_usd=tier0.cost_usd + extra_cost,
    )


__all__ = [
    "AMBIGUOUS_AMOUNT_SPREAD_PARAMS",
    "APPLICATION_FEE_PARAMS",
    "CLEAN_FREE_TUITION_PARAMS",
    "CONDITIONAL_FREE_TUITION_PARAMS",
    "DEADLINE_PARAMS",
    "DawidSkeneSlotParams",
    "IELTS_BAR_PARAMS",
    "MIN_GPA_PARAMS",
    "ReaderAuditCounts",
    "SCHOLARSHIP_SUSPENDED_PARAMS",
    "SLOT_DEFAULT_PARAMS",
    "calibrate_slot_params",
    "detect_tuition_amount_spread_risk",
    "needs_high_risk_arbitration",
    "refine_with_dual_readers",
    "slot_escalation_bounds",
    "slot_posterior_log_odds",
]
