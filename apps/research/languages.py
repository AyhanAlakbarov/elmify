"""The language loop -- which languages a sweep pass writes its angles in.

Decision 38 (2026-09-24): every official language of the country from
Wikidata P37, plus English, never one language per country. `STEERING`'s single
`language` column was right for Türkiye and wrong for most of the corridor: a
Kazakh funder's page is more often Russian than Kazakh, and Uzbekistan,
Belgium, Switzerland, India and Pakistan publish in several.

A diaspora pass is the exception, and it is not a special case of this rule
but a different key (decision 37): the pass is `(host country, home
language)`, so its languages are that home language, then English -- an
Azerbaijani student association in Germany writes in Azerbaijani, and a
German-language angle would never find it. Both legs' angles carry the home
language in their key, so the English set of one home language's pass is
never another's.

The per-language yield (tally.py) decides which languages keep running;
this module only says which ones start.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from . import wikidata

logger = logging.getLogger(__name__)

_ISO2 = re.compile(r"^[A-Z]{2}$")
#: The same shape vocabulary.py's `_LANG` checks: codes come back from
#: Wikidata (P424) and must not be trusted further than that.
_LANG = re.compile(r"^[a-z]{2,3}(-[a-z0-9]+)*$")
#: SweepAngle.language / SweepAngle.home_language / SweepRun.home_language
#: are all CharField(max_length=12) -- `_LANG` alone does not bound length
#: (a BCP-47 tag can carry arbitrarily many subtags), so a code that
#: matches it can still be too long for the column.
MAX_LANGUAGE_LEN = 12

#: P297 is the ISO 3166-1 alpha-2 code, P37 official language, P424 the
#: language's Wikimedia code -- the same code vocabulary.py's kind words are
#: keyed on, so the loop and the vocabulary must agree on which alphabet a
#: language is. Only current countries: dissolved ones (a P576 claim) do not
#: run sweeps. The country code is validated against `_ISO2` before it is
#: formatted in, so this string cannot be steered.
_QUERY = """SELECT DISTINCT ?code WHERE {{
  ?country wdt:P297 "{code}" ; wdt:P31 wd:Q6256 .
  FILTER NOT EXISTS {{ ?country wdt:P576 [] }}
  ?country wdt:P37 ?language .
  ?language wdt:P424 ?code .
}}"""


class CountryLanguages(Protocol):
    def languages(self, country_code: str) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class WikidataLanguages:
    sparql: Callable[[str], list[dict[str, str]]] = field(default=wikidata.sparql)

    def languages(self, country_code: str) -> tuple[str, ...]:
        code = country_code.upper()
        if not _ISO2.match(code):
            raise ValueError(f"not an ISO 3166-1 alpha-2 code: {country_code!r}")
        rows = self.sparql(_QUERY.format(code=code))
        codes: set[str] = set()
        for row in rows:
            raw = row.get("code", "").lower()
            if _LANG.match(raw):
                codes.add(raw)
            else:
                logger.warning("not a language code from Wikidata for %s: %r", code, raw)
        # Sorted: SPARQL guarantees no order, and a pass's batch order must be
        # reproducible from its languages column.
        return tuple(sorted(codes))


def home_language(family: str, codes: Sequence[str]) -> str:
    """The one home language a diaspora pass is keyed on; "" for any other
    family, which has none."""
    codes = [code.lower() for code in codes]
    if long := [code for code in codes if len(code) > MAX_LANGUAGE_LEN]:
        raise ValueError(f"language code longer than {MAX_LANGUAGE_LEN} characters: {long}")
    if bad := [code for code in codes if not _LANG.match(code)]:
        raise ValueError(f"not a language code: {bad}")
    if family != "AFFINITY_OR_DIASPORA":
        if codes:
            raise ValueError(f"a home language is for AFFINITY_OR_DIASPORA only, not {family}")
        return ""
    if len(codes) != 1:
        raise ValueError(
            "a diaspora pass is keyed (host country, home language) -- name exactly one home "
            f"language, got {codes or 'none'}"
        )
    return codes[0]


def pass_languages(
    country_code: str,
    family: str,
    *,
    source: CountryLanguages,
    home_language: str = "",
) -> tuple[str, ...]:
    """The languages a pass runs in: see `ordered_languages`."""
    if family == "AFFINITY_OR_DIASPORA":
        if not home_language:
            raise ValueError(
                "a diaspora pass is keyed (host country, home language) -- name the home language"
            )
        return ordered_languages((home_language,))
    local = source.languages(country_code)
    if not local:
        # Visibly incomplete, never silently English: a country Wikidata
        # gives no official language for is a data gap, logged.
        logger.warning("no official language for %s in Wikidata; English only", country_code)
    return ordered_languages(local)


def ordered_languages(languages: Sequence[str]) -> tuple[str, ...]:
    """Local first, English last, no repeats."""
    local = [language.lower() for language in languages]
    return (*dict.fromkeys(language for language in local if language != "en"), "en")
