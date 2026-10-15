"""My list: the student's chosen options grouped by country, and one option's page.

Reads tenant tables only. Everything about a programme or award comes from the
copies the worker wrote onto RecommendationCandidate (``details``, ``fit``,
``funding_card``), never from the catalogue: this runs as ``runtime_web``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from apps.documents.table import ROWS
from apps.documents.templatetags.cv_countries import country_name
from apps.funding.models import RecommendationCandidate
from apps.portals.models import Application

from .board import Board, Card

#: Requirement keys in plain words, for the page's requirement list.
KEY_LABELS = {
    "CITIZENSHIP": "Citizenship",
    "RESIDENCE": "Where you live",
    "DESCENT": "Family origin",
    "FIELD": "Field of study",
    "PRIOR_DEGREE": "Previous degree",
    "PRIOR_INSTITUTION": "Where you studied",
    "GRADE": "Grades (GPA)",
    "TALENT": "Talent or achievement",
    "WORK_EXPERIENCE": "Work experience",
    "LANGUAGE": "Language",
    "AGE": "Age",
    "GENDER": "Gender",
    "NEED": "Financial need",
    "REFUGEE_OR_DISPLACED": "Refugee or displaced",
    "DISABILITY": "Disability",
    "EMPLOYMENT": "Employment",
    "AFFINITY": "Membership or affiliation",
    "GUARANTOR": "Guarantor",
    "OPEN": "Open to everyone",
    "OTHER": "Other condition",
    "AGE_CAP": "Age",
    "MEANS_TEST": "Financial need",
    "AFFILIATION": "Membership or affiliation",
}

VERDICTS = {
    "SATISFIED": ("meets", "You meet this"),
    "FAILED": ("fails", "You don’t meet this yet"),
    "UNDECIDABLE": ("unsure", "We can’t tell yet"),
}

_COST_LABELS = {
    "TUITION": "Tuition",
    "HOUSING": "Housing",
    "FOOD": "Food",
    "TRANSPORT": "Transport",
    "UTILITIES": "Utilities",
    "INSURANCE": "Health insurance",
    "OTHER": "Other costs",
}

_COVER_LABELS = {
    "TUITION": "Tuition",
    "STIPEND": "Monthly stipend",
    "ASSISTANTSHIP": "Paid assistantship",
    "HOUSING": "Housing",
    "INSURANCE": "Health insurance",
    "TRAVEL": "Travel",
    "RELOCATION": "Relocation",
    "OTHER": "Other support",
}

_PERIODS = {
    "ONE_OFF": "once",
    "MONTHLY": "a month",
    "ANNUAL": "a year",
    "FULL_PROGRAM": "for the whole programme",
}

_LABEL_KINDS = {label: kind for kind, label in ROWS}

#: The award's stored codes in words. UNSTATED and "" are left off the page.
_TIMING = {
    "PRE_ARRIVAL": "Before you arrive",
    "POST_ARRIVAL": "After you arrive",
    "EITHER": "Before or after you arrive",
}
_CYCLE = {
    "ANNUAL_FIXED": "Once a year, fixed deadline",
    "ROLLING": "Any time (rolling)",
    "WITH_ADMISSION_CYCLE": "With your university application",
    "ONE_OFF": "A one-time call",
}


@dataclass(frozen=True)
class Missing:
    label: str
    url: str


@dataclass(frozen=True)
class Entry:
    card: Card
    is_award: bool
    missing: tuple[Missing, ...]
    detail_url: str


@dataclass(frozen=True)
class CountryGroup:
    code: str
    name: str
    entries: tuple[Entry, ...]


def missing_links(card: Card, *, counselor_view: bool = False) -> tuple[Missing, ...]:
    """Each missing document, linked to the place that makes or takes it."""
    links = []
    for label in card.missing:
        kind = _LABEL_KINDS.get(label, "")
        if counselor_view or not kind:
            url = card.documents_url
        elif kind == "MOTIVATION_LETTER":
            url = f"/student/writing/#letter-{card.application_id}"
        elif kind == "CV":
            url = "/student/writing/#drafts"
        else:
            url = card.documents_url
        links.append(Missing(label, url))
    return tuple(links)


def country_groups(student_id: UUID, board: Board) -> tuple[CountryGroup, ...]:
    awards = set(
        Application.objects.filter(
            student_id=student_id, candidate__opportunity_id__isnull=False
        ).values_list("id", flat=True)
    )
    grouped: dict[str, list[Entry]] = {}
    for card in board.cards:
        grouped.setdefault(card.country, []).append(
            Entry(
                card=card,
                is_award=card.application_id in awards,
                missing=missing_links(card),
                detail_url=f"/student/applications/{card.application_id}/",
            )
        )
    groups = [
        CountryGroup(code, country_name(code) if code else "Other", tuple(entries))
        for code, entries in grouped.items()
    ]
    # Countries by name; options with no country last.
    groups.sort(key=lambda group: (not group.code, group.name))
    return tuple(groups)


def _period(value: object) -> str:
    return _PERIODS.get(str(value), str(value).lower().replace("_", " "))


@dataclass(frozen=True)
class Requirement:
    label: str
    tone: str
    verdict: str
    quote: str
    reason: str


@dataclass(frozen=True)
class Line:
    label: str
    value: str


@dataclass(frozen=True)
class OptionPage:
    """Everything one option's page shows, already in words."""

    candidate: RecommendationCandidate
    is_award: bool
    facts: tuple[Line, ...]
    costs: tuple[Line, ...]
    covers: tuple[Line, ...]
    budget: str
    requirements: tuple[Requirement, ...]
    fits: tuple[str, ...]
    bonds: tuple[str, ...]
    required_documents: tuple[str, ...]
    has_details: bool
    #: A grade bar is among the requirements; else the page says none is stated.
    states_grade: bool


def _reason(text: str) -> str:
    """'GRADE: 89 on 100 against 80' -> '89 on 100 against 80'."""
    head, sep, rest = text.partition(": ")
    return rest if sep and head.isupper() else text


_PLAIN = (
    # (key, pattern over the engine's reason, sentence) -- the reason strings
    # are apps.funding.eligibility.decide's; an unmatched one is shown as is.
    ("GRADE", re.compile(r"^GRADE: (?P<held>\S+) on (?P<scale>.+) against (?P<bar>\S+)$"),
     "Your grade of {held} on a {scale} scale meets the {bar_int} required"),
    ("LANGUAGE", re.compile(r"^LANGUAGE: (?P<lang>\S+) at (?P<held>\S+) against (?P<bar>\S+)$"),
     "Your {lang} at {held} meets the {bar} level required"),
    ("CITIZENSHIP", re.compile(r"^nationality (?P<held>[A-Z]{2}) against "),
     "Your citizenship ({country}) is on the list of countries it accepts"),
    ("RESIDENCE", re.compile(r"^country of residence (?P<held>[A-Z]{2}) against "),
     "You live in a country it accepts ({country})"),
    ("AGE", re.compile(r"^AGE: (?P<held>\d+) against (?P<op>\w+) (?P<bar>[\d.]+)$"),
     "Your age ({held}) is within its limit of {bar_int}"),
    ("PRIOR_DEGREE", re.compile(r"^PRIOR_DEGREE: holds (?P<held>\w+)$"),
     "You hold the {held_lower}'s degree it asks for"),
    ("WORK_EXPERIENCE", re.compile(r"^WORK_EXPERIENCE: (?P<held>\d+) months against (?P<bar>\S+)$"),
     "Your {held} months of experience meet the {bar} required"),
)


def plain_reason(key: str, reason: str) -> str:
    """The engine's reason as a sentence a student reads, or the reason unchanged."""
    for rule_key, pattern, sentence in _PLAIN:
        match = pattern.match(reason) if key == rule_key else None
        if match is None:
            continue
        found = match.groupdict()
        held = found.get("held", "")
        bar = found.get("bar", "")
        return sentence.format(
            **found,
            country=country_name(held) if len(held) == 2 else held,
            bar_int=bar.removesuffix(".0"),
            held_lower=held.lower(),
        )
    return _reason(reason)


def _fit_sentence(key: str, reason: str) -> str:
    return plain_reason(key, reason) if reason else KEY_LABELS.get(key, "This condition")


def option_page(candidate: RecommendationCandidate) -> OptionPage:
    details = candidate.details or {}
    fit = candidate.fit or {}
    card = candidate.funding_card or {}
    is_award = candidate.opportunity_id is not None

    facts: list[Line] = []
    if is_award and details.get("holder"):
        facts.append(Line("Offered by", str(details["holder"])))
    elif candidate.institution_name:
        facts.append(Line("University", candidate.institution_name))
    if candidate.country_code:
        facts.append(Line("Country", country_name(candidate.country_code)))
    if details.get("city"):
        facts.append(Line("City", str(details["city"])))
    if details.get("duration_months"):
        months = int(details["duration_months"])
        facts.append(
            Line("Length", f"{months // 12} years" if months % 12 == 0 and months >= 24
                 else f"{months} months")
        )
    elif details.get("duration_text"):
        facts.append(Line("Length", str(details["duration_text"])))
    if details.get("languages"):
        facts.append(Line("Taught in", ", ".join(str(x) for x in details["languages"])))
    if card.get("deadline"):
        facts.append(Line("Deadline", str(card["deadline"])))
    timing = _TIMING.get(str(details.get("timing", "")), "")
    if timing:
        facts.append(Line("When to apply", timing))
    cycle = _CYCLE.get(str(details.get("cycle", "")), "")
    if cycle:
        facts.append(Line("How often", cycle))
    if candidate.application_fee:
        fee = f"{candidate.application_fee} {candidate.application_fee_currency}"
        facts.append(Line("Application fee", fee))

    costs = tuple(
        Line(
            _COST_LABELS.get(str(c.get("kind")), "Cost"),
            f"{c.get('amount')} {c.get('currency')} {_period(c.get('period'))}",
        )
        for c in details.get("costs", [])
        if isinstance(c, dict)
    )
    covers: list[Line] = []
    for name in ("tuition", "living"):
        if card.get(name) in ("FULL", "PARTIAL"):
            covers.append(
                Line("Tuition" if name == "tuition" else "Living costs",
                     "fully covered" if card[name] == "FULL" else "partly covered")
            )
    for c in details.get("covers", []):
        if isinstance(c, dict) and c.get("amount"):
            covers.append(
                Line(_COVER_LABELS.get(str(c.get("kind")), "Support"),
                     f"{c['amount']} {_period(c.get('period'))}")
            )
    if not covers:
        covers = [Line("Amount", str(line)) for line in card.get("amounts", [])]

    budget = fit.get("budget") or {}
    requirements = tuple(
        Requirement(
            label=KEY_LABELS.get(str(row.get("key")), "Condition"),
            tone=VERDICTS.get(str(row.get("outcome")), ("unsure", ""))[0],
            verdict=VERDICTS.get(str(row.get("outcome")), ("unsure", "We can’t tell yet"))[1],
            quote=str(row.get("quote", "")),
            reason=plain_reason(str(row.get("key")), str(row.get("reason", ""))),
        )
        for row in fit.get("conditions", [])
        if isinstance(row, dict)
    )
    fits = tuple(
        _fit_sentence(str(row.get("key")), str(row.get("reason", "")))
        for row in fit.get("conditions", [])
        if isinstance(row, dict) and row.get("outcome") == "SATISFIED"
    )
    bonds = tuple(
        str(b.get("quote") or f"You must return home for {b.get('months')} months after.")
        for b in details.get("bonds", [])
        if isinstance(b, dict)
    )
    return OptionPage(
        candidate=candidate,
        is_award=is_award,
        facts=tuple(facts),
        costs=costs,
        covers=tuple(covers),
        budget=f"{budget['amount']} {budget['currency']} a year" if budget.get("amount") else "",
        requirements=requirements,
        fits=fits,
        bonds=bonds,
        required_documents=tuple(str(d) for d in details.get("required_documents", [])),
        has_details=bool(details),
        states_grade=any(
            isinstance(row, dict) and row.get("key") == "GRADE"
            for row in fit.get("conditions", [])
        ),
    )
