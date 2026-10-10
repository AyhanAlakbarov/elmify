# Document Output Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the text-normalisation and metadata-scrubbing utilities that every generated CV, SOP and motivation letter must pass through before release.

**Architecture:** Three pure functions in a new `apps/documents/` package, each taking a value and returning a cleaned value with no I/O, no database access and no Django dependency. They are libraries awaiting a caller — the render layer that will invoke them does not exist yet, which is deliberate: these are independently testable now and the renderer wires them in later.

**Tech Stack:** Python 3.12, stdlib (`unicodedata`, `re`, `zipfile`, `io`), `pypdf` for PDF, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-08-21-phase2-cv-engine-design.md` (PDF output contract) implementing `phased requirements.md` §4.2.3 "Generated document output hygiene".

## Global Constraints

- Python `>=3.12,<3.13`. Django 5.2. Managed by `uv` — never `pip install` directly.
- Ruff: `line-length = 100`, lint rules `["E", "F", "I", "UP"]`. Run `uv run ruff format` and `uv run ruff check` before committing.
- Tests live under `tests/<app>/` mirroring `apps/<app>/`. Every test directory needs `__init__.py`.
- `DJANGO_SETTINGS_MODULE = config.settings.test` (already configured in `pyproject.toml`).
- Bandit runs on every commit via pre-commit. `pre-commit` lives in the project venv, so commits need `.venv/bin` on PATH: `export PATH="$PWD/.venv/bin:$PATH"`.
- §4.2.3 permits **hygiene only**. These functions must never attempt to remove, obscure or defeat signals that a document was produced with AI assistance. Scope is toolchain metadata and character-level text cleanliness.
- Never strip letters or diacritics. Applicant names (`Łódź`, `Aygün`, `Češka`) and institution names in original scripts must survive byte-identical.

## File Structure

| File | Responsibility |
|---|---|
| `apps/documents/__init__.py` | Package marker. No Django app registration yet — `apps.py`, `models.py` and `INSTALLED_APPS` arrive with the models task in a later plan. These are plain importable functions. |
| `apps/documents/hygiene.py` | All three functions. One file because they share one purpose (release-time cleaning) and are small; splitting by format would scatter a single responsibility across three files. |
| `tests/documents/__init__.py` | Test package marker. |
| `tests/documents/test_hygiene.py` | Tests for all three functions. |
| `pyproject.toml` | Adds the `pypdf` dependency (Task 2 only). |

---

### Task 1: Text hygiene functions

**Files:**
- Create: `apps/documents/__init__.py` (empty)
- Create: `apps/documents/hygiene.py`
- Create: `tests/documents/__init__.py` (empty)
- Create: `tests/documents/test_hygiene.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize_text(text: str) -> str` and `to_ascii_punctuation(text: str) -> str`, both importable from `apps.documents.hygiene`. The PDF and DOCX functions in Tasks 2-3 do not call either.

**Why these specific characters:** zero-width and soft-hyphen characters survive copy-paste and corrupt the receiving side's text extraction — the same extraction R-043 depends on being clean. Bidirectional overrides (U+202A–U+202E) are a Trojan Source vector: they can make rendered text differ from its underlying bytes, so a reviewer and a parser see different documents.

**Quote style is deliberately not hygiene.** `normalize_text` preserves typographic quotes and en/em dashes, because a PDF renders them correctly and `Bachelor’s` appears on nearly every CV. Converting to ASCII is a *destination* decision, so it lives in the separate `to_ascii_punctuation`, called only by `FIELD_MAPPED` portal exports and funder templates with a narrow charset. Note the consequence for the mojibake case: repairing `Bachelorâ€™s` yields a curly U+2019, and it stays curly.

- [ ] **Step 1: Create the package markers**

```bash
mkdir -p apps/documents tests/documents
touch apps/documents/__init__.py tests/documents/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/documents/test_hygiene.py`:

```python
import pytest

from apps.documents.hygiene import normalize_text


@pytest.mark.parametrize(
    ("label", "raw", "expected"),
    [
        ("zero_width_space", "Lead​ership", "Leadership"),
        ("soft_hyphen", "Uni­versity", "University"),
        ("bidi_override", "safe‮txt", "safetxt"),
        ("non_breaking_space", "5 years", "5 years"),
        ("non_breaking_hyphen", "TU‑Delft", "TU-Delft"),
        ("mojibake_apostrophe", "Bachelorâ€™s", "Bachelor’s"),
        ("mojibake_accent", "UniversitÃ© Paris", "Université Paris"),
        ("control_character", "Team\x07 lead", "Team lead"),
    ],
)
def test_normalize_text_cleans(label: str, raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    "text",
    ["Łódź", "Aygün", "Češka", "2020–2024", "Café", "Bachelor’s degree", "“Summa”"],
)
def test_normalize_text_preserves_meaningful_characters(text: str) -> None:
    """Diacritics, non-Latin letters, en dashes and typographic quotes are content."""
    assert normalize_text(text) == text


def test_normalize_text_collapses_blank_lines_and_trims() -> None:
    assert normalize_text("Header   \n\n\n\nBody\n") == "Header\n\nBody"


def test_normalize_text_handles_empty() -> None:
    assert normalize_text("") == ""
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/documents/test_hygiene.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'apps.documents.hygiene'`.

- [ ] **Step 4: Write the implementation**

Create `apps/documents/hygiene.py`:

```python
"""Release-time document hygiene.

Implements ``phased requirements.md`` 4.2.3: strip toolchain metadata from
generated files and normalise text before rendering. Hygiene only -- nothing
here removes or obscures signals that a document was produced with AI
assistance, which 4.2 and 4.2.2 continue to prohibit.
"""

import re
import unicodedata

# Invisible characters that survive copy-paste and corrupt downstream text
# extraction, plus the bidirectional overrides that let rendered text differ
# from its underlying bytes (Trojan Source).
_STRIP_CHARS = dict.fromkeys(
    [
        0x00AD,  # soft hyphen
        0x200B,  # zero-width space
        0x200C,  # zero-width non-joiner
        0x200D,  # zero-width joiner
        0x2060,  # word joiner
        0xFEFF,  # zero-width no-break space / BOM
        0x200E,  # left-to-right mark
        0x200F,  # right-to-left mark
        0x202A,  # left-to-right embedding
        0x202B,  # right-to-left embedding
        0x202C,  # pop directional formatting
        0x202D,  # left-to-right override
        0x202E,  # right-to-left override
        0x2066,  # left-to-right isolate
        0x2067,  # right-to-left isolate
        0x2068,  # first strong isolate
        0x2069,  # pop directional isolate
    ]
)

# Characters that break line-wrapping or text extraction. Quote style is NOT
# handled here -- it is a rendering choice, see to_ascii_punctuation().
_REPLACE_CHARS = {
    0x00A0: " ",  # non-breaking space
    0x2011: "-",  # non-breaking hyphen
    0x2012: "-",  # figure dash
    0x2028: "\n",  # line separator
    0x2029: "\n",  # paragraph separator
}

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_MOJIBAKE_MARKERS = ("Ã", "â€", "Â")


def _repair_mojibake(text: str) -> str:
    """Repair UTF-8 bytes that were decoded as cp1252 (``Bachelorâ€™s``).

    Returns the input unchanged unless the repair round-trips cleanly, so
    correctly encoded text is never corrupted.
    """
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text
    return repaired if "�" not in repaired else text


def normalize_text(text: str) -> str:
    """Return ``text`` with invisible, control and mangled characters removed.

    Letters and diacritics are never touched: applicant and institution names
    in any script survive unchanged.
    """
    if not text:
        return text
    text = _repair_mojibake(text)
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_STRIP_CHARS).translate(_REPLACE_CHARS)
    text = _CONTROL_CHARS.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/documents/test_hygiene.py -v`

Expected: PASS — 17 passed (8 parametrised cleaning cases, 7 preservation cases, 1 blank-line case, 1 empty case).

- [ ] **Step 6: Write the failing test for `to_ascii_punctuation`**

Append to `tests/documents/test_hygiene.py`:

```python
from apps.documents.hygiene import to_ascii_punctuation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bachelor’s", "Bachelor's"),
        ("“Summa”", '"Summa"'),
        ("2020–2024", "2020-2024"),
        ("", ""),
    ],
)
def test_to_ascii_punctuation_folds_typography(raw: str, expected: str) -> None:
    assert to_ascii_punctuation(raw) == expected


def test_to_ascii_punctuation_preserves_letters() -> None:
    """Only punctuation folds. Names must never be transliterated."""
    assert to_ascii_punctuation("Aygün Łódź") == "Aygün Łódź"
```

- [ ] **Step 7: Run it to verify it fails**

Run: `uv run pytest tests/documents/test_hygiene.py -k ascii -v`

Expected: `ImportError: cannot import name 'to_ascii_punctuation'`.

- [ ] **Step 8: Implement `to_ascii_punctuation`**

Append to `apps/documents/hygiene.py`:

```python
# Typographic punctuation folded to ASCII for destinations with a narrow
# charset -- portal form fields that mangle non-ASCII. Letters are never
# touched: folding a name would corrupt it.
_ASCII_PUNCTUATION = {
    0x2018: "'",
    0x2019: "'",
    0x201A: "'",
    0x201B: "'",
    0x201C: '"',
    0x201D: '"',
    0x201E: '"',
    0x2032: "'",  # prime
    0x2033: '"',  # double prime
    0x2013: "-",  # en dash
    0x2014: "-",  # em dash
}


def to_ascii_punctuation(text: str) -> str:
    """Fold typographic punctuation to ASCII for narrow-charset destinations.

    Call this only for ``FIELD_MAPPED`` portal exports and funder templates
    that need it -- PDF variants keep typographic punctuation. Letters and
    diacritics are never altered.
    """
    if not text:
        return text
    return text.translate(_ASCII_PUNCTUATION)
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/documents/test_hygiene.py -v`

Expected: PASS — 22 tests (17 from step 5, plus 4 ASCII-folding cases and 1 letter-preservation case).

- [ ] **Step 10: Lint and type-check**

```bash
uv run ruff format apps/documents tests/documents
uv run ruff check apps/documents tests/documents
uv run mypy apps/documents
```

Expected: all clean.

- [ ] **Step 11: Commit**

```bash
export PATH="$PWD/.venv/bin:$PATH"
# Stage only this task's files, then commit ONLY those paths. The repo index
# holds ~35 files staged by other work -- a bare `git commit` would sweep them in.
git add apps/documents tests/documents
git commit -m "feat(documents): text hygiene and ASCII punctuation folding

normalize_text strips zero-width, soft-hyphen, control and bidi-override
characters and repairs cp1252/UTF-8 mojibake. It preserves typographic quotes
and dashes, because quote style is a destination decision rather than hygiene:
to_ascii_punctuation handles that separately for narrow-charset portal fields.
Letters and diacritics are never altered. Part of phased requirements 4.2.3." -- apps/documents tests/documents
```

---

### Task 2: PDF metadata scrubbing

**Files:**
- Modify: `pyproject.toml` (add `pypdf` to `[project] dependencies`, alphabetical: after `psycopg`, before `pydantic`)
- Modify: `apps/documents/hygiene.py` (append)
- Modify: `tests/documents/test_hygiene.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `scrub_pdf_metadata(data: bytes) -> bytes` — takes PDF bytes, returns PDF bytes with the document information dictionary and XMP packet removed. Page content is untouched.

**Why a library:** PDF is a cross-referenced binary container; editing the trailer by hand invalidates the xref table. `pypdf` is pure Python (no compiled extension, no system libraries), BSD-3-Clause, and is the standard tool for this. Verified working at 6.16.1.

- [ ] **Step 1: Add the dependency**

```bash
uv add 'pypdf>=6.16,<7'
```

Verify `pyproject.toml`'s `[project] dependencies` now contains `"pypdf>=6.16,<7"` and that `uv.lock` was updated.

- [ ] **Step 2: Write the failing test**

Append to `tests/documents/test_hygiene.py`:

```python
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from apps.documents.hygiene import scrub_pdf_metadata


def _pdf_with_metadata() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata(
        {"/Producer": "SecretLib 9.2", "/Creator": "tehsil-agent", "/Author": "Orkhan"}
    )
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_scrub_pdf_metadata_removes_document_info() -> None:
    scrubbed = scrub_pdf_metadata(_pdf_with_metadata())
    reader = PdfReader(BytesIO(scrubbed))
    assert not reader.metadata


def test_scrub_pdf_metadata_removes_xmp() -> None:
    scrubbed = scrub_pdf_metadata(_pdf_with_metadata())
    assert PdfReader(BytesIO(scrubbed)).xmp_metadata is None


def test_scrub_pdf_metadata_preserves_pages() -> None:
    scrubbed = scrub_pdf_metadata(_pdf_with_metadata())
    assert len(PdfReader(BytesIO(scrubbed)).pages) == 1


def test_scrub_pdf_metadata_rejects_non_pdf() -> None:
    with pytest.raises(ValueError, match="not a readable PDF"):
        scrub_pdf_metadata(b"this is not a pdf")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/documents/test_hygiene.py -k pdf -v`

Expected: `ImportError: cannot import name 'scrub_pdf_metadata'`.

- [ ] **Step 4: Write the implementation**

Append to `apps/documents/hygiene.py` (and add `from io import BytesIO` and `from pypdf import PdfReader, PdfWriter` to the imports at the top, keeping ruff's import ordering):

```python
def scrub_pdf_metadata(data: bytes) -> bytes:
    """Return ``data`` with its document info dictionary and XMP packet removed.

    Page content is untouched. Raises ``ValueError`` if the bytes are not a
    readable PDF -- failing loudly beats silently releasing an unscrubbed file.
    """
    try:
        writer = PdfWriter(clone_from=BytesIO(data))
    except Exception as exc:  # pypdf raises several unrelated types here
        raise ValueError("not a readable PDF") from exc

    writer.metadata = None
    root = writer.root_object
    if "/Metadata" in root:
        del root["/Metadata"]

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/documents/test_hygiene.py -v`

Expected: PASS — all Task 1 tests plus 4 new PDF tests.

- [ ] **Step 6: Confirm Bandit accepts the broad except**

Run: `uv run bandit -c pyproject.toml -r apps/documents`

Expected: no issues. `B110` (try/except/pass) does not apply because the handler raises. If Bandit flags anything, fix the code rather than adding a `# nosec` — per CLAUDE.md a finding is a real bug or a documented false positive, never something silenced.

- [ ] **Step 7: Lint, type-check and commit**

```bash
uv run ruff format apps/documents tests/documents
uv run ruff check apps/documents tests/documents
uv run mypy apps/documents
export PATH="$PWD/.venv/bin:$PATH"
# Stage only this task's files, then commit ONLY those paths. The repo index
# holds ~35 files staged by other work -- a bare `git commit` would sweep them in.
git add pyproject.toml uv.lock apps/documents tests/documents
git commit -m "feat(documents): strip PDF document info and XMP metadata

Removes Producer, Creator, Author and the XMP packet from generated PDFs so a
tenant's white-label identity does not leak the toolchain. Page content is
untouched and unreadable input raises rather than passing through unscrubbed.
Adds pypdf (pure Python, BSD-3-Clause)." -- pyproject.toml uv.lock apps/documents tests/documents
```

---

### Task 3: DOCX metadata scrubbing

**Files:**
- Modify: `apps/documents/hygiene.py` (append)
- Modify: `tests/documents/test_hygiene.py` (append)

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: `scrub_docx_metadata(data: bytes) -> bytes` — takes DOCX bytes, returns DOCX bytes whose `docProps` parts are emptied.

**Why replace rather than delete:** `_rels/.rels` holds relationships pointing at `docProps/core.xml`, `docProps/app.xml` and `docProps/custom.xml`. Deleting those parts leaves dangling relationships and an arguably invalid OOXML package that Word may refuse or repair. Replacing each part with a well-formed empty element keeps the package structurally intact while removing every identifying value. Verified against the real Swedish Institute funder template, which carries all three parts.

No new dependency: `zipfile` is stdlib, and the replacement parts are fixed byte constants, so nothing is parsed. (`defusedxml` is already a project dependency for cases that do need XML parsing — this one does not.)

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_hygiene.py`:

```python
import zipfile

from apps.documents.hygiene import scrub_docx_metadata


def _docx_with_metadata() -> bytes:
    """Minimal OOXML package carrying identifying document properties."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
        archive.writestr("word/document.xml", "<w:document>CURRICULUM VITAE</w:document>")
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:creator>Orkhan</dc:creator></cp:coreProperties>",
        )
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0"?><Properties '
            'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Application>SecretWriter</Application></Properties>",
        )
    return buffer.getvalue()


def test_scrub_docx_metadata_removes_identifying_values() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_metadata())
    with zipfile.ZipFile(BytesIO(scrubbed)) as archive:
        assert b"Orkhan" not in archive.read("docProps/core.xml")
        assert b"SecretWriter" not in archive.read("docProps/app.xml")


def test_scrub_docx_metadata_keeps_every_part() -> None:
    original = _docx_with_metadata()
    scrubbed = scrub_docx_metadata(original)
    with zipfile.ZipFile(BytesIO(original)) as before, zipfile.ZipFile(BytesIO(scrubbed)) as after:
        assert sorted(after.namelist()) == sorted(before.namelist())


def test_scrub_docx_metadata_preserves_document_body() -> None:
    scrubbed = scrub_docx_metadata(_docx_with_metadata())
    with zipfile.ZipFile(BytesIO(scrubbed)) as archive:
        assert b"CURRICULUM VITAE" in archive.read("word/document.xml")
        assert archive.testzip() is None


def test_scrub_docx_metadata_rejects_non_docx() -> None:
    with pytest.raises(ValueError, match="not a readable DOCX"):
        scrub_docx_metadata(b"this is not a docx")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/documents/test_hygiene.py -k docx -v`

Expected: `ImportError: cannot import name 'scrub_docx_metadata'`.

- [ ] **Step 3: Write the implementation**

Append to `apps/documents/hygiene.py` (add `import zipfile` to the imports):

```python
# Well-formed but empty replacements. The parts must survive because
# _rels/.rels holds relationships pointing at them; deleting them would leave
# dangling references and an invalid package.
_EMPTY_DOCPROPS = {
    "docProps/core.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<cp:coreProperties"
        b' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        b' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        b' xmlns:dcterms="http://purl.org/dc/terms/"'
        b' xmlns:dcmitype="http://purl.org/dc/dcmitype/"'
        b' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>'
    ),
    "docProps/app.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<Properties"
        b' xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
        b' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>'
    ),
    "docProps/custom.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<Properties"
        b' xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"'
        b' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>'
    ),
}


def scrub_docx_metadata(data: bytes) -> bytes:
    """Return ``data`` with every ``docProps`` part replaced by an empty one.

    Every part and relationship is preserved so the OOXML package stays valid;
    only the identifying values are removed. Raises ``ValueError`` if the bytes
    are not a readable DOCX.
    """
    try:
        source = zipfile.ZipFile(BytesIO(data))
        if source.testzip() is not None:
            raise ValueError("not a readable DOCX")
    except zipfile.BadZipFile as exc:
        raise ValueError("not a readable DOCX") from exc

    out = BytesIO()
    with source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            replacement = _EMPTY_DOCPROPS.get(item.filename)
            target.writestr(
                item.filename,
                replacement if replacement is not None else source.read(item.filename),
            )
    return out.getvalue()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/documents/test_hygiene.py -v`

Expected: PASS — all tests from Tasks 1–3.

- [ ] **Step 5: Run the whole suite for regressions**

Run: `uv run pytest -q`

Expected: no new failures. Nothing imports `apps.documents` yet, so this task cannot break existing behaviour; the run confirms it.

- [ ] **Step 6: Lint, type-check, scan and commit**

```bash
uv run ruff format apps/documents tests/documents
uv run ruff check apps/documents tests/documents
uv run mypy apps/documents
uv run bandit -c pyproject.toml -r apps/documents
export PATH="$PWD/.venv/bin:$PATH"
# Stage only this task's files, then commit ONLY those paths. The repo index
# holds ~35 files staged by other work -- a bare `git commit` would sweep them in.
git add apps/documents tests/documents
git commit -m "feat(documents): empty DOCX document properties on release

Replaces docProps/core.xml, app.xml and custom.xml with well-formed empty
parts rather than deleting them, so relationships in _rels/.rels stay valid
and the package still opens. Verified against a real funder template carrying
all three parts. Completes phased requirements 4.2.3." -- apps/documents tests/documents
```

---

## Self-review notes

**Spec coverage.** §4.2.3 asks for three things. Metadata stripping from generated PDF and DOCX — Tasks 2 and 3. Text normalisation covering zero-width/control characters, quote and dash normalisation, and encoding-artifact repair — Task 1. Treating both as requirements rather than optional post-processing — expressed as the render layer calling them, which lands with the renderer task in a later plan.

**Deliberately out of scope.** No call site: the render layer does not exist and the PDF library choice is still an open decision in the spec. These three functions are the stable part regardless of which renderer wins, because they operate on output bytes rather than on the rendering process. When the renderer lands, wiring is one call per format.

**Verification status.** Every code block was executed before being written here: `normalize_text` against 13 cases including mojibake repair and diacritic preservation, `scrub_pdf_metadata` against pypdf 6.16.1's public `root_object` API, and `scrub_docx_metadata` against the real Swedish Institute template, which carries all three `docProps` parts and whose `_rels/.rels` references every one of them.

**Punctuation — settled, and the decomposition changed because of it.** The first draft had `normalize_text` folding curly quotes to ASCII, with a note asking whether that should become a parameter. It should not: quote style is not a hygiene property at all, and a boolean flag would have preserved the confusion between two different jobs. `normalize_text` now does only the safety work — invisible, control and bidi characters, mojibake, NFC, line-wrap-breaking characters — and always runs everywhere with no options. `to_ascii_punctuation` is a separate function called only by destinations with a narrow charset. PDF variants therefore keep `Bachelor’s` with a proper apostrophe.

One consequence worth flagging to the implementer, because the test encodes it: repairing the mojibake `Bachelorâ€™s` produces a **curly** U+2019, and it stays curly. The mojibake test asserts `Bachelor’s`, not `Bachelor's`.
