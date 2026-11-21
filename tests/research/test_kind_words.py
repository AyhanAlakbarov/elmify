"""Kind words per language (spec 6.5 rule 1): the angle generator's vocabulary.

The builder is tested against a faked query service; the committed file is
tested through its real consumer, `generate_angles`.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command

from apps.research import kind_words, vocabulary
from apps.research.angles import PASS_SHAPES, AngleSet, GeneratedAngle, generate_angles
from apps.research.kind_words import (
    KindWords,
    build_kind_words_doc,
    load_kind_words,
    read_holder_kinds,
)
from apps.research.models import ANGLE_KINDS
from apps.research.vocabulary import VocabularyShape

_ENTITY = "http://www.wikidata.org/entity/"


def _row(qid: str, word: str, lang: str, rank: int = 0) -> dict[str, str]:
    return {"kind": f"{_ENTITY}{qid}", "word": word, "lang": lang, "rank": str(rank)}


def _map(target, kinds: dict[str, list[str]]) -> None:
    (target / "holder_kinds.json").write_text(json.dumps({
        "kinds": {k: [{"qid": q, "label": "x"} for q in qids] for k, qids in kinds.items()}
    }), "utf-8")


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    target = tmp_path / "resolver_data"
    target.mkdir()
    monkeypatch.setattr(vocabulary, "DATA_DIR", target)
    return target


def test_labels_come_before_aliases_and_items_keep_the_map_s_order(data_dir) -> None:
    _map(data_dir, {"PRIVATE_FOUNDATION": ["Q157031", "Q708676"]})
    rows = [
        _row("Q708676", "hayır kurumu", "tr"),
        _row("Q157031", "vakfı", "tr", rank=1),
        _row("Q157031", "vakıf", "tr"),
        _row("Q157031", "foundation", "en"),
        _row("Q708676", "charity", "en"),
    ]
    doc = build_kind_words_doc(retrieved_on="2026-10-12", sparql=lambda _q: rows)
    assert doc["words"]["PRIVATE_FOUNDATION"]["tr"] == ["vakıf", "hayır kurumu", "vakfı"]
    assert doc["items"] == {"PRIVATE_FOUNDATION": ["Q157031", "Q708676"]}
    assert doc["retrieved_on"] == "2026-10-12"


def test_abbreviations_bad_language_tags_and_case_duplicates_are_dropped(data_dir) -> None:
    _map(data_dir, {"EMPLOYER": ["Q783794"]})
    rows = [
        _row("Q783794", "company", "en"),
        _row("Q783794", "co.", "en", rank=1),
        _row("Q783794", "Company", "en", rank=1),
        _row("Q783794", "회사", "ko"),
        _row("Q783794", "firma", "x'; DROP"),
        _row("Q783794", "firma", "de-x-a-very-long-private-tag"),
    ]
    doc = build_kind_words_doc(retrieved_on="2026-10-12", sparql=lambda _q: rows)
    # Two characters is a whole word in Korean; only the dotted form goes.
    assert doc["words"]["EMPLOYER"] == {"en": ["company"], "ko": ["회사"]}


def test_an_item_with_no_english_label_stops_the_build(data_dir) -> None:
    _map(data_dir, {"EMPLOYER": ["Q783794", "Q6881511"]})
    rows = [_row("Q783794", "company", "en"), _row("Q6881511", "Unternehmen", "de")]
    with pytest.raises(VocabularyShape, match="Q6881511"):
        build_kind_words_doc(retrieved_on="2026-10-12", sparql=lambda _q: rows)


@pytest.mark.parametrize(
    "kinds", [{"NOT_A_KIND": ["Q1"]}, {"EMPLOYER": ["wd:Q1 } UNION {"]}, {"EMPLOYER": []}]
)
def test_a_map_row_that_is_not_a_holder_kind_or_a_qid_never_reaches_the_query(
    data_dir, kinds
) -> None:
    _map(data_dir, kinds)

    def never(_query: str) -> list[dict[str, str]]:
        raise AssertionError("a bad map must stop before any query")

    with pytest.raises(VocabularyShape):
        build_kind_words_doc(retrieved_on="2026-10-12", sparql=never)


def _corrections(target, *, add=(), drop=()) -> None:
    (target / "kind_word_corrections.json").write_text(
        json.dumps({"add": list(add), "drop": list(drop)}), "utf-8"
    )


_AZ_ROWS = [
    _row("Q157031", "foundation", "en"),
    _row("Q157031", "Vəqf", "az"),
    _row("Q157031", "Айырбас", "kk"),
    _row("Q157031", "Қор", "kk", rank=1),
]
_FOND = {
    "kind": "PRIVATE_FOUNDATION", "language": "az", "word": "fond",
    "source": "https://e-qanun.az/framework/511", "checked_on": "2026-10-12",
}


def test_a_sourced_word_leads_its_language_and_a_wrong_one_is_dropped(data_dir) -> None:
    _map(data_dir, {"PRIVATE_FOUNDATION": ["Q157031"]})
    _corrections(
        data_dir,
        add=[_FOND, {**_FOND, "language": "et", "word": "sihtasutus"}],
        drop=[{"kind": "PRIVATE_FOUNDATION", "language": "kk", "word": "айырбас",
               "why": "means exchange"}],
    )
    doc = build_kind_words_doc(retrieved_on="2026-10-12", sparql=lambda _q: _AZ_ROWS)
    words = doc["words"]["PRIVATE_FOUNDATION"]
    assert words["az"] == ["fond", "Vəqf"]
    assert words["et"] == ["sihtasutus"]  # a language Wikidata had nothing in
    assert words["kk"] == ["Қор"]
    assert doc["corrections"] == {"added": 2, "dropped": 1}


@pytest.mark.parametrize(
    "corrections",
    [
        {"add": [{**_FOND, "source": ""}]},  # a hand-added word with no page behind it
        {"add": [{**_FOND, "source": "http://e-qanun.az/framework/511"}]},
        {"add": [{k: v for k, v in _FOND.items() if k != "checked_on"}]},
        {"add": [{**_FOND, "kind": "EMPLOYER"}]},  # not a kind the map carries
        {"add": [{**_FOND, "language": "az'; DROP"}]},
        {"drop": [{"kind": "PRIVATE_FOUNDATION", "language": "kk", "word": "Айырбас"}]},
        # Wikidata was corrected: a drop that removes nothing is a stale row.
        {"drop": [{"kind": "PRIVATE_FOUNDATION", "language": "az", "word": "nope", "why": "x"}]},
    ],
)
def test_an_unsourced_unusable_or_stale_correction_stops_the_build(
    data_dir, corrections
) -> None:
    _map(data_dir, {"PRIVATE_FOUNDATION": ["Q157031"]})
    _corrections(data_dir, **corrections)
    with pytest.raises(VocabularyShape):
        build_kind_words_doc(retrieved_on="2026-10-12", sparql=lambda _q: _AZ_ROWS)


def test_a_regional_tag_reads_its_base_language_s_words_only_when_it_has_none() -> None:
    words = KindWords({"EMPLOYER": {"en": ("company",), "zh": ("公司",), "en-gb": ("firm",)}})
    assert words.words("EMPLOYER", "zh-cn") == ("公司",)
    assert words.words("EMPLOYER", "en-gb") == ("firm",)
    assert words.words("EMPLOYER", "tr") == ()


def test_generic_norwegian_reads_bokmal_s_words() -> None:
    words = KindWords({"PRIVATE_FOUNDATION": {"nb": ("stiftelse",), "nn": ("stifting",)}})
    assert words.words("PRIVATE_FOUNDATION", "no") == ("stiftelse",)
    assert words.words("PRIVATE_FOUNDATION", "nn") == ("stifting",)


def test_the_loader_is_none_until_built_then_reads_back_what_the_command_wrote(
    monkeypatch, data_dir
) -> None:
    assert load_kind_words() is None
    _map(data_dir, {"PRIVATE_FOUNDATION": ["Q157031"]})
    rows = [_row("Q157031", "foundation", "en"), _row("Q157031", "vakıf", "tr")]
    monkeypatch.setattr(
        kind_words, "build_kind_words_doc",
        lambda *, retrieved_on: build_kind_words_doc(
            retrieved_on=retrieved_on, sparql=lambda _q: rows
        ),
    )
    call_command("build_kind_words")
    loaded = load_kind_words()
    assert loaded is not None
    assert loaded.words("PRIVATE_FOUNDATION", "tr") == ("vakıf",)
    assert loaded.words("PRIVATE_FOUNDATION", "xx") == ()
    assert loaded.words("EMPLOYER", "tr") == ()


def test_a_shape_failure_stops_the_command_before_the_file_is_written(
    monkeypatch, data_dir
) -> None:
    def broken(*, retrieved_on: str) -> dict:
        raise VocabularyShape("no English label for ['Q1']")

    monkeypatch.setattr(kind_words, "build_kind_words_doc", broken)
    with pytest.raises(CommandError, match="no English label"):
        call_command("build_kind_words")
    assert not (data_dir / "kind_words.json").exists()


def test_the_committed_map_covers_every_kind_a_sweep_pass_searches_for() -> None:
    mapped = set(read_holder_kinds())
    searched = {kind for shape in PASS_SHAPES.values() for kind in shape.kinds}
    assert searched <= mapped


def test_the_committed_words_give_every_pass_an_english_word_and_no_abbreviation() -> None:
    words = load_kind_words()
    assert isinstance(words, KindWords)
    for family, shape in PASS_SHAPES.items():
        assert any(words.words(kind, "en") for kind in shape.kinds), family
    assert words.words("PRIVATE_FOUNDATION", "tr")[0] == "vakıf"
    assert words.words("PRIVATE_FOUNDATION", "de")[0] == "Stiftung"
    assert "co." not in words.words("EMPLOYER", "en")
    # The committed corrections: the word Azerbaijani foundations use leads,
    # and the Kazakh word for "exchange" is gone.
    assert words.words("PRIVATE_FOUNDATION", "az")[0] == "fond"
    assert words.words("DIASPORA_AFFINITY", "tr")[0] == "dernek"
    assert "Айырбас" not in words.words("PRIVATE_FOUNDATION", "kk")
    assert words.words("POLITICAL_FOUNDATION", "en-gb") == words.words(
        "POLITICAL_FOUNDATION", "en"
    )


class _Parser:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        parsed = AngleSet(angles=[
            GeneratedAngle(
                angle=kind,
                query=f"Vakfımız yüksek lisans öğrencilerine burs vermektedir ({kind} {n}).",
                brave_terms=f'intitle:vakfı "burs" {kind.lower()}{n}',
            )
            for kind in ANGLE_KINDS for n in range(3)
        ])
        return SimpleNamespace(output_parsed=parsed, output=[])


@pytest.mark.django_db
def test_the_committed_words_reach_the_generator_s_prompt_as_given() -> None:
    """The real producer through the real consumer: the file `build_kind_words`
    wrote is what `generate_angles` hands the model, word for word."""
    cache.clear()
    words = load_kind_words()
    assert words is not None
    parser = _Parser()
    outcome = generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr", "zz"),
        vocabulary=words, parser=parser, now=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert outcome == {"tr": "written", "zz": "no_vocabulary"}
    (call,) = parser.calls
    data = call["input"][1]["content"]
    assert "- PRIVATE_FOUNDATION" in data and "vakıf" in data
    # Turkish has no word for a party foundation on Wikidata: the kind is
    # left out of the prompt rather than given a model's own translation.
    assert "POLITICAL_FOUNDATION" not in data
