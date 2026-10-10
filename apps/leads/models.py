"""Demo requests from the public website (the landing page's "Book a demo").

A request belongs to the agency whose host received it, like every other row
here: on Elmify's own host that is Elmify, on a white-label host it is that
agency. Its owner reads them on the owner dashboard. The person who asked is a
prospect, not a student, so nothing here touches the student ledger or erasure.
"""

from __future__ import annotations

from uuid import uuid4

from django.db import models

from apps.tenancy.models import TenantScopedModel


class DemoRequest(TenantScopedModel):
    class Role(models.TextChoices):
        STUDENT = "STUDENT", "Student"
        PARENT = "PARENT", "Parent"
        AGENCY = "AGENCY", "Education agency or consultant"
        UNIVERSITY = "UNIVERSITY", "University"
        OTHER = "OTHER", "Other"

    class State(models.TextChoices):
        NEW = "NEW", "New"
        CONTACTED = "CONTACTED", "Contacted"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    full_name = models.CharField(max_length=150)
    email = models.EmailField(max_length=254)
    role = models.CharField(max_length=20, choices=Role.choices)
    organisation = models.CharField(max_length=150, blank=True)
    country = models.CharField(max_length=80, blank=True)
    message = models.TextField(max_length=2000, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.NEW)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="demo_request_tenant_id_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"
