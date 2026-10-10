"""Builders shared by the provenance-gate tests. Catalogue rows only; no network."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit
from uuid import uuid4

from django.utils import timezone

from apps.funding.models import (
    Institution,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramEvidenceClaim,
)
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.hosts import registrable_domain
from apps.research.models import ClosedList, Organisation, ProvenanceVerdict, RegisterEntry
from apps.research.provenance import evidence_of, record_verdict, verdict_of
from apps.research.register import record_organisation


def make_body(domain: str, *, kind: str = "INSTITUTION", country_code: str = "") -> Organisation:
    return record_organisation(
        domain=domain, name=domain, kind=kind, country_code=country_code, found_via="TEST"
    )


def make_list(
    slug: str,
    *,
    country_code: str = "",
    terms: str = "OPEN",
    printed_size: int | None = None,
    source_url: str = "https://register.example.test/list",
    holder_kinds: tuple[str, ...] = ("INSTITUTION",),
) -> ClosedList:
    return ClosedList.objects.create(
        slug=slug, title=slug, country_code=country_code, holder_kinds=list(holder_kinds),
        rung=1, source_url=source_url, maintainer="test", carries_purpose=False,
        carries_website=True, reuse_terms=terms, is_denominator=True,
        read_policy="ENUMERATE_ONLY", printed_size=printed_size,
        verified_on=date(2026, 9, 26),
    )


def page(
    url: str,
    html: str | bytes,
    *,
    final_url: str | None = None,
    outcome: Outcome = Outcome.FETCHED,
    content_type: str = "text/html",
) -> FetchedPage:
    body = html.encode() if isinstance(html, str) else html
    return FetchedPage(
        final_url=final_url or url, redirects=(), content_type=content_type, body=body,
        fetched_via="FIRECRAWL", outcome=outcome,
    )


@dataclass
class FakeFetch:
    """`fetch_page` stand-in: a URL it does not hold answers DEAD, bodiless."""

    pages: Mapping[str, FetchedPage]
    calls: list[str] = field(default_factory=list)

    def __call__(self, url: str, **_kwargs: object) -> FetchedPage:
        self.calls.append(url)
        return self.pages.get(url) or page(url, b"", outcome=Outcome.DEAD)


@dataclass
class HomeFetch(FakeFetch):
    """`FakeFetch` whose `homes` domains each serve a homepage that names the
    body: the name on the domain's register row, else its Organisation's name.
    Any other URL it does not hold answers DEAD, like FakeFetch."""

    homes: frozenset[str] = field(default_factory=frozenset)

    def __call__(self, url: str, **_kwargs: object) -> FetchedPage:
        self.calls.append(url)
        if url in self.pages:
            return self.pages[url]
        domain = registrable_domain(url)
        if domain not in self.homes:
            return page(url, b"", outcome=Outcome.DEAD)
        name = (
            RegisterEntry.objects.filter(website_domain=domain).order_by("pk")
            .values_list("name", flat=True).first()
            or Organisation.objects.filter(domains__registrable_domain=domain).order_by("pk")
            .values_list("name", flat=True).first()
        )
        if name is None:
            return page(url, "<html><head><title></title></head><body></body></html>")
        return page(
            url,
            f"<html><head><title>{name}</title></head><body><header>{name}</header>"
            "<main>Welcome</main></body></html>",
        )


@dataclass
class SiteFetch(FakeFetch):
    """Every URL on `site` (by registrable domain) answers `html`, landing on
    `landed` when set; anything else answers DEAD. For tests that must not
    depend on which exact URL form a caller asks for first."""

    site: str = ""
    html: str = ""
    landed: str | None = None

    def __call__(self, url: str, **_kwargs: object) -> FetchedPage:
        self.calls.append(url)
        if registrable_domain(url) != self.site:
            return page(url, b"", outcome=Outcome.DEAD)
        return page(url, self.html, final_url=self.landed)


def attach_evidence(program: Program, *urls: str) -> list[OfficialEvidenceClaim]:
    claims = []
    for url in urls:
        source, _ = OfficialSource.objects.get_or_create(
            canonical_url=url,
            defaults={"publisher": urlsplit(url).hostname or url, "source_type": "PROGRAM"},
        )
        claim = OfficialEvidenceClaim.objects.create(
            source=source, claim=f"{program.name} is offered", evidence_strength="DIRECT",
            visibility="STUDENT_FACING", claim_class="IDENTITY", last_checked_at=timezone.now(),
        )
        ProgramEvidenceClaim.objects.create(program=program, evidence_claim=claim)
        claims.append(claim)
    all_urls = OfficialEvidenceClaim.objects.filter(program=program).values_list(
        "source__canonical_url", flat=True
    )
    domain, institutional = evidence_of(all_urls)
    Program.objects.filter(id=program.id).update(
        evidence_domain=domain, evidence_institutional=institutional
    )
    program.refresh_from_db()
    return claims


def evidence_program(
    *urls: str,
    name: str = "MSc Computer Science",
    institution: Institution | None = None,
    joint: bool = False,
) -> Program:
    """A programme whose OfficialEvidenceClaims sit on `urls`, with its evidence
    columns set the way the catalogue writer sets them. `joint` makes a JOINT
    programme, which carries no Institution (Program's provision-type check)."""
    if joint:
        institution = None
    else:
        institution = institution or Institution.objects.create(
            canonical_key=f"institution:{uuid4()}", name="Example University",
            country_code="DE", official_website="https://university.example.test/",
        )
    program = Program.objects.create(
        institution=institution, canonical_key=f"program:{uuid4()}", name=name,
        campus_name="Main", city="Munich", country_code="DE", location_key=f"de:{uuid4()}",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
        provision_type="JOINT" if joint else "SINGLE", provider_text="A; B" if joint else "",
    )
    attach_evidence(program, *urls)
    return program


@dataclass
class FakeStore:
    objects: dict[str, bytes] = field(default_factory=dict)

    def put(self, key: str, body: bytes) -> str:
        self.objects[key] = body
        return "test-version"

    def get(self, key: str) -> bytes:
        return self.objects[key]


def attach_snapshot(claim: OfficialEvidenceClaim, text: str, store: FakeStore) -> None:
    key = f"official-sources/{uuid4()}"
    snapshot = OfficialSourceSnapshot.objects.create(
        source=claim.source, s3_key=key, s3_version_id="1", sha256=uuid4().hex * 2,
        final_url=claim.source.canonical_url, redirect_chain=[], retrieved_at=timezone.now(),
        admissions_cycle="2027", content_type="text/html", byte_size=len(text),
    )
    OfficialEvidenceClaim.objects.filter(id=claim.id).update(snapshot=snapshot)
    store.objects[key] = f"<p>{text}</p>".encode()


def recognise(
    organisation: Organisation, bound_domain: str, reason: str = "register", *, now=None
) -> ProvenanceVerdict:
    return record_verdict(
        organisation, bound_domain, verdict=verdict_of(reason), reason_code=reason,
        evidence={}, now=now or timezone.now(), next_check_at=None,
    )
