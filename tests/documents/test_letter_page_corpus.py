"""Live: score today's page read against the letter-rule page corpus.

`docs/research/letter-page-corpus.csv` holds one row per real programme page, each
with the letter rule a person verified on that page (or, for `hops > 0`, on the page
the rule actually lives on). This runs the production path -- the fetch engine,
`read_and_derive`, `decide_letter_shape` -- on each `page_url` and scores the shape it
writes. It is the page-level twin of `test_letter_derive.py`'s sentence-level eval:
that one hands the judge the sentence; this one makes the engine find it first.

Cost: one fetch plus three statement reads and three judge readings per page whose
text changed. Excluded from a default run by `-m 'not live'`. Run with:

    set -a; . ~/.config/elmify/openai.env; . ~/.config/elmify/anthropic.env
    . ~/.config/elmify/firecrawl.env; set +a
    uv run pytest tests/documents/test_letter_page_corpus.py -m live -s

The printed table is the artifact. Nothing is asserted until a baseline exists --
the floors are ratcheted by hand, as the CV corpus's are.
"""

from __future__ import annotations

import csv
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

_CORPUS = Path(__file__).resolve().parents[2] / "docs/research/letter-page-corpus.csv"
_LENGTH_FIELDS = ("max_words", "min_words", "max_chars", "max_pages")
_APPS = Path(__file__).resolve().parents[2] / "apps"
#: Every module a programme page passes through on its way to a letter shape.
#: Not all of apps/: the CV catalogue cites its hand-verified sources by URL and
#: the mailbox uses real domains as examples, neither of which is a special case
#: in the letter read.
_READ_PATH = (
    *(_APPS / "research").glob("fetch*.py"),
    *(_APPS / "research" / "providers").glob("*.py"),
    _APPS / "research" / "reader.py",
    _APPS / "research" / "discovery.py",
    _APPS / "documents" / "program_rules.py",
    _APPS / "documents" / "derive.py",
    *(_APPS / "documents").glob("letter_*.py"),
)


class MemoryObjectStore:
    """Copied from tests/research/test_reader.py -- not imported across modules."""

    def __init__(self) -> None:
        self.objects: list[tuple[str, bytes]] = []

    def put(self, key: str, body: bytes) -> str:
        self.objects.append((key, body))
        return f"v{len(self.objects)}"


def _flat(text: str) -> str:
    """Compare text the way a reader sees it: one space, no soft hyphens or
    thin spaces, case folded. "1 000" (French thin space) and "1 000" match."""
    text = unicodedata.normalize("NFKC", text).replace("­", "")
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass(frozen=True)
class Scored:
    row_id: str
    outcome: str  # read | blocked | failed
    quote_on_page: bool
    quote_reached_writer: bool
    required_ok: bool
    lengths: dict[str, tuple[str, str]]  # field -> (expected, got)

    def length_misses(self) -> list[str]:
        return [f for f, (want, got) in self.lengths.items() if want != got]


def _expected(row: dict[str, str], field: str) -> str:
    return row[field].strip()


def _got(prompt: object, field: str) -> str:
    value = getattr(prompt, f"letter_{field}", None)
    if value is None:
        return ""
    return str(int(value)) if float(value) == int(value) else str(value)


def _score(row: dict[str, str], *, parser: object, claude: object) -> Scored:
    from apps.documents.program_rules import read_and_derive
    from apps.funding.models import ApplicationPrompt, Institution, OfficialSource, Program
    from apps.research.egress import SourceBlocked, UnsafeTarget

    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}", name=row["institution"],
        country_code=row["country"],
        official_website=row["page_url"],
    )
    program = Program.objects.create(
        institution=institution, canonical_key=f"letter-corpus:{row['id']}:{uuid4()}",
        name=row["programme"], campus_name="Main", city="Main", country_code=row["country"],
        location_key=f"corpus:{uuid4().hex[:8]}", degree_level="MASTER",
        teaching_languages=["English"], duration_months=24,
    )
    source, _ = OfficialSource.objects.get_or_create(
        canonical_url=row["page_url"],
        defaults={"publisher": row["institution"], "source_type": OfficialSource.Type.PROGRAM},
    )
    empty = {f: (_expected(row, f), "") for f in _LENGTH_FIELDS}
    try:
        read = read_and_derive(
            program=program, source=source, store=MemoryObjectStore(), parser=parser,
            claude=claude, admissions_cycle="2027",
        )
    except (SourceBlocked, UnsafeTarget) as error:
        print(f"  {row['id']}: blocked: {type(error).__name__}: {str(error)[:160]}")
        return Scored(row["id"], "blocked", False, False, False, empty)
    except Exception as error:  # a probe reports every failure; nothing is hidden
        print(f"  {row['id']}: FAILED: {type(error).__name__}: {str(error)[:200]}")
        return Scored(row["id"], "failed", False, False, False, empty)

    quote = _flat(row["quote"])
    on_page = bool(quote) and quote in _flat(read.page_text)
    prompt = ApplicationPrompt.objects.filter(programme=program, cycle="2027").first()
    written = [] if prompt is None else list(prompt.letter_written_requirements)
    sources = {} if prompt is None else dict(prompt.letter_shape_sources)
    carried = [str(r.get("text", "")) for r in written] + [
        str(s.get("text", "")) for s in sources.values()
    ]
    reached = any(quote[:60] in _flat(text) or _flat(text) in quote for text in carried if text)
    got_required = "" if prompt is None else prompt.letter_document_required.lower()
    want_required = row["document_required"]
    required_ok = (
        got_required == want_required
        or (want_required == "unstated" and got_required in ("unstated", "required"))
    )
    lengths = {f: (_expected(row, f), _got(prompt, f)) for f in _LENGTH_FIELDS}
    return Scored(row["id"], "read", on_page, reached, required_ok, lengths)


@pytest.mark.live
@pytest.mark.django_db
def test_the_page_read_against_the_letter_corpus() -> None:
    openai = pytest.importorskip("openai")
    anthropic = pytest.importorskip("anthropic")
    rows = list(csv.DictReader(_CORPUS.open(encoding="utf-8")))
    # LETTER_CORPUS_SHARD=i/n runs every n-th row from i, so n processes (each
    # with its own POSTGRES_DB, hence its own test database) share the corpus.
    index, count = (int(x) for x in os.environ.get("LETTER_CORPUS_SHARD", "0/1").split("/"))
    rows = rows[index::count]
    parser, claude = openai.OpenAI().responses, anthropic.Anthropic().messages

    print("\nid                  outcome  on_page reached req  length misses (want->got)")
    results = []
    for row in rows:
        r = _score(row, parser=parser, claude=claude)
        results.append(r)
        # Printed as each page finishes: a run cut off by its timeout keeps
        # every row it scored (the first full run lost all of them).
        misses = ", ".join(f"{f} {r.lengths[f][0] or '-'}->{r.lengths[f][1] or '-'}"
                           for f in r.length_misses())
        print(f"{r.row_id:<19} {r.outcome:<8} {str(r.quote_on_page):<7} "
              f"{str(r.quote_reached_writer):<7} {'ok' if r.required_ok else 'NO':<4} {misses}",
              flush=True)
    by_id = {row["id"]: row for row in rows}

    read = [r for r in results if r.outcome == "read"]
    exact = [r for r in read if not r.length_misses()]
    wrong = [  # a cap we set that the page does not state, or a different number
        (r.row_id, f) for r in read for f, (want, got) in r.lengths.items() if got and got != want
    ]
    print(f"\nread {len(read)}/{len(results)}; quote on fetched page "
          f"{sum(r.quote_on_page for r in read)}/{len(read)}; rule reached writer "
          f"{sum(r.quote_reached_writer for r in read)}/{len(read)}; required correct "
          f"{sum(r.required_ok for r in read)}/{len(read)}; every length exact "
          f"{len(exact)}/{len(read)}; wrong values set: {wrong or 'none'}")
    for split in ("dev", "heldout"):
        members = [r for r in read if by_id[r.row_id]["split"] == split]
        ok = sum(1 for r in members if not r.length_misses() and r.required_ok)
        print(f"  split {split:<8} fully right {ok}/{len(members)}")
    for stratum in sorted({s for row in rows for s in row["strata"].split(";") if s}):
        members = [r for r in read if stratum in by_id[r.row_id]["strata"].split(";")]
        if members:
            ok = sum(1 for r in members if not r.length_misses() and r.required_ok)
            print(f"  {stratum:<22} {ok}/{len(members)}")


def _corpus_hosts() -> set[str]:
    hosts = set()
    for row in csv.DictReader(_CORPUS.open(encoding="utf-8")):
        for url in (row["page_url"], row["rule_url"]):
            host = urlsplit(url).hostname or ""
            if host:
                hosts.add(host.removeprefix("www."))
    return hosts


def test_no_engine_code_names_a_corpus_university() -> None:
    """The corpus measures the engine; it must never become the engine.

    A fix that special-cases one university passes that university's row and
    teaches the engine nothing (owner, 2026-09-25: "a robust and generalizable
    engine, not rules for specific universities"). This fails if any module under
    apps/ names a host the corpus scores -- the cheapest place for such a special
    case to hide. The held-out split catches the subtler kind.
    """
    hosts = _corpus_hosts()
    assert hosts
    assert all(path.exists() for path in _READ_PATH) and len(_READ_PATH) > 8
    offenders = [
        f"{path.relative_to(_APPS.parent)}: {host}"
        for path in _READ_PATH
        for host in hosts
        if host in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_corpus_is_well_formed() -> None:
    rows = list(csv.DictReader(_CORPUS.open(encoding="utf-8")))
    assert len(rows) >= 30
    assert len({row["id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["split"] in ("dev", "heldout"), row["id"]
        assert row["document_required"] in ("required", "not_required", "unstated"), row["id"]
        assert row["quote"].strip(), row["id"]
        assert len(row["country"]) == 2, row["id"]
        for field in _LENGTH_FIELDS:
            assert row[field] == "" or row[field].isdigit(), (row["id"], field)
    assert sum(row["split"] == "heldout" for row in rows) >= 0.3 * len(rows)
