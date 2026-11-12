"""ICAO Doc 9303 specimens (Part 4, TD3; Part 5, TD1) and the failure cases."""

from datetime import date

from apps.documents import mrz

TD3 = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
)
TD1 = (
    "I<UTOD231458907<<<<<<<<<<<<<<<\n"
    "7408122F1204159UTO<<<<<<<<<<<6\n"
    "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"
)


def test_check_digits_of_the_specimens():
    assert mrz.check_digit("L898902C3") == "6"
    assert mrz.check_digit("740812") == "2"
    assert mrz.check_digit("120415") == "9"
    assert mrz.check_digit("D23145890") == "7"


def test_the_td3_specimen_parses_and_every_digit_holds():
    strip = mrz.parse(TD3)
    assert strip is not None and strip.format == "TD3" and strip.composite_ok
    assert (strip.surname, strip.given_names) == ("ERIKSSON", "ANNA MARIA")
    assert (strip.number, strip.birth, strip.expiry, strip.sex) == (
        "L898902C3", "740812", "120415", "F",
    )
    assert strip.nationality == "UTO" and strip.issuing_state == "UTO"
    assert strip.names_truncated is False


def test_the_td1_specimen_parses_and_every_digit_holds():
    strip = mrz.parse(TD1)
    assert strip is not None and strip.format == "TD1" and strip.composite_ok
    assert (strip.number, strip.birth, strip.expiry) == ("D23145890", "740812", "120415")
    assert (strip.surname, strip.given_names) == ("ERIKSSON", "ANNA MARIA")
    assert strip.names_truncated is False


def test_one_changed_digit_fails_its_own_check_and_the_composite():
    broken = TD3.replace("L898902C36", "L898903C36")
    strip = mrz.parse(broken)
    assert strip is not None and strip.number is None and not strip.composite_ok


def test_spaces_and_lowercase_from_ocr_are_tolerated_but_a_wrong_length_is_not():
    assert mrz.parse(TD3.lower().replace("<<<<", "< < < < ")) is not None
    assert mrz.parse(TD3[:-1]) is None
    assert mrz.parse("not a strip") is None


def test_a_document_number_continued_in_optional_data_is_not_proven():
    # A TD1 number longer than 9 characters puts "<" in the check position.
    long_number = TD1.replace("D231458907", "D23145890<", 1)
    strip = mrz.parse(long_number)
    assert strip is not None and strip.number is None


def test_dates_agree_with_the_printed_page_and_resolve_their_century():
    assert mrz.printed_agrees("740812", date(1974, 8, 12))
    assert not mrz.printed_agrees("740812", date(1974, 8, 13))
    today = date(2026, 10, 12)
    assert mrz.date_from_strip("740812", birth=True, today=today) == date(1974, 8, 12)
    assert mrz.date_from_strip("051231", birth=True, today=today) == date(2005, 12, 31)
    assert mrz.date_from_strip("310519", birth=False, today=today) == date(2031, 5, 19)
    assert mrz.date_from_strip("991399", birth=True, today=today) is None


def test_icao_codes_become_english_country_names():
    assert mrz.country_name_for("AZE") == "Azerbaijan"
    assert mrz.country_name_for("D<<") == "Germany"
    assert mrz.country_name_for("GBN") == "United Kingdom"
    assert mrz.country_name_for("UNK") == "Kosovo"
    assert mrz.country_name_for("UTO") is None  # the specimens' fictional state
    assert "XXA" in mrz.NO_CITIZENSHIP and "XXB" in mrz.NO_CITIZENSHIP


def test_printed_names_agree_with_their_strip_forms():
    assert mrz.names_agree("ƏLİYEV", "ALIYEV")
    assert mrz.names_agree("ƏLİYEV", "ELIYEV")
    assert mrz.names_agree("MÜLLER", "MUELLER") and mrz.names_agree("MÜLLER", "MULLER")
    assert mrz.names_agree("ŞAHİN", "SAHIN")
    assert mrz.names_agree("GROß", "GROSS")
    # Truncated strip (strip has truncated the name): printed must START WITH strip
    assert mrz.names_agree("ANNA MARIA LOUISE", "ANNA MARIA LOU", truncated=True)
    assert not mrz.names_agree("ANNA MARIA LOUISE", "ANNA MARIA LOU", truncated=False)
    # Non-truncated (default): printed must match strip EXACTLY
    assert not mrz.names_agree("ANNA", "ANNE")
    assert not mrz.names_agree("ANNA", "")
    # Test prefix vs exact match with truncation
    assert not mrz.names_agree("ANNA", "A")  # prefix without truncated=True
    assert not mrz.names_agree("ERIKSSON", "ERIK")  # prefix without truncated=True
    assert mrz.names_agree("ANNA", "A", truncated=True)  # prefix with truncated=True
    assert mrz.names_agree("ERIKSSON", "ERIK", truncated=True)  # prefix with truncated=True


def test_fold_tokens_match_across_spellings():
    # Each letter's first strip form: Ə -> A, Ü -> UE, Ğ -> G. Both sides of a
    # comparison fold the same way, so the spelling chosen does not matter.
    assert mrz.fold_tokens("Məmmədova-Ağayeva Gülnarə") == {"MAMMADOVA", "AGAYEVA", "GUELNARA"}


def test_parse_rejects_non_string_input():
    assert mrz.parse(None) is None
    assert mrz.parse(123) is None
    assert mrz.parse([]) is None


def test_parse_rejects_invalid_document_codes():
    # Only P, I, A, C as first letter are valid
    invalid_v = TD3.replace("P<UTO", "V<UTO")
    assert mrz.parse(invalid_v) is None


def test_date_field_with_angle_brackets_is_none():
    # A date field that contains "<" is None even if check digit is 0
    # TD1 second line: "7408122F..." -> replace "7408122" (birth + check)
    # with "<<<<<<<" (all angle brackets)
    all_angle_birth = TD1.replace("7408122", "<<<<<<<")
    strip = mrz.parse(all_angle_birth)
    assert strip is not None and strip.birth is None


def test_names_truncated_flag():
    # Full name field (ends with <)
    strip = mrz.parse(TD3)
    assert strip is not None and strip.names_truncated is False
    # Name field that is truncated (no trailing <)
    td3_full = TD3.replace(
        "ERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
        "ERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<A"
    )
    strip = mrz.parse(td3_full)
    assert strip is not None and strip.names_truncated is True


def test_names_agree_with_diacritics_and_alternative_letters():
    # Œ (OE)
    assert mrz.names_agree("ŒUVRE", "OEUVRE")
    # Ð (D or DJ)
    assert mrz.names_agree("ÐURIĆ", "DURIC")
    assert mrz.names_agree("ÐURIĆ", "DJURIC")
    # Apostrophes are dropped
    assert mrz.names_agree("O'BRIEN", "OBRIEN")


def test_names_agree_with_large_character_sets():
    # Test no 64-form cap: ÄÄÄÄÄÄÄÄ with many options
    assert mrz.names_agree("ÄÄÄÄÄÄÄÄ", "AAAAAAAA")
    assert mrz.names_agree("ÄÄÄÄÄÄÄÄ", "AEAEAEAEAEAEAEAE")


def test_same_name_token_ownership_matching():
    # Equal after loose transliteration
    assert mrz.same_name_token("ORKHAN", "ORXAN")
    # Mamedov/Mammadov (Ə -> A, loose match)
    assert mrz.same_name_token("Mamedov", "MAMMADOV")
    # Eliyev/ƏLIYEV (Ə -> A or E)
    assert mrz.same_name_token("Eliyev", "ƏLIYEV")
    # Müller/MUELLER (Ü -> UE)
    assert mrz.same_name_token("Müller", "MUELLER")
    # Non-matching
    assert not mrz.same_name_token("ANNA", "ANNE")
    assert not mrz.same_name_token("RAUF", "NARMIN")
    # Short tokens: equal short tokens match
    assert mrz.same_name_token("AL", "AL")
    # Short tokens: non-equal don't match
    assert not mrz.same_name_token("AL", "AA")


def test_hyphenated_names_match():
    # Hyphen in printed matches space in strip
    assert mrz.names_agree("Məmmədova-Ağayeva", "MAMMADOVA AGAYEVA")
    assert mrz.names_agree("ANNA-MARIA", "ANNA MARIA")
    # Hyphen with spaces
    assert mrz.names_agree("ANNA - MARIA", "ANNA MARIA")


def test_trailing_spaces_in_printed_exact_mode():
    # Trailing spaces in printed should not cause false negatives
    assert mrz.names_agree("ANNA ", "ANNA")
    assert mrz.names_agree("ANNA  ", "ANNA")


def test_curly_apostrophe_dropped():
    # Both straight and curly apostrophes are dropped
    assert mrz.names_agree("O'BRIEN", "OBRIEN")  # straight apostrophe (U+0027)
    assert mrz.names_agree("O’BRIEN", "OBRIEN")  # curly right single quotation mark (U+2019)


def test_dots_and_commas_as_separators():
    # Dots and commas are treated as separators like hyphens and spaces
    assert mrz.names_agree("ST. JOHN", "ST JOHN")
    assert mrz.names_agree("SMITH, JOHN", "SMITH JOHN")


def test_a_ratio_match_needs_near_equal_length():
    assert not mrz.same_name_token("HASAN", "HASANOV")
    assert mrz.same_name_token("MAMEDOV", "MAMMADOV")


def test_icao_separators_and_punctuation():
    assert not mrz.names_agree("ƏLI YEVA", "ALIYEVA")  # a space is a space
    assert mrz.names_agree("Ə.LIYEVA", "ALIYEVA")  # the dot is not represented
    assert mrz.names_agree("ST. JOHN", "ST JOHN")
    assert mrz.names_agree("ANNA-MARIA", "ANNA MARIA")
    assert not mrz.names_agree("ANNA-MARIA", "ANNAMARIA")
    assert mrz.names_agree("O‘BRIEN", "OBRIEN")
    assert mrz.names_agree("O’BRIEN", "OBRIEN")


def test_a_padded_number_is_proven_by_its_digit():
    from tests.documents.id_fixtures import td3

    strip = mrz.parse(td3(number="C0123456"))
    assert strip is not None and strip.number == "C0123456"


def test_given_names_compare_exactly_up_to_spelling():
    assert not mrz.same_given_name("Kamil", "Kamilə")
    assert not mrz.same_given_name("NƏRMINƏ", "Nərmin")
    assert mrz.same_given_name("Nərmin", "NƏRMIN")
    assert mrz.same_given_name("Nermin", "NƏRMIN")
    assert mrz.same_given_name("Orkhan", "ORXAN")
    assert not mrz.same_given_name("RAUF", "NARMIN")


def test_uzbek_okina_is_punctuation():
    assert mrz.names_agree("GʻOFUROV", "GOFUROV")
    assert mrz.names_agree("GʼOFUROV", "GOFUROV")


def test_given_names_on_base_letters_with_schwa_as_a_or_e():
    for a, b in [("EMIL", "AMIL"), ("EMIN", "AMIN"), ("ENAR", "ANAR"), ("RENA", "RANA"),
                 ("ELENA", "ALANA"), ("Kamil", "Kamilə"), ("NƏRMINƏ", "Nərmin")]:
        assert not mrz.same_given_name(a, b), (a, b)
    for a, b in [("Nərmin", "NƏRMIN"), ("Nermin", "NƏRMIN"), ("Narmin", "NƏRMIN"),
                 ("Orkhan", "ORXAN"), ("Umid", "ÜMID"), ("Gulnar", "GÜLNAR"),
                 ("Ulviyya", "ÜLVIYYƏ"), ("Omar", "ÖMƏR"), ("Javid", "CAVID"),
                 ("Jeyhun", "CEYHUN"), ("Sevinj", "SEVINC"), ("Ilkin", "İLKIN"),
                 ("Łukasz", "LUKASZ"), ("Jürgen", "JUERGEN"), ("Søren", "SOEREN"),
                 ("Bjørn", "BJOERN"), ("Åsa", "AASA"), ("Þór", "THOR")]:
        assert mrz.same_given_name(a, b), (a, b)


def test_name_keys_carry_icao_forms_and_base_letters():
    assert {"MUELLER", "MULLER"} <= mrz.name_keys("Müller")
    assert {"DCOKOVIC", "DOKOVIC"} <= mrz.name_keys("Đoković")  # DJ, then J as C
    assert mrz.name_keys("O'Brien") == {"OBRIEN"}
    assert not mrz.same_given_name("Иван", "Пётр")  # no Latin letters: nothing to compare


def test_non_latin_letters_stay_in_the_key():
    assert mrz.name_keys("Kamil\u04d9") == mrz.name_keys("Kamilə")  # Cyrillic ә is Ə
    assert not mrz.same_given_name("Kamil\u04d9", "KAMIL")
    assert not mrz.same_given_name("Ruslan\u0430", "RUSLAN")  # Cyrillic а
    assert mrz.same_given_name("G\u02bbofur", "GOFUR")  # a modifier letter is punctuation


def test_name_keys_are_capped():
    import time

    started = time.perf_counter()
    assert not mrz.same_given_name("Ə" * 30, "A" * 29 + "E")
    assert len(mrz.name_keys("Ə" * 30)) <= 256
    assert time.perf_counter() - started < 0.1
