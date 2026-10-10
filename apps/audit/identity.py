"""Erasure of the login identity, which the redaction walk cannot reach.

apps/audit/redaction.py erases everything a student's Membership reaches. It
cannot reach auth.User: student_reachable_models() grows the set by adding
models whose foreign keys point INTO it, and Membership.user points the other
way. So the login email, the person's name and a working password survive an
erasure that reports EXECUTED.

This module is a sibling rather than part of redaction.py because the two have
opposite scope. redact_student is tenant-scoped and refuses to run when the
ambient tenant does not match its argument; this is deliberately global, since
its whole job is to see whether the person still belongs to another agency.

Design: docs/superpowers/specs/2026-09-09-identity-erasure-design.md
"""

from typing import Any
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection, models


def identity_fields() -> list[str]:
    """Every concrete, non-relational column on auth.User."""
    return [
        f.name
        for f in get_user_model()._meta.get_fields()
        if getattr(f, "concrete", False) and not f.is_relation
    ]


# Written on erasure. password is handled separately via set_unusable_password()
# rather than assigned here -- a raw value in this dict would be a stored
# credential, and Django's hashing is the only thing that should write it.
IDENTITY_REDACT: dict[str, Any] = {
    "email": "",
    "first_name": "",
    "last_name": "",
    "username": None,  # UNIQUE -- written below, not assigned from here
    "password": None,  # nosec B105 -- not a credential, a sentinel meaning "handled via set_unusable_password()"
    "is_active": False,
}

# Structural or a bare timestamp: identifies nobody on its own. is_staff and
# is_superuser are kept because redact_identity refuses to touch any user where
# either is set, so they are never reached with a true value.
IDENTITY_KEEP: tuple[str, ...] = (
    "id",
    "last_login",
    "date_joined",
    "is_staff",
    "is_superuser",
)


class IdentityRetention(models.TextChoices):
    """Why a login survived an erasure. Three cases, two of them a mistake.

    STILL_ENROLLED is lawful and expected -- the person holds an active
    membership at another agency and their login has to keep working. The other
    two mean somebody misconfigured something and a human must look. Collapsing
    them into one boolean puts a misconfiguration and a normal outcome behind
    the same word on the owner screen, which is the only place this fact is
    ever reported: after an erasure the student is gone and cannot be told
    anything.
    """

    STILL_ENROLLED = "STILL_ENROLLED", "Still active at another agency"
    STAFF_ACCOUNT = "STAFF_ACCOUNT", "Account holds Django staff or superuser rights"
    NOT_A_STUDENT = "NOT_A_STUDENT", "The erased membership was not a student"


def redact_identity(*, user_id: Any, membership_role: str) -> IdentityRetention | None:
    """Scrub the login unless the person is still active somewhere. Deletes no rows.

    Returns None when the identity was scrubbed, and an IdentityRetention when
    it was deliberately retained. The caller records that as
    DeletionRequest.identity_retained plus identity_retained_reason: an erasure
    that leaves the person identifiable must say so rather than report a clean
    EXECUTED, and must say which of the three reasons applies.

    Call this AFTER the erased membership has been deactivated -- the guard
    below counts active memberships and the erased one must not be among them.
    """
    from apps.tenancy.models import Membership

    # .get(), not .first(): the only caller passes request.student.user_id, a
    # non-null FK, so a missing user is impossible. If it ever happens, raising
    # beats returning False -- the caller records that as identity_retained,
    # claiming a lawful retention for a user that does not exist.
    user = get_user_model()._default_manager.get(pk=user_id)
    if membership_role != Membership.Role.STUDENT:
        return IdentityRetention.NOT_A_STUDENT
    if user.is_staff or user.is_superuser:
        return IdentityRetention.STAFF_ACCOUNT
    # A SECURITY DEFINER function, not a queryset, and this is the single most
    # dangerous line in the module. The whole purpose of the question is to see
    # memberships at OTHER agencies, and every ordinary read is filtered to the
    # erasing one: Membership.objects by the tenant-scoped manager, and
    # Membership._base_manager by tenancy_membership's row-level policy, which
    # the NOBYPASSRLS runtime role cannot escape and which advance_deletion has
    # already pinned to the erasing tenant on this very connection. Either would
    # find nothing, the guard would pass, and a login another agency is still
    # using would be irreversibly scrubbed and recorded as a complete erasure.
    # Do not "tidy" this back into the ORM.
    # See apps/audit/migrations/0004_active_membership_guard.py.
    with connection.cursor() as cursor:
        cursor.execute("SELECT public.user_has_active_membership(%s)", [user_id])
        (still_enrolled,) = cursor.fetchone()
    if still_enrolled:
        return IdentityRetention.STILL_ENROLLED

    for field, value in IDENTITY_REDACT.items():
        if field == "password":
            user.set_unusable_password()
        elif field == "username":
            # UNIQUE: "" succeeds for the first erased user in a database and
            # raises an integrity error for the second, mid-transaction.
            user.username = f"deleted-{uuid4()}"
        else:
            setattr(user, field, value)
    user.save(update_fields=list(IDENTITY_REDACT))
    # A credential, not a record: CASCADE from User with nothing protecting it,
    # and a working second factor outliving an erasure is the same failure as
    # leaving a portal password behind.
    user.totpdevice_set.all().delete()  # type: ignore[attr-defined]
    return None
