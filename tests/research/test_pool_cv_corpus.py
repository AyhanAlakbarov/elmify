"""The pooling command: digests and vendor-pass candidates for the CV corpus."""

from __future__ import annotations

import csv
import io
import pathlib

import pytest
from django.core.management.base import OutputWrapper

from apps.research.corpus import PROGRAMME_COLUMNS, RULE_COLUMNS, Rule, load_corpus, text_digest
from apps.research.egress import SourceBlocked
from apps.research.management.commands import pool_cv_corpus
from apps.research.management.commands.pool_cv_corpus import (
    CANDIDATE_COLUMNS,
    candidates,
    fill_digests,
    write_candidates,
)


def _rule(url: str, sha: str = "") -> Rule:
    return Rule(
        programme_id="p", source_url=url, source_sha256=sha, sentence="s",
        requirement_key="max_pages", requirement_value="2", enforcement="BINDING",
        status="accepted", adjudicated_by="claude", pool_source="hand", note="",
    )


def test_fill_digests_fills_only_blank_rows_and_names_what_it_could_not_read() -> None:
    rules = [_rule("https://a.example/x"), _rule("https://b.example/y"),
             _rule("https://c.example/z", sha="f" * 64)]
    extracted = {"https://a.example/x": "# A\n\nbody"}

    filled, unread = fill_digests(rules, extracted)

    assert filled[0].source_sha256 == text_digest("# A\n\nbody")
    assert filled[1].source_sha256 == ""
    assert filled[2].source_sha256 == "f" * 64  # already digested: untouched
    assert unread == ["https://b.example/y"]


def test_candidates_keep_the_heading_and_skip_sentences_already_labelled() -> None:
    markdown = (
        "# Apply\n"
        "Some intro.\n"
        "## Required documents\n"
        "- A valid passport\n"
        "- (Europass) CV\n"
        "- Your özgeçmiş, two pages at most\n"
        "## Contact\n"
        "Write to the CV office.\n"
    )
    got = candidates("p", "https://h.example/apply", markdown,
                     known=frozenset({"(europass) cv"}))

    assert [(c["heading"], c["sentence"]) for c in got] == [
        ("## Required documents", "- Your özgeçmiş, two pages at most"),
        ("## Contact", "Write to the CV office."),
    ]
    assert got[0]["programme_id"] == "p"
    assert got[0]["source_sha256"] == text_digest(markdown)
    assert got[0]["pool_source"] == "vendor_agent"


def test_write_candidates_appends_with_a_header_only_once(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "cand.csv"
    row = {"programme_id": "p", "source_url": "https://h.example", "source_sha256": "a" * 64,
           "heading": "", "sentence": "CV", "pool_source": "vendor_agent"}
    write_candidates(path, [row])
    write_candidates(path, [row])
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == list(CANDIDATE_COLUMNS)
    assert len(rows) == 3
    assert tuple(CANDIDATE_COLUMNS) == (
        "programme_id", "source_url", "source_sha256", "heading", "sentence", "pool_source"
    )
    assert set(RULE_COLUMNS) >= {"programme_id", "source_url", "source_sha256", "sentence"}


def _programme_row(pid: str, seed_url: str, split: str) -> dict[str, str]:
    return {
        "id": pid, "institution": "I", "funder": "", "seed_url": seed_url,
        "admissions_cycle": "2026/27", "expected_outcome": "found", "strata": "", "split": split,
    }


def _rule_row(pid: str, source_url: str) -> dict[str, str]:
    return {
        "programme_id": pid, "source_url": source_url, "source_sha256": "",
        "sentence": "CV required.", "requirement_key": "max_pages", "requirement_value": "2",
        "enforcement": "BINDING", "status": "accepted", "adjudicated_by": "claude",
        "pool_source": "hand", "note": "",
    }


def test_digest_scopes_the_unread_report_to_the_urls_it_actually_requested(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    programmes_path = tmp_path / "programmes.csv"
    rules_path = tmp_path / "rules.csv"
    with programmes_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROGRAMME_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(_programme_row("a", "https://a.example", "dev"))
        writer.writerow(_programme_row("b", "https://b.example", "heldout"))
    with rules_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RULE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(_rule_row("a", "https://a.example/apply"))
        writer.writerow(_rule_row("b", "https://b.example/apply"))

    corpus = load_corpus(programmes_path, rules_path, contaminated=frozenset())
    monkeypatch.setattr(pool_cv_corpus, "RULES_CSV", rules_path)

    requested: list[list[str]] = []

    def fake_extract(urls: list[str], *, api_key: str) -> dict[str, str]:
        requested.append(list(urls))
        return {url: "# page\n\ntext" for url in urls}

    monkeypatch.setattr(pool_cv_corpus, "tavily_extract", fake_extract)

    cmd = pool_cv_corpus.Command()
    cmd.stdout = OutputWrapper(io.StringIO())
    cmd.stderr = OutputWrapper(io.StringIO())

    cmd._digest(corpus, "k", {"a"})

    assert requested == [["https://a.example/apply"]]
    assert "could not read" not in cmd.stderr.getvalue()
    assert cmd.stdout.getvalue().strip() == "digest: filled 1 of 1 URLs"

    with rules_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    by_id = {row["programme_id"]: row for row in rows}
    assert by_id["a"]["source_sha256"] == text_digest("# page\n\ntext")
    assert by_id["b"]["source_sha256"] == ""


def _corpus_with_two_dev_programmes(tmp_path: pathlib.Path) -> object:
    programmes_path = tmp_path / "programmes.csv"
    rules_path = tmp_path / "rules.csv"
    with programmes_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROGRAMME_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(_programme_row("a", "https://a.example", "dev"))
        writer.writerow(_programme_row("b", "https://b.example", "dev"))
    with rules_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RULE_COLUMNS, lineterminator="\n")
        writer.writeheader()
    return load_corpus(programmes_path, rules_path, contaminated=frozenset())


def test_vendor_pass_continues_past_a_programme_whose_crawl_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _corpus_with_two_dev_programmes(tmp_path)
    candidates_path = tmp_path / "cand.csv"
    monkeypatch.setattr(pool_cv_corpus, "CANDIDATES_CSV", candidates_path)

    def fake_crawl(url: str, *, api_key: str, instructions: str) -> dict[str, str]:
        if url == "https://a.example":
            raise SourceBlocked("read timeout")
        return {"https://b.example/apply": "## Documents\n- CV"}

    monkeypatch.setattr(pool_cv_corpus, "tavily_crawl", fake_crawl)

    cmd = pool_cv_corpus.Command()
    cmd.stdout = OutputWrapper(io.StringIO())
    cmd.stderr = OutputWrapper(io.StringIO())

    cmd._vendor(corpus, "k", corpus.in_split("dev"))

    assert "vendor: a: crawl failed (SourceBlocked" in cmd.stderr.getvalue()
    assert "Firecrawl" in cmd.stderr.getvalue()
    assert "vendor: b: 1 pages, 1 candidates" in cmd.stdout.getvalue()

    with candidates_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["programme_id"] == "b"


def test_vendor_pass_does_not_requeue_a_sentence_already_in_the_candidates_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    programmes_path = tmp_path / "programmes.csv"
    rules_path = tmp_path / "rules.csv"
    with programmes_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROGRAMME_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(_programme_row("a", "https://a.example", "dev"))
    with rules_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RULE_COLUMNS, lineterminator="\n")
        writer.writeheader()
    corpus = load_corpus(programmes_path, rules_path, contaminated=frozenset())

    candidates_path = tmp_path / "cand.csv"
    with candidates_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerow({
            "programme_id": "a", "source_url": "https://a.example/apply", "source_sha256": "x",
            "heading": "", "sentence": "- CV", "pool_source": "vendor_agent",
        })
    monkeypatch.setattr(pool_cv_corpus, "CANDIDATES_CSV", candidates_path)

    def fake_crawl(url: str, *, api_key: str, instructions: str) -> dict[str, str]:
        return {"https://a.example/apply": "- CV"}

    monkeypatch.setattr(pool_cv_corpus, "tavily_crawl", fake_crawl)

    cmd = pool_cv_corpus.Command()
    cmd.stdout = OutputWrapper(io.StringIO())
    cmd.stderr = OutputWrapper(io.StringIO())

    cmd._vendor(corpus, "k", corpus.in_split("dev"))

    with candidates_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert "0 candidates" in cmd.stdout.getvalue()
