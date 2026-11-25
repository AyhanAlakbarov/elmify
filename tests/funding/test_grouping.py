from uuid import uuid4

from apps.funding.grouping import funds, group_under_funding
from apps.funding.models import RecommendationCandidate


def _programme(name: str, **fields) -> RecommendationCandidate:
    return RecommendationCandidate(program_name=name, program_id=uuid4(), **fields)


def _award(
    name: str, scope: str = "PROGRAM", deadline: str = "", levels: tuple[str, ...] = (), **fields
) -> RecommendationCandidate:
    return RecommendationCandidate(
        program_name=name,
        opportunity_id=uuid4(),
        funding_card={"scope": scope, "deadline": deadline, "degree_levels": list(levels)},
        **fields,
    )


def test_an_award_funds_the_programmes_it_lists() -> None:
    tum = _programme("TUM M.Sc.")
    daad = _award("DAAD", funds_program_ids=[tum.program_id])
    assert funds(daad, tum)
    assert not funds(daad, _programme("KTH M.Sc."))


def test_institution_country_global_and_holder_scopes() -> None:
    institution = uuid4()
    tum = _programme(
        "TUM M.Sc.", institution_id=institution, country_code="DE", degree_level="MASTER"
    )
    kth = _programme("KTH M.Sc.", institution_id=uuid4(), country_code="SE", degree_level="MASTER")
    assert funds(_award("TUM Excellence", scope="INSTITUTION", institution_id=institution), tum)
    assert not funds(_award("TUM Excellence", scope="INSTITUTION", institution_id=institution), kth)
    assert funds(_award("Germany grant", scope="COUNTRY", country_code="DE"), tum)
    assert not funds(_award("Germany grant", scope="COUNTRY", country_code="DE"), kth)
    assert funds(_award("Anywhere", scope="GLOBAL"), kth)
    # Owner, 2026-10-04: an open HOLDER award funds what the student could
    # apply to in its country; with no country it names nothing to match on.
    assert funds(_award("DAAD", scope="HOLDER", country_code="DE"), tum)
    assert not funds(_award("DAAD", scope="HOLDER", country_code="DE"), kth)
    assert not funds(_award("Own application", scope="HOLDER"), kth)


def test_the_degree_level_is_checked_only_where_both_sides_carry_one() -> None:
    tum = _programme("TUM M.Sc.", country_code="DE", degree_level="MASTER")
    unknown = _programme("TUM named", country_code="DE")
    doctoral = _award("Doctoral grant", scope="COUNTRY", country_code="DE", levels=("PHD",))
    assert not funds(doctoral, tum)
    assert funds(doctoral, unknown)
    assert funds(_award("Any level", scope="COUNTRY", country_code="DE"), tum)


def test_an_open_award_lists_every_eligible_programme_from_both_lists() -> None:
    tum = _programme("TUM M.Sc.", country_code="DE")
    lmu = _programme("LMU M.Sc.", country_code="DE")
    kth = _programme("KTH M.Sc.", country_code="SE")
    daad = _award("DAAD", scope="HOLDER", country_code="DE")

    groups = group_under_funding([tum, kth, daad], extra=[lmu], extra_label="in Other options")

    assert groups[0].label == "Eligible programmes in Germany"
    assert [(p.candidate.program_name, p.elsewhere) for p in groups[0].programmes] == [
        ("TUM M.Sc.", ""),
        ("LMU M.Sc.", "in Other options"),
    ]
    assert groups[-1].label == "Programmes without separate funding"
    assert [p.candidate.program_name for p in groups[-1].programmes] == ["KTH M.Sc."]


def test_a_programme_under_two_awards_says_so_under_each() -> None:
    tum = _programme("TUM M.Sc.")
    daad = _award("DAAD", funds_program_ids=[tum.program_id], deadline="2026-11-01")
    erasmus = _award("Erasmus", funds_program_ids=[tum.program_id], deadline="2026-12-01")

    groups = group_under_funding([tum, erasmus, daad])

    assert [g.award.program_name if g.award else None for g in groups] == ["DAAD", "Erasmus", None]
    assert groups[0].programmes[0].also_under == ("Erasmus",)
    assert groups[1].programmes[0].also_under == ("DAAD",)
    assert groups[2].programmes == ()


def test_unfunded_programmes_close_the_list_and_undated_awards_come_last() -> None:
    kth = _programme("KTH M.Sc.")
    undated = _award("Undated", scope="HOLDER")
    dated = _award("Dated", scope="HOLDER", deadline="2026-10-30")

    groups = group_under_funding([kth, undated, dated])

    assert [g.award.program_name if g.award else None for g in groups] == ["Dated", "Undated", None]
    assert [p.candidate.program_name for p in groups[-1].programmes] == ["KTH M.Sc."]


def test_a_home_country_holder_scheme_never_groups_domestic_programmes_by_country() -> None:
    baku = _programme("Baku State MSc", country_code="AZ")
    abroad = _programme("ELTE MSc", country_code="HU")
    state_prog = _award(
        "State Programme",
        scope="HOLDER",
        country_code="AZ",
        funds_program_ids=[abroad.program_id],
    )

    groups = group_under_funding([baku, abroad, state_prog], home_country="AZ")

    assert groups[0].label == "Programmes it can pay for"
    assert [p.candidate.program_name for p in groups[0].programmes] == ["ELTE MSc"]
    assert [p.candidate.program_name for p in groups[-1].programmes] == ["Baku State MSc"]


def test_group_under_funding_orders_programmes_by_rank_then_name() -> None:
    z_first_rank = _programme("Zeta MSc", rank=1)
    a_second_rank = _programme("Alpha MSc", rank=2)
    b_unranked = _programme("Beta MSc", rank=None)

    groups = group_under_funding([b_unranked, a_second_rank, z_first_rank])

    assert [p.candidate.program_name for p in groups[-1].programmes] == [
        "Zeta MSc",
        "Alpha MSc",
        "Beta MSc",
    ]


def test_wp3_outbound_home_country_and_holder_scholarships_group_foreign_programmes() -> None:
    baku = _programme("Baku State MSc", country_code="AZ", degree_level="MASTER")
    delft = _programme("TU Delft MSc", country_code="NL", degree_level="MASTER")
    munich = _programme("TUM MSc", country_code="DE", degree_level="MASTER")
    # Outbound home-government HOLDER scholarship without explicit funds_program_ids
    dp_state = _award(
        "Azerbaijan State Programme (DP) for Study Abroad",
        scope="HOLDER",
        country_code="AZ",
        levels=("MASTER",),
    )

    groups = group_under_funding([baku, delft, munich, dp_state], home_country="AZ")

    assert groups[0].label == "Programmes it can pay for"
    assert [p.candidate.program_name for p in groups[0].programmes] == [
        "TU Delft MSc",
        "TUM MSc",
    ]
    assert [p.candidate.program_name for p in groups[-1].programmes] == ["Baku State MSc"]


def test_multi_country_award_resolves_per_country_amount_on_grouped_programmes() -> None:
    from apps.funding.grouping import award_amounts_for_country

    delft = _programme("TU Delft MSc", country_code="NL", degree_level="MASTER")
    munich = _programme("TUM MSc", country_code="DE", degree_level="MASTER")
    edinburgh = _programme("Edinburgh MSc", country_code="GB", degree_level="MASTER")
    kth = _programme("KTH MSc", country_code="SE", degree_level="MASTER")
    multi_award = RecommendationCandidate(
        program_name="Multi-Country Outbound Scholarship",
        opportunity_id=uuid4(),
        country_code="AZ",
        funding_card={
            "scope": "HOLDER",
            "deadline": "2026-12-01",
            "degree_levels": ["MASTER"],
            "amounts": [
                "Germany: 934 EUR/month",
                "Netherlands: 1150 EUR/month",
                "United Kingdom: 1350 GBP/month",
            ],
            "amounts_by_country": {
                "DE": ["934 EUR/month"],
                "NL": ["1150 EUR/month"],
                "GB": ["1350 GBP/month"],
            },
            "default_amounts": ["800 EUR/month"],
        },
    )

    assert award_amounts_for_country(multi_award.funding_card, "DE") == ("934 EUR/month",)
    assert award_amounts_for_country(multi_award.funding_card, "GB") == ("1350 GBP/month",)
    assert award_amounts_for_country(multi_award.funding_card, "SE") == ("800 EUR/month",)
    assert award_amounts_for_country(multi_award.funding_card, "") == (
        "Germany: 934 EUR/month",
        "Netherlands: 1150 EUR/month",
        "United Kingdom: 1350 GBP/month",
    )

    groups = group_under_funding(
        [delft, munich, edinburgh, kth, multi_award], home_country="AZ"
    )
    by_name = {p.candidate.program_name: p.award_amount for p in groups[0].programmes}
    assert by_name == {
        "Edinburgh MSc": "1350 GBP/month",
        "TU Delft MSc": "1150 EUR/month",
        "TUM MSc": "934 EUR/month",
        "KTH MSc": "800 EUR/month",
    }




