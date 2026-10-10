# Europass: render it on europa.eu, by driving the editor

**Status:** RETIRED 2026-08-25, unimplemented. Its central premise was wrong.
**Retired in favour of:** `2026-08-25-europass-api-render-design.md`, which it had superseded.
**Kept because:** everything below §1 is a sound contingency design, and the evidence
in "Why this was retired" is the more useful half of the document.

## Why this was retired

This spec argued for browser automation from one claim: *"europa.eu renders the
visible PDF in the browser, not on the server. No server endpoint returns a rendered
CV."* That claim is false, and the blank CV that motivated it had two ordinary causes.

**The server renderer works.** `/office/download/pdf/{token}` returns a complete,
multi-section Europass PDF — education, the CEFR grid, section headings, cairo-produced,
`attachment.xml` intact. It was returning a near-empty one because we asked it to:

1. **The profile was never stored.** `POST /eprofile/cv` seeds a CV from
   `personalInformation`'s name/email and the `template` block and silently discards
   every content section. `PUT /eprofile/cv/{id}` is the write path. The pipeline
   never issued one, so the renderer converted an empty document, correctly.
2. **`preference.profileStructure` names the sections to print, and we sent `[]`.**

Fixed in `ac499e1`; a live canary now renders 434 characters of text where it rendered
54.

## Two claims in the retired text that were wrong, and how

Both are worth keeping, because both were arrived at honestly and both misled.

**"profileStructure was tested in four shapes with byte-identical output; it is not
the mechanism."** The shapes were fine. The experiment was confounded by cause (1):
with no content stored server-side, *every* value of `profileStructure` renders the
same empty page. The test could not have produced a difference whatever the answer,
so its null result carried no information. It was recorded as settled and marked
do-not-redo, which is what kept the real mechanism hidden for a full session.

**"Importing our API-generated PDF restores only the name."** True, and correctly
noted at the time as inconclusive because the PDF was itself defective. It was
nonetheless read as corroboration. The import restored exactly what the document
contained.

The shared failure is generalising a mechanism from an observation taken inside a
system already broken somewhere upstream. A negative result from an experiment that
could not have gone the other way is not evidence.

## What survives

- **Verification: a rendered CV must contain every section's content.** Now enforced
  by `europass_canary`, which fails unless the degree, the institution and the
  language are on the page. Provenance proves the document is Europass; only this
  proves it says anything.
- **No fallback, ever** (§4) — unchanged and reaffirmed.
- **The flow must be asynchronous** (§5) — and more so than this spec knew: the
  download itself is async, answering 204 before the PDF exists.
- **Data protection** — unchanged and unresolved. Guest CVs holding real student data
  are created on europa.eu and never deleted. The retention question in the unsent
  `EMPL-ELM-SUPPORT@ec.europa.eu` email is the one that does not shrink with volume.
- **Nothing in a Europass PDF is cryptographically verifiable.** Three PDFs, one from
  their own client, carry no signature, certificate, hash or encryption. Independent
  of which path renders.

## When to revive this

Only on evidence that the API path is closed — the render endpoint withdrawn, or
authentication introduced that guest sessions cannot satisfy. Cost, brittleness and
ToS posture are all worse here; that was true when it was written and is not the
reason it was retired.

---

*Everything below is the retired design, preserved unedited as the contingency.*

## Decisions

### 1. Keep the pipeline. Replace the mechanism.

The queue, the single pinned worker, the fixed pacing, the global circuit breaker,
the content-hash cache and the canary are the correct architecture for long-running,
rate-sensitive, externally fragile work that must not block a web request. That
describes browser automation more accurately than it described the HTTP client.

**Replaced:** `apps/documents/europass.py` — the HTTP client, its payload mapper, its
provenance assertion, and its tests. A browser driver takes its place behind the same
interface `render_and_store` already calls.

**Kept unchanged:** `europass_queue.py`, `europass_worker.py`, `europass_render.py`,
`run_europass_worker.py`, `EuropassRenderCache`, `EuropassCircuit`, migrations
`0010`/`0011`, and the infra — queue, DLQ, pinned worker service, alarms, canary
schedule, IAM.

The canary becomes *more* valuable, not less: it now watches a UI, which breaks more
often and more silently than an API.

### 2. Data entry: import, not form-filling — to be proven first

Two ways to get a student's data into the editor:

- **Form-filling.** Drive every field. Many selectors, maximum brittleness. My
  session hit wizard resets, dialog interception, a "Resume last CV" prompt and
  `beforeunload` dialogs — each an opportunity for a selector to break.
- **Import.** Generate a Europass XML, upload it via *Start from Europass CV*, then
  Download. Three interactions instead of dozens.

Import is strongly preferred and **is the first thing implementation must prove.**
Our API-generated PDF imported with only the name restored — but that PDF was itself
defective, so the test is inconclusive. A correctly-formed Europass XML may import
cleanly. If it does, brittleness drops by an order of magnitude.

If import cannot be made to work, form-filling is the fallback, and the brittleness
budget in §5 tightens accordingly.

### 3. The emblem question dissolves

It is no longer ours to decide. Their renderer produces the document, and the
editor's *Customise your CV* panel exposes *Show logo on* alongside template, colour,
text size and page number. We choose a setting; we do not reproduce an emblem.
Default: logo on, matching the editor's own default and the user's stated preference.

The EU emblem third-party-use exposure recorded in the previous revision no longer
applies — the document is genuinely produced through europa.eu.

### 4. No fallback

Unchanged from the pipeline spec and reaffirmed. No path may substitute a
non-Europass artefact when europa.eu is unavailable. An outage is a delay. The
circuit breaker pauses; the queue holds; the student waits. A silently substituted
CV is worse than a late one.

### 5. Timing and the student flow

A browser render is 30–60 seconds. This is why the queue stays. The student-facing
surface must show the CV as pending and notify on completion — that surface does not
exist yet and remains out of scope, but this spec constrains it: **the flow must be
asynchronous.** Any design that blocks a request on a Europass render is wrong.

Pacing becomes partly self-enforcing: one worker at 30–60 s/render tops out near
1–2 per minute, far below the 30/minute ceiling. `_INTER_CALL_DELAY_SECONDS` stays
anyway — it costs nothing and it is the only explicit rate control.

## Security

Running a headless browser that executes third-party JavaScript is a materially
different posture from making HTTP calls, and the worker is not currently built for
it. Today `EuropassWorkerTaskRole` holds `sqs:ReceiveMessage`/`DeleteMessage` on its
own queue and `s3:GetObject`/`PutObject` on `${EvidenceBucket.Arn}/tenants/*`. A
browser in that container executes europa.eu's code with those credentials reachable.

Requirements:

- The browser runs with no AWS credentials in its environment; S3 and SQS work
  happens in the worker process, not the browser process.
- Egress from the browser restricted to europa.eu.
- Sandbox enabled; no shared profile between renders; session state discarded per CV.
- The rendered PDF is treated as untrusted input — it already is, via
  `scrub_pdf_metadata`, and that must continue to run.

## Data protection

Unchanged and unresolved: we create guest CVs on europa.eu containing a student's
real data, and we do not delete them. Retention and controllership are unknown. This
is the same exposure the HTTP path carried, neither better nor worse, and it is the
one question in the unsent `EMPL-ELM-SUPPORT@ec.europa.eu` email that does not shrink
with volume.

At ~100 renders/day the rate question in that email is moot — roughly 0.2/minute,
indistinguishable from a couple of people using the site. The ToS question is a
deliberate acceptance: automating a human-facing interface is a different posture
from calling an API, and "it was not blocked" is not "it was permitted."

## Verification

- **A rendered CV contains every section's content.** This is the check whose absence
  let a blank CV ship through seventeen commits. It is required regardless of any
  other decision in this document.
- Provenance assertion retained: `attachment.xml` present with Candidate markers.
- The canary drives the full flow — import or fill, then download — and asserts
  content, not just a 200. The previous canary exercised three of four calls and
  never touched the two that were broken.
- Full suite green; `ruff`, `mypy`, `bandit`, `makemigrations --check` clean.
- No test drives europa.eu. The canary is deliberately not a test.

## What this does not cover

- **The trigger.** Nothing enqueues yet.
- **The student-facing pending/notify surface**, constrained by §5 but not designed here.
- **Content quality** — how to write a strong entry, partly answered by R-084/R-085.
- **Uploading a student's own Europass CV.** `ingest_uploaded_cv` already exists and
  remains the escape hatch if a programme ever demands the student create it
  personally. Not part of this path.

## Risks

- **Their UI changes and every render fails.** The largest risk, and the reason the
  canary matters more than before. Mitigation: canary on a schedule, DLQ alarm,
  circuit breaker. Accepted: a UI change is an outage until someone fixes selectors.
- **Import may not work**, forcing form-filling and raising brittleness. §2 makes
  proving this the first implementation task.
- **Chromium in the render container** — roughly 500 MB and memory-hungry. At this
  volume, one task is sufficient.
- **ToS posture.** Accepted deliberately; see Data protection.
