"""Counsellor notes computed at read time, never stored (plan decision 24).

They quote the student's own name and record, so they exist only on the
screen of the counsellor looking at them. Nothing here corrects anything:
generation never stamps a name (generation.py), because a wrong name must be
caught by a person (spec §9) -- these notes are how the person is told.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from uuid import UUID

from pydantic import ValidationError

from apps.tenancy.models import Membership

from .hygiene import normalize_text
from .models import DocumentDraft, VerifiedFact
from .schemas import CVContent
from .verification import unsuperseded_facts


def _tokens(name: str) -> frozenset[str]:
    return frozenset(normalize_text(name).casefold().replace("-", " ").split())


def name_notes(content: CVContent, identities: Iterable[VerifiedFact]) -> list[str]:
    """Spec §9: the CV prints the passport's English spelling, and the engine
    never re-spells it. A full name differing from any current IDENTITY fact
    -- the passport's once document fact-reading lands, the confirmed details
    until then -- and a surname or given name the CV's name lacks are notes.
    Word order and case are not differences."""
    printed = content.personal_information.full_name
    printed_tokens = _tokens(printed)
    notes: list[str] = []
    for fact in identities:
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        source = (
            "the passport"
            if fact.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
            else "the student's confirmed details"
        )
        other = str(payload.get("full_name") or "")
        if other and _tokens(other) != printed_tokens:
            notes.append(
                f"The CV prints the name “{printed}”, but {source} gives “{other}”. "
                "Check it against the passport's English spelling."
            )
        for key, label in (
            ("surname", "surname"),
            ("given_name", "given name"),
            ("given_names", "given name"),
        ):
            part = str(payload.get(key) or "")
            if part and not _tokens(part) <= printed_tokens:
                notes.append(
                    f"The CV name “{printed}” does not contain the {label} “{part}” "
                    "the student gave as in their passport."
                )
    return list(dict.fromkeys(notes))


#: Spec §7.3: dates, titles and grades. Only indexed education fields, which
#: name one degree unambiguously (plan decision 25).
_FORM_FIELD = re.compile(
    r"^education\.(\d+)\.(start_date|end_date|degree_as_awarded|degree_english|grade_native)$"
)
_LABEL = {
    "start_date": "start date", "end_date": "end date", "degree_as_awarded": "title",
    "degree_english": "English title", "grade_native": "grade",
}


def _shown(key: str, value: object) -> str:
    """Dates compare and print by month: the CV prints months, the form may
    carry a day nobody asked about."""
    if value is None:
        return ""
    if key.endswith("_date"):
        return (value.isoformat() if isinstance(value, date) else str(value))[:7]
    return " ".join(normalize_text(str(value)).split())


def consistency_notes(
    content: CVContent,
    *,
    title: str,
    packet_values: Sequence[dict[str, object]],
    typed_over: Mapping[str, str],
) -> list[str]:
    """Selection is allowed, contradiction is not (spec §7.3). Every indexed
    education value the form carries -- ours, or the student's own typed over
    ours -- is compared with the same degree on the CV."""
    degrees = sorted(
        content.education,
        key=lambda e: (e.start_date.isoformat() if e.start_date else "",
                       e.end_date.isoformat() if e.end_date else ""),
    )
    notes: list[str] = []
    for entry in packet_values:
        match = _FORM_FIELD.match(str(entry.get("profile_field") or ""))
        if match is None:
            continue
        number, key = int(match.group(1)), match.group(2)
        form = typed_over.get(str(entry.get("selector") or ""), entry.get("value"))
        if form in (None, "") or not 1 <= number <= len(degrees):
            continue
        ours = getattr(degrees[number - 1], key)
        if _shown(key, form).casefold() != _shown(key, ours).casefold():
            notes.append(
                f"{title}: the application form gives degree {number} {_LABEL[key]} "
                f"“{_shown(key, form)}”, the CV says “{_shown(key, ours) or 'nothing'}”."
            )
    return notes


def counsellor_notes(
    student: Membership, drafts: Sequence[DocumentDraft]
) -> dict[UUID, list[str]]:
    """Name and form notes per CV draft, for the counsellor's view only.

    A draft whose content no longer validates (an erased student's, redacted
    to {}) gets no notes and raises nothing.
    """
    from apps.portals.models import Application, ApplicationStep, PortalAnswer

    from .verification import disowned_refs, retired_refs

    identities = list(
        unsuperseded_facts(student)
        .filter(category=VerifiedFact.Category.IDENTITY, confirmed_by__isnull=False)
        .exclude(source_ref__in=disowned_refs(student) | retired_refs(student))
    )
    contents: dict[UUID, CVContent] = {}
    notes: dict[UUID, list[str]] = {}
    for draft in drafts:
        notes[draft.id] = []
        try:
            contents[draft.id] = CVContent.model_validate(draft.content)
        except ValidationError:
            continue
        notes[draft.id].extend(name_notes(contents[draft.id], identities))
    if not contents:
        return notes
    applications = list(
        Application.objects.filter(student=student).select_related("candidate", "portal_form")
    )
    steps_by_app: dict[UUID, ApplicationStep] = {}
    for packet_step in ApplicationStep.objects.filter(
        application__in=applications, kind="PACKET"
    ).order_by("application_id", "-sequence"):
        steps_by_app.setdefault(packet_step.application_id, packet_step)
    form_ids = {a.portal_form_id for a in applications if a.portal_form_id is not None}
    answers_by_form: dict[UUID, dict[str, str]] = {}
    if form_ids:
        for answer in PortalAnswer.objects.filter(
            student=student,
            portal_form_id__in=form_ids,
            outcome=PortalAnswer.Outcome.CHANGED_OUR_VALUE,
        ).order_by("created_at"):
            answers_by_form.setdefault(answer.portal_form_id, {})[answer.selector] = answer.value
    for application in applications:
        step = steps_by_app.get(application.id)
        if step is None or not isinstance(step.detail, dict):
            continue
        typed_over = (
            answers_by_form.get(application.portal_form_id, {})
            if application.portal_form_id is not None
            else {}
        )
        values = [v for v in step.detail.get("values", []) if isinstance(v, dict)]
        for document in step.detail.get("documents", []):
            draft_id = document.get("draft_id") if isinstance(document, dict) else None
            if not draft_id:
                continue
            try:
                parsed_id = UUID(str(draft_id))
            except ValueError:
                continue
            content = contents.get(parsed_id)
            if content is not None:
                notes[parsed_id].extend(consistency_notes(
                    content, title=application.title, packet_values=values,
                    typed_over=typed_over,
                ))
    return notes
