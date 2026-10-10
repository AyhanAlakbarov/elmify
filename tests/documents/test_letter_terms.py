import pytest

from apps.documents.letter_terms import (
    TERMS,
    detect_language,
    figures_on_line,
    normalise_numerals,
    numbers_on_line,
)


def test_every_seeded_language_has_a_document_word_and_a_unit_word() -> None:
    assert set(TERMS) == {"en", "de", "fr", "nl", "it", "es", "pt", "ru", "tr", "zh", "ja", "ko"}
    for code, row in TERMS.items():
        assert row.document, code
        assert row.unit, code


def test_the_pages_own_lang_attribute_wins() -> None:
    """The CMS states it; nothing we infer beats what the publisher declared."""
    assert detect_language("Ceci est une page.", html_lang="de-DE") == "de"
    assert detect_language("", html_lang="PT-br") == "pt"


def test_an_unseeded_lang_attribute_is_not_invented_into_a_neighbour() -> None:
    assert detect_language("valami magyarul", html_lang="hu") == ""


def test_an_absurd_lang_attribute_is_not_logged_in_full(caplog) -> None:
    """An attacker-controlled <html lang> must never reach the log verbatim.

    `declared` is bounded only by the page-body size cap upstream, not by
    anything in this function, so the warning itself must bound what it
    prints -- a raw %r of the full value is a log-flooding vector on every
    catalog read.
    """
    absurd = "x" * 5_000
    with caplog.at_level("WARNING"):
        assert detect_language("", html_lang=absurd) == ""
    messages = [record.getMessage() for record in caplog.records]
    assert messages, "expected at least the unseeded-language warning"
    for message in messages:
        assert absurd not in message
        assert len(message) < 200


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("학업계획서를 제출하십시오", "ko"),
        ("志望理由書を提出してください", "ja"),
        ("请提交个人陈述和读书计划", "zh"),
    ],
)
def test_script_decides_the_cjk_languages(text, expected) -> None:
    """Kana marks Japanese even among Han; Hangul marks Korean; Han alone is Chinese."""
    assert detect_language(text) == expected


def test_stopwords_decide_a_latin_page_with_no_lang_attribute() -> None:
    french = "Vous devez joindre une lettre de motivation dans le dossier de candidature."
    german = "Sie müssen ein Motivationsschreiben mit der Bewerbung für das Studium einreichen."
    assert detect_language(french) == "fr"
    assert detect_language(german) == "de"


def test_a_page_that_matches_nothing_is_unknown_not_english() -> None:
    """Unknown falls back to labels only and is logged (spec §3); it never guesses en."""
    assert detect_language("1234 5678 9012") == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("٥٠٠ كلمة", "500 كلمة"),
        ("五百字", "500字"),
        ("500 words", "500 words"),
        ("１０００", "1000"),
    ],
)
def test_numerals_normalise_across_scripts(raw, expected) -> None:
    assert normalise_numerals(raw) == expected


@pytest.mark.parametrize(
    ("line", "number"),
    [
        # Measured live 2026-09-25: each of these caps was dropped as "not on the
        # page" because it is written as a word or grouped with a space.
        ("Approximately one A4 page in the language of instruction", 1),  # ETH
        ("eine schriftliche Begründung von maximal zwei DIN-A4-Seiten", 2),  # TUM
        ("rédigé en français ou, à défaut, en anglais, sur une ou deux pages.", 2),  # Eiffel
        ("Votre lettre de motivation doit aborder en maximum 1 000 mots", 1000),  # Sciences Po
        ("no more than 1\u202f500 words", 1500),
        ("en fazla iki sayfa", 2),
        ("не более двух страниц", 2),
    ],
)
def test_a_count_written_as_a_word_or_space_grouped_is_on_the_line(line, number) -> None:
    assert number in numbers_on_line(line)


@pytest.mark.parametrize(
    ("line", "number"),
    [
        # A number word far from any length unit verifies nothing: "one of the
        # documents" must never stand in for a one-page cap a reading invented.
        ("One of the documents is a motivation letter of 500 words.", 1),
        # Joining a space-grouped figure never hides the figures it joined: the
        # real 500 still verifies, and 2500 is only on the line as printed.
        ("Part 2 500 words maximum", 500),
    ],
)
def test_number_verification_stays_strict(line, number) -> None:
    on_line = numbers_on_line(line)
    if number == 1:
        assert 1 not in on_line
    else:
        assert number in on_line and 2 in on_line


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # Measured live 2026-09-25 (TUM, ETH, Sciences Po): written as a word, or
        # space-grouped, and each lost its cap.
        ("eine schriftliche Begründung von maximal zwei DIN-A4-Seiten", [(2, "seiten")]),
        ("Approximately one A4 page in the language of instruction", [(1, "page")]),
        # Fix round 1, finding 1: a part of a space-grouped number is never
        # offered as its own figure. Plausibility bands do not reliably catch
        # this -- 500 is a plausible word count on its own, unlike the 1 in
        # the pre-fix "1 000 mots" case.
        ("Votre lettre de motivation doit aborder en maximum 1 000 mots", [(1000, "mots")]),
        ("maximal 1 500 mots", [(1500, "mots")]),
        ("не более 1 500 слов", [(1500, "слов")]),
        # A number word far from any unit is no figure at all.
        ("One of the documents is a motivation letter of 500 words.", [(500, "words")]),
        # A range: both figures, each with the unit.
        ("The letter should be 300–500 words.", [(300, "words"), (500, "words")]),
        ("at most 3,500 characters (approximately 500 words)",
         [(3500, "characters"), (500, "words")]),
        # A year is offered with no unit: whether it is a limit is the page's to say.
        ("Letters for the 2027 intake may not exceed 800 words.", [(2027, ""), (800, "words")]),
        # A dot before exactly three digits is a thousands group (Kassel's floor)...
        ("mindestens 2.800 Zeichen", [(2800, "zeichen")]),
        # ...and one or two digits after a comma or dot are a decimal.
        ("maximal 1,5 Seiten", [(1.5, "seiten")]),
        # A CJK unit runs into the next word; a figure after CJK text is still found.
        ("不超过800字以内", [(800, "字")]),
    ],
)
def test_figures_carry_the_unit_printed_beside_them(line, expected) -> None:
    assert [(f.number, f.unit) for f in figures_on_line(line)] == expected


def test_a_figure_glued_to_a_letter_is_a_model_name_not_a_count() -> None:
    """The 4 in "A4" was a candidate limit under the old digit finder; it is none here."""
    assert all(f.number != 4 for f in figures_on_line("one A4 page, DIN-A4 format"))


def test_a_figures_span_indexes_the_normalised_line() -> None:
    line = "mindestens 2.800 Zeichen"
    (figure,) = figures_on_line(line)
    assert normalise_numerals(line)[figure.span[0] : figure.span[1]] == "2.800"


# <!-- fix round 1, finding 4 -->
def test_a_unit_does_not_cross_an_unrelated_figure() -> None:
    """"500 words" is a different figure's own unit than "2027" -- crossing
    over an intervening number to reach a unit is only for a stated range or
    list, never for two unrelated numbers a sentence happens to print near
    each other."""
    assert [(f.number, f.unit) for f in figures_on_line("In 2027 500 words max")] == [
        (2027, ""), (500, "words"),
    ]


def test_a_range_dash_or_range_word_still_shares_the_unit_across_the_figures() -> None:
    assert [(f.number, f.unit) for f in figures_on_line("300-500 words")] == [
        (300, "words"), (500, "words"),
    ]
    assert [(f.number, f.unit) for f in figures_on_line("300 to 500 words")] == [
        (300, "words"), (500, "words"),
    ]


def test_a_date_is_never_offered_as_a_figure() -> None:
    """"15.10.2026" is a date, not a 15.1-page decimal or a bare 2026-page cap --
    neither reading is a figure a limit could be built from. Only the real "2
    pages" remains."""
    assert [(f.number, f.unit) for f in figures_on_line(
        "Deadline 15.10.2026, max 2 pages"
    )] == [(2, "pages")]


# <!-- fix round 1, finding 5 -->
def test_a_cyrillic_or_greek_prefix_is_also_not_a_count() -> None:
    """The lookbehind was Latin-only, so "А4" (Cyrillic А) offered a 4 exactly
    like the Latin "A4" case should have refused."""
    assert [(f.number, f.unit) for f in figures_on_line("А4 2 страницы")] == [(2, "страницы")]
    assert all(f.number != 4 for f in figures_on_line("Σ4 2 pages"))
