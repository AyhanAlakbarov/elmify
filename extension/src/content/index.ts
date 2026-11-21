/**
 * The order of operations, and the order is the security model:
 *
 *   packet -> ORIGIN CHECK -> snapshot (once, if the server has no map) ->
 *   packet (again) -> origin check -> challenge check -> VERIFY -> skip what
 *   is already right -> fill -> read back -> report.
 *
 *   The origin is checked on BOTH paths, and the first one is the one that
 *   was missing. A first-encounter snapshot used to be built and posted from
 *   a page nothing had verified, because the only source of form_url was the
 *   packet and on that path there is no packet. The server's 424 now names
 *   the page (ext_api.py::packet), so the check runs before the form is
 *   described to anyone. A snapshot carries no value, so what this closes is
 *   sabotage of a learned FieldMap rather than exfiltration -- but a
 *   FieldMap aimed at the wrong controls is what verify.ts then has to catch
 *   for every student in the tenant.
 *
 * Verification is before the fill and not after it. After, it would be a
 * report; before, it is a guard.
 */
import type { FillPacket, PacketChoice, PacketField } from "../types.js";
import type { AddressVerdict } from "./address.js";
import { checkAddress, looksRejected, settle } from "./address.js";
import type { Attachment } from "./fill.js";
import type { CredentialPage } from "./credentials.js";
import { covered, credentialPage, entry, sameAddress, taggedFormOf, typeCredentials, usable } from "./credentials.js";
import { codeField, typeCode } from "./code.js";
import {
  alreadyCorrect,
  attachDocuments,
  fillVerified,
  onScreen,
  openerFor,
  readBack,
  retype,
  soleFileInput,
  soleMatch,
} from "./fill.js";
import { detectChallenge, detectConfirmation, readStatus } from "./page_signals.js";
import {
  GROUPS,
  REFUSED_TYPES,
  accessibleName,
  buildSnapshot,
  clip,
  headingFor,
} from "./snapshot.js";
import { savedCopy } from "./record.js";
import { contentLabels } from "./labels.js";
import { clearMarks, drawMarks, marksForTest, marksTextForTest } from "./marks.js";
import type { FieldRecord } from "./state.js";
import { applyPortalErrors, classify, watchStudentEdits } from "./state.js";
import type { VerifiedEntry } from "./verify.js";
import { originMatches, verifyEntries, visible } from "./verify.js";

declare const __ELMIFY_TEST__: boolean;

async function ask<T>(message: unknown): Promise<T> {
  return (await chrome.runtime.sendMessage(message)) as T;
}

async function dock(patch: Record<string, unknown>): Promise<void> {
  await ask({ type: "dock", patch });
}

/** The portal-address control of the last run on this page, for the dock's
 *  "use my plain address" button. Page-lifetime only, like the run itself. */
let lastEmail: {
  applicationId: string;
  item: VerifiedEntry;
  plain: string;
  /** Overrides the FieldMap re-check for a box no entry names (credentials.ts). */
  recheck?: () => boolean;
} | null = null;

/** The student chose "use my plain address": an error we could not read.
 *  Their evidence about their own account only, like every report. */
async function usePlainAddress(): Promise<void> {
  if (!lastEmail) {
    await dock({ message: "plain_not_started" });
    return;
  }
  const { applicationId, item, plain, recheck } = lastEmail;
  // Review M3: the control must still be the one the run verified -- on the
  // page, and still what verify.ts accepts for this entry -- and must hold the
  // plain address once typed. A re-rendered or locked field gets neither the
  // write nor a report, and the student is told so.
  const [again] = !recheck && item.element?.isConnected ? verifyEntries([item.entry]) : [];
  const same = recheck ? recheck() : again?.ok === true && again.element === item.element;
  if (same) retype(item, plain);
  // Review R2 finding 2: the same settle the refusal check waits through --
  // a page that reverts the write a tick later (Vue's nextTick, a plain
  // setTimeout(0)) is invisible to a read-back taken before its timer fires.
  if (same && item.element) await settle(item.element);
  const typed = same && readBack([{ ...item, entry: { ...item.entry, value: plain } }]).length === 0;
  if (!typed) {
    await dock({ message: "plain_not_typed" });
    return;
  }
  await ask({ type: "address", applicationId, event: "rejected", evidence: "student" });
  await dock({ message: "plain_typed" });
}

type DockChoice = { filename: string; options: { selector: string; description: string }[] };

/** The choices of the last run on this page, and its documents line. A pick
 *  is honoured only for a box the packet offered and the run showed. */
let pendingChoices = new Map<string, { choice: PacketChoice; dock: DockChoice }>();
let documentRows: { filename: string; state: "attached" | "manual"; note?: string }[] = [];
/** Every box this run put a document into: never offered to a choice again. */
let filledBoxes = new Set<HTMLInputElement>();

/** The boxes of a choice the student can see, each described by the page's own
 *  words: the section heading and the box's name or its row's visible text. */
function dockChoice(choice: PacketChoice): DockChoice {
  return {
    filename: choice.filename,
    options: choice.selectors.flatMap((selector) => {
      const input = soleFileInput(selector);
      const opener = input ? openerFor(input) : null;
      if (!input || filledBoxes.has(input) || !opener || !onScreen(opener)) return [];
      const name = accessibleName(input) || (input.closest<HTMLElement>(GROUPS)?.innerText ?? "");
      const description = clip([headingFor(input), name].filter(Boolean).join(" · "), 120);
      return [{ selector, description }];
    }),
  };
}

/** The worker sends a document as base64: sendMessage is JSON, and an
 *  ArrayBuffer arrives as {} (final review I6). */
function fromBase64(base64: unknown): ArrayBuffer | null {
  if (typeof base64 !== "string") return null;
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0)).buffer;
}

/** Re-offer every open choice against the boxes still free. One left with
 *  fewer than two is nothing to choose between, and code does not take the
 *  box left over either: the student attaches it. */
function settleChoices(): void {
  for (const [filename, pending] of pendingChoices) {
    const shown = dockChoice(pending.choice);
    if (shown.options.length >= 2) {
      pending.dock = shown;
      continue;
    }
    pendingChoices.delete(filename);
    documentRows = [...documentRows, { filename, state: "manual" }];
  }
}

function manualCount(): number {
  return documentRows.filter((row) => row.state === "manual").length + pendingChoices.size;
}

/** The student picked a box in the panel. */
async function attachChoice(filename: string, selector: string): Promise<boolean> {
  const pending = pendingChoices.get(filename);
  if (!pending || !pending.dock.options.some((option) => option.selector === selector)) {
    return false;
  }
  const thisRun = current;
  pendingChoices.delete(filename); // one answer per choice, even for a double press
  const result = await ask<{ ok: boolean; base64?: string }>({
    type: "document",
    path: pending.choice.download_path,
  }).catch(() => null);
  if (thisRun !== current) return false; // Stop arrived while we fetched: attach nothing
  const bytes = result?.ok ? fromBase64(result.base64) : null;
  const input = soleFileInput(selector);
  const free = input !== null && !filledBoxes.has(input); // another pick took it meanwhile
  let placed = false;
  if (!bytes || !free) {
    pendingChoices.set(filename, pending); // still theirs to answer
  } else {
    const outcome = attachDocuments(
      [{ filename, bytes, selector, kind: pending.choice.kind, chosen: true }],
      filledBoxes,
    );
    placed = outcome.attached.length > 0;
    documentRows = [...documentRows, { filename, state: placed ? "attached" : "manual" }];
  }
  settleChoices();
  if (lastRun) await dock(lastRun.patch()); // the whole dock, status recomputed
  return placed;
}

function samePage(formUrl: string): boolean {
  // "/apply" and "/apply/" are one page to every portal we have met.
  const path = (pathname: string) => pathname.replace(/\/+$/, "");
  try {
    const a = new URL(formUrl);
    return a.origin + path(a.pathname) === location.origin + path(location.pathname);
  } catch {
    return false;
  }
}

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
 *  was before the platform held passwords. The password lives only in `reply`
 *  and the page's own boxes: never stored, docked, reported or logged. */
async function signIn(
  applicationId: string,
  page: CredentialPage,
  plain: string,
  stale: () => boolean,
  challenge: boolean,
): Promise<void> {
  const boxes = [page.identifier, ...page.passwords];
  // The portal sent the sign-up back after Submit, refusing the tagged address
  // we typed: it still holds that address, its passwords are cleared, and it
  // shows the refusal. Every other non-empty box is the student's own text,
  // and asking first would have the server mint a password the portal never
  // gets. The came-back guess is confirmed below against the account's own
  // username before anything is typed.
  const cameBack =
    page.kind === "signup" &&
    Boolean(plain) &&
    page.passwords.every((box) => box.value === "") &&
    taggedFormOf(page.identifier.value, plain) &&
    looksRejected(page.identifier);
  // A login whose address box the portal or browser remembered: asking mints
  // nothing (only a sign-up does), and only the password is typed, once the
  // remembered address proves to be this account's.
  const remembered =
    page.kind === "login" && page.passwords.every((box) => box.value === "") && page.identifier.value !== "";
  if (!cameBack && !remembered && boxes.some((box) => box.value !== "")) {
    await dock({ status: "login", message: "log_in" });
    return;
  }
  const reply = await ask<{ ok: boolean; code?: string; username?: unknown; password?: unknown }>({
    type: "portal-login",
    applicationId,
    page: page.kind,
    host: location.hostname, // not .host: the worker compares a hostname, no port
    ...(page.maxLength ? { max_length: page.maxLength } : {}),
    // The server only reads on this: a password made now is one the portal never got.
    ...(cameBack ? { came_back: true } : {}),
  }).catch(() => null);
  if (stale()) return; // never type after the student pressed Stop
  if (reply?.code === "browser_unconfirmed") {
    // This browser was paired without the student's password: the server
    // holds portal passwords back until they allow it on Portal logins.
    await dock({ status: "login", message: "browser_unconfirmed" });
    return;
  }
  if (reply?.code === "login_not_accepted") {
    // We typed one and the portal is back at its login: the password we keep is
    // not this account's. Type nothing; the student logs in and hands it over.
    await dock({ status: "login", message: "login_not_accepted" });
    return;
  }
  const login =
    reply?.ok && typeof reply.username === "string" && typeof reply.password === "string"
      ? { username: reply.username, password: reply.password }
      : null;
  const ours = cameBack
    ? login?.username === page.identifier.value
    : !remembered || (login !== null && sameAddress(login.username, page.identifier.value));
  if (!login || !ours || !typeCredentials(page, login.username, login.password)) {
    // Some boxes may hold it now (a later box refused its value): that is a
    // typed login for the worker's lockout guard. Typed none of what we were
    // handed: say so, and the guard forgets the hand-out.
    const partly = login !== null && page.passwords.some((box) => box.value === login.password);
    const message = partly ? "log_in_typed" : login ? "log_in_untyped" : "log_in";
    await dock({ status: "login", message });
    return;
  }
  let verdict: AddressVerdict | null = null;
  if (page.kind === "signup") {
    // The address typed into a sign-up IS the registration (ext_api.address_report).
    const item = entry(page.identifier, login.username, "contact.email");
    verdict = plain ? await checkAddress(item, plain, cameBack) : "kept";
    if (stale()) return;
    // The dock's "use my plain address" button. No FieldMap entry names this
    // box, so the re-check is the one credentialPage used to pick it.
    lastEmail = plain
      ? { applicationId, item, plain, recheck: () => page.identifier.isConnected && usable(page.identifier) }
      : null;
    if (verdict === "form" || verdict === "page" || verdict === "after_submit") {
      await ask({ type: "address", applicationId, event: "rejected", evidence: verdict });
    } else if (verdict === "kept") {
      await ask({ type: "address", applicationId, event: "given" });
    }
  }
  if (stale()) return;
  // A new account's portal mails a code or a link once Register is pressed.
  if (page.kind === "signup") await ask({ type: "await-code", applicationId });
  // "log_in_typed" stays the dock's word for a typed login, CAPTCHA or not;
  // the CAPTCHA is said in the panel after it.
  const typed =
    page.kind === "login" ? "log_in_typed" : verdict === "after_submit" ? "submit_again" : "sign_up_typed";
  await dock({ status: "login", message: typed });
  if (challenge) await dock({ message: "typed_captcha" });
}

/** The current run: its listeners and observers die together on Stop or a new run. */
let current: { abort: AbortController; confirmation: MutationObserver | null } = {
  abort: new AbortController(),
  confirmation: null,
};

/** Take everything this page holds of ours down: marks, observers, edit listeners. */
function stop(): void {
  current.abort.abort();
  current.confirmation?.disconnect();
  current = { abort: new AbortController(), confirmation: null }; // a run holding the old one is stale
  lastRun = null;
  lastEmail = null; // the use-plain button must not type into a stopped page (final review M4)
  pendingChoices = new Map();
  documentRows = [];
  filledBoxes = new Set();
  clearMarks();
}

function needsYou(records: Map<string, FieldRecord>): boolean {
  return Array.from(records.values()).some((r) =>
    ["your_turn", "portal_error", "mismatch"].includes(r.view.state),
  );
}

interface TypedAnswer { selector: string; kind: "hint" | "changed"; value: string }

/** What the student typed into boxes the packet named, for the answers channel
 *  only: never into the dock patch or the marks. Capped like the server (100
 *  answers, 500 characters): an over-long value is left out rather than
 *  refusing the whole batch. */
function typedAnswers(records: Map<string, FieldRecord>): TypedAnswer[] {
  const out: TypedAnswer[] = [];
  for (const record of records.values()) {
    const element = record.element;
    if (!element || !record.selector || record.view.state !== "changed_by_you") continue;
    // Defence in depth, unreachable today: verify.ts refuses a password box as
    // an entry and the hint loop skips REFUSED_TYPES, so no record holds one.
    // Checked before the value is read, so a future path that adds one still
    // never sends a password. A file box's value is a local path, not an answer.
    if (
      element instanceof HTMLInputElement &&
      ["password", "file"].includes(element.type.toLowerCase())
    ) {
      continue;
    }
    if (
      !(element instanceof HTMLInputElement) &&
      !(element instanceof HTMLTextAreaElement) &&
      !(element instanceof HTMLSelectElement)
    ) {
      continue;
    }
    const value = element.value;
    if (!value || value.length > 10000) continue;
    out.push({ selector: record.selector, kind: record.hint ? "hint" : "changed", value });
    if (out.length === 100) break;
  }
  return out;
}

/** The student pressed "I have checked this page": send what they typed. */
function sendAnswers(): void {
  if (!lastRun) return;
  const answers = lastRun.answers();
  if (answers.length > 0) {
    void ask({ type: "answers", applicationId: lastRun.applicationId, answers });
  }
}

/** "review" when nothing on this page needs the student, else "blocked". */
function reviewStatus(records: Map<string, FieldRecord>, manualDocuments: number): "review" | "blocked" {
  return needsYou(records) || manualDocuments > 0 ? "blocked" : "review";
}

/** A portal shows its errors after an in-page validation, not only on reload.
 *  Debounced so a busy page cannot spin it; our own marks redraw only on change.
 *  Ends with the run: stop() aborts `signal`, which disconnects it. */
function watchPortalErrors(records: Map<string, FieldRecord>, report: () => void, signal: AbortSignal): void {
  let first = 0; // when the pending burst began: constant churn still fires every 500 ms
  let timer: number | undefined;
  const observer = new MutationObserver(() => {
    clearTimeout(timer);
    const now = Date.now();
    if (!first) first = now;
    const delay = Math.max(0, Math.min(150, first + 500 - now));
    timer = window.setTimeout(() => {
      first = 0;
      if (applyPortalErrors(records)) report();
    }, delay);
  });
  signal.addEventListener("abort", () => {
    observer.disconnect();
    clearTimeout(timer);
  });
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    attributes: true,
    characterData: true,
    attributeFilter: ["aria-invalid", "class", "aria-describedby", "aria-errormessage", "style", "hidden"],
  });
}

/** The finished run on this document, so a reopened panel (a resume) can be
 *  re-told what is on the page without filling, or reporting a fill, twice. */
let lastRun: {
  draw: () => void;
  patch: () => Record<string, unknown>;
  applicationId: string;
  answers: () => TypedAnswer[];
  useOffer: (key: string, value: string) => boolean;
} | null = null;

function resumeRun(): boolean {
  if (!lastRun) return false;
  lastRun.draw();
  void dock(lastRun.patch());
  return true;
}

/** The only document kinds the panel has a reason string for; any other kind
 *  the server might send falls back to the generic "From your verified facts". */
const DOCUMENT_KINDS: ReadonlySet<string> = new Set(["passport", "diploma", "certificate"]);

async function run(
  applicationId: string,
  portalFormId: string,
  language = "en",
  origin = location.origin,
  relearned = false,
): Promise<void> {
  // The worker names the origin it bound. A page on any other origin -- the
  // tab moved between the worker's check and the injection -- asks nothing.
  if (origin !== location.origin) return;
  stop(); // a new run replaces the last one on this page
  const thisRun = current;
  const stale = () => thisRun !== current; // Stop, or a newer start, arrived while we waited
  let response = await ask<{
    ok: boolean;
    code?: string;
    packet?: FillPacket;
    form_url?: string;
  }>({
    type: "packet",
    applicationId,
  });

  if (!response.ok && response.code === "no_field_map") {
    // Before describing this form to the server, establish that it IS the
    // form. An absent form_url refuses too: a server too old to send one
    // cannot tell us what we are looking at, and guessing is the behaviour
    // this check replaces.
    if (!response.form_url || !originMatches(response.form_url)) {
      await dock({ status: "blocked", message: "wrong_page" });
      return;
    }
    // First time anyone in this agency has met this form. The snapshot is
    // value-free; the server learns from it and scopes the map to this tenant.
    const learned = await ask<{ ok: boolean; code?: string }>({
      type: "snapshot",
      portalFormId,
      applicationId,
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
  if (stale()) return;

  if (!onFormPage(packet.entries)) {
    const credentials = credentialPage();
    if (credentials) {
      // Typed anyway: the student proves they are human and presses the button.
      const challenge = detectChallenge();
      if (challenge) {
        await ask({ type: "event", applicationId, kind: "CHALLENGE", detail: { kind: challenge.kind } });
      }
      await signIn(applicationId, credentials, packet.plain_email ?? "", stale, challenge !== null);
      return;
    }
    if (codeField()) {
      // The portal sent a code by email: the worker watches the inbox for it
      // and types it here when it comes (spec §6). Nothing to fill meanwhile.
      const watch = await ask<{ ok: boolean; watching?: boolean }>({ type: "await-code", applicationId }).catch(
        () => null,
      );
      // No inbox to read: the worker has already told the student to type it.
      if (watch?.watching) await dock({ message: "waiting_code" });
      return;
    }
    const passwords = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="password"]'));
    if (passwords.some(visible)) {
      // A password page whose address box we cannot name: the student's. A
      // cookie notice over the boxes is worth saying: closing it lets us type.
      await dock({ status: "login", message: passwords.some(covered) ? "log_in_covered" : "log_in" });
      return;
    }
  }

  const challenge = detectChallenge();
  if (challenge) {
    await ask({ type: "event", applicationId, kind: "CHALLENGE", detail: { kind: challenge.kind } });
    await dock({ status: "blocked", message: "captcha" });
    return;
  }

  await dock({ status: "filling", applicationId });
  if (stale()) return; // never type after the student pressed Stop
  const verified = verifyEntries(packet.entries);
  // A form the portal changed (spec 10): most of the map's controls are gone
  // from the very page the map was learned for. Describe the page again, once
  // per run; a refusal (rate limit, nothing mappable) leaves the run going with
  // every missing field red.
  const gone = verified.filter((item) => !item.ok && item.reason === "no_such_control").length;
  const hints = packet.hints ?? [];
  const goneHints = hints.filter((hint) => !soleMatch(hint.selector)).length;
  const totalMapped = verified.length + hints.length;
  const totalGone = gone + goneHints;
  if (!relearned && samePage(packet.form_url) && totalGone * 2 > totalMapped) {
    const learned = await ask<{ ok: boolean; code?: string }>({
      type: "snapshot",
      portalFormId,
      applicationId,
      snapshot: buildSnapshot(document),
    });
    if (learned.ok && !stale()) return run(applicationId, portalFormId, language, origin, true);
  }
  const refused = verified
    .filter((item) => !item.ok)
    .map((item) => ({ profile_field: item.entry.profile_field, reason: item.reason }));

  const skip = alreadyCorrect(verified, packet.equivalences ?? {});
  const email = verified.find(
    (item) => item.ok && item.element && item.entry.profile_field === "contact.email",
  );
  const plain = packet.plain_email ?? "";
  // Read before typing: the page the portal sent back after Submit.
  const cameBack = Boolean(
    email?.element && plain && skip.has("contact.email") && looksRejected(email.element),
  );
  const { filled, theirs } = fillVerified(verified, skip);
  const address: AddressVerdict | null =
    email && plain ? await checkAddress(email, plain, cameBack) : null;
  if (stale()) return; // Stop arrived while the address settled
  const swapped = address === "form" || address === "page" || address === "after_submit";
  lastEmail = email && plain ? { applicationId, item: email, plain } : null;

  const fetched: Attachment[] = [];
  const notes = new Map<string, string>(); // filename -> reason code; panel only
  const unavailable: string[] = []; // the student attaches these (final review M1)
  for (const document_ of packet.documents) {
    const result = await ask<{ ok: boolean; base64?: string }>({
      type: "document",
      path: document_.download_path,
    }).catch(() => null);
    if (document_.note) notes.set(document_.filename, document_.note);
    const bytes = result?.ok ? fromBase64(result.base64) : null;
    if (bytes) {
      fetched.push({
        filename: document_.filename,
        bytes,
        selector: document_.selector ?? null,
        kind: document_.kind,
        type: document_.content_type ?? "application/pdf",
      });
    } else unavailable.push(document_.filename);
  }
  if (stale()) return; // Stop arrived while the worker fetched (final review I3)
  const attachments = attachDocuments(fetched, filledBoxes);
  attachments.manual.push(...unavailable);

  await ask({
    type: "event",
    applicationId,
    kind: "FILL",
    detail: { filled, refused, attachments, field_map_version: packet.field_map_version },
  });

  if (swapped) {
    await ask({ type: "address", applicationId, event: "rejected", evidence: address });
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
      .filter((item) => !theirs.has(item.entry.profile_field))
      .map((item) =>
        swapped && item === email ? { ...item, entry: { ...item.entry, value: plain } } : item,
      ),
    packet.equivalences ?? {},
  );
  await ask({
    type: "event",
    applicationId,
    kind: "READ_BACK",
    detail: { mismatches },
  });

  if (stale()) return;
  for (const choice of packet.choices ?? []) {
    const unshown = { filename: choice.filename, options: [] };
    pendingChoices.set(choice.filename, { choice, dock: unshown });
  }
  // A file's prepare note rides on its own row (panel only).
  const noted = (filename: string) => (notes.has(filename) ? { note: notes.get(filename) } : {});
  documentRows = [
    ...attachments.attached.map((a) => ({ filename: a.filename, state: "attached" as const, ...noted(a.filename) })),
    ...attachments.manual.map((filename) => ({ filename, state: "manual" as const, ...noted(filename) })),
  ];
  settleChoices(); // offers each choice its free, visible boxes; fewer than two is manual
  const records = classify(verified, filled, skip, mismatches, theirs, samePage(packet.form_url));
  // Hints: the map's guesses and the fields this student holds no fact for.
  // One red row each, on exactly one visible, typeable control; never typed.
  for (const hint of packet.hints ?? []) {
    if (records.has(hint.profile_field)) continue; // an entry for the field wins
    const element = soleMatch(hint.selector); // malformed or ambiguous marks nothing
    if (!(element instanceof HTMLElement) || !visible(element)) continue;
    if (REFUSED_TYPES.has((element.getAttribute("type") ?? "").toLowerCase())) continue;
    const control = element as HTMLInputElement;
    if (control.disabled || control.readOnly) continue;
    const held = control.value ?? "";
    records.set(hint.profile_field, {
      view: {
        key: hint.profile_field,
        // A value already on the page is "check this", never "changed by you".
        state: held ? "mismatch" : "your_turn",
        reason: held
          ? "held_other"
          : hint.reason === "unsure"
            ? "our_guess"
            : hint.offer
              ? "offer"
              : hint.expired_on
                ? "document_expired"
                : hint.upload_kind
                  ? "upload_once"
                  : "no_fact",
        placed: false,
      },
      element,
      selector: hint.selector,
      hint: true,
    });
  }
  // Typed back from the student's own earlier answer (decision B): labelled so.
  const fromAnswer = new Set(
    packet.entries.filter((e) => e.from_answer === true).map((e) => e.profile_field),
  );
  for (const key of fromAnswer) {
    const view = records.get(key)?.view;
    if (view && (view.state === "filled" || view.state === "already")) {
      view.reason = "from_your_answer";
    }
  }
  // Proven by the student's own document (spec 2026-10-12 §7.4): marked so.
  const fromDocument = new Map(
    packet.entries
      .filter((e) => DOCUMENT_KINDS.has(e.source_kind ?? "") && e.from_answer !== true)
      .map((e) => [e.profile_field, e.source_kind as string]),
  );
  for (const [key, source] of fromDocument) {
    const view = records.get(key)?.view;
    if (view && (view.state === "filled" || view.state === "already")) {
      view.reason = `from_${source}`;
    }
  }
  // The next-step chip, while any field needs the student (final review M5).
  const draw = () =>
    drawMarks(
      records,
      contentLabels(language, needsYou(records) ? "answer" : null, fromAnswer, fromDocument),
      report,
    );
  const report = () => {
    draw(); // a "changed by you" or a lost mark redraws before the panel hears of it
    void dock({
      fields: Array.from(records.values(), (r) => r.view),
      status: reviewStatus(records, manualCount()),
    });
  };
  /** The student tapped Use in our panel; the worker confirmed the fact and sends
   *  the server's value. One box, through verify -> fill -> read back, exactly as
   *  an entry: judged against every entry's field (a label fitting two of the
   *  packet's fields is ambiguous_name, as in the run), never over a value
   *  already there, never into a box the packet did not offer this value for. */
  const useOffer = (key: string, value: string): boolean => {
    if (stale()) return false;
    const record = records.get(key);
    const hint = (packet.hints ?? []).find((h) => h.profile_field === key && h.offer);
    if (!record?.hint || !hint?.offer) return false;
    const entry: PacketField = {
      selector: hint.selector, method: hint.offer.method, value, profile_field: key,
    };
    const checked = verifyEntries([...packet.entries, entry]).slice(-1);
    const { filled } = fillVerified(checked, new Set());
    const mismatches = readBack(checked, packet.equivalences ?? {});
    if (!filled.includes(key)) return false;
    // The same classification a normal entry gets: a read-back mismatch is
    // "check this", not a live offer over a box that now holds a value.
    const view = classify(checked, filled, new Set(), mismatches, new Set()).get(key)?.view;
    if (!view) return false;
    const source = hint.offer.source_kind;
    record.view = view;
    record.hint = false;
    if (view.state === "filled" && DOCUMENT_KINDS.has(source)) {
      view.reason = `from_${source}`;
      fromDocument.set(key, source);
    }
    report();
    return view.state === "filled";
  };
  watchStudentEdits(records, thisRun.abort.signal, () => {
    applyPortalErrors(records);
    report();
  });
  applyPortalErrors(records);
  watchPortalErrors(records, report, thisRun.abort.signal);
  draw();

  // Live, not a copy taken now: a resume redraw, or a pick in the panel, must
  // never re-send an answered choice or a stale documents line.
  const finalPatch = () => ({
    status: reviewStatus(records, manualCount()),
    fields: Array.from(records.values(), (r) => r.view),
    documents: documentRows,
    choices: Array.from(pendingChoices.values(), (pending) => pending.dock),
    notes: packet.notes ?? [],
    // The one thing the student must be told every single time. A code: the
    // panel says it in the student's language (final review I2).
    message: address === "after_submit" ? "submit_again" : swapped ? "swapped_plain" : "check_submit",
  });
  // Set before the await: a Stop or a newer run during it clears it in stop().
  if (!stale()) {
    lastRun = { draw, patch: finalPatch, applicationId, answers: () => typedAnswers(records), useOffer };
  }
  await dock(finalPatch());

  // The student is about to press Submit. A confirmation appears after a
  // navigation or a re-render, so watch rather than check once. Disconnected
  // after the first hit: one SUBMITTED row per run, and the observer must not
  // outlive the thing it is observing.
  const markers = packet.confirmation_markers ?? [];
  if (markers.length > 0 && !stale()) {
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
        type: "status",
        applicationId,
        status: readStatus(),
      });
      void dock({ status: "done", message: "confirmed" });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    thisRun.confirmation = observer;
  }
}

// Guarded: the e2e suite injects this bundle into a plain fixture page with
// `page.add_script_tag`, which has no `chrome` extension API at all. An
// unconditional call here throws ReferenceError and aborts the whole IIFE
// before the test hooks below are ever defined -- every hook would silently
// not exist, and page.evaluate would fail on "not a function" for reasons
// unrelated to what each test actually checks. In a real content script
// `chrome` is always present, so this changes nothing in production.
//
// The worker injects this file again on a resume, into a page that may already
// run it. The flag lives in the content script's own world, so the first copy
// keeps listening and a second copy stays inert.
const LISTENING = "__elmify_listening";
if (
  typeof chrome !== "undefined" &&
  chrome.runtime?.onMessage &&
  !(globalThis as Record<string, unknown>)[LISTENING]
) {
  (globalThis as Record<string, unknown>)[LISTENING] = true;
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "choice:attach") {
      const { filename, selector } = message as { filename?: unknown; selector?: unknown };
      if (typeof filename !== "string" || typeof selector !== "string") return false;
      void attachChoice(filename, selector).then((ok) => sendResponse({ ok }));
      return true; // the answer is asynchronous
    }
    if (message?.type === "offer:fill") {
      // From the worker only (a page cannot reach this listener), after the
      // server confirmed the fact. The key and value are checked against our
      // own packet inside useOffer.
      const ok = typeof message.key === "string" && typeof message.value === "string"
        && lastRun?.useOffer(message.key, message.value) === true;
      sendResponse({ ok });
      return false;
    }
    if (message?.type === "record") {
      // Bench mode (plan 6): the operator's walk. Structure only, no values;
      // the server redacts the copy's text again before it keeps it.
      // The origin is the page's own, read now: the worker checks it again
      // after its awaits, so a tab that navigated meanwhile is not recorded.
      sendResponse({
        origin: location.origin,
        snapshot: buildSnapshot(document),
        html: savedCopy(document),
      });
      return false;
    }
    if (message?.type === "start") {
      const origin = typeof message.origin === "string" ? message.origin : "";
      if (message.resume === true && origin === location.origin && resumeRun()) return false;
      void run(message.applicationId, message.portalFormId, message.language, origin);
    }
    if (message?.type === "stop") stop();
    if (message?.type === "review:open") sendAnswers();
    if (message?.type === "use_plain_address") void usePlainAddress();
    if (message?.type === "type-code") {
      // Answered synchronously: typeCode does no waiting.
      sendResponse({ typed: typeCode(String(message.code ?? ""), String(message.origin ?? "")) });
    }
    return false;
  });
}

// Test hooks. The e2e suite drives the real bundle rather than a re-
// implementation of it, and these are the smallest surface that allows that.
// They read the page and return verdicts; none of them reaches the network,
// holds a credential, or is reachable from a portal page's own script when the
// extension injects this file itself (the content script runs in an isolated
// world, so `globalThis` there is not the page's `window`).
// A VerifiedEntry carries an HTMLElement, which page.evaluate cannot return --
// it serializes to nothing and the assertion reads a silent {}. The hook
// projects each verdict to the three fields the tests assert on instead.
(globalThis as Record<string, unknown>)["__elmify_verify"] = (entries: PacketField[]) =>
  verifyEntries(entries).map((item: VerifiedEntry) => ({
    profile_field: item.entry.profile_field,
    ok: item.ok,
    reason: item.reason,
  }));
(globalThis as Record<string, unknown>)["__elmify_fill"] = (entries: PacketField[]) =>
  fillVerified(verifyEntries(entries), new Set()).filled;
(globalThis as Record<string, unknown>)["__elmify_detect_challenge"] = detectChallenge;
(globalThis as Record<string, unknown>)["__elmify_snapshot"] = () => buildSnapshot(document);
(globalThis as Record<string, unknown>)["__elmify_attach"] = attachDocuments;
// run() itself, so the e2e suite can drive the real order of operations
// rather than a re-implementation of it. It reaches the network through
// chrome.runtime.sendMessage exactly as production does; a test supplies its
// own stub for that and asserts on the messages the run actually sent.
(globalThis as Record<string, unknown>)["__elmify_run"] = run;
(globalThis as Record<string, unknown>)["__elmify_use_plain"] = usePlainAddress;
if (__ELMIFY_TEST__) {
  (globalThis as Record<string, unknown>)["__elmify_code_field"] = () => codeField()?.id ?? null;
  // What credentials.ts read: page kind, the address box's id, the password box
  // count -- never a box's value.
  (globalThis as Record<string, unknown>)["__elmify_credential_page"] = () => {
    const found = credentialPage();
    return (
      found && {
        kind: found.kind,
        identifier: found.identifier.id,
        passwords: found.passwords.length,
        maxLength: found.maxLength ?? null,
      }
    );
  };
  (globalThis as Record<string, unknown>)["__elmify_offer"] = (key: string, value: string) =>
    lastRun?.useOffer(key, value) ?? false;
  (globalThis as Record<string, unknown>)["__elmify_marks"] = marksForTest;
  (globalThis as Record<string, unknown>)["__elmify_marks_text"] = marksTextForTest;
  (globalThis as Record<string, unknown>)["__elmify_choice"] = attachChoice;
  (globalThis as Record<string, unknown>)["__elmify_review"] = sendAnswers;
  (globalThis as Record<string, unknown>)["__elmify_saved_copy"] = () => savedCopy(document);
  (globalThis as Record<string, unknown>)["__elmify_read_back"] = (
    entries: PacketField[],
    equivalences: Record<string, string>,
  ) => {
    const verified = verifyEntries(entries);
    return {
      verdicts: verified.map((item) => ({
        profile_field: item.entry.profile_field,
        ok: item.ok,
        reason: item.reason,
      })),
      mismatches: readBack(verified, equivalences),
    };
  };
}
