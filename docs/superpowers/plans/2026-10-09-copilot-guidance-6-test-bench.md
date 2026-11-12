# Co-pilot Guidance 6: The Portal Test Bench — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make amber rare (spec D7, §9).
- The owner walks a real application in their own account while the co-pilot records every page.
- Repeat runs fill those saved copies offline from synthetic sample students who hit the hard cases.
- Every amber becomes a rule (a format, a dropdown synonym, a read-back equivalence, a map correction).
- A portal's map counts as verified only at zero ambers, with its login and sign-up walked and working, and then serves every tenant.
- Live learning (plan 5) records its pages too, so the bench knows which portals still wait for a walk, and a portal that changes its form goes back on that queue.

**Architecture:**
- **Records.** A new platform table, `portals.PageRecord`, holds every recorded page: its redacted, value-free snapshot, plus for bench walks a value-blanked, script-free, server-redacted HTML copy in the object store. Live learning records its page there too (snapshot only, never HTML), and LIVE_LEARN records are never replayed.
- **The operator door.** A `PLATFORM_ADMIN` of the platform agency with MFA enrolled pairs the extension from the platform dashboard. The panel then shows a bench section; "Record this page" injects the content script into the active tab (the chosen form's own origin only) and posts the page.
- **Rules.** Per-portal rules live on `PortalForm` (`value_formats`, `option_synonyms`, `readback_equivalences`, `password_rules`). The packet applies formats and synonyms server-side, and ships the equivalences so read-back accepts a harmless portal change.
- **The runner.** `manage.py portal_bench` serves the saved copies from `127.0.0.1` to headless Chromium with the built test bundle injected. It aborts every other request, never clicks, and reports ambers per sample student.
- **Promotion.** `--promote` copies a zero-amber map to a platform-shared, `verified_at`-stamped `FieldMap`, which outranks any tenant-learned map until a live relearn marks the form `needs_bench`.

**Tech Stack:** Django 5, pydantic, lxml (already a dependency), S3 via `apps/research/storage.py::S3ObjectStore`, django-otp, Playwright (sync API, as `tests/portals/test_extension_e2e.py`), TypeScript + esbuild.

**Spec:** `docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md` §9 (the bench and the verified gate), §6 and §13 (each portal's password rules and login form are recorded on the bench), §10 ("The portal changes a value after we typed it": a change the bench taught us stays green; "A portal that changed its form"), D6 and §9's last bullet (wording read in four languages). Plan 5 (`2026-10-09-copilot-guidance-5-form-learning.md`) supplies `FieldMap.slots`, `PacketHint`, `profile.field_class`, `snapshot.student_value_pattern`/`redact_student_values`, `slots.pair_slots` and the relearn this plan reacts to.

## Global Constraints

- **Order.** Branch `claude/copilot-form-learning`; execute after plan 5 (its migrations end at `0025_portal_answer`; this plan's are `0026`–`0028`).
- **Never live on a portal for samples.** The bench never creates an account for a sample student, never loads a live portal URL during a replay, and never presses Next, Submit or anything else. The runner serves only `http://127.0.0.1:<port>/...` and aborts every other request. Live checks are the owner's own account, stopped before Submit (spec §9).
- **No values in a recording.** The saved HTML copy has every input value, textarea text and selection removed, and every `<script>` removed, before it leaves the browser. The server then redacts every one of the operator's own values from the copy's text (plan 5's whole-word, three-characters-or-more pattern), and refuses a copy whose form controls still hold one. A "Welcome, Orkhan" banner is redacted, never a refusal.
- **Retention (owner, 2026-10-09, decision C).** LIVE_LEARN records keep their redacted snapshot; bench records keep their redacted HTML. Neither is ever served to any tenant view: only the operator's `portal_bench` command reads them. Student erasure does not reach `PageRecord` or the bench HTML, by owner decision, because they hold no student value by construction (a snapshot carries no value and its free text is redacted; a bench copy is the operator's own walk, blanked and redacted).
- **Operator only.** Every bench route and every `portal_bench` mode needs an active `PLATFORM_ADMIN` membership of the `research.PlatformAgency` agency whose user holds a confirmed TOTP device. That is `apps/research/views.py::_operator`'s door, adapted to a device token (Task 2); never an agency role.
- **Never across tenants.** The operator's forbidden values come from the platform tenant only (their own facts there, their name, their login email). The owner's student membership in another agency is a person's data in another tenant, which CLAUDE.md rules out; the in-browser blanking is the primary guard and the server pass is the second. The bench never reads `PortalAnswer` rows either.
- **Sample students are synthetic.** They are fixed in code and never copied from a real student.
- **Typing.** Every Python line ≤ 100 characters, `mypy --strict` clean (no bare `dict`/`list`, annotated empty containers, typed `def`s); every TS line valid for `tsc --noEmit` with `noUncheckedIndexedAccess`.
- **Commands:**
  - tests: `POSTGRES_DB=elmify_copilot_learning uv run pytest -q <paths>`;
  - browser tests: `POSTGRES_DB=elmify_copilot_learning uv run pytest -q -m extension <paths>` after `npm --prefix extension run check` (which builds `dist` and `dist-test`; the e2e suite and the runner load `dist-test`);
  - lint: `uv run ruff check .` only, never `ruff format`;
  - types: `uv run mypy apps config`;
  - migrations: `uv run python manage.py makemigrations --check --dry-run` after each migration task.
- **Never push to `master`.** Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The operator door on a device token** (Tasks 2 and 3). `is_bench_operator` needs an active `PLATFORM_ADMIN` of the platform agency **and** a confirmed TOTP device, because `require_staff_mfa` reads a verified session a device token never has. An operator pairs only from the platform host, behind the dashboard session's own MFA gate. The worker injects the content script outside a fill binding only for `bench:record`, only after the server listed forms for this device, only into the active tab on the chosen form's own origin.
2. **The owner's own values in a recording** (Tasks 2 and 3). Blanked in the browser; then redacted from the copy's text server-side as whole words, refused only when a form control still holds one, and refused above 1.5 MB (under Django's 2.5 MB body limit after JSON escaping).
3. **A saved page whose own scripts, images or styles point at the live portal.** The replay never reaches it: every non-`127.0.0.1` request is aborted and counted, and the report says so (Task 5).
4. **A verified map, a tenant-learned map and a changed portal** (Tasks 6 and 7). The verified map serves every tenant and a tenant cannot shadow it by learning again, until a live relearn marks the form `needs_bench`; then the tenant's fresh map wins and the form is on `--queue`. `_store_map` supersedes only its own scope's current row, never through `current_for`. Promotion with an amber left, or without a LOGIN and a SIGNUP record carrying password rules and `walk_ok`, is refused and writes nothing.
5. **A portal that uppercases names or reformats dates after typing** (Task 4). Once taught, read-back stays green for that portal and that field class only. Turkish names compare upper-cased on both sides ("Işıl" = "IŞIL"); a date compares as a date only when both sides read unambiguously; `digits` never matches two empty strings.

---

### Task 1: `PageRecord`, and live learning records its page

**Files:**
- Modify: `apps/portals/models.py` (new `PageRecord`)
- Create: `apps/portals/migrations/0026_page_record.py` (generated)
- Modify: `apps/portals/ext_api.py::snapshot` (writes a LIVE_LEARN record after a map is stored)
- Test: `tests/portals/test_page_record.py` (new), `tests/portals/test_ext_api.py`

**Interfaces:**
- Produces `PageRecord` (a plain platform model, no RLS, like `FieldMap`):
  - `id`; `portal_form` → `PortalForm`; `field_map` → `FieldMap` (nullable, SET_NULL);
  - `source` (`LIVE_LEARN`, `BENCH_WALK`) and `page_kind` (`FORM`, `LOGIN`, `SIGNUP`, `CONFIRMATION`, `OTHER`);
  - `step` (positive int; the page's order in a walk);
  - `snapshot` (JSON, the redacted snapshot, `page_url` reduced to its origin);
  - `html_key` (char 300, blank; BENCH only), `password_rules` (text, blank; BENCH only);
  - `walk_ok` (bool, default False: the operator confirmed this LOGIN or SIGNUP worked in the live walk, Task 6);
  - `learned_by_tenant` → `tenancy.Agency` (nullable), `created_at`.

- [ ] **Step 1: Write the failing tests.** Create `tests/portals/test_page_record.py`:

```python
import pytest


@pytest.mark.django_db
def test_a_page_record_holds_a_snapshot_and_no_value_column(agency_a) -> None:
    from apps.portals.models import PageRecord, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="rec-1")
    record = PageRecord.objects.create(
        portal_form=form, source=PageRecord.Source.LIVE_LEARN, page_kind=PageRecord.Kind.FORM,
        step=1, snapshot={"page_url": "https://apply.example.edu", "controls": []},
        learned_by_tenant=agency_a,
    )
    assert record.html_key == "" and record.password_rules == "" and record.walk_ok is False
    assert "value" not in {f.name for f in PageRecord._meta.get_fields()}
```

In `tests/portals/test_ext_api.py`, append to `test_a_snapshot_becomes_a_field_map` (`:323`), after its last assertion:

```python
    from apps.portals.models import PageRecord

    record = PageRecord.objects.get(portal_form_id=application.portal_form_id)
    assert (record.source, record.page_kind, record.learned_by_tenant_id) == (
        "LIVE_LEARN", "FORM", agency_a.id,
    )
    assert record.html_key == ""
    assert record.snapshot["page_url"] == "https://apply.example.edu"  # the origin only
```

and add a test that the stored snapshot is redacted:

```python
def test_a_live_learned_page_record_is_redacted_of_the_students_values(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    from apps.portals import ext_api
    from apps.portals.models import FieldMap, PageRecord

    monkeypatch.setattr(
        ext_api, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    monkeypatch.setattr(
        ext_api, "learn_from_snapshot",
        lambda form, snapshot, **kwargs: FieldMap.objects.create(
            portal_form=form, version=1, entries=[]
        ),
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    body = json.loads(json.dumps(SNAPSHOT_BODY))
    body["controls"][0]["context"] = "Signed in as Ada Byron"
    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot", data=json.dumps(body),
        content_type="application/json", HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 201
    record = PageRecord.objects.get(portal_form_id=application.portal_form_id)
    assert record.snapshot["controls"][0]["context"] == "Signed in as ■"
```

- [ ] **Step 2: Run; expect failure** (`ImportError: PageRecord`).

Run: `POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_page_record.py tests/portals/test_ext_api.py -k "page_record or becomes_a_field_map or live_learned"`

- [ ] **Step 3: Implement.** In `apps/portals/models.py`, after `FieldMap`:

```python
class PageRecord(models.Model):
    """One recorded portal page: what the bench replays and what verifies a map
    (spec §9, §10 "A form we have not mapped yet"). Never a value: `snapshot` is
    the redacted, value-free description, and a BENCH_WALK's HTML copy (in the
    object store under `html_key`) was blanked in the browser and redacted
    server-side (bench.py).

    Retention (owner, 2026-10-09): kept, never served to any tenant view -- only
    the operator's `portal_bench` reads it -- and not reached by a student's
    erasure, because it holds no student value by construction.
    """

    class Source(models.TextChoices):
        LIVE_LEARN = "LIVE_LEARN"
        BENCH_WALK = "BENCH_WALK"

    class Kind(models.TextChoices):
        FORM = "FORM"
        LOGIN = "LOGIN"
        SIGNUP = "SIGNUP"
        CONFIRMATION = "CONFIRMATION"
        OTHER = "OTHER"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    portal_form = models.ForeignKey(
        PortalForm, on_delete=models.CASCADE, related_name="page_records"
    )
    field_map = models.ForeignKey(
        FieldMap, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source = models.CharField(max_length=12, choices=Source.choices)
    page_kind = models.CharField(max_length=12, choices=Kind.choices)
    step = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField()
    html_key = models.CharField(max_length=300, blank=True, default="")
    password_rules = models.TextField(blank=True, default="")
    #: The operator confirmed this LOGIN or SIGNUP page worked as spec §6 says
    #: in their own live walk (`portal_bench --walk-ok`). Promotion needs both.
    walk_ok = models.BooleanField(default=False)
    learned_by_tenant = models.ForeignKey(
        "tenancy.Agency", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
```

Run `uv run python manage.py makemigrations portals -n page_record`. Pin its tenancy dependency to `("tenancy", "0002_rls")` with `0012_field_map_scope.py`'s comment (the earliest tenancy migration that creates `Agency`; `tests/migrations/test_task7_migrations.py` rolls tenancy back to 0004).

In `ext_api.py::snapshot`, bind the forbidden list before the learn call and use it there:

```python
    forbidden = [*values.values(), *addresses]
```

(`forbidden_values=forbidden`), and inside the existing `with tenant_transaction(...)` that writes the `AuditEvent`, after it:

```python
        PageRecord.objects.create(
            portal_form=application.portal_form,
            field_map=field_map,
            source=PageRecord.Source.LIVE_LEARN,
            page_kind=PageRecord.Kind.FORM,
            # Never HTML on this path: the snapshot only, origin-only URL and
            # free text redacted, exactly what the model was shown.
            snapshot=json.loads(
                redact_student_values(_page_origin(parsed), forbidden).model_dump_json()
            ),
            learned_by_tenant_id=application.tenant_id,
        )
```

Import `_page_origin` from `.learn`, `redact_student_values` from `.snapshot` and `PageRecord` from `.models`.

- [ ] **Step 4: Run; expect pass.** (Step 2 command, plus the whole of `tests/portals/test_ext_api.py`, then `uv run python manage.py makemigrations --check --dry-run`.)

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add apps/portals tests/portals
git -C /home/orkhan/Desktop/copilot-learning commit -m "feat(portals): PageRecord; every live-learned page is recorded, redacted, for the bench

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The operator door: pairing, MFA, and the recording endpoints

**Files:**
- Create: `apps/portals/bench.py` (`is_bench_operator`, `operator_forbidden_values`, `RecordingRefused`, `MAX_HTML_BYTES`, `store_bench_page`)
- Modify: `apps/portals/views.py::pairing_code` (an operator pairs from the platform host)
- Modify: `apps/portals/ext_api.py` (`bench_whoami`, `bench_portal_forms`, `bench_page`), `apps/portals/urls.py`
- Test: `tests/portals/test_bench_api.py` (new)

**Interfaces:**
- Produces:
  - `is_bench_operator(membership: Membership) -> bool`;
  - `operator_forbidden_values(operator: Membership) -> list[str]` (caller holds the platform tenant's transaction);
  - `store_bench_page(portal_form: PortalForm, *, page_kind: str, password_rules: str, snapshot: FormSnapshot, html: str, forbidden_values: list[str], step: int) -> PageRecord`, raising `RecordingRefused`;
  - routes: GET `ext/bench/whoami` → `{"operator": bool}`; GET `ext/bench/portal-forms` → `{"forms": [{"id", "portal_host", "form_url"}]}`; POST `ext/bench/portal-forms/<uuid>/pages` → 201 `{"record_id"}`.

- [ ] **Step 1: Write the failing tests.** Create `tests/portals/test_bench_api.py`:

```python
"""The bench's door: a platform operator with MFA, on a device token."""

import json

import pytest
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.tenancy.context import tenant_scope
from tests.conftest import verify_mfa_session
from tests.portals.test_ext_api import _pair

pytestmark = pytest.mark.django_db

HTML = (
    "<!doctype html><html><body><p>Welcome, Orkhan Abdullayev</p>"
    "<form><label for='gn'>First name</label><input id='gn'></form></body></html>"
)
SNAP = {"page_url": "https://apply.example.edu/p",
        "controls": [{"selector": "#gn", "tag": "input", "label": "First name"}]}


@pytest.fixture
def platform(db):
    from apps.research.models import PlatformAgency
    from apps.tenancy.models import Agency

    agency = Agency.objects.create(name="Platform")
    PlatformAgency.objects.create(agency=agency)
    return agency


@pytest.fixture
def platform_domain(platform):
    from apps.tenancy.models import TenantDomain

    return TenantDomain.objects.create(
        agency=platform, host="platform.example.test", verified_at=timezone.now()
    )


@pytest.fixture
def operator(platform, django_user_model):
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="operator", email="owner@example.org",
        first_name="Orkhan", last_name="Abdullayev",
    )
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    with tenant_scope(platform.id):
        return Membership.objects.create(
            tenant=platform, user=user, role=Membership.Role.PLATFORM_ADMIN
        )


@pytest.fixture
def operator_token(client, platform, platform_domain, operator) -> str:
    return _pair(client, platform, operator, platform_domain)


@pytest.fixture
def portal_form():
    from apps.portals.models import PortalForm

    return PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="bench-1",
        form_url="https://apply.example.edu/apply",
    )


@pytest.fixture
def bench_store(monkeypatch, fake_store):
    from apps.portals import bench

    monkeypatch.setattr(bench, "_store", lambda: fake_store)
    return fake_store


def _get(client, domain, token: str, path: str):
    return client.get(path, HTTP_HOST=domain.host, HTTP_AUTHORIZATION=f"Bearer {token}")


def _record(client, domain, token: str, form_id, body: dict[str, object]):
    return client.post(
        f"/ext/bench/portal-forms/{form_id}/pages", data=json.dumps(body),
        content_type="application/json", HTTP_HOST=domain.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_a_student_is_not_a_bench_operator(
    client, agency_a, domain_a, membership_a, portal_form
) -> None:
    token = _pair(client, agency_a, membership_a, domain_a)
    assert _get(client, domain_a, token, "/ext/bench/whoami").json() == {"operator": False}
    assert _get(client, domain_a, token, "/ext/bench/portal-forms").status_code == 403
    response = _record(client, domain_a, token, portal_form.id,
                       {"page_kind": "FORM", "snapshot": SNAP, "html": HTML})
    assert response.status_code == 403


def test_an_operator_without_mfa_or_outside_the_platform_is_not_one(
    operator, agency_a, django_user_model
) -> None:
    from apps.portals.bench import is_bench_operator
    from apps.tenancy.models import Membership

    assert is_bench_operator(operator)
    TOTPDevice.objects.filter(user=operator.user).delete()
    assert not is_bench_operator(operator)
    user = django_user_model.objects.create_user(username="padmin")
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    with tenant_scope(agency_a.id):
        ordinary = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.PLATFORM_ADMIN
        )
    assert not is_bench_operator(ordinary)  # PLATFORM_ADMIN of an ordinary agency


def test_the_operator_pairs_from_the_platform_dashboard(client, platform_domain, operator) -> None:
    client.force_login(operator.user)
    verify_mfa_session(client, operator.user)
    response = client.post("/api/extension/pairing-code", HTTP_HOST=platform_domain.host)
    assert response.status_code == 201 and response.json()["code"]


def test_the_operator_sees_the_portal_forms(
    client, platform_domain, operator_token, portal_form
) -> None:
    assert _get(client, platform_domain, operator_token, "/ext/bench/whoami").json() == {
        "operator": True,
    }
    forms = _get(client, platform_domain, operator_token, "/ext/bench/portal-forms").json()
    assert {"id": str(portal_form.id), "portal_host": "apply.example.edu",
            "form_url": "https://apply.example.edu/apply"} in forms["forms"]


def test_a_recording_is_stored_with_the_greeting_redacted(
    client, platform_domain, operator_token, portal_form, bench_store
) -> None:
    from apps.portals.models import PageRecord

    response = _record(client, platform_domain, operator_token, portal_form.id, {
        "page_kind": "SIGNUP", "password_rules": "At least 12 characters, one digit",
        "snapshot": SNAP, "html": HTML,
    })
    assert response.status_code == 201
    record = PageRecord.objects.get(id=response.json()["record_id"])
    assert (record.source, record.page_kind, record.learned_by_tenant_id, record.step) == (
        "BENCH_WALK", "SIGNUP", None, 1,
    )
    assert record.password_rules.startswith("At least 12")
    stored = bench_store.get(record.html_key).decode()
    assert "Orkhan" not in stored and "Welcome, ■" in stored and 'id="gn"' in stored
    assert record.snapshot["page_url"] == "https://apply.example.edu"


@pytest.mark.parametrize("html", [
    HTML.replace("<input id='gn'>", "<input id='gn' value='Orkhan Abdullayev'>"),
    HTML.replace("<input id='gn'>", "<textarea>owner@example.org</textarea>"),
    "<html><body>" + "x" * 1_500_001 + "</body></html>",
])
def test_a_recording_with_a_value_in_a_control_or_too_large_is_refused(
    client, platform_domain, operator_token, portal_form, bench_store, html: str
) -> None:
    from apps.portals.models import PageRecord

    response = _record(client, platform_domain, operator_token, portal_form.id,
                       {"page_kind": "FORM", "snapshot": SNAP, "html": html})
    assert (response.status_code, response.json()["error"]) == (400, "invalid_recording")
    assert not PageRecord.objects.exists()
```

- [ ] **Step 2: Run; expect 404 on the new routes and 403 on the operator's pairing code.**

Run: `POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_bench_api.py`

- [ ] **Step 3: Implement `apps/portals/bench.py`.**

```python
"""The portal test bench (spec §9): the owner's recorded walk, the offline
replay and the verified gate. Platform-only: no agency role reaches any of it."""

from __future__ import annotations

import json
import re

import lxml.html
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.research.models import PlatformAgency
from apps.research.storage import S3ObjectStore
from apps.tenancy.models import Membership

from .learn import _page_origin
from .models import PageRecord, PortalForm
from .profile import verified_values
from .snapshot import (
    FormSnapshot,
    SnapshotPIILeak,
    assert_no_student_values,
    redact_student_values,
    student_value_pattern,
)

#: 1.5 MB. The copy arrives inside a JSON body, and JSON escaping inflates HTML
#: (every quote and newline gains a backslash), so this keeps a maximal copy
#: under Django's 2.5 MB DATA_UPLOAD_MAX_MEMORY_SIZE -- the reasoning of
#: ext_api's _MAX_IMAGE_BYTES. Above Django's limit the refusal is an HTML 400
#: no JSON client can read, so a larger cap here would be dead code.
MAX_HTML_BYTES = 1_500_000


class RecordingRefused(Exception):
    """A bench recording the server will not keep."""


def _store() -> S3ObjectStore:
    return S3ObjectStore()


def is_bench_operator(membership: Membership) -> bool:
    """An active PLATFORM_ADMIN of the platform agency, with MFA enrolled.

    research/views.py::_operator's door on a device token. require_staff_mfa
    reads a VERIFIED SESSION, which a device token never has, so two things
    stand in for it: the pairing code was minted from a dashboard session that
    TenantMembershipMiddleware already held to require_staff_mfa (a
    PLATFORM_ADMIN reaches no page unverified), and the user must still hold a
    confirmed TOTP device now -- removing the device ends bench access.
    """
    return bool(
        membership.active
        and membership.role == Membership.Role.PLATFORM_ADMIN
        and PlatformAgency.objects.filter(agency_id=membership.tenant_id).exists()
        and TOTPDevice.objects.filter(user_id=membership.user_id, confirmed=True).exists()
    )


def operator_forbidden_values(operator: Membership) -> list[str]:
    """What a recording must not carry: the operator's own facts in the platform
    tenant, their name and their login email. The platform tenant only -- the
    owner's student membership in another agency is a person's data in another
    tenant (CLAUDE.md). Caller holds tenant_transaction(operator.tenant_id)."""
    user = operator.user
    found = [*verified_values(operator).values(), user.get_full_name(), user.email]
    return [value for value in found if value.strip()]


def _redacted_html(html: str, pattern: re.Pattern[str] | None) -> str:
    """The saved copy with every operator value in its text redacted.

    A value inside a form control -- an input's value attribute, a textarea's
    text, an option's value -- means the in-browser blanking failed, and is
    refused: there the value is the page's data, not its wording. A value in
    ordinary text ("Welcome, Orkhan") is the portal greeting its user, and is
    redacted the way a snapshot's free text is.
    """
    if pattern is None:
        return html
    tree = lxml.html.document_fromstring(html)
    for control in tree.iter("input", "option"):
        if pattern.search(control.get("value") or ""):
            raise RecordingRefused("a form control in the saved copy holds a value")
    for control in tree.iter("textarea"):
        if pattern.search(control.text_content() or ""):
            raise RecordingRefused("a textarea in the saved copy holds a value")
    for element in tree.iter():
        if element.text:
            element.text = pattern.sub("■", element.text)
        if element.tail:
            element.tail = pattern.sub("■", element.tail)
        for name, value in list(element.attrib.items()):
            element.set(name, pattern.sub("■", value))
    out: str = lxml.html.tostring(tree, encoding="unicode", doctype="<!doctype html>")
    return out


def store_bench_page(
    portal_form: PortalForm,
    *,
    page_kind: str,
    password_rules: str,
    snapshot: FormSnapshot,
    html: str,
    forbidden_values: list[str],
    step: int,
) -> PageRecord:
    if len(html.encode()) > MAX_HTML_BYTES:
        raise RecordingRefused("the saved copy is larger than a form page")
    try:
        redacted = redact_student_values(_page_origin(snapshot), forbidden_values)
        assert_no_student_values(redacted, forbidden_values)
    except SnapshotPIILeak as leak:
        raise RecordingRefused(str(leak)) from leak
    body = _redacted_html(html, student_value_pattern(forbidden_values)).encode()
    record = PageRecord.objects.create(
        portal_form=portal_form,
        source=PageRecord.Source.BENCH_WALK,
        page_kind=page_kind,
        step=step,
        snapshot=json.loads(redacted.model_dump_json()),
        password_rules=password_rules,
    )
    record.html_key = f"bench/{portal_form.id}/{record.id}.html"
    _store().put(record.html_key, body)
    record.save(update_fields=["html_key"])
    return record
```

- [ ] **Step 4: An operator pairs from the platform host.** In `apps/portals/views.py::pairing_code`, replace the `try: student = ... except PermissionDenied: return ...` block with:

```python
    try:
        member = current_membership(request, Membership.Role.STUDENT)
    except PermissionDenied:
        # The bench (plan 6): a platform operator pairs from the platform host.
        # This session already passed require_staff_mfa in
        # TenantMembershipMiddleware; is_bench_operator re-checks the rest.
        try:
            member = current_membership(request, Membership.Role.PLATFORM_ADMIN)
        except PermissionDenied:
            return JsonResponse({"error": "student_membership_required"}, status=403)
        if not is_bench_operator(member):
            return JsonResponse({"error": "student_membership_required"}, status=403)
    return JsonResponse({"code": issue_pairing_code(member)}, status=201)
```

and import `is_bench_operator` from `.bench`. `_device_endpoint`'s privacy gates (`needs_acceptance`, `processing_stopped`) return False for a non-student, so an operator's token passes them.

- [ ] **Step 5: The routes.** In `ext_api.py`, add (importing `Literal` is already done; import `PageRecord`, `PortalForm` from `.models`, and `RecordingRefused, is_bench_operator, operator_forbidden_values, store_bench_page` from `.bench`):

```python
#: The operator records one page at a time while walking a form; three hundred
#: an hour is far above that and far below a loop.
_BENCH_RATE_LIMIT = 300


class _BenchPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_kind: Literal["FORM", "LOGIN", "SIGNUP", "CONFIRMATION", "OTHER"]
    password_rules: str = Field(default="", max_length=2000)
    snapshot: FormSnapshot
    html: str


def _bench_operator(pairing: ExtensionPairing) -> None:
    if not is_bench_operator(pairing.membership):
        raise _ApiError(403, "not_operator")


@require_GET
@_device_endpoint
def bench_whoami(request: HttpRequest, pairing: ExtensionPairing) -> HttpResponse:
    """Whether this device may record bench pages. Never why not."""
    return JsonResponse({"operator": is_bench_operator(pairing.membership)})


@require_GET
@_device_endpoint
def bench_portal_forms(request: HttpRequest, pairing: ExtensionPairing) -> HttpResponse:
    """The forms an operator may record a walk for. Platform rows, no tenant data."""
    _bench_operator(pairing)
    forms = PortalForm.objects.exclude(form_url="").order_by("portal_host", "form_key")[:500]
    return JsonResponse(
        {
            "forms": [
                {"id": str(form.id), "portal_host": form.portal_host, "form_url": form.form_url}
                for form in forms
            ]
        }
    )


@require_POST
@_device_endpoint
def bench_page(
    request: HttpRequest, pairing: ExtensionPairing, portal_form_id: UUID
) -> HttpResponse:
    """One page of the operator's walk (spec §9). Stored redacted; refused when a
    form control still holds one of the operator's values, or when too large."""
    _bench_operator(pairing)
    _limit("ext-bench", pairing, _BENCH_RATE_LIMIT)
    portal_form = PortalForm.objects.filter(id=portal_form_id).first()
    if portal_form is None:
        raise _ApiError(404, "not_found")
    try:
        body = _BenchPage.model_validate(_json_body(request))
    except ValidationError as error:
        raise _ApiError(400, "invalid_recording") from error
    with tenant_transaction(pairing.tenant_id):
        forbidden = operator_forbidden_values(pairing.membership)
    step = 1 + PageRecord.objects.filter(
        portal_form=portal_form, source=PageRecord.Source.BENCH_WALK
    ).count()
    try:
        record = store_bench_page(
            portal_form, page_kind=body.page_kind, password_rules=body.password_rules,
            snapshot=body.snapshot, html=body.html, forbidden_values=forbidden, step=step,
        )
    except RecordingRefused as refused:
        raise _ApiError(400, "invalid_recording") from refused
    with tenant_transaction(pairing.tenant_id):
        AuditEvent.objects.create(
            tenant_id=pairing.tenant_id,
            actor=pairing.membership,
            actor_kind=AuditEvent.ActorKind.HUMAN,
            event="portal.bench_page_recorded",
            object_id=record.id,
        )
    return JsonResponse({"record_id": str(record.id)}, status=201)
```

In `urls.py`, beside the snapshot route:

```python
    path("ext/bench/whoami", ext_api.bench_whoami, name="portals-ext-bench-whoami"),
    path("ext/bench/portal-forms", ext_api.bench_portal_forms, name="portals-ext-bench-forms"),
    path(
        "ext/bench/portal-forms/<uuid:portal_form_id>/pages",
        ext_api.bench_page,
        name="portals-ext-bench-page",
    ),
```

- [ ] **Step 6: Run; expect pass.** (Step 2 command, plus `tests/portals/test_ext_api.py tests/portals/test_pairing.py`.)

- [ ] **Step 7: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add apps/portals tests/portals
git -C /home/orkhan/Desktop/copilot-learning commit -m "feat(portals): the bench's operator door -- MFA on a device token, redacted recordings, a value in a control refused

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Bench mode in the extension: record the active page, blanked of every value

A `PLATFORM_ADMIN` has no application, so no fill binding ever injects the content script for them. Bench mode is its own, narrower path: the panel shows a bench section only when the server listed forms for this device; "Record this page" asks for the chosen form's origin in the operator's click, and the worker injects the content script into the active tab only when that tab is on that origin.

**Files:**
- Create: `extension/src/content/record.ts` (`savedCopy`)
- Modify: `extension/src/content/index.ts` (the `record` message; `__elmify_saved_copy` test hook)
- Modify: `extension/src/service_worker.ts` (`bench:hello`, `bench:record`), `extension/src/api.ts` (`BenchForm`, `benchWhoami`, `benchPortalForms`, `postBenchPage`), `extension/src/types.ts` (`DockState.bench`, `bench_last`)
- Modify: `extension/src/panel/panel.ts`, `panel.html`, `i18n.ts`
- Test: `tests/portals/test_extension_e2e.py`, `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Produces:
  - TS `savedCopy(root: Document): string`: the page's HTML with no scripts, no event-handler attributes, no `<base>`/`<iframe>` and no values;
  - worker messages `{type: "bench:hello"}` and `{type: "bench:record", portalFormId, page_kind, password_rules}`, both only `fromDock`;
  - content message `{type: "record"}` → `sendResponse({snapshot, html})`;
  - `DockState.bench?: {forms: BenchForm[]} | null`, `DockState.bench_last?: {page_kind: string; ok: boolean} | null`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/portals/test_extension_e2e.py`:

```python
@pytest.mark.extension
def test_a_saved_copy_carries_no_value_and_no_script(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.fill("#gn", "Orkhan")
    page.fill("#em", "owner@example.org")
    page.evaluate("""() => {
        const s = document.createElement("script"); s.textContent = "window.x = 1";
        document.body.appendChild(s);
        document.querySelector("#gn").setAttribute("onblur", "steal()");
        document.querySelector("#fn").setAttribute("value", "Abdullayev");
    }""")
    page.add_script_tag(path=str(DIST / "content.js"))
    html = page.evaluate("() => window.__elmify_saved_copy()")
    assert "Orkhan" not in html and "owner@example.org" not in html
    assert "Abdullayev" not in html  # a served, pre-filled value attribute too
    assert "<script" not in html.lower() and "onblur" not in html.lower()
    assert 'id="gn"' in html  # the structure survives
```

Append to `tests/portals/test_extension_bundle.py`:

```python
def test_bench_messages_are_accepted_only_from_the_dock() -> None:
    worker = bundle_text("service_worker.js")
    for kind in ("bench:hello", "bench:record"):
        assert re.search(rf'"{kind}"[\s\S]{{0,300}}fromDock', worker), kind


def test_a_saved_copy_is_built_never_cached() -> None:
    assert "localStorage" not in bundle_text("content.js")
```

- [ ] **Step 2: Run; expect failure** (`__elmify_saved_copy` is undefined).

Run: `npm --prefix extension run check && POSTGRES_DB=elmify_copilot_learning uv run pytest -q -m extension tests/portals/test_extension_e2e.py -k saved_copy`

- [ ] **Step 3: Implement `content/record.ts`.**

```ts
/**
 * The page as the bench will replay it: structure only.
 *
 * Built on a clone, so the live page is never touched. Every value goes --
 * input values (property AND attribute), textarea text, the selected option --
 * because the owner walks with their real account. Every script and inline
 * handler goes too: a replay must never run the portal's own code, which would
 * call the live portal from the bench. A <base> goes because it would point
 * relative URLs back at the live host, and an <iframe> because it is a live
 * page of its own.
 */
export function savedCopy(root: Document): string {
  const copy = root.documentElement.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("script, noscript, base, iframe").forEach((node) => node.remove());
  copy.querySelectorAll("*").forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      if (attribute.name.toLowerCase().startsWith("on")) element.removeAttribute(attribute.name);
    }
  });
  copy.querySelectorAll("input").forEach((element) => {
    element.removeAttribute("value");
    element.removeAttribute("checked");
  });
  copy.querySelectorAll("textarea").forEach((element) => {
    element.textContent = "";
  });
  copy.querySelectorAll("option").forEach((element) => element.removeAttribute("selected"));
  return "<!doctype html>\n" + copy.outerHTML;
}
```

`cloneNode` copies attributes, not live properties, so a typed value lives only in the property and never reaches the clone; the attribute removal covers values the page served pre-filled. In `content/index.ts`, import `savedCopy` and add to the listener, before `start`:

```ts
    if (message?.type === "record") {
      // Bench mode (plan 6): the operator's walk. Structure only, no values;
      // the server redacts the copy's text again before it keeps it.
      sendResponse({ snapshot: buildSnapshot(document), html: savedCopy(document) });
      return false;
    }
```

and inside the `if (__ELMIFY_TEST__)` block: `(globalThis as Record<string, unknown>)["__elmify_saved_copy"] = () => savedCopy(document);`.

- [ ] **Step 4: The API, the worker and the panel.**
- **API.** In `api.ts`:

```ts
export interface BenchForm { id: string; portal_host: string; form_url: string }

export async function benchWhoami(origin: string): Promise<boolean> {
  const body = (await call(origin, "/ext/bench/whoami")) as { operator?: unknown };
  return body.operator === true;
}

export async function benchPortalForms(origin: string): Promise<BenchForm[]> {
  const body = (await call(origin, "/ext/bench/portal-forms")) as { forms: BenchForm[] };
  return body.forms;
}

export async function postBenchPage(
  origin: string,
  portalFormId: string,
  page: { page_kind: string; password_rules: string; snapshot: unknown; html: string },
): Promise<{ record_id: string }> {
  return (await call(origin, `/ext/bench/portal-forms/${portalFormId}/pages`, {
    method: "POST",
    body: JSON.stringify(page),
  })) as { record_id: string };
}
```

- **Types.** `DockState` gains:

```ts
  /** Bench mode (plan 6): set only when the server lists forms for this device. */
  bench?: { forms: { id: string; portal_host: string; form_url: string }[] } | null;
  bench_last?: { page_kind: string; ok: boolean } | null;
```

- **Worker.** Beside `KNOWN_LANGS`: `const KNOWN_PAGE_KINDS = new Set(["FORM", "LOGIN", "SIGNUP", "CONFIRMATION", "OTHER"]);`. In `messageRefusal`:

```ts
  if (message["type"] === "bench:hello" && !fromDock(sender)) return "untrusted_sender";
  if (message["type"] === "bench:record") {
    if (!fromDock(sender)) return "untrusted_sender";
    if (!KNOWN_PAGE_KINDS.has(message["page_kind"] as string)) return "invalid_message";
    const formId = message["portalFormId"];
    if (typeof formId !== "string" || !APPLICATION_ID_RE.test(formId)) return "invalid_message";
  }
```

  In `handle` (importing `benchWhoami`, `benchPortalForms`, `postBenchPage` and `type BenchForm`):

```ts
  if (message?.type === "bench:hello") {
    void (async () => {
      const origin = await dashboardOrigin();
      let forms: BenchForm[] = [];
      try {
        if (origin && (await benchWhoami(origin))) forms = await benchPortalForms(origin);
      } catch {
        forms = []; // not an operator, offline or refused: no bench section
      }
      await chrome.storage.session.set({ bench_forms: forms });
      await patchDock({ bench: forms.length > 0 ? { forms } : null });
      sendResponse({ ok: true });
    })();
    return true;
  }
  if (message?.type === "bench:record") {
    void (async () => {
      const origin = await dashboardOrigin();
      const stored = await chrome.storage.session.get("bench_forms");
      const forms = (stored["bench_forms"] ?? []) as BenchForm[];
      const form = forms.find((candidate) => candidate.id === message.portalFormId);
      const link = form ? safeLink(form.form_url) : null;
      const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      // Only for a device the server listed forms for, only the active tab, and
      // only on the chosen form's own origin -- the one the panel asked for.
      if (!origin || !form || !link || tab?.id === undefined
          || !onOrigin(tab.url, new URL(link).origin)) {
        await patchDock({ bench_last: { page_kind: message.page_kind, ok: false } });
        return sendResponse({ ok: false, code: "wrong_page" });
      }
      try {
        await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
        const page = (await chrome.tabs.sendMessage(tab.id, { type: "record" })) as {
          snapshot?: unknown;
          html?: unknown;
        };
        if (typeof page?.html !== "string") throw new ExtError(400, "invalid_recording");
        await postBenchPage(origin, form.id, {
          page_kind: message.page_kind,
          password_rules: String(message.password_rules ?? ""),
          snapshot: page.snapshot,
          html: page.html,
        });
        await patchDock({ bench_last: { page_kind: message.page_kind, ok: true } });
        sendResponse({ ok: true });
      } catch (error) {
        await patchDock({ bench_last: { page_kind: message.page_kind, ok: false } });
        const code = error instanceof ExtError ? error.code : "request_failed";
        sendResponse({ ok: false, code });
      }
    })();
    return true;
  }
```

  ponytail: the form's own origin only, so a LOGIN on a separate single-sign-on host cannot be recorded; add an origin picker when a portal measured needs one.
- **Panel.** In `panel.html`, before `#unpair`:

```html
      <section id="bench" hidden>
        <h2 data-i18n="h_bench"></h2>
        <label><span data-i18n="bench_form"></span> <select id="bench-form"></select></label>
        <label><span data-i18n="bench_kind"></span>
          <select id="bench-kind">
            <option>FORM</option><option>LOGIN</option><option>SIGNUP</option>
            <option>CONFIRMATION</option><option>OTHER</option>
          </select>
        </label>
        <label id="bench-rules-label" hidden><span data-i18n="bench_password_rules"></span>
          <textarea id="bench-rules" maxlength="2000"></textarea></label>
        <button id="bench-record" type="button" data-i18n="bench_record"></button>
        <p id="bench-last"></p>
      </section>
```

  In `panel.ts`, after `chrome.runtime.sendMessage({ type: "dock:hello" })`: `chrome.runtime.sendMessage({ type: "bench:hello" }).catch(() => {});`. In `render`:

```ts
  const bench = document.getElementById("bench");
  if (bench) bench.hidden = !state.bench;
  const formPicker = document.getElementById("bench-form") as HTMLSelectElement | null;
  if (formPicker && state.bench) {
    const chosen = formPicker.value;
    formPicker.replaceChildren(
      ...state.bench.forms.map((form) => new Option(form.portal_host, form.id)),
    );
    if (chosen) formPicker.value = chosen;
  }
  const kind = (document.getElementById("bench-kind") as HTMLSelectElement | null)?.value ?? "";
  const rulesLabel = document.getElementById("bench-rules-label");
  if (rulesLabel) rulesLabel.hidden = kind !== "LOGIN" && kind !== "SIGNUP";
  const last = document.getElementById("bench-last");
  if (last) {
    last.textContent = state.bench_last
      ? t(lang, state.bench_last.ok ? "bench_saved" : "bench_failed")
      : "";
  }
```

  and the button:

```ts
// The operator's act, in our own panel. The host permission is asked here, in
// the click, before any await could spend the gesture.
document.getElementById("bench-record")?.addEventListener("click", () => {
  const formId = (document.getElementById("bench-form") as HTMLSelectElement | null)?.value;
  const form = state.bench?.forms.find((candidate) => candidate.id === formId);
  if (!form) return;
  let origin: string;
  try {
    origin = new URL(form.form_url).origin;
  } catch {
    return;
  }
  const pageKind = (document.getElementById("bench-kind") as HTMLSelectElement | null)?.value;
  const rules = (document.getElementById("bench-rules") as HTMLTextAreaElement | null)?.value;
  const asked = chrome.permissions.request({ origins: [`${origin}/*`] });
  void (async () => {
    if (!(await asked)) return render({ ...state, message: t(lang, "permission_needed") });
    await chrome.runtime.sendMessage({
      type: "bench:record",
      portalFormId: form.id,
      page_kind: pageKind ?? "FORM",
      password_rules: rules ?? "",
    });
  })();
});
document.getElementById("bench-kind")?.addEventListener("change", () => render(state));
```

  Add to all four tables in `i18n.ts`:
  - `h_bench`: en "Test bench", az "Sınaq stendi", tr "Test tezgâhı", ru "Тестовый стенд"
  - `bench_form`: en "Which portal form?", az "Hansı portal forması?", tr "Hangi portal formu?", ru "Какая форма портала?"
  - `bench_kind`: en "What page is this?", az "Bu hansı səhifədir?", tr "Bu hangi sayfa?", ru "Что это за страница?"
  - `bench_password_rules`: en "The portal's password rules, as it states them", az "Portalın şifrə qaydaları, onun yazdığı kimi", tr "Portalın şifre kuralları, yazdığı şekliyle", ru "Правила пароля портала, как он их пишет"
  - `bench_record`: en "Record this page", az "Bu səhifəni yaz", tr "Bu sayfayı kaydet", ru "Записать страницу"
  - `bench_saved`: en "Page recorded", az "Səhifə yazıldı", tr "Sayfa kaydedildi", ru "Страница записана"
  - `bench_failed`: en "Not recorded. Open the chosen form's own site, then try again.", az "Yazılmadı. Seçilmiş formanın öz saytını açın və yenidən cəhd edin.", tr "Kaydedilmedi. Seçilen formun kendi sitesini açın ve tekrar deneyin.", ru "Не записано. Откройте сайт выбранной формы и попробуйте снова."

  `test_only_the_panel_asks_for_the_portal_s_host_permission` stays green (the worker's count is still one); `test_the_worker_injects_content_only_into_a_bound_tab_on_its_own_origin` stays green, and its docstring gains one line: "Bench mode (plan 6) is the one other injection: operator only, the active tab, the chosen form's origin."

- [ ] **Step 5: Run; expect pass.** (Step 2 command, plus `POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_extension_bundle.py`.)

- [ ] **Step 6: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add extension/src tests/portals
git -C /home/orkhan/Desktop/copilot-learning commit -m "feat(extension): bench mode -- the operator records the active page of a chosen form, blanked of values and scripts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Per-portal rules: value formats, dropdown synonyms, read-back equivalences

**Files:**
- Modify: `apps/portals/models.py` (`PortalForm.value_formats`, `.option_synonyms`, `.readback_equivalences`, `.password_rules`)
- Create: `apps/portals/migrations/0027_portal_rules.py` (generated)
- Create: `apps/portals/rules.py` (`RulesForm`, `format_value`, `apply_rules`)
- Modify: `apps/portals/packets.py` (`mint_packet` applies rules; `FillPacket.equivalences`)
- Modify: `extension/src/types.ts`, `extension/src/content/fill.ts` (`sameValue`; `readBack` and `alreadyCorrect` honour equivalences), `extension/src/content/index.ts` (passes them; the `__elmify_read_back` test hook)
- Test: `tests/portals/test_rules.py` (new), `tests/portals/test_packet.py`, `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Produces:
  - `PortalForm.value_formats: dict[str, str]` (field class → format name), `.option_synonyms: dict[str, dict[str, str]]` (field class → our value → the portal's option text), `.readback_equivalences: dict[str, str]` (field class → `"casefold" | "collapse_spaces" | "digits" | "date"`), `.password_rules: str`;
  - `format_value(value: str, fmt: str) -> str`; `apply_rules(portal_form: RulesForm, profile_field: str, value: str) -> str`;
  - `FillPacket.equivalences: dict[str, str]` (default empty);
  - TS `sameValue(actual: string, expected: string, rule: string | undefined): boolean`.
- Field class = plan 5's `profile.field_class` (`education.2.end_date` → `education.end_date`); TS uses plan 5's `fieldClass`.

- [ ] **Step 1: Write the failing tests.** Create `tests/portals/test_rules.py`:

```python
import pytest

from apps.portals.rules import format_value


@pytest.mark.parametrize("fmt, expected", [
    ("DD.MM.YYYY", "07.03.2001"), ("MM/DD/YYYY", "03/07/2001"),
    ("YYYY-MM-DD", "2001-03-07"), ("DD/MM/YYYY", "07/03/2001"),
])
def test_an_iso_date_is_written_in_the_portals_format(fmt: str, expected: str) -> None:
    assert format_value("2001-03-07", fmt) == expected


def test_a_value_that_is_not_an_iso_date_is_never_reformatted() -> None:
    assert format_value("March 2001", "DD.MM.YYYY") == "March 2001"


@pytest.mark.django_db
def test_rules_apply_by_field_class_and_synonyms_replace_the_option_text() -> None:
    from apps.portals.models import PortalForm
    from apps.portals.rules import apply_rules

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="rules-1",
        value_formats={"education.end_date": "DD.MM.YYYY"},
        option_synonyms={"personal.nationality": {"Azerbaijan": "Azerbaijan, Republic of"}},
    )
    assert apply_rules(form, "education.2.end_date", "2024-06-30") == "30.06.2024"
    assert apply_rules(form, "personal.nationality", "Azerbaijan") == "Azerbaijan, Republic of"
    assert apply_rules(form, "personal.given_name", "Ləman") == "Ləman"
```

Append to `tests/portals/test_packet.py`:

```python
def test_the_packet_carries_formatted_values_and_the_portals_equivalences(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "2001-03-07"},
    )
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a, membership_a,
            value_formats={"personal.city": "DD.MM.YYYY"},
            readback_equivalences={"identity.full_name": "casefold"},
        )
        packet = packets.mint_packet(application)
    assert [e.value for e in packet.entries] == ["Ada Byron", "07.03.2001"]
    assert packet.equivalences == {"identity.full_name": "casefold"}
```

Append to `tests/portals/test_extension_e2e.py`:

```python
@pytest.mark.extension
@pytest.mark.parametrize("typed, shown, rule, green", [
    ("Işıl", "IŞIL", "casefold", True),  # Turkish dotless i, upper on both sides
    ("İpek", "İPEK", "casefold", True),
    ("Leyla", "LEYLA", None, False),  # no rule taught: amber
    ("Lala", "LEYLA", "casefold", False),  # a different name never passes
    ("2001-03-17", "17.03.2001", "date", True),
    ("2001-03-07", "07.03.2001", "date", False),  # 7 March or 3 July: stays amber
    ("+994 50 123", "99450123", "digits", True),
    ("Baku", "B a k u", "digits", False),  # no digits on either side is no match
])
def test_read_back_honours_only_the_rule_the_bench_taught(
    browser_context, fixture_server, typed: str, shown: str, rule: str | None, green: bool
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.fill("#gn", shown)
    page.add_script_tag(path=str(DIST / "content.js"))
    entry = {"selector": "#gn", "method": "fill", "value": typed,
             "profile_field": "personal.given_name"}
    equivalences = {"personal.given_name": rule} if rule else {}
    result = page.evaluate("([e, q]) => window.__elmify_read_back(e, q)", [[entry], equivalences])
    assert (result["mismatches"] == []) is green
```

- [ ] **Step 2: Run; expect `ModuleNotFoundError: apps.portals.rules`.**

Run: `POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_rules.py`

- [ ] **Step 3: Implement the server side.** In `PortalForm`:

```python
    #: Per-portal rules the bench taught (plan 6, spec §9), keyed by field class.
    value_formats = models.JSONField(default=dict, blank=True)
    option_synonyms = models.JSONField(default=dict, blank=True)
    readback_equivalences = models.JSONField(default=dict, blank=True)
    #: The portal's own password rules, from the recorded SIGNUP page (spec §6).
    password_rules = models.TextField(blank=True, default="")
```

Run `uv run python manage.py makemigrations portals -n portal_rules`. Create `apps/portals/rules.py`:

```python
"""Per-portal rules the bench taught (spec §9): every amber fixed here, never
left for the student. Applied server-side before a value leaves in a packet."""

from __future__ import annotations

import re
from datetime import date
from typing import Protocol

from .profile import field_class

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORMATS = {
    "DD.MM.YYYY": "%d.%m.%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
}


class RulesForm(Protocol):
    """What the rules read off a PortalForm; the bench runner passes the same."""

    value_formats: dict[str, str]
    option_synonyms: dict[str, dict[str, str]]
    readback_equivalences: dict[str, str]


def format_value(value: str, fmt: str) -> str:
    pattern = _FORMATS.get(fmt)
    if pattern is None or not _ISO.match(value):
        return value
    try:
        return date.fromisoformat(value).strftime(pattern)
    except ValueError:
        return value


def apply_rules(portal_form: RulesForm, profile_field: str, value: str) -> str:
    key = field_class(profile_field)
    value = format_value(value, (portal_form.value_formats or {}).get(key, ""))
    return (portal_form.option_synonyms or {}).get(key, {}).get(value, value)
```

In `packets.py`, import `apply_rules` from `.rules`; in `mint_packet`'s entries loop, the verified-fact `PacketField` takes `value=apply_rules(form, field, values[field])` (a student's own typed-back answer, `from_answer=True`, is left exactly as they typed it). `FillPacket` gains `equivalences: dict[str, str] = Field(default_factory=dict)` (import `Field`), set to `dict(form.readback_equivalences or {})`. The PACKET step records the formatted values, as it records values today.

- [ ] **Step 4: The extension.** In `types.ts`, add `equivalences?: Record<string, string>;` to `FillPacket`. In `content/fill.ts`, import `fieldClass` from `./verify.js` and add:

```ts
type Ymd = [number, number, number];

/** Every reading of a written date: one for YYYY-MM-DD; for D/M/YYYY one when
 *  the day is over 12 or day equals month, two when both orders make sense. */
function readings(text: string): Ymd[] {
  const iso = /^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$/.exec(text.trim());
  if (iso) return [[Number(iso[1]), Number(iso[2]), Number(iso[3])]];
  const other = /^(\d{1,2})[-./](\d{1,2})[-./](\d{4})$/.exec(text.trim());
  if (!other) return [];
  const [a, b, y] = [Number(other[1]), Number(other[2]), Number(other[3])];
  const out: Ymd[] = [];
  if (b <= 12 && a <= 31) out.push([y, b, a]); // day first
  if (a <= 12 && b <= 31 && a !== b) out.push([y, a, b]); // month first
  return out;
}

const digitsOf = (s: string): string => s.replace(/\D+/g, "");

/** Read-back equivalences the bench taught for one portal (plan 6). Each one
 *  widens equality for its own field class only, and never to "anything". */
const EQUIVALENCE: Record<string, (actual: string, expected: string) => boolean> = {
  // Upper case on both sides, not lower: "Işıl" and "IŞIL" lower to "ışıl" and
  // "işil", while both upper to "IŞIL" -- dotted and dotless i collapse the way
  // a portal's own uppercasing collapses them.
  casefold: (actual, expected) => actual.toUpperCase() === expected.toUpperCase(),
  collapse_spaces: (actual, expected) =>
    actual.replace(/\s+/g, " ").trim() === expected.replace(/\s+/g, " ").trim(),
  digits: (actual, expected) =>
    digitsOf(expected) !== "" && digitsOf(actual) === digitsOf(expected),
  // A date compares as a date only when both sides read one way; an ambiguous
  // 07.03.2001 stays amber, and the fix is a value_formats rule instead.
  date: (actual, expected) => {
    const [x, y] = [readings(actual), readings(expected)];
    return x.length === 1 && y.length === 1 && x[0]!.join("-") === y[0]!.join("-");
  },
};

export function sameValue(actual: string, expected: string, rule: string | undefined): boolean {
  if (actual === expected) return true;
  if (rule === undefined || !Object.hasOwn(EQUIVALENCE, rule)) return false;
  return EQUIVALENCE[rule]?.(actual, expected) ?? false;
}
```

`alreadyCorrect(verified, equivalences: Record<string, string> = {})` and `readBack(verified, equivalences: Record<string, string> = {})` compare with `sameValue(current, item.entry.value, equivalences[fieldClass(item.entry.profile_field)])` instead of `===` / `!==`. In `content/index.ts::run`, pass `packet.equivalences ?? {}` to both calls; `usePlainAddress` keeps the default. Add the test hook inside the `if (__ELMIFY_TEST__)` block (the bench runner loads `dist-test`, Task 5):

```ts
  (globalThis as Record<string, unknown>)["__elmify_read_back"] = (
    entries: PacketField[],
    equivalences: Record<string, string>,
  ) => {
    const verified = verifyEntries(entries);
    return {
      verdicts: verified.map((item) => ({
        profile_field: item.entry.profile_field,
        ok: item.ok,
        reason: item.reason,
      })),
      mismatches: readBack(verified, equivalences),
    };
  };
```

- [ ] **Step 5: Run; expect pass.**

Run: `POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_rules.py tests/portals/test_packet.py && uv run python manage.py makemigrations --check --dry-run && npm --prefix extension run check && POSTGRES_DB=elmify_copilot_learning uv run pytest -q -m extension tests/portals/test_extension_e2e.py -k "read_back or plain"`

- [ ] **Step 6: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add apps/portals extension/src tests/portals
git -C /home/orkhan/Desktop/copilot-learning commit -m "feat(portals): per-portal formats, dropdown synonyms and read-back equivalences the bench teaches

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The offline runner, the synthetic sample students and `portal_bench`

**Files:**
- Create: `apps/portals/bench_students.py` (`SampleStudent`, `SAMPLE_STUDENTS`)
- Create: `apps/portals/bench_runner.py` (`BenchMap`, `StudentRun`, `BenchReport`, `replay`, `suggest_rule`)
- Create: `apps/portals/management/commands/portal_bench.py`
- Create: `tests/portals/fixtures/bench_leaky_page.html`
- Test: `tests/portals/test_bench_runner.py` (new; browser tests marked `extension`)

**Interfaces:**
- Produces:
  - `SampleStudent(name: str, values: dict[str, str], documents: tuple[tuple[str, str, Literal["ORIGINAL", "TRANSLATION"]], ...])`; a document is `(filename, kind, variant)`;
  - `replay(portal_form: RulesForm, field_map: BenchMap, *, pages: list[tuple[object, bytes]], students: tuple[SampleStudent, ...] = SAMPLE_STUDENTS, transforms: dict[str, str] | None = None) -> BenchReport`;
  - `BenchReport(per_student: dict[str, StudentRun], blocked_requests: int)` with `.clean`, and `StudentRun(ambers: list[dict[str, str]], refused: list[dict[str, object]], manual_documents: list[str], open_choices: int)`;
  - `suggest_rule(expected: str, actual: str) -> str`;
  - `manage.py portal_bench <portal_form_id> --operator <email>`; exits 1 when not clean.

- [ ] **Step 1: Write the sample students.** Create `apps/portals/bench_students.py`. The keys follow `profile.verified_values` (`category.key`, plus plan 5's indexed `education.N.*`):

```python
"""Synthetic applicants for the bench (spec §9). Never copied from a real student."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Variant = Literal["ORIGINAL", "TRANSLATION"]


@dataclass(frozen=True)
class SampleStudent:
    name: str
    values: dict[str, str]
    documents: tuple[tuple[str, str, Variant], ...] = field(default_factory=tuple)


SAMPLE_STUDENTS: tuple[SampleStudent, ...] = (
    SampleStudent(
        "long multi-part name with ə/ğ/ı",
        {
            "identity.full_name": "Gülnarə Ləman Məmmədova-Ağayeva",
            "personal.given_name": "Gülnarə Ləman",
            "personal.family_name": "Məmmədova-Ağayeva",
            "personal.date_of_birth": "2001-03-07",
            "personal.nationality": "Azerbaijan",
            "education.1.institution_original": "Azərbaycan Dövlət İqtisad Universiteti",
            "education.1.end_date": "2023-06-30",
        },
        (
            ("transcript-az.pdf", "TRANSCRIPT", "ORIGINAL"),
            ("transcript-en.pdf", "TRANSCRIPT", "TRANSLATION"),
        ),
    ),
    SampleStudent(
        "two degrees",
        {
            "identity.full_name": "Rauf Hüseynov",
            "personal.given_name": "Rauf",
            "personal.family_name": "Hüseynov",
            "personal.date_of_birth": "1998-12-31",
            "personal.nationality": "Azerbaijan",
            "education.1.institution_original": "Bakı Dövlət Universiteti",
            "education.1.end_date": "2020-06-30",
            "education.2.institution_original": "ADA University",
            "education.2.end_date": "2022-06-30",
        },
        (
            ("bsc.pdf", "TRANSCRIPT", "ORIGINAL"),
            ("msc.pdf", "TRANSCRIPT", "ORIGINAL"),
            ("cv.pdf", "CV", "ORIGINAL"),
        ),
    ),
    SampleStudent(
        "Turkish dotted and dotless i",
        {
            "identity.full_name": "Işıl İpek Öztürk",
            "personal.given_name": "Işıl İpek",
            "personal.family_name": "Öztürk",
            "personal.date_of_birth": "2000-01-15",
            "personal.nationality": "Türkiye",
        },
        (("cv.pdf", "CV", "ORIGINAL"),),
    ),
    SampleStudent(
        "single name, no family name",
        {
            "identity.full_name": "Aynur",
            "personal.given_name": "Aynur",
            "personal.date_of_birth": "1999-05-05",
            "personal.nationality": "Azerbaijan",
        },
    ),
)
```

- [ ] **Step 2: Write the failing runner tests.** Create `tests/portals/fixtures/bench_leaky_page.html`:

```html
<!doctype html>
<!-- A saved copy whose own assets still point at the live portal. The replay
     must abort both requests and count them. -->
<html lang="en"><head><meta charset="utf-8" /><title>Apply</title>
<link rel="stylesheet" href="https://live-portal.example/site.css" /></head>
<body><form>
  <label for="gn">First name</label><input id="gn" />
  <label for="fn">Last name</label><input id="fn" />
  <img src="https://live-portal.example/beacon.gif" alt="" />
</form></body></html>
```

Create `tests/portals/test_bench_runner.py`:

```python
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _map(entries: list[dict[str, object]]):
    return type("Map", (), {"entries": entries, "slots": []})()


def _form(**rules: object):
    defaults: dict[str, object] = {
        "value_formats": {}, "option_synonyms": {}, "readback_equivalences": {},
    }
    return type("Form", (), {**defaults, **rules})()


def _page(name: str) -> tuple[object, bytes]:
    record = type("Record", (), {"page_kind": "FORM", "step": 1})()
    return record, (FIXTURES / name).read_bytes()


def _entry(field: str, selector: str) -> dict[str, object]:
    return {"profile_field": field, "sure": True,
            "action": {"selector": selector, "method": "fill", "arguments": ["%value%"]}}


@pytest.mark.extension
def test_the_replay_never_reaches_the_live_portal() -> None:
    from apps.portals.bench_runner import replay

    report = replay(_form(), _map([_entry("personal.given_name", "#gn")]),
                    pages=[_page("bench_leaky_page.html")])
    assert report.blocked_requests >= 2


@pytest.mark.extension
def test_a_clean_page_reports_clean_and_a_missing_family_name_is_not_an_amber() -> None:
    from apps.portals.bench_runner import replay

    report = replay(_form(), _map([
        _entry("personal.given_name", "#gn"), _entry("personal.family_name", "#fn"),
    ]), pages=[_page("bench_leaky_page.html")])
    assert report.per_student["single name, no family name"].ambers == []  # a hint, not amber
    assert report.clean


@pytest.mark.extension
def test_a_control_on_a_later_page_is_not_a_refusal() -> None:
    """Multi-page: an entry counts as refused only if it verified on no page,
    and a control simply absent from a page is never a refusal."""
    from apps.portals.bench_runner import replay

    report = replay(_form(), _map([_entry("personal.given_name", "#gn")]), pages=[
        _page("two_page_form_page2.html"), _page("bench_leaky_page.html"),
    ])
    assert all(run.refused == [] for run in report.per_student.values())


@pytest.mark.extension
def test_a_portal_that_uppercases_is_an_amber_until_the_rule_exists() -> None:
    """Saved copies carry no scripts (Task 3), so a portal's own uppercasing
    cannot replay. `transforms` stands in for what the owner's live walk saw."""
    from apps.portals.bench_runner import replay

    entries = [_entry("personal.given_name", "#gn")]
    page = _page("bench_leaky_page.html")
    upper = {"#gn": "upper"}
    assert not replay(_form(), _map(entries), pages=[page], transforms=upper).clean
    taught = _form(readback_equivalences={"personal.given_name": "casefold"})
    assert replay(taught, _map(entries), pages=[page], transforms=upper).clean


@pytest.mark.parametrize("expected, actual, kind", [
    ("Işıl", "IŞIL", "casefold"),
    ("2001-03-07", "07.03.2001", "value_formats"),
    ("+994 50 123", "99450123", "digits"),
    ("Azerbaijan", "", "option_synonyms"),
])
def test_every_amber_gets_a_suggested_rule(expected: str, actual: str, kind: str) -> None:
    from apps.portals.bench_runner import suggest_rule

    assert kind in suggest_rule(expected, actual)
```

`transforms` is test-only and narrow (`{selector: "upper"}`): the runner applies it after typing. `two_page_form_page2.html` already exists in `tests/portals/fixtures/`.

- [ ] **Step 3: Run; expect `ModuleNotFoundError: apps.portals.bench_runner`.**

Run: `npm --prefix extension run check && POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_bench_runner.py && POSTGRES_DB=elmify_copilot_learning uv run pytest -q -m extension tests/portals/test_bench_runner.py`

- [ ] **Step 4: Implement `apps/portals/bench_runner.py`.**

```python
"""Replay saved copies of a portal's pages offline, from synthetic students
(spec §9). Never a live portal: pages are served from a temporary directory on
127.0.0.1 and every other request is aborted and counted. Loads the TEST
bundle (extension/dist-test): __elmify_read_back exists only there, so the
production bundle never ships it."""

from __future__ import annotations

import re
import tempfile
import threading
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from .bench_students import SAMPLE_STUDENTS, SampleStudent
from .packets import PacketRefused, _parse_entry
from .rules import RulesForm, apply_rules
from .slots import HeldDocument, pair_slots, parse_slots

if TYPE_CHECKING:
    from playwright.sync_api import Route

DIST = Path(__file__).resolve().parents[2] / "extension" / "dist-test"

_UPPER = (
    "(s) => { const el = document.querySelector(s);"
    " if (el) el.value = el.value.toUpperCase(); }"
)


class BenchMap(Protocol):
    entries: list[dict[str, object]]
    slots: object


@dataclass
class StudentRun:
    ambers: list[dict[str, str]] = field(default_factory=list)
    refused: list[dict[str, object]] = field(default_factory=list)
    manual_documents: list[str] = field(default_factory=list)
    open_choices: int = 0


@dataclass
class BenchReport:
    per_student: dict[str, StudentRun] = field(default_factory=dict)
    blocked_requests: int = 0

    @property
    def clean(self) -> bool:
        return all(
            not r.ambers and not r.refused and not r.manual_documents and not r.open_choices
            for r in self.per_student.values()
        )


def _entries(
    portal_form: RulesForm, field_map: BenchMap, student: SampleStudent
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for raw in field_map.entries:
        if raw.get("sure", True) is False:
            continue  # a hint in a real packet: never typed, never amber
        try:
            profile_field, action = _parse_entry(raw)
        except PacketRefused:
            continue  # a malformed row refuses a real packet; the report shows nothing typed
        value = student.values.get(profile_field)
        if value is None:
            continue  # no fact: a hint in a real packet, never typed, never amber
        out.append({
            "selector": action.selector,
            "method": (action.method or "").strip(),
            "value": apply_rules(portal_form, profile_field, value),
            "profile_field": profile_field,
        })
    return out


def _documents(
    field_map: BenchMap, student: SampleStudent
) -> tuple[list[dict[str, str]], int]:
    """The student's documents through plan 5's own pairing, for the kinds the
    map has a slot for. A form that asks for no upload has no document ambers."""
    slots = parse_slots(field_map.slots)
    kinds = {slot.kind for slot in slots}
    held = [
        HeldDocument(source="upload", id=uuid4(), filename=name, kind=kind,
                     variant=variant, download_path="")
        for name, kind, variant in student.documents
        if kind in kinds
    ]
    degrees = {
        key.split(".")[1] for key in student.values if re.fullmatch(r"education\.\d+\.\w+", key)
    }
    pairing = pair_slots(slots, held, len(degrees))
    attach = [
        {"filename": held_doc.filename, "selector": slot.selector, "kind": held_doc.kind}
        for slot, held_doc in pairing.assigned
    ]
    return attach, len(pairing.choices)


def replay(
    portal_form: RulesForm,
    field_map: BenchMap,
    *,
    pages: list[tuple[object, bytes]],
    students: tuple[SampleStudent, ...] = SAMPLE_STUDENTS,
    transforms: dict[str, str] | None = None,
) -> BenchReport:
    from playwright.sync_api import sync_playwright

    report = BenchReport()
    with tempfile.TemporaryDirectory() as root:
        for index, (_record, body) in enumerate(pages):
            Path(root, f"page-{index}.html").write_bytes(body)
        handler = partial(SimpleHTTPRequestHandler, directory=root)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}/"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()

                def gate(route: Route) -> None:
                    if route.request.url.startswith(base):
                        route.continue_()
                    else:
                        report.blocked_requests += 1
                        route.abort()

                context.route("**/*", gate)
                for student in students:
                    run = report.per_student.setdefault(student.name, StudentRun())
                    entries = _entries(portal_form, field_map, student)
                    attach, run.open_choices = _documents(field_map, student)
                    verified_somewhere: set[str] = set()
                    refusals: dict[str, dict[str, object]] = {}
                    attached: set[str] = set()
                    for index in range(len(pages)):
                        page = context.new_page()
                        page.goto(f"{base}page-{index}.html")
                        if not page.url.startswith(base):  # never left the bench
                            raise RuntimeError(f"the replay left the bench: {page.url}")
                        page.add_script_tag(path=str(DIST / "content.js"))
                        page.evaluate("(e) => window.__elmify_fill(e)", entries)
                        for selector, kind in (transforms or {}).items():
                            if kind == "upper":
                                page.evaluate(_UPPER, selector)
                        result = page.evaluate(
                            "([e, q]) => window.__elmify_read_back(e, q)",
                            [entries, dict(portal_form.readback_equivalences or {})],
                        )
                        run.ambers.extend(result["mismatches"])
                        for verdict in result["verdicts"]:
                            if verdict["ok"]:
                                verified_somewhere.add(verdict["profile_field"])
                            elif verdict["reason"] != "no_such_control":
                                refusals[verdict["profile_field"]] = verdict
                        if attach:
                            placed = page.evaluate(
                                "(docs) => window.__elmify_attach("
                                "docs.map((d) => ({...d, bytes: new ArrayBuffer(8)})))",
                                attach,
                            )
                            attached.update(a["filename"] for a in placed["attached"])
                        page.close()
                    # Multi-page: refused only if it verified on no page at all.
                    run.refused = [v for f, v in refusals.items() if f not in verified_somewhere]
                    run.manual_documents = [
                        d["filename"] for d in attach if d["filename"] not in attached
                    ]
                browser.close()
        finally:
            server.shutdown()
    return report


def suggest_rule(expected: str, actual: str) -> str:
    """The rule kind most likely to turn this amber green. A suggestion only:
    the command never writes a rule, the owner does."""
    if actual == "":
        return "option_synonyms (no option matched), or a map correction"
    if expected.upper() == actual.upper():
        return "readback_equivalences: casefold"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", expected) and sorted(
        re.findall(r"\d+", expected)
    ) == sorted(re.findall(r"\d+", actual)):
        return f"value_formats: the portal writes this date as {actual!r}"
    if digits := re.sub(r"\D", "", expected):
        if digits == re.sub(r"\D", "", actual):
            return "readback_equivalences: digits"
    if " ".join(expected.split()) == " ".join(actual.split()):
        return "readback_equivalences: collapse_spaces"
    return "a map correction (the box asks for something else)"
```

- [ ] **Step 5: Write the command.** Create `apps/portals/management/commands/portal_bench.py`:

```python
"""Replay a portal form's recorded bench walk offline (spec §9).

    uv run python manage.py portal_bench <portal_form_id> --operator <email>

Exit 1 when the report is not clean. The command never writes a rule: the
owner sets value_formats / option_synonyms / readback_equivalences (admin or
shell), or corrects the map, then re-runs.
"""

from __future__ import annotations

from argparse import ArgumentParser
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.portals.bench import is_bench_operator
from apps.portals.bench_runner import BenchReport, replay, suggest_rule
from apps.portals.models import FieldMap, PageRecord, PortalForm
from apps.research.models import PlatformAgency
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership


def resolve_operator(email: str) -> Membership:
    """The named bench operator, read inside the platform tenant (Membership is
    FORCE RLS), exactly as funding_review resolves its operator."""
    platform = PlatformAgency.objects.first()
    if platform is None:
        raise CommandError("no platform agency is set (manage.py set_platform_agency)")
    with tenant_scope(platform.agency_id), tenant_transaction(platform.agency_id):
        operator = (
            Membership.objects.filter(
                tenant_id=platform.agency_id, role=Membership.Role.PLATFORM_ADMIN,
                active=True, user__is_active=True, user__email__iexact=email,
            )
            .select_related("user")
            .first()
        )
        if operator is None or not is_bench_operator(operator):
            raise CommandError(f"no bench operator with email {email} (PLATFORM_ADMIN + MFA)")
    return operator


def bench_map(form: PortalForm) -> FieldMap:
    """The shared map, else the newest live tenant map: the bench verifies
    whichever map students are actually being served."""
    current = FieldMap.current_for(form, None) or (
        FieldMap.objects.filter(portal_form=form, superseded_at__isnull=True)
        .order_by("-version")
        .first()
    )
    if current is None:
        raise CommandError("this form has no map yet: a student's first visit learns one")
    return current


def run_bench(form: PortalForm) -> tuple[BenchReport, FieldMap]:
    records = (
        PageRecord.objects.filter(portal_form=form, source=PageRecord.Source.BENCH_WALK)
        .exclude(html_key="")
        .order_by("step")
    )
    store = S3ObjectStore()
    pages: list[tuple[object, bytes]] = [(r, store.get(r.html_key)) for r in records]
    if not pages:
        raise CommandError("no recorded walk: walk it first (docs/runbooks/portal-bench.md)")
    field_map = bench_map(form)
    return replay(form, field_map, pages=pages), field_map


class Command(BaseCommand):
    help = "Replay a portal form's recorded bench walk offline from synthetic students."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("portal_form_id", nargs="?", type=UUID)
        parser.add_argument("--operator", required=True, help="the bench operator's email")

    def handle(self, *args: object, **options: object) -> None:
        resolve_operator(str(options["operator"]))
        form = self._form(options["portal_form_id"])
        report, _field_map = run_bench(form)
        self._print(report)
        if not report.clean:
            raise CommandError("not clean: set the suggested rules or correct the map, re-run")

    def _form(self, form_id: object) -> PortalForm:
        if not isinstance(form_id, UUID):
            raise CommandError("name a portal form id")
        form = PortalForm.objects.filter(id=form_id).first()
        if form is None:
            raise CommandError(f"no portal form {form_id}")
        return form

    def _print(self, report: BenchReport) -> None:
        self.stdout.write(f"blocked requests to anywhere but the bench: {report.blocked_requests}")
        for name, run in report.per_student.items():
            self.stdout.write(
                f"{name}: {len(run.ambers)} amber, {len(run.refused)} refused, "
                f"{len(run.manual_documents)} manual documents, {run.open_choices} open choices"
            )
            for amber in run.ambers:
                self.stdout.write(
                    f"  {amber['profile_field']}: {amber['expected']!r} -> {amber['actual']!r}"
                    f"  [{suggest_rule(amber['expected'], amber['actual'])}]"
                )
            for verdict in run.refused:
                self.stdout.write(f"  refused {verdict['profile_field']}: {verdict['reason']}")
            for filename in run.manual_documents:
                self.stdout.write(f"  attach by hand: {filename}")
        self.stdout.write("CLEAN" if report.clean else "NOT CLEAN")
```

Add a command test to `tests/portals/test_bench_runner.py` (no browser; it reuses Task 2's fixtures by import):

```python
from tests.portals.test_bench_api import operator, platform, portal_form  # noqa: F401


@pytest.mark.django_db
def test_the_command_refuses_a_form_with_no_recorded_walk(operator, portal_form) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="no recorded walk|no map yet"):
        call_command("portal_bench", str(portal_form.id), "--operator", "owner@example.org")
```

- [ ] **Step 6: Run; expect pass.** (Step 3 command.)

- [ ] **Step 7: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add apps/portals tests/portals
git -C /home/orkhan/Desktop/copilot-learning commit -m "feat(portals): portal_bench replays saved copies offline from synthetic students and counts every amber

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The verified gate: promote a zero-amber map to every tenant

**Files:**
- Modify: `apps/portals/models.py` (`FieldMap.verified_at`, `PortalForm.needs_bench`; `current_for` prefers a verified map unless the form needs the bench)
- Create: `apps/portals/migrations/0028_field_map_verified.py` (generated)
- Modify: `apps/portals/learn.py::_store_map` (supersede its own scope's current row by an explicit filter)
- Modify: `apps/portals/bench.py` (`PromotionRefused`, `promote`), `apps/portals/management/commands/portal_bench.py` (`--promote`, `--walk-ok`)
- Test: `tests/portals/test_bench_promote.py` (new)

**Interfaces:**
- Produces:
  - `FieldMap.verified_at: datetime | None`; `PortalForm.needs_bench: bool` (default False);
  - `promote(portal_form: PortalForm, source_map: FieldMap, report: BenchReport, *, operator: Membership) -> FieldMap`, raising `PromotionRefused(reason)` and writing nothing;
  - `portal_bench <form> --operator <email> --walk-ok LOGIN|SIGNUP` (marks the newest such BENCH_WALK record `walk_ok=True`, spec §6 checked by the owner's own walk) and `--promote`.

- [ ] **Step 1: Write the failing tests.** Create `tests/portals/test_bench_promote.py`:

```python
import pytest

from apps.portals.bench_runner import BenchReport, StudentRun
from apps.tenancy.context import tenant_scope
from tests.portals.test_bench_api import operator, platform, portal_form  # noqa: F401

pytestmark = pytest.mark.django_db

ENTRY = {"profile_field": "identity.full_name", "sure": True,
         "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]}}


def _clean() -> BenchReport:
    return BenchReport(per_student={"s": StudentRun()})


def _dirty() -> BenchReport:
    return BenchReport(per_student={"s": StudentRun(ambers=[{"profile_field": "x"}])})


@pytest.fixture
def tenant_map(portal_form, agency_a):
    from apps.portals.models import FieldMap

    return FieldMap.objects.create(
        portal_form=portal_form, version=1, learned_by_tenant=agency_a, entries=[ENTRY]
    )


def _walked(portal_form, *, walk_ok: bool = True) -> None:
    from apps.portals.models import PageRecord

    for kind in ("LOGIN", "SIGNUP"):
        PageRecord.objects.create(
            portal_form=portal_form, source="BENCH_WALK", page_kind=kind, step=1,
            snapshot={"page_url": "https://apply.example.edu", "controls": []},
            password_rules="At least 12 characters", walk_ok=walk_ok,
        )


def test_promotion_with_an_amber_is_refused_and_writes_nothing(tenant_map, operator) -> None:
    from apps.portals.bench import PromotionRefused, promote
    from apps.portals.models import FieldMap

    _walked(tenant_map.portal_form)
    with pytest.raises(PromotionRefused, match="not clean"):
        promote(tenant_map.portal_form, tenant_map, _dirty(), operator=operator)
    assert not FieldMap.objects.filter(verified_at__isnull=False).exists()


@pytest.mark.parametrize("walk_ok", [False, None])
def test_promotion_needs_a_login_and_signup_that_were_walked(
    tenant_map, operator, walk_ok: bool | None
) -> None:
    from apps.portals.bench import PromotionRefused, promote

    if walk_ok is not None:
        _walked(tenant_map.portal_form, walk_ok=walk_ok)
    with pytest.raises(PromotionRefused, match="LOGIN"):
        promote(tenant_map.portal_form, tenant_map, _clean(), operator=operator)


def test_a_verified_map_serves_every_tenant_and_a_tenant_cannot_shadow_it(
    tenant_map, operator, agency_a, agency_b
) -> None:
    from apps.funding.models import AuditEvent
    from apps.portals.bench import promote
    from apps.portals.learn import _store_map
    from apps.portals.models import FieldMap

    form = tenant_map.portal_form
    _walked(form)
    verified = promote(form, tenant_map, _clean(), operator=operator)
    assert verified.learned_by_tenant_id is None and verified.verified_at is not None
    assert verified.entries == tenant_map.entries and verified.slots == tenant_map.slots
    form.refresh_from_db()
    assert form.password_rules == "At least 12 characters" and form.needs_bench is False
    for tenant in (agency_a, agency_b):
        assert FieldMap.current_for(form, tenant.id) == verified
    # A tenant learning again supersedes ITS OWN older map, and still loses.
    relearned = _store_map(form, [ENTRY], learned_by_tenant_id=agency_a.id)
    tenant_map.refresh_from_db()
    assert tenant_map.superseded_at is not None
    assert FieldMap.current_for(form, agency_a.id) == verified
    # Until a live relearn says the portal changed: then the tenant's own wins.
    form.needs_bench = True
    form.save(update_fields=["needs_bench"])
    assert FieldMap.current_for(form, agency_a.id) == relearned
    assert FieldMap.current_for(form, agency_b.id) == verified  # the shared fallback
    with tenant_scope(operator.tenant_id):
        assert AuditEvent.objects.filter(
            event="portal.field_map_verified", object_id=verified.id
        ).exists()
```

- [ ] **Step 2: Run; expect failure.**

Run: `POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_bench_promote.py`

- [ ] **Step 3: Implement.**
- **Fields.** `FieldMap` gains `verified_at = models.DateTimeField(null=True, blank=True)` with the comment "#: Set by the bench's verified gate (plan 6). A verified map is shared (learned_by_tenant NULL) and outranks a tenant's own map unless its form needs_bench."; `PortalForm` gains:

```python
    #: A live relearn met a changed form while a bench-verified map served it
    #: (plan 5 Task 6). Until the bench runs again the verified map no longer
    #: outranks a tenant's fresh one, and `portal_bench --queue` lists the form.
    needs_bench = models.BooleanField(default=False)
```

  Run `uv run python manage.py makemigrations portals -n field_map_verified`.
- **`current_for`.** At the top of `FieldMap.current_for`, before the scoped lookup:

```python
        verified = (
            cls.objects.filter(
                portal_form=portal_form,
                learned_by_tenant__isnull=True,
                verified_at__isnull=False,
                superseded_at__isnull=True,
            )
            .order_by("-version")
            .first()
        )
        if verified is not None and not portal_form.needs_bench:
            return verified
```

  and add to its docstring: "A bench-verified map comes first, for every tenant: a person has checked it against the real pages (CLAUDE.md, 'Promotion ... after a human looks'). A form that needs the bench again falls back to the order below, where the verified row is simply the shared one."
- **`_store_map`.** Replace `previous = FieldMap.current_for(portal_form, learned_by_tenant_id)` and its `if` with an explicit read of this scope's own current row (once verified maps win, `current_for` would hand a tenant the verified row, and the tenant's own older map would never be superseded):

```python
        previous = (
            FieldMap.objects.filter(
                portal_form=portal_form,
                learned_by_tenant_id=learned_by_tenant_id,
                superseded_at__isnull=True,
            )
            .order_by("-version")
            .first()
        )
        if previous is not None:
            # Only ever our own scope's row: superseding the shared row from a
            # tenant's snapshot is the cross-tenant write this column prevents.
            previous.supersede()
```

- **`promote`** in `apps/portals/bench.py` (import `transaction` from `django.db`, `timezone` from `django.utils`, `AuditEvent` from `apps.funding.models`, `tenant_scope` from `apps.tenancy.context`, `tenant_transaction` from `apps.tenancy.db`, `BenchReport` from `.bench_runner`, `_store_map` from `.learn`, and `FieldMap` from `.models`):

```python
class PromotionRefused(Exception):
    pass


def promote(
    portal_form: PortalForm, source_map: FieldMap, report: BenchReport, *, operator: Membership
) -> FieldMap:
    """Spec §9's verified gate. Copies the bench-clean map to a platform-shared,
    verified row. Refuses, writing nothing, unless the bench is clean and the
    walk recorded the portal's login and sign-up pages, with their password
    rules, as having worked (spec §6, checked by the owner's own walk)."""
    if not is_bench_operator(operator):
        raise PromotionRefused("only a bench operator promotes a map")
    if not report.clean:
        raise PromotionRefused(
            "the bench run is not clean: an amber, a refusal, a manual document "
            "or an open choice remains"
        )
    walked = PageRecord.objects.filter(
        portal_form=portal_form, source=PageRecord.Source.BENCH_WALK
    )
    for kind in (PageRecord.Kind.LOGIN, PageRecord.Kind.SIGNUP):
        if not walked.filter(page_kind=kind, walk_ok=True).exclude(password_rules="").exists():
            raise PromotionRefused(
                f"no recorded {kind} page with its password rules marked as worked "
                f"(portal_bench --walk-ok {kind})"
            )
    signup_rules = (
        walked.filter(page_kind=PageRecord.Kind.SIGNUP)
        .exclude(password_rules="")
        .order_by("-created_at")
        .values_list("password_rules", flat=True)
        .first()
    )
    with transaction.atomic():
        verified = _store_map(
            portal_form, list(source_map.entries), slots=list(source_map.slots or []),
            learned_by_tenant_id=None,
        )
        verified.verified_at = timezone.now()
        verified.save(update_fields=["verified_at"])
        portal_form.password_rules = signup_rules or ""
        portal_form.needs_bench = False
        portal_form.save(update_fields=["password_rules", "needs_bench"])
        # AuditEvent is a TenantScopedModel: the scope for its save, the GUC for
        # its FORCE RLS policy. Written under the platform agency, by the operator.
        with tenant_scope(operator.tenant_id), tenant_transaction(operator.tenant_id):
            AuditEvent.objects.create(
                tenant_id=operator.tenant_id,
                actor=operator,
                actor_kind=AuditEvent.ActorKind.HUMAN,
                event="portal.field_map_verified",
                object_id=verified.id,
            )
    return verified
```

  `bench_runner` imports nothing from `bench`, so the import is one-way.
- **Command flags.** In `portal_bench.py`, add arguments `parser.add_argument("--promote", action="store_true")` and `parser.add_argument("--walk-ok", choices=["LOGIN", "SIGNUP"])`, and replace `handle`'s body after `resolve_operator(...)`:

```python
        operator = resolve_operator(str(options["operator"]))
        form = self._form(options["portal_form_id"])
        if options["walk_ok"]:
            record = (
                PageRecord.objects.filter(
                    portal_form=form, source=PageRecord.Source.BENCH_WALK,
                    page_kind=str(options["walk_ok"]),
                )
                .order_by("-created_at")
                .first()
            )
            if record is None:
                raise CommandError(f"no recorded {options['walk_ok']} page for this form")
            record.walk_ok = True
            record.save(update_fields=["walk_ok"])
            self.stdout.write(f"{options['walk_ok']} marked as worked in the live walk")
            return
        report, field_map = run_bench(form)
        self._print(report)
        if not report.clean:
            raise CommandError("not clean: set the suggested rules or correct the map, re-run")
        if options["promote"]:
            try:
                verified = promote(form, field_map, report, operator=operator)
            except PromotionRefused as refused:
                raise CommandError(str(refused)) from refused
            self.stdout.write(f"verified: field map v{verified.version} now serves every tenant")
```

  (the first line replaces the bare `resolve_operator(...)` call; import `PromotionRefused, promote` from `apps.portals.bench`). `--promote` therefore only ever follows a replay it has just run.

- [ ] **Step 4: Run; expect pass.** (Step 2 command, plus `tests/portals/test_models.py tests/portals/test_snapshot_learn.py tests/portals/test_packet.py tests/portals/test_learn.py`, then `uv run python manage.py makemigrations --check --dry-run`.)

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add apps/portals tests/portals
git -C /home/orkhan/Desktop/copilot-learning commit -m "feat(portals): the verified gate -- a zero-amber bench map with walked login and sign-up serves every tenant

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The owner's to-walk queue, and a changed portal goes back on it

The bench verifies only what was walked. This task makes the walk list explicit: `portal_bench --queue` lists every portal form students are already meeting (LIVE_LEARN records) that has no verified map, and every form a live relearn marked `needs_bench` (the portal changed under its verified map, plan 5 Task 6). LIVE_LEARN records are never replayed (they hold no HTML); they only put a form on the queue.

**Files:**
- Modify: `apps/portals/ext_api.py::snapshot` (a relearn over a verified map marks the form `needs_bench`)
- Modify: `apps/portals/management/commands/portal_bench.py` (`--queue`)
- Test: `tests/portals/test_ext_api.py`, `tests/portals/test_bench_runner.py`

**Interfaces:**
- Produces: `manage.py portal_bench --operator <email> --queue`, one line per form: `<id>  <portal_host>  <reason>  live=<n> walked=<n>`, reason `unverified` or `changed`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/portals/test_ext_api.py`:

```python
def test_a_relearn_over_a_verified_map_puts_the_form_back_on_the_bench(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    from django.utils import timezone

    from apps.portals import ext_api
    from apps.portals.models import FieldMap, PortalForm

    monkeypatch.setattr(ext_api, "verified_values", lambda student: {})
    monkeypatch.setattr(
        ext_api, "learn_from_snapshot",
        lambda form, snapshot, **kwargs: FieldMap.objects.create(
            portal_form=form, version=9, entries=[], learned_by_tenant_id=kwargs["tenant_id"]
        ),
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    FieldMap.objects.filter(portal_form_id=application.portal_form_id).update(
        verified_at=timezone.now()
    )
    token = _pair(client, agency_a, membership_a, domain_a)
    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot",
        data=json.dumps(SNAPSHOT_BODY), content_type="application/json",
        HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 201
    assert PortalForm.objects.get(id=application.portal_form_id).needs_bench is True
```

Append to `tests/portals/test_bench_runner.py`:

```python
@pytest.mark.django_db
def test_the_queue_lists_unverified_live_forms_and_changed_ones(operator, agency_a) -> None:
    from io import StringIO

    from django.core.management import call_command

    from apps.portals.models import PageRecord, PortalForm

    met = PortalForm.objects.create(portal_host="met.example.edu", form_key="q-1")
    PageRecord.objects.create(
        portal_form=met, source="LIVE_LEARN", page_kind="FORM", step=1,
        snapshot={"page_url": "https://met.example.edu", "controls": []},
        learned_by_tenant=agency_a,
    )
    changed = PortalForm.objects.create(
        portal_host="changed.example.edu", form_key="q-2", needs_bench=True
    )
    PortalForm.objects.create(portal_host="nobody.example.edu", form_key="q-3")
    out = StringIO()
    call_command("portal_bench", "--operator", "owner@example.org", "--queue", stdout=out)
    lines = out.getvalue().splitlines()
    assert any(str(met.id) in line and "unverified" in line for line in lines)
    assert any(str(changed.id) in line and "changed" in line for line in lines)
    assert not any("nobody.example.edu" in line for line in lines)
```

- [ ] **Step 2: Run; expect failure.**

Run: `POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_ext_api.py tests/portals/test_bench_runner.py -k "back_on_the_bench or queue"`

- [ ] **Step 3: Implement.** In `ext_api.py::snapshot`, inside the same `tenant_transaction` as the `PageRecord` (import `FieldMap` from `.models`):

```python
        # A tenant relearning a form that a bench-verified map serves: the portal
        # changed under the verified map (plan 5 Task 6). Back on the queue, and
        # the verified map stops outranking this tenant's fresh one meanwhile.
        if FieldMap.objects.filter(
            portal_form_id=application.portal_form_id,
            verified_at__isnull=False,
            superseded_at__isnull=True,
        ).exists():
            PortalForm.objects.filter(pk=application.portal_form_id).update(needs_bench=True)
```

In `portal_bench.py`, add `parser.add_argument("--queue", action="store_true")`, and directly after `operator = resolve_operator(...)` in `handle`:

```python
        if options["queue"]:
            self._queue()
            return
```

with:

```python
    def _queue(self) -> None:
        """The owner's walk list: forms students already meet with no verified
        map, and forms whose portal changed under their verified map."""
        verified = FieldMap.objects.filter(
            verified_at__isnull=False, superseded_at__isnull=True
        ).values_list("portal_form_id", flat=True)
        live = PageRecord.objects.filter(source=PageRecord.Source.LIVE_LEARN)
        unverified = PortalForm.objects.filter(
            id__in=live.values_list("portal_form_id", flat=True)
        ).exclude(id__in=verified)
        changed = PortalForm.objects.filter(needs_bench=True)
        rows = [(form, "changed") for form in changed] + [
            (form, "unverified") for form in unverified.exclude(needs_bench=True)
        ]
        for form, reason in sorted(rows, key=lambda row: row[0].portal_host):
            records = PageRecord.objects.filter(portal_form=form)
            self.stdout.write(
                f"{form.id}  {form.portal_host}  {reason}  "
                f"live={records.filter(source=PageRecord.Source.LIVE_LEARN).count()} "
                f"walked={records.filter(source=PageRecord.Source.BENCH_WALK).count()}"
            )
```

- [ ] **Step 4: Run; expect pass.** (Step 2 command, then the whole of both files.)

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add apps/portals tests/portals
git -C /home/orkhan/Desktop/copilot-learning commit -m "feat(portals): portal_bench --queue -- live-learned forms with no verified map, and portals that changed under one

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The wording sheet in four languages

**Files:**
- Modify: `extension/src/content/labels.ts` (export the table as `MARK_LABELS`)
- Modify: `extension/build.mjs` (write `dist/i18n.json` and `dist-test/i18n.json` from `panel/i18n.ts`'s `STRINGS` and the mark labels)
- Modify: `apps/portals/management/commands/portal_bench.py` (`--wording <out_dir>`)
- Test: `tests/portals/test_bench_wording.py` (new)

**Interfaces:**
- Consumes: plan 1's `panel/i18n.ts` (`STRINGS`) and `content/labels.ts` (the mark labels).
- Produces: `dist/i18n.json` of the shape `{lang: {key: text}}` (panel keys as they are; mark labels as `mark_<key>` and `mark_step_<step>`), and an HTML review sheet.

- [ ] **Step 1: Write the failing test.** Create `tests/portals/test_bench_wording.py`:

```python
import json
import pathlib

import pytest

DIST = pathlib.Path(__file__).resolve().parents[2] / "extension" / "dist"


def test_every_message_and_mark_exists_in_all_four_languages() -> None:
    path = DIST / "i18n.json"
    if not path.exists():
        pytest.skip("extension/dist is missing -- npm --prefix extension run build")
    catalogue = json.loads(path.read_text())
    assert set(catalogue) == {"az", "tr", "ru", "en"}
    keys = set(catalogue["en"])
    assert {"mark_filled", "mark_fromAnswer", "mark_step_next", "r_our_guess"} <= keys
    for lang, messages in catalogue.items():
        assert set(messages) == keys, f"{lang} misses {keys - set(messages)}"
        assert all(text.strip() for text in messages.values()), lang
```

- [ ] **Step 2: Implement.**
- **`labels.ts`.** Rename `TABLE` to `export const MARK_LABELS` (and its one use in `contentLabels`).
- **`build.mjs`.** Add `writeFile` to the `node:fs/promises` import and, after the `cp` calls:

```js
// The four-language wording sheet's source (plan 6): every panel string and
// every mark label, from the same modules the bundles are built from, so the
// sheet cannot drift from what ships.
const catalogue = await build({
  stdin: {
    contents:
      'export { STRINGS } from "./src/panel/i18n.ts";\n' +
      'export { MARK_LABELS } from "./src/content/labels.ts";',
    resolveDir: ".",
    loader: "ts",
  },
  bundle: true,
  write: false,
  format: "esm",
  platform: "neutral",
});
const source = Buffer.from(catalogue.outputFiles[0].text).toString("base64");
const { STRINGS, MARK_LABELS } = await import(`data:text/javascript;base64,${source}`);
const sheet = {};
for (const lang of Object.keys(STRINGS)) {
  sheet[lang] = { ...STRINGS[lang] };
  for (const [key, value] of Object.entries(MARK_LABELS[lang])) {
    if (typeof value === "string") sheet[lang][`mark_${key}`] = value;
    else for (const [step, text] of Object.entries(value)) sheet[lang][`mark_step_${step}`] = text;
  }
}
await writeFile(`${out}/i18n.json`, JSON.stringify(sheet, null, 2));
```

- **`--wording <out_dir>`.** In `portal_bench.py`, add `parser.add_argument("--wording", metavar="OUT_DIR")` and, after the `--walk-ok` branch in `handle`:

```python
        if options["wording"]:
            self._wording(form, Path(str(options["wording"])))
            return
```

  with (importing `json`, `Path` from `pathlib` and `escape` from `django.utils.html`):

```python
    def _wording(self, form: PortalForm, out: Path) -> None:
        """One table per recorded page, in walk order: every message in az, tr,
        ru and en, beside the page's own control labels, with a link to the
        page's saved copy written next to the sheet -- never the live portal."""
        dist = Path(__file__).resolve().parents[4] / "extension" / "dist" / "i18n.json"
        catalogue: dict[str, dict[str, str]] = json.loads(dist.read_text())
        out.mkdir(parents=True, exist_ok=True)
        store = S3ObjectStore()
        parts: list[str] = ["<!doctype html><meta charset='utf-8'><title>Wording</title>"]
        records = PageRecord.objects.filter(
            portal_form=form, source=PageRecord.Source.BENCH_WALK
        ).order_by("step")
        for record in records:
            copy = f"page-{record.step}.html"
            (out / copy).write_bytes(store.get(record.html_key))
            snapshot = record.snapshot if isinstance(record.snapshot, dict) else {}
            controls = snapshot.get("controls", [])
            labels = ", ".join(escape(str(c.get("label", ""))) for c in controls)
            parts.append(
                f"<h2>{escape(record.page_kind)} · step {record.step}</h2>"
                f"<p><a href='{copy}'>saved copy</a> · labels on this page: {labels}</p>"
                "<table><tr><th>key</th><th>az</th><th>tr</th><th>ru</th><th>en</th></tr>"
            )
            for key in sorted(catalogue["en"]):
                cells = "".join(
                    f"<td>{escape(catalogue[lang][key])}</td>" for lang in ("az", "tr", "ru", "en")
                )
                parts.append(f"<tr><td>{escape(key)}</td>{cells}</tr>")
            parts.append("</table>")
        (out / "wording.html").write_text("".join(parts), encoding="utf-8")
        self.stdout.write(f"wrote {out / 'wording.html'}")
```

  (`parents[4]` from `apps/portals/management/commands/portal_bench.py` is the repository root.)

- [ ] **Step 3: Run; expect pass.**

Run: `npm --prefix extension run check && POSTGRES_DB=elmify_copilot_learning uv run pytest -q tests/portals/test_bench_wording.py`

- [ ] **Step 4: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add extension/build.mjs extension/src apps/portals tests/portals
git -C /home/orkhan/Desktop/copilot-learning commit -m "feat(portals): the four-language wording sheet, mark labels included

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Gates, runbook and CLAUDE.md

- [ ] **Step 1: Run every gate.**

```bash
cd /home/orkhan/Desktop/copilot-learning
uv run ruff check .
uv run mypy apps config
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
npm --prefix extension run check
POSTGRES_DB=elmify_copilot_learning uv run pytest -q
POSTGRES_DB=elmify_copilot_learning uv run pytest -q -m extension tests/portals
```

Expected: all clean. Record any failure that is already present on the base branch, with the command that shows it there.

- [ ] **Step 2: Runbook and CLAUDE.md.**
- Create `docs/runbooks/portal-bench.md`:
  1. sign in to the platform dashboard (MFA), click the toolbar button to pair the extension to the operator account;
  2. `uv run python manage.py portal_bench --operator <email> --queue` lists what to walk;
  3. walk the real application in the owner's own portal account; on every page choose the form and the page kind in the panel's Test bench section and press "Record this page" (LOGIN and SIGNUP with the password rules as the portal states them); stop before Submit;
  4. once login and sign-up behaved as spec §6 says, run `portal_bench <form> --operator <email> --walk-ok LOGIN` and `--walk-ok SIGNUP`;
  5. run `portal_bench <form> --operator <email>`; set the rules it suggests (`value_formats`, `option_synonyms`, `readback_equivalences`) or correct the map, and re-run until CLEAN;
  6. run `--wording <dir>` and read every message in all four languages against each page;
  7. run `--promote`.

  It also states the two never-rules (no sample-student account on a live portal; no Next or Submit on a live portal), that recordings are kept and never served to tenants (owner, 2026-10-09), and the SSO limit: a login on a host other than the form's cannot be recorded yet.
- Add to CLAUDE.md's Phase 3 section: "A bench-verified map (`FieldMap.verified_at`, plan 6) outranks a tenant-learned one and serves every tenant until a live relearn marks its form `needs_bench`; that is the 'promotion after a human looks' this section said was not built. `PageRecord` and bench HTML are kept, never served to a tenant view, and not reached by erasure (owner, 2026-10-09: no student value by construction)."

- [ ] **Step 3: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-learning add docs/runbooks/portal-bench.md CLAUDE.md
git -C /home/orkhan/Desktop/copilot-learning commit -m "docs: the portal bench runbook; CLAUDE.md records the verified gate and recording retention

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
