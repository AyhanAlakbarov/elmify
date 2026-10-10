from __future__ import annotations

from django.db import transaction

from apps.tenancy.models import Membership

from .audit import record_event
from .drafts import create_draft
from .models import DocumentDraft, RevisionRequest, VerifiedFact
from .schemas import CVContent

_STYLE_STRUCTURE_ROUND_CAP = 2


class RevisionRejected(ValueError):
    pass


def _style_structure_count(document: DocumentDraft) -> int:
    return RevisionRequest.objects.filter(
        document__student=document.student,
        document__kind=document.kind,
        kind=RevisionRequest.Kind.STYLE_STRUCTURE,
    ).count()


def _is_unsuperseded(fact: VerifiedFact) -> bool:
    return not VerifiedFact.objects.filter(supersedes=fact).exists()


@transaction.atomic
def request_revision(
    *,
    document: DocumentDraft,
    kind: str,
    requested_by: Membership,
    note: str,
    superseding_fact: VerifiedFact | None = None,
) -> RevisionRequest:
    if kind == RevisionRequest.Kind.STYLE_STRUCTURE:
        if _style_structure_count(document) >= _STYLE_STRUCTURE_ROUND_CAP:
            raise RevisionRejected("style/structure revision cap reached for this document kind")
    elif kind == RevisionRequest.Kind.FACTUAL_CORRECTION:
        if superseding_fact is None or not _is_unsuperseded(superseding_fact):
            raise RevisionRejected("factual correction requires an unsuperseded superseding_fact")
    else:
        raise RevisionRejected(f"unknown revision kind {kind!r}")
    revision = RevisionRequest.objects.create(
        document=document,
        kind=kind,
        requested_by=requested_by,
        note=note,
        superseding_fact=superseding_fact,
    )
    record_event(actor=requested_by, event="document.revision_requested", object_id=document.id)
    return revision


@transaction.atomic
def counselor_quick_edit(
    *, document: DocumentDraft, content: CVContent, counselor: Membership
) -> DocumentDraft:
    """A counselor hand edit. Deliberately does NOT create a RevisionRequest --
    it is not a revision round (spec: 'a counselor's hand edit is not a
    revision round')."""
    new_version = create_draft(
        student=document.student,
        kind=document.kind,
        content=content,
        facts=[link.fact for link in document.source_fact_links.select_related("fact")],
        programme=document.programme,
        render_variant=document.render_variant,
        actor=counselor,
    )
    # Unconditional per spec ("Approval invalidation"): the prior version --
    # DRAFT or APPROVED -- always moves to SUPERSEDED when a new one is made.
    DocumentDraft.objects.filter(id=document.id).exclude(
        status=DocumentDraft.Status.SUPERSEDED
    ).update(status=DocumentDraft.Status.SUPERSEDED)
    return new_version
