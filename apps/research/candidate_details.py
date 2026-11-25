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

import re
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from apps.funding.conditions import _decision_for

if TYPE_CHECKING:
    from apps.accounts.schemas import StudentProfileSnapshot
    from apps.funding.evaluation import (
        ApplicantConditionFact,
        AwardCandidateFacts,
        CandidateFacts,
        ReturnServiceFact,
    )

_PORTAL_PLATFORMS: tuple[str, ...] = (
    "uni-assist.de",
    "hochschulstart.de",
    "studielink.nl",
    "dreamapply.com",
    "moveon4.de",
    "moveonnet.eu",
    "smapply.io",
    "smapply.org",
    "smapply.ca",
    "embark.com",
    "applyweb.com",
    "commonapp.org",
    "ucas.com",
    "parcoursup.fr",
    "osiris-student.nl",
    "mobility-online.com",
    "fullfabric.com",
    "submittable.com",
    "universityadmissions.se",
    "antagning.se",
    "opintopolku.fi",
    "samordnaopptak.no",
    "monmaster.gouv.fr",
    "meindaad.de",
    "stipendiumhungaricum.hu",
    "turkiyeburslari.gov.tr",
    "campuschina.org",
)

_PORTAL_HOST_PREFIXES: tuple[str, ...] = (
    "apply.",
    "portal.",
    "bewerbung.",
    "application.",
    "applications.",
    "candidature.",
    "candidatures.",
    "ecandidat.",
    "tumonline.",
    "hisinone.",
    "klips.",
    "campo.",
    "heico.",
    "agnes.",
    "stine.",
    "marvin.",
    "friedolin.",
    "jogustine.",
    "osiris.",
)

_PORTAL_PATH_PATTERN = re.compile(
    r"(?:^|/)(?:apply|portal|bewerbung|bewerben|applications?|online[-_]application|"
    r"candidatures?|e-?candidat|tumonline|hisinone)(?:/|$|\?|#)",
    re.IGNORECASE,
)


def is_portal_url(url: str) -> bool:
    """Whether ``url`` is an https address pointing to an application portal."""
    candidate = url.strip()
    if not candidate or len(candidate) > 500:
        return False
    try:
        parts = urlsplit(candidate)
        _ = parts.port
    except ValueError:
        return False
    if parts.scheme.casefold() != "https" or parts.username or parts.password:
        return False
    host = (parts.hostname or "").rstrip(".").casefold()
    if not host or "." not in host or host.endswith((".invalid", ".arpa", ".localhost")):
        return False
    if any(host == dom or host.endswith(f".{dom}") for dom in _PORTAL_PLATFORMS):
        return True
    if host.startswith(_PORTAL_HOST_PREFIXES):
        return True
    path = parts.path or "/"
    return bool(_PORTAL_PATH_PATTERN.search(path))


def pick_portal_url(urls: Iterable[str]) -> str:
    """Return the first valid portal URL from ``urls``, or ``""``."""
    for raw in urls:
        if not isinstance(raw, str):
            continue
        cleaned = raw.strip()
        if is_portal_url(cleaned):
            return cleaned
    return ""


def _money(amount: object, currency: object) -> str:
    return f"{amount} {currency}" if amount is not None and currency else ""


def _bonds(rows: Sequence[ReturnServiceFact]) -> list[dict[str, object]]:
    return [{"months": row.months, "quote": row.rule_text} for row in rows]


def _benefit_matches_program(benefit: object, facts: CandidateFacts) -> bool:
    scope = getattr(benefit, "scope_type", "GLOBAL")
    if scope == "COUNTRY":
        raw_cc = getattr(benefit, "country_code", None) or ""
        if not raw_cc or not facts.program_country_code:
            return False
        allowed = {c.strip().upper() for c in raw_cc.split(",") if c.strip()}
        return facts.program_country_code.strip().upper() in allowed
    if scope == "CITY":
        return (
            bool(facts.location_key)
            and getattr(benefit, "location_key", None) == facts.location_key
        )
    if scope == "PROGRAM":
        return bool(facts.program_id) and getattr(benefit, "program_id", None) == facts.program_id
    return True


def program_details(facts: CandidateFacts, *, portal_url: str = "") -> dict[str, object]:
    details: dict[str, object] = {
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
            if _benefit_matches_program(benefit, facts)
        ],
        "bonds": _bonds(facts.return_service),
    }
    resolved_portal = pick_portal_url((portal_url,)) if portal_url else ""
    if resolved_portal:
        details["portal_url"] = resolved_portal
    return details


def award_details(facts: AwardCandidateFacts, *, portal_url: str = "") -> dict[str, object]:
    card = facts.card
    details: dict[str, object] = {
        "holder": facts.holder_name,
        "timing": card.timing if card is not None else "",
        "cycle": card.cycle if card is not None else "",
        "duration_text": card.duration_text if card is not None else "",
        "covers": [
            {
                "kind": benefit.kind,
                "amount": _money(benefit.amount, benefit.currency),
                "period": benefit.period,
                **(
                    {"country_code": benefit.country_code}
                    if getattr(benefit, "scope_type", "GLOBAL") == "COUNTRY"
                    and getattr(benefit, "country_code", None)
                    else {}
                ),
                **(
                    {"location_key": benefit.location_key}
                    if getattr(benefit, "scope_type", "GLOBAL") == "CITY"
                    and getattr(benefit, "location_key", None)
                    else {}
                ),
            }
            for benefit in facts.benefits
        ],
        "required_documents": list(card.required_documents) if card is not None else [],
        "bonds": _bonds(facts.return_service),
    }
    resolved_portal = pick_portal_url((portal_url,)) if portal_url else ""
    if resolved_portal:
        details["portal_url"] = resolved_portal
    return details


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
