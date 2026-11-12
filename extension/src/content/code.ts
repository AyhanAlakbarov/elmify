/**
 * The portal's "enter the code we emailed you" box (spec 2026-10-09 §6, §10).
 *
 * One box only. `autocomplete="one-time-code"` is the standard way a page names
 * it; without that, the page's ONLY text box, on a page with no password box,
 * whose own name says code, is one. A name alone is weak evidence -- a login's
 * CAPTCHA or a payment's reference box say "code" too -- so it counts only when
 * nothing else on the page could be the box meant. A split input -- a box per
 * digit -- is never a single box, so the student types it from the panel.
 *
 * ponytail: split inputs are left to the student. Type one character per box
 * when a measured portal uses one.
 */
import { entry } from "./credentials.js";
import { fillVerified } from "./fill.js";
import { accessibleName } from "./snapshot.js";
import { visible } from "./verify.js";

/** The server's own rule (apps/mailbox/actions.py: isalnum, at most 12). */
export const CODE_RE = /^[A-Za-z0-9]{1,12}$/;

const BOXES = 'input:not([type]), input[type="text"], input[type="tel"], input[type="number"]';
const CODE_WORDS = /code|otp|one.?time|verif|token|kod|код|doğrula|bestätig/i;
// "Postal code", "Course code", a login's "Security code" CAPTCHA, a payment's
// "Bank reference code": a code of another kind. An emailed code typed into one
// of these is the mistake this list exists to prevent.
const NOT_CODE_WORDS =
  /postal|zip|post.?code|course|program|promo|discount|coupon|referral|country|area|phone|captcha|security|reference|bank|amount|payment/i;

export function codeField(): HTMLInputElement | null {
  const boxes = Array.from(document.querySelectorAll<HTMLInputElement>(BOXES)).filter(
    (box) => visible(box) && !box.disabled && !box.readOnly,
  );
  const marked = boxes.filter((box) => box.autocomplete === "one-time-code");
  if (marked.length > 0) return marked.length === 1 ? marked[0]! : null;
  if (boxes.length !== 1) return null;
  const passwords = document.querySelectorAll<HTMLInputElement>('input[type="password"]');
  if (Array.from(passwords).some(visible)) return null;
  const named = boxes.filter((box) => {
    const name = `${accessibleName(box)} ${box.name} ${box.id} ${box.placeholder}`;
    return CODE_WORDS.test(name) && !NOT_CODE_WORDS.test(name);
  });
  return named.length === 1 ? named[0]! : null;
}

/** Type a checked code into the page's one code box. Never presses anything.
 *  True only when the box now holds exactly the code: a number box blanks
 *  letters, and a box per digit marked on its first digit takes six into one. */
export function typeCode(code: string, origin: string): boolean {
  if (origin !== location.origin || window.top !== window || !CODE_RE.test(code)) return false;
  const box = codeField();
  if (!box || (box.maxLength > 0 && box.maxLength < code.length)) return false;
  return fillVerified([entry(box, code, "portal.verification_code")], new Set()).filled.length === 1 && box.value === code;
}
