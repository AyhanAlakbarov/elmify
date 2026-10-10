"""Pool candidate sentences for the CV-requirement corpus, or fill its digests.

Two of the three passes the spec names run here: `--digest` records what each
labelled page said (Tavily Extract, whitespace-insensitive sha256) so the live
runner can tell a changed page from a missed one, and `--pass vendor` runs a
guided Tavily crawl from each programme's front page and writes every line that
names the CV to a candidates file for a human to adjudicate. The pipeline pass
is the live runner's own output (tests/research/test_cv_corpus.py prints it);
the hand pass is a person. Nothing here writes a label.

Spec: docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md.
"""

from __future__ import annotations

import csv
import pathlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.research.corpus import (
    CANDIDATE_TERMS,
    REPO,
    RULE_COLUMNS,
    RULES_CSV,
    SPLITS,
    Corpus,
    Programme,
    Rule,
    load_corpus,
    normalize_value,
    text_digest,
)
from apps.research.egress import SourceBlocked, UnsafeTarget
from apps.research.search import tavily_crawl, tavily_extract

CANDIDATES_CSV = REPO / "docs/research/cv-corpus-candidates.csv"
CANDIDATE_COLUMNS = (
    "programme_id", "source_url", "source_sha256", "heading", "sentence", "pool_source",
)
#: What the vendor crawl is told to look for. Deliberately about the DOCUMENTS
#: page, not "CV": on a university domain "CV" is the careers office.
CRAWL_INSTRUCTIONS = (
    "Find the pages that list the documents an applicant must submit with their "
    "application, and any page stating rules for the CV or curriculum vitae "
    "(format, length, template, photo, language)."
)


def fill_digests(
    rules: Sequence[Rule], extracted: Mapping[str, str]
) -> tuple[list[Rule], list[str]]:
    """Fill blank digests from `extracted` ({url: markdown}); return the rules and
    the URLs that stayed blank because Tavily could not read them."""
    filled: list[Rule] = []
    unread: list[str] = []
    for rule in rules:
        if rule.source_sha256:
            filled.append(rule)
            continue
        text = extracted.get(rule.source_url)
        if text:
            filled.append(replace(rule, source_sha256=text_digest(text)))
        else:
            filled.append(rule)
            if rule.source_url not in unread:
                unread.append(rule.source_url)
    return filled, unread


def candidates(
    programme_id: str, url: str, markdown: str, *, known: frozenset[str]
) -> list[dict[str, str]]:
    """Every line of `markdown` that names the CV, with the heading above it.

    `known` holds normalized sentences already in the rules file, so a re-run does
    not re-pool what is labelled. The heading travels with the line because the
    survey found rules as short as "- (Europass) CV" whose meaning is the heading.
    """
    digest = text_digest(markdown)
    heading = ""
    out: list[dict[str, str]] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line
            continue
        if CANDIDATE_TERMS.search(line) and normalize_value(line.lstrip("-*+ ")) not in known:
            out.append({
                "programme_id": programme_id, "source_url": url, "source_sha256": digest,
                "heading": heading, "sentence": line, "pool_source": "vendor_agent",
            })
    return out


def pooled_sentences(path: pathlib.Path) -> frozenset[str]:
    """Sentences already in the candidates file, normalized -- so a re-run of the
    vendor pass never queues the same line twice for adjudication.

    Stripped the same leading list markers ``candidates()``'s own known-check
    strips off a fresh crawl line, so a previously pooled bulleted sentence
    ("- CV") dedupes against a re-crawl of the same bulleted line -- the same
    normalizer the rules dedup uses, applied the same way.
    """
    if not path.exists() or path.stat().st_size == 0:
        return frozenset()
    with path.open(newline="", encoding="utf-8") as handle:
        return frozenset(
            normalize_value(row["sentence"].lstrip("-*+ ")) for row in csv.DictReader(handle)
        )


def write_candidates(path: pathlib.Path, rows: Iterable[Mapping[str, str]]) -> None:
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_COLUMNS, lineterminator="\n")
        if new:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_rules(path: pathlib.Path, rules: Sequence[Rule]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RULE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for rule in rules:
            writer.writerow({column: getattr(rule, column) for column in RULE_COLUMNS})


class Command(BaseCommand):
    help = "Fill source digests or pool vendor-crawl candidates for the CV-requirement corpus"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--digest", action="store_true",
                            help="fill blank source_sha256 from a fresh Tavily extract")
        parser.add_argument("--pass", dest="pass_", choices=["vendor"],
                            help="append candidate sentences from this pass to the candidates CSV")
        parser.add_argument("--split", default="dev", choices=sorted(SPLITS))
        parser.add_argument("--only", default="", help="comma-separated programme ids")

    def handle(self, *_args: object, **options: object) -> None:
        api_key = str(settings.SEARCH_API_KEY)
        if not api_key:
            raise CommandError("SEARCH_API_KEY is unset (export SEARCH_API_KEY=$TAVILY_API_KEY)")
        if not options["digest"] and not options["pass_"]:
            raise CommandError("nothing to do: pass --digest and/or --pass vendor")
        corpus = load_corpus()
        for warning in corpus.warnings:
            self.stderr.write(warning)
        only = {p for p in str(options["only"]).split(",") if p}
        chosen = [
            p for p in corpus.in_split(str(options["split"])) if not only or p.id in only
        ]
        if options["digest"]:
            self._digest(corpus, api_key, {p.id for p in chosen})
        if options["pass_"] == "vendor":
            self._vendor(corpus, api_key, chosen)

    def _digest(self, corpus: Corpus, api_key: str, programme_ids: set[str]) -> None:
        blank = sorted({
            r.source_url for r in corpus.rules
            if not r.source_sha256 and r.programme_id in programme_ids
        })
        if not blank:
            self.stdout.write("digest: nothing blank")
            return
        extracted = tavily_extract(blank, api_key=api_key)
        filled, unread = fill_digests(corpus.rules, extracted)
        # fill_digests runs over every rule so the whole file is rewritten intact,
        # but a blank row outside programme_ids was never requested -- bound the
        # reported "unread" list to what was actually asked for, or an out-of-scope
        # row is falsely reported as unreadable and the filled count goes wrong.
        requested = set(blank)
        unread = [url for url in unread if url in requested]
        _write_rules(RULES_CSV, filled)
        self.stdout.write(f"digest: filled {len(blank) - len(unread)} of {len(blank)} URLs")
        for url in unread:
            self.stderr.write(f"digest: Tavily could not read {url}")

    def _vendor(self, corpus: Corpus, api_key: str, programmes: Sequence[Programme]) -> None:
        known = frozenset(
            normalize_value(r.sentence) for r in corpus.rules
        ) | pooled_sentences(CANDIDATES_CSV)
        total = 0
        for programme in programmes:
            try:
                pages = tavily_crawl(
                    programme.seed_url, api_key=api_key, instructions=CRAWL_INSTRUCTIONS
                )
            except (SourceBlocked, UnsafeTarget) as error:
                # One slow or refusing site must not end the pass for the other 29.
                self.stderr.write(
                    f"vendor: {programme.id}: crawl failed ({type(error).__name__}: {error}) -- "
                    "run the Firecrawl /agent fallback by hand and record its use"
                )
                continue
            if not pages:
                self.stderr.write(
                    f"vendor: no crawl results for {programme.id} -- run the Firecrawl /agent "
                    "fallback by hand and record its use in the programme's note"
                )
                continue
            rows: list[dict[str, str]] = []
            for url, markdown in pages.items():
                rows.extend(candidates(programme.id, url, markdown, known=known))
            write_candidates(CANDIDATES_CSV, rows)
            total += len(rows)
            self.stdout.write(f"vendor: {programme.id}: {len(pages)} pages, {len(rows)} candidates")
        self.stdout.write(f"vendor: {total} candidates appended to {CANDIDATES_CSV.name}")
