from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import models
from django.utils import timezone

from apps.tenancy.models import Membership, TenantScopedModel

if TYPE_CHECKING:
    from apps.portals.models import Application


class RoadmapItem(TenantScopedModel):
    class Stage(models.TextChoices):
        STRATEGY = "STRATEGY", "Strategy"
        DOCUMENTS = "DOCUMENTS", "Documents"
        APPLICATION_PREP = "APPLICATION_PREP", "Application preparation"
        PORTAL_EXCEPTION = "PORTAL_EXCEPTION", "CAPTCHA/portal exception"
        SUBMISSION = "SUBMISSION", "Permitted submission"
        FEE_EXECUTION = "FEE_EXECUTION", "Fee execution and reconciliation"
        MONITORING = "MONITORING", "Monitoring"
        INTERVIEW = "INTERVIEW", "Interview"
        PERSONAL_ACTION = "PERSONAL_ACTION", "Required personal action"

    class State(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        DONE = "DONE", "Done"
        BLOCKED = "BLOCKED", "Blocked"

    class OwnerKind(models.TextChoices):
        HUMAN = "HUMAN", "Human"
        AGENT = "AGENT", "Autonomous agent"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="roadmap_items")
    stage = models.CharField(max_length=30, choices=Stage.choices)
    owner = models.ForeignKey(
        Membership, null=True, on_delete=models.PROTECT, related_name="owned_roadmap_items"
    )
    #: The agent owns steps too (`phased requirements.md` §5.2 shows an owner
    #: for every step), and it has no Membership. A synthetic "agent" member
    #: was rejected: Membership is the tenancy primitive, so that row would be
    #: a real principal carrying roles, MFA and RLS standing. Nullable `owner`
    #: alone would make "unowned" and "agent-owned" the same row, so the two
    #: fields are constrained together.
    owner_kind = models.CharField(
        max_length=10, choices=OwnerKind.choices, default=OwnerKind.HUMAN
    )
    deadline = models.DateTimeField()
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    result = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class DeadlineUrgency(models.TextChoices):
        OVERDUE = "OVERDUE", "Overdue"
        DUE_SOON = "DUE_SOON", "Due soon"
        SCHEDULED = "SCHEDULED", "Scheduled"

    #: Deadline treatment: ≤14 days inherits the review state,
    #: past-due the ineligible state; a DONE item is never urgent.
    DUE_SOON_WINDOW_DAYS = 14

    @property
    def deadline_urgency(self) -> RoadmapItem.DeadlineUrgency:
        if self.state == self.State.DONE:
            return self.DeadlineUrgency.SCHEDULED
        now = timezone.now()
        if self.deadline < now:
            return self.DeadlineUrgency.OVERDUE
        if self.deadline <= now + timedelta(days=self.DUE_SOON_WINDOW_DAYS):
            return self.DeadlineUrgency.DUE_SOON
        return self.DeadlineUrgency.SCHEDULED

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="roadmap_tenant_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(owner_kind="HUMAN", owner__isnull=False)
                | models.Q(owner_kind="AGENT", owner__isnull=True),
                name="roadmapitem_owner_kind_matches_owner",
            ),
        ]


class ManualOperation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    roadmap_item = models.ForeignKey(RoadmapItem, on_delete=models.PROTECT)
    actor = models.ForeignKey(Membership, on_delete=models.PROTECT)
    description = models.TextField()
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="manualop_tenant_id_uniq")
        ]


class RequiredAction(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    description = models.TextField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="requiredaction_tenant_id_uniq")
        ]


class Notification(TenantScopedModel):
    class Action(models.TextChoices):
        """The one button "Needs you now" shows for this notification (spec §3)."""

        OPEN_MESSAGE = "OPEN_MESSAGE", "Open message"
        OPEN_PORTAL = "OPEN_PORTAL", "Open portal"
        RECONNECT = "RECONNECT", "Reconnect"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    recipient = models.ForeignKey(Membership, on_delete=models.PROTECT)
    # Who the message is ABOUT, which is not always who receives it: four of the
    # six escalation triggers route to the assigned counselor. Erasure redacts
    # by roadmap_item__student_id, so a notification with no link is one that
    # cannot be erased. Both writers create the RoadmapItem immediately before
    # the notification and it already carries the right student.
    roadmap_item = models.ForeignKey(RoadmapItem, on_delete=models.PROTECT)
    message = models.TextField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    #: Needs a person to acknowledge it; unanswered, apps/watch escalates it.
    #: Everything else waits for the daily summary (spec §4).
    urgent = models.BooleanField(default=False)
    #: How far escalation has gone: 0 dashboard only, 1 emailed, 2 counsellor told.
    escalation_level = models.PositiveSmallIntegerField(default=0)
    #: The application it is about, when it is about one. SET_NULL: removing a
    #: card must not take the student's notification history with it.
    application = models.ForeignKey(
        "portals.Application", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=20, choices=Action.choices, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="notification_tenant_id_uniq")
        ]

    @classmethod
    def raise_card(
        cls,
        *,
        student: Membership,
        recipient: Membership,
        stage: str,
        deadline: datetime,
        message: str,
        owner: Membership | None = None,
        urgent: bool = False,
        action: str = "",
        application: Application | None = None,
    ) -> Notification:
        """One roadmap item about `student` and the notification pointing at it.

        In that order and never separately: roadmap_item is not nullable, and
        erasure redacts notifications by roadmap_item__student_id. No owner is
        the agent's own item (RoadmapItem's check constraint pairs owner=None
        with AGENT); an owner is the person asked to act.
        """
        item = RoadmapItem.objects.create(
            tenant_id=student.tenant_id,
            student=student,
            stage=stage,
            owner=owner,
            owner_kind=(
                RoadmapItem.OwnerKind.AGENT if owner is None else RoadmapItem.OwnerKind.HUMAN
            ),
            deadline=deadline,
        )
        return cls.objects.create(
            tenant_id=student.tenant_id,
            recipient=recipient,
            roadmap_item=item,
            message=message,
            urgent=urgent,
            action=action,
            application=application,
        )


class ConversationMessage(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    counselor = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    sender = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="message_tenant_id_uniq")
        ]


class ServiceEngagement(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    credit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="engagement_tenant_id_uniq")
        ]


class StudentCycle(TenantScopedModel):
    """One academic-year cycle a student pays for (transcript spec R13, §7.1).

    Nothing is uploaded as a transcript and no programme search starts until `paid_at` is set:
    today by `manage.py mark_cycle_paid`, later by a checkout. `pages_used` is the transcript
    reader's allowance counter -- 50 pages a cycle -- kept here and not in the rate-limit cache,
    because a cycle outlives any cache window.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    academic_year = models.CharField(max_length=9)
    paid_at = models.DateTimeField(null=True, blank=True)
    pages_used = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="studentcycle_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("student", "academic_year"), name="studentcycle_student_year_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(academic_year__regex=r"^\d{4}-\d{4}$"),
                name="studentcycle_academic_year_shape",
            ),
        ]


class ApplicationFeeLedgerEntry(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    program_id = models.UUIDField()
    approved_limit = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    charged_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    masked_card_reference = models.CharField(max_length=20, blank=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="ledger_tenant_id_uniq")
        ]


#: What a student may upload (spec §6). CV and TRANSCRIPT are read by the
#: document worker; every other kind is stored for the student to attach.
UPLOAD_KINDS = (
    ("CV", "CV"),
    ("TRANSCRIPT", "Transcript"),
    ("PASSPORT", "Passport"),
    ("DIPLOMA", "Diploma"),
    ("LANGUAGE_CERTIFICATE", "Language certificate"),
    ("RECOMMENDATION", "Recommendation letter"),
    ("OTHER", "Other document"),
)
UPLOAD_KIND_VALUES = frozenset(value for value, _label in UPLOAD_KINDS)


#: An upload the check refused, and what the student is told to do instead
#: (dashboard spec §6, "Upload safety"). Terminal: a redelivered scan verdict
#: never reopens one; the student uploads again.
UPLOAD_REJECTIONS = {
    "REJECTED_TYPE": "Upload a PDF, JPEG or PNG",
    "REJECTED_ACTIVE_CONTENT": (
        "This PDF contains active content; save it again as a plain PDF "
        "(Print → Save as PDF) and upload that"
    ),
}
#: Owner, 2026-10-05: a CV is one of the three as well. A Word CV is the common case.
CV_REJECTED_TYPE = (
    "Upload a PDF, JPEG or PNG; for a Word CV, export it as a PDF "
    "(File → Save as → PDF) and upload that"
)


class DocumentVersion(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    object_key = models.CharField(max_length=500)
    state = models.CharField(max_length=30, default="QUARANTINED")
    scan_result = models.CharField(max_length=20, blank=True)
    #: What the student said this upload is. Routes the scanned-clean file to
    #: its reader; a CV and a transcript are read into different things.
    kind = models.CharField(
        max_length=20,
        choices=UPLOAD_KINDS,
        default="CV",
        db_default="CV",
    )
    #: Shown for a passport and a language certificate (spec §6). Typed by the
    #: student; nothing reads it out of the file.
    expires_on = models.DateField(null=True, blank=True)
    #: The S3 version GuardDuty scanned (the verdict's versionId): the only version of the
    #: quarantine key that is ever checked, copied or read. Empty until a verdict names one.
    scanned_version = models.CharField(max_length=1024, blank=True)
    #: Where the scanned-clean, checked copy lives, under the student's own prefix
    #: (documents/storage.py::promote_upload). Empty until promoted. What the
    #: extension downloads; the quarantine original stays where it is.
    promoted_key = models.CharField(max_length=500, blank=True)
    #: The upload check's reading of the file's own first bytes, never the client's.
    content_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def rejection_message(self) -> str:
        if self.state == "REJECTED_TYPE" and self.kind == "CV":
            return CV_REJECTED_TYPE
        return UPLOAD_REJECTIONS.get(self.state, "")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="document_tenant_id_uniq")
        ]


class Receipt(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    ledger_entry = models.ForeignKey(ApplicationFeeLedgerEntry, on_delete=models.PROTECT)
    object_key = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="receipt_tenant_id_uniq")
        ]
