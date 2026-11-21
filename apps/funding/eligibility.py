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
    "PRIOR_INSTITUTION": ("IN",),
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
    "5": "5.0",
    "5.0": "5.0",
    "0-5": "5.0",
    "0-5.0": "5.0",
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
    cleaned_num_str = re.sub(
        r"\b(?:cefr\s*)?[abc][12]\b|(?:/|out\s+of)\s*(?:9(?:\.0)?|90|120|160)\b",
        " ",
        lower,
    )
    nums = [_parse_finite(tok) for tok in re.findall(r"\d+(?:[.,]\d+)?", cleaned_num_str)]
    score = next((n for n in nums if n is not None), None)
    if score is None:
        return None
    for test_name in ("ielts", "toefl", "pte", "duolingo", "testdaf", "dsh"):
        if test_name in lower or (test_name == "duolingo" and re.search(r"\bdet\b", lower)):
            if test_name == "toefl" and score < 30:
                return None
            return test_name, score
    return None


def _to_ielts_equiv(test_name: str, score: float) -> float | None:
    """Map an English standardized test score to its official IELTS band equivalent."""
    if test_name == "ielts":
        return score
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
    m_cefr = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", upper)
    if m_cefr:
        return m_cefr.group(1)
    lower = cleaned.casefold()
    if re.search(r"\b(?:cpe|c2\s+proficiency|dsh\s*[-–]?\s*3)\b", lower):
        return "C2"
    if re.search(
        r"\b(?:cae|c1\s+advanced|dsh\s*[-–]?\s*2|tdn\s*[45]|testdaf\s*4\s*x\s*4)\b", lower
    ):
        return "C1"
    if re.search(r"\b(?:fce|b2\s+first|dsh\s*[-–]?\s*1|tdn\s*3)\b", lower):
        return "B2"
    cleaned_num_str = re.sub(
        r"(?:/|out\s+of)\s*(?:9(?:\.0)?|90|120|160)\b",
        " ",
        lower,
    )
    nums = [
        _parse_finite(tok)
        for tok in re.findall(r"\d+(?:[.,]\d+)?", cleaned_num_str)
    ]
    score = next((n for n in nums if n is not None), None)
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
        if score >= 95:
            return "C1"
        if score >= 72:
            return "B2"
        if score >= 42:
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
        if score >= 130:
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
    return None


_LANGUAGE_ALIASES: dict[str, str] = {
    "en": "english",
    "eng": "english",
    "de": "german",
    "deu": "german",
    "ger": "german",
    "deutsch": "german",
    "fr": "french",
    "fra": "french",
    "fre": "french",
    "français": "french",
    "francais": "french",
    "it": "italian",
    "ita": "italian",
    "italiano": "italian",
    "es": "spanish",
    "spa": "spanish",
    "español": "spanish",
    "espanol": "spanish",
    "nl": "dutch",
    "nld": "dutch",
    "dut": "dutch",
    "nederlands": "dutch",
    "tr": "turkish",
    "tur": "turkish",
    "türkçe": "turkish",
    "turkce": "turkish",
    "az": "azerbaijani",
    "aze": "azerbaijani",
    "azərbaycan": "azerbaijani",
    "ru": "russian",
    "rus": "russian",
    "русский": "russian",
    "zh": "chinese",
    "zho": "chinese",
    "chi": "chinese",
    "mandarin": "chinese",
    "mandarin chinese": "chinese",
    "ja": "japanese",
    "jpn": "japanese",
    "ko": "korean",
    "kor": "korean",
    "ar": "arabic",
    "ara": "arabic",
    "pt": "portuguese",
    "por": "portuguese",
    "pl": "polish",
    "pol": "polish",
    "sv": "swedish",
    "swe": "swedish",
}


def _normalize_language(raw: str) -> str:
    folded = " ".join(raw.strip().split()).casefold()
    return _LANGUAGE_ALIASES.get(folded, folded)


def _split_language_bar(raw: str) -> tuple[str, str]:
    cleaned = " ".join(raw.strip().split())
    if not cleaned:
        return "", ""
    if " " not in cleaned:
        return cleaned, ""
    head, _, tail = cleaned.rpartition(" ")
    if tail.upper() in _CEFR or not head:
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


def _decide_prior_institution(
    condition: ConditionTriple, profile: object, _today: _date | None = None
) -> Decision:
    records = tuple(getattr(profile, "academic_history", ()))
    if not records:
        return _undecidable("PRIOR_INSTITUTION: the profile does not carry academic history")
    countries = expand_countries(condition.value)
    if countries is not None:
        held_countries = {
            str(getattr(record, "country_code", "")).upper() for record in records
        }
        return _verdict(
            bool(held_countries & set(countries)),
            f"PRIOR_INSTITUTION: studied in {sorted(held_countries)}",
        )
    names = {str(getattr(record, "institution", "")).casefold() for record in records}
    wanted_name = condition.value.strip().casefold()
    if not wanted_name:
        return _undecidable(
            f"PRIOR_INSTITUTION: '{condition.value}' names no institution to match"
        )
    if wanted_name in names:
        return Decision("SATISFIED", f"PRIOR_INSTITUTION: studied at {condition.value}")
    return _undecidable(
        f"PRIOR_INSTITUTION: '{condition.value}' is a name, not a country list -- "
        "a human decides whether it matches"
    )


def _decide_grade(
    condition: ConditionTriple, profile: object, _today: _date | None = None
) -> Decision:
    bar_text, scale = _split_scale(condition.value)
    bar = _parse_finite(bar_text)
    if bar is None or not scale:
        return _undecidable(f"GRADE: '{condition.value}' does not state a finite bar")
    norm_wanted_scale = _normalize_scale(scale)
    matched_decisions: list[Decision] = []
    unstated_markers = {"", "not stated", "unknown", "none", "n/a", "-"}
    for record in getattr(profile, "academic_history", ()):
        rec_scale = str(getattr(record, "grading_scale", ""))
        raw_grade = str(getattr(record, "grade", "")).strip()
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
        item_lang = _normalize_language(str(getattr(item, "language", "")))
        item_level = str(getattr(item, "level", "")).strip()
        item_ev_type = str(getattr(item, "evidence_type", "") or "").upper()
        if not item_lang:
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
