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

import itertools
import re
import string

from babel import Locale, UnknownLocaleError

from apps.accounts.field_taxonomy import (
    TaxonomyParser,
    resolve_field_taxonomy,
    resolve_field_taxonomy_with_llm,
)
from apps.accounts.schemas import StudentProfileSnapshot
from apps.documents.research_fit.anchors import guard_phrase, strip_named_runs
from apps.documents.templatetags.cv_countries import country_name

from .providers import SearchRequest
from .tap_seams import AngleRow, TapQueryInputs

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
    "budget_stretch",
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

SLOTS = frozenset(
    {"field", "interest", "teaching_language", "money", "intake", "duration", "pathway",
     "destination"}
)
_RESULTS_PER_ANGLE = 12  # decision 30: 10-15 per angle

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

#: Names guard_phrase's punctuation strip would mangle ("C++" became "c"): held as
#: letter-only stand-ins through the guard, then put back.
_SYMBOL_WORDS = {"c++": "cplusplussym", "c#": "csharpsym", "f#": "fsharpsym"}
_SYMBOL_WORD = re.compile(r"(?<![\w+#])(c\+\+|c#|f#)(?![\w+#])", re.IGNORECASE)
_CONNECTORS = frozenset({"at", "in", "with", "from", "of", "for", "and", "under", "by", "on"})


def _banned(profile: StudentProfileSnapshot) -> frozenset[str]:
    """What must never survive into field words: the student's own schools
    (AcademicRecord.institution), and where they are from, by name.
    ExperienceRecord has no employer field on master -- only a free-text
    summary, which is an output filter and never read here."""
    names = {record.institution for record in profile.academic_history}
    names |= {country_name(profile.nationality), country_name(profile.country_of_residence)}
    return frozenset(name for name in names if name)


def _words(text: str, *, banned: frozenset[str]) -> str:
    held = _SYMBOL_WORD.sub(lambda m: f" {_SYMBOL_WORDS[m.group(1).lower()]} ", text)
    guarded = guard_phrase(strip_named_runs(held).lower(), banned=banned).split()
    back = {stand_in: word for word, stand_in in _SYMBOL_WORDS.items()}
    guarded = [back.get(word, word) for word in guarded]
    while guarded and guarded[0] in _CONNECTORS:
        guarded.pop(0)
    while guarded and guarded[-1] in _CONNECTORS:
        guarded.pop()
    return " ".join(guarded)


def inputs_from(
    profile: StudentProfileSnapshot,
    *,
    parser: TaxonomyParser | None = None,
    student_id: str = "anonymous",
) -> TapQueryInputs:
    banned = _banned(profile)
    field = _words(profile.target_field, banned=banned)
    interests = tuple(
        phrase for phrase in (_words(i, banned=banned) for i in profile.research_interests)
        if phrase
    )
    field_words: tuple[str, ...] = (field,) if field else ()
    if field:
        resolution = (
            resolve_field_taxonomy_with_llm(
                field,
                interests,
                parser=parser,
                student_id=student_id,
                banned=banned,
            )
            if parser is not None
            else resolve_field_taxonomy(field, interests)
        )
        if resolution.is_ambiguous_or_interdisciplinary:
            expanded = [field]
            for title in resolution.canonical_degree_titles[:8]:
                guarded_title = _words(title, banned=banned)
                if guarded_title and guarded_title not in expanded:
                    expanded.append(guarded_title)
            field_words = tuple(expanded)
    excluded = set(profile.excluded_countries)
    has_no_funding_needed = any(
        c.kind == "OTHER" and c.value.strip().upper() == "NO_FUNDING_NEEDED"
        for c in (*profile.non_negotiables, *profile.negotiable_preferences)
    )
    ignores_funding = (
        profile.funding_dependency == "OPTIONAL" and profile.self_funding_capacity is None
    ) or (
        profile.funding_dependency in {"OPTIONAL", "IMPORTANT"} and has_no_funding_needed
    )
    return TapQueryInputs(
        field_words=field_words,
        interest_words=interests,
        teaching_languages=tuple(profile.acceptable_teaching_languages),
        money_words=() if ignores_funding else _MONEY[profile.funding_dependency],
        money_first=profile.strategy == "FUNDING_FIRST",
        intake_year=profile.intended_intake.year,
        duration_words=_DURATION[profile.duration_preference],
        research_pathway=profile.career_intent == "PHD",
        # ISO codes: each query names them in its template's language (render time).
        destinations=tuple(code for code in profile.allowed_countries if code not in excluded),
    )


def _slots(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}


def _country(code: str, language: str) -> str:
    """A destination as a page in `language` names it: "Deutschland" in a German
    template, "Germany" in an English one (CLDR, through Babel)."""
    try:
        name = Locale.parse(language).territories.get(code)
    except (ValueError, UnknownLocaleError):
        name = None
    return name or country_name(code)


def _diagonal(interests: int, destinations: int) -> list[tuple[int, int]]:
    """(interest, destination) index pairs, ordered so every interest and every
    destination comes early: (0,0), (0,1), (1,0), (0,2), (1,1), (2,0), ..."""
    pairs = [(i, d) for i in range(max(interests, 1)) for d in range(max(destinations, 1))]
    return sorted(pairs, key=lambda pair: (pair[0] + pair[1], pair[0]))


def render_tap_queries(
    inputs: TapQueryInputs,
    angles: tuple[AngleRow, ...],
) -> tuple[tuple[str, SearchRequest], ...]:
    """(angle id, request) in every run-order render; the caller caps.

    An angle with an {interest} or {destination} slot renders once per research
    interest and once per destination: one query naming three countries returned
    5 universities, all German, where one query per country returned 16 across
    the three (2026-10-12 probe). The order is round-robin across
    angles, and each angle starts one destination further on, so every country
    is asked before any country repeats (c093e77a started every angle at the
    first country: 15 angles x 3 countries gave Sweden no query, 2026-10-14).

    The angle id rides beside the request, not inside it: SearchRequest's
    field list is pinned so no student fact can travel in it, and `phrasing`
    carries "english" / "local" for the tally, as the harness sets it.
    """
    values = {
        "field": inputs.field_words[0] if inputs.field_words else "",
        "teaching_language": (
            f"taught in {inputs.teaching_languages[0]}" if inputs.teaching_languages else ""
        ),
        "money": ", ".join(inputs.money_words[:2]),
        "intake": str(inputs.intake_year),
        "duration": inputs.duration_words[0] if inputs.duration_words else "",
        "pathway": _PATHWAY if inputs.research_pathway else "",
    }
    fields, interests, destinations = inputs.field_words, inputs.interest_words, inputs.destinations

    def request(
        angle: AngleRow, field_val: str, interest: str, codes: tuple[str, ...]
    ) -> SearchRequest:
        filled = {
            **values,
            "field": field_val,
            "interest": interest,
            "destination": ", ".join(_country(code, angle.language) for code in codes),
        }
        return SearchRequest(
            query=" ".join(angle.template.format(**filled).split()),
            country_code="",
            language=angle.language,
            phrasing="english" if angle.language == "en" else "local",
            max_results=_RESULTS_PER_ANGLE,
        )

    # (money?, angle, field_val, interest, destination code or "") per render, per angle.
    per_angle: list[list[tuple[bool, AngleRow, str, str, str]]] = []
    for index, angle in enumerate(angles):
        slots = _slots(angle.template)
        if not slots <= SLOTS:
            continue  # a slot outside the allow-list refuses the angle, never renders it
        given = {**values, "interest": interests, "destination": destinations}
        if any(not given[slot] for slot in slots):
            continue  # an angle whose input the student did not give is not asked blank
        uses_interest, uses_destination = "interest" in slots, "destination" in slots
        uses_multi_field = "field" in slots and len(fields) > 1 and not uses_interest
        if uses_multi_field:
            pairs = _diagonal(len(fields), len(destinations) if uses_destination else 0)
            if uses_destination:
                shift = index % len(pairs)
                pairs = pairs[shift:] + pairs[:shift]
            per_angle.append([
                (
                    "money" in slots,
                    angle,
                    fields[f_idx],
                    "",
                    destinations[d] if uses_destination else "",
                )
                for f_idx, d in pairs
            ])
        else:
            pairs = _diagonal(
                len(interests) if uses_interest else 0,
                len(destinations) if uses_destination else 0,
            )
            if uses_destination:
                shift = index % len(pairs)
                pairs = pairs[shift:] + pairs[:shift]
            per_angle.append([
                (
                    "money" in slots,
                    angle,
                    values["field"],
                    interests[i] if uses_interest else "",
                    destinations[d] if uses_destination else "",
                )
                for i, d in pairs
            ])
    if inputs.money_first:
        # Stable: money angles first, each group in stored order.
        per_angle.sort(key=lambda renders: not renders[0][0])
    ordered = [
        render
        for round_ in itertools.zip_longest(*per_angle)
        for render in round_
        if render is not None
    ]
    return tuple(
        (angle.id, request(angle, field_val, interest, (code,) if code else ()))
        for _, angle, field_val, interest, code in ordered
    )
