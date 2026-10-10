"""The mail decision questions (dashboard spec §4), in one place.

Written to docs/superpowers/research/2026-09-23-jev-question-engineering.md:
atomic questions (rule 1) pointing at the state by name (rule 2), options as
criteria keys with literal descriptions (rules 5, 8), a gate Noul per outcome
option (v5 measured per-option gates raising precision), everything in one
request (rule 10), forward order only (no material order bias measured), English
questions over the original-language email (translation arms gained nothing).
Wording "a" ships; "b" is Gate 12's alternative, kept so `decision_eval` can
compare them. Never change a wording without re-running it.
"""

from __future__ import annotations

from apps.research.decisions import Choice, Noul, Question

DECISION = "mail_decision"
OUTCOMES = ("ADMITTED", "ADMITTED_CONDITIONAL", "WAITLISTED", "REJECTED", "NOT_STATED")
FUNDING_OUTCOMES = ("AWARDED", "WAITLISTED", "NOT_AWARDED", "NOT_STATED")
#: A funding answer in Application.Outcome's vocabulary.
FUNDING_TO_OUTCOME = {"AWARDED": "ADMITTED", "WAITLISTED": "WAITLISTED", "NOT_AWARDED": "REJECTED"}

#: Learn-then-Test delta per barred question: anything that can put a wrong
#: ADMITTED or REJECTED in front of a family is the strictest (1/500, 1,497 clean
#: rows by zero_error_rows_needed); the rest 1/100 (299 rows).
STRICT, ORDINARY = 0.002, 0.01
DELTAS: dict[str, float] = {
    "is_decision": STRICT,
    "gate:ADMITTED": STRICT,
    "gate:REJECTED": STRICT,
    "gate:ADMITTED_CONDITIONAL": ORDINARY,
    "gate:WAITLISTED": ORDINARY,
    "fgate:AWARDED": STRICT,
    "fgate:NOT_AWARDED": STRICT,
    "fgate:WAITLISTED": ORDINARY,
    "other_programme": ORDINARY,
}
GATED = tuple(DELTAS)
_EMAIL = "`email`"

#: question id -> (wording a, wording b)
_NOULS: dict[str, tuple[str, str]] = {
    "is_decision": (
        "Does `email` give the final result of the application to `application.programme`?",
        "Is `email` the institution's decision on the application to `application.programme`?",
    ),
    "gate:ADMITTED": (
        "Does `email` say the applicant is admitted to `application.programme` without conditions?",
        "Is the applicant given an unconditional place on `application.programme` in `email`?",
    ),
    "gate:ADMITTED_CONDITIONAL": (
        "Does `email` offer a place on `application.programme` that depends on a condition the "
        "applicant must still meet?",
        "Is the place on `application.programme` in `email` conditional?",
    ),
    "gate:WAITLISTED": (
        "Does `email` say the applicant is on a waiting, reserve, ranking or pending list for "
        "`application.programme`?",
        "Is the applicant waitlisted for `application.programme` in `email`?",
    ),
    "gate:REJECTED": (
        "Does `email` say the applicant is not offered a place on `application.programme`?",
        "Is the application to `application.programme` refused in `email`?",
    ),
    "fgate:AWARDED": (
        "Does `email` say `application.funding` is awarded to the applicant?",
        "Is the applicant granted `application.funding` in `email`?",
    ),
    "fgate:WAITLISTED": (
        "Does `email` say the applicant is on a reserve or waiting list for `application.funding`?",
        "Is the applicant waitlisted for `application.funding` in `email`?",
    ),
    "fgate:NOT_AWARDED": (
        "Does `email` say `application.funding` is not awarded to the applicant?",
        "Is `application.funding` refused to the applicant in `email`?",
    ),
    "other_programme": (
        "Does `email` offer a place on a programme other than `application.programme`?",
        "Is the applicant offered a different programme than `application.programme` in `email`?",
    ),
}
_IS_DECISION_CRITERIA = {
    "true": "the email states the admission result, or says the result has been made and can "
            "be read in the applicant's portal",
    "false": "an acknowledgement of receipt, a notice of when results will be released, a "
             "document request, an interview invitation, a stage result such as passing "
             "pre-selection, a reminder, a deferral",
}
_OUTCOME_CRITERIA = {
    "ADMITTED": "the email says the applicant is offered or given a place on "
                "`application.programme`, with nothing left to meet",
    "ADMITTED_CONDITIONAL": "the email offers a place on `application.programme` that depends on "
                            "something still to be done or shown, such as a final transcript, a "
                            "grade or a language certificate",
    "WAITLISTED": "the email says there is no place on `application.programme` now and the "
                  "applicant is on a waiting, reserve, ranking or pending list",
    "REJECTED": "the email says the applicant is not offered a place on `application.programme`",
    "NOT_STATED": "the email does not state the result for `application.programme`: it says a "
                  "decision is available elsewhere, or it is about something else",
}
_FUNDING_CRITERIA = {
    "AWARDED": "the email says `application.funding` is awarded or granted to the applicant",
    "WAITLISTED": "the email says the applicant is on a reserve or waiting list for "
                  "`application.funding`",
    "NOT_AWARDED": "the email says `application.funding` is not awarded to the applicant",
    "NOT_STATED": "the email does not give the result for `application.funding`",
}
_CHOICES = {
    "outcome": ("Which result does `email` give for `application.programme`?",
                "What does `email` decide about `application.programme`?"),
    "funding": ("Which result does `email` give for `application.funding`?",
                "What does `email` decide about `application.funding`?"),
}


def questions(wording: str = "a", *, funding: bool) -> dict[str, Question]:
    """Every question, in one map: one request (rule 10)."""
    pick = 0 if wording == "a" else 1
    out: dict[str, Question] = {
        "is_decision": Noul(_NOULS["is_decision"][pick], criteria=_IS_DECISION_CRITERIA,
                            inspect=_EMAIL),
        "outcome": Choice(_CHOICES["outcome"][pick], options=OUTCOMES,
                          criteria=_OUTCOME_CRITERIA, inspect=_EMAIL),
        "other_programme": Noul(_NOULS["other_programme"][pick], inspect=_EMAIL),
    }
    for qid, texts in _NOULS.items():
        if qid.startswith("gate:") or (funding and qid.startswith("fgate:")):
            out[qid] = Noul(texts[pick], inspect=_EMAIL)
    if funding:
        out["funding"] = Choice(_CHOICES["funding"][pick], options=FUNDING_OUTCOMES,
                                criteria=_FUNDING_CRITERIA, inspect=_EMAIL)
    return out
