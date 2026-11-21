"""CLAUDE.md stays an index; area guidance lives in .claude/rules/ (PR #206).

A branch cut before the split conflicts on CLAUDE.md, and taking "their" side
restores all 1,600 lines and duplicates every rules file. These checks make
that a failure instead of a silent revert.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = ROOT / "CLAUDE.md"
RULES = ROOT / ".claude/rules"
#: Anthropic's stated target for a repository CLAUDE.md is about 200 lines.
MAX_LINES = 200


def _headings(text: str) -> set[str]:
    return set(re.findall(r"(?m)^## (.+)$", text))


def test_claude_md_stays_under_its_line_budget() -> None:
    lines = len(CLAUDE_MD.read_text().splitlines())
    assert lines <= MAX_LINES, (
        f"CLAUDE.md is {lines} lines (budget {MAX_LINES}). Area guidance goes in the matching "
        ".claude/rules/<area>.md file; a merge that took the pre-split CLAUDE.md restores it."
    )


def test_no_section_lives_in_both_claude_md_and_a_rules_file() -> None:
    inline = _headings(CLAUDE_MD.read_text())
    for rules_file in RULES.glob("*.md"):
        both = inline & _headings(rules_file.read_text())
        assert not both, f"{sorted(both)} is in both CLAUDE.md and {rules_file.name}; keep one copy"


def test_every_heading_the_index_names_exists() -> None:
    index = CLAUDE_MD.read_text().split("## Area rules (`.claude/rules/`)", 1)[1]
    for name, titles in re.findall(r"- `\.claude/rules/([\w-]+\.md)`: (.+)", index):
        present = _headings((RULES / name).read_text())
        for title in re.findall(r'"([^"]+)"', titles):
            assert title in present, f"index names {title!r} but {name} has no such heading"


#: A map names a file as `path` or `path::function`, relative to one of its own
#: `paths:` globs, the repository root, or .claude/rules/.
_MAP_REF = re.compile(r"`([\w./-]+(?:\.py|\.md|\.html|/))(?:::(\w+))?`")


def test_every_file_and_function_a_map_names_exists() -> None:
    """A map that names a moved file sends Claude back to grep for it -- the cost the
    maps exist to save (2026-10-24: 62M tokens of Explore rediscovering the layout)."""
    for area_map in sorted(RULES.glob("*-map.md")):
        text = area_map.read_text()
        bases = [ROOT / glob.split("*")[0] for glob in re.findall(r'(?m)^  - "([^"]+)"$', text)]
        refs = _MAP_REF.findall(text)
        assert refs, f"{area_map.name} names no file; the pattern no longer matches its style"
        for ref, function in refs:
            hits = [base / ref for base in (*bases, ROOT, RULES) if (base / ref).exists()]
            assert hits, f"{area_map.name} names `{ref}`, which no longer exists"
            if function:
                assert re.search(rf"(?m)^(?:def|class) {function}\b", hits[0].read_text()), (
                    f"{area_map.name} names `{ref}::{function}`, but {ref} no longer defines it"
                )
