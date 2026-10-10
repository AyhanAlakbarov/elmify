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
    candidate. The return value counts rows actually changed.
    """
    ids = list(fact_ids)
    candidates = list(VerifiedFact.objects.select_for_update().filter(student=student, id__in=ids))
    if len(candidates) != len(set(ids)):
        raise FactNotFound("one or more fact ids are not in this student's ledger")
    superseded = set(
        VerifiedFact.objects.filter(supersedes_id__in=ids).values_list("supersedes_id", flat=True)
    )
    now = timezone.now()
    confirmed = 0
    for fact in candidates:
        if fact.confirmed_by_id is not None or fact.id in superseded:
            continue
        fact.confirmed_by = actor
        fact.confirmed_at = now
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
        record_event(actor=actor, event="fact.confirmed", object_id=fact.id)
        confirmed += 1
    return confirmed
