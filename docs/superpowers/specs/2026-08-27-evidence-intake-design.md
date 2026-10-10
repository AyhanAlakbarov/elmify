# Evidence Intake — Design

Turn artefacts a student already has -- a code repository, a published paper, a thesis PDF --
into facts in the existing ledger, so that work which never reached the CV can reach it, and so
the claims that do reach it are attributable.

## Problem

A student's CV is written from memory. The projects that would carry the application are often
absent from it, or present but described badly. The applicant who most needs help writing about
his work is, by definition, the one least likely to have written about it anywhere else.

Meanwhile the platform already has the machinery to turn facts into documents. What it does not
have is any way to get facts out of the evidence a student is sitting on.

Nothing here is speculative crawling. The entry point is a student saying "I have a project that
is not on my CV" and naming one artefact.

## What the research changed

`docs/research/2026-08-27-cv-content-merge-note.md` -- three independent runs -- found that in
published European rubrics the CV carries close to zero scoring weight (TUM MSc Quantum Science:
0 of 120 points, against 40 for the transcript and 40 for the motivation letter; TU Delft
Aerospace: 0%; Copenhagen Business School: absent from the criteria), and that a peer-reviewed
mapping review (Kurysheva et al., *Int. J. STEM Education* 10(1) 2023) places the CV among methods
"not given substantial weight in selection decisions."

Two consequences bind this design:

1. **Fabrication is the only CV outcome the research proves is punished.** Manchester, UCL,
   Bristol, Edinburgh, City, UCAS, Charles University, Cambridge Judge and the Rhodes Trust all
   publish admissions-fraud policies with application cancellation, offer withdrawal and
   post-enrolment de-registration as consequences. No institution anywhere draws a written line
   between emphasis and fabrication.
2. **Evidence intake is worth building anyway, and is worth more than CV tailoring.** It produces
   verifiable material, and both deep-research runs converge on verifiability as the
   highest-value check. It also feeds the motivation letter, which is the document that actually
   scores.

## Reuse, not a CV feature

`VerifiedFact` is the shared ledger and its docstring already anticipates this: "Every writer (the
profile bridge, upload ingestion, the consultant) goes through it." The letter engine on
`claude/phase2-motivation-letter-engine` reads the same model --
`verify_letter_claims(..., facts: dict[UUID, VerifiedFact], ...)`.

Evidence intake is therefore a **third writer into the existing ledger**, not a CV subsystem. Both
document engines get it without further work.

## Scope

**In:** GitHub and GitLab repositories; publications identified by DOI; uploaded project or thesis
documents (PDF/DOCX). One artefact per invocation, student-initiated.

**Out:** CV tailoring; the skill layer; programme intelligence; self-hosted git; OCR for image-only
PDFs; storing any credential; **and the interaction surface itself**.

That last exclusion matters for whoever plans this. This design produces a *function* that returns
a structured outcome. `NEEDS_INPUT` carries the question to put to the student and the mechanical
facts that frame it; it does not ask anyone anything. Who renders that question, and how the
student's answer comes back, is a view-and-consultant-workflow concern that belongs with the
existing concierge surfaces -- not here. Nothing in this package imports a view, a form or a
template.

## Architecture

A package, `apps/documents/evidence/`, following the `funder_templates/` precedent.

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `sources.py` | Parse student input into typed identifiers. No network. | nothing |
| `repo.py` | Identifiers (+ optional token) → repository facts | `sources` types; github.com / gitlab.com |
| `publication.py` | DOI → bibliographic record | `sources` types; Crossref, then OpenAlex |
| `extraction.py` | Selected repo files, or extracted document text → a *proposed* description | `repo` output, `extract_text` output; OpenAI |
| `facts.py` | Everything above → `VerifiedFact` via `verification.fact_payload` | all of the above; Django |

### `sources.py` is the trust boundary

Its job is to reduce untrusted input to structured identifiers -- `("github", "0rkhann",
"MicroKatc")`, `("doi", "10.1021/acscatal.5c00348")` -- so that **no student-supplied string ever
becomes a hostname or an unescaped path segment.** We construct every URL; the student supplies
only owner and repository name, validated against a strict pattern.

This is what makes the "one fixed trusted host" property true rather than aspirational, and it is
why `validate_public_url` and `LocalEgressProxy` are not needed here: the host is our constant, not
their input. A URL naming any other host is rejected, not fetched.

### Why the REST API and not a clone

`docs/research/2026-08-27-evidence-intake-landscape.md` establishes that every tool in the
repomix / gitingest / code2prompt family clones the repository. They are implementations of "clone
it and walk the files", and none addresses the reason that is expensive here -- connecting to an
arbitrary host the student named. Adopting one saves the file-walking code, which is the cheap
part, and none of the security work.

Six REST endpoints against a fixed host give what CV bullets need, with no clone, no sandbox and no
SSRF surface. No client library: PyGithub is LGPL-3.0 and several thousand lines of object mapping
over six GET requests the existing HTTP stack already covers.

### Why `facts.py` is separate

`verification.fact_payload` is the canonical payload builder -- "Every fact writer in this codebase
goes through here, so payload keys are defined in exactly one place -- the place the verifier reads
them from." Folding fact construction into the two fetchers would duplicate tier-and-provenance
logic and let it drift, which is the failure that function exists to prevent.

`facts.py` is also the only module in the package that imports Django models. This is pinned by a
test.

### Why `extraction.py` is quarantined

It is the only LLM in the package, so `CLAUDE.md`'s AI rules apply to exactly one file: untrusted
content labelled as data and never as instructions, output schema-constrained with Pydantic
`extra="forbid"`, `max_output_tokens` capped, and per-tenant rate limiting added in the same change
via `apps/ratelimit.py::rate_limited` -- the same pattern `ingestion.py` and `generation.py`
already follow.

Keeping it apart means the deterministic path, which is most of the value, is testable with no
model in the loop.

## Data flow

```
student: "I have a project that is not on my CV"
        |
        +-- repo URL ------> sources.parse --> repo.fetch      --+
        +-- DOI / link ----> sources.parse --> publication.fetch-+  mechanical
        +-- PDF / DOCX ----> open_document --> extract_text -----+  (text only)
                                                   |
                                   facts.project --+   provenance stamped
                                                   |
                             does the evidence establish authorship,
                             and is there enough to describe the work?
                                  +-- yes --> done, zero interaction
                                  +-- no  --> extraction.propose  (the only LLM)
                                                   |
                                          draft description
                                                   |
                                    student accepts or edits
                                                   |
                                          his assertion -> fact
```

The three sources are not symmetric, and the diagram flattens that. A DOI is almost entirely
mechanical. A repository is mixed. **An uploaded document yields almost nothing mechanical** -- that
it exists, who uploaded it, when -- because nothing inside a PDF is re-derivable from a durable
external source. It therefore reaches `extraction.propose` in nearly every case, and its facts are
`ASSERTED` rather than `MECHANICAL`. Tier is decided per fact, never per source type.

The PDF path reuses what exists: `apps/concierge/documents.py::open_document` (refuses anything not
`AVAILABLE`, inheriting the quarantine and malware-scan gate) and
`apps/documents/ingestion.py::extract_text` (sniffs magic bytes rather than trusting a filename,
normalises, caps length). Nothing new is written for it.

## Fact tiers

Confirmation burden scales with the distance between a claim and its evidence.

| Tier | Meaning | Gate | Example |
| --- | --- | --- | --- |
| `MECHANICAL` | Re-derivable from a durable source at any time | auto-confirmed | languages by byte count; commit range; contributor logins; Crossref volume/issue/pages/ordered authors |
| `ASSERTED` | The student's own claim, recorded as his | no separate confirmation step -- asserting it *is* the confirmation | "I accelerated training 60x"; an edited description |
| `PROPOSED` | An LLM draft with no author yet | **never written as a fact**; must be accepted or edited first | `extraction.propose` output |

A `PROPOSED` value is not a fact and is never persisted as one. The student accepting or editing it
is what makes it `ASSERTED`, and he is then its author. This is what makes "fabrication is the
student's responsibility" coherent: every interpretive claim in the system has a human author, and
the only thing the platform refuses to ship is a sentence with no author at all.

Each fact records source type, source identifier, retrieval timestamp and tier -- the same
discipline `Program.cv_format_requirement` already follows with `cv_format_source_url`,
`cv_format_confidence` and `cv_format_verified_for_cycle`.

Re-ingesting the same artefact supersedes rather than duplicates, using `VerifiedFact`'s existing
append-only `supersedes` mechanism.

## Authorship is never inferred

This is the core correctness property, and it is not hypothetical. Of the four project
repositories on the account this design was validated against, **three are forks with zero commits
by the account owner**:

| Repository | Fork of | Owner's commits | `ahead_by` |
| --- | --- | --- | --- |
| `cdr_bench` | `AxelRolov/cdr_bench` | 0 | 0 |
| `ChemographyKit` | `Laboratoire-de-Chemoinformatique/ChemographyKit` | 0 | 0 |
| `neptune` | `schwallergroup/saturn` | 0 | 0 |
| `MicroKatc` | not a fork | 21, sole contributor | n/a |

`cdr_bench` is described as "Benchmarking Dimensionality Reduction Techniques on Chemical
Datasets" -- an ideal-looking CV bullet. Any tool that reads name and description and generates a
bullet puts three fabricated projects on this CV. Two mechanical fields catch all three, at zero
LLM cost.

`ahead_by = 0` does **not** prove the student did nothing -- work may live on an unmerged branch,
under another account, or in a lab's own repository. It proves only that we cannot mechanically
claim it. The outcome is therefore `NEEDS_INPUT`, with a question sharpened by the mechanical
facts: *"This is a fork of `schwallergroup/saturn` with no commits from you on the default branch.
What was your role?"*

The publication equivalent is already solved in the schema. `PublicationEntry.self_author_index`
exists because name matching is unreliable -- "Abdullayev O.", "O. Abdullayev" and
"Abdullayev, Orkhan" are one person while a co-author's similar surname is not. Crossref supplies
the ordered author list; **the student selects his index**. Never automatic.

## Reading a repository with no README

A README is absent or useless exactly when it is most needed. Signals, in the order they should be
consulted:

1. **Docstrings** -- prose the author wrote, adjacent to what it describes
2. **Class, function and parameter names**
3. **Imports parsed from source**
4. **Directory names**
5. **Notebook markdown cells** -- often the real documentation in research repositories
6. **Commit messages**
7. **README**, when present
8. **`requirements.txt` -- unreliable, do not weight it**

Item 8 is measured, not assumed: the validated repository's `requirements.txt` is a `pip freeze` of
the author's entire operating system (`apturl`, `Brlapi`, `blinker`, `bcrypt`). Declared dependency
files can be system freezes; imports cannot.

Stripped of its README, that repository still yields `ApparentEaAnalysis`, `DRCAnalysis`,
`MicroKinetics`, a `GaussOutputFiles/` directory, and docstrings such as *"Calculates apparent
activation energy from the slope: ln(ri) = -Ea/RT + ln(A)"* -- enough for the same bullet. If every
signal is thin, the outcome is `NEEDS_INPUT`.

## Error handling

Three outcomes, following the house "classify, do not raise" pattern that
`render_cv_with_warnings` already uses:

- **`SUCCESS`** -- facts written
- **`NEEDS_INPUT`** -- the fetch worked; the evidence cannot support a claim alone
- **`FAILED`** -- nothing written, specific reason surfaced

`NEEDS_INPUT` is load-bearing. A fork with `ahead_by = 0`, or a Crossref record in which the
student cannot identify himself, is not an error. Collapsing it into either success or failure is
what produces fabricated bullets.

| Module | Failure | Outcome |
| --- | --- | --- |
| `sources` | host is not github.com / gitlab.com; `../` or encoded traversal in owner or repo; malformed DOI | `FAILED`, specific |
| `repo` | 404 -- GitHub returns 404 rather than 403 for private repositories so existence does not leak | `FAILED` -- "not found, or private and no key supplied" |
| `repo` | invalid, expired or wrongly scoped token | `FAILED`; the token never appears in the message, the logs or an exception |
| `repo` | rate limit (60/hour unauthenticated, 5000/hour with a token) | `FAILED`, marked retryable |
| `repo` | fork, `ahead_by = 0`, student absent from contributors | `NEEDS_INPUT` |
| `publication` | DOI absent from Crossref (common for conference papers) | fall back to OpenAlex |
| `publication` | absent from both | `NEEDS_INPUT` |
| `publication` | record complete; which author is the student? | `NEEDS_INPUT`, always |
| `extraction` | model refusal | `FAILED` -- reuse the existing `_has_refusal` check |
| `extraction` | malformed output | Pydantic `extra="forbid"` -> `FAILED` |
| document | image-only PDF with no text layer | `FAILED` -- no OCR here |
| document | not PDF/DOCX, or scan incomplete | existing `UnsupportedUpload` / `open_document` refusal |

Two rules belong in the module docstrings:

**An error never produces a fact.** Partial success is the trap. A Crossref record missing its
author list must not become a publication fact with empty authors; either it satisfies the schema
or it routes to `NEEDS_INPUT`.

**Authorship is never inferred.** See above; both mechanisms already have precedent in the
codebase.

## Credentials

Private GitHub repositories are supported through a **fine-grained personal access token scoped to
the single repository, read-only**. That is a real GitHub capability on the free plan.

GitLab.com does not offer an equivalent: project access tokens require Premium or Ultimate on
gitlab.com, deploy tokens are git credentials rather than API credentials, and a personal access
token with `read_api` is scoped to the user rather than the repository -- which would give the
platform read access to everything the student can see. **Private GitLab repositories are therefore
out of scope**, and the student is told why rather than being asked for an over-scoped token.

**The token is never persisted.** It is used inside the request that fetches, and discarded. This
is possible because intake is a one-shot operation: facts persist, access does not. If the
repository changes and the student wants a refresh, he supplies a new token.

This must be stated loudly in the module, because `CLAUDE.md`'s Phase 3 rule names the exact
failure it is guarding against: "Portal credentials never live in the database... never a model
field, never a `JSONField`... The failure mode this rule exists to prevent is a password column
added in passing during a sprint." Storing the token to spare the student a paste would drag in
Secrets Manager, a KMS key, per-secret IAM and a GDPR erasure path -- none of which is needed if
nothing is stored.

## Testing

Every path where a bug produces a fabricated claim is a pure function with no network:

| Under test | Why it is the core | Method |
| --- | --- | --- |
| `sources.parse` | a bug lets a student string become a hostname or escape the path | exhaustive table: hosts, `../`, encoded slashes, DOI patterns, junk |
| authorship gate | a bug lets a fork with `ahead_by = 0` produce a fact | table over (fork, `ahead_by`, contributor present) -> outcome |
| tier assignment | a bug marks an interpretive claim auto-confirmed | every field -> asserted tier |

These get exhaustive tests; the fetchers around them are thin I/O and get thin tests.

**Fixtures are captured from real responses**, not invented: one genuine repository (not a fork,
sole contributor, substantial README), three forks with `ahead_by = 0`, one `requirements.txt` that
is a system freeze, and one real Crossref record.

**Network is injected, not mocked at the library level.** A fake transport is passed into
`repo.fetch` and `publication.fetch`, for the same reason `europass.py` owns its transport.

**One opt-in live contract test per external API**, skipped by default, asserting only that the
fields depended on still exist -- `fork`, `parent`, `ahead_by`, `contributors[].login`, and
Crossref `author[]` and `issue`. Fixtures cannot catch API drift; this can.

**Two structural invariants**, in the style of `test_module_imports_without_django`:

- no fact is written with tier `MECHANICAL` unless its value came from a mechanical field
- `facts.py` is the only module in the package importing Django models

`extraction.py` is tested with a stub parser, including a README containing "ignore previous
instructions", asserting it is treated as data.

## Out of scope

- **CV tailoring.** Unevidenced by three research runs, and dangerous where it implies omission:
  uni-assist requires "no omissions", ETH Zürich a gapless history, and DAAD treats a missing
  document as grounds for exclusion. Any future "keep the best N entries" logic must be
  country-aware or it will break German applications.
- **The skill layer.** Generic competencies are inert on current evidence. ESCO was deferred in
  `2026-08-22-open-source-landscape.md` on the grounds that nothing needed skill normalisation;
  revisit there, not here.
- **Programme intelligence.** Its value rose, but its consumer is the motivation letter's
  programme-fit section, not the CV.
- **GROBID.** Real, healthy, Apache-2.0, and heavy -- a Java service with its own model weights,
  needed only for a PDF with no DOI. Revisit if DOI-less manuscripts prove common.
- **OCR for image-only PDFs.** The shortlist is already governed by the ingestion design.
- **Self-hosted GitLab and arbitrary git hosts.** No fixed-host guarantee, so they are the clone
  problem by another name.
