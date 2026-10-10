"""Consent and privacy records (spec 2026-10-03-consent-and-privacy-notice-design.md).

`LegalDocument` is platform data, not a tenant's: one Terms and two Privacy
Notices per language, versioned. Both runtime roles may only read it; the owner
(the migration role) publishes through `manage.py publish_legal_documents`, so
the text a student accepted can never be edited after the fact.
"""

from uuid import uuid4

from django.db import models

from apps.tenancy.models import Membership, TenantScopedModel


class LegalDocument(models.Model):
    class Kind(models.TextChoices):
        TERMS = "terms", "Terms of Service"
        PRIVACY_NOTICE_DIRECT = "privacy_notice_direct", "Privacy Notice"
        PRIVACY_NOTICE_AGENCY = "privacy_notice_agency", "Privacy Notice"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    kind = models.CharField(max_length=40, choices=Kind.choices)
    language = models.CharField(max_length=2)
    version = models.PositiveIntegerField()
    body = models.TextField()
    sha256 = models.CharField(max_length=64)
    #: A material change makes every student re-accept at their next login.
    material = models.BooleanField(default=True)
    effective_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "language", "version"), name="legal_document_version_uniq"
            ),
            models.UniqueConstraint(
                fields=("kind", "language", "sha256"), name="legal_document_text_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0), name="legal_document_version_positive"
            ),
        ]


class Acceptance(TenantScopedModel):
    """One row per document version a student accepted (spec section 3)."""

    class Surface(models.TextChoices):
        SIGNUP = "signup", "Signup"
        REACCEPTANCE = "reacceptance", "Re-acceptance"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="acceptances")
    document = models.ForeignKey(LegalDocument, on_delete=models.PROTECT, related_name="+")
    accepted_at = models.DateTimeField()
    surface = models.CharField(max_length=20, choices=Surface.choices)
    language = models.CharField(max_length=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="acceptance_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student", "document"), name="acceptance_once_per_document"
            ),
        ]


class PrivacyRequest(TenantScopedModel):
    """A student's request about their data, from whatever channel it came (spec section 6).

    No free text is stored: the request itself stays in the privacy@ mailbox or
    on paper; this row is the deadline and the processing stop.
    """

    class Kind(models.TextChoices):
        ACCESS = "access", "Access"
        CORRECTION = "correction", "Correction"
        DELETION = "deletion", "Deletion"
        OBJECTION = "objection", "Objection"
        WITHDRAWAL = "withdrawal", "Withdrawal of consent"

    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        PAPER_WITH_ID = "paper_with_id", "Paper with ID"
        E_SIGNATURE = "e_signature", "Enhanced e-signature"

    class Outcome(models.TextChoices):
        OPEN = "", "Open"
        DONE = "done", "Done"
        DECLINED = "declined", "Declined"
        RESUMED = "resumed", "Resumed at the student's request"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="privacy_requests"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    received_at = models.DateTimeField()
    due_at = models.DateTimeField()
    handled_at = models.DateTimeField(null=True, blank=True)
    #: The staff membership that closed it. Tenant-guarded by a composite FK (0008).
    handled_by = models.ForeignKey(
        Membership, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="privacy_request_tenant_id_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=("tenant", "student", "kind"), name="privacy_request_student_idx")
        ]
