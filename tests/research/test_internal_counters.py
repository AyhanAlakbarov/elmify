"""`SearchTap.queries_reused` is for us only (owner decision, programme-search round 2).

It counts searches the engine skipped, which says nothing a student or agency
should act on. The engine, its models, migrations and the erasure classification
may name it; any other file under apps/, config/ or templates/ (templates,
views, serializers, admin, exports, API code) may not.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "queries_reused"
SCANNED = ("apps", "config", "templates")
SUFFIXES = {".py", ".html", ".txt", ".csv", ".json", ".js", ".md", ".xml"}
ALLOWED_PREFIXES = ("apps/research/", "apps/audit/redaction.py")


def offenders(root: Path) -> list[str]:
    found = []
    for top in SCANNED:
        for path in sorted((root / top).rglob("*")):
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            if rel.startswith(ALLOWED_PREFIXES):
                continue
            if NAME in path.read_text(errors="ignore"):
                found.append(rel)
    return found


def test_queries_reused_stays_out_of_agency_facing_surfaces() -> None:
    assert offenders(ROOT) == [], (
        f"{NAME} is an internal engine counter; do not show or export it. "
        "Allowed only in apps/research/ and apps/audit/redaction.py."
    )


def test_the_scan_catches_a_template_and_a_stray_module(tmp_path: Path) -> None:
    (tmp_path / "apps/x/templates/x").mkdir(parents=True)
    (tmp_path / "apps/x/templates/x/a.html").write_text(f"{{{{ tap.{NAME} }}}}")
    (tmp_path / "apps/x/views.py").write_text(f"row = tap.{NAME}")
    (tmp_path / "apps/research").mkdir()
    (tmp_path / "apps/research/tap.py").write_text(NAME)
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates/b.html").write_text(NAME)
    want = ["apps/x/templates/x/a.html", "apps/x/views.py", "templates/b.html"]
    assert offenders(tmp_path) == want
