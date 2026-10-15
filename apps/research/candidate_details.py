"""What the scholarship page shows about one option, and why the student fits it.

Built in the worker at publish time from the same facts the evaluator decided
on, and copied onto the tenant's RecommendationCandidate: the web tier renders
it and never reads the catalogue (CLAUDE.md, the catalogue boundary).

Two halves, kept apart because they are different kinds of data:

* ``details`` -- facts about the programme or award (city, length, languages,
  costs, what it covers, a return-home bond). The same for every student.
* ``fit`` -- each published condition decided against THIS student's profile.
  It carries the student's own grade, language level and nationality in its
  reasons, so it is erased with them (audit.redaction).

Pure: no database access, so it is tested against plain facts.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from apps.funding.conditions import _decision_for

if TYPE_CHECKING:
    from apps.accounts.schemas import StudentProfileSnapshot
    from apps.funding.evaluation import (
        ApplicantConditionFact,
        AwardCandidateFacts,
        CandidateFacts,
        ReturnServiceFact,
    )


def _money(amount: object, currency: object) -> str:
    return f"{amount} {currency}" if amount is not None and currency else ""


def _bonds(rows: Sequence[ReturnServiceFact]) -> list[dict[str, object]]:
    return [{"months": row.months, "quote": row.rule_text} for row in rows]


def program_details(facts: CandidateFacts) -> dict[str, object]:
    return {
        "city": facts.city,
        "duration_months": facts.duration_months,
        "languages": list(facts.teaching_languages),
        "costs": [
            {
                "kind": cost.kind,
                "amount": str(cost.amount),
                "currency": cost.currency,
                "period": cost.period,
            }
            for cost in facts.cost_components
            if cost.kind != "APPLICATION_FEE"
        ],
        "covers": [
            {
                "kind": benefit.kind,
                "amount": _money(benefit.amount, benefit.currency),
                "period": benefit.period,
            }
            for benefit in facts.benefits
        ],
        "bonds": _bonds(facts.return_service),
    }


def award_details(facts: AwardCandidateFacts) -> dict[str, object]:
    card = facts.card
    return {
        "holder": facts.holder_name,
        "timing": card.timing if card is not None else "",
        "cycle": card.cycle if card is not None else "",
        "duration_text": card.duration_text if card is not None else "",
        "covers": [
            {
                "kind": benefit.kind,
                "amount": _money(benefit.amount, benefit.currency),
                "period": benefit.period,
            }
            for benefit in facts.benefits
        ],
        "required_documents": list(card.required_documents) if card is not None else [],
        "bonds": _bonds(facts.return_service),
    }


def fit_for(
    conditions: Sequence[ApplicantConditionFact], profile: StudentProfileSnapshot | None
) -> list[dict[str, str]]:
    """Each condition the page states, decided against the student.

    The same decision the evaluator made (one engine, ``conditions._decision_for``),
    so the page can never say "you fit" about a condition the pack failed on.
    Without a full profile nothing is decided, and nothing is claimed.
    """
    if profile is None:
        return []
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for condition in conditions:
        decision = _decision_for(condition, profile)
        key = condition.key or condition.condition_type
        # The same sentence attached to two benefits is one requirement.
        if (key, condition.rule_text) in seen:
            continue
        seen.add((key, condition.rule_text))
        rows.append(
            {
                "key": key,
                "outcome": decision.outcome,
                "quote": condition.rule_text[:600],
                "reason": decision.reason[:300],
            }
        )
    return rows


def budget_line(profile: StudentProfileSnapshot | None) -> dict[str, str]:
    """What the student said they can pay a year, for the page's cost box."""
    if profile is None or profile.self_funding_capacity is None:
        return {}
    capacity = profile.self_funding_capacity
    return {"amount": str(capacity.amount), "currency": capacity.currency}
