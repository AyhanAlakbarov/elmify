from apps.research.candidates.dates import find_relative_dates

FULBRIGHT = ("Fulbright operates on a yearly application cycle, which generally opens "
             "approximately 15 months before the anticipated start of the grant with a deadline "
             "approximately 11 or 12 months before the grant's start date.")


def test_fulbright_gives_two_relative_dates():
    opening, deadline = find_relative_dates(FULBRIGHT)
    assert (opening.low, opening.high, opening.unit, opening.direction) == (
        15, 15, "months", "before")
    assert opening.approximately and opening.anchor == "the anticipated start of the grant"
    assert (deadline.low, deadline.high, deadline.approximately) == (11, 12, True)
    assert deadline.anchor == "the grant's start date"


def test_russian_turkish_and_azerbaijani_forms():
    (ru,) = find_relative_dates("Заявки принимаются за 6 месяцев до начала обучения.")
    assert (ru.low, ru.unit, ru.direction, ru.anchor) == (6, "months", "before", "начала обучения")
    (tr,) = find_relative_dates("Başvurular programın başlangıcından yaklaşık 3 ay önce kapanır.")
    assert (tr.low, tr.unit, tr.direction, tr.approximately) == (3, "months", "before", True)
    (az,) = find_relative_dates("Müraciətlər təhsilin başlanmasından 2 ay əvvəl bitir.")
    assert (az.low, az.unit, az.direction) == (2, "months", "before")


def test_a_duration_is_not_a_relative_date():
    assert find_relative_dates("The scholarship lasts 12 months.") == []


def test_the_turkic_anchor_is_the_noun_phrase_before_the_ablative():
    (az,) = find_relative_dates("Müraciətlər təhsilin başlanmasından 2 ay əvvəl bitir.")
    assert az.anchor == "təhsilin başlanması" and az.text.startswith("təhsilin")


def test_a_longer_number_is_never_read_by_its_tail():
    assert find_relative_dates("about 1.5 years before the start") == []
    assert find_relative_dates("1,5 years before the start") == []
    assert find_relative_dates("stipend 1000 days before the start") == []
