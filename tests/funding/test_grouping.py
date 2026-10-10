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

    assert groups[0].label == "Eligible programmes in DE"
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
