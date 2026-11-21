"""My list: the student's chosen options grouped by country, and one option's page.

Reads tenant tables only. Everything about a programme or award comes from the
copies the worker wrote onto RecommendationCandidate (``details``, ``fit``,
``funding_card``), never from the catalogue: this runs as ``runtime_web``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from apps.accounts.models import StudentProfileVersion
from apps.documents.referee_needs import needs_for
from apps.documents.table import ROWS, kinds_named
from apps.documents.templatetags.cv_countries import country_name
from apps.funding.models import RecommendationCandidate
from apps.portals.models import Application

from .board import Board, Card

if TYPE_CHECKING:
    from apps.tenancy.models import Membership

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
_KIND_LABELS = dict(ROWS)

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
_DEGREE_LEVELS = {
    "MASTER": "Master's (MSc / MA)",
    "BACHELOR": "Bachelor's",
    "PHD": "PhD / Doctorate",
}
_FAMILIES = {
    "GOVERNMENT_SCHOLARSHIP": "Government scholarship",
    "PRIVATE_FOUNDATION": "Private foundation",
    "DEPARTMENT_OR_PROGRAM": "University / departmental award",
    "INSTITUTIONAL": "University scholarship",
}
_ROUTES = {
    "AUTOMATIC_ON_ADMISSION": "Included with admission (no separate form)",
    "SEPARATE_APPLICATION": "Separate scholarship application",
}
_CAREER_INTENTS = {
    "PHD": "PhD & academic research",
    "INDUSTRY": "Industry & R&D",
    "PUBLIC_SECTOR": "Public sector & policy",
    "ENTREPRENEURSHIP": "Entrepreneurship",
}


@dataclass(frozen=True)
class Missing:
    label: str
    url: str


@dataclass(frozen=True)
class ChecklistItem:
    text: str
    category: str
    status: str
    tone: str
    url: str
    action_label: str


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
            url = f"/student/writing/letters/{card.application_id}/"
        elif kind in ("REFERENCE_LETTER", "RECOMMENDATION"):
            url = f"/student/writing/letters/{card.application_id}/?doc=references"
        elif kind == "CV":
            url = "/student/writing/#drafts"
        else:
            url = card.documents_url
        links.append(Missing(label, url))
    return tuple(links)


def _kind_url(kind: str, card: Card, *, counselor_view: bool) -> tuple[str, str]:
    if counselor_view or not kind:
        return card.documents_url, "Documents"
    if kind == "MOTIVATION_LETTER":
        return f"/student/writing/letters/{card.application_id}/", "CV & letters"
    if kind in ("REFERENCE_LETTER", "RECOMMENDATION"):
        return f"/student/writing/letters/{card.application_id}/?doc=references", "Referees"
    if kind == "CV":
        return "/student/writing/#drafts", "CV & letters"
    return card.documents_url, "Documents"


def checklist_for(card: Card, *, counselor_view: bool = False) -> tuple[ChecklistItem, ...]:
    """Each sentence in `card.requirements` paired with its live status in the student's kit."""
    missing_set = set(card.missing)
    has_doc_tracking = card.documents[1] > 0
    items: list[ChecklistItem] = []
    for sentence in card.requirements:
        matched = sorted(kinds_named(sentence))
        if not matched:
            items.append(ChecklistItem(sentence, "", "", "neutral", "", ""))
            continue
        primary_kind = matched[0]
        label = _KIND_LABELS.get(primary_kind, "")
        url, workspace = _kind_url(primary_kind, card, counselor_view=counselor_view)
        if any(_KIND_LABELS.get(k, "") in missing_set for k in matched):
            items.append(
                ChecklistItem(
                    text=sentence,
                    category=label,
                    status="Missing",
                    tone="warn",
                    url=url,
                    action_label=f"Open {workspace}",
                )
            )
        elif has_doc_tracking:
            items.append(
                ChecklistItem(
                    text=sentence,
                    category=label,
                    status="Ready in kit",
                    tone="ok",
                    url=url,
                    action_label=workspace,
                )
            )
        else:
            items.append(ChecklistItem(sentence, label, "", "neutral", url, workspace))
    return tuple(items)


def profile_alignment_for(
    student: Membership, candidate: RecommendationCandidate | None
) -> tuple[Line, ...]:
    """Student-specific profile context aligned to this candidate (tenant tables only)."""
    profile = StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    snapshot = (profile.snapshot if profile else None) or {}
    if not isinstance(snapshot, dict) or not snapshot:
        return ()
    lines: list[Line] = []
    history = snapshot.get("academic_history")
    if isinstance(history, list) and history and isinstance(history[0], dict):
        first = history[0]
        qual = str(first.get("qualification") or "").strip()
        field = str(first.get("field") or "").strip()
        inst = str(first.get("institution") or "").strip()
        grade = str(first.get("grade") or "").strip()
        scale = str(first.get("grading_scale") or "").strip().removeprefix("0-")
        deg_part = " ".join(p for p in (qual, f"in {field}" if field else "") if p)
        inst_part = f" · {inst}" if inst else ""
        gpa_part = (
            f" (GPA {grade}/{scale})"
            if grade and scale
            else (f" (GPA {grade})" if grade else "")
        )
        if deg_part or inst_part:
            lines.append(Line("Your academic background", f"{deg_part}{inst_part}{gpa_part}"))
    target_field = str(snapshot.get("target_field") or "").strip()
    notes = str(snapshot.get("additional_notes") or "").strip().rstrip(".")
    career_code = str(snapshot.get("career_intent") or "").strip()
    career = _CAREER_INTENTS.get(career_code, "")
    focus_parts = [p for p in (target_field, notes) if p]
    if focus_parts:
        focus_text = " — ".join(focus_parts)
        if career:
            focus_text = f"{focus_text} ({career})"
        lines.append(Line("Your field & research focus", focus_text))
    elif career:
        lines.append(Line("Your career track", career))
    langs = snapshot.get("language_evidence")
    if isinstance(langs, list) and langs and isinstance(langs[0], dict):
        l0 = langs[0]
        lang_name = str(l0.get("language") or "").strip()
        level = str(l0.get("level") or "").strip()
        if lang_name and level:
            lines.append(Line("Your verified language level", f"{lang_name} {level}"))
    if (
        candidate is not None
        and candidate.self_funded is not None
        and not candidate.is_below_fit_bar
    ):
        if candidate.opportunity_id is None and not candidate.funding_gap_is_placeholder:
            lines.append(
                Line(
                    "Your self-funded coverage",
                    f"{candidate.self_funded} {candidate.currency} covered by your stated budget",
                )
            )
    return tuple(lines)


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
    risk_tier: str = ""
    rank: int | None = None
    risk_notes: tuple[str, ...] = ()
    funding_condition: str = ""
    referee_rules: tuple[Line, ...] = ()


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
    ("OTHER", re.compile(r"^OTHER: the page states a condition no key fits; read the sentence$"),
     "Check the official rule above — your counsellor will help confirm if this applies to you"),
    (
        "TALENT",
        re.compile(
            r"^TALENT: the profile does not carry sports or arts achievement; a human decides it$"
        ),
        "Based on sports, arts, or competition achievements — "
        "your counsellor will review this with you",
    ),
    ("NEED", re.compile(r"^NEED: the profile does not carry income; a human decides a means test$"),
     "Based on household financial need — checked during your application"),
    (
        "EMPLOYMENT",
        re.compile(r"^EMPLOYMENT: the profile does not carry an employer; a human decides it$"),
        "Depends on your employer or work status — checked with your counsellor",
    ),
    (
        "AFFINITY",
        re.compile(r"^AFFINITY: a membership the profile does not record; a human decides it$"),
        "Depends on a specific membership or affiliation — check the official rule above",
    ),
    (
        "GUARANTOR",
        re.compile(r"^GUARANTOR: whether a guarantor can be produced is not in the profile$"),
        "Requires a financial guarantor — check the official rule above",
    ),
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


def _referee_lines(candidate: RecommendationCandidate, *, is_award: bool) -> tuple[Line, ...]:
    records = (
        candidate.referee_requirements
        if isinstance(candidate.referee_requirements, list)
        else []
    )
    if not records:
        return ()
    need = needs_for(records, award=is_award)
    pairs = (
        ("Letters required", need.count),
        ("Who writes them", need.kind),
        ("Submission mode", need.mode),
        ("Referee email", need.institutional_email_required),
        ("Referee deadline", need.due),
    )
    return tuple(
        Line(label, stated.rule_text)
        for label, stated in pairs
        if stated is not None and stated.rule_text
    )


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
    if candidate.degree_level:
        deg_label = _DEGREE_LEVELS.get(candidate.degree_level, candidate.degree_level.title())
        facts.append(Line("Degree level", deg_label))
    if is_award and card.get("family"):
        family_label = _FAMILIES.get(str(card.get("family")), "")
        if family_label:
            facts.append(Line("Scholarship type", family_label))
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
    if card.get("route"):
        route_label = _ROUTES.get(str(card.get("route")), "")
        if route_label:
            facts.append(Line("Funding route", route_label))
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
        risk_tier=candidate.risk_tier_label,
        rank=candidate.rank,
        risk_notes=tuple(candidate.risk_notes),
        funding_condition=candidate.funding_condition,
        referee_rules=_referee_lines(candidate, is_award=is_award),
    )
