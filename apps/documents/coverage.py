"""What a programme's page says about how much history a CV covers, and the
items those rules (and the relevance engine) may act on.

Pure: no database, no model. selection.py applies it at generation, and
render.py's checkers read it at render.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from .constraints import CAP_SECTIONS, ConstraintRule
from .hygiene import normalize_text
from .schemas import CVContent, EducationEntry

#: Further back keeps more. Two cv_start sentences on one page settle on the
#: one that reaches furthest, because leaving a period off is the failure a
#: programme rejects for, and an extra old entry is not.
_START_REACH = {"upper_secondary": 3, "first_degree": 2, "last_n_years": 1}


@dataclass(frozen=True)
class Coverage:
    complete: bool = False
    start: str = ""
    years: int = 0
    caps: tuple[tuple[str, int], ...] = ()


def coverage_of(rules: Iterable[ConstraintRule]) -> Coverage:
    """The page's coverage rules, settled on the side that keeps more.

    A malformed value is skipped, never raised: every one of these rules is a
    page reading (ADVISORY_HIGH_RISK), and skipping one keeps everything,
    which is the safe direction.
    """
    complete = False
    start, years = "", 0
    caps: dict[str, int] = {}
    for rule in rules:
        value = rule.value
        if rule.key == "cv_scope":
            complete = complete or value == "complete"
        elif rule.key == "cv_start" and isinstance(value, dict):
            kind = str(value.get("start") or value.get("milestone") or "")
            n = value.get("years", 0)
            if not kind and isinstance(n, int) and n > 0:
                kind = "last_n_years"
            if kind not in _START_REACH:
                continue
            if kind == "last_n_years" and not (isinstance(n, int) and n > 0):
                continue
            if (
                not start
                or _START_REACH[kind] > _START_REACH[start]
                or (kind == start == "last_n_years" and isinstance(n, int) and n > years)
            ):
                start, years = kind, (n if kind == "last_n_years" and isinstance(n, int) else 0)
        elif rule.key == "cv_item_cap" and isinstance(value, dict):
            section, n = value.get("section"), value.get("max")
            if section in CAP_SECTIONS and isinstance(n, int) and not isinstance(n, bool) and n > 0:
                caps[str(section)] = max(n, caps.get(str(section), 0))
    return Coverage(complete, start, years, tuple(sorted(caps.items())))


#: A school-leaving entry, in the languages the first students' documents use.
#: Bare "school" is absent on purpose ("Baku Higher Oil School" is a
#: university), and so is "baccalaur" (Quebec's baccalauréat is a bachelor's).
#: ponytail: a word list; a school spelled otherwise is asked about again by
#: the upper-secondary gap question, which costs a question, never a fact.
_SECONDARY = re.compile(
    r"\b(secondary|high school|school[- ]leaving|lyceum|lyc[ée]e|gymnasium|abitur|attestat"
    r"|matura|a[- ]levels?|orta m[əe]kt[əe]b|lisey|lise|лицей|школа|аттестат)\b",
    re.IGNORECASE,
)


def is_secondary(entry: EducationEntry) -> bool:
    return bool(
        _SECONDARY.search(entry.degree_as_awarded) or _SECONDARY.search(entry.institution_original)
    )


#: Language tests by name (R-041: they belong in Languages). Used to drop a
#: certification that duplicates a Languages entry, and to keep every
#: language test away from the relevance engine (question doc: "always kept").
LANGUAGE_TEST = re.compile(
    r"\b(ielts|toefl|testdaf|dsh|delf|dalf|tcf|tef|dele|t[öo]mer|goethe|telc|"
    r"duolingo english test|pte academic|cambridge (?:english|c1|c2|b2)|hsk|jlpt|topik|"
    r"cils|celi)\b",
    re.IGNORECASE,
)


def item_digest(section: str, text: str) -> str:
    """What the put-back store and the relevance cache key on. Case and
    spacing never make a new item; the section does."""
    folded = " ".join(normalize_text(text).casefold().split())
    return hashlib.sha256(f"{section}\n{folded}".encode()).hexdigest()


@dataclass(frozen=True)
class Item:
    """One whole optional entry: the unit the engine keeps or leaves out.

    `field` and `index` name the entry in CVContent; `text` is the student's
    own words on one line (what Jev reads, and what "left out" shows);
    `when` is the latest date the entry carries, for "most recent" and for a
    cv_start window.
    """

    section: str
    field: str
    index: int
    text: str
    when: date | None

    @property
    def digest(self) -> str:
        return item_digest(self.section, self.text)


def _line(*parts: str | None, when: date | None = None) -> str:
    text = ", ".join(p for p in parts if p)
    return f"{text} ({when.year})" if when else text


def items_of(content: CVContent) -> tuple[Item, ...]:
    """Every entry a page cap or the relevance engine may act on.

    Never education, languages, references, the summary or a gap statement:
    those are not optional (spec §7.2), and a gap statement accounts for a
    period the CV must cover (spec §9).
    """
    found: list[Item] = []
    for index, entry in enumerate(content.experience):
        when = entry.end_date or entry.start_date
        found.append(Item(
            "volunteering" if entry.unpaid else "experience", "experience", index,
            _line(entry.title, entry.employer, when=when), when,
        ))
    for index, research in enumerate(content.research):
        when = research.end_date or research.start_date
        found.append(
            Item("research", "research", index, _line(research.thesis_title, when=when), when)
        )
    for index, publication in enumerate(content.publications):
        when = date(publication.year, 1, 1) if publication.year else None
        found.append(Item(
            "publications", "publications", index, _line(publication.title, when=when), when,
        ))
    for index, award in enumerate(content.awards):
        found.append(Item(
            "awards", "awards", index, _line(award.title, award.awarding_body, when=award.date),
            award.date,
        ))
    for index, cert in enumerate(content.certifications):
        found.append(Item(
            "certifications", "certifications", index,
            _line(cert.title, cert.issuer, when=cert.date), cert.date,
        ))
    for index, project in enumerate(content.projects):
        when = project.end_date or project.start_date
        found.append(Item(
            "projects", "projects", index, _line(project.title, when=when), when,
        ))
    for index, skill in enumerate(content.skills):
        found.append(Item("skills", "skills", index, skill.name, None))
    return tuple(found)
