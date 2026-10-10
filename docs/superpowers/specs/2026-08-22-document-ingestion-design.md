# Phase 2 design: Document ingestion, OCR and source fetching

Status: design, not yet implemented. Date: 2026-08-22.

Scope: how external material reaches the `VerifiedFact` ledger reliably — scanned transcript
extraction, the reliability gate that decides whether an extraction is usable, and the fetch
transport used for programme sources.

**This document amends `2026-08-21-phase2-cv-engine-design.md`.** That design specified the
ingestion path's *shape* (scan → extract → confirm → generate) but not its mechanics, and its
confirmation rule is superseded here. See "What this supersedes" at the end.

It is deliberately separate from the §4.2 motivation-letter design: ingestion feeds every document
kind, so binding it to the letter engine would scope it wrongly.

## Decision 1 — no student confirmation of extracted facts

The CV engine design required that "nothing extracted from an upload is ever used unconfirmed",
with the student or counselor confirming each candidate fact. That rule merged two different
problems under one remedy, and the remedy only fits one of them.

| Source | Actual risk | Correct control |
|---|---|---|
| A CV the applicant wrote | Their own claims being laundered into evidence | `source_tier = STUDENT_STATEMENT`. Already solved by the ledger's tiering; confirmation was never what fixed it. |
| A transcript or certificate | **We misread it.** The document is genuine institutional evidence. | Extraction reliability gate (Decision 3). Not a human proofreading pass. |

Asking the student to confirm forty OCR-extracted grades is both friction and ineffective: it is
the work they paid the service to do, and people click through review screens. It also puts the
customer in the position of certifying our machinery's accuracy, which is not a judgement they
were engaged to make.

**Machine-read facts are therefore usable once they pass the reliability gate, with no student
confirmation step.** Where a human check is genuinely warranted, it is the **counselor's** — they
already receive the fact overlay under §4.2.1, they are staff rather than the customer, and
reviewing extracted facts is the work they are paid for. This matches the authority split the CV
design already sets out: the student supplies facts, the counselor supplies judgement.

Unchanged: facts only the student can know ("I led a team of five") still come from answering the
consultant, and the answering *is* the record. No extra screen, no attestation step.

Also unchanged: `confirmed_by` stays on `VerifiedFact`. It now records *what* cleared the fact —
the gate, or a named counselor — rather than a mandatory student click. A fact that fails the gate
and has no counselor decision is still invisible to generation.

## Decision 2 — benchmark document VLMs; do not default to Tesseract

`pypdf` is already a dependency and extracts text from PDFs that *have* text. There is no OCR in
the project, so scanned transcripts — the common case for master's applicants worldwide —
currently cannot be ingested at all.

Tesseract was the initial recommendation on latency grounds. **That constraint does not exist
here**: uploads are asynchronous with a budget of a day or more, so there is no reason to trade
accuracy for speed. Document-VLMs substantially outperform classical OCR on our hard cases —
grade tables, institutional stamps and seals, mixed scripts, rotated phone photographs.

### Benchmark plan

1. Pull the current **OmniDocBench** leaderboard. Do not select from memory; this field moves
   monthly and any ranking written into this document is stale on arrival.
2. Shortlist three. Candidates as of writing: **PaddleOCR-VL** (Baidu), **dots.ocr** (RedNote),
   **MinerU** (Shanghai AI Lab), **GOT-OCR2.0**, **MonkeyOCR**, and **Surya** for layout.
   Several of the strongest are Chinese-published; licence terms must be checked per model, not
   assumed from the others.
3. Benchmark on **real transcripts**, not benchmark documents: Azerbaijani, Turkish, Russian,
   Chinese and Arabic scripts; phone photographs as well as flatbed scans; stamped and signed
   pages. Academic benchmark ranking does not predict performance on a stamped transcript from a
   regional university.

### Benchmark pairs, not models

The gate consumes a *pair* of engines, so single-model accuracy is the wrong score. Measure:

- **Combined accuracy where the pair agrees** — what the gate actually lets through.
- **False-disagreement rate on correct reads** — how often the pair flags a document that was
  fine. Each false disagreement is a retake request sent to a customer whose upload was good,
  which is precisely the friction Decision 1 exists to avoid. A pair of individually strong
  engines that is noisy together loses to a weaker, quieter pair.

### The criterion that decides it

**Table-structure recovery, not character accuracy.** A transcript is a table. A model that reads
every character correctly but binds a grade to the wrong course has produced a *worse* result than
one that fails visibly — the first is a silent factual error flowing into a CV and a motivation
letter, the second is a retake request. Score row-to-grade binding explicitly and weight it above
raw character error rate.

Self-hosting versus a hosted API is an open decision (see below), but note that transcripts are
personal data: a hosted model means a processor agreement and a data-protection review, which is a
cost self-hosting does not carry.

## Decision 3 — extraction reliability gate and retake loop

Extraction is only usable if we can tell when it failed. Three independent signals, in order.

### Why not model confidence

OCR engines report a per-word confidence, and gating on it is the obvious design. It measures the
wrong thing: it scores *how clearly a shape matching this character was seen*, not whether the
character is right. A blurred `8` resembling a clean `3` returns `3` at high confidence. Neural
models are poorly calibrated on out-of-distribution input, and a skewed, stamped, low-resolution
phone photograph is exactly that — so the scans we most need to catch are the ones that produce
confidently wrong output.

Confidence is the model grading its own work. It may break a tie; it does not decide the gate.
This is the same principle as the anti-fabrication gate in the CV and letter designs, where a
deterministic check — never the model's own assessment — is the guarantee.

### The three signals

**1. Image quality, at upload, before OCR.** Blur, resolution, skew, cropped edges, glare. Checked
client-side so the request lands **while the phone is still in the user's hand** — a retake asked
at upload costs seconds; the same request a day later is a support ticket. Most unusable scans are
catchable here with no OCR at all, which also makes this the cheapest signal.

**2. Engine disagreement — the primary gate.** Run two architecturally different engines over the
same page and compare field by field. Agreement between independently built systems is strong
evidence; two of them producing the same wrong answer is unlikely. Disagreement marks that field
unreliable whatever confidence either model claimed. This is a measurement taken from outside the
model, which is why it outranks signal 3.

**Start by pairing a VLM with classical OCR.** The requirement is architectural difference, and
classical OCR (Tesseract, or PaddleOCR's classical pipeline) is maximally unlike a transformer VLM
— it fails by producing garbage where a VLM fails by producing plausible hallucination, so the two
cannot agree on the same wrong answer.

This is an accuracy choice, not a cost one. If the pair benchmark shows classical OCR is too noisy
a partner — flagging good documents often enough to generate needless retake requests — **fall
back to a second VLM from a different lab**, which stays architecturally distinct enough while
reading hard scans far better. The cost envelope permits it (see "Cost" below); what must never be
paired is two fine-tunes of one base model, which would agree on the same mistakes.

**Scope the double-read to consequential fields** — grades, dates, degree titles, institution
names — not every character on the page. Disagreement on a course description is not worth a
retake request.

**3. Structural validity.** Grades within the valid range for the stated scale, dates that parse
and order correctly, credits that sum plausibly, course count matching table rows. Deterministic,
and it catches row misalignment — precisely the failure confidence scores are blindest to.

### The retake loop

- **Ask specifically.** *"Page 2, the right-hand grade column is cut off"* — never "we could not
  read your document". A vague request returns the same photograph.
- **Ask once.** A second failed upload does not trigger a third request.
- **Terminate on a human, not on the student.** After a second failure the document becomes a
  counselor task: a person opens the file and enters the values, written as
  `AUTHORITATIVE_DOCUMENT` with the counselor as `confirmed_by`. Applicants holding genuinely
  poor-quality institutional documents exist and must not hit a wall.
- **Never guess.** An ungated extraction is never written to the ledger, so it can never reach a
  generated document.

Ordering relative to the malware scan is unchanged from the CV design: **scan first**, always. A
file failing the scan is quarantined and reaches neither OCR nor the quality check.

### Cost — not a constraint on this design

**Product decision: extraction cost per student is not a constraint. Anything up to roughly $10
per student is acceptable** against a service priced in the hundreds. That is a ceiling to design
freely under, not a target to optimize toward.

Estimated actual cost sits far below it. A 1-2B document VLM processes a page in single-digit
seconds on a mid-range GPU instance — order of hundreds of pages per GPU-hour — and a student
uploads roughly ten pages in total, putting one engine in the low cents. (Figures are estimates;
confirm against current pricing during the benchmark.)

**The consequence is the useful part: cost is not a selection criterion anywhere in this
document.** Choose the engine pair on accuracy and false-disagreement rate; choose hosted versus
self-hosted on data protection. Double-reading needs no cost justification, and neither would a
third pass if the benchmark showed one earned its place.

Deferred as premature optimization, recorded so it is not rediscovered: an idle GPU costs the same
whether it processes ten pages or ten thousand, so at scale the provisioning model dominates every
inference choice here. The fix — queue uploads, process on spot capacity, scale to zero between
runs — is well within the day-plus latency budget, but it buys nothing at current volume against a
$1 envelope. Revisit when extraction spend approaches that envelope, not before.

## Decision 4 — scrapling as the fetch transport, behind the existing SSRF guard

Adopted. Sites block ordinary clients for no reason we can address, and a blocked fetch is an
operational failure: it stops the funding engine seeing an official page it is entitled to read.

**`apps/research/egress.py` is not replaced.** Its core is not anti-bot machinery — it is SSRF
protection. `validate_public_url` (`apps/research/egress.py:66`) resolves the hostname and rejects
any URL landing on a non-global address (loopback, private ranges, link-local, the cloud metadata
endpoint), then pins the connection to that resolved address so DNS cannot be swapped underneath
it. That guard exists because fetch URLs originate in LLM output and student input rather than a
curated list. Scrapling does not provide this and is not intended to; the two are layers, not
alternatives.

The change:

- **Retained:** `validate_public_url`, DNS pre-resolution and address pinning, the redirect limit,
  the 10 MB response cap (`MAX_RESPONSE_BYTES`), the content-type allowlist.
- **Replaced:** urllib3 as the retrieval mechanism, in `_request`. Scrapling's stealth fetcher
  takes over the actual GET.
- **Untouched:** `apps/research/snapshot.py`. Bodies are still SHA-256 hashed and stored as
  versioned evidence, so the provenance chain the recommendation engine depends on is unaffected.

`FetchResult.browser_required` already exists (`apps/research/egress.py:63`), so the escalation
path was anticipated by the current code.

Two operational notes:

- Stealth mode drives a real browser and is slow. Keep a plain-fetch fast path and escalate only
  on a block, rather than paying browser cost on every fetch.
- This adds a third-party dependency to the **product runtime**, distinct from the scrapling MCP
  server used as a research tool. It goes through the repository's unverified-source gate and will
  be covered by `pip-audit` in CI.

## What this supersedes in the CV engine design

`2026-08-21-phase2-cv-engine-design.md`, section "Populating the ledger":

- Step 5's "the student (or counselor) confirms each candidate before it becomes usable" and
  "**Nothing extracted from an upload is ever used unconfirmed**" — replaced by Decision 1. The
  anti-laundering intent behind that rule is preserved by `source_tier`, which is what actually
  carried it.
- Step 3's "extract text" — given mechanics by Decisions 2 and 3.
- Testing item 13, "Unconfirmed facts are invisible to generation" — restated as: a fact that has
  not passed the reliability gate and carries no counselor decision is invisible to generation.

Its malware-scan-first ordering (step 2) and its `source_tier` tiering are unchanged and remain
binding.

## Testing strategy

1. **Scan precedes everything**: a file failing the malware scan reaches neither the quality check
   nor OCR, and is never written to the normal storage prefix.
2. **Quality check rejects before OCR**: a blurred or cropped upload produces a retake request
   without an OCR call being made.
3. **Disagreement blocks a field**: two engines returning different values for one grade mark that
   field unreliable, even when both report high confidence. Assert the gate ignores confidence.
4. **Structural validation catches misalignment**: a grade outside its scale's range, and a
   row-shifted table whose credits no longer sum, are both rejected.
5. **Retake asks specifically and once**: the request names the page and region; a second failure
   routes to a counselor task rather than a third request.
6. **Ungated extractions never reach the ledger**: a failed extraction writes no `VerifiedFact`,
   and no draft can cite it.
7. **Counselor-entered values are attributed**: a manually entered transcript value carries the
   counselor as `confirmed_by` and appears in the audit trail.
8. **No student confirmation is required**: a gate-passing extracted fact is usable by generation
   with no student action recorded.
9. **SSRF guard survives the transport swap**: a URL resolving to a loopback, private, link-local
   or metadata address is rejected before scrapling is invoked. Assert against the transport
   itself, not only against `validate_public_url`.
10. **Caps survive the transport swap**: the response-size ceiling, redirect limit and content-type
    allowlist still apply when scrapling performs the fetch.
11. **Evidence chain intact**: a body fetched through scrapling produces the same SHA-256 snapshot
    record as one fetched through urllib3.

## Open decisions for the implementation plan

- **Which VLM** — output of the benchmark above, not decidable here.
- **Self-hosted or hosted** — **a data-protection decision, not a cost one.** Hosted models mean
  transcripts leave our infrastructure, requiring a processor agreement and a data-protection
  review; self-hosting carries operational load instead. Both fit the cost envelope, so price
  should not break the tie.
- **Which second engine** backs the disagreement check, and the disagreement threshold per field
  type — both fall out of the pair benchmark above. Start with classical OCR and fall back to a
  second VLM from a different lab if the false-disagreement rate is too high. Settled either way:
  never two fine-tunes of one base model, which would agree on the same mistakes and make the
  signal worthless.
- **Batch scheduling and instance class** — *deferred, not open.* Spot versus on-demand, queue
  depth and batch-window latency are cost optimizations for a later stage; see "Cost" above for
  the trigger to revisit.
- **Client-side quality-check implementation** — browser-native (canvas blur/edge detection) versus
  a small WASM model. Start with the former; it is native-platform work before it is a dependency.
- **Scrapling escalation policy** — which response signals classify as "blocked" and trigger the
  browser path.
