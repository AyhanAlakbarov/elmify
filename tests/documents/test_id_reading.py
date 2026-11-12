# tests/documents/test_id_reading.py
"""Spec 2026-10-12 §5.2: what a passport read proves, one test per rule."""

from datetime import date

import pytest

from apps.documents.id_reading import NotRead, read_id
from tests.documents.id_fixtures import field, passport, result

TODAY = date(2026, 10, 12)


#: The fixtures' holder: with no known name nothing is proven (owner_unknown).
OWNER = ("Nərmin Əliyeva",)


def _read(azure, known_names=OWNER):
    values = read_id(azure, known_names=list(known_names), threshold=0.95, today=TODAY)
    return {v.key: v for v in values}


def test_a_clean_passport_proves_its_strip_values_and_its_confident_page_values():
    got = _read(passport())
    for key in ("id_document.number", "identity.date_of_birth", "id_document.expiry_date"):
        assert got[key].proven and got[key].why == "check_digit"
    assert got["identity.date_of_birth"].value == "1998-03-14"
    assert got["identity.sex"].proven and got["identity.sex"].why == "strip_agrees"
    assert got["identity.citizenship"].value == "Azerbaijan" and got["identity.citizenship"].proven
    assert got["identity.surname"].value == "ƏLIYEVA" and got["identity.surname"].proven
    place = got["identity.place_of_birth"]
    assert place.proven and place.why == "confident"
    assert got["id_document.document_type"].value == "passport"
    assert got["id_document.issuing_country"].value == "Azerbaijan"


def test_a_page_disagreeing_with_the_strip_is_doubtful():
    got = _read(passport(fields={"DateOfBirth": field("1998-03-15", kind="date")}))
    assert not got["identity.date_of_birth"].proven
    assert got["identity.date_of_birth"].why == "strip_disagrees"
    assert got["identity.date_of_birth"].value == "1998-03-15"  # the printed form is shown


def test_sex_is_never_proven_by_the_strip_alone():
    """No check digit covers it: an OCR slip in the strip's sex position leaves the
    composite valid, so only agreement with the page proves it."""
    got = _read(passport(fields={"Sex": field("M")}))
    assert not got["identity.sex"].proven and got["identity.sex"].why == "strip_disagrees"


def test_a_broken_composite_proves_nothing_from_the_strip():
    azure = passport()
    strip = azure.documents[0].fields["MachineReadableZone"]
    broken = strip.content[:-1] + ("1" if strip.content[-1] != "1" else "2")
    azure.documents[0].fields["MachineReadableZone"] = strip.model_copy(update={"content": broken})
    got = _read(azure)
    strip_backed = ("id_document.number", "identity.date_of_birth", "id_document.expiry_date",
                    "identity.sex", "identity.surname", "identity.given_names",
                    "identity.citizenship", "id_document.document_type",
                    "id_document.issuing_country")
    assert _unproven(got, *strip_backed)


def test_no_strip_leaves_strip_values_doubtful():
    azure = result({"FirstName": field("NƏRMIN"), "LastName": field("ALIYEVA"),
                    "DateOfBirth": field("1998-03-14", kind="date")})
    got = _read(azure)
    assert not got["identity.date_of_birth"].proven
    assert got["identity.date_of_birth"].why == "no_strip"


def test_a_low_confidence_place_of_birth_is_doubtful():
    azure = passport(fields={"PlaceOfBirth": field("BAKU", confidence=0.80)})
    got = _read(azure)
    assert not got["identity.place_of_birth"].proven
    assert got["identity.place_of_birth"].why == "low_confidence"


def test_low_word_confidence_makes_a_confident_field_doubtful():
    got = _read(passport(word_confidence=0.6))
    assert not got["identity.place_of_birth"].proven


def test_a_stateless_document_never_proves_a_citizenship():
    got = _read(passport(strip_args={"nationality": "XXA"},
                         fields={"Nationality": field("XXA", kind="countryRegion")}))
    assert not got["identity.citizenship"].proven
    assert got["identity.citizenship"].why == "no_citizenship"


def test_someone_elses_passport_proves_nothing():
    got = _read(passport(), known_names=["Rauf Hüseynov"])
    assert not any(v.proven for v in got.values())
    assert {v.why for v in got.values()} == {"owner_mismatch"}


def test_the_students_own_passport_matches_across_spellings():
    got = _read(passport(), known_names=["Nərmin Əliyeva"])
    assert got["id_document.number"].proven


def test_not_an_id_document_and_no_data_page():
    with pytest.raises(NotRead) as wrong:
        read_id(result({}, doc_type="invoice"), known_names=[], threshold=0.95, today=TODAY)
    assert wrong.value.code == "not_an_id_document"
    empty = result({}).model_copy(update={"documents": ()})
    with pytest.raises(NotRead) as none:
        read_id(empty, known_names=[], threshold=0.95, today=TODAY)
    assert none.value.code == "no_data_page"


def test_a_fathers_passport_with_the_same_surname_proves_nothing():
    got = _read(passport(fields={"FirstName": field("RAUF")}, strip_args={"given": "RAUF"}),
                known_names=["Nərmin Əliyeva"])
    assert not any(v.proven for v in got.values())
    assert {v.why for v in got.values()} == {"owner_mismatch"}


def test_a_cv_spelled_differently_still_matches():
    got = _read(passport(), known_names=["Narmin Aliyeva"])
    assert got["id_document.number"].proven


def _unproven(got, *keys):
    return all(not got[k].proven for k in keys)


def test_ownership_needs_the_given_name_and_a_surname():
    # no printed or strip given name to compare: a surname alone is not enough
    azure = passport(fields={"FirstName": field("")})
    azure.documents[0].fields.pop("FirstName")
    assert not _read(azure, known_names=["Rauf Hüseynov"])["id_document.number"].proven
    # a father named in the middle of a patronymic name
    father = passport(fields={"FirstName": field("RAUF"), "LastName": field("ƏLIYEV")},
                      strip_args={"given": "RAUF", "surname": "ALIYEV"})
    assert not _read(father, known_names=["Nərmin Rauf qızı Əliyeva"])["id_document.number"].proven
    # a namesake by surname only, and a similar-looking given name
    other = passport(fields={"FirstName": field("HƏSƏN"), "LastName": field("ƏLIYEV")},
                     strip_args={"given": "HASAN", "surname": "ALIYEV"})
    assert not _read(other, known_names=["Ali Hasanov"])["id_document.number"].proven


@pytest.mark.parametrize("name", ["Nərmin Əliyeva", "Narmin Aliyeva", "Əliyeva Nərmin"])
def test_the_students_name_in_any_spelling_or_order_matches(name):
    assert _read(passport(), known_names=[name])["id_document.number"].proven


@pytest.mark.parametrize("key,value,kind", [
    ("DateOfBirth", "2098-03-14", "date"), ("DateOfBirth", "1898-03-14", "date"),
    ("DateOfExpiration", "2131-05-19", "date"),
])
def test_an_implausible_date_is_never_proven(key, value, kind):
    yymmdd = value[2:4] + value[5:7] + value[8:10]
    arg = {"DateOfBirth": "birth", "DateOfExpiration": "expiry"}[key]
    got = _read(passport(fields={key: field(value, kind=kind)}, strip_args={arg: yymmdd}))
    name = {"DateOfBirth": "identity.date_of_birth",
            "DateOfExpiration": "id_document.expiry_date"}[key]
    assert not got[name].proven and got[name].why == "implausible"
    assert got[name].value == value


def test_a_cut_given_name_field_does_not_excuse_a_longer_surname():
    long_given = "NARMIN<ELMIRA<GULNARA<KAMALA<AYTAN"
    azure = passport(fields={"LastName": field("ƏLIYEVAXYZ")},
                     strip_args={"given": long_given.replace("<", " ")})
    assert not _read(azure)["identity.surname"].proven


def test_a_name_disagreeing_with_the_strip_is_doubtful():
    got = _read(passport(fields={"LastName": field("HÜSEYNOV")}),
                known_names=["Nərmin Hüseynov"])  # the owner, so the strip rule decides
    assert not got["identity.surname"].proven and got["identity.surname"].why == "strip_disagrees"


def test_a_nationality_disagreeing_with_the_strip_is_doubtful():
    got = _read(passport(fields={"Nationality": field("TUR", kind="countryRegion")}))
    assert not got["identity.citizenship"].proven
    assert got["identity.citizenship"].why == "strip_disagrees"


def test_a_padded_document_number_is_proven():
    got = _read(passport(fields={"DocumentNumber": field("C0123456")},
                         strip_args={"number": "C0123456"}))
    assert got["id_document.number"].proven and got["id_document.number"].why == "check_digit"


def test_sex_outside_the_closed_list_is_never_proven():
    got = _read(passport(fields={"Sex": field("Q")}, strip_args={"sex": "Q"}))
    assert not got["identity.sex"].proven


def test_an_unparseable_printed_date_falls_back_to_the_strip_unproven():
    got = _read(passport(fields={"DateOfBirth": field("14/03/98")}))
    assert got["identity.date_of_birth"].value == "1998-03-14"
    assert not got["identity.date_of_birth"].proven
    assert got["identity.date_of_birth"].why == "low_confidence"


def test_the_document_with_a_sound_strip_wins():
    bad = passport(strip_args={"number": "C01X00T47"})
    good = passport()
    broken = bad.documents[0].fields["MachineReadableZone"]
    bad.documents[0].fields["MachineReadableZone"] = broken.model_copy(
        update={"content": broken.content[:-1] + ("1" if broken.content[-1] != "1" else "2")})
    both = good.model_copy(update={"documents": (bad.documents[0], good.documents[0])})
    assert _read(both)["id_document.number"].proven


def test_an_overlong_value_is_never_proven():
    got = _read(passport(fields={"PlaceOfBirth": field("B" * 250)}))
    assert not got["identity.place_of_birth"].proven


def test_a_td1_id_card_end_to_end():
    from tests.documents.id_fixtures import td1
    printed = {
        "LastName": field("ƏLIYEVA"), "FirstName": field("NƏRMIN"),
        "DocumentNumber": field("AZE123456"), "DateOfBirth": field("1998-03-14", kind="date"),
        "DateOfExpiration": field("2031-05-19", kind="date"), "Sex": field("F"),
        "Nationality": field("AZE", kind="countryRegion"),
    }
    got = _read(result(printed, doc_type="idDocument.nationalIdentityCard", strip=td1()))
    for key in ("id_document.number", "identity.date_of_birth", "id_document.expiry_date",
                "identity.sex", "identity.citizenship", "identity.surname",
                "identity.given_names", "id_document.document_type"):
        assert got[key].proven, (key, got[key])


@pytest.mark.parametrize("known,printed_given,printed_surname,strip_given,strip_surname", [
    ("Kamilə Əliyeva", "KAMIL", "ƏLIYEV", "KAMIL", "ALIYEV"),
    ("Nərmin Əliyeva", "NƏRMINƏ", "ƏLIYEVA", "NARMINA", "ALIYEVA"),
    ("Rauf", "NƏRMIN", "ƏLIYEVA", "NARMIN", "ALIYEVA"),
    # the word that matched the given name never also matches the surname
    ("Marko Marković", "MARKO", "MARKOV", "MARKO", "MARKOV"),
    ("Marković Marko", "MARKO", "MARKOV", "MARKO", "MARKOV"),
    ("Ana Jovanović", "ANA", "ANNA", "ANA", "ANNA"),
    # a Cyrillic letter never vanishes: ә is Ə, а stays a letter
    ("Kamil\u04d9 Əliyeva", "KAMIL", "ƏLIYEV", "KAMIL", "ALIYEV"),
    ("Samir\u04d9 Həsənova", "SAMIR", "HƏSƏNOV", "SAMIR", "HASANOV"),
    ("Nərmin\u04d9 Əliyeva", "NƏRMIN", "ƏLIYEVA", "NARMIN", "ALIYEVA"),
    ("Ruslan\u0430 Ivanova", "RUSLAN", "IVANOV", "RUSLAN", "IVANOV"),
    ("Kamil Əliyev", "KAMIL\u04d8", "ƏLIYEVA", "KAMILA", "ALIYEVA"),
])
def test_siblings_and_other_given_names_do_not_pass(known, printed_given, printed_surname,
                                                     strip_given, strip_surname):
    azure = passport(fields={"FirstName": field(printed_given), "LastName": field(printed_surname)},
                     strip_args={"given": strip_given, "surname": strip_surname})
    assert not _read(azure, known_names=[known])["id_document.number"].proven


@pytest.mark.parametrize("known", [
    ["Əliyeva Nərmin Rauf qızı"], ["Nərmin Rauf qızı Əliyeva"], ["Nərmin"], ["Nərmin", "  "],
    ["  ", "Nərmin Əliyeva"],
])
def test_official_order_patronymics_and_one_word_names_match(known):
    assert _read(passport(), known_names=known)["id_document.number"].proven


def test_a_blank_known_name_is_ignored_entirely():
    assert not _read(passport(), known_names=["Rauf", "  "])["id_document.number"].proven


@pytest.mark.parametrize("known", [[], ["  "]], ids=["none", "blank"])
def test_no_known_name_leaves_every_value_doubtful(known):
    """Final review, item 7: an account made without a name (manage.py
    create_student) skipped the ownership check, so the first passport uploaded --
    anyone's -- was proven."""
    got = _read(passport(), known_names=known)
    assert {(v.proven, v.why) for v in got.values()} == {(False, "owner_unknown")}
    from apps.documents.fact_labels import WHY_TEXT

    assert "add your name to your account" in WHY_TEXT["owner_unknown"]


def test_strip_sex_x_is_accepted():
    ok = _read(passport(fields={"Sex": field("X")}, strip_args={"sex": "X"}))
    assert ok["identity.sex"].proven
    bad = _read(passport(fields={"Sex": field("F")}, strip_args={"sex": "X"}))
    assert not bad["identity.sex"].proven


def _own(given, surname, strip_given=None, strip_surname=None):
    return passport(fields={"FirstName": field(given), "LastName": field(surname)},
                    strip_args={"given": strip_given or given, "surname": strip_surname or surname})


def test_given_names_that_differ_by_a_vowel_are_different_people():
    got = _read(_own("EMIL", "ƏLIYEV", strip_surname="ALIYEV"), known_names=["Amil Əliyev"])
    assert {v.why for v in got.values()} == {"owner_mismatch"}
    got = _read(_own("ÜMID", "ƏLIYEV", "UMID", "ALIYEV"), known_names=["Umid Aliyev"])
    assert got["id_document.number"].proven


@pytest.mark.parametrize("known,given,surname", [
    ("Aigul Asan kyzy", "AIGUL", "TOKTOGULOVA"),
    ("Nərmin Rauf qızı", "NƏRMIN", "HÜSEYNOVA"),
])
def test_a_collapsed_multiword_name_still_checks_the_surname(known, given, surname):
    azure = _own(given, surname, given.replace("Ə", "A"), surname.replace("Ü", "U"))
    assert not _read(azure, known_names=[known])["id_document.number"].proven


@pytest.mark.parametrize("known,given,surname,strip_given,strip_surname", [
    ("Nərmin", "NƏRMIN", "ƏLIYEVA", "NARMIN", "ALIYEVA"),
    ("Əliyeva Nərmin Raufovna", "NƏRMIN", "ƏLIYEVA", "NARMIN", "ALIYEVA"),
    ("Ivanov Ivan Petrovich", "IVAN", "IVANOV", "IVAN", "IVANOV"),
    ("Shevchenko Taras Hryhorovych", "TARAS", "SHEVCHENKO", "TARAS", "SHEVCHENKO"),
    ("Ilyina Anna Ilyinichna", "ANNA", "ILYINA", "ANNA", "ILYINA"),
    ("Ana Jovanović", "ANA", "JOVANOVIĆ", "ANA", "JOVANOVIC"),
    ("Ana Jovanovic", "ANA", "JOVANOVIĆ", "ANA", "JOVANOVIC"),
    ("Jovanović Ana", "ANA", "JOVANOVIĆ", "ANA", "JOVANOVIC"),
    # Balkan -ović/-ević and two-word -ovich names are surnames, never patronymics
    ("Marko Petrović", "MARKO", "PETROVIĆ", "MARKO", "PETROVIC"),
    ("Novak Đoković", "NOVAK", "ĐOKOVIĆ", "NOVAK", "DJOKOVIC"),
    ("Roman Abramovich", "ROMAN", "ABRAMOVICH", "ROMAN", "ABRAMOVICH"),
    ("Ales Lukashevich", "ALES", "LUKASHEVICH", "ALES", "LUKASHEVICH"),
    ("Lukasz Nowak", "ŁUKASZ", "NOWAK", "LUKASZ", "NOWAK"),
    ("Juergen Mueller", "JÜRGEN", "MÜLLER", "JUERGEN", "MUELLER"),
    # a first word is never a patronymic (Croatian Ivna)
    ("Ivna Marija Horvat", "IVNA", "HORVAT", "IVNA", "HORVAT"),
    ("Aliyeva Leyla Rauf gizi", "LEYLA", "ƏLIYEVA", "LEYLA", "ALIYEVA"),
    ("G\u02bbofur Karimov", "GOFUR", "KARIMOV", "GOFUR", "KARIMOV"),
])
def test_one_word_names_and_russian_patronymics_match(known, given, surname, strip_given,
                                                      strip_surname):
    azure = _own(given, surname, strip_given, strip_surname)
    assert _read(azure, known_names=[known])["id_document.number"].proven


@pytest.mark.parametrize("known,strip_given,strip_surname", [
    ("Marko Petrović", "MARKO", "PETROVIC"),
    ("Novak Đoković", "NOVAK", "DJOKOVIC"),
    ("Roman Abramovich", "ROMAN", "ABRAMOVICH"),
    ("Ales Lukashevich", "ALES", "LUKASHEVICH"),
    ("Jürgen Müller", "JUERGEN", "MUELLER"),
    ("Søren Hansen", "SOEREN", "HANSEN"),
])
def test_a_strip_without_printed_names_matches_its_icao_spelling(known, strip_given,
                                                                  strip_surname):
    azure = passport(strip_args={"given": strip_given, "surname": strip_surname})
    azure.documents[0].fields.pop("FirstName")
    azure.documents[0].fields.pop("LastName")
    assert _read(azure, known_names=[known])["id_document.number"].proven


def test_no_given_name_and_no_strip_is_a_mismatch():
    azure = result({"LastName": field("ƏLIYEVA"), "PlaceOfBirth": field("BAKU")})
    got = _read(azure, known_names=["Rauf Hüseynov"])
    assert got["identity.place_of_birth"].why == "owner_mismatch"


@pytest.mark.parametrize("known,given,surname,strip_given,strip_surname,owned", [
    (["Marko Marković", "Marko Markovic"], "MARKO", "MARKOV", "MARKO", "MARKOV", False),
    (["Ana Jovanović", "Jovanović Ana"], "ANA", "ANNA", "ANA", "ANNA", False),
    (["Osman Krasniqi", "Osman Krasniqi"], "OSMAN", "OSMANI", "OSMAN", "OSMANI", False),
    (["Marko", "Marko Marković"], "MARKO", "MARKOV", "MARKO", "MARKOV", False),
    (["Rauf", "Nərmin Əliyeva"], "RAUF", "ƏLIYEV", "RAUF", "ALIYEV", False),
    (["Nərmin Əliyeva", "Nana"], "NANA", "ƏLIYEVA", "NANA", "ALIYEVA", False),
    (["Nərmin Əliyeva", "Narmin Aliyeva"], "NƏRMIN", "ƏLIYEVA", "NARMIN", "ALIYEVA", True),
])
def test_given_name_and_surname_come_from_one_known_name(known, given, surname, strip_given,
                                                         strip_surname, owned):
    azure = _own(given, surname, strip_given, strip_surname)
    assert _read(azure, known_names=known)["id_document.number"].proven is owned


def test_passport_with_mismatched_birth_date_marks_owner_mismatch():
    values = read_id(
        passport(),
        known_names=list(OWNER),
        known_birth_date="2000-01-01",
        threshold=0.95,
        today=TODAY,
    )
    got = {v.key: v for v in values}
    assert got["identity.surname"].why == "owner_mismatch"
    assert not got["identity.surname"].proven
    assert not got["id_document.number"].proven


def test_multi_schwa_azerbaijani_ascii_surnames_match_owner():
    from apps.documents.id_reading import owner_matches_document_text, owner_matches_full_name

    assert owner_matches_full_name("Leyla Memmedzade", ["Leyla Mammadzada"]) is True
    assert owner_matches_full_name("Orkhan Hesenov", ["Orkhan Hasanov"]) is True
    assert owner_matches_document_text(
        "Candidate Name: MEMMEDZADE LEYLA", ["Leyla Mammadzada"]
    ) is True


@pytest.mark.django_db
def test_known_owner_names_falls_back_to_unconfirmed_student_statement_when_account_unnamed(
    agency_a, membership_a
):
    from apps.documents.id_reading import known_owner_names
    from apps.documents.models import VerifiedFact
    from apps.tenancy.context import tenant_scope

    membership_a.user.first_name, membership_a.user.last_name = "", ""
    membership_a.user.save()
    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Narmin Aliyeva"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:cv",
            confirmed_by=None,
            confirmed_at=None,
            created_by=membership_a,
        )
        assert known_owner_names(membership_a) == ["Narmin Aliyeva"]
        assert known_owner_names(membership_a, exclude_ref="upload:cv") == []


