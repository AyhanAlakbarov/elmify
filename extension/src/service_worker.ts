import {
  ExtError,
  checkMailbox,
  dashboardOrigin,
  deviceToken,
  fetchActions,
  fetchPacket,
  fetchRegistration,
  forgetPacket,
  loadPacket,
  pairFromTab,
  postActionResult,
  postAddress,
  postEvent,
  postRegistrationAnswer,
  postSnapshot,
  postStatus,
  revoke,
  storePacket,
} from "./api.js";

/** One alarm per registration being watched. An alarm, not setTimeout: the
 *  worker is unloaded when idle and a timer would die with it. */
const REGISTRATION_ALARM = "registration:";

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
  // Once paired, this installation belongs to ONE dashboard, and the check
  // belongs HERE rather than beside the token check below. The old order asked
  // Chrome for a host permission first, was granted it, and only then found the
  // token and returned -- leaving the extension holding a standing permission
  // on a site it will never talk to. revoke() clears the stored origin, so
  // unpairing still lets the student pair somewhere else.
  const paired = await dashboardOrigin();
  if (paired && paired !== origin) return;
  const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
  if (!granted) return;
  await chrome.sidePanel.open({ tabId: tab.id });
  if (await deviceToken()) return;
  await pairFromTab(tab.id, origin);
});

/** Merge a patch into the dock's stored state and broadcast it to any open
 *  panel. A plain function call, never chrome.runtime.sendMessage — the
 *  service worker cannot message its own listener; Chrome delivers
 *  sendMessage only to OTHER extension contexts, and calling it here either
 *  silently no-ops (panel open) or throws unhandled (panel closed, the
 *  normal case), which used to abort the rest of the caller's work. */
async function patchDock(patch: Record<string, unknown>): Promise<Record<string, unknown>> {
  const stored = await chrome.storage.session.get("dock");
  const next = { ...(stored["dock"] ?? {}), ...patch };
  await chrome.storage.session.set({ dock: next });
  chrome.runtime.sendMessage({ type: "dock:state", state: next }).catch(() => {});
  return next;
}

/** Take down the registration question -- but only the one for this
 *  application: a second registration's question may be on screen by now
 *  (final review M1). */
async function clearRegistration(applicationId: string): Promise<void> {
  const stored = await chrome.storage.session.get("dock");
  const dock = (stored["dock"] ?? {}) as { registration?: { applicationId?: string } | null };
  if (dock.registration?.applicationId === applicationId) await patchDock({ registration: null });
}

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

/** Application ids are UUIDs (apps/portals/models.py) interpolated,
 *  unescaped, into every id-addressed route's path below. Checked once, here
 *  -- a crafted string such as "../actions/<id>/result" would otherwise
 *  widen an id-addressed call into an unrelated route, carried on the
 *  device's own token (fix round 1, M1). */
const APPLICATION_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// The closed vocabularies ext_api.py's own models check server side
// (_AddressReport.event, _REJECTION_EVIDENCE, _RegistrationAnswer.arrived).
// Checked again here so a malformed value never leaves the worker at all.
const KNOWN_EVENTS = new Set(["given", "rejected"]);
const KNOWN_EVIDENCE = new Set(["form", "page", "after_submit", "student"]);
const KNOWN_ARRIVED = new Set(["tagged", "plain", "none"]);

/** Only the dock page -- our own side panel -- may answer for the student.
 *  A content script always carries a `sender.tab`; the panel never does, and
 *  its `sender.url` is this extension's own panel.html, not a page's. */
const PANEL_URL = chrome.runtime.getURL("panel.html");
function fromDock(sender: chrome.runtime.MessageSender): boolean {
  return !sender.tab && sender.url === PANEL_URL;
}

/**
 * The worker's one message-boundary check (fix round 1, I1 + M1). Every case
 * below runs only after this returns null, so a check belongs here and is
 * never repeated inside a handler.
 *
 * `registration:answer` speaks for the student -- a compromised portal
 * renderer running as a content script must not be able to post one.
 * `address` is the opposite: only a content script witnessed anything on a
 * page, so only one may report it.
 */
function messageRefusal(
  message: Record<string, unknown>,
  sender: chrome.runtime.MessageSender,
): string | null {
  const applicationId = message["applicationId"];
  if (applicationId !== undefined) {
    if (typeof applicationId !== "string" || !APPLICATION_ID_RE.test(applicationId)) {
      return "invalid_message";
    }
  }
  if (message["type"] === "address") {
    if (!sender.tab) return "untrusted_sender";
    if (!KNOWN_EVENTS.has(message["event"] as string)) return "invalid_message";
    const evidence = message["evidence"];
    if (evidence !== undefined && !KNOWN_EVIDENCE.has(evidence as string)) {
      return "invalid_message";
    }
  }
  if (message["type"] === "registration:answer") {
    if (!fromDock(sender)) return "untrusted_sender";
    if (!KNOWN_ARRIVED.has(message["arrived"] as string)) return "invalid_message";
  }
  return null;
}

// THE message listener. Tasks 8, 9, 10, 11 and 12 add their cases INSIDE it.
// A second addListener returning true for the same message is a race over one
// sendResponse, and the loser throws where nobody sees it.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const refusal = messageRefusal(message ?? {}, sender);
  if (refusal) {
    sendResponse({ ok: false, code: refusal });
    return false;
  }
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
        // form_url only, and only from the server's own refusal body: the
        // content script needs it to check this page's origin before it
        // describes the form to anyone.
        const formUrl = error instanceof ExtError ? error.detail["form_url"] : undefined;
        sendResponse({
          ok: false,
          code,
          ...(typeof formUrl === "string" ? { form_url: formUrl } : {}),
        });
      }
    })();
    // Keep the message channel open for the async reply above.
    return true;
  }
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
  if (message?.type === "status") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      try {
        await postStatus(origin, message.applicationId, message.status);
        sendResponse({ ok: true });
      } catch (error) {
        sendResponse({ ok: false, code: error instanceof ExtError ? error.code : "request_failed" });
      }
    })();
    return true;
  }
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
          await forgetPacket(message.applicationId);
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
        // 409 no_registration: nothing is left to answer -- the student chose
        // their plain address since the question went up (final review M1).
        if (code === "no_registration") await clearRegistration(message.applicationId);
        const messages: Record<string, string> = {
          invalid_sender: "That does not look like an email address. Copy the sender from the email.",
          no_registration: "Nothing to answer any more: this portal uses your plain address.",
        };
        await patchDock({
          message: messages[code] ?? "We could not save your answer. Try again in a minute.",
        });
        sendResponse({ ok: false, code });
      }
    })();
    return true;
  }
  if (message?.type === "dock") {
    // The worker holds the dock's state so a reopened panel is not blank.
    void (async () => {
      await patchDock(message.patch);
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
  if (message?.type === "unpair") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (origin) await revoke(origin);
      await chrome.storage.session.clear();
      await patchDock({ status: "idle", message: "Disconnected." });
    })();
    return false;
  }
  return false;
});

/** A queued link we are willing to turn into a tab, or null.
 *
 *  The server checks the host against the student's own pack before queueing
 *  the action; the extension cannot re-derive that list, so its job is the
 *  scheme. Without this a `javascript:` or `data:` payload becomes a tab --
 *  and the payload is text a third party wrote, extracted from an email. */
function safeLink(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

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
    const link =
      action.kind === "OPEN_VERIFICATION_URL" ? safeLink(action.payload["url"]) : null;
    if (link) {
      // Opened in the student's own browser, in a new tab they can see. No
      // navigation of the tab they are standing on.
      await chrome.tabs.create({ url: link, active: false });
      await postActionResult(origin, action.id, true, { opened: true });
    } else {
      // Anything else is for the student to do; the dock shows it and the
      // result is posted when they say so.
      await patchDock({ message: action.kind });
    }
  }
});

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
  if (!origin) return void patchDock({ message: "Connect this browser to your dashboard first." });
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
    } else {
      // GET answers 200 with none/done/waiting, never 409: anything but `ask`
      // means there is no question to show for this registration (the
      // mailbox sweep settled it, or the account went untagged), so a stale
      // one comes down (final review M1).
      await clearRegistration(applicationId);
    }
  } catch {
    // rate_limited or a network blip: the tag status stays unmeasured, the
    // safe default.
  }
});
