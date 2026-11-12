"""The student's single click: a candidate fact becomes a confirmed one.

Every fact writer in this app records ``confirmed_by=None`` on purpose -- an
applicant-written CV, a model's reading of it, and a profile bridge are all
claims, not verified facts -- and ``generatable_facts`` shows generation only
the confirmed ones. This module is the only transition between the two, so it
is where the authorship record is actually made.

Engine-level, not CV-level: the motivation-letter engine confirms from the
same ledger, which is why this is a module of its own rather than a function
inside a CV one.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import Membership

from .audit import record_event
from .models import VerifiedFact
from .verification import nameless_identity


class FactNotFound(LookupError):
    """An id does not name a fact in this student's ledger.

    Callers must render this as 404, never 403: a 403 would confirm the fact
    exists, which is the convention storage.download_document already keeps.
    """


@transaction.atomic
def confirm_facts(*, student: Membership, fact_ids: Iterable[UUID], actor: Membership) -> int:
    """Stamp ``confirmed_by``/``confirmed_at`` on this student's candidates.

    Ids are resolved through ``student=student``, never by id alone, so a fact
    belonging to somebody else is indistinguishable from one that does not
    exist.

    All or nothing on *lookup*: an id that is not this student's raises before
    anything is written, so one bad id in a batch cannot half-confirm the rest.
    Already-confirmed and superseded rows are skipped rather than refused --
    a resubmitted list is a retry, and a superseded row is no longer a
    candidate; so is a document's whole row already placed, or one an unconfirmed
    CV row may be (fact_writer), and a nameless IDENTITY
    (verification.nameless_identity), which is never a candidate at all.
    The return value counts rows actually changed.
    """
    ids = list(fact_ids)
    candidates = list(VerifiedFact.objects.select_for_update().filter(student=student, id__in=ids))
    if len(candidates) != len(set(ids)):
        raise FactNotFound("one or more fact ids are not in this student's ledger")
    superseded = set(
        VerifiedFact.objects.filter(supersedes_id__in=ids).values_list("supersedes_id", flat=True)
    )
    # A diploma's or certificate's whole row whose document a confirmed row already
    # carries: confirming it would be a second degree for one document. Only document
    # rows qualify, so the CV and letter engines' confirmations are unchanged.
    # And one an unconfirmed CV degree may be: confirming both would be two degrees.
    from .degree_match import held_duplicates  # degree_match imports this module
    from .fact_writer import held_whole_rows, placed_whole_rows  # fact_writer imports this
    from .verification import disowned_refs, retired_refs

    excluded_refs = disowned_refs(student) | retired_refs(student)
    superseded |= placed_whole_rows(student, candidates) | held_whole_rows(student, candidates)
    # A CV degree that may be one already held waits for "Different degree" (plan 3b Task 7).
    superseded |= held_duplicates(candidates)
    now = timezone.now()
    confirmed = 0
    identity_confirmed = False
    profile_sync_needed = False
    for fact in candidates:
        if (
            fact.confirmed_by_id is not None
            or fact.id in superseded
            or nameless_identity(fact)
            or fact.source_ref in excluded_refs
        ):
            continue
        fact.confirmed_by = actor
        fact.confirmed_at = now
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
        record_event(actor=actor, event="fact.confirmed", object_id=fact.id)
        confirmed += 1
        if fact.category == VerifiedFact.Category.IDENTITY:
            identity_confirmed = True
        elif fact.category in (
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.LANGUAGE,
            VerifiedFact.Category.EXPERIENCE,
            VerifiedFact.Category.RESEARCH,
        ):
            profile_sync_needed = True
    if identity_confirmed:
        from .cv_jobs import resume_waiting_cvs

        resume_waiting_cvs(student)
    if profile_sync_needed:
        from .profile_bridge import sync_facts_to_profile

        sync_facts_to_profile(student)
    return confirmed
