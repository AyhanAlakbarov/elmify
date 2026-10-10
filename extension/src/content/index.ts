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
import type { FillPacket, PacketField } from "../types.js";
import type { AddressVerdict } from "./address.js";
import { checkAddress, looksRejected, settle } from "./address.js";
import { alreadyCorrect, attachDocuments, fillVerified, readBack, retype } from "./fill.js";
import { detectChallenge, detectConfirmation, readStatus } from "./page_signals.js";
import { buildSnapshot } from "./snapshot.js";
import type { VerifiedEntry } from "./verify.js";
import { originMatches, verifyEntries } from "./verify.js";

async function ask<T>(message: unknown): Promise<T> {
  return (await chrome.runtime.sendMessage(message)) as T;
}

async function dock(patch: Record<string, unknown>): Promise<void> {
  await ask({ type: "dock", patch });
}

/** The portal-address control of the last run on this page, for the dock's
 *  "use my plain address" button. Page-lifetime only, like the run itself. */
let lastEmail: { applicationId: string; item: VerifiedEntry; plain: string } | null = null;

/** The student chose "use my plain address": an error we could not read.
 *  Their evidence about their own account only, like every report. */
async function usePlainAddress(): Promise<void> {
  if (!lastEmail) {
    await dock({ message: "Start filling this page first, then use this button again." });
    return;
  }
  const { applicationId, item, plain } = lastEmail;
  // Review M3: the control must still be the one the run verified -- on the
  // page, and still what verify.ts accepts for this entry -- and must hold the
  // plain address once typed. A re-rendered or locked field gets neither the
  // write nor a report, and the student is told so.
  const [again] = item.element?.isConnected ? verifyEntries([item.entry]) : [];
  const same = again?.ok === true && again.element === item.element;
  if (same) retype(item, plain);
  // Review R2 finding 2: the same settle the refusal check waits through --
  // a page that reverts the write a tick later (Vue's nextTick, a plain
  // setTimeout(0)) is invisible to a read-back taken before its timer fires.
  if (same && item.element) await settle(item.element);
  const typed = same && readBack([{ ...item, entry: { ...item.entry, value: plain } }]).length === 0;
  if (!typed) {
    await dock({
      message:
        "We could not type your plain address on this page. Type it into the email field " +
        "yourself, then submit with the portal's own button.",
    });
    return;
  }
  await ask({ type: "address", applicationId, event: "rejected", evidence: "student" });
  await dock({
    message: "We typed your plain address. Check it, then submit with the portal's own button.",
  });
}

async function run(applicationId: string, portalFormId: string): Promise<void> {
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

  const challenge = detectChallenge();
  if (challenge) {
    await ask({ type: "event", applicationId, kind: "CHALLENGE", detail: { kind: challenge.kind } });
    await dock({
      status: "blocked",
      message: "The portal is asking you to prove you are human. Do that, then start again.",
    });
    return;
  }

  await dock({ status: "filling", applicationId });
  const verified = verifyEntries(packet.entries);
  const refused = verified
    .filter((item) => !item.ok)
    .map((item) => ({ profile_field: item.entry.profile_field, reason: item.reason }));

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
  const swapped = address === "form" || address === "page" || address === "after_submit";
  lastEmail = email && plain ? { applicationId, item: email, plain } : null;

  const fetched: { filename: string; bytes: ArrayBuffer }[] = [];
  for (const document_ of packet.documents) {
    const result = await ask<{ ok: boolean; bytes?: ArrayBuffer }>({
      type: "document",
      path: document_.download_path,
    });
    if (result.ok && result.bytes) fetched.push({ filename: document_.filename, bytes: result.bytes });
  }
  const attachments = attachDocuments(fetched);

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
      .map((item) =>
        swapped && item === email ? { ...item, entry: { ...item.entry, value: plain } } : item,
      ),
  );
  await ask({
    type: "event",
    applicationId,
    kind: "READ_BACK",
    detail: { mismatches },
  });

  await dock({
    status: refused.length || mismatches.length || attachments.manual.length ? "blocked" : "done",
    filled,
    yourTurn: [
      ...refused.map((item) => ({ label: item.profile_field, reason: item.reason })),
      ...attachments.manual.map((filename) => ({ label: filename, reason: "attach_manually" })),
    ],
    mismatches: mismatches.map((item) => ({
      label: item.profile_field,
      expected: item.expected,
      actual: item.actual,
    })),
    // The one thing the student must be told every single time.
    message:
      (swapped
        ? "This portal would not take your tagged address, so we typed your plain one. "
        : "") +
      (address === "after_submit"
        ? "Submit the form again yourself, with the portal's own button."
        : "Check the form, then submit it yourself with the portal's own button."),
  });

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
        type: "status",
        applicationId,
        status: readStatus(),
      });
      void dock({ status: "done", message: "The portal confirmed it received your application." });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
}

// Guarded: the e2e suite injects this bundle into a plain fixture page with
// `page.add_script_tag`, which has no `chrome` extension API at all. An
// unconditional call here throws ReferenceError and aborts the whole IIFE
// before the test hooks below are ever defined -- every hook would silently
// not exist, and page.evaluate would fail on "not a function" for reasons
// unrelated to what each test actually checks. In a real content script
// `chrome` is always present, so this changes nothing in production.
if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "start") void run(message.applicationId, message.portalFormId);
    if (message?.type === "use_plain_address") void usePlainAddress();
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
(globalThis as Record<string, unknown>)["__tehsil_attach"] = attachDocuments;
// run() itself, so the e2e suite can drive the real order of operations
// rather than a re-implementation of it. It reaches the network through
// chrome.runtime.sendMessage exactly as production does; a test supplies its
// own stub for that and asserts on the messages the run actually sent.
(globalThis as Record<string, unknown>)["__tehsil_run"] = run;
(globalThis as Record<string, unknown>)["__tehsil_use_plain"] = usePlainAddress;
