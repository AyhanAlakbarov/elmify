# Card Reader, Slice 1: Code Finders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the code that finds every value a funding card can show — amounts (with ranges,
approximations, conversions and multipliers), dates (absolute, month-only, ranges, ambiguous order),
relative dates, durations, intakes, places, levels and entry requirements — plus the per-language
funding-word table, so the Jev reader (slice 2) only ever picks among candidates code found.

**Architecture:** Pure functions over one line of page text, in a new package
`apps/research/candidates/`, returning frozen dataclasses with character offsets. Month and country
names come from Unicode CLDR through Babel instead of hand-typed tables. One assembler keys every
candidate by name (`amounts.m3`, `dates.d1`) because Jev addressed by list position answered about a
neighbour. No model, no network, no database: every task is unit-tested at $0.

**Tech Stack:** Python 3 (repo pin), Django app layout, `re`, `decimal`, Babel (new dependency,
Task 1), pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-verified-catalog-one-reader-design.md` §5 step 1 and
step 4 (finders), §5.2 (what each candidate feeds), §5.3 (languages); decision-engine spec
`2026-10-03-one-decision-engine-design.md` §3.11 (dates, ranges, "exact or up to"); research
`.context/research/2026-10-03-dates-and-bounds-fixes.md` (both on branch `claude/verified-catalog-design`,
commits 4c2b69d1 or newer).

## Plan 3 as a whole (this is slice 1 of 4)

Plan 3 is the Jev funding reader (verified-catalog §5; decision-engine §10 item 3). Four slices, each
its own plan and PR, in this order:

1. **Code finders** (this plan).
2. **The quote proposer and the Jev reader:** an LLM proposes exact value quotes per line (owner
   decision 2026-10-05, hybrid extraction; code keeps only byte-exact substrings and parses them with
   this slice's parsers; measured in `docs/superpowers/2026-10-05-hybrid-extraction-measurement.md`),
   unioned with this slice's candidates. Then the Jev reader: D8 injection screen, Call 1 (which lines matter), Call 2 (which award each
   line belongs to), Call 3 (§5.2's catalogue per award), the typed card. It includes a single-page
   entry point for one `Program` and source (verified-catalog §3.3 needs it on demand), and output
   shaped so one programme can carry several tracks (§3.2, EMJMs).
3. **Writing and showing the card:** storage for ranges, relative dates and family amounts, the
   per-value reader record, the serve rule, rewiring `pipeline._fund_page`, deleting `funding_judge.py`'s vote.
4. **The cycle verifier ported to Jev** (`VerifyDueCyclesRule` stays DISABLED).

**Serve rule (owner, 2026-10-05; verified-catalog §5.5 at 4c2b69d1):** Jev and Kimi K3 agree at the
question's bar, or, when they disagree, Claude Sonnet 5.5 sides with one of them (2 of 3); otherwise
the award is hidden. Bars stay provisional until a certification batch. That is slice 2 and 3's
concern; this slice calls no model.

## Global Constraints

- Lint only, never `ruff format`: `uv run ruff check .` (CLAUDE.md).
- Types: `uv run mypy apps config`.
- Tests: `POSTGRES_DB=tehsil_card_reader uv run pytest -q` (per-branch DB name, CLAUDE.md).
- Never hand-edit `uv.lock`; dependencies change only through `uv add` (CLAUDE.md, Python rules).
- "Code counts, code computes, code parses. Jev decides only what needs a judgment." (§5.1)
- "A span with no day is a month, never given one" — "February 2027" is never "February 20". (§5 step 4)
- "Year-only and academic-year spans go to the intake finder", never to dates. (§5 step 4)
- Ranges and approximations are code's; `range` is never asked of Jev. (§5.2 `bound`)
- A currency form listed for two currencies ($, kr, ¥, manat, som) confirms neither (`card_fields._forms`).
- An unknown region is `no_candidate`: counted, never guessed. (§5 step 4)
- Nothing is translated; a page is read in its own language. (§5 step 1)

## Review Focus

Every code block below was run before it was written here (2026-10-05, Babel 2.18.0): 156 tests,
`ruff check` and `mypy --strict` clean, and the finders measured on the 4,113 round-1 lines (worst
line 9 ms; 4,000-character synthetic lines 20–27 ms). The likeliest remaining risks:

1. **Short names and the Turkic ending list.** A stem under five letters takes only the endings in
   `locale_names._CASE`; a Hungarian ending ("Kubában") or an az/tr ending outside the list is
   missed, and a short ordinary word that ends in a listed ending is a place. `_NOT_PLACES` ("mali",
   "того") also drops English "Mali" said alone. Owner: `test_a_short_name_takes_only_a_case_ending`
   (Task 1), `test_ordinary_words_are_not_places` (Task 7).
2. **Demonyms that are also language names.** "French", "German", "Turkish", "французск" mark a
   place on "taught in French" lines. Places on lines the key marks with no question rose from 179 to
   224, almost all real mentions ("РФ" in "Президента РФ", "UK", "Hungary"); whether a place is a
   who-may-apply rule stays the reader's `eligible_pN` question. Owner: the alias table (Task 7).
3. **"and" joins a range only after a lead.** "1 and 15 March" without "between"/"с"/"arasında"
   gives two dates; "300 və 500 manat" gives two amounts (pinned), and a list of non-money numbers
   right before an amount ("ages 18, 20 and 500 EUR") would be read as amounts sharing its currency.
   Owner: `test_and_lists_*` (Tasks 3 and 4).
4. **Header cues by longest match.** "Son müraciət tarixi" is a deadline because "son müraciət" is the
   longest cue; a header holding two cues of which the shorter is right needs its own row (as
   "başvuru sonuç" and "application deadline" have). Owner: `test_a_column_header_names_its_dates_role`
   (Task 8a).
5. **Values code still declines to read.** A decimal comma without a multiplier ("104,5 manat")
   stays `low=None`; "under 35" is stored as `age_max=34`; a Russian specialist degree
   ("специалитет") is a `bachelor` level (a first degree entered from school). Owners:
   `test_multipliers_and_other_scripts`, `test_requirement_values`.

---

## File Structure

| file | responsibility |
|---|---|
| `apps/research/locale_names.py` | CLDR month and country names per language (Babel); inflection-tolerant patterns |
| `docs/research/funding-terms.csv` | per-language funding words (data, reviewed like the currency forms) |
| `apps/research/funding_terms.py` | compiles that table into the pattern `readable_text(terms=...)` takes |
| `apps/research/candidates/__init__.py` | the dataclasses and `find_all(lines) -> Candidates` |
| `apps/research/candidates/amounts.py` | amounts, multipliers, ranges, approximations, conversions |
| `apps/research/candidates/dates.py` | absolute dates, month-only, ranges, ambiguity; relative dates |
| `apps/research/candidates/spans.py` | durations and intakes |
| `apps/research/candidates/who.py` | places, levels (incl. postdoc), entry requirements with values |
| `apps/research/candidates/headers.py` | a table column header's date role (`header_cue`) |
| `docs/research/region-names.csv` | region names per language for `funding/regions.py` keys |
| `docs/research/place-aliases.csv` | demonyms and common names CLDR lacks, hand-seeded |
| `docs/research/date-header-cues.csv` | per-language header cues and the date role each names |
| `docs/research/currency-evidence.csv` | six rows added: 원, руб, рубль, рубля, рублей, сум |
| `apps/research/engine_eval/evidence.py` | switched to the candidates (one finder, not two) |
| `apps/research/funding_reader.py:40-57` | `_FUNDING_TERMS` becomes `funding_terms()` |

---

### Task 1: Babel and CLDR names

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (through `uv add` only)
- Create: `apps/research/locale_names.py`
- Test: `tests/research/test_locale_names.py`

**Why Babel (buy before build):** checked 2026-10-05 with Babel 2.18.0: it carries month names
(format wide + abbreviated) and country names for az, tr, ru, en, fr, de, hu, ko, zh, ja, including
Russian's genitive "февраля". Options weighed: `pycountry` (country names only, through gettext,
patchy for az), `dateparser` (measured and rejected for dates, §5 step 4), hand-typed tables (no
source, and every language would need review). Babel's **stand-alone** month context falls back to
another locale for several languages in 2.18 (Turkish stand-alone February printed "fevral"), so only
the format context is read, plus Russian's stand-alone nominative.

**Why stems only in six languages (measured on the 4,113 round-1 lines):** stemming every CLDR name
made Polish "Belgia" match Turkish "belge" (document) about 90 times, Spanish "enero" match "Energy",
Hungarian "Chile" match "children" and German "Kongo" match "Hong Kong". Names now take endings only
in az, tr, ru, uk, kk and hu; Russian and Ukrainian drop exactly one final vowel first ("Турция" ->
"Турци-и"); a stem under five letters takes only a Turkic case ending or, in Russian, at most three
letters (so "mali" is not read in "maliyyə", nor "инди" in "индивидуальных"). Names are grouped by
first letter in the alternation, which took `find_places` from 101 ms to 7 ms on a 4,000-character
line.

**Interfaces:**
- Produces: `LANGUAGES`, `INFLECTING`; `fold(text) -> str` (casefold without the combining dot of
  "İ"); `month_names(lang, wide_only=False) -> dict[str, int]`; `country_names(lang) -> dict[str, str]`;
  `all_months()`, `all_countries()`; `month_forms(wide_only=False)` and `country_forms()` ->
  `tuple[(name, language, value), ...]`; `inflected(forms: Iterable[tuple[str, str]]) -> str`;
  `lookup(token, forms) -> value | None` (exact name first, then the longest stem).

- [ ] **Step 1: Add the dependency**

Run: `uv add "babel>=2.18,<3"` then `uv sync --locked --group dev`
Expected: `pyproject.toml` lists babel; `uv.lock` updated by uv; `uv run pip-audit` reports no
known vulnerabilities (run it with network access).

- [ ] **Step 2: Write the failing tests**

```python
# tests/research/test_locale_names.py
import re

from apps.research.locale_names import (
    all_countries,
    all_months,
    country_forms,
    country_names,
    inflected,
    lookup,
    month_names,
)


def test_month_names_come_from_the_format_context():
    assert month_names("tr")["şubat"] == 2
    assert month_names("az")["fevral"] == 2
    assert month_names("ru")["февраля"] == 2 and month_names("ru")["февраль"] == 2
    assert month_names("hu")["február"] == 2
    # Babel 2.18's stand-alone context falls back to another locale ("fevral" for Turkish)
    assert "fevral" not in month_names("tr")
    assert "feb" not in month_names("en", wide_only=True)


def test_abbreviations_drop_their_dot():
    assert month_names("ru")["февр"] == 2
    assert month_names("en")["feb"] == 2


def test_country_names_map_to_alpha_2_codes():
    assert country_names("az")["azərbaycan"] == "AZ"
    assert country_names("ru")["турция"] == "TR"
    assert country_names("ko")["아제르바이잔"] == "AZ"
    assert all(len(code) == 2 and code.isalpha() for code in country_names("en").values())


def test_inflected_month_and_country_forms():
    forms = [("февраля", "ru"), ("турция", "ru"), ("azərbaycan", "az"), ("şubat", "tr")]
    pattern = re.compile(inflected(forms), re.IGNORECASE)
    for text in ("1 февраля", "в феврале", "в Турции", "Azərbaycanın", "Şubat'ta"):
        assert pattern.search(text), text
    # a stem never matches inside another word, and only inflecting languages are stemmed
    assert not re.compile(inflected([("mart", "tr")]), re.IGNORECASE).search("smartphone")
    assert not re.compile(inflected([("enero", "es")]), re.IGNORECASE).search("Energy")
    assert not re.compile(inflected([("belgia", "pl")]), re.IGNORECASE).search("belgeler")


def test_lookup_prefers_an_exact_name_then_the_longest_stem():
    assert lookup("Турции", country_forms()) == "TR"
    assert lookup("Niger", country_forms()) == "NE"
    assert lookup("Nigeria", country_forms()) == "NG"
    assert lookup("İraq", country_forms()) == "IQ"


def test_every_language_contributes_months_and_countries():
    assert len(all_months()) > 200
    assert all_countries()["türkiye"] == "TR"


def test_a_short_name_takes_only_a_case_ending():
    forms = [("mali", "tr"), ("индия", "ru"), ("çin", "az")]
    pattern = re.compile(inflected(forms), re.IGNORECASE)
    for text in ("maliyyələşdirilməsi", "malik olmaq", "индивидуальных"):
        assert not pattern.search(text), text
    for text in ("Mali'den", "Malidə", "Индии", "Çində", "Çinli", "Çinədək"):
        assert pattern.search(text), text
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/test_locale_names.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.locale_names'`

- [ ] **Step 4: Implement**

```python
# apps/research/locale_names.py
"""Month and country names in every page language, from Unicode CLDR through Babel.

Buy before build: CLDR already carries each destination language's month and country names,
including Russian's genitive months; a hand-typed table would need a source and a reviewer per
language. Pure apart from Babel's bundled data.

Case endings are matched only in the languages that attach them (az, tr, ru, uk, kk, hu). Every
other language is matched exactly: stemming Polish "Belgia" to "belg" made every Turkish "belge"
(document) a Belgian, and Spanish "enero" made "Energy" a January.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import cache
from typing import cast

from babel import Locale

#: The languages pages are read in (verified-catalog §5.3).
LANGUAGES: tuple[str, ...] = (
    "az", "tr", "ru", "en", "fr", "de", "hu", "ko", "zh", "ja", "es", "it", "pl", "uk", "kk",
)
#: Languages whose names take case endings; only these are matched by stem.
INFLECTING = frozenset({"az", "tr", "ru", "uk", "kk", "hu"})
#: Of those, the ones whose ending replaces a final vowel ("Турция" -> "Турции"). Turkic and
#: Hungarian endings attach to the whole name ("Türkiye'de", "Rusiyada"); dropping a vowel there
#: made Hungarian "Chile" match "children".
_REPLACES_VOWEL = frozenset({"ru", "uk"})
_VOWELS = "аяеёиийьоуюыaeiouəıö"
#: Shorter stems match inside ordinary words ("mar" in "smartphone").
_MIN_STEM = 4


def fold(text: str) -> str:
    """Casefold without the combining dot Python adds to a casefolded "İ"."""
    return text.casefold().replace("̇", "")


@cache
def month_names(lang: str, wide_only: bool = False) -> dict[str, int]:
    """Folded month name or abbreviation (dot dropped) -> month number.

    Only the format context: Babel 2.18's stand-alone context falls back to another locale for
    several languages (Turkish stand-alone February is "fevral"). Russian and Ukrainian also get
    their stand-alone nominative ("февраль" beside genitive "февраля").
    """
    locale = Locale.parse(lang)
    contexts = [("format", "wide")]
    if not wide_only:
        contexts.append(("format", "abbreviated"))
    if lang in ("ru", "uk"):
        contexts.append(("stand-alone", "wide"))
    names: dict[str, int] = {}
    for context, width in contexts:
        for number, name in locale.months[context][width].items():
            names[fold(name).rstrip(".")] = int(number)
    return names


@cache
def country_names(lang: str) -> dict[str, str]:
    """Folded country name -> ISO 3166 alpha-2 code (CLDR numeric regions skipped)."""
    return {
        fold(name): code
        for code, name in Locale.parse(lang).territories.items()
        if len(code) == 2 and code.isalpha()
    }


@cache
def all_months() -> dict[str, int]:
    merged: dict[str, int] = {}
    for lang in LANGUAGES:
        merged.update(month_names(lang))
    return merged


@cache
def all_countries() -> dict[str, str]:
    merged: dict[str, str] = {}
    for lang in LANGUAGES:
        merged.update(country_names(lang))
    return merged


@cache
def month_forms(wide_only: bool = False) -> tuple[tuple[str, str, int], ...]:
    """(name, language, month) for every language."""
    return tuple(
        (name, lang, number)
        for lang in LANGUAGES
        for name, number in month_names(lang, wide_only).items()
    )


@cache
def country_forms() -> tuple[tuple[str, str, str], ...]:
    """(name, language, alpha-2 code) for every language."""
    return tuple(
        (name, lang, code) for lang in LANGUAGES for name, code in country_names(lang).items()
    )


def _stem(word: str, lang: str) -> str:
    """Drop exactly one final vowel, in Russian and Ukrainian, when what is left is long enough
    ("турция" -> "турци")."""
    if lang in _REPLACES_VOWEL and word[-1:] in _VOWELS and len(word) - 1 >= _MIN_STEM:
        return word[:-1]
    return word


#: What a short stem may take. Any ending would read Turkish "mali" (Mali) in "maliyyə" (finance)
#: and Russian "инди" (India) in "индивидуальных"; so a stem under five letters takes only a Turkic
#: case ending or, in Russian and Ukrainian, at most three letters.
_SHORT = 5
_CASE = r"(?:n?[ıiuüə]n|[ıiuüə]|[yn]?[aeə]|[dt][aeə][nk]?|l[ıiuüə])"
_TURKIC_ENDING = rf"(?:['’]\w+|{_CASE}{_CASE}?)?(?!\w)"
_SLAVIC_ENDING = r"\w{0,3}(?!\w)"


def _ending(stem: str, lang: str) -> str:
    if len(stem) >= _SHORT:
        return r"(?:['’]?\w+)?"
    return _SLAVIC_ENDING if lang in _REPLACES_VOWEL else _TURKIC_ENDING


def _form(name: str, lang: str) -> str:
    """One name as a pattern, word by word; each stem may take an ending when `lang` inflects."""
    words = fold(name).split()
    if lang in INFLECTING:
        stems = [_stem(word, lang) for word in words]
        return r"\s+".join(re.escape(stem) + _ending(stem, lang) for stem in stems)
    return r"\s+".join(re.escape(word) for word in words) + r"(?!\w)"


def inflected(forms: Iterable[tuple[str, str]]) -> str:
    """A regex alternation matching each (name, language) at a word start.

    Endings attach directly ("Azərbaycanın", "Şubat'ta" after an apostrophe) in Turkic and
    Hungarian, and replace the final vowel in Slavic ("Турции"), so an inflecting language's name
    is matched by its stem plus an ending; other languages' names match exactly. Names are grouped
    by first letter, so a 4,000-name alternation costs one branch per position, not 4,000; within a
    letter, longest first, so "yüksek lisans" wins over "lisans" where both are listed.
    """
    tails: dict[str, set[str]] = {}
    for name, lang in forms:
        folded = fold(name)
        if folded:
            first = re.escape(folded[0])
            tails.setdefault(first, set()).add(_form(name, lang)[len(first):])
    body = "|".join(
        f"{first}(?:{'|'.join(sorted(group, key=len, reverse=True))})"
        for first, group in sorted(tails.items())
    )
    return rf"(?<!\w)(?:{body})"


@cache
def _index(
    forms: tuple[tuple[str, str, object], ...],
) -> tuple[dict[str, object], tuple[tuple[tuple[str, ...], object], ...]]:
    exact: dict[str, object] = {}
    for name, _, value in forms:
        exact.setdefault(name, value)
    stems = [
        (tuple(_stem(word, lang) for word in name.split()), value)
        for name, lang, value in forms
        if lang in INFLECTING
    ]
    stems.sort(key=lambda item: -sum(map(len, item[0])))
    return exact, tuple(stems)


def lookup[V](token: str, forms: tuple[tuple[str, str, V], ...]) -> V | None:
    """The value of the name `token` prints: an exact name first, then the longest stem it starts
    with among the inflecting languages' names."""
    folded = " ".join(fold(token).split())
    exact, stems = _index(forms)
    if folded in exact:
        return cast(V, exact[folded])
    words = folded.split()
    for stem, value in stems:
        if len(words) == len(stem) and all(w.startswith(s) for w, s in zip(words, stem)):
            return cast(V, value)
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/test_locale_names.py -q`
Expected: 7 passed. If a CLDR spelling differs from a test (for example a Korean country name), print
`country_names("ko")` and fix the test to CLDR's spelling, never the data.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock apps/research/locale_names.py tests/research/test_locale_names.py
git commit -m "feat(research): CLDR month and country names per page language, through Babel"
```

---

### Task 2: The per-language funding-word table

**Files:**
- Create: `docs/research/funding-terms.csv`, `apps/research/funding_terms.py`
- Modify: `apps/research/funding_reader.py` (`_FUNDING_TERMS`, its comment, `import re`)
- Test: `tests/research/test_funding_terms.py`

**Why:** `_FUNDING_TERMS` is English plus beca/bourse/borsa, and `readable_text` drops every section
it does not match, so a Russian or Azerbaijani funding section is never read (§5 step 1: "the term
list is a fetch filter in all but name … it must fail open"). Its five callers keep the name; only
its value changes. Failing open is the rule for every row: "burs" is a stem, so "Bursa" (a city)
costs one extra section read, where a word-bounded "burs" missed "bursiyer"; and the table carries
the wording of no-amount funding ("бесплатное обучение", "dövlət hesabına", "sigorta").

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `funding_terms() -> re.Pattern[str]` (cached); `FUNDING_TERMS_FILE: Path`;
  `funding_reader._FUNDING_TERMS` is now `funding_terms()`.

- [ ] **Step 1: Write the data file**

```csv
term,language,match,note
scholarship,en,stem,
bursar,en,stem,
fellowship,en,stem,
fund,en,word,"fund, funding, funded"
funding,en,word,
funded,en,word,
financial aid,en,stem,
financial support,en,stem,
tuition,en,stem,
fee,en,word,
fees,en,word,
waiver,en,stem,
discount,en,stem,
stipend,en,stem,"also matches Stipendium, stipendio"
assistantship,en,stem,
grant,en,stem,
award,en,stem,
loan,en,word,
loans,en,word,
housing,en,stem,
accommodation,en,stem,
insurance,en,stem,
travel,en,stem,
relocation,en,stem,
internship,en,stem,
placement,en,stem,
co-op,en,stem,
allowance,en,stem,
beca,es,word,"word-bounded: 'because' contains beca"
becas,es,word,
matrícula,es,stem,
bourse,fr,word,
bourses,fr,word,
frais de scolarité,fr,stem,
exonération,fr,stem,
aide financière,fr,stem,
logement,fr,stem,
assurance,fr,stem,
borsa,it,word,
borse,it,word,
tasse universitarie,it,stem,
förderung,de,stem,
studiengebühr,de,stem,
versicherung,de,stem,
wohnheim,de,stem,
ösztöndíj,hu,stem,
tandíj,hu,stem,
támogatás,hu,stem,
təqaüd,az,stem,
qrant,az,stem,
təhsil haqqı,az,stem,
ödəniş,az,stem,
güzəşt,az,stem,
maliyyə,az,stem,
yataqxana,az,stem,
sığorta,az,stem,
dövlət hesabına,az,stem,
burs,tr,stem,"a stem on purpose: 'Bursa' (a city) costs one extra section read, a missed 'bursiyer' costs a section"
hibe,tr,stem,
öğrenim ücreti,tr,stem,
harç,tr,stem,
muafiyet,tr,stem,
indirim,tr,stem,
ücretsiz,tr,stem,
sigorta,tr,stem,
yurt,tr,word,
стипенди,ru,stem,
грант,ru,stem,
финансир,ru,stem,
оплат,ru,stem,
стоимость обучения,ru,stem,
скидк,ru,stem,
льгот,ru,stem,
общежити,ru,stem,
проживани,ru,stem,
квот,ru,stem,
бесплатн,ru,stem,
бюджетн,ru,stem,
страхов,ru,stem,
стипенді,uk,stem,
стипендия,kk,stem,
шәкіртақы,kk,stem,
stypendium,pl,stem,
장학금,ko,stem,
등록금,ko,stem,
생활비,ko,stem,
지원금,ko,stem,
奖学金,zh,stem,
助学金,zh,stem,
学费,zh,stem,
生活费,zh,stem,
奨学金,ja,stem,
授業料,ja,stem,
生活費,ja,stem,
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/research/test_funding_terms.py
import pytest

from apps.research.funding_terms import funding_terms


@pytest.mark.parametrize("line", [
    "Scholarships for international students",
    "Təqaüd proqramı: ayda 200 manat",
    "Burs başvuru koşulları",
    "Bursiyerlere aylık ödeme yapılır",
    "Размер стипендии — 25 000 рублей",
    "Бесплатное обучение в магистратуре",
    "Təhsil dövlət hesabına ödənilir",
    "Öğrenim ücretsizdir ve sağlık sigortası sağlanır",
    "Стипендія для іноземців",
    "Ösztöndíj összege havonta",
    "외국인 장학금 안내",
    "研究生奖学金",
    "Bourse d'excellence",
    "Logement et assurance",
    "Studiengebühren und Förderung",
    "Becas para estudiantes",
])
def test_a_funding_section_in_every_page_language_is_kept(line):
    assert funding_terms().search(line)


@pytest.mark.parametrize("line", [
    "because the course is popular",
    "Campus map and parking",
])
def test_word_bounded_terms_do_not_fire_inside_other_words(line):
    assert not funding_terms().search(line)


def test_the_reader_uses_the_table():
    from apps.research.funding_reader import _FUNDING_TERMS
    assert _FUNDING_TERMS.search("Təqaüd")
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/test_funding_terms.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.funding_terms'`

- [ ] **Step 4: Implement**

```python
# apps/research/funding_terms.py
"""The funding words a page's sections are kept by, in every page language.

`readable_text(terms=...)` drops each section matching none of these, so this table is a fetch
filter in all but name and must fail open (verified-catalog §5 step 1): a word missing here hides a
funding section from every reader. Data, not code, reviewed like
docs/research/currency-evidence.csv.
"""

from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

FUNDING_TERMS_FILE = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "funding-terms.csv"
)


@cache
def funding_terms() -> re.Pattern[str]:
    """One case-insensitive pattern: `stem` rows match anywhere, `word` rows only as whole words."""
    with FUNDING_TERMS_FILE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    parts = sorted(
        (
            rf"(?<!\w){re.escape(r['term'])}(?!\w)" if r["match"] == "word"
            else re.escape(r["term"])
            for r in rows
        ),
        key=len,
        reverse=True,
    )
    return re.compile("|".join(parts), re.IGNORECASE)
```

Then in `apps/research/funding_reader.py`: add `from .funding_terms import funding_terms` to the
relative imports, between `from .funding_judge import ...` and `from .register import ...`; replace
the `_FUNDING_TERMS = re.compile(...)` block (lines 49-57 on master b367413a) and the comment above
it with the block below; and delete `import re`, which nothing else in the module uses (checked on
this branch: no other `re.` in the file).

```python
#: Kept by name for its five callers; the words are data now (docs/research/funding-terms.csv),
#: in every page language, because readable_text drops each section this does not match.
_FUNDING_TERMS = funding_terms()
```

- [ ] **Step 5: Run the tests, then the callers' tests**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/test_funding_terms.py tests/research/test_funding_reader.py tests/research/test_discovery_pipeline.py tests/research/test_pipeline_funding.py -q`
Expected: all pass. A caller test that pinned an English-only selection and now keeps an extra
section is a correct change in behaviour; update its expectation and say so in the commit.

- [ ] **Step 6: Commit**

```bash
git add docs/research/funding-terms.csv apps/research/funding_terms.py apps/research/funding_reader.py tests/research/test_funding_terms.py
git commit -m "feat(research): funding words in every page language, as data; the section filter fails open"
```

---

### Task 3: Amount candidates

**Files:**
- Create: `apps/research/candidates/__init__.py`, `apps/research/candidates/amounts.py`
- Modify: `docs/research/currency-evidence.csv` (six rows)
- Test: `tests/research/candidates/__init__.py` (empty), `tests/research/candidates/test_amounts.py`

**Interfaces:**
- Consumes: `apps.research.card_fields._figure`, `evidence_rows`; `apps.reference_data.ISO_4217_CODES`;
  `apps.research.locale_names.fold` (Task 1).
- Produces: `Amount` in `candidates/__init__.py` (below) and `find_amounts(line: str) -> list[Amount]`.
  `currency` is the one currency the span names, or None; `currencies` is every currency its form
  could name ("manat" -> AZN and TMT). `converted_from` is an index into this line's amounts; Task 8
  turns it into a key.

- [ ] **Step 1: Add the currency rows**

Append to `docs/research/currency-evidence.csv`. Every row is a form that names one currency, and
the production `card_fields` tests still pass with them (`tests/research/test_card_fields.py`, 73
passed with these rows on 2026-10-05):

```csv
원,KRW,symbol,drafted
руб,RUB,abbreviation,drafted
рубль,RUB,name,drafted
рубля,RUB,name,drafted
рублей,RUB,name,drafted
сум,UZS,name,drafted
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/research/candidates/test_amounts.py
import time
from decimal import Decimal

from apps.research.candidates.amounts import find_amounts


def one(line):
    found = find_amounts(line)
    assert len(found) == 1, found
    return found[0]


def test_a_single_amount_with_its_currency():
    a = one("Monthly stipend: 43,000 HUF for 12 months")
    assert (a.low, a.high, a.currency, a.bound) == (Decimal(43000), Decimal(43000), "HUF", None)


def test_ranges_in_four_languages_are_one_candidate():
    assert one("50만원~150만원").bound == "range"
    a = one("Les montants tournent entre 1 200 et 2 100 € par mois")
    assert (a.low, a.high, a.currency, a.bound) == (Decimal(1200), Decimal(2100), "EUR", "range")
    a = one("¥143,000～145,000")
    assert (a.low, a.high, a.bound) == (Decimal(143000), Decimal(145000), "range")
    a = one("стипендия от 10 000 до 20 000 рублей")
    assert (a.low, a.high, a.currency, a.bound) == (Decimal(10000), Decimal(20000), "RUB", "range")
    a = one("EUR 1 000 – 2 000 per month")
    assert (a.low, a.high, a.bound) == (Decimal(1000), Decimal(2000), "range")


def test_and_lists_amounts_unless_a_lead_makes_it_a_range():
    assert [a.low for a in find_amounts("müvafiq olaraq 300 və 500 manat")] == [300, 500]
    assert [a.low for a in find_amounts("aylıq 110, 160 və 200 manat")] == [110, 160, 200]
    assert one("between 500 and 800 TL").bound == "range"
    assert one("500 ile 800 TL arasında").bound == "range"


def test_different_currencies_or_a_falling_pair_never_merge():
    found = find_amounts("a grant of 500 TRY and 20 AZN")
    assert [a.text for a in found] == ["500 TRY", "20 AZN"]
    assert [a.bound for a in find_amounts("500 TRY – 20 AZN")] == [None, None]
    assert [a.bound for a in find_amounts("2 000 € – 1 000 €")] == [None, None]


def test_approximations_are_code_s():
    assert one("aylıq təxminən 100 manat təqaüd").bound == "approximately"
    assert one("250만원 내외").bound == "approximately"
    assert one("about £1,500 a term").bound == "approximately"


def test_a_parenthesised_conversion_points_at_its_amount():
    found = find_amounts("HUF 65,000 (approx. 180 EUR)")
    assert len(found) == 2 and found[1].converted_from == 0 and found[1].currency == "EUR"
    # the same currency in brackets is an alternative figure, not a conversion
    found = find_amounts("1,300 euros (1,400 euros beginning with February 2026)")
    assert [a.converted_from for a in found] == [None, None]


def test_multipliers_and_other_scripts():
    assert one("50만원").low == Decimal(500000)
    assert one("1,5 млн руб.").low == Decimal(1500000)
    assert one("3 bin TL").low == Decimal(3000)
    assert one("١٢٠٠ €").low == Decimal(1200)
    assert one("1,5 €").low is None  # one digit after a comma, no multiplier: ambiguous
    assert one("3000 (üç min) manat").low == Decimal(3000)
    assert one("aylık 600,- TL").low == Decimal(600)


def test_grades_and_bare_numbers_are_not_amounts():
    assert find_amounts("minimum 71 bal, GPA 3.5") == []
    assert find_amounts("Founded in 1998 with 12,000 students") == []


def test_a_currency_word_never_ends_another_word():
    assert find_amounts("EMBO Doktora Sonrası Araştırma Bursları 2027 Yılı") == []
    assert find_amounts("burs bitiş tarihini izleyen 1 ay içerisinde") == []


def test_an_ambiguous_currency_form_names_no_currency():
    # "$" and "manat" are listed for several currencies: the figure stays, the currency does not
    a = one("$5,000 per year")
    assert a.low == Decimal(5000) and a.currency is None
    a = one("ayda 200 manat")
    assert a.currencies == frozenset({"AZN", "TMT"}) and a.currency is None


def test_long_runs_of_digits_stay_linear():
    for line in ("1 " * 2000, "1.2.3.4.5.6.7.8.9." * 230, "1 000 EUR, " * 400):
        started = time.perf_counter()
        find_amounts(line)
        assert time.perf_counter() - started < 0.05, line[:20]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_amounts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.candidates'`

- [ ] **Step 4: Implement**

```python
# apps/research/candidates/__init__.py
"""Every value a funding card can show, found by code on one line (verified-catalog §5 step 4).

Jev never reads a number, a date or a place off a page: code finds the candidates, Jev picks among
them, code copies the pick. A funding line where code finds nothing is `no_candidate`, and that
count is what improves these finders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Amount:
    text: str            # verbatim span, joined ends for a range
    start: int
    end: int
    low: Decimal | None  # None when the figure's marks are ambiguous
    high: Decimal | None  # == low unless bound == "range"
    currency: str | None  # ISO code, only when the span names exactly one
    bound: str | None    # "range" | "approximately" | None (Jev asks exact/up_to/at_least)
    converted_from: int | None = None  # index, in this line, of the amount this one converts
    currencies: frozenset[str] = frozenset()  # every currency the span's form could name
```

```python
# apps/research/candidates/amounts.py
"""Amounts: a number with a currency form, read as the page printed it.

Ranges ("50만원~150만원", "entre 1 200 et 2 100 €") and approximations ("təxminən", "내외") are
recorded by code, never asked (decision-engine §3.11; Jev scored 0/3 on ranges). A multiplier word
between the number and the currency ("50만원", "1,5 млн руб.") multiplies. "and"/"və"/"и" joins a
range only after a lead ("between", "от", "arasında"); without one it lists amounts ("müvafiq olaraq
300 və 500 manat" is two). Two amounts in different currencies, or a low above the high, never
merge.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from functools import cache

from apps.reference_data import ISO_4217_CODES
from apps.research.card_fields import _figure, evidence_rows
from apps.research.locale_names import fold

from . import Amount

_MARK = "[.,'’   ]"
#: A figure as money prints it. A group mark is always followed by exactly three digits, so a list
#: ("120, 180, 240") is three figures; and a figure never starts inside another (the lookbehinds),
#: which keeps a 4,000-character run of digits linear instead of quadratic.
_NUMBER = (
    rf"(?<!\d)(?<!\d{_MARK})"
    rf"(?:\d{{1,3}}(?:{_MARK}\d{{3}})+(?:[.,]\d{{1,2}})?|\d+(?:[.,]\d{{1,2}})?)(?:[.,]-)?"
)
#: Multiplier words, folded, as pages print them between a figure and its currency.
_MULTIPLIERS: dict[str, int] = {
    "만": 10_000, "억": 100_000_000, "천": 1_000, "万": 10_000, "千": 1_000, "億": 100_000_000,
    "k": 1_000, "тыс": 1_000, "тыс.": 1_000, "тысяч": 1_000, "млн": 1_000_000, "млн.": 1_000_000,
    "million": 1_000_000, "mln": 1_000_000, "milyon": 1_000_000, "bin": 1_000, "min": 1_000,
    "mio": 1_000_000, "mio.": 1_000_000, "millió": 1_000_000, "ezer": 1_000,
}
_CJK_MULTIPLIERS = "만억천万千億"
_MULT = "|".join(
    re.escape(m) if m in _CJK_MULTIPLIERS else re.escape(m) + r"(?![^\W\d_])"
    for m in sorted(_MULTIPLIERS, key=len, reverse=True)
)
#: Joiners that make a range on their own, and those ("and", "və") that need a lead.
_FREE_JOIN = r"~|～|–|—|-|to|à|a|bis|до"
_LEAD_JOIN = r"and|и|ve|və|et|ile|ilə"
_LEAD_BEFORE = re.compile(r"(?:between|entre|от|с|from|zwischen|von)\s*$", re.IGNORECASE)
_LEAD_AFTER = re.compile(r"^\s*(?:arasında|arasındakı|aralığında|arası)", re.IGNORECASE)
#: Words that list figures sharing one currency: "300 və 500 manat" is 300 manat and 500 manat.
_LIST = r",|and|или|or|и|ve|və|veya|yaxud|et"
_APPROX_BEFORE = re.compile(
    r"(?:about|approx\.?|approximately|around|roughly|circa|ca\.|около|примерно|приблизительно|"
    r"yaklaşık|təxminən|environ|etwa|körülbelül|kb\.|약)\s*$", re.IGNORECASE)
_APPROX_AFTER = re.compile(r"^\s*(?:내외|정도|가량|前後|左右|程度)")
_CONVERSION = re.compile(
    r"\s*\(\s*(?:approx\.?|about|ca\.|≈|~|около|примерно|yaklaşık|təxminən)?\s*", re.IGNORECASE)


def _ascii(text: str) -> str:
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch for ch in text)


@cache
def _codes_by_form() -> dict[str, frozenset[str]]:
    """Folded form -> every currency the evidence file lists it for ("manat" -> AZN and TMT)."""
    codes: dict[str, set[str]] = {}
    for row in evidence_rows():
        codes.setdefault(fold(row.form), set()).add(row.currency)
    return {form: frozenset(found) for form, found in codes.items()}


def _form_pattern(form: str) -> str:
    """A form that starts or ends with a letter may not continue a word: "lari" (GEL) is not the
    Turkish suffix in "Bursları", "yen" is not the end of "izleyen". After a CJK multiplier a sign
    may touch it ("50만원")."""
    pattern = re.escape(form)
    if form[0].isalpha():
        pattern = rf"(?:(?<![^\W\d_])|(?<=[{_CJK_MULTIPLIERS}])){pattern}"
    if form[-1].isalpha():
        pattern += r"(?![^\W\d_])"
    return pattern


@cache
def _currency_alternation() -> str:
    forms = sorted(_codes_by_form(), key=len, reverse=True)
    # ISO codes only in capitals ("eur 100" is not an amount); listed forms case-insensitive
    codes = [rf"(?-i:(?<![A-Za-z]){c}(?![A-Za-z]))" for c in sorted(ISO_4217_CODES)]
    return "|".join([_form_pattern(f) for f in forms] + codes)


@cache
def _amount() -> re.Pattern[str]:
    cur = _currency_alternation()
    after = (rf"(?P<n2>{_NUMBER})(?:\s?(?P<m2>{_MULT}))?\s?(?:\([^()\d]{{1,40}}\)\s?)?"
             rf"(?P<c2>{cur})")
    before = rf"(?P<c1>{cur})\s?(?P<n1>{_NUMBER})(?:\s?(?P<m1>{_MULT}))?"
    return re.compile(rf"{before}|{after}", re.IGNORECASE)


def _value(number: str | None, multiplier: str | None) -> Decimal | None:
    if number is None:
        return None
    plain = re.sub(r"[.,]-$", "", _ascii(number.strip()))
    figure = _figure(plain)
    if figure is None and multiplier:
        # "1,5 млн": before a multiplier a comma is a decimal mark, not money's group rule
        try:
            figure = Decimal(plain.replace(",", ".").replace(" ", ""))
        except ArithmeticError:
            return None
    if figure is None:
        return None
    return figure * _MULTIPLIERS[fold(multiplier)] if multiplier else figure


def _currencies(form: str) -> frozenset[str]:
    if form in ISO_4217_CODES:
        return frozenset({form})
    return _codes_by_form().get(fold(form), frozenset())


def _same_currency(a: Amount, b: Amount) -> bool:
    return not a.currencies or not b.currencies or bool(a.currencies & b.currencies)


def _range(line: str, low: Amount, high: Amount, join: str) -> bool:
    """Whether `low` and `high`, with `join` between them, are one range."""
    if low.low is None or high.high is None or low.low >= high.high:
        return False
    if "range" in (low.bound, high.bound):
        return False
    if not _same_currency(low, high):
        return False
    if re.fullmatch(rf"\s*(?:{_FREE_JOIN})\s*", join, re.IGNORECASE):
        return True
    return bool(
        re.fullmatch(rf"\s*(?:{_LEAD_JOIN})\s*", join, re.IGNORECASE)
        and (_LEAD_BEFORE.search(line[max(0, low.start - 20):low.start])
             or _LEAD_AFTER.match(line[high.end:]))
    )


def _merged(line: str, low: Amount, high: Amount) -> Amount:
    both = low.currencies & high.currencies
    return Amount(line[low.start:high.end], low.start, high.end, low.low, high.high,
                  high.currency or low.currency, "range", None,
                  both or low.currencies or high.currencies)


def _raw(line: str) -> list[Amount]:
    raw: list[Amount] = []
    for match in _amount().finditer(line):
        value = _value(match.group("n1") or match.group("n2"),
                       match.group("m1") or match.group("m2"))
        currencies = _currencies(match.group("c1") or match.group("c2"))
        single = next(iter(currencies)) if len(currencies) == 1 else None
        raw.append(Amount(match.group(0).strip(), match.start(), match.end(), value, value,
                          single, None, None, currencies))
    return raw


def _bare(line: str, start: int, end: int, like: Amount) -> Amount:
    """A figure the page printed without its currency, which it shares with `like`."""
    text = line[start:end]
    match = re.match(rf"({_NUMBER})(?:\s?({_MULT}))?", text, re.IGNORECASE)
    value = _value(match.group(1), match.group(2)) if match else None
    return Amount(text, start, end, value, value, like.currency, None, None, like.currencies)


def find_amounts(line: str) -> list[Amount]:
    raw = _raw(line)
    out: list[Amount] = []
    for i, amount in enumerate(raw):
        previous = out[-1] if out else None
        floor = previous.end if previous else 0
        if previous is not None and _range(line, previous, amount, line[previous.end:amount.start]):
            out[-1] = _merged(line, previous, amount)
            continue
        # a bare figure joined to this amount: "entre 1 200 et 2 100 €", "от 10 000 до 20 000 руб"
        tail_start = max(floor, amount.start - 60)
        tail = line[tail_start:amount.start]
        bare = re.search(rf"(?P<n>{_NUMBER})(?:\s?(?P<m>{_MULT}))?(?P<j>\s*(?:{_FREE_JOIN}|"
                         rf"{_LEAD_JOIN})\s*)$", tail, re.IGNORECASE)
        if bare is not None:
            low_end = bare.end("m") if bare.group("m") else bare.end("n")
            low = _bare(line, tail_start + bare.start(), tail_start + low_end, amount)
            if _range(line, low, amount, bare.group("j")):
                out.append(_merged(line, low, amount))
                continue
        # bare figures listed before this amount share its currency: "110, 160 və 200 manat"
        listed: list[Amount] = []
        cursor = amount.start
        while True:
            item = re.search(rf"(?P<n>{_NUMBER})(?:\s?(?P<m>{_MULT}))?\s*(?:{_LIST})\s*$",
                             line[max(floor, cursor - 40):cursor], re.IGNORECASE)
            if item is None:
                break
            offset = max(floor, cursor - 40)
            listed.insert(0, _bare(line, offset + item.start(),
                                   offset + (item.end("m") if item.group("m") else item.end("n")),
                                   amount))
            cursor = offset + item.start()
        out.extend(listed)
        # a bare figure after it: "¥143,000～145,000", "EUR 1 000 – 2 000"
        following = raw[i + 1].start if i + 1 < len(raw) else len(line)
        ahead = re.match(rf"\s*(?:{_FREE_JOIN})\s*(?P<n>{_NUMBER})(?:\s?(?P<m>{_MULT}))?",
                         line[amount.end:following], re.IGNORECASE)
        if ahead is not None:
            high = _bare(line, amount.end + ahead.start("n"), amount.end + ahead.end(), amount)
            if _range(line, amount, high, line[amount.end:high.start]):
                out.append(_merged(line, amount, high))
                continue
        before = line[max(0, amount.start - 16):amount.start]
        bound = None
        if _APPROX_BEFORE.search(before) or _APPROX_AFTER.match(line[amount.end:]):
            bound = "approximately"
        converted = None
        if (previous is not None and _CONVERSION.fullmatch(line[previous.end:amount.start])
                and previous.currencies and amount.currencies
                and not previous.currencies & amount.currencies):
            converted = len(out) - 1
            bound = None  # "approx." inside a conversion qualifies the conversion, not the award
        out.append(Amount(amount.text, amount.start, amount.end, amount.low, amount.high,
                          amount.currency, bound, converted, amount.currencies))
    return out
```

Implementer notes, which are part of the task:
- `"1,5 млн руб."`: `_figure("1,5")` refuses (one digit after a mark), so `_value` falls back to a
  decimal comma only when a multiplier follows; a bare "1,5 €" stays `None` (pinned).
- `_NUMBER`'s lookbehinds are what keep a 4,000-character run of digits at 13 ms instead of 3 s
  (measured); keep them if the pattern is ever changed, and keep `test_long_runs_of_digits_stay_linear`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_amounts.py tests/research/test_card_fields.py -q`
Expected: all pass (11 in `test_amounts.py`).

- [ ] **Step 6: Commit**

```bash
git add apps/research/candidates tests/research/candidates docs/research/currency-evidence.csv
git commit -m "feat(research): amount candidates -- ranges, approximations, conversions and multipliers by code"
```

---

### Task 4: Date candidates

**Files:**
- Create: `apps/research/candidates/dates.py`
- Modify: `apps/research/candidates/__init__.py` (append `Date`)
- Test: `tests/research/candidates/test_dates.py`

**Interfaces:**
- Consumes: `apps.research.locale_names.inflected`, `lookup`, `month_forms` (Task 1).
- Produces: `Date` (below) and `find_dates(line: str) -> list[Date]`. An ambiguous slash date keeps
  its two numbers in `first`/`second` (and `end_first`/`end_second` for a range's end), so Jev's
  date_order answer can be applied without re-parsing the text.

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/candidates/test_dates.py
from apps.research.candidates.dates import find_dates


def parts(line):
    found = find_dates(line)
    assert len(found) == 1, found
    d = found[0]
    return (d.year, d.month, d.day, d.end_year, d.end_month, d.end_day)


def test_absolute_dates_in_several_languages():
    assert parts("Deadline: 15 March 2026") == (2026, 3, 15, None, None, None)
    assert parts("до 1 февраля 2027 г.") == (2027, 2, 1, None, None, None)
    assert parts("Son müraciət tarixi - 20 may 2026") == (2026, 5, 20, None, None, None)
    assert parts("Başvurular 15 Ocak 2026'da sona erer") == (2026, 1, 15, None, None, None)
    assert parts("2026年3月15日まで") == (2026, 3, 15, None, None, None)
    assert parts("2026. február 15.") == (2026, 2, 15, None, None, None)
    assert parts("2026-03-15") == (2026, 3, 15, None, None, None)


def test_month_year_is_never_clipped_to_a_day():
    assert parts("Applications open in February 2027") == (2027, 2, None, None, None, None)


def test_ranges_are_one_candidate():
    assert parts("с 1 февраля по 31 июля 2026 года") == (2026, 2, 1, 2026, 7, 31)
    assert parts("Applications: 1–15 March 2026") == (2026, 3, 1, 2026, 3, 15)
    assert parts("müraciət tarixləri fevral-aprel aylarını əhatə edəcək") == (
        None, 2, None, None, 4, None)
    assert parts("Qəbul may-iyun aylarında") == (None, 5, None, None, 6, None)
    assert parts("접수기간: 3월 2일 ~ 3월 20일") == (None, 3, 2, None, 3, 20)


def test_suffix_ranges_in_azerbaijani_and_turkish():
    assert parts("Qeydiyyat 1 fevraldan 31 iyuladək davam edir") == (None, 2, 1, None, 7, 31)
    assert parts("Başvurular 15 Ocak'tan 15 Şubat'a kadar") == (None, 1, 15, None, 2, 15)


def test_and_lists_dates_unless_a_lead_makes_it_a_range():
    assert len(find_dates("Deadlines: 1 April and 1 October 2026")) == 2
    assert len(find_dates("Исключение — декабрь и апрель")) == 2
    assert parts("apply between October and January") == (None, 10, None, None, 1, None)


def test_slash_dates_with_both_parts_under_13_are_ambiguous():
    d = find_dates("Deadline 10/11/2026")[0]
    assert d.order_ambiguous and d.year == 2026 and (d.first, d.second) == (10, 11)
    d = find_dates("Deadline 25/11/2026")[0]
    assert not d.order_ambiguous and (d.day, d.month) == (25, 11)
    d = find_dates("Son tarix 10.11.2026")[0]
    assert not d.order_ambiguous and (d.day, d.month) == (10, 11)
    d = find_dates("Deadline 10/11/2026 to 12/12/2026")[0]
    assert d.order_ambiguous and (d.end_first, d.end_second) == (12, 12)


def test_codes_grades_and_intakes_are_not_dates():
    assert find_dates("Направление 37.03.01 Психология") == []
    assert find_dates("Направление 09.03.01 Информатика") == []
    assert find_dates("minimum 71 bal") == []
    assert find_dates("2026/27 academic year") == []
    assert find_dates("Founded in 1998") == []
    assert find_dates("10 Marmara Üniversitesi") == []


def test_ordinary_words_are_not_months():
    assert find_dates("students may apply") == []
    assert find_dates("they march on campus") == []
    assert find_dates("MSc Renewable Energy; Enerji Sistemleri") == []
    assert find_dates("Gerekli belgeler listesi") == []


def test_qualified_and_prepositional_months():
    assert [d.month for d in find_dates("Results in late March or early April.")] == [3, 4]
    assert parts("Applications open in March") == (None, 3, None, None, None, None)


def test_a_numeric_month_day_in_cjk_without_year():
    assert parts("3월 15일 마감") == (None, 3, 15, None, None, None)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_dates.py -q`
Expected: FAIL with `ModuleNotFoundError` or `ImportError: cannot import name 'find_dates'`

- [ ] **Step 3: Implement**

Append to `candidates/__init__.py`:

```python
@dataclass(frozen=True)
class Date:
    text: str
    start: int
    end: int
    year: int | None
    month: int | None
    day: int | None          # None when the page states no day: never invented
    end_year: int | None = None
    end_month: int | None = None
    end_day: int | None = None
    order_ambiguous: bool = False  # "10/11/2026": Jev's date_order question decides
    first: int | None = None       # the two numbers of an ambiguous date, in printed order
    second: int | None = None
    end_first: int | None = None
    end_second: int | None = None
```

Then:

```python
# apps/research/candidates/dates.py
"""Dates as the page printed them: code parses day, month and year; Jev is asked only a date's role,
and its order when a slash date is ambiguous (verified-catalog §5 step 4).

Measured 2026-10-03 on session f7's v5 key: 208 of 211 key dates found across 8 languages once
year-only and academic-year spans go to the intake finder. A span with no day is a month, never
given one: the 2026-09-27 run's every "wrong day" was "February 2027" clipped to "February 20".
"""

from __future__ import annotations

import re
from functools import cache

from apps.research.locale_names import inflected, lookup, month_forms

from . import Date

_ORDINAL = r"(?:st|nd|rd|th|er|-?(?:ci|cı|cu|cü|si|sı|su|sü|inci|ıncı|nci|ncı))?"
#: Joiners that make a range on their own; "and"-words make one only after a lead
#: ("between October and January"), otherwise they list ("1 April and 1 October 2026").
_FREE_JOIN = re.compile(
    r"^\s*(?:[–—~～-]|to|until|till|through|по|до|-?(?:dək|dek|qədər|kadar)|bis|au|부터)\s*$",
    re.IGNORECASE)
_LEAD_JOIN = re.compile(r"^\s*(?:and|и|ve|və|et|ile|ilə|및)\s*$", re.IGNORECASE)
_RANGE_LEAD = re.compile(r"(?:from|between|с|от|entre|du|vom|von|zwischen)\s*$", re.IGNORECASE)
#: An ablative ending on the first date joins it to the next: "1 fevraldan 31 iyuladək",
#: "15 Ocak'tan 15 Şubat'a kadar", "13 iyuldan 22 iyul".
_ABLATIVE = re.compile(r"(?:['’]?(?:n?d|t)[aeə]n)$", re.IGNORECASE)
#: English month names that are also ordinary words; alone they count only after a preposition
#: and with a capital ("in March"), never in "they march on campus" or "students may apply".
_WORD_MONTHS = {"march", "may"}
_QUALIFIER = r"(?:late|early|mid|end of|beginning of|the end of|start of)"
_PREPOSITION = r"(?:in|by|until|before|after|from|since|during|of)"


@cache
def _forms() -> tuple[tuple[str, str, int], ...]:
    """Every month form; an abbreviation is matched exactly in every language, because a Turkish
    "Mar" free to take endings is the "Mar" of "10 Marmara Üniversitesi"."""
    wide = set(month_forms(wide_only=True))
    return tuple(form if form in wide else (form[0], "", form[2]) for form in month_forms())


@cache
def _month() -> str:
    return inflected((name, lang) for name, lang, _ in _forms())


@cache
def _wide_month() -> str:
    return inflected((name, lang) for name, lang, _ in month_forms(wide_only=True))


@cache
def _bare_month() -> str:
    """A wide month name standing alone ("fevral-aprel", "Noyabr ayından"): 4+ letters, and never
    a name that is also an English word."""
    return inflected(
        (name, lang) for name, lang, _ in month_forms(wide_only=True)
        if len(name) >= 4 and name not in _WORD_MONTHS
    )


def _month_number(token: str) -> int | None:
    return lookup(token.rstrip("."), _forms())


@cache
def _patterns() -> tuple[re.Pattern[str], ...]:
    m, wide, bare = _month(), _wide_month(), _bare_month()
    return tuple(re.compile(p, re.IGNORECASE) for p in (
        r"(?<!\d)(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})(?!\d)",
        rf"(?<!\d)(?P<d1>\d{{1,2}})\s*[–-]\s*(?P<d>\d{{1,2}})\.?\s+(?P<mn>{m})\.?"
        rf"(?:,?\s+(?P<y>\d{{4}}))?",
        # dotted dates carry a four-digit year: "09.03.01" is a Russian specialty code
        r"(?<![\d.])(?P<a>\d{1,2})(?P<sep>[./])(?P<b>\d{1,2})(?P=sep)(?P<y>\d{4}|(?<=/)\d{2})"
        r"(?![\d.])",
        rf"(?<!\d)(?P<d>\d{{1,2}}){_ORDINAL}\.?\s+(?P<mn>{m})\.?(?:,?\s+(?P<y>\d{{4}}))?(?!\d)",
        # year first ("2026. február 15.") before month-day, which would take "február 15" alone
        rf"(?<!\d)(?P<y>\d{{4}})\.?\s+(?P<mn>{m})\.?(?:\s+(?P<d>\d{{1,2}})\.?)?",
        rf"(?P<mn>{m})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th|\s?일|\s?日)?(?!\d)"
        rf"(?:,?\s+(?P<y>\d{{4}}))?",
        rf"(?P<mn>{m})\.?,?\s+(?P<y>\d{{4}})(?!\d)",
        r"(?P<y>\d{4})\s?[年년]\s?(?P<mo>\d{1,2})\s?[月월](?:\s?(?P<d>\d{1,2})\s?[日일])?",
        r"(?<![\d.])(?P<mo>\d{1,2})\s?[月월](?:\s?(?P<d>\d{1,2})\s?[日일])?",
        # month to month: "fevral-aprel", "may-iyun", "May–June"
        rf"(?P<mn>{wide})\s*[–—-]\s*(?P<mn2>{wide})",
        rf"{_QUALIFIER}\s+(?P<mn>{wide})",
        rf"(?<!\w){_PREPOSITION}\s+(?P<mn>(?-i:March|May))(?!\w)",
        rf"(?P<mn>{bare})",
    ))


def _ambiguous(match: re.Match[str], year: int | None) -> Date | None:
    a, b = int(match.group("a")), int(match.group("b"))
    text, start, end = match.group(0), match.start(), match.end()
    if match.group("sep") == ".":           # day-first wherever pages print dots
        day, month = a, b
    elif a > 12 and b <= 12:
        day, month = a, b
    elif b > 12 and a <= 12:
        day, month = b, a
    else:
        if not (1 <= a <= 12 and 1 <= b <= 12):
            return None
        return Date(text, start, end, year, None, None, order_ambiguous=True, first=a, second=b)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return Date(text, start, end, year, month, day)


def _single(match: re.Match[str]) -> Date | None:
    g = match.groupdict()
    year = int(g["y"]) if g.get("y") else None
    if year is not None and year < 100:
        year += 2000
    if g.get("sep"):
        return _ambiguous(match, year)
    month = int(g["mo"]) if g.get("mo") else (_month_number(g["mn"]) if g.get("mn") else None)
    day = int(g["d"]) if g.get("d") else None
    if month is None or not 1 <= month <= 12 or (day is not None and not 1 <= day <= 31):
        return None
    text, start, end = match.group(0), match.start(), match.end()
    if g.get("mn2"):  # "fevral-aprel": one candidate, two months, no day
        last = _month_number(g["mn2"])
        if last is None:
            return None
        return Date(text, start, end, None, month, None, None, last, None)
    if g.get("d1"):  # "1–15 March 2026": one candidate, both days in the same month
        first = int(g["d1"])
        if not 1 <= first <= 31:
            return None
        return Date(text, start, end, year, month, first, year, month, day)
    return Date(text, start, end, year, month, day)


def _spans(line: str) -> list[Date]:
    taken: list[Date] = []
    for pattern in _patterns():
        for match in pattern.finditer(line):
            if any(match.start() < t.end and t.start < match.end() for t in taken):
                continue
            date = _single(match)
            if date is not None:
                taken.append(date)
    return sorted(taken, key=lambda d: d.start)


def _joined(line: str, previous: Date, date: Date) -> bool:
    gap = line[previous.end:date.start]
    if _FREE_JOIN.match(gap):
        return True
    if not gap.strip() and _ABLATIVE.search(previous.text):
        return True
    return bool(_LEAD_JOIN.match(gap) and _RANGE_LEAD.search(line[:previous.start]))


def find_dates(line: str) -> list[Date]:
    out: list[Date] = []
    for date in _spans(line):
        previous = out[-1] if out else None
        if previous is not None and previous.end_month is None and _joined(line, previous, date):
            out[-1] = Date(
                line[previous.start:date.end], previous.start, date.end,
                previous.year or date.year, previous.month or date.month, previous.day,
                date.year or previous.year, date.month, date.day,
                previous.order_ambiguous or date.order_ambiguous,
                previous.first, previous.second, date.first, date.second,
            )
            continue
        out.append(date)
    return out
```

Implementer notes, which are part of the task:
- Year inheritance in a range: "с 1 февраля по 31 июля 2026 года" — the first span has no year; the
  merge takes the second's. That is the only inference allowed; never infer a year from today.
- Merging requires the previous date's `end_month` to be empty, so three dates never fold into one.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_dates.py -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/candidates tests/research/candidates/test_dates.py
git commit -m "feat(research): date candidates -- parts by code, month-only kept, ranges, ambiguous slash order"
```

---

### Task 5: Relative dates

**Files:**
- Modify: `apps/research/candidates/dates.py`, `apps/research/candidates/__init__.py`
- Test: `tests/research/candidates/test_relative_dates.py`

**Interfaces:**
- Produces: `RelativeDate` (below) and `find_relative_dates(line: str) -> list[RelativeDate]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/candidates/test_relative_dates.py
from apps.research.candidates.dates import find_relative_dates

FULBRIGHT = ("Fulbright operates on a yearly application cycle, which generally opens "
             "approximately 15 months before the anticipated start of the grant with a deadline "
             "approximately 11 or 12 months before the grant's start date.")


def test_fulbright_gives_two_relative_dates():
    opening, deadline = find_relative_dates(FULBRIGHT)
    assert (opening.low, opening.high, opening.unit, opening.direction) == (
        15, 15, "months", "before")
    assert opening.approximately and opening.anchor == "the anticipated start of the grant"
    assert (deadline.low, deadline.high, deadline.approximately) == (11, 12, True)
    assert deadline.anchor == "the grant's start date"


def test_russian_turkish_and_azerbaijani_forms():
    (ru,) = find_relative_dates("Заявки принимаются за 6 месяцев до начала обучения.")
    assert (ru.low, ru.unit, ru.direction, ru.anchor) == (6, "months", "before", "начала обучения")
    (tr,) = find_relative_dates("Başvurular programın başlangıcından yaklaşık 3 ay önce kapanır.")
    assert (tr.low, tr.unit, tr.direction, tr.approximately) == (3, "months", "before", True)
    (az,) = find_relative_dates("Müraciətlər təhsilin başlanmasından 2 ay əvvəl bitir.")
    assert (az.low, az.unit, az.direction) == (2, "months", "before")


def test_a_duration_is_not_a_relative_date():
    assert find_relative_dates("The scholarship lasts 12 months.") == []


def test_the_turkic_anchor_is_the_noun_phrase_before_the_ablative():
    (az,) = find_relative_dates("Müraciətlər təhsilin başlanmasından 2 ay əvvəl bitir.")
    assert az.anchor == "təhsilin başlanması" and az.text.startswith("təhsilin")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_relative_dates.py -q`
Expected: FAIL with `ImportError: cannot import name 'find_relative_dates'`

- [ ] **Step 3: Implement**

Append to `candidates/__init__.py`:

```python
@dataclass(frozen=True)
class RelativeDate:
    text: str
    start: int
    end: int
    low: int                 # 15, or 11 in "11 or 12"
    high: int                # == low unless a range
    unit: str                # "months" | "weeks" | "days" | "years"
    direction: str           # "before" | "after"
    anchor: str              # verbatim: "the anticipated start of the grant"
    approximately: bool
```

In `dates.py`, change `from . import Date` to `from . import Date, RelativeDate`, then append:

```python
_UNITS = {
    "month": "months", "months": "months", "месяц": "months", "месяца": "months",
    "месяцев": "months", "ay": "months", "week": "weeks", "weeks": "weeks", "недел": "weeks",
    "hafta": "weeks", "həftə": "weeks", "day": "days", "days": "days", "дн": "days",
    "день": "days", "gün": "days", "year": "years", "years": "years", "год": "years",
    "лет": "years", "yıl": "years", "il": "years",
}
_APPROX = r"approximately|about|around|roughly|some|примерно|около|приблизительно|yaklaşık|təxminən"
_END = r"(?=\s+(?:with|and|while|which|or|и|ile|ve|və)\b|[.,;:]|$)"
_EN = re.compile(
    rf"(?:(?P<ap>{_APPROX})\s+)?(?P<lo>\d{{1,3}})(?:\s*(?:or|to|–|-)\s*(?P<hi>\d{{1,3}}))?\s+"
    rf"(?P<unit>months?|weeks?|days?|years?)\s+(?P<dir>before|after|prior to|ahead of)\s+"
    rf"(?P<anchor>.{{3,80}}?){_END}", re.IGNORECASE)
_RU = re.compile(
    rf"(?:(?P<ap>{_APPROX})\s+)?за\s+(?P<lo>\d{{1,3}})(?:\s*[–-]\s*(?P<hi>\d{{1,3}}))?\s+"
    rf"(?P<unit>месяц\w*|недел\w*|дн\w*|день|год\w*|лет)\s+(?P<dir>до)\s+"
    rf"(?P<anchor>.{{3,80}}?){_END}", re.IGNORECASE)
#: The Turkic offset is found from its number and direction ("2 ay əvvəl"); the anchor, the noun
#: phrase in the ablative before it, is then read from at most 80 characters back. Searching for the
#: anchor first cost 80 steps at every position of the line.
_TURKIC = re.compile(
    rf"(?:(?P<ap>{_APPROX})\s+)?(?P<lo>\d{{1,3}})(?:\s*[–-]\s*(?P<hi>\d{{1,3}}))?\s+"
    rf"(?P<unit>ay|hafta|həftə|gün|yıl|il)\s+(?P<dir>önce|əvvəl|sonra)", re.IGNORECASE)
_TURKIC_ANCHOR = re.compile(
    r"(?P<anchor>[^.,;]{3,80}?)'?(?:n?dan|n?dən|n?den|n?tan|n?tən|n?ten)\s+$", re.IGNORECASE)
_DIRECTION = {"before": "before", "prior to": "before", "ahead of": "before", "до": "before",
              "önce": "before", "əvvəl": "before", "after": "after", "sonra": "after"}


def _unit(word: str) -> str:
    folded = word.casefold()
    for key in sorted(_UNITS, key=len, reverse=True):
        if folded.startswith(key):
            return _UNITS[key]
    raise ValueError(word)


def find_relative_dates(line: str) -> list[RelativeDate]:
    """Offsets from an anchor. The Turkic anchor is the last two words before the ablative
    ending, verbatim ("təhsilin başlanması"); it never becomes a date here."""
    found: list[RelativeDate] = []
    for pattern in (_EN, _RU, _TURKIC):
        for m in pattern.finditer(line):
            start = m.start()
            if pattern is _TURKIC:
                back = max(0, start - 80)
                anchored = _TURKIC_ANCHOR.search(line[back:start])
                if anchored is None:
                    continue
                anchor = " ".join(anchored.group("anchor").split()[-2:])
                start = back + anchored.start() + anchored.group(0).index(anchor)
            else:
                anchor = m.group("anchor").strip()
            low = int(m.group("lo"))
            high = int(m.group("hi")) if m.group("hi") else low
            found.append(RelativeDate(line[start:m.end()], start, m.end(), low, high,
                                      _unit(m.group("unit")),
                                      _DIRECTION[m.group("dir").casefold()], anchor,
                                      bool(m.group("ap"))))
    return sorted(found, key=lambda r: r.start)
```

An anchor never becomes a date here. Slice 3 turns a relative date into a calendar date only when
the anchor is the intake and the intake's date is known, shown as approximate (verified-catalog §5
step 4).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_relative_dates.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/candidates tests/research/candidates/test_relative_dates.py
git commit -m "feat(research): relative-date candidates -- offset, unit, direction and anchor by code"
```

---

### Task 6: Durations and intakes

**Files:**
- Create: `apps/research/candidates/spans.py`
- Modify: `apps/research/candidates/__init__.py`
- Test: `tests/research/candidates/test_spans.py`

**Interfaces:**
- Consumes: `apps.funding.validity.intake_start_year` (the one rule for an intake's first year);
  `find_relative_dates` (Task 5).
- Produces: `Duration`, `Intake` (below), `find_durations(line) -> list[Duration]`,
  `find_intakes(line) -> list[Intake]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/candidates/test_spans.py
from apps.research.candidates.spans import find_durations, find_intakes


def test_durations_in_several_languages():
    (d,) = find_durations("for 12 months a year")
    assert (d.count, d.unit, d.months) == (12, "months", 12)
    (d,) = find_durations("Master's: 2 years")
    assert (d.unit, d.months) == ("years", 24)
    (d,) = find_durations("Magistratura: 4 semestr")
    assert (d.count, d.unit, d.months) == (4, "semesters", None)
    (d,) = find_durations("석사과정 : 4학기")
    assert (d.count, d.unit) == (4, "semesters")


def test_the_standard_period_of_study_has_no_number():
    (d,) = find_durations("for the standard period of study")
    assert (d.count, d.unit, d.months) == (None, "programme", None)
    (d,) = find_durations("на весь период обучения")
    assert d.unit == "programme"


def test_a_relative_date_is_not_a_duration():
    assert find_durations("opens approximately 15 months before the start of the grant") == []
    assert find_durations("Namizədlərin siyahısı elan edilir 1 il əvvəl") == []


def test_intakes():
    (i,) = find_intakes("2026/27 academic year")
    assert (i.start_year, i.end_year) == (2026, 2027)
    (i,) = find_intakes("2025-2026-cı tədris ili")
    assert (i.start_year, i.end_year) == (2025, 2026)
    (i,) = find_intakes("Fall 2026 intake")
    assert (i.start_year, i.season) == (2026, "Fall")
    assert find_intakes("Founded in 1998") == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_spans.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.candidates.spans'`

- [ ] **Step 3: Implement**

Append to `candidates/__init__.py`:

```python
@dataclass(frozen=True)
class Duration:
    text: str
    start: int
    end: int
    count: int | None   # None for "the standard period of study"
    unit: str           # "months" | "years" | "semesters" | "programme"
    months: int | None  # count*12 for years, count for months; None for semesters and programme


@dataclass(frozen=True)
class Intake:
    text: str
    start: int
    end: int
    start_year: int
    end_year: int | None
    season: str | None  # verbatim season word, "Fall", "Payız", "Wintersemester"
```

Then:

```python
# apps/research/candidates/spans.py
"""Durations and intakes. Code multiplies years into months; a semester count stays a count,
because a semester's length is the institution's, never a guess (card_fields.duration_months'
rule)."""

from __future__ import annotations

import re

from apps.funding.validity import intake_start_year

from . import Duration, Intake
from .dates import find_relative_dates

_UNIT = (
    ("months", r"months?|ay(?:lıq|lik)?|месяц\w*|мес\.|hónap\w*|mois|monat\w*|개월|个月|か月|ヶ月"),
    ("years", r"years?|il|yıl|год\w*|лет|év\w*|ans?|jahr\w*|년|年"),
    ("semesters", r"semesters?|semestr\w*|dönem|семестр\w*|félév\w*|학기|学期"),
)
#: "1 il əvvəl" (one year before) is an offset, not how long anything lasts.
_OFFSET = r"(?!\s+(?:əvvəl|önce|before|prior|ago|sonra|after|later|назад|спустя))"
_COUNT = re.compile(
    r"(?<!\d)(?P<n>\d{1,2})\s?(?P<unit>" + "|".join(p for _, p in _UNIT) + r")(?!\w)" + _OFFSET,
    re.IGNORECASE)
_PROGRAMME = re.compile(
    r"standard period of study|regelstudienzeit|full duration of (?:the )?"
    r"(?:study|studies|programme|program)|entire (?:duration|period) of (?:study|the programme)|"
    r"весь период обучения|öğrenim süresi boyunca|tam təhsil müddəti|təhsil müddəti ərzində",
    re.IGNORECASE)
_INTAKE_YEARS = re.compile(r"(?<!\d)(?P<a>\d{4})\s*[/–-]\s*(?P<b>\d{4}|\d{2})(?!\d)")
_SEASON = re.compile(
    r"(?P<s>fall|autumn|spring|winter|summer|payız|yaz|güz|bahar|осен\w*|весен\w*|"
    r"wintersemester|sommersemester)\s+(?P<y>\d{4})", re.IGNORECASE)


def _unit_of(word: str) -> str:
    for unit, pattern in _UNIT:
        if re.fullmatch(pattern, word, re.IGNORECASE):
            return unit
    raise ValueError(word)


def find_durations(line: str) -> list[Duration]:
    relative = [(r.start, r.end) for r in find_relative_dates(line)]
    out: list[Duration] = []
    for m in _COUNT.finditer(line):
        if any(a <= m.start() < b for a, b in relative):
            continue
        count, unit = int(m.group("n")), _unit_of(m.group("unit"))
        months = count * 12 if unit == "years" else count if unit == "months" else None
        out.append(Duration(m.group(0), m.start(), m.end(), count, unit, months))
    for m in _PROGRAMME.finditer(line):
        out.append(Duration(m.group(0), m.start(), m.end(), None, "programme", None))
    return sorted(out, key=lambda d: d.start)


def find_intakes(line: str) -> list[Intake]:
    out: list[Intake] = []
    for m in _INTAKE_YEARS.finditer(line):
        start, tail = int(m.group("a")), m.group("b")
        end = int(tail) if len(tail) == 4 else (start // 100) * 100 + int(tail)
        if not 0 < end - start <= 6:
            continue
        year = intake_start_year(m.group(0))
        if year is not None:
            out.append(Intake(m.group(0), m.start(), m.end(), year, end, None))
    for m in _SEASON.finditer(line):
        out.append(Intake(m.group(0), m.start(), m.end(), int(m.group("y")), None, m.group("s")))
    return sorted(out, key=lambda i: i.start)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_spans.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/research/candidates tests/research/candidates/test_spans.py
git commit -m "feat(research): duration and intake candidates; a semester stays a count"
```

---

### Task 7: Places, levels and entry requirements

**Files:**
- Create: `apps/research/candidates/who.py`, `docs/research/region-names.csv`,
  `docs/research/place-aliases.csv`
- Modify: `apps/research/candidates/__init__.py`
- Test: `tests/research/candidates/test_who.py`

**Interfaces:**
- Consumes: `apps.research.locale_names.country_forms`, `fold`, `inflected`, `lookup` (Task 1);
  `apps.funding.regions.REGIONS`.
- Produces: `Place`, `Level`, `Requirement` (below); `find_places(line)`, `find_levels(line)`,
  `find_requirements(line)`. `Level.level` gains `"postgraduate"` (master or doctorate, as
  "Lisansüstü" and "postgraduate" say). `Requirement` carries its values: `test`, `score`, `cefr`,
  `scale`, `age_min`, `age_max` (inclusive; "under 35" is 34).

- [ ] **Step 1: Write the region names**

Every `region` value must be a key of `apps/funding/regions.py::REGIONS`; Step 3's test pins it.
A name in an inflecting language is matched by its stems, so the genitive forms Russian uses are
listed as their own rows. All-capital names ("EU", "AB", "ЕС") match in capitals only.

```csv
region,language,name
EU,en,European Union
EU,en,EU
EU,az,Avropa İttifaqı
EU,tr,Avrupa Birliği
EU,tr,AB
EU,ru,Европейский союз
EU,ru,Европейского союза
EU,ru,Европейском союзе
EU,ru,Евросоюз
EU,ru,ЕС
EU,fr,Union européenne
EU,fr,UE
EU,de,Europäische Union
EEA,en,European Economic Area
EEA,en,EEA
EEA,tr,Avrupa Ekonomik Alanı
EEA,ru,Европейская экономическая зона
EASTERN_PARTNERSHIP,en,Eastern Partnership
EASTERN_PARTNERSHIP,az,Şərq Tərəfdaşlığı
EASTERN_PARTNERSHIP,tr,Doğu Ortaklığı
EASTERN_PARTNERSHIP,ru,Восточное партнёрство
EASTERN_PARTNERSHIP,ru,Восточного партнёрства
WESTERN_BALKANS,en,Western Balkans
WESTERN_BALKANS,tr,Batı Balkanlar
ASEAN,en,ASEAN
AFRICAN_UNION,en,African Union
AFRICAN_UNION,tr,Afrika Birliği
COMMONWEALTH,en,Commonwealth
```

- [ ] **Step 2: Write the place aliases**

CLDR carries each country's name, not the demonyms and common names students meet ("Turkish",
"T.C. vatandaşı", "азербайджанские", "Turkey", "Republic of Korea", "UK"). Hand-seeded for the 30
countries this platform's students come from or go to. Russian adjectives are listed as their stem
("азербайджанск"), which takes any ending. Demonyms that are also a language name with an ending
("İngilizce", "Almanca") are left out, because "-ce/-ca" would read them as a place. **Follow-up,
not built here:** seed the full list from Wikidata P1549 (demonym) through `apps/research/wikidata.py`.

```csv
code,language,name
AZ,en,Azerbaijani
AZ,az,azərbaycanlı
AZ,tr,Azerbaycan
AZ,ru,азербайджанск
TR,en,Turkey
TR,en,Turkish
TR,az,türkiyəli
TR,tr,Türk vatandaşı
TR,tr,Türk vatandaşları
TR,tr,T.C. vatandaşı
TR,tr,T.C. vatandaşları
TR,tr,T.C.
TR,ru,Турецкой Республики
TR,ru,турецк
RU,en,Russian Federation
RU,az,Rusiya Federasiyası
RU,tr,Rusya Federasyonu
RU,ru,РФ
RU,ru,российск
KZ,en,Kazakh
KZ,en,Kazakhstani
KZ,az,qazaxıstanlı
KZ,ru,казахстанск
UZ,en,Uzbek
UZ,en,Uzbekistani
UZ,az,özbəkistanlı
UZ,ru,узбекистанск
KG,en,Kyrgyz
KG,az,qırğızıstanlı
KG,ru,кыргызск
KG,ru,киргизск
TM,en,Turkmen
TM,az,türkmənistanlı
TM,ru,туркменск
GE,en,Georgian
GE,az,gürcüstanlı
GE,ru,грузинск
UA,en,Ukrainian
UA,az,ukraynalı
UA,tr,Ukraynalı
UA,ru,украинск
BY,en,Belarusian
BY,az,belaruslu
BY,tr,Belaruslu
BY,ru,белорусск
IR,en,Iranian
IR,az,iranlı
IR,tr,İranlı
IR,ru,иранск
PK,en,Pakistani
PK,az,pakistanlı
PK,tr,Pakistanlı
PK,ru,пакистанск
IN,en,Indian
IN,az,hindistanlı
IN,tr,Hintli
IN,ru,индийск
CN,en,Chinese
CN,en,PRC
CN,az,çinli
CN,tr,Çinli
CN,ru,КНР
CN,ru,китайск
KR,en,Republic of Korea
KR,en,Korea
KR,en,Korean
KR,az,Koreya Respublikası
KR,tr,Kore Cumhuriyeti
KR,tr,Güney Kore
KR,ru,Республика Корея
KR,ru,Республики Корея
KR,ru,южнокорейск
JP,en,Japanese
JP,az,yaponiyalı
JP,ru,японск
DE,en,German
DE,az,almaniyalı
DE,ru,германск
FR,en,French
FR,fr,française
FR,fr,français
FR,az,fransalı
FR,ru,французск
GB,en,UK
GB,en,U.K.
GB,en,Great Britain
GB,en,Britain
GB,en,British
GB,az,Böyük Britaniya
GB,tr,İngiltere
GB,ru,Великобритания
GB,ru,британск
US,en,USA
US,en,U.S.
US,en,U.S.A.
US,en,United States of America
US,en,American
US,az,ABŞ
US,tr,ABD
US,ru,США
US,ru,американск
HU,en,Hungarian
HU,az,macarıstanlı
HU,ru,венгерск
IT,en,Italian
IT,az,italiyalı
IT,ru,итальянск
ES,en,Spanish
ES,az,ispaniyalı
ES,ru,испанск
PL,en,Polish
PL,az,polşalı
PL,tr,Polonyalı
PL,ru,польск
NL,en,Dutch
NL,en,Holland
NL,az,niderlandlı
NL,tr,Hollanda
NL,ru,нидерландск
NL,ru,голландск
SE,en,Swedish
SE,az,isveçli
SE,tr,İsveçli
SE,ru,шведск
FI,en,Finnish
FI,az,finlandiyalı
FI,tr,Finlandiyalı
FI,ru,финляндск
CZ,en,Czech
CZ,en,Czech Republic
CZ,az,çexiyalı
CZ,ru,чешск
AT,en,Austrian
AT,az,avstriyalı
AT,tr,Avusturyalı
AT,ru,австрийск
CH,en,Swiss
CH,az,isveçrəli
CH,tr,İsviçreli
CH,ru,швейцарск
HK,en,Hong Kong
```

- [ ] **Step 3: Write the failing tests**

```python
# tests/research/candidates/test_who.py
import csv
from decimal import Decimal
from pathlib import Path

from apps.funding.regions import REGIONS
from apps.research.candidates.who import find_levels, find_places, find_requirements

DOCS = Path(__file__).resolve().parents[3] / "docs" / "research"


def codes(line):
    return {p.code for p in find_places(line)}


def test_countries_by_their_names_in_the_page_language():
    assert codes("Azərbaycan Respublikasının vətəndaşları müraciət edə bilər") == {"AZ"}
    assert codes("студенты из Турции и Казахстана") == {"TR", "KZ"}
    assert codes("Students from Niger and Nigeria") == {"NE", "NG"}


def test_demonyms_and_common_names_from_the_alias_table():
    assert codes("Türk vatandaşı olmak") == {"TR"}
    assert codes("T.C. vatandaşları başvurabilir") == {"TR"}
    assert codes("open to Turkish and Kazakh citizens") == {"TR", "KZ"}
    assert codes("граждане Республики Корея и азербайджанские студенты") == {"KR", "AZ"}
    assert codes("Students from Turkey, the UK and the USA") == {"TR", "GB", "US"}
    assert codes("tell us about you") == set()


def test_regions_and_unknown_groups():
    places = find_places("Citizens of the European Union or of developing countries")
    assert ("EU", "region") in {(p.code, p.kind) for p in places}
    assert ("developing countries", "unknown_group") in {(p.text.casefold(), p.kind)
                                                         for p in places}
    assert [(p.code, p.kind) for p in find_places("Open to non-EU students only")] == [
        (None, "unknown_group")]
    assert codes("Le jury a eu lieu en mai") == set()
    assert codes("граждане Европейского союза") == {"EU"}
    assert codes("Avropa İttifaqına üzv ölkələr") == {"EU"}


def test_foreign_nationals_are_an_unknown_group():
    for line in ("Прием иностранных граждан", "xarici vətəndaşlar üçün",
                 "Yabancı uyruklu öğrenciler", "Open to foreign nationals"):
        assert [p.kind for p in find_places(line)] == ["unknown_group"], line


def test_ordinary_words_are_not_places():
    assert find_places("Mali destek programı") == []
    assert codes("Mali'den gelen öğrenciler") == {"ML"}
    assert find_places("children of staff") == []
    assert find_places("belge") == []
    assert find_places("Gerekli belgeler") == []
    assert find_places("того же года") == []
    assert codes("Hong Kong residents") == {"HK"}


def test_an_institution_named_after_a_place_still_yields_the_place():
    # the reader's eligible_pN question decides whether students of that institution may apply
    assert codes("Azərbaycan Dövlət Aqrar Universitetinə daxil olanlar") == {"AZ"}


def levels(line):
    return [found.level for found in find_levels(line)]


def test_levels_including_postdoc():
    assert levels("Yurt Dışı Doktora Sonrası Araştırma Bursu") == ["postdoc"]
    assert levels("yüksek lisans ve doktora öğrencileri") == ["master", "phd"]
    assert levels("Учитесь в магистратуре или на 3–4 курсе бакалавриата") == [
        "master", "bachelor"]
    assert levels("EMBO postdoctoral fellowships") == ["postdoc"]
    assert levels("석사과정 및 박사과정") == ["master", "phd"]
    assert levels("CALL FOR APPLICATIONS - BA/BSC, MA/MSC") == [
        "bachelor", "bachelor", "master", "master"]
    assert levels("Lisansüstü Burs Programları") == ["postgraduate"]
    assert levels("development-oriented postgraduate study programmes") == ["postgraduate"]


def test_words_that_contain_a_level_are_not_levels():
    assert levels("Masterclass on Mastercard payments") == []
    assert levels("promotion of the programme") == []
    assert levels("a valid driving licence") == []


def test_requirements():
    kinds = [r.kind for r in find_requirements(
        "IELTS 6.5 or TOEFL iBT 90; B2 level; GPA 3.0/4.0; under 35")]
    assert kinds == ["language_test", "language_test", "cefr", "grade", "age"]
    assert [r.kind for r in find_requirements("minimum 71 bal")] == ["grade"]
    assert [r.age_max for r in find_requirements("35 yaşdan çox olmayan")] == [35]
    assert find_requirements("Room A1 and B2 building") == []


def test_requirement_values():
    (r,) = find_requirements("English B2")
    assert (r.kind, r.cefr) == ("cefr", "B2")
    (r,) = find_requirements("GPA 3.0/4.0")
    assert (r.score, r.scale) == (Decimal("3.0"), Decimal("4.0"))
    (r,) = find_requirements("не старше 35 лет")
    assert r.age_max == 35
    (r,) = find_requirements("under 35")
    assert r.age_max == 34
    (r,) = find_requirements("TOPIK 3급")
    assert (r.test, r.score) == ("TOPIK", Decimal(3))
    (r,) = find_requirements("HSK 4")
    assert (r.test, r.score) == ("HSK", Decimal(4))
    (r,) = find_requirements("YDS 55")
    assert (r.test, r.score) == ("YDS", Decimal(55))
    (r,) = find_requirements("YÖKDİL 60")
    assert r.test == "YÖKDİL"
    (r,) = find_requirements("GPA of at least 3.0")
    assert r.score == Decimal("3.0")


def test_every_region_name_row_names_a_known_region():
    with (DOCS / "region-names.csv").open(encoding="utf-8") as handle:
        assert {row["region"] for row in csv.DictReader(handle)} <= set(REGIONS)


def test_every_alias_row_names_an_alpha_2_code():
    with (DOCS / "place-aliases.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert all(len(row["code"]) == 2 and row["code"].isupper() for row in rows)
```

- [ ] **Step 4: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_who.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.candidates.who'`

- [ ] **Step 5: Implement**

Append to `candidates/__init__.py`:

```python
@dataclass(frozen=True)
class Place:
    text: str
    start: int
    end: int
    code: str | None   # ISO alpha-2, or a REGIONS key; None for an unknown group
    kind: str          # "country" | "region" | "unknown_group"


@dataclass(frozen=True)
class Level:
    text: str
    start: int
    end: int
    level: str  # "bachelor" | "master" | "phd" | "postdoc" | "postgraduate" (master or phd)


@dataclass(frozen=True)
class Requirement:
    text: str
    start: int
    end: int
    kind: str                      # "language_test" | "cefr" | "grade" | "age"
    test: str | None = None        # "IELTS", "TOEFL iBT", "TOPIK", "YDS", ...
    score: Decimal | None = None   # a test score or a grade
    cefr: str | None = None        # "B2"
    scale: Decimal | None = None   # 4.0 in "GPA 3.0/4.0"
    age_min: int | None = None
    age_max: int | None = None     # inclusive: "under 35" is 34
```

Then:

```python
# apps/research/candidates/who.py
"""Who may apply: places, degree levels and entry requirements, found by code.

A place inside an institution's name ("Azərbaycan Dövlət Aqrar Universiteti") is still a place
candidate: whether students of that institution may apply is the reader's `eligible_pN` question
(owner gold, 2026-10-05). A group this code cannot expand to countries ("developing countries", the
DAC list, the CIS, "foreign nationals") is `unknown_group`: counted as no_candidate, never guessed
(verified-catalog §5 step 4); its count says which `funding/regions.py` row to add, with its
defining URL.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Iterable
from decimal import Decimal
from functools import cache
from pathlib import Path

from apps.research.locale_names import country_forms, fold, inflected, lookup

from . import Level, Place, Requirement

_DOCS = Path(__file__).resolve().parents[3] / "docs" / "research"
REGION_NAMES_FILE = _DOCS / "region-names.csv"
PLACE_ALIASES_FILE = _DOCS / "place-aliases.csv"
#: Country names that are ordinary words on these pages: Turkish "mali" (financial, "Mali destek
#: programı"), Russian "того" (of that). "Mali'den" still reads as Mali.
_NOT_PLACES = frozenset({"того", "mali"})
_GROUPS = re.compile(
    r"(?<!\w)(?:developing countries|partner countries|programme countries|program countries|"
    r"non-EU|DAC list|least developed countries|CIS countries|Commonwealth of Independent States|"
    r"СНГ|Turkic States|Türk Dövlətləri|Türk Devletleri|OIC|İslam Əməkdaşlıq|İslam İşbirliği|"
    r"üçüncü ölkələr|third countries|en az gelişmiş ülkeler|"
    r"foreign nationals?|foreign citizens?|international students?|иностранн\w* граждан|"
    r"иностранн\w* студент|xarici vətəndaş|xarici tələbə|əcnəbi|yabancı uyruklu|"
    r"uluslararası öğrenci|ODA[- ]eligible|иностранн\w* гражданств|без гражданства)\w*",
    re.IGNORECASE)
_LEVELS = (
    ("postdoc", r"post-?doc\w*|postdoctoral|doktora sonrası|postdoktorantura|постдок\w*|박사후|"
                r"博士后|ポスドク"),
    ("postgraduate", r"post-?graduate\w*|(?<!\w)graduate (?:students?|stud\w+|programmes?|"
                     r"programs?|degrees?|school)|lisansüstü|послевузовск\w*"),
    ("master", r"(?<!\w)master'?s?(?!\w)|(?<!\w)(?-i:MA|MSc|MSC|M\.Sc\.?)(?!\w)|magistr\w*|"
               r"yüksek lisans|магистр\w*|mesterképzés|석사|硕士|修士"),
    ("phd", r"ph\.?\s?d|doctoral|doctorate|doktorantura|doktora(?! sonrası)|аспирант\w*|"
            r"докторант\w*|doktori|doctorat|박사(?!후)|博士(?!后)"),
    ("bachelor", r"bachelor'?s?|undergraduate|bakalavr\w*|(?<!yüksek )lisans(?!üstü)|"
                 r"бакалавр\w*|специалитет\w*|alapképzés|(?<!\w)(?-i:BA|BSc|BSC|B\.Sc\.?)"
                 r"(?!\w)|학사|本科|学士"),
)
_TEST = r"IELTS|TOEFL(?:\s*iBT)?|Duolingo|TOEIC|PTE|TOPIK|HSK|YDS|YÖKDİL|YOKDIL|e-YDS"
_LANGUAGE_CUE = re.compile(
    r"english|german|french|russian|turkish|language|level|cefr|ingilis|alman|fransız|türk|rus|"
    r"dil|səviyyə|seviye|английск|немецк|французск|русск|турецк|язык|уровн|niveau|sprach|deutsch",
    re.IGNORECASE)


def _decimal(text: str | None) -> Decimal | None:
    return Decimal(text.replace(",", ".")) if text else None


def _language_test(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "language_test",
                       test=" ".join(m.group("test").split()), score=_decimal(m.group("score")))


def _grade(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "grade", score=_decimal(m.group("score")),
                       scale=_decimal(m.groupdict().get("scale")))


def _age_below(m: re.Match[str]) -> Requirement:
    # "under 35", "35 yaşını doldurmamış": not yet 35, so 34 at most
    return Requirement(m.group(0), m.start(), m.end(), "age", age_max=int(m.group("age")) - 1)


def _age_max(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "age", age_max=int(m.group("age")))


def _age_min(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "age", age_min=int(m.group("age")))


def _age_span(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "age", age_min=int(m.group("lo")),
                       age_max=int(m.group("age")))


_REQUIREMENTS: tuple[tuple[str, Callable[[re.Match[str]], Requirement]], ...] = (
    (rf"(?<!\w)(?P<test>{_TEST})\s*(?:score\s*(?:of\s*)?|level\s*|:\s*)?"
     r"(?P<score>\d{1,3}(?:[.,]\d)?)(?:\s?급)?(?!\d)", _language_test),
    (r"(?<!\w)(?:C?GPA|ÜOMG|ortalama\w*|средний балл)\s*(?:of\s*)?(?:at least\s*|minimum\s*|"
     r"min\.?\s*|en az\s*|ən azı\s*|:\s*)?(?P<score>\d{1,3}(?:[.,]\d{1,2})?)"
     r"(?:\s*/\s*(?P<scale>\d{1,3}(?:[.,]\d{1,2})?))?(?![\d.,]?\d)", _grade),
    (r"(?<![\d.,])(?P<score>\d[.,]\d{1,2})(?:\s*/\s*(?P<scale>\d(?:[.,]\d{1,2})?))?"
     r"\s*C?GPA\b", _grade),
    (r"(?<![\d.,])(?P<score>\d{2,3})\s*(?:bal|балл\w*|points?|puan)\b", _grade),
    (r"(?:under|below|younger than)\s+(?:the age of\s+)?(?P<age>\d{2})(?!\d)", _age_below),
    (r"(?<!\d)(?P<age>\d{2})\s*yaşını\s+doldurmamış", _age_below),
    (r"(?:not older than|no older than|up to the age of|не старше)\s+(?P<age>\d{2})(?!\d)"
     r"(?:\s*(?:лет|years?))?", _age_max),
    (r"(?<!\d)(?P<age>\d{2})\s*(?:yaşdan|yaşından)\s+(?:çox olmayan|büyük olmayan)", _age_max),
    (r"(?:yaş sınırı|yaş həddi|age limit)\s*:?\s*(?P<age>\d{2})(?!\d)", _age_max),
    (r"(?:at least|не моложе|not younger than)\s+(?P<age>\d{2})\s*(?:years? old|лет)", _age_min),
    (r"(?:aged?|ages|yaş(?:ı|ları)?)\s+(?P<lo>\d{2})\s*(?:[–-]|to)\s*(?P<age>\d{2})(?!\d)",
     _age_span),
)


@cache
def _region_forms() -> tuple[tuple[str, str, str], ...]:
    with REGION_NAMES_FILE.open(encoding="utf-8", newline="") as handle:
        return tuple((row["name"], row["language"], row["region"])
                     for row in csv.DictReader(handle))


@cache
def _alias_forms() -> tuple[tuple[str, str, str], ...]:
    with PLACE_ALIASES_FILE.open(encoding="utf-8", newline="") as handle:
        return tuple((row["name"], row["language"], row["code"])
                     for row in csv.DictReader(handle))


def _acronym(name: str) -> bool:
    """"EU", "UK", "U.S.", "РФ": matched in capitals only ("us" is a pronoun)."""
    letters = name.replace(".", "")
    return " " not in name and len(letters) <= 5 and letters.isupper()


def _alternation(forms: Iterable[tuple[str, str, str]]) -> re.Pattern[str]:
    forms = list(forms)
    names = inflected((name, lang) for name, lang, _ in forms if not _acronym(name))
    acronyms = sorted({re.escape(name) for name, _, _ in forms if _acronym(name)},
                      key=len, reverse=True)
    if acronyms:
        names += rf"|(?-i:(?<!\w)(?:{'|'.join(acronyms)})(?!\w))"
    return re.compile(names, re.IGNORECASE)


def _folded(forms: Iterable[tuple[str, str, str]]) -> tuple[tuple[str, str, str], ...]:
    return tuple((" ".join(fold(name).split()), lang, value) for name, lang, value in forms)


@cache
def _regions() -> tuple[re.Pattern[str], tuple[tuple[str, str, str], ...]]:
    return _alternation(_region_forms()), _folded(_region_forms())


@cache
def _countries() -> tuple[re.Pattern[str], tuple[tuple[str, str, str], ...]]:
    forms = _alias_forms() + country_forms()
    return _alternation(forms), _folded(forms)


def find_places(line: str) -> list[Place]:
    out = [Place(m.group(0), m.start(), m.end(), None, "unknown_group")
           for m in _GROUPS.finditer(line)]
    for pattern, forms, kind in (_regions() + ("region",), _countries() + ("country",)):
        for m in pattern.finditer(line):
            if any(p.start < m.end() and m.start() < p.end for p in out):
                continue
            if fold(m.group(0)) in _NOT_PLACES:
                continue
            code = lookup(m.group(0), forms)
            if code is not None:
                out.append(Place(m.group(0), m.start(), m.end(), code, kind))
    return sorted(out, key=lambda p: p.start)


def find_levels(line: str) -> list[Level]:
    out: list[Level] = []
    for level, pattern in _LEVELS:
        for m in re.finditer(pattern, line, re.IGNORECASE):
            if not any(found.start <= m.start() < found.end for found in out):
                out.append(Level(m.group(0), m.start(), m.end(), level))
    return sorted(out, key=lambda found: found.start)


def _cefr(line: str) -> list[Requirement]:
    """A CEFR level counts only beside a language or level word: "Room B2" is a room."""
    out: list[Requirement] = []
    for m in re.finditer(r"(?<![\w-])(?P<cefr>[ABC][12])(?![\w-])", line):
        context = line[max(0, m.start() - 25):m.start()] + " " + line[m.end():m.end() + 15]
        if _LANGUAGE_CUE.search(context):
            out.append(Requirement(m.group(0), m.start(), m.end(), "cefr", cefr=m.group("cefr")))
    return out


def find_requirements(line: str) -> list[Requirement]:
    out = _cefr(line)
    for pattern, read in _REQUIREMENTS:
        for m in re.finditer(pattern, line, re.IGNORECASE):
            if not any(r.start < m.end() and m.start() < r.end for r in out):
                out.append(read(m))
    return sorted(out, key=lambda r: r.start)
```

Implementer note, part of the task: the case marker in "Учитесь в магистратуре" is a current-study
condition, not the award's level (owner gold): the candidate is still a `Level`; the reader's
`target_level` vs `requires_cN` criteria decide which it is (verified-catalog §5.2, at 4c2b69d1).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_who.py -q`
Expected: 12 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/research/candidates docs/research/region-names.csv docs/research/place-aliases.csv tests/research/candidates/test_who.py
git commit -m "feat(research): place, level and requirement candidates; unknown groups are counted, never guessed"
```

---

### Task 8: One assembler, keyed by name, and one finder for the harness

**Files:**
- Modify: `apps/research/candidates/__init__.py` (imports; add `Line`, `Found`, `Candidates`,
  `find_all`)
- Modify: `apps/research/engine_eval/evidence.py` (use the candidates)
- Test: `tests/research/candidates/test_find_all.py`; existing `tests/research/engine_eval/test_evidence.py`
  and `test_jev_reader.py` must still pass

**Interfaces:**
- Consumes: every finder from Tasks 3–7.
- Produces (slice 2 builds Jev's state from this): `Line(text, heading="", header="")`;
  `Found(line, value, from_header)`; `Candidates` with one `dict[str, Found[...]]` per kind keyed
  "m1", "d1", "r1", "u1", "i1", "p1", "l1", "c1", plus `conversion_of` ("m3" -> "m2");
  `Candidates.state()`; `Candidates.no_candidate(kind, flagged) -> list[int]`;
  `find_all(lines: Sequence[Line | str]) -> Candidates`, which reads each line's text and, when
  present, its column header (Task 8a adds the header's role cue). Do not touch
  `funding_judge.Line`; slice 3 deletes it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/research/candidates/test_find_all.py
from apps.research.candidates import find_all


def test_candidates_are_keyed_by_name_across_lines():
    c = find_all(["Stipend: 43,000 HUF per month for 12 months", "Deadline: 15 January 2027",
                  "Open to citizens of Azerbaijan", "Campus life"])
    assert set(c.amounts) == {"m1"} and c.amounts["m1"][0] == 0
    assert set(c.dates) == {"d1"} and c.dates["d1"].line == 1
    assert c.places["p1"].value.code == "AZ"
    assert c.state()["amounts"]["m1"] == {"text": "43,000 HUF", "line": 0, "from_header": False,
                                          "conversion_of": None}


def test_no_candidate_is_counted_per_kind_over_the_flagged_lines():
    c = find_all(["Stipend: 43,000 HUF", "Deadline: 15 January 2027", "Campus life",
                  "All costs are covered"])
    assert c.no_candidate("amounts", [0, 3]) == [3]
    assert c.no_candidate("dates", [1]) == []
    assert c.no_candidate("dates", [0, 1, 2]) == [0, 2]


def test_a_conversion_points_at_its_amount_by_key():
    c = find_all(["Tuition: 1,000 EUR", "Stipend: HUF 65,000 (approx. 180 EUR)"])
    assert c.state()["amounts"]["m3"]["conversion_of"] == "m2"
    assert c.state()["amounts"]["m2"]["conversion_of"] is None


def test_a_relative_date_is_never_also_a_duration():
    c = find_all(["opens approximately 15 months before the anticipated start of the grant"])
    assert len(c.relative_dates) == 1 and c.durations == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_find_all.py -q`
Expected: FAIL with `ImportError: cannot import name 'find_all'`

- [ ] **Step 3: Implement**

In `candidates/__init__.py`, replace the import block

```python
from dataclasses import dataclass
from decimal import Decimal
```

with

```python
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, NamedTuple
```

and append (the finder modules are imported inside `find_all`, because they import the dataclasses
from this package):

```python
@dataclass(frozen=True)
class Line:
    """One line of a page: its text, the heading it sits under, and, for a table cell, the
    column header ("신청시기") the cell's value is read with."""

    text: str
    heading: str = ""
    header: str = ""


class Found[T](NamedTuple):
    line: int          # index of the line in the list `find_all` was given
    value: T
    from_header: bool  # found in the line's column header, not in its text


@dataclass(frozen=True)
class Candidates:
    amounts: dict[str, Found[Amount]]                # "m1"
    dates: dict[str, Found[Date]]                    # "d1"
    relative_dates: dict[str, Found[RelativeDate]]   # "r1"
    durations: dict[str, Found[Duration]]            # "u1"
    intakes: dict[str, Found[Intake]]                # "i1"
    places: dict[str, Found[Place]]                  # "p1"
    levels: dict[str, Found[Level]]                  # "l1"
    requirements: dict[str, Found[Requirement]]      # "c1"
    conversion_of: dict[str, str] = field(default_factory=dict)  # "m3" -> "m2"

    def _groups(self) -> dict[str, Mapping[str, Found[Any]]]:
        return {"amounts": self.amounts, "dates": self.dates, "relative_dates": self.relative_dates,
                "durations": self.durations, "intakes": self.intakes, "places": self.places,
                "levels": self.levels, "requirements": self.requirements}

    def state(self) -> dict[str, dict[str, dict[str, object]]]:
        """{"amounts": {"m1": {"text": ..., "line": 0, ...}}, ...} -- Jev's state, keyed by name."""
        out: dict[str, dict[str, dict[str, object]]] = {}
        for group, items in self._groups().items():
            out[group] = {}
            for key, found in items.items():
                entry: dict[str, object] = {"text": found.value.text, "line": found.line,
                                            "from_header": found.from_header}
                if group == "amounts":
                    entry["conversion_of"] = self.conversion_of.get(key)
                out[group][key] = entry
        return out

    def no_candidate(self, kind: str, flagged: Iterable[int]) -> list[int]:
        """The flagged line indexes where the `kind` finder ("amounts", "dates", ...) found
        nothing: the lines a reader said carry such a value and code could not show one."""
        seen = {found.line for found in self._groups()[kind].values()}
        return sorted({n for n in flagged if n not in seen})


def _keyed[T](prefix: str, finder: Callable[[str], Sequence[T]],
              rows: Sequence[tuple[int, str, bool]]) -> dict[str, Found[T]]:
    out: dict[str, Found[T]] = {}
    for n, text, from_header in rows:
        for value in finder(text):
            out[f"{prefix}{len(out) + 1}"] = Found(n, value, from_header)
    return out


def find_all(lines: Sequence[Line | str]) -> Candidates:
    """Every candidate on every line, keyed by name. A line's column header is read too, and what
    it yields is marked `from_header`."""
    # The finder modules import the dataclasses above, so they are imported here, not at the top.
    from .amounts import find_amounts
    from .dates import find_dates, find_relative_dates
    from .spans import find_durations, find_intakes
    from .who import find_levels, find_places, find_requirements

    rows: list[tuple[int, str, bool]] = []
    for n, raw in enumerate(lines):
        line = Line(raw) if isinstance(raw, str) else raw
        rows.append((n, line.text, False))
        if line.header:
            rows.append((n, line.header, True))

    amounts: dict[str, Found[Amount]] = {}
    conversion_of: dict[str, str] = {}
    for n, text, from_header in rows:
        keys: list[str] = []
        for amount in find_amounts(text):
            key = f"m{len(amounts) + 1}"
            amounts[key] = Found(n, amount, from_header)
            keys.append(key)
            if amount.converted_from is not None:
                conversion_of[key] = keys[amount.converted_from]

    return Candidates(
        amounts, _keyed("d", find_dates, rows), _keyed("r", find_relative_dates, rows),
        _keyed("u", find_durations, rows), _keyed("i", find_intakes, rows),
        _keyed("p", find_places, rows), _keyed("l", find_levels, rows),
        _keyed("c", find_requirements, rows), conversion_of,
    )
```

Then switch the harness to the same finders, so the evidence the scorer leans on is the production
finder, not a second copy. `apps/research/engine_eval/evidence.py` becomes (`amounts()` keeps its
name: `jev_reader.py` and `test_evidence.py` import it; `_NATIONALITY` and `_THRESHOLD` stay, because
they flag eligibility wording, which places alone do not):

```python
"""Deterministic evidence a 'yes' can lean on (research 2026-10-03: a second bar, not a gate).

The scorer gives each tier two bars -- one for lines where code found this evidence, one for
lines where it did not -- so evidence lowers the bar where it exists instead of hiding facts
code missed.
"""

from __future__ import annotations

import re

from apps.research.candidates.amounts import find_amounts
from apps.research.candidates.dates import find_dates, find_relative_dates
from apps.research.candidates.who import find_levels

_NATIONALITY = re.compile(
    r"citizen|national|international student|foreign|resident|"
    r"vətəndaş|əcnəbi|xarici|"
    r"vatandaş|uluslararası öğrenci|yabancı|"
    r"граждан|иностран|соотечественник|резидент", re.IGNORECASE)
_THRESHOLD = re.compile(
    r"gpa|cgpa|ielts|toefl|gre|gmat|ümumi orta|üomg|\bdil\b|yaş|age|не старше|не моложе|"
    r"не менее|at least|minimum|en az|ən azı|\b\d{2,3}\s*(?:\+|%|bal|балл|points?)\b|"
    r"\b[0-4][.,]\d{1,2}\b", re.IGNORECASE)


def amounts(text: str) -> list[str]:
    """The production amount finder's spans, so the scorer leans on the finder the reader uses."""
    return [a.text for a in find_amounts(text)]


def evidence(question_id: str, text: str) -> bool:
    if question_id == "application_date":
        return bool(find_dates(text) or find_relative_dates(text))
    if question_id == "level_rule":
        return bool(find_levels(text))
    if question_id == "nationality_rule":
        return bool(_NATIONALITY.search(text))
    if question_id == "requirement_rule":
        return bool(_THRESHOLD.search(text))
    if question_id == "money_to_student":
        return bool(amounts(text))
    return True
```

- [ ] **Step 4: Run the new and the harness tests**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates tests/research/engine_eval -q`
Expected: all pass (`test_evidence.py`, `test_jev_reader.py`, `test_score.py`, `test_key.py`,
`test_questions.py` and `test_items.py` passed against these finders on 2026-10-05). A harness test
that pinned the old regex's exact output is reported in the task report with the line, and the
finder is fixed, not the test, unless the old output was wrong.

- [ ] **Step 5: Commit**

```bash
git add apps/research/candidates apps/research/engine_eval/evidence.py tests/research/candidates/test_find_all.py
git commit -m "feat(research): one candidate assembler keyed by name; the harness uses the production finders"
```

---

### Task 8a: Header rows and the date-header cue table

**Files:**
- Create: `docs/research/date-header-cues.csv`, `apps/research/candidates/headers.py`
- Test: `tests/research/candidates/test_headers.py`

**Why:** dates research 2026-10-03 §1(c): 36 of 55 date candidates in the f7 key were Korean month
cells under 신청시기 ("application period") or 선발시기 ("selection period"); without the column header
a bare month has no role. Task 8's `find_all` already reads a `Line`'s `header` and marks what it
yields `from_header`; this task adds the per-language cue table that names the header's role. The
cue is shown to Jev beside the cell; it never decides the role on its own.

**Interfaces:**
- Produces: `DATE_HEADER_CUES_FILE`, `ROLES` (application_window, deadline, selection,
  funding_period, results), `header_cue(text: str) -> str | None` (the longest matching cue's role).

- [ ] **Step 1: Write the cue table**

```csv
cue,language,role
application,en,application_window
applications open,en,application_window
application period,en,application_window
deadline,en,deadline
application deadline,en,deadline
closing date,en,deadline
due date,en,deadline
last date,en,deadline
selection,en,selection
interview,en,selection
payment,en,funding_period
disbursement,en,funding_period
funding period,en,funding_period
results,en,results
announcement,en,results
müraciət,az,application_window
qəbul,az,application_window
son müraciət,az,deadline
son tarix,az,deadline
seçim,az,selection
müsahibə,az,selection
ödəniş,az,funding_period
təqaüdün ödənilməsi,az,funding_period
nəticə,az,results
başvuru,tr,application_window
son başvuru,tr,deadline
son tarih,tr,deadline
son,tr,deadline
seçim,tr,selection
mülakat,tr,selection
ödeme,tr,funding_period
burs ödemesi,tr,funding_period
sonuç,tr,results
приём заявок,ru,application_window
прием заявок,ru,application_window
подача заявок,ru,application_window
срок подачи,ru,deadline
крайний срок,ru,deadline
до,ru,deadline
отбор,ru,selection
собеседование,ru,selection
выплат,ru,funding_period
результат,ru,results
신청,ko,application_window
접수,ko,application_window
마감,ko,deadline
선발,ko,selection
면접,ko,selection
지급,ko,funding_period
발표,ko,results
başvuru sonuç,tr,results
application results,en,results
müraciətin nəticə,az,results
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/research/candidates/test_headers.py
import csv

import pytest

from apps.research.candidates import Line, find_all
from apps.research.candidates.headers import DATE_HEADER_CUES_FILE, ROLES, header_cue


@pytest.mark.parametrize(("header", "role"), [
    ("신청시기", "application_window"),
    ("선발시기", "selection"),
    ("Son müraciət tarixi", "deadline"),
    ("Müraciətlərin qəbulu", "application_window"),
    ("Son başvuru tarihi", "deadline"),
    ("Выплата стипендии", "funding_period"),
    ("Приём заявок", "application_window"),
    ("Application deadline", "deadline"),
    ("Results announced", "results"),
    ("Başvuru sonuçları", "results"),
])
def test_a_column_header_names_its_dates_role(header, role):
    assert header_cue(header) == role


def test_a_header_with_no_cue_names_nothing():
    assert header_cue("Programme") is None
    assert header_cue("Документы") is None  # "до" is a whole word, not the start of this one


def test_every_cue_row_names_a_known_role():
    with DATE_HEADER_CUES_FILE.open(encoding="utf-8") as handle:
        assert {row["role"] for row in csv.DictReader(handle)} <= set(ROLES)


def test_a_cell_is_read_with_its_column_header():
    c = find_all([Line("3월", header="신청시기 (2026년 3월)"), "Deadline: 15 January 2027"])
    found = [(f.line, f.from_header) for f in c.dates.values()]
    assert found == [(0, False), (0, True), (1, False)]
    assert c.state()["dates"]["d2"]["from_header"] is True
    assert header_cue("신청시기 (2026년 3월)") == "application_window"
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_headers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.candidates.headers'`

- [ ] **Step 4: Implement**

```python
# apps/research/candidates/headers.py
"""What a table's column header says a date in that column is (dates research 2026-10-03 §1(c)).

36 of 55 dates in the f7 key were Korean month cells under 신청시기 ("application period") or
선발시기 ("selection period"); read without the header, a bare month has no role. The cue is
context shown to Jev beside the cell, never the role on its own. Data, not code: the cues are
docs/research/date-header-cues.csv.
"""

from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

from apps.research.locale_names import fold

DATE_HEADER_CUES_FILE = (
    Path(__file__).resolve().parents[3] / "docs" / "research" / "date-header-cues.csv"
)
ROLES = ("application_window", "deadline", "selection", "funding_period", "results")


def _pattern(cue: str) -> re.Pattern[str]:
    """A cue in a script without case (Hangul, Han) is a substring: Korean headers run words
    together ("신청시기"). A cue of three letters or fewer ("son", "до") is a whole word; a longer
    one starts a word and may take an ending ("выплата", "müraciətlər")."""
    if cue.upper() == cue.lower():
        return re.compile(re.escape(cue))
    if len(cue) <= 3:
        return re.compile(rf"(?<!\w){re.escape(cue)}(?!\w)", re.IGNORECASE)
    return re.compile(rf"(?<!\w){re.escape(cue)}", re.IGNORECASE)


@cache
def _cues() -> tuple[tuple[re.Pattern[str], int, str], ...]:
    with DATE_HEADER_CUES_FILE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if unknown := {row["role"] for row in rows} - set(ROLES):
        raise ValueError(f"unknown header roles: {sorted(unknown)}")
    return tuple((_pattern(fold(row["cue"])), len(row["cue"]), row["role"]) for row in rows)


def header_cue(text: str) -> str | None:
    """The role the longest cue in `text` names, or None: "Son müraciət tarixi" is a deadline
    although it also contains "müraciət"."""
    folded = fold(text)
    found = [(length, role) for pattern, length, role in _cues() if pattern.search(folded)]
    return max(found)[1] if found else None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_headers.py -q`
Expected: 13 passed.

- [ ] **Step 6: Commit**

```bash
git add docs/research/date-header-cues.csv apps/research/candidates/headers.py tests/research/candidates/test_headers.py
git commit -m "feat(research): a table cell is read with its column header; header cues per language, as data"
```

---

### Task 9: The finders against the round-1 lines (regression set, $0)

**Files:**
- Create: `tests/research/candidates/test_round1_lines.py`
- Uses: `docs/research/gold/2026-10-04-round-1-owner-gold.csv` (committed 664418bb)

**Why:** the 114 owner-checked lines are the only real lines with a human verdict in the repository.
Every deadline line the owner marked correct must yield a date or relative-date candidate, and every
money line a currency amount or a "covers" phrase; a line that yields nothing is `no_candidate`, the
metric the spec says improves the finders.

- [ ] **Step 1: Write the test**

```python
# tests/research/candidates/test_round1_lines.py
import csv
from pathlib import Path

from apps.research.candidates import find_all

GOLD = (Path(__file__).resolve().parents[3] / "docs" / "research" / "gold"
        / "2026-10-04-round-1-owner-gold.csv")


def _rows(kind):
    with GOLD.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [r for r in rows if r["kind"] == kind and r["verdict"] == "correct"]


def test_every_correct_deadline_line_has_a_date_candidate():
    missing = []
    for row in _rows("deadline"):
        found = find_all([row["line_text"]])
        if not (found.dates or found.relative_dates):
            missing.append(row["line_text"])
    assert missing == []


def test_report_money_lines_without_an_amount():
    missing = [r["line_text"] for r in _rows("money") if not find_all([r["line_text"]]).amounts]
    # money lines that state coverage in words ("all expenses are covered") carry no amount;
    # this number is a ratchet: lower it when a finder improves, never raise it
    assert len(missing) <= 20, missing
```

- [ ] **Step 2: Run it**

Run: `POSTGRES_DB=tehsil_card_reader uv run pytest tests/research/candidates/test_round1_lines.py -q -rA`
Expected: both pass. Measured 2026-10-05: 14 of 14 correct deadline lines have a candidate; 20 of
29 correct money lines carry no amount (they state coverage in words: "all expenses are covered",
"бесплатное обучение"), hence the ratchet at 20. If the run prints fewer, lower the number.
A deadline line with no candidate is a finder bug: fix the finder in Task 4 or 5's module.

- [ ] **Step 3: Full gates and commit**

Run: `uv run ruff check . && uv run mypy apps config && POSTGRES_DB=tehsil_card_reader uv run pytest -q`
Expected: all pass.

```bash
git add tests/research/candidates/test_round1_lines.py apps/research/candidates
git commit -m "test(research): the finders on the owner's round-1 lines -- every deadline line has a candidate"
```

---

## Self-review notes (writer's)

- Spec coverage: §5 step 1 term table (Task 2); step 4 amounts, ranges, approximations, conversions
  (Task 3); dates, month-only, ambiguous order (Task 4); relative dates (Task 5); durations, intakes
  (Task 6); places, regions, unknown groups, who-may-apply incl. postdoc (Task 7); keyed state and
  no_candidate (Task 8); table header rows and their cue table (Task 8a). Out of this slice, by design: the regions rows for DAC, CIS, OTS, OIC and
  Erasmus partner countries (each needs its defining URL; the `unknown_group` count says which to add
  first — a data task with research, not code), D8, Calls 1–3 (slice 2), storage (slice 3).
- Placeholder scan: no TBD/TODO; every code step carries code; dataclass names (`Amount`, `Date`,
  `RelativeDate`, `Duration`, `Intake`, `Place`, `Level`, `Requirement`, `Line`, `Found`,
  `Candidates`) match across tasks.
- Verified 2026-10-05 in a scratch overlay of this branch (repo untouched): every block was run, and
  applying Tasks 3–8's append steps to `candidates/__init__.py` and `dates.py` rebuilds the tested files
  byte for byte. Not run there: Task 2 Step 5's caller tests (they need the database), and each task's
  tests at its own intermediate state (only the final state was run).
