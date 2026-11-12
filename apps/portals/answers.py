"""What students type where the co-pilot was unsure (owner, 2026-10-09).

The value is the student's own and stays in their tenant (FORCE RLS), erased
with them. It is never sent to a model and never written to a map: a map learns
only WHICH field a box asks for, from several students agreeing.

Only a hint the packet marked `unsure` is a guess (preflight #1). A box the map
is sure of -- a `no_fact` hint, or an entry we typed -- records what the student
typed, but never as a confirmation or a correction, so no number of students
can remap it.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .learn import _store_map
from .models import Application, ApplicationStep, FieldMap, PortalAnswer, PortalForm
from .profile import field_class, narrative_values, verified_values

CONFIRMATIONS_TO_BE_SURE = 3
CORRECTIONS_TO_REMAP = 2
MAX_ANSWERS = 100
MAX_VALUE = 10_000

#: A selector naming a password box. The extension never reads one (content
#: typedAnswers); a batch carrying one is refused whole, so no part of what a
#: misbehaving client sent alongside it is kept. "passport" does not match.
_PASSWORD = re.compile(r"pass(word|wd)|pwd", re.IGNORECASE)

_LOCKED_IDENTITY_FIELDS = frozenset(
    {
        "identity.given_names",
        "identity.surname",
        "identity.full_name",
        "identity.date_of_birth",
        "id_document.number",
    }
)


def _identity_value_matches(field: str, typed_value: str, expected: str) -> bool:
    from apps.documents import mrz
    from apps.documents.id_reading import owner_matches_full_name

    if field == "identity.given_names":
        return mrz.same_given_name(typed_value, expected)
    if field == "identity.surname":
        return mrz.same_name_token(typed_value, expected)
    if field == "identity.full_name":
        return owner_matches_full_name(typed_value, (expected,))
    return typed_value.strip().casefold() == expected.strip().casefold()

logger = logging.getLogger(__name__)


class AnswerRefused(Exception):
    pass


class Answer(BaseModel):
    """One typed answer, as the extension sends it. The guessed field is not on
    the wire: the server reads it from its own PACKET row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: str = Field(min_length=1, max_length=300)
    kind: Literal["hint", "changed"]
    value: str = Field(max_length=MAX_VALUE)


def _named(
    application: Application,
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """The latest PACKET's hints (selector -> (field, reason)) and typed entries
    (selector -> field): the only boxes an answer may come from. The PACKET row
    is the server's own; the extension cannot write one (ext_api._EVENT_KINDS)."""
    packet = (
        ApplicationStep.objects.filter(
            application=application, kind=ApplicationStep.Kind.PACKET
        )
        .order_by("-sequence")
        .first()
    )
    detail = packet.detail if packet is not None and isinstance(packet.detail, dict) else {}
    hints = {
        str(h.get("selector")): (str(h.get("profile_field", "")), str(h.get("reason", "")))
        for h in detail.get("hints", [])
        if isinstance(h, dict)
    }
    values = {
        str(v.get("selector")): str(v.get("profile_field", ""))
        for v in detail.get("values", [])
        if isinstance(v, dict)
    }
    return hints, values


def _match(facts: dict[str, str], guessed: str, value: str) -> str:
    """The fact this typed value equals: the guessed field first, then one of
    the same class (another degree's end date), then any. "" for none."""
    typed = value.strip().casefold()
    if not typed:
        return ""
    equal = [key for key, fact in facts.items() if fact.strip().casefold() == typed]
    if guessed in equal:
        return guessed
    # "education.2.end_date" before the unindexed "education.end_date": the
    # indexed key names the degree, the unindexed one is only the first.
    equal.sort(key=lambda key: field_class(key) == key)
    same_class = [key for key in equal if field_class(key) == field_class(guessed)]
    return (same_class or equal or [""])[0]


def record_answers(application: Application, answers: list[Answer]) -> list[PortalAnswer]:
    """Store what the student typed into boxes the latest PACKET named.

    An answer for any other box is skipped, not stored: the extension may hold
    a packet older than the latest PACKET row, and one stale box must not lose
    the rest of the student's answers. Too many answers, or any answer naming a
    password box, refuses the whole batch and writes nothing. The caller holds
    tenant_transaction(application.tenant_id): the table is FORCE RLS.
    """
    if len(answers) > MAX_ANSWERS:
        raise AnswerRefused("too_many_answers")
    if any(_PASSWORD.search(answer.selector) for answer in answers):
        raise AnswerRefused("password")
    hints, values = _named(application)
    named = [
        answer
        for answer in answers
        if answer.selector in (hints if answer.kind == "hint" else values)
    ]
    if len(named) < len(answers):
        # Counts only: a selector is the portal's, a value the student's.
        logger.info(
            "answers: skipped %d of %d not named by the latest packet (application %s)",
            len(answers) - len(named),
            len(answers),
            application.id,
        )
    if application.portal_form is None:
        raise AnswerRefused("no_portal")  # unreachable: a PACKET needs a portal form
    narratives = narrative_values(
        application.student,
        program_id=application.program_id,
        application_id=application.id,
    )
    facts = {**narratives, **verified_values(application.student)}
    saved: list[PortalAnswer] = []
    for answer in named:
        if answer.kind == "hint":
            field, reason = hints[answer.selector]
        else:
            field, reason = values[answer.selector], ""
        matched = _match(facts, field, answer.value)
        if answer.kind == "changed":
            outcome = PortalAnswer.Outcome.CHANGED_OUR_VALUE
        elif reason != "unsure":
            outcome = PortalAnswer.Outcome.NEW_ANSWER  # a sure box is never a guess
        elif matched and matched == field:
            outcome = PortalAnswer.Outcome.CONFIRMED_GUESS
        elif matched:
            outcome = PortalAnswer.Outcome.CORRECTED_GUESS
        else:
            outcome = PortalAnswer.Outcome.NEW_ANSWER
        saved.append(
            PortalAnswer.objects.create(
                tenant=application.tenant,
                student=application.student,
                portal_form=application.portal_form,
                selector=answer.selector,
                guessed_field=field,
                matched_field=matched,
                value=answer.value,
                outcome=outcome,
            )
        )
        if outcome == PortalAnswer.Outcome.CHANGED_OUR_VALUE and field in _LOCKED_IDENTITY_FIELDS:
            expected = facts.get(field, "").strip()
            if expected and not _identity_value_matches(field, answer.value, expected):
                from apps.documents.id_reading import raise_identity_mismatch_alert
                from apps.funding.models import AuditEvent

                AuditEvent.objects.create(
                    tenant_id=application.tenant_id,
                    actor=application.student,
                    actor_kind=AuditEvent.ActorKind.HUMAN,
                    event="portal.identity_mismatch_typed",
                    object_id=application.id,
                )
                student_label = (
                    application.student.user.get_full_name() or application.student.user.email
                )
                raise_identity_mismatch_alert(
                    application.student,
                    stage="PORTAL_EXCEPTION",
                    application=application,
                    message=(
                        f"Verified identity field ({field}) was overwritten on portal form "
                        f"for {student_label}."
                    ),
                )
    return saved


def learn_from_answers(portal_form: PortalForm, tenant_id: UUID) -> FieldMap | None:
    """A new tenant map version when students' answers agree, else None.

    Only this tenant's own map changes here, and only its unsure entries: a
    sure entry is never remapped by answers. A shared or bench-verified map
    changes only on the bench (plan 6). The bench never reads these rows: they
    are one tenant's students' typed values, and reading them across tenants is
    the person's-data crossing CLAUDE.md rules out.
    """
    current = FieldMap.current_for(portal_form, tenant_id)
    if current is None or current.learned_by_tenant_id != tenant_id:
        return None
    # RLS is the tenant too; the filter says so where a reader can see it.
    answers = PortalAnswer.objects.filter(portal_form=portal_form, tenant_id=tenant_id)
    entries: list[dict[str, object]] = []
    changed = False
    for entry in current.entries:
        action = entry.get("action")
        field = str(entry.get("profile_field", ""))
        if entry.get("sure") is not False or not isinstance(action, dict):
            entries.append(entry)
            continue
        here = answers.filter(selector=str(action.get("selector", "")), guessed_field=field)
        confirmed = (
            here.filter(outcome=PortalAnswer.Outcome.CONFIRMED_GUESS)
            .values("student")
            .distinct()
            .count()
        )
        corrections = Counter(
            matched
            for matched, _student in here.filter(outcome=PortalAnswer.Outcome.CORRECTED_GUESS)
            .values_list("matched_field", "student")
            .distinct()
        )
        ranked = corrections.most_common(2)
        best, votes = ranked[0] if ranked else ("", 0)
        contested = len(ranked) == 2 and ranked[1][1] == votes  # a tie remaps nothing
        if votes >= CORRECTIONS_TO_REMAP and not contested and best != field:
            entry = {**entry, "profile_field": best, "sure": True}
            changed = True
        elif confirmed >= CONFIRMATIONS_TO_BE_SURE:
            entry = {**entry, "sure": True}
            changed = True
        entries.append(entry)
    if not changed:
        return None
    return _store_map(
        portal_form, entries, slots=list(current.slots or []), learned_by_tenant_id=tenant_id
    )
