# Consent and Privacy Notice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A student signs up on a plain-HTML page by ticking one box that accepts the current Terms and Privacy Notice; acceptance is recorded per document version; a material change forces re-acceptance; privacy requests (objection, withdrawal, access, correction, deletion) are logged with a 7-working-day due date, and an open objection or withdrawal stops processing for that student.

**Architecture:** A new app `apps/privacy` holds three models. `LegalDocument` is a shared platform table (no tenant, no RLS) that both runtime roles may only SELECT; rows are written by `manage.py publish_legal_documents` run as the migration role, from text files in `apps/privacy/legal/`. `Acceptance` and `PrivacyRequest` are tenant-scoped with the standard RLS + composite-FK guards. Two lock functions, `acceptance_lock_target` and `privacy_stop_target`, sit beside the existing `deletion_lock_target` and are applied at the same three places (dashboard middleware, extension API, reminder sweep).

**Tech Stack:** Django 5/6, PostgreSQL 17 RLS, pytest-django. Plain unstyled HTML templates (requirements P1-9 amendment).

**Spec:** `docs/superpowers/specs/2026-10-03-consent-and-privacy-notice-design.md` (legal basis: `docs/legal/2026-10-03-consent-and-privacy-memo.md`).

## Global Constraints

- ~~Every student is 18 or over; signup refuses a date of birth under 18 and stores only `age_confirmed_18_plus`~~ — removed 2026-10-04 by the owner: no age check, no date of birth, no stored age (spec §0.5).
- One required, unticked checkbox; wording exactly: "I agree to the Terms of Service and consent to the processing of my personal data as described in the Privacy Notice, including its transfer to the countries it lists." (spec §1).
- Languages at launch: `az`, `en`, `ru` (spec §1). A missing language falls back to `en`.
- Direct students (tenant = `research.PlatformAgency.agency`) accept `terms` + `privacy_notice_direct`; agency students accept `terms` + `privacy_notice_agency` (spec §5).
- Privacy request deadline: 7 working days (Mon–Fri) from receipt (spec §6). No public-holiday calendar.
- Requests are advertised by e-mail only; a request on paper with ID or by enhanced e-signature is still logged (spec §6). No privacy-settings page (spec §8).
- Lint: `uv run ruff check .` only, never `ruff format`. Types: `uv run mypy apps config`. Tests: `POSTGRES_DB=tehsil_consent_privacy uv run pytest -q`.
- New tenant tables: `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy `tenant_isolation`, composite FK `(tenant_id, student_id) -> tenancy_membership (tenant_id, id)` (CLAUDE.md, "Row-level security").
- Every field of a model reachable from `Membership` is classified once in `apps/audit/redaction.py` `REDACT` or `KEEP` (`tests/audit/test_redaction_classification.py`).
- **Deferred, not in this plan:** the anonymiser and anonymised store (spec §4, build step 3). No admission or funding outcome is recorded anywhere yet (CLAUDE.md, "Derived data"), so there is nothing to anonymise; build it with outcome capture (tailored-programme spec build step 8). The agency data-processing agreement is a document (Task 6), not code.
- **Also deferred:** deleting personal data 12 months after an account goes inactive (spec §2, §4) — it needs a scheduled job, and the erasure schedule itself is deliberately unscheduled until something is deployed (CLAUDE.md, "Erasure: the schedule is deferred"); build both together. Marketing e-mails to former students (spec §7) — nothing sends e-mail to students yet; the unsubscribe record ships with the first such e-mail.

## Review Focus

1. **A student who signed up before a material change logs in** — must land on the re-acceptance page, not the dashboard; must still reach the legal pages and the deletion pages. (Task 4)
2. **A device-token request from a student with an open objection** — the extension API must refuse it (`processing_stopped` 403) exactly as it refuses a pending erasure. (Task 5)
3. **Signup with an e-mail that already has an account, in any case** — refused with a form error, no second User, no Membership. (Task 3)
4. **A date of birth exactly 18 years ago today, and 29 February birthdays** — 18 today is accepted; a 29 Feb birthday turns 18 on 1 Mar in non-leap years. (Task 3)
5. **The web role trying to write `LegalDocument`** — permission denied; only the owner (migration role) can publish. (Task 1)

---

## File structure

- `apps/privacy/__init__.py`, `apps/privacy/apps.py` — app registration.
- `apps/privacy/models.py` — `LegalDocument`, `Acceptance`, `PrivacyRequest`.
- `apps/privacy/documents.py` — reading the text files, publishing versions, picking current documents.
- `apps/privacy/acceptance.py` — required kinds per tenant, recording acceptance, `acceptance_lock_target`.
- `apps/privacy/requests.py` — working-day due dates, recording requests, `privacy_stop_target`.
- `apps/privacy/views.py`, `apps/privacy/urls.py`, `apps/privacy/forms.py` — signup, re-acceptance, legal pages, stopped page.
- `apps/privacy/templates/privacy/*.html` — plain HTML.
- `apps/privacy/legal/<kind>.<lang>.md` — the document texts.
- `apps/privacy/management/commands/publish_legal_documents.py`, `record_privacy_request.py`, `list_privacy_requests.py`.
- `apps/privacy/migrations/0001_initial.py` (models), `0002_guards.py` (RLS, composite FKs, grants, owner-only trigger).
- Modify: `config/settings/base.py` (INSTALLED_APPS), `config/urls.py`, `apps/tenancy/middleware.py`, `apps/portals/ext_api.py`, `apps/portals/reminders.py`, `apps/audit/redaction.py`.
- Tests: `tests/privacy/test_documents.py`, `test_acceptance.py`, `test_signup.py`, `test_reacceptance.py`, `test_requests.py`, `test_guards.py`.
- Docs: `docs/runbooks/privacy.md`, `docs/legal/2026-10-03-agency-data-processing-agreement.md`.

---

### Task 1: The app, `LegalDocument`, and publishing document versions

**Files:**
- Create: `apps/privacy/__init__.py`, `apps/privacy/apps.py`, `apps/privacy/models.py`, `apps/privacy/documents.py`, `apps/privacy/management/__init__.py`, `apps/privacy/management/commands/__init__.py`, `apps/privacy/management/commands/publish_legal_documents.py`, `apps/privacy/migrations/__init__.py`, `apps/privacy/migrations/0001_initial.py`, `apps/privacy/migrations/0002_guards.py`, `apps/privacy/legal/terms.en.md`, `apps/privacy/legal/privacy_notice_direct.en.md`, `apps/privacy/legal/privacy_notice_agency.en.md`
- Modify: `config/settings/base.py:16` (append `"apps.privacy"` to INSTALLED_APPS after `"apps.mailbox"`)
- Test: `tests/privacy/__init__.py`, `tests/privacy/test_documents.py`, `tests/privacy/test_guards.py`

**Interfaces:**
- Produces:
  - `LegalDocument` fields: `id: UUID`, `kind: str` (choices `terms`, `privacy_notice_direct`, `privacy_notice_agency`), `language: str` (`az`/`en`/`ru`), `version: int` (≥1, unique with kind+language), `body: str`, `sha256: str` (64 hex, unique with kind+language), `material: bool`, `effective_at: datetime`.
  - `documents.LANGUAGES = ("az", "en", "ru")`, `documents.KINDS = ("terms", "privacy_notice_direct", "privacy_notice_agency")`.
  - `documents.publish(kind: str, language: str, body: str, *, material: bool) -> tuple[LegalDocument, bool]` — returns `(row, created)`; same `sha256` as the latest version → `(latest, False)`.
  - `documents.current(kind: str, language: str) -> LegalDocument | None` — latest version in that language, else latest in `en`, else None.

- [ ] **Step 1: Write the failing tests**

`tests/privacy/test_documents.py`:

```python
import pytest

from apps.privacy import documents
from apps.privacy.models import LegalDocument


@pytest.mark.django_db
def test_publishing_new_text_adds_a_version_and_same_text_does_not():
    first, created = documents.publish("terms", "en", "Terms v1", material=True)
    assert created and first.version == 1
    again, created = documents.publish("terms", "en", "Terms v1", material=True)
    assert not created and again.pk == first.pk
    second, created = documents.publish("terms", "en", "Terms v2", material=False)
    assert created and second.version == 2 and second.material is False
    assert LegalDocument.objects.filter(kind="terms", language="en").count() == 2


@pytest.mark.django_db
def test_current_falls_back_to_english():
    documents.publish("terms", "en", "Terms", material=True)
    assert documents.current("terms", "az").language == "en"
    documents.publish("terms", "az", "Şərtlər", material=True)
    assert documents.current("terms", "az").language == "az"
    assert documents.current("privacy_notice_direct", "az") is None


@pytest.mark.django_db
def test_publish_refuses_unknown_kind_and_language():
    with pytest.raises(ValueError):
        documents.publish("cookies", "en", "x", material=True)
    with pytest.raises(ValueError):
        documents.publish("terms", "de", "x", material=True)


@pytest.mark.django_db
def test_command_publishes_every_shipped_file(capsys):
    from django.core.management import call_command

    call_command("publish_legal_documents")
    kinds = set(LegalDocument.objects.values_list("kind", flat=True))
    assert kinds == {"terms", "privacy_notice_direct", "privacy_notice_agency"}
    call_command("publish_legal_documents")  # idempotent
    assert LegalDocument.objects.filter(kind="terms", language="en").count() == 1
```

`tests/privacy/test_guards.py` (grants; uses the existing `role_connection` factory in `tests/conftest.py:234` — read its docstring for the call shape before writing):

```python
import pytest
from django.db import connection


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("role", ["runtime_web", "runtime_engine"])
def test_runtime_roles_read_but_never_write_legal_documents(role, role_connection):
    from apps.privacy import documents

    documents.publish("terms", "en", "Terms", material=True)  # as the owner
    with role_connection(role) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM privacy_legaldocument")
        assert cur.fetchone()[0] == 1
        with pytest.raises(Exception, match="permission denied|only the owner"):
            cur.execute(
                "INSERT INTO privacy_legaldocument (id, kind, language, version, body, sha256, material, effective_at)"
                " VALUES (gen_random_uuid(), 'terms', 'en', 2, 'x', repeat('a', 64), true, now())"
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.privacy'`.

- [ ] **Step 3: Implement**

`apps/privacy/apps.py`:

```python
from django.apps import AppConfig


class PrivacyConfig(AppConfig):
    name = "apps.privacy"
```

`apps/privacy/models.py` (only `LegalDocument` in this task; Tasks 2 and 5 append):

```python
"""Consent and privacy records (spec 2026-10-03-consent-and-privacy-notice-design.md).

`LegalDocument` is platform data, not a tenant's: one Terms and two Privacy
Notices per language, versioned. Both runtime roles may only read it; the owner
(the migration role) publishes through `manage.py publish_legal_documents`, so
the text a student accepted can never be edited after the fact.
"""

from uuid import uuid4

from django.db import models


class LegalDocument(models.Model):
    class Kind(models.TextChoices):
        TERMS = "terms", "Terms of Service"
        PRIVACY_NOTICE_DIRECT = "privacy_notice_direct", "Privacy Notice"
        PRIVACY_NOTICE_AGENCY = "privacy_notice_agency", "Privacy Notice"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    kind = models.CharField(max_length=40, choices=Kind.choices)
    language = models.CharField(max_length=2)
    version = models.PositiveIntegerField()
    body = models.TextField()
    sha256 = models.CharField(max_length=64)
    #: A material change makes every student re-accept at their next login.
    material = models.BooleanField(default=True)
    effective_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("kind", "language", "version"), name="legal_document_version_uniq"),
            models.UniqueConstraint(fields=("kind", "language", "sha256"), name="legal_document_text_uniq"),
            models.CheckConstraint(condition=models.Q(version__gt=0), name="legal_document_version_positive"),
        ]
```

`apps/privacy/documents.py`:

```python
"""Publishing and choosing legal document versions."""

import hashlib
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.privacy.models import LegalDocument

LANGUAGES = ("az", "en", "ru")
KINDS = tuple(LegalDocument.Kind.values)
LEGAL_DIR = Path(__file__).resolve().parent / "legal"


def _check(kind: str, language: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown legal document kind {kind!r}")
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language {language!r}")


def publish(kind: str, language: str, body: str, *, material: bool) -> tuple[LegalDocument, bool]:
    """Add a version when the text changed; the same text returns the latest row."""
    _check(kind, language)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with transaction.atomic():
        latest = (
            LegalDocument.objects.select_for_update()
            .filter(kind=kind, language=language)
            .order_by("-version")
            .first()
        )
        if latest is not None and latest.sha256 == digest:
            return latest, False
        row = LegalDocument.objects.create(
            kind=kind,
            language=language,
            version=(latest.version + 1) if latest else 1,
            body=body,
            sha256=digest,
            material=material,
            effective_at=timezone.now(),
        )
        return row, True


def current(kind: str, language: str) -> LegalDocument | None:
    """The latest version in `language`, else in English, else None."""
    for lang in dict.fromkeys((language, "en")):
        row = LegalDocument.objects.filter(kind=kind, language=lang).order_by("-version").first()
        if row is not None:
            return row
    return None


def shipped_files() -> list[tuple[str, str, Path]]:
    """(kind, language, path) for every `legal/<kind>.<lang>.md` file."""
    out = []
    for path in sorted(LEGAL_DIR.glob("*.md")):
        kind, _, language = path.stem.rpartition(".")
        _check(kind, language)
        out.append((kind, language, path))
    return out
```

`apps/privacy/management/commands/publish_legal_documents.py`:

```python
"""Publish every `apps/privacy/legal/<kind>.<lang>.md` whose text changed.

Run as the migration role (DATABASE_ROLE=migration): the runtime roles may only
read privacy_legaldocument, and an owner-only trigger refuses anyone else.
`--minor` marks the new versions as non-material, so students are not asked to
re-accept a typo fix.
"""

from django.core.management.base import BaseCommand

from apps.privacy import documents


class Command(BaseCommand):
    help = "Publish changed legal document texts as new versions."

    def add_arguments(self, parser):
        parser.add_argument("--minor", action="store_true", help="the change is not material")

    def handle(self, *args, minor: bool = False, **options):
        for kind, language, path in documents.shipped_files():
            row, created = documents.publish(
                kind, language, path.read_text(encoding="utf-8"), material=not minor
            )
            state = "published" if created else "unchanged"
            self.stdout.write(f"{kind}.{language}: v{row.version} {state}")
```

`apps/privacy/migrations/0001_initial.py`: generate with `uv run python manage.py makemigrations privacy`, then check it creates only `LegalDocument` with the three constraints.

`apps/privacy/migrations/0002_guards.py` — the same grant + owner-only-trigger shape as `apps/research/migrations/0013_resolution_item_rls.py:106-131` (read it first), without RLS (the table holds no person):

```python
"""Both runtime roles read legal documents; only the owner writes them.

Same shape as research/0013's platform-agency marker, and for the same reason:
the text a student accepted must not be editable by the web tier. No RLS -- the
table holds no person and every tenant shows the same documents. Depends on
funding/0049, whose default privileges grant DML on every new table to both
runtime roles; this migration takes the writes back.
"""

from django.db import migrations

TABLE = "privacy_legaldocument"

FORWARD = f"""
REVOKE ALL ON public.{TABLE} FROM runtime_engine, runtime_web;
GRANT SELECT ON public.{TABLE} TO runtime_engine, runtime_web;

CREATE FUNCTION public.privacy_legaldocument_owner_only() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NOT pg_has_role(
        current_user, (SELECT relowner FROM pg_class WHERE oid = TG_RELID), 'USAGE'
    ) THEN
        RAISE EXCEPTION 'only the owner of % may write it: run manage.py '
            'publish_legal_documents with DATABASE_ROLE=migration', TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER privacy_legaldocument_owner_only
    BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{TABLE}
    FOR EACH STATEMENT EXECUTE FUNCTION public.privacy_legaldocument_owner_only();
"""

REVERSE = f"""
DROP TRIGGER IF EXISTS privacy_legaldocument_owner_only ON public.{TABLE};
DROP FUNCTION IF EXISTS public.privacy_legaldocument_owner_only();
GRANT SELECT, INSERT, UPDATE, DELETE ON public.{TABLE} TO runtime_engine, runtime_web;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("privacy", "0001_initial"),
        ("funding", "0049_catalog_grants"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
```

The three `legal/*.en.md` files: copy their text from Task 6, Step 1 (write Task 6's English drafts now; Task 6 adds `az` and `ru` and reviews them).

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy -q`
Expected: PASS. If `test_runtime_roles_read_but_never_write_legal_documents` fails because `funding/0049`'s default privileges are not applied to this table, check the migration order with `uv run python manage.py showmigrations privacy funding`.

Then run the sweeps a new table can trip: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/tenancy tests/audit -q`. Expected: PASS. `LegalDocument` is not added to `_SHARED_TABLES` (that list is for catalogue tables with `shared_catalog_select`, which the web role cannot read).

- [ ] **Step 5: Commit**

```bash
git add apps/privacy config/settings/base.py tests/privacy
git commit -m "feat(privacy): versioned legal documents, readable by both roles, written only by the owner"
```

---

### Task 2: `Acceptance` and what a student must have accepted

**Files:**
- Modify: `apps/privacy/models.py` (append `Acceptance`), `apps/audit/redaction.py` (KEEP entry)
- Create: `apps/privacy/acceptance.py`, `apps/privacy/migrations/0003_acceptance.py` (generated), `apps/privacy/migrations/0004_acceptance_guards.py`
- Test: `tests/privacy/test_acceptance.py`

**Interfaces:**
- Consumes: `LegalDocument`, `documents.current(kind, language)` (Task 1); `research.models.PlatformAgency`; `tenancy.models.Membership`, `TenantScopedModel`.
- Produces:
  - `Acceptance` fields: `tenant` (from base), `id`, `student: FK Membership (PROTECT)`, `document: FK LegalDocument (PROTECT)`, `accepted_at: datetime`, `surface: str` (`signup`/`reacceptance`), `language: str`, `age_confirmed_18_plus: bool`.
  - `acceptance.required_kinds(tenant_id: UUID) -> tuple[str, str]` — `("terms", "privacy_notice_direct")` for the platform agency, else `("terms", "privacy_notice_agency")`.
  - `acceptance.documents_to_accept(tenant_id: UUID, language: str) -> list[LegalDocument]`.
  - `acceptance.record(student: Membership, docs: list[LegalDocument], *, surface: str, language: str) -> None`.
  - `acceptance.needs_acceptance(student: Membership) -> bool`.
  - `acceptance.acceptance_lock_target(membership: Membership) -> str | None` — `reverse("privacy-accept")` when a student needs acceptance, else None. (`privacy-accept` URL arrives in Task 4; the test here reverses lazily, so Task 2 tests do not call it.)

- [ ] **Step 1: Write the failing tests**

`tests/privacy/test_acceptance.py`:

```python
import pytest

from apps.privacy import acceptance, documents
from apps.privacy.models import Acceptance
from apps.tenancy.context import tenant_scope


@pytest.fixture
def published(db):
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)


@pytest.mark.django_db
def test_agency_students_accept_the_agency_notice(agency_a, published):
    assert acceptance.required_kinds(agency_a.id) == ("terms", "privacy_notice_agency")


@pytest.mark.django_db
def test_platform_students_accept_the_direct_notice(agency_a, published):
    from apps.research.models import PlatformAgency

    PlatformAgency.objects.create(agency=agency_a)
    assert acceptance.required_kinds(agency_a.id) == ("terms", "privacy_notice_direct")


@pytest.mark.django_db
def test_accepting_clears_the_need_and_a_material_change_brings_it_back(membership_a, published):
    with tenant_scope(membership_a.tenant_id):
        assert acceptance.needs_acceptance(membership_a)
        docs = acceptance.documents_to_accept(membership_a.tenant_id, "en")
        acceptance.record(membership_a, docs, surface="signup", language="en")
        assert not acceptance.needs_acceptance(membership_a)
        assert Acceptance.objects.filter(student=membership_a).count() == 2

        documents.publish("terms", "en", "terms v2 typo fix", material=False)
        assert not acceptance.needs_acceptance(membership_a)
        documents.publish("terms", "en", "terms v3 new purpose", material=True)
        assert acceptance.needs_acceptance(membership_a)


@pytest.mark.django_db
def test_counselors_never_need_student_acceptance(counselor_membership, published):
    with tenant_scope(counselor_membership.tenant_id):
        assert not acceptance.needs_acceptance(counselor_membership)


@pytest.mark.django_db
def test_no_published_documents_means_nothing_to_accept(membership_a):
    with tenant_scope(membership_a.tenant_id):
        assert not acceptance.needs_acceptance(membership_a)
```

Also add an RLS test using the existing `rls_enforced_orm` fixture (read `tests/portals/test_rls_spine.py` for its use) asserting tenant B cannot read tenant A's `Acceptance` row:

```python
@pytest.mark.django_db(transaction=True)
def test_acceptance_rows_are_tenant_isolated(membership_a, agency_b, published, rls_enforced_orm):
    from apps.tenancy.db import tenant_transaction

    with tenant_scope(membership_a.tenant_id), tenant_transaction(membership_a.tenant_id):
        docs = acceptance.documents_to_accept(membership_a.tenant_id, "en")
        acceptance.record(membership_a, docs, surface="signup", language="en")
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert Acceptance._base_manager.count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy/test_acceptance.py -q`
Expected: FAIL — `ImportError: cannot import name 'acceptance'`.

- [ ] **Step 3: Implement**

Append to `apps/privacy/models.py`:

```python
from apps.tenancy.models import Membership, TenantScopedModel


class Acceptance(TenantScopedModel):
    """One row per document version a student accepted (spec §3)."""

    class Surface(models.TextChoices):
        SIGNUP = "signup", "Signup"
        REACCEPTANCE = "reacceptance", "Re-acceptance"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="acceptances")
    document = models.ForeignKey(LegalDocument, on_delete=models.PROTECT, related_name="+")
    accepted_at = models.DateTimeField()
    surface = models.CharField(max_length=20, choices=Surface.choices)
    language = models.CharField(max_length=2)
    age_confirmed_18_plus = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="acceptance_tenant_id_uniq"),
            models.UniqueConstraint(fields=("tenant", "student", "document"), name="acceptance_once_per_document"),
        ]
```

`apps/privacy/acceptance.py`:

```python
"""Which documents a student must have accepted, and the lock that enforces it."""

from uuid import UUID

from django.urls import reverse
from django.utils import timezone

from apps.privacy import documents
from apps.privacy.models import Acceptance, LegalDocument
from apps.tenancy.models import Membership


def required_kinds(tenant_id: UUID) -> tuple[str, str]:
    from apps.research.models import PlatformAgency

    direct = PlatformAgency.objects.filter(agency_id=tenant_id).exists()
    return ("terms", "privacy_notice_direct" if direct else "privacy_notice_agency")


def documents_to_accept(tenant_id: UUID, language: str) -> list[LegalDocument]:
    docs = [documents.current(kind, language) for kind in required_kinds(tenant_id)]
    return [d for d in docs if d is not None]


def record(student: Membership, docs: list[LegalDocument], *, surface: str, language: str) -> None:
    now = timezone.now()
    for doc in docs:
        Acceptance.objects.get_or_create(
            student=student,
            document=doc,
            defaults={"accepted_at": now, "surface": surface, "language": language},
        )


def needs_acceptance(student: Membership) -> bool:
    """True when some required kind has a material version newer than any the student accepted.

    The language is the one the student last accepted in (English before any).
    A kind with no published document asks for nothing.
    """
    if student.role != Membership.Role.STUDENT:
        return False
    last = Acceptance.objects.filter(student=student).order_by("-accepted_at").first()
    language = last.language if last else "en"
    for kind in required_kinds(student.tenant_id):
        doc = documents.current(kind, language)
        if doc is None:
            continue
        newest_material = (
            LegalDocument.objects.filter(kind=doc.kind, language=doc.language, material=True)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        ) or 0
        accepted = (
            Acceptance.objects.filter(student=student, document__kind=doc.kind, document__language=doc.language)
            .order_by("-document__version")
            .values_list("document__version", flat=True)
            .first()
        ) or 0
        if accepted < newest_material:
            return True
    return False


def acceptance_lock_target(membership: Membership) -> str | None:
    return reverse("privacy-accept") if needs_acceptance(membership) else None
```

Migrations: `uv run python manage.py makemigrations privacy` (creates `0003_acceptance`). Then write `0004_acceptance_guards.py` copying `apps/audit/migrations/0008_pseudonym_tenant_guards.py` exactly, with `TABLES = ("privacy_acceptance",)`, constraint `acceptance_student_tenant_fk` on `(tenant_id, student_id) REFERENCES tenancy_membership (tenant_id, id)`, and dependencies `[("privacy", "0003_acceptance"), ("tenancy", "0002_rls")]`.

`apps/audit/redaction.py` `KEEP`: add, with a comment that none of it is personal data and the identifying link is the `student` relation (excluded from classification):

```python
    "privacy.Acceptance": ("accepted_at", "surface", "language", "age_confirmed_18_plus"),
```

If `tests/audit/test_redaction_classification.py` then reports `privacy.LegalDocument` as reachable and unclassified, add it to `KEEP` too (platform text, no person):

```python
    "privacy.LegalDocument": ("kind", "language", "version", "body", "sha256", "material", "effective_at"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy tests/audit/test_redaction_classification.py tests/tenancy/test_database_isolation.py -q`
Expected: PASS (including `test_every_tenant_scoped_model_has_rls_enabled_and_forced`).

- [ ] **Step 5: Commit**

```bash
git add apps/privacy apps/audit/redaction.py tests/privacy
git commit -m "feat(privacy): record accepted document versions; a material change asks again"
```

---

### Task 3: Signup page

**Files:**
- Create: `apps/privacy/forms.py`, `apps/privacy/views.py`, `apps/privacy/urls.py`, `apps/privacy/templates/privacy/signup.html`, `apps/privacy/templates/privacy/legal_document.html`
- Modify: `config/urls.py` (add `path("", include("apps.privacy.urls")),` after the mailbox include)
- Test: `tests/privacy/test_signup.py`

**Interfaces:**
- Consumes: `acceptance.documents_to_accept`, `acceptance.record` (Task 2); `documents.current` (Task 1).
- Produces: URL names `privacy-signup` (`/signup/`), `privacy-legal` (`/legal/<kind>/`), `forms.SignupForm`, `forms.is_adult(born: date, today: date) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/privacy/test_signup.py`:

```python
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.privacy import documents
from apps.privacy.forms import is_adult
from apps.privacy.models import Acceptance
from apps.tenancy.models import Membership

CONSENT = "consent"


@pytest.fixture
def published(db):
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)


def _post(client, host, **over):
    data = {
        "full_name": "Aysel Mammadova",
        "email": "Aysel@Example.com",
        "password": "correct-horse-battery-staple",
        "date_of_birth": "2000-05-01",
        "language": "en",
        CONSENT: "on",
    }
    data.update(over)
    return client.post(reverse("privacy-signup"), data, HTTP_HOST=host)


def test_is_adult_edges():
    assert is_adult(date(2008, 10, 3), date(2026, 10, 3))
    assert not is_adult(date(2008, 10, 4), date(2026, 10, 3))
    assert not is_adult(date(2008, 2, 29), date(2026, 2, 28))
    assert is_adult(date(2008, 2, 29), date(2026, 3, 1))


@pytest.mark.django_db
def test_signup_creates_student_records_acceptance_and_logs_in(client, domain_a, published):
    response = _post(client, domain_a.host)
    assert response.status_code == 302
    user = get_user_model().objects.get(username="aysel@example.com")
    membership = Membership._base_manager.get(user=user)
    assert membership.role == Membership.Role.STUDENT and membership.tenant_id == domain_a.agency_id
    kinds = set(Acceptance._base_manager.filter(student=membership).values_list("document__kind", flat=True))
    assert kinds == {"terms", "privacy_notice_agency"}
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_signup_without_the_tick_creates_nothing(client, domain_a, published):
    response = _post(client, domain_a.host, **{CONSENT: ""})
    assert response.status_code == 400
    assert not get_user_model().objects.exists()


@pytest.mark.django_db
def test_signup_under_18_is_refused(client, domain_a, published):
    response = _post(client, domain_a.host, date_of_birth=date.today().replace(year=date.today().year - 17).isoformat())
    assert response.status_code == 400
    assert not get_user_model().objects.exists()


@pytest.mark.django_db
def test_signup_with_an_existing_email_in_any_case_is_refused(client, domain_a, published):
    assert _post(client, domain_a.host).status_code == 302
    client.logout()
    response = _post(client, domain_a.host, email="AYSEL@example.COM")
    assert response.status_code == 400
    assert get_user_model().objects.count() == 1


@pytest.mark.django_db
def test_signup_refuses_when_no_documents_are_published(client, domain_a):
    response = _post(client, domain_a.host)
    assert response.status_code == 503
    assert not get_user_model().objects.exists()


@pytest.mark.django_db
def test_date_of_birth_is_never_stored(client, domain_a, published):
    _post(client, domain_a.host)
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name LIKE 'privacy_%' AND column_name ILIKE '%birth%'"
        )
        assert cur.fetchone()[0] == 0


@pytest.mark.django_db
def test_legal_page_shows_the_current_text(client, domain_a, published):
    response = client.get(reverse("privacy-legal", args=["terms"]) + "?lang=az", HTTP_HOST=domain_a.host)
    assert response.status_code == 200 and b"terms v1" in response.content
    assert client.get(reverse("privacy-legal", args=["cookies"]), HTTP_HOST=domain_a.host).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy/test_signup.py -q`
Expected: FAIL — `ImportError` / `NoReverseMatch`.

- [ ] **Step 3: Implement**

`apps/privacy/forms.py`:

```python
from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from apps.privacy.documents import LANGUAGES

CONSENT_TEXT = (
    "I agree to the Terms of Service and consent to the processing of my personal data as "
    "described in the Privacy Notice, including its transfer to the countries it lists."
)


def is_adult(born: date, today: date) -> bool:
    """18 or over today; a 29 February birthday turns 18 on 1 March in a non-leap year."""
    try:
        eighteenth = born.replace(year=born.year + 18)
    except ValueError:  # 29 Feb into a non-leap year
        eighteenth = date(born.year + 18, 3, 1)
    return today >= eighteenth


class SignupForm(forms.Form):
    full_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput, min_length=12)
    #: Used only to confirm 18+ and then discarded (spec §0.5); never saved.
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    language = forms.ChoiceField(choices=[(code, code) for code in LANGUAGES], initial="en")
    consent = forms.BooleanField(required=True, label=CONSENT_TEXT)

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("An account with this e-mail already exists.")
        return email

    def clean_date_of_birth(self) -> date:
        born = self.cleaned_data["date_of_birth"]
        if not is_adult(born, date.today()):
            raise forms.ValidationError("You must be 18 or over to sign up.")
        return born

    def clean_password(self) -> str:
        password = self.cleaned_data["password"]
        validate_password(password)
        return password
```

`apps/privacy/views.py` (signup + legal page; Task 4 and 5 append):

```python
"""Signup, legal pages, re-acceptance and the processing-stopped notice.

Plain, unstyled HTML on purpose (requirements P1-9 amendment): the team designs
the presentation later; these pages exist so the behaviour can be tested end to end.
"""

from django.contrib.auth import get_user_model, login
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.privacy import acceptance, documents
from apps.privacy.forms import CONSENT_TEXT, SignupForm
from apps.tenancy.context import current_tenant_id
from apps.tenancy.models import Membership


@require_http_methods(["GET", "POST"])
def signup(request: HttpRequest) -> HttpResponse:
    tenant_id = current_tenant_id()
    language = request.POST.get("language") or request.GET.get("lang") or "en"
    docs = acceptance.documents_to_accept(tenant_id, language)
    if len(docs) < 2:
        # Never create an account that accepted nothing: the documents are published
        # by `manage.py publish_legal_documents` at deploy (docs/runbooks/privacy.md).
        return HttpResponse("Signup is not available yet.", status=503)
    form = SignupForm(request.POST or None, initial={"language": language})
    if request.method == "POST":
        if not form.is_valid():
            return render(request, "privacy/signup.html", {"form": form, "docs": docs, "consent_text": CONSENT_TEXT}, status=400)
        data = form.cleaned_data
        first, _, last = data["full_name"].strip().partition(" ")
        user = get_user_model().objects.create_user(
            username=data["email"], email=data["email"], password=data["password"],
            first_name=first, last_name=last,
        )
        student = Membership.objects.create(user=user, role=Membership.Role.STUDENT)
        acceptance.record(student, acceptance.documents_to_accept(tenant_id, data["language"]),
                          surface="signup", language=data["language"])
        login(request, user)
        return redirect("/student/")
    return render(request, "privacy/signup.html", {"form": form, "docs": docs, "consent_text": CONSENT_TEXT})


def legal_document(request: HttpRequest, kind: str) -> HttpResponse:
    if kind not in documents.KINDS:
        raise Http404
    doc = documents.current(kind, request.GET.get("lang") or "en")
    if doc is None:
        raise Http404
    return render(request, "privacy/legal_document.html", {"doc": doc})
```

The `HostTenantContextMiddleware` already wraps each request in `atomic()` with the tenant set, so the User, Membership and Acceptance rows commit together or not at all.

`apps/privacy/urls.py`:

```python
from django.urls import path

from apps.privacy import views

urlpatterns = [
    path("signup/", views.signup, name="privacy-signup"),
    path("legal/<str:kind>/", views.legal_document, name="privacy-legal"),
]
```

`apps/privacy/templates/privacy/signup.html` (plain; mirror `apps/documents/templates/documents/gap_interview.html`'s skeleton):

```html
<!doctype html>
<html lang="{{ form.language.value|default:'en' }}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Sign up</title></head>
<body>
<main>
  <h1>Sign up</h1>
  <form method="post">
    {% csrf_token %}
    {{ form.non_field_errors }}
    <p>{{ form.full_name.label_tag }} {{ form.full_name }} {{ form.full_name.errors }}</p>
    <p>{{ form.email.label_tag }} {{ form.email }} {{ form.email.errors }}</p>
    <p>{{ form.password.label_tag }} {{ form.password }} {{ form.password.errors }}</p>
    <p>{{ form.date_of_birth.label_tag }} {{ form.date_of_birth }} {{ form.date_of_birth.errors }}</p>
    <p>{{ form.language.label_tag }} {{ form.language }}</p>
    <p>
      <label><input type="checkbox" name="consent" {% if form.consent.value %}checked{% endif %}>
      I agree to the <a href="{% url 'privacy-legal' 'terms' %}?lang={{ form.language.value|default:'en' }}">Terms of Service</a>
      and consent to the processing of my personal data as described in the
      {% for doc in docs %}{% if doc.kind != 'terms' %}<a href="{% url 'privacy-legal' doc.kind %}?lang={{ doc.language }}">Privacy Notice</a>{% endif %}{% endfor %},
      including its transfer to the countries it lists.</label>
      {{ form.consent.errors }}
    </p>
    <button type="submit">Create account</button>
  </form>
</main>
</body>
</html>
```

`apps/privacy/templates/privacy/legal_document.html`:

```html
<!doctype html>
<html lang="{{ doc.language }}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{ doc.get_kind_display }}</title></head>
<body><main>
  <p>Version {{ doc.version }}, effective {{ doc.effective_at|date:"Y-m-d" }}</p>
  <pre style="white-space: pre-wrap">{{ doc.body }}</pre>
</main></body>
</html>
```

If `/signup/` and `/legal/` are rejected by `TenantMembershipMiddleware` for anonymous users: they are not (it acts only when authenticated). If the `@login_required` default `LOGIN_URL` matters: it does not here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/privacy config/urls.py tests/privacy
git commit -m "feat(privacy): plain-HTML signup with one consent box and an 18+ check"
```

---

### Task 4: Re-acceptance after a material change

**Files:**
- Modify: `apps/privacy/views.py`, `apps/privacy/urls.py`, `apps/tenancy/middleware.py:26` and `:117-120`
- Create: `apps/privacy/templates/privacy/accept.html`
- Test: `tests/privacy/test_reacceptance.py`

**Interfaces:**
- Consumes: `acceptance.acceptance_lock_target`, `needs_acceptance`, `documents_to_accept`, `record` (Task 2).
- Produces: URL `privacy-accept` (`/privacy/accept/`); middleware applies the acceptance lock after the deletion lock.

- [ ] **Step 1: Write the failing tests**

`tests/privacy/test_reacceptance.py`:

```python
import pytest
from django.urls import reverse

from apps.privacy import acceptance, documents
from apps.tenancy.context import tenant_scope


@pytest.fixture
def accepted(membership_a):
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)
    with tenant_scope(membership_a.tenant_id):
        acceptance.record(membership_a, acceptance.documents_to_accept(membership_a.tenant_id, "en"),
                          surface="signup", language="en")
    return membership_a


@pytest.mark.django_db
def test_a_material_change_redirects_every_page_to_reacceptance(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302 and response["Location"] == reverse("privacy-accept")


@pytest.mark.django_db
def test_legal_pages_and_deletion_pages_stay_reachable(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    assert client.get(reverse("privacy-legal", args=["terms"]), HTTP_HOST=domain_a.host).status_code == 200
    assert client.get(reverse("privacy-accept"), HTTP_HOST=domain_a.host).status_code == 200


@pytest.mark.django_db
def test_reaccepting_lifts_the_lock(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    response = client.post(reverse("privacy-accept"), {"consent": "on"}, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    with tenant_scope(accepted.tenant_id):
        assert not acceptance.needs_acceptance(accepted)


@pytest.mark.django_db
def test_reaccept_without_the_tick_keeps_the_lock(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    assert client.post(reverse("privacy-accept"), {}, HTTP_HOST=domain_a.host).status_code == 400
    with tenant_scope(accepted.tenant_id):
        assert acceptance.needs_acceptance(accepted)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy/test_reacceptance.py -q`
Expected: FAIL — `NoReverseMatch: 'privacy-accept'`.

- [ ] **Step 3: Implement**

Append to `apps/privacy/views.py`:

```python
from django.contrib.auth.decorators import login_required

from apps.tenancy.services import current_membership


@login_required
@require_http_methods(["GET", "POST"])
def accept(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    last = student.acceptances.order_by("-accepted_at").first()
    language = last.language if last else "en"
    docs = acceptance.documents_to_accept(student.tenant_id, language)
    if request.method == "POST":
        if request.POST.get("consent") != "on":
            return render(request, "privacy/accept.html", {"docs": docs, "consent_text": CONSENT_TEXT, "error": True}, status=400)
        acceptance.record(student, docs, surface="reacceptance", language=language)
        return redirect("/student/")
    return render(request, "privacy/accept.html", {"docs": docs, "consent_text": CONSENT_TEXT})
```

`apps/privacy/urls.py`: add `path("privacy/accept/", views.accept, name="privacy-accept"),`.

`apps/privacy/templates/privacy/accept.html`:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Updated terms</title></head>
<body><main>
  <h1>We updated our terms</h1>
  <p>Please read the new versions:</p>
  <ul>{% for doc in docs %}<li><a href="{% url 'privacy-legal' doc.kind %}?lang={{ doc.language }}">{{ doc.get_kind_display }}</a> (version {{ doc.version }})</li>{% endfor %}</ul>
  <form method="post">{% csrf_token %}
    <p><label><input type="checkbox" name="consent"> {{ consent_text }}</label>{% if error %} <strong>Tick the box to continue.</strong>{% endif %}</p>
    <button type="submit">Continue</button>
  </form>
</main></body>
</html>
```

`apps/tenancy/middleware.py`: extend the exempt prefixes and apply the second lock right after the deletion lock (same request, same membership):

```python
_DELETION_EXEMPT_PREFIXES = ("/student/account/deletion/", "/student/account/restore/")
#: Reachable while a student must re-accept: the page itself, the documents it
#: links to, and the deletion pages (refusing new terms must not block erasure).
_ACCEPTANCE_EXEMPT_PREFIXES = ("/privacy/accept/", "/legal/", *_DELETION_EXEMPT_PREFIXES)
```

and in `TenantMembershipMiddleware.__call__`, after the deletion-lock block:

```python
            if not request.path.startswith(_ACCEPTANCE_EXEMPT_PREFIXES):
                from apps.privacy.acceptance import acceptance_lock_target

                target = acceptance_lock_target(membership)
                if target is not None:
                    return redirect(target)
```

(The import is local because `apps.privacy` imports `apps.tenancy.models`; a module-level import here would be circular.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy tests/tenancy tests/audit/test_deletion_views.py -q`
Expected: PASS. Existing student-view tests must not start redirecting: they publish no legal documents, and `needs_acceptance` asks for nothing when none is published.

- [ ] **Step 5: Commit**

```bash
git add apps/privacy apps/tenancy/middleware.py tests/privacy
git commit -m "feat(privacy): a material change sends students to re-accept before anything else"
```

---

### Task 5: Privacy requests and the processing stop

**Files:**
- Modify: `apps/privacy/models.py` (append `PrivacyRequest`), `apps/privacy/views.py`, `apps/privacy/urls.py`, `apps/tenancy/middleware.py`, `apps/portals/ext_api.py:139-140`, `apps/portals/reminders.py:242-249`, `apps/audit/redaction.py`
- Create: `apps/privacy/requests.py`, `apps/privacy/migrations/0005_privacyrequest.py` (generated), `apps/privacy/migrations/0006_privacyrequest_guards.py`, `apps/privacy/management/commands/record_privacy_request.py`, `apps/privacy/management/commands/list_privacy_requests.py`, `apps/privacy/templates/privacy/stopped.html`
- Test: `tests/privacy/test_requests.py`

**Interfaces:**
- Consumes: `Membership`, `TenantScopedModel`, `record_event` (`apps/documents/audit.py:10`, `record_event(*, actor: Membership | None, event: str, object_id: UUID)`).
- Produces:
  - `PrivacyRequest` fields: `tenant`, `id`, `student: FK Membership (PROTECT)`, `kind` (`access`, `correction`, `deletion`, `objection`, `withdrawal`), `channel` (`email`, `paper_with_id`, `e_signature`), `received_at`, `due_at`, `handled_at: datetime | None`, `outcome` (`""`, `done`, `declined`).
  - `requests.working_days_after(start: datetime, days: int) -> datetime`.
  - `requests.record(student: Membership, *, kind: str, channel: str, received_at: datetime) -> PrivacyRequest`.
  - `requests.processing_stopped(student: Membership) -> bool` — an objection or withdrawal not `declined` stops processing.
  - `requests.privacy_stop_target(membership: Membership) -> str | None` — `reverse("privacy-stopped")` or None.

- [ ] **Step 1: Write the failing tests**

`tests/privacy/test_requests.py`:

```python
from datetime import datetime, timezone

import pytest
from django.urls import reverse

from apps.privacy import requests
from apps.tenancy.context import tenant_scope


def test_seven_working_days_skip_weekends():
    friday = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    assert requests.working_days_after(friday, 7) == datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
    assert requests.working_days_after(saturday, 1) == datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


@pytest.mark.django_db
def test_recording_an_objection_stops_processing_and_sets_the_due_date(membership_a):
    received = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    with tenant_scope(membership_a.tenant_id):
        assert not requests.processing_stopped(membership_a)
        row = requests.record(membership_a, kind="objection", channel="email", received_at=received)
        assert row.due_at == datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
        assert requests.processing_stopped(membership_a)
        row.outcome = "declined"
        row.save()
        assert not requests.processing_stopped(membership_a)


@pytest.mark.django_db
def test_an_access_request_does_not_stop_processing(membership_a):
    with tenant_scope(membership_a.tenant_id):
        requests.record(membership_a, kind="access", channel="paper_with_id",
                        received_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
        assert not requests.processing_stopped(membership_a)


@pytest.mark.django_db
def test_unknown_kind_or_channel_is_refused(membership_a):
    with tenant_scope(membership_a.tenant_id), pytest.raises(ValueError):
        requests.record(membership_a, kind="complaint", channel="email",
                        received_at=datetime(2026, 10, 2, tzinfo=timezone.utc))


@pytest.mark.django_db
def test_a_stopped_student_sees_the_notice_page(client, user_a, domain_a, membership_a):
    with tenant_scope(membership_a.tenant_id):
        requests.record(membership_a, kind="withdrawal", channel="email",
                        received_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
    client.force_login(user_a)
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302 and response["Location"] == reverse("privacy-stopped")
    assert client.get(reverse("privacy-stopped"), HTTP_HOST=domain_a.host).status_code == 200


@pytest.mark.django_db
def test_the_extension_api_refuses_a_stopped_student(membership_a):
    """Mirror tests/portals' existing deletion-lock test for `_device_endpoint`
    (find it with `grep -rn account_locked tests/portals`); same setup, but record a
    withdrawal instead of opening a DeletionRequest, and expect
    `{"error": "processing_stopped"}` with status 403."""
```

The last test's body: copy the setup of the existing `account_locked` test in `tests/portals` (it pairs a device for `membership_a` and calls a device endpoint), replace the DeletionRequest with `requests.record(..., kind="withdrawal", ...)`, and assert `response.status_code == 403 and response.json() == {"error": "processing_stopped"}`.

Also add one test in the same style as the existing reminder-sweep tests (`grep -rn send_due_reminders tests/portals`): a student with an open objection gets no reminder.

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy/test_requests.py -q`
Expected: FAIL — `ImportError: cannot import name 'requests'`.

- [ ] **Step 3: Implement**

Append to `apps/privacy/models.py`:

```python
class PrivacyRequest(TenantScopedModel):
    """A student's request about their data, from whatever channel it came (spec §6).

    No free text is stored: the request itself stays in the privacy@ mailbox or
    on paper; this row is the deadline and the processing stop.
    """

    class Kind(models.TextChoices):
        ACCESS = "access", "Access"
        CORRECTION = "correction", "Correction"
        DELETION = "deletion", "Deletion"
        OBJECTION = "objection", "Objection"
        WITHDRAWAL = "withdrawal", "Withdrawal of consent"

    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        PAPER_WITH_ID = "paper_with_id", "Paper with ID"
        E_SIGNATURE = "e_signature", "Enhanced e-signature"

    class Outcome(models.TextChoices):
        OPEN = "", "Open"
        DONE = "done", "Done"
        DECLINED = "declined", "Declined"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="privacy_requests")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    received_at = models.DateTimeField()
    due_at = models.DateTimeField()
    handled_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="privacy_request_tenant_id_uniq"),
        ]
        indexes = [models.Index(fields=("tenant", "student", "kind"), name="privacy_request_student_idx")]
```

`apps/privacy/requests.py`:

```python
"""Privacy requests: their deadline, and the processing stop an objection or withdrawal causes.

Azerbaijan's Law on Personal Data Art. 7.2: processing stops immediately on an
objection; Art. 12.4: reply within 7 working days (memo §2). Weekends are skipped;
public holidays are not modelled (# ponytail: add a holiday calendar if a deadline
is ever missed because of one).
"""

from datetime import datetime, timedelta

from django.urls import reverse

from apps.documents.audit import record_event
from apps.privacy.models import PrivacyRequest
from apps.tenancy.models import Membership

STOPPING_KINDS = (PrivacyRequest.Kind.OBJECTION, PrivacyRequest.Kind.WITHDRAWAL)
DUE_WORKING_DAYS = 7


def working_days_after(start: datetime, days: int) -> datetime:
    moment = start
    while days > 0:
        moment += timedelta(days=1)
        if moment.weekday() < 5:
            days -= 1
    return moment


def record(student: Membership, *, kind: str, channel: str, received_at: datetime) -> PrivacyRequest:
    if kind not in PrivacyRequest.Kind.values:
        raise ValueError(f"unknown privacy request kind {kind!r}")
    if channel not in PrivacyRequest.Channel.values:
        raise ValueError(f"unknown privacy request channel {channel!r}")
    row = PrivacyRequest.objects.create(
        student=student, kind=kind, channel=channel, received_at=received_at,
        due_at=working_days_after(received_at, DUE_WORKING_DAYS),
    )
    record_event(actor=None, event=f"privacy.request.{kind}", object_id=row.id)
    return row


def processing_stopped(student: Membership) -> bool:
    if student.role != Membership.Role.STUDENT:
        return False
    return (
        PrivacyRequest.objects.filter(student=student, kind__in=STOPPING_KINDS)
        .exclude(outcome=PrivacyRequest.Outcome.DECLINED)
        .exists()
    )


def privacy_stop_target(membership: Membership) -> str | None:
    return reverse("privacy-stopped") if processing_stopped(membership) else None
```

Check `record_event`'s behaviour with `actor=None` before relying on it (`apps/documents/audit.py:10`); if it requires an actor, call `AuditEvent.objects.create(actor=None, event=..., object_id=...)` directly the way `apps/audit/console.py:58` does.

Views/URL: append to `apps/privacy/views.py`:

```python
@login_required
def stopped(request: HttpRequest) -> HttpResponse:
    return render(request, "privacy/stopped.html")
```

`urls.py`: `path("privacy/stopped/", views.stopped, name="privacy-stopped"),`. Template `stopped.html`: a plain page saying "You asked us to stop processing your data, so your account is paused. To resume, or for anything else, e-mail privacy@ (the address in the Privacy Notice)." with a link to the Privacy Notice.

Middleware (`apps/tenancy/middleware.py`): add `"/privacy/stopped/"` to `_ACCEPTANCE_EXEMPT_PREFIXES`, and before the acceptance-lock block:

```python
            if not request.path.startswith(_ACCEPTANCE_EXEMPT_PREFIXES):
                from apps.privacy.requests import privacy_stop_target

                target = privacy_stop_target(membership)
                if target is not None:
                    return redirect(target)
```

`apps/portals/ext_api.py`, right after the `deletion_lock_target` check:

```python
        from apps.privacy.requests import processing_stopped

        if processing_stopped(pairing.membership):
            return JsonResponse({"error": "processing_stopped"}, status=403)
```

`apps/portals/reminders.py`, in the `Application.objects.filter(...)` of the sweep, exclude students with an open stopping request:

```python
                ).exclude(
                    student__privacy_requests__kind__in=("objection", "withdrawal"),
                    student__privacy_requests__outcome__in=("", "done"),
                ).values_list("id", flat=True)
```

Migrations: `makemigrations privacy` (0005), then `0006_privacyrequest_guards.py` copying Task 2's guard migration with `TABLES = ("privacy_privacyrequest",)`, constraint `privacy_request_student_tenant_fk`, dependencies `[("privacy", "0005_privacyrequest"), ("tenancy", "0002_rls")]`.

`apps/audit/redaction.py` `KEEP`:

```python
    "privacy.PrivacyRequest": ("kind", "channel", "received_at", "due_at", "handled_at", "outcome"),
```

Commands. `record_privacy_request.py` (run by whoever reads privacy@):

```python
"""Log a privacy request: manage.py record_privacy_request --host <tenant host> --email <student> --kind objection --channel email [--received 2026-10-03T10:00:00+04:00]"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.privacy import requests
from apps.privacy.models import PrivacyRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Membership, TenantDomain


class Command(BaseCommand):
    help = "Record a privacy request received by e-mail, paper with ID or e-signature."

    def add_arguments(self, parser):
        parser.add_argument("--host", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--kind", required=True, choices=PrivacyRequest.Kind.values)
        parser.add_argument("--channel", required=True, choices=PrivacyRequest.Channel.values)
        parser.add_argument("--received")

    def handle(self, *args, host, email, kind, channel, received=None, **options):
        domain = TenantDomain.objects.filter(host=host, verified_at__isnull=False).first()
        if domain is None:
            raise CommandError(f"no verified tenant host {host!r}")
        moment = parse_datetime(received) if received else timezone.now()
        if moment is None:
            raise CommandError("--received must be an ISO 8601 datetime with a timezone")
        with tenant_scope(domain.agency_id), transaction.atomic():
            set_local_tenant(domain.agency_id)
            student = Membership.objects.filter(
                user__username__iexact=email.strip(), role=Membership.Role.STUDENT
            ).first()
            if student is None:
                raise CommandError("no student with that e-mail in this tenant")
            row = requests.record(student, kind=kind, channel=channel, received_at=moment)
        self.stdout.write(f"recorded {kind}; reply due {row.due_at:%Y-%m-%d %H:%M %Z}")
```

`list_privacy_requests.py`: for each verified tenant (loop `TenantDomain` distinct agency ids, each inside `tenant_scope` + `set_local_tenant` in an atomic block), print open requests (`outcome=""`) ordered by `due_at`, marking overdue ones. Add a test that runs `record_privacy_request` via `call_command` against `domain_a` and asserts one row exists and stdout contains `reply due`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy tests/portals tests/tenancy tests/audit -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/privacy apps/tenancy/middleware.py apps/portals/ext_api.py apps/portals/reminders.py apps/audit/redaction.py tests/privacy
git commit -m "feat(privacy): log privacy requests with a 7-working-day deadline; an objection pauses processing"
```

---

### Task 6: Document texts, agency agreement template, runbook

**Files:**
- Create/finish: `apps/privacy/legal/terms.{en,az,ru}.md`, `apps/privacy/legal/privacy_notice_direct.{en,az,ru}.md`, `apps/privacy/legal/privacy_notice_agency.{en,az,ru}.md`, `docs/legal/2026-10-03-agency-data-processing-agreement.md`, `docs/runbooks/privacy.md`
- Test: `tests/privacy/test_documents.py` (append)

**Interfaces:**
- Consumes: `documents.shipped_files()` (Task 1).
- Produces: nine document files the deploy publishes.

- [ ] **Step 1: Write the failing test**

Append to `tests/privacy/test_documents.py`:

```python
REQUIRED_NOTICE_TOPICS = ("privacy@", "7 working days", "12 months", "anonymised", "China")


def test_every_kind_ships_in_every_language():
    shipped = {(kind, lang) for kind, lang, _ in documents.shipped_files()}
    assert shipped == {(k, lang) for k in documents.KINDS for lang in documents.LANGUAGES}


def test_english_notices_carry_what_the_law_requires():
    for kind in ("privacy_notice_direct", "privacy_notice_agency"):
        text = (documents.LEGAL_DIR / f"{kind}.en.md").read_text(encoding="utf-8")
        for topic in REQUIRED_NOTICE_TOPICS:
            assert topic in text, (kind, topic)


def test_every_translation_is_marked_as_a_draft_for_the_lawyer():
    for kind, lang, path in documents.shipped_files():
        if lang != "en":
            assert "DRAFT" in path.read_text(encoding="utf-8").splitlines()[0], path.name
```

- [ ] **Step 2: Run to verify it fails**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy/test_documents.py -q`
Expected: FAIL — the `az`/`ru` files do not exist.

- [ ] **Step 3: Write the texts**

`privacy_notice_direct.en.md` carries every item of spec §2 in plain sentences, in this order: who we are and `privacy@` (use the placeholder address `privacy@tehsil.example` and the line "Company name and address: to be completed before launch" — the company is not incorporated yet); what we process (the spec §2 list); why, one purpose per line, including "improving recommendations, aggregate statistics and testing our models on anonymised data only"; sensitive information; who receives it, naming the AI providers by company and country, including the People's Republic of China; transfers abroad and that the student's consent permits them; how long ("personal data for as long as your account is active plus 12 months, then deleted; anonymised data, which cannot identify you, indefinitely"); rights and how to use them ("e-mail privacy@…; we reply within 7 working days"); how changes are announced. `privacy_notice_agency.en.md` is the same, with the agency named as controller ("{{ agency }}") and Tehsil as its processor, and no marketing paragraph. `terms.en.md`: the service, the student's obligations (true information, own documents), that the student pays application fees directly to institutions, no admission or funding guarantee, liability limits, termination and deletion, governing law Azerbaijan.

`az` and `ru` files: faithful translations of the English, each starting with the line `DRAFT — translation for legal review, not yet approved.`.

`docs/legal/2026-10-03-agency-data-processing-agreement.md`: the template from spec §5 — subject and duration, processing only on the agency's documented instructions, the sub-processor list with countries, the anonymisation instruction (spec §4, deferred until outcome capture exists), confidentiality, security measures (RLS tenant isolation, encryption at rest by the host), help with student requests within the 7-working-day deadline, deletion or return at the end of the agreement, audit rights. Mark it "Template — for review by a licensed lawyer".

`docs/runbooks/privacy.md`: publishing (`DATABASE_ROLE=migration uv run python manage.py publish_legal_documents [--minor]` at every deploy, and what `--minor` means); reading `privacy@` daily; logging each request with `record_privacy_request` (including paper and e-signature requests — never refuse a channel); checking `list_privacy_requests` daily; the 7-working-day deadline; that an objection or withdrawal pauses the student's account until it is handled, and that a deletion request goes through the existing erasure flow (`/student/account/deletion/` and `execute_due_erasures`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_consent_privacy uv run pytest tests/privacy -q`
Expected: PASS.

- [ ] **Step 5: Full validation and commit**

Run, in order, and fix anything they report:

```bash
uv run ruff check .
uv run mypy apps config
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=tehsil_consent_privacy uv run pytest -q
```

```bash
git add apps/privacy/legal docs/legal docs/runbooks/privacy.md tests/privacy
git commit -m "docs(privacy): notices and terms in az/en/ru, agency DPA template, privacy runbook"
```
