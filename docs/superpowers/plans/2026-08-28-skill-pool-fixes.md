# Skill Pool Fixes Implementation Plan (plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every name in a student's skill pool something a machine measured, and give each name the evidence that backs it.

**Architecture:** Delete the eight import regexes in `signals.py` that scan arbitrary source text and replace them with parsers for the dependency manifests those languages already ship. Rank libraries by how many files import them rather than alphabetically. Extend `SkillEntry` with a `kind` and an `evidence` string, carried in the fact payload for provenance and never compared by the verifier.

**Tech Stack:** Python 3.12, Django 5.2, Pydantic 2, pytest, `json` / `tomllib` (stdlib), `defusedxml` (already a runtime dependency).

**Spec:** `docs/superpowers/specs/2026-08-27-skill-tailoring-design.md` (sections 4.1-4.3; this plan implements shipping-order step 1 only)

## Global Constraints

- Run tests as `POSTGRES_DB=tehsil_ei uv run pytest -q`. The shared `test_tehsil` database wedges across parallel sessions and the symptom looks like an unrelated regression.
- `uv run ruff check apps config tests` and `uv run mypy apps config` must pass before every commit. Do **not** run `ruff format` -- this repo is lint-only and formatting churns 26 unrelated files.
- Nothing in `apps/documents/evidence/` may import `django.db` except `facts.py`. `tests/documents/evidence/test_invariants.py` pins this.
- No new third-party dependency. Every parser in this plan uses the standard library or `defusedxml`, which is already in `[project].dependencies`.
- Model-read content stays `confirmed_by=None`. This plan does not change any confirmation state.
- Commit messages end with the two trailers used across this repo:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` and the `Claude-Session:` line.

---

### Task 1: Manifest parsing replaces the import regexes

Deletes `_IMPORT_PATTERNS`, `_NOT_A_PACKAGE`, `_REVERSE_DNS`, `_package_head` and `foreign_signals` from `signals.py`, and adds one parser per dependency manifest. This is the task that makes `leave` impossible.

**Files:**
- Modify: `apps/documents/evidence/signals.py` (delete lines defining `_IMPORT_PATTERNS`, `_NOT_A_PACKAGE`, `_REVERSE_DNS`, `_package_head`, `foreign_signals`; add the manifest parsers; correct the module docstring's rung 8 paragraph)
- Test: `tests/documents/evidence/test_signals.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `MANIFEST_FILES: tuple[str, ...]` -- the manifest filenames to fetch by name.
  - `manifest_libraries(path: str, text: str) -> tuple[str, ...]` -- declared dependency names from one manifest, sorted; `()` for an unrecognised or unparseable file.
  - `file_signals(path, text, *, local=frozenset()) -> FileSignals` -- unchanged signature; a non-Python, non-notebook, non-prose file now yields `FileSignals(path=path)` with no imports.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/evidence/test_signals.py`:

```python
from apps.documents.evidence.signals import (
    MANIFEST_FILES,
    file_signals,
    manifest_libraries,
)


def test_prose_in_a_source_comment_is_not_a_package():
    """The regression this task exists for.

    The deleted Julia/MATLAB pattern captured the token after `using` on any
    line of any non-Python file, so an English comment named a package.
    """
    source = "/* using leave-one-out cross validation */\nint main(void){return 0;}\n"
    assert file_signals("src/fit.c", source).imports == ()


def test_package_json_yields_its_declared_dependencies():
    text = """
    {
      "name": "my-project",
      "dependencies": {"react": "^19.0.0", "d3": "^7.9.0"},
      "devDependencies": {"vitest": "^2.1.0"}
    }
    """
    assert manifest_libraries("package.json", text) == ("d3", "react", "vitest")


def test_cargo_toml_yields_its_declared_dependencies():
    text = '[package]\nname = "mine"\n\n[dependencies]\nserde = "1"\ntokio = { version = "1" }\n'
    assert manifest_libraries("Cargo.toml", text) == ("serde", "tokio")


def test_go_mod_names_a_module_by_its_last_segment():
    text = "module example.com/mine\n\ngo 1.22\n\nrequire (\n\tgithub.com/spf13/cobra v1.8.0\n)\n"
    assert manifest_libraries("go.mod", text) == ("cobra",)


def test_r_description_drops_the_language_itself_and_version_bounds():
    text = "Package: mine\nDepends: R (>= 4.0)\nImports:\n    dplyr (>= 1.0),\n    ggplot2\n"
    assert manifest_libraries("DESCRIPTION", text) == ("dplyr", "ggplot2")


def test_pom_takes_artifact_ids_of_dependencies_not_of_the_project():
    text = (
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<artifactId>my-project</artifactId>"
        "<dependencies><dependency>"
        "<groupId>org.apache.spark</groupId><artifactId>spark-sql</artifactId>"
        "</dependency></dependencies></project>"
    )
    assert manifest_libraries("pom.xml", text) == ("spark-sql",)


def test_a_malformed_manifest_yields_nothing_rather_than_raising():
    for name in MANIFEST_FILES:
        assert manifest_libraries(name, "{not valid in any format") == ()


def test_an_unrecognised_filename_is_not_a_manifest():
    assert manifest_libraries("requirements.txt", "numpy==2.0\n") == ()


def test_python_imports_are_unaffected():
    signals = file_signals("run.py", "import numpy\nfrom scipy import optimize\n")
    assert signals.imports == ("numpy", "scipy")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_ei uv run pytest tests/documents/evidence/test_signals.py -q`
Expected: FAIL with `ImportError: cannot import name 'MANIFEST_FILES'`.

- [ ] **Step 3: Delete the regex tier**

In `apps/documents/evidence/signals.py`, delete these five definitions entirely: `_IMPORT_PATTERNS`, `_NOT_A_PACKAGE`, `_REVERSE_DNS`, `_package_head`, `foreign_signals`. Delete the now-unused `import re` only if no other use remains in the file (the manifest parsers below reintroduce one, so keep it).

Then replace the module docstring's rung-8 paragraph, which currently over-generalises the pip-freeze objection:

```python
Rung 8 is the measured part, and it is narrower than it looks. The validated
repository's requirements.txt is a pip freeze of the author's entire operating
system (apturl, Brlapi, blinker, bcrypt), so Python's declared dependency file
is not read. That objection is about pip freeze, not about declared
dependencies in general: package.json's "dependencies" and Cargo.toml's
[dependencies] are hand-written lists of what a project asks for, and they are
parsed exactly (rung 3b). A language whose manifest is absent contributes no
libraries -- nothing is guessed from prose.
```

- [ ] **Step 4: Add the manifest parsers**

Add to `apps/documents/evidence/signals.py`, after `python_signals`:

```python
#: Dependency manifests we can parse exactly. Each is a hand-written list of
#: what a project asks for, which is what separates them from a pip freeze.
MANIFEST_FILES: tuple[str, ...] = (
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "DESCRIPTION",
)

#: A go.mod require line: a module path followed by a version token. Narrow on
#: purpose -- this is one file whose grammar we know, not arbitrary source, and
#: the deleted regex tier failed precisely because it read arbitrary source.
_GO_REQUIRE = re.compile(r"^\s*(?:require\s+)?([a-z][\w.\-]*\.[a-z]{2,}[\w./\-]*)\s+v", re.MULTILINE)

#: R DESCRIPTION fields that name packages. "R" itself is the language.
_R_DEPENDENCY_FIELDS = frozenset({"Imports", "Depends", "Suggests"})


def _npm_manifest(text: str) -> tuple[str, ...]:
    try:
        document = json.loads(text)
    except ValueError:
        return ()
    if not isinstance(document, dict):
        return ()
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = document.get(key)
        if isinstance(section, dict):
            names.update(name for name in section if isinstance(name, str) and name)
    return tuple(sorted(names))


def _cargo_manifest(text: str) -> tuple[str, ...]:
    try:
        document = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return ()
    names: set[str] = set()
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        section = document.get(key)
        if isinstance(section, dict):
            names.update(name for name in section if isinstance(name, str) and name)
    return tuple(sorted(names))


def _go_manifest(text: str) -> tuple[str, ...]:
    """A module path is named by its last segment: the name a human uses."""
    return tuple(sorted({path.split("/")[-1] for path in _GO_REQUIRE.findall(text)}))


def _pom_manifest(text: str) -> tuple[str, ...]:
    """artifactIds of <dependency> elements only.

    A pom names the project with an artifactId too, so the whole-document scan
    would report the project as its own dependency. Tags carry an XML
    namespace, hence the rpartition on '}'.
    """
    try:
        root = DefusedElementTree.fromstring(text)
    except DefusedElementTree.ParseError:
        return ()
    names: set[str] = set()
    for element in root.iter():
        if element.tag.rpartition("}")[2] != "dependency":
            continue
        for child in element:
            if child.tag.rpartition("}")[2] == "artifactId" and child.text:
                names.add(child.text.strip())
    return tuple(sorted(name for name in names if name))


def _description_manifest(text: str) -> tuple[str, ...]:
    """R's DESCRIPTION: comma-separated names, continued on indented lines."""
    names: set[str] = set()
    field: str | None = None
    for line in text.splitlines():
        if line[:1].isspace():
            body = line if field is not None else ""
        else:
            head, _, body = line.partition(":")
            field = head.strip() if head.strip() in _R_DEPENDENCY_FIELDS else None
            if field is None:
                continue
        for part in body.split(","):
            name = part.strip().partition("(")[0].strip()
            if name and name != "R" and name.replace(".", "").isalnum():
                names.add(name)
    return tuple(sorted(names))


_MANIFEST_PARSERS = {
    "package.json": _npm_manifest,
    "Cargo.toml": _cargo_manifest,
    "go.mod": _go_manifest,
    "pom.xml": _pom_manifest,
    "DESCRIPTION": _description_manifest,
}


def manifest_libraries(path: str, text: str) -> tuple[str, ...]:
    """Declared dependency names from one manifest, or () if it is not one.

    Never raises. A manifest we cannot parse is a manifest we learn nothing
    from, which is the same outcome as one that is not there.
    """
    parser = _MANIFEST_PARSERS.get(path.split("/")[-1])
    return parser(text[:_MAX_FILE_CHARS]) if parser is not None else ()
```

Add `import tomllib` to the stdlib imports and `from defusedxml import ElementTree as DefusedElementTree` to the third-party imports.

- [ ] **Step 5: Make `file_signals` stop guessing**

Replace the final line of `file_signals` so an unparseable source file yields nothing rather than regex output:

```python
def file_signals(
    path: str, text: str, *, local: frozenset[str] = frozenset()
) -> FileSignals:
    if path.endswith(".ipynb"):
        return notebook_signals(path, text, local=local)
    if path.endswith(_PROSE_SUFFIXES):
        return prose_signals(path, text)
    if path.endswith(".py"):
        return python_signals(path, text, local=local)
    # A language we have no parser for. Its dependencies are read from its
    # manifest by manifest_libraries, never guessed from its source.
    return FileSignals(path=path)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_ei uv run pytest tests/documents/evidence/test_signals.py -q`
Expected: PASS. Some existing tests in this file assert on `foreign_signals`; delete those tests -- the function they cover no longer exists and the behaviour they pinned is the defect.

- [ ] **Step 7: Run the full suite and the gates**

Run:
```bash
POSTGRES_DB=tehsil_ei uv run pytest -q
uv run ruff check apps config tests
uv run mypy apps config
```
Expected: all pass. `test_intake.py` may fail if a fixture relied on regex-derived imports; if so, update the fixture to supply a manifest instead -- that is the point of the change, not a regression.

- [ ] **Step 8: Commit**

```bash
git add apps/documents/evidence/signals.py tests/documents/evidence/test_signals.py
git commit -m "$(cat <<'EOF'
fix(evidence): read declared manifests instead of regexing foreign source

Eight import patterns ran over every non-Python file, so the Julia/MATLAB rule
fired on English comments and a line reading `using leave-one-out cross
validation` produced the package `leave`. They are deleted, not tightened.

The languages those patterns served declare their dependencies in files that
parse exactly -- package.json, Cargo.toml, go.mod, pom.xml, R's DESCRIPTION --
and a name in one of those provably resolves, which the regexes could never
tell. requirements.txt stays unread: that objection was always about pip
freeze, and the docstring no longer generalises it to every manifest.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Fetch the manifests and count imports

`_repo_evidence` currently collapses imports into a set, which is why the cut in Task 3 has nothing to rank by. This task fetches manifests by name and returns counts.

**Files:**
- Modify: `apps/documents/evidence/intake.py:246-320` (`_Evidence`, `_repo_evidence`)
- Test: `tests/documents/evidence/test_intake.py`

**Interfaces:**
- Consumes: `MANIFEST_FILES`, `manifest_libraries` from Task 1.
- Produces: `_Evidence.libraries: tuple[tuple[str, int], ...]` -- `(name, file_count)` pairs, most-imported first, ties by name. A manifest-declared name that no parsed file imports has count `0`.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/evidence/test_intake.py`. `FakeTransport(responses)` already exists there at line 73 and matches a URL *fragment* to a `(status, body)` pair, so `fetch_file`'s `/contents/<path>` requests need one entry each, base64-encoded the way the GitHub contents API returns them.

```python
def _contents(files):
    """FakeTransport responses shaped like the GitHub contents API."""
    return {
        f"/contents/{path}": (
            200,
            {"encoding": "base64", "content": base64.b64encode(body.encode()).decode()},
        )
        for path, body in files.items()
    }


def _repo_snapshot(**overrides):
    base = dict(
        ref=RepoRef("github", "0rkhann", "MicroKatc"),
        description="",
        is_fork=False,
        parent=None,
        languages={"Python": 60731},
        contributors={"0rkhann": 21},
        commit_count=21,
        first_commit=None,
        last_commit=None,
        ahead_by=None,
        file_names=("package.json",),
    )
    base.update(overrides)
    return RepoSnapshot(**base)


def test_libraries_carry_import_counts_and_include_manifest_names():
    """Counts come from parsed files; manifest names appear even at zero."""
    snapshot = _repo_snapshot(tree_paths=("a.py", "b.py", "package.json"))
    transport = FakeTransport(
        _contents(
            {
                "a.py": "import numpy\nimport torch\n",
                "b.py": "import torch\n",
                "package.json": '{"dependencies": {"d3": "^7"}}',
            }
        )
    )

    evidence = _repo_evidence(snapshot.ref, snapshot, token=None, transport=transport)

    assert evidence.libraries == (("torch", 2), ("numpy", 1), ("d3", 0))
```

Add `import base64` and `from apps.documents.evidence.repo import RepoSnapshot`, `from apps.documents.evidence.sources import RepoRef`, and `_repo_evidence` to this file's imports.

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_ei uv run pytest tests/documents/evidence/test_intake.py::test_libraries_carry_import_counts_and_include_manifest_names -v`
Expected: FAIL -- `libraries` is a tuple of bare strings.

- [ ] **Step 3: Change `_Evidence` and the import collection**

In `apps/documents/evidence/intake.py`, change the dataclass:

```python
@dataclass(frozen=True)
class _Evidence:
    text: str
    #: (name, number of parsed files importing it), most-imported first.
    #: A manifest-declared name no parsed file imports carries 0 -- declared
    #: is evidence enough to propose it, just weaker than declared and used.
    libraries: tuple[tuple[str, int], ...]
```

Replace the rung-3 block in `_repo_evidence`:

```python
    # Rung 3: what the code actually imports, and how often. The count is the
    # ranking evidence -- an alphabetical cut keeps `ase` and drops `torch`.
    counts = Counter(name for signal in parsed for name in signal.imports)

    # Rung 3b: what the project declares it asks for. Fetched by name because
    # interesting_paths selects source and prose, not manifests.
    for name in MANIFEST_FILES:
        if name not in snapshot.file_names:
            continue
        text = fetch_file(ref, name, token=token, transport=transport)
        for declared in manifest_libraries(name, text):
            counts.setdefault(declared, 0)

    libraries = tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    if libraries:
        chunks.append("Imported libraries: " + ", ".join(name for name, _ in libraries))
```

Add `from collections import Counter` to the stdlib imports, and add both `MANIFEST_FILES` and `manifest_libraries` to the existing `from .signals import (...)` block -- both live in `signals.py`.

Change the return:

```python
    return _Evidence(
        text="\n\n".join(chunks)[:_MAX_EVIDENCE_CHARS],
        libraries=libraries,
    )
```

- [ ] **Step 4: Update the call site**

At `apps/documents/evidence/intake.py:168-173`, `write_library_skill_facts` is called with `libraries=evidence.libraries`. Leave the call as it is -- Task 3 changes the parameter's type on the writer's side.

**Correction, applied during execution:** this makes Task 2 unlandable on its own. The moment intake returns `(name, count)` pairs, mypy fails at this call site until Task 3 changes the signature, and this plan's own Global Constraints require mypy to pass before every commit. Tasks 2 and 3 were therefore executed and committed together (`5445b33`). A reviewer can still read them as two changes; they cannot be two commits.

- [ ] **Step 5: Run the test to verify it passes**

Run: `POSTGRES_DB=tehsil_ei uv run pytest tests/documents/evidence/test_intake.py -q`
Expected: the new test passes. `uv run mypy apps config` still reports one error at the `write_library_skill_facts` call; that is Task 3's.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/evidence/intake.py tests/documents/evidence/test_intake.py
git commit -m "$(cat <<'EOF'
feat(evidence): count how often a library is imported, and read manifests

The set of import names carried no ranking signal, so the cut downstream was
alphabetical. Imports are counted per parsed file, and a project's manifest is
fetched by name and folded in at zero: declared is enough to propose a skill,
just weaker evidence than declared and used.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Rank libraries by evidence, not by alphabet

**Files:**
- Modify: `apps/documents/evidence/facts.py` (`write_library_skill_facts`)
- Test: `tests/documents/evidence/test_facts.py`

**Interfaces:**
- Consumes: `_Evidence.libraries: tuple[tuple[str, int], ...]` from Task 2.
- Produces: `write_library_skill_facts(*, student, snapshot, libraries: tuple[tuple[str, int], ...]) -> tuple[VerifiedFact, ...]` -- writes at most `_MAX_LIBRARY_SKILLS` rows, most-imported first.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/evidence/test_facts.py`:

`test_facts.py` sets `pytestmark = pytest.mark.django_db` at module level, so no per-test marker. It builds its subjects with the `_snapshot(**overrides)` helper at line 122 and `_student(agency, django_user_model, name)` at line 40, inside `tenant_scope`. Follow that:

```python
def test_the_library_cut_keeps_the_most_imported_not_the_alphabetically_first(
    agency_a, django_user_model
):
    """`ase` beat `torch` only because the truncation sorted by name."""
    libraries = tuple((f"pkg{index:02d}", 1) for index in range(20)) + (("torch", 9),)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-rank")
        facts = write_library_skill_facts(
            student=student, snapshot=_snapshot(), libraries=libraries
        )

    names = [fact.payload["name"] for fact in facts]
    assert len(names) == 15
    assert names[0] == "torch"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_ei uv run pytest tests/documents/evidence/test_facts.py -k most_imported -v`
Expected: FAIL -- `sorted()` on `(name, count)` tuples sorts by name, so `pkg00` leads.

- [ ] **Step 3: Change the writer**

In `apps/documents/evidence/facts.py`, change the signature and the `names=` argument of `write_library_skill_facts`:

```python
def write_library_skill_facts(
    *,
    student: Membership,
    snapshot: RepoSnapshot,
    libraries: tuple[tuple[str, int], ...],
) -> tuple[VerifiedFact, ...]:
```

and

```python
        names=tuple(
            name
            for name, _count in sorted(libraries, key=lambda item: (-item[1], item[0]))
        )[:_MAX_LIBRARY_SKILLS],
```

Update the `_MAX_LIBRARY_SKILLS` comment, which currently claims the head of an alphabetical list is the story:

```python
#: A repository can import a long tail; the most-imported head is the story.
#: The rank is the file count from intake's Counter, not the name.
_MAX_LIBRARY_SKILLS = 15
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
POSTGRES_DB=tehsil_ei uv run pytest tests/documents/evidence/ -q
uv run mypy apps config
```
Expected: all pass, and the mypy error Task 2 left behind is gone.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/evidence/facts.py tests/documents/evidence/test_facts.py
git commit -m "$(cat <<'EOF'
fix(evidence): cut libraries by import count, not alphabetically

sorted(libraries)[:15] kept `ase` and dropped `torch` while the comment claimed
the head of the list was the story. It was the alphabetic head. Rank by the
number of files importing a name, ties by name.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `SkillEntry` carries a kind and its evidence

**Files:**
- Modify: `apps/documents/schemas.py:211-224` (`SkillEntry`)
- Modify: `apps/documents/verification.py:201` (the skills line of `_PAYLOAD_KEYS`)
- Test: `tests/documents/test_verification.py` (the file that already covers `fact_payload`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `SkillEntry(name: str, category: str | None = None, kind: str | None = None, evidence: str | None = None)`. `kind` is one of `"language"`, `"library"`, `"technique"`. `evidence` is a short human-readable justification. Both are carried in the SKILL payload and never compared by the verifier.

- [ ] **Step 1: Write the failing test**

```python
def test_skill_payload_carries_kind_and_evidence_without_comparing_them():
    entry = SkillEntry(name="torch", category="Libraries and frameworks",
                       kind="library", evidence="imported by 9 files")

    payload = fact_payload(entry, category=VerifiedFact.Category.SKILL)

    assert payload["kind"] == "library"
    assert payload["evidence"] == "imported by 9 files"
    # Identity is the name alone: re-ingesting with different evidence must
    # supersede the row, not create a second skill.
    assert payload["name"] == "torch"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_ei uv run pytest -k skill_payload_carries -v`
Expected: FAIL with a Pydantic `ValidationError` -- `SkillEntry` forbids extra fields.

- [ ] **Step 3: Extend the schema**

In `apps/documents/schemas.py`, add to `SkillEntry`:

```python
    name: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    #: How this name was derived: "language" (host byte count), "library"
    #: (a parsed import or a declared manifest entry) or "technique" (read by
    #: a model out of the project's prose). Tailoring reads this, not the
    #: rendered heading -- see the skill-tailoring design, section 4.1.
    kind: str | None = Field(default=None, max_length=20)
    #: What backs the name, in a sentence a human can check: "12431 bytes",
    #: "imported by 9 files", or the excerpt that named a technique.
    evidence: str | None = Field(default=None, max_length=1_000)
```

- [ ] **Step 4: Carry them in the payload, uncompared**

In `apps/documents/verification.py`, change line 201:

```python
    # category/kind/evidence are provenance, never compared: how a skill was
    # derived and what backs it are facts about our reading, not claims the
    # applicant can contradict. Same treatment as publications' volume/issue/
    # pages -- see the module docstring on what SUPPORTED means.
    + (("category", "kind", "evidence") if spec.field == "skills" else ())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
POSTGRES_DB=tehsil_ei uv run pytest -q
uv run mypy apps config
```
Expected: all pass. No existing verdict changes -- the new keys are outside `spec.identity` and `spec.detail`, so nothing new is compared.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/schemas.py apps/documents/verification.py tests/
git commit -m "$(cat <<'EOF'
feat(documents): give a skill its kind and the evidence behind it

A skill was a word and a heading, which cannot be ranked and cannot be shown to
anyone. kind records how the name was derived; evidence records what backs it.
Both are carried for provenance and never compared -- how we read a repository
is not a claim the applicant can contradict, the same reasoning that keeps a
publication's volume out of the verdict.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The writers populate kind and evidence

**Files:**
- Modify: `apps/documents/evidence/facts.py` (`_write_skills`, `write_skill_facts`, `write_library_skill_facts`, `write_technique_skill_facts`)
- Test: `tests/documents/evidence/test_facts.py`

**Interfaces:**
- Consumes: `SkillEntry.kind` / `.evidence` from Task 4; the `(name, count)` pairs from Task 3.
- Produces: `_write_skills(..., entries: tuple[tuple[str, str], ...], kind: str, ...)` -- `entries` are `(name, evidence)` pairs; `kind` is stamped on every row the call writes.

- [ ] **Step 1: Write the failing test**

```python
def test_each_skill_row_records_what_backs_it(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-evidence")
        languages = write_skill_facts(student=student, snapshot=_snapshot())
        libraries = write_library_skill_facts(
            student=student, snapshot=_snapshot(), libraries=(("torch", 9), ("d3", 0))
        )

    assert all(fact.payload["kind"] == "language" for fact in languages)
    assert languages[0].payload["evidence"].endswith(" bytes")

    by_name = {fact.payload["name"]: fact.payload for fact in libraries}
    assert by_name["torch"]["kind"] == "library"
    assert by_name["torch"]["evidence"] == "imported by 9 files"
    assert by_name["d3"]["evidence"] == "declared in the project's manifest"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_DB=tehsil_ei uv run pytest tests/documents/evidence/test_facts.py -k records_what_backs -v`
Expected: FAIL with `KeyError: 'kind'` -- the writers still build `SkillEntry(name=..., category=...)`.

- [ ] **Step 3: Change `_write_skills` to take pairs and a kind**

In `apps/documents/evidence/facts.py`:

```python
def _write_skills(
    *,
    student: Membership,
    snapshot: RepoSnapshot,
    entries: tuple[tuple[str, str], ...],
    heading: str,
    kind: str,
    prefix: str,
    tier: str,
    confirmed: bool,
) -> tuple[VerifiedFact, ...]:
    """One skill row per (name, evidence) pair, under one heading.

    ``prefix`` namespaces the source_ref so a library and a language of the
    same name supersede their own row and not each other's.
    """
    source_ref = _repo_source_ref(snapshot)
    now = timezone.now() if confirmed else None
    return tuple(
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.SKILL,
            payload=fact_payload(
                SkillEntry(name=name, category=heading, kind=kind, evidence=evidence),
                category=VerifiedFact.Category.SKILL,
            ),
            source_tier=tier,
            source_ref=f"{source_ref}#{prefix}{name}",
            confirmed_by=student if confirmed else None,
            confirmed_at=now,
            supersedes=_previous(
                student, f"{source_ref}#{prefix}{name}", VerifiedFact.Category.SKILL
            ),
            created_by=student,
        )
        for name, evidence in entries
    )
```

- [ ] **Step 4: Update the three callers**

`write_skill_facts`:

```python
        entries=tuple(
            (language, f"{size} bytes")
            for language, size in sorted(snapshot.languages.items())
            if size >= _LANGUAGE_FLOOR_BYTES
        ),
        heading=_LANGUAGES,
        kind="language",
```

`write_library_skill_facts`:

```python
        entries=tuple(
            (
                name,
                f"imported by {count} files" if count else "declared in the project's manifest",
            )
            for name, count in sorted(libraries, key=lambda item: (-item[1], item[0]))
        )[:_MAX_LIBRARY_SKILLS],
        heading=_LIBRARIES,
        kind="library",
```

`write_technique_skill_facts` keeps `names` for now; Task 6 gives it excerpts:

```python
        entries=tuple((name, "") for name in dict.fromkeys(techniques))[:_MAX_TECHNIQUE_SKILLS],
        heading=_TECHNIQUES,
        kind="technique",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
POSTGRES_DB=tehsil_ei uv run pytest -q
uv run ruff check apps config tests
uv run mypy apps config
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/evidence/facts.py tests/documents/evidence/test_facts.py
git commit -m "$(cat <<'EOF'
feat(evidence): record what backs each skill, per kind

A byte count for a language, an import count or a manifest declaration for a
library. The three headings stop being the carrier of meaning: what a later
tailoring pass reads is the kind, which is set by how the name was derived.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: A technique carries the excerpt that named it

The last kind with no evidence. This changes the extraction schema, so it is last: everything before it is mechanical and lands without touching a model.

**Files:**
- Modify: `apps/documents/evidence/extraction.py` (`ProposedDescription`, the developer prompt)
- Modify: `apps/documents/evidence/facts.py` (`write_technique_skill_facts`)
- Modify: `apps/documents/evidence/intake.py:184-190` (the call site)
- Test: `tests/documents/evidence/test_extraction.py`, `tests/documents/evidence/test_facts.py`

**Interfaces:**
- Consumes: `_write_skills(..., entries, kind=...)` from Task 5.
- Produces:
  - `Technique(name: str, excerpt: str)` -- a Pydantic model, `extra="forbid"`, `frozen=True`.
  - `ProposedDescription.techniques: tuple[Technique, ...]`, max length 12.
  - `write_technique_skill_facts(*, student, snapshot, techniques: tuple[Technique, ...])`.

- [ ] **Step 1: Write the failing tests**

In `tests/documents/evidence/test_extraction.py`:

```python
def test_a_technique_must_quote_the_text_that_named_it():
    with pytest.raises(ValidationError):
        ProposedDescription(thesis_title="t", techniques=({"name": "PCA"},))

    parsed = ProposedDescription(
        thesis_title="t",
        techniques=({"name": "PCA", "excerpt": "reduced the descriptors with PCA"},),
    )
    assert parsed.techniques[0].excerpt == "reduced the descriptors with PCA"
```

In `tests/documents/evidence/test_facts.py`:

```python
def test_a_technique_row_stores_its_excerpt_as_evidence(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-technique")
        facts = write_technique_skill_facts(
            student=student,
            snapshot=_snapshot(),
            techniques=(Technique(name="PCA", excerpt="reduced the descriptors with PCA"),),
        )

    assert facts[0].payload["kind"] == "technique"
    assert facts[0].payload["evidence"] == "reduced the descriptors with PCA"
    assert facts[0].confirmed_by is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_ei uv run pytest tests/documents/evidence/test_extraction.py tests/documents/evidence/test_facts.py -k technique -v`
Expected: FAIL -- `Technique` does not exist.

- [ ] **Step 3: Add the model and change the field**

In `apps/documents/evidence/extraction.py`, above `ProposedDescription`:

```python
class Technique(BaseModel):
    """A named method, and the text in DATA that named it.

    The excerpt is required, not decorative. A name the model cannot quote
    from the repository's own words is a name it supplied, and this schema
    makes supplying one cost a fabricated quote rather than nothing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(min_length=1, max_length=500)
```

and in `ProposedDescription`:

```python
    techniques: tuple[Technique, ...] = Field(default=(), max_length=12)
```

- [ ] **Step 4: Extend the prompt**

In `propose_description`'s developer message, replace the final techniques sentence:

```python
                    "Give the method its ordinary name, not this project's "
                    "wording for it, and set excerpt to the span of DATA that "
                    "named it -- quoted from DATA, never written by you. "
                    "Leave techniques empty rather than padding it."
```

- [ ] **Step 5: Change the writer and the call site**

In `apps/documents/evidence/facts.py`:

```python
def write_technique_skill_facts(
    *, student: Membership, snapshot: RepoSnapshot, techniques: tuple[Technique, ...]
) -> tuple[VerifiedFact, ...]:
```

with

```python
        entries=tuple(
            {technique.name: (technique.name, technique.excerpt) for technique in techniques}.values()
        )[:_MAX_TECHNIQUE_SKILLS],
```

Import `Technique` from `.extraction` in `facts.py`. The `intake.py` call site at line 188 passes `techniques=proposal.techniques` and needs no change -- the type it passes is now `tuple[Technique, ...]`.

- [ ] **Step 6: Run the tests to verify they pass**

Run:
```bash
POSTGRES_DB=tehsil_ei uv run pytest -q
uv run ruff check apps config tests
uv run mypy apps config
POSTGRES_DB=tehsil_ei uv run python manage.py makemigrations --check --dry-run
```
Expected: all pass; no migrations (nothing here is a model field).

- [ ] **Step 7: Commit**

```bash
git add apps/documents/evidence/extraction.py apps/documents/evidence/facts.py tests/documents/evidence/
git commit -m "$(cat <<'EOF'
feat(evidence): make a technique quote the text that named it

techniques was a bare list of strings, so a name the model supplied and a name
the repository stated were indistinguishable. Requiring the excerpt makes the
first cost a fabricated quote, and gives the row the same kind of evidence a
byte count gives a language.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## What this plan does not do

Named here so the next plan's author does not go looking:

- **The gating rule** -- techniques printing only when matched -- belongs to plan 3. Nothing in this plan renders skills, because nothing reads `Category.SKILL` yet.
- **`ACADEMIC_PROFILE`** and the programme-page extraction are plan 2.
- **Wiring `ingest_evidence` to a view.** It still has no caller outside tests, so none of this reaches a student yet. That is separate work the spec does not cover.
