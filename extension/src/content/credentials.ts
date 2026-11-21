/**
 * The portal's own login and sign-up pages (spec 2026-10-09 §6, D3).
 *
 * Read the way a password manager reads them, not from a FieldMap: a password
 * box is the one control a page cannot disguise, so the page kind and the
 * password boxes come from `type="password"` alone. The address goes into the
 * one box before the first password box that asks for it -- and when that is
 * not exactly one box, nothing is typed at all, because a password in the
 * wrong box is the mistake this file exists not to make. Never clicks: the
 * student presses Log in / Register.
 *
 * ponytail: a login whose username is a portal-issued number gets the address
 * typed into its one box and the portal refuses it -- the student logs in, as
 * before this plan. Learn the username box from the bench (plan 6) when a
 * measured portal needs it.
 */
import { fillVerified, onScreen } from "./fill.js";
import type { VerifiedEntry } from "./verify.js";
import { visible } from "./verify.js";

export interface CredentialPage {
  kind: "login" | "signup";
  identifier: HTMLInputElement;
  passwords: HTMLInputElement[];
  /** The smallest maxlength any password box declares, or undefined. */
  maxLength?: number;
}

const BOXES = 'input[type="email"], input[type="text"], input:not([type])';
const PASSWORDS = 'input[type="password"]';
/** Site furniture: a search or newsletter box there is never the login's. */
const FURNITURE = 'header, nav, footer, aside, [role="search"], [role="banner"], [role="navigation"]';

/** A box a person can see and reach. Stricter than verify.ts's `visible`: an
 *  off-screen, covered, unfocusable or aria-hidden box is the shape of a
 *  honeypot, and a password typed into one is a password the portal keeps.
 *  onScreen rejects off the left and top only; the right edge is checked here
 *  because attachDocuments relies on onScreen as it is. */
export function usable(input: HTMLInputElement): boolean {
  return (
    onScreen(input) &&
    input.getBoundingClientRect().left < window.innerWidth &&
    !input.disabled &&
    !input.readOnly &&
    input.getAttribute("tabindex") !== "-1" &&
    !input.closest('[aria-hidden="true"]')
  );
}

/** A box the student can see but not reach: something sits over its centre,
 *  such as a cookie notice. Boxes off the viewport or faded out are not this. */
export function covered(input: HTMLInputElement): boolean {
  if (!visible(input)) return false;
  const r = input.getBoundingClientRect();
  const x = r.left + r.width / 2;
  const y = r.top + r.height / 2;
  if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return false;
  const top = document.elementFromPoint(x, y);
  return top !== null && !input.contains(top);
}

/** A box the address could go in, for the login whose first password box is
 *  `first`. Furniture is furniture only when the login is not inside it too:
 *  a login widget in an <aside> or the <header> is still a login. */
function candidate(input: HTMLInputElement, first: HTMLInputElement): boolean {
  const furniture = input.closest(FURNITURE);
  return input.type !== "search" && (!furniture || furniture.contains(first)) && usable(input);
}

/** The nearest ancestor of the first password box holding a candidate box:
 *  where the address box is chosen. Never above the password box's own form
 *  (one <form> wrapping a whole ASP.NET page holds the header's newsletter
 *  box too), and with no form, reaching <body> means the page has no login
 *  of its own -- a reset page with a header search box, say. */
function addressArea(first: HTMLInputElement): Element | null {
  for (let node = first.parentElement; node; node = node.parentElement) {
    if (!first.form && (node === document.body || node === document.documentElement)) return null;
    if (Array.from(node.querySelectorAll<HTMLInputElement>(BOXES)).some((box) => candidate(box, first))) return node;
    if (node === first.form) return null;
  }
  return null;
}

/** The address box: the single email-like box before the first password box,
 *  or else the single box of any kind there. Null when neither is single. */
function identifierFor(first: HTMLInputElement, area: Element): HTMLInputElement | null {
  const before = Array.from(area.querySelectorAll<HTMLInputElement>(BOXES)).filter(
    (input) => candidate(input, first) && (first.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_PRECEDING) !== 0,
  );
  const emailLike = before.filter(
    (input) => input.type === "email" || ["email", "username"].includes(input.autocomplete),
  );
  if (emailLike.length === 1) return emailLike[0]!;
  return emailLike.length === 0 && before.length === 1 ? before[0]! : null;
}

export function credentialPage(): CredentialPage | null {
  const first = Array.from(document.querySelectorAll<HTMLInputElement>(PASSWORDS)).find(usable);
  if (!first) return null;
  const area = addressArea(first);
  if (!area) return null;
  // The password boxes are the form's (a repeat box may sit in its own row),
  // or the address area's when there is no form. Never the page's.
  const scope: ParentNode = first.form ?? area;
  const passwords = Array.from(scope.querySelectorAll<HTMLInputElement>(PASSWORDS)).filter(usable);
  // Three or more is a change-password page or something stranger: not ours.
  if (passwords.length > 2) return null;
  // A password box with an address area of its own that the first box is not
  // in belongs to another panel -- one ASP.NET <form> holding a login and a
  // register panel. Typing one password into both is the mistake.
  const foreign = (box: HTMLInputElement) => {
    const own = addressArea(box);
    return own !== null && !own.contains(first);
  };
  if (passwords.some(foreign)) return null;
  // A login box beside another password box is a change of password, or two
  // panels: never a sign-up.
  if (passwords.length > 1 && passwords.some((box) => box.autocomplete === "current-password")) return null;
  const identifier = identifierFor(first, area);
  if (!identifier) return null;
  const signup = passwords.length === 2 || passwords.some((box) => box.autocomplete === "new-password");
  const caps = passwords.map((box) => box.maxLength).filter((n) => n > 0);
  return {
    kind: signup ? "signup" : "login",
    identifier,
    passwords,
    ...(caps.length ? { maxLength: Math.min(...caps) } : {}),
  };
}

/** Is `value` the tagged form of `plain` -- `local+tag@domain` (apps/portals/tags.py)? */
export function taggedFormOf(value: string, plain: string): boolean {
  const at = plain.lastIndexOf("@");
  const valueAt = value.lastIndexOf("@");
  if (at <= 0 || valueAt <= at + 1) return false;
  const local = plain.slice(0, at);
  return (
    value.slice(valueAt).toLowerCase() === plain.slice(at).toLowerCase() &&
    value.startsWith(`${local}+`) &&
    !value.slice(at + 1, valueAt).includes("@")
  );
}

export function entry(element: HTMLInputElement, value: string, key: string): VerifiedEntry {
  return { entry: { selector: "", method: "fill", value, profile_field: key }, element, ok: true, reason: "" };
}

/** The same address, as a person would compare it. */
export function sameAddress(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase();
}

/** True only when every box now holds what we typed. fillVerified never types
 *  over a box holding the student's own text, so a partial result means the
 *  student is already doing it, and they finish. An address box already
 *  holding the username (a remembered login) is left exactly as it is. */
export function typeCredentials(page: CredentialPage, username: string, password: string): boolean {
  // The worker was asked between reading these boxes and now: a box the page
  // hid, locked or replaced meanwhile gets nothing, and neither do the others.
  const boxes = [page.identifier, ...page.passwords];
  if (!boxes.every((box) => box.isConnected && usable(box))) return false;
  const items = [
    ...(sameAddress(page.identifier.value, username) ? [] : [entry(page.identifier, username, "portal.username")]),
    ...page.passwords.map((box, i) => entry(box, password, `portal.password.${i}`)),
  ];
  return fillVerified(items, new Set()).filled.length === items.length;
}
