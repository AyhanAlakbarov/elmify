"""Spec 2026-10-12 §5.3: what a diploma or certificate read proves."""

import pytest

from apps.documents.azure_layout import AzureLayout
from apps.documents.fact_readers import CertificateQuotes, DiplomaQuotes
from apps.documents.id_reading import NotRead
from apps.documents.ocr import Flattened
from apps.documents.text_reading import prove, read_text_document, strip_identifiers


def layout(text, confidence=0.99):
    words, offset = [], 0
    for word in text.split(" "):
        words.append({"content": word, "confidence": confidence,
                      "span": {"offset": offset, "length": len(word)}})
        offset += len(word) + 1
    return AzureLayout.model_validate({"content": text, "pages": [
        {"pageNumber": 1, "width": 1, "height": 1, "unit": "inch", "words": words}]})


CERT = "IELTS Academic Test Date 08/11/2025 Overall Band Score 6.5 Listening 7.0 TRF 25AZ000123"


def cert(**over):
    base = dict(document="certificate", test_name="IELTS", test_variant="Academic",
                test_date="08/11/2025", certificate_number="25AZ000123", overall="6.5",
                listening="7.0", reading=None, writing=None, speaking=None, cefr_level=None)
    return CertificateQuotes(**{**base, **over})


def _by_key(values):
    return {v.key: v for v in values}


def test_two_agreeing_quotes_on_the_page_are_proven_and_normalised():
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [cert(), cert()], layout(CERT), (), 0.95))
    assert got["language.test_name"].value == "IELTS" and got["language.test_name"].proven
    assert got["language.language"].value == "English" and got["language.language"].proven
    assert got["language.test_date"].value == "2025-11-08"  # day-first, never proven
    assert not got["language.test_date"].proven
    assert got["language.test_date"].why == "ambiguous_date"
    assert got["language.test_score"].value == "6.5"
    assert got["language.test_score"].why == "readers_agree"
    assert got["language.score_listening"].value == "7.0"


def test_readers_disagreeing_is_doubtful_with_the_first_readers_value():
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [cert(), cert(overall="7.5")], layout(CERT),
                        (), 0.95))
    assert not got["language.test_score"].proven
    assert got["language.test_score"].why == "readers_disagree"


def test_a_shared_quote_that_is_not_on_the_page_is_doubtful():
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [cert(overall="9.0"), cert(overall="9.0")],
                        layout(CERT), (), 0.95))
    assert got["language.test_score"].why == "not_on_page"


def test_low_word_confidence_is_doubtful():
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [cert(), cert()], layout(CERT, 0.7), (), 0.95))
    assert not any(v.proven for v in got.values())


def test_a_visible_layer_that_disagrees_makes_it_doubtful():
    visible = ("IELTS Academic Test Date 08/11/2025 Overall Band Score 6.0",)
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [cert(), cert()], layout(CERT), visible, 0.95))
    assert got["language.test_score"].why == "text_layer_differs"
    assert got["language.test_name"].proven  # still in the visible layer


def test_an_unknown_test_is_kept_but_never_proven():
    text = "Foo English Test Overall 80"
    got = _by_key(prove("LANGUAGE_CERTIFICATE",
                        [cert(test_name="Foo English Test", overall="80")] * 2,
                        layout(text), (), 0.95))
    assert got["language.test_name"].why == "unknown_test"
    assert "language.language" not in got


DIPLOMA = "Bakı Dövlət Universiteti Bakalavr 30.06.2023 AB 123456"


def diploma(**over):
    base = dict(document="original", institution_original="Bakı Dövlət Universiteti",
                institution_english=None, degree_original="Bakalavr", degree_english=None,
                graduation_date="30.06.2023", diploma_number="AB 123456", grade=None)
    return DiplomaQuotes(**{**base, **over})


def test_an_original_diploma_fills_the_original_keys():
    got = _by_key(prove("DIPLOMA", [diploma(), diploma()], layout(DIPLOMA), (), 0.95))
    assert got["education.institution_original"].proven
    assert got["education.degree_as_awarded"].value == "Bakalavr"
    assert got["education.end_date"].value == "2023-06-30"
    assert got["education.diploma_number"].value == "AB 123456"


def test_a_translation_fills_only_the_english_keys():
    text = "Baku State University Bachelor 30 June 2023"
    answer = diploma(document="translation", institution_original="Baku State University",
                     institution_english="Baku State University", degree_original=None,
                     degree_english="Bachelor", graduation_date="30 June 2023",
                     diploma_number=None)
    got = _by_key(prove("DIPLOMA", [answer, answer], layout(text), (), 0.95))
    assert set(got) == {"education.institution_english", "education.degree_english",
                        "education.end_date"}


def test_readers_disagreeing_on_the_label_makes_every_value_doubtful():
    got = prove("DIPLOMA", [diploma(), diploma(document="bilingual")], layout(DIPLOMA), (), 0.95)
    assert got and not any(v.proven for v in got)


def test_identifiers_are_stripped_from_the_readers_copy_only():
    text = "ALIYEVA NARMIN 14.03.1998 Baku State University named after Heydar Aliyev"
    stripped = strip_identifiers(text, ["Narmin Aliyeva", "1998-03-14"])
    assert "NARMIN" not in stripped and "14.03.1998" not in stripped
    assert "Baku State University" in stripped


def test_a_surname_inside_the_institution_name_degrades_to_doubtful():
    text = "Baku State University named after Heydar Aliyev Bakalavr"
    stripped = strip_identifiers(text, ["Narmin Aliyeva", "Aliyev"])
    quoted = stripped.split(" Bakalavr")[0]  # what a reader quotes from its copy
    answer = diploma(institution_original=quoted, graduation_date=None, diploma_number=None)
    got = _by_key(prove("DIPLOMA", [answer, answer], layout(text), (), 0.95))
    assert got["education.institution_original"].why == "not_on_page"


def test_the_whole_read_sends_pictures_and_the_stripped_text():
    sent = {}

    def flatten(document, content, *, max_pages):
        sent["cap"] = max_pages
        return Flattened(image_pdf=None, pages=1, visible=())

    def analyze(body, *, pages=None, locale=None):
        sent["body"] = body
        return layout(CERT + " ALIYEVA")

    def quotes(kind, text):
        sent["text"] = text
        return [cert(), cert()]

    billed = {"pages": 0}
    values, pages = read_text_document(
        kind="LANGUAGE_CERTIFICATE", document=object(), content=b"\x89PNG",
        identifiers=["Aliyeva"],
        threshold=0.95, cap=2, billed=billed, flatten=flatten, analyze=analyze, quotes=quotes)
    assert sent["cap"] == 2 and sent["body"] == b"\x89PNG" and pages == 1
    assert "ALIYEVA" not in sent["text"] and values
    assert billed == {"pages": 1}


def test_both_readers_saying_other_is_not_a_certificate_still_bills_the_page():
    other = cert(document="other")
    billed = {"pages": 0}
    with pytest.raises(NotRead) as refused:
        read_text_document(
            kind="LANGUAGE_CERTIFICATE", document=object(), content=b"x", identifiers=[],
            threshold=0.95, cap=2, billed=billed,
            flatten=lambda d, c, *, max_pages: Flattened(image_pdf=None, pages=1, visible=()),
            analyze=lambda b, **k: layout("Invoice 42"), quotes=lambda k, t: [other, other])
    assert refused.value.code == "not_a_certificate"
    assert billed == {"pages": 1}  # Azure answered: plan 1 counts it on the FAILED path


def test_an_azure_failure_after_the_call_charges_the_cap(settings):
    """Plan 1's rule (final review, minor 7): the call may have been billed with no
    answer to count from, so the cap is charged, the safe over-count."""
    from apps.documents.ocr_errors import OcrUnavailable

    settings.AZURE_DI_ENDPOINT, settings.AZURE_DI_KEY = "https://azure.test", "k"

    def down(body, **kwargs):
        raise OcrUnavailable("timeout")

    billed = {"pages": 0}
    with pytest.raises(OcrUnavailable):
        read_text_document(
            kind="DIPLOMA", document=object(), content=b"x", identifiers=[], threshold=0.95,
            cap=4, billed=billed,
            flatten=lambda d, c, *, max_pages: Flattened(image_pdf=None, pages=1, visible=()),
            analyze=down, quotes=lambda k, t: [])
    assert billed == {"pages": 4}


def test_a_quote_that_is_only_part_of_a_printed_value_is_not_on_the_page():
    """Both readers quoting "5" must not be found inside the printed "6.5" or "25AZ000123"."""
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [cert(overall="5"), cert(overall="5")],
                        layout(CERT), (), 0.95))
    assert got["language.test_score"].why == "not_on_page"
    assert not got["language.test_score"].proven


def test_a_test_alias_inside_another_word_is_an_unknown_test():
    text = "Accepted September Overall 80"
    got = _by_key(prove("LANGUAGE_CERTIFICATE",
                        [cert(test_name="Accepted September", overall="80")] * 2,
                        layout(text), (), 0.95))
    assert got["language.test_name"].why == "unknown_test"
    assert "language.language" not in got


@pytest.mark.parametrize(("printed", "iso", "proven", "why"), [
    ("25/11/2025", "2025-11-25", True, "readers_agree"),  # 25 > 12: day first
    ("11/25/2025", "2025-11-25", True, "readers_agree"),  # 25 > 12: month first
    ("08/08/2025", "2025-08-08", True, "readers_agree"),  # both orders agree
    ("08/11/2025", "2025-11-08", False, "ambiguous_date"),  # 8 Nov or 11 Aug
])
def test_an_all_numeric_date_is_proven_only_when_unambiguous(printed, iso, proven, why):
    text = f"IELTS Test Date {printed}"
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [cert(test_date=printed)] * 2, layout(text),
                        (), 0.95))
    assert got["language.test_date"].value == iso
    assert got["language.test_date"].proven is proven
    assert got["language.test_date"].why == why


def test_a_month_name_date_is_never_ambiguous():
    text = "IELTS Test Date 08 Nov 2025"
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [cert(test_date="08 Nov 2025")] * 2,
                        layout(text), (), 0.95))
    assert got["language.test_date"].value == "2025-11-08" and got["language.test_date"].proven


def test_an_ambiguous_date_has_a_reason_the_student_can_read():
    from apps.documents.fact_labels import WHY_TEXT

    assert WHY_TEXT["ambiguous_date"] == "The date could be read two ways."


# Fix round 1 (adversarial review): each test is an input that used to prove a wrong value.


def _ielts(text, confidence=None, visible=(), **quotes):
    answer = cert(**{"test_variant": None, "test_date": None, "certificate_number": None,
                     "overall": None, "listening": None, **quotes})
    page = layout(text)
    if confidence:
        words = [w.model_copy(update={"confidence": confidence.get(i, w.confidence)})
                 for i, w in enumerate(page.pages[0].words)]
        page = page.model_copy(update={"pages": (page.pages[0].model_copy(
            update={"words": tuple(words)}),)})
    return _by_key(prove("LANGUAGE_CERTIFICATE", [answer, answer], page, visible, 0.95))


def test_every_occurrence_of_a_quote_must_be_read_confidently():
    # word 6 is the overall's own 7.0; the listening 7.0 (word 2) is read sure
    got = _ielts("IELTS Listening 7.0 Reading 6.0 Overall 7.0", {6: 0.5}, overall="7.0")
    assert not got["language.test_score"].proven
    assert got["language.test_score"].why == "low_confidence"


def test_a_word_wrapped_in_brackets_counts_toward_confidence():
    got = _ielts("IELTS Overall (6.5)", overall="6.5")
    assert got["language.test_score"].proven


@pytest.mark.parametrize(("page", "quote"), [
    ("IELTS Listening 7.0 Overall 6.5", "Listening 7.0 Overall 6.5"),
    ("IELTS Overall 6½", "6½"),
    ("IELTS Overall ٦٫٥", "٦٫٥"),
])
def test_a_score_quote_must_hold_exactly_one_plain_number(page, quote):
    got = _ielts(page, overall=quote)
    assert got["language.test_score"].value == quote  # kept as printed, never dropped
    assert not got["language.test_score"].proven
    assert got["language.test_score"].why == "low_confidence"


def test_a_score_quote_may_carry_label_words():
    got = _ielts("IELTS Overall Band 6.5", overall="Overall Band 6.5")
    assert got["language.test_score"].value == "6.5" and got["language.test_score"].proven


@pytest.mark.parametrize(("printed", "iso", "why"), [
    ("12 Nov 13", "12 Nov 13", "date_unclear"),
    ("08.11.25", "08.11.25", "date_unclear"),
    ("8th November 2025", "2025-11-08", "readers_agree"),
    ("2025/11/08", "2025-11-08", "readers_agree"),
])
def test_a_date_without_a_full_year_is_kept_as_printed_and_doubtful(printed, iso, why):
    got = _ielts(f"IELTS Test Date {printed}", test_date=printed)
    assert got["language.test_date"].value == iso
    assert got["language.test_date"].why == why
    assert got["language.test_date"].proven is (why == "readers_agree")


def test_a_date_is_never_dropped_and_the_reason_reads():
    from apps.documents.fact_labels import WHY_TEXT

    assert WHY_TEXT["date_unclear"] == "We couldn't read this date for sure."


def test_yds_names_no_language():
    got = _ielts("YDS Almanca", test_name="YDS Almanca")
    assert got["language.test_name"].value == "YDS" and got["language.test_name"].proven
    assert "language.language" not in got


@pytest.mark.parametrize(("quote", "name"), [
    ("CAE", "Cambridge English C1 Advanced"),
    ("CPE", "Cambridge English C2 Proficiency"),
    ("Cambridge English: Advanced (CAE)", "Cambridge English C1 Advanced"),
    ("Cambridge English: Proficiency", "Cambridge English C2 Proficiency"),
    ("Pre-TOEFL", None),
    ("TOEFL ITP", None),
    ("TOEFL Primary", None),
    ("TOEFL Junior", None),
    ("HSKK", None),
])
def test_test_name_aliases(quote, name):
    got = _ielts(quote, test_name=quote)
    if name is None:
        assert got["language.test_name"].why == "unknown_test"
        assert "language.language" not in got
    else:
        assert got["language.test_name"].value == name
        assert got["language.language"].value == "English"


def test_the_visible_cross_check_counts_occurrences_on_the_same_page():
    """Azure slipped the overall 7.5 to 6.5; the visible layer has 6.5 once, Azure twice."""
    got = _ielts("IELTS Listening 6.5 Overall 6.5", overall="6.5",
                 visible=("IELTS Listening 6.5 Overall 7.5",))
    assert got["language.test_score"].why == "text_layer_differs"
    assert got["language.test_name"].proven


def two_pages(first, second):
    words, offset, pages = [], 0, []
    for number, text in ((1, first), (2, second)):
        words = []
        for word in text.split(" "):
            words.append({"content": word, "confidence": 0.99,
                          "span": {"offset": offset, "length": len(word)}})
            offset += len(word) + 1
        pages.append({"pageNumber": number, "width": 1, "height": 1, "unit": "inch",
                      "words": words})
    return AzureLayout.model_validate({"content": f"{first} {second}", "pages": pages})


def test_the_visible_cross_check_reads_the_page_the_quote_is_on():
    page = two_pages("IELTS Overall 6.5", "Listening 7.0")
    answer = cert(test_variant=None, test_date=None, certificate_number=None, overall="6.5",
                  listening="7.0")
    got = _by_key(prove("LANGUAGE_CERTIFICATE", [answer, answer], page,
                        ("IELTS Overall 7.5", "Listening 7.0 Overall 6.5"), 0.95))
    assert got["language.test_score"].why == "text_layer_differs"  # 6.5 only on page 2
    assert got["language.score_listening"].proven


@pytest.mark.parametrize(("test", "field", "score", "plausible"), [
    ("IELTS", "overall", "9.0", True),
    ("IELTS", "overall", "10.5", False),
    ("IELTS", "overall", "6.3", False),
    ("IELTS", "listening", "7.5", True),
    ("TOEFL iBT", "overall", "110", True),
    ("TOEFL iBT", "overall", "135", False),
    ("TOEFL iBT", "reading", "28", True),
    ("TOEFL iBT", "reading", "31", False),
    ("Duolingo English Test", "overall", "125", True),
    ("Duolingo English Test", "overall", "5", False),
    ("PTE Academic", "overall", "79", True),
    ("PTE Academic", "overall", "95", False),
])
def test_scores_outside_the_tests_range_are_implausible(test, field, score, plausible):
    got = _ielts(f"{test} Score {score}", test_name=test, **{field: score})
    key = "language.test_score" if field == "overall" else f"language.score_{field}"
    assert got[key].proven is plausible
    assert got[key].why == ("readers_agree" if plausible else "implausible")


LEAKS = [
    ("ƏLİYEVA NƏRMİN 14.03.1998", ["Narmin Aliyeva", "1998-03-14"]),
    ("ALİYEVA NARMIN", ["Narmin Aliyeva"]),
    ("Aliyeva Narmin", ["NARMİN ALİYEVA"]),
    ("Date of birth 14 March 1998", ["1998-03-14"]),
    ("Doğum tarihi 14 Mart 1998", ["1998-03-14"]),
    ("Дата рождения 14 марта 1998", ["1998-03-14"]),
    ("DOB March 14, 1998", ["1998-03-14"]),
    ("DOB 03/14/1998", ["1998-03-14"]),
    ("DOB 14.03.98", ["1998-03-14"]),
    ("DOB 14/3/1998", ["1998-03-14"]),
    ("DOB 1998/03/14", ["1998-03-14"]),
    ("DOB 14-03-1998", ["1998-03-14"]),
    ("Passport C 0123 4567", ["C01234567"]),
    ("Passport C-0123-4567", ["C01234567"]),
    ("Li Wei", ["Wei Li"]),
    ("GÖKÇE ÖZTÜRK", ["Gokce Ozturk"]),
    ("Narmin Aliyeva-Smith", ["Narmin Aliyeva-Smith"]),
]


@pytest.mark.parametrize(("text", "identifiers"), LEAKS)
def test_identifiers_never_reach_the_readers(text, identifiers):
    import unicodedata

    for form in (text, unicodedata.normalize("NFD", text)):
        stripped = strip_identifiers(form, identifiers)
        assert not any(ch.isdigit() for ch in stripped), stripped
        assert not any(w in stripped.casefold()
                       for w in ("narmin", "aliyeva", "nərmin", "əliyeva", "wei", "gökçe",
                                 "ozturk", "öztürk", "smith")), stripped


def test_stripping_keeps_the_numbers_the_readers_must_quote():
    text = ("TRF 25AZ000123 Diploma AB 140398 Candidate 1234567XYZ "
            "Name Narmin Aliyeva DOB 14/03/1998 Passport C01234567 Test Date 08/11/2025")
    stripped = strip_identifiers(text, ["Narmin Aliyeva", "1998-03-14", "C01234567", "1234567"])
    for kept in ("25AZ000123", "AB 140398", "1234567XYZ", "08/11/2025"):
        assert kept in stripped
    for gone in ("Narmin", "14/03/1998", "C01234567"):
        assert gone not in stripped


def test_label_disagreement_emits_only_language_neutral_keys():
    answers = [diploma(document="translation", institution_english="Baku State University"),
               diploma(document="original", institution_english="Baku State University")]
    got = prove("DIPLOMA", answers, layout(DIPLOMA + " Baku State University"), (), 0.95)
    assert {v.key for v in got} == {"education.end_date"}
    assert not any(v.proven for v in got)


def test_an_email_is_stripped_whole_never_word_by_word():
    """An address is an exact string: its words are not names, or "baku" in
    student@baku.edu.az would strip "Baku State University"."""
    text = "Baku State University, contact narmin@baku.edu.az"
    stripped = strip_identifiers(text, ["narmin@baku.edu.az"])
    assert stripped == "Baku State University, contact [REDACTED]"


def test_certificate_missing_account_holder_name_marks_owner_mismatch():
    got = _by_key(
        prove(
            "LANGUAGE_CERTIFICATE",
            [cert(), cert()],
            layout(CERT + " Candidate Name: KAMRAN HASANOV"),
            (),
            0.95,
            identifiers=["Narmin Aliyeva", "Nərmin Əliyeva"],
        )
    )
    assert all(not v.proven and v.why == "owner_mismatch" for v in got.values())


def test_certificate_with_transliterated_surname_first_matches_owner():
    got = _by_key(
        prove(
            "LANGUAGE_CERTIFICATE",
            [cert(), cert()],
            layout(CERT + " Candidate Name: ALIYEVA NARMIN"),
            (),
            0.95,
            identifiers=["Nərmin Əliyeva"],
        )
    )
    assert got["language.test_score"].proven

