"""The language loop (decision 38): official languages from CLDR, then English;
diaspora by home language only."""

import pytest

from apps.research.languages import CldrLanguages, home_language, pass_languages


class _Fixed:
    def __init__(self, codes: tuple[str, ...]) -> None:
        self.codes = codes

    def languages(self, country_code: str) -> tuple[str, ...]:
        return self.codes


def test_every_official_language_then_english() -> None:
    assert pass_languages("KZ", "PRIVATE_FOUNDATION", source=_Fixed(("kk", "ru"))) == (
        "kk", "ru", "en",
    )


def test_english_is_not_asked_twice_where_it_is_official() -> None:
    assert pass_languages("PK", "PRIVATE_FOUNDATION", source=_Fixed(("en", "ur"))) == ("ur", "en")


@pytest.mark.parametrize(
    ("country", "languages"),
    [
        # Wikidata listed Hawaiian, Samoan, Chamorro, Carolinian and Spanish and
        # deprecated English; CLDR has English de facto and the rest regional.
        ("US", ("en",)),
        ("FR", ("fr",)),
        ("BE", ("nl", "fr", "de")),
        ("KZ", ("ru", "kk")),
        ("NZ", ("en",)),  # Māori, 2.8% of residents, is left to the English leg
        ("SG", ("en", "zh", "ms")),  # Tamil, 2.1%, likewise
        ("NO", ("nb", "nn")),  # the macrolanguage "no" would run Bokmål twice
        ("AZ", ("az",)),  # az_Cyrl is the same language in another script
        ("ES", ("es",)),  # Catalan, Galician, Basque are regional
    ],
)
def test_cldr_gives_the_languages_a_country_publishes_in(country, languages) -> None:
    assert CldrLanguages().languages(country) == languages


def test_a_us_pass_runs_in_english_alone() -> None:
    assert pass_languages("US", "PRIVATE_FOUNDATION", source=CldrLanguages()) == ("en",)


def test_a_malformed_country_code_is_refused() -> None:
    with pytest.raises(ValueError, match="ISO 3166"):
        CldrLanguages().languages("us; drop")


def test_a_country_with_no_official_language_is_english_only_and_says_so(caplog) -> None:
    assert pass_languages("XX", "PRIVATE_FOUNDATION", source=_Fixed(())) == ("en",)
    assert "no official language" in caplog.text


def test_a_diaspora_pass_runs_in_its_home_language_then_english_not_the_hosts() -> None:
    langs = pass_languages(
        "DE", "AFFINITY_OR_DIASPORA", source=_Fixed(("de",)), home_language="az"
    )
    assert langs == ("az", "en")


def test_a_diaspora_pass_without_a_home_language_is_refused() -> None:
    with pytest.raises(ValueError, match="home language"):
        pass_languages("DE", "AFFINITY_OR_DIASPORA", source=_Fixed(("de",)))


@pytest.mark.parametrize(
    ("family", "codes", "message"),
    [
        ("AFFINITY_OR_DIASPORA", [], "exactly one home language"),
        ("AFFINITY_OR_DIASPORA", ["az", "tr"], "exactly one home language"),
        ("PRIVATE_FOUNDATION", ["az"], "AFFINITY_OR_DIASPORA only"),
        ("AFFINITY_OR_DIASPORA", ["a;z"], "not a language code"),
        # SweepAngle/SweepRun.home_language is CharField(max_length=12); a
        # BCP-47 tag matching `_LANG` can still be longer than the column.
        ("AFFINITY_OR_DIASPORA", ["az-latn-az-extra-long-subtag"], "longer than 12 characters"),
    ],
)
def test_a_diaspora_pass_takes_exactly_one_home_language(family, codes, message) -> None:
    with pytest.raises(ValueError, match=message):
        home_language(family, codes)


def test_the_home_language_is_lowercased_and_empty_outside_diaspora() -> None:
    assert home_language("AFFINITY_OR_DIASPORA", ["AZ"]) == "az"
    assert home_language("PRIVATE_FOUNDATION", []) == ""
