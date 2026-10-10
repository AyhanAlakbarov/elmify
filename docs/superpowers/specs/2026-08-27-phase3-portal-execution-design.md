# Phase 3 Portal Execution

> **Superseded in part, 2026-09-15** by `2026-09-15-glass-box-copilot-design.md`. The server-side
> browser, platform-managed credentials, reauthentication, session persistence, the CAPTCHA
> service and the pause/hand-off/resume question are retired: filling runs as a browser extension in
> the student's own session and the student submits. The field-map model, the typed-values-only
> action allowlist, read-back, the escalation taxonomy and the audit-trail contract stand and are
> reused. Read this document for those, not for where the browser runs.

## Goal

Complete and submit third-party university and scholarship applications from the verified student
profile and the approved application pack, at a cost per application that does not scale with the
number of students, without evading portal access controls.

Scope is Section 5.1 (authority), 5.2 (portal execution) and the portal-exception half of 5.4.
Application-fee payment (5.3) is excluded: Section 10 lists payment-provider support and the legal
treatment of held student funds as unresolved. Monitoring and document requests (5.6) and interview
services (Phase 4) are excluded.

## Probe findings

A throwaway probe against `stagehand==4.0.2` established the following by execution, not documentation.

1. `Stagehand.create()` succeeds against a local Chrome with no Browserbase account and no API key.
   The engine ships as a bundled Chrome extension driven over CDP; its service worker references only
   LLM provider hosts, and no Stagehand or Browserbase host. Orchestration is local.
2. Chrome version is load-bearing. System Chrome 147 fails with
   `CDP command failed: Extensions.loadUnpacked: Method not available`. Chrome gates that method to
   pipe transport, and `--remote-debugging-pipe` then breaks Stagehand's port-based connect, leaving
   no working combination. Playwright's bundled Chrome for Testing 151 works. The browser must be pinned.
3. Extensions do not load in `headless_shell`. Production requires headful Chrome under Xvfb.
4. The Python SDK has no `cacheDir`. Its `cache` parameter is `bool | {threshold: int}` and the cache
   lives in the extension service worker with no `chrome.storage` or `indexedDB` writes. It does not
   survive a process restart and is not shared across tasks. Stagehand's own caching is unusable for a
   multi-task deployment.
5. `observe()` returns `list[Action]`, and `ActionInput` is plain serialisable JSON:
   `{selector, description, method?, arguments?}`. `act()` accepts that object back. This is a better
   primitive than the cache, because the store becomes ours: tenant-visible, versioned, and reviewable.
6. `Variables` substitutes values at execution time, so a stored action carries no student data.
7. `solveCaptchas`, `captchaImageSelector`, `captchaInputSelector`, `advancedStealth` and `fingerprint`
   exist only in `BrowserbaseBrowserSettings` — Browserbase Cloud session settings with no code path on
   the self-hosted browser. Self-hosting forgoes them; the resolution service is integrated directly instead.

## Design

1. New app `apps/portals`. Browser automation lives there and nowhere else;
   `apps/concierge/services.py` stays human-recorded-facts only.
2. Session engine launches pinned Chrome for Testing under Xvfb, routed through
   `apps/research/egress.py::LocalEgressProxy`, with a per-application `user_data_dir` and
   `preserve_user_data_dir=True` so an interrupted session survives for resumption.
3. Learn pass: `observe()` maps one form version to a `FieldMap` of `ActionInput` records. It makes
   one LLM call per form field, once per form version -- an N-field form costs N calls the first time
   it is seen and nothing thereafter, amortised across every student who later applies to it. The
   budget is metered per `observe()` call, not per learn pass, and rate-limited per tenant through
   `apps/ratelimit.py::rate_limited`. Student values reach `observe()` only as Stagehand variable
   *names*, so the returned action carries a `%value%` placeholder rather than a literal.
4. Replay pass: `act(stored_action, variables={...})` fills every subsequent student's application
   with no LLM call at all. This is the cost thesis and it is asserted by test.
5. Recovery is autonomous by default. A selector miss triggers a scoped re-learn of the affected page
   and execution continues; an expired session is reauthenticated with platform-managed credentials;
   transient failures retry with backoff. Each recovery is recorded and surfaced for post-hoc review.
   Nothing blocks on that review.
6. Section 5.2's "create review tasks rather than guessing" is satisfied by recording, not by stopping.
   Stagehand's own `self_heal` stays off, because it re-infers silently and leaves no artifact; our
   re-learn produces a new `FieldMap` version that is diffable against the one it replaced. The rule
   being honoured is that a changed form leaves evidence, not that a human must approve before filling.
7. Escalation is a notification, never a blocking queue. It carries the specific missing fact or
   required action, and it happens only for the cases in "Escalation" below.
8. Pauses reuse the existing `RoadmapItem` stages — `PORTAL_EXCEPTION` for portal challenges,
   `PERSONAL_ACTION` for non-delegable steps — which already satisfy Section 5.2's dashboard requirement.
9. `apps/research/queue.py` is parameterised over its message type rather than duplicated. The existing
   research tests guard the refactor.

## Data model

`PortalForm` and `FieldMap` are platform-shared, not tenant-scoped. A field map is derived from a
public form, contains no PII, and falls under Section 9's "official program evidence as shared platform
intelligence". Scoping it per tenant would multiply the learn cost by tenant count for no isolation gain,
because there is nothing tenant-specific in it. This is a deliberate departure from the Section 9
isolation default and is the single design decision most worth revisiting if a tenant objects.

`Application`, `ApplicationStep` and every record carrying student data are tenant-scoped through
`TenantScopedModel`.

`Application` states: `PREPARING`, `READY_TO_SUBMIT`, `SUBMITTED`, `CONFIRMED`, plus
`BLOCKED_MISSING_FACT`, `BLOCKED_PERSONAL_ACTION`, `BLOCKED_CHALLENGE` and `BLOCKED_PORTAL_ERROR`.

There is deliberately no paused state for a site change or an expired session. Both recover
autonomously and are recorded as `RecoveryEvent` rows rather than halting the application. A
`RecoveryEvent` names the portal, the page, the `FieldMap` version replaced and the one that replaced
it, so a form that has drifted is visible per portal without any application waiting on a human.

`ApplicationStep` records the Section 5.5 audit trail: profile and document versions used, form answers,
uploads, agent and consultant actions, submission time and confirmation, failures and retries. Actions
and evidence are recorded; model chain-of-thought is not.

## Submission authority

Under `counselor-submit` the agent submits. Under `student-submit` it stops at `READY_TO_SUBMIT`,
except for the Section 5.1 rule that an application still unsubmitted 48 hours before its deadline is
submitted under the same one-time authority, recorded as an approval event and notified to the student.

Submission is gated on: the authority mode, counselor approval of every document version under P1-14,
and a read-back assertion that every filled field equals the verified profile value. The read-back runs
against the rendered page, not against what the agent believes it typed.

## Challenge resolution

`CaptchaResolver` is a protocol with two implementations, both required by Section 2's rule that CAPTCHA
is delegable application work.

- `ServiceResolver` — integrated resolution service, provider-pluggable behind one adapter interface,
  enabled by default. Requires an operator-supplied provider credential.
- `ConsultantResolver` — reached only after the service has been tried and has failed or cannot run.
  Preserves the session, creates a scoped `RoadmapItem(PORTAL_EXCEPTION)`, detects completion and
  resumes at the paused step without repeating completed work.

The per-portal approval record is retained as an audit artifact under Section 5.5. It does not block
execution. Section 2's current wording permits the service "only where lawful and permitted by portal
terms"; shipping it enabled by default is a deliberate operator decision that the requirements text
should be updated to match, and Section 10's open portal-terms blocker still applies.

Detection is explicit and deterministic: known challenge containers and scripts are matched by DOM
query, plus a stall heuristic. Detection never guesses. The service is retried with backoff up to a
bounded attempt count; only exhaustion of those attempts reaches a consultant.

The adapter interface takes a challenge type, a site key and a page URL, and returns a token or a
failure. One concrete provider adapter ships; the provider is named in configuration rather than in
code, and an absent or rejected credential is a `ConsultantResolver` fallback, not a crash.

Fingerprint evasion, `advancedStealth`, spoofed navigator properties, and rotating or residential
proxies are out of scope under Section 3.4. This is a capability boundary enforced by test, not a
configuration default.

## Escalation

A human is notified only when the agent lacks information or authority that no software possesses.
Section 5.4 itemises these; they are the whole of the escalation surface.

| Trigger | Why automation cannot resolve it |
| --- | --- |
| A required field has no corresponding verified fact | The agent must not invent data for an attested form |
| Identity verification, legally binding signature, personal attestation | The portal requires a specific human |
| Applicant-specific MFA | The credential reaches the student's own device |
| A challenge the resolution service cannot solve | Outside what any resolution service handles |
| An ambiguous question or a low-confidence decision | Guessing changes what the application asserts |
| A hard portal error — duplicate application, eligibility mismatch, passed deadline | Requires a judgment about what to do next |

Everything else recovers on its own. Escalation delivers the specific missing fact or required action
through the notification channel; it does not create work that other applications wait behind.

Section 5.4's targets — at least 90% autonomous steps, under 10% consultant intervention, under 2%
student portal action — are targets, not measurements. The real rate is unknown until this runs against
live portals and will vary widely by portal. Intervention rate is therefore recorded per portal and
reported, so an expensive portal is visible and can be improved or dropped on evidence.

## Security

Portal page content reaching `observe()` is untrusted input to an LLM. It follows the
`apps/research/extraction.py` pattern: page content is labelled as data rather than instructions, output
is constrained to the `ActionInput` schema, and output tokens are capped. Page content never determines
control flow — a page cannot cause a submission, a navigation off-domain, or a change of student data.

Student values reach the browser only through `Variables` at act time, so no profile value is written to
a `FieldMap` and none is required in an LLM prompt.

A `user_data_dir` holds live portal session cookies. It is encrypted at rest, tenant-isolated, and
expired on a TTL.

`LocalEgressProxy` currently enforces a 30-second tunnel deadline and a 10 MB transfer cap, correct for
research fetches and too tight for an authenticated portal session with document uploads. Both become
configurable, with the present values kept as defaults so the research pipeline is unchanged.

## Cost

A conventional browser agent re-sends serialised page state to the model on every step, so cost scales
with applications. At roughly 60 steps and ~15k input tokens per step, one application costs about
$5.25 on Claude Opus 5 and about $2.10 on Sonnet 5, before retries.

Learn-once removes that scaling. The LLM runs once per form version -- one call per field on that one
pass -- not once per application, and the replay pass makes no model call at all. Amortised over the students applying to one program, cost per
application tends toward the browser compute alone — browser-hours are $0.02 and immaterial next to
tokens. Self-hosting avoids both the 1.2x hosted-token markup and the 0.2x orchestration fee.

The conventional-agent figures above remain estimates carried from published reports, not
measurements.

### First keyed measurement (2026-08-27)

`test_learn_then_replay_against_real_chrome` run with a live credential on `claude-opus-4-8`, against
the two-field `file://` fixture:

| | prompt | completion | wall |
| --- | --- | --- | --- |
| `observe()`, per field | 1323 | 57–59 | 2.1–3.4s |
| Learn pass, 2 fields | 2646 | 116 | — |
| Replay pass | 0 | 0 | — |

At $5/$25 per MTok that is $0.0081 per field, $0.0161 for this form, and $0.00 for every replay after
it. The zero-LLM replay is confirmed by measurement, not only by assertion.

### Prompt caching does not apply (settled 2026-08-27)

A client-side LLM callback captured what `observe()` actually sends. Per call:

| component | size | varies? |
| --- | --- | --- |
| `system_prompt` | 1707 chars | no |
| `response_format` (JSON schema) | 1934 chars | no |
| user message | 239 chars | yes |

The user message is `instruction: <varies>` followed by `Accessibility Tree: <page>` — **the varying
instruction precedes the page content in the same message.** Caching is a strict prefix match, so the
page sits downstream of the first differing byte and cannot be cached. The stable head that does
precede it (system + schema, ~900 tokens) is below the ~1024-token minimum cacheable prefix, so
caching it is a no-op. `LLMUsage.cached_input_tokens` exists in the Stagehand wire model and is always
0 for this reason.

**Write the cost model with no caching assumption.**

### What the learn pass actually costs (measured 2026-08-27)

Measured against a 36-field fixture carrying realistic page furniture — cookie banner, header nav,
breadcrumb, fieldsets, mixed input types, footer — so the accessibility tree is representative rather
than a toy.

The tree is ~12,100 chars, **77% of every `observe()` call**. `N x observe` re-sends the whole tree
once per field, so the page, not the boilerplate, is what makes this shape expensive. (On the earlier
two-field fixture the boilerplate dominated; that was an artefact of a six-line page and should not be
generalised.)

| shape | calls | prompt | completion | cost @ $5/$25 | mapping accuracy |
| --- | --- | --- | --- | --- | --- |
| `N x observe` (as built) | 36 | ~141,800 | ~2,100 | **$0.761** | — |
| `1 x extract`, flat schema | 1 | 8,555 | 428 | **$0.054** | **36/36** |

**~14x cheaper per form version, at perfect accuracy on this form.** Amortised across every student who
replays it, either figure is small; the ratio matters only for how many form versions can be learned
per unit of spend.

### The one open question before `extract` can replace `observe`

`extract` returns *accessibility node references* (`[0-147]`). `act()` needs an actionable selector,
which `observe` yields because Stagehand resolves the chosen node internally. `backend_node_id`
plumbing exists in `webmcp.py` and the wire models, so a resolution path is plausible — but it is
unproven. **Plan 2 should cost the learn pass on `N x observe`, the shape that ships and works, and
carry `1 x extract` as a measured optimisation whose only blocker is node-ref resolution.**

Two implementation notes for whoever takes it:

- A `dict[str, str]` extraction schema silently returns nothing. Two runs came back 0/36 with ~50
  completion tokens, logged as "Extraction incomplete after processing all data" rather than an error.
  A flat schema — one string property per field — works. The failure mode looks like a capability
  limit and is not one.
- `Stagehand.create(model=...)` also accepts a callback
  (`Callable[[LLMGenerateInput], Awaitable[LLMGenerateOutput]]`), which hands over the whole Anthropic
  request. That is the escape hatch from the model-name allowlist currently forcing `claude-opus-4-8`.

Neither is required for the architecture to hold: it depends only on the learn pass being amortised,
which the zero-LLM-replay test asserts directly.

## Verification

- Learn-then-replay against a locally served fixture form asserts zero LLM calls on the replay pass.
- A `FieldMap` never contains any value present in the student profile.
- Challenge detection matches saved challenge markup and does not match ordinary form markup.
- `ServiceResolver` failure falls back to `ConsultantResolver` and preserves completed form state.
- A fixture form whose selectors change mid-run re-learns and completes without escalating, and emits
  a `RecoveryEvent` naming both `FieldMap` versions.
- An expired session reauthenticates and resumes at the last confirmed step, repeating no completed step.
- Each row of the Escalation table escalates, and nothing outside that table does.
- Every `Application` state transition, including each blocked and resume path, round-trips.
- Read-back assertion fails a submission when a rendered field diverges from the verified profile.
- `tests/concierge/test_roadmap.py` continues to assert `apps/concierge/services.py` performs no
  automation, and a mirrored test asserts `apps/portals` imports no fingerprint-evasion or
  proxy-rotation library.
- Existing research queue tests pass unchanged after the queue refactor.

## Safety

Submission is the only irreversible action and is gated on authority mode, counselor document approval
and a rendered-page read-back. Payment is out of scope entirely, so no code in this phase can move
money. Egress stays inside the validated proxy, which continues to block private-network targets.
