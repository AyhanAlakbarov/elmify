import csv
from decimal import Decimal
from pathlib import Path

import pytest

from apps.funding.regions import REGIONS
from apps.research.candidates.who import find_levels, find_places, find_requirements

DOCS = Path(__file__).resolve().parents[3] / "docs" / "research"


def codes(line):
    return {p.code for p in find_places(line)}


def test_countries_by_their_names_in_the_page_language():
    assert codes("Azərbaycan Respublikasının vətəndaşları müraciət edə bilər") == {"AZ"}
    assert codes("студенты из Турции и Казахстана") == {"TR", "KZ"}
    assert codes("Students from Niger and Nigeria") == {"NE", "NG"}


def test_demonyms_and_common_names_from_the_alias_table():
    assert codes("Türk vatandaşı olmak") == {"TR"}
    assert codes("T.C. vatandaşları başvurabilir") == {"TR"}
    assert codes("open to Turkish and Kazakh citizens") == {"TR", "KZ"}
    assert codes("граждане Республики Корея и азербайджанские студенты") == {"KR", "AZ"}
    assert codes("Students from Turkey, the UK and the USA") == {"TR", "GB", "US"}
    assert codes("tell us about you") == set()


def test_regions_and_unknown_groups():
    places = find_places("Citizens of the European Union or of developing countries")
    assert ("EU", "region") in {(p.code, p.kind) for p in places}
    assert ("developing countries", "unknown_group") in {(p.text.casefold(), p.kind)
                                                         for p in places}
    assert [(p.code, p.kind) for p in find_places("Open to non-EU students only")] == [
        (None, "unknown_group")]
    assert codes("Le jury a eu lieu en mai") == set()
    assert codes("граждане Европейского союза") == {"EU"}
    assert codes("Avropa İttifaqına üzv ölkələr") == {"EU"}


def test_foreign_nationals_are_an_unknown_group():
    for line in ("Прием иностранных граждан", "xarici vətəndaşlar üçün",
                 "Yabancı uyruklu öğrenciler", "Open to foreign nationals"):
        assert [p.kind for p in find_places(line)] == ["unknown_group"], line


def test_ordinary_words_are_not_places():
    assert find_places("Mali destek programı") == []
    assert codes("Mali'den gelen öğrenciler") == {"ML"}
    assert find_places("children of staff") == []
    assert find_places("belge") == []
    assert find_places("Gerekli belgeler") == []
    assert find_places("того же года") == []
    assert codes("Hong Kong residents") == {"HK"}


def test_an_institution_named_after_a_place_still_yields_the_place():
    # the reader's eligible_pN question decides whether students of that institution may apply
    assert codes("Azərbaycan Dövlət Aqrar Universitetinə daxil olanlar") == {"AZ"}


def levels(line):
    return [found.level for found in find_levels(line)]


def test_levels_including_postdoc():
    assert levels("Yurt Dışı Doktora Sonrası Araştırma Bursu") == ["postdoc"]
    assert levels("yüksek lisans ve doktora öğrencileri") == ["master", "phd"]
    assert levels("Учитесь в магистратуре или на 3–4 курсе бакалавриата") == [
        "master", "bachelor"]
    assert levels("EMBO postdoctoral fellowships") == ["postdoc"]
    assert levels("석사과정 및 박사과정") == ["master", "phd"]
    assert levels("CALL FOR APPLICATIONS - BA/BSC, MA/MSC") == [
        "bachelor", "bachelor", "master", "master"]
    assert levels("Lisansüstü Burs Programları") == ["postgraduate"]
    assert levels("development-oriented postgraduate study programmes") == ["postgraduate"]


def test_words_that_contain_a_level_are_not_levels():
    assert levels("Masterclass on Mastercard payments") == []
    assert levels("promotion of the programme") == []
    assert levels("a valid driving licence") == []


def test_requirements():
    kinds = [r.kind for r in find_requirements(
        "IELTS 6.5 or TOEFL iBT 90; B2 level; GPA 3.0/4.0; under 35")]
    assert kinds == ["language_test", "language_test", "cefr", "grade", "age"]
    assert [r.kind for r in find_requirements("minimum 71 bal")] == ["grade"]
    assert [r.age_max for r in find_requirements("35 yaşdan çox olmayan")] == [35]
    assert find_requirements("Room A1 and B2 building") == []


def test_requirement_values():
    (r,) = find_requirements("English B2")
    assert (r.kind, r.cefr) == ("cefr", "B2")
    (r,) = find_requirements("GPA 3.0/4.0")
    assert (r.score, r.scale) == (Decimal("3.0"), Decimal("4.0"))
    (r,) = find_requirements("не старше 35 лет")
    assert r.age_max == 35
    (r,) = find_requirements("under 35")
    assert r.age_max == 34
    (r,) = find_requirements("TOPIK 3급")
    assert (r.test, r.score) == ("TOPIK", Decimal(3))
    (r,) = find_requirements("HSK 4")
    assert (r.test, r.score) == ("HSK", Decimal(4))
    (r,) = find_requirements("YDS 55")
    assert (r.test, r.score) == ("YDS", Decimal(55))
    (r,) = find_requirements("YÖKDİL 60")
    assert r.test == "YÖKDİL"
    (r,) = find_requirements("GPA of at least 3.0")
    assert r.score == Decimal("3.0")


def test_every_region_name_row_names_a_known_region():
    with (DOCS / "region-names.csv").open(encoding="utf-8") as handle:
        assert {row["region"] for row in csv.DictReader(handle)} <= set(REGIONS)


def test_every_alias_row_names_an_alpha_2_code():
    with (DOCS / "place-aliases.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert all(len(row["code"]) == 2 and row["code"].isupper() for row in rows)


def test_longer_names_resolve_to_the_right_country():
    assert codes("Democratic People's Republic of Korea") == {"KP"}
    assert codes("Democratic Republic of the Congo") == {"CD"}
    assert codes("students from Northern Ireland") == {"GB"}
    assert codes("Guinea Bissau") == {"GW"}
    assert codes("Republic of Korea") == {"KR"}
    for line in ("Latin American students", "British Columbia residents", "New Jersey"):
        assert codes(line) == set(), line


def test_an_excluded_region_is_one_unknown_group():
    for line in ("Open to non-EU/EEA students", "non-EEA nationals", "non-OECD countries"):
        assert [(p.code, p.kind) for p in find_places(line)] == [(None, "unknown_group")], line
    assert find_places("a non-binding offer") == []


def test_turkish_language_names_are_not_places():
    for line in ("İtalyanca dil belgesi", "Hollandaca", "Portekizce bilenler", "Ukraynaca"):
        assert codes(line) == set(), line
    assert codes("France and Greece") == {"FR", "GR"}


def test_real_mali_and_togo_are_places():
    assert codes("Students from Mali and Niger") == {"ML", "NE"}
    assert codes("Citizens of Mali") == {"ML"}
    assert codes("из Того и Бенина") == {"TG", "BJ"}
    assert codes("Mali'den gelen") == {"ML"}
    assert find_places("mali destek") == []


def test_ages_need_an_age_cue():
    for line in ("see pages 10-20", "page 12-14", "managed 10-20 people", "wages 15-20",
                 "scores below 60 are not accepted", "under 30 ECTS credits"):
        assert [r for r in find_requirements(line) if r.kind == "age"] == [], line
    assert [r.age_max for r in find_requirements("under the age of 35")] == [34]
    (r,) = find_requirements("aged 18-35")
    assert (r.age_min, r.age_max) == (18, 35)


def test_common_test_and_age_phrasings():
    for line, test, score in (("IELTS Academic 6.5", "IELTS", "6.5"),
                              ("IELTS overall 6.5", "IELTS", "6.5"),
                              ("IELTS minimum 6.5", "IELTS", "6.5"),
                              ("PTE Academic 58", "PTE", "58"),
                              ("TOEFL iBT® 90", "TOEFL iBT", "90"),
                              ("Duolingo English Test 110", "Duolingo", "110")):
        (r,) = find_requirements(line)
        assert (r.test, r.score) == (test, Decimal(score)), line
    assert [r.age_max for r in find_requirements("до 35 лет")] == [34]
    assert [r.age_max for r in find_requirements("в возрасте до 35 лет")] == [34]
    assert [r.age_max for r in find_requirements("до 35 лет включительно")] == [35]
    (r,) = find_requirements("в возрасте от 18 до 35 лет")
    assert (r.age_min, r.age_max) == (18, 34)
    (r,) = find_requirements("between the ages of 18 and 35")
    assert (r.age_min, r.age_max) == (18, 35)


def test_level_and_cefr_word_boundaries():
    for line in ("graph databases", "Joseph Dupont", "photograph description",
                 "bachelorette party", "magistrate", "Magistrates' Court"):
        assert levels(line) == [], line
    assert levels("PhD") == levels("Ph.D.") == ["phd"]
    assert levels("bachelor's") == ["bachelor"]
    assert levels("магистратура") == ["master"]
    assert levels("magistr") == ["master"]
    for line in ("Trust building B2", "Brussels office B1", "Türkiye, Blok B1"):
        assert find_requirements(line) == [], line
    for line in ("English B2", "Türkçe B2"):
        assert [r.kind for r in find_requirements(line)] == ["cefr"], line


def test_round_two_new_guinea_and_stray_numbers():
    assert codes("Papua New Guinea") == {"PG"}
    assert codes("students from Papua New Guinea") == {"PG"}
    for line in ("Latin American students", "British Columbia residents", "New Jersey"):
        assert codes(line) == set(), line
    for line in ("IELTS in the last 2 years", "IELTS taken within 2 years"):
        assert [r for r in find_requirements(line) if r.kind == "language_test"] == [], line
    (r,) = find_requirements("IELTS score of 6.5")
    assert (r.test, r.score) == ("IELTS", Decimal("6.5"))


def test_a_parenthesised_gap_word_before_the_score():
    (r,) = find_requirements("IELTS (Academic) 6.5")
    assert (r.test, r.score) == ("IELTS", Decimal("6.5"))
    (r,) = find_requirements("TOEFL (iBT) 90")
    assert (r.test, r.score) == ("TOEFL", Decimal(90))
    assert find_requirements("IELTS in the last 2 years") == []


@pytest.mark.parametrize("line", [
    "Applicants with an average below 70.", "GPA below 60;", "No IELTS band below 60.",
    "Grades below 50.", "scores below 60 are not accepted"])
def test_a_grade_threshold_is_no_age(line):
    assert [r for r in find_requirements(line) if r.kind == "age"] == []


@pytest.mark.parametrize("line, age_max", [
    ("under 35,", 34), ("under 35", 34), ("under the age of 35", 34),
    ("below the age of 30", 29)])
def test_under_with_punctuation_is_still_an_age(line, age_max):
    assert [r.age_max for r in find_requirements(line) if r.kind == "age"] == [age_max]


def test_chinese_taipei_is_taiwan_and_chinese_students_are_unchanged():
    assert codes("Athletes from Chinese Taipei") == {"TW"}
    assert "TW" not in codes("Chinese students may apply")
