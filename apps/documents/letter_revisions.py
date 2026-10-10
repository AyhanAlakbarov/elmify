from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import Membership

from .audit import record_event
from .models import DocumentDraft, RevisionRequest, VerifiedFact
from .revisions import request_revision


class AdviceRequired(Exception):
    def __init__(self, advice_text: str, rule_id: str) -> None:
        super().__init__(advice_text)
        self.advice_text = advice_text
        self.rule_id = rule_id


@transaction.atomic
def _create_style_revision(
    *, document: DocumentDraft, requested_by: Membership, note: str
) -> RevisionRequest:
    # PF-17: spec decision 5 caps style/structure rounds on CORE_NARRATIVE only
    # ("two style rounds on the core narrative; per-programme letters
    # uncapped"). Plan A's request_revision applies its 2-round cap to any
    # document kind, and CV's own cap test relies on that -- so MOTIVATION_LETTER
    # is exempted here, in the wrapper, rather than by widening (or narrowing)
    # the shared cap check in revisions.py.
    if document.kind == DocumentDraft.Kind.MOTIVATION_LETTER:
        revision = RevisionRequest.objects.create(
            document=document,
            kind=RevisionRequest.Kind.STYLE_STRUCTURE,
            requested_by=requested_by,
            note=note,
        )
        record_event(
            actor=requested_by, event="document.revision_requested", object_id=document.id
        )
        return revision
    return request_revision(
        document=document,
        kind=RevisionRequest.Kind.STYLE_STRUCTURE,
        requested_by=requested_by,
        note=note,
    )


def request_letter_style_revision(
    *,
    document: DocumentDraft,
    requested_by: Membership,
    note: str,
    advice_text: str | None = None,
    rule_id: str = "",
    acknowledge_advice: bool = False,
) -> RevisionRequest:
    if advice_text is not None and not acknowledge_advice:
        raise AdviceRequired(advice_text, rule_id)
    request = _create_style_revision(document=document, requested_by=requested_by, note=note)
    request.advice_shown = advice_text or ""
    request.save(update_fields=["advice_shown"])
    return request


def add_student_stated_fact(
    *, student: Membership, category: str, payload: dict[str, object], source_ref: str
) -> VerifiedFact:
    """Decision 8: a fact the student states is verified by the act of
    stating it. No counselor confirmation step -- confirmed_by/confirmed_at
    are set here, immediately, unlike the CV engine's consultant-collected
    facts which also confirm on collection (same rule, same reason)."""
    now = timezone.now()
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref=source_ref,
        confirmed_by=student,
        confirmed_at=now,
        created_by=student,
    )


@transaction.atomic
def request_letter_factual_correction(
    *,
    document: DocumentDraft,
    student: Membership,
    category: str,
    payload: dict[str, object],
    source_ref: str,
) -> RevisionRequest:
    fact = add_student_stated_fact(
        student=student, category=category, payload=payload, source_ref=source_ref
    )
    return request_revision(
        document=document,
        kind=RevisionRequest.Kind.FACTUAL_CORRECTION,
        requested_by=student,
        note=f"student-stated fact added: {source_ref}",
        superseding_fact=fact,
    )
