"""The language loop -- which languages a sweep pass writes its angles in.

Decision 38 (2026-09-24): every official language of the country, plus
English, never one language per country. Since 2026-10-13 the official
languages come from Unicode CLDR (through Babel, already a dependency), not
Wikidata P37: Wikidata marks English as a *deprecated* official language of
the United States and lists Hawaiian, Samoan, Chamorro and Carolinian instead,
so a US pass ran four dead languages before English. CLDR records English as the
US's de-facto official language and those as regional. Regional-only languages
are left out, and so is any official language spoken by under
`_MIN_SPEAKER_SHARE` of residents (Māori in New Zealand, Tamil in Singapore).
Known cost, accepted: Swiss German ("gsw") is de-facto official in CLDR and
runs a pass of its own, though Swiss funders publish in standard German; the
per-language tally drops it rather than a hand-kept exception list.
`STEERING`'s single
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
from collections.abc import Sequence
from dataclasses import dataclass

from .vocabulary import _ISO2 as _ISO2
from .vocabulary import _LANG as _LANG

logger = logging.getLogger(__name__)

#: SweepAngle.language / SweepAngle.home_language / SweepRun.home_language
#: are all CharField(max_length=12) -- `_LANG` alone does not bound length
#: (a BCP-47 tag can carry arbitrarily many subtags), so a code that
#: matches it can still be too long for the column.
MAX_LANGUAGE_LEN = 12

#: CLDR's share of residents who speak the language. Below it a language is
#: left to the English leg (Māori in New Zealand 2.8%, Tamil in Singapore 2.1%).
#: ponytail: one global cut; the per-language tally (tally.py) is what drops a
#: language above it that finds nothing.
_MIN_SPEAKER_SHARE = 5.0


@dataclass(frozen=True)
class CldrLanguages:
    """Official and de-facto official languages, most-spoken first, from CLDR.

    Codes are reduced to the language (az_Cyrl -> az, zh_Hant -> zh), and the
    macrolanguage "no" is dropped beside Bokmål, so no language runs twice.
    """

    def languages(self, country_code: str) -> tuple[str, ...]:
        from babel.languages import get_official_languages, get_territory_language_info

        code = country_code.upper()
        if not _ISO2.match(code):
            raise ValueError(f"not an ISO 3166-1 alpha-2 code: {country_code!r}")
        share = get_territory_language_info(code)
        codes: list[str] = []
        for raw in get_official_languages(code, regional=False, de_facto=True):
            if float(share.get(raw, {}).get("population_percent") or 0.0) < _MIN_SPEAKER_SHARE:
                continue
            language = raw.split("_")[0].lower()
            if _LANG.match(language) and language not in codes:
                codes.append(language)
        if "no" in codes and "nb" in codes:
            codes.remove("no")
        return tuple(codes)


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
    source: CldrLanguages,
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
        # Visibly incomplete, never silently English: a country CLDR gives
        # no official language for is a data gap, logged.
        logger.warning("no official language for %s in CLDR; English only", country_code)
    return ordered_languages(local)


def ordered_languages(languages: Sequence[str]) -> tuple[str, ...]:
    """Local first, English last, no repeats."""
    local = [language.lower() for language in languages]
    return (*dict.fromkeys(language for language in local if language != "en"), "en")
