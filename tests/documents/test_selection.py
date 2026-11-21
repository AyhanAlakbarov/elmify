from datetime import date

import pytest

from apps.documents.coverage import Coverage, items_of
from apps.documents.relevance import Verdict
from apps.documents.schemas import AwardEntry, ExperienceEntry, PublicationEntry
from apps.documents.selection import apply_coverage, select_for_programme, without

from .test_render import _content

TODAY = date(2026, 10, 13)


def _pubs(*years):
    return tuple(
        PublicationEntry(authors=("Doe, J.",), title=f"Paper {y}", year=y) for y in years
    )


def test_a_cap_keeps_the_most_recent_and_lists_the_rest():
    content = _content().model_copy(update={"publications": _pubs(2019, 2023, 2021)})
    chosen = apply_coverage(
        content, Coverage(caps=(("publications", 2),)), kept=frozenset(), today=TODAY
    )
    assert [p.year for p in chosen.content.publications] == [2023, 2021]
    assert [(lo.section, lo.text) for lo in chosen.left_out] == [
        ("publications", "Paper 2019 (2019)")
    ]
    assert chosen.left_out[0].reason == "the programme lists at most 2 publications"


def test_a_put_back_item_survives_a_cap():
    content = _content().model_copy(update={"publications": _pubs(2019, 2023)})
    old = [i for i in items_of(content) if i.text.startswith("Paper 2019")][0]
    chosen = apply_coverage(
        content, Coverage(caps=(("publications", 1),)), kept=frozenset({old.digest}), today=TODAY
    )
    assert len(chosen.content.publications) == 2
    assert chosen.left_out == ()


def test_a_window_leaves_out_only_reach_items_older_than_it():
    content = _content(experience=(
        ExperienceEntry(employer="SOCAR", title="Intern", start_date="2010-06-01",
                        end_date="2010-08-31", bullets=("Built.",)),
        ExperienceEntry(employer="Red Cross", title="Volunteer", unpaid=True,
                        start_date="2010-01-01", end_date="2010-05-01", bullets=("Taught.",)),
    )).model_copy(update={"awards": (AwardEntry(title="Old prize", date="2009-05-01"),
                                      AwardEntry(title="New prize", date="2024-05-01"))})
    chosen = apply_coverage(
        content, Coverage(start="last_n_years", years=10), kept=frozenset(), today=TODAY
    )
    assert [e.employer for e in chosen.content.experience] == ["SOCAR"]   # paid stays
    assert [a.title for a in chosen.content.awards] == ["New prize"]
    assert {lo.section for lo in chosen.left_out} == {"volunteering", "awards"}


def test_no_coverage_changes_nothing():
    content = _content().model_copy(update={"publications": _pubs(2019)})
    chosen = apply_coverage(content, Coverage(), kept=frozenset(), today=TODAY)
    assert chosen.content == content and chosen.left_out == ()


def test_without_drops_by_position_inside_the_right_field():
    content = _content().model_copy(update={"publications": _pubs(2019, 2020, 2021)})
    middle = [i for i in items_of(content) if i.section == "publications"][1]
    assert [p.year for p in without(content, [middle]).publications] == [2019, 2021]


@pytest.mark.django_db
def test_select_for_programme_reads_the_page_and_never_breaks_a_binding_rule(
    agency_a, membership_a, program_factory
):
    """The page's own cap reaches generation through resolve_rules, and the
    BINDING guard leaves a CV that breaks no BINDING rule alone (the revert
    itself is pinned by test_a_leave_out_that_fails_a_binding_rule_is_reverted)."""
    cap = {
        "rule_id": "PAGE-1-cv_item_cap", "key": "cv_item_cap",
        "value": {"section": "publications", "max": 1},
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "Max 1 publication.",
        "scope": "PROGRAMME",
    }
    programme = program_factory(cv_constraints=[cap])
    content = _content().model_copy(update={"publications": _pubs(2019, 2023)})
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        chosen = select_for_programme(content, student=membership_a, programme=programme,
                                      today=TODAY)
    assert [p.year for p in chosen.content.publications] == [2023]


def test_select_without_a_programme_is_a_no_op(membership_a):
    content = _content()
    chosen = select_for_programme(content, student=membership_a, programme=None)
    assert chosen.content is content and chosen.left_out == ()


def test_a_leave_out_that_fails_a_binding_rule_is_reverted(monkeypatch):
    from apps.documents import selection

    content = _content().model_copy(update={"publications": _pubs(2019, 2023)})
    calls = iter([frozenset(), frozenset({"R-BIND"})])
    monkeypatch.setattr(selection, "binding_content_failures", lambda c, r: next(calls))
    chosen = selection._guarded(content, selection.apply_coverage(
        content, Coverage(caps=(("publications", 1),)), kept=frozenset(), today=TODAY
    ), ())
    assert chosen.content is content and chosen.left_out == ()


@pytest.mark.django_db
def test_a_put_back_digest_is_read_for_its_programme_only(agency_a, membership_a, program_factory):
    from apps.documents.models import CVItemChoice
    from apps.documents.selection import _put_back
    from apps.tenancy.context import tenant_scope

    mine, other = program_factory(), program_factory()
    with tenant_scope(agency_a.id):
        CVItemChoice.objects.create(student=membership_a, program_id=mine.id,
                                    section="awards", item_digest="a" * 64)
        assert _put_back(membership_a, mine) == {"a" * 64}
        assert _put_back(membership_a, other) == frozenset()


def _awarded():
    return _content().model_copy(update={"awards": (
        AwardEntry(title="Chess prize", date="2018-05-01"),
        AwardEntry(title="Debate prize", date="2020-05-01"),
        AwardEntry(title="Chemistry olympiad", date="2019-05-01"),
    )})


def _verdicts(content, by_title):
    return {i.digest: by_title[i.text.split(" (")[0]] for i in items_of(content)
            if i.text.split(" (")[0] in by_title}


@pytest.fixture
def judged(monkeypatch, settings):
    settings.CV_RELEVANCE_BAR = 0.9
    from apps.documents import selection

    def install(by_title):
        monkeypatch.setattr(
            selection, "judge",
            lambda items, **kw: {i.digest: by_title[i.text.split(" (")[0]]
                                 for i in items if i.text.split(" (")[0] in by_title},
        )
    return install


@pytest.mark.django_db
def test_only_a_sure_unrelated_item_is_left_out(agency_a, membership_a, program_factory, judged):
    judged({"Chess prize": Verdict("unrelated", 0.95, 0.95),
            "Debate prize": Verdict("unrelated", 0.7, 0.7),
            "Chemistry olympiad": Verdict("cannot_tell", 0.99, 0.0)})
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        chosen = select_for_programme(_awarded(), student=membership_a,
                                      programme=program_factory(), today=TODAY)
    assert [a.title for a in chosen.content.awards] == ["Debate prize", "Chemistry olympiad"]
    assert [(lo.text, lo.reason) for lo in chosen.left_out] == [
        ("Chess prize (2018)", "not related to this programme")
    ]


@pytest.mark.django_db
def test_a_complete_page_switches_the_engine_off(agency_a, membership_a, program_factory,
                                                 monkeypatch):
    from apps.documents import selection
    from apps.tenancy.context import tenant_scope

    monkeypatch.setattr(selection, "judge", lambda *a, **kw: pytest.fail("Jev was asked"))
    complete = {"rule_id": "PAGE-1-cv_scope", "key": "cv_scope", "value": "complete",
                "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "List everything.",
                "scope": "PROGRAMME"}
    with tenant_scope(agency_a.id):
        chosen = select_for_programme(_awarded(), student=membership_a,
                                      programme=program_factory(cv_constraints=[complete]))
    assert len(chosen.content.awards) == 3


@pytest.mark.django_db
def test_a_put_back_item_is_never_left_out_again(agency_a, membership_a, program_factory, judged):
    from apps.documents.models import CVItemChoice
    from apps.tenancy.context import tenant_scope

    judged({"Chess prize": Verdict("unrelated", 0.99, 0.99)})
    programme = program_factory()
    chess = [i for i in items_of(_awarded()) if i.text.startswith("Chess")][0]
    with tenant_scope(agency_a.id):
        CVItemChoice.objects.create(student=membership_a, program_id=programme.id,
                                    section="awards", item_digest=chess.digest)
        chosen = select_for_programme(_awarded(), student=membership_a, programme=programme)
    assert len(chosen.content.awards) == 3 and chosen.left_out == ()


@pytest.mark.django_db
def test_a_funder_template_keeps_its_awards(agency_a, membership_a, program_factory, judged):
    from apps.tenancy.context import tenant_scope

    judged({"Chess prize": Verdict("unrelated", 0.99, 0.99)})
    programme = program_factory(cv_format_requirement="funder_template")
    with tenant_scope(agency_a.id):
        chosen = select_for_programme(_awarded(), student=membership_a, programme=programme)
    assert len(chosen.content.awards) == 3


@pytest.mark.django_db
def test_skills_are_judged_but_never_left_out(agency_a, membership_a, program_factory, judged):
    from apps.documents.schemas import SkillEntry
    from apps.tenancy.context import tenant_scope

    judged({"Juggling": Verdict("unrelated", 0.99, 0.99)})
    content = _content().model_copy(update={"skills": (SkillEntry(name="Juggling"),)})
    with tenant_scope(agency_a.id):
        chosen = select_for_programme(content, student=membership_a, programme=program_factory())
    assert [s.name for s in chosen.content.skills] == ["Juggling"]


@pytest.mark.django_db
def test_an_asked_for_item_prints_first_in_its_section(
    agency_a, membership_a, program_factory, judged
):
    from apps.tenancy.context import tenant_scope

    judged({"Chemistry olympiad": Verdict("asked_for", 0.9, 0.0)})
    with tenant_scope(agency_a.id):
        chosen = select_for_programme(_awarded(), student=membership_a, programme=program_factory())
    assert chosen.content.awards[0].title == "Chemistry olympiad"


@pytest.mark.django_db
def test_general_merit_goes_oldest_first_only_while_the_cv_overflows(
    agency_a, membership_a, program_factory, judged, monkeypatch
):
    from apps.documents import selection
    from apps.tenancy.context import tenant_scope

    judged({"Chess prize": Verdict("general_merit", 0.9, 0.0),
            "Debate prize": Verdict("general_merit", 0.9, 0.0)})
    # Over the page target while more than two awards remain.
    monkeypatch.setattr(selection, "_over_pages",
                        lambda content, variant, constraints: len(content.awards) > 2)
    cap = {"rule_id": "PAGE-1-max_pages", "key": "max_pages", "value": 1,
           "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "One page.", "scope": "PROGRAMME"}
    with tenant_scope(agency_a.id):
        chosen = select_for_programme(_awarded(), student=membership_a,
                                      programme=program_factory(cv_constraints=[cap]))
    assert [a.title for a in chosen.content.awards] == ["Debate prize", "Chemistry olympiad"]
    assert chosen.left_out[0].reason == "left out to keep the CV within the programme's page limit"


def test_over_pages_downgrades_binding_max_pages_so_merit_drops_before_compact_retry(monkeypatch):
    from apps.documents import selection
    from apps.documents.constraints import ConstraintRule, Enforcement

    seen_enforcements: list[Enforcement] = []

    def fake_render(content, *, variant, constraints=()):
        for r in constraints:
            if r.key == "max_pages":
                seen_enforcements.append(r.enforcement)
        return None, ()

    monkeypatch.setattr(selection, "render_cv_with_warnings", fake_render)
    binding_cap = ConstraintRule(
        rule_id="R-080",
        key="max_pages",
        value=2,
        enforcement=Enforcement.BINDING,
        rule_text="Max 2 pages.",
    )
    selection._over_pages(_content(), "STANDARD", (binding_cap,))
    assert seen_enforcements == [Enforcement.ADVISORY_HIGH_RISK]


@pytest.mark.django_db
def test_projects_drop_before_general_merit_when_the_cv_overflows(
    agency_a, membership_a, program_factory, judged, monkeypatch
):
    from apps.documents import selection
    from apps.documents.schemas import ProjectEntry
    from apps.tenancy.context import tenant_scope

    judged({"Debate prize": Verdict("general_merit", 0.9, 0.0)})
    cv = _awarded().model_copy(
        update={
            "projects": (
                ProjectEntry(
                    title="MicroKatc",
                    start_date="2024-08-01",
                    end_date="2025-02-01",
                    bullets=("Implemented stiff ODE integration.",),
                ),
            )
        }
    )
    monkeypatch.setattr(
        selection,
        "_over_pages",
        lambda content, variant, constraints: bool(content.projects),
    )
    cap = {
        "rule_id": "PAGE-1-max_pages",
        "key": "max_pages",
        "value": 1,
        "enforcement": "BINDING",
        "rule_text": "One page.",
        "scope": "PROGRAMME",
    }
    with tenant_scope(agency_a.id):
        chosen = select_for_programme(
            cv,
            student=membership_a,
            programme=program_factory(cv_constraints=[cap]),
        )
    assert chosen.content.projects == ()
    assert [a.title for a in chosen.content.awards] == [
        "Chess prize",
        "Debate prize",
        "Chemistry olympiad",
    ]
    assert [(lo.section, lo.text) for lo in chosen.left_out] == [
        ("projects", "MicroKatc (2025)")
    ]


