/**
 * Describe this page's form controls. Never what anyone typed into them.
 *
 * The server's FormSnapshot forbids extra keys and substring-scans every
 * string here for the student's own verified values, so a label reading
 * "Full name (Ada Byron)" is refused. That is the server's business; this
 * file's business is never to build such a thing in the first place.
 */

/** Types no packet may ever type into. `file` inputs are described like any control: they
 *  are where documents go (plan 5). The rest are controls, secrets or payment fields. */
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
  heading: string;
  context: string;
  accept: string;
  max_length: number;
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

function cleanLabelText(node: Element | null): string {
  if (!node) return "";
  const copy = node.cloneNode(true) as Element;
  copy
    .querySelectorAll(
      "input, select, textarea, button, script, style, option, " +
        '[contenteditable]:not([contenteditable="false"])',
    )
    .forEach((child) => child.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

const CHAR_LIMIT_RE =
  /(?:max(?:imum)?\.?\s*|up\s+to\s+|limit(?:\s+of)?\s*:?\s*|bis\s+zu\s+|не\s+более\s+|макс\.?\s*|\b\d+\s*[-–—to]+\s*)(\d{2,5})\s*(?:char(?:acter)?s?|zeichen\w*|caract[èe]res?|символ\w*|simvol\w*|karakter\w*)\b/i;

const WORD_LIMIT_RE =
  /(?:max(?:imum)?\.?\s*|up\s+to\s+|limit(?:\s+of)?\s*:?\s*|bis\s+zu\s+|не\s+более\s+|макс\.?\s*|\b\d+\s*[-–—to]+\s*)(\d{1,4})\s*(?:words?|w[öo]rter\w*|mots?|слов\w*|söz\w*|kelime\w*)\b/i;

export function inferredMaxLength(...texts: string[]): number {
  for (const text of texts) {
    const charMatch = CHAR_LIMIT_RE.exec(text);
    if (charMatch?.[1]) {
      const cap = Number.parseInt(charMatch[1], 10);
      if (cap >= 10 && cap <= 50000) return cap;
    }
    const wordMatch = WORD_LIMIT_RE.exec(text);
    if (wordMatch?.[1]) {
      const words = Number.parseInt(wordMatch[1], 10);
      if (words >= 5 && words <= 10000) return words * 5;
    }
  }
  return 0;
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
    const labelText = cleanLabelText(document.querySelector(`label[for="${CSS.escape(id)}"]`));
    if (labelText) return labelText;
  }
  const wrappingText = cleanLabelText(element.closest("label"));
  if (wrappingText) return wrappingText;
  const ariaLabel = element.getAttribute("aria-label");
  if (ariaLabel?.trim()) return ariaLabel.trim();
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    const targetText = cleanLabelText(document.getElementById(labelledBy));
    if (targetText) return targetText;
  }
  const placeholder = element.getAttribute("placeholder");
  if (placeholder?.trim()) return placeholder.trim();
  return element.getAttribute("name") ?? "";
}

const HEADINGS = "h1, h2, h3, h4, h5, h6, legend, [role=heading]";
/** The containers that make a control's own group. Exported: fill.ts reads the
 *  same group's visible text when it checks a learned upload box (plan 5 Task 5). */
export const GROUPS = "fieldset, section, li, tr, [role=group], .form-group, .row";

export function clip(text: string, max: number): string {
  return text.replace(/\s+/g, " ").trim().slice(0, max);
}

/** The nearest heading or legend before `element` in document order. A
 *  fieldset's own legend wins over an earlier page heading; a heading or legend
 *  inside a fieldset that does not contain the element is another section's. */
export function headingFor(element: Element): string {
  const legend = element.closest("fieldset")?.querySelector(":scope > legend");
  if (legend?.textContent?.trim()) return clip(legend.textContent, 200);
  let found = "";
  for (const heading of Array.from(document.querySelectorAll(HEADINGS))) {
    const fieldset = heading.closest("fieldset");
    if (fieldset && !fieldset.contains(element)) continue;
    if (heading.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING) {
      found = heading.textContent ?? "";
    }
  }
  return clip(found, 200);
}

/** The text of the control's own group with every control removed: a clone,
 *  so the page is never touched, and no input, select or textarea text (a
 *  textarea's text IS its value). */
export function contextFor(element: Element): string {
  const group = element.closest(GROUPS) ?? element.parentElement;
  if (!group) return "";
  const copy = group.cloneNode(true) as Element;
  copy
    // A rich-text essay box is the student's own text, never page context.
    .querySelectorAll(
      "input, select, textarea, script, style, option, " +
        '[contenteditable]:not([contenteditable="false"])',
    )
    .forEach((node) => node.remove());
  return clip(copy.textContent ?? "", 300);
}

export function buildSnapshot(root: Document): FormSnapshot {
  const controls: SnapshotControl[] = [];
  for (const element of Array.from(root.querySelectorAll("input, select, textarea"))) {
    const elementTag = element.tagName.toLowerCase();
    const controlType = (element.getAttribute("type") ?? "").toLowerCase();
    if (REFUSED_TYPES.has(controlType)) continue;
    const controlLabel = accessibleName(element);
    const controlPlaceholder = element.getAttribute("placeholder") ?? "";
    const controlContext = contextFor(element);
    const domMaxLength =
      (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) &&
      element.maxLength > 0
        ? element.maxLength
        : 0;
    const controlMaxLength =
      domMaxLength > 0
        ? domMaxLength
        : element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement
          ? inferredMaxLength(controlLabel, controlPlaceholder, controlContext)
          : 0;
    controls.push({
      selector: selectorFor(element),
      tag: elementTag,
      type: controlType,
      name: element.getAttribute("name") ?? "",
      id: element.getAttribute("id") ?? "",
      label: controlLabel,
      placeholder: controlPlaceholder,
      options:
        element instanceof HTMLSelectElement
          ? Array.from(element.options).map((option) => option.text)
          : [],
      required: element.hasAttribute("required"),
      heading: headingFor(element),
      context: controlContext,
      accept: clip(element.getAttribute("accept") ?? "", 100),
      max_length: controlMaxLength,
    });
    // The server caps the list at 200 and rejects a longer one outright. Cut
    // here so a sprawling page produces a partial map rather than a 400.
    if (controls.length >= 200) break;
  }
  return { page_url: location.href, controls };
}
