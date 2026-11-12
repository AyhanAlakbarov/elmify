# In-page extension UI: isolation, attacks, and Chrome's guidance

Date: 2026-10-09. Question: should the glass-box co-pilot (Chrome MV3, fills the student's portal form in their own tab, holds a session-only packet of verified personal data) draw guidance on the portal page, keep its side panel, or both?

## Summary

- **What a careful vendor does today (Bitwarden, open source, read on `main`):** the in-page menu is an `<iframe>` loaded from the extension's own origin, placed inside a **closed** shadow root on a custom element with a **random tag name**, shown with the **Popover API (top layer)**, styled with `all: initial` and the maximum z-index, and guarded by MutationObservers that undo page changes to its styles and attributes. It also checks the opacity of `<html>`/`<body>`, keeps itself the last child of its container, checks `elementFromPoint` for overlays, and turns itself off when the page fights for the top layer. None of this is a complete defence, and the vendors say so.
- **The attack it must withstand:** DOM-based extension clickjacking (Marek Tóth, DEF CON 33, Aug 2025). The page makes the extension's UI invisible but still clickable, using opacity on the element, a parent, `<body>` or `<html>`, or by covering it with a `pointer-events:none` top-layer popover. A fake cookie banner then gets the click. All 11 password managers tested were vulnerable in their default configuration. As of the researcher's 14 Jan 2026 update, 1Password and LastPass are still listed as vulnerable. The researcher's own conclusion is that no simple protection exists, that the platform needs a browser API, and that the safest UI is one the page cannot draw over, such as a separate window or browser-drawn UI.
- **Chrome's position:** Chrome's own autofill dropdown is a browser-drawn widget, not page DOM, and it still adds anti-clickjacking checks: it ignores clicks under a cursor that was already resting there, requires the row to be visible enough for long enough, can raise the popup to a security z-order, and caps the size of page-set custom cursors. Chrome's extension docs say to treat content scripts as exposed: hostile pages can manipulate the DOM those scripts depend on, a compromised renderer can take them over, and you should "Assume any data sent to the content script might leak to the web page". The side panel is an extension page that has all Chrome APIs. It can be scoped to one tab and opens only from a user action. The docs give no rule for choosing between a side panel and injected UI. They list the side panel, popup, context menu and others as extension UI, and in-page injected UI is not on that list.
- **Implication for the co-pilot (inference, not a source claim):** keep the side panel as the only place that holds the packet and the only place a fill can be triggered from. If guidance is drawn on the portal page, make it display-only. It should carry no personal data and have no control that releases or fills data, so a hidden or overlaid copy of it is worth nothing to an attacker. "Both" is safe only under that rule.

## Scope (sub-questions)

1. How do password managers draw their inline menus, and what isolation do they use? (Bitwarden source; 1Password, Dashlane and Chrome autofill from first-party pages and source.)
2. Which attacks on in-page extension UI are documented, and how did vendors mitigate each?
3. What does Chrome document about the side panel versus a popup versus injected UI, and what are the side panel's limits?
4. How do in-page overlays interact with screen readers and keyboard focus?

## 1. Where the UI lives and how it is isolated

### Bitwarden (open source, `bitwarden/clients` main, manifest version 2026.10.0)

- The inline-menu host element attaches a **closed** shadow root[^1] and first adds a stylesheet that resets the host's pseudo-elements against page styles.[^2]
- The iframe inside the shadow root loads an extension page and connects back to the background script by port. The iframe gets inline styles including `all: initial`, `position: fixed` and z-index 2147483647.[^3] Messages to the iframe go to the extension origin only, through `postMessage(..., this.extensionOrigin)`, in the same file.
- In `manifest.v3.json`, `overlay/menu.html`, `menu-button.html` and `menu-list.html` are web-accessible resources with `use_dynamic_url` set. The button and list pages are also declared as sandboxed pages. (Source read at https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/manifest.v3.json. Every token in that file is wrapped in JSON quotes, so it is not footnoted.) Chrome defines `use_dynamic_url` as allowing access to the resources only through a per-session dynamic ID.[^4]
- The host is a custom element with a randomly generated tag name[^5]. It is put in the top layer through the Popover API, and the extension looks for other top-layer items that are not its own.[^6]
- MutationObservers undo page changes to the iframe's style and attributes. They also force the menu closed if mutations come in a storm, which is what a page fighting the extension produces.[^7][^8]
- Opacity inherits through the shadow boundary, and Bitwarden's own comment says so. It therefore checks the computed opacity of `html` and `body`[^9] and treats anything at or below 0.6 as unsafe.[^10] It watches only a few attributes because `getComputedStyle` is expensive.[^11]
- When a page element keeps pushing itself after the menu, Bitwarden checks whether that element covers the menu's centre point.[^12] If the page keeps trying to take the top layer, it turns the menu off and alerts the user.[^13]

### 1Password (closed source)

- 1Password says clickjacking and deceptive overlays can trick users into using its autofill prompts.[^14] By default it does not confirm before filling an Identity (PII) item.[^15] For credit cards it always shows a confirmation alert, which it says "cannot be hidden or covered by a malicious or compromised webpage".[^16] How that alert is drawn (a separate window or browser UI) is **Unverified**: the page does not say.

### Dashlane

- Dashlane's advisory: on a domain vulnerable to script injection, an attacker could overlay an element on Dashlane's passkey dialog. The issue was fixed in v6.2531.1 (1 Aug 2025).[^17] The page does not describe how the fix works (**Unverified**).

### LastPass

- No first-party architecture page was fetched. Its status comes only from the researcher's table (§2). Its isolation technique is **Unverified**.

### Chrome's own autofill dropdown (browser-drawn)

- The dropdown is a native `views::Widget` of type `TYPE_POPUP` owned by the browser, not a DOM node.[^18] Behind a feature flag it can use the `kSecuritySurface` z-order to sit above other windows, "but it makes certain attacks (those based on the popup being obscured) less practical".[^19]
- Even browser-drawn UI needed clickjacking hardening. It caps the size of page custom cursors while the popup is open[^20], ignores a click on a suggestion that was under the cursor when the popup appeared[^21], and accepts a suggestion only after checking its visible area and how long it was on screen.[^22]

## 2. Attacks and failure modes, and the mitigations

| Failure mode | Evidence | Mitigation seen |
|---|---|---|
| Opacity on the extension's own element | The core technique[^23] | MutationObserver resets styles; closed shadow root[^24] |
| Open shadow root lets the page reach the inner iframe | Proton Pass case[^25] | Closed shadow root (Bitwarden[^1]); MDN notes closed mode only hides `shadowRoot`, while the creator still holds the reference[^26] |
| Opacity on a parent, `<body>` or `<html>` (inherits into the shadow tree) | Parent-element variant[^23] | `html`/`body` opacity check[^9]; researcher says Popover API "should protect this method"[^27] |
| Full overlay with `pointer-events:none`, or a page popover in the top layer | Overlay variant[^28] | Last-child enforcement, top-layer listing, `elementFromPoint`[^12][^6]; `elementsFromPoint` does not see through `pointer-events:none` popovers[^29] |
| z-index wars | Both sides use 2147483647; the last element in the DOM wins[^30] | Bitwarden re-orders and lowers an attacker's z-index[^12] |
| Page detects which extension is present and whether it is locked | DOM attributes reveal lock state[^31]; one script targets all of them[^32] | Random tag names[^5]; dynamic resource URLs[^4] (reduces fingerprinting, does not remove it) |
| Extension HTML loaded in a page iframe (`web_accessible_resources`) | NordPass: whole UI frameable, 4 clicks shared the vault[^33] | Expose minimal resources; MV3 `matches`; Chrome warns that web-accessible resources make an extension detectable[^34][^35] |
| Hidden form fields catching filled data | Exploit uses a form at `opacity: 0.001`[^23] | 1Password skips hidden fields except for Identity items (on the same page as [^15]; not separately footnoted) |
| Data handed to the content script | Chrome: content scripts share a renderer with the page and can be taken over[^36] | Keep sensitive operations in the service worker; assume data sent to content scripts leaks[^37] |
| Cross-origin iframes containing the form | 1Password fills cards across cross-origin iframes but not logins whose URL does not match the frame origin (same page as [^15]) | Per-frame origin check |
| SPA re-renders removing injected nodes | Bitwarden observes its container's `childList` and re-appends[^12] | MutationObserver on the container |
| Page CSP blocking injected `<style>` | **Unverified.** Chrome documents the isolated-world CSP for scripts only[^38]; nothing fetched covers styles | Bitwarden uses inline style attributes plus one `<style>` inside the shadow root[^2] (whether CSP affects it: Unverified) |
| Inherited fonts and colours | `all: initial` resets every property except `direction`, `unicode-bidi` and custom properties[^39] | `all: initial` on host and iframe[^3] |

Status of fixes: in the researcher's table updated 14 Jan 2026, Bitwarden is fixed in 2025.8.2[^40] and 1Password is still listed as vulnerable. The table gives "≤8.11.27.2", which it marks as the latest version on 14.1.2026, and calls it a clickjacking vulnerability.[^41] The researcher says there is no simple protection and asks for a browser-level API.[^42] He names a separate popup window as the safest UI.[^43]

## 3. Chrome's guidance: side panel, popup, injected UI

- Chrome's UI catalog lists actions, popups, side panels, context menus, the omnibox, notifications and others. It says "A side panel lets users invoke extension features alongside web pages".[^44] It has no entry for UI injected into the page, and no Chrome page fetched here sets a rule for when to use which. Treat any "Chrome recommends X over injected UI" as **Unverified**.
- Side panel capabilities: it is an extension page with all Chrome APIs[^45]. Available from Chrome 114, MV3 only.[^46] It can be scoped to a tab through `setOptions({tabId})`[^47], closes when the user navigates to a site where it is not enabled[^48], and `open()` works only in response to a user action.[^49]
- Width: the API reference has no width or size option. Whether the user can resize the panel is **Unverified**: no fetched page says.
- Content scripts run in an isolated world for JavaScript but share the page's DOM.[^50][^51] Chrome's security guidance says hostile pages can manipulate the DOM content scripts depend on.[^52]

## 4. Accessibility

- Bitwarden's iframe adds a hidden `role="alert"` live region to announce the menu to screen readers.[^53] It appends the menu inside the page's modal dialog because otherwise "Modals commonly run a focus trap that forces focus back inside their subtree"[^54], which breaks both clicks and keyboard use.
- Chrome's own dropdown fires menu start and end accessibility events so that screen readers treat the focus change as temporary.[^55]
- Chrome's extension a11y guidance: use standard controls, keep everything usable by keyboard[^56], and note that `tabIndex = -1` allows programmatic focus while keeping the element out of tab order.[^57]
- No vendor page fetched gives guidance specific to screen readers and in-page overlays beyond the above (**Unverified**).

## Sources searched

The candidate list came from an Exa search ("DOM-based extension clickjacking password managers DEF CON 33"), a GitHub code search (`repo:bitwarden/clients attachShadow`), a Brave search (`site:support.1password.com autofill clickjacking`) and an Exa search for Chromium autofill popup source. Tools available: Exa, Brave, scrapling, GitHub. Not used: Context7 and Tavily. Every quote below comes from a scrapling `get` of the cited URL.

## Sources

[^1]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/iframe-content/autofill-inline-menu-iframe-element.ts "const shadow: ShadowRoot = element.attachShadow({ mode:"
[^2]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/iframe-content/autofill-inline-menu-iframe-element.ts "Builds and prepends an internal stylesheet to the container node with rules"
[^3]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/iframe-content/autofill-inline-menu-iframe.service.ts "Handles initialization of the iframe which includes applying initial styles"
[^4]: https://developer.chrome.com/docs/extensions/reference/manifest/web-accessible-resources "If true, only allow resources to be accessed through a dynamic ID."
[^5]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/content/autofill-inline-menu-content.service.ts "const customElementName = this.generateRandomCustomElementName();"
[^6]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/content/autofill-inline-menu-content.service.ts "Queries and return elements (excluding those of the inline menu) that exist in the"
[^7]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/iframe-content/autofill-inline-menu-iframe.service.ts "Handles mutations to the iframe element. The ensures that the iframe"
[^8]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/iframe-content/autofill-inline-menu-iframe.service.ts "Will remove the autofill inline menu if any set mutation observer is"
[^9]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/content/autofill-inline-menu-content.service.ts "will inherit the opacity, despite being otherwise encapsulated from styling changes"
[^10]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/content/autofill-inline-menu-content.service.ts "const opacityThreshold = 0.6;"
[^11]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/content/autofill-inline-menu-content.service.ts "which blocks layout and freezes the browser."
[^12]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/content/autofill-inline-menu-content.service.ts "Verifies if the last child of the menu container is overlaying the inline menu elements."
[^13]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/content/autofill-inline-menu-content.service.ts "Set inline menu to be off; page is aggressively trying to take top position of top layer"
[^14]: https://support.1password.com/browser-autofill-security/ "Techniques like clickjacking or deceptive overlays can be used to trick users into interacting with interface elements, including autofill prompts, in ways that may expose sensitive information."
[^15]: https://support.1password.com/browser-autofill-security/ "By default, 1Password won’t alert you before you fill an Identity item."
[^16]: https://support.1password.com/browser-autofill-security/ "This alert cannot be hidden or covered by a malicious or compromised webpage, so attackers cannot silently capture your card details."
[^17]: https://support.dashlane.com/hc/en-us/articles/28598967624722-Security-advisory-Passkey-Dialog-Clickjacking-Issue "the issue could allow an attacker to overlay an HTML page element over the Dashlane log-in-with-passkey pop-up dialog."
[^18]: https://chromium.googlesource.com/chromium/src/+/f3438d782566ef170b55f2aa13ff5f9b44f8d956/chrome/browser/ui/views/autofill/popup/popup_base_view.cc "The widget that the PopupBaseView will be attached to."
[^19]: https://chromium.googlesource.com/chromium/src/+/f3438d782566ef170b55f2aa13ff5f9b44f8d956/chrome/browser/ui/views/autofill/popup/popup_base_view.cc "popup use, but it makes certain attacks (those based on the popup being"
[^20]: https://chromium.googlesource.com/chromium/src/+/f3438d782566ef170b55f2aa13ff5f9b44f8d956/chrome/browser/ui/views/autofill/popup/popup_base_view.cc "The maximum size (in DIPs) of custom cursors that are permitted while the"
[^21]: https://chromium.googlesource.com/chromium/src/+/c24bde01e377a8be7742826891857312eec278a6%5E%21/ "This CL ignores clicks on a suggestion if that suggestion was hovered at the time the popup was shown"
[^22]: https://chromium.googlesource.com/chromium/src/+/78bdcf8fe60ffd1606089a1017e6ed4d78af7abb "Before triggering suggestion acceptance, the row view checks its visible area and for how long it was present on the screen."
[^23]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "A new clickjacking technique where a malicious script manipulates UI elements that browser extensions inject into the DOM by making them invisible using javascript."
[^24]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "styles cannot be changed (MutationObserver)"
[^25]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "This usually occurred when a Shadow Root (open) was used, making the element accessible."
[^26]: https://developer.mozilla.org/en-US/docs/Web/API/Element/attachShadow "Note that JavaScript can still access a closed shadow root by storing the value returned by the function."
[^27]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "using Popover API for extension should protect this method"
[^28]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "Because it's completely covered, it would normally not be clickable but with using pointer-events:none it can be."
[^29]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "elementsFromPoint() can be used for partial overlay but cannot be used for popover elements (pointer-events:none are ignored)"
[^30]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "Extension elements in many cases also have the maximum z-index value - the last element in the DOM will be 'on top'."
[^31]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "By analyzing DOM element attributes, attackers can determine whether a password manager is currently locked or unlocked."
[^32]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "The script can simply detect which UI elements are present in the DOM and then use the correct method."
[^33]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "Due to incorrect web_accessible_resources definition, it was possible to load the entire password manager UI in an iframe."
[^34]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "Only necessary files should be defined in the web_accessible_resources."
[^35]: https://developer.chrome.com/docs/extensions/develop/security-privacy/stay-secure "will make an extension detectable by websites and attackers."
[^36]: https://developer.chrome.com/docs/extensions/develop/security-privacy/stay-secure "This makes content scripts vulnerable to leaking data via side channel attacks"
[^37]: https://developer.chrome.com/docs/extensions/develop/security-privacy/stay-secure "Assume any data sent to the content script might leak to the web page."
[^38]: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts "Content scripts running in isolated worlds have the following Content Security Policy (CSP):"
[^39]: https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/all "The all CSS shorthand property resets all of an element's properties except unicode-bidi, direction, and CSS Custom Properties."
[^40]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "Bitwarden Fixed: 2025.8.2 (31.8.2025)"
[^41]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "In addition to the clickjacking vulnerability, 1Password has confusing texting in the dialog box when filling in a credit card."
[^42]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "Some platform-level support should be created - new browser API protection for this clickjacking technique."
[^43]: https://marektoth.com/blog/dom-based-extension-clickjacking/ "The safest solution is to display a new popup window"
[^44]: https://developer.chrome.com/docs/extensions/develop/ui "A side panel lets users invoke extension features alongside web pages"
[^45]: https://developer.chrome.com/docs/extensions/reference/api/sidePanel "As an extension page, side panels have access to all Chrome APIs."
[^46]: https://developer.chrome.com/docs/extensions/reference/api/sidePanel "Availability Chrome 114+ MV3+"
[^47]: https://developer.chrome.com/docs/extensions/reference/api/sidePanel "If specified, the side panel options will only apply to the tab with this id."
[^48]: https://developer.chrome.com/docs/extensions/reference/api/sidePanel "When the user navigates to a site where the side panel is not enabled, the side panel will close"
[^49]: https://developer.chrome.com/docs/extensions/reference/api/sidePanel "This may only be called in response to a user action."
[^50]: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts "is a private execution environment that isn't accessible to the page or other extensions."
[^51]: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts "Although the execution environments of content scripts and the pages that host them are isolated from each other, they share access to the page's DOM."
[^52]: https://developer.chrome.com/docs/extensions/develop/security-privacy/stay-secure "hostile web pages may manipulate parts of the DOM the content script depends on"
[^53]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/iframe-content/autofill-inline-menu-iframe.service.ts "Creates an aria alert element that is used to announce to screen readers"
[^54]: https://raw.githubusercontent.com/bitwarden/clients/main/apps/browser/src/autofill/overlay/inline-menu/content/autofill-inline-menu-content.service.ts "that forces focus back inside their subtree; a menu appended to"
[^55]: https://chromium.googlesource.com/chromium/src/+/f3438d782566ef170b55f2aa13ff5f9b44f8d956/chrome/browser/ui/views/autofill/popup/popup_base_view.cc "readers that the focus is only changing temporarily, and the screen"
[^56]: https://developer.chrome.com/docs/extensions/how-to/ui/a11y "Check that a user can navigate between different parts of an extension without using the mouse."
[^57]: https://developer.chrome.com/docs/extensions/how-to/ui/a11y "removes the element from the tab sequence but still allows the element to receive keyboard focus programmatically."

## Open questions

- **Can a page draw over or capture clicks on the side panel?** No fetched Chrome page says so either way. The claim that the side panel is outside the page's reach is an inference from its being an extension page, not a documented guarantee.
- **Side panel width:** no API option exists. Whether the user can resize it, and the default width, are unsettled.
- **Page CSP and injected styles:** whether a page's `style-src` CSP blocks a `<style>` element or `adoptedStyleSheets` created by an isolated-world content script inside a shadow root is not settled by any fetched source.
- **How 1Password's credit-card confirmation is rendered,** and how Dashlane, LastPass and Keeper implemented their fixes, are not documented on any first-party page fetched.
- **Chrome's current Chromium head:** the `popup_base_view.cc` quotes are pinned to commit `f3438d78`, so whether `kAutofillPopupZOrderSecuritySurface` is on by default was not checked.
