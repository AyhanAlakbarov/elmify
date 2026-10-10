"""Builders for the demand-cell coverage tests, importable from any test
package (tests/audit uses them too; a conftest fixture does not cross
directories)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import uuid4

from django.utils import timezone

from apps.accounts.profile_versions import create_profile_version
from apps.funding.models import (
    BenefitRule,
    EvidenceClaim,
    FundingBenefit,
    FundingOpportunity,
    PackCandidate,
    PackVersion,
    Program,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.research.funding_reader import FAMILY_BY_HOLDER
from apps.research.models import ProfileCellSelection
from apps.research.register import record_organisation
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Agency, Membership
from tests.funding.conftest import make_profile


def make_served_award(
    *,
    holder: str = "PRIVATE_FOUNDATION",
    nationalities: Sequence[str] = (),
    organisation_country: str = "TR",
) -> FundingOpportunity:
    """A served HOLDER award whose home cells are `nationalities`.

    Master stores a nationality list as a BenefitRule (key CITIZENSHIP,
    operator IN, a comma-joined value) on one of the award's benefits -- there
    is no NATIONALITY scope -- so that is what this builds. `nationalities=()`
    writes no rule: the award sits in home ANY.
    """
    n = uuid4().hex[:8]
    organisation = record_organisation(
        domain=f"holder-{n}.example.org", name=f"Holder {n}", kind=holder,
        country_code=organisation_country, found_via="REGISTER",
    )
    award = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{n}", name=f"Award {n}",
        family=FAMILY_BY_HOLDER[holder], scope_type="HOLDER", holder=holder,
        holder_domain=organisation.primary_domain, holder_name=f"Holder {n}",
        organisation=organisation, agreement="AGREED", served=True, money_form="GRANT",
    )
    if nationalities:
        benefit = FundingBenefit.objects.create(
            opportunity=award, kind="STIPEND", period="MONTHLY", description="stipend",
        )
        BenefitRule.objects.create(
            benefit=benefit, kind="ELIGIBILITY", key="CITIZENSHIP", operator="IN",
            value=",".join(nationalities),
            rule_text="Open to citizens of the listed countries.", scope_type="GLOBAL",
        )
    return award


def make_published_student(
    agency: Agency,
    user_model: type,
    *,
    nationality: str = "AZ",
    residence: str | None = None,
    allowed: Sequence[str] = (),
    bucket: str = "physical_sciences",
    eligible_awards: Sequence[FundingOpportunity] = (),
    programs: Sequence[Program] = (),
    intake: date | None = None,
    published: bool = True,
    **overrides: object,
) -> Membership:
    """An active STUDENT with a schema-3 profile version, a ProfileCellSelection,
    a run and a pack (PUBLISHED unless `published=False`) whose candidates point
    at each award and programme given."""
    fields: dict[str, object] = dict(
        nationality=nationality,
        country_of_residence=residence or nationality,
        allowed_countries=tuple(allowed),
    )
    if intake is not None:
        fields["intended_intake"] = intake
    fields.update(overrides)
    with tenant_scope(agency.id):
        user = user_model.objects.create(username=f"student-{uuid4().hex[:8]}")
        student = Membership.objects.create(
            tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
        )
        version = create_profile_version(student=student, snapshot=make_profile(**fields))
        ProfileCellSelection.objects.create(
            student=student, profile_version=version, discipline_bucket=bucket
        )
        run = RecommendationRun.objects.create(profile_version=version)
        pack = PackVersion.objects.create(
            run=run, version=1, published_at=timezone.now() if published else None
        )
        for row in (*eligible_awards, *programs):
            is_award = isinstance(row, FundingOpportunity)
            candidate = RecommendationCandidate.objects.create(
                run=run,
                evidence=EvidenceClaim.objects.create(
                    source_url=f"https://official.example.test/{uuid4()}",
                    claim="Official source.", last_checked_at=timezone.now(),
                ),
                opportunity=row if is_award else None,
                program=None if is_award else row,
                program_name=row.name, funding_gap=0, currency="EUR", eligible=True,
            )
            PackCandidate.objects.create(pack_version=pack, candidate=candidate)
    return student
