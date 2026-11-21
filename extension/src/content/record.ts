/**
 * The page as the bench will replay it: structure only (plan 6).
 *
 * Built on a clone, so the live page is never touched. Every value goes --
 * input values, textarea text, the selected option, a rich-text box's text --
 * because the owner walks with their real account. A clone DOES carry an
 * input's live value and checkedness as properties; what keeps them out is
 * that `outerHTML` serializes attributes only, plus the attribute removals
 * below, which cover values the page served pre-filled. Never read `.value`
 * off the clone and trust it.
 *
 * Every script and inline handler goes too: a replay must never run the
 * portal's own code, which would call the live portal from the bench. A <base>
 * goes because it would point relative URLs back at the live host, an
 * <iframe>/<object>/<embed> because each is a live page of its own, and a
 * <meta http-equiv> because a refresh would navigate the replay to the portal.
 */
export function savedCopy(root: Document): string {
  const copy = root.documentElement.cloneNode(true) as HTMLElement;
  scrub(copy);
  return "<!doctype html>\n" + copy.outerHTML;
}

const REMOVED = "script, noscript, base, iframe, frame, object, embed, meta[http-equiv]";

/** The URL parser drops ASCII whitespace and C0 controls from a scheme, so
 *  `java&#9;script:` still runs; they are dropped here before the test. */
function isScriptUrl(value: string): boolean {
  return /^javascript:/i.test(value.replace(/[\u0000- ]/g, ""));
}

/** Every removal, over `root` and, recursively, every <template>'s content:
 *  querySelectorAll never enters a template, while outerHTML serializes it. */
function scrub(root: ParentNode): void {
  root.querySelectorAll(REMOVED).forEach((node) => node.remove());
  root.querySelectorAll("*").forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      if (attribute.name.toLowerCase().startsWith("on") || isScriptUrl(attribute.value)) {
        element.removeAttribute(attribute.name);
      }
    }
  });
  root.querySelectorAll("input").forEach((element) => {
    element.removeAttribute("value");
    element.removeAttribute("checked");
  });
  root.querySelectorAll("textarea").forEach((element) => {
    element.textContent = "";
  });
  root.querySelectorAll("option").forEach((element) => element.removeAttribute("selected"));
  // A rich-text essay box holds what the owner typed as text, not a value.
  root
    .querySelectorAll('[contenteditable]:not([contenteditable="false"])')
    .forEach((element) => element.replaceChildren());
  root.querySelectorAll("template").forEach((template) => scrub(template.content));
}
