/**
 * What the page is telling us, read deterministically.
 *
 * Ported from apps/portals/challenge.py. Every marker is a container the
 * provider's own script renders; nothing here infers a challenge from page
 * text or a model's opinion. A false positive interrupts a student who was
 * doing fine; a false negative strands one.
 */
import { visible } from "./verify.js";

declare const __ELMIFY_TEST__: boolean;

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

const CONFIRMATION_ROUTE_RE =
  /\/(submitted|confirmation|thank-you|thank_you|complete|receipt|bestaetigung|erfolgreich)(?=\/|$|\?|#)/i;

const RECEIPT_PHRASES = [
  "application has been submitted",
  "successfully submitted",
  "thank you for your application",
  "application was submitted",
  "application has been received",
  "we have received your application",
  "bewerbung wurde eingereicht",
  "bewerbung wurde erfolgreich",
  "bewerbung ist eingegangen",
  "vielen dank für ihre bewerbung",
  "candidature a été soumise",
  "candidature a bien été enregistrée",
  "merci pour votre candidature",
  "müraciətiniz qəbul edildi",
  "müraciətiniz göndərildi",
  "başvurunuz alınmıştır",
  "başvurunuz başarıyla",
  "заявка отправлена",
  "ваша заявка принята",
];

const QUALIFIER_PREFIX_RE =
  /\b(?:after|before|once|when|if|until|unless|please\s+review|sobald|nachdem|bevor|falls|avant|apr[eè]s|lorsque)\b[^.!?\n]{0,80}$/i;

const FILLABLE_SELECTOR =
  'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"]):not([type="search"]), select, textarea';

const SUBMIT_SELECTOR =
  'input[type="submit"]:not([disabled]), button[type="submit"]:not([disabled])';

/** A portal's own account page, as the extension read it. Capped here as well
 *  as server-side (ext_api._PortalStatus) so a hostile page cannot make the
 *  request large enough to be refused for the wrong reason. */
const STATUS_NUMBER_RE =
  /(?:\b(?:application|reference|applicant|bewerbungs|registration)\s*(?:id|no\.?|number|nr\.?|code|#)|\bbewerbungsnummer|\bantragsnummer|\bnum[eé]ro\s+de\s+(?:dossier|candidature)|\bba[sş]vuru\s*(?:no\.?|numaras[ıi])|\baanvraagnummer|номер\s+заявки)\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{3,39})/iu;

function isControlVisible(el: HTMLElement, doc: Document): boolean {
  if (el.hidden || el.getAttribute("aria-hidden") === "true") return false;
  if (el.closest("[hidden], [aria-hidden='true']")) return false;
  if (typeof getComputedStyle === "function") {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
  }
  if (
    doc.body &&
    typeof doc.body.getBoundingClientRect === "function" &&
    doc.body.getBoundingClientRect().width > 0
  ) {
    return visible(el);
  }
  return true;
}

function hasUnqualifiedReceiptPhrase(lower: string): boolean {
  for (const phrase of RECEIPT_PHRASES) {
    let fromIndex = 0;
    while (fromIndex <= lower.length - phrase.length) {
      const idx = lower.indexOf(phrase, fromIndex);
      if (idx === -1) break;
      const prefix = lower.slice(Math.max(0, idx - 120), idx);
      if (!QUALIFIER_PREFIX_RE.test(prefix)) {
        return true;
      }
      fromIndex = idx + phrase.length;
    }
  }
  return false;
}

export function detectAutonomousConfirmation(
  doc: Document = document,
  currentUrl: string = location.href,
): { confirmed: boolean; applicationNumber: string } {
  const _routeMatched = CONFIRMATION_ROUTE_RE.test(currentUrl);
  void _routeMatched;
  const hasVisibleFillable = Array.from(doc.querySelectorAll<HTMLElement>(FILLABLE_SELECTOR)).some(
    (el) => !(el as HTMLInputElement).disabled && isControlVisible(el, doc),
  );
  const hasActiveSubmit = Array.from(doc.querySelectorAll<HTMLElement>(SUBMIT_SELECTOR)).some(
    (el) => isControlVisible(el, doc),
  );
  const zeroInputs = !hasVisibleFillable && !hasActiveSubmit;
  if (!zeroInputs) {
    return { confirmed: false, applicationNumber: "" };
  }
  const rawText = (doc.body?.innerText || doc.body?.textContent || "").slice(0, 10000);
  const lower = rawText.toLowerCase();
  if (!hasUnqualifiedReceiptPhrase(lower)) {
    return { confirmed: false, applicationNumber: "" };
  }
  const match = STATUS_NUMBER_RE.exec(rawText);
  return {
    confirmed: true,
    applicationNumber: (match?.[1] ?? "").slice(0, 100),
  };
}

/** Did the portal say it received the application?
 *
 *  Markers come from PortalForm.confirmation_markers via the packet when that
 *  column is populated; with none configured this falls back to multi-signal
 *  autonomous receipt detection. */
export function detectConfirmation(
  markers: string[] | null,
  doc: Document = document,
  currentUrl: string = location.href,
): boolean {
  if (markers && markers.length > 0) {
    const text = doc.body?.innerText || doc.body?.textContent || "";
    const urlLower = (currentUrl || "").toLowerCase();
    return markers.some((marker) => {
      if (!marker) return false;
      if (text.includes(marker)) return true;
      const m = marker.toLowerCase();
      if (m.startsWith("/") || m.startsWith("http")) {
        return urlLower.includes(m);
      }
      return false;
    });
  }
  return detectAutonomousConfirmation(doc, currentUrl).confirmed;
}

export function readStatus(): {
  portal_state: string;
  application_number: string;
  document_requests: string[];
} {
  const text = (document.body?.innerText ?? "").slice(0, 5000);
  const number = STATUS_NUMBER_RE.exec(text);
  return {
    portal_state: (document.title ?? "").slice(0, 200),
    application_number: (number?.[1] ?? "").slice(0, 100),
    document_requests: Array.from(document.querySelectorAll("[data-document-request]"))
      .slice(0, 50)
      .map((node) => (node.textContent ?? "").trim().slice(0, 200))
      .filter(Boolean),
  };
}

const CONTROLS = "input,select,textarea";

function errorClassed(node: Element): boolean {
  return (node.getAttribute("class") ?? "")
    .toLowerCase()
    .split(/\s+/)
    .some((t) => {
      if (!t || t.startsWith("no-") || t.endsWith("-hint") || t.endsWith("-help")) return false;
      return (
        /(error|invalid|fehler)$/.test(t) ||
        /^(error|invalid|has-error|is-invalid|invalid-feedback)/.test(t)
      );
    });
}

function clean(text: string | null | undefined): string | null {
  const trimmed = (text ?? "").replace(/\s+/g, " ").trim().slice(0, 200);
  return trimmed || null;
}

/** A message node never holds a control, and never is the page itself. */
function messageNode(node: Element | null): node is Element {
  return !!node && node !== document.body && !node.querySelector(CONTROLS);
}

/** The portal's own validation message for a control, or null. Page text:
 *  it goes to the panel only, never into the marks layer. */
export function portalErrorFor(element: HTMLElement): string | null {
  if (element.getAttribute("aria-invalid") === "true") {
    const only = element.getAttribute("aria-errormessage")?.trim();
    const ids = (only || element.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
    const targets = ids.map((id) => document.getElementById(id)).filter((n): n is HTMLElement => messageNode(n));
    // With several describedby targets prefer the visible, error-classed one.
    const best = only
      ? targets[0]
      : (targets.find((n) => visible(n) && errorClassed(n)) ?? targets[0]);
    const text = best ? clean(best.textContent) : null;
    if (text) return text;
  }
  // The wrapper's children count only when this is the wrapper's one control.
  const wrapper = element.parentElement;
  const own = wrapper && wrapper.querySelectorAll(CONTROLS).length === 1;
  const candidates = [element.nextElementSibling, ...(own ? Array.from(wrapper.children) : [])];
  for (const node of candidates) {
    if (!node || node === element || !errorClassed(node) || !messageNode(node)) continue;
    const text = node instanceof HTMLElement && visible(node) ? clean(node.textContent) : null;
    if (text) return text;
  }
  return null;
}

if (__ELMIFY_TEST__) {
  (globalThis as Record<string, unknown>)["__elmify_detect_confirmation"] = (
    markers: string[] | null,
    url?: string,
  ) => detectConfirmation(markers, document, url ?? location.href);
  (globalThis as Record<string, unknown>)["__elmify_detect_autonomous_confirmation"] = (
    url?: string,
  ) => detectAutonomousConfirmation(document, url ?? location.href);
}
