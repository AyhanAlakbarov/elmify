"""Tests for the 5-Breakthrough Programme & Scholarship Scraping Pipeline."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.accounts.schemas import Money
from apps.funding.fx import RateTable
from apps.funding.models import (
    CostComponent,
    Institution,
    OfficialEvidenceClaim,
    Period,
    Program,
    ProgramStatement,
)
from apps.funding.rates import store
from apps.funding.requirements import program_requirements
from apps.research.card_engine import Limit
from apps.research.card_engine.readers import Attempt, Prompt, ReaderSpec, Reply, Stack
from apps.research.card_engine.screen import Screen
from apps.research.programme_scraper import (
    build_programme_bundle,
    classify_programme_sublinks,
    extract_institution_base_profile,
    extract_tier0_programme_facts,
    is_page_unchanged,
    persist_programme_scrape,
    refine_with_dual_readers,
    scrape_programme_pages,
)
from apps.research.spine import build_student_pack
from apps.research.structured_html import extract_jsonld_lines, extract_table_and_dl_lines
from tests.funding.conftest import make_profile
from tests.research.provenance_helpers import attach_evidence, make_body, recognise

pytestmark = pytest.mark.django_db(transaction=True)


def _make_program(
    *,
    country_code: str = "NL",
    domain: str = "utwente.nl",
    name: str = "M.Sc. in Computer Science",
) -> Program:
    suffix = uuid4().hex[:6]
    inst = Institution.objects.create(
        canonical_key=f"inst:{country_code}:{suffix}",
        name=f"University of {domain} {suffix}",
        country_code=country_code,
        official_website=f"https://www.{domain}/",
    )
    prog = Program.objects.create(
        institution=inst,
        canonical_key=f"prog:{country_code}:{suffix}",
        name=name,
        campus_name="Main",
        city="Enschede",
        country_code=country_code,
        location_key=f"{country_code}-ENS-{suffix}",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    url = f"https://www.{domain}/programmes/{suffix}"
    attach_evidence(prog, url)
    body_org = make_body(domain, country_code=country_code)
    recognise(body_org, domain)
    return prog


def test_jsonld_and_2d_table_dl_extraction_disambiguates_eu_vs_non_eu() -> None:
    """Breakthrough 3: Rung 0 JSON-LD verifies visible presence (blocking spoofed JSON),
    and 2D `<table>` / `<dl>` coordinate binding disambiguates EU vs. Non-EU tuition."""
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "EducationalOccupationalProgram",
          "name": "M.Sc. in Artificial Intelligence",
          "timeToComplete": "P24M",
          "inLanguage": "English",
          "offers": {
            "@type": "Offer",
            "category": "International Non-EU Tuition",
            "price": "15,200",
            "priceCurrency": "EUR"
          },
          "applicationDeadline": "2099-12-31"
        }
        </script>
      </head>
      <body>
        <h1>M.Sc. in Artificial Intelligence</h1>
        <p>This two-year Master's programme (24 months) is taught in English.</p>
        <h2>Tuition Fees and Deadlines</h2>
        <table>
          <thead>
            <tr>
              <th>Item</th>
              <th>EU/EEA citizens</th>
              <th>Non-EU / International students</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>Annual Tuition Fee</th>
              <td>EUR 2,530</td>
              <td>EUR 15,200</td>
            </tr>
            <tr>
              <th>Application Deadline</th>
              <td>1 July 2027</td>
              <td>1 May 2027</td>
            </tr>
          </tbody>
        </table>
        <dl>
          <dt>Application fee (Non-EU)</dt>
          <dd>EUR 100</dd>
          <dt>English proficiency</dt>
          <dd>Minimum IELTS 6.5 or TOEFL iBT 90</dd>
        </dl>
      </body>
    </html>
    """
    jsonld_lines = extract_jsonld_lines(html)
    # "15,200" and "English" appear in visible text, but spoofed "2099-12-31" does not!
    jsonld_texts = " ".join(line.text for line in jsonld_lines)
    assert "EUR 15,200" in jsonld_texts
    assert "2099-12-31" not in jsonld_texts

    table_dl_lines = extract_table_and_dl_lines(html)
    headers_and_texts = [(line.header, line.text) for line in table_dl_lines]
    assert (
        "Annual Tuition Fee | Non-EU / International students",
        "EUR 15,200",
    ) in headers_and_texts
    assert ("Application fee (Non-EU)", "EUR 100") in headers_and_texts

    bundle = build_programme_bundle(
        [("https://www.utwente.nl/msc-ai", html)],
        title="M.Sc. in Artificial Intelligence",
    )
    res = extract_tier0_programme_facts(bundle)

    tuition = next(c for c in res.costs if c.kind == "TUITION")
    assert tuition.amount == Decimal("15200")
    assert tuition.currency == "EUR"
    assert tuition.audience == "INTERNATIONAL"

    app_fee = next(c for c in res.costs if c.kind == "APPLICATION_FEE")
    assert app_fee.amount == Decimal("100")
    assert app_fee.currency == "EUR"

    deadline = next(e for e in res.eligibility if e.kind == "DEADLINE")
    assert deadline.value == "2027-05-01"
    assert deadline.audience == "INTERNATIONAL"

    langs = {(e.label, e.value) for e in res.eligibility if e.kind == "LANGUAGE"}
    assert ("IELTS", "6.5") in langs
    assert ("TOEFL iBT", "90") in langs


def test_multi_page_bundle_resolves_cross_page_fee_category_coreference() -> None:
    """Breakthrough 2: Sublink router + multi-page bundle resolves 'Tuition Category B'
    on the front-door page against the fee schedule table on '/tuition-fees'."""
    front_url = "https://www.polimi.it/programmes/msc-data-science"
    front_html = """
    <html>
      <body>
        <h1>M.Sc. in Data Science and Engineering</h1>
        <p>Duration: 120 ECTS. Language of instruction: English.</p>
        <p>International students enrolled in this programme pay Tuition Category B.</p>
        <nav>
          <a href="/en/tuition-and-fees">Tuition and Financial Aid</a>
          <a href="/en/admissions/documents-checklist">Required Documents Checklist</a>
          <a href="/en/bachelor-computer-science">Bachelor Programme</a>
        </nav>
      </body>
    </html>
    """
    tuition_url = "https://www.polimi.it/en/tuition-and-fees"
    tuition_html = """
    <html>
      <body>
        <h2>International Non-EU Tuition Fee Schedule</h2>
        <table>
          <tr><th>Fee Band</th><th>Annual Tuition (Non-EU)</th></tr>
          <tr><th>Category A</th><td>EUR 9,000</td></tr>
          <tr><th>Category B</th><td>EUR 14,500</td></tr>
          <tr><th>Category C</th><td>EUR 19,500</td></tr>
        </table>
      </body>
    </html>
    """
    docs_url = "https://www.polimi.it/en/admissions/documents-checklist"
    docs_html = """
    <html>
      <body>
        <h2>Application Documents</h2>
        <ul>
          <li>Curriculum Vitae: Europass CV format is mandatory for all applicants.</li>
          <li>Motivation letter explaining your academic goals (required).</li>
          <li>Two letters of recommendation from academic professors.</li>
        </ul>
      </body>
    </html>
    """

    sublinks = classify_programme_sublinks(front_url, front_html)
    assert sublinks.tuition_and_fees == tuition_url
    assert sublinks.documents_and_checklist == docs_url
    # Bachelor link was filtered out by _names_another_degree
    assert "bachelor" not in " ".join(sublinks.as_tuple())

    bundle = build_programme_bundle(
        [
            (front_url, front_html),
            (tuition_url, tuition_html),
            (docs_url, docs_html),
        ],
        title="M.Sc. in Data Science and Engineering",
    )
    res = extract_tier0_programme_facts(bundle)

    assert res.fee_category_ref == "B"
    assert res.duration_months == 24
    assert res.teaching_languages == ("English",)
    tuition = next(c for c in res.costs if c.kind == "TUITION")
    assert tuition.amount == Decimal("14500")
    assert tuition.currency == "EUR"
    assert tuition.source_url == tuition_url
    assert res.cv_format == "europass_required"
    assert res.cv_format_source_url == docs_url
    assert res.letter_required == "required"
    assert res.referee_requirements[0]["value"] == "TWO"


def test_institution_base_profile_factoring_across_multiple_programmes() -> None:
    """Breakthrough 1: `InstitutionBaseProfile` extracts university-wide tuition categories,
    application fees, language floors, and deadlines once per domain so individual programmes
    only scrape their delta."""
    central_tuition_url = "https://www.kuleuven.be/tuition-fees"
    central_tuition_html = """
    <html>
      <body>
        <h2>Central Tuition Schedule for Non-EEA Master's Students</h2>
        <table>
          <tr><th>Tariff Group</th><th>Non-EEA Annual Tuition</th></tr>
          <tr><th>Category A</th><td>EUR 1,800</td></tr>
          <tr><th>Category B</th><td>EUR 7,500</td></tr>
        </table>
        <p>Non-EEA application fee: EUR 90.</p>
      </body>
    </html>
    """
    central_adm_url = "https://www.kuleuven.be/admissions"
    central_adm_html = """
    <html>
      <body>
        <h2>General Master's Admission Requirements</h2>
        <p>Minimum English requirement: IELTS 7.0 or CEFR C1.</p>
        <p>Non-EEA application deadline: 1 March 2027.</p>
      </body>
    </html>
    """
    base_profile = extract_institution_base_profile(
        "kuleuven.be",
        [
            (central_tuition_url, central_tuition_html),
            (central_adm_url, central_adm_html),
        ],
    )
    assert set(base_profile.tuition_by_category.keys()) == {"A", "B"}
    assert base_profile.tuition_by_category["A"].amount == Decimal("1800")
    assert base_profile.tuition_by_category["B"].amount == Decimal("7500")
    assert base_profile.application_fee is not None
    assert base_profile.application_fee.amount == Decimal("90")

    # Programme 1 only mentions Category B and 120 ECTS on its thin page
    prog1_html = (
        "<html><body><h1>M.Sc. in Robotics</h1>"
        "<p>120 ECTS. Fee Category B applies.</p></body></html>"
    )
    prog1_bundle = build_programme_bundle(
        [("https://www.kuleuven.be/msc-robotics", prog1_html)],
        base_profile=base_profile,
    )
    res1 = extract_tier0_programme_facts(prog1_bundle, base_profile=base_profile)
    tuition1 = next(c for c in res1.costs if c.kind == "TUITION")
    app1 = next(c for c in res1.costs if c.kind == "APPLICATION_FEE")
    assert tuition1.amount == Decimal("7500")
    assert app1.amount == Decimal("90")
    assert any(e.label == "IELTS" and e.value == "7.0" for e in res1.eligibility)
    assert any(e.kind == "DEADLINE" and e.value == "2027-03-01" for e in res1.eligibility)


def test_tier1_dual_reader_and_tier2_risk_asymmetric_arbitration() -> None:
    """Breakthrough 5: When a page says 'Tuition-free for exchange students from partner
    universities', Tier 0 flags `conditional_free_tuition`. Even if both cheap Tier 1 readers
    mistakenly agree `tuition_free_all_internationals = 'yes'`, `needs_high_risk_arbitration`
    escalates to the Tier 2 frontier decider, which overrides the decision to `'no'`."""
    html = """
    <html>
      <body>
        <h1>M.Sc. in International Economics</h1>
        <p>The programme is tuition-free for exchange students from partner universities.</p>
      </body>
    </html>
    """
    bundle = build_programme_bundle(
        [("https://www.uni-example.org/msc-econ", html)],
        title="M.Sc. in International Economics",
    )
    tier0 = extract_tier0_programme_facts(bundle)
    assert "conditional_free_tuition" in tier0.high_risk_flags
    assert not any(c.kind == "TUITION" and c.amount == Decimal("0.00") for c in tier0.costs)

    test_readers = Stack(
        pair=(
            ReaderSpec("cheap-a", "openrouter", "openai/gpt-5.4-nano", host="OpenAI"),
            ReaderSpec("cheap-b", "openrouter", "google/gemini-3.1-flash-lite", host="Google"),
        ),
        decider=ReaderSpec("frontier-decider", "anthropic", "claude-opus-4-7"),
    )
    called_models: list[str] = []

    def fake_transport(reader: ReaderSpec, prompt: Prompt) -> Attempt:
        called_models.append(reader.name)
        if reader.name in ("cheap-a", "cheap-b"):
            # Both cheap readers fall for the conditional trap and answer "yes"
            return Attempt(
                reply=Reply.model_validate(
                    {
                        "answers": [
                            {
                                "id": "tuition_free_all_internationals",
                                "value": "yes",
                                "quote": "tuition-free",
                            }
                        ]
                    }
                ),
                reason="",
                cost_usd=0.0002,
                latency_s=0.1,
            )
        # The frontier decider reads the partner-university condition and answers "no"
        return Attempt(
            reply=Reply.model_validate(
                {
                    "answers": [
                        {
                            "id": "tuition_free_all_internationals",
                            "value": "no",
                            "quote": "",
                        }
                    ]
                }
            ),
            reason="",
            cost_usd=0.003,
            latency_s=0.2,
        )

    refined = refine_with_dual_readers(
        bundle,
        tier0,
        screen=Screen("clear", frozenset(bundle.section.texts())),
        limit=Limit("test-bucket", 1, 100, 3600),
        readers=test_readers,
        transport=fake_transport,
    )
    assert set(called_models[:2]) == {"cheap-a", "cheap-b"}
    assert called_models[2] == "frontier-decider"
    dec = next(d for d in refined.decisions if d.question == "tuition_free_all_internationals")
    assert dec.status == "decided"
    assert dec.value == "no"
    assert not any(c.kind == "TUITION" and c.amount == Decimal("0.00") for c in refined.costs)


def test_two_stage_persistence_sha256_gate_and_real_caller_integration() -> None:
    """Breakthrough 4 & Real Callers: Two-stage persistence (`gate_and_money` then `full`),
    SHA-256 Digest Gate short-circuiting unchanged HTML, and end-to-end verification with
    `program_requirements` and `build_student_pack`."""
    rates = RateTable(
        base="AZN",
        rates={"AZN": Decimal("1"), "EUR": Decimal("0.54"), "USD": Decimal("0.59")},
        source="CBAR",
        retrieved_on=timezone.now().date(),
    )
    store(rates)
    prog = _make_program(
        country_code="NL", domain="utwente.nl", name="M.Sc. in Computer Science"
    )
    front_url = "https://www.utwente.nl/programmes/msc-computer-science"
    docs_url = "https://www.utwente.nl/programmes/msc-computer-science/documents"

    front_html = f"""
    <html>
      <body>
        <h1>M.Sc. in Computer Science</h1>
        <p>Duration: 24 months (120 ECTS). Taught in English.</p>
        <p>Non-EU / International tuition fee: EUR 8,000 per semester.</p>
        <p>Application fee for international students: EUR 100.</p>
        <p>Minimum English score: IELTS 6.5. Minimum GPA: 3.2 out of 4.0.</p>
        <p>International application deadline: 1 May 2027.</p>
        <a href="{docs_url}">Required Application Documents and Checklist</a>
      </body>
    </html>
    """
    docs_html = """
    <html>
      <body>
        <h2>Application Documents Checklist</h2>
        <ul>
          <li>Europass CV format is required for all candidates.</li>
          <li>Motivation letter (maximum 2 pages) is required.</li>
          <li>Two letters of recommendation from academic referees.</li>
          <li>Official academic transcripts and diploma supplement.</li>
          <li>Digital portfolio of embedded design projects.</li>
        </ul>
      </body>
    </html>
    """

    fetched_urls: list[str] = []

    def fake_fetch(u: str) -> str | None:
        fetched_urls.append(u)
        if u == docs_url:
            return docs_html
        return None

    # Stage A: gate_and_money (does NOT fetch documents sub-page or write ProgramStatements)
    scrape_programme_pages(
        prog,
        front_url,
        front_html,
        fetch_fn=fake_fetch,
        stage="gate_and_money",
    )
    assert docs_url not in fetched_urls
    # EUR 8,000 per semester -> EUR 16,000 ANNUAL
    tuition_row = CostComponent.objects.get(program=prog, kind="TUITION")
    assert tuition_row.amount == Decimal("16000.00")
    assert tuition_row.period == Period.ANNUAL
    assert CostComponent.objects.filter(
        program=prog, kind="APPLICATION_FEE", amount=Decimal("100.00")
    ).exists()
    assert OfficialEvidenceClaim.objects.filter(program=prog, claim_class="ELIGIBILITY").exists()
    assert OfficialEvidenceClaim.objects.filter(program=prog, claim_class="DEADLINE").exists()
    claims_after_stage_a = OfficialEvidenceClaim.objects.filter(program=prog).count()

    # Stage B: full (fetches documents sub-page and populates ProgramStatements & CV/Letter fields)
    scrape_programme_pages(
        prog,
        front_url,
        front_html,
        fetch_fn=fake_fetch,
        stage="full",
    )
    assert docs_url in fetched_urls
    # Idempotency check: Stage B does not duplicate existing TUITION/ELIGIBILITY/DEADLINE claims
    assert OfficialEvidenceClaim.objects.filter(program=prog).count() == claims_after_stage_a
    prog.refresh_from_db()
    assert prog.cv_format_requirement == "europass_required"
    assert prog.letter_required == "required"
    assert prog.portfolio_led is True
    assert prog.referee_requirements and prog.referee_requirements[0]["value"] == "TWO"
    assert ProgramStatement.objects.filter(program=prog, kind="DOCUMENT").count() >= 4
    assert ProgramStatement.objects.filter(program=prog, kind="LANGUAGE").exists()
    assert ProgramStatement.objects.filter(program=prog, kind="COMPETENCY").exists()

    # SHA-256 Digest Gate: calling scrape_programme_pages again on identical HTML short-circuits!
    assert is_page_unchanged(front_url, front_html) is True
    fetched_urls.clear()
    res_cached = scrape_programme_pages(
        prog,
        front_url,
        front_html,
        fetch_fn=fake_fetch,
        stage="full",
    )
    assert fetched_urls == []
    assert res_cached.cost_usd == 0.0

    # Real Caller 1: `program_requirements` (apps/funding/requirements.py)
    reqs = program_requirements(prog, cycle="2027")
    assert any(item.text == "europass_required" for item in reqs.cv)
    applicant_texts = " | ".join(item.text for item in reqs.applicant)
    assert "IELTS" in applicant_texts
    assert "3.2" in applicant_texts

    # Real Caller 2: `build_student_pack` (apps/research/spine.py)
    profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        allowed_countries=("NL",),
        target_field="Computer Science",
        research_interests=(),
        self_funding_capacity=Money(amount=Decimal("25000"), currency="EUR"),
    )
    spine_res = build_student_pack(profile, rates=rates, today=timezone.now().date())
    paid_ids = [card.program_id for card in spine_res.pack.paid]
    assert str(prog.id) in paid_ids
    paid_card = next(c for c in spine_res.pack.paid if c.program_id == str(prog.id))
    assert paid_card.application_fee == Decimal("100.00")
    assert paid_card.application_fee_currency == "EUR"
    assert paid_card.costed is True
    # 2 years * EUR 16,000 + EUR 100 = EUR 32,100 -> ~59,444 AZN
    assert paid_card.gap > Decimal("50000")


def test_edge_cases_per_ects_tuition_semesterbeitrag_and_french_free_application() -> None:
    """Verify edge-case guards:
    1. Per-ECTS tuition (`EUR 65 per ECTS`) scales by 60 ECTS/year -> `EUR 3,900` ANNUAL.
    2. Non-ECTS per-credit tuition (`USD 1,200 per credit`) is marked unresolved.
    3. German `Semesterbeitrag` (`EUR 315`) under 'Tuition and Semester Fees' does not override
       `Keine Studiengebühren` (`0.00 EUR` tuition).
    4. French 'Le dossier de candidature est gratuit' does not trigger a false `0.00 EUR` row.
    """
    # 1. Per-ECTS tuition -> 60 ECTS/year
    ects_bundle = build_programme_bundle(
        [
            (
                "https://www.uab.cat/msc-ai",
                "<html lang='en'><body><h1>M.Sc. in AI</h1>"
                "<p>Non-EU tuition fee: EUR 65 per ECTS.</p></body></html>",
            )
        ]
    )
    ects_res = extract_tier0_programme_facts(ects_bundle)
    tuition_ects = next(c for c in ects_res.costs if c.kind == "TUITION")
    assert tuition_ects.amount == Decimal("3900")
    assert tuition_ects.period == "ANNUAL"

    # 2. Non-ECTS per-credit -> unresolved_slots, not misrecorded as annual
    credit_bundle = build_programme_bundle(
        [
            (
                "https://www.example.edu/ms-cs",
                "<html lang='en'><body><h1>M.S. in CS</h1>"
                "<p>International tuition: USD 1,200 per credit.</p></body></html>",
            )
        ]
    )
    credit_res = extract_tier0_programme_facts(credit_bundle)
    assert "tuition" in credit_res.unresolved_slots
    assert not any(c.kind == "TUITION" for c in credit_res.costs)

    # 3. German Semesterbeitrag under a Tuition heading does not override Keine Studiengebühren
    de_bundle = build_programme_bundle(
        [
            (
                "https://www.rwth-aachen.de/msc-cs",
                "<html lang='de'><body><h2>Studiengebühren und Semesterbeitrag</h2>"
                "<p>Es werden keine Studiengebühren erhoben.</p>"
                "<p>Der Semesterbeitrag beträgt EUR 315 pro Semester.</p></body></html>",
            )
        ]
    )
    de_res = extract_tier0_programme_facts(de_bundle)
    tuition_de = next(c for c in de_res.costs if c.kind == "TUITION")
    assert tuition_de.amount == Decimal("0.00")

    # 4. French 'Le dossier de candidature est gratuit' does not trigger false 0 EUR tuition
    fr_bundle = build_programme_bundle(
        [
            (
                "https://www.sorbonne.fr/master-info",
                "<html lang='fr'><body><h1>Master Informatique</h1>"
                "<p>Le dossier de candidature est gratuit pour tous.</p></body></html>",
            )
        ]
    )
    fr_res = extract_tier0_programme_facts(fr_bundle)
    assert not any(c.kind == "TUITION" and c.amount == Decimal("0.00") for c in fr_res.costs)
    assert "tuition" in fr_res.unresolved_slots


def test_item1_scrape_fetched_programme_page_and_card_host_reader_integration(settings) -> None:
    """Item 1: `scrape_fetched_programme_page` (called inline by `run_discovery`) and
    `CardHostReader` (`seam_bindings.py`) populate missing `CostComponent` rows for discovered
    programmes at $0.00 Tier 0 cost."""
    from apps.funding.models import OfficialSource, OfficialSourceSnapshot
    from apps.research.card_engine import Quote
    from apps.research.card_funding.card import AwardCard, Card, Field, Track
    from apps.research.card_funding.parse import Value
    from apps.research.models import Organisation
    from apps.research.programme_scraper import scrape_fetched_programme_page
    from apps.research.seam_bindings import CardHostReader

    prog = _make_program(country_code="FI", domain="aalto.fi", name="M.Sc. in Machine Learning")
    page_url = "https://www.aalto.fi/en/programmes/msc-machine-learning"
    source = OfficialSource.objects.create(
        canonical_url=page_url,
        publisher="aalto.fi",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key="official-sources/aalto/1",
        s3_version_id="1",
        sha256="a" * 64,
        final_url=page_url,
        redirect_chain=[],
        retrieved_at=timezone.now(),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=200,
        render_status="ARCHIVE:2026-06-25",
    )
    html = b"""
    <html>
      <body>
        <h1>M.Sc. in Machine Learning</h1>
        <table>
          <tr><th>Category</th><th>Annual Tuition Fee</th></tr>
          <tr><th>EU/EEA citizens</th><td>EUR 0</td></tr>
          <tr><th>Non-EU/EEA citizens</th><td>EUR 15,000</td></tr>
        </table>
        <p>Application fee for non-EU applicants: EUR 100.</p>
      </body>
    </html>
    """
    scrape_fetched_programme_page(prog, source=source, snapshot=snapshot, html=html)
    tuition = CostComponent.objects.get(program=prog, kind="TUITION")
    assert tuition.amount == Decimal("15000.00")
    assert tuition.currency == "EUR"
    # Reuses the existing snapshot without losing its render_status marker
    assert OfficialSourceSnapshot.objects.filter(source=source).count() == 1
    claim = OfficialEvidenceClaim.objects.filter(program=prog, claim_class="TUITION").first()
    assert claim is not None and claim.snapshot_id == snapshot.id
    assert claim.snapshot.render_status == "ARCHIVE:2026-06-25"
    app_fee = CostComponent.objects.get(program=prog, kind="APPLICATION_FEE")
    assert app_fee.amount == Decimal("100.00")

    # Now test CardHostReader with fetch_html on a second unpriced Program
    settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE = True
    prog2 = _make_program(country_code="FI", domain="helsinki.fi", name="M.Sc. in Data Science")
    assert not CostComponent.objects.filter(program=prog2, kind="TUITION").exists()
    helsinki_url = "https://www.helsinki.fi/en/scholarships"
    helsinki_html = b"""
    <html>
      <body>
        <h1>M.Sc. in Data Science Scholarships &amp; Tuition</h1>
        <p>Non-EU/EEA tuition fee: EUR 18,000 per academic year.</p>
      </body>
    </html>
    """

    def fake_read_card(_org: Organisation, url: str, _budget: float) -> Card:
        award = AwardCard(
            name="Helsinki Excellence Scholarship",
            name_quote=Quote("Helsinki Excellence Scholarship", "L0.text"),
            fields={
                "tuition_level": Field(
                    name="tuition_level",
                    state="shown",
                    values=(
                        Value(
                            value="full",
                            quote=Quote("100% tuition waiver", "L1.text"),
                            source=url,
                            decisions=(),
                        ),
                    ),
                ),
            },
            holds=(),
        )
        return Card(
            program_id=prog2.id,
            source_url=url,
            lang="en",
            outcome="read",
            tracks=(Track("", (award,)),),
            cost_usd=0.001,
        )

    reader = CardHostReader(
        read_card_fn=fake_read_card,
        fetch_html=lambda _u: helsinki_html,
    )
    host_read = reader.read("helsinki.fi", max_usd=Decimal("0.05"), seed_urls=(helsinki_url,))
    assert host_read is not None
    tuition2 = CostComponent.objects.get(program=prog2, kind="TUITION")
    assert tuition2.amount == Decimal("18000.00")


def test_item2_card_funding_2d_table_dl_and_jsonld_coordinate_binding() -> None:
    """Item 2: `card_funding.awards.page_lines(..., html=...)` binds `<dl>` `<dt>` terms,
    2D `<table>` row/column headers, and visible JSON-LD fields onto `Line.header` within
    each award's section so Master's vs. PhD stipends are disambiguated on separate lines."""
    from apps.research.candidates import find_all
    from apps.research.card_funding.awards import award_section, group, page_lines
    from apps.research.egress import FetchResult
    from apps.research.funding_terms import funding_terms
    from apps.research.reader import readable_text

    html = b"""
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "MonetaryGrant",
          "name": "Rector's Scholarship",
          "amount": {
            "@type": "MonetaryAmount",
            "value": "400",
            "currency": "AZN"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>University Scholarships</h1>
          <h2>Rector's Scholarship</h2>
          <dl>
            <dt>Master's students</dt>
            <dd>Monthly stipend of AZN 400.</dd>
          </dl>
          <h2>Merit Award</h2>
          <table>
            <tr><th>Benefit</th><th>Master's</th><th>PhD</th></tr>
            <tr><td>Monthly stipend</td><td>AZN 500</td><td>AZN 800</td></tr>
          </table>
        </main>
      </body>
    </html>
    """
    fetched = FetchResult("https://uni.example.az/scholarships", (), "text/html", html)
    text = readable_text(fetched, terms=funding_terms())
    page = page_lines(text, lang="en", html=html)

    # Heading indices for "Rector's Scholarship" and "Merit Award"
    heading_idxs = {
        idx
        for idx, (ln, lv) in enumerate(zip(page.lines, page.levels, strict=True))
        if lv and ln.text in ("Rector's Scholarship", "Merit Award")
    }
    assert len(heading_idxs) == 2
    awards, _ = group(page, heading_idxs)
    rector_sec = award_section(page, awards[0])
    merit_sec = award_section(page, awards[1])

    # 1. Rector's Scholarship <dl> bound <dt> ("Master's students") AND visible JSON-LD
    #    ("Schema.org Grant Amount") onto the <dd> line's .header without creating a duplicate
    #    Amount candidate.
    assert any(
        "Master's students" in ln.header
        and "Schema.org Grant Amount" in ln.header
        and ln.text == "Monthly stipend of AZN 400."
        for ln in rector_sec.lines
    )
    assert len(find_all(rector_sec.lines).amounts) == 1

    # 2. Merit Award 2D table split Master's (AZN 500) and PhD (AZN 800) onto separate lines
    #    with their 2D row|col headers!
    merit_headers_texts = [(ln.header, ln.text) for ln in merit_sec.lines]
    assert ("Monthly stipend | Master's", "AZN 500") in merit_headers_texts
    assert ("Monthly stipend | PhD", "AZN 800") in merit_headers_texts

    # 3. `find_all` on Merit Award now puts `m1` (AZN 500) and `l1` (Master's) on the SAME line,
    #    and `m2` (AZN 800) and `l2` (PhD) on a DIFFERENT line!
    cand = find_all(merit_sec.lines)
    assert cand.amounts["m1"].line != cand.amounts["m2"].line
    assert cand.amounts["m1"].line == cand.levels["l1"].line
    assert cand.amounts["m2"].line == cand.levels["l2"].line


def test_item3_stage_b_deep_documents_real_callers_in_apps_documents() -> None:
    """Item 3: Stage B (`deep_documents` / `full`) populates `cv_constraints`, `cv_directives`,
    `file_rules`, and `referee_requirements` in the exact schema validated by
    `rules_from_program`, `directives_from_program`, `rule_for`, `bundle_rule`, and `needs_for`,
    while ignoring third-party supervisor CV limits."""
    from apps.documents.constraints import directives_from_program, rules_from_program
    from apps.documents.file_rules import bundle_rule, rule_for
    from apps.documents.referee_needs import needs_for

    prog = _make_program(country_code="DE", domain="tum.de", name="M.Sc. in Informatics")
    front_url = "https://www.tum.de/msc-informatics"
    front_html = """
    <html>
      <body>
        <h1>M.Sc. in Informatics</h1>
        <p>Tuition fee for international students from non-EU countries: EUR 6,000 per semester.</p>
        <h2>Required Application Documents</h2>
        <ul>
          <li>Curriculum Vitae (PDF, max 2 pages, up to 5 MB) in reverse chronological order,
          without a photo, no date of birth, and without any unexplained gaps.</li>
          <li>Short CV (max 1 page) of your academic supervisor if applying for a thesis track.</li>
          <li>Motivation letter (PDF, up to 3 MB) explaining your academic goals.</li>
          <li>Two letters of recommendation from university professors sent from an
          institutional email.</li>
          <li>All documents must be combined into a single PDF file (up to 10 MB).</li>
        </ul>
      </body>
    </html>
    """
    derived_calls: list[tuple[str, str]] = []

    def fake_derive(p, text_str, snap, lang_code):
        derived_calls.append((snap.final_url, lang_code))

    scrape_programme_pages(
        prog,
        front_url,
        front_html,
        stage="deep_documents",
        derive_fn=fake_derive,
    )
    prog.refresh_from_db()
    assert len(derived_calls) == 1

    # 1. Real caller: `rules_from_program` (apps/documents/constraints.py)
    cv_rules = {r.key: r.value for r in rules_from_program(prog)}
    assert cv_rules["max_pages"] == 2  # Supervisor's "max 1 page" was ignored!
    assert cv_rules["max_bytes"] == 5_000_000
    assert cv_rules["photo_allowed"] is False
    assert cv_rules["date_of_birth_allowed"] is False
    assert cv_rules["no_unexplained_gaps"] == 2

    # 2. Real caller: `directives_from_program` (apps/documents/constraints.py)
    directives = directives_from_program(prog)
    assert len(directives) == 1
    assert (directives[0].action, directives[0].target, directives[0].value) == (
        "order",
        "cv",
        "reverse_chronological",
    )

    # 3. Real caller: `rule_for` and `bundle_rule` (apps/documents/file_rules.py)
    cv_file = rule_for(prog.file_rules, "CV")
    assert cv_file.format == "PDF"
    assert cv_file.max_bytes == 5_000_000
    letter_file = rule_for(prog.file_rules, "MOTIVATION_LETTER")
    assert letter_file.format == "PDF"
    assert letter_file.max_bytes == 3_000_000
    bundle = bundle_rule(prog.file_rules)
    assert bundle is not None
    assert bundle.one_file is True
    assert bundle.max_bytes == 10_000_000

    # 4. Real caller: `needs_for` (apps/documents/referee_needs.py)
    ref_need = needs_for(prog.referee_requirements)
    assert ref_need.letters == 2
    assert ref_need.kind is not None and ref_need.kind.value == "ACADEMIC"
    assert ref_need.institutional_email is True


def test_prose_only_and_table_plus_prose_interaction_and_key_value_tables() -> None:
    """Verifies what happens when:
    1. Facts appear ONLY in prose (including EU + Non-EU fees in the same sentence, or application
       fee + tuition fee in the same sentence, or UK 'International fees' under a Fees heading).
    2. Facts appear in BOTH a table and prose (e.g. a prose range summary or living-cost estimate
       alongside a 2D breakdown table, or a horizontal multi-column EU vs. Non-EU table).
    3. A key-value `<table>` has no `<th>` header row and splits `IELTS`, `GPA`, `CEFR`, and `ECTS`
       across column 0 and column 1.
    4. Prose states EU-only free tuition ('EU/EEA citizens pay no tuition fees') while
       `InstitutionBaseProfile` carries the non-EU tuition."""
    # 1. Pure prose: EU + Non-EU in one sentence (EU listed first!) + App fee & Tuition in one line
    prose_bundle = build_programme_bundle(
        [
            (
                "https://www.uni.example.eu/msc-ai",
                "<html><body><h1>M.Sc. in Artificial Intelligence</h1>"
                "<p>The non-refundable application fee is EUR 100, and tuition fees are "
                "EUR 2,500 per year for EU/EEA citizens and EUR 15,000 per year for "
                "non-EU/EEA international students.</p>"
                "<p>The programme is conducted entirely in English over 2 years.</p>"
                "</body></html>",
            )
        ]
    )
    prose_res = extract_tier0_programme_facts(prose_bundle)
    assert "tuition" not in prose_res.unresolved_slots
    prose_tuition = next(c for c in prose_res.costs if c.kind == "TUITION")
    assert prose_tuition.amount == Decimal("15000")
    assert prose_tuition.audience == "INTERNATIONAL"
    prose_app_fee = next(c for c in prose_res.costs if c.kind == "APPLICATION_FEE")
    assert prose_app_fee.amount == Decimal("100")
    assert prose_res.teaching_languages == ("English",)
    assert prose_res.duration_months == 24

    # 2. Table + Prose together: prose has a range summary ("from EUR 2,500 to EUR 18,000") and
    #    a living-cost estimate ("EUR 10,000"), while a horizontal 3-column table has the exact
    #    EU vs. Non-EU figures.
    both_bundle = build_programme_bundle(
        [
            (
                "https://www.uni.example.nl/msc-ds",
                "<html><body><h1>M.Sc. in Data Science</h1>"
                "<h2>Fees and Funding</h2>"
                "<p>Tuition fees at our university range from EUR 2,500 to EUR 18,000 per year "
                "for domestic and international students. Estimated living costs for international "
                "students are EUR 10,000 per year.</p>"
                "<table>"
                "  <tr><th>Programme</th><th>EU/EEA Tuition</th><th>Non-EU/EEA Tuition</th></tr>"
                "  <tr><td>M.Sc. Data Science</td><td>EUR 2,500</td><td>EUR 16,500</td></tr>"
                "</table>"
                "</body></html>",
            )
        ]
    )
    both_res = extract_tier0_programme_facts(both_bundle)
    assert "tuition" not in both_res.unresolved_slots
    both_tuition = next(c for c in both_res.costs if c.kind == "TUITION")
    assert both_tuition.amount == Decimal("16500")
    assert both_tuition.from_structured is True

    # 3. Key-value `<table>` without `<th>` headers + split IELTS/GPA/CEFR/ECTS across cells
    kv_bundle = build_programme_bundle(
        [
            (
                "https://www.uni.example.uk/msc-robotics",
                "<html><body><h1>M.Sc. in Robotics</h1>"
                "<h2>Fees and Entry Requirements</h2>"
                "<table>"
                "  <tr><td>International fees</td><td>GBP 28,500</td></tr>"
                "  <tr><td>Home fees</td><td>GBP 11,000</td></tr>"
                "  <tr><td>IELTS Academic</td><td>6.5</td></tr>"
                "  <tr><td>Minimum GPA</td><td>3.2/4.0</td></tr>"
                "  <tr><td>English Level</td><td>C1</td></tr>"
                "  <tr><td>ECTS Credits</td><td>120</td></tr>"
                "  <tr><td>Language</td><td>English</td></tr>"
                "</table>"
                "</body></html>",
            )
        ]
    )
    kv_res = extract_tier0_programme_facts(kv_bundle)
    kv_tuition = next(c for c in kv_res.costs if c.kind == "TUITION")
    assert kv_tuition.amount == Decimal("28500")
    assert kv_tuition.currency == "GBP"
    assert kv_res.duration_months == 24
    assert kv_res.teaching_languages == ("English",)
    elig_map = {(e.kind, e.label): e.value for e in kv_res.eligibility}
    assert elig_map[("LANGUAGE", "IELTS")] == "6.5"
    assert elig_map[("GRADE", "Minimum Grade / GPA")] == "3.2/4.0"
    assert elig_map[("LANGUAGE", "CEFR")] == "C1"

    # 4. EU-only free tuition in prose does not block InstitutionBaseProfile non-EU tuition
    base_prof = extract_institution_base_profile(
        "aalto.fi",
        [
            (
                "https://www.aalto.fi/en/tuition-fees",
                "<html><body><h1>Tuition Fees</h1>"
                "<p>Non-EU/EEA Master's tuition fee: EUR 15,000 per academic year.</p>"
                "</body></html>",
            )
        ],
    )
    eu_free_bundle = build_programme_bundle(
        [
            (
                "https://www.aalto.fi/en/msc-design",
                "<html><body><h1>M.Sc. in Design</h1>"
                "<p>Citizens of EU/EEA countries pay no tuition fees.</p>"
                "</body></html>",
            )
        ],
        base_profile=base_prof,
    )
    eu_free_res = extract_tier0_programme_facts(eu_free_bundle, base_profile=base_prof)
    eu_free_tuition = next(c for c in eu_free_res.costs if c.kind == "TUITION")
    assert eu_free_tuition.amount == Decimal("15000")
    assert eu_free_tuition.audience == "INTERNATIONAL"


def test_audit_pass3_multirow_thead_header_currency_negated_docs_and_jsonld_formatting() -> None:
    """Audit Pass 3 verification:
    1. Multi-row `<thead>` merges `colspan`/`rowspan` header rows (`Annual Tuition Fee (EUR)` +
       `Non-EU/EEA citizens`) instead of overwriting Row 0 with Row 1, and synthesizes `Amount`
       when the currency `(EUR)` is in the column header and the cell has a bare number (`15,000`).
    2. Empty top-left corner `<td></td>` or header year (`Tuition 2026/2027`) does not cause
       `_is_column_header_row` to misclassify the header row as a data row.
    3. Unformatted JSON-LD `price: 17500` matches formatted visible text `€17,500`.
    4. Negated document statements (`Motivation letter is not required`, `No reference letters
       are required`) set `letter_required = "not_requested"` and `needs_for(...).letters == 0`
       without creating false `REQUIRED` `ProgramStatement` rows.
    5. `classify_programme_sublinks` ignores `<footer>` links, prioritizes child paths and query
       tabs (`?tab=tuition`), and skips binary image assets.
    6. `CostComponent.objects.update_or_create` updates in place when currency or period changes
       without creating duplicate `(program, kind)` rows."""
    from apps.documents.referee_needs import needs_for

    # 1 & 2. Multi-row <thead> + empty corner <td> + year in header + currency in header & bare cell
    multirow_html = """
    <html>
      <body>
        <h1>M.Sc. in Computational Science</h1>
        <table>
          <thead>
            <tr>
              <td></td>
              <th colspan="2">Annual Tuition Fee 2026/2027 (EUR)</th>
            </tr>
            <tr>
              <th>Track</th>
              <th>EU/EEA citizens</th>
              <th>Non-EU/EEA citizens</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Standard Track</td>
              <td>2,500</td>
              <td>15,000</td>
            </tr>
          </tbody>
        </table>
        <p>A motivation letter is not required for this programme.</p>
        <p>No reference letters are required for admission.</p>
      </body>
    </html>
    """
    bundle = build_programme_bundle(
        [("https://www.uni.example.eu/programmes/msc-comp", multirow_html)]
    )
    res = extract_tier0_programme_facts(bundle)
    tuition = next(c for c in res.costs if c.kind == "TUITION")
    assert tuition.amount == Decimal("15000")
    assert tuition.currency == "EUR"
    assert tuition.audience == "INTERNATIONAL"
    assert tuition.quote.text == "15,000"

    # 4. Negated motivation letter and reference letters
    assert res.letter_required == "not_requested"
    assert not any("Reference" in s.label or "Motivation" in s.label for s in res.statements)
    prog = _make_program(country_code="NL", domain="uni.example.eu", name="M.Sc. Comp")
    persist_programme_scrape(
        prog,
        res,
        pages_by_url={"https://www.uni.example.eu/programmes/msc-comp": multirow_html},
        stage="full",
    )
    prog.refresh_from_db()
    assert prog.letter_required == "not_requested"
    ref_need = needs_for(prog.referee_requirements)
    assert ref_need.letters == 0

    # 6. Updating tuition currency/period on subsequent scrape updates in place (no duplicate row)
    updated_res = extract_tier0_programme_facts(
        build_programme_bundle(
            [
                (
                    "https://www.uni.example.eu/programmes/msc-comp",
                    "<html><body><p>International tuition fee: USD 18,000 per programme.</p>"
                    "</body></html>",
                )
            ]
        )
    )
    persist_programme_scrape(prog, updated_res, stage="gate_and_money")
    assert CostComponent.objects.filter(program=prog, kind="TUITION").count() == 1
    cc = CostComponent.objects.get(program=prog, kind="TUITION")
    assert cc.amount == Decimal("18000")
    assert cc.currency == "USD"
    assert cc.period == "FULL_PROGRAM"

    # 3. Unformatted JSON-LD `price: 17500` matching visible `€17,500`
    jsonld_html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "EducationalOccupationalProgram",
          "name": "M.Sc. Cyber Security",
          "offers": {
            "@type": "Offer",
            "category": "International Non-EU Tuition",
            "price": 17500,
            "priceCurrency": "EUR"
          }
        }
        </script>
      </head>
      <body>
        <h1>M.Sc. Cyber Security</h1>
        <p>Annual fee for international students: €17,500.</p>
      </body>
    </html>
    """
    jl_lines = extract_jsonld_lines(jsonld_html)
    assert any(
        ln.text == "€17,500" and "International Non-EU Tuition" in ln.header for ln in jl_lines
    )

    # 5. Sublink classifier: ignores <footer>, prioritizes child path & query tabs, skips .jpg
    sublink_html = """
    <html>
      <body>
        <main>
          <a href="/assets/tuition-fee-banner.jpg">Tuition Banner</a>
          <a href="/general-university-fees">General Fees</a>
          <a href="/programmes/msc-comp?tab=tuition">Tuition &amp; Fees Tab</a>
          <a href="/programmes/msc-comp/admission-requirements">Admission Requirements</a>
        </main>
        <footer>
          <a href="/footer-scholarships-and-funding-aid">Scholarships Funding Financial Aid</a>
        </footer>
      </body>
    </html>
    """
    sublinks = classify_programme_sublinks(
        "https://www.uni.example.eu/programmes/msc-comp", sublink_html
    )
    assert sublinks.tuition_and_fees == "https://www.uni.example.eu/programmes/msc-comp?tab=tuition"
    assert (
        sublinks.admissions_and_eligibility
        == "https://www.uni.example.eu/programmes/msc-comp/admission-requirements"
    )
    assert sublinks.scholarships_and_funding == ""

    # 6. Yearless autumn deadline ("15 November" for 2027-2029 intake) resolves to 2026-11-15,
    # and persist_programme_scrape never lets a trailing EU_DOMESTIC tuition overwrite INTERNATIONAL
    from dataclasses import replace

    from apps.research.programme_scraper import CostComponentSpec, Quote

    autumn_dl_html = """
    <html>
      <body>
        <h1>M.Sc. in Chemoinformatics</h1>
        <p>Application deadline for the 2027-2029 intake: 15 November.</p>
      </body>
    </html>
    """
    dl_bundle = build_programme_bundle(
        [("https://www.uni.example.eu/msc-chemo", autumn_dl_html)]
    )
    dl_facts = extract_tier0_programme_facts(dl_bundle)
    dl_spec = next(e for e in dl_facts.eligibility if e.kind == "DEADLINE")
    assert dl_spec.value == "2026-11-15"

    mixed_costs_res = replace(
        updated_res,
        costs=(
            CostComponentSpec(
                kind="TUITION",
                amount=Decimal("9000"),
                currency="EUR",
                period="ANNUAL",
                audience="INTERNATIONAL",
                quote=Quote("EUR 9,000", "L1"),
                source_url="https://www.uni.example.eu/msc-comp",
            ),
            CostComponentSpec(
                kind="TUITION",
                amount=Decimal("1500"),
                currency="EUR",
                period="ANNUAL",
                audience="EU_DOMESTIC",
                quote=Quote("EUR 1,500", "L2"),
                source_url="https://www.uni.example.eu/msc-comp",
            ),
        ),
    )
    persist_programme_scrape(prog, mixed_costs_res, stage="gate_and_money")
    cc_after = CostComponent.objects.get(program=prog, kind="TUITION")
    assert cc_after.amount == Decimal("9000")
    assert cc_after.currency == "EUR"


def test_per_credit_and_trimester_quarter_term_tuition_and_multilingual_guards() -> None:
    """Covers Tier-1 PER_CREDIT single-credit conversion (* 30), TRIMESTER/QUARTER/TERM (* 3),
    yearless deadline 60-day past guard, 1/3 referee counts, and multilingual conditional guards."""
    import datetime as dt

    from apps.documents.referee_needs import needs_for
    from apps.research.card_engine import Decision, Quote
    from apps.research.programme_scraper.arbitration import (
        needs_high_risk_arbitration,
        refine_with_dual_readers,
    )
    from apps.research.programme_scraper.extractors import (
        _candidates_with_header_currency,
        _normalize_tuition_amount_and_period,
        _period_from_context,
    )
    from apps.research.programme_scraper.specs import ProgrammeQuestionSet

    # 1. QuestionSet options include PER_CREDIT, TRIMESTER, QUARTER, TERM
    us_html = "<html><body><h1>MS CS</h1><p>Tuition is USD 1,850 per credit hour.</p></body></html>"
    us_bundle = build_programme_bundle([("https://www.columbia.edu/ms-cs", us_html)])
    qset = ProgrammeQuestionSet(
        unresolved_slots=frozenset({"tuition"}),
        high_risk_flags=frozenset(),
    )
    cands = _candidates_with_header_currency(us_bundle.section.lines)
    qs = qset.questions(us_bundle.section, cands, {})
    period_q = next(q for q in qs if q.id == "tuition_period")
    for opt in ("PER_CREDIT", "TRIMESTER", "QUARTER", "TERM"):
        assert opt in period_q.options

    # 2. _period_from_context and _normalize_tuition_amount_and_period
    assert _period_from_context("AUD 12,000 per trimester") == "TRIMESTER"
    assert _period_from_context("USD 15,000 per quarter") == "QUARTER"
    assert _period_from_context("GBP 9,000 per term") == "TERM"
    assert _normalize_tuition_amount_and_period(Decimal("12000"), "TRIMESTER") == (
        Decimal("36000"),
        "ANNUAL",
    )
    assert _normalize_tuition_amount_and_period(Decimal("15000"), "QUARTER") == (
        Decimal("45000"),
        "ANNUAL",
    )
    assert _normalize_tuition_amount_and_period(Decimal("9000"), "TERM") == (
        Decimal("27000"),
        "ANNUAL",
    )
    assert _normalize_tuition_amount_and_period(Decimal("1850"), "PER_CREDIT") == (
        Decimal("55500"),
        "ANNUAL",
    )

    # 3. Tier-1 arbitration with PER_CREDIT multiplies by 30 instead of storing single-credit fee
    us_tier0 = extract_tier0_programme_facts(us_bundle)
    assert "tuition" in us_tier0.unresolved_slots

    test_readers = Stack(
        pair=(
            ReaderSpec("cheap-a", "openrouter", "openai/gpt-5.4-nano", host="OpenAI"),
            ReaderSpec("cheap-b", "openrouter", "google/gemini-3.1-flash-lite", host="Google"),
        ),
        decider=ReaderSpec("frontier-decider", "anthropic", "claude-opus-4-7"),
    )

    def fake_transport(reader: ReaderSpec, prompt: Prompt) -> Attempt:
        return Attempt(
            reply=Reply.model_validate(
                {
                    "answers": [
                        {"id": "tuition_amount", "value": "m1", "quote": "USD 1,850"},
                        {"id": "tuition_period", "value": "PER_CREDIT", "quote": "per credit hour"},
                    ]
                }
            ),
            reason="",
            cost_usd=0.0001,
            latency_s=0.01,
        )

    us_refined = refine_with_dual_readers(
        us_bundle,
        us_tier0,
        screen=Screen("clear", frozenset(us_bundle.section.texts())),
        limit=Limit("test-bucket", 1, 100, 3600),
        readers=test_readers,
        transport=fake_transport,
    )
    tuition_cost = next(c for c in us_refined.costs if c.kind == "TUITION")
    assert tuition_cost.amount == Decimal("55500")
    assert tuition_cost.period == "ANNUAL"
    assert tuition_cost.currency == "USD"

    # 4. Yearless deadline never placed >60 days in the past relative to today
    today = dt.date.today()
    past_dt = today - dt.timedelta(days=120)
    month_name = past_dt.strftime("%B")
    past_dl_html = (
        f"<html><body><p>Application deadline for the {today.year} intake: "
        f"15 {month_name}.</p></body></html>"
    )
    past_bundle = build_programme_bundle([("https://www.uni.example.org/ms", past_dl_html)])
    past_facts = extract_tier0_programme_facts(past_bundle)
    dl_val = next(e.value for e in past_facts.eligibility if e.kind == "DEADLINE")
    assert dt.date.fromisoformat(dl_val) >= today - dt.timedelta(days=60)

    # 5. Referee count: "a letter of recommendation" -> ONE, "drei" -> THREE_OR_MORE
    one_ref_html = (
        "<html><body><p>Applicants must submit a letter of recommendation.</p></body></html>"
    )
    one_ref_bundle = build_programme_bundle([("https://www.uni.example.org/ms-1", one_ref_html)])
    one_ref_facts = extract_tier0_programme_facts(one_ref_bundle)
    assert needs_for(one_ref_facts.referee_requirements).letters == 1

    three_ref_bundle = build_programme_bundle(
        [
            (
                "https://www.uni.example.org/ms-3",
                "<html><body><p>Bewerber reichen drei Empfehlungsschreiben ein.</p></body></html>",
            )
        ]
    )
    three_ref_facts = extract_tier0_programme_facts(three_ref_bundle)
    assert needs_for(three_ref_facts.referee_requirements).letters == 3

    # 6. Multilingual conditional guards trigger needs_high_risk_arbitration
    agreed_free = (
        Decision(
            question="tuition_free_all_internationals",
            status="agreed",
            value="yes",
            quote=Quote("keine Studiengebühren", "L0.text"),
            answers=(),
        ),
    )
    for guard_line in (
        "Keine Studiengebühren, ausgenommen Drittstaatsangehörige.",
        "Gebührenfrei nur für EU-Bürger.",
        "Befreiung für Studierende einer Partneruniversität.",
        "Gratuité sauf pour les étudiants hors UE.",
        "Exonération pour les ressortissants de l'UE.",
        "Geen collegegeld, alleen voor EU-studenten (uitzondering).",
        "Matrícula gratuita excepto estudiantes no comunitarios (exención).",
        "Esonero tasse universitarie, eccetto studenti internazionali.",
    ):
        g_bundle = build_programme_bundle(
            [("https://www.uni.example.org/fees", f"<html><body><p>{guard_line}</p></body></html>")]
        )
        assert needs_high_risk_arbitration(agreed_free, g_bundle.section) == (
            "tuition_free_all_internationals",
        ), guard_line


def test_dawid_skene_log_odds_amount_spread_default_transport_and_fail_closed(monkeypatch) -> None:
    """Verify Proposition 1 Dawid-Skene log-odds boundaries, multi-amount spread escalation,
    default `transport` wiring when `transport=None`, and fail-closed downgrade to `'unresolved'`
    when the Tier 2 frontier decider fails or returns an unlocated quote."""
    import math

    from apps.research.card_engine import Decision, Quote, ReaderAnswer
    from apps.research.programme_scraper import arbitration
    from apps.research.programme_scraper.arbitration import (
        CONDITIONAL_FREE_TUITION_PARAMS,
        DawidSkeneSlotParams,
        detect_tuition_amount_spread_risk,
        needs_high_risk_arbitration,
        refine_with_dual_readers,
        slot_escalation_bounds,
        slot_posterior_log_odds,
    )

    # 1. Exact Proposition 1 formulas for slot_escalation_bounds and slot_posterior_log_odds
    params = DawidSkeneSlotParams(
        prior=0.15,
        sensitivities=(0.90, 0.90),
        specificities=(0.88, 0.88),
        c_fp=100.0,
        c_fn=5.0,
        c_judge=1.0,
    )
    theta_low, theta_high = slot_escalation_bounds(params)
    assert theta_low == pytest.approx(math.log(1.0 / 4.0))
    assert theta_high == pytest.approx(math.log(99.0))
    l_unanimous_yes = slot_posterior_log_odds((True, True), CONDITIONAL_FREE_TUITION_PARAMS)
    assert theta_low < l_unanimous_yes < theta_high

    # 2. Multi-amount spread risk: cheap readers agree on EUR 1,500 when EUR 15,000 is on the page
    spread_html = """
    <html>
      <body>
        <h1>M.Sc. in Data Engineering</h1>
        <p>Fee tariff group I: EUR 1,500. Fee tariff group II: EUR 15,000.</p>
      </body>
    </html>
    """
    spread_bundle = build_programme_bundle(
        [("https://www.uni.example.org/msc-de", spread_html)]
    )
    amt_dec_low = Decision(
        question="tuition_amount",
        status="agreed",
        value="m1",
        quote=Quote("EUR 1,500", "L1.text"),
        answers={
            "cheap-a": ReaderAnswer("m1", Quote("EUR 1,500", "L1.text")),
            "cheap-b": ReaderAnswer("m1", Quote("EUR 1,500", "L1.text")),
        },
    )
    per_dec = Decision(
        question="tuition_period",
        status="agreed",
        value="ANNUAL",
        quote=Quote("EUR 1,500", "L1.text"),
        answers={},
    )
    assert detect_tuition_amount_spread_risk(amt_dec_low, spread_bundle.section) is True
    assert needs_high_risk_arbitration((amt_dec_low, per_dec), spread_bundle.section) == (
        "tuition_amount",
        "tuition_period",
    )

    # 3. Production default transport (transport=None uses default_call for both Tier 1 and Tier 2)
    cond_html = """
    <html>
      <body>
        <h1>M.Sc. in Economics</h1>
        <p>Tuition-free for exchange students from partner universities.</p>
      </body>
    </html>
    """
    cond_bundle = build_programme_bundle(
        [("https://www.uni.example.org/msc-econ", cond_html)]
    )
    cond_tier0 = extract_tier0_programme_facts(cond_bundle)
    test_readers = Stack(
        pair=(
            ReaderSpec("cheap-a", "openrouter", "openai/gpt-5.4-nano", host="OpenAI"),
            ReaderSpec("cheap-b", "openrouter", "google/gemini-3.1-flash-lite", host="Google"),
        ),
        decider=ReaderSpec("frontier-decider", "anthropic", "claude-opus-4-7"),
    )
    default_called: list[str] = []

    def fake_default_call(reader: ReaderSpec, prompt: Prompt) -> Attempt:
        default_called.append(reader.name)
        if reader.name in ("cheap-a", "cheap-b"):
            return Attempt(
                reply=Reply.model_validate(
                    {
                        "answers": [
                            {
                                "id": "tuition_free_all_internationals",
                                "value": "yes",
                                "quote": "Tuition-free",
                            }
                        ]
                    }
                ),
                reason="",
                cost_usd=0.0001,
                latency_s=0.05,
            )
        # Simulate frontier decider returning an unlocated quote (or failing) -> must fail-closed!
        return Attempt(
            reply=Reply.model_validate(
                {
                    "answers": [
                        {
                            "id": "tuition_free_all_internationals",
                            "value": "yes",
                            "quote": "nonexistent fabricated quote",
                        }
                    ]
                }
            ),
            reason="",
            cost_usd=0.002,
            latency_s=0.1,
        )

    monkeypatch.setattr(arbitration, "default_call", fake_default_call)
    refined_fail_closed = refine_with_dual_readers(
        cond_bundle,
        cond_tier0,
        screen=Screen("clear", frozenset(cond_bundle.section.texts())),
        limit=Limit("test-bucket", 1, 100, 3600),
        readers=test_readers,
        transport=None,
    )
    assert "frontier-decider" in default_called
    free_decision = next(
        d for d in refined_fail_closed.decisions if d.question == "tuition_free_all_internationals"
    )
    assert free_decision.status == "unresolved"
    assert free_decision.value is None
    assert not any(
        c.kind == "TUITION" and c.amount == Decimal("0.00") for c in refined_fail_closed.costs
    )
    assert "tuition" in refined_fail_closed.unresolved_slots


def test_calibrated_dawid_skene_six_high_risk_slots_and_scrape_fetched_arbitration() -> None:
    """Verify:
    1. `ProgrammeQuestionSet` emits questions for all 6 high-consequence slots (`tuition`,
       `conditional_free_tuition`, `application_fee`, `deadline`, `min_gpa`, `ielts_bar`,
       `scholarship_suspended`).
    2. `calibrate_slot_params` shrinks Beta-Binomial reader confusion counts (`GoldItem` +
       `DecisionRecord` or `ReaderAuditCounts`) with kappa_0=20.0, enforces the informativeness
       guard `alpha_hat + beta_hat > 1.02`, and falls back cleanly to default params when no
       audited records exist.
    3. `needs_high_risk_arbitration` escalates agreed cheap-reader decisions across the extended
       high-risk slots when conditional guards or competing candidates exist.
    4. `scrape_fetched_programme_page` accepts optional `screen`, `limit`, `readers`, `transport`
       and invokes `refine_with_dual_readers` when `needs_high_risk_arbitration(result)` triggers.
    """
    from apps.funding.models import OfficialSource, OfficialSourceSnapshot
    from apps.research.card_engine import Decision, Quote, ReaderAnswer
    from apps.research.models import DecisionRecord, GoldItem
    from apps.research.programme_scraper import scrape_fetched_programme_page
    from apps.research.programme_scraper.arbitration import (
        APPLICATION_FEE_PARAMS,
        CONDITIONAL_FREE_TUITION_PARAMS,
        DEADLINE_PARAMS,
        IELTS_BAR_PARAMS,
        MIN_GPA_PARAMS,
        SCHOLARSHIP_SUSPENDED_PARAMS,
        ReaderAuditCounts,
        calibrate_slot_params,
        needs_high_risk_arbitration,
    )
    from apps.research.programme_scraper.extractors import _candidates_with_header_currency
    from apps.research.programme_scraper.specs import ProgrammeQuestionSet

    rich_html = """
    <html>
      <body>
        <h1>M.Sc. in Quantitative Finance</h1>
        <p>Tuition fee: EUR 2,500 for EU students, except non-EU students who pay EUR 16,000.</p>
        <p>Application fee: EUR 50 for EU citizens, or EUR 120 for non-EU applicants.</p>
        <p>Application deadline: 15 January 2027 or 1 May 2027.</p>
        <p>Minimum GPA: 3.0 out of 4.0 or 3.5 out of 4.0 for honors track.</p>
        <p>English proficiency: IELTS 6.5 or IELTS 7.0.</p>
      </body>
    </html>
    """
    bundle = build_programme_bundle(
        [("https://www.uni.example.org/msc-qf", rich_html)],
        title="M.Sc. in Quantitative Finance",
    )
    cands = _candidates_with_header_currency(bundle.section.lines)
    qset = ProgrammeQuestionSet(
        unresolved_slots=frozenset(
            {"tuition", "application_fee", "deadline", "min_gpa", "ielts_bar"}
        ),
        high_risk_flags=frozenset({"conditional_free_tuition", "scholarship_suspended"}),
    )
    asked_ids = {q.id for q in qset.questions(bundle.section, cands, {})}
    assert asked_ids == {
        "tuition_amount",
        "tuition_period",
        "tuition_free_all_internationals",
        "application_fee_amount",
        "application_deadline_date",
        "minimum_gpa_bar",
        "minimum_language_bar",
        "scholarship_intake_suspended",
    }

    # 2. Beta-Binomial conjugate calibration (explicit counts + DB GoldItem/DecisionRecord + guard)
    assert calibrate_slot_params("tuition", CONDITIONAL_FREE_TUITION_PARAMS) == (
        CONDITIONAL_FREE_TUITION_PARAMS
    )
    cal_explicit = calibrate_slot_params(
        CONDITIONAL_FREE_TUITION_PARAMS,
        (
            ReaderAuditCounts(tp=30, fn=0, tn=25, fp=0),
            ReaderAuditCounts(tp=10, fn=10, tn=10, fp=10),
        ),
        prior_strength=20.0,
    )
    assert cal_explicit.sensitivities[0] > CONDITIONAL_FREE_TUITION_PARAMS.sensitivities[0]
    assert cal_explicit.specificities[0] > CONDITIONAL_FREE_TUITION_PARAMS.specificities[0]
    assert cal_explicit.sensitivities[1] < CONDITIONAL_FREE_TUITION_PARAMS.sensitivities[1]

    # Informativeness guard: anti-informative counts (alpha_hat + beta_hat <= 1.02) fall back
    cal_uninformative = calibrate_slot_params(
        CONDITIONAL_FREE_TUITION_PARAMS,
        (ReaderAuditCounts(tp=0, fn=200, tn=0, fp=200),),
        prior_strength=20.0,
    )
    assert cal_uninformative.sensitivities[0] == CONDITIONAL_FREE_TUITION_PARAMS.sensitivities[0]
    assert cal_uninformative.specificities[0] == CONDITIONAL_FREE_TUITION_PARAMS.specificities[0]

    # DB-backed calibration from GoldItem + DecisionRecord
    gold_pos = GoldItem.objects.create(
        run="audit-2026-11",
        kind=GoldItem.Kind.MONEY,
        question="application_fee_amount",
        language="en",
        page_url="https://www.uni.example.org/msc-qf",
        line_text="Application fee: EUR 120 for non-EU applicants.",
        claim="m4",
        round=1,
        purpose=GoldItem.Purpose.CERTIFICATION,
        verdict=GoldItem.Verdict.CORRECT,
    )
    DecisionRecord.objects.create(
        state_digest=gold_pos.line_sha256,
        question_digest="q" * 64,
        decision="application_fee_amount",
        question_id="application_fee_amount",
        value="m4",
        confidence=0.95,
        model="cheap-a",
        provider="openrouter",
        refused=False,
    )
    cal_db = calibrate_slot_params("application_fee", APPLICATION_FEE_PARAMS)
    assert cal_db.sensitivities[0] > APPLICATION_FEE_PARAMS.sensitivities[0]

    # 3. needs_high_risk_arbitration across the extended slots
    amt_key = next(iter(cands.amounts.keys()))
    date_key = next(iter(cands.dates.keys()))
    grade_key = next(k for k, r in cands.requirements.items() if r.value.kind == "grade")
    lang_key = next(
        k for k, r in cands.requirements.items() if r.value.kind in ("language_test", "cefr")
    )
    synthetic_decisions = (
        Decision(
            question="application_fee_amount",
            status="agreed",
            value=amt_key,
            quote=Quote("EUR 50", "L1.text"),
            answers={"a": ReaderAnswer(amt_key, None), "b": ReaderAnswer(amt_key, None)},
        ),
        Decision(
            question="application_deadline_date",
            status="agreed",
            value=date_key,
            quote=Quote("15 January 2027", "L2.text"),
            answers={"a": ReaderAnswer(date_key, None), "b": ReaderAnswer(date_key, None)},
        ),
        Decision(
            question="minimum_gpa_bar",
            status="agreed",
            value=grade_key,
            quote=Quote("3.0", "L3.text"),
            answers={"a": ReaderAnswer(grade_key, None), "b": ReaderAnswer(grade_key, None)},
        ),
        Decision(
            question="minimum_language_bar",
            status="agreed",
            value=lang_key,
            quote=Quote("6.5", "L4.text"),
            answers={"a": ReaderAnswer(lang_key, None), "b": ReaderAnswer(lang_key, None)},
        ),
        Decision(
            question="scholarship_intake_suspended",
            status="agreed",
            value="yes",
            quote=Quote("except", "L0.text"),
            answers={"a": ReaderAnswer("yes", None), "b": ReaderAnswer("yes", None)},
        ),
    )
    for p_check in (
        DEADLINE_PARAMS,
        MIN_GPA_PARAMS,
        IELTS_BAR_PARAMS,
        SCHOLARSHIP_SUSPENDED_PARAMS,
    ):
        assert p_check.c_judge < min(p_check.c_fp, p_check.c_fn)
    escalated = needs_high_risk_arbitration(
        synthetic_decisions, bundle.section, candidates=cands
    )
    assert set(escalated) == {
        "application_fee_amount",
        "application_deadline_date",
        "minimum_gpa_bar",
        "minimum_language_bar",
        "scholarship_intake_suspended",
    }

    # 4. scrape_fetched_programme_page with screen & limit invokes refine_with_dual_readers
    prog = _make_program(country_code="DE", domain="uni-cond.de", name="M.Sc. Economics")
    page_url = "https://www.uni-cond.de/msc-economics"
    source = OfficialSource.objects.create(
        canonical_url=page_url,
        publisher="uni-cond.de",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key="official-sources/uni-cond/1",
        s3_version_id="1",
        sha256="c" * 64,
        final_url=page_url,
        redirect_chain=[],
        retrieved_at=timezone.now(),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=200,
    )
    cond_html = """
    <html>
      <body>
        <h1>M.Sc. Economics</h1>
        <p>Tuition-free for exchange students from partner universities.</p>
      </body>
    </html>
    """
    test_readers = Stack(
        pair=(
            ReaderSpec("cheap-a", "openrouter", "openai/gpt-5.4-nano", host="OpenAI"),
            ReaderSpec("cheap-b", "openrouter", "google/gemini-3.1-flash-lite", host="Google"),
        ),
        decider=ReaderSpec("frontier-decider", "anthropic", "claude-opus-4-7"),
    )
    called_in_fetched: list[str] = []

    def fake_transport(reader: ReaderSpec, prompt: Prompt) -> Attempt:
        called_in_fetched.append(reader.name)
        val = "yes" if reader.name in ("cheap-a", "cheap-b") else "no"
        q_txt = "Tuition-free" if val == "yes" else ""
        return Attempt(
            reply=Reply.model_validate(
                {
                    "answers": [
                        {
                            "id": "tuition_free_all_internationals",
                            "value": val,
                            "quote": q_txt,
                        }
                    ]
                }
            ),
            reason="",
            cost_usd=0.0002,
            latency_s=0.05,
        )

    fetched_bundle = build_programme_bundle([(page_url, cond_html)], title=prog.name)
    res_fetched = scrape_fetched_programme_page(
        prog,
        source=source,
        snapshot=snapshot,
        html=cond_html,
        screen=Screen("clear", frozenset(fetched_bundle.section.texts())),
        limit=Limit("test-bucket", 1, 100, 3600),
        readers=test_readers,
        transport=fake_transport,
    )
    assert "frontier-decider" in called_in_fetched
    assert any(
        d.question == "tuition_free_all_internationals" and d.value == "no"
        for d in res_fetched.decisions
    )
    assert not CostComponent.objects.filter(program=prog, kind="TUITION").exists()


def test_stage2_bound_host_reader_2d_table_labels_arbitration_statements_and_leap_day_clamping(
    settings,
    monkeypatch,
) -> None:
    """Verify Stage 2 fixes:
    1. `bound_host_reader()` wires default `fetch_html` (wrapping `retrieve_official_source`)
       and `site_search` (wrapping `exa_site_search` when `EXA_API_KEY` is non-empty).
    2. 2D table `GRADE` and `LANGUAGE` rows prefix `elig.label (elig.value): quote` onto
       `DocumentStatementSpec.text`; multiple GRADE/LANGUAGE/DEADLINE values and scholarship
       suspension statements populate `unresolved_slots` and `high_risk_flags`; and
       `refine_with_dual_readers` updates/prunes `updated_elig` AND `updated_statements`.
    3. Leap-day (`29 February`) and out-of-range days clamp cleanly in `extractors.py`,
       `arbitration.py`, `candidates/dates.py`, `card_funding/parse.py`, and
       `card_funding/store.py`.
    """
    import datetime as dt
    from dataclasses import replace
    from types import SimpleNamespace

    from apps.funding.probability import _extract_required_gpa_bar
    from apps.research.candidates import Date, Found
    from apps.research.candidates.dates import find_dates
    from apps.research.card_engine import Decision, Limit
    from apps.research.card_engine.engine import Attempt, Reply
    from apps.research.card_engine.readers import ReaderSpec, Stack
    from apps.research.card_engine.screen import Screen
    from apps.research.card_funding.card import AwardDate
    from apps.research.card_funding.parse import page_date
    from apps.research.card_funding.store import _date_iso
    from apps.research.providers.base import SiteSearchResult
    from apps.research.seam_bindings import CardHostReader
    from apps.research.tap_seams import bound_host_reader

    # 1. bound_host_reader default fetch_html and site_search wiring
    monkeypatch.setattr(
        "apps.research.discovery.retrieve_official_source",
        lambda url: SimpleNamespace(body=b"<html><body> Tuition EUR 12,000 </body></html>"),
    )
    monkeypatch.setattr(
        "apps.research.providers.exa.exa_site_search",
        lambda *, query, domain, **kw: SiteSearchResult(
            urls=(f"https://{domain}/scholarships",), cost_usd=0.005, provider="exa"
        ),
    )
    settings.EXA_API_KEY = "test-exa-key"
    reader = bound_host_reader(field="Computer Science")
    assert isinstance(reader, CardHostReader)
    assert reader.fetch_html is not None
    assert "Tuition EUR 12,000" in (reader.fetch_html("https://uni.example.org") or "")
    assert reader.site_search is not None
    assert tuple(reader.site_search("master scholarship", "uni.example.org")) == (
        "https://uni.example.org/scholarships",
    )

    # 2a. 2D table row label preservation in DocumentStatementSpec
    table_html = """
    <html>
      <body>
        <h1>M.Sc. Data Science</h1>
        <table>
          <tr><th>Requirement</th><th>Threshold</th></tr>
          <tr><th>Minimum GPA</th><td>3.5 / 4.0</td></tr>
          <tr><th>IELTS</th><td>7.0</td></tr>
        </table>
      </body>
    </html>
    """
    tbl_bundle = build_programme_bundle(
        [("https://uni.example.org/ds", table_html)],
        title="M.Sc. Data Science",
    )
    tbl_res = extract_tier0_programme_facts(tbl_bundle)
    gpa_stmt = next(s for s in tbl_res.statements if s.label == "Minimum Grade / GPA")
    assert gpa_stmt.text == "Minimum Grade / GPA (3.5/4.0): 3.5 / 4.0"
    assert _extract_required_gpa_bar((), tbl_res.statements) == (3.5, "gpa 4.0")
    lang_stmt = next(s for s in tbl_res.statements if s.label == "IELTS")
    assert lang_stmt.text == "IELTS (7.0): 7.0"

    # 2b & 2c. Ambiguous GPA, language, deadline, and scholarship suspension -> arbitration
    ambig_html = """
    <html>
      <body>
        <h1>M.Sc. Computational Finance</h1>
        <p>Tuition fee: EUR 14,000 per year for international students.</p>
        <p>Application deadline: 29 February or 15 May 2027.</p>
        <p>Minimum GPA: 3.0/4.0 for standard track or GPA 3.6/4.0 for honors track.</p>
        <p>English requirement: IELTS 6.5 or IELTS 7.0.</p>
        <p>No scholarships are available for the 2027/28 intake.</p>
      </body>
    </html>
    """
    ambig_bundle = build_programme_bundle(
        [("https://uni.example.org/cf", ambig_html)],
        title="M.Sc. Computational Finance",
    )
    tier0_ambig = extract_tier0_programme_facts(ambig_bundle)
    assert {"deadline", "min_gpa", "ielts_bar", "scholarship_suspended"} <= set(
        tier0_ambig.unresolved_slots
    )
    assert {
        "ambiguous_deadline",
        "ambiguous_min_gpa",
        "ambiguous_ielts_bar",
        "scholarship_suspended",
    } <= set(tier0_ambig.high_risk_flags)

    # Leap-day clamping in Tier 0 deadline extraction ("29 February" in 2027 -> "2027-02-28")
    dl_tier0 = next(e for e in tier0_ambig.eligibility if e.kind == "DEADLINE")
    assert dl_tier0.value == "2027-02-28"

    from apps.research.programme_scraper.extractors import _candidates_with_header_currency

    cands_ambig = _candidates_with_header_currency(ambig_bundle.section.lines)
    gpa_36_key = next(
        k
        for k, r in cands_ambig.requirements.items()
        if r.value.kind == "grade" and str(r.value.score) == "3.6"
    )
    ielts_70_key = next(
        k
        for k, r in cands_ambig.requirements.items()
        if r.value.kind == "language_test" and str(r.value.score) == "7.0"
    )
    feb29_key = next(k for k, d in cands_ambig.dates.items() if d.value.month == 2)

    test_readers = Stack(
        pair=(
            ReaderSpec("cheap-a", "openrouter", "openai/gpt-5.4-nano", host="OpenAI"),
            ReaderSpec("cheap-b", "openrouter", "google/gemini-3.1-flash-lite", host="Google"),
        ),
        decider=ReaderSpec("frontier-decider", "anthropic", "claude-opus-4-7"),
    )

    def arbitrate_transport(_reader: ReaderSpec, _prompt: object) -> Attempt:
        return Attempt(
            reply=Reply.model_validate(
                {
                    "answers": [
                        {
                            "id": "application_deadline_date",
                            "value": feb29_key,
                            "quote": "29 February",
                        },
                        {
                            "id": "minimum_gpa_bar",
                            "value": gpa_36_key,
                            "quote": "3.6/4.0",
                        },
                        {
                            "id": "minimum_language_bar",
                            "value": ielts_70_key,
                            "quote": "IELTS 7.0",
                        },
                        {
                            "id": "scholarship_intake_suspended",
                            "value": "no",
                            "quote": "",
                        },
                    ]
                }
            ),
            reason="",
            cost_usd=0.0001,
            latency_s=0.01,
        )

    refined = refine_with_dual_readers(
        ambig_bundle,
        tier0_ambig,
        screen=Screen("clear", frozenset(ambig_bundle.section.texts())),
        limit=Limit("test-stage2-arb", 1, 100, 3600),
        readers=test_readers,
        transport=arbitrate_transport,
    )
    assert [e.value for e in refined.eligibility if e.kind == "GRADE"] == ["3.6/4.0"]
    assert [e.value for e in refined.eligibility if e.kind == "LANGUAGE"] == ["7.0"]
    assert [e.value for e in refined.eligibility if e.kind == "DEADLINE"] == ["2027-02-28"]
    assert not any(s.label == "Scholarship / Funding Status" for s in refined.statements)
    assert any("3.6/4.0" in s.text for s in refined.statements if s.kind == "COMPETENCY")
    assert not any("3.0/4.0" in s.text for s in refined.statements if s.kind == "COMPETENCY")
    assert [s.text for s in refined.statements if s.kind == "LANGUAGE"] == ["IELTS 7.0"]

    # 3. Leap-day and out-of-range day clamping in dates.py, parse.py::page_date,
    #    store.py::_date_iso
    assert [(d.month, d.day) for d in find_dates("31 and 15 April 2027")] == [(4, 15)]
    joined_leap = find_dates("29 February to 15 March 2027")
    assert len(joined_leap) == 1
    assert (joined_leap[0].year, joined_leap[0].month, joined_leap[0].day) == (2027, 2, 28)

    fake_cands = replace(
        cands_ambig,
        dates={"d_leap": Found(0, Date("29 Feb 2027", 0, 11, 2027, 2, 29), False)},
    )
    p_dt = page_date(
        (Decision("role_d_leap", "agreed", "page_published_or_updated", None, {}),),
        fake_cands,
        dt.date(2026, 1, 1),
    )
    assert p_dt == dt.date(2027, 2, 28)

    aw_date = AwardDate(
        role="application_deadline",
        date=Date("29 Feb 2027", 0, 11, 2027, 2, 29),
        for_all=True,
        places=frozenset(),
        cycle=2027,
    )
    assert _date_iso(aw_date) == "2027-02-28"

    # 4. bound_host_reader wires screen and limit, and conflicting application fees
    #    populate "application_fee" / "ambiguous_application_fee"
    from apps.research.tap_seams import bound_host_reader

    host_reader = bound_host_reader(field="Computer Science")
    assert callable(host_reader.screen)
    assert host_reader.limit is not None

    fee_bundle = build_programme_bundle(
        [
            (
                "https://uni.example.org/fees",
                """
                <html><body>
                  <p>International application fee: EUR 50.</p>
                  <p>Non-EU application fee: EUR 100.</p>
                </body></html>
                """,
            )
        ],
        title="M.Sc. Fees",
    )
    fee_res = extract_tier0_programme_facts(fee_bundle)
    assert "application_fee" in fee_res.unresolved_slots
    assert "ambiguous_application_fee" in fee_res.high_risk_flags




