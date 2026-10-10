from collections.abc import Iterable
from typing import TypeVar
from uuid import uuid4
from zoneinfo import available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.base import ModelBase

from .context import current_tenant_id


def validate_timezone_name(value: str) -> None:
    """Refuse anything ZoneInfo cannot resolve.

    A trust boundary, not tidiness: the reminder sweep reads this field to
    decide whether a student is asleep, and an unresolvable name would raise
    inside a loop that is meant to serve every student in the tenant.
    """
    if value and value not in available_timezones():
        raise ValidationError(f"{value} is not an IANA time zone name")


class Agency(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    name = models.CharField(max_length=200)
    brand_logo_url = models.URLField(max_length=2048, blank=True)
    brand_primary_color = models.CharField(
        max_length=7,
        default="#0254a5",  # platform default; passes validate_brand_palette
        validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$")],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(brand_primary_color__regex=r"^#[0-9A-Fa-f]{6}$"),
                name="agency_valid_brand_color",
            )
        ]


class TenantDomain(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="domains")
    host = models.CharField(max_length=253, unique=True)
    verified_at = models.DateTimeField(null=True, blank=True)


_TenantModel = TypeVar("_TenantModel", bound=models.Model)


class TenantManager(models.Manager[_TenantModel]):
    def get_queryset(self) -> models.QuerySet[_TenantModel]:
        return super().get_queryset().filter(tenant_id=current_tenant_id())


class TenantScopedModel(models.Model):
    tenant = models.ForeignKey(Agency, on_delete=models.CASCADE)
    objects = TenantManager()

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        tenant_id = current_tenant_id()
        if self.tenant_id is None:
            self.tenant_id = tenant_id
        elif self.tenant_id != tenant_id:
            raise ValueError("tenant mismatch")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class Membership(TenantScopedModel):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        COUNSELOR = "COUNSELOR", "Counselor"
        STUDENT = "STUDENT", "Student"
        PLATFORM_ADMIN = "PLATFORM_ADMIN", "Platform admin"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices)
    active = models.BooleanField(default=True)
    #: The address the student applies with: the connected mailbox's address,
    #: or one the student declared and confirmed. This is the address a CV
    #: carries -- NEVER user.email, which is signup and login only. There is
    #: deliberately no fallback between them: publishing the login address to
    #: a funder sends the reply where nothing is watching. Empty means no
    #: address is confirmed yet, and generation refuses to run.
    application_email = models.EmailField(blank=True)
    #: The student's OWN institutional address, when they have one. Printed on
    #: a generated CV in preference to the mailbox above (see
    #: documents.generation.contact_email) and used for nothing else: no
    #: portal is registered with it, nothing is scraped from it, and no reply
    #: to it is watched. An academic CV mailed to a supervisor carries an
    #: address that is itself a credential; a tracked portal application still
    #: carries the platform's. Blank means the student has not given one.
    academic_email = models.EmailField(blank=True)
    #: IANA name, e.g. "Asia/Baku". Blank when unknown, which the reminder
    #: ladder reads as "no quiet hours" and sends on time -- degrading the
    #: other way, holding reminders until a zone is known, drops them silently.
    timezone = models.CharField(max_length=64, blank=True, validators=[validate_timezone_name])
    #: The window in which the ladder will not send. Both null means none.
    #: A window normally crosses midnight (22:00-07:00), which is why the
    #: comparison in reminders.in_quiet_hours is not a simple between.
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)

    @property
    def display_name(self) -> str:
        """Human-readable name for dashboards — never the raw membership UUID.

        Callers rendering lists should select_related("...__user") to avoid
        an extra query per row.
        """
        return self.user.get_full_name() or self.user.get_username()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "user"), name="membership_tenant_user_uniq"),
            models.UniqueConstraint(fields=("tenant", "id"), name="membership_tenant_id_id_uniq"),
        ]


class CounselorAssignment(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    counselor = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="assigned_students"
    )
    student = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="assigned_counselors"
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="assignment_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student"),
                condition=models.Q(active=True),
                name="assignment_one_active_counselor_per_student",
            ),
        ]


class AgencyDataUseAgreementVersion(TenantScopedModel):
    class ReviewState(models.TextChoices):
        NOT_REVIEWED = "NOT_REVIEWED", "Not reviewed"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    agreement_id = models.UUIDField()
    version = models.PositiveIntegerField()
    agreement_reference = models.CharField(max_length=200)
    permitted_purposes = models.JSONField()
    eligible_categories = models.JSONField()
    lawful_basis_review_state = models.CharField(max_length=20, choices=ReviewState.choices)
    effective_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    created_by = models.ForeignKey(Membership, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("tenant", "agreement_id", "-version"),
                name="agreement_tenant_version_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="data_use_agreement_tenant_id_uniq"
            ),
            models.UniqueConstraint(
                fields=("tenant", "agreement_id", "version"),
                name="data_use_agreement_tenant_version_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="data_use_agreement_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    lawful_basis_review_state__in=(
                        "NOT_REVIEWED",
                        "APPROVED",
                        "REJECTED",
                    )
                ),
                name="data_use_agreement_review_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(revoked_at__isnull=True)
                | models.Q(revoked_at__gte=models.F("effective_at")),
                name="data_use_agreement_chronology",
            ),
        ]


class SupportGrant(TenantScopedModel):
    """Time-boxed platform-admin access to a tenant's data for support work."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    administrator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="supportgrant_tenant_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="supportgrant_chronology",
            ),
        ]
