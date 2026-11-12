import type { FieldView } from "../types.js";
import { portalErrorFor } from "./page_signals.js";
import type { VerifiedEntry } from "./verify.js";

export interface Mismatch { profile_field: string; expected: string; actual: string }
export interface FieldRecord {
  view: FieldView;
  element: HTMLElement | null;
  base?: { state: FieldView["state"]; reason: string }; // what it was before a portal error
  selector?: string; // the packet's selector for this row (entry or hint)
  hint?: boolean; // a packet hint: the student's box, never typed by us
}

/** One record per packet entry, from what verify/fill/read-back found. Pure: no DOM writes. */
export function classify(
  verified: VerifiedEntry[],
  filled: string[],
  skip: Set<string>,
  mismatches: Mismatch[],
  theirs: Set<string>,
  onFormPage = false, // the page IS the packet's form_url: a missing control is a bad selector
): Map<string, FieldRecord> {
  const typed = new Set(filled);
  const off = new Set(mismatches.map((m) => m.profile_field));
  const records = new Map<string, FieldRecord>();
  for (const item of verified) {
    const key = item.entry.profile_field;
    let state: FieldView["state"];
    let reason = "";
    if (!item.ok && item.reason === "no_such_control" && onFormPage) {
      state = "your_turn";
      reason = "not_found";
    } else if (!item.ok && item.reason === "no_such_control") state = "elsewhere";
    else if (!item.ok) { state = "your_turn"; reason = item.reason; }
    // A value already on the page that differs from ours: nobody saw the student
    // type it, so it is not "changed by you" -- it is theirs to check (final review I5).
    else if (theirs.has(key)) { state = "mismatch"; reason = "held_other"; }
    else if (off.has(key)) state = "mismatch";
    else if (typed.has(key)) state = "filled";
    else if (skip.has(key)) state = "already";
    else { state = "your_turn"; reason = "not_filled"; }
    records.set(key, {
      view: { key, state, reason, placed: false },
      element: item.element,
      selector: item.entry.selector,
    });
  }
  return records;
}

/** A trusted input on a control we filled or left already-correct makes it the student's. */
export function watchStudentEdits(
  records: Map<string, FieldRecord>,
  signal: AbortSignal, // aborted on Stop or a new run
  onChange: () => void,
): void {
  for (const record of records.values()) {
    const element = record.element;
    if (!element || !["filled", "already", "mismatch", "your_turn"].includes(record.view.state)) {
      continue;
    }
    const onStudentEdit = (event: Event) => {
      if (!event.isTrusted) return; // our own dispatched events are untrusted
      if (record.view.state === "changed_by_you") return;
      record.view.state = "changed_by_you";
      record.view.reason = "";
      record.base = undefined; // re-derived by applyPortalErrors if the error still shows
      onChange();
    };
    element.addEventListener("input", onStudentEdit, { signal });
    element.addEventListener("change", onStudentEdit, { signal });
  }
}

/** The portal's own message wins over filled/already/mismatch/changed_by_you
 *  (a changed value keeps `theirs`); a message that went away restores the state
 *  underneath. Returns whether any field changed, so callers redraw only then. */
export function applyPortalErrors(records: Map<string, FieldRecord>): boolean {
  let changed = false;
  for (const record of records.values()) {
    const { view, element } = record;
    if (!element || (view.state === "elsewhere")) continue;
    const text = portalErrorFor(element);
    if (text) {
      const reason = `portal:${text}`;
      if (view.state === "portal_error" && view.reason === reason) continue;
      if (view.state !== "portal_error") record.base = { state: view.state, reason: view.reason };
      view.theirs = record.base?.state === "changed_by_you";
      view.state = "portal_error";
      view.reason = reason;
      changed = true;
    } else if (view.state === "portal_error" && record.base) {
      view.state = record.base.state;
      view.reason = record.base.reason;
      view.theirs = undefined;
      record.base = undefined;
      changed = true;
    }
  }
  return changed;
}
