# CV-Requirement Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A hand-adjudicated corpus of the CV requirements 45 programmes publish, plus a scorer and a live runner that report recall on binding requirements per stratum against whatever the discovery pipeline is at the time.

**Architecture:** Two CSVs in `docs/research/` are the ground truth. `apps/research/corpus.py` loads and validates them against the engine's own vocabulary and scores `ProgrammeReport`s against them — pure Python, no network. A `live`-marked pytest runs today's pipeline through one injected seam, checks each labelled source for drift via Tavily Extract, prints the per-stratum table and asserts hand-ratcheted floors. A management command fills source digests and pools candidate sentences from a Tavily crawl for a human to adjudicate.

**Tech Stack:** Python 3.14, Django (existing models `Program`, `OfficialSource`, `ProgramStatement`), stdlib `csv`/`hashlib`, Tavily Extract + Crawl through the existing `fetch_json_api`, pytest with the repo's `live` marker.

**Spec:** `docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md`

## Global Constraints

- Work in the worktree `/home/orkhan/Desktop/tehsil_agent/.claude/worktrees/cv-corpus`, branch `claude/cv-corpus`. Never `cd` to the main checkout; it carries the owner's uncommitted work.
- Every `uv run` and `pytest` command below is run from that worktree root.
- `requirement_key` values come from the engine's vocabulary: `CONSTRAINT_KEYS` (`apps/documents/constraints.py`) plus `cv_format_requirement` and `cv_directive`. **Never invent a key**; `unapplied` is the key for a requirement the vocabulary cannot carry.
- `seed_url` is always the programme's own front page, never a documents/requirements/FAQ page.
- Hosts from `docs/research/cv-format-eval.csv` and the 2026-09-15 survey may be `dev`, never `heldout`. The loader enforces it.
- Tavily is called through `fetch_json_api` only (HTTPS, private-network block, no redirects). Never `proxy: stealth`/`enhanced`/`auto` anywhere — Tavily has no such option; the rule is recorded so nobody adds Firecrawl fetching here.
- `ruff check .`, `mypy apps config`, `bandit -c pyproject.toml -r apps config` must stay clean. Line length 100. mypy is `strict`; tests are excluded from mypy.
- Live keys: `set -a; . ~/.config/tehsil_agent/openai.env; . ~/.config/tehsil_agent/anthropic.env; . ~/.config/tehsil_agent/search.env; set +a; export SEARCH_API_KEY="$TAVILY_API_KEY"`. The repo reads Tavily's key from `settings.SEARCH_API_KEY`.
- Commit after every task with the message given. End each commit message with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- The `live` runner spends real credits (one Tavily extract per labelled URL, one `read_and_derive` per programme). Run it only in Task 9.

---

## File structure

| File | Responsibility |
|---|---|
| `apps/documents/constraints.py` (modify) | Export `CONSTRAINT_KEYS: frozenset[str]` beside the `Literal` it is built from. |
| `apps/research/search.py` (modify) | `TAVILY_EXTRACT_URL`, `tavily_extract()`, `TAVILY_CRAWL_URL`, `tavily_crawl()` — thin clients over `fetch_json_api`. |
| `apps/research/corpus.py` (create) | Dataclasses `Programme`, `Rule`, `Corpus`, `ProgrammeReport`, `Tally`, `ScoreTable`; `load_corpus()`, `score()`, `format_table()`, URL/value/digest normalizers, `CANDIDATE_TERMS`. No network, no Django models. |
| `apps/research/management/commands/pool_cv_corpus.py` (create) | `--digest` fills blank `source_sha256`; `--pass vendor` writes candidate sentences from a Tavily crawl to `docs/research/cv-corpus-candidates.csv`. |
| `docs/research/cv-corpus-programmes.csv` (create) | One row per programme. |
| `docs/research/cv-corpus-rules.csv` (create) | One row per labelled rule. |
| `tests/research/test_search_source.py` (modify) | Tests for the two Tavily clients. |
| `tests/research/test_corpus.py` (create) | Fast tests for loader, validator, scorer, and that the committed CSVs load. |
| `tests/research/test_cv_corpus.py` (create) | The `live` runner. |
| `CLAUDE.md`, `apps/documents/constraints.py`, `apps/documents/derive.py`, `tests/documents/test_derive.py` (modify) | "counsellor" → "student" correction, plus two new CLAUDE.md sections. |

---

### Task 1: Tavily Extract and Crawl clients

**Files:**
- Modify: `apps/research/search.py` (after `TAVILY_SEARCH_URL`, line 52; and append two functions at the end of the module)
- Test: `tests/research/test_search_source.py`

**Interfaces:**
- Consumes: `fetch_json_api(url, *, payload, headers, transport=...) -> dict[str, object]` from `apps/research/egress.py`.
- Produces:
  - `TAVILY_EXTRACT_URL: str`, `TAVILY_CRAWL_URL: str`
  - `tavily_extract(urls: Sequence[str], *, api_key: str, post: Callable[..., dict[str, object]] = fetch_json_api) -> dict[str, str]` — `{url_as_passed: markdown}` for every URL Tavily read; missing URLs are absent; calls are chunked 20 URLs at a time.
  - `tavily_crawl(url: str, *, api_key: str, instructions: str, limit: int = 30, post: Callable[..., dict[str, object]] = fetch_json_api) -> dict[str, str]` — `{page_url: markdown}` for every page the crawl returned.

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_search_source.py`:

```python
from apps.research.search import (
    TAVILY_CRAWL_URL,
    TAVILY_EXTRACT_URL,
    tavily_crawl,
    tavily_extract,
)


def test_extract_returns_markdown_keyed_by_the_url_that_was_asked_for() -> None:
    sent: list[dict[str, object]] = []

    def post(url, *, payload, headers):
        sent.append({"url": url, "payload": payload, "headers": headers})
        return {
            "results": [{"url": "https://x.example/apply/", "raw_content": "# Apply\n- CV"}],
            "failed_results": [{"url": "https://y.example/", "error": "403"}],
        }

    got = tavily_extract(["https://x.example/apply", "https://y.example/"], api_key="k", post=post)

    # Keyed as passed (no trailing slash) even though Tavily echoed one back.
    assert got == {"https://x.example/apply": "# Apply\n- CV"}
    assert sent == [{
        "url": TAVILY_EXTRACT_URL,
        "payload": {
            "urls": ["https://x.example/apply", "https://y.example/"],
            "extract_depth": "advanced",
            "format": "markdown",
        },
        "headers": {"Authorization": "Bearer k"},
    }]


def test_extract_chunks_twenty_urls_per_call_and_makes_no_call_for_none() -> None:
    calls: list[int] = []

    def post(url, *, payload, headers):
        calls.append(len(payload["urls"]))
        return {"results": [{"url": u, "raw_content": "x"} for u in payload["urls"]]}

    urls = [f"https://h.example/p{i}" for i in range(25)]
    assert len(tavily_extract(urls, api_key="k", post=post)) == 25
    assert calls == [20, 5]

    def never(*_a, **_k):
        raise AssertionError("no call expected for an empty list")

    assert tavily_extract([], api_key="k", post=never) == {}


def test_crawl_returns_every_page_and_sends_the_instructions() -> None:
    sent: list[dict[str, object]] = []

    def post(url, *, payload, headers):
        sent.append({"url": url, "payload": payload})
        return {"results": [
            {"url": "https://h.example/", "raw_content": "home"},
            {"url": "https://h.example/apply", "raw_content": "## Documents\n- CV"},
        ]}

    got = tavily_crawl("https://h.example", api_key="k", instructions="find the CV rules", limit=7, post=post)

    assert got == {"https://h.example/": "home", "https://h.example/apply": "## Documents\n- CV"}
    assert sent == [{
        "url": TAVILY_CRAWL_URL,
        "payload": {
            "url": "https://h.example",
            "instructions": "find the CV rules",
            "max_depth": 2,
            "limit": 7,
            "extract_depth": "advanced",
            "format": "markdown",
        },
    }]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/research/test_search_source.py -k "extract or crawl" -v`
Expected: FAIL with `ImportError: cannot import name 'TAVILY_CRAWL_URL'`.

- [ ] **Step 3: Implement the two clients**

In `apps/research/search.py`, change the `collections.abc` import to:

```python
from collections.abc import Callable, Iterator, Mapping, Sequence
```

After `TAVILY_SEARCH_URL = "https://api.tavily.com/search"` add:

```python
#: Tavily Extract and Crawl -- the fetch path for programme pages since the owner
#: decision of 2026-09-15 (docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md).
#: Same vendor and same terms as search: "Services" excludes Output, so extracted
#: text may be retained. Measured against Firecrawl /scrape on Türkiye Bursları and
#: FAU: identical requirement lines; and it reads DAAD and Sciences Po, which refuse
#: this platform's own address outright.
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
TAVILY_CRAWL_URL = "https://api.tavily.com/crawl"
#: Tavily's per-call ceiling for /extract.
_EXTRACT_BATCH = 20
```

Append at the end of the module:

```python
def _url_key(url: str) -> str:
    """Tavily echoes a URL with or without its trailing slash; match on either."""
    return url.strip().rstrip("/")


def tavily_extract(
    urls: Sequence[str],
    *,
    api_key: str,
    post: Callable[..., dict[str, object]] = fetch_json_api,
) -> dict[str, str]:
    """Return {url: markdown} for every URL Tavily could read.

    A URL Tavily could not read is simply absent -- the caller decides whether
    absence means `blocked` or `not_found`; this function does not guess. Keys
    are the URLs exactly as passed, so a caller can look its own key back up.
    """
    out: dict[str, str] = {}
    for start in range(0, len(urls), _EXTRACT_BATCH):
        batch = list(urls[start : start + _EXTRACT_BATCH])
        data: Mapping[str, Any] = post(
            TAVILY_EXTRACT_URL,
            payload={"urls": batch, "extract_depth": "advanced", "format": "markdown"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        by_key = {
            _url_key(str(item.get("url") or "")): str(item.get("raw_content") or "")
            for item in list(data.get("results") or [])
            if isinstance(item, Mapping)
        }
        for url in batch:
            text = by_key.get(_url_key(url))
            if text:
                out[url] = text
    return out


def tavily_crawl(
    url: str,
    *,
    api_key: str,
    instructions: str,
    limit: int = 30,
    post: Callable[..., dict[str, object]] = fetch_json_api,
) -> dict[str, str]:
    """Return {page_url: markdown} for every page a guided crawl of `url` returned.

    The vendor pass of the corpus pool (spec, "Building the ground truth"). Its
    output is Tavily's own extract of each page, so a sentence found here is
    already verified against the same extractor the digest uses.
    """
    data: Mapping[str, Any] = post(
        TAVILY_CRAWL_URL,
        payload={
            "url": url,
            "instructions": instructions,
            "max_depth": 2,
            "limit": limit,
            "extract_depth": "advanced",
            "format": "markdown",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return {
        str(item.get("url")): str(item.get("raw_content") or "")
        for item in list(data.get("results") or [])
        if isinstance(item, Mapping) and item.get("url")
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/research/test_search_source.py -v`
Expected: all PASS (the three new tests and every existing one).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check apps/research/search.py tests/research/test_search_source.py && uv run mypy apps/research/search.py`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add apps/research/search.py tests/research/test_search_source.py
git commit -m "$(cat <<'EOF'
research: Tavily Extract and Crawl clients

The fetch path for programme pages after the 2026-09-15 vendor decision.
Thin wrappers over fetch_json_api so the private-network block and
HTTPS-only rule apply unchanged; extract chunks at Tavily's 20-URL ceiling.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Corpus loader and validator

**Files:**
- Modify: `apps/documents/constraints.py` (import line 4; after the `_CONSTRAINT_KEYS` Literal, before `class Enforcement`)
- Create: `apps/research/corpus.py`
- Test: `tests/research/test_corpus.py`

**Interfaces:**
- Consumes: `_CONSTRAINT_KEYS` (Literal) and `Enforcement` (StrEnum: `BINDING`, `ADVISORY_HIGH_RISK`, `ADVISORY_STYLE`) from `apps/documents/constraints.py`.
- Produces:
  - `CONSTRAINT_KEYS: frozenset[str]` in `apps.documents.constraints`.
  - In `apps.research.corpus`: `Programme`, `Rule` (with `.requirement -> tuple[str, str]`), `Corpus` (with `.in_split(split)`, `.rules_for(programme_id, status)`), `CorpusError`, `load_corpus(programmes_path=PROGRAMMES_CSV, rules_path=RULES_CSV, *, contaminated=None) -> Corpus`, `contaminated_hosts(eval_csv=EVAL_CSV) -> frozenset[str]`, `host(url) -> str`, `normalize_url(url) -> str`, `normalize_value(value) -> str`, `text_digest(text) -> str`, constants `OUTCOMES`, `STRATA`, `SPLITS`, `STATUSES`, `ADJUDICATORS`, `POOL_SOURCES`, `REQUIREMENT_KEYS`, `PROGRAMME_COLUMNS`, `RULE_COLUMNS`, `PROGRAMMES_CSV`, `RULES_CSV`, `CANDIDATE_TERMS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_corpus.py`:

```python
"""The labelled CV-requirement corpus: loader, validator and scorer.

Spec: docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from apps.research.corpus import (
    PROGRAMME_COLUMNS,
    RULE_COLUMNS,
    CorpusError,
    contaminated_hosts,
    host,
    load_corpus,
    normalize_url,
    normalize_value,
    text_digest,
)

PROGRAMME_HEADER = ",".join(PROGRAMME_COLUMNS)
RULE_HEADER = ",".join(RULE_COLUMNS)

GOOD_PROGRAMME = (
    "p1,Example University,,https://example.edu,2026/27,found,deep;careers_decoy,dev"
)
GOOD_RULE = (
    "p1,https://example.edu/apply,"
    + "a" * 64
    + ',"CV: max 2 pages.",max_pages,2,BINDING,accepted,claude,hand,'
)


def _write(tmp_path: pathlib.Path, programmes: str, rules: str) -> tuple[pathlib.Path, pathlib.Path]:
    p = tmp_path / "programmes.csv"
    r = tmp_path / "rules.csv"
    p.write_text(textwrap.dedent(programmes).strip() + "\n", encoding="utf-8")
    r.write_text(textwrap.dedent(rules).strip() + "\n", encoding="utf-8")
    return p, r


def test_a_well_formed_corpus_loads_with_typed_rows(tmp_path) -> None:
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{GOOD_PROGRAMME}", f"{RULE_HEADER}\n{GOOD_RULE}")

    corpus = load_corpus(p, r, contaminated=frozenset())

    (programme,) = corpus.programmes
    assert programme.id == "p1"
    assert programme.strata == frozenset({"deep", "careers_decoy"})
    assert programme.split == "dev"
    (rule,) = corpus.rules
    assert rule.requirement == ("max_pages", "2")
    assert rule.enforcement == "BINDING"
    assert corpus.in_split("dev") == (programme,)
    assert corpus.rules_for("p1", "accepted") == (rule,)
    assert corpus.rules_for("p1", "rejected") == ()


def test_every_problem_is_reported_in_one_error(tmp_path) -> None:
    programmes = f"""
        {PROGRAMME_HEADER}
        p1,U,,http://example.edu,,maybe,deep;bogus,test
        p1,U,,https://example.edu,2026/27,found,,dev
    """
    rules = f"""
        {RULE_HEADER}
        ghost,https://example.edu/a,zz,,invented_key,2,SOFT,pending,me,guess,
    """
    p, r = _write(tmp_path, programmes, rules)

    with pytest.raises(CorpusError) as exc:
        load_corpus(p, r, contaminated=frozenset())

    message = str(exc.value)
    for fragment in (
        "seed_url must be https",
        "admissions_cycle is empty",
        "expected_outcome 'maybe'",
        "unknown strata ['bogus']",
        "split 'test'",
        "duplicate id",
        "unknown programme_id",
        "source_sha256 is not 64 hex",
        "sentence is empty",
        "requirement_key 'invented_key' is not in the engine's vocabulary",
        "enforcement 'SOFT'",
        "status 'pending'",
        "adjudicated_by 'me'",
        "pool_source 'guess'",
    ):
        assert fragment in message, fragment


def test_a_wrong_header_is_a_corpus_error(tmp_path) -> None:
    p, r = _write(tmp_path, "id,name\np1,x", f"{RULE_HEADER}")
    with pytest.raises(CorpusError, match="columns are"):
        load_corpus(p, r, contaminated=frozenset())


def test_unapplied_is_the_key_for_what_the_vocabulary_cannot_carry(tmp_path) -> None:
    rule = GOOD_RULE.replace("max_pages,2,BINDING", "unapplied,cv,ADVISORY_HIGH_RISK")
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{GOOD_PROGRAMME}", f"{RULE_HEADER}\n{rule}")
    corpus = load_corpus(p, r, contaminated=frozenset())
    assert corpus.rules[0].requirement == ("unapplied", "cv")


def test_a_contaminated_host_may_be_dev_but_never_heldout(tmp_path) -> None:
    dev = GOOD_PROGRAMME
    held = GOOD_PROGRAMME.replace("p1,", "p2,").replace(",dev", ",heldout")
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{dev}\n{held}", RULE_HEADER)

    load_corpus(p, r, contaminated=frozenset({"other.example"}))  # unrelated host: fine
    with pytest.raises(CorpusError, match="p2.*may not be held out"):
        load_corpus(p, r, contaminated=frozenset({"example.edu"}))
    # A subdomain of a contaminated host is contaminated too (static.daad.de / daad.de).
    sub = held.replace("https://example.edu", "https://static.example.edu")
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{sub}", RULE_HEADER)
    with pytest.raises(CorpusError, match="may not be held out"):
        load_corpus(p, r, contaminated=frozenset({"example.edu"}))


def test_a_blank_digest_and_a_stratum_missing_from_a_split_are_warnings(tmp_path) -> None:
    rule = GOOD_RULE.replace("a" * 64, "")
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{GOOD_PROGRAMME}", f"{RULE_HEADER}\n{rule}")
    corpus = load_corpus(p, r, contaminated=frozenset())
    assert any("no source_sha256" in w for w in corpus.warnings)
    assert any(w.startswith("heldout: no programme carries") for w in corpus.warnings)


def test_contaminated_hosts_come_from_the_eval_csv_and_the_survey(tmp_path) -> None:
    eval_csv = tmp_path / "eval.csv"
    eval_csv.write_text(
        "id,source,language,sentence,outcome,detail\n"
        "a,https://www.daad.de/en/x/,en,s,europass,\n"
        "b,synthetic,en,s,none,\n",
        encoding="utf-8",
    )
    hosts = contaminated_hosts(eval_csv)
    assert "daad.de" in hosts
    assert "synthetic" not in hosts
    assert "sciencespo.fr" in hosts  # from the survey list


def test_normalizers() -> None:
    assert host("https://WWW.Example.EDU/a") == "example.edu"
    assert normalize_url("https://www.example.edu/Apply/") == normalize_url("http://example.edu/apply")
    assert normalize_url("https://x.example/a?b=1") != normalize_url("https://x.example/a")
    assert normalize_value("  Europass_Required ") == "europass_required"
    assert text_digest("a  b\n\nc") == text_digest("a b c")
    assert len(text_digest("x")) == 64
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/research/test_corpus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.corpus'`.

- [ ] **Step 3: Export `CONSTRAINT_KEYS` from constraints.py**

In `apps/documents/constraints.py` change line 4 to:

```python
from typing import Any, Literal, get_args
```

After the closing `]` of `_CONSTRAINT_KEYS` and before `class Enforcement(StrEnum):` add:

```python
#: Every key a stored rule may carry, as a set. The corpus loader
#: (apps.research.corpus) validates labels against it, so the corpus can never
#: name a requirement the engine has no contract for.
CONSTRAINT_KEYS: frozenset[str] = frozenset(get_args(_CONSTRAINT_KEYS))
```

- [ ] **Step 4: Create `apps/research/corpus.py`**

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/research/test_corpus.py -v`
Expected: all 8 PASS.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check apps/research/corpus.py apps/documents/constraints.py tests/research/test_corpus.py && uv run mypy apps/research/corpus.py apps/documents/constraints.py`
Expected: no findings. If mypy objects to `Rule(**{...})`, replace that line with the explicit keyword form:

```python
        rules.append(Rule(
            programme_id=row["programme_id"], source_url=row["source_url"],
            source_sha256=row["source_sha256"], sentence=row["sentence"],
            requirement_key=row["requirement_key"], requirement_value=row["requirement_value"],
            enforcement=row["enforcement"], status=row["status"],
            adjudicated_by=row["adjudicated_by"], pool_source=row["pool_source"],
            note=row["note"],
        ))
```

- [ ] **Step 7: Commit**

```bash
git add apps/research/corpus.py apps/documents/constraints.py tests/research/test_corpus.py
git commit -m "$(cat <<'EOF'
research: corpus loader validates labels against the engine's own vocabulary

Two CSVs are the ground truth for CV-requirement discovery. The loader
refuses any requirement key the engine has no contract for, any held-out
programme on a host the eval set or the survey already touched, and lists
every problem at once. Blank digests and thin strata are warnings.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Scorer

**Files:**
- Modify: `apps/research/corpus.py` (append)
- Test: `tests/research/test_corpus.py` (append)

**Interfaces:**
- Consumes: `Programme`, `Rule`, `Corpus`, `normalize_url`, `normalize_value`, `Enforcement` from Task 2.
- Produces:
  - `ProgrammeReport(programme_id: str, outcome: str, statements: tuple[tuple[str, str], ...], requirements: tuple[tuple[str, str, str], ...])` — `statements` are `(source_url, sentence)`, `requirements` are `(key, value, enforcement)`.
  - `Tally` (mutable dataclass) with counters and properties `binding_recall`, `recall`, `precision`, `localization`, `outcome_accuracy` (each `float | None`), and `.add(other)`.
  - `ScoreTable(rows: Mapping[str, Tally], unjudged: tuple[tuple[str, str, str], ...])` — rows keyed `"ALL"` then stratum names (or `"(control)"`).
  - `score(corpus, reports, *, split, drifted=frozenset(), per_stratum) -> ScoreTable` where `drifted` is a `frozenset[tuple[str, str]]` of `(programme_id, normalize_url(source_url))`.
  - `format_table(table) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_corpus.py`:

```python
from apps.research.corpus import (  # noqa: E402
    Corpus,
    Programme,
    ProgrammeReport,
    Rule,
    format_table,
    normalize_url,
    score,
)


def _programme(pid: str, *, expected: str = "found", strata: str = "", split: str = "dev"):
    return Programme(
        id=pid, institution="U", funder="", seed_url=f"https://{pid}.example",
        admissions_cycle="2026/27", expected_outcome=expected,
        strata=frozenset(s for s in strata.split(";") if s), split=split,
    )


def _rule(pid: str, key: str, value: str, *, enforcement: str = "BINDING",
          status: str = "accepted", url: str | None = None, sentence: str = "s"):
    return Rule(
        programme_id=pid, source_url=url or f"https://{pid}.example/apply", source_sha256="",
        sentence=sentence, requirement_key=key, requirement_value=value,
        enforcement=enforcement, status=status, adjudicated_by="claude", pool_source="hand",
        note="",
    )


def _report(pid: str, *requirements: tuple[str, str], outcome: str = "found",
            statements: tuple[tuple[str, str], ...] = ()):
    return ProgrammeReport(
        programme_id=pid, outcome=outcome, statements=statements,
        requirements=tuple((k, v, "BINDING") for k, v in requirements),
    )


def test_binding_recall_is_scored_apart_from_advisory_recall() -> None:
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(
            _rule("p", "max_pages", "2"),
            _rule("p", "cv_format_requirement", "europass_required"),
            _rule("p", "cv_directive", "emphasise(experience)", enforcement="ADVISORY_HIGH_RISK"),
        ),
        warnings=(),
    )
    reports = {"p": _report("p", ("max_pages", "2"))}

    table = score(corpus, reports, split="dev", per_stratum=False)

    tally = table.rows["ALL"]
    assert (tally.binding_hit, tally.binding_total) == (1, 2)
    assert tally.binding_recall == 0.5
    assert (tally.hit, tally.total) == (1, 3)
    assert tally.precision == 1.0
    assert tally.unjudged == 0


def test_precision_counts_rejected_rules_as_false_positives_and_lists_the_unjudged() -> None:
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(
            _rule("p", "max_pages", "2"),
            _rule("p", "photo_allowed", "false", status="rejected"),
        ),
        warnings=(),
    )
    reports = {"p": _report("p", ("max_pages", "2"), ("photo_allowed", "False"),
                            ("language", "de"))}

    table = score(corpus, reports, split="dev", per_stratum=False)

    tally = table.rows["ALL"]
    assert (tally.true_positive, tally.false_positive, tally.unjudged) == (1, 1, 1)
    assert tally.precision == 0.5
    # Never counted wrong: handed back for adjudication as post_hoc.
    assert table.unjudged == (("p", "language", "de"),)


def test_two_sentences_one_requirement_collapse_and_either_url_localizes() -> None:
    en = "https://p.example/en/apply"
    fr = "https://p.example/fr/candidater"
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(
            _rule("p", "max_pages", "2", url=en, sentence="max 2 pages"),
            _rule("p", "max_pages", "2", url=fr, sentence="2 pages maximum"),
        ),
        warnings=(),
    )
    reports = {"p": _report("p", ("max_pages", "2"),
                            statements=(("http://www.p.example/fr/candidater/", "2 pages maximum"),))}

    tally = score(corpus, reports, split="dev", per_stratum=False).rows["ALL"]

    assert tally.total == 1 and tally.hit == 1
    assert tally.localization == 1.0


def test_localization_is_zero_when_the_right_answer_came_from_the_wrong_page() -> None:
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(_rule("p", "max_pages", "2", url="https://p.example/admissions"),),
        warnings=(),
    )
    reports = {"p": _report("p", ("max_pages", "2"),
                            statements=(("https://p.example/careers/how-to-write-a-cv", "2 pages"),))}
    tally = score(corpus, reports, split="dev", per_stratum=False).rows["ALL"]
    assert tally.recall == 1.0 and tally.localization == 0.0


def test_a_no_cv_programme_is_scored_on_its_outcome_only() -> None:
    corpus = Corpus(programmes=(_programme("p", expected="no_cv", strata="no_cv"),),
                    rules=(), warnings=())
    right = score(corpus, {"p": _report("p", outcome="no_cv")}, split="dev", per_stratum=True)
    wrong = score(corpus, {"p": _report("p", outcome="not_found")}, split="dev", per_stratum=True)

    assert right.rows["ALL"].outcome_accuracy == 1.0
    assert wrong.rows["ALL"].outcome_accuracy == 0.0
    assert right.rows["ALL"].recall is None  # no denominator, not a zero
    assert right.rows["no_cv"].programmes == 1


def test_per_stratum_rows_are_only_built_when_asked_and_a_control_row_collects_the_rest() -> None:
    corpus = Corpus(
        programmes=(_programme("a", strata="deep;blocked"), _programme("b")),
        rules=(_rule("a", "max_pages", "2"), _rule("b", "max_pages", "1")),
        warnings=(),
    )
    reports = {"a": _report("a", ("max_pages", "2")), "b": _report("b")}

    flat = score(corpus, reports, split="dev", per_stratum=False)
    assert set(flat.rows) == {"ALL"}

    table = score(corpus, reports, split="dev", per_stratum=True)
    assert set(table.rows) == {"ALL", "deep", "blocked", "(control)"}
    assert table.rows["deep"].binding_recall == 1.0
    assert table.rows["(control)"].binding_recall == 0.0
    assert table.rows["ALL"].programmes == 2


def test_only_the_requested_split_is_scored() -> None:
    corpus = Corpus(programmes=(_programme("d"), _programme("h", split="heldout")),
                    rules=(), warnings=())
    table = score(corpus, {"d": _report("d")}, split="dev", per_stratum=False)
    assert table.rows["ALL"].programmes == 1  # "h" was neither required nor scored


def test_a_drifted_source_is_excluded_from_the_denominator_and_counted() -> None:
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(_rule("p", "max_pages", "2", url="https://p.example/moved"),
               _rule("p", "language", "en", url="https://p.example/still")),
        warnings=(),
    )
    drifted = frozenset({("p", normalize_url("https://p.example/moved"))})
    tally = score(corpus, {"p": _report("p", ("language", "en"))}, split="dev",
                  drifted=drifted, per_stratum=False).rows["ALL"]
    assert tally.total == 1 and tally.recall == 1.0
    assert tally.drifted == 1


def test_format_table_prints_a_dash_for_an_undefined_ratio() -> None:
    corpus = Corpus(programmes=(_programme("p", expected="no_cv"),), rules=(), warnings=())
    text = format_table(score(corpus, {"p": _report("p", outcome="no_cv")}, split="dev",
                              per_stratum=False))
    header, row = text.strip().splitlines()
    assert header.split()[:3] == ["row", "n", "bind.recall"]
    assert row.split()[:4] == ["ALL", "1", "-", "-"]
    assert row.split()[6] == "1.00"  # outcome accuracy
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/research/test_corpus.py -k "recall or precision or localiz or no_cv or stratum or split or drift or format" -v`
Expected: FAIL with `ImportError: cannot import name 'ProgrammeReport'`.

- [ ] **Step 3: Append the scorer to `apps/research/corpus.py`**

```python


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
            "programmes", "binding_hit", "binding_total", "hit", "total", "true_positive",
            "false_positive", "unjudged", "localized", "outcome_correct", "drifted",
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/research/test_corpus.py -v`
Expected: all PASS (8 from Task 2 plus 10 new).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check apps/research/corpus.py tests/research/test_corpus.py && uv run mypy apps/research/corpus.py`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add apps/research/corpus.py tests/research/test_corpus.py
git commit -m "$(cat <<'EOF'
research: corpus scorer -- binding recall first, localization apart, per stratum

Recall on BINDING requirements is the headline because a missed binding rule
costs a student an application. Localization is scored on the sentence layer
so a discovery miss and a derivation miss are told apart; an unjudged report
is handed back for adjudication, never counted wrong; a drifted source leaves
the denominator; a ratio with no denominator prints as "-", not 0.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Seed the two CSVs and pin that they load

**Files:**
- Create: `docs/research/cv-corpus-programmes.csv`
- Create: `docs/research/cv-corpus-rules.csv`
- Modify: `docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md` (one sentence)
- Test: `tests/research/test_corpus.py` (append)

**Interfaces:**
- Consumes: `load_corpus()` defaults from Task 2.
- Produces: 18 `dev` programme rows and 17 adjudicated rule rows, every one traceable to a sentence measured in this repo (`cv-format-eval.csv`, the 2026-09-15 survey, CLAUDE.md).

- [ ] **Step 1: Write the failing test**

Append to `tests/research/test_corpus.py`:

```python
def test_the_committed_corpus_loads(capsys) -> None:
    """The one fast guard on the real files: any row that breaks the contract
    breaks the default suite, not the next live run."""
    corpus = load_corpus()
    assert len(corpus.programmes) >= 18
    assert len(corpus.rules) >= 17
    assert {p.split for p in corpus.programmes} <= {"dev", "heldout"}
    for warning in corpus.warnings:
        print(warning)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/research/test_corpus.py::test_the_committed_corpus_loads -v`
Expected: FAIL with `FileNotFoundError` on `cv-corpus-programmes.csv`.

- [ ] **Step 3: Create `docs/research/cv-corpus-programmes.csv`**

Every seed is a site this session gave to a vendor map call and got results from, or a URL CLAUDE.md records; every seed is the programme's front page, never its documents page.

```csv
id,institution,funder,seed_url,admissions_cycle,expected_outcome,strata,split
mathmods,"MathMods (Università degli Studi dell'Aquila)",Erasmus Mundus,https://www.mathmods.eu,2026/27,found,,dev
emship,EMship+,Erasmus Mundus,https://emship.eu,2026/27,found,,dev
globed,GLOBED,Erasmus Mundus,https://globed.eu,2026/27,found,,dev
i-mesc,i-MESC,Erasmus Mundus,https://i-mesc.eu,2026/27,found,,dev
europubhealth,Europubhealth+,Erasmus Mundus,https://www.europubhealth.org,2026/27,found,,dev
amir,AMIR,Erasmus Mundus,https://www.amir-em-master.com,2026/27,found,,dev
emhrpp,EMHRPP,Erasmus Mundus,https://www.emhrpp.com,2026/27,found,,dev
emjm-imaging,EMJM IMAGING,Erasmus Mundus,https://www.emjm-imaging.eu,2026/27,found,deep,dev
we-team,WE-TEAM,Erasmus Mundus,https://we-team.education,2026/27,found,deep,dev
membiomed,"MemBioMed (Université Côte d'Azur)",Erasmus Mundus,https://life.univ-cotedazur.eu/international/membiomed,2026/27,found,deep,dev
daad-prime,DAAD PRIME,DAAD,https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programmes/prime/,2026/27,found,blocked;deep,dev
fau-ai-msc,"FAU Erlangen-Nürnberg, M.Sc. Artificial Intelligence",,https://ai.study.fau.eu/,2026/27,found,,dev
turkiye-burslari,Türkiye Bursları,Türkiye Bursları,https://www.turkiyeburslari.gov.tr,2026/27,no_cv,js_only;no_cv,dev
sciencespo-graduate,"Sciences Po, graduate admissions",,https://www.sciencespo.fr/admissions/en/graduate/,2026/27,found,blocked;careers_decoy,dev
ethz-master,"ETH Zürich, Master's programmes",,https://ethz.ch/en/studies/master.html,2026/27,found,deep,dev
stipendium-hungaricum,Stipendium Hungaricum,Tempus Public Foundation,https://stipendiumhungaricum.hu,2026/27,found,in_template;deep,dev
tudelft-master,"TU Delft, MSc programmes",,https://www.tudelft.nl/en/education/programmes/masters,2026/27,found,careers_decoy;deep,dev
leiden-master,"Leiden University, Master's programmes",,https://www.universiteitleiden.nl/en/education/study-programmes/master,2026/27,found,careers_decoy;deep,dev
```

- [ ] **Step 4: Verify every seed answers**

DAAD and Sciences Po refuse this network's address (measured; do not retry them here — Task 9's digest run reads them through Tavily). Every other seed must return 200 or a redirect to 200:

```bash
tail -n +2 docs/research/cv-corpus-programmes.csv | python3 -c "
import csv,sys
for row in csv.reader(sys.stdin):
    if 'daad.de' in row[3] or 'sciencespo.fr' in row[3]: continue
    print(row[3])
" | while read -r u; do printf '%s ' "$(curl -s -o /dev/null -L --max-time 25 -w '%{http_code}' "$u")"; echo "$u"; done
```

Expected: every line begins `200`. A `404` means the front page moved: find the current one from the host's root (`curl -sL "https://<host>/" | grep -oi 'href="[^"]*master[^"]*"' | head`), replace the URL, and note the change in the commit message. A `403`/`000` on a host other than the two named is a new blocked site: add `blocked` to its strata and leave the URL.

- [ ] **Step 5: Create `docs/research/cv-corpus-rules.csv`**

Each row is one sentence a page actually prints (the eval CSV's real rows, split into single sentences where it stored a whole FAQ answer), adjudicated by Claude with the reason in `note`. `source_sha256` is blank until Task 9's `--digest` run. Every `cv_directive` value uses the engine's own shape: `include(<field>)`, `order(<section>,<direction>)`, `emphasise(<section>)`.

```csv
programme_id,source_url,source_sha256,sentence,requirement_key,requirement_value,enforcement,status,adjudicated_by,pool_source,note
daad-prime,https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programmes/prime/faq/,,We recommend using the template provided by europass to make sure that your CV will meet the requirements.,cv_format_requirement,europass_preferred,ADVISORY_HIGH_RISK,accepted,claude,hand,"""recommend"" is a preference, not a mandate"
daad-prime,https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programmes/prime/faq/,,Please ensure that your CV does not contain any chronological gaps.,no_unexplained_gaps,0,BINDING,accepted,claude,hand,DAAD treats a missing period as grounds for exclusion (constraints.py)
daad-prime,https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programmes/prime/faq/,,The curriculum vitae should be prepared in a tabular form in accordance with EU standards.,unapplied,cv,ADVISORY_HIGH_RISK,accepted,claude,hand,tabular layout: no key carries it (eval d3)
amir,https://www.amir-em-master.com/admission/required-documentation-for-all-applications/,,CV in the Europass CV template,cv_format_requirement,europass_required,BINDING,accepted,claude,hand,
membiomed,https://life.univ-cotedazur.eu/international/membiomed/how-to-apply,,"CV : Europass format mandatory. Include details on age, academic records and quality/recognition of the institution having awarded the bachelor or equivalent degree.",cv_format_requirement,europass_required,BINDING,accepted,claude,hand,"""mandatory"""
membiomed,https://life.univ-cotedazur.eu/international/membiomed/how-to-apply,,"CV : Europass format mandatory. Include details on age, academic records and quality/recognition of the institution having awarded the bachelor or equivalent degree.",cv_directive,include(personal.date_of_birth),ADVISORY_HIGH_RISK,accepted,claude,hand,"""details on age"" -- the ledger field that carries age"
membiomed,https://life.univ-cotedazur.eu/international/membiomed/how-to-apply,,"CV : Europass format mandatory. Include details on age, academic records and quality/recognition of the institution having awarded the bachelor or equivalent degree.",unapplied,cv,ADVISORY_HIGH_RISK,accepted,claude,hand,institution recognition: no field carries it (eval d2)
globed,https://globed.eu/how-to-apply/,,Upload your up-to-date Europass CV. Resumes in other formats won’t be accepted.,cv_format_requirement,europass_required,BINDING,accepted,claude,hand,
i-mesc,https://i-mesc.eu/application/student,,Please use the Europass model.,cv_format_requirement,europass_required,BINDING,accepted,claude,hand,polite imperative; still a mandate
mathmods,https://www.mathmods.eu/apply,,CV (use the Europass template available here: https://europa.eu/europass/en);,cv_format_requirement,europass_required,BINDING,accepted,claude,hand,
we-team,https://we-team.education/faq/12-are-there-specific-guidelines-for-preparing-my-cv-for-the-erasmus-mundus-application/,,The CV should be Europass format.,cv_format_requirement,europass_required,BINDING,accepted,claude,hand,
we-team,https://we-team.education/faq/12-are-there-specific-guidelines-for-preparing-my-cv-for-the-erasmus-mundus-application/,,The CV should highlight your academic and professional experiences.,cv_directive,emphasise(experience),ADVISORY_HIGH_RISK,accepted,claude,hand,eval d5
europubhealth,https://www.europubhealth.org/admission-requirements/,,Curriculum Vitae (Europass format preferred).,cv_format_requirement,europass_preferred,ADVISORY_HIGH_RISK,accepted,claude,hand,
emship,https://emship.eu/how-to-apply/,,(Europass) CV,cv_format_requirement,europass_required,BINDING,accepted,claude,hand,a 13-character bullet under a Documents heading; the heading carries the meaning
emhrpp,https://www.emhrpp.com/how-to-apply,,"Yes, any CV format is accepted.",cv_format_requirement,any,ADVISORY_STYLE,accepted,claude,hand,states the ABSENCE of a format rule; a pipeline writing europass here is a false positive
emjm-imaging,https://www.emjm-imaging.eu/application-and-admission/questions-and-answers/,,The only requirement for CV is the 2-page limit. You may use Europass or any other CV template which you find suitable.,max_pages,2,BINDING,accepted,claude,hand,
emjm-imaging,https://www.emjm-imaging.eu/application-and-admission/questions-and-answers/,,The only requirement for CV is the 2-page limit. You may use Europass or any other CV template which you find suitable.,cv_format_requirement,any,ADVISORY_STYLE,accepted,claude,hand,
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/research/test_corpus.py -v -s`
Expected: all PASS. The printed warnings are exactly three lines: `17 rule(s) have no source_sha256 yet ...`, `dev: no programme carries ['non_english']`, and `heldout: no programme carries [...]` (the held-out split is empty until Task 8, which also fills `non_english`).

- [ ] **Step 7: Amend the spec's strata sentence**

In `docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md` replace:

```
Every programme carries one or more flags. `careers_decoy` and `no_cv` are the two that no
```

with:

```
Every programme carries zero or more flags; one with none is a control, so the pipeline's
score on an ordinary site is visible beside its score on the hard ones. `careers_decoy` and
`no_cv` are the two that no
```

- [ ] **Step 8: Commit**

```bash
git add docs/research/cv-corpus-programmes.csv docs/research/cv-corpus-rules.csv tests/research/test_corpus.py docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md
git commit -m "$(cat <<'EOF'
research: seed the CV-requirement corpus with the 18 measured dev programmes

Eighteen programmes whose rule pages this repo has already measured, and the
seventeen sentences from cv-format-eval.csv split into single requirements
and adjudicated. Every seed is the programme's front page. Digests are blank
until the first pooling run; the held-out split is empty until Task 8.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `pool_cv_corpus` management command

**Files:**
- Create: `apps/research/management/commands/pool_cv_corpus.py`
- Test: `tests/research/test_pool_cv_corpus.py`

**Interfaces:**
- Consumes: `load_corpus`, `Corpus`, `Rule`, `RULE_COLUMNS`, `RULES_CSV`, `text_digest`, `CANDIDATE_TERMS`, `SPLITS` (Task 2); `tavily_extract`, `tavily_crawl` (Task 1); `settings.SEARCH_API_KEY`.
- Produces:
  - `manage.py pool_cv_corpus --digest [--split dev] [--only a,b]` — rewrites the rules CSV with `source_sha256` filled for every blank row whose URL Tavily read; prints the URLs it could not.
  - `manage.py pool_cv_corpus --pass vendor [--split dev] [--only a,b]` — appends candidate rows to `docs/research/cv-corpus-candidates.csv` with columns `programme_id,source_url,source_sha256,heading,sentence,pool_source`, skipping sentences already labelled; prints programmes whose crawl returned nothing.
  - Module-level pure helpers used by the tests: `candidates(programme_id, url, markdown, *, known: frozenset[str]) -> list[dict[str, str]]` and `fill_digests(rules, extracted) -> tuple[list[Rule], list[str]]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_pool_cv_corpus.py`:

```python
"""The pooling command: digests and vendor-pass candidates for the CV corpus."""

from __future__ import annotations

import csv
import pathlib

from apps.research.corpus import RULE_COLUMNS, Rule, text_digest
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/research/test_pool_cv_corpus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.management.commands.pool_cv_corpus'`.

- [ ] **Step 3: Create the command**

`apps/research/management/commands/pool_cv_corpus.py`:

```python
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
        if CANDIDATE_TERMS.search(line) and normalize_value(line) not in known:
            out.append({
                "programme_id": programme_id, "source_url": url, "source_sha256": digest,
                "heading": heading, "sentence": line, "pool_source": "vendor_agent",
            })
    return out


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
        _write_rules(RULES_CSV, filled)
        self.stdout.write(f"digest: filled {len(blank) - len(unread)} of {len(blank)} URLs")
        for url in unread:
            self.stderr.write(f"digest: Tavily could not read {url}")

    def _vendor(self, corpus: Corpus, api_key: str, programmes: Sequence[Programme]) -> None:
        known = frozenset(normalize_value(r.sentence) for r in corpus.rules)
        total = 0
        for programme in programmes:
            pages = tavily_crawl(
                programme.seed_url, api_key=api_key, instructions=CRAWL_INSTRUCTIONS
            )
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/research/test_pool_cv_corpus.py -v`
Expected: all 3 PASS.

- [ ] **Step 5: Check the command parses and refuses without a key**

Run: `SEARCH_API_KEY= uv run python manage.py pool_cv_corpus --digest; echo "exit=$?"`
Expected: `CommandError: SEARCH_API_KEY is unset ...` and `exit=1`.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check apps/research/management/commands/pool_cv_corpus.py tests/research/test_pool_cv_corpus.py && uv run mypy apps/research/management/commands/pool_cv_corpus.py && uv run bandit -q -c pyproject.toml -r apps/research`
Expected: no findings.

- [ ] **Step 7: Add the candidates file to `.gitignore`? No.**

The candidates file is committed on purpose: it is the adjudication queue and the record of what each pooling run surfaced. Do nothing here; Task 9 commits it.

- [ ] **Step 8: Commit**

```bash
git add apps/research/management/commands/pool_cv_corpus.py tests/research/test_pool_cv_corpus.py
git commit -m "$(cat <<'EOF'
research: pool_cv_corpus fills source digests and pools vendor-crawl candidates

--digest records what each labelled page said so the runner can tell a
changed page from a missed one. --pass vendor runs a guided Tavily crawl
from each front page and writes every CV-naming line, with its heading, to
the candidates file for a human to adjudicate. Nothing here writes a label.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The live runner

**Files:**
- Create: `tests/research/test_cv_corpus.py`

**Interfaces:**
- Consumes: `load_corpus`, `score`, `format_table`, `ProgrammeReport`, `Programme`, `normalize_url`, `normalize_value`, `text_digest`, `CANDIDATE_TERMS` (Tasks 2-3); `tavily_extract` (Task 1); `read_and_derive` (`apps/documents/program_rules.py`), `program_factory` fixture (`tests/conftest.py`), `OfficialSource`/`ProgramStatement` (`apps/funding/models.py`), `SourceBlocked`/`UnsafeTarget`/`OffSiteRedirect` (`apps/research/egress.py`), `UnreadableSource`/`ReadRateLimited` (`apps/research/reader.py`), `DerivationFailure` (`apps/documents/derive.py`).
- Produces: one `live` test per split (`dev` now; `heldout` parametrized but skipped until a part is declared finished), `BINDING_RECALL_FLOOR` and `OUTCOME_ACCURACY_FLOOR` constants, and a printed report with four blocks: warnings, the table, drift, and two CSV blocks (`candidates` from pipeline statements, `unjudged` requirements).

- [ ] **Step 1: Write the runner**

Create `tests/research/test_cv_corpus.py`:

```python
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
from apps.funding.models import OfficialSource
from apps.research.corpus import (
    CANDIDATE_TERMS,
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


class MemoryObjectStore:
    """Copied from tests/research/test_reader.py:324 -- not imported across modules."""

    def __init__(self) -> None:
        self.objects: list[tuple[str, bytes]] = []

    def put(self, key: str, body: bytes) -> str:
        self.objects.append((key, body))
        return f"v{len(self.objects)}"


def _directive_value(directive: dict[str, object]) -> str:
    """The corpus's shape for a directive: emphasise(experience), order(cv,reverse_chronological)."""
    inner = str(directive.get("target") or "")
    if directive.get("value"):
        inner += f",{directive['value']}"
    return f"{directive['action']}({inner})"


def _baseline(programme: Programme, *, program_factory, parser, claude, store) -> ProgrammeReport:
    """Today's pipeline, seed page only. The seam later parts replace.

    Outcomes today's pipeline can and cannot report: `blocked` when the fetch is
    refused; `not_found` when nothing about a CV came back; `found` otherwise. It
    can never say `no_cv` -- reading one page cannot prove a negative -- so every
    no_cv programme scores an outcome miss at baseline, honestly.
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
    names_cv = any(CANDIDATE_TERMS.search(text) for _, text in statements)
    outcome = "found" if requirements or names_cv else "not_found"
    return ProgrammeReport(programme.id, outcome, statements, tuple(requirements))


def _drift(corpus, programme_ids: set[str], api_key: str) -> tuple[frozenset[tuple[str, str]], list[str]]:
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
    reports = {
        p.id: _baseline(p, program_factory=program_factory, parser=parser, claude=claude, store=store)
        for p in programmes
    }
    drifted, drift_lines = _drift(corpus, {p.id for p in programmes}, api_key)
    table = score(corpus, reports, split=split, drifted=drifted, per_stratum=(split == "dev"))

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
```

- [ ] **Step 2: Confirm the default suite does not run it and that it collects**

Run: `uv run pytest tests/research/test_cv_corpus.py -v`
Expected: `2 deselected` (the `-m 'not live'` addopt) and no errors.

Run: `uv run pytest tests/research/test_cv_corpus.py -m live --collect-only -q`
Expected: two items listed, `test_the_pipeline_against_the_corpus[dev]` and `[heldout]`.

- [ ] **Step 3: Confirm it skips cleanly without the search key**

Run: `SEARCH_API_KEY= uv run pytest tests/research/test_cv_corpus.py -m live -k dev -v`
Expected: SKIPPED with `SEARCH_API_KEY unset` (or `openai`/`anthropic` importorskip if those SDKs are absent). Do **not** export the live keys in this task.

- [ ] **Step 4: Lint**

Run: `uv run ruff check tests/research/test_cv_corpus.py`
Expected: no findings.

- [ ] **Step 5: Commit**

```bash
git add tests/research/test_cv_corpus.py
git commit -m "$(cat <<'EOF'
research: live runner scores today's pipeline against the corpus

One injected seam (today's read_and_derive on the seed page, no discovery),
a Tavily-extract drift check per labelled URL, the per-stratum table for
dev and aggregates for held-out, and two CSV blocks that are the pipeline
pass of the pool. Floors start at 0.0 and are ratcheted by hand.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: The counsellor correction and two CLAUDE.md sections

**Files:**
- Modify: `CLAUDE.md` (lines 746, 749, 819 in the worktree copy; plus two new sections)
- Modify: `apps/documents/constraints.py:43,63`
- Modify: `apps/documents/derive.py:80,432,475,569,618,639`
- Modify: `tests/documents/test_derive.py` (two docstrings)

**Interfaces:** none — comments and documentation only.

- [ ] **Step 1: Replace every "counsellor" in the two code files and the test**

```bash
sed -i \
  -e 's/#: with rule_text so the counsellor reads the page.s own words\./#: with rule_text so the student reads the page'"'"'s own words (CLAUDE.md, "Who reads a CV warning")./' \
  -e 's/the rule, and two quotes must both reach the counsellor\./the rule, and two quotes must both reach the student./' \
  apps/documents/constraints.py
sed -i \
  -e 's/STUDENT -- a warning the counsellor would see quoting/STUDENT -- a warning the student would see quoting/' \
  -e 's/to the counsellor as `undecided` with the quote/to the student as `undecided` with the quote/' \
  -e 's/counsellor instead of risking a rule the page never stated\./student instead of risking a rule the page never stated./' \
  -e 's/# counsellor has to see the quote\./# student has to see the quote./' \
  -e 's/resolve_rules kept one of them and the counsellor saw one warning/resolve_rules kept one of them and the student saw one warning/' \
  -e 's/counsellor reads the sentence the readings could not settle\./student reads the sentence the readings could not settle./' \
  apps/documents/derive.py
sed -i \
  -e 's/the counsellor sees it\./the student sees it./' \
  -e 's/the counsellor sees the$/the student sees the/' \
  tests/documents/test_derive.py
grep -n -i "counsellor\|counselor" apps/documents/constraints.py apps/documents/derive.py tests/documents/test_derive.py
```

Expected: the final `grep` prints nothing. If it prints a line, the wording differs from the pattern: edit that line by hand to say "the student", keeping the rest of the sentence.

- [ ] **Step 2: Fix the three CLAUDE.md lines**

```bash
sed -i \
  -e 's/rule that is wrong costs a warning the counsellor reads beside the quote/rule that is wrong costs a warning the student reads beside the quote/' \
  -e 's/which `render_cv_with_warnings` puts in front of the counsellor\./which `render_cv_with_warnings` puts in front of the student./' \
  -e 's/curated, the CV renders STANDARD, the counsellor sees no warning/curated, the CV renders STANDARD, the student sees no warning/' \
  CLAUDE.md
grep -n "counsellor" CLAUDE.md
```

Expected: `grep` prints nothing. (The "counselor"-spelled lines around 338-350 describe *recommendation* review, are already correct, and stay.)

- [ ] **Step 3: Add the two sections to CLAUDE.md**

Insert immediately before the line `## The rule catalogs — read these before researching CV or letter conventions`:

```markdown
## Who reads a CV warning — the student, not a counsellor

No counsellor reviews CVs (owner, 2026-09-14). The AI writes the CV, the student sees it, and
changes are made through a planned chatbot (the CV-requirement programme, part 6). So every
`undecided` / `unapplied` rule and every render warning has ONE audience: the student, through
that surface, which does not exist yet. Comments in `apps/documents/constraints.py` and
`derive.py`, and three lines in this file, used to say "the counsellor"; they were corrected
2026-09-15 with this note. The design is unchanged — a rule nothing can act on is shown, never
dropped — only the reader is.

## The CV-requirement corpus — read this before measuring discovery or derivation

`docs/research/cv-corpus-programmes.csv` and `cv-corpus-rules.csv` are the hand-adjudicated
ground truth for "did we find the CV requirements this programme publishes"
(`docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md`). Loader and scorer:
`apps/research/corpus.py`. The live runner `tests/research/test_cv_corpus.py` prints
recall/precision/localization per stratum and asserts hand-ratcheted floors; the headline is
**recall on BINDING requirements**, because a missed binding rule costs a student an
application and an invented one costs an edit they can decline. Rules of the file:
`seed_url` is the programme's front page, never a documents page (seeding with the rule page
defines discovery away); a `requirement_key` is always one the engine already has, with
`unapplied` for what the vocabulary cannot carry; hosts from `cv-format-eval.csv` and the
2026-09-15 survey may be `dev`, never `heldout` (`corpus.contaminated_hosts`). `manage.py
pool_cv_corpus --digest` fills source digests; `--pass vendor` pools candidate sentences into
`cv-corpus-candidates.csv` for adjudication. At 45 programmes the corpus demonstrates ≥95%
and diagnoses losses; it cannot demonstrate 99% (spec, "The measurement ceiling").
```

- [ ] **Step 4: Run the touched tests and lint**

Run: `uv run pytest tests/documents/test_derive.py -q && uv run ruff check apps/documents/constraints.py apps/documents/derive.py`
Expected: tests pass (deselecting the live ones), ruff clean. If ruff reports `E501` on constraints.py line 43, break the comment across two `#:` lines.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md apps/documents/constraints.py apps/documents/derive.py tests/documents/test_derive.py
git commit -m "$(cat <<'EOF'
docs: the reader of a CV warning is the student, not a counsellor

Owner fact 2026-09-14: no counsellor reviews CVs. Comments in constraints.py
and derive.py, two test docstrings and three CLAUDE.md lines said otherwise;
corrected, with a CLAUDE.md note recording the fact and a section pointing
the next session at the corpus.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Complete the programme list — 12 more dev, 15 held-out

**Files:**
- Modify: `docs/research/cv-corpus-programmes.csv`

**Interfaces:**
- Consumes: `load_corpus()` and `contaminated_hosts()` (Task 2), `tests/research/test_corpus.py::test_the_committed_corpus_loads` (Task 4).
- Produces: 30 `dev` and 15 `heldout` rows; the loader's two "no programme carries" warnings gone.

This task chooses real programmes. The procedure is fixed; the choices are the executor's, recorded in the commit message.

- [ ] **Step 1: List what the corpus still needs**

Run: `uv run pytest tests/research/test_corpus.py::test_the_committed_corpus_loads -s -q 2>&1 | grep "no programme carries"`
Expected: `dev: no programme carries ['non_english']` and `heldout: no programme carries [...all seven...]`.

- [ ] **Step 2: Add the 12 remaining `dev` programmes**

Candidates the survey already touched (so they are `dev`, and every one is on `contaminated_hosts()`): Rhodes Scholarship (`rhodeshouse.ox.ac.uk`, strata `deep`), Swedish Institute SISGP (`si.se`, `in_template`), Campus France Eiffel with Université Paris-Saclay as host (`universite-paris-saclay.fr`, `in_template;non_english` — the French page carries the template), Fulbright Nepal (`usefnepal.org`, `in_template;deep`), Chevening (`chevening.org`, `no_cv`), Aalto (`aalto.fi`, `deep`), JASSO (`jasso.go.jp`, `js_only;non_english`), Korea GKS (`studyinkorea.go.kr`, `no_cv;in_template`), SBFI Swiss Government Excellence Scholarships (`sbfi.admin.ch`, `blocked;non_english`), Study in Japan MEXT (`studyinjapan.go.jp`, `deep;non_english`), DAAD EPOS (`daad.de`, `blocked;in_template` — the checklist PDF), and one more Erasmus Mundus programme from `docs/research/cv-format-eval.csv`'s hosts not yet seeded (there is none left; take any EMJM from the EACEA catalogue instead, strata empty).

For each: find the **front page** — the URL a student lands on from a search for the programme's name — with

```bash
SEARCH_API_KEY="$TAVILY_API_KEY" uv run python - <<'PY'
import os, json, urllib.request
q = "Rhodes Scholarship official site"  # change per programme
req = urllib.request.Request("https://api.tavily.com/search",
    data=json.dumps({"query": q, "max_results": 5}).encode(),
    headers={"Authorization": f"Bearer {os.environ['SEARCH_API_KEY']}", "Content-Type": "application/json"})
for r in json.load(urllib.request.urlopen(req))["results"]:
    print(r["url"])
PY
```

take the result on the official host, cut it back to the programme's landing page (never a `/documents`, `/how-to-apply` or `/faq` path), confirm it with `curl -s -o /dev/null -L -w '%{http_code}\n' <url>` (200, or a known-blocked host), and append a row. `expected_outcome` is `no_cv` for Chevening and GKS, `found` otherwise. `admissions_cycle` is `2026/27`.

- [ ] **Step 3: Add the 15 `heldout` programmes**

Constraints: no host in `contaminated_hosts()` (the loader refuses one); each of the seven strata present at least once; at least three with strata empty (controls); at least two `no_cv`; at least two `non_english`. Pick from institutions and funders this repo has **never** fetched: e.g. Dutch universities other than Delft and Leiden, Nordic universities other than Aalto, Erasmus Mundus programmes not in the eval CSV, national scholarship schemes (Ireland GOI-IES, Belgium ARES, Italy Invest Your Talent, Czech government scholarships, Vietnamese or Indonesian LPDP-style schemes), US Fulbright commissions other than Nepal. Find each front page as in Step 2. Do **not** read any of their documents pages while choosing — the point of held-out is that nobody has looked. Set `strata` from what is knowable without reading the rules page: the host's nationality (`non_english`), whether it is a funder with a known no-CV posture (`no_cv`), whether the site is a JS shell (`curl -s <url> | wc -c` large with little visible text → `js_only`). Leave the rest empty; drift and pooling will reveal `deep`/`in_template`/`careers_decoy` later and the flags may be added then.

- [ ] **Step 4: Verify the file loads and both warnings are gone**

Run: `uv run pytest tests/research/test_corpus.py -s -q`
Expected: PASS; the output contains no `no programme carries` line, and exactly 45 programmes: `uv run python -c "from apps.research.corpus import load_corpus; c=load_corpus(); print(len(c.in_split('dev')), len(c.in_split('heldout')))"` prints `30 15`.

- [ ] **Step 5: Commit**

```bash
git add docs/research/cv-corpus-programmes.csv
git commit -m "$(cat <<'EOF'
research: the corpus reaches 45 programmes -- 30 dev, 15 held out

<one line per held-out programme: id, host, strata, and why it was chosen>

No held-out host appears in cv-format-eval.csv or the 2026-09-15 survey;
the loader refuses one that does. No documents page of a held-out
programme was read while choosing it.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: First pooling run, baseline measurement, adjudication handoff

**Files:**
- Modify: `docs/research/cv-corpus-rules.csv` (digests filled)
- Create: `docs/research/cv-corpus-candidates.csv`
- Create: `docs/superpowers/research/2026-09-16-cv-corpus-baseline.md` (date = the day it runs)
- Modify: `tests/research/test_cv_corpus.py` (record the baseline beside the floors)

**Interfaces:**
- Consumes: everything above; live keys.
- Produces: a digested rules file, a candidates file for adjudication, and the recorded baseline numbers.

This task spends credits: roughly 20 Tavily extracts for digests, 30 crawls (≈600 pages) for the vendor pass, 20 extracts for the drift check, and 30 `read_and_derive` calls (each three statement reads plus up to six judge calls). Run it once.

- [ ] **Step 1: Export the keys**

```bash
set -a; . ~/.config/tehsil_agent/openai.env; . ~/.config/tehsil_agent/anthropic.env; . ~/.config/tehsil_agent/search.env; set +a
export SEARCH_API_KEY="$TAVILY_API_KEY"
```

- [ ] **Step 2: Fill the digests**

Run: `uv run python manage.py pool_cv_corpus --digest`
Expected: `digest: filled N of N URLs`. If a URL is reported unreadable, record it in the rules row's `note` (`Tavily could not read this URL on <date>`) and leave its digest blank; the runner treats undigested rows as un-driftable.

Then: `uv run pytest tests/research/test_corpus.py -s -q` — PASS, and the `source_sha256` warning is gone or names only the unreadable rows.

- [ ] **Step 3: Run the vendor pass**

Run: `uv run python manage.py pool_cv_corpus --pass vendor --split dev`
Expected: one `vendor: <id>: N pages, M candidates` line per dev programme and a final total. For each `no crawl results` line, run the Firecrawl `/agent` fallback by hand once, paste its candidate URLs' sentences into the candidates file with `pool_source=vendor_agent`, and list the programme under "Firecrawl fallback used" in the baseline note (Step 5) -- the programmes file has no note column on purpose.

- [ ] **Step 4: Run the live runner on `dev`**

Run: `uv run pytest tests/research/test_cv_corpus.py -m live -k dev -s 2>&1 | tee /tmp/claude-1000/-home-orkhan-Desktop-tehsil-agent/ccbb4fe9-8703-4059-a9d3-bfb125dfd675/scratchpad/corpus-baseline.txt`
Expected: PASS (floors are 0.0). The output has the table, drift lines, and the two CSV blocks. Append the `candidates` block's rows to `docs/research/cv-corpus-candidates.csv` (skip the header line). Keep the `unjudged` block for Step 5.

- [ ] **Step 5: Record the baseline**

Create `docs/superpowers/research/<today>-cv-corpus-baseline.md` with: the full table verbatim, the drift lines, the `unjudged` block, which programmes needed the Firecrawl fallback, the credit spend observed, and one paragraph reading the numbers — expected shape: binding recall low (the seed page rarely carries the rule), outcome accuracy under 0.7 (every `no_cv` and `blocked` programme misses), `(control)` row highest, `careers_decoy` and `deep` lowest. State what the numbers say about where part 3 should start.

Then in `tests/research/test_cv_corpus.py`, under the two floor constants, add a comment:

```python
#: Baseline measured <date> on 30 dev programmes (docs/superpowers/research/<date>-cv-corpus-baseline.md):
#: binding recall <x.xx>, recall <x.xx>, precision <x.xx>, localization <x.xx>, outcome <x.xx>.
```

- [ ] **Step 6: Commit and stop for adjudication**

```bash
git add docs/research/cv-corpus-rules.csv docs/research/cv-corpus-candidates.csv docs/superpowers/research/*-cv-corpus-baseline.md tests/research/test_cv_corpus.py
git commit -m "$(cat <<'EOF'
research: first pooling run and the corpus baseline

Digests filled, vendor-pass candidates pooled for all 30 dev programmes,
today's pipeline scored: <one line with the ALL row numbers>. The
candidates file is the adjudication queue; nothing in it is a label yet.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

**Then stop.** What follows is human work, not this plan's: adjudicate `cv-corpus-candidates.csv` row by row into `cv-corpus-rules.csv` (status `accepted`/`rejected`/`close_call`, `adjudicated_by=claude`, `pool_source` as pooled), hand every `close_call` and a random 20% of the `accepted` rows to the owner, and re-run Task 9 Step 4 once the labels have settled. Part 2 begins after that.

---

## Self-review

**Spec coverage.**
- Two CSVs with the spec's exact columns → Task 4 (`PROGRAMME_COLUMNS`, `RULE_COLUMNS` in Task 2 match the spec tables column for column, including `expected_outcome`, `source_sha256`, `enforcement`, `pool_source`).
- Vocabulary pinned to `CONSTRAINT_KEYS` ∪ `{cv_format_requirement, cv_directive}`, `unapplied` for the inexpressible → Task 2.
- Contamination rule, seed-URL rule → Task 2 loader + Task 4/8 procedure + CLAUDE.md section (Task 7).
- Three passes: pipeline = runner's CSV blocks (Task 6), vendor = `--pass vendor` (Task 5), hand = human (Task 9 handoff). Candidate sentences verified against our own Tavily extract: the vendor pass *is* Tavily's extract; the digest is Tavily's extract (Task 5).
- Binding recall headline, recall/precision, localization, outcome accuracy, per-stratum on dev only, unjudged handed back not counted wrong, drift excluded loudly → Task 3 + Task 6.
- Runner `live`, floors as constants ratcheted by hand → Task 6.
- Counsellor correction in CLAUDE.md and code comments → Task 7.
- 45 programmes, 30/15 → Tasks 4 and 8.
- Cost stated → Task 9 preamble. Lifetime/re-pool cadence → not built here by design (part 6 owns the schedule; the spec says so); the command is the thing that schedule will call.
- Owner 20% sample, close_call routing → Task 9 handoff text; columns support it.

**Placeholder scan.** Task 8's programme choices and Task 9's measured numbers are genuinely unknown until executed; each has a fixed procedure and a defined expected shape rather than a "TBD". No other open ends.

**Type consistency.** `ProgrammeReport.requirements` is `tuple[tuple[str, str, str], ...]` in Task 3 and built as `list[tuple[str, str, str]]` then `tuple(...)` in Task 6 ✓. `score(..., drifted: frozenset[tuple[str, str]])` in Task 3; Task 6's `_drift` returns `frozenset[tuple[str, str]]` ✓. `tavily_extract(urls: Sequence[str], *, api_key, post)` in Task 1; Task 5 and Task 6 call it with a `list[str]` and `api_key=` ✓. `fill_digests(rules: Sequence[Rule], extracted: Mapping[str, str])` in Task 5 matches its test ✓. `CANDIDATE_COLUMNS` order in Task 5 matches Task 6's printed header ✓. `Enforcement.BINDING` compared against `Rule.enforcement: str` — `Enforcement` is a `StrEnum`, so `"BINDING" == Enforcement.BINDING` is `True` ✓.
