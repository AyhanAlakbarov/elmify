# Application Kit and Fill Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the server-side half of the glass-box co-pilot — one object that renders as a human-readable **Application Kit** (apply by hand, any device, no extension) and as a machine-readable **Fill Packet** (what the extension types), so the two can never disagree.

**Architecture:** A new `apps/portals/packets.py` owns both renderings. `build_kit` never raises and degrades when a field map or a portal's terms will not allow filling; `mint_packet` refuses in exactly those cases and records a `PACKET` step as the authoritative record of what the platform prepared. A new read-only Django view serves the kit under the ordinary session login. No extension, no HTTP API for the extension, no browser code — those are later plans.

**Tech Stack:** Django 5 + Postgres (row-level security), Pydantic v2 for the packet schema, pytest + pytest-django, `uv` for every command.

**Spec:** `docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md` (read "Decisions", "Decisions taken with the owner", "The Fill Packet", "The Application Kit", "Data model"). Requirements context: `phased requirements.md` §5.2 and §5.5, dated 2026-09-15 amendment blocks.

## Where this plan sits

The spec covers five independently shippable subsystems. This is plan 1 of 5, and the only one the others depend on:

1. **This plan — the kit and the packet** (server only; a student can apply by hand when it lands).
2. Pairing and the extension HTTP API (`ExtensionPairing`, device token, `/ext/*` routes, `DeviceAction`).
3. The extension itself (TypeScript, Manifest V3: service worker, content script, dock).
4. Mailbox OAuth for Google and Microsoft, classification, and the device actions it feeds.
5. The deadline reminder ladder and agency counselor mode.

## Global Constraints

- Python, ruff, mypy, CI and the Dockerfile must all name the same major.minor version. Do not change any of them in this plan.
- Every command runs through `uv run`. Never invoke `pytest`, `python` or `ruff` directly.
- **Run the suite against a private database: `POSTGRES_DB=tehsil_glassbox uv run pytest -q`.** `config/settings/database.py` defaults `POSTGRES_DB` to the constant `"tehsil"`, so every worktree and every concurrent session shares one `test_tehsil` database — `CLAUDE.md`'s "test databases are per-worktree" is not true of this configuration. Measured 2026-09-15: three runs of the same clean tree gave 2458 passed, then 15 errors, then 13 errors, scattered across unrelated apps, while a run under a private name gave 2458 passed. Without the private name a green suite proves nothing and a red one accuses the wrong change.
- `pyproject.toml` sets `addopts = "-m 'not live'"`. Tests in this plan are never marked `live`.
- Tenant-scoped reads must happen inside `tenant_transaction(tenant_id)` (from `apps.tenancy.db`), which sets the `app.tenant_id` GUC that row-level security compares against. A read outside one returns zero rows in production and passes in tests, because the test role is `BYPASSRLS`.
- `PortalForm`, `FieldMap` and `RecoveryEvent` are platform-shared and carry no tenant and no student data. Never write a student value to any of them.
- A replay may only ever type a value. `apps/portals/session.py::FILL_METHODS` is `{"fill", "type", "selectOption", "selectOptionFromDropdown"}` and `is_fillable` additionally requires `arguments[:1] == ["%value%"]`. Nothing in this plan widens either.
- No new dependency is added by this plan.
- Never log a student value, a portal URL carrying a token, or a packet.
- Run `uv run ruff check`, `uv run mypy` and `uv run bandit -c pyproject.toml -r apps config` before each commit.
- **Never run `uv run ruff format` on a directory, and never on a pre-existing file.** Measured 2026-09-15 in this worktree: ruff 0.16.6 (the floor this project allows, `ruff>=0.16.6,<1`) rewrites `except (A, B, C):` to `except A, B, C:`, which is a `SyntaxError` on Python 3. Twenty-two files in this repository contain such a tuple, `apps/portals/services.py:160` among them, and Task 6 edits that file. The formatter would also rewrite 237 files unrelated to this plan, because the committed tree was formatted by some other version. Nothing in this repository's gates runs the formatter — CI runs `uv run ruff check .` and pre-commit runs Bandit — so there is nothing to conform to. Format a brand-new file you wrote if you like (`uv run ruff format path/to/new_file.py`, then confirm it still parses); never a file that existed before your task.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/portals/models.py` (modify) | `PortalForm.TermsPosture` + three columns; `Application.deadline` + `deadline_timezone` |
| `apps/portals/migrations/00XX_*.py` (create, generated) | the two migrations above |
| `apps/portals/packets.py` (create) | `ApplicationKit`, `KitQuestion`, `KitDocument`, `build_kit`; `FillPacket`, `PacketField`, `PacketDocument`, `mint_packet`; `NoFieldMap`, `PacketRefused` |
| `apps/portals/services.py` (modify) | import `NoFieldMap` from `packets` instead of defining it |
| `apps/portals/views.py` (create) | the kit page — one view, context dict only |
| `apps/portals/urls.py` (create) | one route |
| `config/urls.py` (modify) | include `apps.portals.urls` |
| `tests/templates/portals/kit.html` (create) | render-nothing stub, per `tests/templates/README.md` |
| `tests/portals/test_kit.py` (create) | `build_kit` behaviour |
| `tests/portals/test_packet.py` (create) | `mint_packet` behaviour and refusals |
| `tests/portals/test_kit_view.py` (create) | authorization and tenant isolation of the page |

---

### Task 1: A portal's terms posture

**Files:**
- Modify: `apps/portals/models.py` (the `PortalForm` class)
- Create: `apps/portals/migrations/` — one generated migration
- Test: `tests/portals/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PortalForm.TermsPosture` (`SILENT`, `PERSONAL_ACCOUNT_ONLY`, `AGENT_CHANNEL`, `PROHIBITS_AUTOMATION`), `PortalForm.terms_posture: str` defaulting to `SILENT`, `PortalForm.terms_url: str`, `PortalForm.terms_read_on: date | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_models.py`:

```python
def test_a_new_portal_form_is_silent_about_automation(db) -> None:
    """Default posture is SILENT, not permissive-by-omission and not blocking.

    A portal nobody has read the terms of must not block filling (that would
    stop every new portal) and must not be recorded as having been cleared.
    """
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="k1")

    assert form.terms_posture == PortalForm.TermsPosture.SILENT
    assert form.terms_url == ""
    assert form.terms_read_on is None


def test_terms_posture_rejects_a_value_outside_the_enum(db) -> None:
    from django.db.utils import IntegrityError

    from apps.portals.models import PortalForm

    with pytest.raises(IntegrityError):
        PortalForm.objects.create(
            portal_host="apply.example.edu", form_key="k2", terms_posture="MAYBE"
        )
```

Make sure `import pytest` is present at the top of that file.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/portals/test_models.py -k terms -v`
Expected: FAIL with `AttributeError: type object 'PortalForm' has no attribute 'TermsPosture'`.

- [ ] **Step 3: Add the field and the constraint**

In `apps/portals/models.py`, inside `class PortalForm`, after `resolution_approved`:

```python
    class TermsPosture(models.TextChoices):
        """What this portal's own terms say about a tool filling its form.

        Read once per portal and recorded, because the answer is a fact about a
        third party rather than a judgement we can re-derive. A sample of seven
        portals read 2026-09-15 (spec, owner decision 9) found none prohibiting
        automated tools or autofill in the applicant's own session, and every
        one of them making the account personal -- so PERSONAL_ACCOUNT_ONLY is
        the common case and it does not block anything here. Only an explicit
        prohibition does.
        """

        SILENT = "SILENT", "Terms say nothing about automation"
        PERSONAL_ACCOUNT_ONLY = "PERSONAL_ACCOUNT_ONLY", "Personal account, no credential sharing"
        AGENT_CHANNEL = "AGENT_CHANNEL", "A sanctioned agent route exists"
        PROHIBITS_AUTOMATION = "PROHIBITS_AUTOMATION", "Automated tools prohibited"

    #: Default SILENT: an unread portal is served normally. Only
    #: PROHIBITS_AUTOMATION changes behaviour, and it makes the portal
    #: kit-only -- the cost of ignoring an explicit prohibition lands on the
    #: student's application, not on us.
    terms_posture = models.CharField(
        max_length=30, choices=TermsPosture.choices, default=TermsPosture.SILENT
    )
    terms_url = models.URLField(max_length=500, blank=True)
    terms_read_on = models.DateField(null=True, blank=True)
```

And in `PortalForm.Meta.constraints`, alongside the existing `UniqueConstraint`:

```python
            models.CheckConstraint(
                condition=models.Q(
                    terms_posture__in=(
                        "SILENT",
                        "PERSONAL_ACCOUNT_ONLY",
                        "AGENT_CHANNEL",
                        "PROHIBITS_AUTOMATION",
                    )
                ),
                name="portal_form_terms_posture_valid",
            ),
```

- [ ] **Step 4: Generate and inspect the migration**

Run: `uv run python manage.py makemigrations portals`
Then read the generated file and confirm it contains exactly three `AddField` operations and one `AddConstraint`, and nothing else.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/portals/test_models.py -v`
Expected: PASS, including the pre-existing tests in that file.

- [ ] **Step 6: Commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
git add apps/portals/models.py apps/portals/migrations tests/portals/test_models.py
git commit -m "feat(portals): record what a portal's terms say about automation"
```

---

### Task 2: An application carries its own deadline

**Files:**
- Modify: `apps/portals/models.py` (the `Application` class)
- Create: `apps/portals/migrations/` — one generated migration
- Test: `tests/portals/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Application.deadline: datetime | None`, `Application.deadline_timezone: str`.

Context for the implementer: there is no deadline column anywhere in this codebase today. `apps/portals/escalation.py` says so in a comment, and the 2026-09-15 discovery audit confirms neither `Program` nor `FundingOpportunity` carries an application date. The kit has to show one and the later reminder ladder has to read one, so it belongs on the application it is a deadline for.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_models.py`:

```python
def test_an_application_may_carry_a_deadline_in_the_portal_s_own_timezone(
    agency_a, membership_a
) -> None:
    """Stored in the portal's zone, shown in the student's.

    A deadline of "1 December" means midnight where the portal is, and a
    student in another country who reads it as their own midnight submits a
    day late.
    """
    from datetime import datetime, timezone as dt_timezone
    from uuid import uuid4

    from apps.portals.models import Application, PortalForm
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="deadline")
        application = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            deadline=datetime(2026, 12, 1, 23, 59, tzinfo=dt_timezone.utc),
            deadline_timezone="Europe/Berlin",
        )
        application.refresh_from_db()

    assert application.deadline.year == 2026
    assert application.deadline_timezone == "Europe/Berlin"


def test_an_application_without_a_deadline_is_legal(agency_a, membership_a) -> None:
    """Most applications reach the pipeline before anyone has read a date off
    the programme's page. A required column would block the pipeline on the
    discovery gap rather than on anything about this application."""
    from uuid import uuid4

    from apps.portals.models import Application, PortalForm
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="nodeadline")
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )

    assert application.deadline is None
    assert application.deadline_timezone == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/portals/test_models.py -k deadline -v`
Expected: FAIL with `TypeError: Application() got unexpected keyword arguments: 'deadline'`.

- [ ] **Step 3: Add the fields**

In `apps/portals/models.py`, inside `class Application`, after `exception_item`:

```python
    #: When this application is due. Nullable because most applications enter
    #: the pipeline before anyone has read a date off the programme's page, and
    #: no catalog column holds one yet (2026-09-15 discovery audit).
    deadline = models.DateTimeField(null=True, blank=True)
    #: IANA name of the zone the portal states its deadline in, e.g.
    #: "Europe/Berlin". Stored beside the instant because the reminder ladder
    #: and the kit both render it to the student's own zone, and "1 December"
    #: read in the wrong zone is a day late.
    deadline_timezone = models.CharField(max_length=64, blank=True)
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations portals`
Confirm it contains two `AddField` operations and nothing else.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/portals/test_models.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
git add apps/portals/models.py apps/portals/migrations tests/portals/test_models.py
git commit -m "feat(portals): an application carries its own deadline and zone"
```

---

### Task 3: `build_kit` — questions and answers from the field map

**Files:**
- Create: `apps/portals/packets.py`
- Test: `tests/portals/test_kit.py`

**Interfaces:**
- Consumes: `apps.portals.models.Application`, `FieldMap.current_for`, `apps.portals.profile.verified_values`, `apps.tenancy.db.tenant_transaction`.
- Produces:
  - `KitQuestion(profile_field: str, label: str, answer: str, missing: bool)` — frozen dataclass.
  - `KitDocument(label: str, filename: str, download_path: str, draft_id: UUID)` — frozen dataclass (filled in Task 5; declare it now with the fields listed).
  - `ApplicationKit(application_id, portal_host, form_url, apply_with_email, deadline, deadline_timezone, state, questions, requirements, documents, fillable, not_fillable_reason)` — frozen dataclass; `questions: tuple[KitQuestion, ...]`, `requirements: tuple[str, ...]`, `documents: tuple[KitDocument, ...]`.
  - `build_kit(application: Application) -> ApplicationKit` — never raises.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_kit.py`:

```python
"""build_kit: everything a human needs to apply by hand, and it never raises.

The kit is the layer that works with no extension, on any device. Where
mint_packet refuses, the kit degrades -- that asymmetry is the design.
"""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

ENTRIES = [
    {
        "profile_field": "identity.full_name",
        "action": {
            "selector": "#name",
            "description": "Full name",
            "method": "fill",
            "arguments": ["%value%"],
        },
    },
    {
        "profile_field": "personal.city",
        "action": {
            "selector": "#city",
            "description": "City of residence",
            "method": "fill",
            "arguments": ["%value%"],
        },
    },
]


def _application(agency, student, *, entries=ENTRIES, **form_kwargs):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"kit-{uuid4()}",
        form_url="https://apply.example.edu/personal",
        review_required=False,
        **form_kwargs,
    )
    if entries is not None:
        FieldMap.objects.create(portal_form=form, version=1, entries=entries)
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_the_kit_carries_the_portal_s_questions_in_the_portal_s_order(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        kit = packets.build_kit(application)

    assert [q.profile_field for q in kit.questions] == [
        "identity.full_name",
        "personal.city",
    ]
    assert [q.label for q in kit.questions] == ["Full name", "City of residence"]
    assert [q.answer for q in kit.questions] == ["Ada Byron", "London"]
    assert [q.missing for q in kit.questions] == [False, False]
    assert kit.fillable is True
    assert kit.not_fillable_reason == ""
    assert kit.portal_host == "apply.example.edu"
    assert kit.form_url == "https://apply.example.edu/personal"


def test_a_fact_we_do_not_hold_is_shown_as_missing_and_the_kit_is_still_built(
    agency_a, membership_a, monkeypatch
) -> None:
    """A missing fact refuses a packet. It must not refuse a kit: the student
    can still answer that one field by hand, and hiding the rest helps nobody."""
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        kit = packets.build_kit(application)

    assert [(q.profile_field, q.missing) for q in kit.questions] == [
        ("identity.full_name", False),
        ("personal.city", True),
    ]
    assert kit.questions[1].answer == ""


def test_a_portal_whose_terms_prohibit_automation_still_gets_a_kit(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import PortalForm

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a,
            membership_a,
            terms_posture=PortalForm.TermsPosture.PROHIBITS_AUTOMATION,
        )

        kit = packets.build_kit(application)

    assert len(kit.questions) == 2
    assert kit.fillable is False
    assert kit.not_fillable_reason == "automation_prohibited"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/portals/test_kit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.portals.packets'`.

- [ ] **Step 3: Write the minimal implementation**

Create `apps/portals/packets.py`:

```python
"""The Application Kit and the Fill Packet: one object, two renderings.

The kit is what a human reads and types by hand -- any device, no extension,
nothing of ours touching the portal. The packet is the same preparation with
selectors attached, for the extension to type. They are built from one source
here so they cannot disagree about what this student is applying with.

The asymmetry is deliberate and load-bearing: build_kit never raises and
degrades, mint_packet refuses. A student whose portal cannot be filled
automatically has lost speed, not the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from apps.tenancy.db import tenant_transaction

from .models import Application, FieldMap, PortalForm
from .profile import verified_values


@dataclass(frozen=True)
class KitQuestion:
    """One field of the portal's form, with the answer we hold for it."""

    profile_field: str
    label: str
    answer: str
    missing: bool


@dataclass(frozen=True)
class KitDocument:
    """One approved document, and where the student downloads it."""

    label: str
    filename: str
    download_path: str
    draft_id: UUID


@dataclass(frozen=True)
class ApplicationKit:
    application_id: UUID
    portal_host: str
    form_url: str
    apply_with_email: str
    deadline: datetime | None
    deadline_timezone: str
    state: str
    questions: tuple[KitQuestion, ...]
    requirements: tuple[str, ...]
    documents: tuple[KitDocument, ...]
    fillable: bool
    not_fillable_reason: str


def _not_fillable_reason(form: PortalForm, field_map: FieldMap | None) -> str:
    if form.terms_posture == PortalForm.TermsPosture.PROHIBITS_AUTOMATION:
        return "automation_prohibited"
    if field_map is None:
        return "no_field_map"
    return ""


def _questions_from_map(field_map: FieldMap, values: dict[str, str]) -> tuple[KitQuestion, ...]:
    questions = []
    for entry in field_map.entries:
        field = str(entry["profile_field"])
        answer = (values.get(field) or "").strip()
        action = entry.get("action") or {}
        questions.append(
            KitQuestion(
                profile_field=field,
                label=str(action.get("description") or field),
                answer=answer,
                missing=not answer,
            )
        )
    return tuple(questions)


def build_kit(application: Application) -> ApplicationKit:
    """Everything a human needs to apply by hand. Never raises."""
    form = application.portal_form
    field_map = FieldMap.current_for(form)
    with tenant_transaction(application.tenant_id):
        values = verified_values(application.student)
        apply_with_email = application.student.application_email
    reason = _not_fillable_reason(form, field_map)
    questions = _questions_from_map(field_map, values) if field_map else ()
    return ApplicationKit(
        application_id=application.id,
        portal_host=form.portal_host,
        form_url=form.form_url,
        apply_with_email=apply_with_email,
        deadline=application.deadline,
        deadline_timezone=application.deadline_timezone,
        state=application.state,
        questions=questions,
        requirements=(),
        documents=(),
        fillable=reason == "",
        not_fillable_reason=reason,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/portals/test_kit.py -v`
Expected: PASS, three tests.

- [ ] **Step 5: Commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
git add apps/portals/packets.py tests/portals/test_kit.py
git commit -m "feat(portals): build an application kit from the portal's field map"
```

---

### Task 4: `build_kit` degrades when no field map exists

**Files:**
- Modify: `apps/portals/packets.py`
- Test: `tests/portals/test_kit.py`

**Interfaces:**
- Consumes: `ApplicationKit`, `build_kit` from Task 3; `apps.funding.models.ProgramStatement`.
- Produces: `build_kit` fills `requirements` from the programme's `REQUIRED` statements, and fills `questions` from every verified value when there is no field map.

Context: inventing portal questions we have not mapped would be the one dishonest thing a kit could do. Without a map the kit shows what we actually hold, plus the programme's own requirement sentences as a checklist.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_kit.py`:

```python
def _statement(program, text, *, kind="DOCUMENT", requirement="REQUIRED"):
    from django.utils import timezone

    from apps.funding.models import (
        OfficialSource,
        OfficialSourceSnapshot,
        ProgramStatement,
    )

    source = OfficialSource.objects.create(
        canonical_url=f"https://official.example/{uuid4()}",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key=f"official-sources/{uuid4()}",
        s3_version_id="1",
        sha256="a" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=timezone.now(),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=1,
    )
    return ProgramStatement.objects.create(
        program=program,
        snapshot=snapshot,
        kind=kind,
        requirement=requirement,
        text=text,
        label=text[:40],
    )


def test_without_a_field_map_the_kit_shows_what_we_hold_and_the_programme_checklist(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """No map means we do not know the portal's questions. Inventing them is
    the one dishonest thing a kit could do, so it shows our answers instead."""
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"personal.city": "London", "identity.full_name": "Ada Byron"},
    )
    program = program_factory()
    _statement(program, "Submit a curriculum vitae.")
    _statement(program, "A motivation letter is desired.", requirement="DESIRED")

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(
            portal_host="apply.example.edu",
            form_key=f"kit-nomap-{uuid4()}",
            form_url="https://apply.example.edu/personal",
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert kit.fillable is False
    assert kit.not_fillable_reason == "no_field_map"
    # Stable order, so two reads of one kit do not shuffle under the student.
    assert [q.profile_field for q in kit.questions] == [
        "identity.full_name",
        "personal.city",
    ]
    assert all(q.missing is False for q in kit.questions)
    # REQUIRED only: a DESIRED statement is not a checklist item.
    assert kit.requirements == ("Submit a curriculum vitae.",)


def test_a_kit_for_a_programme_we_have_never_read_has_an_empty_checklist(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=None)

        kit = packets.build_kit(application)

    assert kit.requirements == ()
    assert kit.questions == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/portals/test_kit.py -k without_a_field_map -v`
Expected: FAIL — `kit.questions` is `()` and `kit.requirements` is `()`, so the assertion on `profile_field` fails first.

- [ ] **Step 3: Write the implementation**

In `apps/portals/packets.py`, add the import:

```python
from apps.funding.models import ProgramStatement
```

Add the two helpers above `build_kit`:

```python
def _questions_from_values(values: dict[str, str]) -> tuple[KitQuestion, ...]:
    """Every answer we hold, in a stable order.

    Used only when no field map exists. The portal's real questions are
    unknown then, and making some up would put words in the portal's mouth.
    """
    return tuple(
        KitQuestion(profile_field=field, label=field, answer=answer, missing=False)
        for field, answer in sorted(values.items())
        if answer.strip()
    )


def _requirements(application: Application) -> tuple[str, ...]:
    """The programme's own REQUIRED sentences, as a checklist.

    Shared-catalog rows, read outside the tenant transaction on purpose:
    ProgramStatement carries no tenant column.
    """
    return tuple(
        ProgramStatement.objects.filter(
            program_id=application.program_id,
            requirement=ProgramStatement.Requirement.REQUIRED,
        )
        .order_by("text")
        .values_list("text", flat=True)
    )
```

Then replace the two lines in `build_kit` that compute `questions` and pass `requirements=()`:

```python
    questions = (
        _questions_from_map(field_map, values)
        if field_map
        else _questions_from_values(values)
    )
```

and

```python
        requirements=_requirements(application),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/portals/test_kit.py -v`
Expected: PASS, five tests.

- [ ] **Step 5: Commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
git add apps/portals/packets.py tests/portals/test_kit.py
git commit -m "feat(portals): a kit degrades to held answers plus the programme checklist"
```

---

### Task 5: The kit's documents

**Files:**
- Modify: `apps/portals/packets.py`
- Test: `tests/portals/test_kit.py`

**Interfaces:**
- Consumes: `apps.documents.models.DocumentDraft`, `apps.documents.storage.artefact_filename`, the URL name `documents-download`.
- Produces: `_kit_documents(application) -> tuple[KitDocument, ...]`, used by `build_kit` and reused by `mint_packet` in Task 6.

Context: the only exit for a rendered document is `apps/documents/views.py::download_document`, which is `@login_required`, refuses anything not `APPROVED`, and answers 404 to every refusal. The kit links to that route; no presigned or public URL is ever created.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_kit.py`:

```python
def _approved_cv(agency, student, programme=None):
    from apps.documents.models import DocumentDraft

    return DocumentDraft.objects.create(
        tenant=agency,
        student=student,
        kind=DocumentDraft.Kind.CV,
        version=1,
        content={},
        render_variant=DocumentDraft.RenderVariant.STANDARD,
        status=DocumentDraft.Status.APPROVED,
        programme=programme,
    )


def test_the_kit_links_approved_documents_through_the_download_route(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import Application, FieldMap, PortalForm

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    program = program_factory()
    with tenant_scope(agency_a.id):
        draft = _approved_cv(agency_a, membership_a, programme=program)
        form = PortalForm.objects.create(
            portal_host="apply.example.edu",
            form_key=f"kit-docs-{uuid4()}",
            form_url="https://apply.example.edu/personal",
        )
        FieldMap.objects.create(portal_form=form, version=1, entries=ENTRIES)
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert [d.draft_id for d in kit.documents] == [draft.id]
    assert kit.documents[0].filename == "cv-standard.pdf"
    assert kit.documents[0].download_path == f"/documents/{draft.id}/cv-standard.pdf"
    assert kit.documents[0].label == "CV"


def test_an_unapproved_draft_is_not_in_the_kit(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """The download route refuses anything not APPROVED, so listing one would
    be a link that 404s -- and a counselor's unfinished draft is not something
    to put in front of a portal."""
    from apps.documents.models import DocumentDraft
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    program = program_factory()
    with tenant_scope(agency_a.id):
        DocumentDraft.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            version=1,
            content={},
            render_variant=DocumentDraft.RenderVariant.STANDARD,
            status=DocumentDraft.Status.DRAFT,
            programme=program,
        )
        form = PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"kit-unapproved-{uuid4()}"
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert kit.documents == ()


def test_another_programme_s_document_is_not_in_this_application_s_kit(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    mine, theirs = program_factory(), program_factory()
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a, programme=theirs)
        form = PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"kit-other-{uuid4()}"
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=mine.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert kit.documents == ()


def test_a_programme_agnostic_document_is_in_every_kit(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """A CV generated without a programme is the student's general one and
    applies everywhere; dropping it would leave a kit with no CV at all."""
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    program = program_factory()
    with tenant_scope(agency_a.id):
        draft = _approved_cv(agency_a, membership_a, programme=None)
        form = PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"kit-generic-{uuid4()}"
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert [d.draft_id for d in kit.documents] == [draft.id]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/portals/test_kit.py -k document -v`
Expected: FAIL — `kit.documents` is `()` where a draft is expected.

- [ ] **Step 3: Write the implementation**

In `apps/portals/packets.py`, add imports:

```python
from django.db.models import Q
from django.urls import reverse

from apps.documents.models import DocumentDraft
from apps.documents.storage import artefact_filename
```

Add the helper above `build_kit`:

```python
def _kit_documents(application: Application) -> tuple[KitDocument, ...]:
    """Approved documents for this application, linked through the one route
    that exists.

    `download_document` is @login_required, refuses anything not APPROVED and
    answers 404 to every refusal, so the kit links to it rather than minting a
    presigned URL -- `apps/documents/storage.py` says never a presigned URL and
    means it.

    A draft with no programme is the student's general document and belongs in
    every kit; one attached to another programme belongs in none of them.
    """
    drafts = (
        DocumentDraft.objects.filter(
            student=application.student, status=DocumentDraft.Status.APPROVED
        )
        .filter(Q(programme_id=application.program_id) | Q(programme__isnull=True))
        .order_by("kind", "version")
    )
    documents = []
    for draft in drafts:
        filename = artefact_filename(draft.render_variant)
        documents.append(
            KitDocument(
                # draft.kind, not get_kind_display(): TextChoices derives the
                # label from the member name, so DocumentDraft.Kind.CV
                # displays as "Cv". Measured, not assumed.
                label=draft.kind,
                filename=filename,
                download_path=reverse("documents-download", args=[draft.id, filename]),
                draft_id=draft.id,
            )
        )
    return tuple(documents)
```

In `build_kit`, inside the `tenant_transaction` block, add:

```python
        documents = _kit_documents(application)
```

and pass `documents=documents` instead of `documents=()`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/portals/test_kit.py -v`
Expected: PASS, nine tests.

- [ ] **Step 5: Commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
git add apps/portals/packets.py tests/portals/test_kit.py
git commit -m "feat(portals): a kit links this application's approved documents"
```

---

### Task 6: `mint_packet` and the PACKET step

**Files:**
- Modify: `apps/portals/packets.py`, `apps/portals/services.py`
- Test: `tests/portals/test_packet.py`

**Interfaces:**
- Consumes: everything from Tasks 3–5; `apps.portals.session.FieldAction`, `is_fillable`; `apps.portals.models.ApplicationStep`.
- Produces:
  - `PacketField(selector: str, method: str, value: str)`, `PacketDocument(filename: str, download_path: str, draft_id: UUID)`, `FillPacket(application_id, portal_form_id, field_map_version, form_url, entries, documents, issued_at, expires_at, min_extension_version)` — Pydantic models, `extra="forbid"`, frozen.
  - `mint_packet(application: Application) -> FillPacket`.
  - `NoFieldMap` moves here from `services.py`; `services.py` imports it.
  - Module constants `PACKET_TTL = timedelta(hours=2)` and `MIN_EXTENSION_VERSION = "0.1.0"`.

The packet field list is called `entries`, not `fields` or `values`, because both of those shadow Pydantic model attributes.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_packet.py`:

```python
"""mint_packet: what the extension types, and the record of what we prepared.

The PACKET step is the authoritative "what the platform prepared" row in the
§5.5 trail. The extension's later report is an attestation from a device we do
not control; this row is ours.
"""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.test_kit import ENTRIES, _application

pytestmark = pytest.mark.django_db


def test_the_packet_carries_one_entry_per_mapped_field(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        packet = packets.mint_packet(application)

    assert [(e.selector, e.method, e.value) for e in packet.entries] == [
        ("#name", "fill", "Ada Byron"),
        ("#city", "fill", "London"),
    ]
    assert packet.field_map_version == 1
    assert packet.form_url == "https://apply.example.edu/personal"
    assert packet.expires_at > packet.issued_at


def test_minting_records_a_packet_step_carrying_what_we_prepared(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import ApplicationStep

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        packets.mint_packet(application)

        step = ApplicationStep.objects.get(application=application, kind="PACKET")

    assert step.detail["field_map_version"] == 1
    assert step.detail["values"] == {"#name": "Ada Byron", "#city": "London"}
    assert step.detail["documents"] == []


def test_the_kit_and_the_packet_never_disagree(agency_a, membership_a, monkeypatch) -> None:
    """The load-bearing claim of the design: one object, two renderings.

    If these ever drift, a student reads one set of answers on the dashboard
    and a different set gets typed into the portal.
    """
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        kit = packets.build_kit(application)
        packet = packets.mint_packet(application)

    assert [q.answer for q in kit.questions] == [e.value for e in packet.entries]
    assert [d.draft_id for d in kit.documents] == [d.draft_id for d in packet.documents]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/portals/test_packet.py -v`
Expected: FAIL with `AttributeError: module 'apps.portals.packets' has no attribute 'mint_packet'`.

- [ ] **Step 3: Write the implementation**

In `apps/portals/packets.py`, add imports:

```python
from datetime import timedelta

from django.utils import timezone
from pydantic import BaseModel, ConfigDict

from .session import FieldAction, is_fillable
```

Add the constants below the module docstring's imports:

```python
#: A packet is a snapshot of verified facts. Two hours keeps a tab left open
#: overnight from filling yesterday's answers; the extension refetches.
PACKET_TTL = timedelta(hours=2)

#: The oldest extension build whose semantics match this packet shape. An older
#: one refuses the packet and asks to update rather than filling on a guess.
MIN_EXTENSION_VERSION = "0.1.0"
```

Add the exceptions and models:

```python
class NoFieldMap(Exception):
    """The portal form has never been learned. A caller must run the learn pass."""


class PacketRefused(Exception):
    """No packet for this application, with a stable machine-readable reason.

    The reason is matched on by the HTTP layer and by the dashboard, so it must
    not become a sentence anyone will later reword.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PacketField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: str
    method: str
    value: str


class PacketDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    download_path: str
    draft_id: UUID


class FillPacket(BaseModel):
    """What the extension types, and nothing else.

    No credential, no token, no payment field. `entries` rather than `fields`
    or `values`: both shadow Pydantic model attributes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: UUID
    portal_form_id: UUID
    field_map_version: int
    form_url: str
    entries: tuple[PacketField, ...]
    documents: tuple[PacketDocument, ...]
    issued_at: datetime
    expires_at: datetime
    min_extension_version: str
```

Add `mint_packet` and its step writer at the end of the module:

```python
def _record_packet(application: Application, packet: FillPacket) -> None:
    """The §5.5 row for what the platform prepared.

    Its own short transaction, matching services._record: the trail must
    survive a later failure in the same request.
    """
    from .models import ApplicationStep

    with tenant_transaction(application.tenant_id):
        ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind="PACKET",
            detail={
                "field_map_version": packet.field_map_version,
                "values": {entry.selector: entry.value for entry in packet.entries},
                "documents": [
                    {"draft_id": str(document.draft_id), "filename": document.filename}
                    for document in packet.documents
                ],
            },
        )


def mint_packet(application: Application) -> FillPacket:
    """Prepare one application for the extension, or refuse and say why.

    Runs the same pre-checks prepare_application ran before it opened a
    browser, in the same order and for the same reason: there is no point
    handing a student a portal tab for an application that cannot be completed.
    """
    from .escalation import Trigger, escalate

    form = application.portal_form
    if form.terms_posture == PortalForm.TermsPosture.PROHIBITS_AUTOMATION:
        raise PacketRefused("automation_prohibited")
    field_map = FieldMap.current_for(form)
    if field_map is None:
        raise NoFieldMap(f"{form.portal_host} has no current field map")
    with tenant_transaction(application.tenant_id):
        values = verified_values(application.student)
        documents = _kit_documents(application)
    missing = sorted(
        str(entry["profile_field"])
        for entry in field_map.entries
        if not (values.get(str(entry["profile_field"])) or "").strip()
    )
    if missing:
        escalate(application, Trigger.MISSING_FACT, detail=", ".join(missing))
        raise PacketRefused("missing_fact")
    entries = []
    for entry in field_map.entries:
        action = FieldAction.model_validate(entry["action"])
        if not is_fillable(action):
            # A row stored before is_fillable existed outlives it. Refusing
            # here is the third enforcement point, matching fill.py's pre-pass.
            raise PacketRefused("unsafe_action")
        entries.append(
            PacketField(
                selector=action.selector,
                method=(action.method or "").strip(),
                value=values[str(entry["profile_field"])],
            )
        )
    issued_at = timezone.now()
    packet = FillPacket(
        application_id=application.id,
        portal_form_id=form.id,
        field_map_version=field_map.version,
        form_url=form.form_url,
        entries=tuple(entries),
        documents=tuple(
            PacketDocument(
                filename=document.filename,
                download_path=document.download_path,
                draft_id=document.draft_id,
            )
            for document in documents
        ),
        issued_at=issued_at,
        expires_at=issued_at + PACKET_TTL,
        min_extension_version=MIN_EXTENSION_VERSION,
    )
    _record_packet(application, packet)
    return packet
```

`escalate` is imported inside the function: `escalation.py` imports from `.models`, and a module-level import here would make the cycle harder to reason about for no benefit.

In `apps/portals/services.py`, delete the local `NoFieldMap` class and import it instead. Replace:

```python
class NoFieldMap(Exception):
    """The portal form has never been learned. A caller must run the learn pass."""
```

with nothing, and add to the imports:

```python
from .packets import NoFieldMap
```

Keep the name exported from `services` so existing callers and tests keep working.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/portals/ -v`
Expected: PASS, including every pre-existing portal test.

- [ ] **Step 5: Commit**

```bash
uv run ruff check apps/portals tests/portals
uv run mypy apps/portals
uv run bandit -c pyproject.toml -r apps config
git add apps/portals/packets.py apps/portals/services.py tests/portals/test_packet.py
git commit -m "feat(portals): mint a fill packet and record what we prepared"
```

---

### Task 7: The four refusals

**Files:**
- Test only: `tests/portals/test_packet.py`

**Interfaces:**
- Consumes: `mint_packet`, `PacketRefused`, `NoFieldMap` from Task 6.
- Produces: nothing new. This task proves the refusal paths and fixes whatever it finds.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_packet.py`:

```python
def test_a_portal_that_prohibits_automation_refuses_before_anything_else(
    agency_a, membership_a, monkeypatch
) -> None:
    """Checked first, deliberately: a prohibited portal must not escalate a
    missing fact, write a step, or read a single verified value."""
    from apps.portals import packets
    from apps.portals.models import ApplicationStep, PortalForm

    def _explode(student):
        raise AssertionError("verified_values must not be read for a prohibited portal")

    monkeypatch.setattr(packets, "verified_values", _explode)
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a,
            membership_a,
            terms_posture=PortalForm.TermsPosture.PROHIBITS_AUTOMATION,
        )

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

        assert ApplicationStep.objects.filter(application=application).count() == 0

    assert refusal.value.reason == "automation_prohibited"


def test_an_unlearned_portal_raises_no_field_map(agency_a, membership_a) -> None:
    from apps.portals import packets

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=None)

        with pytest.raises(packets.NoFieldMap):
            packets.mint_packet(application)


def test_a_missing_fact_escalates_and_refuses(agency_a, membership_a, monkeypatch) -> None:
    """Same behaviour prepare_application had, for the same reason: there is no
    point opening a portal tab for an application that cannot be completed."""
    from apps.portals import packets
    from apps.portals.models import Application, ApplicationStep

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

        application.refresh_from_db()
        step = ApplicationStep.objects.get(application=application, kind="ESCALATION")

    assert refusal.value.reason == "missing_fact"
    assert application.state == Application.State.BLOCKED_MISSING_FACT
    assert step.detail["detail"] == "personal.city"
    assert not ApplicationStep.objects.filter(application=application, kind="PACKET").exists()


def test_a_stored_action_that_would_do_more_than_type_is_refused(
    agency_a, membership_a, monkeypatch
) -> None:
    """A map row stored before is_fillable existed outlives it. A click stored
    in a shared field map would fire for every student of every tenant."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {"identity.full_name": "Ada"})
    unsafe = [
        {
            "profile_field": "identity.full_name",
            "action": {"selector": "#submit", "method": "click", "arguments": ["%value%"]},
        }
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=unsafe)

        with pytest.raises(packets.PacketRefused) as refusal:
            packets.mint_packet(application)

    assert refusal.value.reason == "unsafe_action"
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/portals/test_packet.py -v`
Expected: PASS if Task 6 was implemented exactly as written. If `test_a_portal_that_prohibits_automation_refuses_before_anything_else` fails, the posture check is in the wrong place — move it to the first statement of `mint_packet`.

- [ ] **Step 3: Commit**

```bash
uv run ruff check tests/portals
git add tests/portals/test_packet.py
git commit -m "test(portals): pin the four ways a packet is refused"
```

---

### Task 8: The kit page

**Files:**
- Create: `apps/portals/views.py`, `apps/portals/urls.py`, `tests/templates/portals/kit.html`
- Modify: `config/urls.py`
- Test: `tests/portals/test_kit_view.py`

**Interfaces:**
- Consumes: `build_kit`; `apps.tenancy.services.current_membership`; `apps.tenancy.models.Membership`.
- Produces: URL name `portals-application-kit` at `/applications/<uuid:application_id>/kit`, rendering `portals/kit.html` with context `{"kit": ApplicationKit}`.

Context for the implementer: `templates/` does not exist in this repository and that is deliberate — read `tests/templates/README.md`. Views return context dicts; the presentation layer is generated later by a separate workflow. Add a render-nothing stub so the view test can assert server behaviour. `apps/tenancy/middleware.py` already opens `transaction.atomic()`, `tenant_scope()` and `set_local_tenant()` around every request, so the view does not scope anything itself.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_kit_view.py`:

```python
"""The kit page: the layer that works with no extension, on any device.

Asserts server behaviour only -- authorization and tenant isolation. There is
no presentation layer to assert on; see tests/templates/README.md.
"""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"view-{uuid4()}",
        form_url="https://apply.example.edu/personal",
    )
    FieldMap.objects.create(
        portal_form=form,
        version=1,
        entries=[
            {
                "profile_field": "identity.full_name",
                "action": {
                    "selector": "#name",
                    "description": "Full name",
                    "method": "fill",
                    "arguments": ["%value%"],
                },
            }
        ],
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_a_student_sees_their_own_kit(client, agency_a, domain_a, membership_a, user_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(user_a)

    response = client.get(
        f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 200
    assert response.context["kit"].application_id == application.id
    assert [q.label for q in response.context["kit"].questions] == ["Full name"]


def test_another_student_s_kit_is_404_not_403(
    client, agency_a, domain_a, membership_a, user_a, user_b
) -> None:
    """404, matching storage.download_document: a 403 would confirm the
    application exists."""
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        application = _application(agency_a, other)
    client.force_login(user_a)

    response = client.get(
        f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 404


def test_an_anonymous_visitor_is_not_shown_a_kit(client, agency_a, domain_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

    response = client.get(
        f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host
    )

    assert response.status_code in (302, 403)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/portals/test_kit_view.py -v`
Expected: FAIL with 404 on every test, because no such route exists.

- [ ] **Step 3: Write the view, the route and the stub**

Create `apps/portals/views.py`:

```python
"""The kit page.

One view, deliberately. The kit is the layer that works with no extension and
on any device, so it is an ordinary session-authenticated page, not part of the
extension's HTTP API.

Refusals are 404, never 403, matching apps/documents/storage.py: a 403 confirms
the object exists.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .models import Application
from .packets import build_kit


@login_required
@require_GET
def application_kit(request: HttpRequest, application_id: str) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(Application, id=application_id, student=student)
    return render(request, "portals/kit.html", {"kit": build_kit(application)})
```

Create `apps/portals/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path(
        "applications/<uuid:application_id>/kit",
        views.application_kit,
        name="portals-application-kit",
    ),
]
```

In `config/urls.py`, add to `urlpatterns` after the `apps.documents.urls` line:

```python
    path("", include("apps.portals.urls")),
```

Create `tests/templates/portals/kit.html`:

```html
{# Test stub. See tests/templates/README.md -- deliberately renders nothing. #}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/portals/test_kit_view.py -v`
Expected: PASS, three tests.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. A new URL include can shadow an existing route; if anything in `tests/tenancy` or `tests/documents` fails, the new path is too greedy — it is not, at `applications/<uuid>/kit`, but check rather than assume.

- [ ] **Step 6: Commit**

```bash
uv run ruff check apps/portals config tests
uv run mypy apps/portals
git add apps/portals/views.py apps/portals/urls.py config/urls.py tests/templates/portals/kit.html tests/portals/test_kit_view.py
git commit -m "feat(portals): serve the application kit as a page"
```

---

### Task 9: Tenant isolation under a real RLS role, and the docs

**Files:**
- Test: `tests/portals/test_kit_view.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: the `rls_enforced_orm` fixture (`tests/conftest.py`), which repoints Django's default connection at a `NOBYPASSRLS` role.
- Produces: nothing new.

Context: the suite runs as a `BYPASSRLS` superuser, so a tenant-scoped read taken outside a `tenant_transaction` returns rows in tests and zero rows in production. `build_kit` reads verified facts and document drafts, both of which are `FORCE ROW LEVEL SECURITY`. Only this fixture can show the difference.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_kit_view.py`:

```python
def test_the_kit_reads_facts_behind_the_row_level_security_policy(
    rls_enforced_orm, client, agency_a, domain_a, membership_a, user_a
) -> None:
    """Under the production role the GUC decides what exists.

    A read taken outside tenant_transaction returns every row here and nothing
    in production, so this is the only test in the file that can tell the
    difference.
    """
    from apps.documents.models import VerifiedFact

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        VerifiedFact.objects.create(
            tenant=agency_a,
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Ada Byron"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="passport.pdf",
            confirmed_at=timezone.now(),
        )
    client.force_login(user_a)

    response = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert [q.answer for q in response.context["kit"].questions] == ["Ada Byron"]
```

Add `from django.utils import timezone` to the imports at the top of that file.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/portals/test_kit_view.py -k row_level -v`
Expected: PASS. If it fails with an empty answer, a read in `build_kit` has escaped its `tenant_transaction` — fix `build_kit`, not the test.

`VerifiedFact.Category.IDENTITY` carries `{"full_name": ...}` and nothing else, and `source_tier` and `source_ref` are both required columns — all three checked against `apps/documents/models.py` on 2026-09-15. If the model has moved since, follow the model and do not change `verified_values`.

- [ ] **Step 3: Document it**

In `CLAUDE.md`, inside the "Application automation (Phase 3)" section, immediately after the 2026-09-15 direction-change block, add:

```markdown
**Built, 2026-09-15: the kit and the packet** (`apps/portals/packets.py`). `build_kit` and
`mint_packet` are one preparation with two renderings and a test pins that they cannot
disagree. The asymmetry is the design: `build_kit` never raises and degrades (no field map ->
held answers plus the programme's REQUIRED statements; `PROHIBITS_AUTOMATION` -> `fillable=False`),
`mint_packet` refuses with a stable reason (`automation_prohibited`, `missing_fact`,
`unsafe_action`, or `NoFieldMap`). Refusing is checked in that order and the posture check is
first, so a prohibited portal never reads a verified value. The `PACKET` `ApplicationStep` is
the authoritative record of what the platform prepared; whatever the extension later reports is
an attestation from a device we do not control. `Application.deadline` and `deadline_timezone`
are the first deadline columns in this codebase -- the catalog still holds none.
```

- [ ] **Step 4: Run everything**

```bash
uv run pytest -q
uv run ruff check apps tests config
uv run mypy apps
uv run bandit -c pyproject.toml -r apps config
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/portals/test_kit_view.py CLAUDE.md
git commit -m "test(portals): the kit reads facts behind the RLS policy"
```

---

## Self-review notes for the executor

Three things this plan deliberately does **not** do, so nobody adds them thinking they were forgotten:

- **No HTTP API for the extension.** `mint_packet` is a Python function with no route. Pairing, the device token and `/ext/*` are plan 2; minting over HTTP without a device token would be an unauthenticated packet endpoint.
- **No deletion of the server-side portal tier.** `auth.py`, `engine.py`, `profiles.py`, `resolve.py`, `dispatch.py`, `worker.py` and the `Portal*` CloudFormation resources stay exactly as they are, dormant at `PortalDesiredCount: 0`, until the extension passes its own tests. Deleting them here would remove the only working filler before its replacement exists.
- **No `SUBMITTED` writer.** `Application.State.SUBMITTED` still has no writer after this plan. The extension reports submission; that is plan 3.
