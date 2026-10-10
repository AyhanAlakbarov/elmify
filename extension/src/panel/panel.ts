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
  registration: null,
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
  const applicationId = document.getElementById("application-id");
  if (applicationId) applicationId.textContent = state.applicationId ?? "";
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
  const registration = document.getElementById("registration");
  if (registration) registration.hidden = state.registration === null;
  const question = document.getElementById("registration-question");
  if (question && state.registration) {
    question.textContent = `Did ${state.registration.portalHost} send you an email?`;
  }
  const tagged = document.getElementById("arrived-tagged");
  if (tagged && state.registration) tagged.textContent = `It went to ${state.registration.address}`;
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
render(EMPTY);

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
document.getElementById("use-plain")?.addEventListener("click", () => {
  void (async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id === undefined) return;
    await chrome.tabs.sendMessage(tab.id, { type: "use_plain_address" }).catch(() => {});
  })();
});
