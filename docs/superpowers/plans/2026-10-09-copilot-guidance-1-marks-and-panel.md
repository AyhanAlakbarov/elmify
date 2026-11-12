# Co-pilot Guidance 1 — On-page Marks and the Reworked Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The student sees what the co-pilot did right next to each field on the portal page (display-only marks), and controls, checks and reviews everything in a side panel that speaks their language. Filling starts from the dashboard's "Apply", follows them across the portal's pages, and never types over what they changed.

**Architecture:**
- **The content script keeps a per-field state.** `content/state.ts` holds filled / already correct / on another page / your turn / changed by you / portal error / mismatch, plus attached documents. It reports that state to the panel (labels and reasons, never the student's values to the page). `content/marks.ts` draws those states beside each field from a closed shadow root, with `pointer-events: none`.
- **The service worker turns the dashboard's `START_FILL` action into a portal tab bound to that application.** The panel's Start button (a user gesture) grants the portal origin and injects `content.js`. The worker re-injects it on each page load while the panel is open.
- **The panel renders the full list, the review and the language choice.** Its own strings table covers az/tr/ru/en.

**Tech Stack:** TypeScript 5.7 + esbuild (MV3, `extension/`), Python/pytest + Playwright Chromium (tests), Django (no server changes in this plan).

**Spec:** `docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md` (§3 journey, §4 marks, §5 panel, §7 the visibility rule for documents, §8 safety, §10 cases, §12 accessibility). Plans 2–6 cover the portal account (§6), mail codes, document preparation, learning unmapped forms, and the test bench.

## Not in this plan
- **Sign-up, login and stored passwords (§6):** plan 2. Here, a portal login page only makes the panel say "Log in, then we continue".
- **Verification codes from mail:** plan 3.
- **Preparing documents to programme rules (§7 first bullet):** plan 4.
- **Learning an unmapped form, and matching upload boxes by surrounding text (§10, §7):** plan 5. Here, a form with no field map shows the server's `no_field_map` refusal as today.
- **The test bench (§9):** plan 6.
- **Plain-language explanations of portal errors (§13):** this plan shows the portal's own error text with a generic localized line.

## Global Constraints
- **Manifest:** `manifest.json` keeps no `content_scripts`, `host_permissions: []`, `optional_host_permissions: ["https://*/*"]` (pinned by `tests/portals/test_extension_bundle.py`).
- **DOM creation:** `createElement` / `attachShadow` only under `extension/src/panel/` and `extension/src/content/` (bundle test).
- **No clicks:** no code path clicks (`test_no_code_path_clicks`). The extension types; the student clicks Next, Submit, consent and navigation.
- **Marks are display-only:** `pointer-events: none`; no buttons, links or inputs; no student value or any identifier of the student, account or agency in the page layer (spec §4, §11).
- **The panel is the authority:** every state a mark shows also appears in the panel, and a mark that cannot be placed is only in the panel.
- **The student's edits win:** never type into a non-empty field, and never type over a value the student changed (spec §10).
- **Documents attach only into a visible upload control named for the document:** the input, or the label/button that opens it, must be visible (spec §7).
- **Panel languages:** `az`, `tr`, `ru`, `en`. The student picks one; the default comes from the browser language, else `en` (D6).
- **The final wording (D5), verbatim in English:** "Check every field and document. When you are sure everything is correct, press Next / Submit yourself. We never press it for you."
- **Existing test contracts:**
  - Keep the panel DOM ids the e2e suite uses: `#registration`, `#registration-question`, `#arrived-tagged`, `#arrived-plain`, `#arrived-none`, `#sender`, `#use-plain`, `#filled`, `#your-turn`, `#mismatches`, `#status`, `#message`.
  - Keep the `SHOULD BE DONE BY AYKHAN` marker in `panel.ts`.
- **Commands:**
  - Build and type-check: `npm --prefix extension run check`.
  - Bundle tests: `uv run pytest tests/portals/test_extension_bundle.py -q`.
  - Browser tests: `uv run pytest tests/portals/test_extension_e2e.py -m extension -q`.
  - Python lint: `uv run ruff check .` (never `ruff format`).
- **Worktree:** `/home/orkhan/Desktop/copilot-guidance`, branch `claude/copilot-on-page-guidance`; use `git -C` for git. The shell's working directory resets between calls.

## Review Focus
1. **A portal page whose CSS sets `* { all: unset }` or `div { display: none !important }` on everything.** Marks still render, the right size, beside the field (Task 3 test).
2. **The student edits a filled field, then the page reloads (a new injection).** The co-pilot does not retype it, and the panel says "Changed by you" (Task 1 test).
3. **Page 2 of a multi-page form.** Page-1 fields are "on another page", not "your turn", and are not marked red (Task 1 test).
4. **The page removes our mark host (SPA re-render) ten times in a row.** The marks stop being re-attached, and the panel lists those fields as "shown here only" (Task 3 test).
5. **The panel is closed mid-form.** No re-injection happens on the next page, and reopening resumes (Task 6 test).

---

### Task 1: The per-field state, and resume without overwriting

**Files:**
- Create: `extension/src/content/state.ts`
- Modify: `extension/src/content/index.ts` (`run`), `extension/src/content/fill.ts` (`fillVerified` fills only empty controls)
- Modify: `extension/src/types.ts` (`FieldView`, `DockState.fields`)
- Create: `tests/portals/fixtures/two_page_form_page2.html`, `tests/portals/fixtures/prefilled_by_student.html`
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Produces, in `types.ts`:

```ts
export type FieldStateKind =
  | "filled"          // we typed it and read back the same value
  | "already"         // the page already held exactly our value
  | "elsewhere"       // the control is not on this page (multi-page form)
  | "your_turn"       // refused: hidden, disabled, mislabelled, no option, no fact
  | "changed_by_you"  // the student typed after us, or the field held their own value
  | "portal_error"    // the portal flagged the control after a submit/next
  | "mismatch";       // the page holds something else after our fill (not the student)
export interface FieldView {
  key: string;            // profile_field, e.g. "personal.given_name"
  state: FieldStateKind;
  reason: string;         // stable code, "" when none (verify.ts reasons, "portal:<text>")
  placed: boolean;        // a mark is on the page for it (Task 3 sets this)
}
// DockState gains:
fields: FieldView[];
documents: { filename: string; state: "attached" | "manual" }[];
```

- Produces, in `content/state.ts`:
  - `export function classify(verified: VerifiedEntry[], filled: string[], skip: Set<string>, mismatches: Mismatch[], theirs: Set<string>): Map<string, FieldRecord>`.
  - `export interface FieldRecord { view: FieldView; element: HTMLElement | null }`.
  - `export function watchStudentEdits(records: Map<string, FieldRecord>, onChange: () => void): void`.
- `fillVerified(verified, skip)` keeps its signature but returns only the profile_fields it typed into. A control that is not empty and not equal to our value is left alone, and its key goes to `changed_by_you`.

- [ ] **Step 1: Fixtures**

`tests/portals/fixtures/prefilled_by_student.html`: a copy of `plain_form.html` whose given-name input carries `value="Aysel M."` (the student's own edit), and whose family-name input is empty.

`tests/portals/fixtures/two_page_form_page2.html`: a form with only `<label for="phone">Phone</label><input id="phone" name="phone">`. The packet still lists the page-1 fields (given name, family name).

- [ ] **Step 2: Write the failing tests** (`tests/portals/test_extension_e2e.py`, using `_run_with_stubbed_messaging`)

```python
def _dock_fields(sent):
    patches = [m["patch"] for m in sent if m.get("type") == "dock" and "fields" in m.get("patch", {})]
    return {f["key"]: f for f in patches[-1]["fields"]}


@pytest.mark.extension
def test_a_field_the_student_already_changed_is_never_typed_over(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/prefilled_by_student.html")
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _plain_packet(fixture_server, "prefilled_by_student.html")}})
    assert page.input_value("#given_name") == "Aysel M."
    fields = _dock_fields(sent)
    assert fields["personal.given_name"]["state"] == "changed_by_you"
    assert fields["personal.family_name"]["state"] == "filled"


@pytest.mark.extension
def test_fields_of_another_page_are_elsewhere_not_your_turn(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/two_page_form_page2.html")
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _two_page_packet(fixture_server)}})
    fields = _dock_fields(sent)
    assert fields["personal.given_name"]["state"] == "elsewhere"
    assert fields["contact.phone"]["state"] == "filled"


@pytest.mark.extension
def test_a_student_edit_after_our_fill_is_reported_as_theirs(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _plain_packet(fixture_server, "plain_form.html")}})
    page.fill("#given_name", "Aysel")  # the TEST types as the student (trusted input events)
    sent = page.evaluate("() => window.__sent")
    assert _dock_fields(sent)["personal.given_name"]["state"] == "changed_by_you"
```

`_plain_packet(server, path)` and `_two_page_packet(server)` build packets in the same shape as the existing `_email_packet`, with `form_url` set to the fixture's URL. Read `_email_packet` (line ~430) and mirror it: entries for `personal.given_name` (`#given_name`), `personal.family_name` (`#family_name`) and, in the two-page packet, `contact.phone` (`#phone`).

- [ ] **Step 3: Run them to see them fail**

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_e2e.py -m extension -q -k "already_changed or another_page or student_edit"`
Expected: FAIL (no `fields` in any dock patch).

- [ ] **Step 4: Implement**

`extension/src/content/state.ts`:

```ts
import type { FieldView } from "../types.js";
import type { VerifiedEntry } from "./verify.js";

export interface Mismatch { profile_field: string; expected: string; actual: string }
export interface FieldRecord { view: FieldView; element: HTMLElement | null }

/** One record per packet entry, from what verify/fill/read-back found. Pure: no DOM writes. */
export function classify(
  verified: VerifiedEntry[],
  filled: string[],
  skip: Set<string>,
  mismatches: Mismatch[],
  theirs: Set<string>,
): Map<string, FieldRecord> {
  const typed = new Set(filled);
  const off = new Set(mismatches.map((m) => m.profile_field));
  const records = new Map<string, FieldRecord>();
  for (const item of verified) {
    const key = item.entry.profile_field;
    let state: FieldView["state"];
    let reason = "";
    if (!item.ok && item.reason === "no_such_control") state = "elsewhere";
    else if (!item.ok) { state = "your_turn"; reason = item.reason; }
    else if (theirs.has(key)) state = "changed_by_you";
    else if (off.has(key)) state = "mismatch";
    else if (typed.has(key)) state = "filled";
    else if (skip.has(key)) state = "already";
    else { state = "your_turn"; reason = "not_filled"; }
    records.set(key, { view: { key, state, reason, placed: false }, element: item.element });
  }
  return records;
}

/** A trusted input on a control we filled or left already-correct makes it the student's. */
export function watchStudentEdits(records: Map<string, FieldRecord>, onChange: () => void): void {
  for (const record of records.values()) {
    const element = record.element;
    if (!element || !["filled", "already", "mismatch"].includes(record.view.state)) continue;
    element.addEventListener("input", (event) => {
      if (!event.isTrusted) return; // our own dispatched events are untrusted
      record.view.state = "changed_by_you";
      record.view.reason = "";
      onChange();
    });
  }
}
```

In `fill.ts::fillVerified`, before typing into an element: if the control's current value is non-empty and differs from `entry.value` (for `select`: the selected option is not the first/placeholder option and differs), do not type. Instead, add the key to a `theirs: Set<string>` that the function now also returns. Change the return to `{ filled: string[]; theirs: Set<string> }` and update its two callers (`run` and the `__elmify_fill` hook, which keeps returning `filled` only).

In `index.ts::run`, after read-back:

```ts
const records = classify(verified, filled, skip, mismatches, theirs);
const report = () => void dock({ fields: Array.from(records.values(), (r) => r.view) });
watchStudentEdits(records, report);
report();
```

Keep the existing `filled` / `yourTurn` / `mismatches` dock keys (the panel still reads them until Task 5), but compute `yourTurn` from `records` entries in state `your_turn` only. This removes the page-1 fields wrongly listed as "your turn" on page 2. Keep `documents` too: `attached` and `manual` from `attachDocuments` become `{filename, state}` rows.

- [ ] **Step 5: Run the tests**

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_e2e.py -m extension -q && uv run pytest tests/portals/test_extension_bundle.py -q`
Expected: PASS (all existing e2e tests too).

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/copilot-guidance add extension/src tests/portals
git -C /home/orkhan/Desktop/copilot-guidance commit -m "feat(extension): a state per field; never type over the student's own value

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Documents attach only into a visible upload control

**Files:**
- Modify: `extension/src/content/fill.ts` (`attachDocuments`)
- Modify: `extension/src/content/verify.ts` (export `visible`)
- Create: `tests/portals/fixtures/hidden_upload_trap.html`, `tests/portals/fixtures/styled_upload_button.html`
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Consumes: `visible(element: HTMLElement): boolean` (now exported from `verify.ts`).
- Produces: `attachDocuments` with the same signature. An upload input is a candidate only when `visible(input)`, or when a visible `<label for=id>`, wrapping `<label>`, or `aria-controls`/`aria-labelledby` element of it is visible **and** carries the document's terms.

- [ ] **Step 1: Fixtures**

`hidden_upload_trap.html`: one visible `<label for="cv">Upload CV</label><input type="file" id="cv">`, plus a hidden `<input type="file" aria-label="Transcript" style="display:none">` with no visible label.

`styled_upload_button.html`: a native `<input type="file" id="tr" style="opacity:0;position:absolute;width:1px;height:1px">` opened by a visible `<label for="tr" class="btn">Upload transcript</label>`, the usual "pretty button" pattern.

- [ ] **Step 2: Failing tests**

```python
def _attach(page, names):
    page.add_script_tag(path=str(DIST / "content.js"))
    return page.evaluate(
        "(names) => window.__elmify_attach(names.map((n) => ({filename: n, bytes: new ArrayBuffer(4)})))",
        names,
    )


@pytest.mark.extension
def test_a_hidden_upload_box_never_receives_a_document(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hidden_upload_trap.html")
    result = _attach(page, ["cv.pdf", "transcript.pdf"])
    assert [a["filename"] for a in result["attached"]] == ["cv.pdf"]
    assert result["manual"] == ["transcript.pdf"]


@pytest.mark.extension
def test_a_styled_upload_button_still_gets_its_document(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/styled_upload_button.html")
    result = _attach(page, ["transcript.pdf"])
    assert [a["filename"] for a in result["attached"]] == ["transcript.pdf"]
```

- [ ] **Step 3: Run to see them fail**

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_e2e.py -m extension -q -k upload`
Expected: the hidden-box test FAILS (the transcript is attached to the hidden input).

- [ ] **Step 4: Implement**

Export `visible` from `verify.ts`. In `attachDocuments`, replace the candidate filter:

```ts
function opener(input: HTMLInputElement): HTMLElement | null {
  if (visible(input)) return input;
  const byFor = input.id ? document.querySelector<HTMLElement>(`label[for="${CSS.escape(input.id)}"]`) : null;
  const wrapping = input.closest("label");
  for (const candidate of [byFor, wrapping]) if (candidate && visible(candidate)) return candidate;
  return null;
}
const inputs = Array.from(document.querySelectorAll("input[type=file]")).filter(
  (input): input is HTMLInputElement => input instanceof HTMLInputElement && !input.disabled && opener(input) !== null,
);
```

Match the document's terms against `accessibleName(input)` **or** the opener's `innerText`, since the visible label is what the student reads.

- [ ] **Step 5: Run the tests** (all e2e + bundle). Expected: PASS, including `test_each_document_finds_its_own_upload_slot`.

- [ ] **Step 6: Commit** — `"fix(extension): a document goes only into an upload box the student can see"`.

---

### Task 3: The marks layer

**Files:**
- Create: `extension/src/content/marks.ts`
- Modify: `extension/src/content/index.ts` (draw after `classify`; redraw on state change)
- Create: `tests/portals/fixtures/hostile_css_form.html`, `tests/portals/fixtures/rerender_form.html`
- Test: `tests/portals/test_extension_e2e.py`, `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Produces:
  - `export function drawMarks(records: Map<string, FieldRecord>, labels: MarkLabels): void`.
  - `export function clearMarks(): void`.
  - `export interface MarkLabels { filled: string; check: string; yourTurn: string; changed: string; portalError: string; why: (key: string) => string; next: string | null }`.
  - Test hook `__elmify_marks()` returns `{ key, state, placed, rect: {x,y,w,h} }[]`, read from the module's own bookkeeping, since the page cannot read a closed shadow root.
- Labels come from the content script's own small string set (the next-step chip and "why" text), passed in from `run`. Task 5 makes them follow the student's language.

- [ ] **Step 1: Fixtures**

- `hostile_css_form.html`: `plain_form.html` plus `<style>* { all: unset !important; font-size: 4px !important } div { display: none !important } [class] { z-index: 2147483647 !important }</style>`.
- `rerender_form.html`: `plain_form.html` plus a script that, every 50 ms for 1 s, removes every child of `<body>` that is not in the original markup. It removes our host the same way an SPA re-render does.

- [ ] **Step 2: Failing tests**

```python
@pytest.mark.extension
def test_marks_sit_beside_filled_fields_and_ignore_the_page_css(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/hostile_css_form.html")
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _plain_packet(fixture_server, "hostile_css_form.html")}})
    marks = {m["key"]: m for m in page.evaluate("() => window.__elmify_marks()")}
    assert marks["personal.given_name"]["state"] == "filled" and marks["personal.given_name"]["placed"]
    assert marks["personal.given_name"]["rect"]["h"] >= 12          # not shrunk to the page's 4px
    host = page.evaluate("() => { const h = document.querySelector('[data-elmify-marks]'); return h && { open: !!h.shadowRoot, pe: getComputedStyle(h).pointerEvents }; }")
    assert host == {"open": False, "pe": "none"}                       # closed root, never clickable


@pytest.mark.extension
def test_a_page_that_keeps_removing_the_marks_falls_back_to_the_panel(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/rerender_form.html")
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _plain_packet(fixture_server, "rerender_form.html")}})
    page.wait_for_timeout(1200)
    marks = page.evaluate("() => window.__elmify_marks()")
    assert all(not m["placed"] for m in marks)
    sent = page.evaluate("() => window.__sent")
    assert all(not f["placed"] for f in _dock_fields(sent).values())


@pytest.mark.extension
def test_a_mark_carries_no_student_value(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/plain_form.html")
    _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _plain_packet(fixture_server, "plain_form.html")}})
    text = page.evaluate("() => window.__elmify_marks_text()")  # all text the layer rendered
    assert "Aysel" not in text and "Mammadova" not in text
```

The host is identified by a `data-elmify-marks` attribute **only in test builds**. Production uses no fixed attribute: the bundle test below pins that the attribute is behind `__ELMIFY_TEST__`, so a portal cannot fingerprint us by it (spec §11). Use an esbuild `define: { __ELMIFY_TEST__: "false" }` in the production build, and a second build `npm --prefix extension run build:test` (`define: "true"`) into `dist-test/`, which the e2e fixture uses. Update `DIST` in the e2e file to `extension/dist-test` and add the CI step to build it (`.github/workflows/ci.yml`, extension job).

Bundle test (`tests/portals/test_extension_bundle.py`):

```python
def test_the_marks_layer_is_closed_unclickable_and_unmarked_in_production():
    content = bundle_text("content.js")
    assert 'mode: "closed"' in content or "mode:\"closed\"" in content
    assert "pointer-events" in content and "none" in content
    assert "data-elmify-marks" not in content  # test-build only
```

- [ ] **Step 3: Run to see them fail.** Expected: FAIL (`__elmify_marks` is not a function).

- [ ] **Step 4: Implement `marks.ts`**

```ts
import type { FieldRecord } from "./state.js";

declare const __ELMIFY_TEST__: boolean;

export interface MarkLabels {
  filled: string; check: string; yourTurn: string; changed: string; portalError: string;
  why: (key: string) => string; next: string | null;
}

const MAX_REATTACH = 5;
let host: HTMLElement | null = null;
let root: ShadowRoot | null = null;
let reattached = 0;
let observer: MutationObserver | null = null;
const drawn = new Map<string, { record: FieldRecord; node: HTMLElement | null }>();

function tagName(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return "x-" + Array.from(bytes, (b) => (b % 26 + 10).toString(36)).join("");
}

const STYLE = `
:host { all: initial !important; position: fixed !important; inset: 0 !important;
        pointer-events: none !important; z-index: 2147483647 !important; }
.mark { all: initial; position: fixed; display: flex; align-items: center; gap: 4px;
        font: 12px/1.3 system-ui, sans-serif; padding: 2px 6px; border-radius: 10px;
        pointer-events: none; white-space: nowrap; }
.filled { background: #e8f5ec; color: #145a2a; } .check { background: #fff4e0; color: #7a4a00; }
.your_turn, .portal_error { background: #fdecec; color: #8a1c1c; } .changed { background: #eef0f3; color: #3a3f47; }
.outline { all: initial; position: fixed; pointer-events: none; border-radius: 4px; box-sizing: border-box; }
.outline.check { border: 2px solid #e0a020; } .outline.your_turn, .outline.portal_error { border: 2px solid #d04040; }
.chip { background: #1d3a8a; color: #fff; font-weight: 600; }
`;

function ensureHost(): ShadowRoot | null {
  if (host?.isConnected && root) return root;
  if (reattached >= MAX_REATTACH) return null;          // the page keeps fighting: give up
  if (host) reattached += 1;
  host = document.createElement(tagName());
  if (__ELMIFY_TEST__) host.setAttribute("data-elmify-marks", "");
  host.setAttribute("aria-hidden", "true");
  host.style.setProperty("pointer-events", "none", "important");
  root = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = STYLE;
  root.append(style);
  document.documentElement.append(host);
  observer?.disconnect();
  observer = new MutationObserver(() => { if (!host?.isConnected) redraw(); });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  return root;
}

let lastLabels: MarkLabels | null = null;

export function drawMarks(records: Map<string, FieldRecord>, labels: MarkLabels): void {
  lastLabels = labels;
  drawn.clear();
  for (const [key, record] of records) drawn.set(key, { record, node: null });
  redraw();
}

function textFor(state: string, labels: MarkLabels): [string, string] | null {
  switch (state) {
    case "filled": case "already": return ["filled", "✓ " + labels.filled];
    case "mismatch": return ["check", "! " + labels.check];
    case "your_turn": return ["your_turn", "✎ " + labels.yourTurn];
    case "portal_error": return ["portal_error", "! " + labels.portalError];
    case "changed_by_you": return ["changed", "✎ " + labels.changed];
    default: return null; // "elsewhere": nothing on this page
  }
}

function redraw(): void {
  const shadow = ensureHost();
  for (const item of drawn.values()) { item.node?.remove(); item.node = null; item.record.view.placed = false; }
  if (!shadow || !lastLabels) return;
  for (const item of drawn.values()) {
    const element = item.record.element;
    const text = textFor(item.record.view.state, lastLabels);
    if (!element || !text || !element.isConnected) continue;
    const box = element.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) continue;
    const node = document.createElement("div");
    node.className = `mark ${text[0]}`;
    node.textContent = text[1];
    node.style.left = `${Math.min(box.right + 6, innerWidth - 160)}px`;
    node.style.top = `${box.top + Math.max(0, (box.height - 18) / 2)}px`;
    shadow.append(node);
    item.node = node;
    item.record.view.placed = true;
  }
}

export function clearMarks(): void {
  observer?.disconnect();
  host?.remove();
  host = null; root = null; drawn.clear();
}

addEventListener("scroll", () => redraw(), { passive: true, capture: true });
addEventListener("resize", () => redraw(), { passive: true });

export function marksForTest(): { key: string; state: string; placed: boolean; rect: { x: number; y: number; w: number; h: number } }[] {
  return Array.from(drawn, ([key, item]) => {
    const r = item.node?.getBoundingClientRect();
    return { key, state: item.record.view.state, placed: item.record.view.placed,
             rect: { x: r?.x ?? 0, y: r?.y ?? 0, w: r?.width ?? 0, h: r?.height ?? 0 } };
  });
}
export function marksTextForTest(): string {
  return Array.from(drawn.values(), (i) => i.node?.textContent ?? "").join("\n");
}
```

Also in `marks.ts`, build and test them the same way:
- **The outline:** a `div.outline.<state>` sized to the field's box, for `check`, `your_turn` and `portal_error`.
- **The "why" tag:** shown when the student **focuses** a filled field, by adding a `focusin` listener on the field's element. The tag reads `labels.why(key)`, e.g. "From your verified facts". Focus is used, not hover, because marks never receive pointer events (spec §4 said "hover"; this keeps the layer unclickable).
- **The next-step chip:** `labels.next`, if non-null, placed beside the first `your_turn` or `portal_error` field.

In `index.ts::run`, after `classify`, call `drawMarks(records, contentLabels(language))`. `contentLabels` is a small table in `content/labels.ts`, keyed by `az/tr/ru/en`, holding the six strings, the "why" templates and next-step texts ("Answer this", "Press Next", "Solve the captcha"). `language` comes from the `start` message (Task 6). Re-call `drawMarks` inside `report()` so a "changed by you" redraws. Expose the `__elmify_marks` / `__elmify_marks_text` hooks only when `__ELMIFY_TEST__`.

Every rendered string is in the shadow root as `textContent`, never `innerHTML`.

- [ ] **Step 5: Build both bundles and run all extension tests**

Add to `extension/package.json`: `"build:test": "node build.mjs --test"`. `build.mjs` reads `process.argv.includes("--test")` and writes to `dist-test` with `define: { __ELMIFY_TEST__: "true" }`; the default is `dist` with `"false"`. `check` builds both.

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_bundle.py -q && uv run pytest tests/portals/test_extension_e2e.py -m extension -q`
Expected: PASS.

- [ ] **Step 6: Commit** — `"feat(extension): display-only marks beside each field, in a closed shadow root"`.

---

### Task 4: The portal's own errors after Next

**Files:**
- Modify: `extension/src/content/page_signals.ts` (add `portalErrorFor(element): string | null`)
- Modify: `extension/src/content/state.ts`, `extension/src/content/index.ts`
- Create: `tests/portals/fixtures/portal_error_form.html`
- Test: `tests/portals/test_extension_e2e.py`

**Interfaces:**
- Produces: `export function portalErrorFor(element: HTMLElement): string | null`. It returns the portal's error text for a control:
  - `aria-invalid="true"` with an `aria-describedby` / `aria-errormessage` target's text;
  - else the text of an adjacent element (next sibling or the control's field wrapper) whose class contains `error`/`invalid`/`fehler` and that is visible.

  Trimmed, at most 200 characters, or null.
- Field state `portal_error` with `reason: "portal:<text>"`. It overrides `filled` / `already` / `mismatch`, but never `changed_by_you`: the student's value with a portal error shows "portal_error", and the panel says it is their value.

- [ ] **Step 1: Fixture.** `portal_error_form.html`: `plain_form.html`, where the family-name input has `aria-invalid="true" aria-describedby="fn-err"` and `<span id="fn-err" class="error">Ungültiger Nachname</span>`.

- [ ] **Step 2: Failing test**

```python
@pytest.mark.extension
def test_the_portal_s_own_error_turns_the_field_red_with_its_text(browser_context, fixture_server):
    page = browser_context.new_page()
    page.goto(f"{fixture_server}/portal_error_form.html")
    sent = _run_with_stubbed_messaging(page, {"packet": {"ok": True, "packet": _plain_packet(fixture_server, "portal_error_form.html")}})
    field = _dock_fields(sent)["personal.family_name"]
    assert field["state"] == "portal_error" and field["reason"] == "portal:Ungültiger Nachname"
```

- [ ] **Step 3: Run to see it fail.** Expected: FAIL (state `filled`).

- [ ] **Step 4: Implement.**
  - In `run`, after `classify`, for each record with an element and a state other than `elsewhere`, set `portal_error` per the rule above when `portalErrorFor(element)` returns text.
  - Add a `MutationObserver` on the form (attributes `aria-invalid`, plus childList) that re-checks and calls `report()`. A portal often shows its errors after an in-page validation, not a reload.

- [ ] **Step 5: Run all extension tests.** Expected: PASS.

- [ ] **Step 6: Commit** — `"feat(extension): the portal's own error marks the field and reaches the panel"`.

---

### Task 5: The panel speaks the student's language

**Files:**
- Create: `extension/src/panel/i18n.ts`
- Modify: `extension/src/panel/panel.html`, `extension/src/panel/panel.ts`
- Test: `tests/portals/test_extension_e2e.py`, `tests/portals/test_extension_bundle.py`

**Interfaces:**
- Produces, in `panel/i18n.ts`:

```ts
export type Lang = "az" | "tr" | "ru" | "en";
export const LANGS: readonly Lang[] = ["az", "tr", "ru", "en"];
export function defaultLang(browserLanguage: string): Lang; // "az-AZ" → "az"; unknown → "en"
export function t(lang: Lang, key: StringKey, vars?: Record<string, string>): string;
export function fieldLabel(lang: Lang, profileField: string): string; // "personal.given_name" → "Given name"/"Ad"/"Ad"/"Имя"
```

- `StringKey` covers every panel string:
  - headings: filled, your turn, check these, documents;
  - state words: filled, already correct, on another page, your turn, changed by you, portal error;
  - reason phrases for each `verify.ts` reason;
  - buttons: Start filling, Stop, Language;
  - the progress line template: "Page {page} · {done} of {total} done · {mine} need you";
  - review headings, the D5 wording, "lost connection", "log in, then we continue";
  - the registration prompts already in panel.html.
- Unknown profile fields fall back to `fieldKey` with underscores turned into spaces.
- The chosen language is stored in `chrome.storage.local` key `"language"` and sent to the worker as `{type:"language", lang}`. The worker keeps it in the dock state (`DockState.language: Lang`), so the content script's labels follow it (Task 6 passes it in `start`).

- [ ] **Step 1: Failing tests** (panel harness `_open_panel`/`_push_state`; extend the stub with `storage.local.get/set` and `i18n.getUILanguage: () => "az-AZ"`)

```python
@pytest.mark.extension
def test_the_panel_defaults_to_the_browser_language_and_can_switch(browser_context):
    page = _open_panel(browser_context)
    _push_state(page, {"status": "filling", "fields": [{"key": "personal.given_name", "state": "filled", "reason": "", "placed": True}]})
    assert page.locator("#language").input_value() == "az"
    page.select_option("#language", "en")
    assert "Given name" in page.locator("#fields").inner_text()
    assert {"type": "language", "lang": "en"} in page.evaluate("() => window.__sent")


@pytest.mark.extension
def test_the_review_says_the_owner_s_words(browser_context):
    page = _open_panel(browser_context)
    page.select_option("#language", "en")
    _push_state(page, {"status": "review", "fields": []})
    assert ("Check every field and document. When you are sure everything is correct, "
            "press Next / Submit yourself. We never press it for you.") in page.locator("#review").inner_text()
```

Bundle test: every `StringKey` has a value in all four languages, checked by evaluating `panel.js`'s exported table. Simpler: `i18n.ts` exports `STRINGS`, the test hook `__elmify_strings` exposes it when `__ELMIFY_TEST__`, and an e2e test asserts no empty or missing entry per language.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement.**
  - **`i18n.ts`:** fill the table. Write the az/tr/ru strings yourself, plainly. Mark the file's header comment: "Wording is reviewed against real portal pages on the test bench (spec §9) before release."
  - **`panel.html`:** add `<select id="language">` with the four options (endonyms: Azərbaycanca, Türkçe, Русский, English). Add `<section id="fields">`, `<section id="documents">` and `<section id="review" hidden>`. Keep every existing id.
  - **`panel.ts`:** render all text through `t()`. Render `fields` grouped by state, with friendly labels from `fieldLabel()` and reason phrases from `t()`, and `documents` with their file names. Keep `SHOULD BE DONE BY AYKHAN`.

- [ ] **Step 4: Run all extension tests.** Expected: PASS (update the existing panel tests' expected English strings only if their wording changed, and say so in the report).

- [ ] **Step 5: Commit** — `"feat(extension): the panel speaks the student's chosen language"`.

---

### Task 6: Start from the dashboard, follow every page, stop and review

**Files:**
- Modify: `extension/src/service_worker.ts`, `extension/src/api.ts`, `extension/src/types.ts`
- Modify: `extension/src/panel/panel.ts`, `extension/src/panel/panel.html`
- Modify: `extension/src/content/index.ts` (the `start` message carries `language`; a `stop` message; a login-page check)
- Test: `tests/portals/test_extension_bundle.py`, `tests/portals/test_extension_e2e.py`

**Interfaces:**
- **Worker, on a `START_FILL` action** (from `/ext/actions`, already queued by `apps/portals/applications.py` when the student presses Apply):
  1. fetch the packet for `action.application_id` (existing `api.ts` packet call);
  2. `chrome.tabs.create({ url: packet.form_url })`;
  3. store `binding: { tabId, applicationId, portalFormId, origin, language }` in `chrome.storage.session` key `"bindings"` (a map by tabId);
  4. `chrome.sidePanel.setOptions({ tabId, path: "panel.html", enabled: true })`;
  5. `patchDock({ applicationId, status: "ready", message: "start" })`.
- **Panel → worker:**
  - `{type:"start-fill", tabId}`, sent after the panel itself calls `chrome.permissions.request({ origins: [origin + "/*"] })` inside the Start button's click handler (the user gesture lives in the panel document);
  - `{type:"stop-fill", tabId}`;
  - `{type:"language", lang}` (Task 5).

  Each is gated in `messageRefusal` as dock-only, like `registration:answer`.
- **Worker → content:**
  - `chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] })`, then `chrome.tabs.sendMessage(tabId, { type: "start", applicationId, portalFormId, language })`;
  - `{type:"stop"}` clears the marks and ends observers.
- **Following pages:** on `chrome.tabs.onUpdated` with `status === "complete"` for a bound tab whose URL's origin equals `binding.origin`, and only while a panel port is connected, the worker re-injects and re-sends `start` (a resume). It never injects into an unbound tab or a different origin.
- **Panel open state:** the panel opens `chrome.runtime.connect({ name: "dock" })`. The worker records connected ports. On disconnect it stops re-injecting for that tab (pause), and on reconnect it re-injects once (resume).
- **Content, on `start`:** if the page has a visible `input[type=password]` and none of the packet's selectors resolve, it reports `dock({ status: "login", message: "log in" })` and does nothing else. The panel shows the localized "Log in, then we continue". Otherwise `run(...)`.
- **The review:** after `run`, the content script reports `status: "review"` when no field is in `your_turn`/`portal_error`/`mismatch` and every document is attached; otherwise `"blocked"`. The panel shows the review section (Task 5) in both states, listing what still needs the student first. There is no Next/Submit button anywhere.

- [ ] **Step 1: Failing bundle tests**

```python
def test_the_worker_injects_content_only_into_a_bound_tab_on_its_own_origin():
    worker = bundle_text("service_worker.js")
    assert 'files: ["content.js"]' in worker or "files:[\"content.js\"]" in worker
    assert "bindings" in worker and "onUpdated" in worker
    # the origin check sits with the re-injection
    assert re.search(r"onUpdated[\s\S]{0,800}origin", worker)


def test_start_and_stop_are_accepted_only_from_the_dock():
    worker = bundle_text("service_worker.js")
    for kind in ("start-fill", "stop-fill", "language"):
        assert re.search(rf'"{kind}"[\s\S]{{0,300}}fromDock', worker), kind
```

- [ ] **Step 2: Failing e2e tests** (worker injected with a stub `chrome`, as the existing worker tests do — read them for the harness)

```python
@pytest.mark.extension
def test_a_start_fill_action_opens_the_portal_tab_and_binds_it(...):
    # stub /ext/actions to return one START_FILL for app-1, packet with form_url https://portal.example/apply
    # assert chrome.tabs.create called with that url, sidePanel.setOptions with that tabId,
    # and session "bindings"[tabId] == {applicationId: "app-1", origin: "https://portal.example", ...}


@pytest.mark.extension
def test_a_closed_panel_pauses_and_a_reopened_panel_resumes(...):
    # bind tab 7; no dock port connected; fire tabs.onUpdated(7, {status:"complete"}, {url:"https://portal.example/p2"})
    # assert scripting.executeScript NOT called; connect a "dock" port; assert it IS called once


@pytest.mark.extension
def test_another_origin_in_the_bound_tab_is_never_injected(...):
    # bound to https://portal.example; onUpdated with url https://evil.example/ -> no executeScript
```

Write the three tests concretely against the worker harness the file already uses for worker tests (find it with `grep -n "service_worker.js" tests/portals/test_extension_e2e.py`). Stub `chrome.tabs.create/sendMessage`, `chrome.scripting.executeScript`, `chrome.sidePanel.setOptions`, `chrome.storage.session` (an in-memory object), `chrome.runtime.onConnect`, and `fetch` for `/ext/actions` and the packet.

- [ ] **Step 3: Run to see them fail.**

- [ ] **Step 4: Implement** the worker, panel and content changes exactly as the Interfaces block says.
  - **The Start button handler in `panel.ts`:**

```ts
startButton.addEventListener("click", async () => {
  const binding = await currentBinding(); // from the dock state: tabId, origin
  if (!binding) return;
  const granted = await chrome.permissions.request({ origins: [`${binding.origin}/*`] });
  if (!granted) { showMessage(t(lang, "permission_needed")); return; }
  await chrome.runtime.sendMessage({ type: "start-fill", tabId: binding.tabId });
});
```

  - **The Stop button:** sends `stop-fill`. The worker forwards `{type:"stop"}` to the tab, clears the binding's `active` flag (it no longer re-injects), and patches the dock `status: "stopped"`.
  - **The dock's progress line:** computed in the panel from `fields` — done = `filled + already + changed_by_you`, mine = `your_turn + portal_error + mismatch`, total = all but `elsewhere`.
  - **The panel's layout:** wide when `status` is `ready` / `review` / `blocked`, slim while `filling`. Slim means a CSS class on `<main>` that hides the lists and shows only the progress line and next step.

- [ ] **Step 5: Build and run every extension test, then the Python suite's portal tests.**

Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_bundle.py -q && uv run pytest tests/portals/test_extension_e2e.py -m extension -q && POSTGRES_DB=elmify_copilot uv run pytest tests/portals -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 6: Update the CI job** (`.github/workflows/ci.yml`, extension job): build `dist-test` (`npm --prefix extension run build:test`) before the e2e run.

- [ ] **Step 7: Commit** — `"feat(extension): start from the dashboard, follow each page while the panel is open, stop and review"`.
