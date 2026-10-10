"""Where an application's outcome comes from, and who may overwrite it (spec §4).

Three writers. Trusted mail, through one Jev reading that cleared its bars
(record_from_mail, called by mailbox/actions.py behind the trust gate); an
authenticated offer letter's stated refusal, when the student accepts the offer
(record_refusal_from_offer); and a person (correct_outcome). A person's entry
is never overwritten by a later automatic reading: the outcome is the one fact
this platform has no other record of (CLAUDE.md, "Derived data"), and a misread
one tells a family the wrong thing.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.funding.models import AuditEvent
from apps.tenancy.models import Membership

from .models import Application

if TYPE_CHECKING:
    from apps.mailbox.decision_reader import DecisionReading
    from apps.mailbox.models import MailSignal


def _same_tenant(actor: Membership, application: Application) -> None:
    if actor.tenant_id != application.tenant_id:
        raise PermissionError("the actor belongs to another tenant")


def _write(
    application: Application,
    outcome: str,
    source: str,
    evidence: MailSignal | None,
    *,
    actor: Membership | None,
    at: datetime,
    extra: tuple[str, ...] = (),
) -> None:
    """The one outcome write and its audit row; the gates stay with each writer.
    No actor is the agent; an actor is the person whose press caused it."""
    application.outcome, application.outcome_source = outcome, source
    application.outcome_recorded_at, application.outcome_evidence = at, evidence
    application.save(
        update_fields=[
            *extra, "outcome", "outcome_recorded_at", "outcome_source", "outcome_evidence"
        ]
    )
    AuditEvent.objects.create(
        tenant_id=application.tenant_id,
        actor=actor,
        actor_kind=AuditEvent.ActorKind.AGENT if actor is None else AuditEvent.ActorKind.HUMAN,
        event="application.outcome_recorded",
        object_id=application.id,
    )


def is_funding_application(application: Application) -> bool:
    """A scholarship with its own application, rather than a study place."""
    candidate = application.candidate
    return candidate is not None and candidate.opportunity_id is not None


def record_from_mail(
    application: Application, signal: MailSignal, reading: DecisionReading
) -> list[str]:
    """Trusted mail, read by Jev. Returns the fields changed.

    A decision is available only when the decision question cleared its bar. The
    outcome is recorded only when it cleared its gate, the bars have been
    measured, the provider authenticated the sender (signal.sender_authenticated,
    never a tag alone), and no person recorded one; it is audited as the agent.
    A scholarship card's outcome is the funding answer, since its own name is
    asked as the funding.
    """
    if reading.is_decision is not True:
        return []
    # Fix round 1, item 3: the trust gate lets a tagged mail mark the decision
    # available, but only the provider's delivery verdict may write the outcome.
    authenticated = signal.sender_authenticated
    person = application.outcome_source == Application.OutcomeSource.PERSON
    corrected_after = (
        person
        and application.outcome_recorded_at is not None
        and signal.received_at <= application.outcome_recorded_at
    )
    now = timezone.now()
    changed: list[str] = []
    if application.decision_available_at is None and not corrected_after:
        application.decision_available_at = now
        changed.append("decision_available_at")
    own = reading.funding_outcome if is_funding_application(application) else reading.outcome
    if own and reading.measured and not person and authenticated:
        _write(
            application, own, Application.OutcomeSource.MAIL, signal,
            actor=None, at=now, extra=tuple(changed),
        )
        return [*changed, "outcome", "outcome_recorded_at", "outcome_source", "outcome_evidence"]
    if changed:
        application.save(update_fields=changed)
    return changed


def record_refusal_from_offer(
    application: Application, signal: MailSignal, *, actor: Membership
) -> bool:
    """An accepted offer's letter said the programme applied for was refused.

    The third writer, and the same gate as record_from_mail: only the provider's
    delivery verdict (signal.sender_authenticated) on a reading whose bars were
    measured may write an outcome, and never over a person's entry (review
    ruling, Task 9). Accept is a press about the other programme, not a
    confirmation of this refusal, so an unmeasured reading leaves the card
    asking (final review I1). The press only decides
    when; the statement is the mail's, so the source is MAIL with the signal as
    evidence. Audited as HUMAN with the person who pressed: the write happens
    only because they did, and an AGENT row with no actor would hide that.
    Returns whether it wrote.
    """
    if (
        signal.outcome != Application.Outcome.REJECTED
        or not signal.sender_authenticated
        or (signal.decision_reading or {}).get("measured") is not True
        or application.outcome_source == Application.OutcomeSource.PERSON
        or application.outcome == Application.Outcome.REJECTED
    ):
        return False
    _same_tenant(actor, application)
    _write(
        application, Application.Outcome.REJECTED, Application.OutcomeSource.MAIL, signal,
        actor=actor, at=timezone.now(),
    )
    return True


def correct_outcome(application: Application, outcome: str, *, actor: Membership) -> None:
    """A person records or corrects the outcome. Audited with the person as actor.

    The caller authorizes: the student themself or their assigned counsellor.
    This refuses only what no caller may do, an actor from another tenant.

    Blank means "no decision yet" and also clears decision_available_at, so a
    false "Decision available" can be taken back.
    """
    _same_tenant(actor, application)
    if outcome not in ("", *Application.Outcome.values):
        raise ValueError("unknown outcome")
    if not outcome:
        application.decision_available_at = None
    _write(
        application, outcome, Application.OutcomeSource.PERSON, None,
        actor=actor, at=timezone.now(), extra=() if outcome else ("decision_available_at",),
    )
