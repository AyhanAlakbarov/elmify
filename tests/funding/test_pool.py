"""The interim candidate pool: what a student is evaluated against.

Spec section 10.1. This query is a placeholder for cell selection and its tests
are about the two rules that survive that replacement: the pool never reads an
unserved row, and it never narrows on a preference.
"""

from uuid import uuid4

import pytest

from apps.funding.models import FundingOpportunity, Institution, Program
from apps.funding.pool import candidate_pool
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db


@pytest.fixture
def institution():
    return Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name="Example University",
        country_code="DE",
        official_website="https://university.example.org",
    )


def _program(institution, *, name="MSc Computer Science", country="DE"):
    return Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name=name,
        campus_name="Main",
        city="Munich",
        country_code=country,
        location_key=f"{country}:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )


def _award(*, served, name="Foundation Stipend", suspended_for="", suspension_quote=""):
    organisation = record_organisation(
        domain=f"funder-{uuid4().hex[:8]}.org",
        name="Example Foundation",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )
    return FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}",
        name=name,
        family="PRIVATE_FOUNDATION",
        scope_type="HOLDER",
        holder="PRIVATE_FOUNDATION",
        holder_domain=organisation.primary_domain,
        holder_name="Example Foundation",
        organisation=organisation,
        agreement="AGREED",
        served=served,
        suspended_for=suspended_for,
        suspension_quote=suspension_quote,
    )


def test_the_pool_never_reads_an_unserved_row(profile, institution):
    """The serve gate is the catalog's promise; the pool does not second-guess
    it, and a pool that read unserved rows would put a disputed award in front
    of a student through the back door."""
    _program(institution)
    shown = _award(served=True, name="Served award")
    _award(served=False, name="Unserved award")

    result = candidate_pool(profile, limit=50)

    assert [award.id for award in result.awards] == [shown.id]


def test_a_preference_filters_the_pool_and_a_non_negotiable_does_not(profile, institution):
    """allowed_countries is already a hard gate in the evaluator. Filtering the
    pool by a PREFERRED country hides funding the student would have taken --
    so only excluded_countries and the field narrow the pool."""
    wanted = _program(institution, name="MSc Computer Science", country="DE")
    elsewhere = _program(institution, name="MSc Computer Science", country="NL")

    excluded = profile.model_copy(update={"excluded_countries": ("NL",)})
    result = candidate_pool(excluded, limit=50)
    assert [program.id for program in result.programs] == [wanted.id]

    # allowed_countries is a preference here, and the pool must ignore it: the
    # evaluator decides on it with a reason the student can read.
    preferred = profile.model_copy(update={"allowed_countries": ("DE",)})
    assert {program.id for program in candidate_pool(preferred, limit=50).programs} == {
        wanted.id,
        elsewhere.id,
    }


def test_the_field_narrows_the_pool(profile, institution):
    _program(institution, name="MSc Computer Science")
    other = _program(institution, name="MA Art History")

    result = candidate_pool(profile, limit=50)
    assert other.id not in {program.id for program in result.programs}


def test_an_award_its_own_page_withdrew_is_not_pooled(profile, institution):
    """A page that negated itself said this award is unfunded. Pooling it
    anyway puts a scholarship in the pack that the funder has withdrawn.

    The marker is `suspension_quote`, not `suspended_for`: a suspension naming
    no intake leaves the latter blank and is still a suspension (see that
    field's comment on the model). The earlier form of this filter tested
    whether `suspended_for` contained the intake year, which said nothing at
    all about that case.

    `funding_opportunity_served_not_suspended` makes this pair impossible at
    the database now, so the row below is built unserved and the assertion is
    that the pool agrees -- the filter is defence in depth for the unserve
    sweep that is still owed (spec section 19).
    """
    _program(institution)
    live = _award(served=True, name="Live award")
    _award(
        served=False,
        name="Withdrawn award",
        suspended_for=str(profile.intended_intake.year),
        suspension_quote="No scholarships are offered for this intake.",
    )

    result = candidate_pool(profile, limit=50)
    assert [award.id for award in result.awards] == [live.id]


def test_an_empty_pool_reports_why(profile, institution):
    """P1-7: never a silently short pack. The run records field, countries and
    intake, and the pack publishes that sentence."""
    _program(institution, name="MA Art History")

    result = candidate_pool(profile, limit=50)

    assert result.programs == () and result.awards == ()
    assert result.empty_reason
    assert profile.target_field in result.empty_reason
    assert str(profile.intended_intake.year) in result.empty_reason


def test_a_non_empty_pool_carries_no_reason(profile, institution):
    _program(institution)
    assert candidate_pool(profile, limit=50).empty_reason == ""


def test_the_pool_is_bounded_and_deterministic(profile, institution):
    """An unbounded pool is an unbounded evaluation, and an unordered one makes
    `limit` pick a different set on every call for no stated reason."""
    for index in range(5):
        _program(institution, name=f"MSc Computer Science {index}")

    first = candidate_pool(profile, limit=3)
    second = candidate_pool(profile, limit=3)

    assert len(first.programs) == 3
    assert [p.id for p in first.programs] == [p.id for p in second.programs]


def test_token_field_matching_includes_separated_subject_words(profile, institution):
    exact = _program(institution, name="MSc Computer Science")
    separated = _program(institution, name="MSc in Computer and Information Science")
    unrelated = _program(institution, name="MA Art History")

    result = candidate_pool(profile, limit=50)
    ids = [p.id for p in result.programs]
    assert exact.id in ids
    assert separated.id in ids
    assert unrelated.id not in ids
    assert ids[0] == exact.id


def test_corridor_relevant_holder_awards_are_selected_before_unrelated_countries_at_limit(
    profile, institution
):
    from apps.research.register import record_organisation

    org_br = record_organisation(
        domain="funder-a.br",
        name="Brazil Funder",
        kind="PRIVATE_FOUNDATION",
        country_code="BR",
        found_via="REGISTER",
    )
    org_de = record_organisation(
        domain="funder-z.de",
        name="Germany Funder",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )
    _program(institution, name="MSc Computer Science", country="DE")
    FundingOpportunity.objects.create(
        canonical_key="a-first-alphabetically-brazil",
        name="Brazil Award",
        family="PRIVATE_FOUNDATION",
        scope_type="HOLDER",
        holder="PRIVATE_FOUNDATION",
        holder_domain=org_br.primary_domain,
        holder_name="Brazil Funder",
        organisation=org_br,
        agreement="AGREED",
        served=True,
    )
    de_award = FundingOpportunity.objects.create(
        canonical_key="z-last-alphabetically-germany",
        name="Germany Award",
        family="PRIVATE_FOUNDATION",
        scope_type="HOLDER",
        holder="PRIVATE_FOUNDATION",
        holder_domain=org_de.primary_domain,
        holder_name="Germany Funder",
        organisation=org_de,
        agreement="AGREED",
        served=True,
    )

    result = candidate_pool(profile, limit=1)
    assert [a.id for a in result.awards] == [de_award.id]


def test_candidate_pool_prioritizes_allowed_countries_and_teaching_languages_at_limit(
    profile, institution
):
    other = Program.objects.create(
        institution=institution,
        canonical_key="a-first-alphabetically-fr",
        name="MSc Computer Science",
        campus_name="Main",
        city="Paris",
        country_code="FR",
        location_key="FR:paris",
        degree_level="MASTER",
        teaching_languages=["French"],
        duration_months=24,
    )
    de_german = Program.objects.create(
        institution=institution,
        canonical_key="b-second-alphabetically-de-german",
        name="MSc Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE:munich",
        degree_level="MASTER",
        teaching_languages=["German"],
        duration_months=24,
    )
    de_english = Program.objects.create(
        institution=institution,
        canonical_key="z-last-alphabetically-de-english",
        name="MSc Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )

    preferred = profile.model_copy(
        update={
            "allowed_countries": ("DE",),
            "acceptable_teaching_languages": ("English",),
        }
    )

    top_one = candidate_pool(preferred, limit=1)
    assert [p.id for p in top_one.programs] == [de_english.id]

    top_two = candidate_pool(preferred, limit=2)
    assert [p.id for p in top_two.programs] == [de_english.id, de_german.id]

    all_three = candidate_pool(preferred, limit=10)
    assert [p.id for p in all_three.programs] == [de_english.id, de_german.id, other.id]


def test_candidate_pool_prioritizes_inferred_degree_level_and_non_negotiable_duration(
    profile, institution
):
    msc_24m = Program.objects.create(
        institution=institution,
        canonical_key="a-first-msc-24m",
        name="MSc Computer Science 2yr",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    msc_12m = Program.objects.create(
        institution=institution,
        canonical_key="z-last-msc-12m",
        name="MSc Computer Science 1yr",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=12,
    )

    one_year_non_neg = profile.model_copy(
        update={
            "duration_flexibility": "NON_NEGOTIABLE",
            "duration_preference": "ONE_YEAR",
        }
    )

    top_one = candidate_pool(one_year_non_neg, limit=1)
    assert [p.id for p in top_one.programs] == [msc_12m.id]

    all_two = candidate_pool(one_year_non_neg, limit=10)
    assert [p.id for p in all_two.programs] == [msc_12m.id, msc_24m.id]


@pytest.mark.django_db
def test_home_country_holder_award_not_excluded_when_student_excludes_home_country(
    profile,
):
    home_award = _award(served=True, name="State Program for Study Abroad")
    assert home_award.organisation is not None
    home_award.organisation.country_code = "AZ"
    home_award.organisation.save(update_fields=["country_code"])

    foreign_excluded_award = _award(served=True, name="Banach Scholarship")
    assert foreign_excluded_award.organisation is not None
    foreign_excluded_award.organisation.country_code = "PL"
    foreign_excluded_award.organisation.save(update_fields=["country_code"])

    abroad_only = profile.model_copy(
        update={
            "nationality": "AZ",
            "excluded_countries": ("AZ", "PL"),
        }
    )
    pool = candidate_pool(abroad_only, limit=10)
    award_ids = {a.id for a in pool.awards}
    assert home_award.id in award_ids
    assert foreign_excluded_award.id not in award_ids




