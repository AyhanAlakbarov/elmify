// Everything that speaks to the tenant host. Only the service worker imports
// this; the content script has no credential and makes no cross-origin call.
import type { FillPacket } from "./types.js";

const TOKEN_KEY = "device_token";
const PACKET_PREFIX = "packet:";

/** One non-empty string from storage.local, or null. */
async function storedString(key: string): Promise<string | null> {
  // A storage failure reads as "not paired": every caller then answers its
  // page instead of leaving it waiting on a rejected promise.
  const stored = await chrome.storage.local.get(key).catch(() => ({}) as Record<string, unknown>);
  const value = stored[key];
  return typeof value === "string" && value ? value : null;
}

export async function deviceToken(): Promise<string | null> {
  return storedString(TOKEN_KEY);
}

export async function dashboardOrigin(): Promise<string | null> {
  return storedString("origin");
}

export class ExtError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    /** The rest of the error body. A refusal can carry facts the caller needs:
     *  424 no_field_map names the page the map is for, which is the only way
     *  the content script can check the origin before it builds a
     *  first-encounter snapshot. Never a value, never a credential -- the
     *  server decides what a refusal says. */
    readonly detail: Record<string, unknown> = {},
  ) {
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
    throw new ExtError(
      response.status,
      code,
      body && typeof body === "object" ? (body as Record<string, unknown>) : {},
    );
  }
  return body;
}

/** An upload served by ext_api.document: a device endpoint, so the token and
 *  never a cookie. Drafts still come from download_document with the session.
 *  ponytail: not through call(), which parses JSON; this body is bytes. */
export async function fetchDocument(origin: string, path: string): Promise<ArrayBuffer> {
  const token = await deviceToken();
  if (!token) throw new ExtError(401, "pairing_required");
  const response = await fetch(`${origin}${path}`, {
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
  });
  return fileBytes(response);
}

const FILE_TYPES = ["application/pdf", "image/png", "image/jpeg"];

/** The file's bytes, or document_unavailable. A redirect or a non-file type is
 *  an expired session's login page answering 200, never the student's file. */
export function fileBytes(response: Response): Promise<ArrayBuffer> {
  const type = (response.headers.get("Content-Type") ?? "").split(";", 1).join("").trim().toLowerCase();
  if (!response.ok || response.redirected || !FILE_TYPES.includes(type)) {
    throw new ExtError(response.status, "document_unavailable");
  }
  return response.arrayBuffer();
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
  // Read directly, never through storedString: a storage failure there reads
  // as "none", and minting a fresh id on it would change the device's identity.
  const stored = (await chrome.storage.local.get("installation_id"))["installation_id"];
  const existing = typeof stored === "string" && stored ? stored : null;
  if (existing) return existing;
  const fresh = crypto.randomUUID();
  await chrome.storage.local.set({ installation_id: fresh });
  return fresh;
}

export async function revoke(origin: string): Promise<void> {
  try {
    await call(origin, "/ext/pair", { method: "DELETE" });
  } catch {
    // Best-effort: local state below goes regardless of whether the server
    // could be reached or already considers this token dead. A token we
    // keep after the student asked us to forget it is the worst outcome.
  } finally {
    await chrome.storage.local.remove([TOKEN_KEY, "origin"]);
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

export async function storePacket(applicationId: string, packet: FillPacket): Promise<void> {
  // Session storage: cleared when the browser closes, so verified facts never
  // sit on disk. The server's own 2-hour expiry is the other half.
  await chrome.storage.session.set({ [`${PACKET_PREFIX}${applicationId}`]: packet });
}

/** The cached packet, expired or not: what a page's dock report is checked
 *  against, so a panel reopened hours later still lists the fields. */
export async function cachedPacket(applicationId: string): Promise<FillPacket | null> {
  const stored = await chrome.storage.session.get(`${PACKET_PREFIX}${applicationId}`);
  return (stored[`${PACKET_PREFIX}${applicationId}`] as FillPacket | undefined) ?? null;
}

export async function loadPacket(applicationId: string): Promise<FillPacket | null> {
  const packet = await cachedPacket(applicationId);
  if (!packet) return null;
  if (Date.parse(packet.expires_at) <= Date.now()) return null;
  return packet;
}

/** Drop a cached packet so the next `packet` request re-fetches from the
 *  server -- used after a rejected address, whose next packet carries the
 *  plain address instead. The one place that knows the cache key. */
export async function forgetPacket(applicationId: string): Promise<void> {
  await chrome.storage.session.remove(`${PACKET_PREFIX}${applicationId}`);
}

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

/** What the content script saw when it typed the portal address. */
export async function postAddress(
  origin: string,
  applicationId: string,
  report: { event: string; evidence?: string },
): Promise<{ address: string; awaiting_mail: boolean; ask_after_seconds: number }> {
  return (await call(origin, `/ext/applications/${applicationId}/address`, {
    method: "POST",
    body: JSON.stringify(report),
  })) as { address: string; awaiting_mail: boolean; ask_after_seconds: number };
}

/** The account's login for the portal page the content script stands on
 *  (spec 2026-10-09 §6). Returned to the caller only -- never stored. */
export async function postPortalLogin(
  origin: string,
  applicationId: string,
  ask: { page: "login" | "signup"; host: string; max_length?: number; came_back?: boolean },
): Promise<{ username: string; password: string }> {
  return (await call(origin, `/ext/applications/${applicationId}/portal-login`, {
    method: "POST",
    body: JSON.stringify(ask),
  })) as { username: string; password: string };
}

/** The answers channel (owner, 2026-10-09): values the student typed into boxes
 *  the packet named. The one call that carries typed values. */
export async function postAnswers(
  origin: string,
  applicationId: string,
  answers: unknown[],
): Promise<{ recorded: number }> {
  return (await call(origin, `/ext/applications/${applicationId}/answers`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  })) as { recorded: number };
}

/** The student's one tap on an offered value (spec 2026-10-12 §7.3): the server
 *  confirms the fact and answers with the value to type, formatted for the portal. */
export async function confirmOffer(
  origin: string,
  applicationId: string,
  factId: string,
): Promise<{ profile_field: string; value: string }> {
  return (await call(origin, `/ext/applications/${applicationId}/facts/${factId}/confirm`, {
    method: "POST",
    body: "{}",
  })) as { profile_field: string; value: string };
}

export async function checkMailbox(origin: string): Promise<{ queued: number }> {
  const body = (await call(origin, "/ext/mailbox/check", { method: "POST" })) as { queued?: unknown };
  return { queued: typeof body.queued === "number" ? body.queued : 0 };
}

export async function fetchRegistration(
  origin: string,
  applicationId: string,
): Promise<{ state: string; portal_host?: string; address?: string }> {
  return (await call(origin, `/ext/applications/${applicationId}/registration`)) as {
    state: string;
    portal_host?: string;
    address?: string;
  };
}

export async function postRegistrationAnswer(
  origin: string,
  applicationId: string,
  answer: { arrived: string; sender: string },
): Promise<{ learned: boolean }> {
  return (await call(origin, `/ext/applications/${applicationId}/registration`, {
    method: "POST",
    body: JSON.stringify(answer),
  })) as { learned: boolean };
}

/** Bench mode (plan 6): a portal form an operator may record. */
export interface BenchForm {
  id: string;
  portal_host: string;
  form_url: string;
}

export async function benchWhoami(origin: string): Promise<boolean> {
  const body = (await call(origin, "/ext/bench/whoami")) as { operator?: unknown };
  return body.operator === true;
}

export async function benchPortalForms(origin: string): Promise<BenchForm[]> {
  const body = (await call(origin, "/ext/bench/portal-forms")) as { forms: BenchForm[] };
  return body.forms;
}

/** One recorded page: a value-free snapshot and a value-blanked, script-free copy. */
export async function postBenchPage(
  origin: string,
  portalFormId: string,
  page: { page_kind: string; password_rules: string; snapshot: unknown; html: string },
): Promise<{ record_id: string }> {
  return (await call(origin, `/ext/bench/portal-forms/${portalFormId}/pages`, {
    method: "POST",
    body: JSON.stringify(page),
  })) as { record_id: string };
}
