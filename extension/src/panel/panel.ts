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
import type { DockState, FieldStateKind, FieldView } from "../types.js";
import {
  LANGS,
  STRINGS,
  bundleText,
  defaultLang,
  fieldLabel,
  kindLabel,
  noteText,
  t,
  type Lang,
  type StringKey,
} from "./i18n.js";

declare const __ELMIFY_TEST__: boolean;
if (__ELMIFY_TEST__) (window as unknown as Record<string, unknown>)["__elmify_strings"] = STRINGS;

const EMPTY: DockState = {
  applicationId: null,
  status: "idle",
  fields: [],
  documents: [],
  message: "",
  registration: null,
  code: null,
  code_from: null,
};

let state: DockState = EMPTY;
let lang: Lang = defaultLang(chrome.i18n?.getUILanguage?.() ?? "en");

const STATE_ORDER: FieldStateKind[] = [
  "your_turn",
  "portal_error",
  "mismatch",
  "changed_by_you",
  "elsewhere",
  "filled",
  "already",
];

/** Counted for the progress line and listed first in the review. */
const NEEDS_YOU: FieldStateKind[] = ["your_turn", "portal_error", "mismatch"];
const DONE: FieldStateKind[] = ["filled", "already", "changed_by_you"];

function fieldLine(row: FieldView): string {
  const why = reasonText(row);
  const line = why ? `${fieldLabel(lang, row.key)} — ${why}` : fieldLabel(lang, row.key);
  // A field that would have a mark but has none on the page (final review M6).
  return !row.placed && row.state !== "elsewhere" ? `${line} · ${t(lang, "only_here")}` : line;
}

/** Dock messages are codes ("wrong_page", "log_in", a server refusal) or, from
 *  older paths, whole English sentences. A code is shown in the student's
 *  language; an unknown code gets a generic line rather than raw snake_case. */
function messageText(message: string): string {
  const key = `m_${message.trim().replace(/\s+/g, "_")}`;
  if (Object.hasOwn(STRINGS[lang], key)) return t(lang, key as StringKey);
  return /^[a-z][a-z0-9_]*$/.test(message) ? t(lang, "m_code_other") : message;
}

function reasonText(row: FieldView): string {
  const { reason, theirs, key } = row;
  if (reason.startsWith("portal:")) {
    // The portal's own words: shown as text only, never parsed.
    return t(lang, theirs ? "portal_says_yours" : "portal_says", { text: reason.slice(7) });
  }
  if (reason === "") return "";
  const code = `r_${reason}` as StringKey;
  const source = row.offer ? (`src_${row.offer.source_kind}` as StringKey) : null;
  const kind = row.upload_kind ? (`u_${row.upload_kind}` as StringKey) : null;
  const vars = {
    field: fieldLabel(lang, key),
    value: row.offer?.value ?? "",
    source: source && Object.hasOwn(STRINGS[lang], source) ? t(lang, source) : "",
    kind: kind && Object.hasOwn(STRINGS[lang], kind) ? t(lang, kind) : "",
    date: row.expired_on ?? "",
  };
  return Object.hasOwn(STRINGS[lang], code) ? t(lang, code, vars) : t(lang, "r_other");
}

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
  document.documentElement.lang = lang;
  for (const node of Array.from(document.querySelectorAll<HTMLElement>("[data-i18n]"))) {
    node.textContent = t(lang, node.dataset["i18n"] as StringKey);
  }
  const status = document.getElementById("status");
  if (status) {
    const key = `st_${state.status}` as StringKey;
    status.textContent = Object.hasOwn(STRINGS[lang], key) ? t(lang, key) : state.status;
  }
  const message = document.getElementById("message");
  if (message) message.textContent = messageText(state.message);
  const applicationId = document.getElementById("application-id");
  if (applicationId) applicationId.textContent = state.applicationId ?? "";
  const fields = document.getElementById("fields");
  if (fields) {
    fields.replaceChildren(
      ...STATE_ORDER.flatMap((kind) => {
        const rows = state.fields.filter((row) => row.state === kind);
        if (rows.length === 0) return [];
        const heading = document.createElement("h2");
        heading.textContent = t(lang, `s_${kind}` as StringKey);
        const ul = document.createElement("ul");
        for (const row of rows) {
          const item = document.createElement("li");
          item.textContent = fieldLine(row);
          if (row.reason === "offer" && row.offer) {
            item.append(" ", button(t(lang, "b_use"), () => useOffer(row.key)));
          } else if (row.reason === "upload_once" || row.reason === "document_expired") {
            item.append(" ", button(t(lang, "b_open_documents"), openDocuments));
          }
          ul.append(item);
        }
        return [heading, ul];
      }),
    );
  }
  list(
    "documents",
    state.documents.map(
      (doc) =>
        `${doc.filename} — ${t(lang, doc.state === "attached" ? "d_attached" : "d_manual")}` +
        (doc.note ? ` — ${noteText(lang, doc.note)}` : ""),
    ).concat(
      // Uploads' notes and the refused bundle: a line each, in words (final review I1).
      (state.notes ?? []).map((n) =>
        n.kind === "EVERY_DOCUMENT" ? bundleText(lang, n.note) : `${kindLabel(lang, n.kind)} — ${noteText(lang, n.note)}`,
      ),
    ),
  );
  // A document whose box the student picks: one button per box, its text the
  // page's own words, set as text only.
  const open = state.choices ?? [];
  const choiceSection = document.getElementById("choices");
  if (choiceSection) choiceSection.hidden = open.length === 0;
  document.getElementById("choice-list")?.replaceChildren(
    ...open.map((choice) => {
      const item = document.createElement("li");
      const question = document.createElement("p");
      question.textContent = t(lang, "choice_question", { file: choice.filename });
      item.append(question);
      for (const option of choice.options) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = option.description;
        button.addEventListener("click", () => pick(choice.filename, option.selector));
        item.append(button);
      }
      return item;
    }),
  );
  // What still needs the student, fields first, then documents to attach.
  const mine = NEEDS_YOU.flatMap((kind) => state.fields.filter((row) => row.state === kind));
  const todo = [
    ...mine.map(fieldLine),
    ...open.map((choice) => t(lang, "choice_question", { file: choice.filename })),
    ...state.documents
      .filter((doc) => doc.state === "manual")
      .map((doc) => `${doc.filename} — ${t(lang, "d_manual")}`),
  ];
  const counted = state.fields.filter((row) => row.state !== "elsewhere");
  const progress = document.getElementById("progress");
  if (progress) {
    progress.textContent = counted.length
      ? t(lang, "progress", {
          page: String(state.page ?? 1),
          done: String(counted.filter((row) => DONE.includes(row.state)).length),
          total: String(counted.length),
          mine: String(mine.length),
        })
      : "";
  }
  const nextStep = document.getElementById("next");
  if (nextStep) nextStep.textContent = todo[0] ?? "";
  list("review-todo", todo);
  // Slim while filling; wide when there is something to read (ready, review, blocked).
  document.getElementById("dock")?.classList.toggle("slim", state.status === "filling");
  const review = document.getElementById("review");
  // There is no Next / Submit button here, or anywhere: the student presses the portal's own.
  if (review) review.hidden = state.status !== "review" && state.status !== "blocked";
  const registration = document.getElementById("registration");
  if (registration) registration.hidden = state.registration === null;
  const question = document.getElementById("registration-question");
  if (question && state.registration) {
    question.textContent = t(lang, "reg_question", { host: state.registration.portalHost });
  }
  const tagged = document.getElementById("arrived-tagged");
  if (tagged && state.registration) {
    tagged.textContent = t(lang, "reg_tagged", { address: state.registration.address });
  }
  // textContent, never innerHTML: the code came from an email.
  const code = document.getElementById("code");
  if (code) code.hidden = !state.code;
  const codeText = document.getElementById("code-text");
  if (codeText && state.code) {
    codeText.textContent = state.code_from
      ? t(lang, "code_from_here", { code: state.code, from: state.code_from })
      : t(lang, "code_here", { code: state.code });
  }
  renderBench();
}

/** Bench mode (plan 6): the operator's recorder. Hidden unless the server
 *  listed forms for this device. Host names are set as text only. */
function renderBench(): void {
  const bench = document.getElementById("bench");
  if (bench) bench.hidden = !state.bench;
  const formPicker = document.getElementById("bench-form") as HTMLSelectElement | null;
  if (formPicker && state.bench) {
    const chosen = formPicker.value;
    formPicker.replaceChildren(
      ...state.bench.forms.map((form) => new Option(form.portal_host, form.id)),
    );
    if (chosen) formPicker.value = chosen;
  }
  const kind = (document.getElementById("bench-kind") as HTMLSelectElement | null)?.value ?? "";
  const rulesLabel = document.getElementById("bench-rules-label");
  if (rulesLabel) rulesLabel.hidden = kind !== "LOGIN" && kind !== "SIGNUP";
  const last = document.getElementById("bench-last");
  if (last) {
    last.textContent = state.bench_last
      ? t(lang, state.bench_last.ok ? "bench_saved" : "bench_failed")
      : "";
  }
}

function button(text: string, onClick: () => void): HTMLButtonElement {
  const node = document.createElement("button");
  node.type = "button";
  node.textContent = text;
  node.addEventListener("click", onClick);
  return node;
}

/** The student's tap on an offered value; the worker confirms it and the
 *  content script types the server's value into the one box (spec §7.3). */
function useOffer(key: string): void {
  if (!state.binding) return;
  void chrome.runtime
    .sendMessage({ type: "offer:use", tabId: state.binding.tabId, key })
    .then((reply: { ok?: boolean; code?: string } | undefined) => {
      if (reply?.ok === true) return;
      // A code, never a server sentence; an unknown or missing one is the generic failure
      // (not_typed comes only from the worker).
      const code = reply?.code ?? "request_failed";
      // An account or pairing refusal (pairing_required, account_locked...) reads as its own message.
      const has = (key: string): boolean => Object.hasOwn(STRINGS[lang], key);
      render({
        ...state,
        message: has(`m_offer_${code}`) ? `offer_${code}` : has(`m_${code}`) ? code : "offer_request_failed",
      });
    })
    .catch(() => render({ ...state, message: "offer_request_failed" }));
}

function openDocuments(): void {
  void chrome.runtime.sendMessage({ type: "open:documents" });
}

/** The student's pick of a box; the content script checks it was offered. */
function pick(filename: string, selector: string): void {
  if (!state.binding) return;
  void chrome.runtime.sendMessage({
    type: "choice:answer",
    tabId: state.binding.tabId,
    filename,
    selector,
  });
}

/** The student's answer to the registration-mail question. Theirs to give:
 *  the sender they type is what makes it confirmed (spec §3 rule 2). */
function answer(arrived: "tagged" | "plain" | "none"): void {
  if (!state.registration) return;
  const sender = (document.getElementById("sender") as HTMLInputElement | null)?.value ?? "";
  void chrome.runtime.sendMessage({
    type: "registration:answer",
    applicationId: state.registration.applicationId,
    arrived,
    sender: arrived === "plain" ? sender.trim() : "",
  });
}

chrome.runtime.onMessage.addListener((incoming) => {
  if (incoming?.type === "dock:state") render({ ...state, ...incoming.state });
  return false;
});

chrome.runtime.sendMessage({ type: "dock:hello" }).catch(() => {});
chrome.runtime.sendMessage({ type: "bench:hello" }).catch(() => {});
render(EMPTY);

// Language: browser default first, then the stored choice if there is one.
// Whichever wins is announced to the worker once.
const picker = document.getElementById("language") as HTMLSelectElement | null;
function announce(): void {
  // The worker may not know this message yet; a refusal is harmless.
  chrome.runtime.sendMessage({ type: "language", lang }).catch(() => {});
}
if (picker) {
  picker.value = lang;
  let chosen = false;
  picker.addEventListener("change", () => {
    chosen = true;
    lang = picker.value as Lang;
    void chrome.storage?.local?.set({ language: lang })?.catch(() => {});
    announce();
    render(state);
  });
  void (async () => {
    try {
      const stored = await chrome.storage?.local?.get("language");
      const saved = stored?.["language"];
      if (!chosen && (LANGS as readonly unknown[]).includes(saved)) {
        lang = saved as Lang;
        picker.value = lang;
        render(state);
      }
    } catch {
      // storage unavailable: the browser default stands
    }
    if (!chosen) announce();
  })();
}

// The panel is open while this port is. The worker follows the portal tab's
// page loads only while one is connected, and resumes when one reconnects.
// The ping keeps the worker from being unloaded under an open panel (an idle
// worker closes the port, which would read as the panel closing).
function connectDock(): void {
  const port = chrome.runtime.connect?.({ name: "dock" });
  if (!port) return;
  const ping = setInterval(() => port.postMessage({ type: "ping" }), 25_000);
  port.onDisconnect.addListener(() => {
    clearInterval(ping);
    setTimeout(connectDock, 1_000);
  });
}
connectDock();

// Start asks for the portal's host permission HERE, in the student's click:
// the user gesture lives in this document, and the worker never asks.
document.getElementById("start")?.addEventListener("click", () => {
  const binding = state.binding; // read now: an await before the request would spend the gesture
  if (!binding) return;
  void (async () => {
    const granted = await chrome.permissions.request({ origins: [`${binding.origin}/*`] });
    if (!granted) {
      render({ ...state, message: t(lang, "permission_needed") });
      return;
    }
    await chrome.runtime.sendMessage({ type: "start-fill", tabId: binding.tabId });
  })();
});
// The answers channel's one trigger: the student says they checked the page.
document.getElementById("reviewed")?.addEventListener("click", () => {
  if (state.binding) {
    void chrome.runtime.sendMessage({ type: "review:open", tabId: state.binding.tabId });
  }
});
document.getElementById("stop")?.addEventListener("click", () => {
  if (state.binding) void chrome.runtime.sendMessage({ type: "stop-fill", tabId: state.binding.tabId });
});

// The dock's buttons. None is a page control: dispatching a click is
// forbidden in the content script, while a button the STUDENT presses in our
// own side panel is the opposite thing -- their act, on their own installation.
document.getElementById("unpair")?.addEventListener("click", () => {
  void chrome.runtime.sendMessage({ type: "unpair" });
});
document.getElementById("arrived-tagged")?.addEventListener("click", () => answer("tagged"));
document.getElementById("arrived-plain")?.addEventListener("click", () => answer("plain"));
document.getElementById("arrived-none")?.addEventListener("click", () => answer("none"));
// For a refusal the extension could not read. Straight to the portal tab's
// content script, which holds the control it filled (content/index.ts).
// The bound tab, never "whichever tab is active" (final review M4).
document.getElementById("use-plain")?.addEventListener("click", () => {
  const binding = state.binding;
  if (binding) void chrome.tabs.sendMessage(binding.tabId, { type: "use_plain_address" }).catch(() => {});
});

// Bench mode (plan 6): the operator's act, in our own panel. The host
// permission is asked here, in the click, before any await could spend the
// gesture. The worker records only the active tab, and only on this origin.
let recording = false; // one press at a time: a double press would record twice
document.getElementById("bench-record")?.addEventListener("click", (event) => {
  if (recording) return;
  const formId = (document.getElementById("bench-form") as HTMLSelectElement | null)?.value;
  const form = state.bench?.forms.find((candidate) => candidate.id === formId);
  if (!form) return;
  let origin: string;
  try {
    origin = new URL(form.form_url).origin;
  } catch {
    return;
  }
  const pageKind = (document.getElementById("bench-kind") as HTMLSelectElement | null)?.value;
  const rules = (document.getElementById("bench-rules") as HTMLTextAreaElement | null)?.value;
  const asked = chrome.permissions.request({ origins: [`${origin}/*`] });
  const button = event.currentTarget as HTMLButtonElement;
  recording = true;
  button.disabled = true;
  void (async () => {
    try {
      if (!(await asked)) return render({ ...state, message: t(lang, "permission_needed") });
      const reply = (await chrome.runtime
        .sendMessage({
          type: "bench:record",
          portalFormId: form.id,
          page_kind: pageKind ?? "FORM",
          // Only a sign-up or login page states password rules.
          password_rules: pageKind === "LOGIN" || pageKind === "SIGNUP" ? (rules ?? "") : "",
        })
        .catch(() => ({ ok: false, code: "request_failed" }))) as
        | { ok?: boolean; code?: unknown }
        | undefined;
      if (!reply?.ok) {
        // A code: messageText says it in the operator's language.
        const code = typeof reply?.code === "string" ? reply.code : "request_failed";
        render({ ...state, message: code });
      }
    } finally {
      recording = false;
      button.disabled = false;
    }
  })();
});
document.getElementById("bench-kind")?.addEventListener("change", () => render(state));
