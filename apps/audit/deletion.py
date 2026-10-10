from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.identity import redact_identity
from apps.audit.redaction import redact_student
from apps.documents.storage import delete_student_documents
from apps.funding.models import AuditEvent
from apps.mailbox.secrets import delete_student_mailbox_tokens
from apps.portals.auth import delete_student_portal_credentials
from apps.research.coverage import refresh_cell_coverage
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

from .models import DeletionRequest, Pseudonym, RetentionPolicy

#: How long a student has to change their mind. Thirty days, matching the large
#: consumer products; GDPR's one month limits *responding*, which happens at the
#: click. A longer window is a longer chance to undo something that cannot be
#: undone afterwards.
DELETION_WINDOW = timedelta(days=30)

# CANCELLED needs no key of its own: _TRANSITIONS.get("CANCELLED", set()) is
# empty, so it is terminal for free -- as EXECUTED already is. DENIED is here
# so a student whose erasure the agency refused is not stranded behind a lock
# with no way back in.
_TRANSITIONS = {
    "REQUESTED": {"RETENTION_REVIEW", "CANCELLED"},
    "RETENTION_REVIEW": {"APPROVED", "DENIED", "CANCELLED"},
    "APPROVED": {"EXECUTED", "CANCELLED"},
    "DENIED": {"CANCELLED"},
}


class DeletionBlocked(RuntimeError):
    pass


def advance_deletion(request: DeletionRequest, target_state: str) -> DeletionRequest:
    if target_state not in _TRANSITIONS.get(request.state, set()):
        raise DeletionBlocked(f"cannot move from {request.state} to {target_state}")
    with tenant_scope(request.tenant_id):
        if target_state == "APPROVED":
            if request.legal_hold:
                raise DeletionBlocked("legal hold prevents deletion")
            if not RetentionPolicy.objects.filter(tenant_id=request.tenant_id).exists():
                raise DeletionBlocked("no approved retention policy exists")
            # After the guards, so a refused approval leaves no date behind.
            request.execute_after = timezone.now() + DELETION_WINDOW
        if target_state == "EXECUTED":
            # Before the state write: a storage failure must leave the request
            # in APPROVED rather than recording an erasure that did not happen.
            delete_student_documents(tenant_id=request.tenant_id, student_id=request.student_id)
            # Same path, same rule. A student's portal logins outliving their
            # erasure is the failure CLAUDE.md's Phase 3 rules name by hand.
            delete_student_portal_credentials(
                tenant_id=request.tenant_id, student_id=request.student_id
            )
            # Third on the same path, same rule: a live OAuth grant on the
            # student's own mailbox is worse than a stale password, because it
            # keeps reading after the person is gone.
            delete_student_mailbox_tokens(
                tenant_id=request.tenant_id, student_id=request.student_id
            )
            # Last, and in one transaction with the state write. Purging S3
            # first is load-bearing: delete_student_documents reads object_key
            # to find the objects, and redaction empties it. The S3 purge is
            # idempotent, so a redaction failure here is safe to retry.
            #
            # set_local_tenant because several of these tables are FORCE ROW
            # LEVEL SECURITY on app.tenant_id and the runtime role is
            # NOBYPASSRLS; tenant_scope is a contextvar and never reaches
            # Postgres. Without it the UPDATEs match zero rows and EXECUTED is
            # written over data nothing touched.
            with transaction.atomic():
                set_local_tenant(request.tenant_id)
                redact_student(
                    tenant_id=request.tenant_id, student_id=request.student_id
                )
                # Derived and ML rows reference the student only through this,
                # with CASCADE, so deleting it is how an erasure reaches data
                # the redaction walk never sees. Nothing writes it yet; the
                # delete exists before the data by design.
                Pseudonym.objects.filter(student_id=request.student_id).delete()
                # Before the identity scrub, and load-bearing twice over.
                # middleware.py:64 resolves a request's tenant with
                # filter(user_id=..., active=True), so leaving this True lets an
                # erased person keep reaching the agency that erased them. It
                # also poisons redact_identity's guard, which counts active
                # memberships: a tombstone left active reads as a live
                # relationship forever.
                request.student.active = False
                request.student.save(update_fields=["active"])
                # None means the login was scrubbed. An IdentityRetention
                # means it was deliberately kept, and says which of three
                # reasons -- one lawful, two a misconfiguration someone must
                # fix. Recording both is what keeps EXECUTED honest.
                retention = redact_identity(
                    user_id=request.student.user_id,
                    membership_role=request.student.role,
                )
                request.identity_retained = retention is not None
                request.identity_retained_reason = retention.value if retention else ""
                request.state = target_state
                request.save(
                    update_fields=["state", "identity_retained", "identity_retained_reason"]
                )
                # Last, and deliberately after redact_student: the walk has
                # already run, so these rows are not caught by it. They are the
                # only durable record that an erasure ran at all -- state is a
                # current-value field, and redaction rewrites the row around it.
                # Auditing is also what makes redact_identity's guard a lawful
                # cross-tenant read rather than an unrecorded one
                # (`phased requirements.md` §349).
                AuditEvent.objects.create(
                    actor=None, event="deletion.executed", object_id=request.id
                )
                if request.identity_retained:
                    # Its own row rather than a flag: this is the case a
                    # reviewer has to be able to find by query.
                    AuditEvent.objects.create(
                        actor=None, event="deletion.identity_retained", object_id=request.id
                    )
                # The tenant's demand-cell counts, rebuilt without this student
                # (now inactive, above). CellCoverage has no student relation,
                # so neither the redaction walk nor the Pseudonym cascade can
                # reach it: an erased person leaves it by RECOMPUTATION, and a
                # count cell of 1 is a person. In this per-erasure transaction
                # so an erasure never commits with the old counts standing.
                # EXECUTED is reached only from `execute_due_erasures`, on the
                # worker side: the rebuild reads the served catalogue, which
                # runtime_web holds no grant on.
                refresh_cell_coverage(request.tenant_id)
            return request
        request.state = target_state
        # execute_after is in update_fields for every transition, not just
        # APPROVED: omitting it would drop the assignment above with no error.
        # For the others it rewrites the value the row already holds.
        request.save(update_fields=["state", "execute_after"])
    return request
