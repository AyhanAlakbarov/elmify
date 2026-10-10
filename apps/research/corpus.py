"""The labelled CV-requirement corpus: what a programme publishes, hand-adjudicated.

Design: docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md. Two CSVs
in docs/research/ are the ground truth; this module loads and validates them and
scores a pipeline's reports against them. Nothing here fetches -- the live runner
(tests/research/test_cv_corpus.py) and the pooling command (manage.py
pool_cv_corpus) own the network.

The headline number is recall on BINDING requirements. A missed binding rule costs
a student an application; an invented one costs an edit the student can decline in
the chatbot -- so the two are reported side by side and never averaged.
"""

from __future__ import annotations

import csv
import hashlib
import pathlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from apps.documents.constraints import CONSTRAINT_KEYS, Enforcement

REPO = pathlib.Path(__file__).resolve().parents[2]
PROGRAMMES_CSV = REPO / "docs/research/cv-corpus-programmes.csv"
RULES_CSV = REPO / "docs/research/cv-corpus-rules.csv"
EVAL_CSV = REPO / "docs/research/cv-format-eval.csv"

#: The four outcomes part 3 must report per programme. `no_cv` is a real
#: answer (Chevening, GKS) and the only one the requirement layer cannot score.
OUTCOMES = frozenset({"found", "no_cv", "blocked", "not_found"})
#: Failure modes the 2026-09-15 site survey measured, not a taxonomy. A programme
#: with none is a control.
STRATA = frozenset({
    "blocked", "js_only", "in_template", "deep", "careers_decoy", "no_cv", "non_english",
})
SPLITS = frozenset({"dev", "heldout"})
STATUSES = frozenset({"accepted", "rejected", "close_call"})
ADJUDICATORS = frozenset({"claude", "owner"})
POOL_SOURCES = frozenset({"pipeline", "vendor_agent", "hand", "post_hoc"})
ENFORCEMENTS = frozenset(level.value for level in Enforcement)
#: The engine's own vocabulary plus the two Program-level things a page can set.
#: `unapplied` (in CONSTRAINT_KEYS) is the key for a requirement the vocabulary
#: cannot carry -- never invent another.
REQUIREMENT_KEYS = CONSTRAINT_KEYS | {"cv_format_requirement", "cv_directive"}

PROGRAMME_COLUMNS = (
    "id", "institution", "funder", "seed_url", "admissions_cycle", "expected_outcome",
    "strata", "split",
)
RULE_COLUMNS = (
    "programme_id", "source_url", "source_sha256", "sentence", "requirement_key",
    "requirement_value", "enforcement", "status", "adjudicated_by", "pool_source", "note",
)

#: A line is a candidate rule when it names the CV. Deliberately WIDER than
#: derive._CV_TERMS: the pool must catch what the engine's vocabulary does not
#: yet know (özgeçmiş is Turkish for CV), because a candidate nobody pooled is
#: a rule nobody can label.
CANDIDATE_TERMS = re.compile(
    r"\bcv\b|curriculum vitae|r[ée]sum[ée]|lebenslauf|europass|özgeçmiş", re.IGNORECASE
)

#: Sites the 2026-09-15 fetch survey chose partly because they were findable. With
#: the eval CSV's hosts, these may be `dev` and never `heldout` (spec, "Contamination
#: rule").
_SURVEY_HOSTS = frozenset({
    "tudelft.nl", "universiteitleiden.nl", "rhodeshouse.ox.ac.uk", "si.se", "fau.eu",
    "campusfrance.org", "universite-paris-saclay.fr", "usefnepal.org", "chevening.org",
    "aalto.fi", "studyinkorea.go.kr", "studyinjapan.go.jp", "sbfi.admin.ch",
    "turkiyeburslari.gov.tr", "sciencespo.fr", "ethz.ch", "stipendiumhungaricum.hu",
    "jasso.go.jp",
})

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CorpusError(ValueError):
    """The CSVs do not describe a corpus. Every problem found, one per line."""


@dataclass(frozen=True)
class Programme:
    id: str
    institution: str
    funder: str
    seed_url: str
    admissions_cycle: str
    expected_outcome: str
    strata: frozenset[str]
    split: str


@dataclass(frozen=True)
class Rule:
    programme_id: str
    source_url: str
    source_sha256: str
    sentence: str
    requirement_key: str
    requirement_value: str
    enforcement: str
    status: str
    adjudicated_by: str
    pool_source: str
    note: str

    @property
    def requirement(self) -> tuple[str, str]:
        """The identity two rules share when they state the same thing --
        the requirement layer, where duplicates across languages collapse."""
        return (self.requirement_key, normalize_value(self.requirement_value))


@dataclass(frozen=True)
class Corpus:
    programmes: tuple[Programme, ...]
    rules: tuple[Rule, ...]
    warnings: tuple[str, ...]

    def in_split(self, split: str) -> tuple[Programme, ...]:
        return tuple(p for p in self.programmes if p.split == split)

    def rules_for(self, programme_id: str, status: str) -> tuple[Rule, ...]:
        return tuple(
            r for r in self.rules if r.programme_id == programme_id and r.status == status
        )


def host(url: str) -> str:
    name = (urlsplit(url).hostname or "").casefold()
    return name[4:] if name.startswith("www.") else name


def normalize_url(url: str) -> str:
    """Two URLs are one page when they differ only in scheme, www, trailing slash or
    case. The query string is kept: `?page=2` is a different page."""
    parts = urlsplit(url.strip())
    query = f"?{parts.query}" if parts.query else ""
    return f"{host(url)}{parts.path.rstrip('/')}".casefold() + query


def normalize_value(value: object) -> str:
    return " ".join(str(value).split()).casefold()


def text_digest(text: str) -> str:
    """What drift is measured with: whitespace-insensitive, so a re-render that
    only re-wraps lines is not a change to the page."""
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def contaminated_hosts(eval_csv: pathlib.Path = EVAL_CSV) -> frozenset[str]:
    """Hosts that may not appear in the held-out split."""
    hosts = set(_SURVEY_HOSTS)
    with eval_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["source"].startswith("http"):
                hosts.add(host(row["source"]))
    return frozenset(hosts)


def _contaminated(name: str, contaminated: Iterable[str]) -> bool:
    return any(name == c or name.endswith("." + c) for c in contaminated)


def _read(
    path: pathlib.Path, columns: tuple[str, ...], errors: list[str]
) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            errors.append(f"{path.name}: columns are {reader.fieldnames}, expected {list(columns)}")
            return []
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _check(row: Mapping[str, str], column: str, allowed: frozenset[str], where: str,
           errors: list[str]) -> None:
    if row[column] not in allowed:
        errors.append(f"{where}: {column} {row[column]!r} not in {sorted(allowed)}")


def load_corpus(
    programmes_path: pathlib.Path = PROGRAMMES_CSV,
    rules_path: pathlib.Path = RULES_CSV,
    *,
    contaminated: frozenset[str] | None = None,
) -> Corpus:
    """Load and validate both CSVs. Raises CorpusError listing every problem;
    returns warnings (blank digests, a stratum missing from a split) on the Corpus."""
    errors: list[str] = []
    warnings: list[str] = []
    if contaminated is None:
        contaminated = contaminated_hosts()

    programmes: list[Programme] = []
    seen: set[str] = set()
    for n, row in enumerate(_read(programmes_path, PROGRAMME_COLUMNS, errors), start=2):
        where = f"programmes row {n} ({row.get('id') or '?'})"
        if not row["id"]:
            errors.append(f"{where}: id is empty")
        elif row["id"] in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(row["id"])
        if not row["seed_url"].startswith("https://"):
            errors.append(f"{where}: seed_url must be https")
        if not row["admissions_cycle"]:
            errors.append(f"{where}: admissions_cycle is empty")
        _check(row, "expected_outcome", OUTCOMES, where, errors)
        strata = frozenset(s for s in row["strata"].split(";") if s)
        if unknown := strata - STRATA:
            errors.append(f"{where}: unknown strata {sorted(unknown)}")
        _check(row, "split", SPLITS, where, errors)
        if row["split"] == "heldout" and _contaminated(host(row["seed_url"]), contaminated):
            errors.append(
                f"{where}: {host(row['seed_url'])} was in the eval set or the survey; "
                "it may not be held out"
            )
        programmes.append(Programme(
            id=row["id"], institution=row["institution"], funder=row["funder"],
            seed_url=row["seed_url"], admissions_cycle=row["admissions_cycle"],
            expected_outcome=row["expected_outcome"], strata=strata, split=row["split"],
        ))

    by_id = {p.id: p for p in programmes}
    rules: list[Rule] = []
    undigested = 0
    for n, row in enumerate(_read(rules_path, RULE_COLUMNS, errors), start=2):
        where = f"rules row {n} ({row.get('programme_id') or '?'})"
        programme = by_id.get(row["programme_id"])
        if programme is None:
            errors.append(f"{where}: unknown programme_id")
        if not row["source_url"].startswith("https://"):
            errors.append(f"{where}: source_url must be https")
        if row["source_sha256"] and not _HEX64.match(row["source_sha256"]):
            errors.append(f"{where}: source_sha256 is not 64 hex characters")
        if not row["source_sha256"]:
            undigested += 1
        if not row["sentence"]:
            errors.append(f"{where}: sentence is empty")
        if row["requirement_key"] not in REQUIREMENT_KEYS:
            errors.append(
                f"{where}: requirement_key {row['requirement_key']!r} is not in the "
                "engine's vocabulary"
            )
        _check(row, "enforcement", ENFORCEMENTS, where, errors)
        _check(row, "status", STATUSES, where, errors)
        _check(row, "adjudicated_by", ADJUDICATORS, where, errors)
        _check(row, "pool_source", POOL_SOURCES, where, errors)
        if (
            programme is not None
            and programme.split == "heldout"
            and _contaminated(host(row["source_url"]), contaminated)
        ):
            errors.append(
                f"{where}: source host was in the eval set or the survey; it may not be held out"
            )
        rules.append(Rule(**{column: row[column] for column in RULE_COLUMNS}))

    for programme_id in by_id:
        accepted = {
            r.requirement for r in rules
            if r.programme_id == programme_id and r.status == "accepted"
        }
        rejected = {
            r.requirement for r in rules
            if r.programme_id == programme_id and r.status == "rejected"
        }
        for key, value in sorted(accepted & rejected):
            errors.append(
                f"rules for {programme_id}: ({key}, {value}) is both accepted and rejected; "
                "one identity cannot be both a hit and a false positive"
            )

    if errors:
        raise CorpusError("\n".join(errors))
    if undigested:
        warnings.append(
            f"{undigested} rule(s) have no source_sha256 yet: "
            "run `manage.py pool_cv_corpus --digest`"
        )
    for split in sorted(SPLITS):
        present: set[str] = set()
        for programme in programmes:
            if programme.split == split:
                present |= programme.strata
        if missing := STRATA - present:
            warnings.append(f"{split}: no programme carries {sorted(missing)}")
    return Corpus(tuple(programmes), tuple(rules), tuple(warnings))


# --- scoring ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProgrammeReport:
    """What the pipeline reported for one programme. The runner builds one per row
    through a single injected seam, so this is the only shape the scorer knows."""

    programme_id: str
    outcome: str
    #: (source_url, sentence) -- every statement the pipeline stored.
    statements: tuple[tuple[str, str], ...]
    #: (key, value, enforcement) -- every requirement it wrote.
    requirements: tuple[tuple[str, str, str], ...]


@dataclass
class Tally:
    programmes: int = 0
    binding_hit: int = 0
    binding_total: int = 0
    hit: int = 0
    total: int = 0
    true_positive: int = 0
    false_positive: int = 0
    unjudged: int = 0
    localized: int = 0
    outcome_correct: int = 0
    drifted: int = 0

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float | None:
        """None, never 0.0, when there is nothing to divide by: a `no_cv` programme
        has no requirements, and 0/0 read as zero recall would be a wrong number."""
        return None if denominator == 0 else numerator / denominator

    @property
    def binding_recall(self) -> float | None:
        return self._ratio(self.binding_hit, self.binding_total)

    @property
    def recall(self) -> float | None:
        return self._ratio(self.hit, self.total)

    @property
    def precision(self) -> float | None:
        return self._ratio(self.true_positive, self.true_positive + self.false_positive)

    @property
    def localization(self) -> float | None:
        return self._ratio(self.localized, self.total)

    @property
    def outcome_accuracy(self) -> float | None:
        return self._ratio(self.outcome_correct, self.programmes)

    def add(self, other: Tally) -> None:
        for name in (
            "programmes",
            "binding_hit",
            "binding_total",
            "hit",
            "total",
            "true_positive",
            "false_positive",
            "unjudged",
            "localized",
            "outcome_correct",
            "drifted",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass(frozen=True)
class ScoreTable:
    #: "ALL" first, then one row per stratum when per_stratum was asked for; a
    #: programme with no stratum lands in "(control)".
    rows: Mapping[str, Tally]
    #: (programme_id, key, value) the pipeline reported that nobody has adjudicated.
    #: Spec: adjudicate and add as post_hoc, never count as wrong.
    unjudged: tuple[tuple[str, str, str], ...]


def score_programme(
    programme: Programme,
    rules: Iterable[Rule],
    report: ProgrammeReport,
    *,
    drifted: frozenset[str],
) -> tuple[Tally, list[tuple[str, str, str]]]:
    """One programme's tally. `drifted` holds normalized source URLs whose digest
    no longer matches; their rules leave the denominator rather than scoring a
    dead page as truth."""
    tally = Tally(programmes=1)
    own = [r for r in rules if r.programme_id == programme.id]
    live = [r for r in own if normalize_url(r.source_url) not in drifted]
    tally.drifted = len(own) - len(live)

    accepted = [r for r in live if r.status == "accepted"]
    wanted = {r.requirement for r in accepted}
    binding = {r.requirement for r in accepted if r.enforcement == Enforcement.BINDING}
    rejected = {r.requirement for r in live if r.status == "rejected"}
    reported = {(key, normalize_value(value)) for key, value, _ in report.requirements}

    tally.total, tally.hit = len(wanted), len(wanted & reported)
    tally.binding_total, tally.binding_hit = len(binding), len(binding & reported)
    tally.true_positive = len(reported & wanted)
    tally.false_positive = len(reported & rejected)
    unjudged = sorted(reported - wanted - rejected)
    tally.unjudged = len(unjudged)

    reached = {normalize_url(url) for url, _ in report.statements}
    for requirement in wanted:
        urls = {normalize_url(r.source_url) for r in accepted if r.requirement == requirement}
        tally.localized += int(bool(urls & reached))

    tally.outcome_correct = int(report.outcome == programme.expected_outcome)
    return tally, [(programme.id, key, value) for key, value in unjudged]


def score(
    corpus: Corpus,
    reports: Mapping[str, ProgrammeReport],
    *,
    split: str,
    drifted: frozenset[tuple[str, str]] = frozenset(),
    per_stratum: bool,
) -> ScoreTable:
    """Score every programme in `split`. `reports` must hold one per programme in
    that split (KeyError otherwise -- a missing report is a runner bug, not a miss).
    Per-stratum rows are for `dev` only: at ~2 held-out programmes per stratum the
    number would be noise dressed as diagnosis (spec, "Scoring")."""
    rows: dict[str, Tally] = {"ALL": Tally()}
    unjudged: list[tuple[str, str, str]] = []
    for programme in corpus.in_split(split):
        own_drift = frozenset(url for pid, url in drifted if pid == programme.id)
        tally, missing = score_programme(
            programme, corpus.rules, reports[programme.id], drifted=own_drift
        )
        unjudged.extend(missing)
        rows["ALL"].add(tally)
        if per_stratum:
            for stratum in sorted(programme.strata) or ["(control)"]:
                rows.setdefault(stratum, Tally()).add(tally)
    return ScoreTable(rows, tuple(unjudged))


def _cell(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def format_table(table: ScoreTable) -> str:
    """The artifact a human reads. The assertion in the runner only stops a
    regression; this is where the diagnosis is."""
    header = (
        f"{'row':<16}{'n':>4}{'bind.recall':>13}{'recall':>8}{'precision':>11}"
        f"{'localiz.':>10}{'outcome':>9}{'drift':>7}{'unjudged':>10}"
    )
    lines = [header]
    for name, t in table.rows.items():
        lines.append(
            f"{name:<16}{t.programmes:>4}{_cell(t.binding_recall):>13}{_cell(t.recall):>8}"
            f"{_cell(t.precision):>11}{_cell(t.localization):>10}"
            f"{_cell(t.outcome_accuracy):>9}{t.drifted:>7}{t.unjudged:>10}"
        )
    return "\n".join(lines)
