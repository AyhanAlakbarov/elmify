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

   Tier 2 is the one that can classify a message as a decision, document request, interview
   invitation or fee notice and draft a reply. Tier 1 can only say "the university wrote to you on
   Tuesday" — which is still the notification §5.6 needs. No send scope, at any tier, ever.

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
   "answer routine messages" is amended to "draft".

5. **Tokens are secrets; erasure is defined with storage.** Refresh tokens live in Secrets Manager
   under `tehsil/mailbox/{tenant}/{student}/{provider}` — never a model field, never a `JSONField`,
   never logged. `audit/deletion.py::advance_deletion` destroys them on the `EXECUTED` path, on the
   same IAM grant the portal credentials were going to use (`WorkerTaskRole` `DeleteSecret`,
   re-scoped from `tehsil/portal/*`). The rule is the one the 2026-08-25 decision record wrote for
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
  `address`, `tier` (1|2), `secret_id`, `connected_at`, `last_sync_at`, `sync_cursor`, `status`
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

## Requirements amended (dated blocks in `phased requirements.md`)

- §4.3 rewritten: connect-your-own-mailbox, three tiers, pack-derived filter, no send.
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
  `tehsil/mailbox/*` secrets.
- New app `apps/mailbox/`: `oauth.py` (two providers behind one small interface — the second
  provider is what justifies it), `sync.py`, `filter.py`, `classify.py` (tier 2), `views.py`
  (connect / revoke / tier change), management command `sync_mailboxes`, EventBridge rule modelled on
  `EuropassCanaryRule` once anything is deployed.
- Infra: `WorkerTaskRole` gains `GetSecretValue`/`DeleteSecret` on `tehsil/mailbox/*`; the
  `tehsil/portal/*` grant goes with the portal tier.

## Testing

- Filter: a fixture inbox with 50 messages from 10 domains, 2 in the pack → exactly 2 signals; a
  message from a look-alike domain (`tum.de.example`) is excluded (negative control).
- Extraction: a fixture verification mail produces one `DeviceAction` whose payload is cleared after
  completion and appears in no log and no `MailSignal` row.
- Tier 1 never calls the body endpoint (provider fake records every call).
- Tier 2 classifier: data-labelled prompt, `extra="forbid"`, capped tokens, `rate_limited` —
  the same four assertions the other LLM callers carry.
- Erasure completeness: the existing sweep sees `MailboxConnection` and `MailSignal`; a test
  asserts the secret-destroy call for `tehsil/mailbox/*` on the `EXECUTED` path.
- RLS: another tenant's connection is invisible under `rls_enforced_orm`.
- Logging: a log-capture test asserts no header or body text appears at any level.

## Deliberately not built

- **Sending mail as the student.** Drafts only.
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
