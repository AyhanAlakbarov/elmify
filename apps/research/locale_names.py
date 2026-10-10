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
) -> tuple[dict[str, object], tuple[tuple[tuple[str, ...], str, str, object], ...]]:
    exact: dict[str, object] = {}
    for name, _, value in forms:
        exact.setdefault(name, value)
    stems = [
        (tuple(_stem(word, lang) for word in name.split()), name, lang, value)
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
    for stem, name, lang, value in stems:
        # the startswith test is a cheap prefilter; the fullmatch applies the same ending rule
        # `inflected` does, so "maliyyə" is not Mali and "indiana" is not India
        if (
            len(words) == len(stem)
            and all(w.startswith(s) for w, s in zip(words, stem))
            and re.fullmatch(_form(name, lang), folded)
        ):
            return cast(V, value)
    return None
