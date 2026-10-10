"""Turning a submitted form into ledger writes, without trusting the form.

``gaps.py``'s docstring lists three things its first caller owes. Two are
here. The third is not, and cannot be:

- **A narrower key allowlist than gaps.py can express.** ``answer_questions``
  accepts any key the target fact's *category* carries, which is wider than
  the set the detectors ask about -- EDUCATION carries ``grade_conversion``,
  which gaps.py says in as many words it will never ask for, and SKILL carries
  ``category``, ``kind`` and ``evidence``, which are our reading of the
  student's material rather than their claim. ``submit_answers`` closes that
  by never reading a key *out of* the submission. It re-derives the questions
  and looks up each one's own field name, so a pair no current question
  produced is never looked at.

- **Attribution.** Every fact written here gets one ``AuditEvent`` naming
  whoever operated the form. ``created_by`` on the fact stays the student
  regardless -- that is provenance on the ledger row, matching every other
  fact writer (``ingest_uploaded_cv``, ``bridge_profile_to_facts``,
  ``evidence.facts``) -- and the audit trail is where an operator belongs.

- **Authorisation is NOT here.** ``student`` is taken on trust, exactly as
  ``answer_questions`` takes it. Resolving it from an authenticated session is
  ``apps.tenancy.services.current_membership``'s job, and nothing in this
  module has a request to inspect.

- **Notes are not submitted.** ``gap_notes`` output never reaches this module:
  a note has no field name, so there is nothing for ``submitted`` to carry and
  nothing to look up. That is the whole reason it is a separate type.

No model call, so no rate limiter is owed and this module is not evidence that
one exists. A change that gives this form the model-backed question types owes
``apps/ratelimit.py::rate_limited`` in the same change, per CLAUDE.md.

Design: docs/superpowers/specs/2026-08-30-cv-gap-interview-design.md
"""

from __future__ import annotations

from collections.abc import Mapping

from django.db import transaction

from apps.tenancy.models import Membership

from .audit import record_event
from .gaps import GapQuestion, answer_questions, gap_questions
from .models import VerifiedFact


def field_name(question: GapQuestion) -> str:
    """The form field name a question's answer comes back under.

    The contract between whatever renders the form and this module: both sides
    call this, neither invents the string.

    Keyed by the fact (or, for a question that builds a new one, its slug) and
    the payload key rather than by position, because the ledger can move
    between the render and the submit -- a second tab, a counsellor edit, a
    double submit. Positional names silently land an answer on whatever shifted
    into that slot; a stale name here matches no re-derived question and is
    dropped.

    The slug half is what keeps two create-path questions writing the same key
    apart: before it existed both posted under "None:title" and one answer
    landed in both facts.
    """
    return f"{question.fact_id or question.slug}:{question.payload_key}"


@transaction.atomic
def submit_answers(
    submitted: Mapping[str, str],
    *,
    student: Membership,
    actor: Membership | None = None,
) -> tuple[VerifiedFact, ...]:
    """Write the answers a submission carries.

    ``submitted`` is a raw form mapping -- a Django ``QueryDict`` is one -- and
    is read only through ``field_name``. Keys it carries that no current
    question produced are never looked at, which makes the CSRF token, the
    submit button and a hand-edited field name all the same nothing.

    ``actor`` is whoever operated the form, defaulting to the student
    answering their own questions; a counsellor operating it passes themselves
    while ``student`` stays the student. Same shape as ``drafts.py``'s
    ``actor or student``.

    Atomic over both halves. ``answer_questions`` is already atomic on its
    own, so a refused batch was never the risk; a failure between the ledger
    write and its audit is, and would leave facts nobody can trace.
    """
    questions = gap_questions(student)
    answers = [(question, submitted.get(field_name(question), "")) for question in questions]
    written = answer_questions(answers, student=student)
    for fact in written:
        record_event(actor=actor or student, event="document.gap_answered", object_id=fact.id)
    return written
