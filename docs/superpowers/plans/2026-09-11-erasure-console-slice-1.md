# Erasure Console — Slice 1: Model and Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the already-shipped erasure engine with the state, fields and return values the operator console needs, without giving it a caller yet.

**Architecture:** `apps/audit/deletion.py::advance_deletion` already erases a student and writes `EXECUTED`; nothing calls it. This slice adds a `CANCELLED` transition, four fields on `DeletionRequest`, a reason instead of a bare boolean from `redact_identity`, and an empty `Pseudonym` table whose foreign-key contract is the GDPR deletion-propagation guarantee for future derived data. Every change is exercised by calling `advance_deletion` directly, which is how the engine is tested today. No views, no URLs, no management command.

**Tech Stack:** Django 5.2 LTS on Python 3.14, PostgreSQL 17 with row-level security, pytest + pytest-django, uv for dependency and task running, ruff + mypy + bandit as blocking gates.

**Spec:** `docs/superpowers/specs/2026-09-10-erasure-console-design.md`

## Global Constraints

- **Work in the worktree `.claude/worktrees/erasure-console`, on branch `claude/erasure-console`.** The main checkout at `/home/orkhan/Desktop/tehsil_agent` holds unrelated uncommitted changes and must not be touched.
- **Set `POSTGRES_DB` to a name unique to this worktree before running tests:** `export POSTGRES_DB=tehsil_erasure_console`. The default `tehsil` produces the shared `test_tehsil` database, which wedges when another session runs tests at the same time.
- **Never run `ruff format`.** This repository is lint-only; `ruff format` rewrites 26 unrelated files.
- **The full gate, exactly as CI runs it** (`.github/workflows/ci.yml`):
  ```
  uv run ruff check .
  uv run mypy apps config
  uv run bandit -c pyproject.toml -r apps config
  uv run python manage.py check
  uv run python manage.py makemigrations --check --dry-run
  uv run pytest -q
  ```
  `makemigrations --check --dry-run` means **every model change needs its migration committed in the same task.**
- **Any new field on a student-reachable model must be classified in `apps/audit/redaction.py` in the same task**, or `tests/audit/test_redaction_classification.py::test_every_reachable_field_is_classified_exactly_once` fails. That failure is the enforcement working — never route around it.
- **`advance_deletion` is shipped, tested code on a GDPR path.** Add to it; do not restructure it.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP
  ```

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `apps/audit/deletion.py` | the state machine and the erasure orchestration | modify: `_TRANSITIONS`, `DELETION_WINDOW`, `execute_after` write, identity reason, `Pseudonym` delete |
| `apps/audit/models.py` | `DeletionRequest`, `RetentionPolicy` | modify: four fields, one index; add `Pseudonym` |
| `apps/audit/identity.py` | the login scrub and its cross-tenant guard | modify: `IdentityRetention`, `redact_identity` return type |
| `apps/audit/redaction.py` | the classification map | modify: `KEEP` entries |
| `apps/audit/migrations/0004_*.py` … `0007_*.py` | schema | create: one per model-changing task |
| `tests/audit/test_deletion.py` | transitions and the window | modify |
| `tests/audit/test_identity.py` | identity classification and scrub | modify: 7 call sites |
| `tests/audit/test_identity_rls.py` | the guard under real RLS | modify: 2 call sites |
| `tests/audit/test_pseudonym.py` | the cascade contract | create |

---

### Task 1: `CANCELLED` as a transition target

**Files:**
- Modify: `apps/audit/deletion.py:13-17`
- Test: `tests/audit/test_deletion.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `advance_deletion(request, "CANCELLED")` valid from `REQUESTED`, `RETENTION_REVIEW`, `APPROVED`, `DENIED`. `CANCELLED` and `EXECUTED` are terminal.

- [ ] **Step 1: Write the failing tests**

Append to `tests/audit/test_deletion.py`:

```python
@pytest.mark.django_db
@pytest.mark.parametrize("start", ["REQUESTED", "RETENTION_REVIEW", "APPROVED", "DENIED"])
def test_a_request_can_be_cancelled_from_any_non_terminal_state(agency_a, membership_a, start):
    """Restore is the student's way out, and DENIED is included deliberately.

    A request the agency refused leaves the student locked out but not erased;
    without this transition they would have no way back into their account.
    """
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state=start
        )
    assert advance_deletion(request, "CANCELLED").state == "CANCELLED"


@pytest.mark.django_db
@pytest.mark.parametrize("terminal", ["CANCELLED", "EXECUTED"])
def test_terminal_states_have_no_exit(agency_a, membership_a, terminal):
    """A cancelled or executed request is finished. Nothing moves it again."""
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state=terminal
        )
    for target in ("REQUESTED", "RETENTION_REVIEW", "APPROVED", "DENIED", "EXECUTED"):
        with pytest.raises(DeletionBlocked):
            advance_deletion(request, target)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
export POSTGRES_DB=tehsil_erasure_console
uv run pytest tests/audit/test_deletion.py -q -k "cancelled or terminal"
```

Expected: the `cancelled` cases FAIL with `DeletionBlocked: cannot move from REQUESTED to CANCELLED`. The `terminal` cases already pass — they pin behaviour that must survive the next step.

- [ ] **Step 3: Add `CANCELLED` to the transition table**

In `apps/audit/deletion.py`, replace `_TRANSITIONS`:

```python
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
```

No other change. `CANCELLED` falls through to the function's existing tail — `request.state = target_state; request.save(...)` — which is all it needs.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/audit/test_deletion.py -q
```

Expected: PASS, including the pre-existing transition tests.

- [ ] **Step 5: Commit**

```bash
git add apps/audit/deletion.py tests/audit/test_deletion.py
git commit -m "feat(audit): allow a deletion request to be cancelled

Restore is the student's way out of the thirty-day window, and DENIED is
included so a student whose erasure the agency refused is not stranded
behind a lock with no way back in.

CANCELLED needs no key in the table -- an absent key is already an empty
set of exits, which is what makes EXECUTED terminal today.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 2: `execute_after` and the thirty-day window

**Files:**
- Modify: `apps/audit/models.py` (`DeletionRequest`), `apps/audit/deletion.py`, `apps/audit/redaction.py:119`
- Create: `apps/audit/migrations/0004_deletionrequest_execute_after.py`
- Test: `tests/audit/test_deletion.py`

**Interfaces:**
- Consumes: Task 1's `_TRANSITIONS`.
- Produces: `apps.audit.deletion.DELETION_WINDOW` (a `datetime.timedelta` of 30 days); `DeletionRequest.execute_after: datetime | None`, set by `advance_deletion` on the `APPROVED` transition and **persisted**.

- [ ] **Step 1: Write the failing test**

Append to `tests/audit/test_deletion.py` (add `from datetime import timedelta` and `from django.utils import timezone` to the imports):

```python
@pytest.mark.django_db
def test_approval_stores_the_execution_date_on_the_row(agency_a, membership_a):
    """Reloaded from the database, not read off the in-memory object.

    advance_deletion saves with update_fields, which drops an assigned field
    that is not named there -- silently, with no error. An in-memory assertion
    cannot see that, and the failure it hides is an APPROVED request whose
    execute_after is NULL, which the scheduler's execute_after__lte filter
    never matches: an erasure that never runs, for a student who was shown a
    date.
    """
    with tenant_scope(agency_a.id):
        RetentionPolicy.objects.create(
            tenant=agency_a, version=1, effective_at="2026-01-01T00:00:00Z"
        )
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="RETENTION_REVIEW"
        )
    before = timezone.now()
    advance_deletion(request, "APPROVED")

    with tenant_scope(agency_a.id):
        stored = DeletionRequest.objects.get(id=request.id)
    assert stored.execute_after is not None
    assert stored.execute_after - before >= timedelta(days=29, hours=23)
    assert stored.execute_after - before <= timedelta(days=30, minutes=1)


@pytest.mark.django_db
def test_a_request_that_never_reaches_approved_has_no_execution_date(agency_a, membership_a):
    """A held request is waiting on a human, not on a clock."""
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
    advance_deletion(request, "RETENTION_REVIEW")

    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.get(id=request.id).execute_after is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/audit/test_deletion.py -q -k execution_date
```

Expected: FAIL with `AttributeError` or `FieldError` — `DeletionRequest` has no `execute_after`.

- [ ] **Step 3: Add the field**

In `apps/audit/models.py`, inside `DeletionRequest`, after `identity_retained`:

```python
    #: When the erasure becomes due. Stored rather than computed from
    #: created_at + DELETION_WINDOW, because the student was shown a specific
    #: date and changing the window later must never move a date someone has
    #: already seen. NULL until the request reaches APPROVED.
    execute_after = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 4: Write the window and the save**

In `apps/audit/deletion.py`, add to the imports:

```python
from datetime import timedelta

from django.utils import timezone
```

Add the constant below the imports:

```python
#: How long a student has to change their mind. Thirty days, matching the large
#: consumer products; GDPR's one month limits *responding*, which happens at the
#: click. A longer window is a longer chance to undo something that cannot be
#: undone afterwards.
DELETION_WINDOW = timedelta(days=30)
```

In the `APPROVED` branch, after the two existing guards:

```python
        if target_state == "APPROVED":
            if request.legal_hold:
                raise DeletionBlocked("legal hold prevents deletion")
            if not RetentionPolicy.objects.filter(tenant_id=request.tenant_id).exists():
                raise DeletionBlocked("no approved retention policy exists")
            # After the guards, so a refused approval leaves no date behind.
            request.execute_after = timezone.now() + DELETION_WINDOW
```

Change the function's tail so the field is actually written:

```python
        request.state = target_state
        # execute_after is in update_fields for every transition, not just
        # APPROVED: omitting it would drop the assignment above with no error.
        # For the others it rewrites the value the row already holds.
        request.save(update_fields=["state", "execute_after"])
    return request
```

- [ ] **Step 5: Classify the field**

In `apps/audit/redaction.py`, extend the `KEEP` entry:

```python
    "audit.DeletionRequest": (
        "state",
        "legal_hold",
        "identity_retained",
        "created_at",
        # The date the student was told. It is the record of what was erased
        # and when, which must survive the erasure it describes.
        "execute_after",
    ),
```

- [ ] **Step 6: Generate the migration**

```bash
uv run python manage.py makemigrations audit -n deletionrequest_execute_after
```

Expected: creates `apps/audit/migrations/0004_deletionrequest_execute_after.py` with one `AddField`.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/audit/test_deletion.py tests/audit/test_redaction_classification.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/audit/models.py apps/audit/deletion.py apps/audit/redaction.py \
        apps/audit/migrations/0004_deletionrequest_execute_after.py tests/audit/test_deletion.py
git commit -m "feat(audit): store the erasure date on approval

Thirty days, in one constant. The date is stored rather than computed
from created_at, because the student is shown a specific date and
changing the window later must not move a date someone has seen.

update_fields gains execute_after for every transition, not only
APPROVED: it drops an assigned field silently otherwise, and the failure
that hides is an APPROVED request with a NULL date that the scheduler's
execute_after__lte filter never matches -- an erasure that never runs.
The test reloads from the database for that reason.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 3: The student's reason and the review reason

**Files:**
- Modify: `apps/audit/models.py` (`DeletionRequest`), `apps/audit/redaction.py`
- Create: `apps/audit/migrations/0005_deletionrequest_reasons.py`
- Test: `tests/audit/test_deletion.py`

**Interfaces:**
- Consumes: Task 2's `DeletionRequest`.
- Produces: `DeletionRequest.Reason` and `DeletionRequest.ReviewReason` (both `models.TextChoices`); fields `reason` and `review_reason`; an index on `("tenant", "student", "state")` that slice 2's middleware lock depends on.

- [ ] **Step 1: Write the failing test**

Append to `tests/audit/test_deletion.py`:

```python
@pytest.mark.django_db
def test_the_reason_is_a_fixed_choice_and_never_free_text(agency_a, membership_a):
    """Free text from a student is personal data that would itself need
    redacting. A fixed list avoids the problem and still gives the agency a
    usable "why students leave" signal.
    """
    from django.core.exceptions import ValidationError

    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a,
            student=membership_a,
            state="REQUESTED",
            reason=DeletionRequest.Reason.SWITCHING_AGENCY,
        )
        request.full_clean()

        request.reason = "I am moving to Berlin and my counselor was unhelpful"
        with pytest.raises(ValidationError):
            request.full_clean()


@pytest.mark.django_db
def test_a_held_request_records_why_it_was_held(agency_a, membership_a):
    """review_reason is what the owner screen displays; without it a held
    request is a row nobody can act on.
    """
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a,
            student=membership_a,
            state="RETENTION_REVIEW",
            review_reason=DeletionRequest.ReviewReason.APPLICATIONS_IN_FLIGHT,
        )
        request.full_clean()
        assert DeletionRequest.objects.get(id=request.id).review_reason == "APPLICATIONS_IN_FLIGHT"


@pytest.mark.django_db
def test_the_lock_query_is_indexed(agency_a):
    """Slice 2's middleware runs this on every authenticated student request."""
    index_fields = [tuple(index.fields) for index in DeletionRequest._meta.indexes]
    assert ("tenant", "student", "state") in index_fields
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/audit/test_deletion.py -q -k "fixed_choice or was_held or indexed"
```

Expected: FAIL — `DeletionRequest` has no `Reason`, `ReviewReason`, `reason`, `review_reason`, and no index.

- [ ] **Step 3: Add the choices, the fields and the index**

In `apps/audit/models.py`, inside `DeletionRequest`, above `id`:

```python
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
```

After `execute_after`:

```python
    #: Why the student is leaving. A fixed list and never free text: free text
    #: from a student is personal data that would itself need redacting, and a
    #: list still gives the agency the signal it wants.
    reason = models.CharField(max_length=30, choices=Reason.choices, blank=True)
    #: Why the request stopped in RETENTION_REVIEW. This is what the owner
    #: screen shows, and it is not cleared on release -- a released request
    #: must stay distinguishable from one that was never held.
    review_reason = models.CharField(max_length=30, choices=ReviewReason.choices, blank=True)
```

Extend the model's `Meta` (it currently has only `constraints`):

```python
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
```

- [ ] **Step 4: Classify both fields**

In `apps/audit/redaction.py`, extend the `KEEP` entry to:

```python
    "audit.DeletionRequest": (
        "state",
        "legal_hold",
        "identity_retained",
        "created_at",
        "execute_after",
        # A fixed choice, not free text -- it names a category, never a person.
        "reason",
        "review_reason",
    ),
```

- [ ] **Step 5: Generate the migration**

```bash
uv run python manage.py makemigrations audit -n deletionrequest_reasons
```

Expected: `apps/audit/migrations/0005_deletionrequest_reasons.py` with two `AddField` and one `AddIndex`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/audit/test_deletion.py tests/audit/test_redaction_classification.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/audit/models.py apps/audit/redaction.py \
        apps/audit/migrations/0005_deletionrequest_reasons.py tests/audit/test_deletion.py
git commit -m "feat(audit): record why a student leaves and why a request is held

Both are fixed choices. Free text from a student is personal data that
would itself need redacting, and a list still carries the signal an
agency wants from it.

review_reason is what the owner screen displays, and it is never cleared
on release -- erasing it would leave a released request
indistinguishable from one that was never held.

The index serves slice 2's middleware, which asks whether a student has
an open request on every authenticated request. One indexed .exists()
beats a flag on Membership: that would be a second source of truth for
DeletionRequest.state and would drift in both directions.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 4: `redact_identity` returns a reason, not a boolean

**Files:**
- Modify: `apps/audit/identity.py`, `apps/audit/deletion.py`, `apps/audit/models.py`, `apps/audit/redaction.py`
- Create: `apps/audit/migrations/0006_deletionrequest_identity_retained_reason.py`
- Test: `tests/audit/test_identity.py` (7 call sites), `tests/audit/test_identity_rls.py` (2 call sites)

**Interfaces:**
- Consumes: Task 3's `DeletionRequest`.
- Produces: `apps.audit.identity.IdentityRetention` (a `models.TextChoices` with members `STILL_ENROLLED`, `STAFF_ACCOUNT`, `NOT_A_STUDENT`); `redact_identity(*, user_id, membership_role) -> IdentityRetention | None`, where `None` means the login was scrubbed; `DeletionRequest.identity_retained_reason: str`.

**Why this exists:** `identity_retained=True` today conflates a lawful retention (the person is still a student elsewhere — nothing to do) with two misconfigurations (a Django staff account, a non-student membership — someone must look). Those need different words on a screen and different responses from a human. After erasure the student is gone, so the agency's owner screen is the only audience this fact ever has.

- [ ] **Step 1: Write the failing test**

Append to `tests/audit/test_identity.py`:

```python
def test_the_three_retention_cases_are_distinguishable(agency_a, django_user_model):
    """identity_retained=True means three different things, two of which are
    somebody's mistake. A bare boolean cannot tell an agency which.
    """
    from apps.audit.identity import IdentityRetention, redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        staff = django_user_model.objects.create_user(
            username="staff-person", email="staff@example.test", password="pw", is_staff=True
        )
        counselor = django_user_model.objects.create_user(
            username="a-counselor", email="c@example.test", password="pw"
        )

        assert (
            redact_identity(user_id=staff.id, membership_role=Membership.Role.STUDENT)
            is IdentityRetention.STAFF_ACCOUNT
        )
        assert (
            redact_identity(user_id=counselor.id, membership_role=Membership.Role.COUNSELOR)
            is IdentityRetention.NOT_A_STUDENT
        )


def test_a_scrubbed_login_returns_none(agency_a, django_user_model):
    """None is the "it was erased" answer, so `retention is not None` is the
    flag advance_deletion records.
    """
    from apps.audit.identity import redact_identity
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create_user(
            username="leaving", email="leaving@example.test", password="pw"
        )
        assert redact_identity(user_id=user.id, membership_role=Membership.Role.STUDENT) is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/audit/test_identity.py -q -k "three_retention or returns_none"
```

Expected: FAIL with `ImportError: cannot import name 'IdentityRetention'`.

- [ ] **Step 3: Change the return type**

In `apps/audit/identity.py`, add `from django.db import models` to the imports, and add above `redact_identity`:

```python
class IdentityRetention(models.TextChoices):
    """Why a login survived an erasure. Three cases, two of them a mistake.

    STILL_ENROLLED is lawful and expected -- the person holds an active
    membership at another agency and their login has to keep working. The
    other two mean somebody misconfigured something and a human must look.
    Collapsing them into one boolean puts a misconfiguration and a normal
    outcome behind the same word on the owner screen.
    """

    STILL_ENROLLED = "STILL_ENROLLED", "Still active at another agency"
    STAFF_ACCOUNT = "STAFF_ACCOUNT", "Account holds Django staff or superuser rights"
    NOT_A_STUDENT = "NOT_A_STUDENT", "The erased membership was not a student"
```

Change the signature and the three early returns. The order of the guards does not change:

```python
def redact_identity(*, user_id: Any, membership_role: str) -> IdentityRetention | None:
    """Scrub the login unless the person is still active somewhere. Deletes no rows.

    Returns None when the identity was scrubbed, and an IdentityRetention when
    it was deliberately retained. The caller records that as
    DeletionRequest.identity_retained plus identity_retained_reason: an erasure
    that leaves the person identifiable must say so, and say which of the three
    reasons applies.

    Call this AFTER the erased membership has been deactivated -- the guard
    below counts active memberships and the erased one must not be among them.
    """
    from apps.tenancy.models import Membership

    user = get_user_model()._default_manager.get(pk=user_id)
    if membership_role != Membership.Role.STUDENT:
        return IdentityRetention.NOT_A_STUDENT
    if user.is_staff or user.is_superuser:
        return IdentityRetention.STAFF_ACCOUNT
```

Leave the `SECURITY DEFINER` block and its comment **exactly as they are** — that comment documents the most dangerous line in the module. Change only its outcome:

```python
    if still_enrolled:
        return IdentityRetention.STILL_ENROLLED
```

And the tail:

```python
    user.totpdevice_set.all().delete()  # type: ignore[attr-defined]
    return None
```

- [ ] **Step 4: Add the field and classify it**

In `apps/audit/models.py`, after `review_reason`:

```python
    #: Which of IdentityRetention's three cases left the login alive. Blank
    #: when identity_retained is False. The owner screen shows this, never the
    #: person's name: a retained identity is by definition unscrubbed, so
    #: rendering display_name would put an erased person's real name back on
    #: the screen of the agency that erased them.
    identity_retained_reason = models.CharField(max_length=20, blank=True)
```

Its choices deliberately live on `IdentityRetention` in `identity.py` rather than being duplicated here; `apps/audit/models.py` must not import `identity.py`, which imports `apps.tenancy.models`.

In `apps/audit/redaction.py`, add `"identity_retained_reason"` to the `KEEP["audit.DeletionRequest"]` tuple.

- [ ] **Step 5: Record the reason in `advance_deletion`**

In `apps/audit/deletion.py`, replace the identity block inside the `EXECUTED` branch. Keep the surrounding comment about `False` meaning a deliberate retention, updated for the new type:

```python
                # None means the login was scrubbed. An IdentityRetention means
                # it was deliberately kept, and says which of three reasons --
                # one lawful, two a misconfiguration someone must fix.
                # Recording both is what keeps EXECUTED honest.
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
```

- [ ] **Step 6: Update the nine existing call sites**

These tests assert on the old boolean and will fail. Change each assertion, keeping the test's meaning:

| File:line | Was | Becomes |
|---|---|---|
| `tests/audit/test_identity.py:65` | `assert redact_identity(...)` | `assert redact_identity(...) is None` |
| `tests/audit/test_identity.py:111` | `scrubbed = redact_identity(...)` | `scrubbed = redact_identity(...) is None` |
| `tests/audit/test_identity.py:146` | `scrubbed = redact_identity(...)` | `scrubbed = redact_identity(...) is None` |
| `tests/audit/test_identity.py:177` | `... is False` | `... is IdentityRetention.STILL_ENROLLED` |
| `tests/audit/test_identity.py:197` | `... is False` | `... is IdentityRetention.STAFF_ACCOUNT` |
| `tests/audit/test_identity.py:217` | `... is False` | `... is IdentityRetention.NOT_A_STUDENT` |
| `tests/audit/test_identity_rls.py:55` | `scrubbed = redact_identity(...)` | `scrubbed = redact_identity(...) is None` |
| `tests/audit/test_identity_rls.py:77` | `scrubbed = redact_identity(...)` | `scrubbed = redact_identity(...) is None` |

Read each test before editing it: lines 177, 197 and 217 assert a *specific* refusal, so pick the member matching what that test sets up rather than the row above. Add `IdentityRetention` to each file's imports.

**Do not weaken `tests/audit/test_identity_rls.py`.** Those two run behind the `rls_enforced_orm` fixture and are the only tests that can observe the cross-tenant guard actually working; the assertion changes shape, never strength.

- [ ] **Step 7: Generate the migration**

```bash
uv run python manage.py makemigrations audit -n deletionrequest_identity_retained_reason
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
uv run pytest tests/audit/ -q
uv run mypy apps config
```

Expected: PASS, and mypy clean — the return-type change is the reason mypy runs here rather than only at the end.

- [ ] **Step 9: Commit**

```bash
git add apps/audit/identity.py apps/audit/deletion.py apps/audit/models.py \
        apps/audit/redaction.py apps/audit/migrations/0006_*.py \
        tests/audit/test_identity.py tests/audit/test_identity_rls.py
git commit -m "feat(audit): say which of three reasons kept a login alive

identity_retained=True conflates a lawful retention -- the person is
still a student at another agency, nothing to do -- with two
misconfigurations: a Django staff account and a non-student membership,
both of which someone has to look at. Those need different words and
different responses.

redact_identity returns IdentityRetention | None, None meaning scrubbed,
so identity_retained stays exactly what it was and the reason is
additive. After an erasure the student is gone, so the agency's owner
screen is the only audience this fact will ever have.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 5: `Pseudonym` and the cascade contract

**Files:**
- Modify: `apps/audit/models.py`, `apps/audit/deletion.py`, `apps/audit/redaction.py`
- Create: `apps/audit/migrations/0007_pseudonym.py`, `tests/audit/test_pseudonym.py`

**Interfaces:**
- Consumes: Task 4's `advance_deletion`.
- Produces: `apps.audit.models.Pseudonym` — a random UUID primary key, `tenant`, a `OneToOneField` to `Membership` named `student`, and `created_at`. `advance_deletion` deletes the row for the erased student on the `EXECUTED` path.

**Why an empty table ships:** the delete path has to exist before the data does. `documents.EuropassRenderCache` is already in this repository storing a digest derived from a student's CV with no FK back to them, so the erasure completeness test cannot see it and it survives erasures today — nobody decided that; nobody was thinking about deletion when it was written. See the "Derived data and the ML corpus" section of `CLAUDE.md`.

- [ ] **Step 1: Write the failing tests**

Create `tests/audit/test_pseudonym.py`:

```python
"""Pseudonym is an empty table whose foreign key is a GDPR guarantee.

Derived and ML data references a student through Pseudonym and never through
Membership. Erasure deletes the Pseudonym row and the database removes the
derived rows with it -- propagation enforced by the schema rather than by a
policy comment someone can forget. See CLAUDE.md, "Derived data and the ML
corpus", and docs/superpowers/specs/2026-09-10-erasure-console-design.md.
"""

import pytest
from django.apps import apps as django_apps
from django.db import models
from django.db.models import ForeignKey, OneToOneField
from django.utils import timezone

from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, Pseudonym, RetentionPolicy
from apps.tenancy.context import tenant_scope


def test_every_foreign_key_to_pseudonym_cascades():
    """The whole propagation guarantee is one on_delete argument.

    Passes vacuously today because nothing references Pseudonym yet, and that
    is exactly its job: it fails on the day someone adds the first derived
    table with SET_NULL or PROTECT, which would leave a row describing an
    erased person behind. SET_NULL becomes correct only for a schema that has
    passed the re-identification assessment in `phased requirements.md` §6.1,
    and nothing has.
    """
    offenders = []
    for model in django_apps.get_models():
        for field in model._meta.get_fields():
            if not isinstance(field, (ForeignKey, OneToOneField)):
                continue
            if field.related_model is not Pseudonym:
                continue
            if field.remote_field.on_delete is not models.CASCADE:
                offenders.append(f"{model._meta.label}.{field.name}")
    assert not offenders, (
        f"these must be on_delete=CASCADE: {offenders}. A derived row that "
        "outlives its student is personal data the erasure did not reach."
    )


@pytest.mark.django_db
def test_pseudonym_has_no_writer_yet(agency_a):
    """The empty table is the design, not an omission.

    When the §6.1 extraction pipeline is built and starts creating rows here,
    this test fails and whoever built it must confirm three things before
    replacing the assertion:

      1. Every derived table points at Pseudonym with CASCADE, never at
         Membership directly (test above).
      2. Extraction happens during ordinary use, inside the tenant boundary.
         An erasure never manufactures a dataset.
      3. Nothing retains a derived row through an erasure until a schema has
         passed the §6.1 re-identification assessment.
    """
    with tenant_scope(agency_a.id):
        assert not Pseudonym.objects.exists()


@pytest.mark.django_db
def test_erasure_deletes_the_pseudonym(agency_a, django_user_model, monkeypatch):
    """The one thing this table does today.

    Both AWS calls on the EXECUTED path are patched, following
    tests/audit/test_deletion_purges_documents.py: unpatched,
    delete_student_portal_credentials builds a real secretsmanager client,
    which needs an ambient AWS region -- so the test passes on a laptop with
    ~/.aws/config and fails in CI, which has none.
    """
    from apps.audit import deletion
    from apps.tenancy.models import Membership

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)

    user = django_user_model.objects.create_user(username="pseudo-student")
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        RetentionPolicy.objects.create(
            tenant=agency_a, version=1, effective_at=timezone.now()
        )
        Pseudonym.objects.create(tenant=agency_a, student=student)

        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

        assert not Pseudonym.objects.filter(student_id=student.id).exists()
```

**Why the request is walked rather than created in `APPROVED`:** `advance_deletion`
writes `execute_after` on the `APPROVED` transition (Task 2), and a row inserted
straight into `APPROVED` never gets one. Walking it is also what
`tests/audit/test_deletion_purges_documents.py::_approved_request` does.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/audit/test_pseudonym.py -q
```

Expected: FAIL with `ImportError: cannot import name 'Pseudonym'`.

- [ ] **Step 3: Add the model**

In `apps/audit/models.py`, after `DeletionRequest`:

```python
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
```

- [ ] **Step 4: Delete it on the erasure path**

In `apps/audit/deletion.py`, import it with the others:

```python
from .models import DeletionRequest, Pseudonym, RetentionPolicy
```

Inside the `EXECUTED` branch's `transaction.atomic()`, after `redact_student(...)` and before the `request.student.active = False` line:

```python
                # Derived and ML rows reference the student only through this,
                # with CASCADE, so deleting it is how an erasure reaches data
                # the redaction walk never sees. Nothing writes it yet; the
                # delete exists before the data by design.
                Pseudonym.objects.filter(student_id=request.student_id).delete()
```

- [ ] **Step 5: Classify it**

In `apps/audit/redaction.py`, add to `KEEP`, beside the other `audit.` entry:

```python
    # A bare timestamp on a row the erasure deletes outright -- the pseudonym
    # itself is the primary key, which classifiable_fields() skips.
    "audit.Pseudonym": ("created_at",),
```

- [ ] **Step 6: Generate the migration**

```bash
uv run python manage.py makemigrations audit -n pseudonym
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/audit/ -q
```

Expected: PASS, including `test_redaction_classification.py`, which now sees `audit.Pseudonym` in its walk.

- [ ] **Step 8: Commit**

```bash
git add apps/audit/models.py apps/audit/deletion.py apps/audit/redaction.py \
        apps/audit/migrations/0007_pseudonym.py tests/audit/test_pseudonym.py
git commit -m "feat(audit): add Pseudonym and the cascade that erases derived data

An empty table on purpose. The delete path has to exist before the data
does -- documents.EuropassRenderCache is already here storing a digest
derived from a student's CV with no FK back to them, invisible to the
completeness test and surviving erasures today, because nobody was
thinking about deletion when it was written.

The rule: derived tables point at Pseudonym with CASCADE, never at
Membership and never SET_NULL or PROTECT. advance_deletion deletes the
row; the database removes the derived rows. A test asserts every FK to
it cascades, which passes vacuously now and fails on the day someone
adds the first one wrongly.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 6: Run the full gate

**Files:** none — this task changes nothing and exists so the slice is not declared done on a partial run.

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

Expected: ruff, mypy (275 files), bandit and `manage.py check` clean; `makemigrations --check` reports no changes; pytest reports **at least** the 2179 passed / 45 skipped / 8 deselected that master reports, plus roughly a dozen new tests. A *lower* pass count means a test was deleted rather than updated — investigate before continuing.

- [ ] **Step 3: Report, do not claim**

Paste the actual command output. If any check cannot run, say which, why, and what is therefore unverified. Never report success without the output that shows it.

---

## What this slice deliberately does not do

- **No caller.** `advance_deletion` still has none. Slice 2 adds `request_deletion`, the views and the middleware lock; slice 3 adds the management command and the owner screen.
- **No `DeletionRequest` creation path**, no rate limit, no audit events for human transitions — all slice 2.
- **No threshold, second variant or `SET_NULL`.** `phased requirements.md` §6.1 holds those for the pipeline that does not exist.
- **No EventBridge rule.** Deferred under the deployment gate in `CLAUDE.md`.

## Follow-on plans

Written after this slice lands, so they can be written against real code:

- **Slice 2 — the student flow:** `request_deletion` with the in-flight `Application` check, the three views and URLs, the `TenantMembershipMiddleware` lock, restore, `rate_limited("account-deletion", ...)`, and the four human `AuditEvent` rows.
- **Slice 3 — the command and the owner screen:** `execute_due_erasures` with one transaction per erasure and `select_for_update`, its test behind `rls_enforced_orm`, and the owner screen's three lists.
