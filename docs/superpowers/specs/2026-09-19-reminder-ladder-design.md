# The reminder ladder

Design, 2026-09-19. Plan 5 of the glass-box co-pilot, and the last piece of
`2026-09-15-glass-box-copilot-design.md` §8 that is not built.

§8 fixed the cadence — 14 days, 7 days, 3 days, 1 day and 6 hours before the deadline,
stopping the moment the application is submitted. This document records what §8 left
open, three owner decisions taken on 2026-09-19 that change it, and the four things in
this codebase that the ladder needs and does not have.

## What §8 says, and where this departs from it

| §8 | Here | Why |
|---|---|---|
| "At 3 days a counselor task opens" | **At 1 day and 6 hours** | Owner decision 2026-09-19. Three days out an automated reminder still has room to work; inside 24 hours it does not, and that is where a human is worth spending. |
| counselor task unspecified | **"Message this student on WhatsApp"** | Owner decision. Email reaches this cohort poorly; WhatsApp reaches it. The counselor sends it by hand from their own WhatsApp. |
| "and by notification mail" | Built, **dormant** | No company domain exists yet (owner, 2026-09-19). The code ships; production sending is a config change, not a code change. |
| — | **Automatic WhatsApp is deliberately not built** | Owner decision. Recorded below with what it would need, so the next session does not re-derive it. |

Everything else in §8 stands: the cadence, the dropped 1-hour rung ("a failed upload
cannot be recovered in an hour"), stopping at Submitted, and quiet hours.

**Not in scope, and it was raised and rejected on 2026-09-19.** Submitting an
application on the student's behalf when a deadline is about to pass. It reverses the
glass-box premise that the student always presses Submit, it is the one act every portal
in §9's seven-portal sample prohibits, and it would mean rebuilding the portal-credential
store this project spent three plans retiring. The sanctioned routes — uni-assist's power
of attorney, UCAS's agent channel — remain the only way this could ever be done, per
portal, with the student's signed authorization, and that is a separate decision nobody
has taken.

## The sweep

A management command, `send_due_reminders`, run on a schedule.

**Hourly, not daily.** The 6-hour rung cannot be hit by a daily job, and a 3-hour sweep
would still miss it by up to three hours on a rung whose whole purpose is that it is the
last one. `rate(1 hour)`.

**One tenant scope per agency, one transaction per reminder.** Copy
`execute_due_erasures.py` exactly, including both traps its comments record:
`tenant_scope` refuses to switch tenants, so the scope is per agency inside the loop and
never held across it; and `set_local_tenant` issues `SET LOCAL`, so it belongs inside
*every* transaction. Without the second, the scan is legal SQL that returns zero rows
under RLS — the command finds nothing, exits 0, and no reminder is ever sent. No test in
this repository can catch that, because the test role bypasses RLS.

One transaction per reminder rather than one per agency, for the same reason erasure does
it: a failure on the fortieth student must not roll back the thirty-nine reminders
already recorded as sent, or they all re-send on the next sweep.

**What it scans.** `portals.Application` rows with a non-null `deadline` whose state is
not `SUBMITTED`, `CONFIRMED`, or any `BLOCKED_*` value. A blocked application is waiting
on a human through `escalation.py`; reminding the student to hurry is noise pointed at
someone who cannot act.

**Deadline source is `Application.deadline`, not `RoadmapItem.deadline`.** §8 named the
latter, but `Application` is where the real, portal-stated date lives, beside the
`deadline_timezone` the ladder needs — plan 1 added both columns naming this ladder as
the reason. `RoadmapItem` is what the notification *points at*, unchanged.

## A reminder fires once

`ReminderSent`: tenant-scoped, `application` FK, `rung` (a `TextChoices` field over the
five — `D14`, `D7`, `D3`, `D1`, `H6`, never a raw integer of hours, so a cadence change
cannot silently re-key existing rows), `sent_at`, unique on `(tenant, application, rung)`.

Without it every sweep re-sends every rung that is still in the past — five reminders an
hour, forever, which is worse than none. The unique constraint is the mechanism, not a
`.exists()` check: the check races two sweeps against each other, the constraint cannot.

It doubles as the record of what was sent when, which is what makes "did the student
actually get warned" answerable after a missed deadline.

## Quiet hours, and the field this codebase does not have

§8 requires reminders to respect the student's quiet hours. **Nothing in this codebase
stores a student's timezone** — `Application.deadline_timezone` is the *portal's*, and
`Membership` has no zone at all. Quiet hours without it are unimplementable: 22:00 in
whose evening?

So two fields on `Membership`:

- `timezone` (IANA name, blank when unknown)
- `quiet_hours_start` / `quiet_hours_end` (nullable `TimeField`s)

**A quiet window normally crosses midnight**, and that is the case to write the test
against: `22:00`–`07:00` means "inside" is `t >= start or t <= end`, not `start <= t <= end`,
which is empty for every window anyone would actually set. The non-wrapping window
(`13:00`–`14:00`) is the unusual one.

**Quiet hours defer; they never skip.** A rung that comes due at 02:00 fires when the
window ends. Skipping it loses the reminder entirely, which inverts the feature: the
student is not disturbed *and* not reminded. Deferral is why `ReminderSent` is keyed on
the rung rather than written speculatively at schedule time — the rung stays unsent and
the next sweep inside waking hours picks it up.

**This applies without exception, including to H6.** Owner decision, 2026-09-19: if a
student's quiet window covers the moment their deadline itself passes, the 6-hour rung —
the last one — can lose its only remaining chance to fire and simply never go out. That
was raised explicitly and accepted: quiet hours are honoured unconditionally, not "unless
it's the last one" or "unless it's urgent." Do not special-case H6 to bypass the window;
that question has been asked and answered.

A student with no timezone gets no quiet hours and every rung fires on time. Degrading
the other way — holding reminders until a zone is known — silently drops them.

**Both fields are student-reachable, so both are classified in
`apps/audit/redaction.py` in the same change that adds them**, per the rule
`tests/audit/test_redaction_classification.py` enforces. A quiet window and a timezone
are personal data about when someone sleeps and where they live: `REDACT`.

## Three channels

The sweep decides *who needs which rung*. Each channel is a plain function it calls; there
is no channel registry, no plugin interface, no `NotificationChannel` base class. Three
concrete calls behind one `if` each is smaller than the abstraction that would unify them.

**Dashboard — every rung.** A `concierge.Notification` against the student's
`RoadmapItem`, which is the notification centre §8 names. Already built; nothing new.

**Email — every rung, dormant.** Django's own mail framework, so dev and tests use the
in-memory backend and no domain is needed to test it. Production is `EMAIL_BACKEND` plus
SES credentials, both absent today; with them absent the channel logs that it was skipped
rather than failing the sweep.

Recipient is `Membership.application_email` — never `user.email`, which that field's own
docstring reserves for signup and login. Where `application_email` is blank the student
has no confirmed address, the email rung is skipped, and the dashboard rung still fires.
No fallback between the two addresses, matching the rule already written there.

**Counselor task — the 1-day and 6-hour rungs only.** A `Notification` whose recipient is
the counselor from the student's active `CounselorAssignment`, saying to message this
student on WhatsApp now. `Notification.recipient` and `roadmap_item` are already separate
fields precisely so a notification can be *about* one person and *to* another — the
escalation path uses the same shape.

**A direct-to-student account has no counselor**, so `CounselorAssignment` yields nothing
and no task is created; that student's 1-day and 6-hour rungs are dashboard and email
only. Stated here because silently creating nothing looks identical to a bug.

## Automatic WhatsApp: deliberately not built

Owner decision, 2026-09-19: the counselor sends it by hand for now. What building it
later actually requires, so nobody re-discovers it:

- A WhatsApp Business account on Meta's Cloud API, a dedicated number, and **business
  verification against a registered legal entity** — the real blocker, and a longer one
  than the email domain.
- **Pre-approved message templates.** A business-initiated message outside an open
  conversation window must be a template Meta approved; a deadline reminder is a UTILITY
  template. No freestyle text.
- **Recorded opt-in, which is Meta policy and not optional** — captured at onboarding,
  with when and where. Sending without it gets the number throttled or banned, which
  costs the channel for every student at once.
- The phone number is personal data: a `REDACT` classification and the erasure path, like
  every other student field here.

The code itself is a POST with a template name and two variables. The paperwork is the
project.

## AWS

One `AWS::Events::Rule`, modelled on `EuropassCanaryRule` in `infra/template.yaml`: ECS
`RunTask` against `WorkerTaskDefinition`, `LaunchType: FARGATE`, worker subnets and
`WorkerSecurityGroup`, `ScheduleExpression: "rate(1 hour)"`, overriding the command to
`python manage.py send_due_reminders`.

Nothing else. No SES resource is added while no domain is verified — a CloudFormation
resource pointing at an unverified identity fails the stack, and the channel is designed
to be dormant without it.

Worth noting against the erasure precedent: that rule was deferred because nothing was
deployed to run it against, and the deferral is now a documented deployment blocker. This
one ships *with* its rule for that reason — an hourly sweep nothing invokes is a ladder
that silently never fires, and every screen would say the right thing.

## Testing

The parts worth pinning, and the ones that are hard to see:

- Each rung fires once and only once across repeated sweeps — the constraint, not the
  check.
- A rung due inside quiet hours is not sent, and *is* sent on the first sweep after the
  window ends. The deferral is the whole feature; a test that only asserts silence during
  quiet hours passes on a version that drops the reminder forever.
- Reminders stop at `SUBMITTED` and at `CONFIRMED`, and never fire for a `BLOCKED_*`
  application.
- A student with no counselor gets no counselor task and still gets their own rungs.
- A blank `application_email` skips email and keeps the dashboard notification.
- The RLS trap: the sweep runs under the `rls_enforced_orm` fixture, not only the
  bypassing test role. A sweep that scans without `set_local_tenant` returns zero rows in
  production and passes every ordinary test.

## Deliberately not built

- Automatic WhatsApp (above).
- "Repeat until acknowledged" beyond the five rungs. §4.5 names it; the ladder is the
  implementation, and a reminder that re-fires until a student clicks it is a different
  feature with its own failure mode.
- Per-student channel preferences. One switch per student ("don't email me") is a
  settings surface nobody has asked for; quiet hours already carry the "stop bothering me
  at night" case.
- Any reminder for a deadline the catalog does not hold. Most applications enter the
  pipeline with `deadline` null, by design (2026-09-15 discovery audit), and those simply
  do not appear in the sweep.
