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
