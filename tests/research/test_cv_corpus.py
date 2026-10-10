"""Live: score today's pipeline against the labelled CV-requirement corpus.

Spec: docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md. Costs one
Tavily extract per labelled source URL (the drift check) and one read_and_derive
per programme (three statement reads plus up to six judge calls on a page whose
text changed). Excluded from a default run by `-m 'not live'`. Run with:

    set -a; . ~/.config/tehsil_agent/openai.env; . ~/.config/tehsil_agent/anthropic.env
    . ~/.config/tehsil_agent/search.env; set +a; export SEARCH_API_KEY="$TAVILY_API_KEY"
    uv run pytest tests/research/test_cv_corpus.py -m live -s

The printed table is the artifact; the assertions only stop a regression. The
two CSV blocks at the end are the pipeline pass of the corpus pool: paste them
into docs/research/cv-corpus-candidates.csv for adjudication.
"""

from __future__ import annotations

import csv
import io

import pytest
from django.conf import settings

from apps.documents.derive import DerivationFailure
from apps.funding.models import OfficialSource, OfficialSourceSnapshot, Program
from apps.research.corpus import (
    CANDIDATE_TERMS,
    Corpus,
    Programme,
    ProgrammeReport,
    format_table,
    load_corpus,
    normalize_url,
    normalize_value,
    score,
    text_digest,
)
from apps.research.egress import OffSiteRedirect, SourceBlocked, UnsafeTarget
from apps.research.reader import ReadRateLimited, UnreadableSource
from apps.research.search import tavily_extract

#: Ratcheted BY HAND as each later part lands -- a reviewed code change on purpose.
#: 0.0 so the first run passes and records the baseline (today's pipeline reads the
#: seed page only; there is no discovery yet). Task 9 of the plan records the
#: measured baseline beside these.
BINDING_RECALL_FLOOR = 0.0
OUTCOME_ACCURACY_FLOOR = 0.0
#: Baseline measured 2026-09-16 on 30 dev programmes
#: (docs/superpowers/research/2026-09-16-cv-corpus-baseline.md):
#: binding recall 0.00, recall 0.00, precision -, localization 0.00, outcome 0.10.


class MemoryObjectStore:
    """Copied from tests/research/test_reader.py:324 -- not imported across modules."""

    def __init__(self) -> None:
        self.objects: list[tuple[str, bytes]] = []

    def put(self, key: str, body: bytes) -> str:
        self.objects.append((key, body))
        return f"v{len(self.objects)}"


def _directive_value(directive: dict[str, object]) -> str:
    """The corpus's shape for a directive: emphasise(experience),
    order(cv,reverse_chronological)."""
    inner = str(directive.get("target") or "")
    if directive.get("value"):
        inner += f",{directive['value']}"
    return f"{directive['action']}({inner})"


def _baseline(
    programme: Programme, *, program_factory, parser, claude, store,
    transport_errors: tuple[type[BaseException], ...],
) -> ProgrammeReport | None:
    """Today's pipeline, seed page only. The seam later parts replace; `None` means
    the network failed and the programme was not measured.

    The outcome is read off the ENGINE'S OWN declared state, never off a keyword
    match against the page. It used to be `found if requirements or
    CANDIDATE_TERMS.search(...)`, which made the outcome of a programme that
    states a CV rule we derived nothing from depend on whether the page was
    written in one of six European languages. A Russian page saying "резюме
    обязательно" scored differently from its English twin, and the difference
    was the measurement's, not the engine's.

    Four states, each the engine's own word for what happened:
      blocked    -- the fetch was refused
      not_found  -- nothing derived: a cache hit, a shell page, or a read error
      no_cv      -- the page was read and nothing on it looked like a CV
                    requirement (`NO_CV_FOUND`). Reachable for the first time;
                    it was structurally impossible before, so every no_cv
                    programme scored an outcome miss by construction.
      found      -- rules derived, or the page discussed the CV and stated none

    `no_cv` is a claim about our READING, not about the page: a CV requirement
    our finder could not recognise lands here too, and the corpus will score it
    as an outcome miss -- loudly, which is the point.
    """
    from apps.documents.program_rules import read_and_derive

    program = program_factory(canonical_key=f"corpus:{programme.id}", name=programme.id)
    source = OfficialSource.objects.create(
        canonical_url=programme.seed_url,
        publisher=programme.institution or programme.id,
        source_type=OfficialSource.Type.PROGRAM,
    )
    try:
        result = read_and_derive(
            program=program, source=source, store=store, parser=parser, claude=claude,
            admissions_cycle=programme.admissions_cycle,
        )
    except (SourceBlocked, UnsafeTarget):
        return ProgrammeReport(programme.id, "blocked", (), ())
    except transport_errors as error:
        # The network failed, not the pipeline. Nothing about this programme was
        # measured, so it must not be scored as any outcome -- the caller drops it.
        print(f"unmeasured: {programme.id}: {type(error).__name__}: {error}")
        return None
    except (UnreadableSource, OffSiteRedirect, ReadRateLimited, DerivationFailure) as error:
        print(f"{programme.id}: {type(error).__name__}: {error}")
        return ProgrammeReport(programme.id, "not_found", (), ())

    statements = tuple((s.snapshot.final_url, s.text) for s in result.statements)
    program.refresh_from_db()
    requirements: list[tuple[str, str, str]] = [
        (str(r["key"]), str(r["value"]), str(r["enforcement"])) for r in program.cv_constraints
    ]
    if program.cv_format_requirement != "any":
        requirements.append(
            ("cv_format_requirement", program.cv_format_requirement, "ADVISORY_HIGH_RISK")
        )
    for directive in program.cv_directives:
        requirements.append(("cv_directive", _directive_value(directive), "ADVISORY_HIGH_RISK"))
    if (
        result.snapshot is None
        or result.snapshot.readability != OfficialSourceSnapshot.Readability.OK
    ):
        # A cache hit, or a page we could not read: derivation never ran, so the stored
        # confidence is stale and says nothing about this run.
        outcome = "not_found"
    elif program.cv_format_confidence == Program.CVFormatConfidence.NO_CV_FOUND:
        outcome = "no_cv"
    elif program.cv_format_confidence == Program.CVFormatConfidence.UNVERIFIED:
        outcome = "not_found"
    else:
        outcome = "found"
    return ProgrammeReport(programme.id, outcome, statements, tuple(requirements))


def _drift(
    corpus, programme_ids: set[str], api_key: str
) -> tuple[frozenset[tuple[str, str]], list[str]]:
    """(programme_id, normalized url) for every labelled source whose digest moved,
    plus one printable line per drifted URL. Undigested rows cannot drift."""
    labelled = {
        (r.programme_id, r.source_url, r.source_sha256)
        for r in corpus.rules if r.programme_id in programme_ids and r.source_sha256
    }
    extracted = tavily_extract(sorted({url for _, url, _ in labelled}), api_key=api_key)
    drifted: set[tuple[str, str]] = set()
    lines: list[str] = []
    for programme_id, url, sha in sorted(labelled):
        now = text_digest(extracted.get(url, ""))
        if now != sha:
            drifted.add((programme_id, normalize_url(url)))
            why = "unreadable" if url not in extracted else "changed"
            lines.append(f"drift: {programme_id} {url} ({why})")
    return frozenset(drifted), lines


def _csv_block(title: str, columns: tuple[str, ...], rows) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(row)
    return f"--- {title} ---\n{out.getvalue()}"


@pytest.mark.live
@pytest.mark.django_db
@pytest.mark.parametrize("split", ["dev", pytest.param("heldout", marks=pytest.mark.skip(
    reason="held-out is scored only when a part is declared finished (spec, Scoring)"))])
def test_the_pipeline_against_the_corpus(split, program_factory):
    openai = pytest.importorskip("openai")
    anthropic = pytest.importorskip("anthropic")
    api_key = str(settings.SEARCH_API_KEY)
    if not api_key:
        pytest.skip("SEARCH_API_KEY unset: export SEARCH_API_KEY=$TAVILY_API_KEY")

    corpus = load_corpus()
    for warning in corpus.warnings:
        print(f"warning: {warning}")
    programmes = corpus.in_split(split)
    assert programmes, f"no programmes in split {split!r}"

    parser = openai.OpenAI().responses
    claude = anthropic.Anthropic().messages
    store = MemoryObjectStore()
    transport_errors: tuple[type[BaseException], ...] = (
        openai.APIConnectionError,
        anthropic.APIConnectionError,
    )
    baselines = {
        p.id: _baseline(
            p, program_factory=program_factory, parser=parser, claude=claude, store=store,
            transport_errors=transport_errors,
        )
        for p in programmes
    }
    reports = {pid: report for pid, report in baselines.items() if report is not None}
    unmeasured = sorted(pid for pid, report in baselines.items() if report is None)
    if unmeasured:
        print(f"unmeasured ({len(unmeasured)}): {', '.join(unmeasured)}")
    # A run the network mostly ate is not a baseline; fail it loudly rather than
    # print a table of three programmes as if it meant something.
    assert len(reports) >= 0.8 * len(programmes), (
        f"only {len(reports)}/{len(programmes)} programmes measured"
    )
    measured = Corpus(
        programmes=tuple(p for p in programmes if p.id in reports),
        rules=corpus.rules,
        warnings=corpus.warnings,
    )
    drifted, drift_lines = _drift(corpus, {p.id for p in measured.programmes}, api_key)
    table = score(measured, reports, split=split, drifted=drifted, per_stratum=(split == "dev"))

    print()
    print(format_table(table))
    for line in drift_lines:
        print(line)

    known = {normalize_value(r.sentence) for r in corpus.rules}
    candidates = [
        (pid, url, "", "", text, "pipeline")
        for pid, report in reports.items()
        for url, text in report.statements
        if CANDIDATE_TERMS.search(text) and normalize_value(text) not in known
    ]
    print(_csv_block(
        "candidates (pipeline pass; paste into cv-corpus-candidates.csv)",
        ("programme_id", "source_url", "source_sha256", "heading", "sentence", "pool_source"),
        candidates,
    ))
    print(_csv_block(
        "unjudged requirements (adjudicate, then add as pool_source=post_hoc)",
        ("programme_id", "requirement_key", "requirement_value"),
        table.unjudged,
    ))

    overall = table.rows["ALL"]
    if overall.binding_recall is not None:
        assert overall.binding_recall >= BINDING_RECALL_FLOOR
    assert overall.outcome_accuracy is not None
    assert overall.outcome_accuracy >= OUTCOME_ACCURACY_FLOOR
