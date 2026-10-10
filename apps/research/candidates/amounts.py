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
from decimal import Decimal
from functools import cache

from apps.reference_data import ISO_4217_CODES
from apps.research.card_fields import _ascii_digits, _figure, evidence_rows
from apps.research.locale_names import fold

from . import Amount, _after_plain_word

_MARK = "[.,'’    ]"
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
    r"yaklaşık|təxminən|environ|etwa|körülbelül|kb\.|약|≈|~)\s*$", re.IGNORECASE)
_APPROX_AFTER = re.compile(r"^\s*(?:내외|정도|가량|前後|左右|程度)")
_CONVERSION = re.compile(
    r"\s*\(\s*(?:approx\.?|about|ca\.|≈|~|около|примерно|yaklaşık|təxminən)?\s*", re.IGNORECASE)


def _ascii(text: str) -> str:
    return _ascii_digits(text.replace("\u2009", " "))  # card_fields._figure knows no thin space


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


#: "2026-2027", "2026/27", "from 2020 to 2021": an intake span, the intake finder's, never a figure.
#: Not when a currency follows with no figure after it ("2000-2100 EUR per month" is a range).
_YEAR_SPAN = re.compile(
    r"(?<![\d€$£¥₼₺])(?:19|20)\d\d\s?(?:[-–—/]|to)\s?(?:(?:19|20)\d\d|\d\d)(?!\d)")


def _year(text: str) -> bool:
    return re.fullmatch(r"(?:19|20)\d\d", text) is not None


def _mask_years(line: str) -> str:
    cur = re.compile(rf"\s?(?:{_currency_alternation()})(?!\s?\d)", re.IGNORECASE)
    return _YEAR_SPAN.sub(
        lambda m: m.group(0) if cur.match(line, m.end()) else " " * len(m.group(0)), line)


def find_amounts(line: str) -> list[Amount]:
    line = _mask_years(line)
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
        # a year joins a range only with a year ("2000-2100 EUR"), never with "€12,000"
        if bare is not None and (
                (_year(bare.group("n")) and not 1900 <= (amount.low or 0) < 2200)
                or _after_plain_word(line, tail_start + bare.start())):
            bare = None
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
            if item is None or _year(item.group("n")):
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
