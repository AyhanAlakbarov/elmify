"""Read a repository's own prose and structure, in the order that survives.

intake.repo_evidence assembles these in the spec §7.2 order, and the order
matters because the text is cut at 24,000 characters: description, code
signals, notebooks, libraries, directory names, commit messages, README-type
files (each capped after strip_markup), agent notes. A README can no longer
push everything else out.

requirements.txt is never read: the validated repository's is a pip freeze of
the author's entire operating system. package.json's "dependencies" and
Cargo.toml's [dependencies] are hand-written, and parsed exactly.

Everything here is a pure function over text. No network, no Django, no
execution of what it reads -- ast.parse builds a tree and never runs it.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.parser import Parser

import lxml.etree
import lxml.html
from defusedxml import ElementTree as DefusedElementTree

#: A file bigger than this is a data blob or a vendored bundle, not prose
#: someone wrote to explain the work. Parsing it costs more than it returns.
_MAX_FILE_CHARS = 200_000

#: Directory and filename fragments that never carry an author's description of
#: their own project. Tests are decided by _is_test, by segment.
_NOISE = (
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

#: Files whose text we parse for structure. Only Python has a parser; any other
#: suffix yields an empty FileSignals and would waste a fetch slot.
_PARSED_SUFFIXES = (".py", ".ipynb")

#: Prose the author wrote, in any language's repository. Markdown under docs/
#: is documentation wherever the code happens to be written in, which is why
#: this rung is language-neutral where the AST rung cannot be.
PROSE_SUFFIXES = (".md", ".rst", ".txt")
#: README-type files fetched by name at the root when the selection did not reach them.
README_FILES: tuple[str, ...] = ("README.md", "README.rst", "README.txt", "README")
#: Notes written for coding agents: read last, capped (spec §7.2 rung 8), never as prose.
AGENT_NOTES: tuple[str, ...] = ("CLAUDE.md", "AGENTS.md")
#: Prose files that describe the project's paperwork, not the project.
_NEVER_PROSE = ("LICENSE", "CODE_OF_CONDUCT", "CONTRIBUTING", "CITATION")
#: A .txt counts as prose only under docs/ and below this (tree size): elsewhere it is data.
_TXT_MAX_BYTES = 50_000
#: Badge hosts and paths: a README's badges say nothing about the work.
_BADGES = ("shields.io", "badge", "badgen.net", "codecov.io", "travis-ci")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]*)[^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
#: Fenced blocks and inline spans pass through strip_markup untouched: `List<int>`
#: and `#include <vector>` are code, not tags.
_CODE = re.compile(r"```.*?(?:```|\Z)|`[^`\n]+`", re.DOTALL)
_BLOCK_TAGS = frozenset(
    "p div li h1 h2 h3 h4 h5 h6 tr pre blockquote table ul ol hr details summary section".split()
)
#: Only these are HTML; any other "<word>" is prose or a type name and is kept.
_HTML_TAG = re.compile(
    r"<(?!/?(?:a|abbr|article|b|br|center|code|dd|del|details|div|dl|dt|em|figcaption|figure"
    r"|font|footer|h[1-6]|header|hr|i|iframe|img|ins|kbd|li|nav|ol|p|picture|pre|s|section"
    r"|small|source|span|strong|sub|summary|sup|table|tbody|td|th|thead|tr|u|ul|video"
    r"|script|style|blockquote)(?=[\s/>])|!--)"
)


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
    #: Text outputs of a notebook's code cells (stream, text/plain). Images are dropped.
    outputs: tuple[str, ...] = field(default=())


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


def _cell_text(value: object) -> str:
    if isinstance(value, list):
        return "".join(part for part in value if isinstance(part, str))
    return value if isinstance(value, str) else ""


def _output_text(output: object) -> str:
    """A code cell output's text, or "": an image-only output has none and is skipped."""
    if not isinstance(output, dict):
        return ""
    if output.get("output_type") == "stream":
        return _cell_text(output.get("text")).strip()
    data = output.get("data")
    return _cell_text(data.get("text/plain")).strip() if isinstance(data, dict) else ""


def notebook_signals(
    path: str, text: str, *, local: frozenset[str] = frozenset()
) -> FileSignals:
    """Markdown cells, code-cell imports and text outputs from one .ipynb.

    The WHOLE file is parsed (repo.fetch_files caps it at 5 MB); the converted
    text is shortened afterwards by intake.repo_evidence, never the JSON -- a
    cut JSON document does not parse, which is how a 241 KB notebook used to
    contribute nothing.
    """
    try:
        document = json.loads(text)
    except (ValueError, MemoryError, RecursionError):
        return FileSignals(path=path)
    if not isinstance(document, dict):
        return FileSignals(path=path)

    markdown: list[str] = []
    code: list[str] = []
    outputs: list[str] = []
    for cell in document.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        body = _cell_text(cell.get("source")).strip()
        if cell.get("cell_type") == "markdown" and body:
            markdown.append(body)
        elif cell.get("cell_type") == "code":
            if body:
                code.append(body)
            raw = cell.get("outputs")
            outputs.extend(
                found
                for item in (raw if isinstance(raw, list) else [])
                if (found := _output_text(item))
            )
    imports = (
        python_signals(path, "\n".join(code), local=local).imports if code else ()
    )
    return FileSignals(
        path=path, imports=imports, markdown=tuple(markdown), outputs=tuple(outputs)
    )


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


def _is_badge(source: str) -> bool:
    lowered = source.lower()
    return any(marker in lowered for marker in _BADGES)


def strip_markup(text: str) -> str:
    """A README as prose: HTML tags and badge images out; link text, image alt text,
    Markdown headings and list markers, and code (fenced or inline) kept (spec §7.2).
    Uses the installed lxml."""
    kept: list[str] = []
    # The placeholder's own characters, already in the input, would be mapped back as an
    # index into `kept` that does not exist.
    text = text.translate({0xE000: None, 0xE001: None})

    def park(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return f"\ue000{len(kept) - 1}\ue001"

    text = _CODE.sub(park, text)
    text = _MD_IMAGE.sub(lambda m: "" if _is_badge(m.group(2)) else m.group(1), text)
    text = _MD_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub("&lt;", text)
    if not text.strip():
        return ""
    try:
        root = lxml.html.fragment_fromstring(text, create_parent="div")
    except (lxml.etree.ParserError, ValueError):
        text = re.sub(r"<[^>]+>", "", text).strip()
    else:
        for image in root.iter("img"):
            alt = "" if _is_badge(image.get("src") or "") else (image.get("alt") or "")
            image.tail = alt + (image.tail or "")
        lxml.etree.strip_elements(
            root, "img", "script", "style", lxml.etree.Comment, with_tail=False
        )
        for element in root.iter():
            if element is root or not isinstance(element.tag, str):
                continue
            if element.tag == "br":
                element.tail = "\n" + (element.tail or "")
            elif element.tag in _BLOCK_TAGS:
                element.text = "\n" + (element.text or "")
                element.tail = "\n" + (element.tail or "")
        text = re.sub(r"\n{3,}", "\n\n", root.text_content()).strip()
    return re.sub(r"\ue000(\d+)\ue001", lambda m: kept[int(m.group(1))], text)


def file_signals(
    path: str, text: str, *, local: frozenset[str] = frozenset()
) -> FileSignals:
    if path.endswith(".ipynb"):
        return notebook_signals(path, text, local=local)
    if path.endswith(PROSE_SUFFIXES):
        return prose_signals(path, text)
    if path.endswith(".py"):
        return python_signals(path, text, local=local)
    # A language we have no parser for. Its dependencies are read from its
    # manifest by manifest_libraries, never guessed from its source.
    return FileSignals(path=path)


def _is_test(path: str) -> bool:
    """By segment: a test/tests directory, test_*, *_test.py. Not a substring --
    "latest_model.py" and "contest_solver.py" are the work."""
    *directories, name = path.split("/")
    return (
        any(directory in ("test", "tests") for directory in directories)
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _selectable(path: str, sizes: Mapping[str, int]) -> bool:
    *directories, name = path.split("/")
    if name in AGENT_NOTES:
        return False
    if name.lower().startswith("requirements") and name.endswith(".txt"):
        return False
    if path.endswith(PROSE_SUFFIXES) and name.upper().startswith(_NEVER_PROSE):
        return False
    if path.endswith(".txt"):
        size = sizes.get(path)
        return "docs" in directories and size is not None and size < _TXT_MAX_BYTES
    return path.endswith(_PARSED_SUFFIXES + PROSE_SUFFIXES)


def interesting_paths(
    paths: tuple[str, ...], *, limit: int, sizes: Mapping[str, int] | None = None
) -> tuple[str, ...]:
    """The files most likely to describe the project, shallowest first.

    `sizes` comes from the tree: a .txt is prose only under docs/ and under
    50 KB, and one whose size is unknown is treated as data.
    """
    known = sizes or {}
    candidates = [
        path
        for path in paths
        if _selectable(path, known)
        and not _is_test(path)
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
