# The student dashboard: one place for what to do next

Spec A of two. Spec B (extension v2: start from the board, answers, "add another", autocomplete,
uploads) follows it, because B's buttons live on A's pages. Branch `claude/student-dashboard`,
stacked on `claude/mailbox-graph-push` (PR #170), which is stacked on PR #168: the board reads the
mailbox signals those two PRs record.

## What governs

| Source | What it settles |
|---|---|
| `idea_v2.md:64` | "a centralized dashboard and notification center for missing documents, application changes, interview invitations, and application status" |
| `phased requirements.md` P1-7, P1-9, the 2026-09-15 eligibility-fields amendment, §5.6 | what the dashboard must show; a requested document is uploaded once and attached after its intended application is verified |
| Owner, 2026-10-03 (`owner-decisions` memory, written into `phased requirements.md` on `claude/requirements-owner-2026-10-03`) | the first dashboard is **plain unstyled HTML for testing**; designers do the visual design later. Students pay every application fee themselves. No interview preparation; invitation reminders stay |
| Owner, 2026-10-03/04, this design session | real login kept later; every student-facing page; a kanban board with one card per application; "Needs you now" on top; the recommendation pack grouped **under the funding**; missing documents shown on the dashboard and fed by mail; one click on **Start application** opens the portal and starts filling (spec B) |
| `docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md` | the kit, the packet, pairing. Where it says the extension never clicks, spec B amends it |
| Owner, 2026-10-04, spec review | the AI recognises reliably **that** a decision arrived and the board shows "Decision available"; the outcome is **recorded automatically** when the mail states it or when the student opens the portal (§4); programme pages **show the official source link** (amends P1-7.1); **counsellors work on each student's board with full rights**, not read-only |
| Owner, 2026-10-04, plan review | logout keeps the extension paired; disconnect lives in Settings; erasure revokes (`request_deletion` already revokes every pairing). A counsellor sees a read-only board while the student's deletion request is open. Interview dates are extracted. An open award (HOLDER, COUNTRY, GLOBAL scope) lists every programme the student could use it for. Accept on an offer of another programme creates a new card. "We operate in Azerbaijan; you can send to TypeSafe (using OpenRouter)": student mail may reach Jev, with identifiers stripped (`docs/legal/2026-09-provider-terms.md`), and **one** Jev reading that abstains decides a mail (§4). Uploads reach the extension through a promoted copy and a device route (§6), after a magic-byte type allowlist and an active-content check in the isolated OCR function; a PDF is never rewritten; an EICAR first-deploy check (§6, "Upload safety") |
| Agreed with the consent session (tehsil-agent-f7), 2026-10-03 | this spec owns `templates/base.html`, `templates/registration/login.html`, `templates/student/*`, `/accounts/login/`, `/accounts/logout/`. f7 owns `apps/privacy/templates/privacy/*` and adds `/accounts/logout/` to its `_ACCEPTANCE_EXEMPT_PREFIXES` |

Not in scope: owner and platform pages; counsellor pages other than the student board (§4a); visual design; Gmail; the `+` address delivery
test (it needs the platform to send mail, and no sending domain exists — owner, 2026-09-19).

## 1. Foundation

- **Root `templates/`.** Django's own lookup and what f7 expects. It holds `base.html`,
  `403.html`, `400.html`, `registration/login.html` and `student/*`. No stylesheet. The two
  context processors that exist (`brand_primary_color`, `viewer_role`) stay available but nothing
  styles with them yet.
- **`base.html`:** a skip link to `<main id="main">`, the agency's name, a nav (Home, Programmes &
  funding, Documents, Messages, Settings), a POST logout form, and Django messages rendered with
  `role="status"` (and errors with `role="alert"`). Students see no `/counselor/` or `/owner/`
  links (`tests/concierge/test_roadmap.py` pins this).
- **Login:** Django's `LoginView` at `/accounts/login/` and `LogoutView` (POST only) at
  `/accounts/logout/`, `LOGIN_URL` set to it, and the same limiter the JSON login uses
  (`apps/documents/api.py::auth_login`: 10 attempts per 900 s keyed on a hash of the username),
  applied by wrapping the view. A failed attempt says only "Wrong username or password."
  **Logout keeps the extension paired** (owner, 2026-10-04): pairing needs a toolbar click today
  (`docs/superpowers/plans/2026-09-17-glass-box-extension.md` superseded glass-box decision 4's
  invisible pairing), so revoking at logout would force a re-pair after every login and break
  one-click Start application. Disconnect lives in Settings, Extension; erasure revokes
  (`request_deletion` already revokes every pairing). A deletion-locked student can still log out.
- **`/`** stops answering the bare word "Tehsil": an authenticated student is redirected to
  `/student/`, anyone else to `/accounts/login/`. The Outlook callback, which ends on `/`, then
  lands on the board.
- **`manage.py create_student`** (`--agency`, `--host`, `--username`, password prompted, never an
  argument): an operator tool for testing until f7's self-signup exists. It creates the `User`, the
  `STUDENT` `Membership`, and nothing else.
- **The 42 `frontend` tests un-skip** the moment `templates/` exists (`tests/conftest.py:515-531`).
  Kept, because they test behaviour the plain pages still owe: errors with `role="alert"`, a typed
  value kept after an error, the student nav, the exact 403/400 copy
  (`tests/acceptance/test_denied_page.py`), "Official source"/"Last checked"/"Total funding gap"
  on the pack. Retired, because they pin the deleted visual layer: the htmx vendor file and
  `htmx-config` meta, `--brand-primary`, the component partial file names, the 5-second polling
  attribute. Each retired test is deleted in the same commit as the reason, named in the message.
- **Static files:** CI runs `collectstatic` under production settings (`CompressedManifest`
  raises on any `{% static %}` missing from the manifest, which no test can see — CLAUDE.md
  "Static files").

## 2. Information architecture

Every page answers "what do I need to do now?" first.

| Page | URL | Holds |
|---|---|---|
| **Home** | `/student/` | "Needs you now" (§3), then the board (§4) |
| **Programmes & funding** | `/student/recommendation/` | the pack and the pool, grouped under the funding (§5) |
| **Documents** | `/student/documents/` | the document-by-application table (§6) |
| **Messages** | `/student/messages/` | recognised mail and counsellor messages, per application |
| **Settings** | `/student/settings/` | profile completion (link to the profile wizard), mailbox, extension, account |
| Profile wizard | `/student/profile/` | the existing one-question-per-page wizard |
| Gap interview | `/student/gap-interview/` | the existing page, moved onto `base.html` |
| Kit | `/applications/<id>/kit` | the existing Application Kit: answers, requirements, documents |
| Mailbox | `/student/settings/mailbox/` | connections, connect Outlook (tier, kind), revoke, downgrade, learned senders to confirm |
| Extension | `/student/settings/extension/` | paired devices, last seen, disconnect, how to pair |
| Account | `/student/settings/account/` | request deletion; while pending, the waiting page with Restore |

The mailbox views keep answering JSON to JSON callers and also accept a plain form post, which
redirects back to the mailbox page with a message. The Outlook callback redirects there too.

## 3. Needs you now

One list across everything, sorted by deadline (undated items last, newest first), each with one
button. It replaces "notifications" as a separate list; a `Notification` still exists underneath
and **Acknowledge** still writes `acknowledged_at`.

| Item | Source | Button |
|---|---|---|
| Document missing for an application | §6 | **Submit document** |
| Answer missing for an application | `kit.questions` with `missing=True` | **Answer** (the gap interview, or the profile wizard) |
| An institution wrote (decision, request, fee, interview) | `MailSignal` label cards | **Open message** |
| Interview invitation | `INTERVIEW` card with `interview_at` | **Open message**; the item shows the interview's date and sorts by it |
| An offer of a place on another programme | a `DECISION` signal with `offered_programme` | "<University> offers you a place in <programme>": **Accept** / **Ignore** (§4) |
| Verify your email address | `VERIFICATION` card | **Open message** (or the extension opens it) |
| Application not started, deadline near | `Application` in the first column, deadline within 14 days | **Start application** |
| Fee due | the pack's application fee, application not yet submitted | **Open portal** (the student pays there) |
| Draft to approve | `DocumentDraft` awaiting approval | **Review** |
| Mailbox or extension needs you | lost grant, stale inbox, unpaired extension | **Reconnect** / **Pair** |
| Confirmation overdue | the watchdog's urgent alert | **Open portal** |

## 4. The board

**One card per application**: a programme application, or a scholarship with its own application.
Funding that comes with the admission (a university scholarship, an Erasmus Mundus place) is shown
on the programme's card, not as its own card. Cards linked by funding say so both ways:
"funds: TUM M.Sc." on the DAAD card, "needs: DAAD" on the TUM card.

**Columns**, from `Application.state` plus one new field:

| Column | States |
|---|---|
| To start | `PREPARING` with no fill yet |
| In progress | `PREPARING` after a fill started, `READY_TO_SUBMIT`, any `BLOCKED_*` |
| Submitted | `SUBMITTED` |
| Confirmed | `CONFIRMED` |
| Decision | `decision_available_at` set, or `outcome` set |

**Decision available** (owner, 2026-10-04: the AI should reliably know whether a mail is a
decision and the dashboard shows that one is available). New `Application.decision_available_at`,
set when a **trusted** mail arrives for the application and Jev's reading says it is a decision
(below, §8); the card moves to Decision and reads "Decision available — open the email or your
portal to read it". An untrusted one (an unauthenticated sender) raises the item but moves no card:
a forged "decision" must not move a student's application.

**The decision reading: one Jev reading that abstains** (owner, 2026-10-04, replacing the earlier
"two readings if the gate fails" fallback). `apps/mailbox/decision_reader.py::read_decision` asks
TypeSafe's Jev through OpenRouter (decision name `mail_decision`, `record=False`), designed to the
practices the engine-eval work measured (`docs/superpowers/research/2026-09-23-jev-question-engineering.md`):

- **State** with descriptive keys and nothing else: `{"email": {"from_domain", "subject", "body"},
  "application": {"programme", "university", "funding"}}`. Before the call, code strips the
  student's own name words, every email address and every phone number (a test proves a seeded
  name and address never reach the request payload).
- **One request of atomic questions**: a Noul "Does `email` give the final result of the
  application to `application.programme`?" whose false criteria name acknowledgement, release-date
  notice, document request, interview invitation and stage result; a Choice over `ADMITTED`,
  `ADMITTED_CONDITIONAL`, `WAITLISTED`, `REJECTED`, `NOT_STATED` with a literal definition per
  option; one gate Noul per outcome option (per-option gates measured to raise precision); the same
  Choice and gates for `application.funding` when the card has a funding; a Noul "Does `email`
  offer a place on a programme other than `application.programme`?". Forward option order only
  (no material order bias was measured), the best single wording (averaging wordings added nothing),
  English questions over the original-language email (translation gained nothing).
- **Recording rule**: the decision Noul at or above its bar, and the Choice's top option equal to
  the option whose gate Noul clears that gate's bar, records that outcome; anything else abstains
  (a decision is *available* only if the decision Noul cleared its bar; otherwise the mail is just
  an item). Bars are learned per question with `engine_eval.score` (Learn-then-Test at error cost:
  anything that can produce a wrong ADMITTED or REJECTED at ≤ 1/500, the rest ≤ 1/100) and stored
  with their measurement date; until learned every bar is a conservative 0.95 **and the card asks**
  ("Decision available — the email reads: Admitted. Confirm it below.") instead of recording.
- **Free text stays with the classifier** (Jev generates no text): the document's name, its due
  date, an interview's time, offer conditions and an offered programme's name come from the
  existing OpenAI classifier call, and each quote is kept only when code finds it in the email.
- **Jev unavailable** (not configured, failed, budget, oversize state, rate limit): abstain, and a
  card with a decision-labelled mail reads "Decision available — confirm". Never a fall back to an
  unmeasured reader for the outcome.
- **Measured**: `manage.py decision_eval` over `GoldItem` rows of kind `decision_mail` (labelled in
  `/platform/gold/`), seeded from synthetic letters for every hard case in English, German,
  Swedish, Dutch and Turkish plus university templates as they are collected; it reports per
  question precision and coverage at the bar, the zero-error rows a round needs (299 for ≤ 1/100,
  1,497 for ≤ 1/500), compares two wordings per question (Gate 12) and the spend at Jev's
  $0.042 per million tokens. `live`-marked; never runs by default.

**New: `Application.outcome`** (`ADMITTED`, `ADMITTED_CONDITIONAL`, `WAITLISTED`, `REJECTED`,
`WITHDRAWN`, blank), with
`outcome_recorded_at`, `outcome_source` (`MAIL`, `PORTAL`, `PERSON`) and `outcome_evidence` (the
`MailSignal` or the portal reading it came from; never the letter's text). **Recorded
automatically** (owner, 2026-10-04) from either source:

- **Mail.** On the content tier, a trusted mail whose Jev reading clears its bars sets the
  outcome. The classifier's verdict carries the quotes: `outcome_conditions` (short items copied
  from the email, each becoming a missing item on the card when the reading is
  `ADMITTED_CONDITIONAL`, e.g. "final transcript", "B2 certificate") and `offered_programme`
  (≤ 120 characters, the name of a different programme the letter offers a place on, used when
  Jev says an offer is there), schema-constrained. The outcome is blank when the mail only says a
  decision is available ("log in to see your decision"), which is the common case, and then only
  `decision_available_at` is set. The owner expects outcomes to read
  reliably, because admitted, waitlisted and rejected letters differ a lot (2026-10-04); the cases
  the gate set must cover are the ones that do not: conditional admission, two decisions in one
  letter (admitted, scholarship declined: the funding outcome goes on the funding's card), an offer
  for a different programme (below), a stage result ("passed pre-selection, interview on …", which records nothing), and reserve lists
  under other names.
- **An offer for a different programme** (owner, 2026-10-04) creates a new card, on the student's
  word. What the letter says about the programme applied for is an ordinary reading of that card's
  outcome (usually REJECTED). The offer itself waits on the signal and Needs you now reads "<University>
  offers you a place in <programme>" with **Accept** and **Ignore**. Accept creates a new
  `Application` for that programme through the same add-to-applications path, with the original
  application's portal when the offer comes from that portal's institution, else portal-less with
  the counsellor task; it records the original card's outcome as REJECTED only if the letter said
  so (as the person who accepted). Ignore dismisses the item. The new card has no pack candidate,
  so it carries the letter's name for the programme.
- **Portal.** When the student opens the portal with the extension paired, the extension reads the
  application's status text (the `READ_PORTAL_STATUS` action, declared and never built; spec B),
  and the server reads it with the same questions.

The card then reads "Admitted — from TUM's email, 3 Oct" with the source, and **"Not right?"**
lets the student or counsellor correct it (`outcome_source=PERSON`, audited); a person's entry is
never overwritten by a later automatic reading. Because an admission outcome is the one fact this
platform has no record of anywhere (CLAUDE.md "Derived data") and a misread one tells a family the
wrong thing, automatic recording rests on two guards: **trusted mail only** (an unauthenticated sender
suggests, never records), and **one Jev reading that abstains** at bars learned to **zero wrong
outcomes** at the round's target (abstaining is allowed, a wrong `ADMITTED` or `REJECTED` is not),
the card asking a person whenever the reading abstains, the bars are unlearned, or Jev is
unavailable. Erasure: REDACT for
`outcome` and its fields (they are about the person).

**A card shows:**

- university and programme (or the scholarship's name), country;
- the deadline with a countdown, in `deadline_timezone`;
- readiness: "Documents 4/6 · Answers 12/14" from the kit;
- funding attached: name, what it covers (tuition / living / travel), amount, remaining gap;
- the application fee, "you pay this at submission";
- a badge per new recognised mail and per missing item;
- one main button by column: **Start application** → **Continue filling** → **Submit document** /
  **Open portal**; and a link to the kit.

## 4a. The counsellor on a student's board

An assigned counsellor (`CounselorAssignment`) opens `/counselor/students/<id>/` and sees the same
home, board, documents and messages as the student, **with full rights** (owner, 2026-10-04): add
and remove applications, upload documents for the student, answer missing items, record outcomes,
acknowledge items, write to the student. Each write records who made it (`AuditEvent` with the
counsellor as actor). One thing stays with the student: **Start application and the fill itself**
run in the student's own browser, through the student's paired extension and portal session, so a
counsellor prepares and the student starts (the glass-box spec's "counselor prepares, student
applies"). Staff MFA applies as for every counsellor page. Only an assigned counsellor of the
student's own agency; anyone else gets a 404.

While the student has an open deletion request the counsellor's board is **read-only** (owner,
2026-10-04): every counsellor write is refused (409), and the page says "This student has asked to
delete their account; changes are paused" and renders no forms.

## 5. Programmes & funding

Grouped **under the funding** (owner, 2026-10-04):

- One group per funding opportunity in the pack, headed by the funding: name, holder, what it
  covers, amount, deadline, the structured eligibility fields (nationality rule and the student's
  status, degree stage, grade requirement beside the student's grade in its own scale, deadline /
  intake / cycle in one of the three states). Beneath it, the programmes it can pay for, from
  `FundingOpportunity.programs` (and `program`/`institution` for single-programme and
  institution-wide scope), each with its own fit, fee and gap.
- **Open awards** (owner, 2026-10-04): a HOLDER- or COUNTRY-scope award names no programme, so it
  heads a group listing every programme in the student's pack and pool that it could fund, matched
  on the award's `country_code` (and degree level where both sides carry one), labelled "Eligible
  programmes in <country>". A GLOBAL-scope award lists every programme. Programmes keep appearing
  under their other groups too, marked "also under …".
- A last group, **Programmes without separate funding**: self-funded, or funded only through the
  admission itself.
- A programme fundable by two opportunities appears under both, marked "also under …".
- Each item: **Add to my applications**, **Reject**, **Replace** (the existing pack commands), the
  short explanation, and **"Official source · last checked <date>"** linking to the university's or
  funder's own page (owner, 2026-10-04, amending P1-7.1's "does not display the official source
  URLs"). Only `https` links are rendered, as `RequirementItem` already requires.
- The pool sits below the pack under **Other options**, grouped the same way.
- While research is still running, the page says so and reloads itself every 15 s (a
  `<meta http-equiv="refresh">` only while pending), replacing the deleted htmx polling.

## 6. Documents, and a document someone asks for

**The table:** rows are documents (passport, transcript, diploma, language certificate, CV,
motivation letter per application, recommendation letters), columns are applications, each cell
one of *not needed*, *missing*, *uploaded*, *approved*, *certified copy needed*. Expiry is shown
for the passport and a language certificate. A document is uploaded once and reused wherever it is
needed.

**Where "missing" comes from:**

1. The kit's requirements and documents (`Application.kit_requirements`, `KitDocument`).
2. **Mail.** A `DOCUMENT_REQUEST` message on the content tier now also yields the document's name
   and its deadline: `MailVerdict` gains `document_name` (≤ 120 characters, plain text) and
   `document_due` (a date or blank), schema-constrained like every other field, and stored on the
   signal, never the mail's text. On the metadata tier nothing is read, so the item says "TUM asked
   for a document — open the email" and lets the student choose which document it is.
3. A portal page that asks for an upload the map knows (spec B).

**Submit document:**

1. If the platform holds it (an approved CV, an uploaded transcript), the dashboard shows which
   application it is going to and asks nothing else — §5.6's "verify the document's intended
   application" is the application the item belongs to.
2. If not, the student uploads it once here (the existing presigned upload API), then step 1.
3. The extension opens the portal's upload page and attaches it (spec B: the `OPEN_UPLOAD_PAGE`
   action, declared in `DeviceAction.Kind` and never produced or handled until now). On a portal
   flagged `uploads_irreversible` the side panel asks the student to confirm first.

**How an upload reaches the extension** (owner, 2026-10-04). An upload stays at
`quarantine/{tenant}/{document}`, which the web tier may only write. When the scan result is clean
and the upload check below passes, the document worker that handles it copies the object, byte for
byte, to `tenants/{tenant}/students/{student}/uploads/{document_id}/{version}` (version: the
content's own digest) and records the key and the content type the check read from the bytes on
the `DocumentVersion`.
That worker already holds read on `quarantine/*` and write on `tenants/*`, so no IAM grant changes;
GuardDuty's own `DocumentScanRole` runs none of our code and gets nothing new. Erasure needs no new
code: the student-prefix purge already covers `uploads/`. A new route `GET /ext/documents/<id>`
(device token, deletion lock, rate-limited) streams the copy through the web role with the stored
content type and the three headers below, and answers 404 unless the document is the paired
student's, scanned clean, checked, promoted, and named for one of their applications (by a live
upload action or the current fill packet).

**Upload safety** (owner, 2026-10-04). An upload is attached to a university portal in the
student's name and opened there by admissions staff, so it is held to more than a clean scan.
Already in place: the presigned form pins the exact key by equality and caps the size at 10 MB in
S3 itself, so an oversized file never lands; `quarantine/` is readable only by GuardDuty, the
document worker and the isolated OCR function (which reads only objects GuardDuty tagged clean);
scan first — nothing reads an upload before `NO_THREATS_FOUND` (2026-08-22 ingestion design); the
bucket is encrypted, versioned and private; TLS only. Three additions:

1. **A type allowlist, read from the file's own first bytes.** PDF (`%PDF-`), JPEG (`FF D8 FF`) or
   PNG (`89 50 4E 47 0D 0A 1A 0A`); anything else ends in the terminal state `REJECTED_TYPE`, shown
   as "Upload a PDF, JPEG or PNG". The content type comes from this check, never from the filename
   or the declared type, and every route that serves an upload sends
   `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and
   `Content-Security-Policy: sandbox; default-src 'none'`. *Why:* a scanner finds known malware,
   not an HTML or SVG page named `passport.pdf`; served with a guessed type, that page runs script.
   The headers make the copy a download that is never sniffed and, if rendered anyway, runs and
   loads nothing.
2. **A PDF with active content is rejected, never rewritten.** JavaScript (`/JS`, `/JavaScript`,
   an `/OpenAction` or `/AA` that runs a script or a program), `/Launch`, an embedded file
   (`/EmbeddedFiles`, `/EmbeddedFile`), `/RichMedia` or an XFA form ends `REJECTED_ACTIVE_CONTENT`:
   "This PDF contains active content; save it again as a plain PDF (Print → Save as PDF) and upload
   that". A PDF that cannot be parsed is refused the same way. *Why reject:* a clean scan says
   nothing about a script that runs when a portal or an admissions officer opens the file. *Why
   never rewrite:* stripping content breaks a signed document — Azerbaijan's TMİS e-diplomas verify
   only byte for byte — so a passing PDF is copied unchanged. *Where:* parsing a hostile PDF is the
   risky act, so the check runs inside the isolated OCR function — no route out, read-only on
   `quarantine/`, writing nothing — as a second operation (`inspect`) on its existing entry point,
   returning the type and the active content it found; locally it is the same child process the
   OCR path runs. It reads with pypdf, added to the OCR image because pdfium (already there) can
   run a document's open action but cannot report one. The worker promotes only on
   `NO_THREATS_FOUND` **and** an allowed type **and** no active content. A clean verdict commits
   a new state, `CHECKING` (shown as "checking…"), never `AVAILABLE`; only the check moves it on —
   to `AVAILABLE` together with the promoted copy, to a rejection, or, when the check never
   answers by the queue's last retry, to `REVIEW_REQUIRED`. So `AVAILABLE` always means checked
   and promoted, and no reader of it (ingestion, the documents table, the upload poll, Submit
   document, `/ext/documents`) can take an unchecked file for a usable one.
3. **A first-deploy check.** The GuardDuty Malware Protection plan has never run on real AWS.
   Before the first real student uploads, the standard EICAR test file goes through the real
   presigned form and must come back `THREATS_FOUND`, blocked, not promoted, and 404 at
   `/ext/documents/<id>` (the live-check runbook).

## 7. Start application

- **Add to my applications** creates the `Application`. It needs a `PortalForm` (`portal_form` is
  required) and the catalogue's `Program` has no portal field, so: when the portal is known (a
  `PortalForm` for the programme's application host exists), the card is created ready; when it is
  not, the card is created in **To start** with **Open programme page** instead of Start, and a
  counsellor task "find the application portal for <programme>" is raised. Recording the portal
  then enables Start. (Who and what fills `PortalForm` for a programme at scale is a dependency,
  §9.)
- `capture_requirements(application)` runs in the worker when the card is created
  (CLAUDE.md: the kit reads only that copy).
- **Start application** posts to the server, which marks the card in progress and queues a
  `START_FILL` device action; spec B makes the extension open the portal and fill. Rate-limited
  per student like the other device actions.

## 8. Mail on the board

| Label | Board effect |
|---|---|
| `RECEIVED` (trusted) | card moves to Confirmed (the existing `SUBMITTED → CONFIRMED`) |
| `DOCUMENT_REQUEST` | a missing-document item on the card (§6) |
| `VERIFICATION` | an item; the extension opens it when trusted |
| `INTERVIEW` | an item with the date if the mail states one (`interview_at`, owner 2026-10-04): the item shows it and sorts by it; reminders stay |
| `DECISION` | trusted and Jev's reading clears its bars: card moves to Decision, "Decision available", and the outcome is recorded when the reading states it (once bars are learned; until then the card asks); abstained or Jev unavailable: "Decision available — confirm"; untrusted: the item only (§4). An offered other programme: Accept / Ignore (§4) |
| `FEE` | a fee item |
| `OTHER` | a badge only |

Mail with no application (`MailSignal.application` empty) shows under Messages and on no card.

## 9. Data and code changes

- `Application.decision_available_at`, `outcome`, `outcome_recorded_at`, `outcome_source`,
  `outcome_evidence` (migration; redaction classification); `MailVerdict.outcome_conditions`,
  `offered_programme` (quotes; the classifier reads no outcome); `MailSignal.decision_reading`
  (Jev's reading, REDACT), `outcome`, `funding_outcome`, `offered_programme` (REDACT) and
  `offer_handled_at`; `Application.name` (an accepted offer's programme).
- `apps/mailbox/decision_reader.py`, `decision_questions.py`, `decision_bars.py`;
  `manage.py decision_eval`; `GoldItem.Kind` gains `decision_mail`. Needs `origin/master`'s
  `engine_eval` and `GoldItem` (PR #171), and `OPENROUTER_API_KEY` on the mailbox worker.
- `DocumentVersion.promoted_key` (REDACT) and `content_type`; `state` widened to 30 characters for
  `REJECTED_TYPE` / `REJECTED_ACTIVE_CONTENT`, and the new `CHECKING` state; the check and the promotion in the scan handler;
  an `inspect` operation on the OCR function (pypdf added to the OCR image);
  `GET /ext/documents/<id>`.
- Reading the portal's status page is spec B (`READ_PORTAL_STATUS`).
- The counsellor board view (§4a) and its write paths, each audited.
- `phased requirements.md` P1-7.1 amended to show official source links on the dashboard.
- `MailVerdict.document_name`, `document_due`; `MailSignal.document_name`, `document_due`
  (migration; REDACT).
- `MailVerdict.interview_at` (an ISO 8601 date or date-time, pattern-constrained, blank when the
  mail states none; asked for on `INTERVIEW` mail only); `MailSignal.interview_at` (nullable,
  REDACT to NULL).
- Open awards: a programme's degree level copied onto its pack candidate, so grouping can match
  levels where both sides carry one.
- New views: home board, documents table, messages, settings (mailbox, extension, account),
  outcome post, start post, add-to-applications post, settings-page form posts for mailbox and
  extension disconnect.
- `create_student` command; login/logout routes and limiter; `/` redirect.
- Templates for every student page; the gap interview moved onto `base.html` (its test pins an
  exact `<input type="text"` count, so `base.html` holds no text input).

**Dependencies, stated rather than assumed:**

- Nothing in production creates an `Application` today; this spec adds the student's own "Add to
  my applications". A programme's portal (`PortalForm`) has no source at scale.
- The board shows mail only once PRs #168/#170 merge.
- A requested document reaches the portal only with spec B.

## 10. Open questions for the owner

None open. Answered 2026-10-04: source links shown; counsellors with full rights; a decision is
marked available, and its outcome recorded automatically from trusted mail or the portal, with a
person able to correct it. Answered at plan review, 2026-10-04: logout keeps the extension paired;
a leaving student's board is read-only for the counsellor; interview dates are extracted; open
awards list every eligible programme; Accept on an offer of another programme creates a card;
student mail may go to Jev via OpenRouter and one abstaining reading decides; uploads reach the
extension.

## 11. Testing

- Every new view: GET renders, POST effects, role and tenant isolation (another student's
  application is a 404), the deletion and acceptance locks redirect.
- The kept `frontend` tests pass against the real templates; the retired ones are listed in the
  commit that deletes them.
- The board's column mapping and the funding grouping get unit tests on plain data, so they do
  not depend on markup.
- `collectstatic` under production settings in CI.
- A live check like the mailbox one: a test student, a real Outlook inbox, a document request
  mail, the card updating.
- The decision reader (§4): a fake decisions client proves the recording rule, the abstentions,
  the funding and offer questions and that no stripped identifier reaches the payload;
  `manage.py decision_eval` (`live`) learns the bars on the labelled `decision_mail` gold rows,
  with zero false "decision available" and zero wrong outcomes at the bar as the targets
  (abstentions and coverage reported).
- Uploads to the extension: a clean upload is promoted once, a blocked one never; an HTML file named
  `passport.pdf` and an SVG end `REJECTED_TYPE`; PDFs written with pypdf carrying an `/OpenAction`
  JavaScript, an embedded file, `/Launch` or XFA each end `REJECTED_ACTIVE_CONTENT`; a plain PDF and
  a signed-looking one (`/Sig` field, no active content) are promoted byte-identical; a check that
  never answers promotes nothing; while the check runs the committed state is `CHECKING`, which
  no Submit is offered for and `/ext/documents` refuses; a redelivered `NO_THREATS_FOUND` never
  reopens a rejected upload; the route serves only a named, promoted, clean document of the
  paired student (404 otherwise) with `attachment`, `nosniff` and `sandbox; default-src 'none'`
  asserted; the infra test pins that no new grant was needed; erasure's prefix purge reaches the copy.
- Live, once, on the first deploy: the EICAR upload is `THREATS_FOUND`, blocked, unpromoted, 404.
- Counsellor board: an unassigned counsellor gets 404; every counsellor write leaves an
  `AuditEvent`; Start application is not offered to the counsellor; while the student's deletion
  request is open every write is refused and the page renders no forms.
- Logout leaves the extension paired. An interview mail's date reaches its item. An open award lists
  the programmes of its country from pack and pool. Accept on an offer creates the card (same
  portal when the same institution offers it) and Ignore dismisses it.
