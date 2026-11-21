# Co-pilot on-page guidance — marks on the portal, the panel as the control centre

**Status:** design, awaiting owner review (2026-10-09).
**Amends:** `2026-09-15-glass-box-copilot-design.md` (the "side-panel dock" in its Architecture).
**Evidence:** `docs/superpowers/research/2026-10-09-in-page-guidance-vs-side-panel.md`,
`docs/superpowers/research/2026-10-09-extension-in-page-ui-isolation.md` (both citation-checked).
**Not in this spec:** pre-filling free-text questions — a separate spec (the open-question tool,
`docs/superpowers/research/2026-10-09-portal-open-questions.md`).

## 1. Goal

A student applying to a university abroad — often for the first time, in a portal in a language
they do not read well, against a deadline — always knows three things: what the co-pilot just did,
what they must do next, and that nothing was sent without them. The co-pilot fills the form; the
student checks it and presses Next and Submit themselves. That check is the product: students use
it because they want to be sure the AI did nothing wrong.

## 2. Owner decisions (2026-10-09)

| # | Decision |
|---|---|
| D1 | **Hybrid.** Guidance is drawn on the portal page as marks; every control and the full record stay in Chrome's side panel. |
| D2 | **Straight to the right page.** The co-pilot opens the programme's application page directly (the Fill Packet's `form_url`). A logged-out student is sent by the portal to its login and back. |
| D3 | **We create and keep the student's portal account** (owner, 2026-10-09; reverses the 2026-09-15 "no portal credential exists anywhere"). The co-pilot signs the student up with the portal address issued for them and a strong generated password, stores the password in the secret store, logs in for them, and shows email + password on the dashboard when the student wants to enter the portal on their own. This is how agencies in Azerbaijan and the region work; the risk is recorded in §6. |
| D4 | **Documents attach automatically** while filling — no button — and are **prepared beforehand** to each programme's rules (size, format, pages, merging, file name). |
| D5 | **The final wording** is "Check every field and document. When you are sure everything is correct, press Next / Submit yourself. We never press it for you." |
| D6 | **The student chooses the panel's language** — Azerbaijani, Turkish, Russian or English — at first open and any time after; the default is their dashboard language. |
| D7 | **Amber is for genuine surprises only.** Its causes are removed by testing on the owner's real portals before a portal is offered to students (§9). |
| D8 | **Declarations are always left to the student.** |

## 3. The student's journey

1. **Apply.** On the dashboard the student presses "Apply to <programme>". The portal's application
   page opens in a new tab with the panel beside it, in the student's chosen language.
2. **Log in or sign up (§6).** If the portal shows its login, the co-pilot types the student's portal login and the student presses Log in; if it is a first visit, the co-pilot fills the sign-up's address and a generated password (§6) and the student presses Register.
3. **Start.** One button in the panel: "Start filling". Fields fill one by one with a short visible
   pause, so the student sees it happen.
4. **Marks appear on the page (§4)** beside each field, plus one next-step chip.
5. **Documents attach (§7)** into their fields, each with a tick and its file name.
6. **Pages.** On a multi-page form the panel's top line stays ("Page 2 of 4 · 9 of 12 done · 2 need
   you"), and the marks are redrawn on each new page.
7. **Check, then Next.** Before every Next and before Submit, the panel shows the review (§5) and the
   wording of D5.
8. **Sent.** The co-pilot reads the portal's confirmation and the dashboard card moves to Submitted.

## 4. On the page: marks only

### What is drawn

| Mark | Meaning |
|---|---|
| Green tick | Filled from the student's verified facts, and read back unchanged. |
| Amber outline + "Check this" | We are not sure the portal took the value as intended (§9 keeps this rare). |
| Red outline + "You fill this" | Only the student can answer it: a declaration, an essay box, a choice we hold no fact for. |
| Grey "Changed by you" | The student edited a value we filled; their value stands (§10). |
| File tick + file name | A document was attached to this upload field. |
| One next-step chip | The single thing the student must do now: "Answer this", "Press Next", "Solve the captcha". Never more than one. |
| "Why this value?" tag (on hover) | The source and date, e.g. "From your passport · checked 12 Sept". Never the value or any other data. |

All text is in the panel language (D6), whatever the portal's language. Every mark carries an icon
as well as a colour, so it is not colour-only.

### What is never drawn

No buttons, no links, no inputs, and no personal data — not even the value already in the field.
Every mark is display-only (`pointer-events: none`). This is the design's answer to DOM-based
extension clickjacking (Tóth, DEF CON 33: every password manager tested was tricked by a page making
the extension's UI invisible but clickable): there is nothing on the page worth clicking, so tricking
a click gains nothing. The worst a hostile page can do is hide a mark or draw a fake one; the panel's
review (§5) is the authority, never the marks.

### How marks are drawn

- **A layer over the page, never inside the portal's own fields**, the way Grammarly draws its
  underlines: writing into a host page's DOM corrupted text and crashed sites.
- **Isolated from the portal's CSS**: one custom element with a random tag name, holding a *closed*
  shadow root; inside, `all: initial` and the co-pilot's own font, so 2005-era portal CSS cannot
  restyle the marks and inherited properties are reset (Bitwarden's inline menu uses the same host
  shape).
- **Positioned against the field's box**, re-measured on scroll, resize and layout change; a
  `MutationObserver` re-attaches the layer if the page removes it.
- **Gives up quietly.** A mark that cannot be placed — the field is in a cross-origin frame, the
  layout fights back, the layer keeps being removed — is not retried forever: that row is shown in the
  panel instead. Nothing is ever only on the page.

## 5. In the panel: controls and the whole record

The panel is drawn by Chrome outside the page, so the portal cannot hide, fake or click it. It holds:

- **Start filling** and **Stop** (halts filling at any moment).
- **The progress line** and the current next step.
- **The full list**: every field and document with its state, including what cannot be pinned to the
  current page (later pages, unplaceable marks, values the portal changed after we typed them, errors
  such as "lost connection to Elmify").
- **The review before every Next and Submit**: everything filled, every document and the field it
  went into, everything still the student's, and every value the portal changed — then the D5 wording.
- **Language** (D6).

**Three sizes:** open for Start, **slim** while filling (the progress line and the next step), wide
for the review. Chrome gives no API to set the panel's width; "slim" and "wide" are the panel's own
layout, collapsing or expanding its content.

## 6. The portal account: created, kept and used for the student (D3)

- **Direct link (D2).** The panel opens the Fill Packet's `form_url`. If the portal asks for a login,
  the co-pilot logs in for the student and returns to the form.
- **First visit: sign-up.** The co-pilot fills the sign-up form with the student's facts, the portal
  address issued for them (`PortalAccount`, a tag on the student's own inbox — no platform mailbox),
  and a **generated strong password** (random, 20+ characters, meeting the portal's own rules, which
  the bench records). The student never has to invent or remember it.
- **Mail the portal sends is handled for the student (owner, 2026-10-09).** When the portal says "we
  sent a code / a link to your email", the platform reads that mail from the student's connected inbox
  (only mail from that portal's sender, as the mailbox connection is already scoped) and the co-pilot
  types the code into the portal, or opens the verification link in the student's own browser. The
  student does not have to switch to their inbox. The panel says what happened ("Verification code
  from TUM entered"). If no mail arrives within a few minutes, or the inbox is not connected, the
  panel asks the student to type the code themselves.
- **Later visits: login.** The co-pilot fills the login form; the student presses Log in (the co-pilot
  still never clicks — it types, the student clicks). If the portal asks for MFA or a captcha, it is
  the student's turn as in §10.
- **The dashboard shows the credentials** on request — "Your TUM portal login: aysel.m+k3x9@gmail.com /
  ••••••• [show]" — so the student can always enter the portal without us. Revealing the password
  asks the student to confirm their own identity again and leaves an AuditEvent.
- **Where the password lives** (CLAUDE.md's standing rule, "Portal credentials never live in the
  database"): a dedicated secret store (Secrets Manager under its own KMS key, one secret per
  student-portal account), readable only by the service that mints the login for the extension; never
  a model field, never logged, never in an exception message, never in the evidence bucket. The
  extension receives it only for the login page, in session memory, and types it like any value.
- **Erasure** destroys the student's portal secrets on the same path that deletes their documents
  (`advance_deletion`), or GDPR erasure leaves credentials behind.
- **The student can take the account over** at any time: "I changed my password" in the dashboard
  stops the co-pilot logging in for that portal (it then waits for the student to log in, as a fallback
  for any portal whose login we cannot fill).
- **Risk, recorded:** every portal in the 2026-09-15 seven-portal terms sample forbids sharing
  credentials. Holding them puts the platform on the wrong side of those terms (an account could be
  suspended), and makes the secret store a target worth attacking (one breach = thousands of students'
  portal accounts). The owner accepts this as regional practice; the controls above are the price.

## 7. Documents attach automatically (D4)

- **Prepared beforehand.** Each programme's document rules are already read (the requirement reader):
  maximum size, format (PDF or JPG), page limits, "all diplomas as one PDF", file-name patterns. Before
  the student reaches the portal, the platform prepares each file to fit: compress, convert, merge,
  rename, and keep generated documents within page limits. The panel message for a rejected file
  ("the portal wants a JPG under 2 MB") is kept only for a rule nobody wrote down.
- **Which box gets which file.** The co-pilot reads each upload box the way a person does — its own
  label, the heading above it, the text around it ("Degree 2 — upload transcript") — when it learns
  the form (§10, "A form we have not mapped yet"). An unnamed "Upload" box is matched by its heading.
  An original and its English translation each go to their own box; the platform holds both.
- **Repeated sections** ("Degree 1", "Degree 2") are filled from the student's own degrees when the
  platform knows them; only a section the platform holds nothing for is left to the student.
- While filling, each approved document (CV, transcript, letters — P1-14 approval) is attached to the
  upload box the FieldMap names for it, and gets a file tick on the page and a row in the review.
- **Never into a field the student cannot see.** Today `extension/src/content/fill.ts::attachDocuments`
  matches file inputs by accessible name and does **not** check visibility (field values are
  checked, in `verify.ts::verifyEntries`; documents are not). Portals often hide the native file input
  behind a styled "Upload" button, so "the input itself is visible" is the wrong test. The rule:
  the input, or the label/button that opens it, must be visible and must carry the document's name;
  otherwise the document becomes a panel instruction ("Attach cv.pdf here") and is not attached. This
  closes the one real data risk on a compromised portal: a hidden file input receiving a passport scan.
- Custom drag-and-drop or direct-to-cloud upload widgets with no file input stay a panel instruction,
  as today.

## 8. Safety rules this design keeps

1. The Fill Packet stays in the service worker's session storage; marks receive states and sources,
   never values.
2. Fills and attachments act only on the portal origin the server pinned, only on fields the
   FieldMap is sure of (bench-verified or learned live, §10), only on visible fields (§7).
3. The co-pilot never clicks Next, Submit, consent or navigation. It types; the student clicks.
4. The panel is the authority. A mark the page hid or faked cannot change what the review says.

## 9. Making amber rare: the portal test bench (D7)

Amber comes from four causes: a format the portal reads differently (dates, phone numbers, name
order), a dropdown option that does not match ("Azerbaijan" vs "Azerbaijan, Republic of"), an
uncertain FieldMap, and the portal changing a value after we typed it.

- **On the owner's real portals, without polluting them.** For each supported portal, the owner
  walks a real application in their own account and the co-pilot records every page (snapshot).
  Repeat runs fill those **saved copies offline** from sample students chosen to hit the hard cases:
  long and multi-part names, ə/ğ/ı letters, foreign date formats, several degrees, a translation plus
  an original. The bench **never** creates accounts for sample students on a live portal and
  **never** presses Next or Submit there: fake applicants in a university's system would breach the
  portal's terms and waste its staff's time. Live checks are the owner's own account only, stopped
  before Submit.
- **Every amber is counted and fixed in the rules** — a format rule, a dropdown synonym, a FieldMap
  correction — never left for the student.
- **The verified gate.** A portal's map counts as *verified* only when its bench run shows **zero ambers**,
  every document attaching, and the sign-up/login path behaving as §6 says. Until then the portal is still
  served by the live-learned map (§10), with every unsure field left to the student. The bench is
  re-run when a portal changes its form; amber on a verified portal then means a genuine surprise.
- **The wording is framed on the same runs**: every panel message and mark label is read in all four
  languages against the real pages before release.

## 10. Cases the journey must handle

| Case | Behaviour |
|---|---|
| **The student edits a field we filled** | Their value wins. The mark turns grey "Changed by you", the review shows their value, and the co-pilot never types over it — not on re-fill, not on resume. Read-back tells "the student changed it" (an input event after our fill) from "the portal changed it" (no student input). |
| **The portal changes a value after we typed it** | Uppercased name, reformatted date, cleared dropdown. A change the bench taught us is harmless (§9) stays green; anything else is amber and is listed in the review with both values. |
| **The portal logs the student out mid-form** | The co-pilot recognises the login page, pauses, and the panel says "The portal logged you out. Log in again; we'll continue where you were." After login it re-reads the page and fills only what is empty. |
| **The student comes back later** (another day, Fill Packet expired after 2 h) | A fresh packet is fetched; fields already correct are left alone (`already_correct`); marks are rebuilt from what the page holds now. Nothing typed twice, nothing overwritten. |
| **Back button / a page reloaded** | Same as coming back: re-read, mark, fill only what is empty. |
| **Fields that appear after a choice** (country → region list loads) | The co-pilot waits for the dependent field to appear (bounded, then a panel row "We couldn't find <field> — fill it yourself"), and marks re-position after the layout shifts. |
| **The portal shows its own error after Next** ("Invalid postcode") | The co-pilot reads the portal's error next to the field, marks the field red, and the panel shows it with a plain explanation in the student's language. The portal's own text is shown too, so nothing is lost in translation. |
| **Email verification code or link** | Handled for the student (§6): read from their inbox, typed or opened, shown in the panel. |
| **Captcha, SMS or authenticator-app codes** | A "Your turn" chip on the page and a panel row; the co-pilot waits and resumes after (existing challenge detection). |
| **The form is inside a frame from another site** | Filling and marks work only where the extension is allowed on that frame's origin; otherwise every field of that frame is a panel row. |
| **Two applications open at once** | Each tab has its own panel state (`chrome.sidePanel` per tab) and its own packet; nothing crosses tabs. |
| **The student closes the panel mid-fill** | Filling pauses. Reopening resumes from the page's current state. Nothing runs without the panel open. |
| **A document the portal rejects** (too large, must be JPG, max pages) | The panel says what the portal wants and offers the right file from the student's documents if one exists; a format conversion is not in this spec. |
| **Two upload boxes with the same label** ("Transcript" twice) | Told apart by the heading and text around each (§7). If the context still does not tell them apart, the panel asks the student which box gets which file — never a guess. |
| **A small laptop screen (1366 px)** | Slim panel while filling; marks never cover the field's own text or the portal's buttons — a chip that would overlap a button moves to the field's other side or into the panel. |
| **Page zoom, dark mode, right-to-left pages** | Marks follow the field's box at any zoom; their colours are the co-pilot's own, not the page's. |
| **The student asks for deletion, or their pairing is revoked** | Filling stops at once and the panel says why (the device token dies with the account — 2026-09-17 rule). |
| **A form we have not mapped yet** (a new university, or a portal that changed its form) | The co-pilot learns it on the spot: it snapshots the page, the server works out what each field and upload box asks for (labels, headings, surrounding text) and returns a map, and the co-pilot fills from it. A field the map is sure of is filled and read back as usual; a field it is unsure of is not guessed — it is left red "You fill this" with what we think it asks. The page is recorded so the bench (§9) verifies the map and the next student gets it fully. |

## 11. What the portal can learn about us

The marks layer and the typing are visible to the portal's own scripts: a portal can tell that this
student used the co-pilot. That is accepted — the seven-portal terms sample forbids credential
sharing, not autofill — but it means nothing in the page layer may carry an identifier of the
student, the platform account or the agency. Events reported to our server carry states, never
values, as today.

**One exception: the answers channel** (owner, 2026-10-09; plan 5 Task 6). When the student opens the review, the co-pilot sends what they typed into boxes we left red, and into boxes where they changed our value. That way the system learns from real answers. It never sends a password field or any box the packet did not name, and the server refuses both. The values stay in the student's own tenant (`portals.PortalAnswer`, FORCE RLS, erased with the student). They never reach a model, a shared map, a mark or the dock state. A map learns only which field a box asks for: 3 students confirming a guess make it sure, and 2 agreeing corrections re-point it.

## 12. Accessibility

The marks layer is `aria-hidden`: a screen reader user gets everything from the panel, which is an
ordinary extension page with real headings, lists and buttons. Marks are never colour-only. Keyboard
focus is never moved onto the portal page by the co-pilot.

## 13. Open

- Each portal's password rules and login form (§6) — recorded on the bench.
- Whether the plain-language explanation of a portal's error (§10) is a fixed list per portal (from
  the bench) or produced by a model; a model would see portal text only, never the student's values.
- Firefox and Safari: unchanged from the 2026-09-15 spec (Chromium first).
- The open-question tool (second spec).
