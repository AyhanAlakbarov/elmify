# Lanes plan 1a — links between cards, the route copy, auto-added awards

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** give every application card a copied route it can be started from. Link a programme card to the separately applied awards that pay for it, and add the awards the student is confirmed eligible for automatically.

**Architecture:**
- **Route copy.** A typed snapshot of a programme's application route (`RouteSnapshot`) is stored on `portals.Application.route_snapshot`. Today it's written from the agency-recorded portal (the fallback). Plan 1b writes it from §3.4's served catalogue routes, in the same shape.
- **Links.** A new tenant table `portals.ApplicationLink` links cards.
- **Auto-add.** `apps/portals/award_links.py` decides, from each award's copied `route`, whether it becomes a card, a line or a suggestion. Adding a programme adds its eligible separate awards and links them.

**Tech stack:** Django 5.2, Postgres row-level security, pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-programme-lanes-and-money-design.md` (§2, §3, §4), on branch `claude/lanes-and-money-design`.

**What this plan leaves to plan 1b** (spec §14 put them in plan 1, but their sources don't exist on master yet):
- copying §3.4's `SERVED` routes into the snapshot, and choosing the route by audience (§9.6). These need `funding.ApplicationRoute` / `RouteStep` / `RouteDate`, which the catalogue plans build;
- the award facts `route_order`, `results_date`, fee and `renewal_condition` (§5.2 additions, not yet extracted). Until then a link is `LINKED_ONLY`, never `WAITS_FOR`;
- copying `Program.referee_requirements` (PR #185, merged to master as a00418a3 on 2026-10-09). It moves to plan 4, which is the first plan to read it.

## Global Constraints

- **Setup, before Task 1:** `git -C /home/orkhan/Desktop/lanes-and-money-design merge origin/master`. The branch is cut from 70848a31, and master since added funding/0058 (`referee_requirements`) and documents/0027. A new portals migration is numbered after master's portals leaf. Check `ls apps/portals/migrations` after the merge, and renumber 0024–0026 in this plan if master moved past 0023.

- **Worktree:** `/home/orkhan/Desktop/lanes-and-money-design`, branch `claude/lanes-and-money-design`. The shell cwd resets to `/home/orkhan/Desktop/tehsil_agent` after every command, so prefix commands with `cd /home/orkhan/Desktop/lanes-and-money-design &&` and use `git -C /home/orkhan/Desktop/lanes-and-money-design`.
- **Test DB:** `POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider <paths>`. Never run two suites at once on one DB.
- **Gates:**
  - `uv run ruff check .`, never `ruff format`;
  - `uv run mypy apps config`;
  - `uv run python manage.py check`;
  - `uv run python manage.py makemigrations --check --dry-run`;
  - `uv run bandit -c pyproject.toml -r apps config`.
- **No blanket `# type: ignore`.** Never hand-edit `uv.lock` or an applied migration.
- **Web tier reads tenant tables only** (dashboard spec): never `funding.Program`, `FundingOpportunity` or any catalogue table from a view. The worker writes the copies.
- **Every new tenant→tenant FK gets a composite `(tenant_id, X)` guard**, in a hand-written RunSQL migration (precedent: `apps/portals/migrations/0023_dashboard_tenant_guards.py`).
- **Every new tenant table** is `ENABLE` + `FORCE ROW LEVEL SECURITY`, with the `tenant_isolation` policy (precedent: `apps/privacy/migrations/0004_acceptance_guards.py`).
- **Every new field** is classified in `apps/audit/redaction.py` (REDACT or KEEP).
- **Words on any student-visible string:** Scholarship, Tuition waiver, Discount. Never "award", "HOLDER" or a route code.
- **Commit messages** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The same award paying for two programmes** the student adds → one award card, linked to both programme cards. Never two award cards. (Task 4 test `test_one_award_for_two_programmes_is_one_card_linked_twice`.)
2. **Adding the same programme twice** (double click, or re-adding after it already exists) → no second set of award cards or links. (Task 4 test `test_adding_twice_adds_awards_once`.)
3. **An award that isn't confirmed eligible** (`POSSIBLY_ELIGIBLE`, `NOT_ELIGIBLE`, `REJECTED` state, LOW confidence) → never a card, at most a suggestion line. (Task 4 test `test_only_confirmed_eligible_separate_awards_become_cards`, Task 5 test `test_possibly_eligible_separate_award_is_a_suggestion`.)
4. **A link pointing at another student's card or another tenant's card** → refused by the database. (Task 2 test `test_a_link_cannot_cross_tenants` with `rls_enforced_orm`, and `test_a_link_joins_one_students_cards_only`.)
5. **The agency fallback snapshot exists only when a portal is known.** Recording a portal later fills it, and a card with no portal has an empty snapshot, never a fake step. (Task 1 tests.)

---

### Task 1: The route snapshot and its agency fallback

**Files:**
- Create: `apps/portals/route_snapshot.py`, `tests/portals/test_route_snapshot.py`
- Modify: `apps/portals/models.py` (`Application`: add `route_snapshot`), `apps/portals/applications.py` (`_create`, `record_portal`), `apps/audit/redaction.py` (KEEP `route_snapshot`)
- Migration: `apps/portals/migrations/0024_application_route_snapshot.py` (generated)

**Interfaces:**
- Produces:
  - `RouteSnapshot` (pydantic, `extra="forbid"`): fields `source: Literal["AGENCY", "CATALOGUE"]`, `route_id: str = ""`, `audience: str = "ALL"`, `kind: str = "SELF_FUNDED"`, `intake: str = ""`, `steps: list[SnapshotStep]`;
  - `SnapshotStep`: `position: int`, `purpose: Literal["APPLY", "PRE_CHECK", "RANKING_ROUND", "VISA_PREENROL"]`, `channel: Literal["PORTAL", "EMAIL", "POST", "NONE"]`, `portal_url: str = ""`, `portal_system: str = ""`, `fee_amount: str = ""`, `fee_currency: str = ""`, `fee_deadline: str = ""`, `dates: list[SnapshotDate] = []`, `quote: str = ""`, `source_url: str = ""`;
  - `SnapshotDate`: `role: str`, `date: str = ""`, `timezone: str = ""`, `timezone_source: str = ""`, `quote: str = ""`;
  - `snapshot_from_portal(form: PortalForm) -> RouteSnapshot`;
  - `read_snapshot(application: Application) -> RouteSnapshot | None` (None when empty or unreadable).
- `Application.route_snapshot: JSONField(default=dict, blank=True)`. `{}` means no route known.

- [ ] **Step 1: Write the failing tests**

`tests/portals/test_route_snapshot.py`:

```python
import pytest

from apps.portals import applications as applications_module
from apps.portals.applications import add_application, record_portal
from apps.portals.models import Application, PortalForm
from apps.portals.route_snapshot import RouteSnapshot, read_snapshot, snapshot_from_portal
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch):
    monkeypatch.setattr(applications_module, "enqueue_document_work", lambda *_a, **_k: None)


def test_the_agency_fallback_is_one_apply_step_on_the_recorded_portal() -> None:
    form = PortalForm(portal_host="apply.tum.de", form_key="/x", form_url="https://apply.tum.de/x")
    snapshot = snapshot_from_portal(form)
    assert snapshot.source == "AGENCY"
    assert [(s.position, s.purpose, s.channel, s.portal_url) for s in snapshot.steps] == [
        (1, "APPLY", "PORTAL", "https://apply.tum.de/x")
    ]
    assert snapshot.steps[0].dates == [] and snapshot.steps[0].fee_amount == ""


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValueError):
        RouteSnapshot.model_validate({"source": "AGENCY", "steps": [], "surprise": 1})


def test_a_card_without_a_portal_has_no_snapshot(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=candidate.id, actor=membership_a)
        assert card.route_snapshot == {}
        assert read_snapshot(card) is None


def test_recording_a_portal_fills_the_snapshot(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=candidate.id, actor=membership_a)
        record_portal(card, "https://apply.tum.de/msc", actor=membership_a)
        card.refresh_from_db()
        snapshot = read_snapshot(card)
    assert snapshot is not None
    assert snapshot.steps[0].portal_url == "https://apply.tum.de/msc"


def test_a_card_reusing_a_known_portal_gets_its_snapshot(
    agency_a, membership_a, user_b, program_factory
) -> None:
    from apps.funding.models import RecommendationCandidate
    from apps.tenancy.models import Membership

    program = program_factory()
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(program_id=program.id)
        other = Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        first = add_application(student=membership_a, candidate_id=candidate.id, actor=membership_a)
        record_portal(first, "https://apply.tum.de/msc", actor=membership_a)
    run_b = make_run(agency_a, other)
    candidate_b = make_db_candidate(agency_a, run_b, program_name="MSc Chemistry")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=candidate_b.id).update(program_id=program.id)
    make_published_pack(agency_a, run_b, (candidate_b,))
    with tenant_scope(agency_a.id):
        second = add_application(student=other, candidate_id=candidate_b.id, actor=other)
        snapshot = read_snapshot(second)
    assert snapshot is not None and snapshot.steps[0].portal_url == "https://apply.tum.de/msc"


def test_an_unreadable_snapshot_reads_as_none(agency_a, membership_a) -> None:
    card = Application(route_snapshot={"source": "nonsense"})
    assert read_snapshot(card) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/portals/test_route_snapshot.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.portals.route_snapshot'`.

- [ ] **Step 3: Write the snapshot module**

`apps/portals/route_snapshot.py`:

```python
"""A card's copy of how its programme is applied for (lanes spec §3.1).

The web tier reads this copy, never the catalogue. Plan 1b writes it from the
catalogue's served route (verified-catalog spec §3.4) in this same shape; until
then the only writer is the agency fallback: the portal a person recorded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from .models import Application, PortalForm


class SnapshotDate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    date: str = ""
    timezone: str = ""
    timezone_source: str = ""
    quote: str = ""


class SnapshotStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    purpose: Literal["APPLY", "PRE_CHECK", "RANKING_ROUND", "VISA_PREENROL"]
    channel: Literal["PORTAL", "EMAIL", "POST", "NONE"]
    portal_url: str = ""
    portal_system: str = ""
    fee_amount: str = ""
    fee_currency: str = ""
    fee_deadline: str = ""
    dates: list[SnapshotDate] = []
    quote: str = ""
    source_url: str = ""


class RouteSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["AGENCY", "CATALOGUE"]
    route_id: str = ""
    audience: str = "ALL"
    kind: str = "SELF_FUNDED"
    intake: str = ""
    steps: list[SnapshotStep]


def snapshot_from_portal(form: PortalForm) -> RouteSnapshot:
    """The fallback: one APPLY step on the portal a person recorded, nothing else known."""
    return RouteSnapshot(
        source="AGENCY",
        steps=[SnapshotStep(position=1, purpose="APPLY", channel="PORTAL", portal_url=form.form_url)],
    )


def read_snapshot(application: Application) -> RouteSnapshot | None:
    """The card's snapshot, or None when there is none or it no longer parses."""
    if not application.route_snapshot:
        return None
    try:
        return RouteSnapshot.model_validate(application.route_snapshot)
    except ValidationError:
        return None
```

- [ ] **Step 4: Add the field and the writers**

In `apps/portals/models.py`, inside `class Application`, next to the `kit_*` fields:

```python
    #: How this programme is applied for, copied when the card is made (lanes
    #: spec §3.1; apps/portals/route_snapshot.py). {} = no route known yet.
    route_snapshot = models.JSONField(default=dict, blank=True)
```

In `apps/portals/applications.py`, add `from .route_snapshot import snapshot_from_portal` to the imports.

In `_create`, change the `Application.objects.create(...)` call to pass:

```python
        route_snapshot=snapshot_from_portal(portal).model_dump(mode="json") if portal else {},
```

In `record_portal`, replace:

```python
    application.portal_form = form
    application.save(update_fields=["portal_form"])
```

with:

```python
    application.portal_form = form
    application.route_snapshot = snapshot_from_portal(form).model_dump(mode="json")
    application.save(update_fields=["portal_form", "route_snapshot"])
```

In `apps/audit/redaction.py`, add `"route_snapshot",` to the KEEP tuple for `"portals.Application"`, with a comment: `# a copy of the programme's published route, like kit_requirements`.

Generate the migration: `cd /home/orkhan/Desktop/lanes-and-money-design && uv run python manage.py makemigrations portals -n application_route_snapshot`

- [ ] **Step 5: Run the tests and the neighbours**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/portals/test_route_snapshot.py tests/portals/test_applications.py tests/audit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/orkhan/Desktop/lanes-and-money-design && git add apps/portals/route_snapshot.py apps/portals/models.py apps/portals/applications.py apps/audit/redaction.py apps/portals/migrations/0024_application_route_snapshot.py tests/portals/test_route_snapshot.py && git commit -m "feat(portals): a card copies how its programme is applied for

The agency-recorded portal is the only writer until the catalogue serves routes (plan 1b).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `ApplicationLink`, a link between two cards

**Files:**
- Modify: `apps/portals/models.py` (new `ApplicationLink`), `apps/audit/redaction.py` (KEEP `order`, `created_at`)
- Migrations: `apps/portals/migrations/0025_applicationlink.py` (generated), `apps/portals/migrations/0026_applicationlink_guards.py` (hand-written: RLS + composite guards)
- Test: `tests/portals/test_application_link.py`, and add the two constraint names to `tests/migrations/test_portals_tenant_guards.py`'s `_COMPOSITE_FKS`

**Interfaces:**
- Produces: `ApplicationLink(TenantScopedModel)` with:
  - `from_app` → `Application` (CASCADE, related_name `links_out`);
  - `to_app` → `Application` (CASCADE, related_name `links_in`);
  - `order` (`WAITS_FOR` / `PARALLEL` / `LINKED_ONLY`);
  - `created_at`.

  Unique `(from_app, to_app)`; check `from_app != to_app`; check `order` in the three values.
- `ApplicationLink.Order` TextChoices.

- [ ] **Step 1: Write the failing tests**

`tests/portals/test_application_link.py`:

```python
import pytest
from django.db import IntegrityError, transaction
from uuid import uuid4

from apps.portals.models import Application, ApplicationLink
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _card(tenant, student) -> Application:
    return Application.objects.create(tenant=tenant, student=student, program_id=uuid4())


def test_a_link_joins_two_cards_once(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        programme, award = _card(agency_a, membership_a), _card(agency_a, membership_a)
        ApplicationLink.objects.create(tenant=agency_a, from_app=award, to_app=programme)
        assert award.links_out.get().order == ApplicationLink.Order.LINKED_ONLY
        with pytest.raises(IntegrityError), transaction.atomic():
            ApplicationLink.objects.create(tenant=agency_a, from_app=award, to_app=programme)


def test_a_card_cannot_link_to_itself(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        card = _card(agency_a, membership_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            ApplicationLink.objects.create(tenant=agency_a, from_app=card, to_app=card)


def test_a_link_cannot_cross_tenants(agency_a, agency_b, membership_a, membership_b) -> None:
    with tenant_scope(agency_a.id):
        mine = _card(agency_a, membership_a)
    with tenant_scope(agency_b.id):
        theirs = _card(agency_b, membership_b)
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        ApplicationLink.objects.create(tenant=agency_a, from_app=mine, to_app=theirs)


def test_deleting_a_card_removes_its_links(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        programme, award = _card(agency_a, membership_a), _card(agency_a, membership_a)
        ApplicationLink.objects.create(tenant=agency_a, from_app=award, to_app=programme)
        programme.delete()
        assert not ApplicationLink.objects.exists()
```

If `agency_b` / `membership_b` aren't fixture names in `tests/conftest.py`, use the names the tenancy isolation tests use for the second tenant and its student.

Also add `"portal_link_from_tenant_fk"` and `"portal_link_to_tenant_fk"` to `_COMPOSITE_FKS` in `tests/migrations/test_portals_tenant_guards.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/portals/test_application_link.py tests/migrations/test_portals_tenant_guards.py`
Expected: FAIL with `ImportError: cannot import name 'ApplicationLink'`.

- [ ] **Step 3: Add the model**

In `apps/portals/models.py`, after `class Application`:

```python
class ApplicationLink(TenantScopedModel):
    """One card linked to another: an award applied for separately and the
    programme it pays for (lanes spec §3.2, §4). ``WAITS_FOR``: ``from_app``
    cannot proceed until ``to_app`` has its outcome. Plan 1a writes only
    ``LINKED_ONLY``; the order arrives with the award facts (plan 1b)."""

    class Order(models.TextChoices):
        WAITS_FOR = "WAITS_FOR", "Waits for"
        PARALLEL = "PARALLEL", "In parallel"
        LINKED_ONLY = "LINKED_ONLY", "Linked"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    from_app = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="links_out")
    to_app = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="links_in")
    order = models.CharField(max_length=12, choices=Order.choices, default=Order.LINKED_ONLY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("from_app", "to_app"), name="portal_link_pair_uniq"),
            models.CheckConstraint(
                condition=~models.Q(from_app=models.F("to_app")), name="portal_link_not_self"
            ),
            models.CheckConstraint(
                condition=models.Q(order__in=("WAITS_FOR", "PARALLEL", "LINKED_ONLY")),
                name="portal_link_order_valid",
            ),
        ]
```

Generate: `cd /home/orkhan/Desktop/lanes-and-money-design && uv run python manage.py makemigrations portals -n applicationlink`

- [ ] **Step 4: Write the guard migration**

`apps/portals/migrations/0026_applicationlink_guards.py`:

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("portals", "0025_applicationlink")]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE portals_applicationlink ENABLE ROW LEVEL SECURITY;
            ALTER TABLE portals_applicationlink FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON portals_applicationlink
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            """,
            """
            DROP POLICY IF EXISTS tenant_isolation ON portals_applicationlink;
            ALTER TABLE portals_applicationlink DISABLE ROW LEVEL SECURITY;
            """,
        ),
        # Both ends must be cards of the link's own tenant (the composite
        # guard every tenant-to-tenant FK here carries; 0023 is the precedent).
        migrations.RunSQL(
            """
            ALTER TABLE portals_applicationlink
                ADD CONSTRAINT portal_link_from_tenant_fk
                FOREIGN KEY (tenant_id, from_app_id)
                REFERENCES portals_application (tenant_id, id) ON DELETE CASCADE;
            ALTER TABLE portals_applicationlink
                ADD CONSTRAINT portal_link_to_tenant_fk
                FOREIGN KEY (tenant_id, to_app_id)
                REFERENCES portals_application (tenant_id, id) ON DELETE CASCADE;
            """,
            """
            ALTER TABLE portals_applicationlink DROP CONSTRAINT portal_link_from_tenant_fk;
            ALTER TABLE portals_applicationlink DROP CONSTRAINT portal_link_to_tenant_fk;
            """,
        ),
    ]
```

Check how other tenant tables receive their `runtime_web` / `runtime_engine` grants: default privileges in `apps/tenancy/migrations`, or explicit `GRANT` lines like the one in `apps/privacy/migrations/0004_acceptance_guards.py`. Follow the same mechanism. `tests/tenancy/test_database_isolation.py` must pass with the new table.

In `apps/audit/redaction.py`, add to the KEEP mapping:

```python
    # a link between two of the student's own cards; both ends are erased
    # with them (CASCADE), so the row carries nothing of its own.
    "portals.ApplicationLink": ("order", "created_at"),
```

- [ ] **Step 5: Run the tests and the isolation suite**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/portals/test_application_link.py tests/migrations tests/tenancy/test_database_isolation.py tests/audit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/orkhan/Desktop/lanes-and-money-design && git add apps/portals/models.py apps/audit/redaction.py apps/portals/migrations/0025_applicationlink.py apps/portals/migrations/0026_applicationlink_guards.py tests/portals/test_application_link.py tests/migrations/test_portals_tenant_guards.py && git commit -m "feat(portals): a link between two of a student's cards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The award's duration on its card copy

**Files:**
- Modify: `apps/research/services.py` (`_award_copy`)
- Test: `tests/research/test_candidate_copies.py` (append)

**Interfaces:**
- Produces: `funding_card["duration_months"]` (`int | None`) and `funding_card["duration_text"]` (`str`), copied from `FundingOpportunity.duration_months` / `duration_text`. Plan 3's per-year money line reads them.

- [ ] **Step 1: Write the failing test**

Append to `tests/research/test_candidate_copies.py` (its imports already include `uuid4`, `pytest`, `FundingOpportunity`, `PackedAward` and `_award_copy`):

```python
def _global_award(**fields) -> FundingOpportunity:
    return FundingOpportunity.objects.create(
        canonical_key=f"read:global:{uuid4()}",
        name="Global award",
        family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL",
        agreement="AGREED",
        served=True,
        **fields,
    )


def _packed(opportunity: FundingOpportunity) -> PackedAward:
    return PackedAward(
        award_id=str(opportunity.id),
        name=opportunity.name,
        holder_name="Global Fund",
        deadline=None,
        ordering="FEE_FREE",  # type: ignore[arg-type]
        ordering_reason="",
        unconfirmed=(),
    )


@pytest.mark.django_db
def test_the_award_copy_carries_its_duration() -> None:
    opportunity = _global_award(duration_months=12, duration_text="one year")
    card = _award_copy(opportunity, _packed(opportunity))["funding_card"]
    assert card["duration_months"] == 12  # type: ignore[index]
    assert card["duration_text"] == "one year"  # type: ignore[index]


@pytest.mark.django_db
def test_an_award_without_a_stated_duration_copies_none() -> None:
    opportunity = _global_award()
    card = _award_copy(opportunity, _packed(opportunity))["funding_card"]
    assert card["duration_months"] is None  # type: ignore[index]
    assert card["duration_text"] == ""  # type: ignore[index]
```

(The `# type: ignore` lines follow this test file's existing style; mypy runs on `apps config` only.)

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/research/test_candidate_copies.py`
Expected: FAIL with `KeyError: 'duration_months'`.

- [ ] **Step 3: Copy the fields**

In `apps/research/services.py`, inside `_award_copy`'s `"funding_card": {...}`, after `"degree_levels": [],`:

```python
            # How long the award pays for, as the page states it (lanes spec §9.5);
            # the per-year money line reads it. None/"" when the page is silent.
            "duration_months": award.duration_months,
            "duration_text": award.duration_text,
```

- [ ] **Step 4: Run it to pass**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/research/test_candidate_copies.py tests/funding/test_grouping.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/orkhan/Desktop/lanes-and-money-design && git add apps/research/services.py tests/research/test_candidate_copies.py && git commit -m "feat(research): an award's card copy carries how long it pays for

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Adding a programme adds its eligible separate awards

**Files:**
- Create: `apps/portals/award_links.py`, `tests/portals/test_award_links.py`
- Modify: `apps/portals/applications.py` (`add_application` calls `link_awards` once the card exists, or when an existing card is returned)

**Interfaces:**
- Consumes: `apps.funding.grouping.funds(award, programme) -> bool`; `RecommendationCandidate.eligibility_status`; `funding_card["route"]`; `ApplicationLink` (Task 2); `_create` (Task 1's version).
- Produces:
  - `SEPARATE_ROUTES: frozenset[str] = frozenset({"STUDENT_APPLIES_SEPARATELY", "HOME_GOVERNMENT_NOMINATES"})`;
  - `link_awards(card: Application, *, actor: Membership) -> list[Application]` returns the award cards it added. It's idempotent: no duplicate cards or links.

- [ ] **Step 1: Write the failing tests**

`tests/portals/test_award_links.py`:

```python
import pytest

from apps.funding.models import RecommendationCandidate
from apps.portals import applications as applications_module
from apps.portals.applications import add_application
from apps.portals.models import Application, ApplicationLink
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch):
    monkeypatch.setattr(applications_module, "enqueue_document_work", lambda *_a, **_k: None)


def _award(agency, run, name, route, *, eligible=True, confidence="MEDIUM", state="VISIBLE"):
    award = make_db_candidate(
        agency, run, program_name=name, eligible=eligible,
        evidence_confidence=confidence, state=state,
    )
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funding_card={"scope": "GLOBAL", "route": route},
        )
    award.refresh_from_db()
    return award


def _pack(agency, membership, *, awards):
    run = make_run(agency, membership)
    programme = make_db_candidate(agency, run, program_name="MSc Chemistry")
    made = [_award(agency, run, *spec[:2], **spec[2]) for spec in awards]
    make_published_pack(agency, run, (programme, *made))
    return programme, made


def test_a_separate_eligible_award_is_added_and_linked(agency_a, membership_a) -> None:
    programme, (award,) = _pack(agency_a, membership_a, awards=[("SI Scholarship", "STUDENT_APPLIES_SEPARATELY", {})])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        award_card = Application.objects.get(candidate=award)
        link = ApplicationLink.objects.get()
    assert (link.from_app_id, link.to_app_id, link.order) == (award_card.id, card.id, "LINKED_ONLY")


def test_only_confirmed_eligible_separate_awards_become_cards(agency_a, membership_a) -> None:
    programme, _awards = _pack(agency_a, membership_a, awards=[
        ("Automatic waiver", "AUTOMATIC_ON_ADMISSION", {}),
        ("Considered", "CONSIDERED_WITH_ADMISSION", {}),
        ("Nominated", "INSTITUTION_NOMINATES", {}),
        ("Joint", "JOINT_SELECTION", {}),
        ("Unstated", "UNSTATED", {}),
        ("Low confidence", "STUDENT_APPLIES_SEPARATELY", {"confidence": "LOW"}),
        ("Not eligible", "STUDENT_APPLIES_SEPARATELY", {"eligible": False}),
        ("Rejected", "STUDENT_APPLIES_SEPARATELY", {"state": "REJECTED"}),
        ("Home government", "HOME_GOVERNMENT_NOMINATES", {}),
    ])
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        names = sorted(
            Application.objects.exclude(candidate=programme).values_list("candidate__program_name", flat=True)
        )
    assert names == ["Home government"]


def test_adding_twice_adds_awards_once(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[("SI Scholarship", "STUDENT_APPLIES_SEPARATELY", {})])
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        assert Application.objects.count() == 2
        assert ApplicationLink.objects.count() == 1


def test_one_award_for_two_programmes_is_one_card_linked_twice(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    first = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    second = make_db_candidate(agency_a, run, program_name="MSc Physics")
    award = _award(agency_a, run, "Chevening", "STUDENT_APPLIES_SEPARATELY")
    make_published_pack(agency_a, run, (first, second, award))
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=first.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=second.id, actor=membership_a)
        assert Application.objects.filter(candidate=award).count() == 1
        assert sorted(ApplicationLink.objects.values_list("to_app__candidate__program_name", flat=True)) == [
            "MSc Chemistry", "MSc Physics",
        ]


def test_an_award_added_directly_links_to_programmes_already_on_the_board(agency_a, membership_a) -> None:
    programme, (award,) = _pack(agency_a, membership_a, awards=[("SI Scholarship", "STUDENT_APPLIES_SEPARATELY", {})])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        ApplicationLink.objects.all().delete()
        Application.objects.filter(candidate=award).delete()
        award_card = add_application(student=membership_a, candidate_id=award.id, actor=membership_a)
        link = ApplicationLink.objects.get()
    assert (link.from_app_id, link.to_app_id) == (award_card.id, card.id)


def test_an_award_that_funds_nothing_here_is_not_added(agency_a, membership_a) -> None:
    programme, (award,) = _pack(agency_a, membership_a, awards=[("Elsewhere", "STUDENT_APPLIES_SEPARATELY", {})])
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funding_card={"scope": "INSTITUTION", "route": "STUDENT_APPLIES_SEPARATELY"},
        )
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        assert not Application.objects.filter(candidate=award).exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/portals/test_award_links.py`
Expected: FAIL. The first assertion finds no award card (`Application.DoesNotExist`).

- [ ] **Step 3: Write `award_links.py`**

`apps/portals/award_links.py`:

```python
"""Programme cards and the awards applied for separately that pay for them
(lanes spec §2, §4). An award the student is confirmed eligible for becomes its
own card, linked to every programme card it funds; one award is one card."""

from __future__ import annotations

from apps.funding.grouping import funds
from apps.funding.models import RecommendationCandidate
from apps.tenancy.models import Membership

from .models import Application, ApplicationLink

#: The award routes with an application of their own (§5.2's `_Route`).
SEPARATE_ROUTES: frozenset[str] = frozenset({"STUDENT_APPLIES_SEPARATELY", "HOME_GOVERNMENT_NOMINATES"})


def _is_award(candidate: RecommendationCandidate) -> bool:
    return candidate.opportunity_id is not None or bool(candidate.funding_card)


def _addable(award: RecommendationCandidate) -> bool:
    return (
        award.state == RecommendationCandidate.State.VISIBLE
        and (award.funding_card or {}).get("route") in SEPARATE_ROUTES
        and award.eligibility_status == RecommendationCandidate.EligibilityStatus.ELIGIBLE
    )


def _link(award_card: Application, programme_card: Application) -> None:
    ApplicationLink.objects.get_or_create(
        tenant_id=award_card.tenant_id, from_app=award_card, to_app=programme_card,
        defaults={"order": ApplicationLink.Order.LINKED_ONLY},
    )


def link_awards(card: Application, *, actor: Membership) -> list[Application]:
    """Add and link the separate awards for a programme card, or link an award
    card to the programme cards already on the board. Idempotent."""
    from .applications import _create  # the one way a card is made

    candidate = card.candidate
    if candidate is None:
        return []
    cards = {
        c.candidate_id: c
        for c in Application.objects.filter(student=card.student, candidate__isnull=False)
        .select_related("candidate")
    }
    if _is_award(candidate):
        for other in cards.values():
            if not _is_award(other.candidate) and funds(candidate, other.candidate):
                _link(card, other)
        return []
    added: list[Application] = []
    pool = RecommendationCandidate.objects.filter(run_id=candidate.run_id)
    for award in pool:
        if not _is_award(award) or not _addable(award) or not funds(award, candidate):
            continue
        award_card = cards.get(award.id)
        if award_card is None:
            award_card = _create(
                card.student, program_id=award.opportunity_id or award.id, candidate=award, name="",
                portal=None, actor=actor, event="application.award_added", capture=True,
            )
            cards[award.id] = award_card
            added.append(award_card)
        _link(award_card, card)
    return added
```

The pool is the programme card's own run (`run_id=candidate.run_id`). That is the pack the student added it from, and `_addable` already requires `state=VISIBLE`, the same rule `add_application` uses.

`_create` calls `_ask_for_portal` when `portal is None`. For an award card, the portal question is about the award's own application, which is correct: a counsellor task asks for it.

- [ ] **Step 4: Call it from `add_application`**

In `apps/portals/applications.py`:
- add `from .award_links import link_awards` at the top;
- in `add_application`, change the `existing` branch to call `link_awards(existing, actor=actor)` before `return existing`;
- change the create path so the card is assigned, linked, then returned:

```python
        with transaction.atomic():
            card = _create(
                student, program_id=target, candidate=candidate, name="",
                portal=_known_portal(target), actor=actor, event="application.added",
                capture=True,
            )
        link_awards(card, actor=actor)
        return card
```

`link_awards` runs outside the savepoint, so a concurrent duplicate award insert raises `IntegrityError` on `portal_app_one_per_candidate`. Guard each `_create` inside `link_awards` with the same savepoint-and-re-read pattern `add_application` uses, so a double click never 500s:

```python
            try:
                with transaction.atomic():
                    award_card = _create(...)
            except IntegrityError:
                award_card = Application.objects.get(student=card.student, candidate=award)
```

Add `from django.db import IntegrityError, transaction` to `award_links.py`.

- [ ] **Step 5: Run the tests and the application suite**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/portals tests/dashboard`
Expected: PASS. Existing tests that add a programme from a pack holding a separate eligible award may now see one more card. Update any count assertion the change breaks, and say which ones in the commit message.

- [ ] **Step 6: Commit**

```bash
cd /home/orkhan/Desktop/lanes-and-money-design && git add apps/portals/award_links.py apps/portals/applications.py tests/portals/test_award_links.py && git commit -m "feat(portals): adding a programme adds the separate awards the student is eligible for

One award is one card, linked to every programme card it funds (lanes spec §4).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Award lines and suggestions for a programme card

**Files:**
- Modify: `apps/portals/award_links.py` (add `award_lines`)
- Test: `tests/portals/test_award_links.py` (append)

**Interfaces:**
- Produces:
  - `AwardLine` (frozen dataclass): `name: str`, `kind: Literal["AUTOMATIC", "SAME_APPLICATION", "NOMINATED", "COMBINED", "SUGGESTED", "NOT_STATED"]`, `text: str`, `candidate_id: UUID`;
  - `award_lines(card: Application) -> list[AwardLine]`: for a programme card, every pack award that funds it and isn't its own card, in the pack's award order.

  Plan 2 renders these lines.

- [ ] **Step 1: Write the failing tests**

Append to `tests/portals/test_award_links.py`:

```python
from apps.portals.award_links import award_lines


def test_lines_say_what_the_student_does(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[
        ("Automatic waiver", "AUTOMATIC_ON_ADMISSION", {}),
        ("Merit scholarship", "CONSIDERED_WITH_ADMISSION", {}),
        ("Dean's award", "INSTITUTION_NOMINATES", {}),
        ("EMJM scholarship", "JOINT_SELECTION", {}),
        ("Mystery fund", "UNSTATED", {}),
    ])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        lines = {line.name: (line.kind, line.text) for line in award_lines(card)}
    assert lines == {
        "Automatic waiver": ("AUTOMATIC", "Considered automatically — nothing to do"),
        "Merit scholarship": ("SAME_APPLICATION", "Considered with your application — nothing extra to submit"),
        "Dean's award": ("NOMINATED", "Nominated by the university — you cannot apply for it"),
        "EMJM scholarship": ("COMBINED", "Programme + scholarship, one application"),
        "Mystery fund": ("NOT_STATED", "How to apply for this is not stated — open its page"),
    }


def test_possibly_eligible_separate_award_is_a_suggestion(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[
        ("SI Scholarship", "STUDENT_APPLIES_SEPARATELY", {"confidence": "LOW"}),
    ])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        (line,) = award_lines(card)
    assert (line.kind, line.text) == ("SUGGESTED", "Suggested for this programme — check you qualify, then add it")


def test_an_award_already_on_the_board_is_not_a_line(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[("SI Scholarship", "STUDENT_APPLIES_SEPARATELY", {})])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        assert award_lines(card) == []


def test_lines_never_use_internal_words(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[(n, r, {}) for n, r in [
        ("A", "AUTOMATIC_ON_ADMISSION"), ("B", "CONSIDERED_WITH_ADMISSION"),
        ("C", "INSTITUTION_NOMINATES"), ("D", "JOINT_SELECTION"), ("E", "UNSTATED"),
    ]])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        text = " ".join(line.text for line in award_lines(card)).casefold()
    for word in ("award", "holder", "route", "_"):
        assert word not in text
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/portals/test_award_links.py`
Expected: FAIL with `ImportError: cannot import name 'award_lines'`.

- [ ] **Step 3: Add `award_lines`**

Append to `apps/portals/award_links.py` (add `from dataclasses import dataclass`, `from typing import Literal`, `from uuid import UUID` to the imports):

```python
LineKind = Literal["AUTOMATIC", "SAME_APPLICATION", "NOMINATED", "COMBINED", "SUGGESTED", "NOT_STATED"]

_LINE_FOR_ROUTE: dict[str, tuple[LineKind, str]] = {
    "AUTOMATIC_ON_ADMISSION": ("AUTOMATIC", "Considered automatically — nothing to do"),
    "CONSIDERED_WITH_ADMISSION": (
        "SAME_APPLICATION", "Considered with your application — nothing extra to submit",
    ),
    "INSTITUTION_NOMINATES": ("NOMINATED", "Nominated by the university — you cannot apply for it"),
    "JOINT_SELECTION": ("COMBINED", "Programme + scholarship, one application"),
    "UNSTATED": ("NOT_STATED", "How to apply for this is not stated — open its page"),
    "": ("NOT_STATED", "How to apply for this is not stated — open its page"),
}
_SUGGESTED: tuple[LineKind, str] = ("SUGGESTED", "Suggested for this programme — check you qualify, then add it")


@dataclass(frozen=True)
class AwardLine:
    name: str
    kind: LineKind
    text: str
    candidate_id: UUID


def award_lines(card: Application) -> list[AwardLine]:
    """What the programme card says about each pack award that funds it and is
    not already its own card (lanes spec §2). Plan 2 renders these."""
    candidate = card.candidate
    if candidate is None or _is_award(candidate):
        return []
    on_board = set(
        Application.objects.filter(student=card.student, candidate__isnull=False)
        .values_list("candidate_id", flat=True)
    )
    lines: list[AwardLine] = []
    for award in RecommendationCandidate.objects.filter(run_id=candidate.run_id).order_by("program_name"):
        if not _is_award(award) or award.id in on_board or award.state != "VISIBLE":
            continue
        if not funds(award, candidate):
            continue
        route = (award.funding_card or {}).get("route", "")
        if route in SEPARATE_ROUTES:
            kind, text = _SUGGESTED
        else:
            kind, text = _LINE_FOR_ROUTE.get(route, _LINE_FOR_ROUTE[""])
        lines.append(AwardLine(award.program_name, kind, text, award.id))
    return lines
```

The candidate set is the programme card's own run, exactly as in `link_awards` (Task 4).

- [ ] **Step 4: Run the tests, then the full suite**

Run: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider tests/portals/test_award_links.py`
Expected: PASS.

Run the full suite once: `cd /home/orkhan/Desktop/lanes-and-money-design && POSTGRES_DB=tehsil_lanes uv run pytest -q -p no:cacheprovider`
Expected: 0 failed.

Run the gates: `uv run ruff check .`, `uv run mypy apps config`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `uv run bandit -c pyproject.toml -r apps config`. All must be clean.

- [ ] **Step 5: Commit**

```bash
cd /home/orkhan/Desktop/lanes-and-money-design && git add apps/portals/award_links.py tests/portals/test_award_links.py && git commit -m "feat(portals): what a programme card says about each award that funds it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
