"""Dossier assembly: gathers a student's cross-app audit trail for one tenant.

Shared by exports.py (zips the dossier alongside a manifest) and any future
counselor-facing dossier view.
"""

from __future__ import annotations

from uuid import UUID

from django.template.loader import render_to_string

from apps.concierge.models import ApplicationFeeLedgerEntry, ManualOperation, Receipt, RoadmapItem
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership


def resolve_student(tenant_id: UUID, student_id: UUID) -> Membership:
    """Look up the student within their own tenant, or raise ValueError.

    Callers pass an untrusted tenant_id/student_id pair (e.g. from a request);
    this is the guard against fetching one tenant's data using another
    tenant's id.
    """
    with tenant_scope(tenant_id):
        try:
            return Membership.objects.get(id=student_id, tenant_id=tenant_id)
        except Membership.DoesNotExist as error:
            raise ValueError("student does not belong to tenant") from error


def build_dossier(tenant_id: UUID, student_id: UUID) -> str:
    student = resolve_student(tenant_id, student_id)
    with tenant_scope(tenant_id):
        context = {
            "student": student,
            "events": AuditEvent.objects.filter(object_id=student_id),
            "roadmap_items": RoadmapItem.objects.filter(student_id=student_id),
            "manual_operations": ManualOperation.objects.filter(
                roadmap_item__student_id=student_id
            ),
            "ledger_entries": ApplicationFeeLedgerEntry.objects.filter(student_id=student_id),
            "receipts": Receipt.objects.filter(ledger_entry__student_id=student_id),
        }
        return render_to_string("audit/dossier.html", context)
