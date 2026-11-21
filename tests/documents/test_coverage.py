from apps.documents.constraints import _MULTI_KEYS, CONSTRAINT_KEYS, ConstraintRule, Enforcement
from apps.documents.coverage import Coverage, coverage_of, is_secondary, item_digest, items_of
from apps.documents.schemas import AwardEntry, EducationEntry, ExperienceEntry, TimelineEntry

from .test_render import _content


def _rule(key, value, rule_id="PAGE-1-x"):
    return ConstraintRule(
        rule_id=rule_id, key=key, value=value,
        enforcement=Enforcement.ADVISORY_HIGH_RISK, rule_text="the page's sentence",
        scope="PROGRAMME",
    )


def test_the_three_coverage_keys_are_constraint_keys_and_per_sentence():
    for key in ("cv_scope", "cv_start", "cv_item_cap"):
        assert key in CONSTRAINT_KEYS
        assert key in _MULTI_KEYS


def test_no_rule_is_no_coverage():
    assert coverage_of(()) == Coverage()


def test_complete_beats_relevant_only():
    rules = (
        _rule("cv_scope", "relevant_only", "PAGE-1-a"),
        _rule("cv_scope", "complete", "PAGE-2-a"),
    )
    assert coverage_of(rules).complete is True


def test_the_start_reaching_furthest_back_wins():
    rules = (
        _rule("cv_start", {"start": "last_n_years", "years": 5}, "PAGE-1-a"),
        _rule("cv_start", {"start": "upper_secondary"}, "PAGE-2-a"),
        _rule("cv_start", {"start": "first_degree"}, "PAGE-3-a"),
    )
    assert coverage_of(rules).start == "upper_secondary"
    two_windows = (
        _rule("cv_start", {"start": "last_n_years", "years": 5}, "PAGE-1-a"),
        _rule("cv_start", {"start": "last_n_years", "years": 10}, "PAGE-2-a"),
    )
    assert (coverage_of(two_windows).start, coverage_of(two_windows).years) == ("last_n_years", 10)


def test_two_caps_on_one_section_keep_the_larger_and_a_bad_cap_is_ignored():
    rules = (
        _rule("cv_item_cap", {"section": "publications", "max": 3}, "PAGE-1-a"),
        _rule("cv_item_cap", {"section": "publications", "max": 5}, "PAGE-2-a"),
        _rule("cv_item_cap", {"section": "education", "max": 1}, "PAGE-3-a"),
        _rule("cv_item_cap", {"section": "awards", "max": "five"}, "PAGE-4-a"),
        _rule("cv_item_cap", "junk", "PAGE-5-a"),
    )
    assert coverage_of(rules).caps == (("publications", 5),)


def test_a_school_leaving_entry_is_secondary_and_a_degree_is_not():
    def entry(degree, institution="School No. 6"):
        return EducationEntry(degree_as_awarded=degree, institution_original=institution)

    assert is_secondary(entry("Attestat of complete secondary education"))
    assert is_secondary(entry("Abitur", "Goethe-Gymnasium"))
    assert is_secondary(entry("Diploma", "Baku Lyceum No. 1"))
    assert not is_secondary(entry("BSc Chemical Engineering", "Baku Higher Oil School"))
    assert not is_secondary(entry("Baccalauréat en sciences", "Université Laval"))


def test_items_cover_optional_sections_and_never_education_timeline_or_languages():
    content = _content(
        experience=(
            ExperienceEntry(employer="Red Cross", title="Volunteer", unpaid=True,
                            start_date="2021-01-01", end_date="2021-06-30", bullets=("Taught.",)),
            ExperienceEntry(employer="SOCAR", title="Intern",
                            start_date="2022-06-01", end_date="2022-08-31", bullets=("Built.",)),
        )
    ).model_copy(update={
        "awards": (AwardEntry(title="Debate prize", awarding_body="ADA", date="2020-05-01"),),
        "timeline": (TimelineEntry(start_date="2023-01-01", end_date="2023-12-31",
                                   statement="Compulsory military service."),),
    })
    found = {(item.section, item.text) for item in items_of(content)}
    assert ("volunteering", "Volunteer, Red Cross (2021)") in found
    assert ("experience", "Intern, SOCAR (2022)") in found
    assert ("awards", "Debate prize, ADA (2020)") in found
    assert not any(
        item.section in ("education", "timeline", "languages") for item in items_of(content)
    )


def test_the_digest_ignores_case_and_spacing_but_not_the_section():
    assert item_digest("awards", "Debate  Prize") == item_digest("awards", "debate prize")
    assert item_digest("awards", "Debate prize") != item_digest("certifications", "Debate prize")
    assert len(item_digest("awards", "x")) == 64


def test_an_undated_item_has_no_when():
    content = _content().model_copy(update={"awards": (AwardEntry(title="Prize"),)})
    (award,) = [i for i in items_of(content) if i.section == "awards"]
    assert award.when is None
    assert award.text == "Prize"


def test_certifications_are_items_and_language_tests_are_recognised():
    from apps.documents.coverage import LANGUAGE_TEST
    from apps.documents.schemas import CertificationEntry

    content = _content().model_copy(update={"certifications": (
        CertificationEntry(title="First Aid", issuer="Red Crescent", date="2022-03-01"),
    )})
    (cert,) = [i for i in items_of(content) if i.section == "certifications"]
    assert (cert.field, cert.text) == ("certifications", "First Aid, Red Crescent (2022)")
    for name in ("IELTS Academic 7.5", "TOEFL iBT 104", "TestDaF", "DELF B2", "TÖMER C1",
                 "Goethe-Zertifikat B2", "Duolingo English Test"):
        assert LANGUAGE_TEST.search(name), name
    assert not LANGUAGE_TEST.search("AWS Cloud Practitioner")


def test_no_page_rule_or_relevance_answer_can_reach_a_gap_statement():
    content = _content().model_copy(update={"timeline": (TimelineEntry(
        start_date="2024-10-01", end_date="2025-10-31",
        statement="Compulsory military service"),)})
    assert all(item.field != "timeline" for item in items_of(content))


def test_projects_are_items_for_coverage_and_page_overflow():
    from apps.documents.schemas import ProjectEntry

    content = _content().model_copy(
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
    (proj,) = [i for i in items_of(content) if i.section == "projects"]
    assert (proj.field, proj.text) == ("projects", "MicroKatc (2025)")



