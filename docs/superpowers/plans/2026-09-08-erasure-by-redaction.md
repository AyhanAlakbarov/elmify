# Erasure by Redaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `advance_deletion` overwrite every database field that can carry a student's personal data before it writes `state = "EXECUTED"`, so the erasure record is legally true.

**Architecture:** A new `apps/audit/redaction.py` holds an explicit per-field classification (REDACT / KEEP / UNDECIDED) keyed by `"app_label.ModelName"`, plus the model-graph walk that proves the classification is complete. `redact_student()` runs one `UPDATE` per REDACT model, filtered to that student through a hand-written subject path. `advance_deletion` calls it inside a transaction, after the S3 and Secrets Manager purges and before the state write.

**Tech Stack:** Django ORM, Postgres (row-level security on some tables), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md`

## Global Constraints

- **Delete no rows.** Every FK, timestamp and row survives. The schema is `PROTECT` almost everywhere and a delete-based erasure raises `ProtectedError`.
- **Redaction value is the empty value for the field's type** — `""` for `CharField`/`TextField`, `{}` for `JSONField`. Never `NULL`: `NOT NULL` constraints must keep holding.
- **Fails closed.** A failure anywhere in redaction leaves the request `APPROVED`. `EXECUTED` is written only after every redaction succeeded, in the same transaction.
- **Order is load-bearing.** S3 purge runs *before* `object_key` fields are redacted, because `delete_student_documents` reads them to find the objects.
- **The graph walk scans forward FKs across `apps.get_models()`, never `Membership._meta.related_objects`.** Nine models FK `Membership` with `related_name="+"` and have no reverse accessor — including `concierge.ConversationMessage`, the counselor's free-text correspondence about the student.
- **Do not weaken an existing invariant** to make erasure easier — no relaxing `PROTECT`, no nulling `AuditEvent.actor`.
- **§10 retention periods stay open.** Nothing here may require inventing them.

---

## Correction to the spec, carried into this plan

Two findings from running the spec's own walk against the real schema. Both were measured, not inferred; the commands are in Task 1.

**1. The classification test must use the transitive closure (32 models), not a one-hop scan (22).**

The spec says a forward scan "sees 22". That number is *models with a direct FK to `Membership`* — one hop. The transitive closure is **32**. The nine models reachable only through a chain are:

```
concierge.Receipt              documents.DocumentDraftFact    funding.EvaluationExample
funding.PackCandidate          funding.PackVersion            funding.RecommendationCandidate
funding.RecommendationRun      portals.ApplicationStep        reports.ConsultationReport
```

**Four of those nine are classified in the spec's own tables** — `portals.ApplicationStep.detail` (REDACT), `reports.ConsultationReport.object_key` (REDACT), `funding.RecommendationCandidate.program_name` (KEEP), `funding.EvaluationExample.expected_structured_result` (KEEP-by-constraint). A one-hop test reaches none of them. `ApplicationStep.detail` holds "the literal values typed into a third-party application form" — named in the spec's defect list — and would be invisible to the test meant to guarantee it was classified.

This is the same failure mode the spec warns about one level up: the first draft's reverse walk missed `ConversationMessage`. The plan uses the closure.

**2. The subject path cannot be derived automatically — it must be written by hand per model.**

A shortest-path search from model to `Membership` returns *a* Membership FK, not *the student's*. It picks:

| Model | Auto-derived | Correct | Why the difference matters |
|---|---|---|---|
| `concierge.ManualOperation` | `actor_id` | `roadmap_item__student_id` | `actor` is the staff member who performed it |
| `documents.RevisionRequest` | `requested_by_id` | `document__student_id` | `requested_by` is the requester, `related_name="+"` |
| `funding.Approval` | `actor_id` | `pack_version__run__profile_version__student_id` | `actor` is the approving counselor |

Filtering `ManualOperation` by `actor_id` would redact operations performed *by* the erased person and leave every operation written *about* them. Paths are therefore data in the map, and Task 1's test forces one to exist for every REDACT model.

**3. Two fields the spec does not classify, surfaced by the closure. Both resolved 2026-09-08.**

- **`concierge.Receipt.object_key` → KEEP, by constraint.** GDPR Article 17(3)(b) withdraws the
  right to erasure where processing is necessary to comply with a legal obligation, and a statutory
  accounting-retention duty is one. German accounting receipts run 8 years under §147 AO (reduced
  from ten on 1 January 2025 by BEG IV), counted from the end of the calendar year. Nothing writes
  `Receipt` today, so this is a promise about a future writer, not an observation — the four rules
  that make it true are in the spec, and Task 6 adds the tripwire that fires when a writer appears.

- **`concierge.Notification` → REDACT via a new FK.** Not a product question: the code answers it.
  `apps/portals/escalation.py::_recipient` sends only `PERSONAL_ATTESTATION` and `APPLICANT_MFA` to
  the student; the other four triggers go to the assigned counselor carrying free text about the
  student. Redacting by `recipient_id` would leave those behind and unfindable. Task 2 gives
  `Notification` a non-null FK to `RoadmapItem` — which both writers already create, already
  carrying the right student — so `roadmap_item__student_id` covers both cases in one path.

Because both are resolved, `UNDECIDED` ships empty and erasure runs. The `UNDECIDED` class and the
test that blocks on it stay: they are the mechanism that made these two visible.

---

## File Structure

- **Create `apps/audit/redaction.py`** — the classification map, the graph walk, and `redact_student()`. One file because the map and the walk that validates it must not drift apart; a reader checking whether a field is covered reads one thing.
- **Modify `apps/audit/deletion.py`** — add the `redact_student()` call and the transaction in the `EXECUTED` branch. No other change.
- **Create `tests/audit/test_redaction_classification.py`** — the completeness test. Separate file because it is a schema-shape guard that fails for reasons unrelated to erasure behaviour (someone added a field), and that distinction should be visible in the failure.
- **Create `tests/audit/test_redaction.py`** — behaviour: redaction happened, KEEP survived, fails closed.
- **Modify `apps/concierge/models.py` and `apps/portals/escalation.py`** — the one schema change: `Notification` gains a non-null FK to `RoadmapItem` so a message about a student is findable when the recipient is somebody else. Kept in the app that owns the model rather than pulled into the audit app; erasure reads the link, it does not own it.
- **Create `tests/portals/test_notification_subject.py`** — that both writers set the link. It lives beside the escalation code it constrains, because that is where someone adding a third writer will look.

---

### Task 1: The graph walk and the completeness test

The enforcement spine. Built first and deliberately failing, so the map in Task 3 is filled to satisfy a real check rather than from reading the spec's prose.

**Files:**
- Create: `apps/audit/redaction.py`
- Create: `tests/audit/test_redaction_classification.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `student_reachable_models() -> list[type[Model]]`, `classifiable_fields(model) -> list[str]`, and the three module-level dicts `REDACT: dict[str, RedactSpec]`, `KEEP: dict[str, tuple[str, ...]]`, `UNDECIDED: dict[str, tuple[str, ...]]`. `RedactSpec` is a `NamedTuple` with fields `subject: str` and `fields: tuple[str, ...]`. Task 3 fills the dicts; Task 4 calls `redact_student`.

- [ ] **Step 1: Write the failing test**

Create `tests/audit/test_redaction_classification.py`:

```python
"""The erasure classification must cover every field that can reach a student.

This test fails when someone adds a field to a student-reachable model. That is
the point: it stops the build until erasure has an answer for the new field.
"""

from apps.audit.redaction import (
    KEEP,
    REDACT,
    UNDECIDED,
    classifiable_fields,
    student_reachable_models,
)


def _label(model):
    return f"{model._meta.app_label}.{model.__name__}"


def test_every_reachable_field_is_classified_exactly_once():
    unclassified = []
    duplicated = []
    for model in student_reachable_models():
        label = _label(model)
        classes = {
            "REDACT": set(REDACT[label].fields) if label in REDACT else set(),
            "KEEP": set(KEEP.get(label, ())),
            "UNDECIDED": set(UNDECIDED.get(label, ())),
        }
        for name in classifiable_fields(model):
            holders = [cls for cls, names in classes.items() if name in names]
            if not holders:
                unclassified.append(f"{label}.{name}")
            elif len(holders) > 1:
                duplicated.append(f"{label}.{name} in {holders}")
    assert not unclassified, "unclassified fields:\n  " + "\n  ".join(sorted(unclassified))
    assert not duplicated, "multiply classified:\n  " + "\n  ".join(sorted(duplicated))


def test_classification_names_no_field_that_does_not_exist():
    """A typo in the map is silent otherwise: it classifies nothing and hides a real field."""
    reachable = {_label(m): set(classifiable_fields(m)) for m in student_reachable_models()}
    stale = []
    for mapping, names in (
        ("REDACT", {k: v.fields for k, v in REDACT.items()}),
        ("KEEP", KEEP),
        ("UNDECIDED", UNDECIDED),
    ):
        for label, fields in names.items():
            if label not in reachable:
                stale.append(f"{mapping}: {label} is not student-reachable")
                continue
            for field in fields:
                if field not in reachable[label]:
                    stale.append(f"{mapping}: {label}.{field} does not exist")
    assert not stale, "stale classification entries:\n  " + "\n  ".join(sorted(stale))


def test_every_redact_model_has_a_subject_path():
    """Without a path, redact_student cannot find that model's rows for one student.

    The path is hand-written per model because a shortest-path search picks the
    wrong FK: ManualOperation.actor is the staff member, not the subject.
    """
    missing = [label for label, spec in REDACT.items() if not spec.subject]
    assert not missing, f"REDACT entries with no subject path: {missing}"


def test_erasure_refuses_to_run_while_anything_is_undecided():
    """UNDECIDED is a launch blocker made visible, not a parking lot.

    Delete this assertion only together with the last UNDECIDED entry.
    """
    assert UNDECIDED == {}, (
        "fields still awaiting a retention decision (phased requirements.md §10): "
        f"{UNDECIDED}"
    )


def test_walk_uses_forward_fks_and_sees_the_hidden_models():
    """A reverse walk misses models declaring related_name='+'.

    ConversationMessage.body is the counselor's free-text correspondence about
    the student and has no reverse accessor. Do not 'simplify' the walk to
    Membership._meta.related_objects.
    """
    labels = {_label(m) for m in student_reachable_models()}
    for hidden in (
        "concierge.ConversationMessage",
        "documents.ConsentEvent",
        "documents.RevisionRequest",
        "funding.ConstraintOverride",
    ):
        assert hidden in labels, f"{hidden} not reached: the walk went backwards"


def test_walk_reaches_models_that_are_more_than_one_hop_away():
    """A one-hop scan misses ApplicationStep.detail -- the values typed into a
    third-party application form -- and ConsultationReport, both REDACT."""
    labels = {_label(m) for m in student_reachable_models()}
    for distant in (
        "portals.ApplicationStep",
        "reports.ConsultationReport",
        "funding.RecommendationCandidate",
        "concierge.Receipt",
    ):
        assert distant in labels, f"{distant} not reached: the walk stopped at one hop"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/audit/test_redaction_classification.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.audit.redaction'`

- [ ] **Step 3: Write the walk, with the maps left empty**

Create `apps/audit/redaction.py`:

```python
"""GDPR erasure by redaction: overwrite personal fields, delete no rows.

Deleting rows is not available here. The model graph from Membership is PROTECT
on all but four edges, so deleting StudentProfileVersion raises ProtectedError.
Every row, FK and timestamp therefore survives an erasure; only the fields that
can single out a person are overwritten.

Design: docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md
"""

from __future__ import annotations

from typing import NamedTuple

from django.apps import apps
from django.db.models import ForeignKey, Model, OneToOneField

from apps.tenancy.models import Membership


class RedactSpec(NamedTuple):
    """How to find one student's rows on a model, and what to overwrite.

    `subject` is an ORM lookup path ending in an id, relative to the model,
    naming the FK chain that reaches the student the erasure is about. It is
    written by hand rather than derived: a shortest-path search finds *a*
    Membership FK, not the student's. ManualOperation.actor is the staff member
    who performed the operation; the subject is roadmap_item.student.
    """

    subject: str
    fields: tuple[str, ...]


def _forward_fks(model: type[Model]) -> list[ForeignKey | OneToOneField]:
    return [
        f
        for f in model._meta.get_fields()
        if isinstance(f, (ForeignKey, OneToOneField)) and f.concrete
    ]


def student_reachable_models() -> list[type[Model]]:
    """Every model whose rows can be tied to one student, Membership included.

    Forward FKs across apps.get_models(), transitively. NOT
    Membership._meta.related_objects: nine FKs to Membership declare
    related_name="+" and create no reverse accessor, so a reverse walk cannot
    see ConversationMessage, ConsentEvent, RevisionRequest or
    ConstraintOverride. ConversationMessage.body is the counselor's free-text
    correspondence about the student.

    Transitive, not one hop. ApplicationStep reaches the student only through
    Application, and ConsultationReport only through
    PackVersion -> RecommendationRun -> StudentProfileVersion; both hold REDACT
    fields and a one-hop scan classifies neither.
    """
    reached: set[type[Model]] = {Membership}
    changed = True
    while changed:
        changed = False
        for model in apps.get_models():
            if model in reached:
                continue
            if any(f.related_model in reached for f in _forward_fks(model)):
                reached.add(model)
                changed = True
    return sorted(reached, key=lambda m: (m._meta.app_label, m.__name__))


def classifiable_fields(model: type[Model]) -> list[str]:
    """Concrete, non-relational columns -- the ones that can hold a value.

    Relations are excluded because the design keeps every FK: an FK is the
    structure that survives, never the personal data. The primary key is
    excluded for the same reason -- Membership survives as an opaque key.
    """
    return [
        f.name
        for f in model._meta.get_fields()
        if getattr(f, "concrete", False) and not f.is_relation and not f.primary_key
    ]


REDACT: dict[str, RedactSpec] = {}
KEEP: dict[str, tuple[str, ...]] = {}
UNDECIDED: dict[str, tuple[str, ...]] = {}
```

- [ ] **Step 4: Run the test to see it now fails on the classification, not the import**

Run: `uv run pytest tests/audit/test_redaction_classification.py -q 2>&1 | tail -40`
Expected: `test_walk_uses_forward_fks_and_sees_the_hidden_models`, `test_walk_reaches_models_that_are_more_than_one_hop_away`, `test_every_redact_model_has_a_subject_path` and `test_erasure_refuses_to_run_while_anything_is_undecided` PASS. `test_every_reachable_field_is_classified_exactly_once` FAILS with a printed list of 124 unclassified fields across 32 models. Read that list — it is the input to Task 2.

- [ ] **Step 5: Commit**

```bash
git add apps/audit/redaction.py tests/audit/test_redaction_classification.py
git commit -m "test: enforce erasure classification completeness over the student model graph

The walk scans forward FKs transitively. A reverse walk misses the nine FKs
declaring related_name='+', and a one-hop scan misses ApplicationStep and
ConsultationReport -- both of which hold REDACT fields.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 2: Link each notification to the escalation it is about

A schema change, and the only one in this plan. It comes before the classification because Task 3's
map filters `Notification` through the FK this task adds.

**Files:**
- Modify: `apps/concierge/models.py` (the `Notification` model)
- Create: `apps/concierge/migrations/00XX_notification_roadmap_item.py` (generated)
- Modify: `apps/portals/escalation.py:115` and `:156` (the two writers)
- Test: `tests/audit/test_redaction.py` (created in Task 4 — if running out of order, put this test
  in `tests/portals/test_escalation.py` instead)

**Interfaces:**
- Consumes: nothing.
- Produces: `Notification.roadmap_item`, a non-null FK to `concierge.RoadmapItem` with
  `on_delete=models.PROTECT`, matching every other FK in this app. Task 3's REDACT map uses the
  lookup path `roadmap_item__student_id`.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_notification_subject.py`:

```python
"""A notification must name the student it is about, not only its recipient.

Four of the six escalation triggers route to the assigned counselor, carrying
free text about the student. Without this link those messages are unfindable at
erasure: nothing in the row says whose data they hold.
"""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student):
    """Mirrors tests/portals/test_escalation.py::_application.

    form_key varies because PortalForm has a unique (portal_host, form_key)
    constraint and this helper is called more than once per test.
    """
    from apps.portals.models import Application, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_counselor_bound_escalation_still_names_the_student(
    agency_a, membership_a, counselor_membership
):
    """MISSING_FACT routes to the counselor. The student must still be reachable."""
    from apps.concierge.models import Notification
    from apps.portals.escalation import Trigger, escalate
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)

        escalate(application, Trigger.MISSING_FACT, detail="passport_number, date_of_birth")

        notification = Notification.objects.get()
        assert notification.recipient_id == counselor_membership.id, (
            "fixture is wrong: MISSING_FACT must route to the counselor for this test to mean anything"
        )
        assert notification.roadmap_item.student_id == membership_a.id


def test_student_bound_escalation_also_carries_the_link(
    agency_a, membership_a, counselor_membership
):
    """APPLICANT_MFA routes to the student. One path must cover both cases."""
    from apps.concierge.models import Notification
    from apps.portals.escalation import Trigger, escalate
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)

        escalate(application, Trigger.APPLICANT_MFA, detail="one-time code required")

        notification = Notification.objects.get()
        assert notification.recipient_id == membership_a.id
        assert notification.roadmap_item.student_id == membership_a.id


def test_the_first_portal_review_notification_also_carries_the_link(
    agency_a, membership_a, counselor_membership
):
    """The second writer. request_first_portal_review is not an escalation but
    creates a RoadmapItem and a Notification the same way."""
    from apps.concierge.models import Notification
    from apps.portals.escalation import request_first_portal_review
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)
        application.portal_form.review_required = True
        application.portal_form.save(update_fields=["review_required"])

        request_first_portal_review(application)

        notification = Notification.objects.get()
        assert notification.roadmap_item.student_id == membership_a.id
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_notification_subject.py -q`
Expected: FAIL — `django.core.exceptions.FieldError` or `AttributeError: 'Notification' object has no attribute 'roadmap_item'`.

- [ ] **Step 3: Add the field**

In `apps/concierge/models.py`, in `class Notification`, below `recipient`:

```python
    # Who the message is ABOUT, which is not always who receives it: four of the
    # six escalation triggers route to the assigned counselor. Erasure redacts
    # by roadmap_item__student_id, so a notification with no link is one that
    # cannot be erased. Both writers create the RoadmapItem immediately before
    # the notification and it already carries the right student.
    roadmap_item = models.ForeignKey(RoadmapItem, on_delete=models.PROTECT)
```

- [ ] **Step 4: Write the migration by hand**

`makemigrations` cannot generate this one non-interactively. Django prompts for a one-off default
whenever a **non-nullable** field is added to an existing model — always, whether or not the table
has rows — and a foreign key has no sensible one-off default. Do not make the field nullable to
dodge the prompt: a `Notification` with a null `roadmap_item` is one erasure cannot reach, which is
the whole defect this task closes.

Write `apps/concierge/migrations/0006_notification_roadmap_item.py` directly:

```python
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Add the subject link with no default.

    No default is deliberate. concierge_notification is empty in every
    environment -- nothing is deployed, and PortalDesiredCount ships 0 so the
    escalation path that writes Notification has never run -- so this applies
    cleanly. If some environment does hold rows, it fails loudly with a NOT NULL
    violation rather than backfilling a wrong subject, and the right response is
    to backfill from RoadmapItem explicitly, not to supply a placeholder.
    """

    dependencies = [
        ("concierge", "0005_roadmap_item_agent_owner"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="roadmap_item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="concierge.roadmapitem",
            ),
        ),
    ]
```

Then confirm Django agrees the model and migrations are in sync:

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: no changes detected. If it wants to create another migration, the hand-written one does
not match the model — reconcile them rather than accepting a second migration.

- [ ] **Step 5: Set it in both writers**

In `apps/portals/escalation.py`, in `_escalate` (~line 115), add `roadmap_item=item` to the
`Notification.objects.create(...)` call:

```python
    Notification.objects.create(
        tenant=application.tenant,
        recipient=recipient,
        roadmap_item=item,
        message=f"{application.portal_form.portal_host}: {trigger.value} -- {detail}",
    )
```

and the same in `_request_first_portal_review` (~line 156):

```python
    Notification.objects.create(
        tenant=application.tenant,
        recipient=recipient,
        roadmap_item=item,
        message=(
            f"First prepared application on {portal_form.portal_host} -- "
            "review before it is submitted."
        ),
    )
```

Both already have `item` in scope from the `RoadmapItem.objects.create` directly above.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/portals/ -q`
Expected: PASS. Existing escalation tests must still pass — the field is additive and both writers set it.

- [ ] **Step 7: Commit**

```bash
git add apps/concierge/models.py apps/concierge/migrations/ apps/portals/escalation.py tests/portals/test_notification_subject.py
git commit -m "feat: notifications record the student they are about, not only the recipient

Four of six escalation triggers route to the assigned counselor with free text
about the student. Those messages were unreachable at erasure: nothing in the
row named whose data they held.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 3: Fill the classification

Turning the failing list from Task 1 into a decision per field. The spec's tables are the source; the two fields it does not cover go to `UNDECIDED`, which keeps the erasure refusing to run until someone decides.

**Files:**
- Modify: `apps/audit/redaction.py` (the three dicts at the bottom)

**Interfaces:**
- Consumes: `RedactSpec`, `student_reachable_models`, `classifiable_fields` from Task 1.
- Produces: populated `REDACT`, `KEEP`, `UNDECIDED`. Task 4's `redact_student` reads `REDACT`.

- [ ] **Step 1: Replace the three empty dicts with the classification**

In `apps/audit/redaction.py`, replace the `REDACT`/`KEEP`/`UNDECIDED` assignments:

```python
# Subject paths are hand-written. A shortest-path search picks the wrong FK on
# three of these: ManualOperation.actor and Approval.actor are staff, and
# RevisionRequest.requested_by is the requester.
REDACT: dict[str, RedactSpec] = {
    "accounts.StudentProfileVersion": RedactSpec("student_id", ("snapshot",)),
    "documents.VerifiedFact": RedactSpec("student_id", ("payload", "source_ref")),
    "documents.DocumentDraft": RedactSpec("student_id", ("content",)),
    "documents.RevisionRequest": RedactSpec("document__student_id", ("note",)),
    "concierge.RoadmapItem": RedactSpec("student_id", ("result",)),
    "concierge.RequiredAction": RedactSpec("student_id", ("description",)),
    "concierge.ManualOperation": RedactSpec("roadmap_item__student_id", ("description",)),
    "concierge.ConversationMessage": RedactSpec("student_id", ("body",)),
    # NOT recipient_id: four of the six escalation triggers route to the
    # assigned counselor with free text about the student, and those rows name
    # nobody. roadmap_item carries the subject whoever received the message.
    "concierge.Notification": RedactSpec("roadmap_item__student_id", ("message",)),
    "portals.ApplicationStep": RedactSpec("application__student_id", ("detail",)),
    "tenancy.Membership": RedactSpec("id", ("application_email", "academic_email")),
    # object_version, not pack_version: the FK is named for the generic
    # "approved object" the abandoned counselor gate had in mind.
    "funding.Approval": RedactSpec(
        "object_version__run__profile_version__student_id", ("reason",)
    ),
    # object_key is redacted only after the S3 object is purged: the purge reads
    # it to find the object. advance_deletion enforces that order.
    "reports.ConsultationReport": RedactSpec(
        "pack_version__run__profile_version__student_id", ("object_key",)
    ),
    "concierge.DocumentVersion": RedactSpec("student_id", ("object_key",)),
}

KEEP: dict[str, tuple[str, ...]] = {
    "tenancy.Membership": ("role", "active"),
    "accounts.StudentProfileVersion": ("version", "schema_version", "created_at"),
    "audit.DeletionRequest": ("state", "legal_hold", "created_at"),
    "concierge.ApplicationFeeLedgerEntry": (
        "program_id",
        "approved_limit",
        "currency",
        "charged_amount",
        # A masked financial reference, kept with the ledger entry it belongs
        # to. Whether the ledger has a statutory retention floor is §10's
        # question; redaction does not prejudge it.
        "masked_card_reference",
        "refund_amount",
        "created_at",
    ),
    "concierge.ConversationMessage": ("created_at",),
    # KEEP by constraint, not by inspection: nothing writes Receipt today.
    # GDPR Art. 17(3)(b) withdraws the right to erasure where retention is a
    # legal obligation; German accounting receipts run 8 years under §147 AO.
    # Four rules make this true and are in the spec: the key stays opaque, the
    # retained object is access-restricted (Art. 18) rather than merely kept,
    # it is destroyed when the period expires, and the exemption covers the
    # receipt and nothing else. Tripwire: test_receipt_has_no_writer_yet.
    "concierge.Receipt": ("object_key", "created_at"),
    "concierge.DocumentVersion": ("state", "scan_result", "created_at"),
    "concierge.ManualOperation": ("performed_at",),
    "concierge.Notification": ("acknowledged_at", "created_at"),
    "concierge.RequiredAction": ("acknowledged_at", "created_at"),
    "concierge.RoadmapItem": ("stage", "owner_kind", "deadline", "state", "created_at"),
    "concierge.ServiceEngagement": ("platform_fee", "currency", "credit_amount", "created_at"),
    "documents.ConsentEvent": ("mode", "granted_at", "revoked_at"),
    "documents.DocumentDraft": (
        "kind",
        "version",
        "render_variant",
        "status",
        "approved_at",
        "created_at",
        "approval_mode",
    ),
    "documents.DocumentDraftFact": ("created_at",),
    "documents.RevisionRequest": ("kind", "created_at"),
    "documents.VerifiedFact": ("category", "source_tier", "confirmed_at", "created_at"),
    "funding.Approval": ("decision", "created_at"),
    "funding.AuditEvent": ("actor_kind", "event", "object_id", "created_at"),
    # risk_text_shown is the catalog rule's own wording, set from
    # violation.rule.rule_text by apps/documents/overrides.py. Identical for
    # every student who hits that rule; it exists to prove which warning was
    # shown, since rule text changes.
    "funding.ConstraintOverride": ("rule_id", "risk_text_shown", "created_at"),
    # expected_structured_result is KEEP *by constraint*, not by inspection:
    # nothing writes it today. Whoever builds the writer may persist
    # schema-constrained model output only, never free text or an identifier.
    # See tests/audit/test_redaction.py::test_evaluation_example_holds_no_identifier.
    "funding.EvaluationExample": (
        "input_schema_version",
        "expected_structured_result",
        "allowed_purposes",
        "created_at",
    ),
    "funding.PackVersion": (
        "version",
        "created_at",
        "published_at",
        "superseded_at",
        "approved_version_id",
    ),
    # program_name is a programme, not a person.
    "funding.RecommendationCandidate": (
        "program_name",
        "funding_gap",
        "currency",
        "eligible",
        "state",
        "funding_gap_is_placeholder",
        "evidence_confidence",
    ),
    "funding.RecommendationRun": ("state", "created_at", "dispatched_at"),
    "funding.StudentDecision": ("decision", "created_at"),
    "portals.Application": ("program_id", "state", "created_at"),
    "portals.ApplicationStep": ("sequence", "kind", "created_at"),
    "reports.ConsultationPayment": (
        "amount",
        "currency",
        "status",
        "credited_engagement_id",
        "created_at",
    ),
    "reports.ConsultationReport": ("s3_version_id", "sha256", "content_type", "generated_at"),
    # Tenant-level, not about the student.
    "tenancy.AgencyDataUseAgreementVersion": (
        "agreement_id",
        "version",
        "agreement_reference",
        "permitted_purposes",
        "eligible_categories",
        "lawful_basis_review_state",
        "effective_at",
        "revoked_at",
        "created_at",
    ),
    "tenancy.CounselorAssignment": ("active", "created_at"),
}

# Both entries that lived here were resolved on 2026-09-08 -- Receipt to KEEP by
# constraint, Notification to REDACT through the FK Task 2 adds. The class and
# the test that blocks on it stay: they are the mechanism that made those two
# visible, and the next field nobody has thought about lands here too.
UNDECIDED: dict[str, tuple[str, ...]] = {}
```

- [ ] **Step 2: Run the completeness test**

Run: `uv run pytest tests/audit/test_redaction_classification.py -q 2>&1 | tail -40`
Expected: `test_every_reachable_field_is_classified_exactly_once`, `test_classification_names_no_field_that_does_not_exist` and `test_every_redact_model_has_a_subject_path` PASS. `test_erasure_refuses_to_run_while_anything_is_undecided` FAILS, naming `concierge.Receipt` and `concierge.Notification`.

That failure is correct and expected at this step. It is the design working: two fields have no retention answer, so erasure must not claim to be complete.

- [ ] **Step 3: If the completeness test still lists unclassified fields, add them**

The field lists above were read off the schema at commit `e9c8249`. If migrations have landed since, the test prints the exact `label.field` strings still missing. For each, decide by the spec's rule — *does this field, alone or with its neighbours, single out a person?* — and add it to `KEEP` or to `REDACT` (with a subject path). If the answer needs a product decision, add it to `UNDECIDED` with a comment saying what the decision is. Do not guess a field into `KEEP` to make the test green.

- [ ] **Step 4: Commit**

```bash
git add apps/audit/redaction.py
git commit -m "feat: classify every student-reachable field for erasure

Two fields reach UNDECIDED: Receipt.object_key and Notification.message.
Erasure refuses to run while either is unresolved, which is the point --
a field with no retention answer must not be silently skipped.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 4: `redact_student()`

**Files:**
- Modify: `apps/audit/redaction.py`
- Create: `tests/audit/test_redaction.py`

**Interfaces:**
- Consumes: `REDACT`, `RedactSpec`, `UNDECIDED` from Task 3.
- Produces: `redact_student(*, tenant_id: UUID, student_id: UUID) -> int` returning the number of rows updated, and `RedactionIncomplete(RuntimeError)`. Task 5 calls both from `advance_deletion`.

- [ ] **Step 1: Write the failing test**

Two schema facts this test must respect, both verified against the live models:
`VerifiedFact.created_by` is a **non-null** FK to `Membership` (omit it and you get an
`IntegrityError`, not a redaction failure), and `RoadmapItem.deadline` is a required
`DateTimeField` — pass `timezone.now()`, not a string. `RoadmapItem.owner` is nullable, so it may
be left out.

Create `tests/audit/test_redaction.py`:

```python
import pytest
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.audit.redaction import RedactionIncomplete, redact_student
from apps.concierge.models import RoadmapItem
from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency,
        user=user,
        role=Membership.Role.STUDENT,
        active=True,
        application_email=f"{name}@example.test",
        academic_email=f"{name}@uni.example.test",
    )


def test_redaction_empties_personal_fields_and_keeps_structure(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        fact = VerifiedFact.objects.create(
            tenant=agency_a,
            student=student,
            category="EMPLOYMENT",
            payload={"employer": "Acme GmbH", "name": "Amina Yusuf"},
            source_tier="DOCUMENT",
            source_ref="s3://evidence/cv.pdf",
            created_by=student,
        )
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=student,
            stage=RoadmapItem.Stage.DOCUMENTS,
            owner_kind="AGENT",
            deadline=timezone.now(),
            result="Amina's passport scan is blurred; ask her to resend.",
        )

        redact_student(tenant_id=agency_a.id, student_id=student.id)

        fact.refresh_from_db()
        item.refresh_from_db()
        student.refresh_from_db()

    # REDACT: emptied, not deleted, not NULL.
    assert fact.payload == {}
    assert fact.source_ref == ""
    assert item.result == ""
    assert student.application_email == ""
    assert student.academic_email == ""
    # KEEP: the structured residue the models need survives untouched.
    assert fact.category == "EMPLOYMENT"
    assert fact.source_tier == "DOCUMENT"
    assert item.stage == RoadmapItem.Stage.DOCUMENTS
    assert item.owner_kind == "AGENT"
    assert student.role == Membership.Role.STUDENT
    # The rows themselves survive: nothing was deleted.
    assert VerifiedFact.objects.filter(pk=fact.pk).exists()
    assert Membership.objects.filter(pk=student.pk).exists()


def test_redaction_touches_only_the_named_student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        erased = _student(agency_a, django_user_model, "amina")
        bystander = _student(agency_a, django_user_model, "kwame")
        keep = VerifiedFact.objects.create(
            tenant=agency_a,
            student=bystander,
            category="EDUCATION",
            payload={"degree": "BSc"},
            source_tier="DOCUMENT",
            source_ref="s3://evidence/kwame.pdf",
            created_by=bystander,
        )

        redact_student(tenant_id=agency_a.id, student_id=erased.id)

        keep.refresh_from_db()
        bystander.refresh_from_db()

    assert keep.payload == {"degree": "BSc"}
    assert keep.source_ref == "s3://evidence/kwame.pdf"
    assert bystander.application_email == "kwame@example.test"


def test_redaction_refuses_to_run_while_a_field_is_undecided(
    agency_a, django_user_model, monkeypatch
):
    """A partial erasure must not be reachable by forgetting a decision."""
    monkeypatch.setattr(
        "apps.audit.redaction.UNDECIDED", {"concierge.Receipt": ("object_key",)}
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        version = StudentProfileVersion.objects.create(
            tenant=agency_a, student=student, version=1, schema_version=1,
            snapshot={"name": "Amina Yusuf"},
        )
        with pytest.raises(RedactionIncomplete):
            redact_student(tenant_id=agency_a.id, student_id=student.id)
        version.refresh_from_db()

    # Refused before touching anything, not halfway through.
    assert version.snapshot == {"name": "Amina Yusuf"}


def test_evaluation_example_holds_no_identifier():
    """Owed by the spec: EvaluationExample is KEEP by constraint, not inspection.

    Nothing writes it today, so there is no content to assert against. When a
    writer exists, replace this with an assertion that what it persists
    contains no value drawn from a REDACT field.
    """
    from apps.funding.models import EvaluationExample

    assert not EvaluationExample.objects.exists(), (
        "EvaluationExample now has rows: this test must be replaced with a real "
        "assertion that its contents carry no identifier. See the spec's "
        "'Owed' section."
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/audit/test_redaction.py -q`
Expected: FAIL — `ImportError: cannot import name 'RedactionIncomplete' from 'apps.audit.redaction'`

- [ ] **Step 3: Implement `redact_student`**

First add the `UUID` import this step needs — Task 1 deliberately left it out, because an unused
import fails CI's blocking `ruff check`. At the top of `apps/audit/redaction.py`, change:

```python
from typing import NamedTuple
```

to:

```python
from typing import NamedTuple
from uuid import UUID
```

Then append to `apps/audit/redaction.py`:

```python
class RedactionIncomplete(RuntimeError):
    """Raised when a field has no retention decision, before anything is written.

    Erasure that skips a field is worse than erasure that refuses: the first
    records a legal claim that is false.
    """


def _empty_value(model: type[Model], field_name: str) -> object:
    """The empty value for a field's type -- never NULL.

    NOT NULL constraints must keep holding, and "redacted" is distinguishable
    from "never set" through the DeletionRequest, which is where that fact
    belongs.
    """
    field = model._meta.get_field(field_name)
    internal = field.get_internal_type()
    if internal == "JSONField":
        return {}
    if internal in ("CharField", "TextField"):
        return ""
    raise RedactionIncomplete(
        f"no empty value defined for {model.__name__}.{field_name} ({internal})"
    )


def redact_student(*, tenant_id: UUID, student_id: UUID) -> int:
    """Overwrite every REDACT field belonging to one student. Deletes nothing.

    Returns the number of rows updated. Callers run this inside a transaction:
    a failure part-way through must leave no partially redacted student, and
    advance_deletion must not write EXECUTED unless this returned.

    Some of these tables are FORCE ROW LEVEL SECURITY on app.tenant_id and the
    production role is NOBYPASSRLS, so the caller must also have called
    set_local_tenant -- tenant_scope alone is a contextvar and never reaches
    Postgres. Without it these UPDATEs are legal SQL that match zero rows, and
    the erasure silently does nothing.
    """
    if UNDECIDED:
        raise RedactionIncomplete(
            "fields awaiting a retention decision (phased requirements.md §10): "
            f"{sorted(UNDECIDED)}"
        )
    updated = 0
    for label, spec in REDACT.items():
        model = apps.get_model(label)
        empties = {name: _empty_value(model, name) for name in spec.fields}
        updated += model.objects.filter(**{spec.subject: student_id}).update(**empties)
    return updated
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/audit/test_redaction.py -q`
Expected: PASS, 4 tests.

If `test_redaction_empties_personal_fields_and_keeps_structure` fails with all values unchanged and zero rows matched, the test is missing `set_local_tenant` — add `from apps.tenancy.db import set_local_tenant` and call it inside a `transaction.atomic()` in the test, mirroring `apps/documents/storage.py::delete_student_documents`.

- [ ] **Step 5: Commit**

```bash
git add apps/audit/redaction.py tests/audit/test_redaction.py
git commit -m "feat: redact_student overwrites personal fields in place

Deletes no rows: the model graph is PROTECT almost everywhere. Refuses to
run while any field is UNDECIDED.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 5: Wire it into `advance_deletion`, fail closed

The change that closes the defect. Kept separate because it is the one a reviewer must read hardest: it decides what "EXECUTED" now means.

**Files:**
- Modify: `apps/audit/deletion.py`
- Modify: `tests/audit/test_redaction.py` (append)

**Interfaces:**
- Consumes: `redact_student`, `RedactionIncomplete` from Task 4.
- Produces: no new names. `advance_deletion`'s signature is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/audit/test_redaction.py`:

```python
def test_executed_redacts_and_is_written_only_after_redaction_succeeds(
    agency_a, django_user_model, monkeypatch
):
    from django.utils import timezone

    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_documents", lambda **kw: 0
    )
    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        fact = VerifiedFact.objects.create(
            tenant=agency_a, student=student, category="IDENTITY",
            payload={"name": "Amina Yusuf"}, source_tier="DOCUMENT",
            source_ref="s3://evidence/cv.pdf",
            created_by=student,
        )
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

        request.refresh_from_db()
        fact.refresh_from_db()

    assert request.state == "EXECUTED"
    assert fact.payload == {}


def test_a_failed_redaction_leaves_the_request_approved(
    agency_a, django_user_model, monkeypatch
):
    """The whole point: EXECUTED must never outrun the redaction it claims."""
    from django.utils import timezone

    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0
    )

    def boom(**kwargs):
        raise RedactionIncomplete("simulated failure")

    monkeypatch.setattr("apps.audit.deletion.redact_student", boom)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        fact = VerifiedFact.objects.create(
            tenant=agency_a, student=student, category="IDENTITY",
            payload={"name": "Amina Yusuf"}, source_tier="DOCUMENT",
            source_ref="s3://evidence/cv.pdf",
            created_by=student,
        )
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")

        with pytest.raises(RedactionIncomplete):
            advance_deletion(request, "EXECUTED")

        request.refresh_from_db()
        fact.refresh_from_db()

    assert request.state == "APPROVED"
    assert fact.payload == {"name": "Amina Yusuf"}
```



Then append the mechanism test. It is not redundant with the two above: the **test database role is
not the production `NOBYPASSRLS` role**, so RLS enforces nothing in tests and an outcome-only
assertion passes identically whether or not `set_local_tenant` ever ran. In production it is the
difference between redacting the rows and silently matching zero of them while writing `EXECUTED`.
`tests/audit/test_deletion_purges_documents.py::test_delete_student_documents_sets_tenant_guc_before_reading_uploads`
pins the same mechanism for the S3 half and is the pattern this mirrors.

```python
def test_executed_sets_the_tenant_guc_in_a_transaction_before_redacting(
    agency_a, django_user_model, monkeypatch
):
    """Pins the mechanism, not the outcome.

    Several redacted tables are FORCE ROW LEVEL SECURITY keyed on the Postgres
    app.tenant_id GUC. tenant_scope is only a contextvar and never reaches
    Postgres, so without set_local_tenant the UPDATEs are legal SQL matching
    zero rows -- the erasure "succeeds", EXECUTED is written, and nothing was
    redacted. The test role enforces no RLS, so only the mechanism is provable
    here: that the GUC is set, with the right tenant, inside an open
    transaction, before redact_student runs.
    """
    from django.db import connection
    from django.utils import timezone

    from apps.audit import deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)

    order: list[tuple[str, object, bool]] = []
    real_set_local_tenant = deletion.set_local_tenant
    real_redact = deletion.redact_student

    def _spy_guc(tenant_id):
        order.append(("guc", tenant_id, connection.in_atomic_block))
        return real_set_local_tenant(tenant_id)

    def _spy_redact(**kwargs):
        order.append(("redact", kwargs["tenant_id"], connection.in_atomic_block))
        return real_redact(**kwargs)

    monkeypatch.setattr(deletion, "set_local_tenant", _spy_guc)
    monkeypatch.setattr(deletion, "redact_student", _spy_redact)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "guc")
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

    assert order == [
        ("guc", agency_a.id, True),
        ("redact", agency_a.id, True),
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/audit/test_redaction.py -q -k "executed or approved or guc"`
Expected: `test_executed_redacts_...` FAILS with `assert {'name': 'Amina Yusuf'} == {}` — `advance_deletion` writes `EXECUTED` without redacting. That failing assertion is the production defect, reproduced.

- [ ] **Step 3: Wire it in**

Modify `apps/audit/deletion.py`. Replace the imports and the `EXECUTED` branch:

```python
from django.db import transaction

from apps.audit.redaction import redact_student
from apps.documents.storage import delete_student_documents
from apps.portals.auth import delete_student_portal_credentials
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

from .models import DeletionRequest, RetentionPolicy
```

and, inside `advance_deletion`:

```python
        if target_state == "EXECUTED":
            # Before the state write: a storage failure must leave the request
            # in APPROVED rather than recording an erasure that did not happen.
            delete_student_documents(tenant_id=request.tenant_id, student_id=request.student_id)
            # Same path, same rule. A student's portal logins outliving their
            # erasure is the failure CLAUDE.md's Phase 3 rules name by hand.
            delete_student_portal_credentials(
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
                request.state = target_state
                request.save(update_fields=["state"])
            return request
        request.state = target_state
        request.save(update_fields=["state"])
    return request
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/audit/ -q`
Expected: PASS. The existing `tests/audit/test_deletion.py` and `test_deletion_purges_documents.py` must still pass — they exercise the same transitions.

`UNDECIDED` is empty as of Task 3, so `redact_student` does not refuse and those tests need no
monkeypatch. If one of them now fails on the `EXECUTED` path for a different reason, the likely
cause is a missing `set_local_tenant` in the test's own setup: several redacted tables are FORCE ROW
LEVEL SECURITY, so the `UPDATE`s match zero rows without it. Do not fix that by emptying a
classification.

- [ ] **Step 5: Commit**

```bash
git add apps/audit/deletion.py tests/audit/test_redaction.py
git commit -m "fix: erasure now redacts the database, not only S3 and Secrets Manager

advance_deletion wrote EXECUTED while the parsed CV, the generated CV, the
profile snapshot and every free-text field about the student stayed in
Postgres. EXECUTED is now written in the same transaction as the redaction.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```

---

### Task 6: The Receipt tripwire, and the full gate

`UNDECIDED` is empty as of Task 3, so erasure runs. What is left is the guard for the one
classification that rests on a promise rather than on data.

**Files:**
- Modify: `tests/audit/test_redaction.py`
- Modify: `docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md` (only if the map drifted)

**Interfaces:**
- Consumes: `KEEP` from Task 3.
- Produces: no new names.

- [ ] **Step 1: Write the tripwire**

Append to `tests/audit/test_redaction.py`:

```python
def test_receipt_has_no_writer_yet():
    """Receipt.object_key is KEEP by constraint. This fails when that stops being safe.

    Nothing creates a Receipt today, so the classification is a promise about a
    writer that does not exist. When one is built, this test fails and whoever
    built it must read the four rules in the spec and replace this assertion:

      1. object_key stays opaque -- no payer name in a field we keep forever.
      2. Retained means access-restricted after erasure (GDPR Art. 18), not
         merely kept. apps/audit/services.py already serves receipts into the
         student dossier via ledger_entry__student_id.
      3. Destroyed when the statutory period expires (§147 AO: 8 years from the
         end of the calendar year). Retention is a floor, not a licence.
      4. The exemption covers the receipt and nothing else.
    """
    from apps.concierge.models import Receipt

    assert not Receipt.objects.exists(), (
        "Receipt now has a writer. Read the four constraints in "
        "docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md and replace "
        "this assertion with a real one -- KEEP was a promise, not an observation."
    )


def test_masked_card_reference_has_no_writer_yet():
    """The third KEEP-by-constraint field, and the one with no stated constraint.

    ApplicationFeeLedgerEntry has no writer at all, so `masked_card_reference`
    is KEEP on the strength of its NAME implying the value arrives already
    masked. Nothing enforces that. A writer that stores a full PAN, or a
    cardholder name, puts unerasable payment data in a field this design
    promises is safe to keep -- and unlike Receipt and EvaluationExample, that
    promise was never written down until now.

    The constraint on whoever builds the writer: this column may hold a masked
    reference only -- last four digits or a processor token -- never a full
    card number, never a cardholder name, never anything that identifies the
    payer. If a fuller reference is genuinely needed, it is REDACT, not KEEP,
    and belongs in the map with a subject path of `student_id`.
    """
    from apps.concierge.models import ApplicationFeeLedgerEntry

    assert not ApplicationFeeLedgerEntry.objects.exists(), (
        "ApplicationFeeLedgerEntry now has a writer. Confirm masked_card_reference "
        "holds only a masked reference, then replace this assertion with one that "
        "checks it -- or move the field to REDACT."
    )
```

Then append the ordering test. Review of the previous task found this property is load-bearing but
pinned by nothing: `delete_student_documents` reads `object_key` to locate the S3 objects, and
redaction empties that column. Inverted, the purge finds nothing and the student's documents survive
in S3 forever while the request reads EXECUTED — a silent, unrecoverable compliance failure that a
refactor could introduce without a single test going red.

```python
def test_the_s3_purge_runs_before_redaction_empties_the_keys(
    agency_a, django_user_model, monkeypatch
):
    """Order is load-bearing, and nothing else pins it.

    delete_student_documents finds objects BY object_key, and redaction empties
    object_key. Reversed, the purge enumerates nothing, every document survives
    in S3, and the request still reads EXECUTED. The S3 purge is idempotent, so
    this order is also the safely retryable one.
    """
    from django.utils import timezone

    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    order: list[str] = []
    real_redact = deletion.redact_student

    monkeypatch.setattr(
        deletion, "delete_student_documents", lambda **kw: order.append("s3") or 0
    )
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)

    def _spy_redact(**kwargs):
        order.append("redact")
        return real_redact(**kwargs)

    monkeypatch.setattr(deletion, "redact_student", _spy_redact)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "order")
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

    assert order == ["s3", "redact"]
```

- [ ] **Step 2: Run the audit tests**

Run: `uv run pytest tests/audit/ -q`
Expected: PASS, including `test_erasure_refuses_to_run_while_anything_is_undecided` (now vacuous,
since `UNDECIDED` is empty) and every existing deletion test.

Remove any `redact_student` monkeypatch added to the existing deletion tests in Task 5 Step 4 — it
was only needed while `UNDECIDED` was non-empty — and confirm they still pass without it.

- [ ] **Step 3: Check the classification did not drift from the schema**

Run: `uv run pytest tests/audit/test_redaction_classification.py -q`
Expected: PASS. If it now lists unclassified fields, migrations have landed since the plan was
written. Classify each by the spec's rule — *does this field, alone or with its neighbours, single
out a person?* — and add it. Do not guess a field into `KEEP` to make the test green; that is the
one move this whole design exists to prevent.

- [ ] **Step 4: Run the full gate**

```bash
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
```

All five must pass. `ruff format` is deliberately **not** run in this repository — the gate is
lint-only, and running it churns unrelated files.

- [ ] **Step 5: Commit**

```bash
git add tests/audit/test_redaction.py docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md
git commit -m "test: tripwire for Receipt, the one KEEP that rests on a promise

Receipt has no writer, so its classification cannot be checked by inspection.
This fails the day one appears.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LgxcordBdyPJUPX3sahrKP"
```


## Out of scope, per the spec

Each is a separate deliverable. Do not fold any of them into this plan.

- **Giving `advance_deletion` a caller.** It is still unreachable from `apps/`; this plan makes it correct, not reachable. That is an interaction-surface decision.
- **Anonymising the `User`.** `Membership.user` is `CASCADE` from `AUTH_USER_MODEL` and a user may hold memberships in other agencies. Needs a last-active-membership check.
- **Deleting the counselor-gate fossils** — `funding.Approval` and the `PackVersion` approval scaffolding. This plan classifies `Approval.reason` as REDACT so that erasure is correct whether or not the fossil is removed later.
- **Deciding §10 retention periods.** Rows survive, so whatever §10 settles still applies to them.
