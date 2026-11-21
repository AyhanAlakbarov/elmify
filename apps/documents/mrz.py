"""The machine-readable strip of a passport (TD3) or an ID card (TD1).

ICAO Doc 9303 Parts 3-5. Standard library plus the country names this repo already
carries: about thirty lines of rules, not worth a dependency. The strip proves a
value only through its own check digit (spec 2026-10-12 §5.2): the document number,
the date of birth and the expiry each have one, and a composite digit covers them
together. Sex and nationality sit outside every digit, so they are proven only by
agreeing with the printed page -- never by the strip alone.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import cache

from babel.core import get_global

from .templatetags.cv_countries import country_name

_WEIGHTS = (7, 3, 1)
_STRIP_CHARS = re.compile(r"^[A-Z0-9<]+$")

#: ICAO codes ISO 3166 does not carry (Doc 9303 Part 3, 5): Germany's one-letter
#: code, the five British nationality classes, and the UN's code for Kosovo.
_ICAO_ONLY = {"D": "DE", "GBD": "GB", "GBN": "GB", "GBO": "GB", "GBP": "GB", "GBS": "GB",
              "UNK": "XK"}
#: Stateless (XXA), refugee (XXB, XXC) and unspecified (XXX): the field names no
#: citizenship, so nothing is ever proven from it.
NO_CITIZENSHIP = frozenset({"XXA", "XXB", "XXC", "XXX"})

#: Letters whose strip form differs between issuers, each with every form an
#: issuer uses (Doc 9303 Part 3, 6, plus national practice). Anything else is
#: folded by Unicode decomposition. Entries come from specimens and the consented
#: set (spec §9), never from guesswork. names_agree drops punctuation before comparing letters.
_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "Ə": ("A", "E"),
    "Ä": ("AE", "A"),
    "Ö": ("OE", "O"),
    "Ü": ("UE", "U"),
    "Å": ("AA", "A"),
    "Æ": ("AE",),
    "Ø": ("OE", "O"),
    "ß": ("SS",),
    "Ð": ("D", "DJ"),
    "Đ": ("DJ", "D"),
    "Þ": ("TH",),
    "Ł": ("L",),
    "Œ": ("OE",),
}


def check_digit(field: str) -> str:
    """The 7-3-1 weighted check digit of a strip field (Doc 9303 Part 3, 4.9)."""
    total = 0
    for index, char in enumerate(field):
        if char.isdigit():
            value = int(char)
        elif "A" <= char <= "Z":
            value = ord(char) - 55
        elif char == "<":
            value = 0
        else:
            raise ValueError("not a strip character")
        total += value * _WEIGHTS[index % 3]
    return str(total % 10)


@dataclass(frozen=True)
class Strip:
    format: str
    document_code: str
    issuing_state: str
    surname: str
    given_names: str
    #: None when the field's own check digit fails (or is "<", a continued number).
    number: str | None
    nationality: str
    birth: str | None
    sex: str
    expiry: str | None
    composite_ok: bool
    #: True when the name field is full (does not end with "<").
    names_truncated: bool


def _checked(field: str, digit: str, *, date: bool = False) -> str | None:
    """The field when its own digit holds. Only a date may not contain "<"; a
    number is padded with it (Doc 9303), and "<" in the digit place means the
    number continues elsewhere."""
    if digit == "<" or (date and "<" in field):
        return None
    return field if check_digit(field) == digit else None


def _names(field: str) -> tuple[str, str]:
    surname, _, given = field.partition("<<")
    return " ".join(surname.split("<")).strip(), " ".join(given.split("<")).strip()


def parse(raw: str) -> Strip | None:
    """A strip from OCR text, or None when it is not one. Spaces and case are an
    OCR's; a wrong line length or a stray character is not a strip."""
    if not isinstance(raw, str):
        return None
    lines = [line.replace(" ", "").upper() for line in raw.splitlines() if line.strip()]
    if not all(_STRIP_CHARS.match(line) for line in lines):
        return None
    shapes: dict[int, tuple[int, Callable[..., Strip | None]]] = {2: (44, _td3), 3: (30, _td1)}
    shape = shapes.get(len(lines))
    if shape is None or not all(len(line) == shape[0] for line in lines):
        return None
    result = shape[1](*lines)
    if result and result.document_code and result.document_code[0] in "PIAC":
        return result
    return None


def _td3(first: str, second: str) -> Strip:
    name_field = first[5:44]
    surname, given = _names(name_field)
    composite = second[0:10] + second[13:20] + second[21:43]
    return Strip(
        format="TD3",
        document_code=first[0:2].replace("<", ""),
        issuing_state=first[2:5],
        surname=surname,
        given_names=given,
        number=(_checked(second[0:9], second[9]) or "").replace("<", "") or None,
        nationality=second[10:13],
        birth=_checked(second[13:19], second[19], date=True),
        sex=second[20],
        expiry=_checked(second[21:27], second[27], date=True),
        composite_ok=check_digit(composite) == second[43],
        names_truncated=not name_field.endswith("<"),
    )


def _td1(first: str, second: str, third: str) -> Strip:
    surname, given = _names(third)
    composite = first[5:30] + second[0:7] + second[8:15] + second[18:29]
    return Strip(
        format="TD1",
        document_code=first[0:2].replace("<", ""),
        issuing_state=first[2:5],
        surname=surname,
        given_names=given,
        # ponytail: a number longer than 9 characters continues in the optional
        # field with "<" in the check position; it stays unproven rather than
        # parsed. Add the continuation rule if a real document needs it.
        number=(_checked(first[5:14], first[14]) or "").replace("<", "") or None,
        nationality=second[15:18],
        birth=_checked(second[0:6], second[6], date=True),
        sex=second[7],
        expiry=_checked(second[8:14], second[14], date=True),
        composite_ok=check_digit(composite) == second[29],
        names_truncated=not third.endswith("<"),
    )


def printed_agrees(yymmdd: str, printed: date) -> bool:
    return printed.strftime("%y%m%d") == yymmdd


def date_from_strip(yymmdd: str, *, birth: bool, today: date) -> date | None:
    """The strip's date with its century resolved: a birth date is never in the
    future; an expiry is in this century. Used only for a doubtful value, when no
    printed date exists to agree with."""
    try:
        year, month, day = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
        resolved = date(2000 + year, month, day)
        if birth and resolved > today:
            resolved = resolved.replace(year=resolved.year - 100)
    except ValueError:
        return None
    return resolved


def country_name_for(code: str) -> str | None:
    """English country name for an ICAO code, or None for anything ISO does not name."""
    code = code.replace("<", "").upper()
    if code in NO_CITIZENSHIP:
        return None
    alpha2 = _ICAO_ONLY.get(code)
    if alpha2 is None:
        aliases = get_global("territory_aliases").get(code) or []
        alpha2 = aliases[0] if len(aliases) == 1 else None
    if alpha2 is None:
        return None
    name = country_name(alpha2)
    return name if name != alpha2 else None


def _letter_options(char: str) -> tuple[str, ...]:
    if char in _ALTERNATIVES:
        return _ALTERNATIVES[char]
    base = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
    return (base,) if len(base) == 1 and "A" <= base <= "Z" else (" ",)


def _single_form(printed: str) -> str:
    """Convert printed text to single strip form using each letter's first option."""
    result = []
    for char in printed.upper():
        options = _letter_options(char)
        result.append(options[0])
    return " ".join("".join(result).split())


_PUNCTUATION = re.compile("['‘’`.,ʻʼ]")
_SEPARATORS = re.compile(r"[\s\-–—]+")


def _matches_with_truncation(printed: str, wanted: str, *, exact: bool = False) -> bool:
    """Letter-by-letter matching. ICAO drops punctuation (apostrophes, dots,
    commas); a space or hyphen run is one strip space. exact=False accepts a
    strip name that is a prefix of the printed form (a truncated name field)."""
    wanted_normalized = " ".join(wanted.upper().split())
    printed_upper = _SEPARATORS.sub(" ", _PUNCTUATION.sub("", printed.upper())).strip()

    @cache
    def match(p_idx: int, w_idx: int) -> bool:
        if w_idx == len(wanted_normalized):
            return p_idx == len(printed_upper) if exact else True
        if p_idx == len(printed_upper):
            return False
        return any(
            wanted_normalized.startswith(option, w_idx) and match(p_idx + 1, w_idx + len(option))
            for option in _letter_options(printed_upper[p_idx])
        )

    return match(0, 0)


def names_agree(printed: str, strip_name: str, *, truncated: bool = False) -> bool:
    """The printed name agrees with the strip name.

    When truncated=True, some strip form of printed must START WITH strip_name
    (the strip truncates long names, so prefix is agreement).
    When truncated=False, some form must EQUAL the strip name exactly.
    """
    wanted = " ".join(strip_name.upper().split())
    if not wanted:
        return False
    return _matches_with_truncation(printed, wanted, exact=not truncated)


def fold_tokens(text: str) -> set[str]:
    """Name words in one fixed spelling (each letter's first strip form), for
    comparing a CV's name with a passport's."""
    form = _single_form(text)
    return set(form.split()) if form else set()


_DIGRAPHS = (("KH", "X"), ("SH", "S"), ("CH", "C"), ("ZH", "J"), ("GH", "G"), ("Q", "G"),
             ("J", "C"))  # last: Azerbaijani C is English J
_MAX_KEYS = 256
_CYRILLIC_SCHWA = {"\u04d8": "Ə", "\u04d9": "Ə"}


def _keys(word: str) -> list[str]:
    """Every spelling of a name word, the all-first-options spelling first. Per
    letter: its ICAO strip forms, plus its base letter; Ə (and Cyrillic Ә) is A
    or E; any other non-Latin letter stays itself, so it never equals a Latin
    one; non-letters and modifier letters are dropped. Past _MAX_KEYS spellings each letter
    takes its first option only, so a long name fails closed instead of
    expanding exponentially."""
    keys = [""]
    for char in word.upper():
        char = _CYRILLIC_SCHWA.get(char, char)
        category = unicodedata.category(char)
        if not category.startswith("L") or category == "Lm":
            continue  # punctuation, marks, and modifier letters such as Uzbek ʻ
        base = "".join(c for c in unicodedata.normalize("NFKD", char)
                       if not unicodedata.combining(c))
        options = _ALTERNATIVES.get(char, ())
        if len(base) == 1 and "A" <= base <= "Z" and base not in options:
            options += (base,)
        options = options or (char,)  # a non-Latin letter stays itself
        if len(keys) * len(options) > _MAX_KEYS:
            options = options[:1]
        keys = [key + option for key in keys for option in options]
    if keys == [""]:
        return []
    for old, new in _DIGRAPHS:
        keys = [key.replace(old, new) for key in keys]
    return list(dict.fromkeys(keys))


def name_keys(word: str) -> set[str]:
    return set(_keys(word))


def same_given_name(a: str, b: str) -> bool:
    """Two given names equal up to spelling: no fuzzy ratio, because Kamil and
    Kamilə (brother and sister) must differ, and plain A and E stay distinct
    (Emil is not Amil). Only Ə is either."""
    return bool(name_keys(a) & name_keys(b))


def same_name_token(a: str, b: str) -> bool:
    """Two surname words for ownership: equal up to spelling, or (both at least
    three letters, lengths within one) 80% alike, for Mamedov/Mammadov."""
    keys_a, keys_b = _keys(a), _keys(b)
    if set(keys_a) & set(keys_b):
        return True
    if not keys_a or not keys_b or min(map(len, keys_a + keys_b)) < 3:
        return False
    first_a, first_b = keys_a[0], keys_b[0]
    if (
        len(first_a) >= 5
        and len(first_b) >= 5
        and first_a.replace("E", "A") == first_b.replace("E", "A")
    ):
        return True
    return (abs(len(first_a) - len(first_b)) <= 1
            and difflib.SequenceMatcher(None, first_a, first_b).ratio() >= 0.8)
