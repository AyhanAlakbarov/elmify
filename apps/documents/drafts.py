from __future__ import annotations

from collections.abc import Iterable

from django.db import models, transaction

from apps.funding.models import Program
from apps.tenancy.models import Membership

from .audit import record_event
from .models import DocumentDraft, DocumentDraftFact, VerifiedFact
from .schemas import CVContent


def attach_source_facts(*, document: DocumentDraft, facts: Iterable[VerifiedFact]) -> None:
    """Link facts to a draft through the tenant-scoped through model.

    Never use ``document.source_facts.add(...)``: ``add()`` bulk-creates the
    through rows, which skips ``TenantScopedModel.save()``'s tenant guard.
    """
    for fact in facts:
        DocumentDraftFact.objects.get_or_create(document=document, fact=fact)


@transaction.atomic
def create_draft(
    *,
    student: Membership,
    kind: str,
    content: CVContent,
    facts: Iterable[VerifiedFact] = (),
    programme: Program | None = None,
    render_variant: str = "",
    actor: Membership | None = None,
) -> DocumentDraft:
    """Append a new draft version. Same locking shape as create_profile_version.

    The lock is taken on the student row, not on the previous draft: two
    concurrent generations for one student must serialise, and locking the
    previous draft would let them both read the same max(version).
    """
    locked_student = Membership.objects.select_for_update().get(id=student.id)
    latest = (
        DocumentDraft.objects.filter(student=locked_student, kind=kind).aggregate(
            value=models.Max("version")
        )["value"]
        or 0
    )
    draft = DocumentDraft.objects.create(
        student=locked_student,
        kind=kind,
        version=latest + 1,
        content=content.model_dump(mode="json"),
        programme=programme,
        render_variant=render_variant,
        status=DocumentDraft.Status.DRAFT,
    )
    attach_source_facts(document=draft, facts=facts)
    record_event(actor=actor or student, event="document.generated", object_id=draft.id)
    return draft
