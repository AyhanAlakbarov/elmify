"""The measured question catalogue v2 (2026-10-03): eight line questions and one amount Choice.

Wording A is the v2 spike's wording, measured; wording B is the alternative the harness compares.
Criteria are given to Jev as Noul criteria and, verbatim, to every labeller and chat reader -- the
measurement that cut key disagreement from 4.4% to 0.9% (spec §3.7 rule 8).
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.research.decisions import Choice, Noul


@dataclass(frozen=True)
class LineQuestion:
    id: str
    tier: str
    wording_a: str
    wording_b: str
    true: str
    false: str


LINE_QUESTIONS: tuple[LineQuestion, ...] = (  # noqa: E501
    LineQuestion("money_to_student", "money",  # noqa: E501
                 "Does {p} say that a student is paid money directly, such as a monthly stipend, allowance or cash grant?",  # noqa: E501
                 "Does {p} state cash that a scholarship holder receives?",
                 "cash paid to the student: stipend, monthly allowance, grant, salary",
                 "costs paid on the student's behalf (tuition, tickets, insurance, housing provided); a programme title or the word scholarship alone"),  # noqa: E501
    LineQuestion("costs_covered", "money",  # noqa: E501
                 "Does {p} say that some of a student's costs are paid for them, such as tuition, travel, accommodation, insurance or visa costs?",  # noqa: E501
                 "Does {p} state a cost the funder pays or provides for the student?",
                 "a cost the funder pays for or provides: tuition, travel, accommodation, insurance, visa, books",  # noqa: E501
                 "a title or the word scholarship alone; money paid directly to the student only"),
    LineQuestion("fee_waived", "money",  # noqa: E501
                 "Does {p} say that a tuition or other fee is waived, reduced or not charged for a student?",  # noqa: E501
                 "Does {p} state that a fee is free or reduced for the student?",
                 "tuition or another fee is free, waived, exempted or reduced",
                 "a fee the student must pay; costs covered without saying a fee is waived"),
    LineQuestion("application_date", "deadline",  # noqa: E501
                 "Does {p} state a date, deadline or period for applying?",
                 "Does {p} give when applications open, close or are due?",
                 "a date, deadline or period for submitting applications, including when applications open or close",  # noqa: E501
                 "other dates: publication dates, results, study start, history"),
    LineQuestion("nationality_rule", "eligibility",  # noqa: E501
                 "Does {p} state a nationality, citizenship or country-of-residence condition for applicants?",  # noqa: E501
                 "Does {p} say which citizens or residents may or may not apply?",
                 "which citizens or residents may or may not apply, including 'international students', 'foreign citizens', 'citizens of X'",  # noqa: E501
                 "a country only as the funder or the place of study"),
    LineQuestion("level_rule", "eligibility",  # noqa: E501
                 "Does {p} state which degree or study level the scholarship or application is for, such as bachelor's, master's or PhD?",  # noqa: E501
                 "Does {p} name the degree or study level offered or required?",
                 "the degree or study level offered or required, including in a title such as 'Master's and PhD Scholarships'",  # noqa: E501
                 "no degree or study level is named"),
    LineQuestion("requirement_rule", "eligibility",  # noqa: E501
                 "Does {p} state a grade, test score, age, language or work-experience requirement an applicant must meet?",  # noqa: E501
                 "Does {p} set a minimum an applicant must meet, such as a grade, score, age limit or language level?",  # noqa: E501
                 "a minimum grade, GPA, test, score, age limit, language level or work experience applicants must meet",  # noqa: E501
                 "degree level or nationality only; a document to submit without a threshold"),
    LineQuestion("not_available", "eligibility",  # noqa: E501
                 "Does {p} say that a scholarship or programme is closed, cancelled, abolished or not offered?",  # noqa: E501
                 "Does {p} state that a scholarship or call has ended or is not offered?",
                 "the scholarship, call or programme is closed, cancelled, abolished, suspended or not offered",  # noqa: E501
                 "only some group is excluded; a deadline is merely stated"),
)

AMOUNT_ROLE_OPTIONS: tuple[str, ...] = (
    "paid_to_student", "fee_charged_to_student", "reduction_of_fee", "in_kind_value",
    "cost_estimate", "total_budget_or_count", "other", "unstated",
)
AMOUNT_ROLE_A = "Who pays the amount in {p}?"
AMOUNT_ROLE_B = "What is the amount in {p}, read on its line?"

TIERS: dict[str, str] = {q.id: q.tier for q in LINE_QUESTIONS} | {"amount_role": "money"}
BOUNDS: dict[str, float] = {"deadline": 0.001, "eligibility": 0.002, "documents": 0.002, "money": 0.01}  # noqa: E501


def criteria_text(q: LineQuestion) -> str:
    return f"TRUE: {q.true}. FALSE: {q.false}."


def rules_text(p: str) -> str:
    """Every line question with its criteria, about `p` -- what each reader is told."""
    return "\n".join(f"{q.id}: " + q.wording_a.format(p=p) + " " + criteria_text(q)
                     for q in LINE_QUESTIONS)


YES_NO: dict[str, list[str]] = {q.id: ["yes", "no"] for q in LINE_QUESTIONS}


def jev_noul(q: LineQuestion, item_id: str, wording: str) -> Noul:
    path = f"`lines.{item_id}.text`"
    text = (q.wording_a if wording == "a" else q.wording_b).format(p=path)
    return Noul(question=text, criteria={"true": q.true, "false": q.false}, inspect=path)


def jev_amount_choice(amount_id: str, wording: str, reverse: bool) -> Choice:
    path = f"`amounts.{amount_id}`"
    options = tuple(reversed(AMOUNT_ROLE_OPTIONS)) if reverse else AMOUNT_ROLE_OPTIONS
    text = (AMOUNT_ROLE_A if wording == "a" else AMOUNT_ROLE_B).format(p=path)
    return Choice(question=text, options=options, inspect=path)
