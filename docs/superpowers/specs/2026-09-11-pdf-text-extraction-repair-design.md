# PDF text extraction: repairing kerning artifacts, and refusing silence

**Date:** 2026-09-11
**Status:** accepted
**Touches:** `apps/documents/ingestion.py::extract_text`, `tests/documents/cv_corpus.py`

## Why this exists

`extract_text` is the only step between an uploaded document and the fact
ledger, and it is the only step in that chain with no check on it. Fetching has
`validate_public_url`, an origin comparison and a digest. Generation has
`verify_against_facts` and a blocking UNSUPPORTED verdict. Approval has a human.
Between the PDF bytes and the first `VerifiedFact` row there was nothing, so two
failures reached the ledger unannounced. Both were measured, not reasoned about.

### Failure 1: pypdf inserts spaces that are not in the document

pypdf's default (`plain`) extraction mode emits a space when a text-showing
operator's kerning adjustment crosses a threshold. Reproduced from raw bytes: a
minimal PDF containing `[(Scikit) -200 (-learn)] TJ` extracts as `Scikit -learn`,
while the same file at `-100` extracts correctly. The glyph is incidental -- the
threshold is about displacement, so the artifact lands wherever a producer kerns
tightly, which in practice is around hyphens and before commas and periods.

Measured on a real CV (`Microsoft Word LTSC`): 8 hyphen splits and 4 punctuation
splits, including `Garay -Ruiz` and `Bori -Bru`, which are a co-author's surname.
These reached `VerifiedFact.payload` and printed into a generated CV.

Producer survey over ~120 PDFs: Microsoft Word is both the most common producer
and effectively the only one generating the artifact in volume (11 files, ~43
occurrences). Google Docs, LaTeX/pdfTeX, iText, Cairo and Canva produced none.
Word is also what applicants will upload, so this is not an edge case.

### Failure 2: an unreadable PDF is indistinguishable from an empty one

An image-only PDF (38,064 bytes, built in the probe) returns `""` from
`extract_text`, no exception. `ingest_uploaded_cv` then writes no facts and
returns `()`, which is the same result as a CV containing nothing. The student
sees an empty profile and no error.

This is the same shape as the failure `CLAUDE.md` already records for programme
pages -- "a page that reads as saying nothing is indistinguishable from one that
says nothing" -- which was fixed there by `refresh.py::readable_text` and never
applied to the student side.

## What "best" means here

Taken from constraints this repo already states, not from a general preference:

1. A failure must be loud rather than silent.
2. A guarantee should be structural rather than a policy someone can relax.
3. No new dependency on the path carrying student PII without a reason that
   survives the licence and isolation questions.

Accuracy of extraction is therefore not the deciding axis. Converting an
invisible corruption into a visible one, at the smallest surface, is.

## Rejected alternatives

**`extraction_mode="layout"`.** Fixes the artifact completely on the measured CV
(8 splits to 0) and, as a bonus, keeps each degree's dates and city on the same
line as the degree. Rejected because it fails worse elsewhere: on a Springer
paper it drops required spaces, producing
`Chemistr y hasdiversified fromabasic understanding oftheelements`. `extract_text`
also feeds `apps/documents/evidence/intake.py`, which reads papers. Trading a
stray space for glued words on the evidence path is a bad trade.

**A different extractor.** PyMuPDF is AGPL, which is a licensing problem for a
commercial platform. `pypdfium2` and `pdfminer.six` are neither installed nor
justified: both put a new dependency on the one path carrying student documents,
and both trade a known, measured artifact for an unmeasured one.

**OCR for image-only PDFs.** Not built. The expected input is Word- and
Canva-produced PDFs, and the only text-free files in the survey were phone
photographs of documents. A refusal costs a few lines; OCR on the PII path would
need its own isolation design, like the browser task got. Revisit if real uploads
show scans, which failure 2's guard will make visible.

**Per-fact source excerpts.** `ProgramCompetency` already carries `term` plus the
`excerpt` it came from; `VerifiedFact.source_ref` carries only `upload:<uuid>`.
Applying the catalog-side pattern to the student side would let whoever confirms
a fact check it against the source. Deferred, for two reasons: it does not fix
this bug, since the excerpt would carry the same artifact, and there is no
confirmation UI to show it in -- `apps/documents/views.py` exposes the gap
interview and nothing else.

## The design

### 1. Repair, in `extract_text`'s PDF branch only

Two joins, applied to pypdf's output before `normalize_text`:

- a space between a word character and a following `-` that begins a word:
  `Scikit -learn` becomes `Scikit-learn`
- a space between a word character and a following `,` or `.` that ends a token:
  `Abdullayev ,` becomes `Abdullayev,`

Both are typographic invariants in the scripts this platform prints, not
guesses about intent.

**Not `:` or `;`.** French typography requires a space before them. A French
university document in the survey contains 45 legitimate ` :` occurrences, and
this platform's students write French. Widening the rule to "punctuation" would
corrupt correct text, which is worse than the bug.

Range separators and bullets survive by construction: ` - ` has a space on both
sides and fails the lookahead, and a bullet at line start has `\n` behind it,
which is not a word character.

The DOCX branch is untouched -- the artifact is a PDF text-positioning effect and
does not exist there.

### 2. Refuse silence, in `ingest_uploaded_cv`

The guard belongs in the caller, not in `extract_text`, because
`apps/documents/evidence/intake.py` **already has it** -- an evidence document
with no text layer returns `IntakeResult(FAILED, "no text layer in the document;
OCR is out of scope")`. Raising inside `extract_text` would turn that clean
result into an exception. The CV path was simply the one without the check.

So `ingest_uploaded_cv` raises `UnsupportedUpload` -- the error `extract_text`
already raises for a file that is neither PDF nor DOCX, so callers face no new
exception type -- with intake's wording, since it is the same refusal for the
same reason.

Empty rather than a per-page character floor: a floor invites a threshold
argument and would refuse a legitimately sparse one-page CV, while zero
characters from a non-empty file is unambiguous.

### 3. Measure the extractor, not only the model

`tests/documents/cv_corpus.py` renders all six of its documents with WeasyPrint
at test time. That is deliberate (no binaries in git) and it means the corpus
structurally cannot contain a producer artifact -- it measures the model's
reading and never the extractor's. The corpus is left alone: it is keyed to the
`live` accuracy tier, and this defect is deterministic and needs no model call to
detect. The kerned document is built from raw bytes in `_kerned_pdf`, beside the
tests that use it, honouring the same no-binaries rule.

## Testing

Five tests in `tests/documents/test_ingestion.py`:

- a kerned PDF extracts `Scikit-learn`; the same test asserts pypdf's own
  reading is `Scikit -learn`, so the premise is pinned rather than assumed
- the same PDF at `kern=-100` never needed repairing -- the companion that makes
  a future pypdf which stops inventing the space fail loudly, instead of leaving
  a regex nobody can justify
- ` :` and ` ;` survive (the French case)
- ` - ` ranges and `- ` bullets survive
- a PDF with no text layer raises `UnsupportedUpload` and writes no facts

**Result (2026-09-11).** `pytest` 1879 passed / 43 skipped, `ruff` clean, `mypy`
clean over 236 files, `bandit` 0 findings, no pending migrations. Live re-run of
the real Word-produced CV: 8 artifacts in the generated document before
(`Garay -Ruiz`, `Bori -Bru`, `Scikit -learn`, `multi -step`, `ligand -exchange`,
`rhodium -catalyzed`, `PyTorch -based`, `ultra -large`), **0 after**, with the
same 31 facts, 31 verdicts and 0 UNSUPPORTED on both sides.

## Known, accepted, not fixed here

In plain mode a CV's education section extracts as institution names followed by
a *separate* block of cities and date ranges; the model re-associates them by
order. It did so correctly on the measured CV. No regex addresses this, and
layout mode -- which does -- is rejected above. Recorded so the next person
measuring extraction does not mistake it for a new finding.
