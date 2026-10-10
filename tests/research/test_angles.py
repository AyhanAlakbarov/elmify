"""The angle generator and store (spec 6.3, the page-voiced rule; 6.7)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.db import IntegrityError, transaction

from apps.research.angles import (
    PASS_SHAPES,
    AngleSet,
    GeneratedAngle,
    active_angles,
    cycle_label,
    generate_angles,
    steering_angle,
)
from apps.research.models import ANGLE_KINDS, SWEEP_FAMILIES, SweepAngle

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 9, 25, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_limits():
    cache.clear()


class _Vocab:
    def __init__(self, words: dict[tuple[str, str], tuple[str, ...]]) -> None:
        self._words = words

    def words(self, kind: str, language: str) -> tuple[str, ...]:
        return self._words.get((kind, language), ())


class _Parser:
    def __init__(self, parsed: AngleSet | None) -> None:
        self.parsed = parsed
        self.calls: list[dict] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed, output=[])


def _set(samples: int = 3) -> AngleSet:
    return AngleSet(angles=[
        GeneratedAngle(
            angle=kind,
            query=f"Vakfımız yüksek lisans öğrencilerine burs vermektedir ({kind} {n}).",
            brave_terms=f'intitle:vakfı "burs" {kind.lower()}{n}',
        )
        for kind in ANGLE_KINDS for n in range(samples)
    ])


_TR_VOCAB = _Vocab({("PRIVATE_FOUNDATION", "tr"): ("vakıf", "vakfı")})


def test_the_pass_shapes_are_exactly_the_sweep_families() -> None:
    assert set(PASS_SHAPES) == set(SWEEP_FAMILIES)


def test_every_angle_kind_has_a_definition_in_batch_order() -> None:
    # A test, not a module-level assert: Bandit (B101) runs over apps/ in CI.
    from apps.research.angles import ANGLE_DEFINITIONS

    assert tuple(ANGLE_DEFINITIONS) == ANGLE_KINDS


def test_a_generated_set_is_stored_as_versioned_rows() -> None:
    parser = _Parser(_set())
    outcome = generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=parser, now=NOW,
    )
    assert outcome == {"tr": "written"}
    rows = SweepAngle.objects.filter(country_code="TR", language="tr")
    assert rows.count() == len(ANGLE_KINDS) * PASS_SHAPES["PRIVATE_FOUNDATION"].samples
    assert set(rows.values_list("version", flat=True)) == {1}
    assert set(rows.values_list("cycle", flat=True)) == {"2026-2027"}

    generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=_Parser(_set()), now=NOW, regenerate=True,
    )
    assert set(rows.values_list("version", flat=True)) == {1, 2}
    assert {a.version for a in active_angles("TR", "PRIVATE_FOUNDATION", ("tr",))} == {2}


def test_a_language_the_vocabulary_cannot_supply_is_not_generated() -> None:
    """Lever 3: kind words come from the per-language vocabulary, never
    translated by the generator -- so no vocabulary means no call."""
    parser = _Parser(_set())
    outcome = generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr", "en"),
        vocabulary=_TR_VOCAB, parser=parser, now=NOW,
    )
    assert outcome == {"tr": "written", "en": "no_vocabulary"}
    assert len(parser.calls) == 1


def test_the_kind_words_travel_as_data_and_no_student_field_can() -> None:
    parser = _Parser(_set())
    generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=parser, now=NOW,
    )
    call = parser.calls[0]
    user = call["input"][1]["content"]
    assert "DATA" in call["input"][0]["content"]
    assert "vakıf" in user and "2026-2027" in user and "TR" in user
    assert call["store"] is False
    assert call["max_output_tokens"] <= 3000
    assert call["text_format"] is AngleSet


def test_an_exa_sentence_carrying_a_search_operator_is_dropped() -> None:
    """Lever 7: nothing negative in the text -- an embedding cannot subtract,
    and operators belong in brave_terms."""
    bad = AngleSet(angles=[
        GeneratedAngle(angle="APPLICATION", query="burs başvurusu -haber site:tev.org.tr",
                       brave_terms='"burs başvurusu" -haber'),
        GeneratedAngle(angle="FAQ", query="Sıkça sorulan sorular: burs başvurusu nasıl yapılır?",
                       brave_terms='"sıkça sorulan sorular" burs'),
    ])
    generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=_Parser(bad), now=NOW,
    )
    assert list(SweepAngle.objects.values_list("angle", flat=True)) == ["FAQ"]


def test_double_hyphen_heading_separator_is_not_a_search_operator() -> None:
    """A sentence using ` -- ` as heading separator (the page-voiced style
    from the module docstring) must not be dropped as an operator. True
    operators like `-word` must still be caught."""
    mixed = AngleSet(angles=[
        GeneratedAngle(
            angle="ABOUT",
            query="Vakfımız her yil burs vermektedir -- Burs Basvurusu.",
            brave_terms='vakfı burs başvurusu',
        ),
        GeneratedAngle(
            angle="APPLICATION",
            query="Unsere Stiftung foerdert Studenten -- Bewerbung.",
            brave_terms='stiftung bewerbung',
        ),
        GeneratedAngle(
            angle="ELIGIBILITY",
            query="Requirements page – Eligibility criteria and deadlines",
            brave_terms='eligibility requirements',
        ),
        GeneratedAngle(
            angle="SEASON",
            query="2026 scholarship call -old-news inurl:bewerbung",
            brave_terms='-old-news inurl:bewerbung',
        ),
    ])
    generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=_Parser(mixed), now=NOW,
    )
    # Only SEASON is dropped because it carries -old-news operator.
    # ABOUT, APPLICATION, ELIGIBILITY are stored because -- and – are not operators.
    stored_angles = list(
        SweepAngle.objects.order_by("angle").values_list("angle", flat=True)
    )
    assert stored_angles == ["ABOUT", "APPLICATION", "ELIGIBILITY"]


def test_brave_terms_over_fifty_words_are_dropped() -> None:
    long_terms = " ".join(["burs"] * 51)
    s = AngleSet(angles=[GeneratedAngle(angle="FAQ", query="Sıkça sorulan sorular: burs.",
                                        brave_terms=long_terms)])
    generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=_Parser(s), now=NOW,
    )
    assert SweepAngle.objects.count() == 0


def test_a_language_whose_every_angle_was_unusable_says_so() -> None:
    only_bad = AngleSet(angles=[
        GeneratedAngle(angle="APPLICATION", query="Vakfımız burs vermektedir site:x",
                       brave_terms="vakfı burs"),
    ])
    outcome = generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=_Parser(only_bad), now=NOW,
    )
    assert outcome == {"tr": "no_usable"}
    assert SweepAngle.objects.count() == 0


def test_a_duplicate_query_in_one_generation_is_stored_once() -> None:
    """A duplicate sample earns no credit; it only spends an ask."""
    same = "Vakfımız yüksek lisans öğrencilerine burs vermektedir."
    dup = AngleSet(angles=[
        GeneratedAngle(angle="APPLICATION", query=same, brave_terms="vakfı burs"),
        GeneratedAngle(angle="APPLICATION", query=same, brave_terms="vakfı burs başvuru"),
        GeneratedAngle(angle="FAQ", query=same, brave_terms="vakfı sss"),
        GeneratedAngle(angle="APPLICATION", query="Burs başvurusu nasıl yapılır?",
                       brave_terms="burs başvuru"),
    ])
    generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=_Parser(dup), now=NOW,
    )
    rows = list(SweepAngle.objects.order_by("sample").values_list("angle", "query"))
    assert rows == [("APPLICATION", same), ("APPLICATION", "Burs başvurusu nasıl yapılır?")]


def test_a_refused_reading_writes_nothing_and_says_so() -> None:
    outcome = generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=_Parser(None), now=NOW,
    )
    assert outcome == {"tr": "no_answer"}
    assert SweepAngle.objects.count() == 0


def test_generation_is_rate_limited_per_country_and_family(settings) -> None:
    settings.SWEEP_ANGLE_GENERATIONS_PER_DAY = 1
    kwargs = dict(country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
                  vocabulary=_TR_VOCAB, now=NOW)
    assert generate_angles(parser=_Parser(_set()), **kwargs) == {"tr": "written"}
    assert generate_angles(parser=_Parser(_set()), regenerate=True, **kwargs) == {
        "tr": "rate_limited"
    }


def test_a_language_with_this_cycles_set_is_skipped_unless_regenerated(settings) -> None:
    """The daily limit is spent on missing languages, not on rewriting a set."""
    settings.SWEEP_ANGLE_GENERATIONS_PER_DAY = 2
    kwargs = dict(country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
                  vocabulary=_TR_VOCAB, now=NOW)
    assert generate_angles(parser=_Parser(_set()), **kwargs) == {"tr": "written"}
    parser = _Parser(_set())
    assert generate_angles(parser=parser, **kwargs) == {"tr": "exists"}
    assert parser.calls == []
    # "exists" spent nothing: the one remaining generation is still there.
    assert generate_angles(parser=_Parser(_set()), regenerate=True, **kwargs) == {
        "tr": "written"
    }


def test_last_cycles_set_is_not_this_cycles() -> None:
    kwargs = dict(country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
                  vocabulary=_TR_VOCAB)
    generate_angles(parser=_Parser(_set()), now=datetime(2025, 9, 25, tzinfo=UTC), **kwargs)
    assert generate_angles(parser=_Parser(_set()), now=NOW, **kwargs) == {"tr": "written"}


def test_the_steering_interim_is_not_a_set_that_blocks_generation() -> None:
    steering_angle("TR", now=NOW)
    outcome = generate_angles(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr",),
        vocabulary=_TR_VOCAB, parser=_Parser(_set()), now=NOW,
    )
    assert outcome == {"tr": "written"}


def test_the_steering_row_is_one_labelled_angle() -> None:
    row = steering_angle("TR", now=NOW)
    assert row.written_by == "STEERING"
    assert row.family == "PRIVATE_FOUNDATION" and row.language == "tr"
    assert "burs" in row.query
    assert SweepAngle.objects.count() == 1


def test_the_cycle_turns_in_september() -> None:
    assert cycle_label(datetime(2026, 9, 1, tzinfo=UTC)) == "2026-2027"
    assert cycle_label(datetime(2026, 8, 31, tzinfo=UTC)) == "2025-2026"


# --- diaspora passes are keyed (host country, home language) (decision 37) --

_DIASPORA_VOCAB = _Vocab({
    ("DIASPORA_AFFINITY", "az"): ("icma",),
    ("DIASPORA_AFFINITY", "tr"): ("dernek",),
    ("DIASPORA_AFFINITY", "en"): ("association",),
})


def _diaspora(home: str, parser: _Parser) -> dict[str, str]:
    return generate_angles(
        country_code="DE", family="AFFINITY_OR_DIASPORA", languages=(home, "en"),
        home_language=home, vocabulary=_DIASPORA_VOCAB, parser=parser, now=NOW,
    )


def test_two_home_languages_in_one_host_never_share_an_angle_english_included() -> None:
    assert _diaspora("az", _Parser(_set())) == {"az": "written", "en": "written"}
    assert _diaspora("tr", _Parser(_set())) == {"tr": "written", "en": "written"}
    az = active_angles("DE", "AFFINITY_OR_DIASPORA", ("az", "en"), home_language="az")
    tr = active_angles("DE", "AFFINITY_OR_DIASPORA", ("tr", "en"), home_language="tr")
    assert {a.pk for a in az}.isdisjoint({a.pk for a in tr})
    assert {a.language for a in az} == {"az", "en"} and {a.language for a in tr} == {"tr", "en"}
    # Each home language's English set is its own version 1, not the other's v2.
    assert {a.version for a in az + tr} == {1}
    assert {a.home_language for a in az} == {"az"} and {a.home_language for a in tr} == {"tr"}


def test_an_english_diaspora_angle_is_generated_naming_its_home_language() -> None:
    parser = _Parser(_set())
    _diaspora("az", parser)
    english = parser.calls[1]["input"][1]["content"]
    assert "language: en" in english
    assert "home language: az" in english and "living in DE" in english


def test_a_home_language_outside_a_diaspora_pass_is_refused_by_the_database() -> None:
    fields = dict(
        country_code="DE", language="en", angle="FAQ", sample=0, version=1,
        cycle="2026-2027", query="q", written_by="t",
    )
    for family, home in (("PRIVATE_FOUNDATION", "az"), ("AFFINITY_OR_DIASPORA", "")):
        with pytest.raises(IntegrityError), transaction.atomic():
            SweepAngle.objects.create(family=family, home_language=home, **fields)
