import pytest

from apps.research.angles import STEERING
from apps.research.funding_terms import FUNDING_TERMS_FILE, funding_terms


@pytest.mark.parametrize("line", [
    "Scholarships for international students",
    "Təqaüd proqramı: ayda 200 manat",
    "Burs başvuru koşulları",
    "Bursiyerlere aylık ödeme yapılır",
    "Размер стипендии — 25 000 рублей",
    "Бесплатное обучение в магистратуре",
    "Təhsil dövlət hesabına ödənilir",
    "Öğrenim ücretsizdir ve sağlık sigortası sağlanır",
    "Стипендія для іноземців",
    "Ösztöndíj összege havonta",
    "외국인 장학금 안내",
    "研究生奖学金",
    "Bourse d'excellence",
    "Logement et assurance",
    "Studiengebühren und Förderung",
    "Becas para estudiantes",
    "Bolsa de estudo e isenção de propina",
    "Studiebeurs en collegegeld",
    "Apuraha ja lukukausimaksu",
    "Υποτροφίες και απαλλαγή από δίδακτρα",
    "Bursă de studiu și scutire de taxă de școlarizare",
    "სტიპენდია და სწავლის საფასური",
    "Կրթաթոշակ և ուսման վարձի զեղչ",
    "Beasiswa dan biaya pendidikan",
    "Học bổng và miễn giảm học phí",
    "منحة دراسية وإعفاء من الرسوم الدراسية",
    "अंतर्राष्ट्रीय छात्रों के लिए छात्रवृत्ति",
    "طلبا کے لیے وظیفہ اور فیس معافی",
])
def test_a_funding_section_in_every_page_language_is_kept(line):
    assert funding_terms().search(line)


def test_every_steering_language_has_funding_terms():
    import csv
    with FUNDING_TERMS_FILE.open(encoding="utf-8", newline="") as handle:
        langs_in_csv = {row["language"] for row in csv.DictReader(handle)}
    steering_langs = {s.language for s in STEERING.values()}
    assert steering_langs <= langs_in_csv


@pytest.mark.parametrize("line", [
    "because the course is popular",
    "Campus map and parking",
])
def test_word_bounded_terms_do_not_fire_inside_other_words(line):
    assert not funding_terms().search(line)


def test_the_reader_uses_the_table():
    from apps.research.funding_reader import _FUNDING_TERMS
    assert _FUNDING_TERMS.search("Təqaüd")


@pytest.mark.parametrize("line", [
    "scholarship", "bursary", "fellowship", "fund", "funding", "funded", "financial aid",
    "financial support", "tuition", "fee", "fees", "waiver", "discount", "stipend",
    "assistantship", "grant", "award", "loan", "housing", "accommodation", "insurance",
    "travel", "relocation", "internship", "placement", "co-op", "paid position",
    "paid research", "Paid Research Assistant", "paid internship", "paid placement",
    "beca", "bourse", "borsa",
])
def test_every_word_of_the_old_english_regex_still_matches(line):
    assert funding_terms().search(line)


@pytest.mark.parametrize("line", ["Stypendium dla cudzoziemców", "Stypendia naukowe"])
def test_polish_stypend_matches_every_inflection(line):
    assert funding_terms().search(line)
