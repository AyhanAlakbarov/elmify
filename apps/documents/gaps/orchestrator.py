"""Gap review orchestrator: aggregates all deterministic gap questions for a
student's fact ledger.
"""

from __future__ import annotations

from apps.documents.gaps.detectors.academics import (
    education_completeness,
    missing_degree_detail,
    missing_grade,
    missing_medium_of_instruction,
)
from apps.documents.gaps.detectors.profile import (
    abbreviated_names,
    missing_contact,
    name_parts,
)
from apps.documents.gaps.detectors.requirements import (
    _active_draft_programme_questions,
    absent_sections,
    incomplete_entry,
    missing_award,
    missing_language_detail,
    missing_publication_detail,
    programme_required,
    upper_secondary_required,
)
from apps.documents.gaps.detectors.timeline import timeline_gaps
from apps.documents.gaps.models import GapQuestion
from apps.funding.models import Program
from apps.tenancy.models import Membership


def gap_questions(
    student: Membership, programme: Program | None = None
) -> tuple[GapQuestion, ...]:
    """Everything the ledger can be asked about without a model call.

    Ordered by value, highest first, and the order is the only thing spent: a
    contact line and a language certificate come before a publication's year,
    so a student who stops a third of the way down has answered the questions
    every destination asks. There is no cap, deliberately -- a dropped question
    is a fact the ledger never gets and nothing ever asks for again, which is
    the silent failure this repo keeps recording.

    Deliberately whole-ledger and one-shot rather than a conversation: these
    questions are independent of each other, the student sees one form, and a
    chat loop would cost a call per turn to produce the same questions in a
    worse order.

    With a programme, its own `include` requirements are asked last -- they
    are the most specific and the least likely to be answerable from memory.
    """
    questions = (
        missing_contact(student)
        + name_parts(student)
        + missing_language_detail(student)
        + timeline_gaps(student)
        + missing_medium_of_instruction(student)
        + missing_grade(student)
        + missing_degree_detail(student)
        + abbreviated_names(student)
        + incomplete_entry(student)
        + missing_publication_detail(student)
        + missing_award(student)
        + absent_sections(student)
        + education_completeness(student)
    )
    if programme is not None:
        questions += upper_secondary_required(student, programme) + programme_required(
            student, programme
        )
    else:
        questions += _active_draft_programme_questions(student)
    return questions
