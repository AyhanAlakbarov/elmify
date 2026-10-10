# The glass-box co-pilot: the extension types, the student clicks

Status: **design, direction agreed with the owner 2026-09-15** (see "Decisions taken with the owner");
spec text awaiting final read. Authorizes planning only.
Date: 2026-09-15.
Supersedes, in part: `2026-08-27-phase3-portal-execution-design.md` (the server-side browser,
credentials, reauthentication, session persistence, the resume spike) and decisions 3, 4 and 5 of
`2026-08-25-application-automation-decisions-design.md`. Decisions 1, 2 and 6 of that record stand.
Leaves untouched: `2026-08-26-browser-isolation-design.md` — that is the *research* browser tier,
which never held credentials and is not this.
Requirements amended: `phased requirements.md` §2, §2.1, §5.1, §5.2, §5.4, §5.5, §5.6, §10 (dated
2026-09-15 blocks in place).

## Goal, in three beats

**What and why.** Move the form-filling browser from a platform-run EC2 task holding
platform-managed portal passwords into the student's own browser, as an extension paired to the
dashboard. The dashboard still discovers, prepares and verifies; the extension fills the visible
portal tab field by field while the student watches; the student presses Submit. The portal-agnostic
core — field maps, the typed-values-only action allowlist, read-back against the rendered page, the
escalation taxonomy, the §5.5 audit trail — is kept. What is retired is everything that existed only
because the browser was remote: portal credentials in Secrets Manager, reauthentication, per-tenant
browser profiles, the sandboxed EC2 tier, and the pause / hand-to-a-consultant / resume problem that
`CLAUDE.md` still lists as the unrun spike §5.2 depends on in six places.

**The catch.** Fills happen only while the student is present, in a Chromium browser on a computer.
There is no background execution, no consultant filling on the student's behalf, and therefore no
`counselor-submit` mode and no 48-hour auto-submit: the platform can no longer press Submit for
anyone, by construction. The extension runs on a machine we do not control, against a page DOM the
portal controls; the design treats both as untrusted. The Chrome Web Store review becomes an external
gate on every release.

**What it costs to reverse.** Nothing until the deletion plan runs: `PortalDesiredCount` is already
`0`, so the server tier can stay in the tree, dormant, until the extension passes the ported tests.
After deletion, going back means rebuilding the credential store and the EC2 tier — a week, not a
quarter — and re-opening the §10 terms question in its harder form.

## What the code says today (measured, not inferred)

- **Nobody submits.** `apps/portals/services.py` stops at `READY_TO_SUBMIT`; its docstring says there
  is deliberately no code path that could submit if a flag were flipped. `Application.State` has
  `SUBMITTED`/`CONFIRMED` members nothing sets. The built pipeline is already `student-submit`.
- **Nothing uploads.** `session.py::FILL_METHODS` is `{fill, type, selectOption,
  selectOptionFromDropdown}`; `grep upload|setInputFiles` over `apps/portals` finds nothing. Yet
  §5.5 requires the audit trail to cover "uploaded documents" and §5.6 requires uploading a requested
  document to the portal. A content script driving a real `<input type=file>` is the natural closer.
- **Half the modules exist because the browser is remote.** `auth.py` (Secrets Manager credentials,
  reauth), `profiles.py` (per-application Chrome profiles with live cookies), `engine.py` (pinned
  Chrome, event-loop bridge, sandbox refusal), `resolve.py` (CAPTCHA service / consultant),
  `dispatch.py` (resume polling), `worker.py`/`queue.py`, and in `infra/template.yaml` the
  `PortalTaskDefinition`, `PortalTaskRole`, `PortalSecurityGroup` (admitted to Postgres on 5432),
  `PortalInstanceRole`/`Profile`, launch template, ASG, capacity provider and `PortalDesiredCount`.
- **The learn pass runs the model from inside the browser process.** `PortalTaskDefinition` carries
  `ANTHROPIC_API_KEY` because Stagehand's `observe()` calls the model from the browser
  (`infra/template.yaml`, comment near line 2510). The extension design moves that call to the server.
- **The other half is pure logic.** `models.py` (`PortalForm`, `FieldMap` — platform-shared, no PII,
  no tenant scope), `session.py` (allowlist), `profile.py` (verified facts → `"category.key"`),
  `fill.py::already_correct` and `read_back`, `escalation.py` (six triggers), `recovery.py`'s FILL
  audit write, `reporting.py`, and the first three steps of `services.py::prepare_application`
  (field map → verified values → `MISSING_FACT` before any browser opens).

## Decisions

1. **The extension types, the student clicks.** The content script executes the four
   `FILL_METHODS` plus one new method, `setFiles`. It never dispatches a click on a navigation,
   consent or submit control, and the allowlist is enforced in the content script exactly as
   `fill.py` and `engine.py` enforce it today, before any action runs. Multi-step forms: the student
   presses *Next*; the extension detects the new step and fills it. This generalises the owner's
   "student clicks Submit themselves" into the rule that makes the terms position defensible.

2. **The server prepares; the packet is the authority.** The dashboard's *Launch & Autofill*
   action asks the server to mint a **Fill Packet** for one `Application`: the current `FieldMap`
   version, the verified values it names, the approved documents to attach, `form_url`, and an
   expiry. Minting runs the same three checks `prepare_application` runs before it opens a browser
   today, so `MISSING_FACT` still escalates server-side and a packet is never issued for an
   application that cannot be completed. The server records `PACKET` as an `ApplicationStep` with
   the values and document digests — that row, not the extension's report, is the authoritative
   "what we prepared" in the §5.5 trail.

3. **No portal credential exists anywhere.** The student is already logged in. `auth.py`,
   the `tehsil/portal/*` secret prefix, `PortalTaskRole`'s `GetSecretValue`, reauthentication,
   recovery-by-portal-identifier and the browser profiles are retired. `WorkerTaskRole`'s
   `DeleteSecret` on that prefix is re-scoped to the mailbox tokens of
   `2026-09-15-student-owned-mailbox-design.md`, not deleted: erasure still needs it.

4. **Pairing is invisible and bound to one membership.** When a logged-in student loads the
   dashboard and the extension is installed, the page hands the extension a one-time pairing code
   minted for that session; the extension exchanges it for a **device token** bound to the
   `Membership` and to this installation. No QR code, no copy-paste. The token is revocable from the
   dashboard, revoked on logout and on erasure, and never reaches a portal page. On a white-label
   agency domain the handshake runs in a hidden iframe from the platform's canonical origin — the one
   origin the manifest's `externally_connectable` can name in advance — while the extension's API
   calls go to the tenant's own host, so host-to-tenant resolution and RLS run exactly as they do for
   the dashboard. No second tenant-resolution path is introduced.

5. **Per-portal consent is a browser permission, not a platform screen.** The extension declares
   no blanket host access. The first time a student launches a given portal origin, the dock asks
   "Allow filling on `portal.example.edu`?"; that click is the user gesture Chrome requires, the
   browser shows the origin, and the grant is recorded as an `AuditEvent`. The manifest uses
   `optional_host_permissions`; `<all_urls>` is never requested. (Chrome's `activeTab` alone is
   insufficient: it is revoked on navigation, and applications navigate.)

6. **The learn pass moves to the server and reads a value-free snapshot.** When a `PortalForm`
   has no current `FieldMap` for the page it sees, the content script builds a **form schema
   snapshot** — per control: tag, type, name, id, label text, placeholder, options, required flag, a
   stable selector — with every value stripped, and sends it to the server, which runs the one model
   call that maps `"category.key"` vocabulary onto selectors and stores the `FieldMap`. The model key
   leaves the browser for good. `learn.py`'s `PIILeak` guard now runs over the snapshot: a snapshot
   containing any of the student's verified values is refused, because a shared map learned in one
   student's browser must not carry that student. Page text is labelled as data in the prompt, output
   is schema-constrained, tokens capped, and the call sits behind `rate_limited()` per tenant — the
   `CLAUDE.md` LLM baseline, unchanged.

7. **Read-back stays, and is reported, not trusted.** After filling, the content script reads
   each selector's rendered value and compares it with the packet. Mismatches are red rows in the
   dock and a `READ_BACK` step with the mismatch list; a mismatch still escalates `PORTAL_ERROR` and
   is still not retried. The server cannot see the page, so it records the report as the student's
   device's attestation, alongside its own authoritative `PACKET` row.

8. **Challenges are the student's own act.** CAPTCHA, applicant MFA, attestation checkboxes and
   signatures are detected (the `challenge.py` DOM-marker logic, ported) and the dock says "your
   turn"; the extension pauses and resumes filling when the page moves on. No consultant task, no
   resolution service, no preserved session to hand anywhere. `resolve.py` and the
   `PortalForm.resolution_approved` flag are retired. Of the six escalation triggers,
   `UNSOLVED_CHALLENGE`, `APPLICANT_MFA` and `PERSONAL_ATTESTATION` become dock prompts to the
   student who is already there; `MISSING_FACT` stays server-side; `AMBIGUOUS_DECISION` and
   `PORTAL_ERROR` still create a counselor task.

9. **Documents attach through the existing download route.** The packet lists approved
   `DocumentDraft` PDFs by the dashboard-relative `download_document` URL. The extension's service
   worker fetches them on the dashboard host with the student's own session — the route is
   `@login_required`, student-readable and refuses anything not `APPROVED` — and the content script
   attaches the bytes to the named `<input type=file>` with `setFiles`. No presigned URL is added;
   `storage.py`'s "never a public or presigned URL" stands. The `FILL` step records each document's `draft_id` and
   the `sha256` the extension computed over the bytes it attached, closing the §5.5 "uploaded
   documents" gap.

10. **Submission is the student's; confirmation is captured.** The student presses Submit on the
    portal. Where a `PortalForm` carries `confirmation_markers` (URL pattern or page text learned on
    first use), the extension detects the confirmation page; otherwise the student presses *I
    submitted* in the dock. Either way the extension captures the visible tab under the granted host
    permission and reports `SUBMITTED` with the image as evidence, stored under the student's
    document prefix so `_purge_prefix` erases it. `Application.State` moves to `SUBMITTED`
    (student-attested) and to `CONFIRMED` when the mailbox design's signal or a marker-matched
    confirmation page arrives.

11. **One submission mode.** `counselor-submit` and the 48-hours-before-deadline auto-submit are
    removed from §5.1. No server-side submission path exists today and none is planned; keeping the
    clause would promise a safety net the architecture cannot deliver. The deadline safety net is
    §4.5's repeated reminders until acknowledged, a counselor outreach task at T-72h for any
    application still unsubmitted, and an explicit *unsubmitted at deadline* outcome on the roadmap.
    Consultants doing portal work by hand during the concierge MVP is unchanged and remains gated by
    §10 as before; this design neither enables nor forbids it.

12. **The server-side tier is retired by a separate deletion plan**, after the extension passes
    the ported `tests/portals` suite. Until then it stays dormant at `PortalDesiredCount: 0`. The
    `CLAUDE.md` "two browsers" table gets a third row now and loses the portal row then.

## Decisions taken with the owner, 2026-09-15 (evening)

Recorded from the brainstorming session that followed the first draft. Where these differ from the
numbered decisions above, these govern.

1. **Two layers: the Application Kit, then the extension.** For every application the dashboard
   holds an **Application Kit**: the portal's questions in the portal's order with our answers, the
   exact approved document for each requirement, the address to register with, the deadline and the
   status. The kit is readable and copyable on any device with nothing installed and nothing of ours
   touching the portal. The extension *applies* the kit. If the extension cannot act on a portal,
   the student falls back to the kit and nothing is lost. The kit is the product; the extension is
   speed.

2. **Install and pairing are enforced onboarding, not optional extras.** The dashboard detects the
   extension on every load. Without it, the *Start application* button becomes *Install the
   extension* (one click to the store listing, then back), and the kit is shown meanwhile. With it,
   pairing completes silently on the first dashboard load after install and the card header reads
   *Extension connected to <student name>* with a revoke link. The extension refuses to fill while
   unpaired or paired to a different account than the dashboard session, and shows why. Pairing is
   bound to one `Membership`; a heartbeat every dashboard load keeps `last_seen_at` current so the
   dashboard can say "extension not seen since Tuesday".

3. **Strict Next stays: the extension types, the student clicks.** After each page the dock says
   *"Page 2 of 6 filled. Check it, then press Next and I will fill the next page."* When the student
   presses Next the extension detects the new page and fills within a second. Anything unfilled or
   unverified is highlighted on the page and listed in the dock. Pressing Next automatically, under
   label guards, was considered and declined for launch; it may be revisited per portal once that
   portal's steps have run cleanly for real students and a counselor has reviewed them.

4. **Last-page detection changes the wording, never the safety.** Signals: the button label
   (Submit, Send application, Apply, Finish, Einreichen, Absenden), a step counter on its last step,
   a declaration checkbox, a summary of entered data, a fee section, "cannot be changed after
   submission" text, a review/summary/confirm URL, and — after the first student on a portal
   submits — the recorded last page. Two or more signals switch the dock to *"This looks like the
   final page. Review everything; the button below sends your application."* A wrong guess costs a
   wrong sentence, not a submitted application, because the student always presses.

5. **Verification links open by themselves, in the student's browser.** When the connected mailbox
   (content tier, `2026-09-15-student-owned-mailbox-design.md`) yields a portal's verification link,
   the extension opens it in a tab while the student is on the dashboard, the portal verifies, the
   tab closes, the card updates. Default on, per-student switch to off. A six-digit code instead of
   a link is shown in the dock and typed by the extension. Never opened from our servers.

6. **Status moves by itself; uploads take one press.** Mails saying "received", carrying an
   application number, an interview date or a decision update the card with no press. "Please
   upload X" puts a task on the card; pressing it has the extension open the right portal page and
   attach the right approved file, and the student presses the portal's own upload control — for
   the same reason they press Submit.

7. **The extension also reads the portal.** When the student opens their portal account page with
   the extension present, it reads the application status and any document request shown there and
   updates the card. This is the tracking path that needs no mailbox at all, and it is what covers
   portals that send from vendor domains the mail filter has not yet learned.

8. **Reminder ladder, automatic.** 14 days, 7 days, 3 days, 1 day and 6 hours before the deadline,
   on the dashboard and by notification mail. The 1-hour reminder was dropped: a failed upload
   cannot be recovered in an hour. At 3 days a counselor task opens. Every reminder stops the
   moment the card reaches Submitted. Deadlines are stored in the portal's time zone and shown in
   the student's; reminders respect the student's quiet hours. Uses `RoadmapItem.deadline`,
   `DeadlineUrgency` and the notification centre; §4.5's "repeat until acknowledged" is the rule
   it implements.

9. **Portal terms: checked on a sample, recorded per portal, and not a reason to stop.** Terms of
   seven portals were read on 2026-09-15 (table below). None forbids automated tools, scripts,
   extensions or autofill in the applicant's own session. What every one *does* say is that the
   account is personal and credentials may not be shared. So the extension in the student's own
   session is inside every set of terms read; a counselor logging in as the student is the one act
   they prohibit. Each `PortalForm` carries `terms_posture` ∈ `SILENT` | `PERSONAL_ACCOUNT_ONLY` |
   `AGENT_CHANNEL` | `PROHIBITS_AUTOMATION`, set when the portal is first mapped. Only
   `PROHIBITS_AUTOMATION` changes behaviour: that portal is kit-only, because the consequence of
   ignoring an explicit prohibition lands on the student's application, not on us. Default posture
   for an unread portal is `SILENT`, so nothing blocks on a terms read.

   | Portal | Read | Automation / autofill clause | What it does say |
   |---|---|---|---|
   | universityadmissions.se (Sweden, national) | terms and conditions page | none | "You are the only person who may use your personal user account, password and codes" |
   | uni-assist (Germany) | terms and conditions page | none | §1(4): representation by an authorized third party **is allowed** with a signed power of attorney |
   | Studielink (Netherlands, national) | general terms page | none | login details confidential; "misuse" undefined |
   | TUMonline (TUM) | IT use policy §2, §4, §8 | none | §4(3a) sharing credentials prohibited; §4(3c) user answers for every action under their login |
   | Campus France (campusfrance.org) | terms of use | none | covers the website only; the *Études en France* platform's own CGU was unreachable (certificate error) — unread |
   | UCAS | agent-portal terms of service | none | a **sanctioned agent channel** exists, with its own accounts and terms; applicant terms PDF not readable by the tools used — unread |
   | DreamApply (vendor) | — | — | applicant terms are set per institution; vendor terms page returned 404 — unread |

10. **B2B: counselors prepare; whether they also fill is the agency's call, per portal.** The
    counselor pairing that the first draft listed as "deliberately not built" is built, as a
    tenant-level switch the agency owner turns on with a recorded acknowledgment. The default under
    the switch is *counselor prepares, student applies*: the counselor builds and reviews the kit,
    the student's own extension applies it. A counselor filling in the student's account is allowed
    only where the agency owner has additionally accepted that portal's `terms_posture`, since the
    sample shows credential sharing is exactly what portals prohibit; where a sanctioned route
    exists (uni-assist's power of attorney, UCAS's agent portal) the dashboard points to it. Every
    counselor action is recorded with the counselor as actor and the student as subject.

11. **Mail providers: Google and Microsoft both, from the pilot.** The pilot runs under Google's
    100-user testing cap; the restricted-scope verification and yearly assessment are budgeted before
    the 101st Gmail user. Details in the mailbox spec's "Decisions taken with the owner".

13. **Registration is filled like any other form, and the student presses "Create account".**
    The owner's flow opens with the extension signing the student up on the portal. That is the same
    act as filling an application page: the extension types the email, the generated password and the
    name fields from the kit, and the student presses the portal's own create-account button. Chrome's
    own password manager offers to save the password — we never store it, never read it back and never
    hold a portal credential (decision 3 stands). A `PortalForm` therefore carries a second field map,
    `signup_map`, learned the same way as the application one and shared the same way. Portals whose
    sign-up needs a phone number, a national ID or an emailed code are ordinary "your turn" prompts.

12. **Browsers: the Chromium family at launch; Firefox and Safari later.** Chrome, Edge, Brave, Opera,
    Vivaldi and Arc install the same extension from the same store, and Edge ships with every Windows
    machine. When the dashboard detects any other browser, or a phone, it shows the Application Kit
    and the line **"For one-click filling, open this in Chrome or Edge."** The dashboard counts how
    often that line is shown, per browser; Firefox is ported when the count is noticeable (same
    extension format, its own store, days of work), Safari only if Mac users who decline Chrome are a
    real share (Apple wrapper app and developer account). The onboarding also says early that
    submission day needs a laptop, so no one learns it at a deadline.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ 1. Dashboard (tenant host)                                   │
│    discovery · pack · documents (P1-14 approved) · roadmap    │
│    [Launch & Autofill TUM]  ──►  server mints Fill Packet     │
│                                  PACKET step recorded         │
└───────────────┬──────────────────────────────────────────────┘
                │ pairing (once, invisible): one-time code ► device token
                ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. Extension (Manifest V3, Chromium)                          │
│    service worker: fetch packet, fetch PDFs on dashboard host │
│    content script (portal origin, after consent):             │
│       snapshot ► server learn ► FieldMap                      │
│       fill/type/select/setFiles · already_correct · read-back │
│       challenge detection ► "your turn"                        │
│    side-panel dock: progress bar, red rows, your-turn prompts  │
└───────────────┬──────────────────────────────────────────────┘
                │ events: FILL · READ_BACK · CHALLENGE · SUBMITTED
                ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. Handshake                                                  │
│    student presses Submit on the portal                        │
│    extension captures confirmation ► SUBMITTED ► CONFIRMED     │
│    roadmap card moves; counselor queue sees mismatches only    │
└──────────────────────────────────────────────────────────────┘
```

### The Fill Packet

```
FillPacket
  application_id, portal_form_id, field_map_version, form_url
  values:     { selector -> str }          # verified facts only, profile.py vocabulary
  documents:  [ { selector, filename, download_path, sha256 } ]
  markers:    confirmation_markers | null
  issued_at, expires_at (≤ 2 h), min_extension_version
```

Held by the extension in session-only storage (`chrome.storage.session`, memory, cleared when the
browser closes) — never `chrome.storage.local`, never a portal page's storage. A packet past
`expires_at` is refetched, so a student who leaves the tab open overnight fills from current facts.

### The Application Kit — the same data, rendered for a human

The kit and the packet are one server-side object with two renderings, so they can never disagree.
`packets.py::build_kit(application)` returns the ordered questions, answers, documents, registration
address, deadline and status; `mint_packet` is that object plus selectors, an expiry and a signature,
and the kit view drops the selectors. The kit renders as an ordinary dashboard page — readable,
copyable field by field, printable, with each document's download link — and is reachable on any
device with no extension, no host permission and nothing of ours touching the portal. Where the
packet cannot be minted (no field map yet, `PROHIBITS_AUTOMATION`, a non-Chromium browser) the kit
is still built: it needs `programme requirements + verified facts + approved documents`, never a
`FieldMap`. With a map, the kit's answers are in the portal's own order and carry its labels; without
one, they are every verified answer we hold, in a stable order, beside the programme's own REQUIRED
statements as a checklist. Inventing portal questions we have not mapped would be the one dishonest
thing a kit could do. That asymmetry is the point — the kit degrades, the packet refuses.

Not every step is a form. An award the student reaches by being nominated (the institution or the
home government puts them forward) is an **`EMAIL` step** in the kit — whom to write to, by when,
and a student-approved draft sent from their own client. Kit-only by nature: there is no portal,
so no packet. Defined in the funding engine spec, 2026-09-22 design §9.2 (added 2026-09-25).

The packet carries each document's `draft_id`, filename and download path, not a digest: computing one
server-side means reading the artefact out of object storage on every mint, and the extension holds
the bytes anyway, so it reports the `sha256` it fetched in the `FILL` event and the server stores that.

**It also carries no `selector` for a document, and that is a gap rather than a decision.** The shape
above lists one, and nothing in today's data model can supply it: a `FieldMap` entry is a
`profile_field` and an action, and the learn pass has never been asked which control on the page is a
file input. So the packet names the document and not where it goes, and the extension cannot call
`setFiles` on the strength of the packet alone. **Plan 3 supplies it**, by teaching the learn pass to
map upload controls the way it maps text fields; until then the kit's document list is a human
instruction, which is what the kit is for. Recorded here because the alternative is rediscovering it
against a live portal at a deadline.

The filename is derived through `resolve_variant`, never from `DocumentDraft.render_variant` directly.
Production drafts leave that field blank and the worker writes the object under the resolved variant,
so reading the stored field yields `cv-.pdf` for an object called `cv-standard.pdf` — a link that
404s, for every kit, silently. Measured 2026-09-15; `apps/documents/api.py` had already solved it and
says so in its own docstring.

### Extension API (tenant host, device-token authenticated)

| Route | Purpose |
|---|---|
| `POST /ext/pair` | one-time code → device token; records `ExtensionPairing` |
| `GET /ext/applications/{id}/packet` | mint or return the current packet (runs the three pre-checks) |
| `POST /ext/portal-forms/{id}/snapshot` | value-free form schema → learn → `FieldMap` |
| `POST /ext/applications/{id}/events` | `FILL`, `READ_BACK`, `CHALLENGE`, `SUBMITTED` (+ image) |
| `GET /ext/actions` | pending device actions for this student: verification links to open, codes to type, portal pages to read (owner decisions 5, 6, 7) |
| `POST /ext/actions/{id}/result` | that action's outcome; closes it or leaves it for the student |
| `POST /ext/applications/{id}/status` | a portal account page the student opened, parsed: state, application number, document requests |
| `DELETE /ext/pair` | revoke this installation |

The kit itself is not an extension route: it is a dashboard page (`/applications/{id}/kit`) under the
ordinary session login, because its whole purpose is to work with no extension present.

### What plan 3 must not drop: the extension verifies the map against the page

**The extension must refuse to type a value into a control it cannot recognise.** Before filling,
the content script resolves every selector in the packet and checks, for each one, that it names a
control that exists, is visible, and whose accessible name — label, `aria-label`, `placeholder`,
`name` — plausibly matches the profile field being typed into it. A selector that resolves to
nothing, to a hidden control, or to one whose name matches nothing about the field is highlighted
in the dock and left unfilled, not typed into.

**This is a security requirement, not polish, and it is the ONLY place the check can live.** A
`FieldMap` learned from a snapshot is a claim by a client: the student's browser described the form
and the server took its word, because the server has no page to compare against. Read-back cannot
catch a bad claim either — it reads back the selector it typed into and finds the value sitting
there, so a wrong-but-consistent map verifies clean. The extension is the only party that sees the
real page, which makes it the only party that can tell a map from a lie.

The residual it closes, measured against the design as plan 2 shipped it: one student can craft a
snapshot naming selectors of their choosing, and every later student **in the same agency** filling
that form has their verified values typed where the first student chose. The ceiling is sabotage
and misplacement — a date of birth landing in a free-text box the university reads — never
exfiltration: the attacker never receives a value, cannot reach another tenant (plan 2's
`FieldMap.learned_by_tenant` closed that), and cannot cause a click. What makes it worth closing
anyway is that "check the page before you press" does not survive a subtle swap, and a selector
pointing at a hidden control is invisible to the student entirely.

Two things plan 2 deliberately did NOT do, so plan 3 does not assume they exist: there is no
server-side selector check (the server has no ground truth to check against), and there is no
agreement rule requiring N snapshots to match (it needs volume the pilot will not have and it
delays every new portal). What plan 2 does provide is attribution — a
`portal.field_map_learned` `AuditEvent` naming the membership whose browser sent each snapshot.

### What plan 2 must not drop

`phased requirements.md` §5.2 requires a consultant to review the first application prepared on each
new portal, and the retiring server tier honours it: `services.py::prepare_application` ends with
`request_first_portal_review(application)`. **`mint_packet` does not call it**, deliberately — the
packet has no caller until plan 2 adds one, so the review task would fire for nobody. It is written
here rather than in a code comment because the failure mode is silent: as the server tier retires,
that review disappears with it and no test goes red. Plan 2 owns placing it, and
`PortalForm.review_required` is the flag it must consult.

Every route resolves the tenant from the host as the dashboard does and runs inside
`tenant_scope()` with `set_local_tenant()`; the device token only identifies the membership. Tested
through `rls_enforced_orm`.

## Data model

**Every new field on a student-reachable model must be classified in `apps/audit/redaction.py`**
as `REDACT`, `KEEP` or `UNDECIDED`, in the same change that adds it.
`tests/audit/test_redaction_classification.py` enforces it, and a miss does not fail politely: an
unclassified column left the whole suite at 2 failures and 23 errors, every one of the errors in a
file that passes on its own (measured 2026-09-15 on `Application.deadline`). Platform-shared tables —
`PortalForm`, `FieldMap` — are not student-reachable and need no entry, which is exactly the
distinction that makes the miss easy. `ExtensionPairing`, `DeviceAction`, `MailSignal` and
`MailboxConnection` all land on the student-reachable side.

- `ExtensionPairing` (tenant-scoped): `membership` FK, `token_hash`, `installation_id`,
  `created_at`, `last_seen_at`, `revoked_at`. Cascades with the membership; erasure revokes.
- `PortalForm.confirmation_markers` (JSON, nullable): learned on first confirmed submission, shared
  like the `FieldMap` it sits beside, PII-guarded the same way.
- `ApplicationStep.kind` gains `PACKET`, `CHALLENGE`, `SUBMITTED`; `FILL`, `READ_BACK`,
  `ESCALATION` and `RECOVERY` keep their meaning.
- `Application.State`: no new members. `SUBMITTED` and `CONFIRMED` finally get writers.
- `PortalForm.signup_map` (FK to a `FieldMap`, nullable): the sign-up form's map (owner decision 13).
- `PortalForm.final_page_markers` (JSON, nullable): the signals of owner decision 4, learned from the
  first student who submits on that portal, shared like every other `PortalForm` field.
- `PortalForm.terms_posture` (char, default `SILENT`): `SILENT` | `PERSONAL_ACCOUNT_ONLY` |
  `AGENT_CHANNEL` | `PROHIBITS_AUTOMATION`, with `terms_url` and `terms_read_on`. Only
  `PROHIBITS_AUTOMATION` changes behaviour: `mint_packet` refuses and the dashboard serves the kit.
- `PortalForm.sender_domains` (JSON list): the addresses this portal really mails from, learned from
  the first confirmed message (mailbox spec, owner decision 4).
- `DeviceAction` (tenant-scoped): `membership` FK, `application` FK (nullable), `kind`
  (`OPEN_VERIFICATION_URL` | `TYPE_CODE` | `READ_PORTAL_STATUS` | `OPEN_UPLOAD_PAGE`), `payload`
  (JSON — a URL or code, short-lived), `created_at`, `delivered_at`, `completed_at`, `expires_at`.
  Erasure cascades with the membership; a completed action's payload is cleared, since a verification
  URL is a bearer credential for the student's portal account.
- `Tenant.counselor_fill_enabled` (bool, default False) and `TenantPortalAcknowledgement`
  (`tenant`, `portal_form`, `acknowledged_by`, `acknowledged_at`): owner decision 10's switch. Absent
  either, a counselor may build and review a kit but the extension refuses to fill on their pairing.
- `Application.deadline` (datetime, nullable) and `Application.deadline_timezone` (IANA name): the
  first deadline columns in this codebase. `escalation.py` records that an application carries none
  today and the 2026-09-15 discovery audit records that no catalog table holds one either, so the kit
  has nothing to show and the reminder ladder nothing to read until this exists. Nullable, because
  most applications enter the pipeline before anyone has read a date off the programme's page.
- `ApplicationStep.kind` gains `PACKET`, `CHALLENGE`, `SUBMITTED`, `SIGNUP`, `STATUS`, `VERIFY`.
- `AuditEvent.actor_kind`: the extension acts as the student's tool; events carry
  `actor=<student>` with `channel="extension"` in the detail, not a synthetic actor. Under counselor
  mode the actor is the counselor and the subject is the student.

## Security model — the third row in the two-browsers table

| | `BrowserTaskDefinition` (research) | `PortalTaskDefinition` (retiring) | Extension (this design) |
|---|---|---|---|
| Where it runs | Fargate, platform | EC2, platform | the student's browser |
| Credentials in reach | none | DB password, model key, portal logins | **a device token for one membership** |
| Security rests on | nothing to steal | the renderer sandbox holds | **nothing of ours is there to steal; the portal is the student's own session** |

What the hostile actors can and cannot do:

- **A hostile portal page** controls the DOM the content script reads. It can make read-back lie
  about its own form to its own applicant — the same thing it could do to the student typing by
  hand. It cannot read extension state (isolated world), cannot call the extension API, and cannot
  reach the dashboard host: the packet and the PDFs travel service-worker → content script, never
  through page-accessible storage. Text it puts in labels reaches the server's learn call as
  untrusted data, under the reference prompt pattern; that is prompt injection against a call whose
  only output is a selector map validated against the snapshot's own selectors.
- **Malware on the student's machine** already owns their portal session cookie; the device token
  adds a way to read that student's own packets and post events for that student's own applications.
  Tokens are per-installation, revocable, and every event is one student's, tenant-scoped.
- **A compromised Web Store account** is the supply-chain risk this design newly carries. MV3
  forbids remote code, so behaviour is fixed at publish; the `FieldMap` is data, and the allowlist
  means a stored map cannot make the extension click. Publishing needs the same two-person rule as
  a production deploy; the plan pins it.
- **Tenant isolation** is unchanged in shape: the extension speaks to the tenant host, and every
  row it touches is tenant-scoped under RLS. No cross-tenant read is introduced; the shared
  `FieldMap`/`PortalForm` rows were already platform data with no PII.

## Terms: the three nouns

§10 names *automated access*, *delegated form completion* and *submission*. Against the retiring
design all three applied: the platform logged in with its own credentials from its own IP, completed
forms as an agent, and (in `counselor-submit`) submitted. Against this design: there is no platform
access to the portal at all — no login, no IP, no session of ours; form completion happens in the
applicant's own authenticated session, initiated by the applicant, on the applicant's device, with
values the applicant approved, which is the category browser autofill and password managers occupy;
and submission is the applicant's own click. What remains for §10 is portal language that forbids
"automated tools" broadly enough to catch autofill in the user's own session, plus file attachment.
That is a materially narrower question, and the design records it as such rather than as settled.
The `phased requirements.md` §3.4 rule on fingerprint evasion and anti-bot bypass is untouched: the
student's own browser needs no evasion, which was the whole point of the 2026-08-25 CAPTCHA reasoning
("IP reputation, behaviour and session history far more than fingerprint").

## What changes in code

| Module | Fate |
|---|---|
| `models.py` (`PortalForm`, `FieldMap`, `Application`, `ApplicationStep`) | keep; add `confirmation_markers`, new step kinds |
| `session.py` (`FILL_METHODS`, `is_fillable`) | keep; add `setFiles`; the JS content script mirrors it and a test asserts the two sets are equal |
| `profile.py` | keep unchanged |
| `services.py` steps 1–3 | keep, become `packets.py::mint_packet` |
| `fill.py::already_correct`, `read_back` | port to the content script; Python versions stay for packet-side unit tests |
| `escalation.py` | keep; three triggers reroute to the dock instead of a consultant task |
| `recovery.py` FILL audit write | keep, fed by the events route |
| `challenge.py` | port DOM markers to the content script |
| `learn.py` | keep the PII guard and rate limit; replace Stagehand `observe()` with the snapshot mapper |
| `reporting.py` | keep |
| `auth.py`, `profiles.py`, `engine.py`, `resolve.py`, `dispatch.py`, `worker.py`, `queue.py`, `run_portal_worker` | retire (deletion plan) |
| `infra/template.yaml` Portal* resources, `scripts/validate_portal_sandbox.py` | retire (deletion plan); re-scope `WorkerTaskRole` `DeleteSecret` to `tehsil/mailbox/*` |
| new `apps/portals/ext_api.py`, `packets.py` (`build_kit` + `mint_packet`), `pairing.py`, `actions.py` | server side of the extension |
| new `apps/portals/views.py` kit page + `templates/portals/kit.html` | the no-extension layer |
| `apps/concierge` reminder command (`send_deadline_reminders`) + an EventBridge rule beside `EuropassCanaryRule` | owner decision 8's ladder |
| new `extension/` (TypeScript, MV3) | service worker, content script, side-panel dock |

The `stagehand` dependency leaves `pyproject.toml` with the deletion plan.

## Testing

- **Allowlist parity.** One test loads the content script's action switch and asserts its method
  set equals `FILL_METHODS | {"setFiles"}`; a second asserts no code path in the content script
  dispatches `click` (static scan of the built bundle for `.click(` and `MouseEvent`).
- **End to end.** Playwright (the `patchright` already pinned) launches Chromium with the unpacked
  extension against `tests/portals/fixtures/*.html` served locally: pair, mint, fill, attach a PDF,
  read back, detect a fixture CAPTCHA, detect a confirmation page, post events. Runs in the
  `portal-sandbox` CI job's slot.
- **Server side.** Packet minting refuses without a field map, escalates `MISSING_FACT`, expires;
  snapshot learn refuses a snapshot containing a verified value (`PIILeak`); events for another
  student's application are 404 under `rls_enforced_orm`; revocation invalidates the token.
- **Terms of the trail.** A test asserts every application that reaches `SUBMITTED` has a `PACKET`,
  at least one `FILL`, a `READ_BACK` and a `SUBMITTED` step in sequence.
- **Kit without an extension.** A `PROHIBITS_AUTOMATION` portal and a portal with no `FieldMap` both
  refuse a packet and still render a kit carrying every question, answer and document.
- **Actions.** A `DeviceAction` is delivered once, its payload cleared on completion, and expires;
  another student's action is 404 under `rls_enforced_orm`.
- **Counselor mode.** Without `counselor_fill_enabled` plus the portal acknowledgement, a counselor
  pairing is refused a packet and offered the kit.
- **Reminders.** A fixture application at each rung fires exactly one reminder; a submitted
  application fires none; the 3-day rung also opens a counselor task.
- **Negative control.** A packet whose values are altered in transit fails read-back against the
  fixture — proving read-back compares to the packet, not to what was typed.

## Cost

One model call per new form version (the learn pass), server-side, rate-limited per tenant; replay
fills make zero model calls, as today. No EC2 instance, no Secrets Manager entries per student, no
Xvfb, no browser image in the `portal` Docker stage. The recurring cost that replaces them is Web
Store publishing and a Playwright job in CI.

## Deliberately not built

- **Firefox and Safari** — owner decision 12 above: later, on a measured trigger; the dashboard shows
  "For one-click filling, open this in Chrome or Edge" and the kit meanwhile.
- **Mobile.** No extensions on mobile browsers; the dashboard shows "open on a computer" and the
  application card stays actionable.
- **Counselor pairing** was listed here in the first draft; it is now decision 10 above (built, as an
  agency-level switch defaulting to *counselor prepares, student applies*).
- **Clicking Next, Create account or Submit.** Ever. If a portal's flow cannot be completed without
  the extension clicking, the extension fills what it can and the dock tells the student what to press.
- **Payment forms.** §5.3 is unchanged; card fields are never in a packet.
- **A CAPTCHA resolution service.** The student is present. The §2 and §5.1 clauses about a
  service are removed rather than left dormant.
- **Background fill.** Nothing runs when the student is not on the tab.

## Risks and ceilings

- **Custom upload widgets** (drag-and-drop, direct-to-S3 uploaders) do not expose a native file
  input. `setFiles` handles the native case only; the rest becomes a dock instruction ("attach
  `cv.pdf` here") with the file offered from the dock. Measure on the first ten real portals before
  deciding whether a `drop`-event path is worth its click-adjacent risk.
- **Framework-controlled inputs** ignore a bare value assignment. The content script uses the
  native value setter plus `input`/`change` events — the standard technique — and read-back catches
  the cases where it is not enough.
- **Browser autofill** may race the extension on the same fields; the dock disables nothing in the
  browser, so read-back is the arbiter.
- **Version drift.** The packet carries `min_extension_version`; an older extension refuses the
  packet and asks for an update rather than filling with stale semantics.
- **Store review latency** makes a hotfix a days-long affair. The `FieldMap` being server data is
  the mitigation: a portal change is a re-learn, not a release.

## Open decisions for the owner

1. ~~Retire `counselor-submit` and the 48-hour clause~~ — **decided 2026-09-15: retired.** The
   student is responsible for the acts that carry their name; the platform removes everything around
   them.
2. ~~Confirmation evidence~~ — **decided 2026-09-15: capture automatically**; the confirmation mail
   and the portal status read (decision 7) corroborate it.
3. **Deletion timing**: delete the server tier once the extension's end-to-end suite is green on
   the fixtures (recommended), or after the first real portal succeeds?
