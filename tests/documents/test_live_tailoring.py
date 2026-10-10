"""One real CV and one real programme page, end to end, against the live API.

The handoff's open question was whether `extract_statements` had ever
seen a real page. It had not, and the first one it saw failed: FAU's AI M.Sc.
page is 422,515 characters of HTML whose first 24,000 -- the whole of the
model's input -- are `<head>` and inlined CSS. `reader.readable_text` is the
fix; this is the check that the fix holds against a page nobody controls.

Marked `live` (excluded by `pyproject.toml`'s `addopts`, like the Crossref and
GitHub tests in tests/documents/evidence/). It costs three model calls, and it
skips unless both inputs are named:

    LIVE_CV_PDF=/path/to/cv.pdf \
    LIVE_PROGRAM_URL=https://www.fau.eu/degree-program/artificial-intelligence-ai-m-sc/ \
    POSTGRES_DB=tehsil_ei uv run pytest tests/documents/test_live_tailoring.py -m live -s
"""

import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.utils import timezone
from openai import OpenAI

from apps.concierge.documents import register
from apps.documents.generation import generate_cv
from apps.documents.ingestion import ingest_uploaded_cv
from apps.documents.models import VerifiedFact
from apps.documents.render import render_cv
from apps.documents.tailoring import fact_pool, tailor_skills
from apps.documents.verification import generatable_facts
from apps.funding.models import Institution, OfficialSource, Program, ProgramStatement
from apps.research.reader import read_program_page
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.uploads import promoted_upload

pytestmark = [pytest.mark.django_db, pytest.mark.live]


class MemoryObjectStore:
    """Copied from tests/research/test_reader.py:269 -- not imported across modules."""

    def __init__(self) -> None:
        self.objects: list[tuple[str, bytes]] = []

    def put(self, key: str, body: bytes) -> str:
        self.objects.append((key, body))
        return "version-1"


def test_a_real_cv_against_a_real_programme_page(agency_a, django_user_model, fake_store, capsys):
    pdf_path = os.getenv("LIVE_CV_PDF")
    program_url = os.getenv("LIVE_PROGRAM_URL")
    if not pdf_path or not program_url:
        pytest.skip("set LIVE_CV_PDF and LIVE_PROGRAM_URL")

    client = OpenAI()
    # Names are cosmetic here: extract_statements is given page text and
    # nothing else, so nothing downstream reads them. Kept generic so the test
    # is not tied to the one programme it was first written against.
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name=os.getenv("LIVE_INSTITUTION", "Live Probe University"),
        country_code=os.getenv("LIVE_COUNTRY", "DE"),
        official_website=f"https://{urlsplit(program_url).hostname}",
    )
    program = Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name=os.getenv("LIVE_PROGRAM_NAME", "Live Probe Programme"),
        campus_name="Main Campus",
        city="Main Campus",
        country_code=os.getenv("LIVE_COUNTRY", "DE"),
        location_key="live:probe",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    source = OfficialSource.objects.create(
        canonical_url=program_url,
        publisher=os.getenv("LIVE_INSTITUTION", "Live Probe University"),
        source_type=OfficialSource.Type.PROGRAM,
    )

    read = read_program_page(
        program=program,
        source=source,
        store=MemoryObjectStore(),
        parser=client.responses,
        admissions_cycle="2027",
    )

    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username=f"live-{uuid4().hex[:8]}")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        document = promoted_upload(
            register(agency_a.id, student.id), fake_store, Path(pdf_path).read_bytes()
        )
        facts = ingest_uploaded_cv(
            document=document, student=student, client=client, store=fake_store
        )
        tailored = tailor_skills(
            student,
            list(ProgramStatement.objects.filter(program=program)),
            parser=client.responses,
        )

        with capsys.disabled():
            print(f"\n=== {len(facts)} facts from the CV ===")
            for category in VerifiedFact.Category:
                names = [f.payload for f in facts if f.category == category]
                if names:
                    print(f"{category.label}: {len(names)}")
            print(f"\n=== {len(read.statements)} statements the page made ===")
            for c in read.statements:
                print(f"  [{c.requirement:8}] {c.label}\n             <- {c.text[:120]}")
            print(f"\n=== printed skills, {tailored.basis} ===")
            for entry in tailored.printed:
                print(f"  {entry.name}")
            print(f"\n=== gaps ({len(tailored.gaps)}) ===")
            for gap in tailored.gaps:
                print(f"  {gap}")

        # The point of the run: a real page must yield real requirements, and
        # the pool must not be empty. Either being zero is the silent failure
        # this test exists to make loud. Inside the tenant_scope block, not
        # after it -- fact_pool reads a tenant-scoped manager.
        assert read.statements, "the programme page produced no statements"
        assert fact_pool(student), "the CV produced no facts"


def test_a_real_cv_is_confirmed_generated_and_rendered(
    agency_a, django_user_model, fake_store, capsys
):
    """The back half: candidate facts -> confirmed facts -> CVContent -> PDF.

    The front half above stops at a tailored list, which is an input to a CV
    and not a CV. Nothing it writes can reach a document: ingest_uploaded_cv
    writes every fact confirmed_by=None, generate_cv reads generatable_facts
    (unsuperseded AND confirmed), so an uploaded CV yields an empty prompt and
    generate_cv raises IdentityNotConfirmed on its first line. That gate is the
    anti-fabrication design and tests/documents/test_ingestion.py already pins
    it.

    So this test CONFIRMS EVERY FACT ITSELF, which in production is a human
    reading each candidate and accepting it. That step is simulated here and
    nowhere else -- do not lift this loop into application code.

    Writes the PDF to LIVE_CV_OUT when set. Two model calls, three if
    generate_cv retries.
    """
    pdf_path = os.getenv("LIVE_CV_PDF")
    if not pdf_path:
        pytest.skip("set LIVE_CV_PDF")

    client = OpenAI()
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username=f"live-{uuid4().hex[:8]}")
        student = Membership.objects.create(
            tenant=agency_a,
            user=user,
            role=Membership.Role.STUDENT,
            active=True,
            application_email=f"live-{uuid4().hex[:8]}@apply.example.test",
        )
        document = promoted_upload(
            register(agency_a.id, student.id), fake_store, Path(pdf_path).read_bytes()
        )
        facts = ingest_uploaded_cv(
            document=document, student=student, client=client, store=fake_store
        )
        assert not generatable_facts(student).exists(), "an upload must start invisible"

        # The simulated human. See the docstring.
        VerifiedFact.objects.filter(id__in=[f.id for f in facts]).update(
            confirmed_by=student, confirmed_at=timezone.now()
        )

        result = generate_cv(student=student, client=client)
        # constraints=() -- the catalog rules are seeded by a management
        # command and this DB has none, so no page limit is enforced here.
        artifact = render_cv(result.content, variant="STANDARD")

        with capsys.disabled():
            print(f"\n=== generated CV, retried={result.retried} ===")
            print(f"pages={artifact.page_count} bytes={artifact.byte_size}")
            content = result.content
            print(
                f"name={content.personal_information.full_name!r} "
                f"edu={len(content.education)} exp={len(content.experience)} "
                f"res={len(content.research)} pub={len(content.publications)} "
                f"skills={len(content.skills)} lang={len(content.languages)}"
            )
            blocking = [v for v in result.verdicts if v.verdict == "UNSUPPORTED"]
            print(f"verdicts={len(result.verdicts)} unsupported={len(blocking)}")
            for verdict in blocking[:10]:
                print(f"  UNSUPPORTED: {verdict}")
            out = os.getenv("LIVE_CV_OUT")
            if out and artifact.pdf_bytes:
                Path(out).write_bytes(artifact.pdf_bytes)
                print(f"wrote {out}")

    assert artifact.pdf_bytes, "no PDF produced"


def test_a_programmes_own_rules_land_on_top_of_the_standard_ones(
    agency_a, django_user_model, fake_store, capsys
):
    """The whole stack, once: catalog rules under a programme's own.

    The two halves above stop short of the thing the layering exists for. This
    one seeds the curated catalog, reads a real programme page for that
    programme's OWN rules, resolves the two together through
    constraints.resolve_rules, and renders with the result -- so what comes out
    is a CV the destination's stated requirements have actually acted on, and
    the printout says which rule came from where.

    Precedence is resolve_rules': UNIVERSAL < TRACK < COUNTRY < INSTITUTION <
    FUNDER < the programme's own, with the one guard that a programme rule may
    never LOWER a key's enforcement (an advisory sentence off a third-party page
    must not delete a funder's BINDING requirement -- see that function).

    Costs a page fetch and up to eight model calls: six for read_and_derive
    (three statement reads, three judgements) and two for generation.

        LIVE_CV_PDF=/path/to/cv.pdf \
        LIVE_PROGRAM_URL=https://... \
        LIVE_FUNDER=daad-study-scholarships \
        LIVE_CV_OUT=/tmp/tailored.pdf \
        POSTGRES_DB=tehsil_ei uv run pytest \
          tests/documents/test_live_tailoring.py -m live -s \
          -k programmes_own_rules
    """
    pdf_path = os.getenv("LIVE_CV_PDF")
    program_url = os.getenv("LIVE_PROGRAM_URL")
    if not pdf_path or not program_url:
        pytest.skip("set LIVE_CV_PDF and LIVE_PROGRAM_URL")

    from apps.documents.catalog_seed import SEED_FUNDERS, seed_cv_rules
    from apps.documents.constraints import directives_from_program, resolve_rules
    from apps.documents.program_rules import read_and_derive
    from apps.documents.render import render_cv_with_warnings
    from apps.funding.models import FundingFamily, FundingOpportunity, OpportunityScope

    client = OpenAI()
    # seed_cv_rules refuses to load a FUNDER-scoped rule whose funder is not
    # already in the catalog -- correctly, since a rule scoped to nobody
    # reaches no CV and says nothing about it. In production those rows arrive
    # through the discovery pipeline; here the test stands in for it.
    for canonical_key, name, _requirement in SEED_FUNDERS:
        FundingOpportunity.objects.get_or_create(
            canonical_key=canonical_key,
            defaults={
                "name": name,
                "family": FundingFamily.GOVERNMENT_SCHOLARSHIP,
                "scope_type": OpportunityScope.GLOBAL,
            },
        )
    seeded = seed_cv_rules()

    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name=os.getenv("LIVE_INSTITUTION", "Live Probe University"),
        country_code=os.getenv("LIVE_COUNTRY", "DE"),
        official_website=f"https://{urlsplit(program_url).hostname}",
    )
    program = Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name=os.getenv("LIVE_PROGRAM_NAME", "Live Probe Programme"),
        campus_name="Main Campus",
        city="Main Campus",
        country_code=os.getenv("LIVE_COUNTRY", "DE"),
        location_key="live:probe",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    source = OfficialSource.objects.create(
        canonical_url=program_url,
        publisher=institution.name,
        source_type=OfficialSource.Type.PROGRAM,
    )
    # The funder layer. canonical_key is what CatalogRule's FUNDER scope
    # matches on, so this has to be a key SEED_FUNDERS actually carries.
    funder_key = os.getenv("LIVE_FUNDER", "daad-study-scholarships")
    opportunity = FundingOpportunity.objects.get(canonical_key=funder_key)

    read = read_and_derive(
        program=program,
        source=source,
        store=MemoryObjectStore(),
        parser=client.responses,
        admissions_cycle="2027",
    )
    program.refresh_from_db()

    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username=f"live-{uuid4().hex[:8]}")
        student = Membership.objects.create(
            tenant=agency_a,
            user=user,
            role=Membership.Role.STUDENT,
            active=True,
            application_email=f"live-{uuid4().hex[:8]}@apply.example.test",
        )
        document = promoted_upload(
            register(agency_a.id, student.id), fake_store, Path(pdf_path).read_bytes()
        )
        facts = ingest_uploaded_cv(
            document=document, student=student, client=client, store=fake_store
        )
        # The simulated human, exactly as the test above: see its docstring,
        # and do not lift this loop into application code.
        VerifiedFact.objects.filter(id__in=[f.id for f in facts]).update(
            confirmed_by=student, confirmed_at=timezone.now()
        )

        result = generate_cv(student=student, client=client, programme=program)
        rules = resolve_rules(program, opportunity, content=result.content)
        directives = directives_from_program(program)
        artifact, violations = render_cv_with_warnings(
            result.content,
            variant="STANDARD",
            constraints=rules,
            directives=directives,
        )

        with capsys.disabled():
            print(f"\n=== catalog seeded: {seeded} ===")
            print(f"=== the page said {len(read.statements)} things; "
                  f"{len(program.cv_constraints)} became rules, "
                  f"{len(program.cv_directives)} became directives ===")
            for rule in program.cv_constraints:
                print(f"  PROGRAMME  {rule.get('key')}={rule.get('value')!r} "
                      f"[{rule.get('enforcement')}] {str(rule.get('rule_text'))[:90]}")
            for directive in program.cv_directives:
                print(f"  DIRECTIVE  {directive.get('action')} {directive.get('target')} "
                      f"{directive.get('value') or ''}")
            print(f"\n=== {len(rules)} rules resolved for this application ===")
            for rule in sorted(rules, key=lambda r: r.key):
                print(f"  {rule.rule_id:12} {rule.key:28} = {str(rule.value)[:28]:28} "
                      f"[{rule.enforcement}]")
            print(f"\n=== rendered: pages={artifact.page_count} "
                  f"bytes={artifact.byte_size} violations={len(violations)} ===")
            for violation in violations:
                print(f"  VIOLATION {violation}")
            out = os.getenv("LIVE_CV_OUT")
            if out and artifact.pdf_bytes:
                Path(out).write_bytes(artifact.pdf_bytes)
                print(f"wrote {out}")

    assert artifact.pdf_bytes, "no PDF produced"
    assert rules, "no rules resolved -- the catalog seed or the scope match is wrong"
