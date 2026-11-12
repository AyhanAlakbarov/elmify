# Co-pilot Guidance 4 — Documents Prepared to Each Programme's File Rules — Implementation Plan

> Note (2026-10-11): staff view and download of files without a grant is covered by `docs/superpowers/plans/2026-10-11-staff-file-access.md`; where this plan says counsellor-only or grant-required, that plan supersedes it for platform staff.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before a student reaches a portal, each document the co-pilot will attach already fits the programme's written file rules: maximum size, PDF or JPG, "all diplomas as one PDF", "the whole application as one PDF", and a file-name pattern. When a file cannot be made to fit, the student is told why, in the panel and the kit, before they start.

**Architecture:**
- **The requirement reader learns file rules.** Any candidate sentence that names a file thing (a size in MB or KB, PDF, JPG, a file name, "one file") is asked five closed questions:
  - which document,
  - which format,
  - one file or separate files,
  - which printed size is the cap,
  - which printed file name is required.
  This uses the same shape as the referee questions (`grammar_values._referee_questions`). The answers are stored per programme as records on `Program.file_rules` (catalogue). The worker copies them to `Application.kit_file_rules` (tenant) in `capture_requirements`.
- **One transform implementation, in the isolated parser.** `ocr/read_pages.py` gains `prepare(parts, target)`: convert, merge and compress with Pillow, pypdf and pypdfium2. **Uploads must be transformed there** (CLAUDE.md, and `ocr/read_pages.py`'s own docstring: the process that parses an untrusted file holds no secret and no route to the internet). Our own generated documents (CV, letters) could legally be transformed in the worker. They go through the same parser function anyway, so one implementation exists. They travel inline in the request; uploads travel as `{key, version_id}`, exactly as `inspect` does today. The worker only renames, stores and records.
- **The result is a `PreparedDocument` row per (application, slot)**, stored under the student's own S3 prefix (so erasure's prefix purge covers it). It carries an inputs digest. The kit and the Fill Packet serve a prepared file only while its digest matches the current sources and rules. Otherwise they serve the original, exactly as today.

**Tech Stack:** Django 5.2 / Python 3.14 (app), Python 3.12 + Pillow 12 + pypdf 6 + pypdfium2 5.14 (`ocr/`, its own `uv` project), TypeScript (extension, Task 8 only), pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md` §7 ("Prepared beforehand"), owner decision D4, §10 ("A document the portal rejects"). Plan 1 (`docs/superpowers/plans/2026-10-09-copilot-guidance-1-marks-and-panel.md`) owns attaching and the visibility rule. Plan 5 owns which upload box gets which file.

## What was measured, and what this plan covers

The whole design is sized to these, from `docs/research/cv-rules.csv` and `cv-ruleset.md`. No live portal test exists yet; plan 6's bench is where JPG and per-diploma rules would surface.

| Rule | Source | Covered by |
|---|---|---|
| Whole application "compiled as a single PDF file", items in a fixed order, "must not exceed 10 MB" | R-008 Mundus Journalism | `EVERY_DOCUMENT` + `ONE_FILE` + size → one bundle |
| File ≤ 2 MB | R-060 Europubhealth+ | size |
| Default ≤ 2 MB; Campus France 1.5 MB / 300 KB | R-067 | size (300 KB is plausible here; the CV megabytes band of 0.1 MB still drops it) |
| Supporting documents "pdf format", "under 2MB", "not encrypted" | R-082 Cambridge | format `PDF` + size; parser output is never encrypted |
| "Upload as a single PDF named SURNAME_CV.pdf" | grammar_questions.py example | name pattern |
| CV page limits | already `max_pages` (render-time) | unchanged: generated documents are rendered within page limits today |

**Not covered, on purpose:**
- PNG as a required format: not measured.
- Page limits on uploads: a transcript is not ours to shorten.
- A rule the page never wrote: the panel's "the portal wants…" message stays, per spec §7.

## Global Constraints
- **Uploads are transformed only in the isolated parser** (`ocr/read_pages.py`, run as the OCR Lambda, or locally as its child process). The worker and the web tier never open, rewrite or re-encode an upload's bytes. They copy them, as `promote_upload` does.
- **A file that already fits is served byte for byte.** `prepare` returns the original bytes when there is one part, its format is allowed and it is under the cap. Re-encoding a file that already fits only loses quality.
- **A signed PDF is never rewritten.** This is `ocr/read_pages.py::inspect`'s rule: Azerbaijan's TMIS e-diplomas verify byte for byte. If such a file must change (compress, merge, convert), the result is `CANNOT_FIT` with reason `signed`, and the student is told. It is never a silently broken signature.
- **A rule nobody wrote changes nothing.** No default cap is applied. With no rule for a document, nothing is prepared and the original is served.
- **Sizes are decimal:** 1 MB = 1,000,000 bytes and 1 KB = 1,000 bytes (the stricter reading, as `rule_sinks._BYTES_PER_MEGABYTE`). A plausible cap is 10,000 bytes to 100,000,000 bytes; anything else is a misread.
- **Values come from the page, never a model:**
  - A size option is a figure code found in the sentence.
  - A file-name option is a token code found in the sentence.
  - The model only chooses among them, at `SLOT_BAR` (0.85). `NOT_STATED` and below-bar answers write nothing.
- **Never a guessed surname.** The surname comes only from a confirmed `IDENTITY` fact `surname`. The owner decided on 2026-10-09 to collect it on the dashboard; that collection is a separate change, not this plan.
  - Until the fact exists, a pattern needing `{surname}` is not applied. The file keeps its own name, and `reason="name_needs_surname"` tells the student what to rename it to.
  - `{given_name}` is never applied: no fact holds it.
- **Filenames are `^[A-Za-z0-9._-]{1,100}$`** (`storage._SAFE_FILENAME`); a full name is ASCII-folded into it.
- **The parser's answer is at most 4,000,000 raw bytes** (a synchronous Lambda response is capped at 6 MB, and base64 grows by a third).
  - Larger results are `CANNOT_FIT` / `too_large_to_return`.
  - `ponytail:` the upgrade is a write-only output prefix for the function; build it when a measured rule needs a bigger bundle.
- **Tenant tables:** a new tenant table gets `ENABLE` + `FORCE ROW LEVEL SECURITY` and the `tenant_isolation` policy, its composite `(tenant_id, …)` FK guards, and a `redaction.py` classification in the same change. The web tier reads no catalogue table: the kit and packet read only `Application.kit_file_rules` and `PreparedDocument`.
- **Repo commands:**
  - `uv run ruff check .` (never `ruff format`)
  - `uv run mypy apps config`
  - `POSTGRES_DB=elmify_copilot_docprep uv run pytest -q <paths>`
  - `uv run python manage.py makemigrations --check --dry-run`
  - parser tests: `uv run --project ocr pytest ocr -q`
- **Worktree:** `/home/orkhan/Desktop/copilot-docprep`, branch `claude/copilot-document-prep` (from `claude/copilot-on-page-guidance`). Use `git -C /home/orkhan/Desktop/copilot-docprep` for every git command. The shell resets its working directory between calls.
- **Migration numbers:** plans 1–3 run on sibling branches and may add migrations first. Renumber at merge; `makemigrations --check` in CI catches a dangling dependency.

## Review Focus
1. **A signed e-diploma PDF under a 2 MB rule it already meets.** It is served byte for byte. If it is over the cap, the result is `CANNOT_FIT` / `signed`, never a rewritten file (Task 4 tests).
2. **A diploma sentence on a page that also caps the CV**, e.g. "Diplomas as one PDF; CV max. 2 MB". Each rule lands on its own document; the CV's existing `max_bytes` constraint still comes out (Task 1 test).
3. **The student replaces an upload, or a CV is re-approved, after preparation.** The stale prepared file is not served: the digest no longer matches, so the original is served until the worker prepares again (Task 6 test).
4. **Two sentences disagree:** "max 2 MB" and "max 5 MB" for the same document → 2 MB; "PDF only" and "JPG only" → no format rule, never a guess (Task 3 test).
5. **A whole-application bundle that cannot be built**, e.g. one signed diploma or a result over 4 MB. The packet carries the separate originals and the bundle's reason, so the student is not left with nothing (Task 7 test).

---

### Task 1: The reader asks file-rule questions

**Files:**
- Modify: `apps/documents/grammar.py`: add `FILE_FIELDS`; `RuleOperation` gains `"file"`.
- Modify: `apps/documents/grammar_values.py`: add `_FILE_TERMS`, `size_options`, `name_options`, `_file_questions`, `_file_drafts`, `_asks_file`; wire them into `value_questions` and `_rules_for`; `_has_sink` handles `"file"`.
- Modify: `apps/documents/rule_sinks.py`: `to_notes` skips `operation == "file"`, like `"referee"`.
- Test: `tests/documents/test_grammar_values.py`

**Interfaces:**
- Produces in `grammar.py`:

```python
#: What a page can state about the FILE a document is submitted as.
#: NOT_STATED never becomes a rule. `document` EVERY_DOCUMENT is a rule for all
#: the applicant's documents at once ("all documents as one PDF, max 10 MB").
FILE_FIELDS: dict[str, tuple[str, ...]] = {
    "document": ("CV", "MOTIVATION_LETTER", "REFERENCE_LETTER", "TRANSCRIPT", "DIPLOMA",
                 "PASSPORT", "LANGUAGE_CERTIFICATE", "EVERY_DOCUMENT", "NOT_STATED"),
    "format": ("PDF", "JPG", "PDF_OR_JPG", "NOT_STATED"),
    "combine": ("ONE_FILE", "SEPARATE_FILES", "NOT_STATED"),
}
RuleOperation = Operation | Literal["referee", "file"]
```

- Produces in `grammar_values.py`: a `file` rule's `value` is a tuple `(document, field, value)`:
  - `field` is one of `"format" | "combine" | "max_bytes" | "name_pattern"`.
  - `value` is a `str`, or an `int` of bytes for `max_bytes`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/documents/test_grammar_values.py`:

```python
_DIPLOMAS = "Please upload all your diplomas as one PDF file of at most 2 MB."


def test_a_file_sentence_is_asked_the_file_questions_whatever_its_document():
    """A transcript or diploma sentence is document `other`, which gets no value
    question at all -- file questions are asked before that, like referee ones."""
    candidates, slots = _one(_DIPLOMAS, "other", "student_action")
    questions = value_questions(candidates, slots)

    assert questions["0:file_document"].options[-1] == "NOT_STATED"
    assert questions["0:file_format"].options == ("PDF", "JPG", "PDF_OR_JPG", "NOT_STATED")
    assert questions["0:file_combine"].options == ("ONE_FILE", "SEPARATE_FILES", "NOT_STATED")
    assert questions["0:file_size"].options == ("2 MB", "none")


def test_a_sentence_naming_no_file_thing_is_not_asked():
    candidates, slots = _one("Two letters of motivation are required.", "other",
                             "student_action")
    assert not any(q.startswith("0:file_") for q in value_questions(candidates, slots))


def test_file_answers_become_one_record_per_stated_field():
    candidates, slots = _one(_DIPLOMAS, "other", "student_action")
    rules = read_values(candidates, slots, client=_script({
        "0:file_document": ("DIPLOMA", 0.97),
        "0:file_format": ("PDF", 0.95),
        "0:file_combine": ("ONE_FILE", 0.93),
        "0:file_size": ("2 MB", 0.96),
    }))
    files = sorted(r.value for r in rules if r.operation == "file")
    assert files == [("DIPLOMA", "combine", "ONE_FILE"), ("DIPLOMA", "format", "PDF"),
                     ("DIPLOMA", "max_bytes", 2_000_000)]
    assert all(r.applied for r in rules if r.operation == "file")


def test_kilobytes_and_an_unsure_answer():
    candidates, slots = _one("Scans must be JPG files under 300 KB.", "other",
                             "student_action")
    rules = read_values(candidates, slots, client=_script({
        "0:file_document": ("PASSPORT", 0.9),
        "0:file_size": ("300 KB", 0.95),
        "0:file_format": ("JPG", 0.6),  # under SLOT_BAR: writes nothing
    }))
    assert [r.value for r in rules if r.operation == "file"] == [
        ("PASSPORT", "max_bytes", 300_000)]


def test_no_document_means_no_file_rule():
    candidates, slots = _one(_DIPLOMAS, "other", "student_action")
    rules = read_values(candidates, slots, client=_script({
        "0:file_size": ("2 MB", 0.99),  # file_document unscripted: NOT_STATED
    }))
    assert not [r for r in rules if r.operation == "file"]


def test_a_file_name_is_offered_from_the_sentence_and_normalised():
    text = "Upload your CV as a single PDF named SURNAME_CV.pdf."
    candidates, slots = _one(text, "cv", "student_action")
    assert value_questions(candidates, slots)["0:file_name"].options == ("SURNAME_CV.pdf", "none")
    rules = read_values(candidates, slots, client=_script({
        "0:file_document": ("CV", 0.98), "0:file_name": ("SURNAME_CV.pdf", 0.95),
    }))
    assert ("CV", "name_pattern", "{surname}_CV.pdf") in [r.value for r in rules]


def test_a_cv_cap_still_reaches_the_cv_constraint():
    """Review Focus 2: the file question is added, the limit path is untouched."""
    text = "The CV may not exceed 2 MB; diplomas as one PDF."
    candidates, slots = _one(text, "cv", "limit")
    questions = value_questions(candidates, slots)
    assert "0:figure:0:bound" in questions and "0:file_document" in questions
```

- [ ] **Step 2: Run them to see them fail.**
Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/documents/test_grammar_values.py -q -k "file"`.
Expected: FAIL (`KeyError: '0:file_document'`).

- [ ] **Step 3: Implement.** In `grammar.py`, add `FILE_FIELDS` beside `REFEREE_FIELDS` and widen `RuleOperation` as shown in Interfaces. In `grammar_values.py`:

```python
from .grammar import FILE_FIELDS  # add to the existing grammar import

#: A file thing a sentence can name. Matched on the raw line; code decides only
#: WHETHER to ask, never what the answer is. ponytail: English, German, French,
#: Russian and Turkish words for file/size; a page in another language still
#: reaches the questions through "PDF"/"MB", which no language translates.
_FILE_TERMS = re.compile(
    r"\b(?:pdf|jpe?g|\d+(?:[.,]\d+)?\s*(?:mb|kb|mo|ko|megabytes?|kilobytes?)|file ?name"
    r"|one file|single file|datei|fichier|dosya|файл|мб|кб)\b"
    r"|\b[\w-]+\.(?:pdf|jpe?g|png)\b",
    re.IGNORECASE,
)
_SIZE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mb|mo|megabytes?|мб|kb|ko|kilobytes?|кб)\b", re.IGNORECASE
)
_FILE_NAME = re.compile(r"\b[\w-]+\.(?:pdf|jpe?g|png)\b", re.IGNORECASE)
#: Placeholder words in a printed file name, casefolded. Anything else is literal.
_NAME_PLACEHOLDERS = {
    "surname": "{surname}", "lastname": "{surname}", "familyname": "{surname}",
    "nachname": "{surname}", "firstname": "{given_name}", "givenname": "{given_name}",
    "vorname": "{given_name}", "name": "{full_name}", "fullname": "{full_name}",
}
_MIN_FILE_BYTES, _MAX_FILE_BYTES = 10_000, 100_000_000


def size_options(text: str) -> tuple[str, ...]:
    """Each size the sentence prints, as printed ("2 MB"), in order."""
    return tuple(dict.fromkeys(f"{m.group(1)} {m.group(2).upper()}" for m in _SIZE.finditer(text)))


def size_bytes(option: str) -> int | None:
    """"2 MB" -> 2_000_000; "300 KB" -> 300_000. None outside the plausible band."""
    number, unit = option.split(" ", 1)
    scale = 1_000 if unit.lower() in ("kb", "ko", "kilobyte", "kilobytes", "кб") else 1_000_000
    value = round(float(number.replace(",", ".")) * scale)
    return value if _MIN_FILE_BYTES <= value <= _MAX_FILE_BYTES else None


def name_options(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(m.group(0) for m in _FILE_NAME.finditer(text)))


def name_pattern(printed: str) -> str:
    """"SURNAME_CV.pdf" -> "{surname}_CV.pdf". Separators and literals are kept."""
    parts = re.split(r"([_\-.\s])", printed)
    return "".join(_NAME_PLACEHOLDERS.get(p.casefold().replace("_", ""), p) for p in parts)


def _asks_file(text: str) -> bool:
    return bool(_FILE_TERMS.search(text))


def _file_questions(i: int, where: str, text: str) -> dict[str, Question]:
    questions: dict[str, Question] = {
        f"{i}:file_document": Choice(
            inspect=where, options=FILE_FIELDS["document"], criteria=_FILE_CRITERIA["document"],
            question="Which of the applicant's documents does this file requirement apply to?",
        ),
        f"{i}:file_format": Choice(
            inspect=where, options=FILE_FIELDS["format"], criteria=_FILE_CRITERIA["format"],
            question="Which file format must the document be submitted in?",
        ),
        f"{i}:file_combine": Choice(
            inspect=where, options=FILE_FIELDS["combine"], criteria=_FILE_CRITERIA["combine"],
            question="Must these documents be combined into one file?",
        ),
    }
    if sizes := size_options(text):
        questions[f"{i}:file_size"] = Choice(
            inspect=where, options=(*sizes, "none"),
            question="Which of these is the largest file size allowed, if any?",
        )
    if names := name_options(text):
        questions[f"{i}:file_name"] = Choice(
            inspect=where, options=(*names, "none"),
            question="Which of these is the file name the applicant must give the file, if any?",
        )
    return questions


def _file_drafts(answers: Mapping[str, Answer], i: int) -> list[_Draft]:
    document = answers.get(f"{i}:file_document")
    if document is None or document.value == "NOT_STATED" or document.confidence < SLOT_BAR:
        return []
    doc = str(document.value)
    drafts: list[_Draft] = []
    for field in ("format", "combine"):
        answer = answers.get(f"{i}:file_{field}")
        if answer is not None and answer.value != "NOT_STATED" and answer.confidence >= SLOT_BAR:
            drafts.append(_Draft("file", (doc, field, str(answer.value)), answer.confidence))
    size = answers.get(f"{i}:file_size")
    if size is not None and size.value != "none" and size.confidence >= SLOT_BAR:
        if (cap := size_bytes(str(size.value))) is not None:
            drafts.append(_Draft("file", (doc, "max_bytes", cap), size.confidence))
    name = answers.get(f"{i}:file_name")
    if name is not None and name.value != "none" and name.confidence >= SLOT_BAR:
        drafts.append(_Draft("file", (doc, "name_pattern", name_pattern(str(name.value))),
                             name.confidence))
    return drafts
```

`_FILE_CRITERIA` defines every option in words, the way `_REFEREE_CRITERIA` does; an undefined option answers under the bar (2026-10-08 probes):

```python
_FILE_CRITERIA: dict[str, dict[str, object]] = {
    "document": {
        "CV": {"what": "The applicant's CV / résumé."},
        "MOTIVATION_LETTER": {"what": "The applicant's motivation letter or statement."},
        "REFERENCE_LETTER": {"what": "A recommendation or reference letter."},
        "TRANSCRIPT": {"what": "A transcript of records or grade list."},
        "DIPLOMA": {"what": "A degree certificate or diploma.",
                    "examples": ["all your diplomas as one PDF"]},
        "PASSPORT": {"what": "A passport or ID scan."},
        "LANGUAGE_CERTIFICATE": {"what": "A language test certificate (IELTS, TOEFL...)."},
        "EVERY_DOCUMENT": {"what": "All application documents at once.",
                           "examples": ["All documents must be compiled as a single PDF file.",
                                        "Each file must be under 2MB."]},
        "NOT_STATED": {"what": "The sentence states no requirement about a file."},
    },
    "format": {
        "PDF": {"what": "Only PDF is accepted.", "examples": ["in pdf format"]},
        "JPG": {"what": "Only JPG/JPEG images are accepted."},
        "PDF_OR_JPG": {"what": "PDF or JPG, the applicant chooses."},
        "NOT_STATED": {"what": "The sentence names no file format."},
    },
    "combine": {
        "ONE_FILE": {"what": "The documents named must be merged into one file.",
                     "examples": ["compiled as a single PDF file", "all diplomas as one PDF"]},
        "SEPARATE_FILES": {"what": "Each document must be a separate file."},
        "NOT_STATED": {"what": "The sentence does not say."},
    },
}
```

Wiring, all in `grammar_values.py`:
- In `value_questions`, right after the referee block and **before** `if not _asks_values(slot): continue`:

```python
        if _asks_file(text):
            # Before the bar and the `other` check: a diploma sentence IS
            # document `other`, and its file rule is the reason it is read.
            questions.update(_file_questions(i, where, text))
```

- In `_rules_for`, move the `slot.document == "other"` early return **below** the `condition` computation, so a conditional diploma rule is still marked conditional.
  - Compute `files = _file_drafts(answers, i) if _asks_file(candidate.text) else []` before that return.
  - Change the return to `return _settled(slot, candidate, files, condition) if files else ()`.
  - Add `*files` to the drafts passed to `_settled` in the two later returns, beside `*referee`.
- In `_has_sink`: `if draft.operation == "file": return True` (its sink is `Program.file_rules`, Task 2).
- In `rule_sinks.to_notes`: extend the existing referee `continue` to `if rule.operation in ("referee", "file"): continue`.
- In `_settled`, the third-party exclusion stays for `file`: a file rule about a referee's own upload is not the applicant's document.

- [ ] **Step 4: Run them to see them pass, plus the whole module and the sinks.**
Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/documents/test_grammar_values.py tests/documents/test_rule_sinks.py tests/documents/test_grammar.py -q`.
Expected: PASS.
- An older test may assert an exact question-id set for a sentence containing "PDF" or "MB". Update that set to include the `file_*` ids. Do not narrow `_FILE_TERMS` to keep an old set.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-docprep add apps/documents/grammar.py apps/documents/grammar_values.py apps/documents/rule_sinks.py tests/documents/test_grammar_values.py
git -C /home/orkhan/Desktop/copilot-docprep commit -m "documents: the reader asks file-rule questions (document, format, one file, size, name)"
```

---

### Task 2: File rules reach the programme: recall, sink, `Program.file_rules`

**Files:**
- Modify: `apps/documents/derive.py`:
  - `candidates()` gains the `_FILE_TERMS` recall path.
  - `Decision.file_rules`.
  - `_read_by_grammar` fills it.
  - The write writes `file_rules`.
- Modify: `apps/documents/rule_sinks.py`: add `to_file_rules`.
- Modify: `apps/documents/management/commands/rederive_rules.py`: keep and write `file_rules`.
- Modify: `apps/funding/models.py`: `Program.file_rules`.
- Create: `apps/funding/migrations/0059_program_file_rules.py` (via `makemigrations funding`).
- Test: `tests/documents/test_file_rules.py` (new)

**Interfaces:**
- Consumes: Task 1's `file` rules, with `value == (document, field, value)`.
- Produces: `to_file_rules(rules, *, source_url) -> tuple[dict[str, object], ...]`. Each record is:

```python
{"document": "DIPLOMA", "field": "max_bytes", "value": 2000000,
 "conditional": False, "condition": "", "rule_text": "<sentence>", "source_url": "<url>"}
```

- [ ] **Step 1: Write the failing tests.** Create `tests/documents/test_file_rules.py`:

```python
import pytest

from apps.documents.derive import candidates
from apps.documents.grammar import Rule
from apps.documents.rule_sinks import to_file_rules

pytestmark = pytest.mark.django_db


def _rule(value, note="", condition=""):
    return Rule(index=0, document="other", operation="file", value=value,
                sentence="Diplomas as one PDF, max 2 MB.", note=note, condition=condition)


def test_a_diploma_line_is_a_candidate_though_it_names_no_cv_or_letter():
    found = candidates("Diplomas as one PDF, max 2 MB.\nOur campus is lovely.", ())
    assert [c.text for c in found] == ["Diplomas as one PDF, max 2 MB."]
    assert not found[0].cv and not found[0].letter


def test_file_only_lines_are_cut_first_when_the_page_is_too_long(monkeypatch):
    monkeypatch.setattr("apps.documents.derive._MAX_CANDIDATES", 2)
    page = "Brochure (PDF, 1 MB)\nYour CV may not exceed two pages.\nA motivation letter is required."
    found = candidates(page, (), language="en")
    assert "Your CV may not exceed two pages." in [c.text for c in found]
    assert "Brochure (PDF, 1 MB)" not in [c.text for c in found]


def test_records_keep_the_sentence_and_the_page():
    records = to_file_rules((_rule(("DIPLOMA", "max_bytes", 2_000_000)),),
                            source_url="https://u.example/apply")
    assert records == ({"document": "DIPLOMA", "field": "max_bytes", "value": 2_000_000,
                        "conditional": False, "condition": "",
                        "rule_text": "Diplomas as one PDF, max 2 MB.",
                        "source_url": "https://u.example/apply"},)


def test_a_conditional_rule_is_kept_marked_and_a_note_is_dropped():
    records = to_file_rules(
        (_rule(("DIPLOMA", "format", "PDF"), note="conditional", condition="nationality"),
         _rule(("DIPLOMA", "format", "PDF"), note="third_party")),
        source_url="u",
    )
    assert [(r["conditional"], r["condition"]) for r in records] == [(True, "nationality")]
```

Also add, beside the referee write test in `tests/documents/test_derive.py`, a test that a grammar read writes `Program.file_rules`. Copy that test's fixture setup. Script a `file_document`/`file_size` answer; assert `program.file_rules[0]["field"] == "max_bytes"`.

- [ ] **Step 2: Run them to see them fail.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/documents/test_file_rules.py -q`. Expected: FAIL (`ImportError: to_file_rules`).

- [ ] **Step 3: Implement.**

In `apps/documents/rule_sinks.py`, beside `to_referee`:

```python
def to_file_rules(rules: Sequence[Rule], *, source_url: str) -> tuple[dict[str, object], ...]:
    """The page's file rules, one record per (document, field) a sentence stated.

    Written to `Program.file_rules`; copied to `Application.kit_file_rules` by
    capture_requirements; folded per document by `apps.documents.file_rules`. A
    conditional rule is kept and marked -- it binds no student until their own
    facts are compared -- and every other note is dropped.
    """
    records: list[dict[str, object]] = []
    for rule in rules:
        if rule.operation != "file" or rule.note not in ("", "conditional"):
            continue
        document, field, value = cast(tuple[str, str, object], rule.value)
        records.append({
            "document": document, "field": field, "value": value,
            "conditional": rule.note == "conditional", "condition": rule.condition,
            "rule_text": _quote(rule.sentence), "source_url": source_url,
        })
    return tuple(records)
```

In `apps/documents/derive.py`:
- Import `_FILE_TERMS` from `grammar_values`. If that import cycles, move `_FILE_TERMS` into `grammar.py` and import it in both modules.
- In `candidates()`: add `file = bool(_FILE_TERMS.search(line))`.
  - A line that is `file` and nothing else (not cv, letter or reference) goes to a separate `file_only` list, as `Candidate(..., cv=False, letter=False)`.
  - `found` gets `[*found, *file_only]` after the statements loop and before the `_MAX_CANDIDATES` cut, so the cap drops file-only lines first.
  - "Programme brochure (PDF, 1.2 MB)" sits in many page footers. Without this, a page full of them could push a real CV sentence past the cap of 100.
- Add `file_rules: tuple[dict[str, object], ...] = ()` to `Decision`, beside `referee`.
- Add `file_rules=to_file_rules(rules, source_url=source_url)` to `_read_by_grammar`'s `Decision(...)`.
- In the write, extend the `referee_requirements` block: `fields["file_rules"] = list(decision.file_rules)`. The comment stays true: only the grammar reads file rules.

In `rederive_rules.py`, mirror the referee lines exactly:
- `kept_files = [d for d in program.file_rules if d.get("rule_text") not in reread]`
- `files = kept_files + list(to_file_rules(rules, source_url=source_url))`
- Add `and files == program.file_rules` to the unchanged test.
- Add `file_rules=files` to `_write_program`.

In `apps/funding/models.py`, after `referee_requirements`:

```python
    #: The page's file rules (rule_sinks.to_file_rules): one record per
    #: (document, field) -- max_bytes, format, combine, name_pattern -- each with
    #: its sentence. Read only by capture_requirements, in the worker.
    file_rules = models.JSONField(default=list, blank=True)
```

Then run `uv run python manage.py makemigrations funding -n program_file_rules`.

- [ ] **Step 4: Run them to see them pass.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/documents/test_file_rules.py tests/documents/test_derive.py tests/documents/test_rederive_rules.py -q && uv run python manage.py makemigrations --check --dry-run`. Expected: PASS, "No changes detected".

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-docprep add apps/documents apps/funding tests/documents
git -C /home/orkhan/Desktop/copilot-docprep commit -m "documents: file rules are written to Program.file_rules by read and re-derivation"
```

---

### Task 3: One rule per document, and the tenant copy

**Files:**
- Create: `apps/documents/file_rules.py`
- Modify: `apps/portals/models.py`: `Application.kit_file_rules`.
- Create: `apps/portals/migrations/0024_application_kit_file_rules.py` (makemigrations).
- Modify: `apps/portals/packets.py`: `capture_requirements` copies the rules.
- Modify: `apps/audit/redaction.py`: `KEEP["portals.Application"]` gains `"kit_file_rules"`.
- Test: `tests/documents/test_file_rules.py`, `tests/portals/test_capture_requirements.py` (or the module holding `capture_requirements`' tests; `grep -rln capture_requirements tests/`).

**Interfaces:**
- Produces in `apps/documents/file_rules.py`:

```python
@dataclass(frozen=True)
class FileRule:
    max_bytes: int | None = None
    format: str | None = None          # "PDF" | "JPG" | "PDF_OR_JPG"
    one_file: bool = False
    name_pattern: str | None = None

    @property
    def empty(self) -> bool: ...

def rule_for(records: Iterable[Mapping[str, object]], document: str) -> FileRule
def bundle_rule(records: Iterable[Mapping[str, object]]) -> FileRule | None   # EVERY_DOCUMENT + ONE_FILE
DRAFT_DOCUMENT: dict[str, str]    # DocumentDraft.Kind -> FILE_FIELDS document
UPLOAD_DOCUMENT: dict[str, str]   # DocumentVersion.kind -> FILE_FIELDS document
```

- [ ] **Step 1: Write the failing tests.** Append to `tests/documents/test_file_rules.py`:

```python
from apps.documents.file_rules import FileRule, bundle_rule, rule_for


def _r(document, field, value, conditional=False):
    return {"document": document, "field": field, "value": value, "conditional": conditional}


def test_the_smaller_cap_wins_and_every_document_applies_to_each():
    records = [_r("DIPLOMA", "max_bytes", 5_000_000), _r("EVERY_DOCUMENT", "max_bytes", 2_000_000)]
    assert rule_for(records, "DIPLOMA").max_bytes == 2_000_000


def test_conflicting_formats_give_no_format_and_the_stricter_one_wins_over_either():
    assert rule_for([_r("CV", "format", "PDF"), _r("CV", "format", "JPG")], "CV").format is None
    assert rule_for([_r("CV", "format", "PDF"), _r("CV", "format", "PDF_OR_JPG")], "CV").format == "PDF"


def test_a_conditional_record_binds_nobody_and_another_document_is_ignored():
    records = [_r("DIPLOMA", "max_bytes", 1_000_000, conditional=True),
               _r("TRANSCRIPT", "combine", "ONE_FILE")]
    assert rule_for(records, "DIPLOMA") == FileRule()


def test_one_file_for_a_kind_and_the_whole_application_bundle():
    records = [_r("DIPLOMA", "combine", "ONE_FILE"), _r("EVERY_DOCUMENT", "combine", "ONE_FILE"),
               _r("EVERY_DOCUMENT", "max_bytes", 10_000_000)]
    assert rule_for(records, "DIPLOMA").one_file is True
    assert bundle_rule(records) == FileRule(max_bytes=10_000_000, format="PDF", one_file=True)
    assert bundle_rule([_r("DIPLOMA", "combine", "ONE_FILE")]) is None


def test_two_different_name_patterns_give_none():
    records = [_r("CV", "name_pattern", "{surname}_CV.pdf"), _r("CV", "name_pattern", "cv.pdf")]
    assert rule_for(records, "CV").name_pattern is None
```

In the capture tests, add a test:
- Create a `Program` with `file_rules=[...]` and an `Application` for it.
- Call `capture_requirements(application)`.
- Assert `application.kit_file_rules` equals the programme's list, with `rule_text` and `source_url` kept.

- [ ] **Step 2: Run them to see them fail.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/documents/test_file_rules.py -q`. Expected: FAIL (`ModuleNotFoundError: apps.documents.file_rules`).

- [ ] **Step 3: Implement** `apps/documents/file_rules.py`:

```python
"""A programme's file rules, folded to one rule per document (spec §7, D4).

Input: `Application.kit_file_rules`, the tenant copy of `Program.file_rules`
(rule_sinks.to_file_rules). Conflicts resolve to the safer reading or to
nothing: the smaller cap; for formats the intersection, or no format when two
sentences contradict; for names, none when two differ. A conditional record
binds no student until their own facts are compared (addendum §6.6).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

DRAFT_DOCUMENT = {"CV": "CV", "MOTIVATION_LETTER": "MOTIVATION_LETTER"}
UPLOAD_DOCUMENT = {
    "CV": "CV", "TRANSCRIPT": "TRANSCRIPT", "PASSPORT": "PASSPORT", "DIPLOMA": "DIPLOMA",
    "LANGUAGE_CERTIFICATE": "LANGUAGE_CERTIFICATE", "RECOMMENDATION": "REFERENCE_LETTER",
}
_ALLOWS = {"PDF": {"PDF"}, "JPG": {"JPG"}, "PDF_OR_JPG": {"PDF", "JPG"}}


@dataclass(frozen=True)
class FileRule:
    max_bytes: int | None = None
    format: str | None = None
    one_file: bool = False
    name_pattern: str | None = None

    @property
    def empty(self) -> bool:
        return self == FileRule()


def _applies(records: Iterable[Mapping[str, object]], documents: set[str]) -> list[Mapping[str, object]]:
    return [r for r in records if r.get("document") in documents and not r.get("conditional")]


def _fold(records: list[Mapping[str, object]], *, one_file_from: set[str]) -> FileRule:
    caps = [int(r["value"]) for r in records if r["field"] == "max_bytes"]  # type: ignore[call-overload]
    formats = {str(r["value"]) for r in records if r["field"] == "format"}
    allowed = set.intersection(*(_ALLOWS[f] for f in formats)) if formats else set()
    fmt = None if not allowed else ("PDF_OR_JPG" if allowed == {"PDF", "JPG"} else allowed.pop())
    combines = {str(r["value"]) for r in records
                if r["field"] == "combine" and r["document"] in one_file_from}
    names = {str(r["value"]) for r in records if r["field"] == "name_pattern"}
    return FileRule(
        max_bytes=min(caps) if caps else None,
        format=fmt,
        one_file=combines == {"ONE_FILE"},
        name_pattern=names.pop() if len(names) == 1 else None,
    )


def rule_for(records: Iterable[Mapping[str, object]], document: str) -> FileRule:
    """This document's rule. EVERY_DOCUMENT's size and format apply to each file;
    its ONE_FILE is the bundle (bundle_rule), never a per-document merge."""
    return _fold(_applies(records, {document, "EVERY_DOCUMENT"}), one_file_from={document})


def bundle_rule(records: Iterable[Mapping[str, object]]) -> FileRule | None:
    """The whole application as one PDF (R-008), or None when no page asked for it."""
    every = _applies(records, {"EVERY_DOCUMENT"})
    rule = _fold(every, one_file_from={"EVERY_DOCUMENT"})
    if not rule.one_file:
        return None
    return FileRule(max_bytes=rule.max_bytes, format="PDF", one_file=True,
                    name_pattern=rule.name_pattern)
```

Model change: in `apps/portals/models.py`, after `kit_letter_cycle`, add `kit_file_rules = models.JSONField(default=list, blank=True)` with comment `#: Program.file_rules, copied by capture_requirements (the web tier reads no catalogue).` Then run `makemigrations portals -n application_kit_file_rules`.

Capture: in `capture_requirements`, before the save:

```python
    application.kit_file_rules = list(
        Program.objects.filter(id=application.program_id)
        .values_list("file_rules", flat=True).first() or []
    )
```

Add `"kit_file_rules"` to the `save(update_fields=[...])` list, and import `Program` from `apps.funding.models`.

In `redaction.py`, add `"kit_file_rules"` after `"kit_letter_cycle"`, under the existing comment (a copy of the programme's published sentences).

- [ ] **Step 4: Run them to see them pass.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/documents/test_file_rules.py tests/portals tests/audit -q && uv run python manage.py makemigrations --check --dry-run && uv run mypy apps config`. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-docprep add apps/documents/file_rules.py apps/portals apps/audit/redaction.py tests
git -C /home/orkhan/Desktop/copilot-docprep commit -m "documents: one file rule per document; capture_requirements copies the programme's file rules"
```

---

### Task 4: The isolated parser prepares a file

**Files:**
- Modify: `ocr/read_pages.py`: add `prepare(parts, target)`, a `handler` branch for `op: prepare`, and a `--prepare` CLI.
- Test: `ocr/test_read_pages.py`

**Interfaces:**
- Produces:
  - `prepare(parts: list[bytes], target: dict) -> dict`.
  - `target` is `{"format": "PDF" | "JPG" | "PDF_OR_JPG" | None, "max_bytes": int | None, "one_file": bool}`.
  - It returns `{"content_type": str, "sha256": str, "body": <base64 str>, "unchanged": bool}` or `{"refused": <reason>}`.
  - The reasons are `unreadable | encrypted | signed | pages | too_large | too_large_to_return`.
- Handler event `{"op": "prepare", "parts": [{"key": str, "version_id": str} | {"inline": <base64>}], "target": {...}}`.
- The CLI `--prepare` reads the same JSON on stdin, with inline parts only.

- [ ] **Step 1: Write the failing tests.** Append to `ocr/test_read_pages.py`. The module's `_png` and `_scanned_pdf` helpers already exist.

```python
import base64
import json

from pypdf import PdfReader, PdfWriter


def _body(result):
    return base64.b64decode(result["body"])


def _signed_pdf():
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer._root_object.update({  # an AcroForm signature field: what makes a PDF "signed"
        rp.NameObject("/AcroForm"): rp.DictionaryObject({rp.NameObject("/SigFlags"): rp.NumberObject(3)}),
    })
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()


def test_a_file_that_already_fits_comes_back_byte_for_byte():
    pdf = _scanned_pdf(200)
    result = rp.prepare([pdf], {"format": "PDF", "max_bytes": len(pdf) + 1, "one_file": False})
    assert result["unchanged"] is True and _body(result) == pdf


def test_two_images_become_one_pdf_with_two_pages():
    result = rp.prepare([_png(), _png()], {"format": "PDF", "max_bytes": None, "one_file": True})
    assert result["content_type"] == "application/pdf"
    assert len(PdfReader(io.BytesIO(_body(result))).pages) == 2


def test_an_oversized_image_is_recompressed_under_the_cap():
    big = _png((3000, 4000))
    result = rp.prepare([big], {"format": "JPG", "max_bytes": 300_000, "one_file": False})
    assert result["content_type"] == "image/jpeg" and len(_body(result)) <= 300_000


def test_a_one_page_pdf_becomes_a_jpg_and_a_long_one_is_refused():
    one = rp.prepare([_scanned_pdf(150)], {"format": "JPG", "max_bytes": None, "one_file": False})
    assert one["content_type"] == "image/jpeg"
    assert rp.prepare([_scanned_pdf(150, pages=3)], {"format": "JPG", "max_bytes": None,
                                                      "one_file": False}) == {"refused": "pages"}


def test_a_signed_pdf_is_never_rewritten():
    signed = _signed_pdf()
    fits = rp.prepare([signed], {"format": "PDF", "max_bytes": None, "one_file": False})
    assert _body(fits) == signed
    merged = rp.prepare([signed, _png()], {"format": "PDF", "max_bytes": None, "one_file": True})
    assert merged == {"refused": "signed"}


def test_an_oversized_pdf_with_no_format_rule_stays_a_pdf():
    pdf = _scanned_pdf(300, pages=2)
    result = rp.prepare([pdf], {"format": None, "max_bytes": len(pdf) // 2, "one_file": False})
    assert result.get("content_type", "application/pdf") == "application/pdf"


def test_what_cannot_fit_is_refused_not_truncated():
    assert rp.prepare([_png((3000, 4000))], {"format": "PDF", "max_bytes": 10_000,
                                             "one_file": False}) == {"refused": "too_large"}
    assert rp.prepare([b"not a document"], {"format": "PDF", "max_bytes": None,
                                            "one_file": False}) == {"refused": "unreadable"}


def test_the_handler_reads_only_the_named_versions_and_inline_parts():
    png = _png()

    class S3:
        def get_object(self, **kw):
            assert kw["VersionId"] == "v1"
            return {"Body": io.BytesIO(png)}

    event = {"op": "prepare", "parts": [{"key": "quarantine/x", "version_id": "v1"},
                                        {"inline": base64.b64encode(png).decode()}],
             "target": {"format": "PDF", "max_bytes": None, "one_file": True}}
    result = rp.handler(event, None, s3=S3())
    assert len(PdfReader(io.BytesIO(_body(result))).pages) == 2
```

- [ ] **Step 2: Run them to see them fail.** Run: `uv run --project ocr pytest ocr -q -k "prepare or fits or signed or handler_reads"`. Expected: FAIL (`AttributeError: module 'read_pages' has no attribute 'prepare'`).

- [ ] **Step 3: Implement**, in `ocr/read_pages.py`:

```python
import base64
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject  # re-exported for tests

#: A synchronous Lambda answer is capped at 6 MB and base64 grows by a third.
#: ponytail: bigger bundles need a write-only output prefix for this function.
RETURN_MAX = 4_000_000
_JPEG_STEPS = ((2400, 85), (2000, 75), (1600, 70), (1200, 60), (1000, 50))


def _type(data: bytes) -> str | None:
    return next((name for magic, name in ALLOWED_TYPES if data.startswith(magic)), None)


def _signed(data: bytes) -> bool:
    """A PDF carrying a signature: an AcroForm with SigFlags, or a /ByteRange."""
    reader = PdfReader(io.BytesIO(data))
    form = reader.trailer["/Root"].get("/AcroForm")
    return b"/ByteRange" in data or bool(form and form.get_object().get("/SigFlags"))


def _jpeg(image: Image.Image, cap: int | None) -> bytes | None:
    image = image.convert("RGB")
    for side, quality in _JPEG_STEPS:
        copy = image.copy()
        copy.thumbnail((side, side))
        out = io.BytesIO()
        copy.save(out, "JPEG", quality=quality, optimize=True)
        if cap is None or out.tell() <= cap:
            return out.getvalue()
    return None


def _as_pdf(data: bytes, kind: str) -> bytes:
    if kind == "application/pdf":
        return data
    out = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(out, "PDF", resolution=150)
    return out.getvalue()


def _merged(pdfs: list[bytes]) -> bytes:
    writer = PdfWriter()
    for pdf in pdfs:
        writer.append(PdfReader(io.BytesIO(pdf)))
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()


def _shrunk_pdf(pdf: bytes, cap: int) -> bytes | None:
    """Re-encode each page image down the JPEG steps until the file fits."""
    for side, quality in _JPEG_STEPS:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
        for page in writer.pages:
            for image in page.images:
                shrunk = image.image.convert("RGB")
                shrunk.thumbnail((side, side))
                image.replace(shrunk, quality=quality)
            page.compress_content_streams()
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        out = io.BytesIO(); writer.write(out)
        if out.tell() <= cap:
            return out.getvalue()
    return None


def _answer(body: bytes, content_type: str, *, unchanged: bool) -> dict:
    if len(body) > RETURN_MAX:
        return {"refused": "too_large_to_return"}
    return {"content_type": content_type, "sha256": hashlib.sha256(body).hexdigest(),
            "body": base64.b64encode(body).decode(), "unchanged": unchanged}


def prepare(parts: list[bytes], target: dict) -> dict:
    """One file that meets `target`, or a refusal naming why (plan 4, Task 4).

    Never rewrites what already fits, and never rewrites a signed PDF.
    """
    kinds = [_type(p) for p in parts]
    if not parts or None in kinds:
        return {"refused": "unreadable"}
    try:
        pdfs = [p for p, k in zip(parts, kinds) if k == "application/pdf"]
        if any(PdfReader(io.BytesIO(p)).is_encrypted for p in pdfs):
            return {"refused": "encrypted"}
        signed = any(_signed(p) for p in pdfs)
        want, cap = target.get("format"), target.get("max_bytes")
        allowed = {"PDF": {"application/pdf"}, "JPG": {"image/jpeg"},
                   "PDF_OR_JPG": {"application/pdf", "image/jpeg"}}.get(want)
        if len(parts) == 1 and (allowed is None or kinds[0] in allowed) and (
                cap is None or len(parts[0]) <= cap):
            return _answer(parts[0], str(kinds[0]), unchanged=True)
        if signed:
            return {"refused": "signed"}
        # A PDF stays a PDF unless JPG is demanded; an image becomes a JPEG
        # unless PDF is demanded. Several parts are always one PDF.
        if len(parts) > 1 or want == "PDF" or (want != "JPG" and kinds[0] == "application/pdf"):
            if len(parts) > 1 and want == "JPG":
                return {"refused": "pages"}
            merged = _merged([_as_pdf(p, str(k)) for p, k in zip(parts, kinds)])
            fitted = merged if cap is None or len(merged) <= cap else _shrunk_pdf(merged, cap)
            if fitted is None:
                return {"refused": "too_large"}
            return _answer(fitted, "application/pdf", unchanged=False)
        if kinds[0] == "application/pdf":
            document = pypdfium2.PdfDocument(parts[0])
            if len(document) != 1:
                return {"refused": "pages"}
            image = document[0].render(scale=150 / 72).to_pil()
        else:
            image = Image.open(io.BytesIO(parts[0]))
        jpeg = _jpeg(image, cap)
        return {"refused": "too_large"} if jpeg is None else _answer(jpeg, "image/jpeg",
                                                                     unchanged=False)
    except Exception:
        # A malformed part is the file not being preparable, never a crash that
        # would read as OCR being unavailable -- and the message never carries
        # the document's text.
        return {"refused": "unreadable"}
```

In `handler`, before the `version_id` check:

```python
    if event.get("op") == "prepare":
        if s3 is None:
            import boto3

            s3 = boto3.client("s3")
        parts = []
        for part in event["parts"]:
            if "inline" in part:
                parts.append(base64.b64decode(part["inline"]))
                continue
            if not part.get("version_id"):
                raise ValueError("no version_id: only the scanned version of an upload is read")
            body = s3.get_object(Bucket=os.environ["DOCUMENT_BUCKET"], Key=part["key"],
                                 VersionId=part["version_id"], Range=f"bytes=0-{MAX_BYTES}")["Body"].read()
            if len(body) > MAX_BYTES:
                return {"refused": "too_large"}
            parts.append(body)
        return prepare(parts, event["target"])
```

In `__main__`, add a branch before `--inspect`. Its stdin is JSON, not raw bytes:

```python
    if sys.argv[1:] == ["--prepare"]:
        envelope = json.loads(data)
        print(json.dumps(prepare([base64.b64decode(p["inline"]) for p in envelope["parts"]],
                                 envelope["target"])))
        raise SystemExit(0)
```

Note: `MAX_BYTES + 1` caps that stdin read. Raise the CLI's read limit for `--prepare` to `4 * MAX_BYTES`. Base64 parts of several files exceed one file's cap.

- [ ] **Step 4: Run them to see them pass.** Run: `uv run --project ocr pytest ocr -q`. Expected: PASS, the old inventory tests included.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-docprep add ocr/read_pages.py ocr/test_read_pages.py
git -C /home/orkhan/Desktop/copilot-docprep commit -m "ocr: prepare a file to a target in the isolated parser; never rewrite what fits or what is signed"
```

---

### Task 5: The worker's seam, the `PreparedDocument` row and its storage

**Files:**
- Modify: `apps/documents/ocr.py`: add `Part`, `Prepared`, and `prepare_files`.
- Modify: `apps/documents/storage.py`: add `prepared_key`, `store_prepared` and `read_prepared`.
- Modify: `apps/portals/models.py`: add `PreparedDocument`.
- Create: `apps/portals/migrations/0025_prepared_document.py`, containing makemigrations output plus `RunSQL` RLS and FK guards.
- Modify: `apps/audit/redaction.py`: add `REDACT` and `KEEP` entries.
- Test: `tests/documents/test_ocr_prepare.py` (new), and `tests/portals/test_prepared_document.py` (new).

**Interfaces:**
- Produces in `apps/documents/ocr.py`:

```python
@dataclass(frozen=True)
class Part:
    upload: DocumentVersion | None = None   # read by the parser from its scanned version
    own: bytes = b""                         # our generated document, sent inline

class Prepared(BaseModel):  # extra="forbid"
    content_type: Literal["application/pdf", "image/jpeg", "image/png"] | None = None
    sha256: str = ""
    body: bytes = b""
    unchanged: bool = False
    refused: str = ""

def prepare_files(parts: Sequence[Part], target: FileRule) -> Prepared   # OcrUnavailable on transport failure
```

- Produces in `apps/documents/storage.py`: `prepared_key(*, tenant_id, student_id, prepared_id, sha256) -> str` gives `tenants/{t}/students/{s}/prepared/{prepared_id}/{sha256[:16]}`. Also `store_prepared(key, body, store=None)`, `read_prepared(key) -> bytes`, and `delete_prepared(key, store=None)`.
  - Check `S3ObjectStore` for a `delete`. If it has none, add one in this task beside its `put`/`get`, under the same `tenants/*` grant.
- Produces in `apps/portals/models.py`: `PreparedDocument`, with fields as in Step 3.

- [ ] **Step 1: Write the failing tests.**

`tests/documents/test_ocr_prepare.py`. Local mode runs the real child, as `inspect_upload`'s tests do. Find the local-child test settings with `grep -n OCR_PYTHON tests -r`.

```python
import io

import pytest
from PIL import Image

from apps.documents.file_rules import FileRule
from apps.documents.ocr import Part, prepare_files


def _png():
    out = io.BytesIO(); Image.new("RGB", (800, 1100), "white").save(out, "PNG")
    return out.getvalue()


def test_our_own_document_goes_inline_and_comes_back_as_a_pdf(settings):
    settings.OCR_FUNCTION_NAME = ""
    result = prepare_files([Part(own=_png())], FileRule(format="PDF"))
    assert result.content_type == "application/pdf" and result.body.startswith(b"%PDF")


def test_a_lambda_event_names_uploads_by_key_and_scanned_version(settings, monkeypatch):
    settings.OCR_FUNCTION_NAME = "ocr"
    sent = {}

    def invoke(key, version, op="", body=None):
        sent.update(body)
        return b'{"refused": "too_large"}'

    monkeypatch.setattr("apps.documents.ocr._invoke_event", invoke)
    upload = type("U", (), {"object_key": "quarantine/a", "scanned_version": "v9"})()
    result = prepare_files([Part(upload=upload), Part(own=b"%PDF-1.7")], FileRule(max_bytes=1))
    assert sent["parts"][0] == {"key": "quarantine/a", "version_id": "v9"}
    assert "inline" in sent["parts"][1] and result.refused == "too_large"
```

In `tests/portals/test_prepared_document.py`:
- **RLS:** a `PreparedDocument` written in tenant A is invisible to tenant B through `rls_enforced_orm`. Copy the pattern of the nearest test that uses that fixture: `grep -rln rls_enforced_orm tests/portals`.
- **Composite FK:** an application from another tenant is refused with `IntegrityError` (the composite FK).
- **Erasure:** `redact_student` blanks `filename`.

- [ ] **Step 2: Run them to see them fail.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/documents/test_ocr_prepare.py tests/portals/test_prepared_document.py -q`. Expected: FAIL (ImportError).

- [ ] **Step 3: Implement.**

`apps/documents/ocr.py`. Refactor `_invoke` so an arbitrary event can be sent. `_invoke(key, version, op)` keeps its signature and builds the event as today. Both call one new `_invoke_event(key, version, op="", body=None)`, which sends `body` when given:

```python
#: Inline parts are our own documents; the request itself is capped at 6 MB.
_INLINE_MAX = 4_000_000


def prepare_files(parts: Sequence[Part], target: FileRule) -> Prepared:
    """Plan 4: one file meeting `target`, built where untrusted files are parsed.
    Uploads travel as their scanned version's key; our own documents inline."""
    target_json = {"format": target.format, "max_bytes": target.max_bytes,
                   "one_file": target.one_file}
    if sum(len(p.own) for p in parts) > _INLINE_MAX:
        return Prepared(refused="too_large")
    if settings.OCR_FUNCTION_NAME:
        event_parts = [
            {"key": p.upload.object_key, "version_id": _scanned_version(p.upload)}
            if p.upload is not None else {"inline": base64.b64encode(p.own).decode()}
            for p in parts
        ]
        raw = _invoke_event("", "", body={"op": "prepare", "parts": event_parts,
                                          "target": target_json})
    else:
        # Locally the child gets every part inline: the promoted copy is the same
        # bytes the scan cleared (promote_upload copies only the verdict's digest).
        from .storage import read_upload

        inline = [read_upload(p.upload) if p.upload is not None else p.own for p in parts]
        envelope = {"parts": [{"inline": base64.b64encode(b).decode()} for b in inline],
                    "target": target_json}
        raw = _run_child(json.dumps(envelope).encode(), "--prepare")
    try:
        answer = json.loads(raw)
        if "refused" in answer:
            return Prepared(refused=str(answer["refused"]))
        body = base64.b64decode(answer["body"])
        if hashlib.sha256(body).hexdigest() != answer["sha256"]:
            raise OcrUnavailable("digest mismatch")
        return Prepared(content_type=answer["content_type"], sha256=answer["sha256"],
                        body=body, unchanged=bool(answer["unchanged"]))
    except (ValueError, KeyError, ValidationError) as error:
        raise OcrUnavailable("unparseable output") from error
```

`apps/documents/storage.py`:

```python
_PREPARED_TEMPLATE = "tenants/{tenant_id}/students/{student_id}/prepared/{prepared_id}/{digest}"


def prepared_key(*, tenant_id: UUID, student_id: UUID, prepared_id: UUID, sha256: str) -> str:
    """Under the student's own prefix, so erasure's prefix purge removes it. The
    digest, not the filename, names the object: a name may carry the student's."""
    return _PREPARED_TEMPLATE.format(tenant_id=tenant_id, student_id=student_id,
                                     prepared_id=prepared_id, digest=sha256[:16])


def store_prepared(key: str, body: bytes, *, store: S3ObjectStore | None = None) -> None:
    (store or _object_store()).put(key, body)


def read_prepared(key: str) -> bytes:
    return _object_store().get(key)


def delete_prepared(key: str, *, store: S3ObjectStore | None = None) -> None:
    """A replaced prepared copy. Never raises: a leftover object is purged with the
    student's prefix on erasure anyway."""
    try:
        (store or _object_store()).delete(key)
    except Exception as error:
        logger.warning("could not delete a replaced prepared object (%s)", type(error).__name__)
```

`apps/portals/models.py`:

```python
class PreparedDocument(TenantScopedModel):
    """One document of one application, prepared to the programme's file rules
    (plan 4). `slot` names what it replaces: "CV:<draft id>", "DIPLOMA:<upload
    id>", "DIPLOMA" for all diplomas merged, or "EVERY_DOCUMENT" for the whole
    application. Served only while `inputs_digest` matches the current sources
    and rules (apps.portals.prepare.current_prepared)."""

    class State(models.TextChoices):
        READY = "READY", "Ready"
        CANNOT_FIT = "CANNOT_FIT", "Cannot fit the rules"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    application = models.ForeignKey(Application, on_delete=models.PROTECT,
                                    related_name="prepared_documents")
    student = models.ForeignKey(Membership, on_delete=models.PROTECT,
                                related_name="prepared_documents")
    slot = models.CharField(max_length=80)
    document = models.CharField(max_length=32)
    #: [{"source": "draft" | "upload", "id": "<uuid>"}], in the file's order.
    sources = models.JSONField(default=list)
    inputs_digest = models.CharField(max_length=64)
    state = models.CharField(max_length=12, choices=State.choices)
    #: Why it cannot fit (signed, too_large, pages, encrypted, unreadable,
    #: too_large_to_return), or a note on a READY file (name_needs_surname).
    reason = models.CharField(max_length=40, blank=True)
    filename = models.CharField(max_length=100, blank=True)
    content_type = models.CharField(max_length=40, blank=True)
    byte_size = models.PositiveIntegerField(null=True, blank=True)
    object_key = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="prepareddoc_tenant_id_uniq"),
            models.UniqueConstraint(fields=("application", "slot"), name="prepareddoc_one_per_slot"),
        ]
```

Migration:
- Run `makemigrations portals -n prepared_document`.
- Append `migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)` with the exact shape of `0019_portal_accounts.py`, for table `portals_prepareddocument`.
- Add two composite guards, one per FK, with the shape of `0023_dashboard_tenant_guards.py`:
  - `prepareddoc_application_tenant_fk` on `(tenant_id, application_id) → portals_application (tenant_id, id)`;
  - `prepareddoc_student_tenant_fk` on `(tenant_id, student_id) → tenancy_membership (tenant_id, id)`.

`redaction.py`:
- `REDACT["portals.PreparedDocument"] = RedactSpec("student_id", ("filename",))`. The comment: a file name can carry the student's name.
- `KEEP["portals.PreparedDocument"]` = every other classifiable field: `slot`, `document`, `sources`, `inputs_digest`, `state`, `reason`, `content_type`, `byte_size`, `object_key`, `created_at`. The object itself goes with the student's prefix.

- [ ] **Step 4: Run them to see them pass.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/documents/test_ocr_prepare.py tests/portals/test_prepared_document.py tests/audit tests/tenancy -q && uv run python manage.py makemigrations --check --dry-run && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config -q`. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-docprep add apps/documents/ocr.py apps/documents/storage.py apps/portals apps/audit/redaction.py tests
git -C /home/orkhan/Desktop/copilot-docprep commit -m "documents: the worker's prepare seam and the PreparedDocument row, under RLS and erasure"
```

---

### Task 6: Prepare an application's documents in the worker

**Files:**
- Create: `apps/portals/prepare.py`
- Modify: `apps/documents/document_queue.py`: `DocumentWorkMessage.action` gains `"prepare_documents"`.
- Modify: `apps/documents/document_worker.py`: dispatch `prepare_documents`; `_capture` calls `prepare_documents` after the copy; after `promote_upload`, prepare for the student's open applications.
- Modify: `apps/documents/approval.py`: on commit, queue preparation for the student's open applications.
- Modify: `apps/portals/applications.py`: `start_application` queues preparation as well, a cheap no-op when the files are current.
- Test: `tests/portals/test_prepare.py` (new)

**Interfaces:**
- Consumes:
  - `rule_for`, `bundle_rule`, `DRAFT_DOCUMENT` and `UPLOAD_DOCUMENT` from Task 3;
  - `prepare_files`, `Part` and `Prepared` from Task 5;
  - `PreparedDocument` from Task 5;
  - `apps.documents.table.table_for(...)` and `Table.held_for(kind, application_id)`. These already decide which ONE document fills each kind for this application:
    - the application's own document before a general one;
    - a certified copy where one is asked for;
    - only `SENDABLE` states.
  - Preparation never chooses documents itself. That way no CV is sent twice, and no superseded upload or document made for another programme is sent.
- Produces in `apps/portals/prepare.py`:

```python
@dataclass(frozen=True)
class Job:
    slot: str
    document: str
    sources: tuple[tuple[str, UUID], ...]      # ("draft" | "upload", id)
    rule: FileRule
    filename: str
    reason: str                                 # "" or name_needs_surname
    digest: str

def jobs_for(application: Application) -> list[Job]                       # pure over tenant rows
def prepare_documents(application: Application, *, transform=prepare_files, store=None) -> list[PreparedDocument]
def current_prepared(application: Application) -> dict[str, PreparedDocument]   # web-safe
def queue_for_student(tenant_id: UUID, student_id: UUID) -> None         # after commit, never raises
def file_name(pattern: str | None, *, full_name: str, fallback: str, extension: str) -> tuple[str, str]
```

- [ ] **Step 1: Write the failing tests.** Create `tests/portals/test_prepare.py`. Use the factories the kit tests use (`tests/portals/test_kit_page.py`: an agency, a membership, an `Application`); an approved CV draft with `rendered_filename`; and an `AVAILABLE` `DocumentVersion` of kind `DIPLOMA`. Pass a fake `transform` that records its calls and returns `Prepared(content_type="application/pdf", sha256=<sha of b"%PDF-x">, body=b"%PDF-x")`. Pass a dict-backed `store`.

```python
def test_no_rule_prepares_nothing(application_with_cv):
    assert prepare_documents(application_with_cv, transform=_never, store=_Store()) == []


def test_a_cv_cap_prepares_the_cv_under_the_student_prefix(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    [prepared] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    assert prepared.state == "READY" and prepared.slot.startswith("CV:")
    assert prepared.object_key.startswith(
        f"tenants/{application_with_cv.tenant_id}/students/{application_with_cv.student_id}/prepared/")


def test_only_the_document_the_table_holds_is_prepared(application_with_cv_draft_and_cv_upload):
    """The table sends the approved CV draft, not also the student's uploaded CV."""
    application_with_cv_draft_and_cv_upload.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    [job] = jobs_for(application_with_cv_draft_and_cv_upload)
    assert job.sources[0][0] == "draft"


def test_the_bundle_leaves_out_what_the_programme_does_not_list(application_with_cv_diploma_passport):
    """Owner 2026-10-09: only what the programme lists. Its kit_requirements name
    the CV and the diploma; the passport the student holds stays out."""
    application_with_cv_diploma_passport.kit_file_rules = [_r("EVERY_DOCUMENT", "combine", "ONE_FILE")]
    [job] = jobs_for(application_with_cv_diploma_passport)
    assert {_kind_of(s) for s in job.sources} == {"CV", "DIPLOMA"}


def test_the_bundle_replaces_every_per_document_job(application_with_cv_and_diploma):
    application_with_cv_and_diploma.kit_file_rules = [
        _r("EVERY_DOCUMENT", "combine", "ONE_FILE"), _r("DIPLOMA", "max_bytes", 2_000_000)]
    [job] = jobs_for(application_with_cv_and_diploma)
    assert job.slot == "EVERY_DOCUMENT" and job.sources[0][0] == "draft"   # the CV leads


def test_a_refusal_is_recorded_with_its_reason(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    [prepared] = prepare_documents(application_with_cv, transform=lambda *_: Prepared(refused="signed"),
                                   store=_Store())
    assert (prepared.state, prepared.reason, prepared.object_key) == ("CANNOT_FIT", "signed", "")


def test_re_preparing_a_slot_deletes_the_object_it_replaces(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    store = _Store()
    [first] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 1_000_000)]   # a re-read page
    [second] = prepare_documents(application_with_cv, transform=_fake_pdf, store=store)
    assert first.object_key not in store.objects and second.object_key in store.objects


def test_a_second_run_with_nothing_changed_does_not_call_the_parser(application_with_cv):
    application_with_cv.kit_file_rules = [_r("CV", "max_bytes", 2_000_000)]
    prepare_documents(application_with_cv, transform=_fake_pdf, store=_Store())
    assert prepare_documents(application_with_cv, transform=_never, store=_Store())


def test_review_focus_3_a_replaced_upload_makes_the_prepared_file_stale(application_with_diploma):
    application_with_diploma.kit_file_rules = [_r("DIPLOMA", "max_bytes", 2_000_000)]
    prepare_documents(application_with_diploma, transform=_fake_pdf, store=_Store())
    _replace_diploma(application_with_diploma)   # a newer upload now fills the cell
    assert current_prepared(application_with_diploma) == {}


def test_names_never_guess_a_surname():
    assert file_name("{surname}_CV.pdf", full_name="Aysel Məmmədova", fallback="cv-standard.pdf",
                     extension=".pdf") == ("cv-standard.pdf", "name_needs_surname")
    assert file_name("{full_name}_CV.pdf", full_name="Aysel Məmmədova", fallback="x.pdf",
                     extension=".pdf") == ("Aysel_Memmedova_CV.pdf", "")
    assert file_name("{surname}_CV.pdf", full_name="Aysel Məmmədova", fallback="x.pdf",
                     extension=".pdf", surname="Məmmədova") == ("Memmedova_CV.pdf", "")
```

- [ ] **Step 2: Run them to see them fail.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/portals/test_prepare.py -q`. Expected: FAIL (`ModuleNotFoundError: apps.portals.prepare`).

- [ ] **Step 3: Implement** `apps/portals/prepare.py`:

```python
"""Plan 4: each document an application will attach, prepared to the programme's
written file rules before the student reaches the portal (spec §7, D4).

Worker-side for everything that transforms (`prepare_documents`); web-safe for
the read the kit and packet make (`current_prepared`): it reads tenant rows only
-- Application.kit_file_rules, drafts, uploads, the ledger -- never the catalogue.
Uploads are transformed only in the isolated parser (apps.documents.ocr).
"""

from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction

from apps.concierge.models import DocumentVersion
from apps.documents import storage
from apps.documents.document_queue import DocumentWorkMessage, enqueue_document_work
from apps.documents.file_rules import (
    DRAFT_DOCUMENT, UPLOAD_DOCUMENT, FileRule, bundle_rule, rule_for,
)
from apps.documents.ocr import OcrUnavailable, Part, Prepared, prepare_files
from apps.tenancy.db import tenant_transaction

from .models import Application, PreparedDocument
from .profile import verified_values

logger = logging.getLogger(__name__)

_EXTENSION = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
_FOLD = str.maketrans({"ə": "e", "Ə": "E", "ı": "i", "İ": "I"})
#: The bundle's order: R-008's own (CV, academic documents, language, references,
#: nationality). ponytail: one fixed order; a page stating another is a note.
_BUNDLE_ORDER = ("CV", "MOTIVATION_LETTER", "DIPLOMA", "TRANSCRIPT", "LANGUAGE_CERTIFICATE",
                 "REFERENCE_LETTER", "PASSPORT")


@dataclass(frozen=True)
class Job:
    slot: str
    document: str
    sources: tuple[tuple[str, UUID], ...]
    rule: FileRule
    filename: str
    reason: str
    digest: str


def _ascii(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.translate(_FOLD))
    return "".join(c for c in folded if c.isascii() and (c.isalnum() or c in "._-") or c == " ")


def file_name(pattern: str | None, *, full_name: str, fallback: str,
              extension: str, surname: str = "") -> tuple[str, str]:
    """The name the page asked for, or the fallback and why. Never a guessed surname:
    the ledger holds a full name only (IDENTITY.full_name)."""
    stem = fallback.rsplit(".", 1)[0]
    if not pattern:
        return f"{stem}{extension}", ""
    if "{given_name}" in pattern or ("{surname}" in pattern and not surname):
        return f"{stem}{extension}", "name_needs_surname"
    filled = pattern.replace("{full_name}", full_name).replace("{surname}", surname)
    name = _ascii(filled).replace(" ", "_")
    name = name.rsplit(".", 1)[0] + extension
    return (name, "") if storage.SAFE_FILENAME.match(name) else (f"{stem}{extension}", "name_unsafe")


def _held(application: Application, *, listed_only: bool = False) -> list[tuple[str, object, str]]:
    """(source, row, FILE_FIELDS document) for each kind this application's cell
    holds in a sendable state -- the document table's choice, never ours.

    `listed_only`: only kinds whose cell is not NOT_NEEDED, i.e. kinds the
    programme's own sentences name. The whole-application bundle uses it (owner,
    2026-10-09): a document nobody asked for is not sent in one PDF."""
    from apps.documents.models import DocumentDraft
    from apps.documents.table import ROWS, SENDABLE, Cell, table_for
    from apps.mailbox.models import MailSignal

    table = table_for(application.student, [application],
                      MailSignal.objects.filter(application=application).select_related("connection"))
    out: list[tuple[str, object, str]] = []
    column = next(i for i, c in enumerate(table.columns) if c.application_id == application.id)
    for (kind, _label), row in zip(ROWS, table.rows, strict=True):
        if listed_only and row.cells[column] == Cell.NOT_NEEDED:
            continue
        held = table.held_for(kind, application.id)
        if held is None or held.state not in SENDABLE or held.document_id is None:
            continue
        document = DRAFT_DOCUMENT.get(kind) if held.source == "draft" else UPLOAD_DOCUMENT.get(kind)
        if document is None:
            continue
        if held.source == "draft":
            row = DocumentDraft.objects.filter(id=held.document_id).exclude(rendered_filename="").first()
        else:
            row = DocumentVersion.objects.filter(id=held.document_id, state="AVAILABLE").exclude(
                promoted_key="").first()
        if row is not None:
            out.append((held.source, row, document))
    return out


def _marker(source: str, item: object) -> str:
    """What makes a source's bytes these bytes: an upload's promoted key carries
    its content digest; a draft's stored filename and version name its render."""
    if source == "upload":
        return str(item.promoted_key)  # type: ignore[attr-defined]
    return f"{item.version}:{item.rendered_filename}"  # type: ignore[attr-defined]


def jobs_for(application: Application) -> list[Job]:
    records = application.kit_file_rules or []
    facts = verified_values(application.student)
    full_name = facts.get("identity.full_name", "")
    #: Collected on the dashboard (owner, 2026-10-09), confirmed like any fact.
    surname = facts.get("identity.surname", "")
    items = _held(application)

    def job(slot: str, document: str, chosen: list[tuple[str, object, str]], rule: FileRule,
            fallback: str) -> Job:
        extension = ".jpg" if rule.format == "JPG" else ".pdf"
        name, reason = file_name(rule.name_pattern, full_name=full_name, fallback=fallback,
                                 extension=extension, surname=surname)
        sources = tuple((s, item.id) for s, item, _ in chosen)  # type: ignore[attr-defined]
        digest = hashlib.sha256(json.dumps(
            {"sources": [(s, str(i.id), _marker(s, i)) for s, i, _ in chosen],  # type: ignore[attr-defined]
             "rule": asdict(rule), "name": name}, sort_keys=True).encode()).hexdigest()
        return Job(slot, document, sources, rule, name, reason, digest)

    if (bundle := bundle_rule(records)) is not None:
        ordered = sorted(_held(application, listed_only=True),
                         key=lambda x: _BUNDLE_ORDER.index(x[2]))
        return [job("EVERY_DOCUMENT", "EVERY_DOCUMENT", ordered, bundle, "application.pdf")] if ordered else []
    # One document per kind (the table holds one per cell), so a per-kind
    # ONE_FILE has nothing to merge: it is kept on the rule, unused, until the
    # table holds several diplomas (see "Open for the owner").
    jobs: list[Job] = []
    for chosen in items:
        source, item, document = chosen
        rule = rule_for(records, document)
        if rule.empty:
            continue
        fallback = (item.rendered_filename if source == "draft"  # type: ignore[attr-defined]
                    else f"{document.lower()}{_EXTENSION.get(item.content_type, '.pdf')}")  # type: ignore[attr-defined]
        jobs.append(job(f"{document}:{item.id}", document, [chosen], rule, fallback))  # type: ignore[attr-defined]
    return jobs


def current_prepared(application: Application) -> dict[str, PreparedDocument]:
    """The prepared rows still true of the current sources and rules, by slot."""
    wanted = {j.slot: j.digest for j in jobs_for(application)}
    rows = PreparedDocument.objects.filter(application=application, slot__in=wanted)
    return {r.slot: r for r in rows if r.inputs_digest == wanted[r.slot]}


def prepare_documents(application: Application, *, transform=prepare_files,  # noqa: ANN001
                      store=None) -> list[PreparedDocument]:  # noqa: ANN001
    """Prepare every slot whose rows are missing or stale. Worker-side only.

    Every database read and write runs in a short tenant_transaction: under FORCE
    RLS a query with no `app.tenant_id` matches nothing (CLAUDE.md, failure mode
    1). The parser call runs OUTSIDE any transaction, because it can take minutes.
    The object is stored before its row says READY, so a failed put never leaves
    a READY row pointing at nothing; and a slot's previous object is deleted when
    it is replaced, so stale copies of a passport scan do not pile up.
    """
    from apps.documents.models import DocumentDraft

    with tenant_transaction(application.tenant_id):
        done = current_prepared(application)
        jobs = jobs_for(application)
        previous = {r.slot: r.object_key for r in
                    PreparedDocument.objects.filter(application=application)}
    results: list[PreparedDocument] = []
    for job in jobs:
        if job.slot in done:
            results.append(done[job.slot])
            continue
        with tenant_transaction(application.tenant_id):
            parts = []
            for source, source_id in job.sources:
                if source == "upload":
                    parts.append(Part(upload=DocumentVersion.objects.get(id=source_id)))
                else:
                    draft = DocumentDraft.objects.get(id=source_id)
                    parts.append(Part(own=storage.read_draft(draft, draft.rendered_filename)))
        try:
            answer: Prepared = transform(parts, job.rule)
        except OcrUnavailable:
            logger.warning("prepare: parser unavailable for application %s", application.id)
            continue  # the original is served; the next trigger tries again
        fields: dict[str, object] = {
            "tenant_id": application.tenant_id, "student": application.student,
            "document": job.document, "inputs_digest": job.digest,
            "sources": [{"source": s, "id": str(i)} for s, i in job.sources],
            "state": PreparedDocument.State.CANNOT_FIT, "reason": answer.refused,
            "filename": "", "content_type": "", "byte_size": None, "object_key": "",
        }
        if not answer.refused:
            prepared_id = uuid4()
            key = storage.prepared_key(tenant_id=application.tenant_id,
                                       student_id=application.student_id,
                                       prepared_id=prepared_id, sha256=answer.sha256)
            storage.store_prepared(key, answer.body, store=store)
            fields.update(
                state=PreparedDocument.State.READY, reason=job.reason, object_key=key,
                filename=job.filename.rsplit(".", 1)[0] + _EXTENSION[str(answer.content_type)],
                content_type=str(answer.content_type), byte_size=len(answer.body),
            )
        with tenant_transaction(application.tenant_id):
            row, _ = PreparedDocument.objects.update_or_create(
                application=application, slot=job.slot, defaults=fields)
        old = previous.get(job.slot, "")
        if old and old != row.object_key:
            storage.delete_prepared(old, store=store)
        results.append(row)
    return results


def queue_for_student(tenant_id: UUID, student_id: UUID) -> None:
    """Queue preparation for each open application of a student. After commit;
    never raises -- a lost message only means the original is served."""
    def _send() -> None:
        try:
            enqueue_document_work(
                DocumentWorkMessage(action="prepare_documents", kind="PREPARE",
                                    tenant_id=tenant_id, student_id=student_id),
                queue_url=settings.DOCUMENT_QUEUE_URL,
            )
        except Exception as error:
            logger.warning("could not queue prepare_documents (%s)", type(error).__name__)

    transaction.on_commit(_send)
```

Wiring:
- **Message:** in `document_queue.py`, add `"prepare_documents"` to the `action` Literal. Its docstring's deploy-order note already covers a new field; the worker rolls first.
- **Worker dispatch:** in `document_worker.py`, `handle_document_work` gets `elif message.action == "prepare_documents": _prepare(message)`.
- **`_prepare`:** under `tenant_scope(message.tenant_id)`, it loops over the student's `Application` rows that `applications.is_startable` accepts and calls `prepare_documents(application)`.
- **After capture:** `_capture` calls `prepare_documents(application)` after the copy. It is the same worker, so no message is needed.
- **After promotion:** after the successful `promote_upload` (document_worker.py ~158), outside the transaction, call `_prepare(...)` for that student. Wrap it in `try/except Exception` with one warning: a promotion never fails because preparation did.
- **After approval:** in `approval.approve_document`, after `record_event`, call `queue_for_student(locked.tenant_id, locked.student_id)`. Lazy-import inside the function, because `apps.documents` must not import `apps.portals` at module level.
- **On Start:** in `applications.start_application`, after `queue_action(...)`, call `queue_for_student(application.tenant_id, application.student_id)`.
- **Filename pattern:** make `_SAFE_FILENAME` public as `SAFE_FILENAME`, keeping `_SAFE_FILENAME = SAFE_FILENAME` for its callers.

- [ ] **Step 4: Run them to see them pass.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/portals tests/documents/test_document_worker.py tests/documents/test_approval.py -q && uv run mypy apps config`. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-docprep add apps tests
git -C /home/orkhan/Desktop/copilot-docprep commit -m "portals: prepare each application's documents in the worker, on capture, approval, promotion and Start"
```

---

### Task 7: The kit and the Fill Packet serve the prepared file

**Files:**
- Modify: `apps/portals/packets.py`:
  - `KitDocument` and `PacketDocument` gain `kind`, `content_type`, `note` and `prepared_id`.
  - `draft_id` becomes optional.
  - `_kit_documents` substitutes prepared rows.
  - `mint_packet` and `_record_packet` carry the new fields.
- Modify: `apps/portals/views.py` + `apps/portals/urls.py`: add `prepared_download`, at `prepared/<uuid:prepared_id>/<str:filename>`, named `portals-prepared-download`.
- Test: `tests/portals/test_prepare.py` (serving), `tests/portals/test_packets.py` (packet shape).

**Interfaces:**
- Consumes: `current_prepared` (Task 6).
- Produces:
  - `PacketDocument(filename, download_path, draft_id: UUID | None, prepared_id: UUID | None = None, kind: str = "", content_type: str = "application/pdf", note: str = "")`.
  - `KitDocument` gains the same four fields, with the same defaults, after `draft_id`. `draft_id` becomes `UUID | None`, because a bundle has no single draft. `note` is `""`, or a reason the panel can show (`signed`, `too_large`, `pages`, `encrypted`, `unreadable`, `too_large_to_return`, `name_needs_surname`, `name_unsafe`).

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_ready_prepared_cv_replaces_the_original_in_the_packet(prepared_cv_application):
    packet = mint_packet(prepared_cv_application)
    [document] = packet.documents
    assert document.prepared_id is not None and document.kind == "CV"
    assert document.download_path.startswith("/portals/prepared/")


def test_a_cannot_fit_bundle_falls_back_to_the_originals_with_its_reason(bundle_refused_application):
    """Review Focus 5."""
    documents = mint_packet(bundle_refused_application).documents
    assert {d.kind for d in documents} >= {"CV"}
    assert all(d.prepared_id is None for d in documents)
    assert any(d.note == "signed" for d in documents)


def test_the_prepared_route_serves_only_the_owner_a_current_ready_file(
        client, prepared_cv_application, other_student_login, owner_login):
    row = PreparedDocument.objects.get(application=prepared_cv_application)
    url = reverse("portals-prepared-download", args=[row.id, row.filename])

    owner_login(client)
    response = client.get(url)
    assert response.status_code == 200 and response.content == _STORED_BYTES
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert response["Content-Disposition"].startswith("attachment")

    other_student_login(client)
    assert client.get(url).status_code == 404

    owner_login(client)
    _replace_cv_draft(prepared_cv_application)   # the sources changed: the row is stale
    assert client.get(url).status_code == 404
```

`owner_login` and `other_student_login` log in the application's student and another student of the same tenant. Build them from the login helper the existing `download_document` tests use (`grep -rn "documents-download" tests`). `_STORED_BYTES` is what the fake store holds for the row.

- [ ] **Step 2: Run them to see them fail.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/portals/test_prepare.py tests/portals/test_packets.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.**

**`_kit_documents`:**
- Build the raw entries as today, with `kind=DRAFT_DOCUMENT.get(draft.kind, draft.kind)`, `content_type="application/pdf"` and `note=""`.
- Then `prepared = current_prepared(application)`, and apply the rules below.

```python
    if (bundle := prepared.get("EVERY_DOCUMENT")) is not None:
        if bundle.state == PreparedDocument.State.READY:
            return (_prepared_entry(bundle),)
        raw = tuple(replace(d, note=bundle.reason) for d in raw)  # Review Focus 5
    out = []
    for entry in raw:
        row = prepared.get(f"{entry.kind}:{entry.draft_id}") or prepared.get(entry.kind)
        if row is None:
            out.append(entry)
        elif row.state == PreparedDocument.State.READY:
            out.append(_prepared_entry(row))
        else:
            out.append(replace(entry, note=row.reason))
    return tuple(dict.fromkeys(out))   # a merged slot appears once
```

- `_prepared_entry(row)` builds `KitDocument(label=row.document, filename=row.filename, download_path=reverse("portals-prepared-download", args=[row.id, row.filename]), draft_id=None, prepared_id=row.id, kind=row.document, content_type=row.content_type, note=row.reason)`.
- When the row is READY, its `reason` is a name note, which is why it is still carried.

**Packet:**
- `mint_packet` maps every field across.
- `_record_packet`'s `documents` list gains `prepared_id`.
- In `ext_api._named_for`, a `"prepared"` source matches `prepared_id` in that same list. Keep it there for the uploads path that plan 5 adds, and add one test for it.

**Uploads (the Submit-document path).** `ext_api.document` already serves an upload named by a live `OPEN_UPLOAD_PAGE` action. That action's payload carries `application_id`. When it does, and that application has a current READY row for the upload's slot (`f"{document}:{upload.id}"`), the route serves the prepared bytes, type and filename instead of the original. Add one route test for this.
- The kit and the Fill Packet keep carrying only what they carry today (CV drafts), plus the bundle.
- Which upload box gets a diploma automatically is plan 5's.

**Route:**
- `@login_required`.
- Find `PreparedDocument` by id with `student=<requesting membership>` and `state=READY`.
- The row must be in `current_prepared(row.application)` and `filename` must equal the URL's.
- Otherwise 404, every refusal.
- On success, return `read_prepared(row.object_key)` with `row.content_type`, `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox; default-src 'none'`. These are `ext_api._inert`'s headers: import it, never copy it.

- [ ] **Step 4: Run them to see them pass, plus the whole portals suite and the web-role check.** Run: `POSTGRES_DB=elmify_copilot_docprep uv run pytest tests/portals tests/tenancy -q && uv run mypy apps config`.
- Expected: PASS.
- Add one test under `web_role_orm` (`tests/conftest.py`) that calls `_kit_documents` inside `reads_no_catalogue()`. The kit runs in the web tier and must not read `Program`.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-docprep add apps/portals tests/portals
git -C /home/orkhan/Desktop/copilot-docprep commit -m "portals: the kit and Fill Packet serve prepared files, and say why one could not be prepared"
```

---

### Task 8: The extension attaches the prepared file as what it is

Lands **after plan 1 merges**. Plan 1 rewrites `attachDocuments` (the visibility rule). Make this change on top of plan 1's version, not today's.

**Base:** `attachDocuments` as of `55f53c85` on `claude/copilot-on-page-guidance` (plan 1 Task 2 closed). Rebase this branch onto it, or onto plan 1's merge, before starting.

**`kind` matching goes through plan 1's gate, never around it** (elmify-97, 2026-10-09):
- The upload control's opener must pass `onScreen(el)`: a rect of at least 4×4, not off the left or top, no opacity-0 ancestor, and `elementFromPoint` hits it.
- Terms are matched against VISIBLE text only: the opener's `innerText` and `aria-label`, never `textContent`.
- A wrapping label holding more than one file input is skipped.
- `label[for]` is resolved with `querySelectorAll`.

`KIND_TERMS` only replaces where the terms come from (kind instead of filename). The predicate that decides whether a control may receive the file stays plan 1's, unchanged. Add one e2e test: a hidden input labelled "Passport" never receives a `PASSPORT` file; it becomes a panel row.

**Files:**
- Modify: `extension/src/types.ts`, `extension/src/content/index.ts`, `extension/src/content/fill.ts`, `extension/src/panel/` (strings for the notes).
- Test: `tests/portals/test_extension_e2e.py`, plus fixtures if needed.

**Interfaces:**
- Consumes: `PacketDocument`'s `kind`, `content_type`, `note` and `prepared_id` (Task 7).
- Produces: the attach item `{ filename, bytes, type, kind }`.

- [ ] **Step 1: Write the failing tests** in `tests/portals/test_extension_e2e.py`, following the existing attach tests:
  1. A packet document with `content_type: "image/jpeg"` and `kind: "PASSPORT"`, named `aliyev_passport.jpg`, lands in an input labelled "Passport scan". The attached `File.type` is `image/jpeg`; read it back in the page with `input.files[0].type`.
  2. A document renamed to `Aysel_Memmedova_CV.pdf` (kind `CV`) still lands in the CV input. Matching uses `kind`, not the name.
  3. A document with `note: "signed"` shows a panel row in the student's language. It says the file could not be prepared and why, and the original is attached.

- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/portals/test_extension_e2e.py -m extension -q -k "prepared or jpeg or kind"`. Expected: FAIL.

- [ ] **Step 3: Implement.**

`types.ts`:

```ts
export interface PacketDocument {
  filename: string;
  download_path: string;
  draft_id: string | null;
  prepared_id?: string | null;
  /** FILE_FIELDS document: CV, TRANSCRIPT, DIPLOMA, ..., EVERY_DOCUMENT. */
  kind?: string;
  content_type?: string;
  /** Why the file could not be prepared (signed, too_large, ...), or "". */
  note?: string;
}
```

`fill.ts`:
- `attachDocuments` takes `{ filename; bytes; type; kind }[]` and builds `new File([item.bytes], item.filename, { type: item.type })`.
- Replace `documentTerms(item.filename)` with `documentTerms(item.kind || item.filename)`, where:

```ts
const KIND_TERMS: Record<string, string[]> = {
  CV: CV_TERMS, MOTIVATION_LETTER: ["motivation", "statement", "letter"],
  REFERENCE_LETTER: ["reference", "recommendation"], TRANSCRIPT: ["transcript", "records", "grades"],
  DIPLOMA: ["diploma", "degree", "certificate"], PASSPORT: ["passport", "identity"],
  LANGUAGE_CERTIFICATE: ["language", "ielts", "toefl"], EVERY_DOCUMENT: ["application", "documents"],
};
function documentTerms(kindOrFilename: string): string[] {
  if (KIND_TERMS[kindOrFilename]) return KIND_TERMS[kindOrFilename];
  // ...the existing filename path, unchanged
}
```

`index.ts` passes `type: document_.content_type ?? "application/pdf"` and `kind: document_.kind ?? ""`. It also pushes a panel row for every `note`. The plan-1 strings table gains one localized line per reason in az/tr/ru/en, e.g. en `"We could not shrink <file> to the programme's limit: it is a signed document. It is attached as it is — check the portal accepts it."`. Keep the reason codes out of the page layer; the panel only.

- [ ] **Step 4: Run them to see them pass.** Run: `npm --prefix extension run check && uv run pytest tests/portals/test_extension_bundle.py -q && uv run pytest tests/portals/test_extension_e2e.py -m extension -q`. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git -C /home/orkhan/Desktop/copilot-docprep add extension tests/portals
git -C /home/orkhan/Desktop/copilot-docprep commit -m "extension: attach prepared files with their real type, match by kind, show why a file was not prepared"
```

---

## Owner decisions, 2026-10-09

- **The whole-application PDF holds only the kinds the programme lists** (`_held(listed_only=True)`); a document nobody asked for is not sent.
- **Several diplomas or transcripts per application are to be supported, as a rare case.**
  - The document table (`apps/documents/table.py`) holds one per kind per application today. Holding several is a separate change to that table, owed and not in this plan.
  - When it lands, `_held` returns every document of a kind. A per-kind `ONE_FILE` then merges them through the same `prepare` call the bundle uses, and Task 6 gains that branch and its test.
- **The surname is collected on the dashboard** as a confirmed `IDENTITY` fact `surname`. That collection is a separate change. This plan uses the fact when it exists, and otherwise shows the rename note.

- **A signed PDF is sent untouched, with a warning.** When a rule would change a signed e-diploma (shrink, merge, convert), it is attached exactly as issued. The panel says it is digitally signed and was therefore not changed, and asks the student to check the portal accepts it. This is the `signed` reason (Tasks 4, 7, 8).

Nothing is open for the owner.

Decided in the plan, not asked:
- Bundles over 4 MB are refused until a real application needs more; R-008 is the only measured case.
- No default size rule is applied when a page writes none (spec §7).
