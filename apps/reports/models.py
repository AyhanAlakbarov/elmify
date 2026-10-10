from uuid import uuid4

from django.db import models

from apps.funding.models import PackVersion
from apps.tenancy.models import Membership, TenantScopedModel


class ConsultationPayment(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, default="PENDING")
    credited_engagement_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="payment_tenant_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(status__in=("PENDING", "PAID", "FAILED", "REFUNDED")),
                name="payment_status_valid",
            ),
        ]


class ConsultationReport(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    pack_version = models.ForeignKey(PackVersion, on_delete=models.PROTECT)
    object_key = models.CharField(max_length=500)
    s3_version_id = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    content_type = models.CharField(max_length=100, default="text/html")
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="report_tenant_id_uniq")
        ]
