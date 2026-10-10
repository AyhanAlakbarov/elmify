import csv
import unicodedata

import pytest

from apps.research.candidates import Line, find_all
from apps.research.candidates.headers import DATE_HEADER_CUES_FILE, ROLES, header_cue


@pytest.mark.parametrize(("header", "role"), [
    ("신청시기", "application_window"),
    ("선발시기", "selection"),
    ("Son müraciət tarixi", "deadline"),
    ("Müraciətlərin qəbulu", "application_window"),
    ("Son başvuru tarihi", "deadline"),
    ("Выплата стипендии", "funding_period"),
    ("Приём заявок", "application_window"),
    ("Application deadline", "deadline"),
    ("Results announced", "results"),
    ("Başvuru sonuçları", "results"),
    ("Müraciət nəticələri", "results"),
    ("Qəbul nəticələri", "results"),
    ("Selection results", "results"),
    ("Interview results", "results"),
    ("신청결과", "results"),
    ("접수결과", "results"),
    ("선발결과", "results"),
    ("Qəbulun son günü", "deadline"),
    ("Qəbulun sonu", "deadline"),
    ("Başvuru bitiş", "deadline"),
    ("Başvuru kapanış", "deadline"),
    ("Application closes", "deadline"),
    ("Last day to apply", "deadline"),
    ("Окончание приема заявок", "deadline"),
    ("접수 마감", "deadline"),
    ("접수마감", "deadline"),
    ("신청마감", "deadline"),
    ("신청 마감", "deadline"),
    ("신청 마감일", "deadline"),
    ("신청 발표", "results"),
])
def test_a_column_header_names_its_dates_role(header, role):
    assert header_cue(header) == role


def test_a_header_with_no_cue_names_nothing():
    assert header_cue("Programme") is None
    assert header_cue("Документы") is None  # "до" is a whole word, not the start of this one


def test_every_cue_row_names_a_known_role():
    with DATE_HEADER_CUES_FILE.open(encoding="utf-8") as handle:
        assert {row["role"] for row in csv.DictReader(handle)} <= set(ROLES)


def test_a_cell_is_read_with_its_column_header():
    c = find_all([Line("3월", header="신청시기 (2026년 3월)"), "Deadline: 15 January 2027"])
    found = [(f.line, f.from_header) for f in c.dates.values()]
    assert found == [(0, False), (0, True), (1, False)]
    assert c.state()["dates"]["d2"]["from_header"] is True
    assert header_cue("신청시기 (2026년 3월)") == "application_window"


def test_two_longest_cues_of_equal_length_and_different_roles_name_nothing():
    assert header_cue("신청") == "application_window"
    assert header_cue("선발") == "selection"
    assert header_cue("신청 선발") is None


@pytest.mark.parametrize("header", ["신청시기", "Приём заявок", "Başvuru sonuçları"])
def test_a_decomposed_header_reads_like_its_composed_form(header):
    nfd = unicodedata.normalize("NFD", header)
    assert nfd != header
    assert header_cue(nfd) == header_cue(header) is not None
