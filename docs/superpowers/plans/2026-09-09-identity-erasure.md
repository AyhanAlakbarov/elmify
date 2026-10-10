# Identity Erasure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an erasure revoke the person's access and scrub their login identity, so that "EXECUTED" stops meaning "everything except the email they log in with".

**Architecture:** A new `apps/audit/identity.py` holds an explicit classification of every `auth.User` field and `redact_identity()`, which scrubs the login only when no active membership remains. `advance_deletion` deactivates the erased membership first, then calls it. When the scrub is refused because the person is still active elsewhere, `DeletionRequest.identity_retained` records that the erasure was knowingly partial.

**Tech Stack:** Django, Postgres, django-otp, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-09-identity-erasure-design.md`

## Global Constraints

- **Delete no rows except TOTP devices.** `Membership.user` is `CASCADE` and `Membership` is `PROTECT`ed by 30 models, so deleting a `User` is impossible. `TOTPDevice` is the sole exception: a credential, `CASCADE`, nothing protecting it.
- **Criterion 2 beats criterion 1.** Never irreversibly break an innocent account. If the person holds another active membership, the login survives and the erasure is recorded as partial. Do not invert this.
- **The membership-count query must NOT be tenant-scoped.** Its purpose is to see other agencies. Use `Membership._base_manager`, never `Membership.objects`. A tenant-scoped read returns nothing, the guard passes, and a live account is scrubbed.
- **`username` is unique.** Blank it and the second erasure in a database raises an integrity error. Use `f"deleted-{uuid4()}"`.
- **`email` is not unique** (verified) — blanking it is safe.
- **Refuse to scrub `is_staff` or `is_superuser` users, and any membership whose role is not `STUDENT`.**
- **Sessions need no code.** `set_unusable_password()` changes the password hash, which changes `get_session_auth_hash()`, which invalidates every session. Do not write session-flushing code.
- **Run tests as:** `export POSTGRES_DB=tehsil_erasure` then `uv run pytest ...`. `ruff` and `mypy` (strict) are blocking CI gates; `ruff format` is deliberately not used.

---

## File Structure

- **Create `apps/audit/identity.py`** — the `auth.User` field classification and `redact_identity()`. A sibling of `redaction.py` rather than part of it: that module is tenant-scoped and guards on the ambient tenant, and this one is deliberately global.
- **Modify `apps/audit/models.py`** — `DeletionRequest.identity_retained`.
- **Create `apps/audit/migrations/0003_deletionrequest_identity_retained.py`.**
- **Modify `apps/audit/redaction.py`** — add `identity_retained` to `KEEP["audit.DeletionRequest"]`.
- **Modify `apps/audit/deletion.py`** — deactivate the membership, then call `redact_identity`.
- **Create `tests/audit/test_identity.py`** — classification completeness, the unscoped-guard regression test, and the scrub.

---

### Task 1: The field classification and its completeness test

The enforcement spine. `auth.User` is unreachable by the existing graph walk, so this change inherits zero coverage; without this test a future Django release adding a field to `auth.User` lands unnoticed.

**Files:**
- Create: `apps/audit/identity.py`
- Create: `tests/audit/test_identity.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `IDENTITY_REDACT: dict[str, object]` mapping field name to the value written, `IDENTITY_KEEP: tuple[str, ...]`, and `identity_fields() -> list[str]`. Task 3 uses all three.

- [ ] **Step 1: Write the failing test**

Create `tests/audit/test_identity.py`:

```python
"""The login identity is outside the redaction walk, so it needs its own guard.

student_reachable_models() grows by adding models whose FKs point INTO the
reached set. Membership.user points the other way, so no walk seeded at
Membership will ever reach auth.User. Nothing else covers these fields.
"""

from django.contrib.auth import get_user_model

from apps.audit.identity import IDENTITY_KEEP, IDENTITY_REDACT, identity_fields


def test_every_user_field_is_classified_exactly_once():
    """auth.User has gained fields across Django releases and will again.

    A new field holding identity must fail the build, not ship unnoticed.
    """
    redact = set(IDENTITY_REDACT)
    keep = set(IDENTITY_KEEP)
    unclassified = [f for f in identity_fields() if f not in redact and f not in keep]
    both = sorted(redact & keep)
    assert not unclassified, f"unclassified auth.User fields: {sorted(unclassified)}"
    assert not both, f"classified twice: {both}"


def test_classification_names_no_field_that_does_not_exist():
    """A typo classifies nothing and silently hides a real field."""
    real = set(identity_fields())
    stale = sorted((set(IDENTITY_REDACT) | set(IDENTITY_KEEP)) - real)
    assert not stale, f"classified fields that do not exist on auth.User: {stale}"


def test_the_identifying_fields_are_redacted_not_kept():
    """Pins the four that matter, so a later edit cannot quietly move one to KEEP."""
    for field in ("email", "first_name", "last_name", "username"):
        assert field in IDENTITY_REDACT, f"{field} must be redacted"
    assert "password" in IDENTITY_REDACT, "the password is a credential, not a record"


def test_username_is_not_blanked_because_it_is_unique():
    """Blanking a unique column works once and raises on the second erasure."""
    assert get_user_model()._meta.get_field("username").unique
    assert IDENTITY_REDACT["username"] != ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `export POSTGRES_DB=tehsil_erasure && uv run pytest tests/audit/test_identity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.audit.identity'`

- [ ] **Step 3: Write the classification**

Create `apps/audit/identity.py`:

```python
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

from __future__ import annotations

from typing import Any
from uuid import uuid4

from django.contrib.auth import get_user_model


def identity_fields() -> list[str]:
    """Every concrete, non-relational column on auth.User."""
    return [
        f.name
        for f in get_user_model()._meta.get_fields()
        if getattr(f, "concrete", False) and not f.is_relation
    ]


def _scrubbed_username() -> str:
    """A unique placeholder, because username is UNIQUE.

    Blanking it to "" succeeds for the first erased user in a database and
    raises an integrity error for the second, mid-transaction. email carries no
    unique constraint (verified), so it is blanked normally.
    """
    return f"deleted-{uuid4()}"


# Written on erasure. password is handled separately via set_unusable_password()
# rather than assigned here -- a raw value in this dict would be a stored
# credential, and Django's hashing is the only thing that should write it.
IDENTITY_REDACT: dict[str, Any] = {
    "email": "",
    "first_name": "",
    "last_name": "",
    "username": _scrubbed_username,
    "password": None,
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
```

- [ ] **Step 4: Run the tests**

Run: `export POSTGRES_DB=tehsil_erasure && uv run pytest tests/audit/test_identity.py -q`
Expected: PASS, 4 tests. If `test_every_user_field_is_classified_exactly_once` fails naming a field, this Django version has one these lists do not — classify it rather than deleting the assertion.

- [ ] **Step 5: Check the gates**

Run: `uv run ruff check apps tests && uv run mypy apps config`
Expected: both clean. An unused import fails the ruff gate, so do not add one speculatively for Task 3.

- [ ] **Step 6: Commit**

```bash
git add apps/audit/identity.py tests/audit/test_identity.py
git commit -m "test: classify every auth.User field for erasure

The redaction walk cannot reach auth.User -- it grows along FKs pointing into
the reached set, and Membership.user points out -- so these fields have no
inherited coverage at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 2: Record that an erasure was partial

`DeletionRequest` gains one field. Separate from the scrub because it is a migration plus a classification entry, and because the completeness test in the *other* module fails until the field is classified — a reviewer should see that as its own green step.

**Files:**
- Modify: `apps/audit/models.py` (`DeletionRequest`)
- Create: `apps/audit/migrations/0003_deletionrequest_identity_retained.py`
- Modify: `apps/audit/redaction.py` (`KEEP["audit.DeletionRequest"]`)

**Interfaces:**
- Consumes: nothing.
- Produces: `DeletionRequest.identity_retained: bool`, default `False`. Task 3 sets it.

- [ ] **Step 1: Write the failing test**

Append to `tests/audit/test_identity.py`:

```python
def test_deletion_request_can_record_a_retained_identity(agency_a, membership_a):
    """An erasure that knowingly leaves the login alive must say so.

    Without this the request reads EXECUTED while the person is still
    identifiable -- the false-claim defect the erasure design exists to prevent,
    one level up.
    """
    from apps.audit.models import DeletionRequest
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        assert request.identity_retained is False
        request.identity_retained = True
        request.save(update_fields=["identity_retained"])
        request.refresh_from_db()
        assert request.identity_retained is True
```

This test needs database access. Add these two lines at the top of
`tests/audit/test_identity.py` if they are not already there — Task 1's tests are pure model
introspection and do not need them, so they will not be:

```python
import pytest

pytestmark = pytest.mark.django_db
```

- [ ] **Step 2: Run it to verify it fails**

Run: `export POSTGRES_DB=tehsil_erasure && uv run pytest tests/audit/test_identity.py -q`
Expected: FAIL — `AttributeError` or `TypeError` on `identity_retained`.

- [ ] **Step 3: Add the field**

In `apps/audit/models.py`, in `class DeletionRequest`, below `legal_hold`:

```python
    # True when the erasure completed but the login identity was deliberately
    # left alive, because the person still holds an active membership at
    # another agency. The tenant-scoped erasure did finish, so state is still
    # EXECUTED -- what would be false is claiming the person is no longer
    # identifiable. This field is that difference.
    identity_retained = models.BooleanField(default=False)
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations audit`
Expected: creates `0003_deletionrequest_identity_retained.py`. A `BooleanField` with a default needs no prompt.

- [ ] **Step 5: Classify the new field**

The classification-completeness test in `tests/audit/test_redaction_classification.py` now fails, because `DeletionRequest` is student-reachable and this field is unclassified. **That failure is the enforcement working.** Add it to `KEEP` in `apps/audit/redaction.py`:

```python
    "audit.DeletionRequest": ("state", "legal_hold", "identity_retained", "created_at"),
```

Do not classify it REDACT: erasing the record of what was erased defeats its purpose.

- [ ] **Step 6: Run the tests**

Run: `export POSTGRES_DB=tehsil_erasure && uv run pytest tests/audit/ -q && uv run python manage.py makemigrations --check --dry-run`
Expected: all pass; no further migrations detected.

- [ ] **Step 7: Commit**

```bash
git add apps/audit/models.py apps/audit/migrations/ apps/audit/redaction.py tests/audit/test_identity.py
git commit -m "feat: record when an erasure leaves the login identity alive

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 3: `redact_identity()`

**Files:**
- Modify: `apps/audit/identity.py`
- Modify: `tests/audit/test_identity.py`

**Interfaces:**
- Consumes: `IDENTITY_REDACT`, `identity_fields` from Task 1; `DeletionRequest.identity_retained` from Task 2.
- Produces: `redact_identity(*, user_id: UUID | int, membership_role: str) -> bool` — returns `True` when the identity was scrubbed, `False` when it was deliberately retained. `advance_deletion` (Task 4) writes that return value into `identity_retained` inverted.

- [ ] **Step 1: Write the failing tests**

Append to `tests/audit/test_identity.py`:

```python
def test_scrubs_the_login_when_no_active_membership_remains(
    agency_a, django_user_model
):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="amina", email="amina@example.test", first_name="Amina", last_name="Yusuf",
        password="pw",
    )
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    with tenant_scope(agency_a.id):
        membership = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
        )
        scrubbed = redact_identity(user_id=user.id, membership_role=membership.role)

    user.refresh_from_db()
    assert scrubbed is True
    assert user.email == ""
    assert user.first_name == ""
    assert user.last_name == ""
    assert user.username != "amina"
    assert user.username.startswith("deleted-")
    assert not user.has_usable_password()
    assert user.is_active is False
    assert not TOTPDevice.objects.filter(user=user).exists()


def test_keeps_the_login_when_the_person_is_active_at_another_agency(
    agency_a, agency_b, django_user_model
):
    """Criterion 2 beats criterion 1: an erasure at one agency must never lock
    the person out of another agency they still belong to."""
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="amina", email="amina@example.test", password="pw"
    )
    with tenant_scope(agency_a.id):
        erased = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
        )
    with tenant_scope(agency_b.id):
        Membership.objects.create(
            tenant=agency_b, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_a.id):
        scrubbed = redact_identity(user_id=user.id, membership_role=erased.role)

    user.refresh_from_db()
    assert scrubbed is False
    assert user.email == "amina@example.test"
    assert user.is_active is True


def test_the_guard_is_not_tenant_scoped(agency_a, agency_b, django_user_model):
    """The regression this design is most likely to acquire later.

    The other-membership query must use Membership._base_manager. Through the
    tenant-scoped default manager it sees only agency A, finds nothing, and
    scrubs a login that agency B is still using. This test is the only thing
    standing between that one-word change and a locked-out user.
    """
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="kwame", email="kwame@example.test", password="pw"
    )
    with tenant_scope(agency_b.id):
        Membership.objects.create(
            tenant=agency_b, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_a.id):
        erased = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
        )
        assert redact_identity(user_id=user.id, membership_role=erased.role) is False

    user.refresh_from_db()
    assert user.email == "kwame@example.test"


def test_refuses_a_django_staff_account(agency_a, django_user_model):
    """A staff or superuser account reaching this path is a misconfiguration,
    not an erasure. Refusing is the recoverable outcome."""
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="ops", email="ops@example.test", password="pw", is_staff=True
    )
    with tenant_scope(agency_a.id):
        membership = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=False
        )
        assert redact_identity(user_id=user.id, membership_role=membership.role) is False

    user.refresh_from_db()
    assert user.email == "ops@example.test"


def test_refuses_a_non_student_membership(agency_a, django_user_model):
    """Erasure is a student right. Offboarding a counselor is a different
    operation and must not run this."""
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="counselor", email="c@example.test", password="pw"
    )
    with tenant_scope(agency_a.id):
        membership = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.COUNSELOR, active=False
        )
        assert redact_identity(user_id=user.id, membership_role=membership.role) is False

    user.refresh_from_db()
    assert user.email == "c@example.test"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `export POSTGRES_DB=tehsil_erasure && uv run pytest tests/audit/test_identity.py -q`
Expected: FAIL — `ImportError: cannot import name 'redact_identity'`.

- [ ] **Step 3: Implement it**

Append to `apps/audit/identity.py`:

```python
def redact_identity(*, user_id: Any, membership_role: str) -> bool:
    """Scrub the login unless the person is still active somewhere. Deletes no rows.

    Returns True when the identity was scrubbed, False when it was deliberately
    retained. The caller records a False as DeletionRequest.identity_retained:
    an erasure that leaves the person identifiable must say so rather than
    report a clean EXECUTED.

    Call this AFTER the erased membership has been deactivated -- the guard
    below counts active memberships and the erased one must not be among them.
    """
    from apps.tenancy.models import Membership

    user_model = get_user_model()
    user = user_model._default_manager.filter(pk=user_id).first()
    if user is None:
        return False
    if membership_role != Membership.Role.STUDENT:
        return False
    if user.is_staff or user.is_superuser:
        return False
    # _base_manager, NOT .objects. The whole purpose of this query is to see
    # memberships at OTHER agencies, and the tenant-scoped default manager
    # filters them out -- it would find nothing, the guard would pass, and a
    # login another agency is still using would be scrubbed. Do not "tidy"
    # this into Membership.objects.
    if Membership._base_manager.filter(user_id=user_id, active=True).exists():
        return False

    for field, value in IDENTITY_REDACT.items():
        if field == "password":
            user.set_unusable_password()
        elif callable(value):
            setattr(user, field, value())
        else:
            setattr(user, field, value)
    user.save(update_fields=list(IDENTITY_REDACT))
    # A credential, not a record: CASCADE from User with nothing protecting it,
    # and a working second factor outliving an erasure is the same failure as
    # leaving a portal password behind.
    user.totpdevice_set.all().delete()
    return True
```

- [ ] **Step 4: Run the tests**

Run: `export POSTGRES_DB=tehsil_erasure && uv run pytest tests/audit/test_identity.py -q`
Expected: PASS, 9 tests.

If `test_scrubs_the_login_...` fails asserting the password is still usable, check that `"password"` is in `update_fields` — it is, because `update_fields=list(IDENTITY_REDACT)` includes it, and `set_unusable_password()` mutates `user.password` in memory before the save.

- [ ] **Step 5: Check the gates**

Run: `uv run ruff check apps tests && uv run mypy apps config`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add apps/audit/identity.py tests/audit/test_identity.py
git commit -m "feat: scrub the login identity when no active membership remains

Refuses on a staff account, a non-student membership, or a person still active
at another agency -- an erasure at one agency must never lock someone out of
another they still belong to.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 4: Wire it into `advance_deletion`, and revoke access

The change that closes the gap. It also fixes a defect found while reviewing the spec: erasure never revoked the person's access.

**Files:**
- Modify: `apps/audit/deletion.py`
- Modify: `tests/audit/test_identity.py`

**Interfaces:**
- Consumes: `redact_identity` from Task 3, `identity_retained` from Task 2.
- Produces: no new names. `advance_deletion`'s signature is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/audit/test_identity.py`:

```python
def _approved_request(agency, student):
    from django.utils import timezone

    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    RetentionPolicy.objects.create(tenant=agency, version=1, effective_at=timezone.now())
    request = DeletionRequest.objects.create(tenant=agency, student=student, state="REQUESTED")
    advance_deletion(request, "RETENTION_REVIEW")
    advance_deletion(request, "APPROVED")
    return request


def test_executed_revokes_access_and_scrubs_the_login(
    agency_a, django_user_model, monkeypatch
):
    """Membership.active is what middleware.py:64 uses to resolve a request's
    tenant. Left True, an erased person keeps access to the agency that erased
    them."""
    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)

    user = django_user_model.objects.create_user(
        username="amina", email="amina@example.test", password="pw"
    )
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")
        request.refresh_from_db()
        student.refresh_from_db()

    user.refresh_from_db()
    assert request.state == "EXECUTED"
    assert student.active is False
    assert request.identity_retained is False
    assert user.email == ""
    assert user.is_active is False


def test_executed_records_a_retained_identity(
    agency_a, agency_b, django_user_model, monkeypatch
):
    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)

    user = django_user_model.objects.create_user(
        username="amina", email="amina@example.test", password="pw"
    )
    with tenant_scope(agency_b.id):
        Membership.objects.create(
            tenant=agency_b, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        request = _approved_request(agency_a, student)
        advance_deletion(request, "EXECUTED")
        request.refresh_from_db()

    user.refresh_from_db()
    assert request.state == "EXECUTED"
    assert request.identity_retained is True
    assert user.email == "amina@example.test"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `export POSTGRES_DB=tehsil_erasure && uv run pytest tests/audit/test_identity.py -q -k "executed"`
Expected: FAIL — `assert True is False` on `student.active`. That failing assertion is the access-revocation defect, reproduced.

- [ ] **Step 3: Wire it in**

In `apps/audit/deletion.py`, add the import:

```python
from apps.audit.identity import redact_identity
```

and inside the `EXECUTED` branch, replace the `transaction.atomic()` block with:

```python
            with transaction.atomic():
                set_local_tenant(request.tenant_id)
                redact_student(
                    tenant_id=request.tenant_id, student_id=request.student_id
                )
                # Before the identity scrub, and load-bearing twice over.
                # middleware.py:64 resolves a request's tenant with
                # filter(user_id=..., active=True), so leaving this True lets an
                # erased person keep reaching the agency that erased them. It
                # also poisons redact_identity's guard, which counts active
                # memberships: a tombstone left active reads as a live
                # relationship forever.
                request.student.active = False
                request.student.save(update_fields=["active"])
                # False means the login was deliberately kept, because the
                # person is still active at another agency. Recording it is
                # what keeps EXECUTED honest.
                request.identity_retained = not redact_identity(
                    user_id=request.student.user_id,
                    membership_role=request.student.role,
                )
                request.state = target_state
                request.save(update_fields=["state", "identity_retained"])
            return request
```

- [ ] **Step 4: Run the tests**

Run: `export POSTGRES_DB=tehsil_erasure && uv run pytest tests/audit/ -q`
Expected: PASS. Every pre-existing test in `tests/audit/` must still pass — they exercise the same transitions. If one fails because it asserts a `Membership` is still active after erasure, read it before changing it and say so prominently in your report.

- [ ] **Step 5: Run the full gate**

```bash
export POSTGRES_DB=tehsil_erasure
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
```

All five must pass. The whole suite takes about three minutes. Do NOT run `ruff format`.

If a test outside `tests/audit/` fails, do not fix it — report it with its name and output. Deactivating a membership is a behaviour change and something elsewhere may depend on it; that is a decision, not a cleanup.

- [ ] **Step 6: Commit**

```bash
git add apps/audit/deletion.py tests/audit/test_identity.py
git commit -m "fix: erasure now revokes access and scrubs the login identity

advance_deletion redacted 124 fields and wrote EXECUTED while auth.User kept
the login email, the person's name and a working password, and the membership
stayed active -- so the person could still sign in to the agency that erased
them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 5: Retire the spec's superseded carve-out

Documentation only, but it is the difference between a spec that describes the system and one that lies about it.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md`

**Interfaces:** none.

- [ ] **Step 1: Replace the carve-out**

In the "What this does not do" section, the bullet beginning **"Does not anonymise the `User`"** is now false. Replace it with:

```markdown
- **Anonymises the `User` only when no active membership remains.** Closed by
  `docs/superpowers/specs/2026-09-09-identity-erasure-design.md`: the login is scrubbed and the
  membership deactivated on the `EXECUTED` path. When the person is still active at another agency
  the login survives by design, and `DeletionRequest.identity_retained` records that the erasure was
  partial.
```

- [ ] **Step 2: Check nothing else still claims the old behaviour**

Run: `grep -rn "Does not anonymise\|does not anonymise" docs/`
Expected: no hits.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md
git commit -m "docs: the User carve-out is closed

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

## Out of scope

- **The operator console.** This plan makes the engine honest; it does not give `advance_deletion` a caller. That is the next design, and it carries the agreed 14-day reversal window and the agency notification.
- **One-agency-per-student as a database invariant.** A partial unique index following the `CounselorAssignment` precedent would make the product rule real, but it is a cross-tenant constraint deserving its own change, and it does not remove the guard here — the guard also covers a student who is also a counselor.
- **`documents.EuropassRenderCache`.** It stores a SHA-256 of the student's CV payload with no FK to `Membership`, so the completeness test cannot see it. Adding the FK is a small separate change.
