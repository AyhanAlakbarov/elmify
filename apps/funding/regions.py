"""Named country sets, as data with a source each.

A funder writes "citizens of Western Balkan countries", not a list of six codes.
Expanding that is a lookup, never a model's guess: a region this table does not
know makes its condition UNDECIDABLE, which a human then resolves by adding a
row here with the URL that defines the membership.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    name: str
    countries: tuple[str, ...]
    #: Where the membership is defined. A region without one is a guess.
    source: str


REGIONS: dict[str, Region] = {
    "EU": Region(
        "European Union",
        (
            "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR",
            "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        ),
        "https://european-union.europa.eu/principles-countries-history/eu-countries_en",
    ),
    "EEA": Region(
        "European Economic Area",
        (
            "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR",
            "HU", "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MT", "NL", "NO", "PL", "PT",
            "RO", "SE", "SI", "SK",
        ),
        "https://www.efta.int/eea",
    ),
    "WESTERN_BALKANS": Region(
        "Western Balkans",
        ("AL", "BA", "ME", "MK", "RS", "XK"),
        "https://neighbourhood-enlargement.ec.europa.eu/enlargement-policy/western-balkans_en",
    ),
    "EASTERN_PARTNERSHIP": Region(
        "Eastern Partnership",
        ("AM", "AZ", "GE", "MD", "UA"),
        "https://www.eeas.europa.eu/eeas/eastern-partnership_en",
    ),
    "ASEAN": Region(
        "Association of Southeast Asian Nations",
        ("BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "VN"),
        "https://asean.org/member-states/",
    ),
    "AFRICAN_UNION": Region(
        "African Union",
        (
            "AO", "BF", "BI", "BJ", "BW", "CD", "CF", "CG", "CI", "CM", "CV", "DJ", "DZ",
            "EG", "EH", "ER", "ET", "GA", "GH", "GM", "GN", "GQ", "GW", "KE", "KM", "LR",
            "LS", "LY", "MA", "MG", "ML", "MR", "MU", "MW", "MZ", "NA", "NE", "NG", "RW",
            "SC", "SD", "SL", "SN", "SO", "SS", "ST", "SZ", "TD", "TG", "TN", "TZ", "UG",
            "ZA", "ZM", "ZW",
        ),
        "https://au.int/en/member_states/countryprofiles2",
    ),
    "COMMONWEALTH": Region(
        "Commonwealth of Nations",
        (
            "AG", "AU", "BB", "BD", "BN", "BS", "BW", "BZ", "CA", "CM", "CY", "DM", "FJ",
            "GA", "GB", "GD", "GH", "GM", "GY", "IN", "JM", "KE", "KI", "KN", "LC", "LK",
            "LS", "MT", "MU", "MV", "MW", "MY", "MZ", "NA", "NG", "NR", "NZ", "PG", "PK",
            "RW", "SB", "SC", "SG", "SL", "SS", "SZ", "TO", "TT", "TV", "TZ", "UG", "VC",
            "VU", "WS", "ZA", "ZM",
        ),
        "https://thecommonwealth.org/our-member-countries",
    ),
}
