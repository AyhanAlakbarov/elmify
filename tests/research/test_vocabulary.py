"""Rules 1-3 as data: built from Wikidata, asserted against a floor and a ceiling.

No vocabulary file is committed yet: `manage.py build_resolver_vocabulary` needs
query.wikidata.org, and egress to it was blocked when this was written
(2026-09-26). So the loader is proven on files the REAL builders write from fake
SPARQL answers into a temporary directory, and the two tests that read the
committed files skip until someone runs the build and commits its output.
"""

import json

import pytest
from django.core.management import CommandError, call_command

from apps.research import vocabulary
from apps.research.names import profile
from apps.research.vocabulary import (
    VocabularyMissing,
    VocabularyShape,
    build_country_doc,
    build_kinds_doc,
)

_OWED = (
    "resolver vocabulary not built: manage.py build_resolver_vocabulary is owed "
    "(no Wikidata egress, 2026-09-26)"
)
_COMMITTED_COUNTRIES = ["TR", "DE", "AZ", "GE", "KZ", "UZ", "VN", "ID"]


def _sparql(answers):
    def run(query, **_):
        for marker, rows in answers.items():
            if marker in query:
                return rows
        raise AssertionError(f"unexpected query: {query[:80]}")
    return run


_ORGS = [{"label": f"{w} Eğitim Vakfı"} for w in ("Ak", "Bor", "Cem", "Dal", "Ece",
                                                  "Fer", "Gül", "Han", "Işık", "Jale")]
_TR_ANSWERS = {
    "wdt:P297": [{"country": "http://www.wikidata.org/entity/Q43", "lang": "tr", "tld": ".tr"}],
    "wd:Q515": [{"label": "Türkiye"}, {"label": "Stuttgart"}, {"label": "Nur-Sultan"}],
    "wdt:P856": _ORGS,
}
_KIND_ANSWERS = {
    "wd:Q43229": [
        {"kind": "http://www.wikidata.org/entity/Q157031", "label": "vakıf"},
        {"kind": "http://www.wikidata.org/entity/Q157031", "label": "foundation"},
        {"kind": "http://www.wikidata.org/entity/Q163740", "label": "non-profit organization"},
        {"kind": "http://www.wikidata.org/entity/Q163740", "label": "NPO"},
    ],
}


@pytest.fixture
def small_floors(monkeypatch):
    monkeypatch.setattr(vocabulary, "_GEO_FLOOR", 1)
    monkeypatch.setattr(vocabulary, "_ORG_FLOOR", 1)
    monkeypatch.setattr(vocabulary, "_KINDS_FLOOR", 1)


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    """A temporary DATA_DIR, with load_vocabulary's cache cleared either side
    so no test sees another's (or the committed) files."""
    target = tmp_path / "resolver_data"
    target.mkdir()
    monkeypatch.setattr(vocabulary, "DATA_DIR", target)
    vocabulary.load_vocabulary.cache_clear()
    yield target
    vocabulary.load_vocabulary.cache_clear()


def test_a_country_doc_carries_places_and_the_country_s_common_name_words(small_floors) -> None:
    doc = build_country_doc("TR", retrieved_on="2026-09-25", sparql=_sparql(_TR_ANSWERS))
    assert doc["country_qid"] == "Q43" and doc["cctld"] == "tr"
    assert doc["languages"] == ["tr", "en", "ru"]
    assert {"turkiye", "nursultan", "sultan"} <= set(doc["geo"])
    assert {"egitim", "vakfi"} <= set(doc["generic"])   # in every one of ten labels
    assert "bor" not in doc["generic"]


def test_a_country_that_is_not_exactly_one_item_is_a_stop() -> None:
    with pytest.raises(VocabularyShape):
        build_country_doc("TR", retrieved_on="2026-09-25", sparql=_sparql({"wdt:P297": []}))


def test_a_country_item_that_is_not_a_qid_never_reaches_the_next_query() -> None:
    with pytest.raises(VocabularyShape, match="not a QID"):
        build_country_doc("TR", retrieved_on="2026-09-25", sparql=_sparql({
            "wdt:P297": [{"country": "http://www.wikidata.org/entity/Q43 } UNION {", "lang": "tr"}],
        }))


def test_kinds_keep_single_token_labels_only(small_floors) -> None:
    doc = build_kinds_doc(
        ["tr", "en"], depth=2, retrieved_on="2026-09-25", sparql=_sparql(_KIND_ANSWERS)
    )
    assert doc["kinds"] == {"Q157031": ["foundation", "vakif"], "Q163740": ["npo"]}


def test_a_language_code_that_is_not_one_never_reaches_the_next_query(small_floors) -> None:
    # P424 values come back from Wikidata and are interpolated into the geo query.
    answers = {**_TR_ANSWERS, "wdt:P297": [
        {"country": "http://www.wikidata.org/entity/Q43", "lang": 'tr") } #'},
    ]}
    with pytest.raises(VocabularyShape, match="language code"):
        build_country_doc("TR", retrieved_on="2026-09-25", sparql=_sparql(answers))


def test_the_loader_reads_back_what_the_builders_write(small_floors, data_dir) -> None:
    country = build_country_doc("TR", retrieved_on="2026-09-25", sparql=_sparql(_TR_ANSWERS))
    kinds = build_kinds_doc(
        country["languages"], depth=2, retrieved_on="2026-09-25", sparql=_sparql(_KIND_ANSWERS)
    )
    (data_dir / "TR.json").write_text(json.dumps(country, ensure_ascii=False), "utf-8")
    (data_dir / "kinds.json").write_text(json.dumps(kinds, ensure_ascii=False), "utf-8")

    v = vocabulary.load_vocabulary("tr")
    assert (v.country_code, v.country_qid, v.cctld) == ("TR", "Q43", "tr")
    assert v.languages == ("tr", "en", "ru")
    assert v.kinds["vakif"] == {"Q157031"} and v.kinds["npo"] == {"Q163740"}
    assert "turkiye" in v.geo and "egitim" in v.generic
    # And it is a vocabulary the name reader can use: every word of this name
    # is kind, place or common, so nothing in it is distinctive.
    p = profile(["Türkiye Eğitim Vakfı"], v)
    assert p.kinds == {"Q157031"} and p.distinctive == frozenset()


def test_a_country_with_no_file_is_vocabulary_missing(data_dir) -> None:
    with pytest.raises(VocabularyMissing, match="TR.json"):
        vocabulary.load_vocabulary("TR")


def test_a_country_without_kinds_or_with_stale_kinds_is_vocabulary_missing(
    small_floors, data_dir
) -> None:
    country = build_country_doc("TR", retrieved_on="2026-09-25", sparql=_sparql(_TR_ANSWERS))
    (data_dir / "TR.json").write_text(json.dumps(country, ensure_ascii=False), "utf-8")
    with pytest.raises(VocabularyMissing, match="kinds.json"):
        vocabulary.load_vocabulary("TR")
    narrow = build_kinds_doc(
        ["en"], depth=2, retrieved_on="2026-09-25", sparql=_sparql(_KIND_ANSWERS)
    )
    (data_dir / "kinds.json").write_text(json.dumps(narrow), "utf-8")
    vocabulary.load_vocabulary.cache_clear()
    with pytest.raises(VocabularyMissing, match="lacks"):
        vocabulary.load_vocabulary("TR")


def test_the_command_writes_each_country_then_kinds_over_every_language(
    monkeypatch, data_dir
) -> None:
    (data_dir / "AZ.json").write_text(json.dumps({"languages": ["az", "en", "ru"]}), "utf-8")
    kinds_asked: list[list[str]] = []

    def country(iso2, *, retrieved_on):
        return {"iso2": iso2, "languages": ["tr", "en", "ru"], "geo": ["turkiye"],
                "generic": ["egitim"], "organisation_labels": 10, "retrieved_on": retrieved_on}

    def kinds(languages, *, depth, retrieved_on):
        kinds_asked.append(list(languages))
        return {"kinds": {"Q157031": ["vakif"]}, "languages": list(languages), "depth": depth}

    monkeypatch.setattr(vocabulary, "build_country_doc", country)
    monkeypatch.setattr(vocabulary, "build_kinds_doc", kinds)
    call_command("build_resolver_vocabulary", "--countries", "tr", "--kind-depth", "3")

    assert json.loads((data_dir / "TR.json").read_text("utf-8"))["iso2"] == "TR"
    # AZ was built on an earlier run: kinds must still cover its languages.
    assert kinds_asked == [["az", "en", "ru", "tr"]]
    written = json.loads((data_dir / "kinds.json").read_text("utf-8"))
    assert written["depth"] == 3


def test_a_shape_failure_stops_the_command_before_kinds_is_written(
    monkeypatch, data_dir
) -> None:
    def country(iso2, *, retrieved_on):
        raise VocabularyShape(f"{iso2}: 3 place tokens")

    monkeypatch.setattr(vocabulary, "build_country_doc", country)
    with pytest.raises(CommandError, match="place tokens"):
        call_command("build_resolver_vocabulary", "--countries", "TR")
    assert not (data_dir / "kinds.json").exists()


@pytest.mark.skipif(not (vocabulary.DATA_DIR / "kinds.json").exists(), reason=_OWED)
def test_the_committed_kinds_name_every_kind_v5_lacked() -> None:
    """4.13b rule 1: nine of Kazakhstan's eleven wrongs were directories that
    matched "embassy" as a DISTINCTIVE word, because the kind list had 16 kinds."""
    doc = json.loads((vocabulary.DATA_DIR / "kinds.json").read_text("utf-8"))
    words = {w for ws in doc["kinds"].values() for w in ws}
    for word in ("embassy", "foundation", "association", "university", "federation",
                 "club", "consulate", "commission", "society", "academy"):
        assert word in words, word


@pytest.mark.parametrize("country", [
    pytest.param(code, marks=pytest.mark.skipif(
        not (vocabulary.DATA_DIR / f"{code}.json").exists()
        or not (vocabulary.DATA_DIR / "kinds.json").exists(),
        reason=_OWED,
    ))
    for code in _COMMITTED_COUNTRIES
])
def test_every_committed_country_loads(country) -> None:
    v = vocabulary.load_vocabulary(country)
    assert v.country_qid.startswith("Q") and v.geo and v.kinds
