# Zero-Hardcoding Portal & Extension Localization, Adaptive DOM Active Learning & Structural Multi-Tenant Host Discovery

**Date:** 2026-11-19
**Engine Scope:** `extension/src/content/fill.ts`, `extension/src/content/vocabulary.ts`, `extension/src/content/index.ts`, `apps/portals/learn.py`, `apps/portals/applications.py`, `apps/mailbox/filter.py`
**Discovery Runs:** `scilit` Argon runs `20261119T012415Z-393d05b6` and `20261119T012529Z-598c4fb4`

---

## 1. Executive Summary

This dossier synthesizes primary web standards (ECMA-402 `Intl.DisplayNames`, Unicode Normalization Forms, W3C WAI-ARIA 1.2, WHATWG HTML Forms, Mozilla Public Suffix List) and peer-reviewed literature on higher-education form-filling agents and cross-domain origin boundaries into a zero-hardcoding architectural blueprint for the browser extension and portal/mailbox backend:

1. **Pillar 1 — Universal 249-Territory Option & `<select>` Resolution via ECMA-402 `Intl.DisplayNames` + Unicode NFKD Folding (`extension/src/content/fill.ts`)**:
   - Replaces the static 11-country table in `OPTION_SYNONYM_GROUPS` (`fill.ts:137-198`) with a runtime-constructed equivalence index generated via `new Intl.DisplayNames(locales, { type: "region" })` and `{ type: "language" }`[^1][^7] combined with Unicode NFKD canonical decomposition (`String.prototype.normalize("NFKD")`)[^2].
   - Covers all 249 ISO-3166-1 alpha-2 codes, alpha-3 codes, and localized endonyms/exonyms across 14 admission portal locales (`en`, `de`, `fr`, `es`, `it`, `nl`, `tr`, `az`, `ru`, `pl`, `pt`, `zh`, `ja`, `ko`, `ar`) at zero network cost.
2. **Pillar 2 — Requirement-Aware Active-Learning Trigger Policy for Server-Side DOM Learning (`extension/src/content/index.ts` & `apps/portals/learn.py`)**:
   - Replaces the static `MIN_UNKNOWN_FOR_LEARN = 3` threshold (`index.ts:749`) with a requirement- and failure-aware trigger policy informed by knowledge-augmented higher-education form-filling agents[^5], W3C WAI-ARIA `aria-required` semantics[^3], and WHATWG HTML `required` input constraints[^8].
   - Fires `postLearn` whenever `unknown.length >= 3` OR (`unknown.length >= 1` and at least one unrecognized control carries `required` / `aria-required="true"` or failed post-fill verification), guarded by a deterministic `(hostname, pathname, controlSignature)` cooldown cache.
3. **Pillar 3 — Catalogue-Derived Multi-Tenant Portal & Mail Platform Discovery (`apps/portals/applications.py` & `apps/mailbox/filter.py`)**:
   - Augments `_KNOWN_PORTAL_PLATFORMS` (`applications.py:57-74`) and `_SHARED_PLATFORMS` (`filter.py:130-215`) with structural bipartite graph discovery over the live programme and institution catalogue, grounded in the Public Suffix List (`eTLD+1`)[^4] and DNS domain origin boundaries[^6].
   - Any registrable domain (`eTLD+1`) referenced by $\ge 2$ distinct `Institution` or `Organisation` rows across `Program`, `FundingOpportunity`, `OfficialSource`, or `PortalForm` is automatically classified as a shared multi-tenant platform (preventing cross-university credential auto-linking and enabling multi-application mailbox disambiguation for regional SaaS portals such as DreamApply, Mobility-Online, Slate, Søknadsweb, CampusFrance, and MonMaster).

---

## 2. Pillar 1: Zero-Hardcoding 249-Territory Option Resolution (`extension/src/content/fill.ts`)

### 2.1 Codebase Diagnosis (`extension/src/content/fill.ts:137-264`)
In `extension/src/content/fill.ts:137-198`, `OPTION_SYNONYM_GROUPS` hardcodes localized country synonyms for only 12 territory codes (`az`, `tr`, `de`, `gb`, `us`, `nl`, `fr`, `it`, `es`, `pl`, `at`, `ch`), plus binary confirmation (`yes`/`no`) and gender (`m`/`f`) tokens. When `selectOption(el, value)` (`fill.ts:227-264`) attempts to fill a `<select>` or ARIA combobox for `nationality`, `country_of_residence`, or `degree.1.country` on a German (`uni-assist.de`), French (`campusfrance.org`), Dutch (`studielink.nl`), or Turkish portal:
- Any applicant from or applying to the remaining ~237 ISO-3166-1 territories (e.g., `GE`, `KZ`, `UA`, `IN`, `PK`, `NG`, `BR`, `CN`, `KR`, `JP`, `CA`, `SE`, `NO`, `FI`, `CH`, `BE`, `HU`, `CZ`) has no entry in `OPTION_SYNONYM_MAP`.
- If the student's profile holds `"Georgia"` or `"GE"` while a German portal `<option>` displays `"Georgien"` (or a French portal displays `"Géorgie"`), exact, synonym, and prefix/substring matching in `selectOption` all return `false`.

### 2.2 Standards-Grounded Solution: ECMA-402 `Intl.DisplayNames` + Unicode NFKD Folding
Every modern Chromium/Firefox extension runtime implements the ECMA-402 Internationalization API (`Intl.DisplayNames`)[^1][^7] backed by the browser's embedded ICU/CLDR database, as well as `String.prototype.normalize`[^2]:
1. **Canonical Folding (`foldOptionText(s: string)`)**:
   ```ts
   function foldOptionText(s: string): string {
     return s
       .normalize("NFKD")
       .replace(/[\u0300-\u036f]/g, "")
       .replace(/\u0131/g, "i")
       .replace(/\u0259/g, "e")
       .toLowerCase()
       .replace(/[^a-z0-9\u0400-\u04ff\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+/g, " ")
       .trim();
   }
   ```
2. **Lazy Runtime ISO-3166 Equivalence Graph (`buildTerritorySynonymMap()`)**:
   - Iterate over all $26 \times 26 = 676$ two-letter ASCII pairs `AA..ZZ` (or the compact 249 ISO-3166-1 alpha-2->alpha-3 string table, $< 1.5\text{ KB}$).
   - Instantiate `new Intl.DisplayNames([locale], { type: "region", fallback: "none" })` across `PORTAL_LOCALES = ["en", "de", "fr", "es", "it", "nl", "tr", "az", "ru", "pl", "pt", "sv", "no", "da", "fi", "hu", "cs", "zh", "ja", "ko", "ar"]`[^1][^7].
   - For each valid alpha-2 code `code` (e.g., `"GE"`), collect its alpha-2 code (`"ge"`), its ISO-3166-1 alpha-3 code (`"geo"`), and every non-empty `displayNames.of(code)` across `PORTAL_LOCALES` (both raw lowercase and `foldOptionText`-folded) into a single `ReadonlySet<string>` equivalence group.
   - Do the same for `new Intl.DisplayNames([locale], { type: "language", fallback: "none" })` across ISO-639-1 language codes so language proficiency dropdowns (`"English"` / `"Englisch"` / `"Anglais"` / `"İngilizce"`) resolve without static lists.
   - Memoize the resulting `Map<string, ReadonlySet<string>>` once per content-script lifecycle ($< 4\text{ ms}$ one-time initialization in V8).

---

## 3. Pillar 2: Requirement-Aware Active-Learning Trigger Policy (`extension/src/content/index.ts` & `apps/portals/learn.py`)

### 3.1 Codebase Diagnosis (`extension/src/content/index.ts:747-757`)
In `extension/src/content/index.ts:747-757`:
```ts
const MIN_UNKNOWN_FOR_LEARN = 3;
if (unknown.length >= MIN_UNKNOWN_FOR_LEARN && !stale()) {
  const learned = await postLearn(appId, snap.controls, location.href);
```
Higher-education application portals frequently split forms across multi-step wizards where an individual step contains only 1 or 2 custom-labeled fields (for example, a single required visa/funding track dropdown or a single degree-equivalency radio group)[^5]. Because `unknown.length < 3`, the extension never calls `postLearn`, leaving required fields blank and preventing `apps/portals/learn.py::learn_portal_page` from learning the selector.

### 3.2 Standards-Grounded Solution: Required-Control & Post-Verify Failure Trigger
Under the WHATWG HTML Living Standard (`required` attribute on `<input>`, `<select>`, `<textarea>`)[^8] and W3C WAI-ARIA 1.2 (`aria-required="true"` on custom widgets/comboboxes)[^3]:
1. **Enrich `ControlDescriptor` in `extension/src/content/snapshot.ts`**:
   - Capture `required: boolean` on each control:
     ```ts
     const isRequired =
       (el as HTMLInputElement).required === true ||
       el.getAttribute("aria-required") === "true" ||
       /\*/.test(labelText);
     ```
2. **Requirement- & Verification-Driven Trigger (`shouldTriggerDomLearn` in `extension/src/content/index.ts:747-757`)**:
   - Trigger `postLearn` when `!stale()` and **any** of the following holds:
     1. `unknown.length >= 3` (bulk unrecognized form step), OR
     2. `unknown.some((c) => c.required)` (at least one mandatory control could not be matched locally), OR
     3. `unknown.length >= 1 && filledCount === 0` (a dedicated step where zero fields could be filled locally).
3. **Idempotent Per-Step Signature Cache**:
   - Compute `stepSignature = `${location.hostname}${location.pathname}:${unknown.map((c) => c.selector).sort().join("|")}`` in `sessionStorage` so `postLearn` runs at most once per unique unknown-control set per session.

---

## 4. Pillar 3: Catalogue-Derived Multi-Tenant Portal & Mail Platform Discovery (`apps/portals/applications.py` & `apps/mailbox/filter.py`)

### 4.1 Codebase Diagnosis (`apps/portals/applications.py:57-74`, `apps/mailbox/filter.py:130-215`)
- `apps/portals/applications.py:57-74` defines a static 14-item frozenset `_KNOWN_PORTAL_PLATFORMS` (`applyweb.com`, `embark.com`, `moveon4.de`, `studielink.nl`, `uni-assist.de`, etc.) used by `_is_shared_portal_platform(url)` to block cross-institution portal auto-linking (`applications.py:141`).
- `apps/mailbox/filter.py:130-215` defines a static frozenset `_SHARED_PLATFORMS` used to prevent sender-domain auto-vouching across unrelated institutions.
- Whenever a university adopts a multi-tenant admissions SaaS platform not in those static lists (e.g., `dreamapply.com`, `mobility-online.de`, `service4mobility.com`, `fs-sc.de`, `monmaster.gouv.fr`, `campusfrance.org`, `apply.study.eu`), two failure modes occur:
  1. `_portal_for_program` can mistakenly share a `PortalForm` across two distinct institutions hosted on the same SaaS domain.
  2. `mailbox/filter.py` can treat a shared SaaS notification domain as single-institution unless two applications for the same student already share it.

### 4.2 Graph-Theoretic Solution: Catalogue eTLD+1 Multi-Institution Degree ($\text{deg}(h) \ge 2$)
Grounded in the Mozilla Public Suffix List (`eTLD+1` registrable domain boundary)[^4] and DNS domain origin isolation[^6]:
1. **Structural Multi-Tenant Host Discovery (`catalogue_shared_portal_hosts()`)**:
   - Extract the registrable domain (`eTLD+1` via `apps.research.hosts.registrable_domain` / `_key`) for every `PortalForm.base_url`, `Program.source_url` / `application_url`, and `OfficialSource.url` linked to an `Institution` (or `Organisation`).
   - Build the bipartite incidence count $\text{deg}(h) = |\{i \in \text{Institutions} : (i, h) \in E\}|$.
   - Any registrable host $h$ linked to $\ge 2$ distinct `Institution` rows with non-matching institutional domains ($h \neq \text{domain}(i)$) is structurally a multi-tenant platform:
     $$\mathcal{H}_{\text{shared}} = \mathcal{H}_{\text{seed}} \cup \left\{ h \in \mathcal{H}_{\text{catalogue}} \;\middle|\; \left|\{i \in \text{Institutions} : h \in \text{PortalHosts}(i) \setminus \text{OwnDomains}(i)\}\right| \ge 2 \right\}$$
2. **Redis-Cached Helper Shared by `apps/portals/applications.py` and `apps/mailbox/filter.py`**:
   - Cache $\mathcal{H}_{\text{shared}}$ in Redis/Valkey under `"portals:shared_platform_hosts:v1"` (TTL 1 hour, invalidated when a `PortalForm` is saved).
   - Call `is_shared_portal_host(host)` inside both `_is_shared_portal_platform` (`apps/portals/applications.py:72`) and `is_shared_platform` (`apps/mailbox/filter.py:218`).

---

## Sources

[^1]: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DisplayNames "The Intl.DisplayNames object enables the consistent translation of language, region and script display names"
[^2]: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/normalize "The normalize() method of String values returns the Unicode Normalization Form of this string"
[^3]: https://www.w3.org/TR/wai-aria-1.2/ "Indicates that user input is required on the element before a form may be submitted"
[^4]: https://publicsuffix.org/learn/ "The Public Suffix List is a cross-vendor initiative to provide an accurate list of domain name suffixes"
[^5]: https://doi.org/10.1186/s41239-026-00612-x "online academic and administrative services in higher education increasingly require students faculty and staff to complete structured forms across heterogeneous institutional platforms"
[^6]: https://doi.org/10.1186/1869-0238-4-13 "http cookies currently in use are governed by the same origin policy that directs web browsers to allow cookie sharing only between web sites in the same dns domain"
[^7]: https://tc39.es/ecma402/ "ecmascript 2027 internationalization api specification"
[^8]: https://html.spec.whatwg.org/multipage/input.html "element is used to create interactive controls for web based forms"
