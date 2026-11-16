"""The profile as a person reads it, grouped by topic (2026-11-16).

`Check your answers` and the Profile page show the same draft answers the wizard
asked for, but grouped (Personal, Education, Experience, ...) with short labels
and plain values: a country by name, money as "400 EUR", a degree as one line.
Nothing here changes an answer; it only formats it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .countries import all_countries
from .forms import PUBLICATION_LEVELS
from .question_widgets import CHOICE_LABELS

SECTIONS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "personal",
        "Personal",
        (
            ("nationality", "Nationality"),
            ("country_of_residence", "Lives in"),
            ("date_of_birth", "Date of birth"),
        ),
    ),
    (
        "education",
        "Education",
        (("academic_history", "Degrees"), ("expected_completion", "Graduation")),
    ),
    (
        "experience",
        "Experience",
        (
            ("work_history", "Work"),
            ("volunteering", "Volunteering"),
            ("publications", "Publications"),
            ("projects", "Projects"),
        ),
    ),
    (
        "plans",
        "Study plans",
        (
            ("target_field", "Wants to study"),
            ("other_target_fields", "Also interested in"),
            ("research_interests", "Directions"),
            ("allowed_countries", "Countries"),
            ("excluded_countries", "Ruled out"),
            ("intended_intake", "Start"),
            ("career_intent", "After the master’s"),
        ),
    ),
    (
        "languages",
        "Languages",
        (
            ("acceptable_teaching_languages", "Can study in"),
            ("language_evidence", "Proof"),
        ),
    ),
    (
        "money",
        "Money",
        (
            ("funding_dependency", "Scholarship"),
            ("self_funding_capacity", "Can pay per year"),
            ("application_budget", "Application fees"),
            ("budget_stretch", "Extra for an exceptional option"),
        ),
    ),
    ("notes", "Anything else", (("additional_notes", "Notes"),)),
)

_ROLE_KIND = {"WORK": "Job", "INTERNSHIP": "Internship", "RESEARCH": "Research"}
_LEVELS = dict(PUBLICATION_LEVELS)
_CAREER = CHOICE_LABELS["career_intent"]
_FUNDING = CHOICE_LABELS["funding_dependency"]


@dataclass(frozen=True)
class Row:
    key: str
    label: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Section:
    slug: str
    title: str
    rows: tuple[Row, ...]


def country_name(code: object) -> str:
    names = dict(all_countries())
    return names.get(str(code), str(code))


def _date(text: object, *, day: bool = True) -> str:
    try:
        when = date.fromisoformat(str(text)[:10])
    except ValueError:
        return str(text)
    return when.strftime("%-d %b %Y" if day else "%b %Y")


def _money(value: object) -> str:
    if not isinstance(value, dict):
        return "None"
    amount = str(value.get("amount", "")).removesuffix(".00")
    return f"{amount} {value.get('currency', '')}".strip()


def _degree(rec: dict[str, object]) -> str:
    head = f"{rec.get('qualification')} {rec.get('field')}, {rec.get('institution')}"
    bits = [f"{head} ({country_name(rec.get('country_code'))})"]
    if rec.get("grade"):
        bits.append(f"grade {rec.get('grade')}/{rec.get('grading_scale')}")
    if rec.get("completed_on"):
        bits.append(f"graduated {_date(rec['completed_on'], day=False)}")
    elif rec.get("expected_completion"):
        bits.append(f"graduating {_date(rec['expected_completion'], day=False)}")
    return " · ".join(bits)


def _role(rec: dict[str, object]) -> str:
    end = _date(rec["end_date"], day=False) if rec.get("end_date") else "now"
    kind = _ROLE_KIND.get(str(rec.get("kind")), "")
    lead = f"{kind}: " if kind else ""
    when = f"{_date(rec.get('start_date'), day=False)} – {end}"
    return f"{lead}{rec.get('title')}, {rec.get('organisation')} · {when}"


def _proof(rec: dict[str, object]) -> str:
    kind = rec.get("evidence_type")
    if kind == "TEST":
        return f"{rec.get('language')}: {rec.get('level')} · by {_date(rec.get('available_by'))}"
    if kind == "DEGREE":
        return f"{rec.get('language')}: my degree was taught in it"
    return f"{rec.get('language')}: {rec.get('level')}"


def _lines(key: str, value: object) -> tuple[str, ...]:
    if value in (None, "", [], {}):
        return {
            "allowed_countries": ("Anywhere",),
            "excluded_countries": ("None",),
            "budget_stretch": ("None",),
            "self_funding_capacity": ("The full cost",),
        }.get(key, ("None",))
    if key in {"nationality", "country_of_residence"}:
        return (country_name(value),)
    if key in {"allowed_countries", "excluded_countries"} and isinstance(value, list):
        return (", ".join(country_name(code) for code in value),)
    if key == "date_of_birth":
        return (_date(value),)
    if key in {"intended_intake", "expected_completion"}:
        return (_date(value, day=False),)
    if key in {"self_funding_capacity", "application_budget", "budget_stretch"}:
        return (_money(value),)
    if key == "career_intent":
        return (_CAREER.get(str(value), str(value)),)
    if key == "funding_dependency":
        return (_FUNDING.get(str(value), str(value)),)
    if isinstance(value, list):
        records = [item for item in value if isinstance(item, dict)]
        if key == "academic_history":
            return tuple(_degree(rec) for rec in records)
        if key in {"work_history", "volunteering"}:
            return tuple(_role(rec) for rec in records)
        if key == "publications":
            return tuple(
                f"{rec.get('title')} — {rec.get('venue')}, {rec.get('year')} · "
                f"{_LEVELS.get(str(rec.get('level')), rec.get('level'))}"
                for rec in records
            )
        if key == "projects":
            return tuple(
                f"{rec.get('title')}{f' ({rec.get('year')})' if rec.get('year') else ''}"
                for rec in records
            )
        if key == "language_evidence":
            return tuple(_proof(rec) for rec in records)
        return (", ".join(str(item) for item in value),)
    return (str(value),)


def review_sections(answers: dict[str, object]) -> tuple[Section, ...]:
    """Every answered question, in its topic, in the order a person reads them."""
    out = []
    for slug, title, keys in SECTIONS:
        rows = tuple(
            Row(key, label, _lines(key, answers[key])) for key, label in keys if key in answers
        )
        if rows:
            out.append(Section(slug, title, rows))
    return tuple(out)


def topic_of(key: str) -> str:
    """The section a question belongs to, shown above it in the wizard."""
    for _slug, title, keys in SECTIONS:
        if any(k == key for k, _label in keys):
            return title
    return ""
