# Portal-filling agents: is "cua-s1" better than our glass-box extension?

Date: 2026-10-03. Serves: the glass-box co-pilot extension
(`docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`; code read in
`/home/orkhan/Desktop/mailbox-graph-push`: `extension/src/content/fill.ts`,
`extension/src/content/snapshot.ts`, `extension/manifest.json`, `apps/portals/snapshot.py`).

## Answer first

- **cua-s1 is not a replacement and is not a fit for the extension.** It is Cua's (trycua) research
  family of small decision scorers, announced 2026-09-19. The form model takes structured elements
  plus extracted document values and picks one of fill/check/click/skip per element. It generates no
  values, reads no screenshots, and on out-of-vocabulary labels it gives a confident `skip`. The 4B
  variant needs over 9 GB of weights and seconds-to-minutes per decision. Neither runs inside an MV3
  extension. Neither is hosted. Neither is measured on OSWorld, WebArena or Online-Mind2Web.
- **Keep (a), the DOM snapshot + one LLM map per form version + deterministic replay, as the
  primary.** Every vision agent and every DOM agent pays model tokens on every application, and the
  vision agents also send screenshots of the student's filled form to a model vendor. (a) pays once
  per portal form version and sends nothing per student.
- **The gaps in (a) are coverage gaps, and an agent does not fix them.** Measured in our own code:
  the snapshot drops every checkbox and radio. It does not reach iframes, shadow DOM or
  contenteditable rich-text editors. It has no "add another" for repeatable blocks and no
  typeahead/combobox handling. Close these deterministically first (see Synthesis).
- **A vision fallback is not worth it.** A DOM-agent fallback through the existing server learn
  call ("map this unmapped control") is the cheap version. Treat it as optional, not as a
  prerequisite.

## Scope (sub-questions)

1. What is "cua-s1": vendor, date, size, licence, hosting, inputs, actions, benchmarks?
2. How do (a) our design, (b) vision computer-use agents and (c) DOM/accessibility-tree agents
   compare on cost, privacy, MV3 fit, determinism and widgets, with vendor prices?
3. What do the sampled portals ask, with which controls, and what can (a) not fill today?
4. Can an MV3 content script attach a file, and can custom upload widgets be driven? What file
   rules do the portals publish?
5. Do the portals' terms forbid automated filling or extensions? (This builds on the repo's
   seven-portal `terms_posture` sample.)

Tools: Exa (discovery and owner-domain step), Brave (exact phrase, second engine), scrapling `get` /
`bulk_get` (every quote below). Tavily and Context7 were not needed and not used. The `ide` MCP
server failed to connect, which made no difference here.

## 1. What is "cua-s1"?

**Identification.** I searched Exa ("announcement of CUA-S1, a computer-use agent model…") and
Brave (`"cua-s1"`, spellcheck off). Both return only one thing by that name: Cua's (trycua,
github.com/trycua/cua) CUA-S1 family. No other model shares the name.

- **Vendor and date.** It was a Show HN by Cua's founders, dated 13 days before 2026-10-03, which
  makes it 2026-09-19 (Exa's crawl date agrees). "S1" means "System One", Kahneman's fast and
  intuitive mode, borrowed from Typesafe's Jev. The first release, CUA-S1-FORMS, has 706k
  parameters and a 2.8 MB checkpoint.[^1]
- **What it does.** It takes structured elements plus values extracted from a document, and for
  each element it predicts use-value / CHECK / CLICK / SKIP. "It does not predict new values for
  text fields, and does not consider screenshots."[^2]
- **The vendor's only form numbers.** These are on its own synthetic task, against hosted Jev:
  99.7% vs 83.6% correct overall[^3], and 7-9 ms locally vs 260-280 ms per hosted call. The vendor
  says those latency samples are not end-to-end times.[^4]
- **The family today has four checkpoints, and the project calls itself early research.**[^5]
  - `cua-s1-form-v0`/`cua-s1-forms`: the 706,048-parameter form scorer.
  - `cua-s1-nano-0.1`: a from-scratch, ~855K-parameter option classifier.[^6]
  - `cua-s1-4b-0.1` and `cua-s1-4b-0.2`: LoRA adapters on a frozen Qwen3.5-4B, with a text
    (accessibility tree) mode and a multimodal (screenshot) mode.[^7]
- **Weights and licence.** The weights are public on Hugging Face and download without a token.[^8]
  The source is MIT.[^12] The model card says a future official checkpoint "may use separate terms"
  that require a commercial licence for production.[^17]
- **Hosting.** There is no API and no pricing: the HF page says the model "isn't deployed by any
  Inference Provider".[^18] You run it yourself.
- **Hardware for the 4B.** It needs more than 9 GB of weights in memory; "An 8 GB host or guest
  cannot run Cua-S1-4B inference".[^9] A warm CPU decision takes 20-50 s.[^10] The chooser accepts
  at most 26 candidates per decision.[^11]
- **Action space.** It chooses one option from a closed set that the caller enumerates (element
  plus action). It never generates free-form actions or values.[^7][^11]
- **Benchmarks.**
  - `cua-s1-4b-0.2` reaches an episode success rate of 0.944 (text) / 0.722 (multimodal) on Cua's
    own live `cua-bench-basic` environments.[^14]
  - It is "not measured on … `osworld_next_action`".[^15]
  - **No OSWorld, WebArena or Online-Mind2Web numbers exist from the vendor.**
- **Failure mode that matters for us.** Outside its 55-concept label catalogue, the form model
  "does not abstain and does not return a low-confidence answer". On held-out forms it scored 29.3%
  (12/41): "36 of 41 predictions were `skip`, with mean confidence 0.974".[^13] University portals
  (German/Swedish/Dutch labels, Anabin-style grade scales) fall outside a 55-concept English
  catalogue. In a desktop probe the 4B model picked an action whose condition did not hold, with
  probability 0.777.[^19] The vendor lists "unsupervised operation on production accounts or
  sensitive data" as out of scope.[^16]

**Fit for "filling forms on university websites".** Only `cua-s1-forms` is about forms, and it
answers a question we already answer deterministically: which verified value goes in which control.
It still needs someone else to produce the candidate list and the values. That is exactly our
FieldMap plus packet. It adds a model that can say `skip` wrongly and confidently, and nothing that
works inside a Chrome extension (Python, PyTorch/safetensors loaders). **Not recommended.**

## 2. Approaches compared on our constraints

The candidate list came from the caller's brief and the vendor pages below. I added one more found
while reading Anthropic's docs: Anthropic's own DOM-level "browser use tool".[^22] UI-TARS
(ByteDance) and Agent S (Simular) were **not researched** for lack of steps, so they are
**Unverified** here. Both are screenshot agents, so they would sit in row (b).

| | (a) Ours: snapshot → one LLM map per form version → deterministic replay | (b) Vision computer-use (Claude computer use, OpenAI computer use, Gemini computer use, cua-s1-4b multimodal) | (c) DOM / a11y-tree agents (browser-use, Stagehand, Nanobrowser, Skyvern) |
|---|---|---|---|
| What reaches a model | value-free control schema, once per form version (`apps/portals/snapshot.py` forbids a `value` key) | a screenshot of the page every turn, including the student's filled-in data[^20][^27][^28] | the page DOM / trimmed a11y tree every step[^31]; Stagehand's `observe()` keeps values out by returning selectors[^30] |
| Runs in the student's MV3 tab | yes (it exists) | no: each vendor expects you to run an execution environment and loop[^29][^24]; the reference implementation is Xvfb in Docker (Anthropic) | Nanobrowser yes (an MV3 extension, Apache-2.0)[^33][^35]; browser-use/Stagehand/Skyvern drive Playwright/CDP from outside the tab |
| Cost per application | ≈ $0 marginal (replay has no model call) | ~$1 per form at Sonnet 5.5 rates (arithmetic below) | per-step model calls; Stagehand can cache repeated actions[^32] |
| Determinism / replay | full; read-back is exact | none; the vendor warns against "tasks requiring perfect precision or sensitive user information without human oversight"[^23] | partial (Stagehand caching/self-heal) |
| Custom widgets | gaps listed in §3 | handles anything visible, by clicking, which our design forbids | DOM-level clicks; same conflict with "never click" |
| Hosted extras | — | — | browser-use cloud and Skyvern cloud sell stealth, proxies and CAPTCHA solving[^36][^39]; that conflicts with our no-circumvention rule and is unusable here |

Published form numbers: Skyvern claims "64.4% accuracy" on WebBench and calls itself the best
agent on WRITE tasks such as filling forms.[^38] That is a vendor claim on its own benchmark. I
found no form-filling benchmark for (a)-style replay; there the measure is read-back mismatches per
portal, which we already record.

**Cost arithmetic (vision agent, Claude Sonnet 5.5 as the example).** Prices are $2 per million
input tokens and $10 per million output tokens.[^25] The computer-use toolset adds about 4,500 input
tokens per request[^21], and each screenshot costs roughly 1,000-1,800 input tokens.[^20]
Assumptions (mine, **Unverified**): a 6-page application with ~60 fields, ~40 agent turns, each
turn carrying the toolset plus the last 3 screenshots (~4,500) plus ~3,000 tokens of text history,
so ≈12,000 input tokens per turn, and ~300 output tokens per turn.

- Input: 40 × 12,000 = 480,000 tokens × $2/M = **$0.96**.
- Output: 40 × 300 = 12,000 tokens × $10/M = **$0.12**.
- Total ≈ **$1.08 per application** on Sonnet 5.5, or ≈$2.16 at Opus 5.5's $4/$20 (same table).
- Keeping the full screenshot history instead grows the cost quadratically.
- Prompt caching lowers the cost; retries and wrong turns raise it.

**Cost arithmetic (ours).**

- One learn call per *form version per page*: ≤200 controls (the snapshot cap) at ~40 tokens each
  ≈ 8,000 input tokens, plus ~2,000 output tokens. At the same Sonnet 5.5 prices that is $0.016 +
  $0.02 ≈ **$0.04 per page version**, or ≈$0.22 for a 6-page portal.
- That cost is paid once per portal version and shared across every student in the tenant, so the
  per-application cost is ≈$0.
- Our actual learn model is the repo's `OPENAI_EXTRACTION_MODEL`, whose price I did not fetch
  (**Unverified**). The order of magnitude does not change.

**Cost (DOM agents).** Each step sends the DOM/a11y tree. I found no vendor per-step token figure
(**Unverified**). Assuming ~10-20k tokens per step and ~40 steps puts it in the same ~$1 range as
(b), less any caching.

**cua-s1 cost.** $0 in API fees, but it needs a ≥16 GB-memory host per decision service and 20-50
s per CPU decision.[^9][^10] That would be our own fleet, and it would mean shipping the student's
page state to it. It is worse on every axis that matters here.

**Recommendation.** Keep (a) as the primary. Do not add a vision agent, even as a fallback:

- it needs screenshots of PII-filled pages to leave the browser;
- it needs a click-capable action space that the design rules out;
- it costs ~$1 per application against ≈$0;
- it cannot run in an MV3 content script without our own remote loop.

If a fallback is wanted, the cheaper one stays inside (a): when verification finds an unmapped
required control, send a value-free snapshot of that one region to the existing learn endpoint and
extend the FieldMap. That is the same call, rate limit and PII guard as today.

## 3. What the portals ask, and what (a) cannot fill today

**What the current code cannot fill** (read from code, not from any vendor):

- `snapshot.ts` `REFUSED_TYPES` drops `checkbox` and `radio`, so every yes/no question, gender
  radio and consent checkbox is invisible to the map.
- `buildSnapshot` uses `root.querySelectorAll("input, select, textarea")`. That misses
  contenteditable rich-text editors and does not descend into iframes or shadow roots.
- `fill.ts` matches `<select>` options by exact value or text ("No option, no guess"). It has no
  path for typeahead/combobox widgets (type, wait, choose a suggestion), because choosing needs a
  click.
- There is no handling for repeatable blocks that need an "Add another" press. That is a click, and
  clicks are forbidden.
- Content scripts can run in iframes only when injected with `all_frames`/`allFrames`.[^46] The
  manifest declares no static content scripts; whether the programmatic injection sets `allFrames`
  was not checked (**Unverified**).

| Portal | Structure and fields (official help pages) | Upload rules | Notes for (a) |
|---|---|---|---|
| uni-assist / My assist (DE) | the per-university application form; "the questions may vary from university to university"[^52]; submitting means "paying the handling fee"[^53] | PDF only, ≤10 MB per file[^50][^51]; scans of *official* certificates[^55]; upload "at any time"[^56] | payment is the student's step; password reset asks for a captcha[^54] |
| universityadmissions.se (SE) | programme selection and prioritisation, then documents | colour scans of originals under the Documents tab[^57]; **uploads cannot be deleted** under Swedish law[^58] | a wrong attachment is irreversible, so `setFiles` here must be the student's confirmed act |
| Studielink (NL) | account creation needs an ID-document scan[^73]; previous education checked against DUO or entered manually; programme choice; institution questions[^74] | Studielink's own guide says no documents are uploaded in Studielink; they go to the institution (**Unverified**: seen only in the cached PDF text, since scrapling could not parse the PDF; the guide also mentions SMS verification at login) | per-institution portals (often DreamApply/Osiris) follow |
| UCAS (UK) | 13 sections, from personal details to references; DOB as day/month/year[^65]; up to two nationalities[^61]; up to five choices[^60]; all mandatory questions must be completed[^66]; fee £34.50 for 2027[^62] | uploads are optional (new for 2027)[^64] | personal statement is 4,000 characters including spaces[^59] (three questions from 2026 entry); the referee is entered by name/email and writes online[^63] |
| DreamApply (many EU universities) | appforms vary by citizenship/category[^70]; "sections with repeating blocks" for education history and work experience[^69] | documents either on the edit page before submit[^72] or as post-submission tasks[^71] | repeatable blocks are standard, so the "add another" gap bites here first |
| DAAD portal (scholarship) | online form plus attachments; tabular CV max 3 pages[^76]; motivation statement[^77]; a recommendation on a DAAD form from a university teacher[^79] | "You can only upload PDF files to the portal."[^75] | portal closes at 24.00 CET/CEST on the last day[^78] |
| Technolutions Slate, HISinOne, CampusNet, Common App, Erasmus Mundus consortium forms | **Unverified**: Slate's knowledge base is behind login; Common App's essay page renders by JS and returned no text; HISinOne/CampusNet/EMJM forms are per-institution and were not reached | — | — |

**Control types observed or documented:** text, select (long country lists), date entered in a
fixed format, multi-value nationality, repeatable blocks, character-limited essays, referee
contact fields, and file inputs.

Rich-text editors, typeahead widgets and iframes are not documented on any help page read
(**Unverified** per portal). They are the known classes the code cannot reach, so measure them on
the first ten real portals, as the spec already plans.

## 4. Document upload from an MV3 content script

- **Native `<input type=file>`.** Content scripts share the page DOM from an isolated world.[^44]
  `new DataTransfer()` exists in all browsers[^43], and `items.add()` accepts a `File`.[^42] So
  `fill.ts::attachDocuments` (build a DataTransfer, assign `input.files`, dispatch `change`) is the
  standard route.
  - The HTML spec's `files` setter, which makes this legal, could not be fetched (the page is too
    large for the tool): **Unverified** here.
  - The events we dispatch carry `isTrusted === false`; MDN says so for anything sent through
    `dispatchEvent()`.[^41] A page that checks `isTrusted` can ignore them, and read-back is the
    only detector.
  - No user activation is needed to set `files`: **Unverified**. Opening the picker programmatically
    *does* need one; FilePond's `browse()` "only works if the user initiaded the callstack".[^48]
- **Widget libraries.**
  - FilePond exposes `addFile(source)`.[^47] Uppy exposes `addFile(file)`/`addFiles(files)`.[^49]
  - Those are *page* JavaScript objects. An isolated-world content script cannot call them; only a
    script injected into the main world can, and then the page's CSP applies.[^45]
  - Many such widgets keep a hidden native file input that the DataTransfer route can target.
    Dropzone's hidden input was not verified (the options file was too large to read): **Unverified**.
  - Direct-to-S3/Azure presigned uploads run inside the widget after it accepts a file, so whatever
    gets the file into the widget gets it uploaded (**Unverified**, no vendor page read).
  - Recommendation: keep the spec's line. Use native inputs only, plus a dock instruction for the
    rest. Main-world calls into widget APIs are a per-portal exception, reviewed one at a time.
- **Published file constraints:**
  - uni-assist: PDF, ≤10 MB, scans of official certificates.[^50][^51][^55]
  - DAAD: PDF only.[^75]
  - universityadmissions.se: colour scans of originals, and no deletion.[^57][^58]
  - UCAS: optional uploads.[^64]
- **When uploads happen:**
  - uni-assist accepts them at any time before the deadline.[^56]
  - DreamApply has them either before submission or as post-submission tasks.[^71][^72]
  - DAAD wants all documents by the deadline (closing at 24.00).[^78]

## 5. Terms and detection

- The repo already sampled seven portals (spec "Decisions taken with the owner" §9). None forbids
  autofill in the applicant's own session; all forbid credential sharing. I did not repeat that.
- New this pass: UCAS's *UCAS Media* generic terms forbid using "any automated system, such as
  ‘robots’, ‘spiders’ or offline readers, to access the Website or the products".[^67] That
  contract is with UCAS Media Limited, for its products and services[^68], not the applicant
  application. The applicant terms are still unread (**Unverified**), so UCAS keeps
  `terms_posture = SILENT` / `AGENT_CHANNEL`. Its wording should be re-checked against the applicant
  terms before UCAS gets a FieldMap.
- **Portals known to block extension-driven input:** none found (**Unverified**, with no search
  hit). The technical signal a portal *could* use is `isTrusted === false` on our synthetic
  events.[^41]

## Synthesis

**Best option.** Keep (a). It is the only option that is ≈$0 per application, sends no student
value or screenshot off the device, runs in the student's tab, and is deterministic with exact
read-back. Rough costs per application:

- (a): ≈$0, plus ≈$0.04 per page version learned once.
- (b) vision agent: ≈$1.08 on Sonnet 5.5, ≈$2.16 on Opus 5.5.
- (c) DOM agent: ~$1, **Unverified** token counts.
- cua-s1: $0 in fees, but self-hosted on 16 GB+ machines at 20-50 s per CPU decision, with
  confident wrong skips.

**What to add to the current design,** in order:

1. **Radios and checkboxes for data answers.** Lift them out of `REFUSED_TYPES` for non-consent
   controls. Setting `checked` plus a `change` event is not a click. Keep consent and declaration
   boxes as "your turn" prompts.
2. **Repeatable blocks.** The extension cannot press "Add another". Fill the first block, then have
   the dock say "press Add, I will fill entry 2". Re-snapshot on a DOM mutation, the same pattern as
   strict Next. DreamApply makes this common.[^69]
3. **Typeahead/combobox.** Type the value with the native setter, then require the student to pick
   the suggestion. Read-back of the committed hidden value decides whether it took.
4. **Rich text and iframes.** Snapshot `[contenteditable]` and set its text. Inject with
   `allFrames` for same-origin and cross-origin frames under the granted host permission.[^46]
5. **Uploads.** Keep native-input `setFiles`. Make the attach a confirm-then-attach step on portals
   where uploads are irreversible (universityadmissions.se[^58]). Add a per-portal reviewed
   main-world adapter only where a widget library is measured on a real portal.
6. **Fallback.** No vision agent. If any fallback is added, use a scoped re-learn of unmapped
   controls through the existing server learn call (value-free, rate-limited).

## Open questions

- The UCAS applicant terms text, and whether any other sampled portal's applicant terms use
  "automated system" wording that would catch autofill.
- The HTML spec `files` setter and whether setting `files` needs user activation (spec page not
  fetched).
- How common iframes, rich-text editors and typeahead widgets are on the real portals: measure on
  the first ten, as the spec says.
- UI-TARS and Agent S pricing and benchmarks, and the vendor OSWorld / Online-Mind2Web numbers for
  OpenAI, Anthropic and Gemini computer use: not fetched.
- The price of `OPENAI_EXTRACTION_MODEL`, for the exact learn-pass cost.

## Sources

[^1]: https://news.ycombinator.com/item?id=49767564 "It has 706k parameters, and the original checkpoint is 2.8 MB."
[^2]: https://news.ycombinator.com/item?id=49767564 "It does not predict new values for text fields, and does not consider screenshots."
[^3]: https://news.ycombinator.com/item?id=49767564 "For the whole decision set: 99.7% correct vs 83.6%."
[^4]: https://news.ycombinator.com/item?id=49767564 "We measured 7-9 ms to score a form locally vs. 260-280 ms per call to hosted Jev"
[^5]: https://github.com/trycua/cua/tree/main/libs/cua-s1 "Cua-S1 is at an early research stage."
[^6]: https://github.com/trycua/cua/tree/main/libs/cua-s1 "a from-scratch, ~855K-parameter option-attention classifier"
[^7]: https://github.com/trycua/cua/tree/main/libs/cua-s1 "a LoRA fine-tune on top of the frozen, open-weight"
[^8]: https://github.com/trycua/cua/tree/main/libs/cua-s1 "All published Cua-S1 artifacts are public on Hugging Face and download without a token."
[^9]: https://github.com/trycua/cua/tree/main/libs/cua-s1 "An 8 GB host or guest cannot run Cua-S1-4B inference"
[^10]: https://github.com/trycua/cua/tree/main/libs/cua-s1 "On CPU, a single warm decision can take 20 to 50 s"
[^11]: https://github.com/trycua/cua/tree/main/libs/cua-s1 "The chooser supports at most 26 candidates, including"
[^12]: https://github.com/trycua/cua/tree/main/libs/cua-s1 "The source code in this component is available under the repository's MIT license."
[^13]: https://raw.githubusercontent.com/trycua/cua/main/libs/cua-s1/MODEL_CARD.md "Outside that vocabulary it does not abstain and does not return a low-confidence answer."
[^14]: https://raw.githubusercontent.com/trycua/cua/main/libs/cua-s1/MODEL_CARD.md "episode success rate is 0.944 text / 0.722 multimodal"
[^15]: https://raw.githubusercontent.com/trycua/cua/main/libs/cua-s1/MODEL_CARD.md "`general_decision` or `osworld_next_action` in either modality"
[^16]: https://raw.githubusercontent.com/trycua/cua/main/libs/cua-s1/MODEL_CARD.md "unsupervised operation on production accounts or sensitive data"
[^17]: https://raw.githubusercontent.com/trycua/cua/main/libs/cua-s1/MODEL_CARD.md "an official checkpoint may use separate terms that permit research and evaluation while requiring a commercial license for production"
[^18]: https://huggingface.co/cua-ai/cua-s1-4b-0.2 "This model isn't deployed by any Inference Provider."
[^19]: https://raw.githubusercontent.com/trycua/cua/main/libs/cua-s1/MODEL_CARD.md "text selected that action with probability 0.777 instead of abstaining"
[^20]: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool "Long agent loops accumulate screenshots quickly (roughly 1,000–1,800 input tokens each)."
[^21]: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool "with its default members adds about 4,500 input tokens to a request"
[^22]: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool "For tasks that stay inside webpages, the browser use tool is the closer fit"
[^23]: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool "Do not use Claude for tasks requiring perfect precision or sensitive user information without human oversight."
[^24]: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool "Anthropic processes the screenshot images and action requests in real time as part of the API call."
[^25]: https://platform.claude.com/docs/en/about-claude/pricing "The best combination of speed and intelligence $2 / MTok $10 / MTok"
[^27]: https://developers.openai.com/api/docs/guides/tools-computer-use "The model uses screenshots and other tool results to decide what to do next."
[^28]: https://ai.google.dev/gemini-api/docs/computer-use "the model predicts pixel coordinates scaled to the height and width of the screen"
[^29]: https://ai.google.dev/gemini-api/docs/computer-use "you will need to implement the client-side execution environment"
[^30]: https://raw.githubusercontent.com/browserbase/stagehand/main/README.md "observe() returns real selectors, so credentials never reach the model"
[^31]: https://raw.githubusercontent.com/browserbase/stagehand/main/README.md "Hybrid accessibility-tree trimming gives agents exactly the page context they need and nothing more."
[^32]: https://raw.githubusercontent.com/browserbase/stagehand/main/README.md "identical calls come back from Browserbase, no tokens spent"
[^33]: https://raw.githubusercontent.com/nanobrowser/nanobrowser/master/README.md "Nanobrowser is an open-source AI web automation tool that runs in your browser."
[^35]: https://raw.githubusercontent.com/nanobrowser/nanobrowser/master/README.md "WXT, Chromium Manifest V3"
[^36]: https://raw.githubusercontent.com/browser-use/browser-use/main/README.md "a $0.02 per browser-hour cloud browser with stealth, CAPTCHA solving and residential proxies"
[^38]: https://raw.githubusercontent.com/Skyvern-AI/skyvern/main/README.md "Skyvern is the best performing agent on WRITE tasks (eg filling out forms, logging in, downloading files, etc)"
[^39]: https://raw.githubusercontent.com/Skyvern-AI/skyvern/main/README.md "comes bundled with anti-bot detection mechanisms, proxy network, and CAPTCHA solvers"
[^41]: https://developer.mozilla.org/en-US/docs/Web/API/Event/isTrusted "when the event was dispatched via EventTarget.dispatchEvent()"
[^42]: https://developer.mozilla.org/en-US/docs/Web/API/DataTransferItemList/add "The item may be a File or a string of a given type."
[^43]: https://developer.mozilla.org/en-US/docs/Web/API/DataTransfer/DataTransfer "constructor creates a new DataTransfer object instance."
[^44]: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts "Content scripts live in an isolated world"
[^45]: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts "When a content script is injected into the main world, the CSP of the page applies."
[^46]: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts "should be injected into all frames matching the specified URL requirements"
[^47]: https://pqina.nl/filepond/docs/api/instance/methods/ "addFile(source [, options]) Adds a file"
[^48]: https://pqina.nl/filepond/docs/api/instance/methods/ "please note that this only works if the user initiaded the callstack"
[^49]: https://uppy.io/docs/uppy/ "addFile(file) addFiles(files) removeFile(fileID)"
[^50]: https://www.uni-assist.de/en/faqs/apply-online "You can only upload pdf files."
[^51]: https://www.uni-assist.de/en/faqs/apply-online "Each file can be a maximum of 10 MB in size."
[^52]: https://www.uni-assist.de/en/faqs/apply-online "The universities supply the application forms, so the questions may vary from university to university."
[^53]: https://www.uni-assist.de/en/faqs/apply-online "Submit your application by paying the handling fee."
[^54]: https://www.uni-assist.de/en/faqs/apply-online "Enter the email address you used to register in My assist and solve the captcha."
[^55]: https://www.uni-assist.de/en/how-to-apply/send-track/uploading-documents/ "We need scans of your official certificates."
[^56]: https://www.uni-assist.de/en/how-to-apply/send-track/uploading-documents/ "You can upload your documents at any time"
[^57]: https://www.universityadmissions.se/en/apply-to-masters/provide-application-documents-masters/submitting-your-documents/ "Scan your original documents in colour and upload them under the Documents tab"
[^58]: https://www.universityadmissions.se/en/apply-to-masters/provide-application-documents-masters/submitting-your-documents/ "According to Swedish law, once a document has been received, it's an officially registered document and cannot be deleted."
[^59]: https://www.ucas.com/applying/applying-to-university/filling-in-your-ucas-application "You have 4,000 characters, including spaces."
[^60]: https://www.ucas.com/applying/applying-to-university/filling-in-your-ucas-application "On your application overview you can add up to five choices"
[^61]: https://www.ucas.com/applying/applying-to-university/filling-in-your-ucas-application "You can submit up to two nationalities in case you have dual citizenship."
[^62]: https://www.ucas.com/applying/applying-to-university/filling-in-your-ucas-application "For 2027 entry, the application fee is £34.50 for up to five choices."
[^63]: https://www.ucas.com/applying/applying-to-university/filling-in-your-ucas-application "All applications require a reference from someone who isn’t a family member"
[^64]: https://www.ucas.com/applying/applying-to-university/filling-in-your-ucas-application "Uploading supportive documents is optional"
[^65]: https://www.ucas.com/applying/applying-to-university/filling-in-your-ucas-application "It's important that your date of birth is formatted as day/month/year."
[^66]: https://www.ucas.com/applying/applying-to-university/filling-in-your-ucas-application "You must complete all mandatory questions and you can’t skip any sections"
[^67]: https://www.ucas.com/about-us/policies/terms-and-conditions/ucas-media-generic-terms-service "use any automated system, such as ‘robots’, ‘spiders’ or offline readers, to access the Website or the products"
[^68]: https://www.ucas.com/about-us/policies/terms-and-conditions/ucas-media-generic-terms-service "We are UCAS Media Limited, a company registered in England and Wales."
[^69]: https://help.dreamapply.com/kb/admission-workflow/appforms/create-appforms/ "Allow applicants to add multiple entries within the same section, such as education history or work experience"
[^70]: https://help.dreamapply.com/kb/admission-workflow/appforms/create-appforms/ "appforms can vary based on the applicant’s citizenship or category"
[^71]: https://help.dreamapply.com/kb/admission-workflow/collect-documents/ "After an applicant submits their application, assigned tasks appear in the"
[^72]: https://help.dreamapply.com/kb/admission-workflow/collect-documents/ "Applicants are prompted to upload the necessary documents or materials before they can submit their application."
[^73]: https://info.studielink.nl/en/how-to-use-studielink "Once you have uploaded a scan of your identity document and entered your contact details"
[^74]: https://info.studielink.nl/en/how-to-use-studielink "you will be asked to check the previous education details registered with DUO or add previous education details manually"
[^75]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57742130 "Scan paper documents and save in PDF format. You can only upload PDF files to the portal."
[^76]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57742130 "in tabular form (max. 3 pages)"
[^77]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57742130 "statement about the academic and personal reasons for the planned study project in Germany"
[^78]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57742130 "The DAAD portal closes at 24.00 hrs. (CET or CEST) on the last application day."
[^79]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=57742130 "(on a DAAD-form) from a university teacher which provides information about your qualifications"
