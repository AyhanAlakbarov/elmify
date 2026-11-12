# Reading a student's GitHub and thesis PDFs into the CV and letters: design

Date: 2026-10-14. Revised 2026-10-15 after an independent review
(`~/agent-workspace/elmify-runs/cv-engine/2026-10-15-evidence-spec-review.md`: 6 blockers, 25 should-fix and 18 notes, all folded in
below). Status: Part A approved to build by the owner, subject to that review.

Owner: Orkhan. Parent spec: `docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md` (Part B
plugs into its Stages 2–4).

Evidence behind it:
- the evidence-engine review, with every finding checked against the code:
  `~/agent-workspace/elmify-runs/cv-engine/2026-10-14-evidence-engine-review.md`;
- the tool trial (repomix, gitingest, code2prompt, yek) in section 7 of that file;
- the tool survey `.context/research/2026-10-14-repo-summarising-tools.md` (citations verified);
- `.context/research/2026-10-14-cv-publication-and-repo-sources.md`;
- `.context/research/2026-10-14-cv-pdf-docx-extraction-libraries.md`.

## 1. What this is for

For a student whose work involves code, their GitHub holds the most detailed account of what they
did. Today nothing from it reaches a CV or a letter: `manage.py ingest_evidence` prints the drafted
text and throws it away, and `facts.write_project_fact` has no caller.

This design makes Elmify:
1. find the student's repos by itself, from a GitHub username;
2. read the promising ones properly;
3. **add** checked bullets to CV entries the work belongs to;
4. add real side projects in a new Projects section, only when they fit the programme;
5. hand the same checked readings to the letter engine.

Uploaded theses and reports (PDF) are read the same way and feed the same places.

**Success looks like this:**
- a student whose CV links GitHub, or who types a username, gets better bullets on the entries
  their repos belong to;
- relevant side projects appear where the CV has room;
- letters can cite concrete project details;
- nothing appears that the repo or PDF does not support;
- the student never has to paste a link or confirm anything for it to work, and can undo any
  addition.

## 2. Decisions already taken (owner, 2026-10-14)

1. **Trust the student.** No ownership checks. Every repo in their account, and every commit in it
   (including `claude[bot]` and `github-actions[bot]` commits, which are the student delegating
   work), counts as theirs.
2. **Discovery is automatic.** Nothing to paste. Four kinds of repo are found:
   - the student's own repos;
   - lab and organisation repos they committed to, using GitHub's GraphQL interface;
   - forks they changed;
   - repos the CV links.
3. **One GitHub key for the platform.** No per-student sign-in. GitLab comes later and works the
   same way.
4. **Add, never rewrite.** The student's own CV sentences are never changed by a model.
5. **Automatic, with undo.** One removal applies everywhere, letters included.
6. **Projects stay off the CV until Stage 4's relevance check is switched on.**
7. **A repo that belongs to an entry is never also a project.** If the match is unsure, the repo
   goes nowhere.
8. **Readings live in their own table.** Nothing reads them unless deliberately wired to.
9. **Programming languages found in repos become skill suggestions**, unconfirmed like libraries.
10. **A repo matched to a degree** becomes a Project if it passes the side-project tests (§10.3).
11. **A new upload type, "Thesis or report".** Only files uploaded as that type are read as projects.
12. **Letters may use readings** through one shared function, which returns checked text only.

Also settled, by the cost review the owner accepted:
- no screening model call: code picks the repos;
- re-read only when a repo changed;
- 24,000-character evidence budget.

## 3. Out of scope

- **GitLab:** later, same design.
- **Private repos:** a GitHub App with read-only contents permission could reach them. Later.
- **Finding papers the CV does not list.** ORCID's public API forbids revenue-generating use, and
  searching by name returns the wrong people.
- **pypdfium2 for LaTeX PDFs:** a separate change.
- **Postponed by the cost review:** the screening model call, the `torch`→PyTorch name table, and
  code readers for R, Julia, C++, Fortran and MATLAB.
- **How a letter uses a reading:** that is the letter session's design.

## 4. Two parts

- **Part A, built now, off `master`.** It finds, reads, checks and stores readings, and gives
  letters checked bullets.
  - Sections: §5–§9, §11 (letters, checked bullets only), §12, §13 and §14.
  - It touches no CV generation code and needs no unbuilt stage.
- **Part B, after CV Stages 2–4.** It puts readings on the CV (§10).
  - It needs Stage 2's `fact_identity`, Stage 3's `applied_fixes` and undo table, and Stage 4's
    relevance check.
  - It adds the undo and entry-match parts of the letter hand-off.

```
username (CV link or typed)
  -> refresh_evidence job (document queue)                                   (§12)
     discovery: own repos + lab/org repos + changed forks + CV links          (§5, github.py)
     selection by code: up to 10 repos                                        (§6)
     for each repo changed since its last reading (or read by an older reader):
        fetch + evidence text (<= 24,000 characters)                          (§7)
        read_repo: one model call                                             (§7.3)
        checks: numbers, per-bullet quotes; support check if its gate is on   (§7.4)
        save, in one short transaction                                        (§7.5)
     delete readings for repos gone from a COMPLETE discovery                 (§6)
thesis/report upload -> the same job, the PDF path                            (§8)
letters: usable_readings(student)                                             (§11)
Part B: CV generation refreshes inline with a time budget, then places readings  (§10)
```

## 5. Finding the repos (`apps/documents/evidence/github.py`, new)

### 5.1 The username

- **Where it is kept.** As an IDENTITY fact carrying `github_url`. The IDENTITY payload already
  carries it (`ingest_evidence.py:67-73` reads `github_url`/`github_username`).
- **Where it comes from:**
  1. **The CV's GitHub profile link.** `confirmed_github_login`'s parser moves to `github.py`, and
     both confirmed and unconfirmed IDENTITY facts are read, per decision 1.
  2. **A login the student types.** It is saved as an IDENTITY fact with `source_tier`
     STUDENT_STATEMENT. It inherits the confirmation of the IDENTITY row it supersedes; with no
     IDENTITY row yet, it is a standalone, unconfirmed login row (amended 2026-10-15).
     Confirming the whole row would confirm a model-read name, and a confirmed nameless row
     would open the generate endpoint's identity check. Discovery reads unconfirmed IDENTITY
     facts anyway (decision 1).
- **The endpoint** (Part A; its screen is Aykhan's): `POST`/`DELETE` on the student API.
  - `_student_endpoint` and CSRF, plus a `rate_limited` bucket `github-login` (10 an hour).
  - The login must match `^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$`.
  - **Setting or changing** it supersedes the old fact and queues a refresh. Readings of repos the
    new account does not reach go at the next complete discovery (§6).
  - **Clearing** it deletes every `github` reading. Skill suggestions already written stay, as
    suggestions.
- **Who is asked:** any student with no known login. The question is optional and costs nothing
  until answered. There is no field-of-study rule.

### 5.2 The four sources

All of them use the platform key `GITHUB_TOKEN` (§12.2).

| Source | How | Requests |
|---|---|---|
| Own repos | REST `GET /users/{login}/repos?type=owner&per_page=100`, every page. Returns name, description, size, `pushed_at`, `created_at`, `fork`, `archived`. | 1 per 100 repos |
| Lab and organisation repos | One GraphQL request carrying ten aliased `contributionsCollection(from, to)` blocks, one per year, each asking for `commitContributionsByRepository(maxRepositories: 25)` with `contributions { totalCount }` and the repo's owner `login`, `__typename` and organisation `name`. | 1 |
| Changed forks | Only forks whose listing has `pushed_at > created_at`, which is free. At most the 10 most recently pushed are checked: a metadata call for the parent (the listing carries none), then the existing compare call. Kept when `ahead_by > 0`. | ≤20 |
| Repos the CV links | `extract_link_urls` re-run on the student's latest AVAILABLE `CV` upload at refresh time. Links are not stored anywhere today. Each link goes through `parse_source`. | 0 |

**Not counted as discovery sources:** pull-request contributions. A pull request to a big project
says little about the student's own work, and the reading would describe that project.

**GitHub's own limits, accepted:**
- **Lab repos.** Commits count only when made with an email linked to the account, and commits
  made inside forks do not count.
- **Private repos** are invisible.
- **Forks.** Only the default branch is read.
- **Repos per year.** At most 25 per year in the contributions query.

**Safety of names returned by GitHub.** Every `owner/name` from GraphQL or REST goes through
`sources._is_safe_segment` before it is used in a URL.

### 5.3 The connection

- `evidence/transport.py` stays the GitHub client. Its `Transport` protocol changes so every call
  returns `(status, body, headers)`, and it gains:
  - `post_json(url, body, headers)` for GraphQL;
  - `get_bytes(url, headers, max_bytes)`, a streamed download with a 5 MB cap, for raw files.
- **Why not `egress.fetch_json_api`:** it returns no response headers, which the rate-limit
  handling needs, and no raw bytes.
- **The exception is safe** because the host is fixed at `api.github.com`, and every path segment
  is validated. It is recorded in `.claude/rules/web-fetching.md` as the fourth first-party
  transport, with this reason.
- **GraphQL answers HTTP 200 even when a query fails.** A response carrying `errors`, or
  `data.user: null`, is treated as a failure. An unknown login gives
  `data.user: null`, which drives the "We couldn't find GitHub user X" message.

### 5.4 Rate limits

Every response's `x-ratelimit-remaining` and `x-ratelimit-reset` headers are read.
- **A 403 or 429 with `remaining == 0`, or any `retry-after` header** (GitHub's secondary limit),
  raises `GitHubRateLimited`. It is no longer reported as "not found, or private", which
  `repo.py:131-134` wrongly does today.
- **The refresh stops there.** Readings already written are kept, and nothing is deleted. The next
  trigger carries on. The single document worker never sleeps waiting for a reset.
- **Before starting:** if the last response showed fewer than 200 requests left, the refresh
  stops before it begins.

## 6. Choosing what to read (`refresh.py`, new)

Code chooses up to 10 repos, in this order:
1. **Repos the CV links.**
2. **Lab and organisation repos** the student made at least 3 commits to, most commits first. The
   commit count comes free from the same GraphQL response.
3. **Own repos and changed forks,** most recently changed first.

Of the 10 slots, at most 5 go to group 3.

**Always skipped:**
- empty repos (`size == 0`);
- the profile repo named after the login;
- `<login>.github.io`;
- untouched forks.

**Re-reading.** A repo is read again only when:
- its listing `pushed_at` differs from the reading's stored `changed_at`, or
- the reading's `reader_version` differs from the current `READER_VERSION`, a constant raised
  whenever the prompt, schema or checks change.

`pushed_at` also moves on pushes to other branches. That costs an occasional unneeded re-read,
accepted.

**Deleting readings.** Readings are deleted only after a **complete** discovery: every listing page
answered 200, and the GraphQL response came back with no `errors`. A reading whose repo appears in
no source of a complete discovery is deleted. A failed or partial discovery deletes nothing, and a
failure fetching one repo keeps that repo's old reading.

## 7. Reading one repo

### 7.1 Fetching (`repo.py`)

**Bundled queries (owner, 2026-10-15).** Each repo is fetched with about **two GraphQL queries plus
one REST request**, not about 30 single requests:
1. **GraphQL query 1** (about 1 point): description, `pushedAt`, `isFork` and `parent`, languages,
   the 100 most recent default-branch commits (for repos the student does not own,
   `history(author: {id})` gives the student's own), and the README blob.
2. **REST** `GET /repos/{o}/{r}/git/trees/{branch}?recursive=1`, the full tree with sizes, which a
   GraphQL query cannot give, since it can only go down a fixed number of levels.
3. **GraphQL query 2** (about 1 point): the files chosen from the tree, as aliased
   `object(expression: "HEAD:<path>") { ... on Blob { byteSize isTruncated text } }` fields. That
   covers code files, notebooks, manifests, signal files and agent notes, up to the existing caps.
   - A blob with `isTruncated: true` or `text: null` (binary) is fetched with the REST raw download
     (`get_bytes`, 5 MB cap) only when it is a notebook or a README; anything else is treated as
     absent.

**Points and requests.** GraphQL points are a separate allowance from REST requests (5,000 of each
an hour on the platform key). Measured 2026-10-15 on `0rkhann/MicroKatc`: query 1, with the README,
cost **1 point**. A changed fork's `ahead_by` stays the REST compare call.

**Free repeat requests.** The tree request sends the reading's stored `etag` (`if-none-match`).
A `304 Not Modified` does not count against the limit (GitHub REST best-practices docs), and the
repo is then left as it is. The listing and fork checks send none: a 304 there would need a stored
response body.

**`fetch_repo` reads** query 1, the tree (now keeping each blob's `size`) and query 2 above; the
fork compare stays a REST call.

**It drops:**
- the contributors request;
- the `owner_login` parameter;
- `commit_count`;
- `authorship` and `Authorship`.

**Commit messages** are kept whole (title and description). Every trailer line (`Co-authored-by:`,
`Signed-off-by:`, `Reviewed-by:` and the like) is removed by code, because trailers carry other
people's names and emails.

**Repos the student does not own** (lab and organisation repos): commit messages and dates come
from query 1's `history(author: {id})`, using the student's GitHub user id from discovery, so they
are the student's own commits, not the whole lab's.

**Dates.**
- For a repo the student owns: first and last commit over all commits, bot commits included
  (decision 1).
- For a lab or organisation repo: the student's own commits.
- When the sample was capped at 100 (`commit_sample_capped`), no dates are kept, as
  `intake.py:210-217` already does.

**The tree:**
- sorted by depth **before** the 2,000-path cut;
- `truncated: true` is logged;
- file paths go to query 2 as GraphQL variables, never pasted into the query text, and are
  URL-quoted for the raw download.

**Files:**
- query 2 returns each file's text;
- a cut-off (`isTruncated`) or binary blob is downloaded raw (`get_bytes`,
  `Accept: application/vnd.github.raw`, 5 MB cap), and only for notebooks and README-type files;
  anything else is absent;
- a Git LFS pointer (text starting `version https://git-lfs`) is absent.

### 7.2 The evidence text (`signals.py`, `intake.py::_repo_evidence`)

The budget stays 24,000 characters. The new order means README-type files can no longer push
everything else out:
1. description: the repo's own one-line description. The `Repository: owner/name` line is
   dropped, so the student's login never reaches a model prompt;
2. code signals: module and function descriptions and names (`python_signals`, unchanged);
3. notebooks (below);
4. libraries: imports, plus declared names from `MANIFEST_FILES`. This is unchanged:
   `requirements.txt` stays unread, because it is often a pip freeze of the whole machine;
5. directory names;
6. commit messages, newest first, merges skipped;
7. README-type files, each capped at 6,000 characters, after `strip_markup`;
8. agent notes (`CLAUDE.md`, `AGENTS.md`), each capped at 3,000 characters.

**File selection (`interesting_paths`):**
- **Test files by segment rule:** a `test`/`tests` directory, a name starting `test_`, or a name
  ending `_test.py`. So `latest_model.py` and `contest_solver.py` are read.
- **Never parsed as prose:** `LICENSE*`, `CODE_OF_CONDUCT*`, `CONTRIBUTING*`, `requirements*.txt`
  and `CITATION.cff`.
- **`.txt` files** count as prose only under a `docs/` directory and under 50 KB (from the tree
  size). Others are data dumps.

**`strip_markup(text)`** (new, in `signals.py`, using the installed `lxml`):
- removes HTML tags and badge images;
- keeps link text and image alt text;
- keeps Markdown headings and list markers.

**Notebooks (`notebook_signals`):**
- parse the whole file (up to 5 MB), then shorten the converted text, never the raw JSON;
- keep markdown cells, imports from code cells, and text outputs (`stream`, `text/plain`);
- drop image outputs;
- an output with no text part is skipped, never an error.

**Evidence floor.** If the text after the description is under 500 characters (for example an
empty default branch, LFS files only, or binaries only), the repo is not read, and any old reading
of it is deleted.

### 7.3 The model call (`extraction.py::read_repo`, replacing `propose_description`)

**Same safety pattern as today:**
- data labelled as data;
- schema-constrained output with `extra="forbid"`;
- capped output tokens;
- `store=False`;
- `OPENAI_EXTRACTION_MODEL`.

The OpenAI account has zero data retention (owner, 2026-10-14).

**Prompt changes:**
- **English only.**
- **Wording by source.** "project" for a repo; "research work" for a thesis or report, replacing
  the hard-coded "software project".
- **The S-026 rules stay:** past tense, no first person, no praise, result before method, no
  number the data does not state.

**Output schema `RepoReading`:**

| Field | Meaning |
|---|---|
| `summary` | One line: what the work is. |
| `kind` | `project`, `course_project`, `exercise_or_tutorial` or `not_a_project`. |
| `bullets` | 1–5 items. Each is `{text: Bullet, evidence: [1–3 verbatim spans copied from DATA]}`. `Bullet` is the existing 500-character type; the prompt asks for at most 200. |
| `methods`, `outcomes` | As today, for research entries. |
| `techniques` | As today, each with its verbatim `excerpt`. |
| `names` | Project, lab, course or thesis names the evidence states, for matching. |

### 7.4 Checks (`apps/documents/evidence/checks.py`, new)

**Run in the refresh**, while the evidence is still in memory:

1. **Quotes.** Every bullet's `evidence` spans and every technique's `excerpt` must appear in the
   evidence text, after whitespace and case are normalised (the `reader.verified_statements` rule).
   A bullet with no surviving span is dropped. Today excerpts are never checked.
2. **Numbers.** Every number in a bullet, `methods` or `outcomes` must appear in that bullet's own
   evidence spans (for `methods`/`outcomes`, in the evidence text). That covers digits and forms
   like `10B`, `3.88M`, `92%`. A bullet that fails is dropped; a failing `methods`/`outcomes`
   becomes null.
   - **Known limit:** numbers written as words, and years or versions that make small integers
     trivially present, are not caught.
3. **Support check** (always on; no launch switch).
   - Jev is asked one closed question per surviving bullet, through
     `apps/research/decisions.ask(record=False)`: "Does this evidence support this sentence? yes /
     no / unsure".
   - Only the bullet and its own evidence spans are sent. That is small (well under Jev's 32k-token
     state limit) and carries no login.
   - Thesis spans are private student text. TypeSafe's data-processing agreement is accepted
     (owner, 2026-10-15), so they may be sent to Jev, and there is no launch switch.
   - It is counted in its own bucket, `evidence-support` (60 an hour per student).
   - A new decision id needs a `provider_for` mapping (`decisions.py:243`).
   - **The verdict is stored on each bullet:** `supported`, `rejected` (`no`, `unsure`, or below
     0.9), or `unchecked` (the call failed or hit its limit). Nothing is kept in a cache.

### 7.5 Saving (`facts.py`)

- **Every database read and write for readings lives in `facts.py`.** This keeps
  `tests/documents/evidence/test_invariants.py`'s rule that only `facts.py` touches the database.
- **One short `tenant_transaction`** saves a reading and its skill suggestions together, after the
  model call has returned. No transaction ever spans an HTTP or model call (the transcript-reader
  pattern).
- **Skill suggestions** (languages, libraries, techniques) are unconfirmed `SKILL` facts, which is
  how the student accepts skills today. Languages switch from confirmed to unconfirmed
  (decision 9).
  - **Nothing is written** when a SKILL fact of the same kind and name already exists unsuperseded
    for the student, confirmed or not.
  - **A re-read never supersedes a skill row.** So a skill the student confirmed is never taken
    away by a later push, and `numpy` from 8 repos is one suggestion, not 8.
- **Deleted:** `facts.write_project_fact`. It stamped a reading as confirmed by the student and has
  no caller.

## 8. Thesis and report PDFs

- **A new upload kind**, `THESIS_OR_REPORT` ("Thesis or report"), is added to
  `apps/concierge/models.py::UPLOAD_KINDS`, with its choices migration. Only PDF is accepted
  for it: the upload check admits PDF, JPEG and PNG only, so a DOCX never passes it (amended
  2026-10-15). Images are refused at the door.
- **It is read on upload** by the refresh job's PDF path, through the existing `_document` code.
  The text comes from `extract_text`, the GuardDuty `AVAILABLE` check stays first, and the same
  `read_repo` call and §7.4 checks apply. Thesis techniques are kept; today they are discarded.
- **Budget:** `_MAX_DOCUMENT_CHARS` stays 200,000, about 50,000 input tokens per thesis, once per
  upload.
- **Each reading points at its upload** through a real foreign key to `DocumentVersion`, with the
  composite tenant guard.
  - A new upload replaces an old reading only when its `replaces` names that upload.
  - "Add another" keeps both.
  - A retired upload's reading is deleted.

## 9. Storage: `EvidenceReading`

A tenant table in `apps/documents/models.py`, mirroring `TranscriptReading`:

| Field | Notes | Erasure |
|---|---|---|
| `student` | FK to `Membership`, PROTECT, like `VerifiedFact`. It is operational data, not a training-derived table, so it does not point at `Pseudonym`. | — |
| `source_kind` | `github` or `pdf` | KEEP |
| `repo` | `owner/name` for `github`, empty for `pdf` | REDACT |
| `document` | FK to `DocumentVersion` for `pdf`, null for `github` | — |
| `changed_at` | repo `pushed_at`, or the upload's `created_at` | KEEP |
| `reader_version` | `READER_VERSION` when read | KEEP |
| `read_at` | | KEEP |
| `reading` | the checked `RepoReading` JSON, plus each bullet's verdict and the dates | REDACT |

**Constraints:** unique on (`student`, `repo`) for `github`, and (`student`, `document`) for
`pdf`.

**Migration:**
- RLS `ENABLE` plus `FORCE`, and the runtime grants;
- the composite tenant foreign-key guard (the `documents` 0029 pattern);
- the table added to `tests/migrations/test_documents_tenant_guards.py`'s `_RLS_TABLES` and
  `_COMPOSITE_FKS`.

**Erasure:**
- registered in `apps/audit/redaction.py`, with every field classified;
- rows deleted inside the `set_local_tenant` block of `advance_deletion`, like `PortalAnswer`;
- the erasure schedule is still the existing deployment blocker. Readings add data behind it; they
  do not change it.

**Nothing else reads this table** except `facts.py`. That keeps readings out of the confirm list
(`api.fact_candidates`, the documents page), the confirm button (`confirmation.py`), skill
tailoring (`tailoring.fact_pool`), the form-filling profile (`portals/profile.py`) and
`generatable_facts`.

## 10. Part B: where readings go on the CV (`apps/documents/cv_evidence.py`)

This part is built after Stages 2–4. It is specified here so Part A stores what it needs.

### 10.1 When it runs

At the top of `_generate` in the document worker, the refresh runs **inline** with a time budget
(the `_prepare(budget=...)` pattern). On timeout, generation uses the readings that exist. Placing
the readings then runs after Stage 3's fixes and before Stage 4's relevance check. It runs only
when `CV_REPO_BULLETS_ENABLED` is on, and only bullets with verdict `supported` are placed.

### 10.2 Is a reading part of an existing entry?

The CV's current entries are matched every time; no match is stored. A reading is part of an entry
when one of these holds:
1. **The organisation matches.** The repo owner is an organisation whose display name or login
   matches the entry's `employer` or `group`.
   - The name must be at least two words, or one word of eight or more characters.
   - Generic words (University, Institute, Lab, Group, Team) do not count towards the match.
   - The student must have made at least 3 commits there.
2. **The thesis matches.** A reading's `names` item equals a `thesis_title`. An education entry and
   a research entry sharing one thesis title count as **one** target.
3. **A shared name.** A reading's `names` item appears, as whole words, in the entry's `title`,
   `project`, `employer`, `group` or bullets, under the same floor of 2 words or 8+ characters.

**Exactly one target may match.** Two or more is unsure, and the reading goes nowhere. A match to
an education entry other than through its thesis is a side project (decision 10).

**Two readings for one target** (a thesis repo and the thesis PDF): the PDF wins on a research
target, and the repo wins on an experience target. A project whose `names` match a reading already
placed is dropped.

### 10.3 Adding to a matched entry

- **Experience entry:** up to 2 bullets, after the student's own, within the 12-bullet cap. A bullet
  already present (case and punctuation ignored) is skipped.
- **Research entry:** `methods` or `outcomes` filled only when empty.
- **Fields never touched:** employer, title, dates, institution, supervisor.

### 10.4 Side projects: the four tests

1. **It is not part of an entry.**
2. **There is something real to say:** `kind` is `project` or `course_project`, with at least one
   `supported` bullet.
3. **It fits the programme:** Stage 4's relevance check says yes. Until that check is on, no
   projects print.
4. **There is room:** at most 2 projects, or 3 when the CV has no research entry and no publication,
   or when the student is switching fields (S-029).

Projects are ordered by relevance, then recency. The rules behind the tests are R-026, R-028, S-029
and S-041; the caps are this design's own judgement.

**`ProjectEntry`** (`schemas.py`):
- `title` (≤300);
- `url` (optional);
- `start_date`, `end_date`: month and year;
- `bullets`: 1–3.

**`CVContent.projects`** defaults to `()`. `CVContent` is `extra="forbid"`, so the worker must be
rolled out before the web tier.

### 10.5 Printing

- **Layouts.** `cv_base.html` (standard), the German tabular layout and Europass. Europass gets its
  own `ProjectEntry` mapper, placed after research entries, never repeating a thesis. The Europass
  payload hash, and so its render cache, changes.
- **SISGP and Rhodes** print no Projects section; added bullets inside entries still apply there.
- **Order:**
  - **Taught track:** Education, Experience, Projects (R-026).
  - **Research track:** after Research and Publications. This is an assumption; see §15.
- **Fulbright's `no_hyperlinks` (R-017):** projects print without their link. The
  `_check_prohibited_content` check is extended to count project and publication URLs; today it
  flags only links and DOIs, and misses publication links.
- **Over the page limit:** added bullets and projects are dropped first, before Stage 1's compact
  retry.

### 10.6 "What we changed", undo, and letters

- **Each addition** is an `applied_fixes` entry, `added_from_github` or `added_from_pdf`.
- **Undo is keyed on the reading** (`repo`, or the upload id) plus the target: `fact_identity`, or
  `projects`. It is not keyed on the bullet text, so an undo survives a re-read.
- **Part B adds two things to `usable_readings`:** it filters out undone readings and bullets, and
  it adds the matched target.

## 11. The letter hand-off (`apps/documents/evidence/readings.py`, Part A)

`usable_readings(student) -> tuple[UsableReading, ...]` returns, for each reading:
- source (`github` or `pdf`), repo URL or document id;
- `summary`, `kind`, `names` and dates;
- the bullets that passed the §7.4 quote and number checks, each with its evidence spans and its
  support verdict.

It reads through `facts.py`. Undo filtering and the matched target come in Part B (§10.6). How a
letter uses a reading, including whether it requires `supported`, is the letter session's choice;
that session is told where this function is.

## 12. Running it

### 12.1 The job

- **A new queue action.** `DocumentQueue` gains `action="refresh_evidence"`. That means a new
  `DocumentWorkMessage.action` value, and the worker rolled out before the web tier, as
  `document_queue.py` describes.
- **Queued when:**
  - a login is set or changed;
  - a CV is uploaded (its links may name repos);
  - a `THESIS_OR_REPORT` file is uploaded.
- **In Part B,** CV generation also runs it inline (§10.1).
- **The GitHub half of a refresh is skipped** when one for the student finished in the last
  10 minutes; the PDF half always runs, so a thesis uploaded just after a CV is still read
  (amended 2026-10-15).
- **The per-student limit.** `rate_limited("evidence_intake", ...)` (20 an hour) counts model reads.
  When it is reached, the refresh logs, stops quietly and keeps what it has. It never crashes the
  worker: today the worker catches only `GenerationRateLimited` and `IngestionRateLimited`, and an
  uncaught `EvidenceRateLimited` would be redelivered forever.
- **Logging.** Every refresh logs GitHub requests, model calls and tokens.

### 12.2 The GitHub key

- **`GITHUB_TOKEN`** is a fine-grained, read-only token for public repositories only, with no
  organisation access, held in Secrets Manager.
- **Wiring:** referenced in `DocumentWorkerTaskDefinition`'s `Secrets`, pinned by
  `tests/infra/test_template.py`, and also on whatever task runs the operator command.
- **No token means no request:** the unauthenticated path through the shared NAT address is
  removed, and an error is logged for staff.
- **It is never logged** and never sent anywhere but `api.github.com`.

### 12.3 Failures

| What fails | What happens |
|---|---|
| No token, or it is rejected | No discovery. Error logged. Nothing deleted. |
| GitHub rate limit (primary or secondary) | `GitHubRateLimited`; the refresh stops. Nothing deleted. |
| Discovery incomplete (network error, non-200 page, GraphQL `errors`) | Nothing deleted. Reads continue for repos already known. |
| One repo fails to fetch | Its old reading is kept. |
| Unknown login | `data.user: null`. One student-facing message: "We couldn't find GitHub user X." |
| Model refuses, fails or answers off-schema | One retry. The old reading is kept if there is one. |
| A check fails | That bullet is dropped. |
| A crash while saving | Nothing saved. |

### 12.4 Cost (assumption)

**Per student:**
- **Discovery:** 2–4 requests, plus up to 10 fork checks of 2 requests each (metadata, then
  compare; amended 2026-10-15). RepoOverview's `parent` cannot replace the metadata call: the
  fork check runs in discovery, before any repo is read.
- **Per repo read:**
  - about 2 GraphQL points and 1–2 REST requests (§7.1), plus raw downloads for oversized
    notebooks or READMEs;
  - about 7,500 model tokens;
  - up to 5 support checks.
- **First refresh at 10 repos:** about 25 GraphQL points, about 20 REST requests and 75,000 tokens.
- **Later refreshes:** close to nothing.

**Per thesis:** about 50,000 tokens, once per upload.

**Platform:** the platform key allows 5,000 GraphQL points and 5,000 REST requests an hour, so
about 200 first-time students an hour, bound by GraphQL points. Repeat refreshes are nearly free
(unchanged repos are skipped, and `304` answers do not count). Beyond that: per-student GitHub
sign-in gives each student their own allowance. A paid GitHub Enterprise Cloud organisation raises
the key to 15,000 requests and 10,000 points an hour. Several keys to spread the load are not
allowed: GitHub's terms limit machine accounts.

## 13. Deletions and the operator command

- **`manage.py ingest_evidence`:**
  - `--source <repo>` and `--owner` are removed;
  - a new `--student` option runs `refresh_evidence` and prints the readings;
  - `--source <doi>` stays, because it is the only caller of the DOI path (`intake._publication`,
    `write_publication_fact`).
- **Deleted:**
  - `authorship` and `Authorship`;
  - the ownership branches and the "We found N commits" question in `_repository`;
  - `owner_login` everywhere;
  - `write_project_fact`;
  - `ProposedDescription` (replaced by `RepoReading`).
- **Tests rewritten or deleted:**
  - `tests/documents/evidence/`: `test_repo.py`, `test_intake.py`, `test_facts.py`,
    `test_extraction.py`, `test_live_contracts.py`, and `test_invariants.py` (its `IntakeResult`
    wording);
  - `tests/documents/test_ingest_evidence_command.py`;
  - `tests/documents/test_live_evidence.py`.
- **Rules:** the `owner_login` paragraph in `.claude/rules/llm-ai-security.md` is rewritten for the
  new path. `.claude/rules/web-fetching.md` records the GitHub transport (§5.3).
- **Privacy:** one line is added to all six privacy notices (direct and agency; English,
  Azerbaijani, Russian) under "What we process": "public information from your GitHub account and
  the repositories you contributed to, when you give us your GitHub username or your CV links it."
  The wording is for the owner's lawyer list.

## 14. Testing (Part A)

**Unit tests in the existing style** (fake GitHub responses):
- **Discovery and the transport:**
  - every listing page read;
  - the 10-year GraphQL query, its `errors`, and `data.user: null`;
  - forks filtered by `pushed_at > created_at`;
  - CV links re-extracted;
  - unsafe `owner/name` refused;
  - `GitHubRateLimited` on both limit kinds;
  - no token means no request.
- **Selection:**
  - group 2 needs at least 3 commits and is ranked by commits;
  - the caps;
  - the skips;
  - the re-read rule (`changed_at`, `reader_version`);
  - deletion only after a complete discovery;
  - a per-repo failure keeps the old reading.
- **Evidence:**
  - README capped at 6,000 and placed after the code;
  - `strip_markup`;
  - commit trailers removed;
  - `?author=` commits used for non-owned repos;
  - the test-file rules (`latest_model.py` is read);
  - `requirements.txt` unread;
  - `.txt` data dumps skipped;
  - an LFS pointer treated as absent;
  - tree depth-sorted before the cut;
  - paths quoted;
  - a 241 KB notebook read whole, with an image-only output skipped;
  - the 500-character evidence floor;
  - the login absent from the prompt.
- **Checks:**
  - a quote not in the evidence drops the bullet;
  - `10B+` not in the bullet's spans drops the bullet;
  - a failed or rate-limited call gives `unchecked`;
  - an answer stores `supported` or `rejected`.
- **Skills:** a re-read never supersedes a confirmed skill; one name across 8 repos is one
  suggestion.
- **PDF:**
  - the kind refuses images;
  - `replaces` replaces, "Add another" keeps both, retiring deletes.
- **Username endpoint:** validation, the limiter, set/change/clear.
- **The job:** the 10-minute skip; `EvidenceRateLimited` stops quietly.

**Database properties:**
- **Saving in one step:** the model call succeeds, then the save raises an error the code does not
  catch; no reading and no skill suggestion survives.
- **Nothing picks readings up by accident:** a saved reading appears in none of
  `generatable_facts`, `api.fact_candidates`, `tailoring.fact_pool` or `portals/profile`.
- **Tenant isolation:** the table is tested behind the `rls_enforced_orm` fixture.
- **Migration guards:** the guard tests' lists are updated.
- **Erasure:** every field classified; erasing a student deletes their readings.

**Fixtures:**
- recorded responses for `0rkhann/MicroKatc` and `0rkhann/nhc-bo-benchmark`;
- the trial's synthetic repo.

**Live check** (`-m live`): one refresh of the owner's account with the real model. Run files go to
`~/agent-workspace/elmify-runs/cv-evidence/<run>`.

**Before Part B prints anything:**
1. The owner labels 30–50 real bullets as supported or not.
2. A command reports how often the support check agrees.
3. `CV_REPO_BULLETS_ENABLED` is switched on at the pass mark.

## 15. Open points

**For the owner, not blocking:**
1. **Wording for group projects.** One option: repo bullets open only with Stage 3's level-1 verbs
   unless the matched entry's own words unlock stronger ones.
2. **The 2 and 3 project caps,** and how "switching fields" is decided (proposed: no degree's field
   matches the programme's, by Stage 4's relevance question).
3. **Dates for an owned repo include bot commits** (decision 1). A repo with scheduled
   `github-actions` commits will show a span running up to today. If that misleads on real CVs,
   restrict dates to non-bot commits; that is a dates rule, not an ownership rule.

**To research before Part B:**
- Projects on a research-track master's CV: how many, and where. Look in `cv-rules.csv` (R-026,
  R-027, R-028) and `cv-style-rules.csv` (S-029, S-039, S-041).
- The support check's accuracy on non-English evidence, measured in §14.
- Whether Stage 4's relevance question needs a project wording
  (`docs/research/2026-10-12-cv-engine/jev-relevance-questions.md`).

**Confirmed during Part A, with a fallback:**
- That one GraphQL request carries ten years. Fallback: one request per year.

**Later:**
- private repos through a GitHub App;
- scanned PDFs;
- pypdfium2;
- GitLab.
