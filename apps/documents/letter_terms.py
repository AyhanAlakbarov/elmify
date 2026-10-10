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
_WORD = re.compile(r"\w+")
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


#: A separator INSIDE a number, between a digit and a group of exactly three.
_GROUPED = re.compile(r"(?<=\d)[,\u00a0\u202f\u2009](?=\d{3}(?!\d))")


def normalise_numerals(text: str) -> str:
    """Western digits for Arabic-Indic, fullwidth and spelled-out CJK counts.

    Used only to check a number the judge returned really is in the sentence
    (derive.py) -- never to rewrite a stored quote, which stays verbatim.

    Digit-group separators go too, and ONLY where the group is exactly three
    digits. "no more than 1,500 words" otherwise reads as the two numbers 1 and
    500: the true cap fails to verify and is dropped, while a reading that
    misread it as 500 verifies and stands -- a smaller cap than the page
    stated, which is the direction that ships a rejected letter (PR review,
    2026-09-22). The three-digit rule is what keeps a German decimal comma out
    of it: "1,5 Seiten" must not become 15.
    """
    text = _GROUPED.sub("", text)
    for cjk, western in _CJK_NUMERALS.items():
        text = text.replace(cjk, western)
    return "".join(
        str(unicodedata.decimal(char)) if unicodedata.category(char) == "Nd" else char
        for char in text
    )


#: Small counts as words, in the seeded languages whose limits are written in a
#: Latin or Cyrillic script. Measured live 2026-09-25: "approximately one A4
#: page" (ETH), "maximal zwei DIN-A4-Seiten" (TUM) and "sur une ou deux pages"
#: (Eiffel) all lost their cap, because a number not printed as digits failed
#: _number_is_on_the_page. Only 1-10: a limit written as a word is a page count
#: in practice. Turkish "on" (10) is left out -- it is an English word too.
_NUMBER_WORDS: dict[str, int] = {
    word: value
    for value, words in {
        1: "one ein eine einer einen eins un une uno una um uma een één bir один одна одной одну",
        2: "two zwei deux dos due dois duas twee iki два две двух",
        3: "three drei trois tres tre três drie üç три трёх трех",
        4: "four vier quatre cuatro quattro quatro dört четыре",
        5: "five fünf cinq cinco cinque vijf beş пять",
        6: "six sechs seis sei zes altı шесть",
        7: "seven sieben sept siete sette sete zeven yedi семь",
        8: "eight acht huit ocho otto oito sekiz восемь",
        9: "nine neun neuf nueve nove negen dokuz девять",
        10: "ten zehn dix diez dieci dez tien десять",
    }.items()
    for word in words.split()
}
#: A number word counts only this many tokens before a length unit ("zwei
#: DIN-A4-Seiten" is three), so "one of the documents" verifies nothing.
_WORD_WINDOW = 3
_TOKEN = re.compile(r"\w+")
#: A space-grouped thousand ("1 000 mots"). Not in _GROUPED: joining is only
#: ever ADDED to the figures on a line, never substituted for them, because a
#: plain space also separates two real numbers ("Part 2 500 words").
_SPACE_GROUPED = re.compile(r"(?<!\d)(\d{1,3})(?: (\d{3}))+(?!\d)")


def _units() -> frozenset[str]:
    return frozenset(unit.casefold() for row in TERMS.values() for unit in row.unit)


def numbers_on_line(text: str) -> set[int]:
    """Every count a sentence states, however it is written.

    The whole-token digit rule is unchanged and always applies; the other two
    readings are added to it, never substituted: a space-grouped thousand joined
    ("1 000" is 1000) and a small number word standing just before a length unit
    ("one A4 page" is 1). Used only to VERIFY a number a reading returned -- the
    guard in derive._number_is_on_the_page -- so each addition can only let a
    printed limit through, never make one up.
    """
    normalised = normalise_numerals(text)
    found = {int(token) for token in re.findall(r"\d+", normalised)}
    for match in _SPACE_GROUPED.finditer(normalised):
        found.add(int(match.group(0).replace(" ", "")))
    tokens = [token.casefold() for token in _TOKEN.findall(normalised)]
    units = _units()
    for index, token in enumerate(tokens):
        value = _NUMBER_WORDS.get(token)
        if value is not None and any(
            later in units for later in tokens[index + 1 : index + 1 + _WORD_WINDOW]
        ):
            found.add(value)
    return found


@dataclass(frozen=True)
class Figure:
    """One count a sentence states, with the unit word printed after it.

    `number` is an int unless the page wrote a decimal ("1,5 Seiten"). `unit` is
    the vocabulary's own unit word, casefolded, found within `_WORD_WINDOW`
    tokens after the figure -- or "" when none is, which is what a year, a date
    or a count of documents looks like. `span` indexes `normalise_numerals(text)`,
    never the raw sentence: the separators it strips move every offset after them.
    """

    number: int | float
    unit: str
    span: tuple[int, int]


#: A figure written in digits. A dot before exactly three digits is a thousands
#: group ("2.800 Zeichen" is 2800 -- normalise_numerals has already joined
#: "2,800"); one or two digits after a dot or comma are a decimal ("1,5 Seiten").
#: Never preceded by a Latin OR CYRILLIC OR GREEK letter or a digit, so the 4 in
#: "A4" -- or in Cyrillic "А4" -- is not a figure (fix round 1, finding 5); `\b`
#: would also refuse "不超过800字", whose neighbour is a word character, so a
#: CJK neighbour is deliberately left out of this class.
_FIGURE = re.compile(
    r"(?<![A-Za-z\d\u0370-\u03ff\u0400-\u04ff])(\d+(?:\.\d{3})*)(?:[.,](\d{1,2}))?(?!\d)"
)

#: A day.month.year date ("15.10.2026"), never a figure: fix round 1, finding
#: 4. Without this, "15.10" reads as the decimal 15.1 (one or two digits after
#: a dot already means a decimal, above) and "2026" reads as a bare year-shaped
#: figure beside it -- two numbers nobody printed as a length, from one date.
_DATE = re.compile(r"(?<!\d)\d{1,2}\.\d{1,2}\.\d{2,4}(?!\d)")


def _within(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(outer[0] <= span[0] and span[1] <= outer[1] for outer in spans)


def _prefix_units() -> tuple[str, ...]:
    """Units in a script written without spaces: they run into the next word
    ("字以内"), so they match as a prefix. Longest first, so "文字" wins over "字"."""
    spaceless = (
        unit
        for unit in _units()
        if _HAN.search(unit) or _HANGUL.search(unit) or _KANA.search(unit)
    )
    return tuple(sorted(spaceless, key=len, reverse=True))


_PREFIX_UNITS = _prefix_units()


#: Joins two figures of one range or list ("300-500 words", "300 to 500
#: words"). Only a gap made of nothing but one of these -- a dash, or the
#: immediately preceding token being one of these words -- lets `_unit_after`
#: read past an intervening NUMBER to reach a unit beyond it (fix round 1,
#: finding 4). Any other gap before a number means that number is a
#: DIFFERENT figure's own, whose unit is its own to find: "In 2027 500 words
#: max" must not give 2027 the 500's unit.
_RANGE_DASH = re.compile(r"^\s*[-\u2010-\u2015]\s*$")
_RANGE_WORDS = frozenset({"to", "and", "bis", "à", "до"})


def _unit_after(rest: str) -> str:
    """The first unit word within `_WORD_WINDOW` tokens of `rest`, or "".

    A Latin or Cyrillic unit must be the whole token -- "wordt" is Dutch for
    "is", not a word count -- and a spaceless-script unit may begin one. A
    NUMBER token stops the scan unless it is joined to the figure being
    looked up by a range or list separator (`_RANGE_DASH` / `_RANGE_WORDS`).
    """
    units = _units()
    previous_end = 0
    previous_token = ""  # nosec B105 -- a regex token, not a credential
    checked = 0
    for match in _TOKEN.finditer(rest):
        if checked >= _WORD_WINDOW:
            break
        token = str(match.group())  # finditer is Any to mypy
        folded = token.casefold()
        if folded in units:
            return folded
        for unit in _PREFIX_UNITS:
            if folded.startswith(unit):
                return unit
        if token.isdigit():
            gap = rest[previous_end : match.start()]
            if not (_RANGE_DASH.match(gap) or previous_token in _RANGE_WORDS):
                return ""
        previous_token = folded
        previous_end = match.end()
        checked += 1
    return ""


def _figure_value(whole: str, fraction: str | None) -> int | float:
    number = int(whole.replace(".", ""))
    return float(f"{number}.{fraction}") if fraction else number


def figures_on_line(text: str) -> tuple[Figure, ...]:
    """Every count the sentence states, each with the unit printed after it.

    The grammar's candidates for a length (addendum 2026-09-26 §6.1): code finds
    them, one Choice per figure says whether it is a cap, a floor, an
    approximation or no limit at all, and the number a rule carries is copied
    from here -- never from a model. So this is where "a value the page did not
    print cannot be chosen" is enforced.

    The three readings `numbers_on_line` verifies with, now returned as figures:
    - digits, as a whole figure (a thousands group joined, a decimal kept),
      offered with or without a unit -- "2027" must still be asked about and
      answered `not_a_limit`; dropping it here would be code deciding what
      only the sentence can say;
    - a space-grouped thousand joined ("1 000 mots"), offered INSTEAD OF the
      plain digits it joins: a digit run wholly inside a joined thousand's
      span is never offered again as its own figure (fix round 1, finding 1).
      Plausibility bands do not reliably catch a stray part on their own --
      "maximal 1 500 mots" splits into a joined 1500 and a stray 500, and 500
      is a perfectly plausible word count, unlike the stray 1 in "1 000
      mots" that the plausibility band happened to catch before this fix;
    - a number word only within `_WORD_WINDOW` tokens before a unit, so "one of
      the documents" is no figure at all.
    A zero is never a length and is not offered, and neither is a digit run
    that is part of a day.month.year date (`_DATE`, fix round 1, finding 4):
    "15.10.2026" is a date, not the decimal 15.1 beside the bare figure 2026.
    Ordered by position, a joined thousand before the part it starts with.
    """
    normalised = normalise_numerals(text)
    excluded = [m.span() for m in _SPACE_GROUPED.finditer(normalised)]
    excluded += [m.span() for m in _DATE.finditer(normalised)]
    found: list[Figure] = []
    for match in _FIGURE.finditer(normalised):
        number = _figure_value(match.group(1), match.group(2))
        if number and not _within(match.span(), excluded):
            found.append(Figure(number, _unit_after(normalised[match.end() :]), match.span()))
    for match in _SPACE_GROUPED.finditer(normalised):
        found.append(
            Figure(
                int(match.group(0).replace(" ", "")),
                _unit_after(normalised[match.end() :]),
                match.span(),
            )
        )
    for match in _TOKEN.finditer(normalised):
        value = _NUMBER_WORDS.get(match.group().casefold())
        if value is not None and not _within(match.span(), excluded):
            unit = _unit_after(normalised[match.end() :])
            if unit:
                found.append(Figure(value, unit, match.span()))
    return tuple(sorted(found, key=lambda figure: (figure.span[0], -figure.span[1])))


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
        logger.warning(
            "page declares an unseeded language (%d chars, starts %r)",
            len(declared),
            declared[:32],
        )
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
