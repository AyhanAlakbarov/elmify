"""The funding question set: §5.2's catalogue under definitions v3, per award (verified-catalog §5).

Every question refers to page text by key -- `amounts.m2`, `places.p1`, `proposed.requirements.0`,
`L4` -- and never carries it: question text and criteria travel outside the untrusted wrapper.
Wording is §5.2's wording A; the criteria are §5.2.1's definitions v3.

One reading answers at most `BATCH` questions, because the reader's reply is capped
(`readers.MAX_OUTPUT_TOKENS`, about 25 answers with quotes). So a section is read in batches:
batch 0 carries the one proposal (requirements, where code alone found 7 of 50 and the proposer
lifted it to 28 of 50, §5) and the kind of each proposed quote; batches 1.. carry the questions
about code's own candidates, which do not depend on the proposals and so run in parallel with it.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from apps.research.candidates import Candidates, Found, find_all
from apps.research.card_engine import Question, Quote, Section, proposal, yes_no

from .groups import group_of

logger = logging.getLogger(__name__)

BATCH = 20

CRITERIA = """Definitions (version 3). Read the section in its own language; answer in the options.
- Level: the TARGET level the award is for. A degree the applicant must already hold ("completed a
  first degree", "2 years' work after the bachelor's") is a prior_degree requirement, and "PhD
  holders cannot apply" an excluded_degree requirement; neither is the level. When the section
  names its students by year of study ("1st-3rd year students", "I, II ve III kurs"), the level is
  year_of_study.
- Level, several named: master_among_several when the section names several target levels and
  master's is one of them. When it names several and master's is not one of them, the level is
  the first of bachelor, phd, postdoc (in that order) that it names.
- Level, in general: higher_education_general when the section names university or
  higher-education students in general and names no level. It is not "any" (the section says
  all or any level) and not "not_stated" (the section says nothing about level).
- Nationality: a condition is a named list of countries, regions or citizenships. Generic
  "international" or "foreign" students is not a list. Residence limits, stateless persons and
  compatriots abroad are conditions for applying.
- Application dates are dates of applying to THIS award. An olympiad, exam, event or competition
  date, or another programme's date, is "other" unless the section says applying happens through
  that event. "Applications are open" with no date is not a date.
- A required test or certificate (SAT, ACT, a copy of a language certificate) is a condition for
  applying even with no score.
- "The programme does not pay X" is none for X, never a waiver: a waiver says the student is not
  charged."""

_PAYS = ("paid_to_student", "fee_charged_to_student", "application_fee", "fee_reduction",
         "in_kind_value", "cost_estimate", "total_budget_or_count", "other", "not_stated")
COVERS = ("tuition", "living", "travel", "housing", "insurance", "relocation", "total")
BENEFICIARIES = ("student", "spouse_or_partner", "children", "family_or_dependants")
_FREQUENCY = ("monthly", "annual", "per_semester", "one_off", "instalments", "not_stated")
_DURATION = ("whole_programme", "first_year_only", "from_second_year", "one_semester",
             "two_semesters", "during_mobility_or_internship", "until_next_assessment", "other",
             "not_stated")
_BOUND = ("exact", "up_to", "at_least", "approximately", "not_stated")
DATE_ROLES = ("application_deadline", "application_opening", "fee_deadline", "application_period",
              "results_announced", "selection_or_award", "funding_period", "programme_start",
              "page_published_or_updated", "other", "not_stated")
REQUIREMENT_KINDS = ("prior_degree", "excluded_degree", "language_test", "test_or_certificate",
                     "grade", "age", "residence_limit", "stateless", "compatriot",
                     "other_condition", "none")
EXTRAS = ("travel", "insurance", "housing", "language_year", "visa_support", "family_support")
OBLIGATIONS = ("return_home", "work_in_host", "serve_funder", "repay_on_breach")
#: The closed lists of funding_judge (spec §3.1), lower-cased; copied, not imported, because
#: slice 3 deletes that module's vote.
_HOLDER = ("national_government", "subnational_government", "political_foundation", "religious",
           "private_foundation", "employer", "intergovernmental", "regional_fund",
           "embassy_bilateral", "diaspora_affinity", "professional_body", "bank_or_lender",
           "alumni", "institution", "not_stated")
_ROUTE = ("automatic_on_admission", "considered_with_admission", "student_applies_separately",
          "institution_nominates", "home_government_nominates", "joint_selection", "other",
          "not_stated")
_MONEY = ("grant", "fee_waiver", "subsidy", "loan", "forgivable_loan", "mixed", "other",
          "not_stated")
_COVER_LEVEL = ("none", "partial", "full", "not_stated")

REQUIREMENTS = proposal(
    "requirements",
    "Point at every span that states a condition for applying to this award: a degree held or "
    "excluded, a test or certificate, a grade, an age, a residence limit, being stateless, or "
    "being a compatriot abroad.",
)

#: Asked once per award: (id, wording A, options, criteria). None as options means yes/no.
AWARD: tuple[tuple[str, str, tuple[str, ...] | None, str], ...] = (
    ("target_level", "Which degree level is this award for?",
     ("master", "bachelor", "phd", "postdoc", "master_among_several",
      "higher_education_general", "any", "year_of_study", "not_stated"),
     "The level the award is FOR, never a degree the applicant must already hold."),
    ("place_basis", "Do these lines test the applicant's citizenship, residence, or both?",
     ("citizenship", "residence", "both", "not_stated"), ""),
    ("money_form", "What form does the money take?", _MONEY, ""),
    ("holder_kind", "Which kind of body gives the money described in these lines?", _HOLDER, ""),
    ("route", "How does a student obtain this money?", _ROUTE, ""),
    ("route_order", "When the money and the admission are applied for separately, which comes "
     "first?", ("before_admission", "after_admission", "parallel", "not_stated"), ""),
    ("tuition_level", "How much of tuition does this award cover?", _COVER_LEVEL,
     "A sentence saying the programme does not pay tuition is none, never a waiver."),
    ("living_level", "How much of living costs does this award cover?", _COVER_LEVEL, ""),
    ("apply_here", "Do these lines state that students apply to the organisation whose page "
     "this is for this money?", None, ""),
    ("apply_elsewhere", "Do these lines state that students apply to a different organisation "
     "than the one whose page this is for this money?", None, ""),
    ("institution_wide", "Do these lines state that students of any programme at the "
     "organisation whose page this is can receive this money?", None, ""),
    ("renewal_condition", "Do these lines state a condition for keeping or renewing the award "
     "after its first period?", None, ""),
    ("internationals", "Do these lines state that international or foreign students are "
     "eligible?", None, ""),
    ("eligibility_elsewhere", "Do these lines say the list of who may apply is given somewhere "
     "else (an agreement, a country list, a drop-down menu, another page)?", None, ""),
    ("discontinued", "Do these lines state that this award is discontinued or not offered in "
     "the coming round?", None, ""),
    ("window_closed", "Do these lines state that applications for this award are currently "
     "closed?", None, ""),
    ("funding_period", "Do these lines state the years during which this award is funded or "
     "offered?", None, ""),
    *((f"extra_{x}", f"Do these lines state that the award includes {x.replace('_', ' ')}?",
       None, "") for x in EXTRAS),
    *((f"obligation_{x}", "Do these lines state that the holder must "
       f"{x.replace('_', ' ').replace('host', 'the host country')}?", None, "")
      for x in OBLIGATIONS),
)


#: The card field an AWARD question is parsed into, where it is not the question's own id.
AWARD_FIELD = {"place_basis": "nationality", "internationals": "nationality",
               "eligibility_elsewhere": "nationality",
               **{f"extra_{x}": "extras" for x in EXTRAS},
               **{f"obligation_{x}": "obligations" for x in OBLIGATIONS}}


def _q(qid: str, text: str, options: tuple[str, ...] | None, criteria: str = "") -> Question:
    return yes_no(qid, text, criteria) if options is None else Question(qid, text, options,
                                                                         criteria)


def on_line(group: Mapping[str, Found[Any]], line: int) -> list[str]:
    """The keys of the candidates in `group` found on line number `line` -- the places (or
    levels, or intakes) that share an amount's or date's own line. Used by every question that
    asks "for all, or per place on its own line"; the parse step reuses it."""
    return [key for key, found in group.items() if found.line == line]


def _amount(key: str, c: Candidates) -> list[Question]:
    found = c.amounts[key]
    ref = f"`amounts.{key}`"
    qs = [_q(f"pays_{key}", f"Who pays the amount in {ref}?", _PAYS,
             "A sentence saying a cost is NOT paid by the programme is never fee_reduction.")]
    qs += [_q(f"covers_{x}_{key}", f"Does the text state that the amount in {ref} is for {x}?",
              None, "yes only when the text names it as what this amount pays for; a "
              "scholarship or stipend whose purpose is not named is no.") for x in COVERS]
    qs.append(_q(f"frequency_{key}", f"How often is the amount in {ref} paid or charged?",
                 _FREQUENCY))
    qs.append(_q(f"duration_{key}", f"For how long is the amount in {ref} paid?", _DURATION))
    if found.value.bound is None:  # code sets range and approximately; it never asks them
        qs.append(_q(f"bound_{key}", f"Is the amount in {ref} an exact sum, a maximum, a "
                     "minimum, or approximate?", _BOUND))
    qs += [_q(f"for_{x}_{key}", f"Does the text state that the amount in {ref} is for the "
              f"{x.replace('_', ' ')}?", None, "A sum paid to the student with no beneficiary "
              "named is for the student.") for x in BENEFICIARIES]
    qs.append(_q(f"for_all_{key}", f"Does {ref} apply to all applicants alike?", None))
    qs += [_q(f"for_{p}_{key}", f"Does {ref} apply to applicants from `places.{p}`?", None)
           for p in on_line(c.places, found.line)]
    if levels := on_line(c.levels, found.line):
        qs.append(_q(f"level_{key}", f"Which study level does the amount in {ref} apply to?",
                     (*levels, "all_levels", "not_stated")))
    if intakes := on_line(c.intakes, found.line):
        qs.append(_q(f"intake_{key}", f"Which intake or year does the amount in {ref} apply "
                     "to?", (*intakes, "not_stated")))
    return qs


def _date(key: str, group: str, c: Candidates) -> list[Question]:
    found = (c.dates if group == "dates" else c.relative_dates)[key]
    ref = f"`{group}.{key}`"
    qs = [_q(f"role_{key}", f"What is the date in {ref}?", DATE_ROLES)]
    if getattr(found.value, "order_ambiguous", False):
        qs.append(_q(f"order_{key}", f"In {ref}, is the first number the day or the month?",
                     ("day_first", "month_first", "not_stated")))
    qs.append(_q(f"for_all_{key}", f"Does {ref} apply to all applicants alike?", None))
    qs += [_q(f"for_{p}_{key}", f"Does {ref} apply to applicants from `places.{p}`?", None)
           for p in on_line(c.places, found.line)]
    return qs


def _place(key: str, c: Candidates) -> list[Question]:
    ref = f"`places.{key}`"
    qs = [_q(f"eligible_{key}", f"Do these lines state that applicants connected to {ref} "
             "can apply, as citizens or residents of it, or as students of an "
             "institution whose name contains it?", None),
          _q(f"excluded_{key}", f"Do these lines state that applicants from {ref} cannot "
             "apply?", None)]
    if group_of(c.places[key].value.text) == "LMY":
        qs.append(_q(f"sole_{key}", f"Is {ref} the whole condition on who may apply, with "
                     "nothing added to it?", None))
    return qs


def wants(fields: frozenset[str], *names: str) -> bool:
    """Whether a read restricted to `fields` (empty: every field) parses any of `names`."""
    return not fields or bool(fields.intersection(names))


def code_questions(c: Candidates, fields: frozenset[str] = frozenset()) -> list[Question]:
    """Every question about the award and code's own candidates, in a stable order. With
    `fields` (the site hunt, 2c), only the questions those card fields are parsed from -- each
    field's whole set, because `parse` holds a field any of its questions left unanswered."""
    qs = [_q(qid, text, options, criteria) for qid, text, options, criteria in AWARD
          if wants(fields, AWARD_FIELD.get(qid, qid))]
    if wants(fields, "benefits", "fees"):
        for key in c.amounts:
            if key not in c.conversion_of:  # a conversion is asked about once, with its amount
                qs += _amount(key, c)
    if wants(fields, "dates"):
        for key in c.dates:
            qs += _date(key, "dates", c)
        for key in c.relative_dates:
            qs += _date(key, "relative_dates", c)
    if wants(fields, "nationality"):
        for key in c.places:
            qs += _place(key, c)
    if wants(fields, "requirements"):
        qs += [_q(f"requires_{key}", f"Do these lines state `requirements.{key}` as a condition "
                  "for applying?", None) for key in c.requirements]
    if wants(fields, "funding_duration"):
        qs += [_q(f"funds_{key}", f"Does `durations.{key}` state how long the funding lasts, not "
                  "how long the programme is?", None) for key in c.durations]
    return qs


def line_of(quote: Quote) -> int:
    return int(quote.where[1:].split(".")[0]) if quote.where.startswith("L") else -1


def repeats_code(c: Candidates, quote: Quote) -> bool:
    """Whether the proposed quote only repeats a code requirement on its own line."""
    line = line_of(quote)
    return any(found.line == line and found.value.text in quote.text
               for found in c.requirements.values())


def kind_questions(c: Candidates, proposed: Mapping[str, tuple[Quote, ...]]) -> list[Question]:
    """What condition each proposed quote states, skipping a quote that only repeats a code
    candidate on its line (code's requirement is already asked about)."""
    qs = []
    for n, quote in enumerate(proposed.get("requirements", ())):
        if repeats_code(c, quote):
            continue
        qs.append(Question(f"kind_{n}", f"What condition for applying does the quote "
                           f"`proposed.requirements.{n}` state?", REQUIREMENT_KINDS))
    if len(qs) > BATCH:
        logger.warning("funding: %d proposed requirements, %d asked", len(qs), BATCH)
    return qs[:BATCH]


@dataclass(frozen=True)
class Funding:
    """One batch of the funding set over one award's section. Batch 0: the proposal and the
    kinds of what it found. Batch n >= 1: slice n of `code_questions`."""

    batch: int = 0
    #: The site hunt reads only these card fields (2c); empty is every field.
    fields: frozenset[str] = frozenset()
    name: str = "funding"
    version: str = "v3"
    criteria: str = CRITERIA

    def proposals(self, section: Section) -> Sequence[Question]:
        return (REQUIREMENTS,) if self.batch == 0 and wants(self.fields, "requirements") else ()

    def questions(self, section: Section, candidates: Candidates,
                  proposed: Mapping[str, tuple[Quote, ...]]) -> Sequence[Question]:
        if self.batch == 0:
            return kind_questions(candidates, proposed)
        return code_questions(candidates, self.fields)[(self.batch - 1) * BATCH:
                                                       self.batch * BATCH]


def batches(section: Section, fields: frozenset[str] = frozenset()) -> int:
    """How many code batches the section needs (batch 0 comes on top)."""
    return math.ceil(len(code_questions(find_all(section.lines), fields)) / BATCH)
