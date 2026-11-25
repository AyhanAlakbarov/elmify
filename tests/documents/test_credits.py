from decimal import Decimal

from apps.documents.credits import to_ects


def test_ects_is_unchanged():
    assert to_ects(Decimal("6"), "ECTS") == Decimal("6.00")


def test_a_us_semester_hour_is_two_ects():
    # A full-time US year is 30 semester hours; a full-time ECTS year is 60.
    assert to_ects(Decimal("3"), "US_SEMESTER_HOUR") == Decimal("6.00")


def test_a_uk_cats_credit_is_half_an_ects():
    # A full-time UK undergraduate year is 120 CATS credits; 60 ECTS / 120 CATS = 0.5.
    assert to_ects(Decimal("15"), "UK_CATS") == Decimal("7.50")
    assert to_ects(Decimal("20"), "UK_CATS") == Decimal("10.00")


def test_a_us_quarter_hour_and_ru_zet_convert_by_statutory_year_load():
    # A full-time US quarter-system year is 45 quarter hours; 60 / 45 = 4/3 ECTS.
    assert to_ects(Decimal("4.5"), "US_QUARTER_HOUR") == Decimal("6.00")
    assert to_ects(Decimal("4"), "US_QUARTER_HOUR") == Decimal("5.33")
    # Russian Federal State Educational Standard (ФГОС) ЗЕТ is 60 per full-time year (1:1 ECTS).
    assert to_ects(Decimal("6"), "RU_ZET") == Decimal("6.00")


def test_a_local_credit_scales_by_the_full_year_load():
    assert to_ects(Decimal("5"), "LOCAL", local_credits_per_year=Decimal("40")) == Decimal("7.50")


def test_a_local_credit_without_a_year_load_is_unknown_not_guessed():
    assert to_ects(Decimal("5"), "LOCAL") is None


def test_an_unknown_unit_is_unknown():
    assert to_ects(Decimal("5"), "UNKNOWN", local_credits_per_year=Decimal("60")) is None


def test_international_credit_units_sws_kp_fce_academic_hours_and_bologna_aliases():
    from apps.documents.credits import infer_local_credits_per_year
    from apps.documents.transcript import academic_record

    # Bologna 1:1 aliases (60/year)
    for unit in ("CFU", "AKTS", "EC", "SE_HP", "EE_EAP", "DE_LP"):
        assert to_ects(Decimal("6"), unit) == Decimal("6.00")

    # German SWS (~40 SWS/year -> 1.5 ECTS per SWS), Latvian KP (40 KP/year -> 1.5 ECTS per KP)
    assert to_ects(Decimal("4"), "DE_SWS") == Decimal("6.00")
    assert to_ects(Decimal("4"), "LV_KP") == Decimal("6.00")

    # Canadian FCE (5.0 FCE/year -> 12 ECTS per 1.0 FCE; 0.5 FCE half-course = 6 ECTS)
    assert to_ects(Decimal("0.5"), "CA_FCE") == Decimal("6.00")
    assert to_ects(Decimal("1.0"), "CA_FCE") == Decimal("12.00")

    # Turkish pre-Bologna local kredi (35/yr) and post-Soviet academic hours (2160h/yr)
    assert to_ects(Decimal("3.5"), "TR_LOCAL_KREDI") == Decimal("6.00")
    assert to_ects(Decimal("108"), "ACADEMIC_HOUR") == Decimal("3.00")
    assert to_ects(Decimal("144"), "ACADEMIC_HOUR") == Decimal("4.00")

    # Tier-2 proportional degree-total normalization for LOCAL credits when year load is omitted
    # Case 1: Explicit total_credits=140 on a 4-year Bachelor -> 140 / 4 = 35 local credits/year
    assert (
        infer_local_credits_per_year(
            [Decimal("3.5")] * 40,
            total_credits=Decimal("140"),
            qualification="Bachelor of Science",
            country_code="TR",
        )
        == Decimal("35")
    )
    # Case 2: Completed 4-year Bachelor with 40 courses summing to 136 local credits -> 34/year
    assert (
        infer_local_credits_per_year(
            [Decimal("3.4")] * 40,
            qualification="BSc",
            country_code="US",
        )
        == Decimal("34")
    )
    # Case 3: Post-Soviet academic hours under LOCAL (median >= 36h, sum >= 1000h) -> 2160h/year
    assert (
        infer_local_credits_per_year(
            [Decimal("108")] * 20,
            qualification="Bachelor",
            country_code="AZ",
        )
        == Decimal("2160")
    )
    # Case 4: Partial transcript (only 5 courses, no total_credits) -> None (never guessed)
    assert (
        infer_local_credits_per_year(
            [Decimal("3")] * 5,
            qualification="BSc",
            country_code="US",
        )
        is None
    )

    # Real caller test: `academic_record` in `apps/documents/transcript.py` feeds normalized ECTS
    from apps.documents.transcript import TranscriptContent, TranscriptCourse

    content = TranscriptContent(
        institution="Istanbul Technical University",
        country_code="TR",
        qualification="Bachelor of Science",
        field="Mechanical Engineering",
        overall_grade="3.50",
        grading_scale="4.0",
        credit_unit="LOCAL",
        local_credits_per_year=None,
        courses=tuple(
            TranscriptCourse(
                title=f"Course {i}",
                credits=Decimal("3.5"),
                grade="AA",
                status="COMPLETED",
            )
            for i in range(40)
        ),
        completed_on="2025-06-15",
        expected_completion=None,
    )
    rec = academic_record(content)
    assert len(rec["courses"]) == 40
    assert rec["courses"][0]["ects"] == "6.00"

