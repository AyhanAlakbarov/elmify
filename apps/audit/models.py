from uuid import uuid4

from django.db import models

from apps.tenancy.models import Membership, TenantScopedModel


class RetentionPolicy(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    version = models.PositiveIntegerField()
    effective_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "version"), name="retention_tenant_version_uniq"
            )
        ]


class DeletionRequest(TenantScopedModel):
    class Reason(models.TextChoices):
        NO_LONGER_APPLYING = "NO_LONGER_APPLYING", "No longer applying abroad"
        PLACE_ACCEPTED = "PLACE_ACCEPTED", "Accepted a place"
        SWITCHING_AGENCY = "SWITCHING_AGENCY", "Switching to another agency"
        PRIVACY = "PRIVACY", "Privacy"
        OTHER = "OTHER", "Other"

    class ReviewReason(models.TextChoices):
        LEGAL_HOLD = "LEGAL_HOLD", "Legal hold"
        NO_RETENTION_POLICY = "NO_RETENTION_POLICY", "No approved retention policy"
        APPLICATIONS_IN_FLIGHT = "APPLICATIONS_IN_FLIGHT", "Applications in progress"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    state = models.CharField(max_length=20, default="REQUESTED")
    legal_hold = models.BooleanField(default=False)
    # True when the erasure completed but the login identity was deliberately
    # left alive, because the person still holds an active membership at
    # another agency. The tenant-scoped erasure did finish, so state is still
    # EXECUTED -- what would be false is claiming the person is no longer
    # identifiable. This field is that difference.
    identity_retained = models.BooleanField(default=False)
    #: When the erasure becomes due. Stored rather than computed from
    #: created_at + DELETION_WINDOW, because the student was shown a specific
    #: date and changing the window later must never move a date someone has
    #: already seen. NULL until the request reaches APPROVED.
    execute_after = models.DateTimeField(null=True, blank=True)
    #: Why the student is leaving. A fixed list and never free text: free text
    #: from a student is personal data that would itself need redacting, and a
    #: list still gives the agency the signal it wants.
    reason = models.CharField(max_length=30, choices=Reason.choices, blank=True)
    #: Why the request stopped in RETENTION_REVIEW. This is what the owner
    #: screen shows, and it is not cleared on release -- a released request
    #: must stay distinguishable from one that was never held.
    review_reason = models.CharField(max_length=30, choices=ReviewReason.choices, blank=True)
    #: Which of IdentityRetention's three cases left the login alive. Blank
    #: when identity_retained is False. The owner screen shows this, never the
    #: person's name: a retained identity is by definition unscrubbed, so
    #: rendering display_name would put an erased person's real name back on
    #: the screen of the agency that erased them.
    #:
    #: The choices live on apps.audit.identity.IdentityRetention rather than
    #: here -- this module must not import identity.py, which imports
    #: apps.tenancy.models. The constraint below is what enforces them.
    identity_retained_reason = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="deletion_tenant_id_uniq")
        ]
        indexes = [
            # Slice 2's middleware asks "does this student have an open
            # request?" on every authenticated request. One indexed .exists()
            # beats a denormalised flag on Membership, which would be a second
            # source of truth for state and would drift.
            models.Index(fields=("tenant", "student", "state"), name="deletion_lock_idx")
        ]
        constraints += [
            # choices= is enforced by full_clean(), which .create() never
            # calls. Without these, a view doing create(reason=POST["reason"])
            # stores thirty characters of arbitrary student free text in a
            # field classified KEEP -- so it outlives the erasure, which is
            # precisely what a fixed list exists to prevent.
            #
            # The values are spelled out rather than read from the enums:
            # a nested Meta cannot see its outer class's names. That
            # duplication is guarded by
            # test_the_constraints_and_the_enums_do_not_drift.
            models.CheckConstraint(
                condition=models.Q(
                    reason__in=(
                        "",
                        "NO_LONGER_APPLYING",
                        "PLACE_ACCEPTED",
                        "SWITCHING_AGENCY",
                        "PRIVACY",
                        "OTHER",
                    )
                ),
                name="deletion_reason_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    review_reason__in=(
                        "",
                        "LEGAL_HOLD",
                        "NO_RETENTION_POLICY",
                        "APPLICATIONS_IN_FLIGHT",
                    )
                ),
                name="deletion_review_reason_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    identity_retained_reason__in=(
                        "",
                        "STILL_ENROLLED",
                        "STAFF_ACCOUNT",
                        "NOT_A_STUDENT",
                    )
                ),
                name="deletion_identity_retained_reason_valid",
            ),
            # A student holds at most one request that is not finished. Without
            # this, two concurrent POSTs both create a row, deletion_pending's
            # get_object_or_404 raises MultipleObjectsReturned, and the student
            # is trapped: every page redirects to a pending screen that 500s
            # and restore needs an id only that screen shows. The middleware
            # lock closes the ordinary path but cannot close a race.
            #
            # Partial, and the state list is spelled out for the same reason
            # the CheckConstraints above are: a nested Meta cannot see its
            # outer class's names, and views.OPEN_DELETION_STATES cannot be
            # imported here without a cycle. Guarded by
            # test_the_open_states_and_the_constraint_do_not_drift.
            models.UniqueConstraint(
                fields=("tenant", "student"),
                condition=models.Q(
                    state__in=("REQUESTED", "RETENTION_REVIEW", "APPROVED", "DENIED")
                ),
                name="deletion_one_open_request_per_student",
            ),
        ]


class Pseudonym(TenantScopedModel):
    """A random id standing in for one student, so derived data need not name them.

    NOTHING WRITES THIS TABLE, AND THAT IS DELIBERATE -- do not delete it as
    dead code. The delete path has to exist before the data does:
    documents.EuropassRenderCache is already in this repository storing a
    digest derived from a student's CV with no FK back to them, so the erasure
    completeness test cannot see it and it survives erasures today. Nobody
    decided that; nobody was thinking about deletion when it was written.

    THE RULE: any table holding data derived from a student points HERE with
    on_delete=models.CASCADE -- never at Membership directly, and never with
    SET_NULL or PROTECT. That foreign key is the GDPR deletion-propagation
    guarantee: advance_deletion deletes this row and the database removes the
    derived rows with it. tests/audit/test_pseudonym.py pins it.

    The pseudonym IS the primary key. Pseudonym is student-reachable, so the
    classification-completeness test demands every field be classified, and
    classifiable_fields() skips primary keys and relations -- so this leaves
    exactly one field to classify instead of two, and a separate `key` column
    would be a second thing to get wrong.

    Design: docs/superpowers/specs/2026-09-10-erasure-console-design.md
    Scope of what is deliberately unbuilt: CLAUDE.md, "Derived data and the ML
    corpus".
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.OneToOneField(Membership, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="pseudonym_tenant_id_uniq")
        ]
