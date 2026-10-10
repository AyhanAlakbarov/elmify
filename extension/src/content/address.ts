/**
 * Did the portal refuse the tagged address? (spec §2a)
 *
 * Read the way a person reads it: the browser's own validity state, the
 * control's aria-invalid, or an error the page ties to the control. The
 * comparison is what makes the verdict evidence rather than a guess: the
 * tagged address is refused, the plain address in the same control is not,
 * and the tagged address is refused AGAIN (review I1: a slow validator makes a
 * stale error look like a refusal on the first read alone).
 *
 * Even then the comparison proves this tagged STRING was refused, not that the
 * "+" was -- a duplicate-account check refuses it just as well (review I3). So
 * only the browser's own verdict, the control's pattern or type refusing the
 * tagged value, is reported as "form"; a refusal resting on the page's script
 * is "page". Both are evidence about this student's account only
 * (apps/portals/tags.py).
 *
 * ponytail: an error the page shows anywhere else -- a banner at the top, a
 * toast -- is invisible to errorBeside(). The dock's "use my plain address"
 * button is the answer for those; widening this to page text would read
 * unrelated errors as the tag's fault for every tenant.
 */
import type { RejectionEvidence } from "../types.js";
import { retype } from "./fill.js";
import type { VerifiedEntry } from "./verify.js";

/** "kept", "unclear", or how the refusal was seen (never "student": that is
 *  the dock's button, not something the page showed). */
export type AddressVerdict = "kept" | "unclear" | Exclude<RejectionEvidence, "student">;

const CONTROLS = "input:not([type=hidden]), select, textarea, button";

/** Rendered, not merely present: Bootstrap keeps its feedback text in the DOM
 *  under `display: none` until the control is marked invalid (review I2). */
function shown(node: Element): boolean {
  if (node instanceof HTMLElement && node.hidden) return false;
  return typeof node.checkVisibility === "function"
    ? node.checkVisibility({ visibilityProperty: true, opacityProperty: true })
    : node.getClientRects().length > 0;
}

/** Errors tied to THIS control and no other (review I2): its aria-errormessage
 *  target, an aria-describedby target that is an alert (a described hint is
 *  not an error), or an alert inside the nearest ancestor holding no other
 *  control. In a flat form that ancestor does not extend past the form, so
 *  another field's alert is never read as this one's.
 *
 *  Review R2 finding 1: bounded to climb no further than the control's own
 *  `form` (or `document.body` with none). A page whose only real control is
 *  this one used to let the climb reach past the form to a site banner
 *  outside it -- there was no OTHER control anywhere to stop at, so the
 *  search kept climbing to the widest ancestor, all the way to <html>. */
function tiedErrors(element: HTMLElement): Element[] {
  const tied: Element[] = [];
  const own = element.getAttribute("aria-errormessage");
  const named = own ? document.getElementById(own) : null;
  if (named) tied.push(named);
  for (const id of (element.getAttribute("aria-describedby") ?? "").split(/\s+/)) {
    const described = id ? document.getElementById(id) : null;
    if (described?.getAttribute("role") === "alert") tied.push(described);
  }
  const boundary = (element as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).form ?? document.body;
  let group: Element | null = null;
  for (let node = element.parentElement; node; node = node.parentElement) {
    if (Array.from(node.querySelectorAll(CONTROLS)).some((other) => other !== element)) break;
    group = node;
    if (node === boundary) break;
  }
  if (group) tied.push(...Array.from(group.querySelectorAll('[role="alert"]')));
  return tied;
}

export function looksRejected(element: HTMLElement): boolean {
  if (element instanceof HTMLInputElement && !element.validity.valid) return true;
  if (element.getAttribute("aria-invalid") === "true") return true;
  return tiedErrors(element).some((node) => shown(node) && (node.textContent ?? "").trim() !== "");
}

/** The browser's own verdict that the value breaks the control's pattern or
 *  type -- the only refusal that says something about the portal (review I3). */
function nativelyRefused(element: HTMLElement): boolean {
  return (
    element instanceof HTMLInputElement &&
    (element.validity.patternMismatch || element.validity.typeMismatch)
  );
}

/** Let the page react as it would to a person leaving the field: many forms
 *  validate on blur, not on input. A focus event, never a click.
 *
 *  Also what a read-back after a write must wait through (review R2 finding
 *  2): a framework that reverts a write a tick later runs on its own timer,
 *  not on this function's blur events, and this is the one place both the
 *  refusal check and a plain-address read-back give it room to run. */
export async function settle(element: HTMLElement): Promise<void> {
  element.dispatchEvent(new FocusEvent("blur"));
  element.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 150));
}

/**
 * Check the tagged address the run just left in `item`'s control, and swap in
 * `plain` when the portal refuses it.
 *
 * `cameBackRejected` is read BEFORE the run typed anything: the page the
 * portal returned after the student pressed Submit already holds the tagged
 * address and marks it invalid. Nothing can be compared on that page -- the
 * error is the server's and stays until the next submit -- so the page's own
 * word is taken, the plain address typed, and the student submits again. The
 * extension never does.
 */
export async function checkAddress(
  item: VerifiedEntry,
  plain: string,
  cameBackRejected: boolean,
): Promise<AddressVerdict> {
  const element = item.element;
  if (!element) return "unclear";
  if (cameBackRejected) {
    retype(item, plain);
    return "after_submit";
  }
  const tagged = item.entry.value;
  await settle(element);
  if (!looksRejected(element)) return "kept";
  const native = nativelyRefused(element);

  retype(item, plain);
  await settle(element);
  if (looksRejected(element)) {
    // The plain address is refused too, so the "+" is not the reason. Put back
    // what the packet says and let the student read the portal's own error.
    retype(item, tagged);
    return "unclear";
  }

  // A-B-A (review I1): the first refusal may have been a stale error the page
  // cleared late, while the plain address was in. Only a refusal that comes
  // back for the tagged address is one; otherwise the tagged value stays.
  retype(item, tagged);
  await settle(element);
  if (!looksRejected(element)) return "unclear";
  const nativeAgain = nativelyRefused(element);

  retype(item, plain);
  await settle(element);
  // The plain read above passed looksRejected, so it passed native validity.
  return native && nativeAgain ? "form" : "page";
}
