"""One eligibility vocabulary: who an award or a programme is open to.

Spec: docs/superpowers/specs/2026-09-19-eligibility-vocabulary-and-register-amendment-design.md

Four partial vocabularies existed before this module and none was the one the
specs named -- the catalog stored six condition types, the evaluator read the
same six, the validity function used seven different ones for whose-deadline,
and the engine design listed eighteen keys in prose. A writer for those would
have written in one language and been read in another.

Pure: no Django import, so the judge (research) and the evaluator (funding) can
both import it without a direction problem, and every decider is testable
against a plain profile object.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import date as _date
from functools import cache
from math import isfinite
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from apps.funding.regions import REGIONS

Key = Literal[
    #: Who the award is for. A country set decides these three.
    "CITIZENSHIP",
    "RESIDENCE",
    "DESCENT",
    #: What the applicant has studied or achieved.
    "FIELD",
    "PRIOR_DEGREE",
    "PRIOR_INSTITUTION",
    #: A numeric bar on a named grading scale. Built as TALENT; renamed by owner
    #: decision 2026-09-22 while BenefitRule held zero rows, because two
    #: unrelated conditions were sharing one key.
    "GRADE",
    #: Sports or arts talent, a label form -- nothing in the profile decides it.
    "TALENT",
    "WORK_EXPERIENCE",
    "LANGUAGE",
    #: Who the applicant is. None of these is decidable from a profile that
    #: does not carry the field, and each says so rather than guessing.
    "AGE",
    "GENDER",
    "NEED",
    "REFUGEE_OR_DISPLACED",
    "DISABILITY",
    "EMPLOYMENT",
    "AFFINITY",
    "GUARANTOR",
    #: The page says "open to all" -- an answer, not an absence.
    "OPEN",
    #: A stated condition no key fits. Kept with its sentence, always
    #: undecidable, never dropped.
    "OTHER",
]
KEYS: tuple[str, ...] = get_args(Key)

Operator = Literal["IN", "NOT_IN", "EQ", "GTE", "LTE", "PRESENT"]
OPERATORS: tuple[str, ...] = get_args(Operator)

#: MONTHS/HOURS for WORK_EXPERIENCE, YEARS for AGE. A means test's currency
#: travels inside `value` ("12000 EUR"): a closed unit list cannot carry 180
#: currency codes and an open one would defeat the schema.
Unit = Literal["MONTHS", "HOURS", "YEARS"]

Outcome = Literal["SATISFIED", "FAILED", "UNDECIDABLE"]


class ConditionTriple(BaseModel):
    """One condition as a page states it, in the closed vocabulary.

    `value` is carried as written text rather than a parsed structure: a country
    set is "AZ,TR" or "WESTERN_BALKANS", a bar is "35", a level is "C1". Parsing
    belongs to the decider that knows the key, and keeping the raw form means a
    re-read compares like with like.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Key
    operator: Operator
    value: str = Field(default="", max_length=200)
    unit: Unit | None = None
    #: The sentence the page printed, verbatim. Quote verification covers it.
    quote: str = Field(min_length=1, max_length=4_000)


@dataclass(frozen=True)
class Decision:
    """Three values, never two.

    UNDECIDABLE is not a soft FAILED: passing a condition silently offers a
    route that may be shut, failing one silently hides a route that may be
    open, and the reason is what a consultant acts on.
    """

    outcome: Outcome
    reason: str


_COUNTRY_GROUPS_CSV = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "country-groups.csv"
)

_REGION_KEY_ALIASES: dict[str, str] = {
    "OECD_DAC": "DAC",
    "OECD DAC": "DAC",
    "ODA": "DAC",
    "OTS": "TURKIC_STATES",
    "ORGANIZATION_OF_TURKIC_STATES": "TURKIC_STATES",
    "COMMONWEALTH_OF_INDEPENDENT_STATES": "CIS",
    "SUB_SAHARAN_AFRICA": "SSA",
    "LEAST_DEVELOPED_COUNTRIES": "LDC",
}


@cache
def _country_group_eligible_codes() -> dict[str, tuple[str, ...]]:
    """Read eligible ISO country sets for `CIS`, `DAC`, `LDC`, `SSA`, `LMY` from
    `docs/research/country-groups.csv` so `expand_countries` can expand group names
    written by `card_funding.store` without duplicating or overriding `groups.py`."""
    out: dict[str, list[str]] = {}
    if not _COUNTRY_GROUPS_CSV.exists():
        return {}
    with _COUNTRY_GROUPS_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "eligible":
                continue
            grp = (row.get("group") or "").strip().upper()
            if not grp:
                continue
            bucket = out.setdefault(grp, [])
            for code in (row.get("codes") or "").split():
                c = code.strip().upper()
                if len(c) == 2 and c.isascii() and c.isalpha() and c not in bucket:
                    bucket.append(c)
    return {k: tuple(sorted(v)) for k, v in out.items()}


@cache
def _all_cldr_country_codes() -> tuple[str, ...]:
    from babel import Locale

    codes = {
        code.upper()
        for code in Locale.parse("en").territories
        if isinstance(code, str) and len(code) == 2 and code.isascii() and code.isalpha()
    }
    for region in REGIONS.values():
        codes.update(region.countries)
    for grp_codes in _country_group_eligible_codes().values():
        codes.update(grp_codes)
    return tuple(sorted(codes))


def _expand_single_region_or_code(token: str) -> tuple[str, ...] | None:
    cleaned = token.strip()
    if not cleaned:
        return None
    if cleaned.upper().startswith("ISO2:"):
        payload = cleaned[5:].strip().upper()
        if payload and len(payload) % 2 == 0 and payload.isascii() and payload.isalpha():
            return tuple(payload[i : i + 2] for i in range(0, len(payload), 2))
        return None
    upper = re.sub(r"[\s\-]+", "_", cleaned.upper())
    if upper in ("ALL_COUNTRIES", "WORLD"):
        return _all_cldr_country_codes()
    upper = _REGION_KEY_ALIASES.get(upper, _REGION_KEY_ALIASES.get(cleaned.upper(), upper))
    region = REGIONS.get(upper)
    if region is not None:
        return region.countries
    grp_codes = _country_group_eligible_codes().get(upper)
    if grp_codes is not None:
        return grp_codes
    if len(cleaned) == 2 and cleaned.isascii() and cleaned.isalpha():
        return (cleaned.upper(),)
    return None


def expand_countries(value: str) -> tuple[str, ...] | None:
    """A country set from ISO codes or named regions, or None if any part is unknown.

    None, never a partial answer: a region this build does not know must make
    its condition undecidable rather than silently matching nobody.
    """
    text = value.strip()
    if not text:
        return None
    single = _expand_single_region_or_code(text)
    if single is not None:
        return single
    parts = [p.strip() for p in re.split(r"[,/]", text) if p.strip()]
    if not parts:
        return None
    combined: list[str] = []
    for part in parts:
        expanded = _expand_single_region_or_code(part)
        if expanded is None:
            return None
        for code in expanded:
            if code not in combined:
                combined.append(code)
    return tuple(combined) if combined else None


#: What a deadline row's condition partitions on. Not eligibility: these say
#: WHOSE deadline a date is, and validity.select_deadline reads them.
DEADLINE_PARTITION_KEYS: tuple[str, ...] = ("APPLICANT_CLASS", "FUNDING", "ROUTE", "ROUND")

#: CEFR is the one language scale two sides can be compared on. "mother tongue",
#: "fluent" and a test score are not points on it, so a bar stated against them
#: escalates rather than being ranked on a guess.
_CEFR = ("A1", "A2", "B1", "B2", "C1", "C2")
_DEGREE_ORDER = ("BACHELOR", "MASTER", "DOCTORATE")
#: Substrings that identify a degree level in a qualification a student typed.
#: "diplom" (the German Diplom) is handled separately, as a bounded word: a bare
#: substring check reads "Diploma in Nursing" as containing it.
_DEGREE_WORDS = {
    "BACHELOR": (
        "bachelor",
        "bsc",
        "b.sc",
        "ba ",
        "b.a",
        "b.s",
        "beng",
        "b.eng",
        "llb",
        "ll.b",
        "licence",
        "lisans",
        "bakalavr",
        "бакалавр",
    ),
    "MASTER": (
        "master",
        "msc",
        "m.sc",
        "m.a",
        "m.s",
        "meng",
        "m.eng",
        "mba",
        "m.b.a",
        "mphil",
        "m.phil",
        "mres",
        "m.res",
        "llm",
        "ll.m",
        "magister",
        "magistr",
        "yüksek lisans",
        "yuksek lisans",
        "магистр",
        "специалист",
    ),
    "DOCTORATE": (
        "doctor",
        "phd",
        "ph.d",
        "dphil",
        "d.phil",
        "doktor",
        "doktora",
        "кандидат наук",
        "доктор наук",
    ),
}
_DEGREE_BOUNDED_ABBRS = {
    "BACHELOR": ("ba", "bs", "bsc", "beng", "llb"),
    "MASTER": ("ma", "ms", "msc", "meng", "mba", "mphil", "mres", "llm"),
    "DOCTORATE": ("phd", "dphil", "md"),
}

#: The operators spec §2.1 permits for a key that can decide differently by
#: operator. A key absent here (OPEN, DESCENT, and the eight never-decidable
#: keys) answers the same way whatever operator a page used, so it is never
#: checked against this table. An operator outside a listed key's set must
#: reach a human rather than be silently read as whichever comparison this
#: module happens to run for that key. (TALENT left this table with the rename:
#: it is a label form now and answers UNDECIDABLE whatever operator a page used,
#: so constraining its operator would only change which sentence it says.)
#: WORK_EXPERIENCE LTE, the ordinary way
#: a page writes "no more than two years", would otherwise be answered by the
#: GTE logic below.
_OPERATORS_BY_KEY: dict[str, tuple[str, ...]] = {
    "CITIZENSHIP": ("IN", "NOT_IN"),
    "RESIDENCE": ("IN", "NOT_IN", "PRESENT"),
    "FIELD": ("IN",),
    "PRIOR_DEGREE": ("GTE", "EQ", "LTE", "NOT_IN"),
    "PRIOR_INSTITUTION": ("IN", "NOT_IN", "EQ"),
    "GRADE": ("GTE", "LTE"),
    "WORK_EXPERIENCE": ("GTE",),
    "LANGUAGE": ("PRESENT", "GTE"),
    "AGE": ("LTE", "GTE"),
    "GENDER": ("EQ",),
}


def _undecidable(reason: str) -> Decision:
    return Decision("UNDECIDABLE", reason)


def _verdict(satisfied: bool, reason: str) -> Decision:
    return Decision("SATISFIED" if satisfied else "FAILED", reason)


def _parse_finite(text: str) -> float | None:
    """float(text), rejecting inf/-inf/nan and a literal that overflows to them.

    float() alone accepts "inf", "-inf", "nan", "Infinity" and "1e400" without
    raising, so an untrusted bar could otherwise force SATISFIED or FAILED past
    the UNDECIDABLE valve instead of reaching a human.
    """
    cleaned = text.strip()
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if isfinite(value) else None


def _bounded_word(text: str, word: str) -> bool:
    """`word` occurs in `text` without being glued to a letter on either side.

    A plain substring check reads "Diploma in Nursing" as containing "diplom",
    or "AI" as present in "Ukrainian studies" -- both glued to a letter, never
    the whole word a page actually meant.
    """
    start = 0
    while True:
        idx = text.find(word, start)
        if idx == -1:
            return False
        before = text[idx - 1] if idx > 0 else ""
        after_at = idx + len(word)
        after = text[after_at] if after_at < len(text) else ""
        if not before.isalpha() and not after.isalpha():
            return True
        start = idx + 1


def _field_matches(a: str, b: str) -> bool:
    """The shorter of two field names must appear in the longer as a whole word.

    Unbounded, "AI" matches "Ukrainian studies" and "IT" matches almost
    anything; since no match is UNDECIDABLE (a human reads it), a false
    positive here is the only way this comparison can be wrong.
    """
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return bool(shorter) and _bounded_word(longer, shorter)


def _country_decision(condition: ConditionTriple, held: str, field_name: str) -> Decision:
    countries = expand_countries(condition.value)
    if countries is None:
        return _undecidable(
            f"{condition.key}: '{condition.value}' is not a country list this build knows"
        )
    if not held:
        return _undecidable(f"{condition.key}: the profile does not carry {field_name}")
    inside = held.upper() in countries
    satisfied = inside if condition.operator != "NOT_IN" else not inside
    return _verdict(
        satisfied, f"{condition.key}: {field_name} {held.upper()} against {condition.value}"
    )


def _is_diplom(text: str) -> bool:
    """"diplom" (the German Diplom, a Master's-equivalent), never "diploma" or
    "diplomarbeit" (a thesis, not a degree). This is its own rule rather than a
    _DEGREE_WORDS entry or a call to the shared _bounded_word: the German and
    English words differ by exactly one trailing letter, "a" -- "Diplomingenieur"
    and "Diplom-Ingenieur" must both match, so the boundary check on the right
    side has to single out that one letter rather than reject every glued
    right side the way _bounded_word does for FIELD's word-boundary match.
    """
    idx = text.find("diplom")
    while idx != -1:
        start_ok = idx == 0 or not text[idx - 1].isalpha()
        after = idx + len("diplom")
        followed_by_a = after < len(text) and text[after] == "a"
        if start_ok and not followed_by_a:
            return True
        idx = text.find("diplom", idx + 1)
    return False


def _degree_level(qualification: str) -> str | None:
    text = qualification.casefold()
    for level in reversed(_DEGREE_ORDER):
        if any(word in text for word in _DEGREE_WORDS[level]):
            return level
        if any(_bounded_word(text, abbr) for abbr in _DEGREE_BOUNDED_ABBRS[level]):
            return level
        if level == "MASTER" and _is_diplom(text):
            return level
    return None


def _split_scale(value: str) -> tuple[str, str]:
    """"3.0 GPA 4.0" -> ("3.0", "GPA 4.0") and "3.0/4.0" -> ("3.0", "4.0")."""
    cleaned = value.strip()
    if "/" in cleaned and " " not in cleaned:
        head, _, tail = cleaned.partition("/")
        return head.strip(), tail.strip()
    head, _, tail = cleaned.partition(" ")
    if "/" in head and not tail:
        h2, _, t2 = head.partition("/")
        return h2.strip(), t2.strip()
    return head.strip(), tail.strip()


_SCALE_ALIASES: dict[str, str] = {
    "4": "gpa 4.0",
    "4.0": "gpa 4.0",
    "0-4": "gpa 4.0",
    "0-4.0": "gpa 4.0",
    "0.0-4.0": "gpa 4.0",
    "out of 4": "gpa 4.0",
    "out of 4.0": "gpa 4.0",
    "gpa 4": "gpa 4.0",
    "gpa 4.0": "gpa 4.0",
    "cgpa 4": "gpa 4.0",
    "cgpa 4.0": "gpa 4.0",
    "4.0 gpa": "gpa 4.0",
    "4.00": "gpa 4.0",
    "4.3": "gpa 4.3",
    "4.30": "gpa 4.3",
    "0-4.3": "gpa 4.3",
    "0.0-4.3": "gpa 4.3",
    "out of 4.3": "gpa 4.3",
    "gpa 4.3": "gpa 4.3",
    "cgpa 4.3": "gpa 4.3",
    "4.3 gpa": "gpa 4.3",
    "4.5": "gpa 4.5",
    "4.50": "gpa 4.5",
    "0-4.5": "gpa 4.5",
    "0.0-4.5": "gpa 4.5",
    "out of 4.5": "gpa 4.5",
    "gpa 4.5": "gpa 4.5",
    "cgpa 4.5": "gpa 4.5",
    "4.5 gpa": "gpa 4.5",
    "5": "5.0",
    "5.0": "5.0",
    "0-5": "5.0",
    "0-5.0": "5.0",
    "2-5": "5.0",
    "2.0-5.0": "5.0",
    "3-5": "5.0",
    "3.0-5.0": "5.0",
    "out of 5": "5.0",
    "out of 5.0": "5.0",
    "gpa 5.0": "5.0",
    "cgpa 5": "5.0",
    "cgpa 5.0": "5.0",
    "1-5": "german 1-5",
    "1.0-5.0": "german 1-5",
    "1,0-5,0": "german 1-5",
    "german 1-5": "german 1-5",
    "german 1.0-5.0": "german 1-5",
    "6": "6.0",
    "6.0": "6.0",
    "1-6": "6.0",
    "1.0-6.0": "6.0",
    "1,0-6,0": "6.0",
    "2-6": "6.0",
    "2.0-6.0": "6.0",
    "out of 6": "6.0",
    "out of 6.0": "6.0",
    "swiss 1-6": "6.0",
    "7": "7.0",
    "7.0": "7.0",
    "0-7": "7.0",
    "1-7": "7.0",
    "1.0-7.0": "7.0",
    "out of 7": "7.0",
    "out of 7.0": "7.0",
    "gpa 7": "7.0",
    "gpa 7.0": "7.0",
    "cgpa 7": "7.0",
    "cgpa 7.0": "7.0",
    "9": "9.0",
    "9.0": "9.0",
    "0-9": "9.0",
    "1-9": "9.0",
    "out of 9": "9.0",
    "out of 9.0": "9.0",
    "gpa 9": "9.0",
    "gpa 9.0": "9.0",
    "cgpa 9": "9.0",
    "cgpa 9.0": "9.0",
    "10": "10.0",
    "10.0": "10.0",
    "cgpa 10": "10.0",
    "cgpa 10.0": "10.0",
    "gpa 10": "10.0",
    "gpa 10.0": "10.0",
    "0-10": "10.0",
    "1-10": "10.0",
    "out of 10": "10.0",
    "out of 10.0": "10.0",
    "12": "12.0",
    "12.0": "12.0",
    "-3-12": "12.0",
    "02-12": "12.0",
    "2-12": "12.0",
    "out of 12": "12.0",
    "danish 12": "12.0",
    "7-step": "12.0",
    "20": "20.0",
    "20.0": "20.0",
    "0-20": "20.0",
    "1-20": "20.0",
    "out of 20": "20.0",
    "out of 20.0": "20.0",
    "30": "30.0",
    "30.0": "30.0",
    "0-30": "30.0",
    "18-30": "30.0",
    "out of 30": "30.0",
    "100": "100",
    "100.0": "100",
    "100%": "100",
    "%": "100",
    "0-100": "100",
    "1-100": "100",
    "out of 100": "100",
    "percentage": "100",
    "percent": "100",
    "110": "110",
    "110.0": "110",
    "66-110": "110",
    "out of 110": "110",
}


def _normalize_scale(raw: str) -> str:
    folded = " ".join(raw.strip().lstrip("/").split()).casefold()
    folded = re.sub(r"^(?:on(?:\s+a)?|out\s+of)\s+", "", folded)
    folded = re.sub(r"(?:[\s-]+point)?\s+scale$", "", folded)
    return _SCALE_ALIASES.get(folded, folded)


_NON_LANGUAGE_TOKENS: frozenset[str] = frozenset(
    {
        "unstated_language",
        "a1",
        "a2",
        "b1",
        "b2",
        "c1",
        "c2",
        "ielts",
        "toefl",
        "pte",
        "duolingo",
        "cambridge",
        "cae",
        "cpe",
        "fce",
        "pet",
        "ket",
        "testdaf",
        "dsh",
        "goethe",
        "ösd",
        "osd",
        "telc",
        "delf",
        "dalf",
        "tcf",
        "tef",
        "dele",
        "siele",
        "cils",
        "celi",
        "plida",
        "torfl",
        "trki",
        "трки",
        "тэу",
        "тбу",
        "tömer",
        "tomer",
        "yökdil",
        "hsk",
        "jlpt",
        "topik",
    }
)


def _extract_test_and_score(raw_level: str) -> tuple[str, float] | None:
    lower = " ".join(raw_level.strip().split()).casefold()
    m_jlpt = re.search(r"\b(?:jlpt\s*)?n\s*([1-5])\b", lower)
    if m_jlpt and ("jlpt" in lower or re.search(r"\bn[1-5]\b", lower)):
        # Higher JLPT proficiency is lower N-number (N1=highest, N5=lowest); store
        # inverted (6 - N) so `held >= wanted` holds in `_decide_language`.
        return "jlpt", float(6 - int(m_jlpt.group(1)))
    if any(tok in lower for tok in ("torfl", "trki", "трки")):
        m_torfl = re.search(r"\b(?:torfl|trki|трки)[\s\-–:]*(iv|iii|ii|i|[1-4])\b", lower)
        if m_torfl:
            tok = m_torfl.group(1)
            roman_map = {"i": 1.0, "ii": 2.0, "iii": 3.0, "iv": 4.0}
            return "torfl", roman_map.get(tok, float(tok) if tok.isdigit() else 0.0)
    cleaned_num_str = re.sub(
        r"\b(?:cefr\s*)?[abc][12]\b|(?:/|out\s+of)\s*(?:9(?:\.0)?|90|100|120|160|230|699|900|1000)\b"
        r"|\btopik\s+i{1,2}\b",
        " ",
        lower,
    )
    nums = [_parse_finite(tok) for tok in re.findall(r"\d+(?:[.,]\d+)?", cleaned_num_str)]
    score = next((n for n in nums if n is not None), None)
    if score is None:
        return None
    if 120.0 <= score <= 230.0 and any(
        tok in lower
        for tok in (
            "cambridge",
            "cae",
            "cpe",
            "fce",
            "pet",
            "ket",
            "c1 advanced",
            "c2 proficiency",
            "b2 first",
            "b1 preliminary",
            "a2 key",
        )
    ):
        return "cambridge", score
    for test_name in (
        "ielts",
        "toefl",
        "pte",
        "duolingo",
        "testdaf",
        "dsh",
        "tcf",
        "tef",
        "siele",
        "cils",
        "celi",
        "topik",
        "hsk",
    ):
        if test_name in lower or (
            test_name == "duolingo" and re.search(r"\bdet\b", lower)
        ) or (
            test_name == "testdaf" and re.search(r"\btdn\b", lower)
        ):
            if test_name == "toefl" and score < 30:
                return None
            if test_name == "testdaf" and score <= 5:
                # Normalize TDN 3/4/5 to 12/16/18 on the 4-subtest (max 20) scale.
                score = 18.0 if score >= 5 else (16.0 if score >= 4 else 12.0)
            return test_name, score
    return None


def _to_ielts_equiv(test_name: str, score: float) -> float | None:
    """Map an English standardized test score to its official IELTS band equivalent."""
    if test_name == "ielts":
        return score
    if test_name == "cambridge":
        for threshold, band in (
            (209.0, 9.0),
            (205.0, 8.5),
            (200.0, 8.0),
            (191.0, 7.5),
            (185.0, 7.0),
            (176.0, 6.5),
            (169.0, 6.0),
            (162.0, 5.5),
            (154.0, 5.0),
            (147.0, 4.5),
            (140.0, 4.0),
        ):
            if score >= threshold:
                return band
        return 3.5
    if test_name == "toefl":
        for threshold, band in (
            (118.0, 9.0),
            (115.0, 8.5),
            (110.0, 8.0),
            (102.0, 7.5),
            (94.0, 7.0),
            (79.0, 6.5),
            (60.0, 6.0),
            (46.0, 5.5),
            (35.0, 5.0),
            (32.0, 4.5),
        ):
            if score >= threshold:
                return band
        return 4.0
    if test_name == "pte":
        for threshold, band in (
            (89.0, 9.0),
            (84.0, 8.5),
            (79.0, 8.0),
            (73.0, 7.5),
            (65.0, 7.0),
            (58.0, 6.5),
            (50.0, 6.0),
            (42.0, 5.5),
            (36.0, 5.0),
        ):
            if score >= threshold:
                return band
        return 4.5
    if test_name == "duolingo":
        for threshold, band in (
            (160.0, 9.0),
            (155.0, 8.5),
            (145.0, 8.0),
            (135.0, 7.5),
            (125.0, 7.0),
            (115.0, 6.5),
            (100.0, 6.0),
            (85.0, 5.5),
            (75.0, 5.0),
        ):
            if score >= threshold:
                return band
        return 4.5
    return None


def _level_to_cefr(raw_level: str) -> str | None:
    """Return a canonical CEFR level (`A1`..`C2`) from either a direct CEFR code
    or a well-known standardized exam score (`IELTS 6.5` -> `B2`, `TOEFL 100` -> `C1`)."""
    cleaned = " ".join(raw_level.strip().split())
    if not cleaned:
        return None
    upper = cleaned.upper()
    if upper in _CEFR:
        return upper
    upper_no_cam_titles = re.sub(
        r"\b(?:C2\s+PROFICIENCY|C1\s+ADVANCED|B2\s+FIRST|B1\s+PRELIMINARY|A2\s+KEY)\b",
        " ",
        upper,
    )
    m_cefr = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", upper_no_cam_titles)
    if m_cefr:
        return m_cefr.group(1)
    lower = cleaned.casefold()
    if any(tok in lower for tok in ("torfl", "trki", "трки", "тбу", "тэу")):
        if re.search(r"\b(?:torfl|trki|трки)[\s\-–:]*(?:iv|4)\b", lower):
            return "C2"
        if re.search(r"\b(?:torfl|trki|трки)[\s\-–:]*(?:iii|3)\b", lower):
            return "C1"
        if re.search(r"\b(?:torfl|trki|трки)[\s\-–:]*(?:ii|2)\b", lower):
            return "B2"
        if re.search(r"\b(?:torfl|trki|трки)[\s\-–:]*(?:i|1)\b", lower):
            return "B1"
        if re.search(r"\b(?:тбу|tbu)\b", lower):
            return "A2"
        if re.search(r"\b(?:тэу|teu)\b", lower):
            return "A1"
    cleaned_num_str = re.sub(
        r"\b(?:cefr\s*)?[abc][12]\b|(?:/|out\s+of)\s*(?:9(?:\.0)?|90|100|120|160|230|699|900|1000)\b"
        r"|\btopik\s+i{1,2}\b",
        " ",
        lower,
    )
    nums = [
        _parse_finite(tok)
        for tok in re.findall(r"\d+(?:[.,]\d+)?", cleaned_num_str)
    ]
    score = next((n for n in nums if n is not None), None)
    if (
        score is not None
        and 120.0 <= score <= 230.0
        and any(
            tok in lower
            for tok in (
                "cambridge",
                "cae",
                "cpe",
                "fce",
                "pet",
                "ket",
                "c1 advanced",
                "c2 proficiency",
                "b2 first",
                "b1 preliminary",
                "a2 key",
            )
        )
    ):
        if score >= 200:
            return "C2"
        if score >= 180:
            return "C1"
        if score >= 160:
            return "B2"
        if score >= 140:
            return "B1"
        return "A2"
    if re.search(
        r"\b(?:cpe|c2\s+proficiency|dsh\s*[-–]?\s*3|gds|großes\s+deutsches\s+sprachdiplom|"
        r"grosses\s+deutsches\s+sprachdiplom|zop|zentrale\s+oberstufenprüfung|"
        r"dele\s+superior|cils\s+(?:quattro|4)|celi\s*5)\b",
        lower,
    ):
        return "C2"
    if re.search(
        r"\b(?:cae|c1\s+advanced|dsh\s*[-–]?\s*2|tdn\s*[45]|testdaf\s*4\s*x\s*[45]|"
        r"kds|kleines\s+deutsches\s+sprachdiplom|dalf|siele\s*s5|cils\s+(?:tre|3)|"
        r"celi\s*4|(?:jlpt\s*)?n\s*1|tömer\s+yüksek|tomer\s+yuksek)\b",
        lower,
    ):
        return "C1"
    if re.search(
        r"\b(?:fce|b2\s+first|dsh\s*[-–]?\s*1|tdn\s*3|testdaf\s*4\s*x\s*3|"
        r"dele\s+intermedio|siele\s*s4|cils\s+(?:due|2)|celi\s*3|(?:jlpt\s*)?n\s*2|"
        r"tömer\s+orta|tomer\s+orta)\b",
        lower,
    ):
        return "B2"
    if re.search(
        r"\b(?:pet|b1\s+preliminary|zertifikat\s+deutsch|dele\s+inicial|siele\s*s3|"
        r"cils\s+(?:uno|1)|celi\s*2|(?:jlpt\s*)?n\s*3)\b",
        lower,
    ):
        return "B1"
    if re.search(
        r"\b(?:ket|a2\s+key|siele\s*s2|celi\s*1|(?:jlpt\s*)?n\s*4|"
        r"tömer\s+temel|tomer\s+temel)\b",
        lower,
    ):
        return "A2"
    if re.search(r"\b(?:siele\s*s1|celi\s*(?:impatto|0)|(?:jlpt\s*)?n\s*5)\b", lower):
        return "A1"
    if score is None:
        return None
    if "ielts" in lower:
        if score >= 8.5:
            return "C2"
        if score >= 7.0:
            return "C1"
        if score >= 5.5:
            return "B2"
        if score >= 4.0:
            return "B1"
        return "A2"
    if "toefl" in lower and score >= 30:
        if score >= 114:
            return "C2"
        if score >= 94:
            return "C1"
        if score >= 60:
            return "B2"
        if score >= 35:
            return "B1"
        return "A2"
    if "pte" in lower and score >= 10:
        if score >= 85:
            return "C2"
        if score >= 76:
            return "C1"
        if score >= 59:
            return "B2"
        if score >= 43:
            return "B1"
        return "A2"
    if ("duolingo" in lower or re.search(r"\bdet\b", lower)) and score >= 10:
        if score >= 155:
            return "C2"
        if score >= 125:
            return "C1"
        if score >= 100:
            return "B2"
        if score >= 60:
            return "B1"
        return "A2"
    if "testdaf" in lower or re.search(r"\btdn\b", lower):
        if score >= 16:
            return "C1"
        if score >= 12:
            return "B2"
        if score >= 4:
            return "C1"
        if score >= 3:
            return "B2"
    if "dsh" in lower:
        if score >= 3:
            return "C2"
        if score >= 2:
            return "C1"
        if score >= 1:
            return "B2"
    if re.search(r"\btcf\b", lower):
        if score >= 600 or score == 6:
            return "C2"
        if score >= 500 or score == 5:
            return "C1"
        if score >= 400 or score == 4:
            return "B2"
        if score >= 300 or score == 3:
            return "B1"
        if score >= 200 or score == 2:
            return "A2"
        if score >= 100 or score == 1:
            return "A1"
    if re.search(r"\btef\b", lower):
        if "/900" in lower or "out of 900" in lower or score > 699:
            if score >= 834:
                return "C2"
            if score >= 699:
                return "C1"
            if score >= 541:
                return "B2"
            if score >= 361:
                return "B1"
            if score >= 181:
                return "A2"
            return "A1"
        if score >= 600 or score == 6:
            return "C2"
        if score >= 500 or score == 5:
            return "C1"
        if score >= 400 or score == 4:
            return "B2"
        if score >= 300 or score == 3:
            return "B1"
        if score >= 200 or score == 2:
            return "A2"
        if score >= 100 or score == 1:
            return "A1"
    if "siele" in lower:
        if score >= 750 or score == 5:
            return "C1"
        if score >= 500 or score == 4:
            return "B2"
        if score >= 300 or score == 3:
            return "B1"
        if score >= 150 or score == 2:
            return "A2"
        return "A1"
    if "jlpt" in lower:
        if score == 1:
            return "C1"
        if score == 2:
            return "B2"
        if score == 3:
            return "B1"
        if score == 4:
            return "A2"
        if score == 5:
            return "A1"
    if "topik" in lower or "급" in lower:
        if score >= 6:
            return "C2"
        if score >= 5:
            return "C1"
        if score >= 4:
            return "B2"
        if score >= 3:
            return "B1"
        if score >= 2:
            return "A2"
        if score >= 1:
            return "A1"
    if "hsk" in lower:
        if score >= 7:
            return "C2"
        if score == 6:
            return "C1"
        if score == 5:
            return "B2"
        if score == 4:
            return "B1"
        if score == 3:
            return "A2"
        if score in (1, 2):
            return "A1"
    if any(tok in lower for tok in ("tömer", "tomer", "yökdil", "yokdil", "yds")):
        if score >= 85:
            return "C1"
        if score >= 70:
            return "B2"
        if score >= 55:
            return "B1"
        if score >= 40:
            return "A2"
    return None


_LANGUAGE_ALIASES: dict[str, str] = {
    "en": "english",
    "eng": "english",
    "englisch": "english",
    "anglais": "english",
    "inglese": "english",
    "inglés": "english",
    "ingles": "english",
    "engels": "english",
    "ingilizce": "english",
    "i\u0307ngilizce": "english",
    "ingilis": "english",
    "ingilis dili": "english",
    "английский": "english",
    "英语": "english",
    "英語": "english",
    "영어": "english",
    "de": "german",
    "deu": "german",
    "ger": "german",
    "deutsch": "german",
    "allemand": "german",
    "tedesco": "german",
    "alemán": "german",
    "aleman": "german",
    "duits": "german",
    "almanca": "german",
    "alman": "german",
    "alman dili": "german",
    "немецкий": "german",
    "德语": "german",
    "ドイツ語": "german",
    "독일어": "german",
    "fr": "french",
    "fra": "french",
    "fre": "french",
    "français": "french",
    "francais": "french",
    "französisch": "french",
    "franzosisch": "french",
    "francese": "french",
    "francés": "french",
    "frances": "french",
    "frans": "french",
    "fransızca": "french",
    "fransizca": "french",
    "французский": "french",
    "法语": "french",
    "フランス語": "french",
    "프랑스어": "french",
    "it": "italian",
    "ita": "italian",
    "italiano": "italian",
    "italienisch": "italian",
    "italien": "italian",
    "italiaans": "italian",
    "итальянский": "italian",
    "es": "spanish",
    "spa": "spanish",
    "español": "spanish",
    "espanol": "spanish",
    "spanisch": "spanish",
    "espagnol": "spanish",
    "spagnolo": "spanish",
    "spaans": "spanish",
    "испанский": "spanish",
    "nl": "dutch",
    "nld": "dutch",
    "dut": "dutch",
    "nederlands": "dutch",
    "niederländisch": "dutch",
    "niederlandisch": "dutch",
    "néerlandais": "dutch",
    "neerlandais": "dutch",
    "olandese": "dutch",
    "tr": "turkish",
    "tur": "turkish",
    "türkçe": "turkish",
    "turkce": "turkish",
    "türkisch": "turkish",
    "az": "azerbaijani",
    "aze": "azerbaijani",
    "azərbaycan": "azerbaijani",
    "azərbaycan dili": "azerbaijani",
    "azerbaijani": "azerbaijani",
    "ru": "russian",
    "rus": "russian",
    "русский": "russian",
    "russisch": "russian",
    "russe": "russian",
    "zh": "chinese",
    "zho": "chinese",
    "chi": "chinese",
    "mandarin": "chinese",
    "mandarin chinese": "chinese",
    "中文": "chinese",
    "汉语": "chinese",
    "chinesisch": "chinese",
    "ja": "japanese",
    "jpn": "japanese",
    "日本語": "japanese",
    "japanisch": "japanese",
    "ko": "korean",
    "kor": "korean",
    "한국어": "korean",
    "koreanisch": "korean",
    "ar": "arabic",
    "ara": "arabic",
    "العربية": "arabic",
    "arabisch": "arabic",
    "pt": "portuguese",
    "por": "portuguese",
    "português": "portuguese",
    "portugues": "portuguese",
    "pl": "polish",
    "pol": "polish",
    "polski": "polish",
    "sv": "swedish",
    "swe": "swedish",
    "svenska": "swedish",
}


def _normalize_language(raw: str) -> str:
    folded = " ".join(raw.strip().split()).casefold()
    return _LANGUAGE_ALIASES.get(folded, folded)


_TEST_LANGUAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:testdaf|tdn|dsh|goethe|ösd|osd|kds|gds|zop|zertifikat\s+deutsch|"
            r"großes\s+deutsches\s+sprachdiplom|grosses\s+deutsches\s+sprachdiplom|"
            r"kleines\s+deutsches\s+sprachdiplom|zentrale\s+oberstufenprüfung)\b",
            re.IGNORECASE,
        ),
        "german",
    ),
    (re.compile(r"\b(?:delf|dalf|tcf|tef)\b", re.IGNORECASE), "french"),
    (re.compile(r"\b(?:dele|siele)\b", re.IGNORECASE), "spanish"),
    (re.compile(r"\b(?:cils|celi|plida)\b", re.IGNORECASE), "italian"),
    (re.compile(r"\b(?:torfl|trki|трки|тбу|тэу)\b", re.IGNORECASE), "russian"),
    (re.compile(r"\b(?:jlpt|n[1-5])\b", re.IGNORECASE), "japanese"),
    (re.compile(r"\btopik\b|급", re.IGNORECASE), "korean"),
    (re.compile(r"\bhsk\b", re.IGNORECASE), "chinese"),
    (re.compile(r"\b(?:tömer|tomer|yökdil|yokdil|yds)\b", re.IGNORECASE), "turkish"),
    (
        re.compile(
            r"\b(?:toefl|pte|duolingo|det|cambridge|cae|cpe|fce|pet|ket|ielts|"
            r"c1\s+advanced|c2\s+proficiency|b2\s+first|b1\s+preliminary|a2\s+key)\b",
            re.IGNORECASE,
        ),
        "english",
    ),
)

_QUOTE_LANGUAGE_NAMES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:english|englisch)\b", re.IGNORECASE), "english"),
    (re.compile(r"\b(?:german|deutsch|deutsche[nr]?)\b", re.IGNORECASE), "german"),
    (re.compile(r"\b(?:french|français|francais|französisch)\b", re.IGNORECASE), "french"),
    (re.compile(r"\b(?:spanish|español|espanol|spanisch)\b", re.IGNORECASE), "spanish"),
    (re.compile(r"\b(?:italian|italiano|italienisch)\b", re.IGNORECASE), "italian"),
    (re.compile(r"\b(?:dutch|nederlands|niederländisch)\b", re.IGNORECASE), "dutch"),
    (re.compile(r"\b(?:turkish|türkçe|turkce|türkisch)\b", re.IGNORECASE), "turkish"),
    (re.compile(r"\b(?:azerbaijani|azərbaycan)\b", re.IGNORECASE), "azerbaijani"),
    (re.compile(r"\b(?:russian|русский|russisch)\b", re.IGNORECASE), "russian"),
    (re.compile(r"\b(?:chinese|mandarin)\b", re.IGNORECASE), "chinese"),
    (re.compile(r"\b(?:japanese|japanisch)\b", re.IGNORECASE), "japanese"),
    (re.compile(r"\b(?:korean|koreanisch)\b", re.IGNORECASE), "korean"),
    (re.compile(r"\b(?:arabic|arabisch)\b", re.IGNORECASE), "arabic"),
    (re.compile(r"\b(?:portuguese|portugiesisch)\b", re.IGNORECASE), "portuguese"),
    (re.compile(r"\b(?:polish|polnisch)\b", re.IGNORECASE), "polish"),
    (re.compile(r"\b(?:swedish|schwedisch)\b", re.IGNORECASE), "swedish"),
)


def _infer_language_from_test(raw: str) -> str | None:
    cleaned = " ".join(raw.strip().split())
    if not cleaned:
        return None
    matched: set[str] = set()
    for pattern, lang in _TEST_LANGUAGE_PATTERNS:
        if pattern.search(cleaned):
            matched.add(lang)
    return next(iter(matched)) if len(matched) == 1 else None


def _infer_language_from_quote(quote: str) -> str | None:
    cleaned = " ".join((quote or "").strip().split())
    if not cleaned:
        return None
    matched: set[str] = set()
    for pattern, lang in _QUOTE_LANGUAGE_NAMES:
        if pattern.search(cleaned):
            matched.add(lang)
    if len(matched) == 1:
        return next(iter(matched))
    return _infer_language_from_test(cleaned)


def _split_language_bar(raw: str) -> tuple[str, str]:
    cleaned = " ".join(raw.strip().split())
    if not cleaned:
        return "", ""
    if " " not in cleaned:
        return cleaned, ""
    head, _, tail = cleaned.rpartition(" ")
    if not head:
        return head, tail
    if tail.upper() in _CEFR and (
        " " not in head or head.casefold() in _LANGUAGE_ALIASES
    ):
        return head, tail
    first, _, rest = cleaned.partition(" ")
    return first, rest


def _decide_residence(
    condition: ConditionTriple, profile: object, today: _date | None = None
) -> Decision:
    if condition.operator == "PRESENT":
        from apps.funding.transcript_eligibility import (
            _ERASMUS_12_MONTH_RULE_RE,
            _ERASMUS_PROGRAMME_COUNTRIES,
        )

        probe_text = f"{condition.value} {condition.quote}".strip()
        if _ERASMUS_12_MONTH_RULE_RE.search(probe_text):
            nat = str(getattr(profile, "nationality", "") or "").upper()
            res_country = str(getattr(profile, "country_of_residence", "") or "").upper()
            intake_dt = getattr(profile, "intended_intake", None)
            ref_year = (
                intake_dt.year
                if isinstance(intake_dt, _date)
                else (today.year if today is not None else _date.today().year)
            )
            if nat not in _ERASMUS_PROGRAMME_COUNTRIES:
                if res_country in _ERASMUS_PROGRAMME_COUNTRIES and res_country != nat:
                    return _verdict(
                        False,
                        f"RESIDENCE: current residence {res_country} is in a Programme Country",
                    )
                for rec in tuple(getattr(profile, "academic_history", ()) or ()):
                    rec_cc = str(getattr(rec, "country_code", "") or "").upper()
                    if rec_cc not in _ERASMUS_PROGRAMME_COUNTRIES or rec_cc == nat:
                        continue
                    comp_on = getattr(rec, "completed_on", None)
                    exp_comp = getattr(rec, "expected_completion", None)
                    rec_year = (
                        comp_on.year
                        if isinstance(comp_on, _date)
                        else (exp_comp.year if isinstance(exp_comp, _date) else ref_year)
                    )
                    if ref_year - rec_year <= 5:
                        return _verdict(
                            False,
                            f"RESIDENCE: studied in Programme Country {rec_cc} "
                            "within last 5 years",
                        )
            return Decision(
                "SATISFIED",
                "RESIDENCE: no Programme Country residence > 12 months in last 5 years",
            )
        return _undecidable(f"RESIDENCE: '{condition.value}' requires human review")
    return _country_decision(
        condition, str(getattr(profile, "country_of_residence", "")), "country of residence"
    )


def _decide_field(
    condition: ConditionTriple, profile: object, _today: _date | None = None
) -> Decision:
    from apps.accounts.field_taxonomy import resolve_field_taxonomy

    target = str(getattr(profile, "target_field", "")).casefold()
    interests = tuple(getattr(profile, "research_interests", ()) or ())
    prior_fields = tuple(
        str(getattr(r, "field", "")).strip()
        for r in getattr(profile, "academic_history", ()) or ()
        if str(getattr(r, "field", "")).strip()
    )
    resolution = resolve_field_taxonomy(target, interests)
    prior_expanded: list[str] = []
    for pf in prior_fields:
        pf_res = resolve_field_taxonomy(pf)
        prior_expanded.extend((pf, *pf_res.canonical_degree_titles, *pf_res.parent_fields))
    candidate_fields = tuple(
        dict.fromkeys(
            f.casefold()
            for f in (
                target,
                *resolution.canonical_degree_titles,
                *resolution.parent_fields,
                *(str(i) for i in interests),
                *prior_expanded,
            )
            if f
        )
    )
    raw_wanted = [
        part.strip().casefold() for part in condition.value.split(",") if part.strip()
    ]
    wanted_fields: list[str] = []
    for part in raw_wanted:
        if part not in wanted_fields:
            wanted_fields.append(part)
        for syn in resolve_field_taxonomy(part).canonical_degree_titles:
            if syn not in wanted_fields:
                wanted_fields.append(syn)
    if candidate_fields and any(
        _field_matches(part, held_field)
        for part in wanted_fields
        for held_field in candidate_fields
    ):
        return Decision("SATISFIED", f"FIELD: {target} matches {condition.value}")
    # No match is not exclusion: "engineering" does not exclude "robotics".
    return _undecidable(
        f"FIELD: {condition.value} against '{target}' -- a human decides whether they overlap"
    )


def _decide_prior_degree(
    condition: ConditionTriple, profile: object, _today: _date | None = None
) -> Decision:
    levels = [
        _degree_level(str(getattr(record, "qualification", "")))
        for record in getattr(profile, "academic_history", ())
    ]
    held_levels = [level for level in levels if level is not None]
    if not held_levels:
        return _undecidable("PRIOR_DEGREE: no qualification in the profile names a level")
    best = max(_DEGREE_ORDER.index(level) for level in held_levels)
    if condition.operator == "NOT_IN":
        raw_parts = [p.strip().upper() for p in condition.value.split(",") if p.strip()]
        excluded_levels = [p for p in raw_parts if p in _DEGREE_ORDER]
        if not excluded_levels:
            inferred_lvl = _degree_level(condition.value)
            if inferred_lvl is not None:
                excluded_levels = [inferred_lvl]
        if not excluded_levels:
            return _undecidable(f"PRIOR_DEGREE: '{condition.value}' is not a known level")
        satisfied = not bool(set(held_levels) & set(excluded_levels))
        return _verdict(satisfied, f"PRIOR_DEGREE: holds {_DEGREE_ORDER[best]}")
    wanted_level = condition.value.strip().upper()
    if wanted_level not in _DEGREE_ORDER:
        return _undecidable(f"PRIOR_DEGREE: '{condition.value}' is not a known level")
    wanted_index = _DEGREE_ORDER.index(wanted_level)
    if condition.operator == "EQ":
        satisfied = best == wanted_index
    elif condition.operator == "LTE":
        satisfied = best <= wanted_index
    else:
        satisfied = best >= wanted_index
    return _verdict(satisfied, f"PRIOR_DEGREE: holds {_DEGREE_ORDER[best]}")


_INSTITUTION_STOPWORDS: frozenset[str] = frozenset(
    {
        "of",
        "the",
        "for",
        "in",
        "at",
        "on",
        "to",
        "and",
        "by",
        "de",
        "du",
        "des",
        "d",
        "la",
        "le",
        "les",
        "l",
        "di",
        "del",
        "della",
        "dei",
        "degli",
        "delle",
        "da",
        "do",
        "dos",
        "das",
        "von",
        "zu",
        "zur",
        "zum",
        "im",
        "am",
        "an",
        "auf",
        "bei",
        "der",
        "die",
        "den",
        "dem",
        "und",
        "für",
        "fuer",
        "ve",
        "named",
        "after",
    }
)

_INSTITUTION_TOKEN_STEMS: dict[str, str] = {
    "university": "uni",
    "universität": "uni",
    "universitaet": "uni",
    "universitat": "uni",
    "université": "uni",
    "universite": "uni",
    "università": "uni",
    "universita": "uni",
    "universidad": "uni",
    "universidade": "uni",
    "universiteit": "uni",
    "uniwersytet": "uni",
    "universitet": "uni",
    "universitetet": "uni",
    "universiteti": "uni",
    "üniversitesi": "uni",
    "universitesi": "uni",
    "univerzita": "uni",
    "univerza": "uni",
    "egyetem": "uni",
    "yliopisto": "uni",
    "universitatea": "uni",
    "uni": "uni",
    "univ": "uni",
    "technical": "tech",
    "technische": "tech",
    "technology": "tech",
    "technologie": "tech",
    "teknik": "tech",
    "tekniska": "tech",
    "teknillinen": "tech",
    "politecnico": "tech",
    "politechnika": "tech",
    "polytechnique": "tech",
    "polytechnic": "tech",
    "polytechnische": "tech",
    "hochschule": "tech",
    "th": "tech",
    "institute": "inst",
    "institut": "inst",
    "instituto": "inst",
    "istituto": "inst",
    "instituut": "inst",
    "institutet": "inst",
    "instytut": "inst",
    "state": "state",
    "staatliche": "state",
    "dövlət": "state",
    "dovlet": "state",
    "devlet": "state",
    "national": "national",
    "nationale": "national",
    "nacional": "national",
    "nazionale": "national",
    "milli": "national",
    "federal": "federal",
    "eidgenössische": "federal",
    "eidgenoessische": "federal",
    "eidgenossische": "federal",
    "swiss": "swiss",
    "schweizerische": "swiss",
    "free": "free",
    "freie": "free",
    "applied": "applied",
    "angewandte": "applied",
    "sciences": "sciences",
    "wissenschaften": "sciences",
    "münchen": "munich",
    "muenchen": "munich",
    "munchen": "munich",
    "munich": "munich",
    "wien": "vienna",
    "vienna": "vienna",
    "zürich": "zurich",
    "zuerich": "zurich",
    "zurich": "zurich",
    "genève": "geneva",
    "geneve": "geneva",
    "geneva": "geneva",
    "genf": "geneva",
    "köln": "cologne",
    "koeln": "cologne",
    "koln": "cologne",
    "cologne": "cologne",
    "nürnberg": "nuremberg",
    "nuernberg": "nuremberg",
    "nurnberg": "nuremberg",
    "nuremberg": "nuremberg",
    "göttingen": "gottingen",
    "goettingen": "gottingen",
    "gottingen": "gottingen",
    "tübingen": "tubingen",
    "tuebingen": "tubingen",
    "tubingen": "tubingen",
    "würzburg": "wurzburg",
    "wuerzburg": "wurzburg",
    "wurzburg": "wurzburg",
    "münster": "munster",
    "muenster": "munster",
    "munster": "munster",
    "düsseldorf": "dusseldorf",
    "duesseldorf": "dusseldorf",
    "dusseldorf": "dusseldorf",
    "warszawa": "warsaw",
    "warsaw": "warsaw",
    "kraków": "krakow",
    "krakow": "krakow",
    "cracow": "krakow",
    "praha": "prague",
    "prague": "prague",
    "moskva": "moscow",
    "moscow": "moscow",
    "roma": "rome",
    "rome": "rome",
    "milano": "milan",
    "milan": "milan",
    "firenze": "florence",
    "florence": "florence",
    "torino": "turin",
    "turin": "turin",
    "padova": "padua",
    "padua": "padua",
    "venezia": "venice",
    "venice": "venice",
    "napoli": "naples",
    "naples": "naples",
    "bruxelles": "brussels",
    "brussel": "brussels",
    "brussels": "brussels",
    "leuven": "leuven",
    "louvain": "leuven",
    "gent": "ghent",
    "ghent": "ghent",
    "gand": "ghent",
    "københavn": "copenhagen",
    "kobenhavn": "copenhagen",
    "copenhagen": "copenhagen",
    "göteborg": "gothenburg",
    "goteborg": "gothenburg",
    "gothenburg": "gothenburg",
    "helsingfors": "helsinki",
    "helsinki": "helsinki",
    "beijing": "beijing",
    "peking": "beijing",
    "bakı": "baku",
    "baki": "baku",
    "baku": "baku",
    "azərbaycan": "azerbaijan",
    "azerbaycan": "azerbaijan",
    "azerbaijan": "azerbaijan",
    "türkiye": "turkey",
    "turkiye": "turkey",
    "turkey": "turkey",
}

_INSTITUTION_COMPOUND_ABBRS: dict[str, tuple[str, ...]] = {
    "tu": ("tech", "uni"),
    "fu": ("free", "uni"),
    "hu": ("humboldt", "uni"),
    "ku": ("katholieke", "uni"),
    "eth": ("federal", "tech", "inst"),
    "epfl": ("federal", "tech", "lausanne"),
    "rwth": ("rwth", "tech", "uni"),
    "lmu": ("ludwig", "maximilian", "uni"),
    "kit": ("karlsruhe", "inst", "tech"),
}

_GENERIC_INSTITUTION_TOKENS: frozenset[str] = frozenset(
    {
        "uni",
        "tech",
        "inst",
        "state",
        "national",
        "federal",
        "swiss",
        "free",
        "applied",
        "sciences",
        "college",
        "school",
        "academy",
        "higher",
        "education",
        "institution",
        "institutions",
        "universities",
        "partner",
        "recognized",
        "recognised",
        "accredited",
        "approved",
        "eligible",
        "public",
        "private",
        "research",
        "international",
        "world",
        "top",
        "ranked",
        "ranking",
        "group",
    }
)


def _fold_ascii(token: str) -> str:
    folded = (
        token.casefold()
        .replace("ß", "ss")
        .replace("ø", "o")
        .replace("å", "a")
        .replace("æ", "ae")
        .replace("ı", "i")
        .replace("ə", "e")
    )
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _institution_signature(raw: str) -> tuple[frozenset[str], frozenset[str], bool]:
    """Return ``(canonical_tokens, acronyms, has_specific_identity)`` for an institution string."""
    cleaned = raw.strip().casefold()
    if not cleaned:
        return frozenset(), frozenset(), False
    parts = [cleaned]
    for paren in re.findall(r"\(([^)]+)\)", cleaned):
        if paren.strip():
            parts.append(paren.strip())
    without_parens = re.sub(r"\([^)]*\)", " ", cleaned).strip()
    if without_parens and without_parens not in parts:
        parts.append(without_parens)

    canon_tokens: set[str] = set()
    acronyms: set[str] = set()
    for part in parts:
        raw_words = [
            w for w in re.split(r"[^a-z0-9äöüßøåæıəğşçéèêëàáâãії]+", part) if w
        ]
        sig_words = [
            w
            for w in raw_words
            if w not in _INSTITUTION_STOPWORDS and _fold_ascii(w) not in _INSTITUTION_STOPWORDS
        ]
        if not sig_words:
            continue
        if len(sig_words) == 1 and 2 <= len(sig_words[0]) <= 6 and sig_words[0].isalpha():
            acronyms.add(_fold_ascii(sig_words[0]))
        if len(sig_words) >= 2:
            raw_initialism = "".join(_fold_ascii(w)[0] for w in sig_words if _fold_ascii(w))
            if len(raw_initialism) >= 2:
                acronyms.add(raw_initialism)
        part_canon: list[str] = []
        for word in sig_words:
            folded = _fold_ascii(word)
            if folded in _INSTITUTION_COMPOUND_ABBRS:
                if len(sig_words) == 1:
                    acronyms.add(folded)
                part_canon.extend(_INSTITUTION_COMPOUND_ABBRS[folded])
                continue
            stem = _INSTITUTION_TOKEN_STEMS.get(word) or _INSTITUTION_TOKEN_STEMS.get(folded)
            if stem is not None:
                part_canon.append(stem)
            else:
                if folded.startswith("ludwig") or folded.startswith("maximilian"):
                    part_canon.append("ludwig" if folded.startswith("ludwig") else "maximilian")
                else:
                    part_canon.append(folded)
        canon_tokens.update(part_canon)
        if len(part_canon) >= 2:
            canon_initialism = "".join(tok[0] for tok in part_canon if tok)
            if len(canon_initialism) >= 2:
                acronyms.add(canon_initialism)
        if "federal" in part_canon and "tech" in part_canon and "zurich" in part_canon:
            acronyms.add("eth")
        if "ludwig" in part_canon and "maximilian" in part_canon and "munich" in part_canon:
            acronyms.add("lmu")
    specific = bool((canon_tokens - _GENERIC_INSTITUTION_TOKENS) or acronyms)
    return frozenset(canon_tokens), frozenset(acronyms), specific


def _institution_matches(wanted_raw: str, held_raw: str) -> bool:
    w_clean = " ".join(wanted_raw.strip().split()).casefold()
    h_clean = " ".join(held_raw.strip().split()).casefold()
    if not w_clean or not h_clean:
        return False
    if w_clean == h_clean or _fold_ascii(w_clean) == _fold_ascii(h_clean):
        return True
    w_tokens, w_acronyms, w_specific = _institution_signature(w_clean)
    h_tokens, h_acronyms, h_specific = _institution_signature(h_clean)
    if not w_specific or not h_specific:
        return False
    if w_acronyms & h_acronyms:
        w_places = w_tokens - _GENERIC_INSTITUTION_TOKENS - w_acronyms
        h_places = h_tokens - _GENERIC_INSTITUTION_TOKENS - h_acronyms
        if not w_places or not h_places or (w_places & h_places):
            return True
    w_dist = w_tokens - _GENERIC_INSTITUTION_TOKENS
    h_dist = h_tokens - _GENERIC_INSTITUTION_TOKENS
    if w_dist and h_dist and w_tokens == h_tokens:
        return True
    if (
        w_dist
        and w_dist == h_dist
        and ("tech" in w_tokens) == ("tech" in h_tokens)
        and ("applied" in w_tokens) == ("applied" in h_tokens)
    ):
        return True
    return False


def _decide_prior_institution(
    condition: ConditionTriple, profile: object, _today: _date | None = None
) -> Decision:
    records = tuple(getattr(profile, "academic_history", ()))
    if not records:
        return _undecidable("PRIOR_INSTITUTION: the profile does not carry academic history")
    countries = expand_countries(condition.value)
    if countries is not None:
        held_countries = {
            str(getattr(record, "country_code", "")).upper()
            for record in records
            if str(getattr(record, "country_code", "")).strip()
        }
        if not held_countries:
            return _undecidable("PRIOR_INSTITUTION: the profile does not carry academic history")
        inside = bool(held_countries & set(countries))
        satisfied = not inside if condition.operator == "NOT_IN" else inside
        return _verdict(
            satisfied,
            f"PRIOR_INSTITUTION: studied in {sorted(held_countries)}",
        )
    wanted_raw = condition.value.strip()
    if not wanted_raw:
        return _undecidable(
            f"PRIOR_INSTITUTION: '{condition.value}' names no institution to match"
        )
    held_names = [
        str(getattr(record, "institution", "")).strip()
        for record in records
        if str(getattr(record, "institution", "")).strip()
    ]
    wanted_parts = [p.strip() for p in re.split(r"[,;]", wanted_raw) if p.strip()]
    matched = any(
        _institution_matches(part, held_name)
        for part in wanted_parts
        for held_name in held_names
    )
    if matched:
        if condition.operator == "NOT_IN":
            return _verdict(False, f"PRIOR_INSTITUTION: studied at {condition.value}")
        return Decision("SATISFIED", f"PRIOR_INSTITUTION: studied at {condition.value}")
    if (
        condition.operator == "NOT_IN"
        and held_names
        and all(_institution_signature(part)[2] for part in wanted_parts)
    ):
        return Decision("SATISFIED", f"PRIOR_INSTITUTION: did not study at {condition.value}")
    return _undecidable(
        f"PRIOR_INSTITUTION: '{condition.value}' is a name, not a country list -- "
        "a human decides whether it matches"
    )


def _to_bavarian(
    grade: float | str, scale: str, country_code: str = ""
) -> float | None:
    """Convert `(grade, scale, country_code)` to its Modified Bavarian (`1.0`..`5.0`) float
    using the canonical piecewise-equipercentile converter in `transcript_eligibility`."""
    from apps.funding.transcript_eligibility import convert_grade_to_bavarian

    bav = convert_grade_to_bavarian(str(grade), scale, country_code)
    return float(bav) if bav is not None else None


def _decide_grade(
    condition: ConditionTriple, profile: object, _today: _date | None = None
) -> Decision:
    bar_text, scale = _split_scale(condition.value)
    bar = _parse_finite(bar_text)
    if bar is None or not scale:
        if condition.operator in ("GTE", "EQ"):
            from apps.funding.transcript_eligibility import (
                _evaluate_uk_honours_for_record,
                _uk_honours_tier,
            )

            hon_bar = _uk_honours_tier(condition.value)
            if hon_bar is not None:
                hon_decisions: list[Decision] = []
                for record in getattr(profile, "academic_history", ()):
                    ev = _evaluate_uk_honours_for_record(hon_bar[0], hon_bar[1], record)
                    if ev is None:
                        continue
                    verdict = _verdict(ev.outcome == "SATISFIED", f"GRADE: {ev.status_text}")
                    if verdict.outcome == "SATISFIED":
                        return verdict
                    hon_decisions.append(verdict)
                if hon_decisions:
                    return hon_decisions[0]
        return _undecidable(f"GRADE: '{condition.value}' does not state a finite bar")
    norm_wanted_scale = _normalize_scale(scale)
    matched_decisions: list[Decision] = []
    unstated_markers = {"", "not stated", "unknown", "none", "n/a", "-"}
    for record in getattr(profile, "academic_history", ()):
        rec_scale = str(getattr(record, "grading_scale", ""))
        raw_grade = str(getattr(record, "grade", "")).strip()
        rec_cc = str(getattr(record, "country_code", "") or "").strip().upper()
        if (
            rec_scale.strip().casefold() in unstated_markers
            or raw_grade.casefold() in unstated_markers
        ):
            from apps.funding.transcript_eligibility import _resolve_record_grade_and_scale

            g_dec, eff_scale, _ = _resolve_record_grade_and_scale(record)
            if eff_scale:
                rec_scale = eff_scale
            if g_dec is not None and raw_grade.casefold() in unstated_markers:
                raw_grade = str(g_dec)
        if not rec_scale or _normalize_scale(rec_scale) != norm_wanted_scale:
            continue
        if rec_cc in {"CZ", "SK", "PH"}:
            continue
        if rec_cc in {"DE", "AT"} and norm_wanted_scale in {"gpa 4.0", "5.0"}:
            continue
        if norm_wanted_scale == "german 1-5" and rec_cc in {
            "HU",
            "RU",
            "KZ",
            "BY",
            "UA",
            "UZ",
            "KG",
            "TJ",
            "TM",
            "NG",
            "SA",
        }:
            continue
        if norm_wanted_scale == "100" and rec_cc in {"GB", "UK", "IE", "AU", "NZ"} and bar > 70:
            continue
        grade = _parse_finite(raw_grade.rstrip("%").strip())
        if grade is None:
            m_comp = re.match(
                r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:/\s*\d+(?:[.,]\d+)?|%)?"
                r"(?:\s*[\(\[\-–—].*|\s*$)",
                raw_grade,
            )
            if m_comp:
                grade = _parse_finite(m_comp.group(1))
        if grade is None:
            continue
        satisfied = grade <= bar if condition.operator == "LTE" else grade >= bar
        verdict = _verdict(
            satisfied,
            f"GRADE: {raw_grade} on {scale} against {bar}",
        )
        if verdict.outcome == "SATISFIED":
            return verdict
        matched_decisions.append(verdict)
    if matched_decisions:
        return matched_decisions[0]
    # Cross-scale conversion via Modified Bavarian Formula when operator matches scale
    # direction: LTE for inverted German 1-5 scale, GTE for ascending numeric scales.
    is_inverted_target = norm_wanted_scale in ("german 1-5", "1.0-4.0")
    can_convert_direction = (
        condition.operator == "LTE" if is_inverted_target else condition.operator == "GTE"
    )
    if can_convert_direction:
        from decimal import Decimal as _Decimal

        from apps.funding.transcript_eligibility import convert_grade_to_bavarian

        target_bav = (
            _Decimal(str(bar))
            if is_inverted_target
            else convert_grade_to_bavarian(str(bar), scale)
        )
        if target_bav is not None:
            converted_decisions: list[Decision] = []
            for record in getattr(profile, "academic_history", ()):
                rec_scale = str(getattr(record, "grading_scale", ""))
                raw_grade = str(getattr(record, "grade", "")).strip()
                rec_cc = str(getattr(record, "country_code", ""))
                rec_bav = convert_grade_to_bavarian(raw_grade, rec_scale, rec_cc)
                if rec_bav is None:
                    continue
                # Lower Bavarian grade is better (1.0 is highest, 4.0 is lowest passing)
                satisfied = rec_bav <= target_bav
                verdict = _verdict(
                    satisfied,
                    f"GRADE: {raw_grade} ({rec_scale}) converted to {rec_bav} Bavarian "
                    f"against {bar} ({scale}, {target_bav} Bavarian)",
                )
                if verdict.outcome == "SATISFIED":
                    return verdict
                converted_decisions.append(verdict)
            if converted_decisions:
                return converted_decisions[0]
    return _undecidable(
        f"GRADE: no qualification is graded on '{scale}', and grades are not converted"
    )


def _decide_work_experience(
    condition: ConditionTriple, profile: object, _today: _date | None = None
) -> Decision:
    if condition.unit not in (None, "MONTHS", "YEARS"):
        return _undecidable(
            f"WORK_EXPERIENCE: a bar in {condition.unit} cannot be compared to months"
        )
    # Absent/None vs. empty answer -- do not re-flip this a third time.
    # None is "never asked": a caller with no `experience` concept (getattr
    # default) or a StudentProfileSnapshot from the short onboarding, which no
    # longer asks about experience (apps/accounts/consultation.py), so the field
    # defaults to None (apps/accounts/schemas.py). That is unknown and abstains.
    # A *present* empty tuple is a recorded answer of "none" -- zero months,
    # which can and should fail a positive bar, not an abstention.
    raw_experience = getattr(profile, "experience", None)
    if raw_experience is None:
        return _undecidable("WORK_EXPERIENCE: the profile does not carry any experience")
    records = tuple(raw_experience)
    months = sum(
        int(getattr(record, "months", 0)) for record in records
        if str(getattr(record, "kind", "")) == "WORK"
    )
    bar = _parse_finite(condition.value)
    if bar is not None and condition.unit == "YEARS":
        bar = bar * 12.0
    elif bar is None:
        m_dur = re.match(
            r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(years?|yrs?|months?|mos?)\b",
            condition.value,
            re.IGNORECASE,
        )
        if m_dur:
            parsed_num = _parse_finite(m_dur.group(1))
            if parsed_num is not None:
                unit_tok = m_dur.group(2).casefold()
                bar = parsed_num * 12.0 if unit_tok.startswith("y") else parsed_num
    if bar is None:
        return _undecidable(f"WORK_EXPERIENCE: '{condition.value}' is not a number of months")
    return _verdict(months >= bar, f"WORK_EXPERIENCE: {months} months against {bar}")


def _decide_language(
    condition: ConditionTriple, profile: object, today: _date | None = None
) -> Decision:
    language, level = _split_language_bar(condition.value)
    norm_lang = _normalize_language(language) if language else ""
    if (
        not norm_lang
        or norm_lang in _NON_LANGUAGE_TOKENS
        or (
            norm_lang not in _LANGUAGE_ALIASES.values()
            and _infer_language_from_test(language) is not None
        )
    ):
        val_without_marker = re.sub(
            r"^\s*unstated_language\b\s*", "", condition.value, flags=re.IGNORECASE
        ).strip()
        inferred = _infer_language_from_test(val_without_marker)
        if inferred is not None and condition.operator == "GTE":
            norm_lang = inferred
            language = inferred.capitalize()
            level = val_without_marker
        elif inferred is not None and condition.operator == "PRESENT" and inferred != "english":
            norm_lang = inferred
            language = inferred.capitalize()
            level = (
                val_without_marker
                if (
                    _level_to_cefr(val_without_marker) is not None
                    or _extract_test_and_score(val_without_marker) is not None
                )
                else ""
            )
        else:
            quote_lang = _infer_language_from_quote(condition.quote)
            if quote_lang is not None and val_without_marker:
                norm_lang = quote_lang
                language = quote_lang.capitalize()
                level = val_without_marker
            else:
                norm_lang = ""
    if not norm_lang or norm_lang in _NON_LANGUAGE_TOKENS:
        # A condition that names no language (or only a bare CEFR/test token like
        # "B2" or "IELTS 6.5" without naming the language) cannot fail anybody --
        # it must escalate as UNDECIDABLE rather than falsely failing the student.
        return _undecidable(f"LANGUAGE: '{condition.value}' does not name a language")
    ref_date = today if today is not None else _date.today()
    has_moi_quote = bool(
        re.search(
            r"medium of instruction|taught in english|prior degree in english|"
            r"english-speaking country",
            condition.quote or "",
            re.IGNORECASE,
        )
    )
    records = tuple(getattr(profile, "language_evidence", ()))
    if not records:
        return _undecidable("LANGUAGE: the profile does not carry language evidence")
    intake = getattr(profile, "intended_intake", None)
    evidence: dict[str, str] = {}
    evidence_types: dict[str, str] = {}
    late_evidence: dict[str, tuple[str, _date, _date]] = {}
    for item in records:
        raw_item_lang = str(getattr(item, "language", "")).strip()
        item_lang = _normalize_language(raw_item_lang)
        item_level = str(getattr(item, "level", "")).strip()
        if item_lang in _NON_LANGUAGE_TOKENS:
            inferred_item_lang = _infer_language_from_test(f"{raw_item_lang} {item_level}")
            if inferred_item_lang is not None:
                item_lang = inferred_item_lang
                if raw_item_lang and raw_item_lang.casefold() not in item_level.casefold():
                    item_level = f"{raw_item_lang} {item_level}".strip()
        item_ev_type = str(getattr(item, "evidence_type", "") or "").upper()
        if not item_lang or item_lang in _NON_LANGUAGE_TOKENS:
            continue
        avail = getattr(item, "available_by", None)
        if isinstance(avail, _date) and isinstance(intake, _date) and avail > intake:
            late_evidence[item_lang] = (item_level, avail, intake)
            continue
        prev = evidence.get(item_lang)
        if prev is None:
            evidence[item_lang] = item_level
            evidence_types[item_lang] = item_ev_type
        else:
            prev_cefr = _level_to_cefr(prev)
            cur_cefr = _level_to_cefr(item_level)
            if cur_cefr is not None and (
                prev_cefr is None or _CEFR.index(cur_cefr) > _CEFR.index(prev_cefr)
            ):
                evidence[item_lang] = item_level
                evidence_types[item_lang] = item_ev_type
            elif cur_cefr is not None and cur_cefr == prev_cefr:
                prev_ts = _extract_test_and_score(prev)
                cur_ts = _extract_test_and_score(item_level)
                if prev_ts and cur_ts and prev_ts[0] == cur_ts[0] and cur_ts[1] > prev_ts[1]:
                    evidence[item_lang] = item_level
                    evidence_types[item_lang] = item_ev_type
                elif prev_ts is None and cur_ts is not None:
                    evidence[item_lang] = item_level
                    evidence_types[item_lang] = item_ev_type
    held_level = evidence.get(norm_lang)
    held_ev_type = evidence_types.get(norm_lang, "")
    if held_level is None:
        if norm_lang in late_evidence:
            late_lvl, late_avail, late_intake = late_evidence[norm_lang]
            return _verdict(
                False,
                f"LANGUAGE: {language} ({late_lvl}) is available on {late_avail}, "
                f"after intended intake {late_intake}",
            )
        return _verdict(False, f"LANGUAGE: no evidence for {language}")
    if held_ev_type == "DEGREE":
        from apps.funding.transcript_eligibility import ungraduated_degree_completion

        if ungraduated_degree_completion(profile, ref_date) is not None:
            return _undecidable(
                f"LANGUAGE: prior-degree {language} proficiency waiver/certificate "
                "applies upon graduation"
            )
    if not level:
        return Decision("SATISFIED", f"LANGUAGE: evidence for {language} is present")
    held_ts = _extract_test_and_score(held_level)
    wanted_ts = _extract_test_and_score(level)
    if held_ev_type == "DEGREE" and wanted_ts is not None and not has_moi_quote:
        return _undecidable(
            f"LANGUAGE: prior degree taught in {language} is not an official "
            f"{wanted_ts[0]} test certificate"
        )
    if held_ts is not None and wanted_ts is not None:
        meets_bar: bool | None
        if held_ts[0] == wanted_ts[0]:
            meets_bar = held_ts[1] >= wanted_ts[1]
        else:
            held_eq = _to_ielts_equiv(*held_ts)
            wanted_eq = _to_ielts_equiv(*wanted_ts)
            meets_bar = (
                held_eq >= wanted_eq
                if (held_eq is not None and wanted_eq is not None)
                else None
            )
        if meets_bar is not None:
            if not meets_bar:
                return _verdict(False, f"LANGUAGE: {language} at {held_level} against {level}")
            if held_ev_type in {"ATTESTED", "OTHER"}:
                return _undecidable(
                    f"LANGUAGE: self-attested {language} ({held_level}) is not an official "
                    f"{wanted_ts[0]} test certificate"
                )
            return _verdict(True, f"LANGUAGE: {language} at {held_level} against {level}")
    held_cefr = _level_to_cefr(held_level)
    wanted_cefr = _level_to_cefr(level)
    if held_cefr is None or wanted_cefr is None:
        return _undecidable(
            f"LANGUAGE: '{held_level}' and '{level}' are not both CEFR levels"
        )
    if _CEFR.index(held_cefr) < _CEFR.index(wanted_cefr):
        return _verdict(False, f"LANGUAGE: {language} at {held_level} against {level}")
    if wanted_ts is not None and held_ev_type in {"ATTESTED", "OTHER"}:
        return _undecidable(
            f"LANGUAGE: self-attested {language} ({held_level}) is not an official "
            f"{wanted_ts[0]} test certificate"
        )
    return _verdict(
        True,
        f"LANGUAGE: {language} at {held_level} against {level}",
    )


def _decide_age(
    condition: ConditionTriple, profile: object, today: _date | None = None
) -> Decision:
    born = getattr(profile, "date_of_birth", None)
    if born is None:
        return _undecidable("AGE: the profile does not carry a date of birth")
    bar = _parse_finite(condition.value)
    if bar is None:
        return _undecidable(f"AGE: '{condition.value}' is not a number of years")
    ref_date = today if today is not None else _date.today()
    years = (
        ref_date.year
        - born.year
        - ((ref_date.month, ref_date.day) < (born.month, born.day))
    )
    satisfied = years <= bar if condition.operator == "LTE" else years >= bar
    return _verdict(satisfied, f"AGE: {years} against {condition.operator} {bar}")


def _decide_gender(
    condition: ConditionTriple, profile: object, _today: _date | None = None
) -> Decision:
    held_gender = str(getattr(profile, "gender", "")).strip()
    if not held_gender:
        return _undecidable("GENDER: the profile does not state a gender")
    return _verdict(
        held_gender.casefold() == condition.value.strip().casefold(),
        f"GENDER: {held_gender} against {condition.value}",
    )


_KEY_DECIDERS = {
    "RESIDENCE": _decide_residence,
    "FIELD": _decide_field,
    "PRIOR_DEGREE": _decide_prior_degree,
    "PRIOR_INSTITUTION": _decide_prior_institution,
    "GRADE": _decide_grade,
    "WORK_EXPERIENCE": _decide_work_experience,
    "LANGUAGE": _decide_language,
    "AGE": _decide_age,
    "GENDER": _decide_gender,
}


def decide(
    condition: ConditionTriple,
    profile: object,
    *,
    today: _date | None = None,
) -> Decision:
    """Whether this student satisfies one published condition.

    `profile` is read by getattr rather than typed: this module is imported by
    the judge (apps.research), and importing the Django profile schema here
    would make a pure module depend on settings.
    """
    key = condition.key
    allowed_operators = _OPERATORS_BY_KEY.get(key)
    if allowed_operators is not None and condition.operator not in allowed_operators:
        return _undecidable(f"{key}: operator {condition.operator} is not valid for this key")
    if key == "OPEN":
        return Decision("SATISFIED", "the page states the award is open to all")
    if key == "CITIZENSHIP":
        return _country_decision(condition, str(getattr(profile, "nationality", "")), "nationality")
    if key == "DESCENT":
        return _undecidable("DESCENT: the profile does not carry descent; a human decides it")
    handler = _KEY_DECIDERS.get(key)
    if handler is not None:
        return handler(condition, profile, today)
    # TALENT, NEED, REFUGEE_OR_DISPLACED, DISABILITY, EMPLOYMENT, AFFINITY,
    # GUARANTOR, OTHER. Special-category or unasked by decision (spec section 4);
    # a human decides.
    return _undecidable(_UNASKED.get(key, f"{key}: no profile field decides this"))


_UNASKED: dict[str, str] = {
    "TALENT": (
        "TALENT: the profile does not carry sports or arts achievement; a human decides it"
    ),
    "NEED": "NEED: the profile does not carry income; a human decides a means test",
    "REFUGEE_OR_DISPLACED": (
        "REFUGEE_OR_DISPLACED: not asked in the consultation; a human decides it"
    ),
    "DISABILITY": "DISABILITY: not asked in the consultation; a human decides it",
    "EMPLOYMENT": "EMPLOYMENT: the profile does not carry an employer; a human decides it",
    "AFFINITY": "AFFINITY: a membership the profile does not record; a human decides it",
    "GUARANTOR": "GUARANTOR: whether a guarantor can be produced is not in the profile",
    "OTHER": "OTHER: the page states a condition no key fits; read the sentence",
}
