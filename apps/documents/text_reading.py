"""What a diploma or language certificate read proves (spec 2026-10-12 §5.3).

Azure reads the pages as pictures (ocr.flatten), two readers from different model
families quote fields out of that text with the student's identifiers stripped, and
code decides. A value is proven only when both readers quoted the same characters,
the quote is on the page as Azure read it, Azure was sure of every word in it, and --
on a born-digital PDF -- the quote is among the page's visible characters. Code, never
a model, turns a quote into an ISO date or a score."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from functools import cache

from django.conf import settings
from pydantic import BaseModel

from apps.research.locale_names import fold, month_forms

from . import ocr
from .azure_layout import AzureLayout, AzureWord, analyze_layout
from .fact_readers import read_quotes
from .id_reading import NotRead, ReadValue, owner_matches_document_text
from .ocr_errors import OcrUnavailable
from .transcript import _fold, _nfc

_SNIPPET = 200
_PLACEHOLDER = "[REDACTED]"

#: Closed test list (spec §5.3.3): alias pattern, matched as whole words in the folded
#: quote -> (test name, language). YDS is set in English, German, French and others, so
#: it names no language. A sibling exam on another scale is excluded before any alias.
_TEST_ALIASES: tuple[tuple[str, str, str], ...] = (
    (r"duolingo", "Duolingo English Test", "English"),
    (r"c2\s+proficiency|cpe|cambridge\s+english:?\s+proficiency",
     "Cambridge English C2 Proficiency", "English"),
    (r"c1\s+advanced|cae|cambridge\s+english:?\s+advanced",
     "Cambridge English C1 Advanced", "English"),
    (r"ielts", "IELTS", "English"),
    (r"toefl", "TOEFL", "English"),
    (r"pte", "PTE", "English"),
    (r"testdaf", "TestDaF", "German"),
    (r"delf", "DELF", "French"),
    (r"dalf", "DALF", "French"),
    (r"topik", "TOPIK", "Korean"),
    (r"jlpt|japanese-language\s+proficiency", "JLPT", "Japanese"),
    (r"hsk", "HSK", "Chinese"),
    (r"yds", "YDS", ""),
)
#: TOEFL Essentials is on a 1-12 scale, so it is excluded with the school-age TOEFLs.
_NOT_A_LISTED_TEST = re.compile(r"(?<!\w)(?:pre-toefl|toefl\s+(?:itp|primary|junior|essentials))"
                                r"(?!\w)")
TESTS = {name: language for _alias, name, language in _TEST_ALIASES}
#: Test -> ((low, high, step) overall, (low, high, step) per section); step None: any.
_RANGES: dict[str, tuple[tuple[int, int, str | None], tuple[int, int, str | None]]] = {
    "IELTS": ((0, 9, "0.5"), (0, 9, "0.5")),
    "TOEFL": ((0, 120, None), (0, 30, None)),
    "Duolingo English Test": ((10, 160, None), (10, 160, None)),
    "PTE": ((10, 90, None), (10, 90, None)),
}
_SCORES = frozenset({"overall", "listening", "reading", "writing", "speaking"})
_CEFR = re.compile(r"\b([ABC][12])\b")
#: A standalone ASCII number; one glued to a letter ("B2", "Band6.5") is not counted.
_SCORE = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?!\w|[.,]\d)", re.ASCII)
_BETWEEN = re.compile(r"[\s./,-]{1,3}")


@cache
def _months() -> dict[str, frozenset[int]]:
    """Folded month name or abbreviation, every language -> month numbers."""
    months: dict[str, set[int]] = defaultdict(set)
    for name, _lang, number in month_forms():
        months[fold(name)].add(number)
        months[_fold(name)].add(number)
    return {name: frozenset(numbers) for name, numbers in months.items()}


def _is_birth(parts: list[str], born: date) -> bool:
    """Three tokens printing `born` as day-month-year, month-day-year or year-month-day,
    the month as a number or a name, the year in two or four digits."""
    day = re.compile(rf"0?{born.day}(?:st|nd|rd|th)?", re.IGNORECASE)

    def is_month(part: str) -> bool:
        return part in (str(born.month), f"{born.month:02}") or born.month in _months().get(
            _fold(part), ())

    def is_year(part: str) -> bool:
        return part in (str(born.year), f"{born.year % 100:02}")

    days = [bool(day.fullmatch(p)) for p in parts]
    months = [is_month(p) for p in parts]
    years = [is_year(p) for p in parts]
    return any(days[a] and months[b] and years[c] for a, b, c in ((0, 1, 2), (1, 0, 2), (2, 1, 0)))


def _strip_birth(text: str, born: date) -> str:
    compact = {f"{born:%d%m%Y}", f"{born:%Y%m%d}", f"{born:%m%d%Y}"}
    tokens = list(re.finditer(r"\w+", text))
    spans: list[tuple[int, int]] = []
    for i, token in enumerate(tokens):
        if token.group() in compact:
            spans.append(token.span())
        run = tokens[i:i + 3]
        if len(run) == 3 and all(_BETWEEN.fullmatch(text[a.end():b.start()])
                                 for a, b in zip(run, run[1:], strict=False)) and _is_birth(
                [t.group() for t in run], born):
            spans.append((run[0].start(), run[2].end()))
    for start, end in sorted(spans, reverse=True):
        if _PLACEHOLDER not in text[start:end]:
            text = text[:start] + _PLACEHOLDER + text[end:]
    return text


def strip_identifiers(text: str, identifiers: list[str]) -> str:
    """The readers' copy, with what names the student replaced (spec §8). Verification
    always runs on the unstripped text.

    - A name: every word of 2+ letters, matched word by word after the transcript reader's
      folding (NFC, casefold, diacritics and the Turkic/Azerbaijani İ ı Ə folded), so
      ƏLİYEVA, ALİYEVA and Aliyeva are one word.
    - An ISO date of birth: day-month-year, month-day-year or year-month-day, any of
      `. / - ,` or spaces between, a two- or four-digit year, the month as a number or a
      name in any language locale_names knows (en, az, tr, ru among them), and the
      eight-digit compact forms. Six-digit compacts are left: they collide with document
      numbers the readers must quote.
    - Anything else with a digit or an `@` (an ID number, a phone, an e-mail) is matched
      whole, ignoring spaces and hyphens -- never word by word, or an address at baku.edu.az
      would strip "Baku State University".

    Known limit: a name printed in another script (Алиева for an account's Aliyeva) is not
    transliterated, and reaches the readers.
    """
    text = _nfc(text)
    names: set[str] = set()
    for identifier in (_nfc(i.strip()) for i in identifiers):
        if not identifier:
            continue
        try:
            text = _strip_birth(text, date.fromisoformat(identifier))
            continue
        except ValueError:
            pass
        if "@" in identifier or any(char.isdigit() for char in identifier):
            body = r"[\s-]*".join(re.escape(c) for c in re.sub(r"[\s-]", "", identifier))
            text = re.sub(rf"(?<![^\W_]){body}(?![^\W_])", _PLACEHOLDER, text,
                          flags=re.IGNORECASE)
        else:
            names.update(_fold(w) for w in re.findall(r"\w+", identifier) if len(w) >= 2)
    return re.sub(r"\w+", lambda m: _PLACEHOLDER if _fold(m.group()) in names else m.group(),
                  text)


def _pattern(quote: str) -> re.Pattern[str]:
    """Whole tokens only: a quoted "5" is not on a page that prints "6.5", "25AZ" or
    "25AZ/000123"."""
    body = r"\s+".join(re.escape(token) for token in quote.split())
    return re.compile(
        rf"(?<!\w)(?<!\w[.,/-]){body}(?:(?=-(?:ci|cü|cu|cı)\b)|(?![.,/-]?\w))"
    )


def _occurrences(quote: str, layout: AzureLayout) -> list[tuple[int, list[AzureWord]]]:
    """Every place the quote is on the page as Azure read it: (page index, its words)."""
    import unicodedata

    found = []
    matches = list(_pattern(quote).finditer(layout.content))
    if not matches:
        nfd_quote = unicodedata.normalize("NFD", quote)
        if nfd_quote != quote:
            matches = list(_pattern(nfd_quote).finditer(layout.content))
    for match in matches:
        page, words = -1, []
        for candidate in layout.pages:
            hits = [w for w in candidate.words if w.span.offset < match.end()
                    and w.span.offset + w.span.length > match.start()]
            if hits and page == -1:
                page = candidate.pageNumber - 1
            words.extend(hits)
        found.append((page, words))
    return found


_YEAR_FIRST = re.compile(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})")
_NUMERIC = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})")


def _iso_date(quote: str) -> str | None:
    """A full ISO date, or None (the caller keeps the quote as printed, doubtful). An
    all-numeric date is day-first unless its first part cannot be a month; an ambiguous
    one comes back day-first and `prove` never proves it (_ambiguous_date). Year-first
    is always year-month-day. A month name needs a four-digit year; any of space / - . ,
    separates its parts ("18/JAN/2025", "18-Jan-2025")."""
    text = quote.strip()
    if match := _YEAR_FIRST.fullmatch(text):
        year, month, day = (int(g) for g in match.groups())
    elif match := _NUMERIC.fullmatch(text):
        day, month, year = (int(g) for g in match.groups())
        if month > 12:
            day, month = month, day
    else:
        tokens = [fold(t) for t in re.split(r"[\s/.,-]+", text) if t]
        years = [int(t) for t in tokens if re.fullmatch(r"\d{4}", t)]
        days = [int(m[1]) for t in tokens if (m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?", t))]
        named = [_months()[t] for t in tokens if t in _months()]
        numeric = [t for t in tokens if any(c.isdigit() for c in t)]
        if not (len(years) == len(days) == len(named) == 1 and len(numeric) == 2
                and len(named[0]) == 1):
            return None
        year, month, day = years[0], next(iter(named[0])), days[0]
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _ambiguous_date(quote: str) -> bool:
    """08/11/2025 is 8 November or 11 August: both parts 12 or under and different."""
    match = _NUMERIC.fullmatch(quote.strip())
    if match is None:
        return False
    first, second = int(match[1]), int(match[2])
    return first <= 12 and second <= 12 and first != second


def _number(quote: str) -> str | None:
    """The one plain number in a score quote; None for none, two, or a non-ASCII digit."""
    found = _SCORE.findall(quote)
    if len(found) != 1 or any(c.isnumeric() and not c.isascii() for c in quote):
        return None
    return str(found[0]).replace(",", ".")


def _plausible(test: str, field: str, score: str) -> bool:
    ranges = _RANGES.get(test)
    if ranges is None:
        return True
    low, high, step = ranges[0 if field == "overall" else 1]
    number = Decimal(score)
    return low <= number <= high and (step is None or number % Decimal(step) == 0)


def _test(quote: str) -> tuple[str, str] | None:
    folded = fold(quote)
    if _NOT_A_LISTED_TEST.search(folded):
        return None
    for alias, name, language in _TEST_ALIASES:
        if re.search(rf"(?<!\w)(?:{alias})(?!\w)", folded):
            return name, language
    return None


#: Quote field -> (fact key, normaliser). A normaliser returning None drops the value,
#: unless _UNCLEAR names it: then the quote is kept as printed, doubtful, with that why.
_IDENTITY: Callable[[str], str | None] = lambda quote: " ".join(quote.split()) or None  # noqa: E731
_UNCLEAR: dict[Callable[[str], str | None], str] = {
    _iso_date: "date_unclear", _number: "low_confidence",
}
_DIPLOMA_ORIGINAL = {
    "institution_original": ("education.institution_original", _IDENTITY),
    "degree_original": ("education.degree_as_awarded", _IDENTITY),
    "diploma_number": ("education.diploma_number", _IDENTITY),
    "grade": ("education.grade_native", _IDENTITY),
}
_DIPLOMA_ENGLISH = {
    "institution_english": ("education.institution_english", _IDENTITY),
    "degree_english": ("education.degree_english", _IDENTITY),
}
#: The keys a diploma fills in any language: all a label disagreement may emit.
_Fields = dict[str, tuple[str, Callable[[str], str | None]]]
_DIPLOMA_EITHER: _Fields = {"graduation_date": ("education.end_date", _iso_date)}
_CERTIFICATE = {
    "test_variant": ("language.test_variant", _IDENTITY),
    "test_date": ("language.test_date", _iso_date),
    "certificate_number": ("language.certificate_number", _IDENTITY),
    "overall": ("language.test_score", _number),
    "listening": ("language.score_listening", _number),
    "reading": ("language.score_reading", _number),
    "writing": ("language.score_writing", _number),
    "speaking": ("language.score_speaking", _number),
    "cefr_level": ("language.cefr_level",
                   lambda q: (m.group(1) if (m := _CEFR.search(q)) else None)),
}


def _fields(kind: str, label: str | None) -> _Fields:
    """`label` None: the readers disagreed on it, so only the language-neutral keys."""
    if kind == "LANGUAGE_CERTIFICATE":
        return _CERTIFICATE
    if label is None:
        return _DIPLOMA_EITHER
    if label == "translation":
        return {**_DIPLOMA_ENGLISH, **_DIPLOMA_EITHER}
    if label == "bilingual":
        return {**_DIPLOMA_ORIGINAL, **_DIPLOMA_ENGLISH, **_DIPLOMA_EITHER}
    return {**_DIPLOMA_ORIGINAL, **_DIPLOMA_EITHER}


def _judge(first: str | None, second: str | None, layout: AzureLayout,
           visible: tuple[str, ...], threshold: float) -> tuple[str | None, bool, str]:
    """(quote to keep, proven, why) for one field across the two readers. Every place
    the quote is on Azure's page must be read sure, and a page with visible characters
    must print it at least as often as Azure found it there."""
    a = _nfc(" ".join((first or "").split())) or None
    b = _nfc(" ".join((second or "").split())) or None
    if a is None and b is None:
        return None, False, ""
    if a is None or a != b:
        return a or b, False, "readers_disagree"
    found = _occurrences(a, layout)
    if not found:
        return a, False, "not_on_page"
    if any(not words or any(w.confidence < threshold for w in words) for _, words in found):
        return a, False, "low_confidence"
    pattern = _pattern(a)
    for page in {page for page, _ in found}:
        seen = _nfc(visible[page]) if 0 <= page < len(visible) else ""
        if seen.strip() and len(pattern.findall(seen)) < sum(p == page for p, _ in found):
            return a, False, "text_layer_differs"
    return a, True, "readers_agree"


def prove(
    kind: str,
    answers: list[BaseModel],
    layout: AzureLayout,
    visible: tuple[str, ...],
    threshold: float,
    *,
    identifiers: Sequence[str] = (),
) -> list[ReadValue]:
    first, second = answers[0], answers[1]
    agreed = getattr(first, "document") == getattr(second, "document")
    values: list[ReadValue] = []

    def add(key: str, value: str, snippet: str, proven: bool, why: str) -> None:
        if not agreed:
            proven, why = False, "readers_disagree"
        values.append(ReadValue(key, value, snippet[:_SNIPPET], proven, why))

    test = None
    if kind == "LANGUAGE_CERTIFICATE":
        quote, proven, why = _judge(getattr(first, "test_name"), getattr(second, "test_name"),
                                    layout, visible, threshold)
        if quote is not None:
            known = _test(quote)
            if known is None:
                add("language.test_name", quote, quote, False, "unknown_test")
            else:
                test = known[0]
                add("language.test_name", known[0], quote, proven, why)
                if known[1]:
                    add("language.language", known[1], quote, proven, why)
    label = getattr(first, "document") if agreed else None
    for field, (key, normalise) in _fields(kind, label).items():
        quote, proven, why = _judge(getattr(first, field), getattr(second, field), layout,
                                    visible, threshold)
        if quote is None:
            continue
        value = normalise(quote)
        problem = None
        if value is None:
            problem = _UNCLEAR.get(normalise)
            if problem is None:
                continue
            value = quote
        elif normalise is _iso_date and _ambiguous_date(quote):
            problem = "ambiguous_date"
        elif field in _SCORES and test and not _plausible(test, field, value):
            problem = "implausible"
        if problem:
            proven, why = False, (problem if proven else why)
        add(key, value, quote, proven, why)
    name_identifiers = [
        item
        for item in identifiers
        if "@" not in item and not any(ch.isdigit() for ch in item) and len(item.split()) >= 2
    ]
    if name_identifiers and not owner_matches_document_text(
        layout.content, name_identifiers
    ):
        values = [
            ReadValue(v.key, v.value, v.snippet, False, "owner_mismatch", target=v.target)
            for v in values
        ]
    return values


def read_text_document(
    *,
    kind: str,
    document: object,
    content: bytes,
    identifiers: list[str],
    threshold: float,
    cap: int,
    billed: dict[str, int],
    flatten: Callable[..., ocr.Flattened] = ocr.flatten,
    analyze: Callable[..., AzureLayout] = analyze_layout,
    quotes: Callable[[str, str], Sequence[BaseModel]] = read_quotes,
) -> tuple[list[ReadValue], int]:
    """`billed["pages"]` is set the moment Azure answers, so every later failure still
    bills them (plan 1: every Azure answer counts toward the shared ceiling)."""
    flat = flatten(document, content, max_pages=cap)
    try:
        layout = analyze(flat.body(content))
    except OcrUnavailable:
        if settings.AZURE_DI_ENDPOINT and settings.AZURE_DI_KEY:
            # As plan 1's passport path: the call may have reached Azure and been billed
            # with no answer to count from. ponytail: charge the cap, the safe over-count.
            billed["pages"] = cap
        raise
    billed["pages"] = len(layout.pages)
    if not layout.content.strip():
        raise NotRead("unreadable")
    answers = list(quotes(kind, strip_identifiers(layout.content, identifiers)))
    if all(getattr(a, "document") == "other" for a in answers):
        raise NotRead("not_a_diploma" if kind == "DIPLOMA" else "not_a_certificate")
    return (
        prove(kind, answers, layout, flat.visible, threshold, identifiers=identifiers),
        len(layout.pages),
    )
