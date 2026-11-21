# The student's own mailbox: read what the pack says to read, send nothing

Amended 2026-09-25 by `2026-09-25-application-watch-design.md` (which mail is read, the
application inbox, when the mailbox is asked for); where they differ, that one governs.

Status: **design, direction agreed with the owner 2026-09-15** (see "Decisions taken with the owner");
spec text awaiting final read. Authorizes planning only.
Date: 2026-09-15.
Supersedes: `phased requirements.md` §4.3 "Dedicated application email" (the platform-domain
address per student), the mailbox half of `2026-08-25-cv-identity-sourcing-design.md`, `idea_v2.md`
refinement E, and `cloud.md` §12's SES-inbound / S3-inbox lines. Companion to
`2026-09-15-glass-box-copilot-design.md`: both rest on one principle — the platform acts inside the
student's own accounts, with the student's own grant, and the student performs.

## Goal, in three beats

**What and why.** No `@platform-domain` address per student and no disposable or proxy domain.
The student connects the mailbox they already use — Gmail, Outlook.com, or a Microsoft 365 / Google
Workspace university account — through OAuth with the smallest scope that does the job. By default
the platform reads **metadata only** (sender, subject, date, labels — headers, never a body), and only
for messages whose sender belongs to an institution or funder in the student's own application pack.
Reading message bodies is a separate, per-student opt-in. The platform never sends as the student:
§4.4's "answer routine messages" becomes "draft the reply; the student sends it".

**The catch.** Both Gmail read scopes — including the metadata-only one — are Google *restricted*
scopes: they need Google's OAuth app verification and an **annual** security assessment (CASA,
ending in a Letter of Validation) before the app leaves testing mode, which caps it at 100 users.
Microsoft's body-free scope needs no admin consent and works on personal accounts, but it forbids
search, and a university's Microsoft 365 or Workspace tenant may block third-party consent
entirely. So there is always a *no connection* tier: the student reports status and uploads the
decision letter by hand.

**What it costs to reverse.** Low. No infrastructure is bought; a connection is a row plus a
refresh token in Secrets Manager, revoked by the student or by erasure. Reverting to a
platform-domain address would mean building SES inbound, an S3 inbox and a per-student domain
identity that nothing today has started.

## Why the platform address existed, and why it no longer needs to

`apps/tenancy/models.py` says it plainly: the platform mailbox is "the address we register on
university and funder portals with, and scrape for results and required actions … publishing the
login address to a funder sends the reply where nothing is watching". The premise is that the only
inbox the platform can watch is one it owns. With the student's grant, the platform can watch the
student's own inbox — narrowly — so the premise falls, and with it: a second identity the student
must remember to check, the §10 "email-provider terms, sender reputation and production-domain
configuration" blocker for inbound mail, SES inbound and the S3 inbox, and the oddity of a
third-party address registered on a portal that will one day ask the student to log in with it. The
code already prefers the student's own address where one exists: `Membership.academic_email` is
printed on the CV ahead of the platform mailbox (`documents/generation.py::contact_email`).

## Decisions

1. **No platform-domain address per student.** `Membership.application_email` keeps its column
   and its gate but changes meaning: *the address the student applies with* — the connected mailbox
   address, or, with no connection, an address the student declares and confirms. `generate_cv`'s
   refusal becomes "tell us which address to print", not "wait for provisioning". The extension fills
   portal email fields from it.

2. **Three tiers, metadata by default.**

   | Tier | Google scope | Microsoft scope | What the platform sees |
   |---|---|---|---|
   | 0 — none | — | — | what the student tells the dashboard |
   | 1 — metadata (default) | `gmail.metadata` | `Mail.ReadBasic` | headers (sender, subject, date) and labels; never body or attachments; neither scope permits search, so the filter runs on sender in code |
   | 2 — content (opt-in) | `gmail.readonly` | `Mail.Read` | body and attachments, **only** of messages that passed the tier-1 filter |
   | 3 — draft (opt-in, added 2026-09-25) | `gmail.compose` | `Mail.ReadWrite` | tier 2, plus the ability to put a finished draft — subject, body, attachments — into the student's own mailbox, on their press (decision 9) |

   Tier 2 is the one that can classify a message as a decision, document request, interview
   invitation or fee notice and draft a reply. Tier 1 can only say "the university wrote to you on
   Tuesday" — which is still the notification §5.6 needs. **No send scope on Microsoft, at any tier,
   ever** — `Mail.Send` is separate and is never requested. On Google the guarantee is weaker and
   decision 9 says exactly how.

3. **The filter is the student's own pack.** Before any message is fetched, the sync computes the
   set of sender domains it is allowed to look at: the origins of the `OfficialSource.canonical_url`
   rows behind the programmes and funders in the student's approved pack, plus the portal hosts of
   the student's `Application` rows. Messages from anyone else are never listed, never fetched and
   never stored. The scope Google or Microsoft grants is wider than this; the filter is what the
   platform *does*, recorded and testable, and it is the answer to "what do you read?" — *only mail
   from the institutions you are applying to*.

4. **Nothing sends.** A tier-2 classification that warrants a reply produces a draft in the
   dashboard, built only from verified facts and approved documents, which the student sends from
   their own client (a prefilled `mailto:` and a copy button). §4.4 "never invent an answer" stands;
   "answer routine messages" is amended to "draft". *Where the draft goes is amended by decision 9;
   that a person presses Send in their own client is not.*

5. **Tokens are secrets; erasure is defined with storage.** Refresh tokens live in Secrets Manager
   under `elmify/mailbox/{tenant}/{student}/{provider}` — never a model field, never a `JSONField`,
   never logged. `audit/deletion.py::advance_deletion` destroys them on the `EXECUTED` path, on the
   same IAM grant the portal credentials were going to use (`WorkerTaskRole` `DeleteSecret`,
   re-scoped from `elmify/portal/*`). The rule is the one the 2026-08-25 decision record wrote for
   portal passwords; this is its second tenant.

6. **Stored derivatives are minimal and about the student only.** A `MailSignal` row holds the
   provider message id, sender domain, received time, the `Application` it was matched to, and (tier
   2) a classification label and confidence. No subject, no body, no attachment bytes are stored. A
   tier-2 extraction writes roadmap facts (a new deadline, a requested document) with the message id
   as provenance. Attachments — a decision letter — are shown to the student and saved as a
   `DocumentDraft` only when the student presses *save*, not automatically.

7. **Providers, and the university case.** Google and Microsoft cover personal mail and, in
   practice, nearly every university mailbox (Workspace or Microsoft 365 under the university's
   tenant). A university tenant that blocks third-party consent puts that student on tier 0 for that
   mailbox; the dashboard says so and nudges them to apply with the personal mailbox they did
   connect. IMAP with an app password is **not** offered: it is a stored credential with full access,
   the class of thing this design exists to avoid.

8. **Google verification is a §10 launch blocker, not a footnote.** Restricted-scope verification
   plus the annual CASA assessment must be complete before a 101st Google user can connect. The
   concierge MVP fits under the 100-user testing cap; production does not. Cost and lead time are to
   be quoted by an approved assessor and recorded in §10 before launch.

9. **One button prepares the whole e-mail — as a draft in the student's own mailbox** (owner,
   2026-09-25). Some awards are applied for by writing to someone: a nomination scheme like France
   Excellence / Eiffel, where the student asks the host institution's international office to put
   them forward (funding engine spec, 2026-09-22 design §9.2, `EMAIL` kit step). That e-mail is a
   subject, a body and the approved PDFs, and **a `mailto:` link cannot carry an attachment** — no
   browser or mail client accepts one, for good reasons. So decision 4's `mailto:` leaves the
   student assembling the attachment by hand at exactly the moment the platform claimed to help.

   On a tier-3 connection, pressing *Prepare this e-mail* creates **one draft in the student's own
   mailbox** — recipient, subject, body, the approved documents pulled from the evidence bucket and
   attached — and opens it in their client. The student reads it and presses Send. Three rules make
   that safe to offer: a draft is written **only** in response to that press, never by the sync or
   any background job; the body is a document like a letter, so it carries a `ConsentEvent`
   approval and **the button does not exist before the student has approved it**; and the
   attachments are only documents already in `APPROVED` state.

   **The provider asymmetry is the cost, and it is not symmetric.** Microsoft separates drafting
   (`Mail.ReadWrite`) from sending (`Mail.Send`), so the structural guarantee survives untouched:
   the platform *cannot* send, because it never holds the scope. Google publishes no draft-only
   scope — `gmail.compose` carries `messages.send` with it. On Gmail, therefore, "the platform
   cannot send" becomes **"the platform does not send"**: a promise kept by our code rather than
   refused by the provider. It is pinned the way `apps/concierge` pins its own boundary — a test
   asserting no send endpoint is called anywhere in the tree, and the scope allowlist naming the
   four scopes that may ever be requested. A weaker guarantee, bought for an attachment, and the
   owner may reverse it for Gmail alone (open decision 4) at the cost of tier 3 being a Microsoft
   feature.

   **The fallback is the old behaviour, and nothing is ever broken by its absence.** On tiers 0-2,
   on a student who declines, and on any draft call that fails, the kit shows the `mailto:` with
   subject and body plus a *download and attach these two files* checklist — the Application Kit's
   own promise that it works on any device, unchanged.

   **What is stored is the provider's draft id on the `EMAIL` `ApplicationStep`**, so the card can
   say *prepared*, *sent* or *replied* — never the body, never a copy of the draft.
   **And erasure does not reach it:** a draft inside the student's own mailbox is their data in
   their account. Erasure destroys our token, our rows and our copies; it cannot delete mail from
   someone's mailbox, and the dashboard says so where it says what erasure does.

   `gmail.compose` is restricted exactly like `gmail.readonly`, so the CASA assessment already
   budgeted in decision 8 covers it; no new class of review appears on either provider.

## Decisions taken with the owner, 2026-09-15 (evening)

Where these differ from the numbered decisions above (notably the default tier), these govern.

1. **Both providers from the pilot.** Google and Microsoft connect at launch. The pilot stays under
   Google's 100-user testing cap; the restricted-scope verification and yearly assessment are a
   budgeted launch item, not a reason to go Microsoft-first.
2. **The content tier is what the agreed flow needs, so it is the tier offered at connect**, with the
   pack-derived sender filter shown on the same screen as the real privacy control. The metadata tier
   stays as the reduced option for a student who declines. (Decision 1 of the open list, resolved by
   implication: everything below except "a mail arrived" requires the body.)
3. **Every mail-driven action becomes a card action, not an inbox trip.** A verification link is
   extracted and opened by the extension in the student's own browser, automatically, default on
   (`2026-09-15-glass-box-copilot-design.md`, owner decision 5); a verification code is shown in the
   dock and typed by the extension. "Received", application numbers, interview dates and decisions
   update the card with no press. "Please upload" becomes a one-press task. Nothing here is ever
   performed from our servers against a portal.
4. **Sender filter learns each portal's real sending domain.** Many portals send from a vendor
   domain, not the university's. The first confirmation a student marks on a portal records that
   sender on the `PortalForm`, shared for every later student; the extension's portal status read
   (glass-box decision 7) covers the gap before it is learned.
5. **The student's current university mailbox is not relied on.** University tenants may block
   third-party consent, and the mailbox usually expires within months of graduation, when decisions
   arrive. It stays what it is today: an address printed on the CV. At onboarding the student picks
   one inbox they own for all applications; a guided two-minute setup of a fresh personal Outlook.com
   address is offered as an option, never created by us (Microsoft forbids automated account
   creation, and an address under our domain is the platform mailbox this design retires).
6. **Attachments are saved on the student's click**, unchanged (open decision 3, resolved).

## Flow

```
connect ──► OAuth (tier-1 scope) ──► MailboxConnection row + token in Secrets Manager
                                              │
sync (per tenant, rate_limited, provider delta/history API)
   │  allowed_domains = pack origins ∪ application portal hosts
   ├─ list messages: Google — metadata format (no `q` search under gmail.metadata), filter by From header
   │                 Microsoft — $filter on from/emailAddress/address and receivedDateTime
   │                 (no $search under Mail.ReadBasic; subjects classified in code)
   ├─ MailSignal per matching message ──► Notification "TUM wrote to you" ──► roadmap card
   └─ content tier: fetch body ──► classify (reference LLM pattern: data-labelled,
         extra="forbid", capped tokens, rate_limited)
            ├─ card fact (received / number / interview / decision)  ── no press
            ├─ DeviceAction (verification URL or code)  ──► extension opens or types it
            └─ draft reply ──► student sends from own client
```

The classifier is the fourth-in-kind LLM caller after `research/extraction.py`,
`funding/explanations.py` and `documents/evidence/extraction.py`, and follows them exactly. Raw
headers and bodies are never logged (engineering rule; `python.md`).

## Data model

- `MailboxConnection` (tenant-scoped): `membership` FK (cascade), `provider` (`GOOGLE`|`MICROSOFT`),
  `address`, `tier` (1|2|3), `secret_id`, `connected_at`, `last_sync_at`, `sync_cursor`, `status`
  (`ACTIVE`|`REVOKED`|`ERROR`), `revoked_at`. One active connection per provider per membership.
- `MailSignal` (tenant-scoped): `connection` FK (cascade), `provider_message_id`, `sender_domain`,
  `received_at`, `application` FK (nullable, `SET_NULL`), `label` (nullable), `confidence`
  (nullable), `created_at`. Unique on `(connection, provider_message_id)`.
- **What a classified message produces is a `DeviceAction`, never a stored link.** The content-tier
  classifier extracts at most one actionable item per message — a verification URL, a numeric code,
  an application number, a document request, an interview date, a decision — and writes it to the
  `DeviceAction` table of `2026-09-15-glass-box-copilot-design.md` (or straight onto the card, for the
  items that need no device). A verification URL is a bearer credential for the student's portal
  account, so it lives only in that short-lived row, is delivered once, and its payload is cleared on
  completion. It is never written to `MailSignal`, never logged, and never leaves the student's own
  browser to be opened.
- **A prepared e-mail is one id on one step.** The tier-3 draft (decision 9) writes the provider's
  draft id onto the `EMAIL` `ApplicationStep` and nothing else — no recipient copy, no body, no
  attachment bytes. The step's later states come from the mailbox it already watches: the reply
  arriving is the read-back.
- **Learned sender domains.** The first message a student confirms as belonging to a portal records
  its sender on `PortalForm.sender_domains`, shared for every later student, which is how the
  pack-derived filter reaches portals that mail from a vendor's domain.
- `Membership.application_email`: column unchanged; docstring and gate message rewritten (see
  "What changes in code").
- `Application.State.CONFIRMED` gains its first writer: a `MailSignal` from the application's portal
  host classified as a confirmation (tier 2), or the extension's marker-matched confirmation page.

## Privacy and security

- **Least scope, then a stricter filter of our own.** The consent screen shows the provider's
  scope; the dashboard shows the domain list actually read, per student, live.
- **Who is the processor.** Google and Microsoft act on the student's own grant; they are not our
  sub-processors for this data. The platform is controller of the derived `MailSignal` rows and of
  anything tier 2 extracts. §10's DPA line is amended accordingly.
- **Tenant isolation.** Connections and signals are tenant-scoped under RLS like every other
  student row; the sync worker runs under `tenant_scope()` with the GUC set, one tenant at a time,
  like `research/worker.py`.
- **Revocation.** From the dashboard (deletes the secret, marks `REVOKED`, keeps signals), on
  erasure (secret destroyed, rows cascade), and on the provider's side (a refresh failure marks
  `ERROR` and notifies the student; nothing retries indefinitely).
- **What is never stored:** subjects (read at both tiers for classification, then discarded), bodies,
  attachments, other people's addresses.
- **What erasure cannot reach.** A tier-3 draft lives in the student's own mailbox (decision 9).
  Erasure destroys the token, the rows and our copies; mail in someone's own account is theirs to
  delete, and the consent screen and the erasure page both say so rather than implying otherwise.

## Requirements amended (dated blocks in `phased requirements.md`)

- §4.3 rewritten: connect-your-own-mailbox, four tiers (the fourth prepares a draft in the student's
  own mailbox, 2026-09-25), pack-derived filter, nothing sent by the platform.
- §4.4: "Answer routine messages" → "Draft routine replies for the student to send"; reading
  requires tier 2.
- §5.6: "Monitor the platform-managed mailbox" → "Monitor the connected mailbox, within the
  pack-derived sender filter".
- §10: inbound "email-provider terms, sender reputation and production-domain configuration" narrows
  to outbound notification mail only; adds Google restricted-scope verification + annual CASA, and
  Microsoft publisher verification; DPA line notes the controller/grant shift.
- `idea_v2.md` §1 and refinement E: superseded by pointer.

## What changes in code

- `apps/tenancy/models.py` `application_email` docstring: from "platform-issued … we register and
  scrape" to "the address the student applies with; connected or declared". `academic_email` stays
  as the CV-preferred address.
- `apps/documents/generation.py::contact_email` docstring; `ApplicationEmailMissing` message;
  `apps/documents/api.py` 409 reason text. The gate logic is unchanged.
- `apps/documents/verification.py` and `apps/documents/models.py` comments that call the address
  "platform-issued … nothing to confirm": a declared address is now a student-attested fact and is
  confirmed once, in the dashboard, like any other.
- `apps/audit/redaction.py`: `application_email` stays in the `Membership` redact spec; add
  `MailboxConnection.address` and `MailSignal` to the erasure sweep; `advance_deletion` destroys
  `elmify/mailbox/*` secrets.
- New app `apps/mailbox/`: `oauth.py` (two providers behind one small interface — the second
  provider is what justifies it), `sync.py`, `filter.py`, `classify.py` (tier 2), `views.py`
  (connect / revoke / tier change), management command `sync_mailboxes`, EventBridge rule modelled on
  `EuropassCanaryRule` once anything is deployed.
- `apps/mailbox/draft.py` and one route behind it (decision 9): builds the MIME message from the
  approved body and the `APPROVED` documents and creates it through whichever provider the
  connection names — Gmail `drafts.create`, Graph `createMessage` plus an attachment upload. It
  refuses without a tier-3 connection and without the body's `ConsentEvent`, and returns the id the
  `EMAIL` step stores. The provider interface gains `create_draft` and nothing that sends.
- Infra: `WorkerTaskRole` gains `GetSecretValue`/`DeleteSecret` on `elmify/mailbox/*`; the
  `elmify/portal/*` grant goes with the portal tier.

## Testing

- Filter: a fixture inbox with 50 messages from 10 domains, 2 in the pack → exactly 2 signals; a
  message from a look-alike domain (`tum.de.example`) is excluded (negative control).
- Extraction: a fixture verification mail produces one `DeviceAction` whose payload is cleared after
  completion and appears in no log and no `MailSignal` row.
- Tier 1 never calls the body endpoint (provider fake records every call).
- Tier 2 classifier: data-labelled prompt, `extra="forbid"`, capped tokens, `rate_limited` —
  the same four assertions the other LLM callers carry.
- Erasure completeness: the existing sweep sees `MailboxConnection` and `MailSignal`; a test
  asserts the secret-destroy call for `elmify/mailbox/*` on the `EXECUTED` path.
- RLS: another tenant's connection is invisible under `rls_enforced_orm`.
- Logging: a log-capture test asserts no header or body text appears at any level.
- Tier 3 (decision 9): no send endpoint is called anywhere in the tree, and the scope allowlist
  admits nothing beyond the four named scopes — the pair that replaces Gmail's missing structural
  guarantee, so neither may be deleted. The draft route refuses a tier-1/2 connection, refuses an
  unapproved body, and refuses a document that is not `APPROVED`; a failing provider call leaves the
  step in its `mailto:` fallback rather than an error page.

## Deliberately not built

- **Sending mail as the student.** Drafts only — in the dashboard at tiers 0-2, in the student's own
  mailbox at tier 3 (decision 9). A person presses Send, always, in their own client.
- **IMAP / app passwords.** A stored full-access credential.
- **Reading Gmail's web UI through the extension.** Fragile, and policy-exposed; the extension is
  for portals.
- **Per-university connectors.** Workspace and Microsoft 365 are the universities.
- **Storing subjects to search later.** If tier 1 proves too blunt, the answer is tier 2 for that
  student, not a subject index.

## Open decisions for the owner

1. ~~Default tier~~ — **resolved 2026-09-15**: content tier offered at connect, metadata as the
   reduced option (see "Decisions taken with the owner", 2).
2. ~~Who pays for the CASA assessment and when~~ — **resolved 2026-09-15**: both providers at
   launch; the assessment is budgeted before the 101st Gmail user.
3. ~~Decision letters~~ — **resolved 2026-09-15**: saved on the student's click.
4. **Tier 3 on Gmail** (opened 2026-09-25). Decision 9 accepts `gmail.compose`, which carries the
   ability to send, to buy a one-press e-mail with attachments. The alternative is tier 3 on
   Microsoft only, with Gmail students kept on `mailto:` plus a download-and-attach checklist —
   structurally unable to send, and worse to use for what is likely most students. Taken as
   written; reversible for Gmail alone by dropping one scope from the allowlist, and worth
   revisiting if Google ever publishes a draft-only scope.
