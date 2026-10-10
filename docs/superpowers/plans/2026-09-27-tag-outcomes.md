# Tag Outcomes (plan 3 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Learn what each portal does with a `+tag` address — keeps it, rejects it at the form, or strips it before mailing — from the extension and from the student's own mail, fall back to the plain address wherever a tag is refused, and never let one tenant's report overturn what every other tenant's students are handed.

**Architecture:** `PortalAccount` gains what *its own* registration measured (`tag_outcome`, `registered_at`); `PortalForm.tag_status` stays the shared default, moved by a report only out of `UNKNOWN` and otherwise only by a human (`manage.py set_tag_status`). The extension reads back the tagged address after typing it, swaps in the plain one (carried in the packet) when the form refuses it, and reports what it saw to one new device route. The first report that the page held the tagged address is the registration: it opens a 30-minute window during which the mailbox sync measures KEEPS (mail to the tag) or STRIPS (untagged mail from that portal's own domain); if the mailbox has not answered after 5 minutes, a `chrome.alarms` alarm makes the dock ask the student, whose answer can name the sender, learned per student as confirmed. The learned-FieldMap snapshot learns `contact.email` as an optional field.

**Tech Stack:** Django 5.2, PostgreSQL 17 with row-level security, pytest + pytest-django, TypeScript 5 + esbuild (Manifest V3), Playwright (sync API) for the extension tests, uv, npm.

**Spec:** `docs/superpowers/specs/2026-09-25-application-watch-design.md` — §2a (tag outcomes per portal), §2, §3 rule 2 (learned senders), §4 (quiet hours), "Data it needs", "Cases the design must handle", "Checks before trusting the design". Plans 1 and 2: `docs/superpowers/plans/2026-09-25-application-watch-core.md`, `docs/superpowers/plans/2026-09-26-mail-recognition.md`; rulings: `.superpowers/sdd/2026-09-26-mail-recognition/progress.md`.

**Design decisions this plan takes (read before Task 1):**

1. **How the server learns a registration happened.** The extension reports `POST /ext/applications/<id>/address {"event": "given"}` when a fill run *typed* the portal address into the `contact.email` control (not when the page already held it — a pre-filled address means the account exists) and the page did not refuse it. The first such report per `PortalAccount` sets `registered_at`, writes a `SIGNUP` `ApplicationStep`, and — when the address carries our tag — opens the registration-mail window. `glass-box §13`'s `signup_map` is not built, so the registration form is whatever mapped form holds `contact.email`; a student who registered by hand before the extension ever filled that portal opens the window late, the dock asks, they answer "No email came", nothing is recorded — the safe default.
2. **How "untagged from that portal" is matched before the sender is known.** Only by the domains the portal's own rows name: the registrable key of `portal_host` and of each curated `PortalForm.sender_domains` entry on that host (`sync._awaiting_registration`), and only for a message received after `registered_at` and inside `REGISTRATION_MAIL_WINDOW`. Those domains are already read under rule 2, so the sync learns nothing new from such a message — it only measures STRIPS. A vendor domain nobody recorded (DreamApply's `mail-eu.dreamapply.com` for `tum.dreamapply.com`) matches nothing, so the dock asks. A shared platform on which the portal happens to sit (a DreamApply subdomain, say) is never resolved by a per-student answer either: it is read only through a human-curated `PortalForm.sender_domains` row on that form, the same route this decision already names (ruling F7) — `learn_answered_sender`'s own guards refuse to write such a domain as a per-student `LearnedSender`.
3. **Learned senders from the registration are read, not yet trusted.** §3 rule 2 keeps a learned domain read-only "until the student confirms one message from it belongs to that institution" — and a typed answer is not that confirmation: it is stronger evidence than a leaked tag, but still text the student typed, and a look-alike address copied by mistake would otherwise open every subdomain of a domain nobody vetted. So `learn_answered_sender` writes the row **unconfirmed**, exactly like a sender first learned from a tag (`sync.py`); the existing confirm button (`mailbox/views.py`) remains the only way to change that (ruling F8). Same guards as learning from a tag: never free mail, never the student's own domains, and never a shared platform's own host (decision 2, ruling F7). The answer's measurement (`tagged` → KEEPS, `plain` → STRIPS) is recorded for **this account only** and never moves the shared status (final review M4): "plain" can as well mean the student retyped the address by hand — the same many-causes reason `page` evidence is account-only — so STRIPS reaches the shared status only from mail.
4. **Who may move the shared status, and which way.** The spec's "sharing cannot be abused" is not true against the code: before this plan `portal_address` re-based every account on a shared `REJECTS`, so one tenant's report would have switched other tenants' already-registered students to an address their portal does not hold and dropped their tag from mail matching. The rule this plan pins: (a) an account's own evidence always governs that account, first observation wins — with two exceptions: the student's own "use my plain address" button switches the account to plain even over its own KEEPS, and mail to the tag corrects the account's own REJECTS back to KEEPS and its tagged address unless that REJECTS came from the button (final review M3; account-only, recorded as `tag_dropped_by_student`); (b) the shared `tag_status` moves only `UNKNOWN → X`, on an account's first measurement, from the browser's native verdict (`form`) or the mail (sync) — never from `page` or `after_submit` evidence (rulings F5 and the Task 6 `page` ruling), the student's registration answer (final review M4), or the "use my plain address" button, which is an error the extension could not read — each of those is this account's evidence only; (c) a set status is moved only by a human (`manage.py set_tag_status`), and a contradicting report is logged `TagStatusDisputed`; (d) a shared `REJECTS` decides only an address's *first* issue and never re-bases one already issued — not only one whose `registered_at` is set: the kit may have handed it out and the student registered by hand, which the server cannot see (final review I1, superseding ruling F1; cost: an issued-but-unused tagged account on a truly rejecting portal still gets the tagged address — the extension swaps it per account on first fill, and a kit user sees the portal's own error). So one tenant's single report **cannot** flip KEEPS to REJECTS for anyone; it **can** measure an unmeasured portal for everyone, and the worst a false first report does is hand *new* registrations the plain address, the pre-tag behaviour. KEEPS and STRIPS change nothing any student is handed; only REJECTS does. Every shared move writes an `AuditEvent` (`portal.tag_status_set`) in the reporter's tenant.
5. **The registration expectation lives on `PortalAccount`, not in `watch.Expectation`.** `Expectation` is per application and "met" is derived from the application's state; a registration is per portal account (one account, many applications), is met by mail, and raises no watchdog alert — the dock asks while the student is at the screen. Its two timings are platform defaults in `apps/watch/rules.py` beside `CONFIRMATION_WINDOW`. No new table, so no new RLS policy.
6. **Quiet hours do not apply to the registration question.** It is a dock prompt shown while the student is operating the portal, not a notification; §4's quiet-hours rule governs watchdog alerts and escalations, which this plan does not add.

**Parked items this plan closes** (from `progress.md`): Task 3 minor "REJECTS after issue re-bases the address on the CURRENT application_email … and applies host-wide" (Task 1: the fallback is the *issued* address without our tag, registered accounts are never re-based, and a report moves every form on the host); Task 3 minor "no CheckConstraint on PortalForm.tag_status" (Task 1); Task 8 minor "mailbox_check answers 429 for ANY SyncRefused cause" (Task 3: a lost grant answers 409 `mailbox_disconnected`).

**Not in this plan, on purpose:**
- The one-time delivery test (§6): it needs an outbound sending domain; `REMINDER_EMAIL_FROM` is empty and the domain is an open owner decision.
- The application-inbox onboarding step (§6): there is no dashboard.
- Gmail: not offered in the pilot.
- Owner decisions: one inbox per provider; reading untagged Junk in an application inbox (progress.md Task 6 owner question).
- A trigger for the fill run. Nothing in `extension/src` injects the content script or sends it `{"type": "start"}` (only `content/index.ts:176` listens for it), so `run()` — and everything this plan adds to it — is reached today only through the e2e suite's `__tehsil_run` hook. The trigger belongs to the dashboard that does not exist (glass-box PR #126).
- `PortalForm.signup_map` (glass-box decision 13): unbuilt; see decision 1.
- Promoting a disputed status automatically, or requiring agreement between tenants: a human uses `set_tag_status`.

## Global Constraints

- Work in `/home/orkhan/Desktop/mailbox-port`, branch `claude/mailbox-port`. Always `git -C /home/orkhan/Desktop/mailbox-port …`; the shell's cwd resets to the main repo and a bare `git commit` lands on the wrong branch.
- Start from the branch tip *after* the controller's in-flight fix to `apps/mailbox/oauth.py` / `sync.py` lands. Every edit to `sync.py` in this plan is anchored on quoted code, not on line numbers; if an anchor moved, apply the same change at the anchor's new place.
- Test DB: prefix every pytest/manage.py command with `POSTGRES_DB=tehsil_mailbox_port`.
- Lint `uv run ruff check .` only — **never `ruff format`**. Types `uv run mypy apps config`. Security `uv run bandit -q -c pyproject.toml -r apps config`. Migrations `POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations --check --dry-run`. Line length 100.
- Extension: `npm --prefix extension ci` once, then `npm --prefix extension run check` (typecheck + build) after every TypeScript change. Extension tests: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_bundle.py -q` and `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_e2e.py -m extension -q` (the `extension` marker is excluded by `pyproject.toml`'s `addopts`; without `-m extension` those tests silently do not run).
- **The extension types, the student clicks.** No bundle may contain `.click(`, `MouseEvent`, `PointerEvent`, `requestSubmit` or `.submit(`; `content.js` may not contain the substrings `press`, `doubleClick`, `dragAndDrop`, `scrollTo` — **including inside user-facing strings** (`test_extension_bundle.py` scans the built text). A `FocusEvent` is allowed.
- `apps/portals/` modules other than `ext_api.py` and `models.py` must not contain the string `SUBMITTED`; no `apps/portals/*.py` may contain `fingerprint`, `residential` or the other words in `tests/portals/test_boundary.py::BANNED`.
- Every new device route uses `ext_api._device_endpoint` (device token + `deletion_lock_target`), calls `_limit(...)` first, resolves the application with `_application_for`, and wraps every tenant read/write in `tenant_transaction`.
- Every field added to a model FK-reachable from `Membership` is classified in `apps/audit/redaction.py`.
- Logs carry ids, portal hosts, statuses and sender domains only — never an address, a tag, or anything the student typed.
- A learned sender is per student, never written to the shared `PortalForm.sender_domains`.
- Every test that could reach the content tier stubs `classify_message` (no paid model calls).
- Commits end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

## Review Focus

1. **Another tenant reports REJECTS on a portal already measured KEEPS.** Expected: the shared status stays KEEPS, `TagStatusDisputed` is logged, and the reporter's own account falls back to its plain address. Pinned in Task 1 (`test_one_tenant_cannot_overturn_a_set_status`).
2. **A shared REJECTS arrives after this student already registered with the tag.** Expected: they keep being handed the tagged address their portal holds. Pinned in Task 1 (`test_a_shared_rejects_never_rebases_a_registered_account`).
3. **An email control that refuses the plain address too** (a pattern unrelated to `+`). Expected: the tagged value is put back and nothing is reported — a report would mark the portal REJECTS for everyone. Pinned in Task 6 (`test_an_error_the_plain_address_also_gets_is_not_blamed_on_the_tag`).
4. **A first sync that reads back portal mail from before the registration.** Expected: no STRIPS. Pinned in Task 4 (`test_untagged_mail_from_before_the_registration_says_nothing`).
5. **The student names a free-mail sender** (a portal that mails from `gmail.com`). Expected: STRIPS is still measured, the sender is not learned, the dock says to watch that inbox themselves. Pinned in Task 3 (`test_a_free_mail_sender_is_never_learned`).

---

### Task 1: What an account measured, and who may move the shared status

**Files:**
- Modify: `apps/portals/models.py` (`PortalForm.Meta`, `PortalAccount`)
- Create: `apps/portals/migrations/0020_tag_outcomes.py`
- Modify: `apps/portals/tags.py` (whole file below)
- Create: `apps/portals/management/commands/set_tag_status.py`
- Modify: `apps/audit/redaction.py`
- Test: `tests/portals/test_tag_outcomes.py`

**Interfaces:**
- Consumes: `PortalForm.TagStatus` (`UNKNOWN`, `KEEPS`, `REJECTS`, `STRIPS`), `PortalAccount` (`student`, `portal_host`, `tag`, `address`), `apps.funding.models.AuditEvent`.
- Produces: `PortalAccount.registered_at: datetime | None`, `PortalAccount.tag_outcome: str` (default `"UNKNOWN"`); `tags.plain_of(account: PortalAccount) -> str`; `tags.account_for(application: Application) -> PortalAccount | None`; `tags.portal_address(application) -> str` (unchanged signature); `tags.record_tag_outcome(account: PortalAccount, outcome: str, *, shared: bool, actor: Membership | None) -> bool` (run inside the account's tenant transaction; True only on the account's first measurement); `manage.py set_tag_status <portal_host> <STATUS>`.

- [ ] **Step 1: Write the failing tests**

Create `tests/portals/test_tag_outcomes.py`:

```python
"""What one account measured about the tag, and who may move the shared status.

The rule (plan 3): a report moves PortalForm.tag_status only out of UNKNOWN;
a set status is moved by a human. An account's own evidence always governs
that account.
"""

from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db

HOST = "apply.example.edu"


def _account(agency, student, *, address="leyla.apply+ab12cd@outlook.com", host=HOST):
    from apps.portals.models import PortalAccount

    return PortalAccount.objects.create(
        tenant=agency, student=student, portal_host=host, tag="ab12cd", address=address
    )


def _form(host=HOST, **kwargs):
    from apps.portals.models import PortalForm

    return PortalForm.objects.create(portal_host=host, form_key=f"f-{uuid4()}", **kwargs)


def _status(host=HOST):
    from apps.portals.models import PortalForm

    return set(PortalForm.objects.filter(portal_host=host).values_list("tag_status", flat=True))


def test_plain_of_removes_only_our_own_tag(agency_a, membership_a):
    from apps.portals.models import PortalAccount
    from apps.portals.tags import plain_of

    ours = PortalAccount(tag="ab12cd", address="leyla.apply+ab12cd@outlook.com")
    theirs = PortalAccount(tag="ab12cd", address="leyla+work@outlook.com")

    assert plain_of(ours) == "leyla.apply@outlook.com"
    assert plain_of(theirs) == ""


def test_a_first_report_measures_every_form_on_the_host(agency_a, membership_a):
    from apps.funding.models import AuditEvent
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form(), _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        assert record_tag_outcome(
            account, PortalForm.TagStatus.KEEPS, shared=True, actor=membership_a
        )
        event = AuditEvent.objects.get(event="portal.tag_status_set")

    assert _status() == {"KEEPS"}
    assert event.object_id == account.id and event.actor_id == membership_a.id


def test_one_tenant_cannot_overturn_a_set_status(
    agency_a, membership_a, agency_b, membership_b, caplog
):
    """The cross-tenant rule: KEEPS stays KEEPS whatever another tenant reports,
    and the report is logged for a human instead."""
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form(tag_status=PortalForm.TagStatus.KEEPS)
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        account = _account(agency_b, membership_b)
        moved = record_tag_outcome(
            account, PortalForm.TagStatus.REJECTS, shared=True, actor=membership_b
        )
        account.refresh_from_db()

    assert moved is True  # the reporter's own account still takes its own evidence
    assert account.tag_outcome == "REJECTS"
    assert account.address == "leyla.apply@outlook.com"
    assert _status() == {"KEEPS"}
    assert "TagStatusDisputed" in caplog.text


def test_evidence_that_is_not_shared_moves_only_the_account(agency_a, membership_a):
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        record_tag_outcome(account, PortalForm.TagStatus.REJECTS, shared=False, actor=membership_a)

    assert _status() == {"UNKNOWN"}


def test_an_account_measures_once(agency_a, membership_a):
    """The account's first observation wins, so one account can move the
    shared row at most once."""
    from apps.portals.models import PortalForm
    from apps.portals.tags import record_tag_outcome

    _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = _account(agency_a, membership_a)
        record_tag_outcome(account, PortalForm.TagStatus.KEEPS, shared=True, actor=None)
        second = record_tag_outcome(
            account, PortalForm.TagStatus.STRIPS, shared=True, actor=None
        )
        account.refresh_from_db()

    assert second is False
    assert account.tag_outcome == "KEEPS"


def test_a_shared_rejects_never_rebases_a_registered_account(agency_a, membership_a):
    """Another tenant's REJECTS arrives after this student registered with the
    tag: the portal holds the tagged address, so the student keeps being handed it."""
    from apps.portals.models import Application, PortalForm
    from apps.portals.tags import portal_address

    form = _form(tag_status=PortalForm.TagStatus.REJECTS)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        account = _account(agency_a, membership_a)
        account.registered_at = timezone.now()
        account.save(update_fields=["registered_at"])
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        assert portal_address(application) == "leyla.apply+ab12cd@outlook.com"


def test_a_rejected_tag_falls_back_to_the_issued_address_not_a_new_one(agency_a, membership_a):
    """The student changed application_email after the tag was issued. The
    portal holds the old mailbox, so the fallback is the old plain address."""
    from apps.portals.models import Application, PortalForm
    from apps.portals.tags import portal_address, record_tag_outcome

    form = _form()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "leyla.new@outlook.com"
        membership_a.save(update_fields=["application_email"])
        account = _account(agency_a, membership_a)
        record_tag_outcome(account, PortalForm.TagStatus.REJECTS, shared=False, actor=membership_a)
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        assert portal_address(application) == "leyla.apply@outlook.com"


def test_a_human_moves_a_set_status():
    from apps.portals.models import PortalForm

    _form(tag_status=PortalForm.TagStatus.KEEPS)
    call_command("set_tag_status", HOST, "REJECTS")

    assert _status() == {"REJECTS"}


def test_an_unknown_status_is_refused_by_the_database():
    from django.db import IntegrityError, transaction

    from apps.portals.models import PortalForm

    form = _form()
    with pytest.raises(IntegrityError), transaction.atomic():
        PortalForm.objects.filter(pk=form.pk).update(tag_status="MAYBE")
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_tag_outcomes.py -q`
Expected: FAIL — `ImportError: cannot import name 'plain_of'` / `TypeError: PortalAccount() got unexpected keyword arguments` for `registered_at`, and `Unknown command: 'set_tag_status'`.

- [ ] **Step 3: Models and migration**

In `apps/portals/models.py`, inside `PortalForm.Meta.constraints`, right after the `portal_form_host_key_uniq` `UniqueConstraint`, add:

```python
            #: A client report reaches this column now (plan 3); an unknown value
            #: must be refused by the database, not only by the view.
            models.CheckConstraint(
                condition=models.Q(tag_status__in=("UNKNOWN", "KEEPS", "REJECTS", "STRIPS")),
                name="portal_form_tag_status_valid",
            ),
```

In `PortalAccount`, replace

```python
    address = models.CharField(max_length=320, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="portalaccount_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("student", "portal_host"), name="portalaccount_one_per_host"
            ),
        ]
```

with

```python
    address = models.CharField(max_length=320, blank=True)
    #: When the extension first typed this address into the portal and the page
    #: held it (spec §2a) -- the registration, as near as the platform can see
    #: it. Opens the registration-mail window, and from then on `address` is
    #: what the portal holds, so a later shared status never re-bases it.
    registered_at = models.DateTimeField(null=True, blank=True)
    #: What THIS account measured about the tag, whatever the shared status
    #: says. The first observation wins; REJECTS also drops the tag from
    #: `address` (tags.record_tag_outcome).
    tag_outcome = models.CharField(
        max_length=10, choices=PortalForm.TagStatus.choices, default=PortalForm.TagStatus.UNKNOWN
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="portalaccount_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("student", "portal_host"), name="portalaccount_one_per_host"
            ),
            models.CheckConstraint(
                condition=models.Q(tag_outcome__in=("UNKNOWN", "KEEPS", "REJECTS", "STRIPS")),
                name="portalaccount_tag_outcome_valid",
            ),
        ]
```

Run `POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations portals --name tag_outcomes`. If it adds a `('tenancy', …)` dependency, delete it (the same spurious edge `0019_portal_accounts.py` documents). The file must read:

```python
# Generated by Django 5.2.17 on 2026-09-27

from django.db import migrations, models


class Migration(migrations.Migration):

    # Only portals: makemigrations adds a spurious tenancy edge when run
    # against an unmigrated database (see 0019_portal_accounts.py). Nothing
    # here touches a tenancy table.
    dependencies = [
        ('portals', '0019_portal_accounts'),
    ]

    operations = [
        migrations.AddField(
            model_name='portalaccount',
            name='registered_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='portalaccount',
            name='tag_outcome',
            field=models.CharField(choices=[('UNKNOWN', 'Not yet measured'), ('KEEPS', 'Keeps the tag'), ('REJECTS', 'Rejects + at the form'), ('STRIPS', 'Accepts but mails the plain address')], default='UNKNOWN', max_length=10),
        ),
        migrations.AddConstraint(
            model_name='portalaccount',
            constraint=models.CheckConstraint(condition=models.Q(('tag_outcome__in', ('UNKNOWN', 'KEEPS', 'REJECTS', 'STRIPS'))), name='portalaccount_tag_outcome_valid'),
        ),
        migrations.AddConstraint(
            model_name='portalform',
            constraint=models.CheckConstraint(condition=models.Q(('tag_status__in', ('UNKNOWN', 'KEEPS', 'REJECTS', 'STRIPS'))), name='portal_form_tag_status_valid'),
        ),
    ]
```

No new table, so no RLS or composite-FK SQL: `portals_portalaccount` already has both (0019).

- [ ] **Step 4: `tags.py`**

Replace `apps/portals/tags.py` with:

```python
"""One tagged address per student per portal host (spec §2, §2a).

`name+tag@domain` reaches the same inbox, and only the portal it was given to
knows it, so mail sent to it names the portal and is strong evidence it came
from there.

Two records of what a portal does with the tag, and the difference is the
security model (plan 3, design decision 4):

- `PortalAccount.tag_outcome` is what ONE student's account measured. The
  student's own evidence always governs their own account.
- `PortalForm.tag_status` is shared by every tenant and is only a default for
  accounts not yet registered. A report moves it only out of UNKNOWN; a set
  status is moved by a human (`manage.py set_tag_status`), never by a report.
  One tenant can therefore measure an unmeasured portal for everyone, but can
  never overturn a measurement, and the worst a false first report does is hand
  new registrations the plain address -- the behaviour before tags existed.
"""

from __future__ import annotations

import logging
import secrets
import string

from apps.funding.models import AuditEvent
from apps.tenancy.models import Membership

from .models import Application, PortalAccount, PortalForm

logger = logging.getLogger(__name__)

_TAG_ALPHABET = string.ascii_lowercase + string.digits
_TAG_LENGTH = 6
_UNKNOWN = PortalForm.TagStatus.UNKNOWN
_REJECTS = PortalForm.TagStatus.REJECTS


def _new_tag() -> str:
    return "".join(secrets.choice(_TAG_ALPHABET) for _ in range(_TAG_LENGTH))


def tagged(address: str, tag: str) -> str:
    """`local+tag@domain`, or the address unchanged when it cannot take a tag."""
    local, at, domain = address.rpartition("@")
    if not at or not local or not domain or "+" in local:
        return address
    return f"{local}+{tag}@{domain}"


def plain_of(account: PortalAccount) -> str:
    """The account's address with OUR tag removed, or "" when it carries none.

    By the account's own tag, never by stripping any "+": a student whose own
    address already holds one was never tagged (see `tagged`), and cutting at
    their "+" would name a mailbox that is not theirs.
    """
    local, at, domain = account.address.rpartition("@")
    suffix = f"+{account.tag}"
    if not at or not account.tag or not local.casefold().endswith(suffix.casefold()):
        return ""
    return f"{local[: -len(suffix)]}@{domain}"


def account_for(application: Application) -> PortalAccount | None:
    """This student's account on this application's portal host, if issued."""
    return PortalAccount.objects.filter(
        student=application.student, portal_host=application.portal_form.portal_host
    ).first()


def portal_address(application: Application) -> str:
    """The address this student uses on this application's portal, or "".

    Run inside a tenant transaction: it creates the account on first use.
    The shared REJECTS re-bases only an account not yet registered: once the
    portal holds an address, another tenant's report cannot change what this
    student is handed for it. The account's own REJECTS already rewrote
    `address` (record_tag_outcome), so it needs no branch here.
    """
    base = application.student.application_email
    if not base:
        return ""
    form = application.portal_form
    account, _ = PortalAccount.objects.get_or_create(
        student=application.student,
        portal_host=form.portal_host,
        defaults={"tenant_id": application.tenant_id, "tag": _new_tag()},
    )
    shared_rejects = form.tag_status == _REJECTS
    if not account.address:
        account.address = base if shared_rejects else tagged(base, account.tag)
        account.save(update_fields=["address"])
    elif shared_rejects and account.registered_at is None and account.address != base:
        account.address = base
        account.save(update_fields=["address"])
    return account.address


def record_tag_outcome(
    account: PortalAccount, outcome: str, *, shared: bool, actor: Membership | None
) -> bool:
    """Record what this account measured; True when it was the first measurement.

    Run inside the account's tenant transaction. Conditional updates, so two
    reports racing (the sync and the dock) settle on whichever lands first
    rather than on whichever saves last.

    `shared` says whether this evidence may also move the platform-wide
    status. It moves it only out of UNKNOWN, and only on the account's own
    first measurement, so one account moves the shared row at most once. A
    report contradicting a set status is logged for a human and changes
    nothing shared.
    """
    updates: dict[str, object] = {"tag_outcome": outcome}
    if outcome == _REJECTS and (plain := plain_of(account)):
        updates["address"] = plain
    moved = bool(
        PortalAccount.objects.filter(pk=account.pk, tag_outcome=_UNKNOWN).update(**updates)
    )
    if not moved:
        return False
    for field, value in updates.items():
        setattr(account, field, value)
    if not shared:
        return True
    host = account.portal_host
    if PortalForm.objects.filter(portal_host=host, tag_status=_UNKNOWN).update(tag_status=outcome):
        # Who measured it for everyone. The shared row has no tenant, so the
        # attribution lives with the account whose evidence moved it.
        AuditEvent.objects.create(
            tenant_id=account.tenant_id,
            actor=actor,
            event="portal.tag_status_set",
            object_id=account.id,
        )
        logger.info("TagStatusSet portal=%s status=%s", host, outcome)
    elif PortalForm.objects.filter(portal_host=host).exclude(tag_status=outcome).exists():
        logger.warning("TagStatusDisputed portal=%s reported=%s", host, outcome)
    return True
```

- [ ] **Step 5: The human path and the redaction classification**

Create `apps/portals/management/commands/set_tag_status.py`:

```python
"""The human path for the shared tag status (plan 3, design decision 4).

A report moves a portal's status only out of UNKNOWN. Correcting a set status
-- a portal that changed its form, a disputed report in the logs, one of the
owner's own measurements -- is a person's decision, taken here.
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.portals.models import PortalForm


class Command(BaseCommand):
    help = "Set the tag status of every form on one portal host"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("portal_host")
        parser.add_argument("status", choices=PortalForm.TagStatus.values)

    def handle(self, *_args: object, **options: object) -> None:
        host = str(options["portal_host"]).strip().casefold()
        updated = PortalForm.objects.filter(portal_host=host).update(
            tag_status=str(options["status"])
        )
        if not updated:
            raise CommandError(f"no portal form on {host}")
        self.stdout.write(f"{host}: {updated} form(s) set to {options['status']}")
```

In `apps/audit/redaction.py`, replace `    "portals.PortalAccount": ("portal_host", "created_at"),` with:

```python
    # registered_at is when, tag_outcome a closed enum about the portal's
    # behaviour -- neither says anything about the person once tag and address
    # are gone.
    "portals.PortalAccount": ("portal_host", "created_at", "registered_at", "tag_outcome"),
```

- [ ] **Step 6: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_tag_outcomes.py tests/portals/test_tags.py tests/audit/test_redaction_classification.py -q && POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations --check --dry-run`
Expected: 24 passed; "No changes detected". (`test_tags.py::test_a_portal_that_rejects_tags_gets_the_plain_address` still passes: that account is unregistered.)

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/portals/models.py apps/portals/migrations/0020_tag_outcomes.py apps/portals/tags.py apps/portals/management/commands/set_tag_status.py apps/audit/redaction.py tests/portals/test_tag_outcomes.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(portals): an account's own tag measurement, and a shared status only a human can overturn

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The packet carries the plain address, and the extension reports what the page did

**Files:**
- Modify: `apps/watch/rules.py`
- Modify: `apps/portals/tags.py` (append two functions, one import)
- Modify: `apps/portals/packets.py` (`FillPacket`, `_merged_with_portal_email`, `build_kit`, `mint_packet`)
- Modify: `apps/portals/ext_api.py` (new view `address_report`)
- Modify: `apps/portals/urls.py`
- Test: `tests/portals/test_ext_address.py`

**Interfaces:**
- Consumes: Task 1's `tags.account_for`, `tags.plain_of`, `tags.record_tag_outcome`, `PortalAccount.registered_at`.
- Produces: `watch.rules.REGISTRATION_MAIL_WINDOW = timedelta(minutes=30)`, `watch.rules.REGISTRATION_ASK_AFTER = timedelta(minutes=5)`; `tags.mark_registered(account, now) -> bool`; `tags.awaits_registration_mail(account, now) -> bool`; `FillPacket.plain_email: str` (default `""`); route `POST /ext/applications/<uuid>/address`, body `{"event": "given"}` or `{"event": "rejected", "evidence": "form" | "after_submit" | "student"}`, answer `{"address": str, "awaiting_mail": bool, "ask_after_seconds": int}`, refusals `400 invalid_report`, `409 no_portal_address`, `404 not_found`; `ext_api._REJECTION_EVIDENCE: dict[str, bool]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/portals/test_ext_address.py`:

```python
"""The extension reports what happened to the portal address it typed (spec §2a)."""

import json

import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.portals.test_ext_api import _application, _pair

pytestmark = pytest.mark.django_db

EMAIL_ENTRIES = [
    {
        "profile_field": "contact.email",
        "action": {"selector": "#email", "method": "fill", "arguments": ["%value%"]},
    }
]


@pytest.fixture
def emailed(agency_a, membership_a, monkeypatch):
    """An application whose map asks for contact.email, and a student with an
    application inbox address -- so the packet issues a tagged address."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        return _application(agency_a, membership_a, entries=EMAIL_ENTRIES)


def _packet(client, application, token, host):
    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _report(client, application, token, host, body):
    return client.post(
        f"/ext/applications/{application.id}/address",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _account(agency, student):
    from apps.portals.models import PortalAccount

    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return PortalAccount.objects.get(student=student)


def test_the_packet_carries_the_plain_address_beside_the_tagged_one(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    token = _pair(client, agency_a, membership_a, domain_a)

    packet = _packet(client, emailed, token, domain_a.host)

    [entry] = packet["entries"]
    assert entry["value"].startswith("leyla.apply+")
    assert packet["plain_email"] == "leyla.apply@outlook.com"


def test_the_first_given_report_opens_the_registration_window(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    from apps.portals.models import ApplicationStep

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    first = _report(client, emailed, token, domain_a.host, {"event": "given"})
    registered_at = _account(agency_a, membership_a).registered_at
    second = _report(client, emailed, token, domain_a.host, {"event": "given"})

    assert first.status_code == 200
    assert first.json()["awaiting_mail"] is True
    assert first.json()["ask_after_seconds"] == 300
    assert second.json()["awaiting_mail"] is False
    assert _account(agency_a, membership_a).registered_at == registered_at
    with tenant_scope(agency_a.id):
        assert ApplicationStep.objects.filter(application=emailed, kind="SIGNUP").count() == 1


def test_a_rejection_seen_on_the_form_hands_out_the_plain_address_everywhere(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    from apps.portals.models import PortalForm

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    response = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "form"}
    )
    packet = _packet(client, emailed, token, domain_a.host)

    assert response.json()["address"] == "leyla.apply@outlook.com"
    assert packet["entries"][0]["value"] == "leyla.apply@outlook.com"
    assert packet["plain_email"] == ""
    assert PortalForm.objects.get(pk=emailed.portal_form_id).tag_status == "REJECTS"


def test_the_student_s_button_moves_their_account_and_nothing_shared(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    from apps.portals.models import PortalForm

    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    response = _report(
        client, emailed, token, domain_a.host, {"event": "rejected", "evidence": "student"}
    )

    assert response.json()["address"] == "leyla.apply@outlook.com"
    assert PortalForm.objects.get(pk=emailed.portal_form_id).tag_status == "UNKNOWN"


@pytest.mark.parametrize(
    "body",
    [{}, {"event": "rejected"}, {"event": "rejected", "evidence": "rumour"}, {"event": "kept"}],
)
def test_a_report_the_server_does_not_know_is_refused(
    client, agency_a, domain_a, membership_a, user_a, emailed, body
):
    token = _pair(client, agency_a, membership_a, domain_a)
    _packet(client, emailed, token, domain_a.host)

    response = _report(client, emailed, token, domain_a.host, body)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_report"}


def test_no_address_issued_yet_is_a_conflict(
    client, agency_a, domain_a, membership_a, user_a, emailed
):
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _report(client, emailed, token, domain_a.host, {"event": "given"})

    assert response.status_code == 409


def test_another_student_s_application_is_404(
    client, agency_a, domain_a, membership_a, user_a, emailed, agency_b, membership_b, domain_b
):
    token = _pair(client, agency_b, membership_b, domain_b)

    response = _report(client, emailed, token, domain_b.host, {"event": "given"})

    assert response.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_ext_address.py -q`
Expected: FAIL — `KeyError: 'plain_email'` and 404 on every `/address` POST.

- [ ] **Step 3: Timings and the two registration helpers**

In `apps/watch/rules.py`, directly above `#: Inside this distance of the deadline the ladder tightens.`, add:

```python
#: Registering on a portal almost always triggers a verification email within
#: minutes (spec §2a). Mail from that portal inside this window says whether it
#: keeps the tag; after it, nothing more is inferred.
REGISTRATION_MAIL_WINDOW = timedelta(minutes=30)

#: When the dock asks the student about that email if the mailbox has not
#: answered yet -- short, because the point is to ask while they are still at
#: the portal's screen.
REGISTRATION_ASK_AFTER = timedelta(minutes=5)

```

In `apps/portals/tags.py`, add `from datetime import datetime` after `import string`, add `from apps.watch.rules import REGISTRATION_MAIL_WINDOW` after `from apps.tenancy.models import Membership`, and append:

```python


def mark_registered(account: PortalAccount, now: datetime) -> bool:
    """Record that the portal now holds this address; True only the first time.

    Run inside the account's tenant transaction. The extension reports every
    fill that typed the address; only the first opens the registration window,
    so a second application on the same portal account reopens nothing.
    """
    opened = bool(
        PortalAccount.objects.filter(pk=account.pk, registered_at__isnull=True).update(
            registered_at=now
        )
    )
    if opened:
        account.registered_at = now
    return opened


def awaits_registration_mail(account: PortalAccount, now: datetime) -> bool:
    """Is the portal's first email, which would say whether it keeps the tag, still due?"""
    return (
        account.registered_at is not None
        and now - account.registered_at < REGISTRATION_MAIL_WINDOW
        and account.tag_outcome == _UNKNOWN
        and bool(plain_of(account))
    )
```

(`apps/watch/rules.py` imports only `datetime`, so `apps.portals` importing it creates no cycle.)

- [ ] **Step 4: The packet's plain address**

In `apps/portals/packets.py`:

Change `from .tags import portal_address` to `from .tags import account_for, plain_of, portal_address`.

At the end of `class FillPacket`, after `confirmation_markers: tuple[str, ...] | None = None`, add:

```python
    #: The contact.email value without our tag, "" when it carries none. The
    #: extension types it instead when the portal refuses the tagged address
    #: (spec §2a) -- the student's own address, in the student's own browser.
    plain_email: str = ""
```

Replace `_merged_with_portal_email` with:

```python
def _merged_with_portal_email(
    application: Application, values: dict[str, str]
) -> tuple[dict[str, str], str, str]:
    """Not a verified fact: the address the student applies with on THIS
    portal, tagged where the portal keeps tags (spec §2a). Shared by
    build_kit and mint_packet so they cannot disagree about contact.email.

    Returns the merged values, the address itself ("" when the student has no
    application_email) and that address without our tag ("" when untagged).
    """
    address = portal_address(application)
    if not address:
        return values, "", ""
    account = account_for(application)
    plain = plain_of(account) if account is not None else ""
    return {**values, "contact.email": address}, address, plain
```

In `build_kit` change `values, address = _merged_with_portal_email(application, values)` to `values, address, _plain = _merged_with_portal_email(application, values)`. In `mint_packet` change `values, _ = _merged_with_portal_email(application, values)` to `values, _, plain_email = _merged_with_portal_email(application, values)`, and add `plain_email=plain_email,` as the last argument of the `FillPacket(...)` call (after `confirmation_markers=(...)`).

- [ ] **Step 5: The route**

In `apps/portals/ext_api.py`: add `from django.utils import timezone` after `from django.http import …`; add `from apps.watch.rules import REGISTRATION_ASK_AFTER` after `from apps.tenancy.middleware import deletion_lock_target`; add `from . import tags` after `from . import pairing as pairing_module`; add `PortalForm` to the `from .models import …` line (wrap it in parentheses, one name per line, if it passes 100 columns). Append:

```python


#: A fill reports its address once per page. Thirty an hour is a student
#: redoing a registration a few times; more is a loop.
_ADDRESS_RATE_LIMIT = 30

#: How the extension knows a portal refused the tagged address, and whether
#: that evidence may move the platform-wide status (tags.py's rule). "form" and
#: "after_submit" are the page itself refusing the tag; "student" is the dock's
#: "use my plain address" button, pressed for an error the extension could not
#: read -- evidence about this account only, never about the portal.
_REJECTION_EVIDENCE = {"form": True, "after_submit": True, "student": False}


@require_POST
@_device_endpoint
def address_report(
    request: HttpRequest, pairing: ExtensionPairing, application_id: UUID
) -> HttpResponse:
    """What happened when the extension typed this portal's address (spec §2a).

    `given`: the page held the address the packet carried. The first report
    for an account is its registration and, when the address is tagged, opens
    the registration-mail window; the answer says so and says when the dock
    should ask the student if no mail has come.
    `rejected`: the page refused the tagged address. The account falls back to
    the plain address for good, and the next packet and kit hand that out.

    Always answers with the account's current address, so the extension never
    has to guess which one the server now holds.
    """
    _limit("ext-address", pairing, _ADDRESS_RATE_LIMIT)
    application = _application_for(pairing, application_id)
    body = _json_body(request)
    event, evidence = body.get("event"), body.get("evidence")
    now = timezone.now()
    awaiting = False
    with tenant_transaction(application.tenant_id):
        account = tags.account_for(application)
        if account is None:
            raise _ApiError(409, "no_portal_address")
        if event == "given":
            if tags.mark_registered(account, now):
                awaiting = tags.awaits_registration_mail(account, now)
                ApplicationStep.objects.create(
                    tenant=application.tenant,
                    application=application,
                    sequence=application.next_step_sequence(),
                    kind=ApplicationStep.Kind.SIGNUP,
                    detail={"tagged": bool(tags.plain_of(account))},
                )
        elif event == "rejected" and isinstance(evidence, str) and evidence in _REJECTION_EVIDENCE:
            tags.record_tag_outcome(
                account,
                PortalForm.TagStatus.REJECTS,
                shared=_REJECTION_EVIDENCE[evidence],
                actor=pairing.membership,
            )
        else:
            raise _ApiError(400, "invalid_report")
    return JsonResponse(
        {
            "address": account.address,
            "awaiting_mail": awaiting,
            "ask_after_seconds": int(REGISTRATION_ASK_AFTER.total_seconds()),
        }
    )
```

In `apps/portals/urls.py`, add as the last entry of `urlpatterns`:

```python
    path(
        "ext/applications/<uuid:application_id>/address",
        ext_api.address_report,
        name="portals-ext-address",
    ),
```

- [ ] **Step 6: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_ext_address.py tests/portals/test_tags.py tests/portals/test_packet.py tests/portals/test_kit.py tests/portals/test_ext_api.py -q`
Expected: all PASS (86 at the time of writing).

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/watch/rules.py apps/portals/tags.py apps/portals/packets.py apps/portals/ext_api.py apps/portals/urls.py tests/portals/test_ext_address.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(portals): the extension reports a held or refused portal address

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The registration question, and a mailbox check that says "reconnect"

**Files:**
- Modify: `apps/mailbox/filter.py` (new `learn_confirmed_sender`)
- Modify: `apps/portals/ext_api.py` (`mailbox_check`; new view `registration`, helper `_registration_state`)
- Modify: `apps/portals/urls.py`
- Test: `tests/portals/test_ext_registration.py`, `tests/portals/test_ext_mailbox_check.py`

**Interfaces:**
- Consumes: Task 1 `tags.record_tag_outcome`, `tags.plain_of`, `tags.account_for`; Task 2 `REGISTRATION_ASK_AFTER`; `apps.mailbox.filter.sender_key`, `learnable_domain`.
- Produces: `filter.learn_confirmed_sender(student: Membership, sender: str, portal_host: str, *, own_addresses: Iterable[str]) -> bool` (inside a tenant transaction); route `GET /ext/applications/<uuid>/registration` → `{"state": "none"}` or `{"state": "waiting" | "ask" | "done", "portal_host": str, "address": str}`; `POST` same path, body `{"arrived": "tagged" | "plain" | "none", "sender": str}` → `{"learned": bool}`, refusals `409 no_registration`, `400 invalid_answer`, `400 invalid_sender`; `POST /ext/mailbox/check` now answers `409 mailbox_disconnected` when every connection refused and one of them lost its grant.

- [ ] **Step 1: Write the failing tests**

Create `tests/portals/test_ext_registration.py`:

```python
"""The registration-mail expectation, asked and answered in the dock (spec §2a)."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.portals.test_ext_api import _application, _pair

pytestmark = pytest.mark.django_db

TAGGED = "leyla.apply+ab12cd@outlook.com"


@pytest.fixture
def registered(agency_a, membership_a):
    """An account on apply.example.edu that registered with its tag `minutes` ago."""
    from apps.portals.models import PortalAccount

    def _make(minutes=10, address=TAGGED):
        with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
            membership_a.application_email = "leyla.apply@outlook.com"
            membership_a.save(update_fields=["application_email"])
            application = _application(agency_a, membership_a)
            PortalAccount.objects.create(
                tenant=agency_a,
                student=membership_a,
                portal_host="apply.example.edu",
                tag="ab12cd",
                address=address,
                registered_at=timezone.now() - timedelta(minutes=minutes),
            )
            return application

    return _make


def _get(client, application, token, host):
    return client.get(
        f"/ext/applications/{application.id}/registration",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _answer(client, application, token, host, body):
    return client.post(
        f"/ext/applications/{application.id}/registration",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _learned(agency, student):
    from apps.mailbox.models import LearnedSender

    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return list(LearnedSender.objects.filter(student=student))


@pytest.mark.parametrize(("minutes", "state"), [(1, "waiting"), (10, "ask"), (45, "ask")])
def test_the_dock_is_told_when_to_ask(
    client, agency_a, domain_a, membership_a, user_a, registered, minutes, state
):
    application = registered(minutes=minutes)
    token = _pair(client, agency_a, membership_a, domain_a)

    body = _get(client, application, token, domain_a.host).json()

    assert body["state"] == state
    assert body["portal_host"] == "apply.example.edu"
    assert body["address"] == TAGGED


def test_an_untagged_account_has_nothing_to_ask(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    application = registered(address="leyla.apply@outlook.com")
    token = _pair(client, agency_a, membership_a, domain_a)

    assert _get(client, application, token, domain_a.host).json() == {"state": "none"}


def test_arrived_at_the_plain_address_measures_strips_and_learns_the_sender_confirmed(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    from apps.portals.models import PortalForm

    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "no-reply@mail-eu.portalvendor.com"},
    )

    assert response.json() == {"learned": True}
    [learned] = _learned(agency_a, membership_a)
    assert learned.domain == "portalvendor.com"
    assert learned.confirmed_at is not None
    assert learned.portal_host == "apply.example.edu"
    assert PortalForm.objects.get(pk=application.portal_form_id).tag_status == "STRIPS"
    assert _get(client, application, token, domain_a.host).json()["state"] == "done"


def test_arrived_at_the_tagged_address_measures_keeps(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    from apps.portals.models import PortalForm

    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, {"arrived": "tagged"})

    assert response.json() == {"learned": False}
    assert PortalForm.objects.get(pk=application.portal_form_id).tag_status == "KEEPS"
    assert _learned(agency_a, membership_a) == []


def test_a_free_mail_sender_is_never_learned(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    """A portal that mails from gmail.com would teach us to read every
    stranger's gmail. The measurement still stands; the sender is refused."""
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(
        client, application, token, domain_a.host, {"arrived": "plain", "sender": "x@gmail.com"}
    )

    assert response.json() == {"learned": False}
    assert _learned(agency_a, membership_a) == []


def test_the_student_s_own_domain_is_never_learned(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "leyla@uni-example.edu.tr"
        membership_a.save(update_fields=["application_email"])

    response = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "friend@uni-example.edu.tr"},
    )

    assert response.json() == {"learned": False}


def test_no_email_records_nothing(client, agency_a, domain_a, membership_a, user_a, registered):
    from apps.portals.models import PortalForm

    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, {"arrived": "none"})

    assert response.status_code == 200
    assert PortalForm.objects.get(pk=application.portal_form_id).tag_status == "UNKNOWN"
    assert _get(client, application, token, domain_a.host).json()["state"] == "ask"


@pytest.mark.parametrize(
    "body",
    [
        {"arrived": "plain"},
        {"arrived": "plain", "sender": "not an address"},
        {"arrived": "maybe"},
        {"arrived": "none", "note": "extra"},
    ],
)
def test_an_answer_the_server_cannot_read_is_refused(
    client, agency_a, domain_a, membership_a, user_a, registered, body
):
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, body)

    assert response.status_code == 400


def test_answering_without_a_registration_is_a_conflict(
    client, agency_a, domain_a, membership_a, user_a
):
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, {"arrived": "tagged"})

    assert response.status_code == 409
```

Append to `tests/portals/test_ext_mailbox_check.py`:

```python


def test_a_lost_grant_is_told_apart_from_a_rate_limit(
    client, agency_a, membership_a, domain_a, monkeypatch
):
    """Plan 2 parked item: every SyncRefused used to answer 429, so the
    extension told a student with a dead grant to wait instead of reconnect."""
    from apps.mailbox import sync as sync_module
    from apps.tenancy.db import tenant_transaction

    def _lost(connection, **_):
        with tenant_transaction(connection.tenant_id):
            MailboxConnection.objects.filter(pk=connection.pk).update(
                status=MailboxConnection.Status.ERROR
            )
        raise sync_module.SyncRefused("provider refused")

    monkeypatch.setattr(sync_module, "sync_connection", _lost)
    with tenant_scope(agency_a.id):
        MailboxConnection.objects.create(
            tenant=agency_a,
            membership=membership_a,
            provider=MailboxConnection.Provider.MICROSOFT,
            address="leyla@outlook.test",
        )
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(CHECK, HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 409
    assert response.json() == {"error": "mailbox_disconnected"}


def test_a_rate_limited_check_still_says_wait(
    client, agency_a, membership_a, domain_a, monkeypatch
):
    from apps.mailbox import sync as sync_module

    def _limited(connection, **_):
        raise sync_module.SyncRefused("sync rate limit reached")

    monkeypatch.setattr(sync_module, "sync_connection", _limited)
    with tenant_scope(agency_a.id):
        MailboxConnection.objects.create(
            tenant=agency_a,
            membership=membership_a,
            provider=MailboxConnection.Provider.MICROSOFT,
            address="leyla@outlook.test",
        )
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(CHECK, HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 429
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_ext_registration.py tests/portals/test_ext_mailbox_check.py -q`
Expected: FAIL — every `/registration` call 404s; `test_a_lost_grant_is_told_apart_from_a_rate_limit` gets 429.

- [ ] **Step 3: Learning a sender the student named**

In `apps/mailbox/filter.py`, add `from django.utils import timezone` above `from apps.funding.models import PackCandidate`, and add directly above `def vouched_senders(`:

```python
def learn_confirmed_sender(
    student: Membership, sender: str, portal_host: str, *, own_addresses: Iterable[str]
) -> bool:
    """The student named who sent a portal's email: read it, and trust it.

    Spec §3 rule 2 keeps a learned domain read-only "until the student confirms
    one message from it belongs to that institution". Here the student is the
    source: standing at the portal they just registered on, they read the
    sender off that portal's own email (spec §2a). That is the confirmation, so
    the row is written confirmed. The same guards as learning from a tag: never
    free mail, never the student's own domains.

    Run inside the student's tenant transaction. False when the domain may
    never be learned (or `sender` names no usable domain).
    """
    domain = sender_key(sender)
    own = {sender_key(address) for address in own_addresses} - {""}
    if not domain or not learnable_domain(domain, own_domains=own):
        return False
    learned, _ = LearnedSender.objects.get_or_create(
        student=student,
        domain=domain,
        defaults={"tenant_id": student.tenant_id, "portal_host": portal_host},
    )
    LearnedSender.objects.filter(pk=learned.pk, confirmed_at__isnull=True).update(
        confirmed_at=timezone.now()
    )
    return True


```

- [ ] **Step 4: The routes**

In `apps/portals/ext_api.py`: add `from datetime import datetime` after `from collections.abc import Callable`, and `PortalAccount` to the `from .models import (...)` list.

In `mailbox_check`, replace

```python
    if connections and refused == len(connections):
        raise _ApiError(429, "rate_limited")
    return JsonResponse({"new_signals": new})
```

with

```python
    if connections and refused == len(connections):
        # "Wait" and "reconnect" are different answers for the dock: a lost
        # grant flips its row to ERROR inside sync_connection (plan 2 parked
        # item, closed here), and telling that student to wait would be a lie.
        with tenant_transaction(pairing.tenant_id):
            disconnected = MailboxConnection.objects.filter(
                pk__in=[connection.pk for connection in connections],
                status=MailboxConnection.Status.ERROR,
            ).exists()
        if disconnected:
            raise _ApiError(409, "mailbox_disconnected")
        raise _ApiError(429, "rate_limited")
    return JsonResponse({"new_signals": new})
```

(`MailboxConnection` is the function's own local import.) Append at the end of the module:

```python


#: The dock asks once per registration; a student answering twice is fine, a
#: page answering in a loop is not.
_REGISTRATION_RATE_LIMIT = 30

_ARRIVED = {"tagged": PortalForm.TagStatus.KEEPS, "plain": PortalForm.TagStatus.STRIPS}


class _RegistrationAnswer(BaseModel):
    """What the student said about the portal's first email. Typed, capped:
    `sender` is text the student typed, and it only ever becomes a domain."""

    model_config = ConfigDict(extra="forbid")

    arrived: str = Field(pattern="^(tagged|plain|none)$")
    sender: str = Field(default="", max_length=320)


@require_http_methods(["GET", "POST"])
@_device_endpoint
def registration(
    request: HttpRequest, pairing: ExtensionPairing, application_id: UUID
) -> HttpResponse:
    """The registration-mail expectation (spec §2a), asked and answered in the dock.

    GET says where it stands: `none` (no tagged registration to watch),
    `done` (the portal's mail, or the student, already answered), `waiting`
    (too early to ask), or `ask` (the mailbox has not answered; ask the
    student while they are still at the portal).

    POST is the student's answer. `tagged` measures KEEPS; `plain` measures
    STRIPS and learns the sender they named, confirmed, because they named it
    (apps.mailbox.filter.learn_confirmed_sender); `none` records nothing --
    the tag status stays unmeasured, which is the safe default.
    """
    _limit("ext-registration", pairing, _REGISTRATION_RATE_LIMIT)
    application = _application_for(pairing, application_id)
    now = timezone.now()
    with tenant_transaction(application.tenant_id):
        account = tags.account_for(application)
    if request.method == "GET":
        return JsonResponse(_registration_state(account, now))

    if account is None or account.registered_at is None:
        raise _ApiError(409, "no_registration")
    try:
        answer = _RegistrationAnswer.model_validate(_json_body(request))
    except ValidationError as error:
        raise _ApiError(400, "invalid_answer") from error
    # Imported here, not at module load: apps.mailbox imports apps.portals.
    from apps.mailbox.filter import learn_confirmed_sender, sender_key
    from apps.mailbox.models import MailboxConnection

    if answer.arrived == "plain" and not sender_key(answer.sender):
        raise _ApiError(400, "invalid_sender")
    learned = False
    with tenant_transaction(application.tenant_id):
        if answer.arrived in _ARRIVED:
            tags.record_tag_outcome(
                account, _ARRIVED[answer.arrived], shared=True, actor=pairing.membership
            )
        if answer.arrived == "plain":
            own = [
                application.student.application_email,
                account.address,
                *MailboxConnection.objects.filter(membership=pairing.membership).values_list(
                    "address", flat=True
                ),
            ]
            learned = learn_confirmed_sender(
                pairing.membership, answer.sender, account.portal_host, own_addresses=own
            )
    return JsonResponse({"learned": learned})


def _registration_state(account: PortalAccount | None, now: datetime) -> dict[str, object]:
    if account is None or account.registered_at is None or not tags.plain_of(account):
        return {"state": "none"}
    if account.tag_outcome != PortalForm.TagStatus.UNKNOWN:
        state = "done"
    elif now - account.registered_at < REGISTRATION_ASK_AFTER:
        state = "waiting"
    else:
        state = "ask"
    return {"state": state, "portal_host": account.portal_host, "address": account.address}
```

In `apps/portals/urls.py`, add as the last entry:

```python
    path(
        "ext/applications/<uuid:application_id>/registration",
        ext_api.registration,
        name="portals-ext-registration",
    ),
```

- [ ] **Step 5: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_ext_registration.py tests/portals/test_ext_mailbox_check.py tests/mailbox/test_filter.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/mailbox/filter.py apps/portals/ext_api.py apps/portals/urls.py tests/portals/test_ext_registration.py tests/portals/test_ext_mailbox_check.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(portals): ask the student about the registration email; a lost grant says reconnect

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The mail itself measures the tag

**Files:**
- Modify: `apps/mailbox/sync.py`
- Test: `tests/mailbox/test_registration_mail.py`

**Interfaces:**
- Consumes: Task 1 `tags.record_tag_outcome`; Task 2 `tags.awaits_registration_mail`, `REGISTRATION_MAIL_WINDOW`; `filter._key` (the host → allowlist-key function plan 2 built).
- Produces: `sync._awaiting_registration(student: Membership, now: datetime) -> dict[str, PortalAccount]`; `sync_connection` records KEEPS on any new signal sent to a tag, and STRIPS on a new untagged signal whose allowlist key is a registering portal's own key, received after `registered_at`.

- [ ] **Step 1: Write the failing tests**

Create `tests/mailbox/test_registration_mail.py`:

```python
"""The registration-mail expectation, resolved by the mail itself (spec §2a).

Tagged mail says the portal keeps the tag. Untagged mail from the portal the
student just registered on says it strips it. Nothing else is inferred.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import sync_connection
from apps.portals.models import PortalAccount, PortalForm
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.mailbox.conftest import FakeProvider, _grant

pytestmark = pytest.mark.django_db
TAGGED = "student+ab12cd@gmail.test"


@pytest.fixture
def registering(connection_with_pack):
    """connection_with_pack's student registered on portal.uni-bonn.de with a
    tag two minutes ago."""
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=TAGGED,
            registered_at=timezone.now() - timedelta(minutes=2),
        )
    return connection


def _header(sender, *, to, received_at=None):
    return MessageHeader(
        message_id=f"m-{sender}-{to}",
        sender=sender,
        received_at=received_at or timezone.now(),
        recipients=(to,),
    )


def _sync(connection, *headers):
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider(headers), secrets_client=_grant())


def _outcome(connection):
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        return PortalAccount.objects.get(student=connection.membership).tag_outcome


def _shared():
    return PortalForm.objects.get(portal_host="portal.uni-bonn.de").tag_status


def test_mail_to_the_tag_measures_keeps(registering):
    _sync(registering, _header("noreply@uni-bonn.de", to=TAGGED))

    assert _outcome(registering) == "KEEPS"
    assert _shared() == "KEEPS"


def test_untagged_mail_from_the_portal_inside_the_window_measures_strips(registering):
    _sync(registering, _header("noreply@mail.uni-bonn.de", to="student@gmail.test"))

    assert _outcome(registering) == "STRIPS"
    assert _shared() == "STRIPS"


def test_untagged_mail_from_before_the_registration_says_nothing(registering):
    """A first sync reads back to when tracking began; a portal email from
    before the student registered is not the registration email."""
    _sync(
        registering,
        _header(
            "noreply@uni-bonn.de",
            to="student@gmail.test",
            received_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )

    assert _outcome(registering) == "UNKNOWN"


def test_untagged_mail_after_the_window_says_nothing(registering):
    with tenant_scope(registering.tenant_id), tenant_transaction(registering.tenant_id):
        PortalAccount.objects.filter(student=registering.membership).update(
            registered_at=timezone.now() - timedelta(hours=2)
        )

    _sync(registering, _header("noreply@uni-bonn.de", to="student@gmail.test"))

    assert _outcome(registering) == "UNKNOWN"
    assert _shared() == "UNKNOWN"


def test_untagged_mail_from_another_pack_domain_says_nothing(registering):
    """tum.de is in the pack, not the portal the student registered on."""
    _sync(registering, _header("noreply@tum.de", to="student@gmail.test"))

    assert _outcome(registering) == "UNKNOWN"


def test_a_set_shared_status_survives_the_mail(registering):
    PortalForm.objects.filter(portal_host="portal.uni-bonn.de").update(
        tag_status=PortalForm.TagStatus.KEEPS
    )

    _sync(registering, _header("noreply@uni-bonn.de", to="student@gmail.test"))

    assert _outcome(registering) == "STRIPS"
    assert _shared() == "KEEPS"
```

(`connection_with_pack` is a GOOGLE connection with the default CONTENT tier; `classify_message` is reached for these headers — `tests/mailbox/conftest.py` already blocks outbound connections, and a failed classification only counts an attempt. If an implementer sees a real model call attempted, stub `apps.mailbox.sync.classify_message` with `lambda **_: MailVerdict(label="OTHER")` per the Global Constraints.)

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox/test_registration_mail.py -q`
Expected: FAIL — `assert 'UNKNOWN' == 'KEEPS'` (and `== 'STRIPS'`); the three "says nothing" tests pass already, which is correct.

- [ ] **Step 3: Implement**

In `apps/mailbox/sync.py`:

Add `_key,` as the first name in the `from apps.mailbox.filter import (…)` block. Replace

```python
from apps.portals.models import Application, PortalAccount
from apps.ratelimit import rate_limited
from apps.tenancy.db import tenant_transaction
```

with

```python
from apps.portals.models import Application, PortalAccount, PortalForm
from apps.portals.tags import awaits_registration_mail, record_tag_outcome
from apps.ratelimit import rate_limited
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership
from apps.watch.rules import REGISTRATION_MAIL_WINDOW
```

Inside `sync_connection`'s first `with tenant_transaction(connection.tenant_id):` block, directly after the `tags = {…}` dict comprehension closes (still inside the `with`), add:

```python
        awaiting = _awaiting_registration(connection.membership, timezone.now())
```

In the header loop, replace

```python
            if is_new:
                created.append(signal)
                announce(signal)
                if shared_portal is not None:
                    shared_portals[signal.pk] = shared_portal
```

with

```python
            if is_new:
                created.append(signal)
                announce(signal)
                if shared_portal is not None:
                    shared_portals[signal.pk] = shared_portal
                # Spec §2a: what this portal does with the tag, measured by the
                # mail itself. Any mail to a tag says the tag survived; untagged
                # mail from a portal the student just registered on says it was
                # stripped. record_tag_outcome keeps the first answer only.
                if account is not None:
                    record_tag_outcome(
                        account, PortalForm.TagStatus.KEEPS, shared=True, actor=None
                    )
                elif (registering := awaiting.get(domain)) is not None and (
                    registering.registered_at is not None
                    and header.received_at >= registering.registered_at
                ):
                    record_tag_outcome(
                        registering, PortalForm.TagStatus.STRIPS, shared=True, actor=None
                    )
```

Add directly above `def _applications_on(`:

```python
def _awaiting_registration(student: Membership, now: datetime) -> dict[str, PortalAccount]:
    """The sender keys of portals whose registration mail is still due (spec §2a).

    Before a portal's sender is known, "untagged mail from that portal" can
    only mean mail from a domain the portal's own row names: its host, or one
    of its curated sender_domains -- both already read under rule 2. A vendor
    domain nobody has recorded matches nothing here; the dock asks the student
    for it instead (ext_api.registration). Read inside the caller's tenant
    transaction.
    """
    awaiting: dict[str, PortalAccount] = {}
    accounts = PortalAccount.objects.filter(
        student=student,
        tag_outcome=PortalForm.TagStatus.UNKNOWN,
        registered_at__gte=now - REGISTRATION_MAIL_WINDOW,
    )
    for account in accounts:
        if not awaits_registration_mail(account, now):
            continue
        curated = PortalForm.objects.filter(portal_host=account.portal_host).values_list(
            "sender_domains", flat=True
        )
        for entry in (account.portal_host, *(d for domains in curated for d in domains or ())):
            if key := _key(str(entry)):
                awaiting.setdefault(key, account)
    return awaiting
```

Why the untagged branch compares `domain` (the matched allowlist key) with `awaiting`'s keys: `matched_domain` returns the allowlist entry the sender falls under — `uni-bonn.de` for `noreply@mail.uni-bonn.de` — and `_key("portal.uni-bonn.de")` is the same `uni-bonn.de`.

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox -q`
Expected: all PASS (217 at the time of writing, including every plan-2 tagged-mail test — those now also record KEEPS, which none of them contradicts).

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/mailbox/sync.py tests/mailbox/test_registration_mail.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(mailbox): tagged and untagged registration mail measure whether a portal keeps the tag

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A learned field map can carry the portal address

**Files:**
- Modify: `apps/portals/learn.py` (`learn_from_snapshot` only — not `learn_form`)
- Modify: `apps/portals/ext_api.py` (`snapshot`)
- Test: `tests/portals/test_snapshot_learn.py`, `tests/portals/test_ext_api.py`

**Interfaces:**
- Consumes: Task 1 `tags.account_for`, `tags.plain_of`, `tags.portal_address`.
- Produces: `learn_from_snapshot(..., optional_fields: tuple[str, ...] = (), client=None)` — optional fields are offered to the model and mapped when present, skipped (never `UnmappedField`) when absent. The snapshot route offers `("contact.email",)` whenever the student has a portal address, and adds the tagged and plain addresses to `forbidden_values`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/portals/test_snapshot_learn.py`:

```python


def _snapshot_with_email():
    from apps.portals.snapshot import FormSnapshot

    base = _snapshot()
    return FormSnapshot(
        page_url=base.page_url,
        controls=[
            *base.controls,
            {
                "selector": "#email",
                "tag": "input",
                "type": "email",
                "name": "email",
                "id": "email",
                "label": "Email address",
                "placeholder": "",
                "options": [],
                "required": True,
            },
        ],
    )


@pytest.mark.django_db
def test_the_portal_address_is_learned_when_the_page_asks_for_it(agency_a) -> None:
    """contact.email is not a verified fact, so it was never offered to the
    learn pass, and a learned map could never fill it (plan 2's deferred item)."""
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-email-1")
    client = _client([("identity.full_name", "#name"), ("contact.email", "#email")])
    field_map = learn_from_snapshot(
        form,
        _snapshot_with_email(),
        profile_fields=["identity.full_name"],
        optional_fields=("contact.email",),
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=client,
    )

    assert [entry["profile_field"] for entry in field_map.entries] == [
        "identity.full_name",
        "contact.email",
    ]
    assert "contact.email" in client.responses.calls[0]["input"][1]["content"]


@pytest.mark.django_db
def test_a_page_with_no_email_control_still_learns(agency_a) -> None:
    from apps.portals.learn import learn_from_snapshot
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="learn-email-2")
    field_map = learn_from_snapshot(
        form,
        _snapshot(),
        profile_fields=["identity.full_name"],
        optional_fields=("contact.email",),
        tenant_id=agency_a.id,
        forbidden_values=[],
        client=_client([("identity.full_name", "#name")]),
    )

    assert [entry["profile_field"] for entry in field_map.entries] == ["identity.full_name"]
```

Append to `tests/portals/test_ext_api.py`:

```python


def test_a_snapshot_offers_the_portal_address_and_forbids_it(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch
) -> None:
    from apps.portals import ext_api
    from apps.portals.models import FieldMap

    seen = {}

    def _learn(form, snapshot, **kwargs):
        seen.update(kwargs)
        return FieldMap.objects.create(portal_form=form, version=1, entries=[])

    monkeypatch.setattr(ext_api, "verified_values", lambda student: {})
    monkeypatch.setattr(ext_api, "learn_from_snapshot", _learn)
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        f"/ext/portal-forms/{application.portal_form_id}/snapshot",
        data=json.dumps(SNAPSHOT_BODY),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 201
    assert seen["optional_fields"] == ("contact.email",)
    assert "leyla.apply@outlook.com" in seen["forbidden_values"]
    assert any(value.startswith("leyla.apply+") for value in seen["forbidden_values"])
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_snapshot_learn.py tests/portals/test_ext_api.py -q`
Expected: FAIL — `TypeError: learn_from_snapshot() got an unexpected keyword argument 'optional_fields'` and `KeyError: 'optional_fields'`.

- [ ] **Step 3: Implement**

In `apps/portals/learn.py`, **inside `learn_from_snapshot` only** (`learn_form` has an identical `is_fillable` block — leave that one alone):

- Add the parameter `optional_fields: tuple[str, ...] = (),` between `forbidden_values: list[str],` and `client: object | None = None,`, and add to its docstring after the first line:

```python

    `profile_fields` must all map or the whole map is refused (UnmappedField).
    `optional_fields` are mapped when the page asks for them and skipped when
    it does not: contact.email is not a verified fact but the portal address
    (tags.py), and a page without an email control is an ordinary page, not a
    half-learned one.
```

- Directly above `parser = client.responses if client is not None else OpenAI().responses`, add `requested = [*profile_fields, *optional_fields]`.
- In the user prompt, change `{json.dumps(profile_fields)}` to `{json.dumps(requested)}`.
- Change `for profile_field in profile_fields:` to `for profile_field in requested:`.
- In that loop, change both `unmapped.append(profile_field)` statements (the `if control is None:` one and the one after `if not is_fillable(action):` that follows `arguments=[VALUE_PLACEHOLDER],`) to:

```python
            if profile_field not in optional_fields:
                unmapped.append(profile_field)
```

In `apps/portals/ext_api.py`'s `snapshot` view, replace

```python
    with tenant_transaction(application.tenant_id):
        values = verified_values(pairing.membership)
    try:
        field_map = learn_from_snapshot(
            application.portal_form,
            parsed,
            profile_fields=sorted(values),
            tenant_id=application.tenant_id,
            forbidden_values=list(values.values()),
        )
```

with

```python
    with tenant_transaction(application.tenant_id):
        values = verified_values(pairing.membership)
        # The portal address is the one field the map needs that is not a
        # verified fact (tags.py). Learned when the page asks for it; and the
        # addresses themselves are forbidden in the snapshot like any value.
        address = tags.portal_address(application)
        account = tags.account_for(application) if address else None
    addresses = [address, tags.plain_of(account)] if account is not None else []
    try:
        field_map = learn_from_snapshot(
            application.portal_form,
            parsed,
            profile_fields=sorted(values),
            optional_fields=("contact.email",) if address else (),
            tenant_id=application.tenant_id,
            forbidden_values=[*values.values(), *addresses],
        )
```

(`assert_no_student_values` already skips a blank forbidden value, so an empty `plain_of` costs nothing.)

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals -q`
Expected: all PASS, including `tests/portals/test_learn.py` (proof that `learn_form` was not touched).

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/portals/learn.py apps/portals/ext_api.py tests/portals/test_snapshot_learn.py tests/portals/test_ext_api.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(portals): a snapshot-learned field map can carry the portal address

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The content script sees a refused tag and types the plain address

**Files:**
- Create: `extension/src/content/address.ts`
- Modify: `extension/src/content/fill.ts` (new `retype`)
- Modify: `extension/src/content/index.ts`
- Modify: `extension/src/types.ts` (`FillPacket.plain_email`)
- Create: `tests/portals/fixtures/tag_rejecting_form.html`, `tests/portals/fixtures/tag_rejected_after_submit.html`, `tests/portals/fixtures/email_only_one_address.html`
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Consumes: Task 2's `plain_email` in the packet and its `address` route (reached through the worker in Task 7).
- Produces: content → worker message `{type: "address", applicationId, event: "given"}` or `{type: "address", applicationId, event: "rejected", evidence: "form" | "after_submit" | "student"}`; content-script message listener case `{type: "use_plain_address"}`; test hook `window.__tehsil_use_plain`; `retype(item: VerifiedEntry, value: string): void`; `checkAddress(item, plain, cameBackRejected): Promise<"kept" | "rejected" | "rejected_after_submit" | "unclear">`; `looksRejected(element: HTMLElement): boolean`.

- [ ] **Step 1: Fixtures**

`tests/portals/fixtures/tag_rejecting_form.html`:

```html
<!doctype html><html><body><form>
  <!-- Studielink's measured behaviour (spec, 2026-09-26): the form's own
       validation refuses a "+" and accepts the plain address. -->
  <label for="em">Email address</label>
  <input id="em" name="email" type="email" pattern="[^+]+@.+">
  <button type="submit">Create account</button>
</form></body></html>
```

`tests/portals/fixtures/tag_rejected_after_submit.html`:

```html
<!doctype html><html><body><form>
  <!-- The page a portal sends back when it refused the tagged address only
       after Submit: the value it was given, marked invalid by the server. -->
  <label for="em">Email address</label>
  <input id="em" name="email" type="email" value="leyla.apply+ab12cd@outlook.com"
         aria-invalid="true" aria-errormessage="em-error">
  <p id="em-error" role="alert">No valid email address has been provided</p>
  <button type="submit">Create account</button>
</form></body></html>
```

`tests/portals/fixtures/email_only_one_address.html`:

```html
<!doctype html><html><body><form>
  <!-- Refuses every address but one: the "+" is not the reason. -->
  <label for="em">Email address</label>
  <input id="em" name="email" type="email" pattern="nobody@example\.org">
  <button type="submit">Create account</button>
</form></body></html>
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/portals/test_extension_e2e.py`:

```python


TAGGED = "leyla.apply+ab12cd@outlook.com"
PLAIN = "leyla.apply@outlook.com"


def _email_packet(form_url):
    """A packet whose one entry is the portal address (apps/portals/tags.py)."""
    return {
        "ok": True,
        "packet": {
            "application_id": "app-1",
            "portal_form_id": "form-1",
            "field_map_version": 1,
            "form_url": form_url,
            "entries": [
                {
                    "selector": "#em",
                    "method": "fill",
                    "value": TAGGED,
                    "profile_field": "contact.email",
                }
            ],
            "documents": [],
            "issued_at": "2026-09-27T10:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "min_extension_version": "0.1.0",
            "confirmation_markers": None,
            "plain_email": PLAIN,
        },
    }


def _of_type(sent, kind):
    return [message for message in sent if message["type"] == kind]


@pytest.mark.extension
def test_a_form_that_refuses_the_tag_gets_the_plain_address(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/tag_rejecting_form.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == PLAIN
    [report] = _of_type(sent, "address")
    assert (report["event"], report["evidence"]) == ("rejected", "form")
    [read_back] = [m for m in _of_type(sent, "event") if m["kind"] == "READ_BACK"]
    assert read_back["detail"]["mismatches"] == []


@pytest.mark.extension
def test_a_form_that_keeps_the_tag_reports_the_registration(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == TAGGED
    [report] = _of_type(sent, "address")
    assert report["event"] == "given"


@pytest.mark.extension
def test_a_rejection_after_submit_swaps_the_address_and_never_submits(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/tag_rejected_after_submit.html")
    page.evaluate(
        "() => { window.__submitted = false; "
        "document.forms[0].addEventListener('submit', () => { window.__submitted = true; }); }"
    )

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == PLAIN
    [report] = _of_type(sent, "address")
    assert (report["event"], report["evidence"]) == ("rejected", "after_submit")
    assert "Submit the form again yourself" in sent[-1]["patch"]["message"]
    assert page.evaluate("() => window.__submitted") is False


@pytest.mark.extension
def test_an_error_the_plain_address_also_gets_is_not_blamed_on_the_tag(
    browser_context, fixture_server
) -> None:
    """Both addresses refused: the "+" is not the reason, so nothing is
    reported -- a report here would mark the portal REJECTS for everyone."""
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/email_only_one_address.html")

    sent = _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    assert page.input_value("#em") == TAGGED
    assert _of_type(sent, "address") == []


@pytest.mark.extension
def test_the_plain_address_button_types_it_and_says_it_was_the_student(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _run_with_stubbed_messaging(page, {"packet": _email_packet(fixture_server)})

    page.evaluate("() => window.__tehsil_use_plain()")
    sent = page.evaluate("() => window.__sent")

    assert page.input_value("#em") == PLAIN
    assert (sent[-2]["event"], sent[-2]["evidence"]) == ("rejected", "student")
```

- [ ] **Step 3: Run to verify failure**

Run: `npm --prefix extension ci && npm --prefix extension run check && POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_e2e.py -m extension -q`
Expected: the five new tests FAIL (`ValueError: not enough values to unpack` on the missing `address` message; `window.__tehsil_use_plain is not a function`); the existing ones PASS.

- [ ] **Step 4: `address.ts` and `retype`**

Create `extension/src/content/address.ts`:

```ts
/**
 * Did the portal refuse the tagged address? (spec §2a)
 *
 * Read the way a person reads it: the browser's own validity state, the
 * control's aria-invalid, or an error the page ties to the control. The
 * comparison is what makes the verdict evidence rather than a guess: the
 * tagged address is refused AND the plain address, in the same control, is
 * not. Only then is the "+" the reason, and only then may the report move the
 * portal's shared status (apps/portals/tags.py).
 *
 * ponytail: an error the page shows anywhere else -- a banner at the top, a
 * toast -- is invisible to errorBeside(). The dock's "use my plain address"
 * button is the answer for those; widening this to page text would read
 * unrelated errors as the tag's fault for every tenant.
 */
import { retype } from "./fill.js";
import type { VerifiedEntry } from "./verify.js";

export type AddressVerdict = "kept" | "rejected" | "rejected_after_submit" | "unclear";

/** An error the page ties to this control: its aria-errormessage target, or
 *  a role=alert inside the control's own container. */
function errorBeside(element: HTMLElement): boolean {
  const targets: Element[] = [];
  const own = element.getAttribute("aria-errormessage");
  const named = own ? document.getElementById(own) : null;
  if (named) targets.push(named);
  if (element.parentElement) {
    targets.push(...Array.from(element.parentElement.querySelectorAll('[role="alert"]')));
  }
  return targets.some(
    (node) => node instanceof HTMLElement && !node.hidden && (node.textContent ?? "").trim() !== "",
  );
}

export function looksRejected(element: HTMLElement): boolean {
  if (element instanceof HTMLInputElement && !element.validity.valid) return true;
  if (element.getAttribute("aria-invalid") === "true") return true;
  return errorBeside(element);
}

/** Let the page react as it would to a person leaving the field: many forms
 *  validate on blur, not on input. A focus event, never a click. */
async function settle(element: HTMLElement): Promise<void> {
  element.dispatchEvent(new FocusEvent("blur"));
  element.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 150));
}

/**
 * Check the tagged address the run just left in `item`'s control, and swap in
 * `plain` when the portal refuses it.
 *
 * `cameBackRejected` is read BEFORE the run typed anything: the page the
 * portal returned after the student pressed Submit already holds the tagged
 * address and marks it invalid. Nothing can be compared on that page -- the
 * error is the server's and stays until the next submit -- so the page's own
 * word is taken, the plain address typed, and the student submits again. The
 * extension never does.
 */
export async function checkAddress(
  item: VerifiedEntry,
  plain: string,
  cameBackRejected: boolean,
): Promise<AddressVerdict> {
  const element = item.element;
  if (!element) return "unclear";
  if (cameBackRejected) {
    retype(item, plain);
    return "rejected_after_submit";
  }
  await settle(element);
  if (!looksRejected(element)) return "kept";
  retype(item, plain);
  await settle(element);
  if (!looksRejected(element)) return "rejected";
  // The plain address is refused too, so the "+" is not the reason. Put back
  // what the packet says and let the student read the portal's own error.
  retype(item, item.entry.value);
  return "unclear";
}
```

(The comments may say "pressed"; esbuild drops comments from the bundle. **Strings** may not contain `press` — see Global Constraints.)

In `extension/src/content/fill.ts`, directly above `/** What the page holds now, against what the packet says it should.`, add:

```ts
/** Type a different value into a control that already passed verification --
 *  the plain address where a portal refused the tagged one (address.ts).
 *  Through fillVerified, so the method allowlist still guards the write. */
export function retype(item: VerifiedEntry, value: string): void {
  fillVerified([{ ...item, entry: { ...item.entry, value } }], new Set());
}

```

In `extension/src/types.ts`, in `FillPacket`, after `confirmation_markers: string[] | null;` add:

```ts
  /** contact.email without our tag; "" (or absent, from an older server) when
   *  the address carries none. Typed instead when the portal refuses the tag. */
  plain_email?: string;
```

- [ ] **Step 5: `index.ts`**

Replace the two import lines

```ts
import type { FillPacket, PacketField } from "../types.js";
import { alreadyCorrect, attachDocuments, fillVerified, readBack } from "./fill.js";
```

with

```ts
import type { FillPacket, PacketField } from "../types.js";
import type { AddressVerdict } from "./address.js";
import { checkAddress, looksRejected } from "./address.js";
import { alreadyCorrect, attachDocuments, fillVerified, readBack, retype } from "./fill.js";
```

Directly after the `dock()` function, add:

```ts

/** The portal-address control of the last run on this page, for the dock's
 *  "use my plain address" button. Page-lifetime only, like the run itself. */
let lastEmail: { applicationId: string; item: VerifiedEntry; plain: string } | null = null;

/** The student chose "use my plain address": an error we could not read.
 *  Their evidence about their own account only -- the server moves nothing
 *  shared on it (ext_api._REJECTION_EVIDENCE). */
async function usePlainAddress(): Promise<void> {
  if (!lastEmail) {
    await dock({ message: "Start filling this page first, then use this button again." });
    return;
  }
  retype(lastEmail.item, lastEmail.plain);
  await ask({
    type: "address",
    applicationId: lastEmail.applicationId,
    event: "rejected",
    evidence: "student",
  });
  await dock({
    message: "We typed your plain address. Check it, then submit with the portal's own button.",
  });
}
```

In `run()`, replace

```ts
  const skip = alreadyCorrect(verified);
  const filled = fillVerified(verified, skip);
```

with

```ts
  const skip = alreadyCorrect(verified);
  const email = verified.find(
    (item) => item.ok && item.element && item.entry.profile_field === "contact.email",
  );
  const plain = packet.plain_email ?? "";
  // Read before typing: the page the portal sent back after Submit.
  const cameBack = Boolean(
    email?.element && plain && skip.has("contact.email") && looksRejected(email.element),
  );
  const filled = fillVerified(verified, skip);
  const address: AddressVerdict | null =
    email && plain ? await checkAddress(email, plain, cameBack) : null;
  const swapped = address === "rejected" || address === "rejected_after_submit";
  lastEmail = email && plain ? { applicationId, item: email, plain } : null;
```

Replace

```ts
  const mismatches = readBack(verified.filter((item) => item.ok));
```

with

```ts
  if (swapped) {
    await ask({
      type: "address",
      applicationId,
      event: "rejected",
      evidence: address === "rejected" ? "form" : "after_submit",
    });
  } else if (address === "kept" && filled.includes("contact.email")) {
    // Typed now and held: the first such report for this portal account is
    // its registration (ext_api.address_report).
    await ask({ type: "address", applicationId, event: "given" });
  }

  // Read back against what the page SHOULD hold, which after a swap is the
  // plain address -- otherwise our own fallback reads as a portal error.
  const mismatches = readBack(
    verified
      .filter((item) => item.ok)
      .map((item) =>
        swapped && item === email ? { ...item, entry: { ...item.entry, value: plain } } : item,
      ),
  );
```

In the final `dock({...})` of `run()`, replace

```ts
    // The one thing the student must be told every single time.
    message: "Check the form, then submit it yourself with the portal's own button.",
```

with

```ts
    // The one thing the student must be told every single time.
    message:
      (swapped
        ? "This portal would not take your tagged address, so we typed your plain one. "
        : "") +
      (address === "rejected_after_submit"
        ? "Submit the form again yourself, with the portal's own button."
        : "Check the form, then submit it yourself with the portal's own button."),
```

In the `chrome.runtime.onMessage` listener, after the `"start"` line, add:

```ts
    if (message?.type === "use_plain_address") void usePlainAddress();
```

After the `__tehsil_run` hook line, add:

```ts
(globalThis as Record<string, unknown>)["__tehsil_use_plain"] = usePlainAddress;
```

- [ ] **Step 6: Run to verify pass**

Run: `npm --prefix extension run check && POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_bundle.py -q && POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_e2e.py -m extension -q`
Expected: typecheck and build clean; all PASS. If `test_the_content_script_types_only_the_allowed_methods` fails on `press`, a user-facing string contains it — reword the string, never the test.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add extension/src/content/address.ts extension/src/content/fill.ts extension/src/content/index.ts extension/src/types.ts tests/portals/fixtures/tag_rejecting_form.html tests/portals/fixtures/tag_rejected_after_submit.html tests/portals/fixtures/email_only_one_address.html tests/portals/test_extension_e2e.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(extension): read back the tagged address and type the plain one where a portal refuses it

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The worker reports, waits on an alarm, and the dock asks

**Files:**
- Modify: `extension/manifest.json` (`alarms` permission)
- Modify: `extension/src/api.ts` (four functions)
- Modify: `extension/src/service_worker.ts`
- Modify: `extension/src/types.ts` (`DockState.registration`)
- Modify: `extension/src/panel/panel.html`, `extension/src/panel/panel.ts`
- Test: `tests/portals/test_extension_e2e.py`, `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: Task 2 route `/address` and its `awaiting_mail` / `ask_after_seconds`; Task 3 routes `/registration` (GET/POST) and `/ext/mailbox/check`'s `409 mailbox_disconnected`; Task 6's `address` and `use_plain_address` messages.
- Produces: `postAddress`, `checkMailbox`, `fetchRegistration`, `postRegistrationAnswer` in `api.ts`; worker cases `"address"` and `"registration:answer"`; alarm `registration:<applicationId>`; `DockState.registration: { applicationId: string; portalHost: string; address: string } | null`; panel elements `#registration`, `#registration-question`, `#arrived-tagged`, `#arrived-plain`, `#arrived-none`, `#sender`, `#use-plain`; panel → worker `{type: "registration:answer", applicationId, arrived, sender}`; panel → tab `{type: "use_plain_address"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/portals/test_extension_e2e.py`:

```python


def _open_panel(browser_context):
    """The real dock bundle, with a stub `chrome` that records what it sends.

    The panel is an extension page, so it is loaded from dist/ as a file rather
    than served; the stub is installed before panel.js runs. Clicking here is
    the TEST pressing the student's button -- the no-click rule binds the
    extension's own bundles, which test_no_code_path_clicks scans.
    """
    page = browser_context.new_page()
    page.add_init_script(
        """
        window.__sent = [];
        window.__listeners = [];
        window.chrome = {
          runtime: {
            sendMessage: async (message) => { window.__sent.push(message); },
            onMessage: { addListener: (listener) => window.__listeners.push(listener) },
          },
          tabs: {
            query: async () => [{ id: 7 }],
            sendMessage: async (tabId, message) => { window.__sent.push({ tabId, ...message }); },
          },
        };
        """
    )
    page.goto((DIST / "panel.html").as_uri())
    return page


def _push_state(page, state):
    page.evaluate(
        "(state) => window.__listeners.forEach((listener) => "
        "listener({ type: 'dock:state', state }))",
        state,
    )


@pytest.mark.extension
def test_the_dock_asks_about_the_registration_email_only_when_told_to(browser_context) -> None:
    page = _open_panel(browser_context)
    assert page.is_hidden("#registration")

    _push_state(
        page,
        {
            "registration": {
                "applicationId": "app-1",
                "portalHost": "apply.example.edu",
                "address": TAGGED,
            }
        },
    )

    assert page.is_visible("#registration")
    assert "apply.example.edu" in page.inner_text("#registration-question")
    assert TAGGED in page.inner_text("#arrived-tagged")


@pytest.mark.extension
def test_the_student_s_answer_carries_the_sender_they_typed(browser_context) -> None:
    page = _open_panel(browser_context)
    _push_state(
        page,
        {"registration": {"applicationId": "app-1", "portalHost": "x.edu", "address": TAGGED}},
    )

    page.fill("#sender", " noreply@mail-eu.portalvendor.com ")
    page.click("#arrived-plain")

    answer = page.evaluate("() => window.__sent.at(-1)")
    assert answer == {
        "type": "registration:answer",
        "applicationId": "app-1",
        "arrived": "plain",
        "sender": "noreply@mail-eu.portalvendor.com",
    }


@pytest.mark.extension
def test_use_my_plain_address_goes_to_the_portal_tab(browser_context) -> None:
    page = _open_panel(browser_context)

    page.click("#use-plain")

    assert page.evaluate("() => window.__sent.at(-1)") == {
        "tabId": 7,
        "type": "use_plain_address",
    }
```

Append to `tests/portals/test_extension_bundle.py`:

```python


def test_the_registration_check_survives_the_worker_being_unloaded() -> None:
    """The dock asks about the registration email minutes later. A service
    worker is unloaded when idle, so the wait must be a chrome.alarms alarm --
    declared in the manifest -- and never a timer that dies with the worker."""
    manifest = json.loads(bundle_text("manifest.json"))
    worker = bundle_text("service_worker.js")
    assert "alarms" in manifest["permissions"]
    assert "alarms.create" in worker and "onAlarm" in worker
    assert "/registration" in worker and "/ext/mailbox/check" in worker


def test_the_address_report_uses_only_the_server_s_evidence_words() -> None:
    """ext_api refuses an evidence word it does not know with a 400 the student
    never sees. Pin the extension's words to the server's."""
    from apps.portals.ext_api import _REJECTION_EVIDENCE

    content = bundle_text("content.js")
    for evidence in _REJECTION_EVIDENCE:
        assert f'"{evidence}"' in content, f"the content script never reports {evidence}"
```

- [ ] **Step 2: Run to verify failure**

Run: `npm --prefix extension run check && POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_bundle.py -q && POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_e2e.py -m extension -q`
Expected: FAIL — `KeyError: 'permissions'`-free assertion `'alarms' in [...]` fails; the panel tests time out waiting for `#registration` / `#use-plain`.

- [ ] **Step 3: Manifest, API and types**

In `extension/manifest.json` change the permissions line to:

```json
  "permissions": ["storage", "scripting", "activeTab", "sidePanel", "alarms"],
```

In `extension/src/types.ts`, at the end of `DockState` (after `message: string;`) add:

```ts
  /** The registration-mail question (spec §2a), or null when nothing is asked.
   *  Set by the service worker when the server says the mailbox has not
   *  answered; cleared when the student answers. */
  registration: { applicationId: string; portalHost: string; address: string } | null;
```

Append to `extension/src/api.ts`:

```ts

/** What the content script saw when it typed the portal address. */
export async function postAddress(
  origin: string,
  applicationId: string,
  report: { event: string; evidence?: string },
): Promise<{ address: string; awaiting_mail: boolean; ask_after_seconds: number }> {
  return (await call(origin, `/ext/applications/${applicationId}/address`, {
    method: "POST",
    body: JSON.stringify(report),
  })) as { address: string; awaiting_mail: boolean; ask_after_seconds: number };
}

export async function checkMailbox(origin: string): Promise<void> {
  await call(origin, "/ext/mailbox/check", { method: "POST" });
}

export async function fetchRegistration(
  origin: string,
  applicationId: string,
): Promise<{ state: string; portal_host?: string; address?: string }> {
  return (await call(origin, `/ext/applications/${applicationId}/registration`)) as {
    state: string;
    portal_host?: string;
    address?: string;
  };
}

export async function postRegistrationAnswer(
  origin: string,
  applicationId: string,
  answer: { arrived: string; sender: string },
): Promise<{ learned: boolean }> {
  return (await call(origin, `/ext/applications/${applicationId}/registration`, {
    method: "POST",
    body: JSON.stringify(answer),
  })) as { learned: boolean };
}
```

- [ ] **Step 4: The service worker**

In `extension/src/service_worker.ts`, add `checkMailbox`, `fetchRegistration`, `postAddress`, `postRegistrationAnswer` to the `import {…} from "./api.js"` list (alphabetical, as the list is), and after that import add:

```ts

/** One alarm per registration being watched. An alarm, not setTimeout: the
 *  worker is unloaded when idle and a timer would die with it. */
const REGISTRATION_ALARM = "registration:";
```

Inside THE message listener, directly before `  if (message?.type === "dock") {`, add:

```ts
  if (message?.type === "address") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      try {
        const answer = await postAddress(origin, message.applicationId, {
          event: message.event,
          ...(message.evidence ? { evidence: message.evidence } : {}),
        });
        if (message.event === "rejected") {
          // The cached packet still carries the tagged address; the server's
          // next one carries the plain address, so fetch that one next time.
          await chrome.storage.session.remove(`packet:${message.applicationId}`);
        }
        if (answer.awaiting_mail) {
          await chrome.alarms.create(`${REGISTRATION_ALARM}${message.applicationId}`, {
            delayInMinutes: Math.max(answer.ask_after_seconds / 60, 0.5),
          });
        }
        sendResponse({ ok: true });
      } catch (error) {
        sendResponse({ ok: false, code: error instanceof ExtError ? error.code : "request_failed" });
      }
    })();
    return true;
  }
  if (message?.type === "registration:answer") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      try {
        const result = await postRegistrationAnswer(origin, message.applicationId, {
          arrived: message.arrived,
          sender: message.sender ?? "",
        });
        const thanks: Record<string, string> = {
          tagged: "Thanks. This portal keeps your tagged address.",
          plain: result.learned
            ? "Thanks. We will recognise this portal's email from now on."
            : "Thanks. We cannot watch mail from that sender, so check that inbox yourself.",
          none: "Thanks. If it arrives later, we will still look for it.",
        };
        await patchDock({ registration: null, message: thanks[message.arrived] ?? "Thanks." });
        sendResponse({ ok: true });
      } catch (error) {
        const code = error instanceof ExtError ? error.code : "request_failed";
        await patchDock({
          message:
            code === "invalid_sender"
              ? "That does not look like an email address. Copy the sender from the email."
              : "We could not save your answer. Try again in a minute.",
        });
        sendResponse({ ok: false, code });
      }
    })();
    return true;
  }
```

Append at the end of the file:

```ts

/**
 * The registration-mail expectation's one check (spec §2a).
 *
 * Asks the server to read the mailbox now, then whether the portal's first
 * email has answered the tag question. If not, the dock asks the student --
 * who is most likely still at the portal. Nothing here repeats: the student
 * answers once, and the mailbox sweep may still settle it on its own.
 */
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm.name.startsWith(REGISTRATION_ALARM)) return;
  const applicationId = alarm.name.slice(REGISTRATION_ALARM.length);
  const origin = await dashboardOrigin();
  if (!origin) return;
  try {
    await checkMailbox(origin);
  } catch (error) {
    if (error instanceof ExtError && error.code === "mailbox_disconnected") {
      await patchDock({
        message: "Your mailbox connection stopped working. Reconnect it on your dashboard.",
      });
    }
    // rate_limited or a network blip: ask the student anyway, below.
  }
  try {
    const registration = await fetchRegistration(origin, applicationId);
    if (registration.state === "ask") {
      await patchDock({
        registration: {
          applicationId,
          portalHost: registration.portal_host ?? "",
          address: registration.address ?? "",
        },
      });
    }
  } catch {
    // Nothing to ask with; the tag status stays unmeasured, the safe default.
  }
});
```

- [ ] **Step 5: The dock**

In `extension/src/panel/panel.html`, replace

```html
      <section><h2>Check these</h2><ul id="mismatches"></ul></section>
      <button id="unpair" type="button">Disconnect this browser</button>
```

with

```html
      <section><h2>Check these</h2><ul id="mismatches"></ul></section>
      <section id="registration" hidden>
        <h2 id="registration-question"></h2>
        <p>Open the email and look at the address it was sent to.</p>
        <button id="arrived-tagged" type="button"></button>
        <label for="sender">Who sent it?</label>
        <input id="sender" type="email" placeholder="noreply@example.org" />
        <button id="arrived-plain" type="button">It went to my address without the + part</button>
        <button id="arrived-none" type="button">No email came</button>
      </section>
      <button id="use-plain" type="button">Use my plain address</button>
      <button id="unpair" type="button">Disconnect this browser</button>
```

In `extension/src/panel/panel.ts`: add `registration: null,` after `message: "",` in `EMPTY`. At the end of `render()` (after the `list("mismatches", …)` call) add:

```ts
  const registration = document.getElementById("registration");
  if (registration) registration.hidden = state.registration === null;
  const question = document.getElementById("registration-question");
  if (question && state.registration) {
    question.textContent = `Did ${state.registration.portalHost} send you an email?`;
  }
  const tagged = document.getElementById("arrived-tagged");
  if (tagged && state.registration) tagged.textContent = `It went to ${state.registration.address}`;
```

and directly after `render()` add:

```ts

/** The student's answer to the registration-mail question. Theirs to give:
 *  the sender they type is what makes it confirmed (spec §3 rule 2). */
function answer(arrived: "tagged" | "plain" | "none"): void {
  if (!state.registration) return;
  const sender = (document.getElementById("sender") as HTMLInputElement | null)?.value ?? "";
  void chrome.runtime.sendMessage({
    type: "registration:answer",
    applicationId: state.registration.applicationId,
    arrived,
    sender: arrived === "plain" ? sender.trim() : "",
  });
}
```

Replace the closing block

```ts
// The one button in this extension, and it only ever removes something. It is
// not a page control: dispatching a click is forbidden in the content script,
// while a button the STUDENT presses in our own side panel is the opposite
// thing -- their act, on their own installation.
document.getElementById("unpair")?.addEventListener("click", () => {
  void chrome.runtime.sendMessage({ type: "unpair" });
});
```

with

```ts
// The dock's buttons. None is a page control: dispatching a click is
// forbidden in the content script, while a button the STUDENT presses in our
// own side panel is the opposite thing -- their act, on their own installation.
document.getElementById("unpair")?.addEventListener("click", () => {
  void chrome.runtime.sendMessage({ type: "unpair" });
});
document.getElementById("arrived-tagged")?.addEventListener("click", () => answer("tagged"));
document.getElementById("arrived-plain")?.addEventListener("click", () => answer("plain"));
document.getElementById("arrived-none")?.addEventListener("click", () => answer("none"));
// For a refusal the extension could not read. Straight to the portal tab's
// content script, which holds the control it filled (content/index.ts).
document.getElementById("use-plain")?.addEventListener("click", () => {
  void (async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id === undefined) return;
    await chrome.tabs.sendMessage(tab.id, { type: "use_plain_address" }).catch(() => {});
  })();
});
```

(`chrome.tabs.query` returns a tab's `id` without the `tabs` permission; only `url`/`title` need it, and asking for it would let us read every URL the student visits — see the comment in `service_worker.ts`'s `onActivated` listener.)

- [ ] **Step 6: Run to verify pass**

Run: `npm --prefix extension run check && POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_bundle.py -q && POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_e2e.py -m extension -q`
Expected: all PASS (38 across both files at the time of writing). The worker itself cannot be driven from pytest — the bundle checks are the evidence for it, as they already are for `/ext/actions`.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add extension/manifest.json extension/src/api.ts extension/src/service_worker.ts extension/src/types.ts extension/src/panel/panel.html extension/src/panel/panel.ts tests/portals/test_extension_e2e.py tests/portals/test_extension_bundle.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(extension): ask about the registration email in the dock; a plain-address button

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Prove it behind the production role, and verify the branch

**Files:**
- Test: `tests/portals/test_ext_rls.py`, `tests/mailbox/test_tagged_rls.py`

**Interfaces:**
- Consumes: everything above; the `rls_enforced_orm` fixture (`tests/conftest.py`); `test_ext_rls.py`'s `_paired` and `application_a_with_email`.
- Produces: nothing new — evidence.

- [ ] **Step 1: Write the RLS tests**

Append to `tests/portals/test_ext_rls.py`:

```python


def test_the_address_and_registration_reports_write_behind_the_policy(
    agency_a,
    domain_a,
    membership_a,
    user_a,
    application_a_with_email,
    client,
    rls_enforced_orm,
    monkeypatch,
) -> None:
    """RED if any write of plan 3's two device routes escapes its
    tenant_transaction: registered_at, the SIGNUP step, the account's
    tag_outcome, the AuditEvent naming who measured the portal, or the
    confirmed LearnedSender would be refused by the policy."""
    from apps.funding.models import AuditEvent
    from apps.mailbox.models import LearnedSender
    from apps.portals import packets
    from apps.portals.models import ApplicationStep, PortalAccount
    from apps.tenancy.db import tenant_transaction

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    token = _paired(client, user_a, domain_a)
    auth = {"HTTP_HOST": domain_a.host, "HTTP_AUTHORIZATION": f"Bearer {token}"}
    base = f"/ext/applications/{application_a_with_email.id}"
    assert client.get(f"{base}/packet", **auth).status_code == 200

    given = client.post(
        f"{base}/address",
        data=json.dumps({"event": "given"}),
        content_type="application/json",
        **auth,
    )
    answered = client.post(
        f"{base}/registration",
        data=json.dumps({"arrived": "plain", "sender": "no-reply@mail-eu.portalvendor.com"}),
        content_type="application/json",
        **auth,
    )

    assert given.status_code == 200, given.content
    assert given.json()["awaiting_mail"] is True
    assert answered.json() == {"learned": True}
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = PortalAccount.objects.get(student=membership_a)
        assert account.registered_at is not None
        assert account.tag_outcome == "STRIPS"
        assert ApplicationStep.objects.filter(kind="SIGNUP").count() == 1
        assert AuditEvent.objects.filter(event="portal.tag_status_set").count() == 1
        assert LearnedSender.objects.get(student=membership_a).confirmed_at is not None
```

Append to `tests/mailbox/test_tagged_rls.py`:

```python


def test_the_mail_measures_the_tag_behind_the_policy(
    connection_with_pack, monkeypatch, rls_enforced_orm
) -> None:
    """RED if sync's registration reads or tag writes escape their
    tenant_transaction: _awaiting_registration would see no account under the
    policy and the STRIPS measurement would silently never happen."""
    from django.utils import timezone

    from apps.funding.models import AuditEvent
    from apps.mailbox import sync as sync_module
    from apps.portals.models import PortalForm

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=TAGGED,
            registered_at=timezone.now(),
        )
    header = MessageHeader(
        message_id="m-strip",
        sender="noreply@uni-bonn.de",
        received_at=timezone.now(),
        recipients=("student@gmail.test",),
    )

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider((header,)), secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        account = PortalAccount.objects.get(student=connection.membership)
        audited = AuditEvent.objects.filter(event="portal.tag_status_set").count()
    assert account.tag_outcome == "STRIPS"
    assert audited == 1
    assert PortalForm.objects.get(portal_host="portal.uni-bonn.de").tag_status == "STRIPS"
```

- [ ] **Step 2: Run, then prove the RLS test can fail**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_ext_rls.py tests/mailbox/test_tagged_rls.py -q`
Expected: PASS.

Negative control (do not commit it): in `apps/mailbox/sync.py` dedent the line `awaiting = _awaiting_registration(connection.membership, timezone.now())` by one level so it runs outside the `with tenant_transaction(...)` block, rerun `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox/test_tagged_rls.py tests/mailbox/test_registration_mail.py -q`, and confirm exactly `test_the_mail_measures_the_tag_behind_the_policy` FAILS while `test_registration_mail.py` still passes (the superuser suite cannot see it — measured while writing this plan). Restore the line; `git -C /home/orkhan/Desktop/mailbox-port diff apps/mailbox/sync.py` must show nothing from this step.

- [ ] **Step 3: Whole-branch gates**

Run:

```bash
cd /home/orkhan/Desktop/mailbox-port
POSTGRES_DB=tehsil_mailbox_port uv run pytest -q
POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_extension_e2e.py -m extension -q
uv run ruff check .
uv run mypy apps config
uv run bandit -q -c pyproject.toml -r apps config
POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=tehsil_mailbox_port uv run python manage.py check
npm --prefix extension run check
grep -rn "SUBMITTED" apps/portals --include=*.py | grep -v -e "ext_api.py" -e "models.py" -e "/migrations/"
```

Expected: every suite passes with 0 failures; ruff "All checks passed!"; mypy "Success"; bandit prints no issue (its "Test in comment" warnings are pre-existing noise); "No changes detected"; "System check identified no issues"; the extension builds; the final `grep` prints nothing.

- [ ] **Step 4: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add tests/portals/test_ext_rls.py tests/mailbox/test_tagged_rls.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "test(portals, mailbox): tag measurement and the registration answer behind NOBYPASSRLS

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review notes (for the controller)

- Every snippet in Tasks 1–8 was applied to a scratch export of `claude/mailbox-port` at `2dc6e940` and run there: the new Python tests, `tests/portals`, `tests/mailbox`, `tests/watch`, `tests/audit`, the extension typecheck/build, the bundle tests and all `-m extension` e2e tests passed; ruff, mypy (`apps config`) and bandit were clean; `makemigrations --check` reported no changes; the Task 8 negative control failed exactly as stated.
- Spec coverage: §2a rejects (Tasks 2, 6, 7), after-Submit rejection (Task 6), the dock button (Tasks 2, 6, 7), strips at registration (Tasks 2, 3, 4, 7), where the status lives and who moves it (Task 1), the packet/kit half (Task 2 — plan 2's `portal_address` did hand out the plain address on a shared REJECTS, but also re-based registered accounts and used the current `application_email`; both fixed in Task 1), `contact.email` learning (Task 5). "Tags are personal data" — the two new fields are classified in Task 1; `tag`/`address` were already redacted.
