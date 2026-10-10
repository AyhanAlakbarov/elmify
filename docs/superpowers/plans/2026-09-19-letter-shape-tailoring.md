# Letter Shape Tailoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A motivation letter obeys the shape rules its own programme page states — length, form, formalities, naming, artifact format — derived from the same single read of the page the CV rules come from, defaulted from sourced research where the page is silent, and enforced with no human reviewer anywhere in the loop.

**Architecture:** The CV deriver already reads each changed page with three model readings (two OpenAI phrasings, one Claude) and acts only on unanimity. This plan widens that one call rather than adding a second: `Candidate` gains `cv`/`letter` flags, `Derivations` gains a `letters` list, and the same samples answer both documents. A new `decide_letter_shape` turns those verdicts into fifteen typed columns on `ApplicationPrompt`, resolving every disagreement to the safer shape by a per-field rule instead of to a warning nobody would read. Generation, render, a third template and one new gate then consume those columns; a sentence the columns cannot type is injected into the generation prompt as data and judge-checked afterwards, or handed to the student as an Application Kit step.

**Tech Stack:** Python 3.14, Django 5.2, Pydantic 2, OpenAI + Anthropic SDKs, WeasyPrint, pytest. **No new runtime dependency** — see Global Constraints on language detection.

**Spec:** `docs/superpowers/specs/2026-09-19-letter-shape-tailoring-design.md` (read it alongside this plan; every task cites its section)

## Global Constraints

- **No human reviews a finished letter** (owner, 2026-09-18). The CV path's answer to a doubtful page — write an `undecided` rule for a counsellor — has no reader here. Every doubt resolves by the per-field rule in §4 to a shape that cannot break the page's requirement. Never add a "show the counsellor" branch to the letter path.
- **One read, one call, both documents** (§3, §9). The letter questions ride on the CV deriver's existing three readings. Six model calls per changed page stays the ceiling; only the tokens per call grow. Never add a second judge call to the derivation path.
- **Every requirement is applied** (§3b). There is no "shown but not applied" state. A confirmed requirement lands in exactly one of: applied at render, written into the prompt then judge-checked, or an Application Kit step for the student. The word `unapplied` (the CV path's rule key) is never used for letters.
- **A sentence is only ever the page's own words.** `rule_text` and every stored quote are verbatim page text, exactly as `ProgramStatement.text` is. Never store a model's paraphrase.
- **`derive._THIRD_PARTY` applies unchanged.** A sentence about a referee's, supervisor's, host's or employer's document sets nothing on the applicant's letter.
- **Untrusted content is data, never instructions** (CLAUDE.md, LLM/AI security). Every prompt carrying page text or a page sentence labels it DATA and says so; `max_output_tokens` is capped on every call; the post-generation check reuses generation's existing per-student rate limit.
- **Language detection adds no dependency.** No `lingua`/`langdetect`-class library is installed (checked: `pyproject.toml` has none) and the task is choosing one of twelve known term rows, not identifying one of seventy-five languages. Order: the page's own `<html lang>`, then script (Hangul → `ko`, Kana → `ja`, Han alone → `zh`, reusing `letter_gates._HANGUL`/`_KANA`/`_HAN`), then a stopword score over the twelve seeded rows. **Trigger for revisiting:** the §8 eval sheet showing a language whose row was never selected on its own pages.
- **The Application Kit has no model yet.** `apps/portals/models.py` has `PortalForm`, `FieldMap`, `RecoveryEvent`, `Application`, `ApplicationStep` and nothing else; the Kit is designed (`2026-09-15-glass-box-copilot-design.md`) and unbuilt. Path-3 student actions are therefore stored on the prompt and exposed by one named function for the Kit to call. Task 11 states this deviation in code.
- **Migration numbering collides across branches.** `apps/funding/migrations/` ends at `0030_cv_directives_undecided_unreadable` on this branch and master renumbered that same migration to `0031` (CLAUDE.md, "Migrations: squash once"). Number every new migration from `ls` at execution time, never from this document, and run `makemigrations --check` before each commit.
- **Never run `ruff format`** in this repo (it produces invalid Python here). The gates are `uv run ruff check`, `uv run mypy`, `uv run pytest`, `uv run bandit -c pyproject.toml -r apps config`.
- **Line length 100**, ruff `select = ["E", "F", "I", "UP"]`, mypy `strict = true`.
- **Test database per worktree:** run pytest with `POSTGRES_DB=tehsil_letter_shape`.

---

## File Structure

| file | responsibility |
|---|---|
| `docs/research/letter-shape-terms.csv` (new) | one row per language: document, unit, signature, naming, portfolio, thesis, coursework terms + detection stopwords |
| `docs/research/letter-formalities.csv` (new) | one row per language: salutation, closing, place-and-date custom, source `M-` id |
| `apps/documents/letter_terms.py` (new) | load the terms CSV, `detect_language`, `normalise_numerals` |
| `apps/research/reader.py` (modify) | `html_lang()`; `ReadResult.page_language` |
| `apps/documents/derive.py` (modify) | `Candidate.cv`/`.letter`, letter candidates, `LetterVerdict`, `Derivations.letters`, the letter question, `letter_outcomes`, `decide_letter_shape`, shape write in `derive_page_rules` |
| `apps/documents/letter_shape.py` (new) | `LetterShape` dataclass, the §4 safer-direction rules, `apply_derived_shape`, `shape_from_prompt`, `constraints_from_shape` |
| `apps/funding/models.py` + migration (modify) | fifteen `ApplicationPrompt` columns, `Program.portfolio_led` |
| `apps/documents/letter_defaults.py` (new) | `COUNTRY_SYSTEM`, `LETTER_SHAPE_DEFAULTS`, `defaults_for`; replaces `silent_funder.DEFAULT_ARCHETYPES_BY_FUNDER_KIND` |
| `apps/documents/letters.py` (modify) | shape into the generation prompt; `NotGeneratable` on `naming=REQUIRED` with no fit; path-2 sentences as data |
| `apps/documents/letter_render.py` (modify) | shape → `ConstraintRule`s, artifact CSS, `letter_formal.html` selection, font allowlist |
| `apps/documents/templates/documents/letter_formal.html` (new) | place/date, addressee, salutation, sign-off, signature line |
| `apps/documents/letter_gates.py` (modify) | `GateCode.NAMING_FORBIDDEN`, `check_naming_forbidden` |
| `apps/documents/letter_verification.py` (modify) | `check_written_requirements` — the path-2 post-generation judge |
| `apps/funding/requirements.py` (new) | `program_requirements(programme)` → letter / cv / applicant panes |
| `apps/documents/management/commands/letter_requirement_backlog.py` (new) | count path-2 and path-3 sentences across the catalog |
| tests: `tests/documents/test_letter_terms.py`, `test_letter_derive.py`, `test_letter_shape.py`, `test_letter_defaults.py`, `test_letter_formal_render.py`, `test_letter_naming_gate.py`, `test_written_requirements.py`, `tests/funding/test_requirements.py` (new); `tests/documents/test_derive.py`, `tests/research/test_reader.py` (modify) | |

---

# Increment 1 — the page's shape reaches the catalog

### Task 1: The page's language, detected before any term is matched

**Files:**
- Create: `docs/research/letter-shape-terms.csv`, `apps/documents/letter_terms.py`
- Modify: `apps/research/reader.py` (`ReadResult`, `read_program_page`)
- Test: `tests/documents/test_letter_terms.py`, `tests/research/test_reader.py`

**Interfaces:**
- Produces: `TERMS: dict[str, TermRow]`; `TermRow(language, document, unit, signature, naming, portfolio, thesis, coursework, stopwords)` each a `tuple[str, ...]`; `detect_language(page_text: str, *, html_lang: str = "") -> str` returning a lowercase two-letter code or `""`; `normalise_numerals(text: str) -> str`; `reader.html_lang(body: bytes) -> str`; `ReadResult.page_language: str = ""`.

- [ ] **Step 1: Write the terms CSV**

`docs/research/letter-shape-terms.csv`, header then twelve rows. Pipe-separated inside each quoted cell; the file is comma-separated and every cell is quoted.

```csv
"language","document","unit","signature","naming","portfolio","thesis","coursework"
"en","letter of motivation|motivation letter|personal statement|statement of purpose|cover letter|motivation|essay|letter","words|characters|pages|page|word|character","sign|signed|signature|declaration|declare","supervisor|professor|faculty|research group|lab|module|course|department","portfolio","thesis|dissertation|research proposal","coursework|taught"
"de","motivationsschreiben|motivationsbrief|anschreiben|begründung|absichtserklärung|aufsatz","wörter|zeichen|seiten|seite|wort","unterschreiben|unterschrift|unterzeichnet|erklärung","betreuer|professor|lehrstuhl|forschungsgruppe|modul|institut","portfolio|mappe","masterarbeit|dissertation|forschungsvorhaben|exposé","lehrveranstaltung|studiengang"
"fr","lettre de motivation|exposé des motifs|lettre|motivation|essai","mots|caractères|pages|page|signes","signer|signature|signé|déclaration","directeur|encadrant|professeur|laboratoire|équipe|unité","portfolio|dossier","mémoire|thèse|projet de recherche","enseignement|cours"
"nl","motivatiebrief|motivatie|brief|essay","woorden|tekens|pagina's|pagina","ondertekenen|handtekening|verklaring","begeleider|promotor|hoogleraar|onderzoeksgroep|vak","portfolio","scriptie|proefschrift|onderzoeksvoorstel","vakken|onderwijs"
"it","lettera motivazionale|lettera di motivazione|lettera|motivazione|saggio","parole|caratteri|pagine|pagina","firmare|firma|firmato|dichiarazione","relatore|supervisore|professore|gruppo di ricerca|dipartimento","portfolio","tesi|progetto di ricerca","corsi|insegnamenti"
"es","carta de motivación|declaración de intenciones|carta|motivación|ensayo","palabras|caracteres|páginas|página|cuartillas","firmar|firma|firmado|declaración","director|tutor|supervisor|profesor|grupo de investigación|departamento","portafolio|portfolio","tesis|trabajo fin de máster|proyecto de investigación","asignaturas|docencia"
"pt","carta de motivação|declaração de motivação|carta|motivação|ensaio","palavras|caracteres|páginas|página","assinar|assinatura|assinado|declaração","orientador|supervisor|professor|grupo de pesquisa|departamento","portfólio|portfolio","dissertação|tese|projeto de pesquisa","disciplinas|curso"
"ru","мотивационное письмо|письмо|эссе|заявление|мотивация","слов|слова|символов|знаков|страниц|страницы","подпись|подписать|подписано|заявление","научный руководитель|профессор|лаборатория|кафедра","портфолио","диссертация|магистерская|исследовательский проект","курсы|дисциплины"
"tr","niyet mektubu|motivasyon mektubu|mektup|deneme|amaç beyanı","kelime|karakter|sayfa|sözcük","imza|imzalı|imzalamak|beyan","danışman|profesör|araştırma grubu|bölüm","portfolyo","tez|araştırma önerisi","ders|dersler"
"zh","个人陈述|自传|读书计划|讀書計畫|自傳|動機信|动机信|申请书|申請書","字|字数|字數|页|頁|字符","签名|簽名|签字|簽字|亲笔|親筆|声明|聲明","导师|導師|教授|实验室|實驗室|课题组|課題組","作品集","论文|論文|研究计划|研究計畫","课程|課程"
"ja","志望理由書|自己推薦書|研究計画書|志望動機|エッセイ|手紙","字|文字|ページ|枚","署名|自署|宣誓|記名","指導教員|教授|研究室|専攻","ポートフォリオ","修士論文|研究計画","履修|授業"
"ko","학업계획서|자기소개서|수학계획서|지원동기|자기소개","자|글자|바이트|페이지|장","서명|자필|서약|날인","지도교수|교수|연구실|학과","포트폴리오","논문|연구계획","수강|교과"
```

**Eight columns, and no `stopwords` column** (pre-flight ruling 2). Detection words live in `_STOPWORDS` in `letter_terms.py`, which is their single source; zh, ja and ko need none because script decides them.

- [ ] **Step 2: Write the failing tests**

```python
# tests/documents/test_letter_terms.py
import pytest

from apps.documents.letter_terms import TERMS, detect_language, normalise_numerals


def test_every_seeded_language_has_a_document_word_and_a_unit_word() -> None:
    assert set(TERMS) == {"en", "de", "fr", "nl", "it", "es", "pt", "ru", "tr", "zh", "ja", "ko"}
    for code, row in TERMS.items():
        assert row.document, code
        assert row.unit, code


def test_the_pages_own_lang_attribute_wins() -> None:
    """The CMS states it; nothing we infer beats what the publisher declared."""
    assert detect_language("Ceci est une page.", html_lang="de-DE") == "de"
    assert detect_language("", html_lang="PT-br") == "pt"


def test_an_unseeded_lang_attribute_is_not_invented_into_a_neighbour() -> None:
    assert detect_language("valami magyarul", html_lang="hu") == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("학업계획서를 제출하십시오", "ko"),
        ("志望理由書を提出してください", "ja"),
        ("请提交个人陈述和读书计划", "zh"),
    ],
)
def test_script_decides_the_cjk_languages(text, expected) -> None:
    """Kana marks Japanese even among Han; Hangul marks Korean; Han alone is Chinese."""
    assert detect_language(text) == expected


def test_stopwords_decide_a_latin_page_with_no_lang_attribute() -> None:
    french = "Vous devez joindre une lettre de motivation dans le dossier de candidature."
    german = "Sie müssen ein Motivationsschreiben mit der Bewerbung für das Studium einreichen."
    assert detect_language(french) == "fr"
    assert detect_language(german) == "de"


def test_a_page_that_matches_nothing_is_unknown_not_english() -> None:
    """Unknown falls back to labels only and is logged (spec §3); it never guesses en."""
    assert detect_language("1234 5678 9012") == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("٥٠٠ كلمة", "500 كلمة"), ("五百字", "500字"), ("500 words", "500 words"), ("１０００", "1000")],
)
def test_numerals_normalise_across_scripts(raw, expected) -> None:
    assert normalise_numerals(raw) == expected
```

```python
# append to tests/research/test_reader.py
from apps.research.reader import html_lang


def test_the_pages_declared_language_is_read_off_the_html_element() -> None:
    assert html_lang(b"<html lang='de-DE'><body><p>x</p></body></html>") == "de-DE"
    assert html_lang(b"<html><body><p>x</p></body></html>") == ""
    assert html_lang(b"not html at all") == ""
```

- [ ] **Step 3: Run to verify failure**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_terms.py tests/research/test_reader.py -q`
Expected: FAIL, `ModuleNotFoundError: apps.documents.letter_terms` and `ImportError: cannot import name 'html_lang'`

- [ ] **Step 4: Implement `letter_terms.py`**

```python
"""The page's language, and that language's words for a letter.

Spec §3: the language is detected FIRST and only then are candidates found,
so a term row is never matched against a page written in another language.
Two safeguards keep this from becoming an English bias in another alphabet:
the reader's own labels stay candidates whatever the language (derive.py),
and an undetected language degrades to labels only, logged -- never to en.

No language-detection library is installed and none is added: the question
here is which of twelve seeded rows to use, not which of seventy-five
languages a text is. `<html lang>` is the publisher's own answer; script
settles the three CJK languages; a stopword score settles the rest.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .letter_gates import _HAN, _HANGUL, _KANA

logger = logging.getLogger(__name__)

_TERMS_CSV = Path(__file__).resolve().parents[2] / "docs" / "research" / "letter-shape-terms.csv"

#: Detection words per language, for a Latin-script page with no `<html lang>`.
#: Deliberately function words, never the term rows: a term row is what we are
#: trying to SELECT, so scoring on it would make every page look like whichever
#: language happened to share a loanword ("portfolio", "essay").
_STOPWORDS: dict[str, tuple[str, ...]] = {
    "en": ("the", "and", "of", "to", "for", "with", "your", "you", "are", "must"),
    "de": ("der", "die", "das", "und", "für", "mit", "nicht", "sie", "ist", "eine"),
    "fr": ("le", "la", "les", "des", "et", "pour", "vous", "une", "dans", "est"),
    "nl": ("de", "het", "een", "en", "van", "voor", "met", "je", "niet", "zijn"),
    "it": ("il", "la", "e", "di", "per", "con", "non", "una", "che", "sono"),
    "es": ("el", "la", "los", "de", "y", "para", "con", "una", "que", "es"),
    "pt": ("o", "a", "os", "de", "e", "para", "com", "uma", "que", "não"),
    "ru": ("и", "в", "на", "не", "для", "что", "с", "по", "как", "или"),
    "tr": ("ve", "bir", "için", "ile", "bu", "olarak", "da", "veya"),
}
_WORD = re.compile(r"\w+", re.UNICODE)
#: CJK count words are written with the multiplier spelled out (五百字 = 500
#: characters). Only the four that appear in a length rule are mapped; a
#: general Chinese-numeral parser is not needed and would be a silent guess.
_CJK_NUMERALS = {
    "一百": "100", "二百": "200", "三百": "300", "四百": "400", "五百": "500",
    "六百": "600", "七百": "700", "八百": "800", "九百": "900", "一千": "1000",
    "二千": "2000", "三千": "3000", "两千": "2000", "兩千": "2000",
}


@dataclass(frozen=True)
class TermRow:
    language: str
    document: tuple[str, ...]
    unit: tuple[str, ...]
    signature: tuple[str, ...]
    naming: tuple[str, ...]
    portfolio: tuple[str, ...]
    thesis: tuple[str, ...]
    coursework: tuple[str, ...]
    stopwords: tuple[str, ...]


def _split(cell: str) -> tuple[str, ...]:
    return tuple(part.strip().casefold() for part in cell.split("|") if part.strip())


@cache
def _load() -> dict[str, TermRow]:
    with _TERMS_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    loaded: dict[str, TermRow] = {}
    for row in rows:
        code = row["language"].strip().casefold()
        loaded[code] = TermRow(
            language=code,
            document=_split(row["document"]),
            unit=_split(row["unit"]),
            signature=_split(row["signature"]),
            naming=_split(row["naming"]),
            portfolio=_split(row["portfolio"]),
            thesis=_split(row["thesis"]),
            coursework=_split(row["coursework"]),
            stopwords=_STOPWORDS.get(code, ()),
        )
    return loaded


TERMS: dict[str, TermRow] = _load()


def normalise_numerals(text: str) -> str:
    """Western digits for Arabic-Indic, fullwidth and spelled-out CJK counts.

    Used only to check a number the judge returned really is in the sentence
    (derive.py) -- never to rewrite a stored quote, which stays verbatim.
    """
    for cjk, western in _CJK_NUMERALS.items():
        text = text.replace(cjk, western)
    return "".join(
        str(unicodedata.decimal(char)) if unicodedata.category(char) == "Nd" else char
        for char in text
    )


def detect_language(page_text: str, *, html_lang: str = "") -> str:
    """The page's language as a seeded two-letter code, or "" when unknown.

    "" is a real answer and the caller must treat it as one: candidates then
    come from the reader's labels alone (spec §3) and the miss is logged, so a
    language with no row is visible as a language rather than as a page that
    states nothing.
    """
    declared = html_lang.strip().casefold().split("-")[0]
    if declared in TERMS:
        return declared
    if declared:
        logger.warning("page declares language %r, which has no term row", declared)
    if _HANGUL.search(page_text):
        return "ko"
    if _KANA.search(page_text):
        return "ja"
    if _HAN.search(page_text):
        return "zh"
    words = {match.group().casefold() for match in _WORD.finditer(page_text)}
    scores = {
        code: len(words.intersection(row.stopwords))
        for code, row in TERMS.items()
        if row.stopwords
    }
    best = max(scores, key=lambda code: scores[code], default="")
    # Two hits, not one: a single shared function word ("de" is Dutch, Spanish
    # and Portuguese; "a" is English and Portuguese) decides nothing.
    if best and scores[best] >= 2 and list(scores.values()).count(scores[best]) == 1:
        return best
    logger.warning("page language could not be detected; using the reader's labels only")
    return ""
```

- [ ] **Step 5: Implement the reader half**

In `apps/research/reader.py`, beside `readable_text`:

```python
def html_lang(body: bytes) -> str:
    """The `lang` the page declares on <html>, or "" -- the publisher's own answer.

    Read from the same bytes readable_text parses rather than threaded out of
    it: readable_text has one job and several callers, and a page's declared
    language is a fact about the document, not about the text we kept.
    """
    try:
        document = lxml.html.document_fromstring(body)
    except (ParserError, ValueError):
        return ""
    return str(document.get("lang") or "")
```

Add to `ReadResult`, after `page_text`:

```python
    #: The language the page declares, for the term row the derivation uses.
    #: Empty on a cache hit, exactly like page_text.
    page_language: str = ""
```

In `read_program_page`, every `ReadResult(...)` construction that already passes `page_text=page_text` also passes `page_language=html_lang(fetched.body)`. Bind it once above the first use:

```python
    page_text = readable_text(fetched)
    page_language = html_lang(fetched.body)
```

**The reader stores the page's DECLARED language and resolves nothing** (pre-flight ruling 1). `detect_language` is called in `apps/documents` — Task 5 wires it into `derive_page_rules` — because the import direction in this repo is documents → research and never the reverse (`program_rules.py`'s own docstring), so the reader cannot reach `letter_terms`.

- [ ] **Step 6: Run to verify pass**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_terms.py tests/research/test_reader.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add docs/research/letter-shape-terms.csv apps/documents/letter_terms.py apps/research/reader.py tests/documents/test_letter_terms.py tests/research/test_reader.py
git commit -m "documents: the page's language, then that language's words"
```

---

### Task 2: Letter candidates, found in the page's own language

**Files:**
- Modify: `apps/documents/derive.py:90-157` (`Candidate`, `candidates`)
- Test: `tests/documents/test_letter_derive.py` (new), `tests/documents/test_derive.py` (existing must stay green)

**Interfaces:**
- Consumes: `letter_terms.TERMS`, `letter_terms.detect_language` (Task 1).
- Produces: `Candidate(text, heading, europass, third_party=False, cv=True, letter=False)`; `candidates(page_text, statements, *, language="") -> tuple[Candidate, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_letter_derive.py
from apps.documents.derive import candidates


def test_a_german_page_finds_its_letter_lines_by_the_german_row() -> None:
    page = (
        "# Bewerbung\n"
        "Das Motivationsschreiben darf maximal zwei Seiten umfassen.\n"
        "Bitte laden Sie Ihren Lebenslauf hoch.\n"
    )
    found = candidates(page, (), language="de")
    letters = [c.text for c in found if c.letter]
    assert letters == ["Das Motivationsschreiben darf maximal zwei Seiten umfassen."]
    # The CV line is still a CV candidate and is not a letter candidate.
    assert [c.text for c in found if c.cv and not c.letter] == [
        "Bitte laden Sie Ihren Lebenslauf hoch."
    ]


def test_a_reader_label_is_a_letter_candidate_in_any_language() -> None:
    """Spec §3: a language with a thin row loses nothing the reader labelled."""
    statement = "Kérjük, csatoljon egy motivációs levelet."  # Hungarian: no row
    found = candidates("# Felvételi\nsemmi\n", (statement,), language="")
    assert [(c.text, c.letter, c.cv) for c in found] == [(statement, True, True)]


def test_one_sentence_can_be_both_documents() -> None:
    page = "Submit a CV and a letter of motivation of at most 500 words.\n"
    (found,) = candidates(page, (), language="en")
    assert found.cv and found.letter


def test_a_letter_line_about_a_referee_is_marked_third_party() -> None:
    page = "Your referee must upload a letter of recommendation of one page.\n"
    (found,) = candidates(page, (), language="en")
    assert found.letter and found.third_party


def test_an_unknown_language_finds_no_letter_line_by_keyword() -> None:
    page = "Kérjük, csatoljon egy motivációs levelet legfeljebb 500 szóban.\n"
    assert candidates(page, (), language="") == ()
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_derive.py -q`
Expected: FAIL, `candidates() got an unexpected keyword argument 'language'`

- [ ] **Step 3: Implement**

Replace the `Candidate` dataclass and `candidates` in `apps/documents/derive.py`:

```python
@dataclass(frozen=True)
class Candidate:
    """One sentence the model is asked about. `text` is verbatim and becomes
    rule_text; `heading` is context only and never stored. `third_party` marks
    a sentence about somebody else's document -- it is still judged and still
    shown, but nothing it says is applied to the applicant's.

    `cv` and `letter` say WHICH document's questions this line is judged for.
    They are separate because the two decisions must not poison each other:
    decide() abstains a page when a line it judges is unjudged, so a
    letter-only line inside the shared listing would otherwise abstain the CV
    format for a sentence that was never about the CV.
    """

    text: str
    heading: str
    europass: bool
    third_party: bool = False
    cv: bool = True
    letter: bool = False


def _letter_line(line: str, row: object | None) -> bool:
    """True when this line names the applicant's letter in the page's language."""
    if row is None:
        return False
    folded = line.casefold()
    return any(word in folded for word in row.document)  # type: ignore[attr-defined]


def candidates(
    page_text: str, statements: Iterable[str], *, language: str = ""
) -> tuple[Candidate, ...]:
    """The sentences put to the judge, found by code over the WHOLE page.

    Three recall paths, none of which is the model's choice of what to quote.
    Every line containing `europass` is a format candidate whether or not it
    names the CV ("Please use the Europass model." -- i-MESC, real). Every line
    matching _CV_TERMS is a constraints candidate. Every line naming the letter
    IN THE PAGE'S OWN LANGUAGE (letter_terms.TERMS[language].document) is a
    letter candidate -- `language` empty means no row matched the page, and
    then only the labels below carry it, which is the spec's stated degraded
    mode rather than an English fallback.

    All three are unioned with the sentences the statement read quoted, so a
    word the vocabulary does not know (özgeçmiş, motivációs levél, 履歴書) still
    reaches the judge when the model's own read found it -- and a statement is
    a candidate for BOTH documents, because the reader labelled it DOCUMENT or
    FORMAT without knowing which document it meant.
    """
    row = TERMS.get(language)
    found: list[Candidate] = []
    seen: set[str] = set()
    heading = ""
    for raw in page_text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        is_heading = bool(_HEADING_LINE.match(line))
        if is_heading:
            line = line.lstrip("#").strip()
        elif line.startswith("- "):
            line = line[2:].strip()
        key = normalize(line)
        europass = "europass" in key
        cv = bool(europass or _CV_TERMS.search(line))
        letter = _letter_line(line, row)
        if (cv or letter) and key not in seen:
            seen.add(key)
            found.append(Candidate(
                text=line, heading=heading, europass=europass,
                third_party=bool(_THIRD_PARTY.search(line)), cv=cv, letter=letter,
            ))
        if is_heading:
            heading = line
    for text in sorted(statements):
        key = normalize(text)
        if key not in seen:
            seen.add(key)
            found.append(Candidate(
                text=text.strip(), heading="", europass="europass" in key,
                third_party=bool(_THIRD_PARTY.search(text)), cv=True, letter=True,
            ))
    return tuple(found)
```

Add the import at the top of `derive.py` — only `TERMS` here, because ruff `F401` fails an unused import and `normalise_numerals` is not needed until Task 4:

```python
from .letter_terms import TERMS
```

**Then scope the CV decision to CV candidates, in the same edit.** `outcomes` and `decide` iterate every candidate today, and `decide` abstains the whole page when one line it judged is `unjudged`. A letter-only line in the shared listing would therefore abstain the CV format for a sentence that was never about the CV. In `outcomes`, skip non-CV lines:

```python
    for i, candidate in enumerate(candidates):
        if not candidate.cv:
            continue
```

`decide`'s `abstain` and its two `for i, o in per.items()` loops then see only CV lines, because `per` no longer carries the others. Pin it:

```python
# append to tests/documents/test_letter_derive.py
from apps.documents.derive import Derivations, decide


def test_a_letter_only_line_cannot_abstain_the_cv_decision() -> None:
    """The shared listing must not let one document's silence blank the other."""
    found = candidates(
        "Submit a Europass CV.\nThe letter must be one page.\n", (), language="en"
    )
    # One sample judges only the CV line; the letter line is unjudged for the CV.
    sample = Derivations(
        formats=({"statement_index": 0, "value": "required"},),  # type: ignore[arg-type]
    )
    decision = decide(found, [sample, sample, sample], source_url="u")

    assert decision.abstained is False
```

- [ ] **Step 4: Run both suites**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_derive.py tests/documents/test_derive.py -q`
Expected: PASS — the existing CV tests are unchanged because every candidate they build is `cv=True, letter=False`.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/derive.py tests/documents/test_letter_derive.py
git commit -m "documents: letter candidates, found in the page's own language"
```

---

### Task 3: One judge call answers both documents

**Files:**
- Modify: `apps/documents/derive.py` (`LetterVerdict`, `Derivations`, `_QUESTION`, `_PHRASINGS`, `_touches`)
- Test: `tests/documents/test_letter_derive.py`

**Interfaces:**
- Produces: `LetterVerdict` (Pydantic, `extra="forbid"`, frozen) with `statement_index`, `subject`, `length_measure`, `length_bound`, `length_number`, `form`, `signed_declaration`, `naming`, `document_required`, `track`, `portfolio_required`, `font_family`, `font_min_pt`, `line_spacing`, `margins_cm`, `file_bundle`, `handwritten`, `requirement_path`; `Derivations.letters: tuple[LetterVerdict, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/documents/test_letter_derive.py
import pytest
from pydantic import ValidationError

from apps.documents.derive import Derivations, LetterVerdict, _PHRASINGS, _touches


def test_a_letter_verdict_is_closed_and_typed() -> None:
    verdict = LetterVerdict(
        statement_index=0, subject="applicant_letter", length_measure="words",
        length_bound="maximum", length_number=500, form="formal_letter", naming="forbidden",
    )
    assert verdict.length_number == 500 and verdict.form == "formal_letter"
    with pytest.raises(ValidationError):
        LetterVerdict(statement_index=0, subject="applicant_letter", form="haiku")
    with pytest.raises(ValidationError):
        LetterVerdict(statement_index=0, subject="applicant_letter", unknown_field=1)


def test_a_letter_verdict_alone_counts_as_having_judged_the_line() -> None:
    """_touches decides thin readings and page abstention; letters count."""
    sample = Derivations(
        letters=(LetterVerdict(statement_index=3, subject="applicant_letter"),)
    )
    assert _touches(sample, 3) and not _touches(sample, 4)


def test_every_phrasing_states_the_letter_question_and_the_data_framing() -> None:
    for phrasing in _PHRASINGS:
        assert "DATA" in phrasing
        assert "letter" in phrasing.lower()
        assert "length" in phrasing.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_derive.py -q`
Expected: FAIL, `cannot import name 'LetterVerdict'`

- [ ] **Step 3: Implement the schema**

In `apps/documents/derive.py`, after `Directive`:

```python
_SUBJECT = Literal["applicant_letter", "other"]
_MEASURE = Literal["words", "characters", "pages", "none"]
_BOUND = Literal["maximum", "minimum", "approximate", "none"]
_FORM = Literal["essay", "formal_letter", "portal_form", "none"]
_NAMING = Literal["required", "invited", "forbidden", "none"]
_REQUIRED = Literal["required", "not_required", "none"]
_TRACK = Literal["research", "taught", "none"]
_BUNDLE = Literal["separate", "with_cv", "single_pdf_all", "none"]
_SPACING = Literal["1.0", "1.5", "2.0", "none"]
#: Which of the three application paths a requirement takes (spec §3b). `none`
#: means the sentence states no requirement on the applicant's letter at all --
#: distinct from a requirement whose path is unknown, which cannot occur
#: because the three are exhaustive by construction.
_PATH = Literal["render", "writer", "student", "none"]


class LetterVerdict(BaseModel):
    """What one sentence says about the applicant's OWN letter.

    One verdict per line per reading. Every field defaults to its "says
    nothing" value so that a reading which answers only the length question
    is still a complete, comparable verdict -- agreement is computed per
    field, and a field nobody answered agrees on "none" harmlessly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_index: int = Field(ge=0)
    subject: _SUBJECT = "other"
    length_measure: _MEASURE = "none"
    length_bound: _BOUND = "none"
    length_number: int | None = Field(default=None, ge=1, le=1_000_000)
    form: _FORM = "none"
    signed_declaration: bool = False
    naming: _NAMING = "none"
    document_required: _REQUIRED = "none"
    track: _TRACK = "none"
    portfolio_required: bool = False
    font_family: str | None = Field(default=None, max_length=60)
    font_min_pt: int | None = Field(default=None, ge=4, le=40)
    line_spacing: _SPACING = "none"
    margins_cm: float | None = Field(default=None, ge=0.1, le=10)
    file_bundle: _BUNDLE = "none"
    handwritten: bool = False
    requirement_path: _PATH = "none"
```

Extend `Derivations`:

```python
class Derivations(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rules: tuple[Derived, ...] = Field(default=(), max_length=100)
    formats: tuple[FormatVerdict, ...] = Field(default=(), max_length=100)
    directives: tuple[Directive, ...] = Field(default=(), max_length=100)
    letters: tuple[LetterVerdict, ...] = Field(default=(), max_length=100)
```

Extend `_touches` (its docstring already promises "in any of the typed outputs"):

```python
def _touches(s: Derivations, i: int) -> bool:
    """Whether sample `s` judged statement `i` at all -- in any of the four
    typed outputs -- so "not judged" and "judged as none/nothing" stay distinct."""
    return (
        any(r.statement_index == i for r in s.rules)
        or any(f.statement_index == i for f in s.formats)
        or any(d.statement_index == i for d in s.directives)
        or any(letter.statement_index == i for letter in s.letters)
    )
```

- [ ] **Step 4: Implement the question**

Add `_LETTER_QUESTION` after `_QUESTION` and append it in each phrasing:

```python
_LETTER_QUESTION = (
    " Also judge each line for the applicant's OWN motivation letter, personal "
    "statement or essay, and return exactly one letter verdict per line. "
    "subject: applicant_letter when the sentence is about the document the "
    "APPLICANT writes, otherwise other -- a letter a referee, supervisor, host or "
    "employer writes is other, and an other verdict sets nothing else. "
    "length_measure/length_bound/length_number: the measure (words, characters, "
    "pages), the bound (maximum, minimum, approximate) and the number the sentence "
    "gives. Wording such as 'about', 'approximately', 'roughly' or 'around' is "
    "approximate, never minimum. Never infer a number the sentence does not print. "
    "form: formal_letter when the document is described with a date, addressee, "
    "salutation or signature; portal_form when it is typed into fields in an online "
    "form; essay when it is continuous prose with none of those; none otherwise. "
    "signed_declaration: true when the applicant must sign a declaration about the "
    "document. naming: required, invited or forbidden when the sentence tells the "
    "applicant to name (or not to name) a specific professor, research group, "
    "laboratory or module; none otherwise. document_required: required when a "
    "letter, statement or essay is required, not_required when the page says none "
    "is needed. track: research when the programme requires a thesis, research "
    "proposal or a prospective supervisor; taught when it states coursework only. "
    "portfolio_required: true when a portfolio is required. "
    "font_family, font_min_pt, line_spacing, margins_cm, file_bundle "
    "(separate, with_cv, single_pdf_all) and handwritten: only when the sentence "
    "states them for this document. "
    "requirement_path: render when the requirement is about the file's appearance "
    "or packaging; writer when it constrains what the text says or how it is "
    "written; student when only the applicant can perform it (hand-write, "
    "hand-sign, print and scan, obtain a stamp, attach a paper form); none when "
    "the sentence states no requirement on the applicant's letter."
)
```

Then in each of the three `_PHRASINGS` entries, replace the trailing `+ _QUESTION` with `+ _QUESTION + _LETTER_QUESTION`.

- [ ] **Step 5: Run to verify pass**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_derive.py tests/documents/test_derive.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/documents/derive.py tests/documents/test_letter_derive.py
git commit -m "documents: the same three readings answer the letter's questions too"
```

---

### Task 4: Ambiguity resolves to the safer shape, never to a warning

**Files:**
- Create: `apps/documents/letter_shape.py`
- Modify: `apps/documents/derive.py` (import `normalise_numerals`, add `decide_letter_shape`)
- Test: `tests/documents/test_letter_shape.py`

**Interfaces:**
- Consumes: `Candidate`, `Derivations`, `LetterVerdict` (Tasks 2-3).
- Produces: `LetterShape` frozen dataclass with fields `document_required: str`, `min_words/max_words/max_chars/max_pages: int | None` (`max_pages` a `float`), `form: str`, `signed_declaration: bool`, `naming: str`, `font_family: str | None`, `font_min_pt: int | None`, `line_spacing: float | None`, `margins_cm: float | None`, `file_bundle: str`, `handwritten: bool`, `sources: dict[str, dict[str, str]]`, `written_requirements: tuple[dict[str, str], ...]`, `student_actions: tuple[dict[str, str], ...]`, `track: str`, `portfolio_led: bool`; `decide_letter_shape(candidates, samples, *, source_url) -> LetterShape`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_letter_shape.py
from apps.documents.derive import Candidate, Derivations, LetterVerdict, decide_letter_shape


def _line(text: str = "The letter must be short.", **kwargs) -> Candidate:
    return Candidate(text=text, heading="", europass=False, cv=False, letter=True, **kwargs)


def _sample(**kwargs) -> Derivations:
    return Derivations(
        letters=(LetterVerdict(statement_index=0, subject="applicant_letter", **kwargs),)
    )


def _decide(candidate, *samples):
    return decide_letter_shape((candidate,), list(samples), source_url="https://x.example/p")


def test_two_readings_disagreeing_on_a_cap_take_the_smaller() -> None:
    shape = _decide(
        _line("The letter must not exceed 800 words."),
        _sample(length_measure="words", length_bound="maximum", length_number=800),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=800),
    )
    assert shape.max_words == 500


def test_one_reading_finding_a_floor_keeps_it() -> None:
    shape = _decide(
        _line("Letters below 500 words will not be accepted."),
        _sample(length_measure="words", length_bound="minimum", length_number=500),
        _sample(),
        _sample(),
    )
    assert shape.min_words == 500


def test_approximate_wording_is_a_cap_and_never_a_floor() -> None:
    shape = _decide(
        _line("The letter should be about one page."),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
    )
    assert shape.max_pages == 1 and shape.min_words is None


def test_caps_in_two_units_are_both_kept() -> None:
    shape = _decide(
        _line("Maximum 500 words and 3500 characters."),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="characters", length_bound="maximum", length_number=3500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
    )
    assert shape.max_words == 500 and shape.max_chars == 3500


def test_a_number_not_on_the_page_is_dropped() -> None:
    """Verification removes fabrication here exactly as it does for a quote."""
    shape = _decide(
        _line("The letter must be short."),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
    )
    assert shape.max_words is None


def test_a_number_written_in_another_script_counts_as_on_the_page() -> None:
    shape = _decide(
        _line("志望理由書は五百字以内とします。"),
        _sample(length_measure="characters", length_bound="maximum", length_number=500),
        _sample(length_measure="characters", length_bound="maximum", length_number=500),
        _sample(length_measure="characters", length_bound="maximum", length_number=500),
    )
    assert shape.max_chars == 500


def test_one_reading_saying_letter_makes_it_a_formal_letter() -> None:
    shape = _decide(
        _line("Address the letter to the admissions committee and sign it."),
        _sample(form="formal_letter"), _sample(form="essay"), _sample(form="essay"),
    )
    assert shape.form == "FORMAL_LETTER"


def test_portal_form_needs_every_reading() -> None:
    """A wrongly assumed form drops the letter's prose, so it is the one
    direction that needs unanimity."""
    mixed = _decide(
        _line("Complete the motivation fields in the online form."),
        _sample(form="portal_form"), _sample(form="portal_form"), _sample(form="essay"),
    )
    assert mixed.form == "FORMAL_LETTER"
    unanimous = _decide(
        _line("Complete the motivation fields in the online form."),
        _sample(form="portal_form"), _sample(form="portal_form"), _sample(form="portal_form"),
    )
    assert unanimous.form == "PORTAL_FORM"


def test_one_forbidden_forbids_and_required_needs_all_three() -> None:
    forbidden = _decide(
        _line("References to faculty should not be made in the letter."),
        _sample(naming="forbidden"), _sample(naming="required"), _sample(naming="invited"),
    )
    assert forbidden.naming == "FORBIDDEN"
    invited = _decide(
        _line("You may name a prospective supervisor in the letter."),
        _sample(naming="required"), _sample(naming="invited"), _sample(naming="none"),
    )
    assert invited.naming == "INVITED"
    required = _decide(
        _line("Name the supervisor you wish to work with in the letter."),
        _sample(naming="required"), _sample(naming="required"), _sample(naming="required"),
    )
    assert required.naming == "REQUIRED"


def test_one_reading_is_enough_for_a_signature_and_for_required() -> None:
    shape = _decide(
        _line("The signed letter must be uploaded."),
        _sample(signed_declaration=True, document_required="required"), _sample(), _sample(),
    )
    assert shape.signed_declaration is True
    assert shape.document_required == "REQUIRED"


def test_a_referees_letter_sets_nothing() -> None:
    shape = _decide(
        _line("Your referee uploads a letter of at most one page.", third_party=True),
        _sample(subject="other", length_measure="pages", length_bound="maximum", length_number=1),
        _sample(length_measure="pages", length_bound="maximum", length_number=1),
        _sample(length_measure="pages", length_bound="maximum", length_number=1),
    )
    assert shape.max_pages is None and shape.document_required == "UNSTATED"


def test_every_applied_field_carries_the_sentence_that_set_it() -> None:
    shape = _decide(
        _line("The letter must not exceed 500 words."),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
    )
    assert shape.sources["max_words"]["text"] == "The letter must not exceed 500 words."
    assert shape.sources["max_words"]["source_url"] == "https://x.example/p"


def test_a_writer_path_sentence_is_kept_for_the_prompt_and_the_check() -> None:
    shape = _decide(
        _line("Write the letter in the third person."),
        _sample(requirement_path="writer"),
        _sample(requirement_path="writer"),
        _sample(requirement_path="writer"),
    )
    assert shape.written_requirements[0]["text"] == "Write the letter in the third person."
    assert shape.student_actions == ()


def test_a_student_path_sentence_becomes_an_action_not_a_prompt_line() -> None:
    shape = _decide(
        _line("The letter must be hand-written and signed in ink."),
        _sample(requirement_path="student", handwritten=True),
        _sample(requirement_path="student", handwritten=True),
        _sample(requirement_path="student", handwritten=True),
    )
    assert shape.handwritten is True
    assert shape.student_actions[0]["text"].startswith("The letter must be hand-written")
    assert shape.written_requirements == ()


def test_artifact_fields_take_the_stated_value_and_the_safer_side_of_two() -> None:
    shape = _decide(
        _line("Use Times New Roman 12 pt, 1.5 line spacing and 2 cm margins."),
        _sample(font_family="Times New Roman", font_min_pt=12, line_spacing="1.5", margins_cm=2.0),
        _sample(font_family="Times New Roman", font_min_pt=11, line_spacing="2.0", margins_cm=2.5),
        _sample(font_family="Times New Roman", font_min_pt=12, line_spacing="1.5", margins_cm=2.0),
    )
    assert shape.font_family == "Times New Roman"
    assert shape.font_min_pt == 12  # the larger minimum
    assert shape.line_spacing == 2.0  # of two spacings, the larger
    assert shape.margins_cm == 2.5  # the larger margin
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_shape.py -q`
Expected: FAIL, `cannot import name 'decide_letter_shape'`

- [ ] **Step 3: Implement `letter_shape.py`**

```python
"""The shape a programme's page states for the applicant's letter.

Spec §1 and §4. Nobody reviews a finished letter (owner, 2026-09-18), so the
CV path's answer to a doubtful page -- an `undecided` rule a counsellor reads
-- has no reader here. Every disagreement resolves, per field, to the shape
that cannot break what the page requires: the smaller cap, the floor kept,
FORMAL_LETTER over ESSAY, FORBIDDEN over INVITED, the larger minimum font.
The disagreement is logged for the eval gate, never surfaced at run time,
because at run time there is nobody there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DOCUMENT_REQUIRED = ("REQUIRED", "NOT_REQUIRED", "UNSTATED")
FORMS = ("ESSAY", "FORMAL_LETTER", "PORTAL_FORM")
NAMING = ("REQUIRED", "INVITED", "FORBIDDEN", "UNSTATED")
FILE_BUNDLES = ("SEPARATE", "WITH_CV", "SINGLE_PDF_ALL")


@dataclass(frozen=True)
class LetterShape:
    """Fifteen typed answers and the sentence behind each one.

    A field with no entry in `sources` was not set by the page: it is a
    default, and the requirements pane says so (spec §1, last paragraph).
    """

    document_required: str = "UNSTATED"
    min_words: int | None = None
    max_words: int | None = None
    max_chars: int | None = None
    max_pages: float | None = None
    form: str = "ESSAY"
    signed_declaration: bool = False
    naming: str = "UNSTATED"
    font_family: str | None = None
    font_min_pt: int | None = None
    line_spacing: float | None = None
    margins_cm: float | None = None
    file_bundle: str = "SEPARATE"
    handwritten: bool = False
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    #: §3b path 2 -- into the generation prompt as data, judge-checked after.
    written_requirements: tuple[dict[str, str], ...] = ()
    #: §3b path 3 -- only the applicant can do these.
    student_actions: tuple[dict[str, str], ...] = ()
    #: §2, set by the same read: the programme's mode.
    track: str = ""
    portfolio_led: bool = False

    def is_stated(self, name: str) -> bool:
        return name in self.sources
```

- [ ] **Step 4: Implement `decide_letter_shape` in `derive.py`**

Add `normalise_numerals` to the `letter_terms` import, then after `decide`:

```python
def _number_is_on_the_page(number: int | None, text: str) -> bool:
    """A length the sentence does not print is a fabrication, and is dropped.

    The same principle as reader.verified_statements: the readings may agree
    perfectly on a number nobody wrote. Compared after numeral normalisation
    so an Arabic-Indic, fullwidth or spelled-out CJK count still matches.
    """
    return number is not None and str(number) in normalise_numerals(text)


def _verdicts_for(samples: list[Derivations], index: int) -> list[LetterVerdict]:
    """One verdict per sample for this line; a sample that gave several gives none.

    Same rule as the CV directives: two verdicts from ONE reading is that
    reading failing to settle, never extra corroboration.
    """
    per_sample: list[LetterVerdict] = []
    for sample in samples:
        mine = [v for v in sample.letters if v.statement_index == index]
        if len(mine) == 1 and mine[0].subject == "applicant_letter":
            per_sample.append(mine[0])
    return per_sample


def decide_letter_shape(
    candidates: tuple[Candidate, ...], samples: list[Derivations], *, source_url: str
) -> LetterShape:
    """The page's letter shape, every disagreement resolved to the safer side.

    Spec §4. Unlike `decide`, this never abstains and never emits a rule for a
    human: there is no human. A field no reading set stays unset and the
    defaults table (letter_defaults.py) answers for it.
    """
    stated: dict[str, dict[str, str]] = {}
    caps: dict[str, int] = {}
    floors: dict[str, int] = {}
    forms: set[str] = set()
    naming_votes: list[str] = []
    required_votes: list[str] = []
    track_votes: list[str] = []
    fonts: dict[str, object] = {}
    written: list[dict[str, str]] = []
    actions: list[dict[str, str]] = []
    signed = handwritten = portfolio = portal_unanimous = False
    bundle = "SEPARATE"
    n = len(samples)

    def record(field_name: str, candidate: Candidate) -> None:
        stated.setdefault(
            field_name, {"text": candidate.text, "source_url": source_url}
        )

    for index, candidate in enumerate(candidates):
        if not candidate.letter:
            continue
        verdicts = _verdicts_for(samples, index)
        if not verdicts or candidate.third_party:
            # A sentence about somebody else's letter sets nothing, exactly as
            # derive._THIRD_PARTY does for the CV -- agreement about the wrong
            # person's document is still the wrong document.
            continue
        measure_key = {"words": "words", "characters": "chars", "pages": "pages"}
        for verdict in verdicts:
            key = measure_key.get(verdict.length_measure)
            if key and _number_is_on_the_page(verdict.length_number, candidate.text):
                number = int(verdict.length_number or 0)
                if verdict.length_bound == "minimum":
                    # The floor is kept if ANY reading found one: shipping
                    # under a stated minimum is a rejection (HBKU, M-091).
                    floors[key] = max(floors.get(key, 0), number)
                    record(f"min_{key}", candidate)
                elif verdict.length_bound in ("maximum", "approximate"):
                    # Approximate never creates a floor; it is read as a cap.
                    caps[key] = min(caps.get(key, number), number)
                    record(f"max_{key}", candidate)
            if verdict.signed_declaration:
                signed = True
                record("signed_declaration", candidate)
            if verdict.handwritten:
                handwritten = True
                record("handwritten", candidate)
            if verdict.portfolio_required:
                portfolio = True
            if verdict.naming != "none":
                naming_votes.append(verdict.naming)
                record("naming", candidate)
            if verdict.document_required != "none":
                required_votes.append(verdict.document_required)
                record("document_required", candidate)
            if verdict.track != "none":
                track_votes.append(verdict.track)
            if verdict.file_bundle != "none":
                bundle = verdict.file_bundle.upper()
                record("file_bundle", candidate)
            for name, value in (
                ("font_family", verdict.font_family),
                ("font_min_pt", verdict.font_min_pt),
                ("margins_cm", verdict.margins_cm),
            ):
                if value is None:
                    continue
                # The larger minimum and the larger margin are the safer side;
                # a family is the one the page names.
                current = fonts.get(name)
                if name == "font_family":
                    fonts[name] = value
                else:
                    fonts[name] = value if current is None else max(float(current), float(value))  # type: ignore[arg-type]
                record(name, candidate)
            if verdict.line_spacing != "none":
                spacing = float(verdict.line_spacing)
                current_spacing = fonts.get("line_spacing")
                fonts["line_spacing"] = (
                    spacing if current_spacing is None else max(float(current_spacing), spacing)
                )
                record("line_spacing", candidate)
            path = verdict.requirement_path
            entry = {"text": candidate.text, "source_url": source_url}
            if path == "writer" and entry not in written:
                written.append(entry)
            elif path == "student" and entry not in actions:
                actions.append(entry)
        # Form is decided per LINE, not per verdict: "every reading says form"
        # is a statement about one sentence, and folding the votes into the
        # page-wide set first would lose which line they agreed on.
        line_forms = [v.form for v in verdicts if v.form != "none"]
        if line_forms:
            forms.update(line_forms)
            record("form", candidate)
            if len(line_forms) == n and set(line_forms) == {"portal_form"}:
                portal_unanimous = True

    # FORMAL_LETTER if any reading anywhere says letter -- it keeps the prose,
    # which is the safer side. PORTAL_FORM only where every reading on one line
    # said so, because a wrongly assumed form drops the letter's prose entirely.
    if "formal_letter" in forms:
        form = "FORMAL_LETTER"
    elif portal_unanimous:
        form = "PORTAL_FORM"
    elif "portal_form" in forms:
        form = "FORMAL_LETTER"
    else:
        form = "ESSAY"
    if "forbidden" in naming_votes:
        naming = "FORBIDDEN"
    elif naming_votes and all(v == "required" for v in naming_votes) and len(naming_votes) >= n:
        naming = "REQUIRED"
    elif "invited" in naming_votes or "required" in naming_votes:
        naming = "INVITED"
    else:
        naming = "UNSTATED"
    document_required = (
        "REQUIRED" if "required" in required_votes
        else "NOT_REQUIRED" if required_votes and all(v == "not_required" for v in required_votes)
        else "UNSTATED"
    )
    track = (
        "research" if "research" in track_votes
        else "taught" if track_votes else ""
    )
    return LetterShape(
        document_required=document_required,
        min_words=floors.get("words"),
        max_words=caps.get("words"),
        max_chars=caps.get("chars"),
        max_pages=float(caps["pages"]) if "pages" in caps else None,
        form=form,
        signed_declaration=signed,
        naming=naming,
        font_family=cast(str | None, fonts.get("font_family")),
        font_min_pt=int(cast(float, fonts["font_min_pt"])) if "font_min_pt" in fonts else None,
        line_spacing=cast(float | None, fonts.get("line_spacing")),
        margins_cm=cast(float | None, fonts.get("margins_cm")),
        file_bundle=bundle,
        handwritten=handwritten,
        sources=stated,
        written_requirements=tuple(written),
        student_actions=tuple(actions),
        track=track,
        portfolio_led=portfolio,
    )
```

Add `from typing import Literal, cast` to derive.py's imports, and
`from .letter_shape import LetterShape`.

- [ ] **Step 5: Run to verify pass**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_shape.py -q`
Expected: PASS (14 tests)

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check apps/documents && uv run mypy apps/documents/derive.py apps/documents/letter_shape.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add apps/documents/letter_shape.py apps/documents/derive.py tests/documents/test_letter_shape.py
git commit -m "documents: the safer shape by rule, per field, with no reviewer"
```

---

### Task 5: The shape columns, and the mode the same read sets

**Files:**
- Modify: `apps/funding/models.py` (`ApplicationPrompt`, `Program`)
- Create: `apps/funding/migrations/00NN_letter_shape.py` (number from `ls`)
- Modify: `apps/documents/derive.py` (`derive_page_rules` writes the shape)
- Modify: `apps/documents/program_rules.py` (pass `admissions_cycle` and `page_language`)
- Test: `tests/documents/test_letter_shape.py`, `tests/documents/test_program_rules.py`

**Interfaces:**
- Produces: `ApplicationPrompt.letter_document_required/letter_min_words/letter_max_words/letter_max_chars/letter_max_pages/letter_form/letter_signed_declaration/letter_naming/letter_font_family/letter_font_min_pt/letter_line_spacing/letter_margins_cm/letter_file_bundle/letter_handwritten/letter_shape_sources/letter_written_requirements/letter_student_actions`; `Program.portfolio_led: bool`; `letter_shape.apply_derived_shape(program, cycle, shape, *, source_url) -> ApplicationPrompt`; `letter_shape.shape_from_prompt(prompt) -> LetterShape`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/documents/test_letter_shape.py
import pytest

from apps.documents.letter_shape import LetterShape, apply_derived_shape, shape_from_prompt
from apps.funding.models import ApplicationPrompt


@pytest.mark.django_db
def test_a_derived_shape_lands_on_the_prompt_and_round_trips(program) -> None:
    shape = LetterShape(
        document_required="REQUIRED", max_words=500, min_words=300, form="FORMAL_LETTER",
        naming="FORBIDDEN", font_family="Times New Roman", font_min_pt=12, line_spacing=1.5,
        margins_cm=2.0, file_bundle="SINGLE_PDF_ALL", handwritten=True, signed_declaration=True,
        sources={"max_words": {"text": "at most 500 words", "source_url": "https://x.example/p"}},
        written_requirements=({"text": "Write in the third person.", "source_url": "u"},),
        student_actions=({"text": "Sign it in ink.", "source_url": "u"},),
        track="research", portfolio_led=True,
    )

    prompt = apply_derived_shape(program, "2027", shape, source_url="https://x.example/p")

    assert prompt.letter_max_words == 500 and prompt.letter_naming == "FORBIDDEN"
    assert prompt.letter_shape_sources["max_words"]["text"] == "at most 500 words"
    program.refresh_from_db()
    assert program.academic_track == "research" and program.portfolio_led is True
    assert shape_from_prompt(prompt) == shape


@pytest.mark.django_db
def test_a_verified_prompt_is_never_overwritten_by_a_page_read(program) -> None:
    """The ladder's precedence: a hand-verified row beats everything (spec §4)."""
    ApplicationPrompt.objects.create(
        programme=program, cycle="2027", confidence=1.0,
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        document_language="en", letter_max_words=900,
    )

    prompt = apply_derived_shape(
        program, "2027", LetterShape(max_words=500), source_url="https://x.example/p"
    )

    assert prompt.letter_max_words == 900


@pytest.mark.django_db
def test_silence_leaves_the_track_blank_and_blank_resolves_as_taught(program) -> None:
    apply_derived_shape(program, "2027", LetterShape(), source_url="https://x.example/p")
    program.refresh_from_db()
    assert program.academic_track == ""
```

Add a `program` fixture to the module if `tests/documents/conftest.py` has none — check first with `grep -rn "def program" tests/documents/conftest.py`; reuse the existing one when it exists.

- [ ] **Step 2: Run to verify failure**

Expected: FAIL, `cannot import name 'apply_derived_shape'`

- [ ] **Step 3: Add the columns**

In `apps/funding/models.py`, inside `ApplicationPrompt` after `header_block_required`:

```python
    # The shape the programme's own page states for the applicant's letter
    # (spec 2026-09-19, §1). Every column is nullable or has an "unstated"
    # default: a value here is a page rule, and its sentence is in
    # letter_shape_sources; a field absent from that dict is a default the
    # engine chose, never something the page said.
    letter_document_required = models.CharField(max_length=12, default="UNSTATED")
    letter_min_words = models.PositiveIntegerField(null=True, blank=True)
    letter_max_words = models.PositiveIntegerField(null=True, blank=True)
    letter_max_chars = models.PositiveIntegerField(null=True, blank=True)
    letter_max_pages = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    letter_form = models.CharField(max_length=13, default="ESSAY")
    letter_signed_declaration = models.BooleanField(default=False)
    letter_naming = models.CharField(max_length=9, default="UNSTATED")
    letter_font_family = models.CharField(max_length=60, blank=True, default="")
    letter_font_min_pt = models.PositiveSmallIntegerField(null=True, blank=True)
    letter_line_spacing = models.DecimalField(
        max_digits=2, decimal_places=1, null=True, blank=True
    )
    letter_margins_cm = models.DecimalField(
        max_digits=3, decimal_places=1, null=True, blank=True
    )
    letter_file_bundle = models.CharField(max_length=14, default="SEPARATE")
    letter_handwritten = models.BooleanField(default=False)
    letter_shape_sources = models.JSONField(default=dict, blank=True)
    #: §3b path 2 and path 3: requirements no column can type. Kept as the
    #: page's own sentences with their URL, never a paraphrase.
    letter_written_requirements = models.JSONField(default=list, blank=True)
    letter_student_actions = models.JSONField(default=list, blank=True)
```

In `Program`, beside `academic_track`:

```python
    #: Set by the same page read that sets academic_track (spec §2): a page
    #: requiring a portfolio keys a different defaults row.
    portfolio_led = models.BooleanField(default=False)
```

Then: `POSTGRES_DB=tehsil_letter_shape uv run python manage.py makemigrations funding -n letter_shape`

- [ ] **Step 4: Implement persistence in `letter_shape.py`**

```python
from decimal import Decimal

from django.db import transaction

from apps.funding.models import ApplicationPrompt, Program


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@transaction.atomic
def apply_derived_shape(
    program: Program, cycle: str, shape: LetterShape, *, source_url: str
) -> ApplicationPrompt:
    """Write a derived shape onto this programme's prompt for one cycle.

    The ladder's precedence (spec §4): a VERIFIED row beats everything, so a
    page read never touches one. Otherwise the shape is written onto the
    (programme, cycle) row -- created if the resolver has not run yet, so a
    derivation is never lost waiting for one.

    `Program.academic_track` and `portfolio_led` are written here too, from the
    same read: a blank track is left blank on purpose and resolves as `taught`
    at use, which is the safer of the two -- it never demands a named
    supervisor the student cannot supply.
    """
    verified = ApplicationPrompt.objects.filter(
        programme=program, cycle=cycle, source=ApplicationPrompt.Source.VERIFIED
    ).first()
    if verified is not None:
        return verified
    fields = {
        "letter_document_required": shape.document_required,
        "letter_min_words": shape.min_words,
        "letter_max_words": shape.max_words,
        "letter_max_chars": shape.max_chars,
        "letter_max_pages": _decimal(shape.max_pages),
        "letter_form": shape.form,
        "letter_signed_declaration": shape.signed_declaration,
        "letter_naming": shape.naming,
        "letter_font_family": shape.font_family or "",
        "letter_font_min_pt": shape.font_min_pt,
        "letter_line_spacing": _decimal(shape.line_spacing),
        "letter_margins_cm": _decimal(shape.margins_cm),
        "letter_file_bundle": shape.file_bundle,
        "letter_handwritten": shape.handwritten,
        "letter_shape_sources": shape.sources,
        "letter_written_requirements": list(shape.written_requirements),
        "letter_student_actions": list(shape.student_actions),
    }
    prompt = ApplicationPrompt.objects.filter(programme=program, cycle=cycle).first()
    if prompt is None:
        prompt = ApplicationPrompt.objects.create(
            programme=program, cycle=cycle, source_url=source_url, confidence=0.0,
            source=ApplicationPrompt.Source.EXTRACTED,
            funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
            structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
            document_language="en", **fields,
        )
    else:
        for name, value in fields.items():
            setattr(prompt, name, value)
        prompt.save(update_fields=list(fields))
    changed: dict[str, object] = {}
    if shape.track:
        changed["academic_track"] = shape.track
    if shape.portfolio_led:
        changed["portfolio_led"] = True
    if changed:
        Program.objects.filter(id=program.id).update(**changed)
    return prompt


def shape_from_prompt(prompt: ApplicationPrompt) -> LetterShape:
    """The stored shape, as the dataclass generation and render consume.

    The programme is re-read rather than taken from `prompt.programme`
    (pre-flight ruling 4): apply_derived_shape writes academic_track with a
    queryset update(), which never refreshes an already-loaded related
    instance, so the cached one would hand back a stale track.
    """
    programme = Program.objects.get(id=prompt.programme_id)
    return LetterShape(
        document_required=prompt.letter_document_required,
        min_words=prompt.letter_min_words,
        max_words=prompt.letter_max_words,
        max_chars=prompt.letter_max_chars,
        max_pages=float(prompt.letter_max_pages) if prompt.letter_max_pages else None,
        form=prompt.letter_form,
        signed_declaration=prompt.letter_signed_declaration,
        naming=prompt.letter_naming,
        font_family=prompt.letter_font_family or None,
        font_min_pt=prompt.letter_font_min_pt,
        line_spacing=float(prompt.letter_line_spacing) if prompt.letter_line_spacing else None,
        margins_cm=float(prompt.letter_margins_cm) if prompt.letter_margins_cm else None,
        file_bundle=prompt.letter_file_bundle,
        handwritten=prompt.letter_handwritten,
        sources=dict(prompt.letter_shape_sources),
        written_requirements=tuple(prompt.letter_written_requirements),
        student_actions=tuple(prompt.letter_student_actions),
        track=programme.academic_track,
        portfolio_led=programme.portfolio_led,
    )
```

- [ ] **Step 5: Wire the derivation**

`derive_page_rules` gains two keyword arguments and one write:

```python
def derive_page_rules(
    program: Program,
    *,
    parser: ResponsesAPI,
    claude: MessagesAPI,
    page_text: str,
    snapshot: OfficialSourceSnapshot,
    admissions_cycle: str = "",
    page_language: str = "",
) -> Decision:
```

Inside, resolve the language here rather than trusting the raw attribute (pre-flight ruling 1) and pass the result to `candidates`:

```python
    language = detect_language(page_text, html_lang=page_language)
    found = candidates(page_text, statements, language=language)
```

(`from .letter_terms import detect_language` at the top of `derive.py`.) Then after
`_write_program(program.id, **fields)` add:

```python
    if admissions_cycle:
        # One read, both documents (spec §3): the letter shape comes from the
        # same samples, inside the same transaction read_and_derive holds, so
        # the CV rules and the letter shape can never sit at different
        # versions of the page. No cycle means a caller that only wants the CV
        # rules -- the shape needs a cycle to be written against.
        apply_derived_shape(
            program, admissions_cycle,
            decide_letter_shape(found, samples, source_url=snapshot.final_url)
            if found else LetterShape(),
            source_url=snapshot.final_url,
        )
```

`samples` is bound only inside the `else` branch today; hoist `samples: list[Derivations] = []` above the `if not found:` branch so the call above is always valid.

`program_rules.read_and_derive` passes both through:

```python
            derive_page_rules(
                program, parser=parser, claude=claude, page_text=result.page_text,
                snapshot=result.snapshot, admissions_cycle=admissions_cycle,
                page_language=result.page_language,
            )
```

- [ ] **Step 6: Run to verify pass**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/ -q && POSTGRES_DB=tehsil_letter_shape uv run python manage.py makemigrations --check`
Expected: PASS, "No changes detected"

- [ ] **Step 7: Commit**

```bash
git add apps/funding/models.py apps/funding/migrations/ apps/documents/letter_shape.py apps/documents/derive.py apps/documents/program_rules.py tests/documents/
git commit -m "documents: the shape the page states lands on the prompt, from the same read"
```

---

### Task 6: Defaults, sourced row by row

**Files:**
- Create: `apps/documents/letter_defaults.py`
- Modify: `apps/documents/silent_funder.py` (delegate to the new table)
- Test: `tests/documents/test_letter_defaults.py`

**Interfaces:**
- Produces: `COUNTRY_SYSTEM: dict[str, str]`; `LETTER_SHAPE_DEFAULTS: dict[tuple[str, str, bool, str], DefaultRow]`; `DefaultRow(archetypes, opening, closing, form, word_target, rules)`; `defaults_for(*, country_code, track, portfolio_led, funder_kind) -> DefaultRow`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_letter_defaults.py
import csv
from pathlib import Path

from apps.documents.letter_defaults import (
    COUNTRY_SYSTEM,
    LETTER_SHAPE_DEFAULTS,
    defaults_for,
)

_RULES = Path("docs/research/letter-shape-rules.csv")
_MAP = Path("docs/research/letter-shape-country-map.csv")
#: Only the countries this test needs to cross-check; the map names countries
#: in English prose, and a full name-to-ISO table is not this test's job.
_COUNTRY_CODES = {
    "Germany": "DE", "Austria": "AT", "Switzerland": "CH", "France": "FR",
    "Spain": "ES", "Portugal": "PT", "Japan": "JP", "South Korea": "KR",
    "Turkey": "TR", "United Kingdom": "GB", "Netherlands": "NL", "Italy": "IT",
}


def _known_rule_ids() -> set[str]:
    with _RULES.open(encoding="utf-8", newline="") as handle:
        return {row["ID"] for row in csv.DictReader(handle)}


def test_every_default_row_cites_an_existing_rule() -> None:
    known = _known_rule_ids()
    for key, row in LETTER_SHAPE_DEFAULTS.items():
        assert row.rules, key
        assert set(row.rules) <= known, (key, set(row.rules) - known)


def test_every_assigned_system_is_a_real_one() -> None:
    """Pre-flight ruling 5: A-F, and no country the map covers is contradicted.

    Asserting COUNTRY_SYSTEM's values against only the systems the research CSV
    happens to name fails a correct table whenever the sample is thin, which
    §10 says it is.
    """
    assert set(COUNTRY_SYSTEM.values()) <= set("ABCDEF")
    with _MAP.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            country, system = row["Country"].strip(), row["System"].strip()[:1]
            code = _COUNTRY_CODES.get(country)
            if code and code in COUNTRY_SYSTEM and system:
                assert COUNTRY_SYSTEM[code] == system, (country, system)


def test_an_unmapped_country_takes_the_shape_that_breaks_no_rule_anywhere() -> None:
    """Spec §5: system B's plain essay, and the resolution is logged."""
    row = defaults_for(
        country_code="ZZ", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    assert row.form == "ESSAY" and row.archetypes


def test_a_funder_kind_overrides_the_country() -> None:
    """A DAAD letter is system D wherever the university sits."""
    german = defaults_for(
        country_code="DE", track="taught", portfolio_led=False,
        funder_kind="GOVERNMENT_SCHOLARSHIP",
    )
    japanese = defaults_for(
        country_code="JP", track="taught", portfolio_led=False,
        funder_kind="GOVERNMENT_SCHOLARSHIP",
    )
    assert german.archetypes == japanese.archetypes


def test_france_defaults_to_a_formal_letter_and_the_uk_does_not() -> None:
    france = defaults_for(
        country_code="FR", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    uk = defaults_for(
        country_code="GB", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    assert france.form == "FORMAL_LETTER" and uk.form == "ESSAY"


def test_a_research_track_opens_on_the_research_position() -> None:
    row = defaults_for(
        country_code="GB", track="research", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    assert "RESEARCH_PLAN" in row.archetypes
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""Default letter shape where the page states none, sourced row by row.

Spec §5. Replaces silent_funder.DEFAULT_ARCHETYPES_BY_FUNDER_KIND, which was
five orders written to make the plan work and cited nothing. Every row here
names the `M-` rules it rests on and a test reads the catalog to check they
exist; a cell with no rule stays empty and inherits the system-level row.

Keyed by MODE, never by subject (owner, 2026-09-19): the research splits on
academic track, portfolio and reader, and the only subject effect found was
register, which §6 leaves as an unbuilt tint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Country -> lettering system, from docs/research/letter-shape-country-map.csv.
#: A country the map does not cover resolves to B, the plain essay that breaks
#: no formality rule anywhere, and the resolution is logged so the first real
#: applicant from such a country surfaces the gap.
COUNTRY_SYSTEM: dict[str, str] = {
    "DE": "A", "AT": "A", "CH": "A", "NL": "A", "BE": "A", "SE": "A", "NO": "A",
    "DK": "A", "FI": "A", "IT": "A", "PL": "A", "CZ": "A", "HU": "A",
    "GB": "B", "IE": "B", "US": "B", "CA": "B", "AU": "B", "NZ": "B", "ZA": "B",
    "FR": "C", "ES": "C", "PT": "C", "BR": "C", "MX": "C", "CL": "C", "AR": "C",
    "JP": "E", "KR": "E", "CN": "E", "TW": "E", "SG": "E", "MY": "E",
    "TR": "F", "RU": "F", "GE": "F", "AM": "F", "AZ": "F", "KZ": "F",
}
_FALLBACK_SYSTEM = "B"
#: A funder whose own sheet overrides wherever the university sits.
_FUNDER_SYSTEM = {
    "GOVERNMENT_SCHOLARSHIP": "D",
    "DEVELOPMENT_FOUNDATION": "D",
    "IMMIGRATION_AUTHORITY": "F",
}


@dataclass(frozen=True)
class DefaultRow:
    archetypes: tuple[str, ...]
    opening: str
    closing: str
    form: str
    word_target: int
    rules: tuple[str, ...]


#: (system, track, portfolio_led, funder_kind) -> row. `""` is a wildcard on
#: track and funder_kind; the lookup narrows from exact to wildcard.
LETTER_SHAPE_DEFAULTS: dict[tuple[str, str, bool, str], DefaultRow] = {
    ("A", "", False, ""): DefaultRow(
        archetypes=("ACADEMIC_PREPARATION", "WHY_PROGRAMME", "CAREER_PLAN_RETURN"),
        opening="name the programme and state the purpose in the first sentences",
        closing="close by returning to the reasons, without new claims",
        form="ESSAY", word_target=500,
        rules=("M-007", "M-008", "M-010"),
    ),
    ("B", "", False, ""): DefaultRow(
        archetypes=("WHY_PROGRAMME", "ACADEMIC_PREPARATION", "CAREER_PLAN_RETURN"),
        opening="state the purpose in the first sentences without repeating the CV",
        closing="close by returning to the reasons",
        form="ESSAY", word_target=550,
        rules=("M-040", "M-044", "M-045"),
    ),
    ("C", "", False, ""): DefaultRow(
        archetypes=("WHY_PROGRAMME", "ACADEMIC_PREPARATION", "CAREER_PLAN_RETURN"),
        opening="open on the problem or present position",
        closing="close on career in two or three sentences",
        form="FORMAL_LETTER", word_target=500,
        rules=("M-025", "M-034", "M-052", "M-056"),
    ),
    ("D", "", False, ""): DefaultRow(
        archetypes=(
            "WHY_COUNTRY", "WHY_PROGRAMME", "ACADEMIC_PREPARATION",
            "CAREER_PLAN_RETURN", "HOME_COUNTRY_CONTRIBUTION",
        ),
        opening="state the professional goal and the sector",
        closing="close on the contribution to the home country, with facts",
        form="ESSAY", word_target=450,
        rules=("M-001", "M-002", "M-003"),
    ),
    ("E", "", False, ""): DefaultRow(
        archetypes=("ACADEMIC_PREPARATION", "WHY_PROGRAMME", "CAREER_PLAN_RETURN"),
        opening="open on the study plan",
        closing="close on the plan after graduation",
        form="ESSAY", word_target=500,
        rules=("M-049", "M-068"),
    ),
    ("F", "", False, ""): DefaultRow(
        archetypes=("WHY_PROGRAMME", "WHY_COUNTRY", "PERSONAL_BACKGROUND",
                    "CAREER_PLAN_RETURN"),
        opening="state the purpose of the stay in the first sentences",
        closing="close on the intention to return",
        form="FORMAL_LETTER", word_target=500,
        rules=("M-084", "M-101"),
    ),
    # Mode rows: a research track names the plan, a portfolio-led one names the work.
    ("", "research", False, ""): DefaultRow(
        archetypes=("RESEARCH_PLAN", "ACADEMIC_PREPARATION", "CAREER_PLAN_RETURN"),
        opening="open on the research question",
        closing="close on the fit with the group's work",
        form="", word_target=0,
        rules=("M-011", "M-112"),
    ),
    ("", "", True, ""): DefaultRow(
        archetypes=("ACADEMIC_PREPARATION", "WHY_PROGRAMME", "CAREER_PLAN_RETURN"),
        opening="open on the work in the portfolio",
        closing="close on what the programme adds to it",
        form="", word_target=0,
        rules=("M-062",),
    ),
}


def defaults_for(
    *, country_code: str, track: str, portfolio_led: bool, funder_kind: str
) -> DefaultRow:
    """The default row for one programme's mode.

    The funder's own system overrides the country's: a DAAD letter is system D
    whatever country the university sits in, and an immigration authority is F.
    A blank track resolves as taught -- the safer of the two, because it never
    demands a named supervisor the student cannot supply.
    """
    system = _FUNDER_SYSTEM.get(funder_kind)
    if system is None:
        system = COUNTRY_SYSTEM.get(country_code.upper(), "")
        if not system:
            logger.warning(
                "country %r has no lettering system; using the plain essay", country_code
            )
            system = _FALLBACK_SYSTEM
    base = LETTER_SHAPE_DEFAULTS[(system, "", False, "")]
    mode = (
        LETTER_SHAPE_DEFAULTS.get(("", track, False, ""))
        if track == "research"
        else LETTER_SHAPE_DEFAULTS.get(("", "", True, "")) if portfolio_led else None
    )
    if mode is None:
        return base
    # A mode row overrides only the cells it fills; empty cells inherit.
    return DefaultRow(
        archetypes=mode.archetypes or base.archetypes,
        opening=mode.opening or base.opening,
        closing=mode.closing or base.closing,
        form=mode.form or base.form,
        word_target=mode.word_target or base.word_target,
        rules=base.rules + mode.rules,
    )
```

- [ ] **Step 4: Point `silent_funder` at it**

Replace the body of `apply_silent_funder_defaults` so the archetypes and word target come from `defaults_for`, keeping its signature and its `ConstraintRule` output. Add a `country_code`, `track`, `portfolio_led` keyword with defaults so existing callers keep working, and note in the docstring that `DEFAULT_ARCHETYPES_BY_FUNDER_KIND` is superseded. Do **not** delete the old dict in this task — `tests/documents/test_silent_funder.py` references it; delete it in the same commit only if that file has no other use for it (`grep -rn DEFAULT_ARCHETYPES_BY_FUNDER_KIND apps tests`).

- [ ] **Step 5: Run**

Run: `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_defaults.py tests/documents/test_silent_funder.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/documents/letter_defaults.py apps/documents/silent_funder.py tests/documents/test_letter_defaults.py
git commit -m "documents: letter defaults keyed by mode, every row citing its rule"
```

---

# Increment 2 — the letter is written and rendered inside the shape

### Task 7: Generation inside the shape

**Files:**
- Modify: `apps/documents/letters.py` (`generate_letter`, `_call_model`)
- Test: `tests/documents/test_letters.py` (append)

**Interfaces:**
- Consumes: `shape_from_prompt`, `defaults_for`.
- Produces: `_shape_instructions(shape, row) -> str`; `generate_letter` raises `NotGeneratable("naming required, no confirmed fit")`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/documents/test_letters.py
import pytest

from apps.documents.letters import NotGeneratable, _shape_instructions
from apps.documents.letter_defaults import defaults_for
from apps.documents.letter_shape import LetterShape


def _row():
    return defaults_for(
        country_code="GB", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )


def test_the_target_length_sits_inside_the_cap_and_above_the_floor() -> None:
    text = _shape_instructions(LetterShape(max_words=500, min_words=300), _row())
    assert "425 words" in text  # 85% of the smaller cap
    assert "at least 300" in text


def test_a_forbidden_naming_shape_forbids_named_people_in_the_prompt() -> None:
    text = _shape_instructions(LetterShape(naming="FORBIDDEN"), _row())
    assert "do not name" in text.lower()


def test_a_written_requirement_reaches_the_prompt_as_quoted_data() -> None:
    shape = LetterShape(
        written_requirements=({"text": "Write in the third person.", "source_url": "u"},)
    )
    text = _shape_instructions(shape, _row())
    assert "The programme states: 'Write in the third person.'" in text


def test_a_required_naming_shape_with_no_confirmed_fit_stops_with_a_named_reason(
    student, prompt_requiring_naming
) -> None:
    with pytest.raises(NotGeneratable, match="naming required, no confirmed fit"):
        generate_letter(
            student=student, prompt=prompt_requiring_naming, facts={}, inputs={},
            forbidden_institution_names=frozenset(),
        )
```

- [ ] **Step 2: Run to verify failure** — `cannot import name '_shape_instructions'`

- [ ] **Step 3: Implement**

In `apps/documents/letters.py`:

```python
def _shape_instructions(shape: LetterShape, row: DefaultRow) -> str:
    """The page's shape, and the default row's moves, as prompt text.

    Aim at 85% of the smaller cap and never below the floor: a letter written
    to the cap overruns it once hygiene and the header block are added, and a
    letter under a stated floor is rejected outright (HBKU, M-091).
    """
    target = shape.max_words or row.word_target
    parts = [
        f" Write about {int(target * 0.85)} words.",
        f" Open so as to {row.opening}; {row.closing}.",
    ]
    if shape.min_words:
        parts.append(f" The letter must be at least {shape.min_words} words.")
    if shape.max_chars:
        parts.append(f" It must not exceed {shape.max_chars} characters including spaces.")
    if shape.form == "FORMAL_LETTER":
        parts.append(
            " Write the body of a formal letter: the date, addressee, salutation and "
            "sign-off are added at render, so do not write them."
        )
    if shape.naming == "FORBIDDEN":
        parts.append(
            " Do not name any person, research group, laboratory or module of the "
            "target institution."
        )
    elif shape.naming == "REQUIRED":
        parts.append(
            " Name the specific supervisor, group or modules given in the data, and "
            "never a name that is not there."
        )
    for requirement in shape.written_requirements:
        # The sentence is quoted as data, exactly as every other untrusted
        # string in this prompt is; it is checked after generation (§3b path 2).
        parts.append(
            f" The programme states: '{requirement['text']}'. Write so that this is satisfied."
        )
    return "".join(parts)
```

In `generate_letter`, after the structure check and before the rate limit:

```python
    shape = shape_from_prompt(prompt)
    row = defaults_for(
        country_code=prompt.programme.country_code,
        track=prompt.programme.academic_track,
        portfolio_led=prompt.programme.portfolio_led,
        funder_kind=prompt.funder_kind,
    )
    if shape.naming == "REQUIRED" and not any(
        getattr(value, "confirmed_fit", False) for value in inputs.values()
    ):
        # Never invent a professor. The page requires a name, the ledger has
        # none, and a letter naming somebody the student never spoke to is the
        # one failure this engine must not ship.
        raise NotGeneratable("naming required, no confirmed fit")
```

and thread `shape`/`row` into `_call_model`, which appends `_shape_instructions(shape, row)` to `instructions` before the structure-specific branch.

If `NarrativeInput` has no `confirmed_fit` attribute yet (`grep -n "confirmed_fit" apps/`), use the research-fit design's field name if present, else gate on `inputs` being non-empty **and** record a `# ponytail:` note naming the real check to wire when the 2026-09-15 fit design lands.

- [ ] **Step 4: Run** — `POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letters.py -q`

- [ ] **Step 5: Commit**

```bash
git add apps/documents/letters.py tests/documents/test_letters.py
git commit -m "documents: the letter is written inside the page's shape"
```

---

### Task 8: Render inside the shape, and the formal template

**Files:**
- Create: `docs/research/letter-formalities.csv`, `apps/documents/templates/documents/letter_formal.html`
- Modify: `apps/documents/letter_render.py`, `apps/documents/letter_shape.py` (`constraints_from_shape`)
- Test: `tests/documents/test_letter_formal_render.py`

**Interfaces:**
- Produces: `constraints_from_shape(shape) -> tuple[ConstraintRule, ...]`; `FORMALITIES: dict[str, Formality]`; `select_letter_variant(structure, *, form="ESSAY") -> str` with a new `"LETTER_FORMAL"` variant; `SHIPPED_FONTS: frozenset[str]`.

- [ ] **Step 1: Write the formalities CSV**

```csv
"language","salutation","closing","place_and_date","source"
"en","Dear Sir or Madam,","Yours faithfully,","no","M-016"
"fr","Madame, Monsieur,","Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées.","yes","M-025"
"es","Estimado/a Señor/a:","Atentamente,","yes","M-034"
"pt","Exmo.(a) Senhor(a),","Com os melhores cumprimentos,","yes","M-101"
"de","Sehr geehrte Damen und Herren,","Mit freundlichen Grüßen,","yes","M-084"
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/documents/test_letter_formal_render.py
import pytest

from apps.documents.letter_shape import LetterShape, constraints_from_shape
from apps.documents.letter_render import SHIPPED_FONTS, render_letter, select_letter_variant
from apps.documents.render import PreflightBlocked


def test_the_shape_becomes_binding_rules_carrying_their_sentence() -> None:
    shape = LetterShape(
        max_words=500, min_words=300,
        sources={
            "max_words": {"text": "no more than 500 words", "source_url": "u"},
            "min_words": {"text": "at least 300 words", "source_url": "u"},
        },
    )
    rules = {rule.key: rule for rule in constraints_from_shape(shape)}
    assert rules["max_words"].value == 500
    assert rules["max_words"].rule_text == "no more than 500 words"
    assert rules["max_words"].enforcement == "BINDING"
    assert rules["min_words"].value == 300


def test_a_formal_shape_selects_the_formal_template() -> None:
    assert select_letter_variant("CONTINUOUS_LETTER", form="FORMAL_LETTER") == "LETTER_FORMAL"
    assert select_letter_variant("CONTINUOUS_LETTER", form="ESSAY") == "LETTER_PDF"


def test_a_floor_blocks_a_short_letter_with_the_pages_sentence(short_content) -> None:
    shape = LetterShape(
        min_words=300, sources={"min_words": {"text": "at least 300 words", "source_url": "u"}}
    )
    with pytest.raises(PreflightBlocked, match="at least 300 words"):
        render_letter(
            short_content, structure="CONTINUOUS_LETTER",
            constraints=constraints_from_shape(shape), shape=shape,
        )


def test_a_font_we_do_not_ship_blocks_rather_than_substitutes(content) -> None:
    shape = LetterShape(font_family="Garamond Pro")
    assert "Garamond Pro" not in SHIPPED_FONTS
    with pytest.raises(PreflightBlocked, match="Garamond Pro"):
        render_letter(content, structure="CONTINUOUS_LETTER", shape=shape)


def _letter_html(content, shape, language: str = "en") -> str:
    """Render the formal template with the same context render_letter builds.

    Pre-flight ruling 3: these assertions are about the rendered CSS, and going
    through render_letter would drag PDF generation into a template test.
    Template SELECTION is covered by its own test above.
    """
    from django.template.loader import render_to_string

    from apps.documents.letter_render import FORMALITIES

    return render_to_string(
        "documents/letter_formal.html",
        {
            "content": content,
            "shape": shape,
            "formality": FORMALITIES.get(language),
            "addressee": "Admissions Committee",
            "place_and_date": "Strasbourg, 19 September 2026",
            "applicant_name": "A Student",
        },
    )


def test_spacing_and_margins_reach_the_rendered_css(content) -> None:
    shape = LetterShape(line_spacing=2.0, margins_cm=2.5, font_min_pt=12)
    html = _letter_html(content, shape)
    assert "line-height: 2.0" in html and "margin: 2.5cm" in html and "12pt" in html


def test_a_language_with_no_formality_row_falls_back_to_essay(content) -> None:
    """Never borrow another language's salutation (spec §6)."""
    shape = LetterShape(form="FORMAL_LETTER")
    html = _letter_html(content, shape, language="tr")
    assert "Sehr geehrte" not in html and "Dear" not in html
```

- [ ] **Step 3: Run to verify failure**

- [ ] **Step 4: Implement**

`letter_shape.py` gains:

```python
from .constraints import ConstraintRule, Enforcement

#: The shape fields letter_render can measure, and the constraint key each one
#: becomes. max_chars maps to the inclusive key: every page measured in the
#: research counts spaces (M-012, M-014).
_SHAPE_TO_KEY = {
    "max_words": "max_words",
    "min_words": "min_words",
    "max_chars": "max_chars_incl_spaces",
    "max_pages": "max_pages",
}


def constraints_from_shape(shape: LetterShape) -> tuple[ConstraintRule, ...]:
    """The shape as BINDING rules, each carrying the sentence that set it.

    BINDING because nobody reviews the letter: an advisory violation here
    would be a warning with no reader, and a letter over a published cap is
    rejected by the portal that counts it.
    """
    rules: list[ConstraintRule] = []
    for name, key in _SHAPE_TO_KEY.items():
        value = getattr(shape, name)
        if value is None:
            continue
        source = shape.sources.get(name, {})
        rules.append(ConstraintRule(
            rule_id=f"SHAPE-{name[:14]}",
            key=key,  # type: ignore[arg-type]
            value=value,
            enforcement=Enforcement.BINDING,
            rule_text=source.get("text") or f"engine default for {name}",
            source_url=source.get("source_url", ""),
        ))
    return tuple(rules)
```

`letter_render.py` gains the variant, the font allowlist, the formalities loader and a `shape` keyword on `render_letter` that:
1. raises `PreflightBlocked` when `shape.font_family` is set and not in `SHIPPED_FONTS`;
2. selects `LETTER_FORMAL` when `shape.form == "FORMAL_LETTER"` **and** the content's language has a formalities row, else falls back to `LETTER_PDF` and logs the missing language;
3. passes `shape` and the formality row into the template context;
4. leaves every existing call path unchanged when `shape` is `None`.

`SHIPPED_FONTS = frozenset({"Helvetica", "Times New Roman", "Arial", "Calibri", "Georgia"})` — verify against what WeasyPrint resolves in the container before committing to the list; a name that resolves to a substitute is worse than a block.

- [ ] **Step 5: Write `letter_formal.html`**

```html
<!DOCTYPE html>
<html lang="{{ content.language }}">
<head><meta charset="utf-8"><style>
  @page { margin: {{ shape.margins_cm|default:2 }}cm; }
  body { font-family: "{{ shape.font_family|default:'Helvetica' }}", sans-serif;
         font-size: {{ shape.font_min_pt|default:11 }}pt;
         line-height: {{ shape.line_spacing|default:'1.5' }}; }
  .place-date { text-align: right; margin-bottom: 18pt; }
  .addressee { margin-bottom: 18pt; white-space: pre-line; }
  .salutation, .closing { margin: 12pt 0; }
  .signature { margin-top: 36pt; }
  p { margin: 0 0 8pt; }
</style></head>
<body>
  {% if formality.place_and_date %}<div class="place-date">{{ place_and_date }}</div>{% endif %}
  <div class="addressee">{{ addressee }}</div>
  <div class="salutation">{{ formality.salutation }}</div>
  {% for unit in content.units %}<p>{{ unit.text }}</p>{% endfor %}
  <div class="closing">{{ formality.closing }}</div>
  <div class="signature">{{ applicant_name }}</div>
</body>
</html>
```

Format the date with the existing `cv_dates` templatetag for `content.language`; pass `addressee` as the committee or coordinator named on the prompt, falling back to the programme's own name.

- [ ] **Step 6: Run and commit**

```bash
POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/ -q
git add docs/research/letter-formalities.csv apps/documents/templates/documents/letter_formal.html apps/documents/letter_render.py apps/documents/letter_shape.py tests/documents/test_letter_formal_render.py
git commit -m "documents: the letter is rendered inside the shape, formalities from their own row"
```

---

### Task 9: The naming gate

**Files:**
- Modify: `apps/documents/letter_gates.py`, `apps/documents/letters.py` (`_evaluate`)
- Test: `tests/documents/test_letter_naming_gate.py`

**Interfaces:**
- Produces: `GateCode.NAMING_FORBIDDEN`; `check_naming_forbidden(content, *, naming, institution_names, research_names) -> tuple[LetterGateViolation, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_letter_naming_gate.py
from apps.documents.letter_gates import GateCode, check_naming_forbidden


def test_a_named_professor_blocks_when_the_page_forbids_naming(content_naming_a_professor):
    violations = check_naming_forbidden(
        content_naming_a_professor, naming="FORBIDDEN",
        institution_names=frozenset({"Example University"}),
        research_names=frozenset({"Professor Jane Roe", "Robotics Group"}),
    )
    assert [v.code for v in violations] == [GateCode.NAMING_FORBIDDEN]


def test_nothing_blocks_when_the_page_does_not_forbid_naming(content_naming_a_professor):
    assert check_naming_forbidden(
        content_naming_a_professor, naming="INVITED",
        institution_names=frozenset(), research_names=frozenset({"Professor Jane Roe"}),
    ) == ()


def test_an_unrelated_capitalised_phrase_does_not_block(content_naming_a_city):
    assert check_naming_forbidden(
        content_naming_a_city, naming="FORBIDDEN",
        institution_names=frozenset({"Example University"}), research_names=frozenset(),
    ) == ()
```

- [ ] **Step 2: Implement**

Add `NAMING_FORBIDDEN = "NAMING_FORBIDDEN"` to `GateCode`, then:

```python
def check_naming_forbidden(
    content: LetterContent,
    *,
    naming: str,
    institution_names: frozenset[str],
    research_names: frozenset[str],
) -> tuple[LetterGateViolation, ...]:
    """No named person, group or lab of the target institution, when forbidden.

    Reuses _CAPITALISED_PHRASE_PATTERN (check_claim_coverage's proper-noun
    detection) and resolves a hit against names we already hold -- the
    institution's own name, and the proper-noun phrases appearing in the
    programme's ProgramStatement rows of ANY kind -- rather than blocking every
    capitalised phrase, which would block a city.

    Pre-flight ruling 3b: the spec says "RESEARCH rows" and ProgramStatement
    has no such kind (COMPETENCY, DOCUMENT, FORMAT, LANGUAGE, OTHER). The
    statements are where a named group or lab actually appears, so the caller
    scans them all.

    A hit blocks and there is no override, because there is nobody to override.
    """
    if naming != "FORBIDDEN":
        return ()
    known = {name.casefold() for name in institution_names | research_names}
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        for match in _CAPITALISED_PHRASE_PATTERN.finditer(unit.text):
            phrase = match.group()
            if phrase.casefold() in known:
                violations.append(LetterGateViolation(
                    GateCode.NAMING_FORBIDDEN,
                    f"the page forbids naming; the letter names {phrase!r}",
                    unit.archetype,
                ))
    return tuple(violations)
```

Call it from `run_letter_gates` with a new `naming` / `research_names` keyword pair, and thread those from `letters._evaluate` off the shape and the programme's `ProgramStatement` RESEARCH rows.

- [ ] **Step 3: Run and commit**

```bash
POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_letter_naming_gate.py tests/documents/test_letter_gates.py -q
git add apps/documents/letter_gates.py apps/documents/letters.py tests/documents/test_letter_naming_gate.py
git commit -m "documents: a forbidden name blocks, with no override"
```

---

### Task 10: The written-requirement check, and one bounded regeneration

**Files:**
- Modify: `apps/documents/letter_verification.py`, `apps/documents/letters.py`
- Test: `tests/documents/test_written_requirements.py`

**Interfaces:**
- Produces: `RequirementVerdict` (Pydantic: `index: int`, `satisfied: bool`); `check_written_requirements(content, requirements, *, parser, claude, program_id) -> tuple[str, ...]` returning the sentences every reading judged unsatisfied.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_written_requirements.py
from apps.documents.letter_verification import check_written_requirements


def test_a_unanimous_no_names_the_sentence(content, fake_parser, fake_claude) -> None:
    fake_parser.answer(satisfied=False)
    fake_claude.answer(satisfied=False)
    unmet = check_written_requirements(
        content, ({"text": "Write in the third person.", "source_url": "u"},),
        parser=fake_parser, claude=fake_claude, program_id="p",
    )
    assert unmet == ("Write in the third person.",)


def test_one_reading_saying_yes_is_enough_to_pass(content, fake_parser, fake_claude) -> None:
    """The bar is unanimity to BLOCK: a regeneration costs a call, and a
    disagreed requirement is not evidence the letter breaks it."""
    fake_parser.answer(satisfied=False)
    fake_claude.answer(satisfied=True)
    assert check_written_requirements(
        content, ({"text": "Write in the third person.", "source_url": "u"},),
        parser=fake_parser, claude=fake_claude, program_id="p",
    ) == ()


def test_no_requirements_makes_no_model_call(content, fake_parser, fake_claude) -> None:
    assert check_written_requirements(
        content, (), parser=fake_parser, claude=fake_claude, program_id="p"
    ) == ()
    assert fake_parser.calls == 0
```

- [ ] **Step 2: Implement**

One call carries **every** requirement as a numbered listing, asked three times in the same two-family split the deriver uses — three calls per letter, not three per sentence. Cap `max_output_tokens`; label the letter and the sentences DATA; return only sentences every reading marked unsatisfied.

In `generate_letter`, after the gates pass, run the check; on a non-empty result take the **one** bounded regeneration `letters.py` already has, passing the unmet sentences as `retry_note`; a second non-empty result raises `PreflightBlocked` naming the sentence.

- [ ] **Step 3: Run and commit**

```bash
POSTGRES_DB=tehsil_letter_shape uv run pytest tests/documents/test_written_requirements.py tests/documents/test_letters.py -q
git add apps/documents/letter_verification.py apps/documents/letters.py tests/documents/test_written_requirements.py
git commit -m "documents: a requirement no column can type is written to, then checked"
```

---

# Increment 3 — shown, counted and proved

### Task 11: The requirements service, and the Kit seam

**Files:**
- Create: `apps/funding/requirements.py`, `apps/documents/management/commands/letter_requirement_backlog.py`
- Test: `tests/funding/test_requirements.py`

**Interfaces:**
- Produces: `program_requirements(programme, *, cycle) -> Requirements` with `.letter`, `.cv`, `.applicant`, each a `tuple[RequirementItem, ...]`; `RequirementItem(text, source_url, requirement, status, statement_id)`; `letter_kit_steps(prompt) -> tuple[RequirementItem, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/funding/test_requirements.py
import pytest

from apps.funding.requirements import letter_kit_steps, program_requirements


@pytest.mark.django_db
def test_the_letter_pane_shows_each_rule_with_its_sentence_and_status(programme_with_shape):
    panes = program_requirements(programme_with_shape, cycle="2027")
    by_text = {item.text: item for item in panes.letter}
    assert by_text["no more than 500 words"].status == "enforced at render"
    assert by_text["Write in the third person."].status == "written to and checked"
    assert by_text["Sign it in ink."].status == "your action"


@pytest.mark.django_db
def test_the_applicant_pane_carries_no_verdict_yet(programme_with_statements):
    panes = program_requirements(programme_with_statements, cycle="2027")
    assert {item.status for item in panes.applicant} == {
        "Stated by the programme. Not yet checked against your record."
    }


@pytest.mark.django_db
def test_kit_steps_are_the_same_objects_the_letter_pane_shows(programme_with_shape):
    panes = program_requirements(programme_with_shape, cycle="2027")
    prompt = programme_with_shape.application_prompts.get(cycle="2027")
    assert letter_kit_steps(prompt) == tuple(
        item for item in panes.letter if item.status == "your action"
    )
```

- [ ] **Step 2: Implement**

Read-only, from data already in the catalog. End the module with:

```python
# SHOULD BE DONE BY AYKHAN: the window that shows these three panes is the
# presentation layer's, and this service is the one thing it calls. The
# Application Kit (2026-09-15 glass-box design) has no model yet -- when it
# lands it reads letter_kit_steps(prompt) rather than the prompt's JSON
# directly, so this is the only seam that moves.
```

- [ ] **Step 3: Implement the backlog command**

`letter_requirement_backlog` counts `letter_written_requirements` and `letter_student_actions` across every prompt, grouped by normalised sentence, printing frequency and one example URL. Spec §3b: a kind seen on three or more programmes becomes the next closed question.

- [ ] **Step 4: Run and commit**

```bash
POSTGRES_DB=tehsil_letter_shape uv run pytest tests/funding/test_requirements.py -q
git add apps/funding/requirements.py apps/documents/management/commands/letter_requirement_backlog.py tests/funding/test_requirements.py
git commit -m "funding: the three requirement panes, and the counter that finds the next column"
```

---

### Task 12: The eval sheet and the live gate

**Files:**
- Create: `docs/research/letter-shape-eval.csv`
- Modify: `tests/documents/test_letter_derive.py` (live gate)

- [ ] **Step 1: Build the sheet**

At least 60 rows drawn from the `M-` catalog **in their original languages**, columns
`id,language,sentence,expected_field,expected_value,source_url`. Include the sentences §8 names by hand: Hamburg's "maximum length is 1.5 pages"; HBKU's below-the-minimum rule; Fulbright's "References to proposed universities or faculty should not be made"; TUM's "maximal zwei DIN-A4-Seiten"; Sciences Po's "en maximum 1 000 mots"; Eiffel's "sur une ou deux pages"; Chile's "extensión máxima de 500 palabras"; UNAM's "máximo de 2 cuartillas"; USP's "de até 2 páginas"; TMU's 讀書計畫 / 自傳; the Korean byte cap; the Japanese single-spacing rule.

- [ ] **Step 2: Write the live gate**

```python
@pytest.mark.live
def test_the_judge_reads_every_language_in_the_eval_sheet() -> None:
    """Per-language recall and precision, printed per language, never averaged.

    The bar: zero wrong caps and zero missed naming=FORBIDDEN in every
    language present. Re-run before any change to the judge prompt.
    """
```

Model it on `tests/documents/test_derive.py`'s existing `live` gate: real `OPENAI_EXTRACTION_MODEL` and `ANTHROPIC_JUDGE_MODEL`, one listing per language, printing a line per language so a language the judge reads badly is visible **as a language**.

- [ ] **Step 3: Seal the held-out acceptance country**

Write `docs/superpowers/plans/2026-09-19-letter-shape-acceptance.md` naming ONE country whose script the eval sheet does not train on (candidates: Japan, Korea, Saudi Arabia, Russia), chosen and committed **before** any rule is edited, with its programme URLs. It is read once at the end and checked by a human against the pages. Per-country numbers on the eval sheet are development scores; this one is the acceptance score.

- [ ] **Step 4: Full validation**

```bash
POSTGRES_DB=tehsil_letter_shape uv run pytest -q
uv run ruff check apps tests config
uv run mypy apps config
POSTGRES_DB=tehsil_letter_shape uv run python manage.py makemigrations --check
uv run bandit -c pyproject.toml -r apps config -q
POSTGRES_DB=tehsil_letter_shape uv run pytest -m live tests/documents/test_letter_derive.py -q  # costs real credits
```

- [ ] **Step 5: Commit**

```bash
git add docs/research/letter-shape-eval.csv docs/superpowers/plans/2026-09-19-letter-shape-acceptance.md tests/documents/test_letter_derive.py
git commit -m "documents: the eval sheet in its own languages, and a sealed acceptance country"
```

---

## Self-Review

**Spec coverage.** §1 fifteen columns → Task 5; §2 mode from the same read → Tasks 3-5; §3 one read both documents, language first → Tasks 1-3; §3b three application paths → Tasks 4 (classification), 7 (path 2 into the prompt), 8 (path 1 at render), 10 (the check), 11 (path 3 and the counter); §4 safer direction per field → Task 4; §5 defaults → Task 6; §6 generation, render, template, gate → Tasks 7-9; §7 requirements service → Task 11; §8 proof → every task's tests plus Task 12; §9 cost → held by Task 3 riding the existing call; §10 the research is a sample → Task 11's counter and Task 12's held-out country.

**Known gaps, stated rather than hidden.**
- **The Application Kit has no model.** Path-3 actions are stored on the prompt and exposed by `letter_kit_steps`; "the letter's Kit entry is not complete until they are ticked" (§3b) cannot be implemented until the Kit exists, and no task pretends otherwise.
- **`naming=REQUIRED` needs the research-fit design's `NarrativeInput`**, which is a separate spec awaiting owner review. Task 7 raises `NotGeneratable` on a missing fit and names the field to wire when that lands.
- **Language detection ships without a library.** The constraint and its revisit trigger are in Global Constraints.
- **The `SHIPPED_FONTS` list is unverified.** Task 8 Step 4 requires checking what WeasyPrint actually resolves in the container before the list is committed: a family name that silently resolves to a substitute is worse than a block, because the page asked for a specific font and got a different one with nothing saying so.

**Type consistency.** `LetterShape` field names match `_SHAPE_TO_KEY`, `apply_derived_shape`'s `fields` dict and `shape_from_prompt` one-for-one. `LetterVerdict.requirement_path` values (`render`/`writer`/`student`/`none`) match `decide_letter_shape`'s branches. `Candidate.cv`/`.letter` are honoured by `outcomes` (Task 2 Step 3 adds the `if not candidate.cv: continue` guard, with its own test) so a letter-only line can never abstain the CV page, and by `decide_letter_shape`'s `if not candidate.letter: continue` so a CV-only line never sets a letter field.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-19-letter-shape-tailoring.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, reviewed between tasks, fast iteration.
2. **Inline Execution** — tasks executed in this session with checkpoints for review.
