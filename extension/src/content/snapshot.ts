/**
 * Describe this page's form controls. Never what anyone typed into them.
 *
 * The server's FormSnapshot forbids extra keys and substring-scans every
 * string here for the student's own verified values, so a label reading
 * "Full name (Ada Byron)" is refused. That is the server's business; this
 * file's business is never to build such a thing in the first place.
 */

/** Types no packet may ever type into. `file` inputs are described like any control: they
 *  are where documents go (plan 5). `radio` inputs are allowed only when they are
 *  non-consent profile controls (checked via `notConsentRadio`). The rest are controls,
 *  secrets or payment/consent fields. */
export const REFUSED_TYPES = new Set([
  "password",
  "hidden",
  "submit",
  "button",
  "image",
  "reset",
  "checkbox",
]);

const CONSENT_RE =
  /\b(consent|agree|accept|confirm|declare|acknowledge|terms|privacy|gdpr|einverstanden|zustimm\w*|datenschutz\w*|j\s*accepte|kabul|onay\w*|razıyam|raziyam|соглас\w*)\b/i;

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

export type ControlDescriptor = SnapshotControl;

export function isControlRequired(el: Element, label: string): boolean {
  return (
    (el as HTMLInputElement).required === true ||
    el.hasAttribute("required") ||
    el.getAttribute("aria-required") === "true" ||
    /\*/.test(label)
  );
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
      "input, select, textarea, button, script, style, option, [role=\"listbox\"], [role=\"option\"], " +
        '[contenteditable]:not([contenteditable="false"])',
    )
    .forEach((child) => child.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

export function isCombobox(element: Element): boolean {
  return (element.getAttribute("role") ?? "").toLowerCase() === "combobox";
}

export function isRadioGroupContainer(element: Element): boolean {
  const tag = element.tagName.toLowerCase();
  const role = (element.getAttribute("role") ?? "").toLowerCase();
  return (
    (tag === "fieldset" || role === "radiogroup") &&
    element.querySelectorAll('input[type="radio"]').length > 0
  );
}

export function isRadioControl(element: Element): boolean {
  return (
    (element instanceof HTMLInputElement && element.type.toLowerCase() === "radio") ||
    isRadioGroupContainer(element)
  );
}

export function radioButtonsFor(element: Element): HTMLInputElement[] {
  if (element instanceof HTMLInputElement && element.type.toLowerCase() === "radio") {
    if (element.name) {
      const scope = element.form ?? document;
      const group = Array.from(
        scope.querySelectorAll<HTMLInputElement>(
          `input[type="radio"][name="${CSS.escape(element.name)}"]`,
        ),
      );
      if (group.length > 0) return group;
    }
    const container = element.closest('fieldset, [role="radiogroup"]');
    if (container) {
      return Array.from(container.querySelectorAll<HTMLInputElement>('input[type="radio"]'));
    }
    return [element];
  }
  if (isRadioGroupContainer(element)) {
    return Array.from(element.querySelectorAll<HTMLInputElement>('input[type="radio"]'));
  }
  return [];
}

export function radioOptionLabel(radio: HTMLInputElement): string {
  const id = radio.getAttribute("id");
  if (id) {
    const labelText = cleanLabelText(document.querySelector(`label[for="${CSS.escape(id)}"]`));
    if (labelText) return labelText;
  }
  const wrappingText = cleanLabelText(radio.closest("label"));
  if (wrappingText) return wrappingText;
  const ariaLabel = radio.getAttribute("aria-label");
  if (ariaLabel?.trim()) return ariaLabel.trim();
  return (radio.getAttribute("value") ?? "").trim();
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

export function radioGroupName(element: Element): string {
  const rg = element.closest('[role="radiogroup"]');
  if (rg) {
    const aria = rg.getAttribute("aria-label")?.trim();
    if (aria) return aria;
    const labelledBy = rg.getAttribute("aria-labelledby");
    if (labelledBy) {
      const targetText = cleanLabelText(document.getElementById(labelledBy));
      if (targetText) return targetText;
    }
  }
  const legend = element.closest("fieldset")?.querySelector(":scope > legend");
  if (legend?.textContent?.trim()) return clip(legend.textContent, 200);
  const group = element.closest(GROUPS) ?? element.parentElement;
  if (group) {
    for (const label of Array.from(group.querySelectorAll("label"))) {
      if (label.getAttribute("for") || label.querySelector('input[type="radio"]')) continue;
      const text = cleanLabelText(label);
      if (text) return text;
    }
  }
  const ownAria = element.getAttribute("aria-label")?.trim();
  if (ownAria) return ownAria;
  const heading = headingFor(element);
  if (heading) return heading;
  return element.getAttribute("name") ?? accessibleName(element);
}

export function notConsentRadio(element: Element): boolean {
  const radios = radioButtonsFor(element);
  const texts = [
    radioGroupName(element),
    headingFor(element),
    element.getAttribute("name") ?? "",
    ...radios.map((r) => radioOptionLabel(r)),
  ];
  return !texts.some((t) => CONSENT_RE.test(t));
}

export interface ComboboxOptionItem {
  element: HTMLElement;
  value: string;
  text: string;
  disabled: boolean;
}

export function comboboxOptionsFor(element: Element): ComboboxOptionItem[] {
  const roots: Element[] = [];
  for (const attr of ["aria-controls", "aria-owns", "list"]) {
    const raw = element.getAttribute(attr) ?? "";
    for (const id of raw.split(/\s+/).filter(Boolean)) {
      const target = document.getElementById(id);
      if (target && !roots.includes(target)) roots.push(target);
    }
  }
  const wrapper = element.closest('[role="combobox"]');
  if (wrapper && wrapper !== element) {
    for (const attr of ["aria-controls", "aria-owns"]) {
      const raw = wrapper.getAttribute(attr) ?? "";
      for (const id of raw.split(/\s+/).filter(Boolean)) {
        const target = document.getElementById(id);
        if (target && !roots.includes(target)) roots.push(target);
      }
    }
  }
  const container = element.closest(GROUPS) ?? element.parentElement;
  if (container) {
    for (const lb of Array.from(container.querySelectorAll('[role="listbox"]'))) {
      if (!roots.includes(lb)) roots.push(lb);
    }
  }
  if (roots.length === 0) {
    const allListboxes = Array.from(document.querySelectorAll('[role="listbox"]'));
    if (allListboxes.length === 1 && allListboxes[0]) {
      roots.push(allListboxes[0]);
    }
  }
  const nodes: HTMLElement[] = [];
  for (const root of roots) {
    if ((root.getAttribute("role") ?? "").toLowerCase() === "option" && root instanceof HTMLElement) {
      nodes.push(root);
    }
    for (const opt of Array.from(root.querySelectorAll<HTMLElement>('[role="option"], option'))) {
      if (!nodes.includes(opt)) nodes.push(opt);
    }
  }
  return nodes.map((opt) => {
    const text =
      (opt.textContent ?? "").replace(/\s+/g, " ").trim() ||
      (opt.getAttribute("aria-label") ?? "").trim();
    const value = (opt.getAttribute("data-value") ?? opt.getAttribute("value") ?? text).trim();
    const disabled =
      opt.getAttribute("aria-disabled") === "true" ||
      opt.hasAttribute("disabled") ||
      (opt as HTMLOptionElement).disabled === true;
    return { element: opt, value, text, disabled };
  });
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
      "input, select, textarea, script, style, option, [role=\"listbox\"], [role=\"option\"], " +
        '[contenteditable]:not([contenteditable="false"])',
    )
    .forEach((node) => node.remove());
  return clip(copy.textContent ?? "", 300);
}

export function buildSnapshot(root: Document): FormSnapshot {
  const controls: SnapshotControl[] = [];
  const seenRadioElements = new Set<Element>();
  const elements = Array.from(
    root.querySelectorAll('input, select, textarea, [role="combobox"]'),
  );
  for (const element of elements) {
    const elementTag = element.tagName.toLowerCase();
    const isNativeControl = ["input", "select", "textarea"].includes(elementTag);
    if (!isNativeControl && element.querySelector("input, select, textarea")) {
      continue;
    }
    const rawType = (element.getAttribute("type") ?? "").toLowerCase();
    const combobox = isCombobox(element);
    if (REFUSED_TYPES.has(rawType)) continue;
    if (rawType === "radio") {
      if (seenRadioElements.has(element)) continue;
      const radios = radioButtonsFor(element);
      for (const r of radios) seenRadioElements.add(r);
      if (!notConsentRadio(element)) continue;
      const groupLabel = radioGroupName(element);
      const radioOptions = radios.map((r) => radioOptionLabel(r)).filter(Boolean);
      controls.push({
        selector: selectorFor(element),
        tag: elementTag,
        type: "radio",
        name: element.getAttribute("name") ?? "",
        id: element.getAttribute("id") ?? "",
        label: groupLabel,
        placeholder: "",
        options: radioOptions,
        required:
          radios.some((r) => isControlRequired(r, radioOptionLabel(r))) ||
          isControlRequired(element, groupLabel),
        heading: headingFor(element),
        context: contextFor(element),
        accept: "",
        max_length: 0,
      });
      if (controls.length >= 200) break;
      continue;
    }
    const controlType = combobox ? "combobox" : rawType;
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
    const options =
      element instanceof HTMLSelectElement
        ? Array.from(element.options).map((option) => option.text)
        : combobox
          ? comboboxOptionsFor(element).map((option) => option.text)
          : [];
    controls.push({
      selector: selectorFor(element),
      tag: elementTag,
      type: controlType,
      name: element.getAttribute("name") ?? "",
      id: element.getAttribute("id") ?? "",
      label: controlLabel,
      placeholder: controlPlaceholder,
      options,
      required: isControlRequired(element, controlLabel),
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
