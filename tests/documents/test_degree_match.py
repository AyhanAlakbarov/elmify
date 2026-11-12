"""Transcript plan 3b Task 7: is a transcript's degree one the student already holds? Decided
only when sure; asked in one tap otherwise. Real-looking names in four languages."""

import pytest
from django.utils import timezone

from apps.documents.degree_match import (
    degree_level,
    institution_key,
    match_record,
    same_degree,
)
from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction


def _fact(institution, degree, end=None, **more):
    return {"institution_original": institution, "degree_as_awarded": degree,
            "end_date": end, **more}


def _record(institution, qualification, completed_on=None, expected_completion=None):
    return {"institution": institution, "qualification": qualification,
            "completed_on": completed_on, "expected_completion": expected_completion}


def test_the_same_university_in_two_languages_is_asked():
    assert same_degree(
        _fact("Baku State University", "BSc Chemistry", "2025-06-30"),
        _record("Bakı Dövlət Universiteti", "Bakalavr", "2025-06-30"),
    ) == "ask"


def test_initials_name_the_same_university():
    assert same_degree(
        _fact("BSU", "BSc", "2025-12-31"),
        _record("Baku State University", "Bachelor of Science", "2025-06-30"),
    ) == "same"


def test_a_bachelors_is_not_a_masters():
    assert same_degree(
        _fact("Baku State University", "BSc"),
        _record("Baku State University", "MSc"),
    ) == "different"


def test_four_years_apart_is_another_degree():
    assert same_degree(
        _fact("Baku State University", "BSc", "2021-06-30"),
        _record("Baku State University", "BSc", "2025-06-30"),
    ) == "different"


def test_a_name_the_transcript_taught_us_matches():
    assert same_degree(
        _fact("Baku State University", "BSc Chemistry", "2025-06-30",
              aliases=["Bakı Dövlət Universiteti", "Bakalavr"]),
        _record("Bakı Dövlət Universiteti", "Bakalavr", "2025-06-30"),
    ) == "same"


def test_the_same_name_however_it_is_spelled():
    assert institution_key("Bakı Dövlət Universiteti") == institution_key(
        "Baki Dovlet Universiteti")
    assert institution_key("Бакинский государственный университет") == institution_key(
        "Бакинский Государственный Университет")


def test_an_unknown_level_and_date_do_not_decide():
    assert same_degree(_fact("Khazar University", "Diploma"),
                       _record("Khazar University", "Diploma")) == "same"


def test_two_unrelated_universities_are_asked_not_assumed_different():
    assert same_degree(_fact("ADA University", "BA", "2024-06-30"),
                       _record("Khazar University", "Bachelor", "2024-06-30")) == "ask"


@pytest.mark.parametrize(("text", "level"), [
    ("Bachelor of Science", "bachelor"), ("Bakalavr", "bachelor"), ("Lisans", "bachelor"),
    ("бакалавр", "bachelor"), ("BSc", "bachelor"), ("B.A.", "bachelor"),
    ("Master of Arts", "master"), ("Magistr", "master"), ("Yüksek Lisans", "master"),
    ("магистр", "master"), ("M.Sc.", "master"),
    ("PhD", "doctorate"), ("Fəlsəfə doktoru", "doctorate"), ("кандидат наук", "doctorate"),
    ("Diploma", "other"), ("", "other"),
])
def test_degree_levels_in_four_languages(text, level):
    assert degree_level(text) == level


def _education(student, payload, confirmed=True):
    return VerifiedFact.objects.create(
        student=student, category="EDUCATION", payload=payload,
        source_tier="STUDENT_STATEMENT", source_ref="upload:cv",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None, created_by=student)


@pytest.mark.django_db
def test_match_record_prefers_a_sure_match_over_a_question(agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert match_record(membership_a, _record("Baku State University", "BSc")) == (
            "none", None)
        asked = _education(membership_a, _fact("ADA University", "BA"))
        assert match_record(membership_a, _record("Baku State University", "BSc")) == (
            "ask", asked)
        same = _education(membership_a, _fact("Baku State University", "BSc"))
        assert match_record(membership_a, _record("Baku State University", "BSc")) == (
            "same", same)
        assert match_record(membership_a, _record("Baku State University", "PhD")) == (
            "different", None)


@pytest.mark.parametrize(("fact", "record"), [
    (_fact("Ohio State University", "BSc", "2024-06-30"),
     _record("Ohio University", "BSc", "2024-06-30")),
    (_fact("University of Michigan", "BA"), _record("Michigan State University", "BA")),
    (_fact("ADA University", "BSc", aliases=["Bachelor of Science"]),
     _record("Khazar University", "Bachelor of Science")),
    (_fact("BSU", "BSc"), _record("Belarusian State University", "Bachelor")),
])
def test_weak_evidence_is_asked_never_assumed(fact, record):
    # Final review finding 7: each of these came back "same".
    assert same_degree(fact, record) == "ask"


def test_two_known_countries_that_differ_are_two_degrees():
    assert same_degree(_fact("BSU", "BSc", "2025-06-30", country="BY"),
                       {**_record("Baku State University", "Bachelor", "2025-06-30"),
                        "country_code": "AZ"}) == "different"


@pytest.mark.parametrize(("text", "level"), [
    ("Bakalavriat", "bachelor"), ("Бакалавриат", "bachelor"), ("Doktora", "doctorate"),
    ("Doktorantura", "doctorate"),
])
def test_more_level_words(text, level):
    assert degree_level(text) == level


@pytest.mark.django_db
def test_a_documents_open_question_and_a_disowned_row_are_not_degrees(agency_a, membership_a):
    # Final review finding 5: an unconfirmed whole-document row is a question, not a degree.
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a, category="EDUCATION", source_tier="AUTHORITATIVE_DOCUMENT",
            payload=_fact("Baku State University", "BSc"), source_ref="document:D",
            created_by=membership_a)
        assert match_record(membership_a, _record("Baku State University", "BSc")) == (
            "none", None)


def test_same_degree_normalizes_country_name_against_country_code():
    assert same_degree(
        _fact("Baku State University", "BSc", "2025-06-30", country="Azerbaijan"),
        {**_record("Baku State University", "Bachelor", "2025-06-30"), "country_code": "AZ"},
    ) == "same"
    assert same_degree(
        _fact("Baku State University", "BSc", "2025-06-30", country="Azərbaycan Respublikası"),
        {**_record("Baku State University", "Bachelor", "2025-06-30"), "country_code": "AZ"},
    ) == "same"
    assert same_degree(
        _fact("Baku State University", "BSc", "2025-06-30", country="Germany"),
        {**_record("Baku State University", "Bachelor", "2025-06-30"), "country_code": "AZ"},
    ) == "different"


def test_global_degree_levels_and_european_institution_keys():
    assert degree_level("B.Tech in Computer Science") == "bachelor"
    assert degree_level("Laurea Triennale in Informatica") == "bachelor"
    assert degree_level("Laurea Magistrale in Informatica") == "master"
    assert degree_level("LL.M. in International Law") == "master"
    assert degree_level("Diplom-Informatiker") == "master"
    assert institution_key("Technische Universität München") == institution_key(
        "Technische Munchen"
    )
    assert institution_key("Université de Montréal") == institution_key("Montreal")

