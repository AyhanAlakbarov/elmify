/**
 * The portal's "enter the code we emailed you" box or split digit boxes
 * (spec 2026-10-09 §6, §10).
 *
 * `autocomplete="one-time-code"` is the standard way a page names a single code
 * box or the first digit of a split input; without that, the page's ONLY text
 * box (or a row of `maxlength="1"` digit boxes), on a page with no password
 * box, whose own name says code/digit, is matched. A name alone is weak
 * evidence -- a login's CAPTCHA or a payment's reference box say "code" too --
 * so it counts only when nothing else on the page could be the box meant.
 */
import { entry } from "./credentials.js";
import { fillVerified } from "./fill.js";
import { accessibleName } from "./snapshot.js";
import { visible } from "./verify.js";

/** The server's own rule (apps/mailbox/actions.py: isalnum, at most 12). */
export const CODE_RE = /^[A-Za-z0-9]{1,12}$/;

const BOXES = 'input:not([type]), input[type="text"], input[type="tel"], input[type="number"]';
const CODE_WORDS = /code|otp|one.?time|verif|token|kod|код|doğrula|bestätig/i;
const SPLIT_DIGIT_WORDS = /\bdigit\b|\bchar\b|\bpin\b|code|otp|one.?time|verif|kod|код/i;
// "Postal code", "Course code", a login's "Security code" CAPTCHA, a payment's
// "Bank reference code": a code of another kind. An emailed code typed into one
// of these is the mistake this list exists to prevent.
const NOT_CODE_WORDS =
  /postal|zip|post.?code|course|program|promo|discount|coupon|referral|country|area|phone|captcha|security|reference|bank|amount|payment/i;

function boxName(box: HTMLInputElement): string {
  return `${accessibleName(box)} ${box.name} ${box.id} ${box.placeholder}`;
}

export function codeFields(): HTMLInputElement[] | null {
  const boxes = Array.from(document.querySelectorAll<HTMLInputElement>(BOXES)).filter(
    (box) => visible(box) && !box.disabled && !box.readOnly,
  );
  const marked = boxes.filter((box) => box.autocomplete === "one-time-code");
  if (marked.length > 0) {
    if (marked.length === 1) {
      if (
        marked[0]!.maxLength === 1 &&
        boxes.length >= 2 &&
        boxes.length <= 12 &&
        boxes.every((b) => b.maxLength === 1 && !NOT_CODE_WORDS.test(boxName(b)))
      ) {
        return boxes;
      }
      return [marked[0]!];
    }
    if (marked.length <= 12 && marked.every((b) => b.maxLength === 1 && !NOT_CODE_WORDS.test(boxName(b)))) {
      return marked;
    }
    return null;
  }
  const passwords = document.querySelectorAll<HTMLInputElement>('input[type="password"]');
  if (Array.from(passwords).some(visible)) return null;
  if (boxes.length === 1) {
    const name = boxName(boxes[0]!);
    return CODE_WORDS.test(name) && !NOT_CODE_WORDS.test(name) ? [boxes[0]!] : null;
  }
  if (
    boxes.length >= 4 &&
    boxes.length <= 12 &&
    boxes.every((b) => b.maxLength === 1 && !NOT_CODE_WORDS.test(boxName(b))) &&
    boxes.some((b) => SPLIT_DIGIT_WORDS.test(boxName(b)))
  ) {
    return boxes;
  }
  return null;
}

export function codeField(): HTMLInputElement | null {
  return codeFields()?.[0] ?? null;
}

/** Type a checked code into the page's code box (or 1-char split digit boxes).
 *  Never presses anything. True only when the box(es) now hold the exact code. */
export function typeCode(code: string, origin: string): boolean {
  if (origin !== location.origin || window.top !== window || !CODE_RE.test(code)) return false;
  const boxes = codeFields();
  if (!boxes || boxes.length === 0) return false;
  if (boxes.length === 1) {
    const box = boxes[0]!;
    if (box.maxLength > 0 && box.maxLength < code.length) return false;
    return (
      fillVerified([entry(box, code, "portal.verification_code")], new Set()).filled.length === 1 &&
      box.value === code
    );
  }
  if (boxes.length !== code.length || boxes.some((b) => b.value !== "")) return false;
  const items = boxes.map((box, i) => entry(box, code[i]!, `portal.verification_code.${i}`));
  return (
    fillVerified(items, new Set()).filled.length === items.length &&
    boxes.map((b) => b.value).join("") === code
  );
}
