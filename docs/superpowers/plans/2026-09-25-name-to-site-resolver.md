# Name→Site Resolver (build item 8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a URL-less organisation name — a VGM foundation with a free-mail address today; a
hub-page or R5 affiliation name tomorrow — into its registrable domain, or into a recorded
**reason** it stays unresolved. The resolver is §6.5 as specified: v4's ladder, the six hold-out
rules as data rather than typed lists, Diffbot Enhance on the residue, and a fresh-script hold-out
that decides whether its answers may be written to the shared catalog at all.

**Architecture:** Pure scoring and a small orchestrator in `apps/research/resolver.py`; name reading
(folding, kinds, morphology) in `apps/research/names.py`; the vocabulary the six rules need —
organisation kinds, country/demonym/settlement names, each country's high-frequency name words —
built from Wikidata by a command into committed JSON under `apps/research/resolver_data/`, never
typed into code. One thin Wikidata transport (`apps/research/wikidata.py`) and one Diffbot Enhance
adapter (`apps/research/providers/diffbot.py`) behind the existing `egress.fetch_json_api`. The
title check fetches through the existing `fetch.fetch_page` seam. Rung 0 is the existing
`domains.email_domain`; keys are the existing `hosts.registrable_domain`; denylisting is the
existing `domains.is_catalogue`; writes go through the existing `register.record_organisation`.
**No new table**: `RegisterEntry` gains the names store and the resolution's reason columns.

**Tech Stack:** Django 5.2 / Python per `requires-python` / Postgres 17; `uv run` for everything;
pytest with `pytestmark = pytest.mark.django_db`; lxml for titles; one new dependency, `anyascii`
(ISC licence — see Task 1 for why not `unidecode`); Tavily `candidates()` (built), Firecrawl →
scrape.do through `fetch_page` (built), Wikidata's public API (CC0), Diffbot Knowledge Graph
Enhance (commercial grant, re-read before use).

**Spec:** `docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md` §6.5 (the
resolver), §6.1 (`names`, `record_organisation`, statuses), §11 (`SITE_UNKNOWN` — the consumer of
what stays unresolved), §13 (Diffbot 400 entities/month), §15 (the readiness ledger's "acceptance
on a fresh script owed"), §16 item 8. The measurements every rule below rests on are in
`docs/superpowers/specs/2026-09-17-role-routed-discovery-design.md` §4.13a–§4.13b and
`docs/superpowers/research/2026-09-18-tool-capability-oversights.md` §5 — read both before
changing a threshold; each number here is cited to them.

---

## Global Constraints

- **Branch and base.** Branch from `master` into a fresh worktree:
  `git worktree add -b claude/resolver ../resolver origin/master`. Test database for every
  `pytest`/`manage.py` call: `POSTGRES_DB=tehsil_resolver`. Two sessions on one database produce
  fake failures.
- **Never hard-code the migration number.** `research` was at `0009_site_job_record_rls` on
  2026-09-25. Task 6 tells you how to find the real leaf; expect to need a merge migration if
  another branch landed a `research` migration while you worked (CLAUDE.md, "Migrations").
- **No new table, and that is a decision, not an omission.** The vocabulary is versioned data in
  the repository (principle 7: data rows with a source URL and a retrieved-on date); the names
  store and the resolution record are columns on `RegisterEntry`, a shared-catalog table that
  already carries `shared_catalog_select` + `catalog_ingestion_write` (research/0007) and is
  already in `_SHARED_TABLES`. The new columns inherit those policies. Task 6 still proves the
  write refusal through `runtime_connection`, because the test role bypasses RLS and nothing else
  proves anything (CLAUDE.md, "Row-level security").
- **Only a URL is read from any provider.** Tavily and Diffbot hand back URLs and nothing else is
  kept: no candidate list, snippet, title or Diffbot score is persisted on any row. The top-3
  candidates §11 shows an operator are recomputed by item 12 at queue time, not stored here. The
  page `<title>` the check reads is origin bytes, read in memory and discarded.
- **No model call anywhere in this plan.** Every decision is deterministic; `rate_limited()` is
  therefore not owed, but every paid call is capped: Tavily per run (`CallBudget`), fetches per
  run (`SweepBudget`), Diffbot per rolling 30 days (counted off `RegisterEntry.diffbot_asked_at`).
- **The resolver writes nothing to the catalog until the gate passes.** `RESOLVER_WRITES_ENABLED`
  defaults to off; `manage.py resolve_register --write` refuses while it is off; Task 12 flips it
  only on a PASS. Until then the output is printed candidates, per the standing rule of 4.13a
  ("`resolve()` output is a candidate … no URL-less register is ingested through it").
- **Freeze before drawing.** The hold-out (Task 10) is drawn only after Tasks 1–9 are committed,
  and it records a digest of the resolver's code and data; the gate (Task 11) refuses to score a
  resolver whose digest differs. Tuning after seeing hold-out results turns the hold-out into
  development data — the Georgia/Kazakhstan lesson (§6.5).
- **Coordination with item 7.** Item 7 also plans a Wikidata adapter. Before Task 2, run
  `ls apps/research/wikidata.py`. If it exists on `master`, **do not create a second transport**:
  add only the functions this plan needs (`find_item`, and `sparql` if absent) to that module with
  the signatures given in Task 2, and adapt imports. If it does not, create it as written.
- **Operator-run, catalog role.** Every command that writes runs as `DATABASE_ROLE=migration` (or
  `SET ROLE catalog_ingestion`) and appends `fetch.CATALOG_ROLE_NOTE` to its help, like
  `classify_organisations`. A write that matches zero rows raises (Task 8, `resolve_entries`) — under the runtime role
  an `UPDATE` on a shared table silently matches nothing, which is failure mode 1 of CLAUDE.md's
  RLS section in a new place.
- **Validation after every task:** `uv run ruff check apps config tests scripts`,
  `uv run mypy apps config`, the task's focused tests with `POSTGRES_DB=tehsil_resolver`,
  `POSTGRES_DB=tehsil_resolver uv run python manage.py makemigrations --check --dry-run`, and
  `uv run bandit -c pyproject.toml -r apps config`. Never `ruff format`. Read `${PIPESTATUS[0]}`,
  never a piped exit code.
- **Commits:** one task per commit, `feat(research): …` / `test(research): …` / `docs: …`, ending
  with the attribution trailer your session is configured with.

---

## File structure

| file | responsibility |
|---|---|
| `pyproject.toml`, `uv.lock` (modify) | add `anyascii` |
| `apps/research/names.py` (create) | `fold`, `tokens`, `kind_of` (morphology + compounds), `NameProfile`, `profile` |
| `apps/research/wikidata.py` (create, or extend — see Global Constraints) | `sparql`, `find_item`, `WikidataMatch` |
| `apps/research/egress.py` (modify) | `fetch_json_api(..., content_types=)` — WDQS answers `application/sparql-results+json` |
| `apps/research/vocabulary.py` (create) | `Vocabulary`, `load_vocabulary`, `build_country_doc`, `build_kinds_doc` |
| `apps/research/resolver_data/kinds.json`, `<CC>.json` (create, generated) | rules 1–3 as data |
| `apps/research/management/commands/build_resolver_vocabulary.py` (create) | writes the JSON above |
| `apps/research/providers/diffbot.py` (create) | `DiffbotEnhance.homepage(name) -> str` — a URL, nothing else |
| `apps/research/models.py` (modify) | `ResolvedVia`, `UnresolvedReason`; five `RegisterEntry` columns |
| `apps/research/migrations/<next>_register_entry_resolution.py` (create) | columns, backfill, shape constraint |
| `apps/research/vgm.py` (modify, two lines) | rung 0 writes `resolved_via=EMAIL` and `names` |
| `apps/research/resolver.py` (create) | scoring tiers, directory rule, title check, `Resolver`, budgets |
| `apps/research/resolve_entries.py` (create) | `RegisterSpec`, `due_entries`, `record_resolution` |
| `apps/research/management/commands/resolve_register.py` (create) | operator entry, dry-run by default |
| `apps/research/holdout.py` (create) | draw, verdicts, adjudication, pass rule, frozen digest |
| `apps/research/management/commands/draw_resolver_holdout.py`, `resolver_gate.py` (create) | the gate |
| `config/settings/base.py` (modify) | `DIFFBOT_TOKEN`, `DIFFBOT_TERMS_READ_ON`, `DIFFBOT_MONTHLY_ENTITIES`, `RESOLVER_TAVILY_CREDITS_PER_RUN`, `RESOLVER_WRITES_ENABLED` |
| `docs/research/resolver-holdout-vn.csv` (create, generated) | the drawn hold-out |
| `docs/superpowers/research/<date>-resolver-holdout-vn.md` (create) | the gate's result, pass or fail |
| `CLAUDE.md`, `docs/legal/2026-09-provider-terms.md` (modify) | two outbound paths; the Diffbot terms read |
| `tests/research/test_names.py`, `test_wikidata.py`, `test_vocabulary.py`, `test_diffbot.py`, `test_resolver_scoring.py`, `test_resolver_title.py`, `test_resolver.py`, `test_resolve_entries.py`, `test_register_entry_resolution_rls.py`, `test_resolve_register_command.py`, `test_holdout.py` (create); `test_egress.py`, `test_vgm.py` (modify) | tests |

---

## What stays unresolved, and why — the contract this plan writes

Every unresolved `RegisterEntry` carries exactly one `unresolved_reason`. The reason decides
whether a later run retries it and what item 12 asks a person. Unresolved is **20% German / 48%
Turkish** on the dev samples (§6.5) and that is the honest shape, not a defect to tune away.

| reason | meaning | retried by `resolve_register`? | item 12 |
|---|---|---|---|
| `ONE_TOKEN_NAME` | ≤ 1 distinctive token and no kind word ("TEMA", "Cusanuswerk") — nothing to agree a title against, so search can never be trusted (4.13a, `tema.org`) | no — final | `SITE_UNKNOWN` |
| `NO_CANDIDATE` | no candidate scored above zero, and Diffbot (if asked) produced nothing that passed the title check. Syllabic acronyms (`bisav`, `tohav`) land here when Diffbot is off | no — final (Diffbot may still be asked on a later run with `--diffbot` if it never was) | `SITE_UNKNOWN` |
| `DIRECTORY` | every scoring candidate's label is only kind/place/common words (`embassies.info`, `stiftungen.de`) — rule 1 | no — final | `SITE_UNKNOWN` |
| `TITLE_MISMATCH` | the best and runner-up candidates were reachable and their titles failed kind agreement or named none of the name's tokens (`inonu.edu.tr` for İnönü Vakfı) | no — final | `SITE_UNKNOWN` |
| `FETCH_FAILED` | a title fetch did not return a usable page (~10% of hosts, 4.13a) — never accepted | yes, after 7 days | `HOST_UNREACHABLE` after the fetch engine's own retries |
| `IDENTIFIER_CONFLICT` | the Wikidata id the name matched is already held by a different organisation | no — final | `SITE_UNKNOWN` (a merge question) |

Not a reason, never written: a run that stopped on its Tavily or fetch budget leaves the entry
exactly as it was, so the next run picks it up. **Some truths are unreachable by name** (rule 5):
an embassy whose site is its ministry's (`esteri.it`) comes back `NO_CANDIDATE`/`TITLE_MISMATCH`
and that is the correct output.

---

### Task 0: Worktree, branch, database, baseline

**Files:** none.

- [ ] **Step 1: Create the worktree from master and read the migration leaf**

```bash
cd ~/tehsil_agent && git fetch origin master && git worktree add -b claude/resolver ../resolver origin/master
ls ../resolver/apps/research/migrations/ | sort | tail -3
ls ../resolver/apps/research/wikidata.py 2>/dev/null || echo "no wikidata.py: Task 2 creates it"
```

Expected: the last migration is `0009_site_job_record_rls.py` or later. Write down the real leaf;
Task 6 depends on it.

- [ ] **Step 2: Prove the suite is green before touching anything**

```bash
cd ../resolver && uv sync --frozen && POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_domains.py tests/research/test_vgm.py tests/research/test_organisation_register.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
```

Expected: `… passed`, `EXIT=0`.

---

### Task 1: Folding, tokens and kind morphology (`names.py`)

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Create: `apps/research/names.py`, `tests/research/test_names.py`

**Why `anyascii` and not `unidecode`:** v5 used `unidecode` for romanisation (4.13b). `Unidecode`
is GPL-2.0-or-later; `anyascii` is ISC, covers every script v5 met (Georgian, Kazakh Cyrillic,
Turkish) plus Vietnamese, and has no dependencies. The romanisations differ in detail, which is one
more reason the fresh hold-out is the only acceptance that counts.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`'s `dependencies`, after `"tldextract>=5.3.2,<6",` add:

```toml
  # apps/research/names.py: romanise every script before a name meets a
  # domain label. ISC; unidecode (GPL) was the measured prototype's choice.
  "anyascii>=0.3.2,<0.4",
```

```bash
uv lock && uv sync --frozen && uv run pip-audit
```

Expected: `No known vulnerabilities found`. If `uv run mypy apps config` later reports
`anyascii` as missing stubs, add `"anyascii.*"` to the `module = [...]` list that already holds
`"lxml.*"` in `pyproject.toml`.

- [ ] **Step 2: Write the failing tests**

`tests/research/test_names.py`:

```python
"""The resolver's reading of a name (spec 6.5, rules 1 and 3; 4.13b's symmetric fold)."""

from apps.research.names import fold, kind_of, profile, tokens
from apps.research.vocabulary import Vocabulary

FOUNDATION, ASSOCIATION, UNIVERSITY, EMBASSY = "Q157031", "Q48204", "Q3918", "Q3917681"


def vocab(**overrides) -> Vocabulary:
    fields = dict(
        country_code="TR", country_qid="Q43", cctld="tr", languages=("tr", "en", "ru"),
        kinds={
            "stiftung": frozenset({FOUNDATION}), "vakif": frozenset({FOUNDATION}),
            "foundation": frozenset({FOUNDATION}), "dernegi": frozenset({ASSOCIATION}),
            "association": frozenset({ASSOCIATION}), "university": frozenset({UNIVERSITY}),
            "embassy": frozenset({EMBASSY}),
        },
        geo=frozenset({"turkiye", "turkey", "turk", "stuttgart", "istanbul"}),
        generic=frozenset({"egitim", "kultur"}),
    )
    fields.update(overrides)
    return Vocabulary(**fields)


def test_folding_is_symmetric_across_scripts_and_umlaut_spellings() -> None:
    # A name and a domain label meet only after the SAME fold: "Hör" and "hoer"
    # must both become "hor", or kind-hoerstiftung.de never matches its name.
    assert fold("Kind Hörstiftung") == fold("kind hoerstiftung") == "kind horstiftung"
    assert fold("İnönü Vakfı") == "inonu vakfi"
    assert tokens("Georgian Young Lawyers' Association") == ("georgian", "young", "lawyers", "association")
    assert tokens("საქართველო")  # romanised to something, never empty


def test_kind_words_tolerate_morphology_and_compounds() -> None:
    v = vocab()
    assert kind_of("vakfi", v) == {FOUNDATION}          # vakfı ~ vakıf, one transposition
    assert kind_of("vakiflar", v) == {FOUNDATION}       # inflection
    assert kind_of("stiftungen", v) == {FOUNDATION}
    assert kind_of("bundesstiftung", v) == {FOUNDATION}  # rule 3: ends with a kind word
    assert kind_of("embassies", v) == {EMBASSY}
    assert kind_of("universitesi", v) == {UNIVERSITY}
    assert kind_of("hirschfeld", v) == frozenset()
    assert kind_of("federal", v) == frozenset()


def test_a_profile_separates_distinctive_tokens_from_kind_place_and_common_words() -> None:
    p = profile(["İstanbul Eğitim ve Kültür Vakfı"], vocab())
    assert p.distinctive == frozenset()                 # every word is place, common or kind
    assert p.kinds == {FOUNDATION}
    assert "istek" not in p.initials                     # syllabic: no lexical rule reaches it
    assert "iekv" in p.initials and "ievkv" in p.initials


def test_every_name_variant_is_scored_as_one_union() -> None:
    # Rule 4: Georgian domains are acronyms of the ENGLISH name.
    native = profile(["საქართველოს ახალგაზრდა იურისტთა ასოციაცია"], vocab())
    both = profile(
        ["საქართველოს ახალგაზრდა იურისტთა ასოციაცია", "Georgian Young Lawyers' Association"],
        vocab(),
    )
    assert "gyla" not in native.initials
    assert "gyla" in both.initials


def test_a_name_with_one_token_and_no_kind_word_cannot_be_resolved_from_search() -> None:
    assert profile(["TEMA"], vocab()).one_token
    assert profile(["Cusanuswerk"], vocab()).one_token
    assert not profile(["TEMA Vakfı"], vocab()).one_token
    assert not profile(["Hrant Dink Vakfı"], vocab()).one_token
```

- [ ] **Step 3: Run to see them fail**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_names.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
```

Expected: collection error — `apps.research.names` and `apps.research.vocabulary` do not exist.

- [ ] **Step 4: Create `apps/research/vocabulary.py` with the dataclass only** (Task 2 adds the
  loader and builders to this file)

```python
"""The data the resolver's six rules read (spec 6.5), and nothing the resolver decides.

Kinds, places and common words are rows from Wikidata with a retrieved-on date
(principle 7: nothing names a scheme, funder, country or page in code). The
2026-09-18 hold-out failed precisely where these were typed by hand: v4 knew
"Türkiye", "Berlin" and "Stuttgart" because someone typed them, and v5 knew none.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Vocabulary:
    country_code: str
    country_qid: str
    #: The country-code TLD without its dot ("tr"), for the +0.25 tiebreak.
    cctld: str
    #: The country's official languages (Wikidata P37 -> P424), then en, ru.
    languages: tuple[str, ...]
    #: Folded single-token kind word -> the Wikidata kind items it labels.
    #: A set because one word labels several kinds ("fund").
    kinds: Mapping[str, frozenset[str]]
    #: Folded tokens of the country's names, demonyms, cities and first-level
    #: divisions (rule 2) -- never evidence of WHICH organisation.
    geo: frozenset[str]
    #: Folded tokens frequent across the country's organisation names -- the
    #: v2 finding that "a lone common word is not evidence", measured per
    #: country instead of typed.
    generic: frozenset[str]
    kinds_by_prefix: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)
    kind_cache: dict[str, frozenset[str]] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        buckets: dict[str, list[str]] = {}
        for word in self.kinds:
            buckets.setdefault(word[:3], []).append(word)
        # Longest first, so "stiftungen" meets "stiftung" before "stift".
        object.__setattr__(
            self,
            "kinds_by_prefix",
            {k: tuple(sorted(v, key=lambda w: (-len(w), w))) for k, v in buckets.items()},
        )
```

- [ ] **Step 5: Create `apps/research/names.py`**

```python
"""The resolver's reading of an organisation's name (spec 6.5).

Three things live here and nothing else: how a name and a domain label are
folded so they can meet (symmetric, every script -- 4.13b), which tokens are
KIND words (rules 1 and 3, with the morphology tolerance v5 measured:
vakfı ~ vakıf, Stiftungen ~ Stiftung, Bundesstiftung ends with Stiftung), and
which tokens are DISTINCTIVE -- the only ones that are evidence of which body
a site belongs to. Place names (rule 2) and a country's common name words are
never distinctive; both come from `vocabulary.Vocabulary`, never from here.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from anyascii import anyascii

if TYPE_CHECKING:
    from .vocabulary import Vocabulary

_SPLIT = re.compile(r"[^a-z0-9]+")
#: Applied to names AND domain labels, so it only ever makes them meet:
#: German domains spell "Hör" as "hoer", anyascii spells it "hor".
_DIGRAPHS = (("ae", "a"), ("oe", "o"), ("ue", "u"))
#: A token shorter than this is never distinctive (v2: "a lone short common
#: word is not evidence"); it still contributes to initials.
MIN_DISTINCTIVE = 4
#: Morphology and compounds only between words this long -- below it a one-edit
#: or prefix match is coincidence, not inflection.
_MIN_MORPH = 5
_MIN_INITIALS = 3


def fold(text: str) -> str:
    folded = anyascii(text).casefold()
    for digraph, vowel in _DIGRAPHS:
        folded = folded.replace(digraph, vowel)
    return folded


def tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in _SPLIT.split(fold(text)) if token)


def _one_edit(a: str, b: str) -> bool:
    """Damerau distance <= 1: one insertion, deletion, substitution or
    adjacent transposition (vakfi/vakif)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return (
            len(diff) == 2
            and diff[1] == diff[0] + 1
            and a[diff[0]] == b[diff[1]]
            and a[diff[1]] == b[diff[0]]
        )
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = next((k for k in range(len(short)) if short[k] != long_[k]), len(short))
    return short[i:] == long_[i + 1 :]


def _morph_kinds(token: str, vocab: Vocabulary) -> frozenset[str]:
    # Rule 3: a token that ENDS with a kind word is a kind word (Bundesstiftung).
    for start in range(1, len(token) - _MIN_MORPH + 1):
        hit = vocab.kinds.get(token[start:])
        if hit:
            return hit
    for word in vocab.kinds_by_prefix.get(token[:3], ()):
        if len(word) < _MIN_MORPH:
            continue
        shared = len(os.path.commonprefix((token, word)))
        if shared >= max(_MIN_MORPH, len(word) - 2) or _one_edit(token, word):
            return vocab.kinds[word]
    return frozenset()


def kind_of(token: str, vocab: Vocabulary) -> frozenset[str]:
    """The Wikidata kind items this token names, or an empty set."""
    cached = vocab.kind_cache.get(token)
    if cached is not None:
        return cached
    found = vocab.kinds.get(token, frozenset())
    if not found and len(token) >= _MIN_MORPH:
        found = _morph_kinds(token, vocab)
    vocab.kind_cache[token] = found
    return found


@dataclass(frozen=True)
class NameProfile:
    distinctive: frozenset[str]
    #: Kind items the name states ("Vakfı" -> foundation). The title check's
    #: agreement is on these, never on the holder vocabulary.
    kinds: frozenset[str]
    kind_words: frozenset[str]
    #: Each variant's tokens joined -- "full slug" (tier 3).
    slugs: frozenset[str]
    #: Each variant's initials, with and without its <= 3-letter words.
    initials: frozenset[str]

    @property
    def one_token(self) -> bool:
        return len(self.distinctive) <= 1 and not self.kinds


def profile(names: Sequence[str], vocab: Vocabulary) -> NameProfile:
    """Every variant scored as one union (rule 4) -- native, English, Russian."""
    distinctive: set[str] = set()
    kinds: set[str] = set()
    kind_words: set[str] = set()
    slugs: set[str] = set()
    initials: set[str] = set()
    for name in names:
        toks = tokens(name)
        if not toks:
            continue
        for token in toks:
            named = kind_of(token, vocab)
            if named:
                kinds |= named
                kind_words.add(token)
            elif (
                len(token) >= MIN_DISTINCTIVE
                and token not in vocab.geo
                and token not in vocab.generic
            ):
                distinctive.add(token)
        slug = "".join(toks)
        if len(slug) >= MIN_DISTINCTIVE:
            slugs.add(slug)
        for group in (toks, tuple(t for t in toks if len(t) > 3)):
            acronym = "".join(t[0] for t in group)
            if len(acronym) >= _MIN_INITIALS:
                initials.add(acronym)
    return NameProfile(
        frozenset(distinctive), frozenset(kinds), frozenset(kind_words),
        frozenset(slugs), frozenset(initials),
    )
```

- [ ] **Step 6: Run the tests**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_names.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
```

Expected: `5 passed`. If `test_a_profile_separates…` fails on `"iekv"`, print
`profile([...]).initials` — the two initials groups are "all tokens" (`ievkv`) and "tokens longer
than three letters" (`iekv`); fix the test only if the fold of *Eğitim*/*Kültür* differs from
`egitim`/`kultur` under the installed anyascii, and say so in the commit message.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock apps/research/names.py apps/research/vocabulary.py tests/research/test_names.py
git commit -m "feat(research): the resolver's reading of a name -- fold, kinds, distinctive tokens"
```

---

### Task 2: Wikidata transport and the vocabulary files (rules 1–3 as data)

**Files:**
- Modify: `apps/research/egress.py`, `tests/research/test_egress.py`, `apps/research/vocabulary.py`
- Create: `apps/research/wikidata.py`, `apps/research/management/commands/build_resolver_vocabulary.py`,
  `apps/research/resolver_data/` (generated), `tests/research/test_wikidata.py`,
  `tests/research/test_vocabulary.py`

- [ ] **Step 1: Let `fetch_json_api` accept a named JSON media type — failing test first**

Wikidata's query service answers `format=json` with `application/sparql-results+json`, and
`fetch_json_api` refuses anything but `application/json`. Widen it by parameter, never by default.
Append to `tests/research/test_egress.py`:

```python
def test_a_json_api_may_name_another_json_media_type_and_only_then_is_it_read(public_dns) -> None:
    def sparql_answer(_target, _path, **_kwargs):
        return FakeResponse(
            headers={"Content-Type": "application/sparql-results+json; charset=utf-8"},
            body=b'{"results": {"bindings": []}}',
        )

    with pytest.raises(SourceBlocked, match="content type"):
        fetch_json_api("https://query.wikidata.org/sparql", params={"q": "x"}, headers={},
                       transport=sparql_answer)
    assert fetch_json_api(
        "https://query.wikidata.org/sparql", params={"q": "x"}, headers={},
        transport=sparql_answer,
        content_types=("application/json", "application/sparql-results+json"),
    ) == {"results": {"bindings": []}}
```

Run: `POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_egress.py -q -k media_type` →
fails with `TypeError: … unexpected keyword argument 'content_types'`.

- [ ] **Step 2: Implement it in `apps/research/egress.py::fetch_json_api`**

Add the parameter after `read_timeout`:

```python
    read_timeout: float | None = None,
    content_types: Collection[str] = ("application/json",),
) -> dict[str, object]:
```

(import `Collection` from `collections.abc` beside the existing `Callable`/`Mapping`), add one
sentence to the docstring — "`content_types` names the JSON media types this API is known to
answer with; the default stays `application/json` so no caller widens by accident." — and replace
the check:

```python
        if content_type not in content_types:
            raise SourceBlocked(f"api returned content type: {content_type or 'missing'}")
```

Re-run: passes, and the whole `test_egress.py` stays green.

- [ ] **Step 3: Write the Wikidata tests**

`tests/research/test_wikidata.py`:

```python
"""Wikidata as the resolver's first stop (P856) and the source of name variants (rule 4)."""

from apps.research import wikidata


def _entity(qid, *, country="Q43", site=None, labels=None, aliases=None, dissolved=False):
    claims = {"P17": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": country}}}}]}
    if site:
        claims["P856"] = [{"rank": "normal", "mainsnak": {"datavalue": {"value": site}}}]
    if dissolved:
        claims["P576"] = [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"time": "+2001"}}}}]
    return {
        "id": qid,
        "claims": claims,
        "labels": {lang: {"language": lang, "value": v} for lang, v in (labels or {}).items()},
        "aliases": {lang: [{"value": v} for v in vs] for lang, vs in (aliases or {}).items()},
    }


def _api(search_hits, entities):
    calls = []

    def get(url, *, params, headers, **_):
        calls.append(params)
        if params["action"] == "wbsearchentities":
            return {"search": [{"id": q} for q in search_hits]}
        return {"entities": {e["id"]: e for e in entities}}

    return get, calls


def test_an_exact_label_in_the_right_country_is_a_match_and_brings_every_variant() -> None:
    get, _ = _api(["Q1"], [_entity(
        "Q1", site="https://www.hrantdink.org/",
        labels={"tr": "Hrant Dink Vakfı", "en": "Hrant Dink Foundation", "de": "Hrant-Dink-Stiftung"},
        aliases={"ru": ["Фонд Гранта Динка"]},
    )])
    match = wikidata.find_item(["Hrant Dink Vakfı"], country_qid="Q43", languages=("tr", "en", "ru"), get=get)
    assert match is not None and match.qid == "Q1"
    assert match.websites == ("https://www.hrantdink.org/",)
    assert match.labels == ("Hrant Dink Vakfı", "Hrant Dink Foundation", "Фонд Гранта Динка")


def test_a_fuzzy_hit_is_never_a_match() -> None:
    # The ROR lesson (4.13a): a plausible top hit is sometimes a different body.
    get, _ = _api(["Q2"], [_entity("Q2", labels={"tr": "İnönü Üniversitesi"})])
    assert wikidata.find_item(["İnönü Vakfı"], country_qid="Q43", languages=("tr",), get=get) is None


def test_wrong_country_dissolved_and_ambiguous_items_are_not_matches() -> None:
    other = _entity("Q3", country="Q183", labels={"tr": "TEMA"})
    gone = _entity("Q4", labels={"tr": "TEMA"}, dissolved=True)
    get, _ = _api(["Q3", "Q4"], [other, gone])
    assert wikidata.find_item(["TEMA"], country_qid="Q43", languages=("tr",), get=get) is None
    twins = [_entity("Q5", labels={"tr": "TEMA"}), _entity("Q6", labels={"tr": "TEMA"})]
    get, _ = _api(["Q5", "Q6"], twins)
    assert wikidata.find_item(["TEMA"], country_qid="Q43", languages=("tr",), get=get) is None


def test_sparql_flattens_bindings_to_values() -> None:
    def get(url, *, params, headers, content_types, **_):
        assert "application/sparql-results+json" in content_types
        return {"results": {"bindings": [{"x": {"type": "literal", "value": "1"}}]}}

    assert wikidata.sparql("SELECT ?x WHERE {}", get=get) == [{"x": "1"}]
```

- [ ] **Step 4: Create `apps/research/wikidata.py`**

```python
"""Wikidata, read two ways: the query service for the resolver's vocabulary, and
the entity API for rung 1 of name->site resolution (spec 6.5).

CC0, so a name->site pair from here is public fact and not a provider
artefact. Still never "take the first row": `wbsearchentities` is fuzzy, so a
hit is a MATCH only when one of its labels or aliases folds to the name
exactly, it is in the right country (P17) and it is not dissolved (P576) --
and only when exactly one item passes. Two passing items is ambiguity, which
is not evidence of either.

Outbound path: listed in CLAUDE.md's "Web fetching" beside the EACEA API --
a data source through `egress.fetch_json_api`, not a page fetch.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .egress import fetch_json_api
from .names import fold

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
_SPARQL_TYPES = ("application/json", "application/sparql-results+json")
#: Names searched per entity; each costs one free API call per language.
_MAX_NAMES = 3

Get = Callable[..., dict[str, object]]


@dataclass(frozen=True)
class WikidataMatch:
    qid: str
    #: P856 values, preferred rank first, deprecated dropped.
    websites: tuple[str, ...]
    #: Labels and aliases in the vocabulary's languages, in that order --
    #: the names store's contribution from Wikidata (rule 4).
    labels: tuple[str, ...]


def sparql(query: str, *, get: Get = fetch_json_api) -> list[dict[str, str]]:
    data = get(
        WIKIDATA_SPARQL, params={"query": query, "format": "json"}, headers={},
        content_types=_SPARQL_TYPES,
    )
    results = data.get("results")
    bindings = results.get("bindings", []) if isinstance(results, dict) else []
    return [
        {key: str(cell.get("value", "")) for key, cell in row.items()}
        for row in bindings
        if isinstance(row, dict)
    ]


def _statements(claims: dict[str, Any], prop: str) -> list[Any]:
    kept = [c for c in claims.get(prop) or [] if c.get("rank") != "deprecated"]
    kept.sort(key=lambda c: c.get("rank") != "preferred")
    values = []
    for claim in kept:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if value is not None:
            values.append(value)
    return values


def _labels(entity: dict[str, Any], languages: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for lang in languages:
        label = ((entity.get("labels") or {}).get(lang) or {}).get("value")
        if label:
            seen.setdefault(label, None)
        for alias in (entity.get("aliases") or {}).get(lang) or []:
            if alias.get("value"):
                seen.setdefault(alias["value"], None)
    return tuple(seen)


def find_item(
    names: Sequence[str],
    *,
    country_qid: str,
    languages: Sequence[str],
    get: Get = fetch_json_api,
) -> WikidataMatch | None:
    """The one Wikidata item these names exactly label in this country, or None."""
    ids: list[str] = []
    for name in names[:_MAX_NAMES]:
        for lang in dict.fromkeys((languages[0], "en")):
            data = get(WIKIDATA_API, params={
                "action": "wbsearchentities", "search": name, "language": lang,
                "uselang": lang, "type": "item", "limit": 10, "format": "json",
            }, headers={})
            for hit in data.get("search") or []:  # type: ignore[union-attr]
                qid = str(hit.get("id") or "")
                if qid and qid not in ids:
                    ids.append(qid)
    if not ids:
        return None
    data = get(WIKIDATA_API, params={
        "action": "wbgetentities", "ids": "|".join(ids[:50]),
        "props": "labels|aliases|claims", "format": "json",
    }, headers={})
    entities = data.get("entities") or {}
    wanted = {fold(name) for name in names}
    all_languages = tuple(dict.fromkeys((*languages, "en", "ru")))
    matches: list[WikidataMatch] = []
    for qid in ids:
        entity = entities.get(qid) if isinstance(entities, dict) else None
        if not isinstance(entity, dict):
            continue
        claims = entity.get("claims") or {}
        countries = {v.get("id") for v in _statements(claims, "P17") if isinstance(v, dict)}
        if country_qid not in countries or _statements(claims, "P576"):
            continue
        every_label = _labels(entity, tuple((entity.get("labels") or {}).keys()))
        if not wanted & {fold(label) for label in every_label}:
            continue
        websites = tuple(v for v in _statements(claims, "P856") if isinstance(v, str))
        matches.append(WikidataMatch(qid, websites, _labels(entity, all_languages)))
    return matches[0] if len(matches) == 1 else None
```

Run `POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_wikidata.py -q` → `4 passed`.

- [ ] **Step 5: Write the vocabulary-builder tests** (`tests/research/test_vocabulary.py`)

```python
"""Rules 1-3 as data: built from Wikidata, asserted against a floor and a ceiling."""

import json

import pytest

from apps.research import vocabulary
from apps.research.vocabulary import VocabularyShape, build_country_doc, build_kinds_doc


def _sparql(answers):
    def run(query, **_):
        for marker, rows in answers.items():
            if marker in query:
                return rows
        raise AssertionError(f"unexpected query: {query[:80]}")
    return run


def test_a_country_doc_carries_places_and_the_country_s_common_name_words(monkeypatch) -> None:
    monkeypatch.setattr(vocabulary, "_GEO_FLOOR", 1)
    monkeypatch.setattr(vocabulary, "_ORG_FLOOR", 1)
    orgs = [{"label": f"{w} Eğitim Vakfı"} for w in ("Ak", "Bor", "Cem", "Dal", "Ece",
                                                       "Fer", "Gül", "Han", "Işık", "Jale")]
    doc = build_country_doc("TR", retrieved_on="2026-09-25", sparql=_sparql({
        "wdt:P297": [{"country": "http://www.wikidata.org/entity/Q43", "lang": "tr", "tld": ".tr"}],
        "wd:Q515": [{"label": "Türkiye"}, {"label": "Stuttgart"}, {"label": "Nur-Sultan"}],
        "wdt:P856": orgs,
    }))
    assert doc["country_qid"] == "Q43" and doc["cctld"] == "tr"
    assert doc["languages"] == ["tr", "en", "ru"]
    assert {"turkiye", "nursultan", "sultan"} <= set(doc["geo"])
    assert {"egitim", "vakfi"} <= set(doc["generic"])   # in every one of ten labels
    assert "bor" not in doc["generic"]


def test_a_country_that_is_not_exactly_one_item_is_a_stop() -> None:
    with pytest.raises(VocabularyShape):
        build_country_doc("TR", retrieved_on="2026-09-25", sparql=_sparql({"wdt:P297": []}))


def test_kinds_keep_single_token_labels_only(monkeypatch) -> None:
    monkeypatch.setattr(vocabulary, "_KINDS_FLOOR", 1)
    doc = build_kinds_doc(["tr", "en"], depth=2, retrieved_on="2026-09-25", sparql=_sparql({
        "wd:Q43229": [
            {"kind": "http://www.wikidata.org/entity/Q157031", "label": "vakıf"},
            {"kind": "http://www.wikidata.org/entity/Q157031", "label": "foundation"},
            {"kind": "http://www.wikidata.org/entity/Q163740", "label": "non-profit organization"},
            {"kind": "http://www.wikidata.org/entity/Q163740", "label": "NPO"},
        ],
    }))
    assert doc["kinds"] == {"Q157031": ["foundation", "vakif"], "Q163740": ["npo"]}


def test_the_committed_kinds_name_every_kind_v5_lacked() -> None:
    """4.13b rule 1: nine of Kazakhstan's eleven wrongs were directories that
    matched "embassy" as a DISTINCTIVE word, because the kind list had 16 kinds."""
    doc = json.loads((vocabulary.DATA_DIR / "kinds.json").read_text("utf-8"))
    words = {w for ws in doc["kinds"].values() for w in ws}
    for word in ("embassy", "foundation", "association", "university", "federation",
                 "club", "consulate", "commission", "society", "academy"):
        assert word in words, word


@pytest.mark.parametrize("country", ["TR", "DE", "AZ", "GE", "KZ", "UZ", "VN", "ID"])
def test_every_committed_country_loads(country) -> None:
    v = vocabulary.load_vocabulary(country)
    assert v.country_qid.startswith("Q") and v.geo and v.kinds
```

- [ ] **Step 6: Add the loader and builders to `apps/research/vocabulary.py`**

Append:

```python
import functools
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from . import wikidata
from .names import tokens

DATA_DIR = Path(__file__).resolve().parent / "resolver_data"

_ISO2 = re.compile(r"^[A-Z]{2}$")
#: Assertions, not tuning: a count outside these bounds is a changed query or a
#: dropped filter, and the build stops rather than writing it (the VGM rule).
_GEO_FLOOR, _GEO_CEILING = 20, 150_000
_ORG_FLOOR, _ORG_LIMIT = 50, 30_000
_KINDS_FLOOR, _KINDS_CEILING = 20, 3_000
#: A token in at least this share of the country's organisation names, and in
#: at least ten of them, is common vocabulary -- never evidence of which body.
_GENERIC_SHARE, _GENERIC_MIN_LABELS = 0.01, 10
#: Kind items: subclasses of organization (Q43229) with at least this many
#: sitelinks -- enough languages to label them (rule 1: "~50 kinds, 26+ languages").
_KIND_SITELINKS = 30

_COUNTRY_Q = """SELECT ?country ?lang ?tld WHERE {{
  ?country wdt:P297 "{iso2}" ; wdt:P31 wd:Q6256 .
  FILTER NOT EXISTS {{ ?country wdt:P576 [] }}
  OPTIONAL {{ ?country wdt:P37 ?l . ?l wdt:P424 ?lang . }}
  OPTIONAL {{ ?country wdt:P78 ?t . ?t rdfs:label ?tld . FILTER(LANG(?tld) = "en") }}
}}"""

_GEO_Q = """SELECT DISTINCT ?label WHERE {{
  {{ BIND(wd:{qid} AS ?place) }}
  UNION {{ ?place wdt:P17 wd:{qid} ; wdt:P31/wdt:P279* wd:Q515 . }}
  UNION {{ wd:{qid} wdt:P150 ?place . }}
  {{ ?place rdfs:label ?label }} UNION {{ ?place skos:altLabel ?label }}
  UNION {{ ?place wdt:P1549 ?label }}
  FILTER(LANG(?label) IN ({langs}))
}}"""

_ORG_Q = """SELECT ?label WHERE {{
  ?org wdt:P17 wd:{qid} ; wdt:P856 [] ; rdfs:label ?label .
  FILTER(LANG(?label) IN ({langs}))
}} LIMIT {limit}"""

_KIND_PATHS = {2: "wdt:P279|wdt:P279/wdt:P279", 3: "wdt:P279|wdt:P279/wdt:P279|wdt:P279/wdt:P279/wdt:P279"}
_KINDS_Q = """SELECT ?kind ?label WHERE {{
  {{ BIND(wd:Q43229 AS ?kind) }} UNION {{ ?kind {path} wd:Q43229 . }}
  ?kind wikibase:sitelinks ?links . FILTER(?links >= {sitelinks})
  {{ ?kind rdfs:label ?label }} UNION {{ ?kind skos:altLabel ?label }}
  FILTER(LANG(?label) IN ({langs}))
}}"""

Sparql = Callable[[str], list[dict[str, str]]]


class VocabularyShape(ValueError):
    """Wikidata answered with something other than what the build measured."""


class VocabularyMissing(LookupError):
    """No committed vocabulary for this country: run build_resolver_vocabulary."""


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _in(languages: Sequence[str]) -> str:
    return ", ".join(f'"{lang}"' for lang in languages)


def build_country_doc(iso2: str, *, retrieved_on: str, sparql: Sparql = wikidata.sparql) -> dict:
    if not _ISO2.match(iso2):
        raise ValueError(f"not an ISO 3166-1 alpha-2 code: {iso2!r}")
    rows = sparql(_COUNTRY_Q.format(iso2=iso2))
    qids = {_qid(row["country"]) for row in rows if row.get("country")}
    if len(qids) != 1:
        raise VocabularyShape(f"{iso2}: {len(qids)} current countries carry this P297")
    qid = qids.pop()
    languages = list(dict.fromkeys([*sorted({r["lang"] for r in rows if r.get("lang")}), "en", "ru"]))
    tld = next((r["tld"].lstrip(".").lower() for r in rows if r.get("tld")), iso2.lower())

    geo: set[str] = set()
    for row in sparql(_GEO_Q.format(qid=qid, langs=_in(languages))):
        toks = tokens(row["label"])
        geo.update(t for t in toks if len(t) >= 3)
        if len(toks) > 1:
            geo.add("".join(toks))  # "Ha Noi" is "hanoi" in a domain label
    if not _GEO_FLOOR <= len(geo) <= _GEO_CEILING:
        raise VocabularyShape(f"{iso2}: {len(geo)} place tokens")

    labels = [
        set(tokens(row["label"]))
        for row in sparql(_ORG_Q.format(qid=qid, langs=_in(languages), limit=_ORG_LIMIT))
    ]
    if len(labels) < _ORG_FLOOR:
        raise VocabularyShape(f"{iso2}: only {len(labels)} organisation labels")
    frequency = Counter(t for toks in labels for t in toks)
    threshold = max(_GENERIC_MIN_LABELS, math.ceil(len(labels) * _GENERIC_SHARE))
    return {
        "iso2": iso2, "country_qid": qid, "cctld": tld, "languages": languages,
        "geo": sorted(geo),
        "generic": sorted(t for t, n in frequency.items() if n >= threshold),
        "organisation_labels": len(labels), "generic_threshold": threshold,
        "retrieved_on": retrieved_on, "source": wikidata.WIKIDATA_SPARQL,
        "queries": {"country": _COUNTRY_Q, "geo": _GEO_Q, "organisations": _ORG_Q},
    }


def build_kinds_doc(
    languages: Sequence[str], *, depth: int, retrieved_on: str, sparql: Sparql = wikidata.sparql
) -> dict:
    rows = sparql(_KINDS_Q.format(
        path=_KIND_PATHS[depth], sitelinks=_KIND_SITELINKS, langs=_in(sorted(languages))
    ))
    kinds: dict[str, set[str]] = {}
    for row in rows:
        toks = tokens(row["label"])
        if len(toks) == 1 and len(toks[0]) >= 3:
            kinds.setdefault(_qid(row["kind"]), set()).add(toks[0])
    if not _KINDS_FLOOR <= len(kinds) <= _KINDS_CEILING:
        raise VocabularyShape(f"{len(kinds)} kinds")
    return {
        "kinds": {qid: sorted(words) for qid, words in sorted(kinds.items())},
        "languages": sorted(languages), "depth": depth, "sitelinks_min": _KIND_SITELINKS,
        "retrieved_on": retrieved_on, "source": wikidata.WIKIDATA_SPARQL, "query": _KINDS_Q,
    }


@functools.cache
def load_vocabulary(country_code: str) -> Vocabulary:
    path = DATA_DIR / f"{country_code.upper()}.json"
    if not path.exists():
        raise VocabularyMissing(f"{path.name}: run manage.py build_resolver_vocabulary")
    country = json.loads(path.read_text("utf-8"))
    kinds_doc = json.loads((DATA_DIR / "kinds.json").read_text("utf-8"))
    stale = set(country["languages"]) - set(kinds_doc["languages"])
    if stale:
        raise VocabularyMissing(f"kinds.json lacks {sorted(stale)}: rebuild it")
    kinds: dict[str, set[str]] = {}
    for qid, words in kinds_doc["kinds"].items():
        for word in words:
            kinds.setdefault(word, set()).add(qid)
    return Vocabulary(
        country_code=country["iso2"], country_qid=country["country_qid"],
        cctld=country["cctld"], languages=tuple(country["languages"]),
        kinds={word: frozenset(qids) for word, qids in kinds.items()},
        geo=frozenset(country["geo"]), generic=frozenset(country["generic"]),
    )
```

Move the new imports to the top of the module with the existing ones (ruff will say so).

- [ ] **Step 7: The command** — `apps/research/management/commands/build_resolver_vocabulary.py`

```python
"""Build the resolver's vocabulary files from Wikidata (spec 6.5, rules 1-3).

Operator-run, free (the query service is CC0 and unauthenticated), and
deterministic enough to diff: re-running it changes a file only when
Wikidata changed. Commit what it writes; the files are the data, the
queries in them are the provenance.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.vocabulary import (
    DATA_DIR, VocabularyShape, build_country_doc, build_kinds_doc,
)


class Command(BaseCommand):
    help = "Write apps/research/resolver_data/<CC>.json and kinds.json from Wikidata."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--countries", required=True, help="comma-separated ISO2, e.g. TR,DE")
        parser.add_argument("--kind-depth", type=int, default=2, choices=(2, 3))

    def handle(self, *args: Any, **options: Any) -> None:
        today = timezone.now().date().isoformat()
        DATA_DIR.mkdir(exist_ok=True)
        try:
            for code in [c.strip().upper() for c in options["countries"].split(",") if c.strip()]:
                doc = build_country_doc(code, retrieved_on=today)
                (DATA_DIR / f"{code}.json").write_text(
                    json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
                self.stdout.write(f"{code}: {len(doc['geo'])} place tokens, "
                                  f"{len(doc['generic'])} common words over "
                                  f"{doc['organisation_labels']} names, languages {doc['languages']}")
            languages = sorted({
                lang for path in DATA_DIR.glob("[A-Z][A-Z].json")
                for lang in json.loads(path.read_text("utf-8"))["languages"]
            })
            kinds = build_kinds_doc(languages, depth=options["kind_depth"], retrieved_on=today)
        except VocabularyShape as error:
            raise CommandError(str(error)) from error
        (DATA_DIR / "kinds.json").write_text(
            json.dumps(kinds, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
        words = sum(len(w) for w in kinds["kinds"].values())
        self.stdout.write(f"kinds: {len(kinds['kinds'])} items, {words} words, {len(languages)} languages")
```

- [ ] **Step 8: Build the files, live, and read the counts**

```bash
POSTGRES_DB=tehsil_resolver uv run python manage.py build_resolver_vocabulary --countries TR,DE,AZ,GE,KZ,UZ,VN,ID
```

Expected: eight country lines and one kinds line; kinds in the tens-to-hundreds of items (spec
expects ~50 kinds that *matter*; the file holds every labelled subclass, which is a superset). If
the query service times out on `DE`'s settlement query, re-run for `DE` alone once; a second
timeout is a `CommandError` to report, not a query to hand-edit.

Then run `POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_vocabulary.py -q`. If
`test_the_committed_kinds_name_every_kind_v5_lacked` fails, re-run the command with
`--kind-depth 3` (embassy/consulate sit deeper under diplomatic mission) and re-test. Record the
depth that passed in the commit message. If depth 3 still misses a word, stop and report which —
that is a finding about Wikidata's tree, and hand-adding the word would be exactly the typed list
rule 1 forbids.

Spot-check, and paste the output into the commit message:

```bash
uv run python -c "
import json; d=json.load(open('apps/research/resolver_data/TR.json'))
print(len(d['generic']), [w for w in ('bilim','sanat','egitim','turk','vakfi','dernegi') if w in d['generic']])"
```

- [ ] **Step 9: Commit**

```bash
git add apps/research/egress.py apps/research/wikidata.py apps/research/vocabulary.py \
  apps/research/management/commands/build_resolver_vocabulary.py apps/research/resolver_data \
  tests/research/test_egress.py tests/research/test_wikidata.py tests/research/test_vocabulary.py
git commit -m "feat(research): the resolver's vocabulary as Wikidata data, not typed lists"
```

---

### Task 3: Candidate scoring — v4's tiers, the directory rule, best score ties by rank

**Files:**
- Create: `apps/research/resolver.py` (scoring half), `tests/research/test_resolver_scoring.py`

- [ ] **Step 1: Write the failing tests** — every case is a measured miss from 4.13a/4.13b

```python
"""v4's lexical tiers plus rules 1-3, pinned by the cases that were measured wrong."""

from apps.research.resolver import ranked, score_candidate
from apps.research.names import profile
from tests.research.test_names import vocab


def _best(name_or_names, urls, **overrides):
    names = [name_or_names] if isinstance(name_or_names, str) else name_or_names
    v = vocab(**overrides)
    scored = [s for s in ranked([urls], profile(names, v), v) if s.score > 0]
    return scored[0].domain if scored else ""


def test_the_best_score_wins_not_the_first_match() -> None:
    # 4.13a: zeiss.com matched one token when a better candidate matched more.
    assert _best("Carl-Zeiss-Stiftung",
                 ["https://www.zeiss.com/", "https://www.schott.com/",
                  "https://www.carl-zeiss-stiftung.de/"],
                 cctld="de") == "carl-zeiss-stiftung.de"


def test_a_kind_word_inside_a_compound_is_not_a_distinctive_match() -> None:
    # 4.13a: bund.de matched a 4-letter token inside "Bundesstiftung".
    assert _best("Bundesstiftung Magnus Hirschfeld",
                 ["https://www.bund.de/", "https://mh-stiftung.de/"], cctld="de") != "bund.de"


def test_a_place_never_forms_a_tier_two_label() -> None:
    # v2 finding 1: caritas + stuttgart was promoted as token + "one generic word".
    v = vocab(cctld="de")
    s = score_candidate("https://caritasstuttgart.de/", 0, profile(["Caritas Stiftung Stuttgart"], v), v)
    assert s is not None and s.tier == 1


def test_the_org_word_and_the_cctld_break_ties() -> None:
    # 4.13a: tema.org (a US association) over tema.org.tr on rank alone.
    assert _best("TEMA Vakfı", ["https://www.tema.org/", "https://www.tema.org.tr/"]) == "tema.org.tr"


def test_an_inflected_token_still_reaches_its_domain() -> None:
    # v4's one rescue: kanservakfi.com for Kanserle Savaş Vakfı (kanser+le).
    assert _best("Kanserle Savaş Vakfı",
                 ["https://kansersavascilari.org/", "https://www.kanservakfi.com/"]) == "kanservakfi.com"


def test_a_label_made_only_of_kind_and_place_words_is_a_directory() -> None:
    # Rule 1: embassies.info, stiftungen.de, vakiflar.gov.tr -- a structural denylist.
    v = vocab()
    p = profile(["Embassy of Italy in Astana"], v)
    for url in ("https://embassies.info/italy", "https://www.stiftungen.de/"):
        s = score_candidate(url, 0, p, v)
        assert s is not None and s.directory and s.score == 0


def test_initials_and_full_slug_are_tier_three() -> None:
    v = vocab()
    tskgv = profile(["Türk Silahlı Kuvvetlerini Güçlendirme Vakfı"], v)
    assert score_candidate("https://www.tskgv.org.tr/", 5, tskgv, v).tier == 3
    gyla = profile(["Georgian Young Lawyers' Association"], v)
    assert score_candidate("https://gyla.ge/", 2, gyla, v).tier == 3


def test_an_aggregator_or_unkeyable_host_is_never_a_candidate() -> None:
    v = vocab()
    p = profile(["Hrant Dink Vakfı"], v)
    assert score_candidate("https://www.scholars4dev.com/hrant-dink", 0, p, v) is None
    assert score_candidate("https://192.0.2.1/", 0, p, v) is None


def test_the_union_of_variant_lists_keeps_each_domain_s_best_rank() -> None:
    v = vocab()
    p = profile(["Hrant Dink Vakfı", "Hrant Dink Foundation"], v)
    order = ranked([["https://a.example.org/", "https://hrantdink.org/"],
                    ["https://hrantdink.org/en"]], p, v)
    assert [s for s in order if s.domain == "hrantdink.org"][0].rank == 0
```

Run: `POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_resolver_scoring.py -q` →
`ModuleNotFoundError: apps.research.resolver`.

- [ ] **Step 2: Create `apps/research/resolver.py` — the scoring half**

```python
"""Name -> site resolution (spec 6.5): v4's ladder with the six hold-out rules.

    rung 0  own-domain e-mail            (domains.email_domain, built)
    rung 1  Wikidata P856, exact match   (wikidata.find_item)
    rung 2  Tavily top 10 per variant -> tiered lexical score over the union
    rung 3  every pick below tier 3: the homepage title must name the same
            KIND of organisation and carry a distinctive token, the
            initials or the slug; the runner-up gets one try
    rung 4  Diffbot Enhance by name on the residue, through the same title check
    else    unresolved, with a reason (the table in the build plan)

Rank was the whole problem (12% -> 80% on the same responses, 4.13a); an
adjacent organisation is the whole residue (Carl-Zeiss-Stiftung -> zeiss.com,
Krupp -> villahuegel.de), which is why a title must agree on KIND and not just
contain a word. A failed fetch is unresolved, never accepted. Deterministic
throughout: no model call, nothing from a provider kept but a URL.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from .domains import is_catalogue
from .hosts import registrable_domain
from .names import MIN_DISTINCTIVE, NameProfile, fold, kind_of
from .vocabulary import Vocabulary

import re

_SPLIT = re.compile(r"[^a-z0-9]+")
_MIN_PIECE = 3


@dataclass(frozen=True)
class Scored:
    url: str
    domain: str
    rank: int
    tier: int
    score: float
    directory: bool


def _hit(token: str, flat: str) -> bool:
    """A distinctive token is in a label -- allowing a two-letter inflection
    on long tokens (kanserle -> kanser), the morphology v5 measured."""
    return token in flat or (len(token) >= 7 and token[:-2] in flat)


def _common_piece(piece: str, vocab: Vocabulary) -> bool:
    return bool(kind_of(piece, vocab)) or piece in vocab.geo or piece in vocab.generic


def _is_directory(flat: str, vocab: Vocabulary) -> bool:
    """Rule 1: a label that splits entirely into kind, place and common words
    names a directory, never an organisation (embassies, stiftungen, vakiflar)."""
    reachable = [False] * (len(flat) + 1)
    reachable[0] = True
    for end in range(_MIN_PIECE, len(flat) + 1):
        for start in range(0, end - _MIN_PIECE + 1):
            if reachable[start] and _common_piece(flat[start:end], vocab):
                reachable[end] = True
                break
    return reachable[len(flat)]


def _tier(flat: str, p: NameProfile, vocab: Vocabulary) -> int:
    if flat in p.slugs or flat in p.initials:
        return 3
    hits = [t for t in sorted(p.distinctive) if _hit(t, flat)]
    if len(hits) >= 2:
        return 2
    for token in hits:
        stem = token if token in flat else token[:-2]
        rest = flat.replace(stem, "", 1)
        # Token + the name's OWN org-word forms the label. Org-words only: a
        # city or a common word here was v2's one defect.
        if rest and kind_of(rest, vocab) & p.kinds:
            return 2
    if any(len(t) >= 6 for t in hits) or flat in p.distinctive:
        # "label = one token" lives here, demoted from its old promotion: it
        # fired for shared brand words (caritas.de, vakifbank, inonu.edu.tr)
        # one right against three wrong, so it is always title-gated.
        return 1
    return 0


def score_candidate(url: str, rank: int, p: NameProfile, vocab: Vocabulary) -> Scored | None:
    host = (urlsplit(url).hostname or "").lower()
    domain = registrable_domain(host) if host else ""
    if not domain or is_catalogue(host) or is_catalogue(domain):
        return None
    label, _, suffix = domain.partition(".")
    flat = "".join(t for t in _SPLIT.split(fold(label)) if t)
    tier = 3 if (flat in p.slugs or flat in p.initials) else None
    if tier is None and _is_directory(flat, vocab):
        return Scored(url, domain, rank, 0, 0.0, True)
    tier = tier if tier is not None else _tier(flat, p, vocab)
    if tier == 0:
        return Scored(url, domain, rank, 0, 0.0, False)
    score = float(tier)
    if any(w in flat for w in p.kind_words if len(w) >= MIN_DISTINCTIVE):
        score += 0.5
    if suffix.rsplit(".", 1)[-1] == vocab.cctld:
        score += 0.25
    return Scored(url, domain, rank, tier, score, False)


def ranked(lists: Sequence[Sequence[str]], p: NameProfile, vocab: Vocabulary) -> list[Scored]:
    """Every candidate from every variant's list, once per domain at its best
    rank, best score first and ties by rank (4.13a)."""
    first: dict[str, tuple[int, str]] = {}
    for results in lists:
        for rank, url in enumerate(results):
            domain = registrable_domain(url)
            if domain and (domain not in first or rank < first[domain][0]):
                first[domain] = (rank, url)
    scored = [
        s for rank, url in first.values()
        if (s := score_candidate(url, rank, p, vocab)) is not None
    ]
    return sorted(scored, key=lambda s: (-s.score, s.rank, s.domain))
```

Fix the import order so `re` sits with the standard-library imports (ruff will flag it).

- [ ] **Step 3: Run, then commit**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_resolver_scoring.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
git add apps/research/resolver.py tests/research/test_resolver_scoring.py
git commit -m "feat(research): v4's lexical tiers with the directory rule and org-word-only promotion"
```

Expected: `9 passed`. If `test_a_kind_word_inside_a_compound…` fails, `mh-stiftung.de` scored
nothing and `bund.de` scored something — print both `Scored` rows; the fix belongs in
`names.kind_of`'s compound rule, never in a special case here.

---

### Task 4: The title check

**Files:**
- Modify: `apps/research/resolver.py`
- Create: `tests/research/test_resolver_title.py`

- [ ] **Step 1: Failing tests** — the four titles 4.13a measured

```python
"""Rung 3: the homepage must name the same KIND of organisation and carry the name (4.13a, rule B)."""

from apps.research.names import profile
from apps.research.resolver import page_titles, title_agrees
from tests.research.test_names import vocab


def _html(title: str, site_name: str = "") -> bytes:
    meta = f'<meta property="og:site_name" content="{site_name}">' if site_name else ""
    return f"<html><head><title>{title}</title>{meta}</head><body>x</body></html>".encode()


def _agrees(name: str, body: bytes) -> bool:
    v = vocab()
    return title_agrees(profile([name], v), page_titles(body), v)


def test_the_right_site_names_its_kind_and_itself() -> None:
    assert _agrees("Hrant Dink Vakfı", _html("Anasayfa - Hrant Dink Vakfı"))
    assert _agrees("İnönü Vakfı", _html("İnönü Vakfı, İsmet İnönü …"))


def test_an_adjacent_organisation_of_another_kind_is_refused() -> None:
    assert not _agrees("Kanserle Savaş Vakfı", _html("Kanser Savaşçıları Derneği"))
    assert not _agrees("İnönü Vakfı", _html("İnönü Üniversitesi"))
    assert not _agrees("Carl-Zeiss-Stiftung", _html("Solutions to shape the future | ZEISS"))


def test_og_site_name_counts_and_a_page_without_either_says_nothing() -> None:
    assert _agrees("Hrant Dink Vakfı", _html("Home", site_name="Hrant Dink Vakfı"))
    assert page_titles(b"") == ()
    assert page_titles(b"<html><body>no head</body></html>") == ()
```

- [ ] **Step 2: Implement** — append to `apps/research/resolver.py`

```python
import lxml.html
from lxml import etree

from .names import tokens


def page_titles(body: bytes) -> tuple[str, ...]:
    """The page's own <title> and og:site_name -- origin bytes, read and dropped."""
    if not body.strip():
        return ()
    try:
        tree = lxml.html.fromstring(body.decode("utf-8", errors="replace"))
    except (etree.ParserError, ValueError):
        return ()
    found = []
    title = tree.findtext(".//title")
    if title:
        found.append(" ".join(title.split()))
    for meta in tree.iter("meta"):
        if (meta.get("property") or "").casefold() == "og:site_name" and meta.get("content"):
            found.append(" ".join(meta.get("content", "").split()))
    return tuple(t for t in found if t)


def title_agrees(p: NameProfile, titles: Sequence[str], vocab: Vocabulary) -> bool:
    """(a) the title names a kind the name names, and (b) it carries a
    distinctive token, the initials or the slug. (a) is what separates an
    adjacent body sharing a word -- "Kanser Savaşçıları" (Derneği) for
    Kanserle Savaş Vakfı -- and a name with no kind word never passes it,
    which is why one-token names never reach this check."""
    title_tokens = [t for title in titles for t in tokens(title)]
    title_kinds = {kind for t in title_tokens for kind in kind_of(t, vocab)}
    if not p.kinds & title_kinds:
        return False
    flat = "".join(title_tokens)
    return (
        any(_hit(t, flat) for t in p.distinctive)
        or any(i in title_tokens for i in p.initials)
        or any(s in flat for s in p.slugs)
    )
```

(move the imports to the top.) Run the three tests → `3 passed`. Commit:
`feat(research): the title check -- kind agreement plus a distinctive token`.

- [ ] **Step 3: Measure whether Firecrawl's `html` keeps `<head>` — 3 credits, before Task 7 relies on it**

`fetch_page` hands back Firecrawl's `html` format (CLAUDE.md, "Web fetching"). Whether that
processed HTML still carries `<head><title>` has not been recorded. Probe three known homepages:

```bash
FIRECRAWL_API_KEY=... POSTGRES_DB=tehsil_resolver DATABASE_ROLE=migration uv run python manage.py shell -c "
from apps.research.fetch import fetch_page
from apps.research.resolver import page_titles
for url in ('https://www.hrantdink.org/', 'https://www.tev.org.tr/', 'https://www.cusanuswerk.de/'):
    p = fetch_page(url, purpose='read', tag='resolver-title-probe')
    print(url, p.outcome, p.fetched_via, page_titles(p.body))"
```

If every row prints a non-empty title: done, note it in the Task 7 commit. **If Firecrawl rows
print `()` while the page plainly has a title**, the processed HTML dropped `<head>`: in
`apps/research/fetch/firecrawl.py`, where `metadata` is read (the `site_status`/`final_url`
block), prepend the vendor-reported title to the body for `page_titles` to find —

```python
    title = str(metadata.get("title") or "")
    if title and b"<title" not in html[:4096].lower():
        html = f"<title>{escape(title)}</title>".encode() + html
```

(`from html import escape`), with a test in `tests/research/test_fetch_firecrawl.py` asserting a
response with `metadata.title` and a head-less `html` yields a body whose `page_titles` is that
title. Re-run the probe; record both runs in the commit message.

---

### Task 5: Diffbot Enhance — a URL and nothing else

**Files:**
- Create: `apps/research/providers/diffbot.py`, `tests/research/test_diffbot.py`,
  `tests/research/fixtures/diffbot_enhance_gyla.json` (captured live, Step 4)
- Modify: `config/settings/base.py`

- [ ] **Step 1: Settings** — after `EXA_API_KEY` in `config/settings/base.py`:

```python
#: Diffbot Knowledge Graph: Enhance by name is the resolver's residue step
#: (spec 6.5; 7/10 on the syllabic-acronym and Georgian-script names no lexical
#: rule reaches). Its terms carry an explicit commercial grant and NO effective
#: date, so they are re-read before use: resolve_register refuses the rung
#: unless DIFFBOT_TERMS_READ_ON (ISO date) is within 31 days.
DIFFBOT_TOKEN = os.getenv("DIFFBOT_TOKEN", "")
DIFFBOT_TERMS_READ_ON = os.getenv("DIFFBOT_TERMS_READ_ON", "")
#: The free tier: 10,000 credits a month at 25 per entity (spec 13).
DIFFBOT_MONTHLY_ENTITIES = int(os.getenv("DIFFBOT_MONTHLY_ENTITIES", "400"))
#: One Tavily basic search is one credit; a name costs up to three (one per variant).
RESOLVER_TAVILY_CREDITS_PER_RUN = int(os.getenv("RESOLVER_TAVILY_CREDITS_PER_RUN", "100"))
#: Off until the fresh-script hold-out passes (build item 8 plan, Task 12).
RESOLVER_WRITES_ENABLED = os.getenv("RESOLVER_WRITES_ENABLED", "") == "1"
```

- [ ] **Step 2: Failing tests** (`tests/research/test_diffbot.py`)

```python
"""Diffbot Enhance on the residue: one URL out, the token never in an error."""

import json
from pathlib import Path

import pytest

from apps.research.egress import SourceBlocked
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.diffbot import DiffbotEnhance

FIXTURE = Path(__file__).parent / "fixtures" / "diffbot_enhance_gyla.json"


def test_only_the_homepage_is_read_from_a_real_response() -> None:
    captured = json.loads(FIXTURE.read_text("utf-8"))
    enhance = DiffbotEnhance(token="t", get=lambda *a, **k: captured, sleep=lambda s: None)
    assert enhance.homepage("Georgian Young Lawyers' Association") in {
        "https://gyla.ge", "https://www.gyla.ge", "https://gyla.ge/", "https://www.gyla.ge/"}


def test_no_entity_is_an_empty_answer_not_an_error() -> None:
    enhance = DiffbotEnhance(token="t", get=lambda *a, **k: {"data": []}, sleep=lambda s: None)
    assert enhance.homepage("Stiftung Gustav Werner und Haus am Berg") == ""


def test_the_token_never_reaches_an_exception() -> None:
    def failing(url, *, params, headers, **_):
        raise SourceBlocked(f"MaxRetryError: /kg/v3/enhance?token={params['token']}")

    enhance = DiffbotEnhance(token="secret-token", get=failing, sleep=lambda s: None)
    with pytest.raises(ProviderUnavailable) as raised:
        enhance.homepage("x")
    assert "secret-token" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


def test_calls_are_paced_to_the_free_tier() -> None:
    slept = []
    enhance = DiffbotEnhance(token="t", get=lambda *a, **k: {"data": []},
                             sleep=slept.append, clock=iter([0.0, 1.0]).__next__)
    enhance.homepage("a")
    enhance.homepage("b")
    assert slept == [pytest.approx(11.0)]
```

- [ ] **Step 3: Implement** `apps/research/providers/diffbot.py`

```python
"""Diffbot Knowledge Graph Enhance -- the resolver's residue rung (spec 6.5).

A resolver, never a classifier and never an enumerator: its categories are
wrong (Cusanuswerk -> "Software Companies") and its confidence runs 0.16-0.54
even when right, so its answer is one URL that takes the same title check as
any search candidate. Nothing else in the response is read or kept --
the confidence included; spec 15's "Diffbot confidence threshold on the next
50" is measured by the gate, not stored on a row.

The token travels as a query parameter, so an exception raised under it is
re-raised without its cause: urllib3 errors print the request path.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..egress import SourceBlocked, fetch_json_api
from .base import ProviderUnavailable

DIFFBOT_ENHANCE_URL = "https://kg.diffbot.com/kg/v3/enhance"
#: Free tier: 5 calls a minute.
_MIN_INTERVAL = 12.0


class DiffbotEnhance:
    def __init__(
        self,
        *,
        token: str,
        get: Callable[..., dict[str, object]] = fetch_json_api,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._token, self._get, self._sleep, self._clock = token, get, sleep, clock
        self._last: float | None = None

    def __repr__(self) -> str:
        return "DiffbotEnhance(token=***)"

    def homepage(self, name: str) -> str:
        now = self._clock()
        if self._last is not None and now - self._last < _MIN_INTERVAL:
            self._sleep(_MIN_INTERVAL - (now - self._last))
        self._last = now
        try:
            data = self._get(DIFFBOT_ENHANCE_URL, params={
                "token": self._token, "type": "Organization", "name": name,
            }, headers={})
        except SourceBlocked:
            raise ProviderUnavailable("diffbot enhance failed") from None
        for item in data.get("data") or []:  # type: ignore[union-attr]
            entity = item.get("entity") if isinstance(item, dict) else None
            uri = str((entity or {}).get("homepageUri") or "")
            if uri:
                return uri if "//" in uri else f"https://{uri}"
        return ""
```

- [ ] **Step 4: Capture the fixture live — 25 Diffbot credits — and pin the shape**

Read `https://www.diffbot.com/company/terms/` first and write today's date into your shell as
`DIFFBOT_TERMS_READ_ON`; the terms carry no effective date (spec 6.2), so the read is the check.

```bash
DIFFBOT_TOKEN=... uv run python -c "
import json, os
from apps.research.egress import fetch_json_api
d = fetch_json_api('https://kg.diffbot.com/kg/v3/enhance', params={'token': os.environ['DIFFBOT_TOKEN'], 'type': 'Organization', 'name': \"Georgian Young Lawyers' Association\"}, headers={})
keep = {'data': [{'entity': {'homepageUri': i.get('entity', {}).get('homepageUri'), 'name': i.get('entity', {}).get('name')}} for i in d.get('data', [])[:1]]}
print(json.dumps(keep, ensure_ascii=False, indent=1))" > tests/research/fixtures/diffbot_enhance_gyla.json
grep -c token tests/research/fixtures/diffbot_enhance_gyla.json   # expect 0
```

The fixture keeps the two keys the adapter reads, from the real response — not the full entity.
If the live response has no `data[].entity.homepageUri` (the shape changed since 2026-09-18),
change `homepage()`'s loop to the key the capture shows, and say so in the commit. Run
`POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_diffbot.py -q` → `4 passed`.

- [ ] **Step 5: Commit** — `feat(research): Diffbot Enhance adapter -- a homepage URL and nothing else`

---

### Task 6: The names store and the resolution record on `RegisterEntry`

**Files:**
- Modify: `apps/research/models.py`, `apps/research/vgm.py`, `tests/research/test_vgm.py`
- Create: `apps/research/migrations/<next>_register_entry_resolution.py`,
  `tests/research/test_register_entry_resolution_rls.py`

- [ ] **Step 1: Failing tests**

Append to `tests/research/test_vgm.py`:

```python
def test_rung_zero_records_how_it_resolved_and_the_register_s_name() -> None:
    from apps.research.vgm import record_vgm

    record_vgm([VgmRow(name="TÜRK EĞİTİM VAKFI", city="Ankara", notification_id="1",
                       email="info@tev.org.tr"),
                VgmRow(name="BİLİM VE SANAT VAKFI", city="İstanbul", notification_id="2",
                       email="bisav@gmail.com")],
               now=datetime(2026, 9, 25, tzinfo=UTC))
    resolved = RegisterEntry.objects.get(external_key="1")
    unresolved = RegisterEntry.objects.get(external_key="2")
    assert resolved.resolved_via == "EMAIL" and resolved.names == ["TÜRK EĞİTİM VAKFI"]
    assert unresolved.resolved_via == "" and unresolved.unresolved_reason == ""
    assert unresolved.names == ["BİLİM VE SANAT VAKFI"]


def test_a_resolved_row_carries_no_reason_and_an_unresolved_one_no_route() -> None:
    with pytest.raises(IntegrityError):
        RegisterEntry.objects.create(
            register="vgm_tr", external_key="x", name="n", last_seen=timezone.now(),
            resolution=RegisterEntry.Resolution.RESOLVED, resolved_via="",
        )
```

`tests/research/test_register_entry_resolution_rls.py`:

```python
"""The resolver writes RegisterEntry; the runtime role must not be able to.

Through `runtime_connection` because the test role bypasses RLS (CLAUDE.md).
An UPDATE the policy refuses does not raise -- it matches zero rows -- which is
exactly why resolve_entries.record_resolution checks its row count.
"""

import pytest
from django.db import connection
from django.utils import timezone
from psycopg import sql

from apps.research.models import RegisterEntry


@pytest.mark.django_db(transaction=True)
def test_the_runtime_role_updates_nothing(runtime_connection) -> None:
    RegisterEntry.objects.create(
        register="vgm_tr", external_key="k", name="BİLİM VE SANAT VAKFI",
        resolution=RegisterEntry.Resolution.UNRESOLVED, last_seen=timezone.now(),
    )
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("GRANT UPDATE ON TABLE {} TO {}").format(
            sql.Identifier("public", "research_registerentry"), role))
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM research_registerentry")
        assert cursor.fetchone()[0] == 1, "the policy must still let every tenant read"
        cursor.execute(
            "UPDATE research_registerentry SET unresolved_reason = 'NO_CANDIDATE', "
            "names = ARRAY['x'] WHERE external_key = 'k'")
        assert cursor.rowcount == 0
```

Run both → fail (`resolved_via` unknown field).

- [ ] **Step 2: Models** — in `apps/research/models.py`, above `class RegisterEntry`:

```python
class ResolvedVia(models.TextChoices):
    """Which rung bound the host (spec 6.5). HUMAN is written by the resolution
    queue (item 12), never by the resolver."""

    EMAIL = "EMAIL"
    WIKIDATA = "WIKIDATA"
    #: Initials or full slug (tier 3): shipped without a title check, measured
    #: to save reachable-by-nobody true sites (tskgv.org.tr, ttgv.org.tr).
    SEARCH_SLUG = "SEARCH_SLUG"
    SEARCH_TITLE = "SEARCH_TITLE"
    DIFFBOT = "DIFFBOT"
    HUMAN = "HUMAN"


class UnresolvedReason(models.TextChoices):
    """Why a name stayed unresolved -- the build plan's table. "" = never tried."""

    ONE_TOKEN_NAME = "ONE_TOKEN_NAME"
    NO_CANDIDATE = "NO_CANDIDATE"
    DIRECTORY = "DIRECTORY"
    TITLE_MISMATCH = "TITLE_MISMATCH"
    FETCH_FAILED = "FETCH_FAILED"
    IDENTIFIER_CONFLICT = "IDENTIFIER_CONFLICT"
```

In `RegisterEntry`, after `contact_domain`:

```python
    #: The names store (spec 6.1/6.5 rule 4): the register's own name first, then
    #: every variant Wikidata supplies once the name matched one item. Scored as a
    #: union; never a lookup key. Carried onto Organisation.names on resolution.
    names = ArrayField(models.CharField(max_length=300), default=list, blank=True)
    resolved_via = models.CharField(
        max_length=12, choices=ResolvedVia.choices, blank=True, default=""
    )
    unresolved_reason = models.CharField(
        max_length=20, choices=UnresolvedReason.choices, blank=True, default=""
    )
    resolution_attempted_at = models.DateTimeField(null=True, blank=True)
    #: Diffbot is 25 credits an entity against 400 a month; this column is both
    #: the monthly meter and the "never ask twice in 90 days" rule.
    diffbot_asked_at = models.DateTimeField(null=True, blank=True)
```

and in its `Meta.constraints` add:

```python
            models.CheckConstraint(
                condition=(
                    Q(resolution="RESOLVED", unresolved_reason="") & ~Q(resolved_via="")
                ) | Q(resolution="UNRESOLVED", resolved_via=""),
                name="register_entry_resolution_shape",
            ),
```

- [ ] **Step 3: Migration** — find the leaf, generate, then insert the backfill before the constraint

```bash
ls apps/research/migrations/ | sort | tail -2
POSTGRES_DB=tehsil_resolver uv run python manage.py makemigrations research --name register_entry_resolution
```

If `makemigrations` reports conflicting leaves, run
`POSTGRES_DB=tehsil_resolver uv run python manage.py makemigrations --merge research` first and
commit the merge migration separately. Open the generated file and insert, **after the five
`AddField`s and before the `AddConstraint`**:

```python
        # Rows written by rung 0 before this column existed resolved by e-mail
        # (vgm.record_vgm is the only writer). Plain SQL: research tables are
        # ENABLE, not FORCE, row-level security, so the migrating owner is not
        # filtered -- and a RunPython would drag the ORM's manager in for nothing.
        migrations.RunSQL(
            "UPDATE research_registerentry SET resolved_via = 'EMAIL' "
            "WHERE resolution = 'RESOLVED' AND resolved_via = '';"
            "UPDATE research_registerentry SET names = ARRAY[name] WHERE names = '{}';",
            reverse_sql=migrations.RunSQL.noop,
        ),
```

Add a module docstring stating: no new table; the columns inherit research/0007's two policies;
verified by `test_register_entry_resolution_rls.py` through `runtime_connection`.

- [ ] **Step 4: `vgm.record_vgm` — rung 0 records its route, and a re-read never undoes the resolver**

Today every re-read of VGM rewrites `resolution` from the e-mail alone, so a monthly re-read would
turn every row the resolver bound back into `UNRESOLVED`. First, the failing test (append to
`tests/research/test_vgm.py`):

```python
def test_a_re_read_never_unresolves_what_the_resolver_bound() -> None:
    from apps.research.vgm import record_vgm

    row = VgmRow(name="BİLİM VE SANAT VAKFI", city="İstanbul", notification_id="2",
                 email="bisav@gmail.com")
    record_vgm([row], now=datetime(2026, 9, 25, tzinfo=UTC))
    org = record_organisation(domain="bisav.org.tr", name=row.name, kind="PRIVATE_FOUNDATION",
                              country_code="TR", found_via="RESOLVER:DIFFBOT")
    RegisterEntry.objects.filter(external_key="2").update(
        resolution="RESOLVED", resolved_via="DIFFBOT", organisation=org,
        names=[row.name, "Science and Art Foundation"])
    record_vgm([row], now=datetime(2026, 10, 25, tzinfo=UTC))
    entry = RegisterEntry.objects.get(external_key="2")
    assert (entry.resolution, entry.resolved_via, entry.organisation_id) == ("RESOLVED", "DIFFBOT", org.id)
    assert entry.names == [row.name, "Science and Art Foundation"]
```

Then replace the `update_or_create` call in `record_vgm` with defaults that only rung 0's own
answer may overwrite, and create-only defaults for the rest (`create_defaults`, Django ≥ 5.0):

```python
            refreshed: dict[str, object] = {
                "name": row.name, "city": row.city, "contact_domain": domain, "last_seen": now,
            }
            if domain:
                # The register's own e-mail is stronger evidence than any search:
                # it overwrites whatever the resolver found.
                refreshed |= {
                    "resolution": RegisterEntry.Resolution.RESOLVED,
                    "resolved_via": ResolvedVia.EMAIL, "unresolved_reason": "",
                }
            entry, _ = RegisterEntry.objects.update_or_create(
                register=REGISTER,
                external_key=external_key,
                defaults=refreshed,
                create_defaults={
                    **refreshed,
                    "names": [row.name],
                    "resolution": (
                        RegisterEntry.Resolution.RESOLVED if domain
                        else RegisterEntry.Resolution.UNRESOLVED
                    ),
                    "resolved_via": ResolvedVia.EMAIL if domain else "",
                },
            )
```

(import `ResolvedVia` from `.models`). The `if not domain: unresolved += 1; continue` that follows
is unchanged — `LadderReport.unresolved` stays "rung 0 did not resolve it", and
`register_coverage` reads the table, so it counts the resolver's work.

- [ ] **Step 5: Run and commit**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_vgm.py tests/research/test_register_entry_resolution_rls.py tests/tenancy/test_database_isolation.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
POSTGRES_DB=tehsil_resolver uv run python manage.py makemigrations --check --dry-run
git add apps/research/models.py apps/research/migrations apps/research/vgm.py tests/research/test_vgm.py tests/research/test_register_entry_resolution_rls.py
git commit -m "feat(research): RegisterEntry carries the names store and why a name stayed unresolved"
```

---

### Task 7: The `Resolver` — rungs 0–4 and the budgets

**Files:**
- Modify: `apps/research/resolver.py`
- Create: `tests/research/test_resolver.py`

- [ ] **Step 1: Failing tests**

```python
"""The ladder end to end on fakes: every rung, every reason, both budgets."""

from dataclasses import fields

import pytest

from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.resolver import (
    CallBudget, CallBudgetSpent, FetchBudgetSpent, NameQuery, Resolution, Resolver,
)
from apps.research.wikidata import WikidataMatch
from tests.research.test_names import vocab


def page(url: str, title: str, outcome=Outcome.FETCHED) -> FetchedPage:
    body = f"<html><head><title>{title}</title></head></html>".encode()
    return FetchedPage(final_url=url, redirects=(), content_type="text/html", body=body,
                       fetched_via="FIRECRAWL", outcome=outcome)


def resolver(*, lists=None, titles=None, wikidata=None, diffbot=None, tavily=10, **kw):
    fetched: list[str] = []

    def fetch(url, **_):
        fetched.append(url)
        title = (titles or {}).get(url)
        if title is None:
            return page(url, "", Outcome.UNREACHABLE)
        if title == "BUDGET":
            return page(url, "", Outcome.BUDGET)
        return page(url, title)

    r = Resolver(vocabulary=vocab(), candidates=lambda name: (lists or {}).get(name, []),
                 tavily=CallBudget(tavily), fetch=fetch, wikidata=wikidata, diffbot=diffbot, **kw)
    return r, fetched


def test_rung_zero_answers_before_any_call() -> None:
    r, fetched = resolver(tavily=0)
    got = r.resolve(NameQuery(("TÜRK EĞİTİM VAKFI",), "TR", contact_email="info@tev.org.tr"))
    assert (got.domain, got.via) == ("tev.org.tr", "EMAIL") and not fetched


def test_wikidata_s_website_is_taken_and_its_labels_join_the_names() -> None:
    match = WikidataMatch("Q1", ("https://www.hrantdink.org/",), ("Hrant Dink Vakfı", "Hrant Dink Foundation"))
    r, _ = resolver(wikidata=lambda names: match, tavily=0)
    got = r.resolve(NameQuery(("Hrant Dink Vakfı",), "TR"))
    assert (got.domain, got.via, got.wikidata_qid) == ("hrantdink.org", "WIKIDATA", "Q1")
    assert got.names == ("Hrant Dink Vakfı", "Hrant Dink Foundation")


def test_a_one_token_name_never_spends_a_search() -> None:
    r, _ = resolver(tavily=0)
    assert r.resolve(NameQuery(("TEMA",), "TR")).reason == "ONE_TOKEN_NAME"


def test_tier_three_ships_without_a_fetch() -> None:
    r, fetched = resolver(lists={"Türk Silahlı Kuvvetlerini Güçlendirme Vakfı": ["https://www.tskgv.org.tr/"]})
    got = r.resolve(NameQuery(("Türk Silahlı Kuvvetlerini Güçlendirme Vakfı",), "TR"))
    assert (got.domain, got.via) == ("tskgv.org.tr", "SEARCH_SLUG") and not fetched


def test_the_best_candidate_is_checked_first() -> None:
    # v4's one rescue: kanservakfi.com (2.5) outscores kansersavascilari.org (2.0).
    name = "Kanserle Savaş Vakfı"
    r, fetched = resolver(
        lists={name: ["https://kansersavascilari.org/", "https://www.kanservakfi.com/"]},
        titles={"https://www.kanservakfi.com/": "Kanser Vakfı - Kanserle Savaş Vakfı",
                "https://kansersavascilari.org/": "Kanser Savaşçıları Derneği"},
    )
    got = r.resolve(NameQuery((name,), "TR"))
    assert (got.domain, got.via) == ("kanservakfi.com", "SEARCH_TITLE")
    assert fetched == ["https://www.kanservakfi.com/"]


def test_the_runner_up_gets_one_try_after_a_title_mismatch() -> None:
    # Both tier 2 at 2.0; rank breaks the tie, so the association's site is
    # checked first and refused on kind (Derneği against Vakfı).
    name = "Hrant Dink Vakfı"
    r, fetched = resolver(
        lists={name: ["https://hrant-dink-dernegi.org/", "https://www.hrantdink.org/"]},
        titles={"https://hrant-dink-dernegi.org/": "Hrant Dink Derneği",
                "https://www.hrantdink.org/": "Anasayfa - Hrant Dink Vakfı"},
    )
    got = r.resolve(NameQuery((name,), "TR"))
    assert (got.domain, got.via) == ("hrantdink.org", "SEARCH_TITLE")
    assert fetched == ["https://hrant-dink-dernegi.org/", "https://www.hrantdink.org/"]


def test_a_failed_fetch_is_unresolved_never_accepted() -> None:
    # hrantdink.org is tier 2 (two distinctive tokens), so it must be fetched;
    # a tier-3 label (hrantdinkvakfi = the slug) would ship unverified instead.
    r, _ = resolver(lists={"Hrant Dink Vakfı": ["https://hrantdink.org/"]})
    assert r.resolve(NameQuery(("Hrant Dink Vakfı",), "TR")).reason == "FETCH_FAILED"


def test_a_redirect_to_another_domain_is_another_body_s_title() -> None:
    name = "Hrant Dink Vakfı"
    r, _ = resolver(lists={name: ["https://hrantdink.org/"]})
    r.fetch = lambda url, **_: page("https://www.agos.com.tr/", "Hrant Dink Vakfı")
    assert r.resolve(NameQuery((name,), "TR")).reason == "TITLE_MISMATCH"


def test_diffbot_answers_the_residue_through_the_same_title_check() -> None:
    name = "Bilim ve Sanat Vakfı"
    r, _ = resolver(lists={name: []}, diffbot=lambda n: "https://www.bisav.org.tr",
                    titles={"https://www.bisav.org.tr/": "BİSAV - Bilim ve Sanat Vakfı"})
    got = r.resolve(NameQuery((name,), "TR"))
    assert (got.domain, got.via, got.diffbot_asked) == ("bisav.org.tr", "DIFFBOT", True)


def test_a_query_may_forbid_diffbot() -> None:
    asked = []
    r, _ = resolver(lists={"Bilim ve Sanat Vakfı": []}, diffbot=lambda n: asked.append(n) or "")
    got = r.resolve(NameQuery(("Bilim ve Sanat Vakfı",), "TR", allow_diffbot=False))
    assert got.reason == "NO_CANDIDATE" and not asked and not got.diffbot_asked


def test_a_directory_only_answer_says_so() -> None:
    name = "Embassy of Italy in Astana"
    r, _ = resolver(lists={name: ["https://embassies.info/italy-astana"]})
    assert r.resolve(NameQuery((name,), "KZ")).reason == "DIRECTORY"


def test_budgets_stop_the_run_instead_of_writing_a_reason() -> None:
    r, _ = resolver(lists={"Hrant Dink Vakfı": []}, tavily=0)
    with pytest.raises(CallBudgetSpent):
        r.resolve(NameQuery(("Hrant Dink Vakfı",), "TR"))
    r, _ = resolver(lists={"Hrant Dink Vakfı": ["https://hrantdink.org/"]},
                    titles={"https://hrantdink.org/": "BUDGET"})
    with pytest.raises(FetchBudgetSpent):
        r.resolve(NameQuery(("Hrant Dink Vakfı",), "TR"))


def test_a_resolution_has_no_field_a_provider_artefact_could_travel_in() -> None:
    """Only a URL is read from a provider, and only a registrable domain leaves."""
    assert {f.name for f in fields(Resolution)} == {
        "domain", "via", "reason", "wikidata_qid", "names", "diffbot_asked"}
```

- [ ] **Step 2: Implement** — append to `apps/research/resolver.py`

```python
from collections.abc import Callable
from dataclasses import dataclass, field

from .classify import _USABLE
from .domains import email_domain
from .fetch import SweepBudget, fetch_page
from .fetch.types import FetchedPage, Outcome
from .models import ResolvedVia, UnresolvedReason
from .names import profile
from .providers.base import ProviderUnavailable
from .wikidata import WikidataMatch

#: Names searched per entity -- native, English, Russian at most (rule 4).
_MAX_QUERY_VARIANTS = 3
#: Reasons the residue rung may still turn around. FETCH_FAILED is retried by
#: the fetch path first; ONE_TOKEN_NAME can never pass a kind check.
_DIFFBOT_REASONS = frozenset({
    UnresolvedReason.NO_CANDIDATE, UnresolvedReason.DIRECTORY, UnresolvedReason.TITLE_MISMATCH,
})


class CallBudgetSpent(RuntimeError):
    """A per-run provider cap ran out. The run stops; nothing is written."""


class FetchBudgetSpent(RuntimeError):
    """The sweep's fetch budget ran out mid-name. The run stops; nothing is written."""


@dataclass
class CallBudget:
    limit: int
    spent: int = 0

    def spend(self) -> None:
        if self.spent >= self.limit:
            raise CallBudgetSpent(f"{self.spent} of {self.limit} calls spent")
        self.spent += 1


@dataclass(frozen=True)
class NameQuery:
    names: tuple[str, ...]
    country_code: str
    contact_email: str = ""
    allow_diffbot: bool = True

    def __post_init__(self) -> None:
        if not any(name.strip() for name in self.names):
            raise ValueError("a NameQuery needs at least one name")


@dataclass(frozen=True)
class Resolution:
    domain: str = ""
    via: str = ""
    reason: str = ""
    wikidata_qid: str = ""
    names: tuple[str, ...] = ()
    diffbot_asked: bool = False


@dataclass(frozen=True)
class _Found:
    domain: str = ""
    via: str = ""
    reason: str = ""


def _distinct(names: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for name in names:
        if name.strip():
            seen.setdefault(fold(name), name.strip())
    return tuple(seen.values())


@dataclass
class Resolver:
    vocabulary: Vocabulary
    candidates: Callable[[str], Sequence[str]]
    tavily: CallBudget
    fetch: Callable[..., FetchedPage] = fetch_page
    budget: SweepBudget | None = None
    wikidata: Callable[[Sequence[str]], WikidataMatch | None] | None = None
    #: The gate turns this off: its truth IS Wikidata's P856.
    use_wikidata_website: bool = True
    diffbot: Callable[[str], str] | None = None
    _titles_by_host: dict[str, tuple[str, ...] | None] = field(default_factory=dict, repr=False)

    def resolve(self, query: NameQuery) -> Resolution:
        names = _distinct(query.names)
        if query.contact_email:
            domain = email_domain(query.contact_email)
            if domain:
                return Resolution(domain=domain, via=ResolvedVia.EMAIL, names=names)
        qid = ""
        if self.wikidata is not None:
            match = self.wikidata(names)
            if match is not None:
                qid, names = match.qid, _distinct((*names, *match.labels))
                if self.use_wikidata_website:
                    domain = next((d for url in match.websites
                                   if (d := registrable_domain(url)) and not is_catalogue(d)), "")
                    if domain:
                        return Resolution(domain, ResolvedVia.WIKIDATA, "", qid, names)
        p = profile(names, self.vocabulary)
        found = self._search(names, p)
        asked = False
        if (not found.domain and found.reason in _DIFFBOT_REASONS
                and self.diffbot is not None and query.allow_diffbot):
            asked, found = self._residue(names, p, found)
        return Resolution(found.domain, found.via, found.reason, qid, names, asked)

    def _search(self, names: tuple[str, ...], p: NameProfile) -> _Found:
        if p.one_token:
            return _Found(reason=UnresolvedReason.ONE_TOKEN_NAME)
        lists: list[Sequence[str]] = []
        for variant in names[:_MAX_QUERY_VARIANTS]:
            self.tavily.spend()
            lists.append(list(self.candidates(variant)))
        scored = ranked(lists, p, self.vocabulary)
        viable = [s for s in scored if s.score > 0]
        if not viable:
            directory = any(s.directory for s in scored)
            return _Found(reason=UnresolvedReason.DIRECTORY if directory
                          else UnresolvedReason.NO_CANDIDATE)
        if viable[0].tier == 3:
            return _Found(viable[0].domain, ResolvedVia.SEARCH_SLUG)
        return self._verify(viable[:2], p, ResolvedVia.SEARCH_TITLE)

    def _residue(self, names: tuple[str, ...], p: NameProfile, found: _Found) -> tuple[bool, _Found]:
        try:
            url = self.diffbot(names[0]) if self.diffbot else ""
        except CallBudgetSpent:
            return False, found
        except ProviderUnavailable:
            return True, found
        domain = registrable_domain(url) if url else ""
        if not domain or is_catalogue(domain):
            return True, found
        verified = self._verify([Scored(url, domain, 0, 0, 0.0, False)], p, ResolvedVia.DIFFBOT)
        if verified.domain or verified.reason == UnresolvedReason.FETCH_FAILED:
            return True, verified
        return True, found

    def _verify(self, candidates: Sequence[Scored], p: NameProfile, via: str) -> _Found:
        reasons: list[str] = []
        for s in candidates:
            titles = self._titles(s)
            if titles is None:
                reasons.append(UnresolvedReason.FETCH_FAILED)
            elif title_agrees(p, titles, self.vocabulary):
                return _Found(s.domain, via)
            else:
                reasons.append(UnresolvedReason.TITLE_MISMATCH)
        if UnresolvedReason.FETCH_FAILED in reasons:
            return _Found(reason=UnresolvedReason.FETCH_FAILED)
        return _Found(reason=UnresolvedReason.TITLE_MISMATCH)

    def _titles(self, s: Scored) -> tuple[str, ...] | None:
        """None = could not look; () = looked and it names nothing (or is elsewhere)."""
        host = (urlsplit(s.url).hostname or s.domain).lower()
        if host in self._titles_by_host:
            return self._titles_by_host[host]
        fetched = self.fetch(f"https://{host}/", purpose="read", tag="resolver-title",
                             budget=self.budget)
        if fetched.outcome == Outcome.BUDGET:
            raise FetchBudgetSpent(fetched.reason or "fetch budget spent")
        if fetched.outcome not in _USABLE:
            titles: tuple[str, ...] | None = None
        elif registrable_domain(fetched.final_url) != s.domain:
            titles = ()  # it landed on another body's site; its title is that body's
        else:
            titles = page_titles(fetched.body)
        self._titles_by_host[host] = titles
        return titles
```

Hoist all imports to the top; check `ruff` and `mypy`. Note the test that swaps `r.fetch` after
construction: the per-host title cache is empty at that point, so the swapped fetch is used.

- [ ] **Step 3: Run and commit**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_resolver.py tests/research/test_resolver_scoring.py tests/research/test_resolver_title.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
git add apps/research/resolver.py tests/research/test_resolver.py
git commit -m "feat(research): the resolver ladder -- e-mail, Wikidata, search, title, Diffbot, reason"
```

Expected: all pass. The Task 4 Step 3 probe result goes in this commit message.

---

### Task 8: Writing a resolution — `resolve_entries.py`

**Files:**
- Create: `apps/research/resolve_entries.py`, `tests/research/test_resolve_entries.py`

- [ ] **Step 1: Failing tests**

```python
"""A resolution becomes a CANDIDATE organisation, or a reason. Never a guess."""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.research.models import Organisation, OrganisationIdentifier, RegisterEntry
from apps.research.register import record_organisation
from apps.research.resolve_entries import (
    CatalogWriteRefused, RegisterSpec, due_entries, record_resolution,
)
from apps.research.resolver import Resolution

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 25, tzinfo=UTC)
SPEC = RegisterSpec(country_code="TR", kind="PRIVATE_FOUNDATION")


def entry(key="k", **overrides) -> RegisterEntry:
    fields = dict(register="vgm_tr", external_key=key, name="HRANT DİNK VAKFI",
                  names=["HRANT DİNK VAKFI"], resolution=RegisterEntry.Resolution.UNRESOLVED,
                  last_seen=timezone.now())
    fields.update(overrides)
    return RegisterEntry.objects.create(**fields)


def test_a_resolution_writes_a_candidate_with_every_name_and_the_wikidata_id() -> None:
    e = entry()
    record_resolution(e, Resolution("hrantdink.org", "WIKIDATA", "", "Q1",
                                    ("HRANT DİNK VAKFI", "Hrant Dink Foundation")), spec=SPEC, now=NOW)
    e.refresh_from_db()
    org = e.organisation
    assert (e.resolution, e.resolved_via, e.unresolved_reason) == ("RESOLVED", "WIKIDATA", "")
    assert org.status == Organisation.Status.CANDIDATE     # the register vouched the body, not the domain
    assert org.found_via == ["RESOLVER:WIKIDATA"]
    assert "Hrant Dink Foundation" in org.names
    assert OrganisationIdentifier.objects.get(scheme="WIKIDATA").value == "Q1"


def test_an_unresolved_name_keeps_what_it_learned_and_says_why() -> None:
    e = entry()
    record_resolution(e, Resolution(reason="TITLE_MISMATCH", names=("HRANT DİNK VAKFI", "Hrant Dink Foundation")),
                      spec=SPEC, now=NOW)
    e.refresh_from_db()
    assert (e.resolution, e.unresolved_reason, e.resolution_attempted_at) == ("UNRESOLVED", "TITLE_MISMATCH", NOW)
    assert e.names == ["HRANT DİNK VAKFI", "Hrant Dink Foundation"]


def test_an_identifier_another_body_holds_is_a_question_not_a_merge() -> None:
    # The domain is already body A's; the Wikidata id is body B's. record_organisation
    # raises rather than guess which body the pair belongs to (register.py).
    a = record_organisation(domain="hrantdink.org", name="A", kind="PRIVATE_FOUNDATION",
                            country_code="TR", found_via="x")
    record_organisation(domain="other.org.tr", name="B", kind="PRIVATE_FOUNDATION",
                        country_code="TR", found_via="x", identifiers=(("WIKIDATA", "Q1"),))
    e = entry()
    record_resolution(e, Resolution("hrantdink.org", "WIKIDATA", "", "Q1",
                                    ("HRANT DİNK VAKFI", "Hrant Dink Foundation")),
                      spec=SPEC, now=NOW)
    e.refresh_from_db()
    a.refresh_from_db()
    assert (e.resolution, e.unresolved_reason, e.organisation_id) == ("UNRESOLVED", "IDENTIFIER_CONFLICT", None)
    assert "Hrant Dink Foundation" not in a.names          # the failed attempt rolled back
    assert not a.identifiers.exists()


def test_diffbot_asked_is_recorded_whatever_it_answered() -> None:
    e = entry()
    record_resolution(e, Resolution(reason="NO_CANDIDATE", names=("x",), diffbot_asked=True), spec=SPEC, now=NOW)
    e.refresh_from_db()
    assert e.diffbot_asked_at == NOW


def test_a_write_that_matches_nothing_raises() -> None:
    e = entry()
    RegisterEntry.objects.filter(pk=e.pk).delete()
    with pytest.raises(CatalogWriteRefused):
        record_resolution(e, Resolution(reason="NO_CANDIDATE", names=("x",)), spec=SPEC, now=NOW)


def test_due_entries_skip_final_reasons_and_retry_fetch_failures_after_a_week() -> None:
    entry("never")
    entry("final", unresolved_reason="NO_CANDIDATE", resolution_attempted_at=NOW)
    entry("fresh-failure", unresolved_reason="FETCH_FAILED", resolution_attempted_at=NOW)
    entry("old-failure", unresolved_reason="FETCH_FAILED", resolution_attempted_at=NOW - timedelta(days=8))
    keys = lambda qs: sorted(qs.values_list("external_key", flat=True))
    assert keys(due_entries("vgm_tr", now=NOW)) == ["never", "old-failure"]
    assert keys(due_entries("vgm_tr", now=NOW, retry_final=True)) == ["final", "never", "old-failure"]
```

- [ ] **Step 2: Implement** `apps/research/resolve_entries.py`

```python
"""A register row's resolution, written -- or its reason (spec 6.5, 6.1).

Status is CANDIDATE for every resolver outcome. The register vouched that the
BODY exists and what kind it is; the resolver found a domain, and nothing
vouched for that pairing but our own checks. REGISTERED stays what 6.1 says it
is -- a register (or, later, an operator through item 12) vouching for the
domain -- and status governs spend and dedupe, never what a student sees.

Every write is `filter(pk=...).update(...)` with its row count checked. Under
the runtime role an UPDATE on this shared table matches zero rows and raises
nothing (the policy hides the row from writes); a resolver run under the wrong
role would otherwise report success and change nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q, QuerySet

from .models import RegisterEntry, UnresolvedReason
from .register import record_organisation
from .resolver import Resolution

#: A fetch failure is the host's, often transient (4.13a: ~10%, broken chains,
#: no answer); a week lets the fetch engine's own retry schedule run first.
FETCH_RETRY_AFTER = timedelta(days=7)
#: One Diffbot entity per name per quarter at most.
DIFFBOT_RETRY_AFTER = timedelta(days=90)


class CatalogWriteRefused(RuntimeError):
    """A resolution matched no row -- deleted meanwhile, or the wrong database role."""


@dataclass(frozen=True)
class RegisterSpec:
    """What a register vouches for every row it lists."""

    country_code: str
    kind: str


def due_entries(register: str, *, now: datetime, retry_final: bool = False) -> QuerySet[RegisterEntry]:
    unresolved = RegisterEntry.objects.filter(
        register=register, resolution=RegisterEntry.Resolution.UNRESOLVED
    )
    due = Q(resolution_attempted_at__isnull=True) | Q(
        unresolved_reason=UnresolvedReason.FETCH_FAILED,
        resolution_attempted_at__lt=now - FETCH_RETRY_AFTER,
    )
    if retry_final:
        due |= ~Q(unresolved_reason=UnresolvedReason.FETCH_FAILED)
    return unresolved.filter(due).order_by("first_seen", "external_key")


def diffbot_allowed(entry: RegisterEntry, *, now: datetime) -> bool:
    return entry.diffbot_asked_at is None or entry.diffbot_asked_at < now - DIFFBOT_RETRY_AFTER


def _update(entry: RegisterEntry, **values: object) -> None:
    if RegisterEntry.objects.filter(pk=entry.pk).update(**values) != 1:
        raise CatalogWriteRefused(
            f"register entry {entry.pk} was not updated: deleted, or not running as catalog_ingestion"
        )


def record_resolution(entry: RegisterEntry, resolution: Resolution, *, spec: RegisterSpec, now: datetime) -> None:
    names = list(resolution.names or (entry.name,))
    common: dict[str, object] = {"names": names, "resolution_attempted_at": now}
    if resolution.diffbot_asked:
        common["diffbot_asked_at"] = now
    with transaction.atomic():
        if resolution.domain:
            identifiers = (("WIKIDATA", resolution.wikidata_qid),) if resolution.wikidata_qid else ()
            try:
                with transaction.atomic():
                    org = record_organisation(
                        domain=resolution.domain, name=entry.name, names=names, kind=spec.kind,
                        country_code=spec.country_code, found_via=f"RESOLVER:{resolution.via}",
                        identifiers=identifiers,
                    )
            except ValueError:
                # record_organisation raises on one identifier held by two bodies
                # (register.py): a merge question for item 12, never a guess here.
                _update(entry, **common, resolution=RegisterEntry.Resolution.UNRESOLVED,
                        resolved_via="", unresolved_reason=UnresolvedReason.IDENTIFIER_CONFLICT)
                return
            _update(entry, **common, resolution=RegisterEntry.Resolution.RESOLVED,
                    resolved_via=resolution.via, unresolved_reason="", organisation=org)
        else:
            _update(entry, **common, resolution=RegisterEntry.Resolution.UNRESOLVED,
                    resolved_via="", unresolved_reason=resolution.reason)
```

Note `record_organisation` also raises `ValueError` for an unkeyable domain; the resolver only
returns keyed domains, so that branch is unreachable from it — the inner `atomic()` keeps a
failed identifier insert from poisoning the outer transaction either way.

- [ ] **Step 3: Run and commit**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_resolve_entries.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
git add apps/research/resolve_entries.py tests/research/test_resolve_entries.py
git commit -m "feat(research): write a resolution as a CANDIDATE, or its reason, and never zero rows"
```

---

### Task 9: `manage.py resolve_register`

**Files:**
- Create: `apps/research/management/commands/resolve_register.py`,
  `tests/research/test_resolve_register_command.py`

- [ ] **Step 1: Failing tests**

```python
"""The operator entry: dry-run by default, writes gated on the hold-out, Diffbot on terms."""

from datetime import UTC, datetime

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.research.management.commands import resolve_register
from apps.research.models import RegisterEntry
from apps.research.resolver import CallBudgetSpent, Resolution

pytestmark = pytest.mark.django_db


class FakeResolver:
    def __init__(self, answers):
        self.answers = answers

    def resolve(self, query):
        answer = self.answers[query.names[0]]
        if answer == "SPENT":
            raise CallBudgetSpent("spent")
        return answer


def _entries(*names):
    for i, name in enumerate(names):
        RegisterEntry.objects.create(register="vgm_tr", external_key=str(i), name=name, names=[name],
                                     resolution=RegisterEntry.Resolution.UNRESOLVED, last_seen=timezone.now())


@pytest.fixture
def keys(settings):
    settings.TAVILY_API_KEY = "t"
    settings.RESOLVER_WRITES_ENABLED = True
    return settings


def test_write_is_refused_until_the_gate_passed(keys) -> None:
    keys.RESOLVER_WRITES_ENABLED = False
    with pytest.raises(CommandError, match="hold-out"):
        call_command("resolve_register", "--register", "vgm_tr", "--write")


def test_diffbot_is_refused_on_stale_terms(keys) -> None:
    keys.DIFFBOT_TOKEN, keys.DIFFBOT_TERMS_READ_ON = "d", "2026-01-01"
    with pytest.raises(CommandError, match="terms"):
        call_command("resolve_register", "--register", "vgm_tr", "--diffbot")


def test_a_dry_run_prints_and_writes_nothing(keys, monkeypatch, capsys) -> None:
    _entries("HRANT DİNK VAKFI")
    monkeypatch.setattr(resolve_register, "build_resolver", lambda **kw: FakeResolver(
        {"HRANT DİNK VAKFI": Resolution("hrantdink.org", "SEARCH_TITLE", names=("HRANT DİNK VAKFI",))}))
    call_command("resolve_register", "--register", "vgm_tr")
    assert "hrantdink.org" in capsys.readouterr().out
    assert RegisterEntry.objects.get().resolution == "UNRESOLVED"


def test_a_spent_budget_stops_the_run_and_leaves_the_rest_untouched(keys, monkeypatch, capsys) -> None:
    _entries("A VAKFI", "B VAKFI")
    monkeypatch.setattr(resolve_register, "build_resolver", lambda **kw: FakeResolver({
        "A VAKFI": Resolution(reason="NO_CANDIDATE", names=("A VAKFI",)), "B VAKFI": "SPENT"}))
    call_command("resolve_register", "--register", "vgm_tr", "--write")
    assert RegisterEntry.objects.get(name="A VAKFI").unresolved_reason == "NO_CANDIDATE"
    assert RegisterEntry.objects.get(name="B VAKFI").resolution_attempted_at is None
    assert "stopped" in capsys.readouterr().out
```

- [ ] **Step 2: Implement**

```python
"""Resolve a register's URL-less rows to sites (spec 6.5), or record why not.

Dry-run by default: prints each name's answer and writes nothing. `--write`
records resolutions and reasons, and is refused until the fresh-script
hold-out has passed (RESOLVER_WRITES_ENABLED) -- until then the resolver's
output is a candidate list for a person to read, which is what the 2026-09-18
standing rule required. A spent budget stops the run between names, never
mid-write, and the untouched names are next run's.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import vgm
from apps.research.fetch import CATALOG_ROLE_NOTE, SweepBudget, default_budget
from apps.research.models import RegisterEntry
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.diffbot import DiffbotEnhance
from apps.research.providers.tavily import TavilyProvider
from apps.research.resolve_entries import (
    RegisterSpec, diffbot_allowed, due_entries, record_resolution,
)
from apps.research.resolver import (
    CallBudget, CallBudgetSpent, FetchBudgetSpent, NameQuery, Resolver,
)
from apps.research.vocabulary import VocabularyMissing, load_vocabulary
from apps.research.wikidata import find_item

#: A register this command may resolve, and what the register vouches for.
REGISTERS = {vgm.REGISTER: RegisterSpec(country_code="TR", kind="PRIVATE_FOUNDATION")}
_TERMS_FRESH = timedelta(days=31)
_DIFFBOT_WINDOW = timedelta(days=30)


def build_resolver(*, country_code: str, tavily_credits: int, diffbot_entities: int,
                   budget: SweepBudget) -> Resolver:
    vocab = load_vocabulary(country_code)
    diffbot_cap = CallBudget(diffbot_entities)
    enhance = DiffbotEnhance(token=settings.DIFFBOT_TOKEN) if diffbot_entities else None

    def diffbot(name: str) -> str:
        diffbot_cap.spend()
        return enhance.homepage(name) if enhance else ""

    return Resolver(
        vocabulary=vocab,
        candidates=TavilyProvider(api_key=settings.TAVILY_API_KEY).candidates,
        tavily=CallBudget(tavily_credits),
        budget=budget,
        wikidata=lambda names: find_item(names, country_qid=vocab.country_qid,
                                         languages=vocab.languages),
        diffbot=diffbot if enhance else None,
    )


class Command(BaseCommand):
    help = "Resolve a register's unresolved names to sites, or record why not." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--register", required=True, choices=sorted(REGISTERS))
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--tavily-credits", type=int,
                            default=settings.RESOLVER_TAVILY_CREDITS_PER_RUN)
        parser.add_argument("--diffbot", action="store_true", help="ask Diffbot on the residue")
        parser.add_argument("--write", action="store_true")
        parser.add_argument("--retry-final", action="store_true",
                            help="also retry names whose reason is final")

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        if options["write"] and not settings.RESOLVER_WRITES_ENABLED:
            raise CommandError("--write is off until the fresh-script hold-out passes "
                               "(RESOLVER_WRITES_ENABLED; build item 8, Task 12)")
        if not settings.TAVILY_API_KEY:
            raise CommandError("TAVILY_API_KEY (or SEARCH_API_KEY) is not set")
        diffbot_entities = 0
        if options["diffbot"]:
            if not settings.DIFFBOT_TOKEN:
                raise CommandError("DIFFBOT_TOKEN is not set")
            try:
                read_on = date.fromisoformat(settings.DIFFBOT_TERMS_READ_ON)
            except ValueError:
                read_on = date.min
            if now.date() - read_on > _TERMS_FRESH:
                raise CommandError("Diffbot's terms carry no effective date; re-read them and "
                                   "set DIFFBOT_TERMS_READ_ON (spec 6.2)")
            used = RegisterEntry.objects.filter(diffbot_asked_at__gte=now - _DIFFBOT_WINDOW).count()
            diffbot_entities = max(0, settings.DIFFBOT_MONTHLY_ENTITIES - used)

        spec = REGISTERS[options["register"]]
        try:
            resolver = build_resolver(country_code=spec.country_code,
                                      tavily_credits=options["tavily_credits"],
                                      diffbot_entities=diffbot_entities, budget=default_budget())
        except VocabularyMissing as error:
            raise CommandError(str(error)) from error

        tally: dict[str, int] = {}
        entries = due_entries(options["register"], now=now, retry_final=options["retry_final"])
        for entry in entries[: options["limit"]]:
            query = NameQuery(tuple(entry.names or [entry.name]), spec.country_code,
                              allow_diffbot=diffbot_allowed(entry, now=now))
            try:
                resolution = resolver.resolve(query)
            except (CallBudgetSpent, FetchBudgetSpent, ProviderUnavailable) as error:
                self.stdout.write(f"stopped: {error}")
                break
            outcome = resolution.via or resolution.reason
            tally[outcome] = tally.get(outcome, 0) + 1
            self.stdout.write(f"{entry.name} -> {resolution.domain or '-'} ({outcome})")
            if options["write"]:
                record_resolution(entry, resolution, spec=spec, now=now)
        self.stdout.write(f"tally: {dict(sorted(tally.items()))}")
        if not options["write"]:
            self.stdout.write("dry run: nothing written")
```

`default_budget()` gives the run the
standard sweep ceiling (`FETCH_SWEEP_CREDITS`); a title fetch is one Firecrawl credit.

- [ ] **Step 3: Run and commit**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_resolve_register_command.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
git add apps/research/management/commands/resolve_register.py tests/research/test_resolve_register_command.py
git commit -m "feat(research): resolve_register -- dry-run by default, writes gated on the hold-out"
```

- [ ] **Step 4: One dry run on VGM, ~25 Tavily credits, to see the shape before the gate**

```bash
TAVILY_API_KEY=... FIRECRAWL_API_KEY=... SCRAPEDO_API_KEY=... DATABASE_ROLE=migration \
  POSTGRES_DB=tehsil_resolver uv run python manage.py read_register --register vgm --max-pages 1
TAVILY_API_KEY=... FIRECRAWL_API_KEY=... SCRAPEDO_API_KEY=... DATABASE_ROLE=migration \
  POSTGRES_DB=tehsil_resolver uv run python manage.py resolve_register --register vgm_tr --limit 10
```

(`read_register` takes the short slug `vgm`; its rows are stored under `vgm.REGISTER`, `vgm_tr`,
which is what `resolve_register` takes. One page is ~50 rows, about a third of them UNRESOLVED.)
Paste the tally into the Task 9 commit's follow-up note in the PR. **This
is development data**, not acceptance; nothing is written. Do not change a rule because of it
unless a result shows a code defect (a crash, a directory accepted, an aggregator returned) —
and if you do, re-run Tasks 3–7's tests and say so in the PR.

---

### Task 10: Assemble the fresh-script hold-out — Vietnamese

**Files:**
- Create: `apps/research/holdout.py`, `apps/research/management/commands/draw_resolver_holdout.py`,
  `tests/research/test_holdout.py`, `docs/research/resolver-holdout-vn.csv` (generated)

**Why Vietnamese, decided now:** §6.5 names Uzbek, Indonesian or Vietnamese. Vietnamese is the
most distant from every development sample: Latin script carrying stacked diacritics (the fold is
exercised as never before), **monosyllabic words** (most tokens are 2–4 letters, so the ≥ 4-letter
distinctive rule and the ≥ 6-letter tier 1 are stressed, and one-token names will be common), and
institutional domains that are English-initials acronyms (`hust.edu.vn`) — rule 4's claim, tested
on a new population. Uzbek is partly Cyrillic, which Kazakh already exercised; Indonesian is kept
unseen as the **next** hold-out if this one fails. Georgia and Kazakhstan are development data and
never used again (§6.5).

**How the set is assembled** (fixed here, before any resolver output exists):

- Population: Wikidata items with `P17 = Q881` (Vietnam), a `P856` website, a Vietnamese (`vi`)
  label, not dissolved (`P576` absent).
- Strata, by `P31/P279*` class, to mirror what the resolver will actually be asked (funders and
  the bodies adjacent to them) instead of "organisations in item order", which gave Kazakhstan
  seventeen embassies: foundation `Q157031` 10, non-profit organisation `Q163740` 10, government
  agency `Q327333` 10, university `Q3918` 10, business `Q4830453` 5, diplomatic mission `Q7843791`
  5 — **50 names**. A stratum that cannot fill is topped up from organisation `Q43229`, marked
  `other`; the total stays 50.
- Order: `ORDER BY MD5(CONCAT(STR(?item), "tehsil-resolver-holdout-vn-2026-09-25"))` — a salt
  committed in this plan before any draw, so the order is reproducible and chosen by nobody.
- Names given to the resolver: the `vi` label, plus the `en` and `ru` labels where they exist —
  what Wikidata would supply under rule 4. Truth: the registrable domains of every `P856` value.
  An item whose truth is unkeyable or on `AGGREGATOR_DOMAINS` is skipped for the next in order.
- Frozen: the CSV records `resolver_digest`, the sha256 of `names.py`, `resolver.py`,
  `vocabulary.py` and every file in `resolver_data/`. The gate refuses to score a different digest.

- [ ] **Step 1: Failing tests** (`tests/research/test_holdout.py`)

```python
"""The hold-out: drawn blind, frozen, scored by rules fixed before the draw."""

import pytest

from apps.research import holdout


def test_rows_group_by_item_and_skip_what_cannot_be_truth() -> None:
    rows = [
        {"item": "http://www.wikidata.org/entity/Q1", "site": "https://hust.edu.vn/", "native": "Đại học Bách khoa Hà Nội", "en": "Hanoi University of Science and Technology"},
        {"item": "http://www.wikidata.org/entity/Q1", "site": "https://en.hust.edu.vn/", "native": "Đại học Bách khoa Hà Nội"},
        {"item": "http://www.wikidata.org/entity/Q2", "site": "https://www.facebook.com/x", "native": "Quỹ X"},
        {"item": "http://www.wikidata.org/entity/Q3", "site": "https://quy-y.org.vn/", "native": "Quỹ Y"},
    ]
    picked = holdout.pick(rows, n=5, taken=set(), stratum="university")
    assert [p.qid for p in picked] == ["Q1", "Q3"]
    assert picked[0].truth == ("hust.edu.vn",)
    assert picked[0].names == ("Đại học Bách khoa Hà Nội", "Hanoi University of Science and Technology")


def test_a_verdict_is_correct_wrong_or_unresolved() -> None:
    assert holdout.verdict("hust.edu.vn", ("hust.edu.vn",)) == "correct"
    assert holdout.verdict("", ("hust.edu.vn",)) == "unresolved"
    assert holdout.verdict("vnu.edu.vn", ("hust.edu.vn",)) == "wrong"


def test_the_pass_rule_is_the_one_fixed_before_the_draw() -> None:
    ok = holdout.Tally(correct=20, wrong=2, unresolved=28, directory_or_aggregator_wrong=0, diffbot_wrong=1)
    assert holdout.passes(ok)
    assert not holdout.passes(ok._replace(wrong=3))
    assert not holdout.passes(ok._replace(correct=19))
    assert not holdout.passes(ok._replace(directory_or_aggregator_wrong=1))
    assert not holdout.passes(ok._replace(diffbot_wrong=2))


def test_the_digest_changes_when_a_rule_changes(tmp_path, monkeypatch) -> None:
    before = holdout.frozen_digest()
    monkeypatch.setattr(holdout, "_FROZEN_EXTRA", (b"a rule changed",))
    assert holdout.frozen_digest() != before
```

- [ ] **Step 2: Implement** `apps/research/holdout.py`

```python
"""The resolver's acceptance test: a fresh-script hold-out (spec 6.5, 15).

Per-country numbers are development scores; acceptance is a blind hold-out
on a script and morphology the resolver has never seen (owner rule
2026-09-18). The rules below were fixed in the build-item-8 plan before any
hold-out was drawn, and the digest makes "the resolver we drew against" the
one that is scored.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from .domains import is_catalogue
from .hosts import registrable_domain

SALT = "tehsil-resolver-holdout-vn-2026-09-25"
STRATA = (
    ("foundation", "Q157031", 10), ("nonprofit", "Q163740", 10),
    ("agency", "Q327333", 10), ("university", "Q3918", 10),
    ("business", "Q4830453", 5), ("mission", "Q7843791", 5),
)
TOP_UP = ("other", "Q43229")
_HERE = Path(__file__).resolve().parent
_FROZEN = ("names.py", "resolver.py", "vocabulary.py")
_FROZEN_EXTRA: tuple[bytes, ...] = ()

DRAW_QUERY = """SELECT ?item ?site ?native ?en ?ru WHERE {{
  ?item wdt:P31/wdt:P279* wd:{cls} ; wdt:P17 wd:{country} ; wdt:P856 ?site .
  FILTER NOT EXISTS {{ ?item wdt:P576 [] }}
  ?item rdfs:label ?native . FILTER(LANG(?native) = "{lang}")
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?ru . FILTER(LANG(?ru) = "ru") }}
}} ORDER BY MD5(CONCAT(STR(?item), "{salt}")) LIMIT {limit}"""


@dataclass(frozen=True)
class Drawn:
    qid: str
    stratum: str
    names: tuple[str, ...]
    truth: tuple[str, ...]


def pick(rows: Iterable[Mapping[str, str]], *, n: int, taken: set[str], stratum: str) -> list[Drawn]:
    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        qid = row["item"].rsplit("/", 1)[-1]
        slot = grouped.setdefault(qid, {"names": {}, "truth": {}})
        for key in ("native", "en", "ru"):
            if row.get(key):
                slot["names"].setdefault(row[key], None)  # type: ignore[union-attr]
        domain = registrable_domain(row.get("site", ""))
        if domain and not is_catalogue(domain):
            slot["truth"].setdefault(domain, None)  # type: ignore[union-attr]
    picked: list[Drawn] = []
    for qid, slot in grouped.items():  # dict keeps the salted order
        if len(picked) == n:
            break
        if qid in taken or not slot["truth"]:
            continue
        picked.append(Drawn(qid, stratum, tuple(slot["names"]), tuple(slot["truth"])))  # type: ignore[arg-type]
        taken.add(qid)
    return picked


def verdict(domain: str, truth: Iterable[str]) -> str:
    if not domain:
        return "unresolved"
    return "correct" if domain in set(truth) else "wrong"


class Tally(NamedTuple):
    correct: int
    wrong: int
    unresolved: int
    directory_or_aggregator_wrong: int
    diffbot_wrong: int


def passes(t: Tally) -> bool:
    """Fixed 2026-09-25, before the draw, from the measured record (§4.13a-b):
    confident-wrong is the harm -- dev was 0/25 German and 1/25 Turkish, the
    failed hold-outs 3/25 Georgian and 11/25 Kazakh -- so at most 2 in 50 (4%).
    Correct at least 20 in 50 (40%): between Turkish dev (48%) and the Georgian
    failure (20%). A wrong answer that is a directory or aggregator is a broken
    rule, not a miss, so none is tolerated; Diffbot is new since v4 and gets
    its own ceiling of one wrong."""
    return (
        t.wrong <= 2 and t.correct >= 20
        and t.directory_or_aggregator_wrong == 0 and t.diffbot_wrong <= 1
    )


def frozen_digest() -> str:
    digest = hashlib.sha256()
    for name in _FROZEN:
        digest.update((_HERE / name).read_bytes())
    for path in sorted((_HERE / "resolver_data").glob("*.json")):
        digest.update(path.name.encode() + path.read_bytes())
    for extra in _FROZEN_EXTRA:
        digest.update(extra)
    return digest.hexdigest()
```

- [ ] **Step 3: The draw command** — `apps/research/management/commands/draw_resolver_holdout.py`

```python
"""Draw the resolver's fresh-script hold-out from Wikidata (build item 8, Task 10).

Free and read-only. Writes docs/research/resolver-holdout-<cc>.csv with the
names the resolver will see, the truth it will not, and the digest of the
resolver being tested. Run once, after Tasks 1-9 are committed.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.research import holdout, wikidata
from apps.research.vocabulary import load_vocabulary


class Command(BaseCommand):
    help = "Draw the resolver's blind hold-out for one country from Wikidata."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", default="VN")
        parser.add_argument("--language", default="vi")

    def handle(self, *args: Any, **options: Any) -> None:
        code = options["country"].upper()
        out = Path(settings.BASE_DIR) / "docs" / "research" / f"resolver-holdout-{code.lower()}.csv"
        if out.exists():
            raise CommandError(f"{out} exists: a hold-out is drawn once, never re-drawn")
        country_qid = load_vocabulary(code).country_qid
        taken: set[str] = set()
        drawn: list[holdout.Drawn] = []
        shortfall = 0
        for stratum, cls, n in holdout.STRATA:
            rows = wikidata.sparql(holdout.DRAW_QUERY.format(
                cls=cls, country=country_qid, lang=options["language"], salt=holdout.SALT, limit=n * 6))
            got = holdout.pick(rows, n=n, taken=taken, stratum=stratum)
            shortfall += n - len(got)
            drawn += got
        if shortfall:
            label, cls = holdout.TOP_UP
            rows = wikidata.sparql(holdout.DRAW_QUERY.format(
                cls=cls, country=country_qid, lang=options["language"], salt=holdout.SALT,
                limit=shortfall * 10))
            drawn += holdout.pick(rows, n=shortfall, taken=taken, stratum=label)
        digest = holdout.frozen_digest()
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["qid", "stratum", "names", "truth", "salt", "resolver_digest"])
            for d in drawn:
                writer.writerow([d.qid, d.stratum, " | ".join(d.names), " ".join(d.truth),
                                 holdout.SALT, digest])
        self.stdout.write(f"{len(drawn)} drawn ({shortfall} topped up) -> {out}")
```

(If `settings.BASE_DIR` is not defined in `config/settings/base.py`, use
`Path(__file__).resolve().parents[4]` — the repository root from this file.)

- [ ] **Step 4: Run tests, commit the code, then draw — once**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_holdout.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
git add apps/research/holdout.py apps/research/management/commands/draw_resolver_holdout.py tests/research/test_holdout.py
git commit -m "feat(research): the resolver's hold-out -- strata, salt, frozen digest, pass rule"
POSTGRES_DB=tehsil_resolver uv run python manage.py draw_resolver_holdout --country VN --language vi
wc -l docs/research/resolver-holdout-vn.csv   # expect 51
git add docs/research/resolver-holdout-vn.csv
git commit -m "docs(research): the Vietnamese resolver hold-out, drawn blind"
```

**Do not open the CSV's `truth` column before the gate has run**, and do not change any frozen file
after this commit — the gate compares digests. If the draw returns fewer than 50 in total, commit
what it drew; the gate reports rates and the pass rule scales (`correct ≥ 40%`, `wrong ≤ 4%`,
rounded down/up respectively) — write the scaled thresholds into the results note before running.

---

### Task 11: The gate — `manage.py resolver_gate`

**Files:**
- Create: `apps/research/management/commands/resolver_gate.py`
- Modify: `tests/research/test_holdout.py`

**What it measures, on the same responses (rule 6):** two arms — **FULL** (every drawn name;
rule 4) and **NATIVE** (the `vi` label only) — share one memoised Tavily cache, one per-host title
cache and one per-name Diffbot cache, so the difference between them is the rule, never provider
variance. Wikidata's website rung is **off** in both arms (its P856 is the truth); names come from
the file, as a register plus Wikidata would supply them.

**Adjudication, automatic, so nobody judges after seeing the answer:** a `wrong` becomes
`correct` only if (i) the resolver's domain's homepage lands (final URL) on a truth domain, or
(ii) every truth domain's homepage comes back `DEAD` and the resolver's homepage title contains a
full name variant (folded, flattened). Anything else stays wrong.

**Cost ceiling:** Tavily ≤ 150 credits (50 names × ≤ 3 variants, shared by both arms); Firecrawl
≤ 200 credits (≤ 2 title fetches per name, cached across arms, plus adjudication); Diffbot ≤ 50
entities = 1,250 credits of the free 10,000/month (these do not appear in
`RegisterEntry.diffbot_asked_at` — subtract them by hand from the month's allowance).

- [ ] **Step 1: Add the adjudication test to `tests/research/test_holdout.py`**

```python
def test_adjudication_only_ever_turns_wrong_into_correct_on_evidence() -> None:
    assert holdout.adjudicate(
        resolved_landed_on="hust.edu.vn", truth=("hust.edu.vn",),
        truth_dead=False, resolved_title_names_it=False) == "correct"
    assert holdout.adjudicate(
        resolved_landed_on="new-site.vn", truth=("old-site.vn",),
        truth_dead=True, resolved_title_names_it=True) == "correct"
    assert holdout.adjudicate(
        resolved_landed_on="new-site.vn", truth=("old-site.vn",),
        truth_dead=False, resolved_title_names_it=True) == "wrong"
```

and to `apps/research/holdout.py`:

```python
def adjudicate(*, resolved_landed_on: str, truth: Iterable[str], truth_dead: bool,
               resolved_title_names_it: bool) -> str:
    if resolved_landed_on in set(truth):
        return "correct"
    if truth_dead and resolved_title_names_it:
        return "correct"
    return "wrong"
```

- [ ] **Step 2: The command** — `apps/research/management/commands/resolver_gate.py`

```python
"""Score the resolver on its blind hold-out (build item 8, Task 11). PASS/FAIL.

Refuses a resolver whose digest differs from the one the hold-out was drawn
against. A budget running out mid-gate is INCOMPLETE, never a partial score.
Prints the table and writes docs/research/resolver-holdout-<cc>-results.csv;
the reading goes in docs/superpowers/research/ by hand (Task 12).
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.research import holdout
from apps.research.domains import is_catalogue
from apps.research.fetch import CATALOG_ROLE_NOTE, SweepBudget, fetch_page
from apps.research.fetch.types import Outcome
from apps.research.hosts import registrable_domain
from apps.research.names import tokens
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.diffbot import DiffbotEnhance
from apps.research.providers.tavily import TavilyProvider
from apps.research.resolver import (
    CallBudget, CallBudgetSpent, FetchBudgetSpent, NameQuery, Resolver, page_titles,
)
from apps.research.vocabulary import load_vocabulary


def _memo(fn, budget: CallBudget | None = None):
    """Same answer for the same key in both arms (rule 6) -- and a cap that
    counts only real calls, never the second arm's cache hits."""
    cache: dict = {}

    def call(key):
        if key not in cache:
            if budget is not None:
                budget.spend()
            cache[key] = fn(key)
        return cache[key]

    return call


class Command(BaseCommand):
    help = "Score the resolver on its blind hold-out and print PASS or FAIL." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", default="VN")
        parser.add_argument("--diffbot", action="store_true")
        parser.add_argument("--tavily-credits", type=int, default=160)
        parser.add_argument("--firecrawl-credits", type=int, default=200)

    def handle(self, *args: Any, **options: Any) -> None:
        code = options["country"].upper()
        root = Path(settings.BASE_DIR) / "docs" / "research"
        rows = list(csv.DictReader((root / f"resolver-holdout-{code.lower()}.csv").open(encoding="utf-8")))
        if {r["resolver_digest"] for r in rows} != {holdout.frozen_digest()}:
            raise CommandError("the resolver changed since the hold-out was drawn: this set is "
                               "development data now; draw a fresh country (plan Task 12)")
        vocab = load_vocabulary(code)
        budget = SweepBudget({"FIRECRAWL": options["firecrawl_credits"], "SCRAPE_DO": 500})
        tavily = TavilyProvider(api_key=settings.TAVILY_API_KEY)
        shared_tavily = CallBudget(options["tavily_credits"])
        candidates = _memo(tavily.candidates, shared_tavily)
        fetch = _memo(lambda url: fetch_page(url, purpose="read", tag="resolver-gate", budget=budget))
        diffbot = None
        if options["diffbot"]:
            enhance = DiffbotEnhance(token=settings.DIFFBOT_TOKEN)
            diffbot = _memo(enhance.homepage, CallBudget(len(rows)))
        results = []
        try:
            for arm in ("FULL", "NATIVE"):
                # The Resolver's own Tavily cap is unbounded here: `candidates`
                # already spends `shared_tavily` on real calls only.
                r = Resolver(vocabulary=vocab, candidates=candidates, tavily=CallBudget(10**6),
                             fetch=lambda url, **_: fetch(url), budget=budget,
                             use_wikidata_website=False, diffbot=diffbot)
                for row in rows:
                    names = tuple(n.strip() for n in row["names"].split(" | ") if n.strip())
                    names = names if arm == "FULL" else names[:1]
                    got = r.resolve(NameQuery(names, code))
                    truth = tuple(row["truth"].split())
                    v = holdout.verdict(got.domain, truth)
                    if v == "wrong":
                        v = self._adjudicate(got.domain, truth, names, fetch)
                    results.append({"qid": row["qid"], "stratum": row["stratum"], "arm": arm,
                                    "domain": got.domain, "via": got.via, "reason": got.reason,
                                    "verdict": v, "catalogue": is_catalogue(got.domain) if got.domain else False})
        except (CallBudgetSpent, FetchBudgetSpent, ProviderUnavailable) as error:
            raise CommandError(f"INCOMPLETE: {error}") from error

        out = root / f"resolver-holdout-{code.lower()}-results.csv"
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        for arm in ("FULL", "NATIVE"):
            mine = [x for x in results if x["arm"] == arm]
            c = Counter(x["verdict"] for x in mine)
            self.stdout.write(f"{arm}: {c['correct']} / {c['wrong']} / {c['unresolved']} "
                              "(correct / confident-wrong / unresolved)")
            self.stdout.write(f"  reasons: {dict(Counter(x['reason'] for x in mine if x['reason']))}")
            self.stdout.write(f"  via: {dict(Counter(x['via'] for x in mine if x['via']))}")
            for stratum in sorted({x['stratum'] for x in mine}):
                s = Counter(x["verdict"] for x in mine if x["stratum"] == stratum)
                self.stdout.write(f"  {stratum}: {s['correct']}/{s['wrong']}/{s['unresolved']}")
        full = [x for x in results if x["arm"] == "FULL"]
        c = Counter(x["verdict"] for x in full)
        tally = holdout.Tally(
            correct=c["correct"], wrong=c["wrong"], unresolved=c["unresolved"],
            directory_or_aggregator_wrong=sum(1 for x in full if x["verdict"] == "wrong" and x["catalogue"]),
            diffbot_wrong=sum(1 for x in full if x["verdict"] == "wrong" and x["via"] == "DIFFBOT"),
        )
        self.stdout.write(f"spend: tavily {shared_tavily.spent} credits, fetch ${budget.usd():.3f}")
        self.stdout.write(("PASS" if holdout.passes(tally) else "FAIL") + f" {tally}")

    def _adjudicate(self, domain, truth, names, fetch) -> str:
        landed = fetch(f"https://{domain}/")
        landed_on = registrable_domain(landed.final_url) if landed.final_url else ""
        dead = all(fetch(f"https://{t}/").outcome == Outcome.DEAD for t in truth)
        flat_title = "".join(tokens(" ".join(page_titles(landed.body))))
        names_it = any("".join(tokens(n)) in flat_title for n in names if tokens(n))
        return holdout.adjudicate(resolved_landed_on=landed_on, truth=truth,
                                  truth_dead=dead, resolved_title_names_it=names_it)
```

(`SweepBudget.usd()` exists, `fetch/__init__.py`.) The Diffbot memo's cap is one entity per
drawn row; a `CallBudgetSpent` from it inside the resolver's residue rung means "not asked", never
a stop. The `directory_or_aggregator_wrong` count uses
`is_catalogue`; a directory can only be returned through a defect in `score_candidate`, and a
wrong answer whose label `_is_directory` would flag is added to it by hand in the results note if
you find one reading the CSV — say so explicitly.

- [ ] **Step 3: Run the unit tests, commit, then run the gate once**

```bash
POSTGRES_DB=tehsil_resolver uv run pytest tests/research/test_holdout.py -q 2>&1 | tail -3; echo "EXIT=${PIPESTATUS[0]}"
git add apps/research/holdout.py apps/research/management/commands/resolver_gate.py tests/research/test_holdout.py
git commit -m "feat(research): resolver_gate -- two arms on the same responses, PASS or FAIL"
TAVILY_API_KEY=... FIRECRAWL_API_KEY=... SCRAPEDO_API_KEY=... DIFFBOT_TOKEN=... DATABASE_ROLE=migration \
  POSTGRES_DB=tehsil_resolver uv run python manage.py resolver_gate --country VN --diffbot
```

Committing `holdout.py` changes the digest? No — `holdout.py` is not in `_FROZEN`; only
`names.py`, `resolver.py`, `vocabulary.py` and `resolver_data/` are. Do not touch those four
between Task 10's draw and this run.

---

### Task 12: Record the result and act on it

**Files:**
- Create: `docs/superpowers/research/<today>-resolver-holdout-vn.md`,
  `docs/research/resolver-holdout-vn-results.csv` (written by the gate)
- Modify: `CLAUDE.md`, `docs/legal/2026-09-provider-terms.md`, and on PASS only
  `config/settings/base.py`

- [ ] **Step 1: Write the results note** — the gate's printed output verbatim, then:
  FULL vs NATIVE (rule 4's measured contribution on a new population); unresolved by reason and
  by stratum; every confident-wrong listed with its domain, the truth and the adjudication;
  Diffbot's answers each with the confidence you read in a separate one-off look if you need the
  threshold measurement §15 owes (read it transiently from a re-run of the adapter in a shell;
  write the numbers in this note, never on a row); spend against the ceilings above. State the
  scaled thresholds if fewer than 50 were drawn.

- [ ] **Step 2: Record the two outbound paths in `CLAUDE.md`** — in "Web fetching", beside the
  EACEA and data.go.kr bullets under "Two more outbound paths are data sources rather than fetches":

```markdown
- **Organisation names → Wikidata** (`apps/research/wikidata.py`). CC0; the entity API for the
  resolver's first stop (an exact label in the right country, never a fuzzy top hit) and the query
  service for the resolver's vocabulary (`manage.py build_resolver_vocabulary`, committed under
  `apps/research/resolver_data/`). Through `egress.fetch_json_api`; WDQS answers
  `application/sparql-results+json`, which only `wikidata.sparql` asks `fetch_json_api` to accept.
- **The resolver's residue → Diffbot Enhance** (`apps/research/providers/diffbot.py`). One homepage
  URL per name, nothing else read; 400 entities a month metered on
  `RegisterEntry.diffbot_asked_at`; its terms have no effective date, so `resolve_register
  --diffbot` refuses unless `DIFFBOT_TERMS_READ_ON` is within 31 days.
```

- [ ] **Step 3: Record the Diffbot terms read** in `docs/legal/2026-09-provider-terms.md`: the
  date you read `diffbot.com/company/terms/`, that the grant still reads as the 2026-09-17 note
  quotes it (`docs/superpowers/research/2026-09-17-diffbot-perplexity-recon.md` §1) or what
  changed, and that only a URL is kept.

- [ ] **Step 4a: On PASS** — flip the default in `config/settings/base.py`:

```python
RESOLVER_WRITES_ENABLED = os.getenv("RESOLVER_WRITES_ENABLED", "1") == "1"
```

and commit with the gate's PASS line in the message body. Then, as an operator step and not
before: `resolve_register --register vgm_tr --write` in batches within the month's credits; the
CANDIDATE organisations it writes are picked up by `classify_organisations` (they carry no
`classified_at`), which is where 4.13a's "a resolution is a candidate for classification" lands.

- [ ] **Step 4b: On FAIL** — leave `RESOLVER_WRITES_ENABLED` off. The note must say which clause
  failed and what the confident-wrongs have in common (the 4.13b format: each cause as a design
  rule, not a tuning). **Vietnamese is now development data.** Any rule change is measured next on
  **Indonesian** (then Uzbek): delete nothing, re-run `draw_resolver_holdout --country ID
  --language id` with a new salt written into `holdout.SALT` **in the same commit as the rule
  change, before the draw**, and never score Vietnam, Georgia or Kazakhstan as acceptance again.

- [ ] **Step 5: Commit, push, open the PR** — body: the gate result, the spend, the unresolved
  shape, and the interfaces below. Do not merge.

---

## Interfaces other items plan against

- **Item 7 (enumerators, hub harvesting):** a URL-less name from a hub page or the Wikidata/ROR
  enumerators is resolved by `Resolver.resolve(NameQuery(names, country_code, contact_email=…))` —
  the same call, no parallel implementation. Item 7 owns persisting hub names; if it keeps them on
  `RegisterEntry` (a hub is a list), `resolve_register` gains a `REGISTERS` row and nothing else.
- **Item 10 (sweep harness):** unaffected by the resolver's writes; its denominator reads
  `RegisterEntry` counts, and `resolved_via`/`unresolved_reason` let it report resolution per route.
- **Item 12 (resolution queue):** `SITE_UNKNOWN` items are `RegisterEntry` rows with
  `resolution=UNRESOLVED` and a final `unresolved_reason`; `FETCH_FAILED` feeds `HOST_UNREACHABLE`
  after the fetch engine's retries. The top-3 candidates the operator sees are recomputed at queue
  time with `ranked()` — this plan stores none. A human pick writes `resolved_via=HUMAN`,
  `status=REGISTERED` (§11's write-back), through `record_organisation`.
- **R5 affiliation lookup (item 14):** a student's employer or prior university is looked up "by
  public name (register first, then the resolver; never a personal fact in a query)". The
  `NameQuery` carries a name and a country only; Tavily's query is the quoted name. Item 14 must
  pass nothing else, and must not write a `RegisterEntry` from a student's answer.

## Self-review against the brief and §6.5

- **§6.5 v4 ladder:** rung 0 (`email_domain`, reused) → Wikidata P856 (Task 2/7) → Tavily top 10
  basic + denylist (`TavilyProvider.candidates`, reused) → tiered lexical score with its exact
  weights (Task 3) → title check with kind agreement for every pick below tier 3 (Tasks 4, 7) →
  unresolved on mismatch, fetch failure and one-token names (Task 7).
- **Six rules, all data-not-rules:** (1) kinds from Wikidata's subclass tree + the directory rule
  (Tasks 2, 3); (2) places and demonyms from Wikidata (Task 2); (3) compounds (Task 1); (4) every
  name variant scored as a union, `names` stored (Tasks 1, 6, 7), measured as FULL vs NATIVE
  (Task 11); (5) unreachable-by-name returns a reason, never a guess (the reasons table); (6) A/B
  in one process on the same responses (Task 11's shared caches).
- **Diffbot residue:** Task 5 + Task 7's `_residue`, title-checked, monthly meter, terms guard.
- **`names` store:** `RegisterEntry.names` → `Organisation.names` via `record_organisation`.
- **What stays unresolved and why:** the table, `UnresolvedReason`, `due_entries`.
- **Fresh-script hold-out:** assembled per Task 10 (population, strata, salt, frozen digest);
  fails per `holdout.passes` (≥ 3 confident-wrong in 50, < 20 correct, any directory/aggregator
  wrong, or ≥ 2 Diffbot wrong); consequence per Task 12.
- **Shared rules:** no spec edited; no migration number hard-coded (Task 6 Step 3); no new table,
  stated and justified; RLS write refusal proved through `runtime_connection`; built on
  `domains.py`, `hosts.py`, `register.py`, `vgm.py`, `fetch_page`, `TavilyProvider` rather than
  beside them.
