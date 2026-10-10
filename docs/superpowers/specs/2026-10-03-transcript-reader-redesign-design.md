# Transcript reader, redesigned — upload, a quality gate, a paid reader, few questions

**Status:** design, agreed with the owner in conversation 2026-10-03; amended 2026-10-04 (R9–R13, §6.5, §8 additions; review passes: §3.1, §4.1, §6.6, §6.7, §7.1, §10). Not built.

**Replaces** the reading half of `2026-09-25-tailored-programme-finding-design.md` §3.1 — the
PP-StructureV3 OCR program on Lambda ("The OCR is PaddleOCR's PP-StructureV3…", "Where it runs",
"Every transcript goes through OCR") and the "No second OCR engine" paragraph. **Keeps** from §3.1:
the summary screen and its four numbers, "a failed check is shown, never repaired", the code checks,
"no generative model writes a stored value", Jev for column and row meaning with its launch gate, the
student-still-studying rules, identity basics and languages. That section gets a one-line pointer here
when this is built.

**Evidence, all in `docs/superpowers/research/`:**
- `2026-10-03-transcript-reader-architecture.md` — open and commercial readers, the text-layer path.
- `2026-10-03-single-vlm-transcript-reader.md` — open vision-language models (VLMs) as the whole reader.
- `2026-10-03-document-capture-quality-gates.md` — how capture products gate quality and ask for retakes.
- `2026-10-04-end-user-confirmation-of-low-confidence-fields.md` — whether asking the uploader about only
  doubtful fields is accepted practice, and the automation-bias evidence behind §6.3 and §6.5.
- `2026-10-03-azerbaijan-transcript-languages.md`, `2026-10-03-azerbaijan-e-diploma-and-grading-scales.md`,
  `2026-10-03-transcript-translation-rules-azerbaijan.md` — written by the engine-spec session, copied here.
- Our own measurements (§8), on the git-ignored eval harness `.superpowers/ocr-eval/` in the
  tailored-programmes worktree: 16 documents, 24 page images, 430 hand-keyed course rows, plus three
  tampered pages.

---

## 1. Goal

A student uploads their transcript once and is asked as little as possible. Pages we cannot read are
refused at once with the reason, so nothing is guessed from them. What we can read becomes course rows
— title, credits and unit, grade, status — accurate enough to check programme requirements and
eligibility and to tailor the match. The student confirms only what the document itself cannot vouch
for.

## 2. Owner decisions recorded here

| # | Decision |
|---|---|
| R1 | **Website only, upload only.** No live camera and no in-browser scanning: a PDF or photos are uploaded and every check runs on the server. |
| R2 | **A page that fails the quality gate is refused at once, with the reason** ("retake this page: the text is too small"), in az/tr/ru/en. |
| R3 | **At most 2 retakes per page.** After that the student types only the flagged cells; each is stored as *typed by the student*, never as read. Nobody on our side steps in (owner rule of 2026-09-23: no person in the pipeline). |
| R4 | **English first, the original accepted.** A certified English translation is the main path; an original-language transcript is still read. |
| R5 | **When a notarised or sworn translation is uploaded, only the translation is read** — a sworn translator has already checked it; the original is read only when no translation is uploaded (owner 2026-10-03, recorded first in the engine spec §1, commit `92ce9539` on `claude/verified-catalog-design`). |
| R6 | **The reader is a pay-per-page service: Azure Document Intelligence.** Chosen on measurement (§8) over Mistral OCR, Google Document AI, a self-hosted VLM, and the current PP-StructureV3 program. |
| R7 | **The transcript is read while the programme search runs.** Neither waits for the other; requirement and eligibility marks show "waiting for your transcript" until the reading is accepted (§6). |
| R8 | **Verifying an e-diploma online is out of scope.** The 2026 Azerbaijani myGov diploma is checked behind a reCAPTCHA (owner 2026-10-03, engine-spec session). |
| R9 | **A born-digital PDF is read from its own text layer** when that layer passes a quality check; Azure reads every other page (owner 2026-10-04). Exact and free where it applies. |
| R10 | **OvisOCR2 is the planned second reader, not a launch component** (owner 2026-10-04). It is added beside Azure — never in place of it — when a GPU is available and a §6.5 trigger fires; cells where the two disagree become cells the student is asked about. |
| R11 | **The confirm screen follows the research's rules** (§6.3): the original cell's crop beside the value, an explicit choice per cell, nothing pre-selected, no "confirm all". |
| R12 | **A random audit of unflagged transcripts measures what slips through** (§6.5) — a person checks a sample by hand, outside the student's flow, so nothing waits on it. |
| R13 | **Payment comes first** (owner 2026-10-04, "for now"): a student pays the platform fee for the academic-year cycle, and only then can upload a transcript, and only then does the programme search start. No page is read for an unpaid profile, so an unpaid sign-up costs nothing to read. |

## 3. The flow

0. **Payment** (R13). Until the cycle is paid, the upload is not offered and the search does not start.
1. **Upload.** The student uploads the transcript — a PDF (born-digital or scanned) or page photos —
   and says whether it is the **original** or a **certified translation** (R5). If both are uploaded,
   only the translation is read. Uploads keep the existing path: quarantine, GuardDuty scan, then the
   document worker (`apps/concierge/documents.py`, `apps/documents/document_worker.py`).
2. **Read and gate, in seconds.** For each page the worker first tries the PDF's own text layer (R9,
   §4); every other page goes to Azure. The quality gate (§5) runs on the result. A refused page is
   shown at once with its reason; the student retakes or re-uploads that page only.
3. **Meanwhile, the rest of onboarding.** The student answers identity basics and the seven questions
   (tailored spec §3.2). The programme search starts from those answers and does not need the
   transcript.
4. **Code checks and Jev.** Rows are cut from the tables, Jev labels columns and rows (unchanged,
   `apps/documents/transcript_questions.py`), and code runs the checks (§6).
5. **The summary screen, last** (tailored spec §3.1 item 3, unchanged): the four numbers, then only the
   cells that need the student (§6.3).
6. **Accepted.** The reading becomes the student's academic record; requirement and eligibility marks
   that were "waiting for your transcript" update, and the student is told.

### 3.1 Pages, uploads and retakes

A transcript is **a set of pages**, not one upload: photos come one per file, a retake replaces one
page, and a translation office's PDF often binds the translation together with a copy of the original.
So:
- **A reading belongs to the transcript, and each page remembers which upload it came from.** Today
  `TranscriptReading` is one-to-one with one `DocumentVersion` (`apps/documents/models.py`); that
  changes (§10). A retake replaces that page's slot and keeps its retake count; the other pages are
  not re-read or re-billed.
- **Page order** comes from printed page numbers where the document has them, else from upload order.
  An exact duplicate page (same image digest) is dropped silently; a photo holding two pages is read
  as it is — Azure returns both — and is not refused for that alone.
- **A translation bound with its original (R5):** pages in the translation's language are read; pages
  in the original's language are skipped, not refused. The language of a page comes from its own text
  (the script and the letters §4's text-layer check already looks for), never from the upload label
  alone. A stamped translation is its own pages, never set side by side with the original (owner
  2026-10-04), so there is no bilingual-column rule: a page that does carry both languages is read whole.
  A scanned page has to be read to learn its language, so a skipped original page still counts toward
  the page allowance (§7.1); a text-layer page's language costs nothing to learn.
- **A file is counted before anything is read.** The isolated parser (§4.1) counts a PDF's pages for free;
  a file holding more pages than the student has left in the allowance is refused whole with that
  number, so a 300-page upload never reaches Azure.
- **A whole new upload replaces the transcript.** Its pages are read and counted again; the old reading
  is kept until the new one is accepted, then superseded (never deleted while it is the one in use).
- **Phone photos:** iPhones store photos as HEIC. Browsers usually convert to JPEG when a file is
  uploaded from a web page, but not always (**Unverified** per browser). A HEIC upload is converted in
  the isolated parser (§4.1) if a permissively licensed converter is available, else refused with
  "Upload a JPEG or PDF" — §9 gate 8 checks a real iPhone upload either way.

## 4. The reader: Azure Document Intelligence

- **What it is:** Microsoft's paid document-reading API, the **Layout** model: text lines and words
  with a polygon and a confidence each, and tables as cells. One call per page, a few seconds each.
- **It replaces the OCR seam, not the reader.** `apps/documents/ocr.py::read_pages` keeps its contract
  — pages of lines and tables — and gains per-cell confidence and polygons. `transcript.py`, the Jev
  questions and the checks keep working on `OcrPage`. PaddleOCR and PP-StructureV3 are removed; the
  Lambda that ran them becomes the small parser of §4.1, so the 10,240 MB memory quota it needed goes
  with them. Two OCR engines are never kept "just in case".
- **A born-digital PDF page is read from its own text layer (R9)** — university-issued PDFs, translation
  offices' PDFs, the 2026 myGov e-diploma. Tables come from `pdfplumber` (MIT; PyMuPDF is ruled out as
  AGPL — `2026-10-03-transcript-reader-architecture.md`), into the same `OcrPage` shape. **The layer is
  used only if it passes a check:** enough characters for the page, no U+FFFD replacement characters,
  and the letters its language needs (ə on an Azerbaijani page, ı/ş/ğ on a Turkish one, Cyrillic on a
  Russian one). A page that fails goes to Azure, like a scan. A text-layer value has no reader
  confidence — it is the document's own text — so only §6.1's checks can flag it. §9 gate 2 measures
  the check on real PDFs.
- **Region:** an EU resource (West Europe was used in the measurement). The key lives in Secrets
  Manager and reaches the worker only, like every other vendor key; it never appears in a log line.
- **Microsoft becomes a processor of student transcripts.** **Launch gate, enforced in code like
  `TRANSCRIPT_JEV_ENABLED`:** a setting, default off, refuses to send a real student's transcript to
  Azure until the owner records that Microsoft's data-processing terms are reviewed. Until then only
  official samples and the owner's own transcript are read. Retention and training terms are
  **Unverified** here and belong to that review.
- **Cost:** list price is roughly $10 per 1,000 pages for Layout — **Unverified** (the pricing page was
  not fetched). A three-page transcript costs about three cents, read once; a retake costs one page.
- **Known weakness, accepted:** Azure reads Azerbaijani ə as e or a (46% of Azerbaijani titles exact;
  57% with an Azerbaijani hint). It costs little under R4/R5, because a translation is in English and
  digits are unaffected — and the summary screen never asks about spelling (tailored spec §3.1 item 3).
- **A cell's confidence is the lowest confidence of the words in it.** An empty cell has none; it is a
  blank, which §6.1's checks treat as a missing value, never as a zero.
- **Language hint:** when the student says the upload is an original in Azerbaijani, Turkish or
  Russian, the request carries that locale (it moved Azerbaijani titles from 46% to 57% exact).
- **The API version is pinned.** Microsoft can improve the Layout model under the same name; a new
  version is adopted only after the harness (§8) is re-run on it, and readings record the version that
  produced them.
- **When Azure is down or slow:** the call is retried with backoff, reusing the worker's existing retry
  path; after that the reading is marked delayed — the student sees "still reading your transcript",
  every mark stays "waiting for your transcript" (§6.4), and the reading resumes when Azure answers.
  There is **no silent fallback** to another reader: a second reader is a measured decision (R10), not
  an outage plan.
- **The reader sits behind one interface** (`read_pages` → `OcrPage`), so replacing Azure, or adding
  OvisOCR2 beside it (R10), changes one module. The harness (§6.5, §8) decides any change.

### 4.1 Untrusted files are still parsed where there is nothing to steal

The current design runs the parser in a Lambda with no database secret and no API key, because "the
process parsing untrusted files holds nothing to steal" (tailored spec §3.1). The redesign keeps that
property; it only removes PaddleOCR from inside it.
- **A small, secretless parser function replaces the OCR Lambda:** it counts and splits PDF pages, reads
  the text layer with `pdfplumber`, renders a page image where a scan or a crop needs one, converts
  HEIC where it can, and computes each page's digest (§3.1). It reads cleared uploads and nothing else,
  as the OCR Lambda does today, in the same subnets with no route to the internet — so the existing
  network stays; only its 10,240 MB memory size and the PaddleOCR image go.
- **The worker only talks to Azure**, sending page bytes it received from the parser; it never opens a
  PDF itself. The CV path's `pypdf` reading inside the worker (`apps/documents/ingestion.py`) is
  unchanged and out of scope here.
- The page-image renderer is chosen for its licence: `pypdfium2` (Apache-2.0/BSD) over PyMuPDF (AGPL),
  **Unverified** until its licence file is read when the plan is written.

## 5. The quality gate

Runs on the reader's own output — Azure's words and polygons for a scan or photo, so there is no
second image-analysis step. A text-layer page (R9) skips the image reasons (`text_too_small`,
`unreadable`, `cut_off`): its text is exact. `not_a_transcript` and `page_missing` apply to every page.
Every refusal names one reason from a fixed list, shown in the student's language with what to do.

| Reason | Signal | Message (English) |
|---|---|---|
| `text_too_small` | median word height below a floor in pixels | "The text is too small to read. Retake closer, or upload the PDF your university gave you." |
| `unreadable` | page mean word confidence below a floor | "We can't read this page clearly. Retake it in good light, flat and in focus." |
| `cut_off` | words or table cells touching the image edge | "Part of the page is cut off. Retake it with all four edges visible." |
| `not_a_transcript` | no table and no course-like rows on the page | "This page doesn't look like a transcript. Upload the page with your courses and grades." |
| `page_missing` | a printed "page X of Y" not covered, or a printed grading-scale reference with no scale page | "Page 2 of 3 is missing." / "Upload the page with the grading scale." |
| `unsupported_file` | not a PDF, PNG or JPEG, or over 10 MB (existing limit) | "Upload a PDF, PNG or JPEG under 10 MB." |

- **Thresholds are set by measurement, not copied.** Vendors' defaults (ABBYY ready-for-OCR at 0.6,
  Veryfi review below 0.8, OCR floors of 12–15 px text) are starting points only. The eval set gains
  degraded copies of its clean pages — blurred, downscaled, glare, skewed, edge-cropped — and each
  threshold sits where reading quality measurably drops, checked against the two real bad pages
  (Mersin at 129 ppi, St Petersburg at ~6 px text).
- **Retry budget (R3):** each page may be retaken twice. A third failure keeps every row that was
  readable and asks the student to type the flagged cells.
- **Never refused for these alone:** a tilted page, and a page with a stamp over some cells (those
  cells are flagged instead, §6.3). Whether Azure pairs rows correctly on a tilted page is part of
  §9 gate 3; the current reader needed straightening for it.

## 6. After reading: checks, then the few questions

### 6.1 Checks the document lets us make

Kept from the current reader (`apps/documents/transcript_checks.py`): course credits against every
printed credit total, exact — where none is printed the screen says "not checked"; the overall grade
outside its stated scale; a course credit outside a sane range; a word mixing Latin and Cyrillic.

**Added:**
- **Point–letter consistency against the institution's grading table.** Azerbaijani transcripts print
  points and a letter per course. The national 2008 bands (91–100 A … under 51 F), the 1999–2008
  bands, and the private universities' own scales (Khazar, BHOS, ADA's 4.0, UFAZ's 0–20) are
  stored as data keyed by institution and date range
  (`2026-10-03-azerbaijan-e-diploma-and-grading-scales.md`; the 2008 order's text is **Unverified**
  there). A row whose points and letter disagree is flagged. Turkish letter grades per course have no
  points beside them, so the check runs only where both are printed. An institution or a year we hold
  no table for gets "not checked", never a guessed scale — the same rule as a missing credit total.
- **Page completeness** from the document itself (§5 `page_missing`).

### 6.2 What is never done

A failed check is shown, never repaired. No value is written that the document did not print. A typed
cell is stored as typed.

### 6.3 What the student is asked

On the summary screen, below the four numbers, only:
- cells in a row that failed a check (§6.1);
- **numeric cells** — credits, grades, points — whose Azure confidence is below a floor set by
  measurement. Measured on the earlier run: confidence below 0.8 flagged 71–100% of Azure's wrong
  Azerbaijani lines. Titles are never asked about for spelling;
- cells left unreadable after the retake budget (R3), to type.

The expected count on an English or translated transcript is zero to three cells (§8).

**Accepted practice, with one condition.** Asking the uploader about only the doubtful fields is used
in production (Expensify contacts the user only when a receipt "needs attention"; Identomat skips its
review page when every field came from a trusted source), though most consumer apps show every field
and document platforms send doubtful fields to their own staff. The condition, from the research:
highlighting a few cells makes people find those errors and miss the rest (Vertanen & Kristensson,
CHI 2008; a radiology review), so it only works if the flags catch nearly every real error. §6.1's
checks carry most of that; §6.5 measures whether together they are enough.

**How each asked cell is shown (R11):**
- the crop of the original cell beside the stored value, and the reason in plain words ("the credits
  don't add up to the total printed on page 2"), never a confidence percentage;
- an explicit choice per cell — *matches*, *fix*, *can't read* — with nothing pre-selected and no
  "confirm all";
- fixing is one field away, and the checks re-run after every edit;
- the reader's value is kept beside the student's (the document stays the authority, and the pair
  is what §6.5 and the harness learn from);
- unflagged cells are never labelled "verified".

### 6.4 Order with the search (R7)

Whichever finishes first is shown. Until the reading is accepted, every requirement or eligibility
mark that needs it says "waiting for your transcript"; none is decided on a half-read transcript.
Accepting updates them and notifies the student. A programme list served from the catalogue can be
ready in seconds; a thin slice's crawl takes longer; a retake waits on the student — the design
assumes no order.

### 6.5 The audit (R12)

**What it answers:** did a wrong value reach the student's record without being flagged? Only our own
audit can say — no published figure exists for how often uploaders' pre-filled values are wrong.

**What a person does with one sampled transcript (about 10–15 minutes):** open the original beside
the stored reading and check every cell that decides something — each course's credits, grade and
in-progress status, and the four headline numbers. Course-title spelling and layout are not checked.
Each wrong stored value is marked as one of:
- **missed** — wrong and never flagged (what the audit exists to find);
- **flagged and fixed** — the student corrected it;
- **flagged, confirmed wrong** — the student chose *matches* on a wrong value (rubber-stamping, the
  other risk the research names).

**Who, and inside which tenant.** A transcript is a person's data, so the audit never crosses tenants
(`CLAUDE.md`, "The rule for crossing tenants"): an agency's sample is audited by that agency's own
counsellor inside its tenant; a direct-to-student transcript by the platform's own staff in the
platform's tenant. When the owner audits an agency's sample, it is under a `SupportGrant` for that
agency — time-boxed, reason-carrying ("transcript audit") and alarmed, like any support access. The
privacy notice (the consent spec, `2026-10-03-consent-and-privacy-notice-design.md`) states that a
person may review a sample of transcripts for accuracy.

**How often:** about 1 transcript in 20 at launch, down to 1 in 100
once the measured missed rate is low, and a rare spot check — or none — once 50–100 audits show it near
zero. The sample is drawn at random from accepted readings. The auditor reads the transcript's
language: a certified English translation is easy; an Azerbaijani or Russian original needs someone
who reads it. **Nothing waits on the audit**: it happens after the student has moved on, so the owner
rule of 2026-09-23 (no person in the pipeline) holds. A wrong value found is corrected in the
student's record and the student is told.

**What a finding changes — the model cannot be retrained, these can:**
1. **The flag floor** (§6.3): misses clustered just above it move it up — more cells asked, fewer slip.
2. **The checks** (§6.1): a pattern (ECTS and local credits swapped on one university's layout) becomes
   a rule.
3. **The quality gate** (§5): misses from dim or small photos tighten its thresholds.
4. **The reader** (R10): any trigger below adds OvisOCR2 as a second reader, or replaces Azure, through
   the harness.
5. **Azure's custom extraction models**, trained on our own labelled documents, if one layout is common
   and troublesome — **Unverified**: Microsoft's current docs were not read for this.
6. **The students affected:** an error tied to one university's layout re-checks every transcript from
   that university, not only the audited one.

**Triggers to revisit the reader:** more than about 1 audited transcript in 20 carries a missed value;
students are asked about more than three cells on average (§9 gate 5); or volume makes a GPU cheaper
than Azure's per-page price. Every audited transcript also joins the harness's answer key, which is
how §9 gate 1's real transcripts keep growing after launch.

### 6.6 Values the student types or fixes

A cell the student fixes, and a cell typed after the retake budget (R3), is the student's own claim —
the same footing as a grade a student self-reports on the US STARS record, which universities later
check against the official transcript (`2026-10-04-end-user-confirmation-of-low-confidence-fields.md`).
So:
- it is stored as **student-entered**, beside what the reader read (or "unreadable"), never overwriting it;
- a requirement or eligibility mark that rests on a student-entered value says so ("based on a grade
  you entered"), because the university will check it against the official transcript;
- a transcript with **more than a few student-entered cells, or any that raises a credit total or grade
  above what was read,** is always audited (§6.5), not sampled;
- the checks (§6.1) run on student-entered values like any other — a typed credit that breaks a printed
  total is flagged again.
A whole transcript typed by hand (every page refused twice) is allowed on the same footing, labelled
self-reported throughout.

### 6.7 What the summary screen does not hold up

Titles feed the course-to-topic labels (tailored spec §4.2). An Azerbaijani original read with ə as
e/a gives "Ehtimal nezeriyyesi" for "Ehtimal nəzəriyyəsi" — the label question reads meaning, not
spelling, so it is not asked about. Whether those misspellings change a label is measured on the
labelled set before the topic labels go live (**Unverified** today).

## 7. Jev and personal data — unchanged

Jev still labels columns (which one is ECTS, which is the local system) and rows (course, heading,
total) through `apps/research/decisions.py`, and still receives only table cells and candidate lines
with the student's name, date of birth and ID-like numbers removed before any call. Its launch gate
(`TRANSCRIPT_JEV_ENABLED`, TypeSafe DPA, OpenRouter terms) is unchanged. Azure, unlike Jev, sees the
whole page, which is why §4 has its own gate.

### 7.1 Limits and cost

- **50 pages per paid academic-year cycle** (owner 2026-10-04): a student pays the platform fee once
  per academic-year cycle, and that payment buys 50 pages — every page read counts,
  whether by Azure or from a text layer, and every retake counts as a page. It bounds what one
  profile can cost (about $0.50 at the list price) and what someone abusing uploads can push through
  the reader. The 51st page is refused with a plain message ("you've reached the upload limit for this
  application cycle — contact us if you need more"); nothing already read is lost. A new paid cycle
  starts a fresh 50. Which record marks a paid cycle belongs to the fees design — today
  `concierge.ServiceEngagement` carries the `platform_fee`; the page count hangs off whatever that
  design names. It replaces today's
  10 readings an hour (`apps/documents/transcript.py::_RATE_LIMIT`). The count is stored with the
  student's transcript record, not in the rate-limit cache, because a cycle outlives any cache window.
- **Our own re-reads never count against the student:** an audit, a harness run, or a re-read after a
  pinned Azure version change. A version change does not re-read stored transcripts by itself; a
  re-read is a decision taken on the harness result, and its readings are compared with the stored
  ones before any record changes.
- A per-tenant daily page ceiling stops many profiles abused at once (an agency account, or a burst of
  sign-ups) from billing without bound; when it is hit, readings wait (§4's delayed state), they are
  not dropped.
- Azure's raw response is not stored beyond what the reading needs (lines, cells, confidences,
  polygons): it carries the student's name and identifiers from the page. The crop shown on the
  confirm screen is cut from the original upload in the evidence bucket when shown, not stored again.
- The worker's dead-letter gap recorded at the 2026-09-27 merge — a worker killed on its last delivery
  leaves a transcript "available" forever — still applies to this path and is closed here: a reading
  stuck in "reading" past a timeout is marked delayed and re-queued.

## 8. Why this reader — measured 2026-10-03

Same pages, same answer key, `score_rows.py` (row-level) in the eval harness. *Paired* = a key row
whose title, credits and grade all sit in one output row. The real Turkish set is seven English-language
Diploma Supplements (300 rows); the generated set is six invented Azerbaijani and Russian pages, clean,
scanned and photographed (279 rows).

| Reader | Real Turkish: paired / wrong numbers / dropped | Generated az/ru: paired | Notes |
|---|---|---|---|
| **Azure Layout** | **96.3% / 7 / 4** | 92.1% (ə→e/a: 39 letters) | per-word confidence; no infrastructure; run-to-run repeatability not yet measured |
| PaddleOCR-VL-1.6 (self-hosted VLM) | 97.3% / 6 / 2 | 96.4% | invented a page of fluent text on the St Petersburg specimen; 9 of 27 pages changed between two identical runs, including a credit (3→2) and a grade (DC→CC); needs a GPU |
| Mistral OCR | 80.7% / 31 / 27 | 100% | grades misread (DC→"SC", G→"Q"); credits 6→"0"; 25 invented rows on Mersin |
| Google Document AI, Layout Parser | 44.3% / 154 / 13 | 97.5% | merges two courses into one row; no confidence or boxes in its output |
| PP-StructureV3 (today's production) | 57.7% / 123 / 4 | 87.5% | as run in the eval harness |
| Surya (reference only) | 97.0% / 7 / 2 | 100% | licence free only under ~$2–5M revenue and bars competing use |

Also measured: **two VLMs agreeing is not proof** — where PaddleOCR-VL and Surya agreed, 5% of rows
were still wrong, both having "corrected" the page's own typos ("Goegraphy"→"Geography") and both
having read a printed CB as BA. All readers left erased grades blank on the tampered pages except
Google, whose row merging attached a neighbour's grade. No reader in this table read the Mersin scan
usefully (OvisOCR2, below, paired 72%): a page like it is what the quality gate exists to refuse.

**Measured 2026-10-03/04, after the table above was written:**

| Reader | Real Turkish: paired / wrong numbers / dropped | Generated az/ru: paired | Notes |
|---|---|---|---|
| OvisOCR2 (0.8B, Apache-2.0, self-hosted) | **98.0% / 4 / 2** | 94.6% | the same answer on all 27 pages across two runs; best on Mersin (72% paired, every other reader 0–55%); returned nothing on St Petersburg rather than inventing; passed all three tampered pages |
| Qwen3.5-4B (FP8 on an 8 GB GPU) | 84.0% / 24 / 24 | 99.3% | **invented an erased grade** ("зачтено") on a tampered page; the same answer twice; bf16 not run (the AWS GPU quota request was declined) |

**OvisOCR2 is the most accurate and the most stable reader measured, and still not the launch reader,
for two measured reasons:**
- **Its own certainty does not point at its mistakes.** Taking each row's lowest token probability over
  its number and grade cells, on 600 paired rows with 14 wrong: flagging below 0.99 caught 2 of the 14
  while asking about 86 right rows; below 0.8 it caught 1. It is confidently wrong, so it cannot drive
  §6.3 — Azure's confidence can.
- **It needs a GPU we cannot get yet.** On six CPU threads it had not finished one page after 34
  minutes (the GPU read the same page in 11 seconds), and AWS declined the GPU quota. Hence R10:
  second reader when a GPU exists — its disagreements with Azure, two readers that err differently,
  become questions.

**Why Azure over PaddleOCR-VL at near-equal accuracy:** confidence per word (what §6.3 runs on), no
GPU to run and nothing to keep warm, and no measured drift — PaddleOCR-VL's drift is measured, Azure's
repeatability is a §9 gate. The trade is a new processor (§4).

## 9. Gates before real students

1. **Real transcripts.** At least 10 consented real transcripts — certified English translations and
   originals, Azerbaijani and Turkish — keyed by hand. The generated Azerbaijani pages are not
   evidence for real ones.
2. **Text-layer PDFs (R9).** On born-digital PDFs (including one 2026 myGov e-diploma if a consenting
   graduate has one): the text-layer check accepts every clean layer and refuses every broken one, and
   rows read from the layer match the hand key.
3. **Quality-gate thresholds** set on the degraded set (§5); a gate that refuses a page the reader
   reads correctly counts as an error too.
4. **Repeatability.** Each real page read twice by Azure; any difference is counted.
5. **Question count.** On the real set, the median number of cells a student is asked about (§6.3);
   the target is zero to three per transcript.
6. **Processor review** (§4) and the existing Jev launch gate (§7).
7. **The audit is ready (§6.5)** — the sampling, the per-cell verdicts and the record of them exist
   before the first real student, so the first transcripts are audited at the launch rate.
8. **A real phone upload** from an iPhone and an Android phone, through the actual upload page: the
   file type that arrives, and that it is read (§3.1).

## 10. What changes in the code

- `apps/documents/ocr.py`: invokes the parser function (§4.1) as it invokes the OCR Lambda today, then
  sends scanned pages to Azure; `OcrPage` gains per-cell confidence, polygons and each page's source.
- New: the quality gate (refusal reasons, per-page retake count), and the upload's original/translation
  label.
- New: the text-layer path (R9) — `pdfplumber` tables into `OcrPage`, and its quality check.
- New: the confirm-screen data (R11) — per asked cell, its crop's page and polygon, the reason, the
  student's choice, and the reader's value kept beside the student's.
- New: the audit (§6.5) — random sampling of accepted readings, a staff-only view of the original
  beside the stored values, and a per-cell verdict (*missed* / *flagged and fixed* / *flagged,
  confirmed wrong*) stored per audited reading, with its erasure entry.
- `apps/documents/transcript_checks.py`: the point–letter check and page completeness; grading tables
  as data.
- The summary screen's highlight list gains low-confidence numeric cells and typed cells.
- `ocr/` becomes the small parser of §4.1: PaddleOCR, its models and `read_pages.py`'s OCR are deleted;
  page counting and splitting, `pdfplumber` text-layer reading, page rendering, HEIC conversion and
  digests replace them. The Lambda keeps its network and role, with a smaller memory size; the settings
  only PaddleOCR read are deleted.
- `TranscriptReading` changes shape (§3.1): one reading per transcript, a page table naming each page's
  upload, slot, retake count, source (*text layer* / *Azure* + API version) and refusal reason; per cell,
  the reader's value, its confidence, its polygon and, where present, the student-entered value (§6.6).
  Its RLS and erasure entries (`apps/audit/redaction.py` REDACT/KEEP) follow every new field.
- Unchanged: Jev questions and the personal-data trimming before any Jev call.

## 11. Open

- Microsoft's data-processing terms for Document Intelligence (retention, training, region) — the §4
  launch gate.
- A GPU for OvisOCR2 (R10): a second AWS quota request with a justification, or a GPU host outside AWS
  (a new processor).
- Azure's Layout price and the per-tenant daily page ceiling's value (§7.1).
- In agency (B2B) mode, who pays the cycle that R13 requires before upload — the student or the agency —
  is the fees design's; this spec only needs "this profile's cycle is paid".
- R13 changes the order the tailored-programme spec describes (onboarding questions and the search while
  the transcript is read): both now start after payment. That spec's §3.1 flow gets the same step 0 when
  this is built; until then this line is the record.
- Whether Azure's custom extraction models are worth training on audited transcripts (§6.5 item 5).
- Whether the summary screen's "confirm" step and the questions screen can be one screen; that belongs
  to the presentation-layer decision (`CLAUDE.md`, "Frontend and design").
