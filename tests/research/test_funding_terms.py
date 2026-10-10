import pytest

from apps.research.funding_terms import funding_terms


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
])
def test_a_funding_section_in_every_page_language_is_kept(line):
    assert funding_terms().search(line)


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
