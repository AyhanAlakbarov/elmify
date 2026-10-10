"""A programme is judged by its own evidence, never by its Institution row (spec §3)."""

import pytest
from django.utils import timezone

from apps.funding.models import (
    Institution,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research.catalog import write_catalog_entry
from apps.research.discovery import LeadIdentity, ResearchLead
from apps.research.extraction import ExtractedClaims, TeachingLanguageClaim
from apps.research.hosts import registrable_domain
from apps.research.models import OrganisationDomain
from apps.research.provenance import evidence_of
from apps.research.spine import _origins

pytestmark = pytest.mark.django_db

CLAIMS = ExtractedClaims(
    duration_months=24,
    teaching_languages=(TeachingLanguageClaim(language="English", evidence="Taught in English."),),
    confidence=0.9,
)


@pytest.mark.parametrize(
    ("urls", "expected"),
    [
        ((), ("", False)),
        (("https://www.tum.de/a", "https://www.cit.tum.de/b"), ("tum.de", True)),
        (("https://www.tum.de/a", "https://blogs.tum.de/b"), ("tum.de", False)),
        (("https://www.tum.de/a", "https://www.lmu.de/b"), ("", False)),
        (("https://foo.github.io/msc",), ("foo.github.io", False)),
        (("https://192.0.2.1/msc",), ("", False)),
    ],
)
def test_evidence_of(urls, expected) -> None:
    assert evidence_of(urls) == expected


def _write(url: str, institution_name: str, program_name: str = "MSc Informatics"):
    source = OfficialSource.objects.create(
        canonical_url=url, publisher="x", source_type=OfficialSource.Type.PROGRAM
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, s3_key="k", s3_version_id="1", sha256="b" * 64, final_url=url,
        redirect_chain=[], retrieved_at=timezone.now(), admissions_cycle="2027",
        content_type="text/html", byte_size=10,
    )
    lead = ResearchLead.from_url(
        url, source_type="PROGRAM", funding_family="", discovered_by="test",
        identity=LeadIdentity(
            institution_name=institution_name, country_code="DE", city="Munich",
            program_name=program_name,
        ),
    )
    return write_catalog_entry(lead=lead, claims=CLAIMS, source=source, snapshot=snapshot)


def test_the_writer_records_the_evidence_domain_and_its_body() -> None:
    result = _write("https://www.tum.de/en/msc-informatics", "Technical University of Munich")
    assert result is not None
    assert (result.program.evidence_domain, result.program.evidence_institutional) == (
        "tum.de", True,
    )
    body = OrganisationDomain.objects.get(registrable_domain="tum.de").organisation
    assert body.kind == "INSTITUTION"
    assert body.country_code == ""  # the page's country is a claim, never evidence (§5.2)
    assert "CATALOG:programme" in body.found_via


def test_a_fake_page_naming_tums_programme_gets_its_own_row() -> None:
    """Spec §1's hole, closed at the programme: the Institution is found by name
    and so is TUM's, but a page from another domain naming the SAME programme
    gets its own Program row (origin_domain is part of the row's identity), so
    TUM's row keeps only TUM's evidence."""
    real = _write("https://www.tum.de/en/msc-informatics", "Technical University of Munich")
    fake = _write("https://tum-admissions.com/msc", "Technical University of Munich")
    assert real is not None and fake is not None
    assert fake.institution == real.institution == Institution.objects.get()
    assert Program.objects.count() == 2
    assert fake.program.id != real.program.id
    assert fake.program.evidence_domain == "tum-admissions.com"
    real.program.refresh_from_db()
    assert (real.program.origin_domain, real.program.evidence_domain) == ("tum.de", "tum.de")
    assert real.program.evidence_institutional
    real_urls = OfficialEvidenceClaim.objects.filter(program=real.program).values_list(
        "source__canonical_url", flat=True
    )
    shown = _origins((real.program,), ())
    assert {registrable_domain(url) for url in [*real_urls, *shown.values()]} == {"tum.de"}


def test_a_second_page_on_a_user_subdomain_marks_the_programme_non_institutional() -> None:
    first = _write("https://www.tum.de/en/msc-informatics", "Technical University of Munich")
    second = _write("https://blogs.tum.de/en/msc-informatics", "Technical University of Munich")
    assert first is not None and second is not None
    assert second.program.id == first.program.id
    second.program.refresh_from_db()
    assert (second.program.evidence_domain, second.program.evidence_institutional) == (
        "tum.de", False,
    )


def test_a_hosting_platform_programme_records_no_body() -> None:
    # Ruling B5: netlify.app, not github.io -- github.io is already an
    # AGGREGATOR domain in domains.py, so a lead on it never reaches the
    # writer (write_catalog_entry returns None, not a hosting-platform row).
    result = _write("https://tum-msc.netlify.app/apply", "Technical University of Munich")
    assert result is not None
    assert result.program.evidence_domain == "tum-msc.netlify.app"
    assert not OrganisationDomain.objects.filter(
        registrable_domain="tum-msc.netlify.app"
    ).exists()
