"""Read a repository's own prose and structure, in the order that survives.

The design spec ranks the signals by how reliably they describe the work, and
the ranking is measured rather than assumed:

    1. docstrings          -- prose the author wrote, next to what it describes
    2. class/function names
    3. imports parsed from source
    4. directory names
    5. notebook markdown cells
    6. commit messages
    7. README, when present
    8. requirements.txt    -- unreliable, deliberately unused

Rung 8 is the measured part, and it is narrower than it looks. The validated
repository's requirements.txt is a pip freeze of the author's entire operating
system (apturl, Brlapi, blinker, bcrypt), so Python's declared dependency file
is not read. That objection is about pip freeze, not about declared
dependencies in general: package.json's "dependencies" and Cargo.toml's
[dependencies] are hand-written lists of what a project asks for, and they are
parsed exactly (rung 3b). A language whose manifest is absent contributes no
libraries -- nothing is guessed from its prose.

Everything here is a pure function over text. No network, no Django, no
execution of what it reads -- ast.parse builds a tree and never runs it, which
is the only reason it is safe to point at a stranger's repository.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
import warnings
from dataclasses import dataclass, field
from email.parser import Parser

from defusedxml import ElementTree as DefusedElementTree

#: A file bigger than this is a data blob or a vendored bundle, not prose
#: someone wrote to explain the work. Parsing it costs more than it returns.
_MAX_FILE_CHARS = 200_000

#: Directory and filename fragments that never carry an author's description
#: of their own project.
_NOISE = (
    "/test",
    "test_",
    "/tests/",
    "/.github/",
    "/node_modules/",
    "/site-packages/",
    "/venv/",
    "/.venv/",
    "/build/",
    "/dist/",
    "/migrations/",
    "/vendor/",
    "conftest.py",
    "setup.py",
)

#: Files whose text we parse for structure. Python gets a real AST; the rest
#: get the regex tier below, which is weaker on purpose -- a wrong import name
#: costs a rejected suggestion, and a parser per language costs a parser per
#: language.
_PARSED_SUFFIXES = (
    ".py", ".ipynb",
    ".js", ".jsx", ".ts", ".tsx",
    ".r", ".R", ".jl", ".m",
    ".go", ".rs", ".java", ".kt", ".scala",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cu",
)

#: Prose the author wrote, in any language's repository. Markdown under docs/
#: is documentation wherever the code happens to be written in, which is why
#: this rung is language-neutral where the AST rung cannot be.
_PROSE_SUFFIXES = (".md", ".rst", ".txt")

@dataclass(frozen=True)
class FileSignals:
    """What one file says about the project, by rung."""

    path: str
    module_doc: str | None = None
    #: Rung 1+2 together: a name is only useful next to the prose under it.
    definitions: tuple[tuple[str, str | None], ...] = ()
    imports: tuple[str, ...] = ()
    #: Rung 5. Often the real documentation in a research repository.
    markdown: tuple[str, ...] = field(default=())


def local_module_names(paths: tuple[str, ...]) -> frozenset[str]:
    """Every name in this repository that an absolute import could resolve to.

    A flat-layout project imports its own siblings absolutely -- `import
    copasi_parser`, not `from . import copasi_parser` -- so the relative-import
    check alone lets a project's own modules through as if they were
    technologies. Measured on the validated repository, which contributed
    `apparent_activation_energy`, `auxilary_functions`, `bash_parsing`,
    `copasi_parser`, `file_operations` and `microkinetics_simulation` before
    this existed. As skills those are worse than useless.
    """
    names: set[str] = set()
    for path in paths:
        segments = path.split("/")
        names.update(segments[:-1])
        if segments[-1].endswith(".py"):
            names.add(segments[-1][:-3])
    return frozenset(names)


def _third_party(names: set[str], local: frozenset[str]) -> tuple[str, ...]:
    """Top-level imports that are neither stdlib nor this repository's own.

    A local module tells us nothing a directory listing did not; a third-party
    package names a technology the author actually used, which is the whole
    reason this rung outranks requirements.txt.
    """
    return tuple(
        sorted(
            name
            for name in names
            if name
            and not name.startswith("_")
            and name not in sys.stdlib_module_names
            and name not in local
        )
    )


def python_signals(
    path: str, text: str, *, local: frozenset[str] = frozenset()
) -> FileSignals:
    """Docstrings, public definitions and imports from one Python file.

    Never raises. A file that does not parse is a file we learn nothing from,
    which is the same outcome as a file that is not there -- and a repository
    the student did not write is entitled to contain code we cannot parse.
    """
    try:
        with warnings.catch_warnings():
            # Someone else's code is entitled to invalid escape sequences.
            # ast.parse reports them as SyntaxWarning, which is their problem
            # and would otherwise be our noise.
            warnings.simplefilter("ignore")
            tree = ast.parse(text[:_MAX_FILE_CHARS])
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return FileSignals(path=path)

    definitions: list[tuple[str, str | None]] = []
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import: a sibling module, not a technology.
            if not node.level and node.module:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_"):
                definitions.append((node.name, ast.get_docstring(node)))

    return FileSignals(
        path=path,
        module_doc=ast.get_docstring(tree),
        definitions=tuple(definitions),
        imports=_third_party(imports, local),
    )


def notebook_signals(
    path: str, text: str, *, local: frozenset[str] = frozenset()
) -> FileSignals:
    """Markdown cells and imports from one .ipynb.

    Rung 5 exists because in a research repository the markdown cells usually
    ARE the documentation -- the README is an afterthought and the prose that
    explains the work sits above the cell that does it.
    """
    try:
        document = json.loads(text[:_MAX_FILE_CHARS])
    except (ValueError, MemoryError):
        return FileSignals(path=path)
    if not isinstance(document, dict):
        return FileSignals(path=path)

    markdown: list[str] = []
    code: list[str] = []
    for cell in document.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        source = cell.get("source")
        body = "".join(source) if isinstance(source, list) else source
        if not isinstance(body, str) or not body.strip():
            continue
        if cell.get("cell_type") == "markdown":
            markdown.append(body.strip())
        elif cell.get("cell_type") == "code":
            code.append(body)

    # The concatenated code cells are parsed as one module purely to reuse the
    # import walk; a notebook that does not parse still keeps its markdown.
    imports = (
        python_signals(path, "\n".join(code), local=local).imports if code else ()
    )
    return FileSignals(path=path, imports=imports, markdown=tuple(markdown))


#: A go.mod require line: a module path followed by a version token. Narrow on
#: purpose -- this is one file whose grammar we know, not arbitrary source, and
#: the deleted regex tier failed precisely because it read arbitrary source.
_GO_REQUIRE = re.compile(
    r"^\s*(?:require\s+)?([a-z][\w.\-]*\.[a-z]{2,}[\w./\-]*)\s+v", re.MULTILINE
)

#: R DESCRIPTION fields that name packages. "R" itself is the language.
_R_DEPENDENCY_FIELDS = ("Imports", "Depends", "Suggests")


def _table_keys(document: dict[str, object], sections: tuple[str, ...]) -> tuple[str, ...]:
    """Keys of the named top-level tables. npm and Cargo differ only in those."""
    names: set[str] = set()
    for section in sections:
        table = document.get(section)
        if isinstance(table, dict):
            names.update(name for name in table if isinstance(name, str) and name)
    return tuple(sorted(names))


def _npm_manifest(text: str) -> tuple[str, ...]:
    try:
        document = json.loads(text)
    except ValueError:
        return ()
    if not isinstance(document, dict):
        return ()
    return _table_keys(document, ("dependencies", "devDependencies"))


def _cargo_manifest(text: str) -> tuple[str, ...]:
    try:
        # tomllib.loads returns a dict or raises; no isinstance needed.
        return _table_keys(tomllib.loads(text), ("dependencies", "dev-dependencies"))
    except (tomllib.TOMLDecodeError, ValueError):
        return ()


def _go_manifest(text: str) -> tuple[str, ...]:
    """A module path is named by its last segment: the name a human uses."""
    return tuple(sorted({path.split("/")[-1] for path in _GO_REQUIRE.findall(text)}))


def _pom_manifest(text: str) -> tuple[str, ...]:
    """artifactIds of <dependency> elements only.

    A pom names the project with an artifactId too, so a whole-document scan
    would report the project as its own dependency. Tags carry an XML
    namespace, hence the rpartition on "}". ParseError covers malformed XML and
    ValueError covers defusedxml's own refusals -- they share no base class,
    and refusing a stranger's entity-expanding pom is why this uses defusedxml.
    """
    try:
        root = DefusedElementTree.fromstring(text)
    except (DefusedElementTree.ParseError, ValueError):
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
    """R's DESCRIPTION is a Debian control file: RFC822 headers with
    continuation lines, which is exactly what email.parser reads. "R" is the
    language rather than a package and "(>= 4.0)" is a version bound. The shape
    guard stays because this is a stranger's file: an R package name is
    letters, digits and dots.
    """
    fields = Parser().parsestr(text[:_MAX_FILE_CHARS])
    names = {
        part.partition("(")[0].strip()
        for field in _R_DEPENDENCY_FIELDS
        for part in (fields.get(field) or "").split(",")
    }
    return tuple(
        sorted(
            name for name in names if name and name != "R" and name.replace(".", "").isalnum()
        )
    )


_MANIFEST_PARSERS = {
    "package.json": _npm_manifest,
    "Cargo.toml": _cargo_manifest,
    "go.mod": _go_manifest,
    "pom.xml": _pom_manifest,
    "DESCRIPTION": _description_manifest,
}

#: The manifests worth fetching by name. Derived from the parser table so the
#: files we ask for and the files we can read cannot drift apart. Each is a
#: hand-written statement of what a project asks for, which is what separates
#: them from a pip freeze.
MANIFEST_FILES: tuple[str, ...] = tuple(_MANIFEST_PARSERS)


def manifest_libraries(path: str, text: str) -> tuple[str, ...]:
    """Declared dependency names from one manifest, or () if it is not one.

    Never raises. A manifest we cannot parse is a manifest we learn nothing
    from, which is the same outcome as one that is not there.
    """
    parser = _MANIFEST_PARSERS.get(path.split("/")[-1])
    return parser(text[:_MAX_FILE_CHARS]) if parser is not None else ()


def prose_signals(path: str, text: str) -> FileSignals:
    """A documentation file, in any repository regardless of its language."""
    return FileSignals(path=path, markdown=(text[:_MAX_FILE_CHARS].strip(),))


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


def interesting_paths(paths: tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    """The files most likely to describe the project, shallowest first.

    Depth is the heuristic: a repository's own entry points and top-level
    modules sit near the root, while the deep files are usually one
    implementation detail each. Test and vendor paths are dropped outright --
    they describe the scaffolding, not the work.
    """
    candidates = [
        path
        for path in paths
        if path.endswith(_PARSED_SUFFIXES + _PROSE_SUFFIXES)
        and not any(fragment in f"/{path}" for fragment in _NOISE)
    ]
    candidates.sort(key=lambda path: (path.count("/"), len(path), path))
    return tuple(candidates[:limit])


def directory_names(paths: tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    """Rung 4. `GaussOutputFiles/` says what a repository is about."""
    seen = {
        segment
        for path in paths
        for segment in path.split("/")[:-1]
        if segment and not segment.startswith(".")
    }
    return tuple(sorted(seen))[:limit]
