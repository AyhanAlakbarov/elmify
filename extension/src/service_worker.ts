import {
  ExtError,
  benchPortalForms,
  benchWhoami,
  checkMailbox,
  confirmOffer,
  dashboardOrigin,
  deviceToken,
  fetchActions,
  fetchDocument,
  fileBytes,
  fetchPacket,
  fetchRegistration,
  forgetPacket,
  cachedPacket,
  loadPacket,
  pairFromTab,
  postActionResult,
  postAddress,
  postAnswers,
  postBenchPage,
  postEvent,
  postPortalLogin,
  postRegistrationAnswer,
  postSnapshot,
  postStatus,
  revoke,
  storePacket,
} from "./api.js";
import type { BenchForm, DeviceActionRow } from "./api.js";
import type { Binding } from "./types.js";

/** One alarm per registration being watched. An alarm, not setTimeout: the
 *  worker is unloaded when idle and a timer would die with it. */
const REGISTRATION_ALARM = "registration:";

/** storage.local holds the device token, and content scripts may read it by
 *  default. Locked at every worker start, before anything can be injected;
 *  follow() waits on it, so a lock that failed means no injection at all. */
const storageLocked = chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });

/** The panel is off everywhere except the tabs we enable it on (a bound portal
 *  tab, the dashboard while pairing). That is what lets a toolbar click open it
 *  before the worker knows which tabs are bound. */
void chrome.sidePanel.setOptions({ enabled: false });

/**
 * The student clicks the toolbar button on their dashboard. That gesture is
 * what lets us ask for the host permission, what opens the panel, and what
 * makes pairing an act rather than something that happened to them.
 *
 * Unmeasured in real Chrome: whether the synchronous open() below, or the
 * awaits before permissions.request(), cost the click its user gesture. One
 * first-time pairing click on a real browser settles it.
 */
chrome.action.onClicked.addListener(async (tab) => {
  // First, before any await, or the click's gesture is gone: opens on a tab
  // whose panel we enabled (a bound portal tab, even on a cold worker whose
  // boundTabs is still empty) and fails silently everywhere else.
  if (tab.id !== undefined) void chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
  // The bound portal tab: that is all.
  if (tab.id !== undefined && boundTabs.has(tab.id)) return;
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
  // Not awaited: an await here would spend the gesture open() needs. Chrome
  // applies the two calls in order.
  void chrome.sidePanel.setOptions({ tabId: tab.id, path: "panel.html", enabled: true });
  await chrome.sidePanel.open({ tabId: tab.id });
  if (await deviceToken()) return;
  await storageLocked; // the pairing script must not run where content could read the token
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
/** Offers being confirmed right now ("app\nfact"): a double tap is one tap. */
const tapping = new Set<string>();
const KNOWN_LANGS = new Set(["az", "tr", "ru", "en"]);
const KNOWN_LOGIN_PAGES = new Set(["login", "signup"]);
/** ext_api.py::_BenchPage.page_kind. */
const KNOWN_PAGE_KINDS = new Set(["FORM", "LOGIN", "SIGNUP", "CONFIRMATION", "OTHER"]);

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
  // contentRefusal ties applicationId to the bound tab only when there is one:
  // a watch with none would be keyed "undefined" and sync the mailbox for
  // nothing, and a login with none would skip that tie and ask for "undefined".
  if (
    (message["type"] === "await-code" || message["type"] === "portal-login") &&
    typeof message["applicationId"] !== "string"
  ) {
    return "invalid_message";
  }
  if (message["type"] === "portal-login") {
    if (!sender.tab) return "untrusted_sender";
    if (!KNOWN_LOGIN_PAGES.has(message["page"] as string)) return "invalid_message";
    const max = message["max_length"];
    if (max !== undefined && !(Number.isInteger(max) && (max as number) >= 1 && (max as number) <= 512)) {
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
  // Starting, stopping and the panel language are the student's acts in our
  // own panel. A portal page asking to be filled is exactly what must not work.
  if (message["type"] === "start-fill" || message["type"] === "stop-fill") {
    if (!fromDock(sender)) return "untrusted_sender";
    if (!Number.isInteger(message["tabId"])) return "invalid_message";
  }
  // Which box a document goes into is the student's answer, in our panel.
  if (message["type"] === "choice:answer") {
    if (!fromDock(sender)) return "untrusted_sender";
    if (!Number.isInteger(message["tabId"])) return "invalid_message";
    if (typeof message["filename"] !== "string" || typeof message["selector"] !== "string") {
      return "invalid_message";
    }
  }
  // "I have checked this page" is the student's press in our panel: the one
  // trigger for the answers channel, so a portal page must not fire it.
  if (message["type"] === "review:open") {
    if (!fromDock(sender)) return "untrusted_sender";
    if (!Number.isInteger(message["tabId"])) return "invalid_message";
  }
  // Using an offered value, and opening the documents page, are the student's
  // presses in our panel; a portal page must not be able to make either.
  if (message["type"] === "offer:use") {
    if (!fromDock(sender)) return "untrusted_sender";
    if (!Number.isInteger(message["tabId"])) return "invalid_message";
    if (typeof message["key"] !== "string") return "invalid_message";
  }
  if (message["type"] === "open:documents" && !fromDock(sender)) return "untrusted_sender";
  if (message["type"] === "answers" && !Array.isArray(message["answers"])) return "invalid_message";
  if (message["type"] === "unpair" && !fromDock(sender)) return "untrusted_sender";
  if (message["type"] === "language") {
    if (!fromDock(sender)) return "untrusted_sender";
    if (!KNOWN_LANGS.has(message["lang"] as string)) return "invalid_message";
  }
  // Bench mode (plan 6) is the operator's act in our own panel: a page must
  // not be able to ask for itself to be recorded.
  if (message["type"] === "bench:hello" && !fromDock(sender)) return "untrusted_sender";
  if (message["type"] === "bench:record") {
    if (!fromDock(sender)) return "untrusted_sender";
    if (!KNOWN_PAGE_KINDS.has(message["page_kind"] as string)) return "invalid_message";
    const formId = message["portalFormId"];
    if (typeof formId !== "string" || !APPLICATION_ID_RE.test(formId)) return "invalid_message";
    if (typeof message["password_rules"] !== "string") return "invalid_message";
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
  if (!CONTENT_TYPES.has(message?.type)) return handle(message, sender, sendResponse);
  void contentRefusal(message, sender).then((refused) => {
    if (!refused) return void handle(message, sender, sendResponse);
    console.warn(`elmify: refused a ${String(message.type)} message from a page`); // the type only
    sendResponse({ ok: false, code: refused });
  });
  return true;
});

/** What a content script may ask for. Every one of these spends the device
 *  token or writes the dock, so each is answered only for the tab it is bound
 *  to (contentRefusal), never for "some content script". */
const CONTENT_TYPES = new Set([
  "packet", "snapshot", "event", "status", "document", "address", "portal-login", "await-code", "dock", "answers",
]);

/** The keys a page's run may set on the dock. Everything else -- binding,
 *  language, registration, page -- is the worker's or the student's. */
const CONTENT_DOCK_KEYS = new Set([
  "status", "message", "fields", "documents", "notes", "choices", "applicationId",
]);
const DOCK_STATUSES = new Set<string>([
  "idle", "pairing", "ready", "filling", "blocked", "done", "review", "login", "stopped",
]);

/** A page's dock message is a code the panel translates, never a sentence:
 *  the panel shows an unknown sentence verbatim, and a portal page must not
 *  get to write one into our own UI. */
const MESSAGE_CODE = /^[a-z][a-z0-9_]*$/;

/**
 * Tie a content-script message to its binding (fix round 1, critical). The
 * tab id, frame id and origin are set by the browser from the sending frame, so
 * a page cannot forge them; what it can choose -- the applicationId, the
 * portal form, the document path -- must then match what the binding and its
 * cached packet already say.
 */
async function contentRefusal(
  message: Record<string, unknown>,
  sender: chrome.runtime.MessageSender,
): Promise<string | null> {
  const tabId = sender.tab?.id;
  if (tabId === undefined || sender.frameId !== 0) return "untrusted_sender";
  const binding = (await bindings())[tabId];
  if (!binding?.active || sender.origin !== binding.origin) return "untrusted_sender";
  if (message["type"] === "dock") {
    // Only the tab the dock shows may write it (final review I1).
    const stored = await chrome.storage.session.get("dock");
    const shown = (stored["dock"] as { binding?: { tabId?: number } } | undefined)?.binding?.tabId;
    if (shown !== tabId) return "untrusted_sender";
  }
  const patch = message["type"] === "dock" ? (message["patch"] as Record<string, unknown>) : {};
  const applicationId = message["applicationId"] ?? patch?.["applicationId"];
  if (applicationId !== undefined && applicationId !== binding.applicationId) return "untrusted_sender";
  if (message["type"] === "snapshot" && message["portalFormId"] !== binding.portalFormId) {
    return "untrusted_sender";
  }
  // The password is for the binding's own host: a page that moved to a
  // single-sign-on host, or any other, asks for nothing (spec §6).
  if (message["type"] === "portal-login" && message["host"] !== new URL(binding.origin).hostname) {
    return "untrusted_sender";
  }
  if (message["type"] === "document") {
    const packet = await loadPacket(binding.applicationId);
    // A choice's document is fetched when the student picks its box.
    const listed =
      packet?.documents.some((doc) => doc.download_path === message["path"]) ||
      (packet?.choices ?? []).some((choice) => choice.download_path === message["path"]);
    if (!listed) return "untrusted_sender";
  }
  return null;
}

/** The only paths a packet links a document under (portals-ext-document, documents-download,
 *  portals-prepared-download); the session cookie goes to nothing else. */
const DOCUMENT_PATHS = ["/ext/documents/", "/documents/", "/prepared/"];

/** Every case below runs only after messageRefusal, and a content script's
 *  message only after contentRefusal. */
function handle(message: any, sender: chrome.runtime.MessageSender, sendResponse: (r?: unknown) => void): boolean {
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
        // The cached packet was minted from the map this snapshot replaces.
        if (typeof message.applicationId === "string") await forgetPacket(message.applicationId);
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
      try {
        // An upload: ext_api.document, a device endpoint -- the token, no cookie.
        // A draft: download_document is @login_required and the student's own
        // session cookie is what authorizes their own document.
        // Parsed, never concatenated: "@evil.example/x" after the origin is another host.
        const url = new URL(String(message.path), origin);
        const listed = DOCUMENT_PATHS.some((prefix) => url.pathname.startsWith(prefix));
        if (url.origin !== origin || !listed) {
          throw new ExtError(0, "document_unavailable");
        }
        const path = url.pathname + url.search;
        let bytes: ArrayBuffer;
        if (path.startsWith("/ext/")) {
          bytes = await fetchDocument(origin, path);
        } else {
          const response = await fetch(url.href, { credentials: "include" });
          bytes = await fileBytes(response);
        }
        // Base64: sendMessage is JSON, and an ArrayBuffer arrives as {} (final review I6).
        sendResponse({ ok: true, base64: toBase64(bytes) });
      } catch (error) {
        // The status only: the path names the student's own upload.
        const status = error instanceof ExtError ? error.status : "network";
        console.warn(`elmify: a document could not be fetched (${status})`);
        sendResponse({ ok: false, code: "document_unavailable" }); // offline: never no answer (M1)
      }
    })();
    return true;
  }
  if (message?.type === "portal-login") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      // We typed a login and this tab is on a login page again instead of the
      // form: the portal did not take it. Typing the same password again only
      // walks the account toward a lockout. Reaching the form clears this, and
      // so does the page saying it typed none of what it was handed.
      if ((await bindings())[sender.tab!.id!]?.loginTyped) {
        return sendResponse({ ok: false, code: "login_not_accepted" });
      }
      try {
        const login = await postPortalLogin(origin, message.applicationId, {
          page: message.page,
          host: message.host,
          ...(message.max_length ? { max_length: message.max_length } : {}),
          ...(message.came_back === true ? { came_back: true } : {}),
        });
        // Set at hand-out, not at typing: a page that typed some boxes and not
        // others, or was stopped between typing and saying so, still had our
        // password typed. The page clears it by saying it typed none of it.
        if (message.page === "login") {
          const binding = (await bindings())[sender.tab!.id!];
          if (binding) await saveBinding({ ...binding, loginTyped: true });
        }
        // Straight back to the page that asked. Never in storage, the dock or
        // a log: the extension holds a portal password only for this reply.
        sendResponse({ ok: true, username: login.username, password: login.password });
      } catch (error) {
        sendResponse({ ok: false, code: error instanceof ExtError ? error.code : "request_failed" });
      }
    })();
    return true;
  }
  if (message?.type === "await-code") {
    void startWatch(message.applicationId).then((watching) => sendResponse({ ok: true, watching }));
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
    const patch = Object.fromEntries(
      Object.entries((message.patch ?? {}) as Record<string, unknown>).filter(([key]) =>
        CONTENT_DOCK_KEYS.has(key),
      ),
    );
    if (typeof patch["message"] !== "string" || !MESSAGE_CODE.test(patch["message"])) delete patch["message"];
    if (!DOCK_STATUSES.has(patch["status"] as string)) delete patch["status"];
    void (async () => {
      // The panel prints field keys and filenames: keep only the packet's own,
      // so a page cannot put a sentence of its choosing there either.
      const binding = (await bindings())[sender.tab!.id!]!;
      // The page was handed a login and typed none of it: nothing of ours is
      // in the boxes, so a login page next is no refusal. Shown as "log_in".
      if (patch["message"] === "log_in_untyped") {
        patch["message"] = "log_in";
        if (binding.loginTyped) await saveBinding({ ...binding, loginTyped: false });
      }
      // "filling" is sent only past the login and password-page checks: this
      // tab reached a page that is not a login, so the last login was taken.
      if (patch["status"] === "filling" && binding.loginTyped) {
        await saveBinding({ ...binding, loginTyped: false });
      }
      // On the form, the portal's mail no longer matters: stop syncing for it,
      // and take down a code the panel was showing.
      if (patch["status"] === "filling") {
        if ((await watches())[binding.applicationId]) await endWatch(binding.applicationId);
        patch["code"] = null;
        patch["code_from"] = null;
      }
      const packet = await cachedPacket(binding.applicationId);
      const keys = new Set([
        ...(packet?.entries ?? []).map((entry) => entry.profile_field),
        ...(packet?.hints ?? []).map((hint) => hint.profile_field),
      ]);
      const hintsByKey = new Map((packet?.hints ?? []).map((hint) => [hint.profile_field, hint]));
      const offered = new Map((packet?.choices ?? []).map((choice) => [choice.filename, choice]));
      const files = new Set([...(packet?.documents ?? []).map((doc) => doc.filename), ...offered.keys()]);
      if ("fields" in patch) {
        // The offer, upload kind and expiry are the packet's, never the page's.
        patch["fields"] = Array.isArray(patch["fields"])
          ? patch["fields"]
              .filter((row) => keys.has(row?.key))
              .map((row) => {
                const { offer: _offer, upload_kind: _kind, expired_on: _expired, ...rest } = row;
                const hint = hintsByKey.get(row.key);
                // A reason the packet does not back would render a sentence with blanks.
                const unbacked =
                  (rest.reason === "offer" && !hint?.offer) ||
                  (rest.reason === "upload_once" && !hint?.upload_kind);
                return {
                  ...rest,
                  ...(unbacked ? { reason: "" } : {}),
                  ...(hint?.offer
                    ? { offer: { value: hint.offer.value, source_kind: hint.offer.source_kind } }
                    : {}),
                  ...(hint?.upload_kind ? { upload_kind: hint.upload_kind } : {}),
                  ...(hint?.expired_on ? { expired_on: hint.expired_on } : {}),
                };
              })
          : [];
      }
      if ("documents" in patch) {
        patch["documents"] = Array.isArray(patch["documents"])
          ? patch["documents"].filter((doc) => files.has(doc?.filename))
          : [];
      }
      if ("notes" in patch) {
        const ours = new Set((packet?.notes ?? []).map((n) => `${n.kind}\n${n.note}`));
        patch["notes"] = Array.isArray(patch["notes"])
          ? patch["notes"]
              .filter((n) => ours.has(`${n?.kind}\n${n?.note}`))
              .map((n) => ({ kind: n.kind, note: n.note }))
          : [];
      }
      if ("choices" in patch) {
        // A choice is the packet's own document and the packet's own boxes;
        // the description is the box's visible page text, shown as text only.
        patch["choices"] = Array.isArray(patch["choices"])
          ? patch["choices"].flatMap((row) => {
              const choice = offered.get(row?.filename);
              if (!choice || !Array.isArray(row.options)) return [];
              const options = row.options
                .filter((o: unknown) => {
                  const option = o as { selector?: unknown; description?: unknown } | null;
                  return (
                    typeof option?.selector === "string" &&
                    choice.selectors.includes(option.selector) &&
                    typeof option.description === "string"
                  );
                })
                .map((o: { selector: string; description: string }) => ({
                  selector: o.selector,
                  description: o.description.slice(0, 120),
                }));
              return [{ filename: choice.filename, options }];
            })
          : [];
      }
      await patchDock(patch);
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
  if (message?.type === "bench:hello") {
    void (async () => {
      const origin = await dashboardOrigin();
      let forms: BenchForm[] = [];
      try {
        if (origin && (await benchWhoami(origin))) forms = await benchPortalForms(origin);
      } catch (error) {
        // Offline or refused: no bench section. The code only, never a body.
        const code = error instanceof ExtError ? error.code : "request_failed";
        console.warn(`elmify: bench forms unavailable (${code})`);
        forms = [];
      }
      await chrome.storage.session.set({ bench_forms: forms });
      await patchDock({ bench: forms.length > 0 ? { forms } : null });
      sendResponse({ ok: true });
    })();
    return true;
  }
  if (message?.type === "bench:record") {
    void (async () => {
      const origin = await dashboardOrigin();
      const stored = await chrome.storage.session.get("bench_forms");
      const forms = (stored["bench_forms"] ?? []) as BenchForm[];
      const form = forms.find((candidate) => candidate.id === message.portalFormId);
      const link = form ? safeLink(form.form_url) : null;
      // The panel asked for this origin's grant in the press; remember it so
      // unpair hands it back (bench origins have no Stop of their own).
      if (link) await rememberBenchOrigin(new URL(link).origin);
      const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      // Only for a form the server listed for this device, only the active tab,
      // and only on that form's own origin -- the one the panel asked for.
      // ponytail: the form's own origin only, so a LOGIN on a separate
      // single-sign-on host cannot be recorded; add an origin picker when a
      // measured portal needs one.
      if (!origin || !form || !link || tab?.id === undefined
          || !onOrigin(tab.url, new URL(link).origin)) {
        await patchDock({ bench_last: { ok: false } });
        return sendResponse({ ok: false, code: "wrong_page" });
      }
      try {
        await storageLocked; // never inject while content scripts could still read the token
        await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
        const page = (await chrome.tabs.sendMessage(tab.id, { type: "record" })) as {
          origin?: unknown;
          snapshot?: unknown;
          html?: unknown;
        } | undefined;
        // The tab may have navigated during the awaits above: the page's own
        // origin, read when it built the copy, must still be the form's.
        if (page?.origin !== new URL(link).origin) throw new ExtError(409, "wrong_page");
        if (typeof page?.html !== "string") throw new ExtError(400, "invalid_recording");
        await postBenchPage(origin, form.id, {
          page_kind: message.page_kind,
          password_rules: message.password_rules,
          snapshot: page.snapshot,
          html: page.html,
        });
        await patchDock({ bench_last: { ok: true } });
        sendResponse({ ok: true });
      } catch (error) {
        const code = error instanceof ExtError ? error.code : "request_failed";
        console.warn(`elmify: a bench page was not recorded (${code})`); // the code only
        await patchDock({ bench_last: { ok: false } });
        sendResponse({ ok: false, code });
      }
    })();
    return true;
  }
  if (message?.type === "language") {
    void patchDock({ language: message.lang }).then(() => sendResponse({ ok: true }));
    return true;
  }
  if (message?.type === "start-fill") {
    void (async () => {
      // Only the tab the dock shows: a stale Start must not re-activate an old one.
      const stored = await chrome.storage.session.get("dock");
      const shown = (stored["dock"] as { binding?: { tabId?: number } } | undefined)?.binding?.tabId;
      if (shown !== message.tabId) return sendResponse({ ok: false, code: "not_shown" });
      const binding = (await bindings())[message.tabId];
      const tab = binding ? await chrome.tabs.get(binding.tabId).catch(() => null) : null;
      if (!binding || !tab?.url || !onOrigin(tab.url, binding.origin)) {
        await patchDock({ status: "blocked", message: "wrong_page" });
        return sendResponse({ ok: false, code: "wrong_page" });
      }
      binding.active = true;
      delete binding.stopped;
      void chrome.sidePanel.setOptions({ tabId: binding.tabId, path: "panel.html", enabled: true });
      await follow(binding, tab.url);
      sendResponse({ ok: true });
    })();
    return true;
  }
  if (message?.type === "choice:answer") {
    void (async () => {
      // Only the tab the dock shows: a stale pick must not attach in an old one.
      const binding = await shownActiveBinding(message.tabId, sendResponse);
      if (!binding) return;
      // Straight to the bound tab's content script, which checks the box was
      // one the packet offered before it attaches anything.
      const reply = await chrome.tabs
        .sendMessage(binding.tabId, {
          type: "choice:attach",
          filename: message.filename,
          selector: message.selector,
        })
        .catch(() => ({ ok: false }));
      sendResponse(reply);
    })();
    return true;
  }
  if (message?.type === "offer:use") {
    void (async () => {
      const binding = await shownActiveBinding(message.tabId, sendResponse);
      if (!binding) return;
      // The offer is the cached packet's own: the panel names a field, nothing more.
      const packet = await cachedPacket(binding.applicationId);
      const hint = (packet?.hints ?? []).find((h) => h.profile_field === message.key && h.offer);
      const origin = await dashboardOrigin();
      if (!hint?.offer || !origin) return sendResponse({ ok: false, code: "not_found" });
      // A double tap is one tap: the second finds the first still in flight.
      const flight = `${binding.applicationId}\n${hint.offer.fact_id}`;
      if (tapping.has(flight)) return sendResponse({ ok: false, code: "busy" });
      tapping.add(flight);
      try {
        const answer = await confirmOffer(origin, binding.applicationId, hint.offer.fact_id);
        const reply = await chrome.tabs
          .sendMessage(binding.tabId, { type: "offer:fill", key: hint.profile_field, value: answer.value })
          .catch(() => null);
        // The fact is confirmed by now: a gone tab or a refused box is "saved, not typed".
        sendResponse(reply?.ok === true ? reply : { ok: false, code: "not_typed" });
      } catch (error) {
        sendResponse({ ok: false, code: error instanceof ExtError ? error.code : "request_failed" });
      } finally {
        tapping.delete(flight);
      }
    })();
    return true;
  }
  if (message?.type === "open:documents") {
    void (async () => {
      const origin = await dashboardOrigin();
      try {
        if (origin) await chrome.tabs.create({ url: `${origin}/student/documents/#upload` });
        sendResponse({ ok: Boolean(origin) });
      } catch {
        sendResponse({ ok: false });
      }
    })();
    return true;
  }
  if (message?.type === "review:open") {
    void (async () => {
      // Only the tab the dock shows, and only while it runs: the press is about
      // the page the student is looking at.
      const binding = await shownActiveBinding(message.tabId, sendResponse);
      if (!binding) return;
      await chrome.tabs.sendMessage(binding.tabId, { type: "review:open" }).catch(() => {});
      sendResponse({ ok: true });
    })();
    return true;
  }
  if (message?.type === "answers") {
    void (async () => {
      const origin = await dashboardOrigin();
      if (!origin) return sendResponse({ ok: false, code: "pairing_required" });
      try {
        // The cached packet stays: the dock filter reads its field keys, and
        // the answers are typed back from the next packet the server mints.
        await postAnswers(origin, message.applicationId, message.answers);
        sendResponse({ ok: true });
      } catch (error) {
        const code = error instanceof ExtError ? error.code : "request_failed";
        sendResponse({ ok: false, code });
      }
    })();
    return true;
  }
  if (message?.type === "stop-fill") {
    void (async () => {
      const binding = (await bindings())[message.tabId];
      if (binding) await stopBinding(binding);
      // No stale choice buttons, and no code from a portal the student stopped.
      await patchDock({ status: "stopped", choices: [], code: null, code_from: null });
      sendResponse({ ok: true });
    })();
    return true;
  }
  if (message?.type === "unpair") {
    void (async () => {
      // Every bound tab stops and hands its permission back first (final review M3).
      for (const binding of Object.values(await bindings())) await stopBinding(binding);
      const origin = await dashboardOrigin();
      await forgetBenchOrigins(origin);
      if (origin) await revoke(origin);
      await chrome.storage.session.clear();
      boundTabs.clear();
      await patchDock({ status: "idle", message: "disconnected" });
    })();
    return false;
  }
  return false;
}

/** Bench origins whose host permission the panel asked for. storage.local,
 *  locked to trusted contexts: a grant outlives the browser session. */
const BENCH_ORIGINS = "bench_origins";

async function rememberBenchOrigin(origin: string): Promise<void> {
  const stored = await chrome.storage.local.get(BENCH_ORIGINS);
  const known = (stored[BENCH_ORIGINS] ?? []) as string[];
  if (known.includes(origin)) return;
  await chrome.storage.local.set({ [BENCH_ORIGINS]: [...known, origin] });
}

/** Unpair hands back every bench grant -- never the dashboard's own. */
async function forgetBenchOrigins(dashboard: string | null): Promise<void> {
  const stored = await chrome.storage.local.get(BENCH_ORIGINS);
  const known = ((stored[BENCH_ORIGINS] ?? []) as string[]).filter((o) => o !== dashboard);
  if (known.length > 0) {
    await chrome.permissions.remove({ origins: known.map((o) => `${o}/*`) }).catch(() => false);
  }
  await chrome.storage.local.remove(BENCH_ORIGINS);
}

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  // In chunks: spreading a whole PDF into one call overflows the argument limit.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

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

// --- The portal tab: bound, injected on Start, followed while the panel is open.

async function bindings(): Promise<Record<string, Binding>> {
  const stored = await chrome.storage.session.get("bindings");
  return (stored["bindings"] ?? {}) as Record<string, Binding>;
}

/** The active binding of the tab the dock shows, or null after answering the
 *  refusal: a stale press must not act on an old tab. */
async function shownActiveBinding(
  tabId: number,
  sendResponse: (response: unknown) => void,
): Promise<Binding | null> {
  const stored = await chrome.storage.session.get("dock");
  const shown = (stored["dock"] as { binding?: { tabId?: number } } | undefined)?.binding?.tabId;
  if (shown !== tabId) {
    sendResponse({ ok: false, code: "not_shown" });
    return null;
  }
  const binding = (await bindings())[tabId];
  if (!binding?.active) {
    sendResponse({ ok: false, code: "not_started" });
    return null;
  }
  return binding;
}

async function saveBinding(binding: Binding): Promise<void> {
  const all = await bindings();
  all[binding.tabId] = binding;
  boundTabs.add(binding.tabId);
  await chrome.storage.session.set({ bindings: all });
}

/** The bound tab ids, in memory, so the toolbar click can tell a portal tab
 *  without an await. Primed from storage when the worker loads; a click that
 *  lands before the prime still opens the panel (onClicked's first line). */
const boundTabs = new Set<number>();
void bindings().then((all) => Object.values(all).forEach((b) => boundTabs.add(b.tabId)));

/** Stop one binding: inactive, its tab told, its permission handed back. */
async function stopBinding(binding: Binding): Promise<void> {
  binding.active = false;
  binding.stopped = true;
  await saveBinding(binding);
  await endWatch(binding.applicationId); // its portal's mail is no longer awaited
  await chrome.sidePanel.setOptions({ tabId: binding.tabId, enabled: false }).catch(() => {});
  await chrome.tabs.sendMessage(binding.tabId, { type: "stop" }).catch(() => {});
  await giveBackPermission(binding.origin);
}

function onOrigin(url: string | undefined, origin: string): boolean {
  try {
    return url !== undefined && new URL(url).origin === origin;
  } catch {
    return false;
  }
}

/** Open dock panels. A port, not a flag in storage: it closes when the panel
 *  does, and with the worker. ponytail: one set for every bound tab -- any open
 *  panel follows them all; key ports by tab if a student fills two portals at once. */
const docks = new Set<chrome.runtime.Port>();

/** Inject into the bound tab and start a run. Every caller has already checked
 *  the tab is on binding.origin; the content script checks form_url's origin too. */
async function follow(binding: Binding, url: string, resume = false): Promise<void> {
  const path = new URL(url).pathname.replace(/\/+$/, "");
  if (!binding.pages.includes(path)) binding.pages.push(path);
  await saveBinding(binding);
  // A new page, or a resume: the run on it re-reports its own choices.
  await patchDock({ page: binding.pages.indexOf(path) + 1, choices: [] });
  try {
    await storageLocked; // never inject while content scripts could still read the token
    await chrome.scripting.executeScript({ target: { tabId: binding.tabId }, files: ["content.js"] });
    const stored = await chrome.storage.session.get("dock");
    const language = (stored["dock"] as { language?: string } | undefined)?.language;
    await chrome.tabs.sendMessage(binding.tabId, {
      type: "start",
      applicationId: binding.applicationId,
      portalFormId: binding.portalFormId,
      language: language ?? "en",
      // The content script refuses to run anywhere else, before its first ask.
      origin: binding.origin,
      // A reopened panel: a page that already ran re-reports instead of re-filling.
      resume,
    });
  } catch (error) {
    // Permission withdrawn, tab gone, or the page navigated mid-injection.
    console.warn("elmify: could not start on the portal tab", error);
    await patchDock({ status: "blocked", message: "unreachable" });
  }
}

chrome.runtime.onConnect.addListener(async (port) => {
  if (port.name !== "dock" || !port.sender || !fromDock(port.sender)) return;
  docks.add(port);
  port.onDisconnect.addListener(() => docks.delete(port)); // pause
  port.onMessage.addListener(() => {}); // the panel's keep-alive; arriving is its whole job
  // Resume: once, for every started binding whose tab is still on its origin.
  for (const binding of Object.values(await bindings())) {
    if (!binding.active) continue;
    const tab = await chrome.tabs.get(binding.tabId).catch(() => null);
    if (tab?.url && onOrigin(tab.url, binding.origin)) await follow(binding, tab.url, true);
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== "complete") return;
  const dashboard = await dashboardOrigin();
  // Apply is a POST that redirects back to the dashboard: that page load is
  // when a START_FILL is waiting, and the student is already on this tab.
  if (dashboard && onOrigin(tab.url, dashboard)) return void (await pollActions(dashboard));
  const binding = (await bindings())[tabId];
  // A bound tab keeps its panel, before Start too (a login redirect after
  // Apply); a stopped one stays off, as Stop left it.
  if (binding && !binding.stopped) await chrome.sidePanel.setOptions({ tabId, path: "panel.html", enabled: true });
  // Only the bound tab, only on its own origin, only after Start and before
  // Stop, and only while a panel is open to show what happens.
  if (!binding?.active || docks.size === 0 || !tab.url || !onOrigin(tab.url, binding.origin)) return;
  await follow(binding, tab.url);
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const all = await bindings();
  if (!(tabId in all)) return;
  const { origin, applicationId, active } = all[tabId]!;
  delete all[tabId];
  boundTabs.delete(tabId);
  await chrome.storage.session.set({ bindings: all });
  await giveBackPermission(origin); // as Stop does (final review M2)
  // A stopped tab's watch ended at Stop; this application may watch in another tab now.
  if (active) await endWatch(applicationId);
});

/** Stop hands the portal's host permission back, so grants do not pile up
 *  across portals. Kept while another started binding uses the same origin,
 *  and never for the dashboard: that one is the pairing's. */
async function giveBackPermission(origin: string): Promise<void> {
  if (origin === (await dashboardOrigin())) return;
  const inUse = Object.values(await bindings()).some((b) => b.active && b.origin === origin);
  if (!inUse) await chrome.permissions.remove({ origins: [`${origin}/*`] }).catch(() => false);
}

/** The student pressed Apply: open the portal in a new tab and bind it. Nothing
 *  is injected here -- the student presses Start in the panel, which is where
 *  the host permission is asked for. */
async function startFill(dashboard: string, action: DeviceActionRow): Promise<void> {
  const applicationId = action.application_id;
  let form: Record<string, unknown> = {};
  if (applicationId && APPLICATION_ID_RE.test(applicationId)) {
    try {
      const packet = await fetchPacket(dashboard, applicationId);
      await storePacket(applicationId, packet);
      form = packet as unknown as Record<string, unknown>;
    } catch (error) {
      if (!(error instanceof ExtError)) throw error; // offline: the action stays queued
      if (error.code !== "no_field_map") {
        await postActionResult(dashboard, action.id, false, { refused: error.code });
        await patchDock({ status: "blocked", message: error.code });
        return;
      }
      form = error.detail; // first encounter: the 424 names the form and its id
    }
  }
  const link = safeLink(form["form_url"]);
  const portalFormId = form["portal_form_id"];
  if (!applicationId || !link || typeof portalFormId !== "string" || !APPLICATION_ID_RE.test(portalFormId)) {
    await postActionResult(dashboard, action.id, false, { refused: "invalid_action" });
    return;
  }
  const tab = await chrome.tabs.create({ url: link });
  if (tab.id === undefined) {
    await postActionResult(dashboard, action.id, false, { refused: "no_tab" });
    return;
  }
  const origin = new URL(link).origin;
  await saveBinding({ tabId: tab.id, applicationId, portalFormId, origin, active: false, pages: [] });
  // One portal at a time (final review I1): every other started binding stops.
  for (const other of Object.values(await bindings())) {
    if (other.active && other.tabId !== tab.id) await stopBinding(other);
  }
  await chrome.sidePanel.setOptions({ tabId: tab.id, path: "panel.html", enabled: true });
  await patchDock({
    applicationId,
    status: "ready",
    message: "start",
    binding: { tabId: tab.id, origin },
    page: 1,
    fields: [],
    documents: [],
    code: null,
    code_from: null,
    notes: [],
  });
  await postActionResult(dashboard, action.id, true, { opened: true });
}

/** One poll at a time: a dashboard load fires onActivated and onUpdated
 *  together, and two polls would both see one START_FILL and open two tabs. */
let polling = false;

async function pollActions(origin: string): Promise<void> {
  if (polling) return;
  polling = true;
  try {
    await answerActions(origin);
  } finally {
    polling = false;
  }
}

/** One alarm per application whose portal mail we are waiting for (spec §6). */
const CODE_WATCH_ALARM = "code-watch:";
/** The server's own rule for a code (apps/mailbox/actions.py). */
const CODE_RE = /^[A-Za-z0-9]{1,12}$/;
const HOSTNAME_RE = /^(?=.{1,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+$/i;
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
 *  ask while watching only extends the watch: no extra mailbox sync. True when
 *  a watch now runs -- the page says "getting it from your inbox" only then. */
async function startWatch(applicationId: string): Promise<boolean> {
  const all = await watches();
  if (all[applicationId]) {
    all[applicationId]!.until = Date.now() + WATCH_MS;
    await chrome.storage.session.set({ codeWatch: all });
    return true;
  }
  const origin = await dashboardOrigin();
  if (!origin) return false;
  try {
    const { queued } = await checkMailbox(origin);
    if (queued === 0) {
      await patchDock({ message: "type_code_yourself" });
      return false;
    }
  } catch (error) {
    if (error instanceof ExtError && error.code === "mailbox_disconnected") {
      await patchDock({ message: "type_code_yourself" });
      return false;
    }
    // rate_limited or offline: a push-driven sync may still bring it; watch anyway.
  }
  all[applicationId] = { until: Date.now() + WATCH_MS, ticks: 0 };
  await chrome.storage.session.set({ codeWatch: all });
  await patchDock({ code: null });
  await chrome.alarms.create(`${CODE_WATCH_ALARM}${applicationId}`, { periodInMinutes: 0.5 });
  return true;
}

/** Messages that mean "we are waiting for the portal's mail": the only ones a
 *  watch's expiry may replace. Anything else the dock says is newer news. */
const WAITING_MESSAGES = new Set(["waiting_code", "sign_up_typed"]);

/** A code or link with no application (several applications on one portal
 *  host) settles whichever watch was waiting: one portal at a time. */
async function endWatchesFor(applicationId: string | null): Promise<void> {
  for (const id of applicationId ? [applicationId] : Object.keys(await watches())) {
    await endWatch(id);
  }
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm.name.startsWith(CODE_WATCH_ALARM)) return;
  const applicationId = alarm.name.slice(CODE_WATCH_ALARM.length);
  const all = await watches();
  const watch = all[applicationId];
  if (!watch) return void (await chrome.alarms.clear(alarm.name));
  if (Date.now() > watch.until) {
    await endWatch(applicationId);
    const dock = (await chrome.storage.session.get("dock"))["dock"] as { message?: string } | undefined;
    if (WAITING_MESSAGES.has(dock?.message ?? "")) await patchDock({ message: "type_code_yourself" });
    return;
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
  await endWatchesFor(action.application_id);
  // The sender's domain, so a shown code says which portal it is for. Text
  // only, and only a hostname: it came from a mail header.
  const from = action.payload["from"];
  const codeFrom = typeof from === "string" && HOSTNAME_RE.test(from) ? from : null;
  await patchDock(
    typed ? { message: "code_typed", code: null, code_from: null } : { message: "code_shown", code, code_from: codeFrom },
  );
  await postActionResult(origin, action.id, true, { typed });
}

async function answerActions(origin: string): Promise<void> {
  // A watch polls every 30 s while the student stands at the portal: a kind
  // this extension has no handler for must not overwrite what the mail did.
  const watching = Object.keys(await watches()).length > 0;
  for (const action of await fetchActions(origin)) {
    if (action.kind === "START_FILL") {
      await startFill(origin, action);
      continue;
    }
    if (action.kind === "TYPE_CODE") {
      await deliverCode(origin, action);
      continue;
    }
    const link =
      action.kind === "OPEN_VERIFICATION_URL" ? safeLink(action.payload["url"]) : null;
    if (link) {
      // Opened in the student's own browser, in a new tab they can see. No
      // navigation of the tab they are standing on.
      await chrome.tabs.create({ url: link, active: false });
      await postActionResult(origin, action.id, true, { opened: true });
      await endWatchesFor(action.application_id);
      await patchDock({ message: "link_opened" });
    } else {
      // Anything else is for the student to do; the dock shows it and the
      // result is posted when they say so.
      if (!watching) await patchDock({ message: action.kind });
    }
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
  await pollActions(origin);
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
