# Reading a student's own documents into facts — design

**Status:** design. Agreed with the owner in conversation on 2026-10-12. Not built.
**Attaches at:** `apps/portals/fact_reading.py::request_fact_reading`, a no-op hook that is already
in master (co-pilot plan 5, `docs/superpowers/plans/2026-10-09-copilot-guidance-5-form-learning.md`).
**Builds on:**
- the transcript reader, for the Azure path, page budgets and the OCR Lambda
  (`docs/superpowers/specs/2026-10-03-transcript-reader-redesign-design.md`);
- the co-pilot spec, for packets, hints and the panel
  (`docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md`);
- the fact ledger (`apps/documents/models.py::VerifiedFact`).

## 1. Purpose

Portals ask for a date of birth, a passport number, a nationality, a degree title or an IELTS score,
again and again, on every application. Today:
- the co-pilot shows a red "You fill this" box for every fact we do not hold;
- for identity data there is **nowhere to hold it**. `VerifiedFact` has no key for a date of birth,
  a passport number, a nationality, a place of birth or a sex, so the co-pilot cannot even
  recognise a "Date of birth" box as one.

The owner's direction (2026-10-09, refined 2026-10-12): the student uploads a passport or ID card,
a diploma or a language certificate once. The platform reads it in the background, and every
portal after that is filled from it. **Success** means a student never types something they have
already uploaded, and is never asked about the same value twice.

## 2. Owner decisions (2026-10-12)

| # | Decision |
|---|---|
| D1 | Scope of the first version: **passport or ID card, diploma, language certificate.** Transcripts keep their own reader. |
| D2 | **Least friction:** no review screen at upload. Reading happens in the background with nothing to press. |
| D3 | **A value we can prove becomes a fact without a confirm press.** "Proven" is defined per document type in §5. The safety net is the proof itself, plus the student seeing every filled box on the portal page before pressing Submit (the glass box). |
| D4 | **A doubtful value never blocks anything.** It is offered at the moment a portal asks ("We read X, use it?"), where one tap fills it and confirms it. The dashboard shows a quiet "N details to check" line and a "Your details" list where any value can be edited. |
| D5 | **The student's own entry always wins.** A later reading never overwrites a value the student typed or edited; a disagreement becomes a detail to check. |
| D6 | **Reader for passports and ID cards:** Azure Document Intelligence `prebuilt-idDocument`, with the strip's check digits verified by our own code. No language model ever sees a passport. |
| D7 | **Reader for diplomas and certificates:** Azure reads every page **as an image**. Two readers from different model families pick the fields out of that text, and every value must be a verbatim quote of it. A born-digital PDF's **visible** text layer is used only as a cross-check, never as the source (§5.3). |

Context: other products converge on "scan once, prefilled, editable, confirm" (airline passport
scanning, Chrome's passport autofill). UCAS-style platforms only store the file. D2–D4 cut the
confirm step down to the cases where it carries information.

## 3. What the student sees

1. **Upload.** They upload as today, on the dashboard's documents list. Nothing else changes and there is nothing to press.
2. **On a portal.** The co-pilot fills the boxes and marks each one "from your passport" (or "from your diploma", or "from your IELTS result").
   - A doubtful value appears in the red box as "We read **12.04.1999** from your passport. Use it?" One tap confirms that single value and fills it.
   - With nothing uploaded, the box says "Upload your passport once and we'll fill this on every portal", with a link to the dashboard.
3. **On the dashboard:**
   - **"Your details"** lists every fact read from a document: the value, the document it came from, and an edit control. An edit is the student's own entry from then on (D5).
   - **"N details to check"** appears only when doubtful values exist. Each one is shown with the snippet it was read from, as a Use / Correct pair. It is never a gate.
   - **"We couldn't read this — upload a clearer photo"** appears beside an upload whose read failed (§6.4).
   - **"This passport doesn't look like yours"** appears for an ownership mismatch (§6.2).

Dashboard strings are English, like the rest of the dashboard's templates, which are not
translated today. Panel strings (plan 3) go into the extension's four-language catalogue.

## 4. Vocabulary

Payload keys live in `apps/documents/verification.py::_SPECS`. `LEARNABLE_FIELDS`
(`apps/portals/profile.py`) is computed from them, so every key below becomes a field the co-pilot
can learn to map with no further change.

### 4.1 IDENTITY (existing category; keys added)

| Key | Value |
|---|---|
| `identity.given_names` | Given names **as printed** on the document's page, with diacritics (`ŞƏHRİYAR`), never the strip's transliteration. |
| `identity.surname` | The surname, as printed. |
| `identity.date_of_birth` | An ISO date, `YYYY-MM-DD`. |
| `identity.place_of_birth` | As printed. Some documents print only a country; that is kept as printed. |
| `identity.sex` | `M`, `F` or `X`, as the document states it. The co-pilot's option matching turns it into the portal's choice. |
| `identity.citizenship` | The English country name (`Azerbaijan`), mapped from the ICAO code through ISO 3166 (`D`→Germany, `GBD`/`GBN`/`GBO`/`GBP`/`GBS`→United Kingdom, Kosovo's `UNK`→Kosovo). The key is `citizenship` because `CVContent.personal_information` already carries one, and the SISGP template prints it as text. `XXA` (stateless) and `XXB`/`XXC` (refugee) are always **doubtful**: a refugee travel document's nationality field is not a citizenship. |

`identity.full_name` and `identity.orcid` are unchanged and still come from the CV.
`date_of_birth`, `sex` and `citizenship` already exist on `CVContent.personal_information`, with no
source until now. The new keys are **carried, not compared**: a CV's date of birth is a `CVDate`
that may be partial ("1999-04"), so comparing it against a full date would read CONFLICTING over
precision, not over a contradiction. Comparing them is a follow-up once a date comparison that
understands precision exists.

### 4.2 ID_DOCUMENT (new category: a CHECK-constraint migration)

A row per document. A student may hold several (dual nationals, or an old passport and its renewal).

| Key | Value |
|---|---|
| `id_document.document_type` | `passport`, `national_id` or `residence_permit` (Azure's document type). |
| `id_document.number` | As printed. |
| `id_document.issuing_country` | The English country name, mapped as for citizenship. |
| `id_document.issue_date` | ISO date. |
| `id_document.expiry_date` | ISO date. |
| `id_document.issuing_authority` | As printed. |

**Which document a portal gets.** `verified_values` flattens one row per key, and "last row wins"
is wrong here. For `id_document.*` it picks:
1. the student's chosen primary document, if they chose one;
2. otherwise, the unexpired **passport** with the latest expiry;
3. otherwise, the unexpired document of any type with the latest expiry.

An expired document is never served to a portal. If only expired ones exist, the box is a hint:
"Your passport expired on 03.2026 — upload the new one." The dashboard asks "Which passport should
we use?" **only** when two or more unexpired passports exist. That is the dual-national case, and
it is the only question this design ever puts to a student unprompted.

### 4.3 LANGUAGE (existing category; keys added)

`test_variant` (`Academic` / `General Training`; the same key carries TOEFL `iBT` / `Essentials`),
`test_date`, `certificate_number` (the IELTS TRF number, the TOEFL appointment number, …),
`score_listening`, `score_reading`, `score_writing` and `score_speaking`. `test_score` stays the
overall score.

Each sitting is its own row. A portal gets the latest sitting by `test_date` across all tests (ruled during the build: a portal box does not say which test it means, so "the requested test" cannot be known). No validity
period is derived: "IELTS is valid for two years" is a convention the portal enforces, not something
printed on the result.

### 4.4 EDUCATION (existing; one key added)

`diploma_number`: the series and number CIS diplomas print, which portals ask for. The diploma
otherwise fills keys that already exist: `degree_as_awarded`, `institution_original`, `end_date`
(the graduation date), `grade_native`, and `degree_english` / `institution_english` **only when the
document prints them in English** (bilingual diplomas, or an uploaded certified translation, §5.3).
`grade_scale` is filled only if printed, and **never inferred**.

## 5. Reading

All reading runs in the document worker after a clean upload is promoted. It goes in
`apps/documents/document_worker.py`'s dispatch, beside `_ingest_cv` and `process_upload`, for the
kinds `PASSPORT`, `DIPLOMA` and `LANGUAGE_CERTIFICATE`.

Azure calls happen **outside** any long transaction, split into short ones exactly as
`transcript_pages` does. Only the promoted copy is read (`storage.read_upload`). The OCR Lambda
stays the only thing that parses the untrusted file: it splits pages, renders them and converts HEIC.

### 5.1 The page budget and the switch

- **Page budget.** Each document kind has a page cap (passport 4 pages, diploma 4, certificate 2;
  settings), and only the first N pages are sent.
  - A passport upload goes to Azure in **one** call limited to the first N pages (Azure's `pages`
    parameter). Azure finds the data page among them, and only those pages are billed. A booklet
    scan whose data page lies beyond the cap fails as `no_data_page`.
  - Pages count against the tenant's daily Azure page ceiling, which is shared with the transcript
    reader (`TRANSCRIPT_TENANT_DAILY_AZURE_PAGES`, reused under its existing name; the comment says
    it now counts both readers).
  - Over the ceiling, the reading is DELAYED exactly as a transcript page is.
  - The cost is about a cent a page; confirm the price on the pricing page before launch.
- **Per-student limit.** 20 document readings an hour (`rate_limited`, bucket `fact-reading`).
  Our own re-reads (a new reader version) never count against it.
- **The switch.** `FACT_READING_ENABLED` ships off. Azure also stays behind the existing
  `TRANSCRIPT_AZURE_ENABLED` gate, which now serves both readers. It keeps its name: renaming it
  would move the deploy configuration for no gain.

### 5.2 Passport and ID card

1. `prebuilt-idDocument` (API version pinned with the existing `AZURE_DI_API_VERSION`).
   `apps/documents/azure_layout.py` gains a model argument; today it hardcodes `prebuilt-layout`.
2. **The strip.** Our code reads the raw strip text from the `MachineReadableZone` field's
   `content`. It recognises TD3 (passports, 2×44 characters) and TD1 (ID cards, 3×30), and
   verifies the ICAO 9303 check digits (7-3-1 weights) of the document number, the date of birth,
   the expiry date and the composite digit.
   - A strip that fails the composite digit proves nothing.
   - If Azure returns no raw strip, nothing from the strip is proven.
   - This is about 30 lines of standard-library code with the ICAO specimen strings as tests; no
     dependency.
3. **Proven, per value.**
   - **Number, date of birth, expiry.** Proven when the strip's own check digit for the value passes
     **and** the printed page agrees.
   - **Nationality and sex.** No check digit covers them: the composite digit skips both positions,
     in TD3 and in TD1 alike. They are proven when the strip and the printed page agree — two
     independent readings of two zones — and the strip's value is in the closed vocabulary (a valid
     ICAO code, or `M`/`F`/`<`). `<` is stored as `X`.
   - Agreement on dates is equality after parsing. The strip's two-digit year resolves its century
     from the printed date. Without a printed date, the date of birth is the year that is not in
     the future and the expiry is `20YY`.
   - **Names.** Proven when the printed name, transliterated, **starts with** the strip's name.
     The strip truncates long names at 39 characters. Transliteration uses the ICAO 9303 Part 3
     table plus a small per-issuing-country table of alternatives, because issuers differ: an
     Azerbaijani `Ə` and a German `Ü` each have more than one strip form. The per-country entries
     come from the specimens and the consented set (§9), never from guesswork. Any alternative
     matching counts as agreement. The **printed** form is what is stored.
   - **Plausibility.** A date is never proven when it is implausible, whatever the strip says.
     The strip carries only two digits of the year, so the century rests on the printed page alone.
     - A date of birth must be today or earlier, and later than 120 years ago.
     - An expiry must fall within ten years before today and twenty years after.
     - An issue date must be today or earlier.

     Otherwise the value is doubtful (`implausible`).
   - **Names follow ICAO punctuation.** A printed space or hyphen is a separator in the strip.
     Apostrophes, dots and commas are not represented in the strip at all. A long name truncated
     in the strip is a prefix only when the strip actually ran out of room. The surname is never
     truncated when the strip shows where the given names begin (`<<`).
   - **Place of birth, issue date, issuing authority.** These are not in the strip. They are proven
     only when Azure's field confidence is at or above the threshold (setting, default 0.95) **and**
     every word of the value is on the page at or above the same word confidence. Otherwise they
     are doubtful.
4. **Ownership check.** The read is compared with the names we already hold for the student:
   the account holder's own name, `identity.full_name` from the CV, and names on earlier identity
   documents. Ruled during the build, 2026-10-12, after an adversarial review.
   - It matches only when **both** of these hold:
     - the first given name (printed, else the strip's) loosely matches the first or the last word
       of a known name;
     - a surname word loosely matches some known-name word.
   - "Loosely" means after the strip spelling, and after the transliteration pairs KH/X, SH/S,
     CH/C, ZH/J, GH/G and Q/G. It is then equality, or a similarity ratio of at least 0.8 with
     lengths within one letter.
   - Why this shape:
     - A parent's passport usually shares the surname. A patronymic ("Rauf qızı") sits in the
       middle of a full name. A parent's given name often becomes a child's surname
       (Həsən → Hasanov).
     - CV and passport spellings differ routinely (Orkhan/Orxan, Mamedov/Mammadov). Name order
       differs too (surname first).
   - On a mismatch, **no fact is written** from this document, and the dashboard says "This
     passport doesn't look like yours". The same happens when we hold names but the read has
     neither a given name nor a surname. Ruled during the build, after review showed a pre-filled
     "Correct" form could confirm a parent's citizenship as the student's.
   - With no name on file at all, every value is doubtful (`owner_unknown`). The dashboard asks the
     student to add their name and upload again; a re-upload of the same file is read again.
   - A student whose name differs from every name we hold types those values by hand. That is the
     accepted cost. It is rare, because any one whole known name matching is enough, and the account
     name is current.
5. **Wrong document.** If Azure returns a document type that is not an identity document, or no
   data page within the cap, the read fails as `not_an_id_document` (§6.4).

### 5.3 Diploma and language certificate

1. **Text.** Every page, up to the cap, goes to Azure `prebuilt-layout` **as an image**, including
   born-digital PDFs.
   - The text the readers see is therefore the text a human sees on the page.
   - Invisible text never reaches a reader. That covers white-on-white text, tiny fonts, off-page
     text, and the render-mode-3 layer that scanner apps add.
   - **The rendered image is the boundary** (as built, after a 31-recipe adversarial review): what
     Azure reads is a 150 dpi picture of the page. Tiny text below the size floor is still legible
     at that resolution (2.5–3.9 pt measured), so text objects that fail the painted test are
     removed from the page before it is rendered. Size means the glyph's height (the font size
     times the text matrix's smaller scale), so stretching text sideways does not get it through.
     Removal is by size and render mode only, never by colour: white text on a dark band is real.
   - Two residuals are accepted: text nested inside a Form XObject, and annotation or form-field
     text, can still reach the readers. This is accepted on the threat model, not on the outcome.
     The uploader is the student, the person the facts describe, who can already set any value on
     the dashboard (D5). An injection can at most make a value "proven" that the student could type
     anyway, and proven never means genuine (§8).
   - A hostile file cannot exhaust the isolated parser. Image sizes are checked first, each rendered
     side is capped at 10,000 px, and pages are rendered one at a time. An answer that would pass
     the parser's size limit is refused as `page_too_large`.
   - This is the documented defence against hidden-text prompt injection, and it also avoids
     trusting another app's OCR.
2. **Before the readers.** Code replaces the student's known identifiers in the text with a
   placeholder: the `identity.*` values and the ID document numbers already held. The readers need
   the institution, the degree, the dates, the grades and the scores, not who the person is.
   Generic digit runs are **not** stripped, because the diploma number and the certificate number
   are exactly what the readers must quote. Verification (step 4) runs against the **unstripped**
   text. The placeholder exists only in the copy sent to the readers, for that one call. Stored
   facts and everything the co-pilot types are the full, unstripped values.
3. **Two readers from different model families.** They use the reader-pair setting shared with the
   catalogue reader (slice 2: DeepSeek V4.1 Flash and GPT-luna at the time of writing; the list is
   configuration). Each:
   - fills a closed, per-kind schema (Pydantic, `extra="forbid"`, capped output tokens);
   - receives the text labelled as data, never as instructions — the reference pattern of
     `apps/research/extraction.py`;
   - quotes each value **verbatim** and picks a closed label for the document: `original`,
     `translation` or `bilingual`.

   The model quotes; **code normalises.** Dates go to ISO, scores to numbers, and the test name maps
   to a closed list:
   - IELTS, TOEFL, Duolingo, PTE;
   - Cambridge English (C1 Advanced, C2 Proficiency);
   - TestDaF, DELF/DALF, TOPIK, JLPT, HSK, YDS.

   An unknown test name is kept as printed and is doubtful.
4. **Proven, per value.**
   - Both readers quoted the same value, the quote is found verbatim in the Azure text, and every
     word of it was read by Azure at or above the word-confidence threshold.
   - **And, for a born-digital PDF**, the quote is also present in the page's **visible** text
     layer. That layer is pdfium's characters, keeping only text that is painted: render mode not
     3 (an outlined glyph with a visible stroke counts), a fill that is not near-white by luminance,
     a size of at least 4 pt, and a position inside the page's crop box in its own coordinates. It
     is a cross-check, not the boundary. A
     disagreement between the two makes the value doubtful. This catches OCR digit slips on exactly
     the values that matter, such as a band score or a GPA.
   - Anything else is doubtful. A disagreement between the readers is **not** sent to a third
     reader: the student is the cheaper and better tiebreak for their own diploma.
5. **Original or translation.** A `translation` document fills only the `*_english` keys and is
   marked as a translation. An `original` fills the `*_original` keys and the language-neutral
   ones. A `bilingual` document fills both.
6. **Which degree.** A diploma's values attach to the EDUCATION row with the same institution
   (`institution_original`, compared normalised) and the same graduation year. With no such row, the
   diploma creates one. A diploma never overwrites a key that row already holds. A disagreement is a
   detail to check, showing both the CV's value and the diploma's (D5).

## 6. From reading to facts

### 6.1 The reading record

`documents.DocumentReading` is a new tenant table: `ENABLE` + `FORCE ROW LEVEL SECURITY`, the
standard `tenant_isolation` policy, and composite `(tenant_id, student_id)` guards, as in
`documents/0026`. It holds:
- `document` (the `DocumentVersion`), `kind` and `state` (`QUEUED`, `READING`, `DELAYED`, `READ`,
  `FAILED`), plus `failure` (a closed code), `attempts` and `next_attempt_at`;
- `file_sha256`: the same bytes are never read twice, so a re-upload of an identical file is free;
- `reader_version`;
- `values`: per key, the normalised value, the **snippet** it came from (the printed text, at most
  200 characters), `proven: bool` and `why` — a closed code such as `check_digit`,
  `readers_agree`, `low_confidence`, `readers_disagree`, `text_layer_differs`, `owner_mismatch`,
  `implausible`, `document_differs`, `older_document` or `student_entry_differs`.

It keeps no raw Azure output and no raw reader output. Azure deletes the analysed file within 24
hours under the Microsoft data-processing terms the transcript reader already relies on.

### 6.2 Writing the facts

In one short transaction after a read:
- **Proven value, no conflicting student entry.**
  - Written as a `VerifiedFact` with `source_tier=AUTHORITATIVE_DOCUMENT`,
    `source_ref="document:<DocumentVersion id>"`, `confirmed_by` = the student whose own document
    it is, and `confirmed_at` = now. The precedent is `evidence/facts.py::write_publication_fact`.
  - An `AuditEvent` `fact.read_from_document`, with `actor_kind=AGENT`, records that the machine
    proved it and no person pressed anything. A trail never claims a click that did not happen.
- **Doubtful value.** Written as an **unconfirmed** `VerifiedFact`; `verified_values` already skips
  those. It reaches a portal only through the one-tap offer (§7).
- **Precedence, per key:**
  1. the student's own entry (an edit, or a value they typed into the dashboard);
  2. the newest proven read;
  3. an older proven read.

  A new read **agreeing** with what is held writes nothing. "Newest" is ruled more strictly than the
  first draft said, after review found that guessing a document's age let an older passport's value
  win (2026-10-12):
  - A document's age is known **only** from its **confirmed** issue date. A doubtful date and the
    upload time never count.
  - A proven value from another document replaces the held one only when both ages are known and
    the new document is strictly newer. Equal ages → the later read wins.
  - An older document's differing value waits as a detail to check (`older_document`). So does a
    differing value whose order is unknown (`document_differs`). It is never dropped silently.
  - Name, citizenship and date of birth never switch silently, even from a newer document: a renewed
    passport with a new surname after a marriage is the student's to confirm.
  - A read differing from the student's own entry, including a correction of one key of an ID
    document, is always a detail to check (D5). A re-read never carries back a key the student owns.
  - A proof of a waiting value writes a new confirmed row under the proving document, never confirms
    the old row in place.
- **Expiry.** A proven `expiry_date` fills `DocumentVersion.expires_on` unless the student has
  typed one. The typed expiry form stays for the documents we do not read.

### 6.3 Ownership of the confirm

Only the student confirms or edits. This matches the existing `api/documents/facts/confirm`, which
deliberately has no staff path. In counsellor-prepares mode a counsellor may upload, but the
details to check stay the student's.

### 6.4 Failures

`FAILED` carries one closed code:
- `unreadable` — Azure found no text, or the image is below the transcript reader's quality gate;
- `not_an_id_document`;
- `no_data_page`;
- `wrong_kind` — the readers labelled a "diploma" as something else;
- `azure_unavailable` — retried with backoff, never shown until the third failure.

Each failure is one line beside the upload on the dashboard with a re-upload link. Nothing else
waits on it: the portal box simply stays "You fill this". A stuck `READING` row is resumed by the
same sweep as transcripts: `resume_transcript_readings` also resumes `DocumentReading` rows,
under its existing name.

## 7. The co-pilot

1. **The hook.** `request_fact_reading(application, fields)` maps each missing field to the document
   kind that can supply it: `identity.*` and `id_document.*` → PASSPORT, `language.*` →
   LANGUAGE_CERTIFICATE, `education.*` → DIPLOMA.
   - An upload of that kind with no `DocumentReading` is queued. This covers documents uploaded
     before this feature shipped, with no backfill job.
   - It is idempotent; it never calls Azure, and it never raises or blocks. It runs in the web
     process inside `mint_packet`, so it only enqueues.
2. **The packet.** A hint can carry `offer: {value, source_kind, fact_id}` when an unconfirmed read
   exists for its field, and `upload_kind` when nothing of the right kind is uploaded.
   `missing_fields` on the PACKET step is unchanged.
3. **One tap.** `POST /ext/applications/<application_id>/facts/<fact_id>/confirm` goes through `_device_endpoint`: the device
   token, an active membership and the deletion lock. It is accepted only when:
   - the fact is this student's, unconfirmed and not superseded;
   - **and** it was offered in the application's latest PACKET step, the same rule that serves
     uploads only when the latest packet named them.

   It writes the tapped value as a new confirmed row through `fact_writer.use_document_value`,
   superseding the waiting one, with the student as actor (`fact.confirmed`). It never calls
   `confirm_facts` in place, because a row confirmed in place keeps its old `created_at` and can
   lose to a later row, so the tapped value would not be the one served next (plan 2 ruling,
   amended 2026-10-14). It is rate limited (30 an hour), and answers with the value for the
   content script to type.
4. **Marks.** A box filled from a document-read fact is marked "from your passport", "from your
   diploma" or "from your IELTS result". The packet entry carries `source_kind`.
5. **Formats.** Dates, sex and country values go through plan 6's per-portal `value_formats` and
   `option_synonyms`. Nationality is stored as a code and rendered as the English country name for
   matching. That uses the country names the destination-country data already carries, never a new
   table.

## 8. Privacy and deletion

- **No language model sees a passport or an ID card**, only Azure and our own code. Diploma and
  certificate text reaches the reader pair with the student's identifiers stripped (§5.3).
- `DocumentReading` gets a `REDACT` entry (`values`, `file_sha256`) and its non-PII fields in the
  allow-list. `advance_deletion` deletes its rows inside the tenant block, as it does `PortalAnswer`.
  The facts themselves are already covered by `VerifiedFact`'s entry.
- **"Proven" means read correctly, not genuine.** Nothing in this design checks a document's
  authenticity, and no screen, export or counsellor view may label a value "verified" in the sense
  of authentic. The portal and the university verify documents.
- The consent and privacy notice (`2026-10-03-consent-and-privacy-notice-design.md`) gains one
  line: uploaded identity documents and certificates are read by a machine to fill applications.

## 9. Launch gates

Before `FACT_READING_ENABLED` is on for real students:
1. **Specimens.** The ICAO 9303 specimen strips and the published specimen passports pass the
   check-digit and transliteration tests.
2. **A consented set**, read with every value judged by the owner:
   - about 30 passports and ID cards (az, tr, ru, en; photos and PDF scans; old and new formats);
   - about 20 diplomas (with translations, bilingual ones and CIS series-and-number ones);
   - about 20 certificates (IELTS paper and eTRF, TOEFL, Duolingo, Cambridge).
3. **Bars, measured on that set:**
   - **zero** proven values that are wrong — any one is a blocker that changes the proof rule, not
     the threshold alone;
   - the doubtful rate is reported per field; the owner sets the acceptable rate;
   - the hidden-text cases are covered: a born-digital certificate carrying white-on-white
     injection text and a scanner-app PDF with an invisible OCR layer each produce values only from
     the visible page.
4. **Before any real file goes to Azure**, the idDocument price and the shared page ceiling are
   confirmed.

## 10. Testing

- The check digits and the TD1/TD3 parsing: the ICAO specimens, plus failure cases (one digit
  changed, a truncated name, a century boundary).
- Transliteration: az, tr and ru names against their strip forms.
- Proof rules, one test per `why` code. Azure responses and reader answers are recorded fixtures.
- Precedence: a student entry against a new read, a renewal, a name change, two valid passports,
  an expired-only passport.
- The visible-text filter, using fixture PDFs with white text, tiny text, off-page text and a
  render-mode-3 layer.
- RLS for `DocumentReading` through `rls_enforced_orm`, erasure coverage through the redaction
  coverage test, and the one-tap endpoint's refusals (not offered, someone else's fact, already
  confirmed, a locked account).
- Extension e2e: an offered hint, then a tap, then a fill and a mark.

## 11. Out of scope

- Reading a passport's chip.
- Selfie or liveness checks.
- Verifying certificates on the IELTS or TOEFL websites, or e-diplomas through QR codes.
- Turning portal answers (`PortalAnswer`) into facts.
- A warning when a passport expires before the programme starts. It is cheap once the expiry is a
  fact; it is a follow-up, not part of this design.
- Transcripts, which have their own reader.

## 12. Known issue found while designing (not fixed here)

The transcript reader's text-layer path (`ocr/read_pages.py`) accepts any page whose layer has a
table and passes `text_layer_usable`, without filtering invisible text. A scanner-app PDF of a
transcript with an invisible OCR layer is therefore read as "exact", and hidden text on a
born-digital page reaches the transcript readers. The visible-text filter in §5.3 is the fix, and
it should be shared. This belongs to the transcript reader's owner.
