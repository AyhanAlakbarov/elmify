from __future__ import annotations

from hashlib import sha256

from django.db import transaction
from django.template.loader import render_to_string

from apps.concierge.models import ServiceEngagement
from apps.funding.models import PackVersion
from apps.research.snapshot import ObjectStore
from apps.research.storage import S3ObjectStore

from .models import ConsultationPayment, ConsultationReport


class ReportBlocked(RuntimeError):
    pass


def generate_report(
    payment: ConsultationPayment, pack: PackVersion, *, store: ObjectStore | None = None
) -> ConsultationReport:
    """Render and store the paid report. **Worker-side only.**

    This writes to S3, and WebTaskRole is deliberately denied s3:PutObject
    (infra/template.yaml; asserted by tests/infra/test_template.py::
    test_web_task_role_can_enqueue_but_not_write_evidence). Calling this from a
    request handler will fail with AccessDenied in production -- enqueue it for
    the worker instead. Do not widen the web role to "fix" that.
    """
    if payment.status != "PAID":
        raise ReportBlocked("consultation payment must be settled")
    if pack.published_at is None:
        raise ReportBlocked("pack must be published")
    if payment.student_id != pack.run.profile_version.student_id:
        raise ReportBlocked("payment does not belong to this pack's student")
    content = render_to_string("reports/consultation_report.html", {"pack": pack}).encode()
    digest = sha256(content).hexdigest()
    key = f"tenants/{pack.tenant_id}/reports/{pack.id}/{digest}.html"
    version_id = (store or S3ObjectStore()).put(key, content)
    return ConsultationReport.objects.create(
        pack_version=pack, object_key=key, s3_version_id=version_id, sha256=digest
    )


@transaction.atomic
def apply_consultation_credit(payment: ConsultationPayment, engagement: ServiceEngagement) -> None:
    # Lock the payment row first: without it, two concurrent calls both read a
    # NULL credited_engagement_id under READ COMMITTED and both spend the credit.
    locked = ConsultationPayment.objects.select_for_update().get(pk=payment.pk)
    if locked.credited_engagement_id is not None:
        raise ReportBlocked("consultation credit already used")
    credit = min(locked.amount, engagement.platform_fee)
    engagement.credit_amount = credit
    locked.credited_engagement_id = engagement.id
    engagement.save(update_fields=["credit_amount"])
    locked.save(update_fields=["credited_engagement_id"])
    payment.credited_engagement_id = engagement.id
