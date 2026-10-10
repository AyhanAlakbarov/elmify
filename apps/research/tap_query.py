"""Tailoring the tap's query to the student -- one rule, three bins (spec 10.5).

A student's answer enters the query only if the target page would PRINT it.
The bin is decided per key, here, as data; never per student and never by a
model. Rendering is slot-filling of stored programme angle rows: deterministic
and reproducible, and no model ever sees the profile to compose query text.

- QUERY_WORDS: the answers a programme or award page prints ("M.Sc. in
  sustainable chemistry", "taught in English", "fully funded", "2027 intake").
- OUTPUT_FILTERS: answers that decide which RESULTS a student is shown -- the
  reader's and the gates' job, after the search. They never reach a provider.
- NEVER: answers no query and no filter may use here. Nationality and
  residence are where the student is from, which a vendor's licence over query
  text (Exa 1.2(c), Tavily 9.2) must never be handed; free text could carry
  anything. Any Art. 9-like field the schema gains goes here, and
  `test_every_profile_field_is_in_exactly_one_bin` fails until it is binned.

Tavily never receives any of this: this module produces SearchRequests for Exa
and Brave only, and the tap is the only caller. `allowed_countries` becomes
destination WORDS at the tap only (decision 33); the area sweep never imports
this module.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

from apps.accounts.schemas import StudentProfileSnapshot
from apps.documents.research_fit.anchors import guard_phrase
from apps.documents.templatetags.cv_countries import country_name

from .providers import SearchRequest
from .tap_seams import AngleRow

QUERY_WORDS = (
    "target_field",
    "research_interests",
    "acceptable_teaching_languages",
    "funding_dependency",
    # The money vocabulary's ORDER: a FUNDING_FIRST student's money angles run
    # first (spec 10.5's table: "and the order the angles run in").
    "strategy",
    "intended_intake",
    "duration_preference",
    # PHD adds the research-pathway words (the spec's `career_intent = research`
    # is `PHD` on master).
    "career_intent",
    "allowed_countries",
)
OUTPUT_FILTERS = (
    "application_budget",
    # The budget rule: what the student can pay decides which results fit, and
    # a page never prints the reader's own capacity.
    "self_funding_capacity",
    "excluded_countries",
    "duration_flexibility",
    "longer_program_justifications",
    "mobility_priorities",
    "weights",
    "non_negotiables",
    "negotiable_preferences",
    "academic_history",
    "experience",
    "language_evidence",
    # Age limits are printed as ELIGIBILITY, which the reader and the gates
    # check against the award's conditions -- never a query word.
    "date_of_birth",
)
NEVER = (
    "nationality",
    # Nationality's rule: where the student lives is as identifying as where
    # they are from, and a home-country award is found by the area sweep of
    # that country (profile-free), never by a query carrying it.
    "country_of_residence",
    # Free text: the one field that could carry anything.
    "additional_notes",
)

_SLOTS = frozenset(
    {"field", "interest", "teaching_language", "money", "intake", "duration", "pathway",
     "destination"}
)
_RESULTS_PER_ANGLE = 12  # decision 30: 10-15 per angle
_MAX_ANGLES = 20  # a tap's 40-call cap over Exa + Brave

_MONEY = {
    "MANDATORY": ("fully funded", "full scholarship", "tuition waiver", "stipend"),
    "IMPORTANT": ("scholarship", "tuition waiver", "stipend"),
    "OPTIONAL": ("partial scholarship", "fee discount", "scholarship"),
}
_DURATION: dict[str, tuple[str, ...]] = {
    "ONE_YEAR": ("one-year master's", "1 year, 60 ECTS"),
    "TWO_YEAR": ("2 years, 120 ECTS",),
    "NONE": (),
}
_PATHWAY = "fully funded MSc position, research assistantship"

#: A capitalised run naming a body or a person rather than a field. guard_phrase
#: strips EVERY capitalised run, which empties the commonest field of all --
#: "Computer Science" -- so the field words are lower-cased before guarding and
#: only the runs carrying one of these words are stripped first. A person named
#: with no title ("catalysis with Ayse Yilmaz") is not caught by this; the
#: student's own institutions are, by `banned`. Recorded, not hidden.
_NAME_MARKERS = frozenset({
    "university", "universität", "universitat", "université", "universite", "universidad",
    "università", "universiteit", "universitet", "üniversitesi", "üniversite", "institute",
    "institut", "college", "school", "academy", "akademie", "polytechnic", "politecnico",
    "hochschule", "prof", "professor", "dr", "lab", "laboratory", "centre", "center",
    "hospital", "inc", "ltd", "gmbh", "llc", "company", "corporation", "bank",
})
_CAPITALISED_RUN = re.compile(
    r"\b(?:[A-ZÀ-ÝĞİÖÜŞÇ][\wÀ-ÿğıöüşç]*\.?)(?:\s+[A-ZÀ-ÝĞİÖÜŞÇ][\wÀ-ÿğıöüşç]*\.?)*"
)
_CONNECTORS = frozenset({"at", "in", "with", "from", "of", "for", "and", "under", "by", "on"})


@dataclass(frozen=True)
class TapQueryInputs:
    """The query-word bin, and nothing else: the shape IS the allow-list
    (spec 10.5, D.6) -- a fact with no field here cannot travel."""

    field_words: tuple[str, ...]
    interest_words: tuple[str, ...]
    teaching_languages: tuple[str, ...]
    money_words: tuple[str, ...]
    money_first: bool
    intake_year: int
    duration_words: tuple[str, ...]
    research_pathway: bool
    destinations: tuple[str, ...]


def _banned(profile: StudentProfileSnapshot) -> frozenset[str]:
    """What must never survive into field words: the student's own schools
    (AcademicRecord.institution), and where they are from, by name.
    ExperienceRecord has no employer field on master -- only a free-text
    summary, which is an output filter and never read here."""
    names = {record.institution for record in profile.academic_history}
    names |= {country_name(profile.nationality), country_name(profile.country_of_residence)}
    return frozenset(name for name in names if name)


def _strip_named_runs(text: str) -> str:
    def drop(match: re.Match[str]) -> str:
        words = {word.strip(".").lower() for word in match.group(0).split()}
        return " " if words & _NAME_MARKERS else match.group(0)

    return _CAPITALISED_RUN.sub(drop, text)


def _words(text: str, *, banned: frozenset[str]) -> str:
    guarded = guard_phrase(_strip_named_runs(text).lower(), banned=banned).split()
    while guarded and guarded[0] in _CONNECTORS:
        guarded.pop(0)
    while guarded and guarded[-1] in _CONNECTORS:
        guarded.pop()
    return " ".join(guarded)


def inputs_from(profile: StudentProfileSnapshot) -> TapQueryInputs:
    banned = _banned(profile)
    field = _words(profile.target_field, banned=banned)
    interests = tuple(
        phrase for phrase in (_words(i, banned=banned) for i in profile.research_interests)
        if phrase
    )
    excluded = set(profile.excluded_countries)
    return TapQueryInputs(
        field_words=(field,) if field else (),
        interest_words=interests,
        teaching_languages=tuple(profile.acceptable_teaching_languages),
        money_words=_MONEY[profile.funding_dependency],
        money_first=profile.strategy == "FUNDING_FIRST",
        intake_year=profile.intended_intake.year,
        duration_words=_DURATION[profile.duration_preference],
        research_pathway=profile.career_intent == "PHD",
        destinations=tuple(
            country_name(code) for code in profile.allowed_countries if code not in excluded
        ),
    )


def _slots(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}


def render_tap_queries(
    inputs: TapQueryInputs, angles: tuple[AngleRow, ...]
) -> tuple[tuple[str, SearchRequest], ...]:
    """(angle id, request) per renderable angle, in run order, at most _MAX_ANGLES.

    The angle id rides beside the request, not inside it: SearchRequest's
    field list is pinned so no student fact can travel in it, and `phrasing`
    carries "english" / "local" for the tally, as the harness sets it.
    """
    values = {
        "field": inputs.field_words[0] if inputs.field_words else "",
        "interest": inputs.interest_words[0] if inputs.interest_words else "",
        "teaching_language": (
            f"taught in {inputs.teaching_languages[0]}" if inputs.teaching_languages else ""
        ),
        "money": ", ".join(inputs.money_words[:2]),
        "intake": str(inputs.intake_year),
        "duration": inputs.duration_words[0] if inputs.duration_words else "",
        "pathway": _PATHWAY if inputs.research_pathway else "",
        "destination": ", ".join(inputs.destinations),
    }
    rendered: list[tuple[bool, str, SearchRequest]] = []
    for angle in angles:
        slots = _slots(angle.template)
        if not slots <= _SLOTS:
            continue  # a slot outside the allow-list refuses the angle, never renders it
        if any(not values[slot] for slot in slots):
            continue  # an angle whose input the student did not give is not asked blank
        request = SearchRequest(
            query=" ".join(angle.template.format(**values).split()),
            country_code="",
            language=angle.language,
            phrasing="english" if angle.language == "en" else "local",
            max_results=_RESULTS_PER_ANGLE,
        )
        rendered.append(("money" in slots, angle.id, request))
    if inputs.money_first:
        # Stable: money angles first, each group in stored order.
        rendered.sort(key=lambda item: not item[0])
    return tuple((angle_id, request) for _, angle_id, request in rendered[:_MAX_ANGLES])
