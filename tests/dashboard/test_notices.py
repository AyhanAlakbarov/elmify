# ruff: noqa: E501  (the owner's sentences are pinned whole, on one line each)
from apps.dashboard.notices import notice_for

# Copied from lanes spec section 13a (owner wording), check date filled in.
_INTRO = "International sanctions in place since 2022 can affect you as a student:"
_POINTS = (
    ("Payments.", "Visa and Mastercard have suspended their operations in Russia, so cards issued outside Russia don't work there. Several major Russian banks are also cut off from SWIFT, the network banks use for international transfers. Ask your bank, before you pay any fee, how you'll pay the tuition and receive money."),
    ("Travel.", "Russian airlines and Russian-registered planes are banned from EU, UK and US airspace. Depending on where you live, you may need a connection through another country, so check routes from your home city."),
    ("Degree recognition.", "Russia's membership of the European Higher Education Area (the Bologna Process) is suspended. If you plan to work or study further in the EU, UK or US, check how your degree will be recognised there."),
    ("Exchanges.", "The EU has ended Erasmus+ cooperation with Russian public bodies, a group that includes Russia's state universities."),
)
_FOOTER = (
    "This is general information as of 12 October 2026, not legal advice. Rules change; "
    "your counsellor can help you check what applies to you."
)


def test_russia_has_the_owner_wording() -> None:
    notice = notice_for("RU")
    assert notice is not None
    assert notice.card_line == (
        "⚠ Studying in Russia: check payments, travel and degree recognition first — see details."
    )
    assert notice.title == "Before you apply to a programme in Russia"
    assert notice.intro == _INTRO
    assert notice.points == _POINTS
    assert notice.footer == _FOOTER
    assert notice.sources, "every fact is checked against a source before it ships"
    assert all(source.startswith("https://") for source in notice.sources)


def test_no_notice_for_other_countries() -> None:
    assert notice_for("SE") is None
    assert notice_for("") is None
