import pytest

from apps.research.engine_eval.evidence import amounts, evidence


@pytest.mark.parametrize("text", [
    "Applications close on 15 January 2027.",
    "Müraciətlər 1 noyabr 2026-cı il tarixdən başlayır.",
    "Başvurular 10 Ocak 2027 tarihine kadar alınacaktır.",
    "Приём заявок до 15 февраля 2027 года.",
    "Deadline: 15.01.2027",
    "Studies start in September 2027.",
    "접수기간: 3월 2일 ~ 3월 20일",
    "Приказ от 31.03.2011г. № 12",
    "Son başvuru: 2026 Aralık",
    "Results in late March or early April.",
    "2026年3月下旬",
])
def test_dates_in_four_languages_count_as_date_evidence(text):
    assert evidence("application_date", text)


def test_a_line_without_a_date_is_not_date_evidence():
    assert not evidence("application_date", "Applications are reviewed by a committee.")


def test_specialty_codes_are_not_dates():
    assert not evidence("application_date", "Направления 37.03.01 и 38.03.04")


@pytest.mark.parametrize("text", [
    "Master's and PhD scholarships", "magistratura səviyyəsi üzrə", "Yüksek Lisans Bursları",
    "обучение в магистратуре и аспирантуре", "bachelor programmes"])
def test_level_words(text):
    assert evidence("level_rule", text)


@pytest.mark.parametrize("text", [
    "Citizens of Azerbaijan may apply", "Azərbaycan vətəndaşları üçün",
    "uluslararası öğrenciler başvurabilir", "иностранные граждане", "international students"])
def test_nationality_words(text):
    assert evidence("nationality_rule", text)


@pytest.mark.parametrize("text", [
    "GPA of at least 3.0", "IELTS 6.5", "ÜOMG 81+", "yaş sınırı 30", "не старше 35 лет"])
def test_requirement_thresholds(text):
    assert evidence("requirement_rule", text)


def test_amounts_find_currency_spans():
    assert amounts("a monthly stipend of 43,000 HUF (approx. 110 EUR)") == ["43,000 HUF", "110 EUR"]
    assert evidence("money_to_student", "a monthly stipend of 43,000 HUF")
    assert evidence("costs_covered", "anything")  # no gate for this question


def test_iso_codes_are_amounts_before_or_after_the_number():
    assert amounts("Stipend 1,000 USD") == ["1,000 USD"]
    assert amounts("USD 1,000 per month") == ["USD 1,000"]
    assert amounts("a grant of 500 TRY and 20 AZN") == ["500 TRY", "20 AZN"]


def test_a_lowercase_code_is_not_an_amount():
    assert amounts("eur 100") == []
    assert amounts("1000 huf") == []
    assert not evidence("money_to_student", "eur 100")


def test_bare_iso_codes_stay_out_of_the_shared_csv():
    # card_fields turns every single-currency row into a case-folded pattern, so a bare code there
    # would make currencies_in() confirm "eur 100"; amounts() adds the codes itself, uppercase only.
    from apps.research.card_fields import evidence_rows
    assert not [r for r in evidence_rows() if r.form in ("HUF", "EUR", "USD")]
