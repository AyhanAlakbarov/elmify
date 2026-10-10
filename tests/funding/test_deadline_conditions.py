"""deadline_for as written -> the vocabulary validity.select_deadline reads."""
import datetime as dt

import pytest

from apps.funding import deadline_conditions
from apps.funding.deadline_conditions import ConditionTerm, normalise_condition
from apps.funding.validity import Evidence, select_deadline

COUNTRIES = {
    "india": "IN", "indian": "IN", "türkiye": "TR", "turkey": "TR", "türkei": "TR",
    "pakistan": "PK", "guinea": "GN", "papua new guinea": "PG",
}
TERMS = (
    ConditionTerm(r"\bnon[- ]?eu\b", "APPLICANT_CLASS:NON_EU"),
    ConditionTerm(r"\beu\b", "NATIONALITY:EU"),
    ConditionTerm(r"\bself[- ]funded\b", "FUNDING:SELF_FUNDED"),
    ConditionTerm(r"\bnominat\w*", "ROUTE:NOMINATION"),
    ConditionTerm(r"\bround\s*(\d+)", "ROUND:{0}"),
    ConditionTerm(r"\bresiden(?:t|ts|ce)\b", "RESIDENCE:*"),
    # A negation word refuses to map: the whole phrase is OTHER, as written.
    ConditionTerm(r"\boutside\b", "OTHER"),
    ConditionTerm(r"\bother than\b", "OTHER"),
    ConditionTerm(r"\bexcept\b", "OTHER"),
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ALL", "ALL"),
        ("", "ALL"),
        ("NATIONALITY:IN", "NATIONALITY:IN"),  # the judge may already write the form
        ("applicants from India", "NATIONALITY:IN"),
        ("Bewerber aus der Türkei", "NATIONALITY:TR"),
        ("applicants from India and Pakistan", "NATIONALITY:IN,PK"),
        ("citizens of Papua New Guinea", "NATIONALITY:PG"),  # longest label wins its span
        ("residents of Türkiye", "RESIDENCE:TR"),
        ("non-EU citizens", "APPLICANT_CLASS:NON_EU"),  # earliest match beats "eu"
        ("EU citizens", "NATIONALITY:EU"),
        ("self-funded students", "FUNDING:SELF_FUNDED"),
        ("nominating institutions", "ROUTE:NOMINATION"),
        ("round 2", "ROUND:2"),
        ("members of the Karajan-Akademie", "OTHER:members of the Karajan-Akademie"),
        ("residents", "OTHER:residents"),  # a residence phrase naming no place
    ],
)
def test_conditions_normalise_from_data_not_a_hand_table(text, expected):
    assert normalise_condition(text, countries=COUNTRIES, terms=TERMS) == expected


def test_a_normalised_nationality_is_what_select_deadline_matches():
    whose = normalise_condition("applicants from India", countries=COUNTRIES, terms=TERMS)
    evidence = Evidence(
        deadlines=((dt.date(2026, 10, 15), whose), (dt.date(2026, 12, 15), "ALL"))
    )
    chosen = select_deadline(evidence, {"nationality": "IN"})
    assert (chosen.date, chosen.condition) == (dt.date(2026, 10, 15), "NATIONALITY:IN")


@pytest.mark.parametrize(
    "text",
    [
        "residents of non-EU countries",
        "non-Indian residents",
        "non Indian applicants",
        "applicants from outside India",
        "citizens of countries other than Pakistan",
        "all nationalities except India",
        "residents of non-European Union countries",
        "EU residents",  # residence plus another term: which one binds is a guess
    ],
)
def test_a_negated_place_is_never_mapped_to_that_place(text):
    """Review of 1a72ace: "residents of non-EU countries" came out RESIDENCE:EU,
    the exact inverse of what the page says. A negated place is refused."""
    assert normalise_condition(text, countries=COUNTRIES, terms=TERMS) == f"OTHER:{text}"


def test_the_shipped_terms_refuse_negation_words():
    terms = deadline_conditions.default_terms()
    for text in ("applicants from outside India", "nationals other than India",
                 "all countries except India", "excluding India"):
        assert normalise_condition(text, countries=COUNTRIES, terms=terms) == f"OTHER:{text}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NATIONALITY:IN,PK", "NATIONALITY:IN,PK"),
        ("RESIDENCE:EU", "RESIDENCE:EU"),
        ("nationality:IN", "NATIONALITY:IN"),  # a lowercase prefix is still the form
        ("ROUND:2", "ROUND:2"),
        ("APPLICANT_CLASS:NON_EU", "APPLICANT_CLASS:NON_EU"),
        ("FUNDING:SELF_FUNDED", "FUNDING:SELF_FUNDED"),
        ("OTHER:" + "x" * 200, "OTHER:" + "x" * 60),
        # Not the form: these fall through to phrase matching.
        ("NATIONALITY:India", "NATIONALITY:IN"),
        ("ROUND:second", "OTHER:ROUND:second"),
        ("residence: no", "OTHER:residence: no"),  # never Norway from lowercase prose
        ("ROUTE:direct applicants", "OTHER:ROUTE:direct applicants"),
        ("NATIONALITY:", "OTHER:NATIONALITY:"),
        # validity reads an OPEN row as unconditional; OTHER would match nobody.
        ("OPEN", "OPEN"),
        ("OPEN:open to all nationalities", "OPEN:open to all nationalities"),
        ("open", "OTHER:open"),
    ],
)
def test_the_normalised_form_passes_through_only_when_it_is_valid(text, expected):
    assert normalise_condition(text, countries=COUNTRIES, terms=TERMS) == expected


def test_injected_country_labels_are_casefolded():
    assert normalise_condition(
        "applicants from India", countries={"India": "IN"}, terms=TERMS
    ) == "NATIONALITY:IN"


def test_a_label_two_countries_share_is_dropped(tmp_path, monkeypatch):
    """"Korean" is a demonym of KP and KR; the last CSV row must not win."""
    docs = tmp_path
    (docs / "country-labels.csv").write_text(
        "label,iso2,language,kind,source,fetched_on\n"
        "Korean,KP,en,demonym,s,2026-09-26\n"
        "Korean,KR,en,demonym,s,2026-09-26\n"
        "South Korea,KR,en,label,s,2026-09-26\n"
        "India,IN,en,label,s,2026-09-26\n"
        "India,in,en,label,s,2026-09-26\n",
        encoding="utf-8",
    )
    deadline_conditions.default_countries.cache_clear()
    monkeypatch.setattr(deadline_conditions, "_DOCS", docs)
    try:
        countries = deadline_conditions.default_countries()
    finally:
        deadline_conditions.default_countries.cache_clear()
    assert countries == {"south korea": "KR", "india": "IN"}
    assert normalise_condition("Korean citizens", countries=countries, terms=TERMS) == (
        "OTHER:Korean citizens"
    )


def test_an_open_row_is_still_the_general_date_for_select_deadline():
    whose = normalise_condition("OPEN", countries=COUNTRIES, terms=TERMS)
    evidence = Evidence(deadlines=((dt.date(2026, 12, 15), whose),))
    chosen = select_deadline(evidence, {"nationality": "IN"})
    assert chosen is not None and chosen.date == dt.date(2026, 12, 15)
