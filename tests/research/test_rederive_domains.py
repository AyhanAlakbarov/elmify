"""rederive_domains: re-key what the old suffix rule merged (spec §5.6)."""

from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.models import (
    FundingOpportunity,
    FundingOpportunityEvidenceClaim,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
)
from apps.research.models import (
    Organisation,
    OrganisationDomain,
    OrganisationIdentifier,
    RegisterEntry,
    RegisterEntryPartner,
)

pytestmark = pytest.mark.django_db


def _snapshot_claim(url: str) -> OfficialEvidenceClaim:
    source = OfficialSource.objects.create(
        canonical_url=url, publisher="x", source_type=OfficialSource.Type.FUNDER
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, s3_key="k", s3_version_id="1", sha256="a" * 64, final_url=url,
        redirect_chain=[], retrieved_at=timezone.now(), admissions_cycle="2027",
        content_type="text/html", byte_size=1,
    )
    return OfficialEvidenceClaim.objects.create(
        source=source, snapshot=snapshot, claim="grant", evidence_strength="DIRECT",
        visibility="STUDENT_FACING", claim_class="FUNDING", last_checked_at=timezone.now(),
    )


def _merged_blog_body() -> Organisation:
    body = Organisation.objects.create(
        primary_domain="blogspot.com", name="A Blog", kind="PRIVATE_FOUNDATION"
    )
    OrganisationDomain.objects.create(organisation=body, registrable_domain="blogspot.com")
    OrganisationIdentifier.objects.create(organisation=body, scheme="WIKIDATA", value="Q1")
    return body


def test_a_body_merged_under_a_platform_root_is_unkeyed_and_its_links_cleared() -> None:
    body = _merged_blog_body()
    award = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}", name="Blog Grant", family="PRIVATE_FOUNDATION",
        scope_type="HOLDER", holder_domain="blogspot.com", organisation=body,
    )
    FundingOpportunityEvidenceClaim.objects.create(
        opportunity=award, evidence_claim=_snapshot_claim("https://foo.blogspot.com/grant")
    )
    entry = RegisterEntry.objects.create(
        register="vgm_tr", external_key="1", name="A Blog", resolution="RESOLVED",
        resolved_via="LISTED", organisation=body, last_seen=timezone.now(),
        contact_domain="blogspot.com",
    )
    partner = RegisterEntryPartner.objects.create(
        entry=entry, organisation=body, role="PARTNER", listed_name="A Blog",
        listed_identifier="9", listed_domain="blogspot.com", disposition="NEW",
    )
    kept = Organisation.objects.create(primary_domain="tum.de", name="TUM", kind="INSTITUTION")
    OrganisationDomain.objects.create(organisation=kept, registrable_domain="tum.de")

    out = StringIO()
    call_command("rederive_domains", stdout=out)

    assert not Organisation.objects.filter(id=body.id).exists()
    assert not OrganisationIdentifier.objects.filter(value="Q1").exists()
    award.refresh_from_db()
    entry.refresh_from_db()
    partner.refresh_from_db()
    # A HOLDER award's `organisation` is NOT NULL
    # (`funding_opportunity_scope_shape_valid`), so the merged body's award is
    # re-pointed to the body for its own re-derived holder domain, never
    # nulled.
    assert award.organisation.primary_domain == "foo.blogspot.com"
    assert award.holder_domain == "foo.blogspot.com"
    assert entry.organisation_id is None and entry.resolution == "UNRESOLVED"
    assert entry.contact_domain == ""
    assert partner.organisation_id is None and partner.disposition == "NO_KEY"
    assert partner.listed_domain == ""
    assert Organisation.objects.filter(id=kept.id).exists()
    assert "unkeyed 1 merged organisations" in out.getvalue()


def test_a_second_run_changes_nothing() -> None:
    _merged_blog_body()
    call_command("rederive_domains", stdout=StringIO())
    out = StringIO()
    call_command("rederive_domains", stdout=out)
    assert "unkeyed 0 merged organisations" in out.getvalue()
    assert "re-derived 0 holder domains, 0 partner domains, 0 contact domains" in out.getvalue()
