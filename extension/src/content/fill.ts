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
import { GROUPS } from "./snapshot.js";
import { fieldClass, visible } from "./verify.js";
import type { VerifiedEntry } from "./verify.js";
import { DOC_TOKENS, normalise, normaliseDoc } from "./vocabulary.js";

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

/** Select values a page uses for "nothing chosen yet". */
const PLACEHOLDERS = ["", "-1", "0", "none", "null"];

function currentValue(element: HTMLElement): string {
  return (element as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value ?? "";
}

type Ymd = [number, number, number];

/** Every reading of a written date: one for YYYY-MM-DD (or YYYY-MM / MM/YYYY);
 *  for D/M/YYYY one when the day is over 12 or day equals month, two when both
 *  orders make sense. Month-only dates use day=0 so they never equal a full date. */
function readings(text: string): Ymd[] {
  const trimmed = text.trim();
  const iso = /^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$/.exec(trimmed);
  if (iso) return [[Number(iso[1]), Number(iso[2]), Number(iso[3])]];
  const isoMonth = /^(\d{4})[-./](\d{1,2})$/.exec(trimmed);
  if (isoMonth) {
    const [y, m] = [Number(isoMonth[1]), Number(isoMonth[2])];
    return m >= 1 && m <= 12 ? [[y, m, 0]] : [];
  }
  const monthYear = /^(\d{1,2})[-./](\d{4})$/.exec(trimmed);
  if (monthYear) {
    const [m, y] = [Number(monthYear[1]), Number(monthYear[2])];
    return m >= 1 && m <= 12 ? [[y, m, 0]] : [];
  }
  const other = /^(\d{1,2})[-./](\d{1,2})[-./](\d{4})$/.exec(trimmed);
  if (!other) return [];
  const [a, b, y] = [Number(other[1]), Number(other[2]), Number(other[3])];
  const out: Ymd[] = [];
  if (b <= 12 && a <= 31) out.push([y, b, a]); // day first
  if (a <= 12 && b <= 31 && a !== b) out.push([y, a, b]); // month first
  return out;
}

const digitsOf = (s: string): string => s.replace(/\D+/g, "");

/** Read-back equivalences the bench taught for one portal (plan 6). Each one
 *  widens equality for its own field class only, and never to "anything". */
const EQUIVALENCE: Record<string, (actual: string, expected: string) => boolean> = {
  // Upper case on both sides, not lower: "Işıl" and "IŞIL" lower to "ışıl" and
  // "işil", while both upper to "IŞIL" -- dotted and dotless i collapse the way
  // a portal's own uppercasing collapses them.
  casefold: (actual, expected) => actual.toLocaleUpperCase() === expected.toLocaleUpperCase(),
  collapse_spaces: (actual, expected) =>
    actual.replace(/\s+/g, " ").trim() === expected.replace(/\s+/g, " ").trim(),
  digits: (actual, expected) =>
    digitsOf(expected) !== "" && digitsOf(actual) === digitsOf(expected),
  // A date compares as a date only when both sides read one way; an ambiguous
  // 07.03.2001 stays amber, and the fix is a value_formats rule instead.
  date: (actual, expected) => {
    const [x, y] = [readings(actual), readings(expected)];
    return x.length === 1 && y.length === 1 && x[0]!.join("-") === y[0]!.join("-");
  },
};

export function sameValue(actual: string, expected: string, rule: string | undefined): boolean {
  if (actual === expected) return true;
  if (rule === undefined || !Object.hasOwn(EQUIVALENCE, rule)) return false;
  return EQUIVALENCE[rule]?.(actual, expected) ?? false;
}

const OPTION_SYNONYM_GROUPS: readonly (readonly string[])[] = [
  ["yes", "true", "ja", "oui", "beli", "evet", "да"],
  ["no", "false", "nein", "non", "xeyr", "hayir", "нет"],
  [
    "azerbaijan",
    "azerbaijani",
    "republic of azerbaijan",
    "az",
    "aze",
    "azerbaycan",
    "aserbaidschan",
    "azerbaidjan",
    "азербайджан",
  ],
  ["turkey", "turkiye", "republic of turkiye", "tr", "tur", "turkei", "turquie", "турция"],
  ["germany", "deutschland", "federal republic of germany", "de", "deu", "allemagne", "германия"],
  ["united kingdom", "great britain", "uk", "gb", "gbr", "vereinigtes konigreich", "royaume uni"],
  ["united states", "united states of america", "usa", "us", "vereinigte staaten", "etats unis"],
];

/** Find the one <option> a <select> offers for `target`:
 *   1. Exact value or text match;
 *   2. Case-insensitive trimmed value or text match (excluding placeholders);
 *   3. Single unambiguous word-boundary match in option text (e.g. "Azerbaijan"
 *      matching "Azerbaijan (+994)" or "AZ - Azerbaijan");
 *   4. Single unambiguous match within a known boolean or country synonym group.
 *  If two options match at any fallback tier, returns undefined so the student decides. */
export function matchSelectOption(
  select: HTMLSelectElement,
  target: string,
): HTMLOptionElement | undefined {
  const options = Array.from(select.options);
  const exact = options.find((opt) => opt.value === target || opt.text === target);
  if (exact) return exact;
  const trimmed = target.trim().toLowerCase();
  if (!trimmed) return undefined;
  const nonPlaceholder = options.filter(
    (opt) => !opt.disabled && !PLACEHOLDERS.includes(opt.value.trim().toLowerCase()),
  );
  const ci = nonPlaceholder.filter(
    (opt) => opt.value.trim().toLowerCase() === trimmed || opt.text.trim().toLowerCase() === trimmed,
  );
  if (ci.length === 1) return ci[0];
  const norm = normalise(target);
  if (norm.length >= 2) {
    const paddedTarget = ` ${norm} `;
    const partial = nonPlaceholder.filter((opt) =>
      ` ${normalise(opt.text)} `.includes(paddedTarget),
    );
    if (partial.length === 1) return partial[0];
  }
  const group = OPTION_SYNONYM_GROUPS.find((synonyms) => synonyms.includes(norm));
  if (group) {
    const groupSet = new Set(group);
    const exactSyn = nonPlaceholder.filter(
      (opt) => groupSet.has(normalise(opt.value)) || groupSet.has(normalise(opt.text)),
    );
    if (exactSyn.length === 1) return exactSyn[0];
    const longSyns = group.filter((s) => s.length >= 4);
    const wordSyn = nonPlaceholder.filter((opt) => {
      const padded = ` ${normalise(opt.text)} `;
      return longSyns.some((s) => padded.includes(` ${s} `));
    });
    if (wordSyn.length === 1) return wordSyn[0];
  }
  return undefined;
}

/** Fields the page already holds correctly -- the only ones safe to skip.
 *  A portal that persisted its own draft returns most of them. */
export function alreadyCorrect(
  verified: VerifiedEntry[],
  equivalences: Record<string, string> = {},
): Set<string> {
  const correct = new Set<string>();
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    const actual = currentValue(item.element);
    const rule = equivalences[fieldClass(item.entry.profile_field)];
    const selectMatch =
      item.element instanceof HTMLSelectElement &&
      matchSelectOption(item.element, item.entry.value)?.value === actual;
    if (sameValue(actual, item.entry.value, rule) || selectMatch) {
      correct.add(item.entry.profile_field);
    }
  }
  return correct;
}

/** Type every verified entry not in `skip`. Returns the fields filled.
 *
 *  Only entries that PASSED verification are here at all: the caller filters
 *  first, so there is no path through this function that types into a control
 *  verify.ts refused. */
export function fillVerified(
  verified: VerifiedEntry[],
  skip: Set<string>,
  overwrite = false, // retype only: replacing a value WE typed
): { filled: string[]; theirs: Set<string> } {
  const filled: string[] = [];
  // Controls holding something other than our value: the student's, left alone.
  const theirs = new Set<string>();
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    if (skip.has(item.entry.profile_field)) continue;
    // Redundant today -- verify.ts refuses method_not_allowed before an entry
    // can arrive here with ok=true -- and it stays. It is the allowlist on the
    // one function in this extension that writes into a page, and the cost of
    // keeping it is a line. A reviewer has already proposed deleting it once.
    if (!FILL_METHODS.includes(item.entry.method as (typeof FILL_METHODS)[number])) continue;
    if (item.entry.method.startsWith("selectOption") && item.element instanceof HTMLSelectElement) {
      const option = matchSelectOption(item.element, item.entry.value);
      // No option, no guess: an unmatched select is the student's to answer.
      if (!option) continue;
      const held = currentValue(item.element);
      const chosen =
        item.element.selectedIndex > 0 && !PLACEHOLDERS.includes(held.trim().toLowerCase());
      if (!overwrite && chosen && held !== option.value) { theirs.add(item.entry.profile_field); continue; }
      nativeSetValue(item.element, option.value);
    } else {
      const held = currentValue(item.element);
      if (!overwrite && held !== "" && held !== item.entry.value) { theirs.add(item.entry.profile_field); continue; }
      nativeSetValue(item.element, item.entry.value);
    }
    filled.push(item.entry.profile_field);
  }
  return { filled, theirs };
}

/** Type a different value into a control that already passed verification --
 *  the plain address where a portal refused the tagged one (address.ts).
 *  Through fillVerified, so the method allowlist still guards the write. */
export function retype(item: VerifiedEntry, value: string): void {
  fillVerified([{ ...item, entry: { ...item.entry, value } }], new Set(), true);
}

/** What the page holds now, against what the packet says it should.
 *  Runs against the RENDERED page, never against what we believe we typed. */
export function readBack(
  verified: VerifiedEntry[],
  equivalences: Record<string, string> = {},
): { profile_field: string; expected: string; actual: string }[] {
  const mismatches = [];
  for (const item of verified) {
    if (!item.ok || !item.element) continue;
    const actual = currentValue(item.element);
    const selectMatch =
      item.element instanceof HTMLSelectElement &&
      matchSelectOption(item.element, item.entry.value)?.value === actual;
    if (
      !sameValue(actual, item.entry.value, equivalences[fieldClass(item.entry.profile_field)]) &&
      !selectMatch
    ) {
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
 *  The name-match path, for a document the packet gives no learned box
 *  (`selector` null): then the filename is what has to find the right slot.
 *  A slot document never comes here -- see attachDocuments. Before this, the
 *  predicate ignored the document entirely, so whichever file the packet
 *  happened to list first took the CV input, whatever that file was. */
function documentTerms(filename: string): string[] {
  const words = normalise(filename.replace(/\.[^.]+$/, "")).split(" ");
  if (words.some((word) => CV_TERMS.includes(word))) return CV_TERMS;
  // A bare number is not a name; "transcript-2026" must not match an input
  // labelled "2026".
  return words.filter((word) => word.length > 2 && !/^\d+$/.test(word));
}

// Specific phrases only: a bare "certificate", "letter" or "statement" names
// several kinds of document ("Bank statement", "Language certificate").
const KIND_TERMS: Record<string, string[]> = {
  CV: ["cv", "resume", "curriculum vitae", "lebenslauf"],
  MOTIVATION_LETTER: [
    "motivation letter", "letter of motivation", "motivation", "statement of purpose", "personal statement",
  ],
  REFERENCE_LETTER: ["recommendation", "reference letter", "letter of reference", "referee"],
  TRANSCRIPT: ["transcript", "academic record", "grade list", "record of studies"],
  DIPLOMA: ["diploma", "degree certificate", "bachelor's certificate", "master's certificate"],
  PASSPORT: ["passport"],
  LANGUAGE_CERTIFICATE: ["ielts", "toefl", "language certificate", "language test", "cefr"],
};

/** The one kind a box's visible text names, or null when it names none or
 *  several: such a box takes no kind-matched document. */
function boxKinds(text: string): string[] {
  const name = ` ${normalise(text)} `;
  // A word start, an optional plural ending (s, es), then a word end: "cvs" is CV, "cvsomething" is not.
  return Object.keys(KIND_TERMS).filter((kind) =>
    KIND_TERMS[kind]!.some((term) => {
      const at = ` ${normalise(term)}`;
      return [" ", "s ", "es "].some((end) => name.includes(at + end));
    }),
  );
}

function boxKind(text: string): string | null {
  const hits = boxKinds(text);
  return hits.length === 1 ? hits[0]! : null;
}

/** Stricter than `visible`, for the label that stands in for a hidden input:
 *  big enough to click, not parked off the page, not faded out by an ancestor,
 *  and not covered by something else at its centre. */
export function onScreen(el: HTMLElement): boolean {
  if (!visible(el)) return false;
  for (let e: Element | null = el; e; e = e.parentElement) {
    if (getComputedStyle(e).opacity === "0") return false;
  }
  const r = el.getBoundingClientRect();
  if (r.width < 4 || r.height < 4) return false;
  if (r.right + window.scrollX <= 0 || r.bottom + window.scrollY <= 0) return false;
  const x = r.left + r.width / 2;
  const y = r.top + r.height / 2;
  if (x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight) {
    const top = document.elementFromPoint(x, y);
    return !!top && el.contains(top);
  }
  return true;
}

export interface Attachment {
  filename: string;
  bytes: ArrayBuffer;
  /** The learned upload box; absent or null keeps the name-match path. */
  selector?: string | null;
  kind?: string;
  /** The file's content type; else read from its filename, else PDF. */
  type?: string;
  /** The student picked this box in the panel: their pick is the authority on
   *  which box, never on whether they can see it. */
  chosen?: boolean;
}

/** The labels that open this file input: its own <label for>, and a wrapping
 *  label that holds no other file input (one wrapping several names none). */
function labelsFor(input: HTMLInputElement): HTMLElement[] {
  const labels = Array.from(
    input.id ? document.querySelectorAll<HTMLElement>(`label[for="${CSS.escape(input.id)}"]`) : [],
  );
  const wrapping = input.closest("label");
  if (wrapping && wrapping.querySelectorAll("input[type=file]").length === 1) labels.push(wrapping);
  return labels;
}

/** What the student would use to open this file input: the input itself when
 *  visible, else an on-screen label for it; null when there is neither. */
export function openerFor(input: HTMLInputElement): HTMLElement | null {
  if (visible(input)) return input;
  return labelsFor(input).find(onScreen) ?? null;
}

/** The one element a selector matches, or null (none, several, or a malformed selector). */
export function soleMatch(selector: string): Element | null {
  try {
    const matches = document.querySelectorAll(selector);
    return matches.length === 1 ? (matches[0] ?? null) : null;
  } catch {
    return null;
  }
}

/** The one enabled file input a selector names, or null. */
export function soleFileInput(selector: string): HTMLInputElement | null {
  const only = soleMatch(selector);
  return only instanceof HTMLInputElement && only.type === "file" && !only.disabled ? only : null;
}

/** Does what the student can SEE at this box name the document's kind? The
 *  live elements' innerText, never a clone's textContent: text hidden from the
 *  student must not name a box (test_text_the_student_cannot_see_...). */
function carriesKind(input: HTMLInputElement, opener: HTMLElement, kind: string): boolean {
  const group = input.closest<HTMLElement>(GROUPS);
  const seen = [
    opener === input ? "" : opener.innerText,
    ...labelsFor(input).filter(onScreen).map((label) => label.innerText),
    group?.innerText ?? "",
  ].join(" ");
  const padded = ` ${normaliseDoc(seen)} `;
  return (DOC_TOKENS[kind] ?? [])
    .map(normaliseDoc)
    .filter((token) => token !== "")
    .some((token) => padded.includes(` ${token} `));
}

const FILE_TYPES: Record<string, string> = { png: "image/png", jpg: "image/jpeg" };

function setFile(input: HTMLInputElement, item: Attachment): void {
  const suffix = item.filename.split(".").pop()?.toLowerCase() ?? "";
  const transfer = new DataTransfer();
  transfer.items.add(
    new File([item.bytes], item.filename, { type: FILE_TYPES[suffix] ?? (item.type || "application/pdf") }),
  );
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

/** The one operation beyond typing, and it is not a click.
 *
 *  `setFiles` writes a DataTransfer onto a native file input. Custom
 *  drag-and-drop and direct-to-S3 widgets expose no such input; those become a
 *  dock instruction ("attach cv.pdf here"), which is the honest answer and the
 *  one the spec's Risks section chose.
 *
 *  A document with a learned `selector` goes only into that box, and only when
 *  the student can see it and its visible text names the document's kind (or
 *  the student picked it). A refusal there is the student's turn, never a
 *  second guess by name. */
export function attachDocuments(
  documents: Attachment[],
  /** Every box this call fills is added here, so a later pick never lands on it. */
  filled: Set<HTMLInputElement> = new Set(),
): { attached: { filename: string; method: string }[]; manual: string[] } {
  // A document goes only into a control the student can see: the input, or the
  // on-screen label that opens it (the "pretty button over a hidden input"
  // case). `text` is what the student can read there, and the only thing the
  // document's name is matched against -- never hidden markup.
  const openers = new Map<HTMLInputElement, string>();
  for (const input of Array.from(document.querySelectorAll("input[type=file]"))) {
    if (!(input instanceof HTMLInputElement) || input.disabled) continue;
    const opener = openerFor(input);
    if (!opener) continue;
    // A hidden input's aria-label is text the student cannot read.
    const text =
      opener === input
        ? [
            ...labelsFor(input).filter(onScreen).map((label) => label.innerText),
            input.getAttribute("aria-label") ?? "",
          ]
        : [opener.innerText];
    openers.set(input, text.join(" "));
  }
  const inputs = Array.from(openers.keys());
  const attached: { filename: string; method: string }[] = [];
  const manual: string[] = [];
  // Slot documents first, so a name match never takes the box a slot names.
  const ordered = [
    ...documents.filter((item) => item.selector),
    ...documents.filter((item) => !item.selector),
  ];
  for (const item of ordered) {
    if (item.selector) {
      const input = soleFileInput(item.selector);
      const opener = input ? openerFor(input) : null;
      const shown = input !== null && opener !== null && onScreen(opener);
      const named =
        shown && (item.chosen === true || carriesKind(input, opener, item.kind ?? ""));
      if (!input || !named || filled.has(input)) {
        manual.push(item.filename);
        continue;
      }
      setFile(input, item);
      filled.add(input);
      attached.push({ filename: item.filename, method: "setFiles" });
      const at = inputs.indexOf(input);
      if (at >= 0) inputs.splice(at, 1);
      continue;
    }
    let target: HTMLInputElement | undefined;
    if (item.kind === "EVERY_DOCUMENT") {
      // The whole-application bundle goes only where there is one box to take it.
      if (openers.size === 1) target = inputs[0];
    } else if (item.kind) {
      target = inputs.find((input) => boxKind(openers.get(input) ?? "") === item.kind);
    } else {
      // Match the input's own name against THIS document's name -- the same
      // accessible name the verification check reads. No match, no guess.
      const terms = documentTerms(item.filename);
      const own = boxKinds(item.filename.replace(/\.[^.]+$/, ""));
      target = inputs.find((input) => {
        const name = normalise(openers.get(input) ?? "");
        // Exclusive like kinds: a box naming a kind the filename does not is that kind's box.
        return boxKinds(name).every((kind) => own.includes(kind)) && terms.some((term) => name.includes(term));
      });
    }
    if (!target) {
      manual.push(item.filename);
      continue;
    }
    setFile(target, item);
    filled.add(target);
    // "setFiles" ships here, as real data in the FILL event's detail, never
    // as a page-DOM marker -- that would fingerprint the portal's own page.
    // It is this file's own vocabulary and is never a server FILL_METHODS
    // entry (see this file's own docstring above).
    attached.push({ filename: item.filename, method: "setFiles" });
    inputs.splice(inputs.indexOf(target), 1);
  }
  return { attached, manual };
}
