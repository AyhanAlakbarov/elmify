# Erasure Console — Slice 2: The Student Flow

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `advance_deletion` its first caller — a student clicking "Delete my account" — and lock the account for the thirty-day window without locking them out of the screen that undoes it.

**Architecture:** A new `apps/audit/console.py` holds the lifecycle service: `request_deletion` creates the `DeletionRequest`, audits it, checks for applications in flight, and walks the request to `APPROVED` or leaves it in `RETENTION_REVIEW`; `cancel_deletion` reverses it. Three thin views in `apps/audit/views.py` gate on `current_membership(..., STUDENT)` and call those services. One check in `TenantMembershipMiddleware` redirects a locked student to the pending screen, exempting the two URLs they need to get out.

**Tech Stack:** Django 5.2 LTS on Python 3.14, PostgreSQL 17 with row-level security, pytest + pytest-django, uv.

**Spec:** `docs/superpowers/specs/2026-09-10-erasure-console-design.md`
**Predecessor:** `docs/superpowers/plans/2026-09-11-erasure-console-slice-1.md` (merged as PR #70 — `CANCELLED`, `execute_after`, `reason`, `review_reason`, `identity_retained_reason`, `Pseudonym`)

## Global Constraints

- **Work in the worktree `.claude/worktrees/erasure-console`, on branch `claude/erasure-console`.** PR #70 is open against it; these commits join that PR.
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
- **Run the FULL suite, never just `tests/audit/`.** Slice 1 shipped two defects that scoped runs hid: a `TenantScopedModel` with no RLS policy, and migrations pinned to the wrong `tenancy` dependency. Both were caught only by `tests/tenancy/` and `tests/migrations/`.
- **Template stubs render nothing.** `tests/templates/README.md` is explicit: a test needing specific markup to pass is asserting presentation — mark it `@pytest.mark.frontend` (skipped while `templates/` is absent) rather than enriching the stub. Behaviour tests assert status codes, redirects and `response.context`.
- **No new model fields in this slice.** Everything needed landed in slice 1. A migration appearing here means something went wrong.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP
  ```

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `apps/audit/console.py` | the deletion lifecycle a human drives: request, cancel | create |
| `apps/audit/views.py` | three student-facing views, role-gated and rate-limited | create |
| `apps/audit/urls.py` | their routes | create |
| `config/urls.py` | include them | modify |
| `apps/tenancy/middleware.py` | the lock | modify |
| `tests/templates/audit/deletion_pending.html` | stub | create |
| `tests/audit/test_console.py` | the service | create |
| `tests/audit/test_deletion_views.py` | the views, the lock, the rate limit | create |

**Why a new module rather than `apps/audit/services.py`:** that file's docstring scopes it to dossier assembly for `exports.py`. The deletion lifecycle is a different concern with different callers, and `apps/audit/` already splits by responsibility — `deletion.py`, `redaction.py`, `identity.py`, `exports.py`.

---

### Task 1: `request_deletion` — the service and the in-flight check

**Files:**
- Create: `apps/audit/console.py`, `tests/audit/test_console.py`

**Interfaces:**
- Consumes: `apps.audit.deletion.advance_deletion`, `DeletionBlocked`; `apps.audit.models.DeletionRequest`; `apps.portals.models.Application`; `apps.funding.models.AuditEvent`.
- Produces: `request_deletion(*, student: Membership, reason: str) -> DeletionRequest`. Returns the request in `APPROVED` when nothing blocks, or `RETENTION_REVIEW` with `review_reason` set when something does. Always writes one `deletion.requested` `AuditEvent`.

**The rule this encodes:** a student with an application at `SUBMITTED` or `CONFIRMED` has work sitting with a university right now. Thirty days later `ApplicationStep.detail` and every document are redacted, and the agency can no longer act on it, contact them, or answer a request for documents. Neither existing guard catches this — `legal_hold` is a manual flag nobody sets, and the `RetentionPolicy` check only asserts a policy row exists.

- [ ] **Step 1: Write the failing tests**

Create `tests/audit/test_console.py`:

```python
"""The lifecycle a human drives. advance_deletion holds the mechanics."""

import pytest
from django.utils import timezone

from apps.audit.console import request_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _policy(agency):
    RetentionPolicy.objects.create(tenant=agency, version=1, effective_at=timezone.now())


def test_an_ordinary_request_reaches_approved_with_a_date(agency_a, membership_a):
    """The one-click flow: nothing in flight, nothing held, clock running."""
    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(
            student=membership_a, reason=DeletionRequest.Reason.SWITCHING_AGENCY
        )

    assert request.state == "APPROVED"
    assert request.execute_after is not None
    assert request.review_reason == ""
    assert request.reason == "SWITCHING_AGENCY"


@pytest.mark.parametrize("in_flight", ["SUBMITTED", "CONFIRMED"])
def test_an_application_in_flight_diverts_to_review(agency_a, membership_a, in_flight):
    """A student with work at a university does not get the one-click path.

    Thirty days later ApplicationStep.detail and every document are redacted,
    and the agency can no longer act on the application, contact the applicant
    or answer a request for documents. The student is told, and a human
    decides.
    """
    from apps.portals.models import Application, PortalForm

    with tenant_scope(agency_a.id):
        _policy(agency_a)
        form = PortalForm.objects.create(portal_host="tum.de", form_key="msc")
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=membership_a.id,
            portal_form=form,
            state=in_flight,
        )
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)

    assert request.state == "RETENTION_REVIEW"
    assert request.review_reason == "APPLICATIONS_IN_FLIGHT"
    assert request.execute_after is None, "a held request waits on a human, not a clock"


def test_a_finished_application_does_not_divert(agency_a, membership_a):
    """PREPARING is not in flight -- nothing has been sent anywhere."""
    from apps.portals.models import Application, PortalForm

    with tenant_scope(agency_a.id):
        _policy(agency_a)
        form = PortalForm.objects.create(portal_host="tum.de", form_key="msc")
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=membership_a.id,
            portal_form=form,
            state="PREPARING",
        )
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.OTHER)

    assert request.state == "APPROVED"


def test_a_legal_hold_diverts_to_review(agency_a, membership_a):
    """advance_deletion raises DeletionBlocked; the service records why."""
    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(
            student=membership_a,
            reason=DeletionRequest.Reason.PRIVACY,
            _legal_hold_for_test=True,
        )

    assert request.state == "RETENTION_REVIEW"
    assert request.review_reason == "LEGAL_HOLD"


def test_a_missing_retention_policy_diverts_to_review(agency_a, membership_a):
    """No policy row is an agency configuration gap, not a student problem."""
    with tenant_scope(agency_a.id):
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)

    assert request.state == "RETENTION_REVIEW"
    assert request.review_reason == "NO_RETENTION_POLICY"


def test_the_request_is_audited_even_when_it_is_diverted(agency_a, membership_a):
    """deletion.requested is written before the walk, so a held request still
    records that the student asked. Without that, a diverted request looks like
    something the agency invented.
    """
    with tenant_scope(agency_a.id):
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)
        events = list(AuditEvent.objects.filter(object_id=request.id))

    assert [e.event for e in events] == ["deletion.requested"]
    assert events[0].actor_id == membership_a.id
    assert events[0].actor_kind == "HUMAN"
```

Note the `_legal_hold_for_test` keyword: `legal_hold` has no writer anywhere in the codebase, so there is no legitimate way to set it. Implement it as a keyword-only argument with a leading underscore and a docstring saying so — see Step 3.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
export POSTGRES_DB=tehsil_erasure_console
uv run pytest tests/audit/test_console.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'apps.audit.console'`.

- [ ] **Step 3: Write the service**

Create `apps/audit/console.py`:

```python
"""The deletion lifecycle a human drives. apps/audit/deletion.py holds the mechanics.

advance_deletion is an engine: it validates transitions and performs the
erasure. What belongs here is the product policy around it -- who may ask, what
blocks a request, and what gets recorded when someone asks. Keeping the two
apart is why the engine has no notion of an application in flight.

Design: docs/superpowers/specs/2026-09-10-erasure-console-design.md
"""

from apps.funding.models import AuditEvent
from apps.portals.models import Application
from apps.tenancy.models import Membership

from .deletion import DeletionBlocked, advance_deletion
from .models import DeletionRequest

#: An application at either of these is sitting with an institution right now.
#: PREPARING and READY_TO_SUBMIT have been sent nowhere, and the BLOCKED_*
#: states are stalled rather than in flight.
IN_FLIGHT_STATES = (Application.State.SUBMITTED, Application.State.CONFIRMED)


def applications_in_flight(student: Membership) -> int:
    """How many of this student's applications are sitting with an institution."""
    return Application.objects.filter(student=student, state__in=IN_FLIGHT_STATES).count()


def request_deletion(
    *,
    student: Membership,
    reason: str,
    _legal_hold_for_test: bool = False,
) -> DeletionRequest:
    """Record a student's erasure request and start the clock, or divert it.

    Returns the request in APPROVED when nothing blocks -- the thirty-day
    window is then running and the scheduler will erase. Returns it in
    RETENTION_REVIEW with review_reason set when something does, which puts it
    on the owner screen for a human instead of on a clock.

    `_legal_hold_for_test` exists because nothing in this codebase writes
    DeletionRequest.legal_hold: it is set out of band, by whoever receives a
    preservation order. Tests need the diverted path reachable; production
    never passes it.
    """
    request = DeletionRequest.objects.create(
        tenant_id=student.tenant_id,
        student=student,
        state="REQUESTED",
        reason=reason,
        legal_hold=_legal_hold_for_test,
    )
    # Before the walk, so a request that is diverted still records that the
    # student asked. Without it a held request looks like something the agency
    # invented.
    AuditEvent.objects.create(
        tenant_id=student.tenant_id,
        actor=student,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="deletion.requested",
        object_id=request.id,
    )

    advance_deletion(request, "RETENTION_REVIEW")

    # Product policy, deliberately not in the engine. Neither existing guard
    # catches this: legal_hold is a manual flag nobody sets, and the
    # RetentionPolicy check only asserts a policy row exists.
    if applications_in_flight(student):
        return _hold(request, DeletionRequest.ReviewReason.APPLICATIONS_IN_FLIGHT)

    try:
        return advance_deletion(request, "APPROVED")
    except DeletionBlocked:
        # The engine refused. Which of its two guards fired decides what the
        # student is told and what the owner has to do about it.
        blocked_by = (
            DeletionRequest.ReviewReason.LEGAL_HOLD
            if request.legal_hold
            else DeletionRequest.ReviewReason.NO_RETENTION_POLICY
        )
        return _hold(request, blocked_by)


def _hold(request: DeletionRequest, review_reason: str) -> DeletionRequest:
    """Leave the request in RETENTION_REVIEW, saying why.

    execute_after stays NULL: a held request waits on a human, not a clock, and
    the scheduler's execute_after__lte filter must never match it.
    """
    request.review_reason = review_reason
    request.save(update_fields=["review_reason"])
    return request
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/audit/test_console.py -q
```

Expected: 7 passed. If `PortalForm.objects.create(...)` raises on a missing field, read `apps/portals/models.py::PortalForm` and supply what it requires — do not change the assertion.

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest -q
```

Expected: 2197 + 7 = 2204 passed, 45 skipped, 8 deselected.

- [ ] **Step 6: Commit**

```bash
git add apps/audit/console.py tests/audit/test_console.py
git commit -m "feat(audit): record a student's erasure request, and divert it when work is in flight

request_deletion is the product policy around advance_deletion: who may
ask, what blocks a request, what gets recorded. The engine stays
mechanics, which is why it has no notion of an application in flight.

A student with an application at SUBMITTED or CONFIRMED has work sitting
with an institution. Thirty days later ApplicationStep.detail and every
document are redacted and the agency can no longer act on it, contact
them, or answer a request for documents. Neither existing guard catches
that: legal_hold is a manual flag nobody sets and the RetentionPolicy
check only asserts a row exists. Those requests divert to
RETENTION_REVIEW for a human.

deletion.requested is written before the walk, so a diverted request
still records that the student asked rather than looking like something
the agency invented.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 2: `cancel_deletion` — restore

**Files:**
- Modify: `apps/audit/console.py`, `tests/audit/test_console.py`

**Interfaces:**
- Consumes: Task 1's module.
- Produces: `cancel_deletion(*, request: DeletionRequest, student: Membership) -> DeletionRequest` — moves the request to `CANCELLED` and writes `deletion.cancelled`. Raises `DeletionBlocked` from `EXECUTED`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/audit/test_console.py`:

```python
def test_a_student_can_cancel_their_own_request(agency_a, membership_a):
    from apps.audit.console import cancel_deletion

    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.OTHER)
        cancelled = cancel_deletion(request=request, student=membership_a)

    assert cancelled.state == "CANCELLED"


def test_cancelling_is_audited_against_the_student(agency_a, membership_a):
    from apps.audit.console import cancel_deletion

    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.OTHER)
        cancel_deletion(request=request, student=membership_a)
        events = [e.event for e in AuditEvent.objects.filter(object_id=request.id)]

    assert events == ["deletion.requested", "deletion.cancelled"]


def test_an_executed_request_cannot_be_cancelled(agency_a, membership_a):
    """Nothing left to restore. advance_deletion's table already says so; this
    pins that the service does not route around it.
    """
    from apps.audit.console import cancel_deletion
    from apps.audit.deletion import DeletionBlocked

    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="EXECUTED"
        )
        with pytest.raises(DeletionBlocked):
            cancel_deletion(request=request, student=membership_a)
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/audit/test_console.py -q -k "cancel or executed_request"
```

Expected: FAIL, `ImportError: cannot import name 'cancel_deletion'`.

- [ ] **Step 3: Implement**

Append to `apps/audit/console.py`:

```python
def cancel_deletion(*, request: DeletionRequest, student: Membership) -> DeletionRequest:
    """Undo a request before it executes. Nothing was erased, so nothing is restored.

    The lock lifts because the middleware's query stops matching -- a property
    of having one source of truth rather than a feature that had to be built.

    Raises DeletionBlocked from EXECUTED, where there is nothing left to
    restore. The caller is responsible for checking that `request` belongs to
    `student`; this writes the audit row that says who did it.
    """
    cancelled = advance_deletion(request, "CANCELLED")
    AuditEvent.objects.create(
        tenant_id=student.tenant_id,
        actor=student,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="deletion.cancelled",
        object_id=request.id,
    )
    return cancelled
```

Note the ordering: `advance_deletion` first, so a refused transition raises before an audit row claims something happened.

- [ ] **Step 4: Verify, then run the full suite**

```bash
uv run pytest tests/audit/test_console.py -q
uv run pytest -q
```

Expected: 10 passed in the file; 2207 passed overall.

- [ ] **Step 5: Commit**

```bash
git add apps/audit/console.py tests/audit/test_console.py
git commit -m "feat(audit): let a student cancel their own deletion request

Nothing was erased, so nothing is restored -- the lock lifts because the
middleware's query stops matching, which is a property of having one
source of truth rather than a feature.

advance_deletion runs before the audit write, so a refused transition
raises before a row claims something happened. EXECUTED has no exit and
the service does not route around that.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 3: The three views

**Files:**
- Create: `apps/audit/views.py`, `apps/audit/urls.py`, `tests/templates/audit/deletion_pending.html`, `tests/audit/test_deletion_views.py`
- Modify: `config/urls.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: three URL names — `audit-request-account-deletion` (`POST /student/account/delete/`), `audit-deletion-pending` (`GET /student/account/deletion/`), `audit-restore-account` (`POST /student/account/restore/`). The pending view renders `audit/deletion_pending.html` with context keys `request_record`, `in_flight`.

**Paths follow the repo's role-prefixed scheme** (`/student/`, `/counselor/`, `/owner/` in `apps/concierge/urls.py`), not a bare `/account/`.

- [ ] **Step 1: Write the failing tests**

Create `tests/audit/test_deletion_views.py`:

```python
"""Server behaviour of the deletion flow: authorization, ownership, rate limit.

Markup assertions carry @pytest.mark.frontend and are skipped while templates/
is absent -- tests/templates/README.md forbids enriching a stub to make a test
pass.
"""

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


def _policy(agency):
    with tenant_scope(agency.id):
        RetentionPolicy.objects.create(tenant=agency, version=1, effective_at=timezone.now())


def test_a_student_requests_deletion(client, agency_a, domain_a, user_a, membership_a):
    _policy(agency_a)
    client.force_login(user_a)
    response = client.post(
        "/student/account/delete/", {"reason": "SWITCHING_AGENCY"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.get(student=membership_a)
    assert request.state == "APPROVED"


def test_the_reason_must_be_one_of_the_choices(client, agency_a, domain_a, user_a, membership_a):
    """The view is the trust boundary. The CheckConstraint behind it would turn
    free text into a 500; this turns it into a 400 and writes nothing.
    """
    _policy(agency_a)
    client.force_login(user_a)
    response = client.post(
        "/student/account/delete/",
        {"reason": "jon@gmail.com moving to Berlin"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 400
    with tenant_scope(agency_a.id):
        assert not DeletionRequest.objects.filter(student=membership_a).exists()


def test_deletion_cannot_be_requested_by_GET(client, agency_a, domain_a, user_a, membership_a):
    _policy(agency_a)
    client.force_login(user_a)
    response = client.get("/student/account/delete/", HTTP_HOST=domain_a.host)
    assert response.status_code == 405


def test_a_counselor_cannot_use_the_student_flow(
    client, agency_a, domain_a, counselor_user, counselor_membership
):
    """Erasure is a student right. A counselor offboarding is another operation."""
    from tests.conftest import verify_mfa_session

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.post(
        "/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 403


def test_a_student_cannot_restore_another_students_request(
    client, agency_a, domain_a, user_a, membership_a, django_user_model
):
    """The ownership check, and the reason it matters: cancelling is not
    destructive, but it silently keeps alive data somebody asked to have
    deleted.
    """
    from apps.tenancy.models import Membership

    _policy(agency_a)
    other_user = django_user_model.objects.create_user(username="other-student")
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT
        )
        victim = DeletionRequest.objects.create(
            tenant=agency_a, student=other, state="APPROVED"
        )

    client.force_login(user_a)
    response = client.post(
        f"/student/account/restore/{victim.id}/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404
    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.get(id=victim.id).state == "APPROVED"


def test_a_student_restores_their_own_request(
    client, agency_a, domain_a, user_a, membership_a
):
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.get(student=membership_a)

    response = client.post(
        f"/student/account/restore/{request.id}/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.get(id=request.id).state == "CANCELLED"


def test_the_request_endpoint_is_rate_limited(
    client, agency_a, domain_a, user_a, membership_a
):
    """The limiter bounds the cancel-and-retry loop, which is the only way to
    reach this endpoint repeatedly.

    Task 4's lock means a student with an open request is redirected away from
    here entirely, so the lock is the primary bound and this limiter is what
    caps someone cycling delete/restore -- two audit rows per turn. The test
    cancels between attempts for exactly that reason; written without the
    cancel it passes before the lock exists and breaks the moment it lands.
    """
    _policy(agency_a)
    client.force_login(user_a)

    codes = []
    for _ in range(7):
        codes.append(
            client.post(
                "/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host
            ).status_code
        )
        with tenant_scope(agency_a.id):
            DeletionRequest.objects.filter(student=membership_a).exclude(
                state__in=("CANCELLED", "EXECUTED")
            ).update(state="CANCELLED")

    assert 429 in codes, f"no request was refused: {codes}"


def test_the_pending_screen_shows_the_request(
    client, agency_a, domain_a, user_a, membership_a
):
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)

    response = client.get("/student/account/deletion/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert response.context["request_record"].state == "APPROVED"
    assert response.context["request_record"].execute_after is not None


def test_the_pending_screen_404s_without_a_request(
    client, agency_a, domain_a, user_a, membership_a
):
    client.force_login(user_a)
    response = client.get("/student/account/deletion/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/audit/test_deletion_views.py -q
```

Expected: every test fails with 404 — the URLs do not exist.

- [ ] **Step 3: Write the stub template**

Create `tests/templates/audit/deletion_pending.html`:

```html
{# Test stub. See tests/templates/README.md -- deliberately renders nothing. #}
```

- [ ] **Step 4: Write the views**

Create `apps/audit/views.py`:

```python
"""The student's own erasure flow. Three views, all gated on their own membership.

apps/audit/console.py holds the lifecycle; these are the trust boundary around
it -- they check the role, check that the request belongs to the caller, and
cap the rate.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.ratelimit import rate_limited
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .console import applications_in_flight, cancel_deletion, request_deletion
from .models import DeletionRequest

#: Requesting an erasure writes a row, an audit event, and starts an
#: irreversible thirty-day clock. Five an hour is generous for a decision
#: nobody makes twice.
_REQUEST_RATE_LIMIT = 5
_REQUEST_RATE_WINDOW_SECONDS = 3600

#: Every state except CANCELLED and EXECUTED. DENIED is open: the agency
#: refused the erasure so nothing was erased, but the student asked to leave
#: and their access stays closed until they restore it themselves. EXECUTED
#: needs no entry -- advance_deletion has set Membership.active = False, so
#: middleware.py finds no membership and never reaches the lock.
OPEN_DELETION_STATES = ("REQUESTED", "RETENTION_REVIEW", "APPROVED", "DENIED")


@login_required
@require_POST
def request_account_deletion(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    if rate_limited(
        "account-deletion",
        student.id,
        limit=_REQUEST_RATE_LIMIT,
        window_seconds=_REQUEST_RATE_WINDOW_SECONDS,
    ):
        return HttpResponse("Too many requests. Try again shortly.", status=429)

    reason = request.POST.get("reason", "")
    # The view is the trust boundary. DeletionRequest carries a CheckConstraint
    # on this column, so an unvalidated value would reach the database and come
    # back as a 500 -- and choices= alone validates nothing, since .create()
    # never calls full_clean().
    if reason not in DeletionRequest.Reason.values:
        return HttpResponseBadRequest("Choose a reason from the list.")

    request_deletion(student=student, reason=reason)
    return redirect("audit-deletion-pending")


@login_required
def deletion_pending(request: HttpRequest) -> HttpResponse:
    """The one screen a student with an open request can reach."""
    student = current_membership(request, Membership.Role.STUDENT)
    record = get_object_or_404(
        DeletionRequest, student=student, state__in=OPEN_DELETION_STATES
    )
    return render(
        request,
        "audit/deletion_pending.html",
        {"request_record": record, "in_flight": applications_in_flight(student)},
    )


@login_required
@require_POST
def restore_account(request: HttpRequest, request_id: str) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    # student=student is the ownership check, and it is the whole security of
    # this endpoint: without it one student could cancel another's erasure.
    # Not destructive, but it silently keeps alive data somebody asked to have
    # deleted.
    record = get_object_or_404(DeletionRequest, id=request_id, student=student)
    cancel_deletion(request=record, student=student)
    return redirect("concierge-student-dashboard")
```

Create `apps/audit/urls.py`:

```python
from django.urls import path

from .views import deletion_pending, request_account_deletion, restore_account

urlpatterns = [
    path(
        "student/account/delete/",
        request_account_deletion,
        name="audit-request-account-deletion",
    ),
    path("student/account/deletion/", deletion_pending, name="audit-deletion-pending"),
    path(
        "student/account/restore/<uuid:request_id>/",
        restore_account,
        name="audit-restore-account",
    ),
]
```

In `config/urls.py`, add to `urlpatterns` after the concierge include:

```python
    path("", include("apps.audit.urls")),
```

- [ ] **Step 5: Verify, then run the full suite**

```bash
uv run pytest tests/audit/test_deletion_views.py -q
uv run pytest -q
```

Expected: 9 passed in the file; 2216 passed overall.

- [ ] **Step 6: Commit**

```bash
git add apps/audit/views.py apps/audit/urls.py config/urls.py \
        tests/templates/audit/deletion_pending.html tests/audit/test_deletion_views.py
git commit -m "feat(audit): student-facing delete, pending and restore views

advance_deletion now has a caller. The views are the trust boundary
around apps/audit/console.py: role gate, ownership check, rate limit.

The reason is validated against Reason.values in the view, because
choices= validates nothing on .create() and the CheckConstraint behind
it would turn free text into a 500 instead of a 400.

student=student on the restore lookup is the whole security of that
endpoint. Without it one student could cancel another's erasure -- not
destructive, but it silently keeps alive data somebody asked to have
deleted.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 4: The lock

**Files:**
- Modify: `apps/tenancy/middleware.py`, `tests/audit/test_deletion_views.py`

**Interfaces:**
- Consumes: Task 3's URL names and `OPEN_DELETION_STATES`.
- Produces: a student with an open `DeletionRequest` is redirected to `audit-deletion-pending` from every path except the pending screen and the restore endpoint.

- [ ] **Step 1: Write the failing tests**

Append to `tests/audit/test_deletion_views.py`:

```python
def test_a_locked_student_is_redirected_away_from_everything(
    client, agency_a, domain_a, user_a, membership_a
):
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)

    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/student/account/deletion/"


def test_the_lock_does_not_trap_the_student_on_the_way_out(
    client, agency_a, domain_a, user_a, membership_a
):
    """The pending screen and restore must stay reachable, or the lock is a
    one-way door and the thirty-day window is decorative.
    """
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        record = DeletionRequest.objects.get(student=membership_a)

    assert client.get("/student/account/deletion/", HTTP_HOST=domain_a.host).status_code == 200
    restored = client.post(
        f"/student/account/restore/{record.id}/", HTTP_HOST=domain_a.host
    )
    assert restored.status_code == 302
    assert restored["Location"] != "/student/account/deletion/"


def test_cancelling_lifts_the_lock(client, agency_a, domain_a, user_a, membership_a):
    """Nothing is undone -- the middleware's query simply stops matching."""
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        record = DeletionRequest.objects.get(student=membership_a)
    client.post(f"/student/account/restore/{record.id}/", HTTP_HOST=domain_a.host)

    assert client.get("/student/", HTTP_HOST=domain_a.host).status_code == 200


def test_a_counselor_is_never_locked(
    client, agency_a, domain_a, counselor_user, counselor_membership
):
    """The lock reads a student's own request. Staff have none, and the query
    must not run for them at all.
    """
    from tests.conftest import verify_mfa_session

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    assert client.get("/counselor/", HTTP_HOST=domain_a.host).status_code == 200
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/audit/test_deletion_views.py -q -k "locked or trap or lifts"
```

Expected: the first three FAIL — `/student/` returns 200 rather than redirecting.

- [ ] **Step 3: Implement the lock**

In `apps/tenancy/middleware.py`, add to the imports:

```python
from django.shortcuts import redirect
from django.urls import reverse
```

Add beside `_MFA_SETUP_PATH`:

```python
#: The two paths a student with an open deletion request must still reach.
#: Without them the lock is a one-way door and the thirty-day reversal window
#: is decorative. Same shape as _MFA_SETUP_PATH above.
_DELETION_EXEMPT_PREFIXES = ("/student/account/deletion/", "/student/account/restore/")


def deletion_lock_target(membership: Membership) -> str | None:
    """Where to send a student whose account is scheduled for deletion, or None.

    One .exists() per authenticated student request, on the
    (tenant, student, state) index added for it. Deliberately a query rather
    than a denormalised flag on Membership: a flag would be a second source of
    truth for DeletionRequest.state and drifts in both directions -- left set
    after a cancellation it locks a student out permanently, and cleared while
    the request is still APPROVED it lets someone be erased mid-session.

    # ponytail: add the flag only if this is ever measured to matter.
    """
    from apps.audit.models import DeletionRequest
    from apps.audit.views import OPEN_DELETION_STATES

    if membership.role != Membership.Role.STUDENT:
        return None
    if not DeletionRequest.objects.filter(
        student=membership, state__in=OPEN_DELETION_STATES
    ).exists():
        return None
    return reverse("audit-deletion-pending")
```

In `TenantMembershipMiddleware.__call__`, after the `require_staff_mfa` block:

```python
            if request.path != _MFA_SETUP_PATH:
                # require_staff_mfa already raises PermissionDenied; letting it
                # propagate is what reaches templates/403.html.
                require_staff_mfa(request.user, membership.role)
            if not request.path.startswith(_DELETION_EXEMPT_PREFIXES):
                target = deletion_lock_target(membership)
                if target is not None:
                    return redirect(target)
        return self.get_response(request)
```

The import of `apps.audit` is inside the function deliberately: `apps/tenancy` is imported by `apps/audit` at module level, and a module-level import here would be a cycle.

- [ ] **Step 4: Verify, then run the full suite**

```bash
uv run pytest tests/audit/test_deletion_views.py -q
uv run pytest -q
```

Expected: 13 passed in the file; 2220 passed overall. **A failure elsewhere in the suite is the interesting outcome** — this middleware runs on every authenticated request, so any test with a student and a `DeletionRequest` fixture now behaves differently. Read those failures rather than adjusting the lock.

- [ ] **Step 5: Commit**

```bash
git add apps/tenancy/middleware.py tests/audit/test_deletion_views.py
git commit -m "feat(tenancy): lock a student whose account is scheduled for deletion

Every page redirects to the pending screen, except the pending screen
and restore -- without those exemptions the lock is a one-way door and
the thirty-day window is decorative. Same shape as the _MFA_SETUP_PATH
exemption above it.

Deliberately a query rather than a flag on Membership. A flag is a
second source of truth for DeletionRequest.state and drifts both ways:
left set after a cancellation it locks a student out permanently, and
cleared while the request is still APPROVED it lets someone be erased
mid-session. One .exists() on the index slice 1 added for it.

Cancelling lifts the lock because the query stops matching. Nothing is
undone because nothing was done.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 5: Run the full CI gate

**Files:** none.

- [ ] **Step 1: Run every check CI runs**

```bash
export POSTGRES_DB=tehsil_erasure_console
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
```

- [ ] **Step 2: Confirm the numbers**

Expected: all static gates clean, **no new migrations** (this slice adds no model fields — one appearing means something went wrong), and pytest at 2220 passed / 45 skipped / 8 deselected. A lower pass count means a test was deleted rather than updated.

- [ ] **Step 3: Report, do not claim**

Paste actual output. If a check cannot run, say which, why, and what is unverified.

---

## What this slice deliberately does not do

- **No owner screen.** `RETENTION_REVIEW` still has no exit — slice 3.
- **No management command and no EventBridge rule.** Nothing reaches `EXECUTED` on a clock yet; the deployment gate in `CLAUDE.md` covers it.
- **No `deletion.released` / `deletion.denied` audit events** — those are written by the owner screen.
- **No markup.** Stubs render nothing; the presentation layer is chosen later by `spec-to-site-orchestrator`.

## Follow-on

**Slice 3 — the command and the owner screen:** `execute_due_erasures` with one transaction per erasure and `select_for_update`, its RLS test behind `rls_enforced_orm`, and the owner screen's three lists (held, counting down, partially erased).
