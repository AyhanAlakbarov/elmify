/**
 * Does this selector name the control the packet thinks it does?
 *
 * The server cannot answer this: it never saw the page, and a FieldMap
 * learned from a snapshot is a CLAIM by a client. Read-back cannot answer it
 * either -- it reads back the selector it typed into and finds the value
 * sitting there, so a wrong-but-consistent map verifies clean. This file is
 * the only place in the system where the map meets the real page.
 *
 * Every refusal leaves the field UNFILLED and visible in the dock. Refusing is
 * always cheaper than typing a date of birth into a free-text box a university
 * will read.
 */
import type { PacketField } from "../types.js";
import { REFUSED_TYPES, accessibleName } from "./snapshot.js";
import { TOKENS, fieldKey, normalise, tokenGroupKey } from "./vocabulary.js";

export interface VerifiedEntry {
  entry: PacketField;
  element: HTMLElement | null;
  ok: boolean;
  /** "" when ok. Otherwise one of the stable reasons below. */
  reason: string;
}

const FILL_METHODS = new Set(["fill", "type", "selectOption", "selectOptionFromDropdown"]);

export function visible(element: HTMLElement): boolean {
  if (element.hidden) return false;
  const style = getComputedStyle(element);
  if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
    return false;
  }
  // offsetParent is null for a fixed-position element too, so the rect is the
  // arbiter: a control with no area is one no person could have filled.
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

/**
 * Does this control's own name say it asks for this fact?
 *
 * Three outcomes:
 *  - the name matches none of the packet's own fields -> no (`name_mismatch`);
 *  - the name matches more than one of the packet's own fields -- e.g. "Ad
 *    Soyad" (Turkish "full name") matches given_name, family_name AND
 *    full_name at once -> no (`ambiguous_name`): the control's true purpose
 *    is ambiguous between two of the packet's own fields, and typing a
 *    partial or wrong answer into it is not safe just because one of the
 *    matches happens to be this entry's own claimed field;
 *  - the name matches exactly one of the packet's own fields, and it is this
 *    entry's own field -> yes. See vocabulary.ts's ceiling note for tokens
 *    that match nothing we know.
 */
function matchingFields(name: string, candidates: readonly string[]): string[] {
  const haystack = normalise(name);
  if (!haystack) return [];
  // Whole-word/whole-phrase match only: padding both sides with a single
  // space turns substring inclusion into a boundary check, so a short token
  // like "ad" (Turkish for first name) cannot match inside "Address", and
  // "not" (Turkish for grade) cannot match inside "Cannot" or "Annotation".
  // Unanchored substring matching was measured to false-accept exactly the
  // cross-field case this check exists to refuse.
  const padded = ` ${haystack} `;
  const hitsByGroup = new Map<string, string[]>();
  for (const group of candidates) {
    const own = TOKENS[group] ?? TOKENS[fieldKey(group)];
    if (!own) continue;
    const hits = own
      .map((token) => normalise(token))
      .filter((norm) => norm.length > 0 && padded.includes(` ${norm} `));
    if (hits.length > 0) hitsByGroup.set(group, hits);
  }
  const matched = Array.from(hitsByGroup.keys());
  if (matched.length <= 1) return matched;
  // Phrase subsumption: a compound phrase matched by one candidate (e.g.
  // "issuing country", "degree in english", "first language") subsumes a
  // shorter head-noun token from a single other candidate ("country",
  // "degree", "first"), provided the compound phrase does not span two
  // distinct sub-candidates (preserving "Ad Soyad" as ambiguous_name).
  return matched.filter((sub) => {
    const subHits = hitsByGroup.get(sub) ?? [];
    return !subHits.every((tSub) =>
      matched.some((sup) => {
        if (sup === sub) return false;
        const supHits = hitsByGroup.get(sup) ?? [];
        return supHits.some((tSup) => {
          if (tSup === tSub || !(` ${tSup} `).includes(` ${tSub} `)) return false;
          const subGroupsInSup = matched.filter(
            (other) =>
              other !== sup &&
              (hitsByGroup.get(other) ?? []).some(
                (tOther) => tOther !== tSup && (` ${tSup} `).includes(` ${tOther} `),
              ),
          );
          return subGroupsInSup.length === 1;
        });
      }),
    );
  });
}

/** "education.2.institution_original" -> "education.institution_original".
 *  Two degrees' institution boxes carry the same label ("University"); which
 *  degree a box belongs to is the map's to say (its heading), never the
 *  label's. So the label check compares classes, not indices. */
export function fieldClass(profileField: string): string {
  return profileField.replace(/\.\d+\./, ".");
}

export function verifyEntries(entries: PacketField[]): VerifiedEntry[] {
  // A typed-back answer names no class: its label was never ours to judge.
  const judged = entries.filter((item) => !item.from_answer);
  const packetGroups = Array.from(new Set(judged.map((item) => tokenGroupKey(item.profile_field))));
  return entries.map((entry) => {
    const refuse = (reason: string): VerifiedEntry => ({ entry, element: null, ok: false, reason });

    if (!FILL_METHODS.has(entry.method)) return refuse("method_not_allowed");

    let matches: NodeListOf<Element>;
    try {
      matches = document.querySelectorAll(entry.selector);
    } catch {
      // An unparseable selector is a malformed map, not a missing control.
      return refuse("bad_selector");
    }
    if (matches.length === 0) return refuse("no_such_control");
    // Two matches means the selector does not identify anything: typing into
    // the first is a coin flip the student would be right to resent.
    if (matches.length > 1) return refuse("not_unique");

    const element = matches[0];
    if (!(element instanceof HTMLElement)) return refuse("no_such_control");

    const tag = element.tagName.toLowerCase();
    if (!["input", "select", "textarea"].includes(tag)) return refuse("not_a_control");

    const type = (element.getAttribute("type") ?? "").toLowerCase();
    if (REFUSED_TYPES.has(type)) return refuse("refused_type");
    if (entry.method.startsWith("selectOption") && tag !== "select") return refuse("not_a_select");

    if (!visible(element)) return refuse("hidden");
    if (
      (element as HTMLInputElement).disabled ||
      (element as HTMLInputElement).readOnly ||
      element.getAttribute("aria-disabled") === "true"
    ) {
      return refuse("disabled");
    }

    // The student typed this answer into this very box before (owner,
    // 2026-10-09): the box is theirs by their own act, so its label is not ours
    // to judge. Every check above (unique, visible, enabled, typeable) still applies.
    if (entry.from_answer === true) return { entry, element, ok: true, reason: "" };

    const matched = matchingFields(accessibleName(element), packetGroups);
    if (matched.length === 0) return refuse("name_mismatch");
    if (matched.length > 1) return refuse("ambiguous_name");
    if (matched[0] !== tokenGroupKey(entry.profile_field)) return refuse("name_mismatch");

    return { entry, element, ok: true, reason: "" };
  });
}

/**
 * The frame this run is allowed to act in.
 *
 * A packet is minted for one form on one origin. A content script runs per
 * frame, so without this an embedded third-party iframe on a portal page
 * would be filled from the same packet.
 */
export function originMatches(formUrl: string): boolean {
  try {
    return new URL(formUrl).origin === location.origin && window.top === window;
  } catch {
    return false;
  }
}
