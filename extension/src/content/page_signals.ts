/**
 * What the page is telling us, read deterministically.
 *
 * Ported from apps/portals/challenge.py. Every marker is a container the
 * provider's own script renders; nothing here infers a challenge from page
 * text or a model's opinion. A false positive interrupts a student who was
 * doing fine; a false negative strands one.
 */
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

/** Did the portal say it received the application?
 *
 *  Markers come from PortalForm.confirmation_markers via the packet when that
 *  column is populated; with none configured this answers false, which is the
 *  right default -- a SUBMITTED row we invented is worse than one we missed,
 *  because the student's roadmap card would move on a guess. */
export function detectConfirmation(markers: string[]): boolean {
  if (markers.length === 0) return false;
  const text = document.body?.innerText ?? "";
  return markers.some((marker) => text.includes(marker));
}

/** A portal's own account page, as the extension read it. Capped here as well
 *  as server-side (ext_api._PortalStatus) so a hostile page cannot make the
 *  request large enough to be refused for the wrong reason. */
export function readStatus(): {
  portal_state: string;
  application_number: string;
  document_requests: string[];
} {
  const text = (document.body?.innerText ?? "").slice(0, 5000);
  const number = /\b(?:application|reference)\s*(?:no\.?|number|id)[:\s]*([A-Z0-9-]{4,40})/i.exec(text);
  return {
    portal_state: (document.title ?? "").slice(0, 200),
    application_number: (number?.[1] ?? "").slice(0, 100),
    document_requests: Array.from(document.querySelectorAll("[data-document-request]"))
      .slice(0, 50)
      .map((node) => (node.textContent ?? "").trim().slice(0, 200))
      .filter(Boolean),
  };
}
