/**
 * Type a verified value into a verified control. Nothing else.
 *
 * Ported from apps/portals/fill.py, which keeps its Python versions for the
 * packet-side unit tests. Two things are different in a browser and both are
 * load-bearing:
 *
 *  - React and every framework like it install a value setter on the element's
 *    prototype and ignore a plain `element.value = x`. The native setter plus
 *    input/change events is the standard technique, and read-back is what
 *    catches the pages where even that is not enough.
 *  - There is no click anywhere in this file, including for a <select>.
 *    selectOption sets `value` and fires change; the dropdown is never opened.
 */
import type { VerifiedEntry } from "./verify.js";
import { accessibleName } from "./snapshot.js";
import { normalise } from "./vocabulary.js";

/** Mirrors apps/portals/session.py::FILL_METHODS. The parity test pins it. */
const FILL_METHODS = ["fill", "type", "selectOption", "selectOptionFromDropdown"] as const;

function nativeSetValue(element: HTMLElement, value: string): void {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  if (setter) setter.call(element, value);
  else (element as HTMLInputElement).value = value;
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function currentValue(element: HTMLElement): string {
  return (element as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value ?? "";
}

/** Fields the page already holds correctly -- the only ones safe to skip.
 *  A portal that persisted its own draft returns most of them. */
export function alreadyCorrect(verified: VerifiedEntry[]): Set<string> {
  const correct = new Set<string>();
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    if (currentValue(item.element) === item.entry.value) correct.add(item.entry.profile_field);
  }
  return correct;
}

/** Type every verified entry not in `skip`. Returns the fields filled.
 *
 *  Only entries that PASSED verification are here at all: the caller filters
 *  first, so there is no path through this function that types into a control
 *  verify.ts refused. */
export function fillVerified(verified: VerifiedEntry[], skip: Set<string>): string[] {
  const filled: string[] = [];
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    if (skip.has(item.entry.profile_field)) continue;
    // Redundant today -- verify.ts refuses method_not_allowed before an entry
    // can arrive here with ok=true -- and it stays. It is the allowlist on the
    // one function in this extension that writes into a page, and the cost of
    // keeping it is a line. A reviewer has already proposed deleting it once.
    if (!FILL_METHODS.includes(item.entry.method as (typeof FILL_METHODS)[number])) continue;
    if (item.entry.method.startsWith("selectOption") && item.element instanceof HTMLSelectElement) {
      const option = Array.from(item.element.options).find(
        (candidate) => candidate.value === item.entry.value || candidate.text === item.entry.value,
      );
      // No option, no guess: an unmatched select is the student's to answer.
      if (!option) continue;
      nativeSetValue(item.element, option.value);
    } else {
      nativeSetValue(item.element, item.entry.value);
    }
    filled.push(item.entry.profile_field);
  }
  return filled;
}

/** Type a different value into a control that already passed verification --
 *  the plain address where a portal refused the tagged one (address.ts).
 *  Through fillVerified, so the method allowlist still guards the write. */
export function retype(item: VerifiedEntry, value: string): void {
  fillVerified([{ ...item, entry: { ...item.entry, value } }], new Set());
}

/** What the page holds now, against what the packet says it should.
 *  Runs against the RENDERED page, never against what we believe we typed. */
export function readBack(
  verified: VerifiedEntry[],
): { profile_field: string; expected: string; actual: string }[] {
  const mismatches = [];
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    const actual = currentValue(item.element);
    if (actual !== item.entry.value) {
      mismatches.push({
        profile_field: item.entry.profile_field,
        expected: item.entry.value,
        actual,
      });
    }
  }
  return mismatches;
}

const CV_TERMS = ["cv", "resume", "curriculum"];

/** Terms an input's label must mention for THIS document to belong in it.
 *
 *  The filename is everything the packet says about a document: PacketDocument
 *  carries filename, download_path and draft_id, and no kind or label. So the
 *  name is what has to find the right slot.
 *
 *  Nothing changes today. `packets.py::_kit_documents` filters to Kind.CV, so
 *  every packet document is `cv-<variant>.pdf` and yields the CV synonyms the
 *  predicate used to hardcode. What changes is the day a second kind gets a
 *  rendered artefact -- which that function's own docstring says is coming.
 *  Until now the predicate ignored the document entirely, so whichever file the
 *  packet happened to list first took the CV input, whatever that file was. */
function documentTerms(filename: string): string[] {
  const words = normalise(filename.replace(/\.[^.]+$/, "")).split(" ");
  if (words.some((word) => CV_TERMS.includes(word))) return CV_TERMS;
  // A bare number is not a name; "transcript-2026" must not match an input
  // labelled "2026".
  return words.filter((word) => word.length > 2 && !/^\d+$/.test(word));
}

/** The one operation beyond typing, and it is not a click.
 *
 *  `setFiles` writes a DataTransfer onto a native file input. Custom
 *  drag-and-drop and direct-to-S3 widgets expose no such input; those become a
 *  dock instruction ("attach cv.pdf here"), which is the honest answer and the
 *  one the spec's Risks section chose. */
export function attachDocuments(
  documents: { filename: string; bytes: ArrayBuffer }[],
): { attached: { filename: string; method: string }[]; manual: string[] } {
  const inputs = Array.from(document.querySelectorAll("input[type=file]")).filter(
    (input): input is HTMLInputElement => input instanceof HTMLInputElement && !input.disabled,
  );
  const attached: { filename: string; method: string }[] = [];
  const manual: string[] = [];
  for (const item of documents) {
    const terms = documentTerms(item.filename);
    // Match the input's own name against THIS document's name -- the same
    // accessible name the verification check reads. No match, no guess.
    const target = inputs.find((input) => {
      const name = normalise(accessibleName(input));
      return terms.some((term) => name.includes(term));
    });
    if (!target) {
      manual.push(item.filename);
      continue;
    }
    const transfer = new DataTransfer();
    transfer.items.add(new File([item.bytes], item.filename, { type: "application/pdf" }));
    target.files = transfer.files;
    target.dispatchEvent(new Event("change", { bubbles: true }));
    // "setFiles" ships here, as real data in the FILL event's detail, never
    // as a page-DOM marker -- that would fingerprint the portal's own page.
    // It is this file's own vocabulary and is never a server FILL_METHODS
    // entry (see this file's own docstring above).
    attached.push({ filename: item.filename, method: "setFiles" });
    inputs.splice(inputs.indexOf(target), 1);
  }
  return { attached, manual };
}
