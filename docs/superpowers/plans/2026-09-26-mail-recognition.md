# Mail Recognition (plan 2 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognise every email that belongs to a student's applications — by the tagged address a portal was given, by the institution's main domain, or by a sender learned from tagged mail — act only on mail whose sender is proven, and turn what a message says into an alert the student sees.

**Architecture:** Server-side only. `apps/portals` gains a per-portal tag status and a `PortalAccount` (one tagged address per student per portal host) that the fill packet and the kit hand out. `apps/mailbox` matches senders on registrable domains, reads mail sent to a tag (including Junk), learns a sender from tagged mail per student, distinguishes an everyday inbox from an application inbox, retries failed classifications, and raises label alerts. The extension can ask for an immediate check. `apps/watch` alerts on a mailbox that stopped being checked.

**Tech Stack:** Django 5.2, PostgreSQL 17 with row-level security, Microsoft Graph, pytest + pytest-django, `tldextract` (already a dependency, offline snapshot via `apps/research/hosts.py`), uv.

**Spec:** `docs/superpowers/specs/2026-09-25-application-watch-design.md` — §2 (how information arrives), §2a (tag outcomes — the status field only; detection is plan 3), §3 (which mail is read), §4 (alerts), §5 (mailbox health), "Data it needs", "Fixes this requires in the mailbox code as built", and the owner decision of 2026-09-26 (no Gmail in the pilot).

**Not in this plan, on purpose:**
- Plan 3: the extension noticing a rejected `+` address and swapping to the plain one, the ~30-minute registration-mail expectation, the dock prompts, the one-time delivery test (it needs an outbound sending domain, which does not exist — `REMINDER_EMAIL_FROM` is empty), and the snapshot vocabulary learning the `contact.email` field.
- The mailbox sweep's EventBridge schedule: the worker task definition carries no Microsoft OAuth client credentials yet. Its rule, and `sync_mailboxes` joining `EXPECTED_JOBS`, ship when those credentials do.
- Gmail changes beyond reading the `To` header: Gmail is not offered in the pilot.
- Microsoft sender authentication through `internetMessageHeaders`: unmeasured; tagged mail acts without it.

## Global Constraints

- Work in `/home/orkhan/Desktop/mailbox-port`, branch `claude/mailbox-port`. Always `git -C /home/orkhan/Desktop/mailbox-port …`; the shell's cwd resets to the main repo and a bare `git commit` lands on the wrong branch.
- Test DB: prefix every pytest/manage.py command with `POSTGRES_DB=tehsil_mailbox_port`.
- Lint `uv run ruff check .` only — **never `ruff format`**. Types `uv run mypy apps config`. Security `uv run bandit -q -c pyproject.toml -r apps config`. Migrations `POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations --check --dry-run`. Line length 100.
- Every tenant-scoped query outside a request runs inside `tenant_scope` **and** `tenant_transaction`. A test under `rls_enforced_orm` with `@pytest.mark.django_db(transaction=True)` is the only proof a path works as the production NOBYPASSRLS role.
- Every new tenant table: `ENABLE` + `FORCE ROW LEVEL SECURITY`, the `tenant_isolation` policy, and a composite `(tenant_id, <fk>_id)` foreign key to each tenant-scoped parent, in its migration. Pattern: `apps/watch/migrations/0001_initial.py`.
- Every field of a model FK-reachable from `Membership` is classified in `apps/audit/redaction.py`.
- `apps/portals/` modules other than `ext_api.py` and `models.py` must not contain the string `SUBMITTED`.
- Logs carry ids, portal hosts and sender domains only — never an email address, a tag, a subject or body text.
- **Reading is broader than acting.** A message may be read and shown when it matches a rule; a link is opened or an application's state moved only when the message is *trusted*: sent to a tagged address and not from Junk, or authenticated by the provider from a sender that is not an unconfirmed learned one.
- A learned sender is per student, never written to the shared `PortalForm.sender_domains`.
- Commits end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

## Review Focus

1. **A leaked tag used by a scammer's own domain.** Expected: the mail is read and its domain learned unconfirmed; its link to its own domain is refused, because the link allowlist leaves out unconfirmed learned domains. Pinned in Task 5 (`test_a_leaked_tag_cannot_open_a_link_off_the_allowlist`).
2. **Junk mail that is not tagged.** Expected: never listed as a signal. Pinned in Task 5.
3. **Two applications on the same portal host** (one Swedish account, several programmes). Expected: one `PortalAccount`, one address; tagged mail is attributed to no single application and the card asks. Pinned in Tasks 2 and 5.
4. **A portal that rejects tags after an account was already issued a tagged address.** Expected: the next packet and kit hand out the plain address. Pinned in Task 2.
5. **The mailbox sweep not running at all.** Expected: no per-student "inbox not checked" alerts (the job-silence alarm owns that). Pinned in Task 9.

---

### Task 1: Bring master in

Master moved ahead while this branch was built and added `apps/concierge/migrations/0007_documentversion_kind.py`, the same number as this branch's `0007_notification_urgent_escalation.py`. Nothing is deployed, so renumbering ours is safe.

**Files:**
- Modify: `apps/concierge/migrations/0007_notification_urgent_escalation.py` → rename to `0008_notification_urgent_escalation.py`
- Modify: `apps/watch/migrations/0001_initial.py` (dependency name)
- Resolve: any textual conflicts in `apps/audit/redaction.py`, `infra/template.yaml`

- [ ] **Step 1: Merge**

```bash
git -C /home/orkhan/Desktop/mailbox-port fetch origin
git -C /home/orkhan/Desktop/mailbox-port merge origin/master
```

Resolve conflicts by keeping both sides' additions (they touch different resources and different redaction entries). Do not drop anything from either side.

- [ ] **Step 2: Renumber the migration**

```bash
cd /home/orkhan/Desktop/mailbox-port
git mv apps/concierge/migrations/0007_notification_urgent_escalation.py apps/concierge/migrations/0008_notification_urgent_escalation.py
```

In the renamed file set its `dependencies` to `[("concierge", "0007_documentversion_kind")]` (keep any other non-concierge dependency it had). In `apps/watch/migrations/0001_initial.py` change `("concierge", "0007_notification_urgent_escalation")` to `("concierge", "0008_notification_urgent_escalation")`. Search for any other reference: `grep -rn "0007_notification_urgent_escalation" apps tests` → expected no output.

- [ ] **Step 3: Verify**

Run:
```bash
POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=tehsil_mailbox_port uv run pytest -q
uv run ruff check . && uv run mypy apps config
```
Expected: "No changes detected"; the full suite passes (baseline on this branch 4014 passed plus whatever master added); lint and types clean. If `makemigrations --check` reports a conflict in another app, add a Django merge migration (`makemigrations --merge`) and say so in the report.

- [ ] **Step 4: Commit** (the merge commit already exists if there were no conflicts; commit the renumbering)

```bash
git -C /home/orkhan/Desktop/mailbox-port add -A apps/concierge/migrations apps/watch/migrations
git -C /home/orkhan/Desktop/mailbox-port commit -m "chore(migrations): renumber the notification migration after master's concierge 0007

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Match senders on the main domain

**Files:**
- Modify: `apps/mailbox/filter.py`
- Modify: `tests/mailbox/test_filter.py`, `tests/mailbox/test_sync.py` (expected sets), `tests/mailbox/conftest.py` (docstring only)

**Interfaces:**
- Produces: `filter.sender_key(sender: str) -> str` — the allowlist key for a `From` value: its registrable domain, or its full host on a shared platform, or `""`. `allowed_senders` keys become the same keys.

- [ ] **Step 1: Write the failing tests**

Append to `tests/mailbox/test_filter.py`:

```python
@pytest.mark.django_db
def test_a_www_evidence_link_still_allowlists_the_institution(agency_a, membership_a):
    """A pack link to www.tum.de kept "www.tum.de", and mail from tum.de never matched."""
    from apps.mailbox.filter import _key

    assert _key("www.tum.de") == "tum.de"
    assert matched_domain("Admissions <admissions@tum.de>", {"tum.de": None}) == "tum.de"
    assert matched_domain("x@mail.tum.de", {"tum.de": None}) == "tum.de"


def test_a_public_suffix_is_never_the_key():
    from apps.mailbox.filter import _key

    assert _key("ects.metu.edu.tr") == "metu.edu.tr"
    assert _key("www.ox.ac.uk") == "ox.ac.uk"


def test_a_shared_platform_keeps_the_full_host():
    """dreamapply.com hosts many universities; its registrable domain names the vendor."""
    from apps.mailbox.filter import _key

    assert _key("tum.dreamapply.com") == "tum.dreamapply.com"


def test_sender_key_reads_the_address_host():
    from apps.mailbox.filter import sender_key

    assert sender_key("Office <noreply@campus.uni-bonn.de>") == "uni-bonn.de"
    assert sender_key("no-at-sign") == ""
```

Change the existing expectation in `test_the_allowlist_is_the_student_s_own_pack_and_portals` from `{"tum.de", "daad.de", "portal.uni-bonn.de"}` to `{"tum.de", "daad.de", "uni-bonn.de"}`, and its `allowed_senders(student)["portal.uni-bonn.de"]` to `allowed_senders(student)["uni-bonn.de"]`. In `tests/mailbox/test_sync.py::test_gmail_content_tier_asks_only_for_pack_senders` change `"portal.uni-bonn.de"` to `"uni-bonn.de"`.

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox/test_filter.py -q`
Expected: FAIL — `ImportError: cannot import name '_key'`.

- [ ] **Step 3: Implement**

In `apps/mailbox/filter.py` add the import `from apps.research.hosts import registrable_domain` and, after `_host_of`:

```python
#: Hosts shared by many institutions: their registrable domain names the vendor,
#: so keying on it would read every customer's mail as this student's. Keep the
#: full host for these. Extend when a new multi-tenant portal vendor appears.
_SHARED_PLATFORMS = frozenset({"dreamapply.com"})


def _key(host: str) -> str:
    """The allowlist key for a host: its registrable domain, "" if none.

    A pack link to www.tum.de must allowlist mail from tum.de and mail.tum.de,
    which suffix matching on the full host never did. The registrable domain,
    from the Public Suffix List snapshot, is what the institution owns:
    metu.edu.tr, never edu.tr.
    """
    host = host.strip().casefold().rstrip(".")
    if not _usable(host):
        return ""
    domain = registrable_domain(host)
    if not domain:
        return ""
    return host if domain in _SHARED_PLATFORMS else domain


def sender_key(sender: str) -> str:
    """The allowlist key for a From value, or ""."""
    return _key(sender_domain(sender))
```

In `allowed_senders` replace `if _usable(host := _host_of(url)):` with `if host := _key(_host_of(url)):` and, in the portal loop, `if not _usable(host := str(entry).casefold()):` with `if not (host := _key(str(entry))):`. `matched_domain` and `host_in` are unchanged: suffix matching against a registrable key already covers every subdomain.

Update the `student_with_pack` docstring in `tests/mailbox/conftest.py` to say the portal allowlists as `uni-bonn.de`.

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/mailbox/filter.py tests/mailbox
git -C /home/orkhan/Desktop/mailbox-port commit -m "fix(mailbox): match senders on the institution's registrable domain

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Tag status, portal accounts, and the tagged address in packet and kit

**Files:**
- Modify: `apps/portals/models.py` (`PortalForm.TagStatus`, `PortalForm.tag_status`; new `PortalAccount`)
- Create: `apps/portals/tags.py`
- Create: `apps/portals/migrations/0018_portal_accounts.py` (generated, then edited; if Task 1 left a later portals leaf, depend on it)
- Modify: `apps/portals/packets.py` (`mint_packet`, `build_kit`)
- Modify: `apps/audit/redaction.py`
- Test: `tests/portals/test_tags.py`

**Interfaces:**
- Produces: `PortalForm.TagStatus` (`UNKNOWN`, `KEEPS`, `REJECTS`, `STRIPS`), `PortalForm.tag_status` (default `UNKNOWN`); `PortalAccount` (`tenant`, `student`, `portal_host`, `tag`, `address`, `created_at`; unique per student and host); `tags.tagged(address: str, tag: str) -> str`; `tags.portal_address(application: Application) -> str` (must run inside a tenant transaction; creates the account on first use). The packet fills profile field **`contact.email`** from it; the kit's `apply_with_email` shows it.

- [ ] **Step 1: Write the failing tests**

`tests/portals/test_tags.py`:

```python
"""One tagged address per student per portal host, handed out by packet and kit."""

import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.portals.test_kit import _application

pytestmark = pytest.mark.django_db

EMAIL_ENTRY = {
    "profile_field": "contact.email",
    "action": {
        "selector": "#email",
        "description": "Email",
        "method": "fill",
        "arguments": ["%value%"],
    },
}


@pytest.fixture
def with_address(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])


def test_tagged_puts_the_tag_before_the_at_sign():
    from apps.portals.tags import tagged

    assert tagged("leyla@outlook.com", "ab12cd") == "leyla+ab12cd@outlook.com"


@pytest.mark.parametrize("address", ["leyla+x@outlook.com", "no-at-sign", "@outlook.com"])
def test_an_address_that_cannot_take_a_tag_is_returned_unchanged(address):
    from apps.portals.tags import tagged

    assert tagged(address, "ab12cd") == address


def test_one_portal_host_gets_one_address(agency_a, membership_a, with_address):
    from apps.portals.models import Application, PortalAccount
    from apps.portals.tags import portal_address

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        first = _application(agency_a, membership_a)
        second = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=first.program_id,
            portal_form=first.portal_form,
        )
        a, b = portal_address(first), portal_address(second)
        assert PortalAccount.objects.filter(student=membership_a).count() == 1

    assert a == b
    local, _, domain = a.partition("@")
    assert domain == "outlook.com"
    assert local.startswith("leyla.apply+") and len(local) == len("leyla.apply+") + 6


def test_a_portal_that_rejects_tags_gets_the_plain_address(agency_a, membership_a, with_address):
    from apps.portals.models import PortalForm
    from apps.portals.tags import portal_address

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        application = _application(agency_a, membership_a)
        issued = portal_address(application)
        PortalForm.objects.filter(pk=application.portal_form_id).update(
            tag_status=PortalForm.TagStatus.REJECTS
        )
        application.portal_form.refresh_from_db()
        assert "+" in issued
        assert portal_address(application) == "leyla.apply@outlook.com"


def test_no_application_email_means_no_address(agency_a, membership_a):
    from apps.portals.tags import portal_address

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert portal_address(_application(agency_a, membership_a)) == ""


def test_the_packet_fills_the_email_field_with_the_tagged_address(
    agency_a, membership_a, with_address, monkeypatch
):
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=[EMAIL_ENTRY])
        packet = packets.mint_packet(application)

    [entry] = packet.entries
    assert entry.profile_field == "contact.email"
    assert entry.value.startswith("leyla.apply+") and entry.value.endswith("@outlook.com")


def test_the_kit_shows_the_tagged_address(agency_a, membership_a, with_address, monkeypatch):
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        kit = packets.build_kit(_application(agency_a, membership_a))

    assert kit.apply_with_email.startswith("leyla.apply+")
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_tags.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.portals.tags'`.

- [ ] **Step 3: Add the models**

In `apps/portals/models.py`, class `PortalForm`, add:

```python
    class TagStatus(models.TextChoices):
        """Whether this portal keeps a +tag in the address it mails (spec §2a).

        Shared by every tenant, unlike a learned sender: a wrong status can only
        cause the safe fallback (the plain address and sender matching), never an
        action.
        """

        UNKNOWN = "UNKNOWN", "Not yet measured"
        KEEPS = "KEEPS", "Keeps the tag"
        REJECTS = "REJECTS", "Rejects + at the form"
        STRIPS = "STRIPS", "Accepts but mails the plain address"

    tag_status = models.CharField(
        max_length=10, choices=TagStatus.choices, default=TagStatus.UNKNOWN
    )
```

and after `Application`:

```python
class PortalAccount(TenantScopedModel):
    """The address one student registered with on one portal host.

    Per host, not per application: one Swedish or uni-assist account holds many
    applications. `address` is fixed when first issued, because it is what the
    portal now holds -- a later change of inbox does not change it.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="portal_accounts"
    )
    portal_host = models.CharField(max_length=253)
    #: Random, lowercase letters and digits. Only this portal is given it.
    tag = models.CharField(max_length=16)
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

- [ ] **Step 4: Migration with the SQL Django cannot write**

Run `POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations portals --name portal_accounts`. Then add, following `apps/watch/migrations/0001_initial.py`: `ENABLE` + `FORCE ROW LEVEL SECURITY` and the `tenant_isolation` policy on `portals_portalaccount`, and

```sql
ALTER TABLE portals_portalaccount
    ADD CONSTRAINT portalaccount_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
```

with its reverse. Drop any spurious later `tenancy` dependency makemigrations adds (see the note in `apps/portals/migrations/0014_reminder_ladder.py`).

- [ ] **Step 5: The address helper**

`apps/portals/tags.py`:

```python
"""One tagged address per student per portal host (spec §2, §2a).

`name+tag@domain` reaches the same inbox, and only the portal it was given to
knows it, so mail sent to it names the portal and is strong evidence it came
from there.
"""

from __future__ import annotations

import secrets
import string

from .models import Application, PortalAccount, PortalForm

_TAG_ALPHABET = string.ascii_lowercase + string.digits
_TAG_LENGTH = 6


def _new_tag() -> str:
    return "".join(secrets.choice(_TAG_ALPHABET) for _ in range(_TAG_LENGTH))


def tagged(address: str, tag: str) -> str:
    """`local+tag@domain`, or the address unchanged when it cannot take a tag."""
    local, at, domain = address.rpartition("@")
    if not at or not local or not domain or "+" in local:
        return address
    return f"{local}+{tag}@{domain}"


def portal_address(application: Application) -> str:
    """The address this student uses on this application's portal, or "".

    Run inside a tenant transaction: it creates the account on first use.
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
    rejects = form.tag_status == PortalForm.TagStatus.REJECTS
    if not account.address or (rejects and account.address != base):
        account.address = base if rejects else tagged(base, account.tag)
        account.save(update_fields=["address"])
    return account.address
```

- [ ] **Step 6: Use it in the packet and the kit**

In `apps/portals/packets.py` import `from .tags import portal_address`. In `mint_packet`, inside the existing `with tenant_transaction(application.tenant_id):` block, after `values = verified_values(application.student)`:

```python
        # Not a verified fact: the address the student applies with on THIS
        # portal, tagged where the portal keeps tags (spec §2a).
        if address := portal_address(application):
            values = {**values, "contact.email": address}
```

In `build_kit`, replace `apply_with_email = application.student.application_email` with

```python
        apply_with_email = portal_address(application) or application.student.application_email
```

- [ ] **Step 7: Classify for erasure**

`apps/audit/redaction.py`: add to `REDACT`

```python
    # The tagged address carries the student's own address; the tag alone names
    # their account on one portal.
    "portals.PortalAccount": RedactSpec("student_id", ("tag", "address")),
```

and to `KEEP` `"portals.PortalAccount": ("portal_host", "created_at"),`.

- [ ] **Step 8: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals tests/audit tests/tenancy/test_database_isolation.py -q`
Expected: all PASS (including `test_nothing_in_the_app_can_submit` — `tags.py` never names that state).

- [ ] **Step 9: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/portals apps/audit/redaction.py tests/portals/test_tags.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(portals): one tagged address per portal account, filled by the packet

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Recipients and Junk in the listing

**Files:**
- Modify: `apps/mailbox/providers.py` (`MessageHeader`, `MicrosoftMailbox.list_headers`, `_graph_headers`, `_google_header`)
- Test: `tests/mailbox/test_providers.py`

**Interfaces:**
- Produces: `MessageHeader.recipients: tuple[str, ...] = ()` (lowercased `To` addresses) and `MessageHeader.junk: bool = False`. `MicrosoftMailbox.list_headers` lists the inbox and then the Junk Email folder, marking Junk headers `junk=True`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/mailbox/test_providers.py`:

```python
_JUNK = "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages"


def _graph_message_to(message_id: str, to: str) -> dict[str, object]:
    return {
        **_graph_message(message_id),
        "toRecipients": [{"emailAddress": {"address": to}}],
    }


def test_microsoft_reports_recipients_lowercased():
    http = FakeHTTP(
        {
            f"{_GRAPH}?": {"value": [_graph_message_to("AAMk1", "Leyla+AB12cd@outlook.com")]},
            f"{_JUNK}?": {"value": []},
        }
    )

    [header] = MicrosoftMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert header.recipients == ("leyla+ab12cd@outlook.com",)
    assert header.junk is False
    assert "toRecipients" in http.requests[0][1]


def test_microsoft_also_lists_junk_and_marks_it():
    """Real portal mail sometimes lands in Junk; sync.py decides what is read from there."""
    http = FakeHTTP(
        {
            f"{_GRAPH}?": {"value": [_graph_message_to("AAMk1", "a@outlook.com")]},
            f"{_JUNK}?": {"value": [_graph_message_to("AAMk2", "b@outlook.com")]},
        }
    )

    headers = MicrosoftMailbox(http=http).list_headers(access_token="at", since=_LONG_AGO)

    assert [(h.message_id, h.junk) for h in headers] == [("AAMk1", False), ("AAMk2", True)]
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox/test_providers.py -q -k "recipients or junk"`
Expected: FAIL (`recipients` is not a field; Junk is not requested).

- [ ] **Step 3: Implement**

`MessageHeader`: add after `authenticated`:

```python
    #: The To addresses, lowercased. Used once to find a tag we issued, never
    #: stored.
    recipients: tuple[str, ...] = ()
    #: Listed from the provider's Junk folder. Only tagged mail is read from
    #: there, and it is never acted on (sync.py).
    junk: bool = False
```

`MicrosoftMailbox.list_headers`: add `toRecipients` to `$select` (`"id,from,receivedDateTime,toRecipients"`), move the existing paging loop into a private method `_list_folder(self, folder: str, query: str, access_token: str, *, junk: bool) -> list[MessageHeader]` that builds `f"{MICROSOFT_API_ORIGIN}/v1.0/me/mailFolders/{folder}/messages?{query}"`, keeps the origin check and the page ceiling log, and passes `junk` to `_graph_headers`. `list_headers` returns `tuple(self._list_folder("inbox", …, junk=False) + self._list_folder("junkemail", …, junk=True))`. Keep the existing comment about the inbox and add one line: Junk is listed separately and marked, so sync.py can read tagged mail from it and nothing else.

`_graph_headers(listing, *, junk: bool = False)`: read `toRecipients` into `recipients=tuple(address.casefold() for …)` (skip malformed entries) and set `junk=junk`.

`_google_header`: request `("metadataHeaders", "To")` in `GoogleMailbox.list_headers`'s metadata call, and parse the `To` header value with `email.utils.getaddresses([value])` into lowercased addresses. Gmail's Spam is not listed (Gmail is not offered in the pilot).

Update the existing Microsoft tests' fake maps so the Junk URL answers `{"value": []}` wherever a test lists headers (FakeHTTP returns 404 for an unknown prefix, which would raise `ProviderError`).

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/mailbox/providers.py tests/mailbox/test_providers.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(mailbox): list recipients, and Junk marked as Junk

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Read tagged mail, learn its sender, and decide trust

**Files:**
- Modify: `apps/mailbox/models.py` (new `LearnedSender`; `MailSignal.trusted`)
- Create: `apps/mailbox/migrations/0002_learned_senders.py` (generated, then edited)
- Modify: `apps/mailbox/filter.py` (`allowed_senders` includes learned senders; new `unconfirmed_senders`)
- Modify: `apps/mailbox/sync.py` (header loop)
- Modify: `apps/mailbox/views.py`, `apps/mailbox/urls.py` (student confirms a learned sender)
- Modify: `apps/audit/redaction.py`
- Test: `tests/mailbox/test_tagged.py`

**Interfaces:**
- Consumes: `PortalAccount` (Task 3), `MessageHeader.recipients`/`junk` (Task 4), `filter.sender_key` (Task 2).
- Produces: `LearnedSender` (`tenant`, `student`, `domain`, `portal_host`, `confirmed_at`, `created_at`; unique per student and domain); `MailSignal.trusted: bool`; `filter.unconfirmed_senders(student) -> set[str]`; route `POST mailbox/senders/<uuid:sender_id>/confirm` named `mailbox-confirm-sender`.

- [ ] **Step 1: Write the failing tests**

`tests/mailbox/test_tagged.py`:

```python
"""Mail sent to a tag we issued: read from any sender, learned, trusted only when clean."""

from datetime import UTC, datetime

import pytest

from apps.mailbox.classify import MailVerdict
from apps.mailbox.models import LearnedSender, MailSignal
from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import sync_connection
from apps.portals.models import DeviceAction, PortalAccount
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.mailbox.conftest import FakeProvider, _grant

pytestmark = pytest.mark.django_db
TAGGED = "student+ab12cd@gmail.test"


@pytest.fixture
def tagged_account(connection_with_pack):
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=TAGGED,
        )
    return connection


def _header(message_id, sender, *, to=TAGGED, junk=False):
    return MessageHeader(
        message_id=message_id,
        sender=sender,
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=(to,),
        junk=junk,
    )


def test_tagged_mail_from_an_unknown_vendor_is_read_and_its_sender_learned(tagged_account):
    connection = tagged_account
    provider = FakeProvider((_header("m1", "no-reply@mail-eu.portalvendor.com"),))

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(connection, provider=provider, secrets_client=_grant())
        learned = LearnedSender.objects.get(student=connection.membership)

    assert signal.sender_domain == "portalvendor.com"
    assert signal.trusted is True
    assert learned.domain == "portalvendor.com"
    assert learned.portal_host == "portal.uni-bonn.de"
    assert learned.confirmed_at is None


def test_untagged_junk_is_never_read(connection_with_pack):
    connection = connection_with_pack
    provider = FakeProvider((_header("m1", "a@tum.de", to="student@gmail.test", junk=True),))

    with tenant_scope(connection.tenant_id):
        assert sync_connection(connection, provider=provider, secrets_client=_grant()) == []


def test_tagged_junk_is_read_but_not_trusted(tagged_account):
    connection = tagged_account
    provider = FakeProvider((_header("m1", "a@uni-bonn.de", junk=True),))

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert signal.trusted is False


def test_a_leaked_tag_cannot_open_a_link_off_the_allowlist(tagged_account, monkeypatch):
    """A scammer who learned the tag mails it from their own domain with a link to it."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(
            label="VERIFICATION",
            action_kind="OPEN_VERIFICATION_URL",
            action_value="https://evil.example.org/verify",
        ),
    )
    connection = tagged_account
    provider = FakeProvider((_header("m1", "x@evil.example.org"),))

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())
        assert DeviceAction.objects.count() == 0


def test_mail_from_an_unconfirmed_learned_sender_is_read_but_not_trusted(tagged_account):
    connection = tagged_account
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        LearnedSender.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            domain="portalvendor.com",
            portal_host="portal.uni-bonn.de",
        )
    header = MessageHeader(
        message_id="m2",
        sender="no-reply@portalvendor.com",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(
            connection, provider=FakeProvider((header,)), secrets_client=_grant()
        )

    assert signal.trusted is False


def test_the_student_confirms_a_learned_sender(student_client, agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        learned = LearnedSender.objects.create(
            tenant=agency_a, student=membership_a, domain="portalvendor.com", portal_host="x"
        )

    response = student_client.post(f"/mailbox/senders/{learned.id}/confirm/")

    assert response.status_code == 200
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        learned.refresh_from_db()
    assert learned.confirmed_at is not None


def test_signals_stay_one_per_message(tagged_account):
    connection = tagged_account
    provider = FakeProvider((_header("m1", "a@uni-bonn.de"),))
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())
        assert MailSignal.objects.count() == 1
```

(`student_client` is an existing fixture in `tests/mailbox/conftest.py`; check how it sets the host header and use the same URL style as `tests/mailbox/test_views.py`. `FakeProvider` needs no change: the new header fields default.)

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox/test_tagged.py -q`
Expected: FAIL — `ImportError: cannot import name 'LearnedSender'`.

- [ ] **Step 3: Models and migration**

`apps/mailbox/models.py`:

```python
class LearnedSender(TenantScopedModel):
    """A sender domain first seen on mail to one of this student's tags.

    Per student and never shared: a tag can leak, and a scammer's domain learned
    from it must not become trusted for anyone else. Read from the moment it is
    learned; trusted only once the student confirms one message from it.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="learned_senders"
    )
    domain = models.CharField(max_length=253)
    #: The portal whose tag the first message was sent to.
    portal_host = models.CharField(max_length=253)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="learnedsender_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("student", "domain"), name="learnedsender_one_per_domain"
            ),
        ]
```

`MailSignal`: add `trusted = models.BooleanField(default=False)` with a comment: whether this message may act (spec §3, acting is stricter than reading); kept so a later retry of its classification acts under the same rule.

Run `makemigrations mailbox --name learned_senders`; add RLS (`ENABLE` + `FORCE`, `tenant_isolation`) on `mailbox_learnedsender` and the composite FK `learnedsender_student_tenant_fk` `(tenant_id, student_id) → tenancy_membership (tenant_id, id)`, with reverses.

`apps/audit/redaction.py`: `REDACT` `"mailbox.LearnedSender": RedactSpec("student_id", ("domain", "portal_host"))`; `KEEP` `"mailbox.LearnedSender": ("confirmed_at", "created_at")`; add `"trusted"` to the `"mailbox.MailSignal"` KEEP tuple.

- [ ] **Step 4: Filter**

In `apps/mailbox/filter.py`, at the end of `allowed_senders` before `return senders`:

```python
    # Learned from mail to this student's own tags (sync.py). Read, but not
    # trusted until confirmed -- unconfirmed_senders says which.
    for domain in LearnedSender.objects.filter(student=student).values_list("domain", flat=True):
        senders.setdefault(domain, None)
```

and add:

```python
def unconfirmed_senders(student: Membership) -> set[str]:
    """Learned sender domains this student has not confirmed. Never trusted."""
    return set(
        LearnedSender.objects.filter(student=student, confirmed_at__isnull=True).values_list(
            "domain", flat=True
        )
    )
```

(import `LearnedSender` from `apps.mailbox.models`).

- [ ] **Step 5: Sync**

In `apps/mailbox/sync.py`, inside the first `with tenant_transaction(...)` block of `sync_connection`, also compute:

```python
        unconfirmed = unconfirmed_senders(connection.membership)
        tags = {
            account.address.casefold(): account
            for account in PortalAccount.objects.filter(student=connection.membership)
            if "+" in account.address.partition("@")[0]
        }
```

Replace the start of the header loop (from `for header in headers:` through the `MailSignal.objects.get_or_create(...)` defaults) with:

```python
    for header in headers:
        account = next((tags[r] for r in header.recipients if r in tags), None)
        if account is not None:
            domain = sender_key(header.sender)
            if not domain:
                continue
            application_id = _only_application(connection, account.portal_host)
            trusted = not header.junk
            if domain not in allowed:
                _learn(connection, domain, account.portal_host)
                allowed[domain] = application_id
                unconfirmed.add(domain)
                # Learned this instant, so unconfirmed; the tag alone is the proof.
        elif header.junk:
            # Junk is read only for mail sent to a tag we issued.
            continue
        else:
            domain = matched_domain(header.sender, allowed)
            if not domain:
                # Never listed further, never fetched, never stored. This branch
                # is the product promise.
                continue
            application_id = allowed[domain]
            trusted = header.authenticated and domain not in unconfirmed
        with tenant_transaction(connection.tenant_id):
            signal, is_new = MailSignal.objects.get_or_create(
                connection=connection,
                provider_message_id=header.message_id,
                defaults={
                    "tenant_id": connection.tenant_id,
                    "sender_domain": domain,
                    "received_at": header.received_at,
                    "application_id": application_id,
                    "trusted": trusted,
                },
            )
```

and change the `apply_verdict` call further down to

```python
apply_verdict(
    signal,
    verdict,
    allowed=_link_allowlist(allowed, unconfirmed),
    authenticated=signal.trusted,
)
```

(replacing `allowed=allowed, authenticated=header.authenticated`). The link allowlist must leave
out unconfirmed learned domains: a leaked tag lets a scammer's own domain be learned, and without
this their link would pass the host check the instant it was learned. A genuine portal's
verification link points at its own portal host, which is already allowlisted through the
application. Add the helpers:

```python
def _only_application(connection: MailboxConnection, portal_host: str) -> UUID | None:
    """The one application on this portal host, or None when there are several."""
    with tenant_transaction(connection.tenant_id):
        ids = list(
            Application.objects.filter(
                student=connection.membership, portal_form__portal_host=portal_host
            ).values_list("id", flat=True)[:2]
        )
    return ids[0] if len(ids) == 1 else None


def _link_allowlist(
    allowed: dict[str, UUID | None], unconfirmed: set[str]
) -> dict[str, UUID | None]:
    """The domains a link in a message may point at: never an unconfirmed learned one."""
    return {domain: app for domain, app in allowed.items() if domain not in unconfirmed}


def _learn(connection: MailboxConnection, domain: str, portal_host: str) -> None:
    with tenant_transaction(connection.tenant_id):
        LearnedSender.objects.get_or_create(
            student=connection.membership,
            domain=domain,
            defaults={"tenant_id": connection.tenant_id, "portal_host": portal_host},
        )
    logger.info("SenderLearned connection=%s domain=%s", connection.id, domain)
```

(imports: `UUID`, `Application`, `PortalAccount` from `apps.portals.models`, `LearnedSender` from `apps.mailbox.models`, `sender_key`, `unconfirmed_senders` from `apps.mailbox.filter`). The trust rule is also written in `apply_verdict`'s docstring: rename nothing, but change its first paragraph under "`authenticated` gates every ACTION" to say the caller passes the message's *trust* (spec §3), which covers provider authentication and tagged delivery.

- [ ] **Step 6: The student confirms a learned sender**

`apps/mailbox/views.py`:

```python
@require_POST
@login_required
def confirm_sender(request: HttpRequest, sender_id: UUID) -> HttpResponse:
    membership = current_membership(request, Membership.Role.STUDENT)
    with tenant_transaction(membership.tenant_id):
        updated = LearnedSender.objects.filter(
            id=sender_id, student=membership, confirmed_at__isnull=True
        ).update(confirmed_at=timezone.now())
    if not updated:
        return JsonResponse({"reason": "not_found"}, status=404)
    return JsonResponse({"confirmed": True})
```

and in `apps/mailbox/urls.py` add `path("mailbox/senders/<uuid:sender_id>/confirm/", views.confirm_sender, name="mailbox-confirm-sender")` (match the existing routes' prefix style in that file).

- [ ] **Step 7: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox tests/audit tests/tenancy/test_database_isolation.py -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/mailbox apps/audit/redaction.py tests/mailbox
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(mailbox): read mail sent to a tag, learn its sender, act only on trusted mail

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The application inbox, and Microsoft only in the pilot

**Files:**
- Modify: `apps/mailbox/models.py` (`MailboxConnection.Kind`, `kind`)
- Create: `apps/mailbox/migrations/0003_connection_kind.py` (generated)
- Modify: `apps/mailbox/views.py` (`connect`, `callback`), `apps/mailbox/sync.py` (`_search_for`, header loop), `config/settings/base.py`, `apps/audit/redaction.py`
- Test: `tests/mailbox/test_views.py`, `tests/mailbox/test_sync.py`

**Interfaces:**
- Produces: `MailboxConnection.Kind` (`EVERYDAY` default, `APPLICATION`); `settings.MAILBOX_PROVIDERS: tuple[str, ...]` (default `("MICROSOFT",)`); `connect` accepts `?kind=`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/mailbox/test_sync.py`:

```python
@pytest.mark.django_db
def test_an_application_inbox_reads_every_sender(connection_with_pack) -> None:
    """It holds nothing but application mail, so no sender filter applies (spec §3)."""
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        connection.kind = MailboxConnection.Kind.APPLICATION
        connection.save(update_fields=["kind"])
    provider = FakeProvider(_inbox())

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert len(signals) == 50
    assert provider.searched == [()]
    assert all(not s.trusted for s in signals if s.sender_domain == "newsletter.example")
```

Append to `tests/mailbox/test_views.py`:

```python
def test_a_provider_not_offered_in_the_pilot_is_refused(settings, student_client):
    settings.MAILBOX_PROVIDERS = ("MICROSOFT",)

    response = student_client.get("/mailbox/connect/GOOGLE/")

    assert response.status_code == 400
    assert response.json() == {"reason": "provider_unavailable"}


def test_an_unknown_inbox_kind_is_refused(settings, student_client):
    settings.MAILBOX_PROVIDERS = ("MICROSOFT",)

    response = student_client.get("/mailbox/connect/MICROSOFT/?kind=OTHER")

    assert response.status_code == 400
    assert response.json() == {"reason": "unknown_kind"}
```

(Match the connect URL to `apps/mailbox/urls.py`; adjust the two literal paths if the prefix differs.)

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox/test_sync.py tests/mailbox/test_views.py -q -k "application_inbox or pilot or kind"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`MailboxConnection`:

```python
    class Kind(models.TextChoices):
        #: The student's everyday inbox: only pack and tagged mail is read.
        EVERYDAY = "EVERYDAY", "Everyday inbox"
        #: An inbox the student created for applications: everything is read.
        APPLICATION = "APPLICATION", "Application inbox"

    #: Default EVERYDAY, so a connection that never says widens nothing.
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.EVERYDAY)
```

Generate the migration. Add `"kind"` to the `"mailbox.MailboxConnection"` KEEP tuple in `apps/audit/redaction.py`.

`config/settings/base.py`, near the other mailbox settings:

```python
#: Providers a student may connect. Google stays off until the app passes
#: Google's restricted-scope verification (owner decision 2026-09-26).
MAILBOX_PROVIDERS = tuple(
    name for name in os.getenv("MAILBOX_PROVIDERS", "MICROSOFT").split(",") if name
)
```

`views.connect`: after reading `tier`, refuse `provider not in settings.MAILBOX_PROVIDERS` with 400 `{"reason": "provider_unavailable"}`; read `kind = request.GET.get("kind", MailboxConnection.Kind.EVERYDAY)`, refuse a value not in `MailboxConnection.Kind.values` with 400 `{"reason": "unknown_kind"}`, and put `"kind": kind` in the signed state. `views.callback`: create the connection with `kind=state.get("kind", MailboxConnection.Kind.EVERYDAY)` (and re-validate it against `Kind.values`, falling back to EVERYDAY).

Existing tests connect with `GOOGLE`: add to `tests/mailbox/conftest.py` an autouse fixture setting `settings.MAILBOX_PROVIDERS = ("GOOGLE", "MICROSOFT")`, so only the new pilot test exercises the default.

`sync._search_for`: return `()` when `connection.kind == MailboxConnection.Kind.APPLICATION`. In the header loop's final `else` branch (Task 5), for an application inbox read every sender:

```python
        else:
            domain = matched_domain(header.sender, allowed)
            if not domain and connection.kind == MailboxConnection.Kind.APPLICATION:
                domain = sender_key(header.sender)
            if not domain:
                continue
            application_id = allowed.get(domain)
            trusted = header.authenticated and domain in allowed and domain not in unconfirmed
```

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox tests/audit -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/mailbox config/settings/base.py apps/audit/redaction.py tests/mailbox
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(mailbox): an application inbox is read whole; only Microsoft in the pilot

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Tell the student what a message said, and retry what could not be read

**Files:**
- Modify: `apps/mailbox/models.py` (`MailSignal.classify_attempts`), migration `0004_classify_attempts.py` (generated)
- Modify: `apps/mailbox/actions.py` (label alerts), `apps/mailbox/sync.py` (retry pass)
- Modify: `apps/audit/redaction.py`
- Test: `tests/mailbox/test_label_alerts.py`

**Interfaces:**
- Produces: `MailSignal.classify_attempts: int`; `sync.MAX_CLASSIFY_ATTEMPTS = 3`; label alerts are urgent `Notification`s (so `apps/watch` escalates them).

- [ ] **Step 1: Write the failing tests**

`tests/mailbox/test_label_alerts.py`:

```python
from datetime import UTC, datetime

import pytest

from apps.concierge.models import Notification
from apps.mailbox.classify import ClassificationFailure, MailVerdict
from apps.mailbox.models import MailSignal
from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import MAX_CLASSIFY_ATTEMPTS, sync_connection
from apps.tenancy.context import tenant_scope
from tests.mailbox.conftest import FakeProvider, _grant

pytestmark = pytest.mark.django_db


def _authenticated(message_id="m1", sender="admissions@tum.de"):
    return MessageHeader(
        message_id=message_id,
        sender=sender,
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        authenticated=True,
    )


@pytest.mark.parametrize("label", ["DECISION", "INTERVIEW", "DOCUMENT_REQUEST", "FEE"])
def test_a_trusted_message_that_needs_the_student_raises_an_urgent_alert(
    connection_with_pack, monkeypatch, label
):
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label=label))
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id):
        sync_connection(
            connection, provider=FakeProvider((_authenticated(),)), secrets_client=_grant()
        )
        urgent = Notification.objects.filter(recipient=connection.membership, urgent=True)
        assert urgent.count() == 1
        assert "tum.de" in urgent.get().message


def test_an_untrusted_decision_raises_no_urgent_alert(connection_with_pack, monkeypatch):
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="DECISION"))
    header = MessageHeader(
        message_id="m1", sender="a@tum.de", received_at=datetime(2026, 9, 20, tzinfo=UTC)
    )
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider((header,)), secrets_client=_grant())
        assert not Notification.objects.filter(urgent=True).exists()


def test_a_failed_classification_is_retried_and_then_shown(connection_with_pack, monkeypatch):
    from apps.mailbox import sync as sync_module

    def fail(**_):
        raise ClassificationFailure("down")

    monkeypatch.setattr(sync_module, "classify_message", fail)
    monkeypatch.setattr(sync_module, "rate_limited", lambda *a, **k: False)
    connection = connection_with_pack
    provider = FakeProvider((_authenticated(),))
    with tenant_scope(connection.tenant_id):
        for _ in range(MAX_CLASSIFY_ATTEMPTS):
            sync_connection(connection, provider=provider, secrets_client=_grant())
        signal = MailSignal.objects.get()
        assert signal.classify_attempts == MAX_CLASSIFY_ATTEMPTS
        assert Notification.objects.filter(message__contains="open the message").count() == 1
        assert len(provider.bodies_fetched) == MAX_CLASSIFY_ATTEMPTS
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox/test_label_alerts.py -q`
Expected: FAIL — `ImportError: cannot import name 'MAX_CLASSIFY_ATTEMPTS'`.

- [ ] **Step 3: Implement**

`MailSignal`: `classify_attempts = models.PositiveSmallIntegerField(default=0)`; generate the migration; add `"classify_attempts"` to the `"mailbox.MailSignal"` KEEP tuple.

`apps/mailbox/actions.py`, at the end of `apply_verdict` before its final `return None` paths — simplest: right after the `if not authenticated: … return None` guard — call `_alert_student(signal, verdict.label)`:

```python
#: Labels that mean the student has something to do or read now. The message
#: never carries the email's own words -- only who wrote and what kind of thing.
_ALERTS = {
    "DECISION": (RoadmapItem.Stage.MONITORING, "{domain} sent a decision. Open your portal to read it."),
    "INTERVIEW": (RoadmapItem.Stage.INTERVIEW, "{domain} invited you to an interview. Check the time and reply."),
    "DOCUMENT_REQUEST": (RoadmapItem.Stage.DOCUMENTS, "{domain} is asking for a document. Check what they need."),
    "FEE": (RoadmapItem.Stage.FEE_EXECUTION, "{domain} says a fee is due. Check the amount and the deadline."),
}
_ALERT_HORIZON = timedelta(days=7)


def _alert_student(signal: MailSignal, label: str) -> None:
    if label not in _ALERTS:
        return
    stage, text = _ALERTS[label]
    application = signal.application
    item = RoadmapItem.objects.create(
        tenant_id=signal.tenant_id,
        student=signal.connection.membership,
        stage=stage,
        owner=signal.connection.membership,
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=(application.deadline if application and application.deadline else None)
        or timezone.now() + _ALERT_HORIZON,
    )
    Notification.objects.create(
        tenant_id=signal.tenant_id,
        recipient=signal.connection.membership,
        roadmap_item=item,
        urgent=True,
        message=text.format(domain=signal.sender_domain),
    )
```

(Wrap the `_ALERTS` lines to ≤100 characters when writing them; imports `timedelta`, `timezone`, `Notification`, `RoadmapItem`.)

`apps/mailbox/sync.py`: add `MAX_CLASSIFY_ATTEMPTS = 3`. Move the body-fetch-classify-apply block into a helper `_classify(connection, client, token, signal, allowed) -> None` that fetches `signal.provider_message_id`, calls `classify_message`, and on success runs `apply_verdict(signal, verdict, allowed=link_allowlist, authenticated=signal.trusted)` in a tenant transaction, where `link_allowlist` is `_link_allowlist(allowed, unconfirmed)` from Task 5 (pass it in); on `(ProviderError, ClassificationFailure, ClassificationRateLimited)` it increments `classify_attempts` (conditional `F()` update in a tenant transaction) and, when that reaches `MAX_CLASSIFY_ATTEMPTS`, creates one card via the existing `_card(connection, stage=RoadmapItem.Stage.MONITORING, message=f"{signal.sender_domain} wrote to you. Open the message to see what it says.")`. Call it for each new signal on the content tier (as today) and, after the header loop, once for every signal of this connection with `label=""`, `0 < classify_attempts < MAX_CLASSIFY_ATTEMPTS`, on the content tier. A successful classification leaves `classify_attempts` as it was.

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/mailbox tests/audit -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/mailbox apps/audit/redaction.py tests/mailbox
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(mailbox): turn decisions, interviews, requests and fees into urgent alerts; retry unread mail

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The extension asks for a check now

**Files:**
- Modify: `apps/portals/ext_api.py` (new `mailbox_check`), `apps/portals/urls.py`
- Test: `tests/portals/test_ext_mailbox_check.py`

**Interfaces:**
- Produces: `POST ext/mailbox/check` (device token) → `200 {"new_signals": <int>}`; `429 {"error": "rate_limited"}` when every connection refused for the sync limit.

- [ ] **Step 1: Write the failing test**

`tests/portals/test_ext_mailbox_check.py`:

```python
"""A portal says "check your email": the extension asks, and we check this student now."""

import pytest

from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope
from tests.portals.test_ext_api import _pair

pytestmark = pytest.mark.django_db


def test_a_paired_extension_triggers_a_sync_of_its_own_student(
    client, agency_a, membership_a, domain_a, monkeypatch
):
    from apps.mailbox import sync as sync_module

    synced = []
    monkeypatch.setattr(
        sync_module, "sync_connection", lambda connection, **_: synced.append(connection.id) or []
    )
    with tenant_scope(agency_a.id):
        connection = MailboxConnection.objects.create(
            tenant=agency_a,
            membership=membership_a,
            provider=MailboxConnection.Provider.MICROSOFT,
            address="leyla@outlook.test",
        )
    token = _pair(client, agency_a, membership_a, domain_a)

    response = client.post(
        "/ext/mailbox/check", HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}"
    )

    assert response.status_code == 200
    assert response.json() == {"new_signals": 0}
    assert synced == [connection.id]


def test_no_token_is_refused(client, domain_a):
    assert client.post("/ext/mailbox/check", HTTP_HOST=domain_a.host).status_code == 401
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals/test_ext_mailbox_check.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Implement**

`apps/portals/ext_api.py`:

```python
@require_POST
@_device_endpoint
def mailbox_check(request: HttpRequest, pairing: ExtensionPairing) -> HttpResponse:
    """Check this student's mailboxes now, because a portal told them to look.

    The hourly sweep is too slow for a code the student is waiting for at the
    portal (spec §3). sync_connection's own per-student limit is the brake.
    Imported here, not at module load: apps.mailbox imports apps.portals.
    """
    from apps.mailbox import sync as mailbox_sync
    from apps.mailbox.models import MailboxConnection

    with tenant_transaction(pairing.tenant_id):
        connections = list(
            MailboxConnection.objects.filter(
                membership=pairing.membership, status=MailboxConnection.Status.ACTIVE
            ).select_related("membership")
        )
    new, refused = 0, 0
    for connection in connections:
        try:
            new += len(mailbox_sync.sync_connection(connection))
        except mailbox_sync.SyncRefused:
            refused += 1
    if connections and refused == len(connections):
        raise _ApiError(429, "rate_limited")
    return JsonResponse({"new_signals": new})
```

`apps/portals/urls.py`: `path("ext/mailbox/check", ext_api.mailbox_check, name="portals-ext-mailbox-check")`.

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/portals -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/portals tests/portals/test_ext_mailbox_check.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(portals): the extension can ask for an immediate mailbox check

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Alert when a student's inbox stops being checked

**Files:**
- Modify: `apps/mailbox/models.py` (`MailboxConnection.health_alerted_at`), migration `0005_health_alerted_at.py` (generated)
- Modify: `apps/mailbox/sync.py` (clear it on a successful sync)
- Create: `apps/watch/mailbox_health.py`
- Modify: `apps/watch/management/commands/watch_applications.py`
- Modify: `apps/audit/redaction.py`
- Test: `tests/watch/test_mailbox_health.py`

**Interfaces:**
- Consumes: `JobRun` (`apps.watch.models`), `being_erased` (`apps.watch.watchdog`).
- Produces: `alert_stale_mailboxes_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int`; `STALE_AFTER = timedelta(hours=6)`.

- [ ] **Step 1: Write the failing tests**

`tests/watch/test_mailbox_health.py`:

```python
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.concierge.models import Notification
from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope
from apps.watch.heartbeat import record_run
from apps.watch.mailbox_health import alert_stale_mailboxes_for_tenant

pytestmark = pytest.mark.django_db


def _connection(agency, student, *, synced_hours_ago):
    with tenant_scope(agency.id):
        connection = MailboxConnection.objects.create(
            tenant=agency,
            membership=student,
            provider=MailboxConnection.Provider.MICROSOFT,
            address="leyla@outlook.test",
        )
        MailboxConnection.objects.filter(pk=connection.pk).update(
            last_sync_at=timezone.now() - timedelta(hours=synced_hours_ago)
        )
    return connection


def test_a_stale_inbox_raises_one_urgent_alert(agency_a, membership_a):
    record_run("sync_mailboxes")
    _connection(agency_a, membership_a, synced_hours_ago=7)

    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 1
    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a, urgent=True).count() == 1


def test_a_fresh_inbox_is_left_alone(agency_a, membership_a):
    record_run("sync_mailboxes")
    _connection(agency_a, membership_a, synced_hours_ago=1)

    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 0


def test_no_alerts_while_the_sweep_itself_is_not_running(agency_a, membership_a):
    """Then every inbox is stale; the job-silence alarm owns that, not each student."""
    _connection(agency_a, membership_a, synced_hours_ago=7)

    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch/test_mailbox_health.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.watch.mailbox_health'`.

- [ ] **Step 3: Implement**

`MailboxConnection`: `health_alerted_at = models.DateTimeField(null=True, blank=True)` (comment: set when a stale-inbox alert was raised, cleared by the next successful sync, so one outage is one alert). Generate the migration; add `"health_alerted_at"` to the `"mailbox.MailboxConnection"` KEEP tuple. In `sync.sync_connection`'s final save, also set `connection.health_alerted_at = None` and include it in `update_fields`.

`apps/watch/mailbox_health.py`:

```python
"""A connected inbox nobody has checked for hours is a promise quietly broken.

Only while the sweep itself runs: if it has stopped, every inbox is stale and
the job-silence alarm (heartbeat.py) is the one to raise it, not each student.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .models import JobRun
from .watchdog import being_erased

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=6)
_SWEEP = "sync_mailboxes"
_SWEEP_WINDOW = timedelta(hours=2)


def alert_stale_mailboxes_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int:
    moment = now or timezone.now()
    last_sweep = JobRun.objects.filter(name=_SWEEP).values_list("last_success_at", flat=True)
    if not last_sweep or moment - last_sweep[0] > _SWEEP_WINDOW:
        return 0
    raised = 0
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            stale = (
                MailboxConnection.objects.filter(
                    status=MailboxConnection.Status.ACTIVE,
                    health_alerted_at__isnull=True,
                    membership__active=True,
                )
                .exclude(being_erased("membership"))
                .annotate(seen=Coalesce("last_sync_at", "connected_at"))
                .filter(seen__lt=moment - STALE_AFTER)
                .select_related("membership")
            )
            for connection in stale:
                item = RoadmapItem.objects.create(
                    tenant_id=tenant_id,
                    student=connection.membership,
                    stage=RoadmapItem.Stage.PERSONAL_ACTION,
                    owner=connection.membership,
                    owner_kind=RoadmapItem.OwnerKind.HUMAN,
                    deadline=moment + timedelta(days=1),
                )
                Notification.objects.create(
                    tenant_id=tenant_id,
                    recipient=connection.membership,
                    roadmap_item=item,
                    urgent=True,
                    message=(
                        "We haven't been able to check your application inbox for a while. "
                        "Open your dashboard and reconnect it."
                    ),
                )
                connection.health_alerted_at = moment
                connection.save(update_fields=["health_alerted_at"])
                logger.info("MailboxStale connection=%s", connection.id)
                raised += 1
    return raised
```

(Check `being_erased`'s exact name and argument in `apps/watch/watchdog.py` and use it as defined there.)

`watch_applications` command: call `alert_stale_mailboxes_for_tenant(agency.id)` in the agency loop after the escalation sweep.

- [ ] **Step 4: Run to verify pass**

Run: `POSTGRES_DB=tehsil_mailbox_port uv run pytest tests/watch tests/mailbox tests/audit -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/mailbox-port add apps/mailbox apps/watch apps/audit/redaction.py tests/watch/test_mailbox_health.py
git -C /home/orkhan/Desktop/mailbox-port commit -m "feat(watch): alert when a connected inbox stops being checked

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Whole-branch verification

- [ ] **Step 1: Every gate**

```bash
cd /home/orkhan/Desktop/mailbox-port
uv run ruff check .
uv run mypy apps config
uv run bandit -q -c pyproject.toml -r apps config
POSTGRES_DB=tehsil_mailbox_port uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=tehsil_mailbox_port uv run pytest -q
```

Expected: all clean, the suite passing with no new failures.

- [ ] **Step 2: One run under the production role**

Add `tests/mailbox/test_tagged_rls.py`: under `rls_enforced_orm` with `@pytest.mark.django_db(transaction=True)`, create a `PortalAccount` and a tagged header, run `sync_connection`, and assert inside a tenant transaction that the signal exists and a `LearnedSender` row was written. This is the only proof the new reads and writes work as the NOBYPASSRLS role. Commit it.

- [ ] **Step 3: Mutation checks (restore after each; tree must end clean)**

- In `sync.py`, make tagged mail untrusted (`trusted = False` in the tagged branch): `test_tagged_mail_from_an_unknown_vendor_is_read_and_its_sender_learned` must fail.
- In `sync.py`, drop the `elif header.junk: continue`: `test_untagged_junk_is_never_read` must fail.
- In `filter.py`, return `host` instead of the registrable domain in `_key`: `test_a_www_evidence_link_still_allowlists_the_institution` must fail.

Restore each with `git -C /home/orkhan/Desktop/mailbox-port checkout -- <file>` and confirm `git status --short` is empty.

- [ ] **Step 4: Report** commands, results, mutation outcomes.
