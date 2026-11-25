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
        ("BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "TL", "VN"),
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
            "RW", "SB", "SC", "SG", "SL", "SZ", "TG", "TO", "TT", "TV", "TZ", "UG", "VC",
            "VU", "WS", "ZA", "ZM",
        ),
        "https://thecommonwealth.org/our-member-countries",
    ),
    "TURKIC_STATES": Region(
        "Organization of Turkic States",
        ("AZ", "KG", "KZ", "TR", "UZ"),
        "https://www.turkicstates.org/en/member-states",
    ),
    "OIC": Region(
        "Organisation of Islamic Cooperation",
        (
            "AE", "AF", "AL", "AZ", "BD", "BF", "BH", "BJ", "BN", "CI", "CM", "DJ", "DZ",
            "EG", "GA", "GM", "GN", "GW", "GY", "ID", "IQ", "IR", "JO", "KG", "KM", "KW",
            "KZ", "LB", "LY", "MA", "ML", "MR", "MV", "MY", "MZ", "NE", "NG", "OM", "PK",
            "PS", "QA", "SA", "SD", "SL", "SN", "SO", "SR", "SY", "TD", "TG", "TJ", "TM",
            "TN", "TR", "UG", "UZ", "YE",
        ),
        "https://www.oic-oci.org/states/?lan=en",
    ),
    "MERCOSUR": Region(
        "Southern Common Market",
        ("AR", "BO", "BR", "CL", "CO", "EC", "GY", "PE", "PY", "SR", "UY", "VE"),
        "https://www.mercosur.int/quienes-somos/paises-del-mercosur/",
    ),
    "CARICOM": Region(
        "Caribbean Community",
        (
            "AG", "BB", "BS", "BZ", "DM", "GD", "GY", "HT", "JM", "KN", "LC", "SR", "TT", "VC",
        ),
        "https://caricom.org/member-states-and-associate-members/",
    ),
    "GCC": Region(
        "Gulf Cooperation Council",
        ("AE", "BH", "KW", "OM", "QA", "SA"),
        "https://www.gcc-sg.org/en/AboutUs/MemberStates",
    ),
    "SAARC": Region(
        "South Asian Association for Regional Cooperation",
        ("AF", "BD", "BT", "IN", "LK", "MV", "NP", "PK"),
        "https://www.saarc-sec.org/index.php/about-saarc/member-states",
    ),
    "SADC": Region(
        "Southern African Development Community",
        (
            "AO", "BW", "CD", "KM", "LS", "MG", "MU", "MW", "MZ", "NA", "SC", "SZ", "TZ", "ZA",
            "ZM", "ZW",
        ),
        "https://www.sadc.int/member-states",
    ),
    "ECOWAS": Region(
        "Economic Community of West African States",
        (
            "BF", "BJ", "CI", "CV", "GH", "GM", "GN", "GW", "LR", "ML", "NE", "NG", "SL", "SN",
            "TG",
        ),
        "https://www.ecowas.int/member-states/",
    ),
    "MENA": Region(
        "Middle East and North Africa",
        (
            "AE", "BH", "DJ", "DZ", "EG", "IL", "IQ", "IR", "JO", "KW", "LB", "LY", "MA", "MT",
            "OM", "PS", "QA", "SA", "SD", "SY", "TN", "TR", "YE",
        ),
        "https://data.worldbank.org/region/middle-east-and-north-africa",
    ),
    "LATAM": Region(
        "Latin America and the Caribbean",
        (
            "AR", "BO", "BR", "BZ", "CL", "CO", "CR", "CU", "DO", "EC", "GT", "GY", "HN", "HT",
            "JM", "MX", "NI", "PA", "PE", "PY", "SR", "SV", "TT", "UY", "VE",
        ),
        "https://data.worldbank.org/region/latin-america-and-caribbean",
    ),
    "NORDIC": Region(
        "Nordic Countries",
        ("DK", "FI", "IS", "NO", "SE"),
        "https://www.norden.org/en/information/nordic-countries",
    ),
    "VISEGRAD": Region(
        "Visegrad Group",
        ("CZ", "HU", "PL", "SK"),
        "https://www.visegradgroup.eu/about",
    ),
    "BENELUX": Region(
        "Benelux Union",
        ("BE", "LU", "NL"),
        "https://www.benelux.int/",
    ),
    "EFTA": Region(
        "European Free Trade Association",
        ("CH", "IS", "LI", "NO"),
        "https://www.efta.int/about-efta/efta-states",
    ),
    "FRANCOPHONE": Region(
        "Organisation internationale de la Francophonie",
        (
            "BE", "BF", "BI", "BJ", "CA", "CD", "CF", "CG", "CH", "CI", "CM", "DJ", "DZ", "FR",
            "GA", "GN", "HT", "KM", "LB", "LU", "MA", "MC", "MG", "ML", "MR", "MU", "NE", "RW",
            "SC", "SN", "TD", "TG", "TN", "VU",
        ),
        "https://www.francophonie.org/88-etats-et-gouvernements-125",
    ),
}
