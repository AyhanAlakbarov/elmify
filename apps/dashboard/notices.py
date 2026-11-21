"""Country notices (lanes spec §13a): display text keyed on a country code.

Owner-approved wording, never catalogue data. New countries are added only by
the owner. Re-check every 3 months: update `checked_on` and `sources`, or report
a fact that changed -- never reword it here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Notice:
    card_line: str
    title: str
    intro: str
    points: tuple[tuple[str, str], ...]
    footer: str
    checked_on: date
    sources: tuple[str, ...]


_RU_CHECKED = date(2026, 10, 12)  # the date Step 1's check was made
_RU = Notice(
    card_line=(
        "⚠ Studying in Russia: check payments, travel and degree recognition first — see details."
    ),
    title="Before you apply to a programme in Russia",
    intro="International sanctions in place since 2022 can affect you as a student:",
    points=(
        (
            "Payments.",
            "Visa and Mastercard have suspended their operations in Russia, so cards issued "
            "outside Russia don't work there. Several major Russian banks are also cut off "
            "from SWIFT, the network banks use for international transfers. Ask your bank, "
            "before you pay any fee, how you'll pay the tuition and receive money.",
        ),
        (
            "Travel.",
            "Russian airlines and Russian-registered planes are banned from EU, UK and US "
            "airspace. Depending on where you live, you may need a connection through another"
            " country, so check routes from your home city.",
        ),
        (
            "Degree recognition.",
            "Russia's membership of the European Higher Education Area (the Bologna Process) "
            "is suspended. If you plan to work or study further in the EU, UK or US, check "
            "how your degree will be recognised there.",
        ),
        (
            "Exchanges.",
            "The EU has ended Erasmus+ cooperation with Russian public bodies, a group that "
            "includes Russia's state universities.",
        ),
    ),
    footer=(
        f"This is general information as of {_RU_CHECKED.day} {_RU_CHECKED:%B %Y}, "
        "not legal advice. Rules change; your counsellor can help you check what applies to you."
    ),
    checked_on=_RU_CHECKED,
    sources=(
        "https://investor.visa.com/news/news-details/2022/Visa-Suspends-All-Russia-Operations/default.aspx",
        "https://investor.mastercard.com/investor-news/investor-news-details/2022/Mastercard-Statement-on-Suspension-of-Russian-Operations/default.aspx",
        "https://enlargement.ec.europa.eu/news/ukraine-eu-agrees-exclude-key-russian-banks-swift-2022-03-02_en",
        "https://web.archive.org/web/20241226025542/https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32022R0334",
        "https://www.legislation.gov.uk/uksi/2022/183/regulation/2",
        "https://web.archive.org/web/20250113173145/https://www.transportation.gov/briefing-room/us-will-block-russian-aircraft-using-all-domestic-airspace",
        "https://ehea.info/about-ehea/ehea-membership-and-criteria/",
        "https://education.ec.europa.eu/news/termination-of-cooperation-with-russian-public-entities-in-research-and-education",
        "https://erasmus-plus.ec.europa.eu/news/eu-stands-with-ukraine",
    ),
)

_NOTICES = {"RU": _RU}


def notice_for(country_code: str) -> Notice | None:
    return _NOTICES.get((country_code or "").upper())
