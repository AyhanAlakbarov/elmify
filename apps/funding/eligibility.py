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

from dataclasses import dataclass
from datetime import date as _date
from math import isfinite
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


def expand_countries(value: str) -> tuple[str, ...] | None:
    """A country set from ISO codes or one named region, or None if unknown.

    None, never a partial answer: a region this build does not know must make
    its condition undecidable rather than silently matching nobody.
    """
    text = value.strip()
    if not text:
        return None
    region = REGIONS.get(text.upper())
    if region is not None:
        return region.countries
    codes = tuple(part.strip().upper() for part in text.split(",") if part.strip())
    if codes and all(
        len(code) == 2 and code.isascii() and code.isalpha() for code in codes
    ):
        return codes
    return None


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
    "BACHELOR": ("bachelor", "bsc", "ba ", "b.a", "b.s", "licence", "lisans"),
    "MASTER": ("master", "msc", "m.a", "m.s", "magister"),
    "DOCTORATE": ("doctor", "phd", "ph.d", "doktor"),
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
    "RESIDENCE": ("IN", "NOT_IN"),
    "FIELD": ("IN",),
    "PRIOR_DEGREE": ("GTE", "EQ"),
    "PRIOR_INSTITUTION": ("IN",),
    "GRADE": ("GTE",),
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
    try:
        value = float(text)
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
        if level == "MASTER" and _is_diplom(text):
            return level
    return None


def _split_scale(value: str) -> tuple[str, str]:
    """"3.0 GPA 4.0" -> ("3.0", "GPA 4.0"). A bar with no scale named has none."""
    head, _, tail = value.strip().partition(" ")
    return head, tail.strip()


def decide(condition: ConditionTriple, profile: object) -> Decision:  # noqa: C901
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
    if key == "RESIDENCE":
        return _country_decision(
            condition, str(getattr(profile, "country_of_residence", "")), "country of residence"
        )
    if key == "DESCENT":
        return _undecidable("DESCENT: the profile does not carry descent; a human decides it")
    if key == "FIELD":
        target = str(getattr(profile, "target_field", "")).casefold()
        wanted_fields = [
            part.strip().casefold() for part in condition.value.split(",") if part.strip()
        ]
        if target and any(_field_matches(part, target) for part in wanted_fields):
            return Decision("SATISFIED", f"FIELD: {target} matches {condition.value}")
        # No match is not exclusion: "engineering" does not exclude "robotics".
        return _undecidable(
            f"FIELD: {condition.value} against '{target}' -- a human decides whether they overlap"
        )
    if key == "PRIOR_DEGREE":
        levels = [
            _degree_level(str(getattr(record, "qualification", "")))
            for record in getattr(profile, "academic_history", ())
        ]
        held_levels = [level for level in levels if level is not None]
        if not held_levels:
            return _undecidable("PRIOR_DEGREE: no qualification in the profile names a level")
        wanted_level = condition.value.strip().upper()
        if wanted_level not in _DEGREE_ORDER:
            return _undecidable(f"PRIOR_DEGREE: '{condition.value}' is not a known level")
        best = max(_DEGREE_ORDER.index(level) for level in held_levels)
        wanted_index = _DEGREE_ORDER.index(wanted_level)
        satisfied = best == wanted_index if condition.operator == "EQ" else best >= wanted_index
        return _verdict(satisfied, f"PRIOR_DEGREE: holds {_DEGREE_ORDER[best]}")
    if key == "PRIOR_INSTITUTION":
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
    if key == "GRADE":
        bar_text, scale = _split_scale(condition.value)
        bar = _parse_finite(bar_text)
        if bar is None:
            return _undecidable(f"GRADE: '{condition.value}' does not state a finite bar")
        for record in getattr(profile, "academic_history", ()):
            if str(getattr(record, "grading_scale", "")).casefold() != scale.casefold():
                continue
            grade = _parse_finite(str(getattr(record, "grade", "")))
            if grade is None:
                break
            return _verdict(
                grade >= bar,
                f"GRADE: {getattr(record, 'grade', '')} on {scale} against {bar}",
            )
        # Conversion between grading systems is one-way and never done here.
        return _undecidable(
            f"GRADE: no qualification is graded on '{scale}', and grades are not converted"
        )
    if key == "WORK_EXPERIENCE":
        if condition.unit not in (None, "MONTHS"):
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
        if bar is None:
            return _undecidable(f"WORK_EXPERIENCE: '{condition.value}' is not a number of months")
        return _verdict(months >= bar, f"WORK_EXPERIENCE: {months} months against {bar}")
    if key == "LANGUAGE":
        language, _, level = condition.value.strip().partition(" ")
        if not language:
            # A condition that names no language cannot fail anybody -- this used
            # to be reachable via a legacy row whose value was synthesised from an
            # unrelated numeric comparable_value ("24" or ""), which partitioned
            # into a "language" no student could ever hold and decided FAILED.
            # Fixes every caller, not just the evaluator's legacy translation.
            return _undecidable(f"LANGUAGE: '{condition.value}' does not name a language")
        records = tuple(getattr(profile, "language_evidence", ()))
        if not records:
            return _undecidable("LANGUAGE: the profile does not carry language evidence")
        evidence = {
            str(getattr(item, "language", "")).casefold(): str(getattr(item, "level", ""))
            for item in records
        }
        held_level = evidence.get(language.casefold())
        if held_level is None:
            return _verdict(False, f"LANGUAGE: no evidence for {language}")
        if not level:
            return Decision("SATISFIED", f"LANGUAGE: evidence for {language} is present")
        if held_level.upper() not in _CEFR or level.upper() not in _CEFR:
            return _undecidable(
                f"LANGUAGE: '{held_level}' and '{level}' are not both CEFR levels"
            )
        return _verdict(
            _CEFR.index(held_level.upper()) >= _CEFR.index(level.upper()),
            f"LANGUAGE: {language} at {held_level} against {level}",
        )
    if key == "AGE":
        born = getattr(profile, "date_of_birth", None)
        if born is None:
            return _undecidable("AGE: the profile does not carry a date of birth")
        bar = _parse_finite(condition.value)
        if bar is None:
            return _undecidable(f"AGE: '{condition.value}' is not a number of years")
        today = _date.today()
        years = (
            today.year
            - born.year
            - ((today.month, today.day) < (born.month, born.day))
        )
        satisfied = years <= bar if condition.operator == "LTE" else years >= bar
        return _verdict(satisfied, f"AGE: {years} against {condition.operator} {bar}")
    if key == "GENDER":
        held_gender = str(getattr(profile, "gender", "")).strip()
        if not held_gender:
            return _undecidable("GENDER: the profile does not state a gender")
        return _verdict(
            held_gender.casefold() == condition.value.strip().casefold(),
            f"GENDER: {held_gender} against {condition.value}",
        )
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
