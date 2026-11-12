"""Checks for docs/wiki, the cited Markdown wiki built from docs/superpowers/research.

Run the checks:  python scripts/wiki_lint.py
Run the test:    uv run pytest tests/test_research_wiki.py

`problems()` lists dead references and fails the test; `report()` lists drift (sources not yet
logged, orphan pages, stale pages) and never fails. Nothing here calls a model or the network.
"""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "docs/wiki"
RESEARCH = ROOT / "docs/superpowers/research"

CITATION = re.compile(r"\[src: ([^\]\s§]+)(?: §(\d+))?\]")
LINK = re.compile(r"\]\(([^)\s]+)\)")
LOG_LINE = re.compile(r"(?m)^## \[\d{4}-\d{2}-\d{2}\] (?:ingest|skip) \| ([^|\n]+?)\s*(?:\||$)")
EXTERNAL = ("http://", "https://", "mailto:", "#")


def git_last_commit(path: Path) -> int | None:
    """Unix time of the last commit touching `path`; None when it has none."""
    out = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return int(out) if out else None


def _pages(wiki: Path) -> list[Path]:
    return sorted(wiki.rglob("*.md"))


def _content_pages(wiki: Path) -> list[Path]:
    return [p for p in _pages(wiki) if p.parent != wiki]


def _sources(research: Path) -> list[Path]:
    return sorted(p for p in research.glob("*.md") if not p.name.startswith("PROMPT-"))


def _relative_links(page: Path) -> list[tuple[str, Path]]:
    """(target as written, resolved file) for each relative link on the page."""
    return [
        (target, (page.parent / target.split("#")[0]).resolve())
        for target in LINK.findall(page.read_text())
        if not target.startswith(EXTERNAL)
    ]


def _has_section(source: Path, n: str) -> bool:
    return re.search(rf"(?m)^#{{2,3}} {n}\.", source.read_text()) is not None


def problems(wiki: Path = WIKI, research: Path = RESEARCH) -> list[str]:
    found: list[str] = []
    linked_from_index: set[Path] = set()
    index = wiki / "index.md"
    if index.exists():
        linked_from_index = {resolved for _, resolved in _relative_links(index)}
    for page in _pages(wiki):
        rel = page.relative_to(wiki)
        text = page.read_text()
        citations = CITATION.findall(text)
        if text.count("[src:") != len(citations):
            found.append(f"{rel}: malformed [src: ...] citation, expected [src: file.md §n]")
        for name, n in citations:
            source = research / name
            if not source.is_file():
                found.append(f"{rel}: cited source {name} does not exist")
            elif n and not _has_section(source, n):
                found.append(f"{rel}: {name} §{n} has no numbered heading {n}")
        for target, resolved in _relative_links(page):
            if not resolved.exists():
                found.append(f"{rel}: link target {target} does not exist")
        if page.parent == wiki:
            continue
        if not citations:
            found.append(f"{rel}: content page has no [src: ...] citation")
        if page.resolve() not in linked_from_index:
            found.append(f"{rel}: not linked from index.md")
    log = wiki / "log.md"
    if log.exists():
        for name in LOG_LINE.findall(log.read_text()):
            if not (research / name).is_file():
                found.append(f"log.md: logged file {name} does not exist in the research folder")
    return found


def report(
    wiki: Path = WIKI,
    research: Path = RESEARCH,
    last_commit: Callable[[Path], int | None] = git_last_commit,
) -> list[str]:
    lines: list[str] = []
    log = wiki / "log.md"
    logged = set(LOG_LINE.findall(log.read_text())) if log.exists() else set()
    lines += [f"{s.name}: not ingested" for s in _sources(research) if s.name not in logged]
    pages = _content_pages(wiki)
    linked = {
        resolved
        for page in pages
        for _, resolved in _relative_links(page)
        if resolved != page.resolve()
    }
    for page in pages:
        rel = page.relative_to(wiki)
        if page.resolve() not in linked:
            lines.append(f"{rel}: orphan, no other content page links to it")
        page_time = last_commit(page)
        if page_time is None:
            continue
        for name in sorted({n for n, _ in CITATION.findall(page.read_text())}):
            source_time = last_commit(research / name)
            if source_time is not None and source_time > page_time:
                lines.append(f"{rel}: stale, {name} changed after the page was last committed")
    return lines


def main() -> int:
    lines = problems() + report()
    print("\n".join(lines) if lines else "wiki: nothing to report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
