# Browser Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the JS-only fetch tier into its own ECS task holding no application
credentials, so a renderer escape while retrieving a hostile page reaches neither the
database, nor `DJANGO_SECRET_KEY`, nor `WorkerTaskRole`.

**Architecture:** A `python -m` HTTP server that imports no Django owns `LocalEgressProxy`
and calls `render_with_scrapling`. The research worker POSTs a URL and gets bytes back.
The browser task has no `TaskRoleArn`, no `Secrets`, an empty `Environment`, and its own
security group that is not admitted to the database.

**Tech Stack:** stdlib `http.server`, urllib3 (already a dependency), Scrapling/patchright,
CloudFormation, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-08-26-browser-isolation-design.md`

## Global Constraints

- Branch: `claude/cv-render-fidelity`, worktree `/home/orkhan/Desktop/tehsil_agent/.worktrees/phase2-cv-engine`.
  **Use `git -C <absolute-path>` for every git command** — the shell cwd resets to the main
  repo, and a commit has already landed on the wrong branch once because of it.
- Every command runs through `uv run`. Never invoke `python` or `pytest` bare.
- Gates before any commit: `uv run ruff check apps tests`, `uv run mypy apps`,
  `uv run pytest -q`, `uv run bandit -c pyproject.toml -r apps config`.
- Line length 100, `target-version = "py312"`, ruff lint selects `E,F,I,UP` only.
- **No new dependency.** stdlib and urllib3 cover all of it.
- **No test may hit the network, and none may launch a real browser.** Every test here
  stubs `render_with_scrapling` or serves from a local `http.server`.
- **`apps/research/browser_server.py` must never import Django, directly or transitively.**
  Task 1 adds a test asserting this. If that test fails, the change is wrong even if
  everything else passes — a Django import drags in a settings module that requires
  `DJANGO_SECRET_KEY`, and the entire point of the task separation is lost.
- KNOWN FLAKE, not yours:
  `tests/test_aws_boundary_run_controller.py::test_image_publication_uses_substituted_commands_without_printing_registry`
  fails intermittently (two commands in `scripts/run_aws_boundary_validation.sh:90` append
  to one trace file) and passes on re-run. If it is the ONLY failure, re-run once and proceed.

## One refinement this plan makes to the spec

The spec leaves the failure taxonomy implicit. This plan pins it: the browser service
answers **403** when `validate_public_url` refuses the target, **413** when the body
exceeds `MAX_RESPONSE_BYTES`, and **502** for every render failure. The worker maps all
three to `BrowserRequired`, which is what `retrieve_official_source`'s callers already
expect. Distinguishing them in the *response* costs nothing and makes an operator's
first log line say which of the three happened; collapsing them at the *client* keeps
the caller's error surface exactly as wide as it is today.

---

### Task 1: The browser server

**Files:**
- Create: `apps/research/browser_server.py`
- Create: `tests/research/test_browser_server.py`

**Interfaces:**
- Consumes: `render_with_scrapling`, `LocalEgressProxy`, `validate_public_url`, `canonicalize_url`.
- Produces: `POST /render` on port 8080. Nothing in this repo imports this module except
  its test — it is an entrypoint, not a library.

**Why first:** it is the whole design, it is testable without any infrastructure, and it
is where the no-Django property is established.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_browser_server.py`. Drive the handler through a real
`http.server` on an ephemeral port with `render_with_scrapling` monkeypatched — the
handler's job is HTTP framing and refusal, and stubbing at the render seam keeps the test
network-free and browser-free.

```python
import subprocess
import sys
import threading
from http.server import HTTPServer

import urllib3

from apps.research import browser_server
from apps.research.egress import MAX_RESPONSE_BYTES, FetchResult, UnsafeTarget


def _serve(monkeypatch, render, *, validate=lambda url: None):
    monkeypatch.setattr(browser_server, "render_with_scrapling", render)
    monkeypatch.setattr(browser_server, "validate_public_url", validate)
    browser_server._Handler.proxy = object()  # never used: render is stubbed
    server = HTTPServer(("127.0.0.1", 0), browser_server._Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/render"


def test_render_returns_body_content_type_and_final_url(monkeypatch):
    def render(url, _proxy):
        return FetchResult("https://official.example/final", (), "text/html", b"<html>ok</html>")

    server, endpoint = _serve(monkeypatch, render)
    try:
        response = urllib3.request("POST", endpoint, body=b"https://official.example/start")
    finally:
        server.shutdown()
    assert response.status == 200
    assert response.data == b"<html>ok</html>"
    assert response.headers["Content-Type"] == "text/html"
    assert response.headers["X-Final-Url"] == "https://official.example/final"


def test_refused_target_answers_403_without_rendering(monkeypatch):
    def refuse(_url):
        raise UnsafeTarget("private address")

    def render(_url, _proxy):  # pragma: no cover - must not run
        raise AssertionError("render must not be reached for a refused target")

    server, endpoint = _serve(monkeypatch, render, validate=refuse)
    try:
        response = urllib3.request("POST", endpoint, body=b"http://169.254.170.2/")
    finally:
        server.shutdown()
    assert response.status == 403


def test_oversized_body_answers_413_and_does_not_send_it(monkeypatch):
    def render(_url, _proxy):
        body = b"x" * (MAX_RESPONSE_BYTES + 1)
        return FetchResult("https://official.example/big", (), "text/html", body)

    server, endpoint = _serve(monkeypatch, render)
    try:
        response = urllib3.request("POST", endpoint, body=b"https://official.example/big")
    finally:
        server.shutdown()
    assert response.status == 413
    assert len(response.data) < 1024


def test_render_failure_answers_502_and_the_server_keeps_serving(monkeypatch):
    calls = []

    def render(url, _proxy):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("chromium fell over")
        return FetchResult(url, (), "text/html", b"second")

    server, endpoint = _serve(monkeypatch, render)
    try:
        first = urllib3.request("POST", endpoint, body=b"https://official.example/a")
        second = urllib3.request("POST", endpoint, body=b"https://official.example/b")
    finally:
        server.shutdown()
    assert first.status == 502
    assert second.status == 200 and second.data == b"second"


def test_module_imports_without_django():
    """The load-bearing property, asserted in a fresh interpreter.

    In-process this would pass vacuously -- pytest has already imported Django.
    A subprocess with no DJANGO_SETTINGS_MODULE is the only honest check.
    """
    probe = (
        "import sys; import apps.research.browser_server; "
        "assert 'django' not in sys.modules, sorted(m for m in sys.modules if 'django' in m)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env={"PATH": "/usr/bin"}
    )
    assert result.returncode == 0, result.stderr
```

Note the `env={"PATH": ...}` on the last test: it must run with `DJANGO_SETTINGS_MODULE`
unset, and the Dockerfile `runtime` stage sets it as an `ENV`. If `sys.executable` needs
more of the environment to start under `uv`, pass `PYTHONPATH` explicitly rather than
inheriting `os.environ` — inheriting it is what makes this test lie.

Run: `uv run pytest tests/research/test_browser_server.py -q` — expect collection error
(module does not exist).

- [ ] **Step 2: Write the server**

Create `apps/research/browser_server.py`:

```python
"""The JS-only fetch tier, in a process that holds no application credentials.

Runs as ``python -m apps.research.browser_server`` in its own ECS task
(``BrowserTaskDefinition``). It imports NOTHING from Django, and that is the
design rather than an accident: a management command would require
DJANGO_SECRET_KEY to boot, and this process exists precisely so that a renderer
escape finds no secret in ``/proc/self/environ``. ``tests/research/
test_browser_server.py::test_module_imports_without_django`` enforces it.

The threat model is stated in
``docs/superpowers/specs/2026-08-26-browser-isolation-design.md``. Short version:
Chromium runs with --no-sandbox because Fargate refuses unprivileged user
namespaces (measured), so a renderer compromise is assumed possible and made
cheap instead of prevented.
"""

import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

from .discovery import canonicalize_url, render_with_scrapling
from .egress import MAX_RESPONSE_BYTES, LocalEgressProxy, validate_public_url

PORT = 8080
MAX_URL_BYTES = 4096

logger = logging.getLogger("browser_server")


class _Handler(BaseHTTPRequestHandler):
    #: Set once by serve(). One proxy serves every request; it is a listening
    #: socket plus a thread, not per-request state.
    proxy: LocalEgressProxy

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
        if self.path != "/render":
            self._refuse(404, "no such endpoint")
            return
        url = self._read_url()
        if url is None:
            return
        try:
            validate_public_url(url)
        except Exception:
            # UnsafeTarget, ValueError from urlsplit, socket.gaierror from
            # resolution -- all of them mean "not a target we will visit", and
            # none of them should tell the caller which.
            self._refuse(403, "target refused")
            return
        try:
            result = render_with_scrapling(canonicalize_url(url), self.proxy)
        except Exception as error:
            # Broad on purpose. Scrapling, patchright and Chromium raise from
            # three different exception hierarchies and a page is allowed to be
            # hostile; one bad URL must not end the process.
            logger.warning("render failed for %s: %s", _safe(url), _safe(str(error)))
            self._refuse(502, "render failed")
            return
        if len(result.body) > MAX_RESPONSE_BYTES:
            self._refuse(413, "body too large")
            return
        self.send_response(200)
        self.send_header("Content-Type", result.content_type)
        self.send_header("X-Final-Url", result.final_url)
        self.send_header("Content-Length", str(len(result.body)))
        self.end_headers()
        self.wfile.write(result.body)

    def _read_url(self) -> str | None:
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            self._refuse(400, "bad content-length")
            return None
        if not 0 < length <= MAX_URL_BYTES:
            self._refuse(400, "url missing or too long")
            return None
        return self.rfile.read(length).decode("utf-8", "replace").strip()

    def _refuse(self, status: int, reason: str) -> None:
        body = reason.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        logger.info(fmt, *args)


def _safe(value: str) -> str:
    """Log-inject nothing: this text came off a page we do not control."""
    return value.replace("\r", " ").replace("\n", " ")[:200]


def serve(port: int = PORT) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with LocalEgressProxy() as proxy:
        _Handler.proxy = proxy
        # nosec B104: binding all interfaces is required -- the task's ENI has a
        # VPC-private address assigned at runtime, and loopback would make the
        # service unreachable by design. Reachability is controlled by
        # BrowserSecurityGroup, which admits WorkerSecurityGroup and nothing
        # else (infra/template.yaml). See the design doc's "Authentication
        # between worker and browser".
        server = HTTPServer(("0.0.0.0", port), _Handler)  # nosec B104
        logger.info("browser service listening on %s", port)
        server.serve_forever()


if __name__ == "__main__":
    serve()
```

**Do not make the server threaded.** `HTTPServer` is single-threaded, and that is the
concurrency control: each `render_with_scrapling` launches a Chromium, and two at once in
a 2 GB task is an OOM. Add this comment above `HTTPServer(...)` if it is not obvious to
the next reader:

`# ponytail: single-threaded, one render at a time. If the browser tier ever stops being
the minority path, raise DesiredCount and add an NLB -- not ThreadingHTTPServer.`

- [ ] **Step 3: Verify**

`uv run pytest tests/research/test_browser_server.py -q` — all pass, including the
subprocess Django check. Then the full gate set.

- [ ] **Step 4: Commit** — `feat(research): serve the browser tier from a credential-free process`

---

### Task 2: The worker's side of the call

**Files:**
- Modify: `apps/research/discovery.py`
- Modify: `tests/research/test_discovery.py`

**Interfaces:**
- Consumes: `BROWSER_SERVICE_URL` from the environment (worker-side only).
- Produces: `render_via_browser_service(url) -> FetchResult`; `retrieve_official_source`'s
  `browser_render` seam narrows from `(url, proxy)` to `(url,)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/research/test_discovery.py`. Serve a stub from a local `http.server` rather
than monkeypatching urllib3 — the thing under test is HTTP handling, and a stubbed
transport would test nothing.

Cases, all required:
1. `200` with `X-Final-Url` and `text/html` → `FetchResult` carrying that final URL,
   content type and body, `redirects == ()`.
2. `502` → `BrowserRequired`.
3. `403` → `BrowserRequired`.
4. A body larger than `MAX_RESPONSE_BYTES` → `ResponseTooLarge`, **asserting the client
   stopped reading rather than buffering it all**. This is the point of the test: the
   server also caps, and a cap only the untrusted sender applies is not a cap.
5. A `200` with a content type outside `ALLOWED_CONTENT_TYPES` (e.g. `application/zip`)
   → `SourceBlocked`. The browser path has never enforced the allowlist the plain path
   does; it does now, on the receiving side.
6. Connection refused → `BrowserRequired` (service stopped, `DesiredCount: 0`).
7. `retrieve_official_source` still returns a successful plain fetch untouched, and still
   falls back on `BrowserRequired` — the existing tests, adapted to the narrower seam.

- [ ] **Step 2: Implement**

```python
import os

BROWSER_SERVICE_URL = "http://browser.tehsil.internal:8080/render"


def render_via_browser_service(url: str, *, service_url: str | None = None) -> FetchResult:
    """Ask the browser task to render a JS-only source.

    The browser runs in a task with no role, no secrets and its own security
    group, so everything coming back over this connection is untrusted in
    exactly the way the page it came from was untrusted -- nothing downstream
    may treat it as more trustworthy for having crossed our own network. Hence
    the size and content-type checks here, which duplicate the server's on
    purpose.
    """
    import urllib3

    endpoint = service_url or os.environ.get("BROWSER_SERVICE_URL", BROWSER_SERVICE_URL)
    try:
        response = urllib3.request(
            "POST",
            endpoint,
            body=url.encode(),
            headers={"Content-Type": "text/plain"},
            # A render with network_idle can legitimately take 60-90s: Scrapling's
            # per-operation timeout defaults to 30,000ms and several stack.
            timeout=urllib3.Timeout(connect=5, read=120),
            retries=False,
            preload_content=False,
        )
    except urllib3.exceptions.HTTPError as error:
        raise BrowserRequired(f"browser service unreachable for {url}") from error
    try:
        if response.status != 200:
            raise BrowserRequired(f"browser service answered HTTP {response.status} for {url}")
        content_type = (_header(response.headers, "Content-Type") or "").split(";", 1)[0]
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise SourceBlocked(f"disallowed content type: {content_type or 'missing'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge(url)
    finally:
        response.release_conn()
    final_url = _header(response.headers, "X-Final-Url") or url
    return FetchResult(canonicalize_url(final_url), (), content_type, body)
```

`_header`, `ALLOWED_CONTENT_TYPES`, `ResponseTooLarge` and `SourceBlocked` all come from
`.egress` — extend the existing import line, do not add a second one.

Then narrow `retrieve_official_source`:

```python
def retrieve_official_source(
    url: str,
    *,
    plain_fetch: Callable[..., FetchResult] = fetch_official_source,
    browser_render: Callable[[str], FetchResult] | None = None,
) -> FetchResult:
    canonical_url = canonicalize_url(url)
    try:
        result = plain_fetch(canonical_url, require_https=True)
    except BrowserRequired:
        result = None
    if result is not None and not result.browser_required:
        return result
    render = browser_render or render_via_browser_service
    return render(canonical_url)
```

The `with LocalEgressProxy() as proxy:` block is **deleted here** — it now lives in
`browser_server.serve()`. `render_with_scrapling` and `browser_fetch_options` keep their
signatures and are untouched; they are simply called from the other task.

- [ ] **Step 3: Verify** — full gate set. `uv run mypy apps` will catch any caller still
  passing two arguments to `browser_render`.

- [ ] **Step 4: Commit** — `feat(research): the worker asks the browser task, it does not launch one`

---

### Task 3: Split the image

**Files:**
- Modify: `Dockerfile`

**Why:** the worker stage currently runs `patchright install --with-deps chromium`. Once
the browser has its own task, the task holding the database password should not be able
to launch a browser at all. This is the step that turns "does not" into "cannot".

- [ ] **Step 1: Add a `browser` stage** inheriting `runtime`, moving the entire
  `PLAYWRIGHT_BROWSERS_PATH` / `patchright install --with-deps chromium` / `chmod -R a+rX`
  block into it, dropping to `USER app`, and ending:

```dockerfile
# Django is never imported by this entrypoint (apps/research/browser_server.py),
# so the settings module inherited from `runtime` is not merely unused -- leaving
# it set would let an accidental `import django.conf` succeed into a settings
# module that demands DJANGO_SECRET_KEY, quietly restoring the exposure this
# whole task split removes.
ENV DJANGO_SETTINGS_MODULE=
CMD ["python", "-m", "apps.research.browser_server"]
```

- [ ] **Step 2: Delete the browser install from the `worker` stage**, keeping the CMD.
  Move the long comment explaining patchright-vs-playwright to the `browser` stage, where
  it now belongs, and leave one line at the worker stage saying where the browser went and
  why (a future reader who sees `render_with_scrapling` in `apps/research/` will otherwise
  "fix" the missing browser).

- [ ] **Step 3: Verify** both stages build and the worker no longer has Chromium:

```
docker build --target worker  -t tehsil-worker-check  .
docker build --target browser -t tehsil-browser-check .
docker run --rm tehsil-browser-check python -c "import scrapling; print('browser stage ok')"
docker run --rm --entrypoint sh tehsil-worker-check -c '! ls /ms-playwright 2>/dev/null && echo "worker has no browser"'
```

If Docker is unavailable in the execution environment, say so in the commit message and
leave this step unverified rather than claiming it passed.

- [ ] **Step 4: Commit** — `build: the credential-holding worker no longer ships a browser`

---

### Task 4: Infrastructure

**Files:**
- Modify: `infra/template.yaml`
- Modify: `tests/infra/test_template.py`

- [ ] **Step 1: Write the failing template tests first.** These are the assertions that
  make the design binding rather than advisory, so they exist before the resources do:

```python
def test_browser_task_has_no_role_and_no_secrets(template: Template) -> None:
    task = template.resource("BrowserTaskDefinition")["Properties"]
    assert "TaskRoleArn" not in task
    container = task["ContainerDefinitions"][0]
    assert container.get("Secrets", []) == []
    assert container.get("Environment", []) == []


def test_browser_group_is_not_admitted_to_the_database(template: Template) -> None:
    database = template.resource("DatabaseSecurityGroup")["Properties"]
    sources = [rule.get("SourceSecurityGroupId") for rule in database["SecurityGroupIngress"]]
    assert {"Ref": "BrowserSecurityGroup"} not in sources


def test_only_the_worker_may_reach_the_browser(template: Template) -> None:
    browser = template.resource("BrowserSecurityGroup")["Properties"]
    assert [rule["SourceSecurityGroupId"] for rule in browser["SecurityGroupIngress"]] == [
        {"Ref": "WorkerSecurityGroup"}
    ]


def test_the_browser_service_ships_stopped(template: Template) -> None:
    assert template.parameter("BrowserDesiredCount")["Default"] == 0
```

Use the existing `template` fixture and its `Template` wrapper (`resource()`,
`parameter()`) from `tests/infra/test_template.py` — it already carries a CloudFormation
loader whose `!Ref X` parses to `{"Ref": "X"}`. Do not write a second parser.

- [ ] **Step 2: Add the resources**, per the spec's §"What the browser task holds" and
  §"Network". In order: `BrowserImage` and `BrowserDesiredCount` parameters (following the
  existing `ProbeImage` precedent — do **not** overload `AppImage`), `BrowserSecurityGroup`
  with its warning comment, one `EndpointSecurityGroup` ingress rule from it on 443,
  `BrowserLogGroup`, `BrowserNamespace` + `BrowserDiscoveryService`
  (`AWS::ServiceDiscovery::PrivateDnsNamespace` / `::Service` on `tehsil.internal`),
  `BrowserTaskDefinition`, and `BrowserService` with `ServiceRegistries` and
  `DesiredCount: !Ref BrowserDesiredCount`.

- [ ] **Step 3: Add `BROWSER_SERVICE_URL` to `WorkerTaskDefinition`'s `Environment`**,
  pointing at the Cloud Map name. This is the one place the URL is configured; the browser
  side's port stays a module constant.

- [ ] **Step 4: Verify** — `uv run pytest tests/infra -q`, then
  `aws cloudformation validate-template` if credentials are available. **They are not, and
  must not be improvised: the root credentials shared into an earlier session are to be
  treated as compromised and revoked.** If no scoped IAM user exists, skip the live
  validation and say so.

- [ ] **Step 5: Commit** — `feat(infra): the browser gets its own task, its own group, and no role`

---

## Verification

Run from the worktree, after Task 4:

```
uv run ruff check apps tests
uv run mypy apps
uv run bandit -c pyproject.toml -r apps config
uv run pip-audit --ignore-vuln PYSEC-2026-2034 --ignore-vuln PYSEC-2026-3412
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
```

Expected: 1106+ passing, 2 skipped, no new migrations. The one `# nosec B104` in
`browser_server.py` is the only suppression this plan adds; bandit must otherwise be at
zero findings.

## What this plan does NOT build

- **Any caller.** `retrieve_official_source` still has none, and this plan does not add
  one. `BrowserDesiredCount` stays 0 and the service ships stopped, so the plan adds no
  running cost — the deploy that adds the first caller flips it to 1.
- **`readonlyRootFilesystem` on the browser task.** Worth trying, needs `tmpfs` mounts for
  the Chromium profile, `~/.cache` and `/tmp`, and needs a real fetch to prove it. Do it
  as a follow-up with a canary as the pass criterion, or not at all — it narrows a blast
  radius that no longer contains anything.
- **Authentication between the worker and the browser.** The security group is the
  control, deliberately: a shared secret would mean giving the browser task a secret.

## What was actually verified, and what a deploy still has to prove

Executed 2026-08-26. Everything above ran, including the parts this section originally
expected to be blocked.

- **Docker builds: run.** Both stages build. The worker has no `/ms-playwright`; the browser
  stage imports `browser_server` with `django` absent from `sys.modules`.
- **End-to-end against a running container: run.** `https://example.com/` and
  `https://quotes.toscrape.com/js/` return byte-identical bodies (matching sha256) whether
  fetched in-process by the old path or through the isolated service. `expired.badssl.com`
  and `self-signed.badssl.com` are refused; `169.254.169.254` is refused by the proxy before
  rendering. Scrapling is not degraded by the move.
- **The exposure is measured, both directions.** Reading the *Chromium* process's own
  `/proc/<pid>/environ` mid-render: with secrets in the container environment it holds
  `DJANGO_SECRET_KEY`, `POSTGRES_RUNTIME_PASSWORD` and
  `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`; as `BrowserTaskDefinition` configures it, none.
- **`cfn-lint`: run, zero errors.** Two warnings, both pre-existing and unrelated (RDS engine
  version, the Europass canary's `Fn::Sub`).
- **`aws cloudformation validate-template`: run, passed.** Note the template is 58 KB against
  the API's 51,200-byte `--template-body` limit, so it must be converted to JSON first — the
  `_CfnLoader` in `tests/infra/test_template.py` parses `!Ref` to `{"Ref": ...}`, which is
  already valid JSON CloudFormation. AWS returned `BrowserDesiredCount` with
  `DefaultValue: "0"` and `Capabilities: [CAPABILITY_IAM]` with reason `[AWS::IAM::Role]` —
  unchanged by this work, because the browser task adds no IAM resource at all.

What none of that covers: `validate-template` checks structure, and `cfn-lint` checks property
schemas offline. Neither creates a resource, so **the first real deploy is still the first
time ECS, Cloud Map and the security groups are exercised for real.** In particular the Cloud
Map A record and the worker's `BROWSER_SERVICE_URL` resolving to it are unproven, and
`BrowserDesiredCount` is 0, so nothing runs until the deploy that wires discovery sets it to 1.
