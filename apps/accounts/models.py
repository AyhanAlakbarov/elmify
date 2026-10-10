from uuid import uuid4

from django.db import models

from apps.tenancy.models import Membership, TenantScopedModel


class StudentProfileVersion(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    schema_version = models.PositiveSmallIntegerField(default=0, db_default=0)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="profile_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student", "version"),
                name="profile_tenant_student_version_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0), name="profile_version_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__in=(0, 1, 2, 3)),
                name="profile_schema_version_valid",
            ),
        ]
