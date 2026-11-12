---
paths:
  - "apps/portals/**"
  - "tests/portals/**"
  - "apps/concierge/**"
  - "apps/mailbox/**"
  - "apps/dashboard/**"
  - "extension/**"
  - "infra/**"
  - "apps/audit/deletion.py"
  - "apps/documents/document_reading.py"
  - "apps/documents/fact_writer.py"
  - "apps/documents/id_reading.py"
  - "apps/documents/mrz.py"
---

## The portal browser: its security model is the sandbox

> **Direction change, 2026-09-15 — server portal tier deleted 2026-10-03 (PR #169).** The server-side
> portal browser tier was replaced by a browser extension that fills the portal in the *student's own*
> logged-in tab, with the student pressing Submit (`docs/superpowers/specs/2026-09-15-glass-box-copilot-design.md`).
> Its security premise is a third one: the model key never leaves the server, and the extension holds only a
> revocable device token for one membership. **Reversed for portal passwords by D3 (2026-10-09 co-pilot spec §6):** the platform now creates and holds each student's portal password in Secrets Manager under `PortalCredentialsKey` (`apps/portals/credentials.py`). The web tier creates, reads and deletes it; the extension receives it only from `ext_api.portal_login` (web tier), once per load of a login or sign-up page. Every hand-out and every reveal leaves an `AuditEvent`. A browser receives portal passwords only after the student proved it is them (`ExtensionPairing.passwords_allowed_at`): paired within 15 minutes of typing their Tehsil password, or allowed later with it on Settings › Portal logins. Without that, whoever holds a left-open dashboard session could pair their own client and read every password the reveal page guards. Erasure still destroys it through `advance_deletion` (`WorkerTaskRole` holds `secretsmanager:DeleteSecret` on `tehsil/portal/*`). `DatabaseSecurityGroup` admits `WebSecurityGroup` and `WorkerSecurityGroup`; `tests/infra/test_template.py` pins it.

**If a server-side browser is ever proposed again, read this first.** Both measurements survive:
the research browser's `/proc/<pid>/environ` carried none of the worker's secrets once it lost its
task role (`.claude/rules/web-fetching.md`), and an authenticated browser is safe only behind an engaged
renderer sandbox, which on this platform means EC2, not Fargate. The deleted code is in git
history at the commit before PR #169.

## Application automation (Phase 3) — decided in advance, and now partly built

> **Direction change, 2026-09-15.** The agent-fills-for-the-student model is retired in favour of
> the glass-box co-pilot: a Manifest V3 extension paired invisibly to the dashboard session fills the
> visible portal tab from a server-minted fill packet, attaches approved PDFs through the existing
> `download_document` route, reads back, and reports; **the extension types, the student clicks** —
> it never dispatches a click on navigation, consent or submit. Kept unchanged: `PortalForm` /
> `FieldMap`, `FILL_METHODS` (`setFiles` lives in the extension's document attach, `fill.ts`, never in `FILL_METHODS`: documents are not field-map entries), `profile.py`, `already_correct`/`read_back`,
> `escalation.py`, the `ApplicationStep` trail. Retired: server-held logins for reauthentication (portal passwords returned with D3, above),
> browser profiles, the CAPTCHA service, `counselor-submit` and the 48-hour auto-submit (§5.1
> amendment), and the pause/hand-off/resume spike — in the student's own tab the question dissolves.
> The mailbox changes in the same direction: no platform address, an OAuth read-only / metadata
> connection to the student's own inbox filtered to the pack's institutions, nothing sent
> (`docs/superpowers/specs/2026-09-15-student-owned-mailbox-design.md`). Several bullets below still
> describe the retired design; they are left as the record of why each decision was taken.
> Owner decisions of the same evening, recorded in that spec: two layers (an Application Kit the
> student can apply by hand on any device, and the extension that applies it fast); install and
> pairing enforced at onboarding; the student presses Next between pages; verification links
> auto-open in the student's own browser; a 14/7/3/1-day + 6-hour reminder ladder; a per-portal
> `terms_posture` from a seven-portal sample in which none forbids autofill and all forbid credential
> sharing; and an agency-level counselor mode defaulting to "counselor prepares, student applies".

**The kit is a counsellor's debugging view, not the student's (owner, 2026-10-10).** Students apply
only through the extension; nothing shows them how to apply by hand. `build_kit` now serves only
`dashboard/views.py::application_answers` ("Answers we'll submit", the assigned counsellor, GET only,
every other caller the same 404 as a random id) and the board's readiness count. That view calls
`build_kit(..., issue_address=False)`: the default issues the student's tagged portal address, which
is a write. Never gate the student's applying on that page.

**Built, 2026-09-15: the kit and the packet** (`apps/portals/packets.py`). `build_kit` and
`mint_packet` are one preparation with two renderings and a test pins that they cannot
disagree. The asymmetry is the design: `build_kit` never raises and degrades (no field map ->
held answers plus the programme's REQUIRED statements; `PROHIBITS_AUTOMATION` -> `fillable=False`),
`mint_packet` refuses with a stable reason (`no_portal`, `automation_prohibited`,
`unsafe_action`, `malformed_field_map`, or `NoFieldMap`). Checked in that order: `no_portal` ->
`automation_prohibited` -> `NoFieldMap` -> `malformed_field_map` -> `unsafe_action`.
A fact-less mapped field is a red hint, never a refusal or an escalation (owner, 2026-10-09); it is
recorded as the PACKET's `missing_fields` and handed to `fact_reading.request_fact_reading`, the
hook a background reader of the student's own uploads attaches to. Maps carry `sure` and `slots`;
unsure or fact-less fields are hints with no value; documents attach by learned slots that code
pairs (`apps/portals/slots.py`). `portals.PortalAnswer` is the one place a typed portal value is
stored: tenant-only, erased with the student, never in a shared map or a prompt.
Every FieldMap row is read through one function, `_parse_entry`, which refuses the whole packet on
any row it cannot read (no `profile_field`, no `action`, or an `action` that fails schema
validation) -- so a malformed row is always caught before `unsafe_action` gets to
reason about it. The posture check is first, so a prohibited portal never reads a verified value. The `PACKET` `ApplicationStep` is
the authoritative record of what the platform prepared; whatever the extension later reports is
an attestation from a device we do not control.

**Since 2026-09-25 the kit reads no catalogue; it reads a copy.** `build_kit` is served from a web
view and `runtime_web` holds no grant on `ProgramStatement` or `ApplicationPrompt`, so
`capture_requirements(application)` copies the checklist, the student's letter actions and the
letter cycle onto the `Application` row, **in the worker**, and `build_kit` reads only that copy.
Two things follow, and neither is built. **Whatever creates an `Application` must call
`capture_requirements` in the worker** before the kit is served — `applications.add_application` creates
one and queues `capture_requirements` to the document worker on commit; until it runs, the kit shows an empty checklist that looks exactly like a
programme stating nothing. And **the copy goes stale when the programme page is re-read**: nothing
re-captures it. Download filenames follow the same rule — `DocumentDraft.rendered_filename` is
written by the worker at render and the web tier never resolves a variant live.

**Built, 2026-09-17: pairing and the extension API** (`apps/portals/pairing.py`, `ext_api.py`,
`snapshot.py`, `actions.py`, plan 2 of 5). Two rules from its security review bind anything built
on top of it:

- **A `FieldMap` learned from a snapshot is scoped to the tenant that sent it.**
  `FieldMap.learned_by_tenant` is NULL only for a map the PLATFORM verified by driving a real
  browser at the real form; a snapshot is a claim by a client, and the server cannot check its
  selectors against the page. Read-back cannot catch a bad one either -- it reads back the same
  selector it typed into, so a wrong-but-consistent map verifies clean. Shared, that let one
  tenant's student decide where every other tenant's students' identity fields get typed.
  `current_for(portal_form, tenant_id)` therefore takes the tenant and **has no default**: a caller
  that forgets it silently gets shared-only maps. Do not add one. Superseding is per-scope for the
  same reason; the version counter stays global because `field_map_form_version_uniq` is
  `(portal_form, version)`. Promotion of a tenant map to the shared row on agreement between
  tenants is deliberately not built. The "after a human looks" half is the verified gate (plan 6):
  a bench-verified map (`FieldMap.verified_at`) outranks a tenant-learned one and serves every
  tenant, and a live relearn over it marks its form `needs_bench`. The bench's read-back is the
  same blind check, so the human look is at the mapping: `portal_bench` prints every row beside
  the box's label on the operator's own walk, and `promote` takes only the exact mapping the
  operator confirmed (`--confirm <digest>`, `bench.mapping_digest`). Do not drop that step as
  redundant with a clean replay; a clean replay cannot see a swapped box. Students' own answers never
  re-point a verified map (verified outranks, by design); answers learn only tenant maps.
  `PageRecord` and bench HTML are kept, never served to a tenant view, and not reached by erasure
  (owner, 2026-10-09: no student value by construction).
- **A device token must die with the account it names.** `authenticate_device` filters on
  `membership__active=True`, and `_device_endpoint` applies `deletion_lock_target`. Both exist
  because the session path enforces those in `current_membership` and `TenantMembershipMiddleware`,
  **inside `if request.user.is_authenticated`** -- a device token carries no session and runs past
  both. Without them, `advance_deletion`'s `active = False` is not load-bearing on this surface and
  a locked-out student's extension keeps being handed packets of their own verified facts for the
  whole thirty-day window. `request_deletion` also revokes every pairing at request time, not at
  `EXECUTED`: `DELETE /ext/pair` authenticates with the very token you would be revoking, so a
  device the student no longer holds cannot revoke itself.

**Built, 2026-10-12: reading a student's documents into facts** (`apps/documents/mrz.py`,
`id_reading.py`, `document_reading.py`, `fact_writer.py`, consumed by `portals/profile.py` and
`portals/fact_reading.py`; spec `docs/superpowers/specs/2026-10-12-document-fact-reading-design.md`).
A passport goes through Azure prebuilt-idDocument plus the MRZ check digits; diplomas and
certificates through the readers in `.claude/rules/llm-ai-security.md`.

- **Launch gate: `FACT_READING_ENABLED` ships off.** It goes on for real students only after spec
  §9's gates: a consented document set judged by the owner, with zero wrong proven values, and one
  live call per reader. Diplomas and certificates also need `FACT_READING_READERS` (two vendors) and
  `OPENROUTER_API_KEY`; with either unset they are neither queued nor read.
- **A proven value is a confirmed fact no person confirmed.** `confirmed_by` names the student whose
  document it is, and the audit event is `fact.read_from_document` with `actor_kind=AGENT`. Proven
  means the strip's check digit and the printed page agree (or Azure's confidence where the strip is
  silent). It never means genuine: nothing checks authenticity, so no screen may call a value
  "verified" in that sense.
- **IDENTITY is no longer one row.** A passport writes one IDENTITY row per key. Anything needing
  the person's name filters with `verification.has_full_name`, never
  `filter(category=IDENTITY).last()`.
- **The ownership check is strict on purpose** (`id_reading._owner_matches`): one known whole name
  must match both the first given name and a surname word. A wrong "yes" sends another person's
  passport to portals unconfirmed, so do not loosen it without the must-hold cases in
  `tests/documents/test_id_reading.py`. A passport that fails it writes no fact, only a problem line.
- **Precedence** (`fact_writer.py`): a document's age comes only from its CONFIRMED issue date; a
  read never carries back a key the student owns; ID documents are grouped per document by
  `verification.id_documents` for both the portal and the dashboard. Never group them a second way.
- **Every Azure answer counts toward the shared daily page ceiling** (`azure_pages` on READ, FAILED
  and DELAYED), not only successful ones. A FAILED reading is never re-queued: the student
  re-uploads.
- **An offered value is typed only after the student's tap, and only the server's.** A packet hint
  may carry a doubtful document value (`PacketHint.offer`). The panel's Use goes panel -> worker ->
  `ext_api.confirm_offer` -> the bound tab. `profile.document_offers` is the one gate: `mint_packet`
  and the route both ask it. The route accepts only a fact the application's latest PACKET step
  offered *and* that `document_offers` still offers now. That means one value per row, of an ID
  document the student owns: never disowned or replaced, never `owner_mismatch` / `owner_unknown`,
  never an unread date (`fact_writer.needs_typing`), never an expired passport's, and a passport
  value only from the one passport portals are served (`profile._picked`). It writes the value as
  a new confirmed row (`fact_writer.use_document_value`), never confirms in place, so the tapped
  value is the one portals get next. The dashboard's Use on a passport value goes through
  `use_document_value` too. The worker takes the offer from its cached packet and the value from
  the route's answer; nothing a page sends names either. The content script types it through
  verify -> fill -> read-back, judged against the whole packet, and never over a held value. A
  value saved but not typed (the tab is gone, or the box is held) is reported to the student as
  `not_typed`, so they type it themselves. The upload prompt's "you have it" is the documents
  table's rule (`apps/documents/table.py`: AVAILABLE or CHECKING, unretired). Diploma and
  certificate values are never one tap away: they are answered on the dashboard.

Full reasoning in `docs/superpowers/specs/2026-08-25-application-automation-decisions-design.md`.

The decisions below still bind where the glass-box design kept them, and most are now
honoured rather than pending, so check before "adding" one. The pause/hand-off/resume
spike is retired with the agent-fills model.

- **Portal credentials never live in the database.** `phased requirements.md` §5.2 has the
  platform reauthenticating with managed credentials, and since D3 passwords are held (`apps/portals/credentials.py`). They go in
  a dedicated secret store (Secrets Manager under a KMS key), keyed per student-portal — never
  a model field, never a `JSONField`, never in the evidence bucket, never logged or in an
  exception message. The IAM grant is per-secret-prefix: the web tier (which mints the login for the extension) creates, reads and deletes; the worker only deletes, on erasure; the dormant portal task also reads (`PortalTaskRole`) until PR #169 removes it. Erasure ships with storage: `apps/audit/deletion.py::advance_deletion` must
  destroy a student's secrets on the same path it deletes their documents, or GDPR erasure
  leaves credentials behind. The failure mode this rule exists to prevent is a password column
  added in passing during a sprint.
- **CAPTCHA is detected and delegated, never circumvented.** The strategy is detect → preserve
  the session → hand to a human → resume, per §5.2. Browser stealth is not a CAPTCHA strategy
  and must not be adopted as one; §2 forbids unauthorized circumvention and §3.4 (formerly §3.6) excludes
  proxy infrastructure intended to evade portal access controls.
- **No fetch vendor is ever pointed at a portal.** Firecrawl and scrape.do read public,
  unauthenticated programme pages (`.claude/rules/web-fetching.md`) — the same rule the Scrapling tier they
  replaced carried, because it is a legal boundary, not a property of which client does the
  fetching. Defeating an access control on an authenticated third-party system is a different act
  from reading a public page. Portal execution gets its own client.
- **No platform egress is pointed at a portal, and rotating or residential pools are never used for portal traffic.** Under the glass-box design portal traffic leaves from the student's own browser.
- **Portal automation goes in a new app, never in `apps/concierge`.** That module's docstring
  guarantees every action in it is a human-recorded fact, and
  `tests/concierge/test_roadmap.py::test_no_payment_or_portal_automation_call` enforces it.
  When Phase 3 lands, the temptation is to delete that test. Don't — narrow the scope by
  putting automation elsewhere. `ManualOperation` gains no automated writer.
- **Agent actions are already representable.** `AuditEvent.actor_kind` distinguishes an agent
  write from a platform write (both carry `actor=NULL`), and `RoadmapItem.owner_kind` lets the
  agent own a step without a synthetic `Membership`. Use them; do not add a fake member row.
