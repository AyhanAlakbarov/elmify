# CV Stage 1: Layout and Typography Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CVs render with a clean text layer, honest dates, Charis SIL (or the programme's named font through a licensed look-alike), and a one-time tighter layout when a binding page cap would otherwise block.

**Architecture:**
- **Templates.** Date wording moves into one template tag (`date_range`) that reads a `today` value from the render context.
- **Content funnel.** The not-yet-started filter sits on the shared funnel (`europass_content`), so every render path sees it.
- **Fonts.** A new module, `cv_fonts.py`, turns the existing CV `font` rule into a resolved family and point size, and `_render_pdf` passes them to `cv_base.html`.
- **Checks.** A `font` checker joins `_CHECKERS`.
- **Tight layout.** `render_cv_with_warnings` retries a failing BINDING `max_pages` once with `compact=True`.

**Tech Stack:** Django templates, WeasyPrint 70, pypdf, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md` §3 (and §3.0's path table).

## Decisions made in this plan
1. **Wording.**
   - "(expected)" applies to any dated entry whose end date is after `today`, not only degrees. A future end is an expected end for a post too.
   - An open-ended entry reads "Present".
2. **A not-yet-started entry is dropped from the funnel unless that would empty Education** (`CVContent.education` has `min_length=1`). In that case the future entries stay and read "Admitted; starts Oct 2026". A CV with no education is worse than one with an announced place.
3. **Funder templates fall back to `date.today()`.** `_funder_dispatch` callables take only content, and SISGP and Rhodes are fixed layouts, so they get no `today` plumbing.
4. **The CSS font name comes only from our own table.** It is never copied from the rule's text, which comes from a third-party page. The font name sits inside a `<style>` block, so this is the injection guard.
5. **The `font` checker verifies the family only**, from the PDF's embedded font names. The point size is honoured in the template but not re-measured.
6. **The tight retry uses template context (`compact`), not a CSS class on `<body>`.** `@page` margins cannot be scoped by a body class.
7. **Local fonts match CI.** They are installed from the distribution's own packages with `apt-get download` + `dpkg -x` into `~/.local/share/fonts` (no root), so local metrics match the CI runner.

## Global Constraints
- Master's applicants only. English CVs only (MVP).
- Lint only: `uv run ruff check .`, never `ruff format`.
- Types: `uv run mypy apps config`.
- Tests: `POSTGRES_DB=elmify_cv_engine_design uv run pytest -q`.
- `uv run python manage.py makemigrations --check --dry-run` must stay clean. This stage adds no migration.
- Worktree `/home/orkhan/Desktop/cv-engine-design`, branch `claude/cv-engine-quality-design`. Use `git -C` for every git command. Never push to `master`.
- Never change what a CV says: every change here is layout, wording of dates, or font.
- `_RefusingFetcher` stays: fonts are system fonts, never file or URL loads.

## Review Focus
1. **The only education entry starts in the future** (an admitted PhD). Expected: it still prints, as "Admitted; starts Oct 2026", and the render does not crash on an empty Education section. Pinned in Task 2.
2. **A programme's font rule is plain text from a third-party page,** for example `Arial; } body { display:none`. Expected: the CSS gets only a family from our table, never that text. Pinned in Task 4.
3. **A CV with Cyrillic text where the programme names Cambria** (Caladea has no Cyrillic). Expected: Liberation Serif plus an advisory note. Pinned in Task 4.
4. **A machine without Charis installed.** Expected: a test fails with an install hint instead of passing on DejaVu metrics. Pinned in Task 3.
5. **A one-page binding cap a CV misses by a few lines.** Expected: the compact retry passes it, and a near-empty compact last page is reported, not blocking. Pinned in Task 5.

---

### Task 1: Clean text layer

**Files:**
- Modify: `apps/documents/templates/documents/cv_base.html` (the `<style>` block: `ul`/`li` rules near "One indent for every list")
- Modify: `apps/documents/templates/documents/cv_funder_rhodes.html` (`ul`, `li` rules, lines ~25–26)
- Modify: `apps/documents/templates/documents/cv_funder_sisgp.html` (`ul`, `li` rules, lines ~20–21)
- Test: `tests/documents/test_render.py`

**Interfaces:**
- Consumes: `render_cv(content, variant=...)`; test helpers `_content`, `_text`, `_many_experience`.
- Produces: no new names. Every `<li>` draws its marker as inline text.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_render.py`)

```python
# --- Stage 1, §3.1: the text layer reads in order -----------------------------

def _bullet_content():
    return _content(
        experience=(
            ExperienceEntry(
                employer="EPFL",
                title="Research Intern",
                city="Lausanne",
                country="CH",
                start_date="2025-09-01",
                end_date="2025-12-31",
                bullets=(
                    "Benchmarked PyTorch models on peptide data.",
                    "Wrote the evaluation scripts.",
                ),
            ),
        )
    )


@pytest.mark.parametrize("variant", ["STANDARD", "GERMAN_TABULAR", "EUROPASS"])
def test_each_bullet_marker_sits_on_its_own_line(variant):
    text = _text(render_cv(_bullet_content(), variant=variant))
    lines = [line.strip() for line in text.splitlines()]
    assert "•" not in lines, "a marker extracted on a line of its own"
    assert any(line.startswith("• Benchmarked") for line in lines)


def test_kerning_does_not_split_a_word():
    text = _text(render_cv(_bullet_content(), variant="STANDARD"))
    assert "PyTorch" in text.replace("\n", " ")
    assert "PyT orch" not in text
```

- [ ] **Step 2: Run them and see them fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_render.py -k "marker_sits or kerning" -v`
Expected: FAIL. Either a bare "•" line is present, or "PyT orch".

- [ ] **Step 3: Change the CSS**

In `cv_base.html`, replace the two rules

```css
  ul { margin: 2pt 0 0; padding-left: 14pt; }
  li { margin-bottom: 1pt; }
```

with

```css
  /* The marker is drawn as inline text (li::before), not as a list marker.
     WeasyPrint writes list markers to the content stream after the page's
     text, so pypdf -- our own upload reader and page-fill check -- extracted
     every "•" as a line at the bottom of the page (R-043, measured
     2026-10-12). font-kerning: none stops pypdf splitting "PyTorch" into
     "PyT orch" at a kerned pair. */
  body { font-kerning: none; }
  ul { margin: 2pt 0 0; padding-left: 14pt; list-style: none; }
  li { margin-bottom: 1pt; }
  li::before { content: "•\00a0"; margin-left: -9pt; display: inline-block; width: 9pt; }
```

Add the same four lines (`body { font-kerning: none; }`, the `ul` with `list-style: none`, `li`, `li::before`) to the `<style>` blocks of `cv_funder_rhodes.html` and `cv_funder_sisgp.html`, replacing their existing `ul`/`li` rules.

- [ ] **Step 4: Run the tests and the whole render module**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_render.py tests/documents/test_funder_templates*.py -q`
Expected: the new tests PASS. For any existing test that now fails, read the failure:
- a page-count change is investigated: the marker width must not grow a line;
- the hyphenation rule (spec §3.1) allows "opti-" at a line end.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/templates/documents/cv_base.html apps/documents/templates/documents/cv_funder_rhodes.html apps/documents/templates/documents/cv_funder_sisgp.html tests/documents/test_render.py
git -C /home/orkhan/Desktop/cv-engine-design commit -m "fix(cv): bullet markers and kerning keep the PDF text layer in reading order

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Honest dates

**Files:**
- Modify: `apps/documents/templatetags/cv_dates.py` (add `date_range`)
- Modify: every template line `{{ X.start_date|month_year }} – {{ X.end_date|month_year:"present" }}`. Find them with
  `grep -rn 'month_year:"present"' apps/documents/templates/`.
  There are 12 lines, in:
  - `cv_base.html`
  - `cv_german_tabular.html`
  - `_cv_experience.html` (3)
  - `_cv_research.html` (2)
  - `cv_funder_rhodes.html` (2)
  - `cv_funder_sisgp.html` (3)
- Modify: `apps/documents/render.py`:
  - `europass_content` and `render_cv_with_warnings` gain `today: date | None = None`;
  - `render_cv` passes it through;
  - `_render_pdf` takes `today` and adds it to the template context;
  - a new `without_future_starts` function.
- Test: `tests/documents/test_render.py`, plus the three existing "present" tests.

**Interfaces:**
- Produces: `date_range` (template tag, `takes_context=True`) and `without_future_starts(content: CVContent, today: date) -> CVContent`.
- Produces: `europass_content(content, directives, *, today: date | None = None) -> tuple[CVContent, bool]`.
- Produces: `render_cv_with_warnings(..., today: date | None = None)` and `render_cv(..., today: date | None = None)`.
- Produces: `_render_pdf(..., today: date)`.

- [ ] **Step 1: Write the failing tests**

```python
# --- Stage 1, §3.2: dates say what is true on the day of the render ----------

_TODAY = date(2026, 10, 13)


def test_a_degree_ending_after_today_reads_expected():
    text = _text(render_cv(
        _education_content(start_date="2024-09-01", end_date="2026-06-30"),
        variant="STANDARD", today=date(2026, 3, 1),
    )).replace("\n", " ")
    assert "Sep 2024 – Jun 2026 (expected)" in text


def test_a_finished_degree_has_no_expected_label():
    text = _text(render_cv(_education_content(), variant="STANDARD", today=_TODAY))
    assert "(expected)" not in text


def test_an_open_ended_entry_reads_present_capitalised():
    text = _text(render_cv(_education_content(end_date=None), variant="STANDARD", today=_TODAY))
    assert "Present" in text


def test_a_post_not_yet_started_is_left_off():
    future = ExperienceEntry(
        employer="Future Lab", title="Research Assistant", city="Paris", country="FR",
        start_date="2026-11-01",
    )
    text = _text(render_cv(_content(experience=(future,)), variant="STANDARD", today=_TODAY))
    assert "Future Lab" not in text


def test_the_only_degree_starting_later_still_prints_as_admitted():
    phd = EducationEntry(
        degree_as_awarded="PhD in Chemoinformatics",
        institution_original="Université de Strasbourg",
        city="Strasbourg", country="FR", start_date="2026-11-01",
    )
    text = _text(render_cv(_content(education=(phd,)), variant="STANDARD", today=_TODAY))
    text = text.replace("\n", " ")
    assert "PhD in Chemoinformatics" in text
    assert "Admitted; starts Nov 2026" in text
    assert "Present" not in text


def test_the_future_filter_reaches_the_europass_payload():
    future = ExperienceEntry(
        employer="Future Lab", title="RA", city="Paris", country="FR", start_date="2026-11-01",
    )
    clean, _ = europass_content(_content(experience=(future,)), (), today=_TODAY)
    assert clean.experience == ()
```

Import `europass_content` from `apps.documents.render` and `EducationEntry`/`ExperienceEntry` if the test module does not already. Then update the three existing tests:

```python
def test_open_ended_entry_still_renders_present():
    text = _text(render_cv(_education_content(end_date=None), variant="STANDARD"))
    assert "Present" in text
```

- `test_an_open_ended_research_entry_reads_as_ongoing`: assert `"Jan 2026 – Present"`.
- `test_an_open_gap_row_closes_at_the_next_post`: assert `"present" not in text.lower()`.

- [ ] **Step 2: Run them and see them fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_render.py -k "expected or present or not_yet_started or admitted or future_filter" -v`
Expected: FAIL, with `TypeError: unexpected keyword argument 'today'` and lowercase "present".

- [ ] **Step 3: Add the template tag** (`apps/documents/templatetags/cv_dates.py`, below `month_year`)

```python
@register.simple_tag(takes_context=True)
def date_range(context: template.Context, start: date | None, end: date | None) -> str:
    """One entry's dates, true on the day of the render (spec §3.2).

    "Present" for an open entry; "(expected)" when the end is after today; an
    entry that has not started yet reads "Admitted; starts Nov 2026". It is
    only ever printed when it is the CV's sole education entry -- the funnel
    (render.without_future_starts) drops every other future start. ``today``
    comes from the render context so tests can fix it; funder templates have
    none and fall back to the real date.
    """
    today = context.get("today") or date.today()
    if start is not None and start > today:
        return f"Admitted; starts {month_year(start)}"
    if end is None:
        return f"{month_year(start)} – Present"
    label = " (expected)" if end > today else ""
    return f"{month_year(start)} – {month_year(end)}{label}"
```

- [ ] **Step 4: Replace the 12 template lines**

Each `{{ entry.start_date|month_year }} – {{ entry.end_date|month_year:"present" }}` becomes `{% date_range entry.start_date entry.end_date %}`. Keep the surrounding markup and any `{% if entry.start_date %}` guards exactly as they are. Every one of these templates already has `{% load cv_dates %}`. Check with `grep -L "load cv_dates" <file>` and add the load line where it is missing.

- [ ] **Step 5: Add the filter and the `today` parameter** (`apps/documents/render.py`)

Below `without_duplicated_posts`:

```python
def without_future_starts(content: CVContent, today: date) -> CVContent:
    """Leave out what has not started yet (spec §3.2).

    A place accepted but not begun is not part of the record, and printing
    it as "Oct 2026 – present" said the student was already enrolled.
    Education keeps its future entries when they are all it has --
    CVContent requires one education entry, and a CV with none is worse
    than one announcing an admitted place (cv_dates.date_range prints it
    as "Admitted; starts ...").
    """

    def started(entry: object) -> bool:
        start = getattr(entry, "start_date", None)
        return start is None or start <= today

    education = tuple(e for e in content.education if started(e)) or content.education
    return content.model_copy(
        update={
            "education": education,
            "experience": tuple(e for e in content.experience if started(e)),
            "research": tuple(e for e in content.research if started(e)),
            "timeline": tuple(e for e in content.timeline if started(e)),
        }
    )
```

Then change the signatures and call sites:
- `europass_content(content, directives, *, today: date | None = None)`. Its body becomes:

```python
    clean = apply_directives(
        reverse_chronological(
            without_future_starts(
                without_duplicated_posts(hygienic_content(content)), today or date.today()
            )
        ),
        directives,
    )
```

- `render_cv_with_warnings(..., today: date | None = None)`. Its first lines become:

```python
    today = today or date.today()
    clean, _ = europass_content(content, directives, today=today)
```

  Pass `today=today` to both `_render_pdf` calls inside it, and use `date_of_issue=today if wants_date else None`, replacing `date.today()`.
- `render_cv(..., today: date | None = None)` passes `today=today` through.
- `_render_pdf(..., today: date)` adds `"today": today` to the `render_to_string` context dict.

- [ ] **Step 6: Run the date tests, then the documents suite**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents -q`
Expected: the new tests PASS. Fix any other test that pins lowercase "present" or an end date now after the real today, by passing `today=` explicitly. Never by loosening the assertion.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents tests/documents
git -C /home/orkhan/Desktop/cv-engine-design commit -m "fix(cv): dates say Present, (expected) and never a not-yet-started place as current

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Charis SIL as the default face, installed everywhere it renders

**Files:**
- Modify: `apps/documents/templates/documents/cv_base.html` (`body` font-family and its comment; `@bottom-center` gets `font-family`)
- Modify: `Dockerfile`, the `apt-get install` that lists `fonts-dejavu-core fonts-liberation` (~line 58)
- Modify: `.github/workflows/ci.yml`, a new step before the `uv run pytest -q` step (~line 89)
- Create: `apps/documents/cv_fonts.py`, with only `embedded_font_names` for now
- Test: `tests/documents/test_cv_fonts.py`

**Interfaces:**
- Produces: `cv_fonts.embedded_font_names(pdf_bytes: bytes) -> frozenset[str]`. Names come without the subset prefix, for example `"CharisSIL"` or `"CharisSIL-Bold"`.
- Produces: `cv_fonts.DEFAULT_FAMILY = "Charis SIL"`.

- [ ] **Step 1: Install the fonts locally, from the distribution's packages, without root**

```bash
cd /tmp/claude-1000/-home-orkhan-Desktop-elmify/a35e3617-8932-4d8d-9130-d657a872d603/scratchpad
mkdir -p debfonts && cd debfonts
apt-get download fonts-sil-charis fonts-crosextra-carlito fonts-crosextra-caladea fonts-ebgaramond
for f in *.deb; do dpkg -x "$f" root; done
mkdir -p ~/.local/share/fonts/elmify-cv && find root -name '*.ttf' -exec cp {} ~/.local/share/fonts/elmify-cv/ \;
fc-cache -f ~/.local/share/fonts && fc-list : family | grep -i -E "charis|carlito|caladea|garamond"
```

Expected: the four families listed. If `apt-get download` is unavailable, stop and report BLOCKED with the error. Do not substitute a different font source.

- [ ] **Step 2: Write the failing tests** (`tests/documents/test_cv_fonts.py`)

```python
import pytest

from apps.documents.cv_fonts import DEFAULT_FAMILY, embedded_font_names
from apps.documents.render import render_cv
from tests.documents.test_render import _content

_INSTALL_HINT = (
    "Charis SIL is not installed, so the CV rendered in a fallback face with different "
    "page counts. Install fonts-sil-charis (CI does; locally see "
    "docs/superpowers/plans/2026-10-13-cv-stage-1-layout-and-typography.md, Task 3 Step 1)."
)


def _faces(artifact):
    return embedded_font_names(artifact.pdf_bytes)


@pytest.mark.parametrize("variant", ["STANDARD", "GERMAN_TABULAR", "EUROPASS"])
def test_the_default_face_is_charis_and_nothing_else(variant):
    faces = _faces(render_cv(_content(), variant=variant))
    assert any("Charis" in face for face in faces), _INSTALL_HINT
    assert not any("DejaVu" in face or "Noto" in face for face in faces), faces


def test_every_letter_our_students_write_is_in_the_default_face():
    sample = "Ə ə Ğ ğ İ ı Ş ş Ç ç Ö ö Ü ü — Привет, Жанна Щукина — Straße — Élève, cœur"
    content = _content(summary=sample)
    faces = _faces(render_cv(content, variant="STANDARD"))
    assert faces and all("Charis" in face for face in faces), faces


def test_default_family_is_the_installed_debian_name():
    assert DEFAULT_FAMILY == "Charis SIL"
```

If `_content(summary=...)` does not render the summary on STANDARD, put the sample in an experience bullet instead. The test needs the letters on the page, in regular, bold (degree title) and italic (gloss).

- [ ] **Step 3: Run and see them fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fonts.py -v`
Expected: FAIL with `ModuleNotFoundError: apps.documents.cv_fonts`.

- [ ] **Step 4: Create `apps/documents/cv_fonts.py`**

```python
"""Which face a CV is set in, and which faces a rendered PDF actually embeds.

Spec: docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md §3.5.
Every face named here is a system font installed from a Debian package
(Dockerfile, ci.yml): render._RefusingFetcher refuses every file and URL
load, so a font that is not installed silently falls back to another face
with different letter widths -- and page counts gate BINDING max_pages.
"""

from __future__ import annotations

import io

from pypdf import PdfReader

#: fonts-sil-charis 6.200 in Debian trixie names its family "Charis SIL".
DEFAULT_FAMILY = "Charis SIL"


def embedded_font_names(pdf_bytes: bytes) -> frozenset[str]:
    """The BaseFont names a PDF embeds, without the subset prefix ("ABCDEF+")."""
    names: set[str] = set()
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        resources = page.get("/Resources")
        fonts = resources.get_object().get("/Font") if resources is not None else None
        if fonts is None:
            continue
        for ref in fonts.get_object().values():
            base = str(ref.get_object().get("/BaseFont", "")).lstrip("/")
            if base:
                names.add(base.split("+", 1)[-1])
    return frozenset(names)
```

- [ ] **Step 5: Set the face in `cv_base.html`**

Replace `body { font-family: "DejaVu Sans", "Helvetica", sans-serif; ...}` and rewrite the comment above it to keep its rule (the installed face comes first) and record the change:

```css
  /* Charis SIL, then DejaVu Sans. Owner decision 2026-10-12 (spec §3.5):
     Charis is SIL OFL, so it may be embedded in the PDFs we hand out, and it
     covers Azerbaijani Ə ə and Cyrillic in four styles. The rule this comment
     used to state still holds -- the face named first must be one that is
     INSTALLED, or a local render and production differ: fonts-sil-charis is
     installed by the Dockerfile and by ci.yml, and test_cv_fonts fails with an
     install hint on a machine without it. DejaVu Sans stays second as the
     installed fallback. {{ font_family }} and {{ font_pt }} come from
     cv_fonts.choose_font -- never from a programme page's text. */
  body { font-family: "{{ font_family|default:'Charis SIL' }}", "DejaVu Sans", sans-serif; font-size: {{ font_pt|default:11 }}pt; line-height: 1.3; }
```

Give the footer the same face, inside `@bottom-center { ... }`:
`font-family: "{{ font_family|default:'Charis SIL' }}", "DejaVu Sans", sans-serif;`

- [ ] **Step 6: Install the fonts in the image and in CI**

`Dockerfile`: add the packages to the existing `apt-get install` list:

```dockerfile
    fonts-dejavu-core fonts-liberation \
    fonts-sil-charis fonts-crosextra-carlito fonts-crosextra-caladea fonts-ebgaramond \
```

Extend the comment above the `RUN` with one paragraph:

```
# fonts-sil-charis is the CV's own face (spec 2026-10-12-cv-engine-quality-design §3.5); Carlito,
# Caladea and EB Garamond are the licensed, metric-compatible stand-ins for Calibri, Cambria and
# Garamond when a PROGRAMME names one, exactly as fonts-liberation is for Times New Roman and Arial.
# All four are SIL OFL and in Debian trixie main (checked 2026-10-13). Gelasio (Georgia) has no
# package, so Georgia falls back to the default with a note.
```

`.github/workflows/ci.yml`: a step immediately before the step whose `run` contains `uv run pytest -q --ignore=tests/portals/test_extension_bundle.py`:

```yaml
      # The CV renders in Charis SIL and in metric-compatible stand-ins for fonts a
      # programme names (spec 2026-10-12-cv-engine-quality-design §3.5). Tests run on
      # this runner, not in the image, so without these a render silently falls back
      # to DejaVu and every page-count test measures the wrong document.
      - run: >-
          sudo apt-get update && sudo apt-get install --no-install-recommends -y
          fonts-sil-charis fonts-crosextra-carlito fonts-crosextra-caladea
          fonts-ebgaramond fonts-liberation fonts-dejavu-core
```

- [ ] **Step 7: Run the font tests, then every render and page-count test**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents -q`
Expected: `test_cv_fonts.py` PASSES. For each test that changes:
- **Page count or final-page fill:** re-render, read the numbers, and decide whether the test's intent still holds with the new metrics. Update the fixture size, not the assertion's meaning. Record each one in the task report.
- **`test_max_length_thesis_prose_still_fits_a_one_page_cap`:** keep its purpose (two 1,000-character fields fit one page). If Charis no longer fits, that is a real finding; report it rather than shrinking the input.

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents/cv_fonts.py apps/documents/templates/documents/cv_base.html Dockerfile .github/workflows/ci.yml tests/documents
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): Charis SIL as the CV face, installed in the image, CI and locally

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Honour the programme's font rule

**Files:**
- Modify: `apps/documents/cv_fonts.py` (add `LOOKALIKE`, `NO_CYRILLIC`, `FontChoice`, `parse_font_rule`, `choose_font`)
- Modify: `apps/documents/render.py`:
  - `_render_pdf` gains `font_family: str` and `font_pt: float`;
  - `render_cv_with_warnings` calls `choose_font` and passes the result;
  - `_check_font` is added to `_CHECKERS`.
- Test: `tests/documents/test_cv_fonts.py`

**Interfaces:**
- Consumes: `ConstraintRule` (`apps/documents/constraints.py`) with `key == "font"`. Its `value` is the page's printed detail: a family ("Arial"), a size ("11"), or both ("Times New Roman, 12 pt"). One `font` rule per page (`rule_sinks.py`).
- Produces: `parse_font_rule(value: object) -> tuple[str | None, float | None]`.
- Produces: `choose_font(rule: ConstraintRule | None, content: CVContent) -> FontChoice`, where `FontChoice` is a frozen dataclass of `family: str`, `pt: float` and `note: str | None`.

- [ ] **Step 1: Write the failing tests** (append to `tests/documents/test_cv_fonts.py`)

```python
from apps.documents.constraints import ConstraintRule, Enforcement
from apps.documents.cv_fonts import choose_font, parse_font_rule
from apps.documents.render import render_cv_with_warnings


def _font_rule(value):
    return ConstraintRule(
        rule_id="P-FONT", key="font", value=value,
        enforcement=Enforcement.ADVISORY_HIGH_RISK,
        rule_text="Use Times New Roman, 12 pt.", source_url="", scope="PROGRAMME",
    )


@pytest.mark.parametrize(("value", "expected"), [
    ("Arial", ("Arial", None)),
    ("11", (None, 11.0)),
    ("Times New Roman, 12 pt", ("Times New Roman", 12.0)),
    ("Calibri 11pt", ("Calibri", 11.0)),
])
def test_parse_font_rule(value, expected):
    assert parse_font_rule(value) == expected


@pytest.mark.parametrize(("named", "face"), [
    ("Times New Roman", "Liberation Serif"), ("Arial", "Liberation Sans"),
    ("Helvetica", "Liberation Sans"), ("Calibri", "Carlito"), ("Cambria", "Caladea"),
    ("Garamond", "EB Garamond"), ("Verdana", "DejaVu Sans"),
])
def test_a_named_font_maps_to_its_licensed_lookalike(named, face):
    assert choose_font(_font_rule(named), _content()).family == face


def test_a_font_with_no_lookalike_keeps_the_default_and_says_so():
    choice = choose_font(_font_rule("Georgia"), _content())
    assert choice.family == "Charis SIL"
    assert "Georgia" in choice.note


def test_page_text_never_reaches_the_css():
    choice = choose_font(_font_rule('Arial; } body { display:none'), _content())
    assert choice.family == "Charis SIL"


def test_caladea_gives_way_to_liberation_serif_for_cyrillic():
    choice = choose_font(_font_rule("Cambria"), _content(summary="Жанна Щукина"))
    assert choice.family == "Liberation Serif"
    assert "Cyrillic" in choice.note


def test_the_named_face_is_embedded_and_the_font_rule_passes():
    artifact, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_font_rule("Times New Roman, 12 pt"),)
    )
    assert any("LiberationSerif" in face for face in embedded_font_names(artifact.pdf_bytes))
    assert not [v for v in violations if v.rule.key == "font"]


def test_an_unhonoured_font_is_reported_not_blocking():
    _, violations = render_cv_with_warnings(
        _content(), variant="STANDARD", constraints=(_font_rule("Georgia"),)
    )
    font = [v for v in violations if v.rule.key == "font"]
    assert font and "Georgia" in font[0].detail
```

- [ ] **Step 2: Run and see them fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_cv_fonts.py -v`
Expected: FAIL with `ImportError: cannot import name 'choose_font'`.

- [ ] **Step 3: Add the resolution** (append to `apps/documents/cv_fonts.py`)

```python
import re
from dataclasses import dataclass

from .constraints import ConstraintRule
from .schemas import CVContent

#: A font a programme names -> the installed, licensed face with the same
#: letter widths (so page limits measure the same document). Liberation and
#: DejaVu come from fonts-liberation / fonts-dejavu-core; the rest from the
#: packages named in the Dockerfile. Georgia is absent on purpose: Gelasio
#: has no Debian package (checked 2026-10-13).
LOOKALIKE: dict[str, str] = {
    "times new roman": "Liberation Serif",
    "times": "Liberation Serif",
    "arial": "Liberation Sans",
    "helvetica": "Liberation Sans",
    "calibri": "Carlito",
    "cambria": "Caladea",
    "garamond": "EB Garamond",
    "verdana": "DejaVu Sans",
}

#: Faces with no Cyrillic glyphs, and what replaces them when the CV has any.
NO_CYRILLIC: dict[str, str] = {"Caladea": "Liberation Serif"}

DEFAULT_PT = 11.0
_SIZE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:pt|points?)?\b", re.IGNORECASE)
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


@dataclass(frozen=True)
class FontChoice:
    family: str
    pt: float
    note: str | None = None


def parse_font_rule(value: object) -> tuple[str | None, float | None]:
    """Split a page's printed font detail into (family, point size)."""
    text = str(value or "").strip()
    match = _SIZE.search(text)
    size = float(match.group(1)) if match else None
    family = _SIZE.sub("", text).strip(" ,;:-") or None
    return family, size


def choose_font(rule: ConstraintRule | None, content: CVContent) -> FontChoice:
    """The face and size a CV renders in (spec §3.5).

    The family is only ever a value from LOOKALIKE or DEFAULT_FAMILY: the
    rule's text is third-party page content and goes into a <style> block,
    so it is looked up, never copied.
    """
    if rule is None:
        return FontChoice(DEFAULT_FAMILY, DEFAULT_PT)
    named, size = parse_font_rule(rule.value)
    pt = size if size is not None and 9.0 <= size <= 14.0 else DEFAULT_PT
    if named is None:
        return FontChoice(DEFAULT_FAMILY, pt)
    face = LOOKALIKE.get(named.casefold())
    if face is None:
        return FontChoice(DEFAULT_FAMILY, pt, f"programme names {named!r}; no licensed "
                          f"look-alike is installed, so the CV keeps {DEFAULT_FAMILY}")
    if face in NO_CYRILLIC and _CYRILLIC.search(content.model_dump_json()):
        replacement = NO_CYRILLIC[face]
        return FontChoice(replacement, pt, f"programme names {named!r}; its look-alike "
                          f"{face} has no Cyrillic, so the CV uses {replacement}")
    return FontChoice(face, pt)
```

A size outside 9–14pt is ignored. A page's "minimum 14" is honoured; a misread "140" is not.

- [ ] **Step 4: Wire it into the renderer** (`apps/documents/render.py`)
- **`_render_pdf`** takes `font_family: str` and `font_pt: float` and adds both to the template context.
- **`render_cv_with_warnings`**, after `clean` is computed:

```python
    font_rule = next((rule for rule in constraints if rule.key == "font"), None)
    font = choose_font(font_rule, clean)
```

  Pass `font_family=font.family, font_pt=font.pt` to every `_render_pdf` call.
- **The checker**, next to `_check_max_pages`:

```python
_OWN_LAYOUT_VARIANTS = frozenset({"STANDARD", "GERMAN_TABULAR", "EUROPASS"})


def _check_font(rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact) -> str | None:
    """The programme's font is honoured on our own templates (spec §3.5).

    Funder templates and the EU's PDF keep their own layout, so for them the
    rule is reported, not applied; it is advisory, so this never blocks.
    """
    if artifact.variant not in _OWN_LAYOUT_VARIANTS or artifact.pdf_bytes is None:
        return f"{artifact.variant} keeps its own font; {rule.value!r} not applied"
    choice = choose_font(rule, content)
    if choice.note:
        return choice.note
    wanted = choice.family.replace(" ", "")
    if not any(wanted in face for face in embedded_font_names(artifact.pdf_bytes)):
        return f"{choice.family} was requested but is not installed"
    return None
```

Register it in `_CHECKERS` as `"font": _check_font`. With a checker present, the rule stops being reported as "no pre-flight check for 'font'".

- [ ] **Step 5: Run the font tests and the documents suite**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents -q`
Expected: PASS. Any test that relied on "no pre-flight check for 'font'" is updated to the new detail text.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents tests/documents
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): honour a programme's named font through its licensed look-alike, and check it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Tight layout only when a binding page cap would block

**Files:**
- Modify: `apps/documents/templates/documents/cv_base.html` (`@page` margin, body size, `.entry` and `h2` spacing read `compact`)
- Modify: `apps/documents/render.py` (`_render_pdf(compact: bool = False)`; the retry inside `render_cv_with_warnings`)
- Test: `tests/documents/test_render.py`

**Interfaces:**
- Consumes: `_render_pdf(..., font_family, font_pt, today)` from Tasks 2 and 4; `_CHECKERS["max_pages"]`.
- Produces: `_render_pdf(..., compact: bool = False)`. Later stages call it unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# --- Stage 1, §3.4: one tighter render before a binding page cap blocks ------

def _one_page_cap(enforcement=Enforcement.BINDING):
    return ConstraintRule(
        rule_id="R-TEST-1P", key="max_pages", value=1, enforcement=enforcement,
        rule_text="one page maximum", source_url="",
    )


def _just_over_one_page():
    """Content that spills a few lines past page one at normal density.
    Built by growing the bullet count until the normal render is 2 pages,
    so the test does not depend on one font's exact metrics."""
    for count in range(1, 40):
        content = _content(experience=_many_experience(count))
        if render_cv(content, variant="STANDARD").page_count == 2:
            return content
    raise AssertionError("could not build a two-page CV")


def test_compact_retry_saves_a_cv_that_just_misses_a_one_page_cap():
    artifact, violations = render_cv_with_warnings(
        _just_over_one_page(), variant="STANDARD", constraints=(_one_page_cap(),)
    )
    assert artifact.page_count == 1
    assert not [v for v in violations if v.rule.key == "max_pages"]


def test_an_advisory_cap_does_not_trigger_the_compact_retry():
    artifact, violations = render_cv_with_warnings(
        _just_over_one_page(), variant="STANDARD",
        constraints=(_one_page_cap(Enforcement.ADVISORY_STYLE),),
    )
    assert artifact.page_count == 2
    assert [v for v in violations if v.rule.key == "max_pages"]


def test_the_compact_render_is_ten_point():
    artifact = _render_pdf(
        _content(), variant="STANDARD", today=date(2026, 10, 13),
        font_family="Charis SIL", font_pt=11.0, compact=True,
    )
    assert artifact.page_count == 1
```

`test_binding_max_pages_violation_blocks` (20 entries, cap 1) stays unchanged and must still raise. Import `_render_pdf` from `apps.documents.render` in the test module.

- [ ] **Step 2: Run and see them fail**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents/test_render.py -k "compact or advisory_cap" -v`
Expected: FAIL. The binding case still blocks at 2 pages, and `compact` is an unexpected keyword.

- [ ] **Step 3: Make the template read `compact`** (`cv_base.html`)
- In `@page`: `size: A4; margin: {% if compact %}19mm{% else %}20mm{% endif %};`
- In `body`: `font-size: {% if compact %}10{% else %}{{ font_pt|default:11 }}{% endif %}pt;`
- `.entry { margin-top: {% if compact %}5pt{% else %}8pt{% endif %}; ... }`
- `h2 { ... margin-top: {% if compact %}10pt{% else %}16pt{% endif %}; ... }`

Add one comment line: compact is used only when a BINDING max_pages would otherwise fail (spec §3.4), and 10pt / 19mm are the S-002 / S-003 lower bounds.

- [ ] **Step 4: Add the retry** (`render.py`)
- `_render_pdf(..., compact: bool = False)` adds `"compact": compact` to the context.
- In `render_cv_with_warnings`, move the existing checks loop into a local `def _violations(artifact) -> list[ConstraintViolation]` with the same body, and call it. Then, before `return`:

```python
    blocked_by_pages = any(
        v.rule.key == "max_pages" and v.rule.enforcement == Enforcement.BINDING
        for v in violations
    )
    # The paths that render through cv_base.html (spec §3.0): our three
    # variants, and EUROPASS_API's local preview when there is no network.
    retry_variant = (
        variant if variant in _OWN_LAYOUT_VARIANTS
        else "EUROPASS" if variant == "EUROPASS_API" and not allow_network
        else None
    )
    if blocked_by_pages and retry_variant is not None:
        # Spec §3.4: one tighter render before a binding page cap blocks.
        # Never content removal; kept only if it clears the cap, and every
        # check runs again on what will actually ship.
        compact = _render_pdf(
            clean,
            variant=retry_variant,
            date_of_issue=today if wants_date else None,
            emphasise=emphasise,
            oldest_first_sections=oldest_first,
            today=today,
            font_family=font.family,
            font_pt=font.pt,
            compact=True,
        )
        compact_violations = _violations(compact)
        if not any(
            v.rule.key == "max_pages" and v.rule.enforcement == Enforcement.BINDING
            for v in compact_violations
        ):
            artifact, violations = compact, compact_violations
```

- **`wants_date` must exist on every path.** Lift its computation above the `if variant == "EUROPASS_API":` chain, so the retry can read it.
- **`_OWN_LAYOUT_VARIANTS`** is the set Task 4 defined next to `_check_font`. Reuse it; do not define a second one.

- [ ] **Step 5: Run the render tests and the documents suite**

Run: `POSTGRES_DB=elmify_cv_engine_design uv run pytest tests/documents -q`
Expected: PASS. `test_binding_max_pages_violation_blocks` still raises.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/cv-engine-design add apps/documents tests/documents
git -C /home/orkhan/Desktop/cv-engine-design commit -m "feat(cv): one compact render before a binding page cap blocks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Stage gate

- [ ] **Step 1: The repo's gates, on the whole branch**

```bash
cd /home/orkhan/Desktop/cv-engine-design
uv run ruff check .
uv run mypy apps config
uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=elmify_cv_engine_design uv run pytest -q --create-db
```

Expected: ruff "All checks passed!", mypy "Success", "No changes detected", and pytest passing with no new failures.

- [ ] **Step 2: Render the owner's sample CV in the new layout** (for the review)

Re-run the typography sample builder (`/tmp/claude-1000/-home-orkhan-Desktop-elmify/a35e3617-8932-4d8d-9130-d657a872d603/scratchpad/typography/build.py`) against the worktree's templates. Write `stage1-standard.pdf` and a PNG of page 1 to `~/Desktop/elmify-out/typography/`, so the owner sees Stage 1's real output.
