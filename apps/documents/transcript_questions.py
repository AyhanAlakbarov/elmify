"""Every question Jev is asked about a transcript, and the bar that makes an answer a highlight.

The Jev contract (spec 2026-09-22 typed-decisions, 3.1a) is followed to the letter: one judgment
per question; each question points at a named part of the state with `inspect`; every Choice has
a way out (`other` / `none`); a Noul is phrased so that yes is the high value. Jev only ever
chooses -- a column's kind, a row's kind, which printed line or number is which -- and code
copies what it chose (apps/documents/transcript.py). It never counts, sums or converts.

`inspect` names a part by key, never by list position -- `rows.r12`, not `rows[12]`. Measured
2026-09-26 on two sample transcripts: addressed by position, Jev answered about a neighbouring row
or column (six of 71 rows mislabelled on each of two runs; the photographed table's grade column
read as `other`), and addressed by key, about the right one (no row wrong on two runs; the grade
column at 1.0).
"""

from __future__ import annotations

from apps.reference_data import ISO_3166_ALPHA2_CODES
from apps.research.decisions import Choice, Noul, Question

#: The decision ID the layer routes and records these under. It never reaches the model.
DECISION = "transcript"

#: ponytail: one bar for every question, untuned -- the vendor's "act automatically" bar for a
#: high-stakes Choice (research note 2026-09-23, rule 11). Spec 7 gate 1 tunes it per question
#: on the labelled transcript set; until then an answer below it is highlighted, never dropped.
UNSURE_BELOW = 0.85

COLUMN_KINDS = ("course_title", "credits", "grade", "course_code", "hours", "semester", "other")
ROW_KINDS = (
    "course",
    "semester_heading",
    "semester_total",
    "overall_total",
    "header",
    "other",
)
CREDIT_SYSTEMS = ("ECTS", "US_SEMESTER_HOUR", "LOCAL", "UNKNOWN")
NONE = "none"


def column(index: int) -> Choice:
    return Choice(
        question="What does this column of the transcript's course table hold?",
        options=COLUMN_KINDS,
        criteria={
            "course_title": "the name of each course, module or subject",
            "credits": {
                "what": "the credit value of each course: ECTS, AKTS, kredi, credits, "
                "credit hours or зачётные единицы",
                "not_for": "hours of teaching, or a grade",
            },
            "grade": {
                "what": "the mark the student received: a number, a letter such as AA or B+, "
                "or a word such as 'отлично' or 'yaxşı'",
                "not_for": "credits",
            },
            "course_code": "a short identifier of each course, such as CHEM101 or 0301101",
            "hours": "hours of teaching or study: saat, часы, hours",
            "semester": "the semester, term or year each course was taken in",
            "other": "anything else, or a column mixing several of the above",
        },
        inspect=f"`columns.c{index}.cells`",
    )


def row_kind(index: int) -> Choice:
    return Choice(
        question="What kind of row of a transcript's course table is this?",
        options=ROW_KINDS,
        criteria={
            "course": "one course or module the student took, with its own title",
            "semester_heading": {
                "what": "a heading naming a semester, term or year",
                "examples": ["1st semester", "Güz Dönemi", "I kurs, II semestr", "1 семестр"],
            },
            "semester_total": {
                "what": "a row totalling the credits or grades of one semester only",
                "not_for": "the total of the whole degree",
            },
            "overall_total": "a row totalling the credits or grades of the whole degree",
            "header": "the table's column titles",
            "other": "anything else: a note, a signature, an empty or unreadable row",
        },
        inspect=f"`rows.r{index}`",
    )


def in_progress(index: int) -> Noul:
    return Noul(
        question="Does this row say the course is still in progress, not yet completed?",
        criteria={
            "true": "the row prints a word or mark for it: 'in progress', 'IP', 'devam ediyor', "
            "'davam edir', 'изучается'",
            "false": "the row has a final grade, or simply has no grade printed",
        },
        inspect=f"`rows.r{index}`",
    )


def failed(index: int) -> Noul:
    return Noul(
        question="Does this row record a failed attempt at the course?",
        criteria={
            "true": "a failing grade such as F, FF, FD, 'kəsr', 'неудовлетворительно', "
            "or a word such as failed, repeat or retake",
            "false": "a passing grade, or no grade",
        },
        inspect=f"`rows.r{index}`",
    )


def _pick(question: str, ids: list[str], inspect: str) -> Choice:
    return Choice(
        question=question,
        options=(*ids, NONE),
        criteria={NONE: "the transcript does not print it"},
        inspect=inspect,
    )


def transcript(lines: list[str], numbers: list[str], dates: list[str]) -> dict[str, Question]:
    """The questions about the whole transcript. A pick with no candidates is not asked.

    `lines`, `numbers` and `dates` are the candidate IDs code found; the answer is one of them
    or `none`, and code copies the candidate's text.
    """
    picks: dict[str, Question] = {
        "credit_system": Choice(
            question="Which credit system does this transcript use?",
            options=CREDIT_SYSTEMS,
            criteria={
                "ECTS": "ECTS or AKTS credits",
                "US_SEMESTER_HOUR": "semester hours or credit hours of a United States institution",
                "LOCAL": "another national or institutional credit system, such as 'kredi' "
                "without AKTS or 'кредит'",
                "UNKNOWN": "the transcript does not say",
            },
        ),
        "country": Choice(
            question="In which country is the institution that issued this transcript? "
            "Answer with its ISO 3166 two-letter code.",
            options=(*sorted(ISO_3166_ALPHA2_CODES), NONE),
            criteria={NONE: "the transcript does not show it"},
            inspect="`lines`",
        ),
    }
    if lines:
        picks |= {
            "institution": _pick(
                "Which line names the university or institution that issued this transcript?",
                lines,
                "`lines`",
            ),
            "qualification": _pick(
                "Which line names the degree or qualification, such as Bachelor of Science, "
                "Bakalavr, Lisans or Бакалавр?",
                lines,
                "`lines`",
            ),
            "field": _pick(
                "Which line names the field or subject of study, such as Chemistry, Kimya "
                "or Химия?",
                lines,
                "`lines`",
            ),
        }
    if numbers:
        picks |= {
            "overall_grade": _pick(
                "Which number is the student's overall grade or grade point average?",
                numbers,
                "`numbers`",
            ),
            "grading_scale": _pick(
                "Which number is the highest grade possible on the scale the overall grade is "
                "given on -- the 4 in '3.45 / 4.00', the 100 in a 100-point scale?",
                numbers,
                "`numbers`",
            ),
            "total_credits": _pick(
                "Which number is the total credits of the whole degree or transcript?",
                numbers,
                "`numbers`",
            ),
        }
    if dates:
        picks |= {
            "completed_on": _pick(
                "Which date is the date the degree was completed or awarded?", dates, "`dates`"
            ),
            "expected_completion": _pick(
                "Which date is a planned or expected graduation date?", dates, "`dates`"
            ),
        }
    return picks
