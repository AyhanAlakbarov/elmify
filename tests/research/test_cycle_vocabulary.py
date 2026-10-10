"""The cycle vocabulary is data (spec principle 7); these pin how it is read."""
import datetime as dt

import pytest

from apps.research import cycle_vocabulary as vocab


@pytest.fixture
def csv_file(tmp_path, monkeypatch):
    path = tmp_path / "cycle-vocabulary.csv"
    path.write_text(
        "language,role,term,source,verified_on\n"
        "en,cycle,deadline,spec#9.2,2026-09-22\n"
        "de,cycle,bewerbung,spec#9.2,2026-09-22\n"
        "tr,cycle,son tarih,spec#9.2,2026-09-22\n"
        "tr,cycle,başvuru,spec#9.2,2026-09-22\n"
        "en,apply,apply,spec#9.2,2026-09-22\n",
        encoding="utf-8",
    )
    vocab.terms.cache_clear()
    monkeypatch.setattr(vocab, "_CSV", path)
    yield path
    vocab.terms.cache_clear()


def test_a_row_without_a_source_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "bad.csv"
    path.write_text("language,role,term,source,verified_on\nen,cycle,call,,2026-09-22\n")
    vocab.terms.cache_clear()
    monkeypatch.setattr(vocab, "_CSV", path)
    with pytest.raises(ValueError, match="incomplete"):
        vocab.terms()
    vocab.terms.cache_clear()


def test_english_always_joins_the_hosts_languages(csv_file):
    assert vocab.for_languages("cycle", ["de"]) == ("deadline", "bewerbung")


def test_a_host_with_no_recorded_language_gets_every_term(csv_file):
    assert set(vocab.for_languages("cycle", [])) == {
        "deadline", "bewerbung", "son tarih", "başvuru",
    }


def test_path_patterns_carry_an_ascii_fold_and_a_hyphenated_form(csv_file):
    paths = vocab.include_paths(["tr"], today=dt.date(2026, 9, 26))
    assert {"başvuru", "basvuru", "son-tarih"} <= set(paths)


def test_year_tokens_are_the_previous_two_the_current_and_the_next():
    assert vocab.year_tokens(dt.date(2026, 9, 26)) == ("2024", "2025", "2026", "2027")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The Example Fellowship opens soon", True),   # the award's name
        ("Applications for 2027 open in March", True),  # a year token
        ("Our campus has a new library", False),
        ("Call 020261234", False),  # digits inside a number are not a year
        ("Example Fellowships abound", False),  # the name inside a longer word
    ],
)
def test_a_page_reaches_the_reader_only_by_name_or_year(text, expected):
    years = ("2025", "2026", "2027")
    assert vocab.mentions_award(text, name="Example Fellowship", years=years) is expected


@pytest.mark.parametrize(
    ("term", "folded"),
    [("başvuru", "basvuru"), ("müraciət", "muraciet"), ("son qəbul", "son qebul"),
     ("Straße", "Strasse")],
)
def test_folding_transliterates_rather_than_dropping(term, folded):
    """Review of 1a72ace: NFKD + ignore turned müraciət into muracit."""
    assert vocab._fold(term) == folded
