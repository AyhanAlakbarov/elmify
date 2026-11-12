"""The research wiki's checks: dead references fail the suite, drift only reports."""

from pathlib import Path

from scripts.wiki_lint import problems, report

INDEX = "# Research wiki\n\n- [A](topics/a.md)\n"


def _tree(tmp_path: Path, files: dict[str, str]) -> tuple[Path, Path]:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (tmp_path / "wiki").mkdir(exist_ok=True)
    (tmp_path / "research").mkdir(exist_ok=True)
    return tmp_path / "wiki", tmp_path / "research"


def test_the_wiki_is_consistent() -> None:
    found = problems()
    assert not found, "\n".join(found)


def test_a_missing_source_is_a_problem(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {"wiki/index.md": INDEX, "wiki/topics/a.md": "Claim [src: gone.md §1]\n"},
    )
    assert any("topics/a.md" in p and "gone.md" in p for p in problems(*tree))


def test_a_missing_section_is_a_problem(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {
            "wiki/index.md": INDEX,
            "wiki/topics/a.md": "One [src: s.md §1] two [src: s.md §2]\n",
            "research/s.md": "# S\n\n## 1. X\n\ntext\n",
        },
    )
    found = problems(*tree)
    assert len(found) == 1
    assert "topics/a.md" in found[0] and "s.md §2" in found[0]


def test_a_citation_without_a_section_needs_only_the_file(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {
            "wiki/index.md": INDEX,
            "wiki/topics/a.md": "Claim [src: s.md]\n",
            "research/s.md": "# S\n\nno numbered headings\n",
        },
    )
    assert problems(*tree) == []


def test_only_relative_links_to_missing_files_are_problems(tmp_path: Path) -> None:
    page = (
        "Claim [src: s.md]. [q](../countries/az.md#quota) [w](https://e.x) "
        "[m](mailto:a@b) [t](#top) [n](nope.md)\n"
    )
    tree = _tree(
        tmp_path,
        {
            "wiki/index.md": INDEX + "- [AZ](countries/az.md)\n",
            "wiki/topics/a.md": page,
            "wiki/countries/az.md": "Claim [src: s.md]\n",
            "research/s.md": "# S\n",
        },
    )
    found = problems(*tree)
    assert len(found) == 1
    assert "topics/a.md" in found[0] and "nope.md" in found[0]


def test_a_page_missing_from_the_index_is_a_problem(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {
            "wiki/index.md": INDEX,
            "wiki/topics/a.md": "Claim [src: s.md]\n",
            "wiki/topics/b.md": "Claim [src: s.md]\n",
            "research/s.md": "# S\n",
        },
    )
    found = problems(*tree)
    assert len(found) == 1 and "topics/b.md" in found[0]


def test_a_content_page_with_no_citation_is_a_problem(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"wiki/index.md": INDEX, "wiki/topics/a.md": "Bare claim.\n"})
    found = problems(*tree)
    assert len(found) == 1 and "topics/a.md" in found[0]


def test_a_logged_file_that_no_longer_exists_is_a_problem(tmp_path: Path) -> None:
    log = (
        "# Wiki log\n"
        "## [2026-10-26] ingest | gone.md\n"
        "## [2026-10-26] skip | here.md | no content\n"
    )
    tree = _tree(tmp_path, {"wiki/index.md": "# W\n", "wiki/log.md": log, "research/here.md": "x"})
    found = problems(*tree)
    assert len(found) == 1 and "log.md" in found[0] and "gone.md" in found[0]


def test_report_names_unlogged_sources_only(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {
            "wiki/log.md": "## [2026-10-26] skip | b.md | not research\n",
            "research/a.md": "x",
            "research/b.md": "x",
            "research/PROMPT-x.md": "x",
            "research/folder/c.md": "x",
        },
    )
    lines = report(*tree, last_commit=lambda _p: None)
    assert [ln for ln in lines if ln.startswith("a.md")]
    assert not any(n in ln for ln in lines for n in ("b.md", "PROMPT-x.md", "c.md"))


def test_report_names_a_page_no_other_page_links_to(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {
            "wiki/index.md": INDEX,
            "wiki/topics/a.md": "Claim [src: s.md]\n",
            "wiki/topics/b.md": "Claim [src: s.md] see [a](a.md)\n",
            "research/s.md": "# S\n",
        },
    )
    lines = report(*tree, last_commit=lambda _p: None)
    assert any(ln.startswith("topics/b.md") and "orphan" in ln for ln in lines)
    assert not any(ln.startswith("topics/a.md") for ln in lines)


def test_report_names_a_stale_page_and_ignores_uncommitted_files(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {
            "wiki/index.md": INDEX,
            "wiki/topics/a.md": "Claim [src: s.md]\n",
            "research/s.md": "# S\n",
        },
    )
    stale = report(*tree, last_commit=lambda p: 100 if p.name == "a.md" else 200)
    assert any(ln.startswith("topics/a.md") and "stale" in ln for ln in stale)
    fresh = report(*tree, last_commit=lambda p: 100 if p.name == "a.md" else None)
    assert not any("stale" in ln for ln in fresh)


def test_a_malformed_citation_is_a_problem(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {
            "wiki/index.md": INDEX,
            "wiki/topics/a.md": "Good [src: s.md §1] bad [src: s.md §1, §2]\n",
            "research/s.md": "# S\n\n## 1. X\n",
        },
    )
    found = problems(*tree)
    assert len(found) == 1
    assert "topics/a.md" in found[0] and "malformed" in found[0]
