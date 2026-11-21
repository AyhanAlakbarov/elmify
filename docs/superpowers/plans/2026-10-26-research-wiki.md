# Research wiki — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sessions answer funding and discovery questions from about 50 short, cited pages under `docs/wiki/` instead of re-reading 19 long research files, and a no-model check keeps those pages true to their sources.

**Architecture:** One script, `scripts/wiki_lint.py`, parses the wiki: `problems()` lists hard failures (missing source or section, dead link, index out of step, uncited page, logged file gone) and the suite asserts it is empty; `report()` lists soft findings (unlogged sources, orphans, stale pages) for a person to read. A path-scoped rules file holds the conventions, and one always-loaded `CLAUDE.md` line points questions at the index. The pages themselves are written by a model in two ingest batches and spot-checked against their sources.

**Tech Stack:** Python 3.14 standard library (`re`, `pathlib`, `subprocess` for `git log`), pytest, ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-10-26-research-wiki-design.md`

## Global Constraints

- The raw research under `docs/superpowers/research/` is never edited.
- Citation form, exactly: `[src: <research filename> §<n>]`, `<n>` a numbered heading (`## 3. ...` or `### 3. ...`) in that file; `[src: <research filename>]` when the file has none.
- A country or scheme gets its own page only when at least two sources say something about it.
- A page stays under about 60 lines; data stays in CSV files and is linked, not copied.
- Page paths: `topics/<slug>.md` (slug = synthesis filename without the date and `-synthesis`), `countries/<iso2 lowercase>.md`, `schemes/<slug>.md`, `sources/<slug>.md`.
- `log.md` lines, exactly: `## [YYYY-MM-DD] ingest | <filename>` or `## [YYYY-MM-DD] skip | <filename> | <reason>`.
- `scripts/wiki_lint.py` never calls a model or the network and always exits 0.
- Checks before the pull request: `uv run pytest tests/test_research_wiki.py tests/test_instruction_files.py`, `uv run ruff check` and `uv run ruff format --check` on the new Python files, `uv run mypy scripts/wiki_lint.py tests/test_research_wiki.py`.
- tehsil never pushes to master: branch `claude/research-wiki`, pull request, merge by hand only on the owner's words.

## Review Focus

1. **A link with an anchor or to the web** (`../countries/az.md#quota`, `https://...`, `#top`) is not a dead link; only a relative file that does not exist is. Test in Task 1.
2. **Research files that are not sources** — `PROMPT-*.md` and the `2026-08-27-masters-cv-evidence/` folder — never show as "not ingested". Test in Task 1.
3. **A file not yet committed** (a page written in this branch's working tree) is never called stale; staleness compares commit times only. Test in Task 1.
4. **A citation to a section a synthesis renumbered** fails the suite, naming the page and the section. Test in Task 1.
5. **A model-written claim its cited section does not support.** No parser catches this; the ten-citation spot check in Tasks 4 and 5 and the owner's review of the pull request do.

---

### Task 1: The checker and an empty wiki

**Files:**
- Create: `scripts/wiki_lint.py`
- Create: `tests/test_research_wiki.py`
- Create: `docs/wiki/index.md`, `docs/wiki/log.md`, `docs/wiki/open-questions.md`
- Commit first, unchanged: `docs/superpowers/specs/2026-10-26-research-wiki-design.md`, `docs/superpowers/plans/2026-10-26-research-wiki.md`

**Interfaces:**
- Produces, in `scripts/wiki_lint.py`:
  - `ROOT: Path`, `WIKI = ROOT / "docs/wiki"`, `RESEARCH = ROOT / "docs/superpowers/research"`
  - `problems(wiki: Path = WIKI, research: Path = RESEARCH) -> list[str]`: one line per failure, each starting with the page path relative to `wiki` and naming the bad reference.
  - `report(wiki: Path = WIKI, research: Path = RESEARCH, last_commit: Callable[[Path], int | None] = git_last_commit) -> list[str]`
  - `git_last_commit(path: Path) -> int | None`: `git log -1 --format=%ct -- <path>`; `None` when the file has no commit.
  - `main() -> int`: prints `problems()` then `report()`, or `wiki: nothing to report`; returns 0.
- Definitions both functions share: a **content page** is any `.md` under a subfolder of `wiki`; `index.md`, `log.md` and `open-questions.md` sit at its root. A **relative link** is a Markdown link target that is not `http(s):`, `mailto:` or `#...`; its `#anchor` is dropped before resolving against the page's folder. A **source** is a top-level `research/*.md` not named `PROMPT-*.md`.

- [ ] **Step 1: Commit the design and this plan**

```bash
git add docs/superpowers/specs/2026-10-26-research-wiki-design.md docs/superpowers/plans/2026-10-26-research-wiki.md
git commit -m "docs: research wiki design and plan"
```

- [ ] **Step 2: Write the failing tests** in `tests/test_research_wiki.py`, with a helper `_tree(tmp_path, files: dict[str, str]) -> tuple[Path, Path]` that writes `wiki/...` and `research/...` files and returns `(wiki, research)`.

```python
def test_the_wiki_is_consistent():
    found = problems()
    assert not found, "\n".join(found)

def test_a_missing_source_is_a_problem(tmp_path):   # page cites [src: gone.md §1]
    assert any("topics/a.md" in p and "gone.md" in p for p in problems(*_tree(...)))

def test_a_missing_section_is_a_problem(tmp_path):  # source has "## 1. X"; §2 fails, §1 passes
def test_a_citation_without_a_section_needs_only_the_file(tmp_path):
def test_only_relative_links_to_missing_files_are_problems(tmp_path):
    # links: ../countries/az.md#quota (exists), https://e.x, mailto:a@b, #top -> no problem
    # nope.md -> one problem naming nope.md
def test_a_page_missing_from_the_index_is_a_problem(tmp_path):
def test_a_content_page_with_no_citation_is_a_problem(tmp_path):
def test_a_logged_file_that_no_longer_exists_is_a_problem(tmp_path):
def test_report_names_unlogged_sources_only(tmp_path):
    # research: a.md (unlogged) -> named; b.md (logged skip), PROMPT-x.md, folder/c.md -> not named
def test_report_names_a_page_no_other_page_links_to(tmp_path):  # a link from index.md does not count
def test_report_names_a_stale_page_and_ignores_uncommitted_files(tmp_path):
    # last_commit stub: page 100, source 200 -> named "stale"; source None -> not named
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_research_wiki.py -q`
Expected: collection error, `No module named 'scripts.wiki_lint'`.

- [ ] **Step 4: Implement `scripts/wiki_lint.py`** with the interfaces above; module docstring gives the two commands (`python scripts/wiki_lint.py`, the test) and says the checks never call a model.

- [ ] **Step 5: Write the empty wiki**: `index.md` with `# Research wiki`, one sentence on what it is, a link to `open-questions.md`, and empty `## Topics`, `## Countries`, `## Schemes`, `## Sources` headings; `log.md` with `# Wiki log` and one line saying entries are appended, newest last; `open-questions.md` with `# Open questions` and one line saying each entry cites both sources.

- [ ] **Step 6: Run the tests and the checks**

Run: `uv run pytest tests/test_research_wiki.py -q && uv run ruff check scripts/wiki_lint.py tests/test_research_wiki.py && uv run ruff format --check scripts/wiki_lint.py tests/test_research_wiki.py && uv run mypy scripts/wiki_lint.py tests/test_research_wiki.py && uv run python scripts/wiki_lint.py`
Expected: all tests pass, ruff and mypy clean; the report lists every research source as not ingested.

- [ ] **Step 7: Commit**

```bash
git add scripts/wiki_lint.py tests/test_research_wiki.py docs/wiki/index.md docs/wiki/log.md docs/wiki/open-questions.md
git commit -m "wiki: the checker, its tests and an empty research wiki"
```

### Task 2: The conventions and the pointer

**Files:**
- Create: `.claude/rules/research-wiki.md`
- Modify: `CLAUDE.md` (the "Area rules" index, after the `funding-map.md` line, and the paragraph after it)

**Interfaces:**
- Consumes: the paths and commands from Task 1.

- [ ] **Step 1: Write `.claude/rules/research-wiki.md`**, exactly:

```markdown
---
paths:
  - "docs/wiki/**"
  - "docs/superpowers/research/**"
---

## Research wiki: answer funding and discovery questions from docs/wiki/

<!-- Owner-approved 2026-10-26. Design: docs/superpowers/specs/2026-10-26-research-wiki-design.md -->

`docs/wiki/` holds short, cited pages built from `docs/superpowers/research/`: one per synthesis
topic, country, scheme and source. Start a funding or discovery question at `docs/wiki/index.md`,
answer from the pages with their citations, and open a raw research file only for what the pages
lack; then offer to add it to the wiki.

Writing or changing a page:
- Every claim ends with `[src: <research filename> §<n>]`, `<n>` a numbered heading in that file
  (leave `§<n>` out when it has none). Never edit the research files themselves.
- Two sources disagree: give both, each cited, and add a line to `docs/wiki/open-questions.md`.
- A country (`countries/<iso2>.md`) or scheme (`schemes/<slug>.md`) gets a page only when two
  sources say something about it; otherwise the fact stays on its topic page.
- Keep a page under about 60 lines; link CSV data instead of copying it.
- List every page in `index.md` under its kind, with a one-line summary.

Adding research: the pull request that adds a file under `docs/superpowers/research/` also updates
the pages it touches, `index.md`, and appends `## [YYYY-MM-DD] ingest | <filename>` to `log.md`, or
`## [YYYY-MM-DD] skip | <filename> | <reason>` when it holds nothing a page needs.

Checks: `tests/test_research_wiki.py` runs with the suite (missing sources or sections, dead links,
index out of step, uncited pages). `python scripts/wiki_lint.py` also reports research not yet
ingested, pages nothing links to, and pages older than a source they cite.
```

- [ ] **Step 2: Add to `CLAUDE.md`** the index line `- \`.claude/rules/research-wiki.md\`: "Research wiki: answer funding and discovery questions from docs/wiki/"` after the `funding-map.md` line, and after the maps paragraph the sentence: `A question about funding, schemes, countries, institutions or discovery sources starts at \`docs/wiki/index.md\`, not the research folder.`

- [ ] **Step 3: Run the instruction-file checks**

Run: `uv run pytest tests/test_instruction_files.py tests/test_research_wiki.py -q`
Expected: pass (the index test finds the new heading; CLAUDE.md stays under 200 lines).

- [ ] **Step 4: Commit**

```bash
git add .claude/rules/research-wiki.md CLAUDE.md
git commit -m "wiki: the conventions, and CLAUDE.md points research questions at the index"
```

### Task 3: The baseline, before any page exists

Runs in `~/Desktop/tehsil_agent/.worktrees/measure-base` reset to `origin/master` (no `docs/wiki/`). Output goes to `~/agent-workspace/state/measure-2026-10-26-wiki/`. Nothing in the repository changes.

- [ ] **Step 1: Write the three questions** as `q1.txt`–`q3.txt`, each prefixed with `Answer from tehsil's own research, citing file and section; change nothing.` (not "research files only", which would steer the after-run away from the wiki):
  - q1: `What can an Azerbaijani master's applicant get from Fulbright and from Korea's GKS: quota, deadline and conditions? Where do our research files disagree or leave it unverified?`
  - q2: `What does our research say about Azerbaijan's own state scholarship programme for study abroad: what it is, how sure we are, and what is still open?`
  - q3: `Which live search provider did our research choose for discovery, why was Google ruled out, and what is still open?`

- [ ] **Step 2: Write the answer key** `key.md` before any run: for each question, the facts a correct answer contains and the file and section each comes from, read directly from the raw research (start from `2026-08-29-fulbright-per-country-verification.md`, `2026-08-29-gks-quota-primary-verification.md`, `2026-08-29-origin-side-synthesis.md` §2–§3 and §8, `2026-08-30-live-search-synthesis.md` §1, §3 and §8).

- [ ] **Step 3: Run each question headless** from the measure-base checkout: `claude -p "$(cat qN.txt)" --output-format json --permission-mode default --max-budget-usd 5 --disallowedTools Write,Edit,NotebookEdit > qN.before.json` (the flags of the 2026-10-25 navigation baseline, plus the write ban), then `python3 ~/agent-workspace/evals/usage/session_spend.py <transcript of that session_id> --json > qN.before.spend.json`. The transcript is the `<session_id>.jsonl` under the config directory's `projects/` folder for that checkout.
Expected: three answers and three spend files; record each answer's score against `key.md` (facts right, facts wrong, citations right) in `scores.md`.

### Task 4: Ingest batch A — funding by country and scheme

**Files:** create pages under `docs/wiki/topics/`, `countries/`, `schemes/`, `sources/`; modify `docs/wiki/index.md`, `log.md`, `open-questions.md`.

**Sources (9):** `2026-08-28-worldwide-funding-sources-synthesis.md`, `2026-08-29-nationality-keyed-synthesis.md`, `2026-09-13-government-inbound-synthesis.md`, `2026-09-13-government-inbound-verification.md`, `2026-08-29-origin-side-synthesis.md`, `2026-08-29-outbound-launch-synthesis.md`, `2026-08-29-fulbright-per-country-verification.md`, `2026-08-29-gks-quota-primary-verification.md`, `2026-08-29-gapfill-openitem-verification.md`.

- [ ] **Step 1: Read each source whole** and write its topic page (syntheses) or fold it into the pages it informs (verification notes), following `.claude/rules/research-wiki.md`. A review file is read only for a fact its synthesis attributes to it, and is then cited itself.
- [ ] **Step 2: Write the country and scheme pages** that pass the two-source rule, list every page in `index.md`, append one `ingest` line per source to `log.md`, and add each disagreement to `open-questions.md`.
- [ ] **Step 3: Run the checks**

Run: `uv run pytest tests/test_research_wiki.py -q && uv run python scripts/wiki_lint.py`
Expected: tests pass; the report names no orphan, and none of the nine sources as not ingested.

- [ ] **Step 4: Spot-check ten citations**: `grep -rnoE '\[src: [^]]+\]' docs/wiki | shuf -n 10`; for each, open the cited section and confirm it supports the sentence it ends. Fix or remove any that do not, and record the count found in the commit message.
- [ ] **Step 5: Commit**

```bash
git add docs/wiki
git commit -m "wiki: ingest funding by country and scheme (9 sources; spot check N/10)"
```

### Task 5: Ingest batch B — corridors, institutions, search; skip the rest

**Sources (10):** `2026-08-27-corridor-mechanics-synthesis.md`, `2026-08-28-corridor-mechanics-round2-synthesis.md`, `2026-08-27-instrument-landscape-synthesis.md`, `2026-08-27-portfolio-theory-synthesis.md`, `2026-08-29-synthesis-crosscheck.md`, `2026-08-29-leading-institutions-synthesis.md`, `2026-08-31-open-admission-synthesis.md`, `2026-08-30-live-search-synthesis.md`, `2026-08-31-register-open-questions-closed.md`, `2026-08-31-three-remaining-gaps.md`.

- [ ] **Step 1: Ingest them** as in Task 4 Steps 1–2, extending existing country and scheme pages rather than adding second ones.
- [ ] **Step 2: Log every other source** as `skip` with a reason of a few words (`review; its synthesis is ingested`, `CV research; see .claude/rules/cv-and-letters.md`, `transcript reader research`, `measurement run`, ...).
- [ ] **Step 3: Run the checks** as in Task 4 Step 3.
Expected: tests pass; `wiki: nothing to report` (no page can be stale yet: uncommitted files are never compared).
- [ ] **Step 4: Spot-check ten citations** as in Task 4 Step 4.
- [ ] **Step 5: Commit**

```bash
git add docs/wiki
git commit -m "wiki: ingest corridors, institutions and search (10 sources; spot check N/10); log the rest as skipped"
```

### Task 6: Measure, decide, open the pull request

- [ ] **Step 1: Run the three questions again** from the `claude/research-wiki` worktree, as in Task 3 Step 3, into `qN.after.json` and `qN.after.spend.json`, and score them against the same `key.md`.
- [ ] **Step 2: Write `result.md`** in the measurement folder: per question and in total, input tokens (new and cache reads), steps, models, and the scores, before against after; and the decision rule's outcome (keep if the three together use at least 30% fewer input tokens and no answer loses a correct fact or citation the baseline had).
- [ ] **Step 3: Run the checks** listed under Global Constraints.
Expected: all pass.
- [ ] **Step 4: Push and open the pull request** with the measurement table and the decision in its description; report to the owner before any merge. If the rule says drop, say so in the report and open nothing until the owner decides.
