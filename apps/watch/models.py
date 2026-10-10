"""What the platform is waiting for on each application, and whether its own jobs run.

Design: docs/superpowers/specs/2026-09-25-application-watch-design.md. Lives
outside apps/portals because the watchdog must name the submitted state, which
tests/portals/test_boundary.py reserves there for ext_api.py and models.py.
"""

from __future__ import annotations

from uuid import uuid4

from django.db import models

from apps.tenancy.models import TenantScopedModel


class Expectation(TenantScopedModel):
    """Something that should happen to one application by a time.

    Met is not a column: an expectation is met when the application's state has
    moved past the one that created it, which the watchdog reads directly. A
    column would be a second copy of the state that could disagree with it.
    `alerted` is the idempotency record: set once, in the same transaction as the
    alert, so a second sweep never alerts twice.
    """

    class Kind(models.TextChoices):
        #: The portal acknowledges a submission. Decision and offer kinds wait
        #: for an outcome record (spec §1).
        CONFIRMATION = "CONFIRMATION", "Portal confirms the submission"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    application = models.ForeignKey(
        "portals.Application", on_delete=models.CASCADE, related_name="expectations"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    due_at = models.DateTimeField()
    alerted = models.ForeignKey(
        "concierge.Notification", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="expectation_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("application", "kind"), name="expectation_once_per_kind"
            ),
        ]


class JobRun(models.Model):
    """The last time a scheduled command finished. Platform-wide; names no one.

    Not tenant-scoped: a job runs across every agency, and "did the reminder
    ladder run" is one fact, not one per tenant.
    """

    name = models.CharField(max_length=64, primary_key=True)
    last_success_at = models.DateTimeField()
