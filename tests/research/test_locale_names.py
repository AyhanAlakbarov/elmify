import re

from apps.research.locale_names import (
    country_forms,
    country_names,
    inflected,
    lookup,
    month_names,
)


def test_month_names_come_from_the_format_context():
    assert month_names("tr")["şubat"] == 2
    assert month_names("az")["fevral"] == 2
    assert month_names("ru")["февраля"] == 2 and month_names("ru")["февраль"] == 2
    assert month_names("hu")["február"] == 2
    # Babel 2.18's stand-alone context falls back to another locale ("fevral" for Turkish)
    assert "fevral" not in month_names("tr")
    assert "feb" not in month_names("en", wide_only=True)


def test_abbreviations_drop_their_dot():
    assert month_names("ru")["февр"] == 2
    assert month_names("en")["feb"] == 2


def test_country_names_map_to_alpha_2_codes():
    assert country_names("az")["azərbaycan"] == "AZ"
    assert country_names("ru")["турция"] == "TR"
    assert country_names("ko")["아제르바이잔"] == "AZ"
    assert all(len(code) == 2 and code.isalpha() for code in country_names("en").values())


def test_inflected_month_and_country_forms():
    forms = [("февраля", "ru"), ("турция", "ru"), ("azərbaycan", "az"), ("şubat", "tr")]
    pattern = re.compile(inflected(forms), re.IGNORECASE)
    for text in ("1 февраля", "в феврале", "в Турции", "Azərbaycanın", "Şubat'ta"):
        assert pattern.search(text), text
    # a stem never matches inside another word, and only inflecting languages are stemmed
    assert not re.compile(inflected([("mart", "tr")]), re.IGNORECASE).search("smartphone")
    assert not re.compile(inflected([("enero", "es")]), re.IGNORECASE).search("Energy")
    assert not re.compile(inflected([("belgia", "pl")]), re.IGNORECASE).search("belgeler")


def test_lookup_prefers_an_exact_name_then_the_longest_stem():
    assert lookup("Турции", country_forms()) == "TR"
    assert lookup("Niger", country_forms()) == "NE"
    assert lookup("Nigeria", country_forms()) == "NG"
    assert lookup("İraq", country_forms()) == "IQ"


def test_a_short_name_takes_only_a_case_ending():
    forms = [("mali", "tr"), ("индия", "ru"), ("çin", "az")]
    pattern = re.compile(inflected(forms), re.IGNORECASE)
    for text in ("maliyyələşdirilməsi", "malik olmaq", "индивидуальных"):
        assert not pattern.search(text), text
    for text in ("Mali'den", "Malidə", "Индии", "Çində", "Çinli", "Çinədək"):
        assert pattern.search(text), text


def test_lookup_applies_the_short_stem_ending_rule():
    assert lookup("Maliyyə", country_forms()) is None
    assert lookup("Çinar", country_forms()) is None
