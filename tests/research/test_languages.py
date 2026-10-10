"""The language loop (decision 38): P37, then English; diaspora by home language only."""

import pytest

from apps.research.languages import WikidataLanguages, home_language, pass_languages


class _Sparql:
    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        self.queries: list[str] = []

    def __call__(self, query: str) -> list[dict[str, str]]:
        self.queries.append(query)
        return [{"code": c} for c in self.codes]


class _Fixed:
    def __init__(self, codes: tuple[str, ...]) -> None:
        self.codes = codes

    def languages(self, country_code: str) -> tuple[str, ...]:
        return self.codes


def test_every_official_language_then_english() -> None:
    sparql = _Sparql(["ru", "kk"])
    assert WikidataLanguages(sparql=sparql).languages("KZ") == ("kk", "ru")
    assert pass_languages("KZ", "PRIVATE_FOUNDATION", source=_Fixed(("kk", "ru"))) == (
        "kk", "ru", "en",
    )


def test_english_is_not_asked_twice_where_it_is_official() -> None:
    assert pass_languages("PK", "PRIVATE_FOUNDATION", source=_Fixed(("en", "ur"))) == ("ur", "en")


def test_the_country_code_cannot_inject_sparql() -> None:
    with pytest.raises(ValueError):
        WikidataLanguages(sparql=_Sparql([])).languages('TR" } UNION { ?x ?y ?z')


def test_the_query_names_p37_and_the_validated_code() -> None:
    sparql = _Sparql(["tr"])
    WikidataLanguages(sparql=sparql).languages("TR")
    assert "P37" in sparql.queries[0]
    assert '"TR"' in sparql.queries[0]


def test_a_malformed_code_is_dropped_and_logged(caplog) -> None:
    with caplog.at_level("WARNING"):
        assert WikidataLanguages(sparql=_Sparql(["EN GB", "x;y", "tr"])).languages("TR") == ("tr",)
    assert "en gb" in caplog.text


def test_a_country_wikidata_gives_no_language_is_english_only_and_says_so(caplog) -> None:
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
