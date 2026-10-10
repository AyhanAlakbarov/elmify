# Erasure Console — Slice 3: The Command and the Owner Screen

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `RETENTION_REVIEW` an exit and `APPROVED` a clock — the management command that erases due requests, and the owner screen that releases or refuses held ones.

**Architecture:** `apps/audit/management/commands/execute_due_erasures.py` scans per agency and erases one request per transaction, locking the row and re-reading its state so a restore that wins the race is honoured. Two new services in `apps/audit/console.py` (`release_deletion`, `deny_deletion`) carry the owner's two actions; three new views in `apps/audit/views.py` render the three lists and drive those services. One migration closes a defect slice 2 shipped.

**Tech Stack:** Django 5.2 LTS on Python 3.14, PostgreSQL 17 with row-level security, pytest + pytest-django, uv.

**Spec:** `docs/superpowers/specs/2026-09-10-erasure-console-design.md`
**Predecessors:** slice 1 (PR #70, merged), slice 2 (PR #71, merged as `8860c68`).

## Global Constraints

- **`export POSTGRES_DB=tehsil_erasure_console`** before running tests.
- **Never run `ruff format`.** Lint-only repo.
- **The full gate, as CI runs it:**
  ```
  uv run ruff check .
  uv run mypy apps config
  uv run bandit -c pyproject.toml -r apps config
  uv run python manage.py check
  uv run python manage.py makemigrations --check --dry-run
  uv run pytest -q
  ```
- **Run the FULL suite, never just `tests/audit/`.** Slice 1 shipped two defects that scoped runs hid.
- **Baseline is 2220 passed / 45 skipped / 8 deselected** (master at `8860c68`).
- **Template stubs render nothing.** `tests/templates/README.md` forbids enriching a stub to make a test pass; markup assertions get `@pytest.mark.frontend` and skip.
- **No EventBridge rule.** The schedule is deliberately deferred and gated in `CLAUDE.md`; this slice builds the command only.
- **`ObjectStoreError` does not exist.** The spec's scheduler sketch catches it; nothing in this repo defines it. `delete_student_documents` and `delete_student_portal_credentials` both raise `botocore.exceptions.ClientError`. Catch that.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP
  ```

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `apps/audit/migrations/0009_one_open_deletion_request.py` | the partial unique constraint | create |
| `apps/audit/models.py` | declare that constraint | modify |
| `apps/audit/views.py` | absorb the duplicate; three owner views | modify |
| `apps/audit/console.py` | `release_deletion`, `deny_deletion` | modify |
| `apps/audit/management/__init__.py` | package marker | create |
| `apps/audit/management/commands/__init__.py` | package marker | create |
| `apps/audit/management/commands/execute_due_erasures.py` | the scheduler | create |
| `apps/audit/urls.py` | owner routes | modify |
| `tests/templates/audit/deletion_console.html` | stub | create |
| `tests/audit/test_execute_due_erasures.py` | the command | create |
| `tests/audit/test_execute_due_erasures_rls.py` | the command under NOBYPASSRLS | create |
| `tests/audit/test_deletion_views.py` | the duplicate, the owner screen | modify |

---

### Task 1: One open request per student

**Files:**
- Modify: `apps/audit/models.py`, `apps/audit/views.py`, `tests/audit/test_deletion_views.py`
- Create: `apps/audit/migrations/0009_one_open_deletion_request.py`

**Interfaces:**
- Produces: a `deletion_one_open_request_per_student` partial `UniqueConstraint`; `request_account_deletion` becomes idempotent — a second open request redirects to the pending screen instead of creating a row.

**The defect this closes, found in slice 2's security review:** `deletion_pending` uses
`get_object_or_404(..., state__in=OPEN_DELETION_STATES)`, which raises `MultipleObjectsReturned` →
500 if a student holds two open requests, and `request_deletion` creates unconditionally. Slice 2's
middleware lock closes the ordinary path but not a concurrent double-submit — double-clicking
"Delete my account" is exactly how that happens. It compounds: every page then redirects to a
pending screen that 500s, and restore needs an id only that screen shows. A student is permanently
trapped.

The database is the only place this can be fixed, because the race is between two requests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/audit/test_deletion_views.py`:

```python
def test_a_second_open_request_is_refused_by_the_database(agency_a, membership_a):
    """The constraint, directly. Two open requests are what makes the pending
    screen raise MultipleObjectsReturned, which traps the student behind a
    500 with no way to reach restore.
    """
    from django.db import IntegrityError

    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="APPROVED")
        with pytest.raises(IntegrityError):
            DeletionRequest.objects.create(
                tenant=agency_a, student=membership_a, state="REQUESTED"
            )


def test_a_closed_request_does_not_block_a_new_one(agency_a, membership_a):
    """The constraint is partial. A student who cancels may ask again."""
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="CANCELLED")
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="EXECUTED")
        again = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )

    assert again.state == "REQUESTED"


def test_the_view_absorbs_a_duplicate_when_the_lock_does_not(
    client, agency_a, domain_a, user_a, membership_a, monkeypatch
):
    """The view's own guard, with the middleware lock disabled.

    The lock normally redirects a second POST before it ever reaches the view,
    so a test that just posts twice proves nothing about this layer -- it
    passes on the lock alone. Disabling the lock is what puts the second POST
    through the view, where the constraint raises IntegrityError and the
    savepoint has to keep the outer transaction usable for the redirect.
    Without the savepoint this returns a TransactionManagementError 500.
    """
    monkeypatch.setattr(
        "apps.tenancy.middleware.deletion_lock_target", lambda membership: None
    )
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)
    second = client.post(
        "/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host
    )

    assert second.status_code == 302, "the caught IntegrityError poisoned the transaction"
    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.filter(student=membership_a).count() == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
export POSTGRES_DB=tehsil_erasure_console
uv run pytest tests/audit/test_deletion_views.py -q -k "second_open or closed_request or double_submit"
```

Expected: `test_a_second_open_request_is_refused_by_the_database` FAILS (`DID NOT RAISE IntegrityError`). The other two pass already — they are the regression guards that keep the constraint from being written too broadly.

- [ ] **Step 3: Add the constraint**

In `apps/audit/models.py`, inside `DeletionRequest.Meta`, append to the second `constraints +=` block:

```python
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
```

- [ ] **Step 4: Generate the migration**

```bash
uv run python manage.py makemigrations audit --name one_open_deletion_request
```

Expected: creates `apps/audit/migrations/0009_one_open_deletion_request.py` with one `AddConstraint`. Read it before continuing — it must depend on `0008_pseudonym_tenant_guards` and contain nothing else.

- [ ] **Step 5: Absorb the duplicate in the view**

In `apps/audit/views.py`, add to the imports:

```python
from django.db import IntegrityError, transaction
```

Replace the body of `request_account_deletion`'s final two lines:

```python
    # The savepoint matters: HostTenantContextMiddleware wraps every request in
    # transaction.atomic(), so an IntegrityError caught without one leaves the
    # transaction poisoned and the redirect below fails with
    # TransactionManagementError. A double-click is not an error to show the
    # student -- the pending screen is where both POSTs were going anyway.
    try:
        with transaction.atomic():
            request_deletion(student=student, reason=reason)
    except IntegrityError:
        pass
    return redirect("audit-deletion-pending")
```

- [ ] **Step 6: Pin the duplication**

Append to `tests/audit/test_deletion_views.py`:

```python
def test_the_open_states_and_the_constraint_do_not_drift():
    """The Meta constraint spells out the states because it cannot import them.
    This is the guard on that duplication, same shape as
    test_the_constraints_and_the_enums_do_not_drift in test_deletion.py.
    """
    from apps.audit.views import OPEN_DELETION_STATES

    constraint = next(
        c
        for c in DeletionRequest._meta.constraints
        if c.name == "deletion_one_open_request_per_student"
    )
    ((lookup, states),) = constraint.condition.children
    assert lookup == "state__in"
    assert tuple(states) == OPEN_DELETION_STATES
```

- [ ] **Step 7: Verify, then run the full suite**

```bash
uv run pytest tests/audit/test_deletion_views.py -q
uv run pytest -q
```

Expected: 17 passed in the file; 2224 passed overall.

- [ ] **Step 8: Commit**

```bash
git add apps/audit/models.py apps/audit/migrations/0009_one_open_deletion_request.py \
        apps/audit/views.py tests/audit/test_deletion_views.py
git commit -m "fix(audit): one open deletion request per student

Two concurrent POSTs both created a row, deletion_pending's
get_object_or_404 then raised MultipleObjectsReturned, and the student
was trapped: every page redirects to a pending screen that 500s, and
restore needs an id only that screen shows. Double-clicking the button
is how it happens.

The middleware lock closes the ordinary path but cannot close a race, so
the constraint is partial-unique in the database. The view absorbs the
duplicate inside a savepoint -- without one the caught IntegrityError
leaves the request's outer atomic() poisoned and the redirect raises
TransactionManagementError.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 2: `execute_due_erasures`

**Files:**
- Create: `apps/audit/management/__init__.py`, `apps/audit/management/commands/__init__.py`, `apps/audit/management/commands/execute_due_erasures.py`, `tests/audit/test_execute_due_erasures.py`

**Interfaces:**
- Consumes: `apps.audit.deletion.advance_deletion`, `DeletionBlocked`; `apps.tenancy.models.Agency`; `apps.tenancy.context.tenant_scope`; `apps.tenancy.db.set_local_tenant`.
- Produces: `manage.py execute_due_erasures`, erasing every `APPROVED` request whose `execute_after` has passed.

**Four things it must get right, every one of which fails silently** (spec, "The scheduler"):

1. **Open a transaction and set the GUC.** A management command has no middleware. `audit_deletionrequest` is FORCE ROW LEVEL SECURITY on `app.tenant_id` and the production runtime role is `NOBYPASSRLS`, so without `set_local_tenant` the scan is legal SQL that returns zero rows — the command finds nothing, reports success, and no erasure ever happens. `set_local_tenant` issues `SET LOCAL`, so it must be re-issued inside **every** transaction, not once per agency.
2. **One transaction per request, never one per agency.** `delete_student_documents` purges S3 *outside* the database, so an S3 error on the fourth student would roll back the first three students' `EXECUTED` rows while their objects are already gone. The unit of atomicity is one erasure, because the unit of irreversible side effect is one erasure.
3. **Lock the row and re-read the state.** `advance_deletion` checks `request.state` on the **in-memory** object, so a request scanned as `APPROVED` and cancelled a second later is erased anyway — irreversibly, against a request that no longer exists.
4. **Do not hold an outer scope.** `tenant_scope` refuses to *switch* tenants (`TenantContextConflict`), so the loop enters and leaves one scope per agency. `Agency` is not tenant-scoped and carries no RLS policy, so listing agencies from the runtime role works.

- [ ] **Step 1: Write the failing tests**

Create `tests/audit/test_execute_due_erasures.py`:

```python
"""The scheduler. Every failure mode here is silent, which is why each has a test.

The S3 purge and the portal-credential purge are stubbed throughout: unpatched
they build real AWS clients, which need an ambient region -- passing on a laptop
with ~/.aws/config and failing in CI, which has none. Same stubs as
tests/audit/test_deletion_purges_documents.py.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0)


def _student(agency, django_user_model, name):
    with tenant_scope(agency.id):
        user = django_user_model.objects.create(username=name)
        return Membership.objects.create(
            tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
        )


def _due(agency, student, *, overdue=True):
    """An APPROVED request whose clock has run out (or has not)."""
    with tenant_scope(agency.id):
        RetentionPolicy.objects.get_or_create(
            tenant=agency, version=1, defaults={"effective_at": timezone.now()}
        )
        request = DeletionRequest.objects.create(
            tenant=agency, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        if overdue:
            # Reach past execute_after rather than sleeping thirty days.
            DeletionRequest.objects.filter(id=request.id).update(
                execute_after=timezone.now() - timedelta(days=1)
            )
            request.refresh_from_db()
        return request


def test_a_due_request_is_erased(agency_a, django_user_model):
    student = _student(agency_a, django_user_model, "due-1")
    request = _due(agency_a, student)

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        request.refresh_from_db()
    assert request.state == "EXECUTED"


def test_a_request_still_counting_down_is_left_alone(agency_a, django_user_model):
    """Criterion 6: only requests past execute_after execute."""
    student = _student(agency_a, django_user_model, "due-2")
    request = _due(agency_a, student, overdue=False)

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        request.refresh_from_db()
    assert request.state == "APPROVED"


def test_a_held_request_is_never_erased_by_the_clock(agency_a, django_user_model):
    """RETENTION_REVIEW has no execute_after, so the filter must not reach it
    even if something later writes one.
    """
    student = _student(agency_a, django_user_model, "due-3")
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a,
            student=student,
            state="RETENTION_REVIEW",
            execute_after=timezone.now() - timedelta(days=1),
        )

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        request.refresh_from_db()
    assert request.state == "RETENTION_REVIEW"


def test_a_restore_that_wins_the_race_is_honoured(agency_a, django_user_model, monkeypatch):
    """Criterion 6a. The student cancels between the scan and the erasure.

    Without select_for_update plus the state re-check, advance_deletion reads
    state off the in-memory object and erases a request that no longer exists
    -- irreversibly, after the student withdrew it. Simulated by cancelling
    inside the lock, which is where the real restore view's UPDATE would land.
    """
    student = _student(agency_a, django_user_model, "race-1")
    request = _due(agency_a, student)

    original = DeletionRequest.objects.select_for_update
    fired: list[int] = []

    def cancel_then_lock(*args, **kwargs):
        # Only on the first call, and never monkeypatch.undo() here: the
        # `monkeypatch` fixture is one instance shared with the autouse _no_aws
        # fixture above, so undoing would restore the real AWS clients midway
        # through the erasure.
        if not fired:
            fired.append(1)
            DeletionRequest.objects.filter(id=request.id).update(state="CANCELLED")
        return original(*args, **kwargs)

    monkeypatch.setattr(DeletionRequest.objects, "select_for_update", cancel_then_lock)

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        request.refresh_from_db()
    assert request.state == "CANCELLED", "erased a request the student had withdrawn"


def test_one_failure_does_not_roll_back_another_erasure(
    agency_a, django_user_model, monkeypatch
):
    """Criterion 6b. Confirmed RED against a version that wraps the agency's
    batch in one atomic(): the first student's EXECUTED row is rolled back
    while their S3 objects are already gone, so tomorrow's run re-erases
    documents that no longer exist and in between the database says the
    erasure never happened.
    """
    from botocore.exceptions import ClientError

    first = _due(agency_a, _student(agency_a, django_user_model, "batch-1"))
    second = _due(agency_a, _student(agency_a, django_user_model, "batch-2"))

    seen: list[object] = []

    def boom(*, tenant_id, student_id):
        seen.append(student_id)
        if len(seen) > 1:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObjects")
        return 0

    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", boom)

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        first.refresh_from_db()
        second.refresh_from_db()
    # The scan's order is not guaranteed, so assert the property rather than
    # which row it landed on: exactly one erasure committed and one did not.
    assert sorted([first.state, second.state]) == ["APPROVED", "EXECUTED"], (
        "one student's failure rolled back another student's completed erasure"
    )


def test_another_agencys_request_is_erased_too(
    agency_a, agency_b, django_user_model, monkeypatch
):
    """The per-agency loop. tenant_scope refuses to switch tenants, so a
    command that opened one scope and stayed in it would raise
    TenantContextConflict on the second agency rather than erase anything.
    """
    a = _due(agency_a, _student(agency_a, django_user_model, "multi-a"))
    b = _due(agency_b, _student(agency_b, django_user_model, "multi-b"))

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        a.refresh_from_db()
    with tenant_scope(agency_b.id):
        b.refresh_from_db()
    assert (a.state, b.state) == ("EXECUTED", "EXECUTED")
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/audit/test_execute_due_erasures.py -q
```

Expected: every test fails with `CommandError: Unknown command: 'execute_due_erasures'`.

- [ ] **Step 3: Create the package markers**

```bash
touch apps/audit/management/__init__.py apps/audit/management/commands/__init__.py
```

Both stay empty — that is what every other `management/commands/` directory in this repo looks like.

- [ ] **Step 4: Write the command**

Create `apps/audit/management/commands/execute_due_erasures.py`:

```python
"""Erase every deletion request whose thirty-day window has run out.

THE SCHEDULE IS DEFERRED AND THIS IS A DEPLOYMENT GATE. Nothing invokes this
on a schedule yet; until the EventBridge rule exists (model it on
EuropassCanaryRule in infra/template.yaml -- ECS RunTask against
WorkerTaskDefinition, rate(1 day)), erasures happen by running this by hand.
A deployment that never invokes it leaves every student who asked to be erased
locked out indefinitely and never erased, with every screen saying the right
thing. See CLAUDE.md, "Erasure: the schedule is deferred".

Design: docs/superpowers/specs/2026-09-10-erasure-console-design.md
"""

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.audit.deletion import DeletionBlocked, advance_deletion
from apps.audit.models import DeletionRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency


class Command(BaseCommand):
    help = "Execute deletion requests whose reversal window has expired"

    def handle(self, *_args: object, **_options: object) -> None:
        # Agency is not tenant-scoped and carries no RLS policy, so listing it
        # from the runtime role works. One scope per agency: tenant_scope
        # refuses to SWITCH tenants (TenantContextConflict), so an outer scope
        # held across the loop would raise on the second agency.
        for agency in Agency.objects.all():
            with tenant_scope(agency.id):
                self._erase_due_for(agency.id)

    def _erase_due_for(self, tenant_id: object) -> None:
        with transaction.atomic():
            # set_local_tenant issues SET LOCAL, so it belongs inside every
            # transaction and not once per agency. Without it this scan is
            # legal SQL that returns zero rows under RLS: the command finds
            # nothing, exits 0, and no erasure ever happens.
            set_local_tenant(tenant_id)
            due_ids = list(
                DeletionRequest.objects.filter(
                    state="APPROVED", execute_after__lte=timezone.now()
                ).values_list("id", flat=True)
            )

        # One transaction per erasure, never one per agency.
        # delete_student_documents purges S3 outside the database, so an error
        # on the fourth student would roll back the first three students'
        # EXECUTED rows while their objects are already gone. Those three then
        # re-run tomorrow against documents that no longer exist, and in
        # between the database says they were never erased.
        for request_id in due_ids:
            try:
                with transaction.atomic():
                    set_local_tenant(tenant_id)
                    # select_for_update plus the re-check is what honours a
                    # restore that wins the race: advance_deletion reads state
                    # off the in-memory object, so a request scanned as
                    # APPROVED and cancelled a second later is otherwise erased
                    # anyway -- irreversibly, after the student withdrew it.
                    # The restore view's UPDATE blocks on this lock.
                    request = DeletionRequest.objects.select_for_update().get(id=request_id)
                    if request.state != "APPROVED":
                        continue
                    advance_deletion(request, "EXECUTED")
            except (DeletionBlocked, ClientError) as error:
                # Per request, so one stuck row does not strand the batch. Each
                # request owns its transaction, so a caught failure leaves
                # every other erasure committed.
                self.stderr.write(f"{request_id}: {error}")
```

- [ ] **Step 5: Verify, then run the full suite**

```bash
uv run pytest tests/audit/test_execute_due_erasures.py -q
uv run pytest -q
```

Expected: 7 passed in the file; 2231 passed overall. (The plan first specified 6; the atomicity test was split in two during execution -- a *caught* ClientError never marks a transaction for rollback, so the original test passed under a single per-agency atomic() too and proved nothing. The second test raises an error the command does not catch, which is what actually reaches the transaction, and is confirmed RED.)

- [ ] **Step 6: Commit**

```bash
git add apps/audit/management tests/audit/test_execute_due_erasures.py
git commit -m "feat(audit): execute deletion requests whose window has expired

One transaction per erasure, never one per agency: the S3 purge happens
outside the database, so a failure on the fourth student would roll back
the first three students' EXECUTED rows while their objects are already
gone. The unit of atomicity is one erasure because the unit of
irreversible side effect is one erasure.

select_for_update plus a state re-check honours a restore that wins the
race. advance_deletion reads state off the in-memory object, so a
request scanned as APPROVED and cancelled a second later would otherwise
be erased anyway, against a request the student had withdrawn.

set_local_tenant inside every transaction, not once per agency: SET
LOCAL does not outlive its transaction, and without it the scan is legal
SQL that returns zero rows under RLS -- the command finds nothing and
exits 0.

The schedule stays deferred. CLAUDE.md carries the deployment gate.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 3: The command under real row-level security

**Files:**
- Create: `tests/audit/test_execute_due_erasures_rls.py`

**Interfaces:**
- Consumes: Task 2's command; the `rls_enforced_orm` fixture in `tests/conftest.py`.

**Why this is its own file:** criterion 7. The rest of the audit suite runs as the test
superuser, which is `BYPASSRLS`, so the command passes there whether or not `set_local_tenant`
is present. This is the only test that can observe the missing-GUC failure. Same reasoning and
same shape as `tests/audit/test_identity_rls.py`.

- [ ] **Step 1: Write the test**

Create `tests/audit/test_execute_due_erasures_rls.py`:

```python
"""The scheduler, run under a role that RLS actually applies to.

The rest of the audit suite runs as the test superuser, which is BYPASSRLS, so
the command's scan sees every row there and passes for the wrong reason. In
production the runtime role is NOBYPASSRLS and audit_deletionrequest is FORCE
ROW LEVEL SECURITY on app.tenant_id, so without set_local_tenant inside the
transaction the scan is legal SQL returning zero rows: the command finds
nothing, exits 0, and no student is ever erased while every screen says the
erasure is scheduled.

Must be confirmed RED against a version of the command with set_local_tenant
removed. Same shape as tests/audit/test_identity_rls.py.

Design: docs/superpowers/specs/2026-09-10-erasure-console-design.md
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0)


@pytest.fixture
def due_request(agency_a, user_a):
    """An overdue APPROVED request, committed as the superuser before
    rls_enforced_orm swaps the role -- the same ordering the portal and
    identity RLS tests use.
    """
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user_a, role=Membership.Role.STUDENT, active=True
        )
        RetentionPolicy.objects.create(
            tenant=agency_a, version=1, effective_at=timezone.now()
        )
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        DeletionRequest.objects.filter(id=request.id).update(
            execute_after=timezone.now() - timedelta(days=1)
        )
        return request


def test_the_command_erases_under_a_nobypassrls_role(agency_a, due_request, rls_enforced_orm):
    """RED with set_local_tenant removed, and unobservable anywhere else.

    Without the GUC the scan returns zero rows, the command exits 0 having done
    nothing, and the student stays locked out forever with their statutory
    month running.
    """
    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        due_request.refresh_from_db()
    assert due_request.state == "EXECUTED", (
        "the scan found nothing under RLS -- set_local_tenant is missing "
        "from the command's transaction"
    )
```

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/audit/test_execute_due_erasures_rls.py -q
```

Expected: 1 passed.

- [ ] **Step 3: Confirm it is RED against a command without the GUC**

This is the step that proves the test is worth having. Temporarily comment out **both**
`set_local_tenant(tenant_id)` calls in `execute_due_erasures.py`, run:

```bash
uv run pytest tests/audit/test_execute_due_erasures_rls.py -q
uv run pytest tests/audit/test_execute_due_erasures.py -q
```

Expected: the RLS test FAILS (`assert 'APPROVED' == 'EXECUTED'`), and the ordinary command tests
still **pass** — which is the whole point: the ordinary suite cannot see this failure. Restore both
lines and re-run to confirm green. Record both outcomes in the commit message; do not skip this
step, and do not commit the commented-out version.

- [ ] **Step 4: Run the full suite**

```bash
uv run pytest -q
```

Expected: 2232 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/audit/test_execute_due_erasures_rls.py
git commit -m "test(audit): the scheduler, under a role RLS applies to

The rest of the suite runs as the test superuser, which is BYPASSRLS, so
the command's scan passes there whether or not set_local_tenant is
present. Confirmed RED with both calls removed: this test fails and
every other command test still passes, which is exactly why it exists.

The failure it guards is silent and total -- the scan returns zero rows,
the command exits 0, and no student is ever erased while every screen
says the erasure is scheduled.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 4: The owner screen

**Files:**
- Modify: `apps/audit/console.py`, `apps/audit/views.py`, `apps/audit/urls.py`, `tests/audit/test_deletion_views.py`
- Create: `tests/templates/audit/deletion_console.html`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `release_deletion(*, request, owner)` and `deny_deletion(*, request, owner)` in `console.py`; three URL names — `audit-deletion-console` (`GET /owner/deletions/`), `audit-release-deletion` (`POST /owner/deletions/<uuid>/release/`), `audit-deny-deletion` (`POST /owner/deletions/<uuid>/deny/`). The console renders `audit/deletion_console.html` with context keys `held`, `counting_down`, `partially_erased`.

**Why this screen is not optional** (spec, "The owner screen"):

- **It is the only exit from `RETENTION_REVIEW`.** There is no agency work queue in this codebase — `concierge.RequiredAction` is student-facing and `report_portal_interventions` is a CLI report. Without it a held request is seen by nobody while the student has been told their records are being kept.
- **It is the only place a partial erasure is ever reported.** After erasure the student is gone and cannot be told anything, so `identity_retained` has exactly one audience.
- **It is the agency's notification.** No email exists in this codebase, so the `APPROVED` list is how an agency learns a student is leaving, in time to act on it.

**`review_reason` is not cleared on release.** It is the record of why the request was held, and the
`AuditEvent` says who released it; erasing it would leave a released request indistinguishable from
one that was never held.

**The partial-erasure list carries ids and reasons, never names.** `Membership.display_name` reads
through to `auth.User`, and in all three retention cases the login was deliberately *not* scrubbed —
so rendering it would put an erased person's real name back on the screen of the agency that erased
them. That list is passed as `.values(...)` rows so the name is structurally unreachable from the
template rather than merely unrendered.

- [ ] **Step 1: Write the failing tests**

Append to `tests/audit/test_deletion_views.py`:

```python
@pytest.fixture
def owner_client(client, agency_a, domain_a, django_user_model):
    """A logged-in, MFA-verified OWNER at agency A. Owners are staff, so
    TenantMembershipMiddleware requires a verified device.
    """
    from apps.tenancy.models import Membership
    from tests.conftest import verify_mfa_session

    user = django_user_model.objects.create_user(username="owner-a")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.OWNER)
    client.force_login(user)
    verify_mfa_session(client, user)
    return client


def _held(agency, student, review_reason="APPLICATIONS_IN_FLIGHT"):
    with tenant_scope(agency.id):
        return DeletionRequest.objects.create(
            tenant=agency,
            student=student,
            state="RETENTION_REVIEW",
            review_reason=review_reason,
        )


def test_the_console_lists_held_requests(owner_client, agency_a, domain_a, membership_a):
    held = _held(agency_a, membership_a)

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert [r.id for r in response.context["held"]] == [held.id]


def test_the_console_lists_requests_counting_down(
    owner_client, agency_a, domain_a, membership_a
):
    """The APPROVED list is the agency's only notification that a student is
    leaving -- no email exists in this codebase.
    """
    _policy(agency_a)
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        from apps.audit.deletion import advance_deletion

        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    assert [r.id for r in response.context["counting_down"]] == [request.id]


def test_the_partial_erasure_list_carries_no_name(
    owner_client, agency_a, domain_a, membership_a
):
    """A retained identity is by definition unscrubbed, so rendering the
    student's name would put an erased person's real name back on the screen
    of the agency that erased them. The rows are .values() dicts, so the name
    is unreachable from the template rather than merely unrendered.
    """
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a,
            student=membership_a,
            state="EXECUTED",
            identity_retained=True,
            identity_retained_reason="STILL_ENROLLED",
        )

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    rows = list(response.context["partially_erased"])
    assert len(rows) == 1
    assert rows[0]["identity_retained_reason"] == "STILL_ENROLLED"
    assert "student" not in rows[0], "the row can reach a Membership, and so a name"


def test_a_counselor_cannot_reach_the_console(
    client, agency_a, domain_a, counselor_user, counselor_membership
):
    """Criterion 9, the role half."""
    from tests.conftest import verify_mfa_session

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.get("/owner/deletions/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


def test_an_owner_cannot_see_another_agencys_requests(
    owner_client, agency_a, agency_b, domain_a, membership_b
):
    """Criterion 9, the tenant half."""
    _held(agency_b, membership_b)

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    assert list(response.context["held"]) == []


def test_releasing_a_held_request_starts_the_clock(
    owner_client, agency_a, domain_a, membership_a
):
    _policy(agency_a)
    held = _held(agency_a, membership_a)

    response = owner_client.post(
        f"/owner/deletions/{held.id}/release/", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        held.refresh_from_db()
    assert held.state == "APPROVED"
    assert held.execute_after is not None
    assert held.review_reason == "APPLICATIONS_IN_FLIGHT", (
        "the reason a request was held is the record of why, and survives release"
    )


def test_refusing_a_held_request_denies_it(owner_client, agency_a, domain_a, membership_a):
    held = _held(agency_a, membership_a, review_reason="LEGAL_HOLD")

    response = owner_client.post(f"/owner/deletions/{held.id}/deny/", HTTP_HOST=domain_a.host)

    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        held.refresh_from_db()
    assert held.state == "DENIED"


def test_the_owners_actions_are_audited_against_the_owner(
    owner_client, agency_a, domain_a, membership_a
):
    """Criterion 13. Every human transition carries the acting membership."""
    from apps.funding.models import AuditEvent

    _policy(agency_a)
    held = _held(agency_a, membership_a)

    owner_client.post(f"/owner/deletions/{held.id}/release/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.get(object_id=held.id, event="deletion.released")
        owner = Membership.objects.get(user__username="owner-a")
    assert event.actor_id == owner.id
    assert event.actor_kind == "HUMAN"


def test_an_owner_cannot_release_another_agencys_request(
    owner_client, agency_a, agency_b, domain_a, membership_b
):
    """The tenant boundary on the write, not only on the read."""
    victim = _held(agency_b, membership_b)

    response = owner_client.post(
        f"/owner/deletions/{victim.id}/release/", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 404
    with tenant_scope(agency_b.id):
        victim.refresh_from_db()
    assert victim.state == "RETENTION_REVIEW"


def test_the_console_actions_are_not_reachable_by_GET(
    owner_client, agency_a, domain_a, membership_a
):
    held = _held(agency_a, membership_a)
    assert (
        owner_client.get(
            f"/owner/deletions/{held.id}/release/", HTTP_HOST=domain_a.host
        ).status_code
        == 405
    )
```

Add `Membership` to the module's imports at the top of the file:

```python
from apps.tenancy.models import Membership
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/audit/test_deletion_views.py -q -k "console or releasing or refusing or owners_actions or another_agencys"
```

Expected: every one fails with 404 — the URLs do not exist.

- [ ] **Step 3: Write the stub template**

Create `tests/templates/audit/deletion_console.html`:

```html
{# Test stub. See tests/templates/README.md -- deliberately renders nothing. #}
```

- [ ] **Step 4: Add the two services**

Append to `apps/audit/console.py`:

```python
def release_deletion(*, request: DeletionRequest, owner: Membership) -> DeletionRequest:
    """An owner lets a held request proceed. The thirty-day clock starts now.

    review_reason is deliberately NOT cleared: it is the record of why the
    request was held, and this event says who released it. Clearing it would
    leave a released request indistinguishable from one that was never held.

    The caller checks that `request` belongs to the owner's tenant; this writes
    the audit row that says who acted.
    """
    released = advance_deletion(request, "APPROVED")
    AuditEvent.objects.create(
        tenant_id=owner.tenant_id,
        actor=owner,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="deletion.released",
        object_id=request.id,
    )
    return released


def deny_deletion(*, request: DeletionRequest, owner: Membership) -> DeletionRequest:
    """An owner refuses a held request. Nothing is erased and the student stays
    locked out until they restore it themselves -- DENIED is an open state for
    exactly that reason (see views.OPEN_DELETION_STATES).
    """
    denied = advance_deletion(request, "DENIED")
    AuditEvent.objects.create(
        tenant_id=owner.tenant_id,
        actor=owner,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="deletion.denied",
        object_id=request.id,
    )
    return denied
```

Both put `advance_deletion` before the audit write, for the same reason `cancel_deletion` does: a
refused transition must raise before a row claims something happened.

- [ ] **Step 5: Write the three views**

In `apps/audit/views.py`, extend the console import:

```python
from .console import (
    applications_in_flight,
    cancel_deletion,
    deny_deletion,
    release_deletion,
    request_deletion,
)
```

Append:

```python
@login_required
def deletion_console(request: HttpRequest) -> HttpResponse:
    """The owner's three lists. The only exit from RETENTION_REVIEW.

    There is no agency work queue in this codebase and no email anywhere in it,
    so this screen is both the queue and the notification: without it a held
    request is seen by nobody while the student has been told their records are
    being kept, and an agency learns a student is leaving only by looking.
    """
    current_membership(request, Membership.Role.OWNER)
    return render(
        request,
        "audit/deletion_console.html",
        {
            "held": DeletionRequest.objects.filter(state="RETENTION_REVIEW").select_related(
                "student"
            ),
            "counting_down": DeletionRequest.objects.filter(state="APPROVED").order_by(
                "execute_after"
            ),
            # .values() rather than model rows, deliberately. A retained
            # identity is by definition unscrubbed, so a Membership in the
            # template can reach display_name -> auth.User and put an erased
            # person's real name back on the screen of the agency that erased
            # them. The reason is what the agency has to act on; two of the
            # three cases are misconfigurations to fix rather than people to
            # look up, and the audit trail carries the identity for anyone with
            # a lawful need for it.
            "partially_erased": DeletionRequest.objects.filter(
                state="EXECUTED", identity_retained=True
            ).values("id", "student_id", "identity_retained_reason", "created_at"),
        },
    )


@login_required
@require_POST
def release_deletion_request(request: HttpRequest, request_id: str) -> HttpResponse:
    owner = current_membership(request, Membership.Role.OWNER)
    # The manager is tenant-scoped, so this 404s on another agency's request
    # rather than acting on it. state= pins the action to a held request: an
    # APPROVED one is already counting down and advance_deletion would refuse
    # it with a 500 rather than a 404.
    record = get_object_or_404(DeletionRequest, id=request_id, state="RETENTION_REVIEW")
    release_deletion(request=record, owner=owner)
    return redirect("audit-deletion-console")


@login_required
@require_POST
def deny_deletion_request(request: HttpRequest, request_id: str) -> HttpResponse:
    owner = current_membership(request, Membership.Role.OWNER)
    record = get_object_or_404(DeletionRequest, id=request_id, state="RETENTION_REVIEW")
    deny_deletion(request=record, owner=owner)
    return redirect("audit-deletion-console")
```

- [ ] **Step 6: Add the routes**

In `apps/audit/urls.py`, extend the import and append three paths:

```python
from .views import (
    deletion_console,
    deletion_pending,
    deny_deletion_request,
    release_deletion_request,
    request_account_deletion,
    restore_account,
)
```

```python
    path("owner/deletions/", deletion_console, name="audit-deletion-console"),
    path(
        "owner/deletions/<uuid:request_id>/release/",
        release_deletion_request,
        name="audit-release-deletion",
    ),
    path(
        "owner/deletions/<uuid:request_id>/deny/",
        deny_deletion_request,
        name="audit-deny-deletion",
    ),
```

- [ ] **Step 7: Verify, then run the full suite**

```bash
uv run pytest tests/audit/test_deletion_views.py -q
uv run pytest -q
```

Expected: 27 passed in the file; 2242 passed overall.

- [ ] **Step 8: Commit**

```bash
git add apps/audit/console.py apps/audit/views.py apps/audit/urls.py \
        tests/templates/audit/deletion_console.html tests/audit/test_deletion_views.py
git commit -m "feat(audit): the owner's deletion console

RETENTION_REVIEW finally has an exit. Three lists: requests held for a
decision, requests counting down, and erasures that kept a login alive.

Each of the three exists for a reason that is easy to miss. There is no
agency work queue in this codebase, so without the first list a held
request is seen by nobody while the student has been told their records
are being kept. There is no email anywhere in this codebase, so the
second list is how an agency learns a student is leaving, in time to act
on it. And after an erasure the student is gone and cannot be told
anything, so the third list is the only audience a partial erasure has.

That third list is passed as .values() rows, not model instances. A
retained identity is by definition unscrubbed, so a Membership reachable
from the template reaches display_name and auth.User -- putting an
erased person's real name back on the screen of the agency that erased
them. The reason is what the agency acts on.

review_reason survives release: it is the record of why the request was
held, and the audit event says who released it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 5: Update `CLAUDE.md`, then run the full CI gate

**Files:** `CLAUDE.md`

**Why `CLAUDE.md` changes here:** its "Erasure: the schedule is deferred" section already states
that `apps/audit/management/commands/execute_due_erasures.py` "is built and tested". That was
written in `cd58bae` and merged in PR #70, while the file did not exist — a reader would have
assumed erasures could be run by hand today. Task 2 makes the claim true. The only edit needed is
to the *owner screen* sentence, which must stop describing slice 3 as unbuilt.

- [ ] **Step 1: Correct the record**

In `CLAUDE.md`, the "Erasure: the schedule is deferred" section is now accurate as written — verify
it, and add one line after the paragraph naming `EuropassCanaryRule`:

```markdown
The owner console (`/owner/deletions/`) is the only exit from `RETENTION_REVIEW` and the only place a
partial erasure is reported. `apps/audit/views.py::deletion_console` passes that list as `.values()`
rows on purpose: a retained identity is unscrubbed, so a `Membership` reachable from the template
reaches `display_name` and puts an erased person's real name back on the agency's screen. Do not
"improve" it into `select_related("student")`.
```

- [ ] **Step 2: Run every check CI runs**

```bash
export POSTGRES_DB=tehsil_erasure_console
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
```

- [ ] **Step 3: Confirm the numbers**

Expected: all static gates clean, **exactly one new migration** (`0009_one_open_deletion_request`,
from Task 1 — `makemigrations --check` must report no *further* changes), and pytest at
**2242 passed / 45 skipped / 8 deselected**. A lower pass count means a test was deleted rather
than updated.

- [ ] **Step 4: Report, do not claim**

Paste actual output. If a check cannot run, say which, why, and what is unverified.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: the owner console, and why its partial-erasure list carries no names

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

## What this slice deliberately does not do

- **No EventBridge rule.** The deployment gate in `CLAUDE.md` covers it. Model it on
  `EuropassCanaryRule` in `infra/template.yaml` when there is something deployed to run it against.
- **No email.** This codebase sends none, anywhere. The locked screen and the `APPROVED` list are
  the notifications.
- **No agency-initiated erasure.** An agency closing its account is a different operation over a
  different subject.
- **No markup.** Stubs render nothing; the presentation layer is chosen later by
  `spec-to-site-orchestrator`.

## After this slice

The erasure console is complete against its spec's Enforcement list. The one thing standing between
it and a real student is the schedule: **the EventBridge rule must exist before the first real
student reaches this flow**, or every request becomes an indefinite lockout with no erasure, and
every screen says the right thing while it happens.
