# Application watch: no deadline is lost without a person knowing

Status: **design, agreed with the owner in conversation 2026-09-25**; spec text awaiting the
owner's read. Authorizes planning only.
Date: 2026-09-25.
Amends: `2026-09-15-student-owned-mailbox-design.md` (which mail is read, the default inbox,
when the mailbox is asked for). Builds on: `2026-09-19-reminder-ladder-design.md` (built),
`2026-09-15-glass-box-copilot-design.md` (the extension, `DeviceAction`, the portal status read).

## Goal, in three beats

**What and why.** A missed university email can become a missed deadline. The owner's
requirement is that nothing the student must act on is missed, and that the platform never
reads mail it has no reason to read. No design can guarantee that every email is caught —
some portals post only inside the account, real mail lands in spam, a student can delete
one. So the guarantee is moved to where it can be kept: **the platform knows what it is
waiting for on every application, and every deadline gets an alert a person has
acknowledged in time.** Email becomes one of several ways information arrives, and the
fastest, not the thing safety rests on.

**The catch.** The platform never holds portal passwords and never logs in to a portal
(below, "Rejected"). So a portal-only update is seen only when someone opens the portal: the
extension reads it then, or the student reports it. The design's job is to make sure someone
opens it at the right moment — and to notice when nobody has.

**What it costs to reverse.** Low. Most of it composes what exists: `Application.deadline`,
the `ApplicationStep` trail, the built reminder ladder, `Notification.acknowledged_at`, the
mailbox app. New are an expectation record per application, a watchdog, per-portal-account
tagged addresses, and self-monitoring.

## Decisions taken with the owner, 2026-09-25

**2026-09-26: no Gmail during the pilot.** Only Microsoft mailboxes connect — personal
Outlook.com and university Microsoft 365 — until Google verifies the app (restricted-scope
verification plus the yearly CASA assessment). An unverified app is capped at 100 Google users
and its grants expire every 7 days, which a reliability product cannot ask students to live
with. The Gmail code on master stays, unexposed; open decision 3 decides when it returns.

1. **Tagged addresses, one per portal account.** The extension registers the student on each
   portal with `name+<random tag>@<provider>`. Gmail and Outlook.com deliver it to the same
   inbox. One tag per portal *account*, not per application: Sweden's national portal,
   uni-assist, Studielink and UCAS each hold many applications under one account.
2. **The application inbox.** At the first application — never at signup — the student is
   asked for the inbox they will apply with. Recommended: a fresh personal Outlook.com inbox
   used only for applications, created by the student with our guide. One click away: their
   existing personal Gmail or Outlook.com. A university address is allowed (owner,
   2026-09-26: the student has until the account closes to finish every step); the connect
   step checks that the university's tenant lets our app connect, and the delivery test checks
   tagging, since that tenant's admin controls both.
3. **Never read an everyday inbox beyond the filter; read an application inbox whole.**
4. **Never log in to a portal from our servers**, and never disguise traffic (no rotating or
   residential address pools). Official representation (uni-assist's power of attorney,
   UCAS's agent channel) is an open decision, per portal.
5. **Never create mail accounts for students.** Google and Microsoft forbid automated or bulk
   creation, and an account we control is the retired platform mailbox again.
6. **The platform may email the student's everyday address** ("TUM needs a document — see
   your dashboard") as one alert channel. It is our own notification mail, never mail sent
   as the student. Dormant until a company sending domain exists (reminder-ladder design).
7. **The promise to customers** is "you will be alerted in time, and we will know you saw
   it" — never "we catch every email".

## What the research found (2026-09-25, public help pages)

Every one of seven portals emails when something changes, but mostly "log in to see it",
not the content. Some things are posted only in the account, emails can be switched off,
and accepting an offer always happens in the portal.

- universityadmissions.se: results are emailed as a notice; document requests go to the
  account's own inbox — "you'll have to check this account regularly as important
  information will be sent to you there"
  (universityadmissions.se/en/support-centre/supporting-documents/).
- uni-assist: "We will inform you by email as soon as the result is available in your My
  assist account" (uni-assist.de/en/how-to-apply/send-track/status-evaluation-result-admission/).
- Studielink: "You will receive all emails in both your Studielink account and your email
  inbox" (info.studielink.nl/en/how-to-use-studielink).
- TUMonline: admission is emailed and appears in the account; accepting the place is
  portal-only (tum.de/en/studies/application/master/application-master).
- Études en France: decisions are entered in the account, applicants told to log in
  regularly; emails require an opt-in box at account creation
  (rdc.campusfrance.org/les-reponses-des-etablissements-le-choix-definitif).
- UCAS: emails on update; not every provider sends interview invitations via UCAS
  (ucas.com/applying/after-you-apply/tracking-your-ucas-application).
- DreamApply: full-content emails from `no-reply@mail-eu.dreamapply.com`; the applicant can
  unsubscribe (help.dreamapply.com/applicants/).
- No evidence either way on whether any portal accepts `+` in an address.

Quotes were read through a summariser; treat them as near-verbatim.

## 1. One timeline per application

The single record of where an application stands. `Application` already carries the state,
the deadline and the `ApplicationStep` trail; this adds **expectations**: what should happen
next and by when (a confirmation after submission, a decision by an announced date, an
offer-acceptance deadline once it is known). Every input below only updates the timeline;
nothing else decides what the student is told.

**First build: the confirmation expectation only.** Decision and offer-acceptance
expectations need a recorded outcome (admitted, rejected, offer deadline), and none exists
anywhere in the schema (CLAUDE.md, "Derived data": no admission outcome is recorded). They
come with the outcome record, as their own change.

Expected timings start as **platform-wide defaults** (for example, a confirmation within
48 hours of submission). A portal gets its own timing only when real data shows it behaves
differently. Researching every portal up front does not scale.

## 2. How information arrives

Each is a way in; losing any one costs speed, not safety.

- **Mail to a tagged address** — exact: only that portal knows the address, so it names the
  portal account and is strong evidence of the sender. Read from spam and junk too, where
  real portal mail sometimes lands.
- **Mail matched by the filter** (§3), for mail sent to the plain address.
- **The extension reading the portal's own status page** while the student has it open, and
  quietly on browser start when the portal still remembers them. Never a background login.
- **The student's quick answer** on a phone: admitted / rejected / still waiting /
  documents requested, or a screenshot we read. Later, if the pilot shows it is needed.
- **Published decision dates** per portal (Sweden's national results date, Campus France's
  calendar). Later, curated as data arrives.
- **The counsellor**, who can record anything.

## 2a. Tag outcomes per portal

Measured 2026-09-26: some portals keep the tag (uni-assist, universityadmissions.se), some
reject `+` at the form (Studielink), and a portal may accept the tag and strip it before
mailing. Each portal's behaviour is recorded once, as a **tag status** — unknown, keeps,
rejects, strips — and every later registration on that portal uses it.

- **Rejects, seen by the extension.** After filling the tagged address it reads the field
  back, as it does every field: the browser's validity state, `aria-invalid`, or an error
  message beside the field. On a rejection it fills the plain address instead, tells the
  student in the dock, and records "rejects". A portal that only rejects after Submit shows
  the error on the page that comes back; the extension swaps in the plain address and the
  student presses Submit again. The extension still never presses Submit. A dock button
  "use my plain address" remains for an error the extension cannot recognise.
- **Strips, seen at registration.** Registering almost always triggers a verification
  email within minutes, so registration opens a short expectation (about 30 minutes) for
  that portal's first email:
  - it arrives with the tag: "keeps";
  - it arrives untagged: "strips", and its sender domain is learned (per student, rule 2);
  - nothing arrives: the dock asks the student, while still at the screen, whether the email
    came and who sent it. The answer is student-confirmed, so the learned sender may act.
- **Where the status lives.** On the portal, shared by every tenant. Unlike a learned sender
  domain, a wrong status can only cause the safe fallback (plain address plus rule 2), never
  an action, so sharing it cannot be abused.

## 3. Which mail is read

In an **application inbox** (decision 2), everything is read: it holds nothing else. The
student says which kind an inbox is when connecting it, and the connection records it; an
everyday inbox is the default, so a missing answer never widens what is read. For an
application inbox the Gmail sender search (commit f76a5c7) is switched off: every message is
wanted, so a search could only lose some.

In an **everyday inbox**, three rules and nothing else:

1. **Mail to a tagged address we issued** is read, whoever sent it.
2. **Mail from the main domain** of a pack university, funder or known portal company is
   read. Main domain means the registrable domain: `tum.de` covers `noreply.tum.de` and
   `mail.tum.de`; `ox.ac.uk`, not `ac.uk` (`tldextract` is already a dependency). The
   known-portal list is small and curated (`mail-eu.dreamapply.com`, uni-assist, UCAS, …).
   A domain first seen on mail to a tagged address is **learned** for that institution, so
   later mail from it to the plain address is read too. Learning is **per student, and
   read-only until confirmed**: a learned domain lets mail be read and shown, never acted
   on, until the student confirms one message from it belongs to that institution. It is
   never written to the shared `PortalForm.sender_domains`: a tag can leak (a portal breach,
   a forwarded mail), and a scammer's domain learned from it and shared would be read — and
   carry a passing DMARC verdict for its own domain — for every tenant's students. The same
   rule CLAUDE.md sets for tenant-learned `FieldMap`s; promotion to the shared list is a
   human decision, deliberately not built.
3. **Everything else is never listed, fetched or stored.**

**Acting is stricter than reading.** A link is opened or an application's state moved only
when the provider confirms the sender (Gmail's DMARC verdict, as built), or the mail came to
a tagged address and not via spam. Spam-folder mail is shown, never acted on. Either way a
link must still pass the built host check (`actions._verification_url`: https, no userinfo,
no backslash, host in this student's allowlist): a leaked tag makes a mail look like the
portal's, not its links safe.

**Which application.** A tag names a portal account. When that account, or a sender domain,
covers several of the student's applications, the email's content decides; if it does not,
the card asks the student ("Is this about Informatics or Data Science?"). The platform never
guesses and moves the wrong application.

**Classification** stays the reference LLM pattern (data-labelled, `extra="forbid"`, capped,
rate-limited). Jev is a candidate classifier behind its existing gate: no real student text
reaches it before its DPA is filed, and it replaces the incumbent only on a live agreement
test. A message whose classification fails is retried; if it still fails it is shown as
"TUM wrote — open it", never left as a silent unlabelled row.

**Speed.** The hourly sweep is too slow for a verification code the student is waiting for
on a portal. When the extension sees a portal ask the student to check their email, it asks
the server to check that student's mailbox now (within the existing per-student sync
limit). ~~Provider push notifications (Gmail watch, Graph subscriptions) are deferred.~~
Superseded 2026-10-03 for Microsoft by §3a.

## 3a. Push for Microsoft mailboxes (owner decision, 2026-10-03)

The owner asked why the trigger is a clock. Research
(`.context/research/2026-10-03-mailbox-push-notifications.md`, primary sources only) found push is
available at both of our tiers on both providers: Graph lists `Mail.ReadBasic, Mail.Read` for
`message` subscriptions in both the work-or-school and the personal-account delegated columns, and
Gmail's `users.watch` and `history.list` accept `gmail.metadata`. Both vendors also say a
notification can be delayed or dropped, so push is the **trigger**, never the only path.

- **Microsoft first, Gmail later.** Graph needs no new cloud account and covers every pilot
  student (the pilot is Microsoft-only). Gmail push needs a Google Cloud Pub/Sub topic in the OAuth
  client's project and waits for Gmail to leave Testing.
- **One subscription per connection**, `changeType: created` on `me/messages`: it spans Inbox and
  Junk, which sync already reads separately. Basic notifications only -- the payload carries a
  resource id, never content, so nothing new about a student's mail reaches the queue or a log.
- **A notification means "sync this connection now", nothing more.** The sync's timestamp cursor
  makes that self-healing: any sync after any notification, missed or not, reads everything since
  the last one. That is why a lifecycle `missed` event needs no delta query here -- it enqueues the
  same sync.
- **The webhook only enqueues.** Graph wants a 202 within 3 seconds and throttles, then drops, a
  slow endpoint ("Dropped notifications can't be recovered"), and a sync takes seconds to tens of
  seconds. So the web tier verifies the notification and puts the connection id on a new standard
  SQS queue; a new one-task mailbox worker runs the sync. Identifiers only on the queue, like the
  Europass queue.
- **Authenticated by `clientState`**, an HMAC of the connection id under the Django secret key, so
  there is no new secret column; compared in constant time. A notification for an unknown or
  inactive subscription is acknowledged and ignored, so Graph never throttles us over a revoked
  student. Rotating the Django secret key invalidates every `clientState`, and a renewal cannot
  resend it (Graph updates only expiry and URL), so push fails closed until the subscriptions are
  recreated: clear `push_subscription_id` on the Microsoft rows and the next sweep recreates them.
  The sweep's own sync reads the mail meanwhile.
- **Notification URL on the tenant's own verified host** (`TenantDomain`), so
  `HostTenantContextMiddleware` selects the tenant and RLS applies exactly as for any request.
  An agency with no verified domain has no push and stays on the sweep.
- **Lifecycle URL is set at creation** (it cannot be added later). `reauthorizationRequired` and
  `subscriptionRemoved` re-run subscription upkeep, `missed` enqueues a sync.
- **The sweep becomes the backstop: `sync_mailboxes` every 6 hours**, scheduled at last
  (`SyncMailboxesRule`). Each run first keeps every Microsoft connection's subscription alive --
  created if absent, renewed when under two days remain, recreated on a 404 -- then syncs. A
  subscription lasts at most 10,080 minutes, so a renewal that fails has eight more runs before it
  lapses. The six hours is a judgement, not a sourced number: long enough to cost little, short
  enough that a dropped notification costs a working morning, not a day.
- **Push syncs have their own per-student limit** (`mailbox-push-sync`, 60 an hour), so a burst
  of mail cannot use up the six-an-hour budget the extension's "check now" depends on. A push sync
  the limit refuses is acknowledged and left to the next sweep.
- **A revoke or an erasure leaves the subscription to lapse.** Deleting it needs the refresh
  token, and the web tier that serves a revoke is deliberately never allowed to read one. It sends
  only ids to a connection that is no longer ACTIVE, which the webhook ignores, and expires within
  seven days; a reconnect replaces it (the 409 path deletes and recreates).
- Behind `MAILBOX_PUSH_ENABLED`, off by default, so no environment subscribes until it has a
  public HTTPS host and the worker is running.

## 4. The watchdog and alerts

The watchdog raises an alert when a deadline approaches (the built ladder: 14, 7, 3, 1 days
and 6 hours), when an expectation is overdue ("we haven't heard from TUM since you
submitted — open your portal"), or when a portal emails "log in to see it" (the answer is
not in the email, so the alert is "open your TUM portal" and the extension reads it there).

**Only urgent items need acknowledgment.** An urgent alert counts once someone
acknowledges it (`Notification.acknowledged_at`); until then it escalates on a schedule tied
to how close the deadline is: dashboard, then email to the student's everyday address
(decision 6: the address the student signs in to us with, `User.email` — not
`application_email`, which may be the application inbox they rarely open), then the
counsellor (the ladder's existing counsellor task at 1 day and 6 hours,
sent by hand on WhatsApp per the reminder-ladder decision). Everything non-urgent goes into
one daily summary — escalating everything trains students to ignore the one that matters.

## 5. The system watches itself

- Every scheduled job (the mailbox sweep, the reminder ladder, the watchdog) records each
  run; an alarm fires when one goes silent. Today nothing schedules the sweep at all, which
  is a launch blocker already recorded in the mailbox command's docstring.
- A mailbox connection that errors, or has not completed a check within a few hours, alerts
  the student and the counsellor.
- An alert that cannot be delivered falls through to the next channel.

## 6. The application inbox, at the moment of need

At the first application, after payment:

- **"Create your application inbox"** is the recommended path; **"Use my existing inbox
  instead"** is one click below it. Three reasons, one line each: every university reply in
  one place; we only ever see this inbox; it stays yours after graduation.
- We suggest a name (`firstname.lastname.apply@outlook.com`), open Outlook's sign-up in a new
  tab; the student creates it with their own phone and password; then one Connect button.
- **Delivery test:** one platform email to `name+<test tag>@…`; if it arrives in the
  connected inbox, tags are used for that address; if not, the plain address and the filter
  are used, and the student is told why.
- For agency students the counsellor can do this with them in the onboarding call.
- **Why Outlook.com now:** until Google verifies the app (restricted scope plus the annual
  CASA assessment), every Gmail connection shows Google's unverified-app warning and its
  refresh token expires after seven days. Once verified, a fresh Gmail is an equal choice.
- **Measured:** completion rate of this step. If many students abandon it, the existing-inbox
  option becomes the main button.

## Cases the design must handle

- **A portal that rejects or strips the tag.** Handled by "Tag outcomes per portal" below.
- **Applications filed before the student joined.** No tag, possibly an unknown portal. The
  student or counsellor adds each one (portal, programme, deadline) so it gets a timeline;
  an application the platform does not know about cannot be watched, and onboarding asks.
- **The inbox is disconnected, revoked or switched.** Registrations keep pointing at the
  old address. The health check names what depends on it: "your application inbox is
  disconnected — 4 applications use it". Switching inboxes keeps the old connection
  expected until the student confirms each portal's address was changed.
- **Two inboxes at once.** An everyday Gmail used before joining and a new Outlook
  application inbox is ordinary; one active connection per provider (as built) allows it.
- **Acknowledged is not resolved.** An acknowledgment stops that alert escalating; the
  expectation stays open, so the deadline ladder and watchdog keep running until the
  timeline shows it done (document uploaded, decision recorded).
- **Quiet hours.** Watchdog alerts and escalations honour the student's quiet hours
  without exception, exactly as the ladder does (owner decision 2026-09-19, recorded in
  `apps/portals/reminders.py`): deferred, never skipped.
- **Tags are personal data.** A tagged address contains the student's name and identifies
  their account on a portal. It is stored per portal account and redacted on erasure with
  the rest of the student's rows.
- **An idle application inbox.** Microsoft can close a consumer account after a long period
  without sign-in, and our API access may not count as one. Application cycles are usually
  shorter; the dashboard reminds the student to sign in to it now and then. Unmeasured.
- **What the counsellor sees.** Facts and labels ("TUM requested a transcript"), never
  message bodies, on the same terms as every other student row.
- **A student who ignores the application inbox entirely** loses nothing: alerts carry the
  content, and an unacknowledged urgent alert escalates.

## Data it needs

- **`PortalAccount`** (tenant-scoped): the student, the portal host (one account can hold
  many applications), the address registered, and its tag.
- **The portal's tag status** (unknown / keeps / rejects / strips), on the shared portal row
  (§2a).
- **A registration expectation**: the portal's first email within about 30 minutes of
  registering (§2a), alongside the confirmation expectation.
- **A new app, `apps/watch`,** owns expectations, the watchdog, escalation and job
  heartbeats. Not `apps/portals`: `tests/portals/test_boundary.py` forbids any module there
  but `ext_api.py` and `models.py` from naming the submitted state, and the watchdog must.
- **Expectations** on the timeline: what is expected next for an application, by when, and
  when it was met. Defaults platform-wide.
- **`MailboxConnection.kind`**: everyday or application inbox (default everyday).
- **Learned sender domains**, per student: the domain, the portal account it was learned
  from, and whether the student has confirmed it.
- **Job heartbeats**: each scheduled job's last successful run, for the silence alarm.

## Fixes this requires in the mailbox code as built

From the 2026-09-25 review of `apps/mailbox` on master:

- `filter._host_of` keeps `www.`, so a pack link to `www.tum.de` never matches mail from
  `tum.de`. Replace suffix matching on the link's host with registrable-domain matching.
- `PortalForm.sender_domains` has no writer, and gets none here: learning is per student
  (rule 2). The shared list stays hand-curated.
- A classification that fails is never retried (the signal stays unlabelled forever).
- Labels (decision, interview, fee, document request) reach nothing the student sees.
- Microsoft mail never acts (no sender verdict under `Mail.ReadBasic`). On the content tier,
  `Mail.Read` may expose `internetMessageHeaders`; whether Outlook's authentication header is
  usable needs one real Outlook mailbox to measure. Tagged-address mail acts regardless.
- The first-sync start and the Gmail sender search already landed (commit f76a5c7).

## Checks before trusting the design

- **Gmail sender search and subdomains.** Whether `from:tum.de` matches `x@mail.tum.de`. The
  owner can check in their own Gmail in a minute.
- **Plus addressing per portal.** Tested live at the first real registration on each portal
  and recorded on the portal; the fallback loses nothing against today. Registering a test
  account on a real portal may itself touch that portal's terms — the owner decides per
  portal.
- **"Did we miss anything?"** For the first pilot students, a button reports any university
  email the dashboard did not show. That measures misses instead of assuming them.

### Results so far (2026-09-26)

- **Gmail sender search, web box: passed.** The owner searched `from:google.com` in a real
  Gmail account and got mail from `no-reply@accounts.google.com`, so a domain search covers
  its subdomains there. **The API is not proven identical:** the `messages.list` reference
  says `q` "Supports the same query format as the Gmail search box", while the filtering
  guide says "most of the same advanced search syntax" and names one divergence (alias
  expansion). Google documents subdomain matching nowhere. Residual check: on the first real
  everyday-Gmail connection, compare the searched listing with an unfiltered one once.
- **Outlook.com plus addressing: passed, measured 2026-09-26.** No official Microsoft consumer
  page documents it and secondary sources contradict each other, so the owner tested it: mail
  to `name+test@outlook.com` on a personal account arrived with the tag intact in To:. The
  per-student delivery test (§6) stays, in case Microsoft changes this.
- **Microsoft 365, measured 2026-09-26:** mail to `name+test@` on a real university tenant
  (MX `*.mail.protection.outlook.com`) was delivered with the tag intact in To:. This is a
  university Microsoft 365 account; personal Outlook.com was measured separately (above).
- **Microsoft 365 tenants:** plus addressing is on by default and an admin can turn it off
  (`Set-OrganizationConfig -DisablePlusAddressInRecipients $true`,
  learn.microsoft.com, "Plus addressing in Exchange Online"). **Google Workspace:** community
  sources say it cannot be turned off; no official page found.
- **Portals and `+`:** research found no documentation either way, and no portal that
  requires an institutional address or forbids aliases. **Measured by the owner, 2026-09-26,
  registering with `name+test@outlook.com`:** uni-assist accepted it and its verification email
  arrived with the tag intact in To:; universityadmissions.se accepted it; **Studielink rejected it** at the form ("No valid
  email address has been provided") — its validation omits `+`. Studielink accounts therefore
  use the plain address and rule 2 (sender domain). The other portals are still untested and
  are measured at their first real registration.

## Build order

1. The dashboard surface alerts appear on (none exists yet).
2. Expectations, the watchdog, acknowledgment and escalation, self-monitoring. These protect
   a student with no mailbox connected at all.
3. The mailbox fixes above, tagged addresses, the delivery test, the application-inbox step,
   the extension-triggered check.
4. Later, only if the pilot shows the need: phone push, the student's quick answer and
   screenshot, curated decision calendars, Gmail push (Microsoft push is §3a, built).

## Rejected, and why

- **Logging in to portals with the student's password.** Several portals' terms forbid
  sharing a login (universityadmissions.se: "You are the only person who may use your
  personal user account"; TUMonline's IT policy §4(3a)); a breach lands on the student's
  application. Holding passwords makes us the thing that leaks. Two-step codes and CAPTCHAs
  would stop it anyway.
- **Rotating or residential addresses to avoid detection.** Removes one signal (a shared
  server address) and leaves new-device alerts, two-step codes and session conflicts; does
  not change the terms breach; residential pools are largely sourced from people's devices
  without real consent. CLAUDE.md already bars them.
- **Reading the whole everyday inbox (with Jev or any model).** Data minimisation argues
  against it when a narrower method gives the same reliability; Google's Limited Use rules
  restrict passing mail to other companies; and it still cannot see portal-only updates.
- **Asking the student to keep a portal tab open.** Portals log out within the hour; laptops
  sleep. Replaced by well-timed prompts.
- **Creating Gmail or Outlook accounts for students.** Decision 5.

## Open decisions for the owner

1. **Direct-to-student customers have no counsellor**, so escalation ends at the student.
   Options: our support team, a backup contact the student names, or a weaker promise. Not
   needed for the agency pilot; decide before direct sales.
2. **Official representation** (uni-assist power of attorney, UCAS agent channel) per portal.
3. **Google verification timing** — it ends the weekly Gmail reconnect and the warning.
4. **Test accounts on real portals** for the plus-addressing check, per portal.
