# Transcript reader plan 3a: where every cell came from, and a picture of the doubtful ones — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every course row the reader cut, know which page, table, row and cell it came from and where that cell sits on the page; and for every row the student will be asked about, store a cropped image of the original cell that only that student (and their counsellor) can see.

**Architecture:** Azure already returns a polygon per cell; `ocr._azure_page` drops it. `OcrPage` gains a `cell_regions` grid of the same shape as `tables` (normalised 0–1 boxes, so no page unit is needed downstream). `transcript.Row` gains its origin (page slot, table, row). After assembly, the worker asks the sandboxed parser (`ocr/read_pages.py`, the OCR Lambda) to render and crop only the flagged rows' cells — an uploaded file is untrusted bytes and is never rendered beside the app's secrets (transcript spec §4.1). Crops are PNGs stored under the student's own prefix, so the existing erasure prefix delete removes them.

**Tech Stack:** Pydantic, Azure Document Intelligence layout JSON, pypdfium2 + Pillow inside the OCR program (its own Python 3.12 project), S3 via `apps/documents/storage.py`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-transcript-reader-redesign-design.md` §6.3 (R11: "the crop of the original cell beside the stored value"), §10; `docs/superpowers/specs/2026-10-15-onboarding-and-transcript-friction-design.md` variant 4.

## Global Constraints

- Lint `uv run ruff check .`; types `uv run mypy apps config`; never `ruff format`.
- App tests: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents`. OCR program: `UV_PYTHON=3.12 uv sync --project ocr --frozen` then `uv run --project ocr pytest ocr -q` (CLAUDE.md "Commands").
- No uploaded file is rendered or decoded in the web or worker process: rendering and cropping happen in `ocr/read_pages.py` only.
- A text-layer page has no reader doubt (`cell_confidence` None) and no Azure polygon: its rows get an origin and no crop. A row flagged only by an arithmetic check on a text-layer page is shown without a crop (3b states this to the student).
- Crops live under `tenants/<tenant>/students/<student>/` (`storage.delete_student_documents` purges that prefix) — never a new top-level prefix.
- Stored reading JSON stays backward compatible: rows and pages written before this plan (no `origin`, no `cell_regions`) still load.
- Commit with an explicit pathspec.

## Review Focus

1. **A table spanning two pages** — each cell belongs to its own page (`_azure_page` already splits on the cell's region); its region must be normalised against *that* page's width and height.
2. **A rotated or landscape photo** — Azure reports polygons in the page's own coordinate space with an `angle`; a crop computed from the bounding box of the polygon must still contain the cell.
3. **A row whose credit cell is blank** (a merged cell spanning rows fills only its top-left slot) — its origin must point at the slot that holds the text, or have no crop, never a crop of an empty box.
4. **A reading assembled from a retaken page** — the crop must come from the current page's upload, never a superseded one (`TranscriptPage.superseded_at`).
5. **The crop endpoint** — another student, another tenant, or a guessed ref must get 404, and a counsellor not assigned to the student must too.

---

### Task 1: `OcrPage` keeps each cell's region

**Files:**
- Modify: `apps/documents/azure_layout.py` (confirm the polygon, page width/height and unit are parsed; add them if absent)
- Modify: `apps/documents/ocr.py` (`OcrPage.cell_regions`, `_azure_page`)
- Test: `tests/documents/test_ocr.py` (or the file that already tests `_azure_page`; `grep -rln "_azure_page" tests`)

**Interfaces:**
- Produces: `OcrPage.cell_regions: tuple[tuple[tuple[Box | None, ...], ...], ...] = ()` where `Box = tuple[float, float, float, float]` — `(left, top, right, bottom)` as fractions of the page's width and height, the axis-aligned bounding box of the cell's polygon; `None` for a blank cell and every text-layer cell.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_azure_cell_carries_its_region_as_page_fractions():
    layout = _layout_with_one_cell(polygon=[100, 50, 300, 50, 300, 80, 100, 80],
                                   page_width=1000, page_height=2000, content="6")
    page = _azure_page(layout, layout.pages[0])
    assert page.cell_regions[0][0][0] == (0.1, 0.025, 0.3, 0.04)


def test_a_blank_cell_has_no_region():
    layout = _layout_with_one_cell(polygon=[100, 50, 300, 50, 300, 80, 100, 80],
                                   page_width=1000, page_height=2000, content="")
    assert _azure_page(layout, layout.pages[0]).cell_regions[0][0][0] is None


def test_a_rotated_polygon_is_boxed_by_its_extremes():
    layout = _layout_with_one_cell(polygon=[300, 50, 310, 80, 110, 90, 100, 60],
                                   page_width=1000, page_height=1000, content="A")
    assert _azure_page(layout, layout.pages[0]).cell_regions[0][0][0] == (0.1, 0.05, 0.31, 0.09)


def test_a_page_stored_before_regions_existed_still_loads():
    assert OcrPage.model_validate({"lines": [], "tables": [[["x"]]]}).cell_regions == ()
```

Build `_layout_with_one_cell` from the Azure response fixture the existing `_azure_page` tests use, adding `boundingRegions[{"pageNumber": 1, "polygon": [...]}]` to the cell and `width`/`height`/`unit` to the page.

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_ocr.py -k "region or rotated or before_regions"`
Expected: FAIL — `OcrPage` has no `cell_regions`.

- [ ] **Step 3: Implement**

In `azure_layout.py`, make sure `AzurePage` parses `width`, `height`, `unit` and each bounding region parses `polygon: tuple[float, ...]` (Azure's layout result carries both; add them to the Pydantic models with `extra` handling unchanged).

In `ocr.py`:

```python
Box = tuple[float, float, float, float]


def _box(polygon: Sequence[float], width: float, height: float) -> Box | None:
    """The polygon's axis-aligned bounding box as fractions of the page. A rotated
    photo's polygon is not a rectangle; its extremes still contain the cell."""
    if len(polygon) < 8 or not width or not height:
        return None
    xs, ys = polygon[0::2], polygon[1::2]
    return (round(min(xs) / width, 4), round(min(ys) / height, 4),
            round(max(xs) / width, 4), round(max(ys) / height, 4))
```

`OcrPage` gains `cell_regions: tuple[tuple[tuple[Box | None, ...], ...], ...] = ()`. In `_azure_page`, build a `regions` grid beside `conf`: for each cell in `mine`, `regions[r][cell.columnIndex] = _box(cell.boundingRegions[0].polygon, page.width, page.height) if text and cell.boundingRegions else None`. The page used is the cell's own page — `page` in this function, since `mine` already holds only this page's cells.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(transcript): every Azure cell keeps where it sits on its page" -- apps/documents/azure_layout.py apps/documents/ocr.py tests/documents/test_ocr.py
```

---

### Task 2: Every course row knows its origin

**Files:**
- Modify: `apps/documents/transcript.py` (`Row` gains `origin`; the row cutter fills it)
- Modify: `apps/documents/transcript_pages.py` (`assemble` passes each page's slot into the cutter; stored `rows` carry origin)
- Test: `tests/documents/test_transcript.py`, `tests/documents/test_transcript_pages.py`

**Interfaces:**
- Produces: `RowOrigin(slot: int, table: int, row: int, cells: dict[str, int])` — the page slot, the table's index on that page, the row's index in that table, and the column index of each named cell (`"title"`, `"credits"`, `"grade"`) that the cutter read. `Row.origin: RowOrigin | None = None` (None for rows read before this plan and rows cut from free lines rather than a table). Stored in `TranscriptReading.rows` under `"origin"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_cut_row_records_its_page_table_row_and_cells():
    reading = read_from_pages(_pages_with_one_course_table(slot=2), ...)
    row = next(r for r in reading.rows if r.title == "Organic Chemistry")
    assert row.origin == RowOrigin(slot=2, table=0, row=3, cells={"title": 0, "credits": 2, "grade": 3})


def test_rows_stored_before_origins_existed_still_load():
    stored = {"index": 0, "kind": "COURSE", "title": "X", "credits": "6", "grade": "A",
              "status": None}
    assert row_from_json(stored).origin is None
```

Use the same page fixtures `test_transcript.py` already builds (a two-page reading with a course table); `row_from_json` is whatever function `assemble`/`prefill` use today to load stored rows — if none exists, Task 2 adds it beside `Row`.

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_transcript.py -k origin`
Expected: FAIL — `RowOrigin` does not exist.

- [ ] **Step 3: Implement**

Add `RowOrigin` (frozen dataclass) and the `origin` field to `Row`. The cutter (`_Cut` in `transcript.py`) already walks page → table → row and knows which column Jev labelled credits/grade/title (it reads `_Cut.doubtful` from those columns' confidence): record `(slot, table_index, row_index, {name: column})` as it emits each row. `read_from_pages` receives each page's slot from `assemble` (today it receives pages in order; pass `(slot, OcrPage)` pairs). Serialise `origin` with the row wherever rows are dumped to `TranscriptReading.rows`.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(transcript): every course row records the page, table, row and cells it came from" -- apps/documents/transcript.py apps/documents/transcript_pages.py tests/documents/test_transcript.py tests/documents/test_transcript_pages.py
```

---

### Task 3: The sandboxed parser crops cells

**Files:**
- Modify: `ocr/read_pages.py` (new `crop` operation)
- Test: `ocr/tests/` (the OCR project's own test directory; `ls ocr`)

**Interfaces:**
- Produces: request `{"op": "crop", "page": <1-based page number in the file>, "boxes": [[l, t, r, b], ...], "dpi": 150}` with the file bytes as today's operations receive them → response `{"crops": ["<base64 PNG>", ...]}` in box order. A box is padded by 2% of the page on every side and clamped to the page. A PDF page is rendered with pypdfium2 at `dpi`; an image is opened with Pillow (`_flat`, which already flattens and size-checks images). Size limits: `_check_size` applies to the rendered page; each crop is at most 1600 px wide (scaled down if larger).

- [ ] **Step 1: Write the failing tests**

```python
def test_crop_returns_one_png_per_box_from_a_pdf_page(sample_pdf_bytes):
    out = handle({"op": "crop", "page": 1, "boxes": [[0.1, 0.1, 0.3, 0.2]], "dpi": 100},
                 sample_pdf_bytes)
    png = base64.b64decode(out["crops"][0])
    assert png.startswith(b"\x89PNG")


def test_crop_of_an_image_page(sample_jpeg_bytes):
    out = handle({"op": "crop", "page": 1, "boxes": [[0, 0, 0.5, 0.5]], "dpi": 100},
                 sample_jpeg_bytes)
    assert len(out["crops"]) == 1


def test_a_box_outside_the_page_is_clamped_not_an_error(sample_pdf_bytes):
    out = handle({"op": "crop", "page": 1, "boxes": [[0.9, 0.9, 1.4, 1.2]], "dpi": 100},
                 sample_pdf_bytes)
    assert out["crops"][0]


def test_a_page_number_past_the_end_is_refused(sample_pdf_bytes):
    with pytest.raises(ValueError):
        handle({"op": "crop", "page": 99, "boxes": [[0, 0, 1, 1]], "dpi": 100}, sample_pdf_bytes)
```

Use the program's existing entry point and fixtures (the name `handle` stands for whatever dispatches ops in `read_pages.py`; read `_answer` and the `__main__` block to find it).

- [ ] **Step 2: Run to verify failure**

Run: `UV_PYTHON=3.12 uv sync --project ocr --frozen && uv run --project ocr pytest ocr -q -k crop`
Expected: FAIL — unknown op.

- [ ] **Step 3: Implement**

```python
_CROP_PAD = 0.02
_CROP_MAX_WIDTH = 1600


def _page_image(data: bytes, page: int, dpi: int) -> Image.Image:
    if _type(data) == "pdf":
        document = pypdfium2.PdfDocument(data)
        if not 1 <= page <= len(document):
            raise ValueError("page out of range")
        pdf_page = document[page - 1]
        width, height = pdf_page.get_size()
        _check_size(width, height, dpi / 72)
        return pdf_page.render(scale=dpi / 72).to_pil()
    if page != 1:
        raise ValueError("page out of range")
    return _flat(data)


def crop(data: bytes, page: int, boxes: list[list[float]], dpi: int) -> dict:
    image = _page_image(data, page, dpi)
    width, height = image.size
    out = []
    for left, top, right, bottom in boxes:
        box = (
            max(0, int((left - _CROP_PAD) * width)), max(0, int((top - _CROP_PAD) * height)),
            min(width, int((right + _CROP_PAD) * width)), min(height, int((bottom + _CROP_PAD) * height)),
        )
        piece = image.crop(box)
        if piece.width > _CROP_MAX_WIDTH:
            piece = piece.resize((_CROP_MAX_WIDTH, round(piece.height * _CROP_MAX_WIDTH / piece.width)))
        buffer = io.BytesIO()
        piece.save(buffer, format="PNG")
        out.append(base64.b64encode(buffer.getvalue()).decode())
    return {"crops": out}
```

Register `"crop"` in the operation dispatch beside `inventory`/`inspect`. The program's bandit run (`ocr/read_pages.py` is in CLAUDE.md's bandit command) must stay clean.

- [ ] **Step 4: Run the tests**

Run: `uv run --project ocr pytest ocr -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(ocr): the sandboxed parser crops cells from a page" -- ocr/read_pages.py ocr/tests
```

---

### Task 4: Crops for the rows the student will be asked about

**Files:**
- Modify: `apps/documents/ocr.py` (a `crop_cells(document, page, boxes) -> list[bytes]` beside the existing inventory call, same transport: Lambda in production, child process locally)
- Modify: `apps/documents/storage.py` (`crop_key`, `store_crop`, `read_crop`)
- Modify: `apps/documents/models.py` (`TranscriptReading.crops = JSONField(default=dict)`), new migration
- Modify: `apps/documents/transcript_pages.py` (`assemble`: after highlights, crop each row-scoped highlight's credits/grade cell — or title cell for `unsure` — that has a region)
- Modify: `apps/audit/redaction.py` (`crops` into the `TranscriptReading` REDACT fields)
- Test: `tests/documents/test_transcript_pages.py`, `tests/documents/test_storage.py`

**Interfaces:**
- Consumes: Task 1 `cell_regions`, Task 2 `Row.origin`, Task 3 `crop` op.
- Produces: `TranscriptReading.crops: dict[str, str]` mapping `"<row index>:<cell name>"` to an object key `tenants/<t>/students/<s>/transcript-crops/<reading id>/<row>-<cell>.png`; `storage.read_crop(reading, ref) -> bytes`. A cell with no region (text-layer page, blank cell, pre-plan reading) has no entry.

- [ ] **Step 1: Write the failing tests**

```python
def test_assembly_crops_only_the_flagged_rows_cells(fake_crop, ...):
    reading = _assemble_with(rows=[_row(0, "Calculus"), _row(1, "Physics", low_confidence=True)])
    assert set(reading.crops) == {"1:credits", "1:grade"}
    assert fake_crop.calls == [(_upload_of_slot(1), 1, [_region(1, "credits"), _region(1, "grade")])]


def test_a_text_layer_row_gets_no_crop(...):
    reading = _assemble_with(rows=[_row(0, "Calculus", text_layer=True, credit_mismatch=True)])
    assert reading.crops == {}


def test_a_retaken_page_is_cropped_from_its_current_upload(...):
    ...


def test_crops_are_under_the_students_prefix():
    key = crop_key(tenant_id=T, student_id=S, reading_id=R, ref="1:grade")
    assert key.startswith(f"tenants/{T}/students/{S}/")


def test_a_crop_failure_never_fails_the_reading(fake_crop_raising, caplog, ...):
    reading = _assemble_with(rows=[_row(0, "Physics", low_confidence=True)])
    assert reading.crops == {}
    assert "transcript crop failed" in caplog.text
```

`fake_crop` replaces `ocr.crop_cells` the way the existing tests replace `ocr.inventory`.

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_transcript_pages.py -k crop tests/documents/test_storage.py -k crop`
Expected: FAIL.

- [ ] **Step 3: Implement**

- `ocr.crop_cells`: build `{"op": "crop", "page": number, "boxes": [...], "dpi": 150}` and call the parser exactly as the inventory is called (same function name, same child-process path locally); decode the base64 PNGs. Any transport or parser error raises `OcrUnavailable`.
- `assemble`: after `highlights` is computed, group row-scoped highlights by the row's origin page; for each page, fetch its current upload (`TranscriptPage` with `superseded_at__isnull=True` for that slot) and its page number in the file, call `crop_cells` once per page, store each PNG with `store_crop`, and write `reading.crops`. Wrap the whole step: on `OcrUnavailable`, log `"transcript crop failed for reading %s: %s"` with the vendor message and leave `crops` empty — the reading is still assembled (3b shows the row without a picture).
- Which cells: `low_confidence` → credits and grade; `unsure` on a row → title; `credit_out_of_range` → credits; `grade_above_scale` → grade; `credit_total_mismatch` (semester scope) → no crop (it is about a sum, not one cell).
- Migration adds `crops`; redaction adds it to `TranscriptReading`'s REDACT tuple. The objects themselves are erased by `delete_student_documents`' student-prefix purge.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents tests/audit tests/tenancy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/migrations/<new>.py
git commit -m "feat(transcript): a picture of each doubtful cell, cut in the sandbox and kept under the student's prefix" -- apps/documents/ocr.py apps/documents/storage.py apps/documents/models.py apps/documents/migrations/<new>.py apps/documents/transcript_pages.py apps/audit/redaction.py tests/documents/test_transcript_pages.py tests/documents/test_storage.py
```

---

### Task 5: The student (and their counsellor) can see a crop

**Files:**
- Modify: `apps/documents/api.py` (`GET api/documents/transcript/crop/<reading_id>/<ref>`), `apps/documents/urls.py`
- Test: `tests/documents/test_api.py`

**Interfaces:**
- Produces: `transcript_crop(request, reading_id, ref) -> HttpResponse` (`image/png`, `Cache-Control: private, max-age=300`). Allowed: the reading's own student; the assigned counsellor (`storage.may_read_student`). Anything else, an unknown ref, or a reading in another tenant: 404.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_student_sees_their_own_crop(student_client, reading_with_crop):
    response = student_client.get(f"/api/documents/transcript/crop/{reading_with_crop.id}/1:grade")
    assert response.status_code == 200 and response["Content-Type"] == "image/png"


def test_another_student_gets_404(other_student_client, reading_with_crop):
    assert other_student_client.get(
        f"/api/documents/transcript/crop/{reading_with_crop.id}/1:grade").status_code == 404


def test_an_unknown_ref_gets_404(student_client, reading_with_crop):
    assert student_client.get(
        f"/api/documents/transcript/crop/{reading_with_crop.id}/9:grade").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_api.py -k crop`
Expected: FAIL — 404 for the owner too (no route).

- [ ] **Step 3: Implement**

A view in the style of the existing student endpoints (`_student_endpoint` for the student; the counsellor path through `storage.may_read_student`): load the reading with the tenant manager, check the requester, look up `reading.crops[ref]`, stream `storage.read_crop`. The web role reads only tenant tables and the bucket — no catalogue — so it is safe under `runtime_web` (`.claude/rules/row-level-security.md`).

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(transcript): the student and their counsellor can see a doubtful cell's picture" -- apps/documents/api.py apps/documents/urls.py tests/documents/test_api.py
```

---

### Task 6: Every gate

```bash
uv run ruff check .
uv run mypy apps config
uv run --project ocr pytest ocr -q
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py check
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q
uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py
```
