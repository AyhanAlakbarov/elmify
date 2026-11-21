"""Academic detectors: missing grades, degree details, medium of instruction, and completeness."""

from __future__ import annotations

from datetime import date

from apps.documents.dates import parse_cv_date
from apps.documents.gaps.detectors.timeline import _read_date
from apps.documents.gaps.models import (
    GapQuestion,
    Kind,
    _already_created,
    _current,
    _cv_on_file,
    _group_questions,
)
from apps.documents.models import VerifiedFact
from apps.tenancy.models import Membership


def missing_grade(student: Membership) -> tuple[GapQuestion, ...]:
    """A degree the ledger has no mark for.

    One question per degree, asking for the mark and its scale together --
    S-027 puts the grade on the institution's own scale, mark and denominator
    together (16.45/20.0, 3.82/4.0). Never asks for a conversion: 16.45/20.0
    is the claim, and a 4.0-scale equivalent is a new claim nobody made, with
    tables that differ between the institution, the destination country and
    the credential evaluator.

    Deliberately does not ask how many semesters the grade covers. Searched
    for S-027; no source states it, and the degree's own date range already
    carries the period. Recorded as a negative result so nobody re-derives it.

    Until a transcript is ingested this asks for grades a transcript already
    carries -- the check reads the ledger, so it needs no change when that
    lands, and a missing grade is a real defect on a graduate application in
    the meantime.
    """
    questions: list[GapQuestion] = []
    for fact in _current(student, VerifiedFact.Category.EDUCATION):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        if payload.get("grade_native"):
            continue
        degree = str(payload.get("degree_as_awarded") or "your degree")
        institution = str(payload.get("institution_original") or "")
        # A fourth-year applicant has no final mark, and "what grade did you
        # finish with" is the wrong question for them -- measured on the real
        # CV, whose in-progress MSc was asked exactly that. Cambridge's own
        # worked sample prints the in-progress form: "Second Year, 2.1
        # expected". So the question checks completion first and asks for a
        # grade so far, which is a real fact, rather than a final one, which
        # does not exist yet. Owner correction 2026-09-16.
        if _degree_complete(payload):
            prompt = (
                f"What grade did you finish {degree} with, on your "
                "institution's own scale? Give the mark and the scale "
                "together, for example 16.45/20.0."
            )
        else:
            prompt = (
                f"What is your grade so far in {degree}, or your expected "
                "classification, on your institution's own scale? For example "
                "15.8/20.0 to date, or '2.1 expected'."
            )
        questions.append(
            GapQuestion(
                kind=Kind.MISSING_GRADE,
                fact_id=fact.id,
                payload_key="grade_native",
                prompt=prompt,
                evidence=(
                    f"{degree}"
                    + (f" at {institution}" if institution else "")
                    + " is on file with no grade."
                ),
            )
        )
    return tuple(questions)


def _degree_complete(payload: dict[str, object]) -> bool:
    """Whether a degree's end date is in the past.

    No end date renders as "present" and is in progress; a future end date is
    an expected graduation and is in progress too. Only a past end date means a
    final grade can exist. The ledger stores dates as the CV printed them
    ("June 2024", "2024-06-30"), so parse_cv_date does the reading -- and an
    unparseable date is treated as complete, because asking for a final grade
    the student may not have is a recoverable wrong question, while asking a
    graduate for a "grade so far" reads as if we did not read their CV.
    """
    raw = payload.get("end_date")
    if not raw:
        return False
    end = parse_cv_date(raw)
    return end is None or end <= date.today()


def _most_recent_degree(facts: list[VerifiedFact]) -> VerifiedFact | None:
    """The degree that started last, or nothing.

    A degree with no readable start date is never the most recent: the answer
    would be whichever row the database returned first, which is not a fact
    about the student.
    """
    dated = [
        (start, fact)
        for fact in facts
        if isinstance(fact.payload, dict)
        and (start := _read_date(fact.payload.get("start_date"))) is not None
    ]
    if not dated:
        return None
    return max(dated, key=lambda pair: pair[0])[1]


def missing_degree_detail(student: Membership) -> tuple[GapQuestion, ...]:
    """What an education entry carries beyond the degree and the institution.

    S-040, from UCC's own list: "dates, qualification, supervisor,
    dissertation, papers and awards". Toronto's worked CV prints
    "Dissertation: ..." then "Supervisor: Dr. Carine Mendelsson" under the
    degree. We printed neither, because nothing ever asked.

    The thesis is asked of the MOST RECENT degree only. A bachelor's thesis on
    a CV whose master's is in progress is rarely what an admissions reader
    wants, and asking every degree turns one question into three for one fact
    a reader uses once.

    A rank is asked only of a COMPLETED degree that already has a grade. UCC
    wants the cohort size beside a foreign grade -- "interpret grades ...
    indicate range of scores and size of class" -- and US credential guidance
    calls a rank more telling than a converted GPA. But an in-progress student
    has no final rank, and a degree with no grade at all is already being
    asked for the grade by missing_grade; a second question about the same
    line is where a form starts feeling like an interrogation.
    """
    facts = _current(student, VerifiedFact.Category.EDUCATION)
    recent = _most_recent_degree(facts)
    questions: list[GapQuestion] = []
    for fact in facts:
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        degree = str(payload.get("degree_as_awarded") or "your degree")
        if fact is recent and not payload.get("thesis_title"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="thesis_title",
                    prompt=(
                        f"What is the title of your {degree} thesis or dissertation? "
                        "If it is not finished, give the working title."
                    ),
                    evidence=f"{degree} is on file with no thesis title.",
                )
            )
        if payload.get("thesis_title") and not payload.get("supervisor"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="supervisor",
                    prompt=f"Who supervised your {degree} thesis?",
                    evidence=(
                        f"{degree} states a thesis and names nobody who supervised it."
                    ),
                )
            )
        if (
            payload.get("grade_native")
            and not payload.get("class_rank")
            and _degree_complete(payload)
        ):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="class_rank",
                    prompt=(
                        f"Where did you rank in your cohort for {degree}, if your "
                        "institution states it? For example '3rd of 120' or 'top 5%'. "
                        "Leave this blank if it was never published."
                    ),
                    evidence=(
                        f"{degree} has a grade and no rank; a reader abroad cannot tell "
                        "what that grade is worth without the cohort."
                    ),
                )
            )
    return tuple(questions)


def missing_medium_of_instruction(student: Membership) -> tuple[GapQuestion, ...]:
    """What language the student's highest COMPLETED degree was taught in.

    S-050's highest-value find and the one that promises nothing. Cornell, USC,
    BU and ASU all accept an English-taught degree in place of a test, and all
    on different terms, so this asks the fact and says nothing about a waiver:
    the prompt must not imply an exemption it cannot grant, because the layer
    that grants one reads a programme's page and this layer never does.

    Completed only. A degree still running has no certifiable medium yet, and a
    fourth-year applicant asked to produce one is being asked for a document
    their registrar will not issue.
    """
    completed = [
        fact
        for fact in _current(student, VerifiedFact.Category.EDUCATION)
        if _degree_complete(fact.payload if isinstance(fact.payload, dict) else {})
    ]
    highest = _most_recent_degree(completed)
    if highest is None:
        return ()
    payload = highest.payload if isinstance(highest.payload, dict) else {}
    if payload.get("medium_of_instruction"):
        return ()
    degree = str(payload.get("degree_as_awarded") or "your degree")
    return (
        GapQuestion(
            kind=Kind.MEDIUM_OF_INSTRUCTION,
            fact_id=highest.id,
            payload_key="medium_of_instruction",
            prompt=(
                f"What language was {degree} taught in, and can your university "
                "issue a letter confirming it? Several universities ask for this in "
                "writing; what they do with it differs, so we record what yours says."
            ),
            evidence=f"{degree} is on file with no language of instruction.",
        ),
    )


def education_completeness(student: Membership) -> tuple[GapQuestion, ...]:
    """Study and roles the student has, and never thought to write down.

    ETH, verbatim: list "every university attended, including any mobility or
    exchange programmes and study programmes which were not completed." ETH
    treats the omission as the applicant's fault, and neither an Erasmus
    semester nor an abandoned programme is a thing anyone volunteers -- the
    first reads as not a real degree, the second as a failure.

    Also the society/committee role Toronto Mississauga's checklist,
    Cambridge and the Harvard Kennedy School all ask for. S-039 still refuses
    a memberships SECTION; as a question it is one line and the answer is an
    ordinary ExperienceEntry, which is where a role with responsibilities
    belongs.

    Fired on any non-empty ledger, same guard as absent_sections and for the
    same reason: nothing in a ledger built from the student's own CV can
    reveal a degree the CV never mentioned. Each of the three groups is
    gated separately by ``_already_created`` -- like voluntary-role and
    referee, a created group is an ordinary EDUCATION or EXPERIENCE row once
    it lands, so the source_ref stamp is the only thing that stops it
    re-firing forever once answered.

    Two questions per programme because an EducationEntry needs an
    institution AND a degree title, and they share a slug so
    answer_questions writes one fact. A society role needs three, like a
    voluntary one.
    """
    if not _cv_on_file(student):
        return ()
    eth = (
        "ETH Zurich asks for every university attended, including exchange "
        "programmes and programmes that were not completed."
    )
    society = (
        "Toronto, Cambridge and the Harvard Kennedy School all ask for positions "
        "held in student societies and committees."
    )
    questions: list[GapQuestion] = []
    for slug, evidence in (
        ("exchange-programme", eth),
        ("unfinished-programme", eth),
        ("society-role", society),
    ):
        if not _already_created(student, slug):
            questions.extend(_group_questions(slug, Kind.EDUCATION_COMPLETENESS, evidence))
    return tuple(questions)
