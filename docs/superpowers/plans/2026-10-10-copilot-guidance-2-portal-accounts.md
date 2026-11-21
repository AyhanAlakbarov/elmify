# Co-pilot plan 2: portal accounts with a platform-held password — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The co-pilot signs the student up on a portal with their issued portal address and a strong generated password, keeps the password in Secrets Manager under its own KMS key, types it into the portal's login page on later visits, and lets the student see it (after re-entering their Elmify password) or take the account over.

**Architecture:** One server module (`apps/portals/credentials.py`) owns the password secrets. It takes over the secret path and the erasure helper from the retired `auth.py`, so PR #169's deletion of `auth.py` cannot take erasure with it. One extension route, `POST /ext/applications/<id>/portal-login`, hands `{username, password}` to the paired extension. It sends the password only when the page's host is the account's portal host. Every hand-out leaves an `AuditEvent`. The content script finds a login or sign-up page by its `type="password"` boxes, the way a password manager does, not from a FieldMap. It types the address and the password, never clicks, and leaves the press to the student. A student settings page lists each portal login, reveals the password after a password re-check, and offers "I changed my password", which deletes our copy.

**Tech Stack:** Django 6 / Python 3.14, boto3 Secrets Manager, CloudFormation (`infra/template.yaml`), Chrome MV3 extension in TypeScript (esbuild), pytest + Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md` §6 (D3), §8, §10 ("The portal logs the student out mid-form", "The student asks for deletion").

## Global Constraints

- **Where the password lives.** "a dedicated secret store (Secrets Manager under its own KMS key, one secret per student-portal account) … never a model field, never logged, never in an exception message, never in the evidence bucket" (spec §6).
- The secret id stays `elmify/portal/{tenant_id}/{student_id}/{portal_host}`. Existing IAM grants and erasure already use that shape.
- **The extension's copy.** "The extension receives it only for the login page, in session memory, and types it like any value." Concretely:
  - the password lives only in the worker's reply to the one content-script message that asked for it;
  - it is never written to `chrome.storage` of any area, never to the dock, never into an event, a mark or a log.
- **Generated password.** "a generated strong password (random, 20+ characters, meeting the portal's own rules)". Defaults:
  - length 24, with at least one lowercase letter, one uppercase letter, one digit and one symbol from `!#-_.`;
  - a password box with a smaller `maxlength` shortens it, down to a floor of 12;
  - below 12, nothing is generated.
- **Erasure.** "Erasure destroys the student's portal secrets on the same path that deletes their documents (`advance_deletion`)." This already happens. It must keep working after this plan and after PR #169.
- **Takeover.** "'I changed my password' in the dashboard stops the co-pilot logging in for that portal." We also delete our copy at that moment, because a secret we no longer need is still a target.
- **Reveal.** "Revealing the password asks the student to confirm their own identity again and leaves an AuditEvent." The re-check is the student's own Elmify password (`request.user.check_password`), rate-limited.
- **Safety rules (§8).**
  - The co-pilot never clicks: it types, the student clicks.
  - Typing happens only on the portal origin the server pinned.
  - Typing goes only into visible, enabled boxes.
  - A box already holding the student's own text is never typed over (`fill.ts::fillVerified` already guarantees this).
- **Page layer (§11).** Nothing on the page carries an identifier of the student, the account or the agency beyond the two values typed into the portal's own boxes.
- **CI gates (CLAUDE.md):**
  - `uv run ruff check .` (never `ruff format`);
  - `uv run mypy apps config`;
  - `POSTGRES_DB=elmify_copilot_accounts uv run pytest -q`;
  - `uv run python manage.py makemigrations --check --dry-run`;
  - `uv run bandit -c pyproject.toml -r apps config`;
  - for the extension: `npm --prefix extension run typecheck`, `npm --prefix extension run build`, `npm --prefix extension run build:test`.
- **Branch.** `claude/copilot-accounts-and-mail` in `/home/orkhan/Desktop/copilot-guidance`. Every git command there uses `git -C /home/orkhan/Desktop/copilot-guidance`, because the shell's working directory resets to the main repo.
- **Migration number.** `makemigrations` picks the next free number on this branch (`0027_…`). Plan 4 (`claude/copilot-document-prep`) and plan 5 (`claude/copilot-form-learning`) also add `0027`+ migrations. Whichever branch merges second renumbers its own and repoints the dependency. CI's `makemigrations --check` catches a miss.

## Review Focus

1. **A portal that refuses our generated password** (no symbols allowed, a cap under 12). The portal shows its own error. The student can type their own password and press "I changed my password". We must not then keep typing the refused one. Pinned in Task 2: `password_rules` is a 409 that writes no secret. Pinned in Task 4: takeover deletes the secret.
2. **A login page with a username box that is not an email** ("Applicant number"). The page's single box before the password is typed into with the address, and the portal refuses the login. The student logs in themselves, which is the same outcome as today. Pinned in Task 6: two candidate boxes means nothing is typed.
3. **A password box that already holds what the student typed.** It is never overwritten. Pinned in Task 6.
4. **A reload of the sign-up page.** The same password must come back, never a second one. Pinned in Task 1 (create is idempotent) and Task 2 (signup twice returns one password, one secret).
5. **A host the binding does not own.** A page on another host asks for the login, for example a single-sign-on host the portal redirected to. The answer is a refusal both in the worker (Task 5) and on the server (Task 2).

---

## File structure

| File | Responsibility |
|---|---|
| `apps/portals/credentials.py` (create) | The password secret store: generate, create-once, read, delete one, delete all for erasure. The only module that touches `elmify/portal/*`. |
| `apps/portals/auth.py` (modify) | Imports `secret_id` and `delete_student_portal_credentials` from `credentials.py` instead of defining them. |
| `apps/audit/deletion.py` (modify) | Imports the erasure helper from `credentials.py`. |
| `apps/portals/models.py` + migration | `PortalAccount.password_held_at` and `.student_managed_at`: markers only, never the password. |
| `apps/audit/redaction.py` (modify) | Lists the two new timestamps as retained. |
| `apps/portals/ext_api.py`, `urls.py` (modify) | `POST /ext/applications/<id>/portal-login`. |
| `apps/portals/views.py`, `urls.py`, `templates/student/settings_portals.html`, `templates/student/settings.html` | The student's "Portal logins" settings page: list, reveal, takeover. |
| `config/settings/base.py` | `PORTAL_SECRETS_KMS_KEY_ID`. |
| `infra/template.yaml`, `tests/infra/test_template.py` | The KMS key, the web tier's grants, the env var. |
| `extension/src/api.ts`, `extension/src/service_worker.ts` | The `portal-login` content message and its checks. |
| `extension/src/content/credentials.ts` (create), `extension/src/content/index.ts` | Finding login and sign-up pages and typing into them. |
| `extension/src/panel/i18n.ts` | Two new panel messages in four languages. |
| `CLAUDE.md` | Corrects "no portal credential exists anywhere". |

---

### Task 1: The password store

**Files:**
- Create: `apps/portals/credentials.py`
- Modify: `apps/portals/auth.py` (delete the bodies of `secret_id` and `delete_student_portal_credentials`; import them)
- Modify: `apps/audit/deletion.py:11` (import line)
- Modify: `config/settings/base.py` (one setting, beside `MAILBOX_OAUTH_REDIRECT_BASE`)
- Test: `tests/portals/test_credentials.py`

**Interfaces:**
- Produces:
  - `generate_password(max_length: int | None = None) -> str`, which raises `PasswordRulesUnmet` when `max_length < 12`;
  - `create_password(*, tenant_id: UUID, student_id: UUID, portal_host: str, username: str, max_length: int | None = None, client: object | None = None) -> str`;
  - `password_for(*, tenant_id: UUID, student_id: UUID, portal_host: str, client: object | None = None) -> str | None`;
  - `delete_password(*, tenant_id: UUID, student_id: UUID, portal_host: str, client: object | None = None) -> bool`;
  - `delete_student_portal_credentials(*, tenant_id: UUID, student_id: UUID, client: object | None = None) -> int` (moved, behaviour unchanged);
  - `secret_id(tenant_id, student_id, portal_host) -> str` (moved, unchanged);
  - `class PasswordRulesUnmet(Exception)`;
  - module-level `_client(client: object | None) -> object`, which tests monkeypatch.

- [ ] **Step 1: Write the failing tests**

```python
"""Portal passwords: in Secrets Manager under their own key, never a column.

What must be true is mostly what this module does NOT do -- never log a
password, never enumerate secrets, never make a second password for an account
that already has one -- so the fake records every call.
"""

from __future__ import annotations

import json
import logging
import string
from uuid import uuid4

import botocore.exceptions
import pytest

from apps.portals import credentials
from apps.portals.credentials import (
    PasswordRulesUnmet,
    create_password,
    delete_password,
    generate_password,
    password_for,
    secret_id,
)

TENANT = uuid4()
STUDENT = uuid4()
HOST = "apply.example.edu"


class FakeSecrets:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def create_secret(self, *, Name: str, SecretString: str, **extra: object) -> dict[str, str]:
        self.calls.append(("create_secret", Name, extra))
        if Name in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceExistsException"}}, "CreateSecret"
            )
        self.store[Name] = SecretString
        return {"ARN": Name}

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        self.calls.append(("get_secret_value", SecretId, {}))
        if SecretId not in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "GetSecretValue"
            )
        return {"SecretString": self.store[SecretId]}

    def delete_secret(self, *, SecretId: str, ForceDeleteWithoutRecovery: bool) -> dict[str, str]:
        self.calls.append(("delete_secret", SecretId, {}))
        if SecretId not in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "DeleteSecret"
            )
        del self.store[SecretId]
        return {"ARN": SecretId}

    def list_secrets(self, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("ListSecrets cannot be resource-scoped in IAM and must not be called")


def test_a_generated_password_is_long_and_has_every_kind_of_character() -> None:
    for _ in range(200):
        password = generate_password()
        assert len(password) == 24
        assert any(c in string.ascii_lowercase for c in password)
        assert any(c in string.ascii_uppercase for c in password)
        assert any(c in string.digits for c in password)
        assert any(c in "!#-_." for c in password)
        assert set(password) <= set(string.ascii_letters + string.digits + "!#-_.")


def test_a_box_s_maxlength_shortens_it_and_below_twelve_nothing_is_made() -> None:
    assert len(generate_password(16)) == 16
    assert len(generate_password(200)) == 24
    with pytest.raises(PasswordRulesUnmet):
        generate_password(11)


def test_two_passwords_are_never_the_same() -> None:
    assert len({generate_password() for _ in range(50)}) == 50


def test_create_stores_once_and_a_second_create_returns_the_first(settings) -> None:
    settings.PORTAL_SECRETS_KMS_KEY_ID = ""
    fake = FakeSecrets()
    first = create_password(
        tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, username="a@b.c", client=fake
    )
    again = create_password(
        tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, username="a@b.c", client=fake
    )
    assert again == first
    stored = json.loads(fake.store[secret_id(TENANT, STUDENT, HOST)])
    assert stored == {"username": "a@b.c", "password": first}
    assert password_for(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake) == first


def test_create_names_the_portal_key_when_one_is_configured(settings) -> None:
    settings.PORTAL_SECRETS_KMS_KEY_ID = "key-123"
    fake = FakeSecrets()
    create_password(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, username="u", client=fake)
    assert fake.calls[0][2] == {"KmsKeyId": "key-123"}


def test_a_missing_secret_reads_as_none_and_logs_no_id(caplog) -> None:
    fake = FakeSecrets()
    with caplog.at_level(logging.DEBUG):
        assert password_for(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake) is None
    assert str(STUDENT) not in caplog.text


def test_the_password_never_reaches_a_log(caplog, settings) -> None:
    settings.PORTAL_SECRETS_KMS_KEY_ID = ""
    fake = FakeSecrets()
    with caplog.at_level(logging.DEBUG):
        password = create_password(
            tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, username="u", client=fake
        )
        password_for(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)
    assert password not in caplog.text


def test_delete_one_says_whether_there_was_one() -> None:
    fake = FakeSecrets()
    fake.store[secret_id(TENANT, STUDENT, HOST)] = json.dumps({"username": "u", "password": "p"})
    assert delete_password(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)
    assert not delete_password(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)


def test_another_refusal_on_delete_propagates() -> None:
    class Denied(FakeSecrets):
        def delete_secret(self, *, SecretId: str, ForceDeleteWithoutRecovery: bool) -> dict[str, str]:
            raise botocore.exceptions.ClientError({"Error": {"Code": "AccessDeniedException"}}, "DeleteSecret")

    with pytest.raises(botocore.exceptions.ClientError):
        delete_password(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=Denied())


def test_erasure_imports_the_helper_from_here() -> None:
    from apps.audit import deletion

    assert deletion.delete_student_portal_credentials is credentials.delete_student_portal_credentials
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_credentials.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.portals.credentials'`.

- [ ] **Step 3: Write `apps/portals/credentials.py`**

```python
"""Portal passwords the platform holds for students (spec 2026-10-09 §6, D3).

In Secrets Manager under their own KMS key, one secret per student per portal,
never in Postgres -- a database dump must not be a set of live portal logins.
The path shape is load-bearing: it is what lets erasure delete every secret a
student owns without ListSecrets, which IAM cannot scope to a resource. The
web tier creates, reads and deletes; the worker only deletes, on erasure.

Nothing here may log a password, a SecretId (it names the student) or a
botocore message (it carries the SecretId).
"""

from __future__ import annotations

import json
import logging
import secrets
import string
from uuid import UUID

import boto3  # type: ignore[import-untyped]
import botocore.exceptions  # type: ignore[import-untyped]
from django.conf import settings

from .models import PortalForm

logger = logging.getLogger(__name__)

#: Accepted by every portal sampled so far; no quote, backslash, angle bracket,
#: ampersand, percent or space, which some forms mangle or refuse.
_SYMBOLS = "!#-_."
_ALPHABET = string.ascii_letters + string.digits + _SYMBOLS
_LENGTH = 24
#: Below this a generated password is weaker than the student would choose.
_FLOOR = 12


class PasswordRulesUnmet(Exception):
    """The portal's box cannot hold a password we are willing to make."""


def secret_id(tenant_id: UUID, student_id: UUID, portal_host: str) -> str:
    """One secret per student per portal.

    Per *student*, not per tenant: a portal account belongs to the applicant.
    """
    return f"elmify/portal/{tenant_id}/{student_id}/{portal_host}"


def _client(client: object | None) -> object:
    return client if client is not None else boto3.client("secretsmanager")


def generate_password(max_length: int | None = None) -> str:
    """24 characters (fewer when the portal's box caps it), one of each kind.

    # ponytail: reads only the box's maxlength. A portal rule beyond length and
    # the four kinds (no symbols, a fixed symbol set) is the student's to meet:
    # they type their own and press "I changed my password". Parse the bench's
    # recorded password_rules (plan 6) when a measured portal needs it.
    """
    length = _LENGTH if max_length is None else min(_LENGTH, max_length)
    if length < _FLOOR:
        raise PasswordRulesUnmet(f"box holds {length} characters")
    chars = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(_SYMBOLS),
        *(secrets.choice(_ALPHABET) for _ in range(length - 4)),
    ]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def create_password(
    *,
    tenant_id: UUID,
    student_id: UUID,
    portal_host: str,
    username: str,
    max_length: int | None = None,
    client: object | None = None,
) -> str:
    """Make and store this account's password, or return the one already stored.

    Create-once on purpose: a reloaded sign-up page must type the SAME
    password, and two racing requests must agree -- the loser of CreateSecret
    reads the winner's.
    """
    store = _client(client)
    name = secret_id(tenant_id, student_id, portal_host)
    password = generate_password(max_length)
    key = settings.PORTAL_SECRETS_KMS_KEY_ID
    try:
        store.create_secret(  # type: ignore[attr-defined]
            Name=name,
            SecretString=json.dumps({"username": username, "password": password}),
            **({"KmsKeyId": key} if key else {}),
        )
    except botocore.exceptions.ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceExistsException":
            raise
        existing = password_for(
            tenant_id=tenant_id, student_id=student_id, portal_host=portal_host, client=store
        )
        if existing is None:
            raise
        return existing
    return password


def password_for(
    *, tenant_id: UUID, student_id: UUID, portal_host: str, client: object | None = None
) -> str | None:
    try:
        response = _client(client).get_secret_value(  # type: ignore[attr-defined]
            SecretId=secret_id(tenant_id, student_id, portal_host)
        )
        password = json.loads(response["SecretString"])["password"]
    except (botocore.exceptions.ClientError, KeyError, TypeError, json.JSONDecodeError):
        logger.warning("no portal password for %s", portal_host)
        return None
    return password if isinstance(password, str) else None


def delete_password(
    *, tenant_id: UUID, student_id: UUID, portal_host: str, client: object | None = None
) -> bool:
    """Destroy one account's password. False when there was none.

    Anything but "already absent" propagates: a caller that records "handed
    over" over a secret that is still live has told the student something false.
    """
    try:
        _client(client).delete_secret(  # type: ignore[attr-defined]
            SecretId=secret_id(tenant_id, student_id, portal_host),
            ForceDeleteWithoutRecovery=True,
        )
    except botocore.exceptions.ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        return False
    return True
```

Then move `delete_student_portal_credentials` from `apps/portals/auth.py` into `credentials.py`, word for word: its docstring, its `ponytail:` comment and its `PortalForm` host loop. Make two edits inside it. Replace `secrets = client or boto3.client("secretsmanager")` with `store = _client(client)`, and rename the local `secrets` to `store`, because the module now imports the stdlib `secrets`. Replace the Task 14 sentence in its comment ("Until the WorkerTaskRole grant lands (Task 14), AccessDenied is the live production case this branch exists to catch.") with "AccessDenied is the case this branch exists to catch."

In `apps/portals/auth.py`:
- delete the `secret_id` and `delete_student_portal_credentials` definitions;
- add `from .credentials import delete_student_portal_credentials, secret_id  # noqa: F401  (re-exported for the retired tier)`.

In `apps/audit/deletion.py`, change line 11 to `from apps.portals.credentials import delete_student_portal_credentials`.

In `config/settings/base.py`, beside `MAILBOX_OAUTH_REDIRECT_BASE`:

```python
#: The KMS key portal passwords are encrypted under (infra: PortalCredentialsKey).
#: Blank locally and in tests, where Secrets Manager's default key is used.
PORTAL_SECRETS_KMS_KEY_ID = os.getenv("PORTAL_SECRETS_KMS_KEY_ID", "")
```

- [ ] **Step 4: Run the tests and the old auth tests**

Run: `POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_credentials.py tests/portals/test_auth.py tests/audit -q`
Expected: PASS. `tests/portals/test_auth.py` imports `delete_student_portal_credentials` and `secret_id` from `apps.portals.auth`, which still re-exports both.

- [ ] **Step 5: Lint, types, commit**

Run: `uv run ruff check apps/portals/credentials.py apps/portals/auth.py apps/audit/deletion.py tests/portals/test_credentials.py && uv run mypy apps config`

```bash
git -C /home/orkhan/Desktop/copilot-guidance add apps/portals/credentials.py apps/portals/auth.py apps/audit/deletion.py config/settings/base.py tests/portals/test_credentials.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(portals): portal passwords live in credentials.py -- generated, created once, erased with the student"
```

---

### Task 2: The extension's login route

**Files:**
- Modify: `apps/portals/models.py` (`PortalAccount`)
- Create: the migration (`uv run python manage.py makemigrations portals --name portal_account_password_markers`)
- Modify: `apps/audit/redaction.py` (the retained-fields tuple for `"portals.PortalAccount"`)
- Modify: `apps/portals/ext_api.py`, `apps/portals/urls.py`
- Test: `tests/portals/test_portal_login.py`

**Interfaces:**
- Consumes: `credentials.create_password`, `credentials.password_for`, `credentials.PasswordRulesUnmet` (Task 1); `tags.account_for(application)`.
- Produces:
  - `PortalAccount.password_held_at: datetime | None` and `PortalAccount.student_managed_at: datetime | None`;
  - the route `POST /ext/applications/<uuid>/portal-login`. It takes `{"page": "login"|"signup", "host": str, "max_length"?: int}` and answers `200 {"username", "password"}` with `Cache-Control: no-store`. Refusals:

    | Status | Code |
    |---|---|
    | 400 | `invalid_request` |
    | 409 | `no_portal_address` |
    | 409 | `wrong_host` |
    | 409 | `student_managed` |
    | 409 | `no_portal_password` |
    | 409 | `registered_without_us` |
    | 409 | `password_rules` |
    | 429 | `rate_limited` |
  - each 200 writes an `AuditEvent`: `event="portal.password_sent"` with `actor=pairing.membership` and `object_id=account.id`;
  - a created password also writes `event="portal.password_created"`.

- [ ] **Step 1: Add the fields** to `PortalAccount` in `apps/portals/models.py`, after `tag_dropped_by_student`:

```python
    #: When the platform made and stored this account's password (spec §6, D3).
    #: A marker only: the password itself is in Secrets Manager
    #: (apps/portals/credentials.py), never in this table.
    password_held_at = models.DateTimeField(null=True, blank=True)
    #: The student said "I changed my password": the co-pilot no longer logs in
    #: here and our copy was deleted at that moment.
    student_managed_at = models.DateTimeField(null=True, blank=True)
```

Run `uv run python manage.py makemigrations portals --name portal_account_password_markers`. In `apps/audit/redaction.py`, add `"password_held_at"` and `"student_managed_at"` to the retained tuple under `"portals.PortalAccount"`, with this comment line above them: `# when we held a password and when the student took it over -- timestamps about the account, not the person.`

- [ ] **Step 2: Write the failing tests** in `tests/portals/test_portal_login.py`

```python
"""POST /ext/applications/<id>/portal-login: the password goes to the paired
extension, for this account's own portal host, and nowhere else."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from apps.funding.models import AuditEvent
from apps.portals import credentials
from apps.portals.credentials import secret_id
from apps.tenancy.context import tenant_scope
from tests.portals.test_credentials import FakeSecrets
from tests.portals.test_ext_api import _pair

pytestmark = pytest.mark.django_db

HOST = "apply.example.edu"


@pytest.fixture
def fake(monkeypatch, settings):
    settings.PORTAL_SECRETS_KMS_KEY_ID = ""
    store = FakeSecrets()
    monkeypatch.setattr(credentials, "_client", lambda client=None: store)
    return store


def _setup(agency, membership):
    from apps.portals.models import Application, PortalForm
    from apps.portals.tags import portal_address

    with tenant_scope(agency.id):
        membership.application_email = "leyla.apply@outlook.com"
        membership.save(update_fields=["application_email"])
        form = PortalForm.objects.create(
            portal_host=HOST, form_key=f"ext-{uuid4()}", form_url=f"https://{HOST}/personal"
        )
        application = Application.objects.create(
            tenant=agency, student=membership, program_id=uuid4(), portal_form=form
        )
        address = portal_address(application)
    return application, address


def _ask(client, application, token, domain, body):
    return client.post(
        f"/ext/applications/{application.id}/portal-login",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_HOST=domain.host,
    )


def test_signup_makes_one_password_and_a_reload_gets_the_same_one(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, address = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    first = _ask(client, application, token, domain_a, {"page": "signup", "host": HOST})
    again = _ask(client, application, token, domain_a, {"page": "signup", "host": HOST})

    assert first.status_code == 200, first.content
    assert first["Cache-Control"] == "no-store"
    assert first.json()["username"] == address
    assert again.json()["password"] == first.json()["password"]
    assert len(fake.store) == 1
    with tenant_scope(agency_a.id):
        account = application.student.portal_accounts.get()
        events = list(AuditEvent.objects.filter(object_id=account.id).values_list("event", flat=True))
    assert account.password_held_at is not None
    assert events.count("portal.password_created") == 1
    assert events.count("portal.password_sent") == 2


def test_login_hands_out_the_stored_password(client, agency_a, domain_a, membership_a, fake) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    made = _ask(client, application, token, domain_a, {"page": "signup", "host": HOST}).json()

    login = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert login.status_code == 200
    assert login.json() == made


def test_login_with_nothing_held_is_the_student_s_turn(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert response.status_code == 409
    assert response.json() == {"error": "no_portal_password"}
    assert fake.store == {}


@pytest.mark.parametrize("host", ["login.example.com", "apply.example.edu.evil.com", ""])
def test_another_host_gets_nothing(client, agency_a, domain_a, membership_a, fake, host) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(client, application, token, domain_a, {"page": "signup", "host": host})

    assert response.status_code == 409
    assert response.json() == {"error": "wrong_host"}
    assert fake.store == {}


def test_a_taken_over_account_is_never_logged_into(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    from django.utils import timezone

    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    _ask(client, application, token, domain_a, {"page": "signup", "host": HOST})
    with tenant_scope(agency_a.id):
        application.student.portal_accounts.update(student_managed_at=timezone.now())

    response = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert response.status_code == 409
    assert response.json() == {"error": "student_managed"}


def test_an_account_registered_by_hand_gets_no_new_password(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    from django.utils import timezone

    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        application.student.portal_accounts.update(registered_at=timezone.now())

    response = _ask(client, application, token, domain_a, {"page": "signup", "host": HOST})

    assert response.status_code == 409
    assert response.json() == {"error": "registered_without_us"}
    assert fake.store == {}


def test_a_box_too_short_for_a_strong_password_writes_nothing(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(
        client, application, token, domain_a, {"page": "signup", "host": HOST, "max_length": 8}
    )

    assert response.status_code == 409
    assert response.json() == {"error": "password_rules"}
    assert fake.store == {}


@pytest.mark.parametrize(
    "body",
    [{"page": "register", "host": HOST}, {"page": "login"}, {"page": "login", "host": HOST, "x": 1},
     {"page": "signup", "host": HOST, "max_length": 0}],
)
def test_a_malformed_ask_is_refused(client, agency_a, domain_a, membership_a, fake, body) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(client, application, token, domain_a, body)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


def test_another_student_s_application_is_404(
    client, agency_a, domain_a, membership_a, fake, django_user_model
) -> None:
    from apps.tenancy.models import Membership

    application, _ = _setup(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        other_user = django_user_model.objects.create_user(username="other", password="x")
        other = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT
        )
    token = _pair(client, agency_a, other, domain_a)

    response = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert response.status_code == 404
```


- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_portal_login.py -q`
Expected: FAIL. The route 404s because it does not exist.

- [ ] **Step 4: Write the route** in `apps/portals/ext_api.py`, after `registration`:

```python
#: A login page is met once per visit. Thirty an hour is a student coming back
#: through many logouts; more is a loop, or a page asking on purpose.
_PORTAL_LOGIN_RATE_LIMIT = 30


class _PortalLoginAsk(BaseModel):
    """Which page the extension is standing on, and its host. `host` is checked
    against the account's own portal host: the password is for that site only."""

    model_config = ConfigDict(extra="forbid")

    page: Literal["login", "signup"]
    host: str = Field(max_length=253)
    max_length: int | None = Field(default=None, ge=1, le=512)


@require_POST
@_device_endpoint
def portal_login(
    request: HttpRequest, pairing: ExtensionPairing, application_id: UUID
) -> HttpResponse:
    """The account's address and password, for the portal's own login or sign-up
    page (spec 2026-10-09 §6, D3).

    `signup` makes the password on first use (credentials.create_password is
    create-once, so a reloaded page gets the same one); `login` only reads one
    we made. Refused when the student took the account over, when they
    registered without us (we never made a password, so there is none to type),
    or when the page is on any other host than the account's.

    Secrets Manager is called outside the tenant transaction: an AWS round trip
    is not something to hold a row lock across. Never logs the password; the
    response is no-store so no cache between here and the extension keeps it.
    """
    _limit("ext-portal-login", pairing, _PORTAL_LOGIN_RATE_LIMIT)
    application = _application_for(pairing, application_id)
    try:
        ask = _PortalLoginAsk.model_validate(_json_body(request))
    except ValidationError as error:
        raise _ApiError(400, "invalid_request") from error
    with tenant_transaction(application.tenant_id):
        account = tags.account_for(application)
    if account is None or not account.address:
        raise _ApiError(409, "no_portal_address")
    if ask.host.casefold() != account.portal_host.casefold():
        raise _ApiError(409, "wrong_host")
    if account.student_managed_at is not None:
        raise _ApiError(409, "student_managed")
    where = {
        "tenant_id": application.tenant_id,
        "student_id": application.student_id,
        "portal_host": account.portal_host,
    }
    events = ["portal.password_sent"]
    if account.password_held_at is not None:
        password = credentials.password_for(**where)
    elif ask.page == "signup":
        if account.registered_at is not None:
            raise _ApiError(409, "registered_without_us")
        try:
            password = credentials.create_password(
                **where, username=account.address, max_length=ask.max_length
            )
        except credentials.PasswordRulesUnmet as unmet:
            raise _ApiError(409, "password_rules") from unmet
        events.insert(0, "portal.password_created")
    else:
        password = None
    if password is None:
        raise _ApiError(409, "no_portal_password")
    now = timezone.now()
    with tenant_transaction(application.tenant_id):
        PortalAccount.objects.filter(pk=account.pk, password_held_at__isnull=True).update(
            password_held_at=now
        )
        for event in events:
            AuditEvent.objects.create(
                tenant_id=application.tenant_id,
                actor=pairing.membership,
                actor_kind=AuditEvent.ActorKind.HUMAN,
                event=event,
                object_id=account.id,
            )
    response = JsonResponse({"username": account.address, "password": password})
    response["Cache-Control"] = "no-store"
    return response
```

Add `from . import credentials` beside the module's other `from . import …` lines. `AuditEvent`, `Literal`, `PortalAccount`, `tags` and `timezone` are already imported in this module; check them with `grep -n "^from\|^import" apps/portals/ext_api.py` and add any that are missing.

In `apps/portals/urls.py`, after the `registration` path:

```python
    path(
        "ext/applications/<uuid:application_id>/portal-login",
        ext_api.portal_login,
        name="portals-ext-portal-login",
    ),
```

- [ ] **Step 5: Run the tests, the ext_api suite, and the erasure coverage tests**

Run: `POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_portal_login.py tests/portals/test_ext_api.py tests/audit -q && uv run python manage.py makemigrations --check --dry-run`
Expected: PASS and "No changes detected".

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add apps/portals/models.py apps/portals/migrations apps/audit/redaction.py apps/portals/ext_api.py apps/portals/urls.py tests/portals/test_portal_login.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(portals): /ext portal-login hands the account's password to its own portal host only, audited"
```

---

### Task 3: The KMS key and the web tier's grant

**Files:**
- Modify: `infra/template.yaml` (a new `PortalCredentialsKey` resource beside the other top-level security resources; two statements in `WebTaskRole`'s policy after the `elmify/mailbox/*` statement at about line 1613; one env entry in `WebTaskDefinition`'s container `Environment` after `MAILBOX_QUEUE_URL`)
- Modify: the `WorkerTaskRole` comment at about line 1675, which names `apps/portals/auth.py::SecretsManagerCredentials`; point it at `apps/portals/credentials.py`
- Test: `tests/infra/test_template.py`

**Interfaces:**
- Consumes: `PORTAL_SECRETS_KMS_KEY_ID` (Task 1).
- Produces: the resource `PortalCredentialsKey`, and the env var on the web task.

- [ ] **Step 1: Write the failing tests** at the end of `tests/infra/test_template.py`:

```python
def _portal_statements(role: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        statement
        for policy in role["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if "elmify/portal/*" in str(statement.get("Resource", ""))
    ]


def test_the_web_tier_creates_reads_and_deletes_portal_passwords_and_never_lists(
    template: Template,
) -> None:
    """apps/portals/ext_api.py::portal_login creates and reads; the student's
    takeover (views.portal_takeover) deletes. Never ListSecrets."""
    portal = _portal_statements(template.resource("WebTaskRole"))
    actions = {
        action
        for statement in portal
        for action in ([statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"])
    }
    assert actions == {
        "secretsmanager:CreateSecret",
        "secretsmanager:GetSecretValue",
        "secretsmanager:DeleteSecret",
    }


def test_portal_passwords_have_their_own_rotating_key_used_only_through_secrets_manager(
    template: Template,
) -> None:
    key = template.resource("PortalCredentialsKey")
    assert key["Type"] == "AWS::KMS::Key"
    assert key["Properties"]["EnableKeyRotation"] is True
    statements = [
        statement
        for policy in template.resource("WebTaskRole")["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if "PortalCredentialsKey" in str(statement.get("Resource", ""))
    ]
    assert len(statements) == 1
    assert set(statements[0]["Action"]) == {"kms:Decrypt", "kms:GenerateDataKey"}
    assert "kms:ViaService" in str(statements[0]["Condition"])


def test_the_web_task_names_the_portal_key(template: Template) -> None:
    containers = template.resource("WebTaskDefinition")["Properties"]["ContainerDefinitions"]
    env = {item["Name"]: item["Value"] for c in containers for item in c.get("Environment", [])}
    assert "PortalCredentialsKey" in str(env["PORTAL_SECRETS_KMS_KEY_ID"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/infra/test_template.py -q -k "portal_passwords or portal_key or web_tier_creates"`
Expected: FAIL. `PortalCredentialsKey is not defined in infra/template.yaml`.

- [ ] **Step 3: Edit the template.** Add the resource:

```yaml
  # Students' portal passwords (spec 2026-10-09 §6, D3; apps/portals/credentials.py).
  # Their own key, so the default aws/secretsmanager key -- which every other
  # secret here uses -- decrypts none of them, and disabling this one stops
  # every portal password at once.
  PortalCredentialsKey:
    Type: AWS::KMS::Key
    Properties:
      Description: Encrypts elmify/portal/* secrets (students' portal passwords)
      EnableKeyRotation: true
      KeyPolicy:
        Version: "2012-10-17"
        Statement:
          - Sid: AccountAdministersThroughIam
            Effect: Allow
            Principal:
              AWS: !Sub "arn:aws:iam::${AWS::AccountId}:root"
            Action: "kms:*"
            Resource: "*"
```

In `WebTaskRole`, after the `elmify/mailbox/*` statement:

```yaml
              # apps/portals/ext_api.py::portal_login creates a student's portal
              # password on their first sign-up and reads it for the extension
              # on every login; the student's "I changed my password"
              # (apps/portals/views.py::portal_takeover) deletes it. Never
              # ListSecrets, for the reason given on the mailbox grant above.
              - Effect: Allow
                Action:
                  - secretsmanager:CreateSecret
                  - secretsmanager:GetSecretValue
                  - secretsmanager:DeleteSecret
                Resource: !Sub "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:elmify/portal/*"
              - Effect: Allow
                Action:
                  - kms:Decrypt
                  - kms:GenerateDataKey
                Resource: !GetAtt PortalCredentialsKey.Arn
                Condition:
                  StringEquals:
                    kms:ViaService: !Sub "secretsmanager.${AWS::Region}.amazonaws.com"
```

In `WebTaskDefinition`'s `Environment`, after `MAILBOX_QUEUE_URL`:

```yaml
            # apps/portals/credentials.py encrypts portal passwords under this
            # key; the web tier is the only task that creates them.
            - Name: PORTAL_SECRETS_KMS_KEY_ID
              Value: !Ref PortalCredentialsKey
```

`WorkerTaskRole` keeps only `secretsmanager:DeleteSecret` on `elmify/portal/*`, which needs no KMS permission. Do not widen it.

- [ ] **Step 4: Run the whole template suite**

Run: `uv run pytest tests/infra -q`
Expected: PASS. A failing cfn-lint test there is a real template error: fix the YAML, never the test.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add infra/template.yaml tests/infra/test_template.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "infra: portal passwords under their own rotating KMS key; the web tier creates, reads and deletes them"
```

---

### Task 4: "Portal logins" on the student's settings

**Files:**
- Modify: `apps/portals/views.py`, `apps/portals/urls.py`
- Create: `templates/student/settings_portals.html`
- Modify: `templates/student/settings.html` (one list item)
- Test: `tests/portals/test_portal_logins_page.py`

**Interfaces:**
- Consumes: `credentials.password_for`, `credentials.delete_password` (Task 1); `PortalAccount.password_held_at` and `.student_managed_at` (Task 2).
- Produces:
  - the routes `student-settings-portals` (GET `student/settings/portals/`), `student-settings-portal-reveal` (POST `student/settings/portals/<uuid:account_id>/reveal/`) and `student-settings-portal-takeover` (POST `student/settings/portals/<uuid:account_id>/takeover/`);
  - `AuditEvent` events `portal.password_revealed` and `portal.password_handed_over`, both HUMAN with `actor=student`.

- [ ] **Step 1: Write the failing tests**

```python
"""The student's own portal logins: shown on request after a password re-check,
and handed over for good with one button."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from apps.funding.models import AuditEvent
from apps.portals import credentials
from apps.portals.credentials import secret_id
from apps.tenancy.context import tenant_scope
from tests.portals.test_credentials import FakeSecrets

pytestmark = pytest.mark.django_db

HOST = "apply.example.edu"
PASSWORD = "Gq7-xR2!mN8_vL4.kP9#wT3z"


@pytest.fixture
def fake(monkeypatch):
    store = FakeSecrets()
    monkeypatch.setattr(credentials, "_client", lambda client=None: store)
    return store


@pytest.fixture
def held(agency_a, membership_a, fake):
    from django.utils import timezone

    from apps.portals.models import PortalAccount

    with tenant_scope(agency_a.id):
        account = PortalAccount.objects.create(
            tenant=agency_a, student=membership_a, portal_host=HOST, tag="k3x9",
            address="leyla.apply+k3x9@outlook.com", password_held_at=timezone.now(),
        )
    fake.store[secret_id(agency_a.id, membership_a.id, HOST)] = json.dumps(
        {"username": account.address, "password": PASSWORD}
    )
    return account


def test_the_page_lists_the_login_and_hides_the_password(client, user_a, domain_a, held) -> None:
    client.force_login(user_a)
    page = client.get("/student/settings/portals/", HTTP_HOST=domain_a.host)
    assert page.status_code == 200
    body = page.content.decode()
    assert HOST in body and held.address in body
    assert PASSWORD not in body


def test_the_right_password_reveals_it_once_and_leaves_a_trail(
    client, user_a, domain_a, held, agency_a, user_a_password
) -> None:
    client.force_login(user_a)
    page = client.post(
        f"/student/settings/portals/{held.id}/reveal/",
        {"password": user_a_password},
        HTTP_HOST=domain_a.host,
    )
    assert page.status_code == 200
    assert PASSWORD in page.content.decode()
    assert page["Cache-Control"] == "no-store"
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(
            event="portal.password_revealed", object_id=held.id
        ).count() == 1


def test_a_wrong_password_reveals_nothing(client, user_a, domain_a, held, agency_a) -> None:
    client.force_login(user_a)
    page = client.post(
        f"/student/settings/portals/{held.id}/reveal/", {"password": "nope"}, HTTP_HOST=domain_a.host
    )
    assert PASSWORD not in page.content.decode()
    with tenant_scope(agency_a.id):
        assert not AuditEvent.objects.filter(event="portal.password_revealed").exists()


def test_guessing_is_rate_limited(client, user_a, domain_a, held, user_a_password) -> None:
    client.force_login(user_a)
    for _ in range(5):
        client.post(f"/student/settings/portals/{held.id}/reveal/", {"password": "nope"}, HTTP_HOST=domain_a.host)
    page = client.post(
        f"/student/settings/portals/{held.id}/reveal/", {"password": user_a_password}, HTTP_HOST=domain_a.host
    )
    assert page.status_code == 429
    assert PASSWORD not in page.content.decode()


def test_takeover_deletes_our_copy_and_stops_the_co_pilot(
    client, user_a, domain_a, held, agency_a, fake
) -> None:
    client.force_login(user_a)
    response = client.post(f"/student/settings/portals/{held.id}/takeover/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert fake.store == {}
    with tenant_scope(agency_a.id):
        held.refresh_from_db()
        assert held.student_managed_at is not None
        assert AuditEvent.objects.filter(event="portal.password_handed_over", object_id=held.id).exists()


def test_another_student_s_account_is_404(client, domain_a, held, django_user_model, agency_a) -> None:
    from apps.tenancy.models import Membership

    other = django_user_model.objects.create_user(username="other2", password="x")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=other, role=Membership.Role.STUDENT)
    client.force_login(other)
    assert client.post(
        f"/student/settings/portals/{held.id}/reveal/", {"password": "x"}, HTTP_HOST=domain_a.host
    ).status_code == 404
    assert client.post(
        f"/student/settings/portals/{held.id}/takeover/", HTTP_HOST=domain_a.host
    ).status_code == 404
```

`user_a` (`tests/conftest.py:389`) is created with no usable password, and `tests/portals/conftest.py` does not exist yet. Create it with this fixture:

```python
import pytest


@pytest.fixture
def user_a_password(user_a):
    user_a.set_password("correct horse battery staple")
    user_a.save(update_fields=["password"])
    return "correct horse battery staple"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_portal_logins_page.py -q`
Expected: FAIL with 404 on `/student/settings/portals/`.

- [ ] **Step 3: Write the views** in `apps/portals/views.py`:

```python
#: Revealing a portal password re-checks the student's own Elmify password; five
#: tries in fifteen minutes is a person mistyping, more is guessing.
_REVEAL_LIMIT = 5
_REVEAL_WINDOW_SECONDS = 900


def _own_account(request: HttpRequest, account_id: UUID) -> tuple[Membership, PortalAccount]:
    student = current_membership(request, Membership.Role.STUDENT)
    return student, get_object_or_404(PortalAccount, id=account_id, student=student)


def _portals_page(
    request: HttpRequest, student: Membership, *, shown: UUID | None = None,
    password: str = "", error: str = "", status: int = 200,
) -> HttpResponse:
    accounts = PortalAccount.objects.filter(student=student).exclude(address="").order_by("portal_host")
    response = render(
        request,
        "student/settings_portals.html",
        {"accounts": accounts, "shown": shown, "password": password, "error": error},
        status=status,
    )
    # A revealed password must not sit in a shared cache or the back button's.
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def portal_logins(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    return _portals_page(request, student)


@login_required
@require_POST
def portal_reveal(request: HttpRequest, account_id: UUID) -> HttpResponse:
    """The password, once, after the student proves it is them (spec §6)."""
    student, account = _own_account(request, account_id)
    if rate_limited(
        "portal-reveal", request.user.pk, limit=_REVEAL_LIMIT, window_seconds=_REVEAL_WINDOW_SECONDS
    ):
        return _portals_page(request, student, error="Too many tries. Wait a few minutes.", status=429)
    if not request.user.check_password(request.POST.get("password", "")):
        return _portals_page(request, student, error="That is not your Elmify password.")
    if account.password_held_at is None or account.student_managed_at is not None:
        return _portals_page(request, student, error="We do not hold a password for this portal.")
    password = credentials.password_for(
        tenant_id=account.tenant_id, student_id=student.id, portal_host=account.portal_host
    )
    if password is None:
        return _portals_page(request, student, error="We could not read it just now. Try again.")
    AuditEvent.objects.create(
        tenant_id=account.tenant_id, actor=student, actor_kind=AuditEvent.ActorKind.HUMAN,
        event="portal.password_revealed", object_id=account.id,
    )
    return _portals_page(request, student, shown=account.id, password=password)


@login_required
@require_POST
def portal_takeover(request: HttpRequest, account_id: UUID) -> HttpResponse:
    """"I changed my password": our copy is deleted first, then the account is
    marked, so a failed delete never reads as handed over."""
    student, account = _own_account(request, account_id)
    credentials.delete_password(
        tenant_id=account.tenant_id, student_id=student.id, portal_host=account.portal_host
    )
    PortalAccount.objects.filter(pk=account.pk).update(student_managed_at=timezone.now())
    AuditEvent.objects.create(
        tenant_id=account.tenant_id, actor=student, actor_kind=AuditEvent.ActorKind.HUMAN,
        event="portal.password_handed_over", object_id=account.id,
    )
    messages.success(request, f"We no longer log in to {account.portal_host} for you.")
    return redirect("student-settings-portals")
```

Add the imports this needs:
- `from django.utils import timezone`
- `from apps.funding.models import AuditEvent`
- `from apps.ratelimit import rate_limited`
- `from . import credentials`
- `PortalAccount` in the `from .models import …` line

Routes, in `apps/portals/urls.py` after `student-settings-extension-disconnect`:

```python
    path("student/settings/portals/", views.portal_logins, name="student-settings-portals"),
    path(
        "student/settings/portals/<uuid:account_id>/reveal/",
        views.portal_reveal,
        name="student-settings-portal-reveal",
    ),
    path(
        "student/settings/portals/<uuid:account_id>/takeover/",
        views.portal_takeover,
        name="student-settings-portal-takeover",
    ),
```

`templates/student/settings_portals.html`:

```html
{% extends "base.html" %}
{% block title %}Portal logins{% endblock %}
{% block content %}
  <h1>Portal logins</h1>
  <p>The co-pilot creates your account on each university portal and logs in for you. You can always log in yourself with these details.</p>
  {% if error %}<p role="alert">{{ error }}</p>{% endif %}
  {% for account in accounts %}
    <article aria-labelledby="portal-{{ account.id }}">
      <h2 id="portal-{{ account.id }}">{{ account.portal_host }}</h2>
      <p>Email: {{ account.address }}</p>
      {% if account.student_managed_at %}
        <p>You manage this login yourself. We do not keep its password.</p>
      {% elif account.password_held_at %}
        {% if shown == account.id %}
          <p>Password: <code>{{ password }}</code></p>
        {% else %}
          <p>Password: ••••••••</p>
          <form method="post" action="{% url 'student-settings-portal-reveal' account.id %}">
            {% csrf_token %}
            <label for="confirm-{{ account.id }}">Your Elmify password, to show it</label>
            <input type="password" id="confirm-{{ account.id }}" name="password" autocomplete="current-password" required>
            <button type="submit">Show password</button>
          </form>
        {% endif %}
        <form method="post" action="{% url 'student-settings-portal-takeover' account.id %}">
          {% csrf_token %}
          <button type="submit">I changed my password</button>
        </form>
      {% else %}
        <p>No password kept: the co-pilot has not signed you up here.</p>
      {% endif %}
    </article>
  {% empty %}
    <p>No portal accounts yet.</p>
  {% endfor %}
{% endblock %}
```

In `templates/student/settings.html`, after the extension item:
`<li><a href="/student/settings/portals/">Portal logins</a> — the accounts the co-pilot made for you</li>`.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_portal_logins_page.py tests/portals -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add apps/portals/views.py apps/portals/urls.py templates/student/settings_portals.html templates/student/settings.html tests/portals/test_portal_logins_page.py tests/portals/conftest.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(portals): the student sees each portal login, reveals its password after a re-check, and can take it over"
```

---

### Task 5: The worker's `portal-login` message

**Files:**
- Modify: `extension/src/api.ts` (one function after `postAddress`)
- Modify: `extension/src/service_worker.ts` (`messageRefusal`, `CONTENT_TYPES`, `contentRefusal`, `handle`)
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Consumes: the route from Task 2.
- Produces:
  - the content message `{type: "portal-login", applicationId, page: "login"|"signup", host: string, max_length?: number}`, answered with `{ok: true, username, password}` or `{ok: false, code}`;
  - `api.postPortalLogin(origin, applicationId, ask) -> Promise<{username: string; password: string}>`.

- [ ] **Step 1: Write the failing e2e tests** in `tests/portals/test_extension_e2e.py`, after the last worker test:

```python
LOGIN_REPLY = {"username": TAGGED, "password": "Gq7-xR2!mN8_vL4.kP9#wT3z"}


def _portal_login(page, extra=None, sender=CONTENT):
    message = {"type": "portal-login", "applicationId": APP_A, "page": "login", "host": "portal.example"}
    return _send(page, {**message, **(extra or {})}, sender)


@pytest.mark.extension
def test_the_worker_hands_the_login_to_its_own_tab_and_keeps_no_copy(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page) == {"ok": True, **LOGIN_REPLY}
    assert LOGIN_REPLY["password"] not in json.dumps(page.evaluate("() => window.__session"))
    sent = [body for key, body in page.evaluate("() => window.__fetched") if key.endswith("/portal-login")]
    assert sent == [{"page": "login", "host": "portal.example"}]


@pytest.mark.extension
@pytest.mark.parametrize(
    ("extra", "sender", "code"),
    [
        ({"host": "login.example.com"}, CONTENT, "untrusted_sender"),
        ({"page": "reset"}, CONTENT, "invalid_message"),
        ({"max_length": "24"}, CONTENT, "invalid_message"),
        ({}, PANEL_SENDER, "untrusted_sender"),
        ({}, {**CONTENT, "frameId": 3}, "untrusted_sender"),
        ({}, {**CONTENT, "origin": "https://evil.example"}, "untrusted_sender"),
    ],
)
def test_a_login_goes_to_no_other_host_frame_or_sender(browser_context, extra, sender, code) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [200, LOGIN_REPLY]},
        session=_binding(),
    )
    assert _portal_login(page, extra, sender) == {"ok": False, "code": code}
    assert not [k for k, _ in page.evaluate("() => window.__fetched") if k.endswith("/portal-login")]


@pytest.mark.extension
def test_a_server_refusal_reaches_the_page_as_its_code(browser_context) -> None:
    page = _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {f"POST /ext/applications/{APP_A}/portal-login": [409, {"error": "student_managed"}]},
        session=_binding(),
    )
    assert _portal_login(page) == {"ok": False, "code": "student_managed"}
```

`PORTAL` is `https://portal.example`, so its host is `portal.example`.

- [ ] **Step 2: Build and run them to verify they fail**

Run: `npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py -q -k "login_to_its_own_tab or no_other_host or refusal_reaches"`
Expected: FAIL. With no handler for the type, the reply is `undefined`.

- [ ] **Step 3: Implement.** In `extension/src/api.ts`, after `postAddress`:

```ts
/** The account's login for the portal page the content script stands on
 *  (spec 2026-10-09 §6). Returned to the caller only -- never stored. */
export async function postPortalLogin(
  origin: string,
  applicationId: string,
  ask: { page: "login" | "signup"; host: string; max_length?: number },
): Promise<{ username: string; password: string }> {
  return (await call(origin, `/ext/applications/${applicationId}/portal-login`, {
    method: "POST",
    body: JSON.stringify(ask),
  })) as { username: string; password: string };
}
```

In `service_worker.ts`:
- import `postPortalLogin`;
- add `const KNOWN_LOGIN_PAGES = new Set(["login", "signup"]);` beside `KNOWN_LANGS`;
- in `messageRefusal`, before `return null`:

```ts
  if (message["type"] === "portal-login") {
    if (!sender.tab) return "untrusted_sender";
    if (!KNOWN_LOGIN_PAGES.has(message["page"] as string)) return "invalid_message";
    const max = message["max_length"];
    if (max !== undefined && !(Number.isInteger(max) && (max as number) >= 1 && (max as number) <= 512)) {
      return "invalid_message";
    }
  }
```

Add `"portal-login"` to `CONTENT_TYPES`. In `contentRefusal`, after the `snapshot` check:

```ts
  // The password is for the binding's own host: a page that moved to a
  // single-sign-on host, or any other, asks for nothing (spec §6).
  if (message["type"] === "portal-login" && message["host"] !== new URL(binding.origin).hostname) {
    return "untrusted_sender";
  }
```

In `handle`, after the `address` case:

```ts
  if (message?.type === "portal-login") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      try {
        const login = await postPortalLogin(origin, message.applicationId, {
          page: message.page,
          host: message.host,
          ...(message.max_length ? { max_length: message.max_length } : {}),
        });
        // Straight back to the page that asked. Never in storage, the dock or
        // a log: the extension holds a portal password only for this reply.
        sendResponse({ ok: true, username: login.username, password: login.password });
      } catch (error) {
        sendResponse({ ok: false, code: error instanceof ExtError ? error.code : "request_failed" });
      }
    })();
    return true;
  }
```

- [ ] **Step 4: Typecheck, build, run the e2e and bundle suites**

Run: `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py tests/portals/test_extension_bundle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add extension/src/api.ts extension/src/service_worker.ts tests/portals/test_extension_e2e.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(extension): the worker fetches a portal login for its bound tab's own host and keeps no copy"
```

---

### Task 6: Typing the login and the sign-up on the page

**Files:**
- Create: `extension/src/content/credentials.ts`
- Modify: `extension/src/content/index.ts`. Replace `loginPage` and its call site in `run()`. Add one test hook beside `__elmify_run`.
- Modify: `extension/src/panel/i18n.ts`. Add `m_log_in_typed` and `m_sign_up_typed` in all four languages, beside `m_log_in`.
- Create: `tests/portals/fixtures/signup.html`, `tests/portals/fixtures/login_two_boxes.html`
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Consumes:
  - the worker message from Task 5;
  - `fillVerified` (`content/fill.ts`), `visible` (`content/verify.ts`) and `checkAddress` (`content/address.ts`).
- Produces:
  - `credentialPage(): CredentialPage | null`;
  - `typeCredentials(page: CredentialPage, username: string, password: string): boolean`;
  - the dock messages `log_in_typed` and `sign_up_typed`, both with `status: "login"`.

- [ ] **Step 1: Write the fixtures**

`tests/portals/fixtures/signup.html`:

```html
<!doctype html>
<html>
<body>
<form>
  <label for="given">First name</label><input id="given" type="text">
  <label for="email">Email</label><input id="email" type="email">
  <label for="pw">Password</label><input id="pw" type="password" autocomplete="new-password" maxlength="30">
  <label for="pw2">Repeat password</label><input id="pw2" type="password">
  <button type="submit">Register</button>
</form>
</body>
</html>
```

`tests/portals/fixtures/login_two_boxes.html`:

```html
<!doctype html>
<html>
<body>
<form>
  <label for="number">Applicant number</label><input id="number" type="text">
  <label for="birth">Date of birth</label><input id="birth" type="text">
  <label for="password">Password</label><input id="password" type="password">
</form>
</body>
</html>
```

- [ ] **Step 2: Write the failing e2e tests**

```python
@pytest.mark.extension
def test_a_login_page_gets_the_held_login_typed_and_nothing_pressed(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}},
    )
    page.evaluate("() => { window.__submitted = false; document.querySelector('form').addEventListener('submit', (e) => { window.__submitted = true; e.preventDefault(); }); }")

    _deliver(page, _start("en", fixture_server))

    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    sent = page.evaluate("() => window.__sent")
    asked = [m for m in sent if m["type"] == "portal-login"]
    assert asked == [{"type": "portal-login", "applicationId": "app-1", "page": "login", "host": "127.0.0.1"}]
    assert page.input_value("#username") == TAGGED
    assert page.input_value("#password") == LOGIN_REPLY["password"]
    assert [m["patch"] for m in sent if m["type"] == "dock"] == [{"status": "login", "message": "log_in_typed"}]
    assert page.evaluate("() => window.__submitted") is False
    assert LOGIN_REPLY["password"] not in json.dumps(sent)  # nothing the page sent carries it


@pytest.mark.extension
def test_with_no_login_held_the_student_logs_in_and_nothing_is_typed(
    browser_context, fixture_server
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": False, "code": "no_portal_password"}},
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    assert page.input_value("#password") == ""
    docks = [m["patch"] for m in page.evaluate("() => window.__sent") if m["type"] == "dock"]
    assert docks == [{"status": "login", "message": "log_in"}]


@pytest.mark.extension
def test_two_boxes_before_the_password_mean_nothing_is_typed(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login_two_boxes.html")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}},
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    sent = page.evaluate("() => window.__sent")
    assert _of_type(sent, "portal-login") == []
    assert page.input_value("#password") == "" and page.input_value("#number") == ""


@pytest.mark.extension
def test_a_box_the_student_already_typed_in_is_not_overwritten(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/login.html")
    page.fill("#password", "their-own")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}},
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'dock')")
    assert page.input_value("#password") == "their-own"
    docks = [m["patch"] for m in page.evaluate("() => window.__sent") if m["type"] == "dock"]
    assert docks == [{"status": "login", "message": "log_in"}]


@pytest.mark.extension
def test_a_sign_up_gets_the_address_and_one_password_in_both_boxes(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/signup.html")
    _content_with_listener(
        page,
        {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}},
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function(
        "() => window.__sent.some((m) => m.type === 'dock' && m.patch.message === 'sign_up_typed')"
    )
    sent = page.evaluate("() => window.__sent")
    asked = _of_type(sent, "portal-login")
    assert asked[0]["page"] == "signup" and asked[0]["max_length"] == 30
    assert page.input_value("#email") == TAGGED
    assert page.input_value("#pw") == LOGIN_REPLY["password"] == page.input_value("#pw2")
    assert page.input_value("#given") == ""  # the rest of a sign-up page is the ordinary fill's
    assert {"type": "address", "applicationId": "app-1", "event": "given"} in sent
```

`_of_type(sent, kind)` exists at about line 527, and `TAGGED` at line 496. Also update `test_a_login_page_asks_the_student_to_log_in_and_touches_nothing`. Its stub now answers the `portal-login` ask with the default `{ok: true}`, which carries no password. That still ends in `log_in` with nothing typed. Keep its assertions and add `"portal-login": {"ok": False, "code": "no_portal_password"}` to its replies, so it states the case it covers.

- [ ] **Step 3: Build and run them to verify they fail**

Run: `npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py -q -k "login or sign_up or two_boxes or already_typed"`
Expected: FAIL. The login test sees `log_in`, and no `portal-login` message was sent.

- [ ] **Step 4: Write `extension/src/content/credentials.ts`**

```ts
/**
 * The portal's own login and sign-up pages (spec 2026-10-09 §6, D3).
 *
 * Read the way a password manager reads them, not from a FieldMap: a password
 * box is the one control a page cannot disguise, so the page kind and the
 * password boxes come from `type="password"` alone. The address goes into the
 * one box before the first password box that asks for it -- and when that is
 * not exactly one box, nothing is typed at all, because a password in the
 * wrong box is the mistake this file exists not to make. Never clicks: the
 * student presses Log in / Register.
 *
 * ponytail: a login whose username is a portal-issued number gets the address
 * typed into its one box and the portal refuses it -- the student logs in, as
 * before this plan. Learn the username box from the bench (plan 6) when a
 * measured portal needs it.
 */
import { fillVerified } from "./fill.js";
import type { VerifiedEntry } from "./verify.js";
import { visible } from "./verify.js";

export interface CredentialPage {
  kind: "login" | "signup";
  identifier: HTMLInputElement;
  passwords: HTMLInputElement[];
  /** The smallest maxlength any password box declares, or undefined. */
  maxLength?: number;
}

const BOXES = 'input[type="email"], input[type="text"], input:not([type])';

function usable(input: HTMLInputElement): boolean {
  return visible(input) && !input.disabled && !input.readOnly;
}

/** The address box: the single email-like box before the first password box,
 *  or else the single box of any kind there. Null when neither is single. */
function identifierFor(first: HTMLInputElement): HTMLInputElement | null {
  const scope: ParentNode = first.form ?? document;
  const before = Array.from(scope.querySelectorAll<HTMLInputElement>(BOXES)).filter(
    (input) => usable(input) && (first.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_PRECEDING) !== 0,
  );
  const emailLike = before.filter(
    (input) => input.type === "email" || ["email", "username"].includes(input.autocomplete),
  );
  if (emailLike.length === 1) return emailLike[0]!;
  return emailLike.length === 0 && before.length === 1 ? before[0]! : null;
}

export function credentialPage(): CredentialPage | null {
  const passwords = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="password"]')).filter(usable);
  if (passwords.length === 0) return null;
  const identifier = identifierFor(passwords[0]!);
  if (!identifier) return null;
  const signup = passwords.length >= 2 || passwords.some((box) => box.autocomplete === "new-password");
  const caps = passwords.map((box) => box.maxLength).filter((n) => n > 0);
  return {
    kind: signup ? "signup" : "login",
    identifier,
    passwords,
    ...(caps.length ? { maxLength: Math.min(...caps) } : {}),
  };
}

function entry(element: HTMLInputElement, value: string, key: string): VerifiedEntry {
  return { entry: { selector: "", method: "fill", value, profile_field: key }, element, ok: true, reason: "" };
}

/** True only when every box now holds what we typed. fillVerified never types
 *  over a box holding the student's own text, so a partial result means the
 *  student is already doing it, and they finish. */
export function typeCredentials(page: CredentialPage, username: string, password: string): boolean {
  const items = [
    entry(page.identifier, username, "portal.username"),
    ...page.passwords.map((box, i) => entry(box, password, `portal.password.${i}`)),
  ];
  return fillVerified(items, new Set()).filled.length === items.length;
}
```

- [ ] **Step 5: Wire it into `run()`** in `extension/src/content/index.ts`:
- import `credentialPage` and `typeCredentials` from `./credentials.js`;
- replace `loginPage` with `onFormPage`, which keeps its selector half;
- replace the call site with the branch below.

```ts
/** The page holds at least one of the form's own controls. */
function onFormPage(entries: PacketField[]): boolean {
  return entries.some((entry) => {
    try {
      return document.querySelector(entry.selector) !== null;
    } catch {
      return false;
    }
  });
}

/** Type the account's login, or a new account's sign-up, and hand the press to
 *  the student. Anything short of every box typed is the student's turn, as it
 *  was before the platform held passwords. */
async function signIn(
  applicationId: string,
  page: ReturnType<typeof credentialPage> & object,
  plain: string,
  stale: () => boolean,
): Promise<void> {
  const reply = await ask<{ ok: boolean; username?: unknown; password?: unknown }>({
    type: "portal-login",
    applicationId,
    page: page.kind,
    host: location.hostname,
    ...(page.maxLength ? { max_length: page.maxLength } : {}),
  }).catch(() => null);
  if (stale()) return;
  const login =
    reply?.ok && typeof reply.username === "string" && typeof reply.password === "string"
      ? { username: reply.username, password: reply.password }
      : null;
  if (!login || !typeCredentials(page, login.username, login.password)) {
    await dock({ status: "login", message: "log_in" });
    return;
  }
  if (page.kind === "signup") {
    // The address typed into a sign-up IS the registration (ext_api.address_report).
    const item: VerifiedEntry = {
      entry: { selector: "", method: "fill", value: login.username, profile_field: "contact.email" },
      element: page.identifier,
      ok: true,
      reason: "",
    };
    const verdict = plain ? await checkAddress(item, plain, false) : "kept";
    if (stale()) return;
    if (verdict === "form" || verdict === "page") {
      await ask({ type: "address", applicationId, event: "rejected", evidence: verdict });
    } else if (verdict === "kept") {
      await ask({ type: "address", applicationId, event: "given" });
    }
  }
  await dock({ status: "login", message: page.kind === "signup" ? "sign_up_typed" : "log_in_typed" });
}
```

In `run()`, replace

```ts
  if (loginPage(packet.entries)) {
    await dock({ status: "login", message: "log_in" });
    return;
  }
```

with

```ts
  if (!onFormPage(packet.entries)) {
    const credentials = credentialPage();
    if (credentials) {
      await signIn(applicationId, credentials, packet.plain_email ?? "", stale);
      return;
    }
    if (Array.from(document.querySelectorAll<HTMLElement>('input[type="password"]')).some(visible)) {
      // A password page whose address box we cannot name: the student's.
      await dock({ status: "login", message: "log_in" });
      return;
    }
  }
```

`checkAddress` already swaps to the plain address when the tagged one is refused, through `retype`. The sign-up path reuses it as-is. The type annotation `ReturnType<typeof credentialPage> & object` is just the non-null `CredentialPage`; import the interface and write `CredentialPage` instead if that reads better.

- [ ] **Step 6: Add the panel strings** in `extension/src/panel/i18n.ts`, beside each language's `m_log_in`:
- en:
  - `m_log_in_typed: "We typed your portal login. Press the portal's Log in button."`
  - `m_sign_up_typed: "We filled in your new portal account with a strong password we keep for you. Press the portal's Register button."`
- az:
  - `m_log_in_typed: "Portal girişinizi yazdıq. Portalın Daxil ol düyməsini basın."`
  - `m_sign_up_typed: "Yeni portal hesabınızı sizin üçün saxladığımız güclü şifrə ilə doldurduq. Portalın Qeydiyyat düyməsini basın."`
- tr:
  - `m_log_in_typed: "Portal giriş bilgilerinizi yazdık. Portalın Giriş düğmesine basın."`
  - `m_sign_up_typed: "Yeni portal hesabınızı sizin için sakladığımız güçlü bir şifreyle doldurduk. Portalın Kayıt düğmesine basın."`
- ru:
  - `m_log_in_typed: "Мы ввели ваш логин на портале. Нажмите кнопку входа на портале."`
  - `m_sign_up_typed: "Мы заполнили ваш новый аккаунт на портале надёжным паролем, который храним для вас. Нажмите кнопку регистрации на портале."`

- [ ] **Step 7: Typecheck, build, run the whole extension suite**

Run: `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py tests/portals/test_extension_bundle.py -q`
Expected: PASS, including `test_every_panel_string_exists_in_all_four_languages`.

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add extension/src/content/credentials.ts extension/src/content/index.ts extension/src/panel/i18n.ts tests/portals/fixtures/signup.html tests/portals/fixtures/login_two_boxes.html tests/portals/test_extension_e2e.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(extension): the co-pilot types the portal login and a new account's sign-up; the student presses the button"
```

---

### Task 7: Record the reversal

**Files:**
- Modify: `CLAUDE.md`. Edit the "Direction change, 2026-09-15" note under "The portal browser" and the first bullet of "Application automation (Phase 3)".
- Modify: `docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md` §3 step 2. It still says "the student sets their own password"; D3 and §6 say the co-pilot generates it.

- [ ] **Step 1: Edit CLAUDE.md.** In the 2026-09-15 direction-change note, the sentence "nothing of ours is in the browser to steal — no portal credential exists anywhere" gets this appended:

> **Reversed for portal passwords by D3 (2026-10-09 co-pilot spec §6):** the platform now creates and holds each student's portal password in Secrets Manager under `PortalCredentialsKey` (`apps/portals/credentials.py`). The web tier creates, reads and deletes it; the extension receives it only in the worker's reply to the login page's one ask. Every hand-out and every reveal leaves an `AuditEvent`. Erasure still destroys it through `advance_deletion`. PR #169 (retire the server portal tier) must keep `credentials.py` and `deletion.py`'s import of it when it is rebased: its current diff removes the erasure call along with `auth.py`.

In "Portal credentials never live in the database", replace "The IAM grant is per-secret-prefix and belongs to the portal-execution role only" with "The IAM grant is per-secret-prefix: the web tier (which mints the login for the extension) creates, reads and deletes; the worker only deletes, on erasure."

- [ ] **Step 2: Edit the spec's §3 step 2** to: "If the portal shows its login, the co-pilot types the student's portal login and the student presses Log in; if it is a first visit, the co-pilot fills the sign-up's address and a generated password (§6) and the student presses Register."

- [ ] **Step 3: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add CLAUDE.md docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md
git -C /home/orkhan/Desktop/copilot-guidance commit -m "docs: CLAUDE.md records the platform-held portal password and what PR #169 must keep"
```

---

## Not in this plan

- **Plan 3:** the portal's verification email, read from the inbox and typed or opened (`2026-10-10-copilot-guidance-3-mail-codes.md`).
- **Portal rules beyond `maxlength` and the four character kinds.** These are read from the bench's recorded `password_rules` (plan 6) once a measured portal refuses our password.
- **A username box that is not the address.** The bench learns it (plan 6).
- **Undoing a takeover** ("let the co-pilot log in again"). There is no request for it.
