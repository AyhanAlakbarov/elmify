# Onboarding From Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A student uploads a transcript (text PDF, scanned PDF or photo); we read it into courses with ECTS, four key numbers and a short list of highlights, prefill their academic record, and ask the new short question set — replacing the 22-question wizard.

**Architecture:** A transcript is an upload like a CV, routed by `DocumentVersion.kind`. The OCR is its own program (`ocr/read_pages.py`, its own uv project on Python 3.12, its own container image) running self-hosted PaddleOCR PP-StructureV3 — every page, text-layer PDFs included, straightened first and refused with a named reason when too coarse, too small or too blurred to read (spec T20). In production it is an AWS Lambda function the document worker invokes with the cleared upload's key, in subnets with no route to the internet; locally and in tests the same program runs as a child process; one seam in the app (`apps/documents/ocr.py`) chooses by a setting. Code drops every line and row that identifies the student, cuts the rest into candidates (table columns and rows, other lines, the numbers and dates on them), and the decision layer's `decisions.ask()` puts closed questions to Jev (`typesafe/jev-1.13` through OpenRouter); code copies the chosen cells verbatim, checks printed credit totals, scale ranges and mixed scripts, and stores the reading — record, highlights, key numbers — in `TranscriptReading`. No generative model reads a transcript (T19); nothing on this path calls OpenAI. The consultation wizard prefills `academic_history` from the latest reading, carries its highlights, and records the version the student accepted. `StudentProfileSnapshot` is at schema version 3.

**Tech Stack:** Django 5.2, pydantic 2, PaddleOCR 3.7.0 / PaddleX 3.7.2 / PaddlePaddle 3.2.2 on CPU (its own uv project, `ocr/`, CPython 3.12), OpenCV and pypdfium2 from that project, AWS Lambda from a container image (`public.ecr.aws/lambda/python:3.12`) invoked with boto3, the decision layer's `apps/research/decisions.py` (`typesafe-sdk`), CloudFormation, pytest against Postgres.

**Spec:** `docs/superpowers/specs/2026-09-25-tailored-programme-finding-design.md` — this plan is its §10 build step 2 (§3.1–3.2). Read §2 (decisions T1–T3, T17, T19, T20), §3, §7, §8 and §11 before starting, and the Jev contract in `docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md` §3 (literal reading, no arithmetic, one judgment per question, `inspect` paths). The OCR measurements behind every number in Task 2a are in the git-ignored `.superpowers/ocr-eval/` (`out/ppstructure/REPORT.md`, `out/paddle_deskew/REPORT.md`, `out/ppstructure/LICENCE.md`).

**Status on this branch (2026-09-26).** Tasks 1, 3, 4 and 5 are executed and were merged to master in PR #132; Task 2 was executed only as the reading's shape (`5e6781aa`), because the reader waited on the OCR choice. What remains, in this order: **2a → 2b → 2c → 3b → 3c → 3d → 6.** Tasks 3b and 3c are the executed Tasks 3 and 5 brought onto the new reading: 3b replaces `uncertain` with highlights and key numbers on the stored reading and in the prefill (Task 5's code), 3c wires the worker to the reader (the step Task 3 left out). Task 2b needs the decision layer's Task 1 merged first — see its prerequisite note.

**Not in this plan, on purpose** (spec §10 later steps): topic labels and the credit decision, reading passports and language certificates (identity and languages are asked for now), narrowing, and any template or UI — the presentation layer is chosen at build time (`CLAUDE.md`, "Frontend and design"). The summary screen's data (key numbers and highlights) is produced and stored here; the screen itself is not.

## Global Constraints

- Work in the worktree `/home/orkhan/Desktop/tailored-programmes` (branch `claude/tailored-programmes-design`). The shell's cwd resets to the main repo between calls: prefix every command with `cd /home/orkhan/Desktop/tailored-programmes &&` and use `git -C /home/orkhan/Desktop/tailored-programmes`.
- Test database: `POSTGRES_DB=tehsil_tailored` on every pytest run — never the shared `test_tehsil`.
- **Never run `ruff format`** — the gate is `ruff check` only.
- After every task: `uv run ruff check apps config tests scripts ocr`, `uv run mypy apps config`, `uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py`, `POSTGRES_DB=tehsil_tailored uv run pytest -q`, and `uv run python manage.py makemigrations --check --dry-run` all clean; after any change under `ocr/`, also `uv run --project ocr pytest ocr -q`.
- **No generative model reads a transcript, and nothing on this path calls OpenAI** (spec T19). Every Jev call goes through `apps.research.decisions.ask()` — the decision layer's one client; never a second Jev client, never an HTTP call built here. Every question lives in `apps/documents/transcript_questions.py`, never at a call site. Jev only chooses among candidates code found; code copies the chosen text verbatim and does every count and sum.
- **What Jev sees is minimised by code first** (owner, 2026-09-26: TypeSafe and OpenRouter now see transcript content). The state holds table cells and candidate lines only, and never a line or row carrying the student's name, a birth date or an ID-like number (Task 2b's `_minimised`, pinned by a test). A per-student `rate_limited()` bucket guards each reading — one OCR run and its Jev requests.
- **The OCR program parses untrusted files, and never beside the app's secrets in production.** It runs as its own Lambda function: a role that reads only GuardDuty-clean uploads, no secret, no route to the internet. Locally, as a child process, it is handed an environment with no secret. Either way it runs under a timeout, its answer is parsed through a pydantic model with `extra="forbid"`, and a crash or a timeout is `OcrUnavailable`, never an empty transcript.
- **The OCR program never enters `AppImage`.** It is built from `ocr/Dockerfile` with `ocr/` as the context; the root `Dockerfile` and the web and worker tasks' sizes do not change.
- **`ocr/` is its own uv project** (CPython 3.12 — paddlepaddle publishes no 3.14 wheel). Change its dependencies with `uv add --project ocr`; never hand-edit `ocr/uv.lock`, never `pip install` into its venv.
- A new tenant-scoped table gets `ENABLE` + `FORCE ROW LEVEL SECURITY`, the `tenant_isolation` policy and a composite `(tenant_id, student_id)` FK in a `RunSQL` migration (pattern: `apps/documents/migrations/0017_narrative_input_tenant_guards.py`), and an entry in `apps/audit/redaction.py`'s `REDACT` and `KEEP`. A new field on one gets its `REDACT` entry in the same change.
- **Migration numbers.** On this branch `documents` ends at `0021`; master already has `0022_draft_rendered_filename`. Before writing Task 3b's migration run `ls apps/documents/migrations/`, take the next free number and depend on the real leaf — `makemigrations --check` is what catches a dependency on a node that does not exist.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

The five failure modes most likely to ship unnoticed, and the test that now owns each. A reviewer checks these first.

1. **A transcript that prints no totals looks clean.** Nothing can be checked, and a silent pass reads as "verified". Owned by Task 2c, `test_a_transcript_printing_no_total_says_not_checked_never_clean`.
2. **Two semesters printed side by side** are cut as one row carrying two courses, or split on the wrong column (NKU prints ECTS and local credits side by side). Owned by Task 2b, `test_two_semesters_printed_side_by_side_are_read_one_after_the_other` and `test_a_second_credits_column_does_not_split_the_table`.
3. **A phone photo with a thumb or a shadow along one edge** chooses the straightening angle instead of the text lines (Otsu did exactly this to the Azerbaijani photo). Owned by Task 2a, `test_a_shadow_along_one_edge_does_not_choose_the_angle`.
4. **Two courses merged into one row** carrying one set of credits — BEUN's measured failure — pass as one course. Owned by Task 2c, `test_two_courses_merged_into_one_row_fail_the_total`.
5. **A Cyrillic transcript read by the Latin models.** PP-OCRv6_medium_rec has no Cyrillic letter among its 18,708 characters, so its output can never look Cyrillic and cannot be what routes the page. Owned by Task 2a, `test_a_cyrillic_page_is_read_by_the_cyrillic_pipeline`.

Two more, found while writing this plan and pinned too: the student's name reaching Jev from an unlabelled page header in Cyrillic (Task 2b, `test_a_name_the_document_labels_once_is_dropped_everywhere`), and Paddle's C++ side printing into the child's stdout, which corrupted the JSON on every real run (Task 2a's `main()`; caught by `test_the_real_engine_reads_a_rendered_line`, which runs the real child).

---

### Task 1: Credits to ECTS

> **Executed** — `974f135c`. Unchanged by the OCR rewrite; kept as the record, do not re-execute.

**Files:**
- Create: `apps/documents/credits.py`
- Test: `tests/documents/test_credits.py`

**Interfaces:**
- Produces: `CreditUnit = Literal["ECTS", "US_SEMESTER_HOUR", "LOCAL", "UNKNOWN"]`; `to_ects(credits: Decimal, unit: CreditUnit, *, local_credits_per_year: Decimal | None = None) -> Decimal | None`.

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal

from apps.documents.credits import to_ects


def test_ects_is_unchanged():
    assert to_ects(Decimal("6"), "ECTS") == Decimal("6.00")


def test_a_us_semester_hour_is_two_ects():
    # A full-time US year is 30 semester hours; a full-time ECTS year is 60.
    assert to_ects(Decimal("3"), "US_SEMESTER_HOUR") == Decimal("6.00")


def test_a_local_credit_scales_by_the_full_year_load():
    assert to_ects(Decimal("5"), "LOCAL", local_credits_per_year=Decimal("40")) == Decimal("7.50")


def test_a_local_credit_without_a_year_load_is_unknown_not_guessed():
    assert to_ects(Decimal("5"), "LOCAL") is None


def test_an_unknown_unit_is_unknown():
    assert to_ects(Decimal("5"), "UNKNOWN", local_credits_per_year=Decimal("60")) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_credits.py -q`
Expected: FAIL — `ModuleNotFoundError: apps.documents.credits`

- [ ] **Step 3: Implement**

```python
"""Credits on a transcript, converted to ECTS.

A full-time year is 60 ECTS (ECTS Users' Guide). Any other system converts by
its own full-time year: 30 US semester hours, or whatever a local system's
year holds. No year load means no conversion -- an unknown figure is reported
as unknown, never guessed, because a guessed credit total decides whether a
programme's "20 ECTS of computing" gate passes.

# ponytail: two named systems plus a per-transcript year load; the spec's
# section 4.4 research adds named systems (AZ, TR local credits) as rows here.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

CreditUnit = Literal["ECTS", "US_SEMESTER_HOUR", "LOCAL", "UNKNOWN"]

_ECTS_PER_YEAR = Decimal("60")
_YEAR_LOAD: dict[str, Decimal] = {"ECTS": Decimal("60"), "US_SEMESTER_HOUR": Decimal("30")}
_CENT = Decimal("0.01")


def to_ects(
    credits: Decimal, unit: CreditUnit, *, local_credits_per_year: Decimal | None = None
) -> Decimal | None:
    if unit == "LOCAL":
        year_load = local_credits_per_year
    else:
        year_load = _YEAR_LOAD.get(unit)
    if year_load is None or year_load <= 0:
        return None
    return (credits * _ECTS_PER_YEAR / year_load).quantize(_CENT, rounding=ROUND_HALF_UP)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_credits.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tailored-programmes add apps/documents/credits.py tests/documents/test_credits.py
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(documents): credits convert to ECTS by the full-time year, or not at all

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Reading a transcript — split into 2a, 2b, 2c

Task 2 as first written sent the text layer or the scan itself to an OpenAI model. That is superseded by spec T19/T20 (owner, 2026-09-25/26): no generative model reads a transcript; self-hosted OCR reads it, code cuts, Jev picks, code copies. Its shape part was executed as `5e6781aa` (`apps/documents/transcript.py`: `TranscriptCourse`, `TranscriptContent`, `academic_record`, `uncertain_fields`); Task 2b rewrites that module. The reader is three reviewable units:

- **2a** — the OCR program and its own image: pages in, lines and table grids out; the upload gate; straightening; script routing; the two ways it is run (an AWS Lambda function in production, a child process locally) behind one seam.
- **2b** — the reader: minimised candidates, Jev's questions, verbatim copies.
- **2c** — the checks, the key numbers and the highlights.

---

### Task 2a: The OCR program — its own image, run on demand, one seam in the app

**Why its own program.** paddlepaddle publishes CPython wheels up to 3.13 only (PyPI and `paddlepaddle.org.cn`, versions 3.2.2 through 3.4.0, checked 2026-09-26), and this app is pinned to 3.14 by five declarations and a test (`CLAUDE.md`, "Python version"). So OCR is its own uv project, `ocr/`, on CPython 3.12 — the interpreter every measurement ran on.

**Why on demand, in its own image** (owner, 2026-09-26). OCR runs a few minutes per upload; an always-on worker sized for the models (4 vCPU / 10 GB, ~$150 a month on Fargate) would sit idle nearly all the time. So in production the program is an **AWS Lambda function from a container image** built by `ocr/Dockerfile` — never added to the shared `AppImage`, which the web and worker tasks keep at their current size. The document worker invokes it synchronously with the key of the GuardDuty-cleared object (a synchronous invocation carries at most 6 MB and an upload may be 10 MB — AWS, "Lambda quotas", *Invocation payload*), and the function reads the object itself. Locally and in tests the same file runs as a child process of the app. One function in the app, `apps.documents.ocr.read_pages(document, content)`, hides which: `settings.OCR_FUNCTION_NAME` set → invoke; empty → child process.

**Every transcript goes through OCR, text-layer PDFs included** (owner, 2026-09-26): pypdf yields no table structure, and one path is one path to test. PDF pages are rendered at 200 dpi with `pypdfium2`, which the OCR program already carries (PaddleX's `ocr-core` extra depends on it) — no new dependency.

**What Lambda imposes, from AWS's own documentation, and how this task meets it:**
- Memory 128–10,240 MB, and "at 1,769 MB, a function has the equivalent of one vCPU"; timeout at most 900 s; container image at most 10 GB uncompressed including all layers (AWS, "Lambda quotas"). The image measures 3.7 GB of layers (5.2 GB as `docker images` reports it) — inside the limit.
- "The container image must be able to run on a read-only file system. Your function code can access a writable `/tmp` directory"; "the default Lambda user must be able to read all the files required" (AWS, "Create a Lambda function using a container image"). The models are baked into `/opt/ocr/paddlex` and made world-readable, `HOME=/tmp`, and CI runs the image with `--read-only --tmpfs /tmp --user 993:990 --network=none` to prove it (measured locally: reads, ~12 s).
- "The `Init` phase is limited to 10 seconds" (AWS, "Understanding the Lambda execution environment lifecycle"). The models are therefore loaded on the first invocation, inside the handler, not at import; measured through the Lambda runtime emulator, Init took 0.2 s.

**Files:**
- Create: `ocr/pyproject.toml`, `ocr/uv.lock` (generated by `uv add`), `ocr/read_pages.py`, `ocr/test_read_pages.py`, `ocr/Dockerfile`, `ocr/.dockerignore`
- Create: `apps/documents/ocr.py`, `tests/documents/test_ocr.py`
- Modify: `config/settings/base.py` (after `DOCUMENT_SCAN_QUEUE_URL`)
- Modify: `tests/test_bootstrap.py` (the OCR image's Python agrees with its lock)
- Modify: `.dockerignore` (`**/.venv`, so a developer's `ocr/.venv` never enters the app image's context)
- Modify: `.github/workflows/ci.yml` (`test` job: bandit scope, the OCR graph's audit, the OCR tests; a new `ocr-image` job)
- Not modified: the root `Dockerfile`. The app image does not grow.

**Interfaces:**
- Consumes: nothing from the app. The program imports only its own dependencies (and, in Lambda, the base image's boto3).
- Produces:
  - The program's answer, the same from both entry points: `{"pages": [{"script": "latin" | "cyrillic", "skew": float, "lines": [str, ...], "tables": [[[str, ...], ...], ...]}, ...]}` or `{"refused": {"reason": str, "page": int}}`. Entry points: `python ocr/read_pages.py < upload` (stdout), `read_pages.handler({"key": "<quarantine key>"}, context)` (Lambda; the bucket is the function's `DOCUMENT_BUCKET`, never the event's), `--bake` (loads every model, reads a synthetic line).
  - `apps.documents.ocr`: `OcrPage` (pydantic, `extra="forbid"`: `script: Literal["latin", "cyrillic"]`, `skew: float`, `lines: tuple[str, ...]`, `tables: tuple[tuple[tuple[str, ...], ...], ...]`); `read_pages(document: DocumentVersion, content: bytes) -> tuple[OcrPage, ...]`; `PageRefused(RuntimeError)` with `.reason: str` (one of `low_resolution`, `blurred`, `text_too_small`, `no_text`, `unreadable`, `too_many_pages`, `page_too_large`) and `.page: int` (1-based); `OcrUnavailable(RuntimeError)`.
  - Settings: `OCR_FUNCTION_NAME` (default empty), `OCR_PYTHON` (default `ocr/.venv/bin/python` under `BASE_DIR`), `OCR_MODEL_HOME` (default `~/.paddlex`).

- [ ] **Step 1: Confirm the constraint this task is shaped by**

Run: `cd /home/orkhan/Desktop/tailored-programmes && echo 'paddlepaddle==3.2.2' | uv pip compile --python-version 3.14 - 2>&1 | head -4`
Expected: `No solution found ... paddlepaddle==3.2.2 has no wheels with a matching Python ABI tag (e.g., cp314)`. If this now resolves, stop and ask the owner whether OCR should become an ordinary dependency.

- [ ] **Step 2: Create the OCR project with `uv add`**

Write `ocr/pyproject.toml` with no dependencies yet:

```toml
[project]
name = "tehsil-ocr"
version = "0"
description = "Transcript OCR, run as a child process of the document worker (apps/documents/ocr.py)"
# paddlepaddle publishes CPython wheels up to 3.13 and the app runs 3.14, so OCR has its own
# interpreter: 3.12, the one every measurement in .superpowers/ocr-eval ran on.
requires-python = "==3.12.*"
dependencies = []

[tool.uv]
package = false

[tool.pytest.ini_options]
python_files = ["test_*.py"]
```

Then add the measured versions — `uv add` writes `ocr/uv.lock`; never edit it by hand:

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv add --project ocr 'paddleocr==3.7.0' 'paddlepaddle==3.2.2' 'paddlex[ocr]==3.7.2' && uv add --project ocr --dev 'pytest>=9.0.3,<10' && ocr/.venv/bin/python --version
```

Expected: `ocr/pyproject.toml` gains the three pins and a `dev` group, `ocr/uv.lock` exists (about 1,600 lines), and the last line prints `Python 3.12.x`. `paddlex[ocr]` is the extra PP-StructureV3 needs; it pins `opencv-contrib-python==4.10.0.84` and brings `pypdfium2`.

- [ ] **Step 3: Audit the new graph**

The main `pip-audit` does not see this project. Audit its exact pins without installing them under 3.14:

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv export --project ocr --frozen --no-hashes --no-dev -o /tmp/ocr-requirements.txt && uv run pip-audit -r /tmp/ocr-requirements.txt --no-deps --disable-pip
```

Expected: `No known vulnerabilities found` (the result on 2026-09-26 for this exact graph). A finding is a real bug: bump the pin with `uv add --project ocr`, or record a `--ignore-vuln` with its reason in `ci.yml` the way the WeasyPrint advisories are recorded. Licences are recorded in `.superpowers/ocr-eval/out/ppstructure/LICENCE.md`: the library and all twelve loaded weights are Apache-2.0.

- [ ] **Step 4: Write the program's failing tests**

Create `ocr/test_read_pages.py`. `_Engines` stands in for the models and `_S3` for boto3's client, so the gate, the routing and the Lambda handler are tested without either.

```python
"""The OCR program's own logic, without the models: decoding, the gate, straightening, the grid,
the Lambda handler.

Runs in the OCR venv (`uv run --project ocr pytest ocr`). The app's own suite collects this file
too and skips it, because cv2 exists only in the OCR venv.
"""

import io

import pytest

cv2 = pytest.importorskip("cv2")

import numpy as np  # noqa: E402
import pypdfium2  # noqa: E402
import read_pages as rp  # noqa: E402
from PIL import Image  # noqa: E402


def _page(lines=("Organic Chemistry I 6 91", "Physical Chemistry II 5 80"), size=(1654, 2339)):
    page = np.full((size[1], size[0], 3), 255, np.uint8)
    for row, text in enumerate(lines):
        cv2.putText(page, text, (120, 300 + 90 * row), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    return page


def _pdf(pages=1, size=(595, 842)):
    pdf = pypdfium2.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(*size)
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


def _scanned_pdf(ppi):
    """One A4 page holding one image at `ppi` -- what a scanner writes."""
    buffer = io.BytesIO()
    width, height = int(8.27 * ppi), int(11.69 * ppi)
    Image.new("RGB", (width, height), "white").save(buffer, format="PDF", resolution=ppi)
    return buffer.getvalue()


def test_a_total_label_over_two_columns_keeps_the_credits_in_their_column():
    rows = rp.grid(
        "<table><tr><td>CHEM101</td><td>Organic Chemistry I</td><td>6</td></tr>"
        "<tr><td colspan='2'>Total</td><td>6</td></tr></table>"
    )
    assert rows == [["CHEM101", "Organic Chemistry I", "6"], ["Total", "", "6"]]


def test_a_semester_printed_once_beside_its_courses_reaches_each_row():
    rows = rp.grid(
        "<table><tr><td rowspan='2'>1</td><td>Organic Chemistry I</td><td>6</td></tr>"
        "<tr><td>Physics I</td><td>5</td></tr></table>"
    )
    assert rows == [["1", "Organic Chemistry I", "6"], ["1", "Physics I", "5"]]


def test_a_runaway_span_is_capped():
    rows = rp.grid("<table><tr><td rowspan='999999' colspan='x'>a</td></tr></table>")
    assert rows == [["a"]]


def test_a_straightened_page_is_level_again():
    page = _page()
    for tilt in (1.2, -0.7):
        assert abs(rp.skew_angle(rp._rotate(page, tilt)) + tilt) <= 0.1


def test_a_shadow_along_one_edge_does_not_choose_the_angle():
    """A phone photo's thumb or table edge: a dark band the sheet's lines do not share."""
    page = rp._rotate(_page(), 1.0)
    page[:, : page.shape[1] // 5] = 40
    assert abs(rp.skew_angle(page) + 1.0) <= 0.1


def test_a_russian_line_reads_as_cyrillic_and_an_azerbaijani_one_does_not():
    assert rp.cyrillic_share(["Русский язык и культура речи"]) == 1.0
    assert rp.cyrillic_share(["Azərbaycan tarixi", "Ali riyaziyyat I"]) == 0.0
    assert rp.cyrillic_share([]) == 0.0


def test_a_low_resolution_scan_is_refused_before_any_model_runs():
    [(image, ppi)] = rp.decode(_scanned_pdf(120))
    assert ppi == pytest.approx(120, abs=1)
    with pytest.raises(rp.Refused) as refusal:
        rp.read_page(None, image, ppi, 1)  # no engines: the gate must refuse first
    assert (refusal.value.reason, refusal.value.page) == ("low_resolution", 1)


def test_a_scan_at_two_hundred_ppi_passes_the_resolution_floor():
    [(_, ppi)] = rp.decode(_scanned_pdf(200))
    assert ppi >= rp.MIN_SCAN_PPI


def test_a_born_digital_page_has_no_scan_resolution():
    [(image, ppi)] = rp.decode(_pdf())
    assert ppi is None
    assert image.shape[1] == round(595 * rp.RENDER_DPI / 72)


def test_more_pages_than_the_cap_are_refused_not_truncated():
    with pytest.raises(rp.Refused, match="too_many_pages"):
        rp.decode(_pdf(pages=rp.MAX_PAGES + 1))


def test_a_page_too_large_to_render_is_refused():
    with pytest.raises(rp.Refused, match="page_too_large"):
        rp.decode(_pdf(size=(20_000, 20_000)))


@pytest.mark.parametrize("data", [b"\x89PNG\r\n\x1a\nnot an image", b"%PDF-1.7 not a pdf"])
def test_bytes_that_do_not_decode_are_refused(data):
    with pytest.raises(rp.Refused, match="unreadable"):
        rp.decode(data)


def test_a_blurred_line_is_below_the_sharpness_floor_and_the_same_line_sharp_is_above():
    page = _page(lines=("Organic Chemistry I 6 91",))
    line = [np.array([[100, 250], [1000, 250], [1000, 320], [100, 320]])]
    assert rp.sharpness(page, line) >= rp.MIN_SHARPNESS
    assert rp.sharpness(cv2.GaussianBlur(page, (0, 0), 4), line) < rp.MIN_SHARPNESS


def test_a_nearly_empty_sharp_page_is_not_mistaken_for_a_blurred_one():
    """Page-wide variance falls with emptiness; the gate measures inside the lines only."""
    sparse = _page(lines=("Total 240",))
    line = [np.array([[100, 250], [420, 250], [420, 320], [100, 320]])]
    assert rp.sharpness(sparse, line) >= rp.MIN_SHARPNESS


class _Engines:
    """Stand-ins for the models: a detector finding one line, a probe reading `probe_text`."""

    def __init__(self, probe_text):
        line = np.array([[100, 250], [1000, 250], [1000, 320], [100, 320]])
        self.detect = type("D", (), {"predict": lambda _, image: [{"dt_polys": [line]}]})()
        self.probe = type("P", (), {"predict": lambda _, crops: [{"rec_text": probe_text}]})()
        self.asked = []
        result = {
            "overall_ocr_res": {"rec_texts": ["Organic Chemistry"], "rec_polys": [line]},
            "layout_det_res": {"boxes": []},
            "table_res_list": [{"pred_html": "<table><tr><td>6</td></tr></table>"}],
        }
        self._pipeline = type("S", (), {"predict": lambda _, image: [result]})()

    def pipeline(self, script):
        self.asked.append(script)
        return self._pipeline


def test_a_cyrillic_page_is_read_by_the_cyrillic_pipeline():
    """The Latin recogniser has no Cyrillic letter, so it can never be the one that notices a
    Russian page; the East-Slavic probe decides, before the page is read."""
    engines = _Engines("Русский язык и культура речи")
    page = rp.read_page(engines, _page(), None, 1)
    assert engines.asked == [rp.CYRILLIC] and page["script"] == rp.CYRILLIC


def test_a_latin_page_is_read_by_the_latin_pipeline():
    engines = _Engines("Azerbaycan tarixi")
    page = rp.read_page(engines, _page(), None, 1)
    assert engines.asked == [rp.LATIN]
    assert page["lines"] == ["Organic Chemistry"] and page["tables"] == [[["6"]]]


class _S3:
    def __init__(self, data):
        self.data, self.asked = data, []

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3's own argument names
        self.asked.append((Bucket, Key))
        return {"Body": io.BytesIO(self.data)}


def test_the_lambda_reads_the_named_key_from_its_own_bucket(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")
    monkeypatch.setattr(rp, "_ENGINES", _Engines("Azerbaycan tarixi"))
    _, png = cv2.imencode(".png", _page())
    s3 = _S3(png.tobytes())
    answer = rp.handler({"key": "quarantine/t/d", "bucket": "elsewhere"}, None, s3=s3)
    assert s3.asked == [("evidence", "quarantine/t/d")]  # the event cannot choose the bucket
    assert answer["pages"][0]["lines"] == ["Organic Chemistry"]


def test_the_lambda_refuses_an_object_over_the_size_cap(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")
    with pytest.raises(ValueError, match="larger"):
        rp.handler({"key": "quarantine/t/d"}, None, s3=_S3(b"\x00" * (rp.MAX_BYTES + 1)))


def test_the_lambda_loads_the_models_once_per_execution_environment(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "evidence")
    monkeypatch.setattr(rp, "_ENGINES", None)
    built = []
    monkeypatch.setattr(rp, "Engines", lambda: built.append(1) or _Engines("Azerbaycan"))
    _, png = cv2.imencode(".png", _page())
    for _ in range(2):
        rp.handler({"key": "quarantine/t/d"}, None, s3=_S3(png.tobytes()))
    assert built == [1]
```

- [ ] **Step 5: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/tailored-programmes && uv run --project ocr pytest ocr -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'read_pages'`

- [ ] **Step 6: Write the program**

Create `ocr/read_pages.py`. `skew_angle` and `_rotate` are copied from `.superpowers/ocr-eval/run_paddle_deskew.py` and the `PPStructureV3` arguments from `run_ppstructure.py` — the measured code, not a re-derivation. The gate's three floors and the page cap come from measurements taken for this plan on the same pages (2026-09-26), recorded in their comments.

```python
"""Transcript pages in, text lines and table grids out -- the OCR program, run on demand.

Two entry points, one reading. In production `handler` is an AWS Lambda function (ocr/Dockerfile):
the document worker invokes it with the key of a GuardDuty-cleared upload and it reads that object
itself, because a synchronous invocation carries at most 6 MB and an upload may be 10 MB. Locally
and in tests the same file runs as a child process of the app: the upload's bytes on stdin, the
answer on stdout. Either way the answer is one JSON object,
  {"pages": [{"script": "latin" | "cyrillic", "skew": 0.72,
              "lines": ["...", ...], "tables": [[["cell", ...], ...], ...]}, ...]}
or {"refused": {"reason": "...", "page": 3}} for a page the reader will not guess from. A crash
is OCR being unavailable (apps/documents/ocr.py), never an empty transcript.

Why a separate interpreter: paddlepaddle publishes CPython wheels up to 3.13 only (PyPI and
paddlepaddle.org.cn, 3.2.2 through 3.4.0, checked 2026-09-26) and the app runs 3.14. So this file
runs under the OCR venv's own Python 3.12 -- the interpreter every measurement in
.superpowers/ocr-eval ran on -- and imports nothing from the app.

The engine settings are the measured ones (spec 3.1, T20; .superpowers/ocr-eval/run_ppstructure.py):
PP-StructureV3 with seal, formula, chart, orientation and unwarping off and table recognition on;
PP-OCRv6 medium detection and recognition for Latin-script pages, PP-OCRv5 server detection and the
East-Slavic recogniser for Cyrillic. Each page is straightened first by the projection-profile
estimate that took a 1-degree scan from 57% to 96% of rows paired (run_paddle_deskew.py).

usage: python read_pages.py < upload  |  python read_pages.py --bake  |  Lambda: read_pages.handler
"""

from __future__ import annotations

import json
import os
import sys
from html.parser import HTMLParser

import cv2
import numpy as np
import pypdfium2
import pypdfium2.raw as pdfium_c

RENDER_DPI = 200
#: ponytail: at the function's 10,240 MB (6 vCPU) a page took 20-67 s, measured 2026-09-26 on
#: five sample pages at 6 cores; eight at the slowest is 536 s, inside the function's 720 s with
#: room for a cold start. A longer upload is refused, never truncated. Raise it with the timeout.
MAX_PAGES = 8
#: The same ceiling the app applies before invoking (apps/documents/transcript.py). Read one byte
#: past it, so a bigger object is an error here too and never a 10 GB read into memory.
MAX_BYTES = 10_000_000
#: A PDF page whose render would exceed this is refused before it is drawn: a 10 MB file can
#: declare a page two hundred inches wide. (Images are capped by OPENCV_IO_MAX_IMAGE_PIXELS,
#: which the caller sets to the same number.)
MAX_PIXELS = 50_000_000

# --- The upload gate (spec 3.1). ponytail: every floor below rests on few pages -- the 24 of
# .superpowers/ocr-eval -- and none on a real student's upload. Re-derive each from the uploads
# refused and then rescanned, once there are twenty of them.
#: A scanned PDF page's own resolution. Mersin's diploma supplement is a 127-129 ppi scan and
#: read 0% on every engine, at a 200-dpi and a 400-dpi render alike (rendering only enlarges
#: its pixels); every scan that read well is 200-400 ppi. 150 sits between.
MIN_SCAN_PPI = 150
#: Median height in pixels of the recognised lines (3+ characters) on the page as read. The
#: SPbU specimen's lines are 10 px (text ~6 px tall) and read 0% everywhere; the lowest page that
#: read well is 15 px (BEUN), photos 22-25 px. 12 sits between.
MIN_TEXT_PX = 12
#: Median over the detected text lines of the Laplacian variance of each line scaled to 32 px
#: tall (sharpness() below). The az scan blurred with a Gaussian of sigma 1.5 / 2 / 2.5 scored 195 /
#: 75 / 36 and kept 24 / 18 / 10 of its 27 course titles exact; the two phone photos, which read
#: well, score 241 and 311. 100 sits between the page that lost a third of its titles and the one
#: that lost three.
MIN_SHARPNESS = 100.0
CYRILLIC_ABOVE = 0.5

LATIN, CYRILLIC = "latin", "cyrillic"
MODELS = {
    LATIN: ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
    CYRILLIC: ("PP-OCRv5_server_det", "eslav_PP-OCRv5_mobile_rec"),
}


class Refused(Exception):
    def __init__(self, reason: str, page: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.page = page


def decode(data: bytes) -> list[tuple[np.ndarray, float | None]]:
    """Every page as a BGR image, with a scanned PDF page's own resolution (None otherwise)."""
    if data.startswith(b"%PDF"):
        try:
            pdf = pypdfium2.PdfDocument(data)
        except pypdfium2.PdfiumError:
            raise Refused("unreadable", 1) from None
        if len(pdf) > MAX_PAGES:
            raise Refused("too_many_pages", len(pdf))
        pages = []
        for number, page in enumerate(pdf, start=1):
            width, height = page.get_size()
            if width * height * (RENDER_DPI / 72) ** 2 > MAX_PIXELS:
                raise Refused("page_too_large", number)
            rgb = np.asarray(page.render(scale=RENDER_DPI / 72).to_pil().convert("RGB"))
            pages.append((cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), scan_ppi(page)))
        return pages
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise Refused("unreadable", 1)
    return [(image, None)]


def scan_ppi(page: pypdfium2.PdfPage) -> float | None:
    """The lowest resolution of any image covering half the page's width or more.

    Area-based, so an image placed rotated reads the same as one placed upright.
    """
    found = []
    for image in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3):
        left, bottom, right, top = image.get_bounds()
        if right - left < page.get_width() / 2:
            continue
        px_width, px_height = image.get_px_size()
        found.append(((px_width * px_height) / ((right - left) * (top - bottom) / 72**2)) ** 0.5)
    return min(found) if found else None


def _rotate(img: np.ndarray, angle: float, border: int = 255) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    c, s = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * s + w * c), int(h * c + w * s)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    bv = border if img.ndim == 2 else (border,) * 3
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderValue=bv)


def skew_angle(img: np.ndarray) -> float:
    """Copied from .superpowers/ocr-eval/run_paddle_deskew.py, the measured estimate."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    f = 1200 / max(g.shape)
    g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    # adaptive, not Otsu: on a phone photo Otsu marks the dark table/background around the sheet
    # as ink and the sheet's edges then pick the angle (it tilted the az photo the wrong way)
    b = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)

    def sharp(a: float) -> float:
        p = _rotate(b, a, border=0).sum(axis=1, dtype=np.float64)
        return float(np.sum(np.diff(p) ** 2))

    best = max(np.arange(-5, 5.001, 0.2), key=sharp)
    return round(float(max(np.arange(best - 0.2, best + 0.2001, 0.02), key=sharp)), 2)


def straighten(img: np.ndarray) -> tuple[np.ndarray, float]:
    angle = skew_angle(img)
    return (_rotate(img, angle) if abs(angle) >= 0.02 else img), angle


def _box(poly: np.ndarray) -> tuple[int, int, int, int]:
    x0, y0 = np.maximum(poly.min(axis=0), 0).astype(int)
    x1, y1 = poly.max(axis=0).astype(int)
    return int(x0), int(y0), int(x1), int(y1)


def sharpness(image: np.ndarray, polys: list[np.ndarray]) -> float:
    """How crisp the letters are, whatever share of the page they cover.

    A page-wide Laplacian variance also falls with emptiness, so a sharp page holding three lines
    would read as blurred; measuring inside the detected lines only does not.
    """
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    values = []
    for poly in polys:
        x0, y0, x1, y1 = _box(poly)
        if y1 - y0 < 4 or x1 - x0 < 4:
            continue
        crop = grey[y0:y1, x0:x1]
        scale = 32 / crop.shape[0]
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        values.append(cv2.Laplacian(crop, cv2.CV_64F).var())
    return float(np.median(values)) if values else 0.0


def cyrillic_share(texts: list[str]) -> float:
    cyrillic = sum(1 for text in texts for ch in text if "\u0400" <= ch <= "\u04ff")
    letters = sum(1 for text in texts for ch in text if ch.isalpha())
    return cyrillic / letters if letters else 0.0


class _Grid(HTMLParser):
    """One predicted HTML table as rows of cell text that line up with their columns.

    A cell spanning columns keeps its text in the first column and leaves the rest empty, so a
    "Total" label over two columns does not push the credits one column left; a cell spanning
    rows repeats downwards, so a semester number printed once beside its courses reaches each.
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._carried: dict[tuple[int, int], str] = {}
        self._cell: list[str] | None = None
        self._span = (1, 1)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.rows.append([])
            self._fill()
        elif tag in ("td", "th") and self.rows:
            given = dict(attrs)
            self._span = (_span(given.get("rowspan")), _span(given.get("colspan")))
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag not in ("td", "th") or self._cell is None:
            return
        text = " ".join("".join(self._cell).split())
        row_index, row = len(self.rows) - 1, self.rows[-1]
        rowspan, colspan = self._span
        start = len(row)
        row.extend([text] + [""] * (colspan - 1))
        for below in range(1, rowspan):
            for offset in range(colspan):
                self._carried[(row_index + below, start + offset)] = text if offset == 0 else ""
        self._cell = None
        self._fill()

    def _fill(self) -> None:
        row_index, row = len(self.rows) - 1, self.rows[-1]
        while (row_index, len(row)) in self._carried:
            row.append(self._carried.pop((row_index, len(row))))


def _span(value: str | None) -> int:
    # The HTML is the table model's prediction, not the upload's, but a span is still capped:
    # a runaway rowspan would otherwise grow the carried map without bound.
    return min(int(value), 200) if value and value.isdigit() and int(value) > 0 else 1


def grid(html: str) -> list[list[str]]:
    parser = _Grid()
    parser.feed(html)
    rows = [row for row in parser.rows if any(row)]
    width = max((len(row) for row in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows]


def _inside(box: tuple[int, int, int, int], regions: list[list[float]]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in regions)


class Engines:
    """The models, loaded on first use: most uploads never need the Cyrillic pipeline."""

    def __init__(self) -> None:
        from paddleocr import TextDetection, TextRecognition

        self.detect = TextDetection(model_name=MODELS[LATIN][0])
        self.probe = TextRecognition(model_name=MODELS[CYRILLIC][1])
        self._pipelines: dict[str, object] = {}

    def pipeline(self, script: str):  # paddleocr ships no types
        if script not in self._pipelines:
            from paddleocr import PPStructureV3

            det, rec = MODELS[script]
            self._pipelines[script] = PPStructureV3(
                text_detection_model_name=det,
                text_recognition_model_name=rec,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                use_seal_recognition=False,
                use_formula_recognition=False,
                use_chart_recognition=False,
                use_table_recognition=True,
            )
        return self._pipelines[script]


def script_of(engines: Engines, image: np.ndarray, polys: list[np.ndarray]) -> str:
    """Latin or Cyrillic, from the East-Slavic recogniser's reading of the 20 widest lines.

    The Latin recogniser cannot answer this: PP-OCRv6_medium_rec has no Cyrillic letter among its
    18,708 characters, so a Russian page read by it comes back as Latin lookalikes and never looks
    Cyrillic. Measured 2026-09-26: Russian pages 1.00 Cyrillic, Azerbaijani, Turkish and English
    0.00-0.12 (the top is HSE's English page with a Russian address line), ~1.5 s a page.
    """
    widest = sorted(polys, key=lambda poly: float(poly[:, 0].min() - poly[:, 0].max()))[:20]
    crops = []
    for poly in widest:
        x0, y0, x1, y1 = _box(poly)
        if x1 > x0 and y1 > y0:
            crops.append(image[y0:y1, x0:x1])
    texts = [result["rec_text"] for result in engines.probe.predict(crops)] if crops else []
    return CYRILLIC if cyrillic_share(texts) > CYRILLIC_ABOVE else LATIN


def read_page(engines: Engines, image: np.ndarray, ppi: float | None, number: int) -> dict | None:
    """One page through the gate and the engine. None for a page with no text on it."""
    if ppi is not None and ppi < MIN_SCAN_PPI:
        raise Refused("low_resolution", number)
    image, angle = straighten(image)
    polys = list(next(iter(engines.detect.predict(image)))["dt_polys"])
    if not polys:
        return None
    if sharpness(image, polys) < MIN_SHARPNESS:
        raise Refused("blurred", number)
    script = script_of(engines, image, polys)
    result = next(iter(engines.pipeline(script).predict(image)))
    ocr = result["overall_ocr_res"]
    boxes = [_box(np.asarray(poly)) for poly in ocr["rec_polys"]]
    heights = [y1 - y0 for (_, y0, _, y1), text in zip(boxes, ocr["rec_texts"]) if len(text) >= 3]
    if heights and float(np.median(heights)) < MIN_TEXT_PX:
        raise Refused("text_too_small", number)
    boxes_found = result["layout_det_res"]["boxes"]
    tables = [box["coordinate"] for box in boxes_found if box["label"] == "table"]
    return {
        "script": script,
        "skew": angle,
        "lines": [
            text
            for text, box in zip(ocr["rec_texts"], boxes)
            if text.strip() and not _inside(box, tables)
        ],
        "tables": [grid(table["pred_html"]) for table in result["table_res_list"]],
    }


def read_document(data: bytes, engines: Engines) -> dict:
    try:
        pages = [
            page
            for number, (image, ppi) in enumerate(decode(data), start=1)
            if (page := read_page(engines, image, ppi, number)) is not None
        ]
        if not pages:
            raise Refused("no_text", 1)
    except Refused as refusal:
        return {"refused": {"reason": refusal.reason, "page": refusal.page}}
    return {"pages": pages}


def bake() -> None:
    """Load every model, and read a synthetic line through the Latin pipeline.

    The Dockerfile runs this twice: once with the network, which downloads the weights into
    PADDLE_PDX_CACHE_HOME, and once with --network=none, which proves nothing is fetched at run
    time -- production egress never reaches a model host.
    """
    page = np.full((900, 1400, 3), 255, np.uint8)
    for row, text in enumerate(("Organic Chemistry I 6 91", "Physical Chemistry II 5 80")):
        cv2.putText(page, text, (60, 200 + 120 * row), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    engines = Engines()
    _, png = cv2.imencode(".png", page)
    output = read_document(png.tobytes(), engines)
    assert "pages" in output, output
    assert any("Chemistry" in line for line in output["pages"][0]["lines"]), output
    engines.pipeline(CYRILLIC).predict(page)
    print("baked", sorted(MODELS[LATIN] + MODELS[CYRILLIC]))


_ENGINES: Engines | None = None


def handler(event: dict, context: object, s3=None) -> dict:  # noqa: ANN001 - a boto3 client
    """The Lambda entry point: read the one cleared upload the document worker names.

    The event carries only the object key. The bucket is the function's own configuration
    (DOCUMENT_BUCKET), so a caller chooses which upload is read, never which bucket, and the role
    can read only objects GuardDuty tagged clean. The models load on the first invocation and stay
    loaded while the execution environment lives -- not at import, because Lambda caps its Init
    phase at 10 seconds and loading them takes longer.
    """
    global _ENGINES
    if s3 is None:
        import boto3  # the Lambda base image ships it; the local child never imports it

        s3 = boto3.client("s3")
    body = s3.get_object(Bucket=os.environ["DOCUMENT_BUCKET"], Key=event["key"])["Body"]
    data = body.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("object is larger than a transcript")
    if _ENGINES is None:
        _ENGINES = Engines()
    return read_document(data, _ENGINES)


def main() -> None:
    # Paddle's C++ side prints to file descriptor 1 ("ReduceMeanCheckIfOneDNNSupport", measured
    # 2026-09-26), which would corrupt the JSON the caller parses. So the answer gets a private
    # copy of stdout, and descriptor 1 -- everything any library prints -- goes to stderr.
    answer = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    if sys.argv[1:] == ["--bake"]:
        bake()
        return
    json.dump(read_document(sys.stdin.buffer.read(), Engines()), answer)
    answer.flush()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run to verify they pass, and that the app's suite skips them**

Run: `cd /home/orkhan/Desktop/tailored-programmes && uv run --project ocr pytest ocr -q && POSTGRES_DB=tehsil_tailored uv run pytest ocr -q`
Expected: `20 passed`, then `1 skipped` (the app's venv has no `cv2`, so `pytest.importorskip` skips the module).

- [ ] **Step 8: Fetch the models once and read a synthetic line**

On a machine that already ran `.superpowers/ocr-eval`, the models are in `~/.paddlex` and nothing downloads.

Run: `cd /home/orkhan/Desktop/tailored-programmes && uv run --project ocr python ocr/read_pages.py --bake`
Expected: the last line is `baked ['PP-OCRv5_server_det', 'PP-OCRv6_medium_det', 'PP-OCRv6_medium_rec', 'eslav_PP-OCRv5_mobile_rec']`. Paddle's log lines go to stderr.

- [ ] **Step 9: Write the seam's failing tests**

Create `tests/documents/test_ocr.py`. The child-process tests run real subprocesses of this interpreter, so the timeout, the environment and the output contract are exercised for real; the Lambda tests replace only `_lambda_client`; one test runs the real program and skips without it.

```python
"""The seam to the OCR program: both transports, what crosses them, what they refuse, and one
run of the real engine."""

import io
import json
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ReadTimeoutError
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

from apps.documents import ocr
from apps.documents.ocr import OcrUnavailable, PageRefused, read_pages

_DOCUMENT = SimpleNamespace(object_key="quarantine/tenant/document")
_PAGE = {"script": "latin", "skew": 0.7, "lines": ["BSc Chemistry"], "tables": [[["6"]]]}


def _child(tmp_path, monkeypatch, body):
    """Stand a small Python script in for ocr/read_pages.py, run by this interpreter."""
    (tmp_path / "ocr").mkdir()
    (tmp_path / "ocr" / "read_pages.py").write_text(textwrap.dedent(body))
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(settings, "OCR_PYTHON", sys.executable)
    monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "")


def _answering(tmp_path, monkeypatch, output):
    (tmp_path / "output.json").write_text(json.dumps(output))
    _child(tmp_path, monkeypatch, f"print(open({str(tmp_path / 'output.json')!r}).read())")


class _Lambda:
    def __init__(self, payload, function_error=None, raises=None):
        self.payload, self.function_error, self.raises = payload, function_error, raises
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        response = {"Payload": io.BytesIO(json.dumps(self.payload).encode())}
        if self.function_error:
            response["FunctionError"] = self.function_error
        return response


def _function(monkeypatch, client):
    monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "tehsil-transcript-ocr")
    monkeypatch.setattr(ocr, "_lambda_client", lambda: client)
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: pytest.fail("ran a child"))


def test_pages_come_back_typed(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [_PAGE]})
    [read] = read_pages(_DOCUMENT, b"%PDF")
    assert read.lines == ("BSc Chemistry",) and read.tables == ((("6",),),)


def test_a_refused_page_is_a_named_refusal(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"refused": {"reason": "blurred", "page": 2}})
    with pytest.raises(PageRefused) as error:
        read_pages(_DOCUMENT, b"%PDF")
    assert (error.value.reason, error.value.page) == ("blurred", 2)


def test_a_crash_is_unavailable_never_an_empty_transcript(tmp_path, monkeypatch):
    _child(tmp_path, monkeypatch, "raise SystemExit(3)")
    with pytest.raises(OcrUnavailable):
        read_pages(_DOCUMENT, b"%PDF")


def test_output_that_is_not_the_contract_is_unavailable(tmp_path, monkeypatch):
    _answering(tmp_path, monkeypatch, {"pages": [{"lines": 1}]})
    with pytest.raises(OcrUnavailable):
        read_pages(_DOCUMENT, b"%PDF")


def test_the_child_inherits_no_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_RUNTIME_PASSWORD", "hunter2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _child(
        tmp_path,
        monkeypatch,
        """
        import json, os
        page = {"script": "latin", "skew": 0.0, "lines": sorted(os.environ), "tables": []}
        print(json.dumps({"pages": [page]}))
        """,
    )
    [read] = read_pages(_DOCUMENT, b"%PDF")
    assert "POSTGRES_RUNTIME_PASSWORD" not in read.lines and "OPENAI_API_KEY" not in read.lines
    assert "OPENCV_IO_MAX_IMAGE_PIXELS" in read.lines


def test_a_hung_engine_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "_TIMEOUT_SECONDS", 0.5)
    _child(tmp_path, monkeypatch, "import time; time.sleep(5)")
    with pytest.raises(OcrUnavailable):
        read_pages(_DOCUMENT, b"%PDF")


def test_with_a_function_named_the_key_is_sent_never_the_bytes(monkeypatch):
    client = _Lambda({"pages": [_PAGE]})
    _function(monkeypatch, client)
    [read] = read_pages(_DOCUMENT, b"%PDF the whole upload")
    assert read.lines == ("BSc Chemistry",)
    [call] = client.calls
    assert call["FunctionName"] == "tehsil-transcript-ocr"
    assert json.loads(call["Payload"]) == {"key": "quarantine/tenant/document"}


def test_a_function_refusal_is_a_named_refusal(monkeypatch):
    _function(monkeypatch, _Lambda({"refused": {"reason": "low_resolution", "page": 1}}))
    with pytest.raises(PageRefused, match="low_resolution"):
        read_pages(_DOCUMENT, b"%PDF")


def test_a_function_error_is_unavailable_and_its_message_is_not_logged(monkeypatch, caplog):
    error = {"errorType": "MemoryError", "errorMessage": "Ali Aliyev 01.05.2002"}
    _function(monkeypatch, _Lambda(error, function_error="Unhandled"))
    with pytest.raises(OcrUnavailable):
        read_pages(_DOCUMENT, b"%PDF")
    assert "MemoryError" in caplog.text and "Aliyev" not in caplog.text


def test_a_function_that_does_not_answer_in_time_is_unavailable(monkeypatch):
    _function(monkeypatch, _Lambda(None, raises=ReadTimeoutError(endpoint_url="lambda")))
    with pytest.raises(OcrUnavailable):
        read_pages(_DOCUMENT, b"%PDF")


def test_the_client_never_retries_an_invocation(monkeypatch):
    """A retry is a second full read of the same transcript, billed."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")  # on ECS the task supplies it
    client = ocr._lambda_client()
    assert client.meta.config.retries["total_max_attempts"] == 1
    assert client.meta.config.read_timeout > ocr._TIMEOUT_SECONDS


_BAKED = Path(settings.OCR_MODEL_HOME, "official_models")


@pytest.mark.skipif(
    not (Path(settings.OCR_PYTHON).exists() and _BAKED.exists()),
    reason="no OCR program: `uv sync --project ocr`, then its read_pages.py --bake",
)
def test_the_real_engine_reads_a_rendered_line(monkeypatch):
    monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "")
    image = Image.new("RGB", (1654, 700), "white")
    font = ImageFont.load_default(size=44)
    ImageDraw.Draw(image).text((80, 200), "Organic Chemistry I   6   91", fill="black", font=font)
    ImageDraw.Draw(image).text((80, 320), "Physical Chemistry II   5   80", fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    [page] = read_pages(_DOCUMENT, buffer.getvalue())
    cells = [cell for table in page.tables for row in table for cell in row]
    text = " ".join([*page.lines, *cells])
    assert "Chemistry" in text
    assert page.script == "latin"
```

- [ ] **Step 10: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_ocr.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.documents.ocr'`

- [ ] **Step 11: Write the seam and its settings**

Create `apps/documents/ocr.py`:

```python
"""Run the transcript OCR (ocr/read_pages.py) over one upload, where it runs.

PaddleOCR cannot be imported here: paddlepaddle has no CPython 3.14 wheel, so the OCR program has
its own Python 3.12 and its own image. In production it is an AWS Lambda function
(settings.OCR_FUNCTION_NAME, ocr/Dockerfile) invoked with the upload's key -- it reads the object
itself, since a synchronous invocation carries at most 6 MB and an upload may be 10 MB -- in
subnets with no route to the internet and a role that can read cleared uploads and nothing else.
Locally and in tests, with the setting empty, the same program runs as a child process of this
one: bytes on stdin, JSON on stdout, no secret in its environment. This module is the only place
that knows which; the reader's tests replace `read_pages` wholesale.

The child-process posture is the pypdf path's, and it is a choice for development only: a
same-user process can read /proc/<parent>/environ whatever environment it was handed. Production
never runs the parser beside the app's secrets.
"""

from __future__ import annotations

import json
import logging
import subprocess  # nosec B404 -- a fixed argv and no shell; the upload travels as stdin data
from typing import Any, Literal

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from django.conf import settings
from pydantic import BaseModel, ConfigDict, ValidationError

from apps.concierge.models import DocumentVersion

logger = logging.getLogger(__name__)

#: The OCR function's own Timeout (infra/template.yaml, OcrFunction): eight pages at the slowest
#: measured page, 67 s at 6 vCPU, plus a cold start. Under the scan queue's 900 s visibility
#: timeout, so a slow read is never redelivered to a second reader while it is still running.
_TIMEOUT_SECONDS = 720


class OcrPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: Literal["latin", "cyrillic"]
    skew: float
    #: The page's text lines outside any table, in reading order.
    lines: tuple[str, ...]
    #: Each table as rows of cell text, spans filled so every row lines up with its columns.
    tables: tuple[tuple[tuple[str, ...], ...], ...]


class _Refusal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    page: int


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: tuple[OcrPage, ...] = ()
    refused: _Refusal | None = None


class PageRefused(RuntimeError):
    """A page nobody can read: the student is asked to rescan, and nothing is guessed from it.

    `reason` is read_pages' name for it -- low_resolution, blurred, text_too_small, no_text,
    unreadable, too_many_pages or page_too_large -- and `page` is 1-based.
    """

    def __init__(self, reason: str, page: int) -> None:
        super().__init__(f"page {page}: {reason}")
        self.reason = reason
        self.page = page


class OcrUnavailable(RuntimeError):
    """The engine did not answer -- a crash, a timeout, a missing interpreter. Never a refusal."""


def _child_env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",  # nosec B108 -- the engine writes nothing there; it wants a HOME to exist
        "PADDLE_PDX_CACHE_HOME": settings.OCR_MODEL_HOME,
        # The models are baked into the image; nothing is downloaded and nothing is checked.
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        # A 10 MB JPEG can declare 50,000 x 50,000 pixels; OpenCV refuses to decode past this.
        "OPENCV_IO_MAX_IMAGE_PIXELS": "50000000",
    }


def read_pages(document: DocumentVersion, content: bytes) -> tuple[OcrPage, ...]:
    """Every page's lines and tables, or PageRefused for a page the gate will not read.

    `content` is what open_document returned for `document`; the child reads it, the Lambda
    function reads the same object by key.
    """
    if settings.OCR_FUNCTION_NAME:
        raw = _invoke(document.object_key)
    else:
        raw = _run_child(content)
    try:
        output = _Output.model_validate_json(raw)
    except ValidationError as error:
        raise OcrUnavailable("unparseable output") from error
    if output.refused is not None:
        raise PageRefused(output.refused.reason, output.refused.page)
    return output.pages


def _lambda_client() -> Any:
    """Indirection for tests only. One attempt, never a retry: a retried invocation is a second
    full read of the same transcript, billed. The read timeout outlasts the function's own."""
    config = Config(
        read_timeout=_TIMEOUT_SECONDS + 30, connect_timeout=10, retries={"total_max_attempts": 1}
    )
    return boto3.client("lambda", config=config)


def _invoke(key: str) -> bytes:
    try:
        response = _lambda_client().invoke(
            FunctionName=settings.OCR_FUNCTION_NAME, Payload=json.dumps({"key": key}).encode()
        )
    except (BotoCoreError, ClientError) as error:
        raise OcrUnavailable(type(error).__name__) from error
    payload: bytes = response["Payload"].read()
    if "FunctionError" in response:
        # The error's type only: its message and stack trace can quote the document's text.
        error_type = json.loads(payload or b"{}").get("errorType", response["FunctionError"])
        logger.warning("OcrFunctionError error=%s", error_type)
        raise OcrUnavailable(f"function error {error_type}")
    return payload


def _run_child(content: bytes) -> bytes:
    try:
        done = subprocess.run(  # nosec B603 -- argv is two paths from settings, never the upload
            [settings.OCR_PYTHON, str(settings.BASE_DIR / "ocr" / "read_pages.py")],
            input=content,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            env=_child_env(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OcrUnavailable(type(error).__name__) from error
    if done.returncode != 0:
        # The exception's name only: a traceback's message can quote the document's text.
        last = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        logger.warning("OcrCrashed exit=%s error=%s", done.returncode, last[0].split(":")[0])
        raise OcrUnavailable(f"exit {done.returncode}")
    return done.stdout
```

In `config/settings/base.py`, after `DOCUMENT_SCAN_QUEUE_URL = ...`:

```python
#: Where transcript OCR runs (apps/documents/ocr.py). Set in production: the Lambda function the
#: document worker invokes. Empty: a child process of this interpreter, run by OCR_PYTHON with
#: models from OCR_MODEL_HOME -- `uv sync --project ocr`'s ocr/.venv/bin/python and wherever its
#: --bake cached them (~/.paddlex by default).
OCR_FUNCTION_NAME = os.getenv("OCR_FUNCTION_NAME", "")
OCR_PYTHON = os.getenv("OCR_PYTHON", str(BASE_DIR / "ocr" / ".venv" / "bin" / "python"))
OCR_MODEL_HOME = os.getenv("OCR_MODEL_HOME", str(Path.home() / ".paddlex"))
```

- [ ] **Step 12: Run to verify they pass, including the real program**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_ocr.py -q -rs`
Expected: `12 passed` on a machine where Step 8 ran (the real read takes ~10–20 s), or `11 passed, 1 skipped` where it did not. The real test is the one that catches the program's stdout being polluted: without `main()`'s descriptor swap, Paddle's `ReduceMeanCheckIfOneDNNSupport` lines land in front of the JSON and the read fails as `OcrUnavailable`.

- [ ] **Step 13: Build the OCR image**

Create `ocr/Dockerfile`:

```dockerfile
# The transcript OCR program as an AWS Lambda container image (apps/documents/ocr.py invokes it).
# Its own image, never the app's: ~3 GB of PaddlePaddle and model weights that no other service
# needs, on Python 3.12 because paddlepaddle publishes no 3.14 wheel. Build context is ocr/, so no
# app code or secret can enter it:
#   docker build --platform linux/amd64 --provenance=false -t tehsil-ocr ocr/
#
# AWS's own Python 3.12 base image: it carries the Lambda runtime client, the runtime interface
# emulator for local invokes, and boto3 (the handler's S3 read). Pinned by digest, like every base
# image here -- a tag is repointable. Bump it deliberately, together with `requires-python`
# in ocr/pyproject.toml (tests/test_bootstrap.py pins the two together).
FROM ghcr.io/astral-sh/uv:0.12.18@sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc AS uv

FROM public.ecr.aws/lambda/python:3.12@sha256:93ffd196f8f7698a506e7b6f442488f563adf9b45ad589bcfff57ce6b9ad4d62
COPY --from=uv /uv /usr/local/bin/uv
# libGL for OpenCV (paddlex pins the non-headless build), libgomp for Paddle; glib is in the base.
RUN dnf install -y mesa-libGL libgomp && dnf clean all
COPY pyproject.toml uv.lock ./
# The exact graph ocr/uv.lock pins, hash-checked, into the task root Lambda puts on sys.path.
RUN uv export --frozen --no-dev -o /tmp/requirements.txt \
    && uv pip install --python /var/lang/bin/python3.12 --target "${LAMBDA_TASK_ROOT}" \
       --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
# Lambda runs the image on a read-only file system as an unprivileged user, with /tmp the one
# writable place. The models live in the image; HOME points anything that insists on writing
# at /tmp.
ENV PADDLE_PDX_CACHE_HOME=/opt/ocr/paddlex HOME=/tmp OPENCV_IO_MAX_IMAGE_PIXELS=50000000
COPY read_pages.py ./
# Bake every model into the image, readable by any user; then prove, with no network at all,
# that nothing is fetched at run time -- the function's subnets have no route to the internet.
RUN python read_pages.py --bake && chmod -R a+rX /opt/ocr
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
RUN --network=none python read_pages.py --bake
CMD ["read_pages.handler"]
```

and `ocr/.dockerignore`:

```text
.venv
__pycache__
*.py[cod]
```

In the root `.dockerignore`, change the line `.venv` to `**/.venv`: the app image's context is the whole repository, and a developer's `ocr/.venv` is 1.4 GB.

Add to `tests/test_bootstrap.py`, after `test_every_declared_python_version_agrees` — the same failure that test exists for, on the OCR program's own two declarations:

```python
def test_the_ocr_image_runs_the_python_its_lock_was_resolved_for() -> None:
    """The OCR program is deliberately on another Python (paddlepaddle has no 3.14 wheel), and
    has the same failure mode on its own: ocr/uv.lock resolved for one interpreter, the image's
    base shipping another. Its two declarations must agree with each other."""
    dockerfile = (ROOT / "ocr/Dockerfile").read_text()
    pyproject = (ROOT / "ocr/pyproject.toml").read_text()
    base = re.findall(r"^FROM public\.ecr\.aws/lambda/python:(\d+\.\d+)@", dockerfile, re.M)
    pinned = re.findall(r'requires-python\s*=\s*"==(\d+\.\d+)\.\*"', pyproject)
    assert base and pinned, "no Python version found in ocr/ -- has the format changed?"
    assert set(base) == set(pinned), f"ocr/Dockerfile {base} vs ocr/pyproject.toml {pinned}"
```

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/test_bootstrap.py -q && docker build --platform linux/amd64 --provenance=false -t tehsil-ocr ocr/`
Expected: `4 passed`; the build succeeds and both `--bake` steps print `baked [...]`, the second with no network. Measured 2026-09-26: the first bake downloads the weights in ~155 s, the offline one takes ~28 s.

Then run it under Lambda's constraints — read-only, an unprivileged user, no network:

```bash
docker run --rm --network=none --read-only --tmpfs /tmp --user 993:990 --entrypoint python tehsil-ocr -c "import cv2, numpy as np, read_pages as rp; page = np.full((900, 1400, 3), 255, np.uint8); cv2.putText(page, 'Organic Chemistry I 6 91', (60, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3); _, png = cv2.imencode('.png', page); out = rp.read_document(png.tobytes(), rp.Engines()); assert any('Chemistry' in line for line in out['pages'][0]['lines']), out; print('read', out['pages'][0]['lines'])"
```

Expected: `read ['Organic Chemistry 1 6 91']` or close (the `1` for `I` is the letter swap spec §3.1 lists; the smoke asserts only `Chemistry`). Measured: ~12 s.

And once through the Lambda runtime interface emulator the base image ships, against a local stand-in for S3, to prove the handler path — the event, the configured bucket, the S3 read — end to end:

```bash
cd /tmp && mkdir -p fakes3/evidence/quarantine/t awscfg && cp /home/orkhan/Desktop/tailored-programmes/.superpowers/ocr-eval/out/paddle/_pages/az_invented_diploma_elave_scan-3.png fakes3/evidence/quarantine/t/d \
  && printf '[default]\ns3 =\n    addressing_style = path\n' > awscfg/config \
  && (cd fakes3 && timeout 300 python3 -m http.server 9000 --bind 127.0.0.1 >/dev/null 2>&1 &) \
  && docker run -d --name ocr-rie --network host --read-only --tmpfs /tmp --user 993:990 -v /tmp/awscfg:/cfg:ro \
     -e AWS_CONFIG_FILE=/cfg/config -e DOCUMENT_BUCKET=evidence -e AWS_ENDPOINT_URL_S3=http://127.0.0.1:9000 \
     -e AWS_ACCESS_KEY_ID=x -e AWS_SECRET_ACCESS_KEY=x -e AWS_DEFAULT_REGION=us-east-1 tehsil-ocr \
  && sleep 2 && for i in 1 2; do time curl -s -XPOST localhost:8080/2015-03-31/functions/function/invocations -d '{"key": "quarantine/t/d"}' | head -c 120; echo; done; docker rm -f ocr-rie
```

Expected: both invocations print `{"pages": [{"script": "latin", ...`. Measured 2026-09-26 on an unrestricted 28-core host: Init 0.2 s, first invocation 34 s, second 24 s — the ~11 s difference is the models loading on the first call, which is part of every cold start.

- [ ] **Step 14: Put the OCR checks in CI**

In `.github/workflows/ci.yml`, `test` job: change the bandit step to `uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py`, and after the existing `pip-audit` step add:

```yaml
      # The OCR program's own graph (ocr/uv.lock, CPython 3.12). The step above audits
      # the app's venv and cannot see it; --no-deps --disable-pip audits the exact
      # pins without installing 3.12 wheels under 3.14.
      - run: |
          uv export --project ocr --frozen --no-hashes --no-dev -o /tmp/ocr-requirements.txt
          uv run pip-audit -r /tmp/ocr-requirements.txt --no-deps --disable-pip
      - run: uv sync --project ocr --frozen && uv run --project ocr pytest ocr -q
```

(The later `uv run pytest -q` then finds `ocr/.venv` but no baked models, so the real-program test skips rather than downloading 1.2 GB of weights.)

Add a job beside `web-image`:

```yaml
  ocr-image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      # Building is half the check: the image's own --network=none bake proves
      # every model is inside it. The run below is the other half, under the
      # constraints Lambda imposes -- a read-only file system with /tmp the only
      # writable place, an unprivileged user, and no network -- so a library that
      # writes a cache beside itself, or a model file only root can read, fails
      # here and not on a student's transcript.
      - run: docker build --platform linux/amd64 --provenance=false -t tehsil-ocr:ci ocr/
      - run: |
          docker run --rm --network=none --read-only --tmpfs /tmp --user 993:990 \
            --entrypoint python tehsil-ocr:ci -c "import cv2, numpy as np, read_pages as rp; page = np.full((900, 1400, 3), 255, np.uint8); cv2.putText(page, 'Organic Chemistry I 6 91', (60, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3); _, png = cv2.imencode('.png', page); out = rp.read_document(png.tobytes(), rp.Engines()); assert any('Chemistry' in line for line in out['pages'][0]['lines']), out; print('read', out['pages'][0]['lines'])"
```

- [ ] **Step 15: Lint, types, security, commit**

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv run ruff check apps config tests scripts ocr && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py && POSTGRES_DB=tehsil_tailored uv run pytest -q
git -C /home/orkhan/Desktop/tailored-programmes add ocr/pyproject.toml ocr/uv.lock ocr/read_pages.py ocr/test_read_pages.py ocr/Dockerfile ocr/.dockerignore apps/documents/ocr.py tests/documents/test_ocr.py tests/test_bootstrap.py config/settings/base.py .dockerignore .github/workflows/ci.yml
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(documents): transcript OCR -- its own image, run on demand, behind an upload gate

paddlepaddle has no CPython 3.14 wheel, so OCR is its own uv project on 3.12 and
its own container image: an AWS Lambda function in production, invoked with the
cleared upload's key, and a child process with no secret locally. Every page is
straightened, routed Latin or Cyrillic by the East-Slavic recogniser, and
refused by name when coarser than 150 ppi, blurred, or set in text under 12 px.
Models are baked into the image; a network-less build step and a read-only,
unprivileged run prove nothing is fetched or written at run time.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: every check clean; bandit reports no issues (the two `# nosec` markers in `apps/documents/ocr.py` name why).

---

### Task 2b: The reader — minimised candidates, Jev's questions, verbatim copies

> **Prerequisite: the decision layer's Task 1 must be in this branch first.** This task imports `Answer`, `Client` and `ask` from `apps/research/decisions.py`, which `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` Task 1 creates (with the settings `TYPESAFE_MODEL`, `TYPESAFE_BASE_URL`, `DECISIONS_PROVIDER` beside the existing `TYPESAFE_API_KEY`, and the pinned `typesafe-sdk`). **No branch has it committed yet** (checked 2026-09-26): `claude/decision-layer` (worktree `/home/orkhan/Desktop/tehsil_agent/.claude/worktrees/agent-a0a4a92d0ab8ba4c7`) sits at master's `ee629959` with only an uncommitted `uv add` of the two SDKs in `pyproject.toml`/`uv.lock`; the plan itself lives on `claude/fetch-spec-refresh` and is also in this tree. So, in order of preference:
>
> 1. Execute that plan's Task 1 on `claude/decision-layer`, commit it, then bring it here:
>    `git -C /home/orkhan/Desktop/tailored-programmes merge claude/decision-layer`
>    That branch is based on master, which already contains this branch (PR #132), so the merge also brings master's newer commits — among them `documents/0022_draft_rendered_filename` (see the migration note in Global Constraints). Resolve any `uv.lock` conflict with `uv lock`, never by hand.
> 2. Or execute that Task 1 here, in this worktree, exactly as written there (Steps 0–6), on this branch.
>
> Either way, check before starting: `cd /home/orkhan/Desktop/tailored-programmes && uv run python -c "from apps.research.decisions import Answer, Client, ask; from django.conf import settings" && grep -n "TYPESAFE_MODEL\|TYPESAFE_BASE_URL\|DECISIONS_PROVIDER" config/settings/base.py` — expected: no error, and three settings lines. The OpenRouter route is configuration, not code: `TYPESAFE_BASE_URL=https://openrouter.ai/api` and `TYPESAFE_MODEL=typesafe/jev-1.13` are set in the environment (Task 3c puts them on the document worker); the decision layer's defaults stay as that plan wrote them. On that route `TYPESAFE_API_KEY` holds the OpenRouter key. The decision layer's module was run against this task's tests on 2026-09-26 and needed no change.

**What this task does.** It replaces the shape-only `apps/documents/transcript.py` with the reader. Code minimises what OCR returned (Global Constraints), cuts candidates, asks Jev closed questions in a first request (what each table column holds; which printed line is the institution, the qualification, the field; which printed number is the overall grade, the scale's maximum, the total credits; which printed date is the completion or expected graduation date; the credit system; the country) and then per row, forty rows a request (the row's kind; whether it says the course is in progress; whether it records a failed attempt). Code copies the chosen cells, marks an earlier failed attempt whose title appears again later as `SUPERSEDED_ATTEMPT` (the comparison is code's, never Jev's), and turns every answer below the bar into an `unsure` highlight. `academic_record`'s output shape — Task 4's `AcademicRecord` — is unchanged.

**Files:**
- Create: `apps/documents/transcript_questions.py`
- Modify (rewrite): `apps/documents/transcript.py`, `tests/documents/test_transcript.py`
- Modify: `tests/documents/test_transcript_worker.py` — drop the one test built on the old shape (Task 3c rewrites this file)

**Interfaces:**
- Consumes: `read_pages`, `OcrPage` (Task 2a); `ask`, `Answer`, `Client`, `Choice`, `Noul`, `Question` (decision layer Task 1); `to_ects`, `CreditUnit` (Task 1); `open_document`, `ReadableObjectStore` (`apps/concierge/documents.py`); `UnsupportedUpload` (`apps/documents/ingestion.py`); `rate_limited`; `ISO_3166_ALPHA2_CODES` (`apps/reference_data.py`).
- Produces:
  - `apps.documents.transcript_questions`: `DECISION = "transcript"`, `UNSURE_BELOW = 0.85`, `NONE = "none"`, `COLUMN_KINDS`, `ROW_KINDS`, `CREDIT_SYSTEMS`, `column(index) -> Choice`, `row_kind(index) -> Choice`, `in_progress(index) -> Noul`, `failed(index) -> Noul`, `transcript(lines, numbers, dates) -> dict[str, Question]`.
  - `apps.documents.transcript`: `TranscriptCourse(title, credits: Decimal | None, grade: str | None, status)`; `TranscriptContent(institution, country_code, qualification, field, overall_grade, grading_scale, credit_unit, local_credits_per_year: Decimal | None, courses, completed_on, expected_completion)` — `uncertain_fields` is gone; `Highlight(kind, scope, ref)` (pydantic, frozen, `extra="forbid"`); `Row(index, kind, title, credits, grade, status)`; `Reading(content, rows, total_credits_line, doubts)`; `TranscriptRateLimited`; `number(text) -> Decimal | None`; `personal_names(student) -> frozenset[str]`; `read_transcript(*, document, names, store=None, client=None) -> Reading`; `academic_record(content) -> dict[str, object]` (unchanged shape). `UncertainField` and `uncertain_fields` are removed.

- [ ] **Step 1: Write the failing tests**

Replace `tests/documents/test_transcript.py` with the file below. `_jev` is a scripted decision client injected through `ask(client=...)`, so the decision layer's own checks (a question left unanswered, the option ceiling, the token estimate) run for real; `_answer` is test scaffolding that answers like a careful reader of these fixtures, not a model of Jev. `read_pages` is replaced at the reader's import site.

```python
import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.concierge.documents import apply_scan_result, register
from apps.documents.ingestion import UnsupportedUpload
from apps.documents.models import VerifiedFact
from apps.documents.ocr import OcrPage, PageRefused
from apps.documents.transcript import (
    Highlight,
    TranscriptContent,
    TranscriptCourse,
    TranscriptRateLimited,
    academic_record,
    number,
    personal_names,
    read_transcript,
)
from apps.research.decisions import Answer
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

_PDF = b"%PDF-1.7 a transcript"
HEADER = ("Code", "Course", "Credits", "Grade")
LINES = (
    "Baku State University",
    "Bachelor of Science",
    "Field of study: Chemistry",
    "GPA 88 / 100",
    "Expected graduation 30.06.2027",
)
COURSES = (
    HEADER,
    ("", "Semester 1", "", ""),
    ("CHEM101", "Organic Chemistry I", "6", "91"),
    ("CS100", "Programming", "5", "FF"),
    ("", "Total", "11", ""),
    ("", "Semester 2", "", ""),
    ("CS100", "Programming", "5", "80"),
    ("CHEM400", "Thesis", "15", "in progress"),
    ("", "Total", "20", ""),
)


def _page(*tables, lines=LINES):
    return OcrPage(
        script="latin",
        skew=0.0,
        lines=tuple(lines),
        tables=tuple(tuple(tuple(row) for row in table) for table in tables),
    )


def _answer(state, qid):
    """What a careful reader of these fixtures answers. Test scaffolding, not a model of Jev."""
    name, _, index = qid.partition(":")
    if name == "column":
        header = state["columns"][int(index)]["cells"][0]
        kinds = {"Code": "course_code", "Course": "course_title", "Credits": "credits"}
        return kinds.get(header, "grade" if header == "Grade" else "other")
    if name in ("kind", "in_progress", "failed"):
        cells = state["rows"][int(index)]
        text = " ".join(cells)
        if name == "in_progress":
            return "in progress" in text
        if name == "failed":
            return "FF" in cells
        if text.strip().startswith("Semester"):
            return "semester_heading"
        if "Overall" in text:
            return "overall_total"
        if "Total" in text:
            return "semester_total"
        return "header" if "Course" in cells else "course"
    lines = {line["text"]: line["id"] for line in state["lines"]}
    numbers = {found["text"]: found["id"] for found in state["numbers"]}
    dates = {found["text"]: found["id"] for found in state["dates"]}
    return {
        "credit_system": "ECTS",
        "country": "AZ",
        "institution": lines.get("Baku State University", "none"),
        "qualification": lines.get("Bachelor of Science", "none"),
        "field": lines.get("Field of study: Chemistry", "none"),
        "overall_grade": numbers.get("88", "none"),
        "grading_scale": numbers.get("100", "none"),
        "total_credits": "none",
        "completed_on": "none",
        "expected_completion": dates.get("30.06.2027", "none"),
    }[qid]


def _jev(*, unsure=(), states=None):
    def call(state, questions, *, model, provider):
        if states is not None:
            states.append(state)
        answers = {}
        for qid in questions:
            value = _answer(state, qid)
            confidence = 0.4 if qid in unsure else 0.97
            answers[qid] = Answer(
                id=qid,
                value=value,
                confidence=confidence,
                probabilities={str(value): confidence},
                model=model,
                provider=provider,
            )
        return answers

    return call


def _document(agency, student, fake_store, content=_PDF):
    document = register(agency.id, student.id, kind="TRANSCRIPT")
    document = apply_scan_result(document, "NO_THREATS_FOUND")
    fake_store.put(document.object_key, content)
    return document


def _read(agency, student, fake_store, *pages, names=frozenset(), client=None, content=_PDF):
    with tenant_scope(agency.id):
        document = _document(agency, student, fake_store, content)
    with patch("apps.documents.transcript.read_pages", return_value=pages):
        return read_transcript(
            document=document, names=names, store=fake_store, client=client or _jev()
        )


def test_every_value_is_a_printed_cell_or_line_jev_chose(agency_a, membership_a, fake_store):
    reading = _read(agency_a, membership_a, fake_store, _page(COURSES))
    content = reading.content
    assert (content.institution, content.qualification, content.field) == (
        "Baku State University",
        "Bachelor of Science",
        "Chemistry",
    )
    assert (content.overall_grade, content.grading_scale) == ("88", "100")
    assert content.credit_unit == "ECTS"
    assert content.country_code == "AZ"
    assert content.expected_completion == date(2027, 6, 30) and content.completed_on is None
    assert [(c.title, c.credits, c.grade, c.status) for c in content.courses] == [
        ("Organic Chemistry I", Decimal("6"), "91", "COMPLETED"),
        ("Programming", Decimal("5"), "FF", "SUPERSEDED_ATTEMPT"),
        ("Programming", Decimal("5"), "80", "COMPLETED"),
        ("Thesis", Decimal("15"), "in progress", "IN_PROGRESS"),
    ]
    assert reading.doubts == ()


def test_a_failed_course_never_retaken_is_kept_as_completed(agency_a, membership_a, fake_store):
    table = (HEADER, ("CS100", "Programming", "5", "FF"))
    [course] = _read(agency_a, membership_a, fake_store, _page(table)).content.courses
    assert course.status == "COMPLETED" and course.grade == "FF"


def test_academic_record_drops_the_superseded_attempt_and_converts_credits():
    content = TranscriptContent(
        institution="Baku State University",
        country_code="AZ",
        qualification="BSc",
        field="Chemistry",
        overall_grade="88",
        grading_scale="100",
        credit_unit="ECTS",
        courses=(
            TranscriptCourse(
                title="Programming", credits=Decimal(5), grade="FF", status="SUPERSEDED_ATTEMPT"
            ),
            TranscriptCourse(title="Programming", credits=Decimal(5), status="COMPLETED"),
            TranscriptCourse(title="Thesis", credits=Decimal(15), status="IN_PROGRESS"),
            TranscriptCourse(title="Misread", credits=Decimal(150), status="COMPLETED"),
        ),
        expected_completion=date(2027, 6, 30),
    )
    record = academic_record(content)
    assert [c["title"] for c in record["courses"]] == ["Programming", "Thesis", "Misread"]
    assert record["courses"][0]["ects"] == "5.00"
    assert record["courses"][1]["in_progress"] is True
    assert record["courses"][2]["ects"] is None  # a 150-credit course fails the range check
    assert record["expected_completion"] == "2027-06-30"


def test_nothing_identifying_the_student_reaches_jev(agency_a, membership_a, fake_store):
    lines = (
        "Family name: Aliyev",
        "Ali Aliyev",
        "Date of birth:",
        "01.05.2002",
        "Student No 20231234",
        *LINES,
    )
    table = (
        HEADER,
        ("Surname", "Aliyev", "", ""),
        ("", "Ali Aliyev", "", ""),
        ("1801101", "Ali riyaziyyat I", "6", "91"),
    )
    states = []
    reading = _read(
        agency_a,
        membership_a,
        fake_store,
        _page(table, lines=lines),
        names=frozenset({"ali", "aliyev"}),
        client=_jev(states=states),
    )
    sent = json.dumps(states, ensure_ascii=False)
    for personal in ("Aliyev", "01.05.2002", "20231234", "1801101"):
        assert personal not in sent
    # Two name words make a line personal, never one: "Ali" is also Azerbaijani for "higher".
    assert [course.title for course in reading.content.courses] == ["Ali riyaziyyat I"]


def test_a_name_the_document_labels_once_is_dropped_everywhere(agency_a, membership_a, fake_store):
    """The Russian specimen prints the name in its personal-data block and again, unlabelled, at
    the head of every page -- in Cyrillic, which no Latin account name would match."""
    pages = (
        _page(lines=("Фамилия Иванов Имя Иван Отчество Иванович", *LINES)),
        _page(COURSES, lines=("Иванов Иван Иванович", "Страница 2")),
    )
    states = []
    _read(agency_a, membership_a, fake_store, *pages, client=_jev(states=states))
    assert "Иванов" not in json.dumps(states, ensure_ascii=False)


def test_a_second_credits_column_does_not_split_the_table(agency_a, membership_a, fake_store):
    """NKU prints ECTS and local credits side by side; the first is the one read."""
    table = (("Code", "Course", "Credits", "Credits", "Grade"), ("C1", "Physics I", "6", "4", "BA"))
    [course] = _read(agency_a, membership_a, fake_store, _page(table)).content.courses
    assert (course.credits, course.grade) == (Decimal("6"), "BA")


def test_personal_names_come_from_the_account_and_from_the_cv(agency_a, membership_a):
    membership_a.user.first_name, membership_a.user.last_name = "Leyla", "Mammadova"
    membership_a.user.save()
    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Leyla Rauf qizi Mammadova"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            created_by=membership_a,
        )
        assert personal_names(membership_a) == {"leyla", "mammadova", "rauf", "qizi"}


def test_an_unsure_answer_becomes_a_highlight(agency_a, membership_a, fake_store):
    reading = _read(
        agency_a,
        membership_a,
        fake_store,
        _page(COURSES),
        client=_jev(unsure=("institution", "kind:2", "column:1")),
    )
    assert set(reading.doubts) == {
        Highlight(kind="unsure", scope="field", ref="institution"),
        Highlight(kind="unsure", scope="row", ref="2"),
        Highlight(kind="unsure", scope="transcript", ref="columns"),
    }


def test_two_semesters_printed_side_by_side_are_read_one_after_the_other(
    agency_a, membership_a, fake_store
):
    table = (
        (*HEADER, *HEADER),
        ("", "Semester 1", "", "", "", "Semester 2", "", ""),
        ("C1", "Physics I", "6", "80", "C2", "Physics II", "6", "75"),
        ("C3", "Algebra", "5", "70", "C4", "Analysis", "5", "72"),
        ("", "Total", "11", "", "", "Total", "11", ""),
    )
    reading = _read(agency_a, membership_a, fake_store, _page(table))
    assert [course.title for course in reading.content.courses] == [
        "Physics I",
        "Algebra",
        "Physics II",
        "Analysis",
    ]
    assert [row.kind for row in reading.rows] == [
        "header", "semester_heading", "course", "course", "semester_total",
    ] * 2


def test_rows_are_asked_forty_at_a_time(agency_a, membership_a, fake_store):
    table = (HEADER, *((f"C{i}", f"Course {i}", "5", "80") for i in range(90)))
    states = []
    reading = _read(agency_a, membership_a, fake_store, _page(table), client=_jev(states=states))
    assert len(reading.content.courses) == 90
    assert [len(state.get("rows", ())) for state in states] == [0, 40, 40, 11]


@pytest.mark.parametrize("content", [b"PK\x03\x04 a docx", b"GIF89a"])
def test_only_a_pdf_png_or_jpeg_is_read(agency_a, membership_a, fake_store, content):
    with pytest.raises(UnsupportedUpload):
        _read(agency_a, membership_a, fake_store, content=content)


def test_an_oversized_upload_is_refused(agency_a, membership_a, fake_store):
    with pytest.raises(UnsupportedUpload):
        _read(agency_a, membership_a, fake_store, content=_PDF + b"\x00" * 10_000_001)


def test_a_page_the_gate_refuses_is_passed_on(agency_a, membership_a, fake_store):
    with tenant_scope(agency_a.id):
        document = _document(agency_a, membership_a, fake_store)
    with patch("apps.documents.transcript.read_pages", side_effect=PageRefused("blurred", 2)):
        with pytest.raises(PageRefused):
            read_transcript(document=document, names=frozenset(), store=fake_store, client=_jev())


def test_reading_is_rate_limited_before_the_ocr_runs(agency_a, membership_a, fake_store):
    with tenant_scope(agency_a.id):
        document = _document(agency_a, membership_a, fake_store)
    with patch("apps.documents.transcript.read_pages", return_value=(_page(COURSES),)) as ocr:
        for _ in range(10):
            read_transcript(document=document, names=frozenset(), store=fake_store, client=_jev())
        with pytest.raises(TranscriptRateLimited):
            read_transcript(document=document, names=frozenset(), store=fake_store, client=_jev())
    assert ocr.call_count == 10


def test_a_printed_number_is_read_with_either_decimal_mark():
    assert number("7,5") == number("7.5") == Decimal("7.5")
    assert number("240") == Decimal("240")
    assert number("6 AKTS") is None and number("") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript.py -q`
Expected: FAIL — `ImportError: cannot import name 'Highlight' from 'apps.documents.transcript'`

- [ ] **Step 3: Write the questions**

Create `apps/documents/transcript_questions.py`. The Jev contract (spec 2026-09-22 §3.1a) binds every line: one judgment per question, `inspect` paths instead of prose indirection, an `other`/`none` way out on every Choice, Nouls phrased so yes is high, examples in the launch markets' own languages.

```python
"""Every question Jev is asked about a transcript, and the bar that makes an answer a highlight.

The Jev contract (spec 2026-09-22 typed-decisions, 3.1a) is followed to the letter: one judgment
per question; each question points at a named part of the state with `inspect`; every Choice has
a way out (`other` / `none`); a Noul is phrased so that yes is the high value. Jev only ever
chooses -- a column's kind, a row's kind, which printed line or number is which -- and code
copies what it chose (apps/documents/transcript.py). It never counts, sums or converts.
"""

from __future__ import annotations

from apps.reference_data import ISO_3166_ALPHA2_CODES
from apps.research.decisions import Choice, Noul, Question

#: The decision ID the layer routes and records these under. It never reaches the model.
DECISION = "transcript"

#: ponytail: one bar for every question, untuned -- the vendor's "act automatically" bar for a
#: high-stakes Choice (research note 2026-09-23, rule 11). Spec 7 gate 1 tunes it per question
#: on the labelled transcript set; until then an answer below it is highlighted, never dropped.
UNSURE_BELOW = 0.85

COLUMN_KINDS = ("course_title", "credits", "grade", "course_code", "hours", "semester", "other")
ROW_KINDS = (
    "course",
    "semester_heading",
    "semester_total",
    "overall_total",
    "header",
    "other",
)
CREDIT_SYSTEMS = ("ECTS", "US_SEMESTER_HOUR", "LOCAL", "UNKNOWN")
NONE = "none"


def column(index: int) -> Choice:
    return Choice(
        question="What does this column of the transcript's course table hold?",
        options=COLUMN_KINDS,
        criteria={
            "course_title": "the name of each course, module or subject",
            "credits": {
                "what": "the credit value of each course: ECTS, AKTS, kredi, credits, "
                "credit hours or зачётные единицы",
                "not_for": "hours of teaching, or a grade",
            },
            "grade": {
                "what": "the mark the student received: a number, a letter such as AA or B+, "
                "or a word such as 'отлично' or 'yaxşı'",
                "not_for": "credits",
            },
            "course_code": "a short identifier of each course, such as CHEM101 or 0301101",
            "hours": "hours of teaching or study: saat, часы, hours",
            "semester": "the semester, term or year each course was taken in",
            "other": "anything else, or a column mixing several of the above",
        },
        inspect=f"`columns[{index}].cells`",
    )


def row_kind(index: int) -> Choice:
    return Choice(
        question="What kind of row of a transcript's course table is this?",
        options=ROW_KINDS,
        criteria={
            "course": "one course or module the student took, with its own title",
            "semester_heading": {
                "what": "a heading naming a semester, term or year",
                "examples": ["1st semester", "Güz Dönemi", "I kurs, II semestr", "1 семестр"],
            },
            "semester_total": {
                "what": "a row totalling the credits or grades of one semester only",
                "not_for": "the total of the whole degree",
            },
            "overall_total": "a row totalling the credits or grades of the whole degree",
            "header": "the table's column titles",
            "other": "anything else: a note, a signature, an empty or unreadable row",
        },
        inspect=f"`rows[{index}]`",
    )


def in_progress(index: int) -> Noul:
    return Noul(
        question="Does this row say the course is still in progress, not yet completed?",
        criteria={
            "true": "the row prints a word or mark for it: 'in progress', 'IP', 'devam ediyor', "
            "'davam edir', 'изучается'",
            "false": "the row has a final grade, or simply has no grade printed",
        },
        inspect=f"`rows[{index}]`",
    )


def failed(index: int) -> Noul:
    return Noul(
        question="Does this row record a failed attempt at the course?",
        criteria={
            "true": "a failing grade such as F, FF, FD, 'kəsr', 'неудовлетворительно', "
            "or a word such as failed, repeat or retake",
            "false": "a passing grade, or no grade",
        },
        inspect=f"`rows[{index}]`",
    )


def _pick(question: str, ids: list[str], inspect: str) -> Choice:
    return Choice(
        question=question,
        options=(*ids, NONE),
        criteria={NONE: "the transcript does not print it"},
        inspect=inspect,
    )


def transcript(lines: list[str], numbers: list[str], dates: list[str]) -> dict[str, Question]:
    """The questions about the whole transcript. A pick with no candidates is not asked.

    `lines`, `numbers` and `dates` are the candidate IDs code found; the answer is one of them
    or `none`, and code copies the candidate's text.
    """
    picks: dict[str, Question] = {
        "credit_system": Choice(
            question="Which credit system does this transcript use?",
            options=CREDIT_SYSTEMS,
            criteria={
                "ECTS": "ECTS or AKTS credits",
                "US_SEMESTER_HOUR": "semester hours or credit hours of a United States institution",
                "LOCAL": "another national or institutional credit system, such as 'kredi' "
                "without AKTS or 'кредит'",
                "UNKNOWN": "the transcript does not say",
            },
        ),
        "country": Choice(
            question="In which country is the institution that issued this transcript? "
            "Answer with its ISO 3166 two-letter code.",
            options=(*sorted(ISO_3166_ALPHA2_CODES), NONE),
            criteria={NONE: "the transcript does not show it"},
            inspect="`lines`",
        ),
    }
    if lines:
        picks |= {
            "institution": _pick(
                "Which line names the university or institution that issued this transcript?",
                lines,
                "`lines`",
            ),
            "qualification": _pick(
                "Which line names the degree or qualification, such as Bachelor of Science, "
                "Bakalavr, Lisans or Бакалавр?",
                lines,
                "`lines`",
            ),
            "field": _pick(
                "Which line names the field or subject of study, such as Chemistry, Kimya "
                "or Химия?",
                lines,
                "`lines`",
            ),
        }
    if numbers:
        picks |= {
            "overall_grade": _pick(
                "Which number is the student's overall grade or grade point average?",
                numbers,
                "`numbers`",
            ),
            "grading_scale": _pick(
                "Which number is the highest grade possible on the scale the overall grade is "
                "given on -- the 4 in '3.45 / 4.00', the 100 in a 100-point scale?",
                numbers,
                "`numbers`",
            ),
            "total_credits": _pick(
                "Which number is the total credits of the whole degree or transcript?",
                numbers,
                "`numbers`",
            ),
        }
    if dates:
        picks |= {
            "completed_on": _pick(
                "Which date is the date the degree was completed or awarded?", dates, "`dates`"
            ),
            "expected_completion": _pick(
                "Which date is a planned or expected graduation date?", dates, "`dates`"
            ),
        }
    return picks
```

- [ ] **Step 4: Rewrite the reader**

Replace `apps/documents/transcript.py`:

```python
"""Read an uploaded transcript: OCR cuts, code finds the candidates, Jev picks, code copies.

No generative model reads a transcript (spec 3.1, T19). The OCR program (ocr.py) returns each
page's text lines and table grids. Code drops everything that identifies the student, then turns
the rest into candidates: table columns, table rows, the other lines, and the numbers and dates
on those lines. Jev answers closed questions about them (transcript_questions.py) through the
decision layer's one client, and code copies the chosen cell or span verbatim. A Jev answer only
ever chooses which printed text is copied; code does every count and sum (transcript_checks.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from apps.concierge.documents import ReadableObjectStore, open_document
from apps.concierge.models import DocumentVersion
from apps.ratelimit import rate_limited
from apps.research.decisions import Answer, Client, ask
from apps.tenancy.models import Membership

from . import transcript_questions as questions
from .credits import CreditUnit, to_ects
from .ingestion import UnsupportedUpload
from .models import VerifiedFact
from .ocr import OcrPage, read_pages

_MAX_UPLOAD_BYTES = 10_000_000
#: One OCR run and its handful of Jev requests per reading; ten an hour is a student re-uploading
#: after a rescan request, not a loop.
_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 3600
#: Cells shown per column when Jev is asked what the column holds: the header and enough values.
_CELLS_PER_COLUMN = 20
#: Three questions per row, 40 rows a request: 16-18k tokens by decisions.py's own estimate on
#: the real OCR output of four sample transcripts (2026-09-26), inside Jev's 64k. The first
#: request -- columns, lines, numbers, dates -- measured 3-12k.
_ROWS_PER_REQUEST = 40
_MAX_ROWS = 240
_MAX_CANDIDATES = 200
_MAX_DATES = 50

RowKind = Literal[
    "course", "semester_heading", "semester_total", "overall_total", "header", "other"
]
CourseStatus = Literal["COMPLETED", "IN_PROGRESS", "SUPERSEDED_ATTEMPT"]

#: A line or table row carrying one of these is never sent anywhere (owner, 2026-09-26: TypeSafe
#: and OpenRouter see course tables, not the student). A label ending its line takes the next line
#: with it -- that is where its value is printed.
_PERSONAL_LABEL = re.compile(
    r"family name|given name|first name|last name|surname|full name|patronymic|"
    r"date of birth|place of birth|birth date|student (?:id|no|number)|identification number|"
    r"passport|national id|^\s*(?:student\s+)?name\s*:|"
    r"soyad|doğum|dogum|kimlik|öğrenci no|öğrenci numara|atasının adı|baba adı|^\s*adı\s*:|"
    r"şəxsiyyət|fin kod|"
    r"фамилия|\bимя\b|отчество|\bф\.?\s?и\.?\s?о\b|дата рождения|место рождения|паспорт|"
    r"зач[её]тной книжки",
    re.IGNORECASE,
)
#: Six digits or more: a student, diploma, passport or ID number. A line holding one is dropped;
#: in a table cell it is masked, because a numeric course code (0301101) is one too.
_ID_NUMBER = re.compile(r"\d{6,}")
#: ponytail: numeric dates only. "16 марта 2026 года" is no candidate, so a transcript printing
#: its dates in words gets the graduation question (Task 5); add month names when one needs it.
_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMBER = re.compile(r"\b\d{1,4}(?:[.,]\d{1,3})?\b")


class TranscriptCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    #: As printed, in the transcript's own unit. Never bounded here: an impossible figure is a
    #: failed range check the student sees, not a reading that fails to load.
    credits: Decimal | None = None
    grade: str | None = Field(default=None, max_length=50)
    #: A failed attempt later retaken is kept by the reader and dropped by academic_record, so
    #: the credits of one course are never counted twice.
    status: CourseStatus


class TranscriptContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Empty when no printed line was chosen: the record then fails AcademicRecord and is not
    #: prefilled, so the student types it rather than confirms a blank.
    institution: str = Field(default="", max_length=200)
    country_code: str = Field(default="", pattern=r"^([A-Z]{2})?$")
    qualification: str = Field(default="", max_length=100)
    field: str = Field(default="", max_length=200)
    overall_grade: str | None = Field(default=None, max_length=50)
    grading_scale: str | None = Field(default=None, max_length=100)
    credit_unit: CreditUnit
    #: ponytail: never set by the reader -- no measured transcript prints a full-time year's
    #: load. A LOCAL unit therefore converts to no ECTS figure; spec 4.4 adds named systems.
    local_credits_per_year: Decimal | None = None
    courses: tuple[TranscriptCourse, ...] = Field(default=(), max_length=150)
    completed_on: date | None = None
    expected_completion: date | None = None


class Highlight(BaseModel):
    """One thing the summary screen marks (spec T2): a failed check, a check that could not run,
    or an answer Jev was unsure of. Never a spelling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "credit_total_mismatch",
        "credit_total_not_checked",
        "grade_above_scale",
        "credit_out_of_range",
        "mixed_script",
        "unsure",
    ]
    #: A row (ref: its index), a semester (ref: the index of the row printing its total), the
    #: whole transcript (ref: empty or what was unsure), or a field of the record (ref: its name).
    scope: Literal["row", "semester", "transcript", "field"]
    ref: str = ""


@dataclass(frozen=True)
class Row:
    """One course-table row as code cut it and Jev labelled it.

    `index` is its place in reading order -- what a highlight on it names. Cells are verbatim;
    a column the table does not have reads as "".
    """

    index: int
    kind: RowKind
    title: str
    credits: str
    grade: str
    status: CourseStatus | None


@dataclass(frozen=True)
class Reading:
    content: TranscriptContent
    rows: tuple[Row, ...]
    #: A total-credits figure printed outside any table, when Jev found one.
    total_credits_line: str | None
    #: Answers below questions.UNSURE_BELOW, as highlights.
    doubts: tuple[Highlight, ...]


class TranscriptRateLimited(RuntimeError):
    pass


def number(text: str) -> Decimal | None:
    """A printed number as a Decimal -- '6', '7.5', '7,5' -- or None for anything else."""
    match = re.fullmatch(r"\s*(\d{1,4})(?:[.,](\d{1,3}))?\s*", text)
    if match is None:
        return None
    return Decimal(match[1] if match[2] is None else f"{match[1]}.{match[2]}")


def personal_names(student: Membership) -> frozenset[str]:
    """The student's name words, from the account and from any identity fact read off a CV.

    Called inside a tenant-scoped transaction: VerifiedFact is behind row-level security.
    """
    names = [student.user.get_full_name()]
    for fact in VerifiedFact.objects.filter(
        student=student, category=VerifiedFact.Category.IDENTITY
    ):
        if isinstance(fact.payload, dict):
            names.append(str(fact.payload.get("full_name", "")))
    return frozenset(
        word.casefold() for name in names for word in re.findall(r"\w+", name) if len(word) >= 2
    )


#: The word or two a document prints right after one of its own labels: "Фамилия Иванов",
#: "Surname: Aliyev". Learned first, so a page header repeating the name without a label --
#: every page of the Russian specimen carries one, in Cyrillic, which no Latin account name
#: matches -- is recognised too. A value starting with a digit (a birth date) teaches nothing.
_VALUE_AFTER_LABEL = re.compile(r"\w*[\s:.]+([^\W\d_]{2,})(?:\s+([^\W\d_]{2,}))?")


def _learned(texts: list[str]) -> set[str]:
    words: set[str] = set()
    for text in texts:
        for label in _PERSONAL_LABEL.finditer(text):
            value = _VALUE_AFTER_LABEL.match(text, label.end())
            if value is not None:
                words |= {word.casefold() for word in value.groups() if word}
    return words


def _names_in(text: str, names: frozenset[str]) -> bool:
    # Two of the student's name words, never one: "Ali" alone is also Azerbaijani for "higher",
    # and "Ali riyaziyyat" is a course.
    found = names & set(re.findall(r"\w+", text.casefold()))
    return bool(names) and len(found) >= min(2, len(names))


def _minimised(pages: tuple[OcrPage, ...], names: frozenset[str]) -> tuple[
    list[str], list[list[list[str]]]
]:
    every = [line for page in pages for line in page.lines]
    every += [cell for page in pages for table in page.tables for row in table for cell in row]
    names = names | _learned(every)
    lines: list[str] = []
    skip_next = False
    for line in (line for page in pages for line in page.lines):
        if skip_next:
            skip_next = False
            continue
        label = _PERSONAL_LABEL.search(line)
        if label and not line[label.end() :].strip(" :.-\t"):
            skip_next = True
        if label or _ID_NUMBER.search(line) or _names_in(line, names):
            continue
        lines.append(line)
    tables = [
        [
            [_ID_NUMBER.sub("#", cell) for cell in row]
            for row in table
            if not any(_PERSONAL_LABEL.search(cell) for cell in row)
            and not _names_in(" ".join(row), names)
        ]
        for page in pages
        for table in page.tables
    ]
    return lines, [table for table in tables if table]


def _candidates(lines: list[str]) -> tuple[list[tuple[str, int]], list[tuple[date, str, int]]]:
    """Numbers and dates printed on the lines, each with the index of its line."""
    numbers: list[tuple[str, int]] = []
    dates: list[tuple[date, str, int]] = []
    for index, line in enumerate(lines):
        for match in _DATE.finditer(line):
            if match[1]:
                day, month, year = match[1], match[2], match[3]  # day first: AZ, TR, RU
            else:
                day, month, year = match[6], match[5], match[4]
            try:
                dates.append((date(int(year), int(month), int(day)), match[0], index))
            except ValueError:
                continue
        numbers += [(found, index) for found in _NUMBER.findall(_DATE.sub(" ", line))]
    return numbers[:_MAX_CANDIDATES], dates[:_MAX_DATES]


def _groups(kinds: list[str]) -> list[list[int]]:
    """A table's columns in course blocks: one block, or one per semester printed side by side.

    Only a second title column starts a block, and it starts where the first block's layout puts
    it: [code, title, credits, grade, code, title, credits, grade] splits before the second code.
    A repeated credits column does not split -- NKU prints ECTS and local credits side by side
    (measured 2026-09-26), and the first, ECTS, is the one read.
    """
    titles = [position for position, kind in enumerate(kinds) if kind == "course_title"]
    starts = [0, *(title - titles[0] for title in titles[1:])] if titles else [0]
    ends = [*starts[1:], len(kinds)]
    return [list(range(start, end)) for start, end in zip(starts, ends, strict=True)]


@dataclass(frozen=True)
class _Cut:
    cells: list[str]
    #: column kind -> position in `cells`, first occurrence
    where: dict[str, int]

    def cell(self, kind: str) -> str:
        return self.cells[self.where[kind]] if kind in self.where else ""


def _course_rows(tables: list[list[list[str]]], kinds: list[list[str]]) -> list[_Cut]:
    """Every row of every course block, block after block, so a side-by-side layout reads its
    left semester to the end before its right one."""
    cut: list[_Cut] = []
    for table, table_kinds in zip(tables, kinds, strict=True):
        for group in _groups(table_kinds):
            where: dict[str, int] = {}
            for offset, position in enumerate(group):
                where.setdefault(table_kinds[position], offset)
            if "course_title" not in where:
                continue
            cut += [_Cut([row[position] for position in group], where) for row in table]
    return cut


def _unsure(answer: Answer) -> bool:
    return answer.confidence < questions.UNSURE_BELOW


def _norm(title: str) -> str:
    return " ".join(title.casefold().split())


def _clip(text: str, limit: int) -> str:
    # Verbatim, and cut only where a field cannot hold more: never text the page did not print.
    return text[:limit]


def read_transcript(
    *,
    document: DocumentVersion,
    names: frozenset[str],
    store: ReadableObjectStore | None = None,
    client: Client | None = None,
) -> Reading:
    """Read one scanned-clean transcript. Raises PageRefused for a page to rescan.

    open_document refuses anything GuardDuty has not marked AVAILABLE, so it stays first -- the
    ordering ingest_uploaded_cv depends on. The rate limit precedes the OCR, the expensive part.
    """
    content = open_document(document, store=store)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise UnsupportedUpload("upload is larger than a transcript")
    if not content.startswith((b"%PDF", b"\x89PNG", b"\xff\xd8\xff")):
        raise UnsupportedUpload("a transcript is read from a PDF, PNG or JPEG")
    if rate_limited(
        "transcript_reading",
        document.student_id,
        limit=_RATE_LIMIT,
        window_seconds=_RATE_WINDOW_SECONDS,
    ):
        raise TranscriptRateLimited("transcript reading rate limit exceeded")
    lines, tables = _minimised(read_pages(document, content), names)
    lines = lines[:_MAX_CANDIDATES]
    numbers, dates = _candidates(lines)

    columns = [
        (t, position, [row[position] for row in table][:_CELLS_PER_COLUMN])
        for t, table in enumerate(tables)
        for position in range(len(table[0]))
        if any(row[position] for row in table)
    ]
    first = ask(
        {
            "columns": [{"cells": cells} for _, _, cells in columns],
            "lines": [{"id": f"l{i}", "text": line} for i, line in enumerate(lines)],
            "numbers": [
                {"id": f"n{i}", "text": text, "line": f"l{k}"}
                for i, (text, k) in enumerate(numbers)
            ],
            "dates": [
                {"id": f"d{i}", "text": text, "line": f"l{k}"}
                for i, (_, text, k) in enumerate(dates)
            ],
        },
        {f"column:{k}": questions.column(k) for k in range(len(columns))}
        | questions.transcript(
            [f"l{i}" for i in range(len(lines))],
            [f"n{i}" for i in range(len(numbers))],
            [f"d{i}" for i in range(len(dates))],
        ),
        decision=questions.DECISION,
        client=client,
    )
    doubts: dict[Highlight, None] = {}
    kinds = [["other"] * len(table[0]) for table in tables]
    for k, (t, position, _) in enumerate(columns):
        kinds[t][position] = str(first[f"column:{k}"].value)
        if _unsure(first[f"column:{k}"]):
            doubts[Highlight(kind="unsure", scope="transcript", ref="columns")] = None
    for qid, answer in first.items():
        if not qid.startswith("column:") and _unsure(answer):
            doubts[Highlight(kind="unsure", scope="field", ref=qid)] = None

    cut = _course_rows(tables, kinds)
    if len(cut) > _MAX_ROWS:
        raise UnsupportedUpload("more table rows than one transcript holds")
    labels: dict[str, Answer] = {}
    for start in range(0, len(cut), _ROWS_PER_REQUEST):
        batch = cut[start : start + _ROWS_PER_REQUEST]
        answered = ask(
            {"rows": [row.cells for row in batch]},
            {
                f"{name}:{i}": build(i)
                for i in range(len(batch))
                for name, build in (
                    ("kind", questions.row_kind),
                    ("in_progress", questions.in_progress),
                    ("failed", questions.failed),
                )
            },
            decision=questions.DECISION,
            client=client,
        )
        for qid, answer in answered.items():
            name, local = qid.split(":")
            labels[f"{name}:{start + int(local)}"] = answer
            if _unsure(answer):
                doubts[Highlight(kind="unsure", scope="row", ref=str(start + int(local)))] = None

    course_titles = [
        _norm(row.cell("course_title")) if labels[f"kind:{i}"].value == "course" else ""
        for i, row in enumerate(cut)
    ]
    rows = []
    for i, row in enumerate(cut):
        kind = cast(RowKind, labels[f"kind:{i}"].value)
        status: CourseStatus | None = None
        if kind == "course":
            if labels[f"failed:{i}"].value is True and course_titles[i] in course_titles[i + 1 :]:
                status = "SUPERSEDED_ATTEMPT"
            elif labels[f"in_progress:{i}"].value is True:
                status = "IN_PROGRESS"
            else:
                status = "COMPLETED"
        if kind == "course" and not row.cell("course_title").strip():
            # A course row with no title is a cut that went wrong (a merged or shifted row);
            # it stays in the credit sums, and the student is shown where.
            doubts[Highlight(kind="unsure", scope="row", ref=str(i))] = None
        rows.append(
            Row(i, kind, row.cell("course_title"), row.cell("credits"), row.cell("grade"), status)
        )

    def picked(qid: str) -> str | None:
        answer = first.get(qid)
        return None if answer is None or answer.value == questions.NONE else str(answer.value)

    def line(qid: str, limit: int) -> str:
        chosen = picked(qid)
        if chosen is None:
            return ""
        text = lines[int(chosen[1:])]
        label, _, value = text.partition(":")
        return _clip((value if value.strip() else label).strip(), limit)

    def printed(qid: str) -> str | None:
        chosen = picked(qid)
        return None if chosen is None else numbers[int(chosen[1:])][0]

    def dated(qid: str) -> date | None:
        chosen = picked(qid)
        return None if chosen is None else dates[int(chosen[1:])][0]

    courses = tuple(
        TranscriptCourse(
            title=_clip(row.title, 200),
            credits=number(row.credits),
            grade=_clip(row.grade, 50) or None,
            status=row.status,
        )
        for row in rows
        if row.kind == "course" and row.status is not None and row.title.strip()
    )
    if len(courses) > 150:
        raise UnsupportedUpload("more courses than one transcript holds")
    country = picked("country")
    return Reading(
        content=TranscriptContent(
            institution=line("institution", 200),
            country_code=country or "",
            qualification=line("qualification", 100),
            field=line("field", 200),
            overall_grade=printed("overall_grade"),
            grading_scale=printed("grading_scale"),
            credit_unit=cast(CreditUnit, first["credit_system"].value),
            courses=courses,
            completed_on=dated("completed_on"),
            expected_completion=dated("expected_completion"),
        ),
        rows=tuple(rows),
        total_credits_line=printed("total_credits"),
        doubts=tuple(doubts),
    )


def _ects(content: TranscriptContent, course: TranscriptCourse) -> Decimal | None:
    if course.credits is None:
        return None
    ects = to_ects(
        course.credits, content.credit_unit, local_credits_per_year=content.local_credits_per_year
    )
    # The profile's CourseRecord holds at most 100. A larger figure has already failed the range
    # check the student sees; the record carries "unknown" rather than refusing the whole reading.
    return ects if ects is not None and ects <= 100 else None


def academic_record(content: TranscriptContent) -> dict[str, object]:
    courses = [
        {
            "title": course.title,
            "ects": None if (ects := _ects(content, course)) is None else str(ects),
            "grade": course.grade,
            "in_progress": course.status == "IN_PROGRESS",
        }
        for course in content.courses
        if course.status != "SUPERSEDED_ATTEMPT"
    ]
    payload = {
        "institution": content.institution,
        "country_code": content.country_code,
        "qualification": content.qualification,
        "field": content.field,
        "grade": content.overall_grade or "not stated",
        "grading_scale": content.grading_scale or "not stated",
        "completed_on": content.completed_on,
        "expected_completion": content.expected_completion,
        "courses": courses,
    }
    return cast("dict[str, object]", json.loads(json.dumps(payload, default=str)))
```

Three decisions in it that a reviewer should see stated:
- **Personal data never leaves.** A line carrying a personal label is dropped (and the next line with it when the label ends the line — that is where its value is printed); a line with a run of six digits or more is dropped; a line holding two of the student's name words is dropped — two, never one, because "Ali" is also Azerbaijani for "higher". Name words come from the account, from CV-read identity facts, and from the document itself: the word or two printed right after its own labels, so the Russian specimen's unlabelled "Иванов Иван Иванович" header on every page is caught. In a table, a row with a label or two name words is dropped whole; a six-digit run inside a cell is masked, because a numeric course code is one too. `# ponytail:`-level limits, stated in the report: a name transliterated differently from every form the account and the document give is not matched; a surname that is also a common word drops the rows it appears in, which the credit-total check then flags.
- **A second title column starts a second course block; nothing else does.** Side-by-side semesters split into blocks read one after the other; a repeated credits column (NKU's ECTS beside local credits, measured) stays in one block and the first is read.
- **Nothing is bounded into failure.** An OCR'd figure no course can have is kept as printed and fails a range check (Task 2c) the student sees; `academic_record` carries such a course's ECTS as unknown rather than letting `AcademicRecord` refuse the whole reading. Only a transcript with more rows or courses than one transcript holds is refused (`UnsupportedUpload`).

- [ ] **Step 5: Drop the worker test built on the old shape**

In `tests/documents/test_transcript_worker.py`, delete `_content()`, `test_a_reading_stores_the_academic_record_and_reads_back_in_scope`, and the now-unused imports `TranscriptContent`, `TranscriptCourse`, `academic_record`, `uncertain_fields` (and `TranscriptReading` only if nothing else in the file uses it — `test_a_clean_transcript_waits_for_its_reader_and_never_reaches_cv_ingestion` does, so it stays). Task 3c replaces this file; the reading's stored round trip is pinned there.

- [ ] **Step 6: Run to verify they pass, then the suite**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript.py -q`
Expected: `16 passed`. The `_clear_rate_limit_cache` autouse fixture in `tests/documents/conftest.py` resets the limiter between tests.

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest -q`
Expected: all pass. `TranscriptReading.uncertain` and the prefill still use the old field until Task 3b; nothing on this branch calls `read_transcript` until Task 3c.

- [ ] **Step 7: Lint, types, commit**

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv run ruff check apps/documents tests/documents && uv run mypy apps config
git -C /home/orkhan/Desktop/tailored-programmes add apps/documents/transcript.py apps/documents/transcript_questions.py tests/documents/test_transcript.py tests/documents/test_transcript_worker.py
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(documents): read a transcript -- code cuts, Jev picks, code copies

No generative model reads a transcript. Code drops every line and row naming
the student, a birth date or an ID number -- learning the name from the
document's own labels -- then asks Jev closed questions through the decision
layer's one client and copies the chosen cells verbatim. A failed attempt is
superseded only when code finds its title again later; an unsure answer
becomes a highlight, never a guess.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2c: The checks, the key numbers and the highlights

**What this task does.** Spec §3.1, "What the reader checks", in code: course credits against every printed credit total — per semester and overall, exact after decimal-comma handling, accepting a total that counts every course, every course but a superseded attempt, or completed courses only; a transcript printing no total says **not checked**, never clean. The overall grade against the stated scale's maximum; each course's credits against 0–30. A word mixing Latin and Cyrillic letters. Averages are not checked. **A failed check is shown, never repaired**: nothing here writes into the reading. Course grades are not checked against the scale, deliberately: the stated scale is the overall grade's, and Turkish transcripts print letter grades per course beside a 4-point average — checking them against it would flag every row.

**Files:**
- Create: `apps/documents/transcript_checks.py`
- Test: `tests/documents/test_transcript_checks.py`

**Interfaces:**
- Consumes: `Reading`, `Row`, `Highlight`, `number`, `TranscriptContent` (Task 2b); `CreditUnit` (Task 1).
- Produces: `KeyNumbers(overall_grade: str | None, grading_scale: str | None, total_credits: str | None, total_credits_printed: bool, credit_unit: CreditUnit, graduation_date: date | None)` (pydantic, `extra="forbid"`); `highlights(reading: Reading) -> tuple[Highlight, ...]` — failed checks, the not-checked marker, then the reader's unsure answers, each once; `key_numbers(reading: Reading) -> KeyNumbers`. Every highlight names its scope: a row by index, a semester by the index of the row printing its total, the transcript, or a field by name.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date

from apps.documents.transcript import Highlight, Reading, Row, TranscriptContent
from apps.documents.transcript_checks import highlights, key_numbers


def _course(index, title, credits, status="COMPLETED", grade="80"):
    return Row(index, "course", title, credits, grade, status)


def _row(index, kind, credits=""):
    return Row(index, kind, "", credits, "", None)


def _reading(*rows, total_line=None, doubts=(), grade="88", scale="100", **content):
    return Reading(
        content=TranscriptContent(
            institution="Baku State University",
            overall_grade=grade,
            grading_scale=scale,
            credit_unit="ECTS",
            expected_completion=date(2027, 6, 30),
            **content,
        ),
        rows=rows,
        total_credits_line=total_line,
        doubts=doubts,
    )


def _two_semesters(first_total="11", overall="31"):
    return (
        _row(0, "semester_heading"),
        _course(1, "Organic Chemistry I", "6"),
        _course(2, "Programming", "5"),
        _row(3, "semester_total", first_total),
        _row(4, "semester_heading"),
        _course(5, "Physical Chemistry", "5"),
        _course(6, "Thesis", "15", status="IN_PROGRESS", grade=""),
        _row(7, "semester_total", "20"),
        _row(8, "overall_total", overall),
    )


def test_totals_that_add_up_raise_nothing():
    assert highlights(_reading(*_two_semesters())) == ()


def test_a_dropped_row_fails_its_semester_and_the_overall_total():
    rows = [row for row in _two_semesters() if row.index != 2]  # OCR dropped "Programming"
    assert highlights(_reading(*rows)) == (
        Highlight(kind="credit_total_mismatch", scope="semester", ref="3"),
        Highlight(kind="credit_total_mismatch", scope="transcript", ref="8"),
    )


def test_two_courses_merged_into_one_row_fail_the_total():
    """BEUN's failure mode: two courses on one row carrying one set of credits."""
    rows = (
        _course(0, "Organic Chemistry I Programming", "6"),
        _row(1, "semester_total", "11"),
    )
    assert Highlight(kind="credit_total_mismatch", scope="semester", ref="1") in highlights(
        _reading(*rows)
    )


def test_a_transcript_printing_no_total_says_not_checked_never_clean():
    rows = (_course(0, "Organic Chemistry I", "6"), _course(1, "Programming", "5"))
    assert highlights(_reading(*rows)) == (
        Highlight(kind="credit_total_not_checked", scope="transcript"),
    )


def test_a_total_counting_completed_courses_only_passes():
    rows = (
        _course(0, "Programming", "5", status="SUPERSEDED_ATTEMPT", grade="FF"),
        _course(1, "Programming", "5"),
        _course(2, "Thesis", "15", status="IN_PROGRESS", grade=""),
        _row(3, "overall_total", "5"),
    )
    assert highlights(_reading(*rows)) == ()


def test_a_total_printed_outside_the_table_is_checked_too():
    rows = (_course(0, "Organic Chemistry I", "6"),)
    assert highlights(_reading(*rows, total_line="240")) == (
        Highlight(kind="credit_total_mismatch", scope="transcript", ref="total_credits"),
    )


def test_a_grade_above_its_scale_is_highlighted_and_one_within_it_is_not():
    rows = (_course(0, "Organic Chemistry I", "6"), _row(1, "overall_total", "6"))
    assert highlights(_reading(*rows, grade="150", scale="100")) == (
        Highlight(kind="grade_above_scale", scope="field", ref="overall_grade"),
    )
    assert highlights(_reading(*rows, grade="3,45", scale="4.00")) == ()


def test_a_sixty_credit_course_is_out_of_range():
    rows = (_course(0, "Organic Chemistry I", "60"), _row(1, "overall_total", "60"))
    assert highlights(_reading(*rows)) == (
        Highlight(kind="credit_out_of_range", scope="row", ref="0"),
    )


def test_a_word_mixing_latin_and_cyrillic_letters_is_highlighted():
    rows = (
        _course(0, "Rуsсkий язык", "5"),  # the у and с are Cyrillic
        _course(1, "Azərbaycan tarixi", "5"),  # ə is a Latin letter
        _course(2, "Русский язык", "5"),
        _row(3, "overall_total", "15"),
    )
    assert highlights(_reading(*rows, field="Хiмия")) == (
        Highlight(kind="mixed_script", scope="field", ref="field"),
        Highlight(kind="mixed_script", scope="row", ref="0"),
    )


def test_an_unsure_answer_is_listed_once_after_the_checks():
    doubt = Highlight(kind="unsure", scope="row", ref="1")
    rows = (_course(0, "Organic Chemistry I", "6"),)
    assert highlights(_reading(*rows, doubts=(doubt, doubt))) == (
        Highlight(kind="credit_total_not_checked", scope="transcript"),
        doubt,
    )


def test_a_failed_check_is_shown_never_repaired():
    rows = (_course(0, "Organic Chemistry I", ""), _row(1, "overall_total", "6"))
    reading = _reading(*rows)
    assert highlights(reading) == (
        Highlight(kind="credit_total_mismatch", scope="transcript", ref="1"),
    )
    assert reading.rows[0].credits == ""  # the missing credit is not filled from the total


def test_the_key_numbers_are_the_printed_ones():
    numbers = key_numbers(_reading(*_two_semesters()))
    assert numbers.model_dump() == {
        "overall_grade": "88",
        "grading_scale": "100",
        "total_credits": "31",
        "total_credits_printed": True,
        "credit_unit": "ECTS",
        "graduation_date": date(2027, 6, 30),
    }


def test_without_a_printed_total_the_key_number_is_our_sum_and_says_so():
    rows = (
        _course(0, "Organic Chemistry I", "6"),
        _course(1, "Programming", "5,5"),
        _course(2, "Thesis", "15", status="IN_PROGRESS", grade=""),
    )
    numbers = key_numbers(_reading(*rows))
    assert (numbers.total_credits, numbers.total_credits_printed) == ("11.5", False)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript_checks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.documents.transcript_checks'`

- [ ] **Step 3: Implement**

```python
"""What the summary screen shows about a reading: four numbers, and where to look.

Code checks what the document itself lets it check (spec 3.1, "What the reader checks"): credits
against every printed credit total, a value outside its scale, a word mixing Latin and Cyrillic
letters. **A failed check is shown, never repaired** -- nothing here writes a value into the
reading; filling a missing credit from a printed total would put a number on the screen the
document never showed. Averages are not checked: they are weighted, rounded and sometimes count
failed attempts, so a misread single grade barely moves them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .credits import CreditUnit
from .transcript import Highlight, Reading, Row, number

#: ponytail: one range for every credit system -- a 30-credit thesis is the largest single
#: course in the measured set, and a 60-credit "course" is a misread column. Per-unit ranges when
#: spec 4.4 names the local systems.
_MAX_COURSE_CREDITS = Decimal("30")


class KeyNumbers(BaseModel):
    """The four numbers that decide eligibility and are typed into portals (spec 3.1 step 3)."""

    model_config = ConfigDict(extra="forbid")

    overall_grade: str | None
    grading_scale: str | None
    total_credits: str | None
    #: False when no total is printed: the figure is then our sum of the completed courses'
    #: credits, and the screen says so rather than presenting it as the transcript's.
    total_credits_printed: bool
    credit_unit: CreditUnit
    graduation_date: date | None


def _credits(rows: Sequence[Row]) -> list[Decimal]:
    return [credits for row in rows if (credits := number(row.credits)) is not None]


def _sums(courses: Sequence[Row]) -> set[Decimal]:
    """What a printed total may be counting: every course, every course but a failed attempt
    later retaken, or completed courses only. Transcripts differ; a total matching none of the
    three is the one that is flagged."""
    def total(rows: Sequence[Row]) -> Decimal:
        return sum(_credits(rows), Decimal(0))

    return {
        total(courses),
        total([row for row in courses if row.status != "SUPERSEDED_ATTEMPT"]),
        total([row for row in courses if row.status == "COMPLETED"]),
    }


def _credit_totals(rows: Sequence[Row], total_line: str | None) -> Iterator[Highlight]:
    semester: list[Row] = []
    courses: list[Row] = []
    printed_totals = 0
    for row in rows:
        if row.kind == "semester_heading":
            semester = []
        elif row.kind == "course":
            semester.append(row)
            courses.append(row)
        elif row.kind == "semester_total" and (printed := number(row.credits)) is not None:
            printed_totals += 1
            if printed not in _sums(semester):
                yield Highlight(kind="credit_total_mismatch", scope="semester", ref=str(row.index))
            semester = []
    overall = [(row.credits, str(row.index)) for row in rows if row.kind == "overall_total"]
    if total_line is not None:
        overall.append((total_line, "total_credits"))
    for text, ref in overall:
        if (printed := number(text)) is None:
            continue
        printed_totals += 1
        if printed not in _sums(courses):
            yield Highlight(kind="credit_total_mismatch", scope="transcript", ref=ref)
    if printed_totals == 0:
        yield Highlight(kind="credit_total_not_checked", scope="transcript")


def _ranges(reading: Reading) -> Iterator[Highlight]:
    grade = number(reading.content.overall_grade or "")
    scale = number(reading.content.grading_scale or "")
    if grade is not None and scale is not None and grade > scale:
        yield Highlight(kind="grade_above_scale", scope="field", ref="overall_grade")
    for row in reading.rows:
        credits = number(row.credits) if row.kind == "course" else None
        if credits is not None and not Decimal(0) <= credits <= _MAX_COURSE_CREDITS:
            yield Highlight(kind="credit_out_of_range", scope="row", ref=str(row.index))


def _mixed(text: str) -> bool:
    """A word holding both Latin and Cyrillic letters -- "Rуsсkий" -- which no language writes."""
    for word in re.findall(r"\w+", text):
        scripts = {unicodedata.name(ch, "").split(" ")[0] for ch in word if ch.isalpha()}
        if {"LATIN", "CYRILLIC"} <= scripts:
            return True
    return False


def _mixed_scripts(reading: Reading) -> Iterator[Highlight]:
    content = reading.content
    for name in ("institution", "qualification", "field"):
        if _mixed(getattr(content, name)):
            yield Highlight(kind="mixed_script", scope="field", ref=name)
    for row in reading.rows:
        if row.kind == "course" and _mixed(row.title):
            yield Highlight(kind="mixed_script", scope="row", ref=str(row.index))


def highlights(reading: Reading) -> tuple[Highlight, ...]:
    """Every failed check, every check that could not run, and every unsure answer, once each."""
    found = [
        *_credit_totals(reading.rows, reading.total_credits_line),
        *_ranges(reading),
        *_mixed_scripts(reading),
        *reading.doubts,
    ]
    return tuple(dict.fromkeys(found))


def key_numbers(reading: Reading) -> KeyNumbers:
    content = reading.content
    overall = [row for row in reading.rows if row.kind == "overall_total"]
    printed = [row.credits for row in overall if number(row.credits) is not None]
    if reading.total_credits_line is not None:
        printed.append(reading.total_credits_line)
    if printed:
        total: str | None = printed[-1]
    else:
        completed = _credits([row for row in reading.rows if row.status == "COMPLETED"])
        total = str(sum(completed, Decimal(0))) if completed else None
    return KeyNumbers(
        overall_grade=content.overall_grade,
        grading_scale=content.grading_scale,
        total_credits=total,
        total_credits_printed=bool(printed),
        credit_unit=content.credit_unit,
        graduation_date=content.completed_on or content.expected_completion,
    )
```

The total credits key number is the last printed overall total (a table's overall-total row, else the line Jev picked); with none printed it is code's sum of the completed courses' credits, and `total_credits_printed` is `False` so the screen can say it is ours. That sum is arithmetic on printed cells, not a value filled from a total.

- [ ] **Step 4: Run to verify they pass**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript_checks.py tests/documents/test_transcript.py -q`
Expected: `29 passed`.

- [ ] **Step 5: Lint, types, commit**

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv run ruff check apps/documents tests/documents && uv run mypy apps config && POSTGRES_DB=tehsil_tailored uv run pytest -q
git -C /home/orkhan/Desktop/tailored-programmes add apps/documents/transcript_checks.py tests/documents/test_transcript_checks.py
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(documents): check a reading against its own totals and scale, and show -- never repair

Credits are summed against every printed total, per semester and overall; a
transcript printing none says not checked. A grade above its scale, a course
outside 0-30 credits and a word mixing Latin and Cyrillic letters are marked.
The four key numbers are the printed ones, and a total we summed says so.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A transcript upload becomes a stored reading

> **Executed, differently from Step 6 below** — `ece14a7b`, `0d1469a6`, `9203936a`. Steps 1–5 and 7–8 landed, plus `tests/documents/test_transcript_reading_rls.py`, which measures the table's isolation behind a `NOBYPASSRLS` role. Step 6 did not: with no reader built, the worker leaves a clean transcript `AVAILABLE` and never routes it to CV ingestion. Task 3b moves the stored reading onto highlights and key numbers; Task 3c routes the worker to the reader. Kept as the record; do not re-execute.

**Files:**
- Modify: `apps/concierge/models.py` (`DocumentVersion`, ~line 173) — add `kind`
- Modify: `apps/concierge/documents.py:53` — `register(..., kind="CV")`
- Modify: `apps/documents/api.py:222` — `uploads` accepts `{"kind": "CV" | "TRANSCRIPT"}`
- Modify: `apps/documents/models.py` — add `TranscriptReading`
- Modify: `apps/documents/document_worker.py` (`handle_scan_result`) — route by kind
- Modify: `apps/audit/redaction.py` — `REDACT` and `KEEP` entries
- Create: `apps/concierge/migrations/0007_documentversion_kind.py` (generated)
- Create: `apps/documents/migrations/0020_transcript_reading.py` (generated) and `0021_transcript_reading_tenant_guards.py` (hand-written)
- Test: `tests/documents/test_transcript_worker.py`

**Interfaces:**
- Consumes: `read_transcript`, `academic_record`, `uncertain_fields`, `TranscriptRateLimited` (Task 2).
- Produces: `DocumentVersion.kind` (`"CV"` default, `"TRANSCRIPT"`); `register(tenant_id, student_id, kind: str = "CV")`; model `documents.TranscriptReading(tenant, student, document, record: JSON, uncertain: JSON list, accepted: JSON | None, created_at)` — `record` is `academic_record(...)`'s output.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import patch

import pytest

from apps.concierge.documents import register
from apps.documents.document_worker import handle_scan_result
from apps.documents.models import TranscriptReading, VerifiedFact
from apps.documents.transcript import TranscriptContent, TranscriptCourse
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _content():
    return TranscriptContent(
        institution="Baku State University",
        country_code="AZ",
        qualification="BSc",
        field="Chemistry",
        overall_grade="88",
        grading_scale="0-100",
        credit_unit="ECTS",
        courses=(TranscriptCourse(title="Organic Chemistry I", credits=6, status="COMPLETED"),),
    )


def _event(document, settings):
    from apps.documents.document_worker import ScanResultEvent

    return ScanResultEvent(
        bucket_name=settings.EVIDENCE_BUCKET_NAME,
        object_key=document.object_key,
        scan_result="NO_THREATS_FOUND",
    )


def test_a_clean_transcript_is_read_into_a_reading_not_cv_facts(
    agency_a, django_user_model, settings
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "w1")
        document = register(agency_a.id, student.id, kind="TRANSCRIPT")
    with patch("apps.documents.document_worker.read_transcript", return_value=_content()) as read:
        handle_scan_result(_event(document, settings))
        handle_scan_result(_event(document, settings))  # redelivery
    assert read.call_count == 1
    with tenant_scope(agency_a.id):
        reading = TranscriptReading.objects.get(document=document)
        assert reading.record["courses"][0]["ects"] == "6.00"
        assert reading.accepted is None
        assert not VerifiedFact.objects.filter(student=student).exists()


def test_an_unreadable_transcript_is_review_required(agency_a, django_user_model, settings):
    from apps.documents.ingestion import UnsupportedUpload

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "w2")
        document = register(agency_a.id, student.id, kind="TRANSCRIPT")
    with patch(
        "apps.documents.document_worker.read_transcript", side_effect=UnsupportedUpload("x")
    ):
        handle_scan_result(_event(document, settings))
    with tenant_scope(agency_a.id):
        document.refresh_from_db()
        assert document.state == "REVIEW_REQUIRED"
        assert not TranscriptReading.objects.filter(document=document).exists()


def test_a_cv_upload_still_goes_to_cv_ingestion(agency_a, django_user_model, settings):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "w3")
        document = register(agency_a.id, student.id)
    with patch("apps.documents.document_worker.ingest_uploaded_cv") as ingest, patch(
        "apps.documents.document_worker.read_transcript"
    ) as read:
        handle_scan_result(_event(document, settings))
    assert ingest.call_count == 1 and read.call_count == 0


def test_the_upload_endpoint_refuses_an_unknown_kind(client_a_student):
    response = client_a_student.post(
        "/api/uploads", data='{"kind": "PASSPORT"}', content_type="application/json"
    )
    assert response.status_code == 400
```

Before writing the last test, read `tests/documents/test_api.py` for the fixture that gives an authenticated student client and the exact uploads URL, and use those names in place of `client_a_student` and `/api/uploads`. Also check `ScanResultEvent`'s real import path and constructor in `apps/documents/document_worker.py` and match it.

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript_worker.py -q`
Expected: FAIL — `ImportError: cannot import name 'TranscriptReading'`

- [ ] **Step 3: Add `kind` to `DocumentVersion` and `register`**

In `apps/concierge/models.py`, inside `DocumentVersion`, after `scan_result`:

```python
    #: What the student said this upload is. Routes the scanned-clean file to
    #: its reader; a CV and a transcript are read into different things.
    kind = models.CharField(
        max_length=20,
        choices=[("CV", "CV"), ("TRANSCRIPT", "Transcript")],
        default="CV",
        db_default="CV",
    )
```

In `apps/concierge/documents.py`, change `register`:

```python
def register(tenant_id: UUID, student_id: UUID, kind: str = "CV") -> DocumentVersion:
    document_id = uuid4()
    with tenant_scope(tenant_id):
        return DocumentVersion.objects.create(
            id=document_id,
            tenant_id=tenant_id,
            student_id=student_id,
            object_key=f"quarantine/{tenant_id}/{document_id}",
            kind=kind,
        )
```

In `apps/documents/api.py::uploads`, before `register(...)`:

```python
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        raise _ApiError(400, "invalid_body") from None
    kind = body.get("kind", "CV") if isinstance(body, dict) else None
    if kind not in {"CV", "TRANSCRIPT"}:
        raise _ApiError(400, "invalid_kind")
    document = register(current_tenant_id(), student.id, kind=kind)
```

(replacing the existing `document = register(current_tenant_id(), student.id)` line).

- [ ] **Step 4: Add `TranscriptReading`**

Append to `apps/documents/models.py`:

```python
class TranscriptReading(TenantScopedModel):
    """What the reader transcribed from one transcript, and what the student kept.

    `record` is the reader's version; `accepted` is the version the student
    continued with on the summary screen (spec T2). The difference between the
    two is where the reader went wrong -- the correction record the spec asks
    for, kept without a second table.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    document = models.OneToOneField("concierge.DocumentVersion", on_delete=models.PROTECT)
    record = models.JSONField()
    uncertain = models.JSONField(default=list)
    accepted = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="transcriptreading_tenant_id_uniq")
        ]
```

Run: `cd /home/orkhan/Desktop/tailored-programmes && uv run python manage.py makemigrations concierge -n documentversion_kind && uv run python manage.py makemigrations documents -n transcript_reading`

Then create `apps/documents/migrations/0021_transcript_reading_tenant_guards.py` (adjust the dependency to the generated file's real name):

```python
from django.db import migrations

TABLE = "documents_transcriptreading"

RLS_SQL = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {TABLE}
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE {TABLE}
    ADD CONSTRAINT transcriptreading_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
"""

REVERSE_SQL = f"""
ALTER TABLE {TABLE} DROP CONSTRAINT transcriptreading_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0020_transcript_reading"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
```

If the runtime role needs an explicit grant on new tables, follow what `0017` or `scripts/create_runtime_role.sql` does for `documents_narrativeinput` — grep for `narrativeinput` in `scripts/` and mirror it.

- [ ] **Step 5: Register it for erasure**

In `apps/audit/redaction.py`, add to `REDACT`:

```python
    "documents.TranscriptReading": RedactSpec("student_id", ("record", "uncertain", "accepted")),
```

and to `KEEP`:

```python
    "documents.TranscriptReading": ("created_at",),
```

Check what redaction writes into a redacted JSON field for existing entries (`VerifiedFact.payload`) and confirm `accepted` being nullable does not break it; run `tests/audit/test_redaction_classification.py`.

- [ ] **Step 6: Route by kind in the worker**

In `apps/documents/document_worker.py`, import at the top:

```python
from .models import TranscriptReading
from .transcript import TranscriptRateLimited, academic_record, read_transcript, uncertain_fields
```

In `handle_scan_result`, after `if document.state != "AVAILABLE": return`, insert before the VerifiedFact idempotency check:

```python
        if document.kind == "TRANSCRIPT":
            _read_transcript(document, event.object_key)
            return
```

and add the helper:

```python
def _read_transcript(document: DocumentVersion, object_key: str) -> None:
    if TranscriptReading.objects.filter(document=document).exists():
        logger.info("DocumentScanAlreadyIngested document=%s", document.id)
        return
    try:
        content = read_transcript(document=document, student=document.student)
    except (UnsupportedUpload, TranscriptRateLimited) as error:
        logger.warning(
            "TranscriptReadRefused document=%s key=%s reason=%s",
            document.id,
            object_key,
            type(error).__name__,
        )
        document.state = "REVIEW_REQUIRED"
        document.save(update_fields=["state"])
        return
    if content is None:
        logger.warning("TranscriptReadEmpty document=%s", document.id)
        document.state = "REVIEW_REQUIRED"
        document.save(update_fields=["state"])
        return
    TranscriptReading.objects.create(
        student=document.student,
        document=document,
        record=academic_record(content),
        uncertain=list(uncertain_fields(content)),
    )
```

- [ ] **Step 7: Run to verify it passes, plus the guards**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript_worker.py tests/audit/test_redaction_classification.py tests/tenancy/test_database_isolation.py tests/documents/test_api.py tests/documents/test_document_worker.py -q`
Expected: all pass, including `test_every_tenant_scoped_model_has_rls_enabled_and_forced`.

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/tailored-programmes add apps/concierge apps/documents apps/audit/redaction.py tests/documents/test_transcript_worker.py
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(documents): a transcript upload is read into a stored, erasable reading

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3b: The stored reading holds highlights and key numbers; the prefill carries them

**What this task does.** Tasks 3 and 5 were executed against the reader's first design: `TranscriptReading.uncertain` held field names the model said it doubted, and the consultation draft carried them as strings. Now a reading produces highlights (failed checks, the not-checked marker, unsure answers — Task 2c) and four key numbers. This task renames the column, adds `key_numbers`, and moves the draft, the prefill and their tests onto `Highlight`. It lands before the worker writes a reading (Task 3c) so that every commit stays green. Task 5's conditional `expected_completion` question ("When do you expect to graduate?", asked only when the prefilled record has no graduation date) is already executed and does not change: a reading copies a date only when Jev picked a printed one.

The summary screen (not built here) reads `TranscriptReading.key_numbers` through `draft.reading_id`; nothing from it is copied into the session.

**Files:**
- Modify: `apps/documents/models.py` (`TranscriptReading`)
- Create: `apps/documents/migrations/00NN_transcript_reading_highlights.py` (hand-written — `makemigrations` asks interactively about a rename)
- Modify: `apps/audit/redaction.py` (`REDACT`)
- Modify: `apps/accounts/consultation.py` (`ConsultationDraft`, `read_draft`, `write_draft`, `prefill_from_latest_reading`)
- Modify: `tests/accounts/test_prefill.py`, `tests/documents/test_transcript_reading_rls.py`

**Interfaces:**
- Consumes: `Highlight` (Task 2b); `KeyNumbers` (Task 2c), stored as its JSON dump.
- Produces: `TranscriptReading.highlights` (JSON list of `Highlight` dumps; replaces `uncertain`), `TranscriptReading.key_numbers` (JSON object, a `KeyNumbers` dump); `ConsultationDraft.highlights: tuple[Highlight, ...]` (replaces `uncertain`); the session envelope key `"highlights"` (replaces `"uncertain"`).

- [ ] **Step 1: Move the tests onto highlights**

In `tests/accounts/test_prefill.py`, add `from apps.documents.transcript import Highlight` to the imports and replace `_reading`:

```python
_GRADE_UNSURE = Highlight(kind="unsure", scope="field", ref="grading_scale")


def _reading(agency, student, highlights=()):
    document = register(agency.id, student.id, kind="TRANSCRIPT")
    return TranscriptReading.objects.create(
        student=student,
        document=document,
        record=_RECORD,
        highlights=[highlight.model_dump() for highlight in highlights],
    )
```

Then, in the same file:
- in `test_a_reading_prefills_the_academic_record_and_skips_its_question`, `_reading(agency_a, student, uncertain=("grading_scale",))` becomes `_reading(agency_a, student, highlights=(_GRADE_UNSURE,))` and `assert draft.uncertain == ("grading_scale",)` becomes `assert draft.highlights == (_GRADE_UNSURE,)`;
- rename `test_retyping_the_record_clears_the_readers_doubts_but_keeps_the_reading` to `test_retyping_the_record_clears_its_highlights_but_keeps_the_reading`, pass `highlights=(_GRADE_UNSURE,)`, and assert `draft.highlights == ()`;
- replace `test_a_reading_with_a_malformed_uncertain_list_is_not_prefilled` with:

```python
def test_a_reading_with_malformed_highlights_is_not_prefilled(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p9")
        reading = _reading(agency_a, student)
        TranscriptReading.objects.filter(id=reading.id).update(highlights=[{"kind": "spelling"}])
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id is None
    assert "academic_history" not in draft.answers
```

In `tests/documents/test_transcript_reading_rls.py`: import `_GRADE_UNSURE` beside `_RECORD` from `tests.accounts.test_prefill`; in the `reading_a` fixture create the row with `highlights=[_GRADE_UNSURE.model_dump()]` instead of `uncertain=["grading_scale"]`; and in `test_the_owning_tenant_prefills_its_reading` assert `draft.highlights == (_GRADE_UNSURE,)`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/accounts/test_prefill.py -q`
Expected: FAIL — `TypeError: TranscriptReading() got unexpected keyword arguments: 'highlights'`

- [ ] **Step 3: The model, its migration, its erasure entry**

In `apps/documents/models.py`, `TranscriptReading`, replace `uncertain = models.JSONField(default=list)` with:

```python
    #: transcript.Highlight dumps: failed checks, unchecked totals, unsure answers (spec T2).
    highlights = models.JSONField(default=list)
    #: transcript_checks.KeyNumbers: the four numbers the summary screen opens with.
    key_numbers = models.JSONField(default=dict)
```

Run `ls /home/orkhan/Desktop/tailored-programmes/apps/documents/migrations/` and create the next number (`0022_…` on this branch as it stands; `0023_…` once master's `0022_draft_rendered_filename` has been merged in), depending on the real leaf:

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    """Written by hand: makemigrations asks interactively whether a field was renamed."""

    dependencies = [("documents", "0021_transcript_reading_tenant_guards")]

    operations = [
        migrations.RenameField("transcriptreading", "uncertain", "highlights"),
        migrations.AddField(
            "transcriptreading", "key_numbers", models.JSONField(default=dict)
        ),
    ]
```

The table's RLS policy and tenant FK (`0021`) are untouched by a column rename and a new column.

In `apps/audit/redaction.py`, `REDACT`, the key numbers are the student's grade and credits, so they are erased with the rest:

```python
    "documents.TranscriptReading": RedactSpec(
        "student_id", ("record", "highlights", "key_numbers", "accepted")
    ),
```

- [ ] **Step 4: The draft carries highlights**

In `apps/accounts/consultation.py`:

1. Import `from apps.documents.transcript import Highlight`, and after `_QUESTIONS_BY_KEY = ...` add:

```python
_HIGHLIGHTS: TypeAdapter[tuple[Highlight, ...]] = TypeAdapter(tuple[Highlight, ...])
```

2. In `ConsultationDraft`, replace the `uncertain` field and its comment:

```python
    #: The transcript reading that prefilled academic_history, and what the
    #: summary screen marks on it: failed checks and unsure answers (spec T2).
    reading_id: UUID | None = None
    highlights: tuple[Highlight, ...] = ()
```

and in `with_answer`, the `academic_history` branch:

```python
        if key == "academic_history":
            # The highlights were about the reading's record, which the student
            # just replaced. reading_id stays: finalize records what they kept as
            # the correction to that reading.
            return replace(self, answers=answers, correction_key=None, highlights=())
```

3. In `read_draft`, the allowed envelope keys name `"highlights"` instead of `"uncertain"`, and the three lines that read `uncertain` become one — a malformed list raises pydantic's `ValidationError`, a `ValueError`, which the existing `except` already turns into a fresh draft:

```python
        highlights = _HIGHLIGHTS.validate_python(envelope.get("highlights", []))
        return ConsultationDraft(
            tenant_id, membership_id, dict(answers), correction, reading_id, highlights
        )
```

4. In `write_draft`:

```python
    if draft.highlights:
        envelope["highlights"] = [highlight.model_dump() for highlight in draft.highlights]
```

5. In `prefill_from_latest_reading`, delete the `uncertain` isinstance check and validate the highlights with the record, then pass them on (and say "or whose highlights do not parse" where the docstring said "or whose uncertain list is not a list of strings"):

```python
    try:
        history = _canonical_answer("academic_history", [reading.record])
        highlights = _HIGHLIGHTS.validate_python(reading.highlights)
    except ValidationError:
        return draft
    return replace(
        draft,
        answers={**draft.answers, "academic_history": history},
        reading_id=reading.id,
        highlights=highlights,
    )
```

- [ ] **Step 5: Run to verify, with the erasure and isolation guards**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/accounts tests/documents/test_transcript_reading_rls.py tests/audit/test_redaction_classification.py tests/tenancy/test_database_isolation.py -q && uv run python manage.py makemigrations --check --dry-run`
Expected: all pass — the RLS tests run behind a `NOBYPASSRLS` role — and `No changes detected`.

- [ ] **Step 6: Lint, types, commit**

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv run ruff check apps tests && uv run mypy apps config && POSTGRES_DB=tehsil_tailored uv run pytest -q
git -C /home/orkhan/Desktop/tailored-programmes add apps/documents/models.py apps/documents/migrations apps/audit/redaction.py apps/accounts/consultation.py tests/accounts/test_prefill.py tests/documents/test_transcript_reading_rls.py
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(documents): a stored reading holds its highlights and key numbers, and the prefill carries them

The reader's doubts were field names a model reported; they are now the checks
that failed, the totals that could not be checked and the answers Jev was
unsure of. Key numbers are stored for the summary screen and erased with the
reading.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3c: The worker reads a transcript through the OCR function, outside the transaction

**What this task does.** Task 3 left a clean transcript waiting at `AVAILABLE`. The worker now reads it — but not inside the handler's transaction: OCR runs for minutes, and a transaction held across it would sit idle holding the row `apply_scan_result` just wrote (the module's own ponytail note allows that for seconds-long model calls, not minutes). The scan verdict commits first; `read_transcript` runs with no transaction open; a second short transaction writes the reading. A task that dies mid-read leaves the document `AVAILABLE`, the redelivered message reads it again, and the one-to-one reading row makes a duplicate impossible. A page the gate refuses sets `RESCAN_REQUIRED`; an upload that is not a PDF, PNG or JPEG, or a student over the limit, is `REVIEW_REQUIRED` as before. `OcrUnavailable` and `DecisionsUnavailable` are not caught: an engine or a provider that did not answer crashes to the dead-letter alarm rather than storing an empty reading.

It also puts the OCR program where it runs in production (owner, 2026-09-26): an **AWS Lambda function from `ocr/Dockerfile`'s image**, invoked by the document worker, which **stays at 0.5 vCPU / 1 GB** — nothing is added to `AppImage` or to the worker's size.

**The function's numbers, measured 2026-09-26** on five sample pages (`.superpowers/ocr-eval`, three Latin, two Cyrillic), each run with the program pinned to 6 and to 4 cores:

| | 6 cores (Lambda at 10,240 MB) | 4 cores (~7,100 MB) |
|---|---|---|
| seconds per page | 19.7–66.9, mean 39.3 | 23.7–81.0, mean 45.0 |
| peak memory | 6.2 GiB with both scripts' pipelines loaded | the same |

- **Memory 10,240 MB.** Lambda gives "the equivalent of one vCPU" at 1,769 MB, so 10,240 MB is its 6-vCPU ceiling (AWS, "Configure Lambda function memory"; "Lambda quotas"). 8,192 MB would cost ~8% less per page for ~15% longer reads and half the headroom over the 6.2 GiB peak; not worth it.
- **Timeout 720 s, page cap 8** (`read_pages.MAX_PAGES`, unchanged). Eight pages at the slowest page measured is 536 s; the rest covers a cold start. 720 s stays under the scan queue's 900 s visibility timeout, so a slow read is never redelivered to a second reader while the first is running, and the worker's client waits 750 s and never retries (a retry is a second full, billed read).
- **Cost per transcript.** Lambda bills $0.0000166667 per GB-second on x86 plus $0.20 per million requests (AWS, "AWS Lambda pricing" and its big-data whitepaper, "$0.00001667 for every GB-second"), and since 1 August 2025 the Init phase is billed too (AWS Compute Blog, "AWS Lambda standardizes billing for INIT Phase"). At 10 GB and 39.3 s a page: **about $0.0066 a page, $0.02 for a typical three-page transcript, $0.09 at worst (eight pages at 67 s)**. The monthly free tier (400,000 GB-seconds) covers about 340 three-page transcripts.
- **Break-even against an always-on worker.** A 4 vCPU / 10 GB Fargate task costs about $150.60 a month ($0.000011244 per vCPU-second, $0.000001235 per GB-second — AWS, "AWS Fargate pricing", example 1); the 0.5 vCPU / 1 GB worker (~$18) runs either way, so the always-on option costs ~$132.60 more a month. At $0.02 a transcript that is **about 6,700 transcripts a month (~220 a day)** — ~7,000 counting the free tier — before an always-on OCR worker would be cheaper.
- **Cold start.** The first transcript after the function has been idle waits for Lambda to start the image and for the models to load. AWS publishes no figure for an image of this size (3.7 GB of layers; the limit is 10 GB); the model load was measured through the runtime interface emulator: the first invocation took ~11 s longer than the second (34 s against 24 s). Expect a cold transcript to take tens of seconds longer than a warm one — unmeasured on Lambda itself until the first deploy.
- **A new account's quota.** "New AWS accounts have reduced concurrency and memory quotas for Lambda Functions … AWS raises these quotas automatically based on your usage" (AWS, "Lambda quotas"). The account has nothing deployed; a 10,240 MB function may be refused on first deploy until the quota is raised — check Service Quotas before deploying.

**What the student sees.** The upload poll (`GET /api/documents/uploads/<id>`) already reports the scan (`QUARANTINED` → `AVAILABLE`, or `BLOCKED`); for a transcript it now also says `read`. So the flow shows "checking your file" while `QUARANTINED`, "reading your transcript" while `AVAILABLE` and `read` is false — typically about two minutes for three pages, longer after idle — then the summary once `read` is true (the wizard's prefill picks the reading up on its next request), or "please rescan" on `RESCAN_REQUIRED`. Nothing blocks on it, and the student does not wait on it: Task 3d moves the transcript's questions to the end of the wizard, so identity basics and the seven questions are answered while the reading runs (spec §3.1, owner 2026-09-26). A student who still reaches the degree question before the reading lands is asked it, and their typed answer stands — the late reading is then not offered. If the function fails, the message is retried by SQS and then dead-lettered while the poll still says `read: false`; the spec's rule for the screen (progress; after a failure or about three minutes at the summary, type it yourself or be emailed when ready) is the presentation layer's to build, not this plan's.

**Where it runs, and why there.** The function parses untrusted files, and its role can read every cleared upload of every tenant. So it runs in two new private subnets whose route table has **no default route at all** — no NAT, no internet gateway — and a gateway endpoint of their own to S3 whose policy allows only `s3:GetObject` on `quarantine/*`. Code that escaped the parser could neither reach the internet nor write to any bucket. The existing private route table cannot be reused: it sends everything else to the NAT. The cost is six new template resources (two subnets, a route table and its two associations, the endpoint, a security group), all free; the alternative, the function outside any VPC, needs none of them and leaves an exploited parser with internet egress beside every student's upload. The function's logs leave through the Lambda service, not these subnets. The worker reaches the Lambda API through its existing NAT.

The function's role holds exactly: `s3:GetObject` on `quarantine/*` **only for objects GuardDuty tagged `NO_THREATS_FOUND`** (the Malware Protection Plan already tags, `DocumentMalwareProtectionPlan`'s `Tagging: ENABLED`), writing its own log group, and the network-interface actions Lambda needs to place it in the subnets (the `AWSLambdaENIManagementAccess` set, which has no resource to scope to). No secret, no key, no environment beyond the bucket's name.

**Files:**
- Modify: `apps/documents/document_worker.py` (`handle_scan_result`; new `_ingest_cv`, `_read_transcript`; module docstring's ponytail note)
- Modify: `apps/documents/api.py` (`upload_status` — `read` for a transcript)
- Modify (rewrite): `tests/documents/test_transcript_worker.py`
- Modify: `infra/template.yaml` (`OcrImage` parameter; the OCR subnets, route table, S3 endpoint, security group; `OcrFunctionRole`, `OcrLogGroup`, `OcrFunction`, `OcrFunctionFailureFilter`; `TypesafeApiKeySecret` and its grant; `DocumentWorkerTaskRole`'s invoke permission; `DocumentWorkerTaskDefinition`'s environment and secret)
- Modify: `infra/parameters/test.json`, `infra/parameters/production.json` (`OcrImage`)
- Modify: `docs/runbooks/deploy.md` (build and push the OCR image)
- Modify: `tests/infra/test_template.py`

**Interfaces:**
- Consumes: `read_transcript`, `personal_names`, `academic_record`, `TranscriptRateLimited` (Task 2b); `highlights`, `key_numbers` (Task 2c); `PageRefused` (Task 2a); `TranscriptReading.highlights`, `.key_numbers` (Task 3b); `read_pages(document, content)` choosing the Lambda transport when `OCR_FUNCTION_NAME` is set (Task 2a).
- Produces: `DocumentVersion.state == "RESCAN_REQUIRED"` for a refused page; one `TranscriptReading` per read transcript; `upload_status`'s `"read": bool` for a transcript; the `OcrFunction` Lambda and the worker's `OCR_FUNCTION_NAME`, `TYPESAFE_*` environment.

- [ ] **Step 1: Write the failing tests**

Replace `tests/documents/test_transcript_worker.py`:

```python
"""A transcript upload is read into a stored reading and never reaches CV ingestion."""

import json
from datetime import date
from unittest.mock import patch

import pytest
from django.conf import settings

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.document_queue import ScanResultEvent
from apps.documents.document_worker import handle_scan_result
from apps.documents.ingestion import UnsupportedUpload
from apps.documents.models import TranscriptReading, VerifiedFact
from apps.documents.ocr import OcrUnavailable, PageRefused
from apps.documents.transcript import Reading, Row, TranscriptContent, TranscriptCourse
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

UPLOADS = "/api/documents/uploads"


def _reading():
    return Reading(
        content=TranscriptContent(
            institution="Baku State University",
            country_code="AZ",
            qualification="BSc",
            field="Chemistry",
            overall_grade="88",
            grading_scale="100",
            credit_unit="ECTS",
            courses=(TranscriptCourse(title="Organic Chemistry I", credits=6, status="COMPLETED"),),
            expected_completion=date(2027, 6, 30),
        ),
        rows=(Row(0, "course", "Organic Chemistry I", "6", "91", "COMPLETED"),),
        total_credits_line=None,
        doubts=(),
    )


def _event(document):
    return ScanResultEvent(
        bucket_name=settings.EVIDENCE_BUCKET_NAME,
        object_key=document.object_key,
        scan_result="NO_THREATS_FOUND",
    )


def test_a_clean_transcript_is_read_once_into_a_reading_not_cv_facts(agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    with (
        patch("apps.documents.document_worker.read_transcript", return_value=_reading()) as read,
        patch("apps.documents.document_worker.ingest_uploaded_cv") as ingest,
    ):
        handle_scan_result(_event(document))
        handle_scan_result(_event(document))  # SQS redelivers
    assert read.call_count == 1
    ingest.assert_not_called()
    with tenant_scope(agency_a.id):
        reading = TranscriptReading.objects.get(document=document)
        assert reading.record["courses"][0]["ects"] == "6.00"
        assert reading.highlights == [
            {"kind": "credit_total_not_checked", "scope": "transcript", "ref": ""}
        ]
        assert reading.key_numbers["total_credits"] == "6"
        assert reading.key_numbers["graduation_date"] == "2027-06-30"
        assert reading.accepted is None
        assert not VerifiedFact.objects.filter(student=membership_a).exists()


def test_a_page_the_gate_refuses_asks_for_a_rescan(agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    refusal = PageRefused("blurred", 2)
    with patch("apps.documents.document_worker.read_transcript", side_effect=refusal):
        handle_scan_result(_event(document))
    with tenant_scope(agency_a.id):
        document.refresh_from_db()
        assert document.state == "RESCAN_REQUIRED"
        assert not TranscriptReading.objects.filter(document=document).exists()


def test_an_upload_that_is_not_a_transcript_file_is_review_required(agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    with patch(
        "apps.documents.document_worker.read_transcript", side_effect=UnsupportedUpload("docx")
    ):
        handle_scan_result(_event(document))
    with tenant_scope(agency_a.id):
        document.refresh_from_db()
        assert document.state == "REVIEW_REQUIRED"


def test_an_engine_that_did_not_answer_crashes_and_leaves_the_upload_available(
    agency_a, membership_a
):
    """Loud, for the dead-letter alarm -- and the scan verdict is already written, so the
    redelivered message reads the file again rather than finding it QUARANTINED."""
    document = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    with (
        patch("apps.documents.document_worker.read_transcript", side_effect=OcrUnavailable("x")),
        pytest.raises(OcrUnavailable),
    ):
        handle_scan_result(_event(document))
    with tenant_scope(agency_a.id):
        document.refresh_from_db()
        assert document.state == "AVAILABLE"
        assert not TranscriptReading.objects.filter(document=document).exists()


def test_a_cv_upload_still_goes_to_cv_ingestion(agency_a, membership_a):
    document = register(agency_a.id, membership_a.id)
    with (
        patch("apps.documents.document_worker.ingest_uploaded_cv") as ingest,
        patch("apps.documents.document_worker.read_transcript") as read,
    ):
        handle_scan_result(_event(document))
    assert ingest.call_count == 1 and read.call_count == 0


def _presign(monkeypatch):
    import apps.documents.api as api

    monkeypatch.setattr(api, "presigned_upload", lambda document: {"url": "u", "fields": {}})


@pytest.mark.parametrize("kind", ["PASSPORT", ["CV"], {"kind": "CV"}])
def test_the_upload_endpoint_refuses_an_unknown_kind(
    client, domain_a, user_a, membership_a, monkeypatch, kind
):
    """A list or dict is unhashable: tested against the set first, it was a 500."""
    _presign(monkeypatch)
    client.force_login(user_a)
    response = client.post(
        UPLOADS,
        data=json.dumps({"kind": kind}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_kind"


def test_the_upload_endpoint_stores_a_transcript_kind(
    client, domain_a, user_a, membership_a, agency_a, monkeypatch
):
    _presign(monkeypatch)
    client.force_login(user_a)
    response = client.post(
        UPLOADS,
        data=json.dumps({"kind": "TRANSCRIPT"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        assert DocumentVersion.objects.get(id=response.json()["document_id"]).kind == "TRANSCRIPT"


def test_the_poll_says_whether_a_clean_transcript_has_been_read_yet(
    client, domain_a, user_a, membership_a, agency_a
):
    """AVAILABLE covers the minutes the OCR runs and every minute after: `read` is what lets the
    upload flow show "reading your transcript" and then move on."""
    document = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    with patch("apps.documents.document_worker.read_transcript", side_effect=OcrUnavailable("x")):
        with pytest.raises(OcrUnavailable):
            handle_scan_result(_event(document))
    client.force_login(user_a)
    poll = f"{UPLOADS}/{document.id}"
    assert client.get(poll, HTTP_HOST=domain_a.host).json() == {
        "state": "AVAILABLE",
        "scan_result": "NO_THREATS_FOUND",
        "read": False,
    }
    with patch("apps.documents.document_worker.read_transcript", return_value=_reading()):
        handle_scan_result(_event(document))
    assert client.get(poll, HTTP_HOST=domain_a.host).json()["read"] is True
```

In `tests/infra/test_template.py`, after `test_the_document_worker_is_its_own_service`:

```python
# --- Transcript OCR runs on demand, in its own function -----------------------


def test_transcript_ocr_is_a_function_from_its_own_image(template: Template) -> None:
    """Not the shared AppImage, and not an always-on worker (owner, 2026-09-26). 10,240 MB is the
    measured 6.2 GB peak plus headroom, and 720 s stays under the scan queue's 900 s visibility
    timeout so a slow read is never redelivered to a second reader."""
    function = template.resource("OcrFunction")["Properties"]
    assert function["PackageType"] == "Image"
    assert function["Code"] == {"ImageUri": {"Ref": "OcrImage"}}
    assert function["MemorySize"] == 10240
    visibility = template.resource("DocumentScanQueue")["Properties"]["VisibilityTimeout"]
    assert function["Timeout"] < visibility
    worker = template.resource("DocumentWorkerTaskDefinition")["Properties"]
    assert (worker["Cpu"], worker["Memory"]) == ("512", "1024")


def test_the_ocr_function_holds_no_secret_and_reads_only_cleared_uploads(
    template: Template,
) -> None:
    function = template.resource("OcrFunction")["Properties"]
    assert function["Environment"]["Variables"] == {"DOCUMENT_BUCKET": {"Ref": "EvidenceBucket"}}
    [policy] = template.resource("OcrFunctionRole")["Properties"]["Policies"]
    reads = [
        statement
        for statement in policy["PolicyDocument"]["Statement"]
        if statement["Action"] == "s3:GetObject"
    ]
    assert reads == [
        {
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": {"Fn::Sub": "${EvidenceBucket.Arn}/quarantine/*"},
            "Condition": {
                "StringEquals": {
                    "s3:ExistingObjectTag/GuardDutyMalwareScanStatus": "NO_THREATS_FOUND"
                }
            },
        }
    ]
    actions = {
        action
        for statement in policy["PolicyDocument"]["Statement"]
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
    }
    assert not {a for a in actions if a.startswith(("secretsmanager:", "kms:", "sqs:"))}
    assert not {a for a in actions if a.startswith("s3:") and a != "s3:GetObject"}


def test_the_ocr_subnets_have_no_route_out_but_s3(template: Template) -> None:
    """The parser of untrusted uploads cannot reach the internet or write to any bucket."""
    routes = [
        resource["Properties"]
        for resource in template.all_resources()
        if resource["Type"] == "AWS::EC2::Route"
    ]
    assert not [route for route in routes if route["RouteTableId"] == {"Ref": "OcrRouteTable"}]
    endpoint = template.resource("OcrS3Endpoint")["Properties"]
    assert endpoint["RouteTableIds"] == [{"Ref": "OcrRouteTable"}]
    [allowed] = endpoint["PolicyDocument"]["Statement"]
    assert allowed["Action"] == "s3:GetObject"
    vpc = template.resource("OcrFunction")["Properties"]["VpcConfig"]
    assert vpc["SubnetIds"] == [{"Ref": "OcrPrivateSubnetA"}, {"Ref": "OcrPrivateSubnetB"}]


def test_the_document_worker_invokes_the_ocr_function_and_reaches_jev(template: Template) -> None:
    container = template.resource("DocumentWorkerTaskDefinition")["Properties"][
        "ContainerDefinitions"
    ][0]
    env = {entry["Name"]: entry["Value"] for entry in container["Environment"]}
    assert env["OCR_FUNCTION_NAME"] == {"Ref": "OcrFunction"}
    assert env["TYPESAFE_BASE_URL"] == "https://openrouter.ai/api"
    assert env["TYPESAFE_MODEL"] == "typesafe/jev-1.13"
    secrets = {entry["Name"]: entry["ValueFrom"] for entry in container["Secrets"]}
    assert secrets["TYPESAFE_API_KEY"] == {"Ref": "TypesafeApiKeySecret"}
    statements = template.resource("DocumentWorkerTaskRole")["Properties"]["Policies"][0][
        "PolicyDocument"
    ]["Statement"]
    assert {
        "Effect": "Allow",
        "Action": "lambda:InvokeFunction",
        "Resource": {"Fn::GetAtt": "OcrFunction.Arn"},
    } in statements
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript_worker.py tests/infra/test_template.py -q`
Expected: FAIL — `AttributeError: <module 'apps.documents.document_worker' ...> does not have the attribute 'read_transcript'`, and `OcrFunction is not defined in infra/template.yaml`.

- [ ] **Step 3: Route by kind, read between two transactions**

In `apps/documents/document_worker.py`, extend the imports:

```python
from .models import DocumentDraft, TranscriptReading, VerifiedFact
from .ocr import PageRefused
```

and, after `from .storage import ...`:

```python
from .transcript import TranscriptRateLimited, academic_record, personal_names, read_transcript
from .transcript_checks import highlights, key_numbers
```

In the module docstring's ponytail note, change "(a model call in the scan path, weasyprint in the render path)." to "(a model call in the CV scan path, weasyprint in the render path). The transcript path does not: its OCR runs for minutes, so it reads between two short transactions (_read_transcript)."

In `handle_scan_result`, replace everything after `if document.state != "AVAILABLE": return` — the transcript placeholder and the CV block — with:

```python
        if document.kind != "TRANSCRIPT":
            _ingest_cv(document, event.object_key)
            return
        if TranscriptReading.objects.filter(document=document).exists():
            logger.info("DocumentScanAlreadyIngested document=%s", document.id)
            return
        names = personal_names(document.student)
    _read_transcript(tenant_id, document, names)
```

Note the last line sits outside the `with tenant_scope(...), transaction.atomic():` block. Then add, below `handle_scan_result`, the CV block moved verbatim into its own function, and the transcript reader:

```python
def _ingest_cv(document: DocumentVersion, object_key: str) -> None:
    if VerifiedFact.objects.filter(
        student_id=document.student_id, source_ref=f"upload:{document.id}"
    ).exists():
        # SQS delivery is at-least-once. Re-applying the scan state is
        # harmless (same value), but a second ingestion duplicates every
        # candidate fact and the student confirms the same claim twice.
        logger.info("DocumentScanAlreadyIngested document=%s", document.id)
        return
    try:
        ingest_uploaded_cv(document=document, student=document.student)
    except UnsupportedUpload:
        # A JPEG, a PNG, a .txt CV: the commonest user error there is, and
        # not an error at all from the worker's side. Uncaught it escapes
        # consume_once and run_document_worker's two-exception filter, so
        # the task dies, the traceback trips DocumentWorkerCrashFilter --
        # and, because this whole handler is one transaction, the
        # apply_scan_result above ROLLS BACK with it. The poll endpoint
        # then answers QUARANTINED forever, which is exactly the
        # indistinguishability upload_status exists to prevent. Terminal,
        # visible, and the message is deleted rather than redelivered.
        # Anything else still raises: a genuine bug must crash loudly.
        logger.warning("DocumentIngestUnsupported document=%s key=%s", document.id, object_key)
        document.state = "REVIEW_REQUIRED"
        document.save(update_fields=["state"])


def _read_transcript(tenant_id: UUID, document: DocumentVersion, names: frozenset[str]) -> None:
    """Read a transcript outside any transaction, then store what was read in a short one.

    OCR takes one to eight minutes; a transaction held across it would sit idle holding the row
    apply_scan_result just wrote. The scan state is committed first, so a task that dies
    mid-read leaves the document AVAILABLE and the redelivered message reads it again -- the
    reading row, one per document, is what makes that safe. OcrUnavailable and
    DecisionsUnavailable are not caught: an engine or a provider that did not answer is a crash
    for the dead-letter alarm, never a transcript that read as empty.
    """
    try:
        reading = read_transcript(document=document, names=names)
        refused = ""
    except PageRefused as refusal:
        # The upload gate (spec 3.1): the student is asked to rescan, nothing is guessed.
        logger.warning(
            "TranscriptRescanRequired document=%s page=%s reason=%s",
            document.id,
            refusal.page,
            refusal.reason,
        )
        reading, refused = None, "RESCAN_REQUIRED"
    except (UnsupportedUpload, TranscriptRateLimited) as error:
        logger.warning(
            "TranscriptReadRefused document=%s reason=%s", document.id, type(error).__name__
        )
        reading, refused = None, "REVIEW_REQUIRED"
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        if reading is None:
            DocumentVersion.objects.filter(id=document.id).update(state=refused)
            return
        TranscriptReading.objects.get_or_create(
            document=document,
            defaults={
                "student_id": document.student_id,
                "record": academic_record(reading.content),
                "highlights": [highlight.model_dump() for highlight in highlights(reading)],
                "key_numbers": key_numbers(reading).model_dump(mode="json"),
            },
        )
```

- [ ] **Step 4: Say whether a transcript has been read**

In `apps/documents/api.py`, import `TranscriptReading` beside `DocumentDraft, VerifiedFact`, and end `upload_status` with:

```python
    body: dict[str, object] = {"state": document.state, "scan_result": document.scan_result}
    if document.kind == "TRANSCRIPT":
        # A transcript is AVAILABLE for the minutes its OCR runs and after it: `read` is what
        # lets the upload flow say "reading your transcript" rather than wait on nothing.
        body["read"] = TranscriptReading.objects.filter(document=document).exists()
    return JsonResponse(body)
```

A CV's poll is unchanged, so `tests/documents/test_api.py::test_the_poll_reports_the_scan_verdict` still asserts its exact body.

- [ ] **Step 5: The function, its network, the worker's wiring**

Apply this change to `infra/template.yaml` (every hunk; the comments carry the reasons above into the template):

```diff
diff --git a/infra/template.yaml b/infra/template.yaml
index 8e08b1ea..8dbef7cc 100644
--- a/infra/template.yaml
+++ b/infra/template.yaml
@@ -63,6 +63,13 @@ Parameters:
       carries Chrome for Testing and Xvfb, which no other service needs.
     AllowedPattern: "^.+@sha256:[0-9a-f]{64}$"
 
+  OcrImage:
+    Type: String
+    Description: >
+      Immutable URI of the ocr/Dockerfile image: transcript OCR as an AWS Lambda function.
+      Separate from AppImage: ~3 GB of PaddlePaddle and model weights no other service needs.
+    AllowedPattern: "^.+@sha256:[0-9a-f]{64}$"
+
   PortalDesiredCount:
     Type: Number
     Default: 0
@@ -287,6 +294,73 @@ Resources:
           ToPort: 5432
           SourceSecurityGroupId: !Ref PortalSecurityGroup
 
+  # --- Transcript OCR: subnets with no route out -------------------------------
+  # The OCR function parses untrusted uploads (pdfium, OpenCV, Paddle). Its subnets
+  # route nowhere but to S3, through a gateway endpoint of their own whose policy
+  # allows one thing: reading a quarantined upload. Code that escaped the parser
+  # can neither reach the internet nor write to any bucket, its own or anyone's.
+  # Subnets, a route table and a gateway endpoint cost nothing. The function's logs
+  # leave through the Lambda service, not these subnets.
+  OcrPrivateSubnetA:
+    Type: AWS::EC2::Subnet
+    Properties:
+      VpcId: !Ref ValidationVpc
+      AvailabilityZone: !Select [0, !GetAZs ""]
+      CidrBlock: 10.50.20.0/24
+      MapPublicIpOnLaunch: false
+
+  OcrPrivateSubnetB:
+    Type: AWS::EC2::Subnet
+    Properties:
+      VpcId: !Ref ValidationVpc
+      AvailabilityZone: !Select [1, !GetAZs ""]
+      CidrBlock: 10.50.21.0/24
+      MapPublicIpOnLaunch: false
+
+  # Deliberately no default route: no NAT, no internet gateway.
+  OcrRouteTable:
+    Type: AWS::EC2::RouteTable
+    Properties:
+      VpcId: !Ref ValidationVpc
+
+  OcrRouteAssociationA:
+    Type: AWS::EC2::SubnetRouteTableAssociation
+    Properties:
+      RouteTableId: !Ref OcrRouteTable
+      SubnetId: !Ref OcrPrivateSubnetA
+
+  OcrRouteAssociationB:
+    Type: AWS::EC2::SubnetRouteTableAssociation
+    Properties:
+      RouteTableId: !Ref OcrRouteTable
+      SubnetId: !Ref OcrPrivateSubnetB
+
+  OcrS3Endpoint:
+    Type: AWS::EC2::VPCEndpoint
+    Properties:
+      ServiceName: !Sub com.amazonaws.${AWS::Region}.s3
+      VpcEndpointType: Gateway
+      VpcId: !Ref ValidationVpc
+      RouteTableIds: [!Ref OcrRouteTable]
+      PolicyDocument:
+        Version: "2012-10-17"
+        Statement:
+          - Effect: Allow
+            Principal: "*"
+            Action: s3:GetObject
+            Resource: !Sub "${EvidenceBucket.Arn}/quarantine/*"
+
+  OcrSecurityGroup:
+    Type: AWS::EC2::SecurityGroup
+    Properties:
+      GroupDescription: Transcript OCR; no ingress, HTTPS out (the route table only reaches S3)
+      VpcId: !Ref ValidationVpc
+      SecurityGroupEgress:
+        - IpProtocol: tcp
+          FromPort: 443
+          ToPort: 443
+          CidrIp: 0.0.0.0/0
+
   S3Endpoint:
     Type: AWS::EC2::VPCEndpoint
     Properties:
@@ -1036,6 +1110,16 @@ Resources:
     Properties:
       Description: Exa API key, the primary index for the families no register covers (populate out-of-band)
 
+  # Same shape again. The transcript reader's closed questions go to TypeSafe's
+  # Jev through the decision layer (apps/research/decisions.py); on the
+  # OpenRouter route (DocumentWorkerTaskDefinition's TYPESAFE_BASE_URL) this
+  # holds the OpenRouter key. decisions.py raises on an empty key -- a
+  # transcript then crashes to the dead-letter queue, never reads as empty.
+  TypesafeApiKeySecret:
+    Type: AWS::SecretsManager::Secret
+    Properties:
+      Description: TypeSafe Jev key, or the OpenRouter key on its route (populate out-of-band)
+
   BraveApiKeySecret:
     Type: AWS::SecretsManager::Secret
     Properties:
@@ -1099,6 +1183,7 @@ Resources:
                   - !Ref ExaApiKeySecret
                   - !Ref BraveApiKeySecret
                   - !Ref TavilyApiKeySecret
+                  - !Ref TypesafeApiKeySecret
 
   # Only WorkerTaskRole can consume the research queue and read/write the
   # evidence bucket. WebTaskRole may only enqueue, read tenants/, and write
@@ -1303,6 +1388,10 @@ Resources:
               - Effect: Allow
                 Action: sqs:SendMessage
                 Resource: !GetAtt EuropassQueue.Arn
+              # Transcript OCR runs in its own function (OcrFunction), never here.
+              - Effect: Allow
+                Action: lambda:InvokeFunction
+                Resource: !GetAtt OcrFunction.Arn
               # Read only, and only the quarantined original: ingestion opens
               # the scanned-clean upload once (apps/documents/ingestion.py).
               - Effect: Allow
@@ -1709,6 +1798,16 @@ Resources:
               Value: runtime
             - Name: POSTGRES_RUNTIME_USER
               Value: tehsil_runtime
+            # Transcript OCR is invoked, never run here (apps/documents/ocr.py).
+            - Name: OCR_FUNCTION_NAME
+              Value: !Ref OcrFunction
+            # Jev through OpenRouter's native decisions route (owner,
+            # 2026-09-26); the SDK appends /v1/systemone. Configuration, not
+            # code: pointing back at api.typesafe.ai is two values here.
+            - Name: TYPESAFE_BASE_URL
+              Value: https://openrouter.ai/api
+            - Name: TYPESAFE_MODEL
+              Value: typesafe/jev-1.13
           Secrets:
             - Name: POSTGRES_RUNTIME_PASSWORD
               ValueFrom: !Ref RuntimeDatabaseSecret
@@ -1716,6 +1815,8 @@ Resources:
               ValueFrom: !Ref ValidationSecret
             - Name: OPENAI_API_KEY
               ValueFrom: !Ref OpenAiApiKeySecret
+            - Name: TYPESAFE_API_KEY
+              ValueFrom: !Ref TypesafeApiKeySecret
           LogConfiguration:
             LogDriver: awslogs
             Options:
@@ -1723,6 +1824,81 @@ Resources:
               awslogs-region: !Ref AWS::Region
               awslogs-stream-prefix: document-worker
 
+  # --- Transcript OCR as an on-demand function (apps/documents/ocr.py) --------
+  # Runs only while a transcript is read, instead of an always-on worker sized for
+  # the models (owner, 2026-09-26). Measured 2026-09-26: peak RSS 6.2 GB with both
+  # scripts' pipelines loaded; 20-67 s a page at 6 cores. So 10,240 MB, which is
+  # also Lambda's ceiling and its 6-vCPU allotment. Timeout 720 s: eight pages at
+  # the slowest measured page, plus a cold start, and still under the scan queue's
+  # 900 s visibility timeout -- a read outlasting it would be redelivered to a
+  # second reader while the first still runs.
+  OcrFunctionRole:
+    Type: AWS::IAM::Role
+    Properties:
+      AssumeRolePolicyDocument:
+        Version: "2012-10-17"
+        Statement:
+          - Effect: Allow
+            Principal: {Service: lambda.amazonaws.com}
+            Action: sts:AssumeRole
+      Policies:
+        - PolicyName: ReadClearedUploadsOnly
+          PolicyDocument:
+            Version: "2012-10-17"
+            Statement:
+              # Only an object GuardDuty tagged clean (DocumentMalwareProtectionPlan's
+              # Tagging): the function never reads what the scan has not passed.
+              - Effect: Allow
+                Action: s3:GetObject
+                Resource: !Sub "${EvidenceBucket.Arn}/quarantine/*"
+                Condition:
+                  StringEquals:
+                    s3:ExistingObjectTag/GuardDutyMalwareScanStatus: NO_THREATS_FOUND
+              - Effect: Allow
+                Action:
+                  - logs:CreateLogStream
+                  - logs:PutLogEvents
+                Resource: !Sub "${OcrLogGroup.Arn}:*"
+              # What Lambda needs to place the function in its subnets
+              # (the AWSLambdaENIManagementAccess set); ENIs have no ARN to scope to.
+              - Effect: Allow
+                Action:
+                  - ec2:CreateNetworkInterface
+                  - ec2:DescribeNetworkInterfaces
+                  - ec2:DescribeSubnets
+                  - ec2:DeleteNetworkInterface
+                  - ec2:AssignPrivateIpAddresses
+                  - ec2:UnassignPrivateIpAddresses
+                Resource: "*"
+
+  OcrLogGroup:
+    Type: AWS::Logs::LogGroup
+    Properties:
+      LogGroupName: !Sub "/aws/lambda/${AWS::StackName}-transcript-ocr"
+      RetentionInDays: 30
+
+  OcrFunction:
+    Type: AWS::Lambda::Function
+    Properties:
+      FunctionName: !Sub "${AWS::StackName}-transcript-ocr"
+      PackageType: Image
+      Code:
+        ImageUri: !Ref OcrImage
+      Architectures: [x86_64]
+      MemorySize: 10240
+      Timeout: 720
+      EphemeralStorage:
+        Size: 512
+      Role: !GetAtt OcrFunctionRole.Arn
+      LoggingConfig:
+        LogGroup: !Ref OcrLogGroup
+      Environment:
+        Variables:
+          DOCUMENT_BUCKET: !Ref EvidenceBucket
+      VpcConfig:
+        SubnetIds: [!Ref OcrPrivateSubnetA, !Ref OcrPrivateSubnetB]
+        SecurityGroupIds: [!Ref OcrSecurityGroup]
+
   # One task. Not a rate knob like the Europass worker's -- nothing here calls
   # a third party on a courtesy budget -- but generation is the expensive part
   # and ~100 documents a day drains from one task with room to spare. Raise it
@@ -1987,6 +2163,20 @@ Resources:
           MetricValue: "1"
           DefaultValue: 0
 
+  # The OCR function's own failures: an exception, a timeout, or the runtime
+  # killed for memory. The worker's crash alarm above fires on the same
+  # transcript (OcrUnavailable is not caught); this says which side failed.
+  OcrFunctionFailureFilter:
+    Type: AWS::Logs::MetricFilter
+    Properties:
+      LogGroupName: !Ref OcrLogGroup
+      FilterPattern: '?"Traceback (most recent call last)" ?"Task timed out" ?"Runtime exited"'
+      MetricTransformations:
+        - MetricNamespace: Tehsil/Documents
+          MetricName: OcrFunctionFailures
+          MetricValue: "1"
+          DefaultValue: 0
+
   # AWS documents five scanResultStatus values. A sixth is survivable --
   # apply_scan_result puts it in REVIEW_REQUIRED -- but it means a human has to
   # decide what the new status means, and every affected upload is waiting.
```

In `infra/parameters/test.json` and `infra/parameters/production.json`, after the `PortalImage` line:

```json
  {"ParameterKey": "OcrImage", "ParameterValue": "REPLACE_WITH_IMAGE_DIGEST_URI"},
```

In `docs/runbooks/deploy.md`, Prerequisites, after step 1, add:

```markdown
   Build and push the transcript OCR image separately -- its own Dockerfile and
   context, single-architecture, as Lambda requires:
   `docker build --platform linux/amd64 --provenance=false -t <repo>:ocr ocr/`,
   push it, and fill in `OcrImage` with its `@sha256:...` digest. Before the first
   deploy to a new account, check Service Quotas: new accounts start with a reduced
   Lambda memory quota and `OcrFunction` asks for 10,240 MB. Request the increase the week
   before the first deploy; if it is refused, deploy at 8,192 MB (spec §3.1).
```

The document worker keeps `OPENAI_API_KEY`: CV ingestion and generation still call OpenAI. The transcript path does not.

- [ ] **Step 6: Run to verify they pass, then the template's own lint**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript_worker.py tests/documents/test_api.py tests/documents/test_document_worker.py tests/infra -q && uv run cfn-lint`
Expected: all pass; `cfn-lint` exits 0.

- [ ] **Step 7: Lint, types, commit**

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv run ruff check apps tests && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py && POSTGRES_DB=tehsil_tailored uv run pytest -q
git -C /home/orkhan/Desktop/tailored-programmes add apps/documents/document_worker.py apps/documents/api.py tests/documents/test_transcript_worker.py infra/template.yaml infra/parameters tests/infra/test_template.py docs/runbooks/deploy.md
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(documents): the worker reads a transcript through an on-demand OCR function

OCR runs as a Lambda function from its own image, invoked with the cleared
upload's key, in subnets with no route out but a read-only S3 endpoint and a
role that reads only GuardDuty-clean objects. The worker stays at 0.5 vCPU and
reads between two short transactions; a refused page asks for a rescan, and the
upload poll says when a transcript has been read. About two cents a
transcript at 10 GB, measured.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

After deploying, a human puts the key once: `aws secretsmanager put-secret-value --secret-id <TypesafeApiKeySecret ARN> --secret-string <key>` — the same out-of-band bootstrap as `OpenAiApiKeySecret`.

---

### Task 3d: The transcript's questions come last, so the reading runs while the student answers

**Files:**
- Modify: `apps/accounts/consultation.py` (`QUESTIONS`, ~line 83)
- Test: `tests/accounts/test_consultation.py`

**Interfaces:**
- Consumes: `QUESTIONS` (executed Task 5).
- Produces: nothing new — the same keys, in a new order.

Spec §3.1 (owner, 2026-09-26): reading takes about two minutes, so the student answers identity basics and the seven questions while it runs, and meets the summary — `academic_history`, and `expected_completion` when the reading has no date — last, just before the free-text notes. `next_profile_question` already skips a key the reading prefilled, so no other code changes.

- [ ] **Step 1: Write the failing test** (append to `tests/accounts/test_consultation.py`)

```python
def test_the_transcript_questions_come_after_every_other_question_but_the_notes():
    from apps.accounts.consultation import QUESTIONS

    keys = [question.key for question in QUESTIONS]
    assert keys[-3:] == ["academic_history", "expected_completion", "additional_notes"]
    assert keys[:3] == ["nationality", "country_of_residence", "date_of_birth"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/accounts/test_consultation.py -q -k transcript_questions_come`
Expected: FAIL — `academic_history` is fourth.

- [ ] **Step 3: Move the two entries**

In `QUESTIONS`, cut these two lines from after `date_of_birth`:

```python
    _question("academic_history", _always),
    _question("expected_completion", lambda draft: _undated(draft.answers)),
```

and paste them immediately before `_question("additional_notes", _always),`. Add one line to the comment above `QUESTIONS`: `#: The transcript's questions come last: the reading runs while the others are answered (spec 3.1).`

- [ ] **Step 4: Run the accounts suite**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/accounts tests/acceptance -q`
Expected: the new test passes. Any test that walked the wizard in the old order (e.g. in `test_consultation_progress.py`, `test_wizard_sequencing_errors.py`, `tests/acceptance/helpers.py`) fails on which question comes next: change that test's expected order to the new one — never the code — and note each in the commit.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv run ruff check apps/accounts tests/accounts tests/acceptance && uv run mypy apps config
git -C /home/orkhan/Desktop/tailored-programmes add apps/accounts/consultation.py tests/accounts tests/acceptance
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(accounts): the transcript's questions come last, so the reading runs while the student answers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Profile schema version 3

> **Executed** — `1a1e2af0`, `f5c66311`, `3d85f47d`. Unchanged by the OCR rewrite; kept as the record, do not re-execute.

**Files:**
- Modify: `apps/accounts/schemas.py` (`AcademicRecord`, `StudentProfileSnapshot`)
- Modify: `apps/accounts/models.py` — check constraint allows 3
- Create: `apps/accounts/migrations/0005_profile_schema_version_3.py` (generated)
- Modify: `apps/accounts/profile_versions.py:44` — write 3
- Modify: `apps/research/services.py:80` — `!= 3`
- Modify fixtures: `tests/funding/conftest.py:88`, `tests/accounts/test_consultation.py:80,122`, `tests/accounts/test_profile_versions.py:89,120`, `tests/acceptance/helpers.py:31`, `tests/documents/test_profile_bridge.py:45`
- Test: `tests/accounts/test_profile_schema_v3.py`

**Interfaces:**
- Produces: `CourseRecord(title, ects: Decimal | None, grade: str | None, in_progress: bool)`; `AcademicRecord.courses: tuple[CourseRecord, ...] = ()`, `AcademicRecord.expected_completion: date | None = None`; on `StudentProfileSnapshot`: `schema_version: Literal[3]`, `date_of_birth: date`, `self_funding_capacity: Money | None = None`, `additional_notes: str = ""`, `career_intent: Literal["WORK_ABROAD", "RETURN_HOME", "PHD", "UNDECIDED"]`, and defaults for `experience`, `research_interests`, `strategy`, `duration_preference`, `duration_flexibility`, `allowed_countries`, `excluded_countries`, `mobility_priorities`, `non_negotiables`, `negotiable_preferences`, `weights`. `DEFAULT_WEIGHTS: Mapping[EvaluationDimension, Decimal]`.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from apps.accounts.schemas import DEFAULT_WEIGHTS, StudentProfileSnapshot


def _answers(**overrides):
    values = {
        "nationality": "AZ",
        "country_of_residence": "AZ",
        "date_of_birth": "2002-05-01",
        "academic_history": [
            {
                "institution": "Baku State University",
                "country_code": "AZ",
                "qualification": "BSc",
                "field": "Chemistry",
                "grade": "88",
                "grading_scale": "0-100",
                "completed_on": None,
                "expected_completion": "2027-06-30",
                "courses": [
                    {"title": "Organic Chemistry I", "ects": "6.00", "grade": "91", "in_progress": False}
                ],
            }
        ],
        "target_field": "Chemistry, maybe synthesis",
        "intended_intake": "2027-09-01",
        "acceptable_teaching_languages": ["English"],
        "language_evidence": [],
        "career_intent": "PHD",
        "application_budget": {"amount": "300", "currency": "EUR"},
        "funding_dependency": "MANDATORY",
    }
    return {**values, **overrides}


def test_the_short_onboarding_answers_make_a_valid_profile():
    profile = StudentProfileSnapshot.model_validate(_answers())
    assert profile.schema_version == 3
    assert profile.strategy == "FUNDING_FIRST"
    assert profile.duration_preference == "NONE"
    assert profile.weights == DEFAULT_WEIGHTS
    assert profile.academic_history[0].courses[0].ects == Decimal("6.00")


def test_not_mandatory_funding_needs_a_self_funding_capacity():
    with pytest.raises(ValidationError) as error:
        StudentProfileSnapshot.model_validate(_answers(funding_dependency="IMPORTANT"))
    assert error.value.errors()[0]["ctx"]["target"] == "self_funding_capacity"


def test_a_self_funded_student_defaults_to_balanced():
    profile = StudentProfileSnapshot.model_validate(
        _answers(
            funding_dependency="OPTIONAL",
            self_funding_capacity={"amount": "15000", "currency": "EUR"},
        )
    )
    assert profile.strategy == "BALANCED"


def test_the_old_career_intent_values_are_gone():
    with pytest.raises(ValidationError):
        StudentProfileSnapshot.model_validate(_answers(career_intent="RESEARCH_OR_PHD"))


def test_a_birth_date_in_the_future_is_refused():
    with pytest.raises(ValidationError):
        StudentProfileSnapshot.model_validate(_answers(date_of_birth=str(date.today().replace(year=date.today().year + 1))))


def test_default_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values(), Decimal("0")) == Decimal("1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/accounts/test_profile_schema_v3.py -q`
Expected: FAIL — `ImportError: cannot import name 'DEFAULT_WEIGHTS'`

- [ ] **Step 3: Change the schema**

In `apps/accounts/schemas.py`:

1. Before `AcademicRecord`, add:

```python
class CourseRecord(BaseModel):
    """One course from a transcript, credits already in ECTS.

    `ects` is None when the credit system could not be converted
    (apps/documents/credits.py) -- unknown, never guessed.
    """

    model_config = _PROFILE_CONFIG

    title: str = Field(min_length=1, max_length=200)
    ects: Decimal | None = Field(default=None, ge=0, le=100, max_digits=6, decimal_places=2)
    grade: str | None = Field(default=None, max_length=50)
    in_progress: bool = False
```

2. In `AcademicRecord`, after `completed_on`, add:

```python
    #: For a student still studying: completed_on is None and this is set.
    expected_completion: date | None = None
    courses: tuple[CourseRecord, ...] = Field(default=(), max_length=150)
```

3. After the `EvaluationDimension` Literal, add:

```python
#: Used when the student does not set weights -- the onboarding no longer asks
#: (spec T3). A product constant, adjustable on the pack; sums to exactly one.
DEFAULT_WEIGHTS: Mapping[EvaluationDimension, Decimal] = MappingProxyType(
    {
        "ACADEMIC_FIT": Decimal("0.20"),
        "PROGRAM_FIT": Decimal("0.20"),
        "CAREER_FIT": Decimal("0.15"),
        "AFFORDABILITY": Decimal("0.20"),
        "DURATION": Decimal("0.05"),
        "MOBILITY_FIT": Decimal("0.10"),
        "RESEARCH_FIT": Decimal("0.10"),
    }
)
```

4. In `StudentProfileSnapshot`, replace the field block with:

```python
    schema_version: Literal[3] = 3
    nationality: CountryCode
    country_of_residence: CountryCode
    date_of_birth: date
    academic_history: tuple[AcademicRecord, ...] = Field(min_length=1, max_length=20)
    target_field: str = Field(min_length=1, max_length=200)
    intended_intake: date
    acceptable_teaching_languages: tuple[NonBlankText100, ...] = Field(min_length=1, max_length=10)
    language_evidence: tuple[LanguageEvidence, ...] = Field(default=(), max_length=20)
    experience: tuple[ExperienceRecord, ...] = Field(default=(), max_length=50)
    research_interests: tuple[NonBlankText200, ...] = Field(default=(), max_length=20)
    #: The after-the-master's question (spec 3.2 question 7). WORK_ABROAD weights
    #: post-study work rights; RETURN_HOME makes return-bonded awards acceptable;
    #: PHD weights research tracks.
    career_intent: Literal["WORK_ABROAD", "RETURN_HOME", "PHD", "UNDECIDED"]
    application_budget: Money
    funding_dependency: Literal["MANDATORY", "IMPORTANT", "OPTIONAL"]
    #: What the student can cover per year for tuition and living. Required
    #: unless funding is MANDATORY (see validate_profile_relationships).
    self_funding_capacity: Money | None = None
    strategy: Literal["BALANCED", "FUNDING_FIRST"]
    duration_preference: Literal["ONE_YEAR", "TWO_YEAR", "NONE"] = "NONE"
    duration_flexibility: Literal["NON_NEGOTIABLE", "WEIGHTED", "NOT_APPLICABLE"] = "NOT_APPLICABLE"
    longer_program_justifications: tuple[Literal["FUNDING", "INTERNSHIP", "RESEARCH"], ...] = ()
    #: Empty means anywhere.
    allowed_countries: tuple[CountryCode, ...] = Field(default=(), max_length=50)
    excluded_countries: tuple[CountryCode, ...] = Field(default=(), max_length=50)
    mobility_priorities: tuple[NonBlankText200, ...] = Field(default=(), max_length=20)
    non_negotiables: tuple[ProfileConstraint, ...] = Field(default=(), max_length=30)
    negotiable_preferences: tuple[ProfileConstraint, ...] = Field(default=(), max_length=30)
    weights: Mapping[EvaluationDimension, Decimal] = DEFAULT_WEIGHTS
    additional_notes: str = Field(default="", max_length=1000)
```

Keep every existing validator. Add a before-validator for the strategy default:

```python
    @model_validator(mode="before")
    @classmethod
    def default_strategy(cls, data: object) -> object:
        if isinstance(data, dict) and "strategy" not in data:
            dependency = data.get("funding_dependency")
            return {**data, "strategy": "FUNDING_FIRST" if dependency == "MANDATORY" else "BALANCED"}
        return data
```

and at the end of `validate_profile_relationships`, before `return self`:

```python
        if self.funding_dependency != "MANDATORY" and self.self_funding_capacity is None:
            raise PydanticCustomError(
                "profile_self_funding_missing",
                "say how much you can cover yourself",
                {"target": "self_funding_capacity"},
            )
        if self.date_of_birth >= date.today():
            raise PydanticCustomError(
                "profile_birth_date_future",
                "date of birth must be in the past",
                {"target": "date_of_birth"},
            )
```

- [ ] **Step 4: Version 3 everywhere it is named**

- `apps/accounts/models.py`: `condition=models.Q(schema_version__in=(0, 1, 2, 3))`.
- `apps/accounts/profile_versions.py`: `schema_version = 3 if isinstance(validated, StudentProfileSnapshot) else 0`.
- `apps/research/services.py:80`: `version.schema_version != 3`.
- Run: `cd /home/orkhan/Desktop/tailored-programmes && uv run python manage.py makemigrations accounts -n profile_schema_version_3`
- Fixtures: in each file listed above, replace `"career_intent": "RAPID_INDUSTRY_ENTRY"` / `"RESEARCH_OR_PHD"` with `"WORK_ABROAD"` / `"PHD"`, add `"date_of_birth": "2000-01-01"`, and where the fixture's `funding_dependency` is not `"MANDATORY"` add `"self_funding_capacity": {"amount": "10000", "currency": "EUR"}`. Change `schema_version == 2` assertions to `== 3`. In `tests/acceptance/helpers.py` the fixture is a tuple of `(key, value)` wizard answers — add the new keys in wizard order after Task 5 lands; for now only fix the values.

- [ ] **Step 5: Run the full suite**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest -q`
Expected: the new test file passes. Failures in `tests/accounts/test_consultation*.py`, `test_wizard_sequencing_errors.py` and `tests/acceptance/` that come from the wizard's question list are expected until Task 5; any other failure is a real consumer of a changed field — fix it here.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/tailored-programmes add apps/accounts apps/research/services.py tests
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(accounts): profile schema 3 -- courses, birth date, self-funding, defaults for what we stopped asking

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The short question set, prefilled from the transcript

> **Executed** — `9254dc48`, `0e8b8701` — with one addition the steps below predate: the conditional `expected_completion` question ("When do you expect to graduate?"), asked only when the prefilled record carries neither a completion nor an expected date, and folded into the record at finalize. The draft's `uncertain` field and session key become `highlights` in Task 3b. Kept as the record; do not re-execute.

**Files:**
- Modify: `apps/accounts/consultation.py` (labels, `QUESTIONS`, `ConsultationDraft`, envelope, finalize)
- Modify: `apps/accounts/forms.py` (field kinds)
- Modify: `apps/accounts/views.py:98` (`profile` prefills on read)
- Modify: `tests/acceptance/helpers.py`, `tests/accounts/test_consultation.py`, `tests/accounts/test_consultation_progress.py`, `tests/accounts/test_wizard_sequencing_errors.py`, `tests/accounts/test_question_labels.py`
- Test: `tests/accounts/test_prefill.py`

**Interfaces:**
- Consumes: `TranscriptReading` (Task 3), schema v3 (Task 4).
- Produces: `ConsultationDraft.uncertain: tuple[str, ...]`, `ConsultationDraft.reading_id: UUID | None`; `prefill_from_latest_reading(draft: ConsultationDraft, *, membership: Membership) -> ConsultationDraft`.

- [ ] **Step 1: Write the failing tests**

```python
from uuid import uuid4

import pytest

from apps.accounts.consultation import (
    ConsultationDraft,
    finalize_consultation,
    next_profile_question,
    prefill_from_latest_reading,
)
from apps.concierge.documents import register
from apps.documents.models import TranscriptReading
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

_RECORD = {
    "institution": "Baku State University",
    "country_code": "AZ",
    "qualification": "BSc",
    "field": "Chemistry",
    "grade": "88",
    "grading_scale": "0-100",
    "completed_on": None,
    "expected_completion": "2027-06-30",
    "courses": [{"title": "Organic Chemistry I", "ects": "6.00", "grade": "91", "in_progress": False}],
}


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _reading(agency, student, uncertain=()):
    document = register(agency.id, student.id, kind="TRANSCRIPT")
    return TranscriptReading.objects.create(
        student=student, document=document, record=_RECORD, uncertain=list(uncertain)
    )


def test_a_reading_prefills_the_academic_record_and_skips_its_question(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p1")
        reading = _reading(agency_a, student, uncertain=("grading_scale",))
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id == reading.id
    assert draft.uncertain == ("grading_scale",)
    assert draft.answer("academic_history")[0]["courses"][0]["title"] == "Organic Chemistry I"
    asked = []
    while (question := next_profile_question(draft)) is not None:
        asked.append(question.key)
        draft = draft.with_answer(question.key, _ANSWERS[question.key])
    assert "academic_history" not in asked


def test_without_a_reading_the_academic_record_is_asked(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p2")
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id is None
    keys = []
    while (question := next_profile_question(draft)) is not None:
        keys.append(question.key)
        draft = draft.with_answer(question.key, _ANSWERS.get(question.key, [_RECORD]))
    assert "academic_history" in keys


def test_mandatory_funding_skips_self_funding_and_changing_it_clears_the_answer():
    draft = ConsultationDraft(uuid4(), uuid4(), {})
    draft = draft.with_answer("funding_dependency", "OPTIONAL")
    draft = draft.with_answer("self_funding_capacity", {"amount": "10000.00", "currency": "EUR"})
    draft = draft.with_answer("funding_dependency", "MANDATORY")
    assert draft.answer("self_funding_capacity") is None


def test_finalize_records_what_the_student_kept(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p3")
        reading = _reading(agency_a, student)
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
        while (question := next_profile_question(draft)) is not None:
            draft = draft.with_answer(question.key, _ANSWERS[question.key])
        finalize_consultation(membership=student, draft=draft)
        reading.refresh_from_db()
        assert reading.accepted == draft.answer("academic_history")[0]


def test_an_accepted_reading_is_not_prefilled_again(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p4")
        reading = _reading(agency_a, student)
        TranscriptReading.objects.filter(id=reading.id).update(accepted=_RECORD)
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id is None


_ANSWERS = {
    "nationality": "AZ",
    "country_of_residence": "AZ",
    "date_of_birth": "2002-05-01",
    "target_field": "Chemistry, maybe synthesis",
    "allowed_countries": [],
    "excluded_countries": [],
    "intended_intake": "2027-09-01",
    "funding_dependency": "MANDATORY",
    "application_budget": {"amount": "300.00", "currency": "EUR"},
    "career_intent": "PHD",
    "acceptable_teaching_languages": ["English"],
    "language_evidence": [],
    "additional_notes": "",
}
```

The answers in `_ANSWERS` must be in canonical form (what `_canonical_answer` produces) or `read_draft` would reject them — if a test fails on a Money value's format, match what `TypeAdapter(Money).dump_json` emits.

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/accounts/test_prefill.py -q`
Expected: FAIL — `ImportError: cannot import name 'prefill_from_latest_reading'`

- [ ] **Step 3: Replace the labels and the question list**

In `apps/accounts/consultation.py`, replace `QUESTION_LABELS` and `QUESTIONS`:

```python
QUESTION_LABELS = {
    "nationality": "Your nationality (2-letter country code)",
    "country_of_residence": "Where do you live now? (2-letter country code)",
    "date_of_birth": "Your date of birth",
    "academic_history": "Your degree so far",
    "target_field": "What do you want to study, and anything specific within it?",
    "allowed_countries": "Which countries would you consider? Leave empty for anywhere",
    "excluded_countries": "Any countries to rule out?",
    "intended_intake": "When do you want to start?",
    "funding_dependency": "Can you go without a scholarship?",
    "self_funding_capacity": "How much can you cover yourself per year for tuition and living?",
    "application_budget": "How much can you spend on application fees?",
    "career_intent": (
        "After the master's, do you want to work in that country, return home, "
        "or continue to a PhD?"
    ),
    "acceptable_teaching_languages": "Which languages could you study in?",
    "language_evidence": "Which language certificates do you have, or plan to take and by when?",
    "additional_notes": "Anything else we should know?",
}


def _always(_draft: ConsultationDraft) -> bool:
    return True


#: Identity basics first (facts, not preferences -- spec 3.1), then the seven
#: questions of spec 3.2. academic_history is asked only when no transcript
#: reading prefilled it: next_profile_question skips any key already answered.
QUESTIONS = (
    _question("nationality", _always),
    _question("country_of_residence", _always),
    _question("date_of_birth", _always),
    _question("academic_history", _always),
    _question("target_field", _always),
    _question("allowed_countries", _always),
    _question("excluded_countries", _always),
    _question("intended_intake", _always),
    _question("funding_dependency", _always),
    _question(
        "self_funding_capacity",
        lambda draft: draft.answer("funding_dependency") in {"IMPORTANT", "OPTIONAL"},
    ),
    _question("application_budget", _always),
    _question("career_intent", _always),
    _question("acceptable_teaching_languages", _always),
    _question(
        "language_evidence", lambda draft: bool(draft.answer("acceptable_teaching_languages"))
    ),
    _question("additional_notes", _always),
)
```

- [ ] **Step 4: Draft carries the reading and its doubts**

Replace `ConsultationDraft` and its envelope handling:

```python
@dataclass(frozen=True)
class ConsultationDraft:
    tenant_id: UUID
    membership_id: UUID
    answers: dict[str, object]
    correction_key: str | None = None
    #: The transcript reading that prefilled academic_history, and the fields
    #: its reader was unsure of -- the summary screen highlights exactly these.
    reading_id: UUID | None = None
    uncertain: tuple[str, ...] = ()

    def answer(self, key: str) -> object | None:
        return self.answers.get(key)

    def with_answer(self, key: str, value: object) -> ConsultationDraft:
        answers = {**self.answers, key: value}
        if key == "funding_dependency" and value == "MANDATORY":
            answers.pop("self_funding_capacity", None)
        return replace(self, answers=answers, correction_key=None)

    def with_correction(self, key: str) -> ConsultationDraft:
        return replace(self, correction_key=key)
```

In `read_draft`, widen the allowed envelope keys to include `"reading_id"` and `"uncertain"`, and build the draft with them:

```python
        reading = envelope.get("reading_id")
        reading_id = UUID(str(reading)) if reading is not None else None
        uncertain = envelope.get("uncertain", [])
        if not isinstance(uncertain, list) or not all(isinstance(v, str) for v in uncertain):
            raise ValueError
        return ConsultationDraft(
            tenant_id, membership_id, dict(answers), correction, reading_id, tuple(uncertain)
        )
```

In `write_draft`, add:

```python
    if draft.reading_id is not None:
        envelope["reading_id"] = str(draft.reading_id)
    if draft.uncertain:
        envelope["uncertain"] = list(draft.uncertain)
```

- [ ] **Step 5: Prefill and record the acceptance**

Add to `apps/accounts/consultation.py` (import `TranscriptReading` from `apps.documents.models`):

```python
def prefill_from_latest_reading(
    draft: ConsultationDraft, *, membership: Membership
) -> ConsultationDraft:
    """Put the latest not-yet-accepted transcript reading into the draft.

    Continuing past the summary is the student's acceptance (spec T2), so a
    reading already accepted is never offered again, and a draft that already
    holds an academic record -- typed or prefilled -- is left alone.
    """
    if "academic_history" in draft.answers:
        return draft
    reading = (
        TranscriptReading.objects.filter(student=membership, accepted__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if reading is None:
        return draft
    answers = {**draft.answers, "academic_history": _canonical_answer("academic_history", [reading.record])}
    return replace(
        draft, answers=answers, reading_id=reading.id, uncertain=tuple(reading.uncertain)
    )
```

In `finalize_consultation`, after `create_profile_version(...)`:

```python
    if draft.reading_id is not None:
        kept = cast(list[object], draft.answers["academic_history"])[0]
        TranscriptReading.objects.filter(id=draft.reading_id, student=membership).update(
            accepted=kept
        )
```

In `apps/accounts/views.py::profile`, right after `draft = read_draft(...)`:

```python
    prefilled = prefill_from_latest_reading(draft, membership=membership)
    if prefilled is not draft:
        write_draft(request.session, prefilled)
        draft = prefilled
```

- [ ] **Step 6: Form fields for the new keys**

In `apps/accounts/forms.py`:
- remove `"research_interests"`, `"mobility_priorities"`, `"longer_program_justifications"` from `_COMMA_SEPARATED`;
- `_JSON_VALUES` becomes `{"academic_history", "language_evidence", "application_budget", "self_funding_capacity"}`;
- `_OPTION_VALUES` becomes `{"career_intent": ("WORK_ABROAD", "RETURN_HOME", "PHD", "UNDECIDED"), "funding_dependency": ("MANDATORY", "IMPORTANT", "OPTIONAL")}`;
- `_OPTIONAL_VALUES` becomes `{"language_evidence", "allowed_countries", "excluded_countries", "additional_notes"}`;
- in `question_field`, handle `date_of_birth` like `intended_intake` (a `DateField` with the date input), and `additional_notes` as `forms.CharField(required=False, max_length=1000)`;
- in `_canonical_value`, `self_funding_capacity` empty stays `value` (like `application_budget`).

- [ ] **Step 7: Bring the existing wizard tests to the new list**

`tests/accounts/test_consultation.py`, `test_consultation_progress.py`, `test_wizard_sequencing_errors.py`, `test_question_labels.py` and `tests/acceptance/helpers.py` walk the old 22 keys. Update each fixture to the new keys and values from `_ANSWERS` above (plus `academic_history`), and change any hard-coded total in a progress assertion: with `funding_dependency = MANDATORY` the applicable total is 14, with `OPTIONAL` it is 15. Delete assertions about `longer_program_justifications` sequencing — that question no longer exists; replace one of them with the self-funding skip rule tested in Step 1.

- [ ] **Step 8: Run to verify**

Run: `cd /home/orkhan/Desktop/tailored-programmes && POSTGRES_DB=tehsil_tailored uv run pytest tests/accounts tests/acceptance -q && POSTGRES_DB=tehsil_tailored uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Lint, types, migrations check, commit**

```bash
cd /home/orkhan/Desktop/tailored-programmes && uv run ruff check apps config tests scripts && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run
git -C /home/orkhan/Desktop/tailored-programmes add apps/accounts tests
git -C /home/orkhan/Desktop/tailored-programmes commit -m "feat(accounts): fifteen short steps instead of twenty-two, the degree prefilled from the transcript

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: One live read of a real sample transcript — real OCR, real Jev

**Files:**
- Test: `tests/documents/test_transcript_live.py` (marker `live`, excluded by default)

This is the only way to learn whether the whole reader — the OCR program and Jev through OpenRouter — reads a transcript at all; mocks cannot. It runs the OCR as the local child process (`OCR_FUNCTION_NAME` unset); the Lambda path is exercised by Task 2a's emulator run and, after deploy, by the first real upload. **Samples only** (owner, 2026-09-26): an official sample or specimen, or the owner's own transcript — never a student's. Real students' transcripts reach Jev only after TypeSafe's DPA is accepted and OpenRouter's terms are reviewed; that is a launch gate in the spec, not a flag in code. The file is read from the path in `TRANSCRIPT_SAMPLE`; the test skips without it, without the OCR interpreter, or without `TYPESAFE_API_KEY`. Its cost is a few thousand Jev input tokens — fractions of a cent.

- [ ] **Step 1: Write the test**

```python
"""One live read of a sample transcript: the real OCR program and the real Jev, nothing mocked but
the storage and the limiter.

Never a real person's transcript (spec T19): an official sample or specimen, from
TRANSCRIPT_SAMPLE. Skips without it, without the OCR interpreter, or without TYPESAFE_API_KEY.
"""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.conf import settings

from apps.documents.transcript import academic_record, read_transcript
from apps.documents.transcript_checks import highlights, key_numbers

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif("TRANSCRIPT_SAMPLE" not in os.environ, reason="no sample transcript"),
    pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="no TYPESAFE_API_KEY"),
    pytest.mark.skipif(not Path(settings.OCR_PYTHON).exists(), reason="no OCR interpreter"),
]


def test_a_sample_transcript_reads_into_courses():
    content = Path(os.environ["TRANSCRIPT_SAMPLE"]).read_bytes()
    document = SimpleNamespace(student_id="live-transcript-check")
    with (
        patch("apps.documents.transcript.open_document", return_value=content),
        patch("apps.documents.transcript.rate_limited", return_value=False),
    ):
        reading = read_transcript(document=document, names=frozenset())  # type: ignore[arg-type]
    record = academic_record(reading.content)
    print(
        record["institution"],
        len(record["courses"]),
        key_numbers(reading).model_dump(mode="json"),
        [highlight.model_dump() for highlight in highlights(reading)],
    )
    assert len(record["courses"]) >= 5
```

- [ ] **Step 2: Run it against a born-digital PDF and against a phone photo**

The key is the OpenRouter key; the route and model are the production ones (Task 3c). The samples are the git-ignored measurement set's: `tr_erzurum_1.pdf` (a published Turkish diploma supplement, text layer — read through OCR like every other upload) and `az_invented_diploma_elave_photo.jpg` (an invented Azerbaijani supplement, photographed).

```bash
cd /home/orkhan/Desktop/tailored-programmes && for sample in tr_erzurum_1.pdf az_invented_diploma_elave_photo.jpg; do
  OCR_PYTHON=$PWD/ocr/.venv/bin/python OCR_MODEL_HOME=$HOME/.paddlex \
  TYPESAFE_API_KEY=<the OpenRouter key> TYPESAFE_BASE_URL=https://openrouter.ai/api TYPESAFE_MODEL=typesafe/jev-1.13 \
  TRANSCRIPT_SAMPLE=.superpowers/ocr-eval/samples/$sample \
  POSTGRES_DB=tehsil_tailored uv run pytest tests/documents/test_transcript_live.py -m live -s -q
done
```

Expected: PASS twice, each printing the institution, the course count, the key numbers and the highlights. Compare the courses against the answer keys in `.superpowers/ocr-eval/key/` (`tr_erzurum_1.json`, `az_invented_diploma_elave.json`) by eye and record what Jev got wrong — this is the first measurement of Jev on transcripts, the input to spec §7 gate 1 and to `UNSURE_BELOW`'s first tuning. A test that fails on `len(courses) >= 5` is a finding, not a flake: record it the same way before changing anything.

- [ ] **Step 3: Commit**

```bash
git -C /home/orkhan/Desktop/tailored-programmes add tests/documents/test_transcript_live.py
git -C /home/orkhan/Desktop/tailored-programmes commit -m "test(documents): a live read of two sample transcripts, real OCR and real Jev

<paste the two printed lines, and what differed from the answer keys>

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
