/**
 * Describe this page's form controls. Never what anyone typed into them.
 *
 * The server's FormSnapshot forbids extra keys and substring-scans every
 * string here for the student's own verified values, so a label reading
 * "Full name (Ada Byron)" is refused. That is the server's business; this
 * file's business is never to build such a thing in the first place.
 */

/** Types no packet may ever type into. `file` is handled separately (task 9);
 *  the rest are controls, secrets or payment fields. */
export const REFUSED_TYPES = new Set([
  "password",
  "hidden",
  "submit",
  "button",
  "image",
  "reset",
  "checkbox",
  "radio",
]);

export interface SnapshotControl {
  selector: string;
  tag: string;
  type: string;
  name: string;
  id: string;
  label: string;
  placeholder: string;
  options: string[];
  required: boolean;
}

export interface FormSnapshot {
  page_url: string;
  controls: SnapshotControl[];
}

/** A selector that resolves to this element and nothing else.
 *
 * Preference order is stability first: an id survives a re-render, a name
 * survives a class rename, and the nth-of-type path survives neither but is
 * better than no map at all. Verified against the page before every use, so a
 * stale one costs an unfilled field, never a wrong one. */
export function selectorFor(element: Element): string {
  const id = element.getAttribute("id");
  if (id) {
    const candidate = `#${CSS.escape(id)}`;
    if (document.querySelectorAll(candidate).length === 1) return candidate;
  }
  const name = element.getAttribute("name");
  if (name) {
    const candidate = `${element.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
    if (document.querySelectorAll(candidate).length === 1) return candidate;
  }
  const path: string[] = [];
  let node: Element | null = element;
  while (node && node !== document.documentElement) {
    const parent: Element | null = node.parentElement;
    if (!parent) break;
    const tag = node.tagName.toLowerCase();
    const index = Array.from(parent.children).filter((c) => c.tagName === node!.tagName).indexOf(node) + 1;
    path.unshift(`${tag}:nth-of-type(${index})`);
    node = parent;
  }
  return path.join(" > ");
}

/**
 * What this control calls itself, to a person reading the page.
 *
 * The same four sources the spec names -- label, aria-label, placeholder,
 * name -- plus aria-labelledby, which is how a real form supplies a label
 * that is not a <label>. This is the string the verification check judges.
 */
export function accessibleName(element: Element): string {
  const id = element.getAttribute("id");
  if (id) {
    const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    if (label?.textContent?.trim()) return label.textContent.trim();
  }
  const wrapping = element.closest("label");
  if (wrapping?.textContent?.trim()) return wrapping.textContent.trim();
  const ariaLabel = element.getAttribute("aria-label");
  if (ariaLabel?.trim()) return ariaLabel.trim();
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    const target = document.getElementById(labelledBy);
    if (target?.textContent?.trim()) return target.textContent.trim();
  }
  const placeholder = element.getAttribute("placeholder");
  if (placeholder?.trim()) return placeholder.trim();
  return element.getAttribute("name") ?? "";
}

export function buildSnapshot(root: Document): FormSnapshot {
  const controls: SnapshotControl[] = [];
  for (const element of Array.from(root.querySelectorAll("input, select, textarea"))) {
    const elementTag = element.tagName.toLowerCase();
    const controlType = (element.getAttribute("type") ?? "").toLowerCase();
    if (REFUSED_TYPES.has(controlType)) continue;
    controls.push({
      selector: selectorFor(element),
      tag: elementTag,
      type: controlType,
      name: element.getAttribute("name") ?? "",
      id: element.getAttribute("id") ?? "",
      label: accessibleName(element),
      placeholder: element.getAttribute("placeholder") ?? "",
      options:
        element instanceof HTMLSelectElement
          ? Array.from(element.options).map((option) => option.text)
          : [],
      required: element.hasAttribute("required"),
    });
    // The server caps the list at 200 and rejects a longer one outright. Cut
    // here so a sprawling page produces a partial map rather than a 400.
    if (controls.length >= 200) break;
  }
  return { page_url: location.href, controls };
}
