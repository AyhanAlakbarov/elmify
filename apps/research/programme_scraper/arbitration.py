"""Tier 1 dual-reader refinement and Tier 2 risk-asymmetric arbitration."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from apps.research.card_engine import (
    Decision,
    Limit,
    Quote,
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
from apps.research.card_engine.screen import Screen

from .extractors import _candidates_with_header_currency
from .patterns import _CONDITIONAL_GUARD_RE
from .specs import (
    CostComponentSpec,
    ProgrammeBundle,
    ProgrammeQuestionSet,
    ProgrammeScrapeResult,
)


def needs_high_risk_arbitration(
    decisions: Sequence[Decision],
    section: Section,
) -> tuple[str, ...]:
    """Return question IDs that must be escalated to the frontier decider even when the
    two cheap readers agreed (`status == "agreed"`), because the claim is a high-consequence
    financial assertion made on a section containing conditional/exception language."""
    section_text = " ".join(f"{line.heading} {line.header} {line.text}" for line in section.lines)
    has_conditions = bool(_CONDITIONAL_GUARD_RE.search(section_text))
    escalate: list[str] = []
    for dec in decisions:
        if dec.status != "agreed":
            continue
        if (
            dec.question == "tuition_free_all_internationals"
            and dec.value == "yes"
            and has_conditions
        ):
            escalate.append(dec.question)
    return tuple(escalate)


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
    kwargs: dict[str, object] = {
        "screen": screen,
        "limit": limit,
        "readers": active_readers,
    }
    if transport is not None:
        kwargs["transport"] = transport

    reading = read(qset, bundle.section, **kwargs)  # type: ignore[arg-type]
    decisions_by_id = {d.question: d for d in reading.decisions}
    extra_cost = sum(c.cost_usd or 0.0 for c in reading.calls)

    # Tier 2 Risk-Asymmetric Arbitration: escalate high-risk agreed claims to decider
    risk_qids = needs_high_risk_arbitration(reading.decisions, bundle.section)
    if risk_qids and transport is not None:
        risk_qs = [q for q in asked if q.id in risk_qids]
        dec_prompt = _prompt(qset, bundle.section, candidates, {}, risk_qs)
        reply, made = _ask(
            active_readers.decider,
            dec_prompt,
            risk_qs,
            limit,
            transport,
            first_raises=False,
        )
        extra_cost += sum(c.cost_usd or 0.0 for c in made)
        if reply is not None:
            for rq in risk_qs:
                given = [a for a in reply.answers if a.id == rq.id and a.value in rq.options]
                if given:
                    q_loc = (
                        locate(given[0].quote, bundle.section)
                        if given[0].value not in rq.unquoted
                        else None
                    )
                    decisions_by_id[rq.id] = Decision(
                        question=rq.id,
                        status="decided",
                        value=given[0].value,
                        quote=q_loc,
                        answers=decisions_by_id[rq.id].answers,
                    )

    updated_costs = list(tier0.costs)
    remaining_unresolved = set(tier0.unresolved_slots)
    primary_url = bundle.page_urls[0] if bundle.page_urls else ""

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
                raw_per = (
                    per_dec.value
                    if (
                        per_dec
                        and per_dec.value
                        in ("ANNUAL", "SEMESTER", "PER_ECTS", "FULL_PROGRAM", "MONTHLY")
                    )
                    else "ANNUAL"
                )
                if raw_per == "PER_ECTS":
                    final_amt = amt_obj.low * Decimal(60)
                    final_per = "ANNUAL"
                elif raw_per == "SEMESTER":
                    final_amt = amt_obj.low * Decimal(2)
                    final_per = "ANNUAL"
                else:
                    final_amt = amt_obj.low
                    final_per = raw_per
                line_idx = found_amt.line
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

    return replace(
        tier0,
        costs=tuple(updated_costs),
        unresolved_slots=frozenset(remaining_unresolved),
        decisions=tuple(decisions_by_id.values()),
        cost_usd=tier0.cost_usd + extra_cost,
    )


__all__ = [
    "needs_high_risk_arbitration",
    "refine_with_dual_readers",
]
