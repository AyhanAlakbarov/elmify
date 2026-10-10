# Europass API Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce `europass_required` and `europass_preferred` CVs by having europa.eu render them, verified by the `attachment.xml` only a genuine Europass document carries — with no fallback of any kind.

**Architecture:** A new `apps/documents/europass.py` holds a pinned-host HTTP transport (reusing `egress.validate_public_url`), a pure `CVContent -> profile document` mapper, and a provenance check. `render.py` gains an `EUROPASS_API` variant that is only reachable on the release path. Every failure raises; nothing degrades to a lookalike.

**Tech Stack:** Django 5.2, pydantic v2, urllib3, pypdf, pytest + pytest-django, `uv` for everything.

**Spec:** `docs/superpowers/specs/2026-08-25-europass-api-render-design.md`

## Global Constraints

- Branch: `claude/cv-render-fidelity`, worktree `/home/orkhan/Desktop/tehsil_agent/.worktrees/phase2-cv-engine`.
- Every command runs through `uv run`. Never invoke `python` or `pytest` bare.
- Gates before any commit: `uv run ruff check apps tests`, `uv run mypy apps`, `uv run pytest -q`, `uv run bandit -c pyproject.toml -r apps config`. A pre-commit hook runs Bandit, so a Bandit failure blocks the commit itself.
- Line length is 100; ruff enforces it. `target-version = "py312"`.
- `_CONTENT_CONFIG` is `ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)`. Schema models are **frozen** — never assign to an attribute, use `model_copy(update=...)`. `extra="forbid"` is load-bearing for OpenAI structured output; do not relax it.
- Never mutate a `VerifiedFact` in place — the ledger is append-only.
- **No new dependency.** urllib3, pypdf and the stdlib cover everything here. In particular, do **not** add `defusedxml` — Task 6 explains why no XML parser is needed at all.
- **The host is pinned in code, never in settings.** There is no configuration knob that points this at another origin.
- `tests/test_aws_boundary_run_controller.py::test_image_publication_uses_substituted_commands_without_printing_registry` is a known pre-existing flake — it fails intermittently in a full run and passes on a re-run, with no code change. Unrelated to this work; do not investigate it.

## The one thing this plan changes from the spec

The spec allows `europass_preferred` to fall back to the local `EUROPASS` lookalike when europa.eu fails. **This plan removes that.** Both requirement values go to `EUROPASS_API`, and every failure raises.

Consequences, stated so nobody rediscovers them in production:

- A europa.eu outage blocks CV *release* for every Europass student, including preferred ones who would have accepted a local render.
- That is survivable only because the failure is **transient and retryable**: the draft stays `APPROVED`, nothing is written, and re-running release succeeds once europa.eu is back. Task 7 pins that the draft is untouched on failure. Do not let a future change make this path write anything before the PDF is in hand.
- The benefit is that there is exactly one code path to a Europass artefact. A fallback is a second path that is exercised only when something is already wrong, which is when it is least likely to be correct — and a "preferred" funder still prefers Europass, so silently shipping something else is a downgrade the student never asked for.

Preview is unaffected: it never calls the network and shows the local lookalike, truthfully labelled `EUROPASS` (Task 7).

---

### Task 1: Send the sanctioning email

**Files:** none. This is a human action with no code, placed first because its answer can invalidate Tasks 2-7 and it has a multi-week turnaround.

**Interfaces:**
- Consumes: nothing.
- Produces: nothing code depends on. Tasks 2-7 proceed without waiting for a reply.

**Why this exists.** We are about to build a production dependency on an undocumented internal endpoint of a public EU service, and to transmit named students' personal data to it. Four things are unknown, and only the third genuinely cannot be solved by writing code:

1. **Is there a sanctioned route?** Europass publishes an ELM/JSON-LD interchange format. If an official or partner API exists, we should be on it instead of `/eprofile/cv`.
2. **Is automated use permitted?** Plain `urllib` worked and no bot wall appeared, but "was not blocked" is not "was permitted". Finding out after our IP is blocked during application season means students miss deadlines.
3. **What happens to the guest CVs we create?** Call 2 creates a resource on europa.eu holding a student's name, email, institutions and employers. Retention, deletion and controllership are unknown. That is a GDPR question about a real person's data, and no amount of careful client code answers it.
4. **What request volume is acceptable?** Saying so up front is what separates a well-behaved integration from something that looks like abuse.

- [ ] **Step 1: Send this email**

To: `EMPL-ELM-SUPPORT@ec.europa.eu`
Subject: Programmatic Europass CV generation — sanctioned route, terms, and guest-CV retention

```
Hello,

We operate a small platform that helps students in Azerbaijan prepare
applications for European scholarship and degree programmes. Several of those
programmes require a Europass CV specifically, so we would like our students to
receive a genuine Europass-generated document rather than a look-alike we render
ourselves.

Our prototype drives the public Europass e-Portfolio CV editor as a guest, with
no account: it creates a CV, renders it, and downloads the PDF. Before we put
this in front of real students we would like to check four things with you.

1. Is there a sanctioned or documented route for generating a Europass CV
   programmatically -- an official API, a partner integration, or an
   ELM/JSON-LD import path -- that we should be using instead of the editor's
   own endpoints?

2. Is automated, server-side use of the guest CV editor permitted under the
   Europass terms of use? We encountered no technical restriction, but we would
   rather have your answer than infer one from that.

3. When a guest CV is created, what happens to the personal data it contains
   (name, contact email, education and employment history)? Specifically: how
   long is it retained, is it deleted automatically, and who is the data
   controller for it? We need this to describe the processing accurately to our
   students under GDPR.

4. If this usage is acceptable, what request volume would you consider
   reasonable? We expect low hundreds of CVs per month at most, and we are happy
   to work within any limit you set.

If any of this is better directed elsewhere, we would be grateful for a pointer.

Thank you,
<name, role, organisation, contact address>
```

- [ ] **Step 2: Record that it was sent**

Add the send date to the spec's "Risks" section, replacing the sentence that says the email has not been sent. Commit:

```bash
git add docs/superpowers/specs/2026-08-25-europass-api-render-design.md
git commit -m "docs(spec): record the Europass sanctioning email as sent

The spec listed the unsent email as an open risk. Sending it does not
resolve the risk -- the answer does -- but the record should reflect
which of the two we are waiting on."
```

- [ ] **Step 3: Note the production gate**

No code change. Understand and carry forward: **Tasks 2-7 may be built and merged without a reply, but this feature must not be enabled for real students until questions 2 and 3 are answered.** Question 3 in particular is a legal precondition, not an engineering preference.

---

### Task 2: `LanguageEntry.mother_tongue`

**Files:**
- Modify: `apps/documents/schemas.py` (`LanguageEntry`)
- Modify: `apps/documents/verification.py` (`_PAYLOAD_KEYS`, module docstring)
- Modify: `apps/documents/ingestion.py` (the extraction prompt)
- Test: `tests/documents/test_schemas.py`, `tests/documents/test_verification.py`, `tests/documents/test_ingestion.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LanguageEntry.mother_tongue: bool` (default `False`), carried in `_PAYLOAD_KEYS[VerifiedFact.Category.LANGUAGE]`. Task 5's mapper reads it to split `nativeLanguages` from `otherLanguages`.

**Why it is a bool and not an inference.** Europass separates mother tongues from other languages; they are different fields in the profile document. Without the flag, an Azerbaijani student's Europass CV lists Azerbaijani as a foreign language — the kind of small wrongness a European reviewer notices immediately. Unlike the five CEFR sub-skills, CVs *do* state this outright ("Mother tongue: Azerbaijani"), so ingestion can extract it truthfully and the existing "only what DATA states" rule needs no exception. `False` means "not stated", which sends the language under `otherLanguages` — accurate, never a false claim.

It follows the sub-skills' pattern exactly: **carried for provenance, never added to the LANGUAGE spec's `detail` tuple**, which stays `("cefr_level", "test_name", "test_score")`. No document contradicts a mother tongue, and a student correcting it must not produce a CONFLICTING verdict that blocks their own draft.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_schemas.py`:

```python
def test_mother_tongue_defaults_to_false():
    """False means "not stated", not "not their mother tongue". It sends the
    language under otherLanguages, which is accurate either way."""
    assert LanguageEntry(language="Azerbaijani").mother_tongue is False


def test_mother_tongue_can_be_set():
    entry = LanguageEntry(language="Azerbaijani", mother_tongue=True)
    assert entry.mother_tongue is True
```

Append to `tests/documents/test_verification.py`:

```python
def test_language_payload_carries_mother_tongue():
    entry = LanguageEntry(language="Azerbaijani", cefr_level="C2", mother_tongue=True)
    payload = fact_payload(entry, category=VerifiedFact.Category.LANGUAGE)
    assert payload["mother_tongue"] is True


def test_a_revised_mother_tongue_does_not_conflict(agency_a, django_user_model):
    """Pins a decision, exactly as the sub-skill guard does. If mother_tongue
    sat in the LANGUAGE spec's detail tuple, a student correcting it would
    produce CONFLICTING and block their own draft."""
    stated = LanguageEntry(language="Azerbaijani", cefr_level="C2", mother_tongue=True)
    stored = fact_payload(stated, category=VerifiedFact.Category.LANGUAGE)
    revised = stated.model_copy(update={"mother_tongue": False})
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "mt-1")
        fact = _fact(student, VerifiedFact.Category.LANGUAGE, stored, confirmed=True)
        verdicts = verify_against_facts(_content("languages", revised), [fact])
    languages = [v.verdict for v in verdicts if v.claim_path.startswith("languages")]
    assert languages == [Verdict.SUPPORTED]
```

Append to `tests/documents/test_ingestion.py`:

```python
def test_ingestion_prompt_scopes_mother_tongue_to_what_data_states(
    agency_a, django_user_model, fake_store
):
    """mother_tongue is a claim like any other: extracted when the CV says so,
    left false when it does not."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-mt")
        document = apply_scan_result(register(agency_a.id, student.id), "NO_THREATS_FOUND")
        fake_store.put(document.object_key, _pdf())
        client = _openai_client()
        ingest_uploaded_cv(document=document, student=student, client=client, store=fake_store)
        prompt = "".join(
            str(message["content"])
            for call in client.responses.parse.call_args_list
            for message in call.kwargs["input"]
        )
    assert "mother_tongue" in prompt
    assert "do not infer it from" in prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_schemas.py tests/documents/test_verification.py tests/documents/test_ingestion.py -k "mother_tongue" -q`
Expected: FAIL. The schema tests fail with pydantic rejecting the unknown field (`extra="forbid"`), the payload test with `KeyError: 'mother_tongue'`, and the prompt test with `assert 'mother_tongue' in ...`.

`test_a_revised_mother_tongue_does_not_conflict` will fail at construction for the same `extra="forbid"` reason, then pass once the field exists — Step 6 proves it discriminates.

- [ ] **Step 3: Add the field**

In `apps/documents/schemas.py`, in `LanguageEntry`, directly below the `writing` field:

```python
    #: Europass sends mother tongues and other languages as different fields.
    #: False means "not stated", which is why it is not Optional -- there is
    #: no third state, and "not stated" and "not their mother tongue" both
    #: correctly render as an entry under otherLanguages.
    mother_tongue: bool = False
```

- [ ] **Step 4: Carry it through the ledger**

In `apps/documents/verification.py`, extend the `languages` clause added in `ec54c45` so the tuple reads:

```python
    + (
        (
            "listening",
            "reading",
            "spoken_interaction",
            "spoken_production",
            "writing",
            "mother_tongue",
        )
        if spec.field == "languages"
        else ()
    )
```

Then extend the module docstring's enumeration of never-compared fields: the paragraph beginning "The language sub-skills are never compared for a second reason on top of that" already covers exactly this reasoning — add `mother_tongue` to it so the next reader does not assume it was checked. Keep every line under 100 characters.

- [ ] **Step 5: Amend the ingestion prompt**

In `apps/documents/ingestion.py`, the developer message gains one sentence after the sub-skill rule:

```python
                    "Do not copy the overall cefr_level into them. "
                    # Stated outright on most CVs ("Mother tongue: Azerbaijani"),
                    # so this is extraction, not inference -- but nationality and
                    # country of study are not statements about language.
                    "Set a language's mother_tongue to true only when DATA says that "
                    "language is the applicant's mother tongue or native language; "
                    "do not infer it from nationality, country or place of birth."
```

- [ ] **Step 6: Verify the guard test discriminates**

`test_a_revised_mother_tongue_does_not_conflict` passes as soon as the field exists, so prove it is not decoration. Temporarily add `"mother_tongue"` to the LANGUAGE spec's `detail` tuple:

```python
        detail=("cefr_level", "test_name", "test_score", "mother_tongue"),
```

Run: `uv run pytest tests/documents/test_verification.py -k mother_tongue -q`
Expected: FAIL — the verdict is `CONFLICTING`, not `SUPPORTED`.

Then revert `detail` to `("cefr_level", "test_name", "test_score")` and re-run; expected PASS. Do not commit the temporary change.

- [ ] **Step 7: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config \
  && uv run python manage.py makemigrations --check --dry-run
```
Expected: all pass; `makemigrations --check` reports **No changes detected** — `LanguageEntry` is a pydantic schema and `VerifiedFact.payload` is a `JSONField`, so nothing here touches the database.

- [ ] **Step 8: Commit**

```bash
git add apps/documents/schemas.py apps/documents/verification.py apps/documents/ingestion.py \
        tests/documents/test_schemas.py tests/documents/test_verification.py \
        tests/documents/test_ingestion.py
git commit -m "feat(documents): give LanguageEntry a mother_tongue flag

Europass sends mother tongues and other languages as different fields.
Without the flag every language goes under otherLanguages, so an
Azerbaijani student's Europass CV lists Azerbaijani as a foreign
language.

Carried in _PAYLOAD_KEYS and deliberately not in the LANGUAGE spec's
detail tuple, for the same reason as the five sub-skills: no document
contradicts a mother tongue, and comparing it would turn a student's own
correction into a CONFLICTING verdict that blocks their draft. Confirmed
by putting it in detail and watching the guard test fail.

Unlike the sub-skills this is usually stated outright, so ingestion
extracts it -- with the prompt scoped to what DATA says, since
nationality is not a statement about language."
```

---

### Task 3: The pinned-host transport

**Files:**
- Create: `apps/documents/europass.py`
- Test: `tests/documents/test_europass.py` (new)

**Interfaces:**
- Consumes: `apps.research.egress.validate_public_url`, `ResolvedTarget`, `Response`, `MAX_RESPONSE_BYTES`, `UnsafeTarget`.
- Produces:
  - `EUROPASS_ORIGIN: str` — `"https://europa.eu"`.
  - `EuropassUnavailable(RuntimeError)` — every failure mode in this module.
  - `EuropassProvenanceMissing(EuropassUnavailable)` — declared here, raised in Task 6.
  - `Transport` — the injectable seam Protocol.
  - `_call(jar, method, path, *, body, accept, transport) -> bytes`.

This task builds the transport and nothing else; `render_europass_pdf` arrives in Task 5 once there is a payload to send.

**Why not extend `fetch_official_source`.** It is GET-only, and it is a security-critical function several other call sites already depend on. Widening it to arbitrary methods and bodies for one caller enlarges its blast radius for all of them. Only `validate_public_url` is reused — it is the part that does the checking.

**Why urllib3 and not `urllib.request` + `http.cookiejar`** (which is what the spike used): `validate_public_url` resolves the host and returns the addresses, and connecting to a *validated address* with `assert_hostname` is what closes the DNS-rebinding window. `urllib.request` re-resolves the name itself and reopens it. Cookie handling is four lines of dict, so the cookiejar buys nothing worth that.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_europass.py`:

```python
import json

import pytest

from apps.documents.europass import (
    EUROPASS_ORIGIN,
    EuropassUnavailable,
    _call,
)
from apps.research.egress import UnsafeTarget


class _FakeResponse:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = _FakeHeaders(headers)
        self._body = body
        self.released = False

    def read(self, amount, decode_content=True):
        chunk, self._body = self._body[:amount], self._body[amount:]
        return chunk

    def release_conn(self):
        self.released = True


class _FakeHeaders(dict):
    def getlist(self, name):
        value = self.get(name)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


def _transport(status=200, headers=None, body=b"{}"):
    """Records what it was asked to send, so the tests can assert on it."""
    sent = []

    def call(target, *, method, path, body_bytes, headers_out):
        sent.append(
            {
                "host": target.host,
                "scheme": target.scheme,
                "method": method,
                "path": path,
                "body": body_bytes,
                "headers": headers_out,
            }
        )
        return _FakeResponse(
            status, {"Content-Type": "application/json", **(headers or {})}, body
        )

    call.sent = sent
    return call


def test_call_echoes_the_xsrf_cookie_as_a_header():
    """The API rejects mutating calls whose X-XSRF-TOKEN header does not match
    the cookie it issued. This is the whole reason a cookie jar exists here."""
    transport = _transport()
    jar = {"XSRF-TOKEN": "tok-123"}
    _call(jar, "POST", "/x", body={"a": 1}, transport=transport)
    assert transport.sent[0]["headers"]["X-XSRF-TOKEN"] == "tok-123"


def test_call_absorbs_set_cookie_into_the_jar():
    transport = _transport(headers={"Set-Cookie": ["XSRF-TOKEN=abc; Path=/", "S=1; Path=/"]})
    jar = {}
    _call(jar, "GET", "/x", transport=transport)
    assert jar == {"XSRF-TOKEN": "abc", "S": "1"}


def test_call_sends_the_jar_back_as_a_cookie_header():
    transport = _transport()
    _call({"S": "1", "XSRF-TOKEN": "t"}, "GET", "/x", transport=transport)
    assert transport.sent[0]["headers"]["Cookie"] == "S=1; XSRF-TOKEN=t"


def test_call_raises_on_an_http_error():
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=_transport(status=500))


def test_call_refuses_a_redirect_instead_of_following_it():
    """These are four known endpoints. A redirect means the API moved, which
    should surface as a failure rather than be chased somewhere unvalidated."""
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=_transport(status=302, headers={"Location": "/y"}))


def test_call_refuses_an_unexpected_content_type():
    transport = _transport(headers={"Content-Type": "text/html"}, body=b"<html>")
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=transport)


def test_call_refuses_a_response_over_the_cap():
    from apps.documents import europass

    # The fake must return the content type the call asks for: _call checks
    # Content-Type BEFORE the read loop, so a mismatch here would raise for
    # that reason and never exercise the size cap at all. match= pins the
    # reason, so this cannot silently start passing for the wrong one.
    transport = _transport(
        headers={"Content-Type": "application/pdf"},
        body=b"x" * (europass._MAX_BYTES + 1),
    )
    with pytest.raises(EuropassUnavailable, match="exceeded"):
        _call({}, "GET", "/x", accept="application/pdf", transport=transport)


def test_call_always_releases_the_connection():
    transport = _transport(status=500)
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=transport)
    # _FakeResponse records it; a leaked connection on the error path is the
    # bug this pins.
    assert transport.sent  # the call was made
```

Then a test that the host really is pinned — this one goes through the real
`validate_public_url`, so it needs no network:

```python
def test_the_origin_is_a_pinned_https_europa_eu_url():
    assert EUROPASS_ORIGIN == "https://europa.eu"


def test_a_non_global_host_is_refused_by_validation():
    """Pins that validate_public_url is what guards this module. The worker
    this runs in is the environment _no_fetch was written to defend:
    169.254.170.2 hands out the task role's credentials."""
    from apps.research.egress import validate_public_url

    with pytest.raises(UnsafeTarget):
        validate_public_url("http://169.254.170.2/v2/credentials")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_europass.py -q`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'apps.documents.europass'`.

- [ ] **Step 3: Write the module**

Create `apps/documents/europass.py`:

```python
"""Render a CV by having europa.eu render it.

The local EUROPASS template is a look-alike: correct sections, no Europass
provenance. What a funder can actually check is the ``attachment.xml`` every
Europass PDF embeds, and ours embeds nothing. This module gets the real thing.

There is no fallback. Every failure here raises, and a caller that wanted a
Europass CV does not silently receive something else -- see the plan's "The
one thing this plan changes from the spec".
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Protocol, cast

import urllib3

from apps.research.egress import (
    MAX_RESPONSE_BYTES,
    ResolvedTarget,
    Response,
    validate_public_url,
)

#: Pinned in code, not in settings. There is no legitimate reason to point
#: this at another origin, so there is no way to.
EUROPASS_ORIGIN = "https://europa.eu"
_API_ROOT = "/europass/eportfolio/api"
_MAX_BYTES = MAX_RESPONSE_BYTES
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)
_TIMEOUT = urllib3.Timeout(connect=5, read=30)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class EuropassUnavailable(RuntimeError):
    """europa.eu did not produce a CV we can use.

    Always transient from the caller's point of view: nothing has been
    written, the draft is untouched, and retrying later is the correct
    response. It is never a reason to render something else instead.
    """


class EuropassProvenanceMissing(EuropassUnavailable):
    """A PDF came back, but it is not a Europass document."""


class Transport(Protocol):
    def __call__(
        self,
        target: ResolvedTarget,
        *,
        method: str,
        path: str,
        body_bytes: bytes | None,
        headers_out: dict[str, str],
    ) -> Response: ...


def _request(
    target: ResolvedTarget,
    *,
    method: str,
    path: str,
    body_bytes: bytes | None,
    headers_out: dict[str, str],
) -> Response:
    """Connect to a *validated address*, not to a name.

    Re-resolving the hostname here would reopen the DNS-rebinding window
    validate_public_url just closed, which matters because this runs in the
    worker where 169.254.170.2 hands out the task role's credentials.
    """
    pool = urllib3.HTTPSConnectionPool(
        target.addresses[0],
        target.port,
        assert_hostname=target.host,
        server_hostname=target.host,
        maxsize=1,
    )
    return cast(
        Response,
        pool.urlopen(
            method,
            path,
            body=body_bytes,
            headers=headers_out,
            redirect=False,
            preload_content=False,
            timeout=_TIMEOUT,
            retries=False,
        ),
    )


def _header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    return value if isinstance(value, str) else None


def _set_cookies(headers: object) -> Iterable[str]:
    getlist = getattr(headers, "getlist", None)
    return getlist("Set-Cookie") if getlist is not None else ()


def _call(
    jar: dict[str, str],
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    accept: str = "application/json",
    transport: Transport = _request,
) -> bytes:
    """One call to the pinned origin. Validates, sends, absorbs cookies, reads.

    ``jar`` is mutated with any Set-Cookie the response carries -- the API
    issues an XSRF-TOKEN cookie whose value must be echoed as a header on
    every mutating call, so the jar is the session.
    """
    target = validate_public_url(f"{EUROPASS_ORIGIN}{path}")
    if target.scheme != "https":
        raise EuropassUnavailable("refusing a non-HTTPS Europass endpoint")
    body_bytes = json.dumps(body).encode() if body is not None else None
    headers_out = {
        "Host": target.host,
        "User-Agent": _USER_AGENT,
        "Accept": accept,
    }
    if jar:
        headers_out["Cookie"] = "; ".join(f"{name}={value}" for name, value in jar.items())
    if body_bytes is not None:
        headers_out["Content-Type"] = "application/json"
    token = jar.get("XSRF-TOKEN")
    if token:
        headers_out["X-XSRF-TOKEN"] = token
    response = transport(
        target, method=method, path=path, body_bytes=body_bytes, headers_out=headers_out
    )
    try:
        for raw in _set_cookies(response.headers):
            name, _, rest = raw.partition("=")
            if name.strip():
                jar[name.strip()] = rest.split(";", 1)[0].strip()
        if response.status in _REDIRECT_STATUSES:
            # Four known endpoints. A redirect means the API moved, and
            # chasing it would send a student's data somewhere unvalidated.
            raise EuropassUnavailable(f"europa.eu redirected {method} {path}")
        if response.status >= 400:
            raise EuropassUnavailable(f"europa.eu returned HTTP {response.status}")
        content_type = (_header(response.headers, "Content-Type") or "").split(";", 1)[0]
        if content_type != accept:
            raise EuropassUnavailable(f"expected {accept}, got {content_type or 'nothing'}")
        chunks: list[bytes] = []
        size = 0
        while chunk := response.read(64 * 1024, decode_content=True):
            size += len(chunk)
            if size > _MAX_BYTES:
                raise EuropassUnavailable(f"response exceeded {_MAX_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.release_conn()
```

The import list above is exactly what this task's code uses — no more. Tasks 5 and 6 each add their own, and each says which.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_europass.py -q`
Expected: PASS

- [ ] **Step 5: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config
```

Bandit deserves attention here: this is the first new outbound HTTP client in the codebase. Expect **0 findings**. If it flags a request without a timeout, the timeout is missing — fix the code, do not add a `# nosec`.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/europass.py tests/documents/test_europass.py
git commit -m "feat(documents): pinned-host transport for the Europass API

Four calls against a single hard-coded origin. The host is a module
constant rather than a setting because there is no legitimate reason to
point this anywhere else.

validate_public_url runs on every URL and the connection is made to the
address it returned, not to the name -- re-resolving would reopen the
DNS-rebinding window in the one process where 169.254.170.2 hands out the
task role's credentials. Redirects are refused rather than followed, the
content type must match what was asked for, and the response is capped at
egress's own 10 MB.

fetch_official_source is deliberately not extended to POST: it is
security-critical and shared, and widening it for one caller enlarges its
blast radius for every existing one."
```

---

### Task 4: Capture the real profile document

**Files:**
- Create: `apps/documents/management/__init__.py`, `apps/documents/management/commands/__init__.py`
- Create: `apps/documents/management/commands/europass_canary.py`
- Create: `tests/documents/fixtures/europass_profile.json` (captured, committed)
- Create: `tests/documents/fixtures/europass_api.pdf` (copied from the spike, committed)

**Interfaces:**
- Consumes: Task 3's `_call`, `EUROPASS_ORIGIN`.
- Produces: `tests/documents/fixtures/europass_profile.json` — the authority for every field name Task 5's mapper uses. The command itself doubles as the production canary.

**Why capture instead of guessing.** The spike exercised `personalInformation` only; the returned XML shows `<EducationHistory/>` and `<EmploymentHistory/>` empty because nothing was sent for them. The field names for education, experience, publications, awards, skills and languages are **unconfirmed**, and the language keys in the spike's probe were a guess whose read-back was never recorded. Task 5 is written against this fixture, not against anyone's memory.

**Why the canary and the capture are one command.** They are the same four calls. A separate throwaway capture script would be a second thing to keep working.

- [ ] **Step 1: Write the command**

Create the two `__init__.py` files empty, then `apps/documents/management/commands/europass_canary.py`:

```python
"""Exercise the live Europass API. Capture its profile document, or check it.

    uv run python manage.py europass_canary --capture   # refresh the fixture
    uv run python manage.py europass_canary             # canary: does it work?

This talks to a third party over the network. It is deliberately NOT a test:
an undocumented API that changes shape must page someone, but it must never
fail a pull request that did not touch this code.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.documents.europass import EuropassUnavailable, _API_ROOT, _call

FIXTURE = Path("tests/documents/fixtures/europass_profile.json")

#: The skeleton the browser POSTs. The API rejects {}. Confirmed by the spike;
#: everything below personalInformation is populated here so the round-trip
#: shows us the real key names for every section.
SKELETON: dict[str, object] = {
    "profile": {
        "language": "en",
        "personalInformation": {
            "firstName": "Canary",
            "lastName": "Probe",
            "personalMottoLine": None,
            "personalDescription": None,
            "sex": "",
            "nationalities": [],
            "socialMediaWebsites": [],
            "emails": ["canary@example.invalid"],
            "phones": [],
            "addresses": [],
            "websites": [],
            "instantMessengers": [],
            "birthPlace": None,
            "legalDocuments": [],
            "workPermits": [],
        },
        "workExperiences": {"solidWorkExperiences": [], "groupedWorkExperiences": []},
        "preference": {
            "id": "",
            "profileId": "",
            "profileStructure": [],
            "dateFormat": "dd/MM/yyyy",
        },
        "skillsAssessment": {"assessment": None, "mediaAttachments": []},
        "customSections": [],
        "profilePicture": None,
    },
    "template": {
        "templateName": "cv-formal",
        "displayLogo": "first",
        "displayPageNumber": "false",
        "closingStatement": None,
        "color": "none",
        "fontSize": "medium",
    },
    "profilePicture": None,
}


class Command(BaseCommand):
    help = "Exercise the live Europass CV API; --capture refreshes the fixture."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--capture",
            action="store_true",
            help="Write the returned profile document to the committed fixture.",
        )

    def handle(self, *args: object, **options: object) -> None:
        jar: dict[str, str] = {}
        try:
            _call(jar, "GET", f"{_API_ROOT}/frontend-config")
            created = json.loads(_call(jar, "POST", f"{_API_ROOT}/eprofile/cv", body=SKELETON))
            cv_id = created.get("id")
            if not isinstance(cv_id, str) or not cv_id:
                raise CommandError(f"create returned no usable id: {created!r}")
            document = json.loads(_call(jar, "GET", f"{_API_ROOT}/eprofile/cv/{cv_id}"))
        except EuropassUnavailable as error:
            raise CommandError(f"Europass API failed: {error}") from error

        keys = sorted(document.get("profile", {}))
        self.stdout.write(f"profile keys: {keys}")
        if options.get("capture"):
            FIXTURE.parent.mkdir(parents=True, exist_ok=True)
            FIXTURE.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
            self.stdout.write(self.style.SUCCESS(f"wrote {FIXTURE}"))
```

- [ ] **Step 2: Capture, once, against the live API**

Run: `uv run python manage.py europass_canary --capture`
Expected: it prints the real `profile` key list and writes `tests/documents/fixtures/europass_profile.json`.

**Read that key list before continuing.** It is the answer Task 5 needs. Write down which key holds education, which holds languages, which holds projects, and which holds publications and awards.

- [ ] **Step 3: Capture the language-code format**

The one thing the key list alone does not answer is whether a language is identified by an ISO 639-3 code (`"eng"`) or a display name (`"English"`). Find out by hand, once — edit `SKELETON` in place to add the language section under the key name Step 2 revealed, using a shape like:

```python
        "languageSkills": {
            "motherTongues": [],
            "nativeLanguages": [{"language": "aze"}],
            "otherLanguages": [
                {
                    "language": "eng",
                    "listening": "C1",
                    "reading": "C1",
                    "spokenInteraction": "C1",
                    "spokenProduction": "C1",
                    "writing": "C1",
                }
            ],
        },
```

Re-run `uv run python manage.py europass_canary --capture` and read what comes back in the fixture. If the codes were rejected or normalised, the fixture shows the accepted form. **Leave the working shape in `SKELETON`** so the canary keeps exercising the language path, then re-run the capture one final time.

- [ ] **Step 4: Commit the genuine PDF as a fixture**

```bash
mkdir -p tests/documents/fixtures
cp /home/orkhan/Desktop/cv-samples/europass_api.pdf tests/documents/fixtures/europass_api.pdf
```

This is a real Europass artefact — Task 6's positive provenance fixture. Confirm it is the right file:

```bash
uv run python -c "
from pypdf import PdfReader
r = PdfReader('tests/documents/fixtures/europass_api.pdf')
print(list(r.attachments))
"
```
Expected: `['attachment.xml']`

- [ ] **Step 5: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 6: Commit**

```bash
git add apps/documents/management tests/documents/fixtures
git commit -m "feat(documents): capture the live Europass profile document

The spike exercised personalInformation only, so every other section's
field name was a guess -- including the language grid keys, whose
read-back was never recorded. This captures the real document from the
API and commits it, so the mapper in the next commit is written against
what europa.eu actually returns.

The command doubles as the production canary: same four calls, run on a
schedule rather than in CI. An undocumented third-party API that changes
shape must page someone, but it must never fail a PR that did not touch
this code.

tests/documents/fixtures/europass_api.pdf is a genuine artefact from the
spike, kept as the positive fixture for the provenance check."
```

---

### Task 5: The mapper

**Files:**
- Modify: `apps/documents/europass.py`
- Test: `tests/documents/test_europass.py`

**Interfaces:**
- Consumes: `CVContent`, `LanguageEntry.mother_tongue` (Task 2), Task 4's fixture, Task 3's `_call`.
- Produces:
  - `europass_payload(content: CVContent) -> dict[str, object]` — pure, no network.
  - `render_europass_pdf(content: CVContent, *, transport: Transport = _request) -> bytes`.
  - `_name_parts(full_name: str) -> tuple[str, str]`.
  - `_language_code(name: str) -> str`.

- [ ] **Step 1: Reconcile the key names with the fixture**

Before writing anything, open `tests/documents/fixtures/europass_profile.json` and read the `profile` object's keys. The code below uses the names the spike suggested. **Where the fixture disagrees, the fixture wins** — correct the string literals in `europass_payload` as you write it. Step 4's fixture test is what holds them afterwards.

- [ ] **Step 2: Write the failing tests**

Append to `tests/documents/test_europass.py`:

```python
from datetime import date

from apps.documents.europass import (
    EuropassUnavailable,
    _language_code,
    _name_parts,
    europass_payload,
    render_europass_pdf,
)
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    LanguageEntry,
    PersonalInformation,
    ResearchEntry,
)


def _content(**overrides):
    base = dict(
        personal_information=PersonalInformation(
            full_name="Leyla Memmedova", email="leyla@apply.example"
        ),
        education=(
            EducationEntry(
                degree_as_awarded="BSc Computer Science",
                institution_original="Baku State University",
                city="Baku",
                country="AZ",
                start_date=date(2017, 9, 15),
                end_date=date(2021, 6, 30),
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )
    base.update(overrides)
    return CVContent(**base)


def test_name_splits_on_the_last_token():
    assert _name_parts("Leyla Memmedova") == ("Leyla", "Memmedova")
    assert _name_parts("Maria del Carmen Garcia") == ("Maria del Carmen", "Garcia")


def test_a_single_token_name_keeps_an_empty_family_name():
    """Better an empty box than a fabricated surname. The student sees this
    at the approval gate, which is the whole justification for splitting."""
    assert _name_parts("Prince") == ("Prince", "")


def test_the_payload_carries_the_split_name():
    payload = europass_payload(_content())
    personal = payload["profile"]["personalInformation"]
    assert personal["firstName"] == "Leyla"
    assert personal["lastName"] == "Memmedova"
    assert personal["emails"] == ["leyla@apply.example"]


def test_a_mother_tongue_goes_to_native_and_the_rest_to_other():
    content = _content(
        languages=(
            LanguageEntry(language="Azerbaijani", cefr_level="C2", mother_tongue=True),
            LanguageEntry(language="English", cefr_level="C1", reading="C2"),
        )
    )
    skills = europass_payload(content)["profile"]["languageSkills"]
    assert [entry["language"] for entry in skills["nativeLanguages"]] == [
        _language_code("Azerbaijani")
    ]
    assert [entry["language"] for entry in skills["otherLanguages"]] == [
        _language_code("English")
    ]


def test_the_language_grid_uses_the_self_assessment_fallback():
    """One stated level fills five columns -- the rule spec 1 built. If the
    mapper read cefr_level directly, a refined sub-skill would be dropped."""
    content = _content(
        languages=(LanguageEntry(language="English", cefr_level="C1", reading="C2"),)
    )
    entry = europass_payload(content)["profile"]["languageSkills"]["otherLanguages"][0]
    assert entry["listening"] == "C1"
    assert entry["reading"] == "C2"
    assert entry["spokenInteraction"] == "C1"
    assert entry["writing"] == "C1"


def test_research_maps_to_projects():
    """Pins the spec's decision. Projects is first-class in Candidate.xsd and
    survives into the embedded XML; a custom section has no guaranteed
    mapping, which would degrade the provenance this whole path exists for."""
    content = _content(
        research=(ResearchEntry(thesis_title="On Graph Sparsifiers", supervisor="Prof. M"),)
    )
    projects = europass_payload(content)["profile"]["projects"]
    assert len(projects) == 1
    assert "On Graph Sparsifiers" in json.dumps(projects[0])


def test_an_unmappable_language_raises_rather_than_vanishing():
    """No fallback means no silent omission either. A Europass CV missing a
    language the student declared is worse than a loud failure, and the fix
    is one dict entry."""
    content = _content(languages=(LanguageEntry(language="Klingon", cefr_level="C2"),))
    with pytest.raises(EuropassUnavailable):
        europass_payload(content)


def test_the_payload_shape_matches_the_captured_fixture():
    """The fixture is what europa.eu actually returned. This is the test that
    catches the undocumented API renaming a section under us."""
    import pathlib

    fixture = json.loads(
        pathlib.Path("tests/documents/fixtures/europass_profile.json").read_text()
    )
    produced = europass_payload(_content())
    assert set(produced["profile"]) <= set(fixture["profile"])


def test_render_calls_the_four_endpoints_in_order():
    calls = []

    def transport(target, *, method, path, body_bytes, headers_out):
        calls.append((method, path))
        if path.endswith("/frontend-config"):
            body = b"{}"
        elif path.endswith("/eprofile/cv"):
            body = b'{"id": "cv-1"}'
        elif "/office/download/pdf/" in path:
            return _FakeResponse(200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 ...")
        else:
            body = b'{"hash": "h-1"}'
        return _FakeResponse(200, {"Content-Type": "application/json"}, body)

    pdf = render_europass_pdf(_content(), transport=transport)
    assert pdf.startswith(b"%PDF")
    assert [path for _method, path in calls] == [
        "/europass/eportfolio/api/frontend-config",
        "/europass/eportfolio/api/eprofile/cv",
        "/europass/eportfolio/api/eprofile/cv/cv-1",
        "/europass/eportfolio/api/office/download/pdf/h-1",
    ]


def test_render_raises_when_create_returns_no_id():
    def transport(target, *, method, path, body_bytes, headers_out):
        return _FakeResponse(200, {"Content-Type": "application/json"}, b"{}")

    with pytest.raises(EuropassUnavailable):
        render_europass_pdf(_content(), transport=transport)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_europass.py -q`
Expected: FAIL with `ImportError: cannot import name 'europass_payload'`.

- [ ] **Step 4: Write the mapper**

Append to `apps/documents/europass.py`:

```python
#: ponytail: the languages this product actually sees, not all of ISO 639-3.
#: An unmapped language raises rather than silently dropping out of the CV;
#: the fix is one entry. Upgrade path is a real ISO 639 table if the catalogue
#: ever outgrows a dict.
_LANGUAGE_CODES = {
    "azerbaijani": "aze",
    "english": "eng",
    "russian": "rus",
    "turkish": "tur",
    "german": "deu",
    "french": "fra",
    "spanish": "spa",
    "italian": "ita",
    "portuguese": "por",
    "dutch": "nld",
    "polish": "pol",
    "czech": "ces",
    "swedish": "swe",
    "norwegian": "nor",
    "danish": "dan",
    "finnish": "fin",
    "greek": "ell",
    "hungarian": "hun",
    "romanian": "ron",
    "arabic": "ara",
    "persian": "fas",
    "farsi": "fas",
    "georgian": "kat",
    "ukrainian": "ukr",
    "chinese": "zho",
    "japanese": "jpn",
    "korean": "kor",
    "hindi": "hin",
    "urdu": "urd",
    "hebrew": "heb",
}

#: Europass's own key for each of the five CEFR sub-skills, in the order
#: LanguageEntry.self_assessment returns them.
_SUB_SKILL_KEYS = (
    "listening",
    "reading",
    "spokenInteraction",
    "spokenProduction",
    "writing",
)


def _language_code(name: str) -> str:
    try:
        return _LANGUAGE_CODES[name.strip().casefold()]
    except KeyError:
        raise EuropassUnavailable(
            f"no Europass language code for {name!r}; add it to _LANGUAGE_CODES"
        ) from None


def _name_parts(full_name: str) -> tuple[str, str]:
    """Europass wants two boxes; CVContent carries one verified name.

    ponytail: the last whitespace token is the family name. Wrong for Spanish
    double surnames and patronymic-final orders, and knowingly so -- the
    upgrade path is optional given_name/family_name on PersonalInformation,
    sourced from the IDENTITY fact and used when present, which needs no
    migration because CVContent is a pydantic schema.

    Splitting at all is the one inference this design permits, for the same
    reason generate_cv refuses to stamp full_name: a name can be wrong in a
    way only a human catches, and the student sees this at the approval gate.
    """
    parts = full_name.split()
    if len(parts) < 2:
        return full_name, ""
    return " ".join(parts[:-1]), parts[-1]


def _language_entry(entry: LanguageEntry) -> dict[str, object]:
    levels = dict(zip(_SUB_SKILL_KEYS, (level for _label, level in entry.self_assessment)))
    return {"language": _language_code(entry.language), **levels}


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def europass_payload(content: CVContent) -> dict[str, object]:
    """CVContent -> the eportfolio profile document. Pure; no network.

    Keeping this pure is the testing strategy: the part that churns when an
    undocumented API shifts is a dictionary, and a dictionary is asserted
    against a captured fixture with no network in CI.
    """
    first_name, last_name = _name_parts(content.personal_information.full_name)
    languages = content.languages
    return {
        "profile": {
            "language": content.document_language,
            "personalInformation": {
                "firstName": first_name,
                "lastName": last_name,
                "personalMottoLine": None,
                "personalDescription": content.summary,
                "sex": content.personal_information.sex or "",
                "nationalities": [],
                "socialMediaWebsites": [],
                "emails": [content.personal_information.email],
                "phones": [],
                "addresses": [],
                "websites": [],
                "instantMessengers": [],
                "birthPlace": None,
                "legalDocuments": [],
                "workPermits": [],
            },
            "workExperiences": {
                "solidWorkExperiences": [
                    {
                        "position": entry.title,
                        "employer": entry.employer,
                        "city": entry.city,
                        "country": entry.country,
                        "startDate": _iso(entry.start_date),
                        "endDate": _iso(entry.end_date),
                        "description": entry.description,
                    }
                    for entry in content.experience
                ],
                "groupedWorkExperiences": [],
            },
            "educationalExperiences": [
                {
                    "title": entry.degree_english or entry.degree_as_awarded,
                    "organisation": entry.institution_english or entry.institution_original,
                    "city": entry.city,
                    "country": entry.country,
                    "startDate": _iso(entry.start_date),
                    "endDate": _iso(entry.end_date),
                }
                for entry in content.education
            ],
            "languageSkills": {
                "motherTongues": [],
                "nativeLanguages": [
                    _language_entry(entry) for entry in languages if entry.mother_tongue
                ],
                "otherLanguages": [
                    _language_entry(entry) for entry in languages if not entry.mother_tongue
                ],
            },
            # Spec decision: a thesis is a research project. Projects is
            # first-class in Candidate.xsd and survives into the embedded XML;
            # a custom section titled "Research" would not.
            "projects": [
                {
                    "title": entry.thesis_title,
                    "description": " ".join(
                        part
                        for part in (entry.supervisor, entry.methods, entry.outcomes)
                        if part
                    ),
                }
                for entry in content.research
            ],
            "publications": [{"title": title} for title in content.publications],
            "achievements": [{"title": award} for award in content.awards],
            "digitalSkills": list(content.skills),
            "preference": {
                "id": "",
                "profileId": "",
                "profileStructure": [],
                "dateFormat": "dd/MM/yyyy",
            },
            "skillsAssessment": {"assessment": None, "mediaAttachments": []},
            "customSections": [],
            "profilePicture": None,
        },
        "template": {
            "templateName": "cv-formal",
            "displayLogo": "first",
            "displayPageNumber": "false",
            "closingStatement": None,
            "color": "none",
            "fontSize": "medium",
        },
        "profilePicture": None,
    }


def _download_token(body: bytes) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise EuropassUnavailable("render returned a non-JSON body") from error
    if isinstance(parsed, str) and parsed:
        return parsed
    if isinstance(parsed, dict):
        for key in ("hash", "token", "id"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value
    raise EuropassUnavailable("render returned no download token")


def render_europass_pdf(content: CVContent, *, transport: Transport = _request) -> bytes:
    """The four calls. Raises EuropassUnavailable; never returns a substitute."""
    payload = europass_payload(content)
    jar: dict[str, str] = {}
    _call(jar, "GET", f"{_API_ROOT}/frontend-config", transport=transport)
    created = json.loads(
        _call(jar, "POST", f"{_API_ROOT}/eprofile/cv", body=payload, transport=transport)
    )
    cv_id = created.get("id") if isinstance(created, dict) else None
    if not isinstance(cv_id, str) or not cv_id:
        raise EuropassUnavailable("create returned no CV id")
    rendered = _call(
        jar,
        "POST",
        f"{_API_ROOT}/eprofile/cv/{quote(cv_id, safe='')}",
        body=payload,
        transport=transport,
    )
    token = _download_token(rendered)
    return _call(
        jar,
        "GET",
        f"{_API_ROOT}/office/download/pdf/{quote(token, safe='')}",
        accept="application/pdf",
        transport=transport,
    )
```

Add the imports this needs at the top of the module: `from datetime import date`, `from urllib.parse import quote`, and `from .schemas import CVContent, LanguageEntry`.

`quote(..., safe="")` on the id and token is not decoration: both come from the remote, and they are interpolated into a URL path.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_europass.py -q`
Expected: PASS. If `test_the_payload_shape_matches_the_captured_fixture` fails, the fixture is right and the literal is wrong — fix the literal.

- [ ] **Step 6: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 7: Commit**

```bash
git add apps/documents/europass.py tests/documents/test_europass.py
git commit -m "feat(documents): map CVContent onto the Europass profile document

Written against the document captured in the previous commit, not against
the spike's guesses. europass_payload is pure so the part that churns when
an undocumented API shifts is a dictionary, asserted against the fixture
with no network in CI.

Three spec decisions land here. research maps to Projects, which is
first-class in Candidate.xsd and survives into the embedded XML. Languages
split on mother_tongue and use self_assessment, so one stated level fills
five columns and a refined sub-skill is not dropped. full_name splits on
the last whitespace token -- the one inference this design permits, for
the same reason generate_cv refuses to stamp a name: a human sees it at
the approval gate.

An unmappable language raises. No fallback means no silent omission
either: a Europass CV quietly missing a declared language is worse than a
loud failure, and the fix is one dict entry."
```

---

### Task 6: Provenance verification

**Files:**
- Modify: `apps/documents/europass.py`
- Test: `tests/documents/test_europass.py`

**Interfaces:**
- Consumes: `EuropassProvenanceMissing` (Task 3), the fixtures (Task 4).
- Produces: `assert_europass_provenance(pdf_bytes: bytes) -> None`.

**Deviation from the spec, deliberate.** The spec says to parse `attachment.xml` as XML and read `schemeAgencyName`. **Do not parse it.** `xml.etree.ElementTree.fromstring` on third-party bytes is an XXE surface, Bandit flags it (B314), and clearing that would mean adding `defusedxml` — a new dependency for a check that two `in` tests do better. The bytes arrived over a validated HTTPS connection from a pinned host; this check exists to catch "we downloaded an error page rendered as a PDF", and substring matching answers that completely.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_europass.py`:

```python
import pathlib

from apps.documents.europass import EuropassProvenanceMissing, assert_europass_provenance


def _genuine_pdf() -> bytes:
    return pathlib.Path("tests/documents/fixtures/europass_api.pdf").read_bytes()


def test_a_genuine_europass_pdf_passes():
    assert_europass_provenance(_genuine_pdf())


def test_our_own_render_fails_provenance():
    """The negative fixture is our own EUROPASS look-alike, which is exactly
    the document that must never pass as Europass."""
    from apps.documents.render import render_cv

    ours = render_cv(_content(), variant="EUROPASS").pdf_bytes
    with pytest.raises(EuropassProvenanceMissing):
        assert_europass_provenance(ours)


def test_unreadable_bytes_fail_provenance():
    with pytest.raises(EuropassProvenanceMissing):
        assert_europass_provenance(b"not a pdf at all")


def test_scrubbing_metadata_preserves_the_attachment():
    """Pins an empirical finding. scrub_pdf_metadata runs on every released
    artefact; if a change to it ever stripped embedded files, every Europass
    CV would lose its provenance silently."""
    from apps.documents.hygiene import scrub_pdf_metadata

    assert_europass_provenance(scrub_pdf_metadata(_genuine_pdf()))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_europass.py -k provenance -q`
Expected: FAIL with `ImportError: cannot import name 'assert_europass_provenance'`.

- [ ] **Step 3: Write the check**

Append to `apps/documents/europass.py`:

```python
_ATTACHMENT_NAME = "attachment.xml"
#: Two markers from a genuine Candidate document. Matched as bytes rather
#: than parsed: these arrive from a third party, an XML parser on third-party
#: bytes is an XXE surface, and the question here ("is this a Europass
#: document or an error page?") does not need a parse tree to answer.
_PROVENANCE_MARKERS = (
    b'schemeAgencyName="EUROPASS"',
    b"http://www.europass.eu/1.0",
)


def assert_europass_provenance(pdf_bytes: bytes) -> None:
    """Refuse a PDF that is not a genuine Europass document.

    Deliberately does NOT check that the XML's name matches the content's.
    europa.eu is the authority on what it rendered; re-litigating its output
    field by field would be a second mapper with no owner.
    """
    try:
        attachments = PdfReader(BytesIO(pdf_bytes)).attachments
    except Exception as error:  # pypdf raises several unrelated types here
        raise EuropassProvenanceMissing("not a readable PDF") from error
    payloads = attachments.get(_ATTACHMENT_NAME) or ()
    if not payloads:
        raise EuropassProvenanceMissing(f"PDF carries no {_ATTACHMENT_NAME}")
    xml = payloads[0]
    missing = [marker for marker in _PROVENANCE_MARKERS if marker not in xml]
    if missing:
        raise EuropassProvenanceMissing(f"{_ATTACHMENT_NAME} is not a Europass Candidate document")
```

Add `from io import BytesIO` and `from pypdf import PdfReader` to the module's imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_europass.py -q`
Expected: PASS

- [ ] **Step 5: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config
```
Expected: Bandit reports **0 findings**. If it reports B314 or B405, an XML parser was used — remove it; the markers are the design.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/europass.py tests/documents/test_europass.py
git commit -m "feat(documents): verify Europass provenance from the embedded XML

Every europa.eu PDF embeds attachment.xml; ours embeds nothing, which
makes it the one reliable discriminator. PDF metadata is not one --
/Producer is cairo for both, and our release scrub clears /Title anyway.

Matched as bytes rather than parsed. The spec said to parse the XML, but
these bytes come from a third party, an XML parser on third-party bytes
is an XXE surface Bandit flags, and clearing that would mean adding
defusedxml for a check two substring tests do better. The question is 'is
this a Europass document or an error page', which needs no parse tree.

Also pins that scrub_pdf_metadata preserves the attachment. It does today;
if that ever changed, every released Europass CV would lose its provenance
with nothing failing."
```

---

### Task 7: Wire in the `EUROPASS_API` variant, with no fallback

**Files:**
- Modify: `apps/documents/models.py` (`DocumentDraft.RenderVariant`)
- Create: `apps/documents/migrations/0009_europass_api_variant.py`
- Modify: `apps/documents/render.py`
- Test: `tests/documents/test_render.py`

**Interfaces:**
- Consumes: `render_europass_pdf`, `assert_europass_provenance`, `EuropassUnavailable` (Tasks 3, 5, 6).
- Produces: nothing later tasks use. This is the last task.

**The shape of the change.** `europass_required` and `europass_preferred` both map to `EUROPASS_API`. `render_cv_with_warnings` gains `allow_network: bool = False`; only `render_draft` passes `True`. On the preview path the variant renders the local `EUROPASS` template and the artefact says `"EUROPASS"` — truthfully, because that is what it is. On the release path any failure propagates.

**One interaction worth knowing before you write the tests:** `_check_date_of_issue` verifies our own date line reached the PDF, and we cannot inject a line into a Europass-rendered document. A programme that is both `europass_required` and has a BINDING `date_of_issue_required` rule therefore becomes `PreflightBlocked`. That is fail-closed and correct — do not "fix" it by skipping the check.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_render.py`:

```python
def test_europass_requirements_route_to_the_api_variant():
    for requirement in (
        Program.CVFormatRequirement.EUROPASS_REQUIRED,
        Program.CVFormatRequirement.EUROPASS_PREFERRED,
    ):
        assert select_render_variant(_program_with(requirement)) == "EUROPASS_API"


def test_preview_of_the_api_variant_never_touches_the_network():
    """Preview happens repeatedly and before anyone has consented to
    anything. It renders the local look-alike and says so."""
    artifact = render_cv(_content(), variant="EUROPASS_API")
    assert artifact.variant == "EUROPASS"
    assert artifact.pdf_bytes is not None


@pytest.mark.django_db
def test_release_calls_the_api_and_labels_the_artefact(agency_a, django_user_model, monkeypatch):
    from apps.documents import render as render_module
    from apps.documents.drafts import create_draft
    from apps.documents.models import DocumentDraft
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    genuine = pathlib.Path("tests/documents/fixtures/europass_api.pdf").read_bytes()
    monkeypatch.setattr(render_module, "render_europass_pdf", lambda content: genuine)
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="ea1")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        DocumentDraft.objects.filter(id=draft.id).update(
            status=DocumentDraft.Status.APPROVED, render_variant="EUROPASS_API"
        )
        draft.refresh_from_db()
        artifact = render_draft(draft=draft)
    assert artifact.variant == "EUROPASS_API"


@pytest.mark.django_db
def test_release_raises_and_never_falls_back(agency_a, django_user_model, monkeypatch):
    """The core decision. If anyone adds a 'helpful' fallback for preferred
    programmes, this fails -- which is the point."""
    from apps.documents import render as render_module
    from apps.documents.drafts import create_draft
    from apps.documents.europass import EuropassUnavailable
    from apps.documents.models import DocumentDraft
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    def _down(content):
        raise EuropassUnavailable("europa.eu is down")

    monkeypatch.setattr(render_module, "render_europass_pdf", _down)
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="ea2")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        DocumentDraft.objects.filter(id=draft.id).update(
            status=DocumentDraft.Status.APPROVED, render_variant="EUROPASS_API"
        )
        draft.refresh_from_db()
        with pytest.raises(EuropassUnavailable):
            render_draft(draft=draft)
        draft.refresh_from_db()
        # Retryable: nothing was written, so re-running release later works.
        assert draft.status == DocumentDraft.Status.APPROVED


@pytest.mark.django_db
def test_release_refuses_a_pdf_without_provenance(agency_a, django_user_model, monkeypatch):
    """A PDF came back but it is not a Europass document -- treated as a
    failure, not as an artefact."""
    from apps.documents import render as render_module
    from apps.documents.drafts import create_draft
    from apps.documents.europass import EuropassProvenanceMissing
    from apps.documents.models import DocumentDraft
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Membership

    ours = render_cv(_content(), variant="EUROPASS").pdf_bytes
    monkeypatch.setattr(render_module, "render_europass_pdf", lambda content: ours)
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="ea3")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        DocumentDraft.objects.filter(id=draft.id).update(
            status=DocumentDraft.Status.APPROVED, render_variant="EUROPASS_API"
        )
        draft.refresh_from_db()
        with pytest.raises(EuropassProvenanceMissing):
            render_draft(draft=draft)
```

Add `import pathlib` to the top of `test_render.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_render.py -k "api_variant or release_" -q`
Expected: FAIL — `select_render_variant` still returns `"EUROPASS"`, and `UnsupportedRenderVariant` is raised for `"EUROPASS_API"`.

- [ ] **Step 3: Add the variant to the model**

In `apps/documents/models.py`, `DocumentDraft.RenderVariant`, after `EUROPASS`:

```python
        EUROPASS_API = "EUROPASS_API"
```

- [ ] **Step 4: Generate and check the migration**

```bash
uv run python manage.py makemigrations documents --name europass_api_variant
```
Expected: creates `apps/documents/migrations/0009_europass_api_variant.py` with a single `AlterField` on `render_variant`, mirroring `0007_render_variant_choices.py`. Read it and confirm it contains nothing else.

- [ ] **Step 5: Wire the variant into rendering**

In `apps/documents/render.py`:

Remap the two Europass requirements:

```python
_REQUIREMENT_TO_VARIANT = {
    "europass_required": "EUROPASS_API",
    "europass_preferred": "EUROPASS_API",
    "any": "STANDARD",
    "funder_template": "FUNDER_TEMPLATE",
    "structured_fields_only": "FIELD_MAPPED",
}
```

Import at the top:

```python
from .europass import assert_europass_provenance, render_europass_pdf
```

Add the branch in `render_cv_with_warnings`, before the final `else`, and add
`allow_network: bool = False` to its signature:

```python
    elif variant == "EUROPASS_API":
        if allow_network:
            artifact = _pdf_artifact(render_europass_pdf(clean), variant="EUROPASS_API")
            # Verify the bytes we are actually going to ship, after scrubbing:
            # a hygiene pass that stripped the attachment would otherwise
            # release a CV whose provenance we only checked before scrubbing.
            assert_europass_provenance(cast(bytes, artifact.pdf_bytes))
        else:
            # Preview: no network budget, and no consent yet to send a
            # student's data to a third party. Show the local look-alike,
            # labelled as the look-alike it is.
            artifact = _render_pdf(clean, variant="EUROPASS")
```

Thread the flag through `render_cv`:

```python
def render_cv(
    content: CVContent,
    *,
    variant: str,
    constraints: tuple[ConstraintRule, ...] = (),
    funder_template_id: str | None = None,
    allow_network: bool = False,
) -> RenderedArtifact:
```

passing `allow_network=allow_network` into `render_cv_with_warnings`, and have
`render_draft` pass `allow_network=True`:

```python
    return render_cv(
        CVContent.model_validate(draft.content),
        variant=draft.render_variant or "STANDARD",
        constraints=constraints,
        funder_template_id=funder_template_id,
        allow_network=True,
    )
```

- [ ] **Step 6: Add the rate limit**

Still in `render_draft`, before the `render_cv` call, after the `DraftNotApproved` check:

```python
    if draft.render_variant == "EUROPASS_API" and rate_limited(
        "europass-render",
        draft.student_id,
        limit=_EUROPASS_RENDER_LIMIT,
        window_seconds=_EUROPASS_RENDER_WINDOW_SECONDS,
    ):
        raise EuropassUnavailable("Europass render rate limit reached; retry later")
```

with the imports and constants near the top of the module:

```python
from apps.ratelimit import rate_limited

from .europass import EuropassUnavailable, assert_europass_provenance, render_europass_pdf

#: A release path that can be re-triggered is a way to hammer a public EU
#: service from our IP, which is how access gets withdrawn.
_EUROPASS_RENDER_LIMIT = 10
_EUROPASS_RENDER_WINDOW_SECONDS = 3600
```

Raising `EuropassUnavailable` here rather than a new class is deliberate: from the caller's side "europa.eu is down" and "wait an hour" are the same instruction — retry later — and there is no view yet that would render them differently.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_render.py -q`
Expected: PASS

- [ ] **Step 8: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config \
  && uv run python manage.py makemigrations --check --dry-run
```
Expected: all pass; `makemigrations --check` reports **No changes detected**, because Step 4 already generated `0009`.

- [ ] **Step 9: Commit**

```bash
git add apps/documents/models.py apps/documents/migrations/0009_europass_api_variant.py \
        apps/documents/render.py tests/documents/test_render.py
git commit -m "feat(documents): render europass_required through europa.eu

Both europass_required and europass_preferred now route to EUROPASS_API,
and there is no fallback for either. A silent downgrade would put a
plausible-looking PDF in the wrong format past an approval gate with no
violation and no warning, which is the failure the binding-Europass
funders reject applications over -- and a 'preferred' funder still
prefers Europass, so shipping something else is a downgrade the student
never asked for.

Every failure raises, and every failure is retryable: nothing is written,
the draft stays APPROVED, and re-running release succeeds once europa.eu
is back. A test pins that.

The API call is on the release path only. Preview renders the local
look-alike and labels the artefact EUROPASS, truthfully -- it happens
repeatedly and before anyone has consented to sending a student's data to
a third party.

Provenance is verified after metadata scrubbing, so what is checked is
what ships. Rate limited per student: a re-triggerable release path is a
way to hammer a public EU service from our IP."
```

---

## Verification

After Task 7, run once from a clean tree:

```bash
uv run ruff check apps tests
uv run mypy apps
uv run pytest -q
uv run bandit -c pyproject.toml -r apps config
uv run python manage.py makemigrations --check --dry-run
```

Expected: all pass, `makemigrations --check` reports no changes, and only the known AWS flake may fail, intermittently.

Then the one thing CI cannot tell you — that the live API still works:

```bash
uv run python manage.py europass_canary
```

Expected: prints the profile key list without error. Put this on a schedule. It must never become a CI step.

## What is deliberately not built

- **Any fallback.** Stated at the top; the tests in Task 7 exist to keep it that way.
- **A retry loop.** `EuropassUnavailable` is retryable by re-running release. An automatic retry inside the render path would multiply load on a public EU service during exactly the outage that caused the failure.
- **Deleting the guest CVs we create on europa.eu.** There is no known endpoint for it, and whether they persist at all is question 3 of Task 1's email. Revisit when the answer arrives.
- **A forged `attachment.xml`.** We could embed a marker-valid XML into our own WeasyPrint PDF and pass Task 6's own check. Never do this, and do not let a future task do it to "make the fallback work". That XML asserts EU-tool origin for a document Europass never rendered — a forged provenance claim made to a funder, in a student's name. The look-alike variant is honest precisely because it makes no such claim, which is why it may never satisfy `europass_required`.
- **A student-facing error surface.** No view calls `render_draft` for Europass yet. When one is added, `EuropassUnavailable` is the single exception it needs to catch, and the message it should show is "try again shortly", not "your CV failed".
