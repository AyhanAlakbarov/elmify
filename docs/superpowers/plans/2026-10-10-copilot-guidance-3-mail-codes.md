# Co-pilot plan 3: the portal's verification email, handled for the student — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a portal sends a verification code or link to the student's email, the co-pilot reads it from their connected inbox while they are still at the portal. It types the code into the portal's code box, or opens the link in a new tab, and the panel says so. If no mail comes within ten minutes, or the inbox is not connected, the panel asks the student to do it themselves.

**Architecture:** The server half already exists and is not changed:
- the mailbox sync classifies a portal's mail as `VERIFICATION`;
- `apps/mailbox/actions.py::apply_verdict` validates the code (alphanumeric, at most 12 characters) or the link (https, no userinfo, a host the pack names);
- it queues a `TYPE_CODE` or `OPEN_VERIFICATION_URL` `DeviceAction` tied to the application.

What is missing is the extension's half. Today it polls actions only when the student visits the dashboard, and it only *shows* `TYPE_CODE`. This plan adds three things:
- a **code watch**: a 30-second Chrome alarm per application, started when the page asks for a code or a sign-up was just typed. It asks the mailbox to sync, then polls actions until a code or link arrives or ten minutes pass;
- **delivery** of `TYPE_CODE` into the bound tab, over a `type-code` message, into a code box found by `autocomplete="one-time-code"` or a single box named for a code;
- the **panel fallback** that shows the code when it cannot be typed.

**Tech Stack:** Chrome MV3 extension in TypeScript (esbuild), pytest + Playwright e2e against a stubbed `chrome`.

**Spec:** `docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md` §6 ("Mail the portal sends is handled for the student"), §10 ("Email verification code or link"), §8.

**Depends on:** plan 2 (`2026-10-10-copilot-guidance-2-portal-accounts.md`), executed first on the same branch. Its `signIn` (content/index.ts) is where Task 1 starts the watch after a sign-up.

## Global Constraints

- From the spec:
  - "the platform reads that mail from the student's connected inbox (only mail from that portal's sender, as the mailbox connection is already scoped) and the co-pilot types the code into the portal, or opens the verification link in the student's own browser";
  - "The panel says what happened";
  - "If no mail arrives within a few minutes, or the inbox is not connected, the panel asks the student to type the code themselves."
- **Never clicks (§8).** The co-pilot types the code; the student presses the portal's Confirm or Verify button. A link opens in a **new, inactive tab**. The tab the student stands on is never navigated (the existing `answerActions` rule).
- **Where a code may be typed.** Only into the active binding whose `applicationId` equals the action's `application_id`, only while that tab's URL is on `binding.origin`, and only in the top frame (`frameId: 0`). The content script re-checks the origin it is told against `location.origin`. A code whose action has no application is shown in the panel, never typed.
- **What a code is.** The same rule the server applies (`apps/mailbox/actions.py::_MAX_CODE_LENGTH` = 12, `isalnum`): `/^[A-Za-z0-9]{1,12}$/`. Checked again in the worker and in the content script. A code failing it is never sent anywhere.
- **What the panel may show.** The code appears in the panel only when typing failed. The panel is the extension's own page, which a portal cannot read. The code lives in `storage.session` `dock.code` and is cleared on the next Start and on the next watch.
- **Mailbox sync budget.** `apps/mailbox/sync.py::SYNC_LIMIT` is 6 on-demand syncs per student per hour. One watch spends at most 3: at start, at 2 minutes and at 5 minutes. A second ask while a watch runs extends it and spends none.
- **Alarm period.** `periodInMinutes: 0.5`. Chrome 120+ honours 30 seconds. The manifest floor is 116, and 116–119 round it to 1 minute, which is slower but correct.
- **No server change.** If a task finds it needs one, stop and report it: the server half is reviewed and merged (student-mailbox plan, PR #178).
- CI gates as in plan 2: `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test`, then `POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py tests/portals/test_extension_bundle.py -q`. Every git command uses `git -C /home/orkhan/Desktop/copilot-guidance`.

## Review Focus

1. **The code arrives after the student left the code page**, for example they reloaded or went back. Typing then fails: no single code box. The panel shows the code. Pinned in Task 2: "no box" means `code_shown` and the code in `dock.code`.
2. **A six-box split code input** (one digit per box). Typing it is out of scope. All the boxes carry `one-time-code`, or none does, so no single box qualifies and the panel shows the code. Pinned in Task 1.
3. **The tab moved to another site before the code came.** Nothing is sent to it. Pinned in Task 2.
4. **The inbox is not connected or needs reconnecting.** The answer is at once "type it yourself", with no ten-minute wait. Pinned in Task 2 (`queued: 0`, and 409 `mailbox_disconnected`).
5. **A hostile page asking the worker to start a watch for another application.** It is refused by `contentRefusal`'s binding check, the same as every content message. Pinned in Task 2.

---

## File structure

| File | Responsibility |
|---|---|
| `extension/src/content/code.ts` (create) | Find the single code box; type a checked code into it. |
| `extension/src/content/index.ts` | The code-page branch of `run()`, the `await-code` ask after a sign-up, the `type-code` listener. |
| `extension/src/api.ts` | `checkMailbox` returns `{queued}`. |
| `extension/src/types.ts` | `DockState.code`. |
| `extension/src/service_worker.ts` | The watch (start, alarm, end), `TYPE_CODE` delivery, the link message. |
| `extension/src/panel/panel.html`, `panel.ts`, `i18n.ts` | The code fallback section and five messages in four languages. |
| `tests/portals/fixtures/code_page.html`, `code_named.html`, `code_split.html` | Pages to find a code box on. |

---

### Task 1: The code box on the page

**Files:**
- Create: `extension/src/content/code.ts`
- Modify: `extension/src/content/index.ts`:
  - the code-page branch in `run()`, inside plan 2's `if (!onFormPage(...))` block, after the credential branch;
  - one `await-code` ask at the end of plan 2's `signIn` for a sign-up;
  - the `type-code` case in the `chrome.runtime.onMessage` listener;
  - one test hook.
- Create: `tests/portals/fixtures/code_page.html`, `code_named.html`, `code_split.html`
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Consumes:
  - `fillVerified` (`content/fill.ts`), `visible` (`content/verify.ts`), `accessibleName` (`content/snapshot.ts`);
  - plan 2's `onFormPage`, `credentialPage` and `signIn`.
- Produces:
  - `codeField(): HTMLInputElement | null`;
  - `typeCode(code: string, origin: string): boolean`;
  - the content→worker message `{type: "await-code", applicationId}`;
  - the worker→content message `{type: "type-code", code, origin}`, answered `{typed: boolean}`;
  - the dock message `waiting_code`.

- [ ] **Step 1: Write the fixtures**

`tests/portals/fixtures/code_page.html`:

```html
<!doctype html>
<html>
<body>
<p>We sent a code to your email.</p>
<form>
  <label for="otp">Code</label><input id="otp" type="text" autocomplete="one-time-code" inputmode="numeric">
  <button type="submit">Verify</button>
</form>
</body>
</html>
```

`tests/portals/fixtures/code_named.html`:

```html
<!doctype html>
<html>
<body>
<form>
  <label for="vc">Verification code</label><input id="vc" type="text">
  <button type="submit">Confirm</button>
</form>
</body>
</html>
```

`tests/portals/fixtures/code_split.html`:

```html
<!doctype html>
<html>
<body>
<form>
  <input type="text" maxlength="1" autocomplete="one-time-code" aria-label="Digit 1">
  <input type="text" maxlength="1" autocomplete="one-time-code" aria-label="Digit 2">
  <input type="text" maxlength="1" autocomplete="one-time-code" aria-label="Digit 3">
  <input type="text" maxlength="1" autocomplete="one-time-code" aria-label="Digit 4">
  <input type="text" maxlength="1" autocomplete="one-time-code" aria-label="Digit 5">
  <input type="text" maxlength="1" autocomplete="one-time-code" aria-label="Digit 6">
</form>
</body>
</html>
```

- [ ] **Step 2: Write the failing e2e tests**

```python
def _type_code(page, code, origin):
    return page.evaluate(
        """([code, origin]) => new Promise((resolve) => {
            const keep = window.__listeners[0]({ type: "type-code", code, origin }, {}, resolve);
            if (!keep) resolve(undefined);
        })""",
        [code, origin],
    )


@pytest.mark.extension
@pytest.mark.parametrize(("fixture", "box"), [("code_page.html", "#otp"), ("code_named.html", "#vc")])
def test_a_code_page_asks_for_the_mail_and_takes_the_code(
    browser_context, fixture_server, fixture, box
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/{fixture}")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    page.evaluate("() => { window.__submitted = false; document.querySelector('form').addEventListener('submit', (e) => { window.__submitted = true; e.preventDefault(); }); }")

    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'await-code')")
    sent = page.evaluate("() => window.__sent")
    assert {"type": "await-code", "applicationId": "app-1"} in sent
    assert {"message": "waiting_code"} in [m["patch"] for m in sent if m["type"] == "dock"]

    assert _type_code(page, "482913", fixture_server) == {"typed": True}
    assert page.input_value(box) == "482913"
    assert page.evaluate("() => window.__submitted") is False


@pytest.mark.extension
def test_a_split_code_input_is_left_to_the_student(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/code_split.html")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    assert _type_code(page, "482913", fixture_server) == {"typed": False}
    assert page.evaluate("() => [...document.querySelectorAll('input')].every((i) => i.value === '')")


@pytest.mark.extension
@pytest.mark.parametrize(
    ("code", "origin_of"),
    [("482913", "other"), ("48 29", "self"), ("<b>1</b>", "self"), ("1234567890123", "self"), ("", "self")],
)
def test_a_code_from_elsewhere_or_not_a_code_is_never_typed(
    browser_context, fixture_server, code, origin_of
) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/code_page.html")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    origin = fixture_server if origin_of == "self" else "https://evil.example"
    assert _type_code(page, code, origin) == {"typed": False}
    assert page.input_value("#otp") == ""


@pytest.mark.extension
def test_a_code_never_types_over_what_the_student_typed(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/code_page.html")
    page.fill("#otp", "111111")
    _content_with_listener(page, {"packet": _plain_packet(fixture_server)})
    assert _type_code(page, "482913", fixture_server) == {"typed": False}
    assert page.input_value("#otp") == "111111"


@pytest.mark.extension
def test_a_sign_up_starts_watching_for_the_portal_s_mail(browser_context, fixture_server) -> None:
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/signup.html")
    _content_with_listener(
        page, {"packet": _plain_packet(fixture_server), "portal-login": {"ok": True, **LOGIN_REPLY}}
    )
    _deliver(page, _start("en", fixture_server))
    page.wait_for_function("() => window.__sent.some((m) => m.type === 'await-code')")
```

`LOGIN_REPLY` and `signup.html` come from plan 2. The listener in `_content_with_listener` is captured into `window.__listeners`. Its third argument is the `sendResponse` this plan's `type-code` case calls.

- [ ] **Step 3: Build and run them to verify they fail**

Run: `npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py -q -k "code"`
Expected: FAIL. No `await-code` is ever sent, and `type-code` gets no answer.

- [ ] **Step 4: Write `extension/src/content/code.ts`**

```ts
/**
 * The portal's "enter the code we emailed you" box (spec 2026-10-09 §6, §10).
 *
 * One box only. `autocomplete="one-time-code"` is the standard way a page names
 * it; without that, a single text box whose own name says code, on a page with
 * at most two text boxes, is one. A split input -- a box per digit -- is never
 * a single box, so the student types it from the panel.
 *
 * ponytail: split inputs are left to the student. Type one character per box
 * when a measured portal uses one.
 */
import { fillVerified } from "./fill.js";
import { accessibleName } from "./snapshot.js";
import { visible } from "./verify.js";

/** The server's own rule (apps/mailbox/actions.py: isalnum, at most 12). */
export const CODE_RE = /^[A-Za-z0-9]{1,12}$/;

const BOXES = 'input:not([type]), input[type="text"], input[type="tel"], input[type="number"]';
const CODE_WORDS = /code|otp|one.?time|verif|token|kod|код|doğrula|bestätig/i;

export function codeField(): HTMLInputElement | null {
  const boxes = Array.from(document.querySelectorAll<HTMLInputElement>(BOXES)).filter(
    (box) => visible(box) && !box.disabled && !box.readOnly,
  );
  const marked = boxes.filter((box) => box.autocomplete === "one-time-code");
  if (marked.length > 0) return marked.length === 1 ? marked[0]! : null;
  if (boxes.length > 2) return null;
  const named = boxes.filter((box) =>
    CODE_WORDS.test(`${accessibleName(box)} ${box.name} ${box.id} ${box.placeholder}`),
  );
  return named.length === 1 ? named[0]! : null;
}

/** Type a checked code into the page's one code box. Never presses anything. */
export function typeCode(code: string, origin: string): boolean {
  if (origin !== location.origin || window.top !== window || !CODE_RE.test(code)) return false;
  const box = codeField();
  if (!box) return false;
  const item = {
    entry: { selector: "", method: "fill", value: code, profile_field: "portal.verification_code" },
    element: box,
    ok: true,
    reason: "",
  };
  return fillVerified([item], new Set()).filled.length === 1;
}
```

- [ ] **Step 5: Wire it into `index.ts`.** Import `codeField` and `typeCode` from `./code.js`.

In `run()`, inside plan 2's `if (!onFormPage(packet.entries)) { … }` block, after the credential branch and before the password-only fallback:

```ts
    if (codeField()) {
      // The portal sent a code by email: the worker watches the inbox for it
      // and types it here when it comes (spec §6). Nothing to fill meanwhile.
      await ask({ type: "await-code", applicationId });
      await dock({ message: "waiting_code" });
      return;
    }
```

At the end of plan 2's `signIn`, before its final `dock(...)`:

```ts
  // A new account's portal mails a code or a link once Register is pressed.
  if (page.kind === "signup") await ask({ type: "await-code", applicationId });
```

In the `chrome.runtime.onMessage` listener, take `sendResponse` as the third argument and add, before `return false`:

```ts
    if (message?.type === "type-code") {
      // Answered synchronously: typeCode does no waiting.
      sendResponse({ typed: typeCode(String(message.code ?? ""), String(message.origin ?? "")) });
    }
```

Test hook, beside `__elmify_use_plain`: `(globalThis as Record<string, unknown>)["__elmify_code_field"] = () => codeField()?.id ?? null;`

- [ ] **Step 6: Typecheck, build, run the extension suite**

Run: `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py tests/portals/test_extension_bundle.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add extension/src/content/code.ts extension/src/content/index.ts tests/portals/fixtures/code_page.html tests/portals/fixtures/code_named.html tests/portals/fixtures/code_split.html tests/portals/test_extension_e2e.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(extension): a portal's code page asks the worker to watch the inbox, and takes the code into its one code box"
```

---

### Task 2: The watch, and delivering what the mail said

**Files:**
- Modify: `extension/src/api.ts` (`checkMailbox` returns `{ queued: number }`)
- Modify: `extension/src/types.ts` (`DockState.code`)
- Modify: `extension/src/service_worker.ts`:
  - `CONTENT_TYPES`;
  - the `handle` case for `await-code`;
  - the watch helpers;
  - `chrome.alarms.onAlarm`;
  - `answerActions`;
  - `startFill`'s `patchDock`.
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Consumes: Task 1's `await-code` and `type-code` messages; `pollActions`, `onOrigin`, `bindings`, `patchDock`, `postActionResult`, `dashboardOrigin`, `ExtError` (all existing in `service_worker.ts` / `api.ts`).
- Produces:
  - `storage.session` key `codeWatch: Record<applicationId, { until: number; ticks: number }>`;
  - the alarm name prefix `code-watch:`;
  - the dock messages `code_typed`, `code_shown`, `link_opened` and `type_code_yourself`, plus `dock.code`;
  - action results posted with `detail: { typed: boolean }` for `TYPE_CODE`.

- [ ] **Step 1: Write the failing e2e tests**

```python
CODE_ACTION = {
    "id": ACTION_ID,
    "kind": "TYPE_CODE",
    "application_id": APP_A,
    "payload": {"code": "482913"},
    "expires_at": "2099-01-01T00:00:00Z",
}


def _watching(page):
    return page.evaluate("() => window.__session.codeWatch ?? {}")


def _tick(page):
    page.evaluate(
        "(id) => Promise.all(window.__on.alarm.map((fn) => fn({ name: `code-watch:${id}` })))", APP_A
    )


def _typing_tab(page, typed):
    page.evaluate(
        """(typed) => { chrome.tabs.sendMessage = async (...args) => {
            window.__calls.push(["tabs.sendMessage", args]); return { typed }; }; }""",
        typed,
    )


def _code_worker(
    browser_context, actions, *, check=(202, {"queued": 1}), tab_url=f"{PORTAL}/verify",
    watch=None, binding_app=APP_A,
):
    session = _binding()
    session["bindings"]["7"]["applicationId"] = binding_app
    if watch:
        session["codeWatch"] = watch
    return _load_worker(
        browser_context,
        {"binding": {"tabId": 7, "origin": PORTAL}},
        {
            "POST /ext/mailbox/check": list(check),
            "GET /ext/actions": [200, {"actions": actions}],
            f"POST /ext/actions/{ACTION_ID}/result": [200, {"completed": True}],
        },
        session=session,
        tabs={7: {"id": 7, "url": tab_url}},
    )


@pytest.mark.extension
def test_a_code_from_the_inbox_is_typed_into_its_own_tab(browser_context) -> None:
    page = _code_worker(browser_context, [CODE_ACTION])
    _typing_tab(page, True)

    assert _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT) == {"ok": True}
    assert APP_A in _watching(page)
    _tick(page)

    assert _calls(page, "tabs.sendMessage") == [
        [7, {"type": "type-code", "code": "482913", "origin": PORTAL}, {"frameId": 0}]
    ]
    dock = page.evaluate("() => window.__session.dock")
    assert dock["message"] == "code_typed" and dock.get("code") is None
    results = [body for key, body in page.evaluate("() => window.__fetched") if key.endswith("/result")]
    assert results == [{"ok": True, "detail": {"typed": True}}]
    assert _watching(page) == {}


@pytest.mark.extension
@pytest.mark.parametrize(
    ("typed", "tab_url", "binding_app"),
    [
        (False, f"{PORTAL}/verify", APP_A),  # the page has no single code box any more
        (True, "https://elsewhere.example/x", APP_A),  # the tab left the portal
        (True, f"{PORTAL}/verify", APP_B),  # no tab bound to this application
    ],
)
def test_a_code_that_cannot_be_typed_is_shown_in_the_panel(
    browser_context, typed, tab_url, binding_app
) -> None:
    page = _code_worker(browser_context, [CODE_ACTION], tab_url=tab_url, binding_app=binding_app)
    _typing_tab(page, typed)

    _page_loaded(page, 9, "https://dash.example/student/")  # a dashboard load polls actions

    dock = page.evaluate("() => window.__session.dock")
    assert dock["message"] == "code_shown" and dock["code"] == "482913"
    if tab_url.startswith("https://elsewhere") or binding_app == APP_B:
        assert _calls(page, "tabs.sendMessage") == []
    results = [body for key, body in page.evaluate("() => window.__fetched") if key.endswith("/result")]
    assert results == [{"ok": True, "detail": {"typed": False}}]


@pytest.mark.extension
@pytest.mark.parametrize("code", ["48 29", "<b>1</b>", "1234567890123", 482913])
def test_a_payload_that_is_not_a_code_goes_nowhere(browser_context, code) -> None:
    page = _code_worker(browser_context, [{**CODE_ACTION, "payload": {"code": code}}])
    _typing_tab(page, True)
    _page_loaded(page, 9, "https://dash.example/student/")
    assert _calls(page, "tabs.sendMessage") == []
    assert page.evaluate("() => window.__session.dock.code ?? null") is None
    results = [body for key, body in page.evaluate("() => window.__fetched") if key.endswith("/result")]
    assert results == [{"ok": False, "detail": {"refused": "invalid_action"}}]


@pytest.mark.extension
def test_a_link_from_the_inbox_opens_in_a_new_tab_and_ends_the_watch(browser_context) -> None:
    link = {**CODE_ACTION, "kind": "OPEN_VERIFICATION_URL", "payload": {"url": f"{PORTAL}/verify?t=abc"}}
    page = _code_worker(browser_context, [link], watch={APP_A: {"until": 9e15, "ticks": 0}})
    _tick(page)
    assert _calls(page, "tabs.create") == [[{"url": f"{PORTAL}/verify?t=abc", "active": False}]]
    assert page.evaluate("() => window.__session.dock.message") == "link_opened"
    assert _watching(page) == {}


@pytest.mark.extension
@pytest.mark.parametrize(
    "check", [[202, {"queued": 0}], [409, {"error": "mailbox_disconnected"}]]
)
def test_no_inbox_means_the_student_is_told_at_once(browser_context, check) -> None:
    page = _code_worker(browser_context, [], check=check)
    _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT)
    assert page.evaluate("() => window.__session.dock.message") == "type_code_yourself"
    assert _watching(page) == {}


@pytest.mark.extension
def test_ten_minutes_without_mail_hands_it_to_the_student(browser_context) -> None:
    page = _code_worker(browser_context, [], watch={APP_A: {"until": 1, "ticks": 3}})
    _tick(page)
    assert page.evaluate("() => window.__session.dock.message") == "type_code_yourself"
    assert _watching(page) == {}


@pytest.mark.extension
def test_a_watch_checks_the_mailbox_three_times_at_most(browser_context) -> None:
    page = _code_worker(browser_context, [])
    _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT)
    _send(page, {"type": "await-code", "applicationId": APP_A}, CONTENT)  # extends, spends nothing
    for _ in range(12):
        _tick(page)
    checks = [k for k, _ in page.evaluate("() => window.__fetched") if k == "POST /ext/mailbox/check"]
    assert len(checks) == 3


@pytest.mark.extension
@pytest.mark.parametrize(
    ("message", "sender"),
    [
        ({"type": "await-code", "applicationId": APP_B}, CONTENT),
        ({"type": "await-code", "applicationId": APP_A}, PANEL_SENDER),
        ({"type": "await-code", "applicationId": APP_A}, {**CONTENT, "frameId": 2}),
    ],
)
def test_only_the_bound_tab_may_start_a_watch_for_its_own_application(
    browser_context, message, sender
) -> None:
    page = _code_worker(browser_context, [])
    assert _send(page, message, sender) == {"ok": False, "code": "untrusted_sender"}
    assert _watching(page) == {}
```

The stub `chrome.alarms` in `_load_worker` (about line 1077) has `create` and `onAlarm` but no `clear`, and `endWatch` calls `clear`. Change that line to:

```python
              alarms: { create: record("alarms.create"), clear: record("alarms.clear", true), onAlarm: listeners("alarm") },
```

`record` returns `undefined` for `create`, the same as the old `async () => {}`, so the registration-alarm tests are unaffected.

- [ ] **Step 2: Build and run them to verify they fail**

Run: `npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py -q -k "code or link_from_the_inbox or no_inbox or ten_minutes or watch"`
Expected: FAIL. There is no `await-code` handler, and `TYPE_CODE` only sets `message: "TYPE_CODE"`.

- [ ] **Step 3: Implement.** In `api.ts`, `checkMailbox` returns the server's count:

```ts
export async function checkMailbox(origin: string): Promise<{ queued: number }> {
  const body = (await call(origin, "/ext/mailbox/check", { method: "POST" })) as { queued?: unknown };
  return { queued: typeof body.queued === "number" ? body.queued : 0 };
}
```

The registration alarm's existing `await checkMailbox(origin)` ignores the value and stays as is.

In `types.ts`, add this to `DockState` after `registration`:

```ts
  /** A verification code the co-pilot could not type: shown in the panel only
   *  (spec §6). Cleared on the next Start and the next watch. */
  code?: string | null;
```

In `service_worker.ts`:
- add `"await-code"` to `CONTENT_TYPES`;
- add `CODE_WATCH_ALARM`, `CODE_RE`, the watch helpers and the action delivery below, beside `REGISTRATION_ALARM` and `answerActions`;
- `startFill`'s final `patchDock({...})` gains `code: null`.

```ts
/** One alarm per application whose portal mail we are waiting for (spec §6). */
const CODE_WATCH_ALARM = "code-watch:";
/** The server's own rule for a code (apps/mailbox/actions.py). */
const CODE_RE = /^[A-Za-z0-9]{1,12}$/;
/** Ten minutes; mailbox syncs at the start and at ticks 4 and 10 (2 and 5
 *  minutes) -- three of SYNC_LIMIT's six an hour. */
const WATCH_MS = 10 * 60 * 1000;
const SYNC_TICKS = new Set([4, 10]);

type Watches = Record<string, { until: number; ticks: number }>;

async function watches(): Promise<Watches> {
  return ((await chrome.storage.session.get("codeWatch"))["codeWatch"] ?? {}) as Watches;
}

async function endWatch(applicationId: string): Promise<void> {
  const all = await watches();
  delete all[applicationId];
  await chrome.storage.session.set({ codeWatch: all });
  await chrome.alarms.clear(`${CODE_WATCH_ALARM}${applicationId}`);
}

/** The page asked for an emailed code, or a sign-up was just typed. A second
 *  ask while watching only extends the watch: no extra mailbox sync. */
async function startWatch(applicationId: string): Promise<void> {
  const all = await watches();
  if (all[applicationId]) {
    all[applicationId]!.until = Date.now() + WATCH_MS;
    await chrome.storage.session.set({ codeWatch: all });
    return;
  }
  const origin = await dashboardOrigin();
  if (!origin) return;
  try {
    const { queued } = await checkMailbox(origin);
    if (queued === 0) return void (await patchDock({ message: "type_code_yourself" }));
  } catch (error) {
    if (error instanceof ExtError && error.code === "mailbox_disconnected") {
      return void (await patchDock({ message: "type_code_yourself" }));
    }
    // rate_limited or offline: a push-driven sync may still bring it; watch anyway.
  }
  all[applicationId] = { until: Date.now() + WATCH_MS, ticks: 0 };
  await chrome.storage.session.set({ codeWatch: all });
  await patchDock({ code: null });
  await chrome.alarms.create(`${CODE_WATCH_ALARM}${applicationId}`, { periodInMinutes: 0.5 });
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm.name.startsWith(CODE_WATCH_ALARM)) return;
  const applicationId = alarm.name.slice(CODE_WATCH_ALARM.length);
  const all = await watches();
  const watch = all[applicationId];
  if (!watch) return void (await chrome.alarms.clear(alarm.name));
  if (Date.now() > watch.until) {
    await endWatch(applicationId);
    return void (await patchDock({ message: "type_code_yourself" }));
  }
  watch.ticks += 1;
  await chrome.storage.session.set({ codeWatch: all });
  const origin = await dashboardOrigin();
  if (!origin) return;
  if (SYNC_TICKS.has(watch.ticks)) await checkMailbox(origin).catch(() => undefined);
  await pollActions(origin);
});

/** Type the mail's code into the tab bound to its application, on that
 *  binding's own origin, top frame only -- or show it in the panel. */
async function deliverCode(origin: string, action: DeviceActionRow): Promise<void> {
  const code = action.payload["code"];
  if (typeof code !== "string" || !CODE_RE.test(code)) {
    await postActionResult(origin, action.id, false, { refused: "invalid_action" });
    return;
  }
  const binding = Object.values(await bindings()).find(
    (b) => b.active && action.application_id !== null && b.applicationId === action.application_id,
  );
  let typed = false;
  if (binding) {
    const tab = await chrome.tabs.get(binding.tabId).catch(() => null);
    if (tab?.url && onOrigin(tab.url, binding.origin)) {
      const reply = (await chrome.tabs
        .sendMessage(binding.tabId, { type: "type-code", code, origin: binding.origin }, { frameId: 0 })
        .catch(() => null)) as { typed?: unknown } | null;
      typed = reply?.typed === true;
    }
  }
  if (action.application_id) await endWatch(action.application_id);
  await patchDock(typed ? { message: "code_typed", code: null } : { message: "code_shown", code });
  await postActionResult(origin, action.id, true, { typed });
}
```

In `answerActions`, handle `TYPE_CODE` before the link branch:

```ts
    if (action.kind === "TYPE_CODE") {
      await deliverCode(origin, action);
      continue;
    }
```

In the existing link branch, after `postActionResult(…, { opened: true })`, add:

```ts
      if (action.application_id) await endWatch(action.application_id);
      await patchDock({ message: "link_opened" });
```

In `handle`, after plan 2's `portal-login` case:

```ts
  if (message?.type === "await-code") {
    void startWatch(message.applicationId).then(() => sendResponse({ ok: true }));
    return true;
  }
```

`contentRefusal` already ties `applicationId` to the bound tab, its top frame and its origin. `await-code` needs no check of its own.

- [ ] **Step 4: Typecheck, build, run the extension suite**

Run: `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py tests/portals/test_extension_bundle.py -q`
Expected: PASS, including the registration-alarm tests that call `checkMailbox`.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add extension/src/api.ts extension/src/types.ts extension/src/service_worker.ts tests/portals/test_extension_e2e.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(extension): watch the inbox while the portal waits for its email; type the code into its own tab or show it in the panel"
```

---

### Task 3: The panel says what happened

**Files:**
- Modify: `extension/src/panel/panel.html` (a `#code` section after `#registration`)
- Modify: `extension/src/panel/panel.ts` (`EMPTY.code`, render)
- Modify: `extension/src/panel/i18n.ts` (six strings in each of four languages)
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Consumes: `DockState.code` and the dock messages from Tasks 1–2.
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.extension
def test_the_panel_shows_a_code_only_when_it_could_not_be_typed(browser_context) -> None:
    page = _open_panel(browser_context)
    assert page.is_hidden("#code")
    _push_state(page, {"message": "code_shown", "code": "482913"})
    assert page.is_visible("#code")
    assert "482913" in page.inner_text("#code")
    _push_state(page, {"message": "code_typed", "code": None})
    assert page.is_hidden("#code")
    assert "Verify" in page.inner_text("#message") or "Confirm" in page.inner_text("#message")


@pytest.mark.extension
@pytest.mark.parametrize(
    "code", ["waiting_code", "code_typed", "code_shown", "link_opened", "type_code_yourself"]
)
def test_every_mail_message_has_its_own_line(browser_context, code) -> None:
    strings = _open_panel(browser_context).evaluate("() => window.__elmify_strings.en")
    assert f"m_{code}" in strings
```

`test_every_panel_string_exists_in_all_four_languages` (already in the suite) covers az, tr and ru.

- [ ] **Step 2: Build and run them to verify they fail**

Run: `npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py -q -k "panel_shows_a_code or mail_message"`
Expected: FAIL. `#code` does not exist.

- [ ] **Step 3: Implement.** In `panel.html`, after the `#registration` section:

```html
      <section id="code" hidden aria-live="polite">
        <p id="code-text"></p>
      </section>
```

In `panel.ts`, add `code: null,` to `EMPTY`, and at the end of the render function, after the registration block:

```ts
  const code = document.getElementById("code");
  if (code) code.hidden = !state.code;
  const codeText = document.getElementById("code-text");
  if (codeText && state.code) codeText.textContent = t(lang, "code_here", { code: state.code });
```

`textContent`, never `innerHTML`: the code came from an email.

In `i18n.ts`, each language gains:

| key | en | az | tr | ru |
|---|---|---|---|---|
| `m_waiting_code` | "The portal emailed you a code. We are getting it from your inbox." | "Portal sizə e-poçtla kod göndərdi. Onu poçt qutunuzdan götürürük." | "Portal size e-postayla bir kod gönderdi. Onu gelen kutunuzdan alıyoruz." | "Портал отправил вам код по почте. Мы забираем его из вашего ящика." |
| `m_code_typed` | "Verification code from your email entered. Press the portal's Verify or Confirm button." | "E-poçtunuzdakı təsdiq kodu yazıldı. Portalın Təsdiqlə düyməsini basın." | "E-postanızdaki doğrulama kodu girildi. Portalın Doğrula veya Onayla düğmesine basın." | "Код подтверждения из вашей почты введён. Нажмите на портале кнопку подтверждения." |
| `m_code_shown` | "We found the code in your email but could not type it. Type it into the portal yourself." | "Kodu e-poçtunuzda tapdıq, amma yaza bilmədik. Onu portala özünüz yazın." | "Kodu e-postanızda bulduk ama yazamadık. Portala kendiniz yazın." | "Мы нашли код в вашей почте, но не смогли его ввести. Введите его на портале сами." |
| `m_link_opened` | "We opened the verification link from your email in a new tab." | "E-poçtunuzdakı təsdiq linkini yeni tabda açdıq." | "E-postanızdaki doğrulama bağlantısını yeni bir sekmede açtık." | "Мы открыли ссылку подтверждения из вашей почты в новой вкладке." |
| `m_type_code_yourself` | "We could not get the portal's email for you. Open it in your inbox and use its code or link." | "Portalın məktubunu sizin üçün ala bilmədik. Onu poçt qutunuzda açın və kodu və ya linki istifadə edin." | "Portalın e-postasını sizin için alamadık. Gelen kutunuzda açın ve kodu ya da bağlantıyı kullanın." | "Мы не смогли получить письмо портала. Откройте его в своём ящике и используйте код или ссылку." |
| `code_here` | "Your code: {code}" | "Kodunuz: {code}" | "Kodunuz: {code}" | "Ваш код: {code}" |

The first test's `#message` assertion matches the English `m_code_typed`, which names both buttons.

- [ ] **Step 4: Typecheck, build, run the extension suite**

Run: `npm --prefix extension run typecheck && npm --prefix extension run build && npm --prefix extension run build:test && POSTGRES_DB=elmify_copilot_accounts uv run pytest tests/portals/test_extension_e2e.py tests/portals/test_extension_bundle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add extension/src/panel/panel.html extension/src/panel/panel.ts extension/src/panel/i18n.ts tests/portals/test_extension_e2e.py
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(panel): say what happened to the portal's email, and show a code only when it could not be typed"
```

---

## Not in this plan

- **Split code inputs** (one box per digit). The panel shows the code instead.
- **SMS and authenticator-app codes.** These stay the student's turn (§10, existing challenge handling).
- **A code mail tied to no application** (several applications on one portal host, `apps/mailbox/actions.py` `shared_portal`). It is shown in the panel, never typed: the platform does not guess which tab.
