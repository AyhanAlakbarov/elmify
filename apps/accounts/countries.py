"""Every country, by name and by continent, for the profile's country pickers.

The continent comes from the country's first time zone in CLDR (`Europe/Berlin`
is Europe), with the island and ocean zones placed by hand. It only groups a
picker, so a debatable border (Cyprus, Türkiye, the Caucasus) is placed where a
student applying from the region would look for it.
"""

from __future__ import annotations

from functools import cache

from babel.core import get_global

from apps.documents.templatetags.cv_countries import _NAMES as COUNTRY_NAMES
from apps.reference_data import ISO_3166_ALPHA2_CODES

CONTINENTS = ("Europe", "Asia", "Americas", "Africa", "Oceania")

_ZONE_PREFIX = {
    "Europe": "Europe",
    "Asia": "Asia",
    "America": "Americas",
    "Africa": "Africa",
    "Pacific": "Oceania",
    "Australia": "Oceania",
    "Atlantic": "Europe",
    "Indian": "Africa",
    "Arctic": "Europe",
}
_BY_HAND = {
    # Atlantic and Indian Ocean zones that are not Europe / Africa.
    "BM": "Americas", "FK": "Americas", "GS": "Americas", "CV": "Africa", "SH": "Africa",
    "MV": "Asia", "IO": "Asia", "CX": "Oceania", "CC": "Oceania",
    # Where a student from the region looks for them.
    "CY": "Europe", "TR": "Europe", "GE": "Asia", "AM": "Asia", "AZ": "Asia",
    "XK": "Europe",
    # First CLDR zone is an outlying island or enclave.
    "ES": "Europe", "CL": "Americas", "EC": "Americas",
}
#: Not places anyone studies or lives: uninhabited or research territories.
_LEFT_OUT = frozenset({"AQ", "BV", "HM", "TF", "UM", "GS"})


def _continent(code: str) -> str | None:
    if code in _BY_HAND:
        return _BY_HAND[code]
    zones = get_global("territory_zones").get(code) or []
    return _ZONE_PREFIX.get(zones[0].split("/")[0]) if zones else None


@cache
def all_countries() -> tuple[tuple[str, str], ...]:
    """(code, English name) for every country a student can pick, by name."""
    return tuple(
        sorted(
            (
                (code, name)
                for code, name in COUNTRY_NAMES.items()
                if code in ISO_3166_ALPHA2_CODES and code not in _LEFT_OUT
            ),
            key=lambda pair: pair[1],
        )
    )


@cache
def countries_by_continent() -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """(continent, ((code, name), ...)) in CONTINENTS order, each sorted by name."""
    groups: dict[str, list[tuple[str, str]]] = {name: [] for name in CONTINENTS}
    for code, name in all_countries():
        continent = _continent(code)
        if continent in groups:
            groups[continent].append((code, name))
    return tuple((name, tuple(groups[name])) for name in CONTINENTS if groups[name])
