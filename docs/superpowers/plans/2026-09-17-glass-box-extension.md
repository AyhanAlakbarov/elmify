# Glass-box extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the browser extension that fills the portal form in the student's own logged-in tab from a server-minted Fill Packet — verifying every selector against the real page before typing, reading back what it typed, and never clicking Next, Submit or any consent control.

**Architecture:** A Manifest V3 extension in `extension/`, written in TypeScript and bundled by esbuild. A service worker holds the device token and talks to the `/ext/*` API that plan 2 shipped; a content script is injected into the portal tab **on a user gesture only** (no declared content script, no blanket host permission) and owns everything that touches the page: snapshot, selector verification, fill, read-back, page signals. A side panel shows progress and whatever the student must do by hand. The server side is already built — this plan adds exactly one field to one Pydantic model and touches no other Python module.

**Tech Stack:** TypeScript 5 + esbuild (bundle) + `tsc --noEmit` (typecheck), Manifest V3, no UI framework, no JS test runner. Every test in this plan is a pytest test: static checks read the built bundle, end-to-end tests drive Chromium through `patchright` (already installed transitively via `scrapling[fetchers]`).

**Spec:** `docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`. Read, at minimum: "Decisions", "Decisions taken with the owner, 2026-09-15 (evening)", "Architecture", "The Fill Packet", "Extension API", "**What plan 3 must not drop: the extension verifies the map against the page**", "Security model", "Testing", "Risks and ceilings". Requirements context: `phased requirements.md` §5.2 and §5.5.

## Where this plan sits

Plan 3 of 5. Plans 1 and 2 are on `master` at `47a5e22`:

1. ✅ The kit and the packet (`apps/portals/packets.py`).
2. ✅ Pairing and the extension HTTP API (`apps/portals/pairing.py`, `ext_api.py`, `actions.py`).
3. **This plan — the extension itself.**
4. Mailbox OAuth (plan 4) — produces the `DeviceAction` rows this plan's poller consumes. An empty queue is the contract until then.
5. The reminder ladder and counselor mode (plan 5).

**Tasks 1–8 are the shippable core:** after task 8 the extension pairs, fetches a packet, learns a form, verifies every selector, fills, and reads back. Tasks 9–13 add documents, page signals, the action poller, the dock and the end-to-end harness. If work has to stop, stop after task 8 — not mid-way through it.

## Global Constraints

- Python is 3.14 in five places (`requires-python`, ruff `target-version`, mypy `python_version`, `ci.yml`, `Dockerfile`). **This plan changes none of them** and adds no Python dependency.
- Every Python command runs through `uv run`. Never invoke `pytest`, `python`, `ruff` or `mypy` directly.
- **Never run `uv run ruff format` in this repository.** Ruff 0.16.6 rewrites this repo's except-tuples into invalid Python. Run `uv run ruff check` only.
- Before each commit: `uv run ruff check`, `uv run mypy apps config`, `uv run bandit -c pyproject.toml -r apps config`, and the tests named in the task.
- Node commands run from `extension/`. Before each commit that touches `extension/src`: `npm run typecheck` and `npm run build`.
- **`apps/portals/session.py::FILL_METHODS` is not widened.** It stays `{"fill", "type", "selectOption", "selectOptionFromDropdown"}` and `is_fillable` still requires `arguments[:1] == ["%value%"]`. `setFiles` is the content script's own vocabulary for file inputs it finds itself; it is never a stored `FieldMap` method and never passes through `is_fillable`. (Task 9 explains why this resolves the spec's "add `setFiles`" line without touching the stored allowlist.)
- **Nothing in this extension dispatches a click, a `MouseEvent`, a `KeyboardEvent` on Enter, `form.submit()`, `form.requestSubmit()`, or sets `location`.** The student presses every button. Task 1 adds the static scan that enforces this and every later task must keep it passing.
- `ext_api.py` must never read `request.user`. Every route there is `@csrf_exempt` and that is only safe while the device token is the sole authenticator.
- A packet lives in `chrome.storage.session` (cleared when the browser closes). The device token lives in `chrome.storage.local` (pairing survives a restart). Neither ever reaches a portal page's storage, a `window` property, or a log.
- Never log a student value, a packet, a device token, or a portal URL carrying a token.
- Tenant-scoped Python reads happen inside `tenant_transaction(tenant_id)`.
- `extension/dist/` and `extension/node_modules/` are gitignored. The built bundle is never committed.

---

## File Structure

| File | Responsibility |
|---|---|
| `extension/package.json` (create) | three dev dependencies, four scripts |
| `extension/package-lock.json` (create, generated) | the pinned tree `npm ci` installs |
| `extension/tsconfig.json` (create) | strict TypeScript, no emit (esbuild emits) |
| `extension/build.mjs` (create) | the esbuild invocation; copies `manifest.json`, `panel.html`, icons into `dist/` |
| `extension/manifest.json` (create) | MV3: no declared content script, optional host permissions only |
| `extension/src/api.ts` (create) | device token storage, packet storage, every `/ext/*` call |
| `extension/src/service_worker.ts` (create) | pairing, packet fetch, document fetch, message router, action poll |
| `extension/src/content/index.ts` (create) | the fill run's order of operations; the only file that talks to the worker |
| `extension/src/content/snapshot.ts` (create) | build a value-free `FormSnapshot` from the live DOM |
| `extension/src/content/verify.ts` (create) | **the selector-verification check** |
| `extension/src/content/vocabulary.ts` (create) | profile field → accepted name tokens (data, not logic) |
| `extension/src/content/fill.ts` (create) | the action allowlist, native value setter, `alreadyCorrect`, `readBack` |
| `extension/src/content/page_signals.ts` (create) | challenge markers, confirmation markers, portal status read |
| `extension/src/panel/panel.html` (create) | the dock's markup — **Aykhan's** |
| `extension/src/panel/panel.ts` (create) | the dock's only DOM owner — **Aykhan's** |
| `extension/src/types.ts` (create) | `FillPacket`, `PacketField`, dock state, worker messages |
| `apps/portals/packets.py` (modify) | one field on `PacketField`; one line in `mint_packet` |
| `tests/portals/test_extension_bundle.py` (create) | bundle exists, allowlist parity, no-click scan, version agreement |
| `tests/portals/test_extension_e2e.py` (create) | the Chromium end-to-end run |
| `tests/portals/fixtures/*.html` (create) | the portal pages the e2e run drives |
| `.github/workflows/ci.yml` (modify) | one `extension` job |
| `.gitignore` (modify) | `extension/dist/` |
| `pyproject.toml` (modify) | one pytest marker |

---

### Task 1: The extension builds, and CI proves it

**Files:**
- Create: `extension/package.json`, `extension/tsconfig.json`, `extension/build.mjs`, `extension/manifest.json`, `extension/src/types.ts`, `extension/src/service_worker.ts`
- Modify: `.gitignore`, `pyproject.toml`, `.github/workflows/ci.yml`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `extension/dist/service_worker.js`, `extension/dist/content.js`, `extension/dist/panel.js`, `extension/dist/manifest.json`; the pytest marker `extension`; the helper `tests/portals/test_extension_bundle.py::bundle_text(name: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/portals/test_extension_bundle.py`:

```python
"""Static checks on the built extension.

These read the BUILT bundle, not the sources: what ships is what Chrome runs,
and a rule enforced only in TypeScript is a rule a later build step can drop.

Locally the bundle may be absent -- `npm --prefix extension ci && npm --prefix
extension run build` builds it. Under CI a missing bundle is a FAILURE and
never a skip: this repository has already shipped one job that went green
having measured nothing (see .github/workflows/ci.yml's portal-sandbox
comments), and a skipping security check is that failure again.
"""

import json
import os
import pathlib

import pytest

DIST = pathlib.Path(__file__).resolve().parents[2] / "extension" / "dist"


def bundle_text(name: str) -> str:
    """The built bundle's source, or a skip/failure per the rule above."""
    path = DIST / name
    if not path.exists():
        message = f"{path} is missing -- run: npm --prefix extension ci && npm --prefix extension run build"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    return path.read_text(encoding="utf-8")


def test_the_three_bundles_are_built() -> None:
    for name in ("service_worker.js", "content.js", "panel.js"):
        assert bundle_text(name).strip(), f"{name} is empty"


def test_the_manifest_is_v3_and_declares_no_content_script() -> None:
    """A declared content script runs on every matching page forever.

    This extension injects into the portal tab on a user gesture instead, so
    the manifest must carry no `content_scripts` key at all and no non-optional
    host permission.
    """
    manifest = json.loads(bundle_text("manifest.json"))
    assert manifest["manifest_version"] == 3
    assert "content_scripts" not in manifest
    assert manifest.get("host_permissions", []) == []
    assert manifest["optional_host_permissions"] == ["https://*/*"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -v`
Expected: FAIL — `extension/dist/manifest.json is missing` (the `CI` guard is not set locally, so the first failure is the missing marker in `pyproject.toml` if you ran it before step 4; otherwise the tests SKIP. A skip here is not a pass — continue.)

- [ ] **Step 3: Create the package**

`extension/package.json`:

```json
{
  "name": "tehsil-copilot",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "node build.mjs",
    "typecheck": "tsc --noEmit",
    "package": "node build.mjs && cd dist && zip -r ../tehsil-copilot.zip .",
    "check": "npm run typecheck && npm run build"
  },
  "devDependencies": {
    "@types/chrome": "^0.0.287",
    "esbuild": "^0.25.0",
    "typescript": "^5.7.0"
  }
}
```

`extension/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": ["chrome"],
    "lib": ["ES2022", "DOM"]
  },
  "include": ["src/**/*.ts", "build.mjs"]
}
```

`extension/build.mjs`:

```js
// The whole build. Three entry points, no config file, no plugin.
//
// bundle: true and format "iife" for the content script -- Chrome will not
// load an ES module as an injected script, and an unbundled import would
// resolve against the PORTAL's origin, not ours.
import { build } from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";

await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });

await build({
  entryPoints: {
    service_worker: "src/service_worker.ts",
    content: "src/content/index.ts",
    panel: "src/panel/panel.ts",
  },
  outdir: "dist",
  bundle: true,
  format: "iife",
  target: "chrome120",
  sourcemap: false,
  legalComments: "none",
});

await cp("manifest.json", "dist/manifest.json");
await cp("src/panel/panel.html", "dist/panel.html");
await cp("icons", "dist/icons", { recursive: true });
```

`extension/manifest.json`:

```json
{
  "manifest_version": 3,
  "name": "Tehsil Application Co-pilot",
  "version": "0.1.0",
  "description": "Fills your application form in your own browser. You press Submit.",
  "background": { "service_worker": "service_worker.js" },
  "action": { "default_title": "Tehsil co-pilot" },
  "side_panel": { "default_path": "panel.html" },
  "permissions": ["storage", "scripting", "activeTab", "sidePanel"],
  "host_permissions": [],
  "optional_host_permissions": ["https://*/*"],
  "icons": { "128": "icons/icon128.png" }
}
```

Create `extension/icons/icon128.png` as any 128×128 PNG placeholder (the visual identity is Aykhan's — see task 12).

- [ ] **Step 4: Create the type surface and a minimal worker**

`extension/src/types.ts`:

```ts
/** The server's FillPacket, as JSON. Mirrors apps/portals/packets.py. */
export interface PacketField {
  /** Where to type. Verified against the live page before use -- see verify.ts. */
  selector: string;
  /** One of FILL_METHODS. Never setFiles: documents are not field-map entries. */
  method: string;
  value: string;
  /** "category.key", e.g. "personal.given_name". Added by task 2; the
   *  verification check cannot judge a control without knowing what it is for. */
  profile_field: string;
}

export interface PacketDocument {
  filename: string;
  download_path: string;
  draft_id: string;
}

export interface FillPacket {
  application_id: string;
  portal_form_id: string;
  field_map_version: number;
  form_url: string;
  entries: PacketField[];
  documents: PacketDocument[];
  issued_at: string;
  expires_at: string;
  min_extension_version: string;
}

/** What the dock renders. The panel owns the DOM; this is all it is given. */
export interface DockState {
  applicationId: string | null;
  status: "idle" | "pairing" | "ready" | "filling" | "blocked" | "done";
  filled: string[];
  /** Fields the extension refused to type, and why. The student does these. */
  yourTurn: { label: string; reason: string }[];
  mismatches: { label: string; expected: string; actual: string }[];
  message: string;
}
```

`extension/src/service_worker.ts` (task 1 version — grown in tasks 3, 4, 8, 9, 10, 11, 12):

```ts
// The extension's only long-lived context. It holds the device token and is
// the only place that speaks to the tenant host; the content script never
// holds a credential and never makes a cross-origin request.
//
// Deliberately NOT setPanelBehavior({openPanelOnActionClick: true}): that
// makes Chrome open the panel itself and chrome.action.onClicked then never
// fires, which would silently kill the pairing gesture task 3 hangs off it.
// The panel is opened from the click handler instead, where the gesture that
// sidePanel.open() requires is still in hand.
export {};
```

**One message listener, for the whole extension.** Tasks 4, 8, 9, 10, 11 and 12 each add a
case to it. Add cases to the single `chrome.runtime.onMessage.addListener` introduced in
task 4 — never a second `addListener`, because two listeners both returning `true` for the
same message is a race over one `sendResponse`, and whichever loses throws into the void.

- [ ] **Step 5: Register the marker and ignore the build output**

Append to `pyproject.toml`'s `[tool.pytest.ini_options]` `markers` list, after the `frontend` entry:

```toml
  "extension: drives Chromium with the built extension; run with -m extension",
```

and change `addopts` in the same block:

```toml
addopts = "-m 'not live and not extension'"
```

**Excluded from the default run rather than self-skipping.** These tests launch a real
browser; a developer who happens to have built the bundle should not get a Chromium window
from `uv run pytest`. Exclusion is explicit and visible in one line — a self-skip is the
thing that makes a suite look green while measuring nothing. The *static* checks in
`test_extension_bundle.py` carry no marker and run every time.

Append to `.gitignore`:

```
extension/dist/
extension/tehsil-copilot.zip
```

(`node_modules/` is already ignored at the repository root.)

- [ ] **Step 6: Build and run the test**

Run:
```bash
cd extension && npm install && npm run check && cd ..
uv run pytest tests/portals/test_extension_bundle.py -v
```
Expected: PASS, three tests.

- [ ] **Step 7: Add the CI job**

Add to `.github/workflows/ci.yml`, as a sibling of `test:`:

```yaml
  extension:
    runs-on: ubuntu-latest
    # The static checks import apps.portals to compare against FILL_METHODS,
    # _EVENT_KINDS and MIN_EXTENSION_VERSION, so this job needs the same
    # settings module -- and therefore the same database -- the test job has.
    # Comparing the bundle against a hand-copied constant instead would be the
    # drift this whole file of tests exists to catch.
    services:
      postgres:
        image: postgres:17-alpine
        env:
          POSTGRES_DB: tehsil
          POSTGRES_USER: tehsil
          POSTGRES_PASSWORD: tehsil
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U tehsil"
          --health-interval 2s
          --health-timeout 2s
          --health-retries 15
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-node@2028fbc5c25fe9cf00d9f06a71cc4710d4507903 # v6.0.0
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: extension/package-lock.json
      - run: npm --prefix extension ci
      - run: npm --prefix extension run typecheck
      - run: npm --prefix extension run build
      - uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1
        with:
          python-version: "3.14"
      - run: uv sync --locked --group dev
      # The static checks. CI=true is set by the runner, so a missing bundle
      # fails here rather than skipping -- which is the whole point of the
      # guard in bundle_text.
      - run: uv run pytest tests/portals/test_extension_bundle.py -q
```

Verify the `setup-node` SHA against the tag before committing: `gh api repos/actions/setup-node/git/ref/tags/v6.0.0 --jq .object.sha`. Every `uses:` in this file is SHA-pinned; an unpinned one will not pass review.

- [ ] **Step 8: Commit**

```bash
git add extension/package.json extension/package-lock.json extension/tsconfig.json \
        extension/build.mjs extension/manifest.json extension/src extension/icons \
        tests/portals/test_extension_bundle.py pyproject.toml .gitignore .github/workflows/ci.yml
git commit -m "feat(extension): a TypeScript build the CI cannot silently skip"
```

---

### Task 2: The packet says which field each selector is for

**Files:**
- Modify: `apps/portals/packets.py` (`PacketField`, `mint_packet`)
- Test: `tests/portals/test_packet.py`

**Interfaces:**
- Consumes: `FillPacket` from plan 1.
- Produces: `PacketField.profile_field: str` on every entry of every minted packet.

**Why:** the selector-verification check asks "does this control plausibly ask for *this* fact?". Without the field's name the extension can only check that a control exists, which is the weak half. `profile_field` is vocabulary (`"personal.given_name"`), never a student value, so it adds nothing to what the packet already carries.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_packet.py`:

```python
def test_every_packet_entry_names_the_field_it_fills(
    agency_a, membership_a, monkeypatch
) -> None:
    """The extension cannot verify a selector it cannot name.

    A control's accessible name is judged against the FIELD, so an entry
    without one degrades the check to "something exists here", which is what
    the spec's plan-3 section rules out.
    """
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        packet = packets.mint_packet(application)

    assert [entry.profile_field for entry in packet.entries] == [
        "identity.full_name",
        "personal.city",
    ]
```

The module already imports `tenant_scope` and `_application` — follow the shape of
`test_the_packet_carries_one_entry_per_mapped_field` directly above it.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_packet.py -k profile_field -v`
Expected: FAIL — `AttributeError: 'PacketField' object has no attribute 'profile_field'`

- [ ] **Step 3: Add the field**

In `apps/portals/packets.py`, in `PacketField`:

```python
class PacketField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: str
    method: str
    value: str
    #: The fact this selector is supposed to ask for, in profile.py vocabulary.
    #: Carried so the extension can check the control's own accessible name
    #: against it before typing -- the server has no page to check against, and
    #: read-back cannot catch a wrong-but-consistent map. Vocabulary only: it
    #: names a category and a key, never a student value.
    profile_field: str
```

In `mint_packet`, in the loop that builds `entries`:

```python
        entries.append(
            PacketField(
                selector=action.selector,
                method=(action.method or "").strip(),
                value=values[field],
                profile_field=field,
            )
        )
```

- [ ] **Step 4: Run the whole packet suite**

Run: `uv run pytest tests/portals/test_packet.py tests/portals/test_ext_api.py -q`
Expected: PASS. `_record_packet` writes `selector` and `value` only, so the audit row is unchanged — confirm no test asserting that row's shape broke.

- [ ] **Step 5: Commit**

```bash
uv run ruff check && uv run mypy apps config
git add apps/portals/packets.py tests/portals/test_packet.py
git commit -m "feat(portals): a packet entry names the fact it is meant to fill"
```

---

### Task 3: Pairing, on the student's own dashboard tab

**Files:**
- Create: `extension/src/api.ts`
- Modify: `extension/src/service_worker.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: `POST /api/extension/pairing-code` (session-authenticated, CSRF-protected), `POST /ext/pair`, `DELETE /ext/pair`.
- Produces: `api.ts`'s `pairFromTab(tabId, origin)`, `deviceToken()`, `callExt(origin, path, init)`, `revoke(origin)`.

**How pairing works, and why this way:** `pairing_code` is an ordinary session view — it is *not* `@csrf_exempt`, so a bare `fetch` from the service worker would be rejected. A content script injected into the dashboard tab shares that tab's cookies and can read `document.cookie`, so it reads `csrftoken`, POSTs same-origin for a one-time code, and hands only the code back to the worker. The worker redeems it at `/ext/pair` and stores the token. No `cookies` permission, no `externally_connectable` (which cannot express a wildcard tenant host anyway), and the page never sees the device token.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_extension_bundle.py`:

```python
def test_the_device_token_never_reaches_a_portal_page() -> None:
    """The token lives in the worker's storage and in its Authorization header.

    The content bundle is what runs inside a portal page's tab. If the string
    that reads the token appears there at all, the token is one message reply
    away from a page that can log it.
    """
    content = bundle_text("content.js")
    assert "device_token" not in content
    assert "Authorization" not in content


def test_the_token_is_stored_outside_session_storage() -> None:
    """Pairing survives a browser restart; a packet does not.

    storage.local for the token, storage.session for the packet. Getting these
    the wrong way round either re-pairs the student every morning or leaves
    verified facts on disk.
    """
    worker = bundle_text("service_worker.js")
    assert "storage.local" in worker
    assert "storage.session" in worker
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k token -v`
Expected: FAIL — `assert 'storage.local' in worker`

- [ ] **Step 3: Write `extension/src/api.ts`**

```ts
// Everything that speaks to the tenant host. Only the service worker imports
// this; the content script has no credential and makes no cross-origin call.
import type { FillPacket } from "./types.js";

const TOKEN_KEY = "device_token";
const PACKET_PREFIX = "packet:";

export async function deviceToken(): Promise<string | null> {
  const stored = await chrome.storage.local.get(TOKEN_KEY);
  const token = stored[TOKEN_KEY];
  return typeof token === "string" && token ? token : null;
}

export async function dashboardOrigin(): Promise<string | null> {
  const stored = await chrome.storage.local.get("origin");
  const origin = stored["origin"];
  return typeof origin === "string" && origin ? origin : null;
}

export class ExtError extends Error {
  constructor(readonly status: number, readonly code: string) {
    // The server's error codes are a contract (ext_api.py::_ApiError) -- they
    // are matched on here, so they are carried, never reworded.
    super(code);
  }
}

async function call(
  origin: string,
  path: string,
  init: RequestInit = {},
): Promise<unknown> {
  const token = await deviceToken();
  if (!token) throw new ExtError(401, "pairing_required");
  const response = await fetch(`${origin}${path}`, {
    ...init,
    // No cookies. The device token is the only authenticator, which is the
    // premise that makes every /ext/ route safe to expose csrf_exempt.
    credentials: "omit",
    headers: {
      ...(init.headers ?? {}),
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });
  const body = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = typeof (body as { error?: unknown }).error === "string"
      ? (body as { error: string }).error
      : "request_failed";
    throw new ExtError(response.status, code);
  }
  return body;
}

/**
 * Redeem a one-time code minted by the dashboard's own session.
 *
 * The code is fetched by a script injected into the dashboard TAB, because
 * /api/extension/pairing-code is CSRF-protected and needs that tab's cookie
 * and csrftoken. Only the code crosses back; the token is minted here and
 * never enters a page.
 */
export async function pairFromTab(tabId: number, origin: string): Promise<void> {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: async () => {
      const csrf = document.cookie
        .split("; ")
        .find((part) => part.startsWith("csrftoken="))
        ?.slice("csrftoken=".length);
      const response = await fetch("/api/extension/pairing-code", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf ?? "", "Content-Type": "application/json" },
      });
      if (!response.ok) return { error: String(response.status) };
      return (await response.json()) as { code?: string };
    },
  });
  const code = (result?.result as { code?: string } | undefined)?.code;
  if (!code) throw new ExtError(401, "pairing_code_unavailable");

  const installation = await installationId();
  const response = await fetch(`${origin}/ext/pair`, {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, installation_id: installation }),
  });
  const body = (await response.json().catch(() => ({}))) as {
    token?: string;
    error?: string;
  };
  if (!response.ok || !body.token) {
    throw new ExtError(response.status, body.error ?? "pair_failed");
  }
  await chrome.storage.local.set({ [TOKEN_KEY]: body.token, origin });
}

async function installationId(): Promise<string> {
  const stored = await chrome.storage.local.get("installation_id");
  const existing = stored["installation_id"];
  if (typeof existing === "string" && existing) return existing;
  const fresh = crypto.randomUUID();
  await chrome.storage.local.set({ installation_id: fresh });
  return fresh;
}

export async function revoke(origin: string): Promise<void> {
  try {
    await call(origin, "/ext/pair", { method: "DELETE" });
  } finally {
    // Local state goes whether or not the server answered: a token we keep
    // after the student asked us to forget it is the worst of both.
    await chrome.storage.local.remove([TOKEN_KEY]);
  }
}

export async function fetchPacket(origin: string, applicationId: string): Promise<FillPacket> {
  return (await call(origin, `/ext/applications/${applicationId}/packet`)) as FillPacket;
}

export async function postEvent(
  origin: string,
  applicationId: string,
  kind: string,
  detail: Record<string, unknown>,
): Promise<void> {
  await call(origin, `/ext/applications/${applicationId}/events`, {
    method: "POST",
    body: JSON.stringify({ kind, detail }),
  });
}

export async function postSnapshot(
  origin: string,
  portalFormId: string,
  snapshot: unknown,
): Promise<{ field_map_version: number }> {
  return (await call(origin, `/ext/portal-forms/${portalFormId}/snapshot`, {
    method: "POST",
    body: JSON.stringify(snapshot),
  })) as { field_map_version: number };
}

export async function storePacket(applicationId: string, packet: FillPacket): Promise<void> {
  // Session storage: cleared when the browser closes, so verified facts never
  // sit on disk. The server's own 2-hour expiry is the other half.
  await chrome.storage.session.set({ [`${PACKET_PREFIX}${applicationId}`]: packet });
}

export async function loadPacket(applicationId: string): Promise<FillPacket | null> {
  const stored = await chrome.storage.session.get(`${PACKET_PREFIX}${applicationId}`);
  const packet = stored[`${PACKET_PREFIX}${applicationId}`] as FillPacket | undefined;
  if (!packet) return null;
  if (Date.parse(packet.expires_at) <= Date.now()) return null;
  return packet;
}
```

- [ ] **Step 4: Wire the toolbar click**

Replace `extension/src/service_worker.ts` with:

```ts
import { dashboardOrigin, deviceToken, pairFromTab } from "./api.js";

/**
 * The student clicks the toolbar button on their dashboard. That gesture is
 * what lets us ask for the host permission, what opens the panel, and what
 * makes pairing an act rather than something that happened to them.
 *
 * Order matters: sidePanel.open() spends the user gesture, so it goes after
 * permissions.request(), which needs one too.
 */
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id || !tab.url) return;
  const origin = new URL(tab.url).origin;
  // https only. The optional host permission is https://*/*, so asking for
  // anything else is a prompt Chrome will refuse anyway.
  if (!origin.startsWith("https://")) return;
  const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
  if (!granted) return;
  await chrome.sidePanel.open({ tabId: tab.id });
  if (await deviceToken()) return;
  await pairFromTab(tab.id, origin);
});
```

- [ ] **Step 5: Build and run the tests**

Run:
```bash
npm --prefix extension run check
uv run pytest tests/portals/test_extension_bundle.py -q
```
Expected: PASS. If `test_the_device_token_never_reaches_a_portal_page` fails, `api.ts` has been imported from `content/index.ts` — it must not be.

- [ ] **Step 6: Commit**

```bash
git add extension/src tests/portals/test_extension_bundle.py
git commit -m "feat(extension): pair from the dashboard's own tab, keep the token out of every page"
```

---

### Task 4: Fetch the packet, and refuse one this build is too old to honour

**Files:**
- Modify: `extension/src/service_worker.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: `api.ts::fetchPacket`, `storePacket`, `loadPacket`.
- Produces: the worker message `{ type: "packet", applicationId }` → `{ ok: true, packet } | { ok: false, code }`; the exported helper `isVersionSupported(min: string, current: string): boolean`.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_extension_bundle.py`:

```python
def test_the_manifest_version_is_at_least_the_packet_floor() -> None:
    """A shipped build older than MIN_EXTENSION_VERSION refuses every packet.

    Both numbers are edited by hand in two files. Pinning them together is the
    only thing that stops a release that cannot fill anything.
    """
    from apps.portals.packets import MIN_EXTENSION_VERSION

    manifest = json.loads(bundle_text("manifest.json"))
    built = tuple(int(part) for part in manifest["version"].split("."))
    floor = tuple(int(part) for part in MIN_EXTENSION_VERSION.split("."))
    assert built >= floor, f"manifest {manifest['version']} < packet floor {MIN_EXTENSION_VERSION}"
```

- [ ] **Step 2: Run it to verify it fails, or passes for the right reason**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k version -v`
Expected: PASS at `0.1.0 >= 0.1.0`. Temporarily set the manifest version to `0.0.9`, re-run, see it FAIL, then set it back. A test that has never been seen to fail is not yet a test.

- [ ] **Step 3: Add the packet route to the worker**

Extend the import at the top of `extension/src/service_worker.ts` — one import
declaration for the whole file, not a second one lower down:

```ts
import {
  ExtError,
  dashboardOrigin,
  deviceToken,
  fetchPacket,
  loadPacket,
  pairFromTab,
  storePacket,
} from "./api.js";
```

Then append:

```ts
/** Semver compare, major.minor.patch only. No range syntax: the packet's
 *  floor is a single version, and a dependency for that would be absurd. */
export function isVersionSupported(min: string, current: string): boolean {
  const parse = (value: string) => value.split(".").map((part) => Number.parseInt(part, 10) || 0);
  const [a, b] = [parse(current), parse(min)];
  for (let i = 0; i < 3; i += 1) {
    const left = a[i] ?? 0;
    const right = b[i] ?? 0;
    if (left !== right) return left > right;
  }
  return true;
}

// THE message listener. Tasks 8, 9, 10, 11 and 12 add their cases INSIDE it.
// A second addListener returning true for the same message is a race over one
// sendResponse, and the loser throws where nobody sees it.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "packet") {
    void (async () => {
      try {
        const origin = await dashboardOrigin();
        if (!origin) throw new ExtError(401, "pairing_required");
        let packet = await loadPacket(message.applicationId);
        if (!packet) {
          packet = await fetchPacket(origin, message.applicationId);
          await storePacket(message.applicationId, packet);
        }
        const current = chrome.runtime.getManifest().version;
        if (!isVersionSupported(packet.min_extension_version, current)) {
          // Refuse rather than fill on a guess: an old build's fill semantics
          // are exactly what min_extension_version exists to distrust.
          sendResponse({ ok: false, code: "update_required" });
          return;
        }
        sendResponse({ ok: true, packet });
      } catch (error) {
        const code = error instanceof ExtError ? error.code : "request_failed";
        sendResponse({ ok: false, code });
      }
    })();
    // Keep the message channel open for the async reply above.
    return true;
  }
  return false;
});
```

- [ ] **Step 4: Build and run**

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_bundle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extension/src/service_worker.ts tests/portals/test_extension_bundle.py
git commit -m "feat(extension): fetch a packet once, and refuse one this build cannot honour"
```

---

### Task 5: The snapshot — describe the form, carry no value

**Files:**
- Create: `extension/src/content/snapshot.ts`, `extension/src/content/index.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: the live DOM.
- Produces: `buildSnapshot(root: Document): FormSnapshot`, `selectorFor(element: Element): string`, `accessibleName(element: Element): string`.

**The shape is fixed by the server.** `apps/portals/snapshot.py` declares `extra="forbid"` on both models: a key this file invents is a 400, not a silent extra. Fields, in order: `page_url`, `controls[] = {selector, tag, type, name, id, label, placeholder, options, required}`. There is **no `value` key and there must never be one** — the server also substring-scans every string in the snapshot for the student's own verified values and refuses the whole request on a hit (`SnapshotPIILeak`).

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_extension_bundle.py`:

```python
def test_the_snapshot_keys_match_the_server_schema() -> None:
    """extra='forbid' means an invented key is a 400 nobody can debug from the
    portal side. Both lists are short; pin them to each other."""
    from apps.portals.snapshot import SnapshotControl

    content = bundle_text("content.js")
    for field in SnapshotControl.model_fields:
        assert f"{field}:" in content.replace(" ", ""), f"snapshot never sets {field}"
```

**"Carries no value" is checked at runtime, not here.** A text scan for `.value` in a
bundle that legitimately reads `element.value` during fill and read-back is a test that
fails for the wrong reason. Task 13 builds a snapshot on a filled fixture page and asserts
no control object has a `value` key at all — definitive, and it cannot be fooled by a
rename.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k snapshot -v`
Expected: FAIL — `snapshot never sets selector`

- [ ] **Step 3: Write `extension/src/content/snapshot.ts`**

```ts
/**
 * Describe this page's form controls. Never what anyone typed into them.
 *
 * The server's FormSnapshot forbids extra keys and substring-scans every
 * string here for the student's own verified values, so a label reading
 * "Full name (Ada Byron)" is refused. That is the server's business; this
 * file's business is never to build such a thing in the first place.
 */

const FILLABLE = new Set(["input", "select", "textarea"]);

/** Types no packet may ever type into. `file` is handled separately (task 9);
 *  the rest are controls, secrets or payment fields. */
export const REFUSED_TYPES = new Set([
  "password",
  "hidden",
  "submit",
  "button",
  "image",
  "reset",
  "checkbox",
  "radio",
]);

export interface SnapshotControl {
  selector: string;
  tag: string;
  type: string;
  name: string;
  id: string;
  label: string;
  placeholder: string;
  options: string[];
  required: boolean;
}

export interface FormSnapshot {
  page_url: string;
  controls: SnapshotControl[];
}

/** A selector that resolves to this element and nothing else.
 *
 * Preference order is stability first: an id survives a re-render, a name
 * survives a class rename, and the nth-of-type path survives neither but is
 * better than no map at all. Verified against the page before every use, so a
 * stale one costs an unfilled field, never a wrong one. */
export function selectorFor(element: Element): string {
  const id = element.getAttribute("id");
  if (id) {
    const candidate = `#${CSS.escape(id)}`;
    if (document.querySelectorAll(candidate).length === 1) return candidate;
  }
  const name = element.getAttribute("name");
  if (name) {
    const candidate = `${element.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
    if (document.querySelectorAll(candidate).length === 1) return candidate;
  }
  const path: string[] = [];
  let node: Element | null = element;
  while (node && node !== document.documentElement) {
    const parent: Element | null = node.parentElement;
    if (!parent) break;
    const tag = node.tagName.toLowerCase();
    const index = Array.from(parent.children).filter((c) => c.tagName === node!.tagName).indexOf(node) + 1;
    path.unshift(`${tag}:nth-of-type(${index})`);
    node = parent;
  }
  return path.join(" > ");
}

/**
 * What this control calls itself, to a person reading the page.
 *
 * The same four sources the spec names -- label, aria-label, placeholder,
 * name -- plus aria-labelledby, which is how a real form supplies a label
 * that is not a <label>. This is the string the verification check judges.
 */
export function accessibleName(element: Element): string {
  const id = element.getAttribute("id");
  if (id) {
    const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    if (label?.textContent?.trim()) return label.textContent.trim();
  }
  const wrapping = element.closest("label");
  if (wrapping?.textContent?.trim()) return wrapping.textContent.trim();
  const ariaLabel = element.getAttribute("aria-label");
  if (ariaLabel?.trim()) return ariaLabel.trim();
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    const target = document.getElementById(labelledBy);
    if (target?.textContent?.trim()) return target.textContent.trim();
  }
  const placeholder = element.getAttribute("placeholder");
  if (placeholder?.trim()) return placeholder.trim();
  return element.getAttribute("name") ?? "";
}

export function buildSnapshot(root: Document): FormSnapshot {
  const controls: SnapshotControl[] = [];
  for (const element of Array.from(root.querySelectorAll("input, select, textarea"))) {
    const tag = element.tagName.toLowerCase();
    if (!FILLABLE.has(tag)) continue;
    const type = (element.getAttribute("type") ?? "").toLowerCase();
    if (REFUSED_TYPES.has(type)) continue;
    controls.push({
      selector: selectorFor(element),
      tag,
      type,
      name: element.getAttribute("name") ?? "",
      id: element.getAttribute("id") ?? "",
      label: accessibleName(element),
      placeholder: element.getAttribute("placeholder") ?? "",
      options:
        element instanceof HTMLSelectElement
          ? Array.from(element.options).map((option) => option.text)
          : [],
      required: element.hasAttribute("required"),
    });
    // The server caps the list at 200 and rejects a longer one outright. Cut
    // here so a sprawling page produces a partial map rather than a 400.
    if (controls.length >= 200) break;
  }
  return { page_url: location.href, controls };
}
```

- [ ] **Step 4: Write the content entry point (task 5 version)**

`extension/src/content/index.ts`:

```ts
/**
 * Everything that touches the portal page, and nothing else.
 *
 * Injected on a user gesture only -- there is no declared content script, so
 * this file does not exist on any page the student did not open it on. It
 * holds no credential: every server call goes through the service worker.
 */
import { buildSnapshot } from "./snapshot.js";

async function ask<T>(message: unknown): Promise<T> {
  return (await chrome.runtime.sendMessage(message)) as T;
}

async function run(applicationId: string, portalFormId: string): Promise<void> {
  await ask({ type: "snapshot", portalFormId, snapshot: buildSnapshot(document) });
  const packet = await ask<{ ok: boolean; code?: string }>({ type: "packet", applicationId });
  if (!packet.ok) {
    await ask({ type: "dock", patch: { status: "blocked", message: packet.code } });
  }
}

// The worker injects this file and then sends one start message.
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "start") {
    void run(message.applicationId, message.portalFormId);
  }
  return false;
});
```

Add the `snapshot` case to the worker's `onMessage` listener, beside the `packet` case:

```ts
  if (message?.type === "snapshot") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      try {
        const learned = await postSnapshot(origin, message.portalFormId, message.snapshot);
        sendResponse({ ok: true, version: learned.field_map_version });
      } catch (error) {
        // 422 unmapped_fields and 429 rate_limited are both ordinary answers
        // here: the first means this form asks for things we do not hold, the
        // second that this tenant has learned enough forms this hour.
        sendResponse({ ok: false, code: error instanceof ExtError ? error.code : "request_failed" });
      }
    })();
    return true;
  }
```

- [ ] **Step 5: Build and run**

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_bundle.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add extension/src/content tests/portals/test_extension_bundle.py
git commit -m "feat(extension): describe the form to the server, and never what is in it"
```

---

### Task 6: The verification check — refuse to type into a control we cannot recognise

**Files:**
- Create: `extension/src/content/verify.ts`, `extension/src/content/vocabulary.ts`
- Test: `tests/portals/test_extension_bundle.py` (static), and the end-to-end fixtures in task 13

**Interfaces:**
- Consumes: `PacketField[]`, `accessibleName`, `REFUSED_TYPES`.
- Produces: `verifyEntries(entries: PacketField[]): VerifiedEntry[]` where
  `VerifiedEntry = { entry: PacketField; element: HTMLElement | null; ok: boolean; reason: string }`.

**This is the task the spec says must not be dropped.** Read that section before starting. The short version: a `FieldMap` learned from a snapshot is a claim by a client, the server has no page to check it against, and read-back cannot catch a bad claim because it reads back the same selector it typed into. The extension is the only party that sees the real page.

**Its known ceiling, stated so nobody has to re-derive it:** the name check is a token table, and a portal in a language the table does not cover will match nothing and leave every field unfilled. That is the safe direction — the student falls back to the Application Kit, which is exactly what the kit is for — but it is a real utility cost, and the fix when it bites is more data in `vocabulary.ts`, never a softer rule. Do not relax this check without the owner.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_extension_bundle.py`:

```python
def test_the_content_script_refuses_before_it_types() -> None:
    """The whole point of the check is its ORDER.

    Verification that ran after the fill would be a report, not a guard. The
    built bundle must contain the refusal reasons, and the e2e fixtures in
    test_extension_e2e.py prove the ordering against a real page.
    """
    content = bundle_text("content.js")
    for reason in ("no_such_control", "not_unique", "hidden", "disabled", "name_mismatch"):
        assert reason in content, f"the verification check has no {reason} refusal"


def test_no_code_path_clicks() -> None:
    """The student presses every button. This is the spec's hardest line.

    A static scan of the built bundle, not of the sources: what ships is what
    Chrome runs. `.click(` catches element.click(); MouseEvent and
    requestSubmit catch the two ways to fake one.
    """
    for name in ("content.js", "service_worker.js"):
        text = bundle_text(name).replace(" ", "")
        for banned in (".click(", "MouseEvent", "PointerEvent", "requestSubmit", ".submit("):
            assert banned not in text, f"{name} contains {banned}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k "refuses or clicks" -v`
Expected: FAIL — `the verification check has no no_such_control refusal`

- [ ] **Step 3: Write `extension/src/content/vocabulary.ts`**

```ts
/**
 * What a control asking for a given profile field plausibly calls itself.
 *
 * DATA, not logic. Keyed by the KEY half of a profile field ("personal.
 * given_name" -> "given_name"), because the category half names where a fact
 * came from, not what a form calls it.
 *
 * ponytail: a token table, not a language model. Its ceiling is honest and
 * one-directional -- a portal in a language not represented here matches
 * nothing, so its fields are left UNFILLED and the student does them by hand
 * from the Application Kit. It never causes a wrong fill. When a real portal
 * measures badly, add tokens here; do not soften verify.ts.
 */
export const TOKENS: Record<string, readonly string[]> = {
  given_name: ["given", "first", "forename", "christian", "vorname", "prenom", "nombre", "ad"],
  family_name: ["family", "last", "surname", "nachname", "familienname", "nom", "apellido", "soyad"],
  middle_name: ["middle", "zweiter"],
  full_name: ["full name", "name", "nom complet", "vollstandiger", "ad soyad"],
  date_of_birth: ["birth", "born", "dob", "geburt", "naissance", "nacimiento", "dogum"],
  place_of_birth: ["place of birth", "birthplace", "geburtsort", "lieu de naissance"],
  nationality: ["nationality", "citizen", "staatsangeh", "nationalite", "nacionalidad", "uyruk"],
  gender: ["gender", "sex", "geschlecht", "sexe", "cinsiyet"],
  email: ["email", "e-mail", "mail", "correo", "eposta", "e-posta"],
  phone: ["phone", "mobile", "telephone", "telefon", "movil", "cep"],
  address: ["address", "street", "adresse", "strasse", "direccion", "adres"],
  city: ["city", "town", "stadt", "ort", "ville", "ciudad", "sehir"],
  postal_code: ["postal", "post code", "zip", "plz", "postleitzahl", "code postal", "posta kodu"],
  country: ["country", "land", "pays", "pais", "ulke"],
  passport_number: ["passport", "reisepass", "passeport", "pasaporte", "pasaport"],
  national_id: ["national id", "identity", "personalausweis", "kimlik", "tc"],
  institution: ["institution", "university", "school", "hochschule", "universitat", "universite", "universidad", "okul"],
  degree: ["degree", "qualification", "abschluss", "diplome", "titulo", "derece"],
  field_of_study: ["field of study", "subject", "major", "studienfach", "domaine", "bolum"],
  graduation_date: ["graduation", "completed", "abschlussdatum", "obtention", "mezuniyet"],
  grade: ["grade", "gpa", "mark", "note", "durchschnitt", "moyenne", "not"],
};

/** Everything a token match has to survive: case, accents and punctuation. */
export function normalise(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** The key half of "category.key". */
export function fieldKey(profileField: string): string {
  const parts = profileField.split(".");
  return parts[parts.length - 1] ?? profileField;
}
```

- [ ] **Step 4: Write `extension/src/content/verify.ts`**

```ts
/**
 * Does this selector name the control the packet thinks it does?
 *
 * The server cannot answer this: it never saw the page, and a FieldMap
 * learned from a snapshot is a CLAIM by a client. Read-back cannot answer it
 * either -- it reads back the selector it typed into and finds the value
 * sitting there, so a wrong-but-consistent map verifies clean. This file is
 * the only place in the system where the map meets the real page.
 *
 * Every refusal leaves the field UNFILLED and visible in the dock. Refusing is
 * always cheaper than typing a date of birth into a free-text box a university
 * will read.
 */
import type { PacketField } from "../types.js";
import { REFUSED_TYPES, accessibleName } from "./snapshot.js";
import { TOKENS, fieldKey, normalise } from "./vocabulary.js";

export interface VerifiedEntry {
  entry: PacketField;
  element: HTMLElement | null;
  ok: boolean;
  /** "" when ok. Otherwise one of the stable reasons below. */
  reason: string;
}

const FILL_METHODS = new Set(["fill", "type", "selectOption", "selectOptionFromDropdown"]);

function visible(element: HTMLElement): boolean {
  if (element.hidden) return false;
  const style = getComputedStyle(element);
  if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
    return false;
  }
  // offsetParent is null for a fixed-position element too, so the rect is the
  // arbiter: a control with no area is one no person could have filled.
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

/**
 * Does this control's own name say it asks for this fact?
 *
 * Three outcomes, and only the middle one is a judgement call:
 *  - the name contains one of the field's own tokens -> yes;
 *  - the name contains tokens of a DIFFERENT field in the same packet and
 *    none of its own -> no, and this is the mis-aimed-map case the check
 *    exists for;
 *  - the name matches nothing we know -> no. See vocabulary.ts's ceiling note.
 */
function nameMatches(name: string, profileField: string): boolean {
  const own = TOKENS[fieldKey(profileField)];
  if (!own) return false;
  const haystack = normalise(name);
  if (!haystack) return false;
  return own.some((token) => haystack.includes(normalise(token)));
}

export function verifyEntries(entries: PacketField[]): VerifiedEntry[] {
  return entries.map((entry) => {
    const refuse = (reason: string): VerifiedEntry => ({ entry, element: null, ok: false, reason });

    if (!FILL_METHODS.has(entry.method)) return refuse("method_not_allowed");

    let matches: NodeListOf<Element>;
    try {
      matches = document.querySelectorAll(entry.selector);
    } catch {
      // An unparseable selector is a malformed map, not a missing control.
      return refuse("bad_selector");
    }
    if (matches.length === 0) return refuse("no_such_control");
    // Two matches means the selector does not identify anything: typing into
    // the first is a coin flip the student would be right to resent.
    if (matches.length > 1) return refuse("not_unique");

    const element = matches[0];
    if (!(element instanceof HTMLElement)) return refuse("no_such_control");

    const tag = element.tagName.toLowerCase();
    if (!["input", "select", "textarea"].includes(tag)) return refuse("not_a_control");

    const type = (element.getAttribute("type") ?? "").toLowerCase();
    if (REFUSED_TYPES.has(type)) return refuse("refused_type");
    if (entry.method.startsWith("selectOption") && tag !== "select") return refuse("not_a_select");

    if (!visible(element)) return refuse("hidden");
    if (
      (element as HTMLInputElement).disabled ||
      (element as HTMLInputElement).readOnly ||
      element.getAttribute("aria-disabled") === "true"
    ) {
      return refuse("disabled");
    }

    if (!nameMatches(accessibleName(element), entry.profile_field)) return refuse("name_mismatch");

    return { entry, element, ok: true, reason: "" };
  });
}

/**
 * The frame this run is allowed to act in.
 *
 * A packet is minted for one form on one origin. A content script runs per
 * frame, so without this an embedded third-party iframe on a portal page
 * would be filled from the same packet.
 */
export function originMatches(formUrl: string): boolean {
  try {
    return new URL(formUrl).origin === location.origin && window.top === window;
  } catch {
    return false;
  }
}
```

- [ ] **Step 5: Build and run the tests**

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_bundle.py -q`
Expected: PASS, including `test_no_code_path_clicks`.

- [ ] **Step 6: Commit**

```bash
git add extension/src/content/verify.ts extension/src/content/vocabulary.ts \
        tests/portals/test_extension_bundle.py
git commit -m "feat(extension): the only party that sees the page checks the map against it"
```

---

### Task 7: Fill — type, and only type

**Files:**
- Create: `extension/src/content/fill.ts`
- Modify: `extension/src/content/index.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: `VerifiedEntry[]`.
- Produces: `alreadyCorrect(verified: VerifiedEntry[]): Set<string>`, `fillVerified(verified: VerifiedEntry[], skip: Set<string>): string[]`.

**Ported from** `apps/portals/fill.py::already_correct` and `fill_form`. The Python versions stay where they are — they are the packet-side unit tests' subject and the spec says to keep them.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_extension_bundle.py`:

```python
def test_the_content_script_types_only_the_allowed_methods() -> None:
    """The spec's allowlist parity test.

    The content script's set of DOM-mutating operations must equal the
    server's FILL_METHODS plus setFiles (task 9's document attachment, which is
    never a stored field-map method -- see this plan's Global Constraints).
    """
    from apps.portals.session import FILL_METHODS

    content = bundle_text("content.js")
    for method in FILL_METHODS:
        assert f'"{method}"' in content, f"the content script does not know {method}"
    # The inverse: nothing beyond the allowlist plus setFiles. Stagehand's
    # takeDeterministicAction dispatched sixteen; these are the ones whose
    # presence here would mean the port grew them back.
    for banned in ("doubleClick", "dragAndDrop", "scrollTo", "press"):
        assert banned not in content, f"the content script can {banned}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k allowed_methods -v`
Expected: FAIL — `the content script does not know selectOptionFromDropdown`

- [ ] **Step 3: Write `extension/src/content/fill.ts`**

```ts
/**
 * Type a verified value into a verified control. Nothing else.
 *
 * Ported from apps/portals/fill.py, which keeps its Python versions for the
 * packet-side unit tests. Two things are different in a browser and both are
 * load-bearing:
 *
 *  - React and every framework like it install a value setter on the element's
 *    prototype and ignore a plain `element.value = x`. The native setter plus
 *    input/change events is the standard technique, and read-back is what
 *    catches the pages where even that is not enough.
 *  - There is no click anywhere in this file, including for a <select>.
 *    selectOption sets `value` and fires change; the dropdown is never opened.
 */
import type { VerifiedEntry } from "./verify.js";

/** Mirrors apps/portals/session.py::FILL_METHODS. The parity test pins it. */
const FILL_METHODS = ["fill", "type", "selectOption", "selectOptionFromDropdown"] as const;

function nativeSetValue(element: HTMLElement, value: string): void {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  if (setter) setter.call(element, value);
  else (element as HTMLInputElement).value = value;
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function currentValue(element: HTMLElement): string {
  return (element as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value ?? "";
}

/** Fields the page already holds correctly -- the only ones safe to skip.
 *  A portal that persisted its own draft returns most of them. */
export function alreadyCorrect(verified: VerifiedEntry[]): Set<string> {
  const correct = new Set<string>();
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    if (currentValue(item.element) === item.entry.value) correct.add(item.entry.profile_field);
  }
  return correct;
}

/** Type every verified entry not in `skip`. Returns the fields filled.
 *
 *  Only entries that PASSED verification are here at all: the caller filters
 *  first, so there is no path through this function that types into a control
 *  verify.ts refused. */
export function fillVerified(verified: VerifiedEntry[], skip: Set<string>): string[] {
  const filled: string[] = [];
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    if (skip.has(item.entry.profile_field)) continue;
    if (!FILL_METHODS.includes(item.entry.method as (typeof FILL_METHODS)[number])) continue;
    if (item.entry.method.startsWith("selectOption") && item.element instanceof HTMLSelectElement) {
      const option = Array.from(item.element.options).find(
        (candidate) => candidate.value === item.entry.value || candidate.text === item.entry.value,
      );
      // No option, no guess: an unmatched select is the student's to answer.
      if (!option) continue;
      nativeSetValue(item.element, option.value);
    } else {
      nativeSetValue(item.element, item.entry.value);
    }
    filled.push(item.entry.profile_field);
  }
  return filled;
}

/** What the page holds now, against what the packet says it should.
 *  Runs against the RENDERED page, never against what we believe we typed. */
export function readBack(
  verified: VerifiedEntry[],
): { profile_field: string; expected: string; actual: string }[] {
  const mismatches = [];
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    const actual = currentValue(item.element);
    if (actual !== item.entry.value) {
      mismatches.push({
        profile_field: item.entry.profile_field,
        expected: item.entry.value,
        actual,
      });
    }
  }
  return mismatches;
}
```

- [ ] **Step 4: Build and run**

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_bundle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extension/src/content/fill.ts tests/portals/test_extension_bundle.py
git commit -m "feat(extension): type a verified value into a verified control, and nothing else"
```

---

### Task 8: The run — verify, fill, read back, report

**Files:**
- Modify: `extension/src/content/index.ts`, `extension/src/service_worker.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: everything above.
- Produces: the `FILL` and `READ_BACK` events on `POST /ext/applications/{id}/events`; the dock patches.

**Event shapes** (`ext_api.py::events` validates `kind` against `_EVENT_KINDS` and requires `detail` to be an object):
- `FILL`: `{ filled: string[], refused: [{ profile_field, reason }], field_map_version }`
- `READ_BACK`: `{ mismatches: [{ profile_field, expected, actual }] }` — **a non-empty `mismatches` escalates `PORTAL_ERROR` server-side and moves the application to `BLOCKED_PORTAL_ERROR`.** Post it once, at the end, never per field.

- [ ] **Step 1: Write the failing test**

Append to `tests/portals/test_extension_bundle.py`:

```python
def test_the_extension_reports_only_kinds_the_server_accepts() -> None:
    """ext_api rejects an unknown kind with 400 and no explanation the student
    can act on. Both lists are short; pin them."""
    from apps.portals.ext_api import _EVENT_KINDS

    content = bundle_text("content.js") + bundle_text("service_worker.js")
    reported = {kind for kind in _EVENT_KINDS if f'"{kind}"' in content}
    assert "FILL" in reported and "READ_BACK" in reported
    # Nothing outside the server's set.
    for forbidden in ("PACKET", "ESCALATION", "RECOVERY"):
        assert f'"{forbidden}"' not in content, f"the extension writes {forbidden} rows"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k kinds -v`
Expected: FAIL — `assert 'FILL' in reported`

- [ ] **Step 3: Write the run**

Replace `extension/src/content/index.ts`:

```ts
/**
 * The order of operations, and the order is the security model:
 *
 *   origin check -> snapshot (once, if the server has no map) -> packet ->
 *   VERIFY -> skip what is already right -> fill -> read back -> report.
 *
 * Verification is before the fill and not after it. After, it would be a
 * report; before, it is a guard.
 */
import type { FillPacket } from "../types.js";
import { alreadyCorrect, fillVerified, readBack } from "./fill.js";
import { buildSnapshot } from "./snapshot.js";
import { originMatches, verifyEntries } from "./verify.js";

async function ask<T>(message: unknown): Promise<T> {
  return (await chrome.runtime.sendMessage(message)) as T;
}

async function dock(patch: Record<string, unknown>): Promise<void> {
  await ask({ type: "dock", patch });
}

async function run(applicationId: string, portalFormId: string): Promise<void> {
  let response = await ask<{ ok: boolean; code?: string; packet?: FillPacket }>({
    type: "packet",
    applicationId,
  });

  if (!response.ok && response.code === "no_field_map") {
    // First time anyone in this agency has met this form. The snapshot is
    // value-free; the server learns from it and scopes the map to this tenant.
    const learned = await ask<{ ok: boolean; code?: string }>({
      type: "snapshot",
      portalFormId,
      snapshot: buildSnapshot(document),
    });
    if (!learned.ok) {
      await dock({ status: "blocked", message: learned.code ?? "learn_failed" });
      return;
    }
    response = await ask({ type: "packet", applicationId });
  }

  if (!response.ok || !response.packet) {
    await dock({ status: "blocked", message: response.code ?? "no_packet" });
    return;
  }
  const packet = response.packet;

  if (!originMatches(packet.form_url)) {
    await dock({ status: "blocked", message: "wrong_page" });
    return;
  }

  await dock({ status: "filling", applicationId });
  const verified = verifyEntries(packet.entries);
  const refused = verified
    .filter((item) => !item.ok)
    .map((item) => ({ profile_field: item.entry.profile_field, reason: item.reason }));

  const skip = alreadyCorrect(verified);
  const filled = fillVerified(verified, skip);

  await ask({
    type: "event",
    applicationId,
    kind: "FILL",
    detail: { filled, refused, field_map_version: packet.field_map_version },
  });

  const mismatches = readBack(verified.filter((item) => item.ok));
  await ask({
    type: "event",
    applicationId,
    kind: "READ_BACK",
    detail: { mismatches },
  });

  await dock({
    status: refused.length || mismatches.length ? "blocked" : "done",
    filled,
    yourTurn: refused.map((item) => ({ label: item.profile_field, reason: item.reason })),
    mismatches: mismatches.map((item) => ({
      label: item.profile_field,
      expected: item.expected,
      actual: item.actual,
    })),
    // The one thing the student must be told every single time.
    message: "Check the form, then press the portal's own Submit button yourself.",
  });
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "start") void run(message.applicationId, message.portalFormId);
  return false;
});
```

Add the `event` case to the worker's listener, beside `packet` and `snapshot`:

```ts
  if (message?.type === "event") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      try {
        await postEvent(origin, message.applicationId, message.kind, message.detail);
        sendResponse({ ok: true });
      } catch (error) {
        sendResponse({ ok: false, code: error instanceof ExtError ? error.code : "request_failed" });
      }
    })();
    return true;
  }
```

- [ ] **Step 4: Build and run everything**

Run: `npm --prefix extension run check && uv run pytest tests/portals -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extension/src tests/portals/test_extension_bundle.py
git commit -m "feat(extension): verify, fill, read back, and hand the form to the student"
```

**Stop point.** The extension now does the job the spec describes for a text form. Tasks 9–13 add documents, page signals, actions, the dock and the end-to-end harness.

---

### Task 9: Attach an approved document

**Files:**
- Create: nothing
- Modify: `extension/src/content/fill.ts`, `extension/src/content/index.ts`, `extension/src/service_worker.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: `PacketDocument`, `GET <origin><download_path>` (session-authenticated, `@login_required`).
- Produces: `attachDocuments(documents: { filename: string; bytes: ArrayBuffer }[]): { attached: string[]; manual: string[] }`.

**Why `setFiles` is not in `FILL_METHODS`.** The spec's "What changes in code" line says `session.py` gains `setFiles`. It does not need to: a file input is never a field-map entry. The map maps *profile fields*, `learn_from_snapshot` derives the method from the control's tag for profile fields only, and `mint_packet` runs every entry through `is_fillable`. Adding `setFiles` there would put a file-writing method into a stored, tenant-shared table that a hostile snapshot can aim — for no gain, because the content script can find `input[type=file]` on the page in front of it. So `setFiles` lives only here, as the content script's own vocabulary, and the spec's parity test (`FILL_METHODS | {"setFiles"}`) is satisfied exactly. **Record this deviation in the commit message.**

The service worker fetches the PDF from the dashboard origin **with credentials**, because `download_document` is `@login_required` and the student's session cookie is what authorizes it. The bytes go to the content script as an `ArrayBuffer` over `chrome.runtime.sendMessage` (structured clone), never through a page-accessible channel.

- [ ] **Step 1: Write the failing test**

```python
def test_setfiles_is_the_content_script_s_own_vocabulary() -> None:
    """The spec's allowlist parity: FILL_METHODS | {"setFiles"}.

    setFiles must NOT be in the server's FILL_METHODS -- a file-writing method
    in a stored, tenant-shared field map is a method a hostile snapshot can
    aim. The content script finds file inputs itself.
    """
    from apps.portals.session import FILL_METHODS

    assert "setFiles" not in FILL_METHODS
    assert "setFiles" in bundle_text("content.js")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k setfiles -v`
Expected: FAIL — `assert 'setFiles' in bundle_text('content.js')`

- [ ] **Step 3: Append to `extension/src/content/fill.ts`**

```ts
/** The one operation beyond typing, and it is not a click.
 *
 *  `setFiles` writes a DataTransfer onto a native file input. Custom
 *  drag-and-drop and direct-to-S3 widgets expose no such input; those become a
 *  dock instruction ("attach cv.pdf here"), which is the honest answer and the
 *  one the spec's Risks section chose. */
export function attachDocuments(
  documents: { filename: string; bytes: ArrayBuffer }[],
): { attached: string[]; manual: string[] } {
  const inputs = Array.from(document.querySelectorAll("input[type=file]")).filter(
    (input): input is HTMLInputElement => input instanceof HTMLInputElement && !input.disabled,
  );
  const attached: string[] = [];
  const manual: string[] = [];
  for (const item of documents) {
    // Match by the input's own name, the same accessible name the
    // verification check reads. No name, no guess.
    const target = inputs.find((input) => {
      const name = normaliseName(accessibleNameOf(input));
      return name.includes("cv") || name.includes("resume") || name.includes("curriculum");
    });
    if (!target) {
      manual.push(item.filename);
      continue;
    }
    const transfer = new DataTransfer();
    transfer.items.add(new File([item.bytes], item.filename, { type: "application/pdf" }));
    // setFiles
    target.files = transfer.files;
    target.dispatchEvent(new Event("change", { bubbles: true }));
    attached.push(item.filename);
    inputs.splice(inputs.indexOf(target), 1);
  }
  return { attached, manual };
}
```

Import `accessibleName as accessibleNameOf` from `./snapshot.js` and `normalise as normaliseName` from `./vocabulary.js` at the top of `fill.ts`.

- [ ] **Step 4: Fetch the bytes in the worker**

Add to the worker's listener:

```ts
  if (message?.type === "document") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      // credentials: "include" -- download_document is @login_required and the
      // student's own session cookie is what authorizes their own document.
      const response = await fetch(`${origin}${message.path}`, { credentials: "include" });
      if (!response.ok) return sendResponse({ ok: false, code: "document_unavailable" });
      sendResponse({ ok: true, bytes: await response.arrayBuffer() });
    })();
    return true;
  }
```

- [ ] **Step 5: Call it from the run**

In `content/index.ts`, after the fill and before the read-back:

```ts
  const fetched: { filename: string; bytes: ArrayBuffer }[] = [];
  for (const document_ of packet.documents) {
    const result = await ask<{ ok: boolean; bytes?: ArrayBuffer }>({
      type: "document",
      path: document_.download_path,
    });
    if (result.ok && result.bytes) fetched.push({ filename: document_.filename, bytes: result.bytes });
  }
  const attachments = attachDocuments(fetched);
```

and add `attachments` to the `FILL` event's detail and `attachments.manual` to the dock's `yourTurn`.

- [ ] **Step 6: Build, run, commit**

```bash
npm --prefix extension run check && uv run pytest tests/portals -q
git add extension/src tests/portals/test_extension_bundle.py
git commit -m "feat(extension): attach the approved PDF without widening the stored allowlist

The spec's 'session.py: add setFiles' line is satisfied by the content
script's own vocabulary instead. A file-writing method in FieldMap.entries
would be a method a hostile snapshot could aim at a control of its choosing,
and it buys nothing: the content script can see the page's file inputs."
```

---

### Task 10: Page signals — a challenge, a confirmation, a status page

**Files:**
- Create: `extension/src/content/page_signals.ts`
- Modify: `extension/src/content/index.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: `apps/portals/challenge.py::MARKERS` (ported verbatim).
- Produces: `detectChallenge(): { kind: string } | null`, `detectConfirmation(markers: string[]): boolean`, `readStatus(): { portal_state, application_number, document_requests }`.

**A challenge escalates nothing.** The student is standing in front of the page — `ext_api.events` writes the `CHALLENGE` row and does not escalate. The dock says "the portal is asking you to prove you are human". No solver, ever.

- [ ] **Step 1: Write the failing test**

```python
def test_the_challenge_markers_match_the_server_s() -> None:
    """Ported, not reinvented. A marker the extension does not know is a
    challenge the student is not told about."""
    from apps.portals.challenge import MARKERS

    content = bundle_text("content.js")
    for _kind, container, _attribute, _response in MARKERS:
        assert container in content, f"the content script does not know {container}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k challenge -v`
Expected: FAIL — `the content script does not know .g-recaptcha`

- [ ] **Step 3: Write `extension/src/content/page_signals.ts`**

```ts
/**
 * What the page is telling us, read deterministically.
 *
 * Ported from apps/portals/challenge.py. Every marker is a container the
 * provider's own script renders; nothing here infers a challenge from page
 * text or a model's opinion. A false positive interrupts a student who was
 * doing fine; a false negative strands one.
 */
const CHALLENGE_MARKERS: [string, string][] = [
  ["recaptcha", ".g-recaptcha"],
  ["hcaptcha", ".h-captcha"],
  ["turnstile", ".cf-turnstile"],
];

export function detectChallenge(): { kind: string } | null {
  for (const [kind, container] of CHALLENGE_MARKERS) {
    if (document.querySelector(container)) return { kind };
  }
  return null;
}

/** Did the portal say it received the application?
 *
 *  Markers come from PortalForm.confirmation_markers via the packet when that
 *  column is populated; with none configured this answers false, which is the
 *  right default -- a SUBMITTED row we invented is worse than one we missed,
 *  because the student's roadmap card would move on a guess. */
export function detectConfirmation(markers: string[]): boolean {
  if (markers.length === 0) return false;
  const text = document.body?.innerText ?? "";
  return markers.some((marker) => text.includes(marker));
}

/** A portal's own account page, as the extension read it. Capped here as well
 *  as server-side (ext_api._PortalStatus) so a hostile page cannot make the
 *  request large enough to be refused for the wrong reason. */
export function readStatus(): {
  portal_state: string;
  application_number: string;
  document_requests: string[];
} {
  const text = (document.body?.innerText ?? "").slice(0, 5000);
  const number = /\b(?:application|reference)\s*(?:no\.?|number|id)[:\s]*([A-Z0-9-]{4,40})/i.exec(text);
  return {
    portal_state: (document.title ?? "").slice(0, 200),
    application_number: (number?.[1] ?? "").slice(0, 100),
    document_requests: Array.from(document.querySelectorAll("[data-document-request]"))
      .slice(0, 50)
      .map((node) => (node.textContent ?? "").trim().slice(0, 200))
      .filter(Boolean),
  };
}
```

- [ ] **Step 4: Call the challenge check from the run**

In `content/index.ts`, immediately after `originMatches` and before verification:

```ts
  const challenge = detectChallenge();
  if (challenge) {
    await ask({ type: "event", applicationId, kind: "CHALLENGE", detail: { kind: challenge.kind } });
    await dock({
      status: "blocked",
      message: "The portal is asking you to prove you are human. Do that, then start again.",
    });
    return;
  }
```

- [ ] **Step 5: Report a confirmation the student's own click produced**

The student presses Submit. The extension is still injected in that tab, so it watches
for the portal's own confirmation and reports it — this is the "Handshake" row of the
spec's architecture diagram, and the reason `Application.State` can reach `SUBMITTED`
without anything of ours ever clicking.

Append to `content/index.ts`, at the end of `run`:

```ts
  // The student is about to press Submit. A confirmation appears after a
  // navigation or a re-render, so watch rather than check once. Disconnected
  // after the first hit: one SUBMITTED row per run, and the observer must not
  // outlive the thing it is observing.
  const markers = packet.confirmation_markers ?? [];
  if (markers.length > 0) {
    const observer = new MutationObserver(() => {
      if (!detectConfirmation(markers)) return;
      observer.disconnect();
      void ask({
        type: "event",
        applicationId,
        kind: "SUBMITTED",
        detail: { form_url: packet.form_url },
      });
      void ask({
        type: "event",
        applicationId,
        kind: "STATUS",
        detail: readStatus(),
      });
      void dock({ status: "done", message: "The portal confirmed it received your application." });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
```

Add `confirmation_markers: string[] | null` to `FillPacket` in `types.ts`. **The server
does not send it yet** — `PortalForm.confirmation_markers` is listed in the spec's "What
changes in code" as a column to add, and no plan has added it. Until it exists the field
is absent, `markers` is empty, and no `SUBMITTED` row is ever written from a guess. That
is the correct default and it is why `detectConfirmation([])` returns `false`: an invented
SUBMITTED moves the student's roadmap card on nothing.

**Follow-up for whoever adds the column:** `mint_packet` sets `confirmation_markers` from
`application.portal_form.confirmation_markers`, and this code starts working with no
change. Record it in the plan's follow-ups, not as a TODO in the source.

- [ ] **Step 6: Post the portal's own status page**

`readStatus` above feeds the `STATUS` event. The dedicated route
(`POST /ext/applications/{id}/status`, validated by `_PortalStatus`) exists for the case
the spec's owner decision 7 describes — the student opens their portal *account* page
later, not during a fill. Add it to `api.ts`:

```ts
export async function postStatus(
  origin: string,
  applicationId: string,
  status: { portal_state: string; application_number: string; document_requests: string[] },
): Promise<void> {
  await call(origin, `/ext/applications/${applicationId}/status`, {
    method: "POST",
    body: JSON.stringify(status),
  });
}
```

and a `status` case in the worker's listener, shaped exactly like the `event` case but
calling `postStatus`. The content script sends `{ type: "status", applicationId, status:
readStatus() }` when a device action of kind `READ_STATUS` named this application (task
11 delivers those).

- [ ] **Step 7: Build, run, commit**

```bash
npm --prefix extension run check && uv run pytest tests/portals -q
git add extension/src/content tests/portals/test_extension_bundle.py
git commit -m "feat(extension): read the page's own signals, solve none of them"
```

---

### Task 11: The device-action poller

**Files:**
- Modify: `extension/src/api.ts`, `extension/src/service_worker.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: `GET /ext/actions`, `POST /ext/actions/{id}/result`.
- Produces: a `chrome.alarms`-free poll on dashboard-tab activation.

**An action is delivered once.** `actions.py::pending_actions` marks every row delivered as it returns it, and the payload is cleared on completion. A poller that drops a response drops the action — so post the result before touching anything else, and never poll from two contexts.

Plan 4 produces the rows; until then the queue is empty and this is a contract test, not a feature.

- [ ] **Step 1: Write the failing test**

```python
def test_the_extension_polls_actions_on_a_bounded_schedule() -> None:
    """ext_api caps this at 120/hour per membership. A poller without its own
    interval discovers that cap at a student's deadline."""
    worker = bundle_text("service_worker.js")
    assert "/ext/actions" in worker
    assert "setInterval" not in worker, "a service worker is unloaded; setInterval does not survive it"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k polls -v`
Expected: FAIL — `assert '/ext/actions' in worker`

- [ ] **Step 3: Add the calls to `api.ts`**

```ts
export interface DeviceActionRow {
  id: string;
  kind: string;
  application_id: string | null;
  payload: Record<string, unknown>;
  expires_at: string;
}

export async function fetchActions(origin: string): Promise<DeviceActionRow[]> {
  const body = (await call(origin, "/ext/actions")) as { actions: DeviceActionRow[] };
  return body.actions;
}

export async function postActionResult(
  origin: string,
  actionId: string,
  ok: boolean,
  detail: Record<string, unknown>,
): Promise<void> {
  await call(origin, `/ext/actions/${actionId}/result`, {
    method: "POST",
    body: JSON.stringify({ ok, detail }),
  });
}
```

- [ ] **Step 4: Poll on tab activation, not on a timer**

Append to `service_worker.ts`:

```ts
// A service worker is unloaded when idle, so setInterval does not survive.
// The student's own dashboard visit is the schedule -- it is also the only
// moment an action (a verification link to open, a code to type) is useful.
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const origin = await dashboardOrigin();
  if (!origin) return;
  const tab = await chrome.tabs.get(tabId);
  // tab.url is undefined for every tab we hold no host permission for, which
  // is every tab but the dashboard. That is the filter, not a bug to fix with
  // a "tabs" permission -- asking for one would let us read every URL the
  // student visits, to answer a question we can already answer.
  if (!tab.url?.startsWith(origin)) return;
  for (const action of await fetchActions(origin)) {
    if (action.kind === "OPEN_LINK" && typeof action.payload["url"] === "string") {
      // Opened in the student's own browser, in a new tab they can see. No
      // navigation of the tab they are standing on.
      await chrome.tabs.create({ url: action.payload["url"] as string, active: false });
      await postActionResult(origin, action.id, true, { opened: true });
    } else {
      // Anything else is for the student to do; the dock shows it and the
      // result is posted when they say so.
      await chrome.runtime.sendMessage({ type: "dock", patch: { message: action.kind } });
    }
  }
});
```

- [ ] **Step 5: Build, run, commit**

```bash
npm --prefix extension run check && uv run pytest tests/portals -q
git add extension/src tests/portals/test_extension_bundle.py
git commit -m "feat(extension): poll for what to do next when the student is actually there"
```

---

### Task 12: The dock — behaviour now, design by Aykhan

**Files:**
- Create: `extension/src/panel/panel.html`, `extension/src/panel/panel.ts`
- Modify: `extension/src/service_worker.ts`
- Test: `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Consumes: `DockState` (from `types.ts`) via `chrome.runtime.sendMessage({type: "dock", patch})`.
- Produces: `render(state: DockState): void` — **the only function in the extension that writes DOM outside a portal page.**

> **SHOULD BE DONE BY AYKHAN.** The panel's visual design — layout, type, colour, motion, copy — is his. This task builds a correct, unstyled surface and puts every piece of state on screen, so his work is a rewrite of `panel.ts`'s `render` and `panel.html`'s markup and touches nothing else. Do not choose a UI framework, a design system or a visual direction here.

- [ ] **Step 1: Write the failing test**

```python
def test_the_panel_is_the_only_dom_owner_and_is_marked_for_handover() -> None:
    """One module owns the dock's DOM, so replacing the design replaces one
    file. The marker is what tells the next session not to design it.

    content/ is excluded on purpose: it writes to the PORTAL's DOM, which is
    its whole job. This asserts nothing else builds the DOCK's.
    """
    panel = pathlib.Path(__file__).resolve().parents[2] / "extension" / "src" / "panel" / "panel.ts"
    assert "SHOULD BE DONE BY AYKHAN" in panel.read_text(encoding="utf-8")
    # No other source file builds the dock's DOM.
    src = pathlib.Path(__file__).resolve().parents[2] / "extension" / "src"
    for path in src.rglob("*.ts"):
        if path.parent.name == "panel" or path.parent.name == "content":
            continue
        assert "createElement" not in path.read_text(encoding="utf-8"), path
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/portals/test_extension_bundle.py -k panel -v`
Expected: FAIL — the file does not exist.

- [ ] **Step 3: Write `extension/src/panel/panel.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Tehsil co-pilot</title>
  </head>
  <body>
    <!-- SHOULD BE DONE BY AYKHAN: this markup is a functional placeholder.
         Every element the dock needs is present and named; the design is his. -->
    <main id="dock">
      <p id="status"></p>
      <p id="message"></p>
      <section><h2>Filled</h2><ul id="filled"></ul></section>
      <section><h2>Your turn</h2><ul id="your-turn"></ul></section>
      <section><h2>Check these</h2><ul id="mismatches"></ul></section>
    </main>
    <script src="panel.js"></script>
  </body>
</html>
```

- [ ] **Step 4: Write `extension/src/panel/panel.ts`**

```ts
/**
 * SHOULD BE DONE BY AYKHAN.
 *
 * The dock's ONLY DOM owner. Everything else in this extension produces state;
 * this file is the one place that turns state into a screen, so the visual
 * design is a rewrite of `render` and of panel.html and touches nothing else.
 *
 * What is here is deliberately unstyled and complete: every field of DockState
 * reaches the screen, because a placeholder that hides state is a placeholder
 * that makes the real design miss a case.
 */
import type { DockState } from "../types.js";

const EMPTY: DockState = {
  applicationId: null,
  status: "idle",
  filled: [],
  yourTurn: [],
  mismatches: [],
  message: "",
};

let state: DockState = EMPTY;

function list(id: string, items: string[]): void {
  const node = document.getElementById(id);
  if (!node) return;
  node.replaceChildren(
    ...items.map((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      return item;
    }),
  );
}

export function render(next: DockState): void {
  state = next;
  const status = document.getElementById("status");
  if (status) status.textContent = state.status;
  const message = document.getElementById("message");
  if (message) message.textContent = state.message;
  list("filled", state.filled);
  list(
    "your-turn",
    state.yourTurn.map((row) => `${row.label} — ${row.reason}`),
  );
  list(
    "mismatches",
    // The student's own values are on their own screen here, which is the one
    // place in this extension that is correct: it is their form.
    state.mismatches.map((row) => `${row.label}: expected ${row.expected}, page holds ${row.actual}`),
  );
}

chrome.runtime.onMessage.addListener((incoming) => {
  if (incoming?.type === "dock:state") render({ ...state, ...incoming.state });
  return false;
});

chrome.runtime.sendMessage({ type: "dock:hello" }).catch(() => {});
render(EMPTY);
```

- [ ] **Step 5: Route dock patches through the worker**

Add to the worker's listener:

```ts
  if (message?.type === "dock") {
    // The worker holds the dock's state so a reopened panel is not blank.
    void (async () => {
      const stored = await chrome.storage.session.get("dock");
      const next = { ...(stored["dock"] ?? {}), ...message.patch };
      await chrome.storage.session.set({ dock: next });
      chrome.runtime.sendMessage({ type: "dock:state", state: next }).catch(() => {});
      sendResponse({ ok: true });
    })();
    return true;
  }
  if (message?.type === "dock:hello") {
    void (async () => {
      const stored = await chrome.storage.session.get("dock");
      chrome.runtime.sendMessage({ type: "dock:state", state: stored["dock"] ?? {} }).catch(() => {});
    })();
    return false;
  }
```

- [ ] **Step 6: Give the student a way to unpair**

`DELETE /ext/pair` exists and nothing calls it yet. Revocation that only the server can
perform is not revocation the student has. Add to `panel.html`, inside `<main>`:

```html
      <button id="unpair" type="button">Disconnect this browser</button>
```

and to `panel.ts`:

```ts
// The one button in this extension, and it only ever removes something. It is
// not a page control: dispatching a click is forbidden in the content script,
// while a button the STUDENT presses in our own side panel is the opposite
// thing -- their act, on their own installation.
document.getElementById("unpair")?.addEventListener("click", () => {
  void chrome.runtime.sendMessage({ type: "unpair" });
});
```

and to the worker's listener:

```ts
  if (message?.type === "unpair") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (origin) await revoke(origin);
      await chrome.storage.session.clear();
      chrome.runtime.sendMessage({ type: "dock:state", state: { status: "idle", message: "Disconnected." } }).catch(() => {});
    })();
    return false;
  }
```

`revoke` already clears the local token even when the server call fails — a token we keep
after the student asked us to forget it is the worst of both outcomes.

Note for `test_no_code_path_clicks`: that scan bans `.click(` in `content.js` and
`service_worker.js`. `panel.js` is a third bundle and is **not** scanned, because the dock
is our own UI — `addEventListener("click", …)` here is listening, not dispatching, and it
is the student pressing it. Do not add `panel.js` to that test's list, and do not move the
unpair handler into either scanned bundle.

- [ ] **Step 7: Build, run, commit**

```bash
npm --prefix extension run check && uv run pytest tests/portals -q
git add extension/src/panel extension/src/service_worker.ts tests/portals/test_extension_bundle.py
git commit -m "feat(extension): a dock that shows every state, with its design left to Aykhan"
```

---

### Task 13: End to end, against a real Chromium

**Files:**
- Create: `tests/portals/test_extension_e2e.py`, `tests/portals/fixtures/plain_form.html`, `tests/portals/fixtures/mislabelled_form.html`, `tests/portals/fixtures/hidden_field_form.html`, `tests/portals/fixtures/challenge.html`
- Modify: `.github/workflows/ci.yml`
- Test: itself

**Interfaces:**
- Consumes: the built `extension/dist/`, `patchright`.
- Produces: the `extension` marker's tests.

**The negative controls are the point.** A suite that only proves a good map fills a good form proves nothing about the check task 6 exists for. Three of the four fixtures are pages where filling must **not** happen.

- [ ] **Step 1: Write the fixtures**

`tests/portals/fixtures/plain_form.html`:

```html
<!doctype html><html><body><form>
  <label for="gn">Given name</label><input id="gn" name="given_name">
  <label for="fn">Family name</label><input id="fn" name="family_name">
  <label for="em">Email address</label><input id="em" name="email" type="email">
  <button type="submit">Submit application</button>
</form></body></html>
```

`tests/portals/fixtures/mislabelled_form.html` — the selector resolves, the control is real, and it asks for something else entirely. This is the hostile-snapshot case:

```html
<!doctype html><html><body><form>
  <label for="gn">Passport number</label><input id="gn" name="given_name">
  <label for="fn">Family name</label><input id="fn" name="family_name">
</form></body></html>
```

`tests/portals/fixtures/hidden_field_form.html`:

```html
<!doctype html><html><body><form>
  <label for="gn">Given name</label><input id="gn" name="given_name" style="display:none">
  <label for="fn">Family name</label><input id="fn" name="family_name" disabled>
</form></body></html>
```

`tests/portals/fixtures/challenge.html`:

```html
<!doctype html><html><body>
  <div class="g-recaptcha" data-sitekey="test"></div>
  <form><label for="gn">Given name</label><input id="gn" name="given_name"></form>
</body></html>
```

- [ ] **Step 2: Write the failing test**

`tests/portals/test_extension_e2e.py`:

```python
"""The extension, driven by a real Chromium against fixture portal pages.

Skipped locally when the bundle or the browser is absent; FAILS under CI for a
missing bundle, for the reason test_extension_bundle.py gives.

Synchronous patchright API on purpose -- no pytest-asyncio dependency, and the
same shape tests/portals/test_engine_browser.py already uses.
"""

import json
import os
import pathlib
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
DIST = pathlib.Path(__file__).resolve().parents[2] / "extension" / "dist"


@pytest.fixture
def fixture_server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(FIXTURES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def browser_context(tmp_path):
    if not (DIST / "manifest.json").exists():
        message = "extension/dist is missing -- npm --prefix extension ci && npm --prefix extension run build"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("patchright is not installed")

    with sync_playwright() as playwright:
        # An ordinary headless browser, NOT --load-extension. Every test below
        # injects content.js itself, so loading the packed extension would buy
        # nothing and cost a headed browser (extensions do not load in old
        # headless) plus an X server on the CI runner. The limitation that
        # creates is stated at the end of task 13 and must stay stated.
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        yield context
        context.close()
        browser.close()


def _verify_in_page(page, entries):
    """Run the bundle's verification against this page and return its verdicts.

    The bundle is injected as a plain script and the check is called directly:
    the pairing and packet round-trips are covered by tests/portals/
    test_ext_api.py, and mixing them in here would make a failure ambiguous.
    """
    page.add_script_tag(path=str(DIST / "content.js"))
    return page.evaluate("(entries) => window.__tehsil_verify(entries)", entries)


@pytest.mark.extension
def test_a_plain_form_fills(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    verdicts = _verify_in_page(
        page,
        [
            {"selector": "#gn", "method": "fill", "value": "Leyla", "profile_field": "personal.given_name"},
            {"selector": "#fn", "method": "fill", "value": "Aliyeva", "profile_field": "personal.family_name"},
        ],
    )
    assert [item["ok"] for item in verdicts] == [True, True]


@pytest.mark.extension
def test_a_mislabelled_control_is_refused_not_typed_into(browser_context, fixture_server) -> None:
    """The hostile-snapshot case, and the one no server-side check can catch.

    #gn exists, is visible and is enabled. It asks for a passport number. A map
    aiming the given name at it is exactly what a crafted snapshot produces,
    and read-back would verify it clean.
    """
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/mislabelled_form.html")
    verdicts = _verify_in_page(
        page,
        [{"selector": "#gn", "method": "fill", "value": "Leyla", "profile_field": "personal.given_name"}],
    )
    assert verdicts[0]["ok"] is False
    assert verdicts[0]["reason"] == "name_mismatch"
    assert page.input_value("#gn") == ""


@pytest.mark.extension
def test_a_hidden_or_disabled_control_is_refused(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hidden_field_form.html")
    verdicts = _verify_in_page(
        page,
        [
            {"selector": "#gn", "method": "fill", "value": "Leyla", "profile_field": "personal.given_name"},
            {"selector": "#fn", "method": "fill", "value": "Aliyeva", "profile_field": "personal.family_name"},
        ],
    )
    assert [item["reason"] for item in verdicts] == ["hidden", "disabled"]


@pytest.mark.extension
def test_a_missing_selector_is_refused(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    verdicts = _verify_in_page(
        page,
        [{"selector": "#nope", "method": "fill", "value": "Leyla", "profile_field": "personal.given_name"}],
    )
    assert verdicts[0]["reason"] == "no_such_control"


@pytest.mark.extension
def test_a_challenge_page_is_detected(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/challenge.html")
    page.add_script_tag(path=str(DIST / "content.js"))
    assert page.evaluate("() => window.__tehsil_detect_challenge()")["kind"] == "recaptcha"


@pytest.mark.extension
def test_a_snapshot_of_a_filled_form_carries_no_value(browser_context, fixture_server) -> None:
    """The definitive form of "the snapshot carries no value".

    The page is filled first, so every control HAS a value to leak. A key-level
    assertion on the built snapshot cannot be fooled by a rename, where a text
    scan of the bundle both misses renames and trips over the legitimate
    element.value reads in fill and read-back.
    """
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.fill("#gn", "Leyla")
    page.fill("#em", "leyla@example.org")
    page.add_script_tag(path=str(DIST / "content.js"))
    snapshot = page.evaluate("() => window.__tehsil_snapshot()")

    assert snapshot["controls"], "the snapshot found no controls"
    for control in snapshot["controls"]:
        assert "value" not in control, control
    assert "Leyla" not in json.dumps(snapshot)
    assert "leyla@example.org" not in json.dumps(snapshot)


@pytest.mark.extension
def test_nothing_the_extension_does_submits_the_form(browser_context, fixture_server) -> None:
    """The spec's hardest guarantee, measured rather than scanned.

    The page records any submit; a full verify-and-fill must leave it unset.
    """
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    page.evaluate("() => { window.__submitted = false; document.forms[0].addEventListener('submit', () => { window.__submitted = true; }); }")
    page.add_script_tag(path=str(DIST / "content.js"))
    page.evaluate(
        "(entries) => window.__tehsil_fill(window.__tehsil_verify(entries))",
        [{"selector": "#gn", "method": "fill", "value": "Leyla", "profile_field": "personal.given_name"}],
    )
    assert page.input_value("#gn") == "Leyla"
    assert page.evaluate("() => window.__submitted") is False
```

- [ ] **Step 3: Expose the three test hooks**

At the bottom of `extension/src/content/index.ts`:

Add `import type { VerifiedEntry } from "./verify.js";` and `import type { PacketField } from "../types.js";` to the file's imports, then append:

```ts
// Test hooks. The e2e suite drives the real bundle rather than a re-
// implementation of it, and these are the smallest surface that allows that.
// They read the page and return verdicts; none of them reaches the network,
// holds a credential, or is reachable from a portal page's own script when the
// extension injects this file itself (the content script runs in an isolated
// world, so `globalThis` there is not the page's `window`).
// A VerifiedEntry carries an HTMLElement, which page.evaluate cannot return --
// it serializes to nothing and the assertion reads a silent {}. The hook
// projects each verdict to the three fields the tests assert on instead.
(globalThis as Record<string, unknown>)["__tehsil_verify"] = (entries: PacketField[]) =>
  verifyEntries(entries).map((item: VerifiedEntry) => ({
    profile_field: item.entry.profile_field,
    ok: item.ok,
    reason: item.reason,
  }));
(globalThis as Record<string, unknown>)["__tehsil_fill"] = (entries: PacketField[]) =>
  fillVerified(verifyEntries(entries), new Set());
(globalThis as Record<string, unknown>)["__tehsil_detect_challenge"] = detectChallenge;
(globalThis as Record<string, unknown>)["__tehsil_snapshot"] = () => buildSnapshot(document);
```

**Note for the executor, and a limit worth knowing:** `page.add_script_tag` injects into
the page's *main* world, so these hooks are reachable from the test. The e2e suite
therefore exercises everything that touches the page — verification, fill, read-back,
snapshot, challenge detection — but **not** the extension's own injection, permission
grant or pairing round-trip, which need an HTTPS host the extension has permission for.
Those are covered on the server side by `tests/portals/test_ext_api.py` and are the part
of this extension that is first exercised for real by a human installing it. Say so when
handing over; do not let the green suite imply otherwise.

- [ ] **Step 4: Run it**

Run:
```bash
npm --prefix extension run build
uv run pytest tests/portals/test_extension_e2e.py -m extension -v
```
Expected: PASS, seven tests. If Chromium is missing: `uv run patchright install chromium`.

- [ ] **Step 5: Add the e2e step to the CI job**

Append to the `extension` job in `.github/workflows/ci.yml`:

```yaml
      - run: uv run patchright install --with-deps chromium
      - run: uv run pytest tests/portals/test_extension_e2e.py -m extension -q
```

- [ ] **Step 6: Commit**

```bash
git add tests/portals/test_extension_e2e.py tests/portals/fixtures \
        extension/src/content/index.ts .github/workflows/ci.yml
git commit -m "test(extension): three pages where filling must not happen, and one where it must"
```

---

## Verification before completion

- [ ] `npm --prefix extension run typecheck` — clean.
- [ ] `npm --prefix extension run build` — clean.
- [ ] `uv run ruff check` — clean.
- [ ] `uv run mypy apps config` — clean.
- [ ] `uv run bandit -c pyproject.toml -r apps config` — clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` — no pending migration (task 2 changes a Pydantic model, not a Django one; a migration here means something else was touched).
- [ ] `uv run pytest -q` — the whole suite, with a per-worktree database: `POSTGRES_DB=tehsil_glassbox uv run pytest -q`.
- [ ] `uv run pytest tests/portals/test_extension_e2e.py -m extension -q` — the browser suite.
- [ ] `git diff master --stat` — confirm the Python surface is `apps/portals/packets.py` plus tests, and nothing else.

## What this plan does not build

- **Firefox and Safari.** Owner decision 12: later, on a measured trigger.
- **Web Store publishing.** `npm run package` produces the zip; publishing is a manual act under the two-person rule the spec asks for. No release automation.
- **eslint/prettier.** `tsc --noEmit` is the gate. Add a formatter when a second author is writing TypeScript here.
- **A JS unit-test runner.** `already_correct` and `read_back` keep their Python twins; everything else is exercised against a real page in task 13.
- **Deleting the retired server tier.** `auth.py`, `profiles.py`, `engine.py`, `resolve.py`, `dispatch.py`, the EC2 portal tier and `PortalTaskRole` stay dormant at `PortalDesiredCount: 0` until the separate deletion plan runs. Open decision 3 in the spec gates that, not this.

## Follow-ups this plan creates

- ~~**`PortalForm.confirmation_markers` does not exist.**~~ **Closed 2026-09-23** (`fe0d8c4`).
  The column is a nullable `JSONField` and `mint_packet` sends it. NULL, not `[]`, for an
  unconfigured portal: the extension reads null as "this check is off", while `[]` reads as
  "these are the markers and none matched" — the same answer an unsubmitted page gives, so
  an unconfigured portal would be indistinguishable from a student who never pressed Submit.
- **Publishing needs the two-person rule.** The spec names a compromised Web Store account
  as the supply-chain risk this design newly carries. `npm run package` produces the zip;
  who may upload it is a decision this plan does not take.
- **`min_extension_version` is edited by hand in two files.** `test_the_manifest_version_is_at_least_the_packet_floor` catches the dangerous direction (a shipped build below the floor). It cannot tell anyone to raise the floor when packet semantics change — that stays a human judgement at release.
- **Nothing sends `{type:"start"}` or injects `content.js` into a portal tab.** Still open, and
  **2026-09-23 established what it is actually blocked on: there is no dashboard.** `templates/` does
  not exist in this repository — the presentation layer is deliberately unbuilt (CLAUDE.md,
  "Frontend and design"), so the spec's `[Launch & Autofill TUM]` button has no page to live on, and
  `pairFromTab` has no pairing screen to read a code from either. The extension is therefore
  unreachable by a real student for a reason that is not the extension's. Building a
  `chrome.action.onClicked` launch path now would be speculative: it could not be exercised by
  anyone, and the e2e harness cannot test it either (it never loads the packed extension — see the
  end of task 13). Both halves — the toolbar launch and a server route that answers "which of this
  student's applications is this page?" — wait for the dashboard.

- **CI has not run on this branch since it was opened.** Measured 2026-09-23: every job of every
  workflow on every branch of this repository, master included, fails in two seconds with zero steps
  executed and no retrievable log. That is an account-level GitHub Actions condition (billing or
  minutes), not this branch. PR #101 reads as entirely red and is not: run locally on 2026-09-23 at
  `8464cc0` it was `npm run typecheck` clean, `npm run build` clean, 263 portals tests passing,
  9 `-m extension` browser tests passing, `ruff`/`mypy`/`bandit` clean and no pending migration.
- ~~**The origin check runs after the first packet fetch, not before.**~~ **Closed 2026-09-23**
  (`dcc642f`), and it was eleven lines rather than the larger change this entry predicted. The 424
  `no_field_map` response names the page, `ExtError` carries a refusal's body so the worker can pass
  it on, and `run()` checks the origin before `buildSnapshot`. An absent `form_url` refuses too — a
  server too old to name the page cannot say what we are looking at. `run()` is now reachable from
  the e2e suite through `__tehsil_run` with `chrome.runtime.sendMessage` stubbed, so three tests
  assert on the messages a real run sent, including the positive control.

## Risks this plan carries into production

- **The token table is the verification check's ceiling.** A portal whose labels are in a language `vocabulary.ts` does not cover matches nothing, refuses every field, and the student falls back to the Application Kit. Safe direction, real cost. Measure it on the first ten real portals before touching the rule; the fix is tokens, not a softer check.
- **`name_mismatch` and a genuinely odd label are indistinguishable.** A portal that labels its given-name field "Applicant identifier 1" is refused exactly like a hostile map. The dock names the field and the student types it.
- **Custom upload widgets** expose no file input; `attachDocuments` returns them as `manual` and the dock says where the file is. The spec's Risks section chose this.
- **A page that rewrites the DOM after the fill** (a wizard step, a framework re-render) can revert a typed value after read-back has passed. Read-back runs once, at the end of the run; a student who presses Next and comes back re-runs the whole thing.
