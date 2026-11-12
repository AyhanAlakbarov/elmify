import re
from pathlib import Path

from babel import Locale

from apps.research.card_funding.years import level_of_year, year_rows

SOURCES = Path(__file__).parent / "sources"


def test_every_row_is_a_country_a_level_and_a_cited_source():
    territories = set(Locale("en").territories)
    for row in year_rows():
        assert row.country in territories and len(row.country) == 2, row
        assert row.level in {"bachelor", "master", "phd"}, row
        assert re.fullmatch(r"[1-9]-[1-9]", row.years), row
        assert row.source_url.startswith("https://"), row


def test_every_rows_years_stop_where_its_source_says_the_bachelors_certainly_does():
    # A source stating a range (a German bachelor's runs three to four years) caps the row at the
    # range's minimum, because the longer end may already be a master's first year.
    snapshot = {}
    for line in (SOURCES / "years.tsv").read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            url, stated, sentence = line.split("\t")
            snapshot[url] = (stated, sentence)
    words = {3: ("drei", "three"), 4: ("vier", "four", "четыре")}
    for row in year_rows():
        stated, sentence = snapshot[row.source_url]
        numbers = [int(n) for n in stated.split("-")]
        for n in numbers:  # the TSV number must be the sentence's own
            assert str(n) in sentence or any(w in sentence.lower() for w in words[n]), (n, sentence)
        assert row.years == f"1-{numbers[0]}", row


def test_each_rows_highest_year_matches_and_the_next_does_not():
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
    phrase = {"az": "{n} kurs", "ru": "{n} курс", "en": "{o} year students"}
    for row in year_rows():
        top = int(row.years[-1])
        make = lambda n: phrase[row.locale].format(n=n, o=ordinal[n])  # noqa: E731
        assert level_of_year(make(top), row.country, row.locale) == "bachelor", row
        assert level_of_year(make(top + 1), row.country, row.locale) is None, row


def test_a_masters_or_doctoral_year_is_never_a_bachelors_year():
    assert level_of_year("1 курс магистратуры", "RU", "ru") is None
    assert level_of_year("2 курс аспирантуры", "RU", "ru") is None
    assert level_of_year("3 курс бакалавриата", "RU", "ru") == "bachelor"
    # an inflected курс must not let the lookahead start mid-word
    for phrase in ("студент 1 курса магистратуры", "на 1 курсе магистратуры",
                   "студентов 2 курса аспирантуры"):
        assert level_of_year(phrase, "RU", "ru") is None, phrase
    assert level_of_year("студенты 3 курса бакалавриата", "RU", "ru") == "bachelor"
    assert level_of_year("I kurs magistr tələbələri", "AZ", "az") is None
    assert level_of_year("II kurs doktorant", "AZ", "az") is None
    assert level_of_year("I kurs bakalavr tələbələri", "AZ", "az") == "bachelor"


def test_the_funders_country_decides_what_a_year_of_study_means():
    english = "for 1st–3rd year students"  # names no country
    assert level_of_year(english, "AZ", "en") == "bachelor"  # an Azerbaijani funder
    assert level_of_year(english, "DE", "en") == "bachelor"  # a German funder
    assert level_of_year(english, "", "en") is None  # an unknown funder: held, no default
    assert level_of_year(english, "FR", "en") is None  # a funder with no row: held
    fourth = "open to 4th year students"
    assert level_of_year(fourth, "AZ", "en") == "bachelor"  # a four-year bachelor's
    assert level_of_year(fourth, "DE", "en") is None  # three to four years: maybe a master's


def test_the_owners_seed_examples_name_bachelor():
    assert level_of_year("Open to I, II və III kurs tələbələri", "AZ", "az") == "bachelor"
    assert level_of_year("студенты 3–4 курс бакалавриата", "RU", "ru") == "bachelor"
    assert level_of_year("студенты 3–4 курс бакалавриата", "RU", "") == "bachelor"


def test_no_row_is_no_level():
    assert level_of_year("5th year students", "AZ", "en") is None  # beyond the bachelor's years
    assert level_of_year("I, II və III kurs", "AZ", "ru") is None  # wrong page language
