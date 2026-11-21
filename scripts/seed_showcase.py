# ruff: noqa: E501 -- demo data rows read better on one line
"""Seed a LOCAL database with a full, realistic-looking student, for demos.

    DJANGO_DEBUG=true uv run python scripts/seed_showcase.py

Like seed_demo.py, but with enough data that every student page has something
on it: programmes and scholarships in eight countries, grade and language
requirements, applications at every stage with deadlines and missing
documents, a CV, motivation letters, uploads, questions and messages.

Everything is FICTIONAL. Universities, scholarships, amounts and rules are
invented for the demo (real cities, made-up institutions), so a screenshot of
this database must never be presented as real catalogue data.

The catalogue and pack go through the real engine (consultation -> research ->
publish), so the "why you fit" checks on each page are the engine's own
decisions. Only what has no offline path (generated documents, portal
progress, uploads) is written directly.

Never run against a real database. Run it on an empty one:
    docker compose down -v && docker compose up -d postgres
    uv run python manage.py migrate
    uv run python scripts/seed_showcase.py

Logins (password for all: elmify-demo-2026): aysel (student), counselor, owner.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
os.environ.setdefault("DJANGO_DEBUG", "true")

import django  # noqa: E402

django.setup()

import seed_demo  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from django.utils import timezone  # noqa: E402

HOST = "localhost"
PASSWORD = "elmify-demo-2026"

if settings.DATABASES["default"]["HOST"] not in {"127.0.0.1", "localhost"}:
    sys.exit("Refusing: seed_showcase only runs against a local database.")


# --------------------------------------------------------------------------
# The catalogue. Every name here is invented.
# --------------------------------------------------------------------------

#: (institution, city, country, programme, months, tuition, currency, housing a month)
PROGRAMMES = (
    ("Isar Technical University", "Munich", "DE", "MSc Chemistry", 24, "0", "EUR", "650"),
    ("Neckar University", "Heidelberg", "DE", "MSc Molecular Chemistry", 24, "3000", "EUR", "520"),
    ("Northsea University", "Groningen", "NL", "MSc Sustainable Chemistry", 24, "16500", "EUR", "600"),
    ("Danube University of Technology", "Budapest", "HU", "MSc Applied Chemistry", 24, "5200", "EUR", "380"),
    ("Euganea University", "Padua", "IT", "MSc Industrial Chemistry", 24, "2600", "EUR", "420"),
    ("Hanbit Institute of Science", "Daejeon", "KR", "MSc Chemistry and Materials", 24, "4800", "EUR", "350"),
    ("Bosphorus Science University", "Istanbul", "TR", "MSc Organic Chemistry", 24, "3500", "EUR", "300"),
    ("Caledonian University", "Edinburgh", "GB", "MSc Chemistry with Data Science", 12, "26000", "EUR", "900"),
)

#: Programme-attached funding: (programme name, award name, kind, amount, period).
ATTACHED = (
    ("MSc Sustainable Chemistry", "Northsea Excellence Waiver", "TUITION", "8250", "ANNUAL"),
    ("MSc Molecular Chemistry", "Neckar Tuition Waiver", "TUITION", "3000", "ANNUAL"),
    ("MSc Chemistry", "Isar Graduate Stipend", "STIPEND", "750", "MONTHLY"),
    ("MSc Applied Chemistry", "Danube Merit Waiver", "TUITION", "5200", "ANNUAL"),
    ("MSc Industrial Chemistry", "Euganea Regional Study Grant", "STIPEND", "560", "MONTHLY"),
    ("MSc Chemistry with Data Science", "Caledonian International Award", "TUITION", "6000", "ANNUAL"),
    ("MSc Chemistry and Materials", "Hanbit Lab Assistantship", "ASSISTANTSHIP", "700", "MONTHLY"),
    ("MSc Organic Chemistry", "Bosphorus Merit Scholarship", "TUITION", "3500", "ANNUAL"),
)

#: Official websites used for demo provenance links so clicking "Open programme page"
#: or "Official source" resolves in a browser instead of failing DNS lookup.
INSTITUTION_URLS = {
    "Isar Technical University": "https://www.tum.de/en/",
    "Neckar University": "https://www.uni-heidelberg.de/en",
    "Northsea University": "https://www.rug.nl/",
    "Danube University of Technology": "https://www.bme.hu/?language=en",
    "Euganea University": "https://www.unipd.it/en/",
    "Hanbit Institute of Science": "https://www.kaist.ac.kr/en/",
    "Bosphorus Science University": "https://bogazici.edu.tr/en-US/Index",
    "Caledonian University": "https://www.ed.ac.uk/",
}

#: Scholarships a student applies for on their own.
AWARDS = (
    {
        "name": "Danubia Government Scholarship",
        "holder": "Danube Education Agency",
        "domain": "stipendiumhungaricum.hu",
        "country": "HU",
        "family": "GOVERNMENT_SCHOLARSHIP",
        "timing": "PRE_ARRIVAL",
        "cycle": "ANNUAL_FIXED",
        "months": 24,
        "tuition": "FULL",
        "living": "PARTIAL",
        "benefits": (
            ("TUITION", None, "Tuition is covered in full for the whole programme."),
            ("STIPEND", "320", "A monthly stipend of 320 EUR."),
            ("HOUSING", "120", "A housing allowance of 120 EUR a month."),
        ),
        "conditions": (
            ("GRADE", "GTE", "75 100", "Applicants need an average of at least 75 out of 100 in their bachelor's degree."),
            ("LANGUAGE", "GTE", "English B2", "English at B2 level or higher, shown by IELTS, TOEFL or an English-taught degree."),
            ("CITIZENSHIP", "IN", "AZ,UZ,KZ,KG,TJ,TR,GE,PK,IN", "Open to citizens of partner countries, including Azerbaijan."),
            ("AGE", "LTE", "35", "Applicants must be 35 or younger on the closing date."),
        ),
        "bond": None,
    },
    {
        "name": "Hanbit Global Scholars Programme",
        "holder": "Hanbit Science Foundation",
        "domain": "www.studyinkorea.go.kr",
        "country": "KR",
        "family": "PRIVATE_FOUNDATION",
        "timing": "PRE_ARRIVAL",
        "cycle": "ANNUAL_FIXED",
        "months": 24,
        "tuition": "FULL",
        "living": "FULL",
        "benefits": (
            ("TUITION", None, "Full tuition at the host university."),
            ("STIPEND", "950", "A living allowance of 950 EUR a month."),
            ("TRAVEL", "800", "One return flight, up to 800 EUR."),
        ),
        "conditions": (
            ("GRADE", "GTE", "80 100", "A bachelor's average of 80/100 or above."),
            ("LANGUAGE", "GTE", "English B2", "English proficiency at B2 or above."),
            ("AGE", "LTE", "40", "Under 40 at the start of the programme."),
        ),
        "bond": None,
    },
    {
        "name": "Rhine Talent Scholarship",
        "holder": "Rhine Talent Foundation",
        "domain": "www.daad.de",
        "country": "DE",
        "family": "PRIVATE_FOUNDATION",
        "timing": "EITHER",
        "cycle": "ANNUAL_FIXED",
        "months": 24,
        "tuition": "NONE",
        "living": "FULL",
        "benefits": (
            ("STIPEND", "934", "934 EUR a month for living costs."),
            ("INSURANCE", "110", "Health insurance, about 110 EUR a month."),
        ),
        "conditions": (
            ("GRADE", "GTE", "85 100", "Excellent grades: at least 85 out of 100."),
            ("OTHER", "PRESENT", "", "Applicants should show social or civic engagement alongside their studies."),
        ),
        "bond": None,
    },
    {
        "name": "Anatolia Science Scholarship",
        "holder": "Anatolia Research Council",
        "domain": "www.turkiyeburslari.gov.tr",
        "country": "TR",
        "family": "GOVERNMENT_SCHOLARSHIP",
        "timing": "PRE_ARRIVAL",
        "cycle": "ANNUAL_FIXED",
        "months": 24,
        "tuition": "FULL",
        "living": "PARTIAL",
        "benefits": (
            ("TUITION", None, "Tuition fees are paid by the council."),
            ("STIPEND", "600", "600 EUR a month."),
        ),
        "conditions": (
            ("GRADE", "GTE", "70 100", "A minimum average of 70/100."),
            ("AGE", "LTE", "30", "Applicants must be under 30."),
        ),
        "bond": None,
    },
    {
        "name": "Caspian Futures Fellowship",
        "holder": "Caspian Futures Fund",
        "domain": "dp.edu.az",
        "country": "AZ",
        "family": "GOVERNMENT_SCHOLARSHIP",
        "timing": "PRE_ARRIVAL",
        "cycle": "ANNUAL_FIXED",
        "months": 24,
        "tuition": "FULL",
        "living": "FULL",
        "benefits": (
            ("TUITION", None, "Tuition anywhere on the fund's university list."),
            ("STIPEND", "1100", "1,100 EUR a month while abroad."),
        ),
        "conditions": (
            ("CITIZENSHIP", "IN", "AZ", "Citizens of Azerbaijan only."),
            ("GRADE", "GTE", "81 100", "A bachelor's average of at least 81 out of 100."),
        ),
        "bond": (60, "Fellows must return and work in Azerbaijan for five years after graduating."),
    },
)

#: Per-programme admission rules so each programme page reflects its own bar and wording.
_ADMISSION_BY_PROGRAMME = {
    "MSc Chemistry": (
        ("PRIOR_DEGREE", "GTE", "BACHELOR", "A bachelor's degree in chemistry or chemical engineering (at least 180 ECTS, including laboratory practicals in inorganic, organic, and physical chemistry)."),
        ("GRADE", "GTE", "78 100", "A bachelor's average of at least 78 out of 100 (German grade 2.2 or better on the Bavarian formula)."),
        ("LANGUAGE", "GTE", "English B2", "English at B2 or above: IELTS Academic 6.5, TOEFL iBT 88, or Cambridge CAE."),
    ),
    "MSc Molecular Chemistry": (
        ("PRIOR_DEGREE", "GTE", "BACHELOR", "A bachelor's degree in chemistry, biochemistry, or molecular sciences with a written research thesis."),
        ("GRADE", "GTE", "75 100", "A minimum undergraduate average of 75 out of 100 (or top third of the graduating class)."),
        ("LANGUAGE", "GTE", "English B2", "Proof of English at B2 level: IELTS 6.5 or TOEFL iBT 90."),
    ),
    "MSc Sustainable Chemistry": (
        ("PRIOR_DEGREE", "GTE", "BACHELOR", "A research-university BSc in chemistry or chemical technology covering catalysis, synthesis, and thermodynamics."),
        ("GRADE", "GTE", "75 100", "A cumulative GPA of at least 75/100 (Dutch 7.0/10 equivalent)."),
        ("LANGUAGE", "GTE", "English C1", "English at C1 or high B2: IELTS Academic 6.5 (no band below 6.0) or TOEFL iBT 92."),
    ),
    "MSc Applied Chemistry": (
        ("PRIOR_DEGREE", "GTE", "BACHELOR", "A BSc in chemistry, chemical engineering, or industrial chemistry with at least 40 credits in core chemical sciences."),
        ("GRADE", "GTE", "70 100", "A bachelor's average of at least 70 out of 100 across all completed semesters."),
        ("LANGUAGE", "GTE", "English B2", "English proficiency at B2 level: IELTS 6.0, TOEFL iBT 80, or equivalent certificate."),
    ),
    "MSc Industrial Chemistry": (
        ("PRIOR_DEGREE", "GTE", "BACHELOR", "A three- or four-year bachelor's degree (Laurea Triennale or foreign equivalent) in chemistry or industrial chemistry."),
        ("GRADE", "GTE", "72 100", "A bachelor's grade average of at least 72 out of 100 (Italian 85/110 equivalent)."),
        ("LANGUAGE", "GTE", "English B2", "English at CEFR B2 level verified by an international test certificate."),
    ),
    "MSc Chemistry and Materials": (
        ("PRIOR_DEGREE", "GTE", "BACHELOR", "A bachelor's degree in chemistry, materials science, or chemical engineering completed before enrollment in Daejeon."),
        ("GRADE", "GTE", "80 100", "A cumulative bachelor's average of at least 80 out of 100 (CGPA 3.2/4.3 on the Korean scale)."),
        ("LANGUAGE", "GTE", "English B2", "Official English score: IELTS Academic 6.5, TOEFL iBT 83, or TEPS 326."),
    ),
    "MSc Organic Chemistry": (
        ("PRIOR_DEGREE", "GTE", "BACHELOR", "A four-year bachelor's degree in chemistry with upper-division organic synthesis coursework."),
        ("GRADE", "GTE", "75 100", "A minimum undergraduate GPA of 75 out of 100 (2.75/4.00 on the YÖK scale)."),
        ("LANGUAGE", "GTE", "English B2", "English proficiency demonstrated by TOEFL iBT 84, IELTS 6.5, or Boğaziçi BUEPT pass."),
    ),
    "MSc Chemistry with Data Science": (
        ("PRIOR_DEGREE", "GTE", "BACHELOR", "A UK 2:1 honours degree (or international equivalent) in chemistry, chemical physics, or computational chemistry."),
        ("GRADE", "GTE", "80 100", "An undergraduate average of at least 80 out of 100 (UK Upper Second-Class Honours, 2:1)."),
        ("LANGUAGE", "GTE", "English C1", "English at IELTS Academic 7.0 (with at least 6.5 in each component) or TOEFL iBT 100."),
    ),
}
_ADMISSION = _ADMISSION_BY_PROGRAMME["MSc Applied Chemistry"]

COUNTRY_TIMEZONES = {
    "DE": "Europe/Berlin",
    "NL": "Europe/Amsterdam",
    "HU": "Europe/Budapest",
    "IT": "Europe/Rome",
    "KR": "Asia/Seoul",
    "TR": "Europe/Istanbul",
    "GB": "Europe/London",
    "AZ": "Asia/Baku",
}

SHOWCASE_RATES = {
    "EUR": "1", "USD": "1.0850", "GBP": "0.8450", "AZN": "1.8450",
    "KRW": "1480", "TRY": "37", "HUF": "395", "INR": "94.5", "PKR": "302",
}


def main() -> None:
    from apps.concierge.models import StudentCycle
    from apps.research.models import PlatformAgency
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Agency, CounselorAssignment, Membership, TenantDomain

    User = get_user_model()
    if TenantDomain.objects.filter(host=HOST).exists():
        sys.exit(
            "Already seeded (a tenant owns 'localhost'). Reset the database first:\n"
            "  docker compose down -v && docker compose up -d postgres\n"
            "  uv run python manage.py migrate"
        )

    seed_demo._publish_legal_documents()
    agency = Agency.objects.create(name="Elmify", brand_primary_color="#4F46E5")
    TenantDomain.objects.create(agency=agency, host=HOST, verified_at=timezone.now())
    student = User.objects.create_user(
        username="aysel", password=PASSWORD, first_name="Aysel", last_name="Mammadova",
        email="aysel.demo@example.com",
    )
    counselor = User.objects.create_user(
        username="counselor", password=PASSWORD, first_name="Leyla", last_name="Huseynova"
    )
    owner = User.objects.create_user(username="owner", password=PASSWORD)
    platform = User.objects.create_user(username="platform", password=PASSWORD)
    PlatformAgency.objects.create(agency=agency)
    with tenant_scope(agency.id):
        student_m = Membership.objects.create(
            tenant=agency, user=student, role=Membership.Role.STUDENT,
            application_email="aysel.demo@example.com",
        )
        counselor_m = Membership.objects.create(
            tenant=agency, user=counselor, role=Membership.Role.COUNSELOR
        )
        Membership.objects.create(tenant=agency, user=owner, role=Membership.Role.OWNER)
        Membership.objects.create(tenant=agency, user=platform, role=Membership.Role.PLATFORM_ADMIN)
        CounselorAssignment.objects.create(tenant=agency, counselor=counselor_m, student=student_m)
        StudentCycle.objects.create(
            student=student_m, academic_year="2026-2027", paid_at=timezone.now()
        )

    secrets = {name: seed_demo._totp(user) for name, user in (
        ("counselor", counselor), ("owner", owner), ("platform", platform)
    )}
    seed_demo._accept_legal(student)
    _seed_catalogue()
    _consultation_and_research(student)
    _choose_everything(student, agency)
    _stage_the_applications(agency, student_m)
    _facts_and_documents(agency, student_m)
    _messages(student, counselor, agency, student_m)

    print("Showcase ready on http://localhost:8000/student/")
    print(f"Logins (password '{PASSWORD}'): aysel (student), counselor, owner")
    for name, key in secrets.items():
        print(f"  {name} TOTP secret (base32): {key}")


def _holder(award: dict) -> str:
    return "PRIVATE_FOUNDATION" if award["family"] == "PRIVATE_FOUNDATION" else "NATIONAL_GOVERNMENT"


def _seed_catalogue() -> None:
    from apps.funding.models import (
        BenefitRule,
        CostComponent,
        FundingBenefit,
        FundingOpportunity,
        FundingOpportunityProgram,
        Institution,
        Program,
    )
    from apps.research.register import record_organisation

    programmes = {}
    for inst_name, city, country, name, months, tuition, currency, housing in PROGRAMMES:
        slug = inst_name.lower().replace(" ", "-")
        institution = Institution.objects.create(
            canonical_key=f"institution:{uuid4()}", name=inst_name, country_code=country,
            official_website=INSTITUTION_URLS.get(inst_name, f"https://{slug}.example.org"),
        )
        program = Program.objects.create(
            institution=institution, canonical_key=f"program:{uuid4()}", name=name,
            campus_name="Main", city=city, country_code=country,
            location_key=f"{country}-{city.upper()}", degree_level="MASTER",
            teaching_languages=["English"], duration_months=months,
        )
        CostComponent.objects.create(
            program=program, kind="TUITION", amount=Decimal(tuition), currency=currency,
            period="ANNUAL",
        )
        CostComponent.objects.create(
            program=program, kind="HOUSING", amount=Decimal(housing), currency=currency,
            period="MONTHLY",
        )
        CostComponent.objects.create(
            program=program, kind="INSURANCE", amount=Decimal("95"), currency=currency,
            period="MONTHLY",
        )
        programmes[name] = program

    for programme_name, award_name, kind, amount, period in ATTACHED:
        program = programmes[programme_name]
        opportunity = FundingOpportunity.objects.create(
            canonical_key=f"read:PROGRAM:{uuid4()}", name=award_name,
            family="DEPARTMENT_OR_PROGRAM", scope_type="PROGRAM", program=program,
            kind="I2_PROGRAMME_ATTACHED", agreement="AGREED", served=True,
            money_form="FEE_WAIVER", route="AUTOMATIC_ON_ADMISSION",
        )
        FundingOpportunityProgram.objects.create(opportunity=opportunity, program=program)
        benefit = FundingBenefit.objects.create(
            opportunity=opportunity, kind=kind, amount=Decimal(amount), currency="EUR",
            period=period, description=f"{award_name}: {amount} EUR.",
        )
        for key, operator, value, text in _ADMISSION_BY_PROGRAMME.get(programme_name, _ADMISSION):
            BenefitRule.objects.create(
                benefit=benefit, kind="APPLICANT_CONDITION", key=key, operator=operator,
                value=value, rule_text=text, condition_type="AFFILIATION", scope_type="GLOBAL",
            )

    for award in AWARDS:
        organisation = record_organisation(
            domain=award["domain"], name=award["holder"],
            kind=_holder(award),
            country_code=award["country"], found_via="REGISTER",
        )
        opportunity = FundingOpportunity.objects.create(
            canonical_key=f"read:holder:{uuid4()}", name=award["name"],
            family=award["family"], scope_type="HOLDER",
            holder=_holder(award), holder_domain=award["domain"],
            holder_name=award["holder"], organisation=organisation, agreement="AGREED",
            served=True, money_form="GRANT", tuition=award["tuition"],
            living=award["living"], timing=award["timing"], cycle=award["cycle"],
            duration_months=award["months"],
        )
        first = None
        for kind, amount, text in award["benefits"]:
            benefit = FundingBenefit.objects.create(
                opportunity=opportunity, kind=kind,
                amount=Decimal(amount) if amount else None, currency="EUR" if amount else None,
                period="MONTHLY" if kind in ("STIPEND", "HOUSING", "INSURANCE") else (
                    "ONE_OFF" if kind == "TRAVEL" else "ANNUAL"
                ),
                description=text,
                amount_text=f"{amount} EUR" if amount else "",
            )
            first = first or benefit
        for key, operator, value, text in award["conditions"]:
            BenefitRule.objects.create(
                benefit=first, kind="APPLICANT_CONDITION", key=key, operator=operator,
                value=value, rule_text=text, condition_type="AFFILIATION",
                scope_type="GLOBAL",
            )
        if award["bond"]:
            months, text = award["bond"]
            BenefitRule.objects.create(
                benefit=first, kind="RETURN_SERVICE", rule_text=text,
                comparable_value=Decimal(months), scope_type="GLOBAL",
            )
        if award["country"] == "AZ":
            for prog in programmes.values():
                FundingOpportunityProgram.objects.create(opportunity=opportunity, program=prog)


def _consultation_and_research(student) -> None:
    """The consultation through the real form, and the research run in-process."""
    import apps.accounts.views as account_views
    from apps.funding.fx import RateTable
    from apps.research.schemas import ResearchMessage
    from apps.research.services import handle_research_message
    from apps.research.worker import process_research_message

    rates = RateTable(
        base="EUR", rates={k: Decimal(v) for k, v in SHOWCASE_RATES.items()},
        source="SHOWCASE", retrieved_on=date.today(),
    )
    queue: list = []
    account_views.dispatch_recommendation_run = lambda *, tenant_id, run_id: queue.append(
        ResearchMessage(kind="run_research", tenant_id=tenant_id, run_id=run_id)
    )
    client = Client()
    client.force_login(student)
    answers = (
        ("nationality", "AZ"),
        ("country_of_residence", "AZ"),
        ("date_of_birth", "2002-05-01"),
        ("target_field", "Chemistry"),
        ("allowed_countries", "DE,NL,HU,IT,KR,TR,GB"),
        ("excluded_countries", ""),
        ("intended_intake", "2027-09-01"),
        ("funding_dependency", "MANDATORY"),
        ("application_budget", {"amount": "400.00", "currency": "EUR"}),
        ("budget_stretch", ""),
        ("career_intent", "PHD"),
        ("acceptable_teaching_languages", "English"),
        ("language_evidence", [{
            "language": "English", "level": "C1", "evidence_type": "TEST",
            "available_by": "2026-11-30",
        }]),
        ("academic_history", [{
            "institution": "Baku State University", "country_code": "AZ",
            "qualification": "BSc", "field": "Chemistry", "grade": "88",
            "grading_scale": "100", "completed_on": "2026-06-30",
        }]),
        ("additional_notes", "Interested in green chemistry and catalysis."),
    )
    for key, value in answers:
        response = client.post(
            "/student/profile/",
            {"key": key, "value": json.dumps(value) if isinstance(value, (dict, list)) else value},
            HTTP_HOST=HOST,
        )
        if response.status_code != 200:
            print(f"  profile answer {key} refused ({response.status_code}); skipped")
    client.post("/student/profile/", {"action": "confirm"}, HTTP_HOST=HOST)
    for message in queue:
        process_research_message(message, lambda value: handle_research_message(value, rates=rates))


def _choose_everything(student, agency) -> None:
    from apps.funding.models import RecommendationCandidate
    from apps.tenancy.context import tenant_scope

    client = Client()
    client.force_login(student)
    with tenant_scope(agency.id):
        ids = list(
            RecommendationCandidate.objects.filter(
                state=RecommendationCandidate.State.VISIBLE, eligible=True
            ).values_list("id", flat=True)
        )
    added = 0
    for candidate_id in ids:
        response = client.post(
            f"/student/applications/add/{candidate_id}/",
            {"seen": "1", "confirm": "1"},
            HTTP_HOST=HOST,
        )
        added += response.status_code == 302
    print(f"Pack: {len(ids)} options, {added} added to My applications")


#: Tailored kit requirements per programme/scholarship so each detail page reflects its actual portal checklist.
_KIT = [
    "Upload a CV in English.",
    "A motivation letter of no more than two pages.",
    "Two recommendation letters from academic referees.",
    "Official transcript of records.",
    "Copy of your passport.",
    "Proof of English: IELTS 6.5 or equivalent.",
]

_KIT_BY_NAME: dict[str, list[str]] = {
    "MSc Chemistry": [
        "Tabular academic CV in English (max 2 pages) detailing laboratory courses and bachelor's thesis.",
        "TUMonline motivation letter (1–2 pages) explaining your choice of catalysis and synthesis modules in Munich.",
        "Two academic recommendation letters from university chemistry faculty.",
        "Official bachelor's transcript of records showing at least 180 ECTS and grading scale.",
        "Scan of your valid passport identification page.",
        "Proof of English proficiency: IELTS Academic 6.5 or TOEFL iBT 88.",
    ],
    "MSc Molecular Chemistry": [
        "Academic curriculum vitae (CV) in English including bachelor's thesis abstract.",
        "Statement of motivation (max 1,000 words) for molecular & supramolecular chemistry at Heidelberg.",
        "Two letters of recommendation from professors who supervised your laboratory work.",
        "Official transcript of records and module handbook descriptions.",
        "Copy of your passport identification page.",
        "English language certificate at B2 level (IELTS 6.5 or TOEFL iBT 90).",
    ],
    "MSc Sustainable Chemistry": [
        "Detailed academic CV in English highlighting green chemistry and catalysis lab skills.",
        "Motivation letter (max 2 pages) addressing Groningen's sustainable synthesis research tracks.",
        "Two academic reference letters submitted via the Studielink / OAS portal.",
        "Certified bachelor's transcript of records with course syllabus summary.",
        "Copy of your valid international passport.",
        "Proof of English: IELTS Academic 6.5 (minimum 6.0 per band) or TOEFL iBT 92.",
    ],
    "MSc Applied Chemistry": [
        "Europass or academic CV in English listing analytical and industrial chemistry coursework.",
        "Motivation letter (1–2 pages) tailored to Budapest's applied chemical engineering faculty.",
        "Two academic recommendation letters on official university letterhead.",
        "Official bachelor's transcript of records with credit hours and grade key.",
        "Copy of your passport photo and signature page.",
        "Proof of English proficiency: IELTS 6.0 or TOEFL iBT 80 certificate.",
    ],
    "MSc Industrial Chemistry": [
        "Academic CV in English detailing polymer, process, or catalysis laboratory training.",
        "Motivation statement (max 2 pages) for the Padua Department of Chemical Sciences.",
        "Two recommendation letters from academic referees.",
        "Official transcript of records with Diploma Supplement or course descriptions.",
        "Copy of your valid passport.",
        "English B2 certificate (IELTS 6.5 or equivalent international test).",
    ],
    "MSc Chemistry and Materials": [
        "Research-focused CV in English listing laboratory instrumentation, synthesis techniques, and thesis title.",
        "Motivation letter & Daejeon Graduate School study plan (max 2 pages) naming target catalysis or materials labs at Hanbit.",
        "Two confidential recommendation letters from chemistry faculty submitted through the Hanbit portal.",
        "Official bachelor's transcript of records with 100-point grading scale conversion.",
        "Copy of your international passport identification page.",
        "Official English score report: IELTS Academic 6.5, TOEFL iBT 83, or TEPS 326.",
    ],
    "MSc Organic Chemistry": [
        "Academic CV in English including organic synthesis and spectroscopy laboratory experience.",
        "Statement of purpose (1–2 pages) outlining your proposed master's thesis direction in Istanbul.",
        "Two academic reference letters from chemistry professors.",
        "Official undergraduate transcript of records.",
        "Copy of your passport identification page.",
        "Proof of English: TOEFL iBT 84, IELTS Academic 6.5, or Boğaziçi BUEPT certificate.",
    ],
    "MSc Chemistry with Data Science": [
        "Academic CV in English highlighting quantitative, programming, and wet-lab chemistry training.",
        "Personal statement (500–750 words) on combining machine learning and data science with molecular chemistry in Edinburgh.",
        "Two academic references from university faculty familiar with your research potential.",
        "Official bachelor's transcript of records (UK 2:1 equivalent, 80/100 or above).",
        "Copy of your passport identification page.",
        "Proof of English at C1 level: IELTS Academic 7.0 (at least 6.5 in each component).",
    ],
    "Hanbit Global Scholars Programme": [
        "Full academic CV in English listing honours, research projects, and laboratory skills.",
        "Hanbit Global Scholars personal statement & study plan in South Korea (max 2 pages).",
        "Two sealed or portal-submitted academic recommendation letters.",
        "Official bachelor's transcript of records.",
        "Copy of your passport proving citizenship eligibility.",
        "Proof of English proficiency: IELTS Academic 6.5 or TOEFL iBT 83.",
    ],
    "Danubia Government Scholarship": [
        "Europass CV in English for the Stipendium Hungaricum / Danubia online system.",
        "One-page motivation letter addressed to the Hungarian host university and Tempus Public Foundation.",
        "Two academic recommendation letters signed by university faculty.",
        "Official bachelor's transcript of records.",
        "Copy of your valid international passport.",
        "Proof of English proficiency at B2 level (IELTS 6.5 or equivalent).",
    ],
    "Rhine Talent Scholarship": [
        "Tabular CV in English highlighting academic merit and civic/community engagement.",
        "Scholarship motivation essay (1–2 pages) for the Rhine Talent Foundation selection committee.",
        "Two academic letters of recommendation from university professors.",
        "Official bachelor's transcript of records showing an average of 85/100 or higher.",
        "Copy of your passport identification page.",
        "Proof of English proficiency (IELTS Academic 6.5 or equivalent).",
    ],
}


def _stage_the_applications(agency, student) -> None:
    """Give the list every stage a real student passes through."""
    from apps.portals.models import Application, PortalForm
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.db import tenant_transaction

    now = timezone.now()
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        applications = list(
            Application.objects.filter(student=student).select_related("candidate")
            .order_by("created_at")
        )
        plans = [
            # (days to deadline, state, started, outcome)
            (5, "PREPARING", True, ""),
            (21, "PREPARING", False, ""),
            (12, "PREPARING", True, ""),
            (48, "PREPARING", False, ""),
            (-10, "SUBMITTED", True, ""),
            (-40, "CONFIRMED", True, "ADMITTED"),
            (33, "PREPARING", False, ""),
            (60, "PREPARING", False, ""),
            (75, "PREPARING", False, ""),
            (90, "PREPARING", False, ""),
            (26, "PREPARING", True, ""),
            (40, "PREPARING", False, ""),
            (55, "PREPARING", False, ""),
        ]
        for application, (days, state, started, outcome) in zip(applications, plans, strict=False):
            day = (now + timedelta(days=days)).date()
            country = (
                application.candidate.country_code
                if application.candidate and application.candidate.country_code
                else "DE"
            )
            tz_name = COUNTRY_TIMEZONES.get(country, "Europe/Berlin")
            local_tz = ZoneInfo(tz_name)
            application.deadline = datetime(
                day.year, day.month, day.day, 23, 59, tzinfo=local_tz
            ).astimezone(UTC)
            application.deadline_timezone = tz_name
            prog_name = application.candidate.program_name if application.candidate else ""
            application.kit_requirements = list(_KIT_BY_NAME.get(prog_name, _KIT))
            if started:
                application.started_at = now - timedelta(days=7)
                source_url = (
                    application.candidate.evidence.source_url
                    if application.candidate and application.candidate.evidence
                    else "https://www.tum.de/en/"
                )
                source_domain = (
                    application.candidate.evidence.source_domain
                    if application.candidate and application.candidate.evidence
                    else "www.tum.de"
                )
                application.portal_form = PortalForm.objects.create(
                    portal_host=source_domain, form_key=f"k-{uuid4()}",
                    form_url=source_url,
                )
            if state != "PREPARING":
                application.state = state
            if outcome:
                application.outcome = outcome
                application.outcome_source = "PERSON"
                application.outcome_recorded_at = now - timedelta(days=3)
            application.save()
            if application.candidate is not None:
                src_url = (
                    application.candidate.evidence.source_url
                    if application.candidate.evidence
                    else "https://www.tum.de/en/"
                )
                application.candidate.referee_requirements = [
                    {
                        "field": "count",
                        "value": "TWO",
                        "date": "",
                        "conditional": False,
                        "condition": "",
                        "rule_text": "Two academic letters of recommendation.",
                        "source_url": src_url,
                    },
                    {
                        "field": "kind",
                        "value": "ACADEMIC",
                        "date": "",
                        "conditional": False,
                        "condition": "",
                        "rule_text": "From university professors or thesis supervisors.",
                        "source_url": src_url,
                    },
                    {
                        "field": "mode",
                        "value": "PORTAL_INVITE",
                        "date": "",
                        "conditional": False,
                        "condition": "",
                        "rule_text": "Invited through the online portal or uploaded as signed PDF.",
                        "source_url": src_url,
                    },
                    {
                        "field": "institutional_email_required",
                        "value": "YES",
                        "date": "",
                        "conditional": False,
                        "condition": "",
                        "rule_text": "Institutional university email address required.",
                        "source_url": src_url,
                    },
                ]
                application.candidate.save(update_fields=["referee_requirements"])
        print(f"Staged {len(applications)} applications")


def _facts_and_documents(agency, student) -> None:
    """Confirmed facts, a CV, two letters, uploads, and a few open questions."""
    from apps.concierge.models import DocumentVersion
    from apps.documents.models import DocumentDraft, VerifiedFact
    from apps.documents.schemas import (
        AwardEntry,
        EducationEntry,
        ExperienceEntry,
        LanguageEntry,
        ResearchEntry,
        SkillEntry,
    )
    from apps.documents.verification import fact_payload
    from apps.portals.models import Application
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.db import tenant_transaction

    C = VerifiedFact.Category
    confirmed = [
        (C.IDENTITY, {"full_name": "Aysel Mammadova"}),
        (C.EDUCATION, fact_payload(EducationEntry(
            degree_as_awarded="Bakalavr, Kimya", degree_english="BSc Chemistry",
            institution_original="Bakı Dövlət Universiteti",
            institution_english="Baku State University", city="Baku", country="AZ",
            start_date="2022-09", end_date="2026-06", grade_native="88", grade_scale="0-100",
        ), category=C.EDUCATION)),
        (C.EXPERIENCE, fact_payload(ExperienceEntry(
            employer="Institute of Petrochemical Processes", title="Research intern",
            city="Baku", country="AZ", start_date="2025-06", end_date="2025-09",
            bullets=(
                "Prepared and characterised polymer samples with FTIR spectroscopy.",
                "Kept the lab's sample log for a team of six researchers.",
            ),
        ), category=C.EXPERIENCE)),
        (C.RESEARCH, fact_payload(ResearchEntry(
            thesis_title="Catalytic oxidation of substituted aromatics",
            institution="Baku State University",
            supervisor="Prof. Rauf Aliyev",
            end_date="2026-06",
        ), category=C.RESEARCH)),
        (C.AWARD, fact_payload(AwardEntry(
            title="Dean's List, Faculty of Chemistry",
            awarding_body="Baku State University",
            date="2024-06",
        ), category=C.AWARD)),
        (C.LANGUAGE, fact_payload(LanguageEntry(language="Azerbaijani", mother_tongue=True),
                                  category=C.LANGUAGE)),
        (C.LANGUAGE, fact_payload(LanguageEntry(
            language="English", cefr_level="C1", test_name="IELTS Academic", test_score="7.0"
        ), category=C.LANGUAGE)),
        (C.SKILL, fact_payload(SkillEntry(name="FTIR spectroscopy"), category=C.SKILL)),
        (C.SKILL, fact_payload(SkillEntry(name="GC-MS chromatography"), category=C.SKILL)),
        (C.SKILL, fact_payload(SkillEntry(name="NMR interpretation"), category=C.SKILL)),
        (C.SKILL, fact_payload(SkillEntry(name="Python for data analysis"), category=C.SKILL)),
    ]
    unconfirmed = [
        (C.EXPERIENCE, fact_payload(ExperienceEntry(
            employer="Green Caspian Society", title="Volunteer coordinator",
            city="Baku", country="AZ", start_date="2023-03", end_date="2024-05",
            bullets=("Organised four beach clean-ups with 120 volunteers.",),
        ), category=C.EXPERIENCE)),
        (C.SKILL, fact_payload(SkillEntry(name="HPLC"), category=C.SKILL)),
    ]
    now = timezone.now()
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        for category, payload in confirmed:
            VerifiedFact.objects.create(
                tenant_id=agency.id, student=student, category=category, payload=payload,
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="demo:showcase", created_by=student, confirmed_by=student,
                confirmed_at=now,
            )
        for category, payload in unconfirmed:
            VerifiedFact.objects.create(
                tenant_id=agency.id, student=student, category=category, payload=payload,
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="demo:showcase", created_by=student,
            )

        cv = DocumentDraft.objects.create(
            tenant_id=agency.id, student=student, kind=DocumentDraft.Kind.CV, version=1,
            is_general=True, destination_label="General Master CV",
            render_variant="STANDARD", content=_cv_content(),
            status=DocumentDraft.Status.APPROVED, approved_by=student, approved_at=now,
            rendered_filename="Aysel-Mammadova-CV.pdf",
        )
        stored = [(cv, "Aysel-Mammadova-CV.pdf")]
        programmes = [
            a for a in Application.objects.filter(student=student).select_related("candidate")
            if a.candidate is not None and a.candidate.program_id is not None
        ]
        tailored_cv_specs = [
            (0, "GERMAN_TABULAR", "Aysel-Mammadova-CV-Isar-Tabular.pdf"),
            (2, "EUROPASS", "Aysel-Mammadova-CV-Euganea-Europass.pdf"),
            (1, "STANDARD", "Aysel-Mammadova-CV-Hanbit-Research.pdf"),
        ]
        for cv_ver, (prog_idx, variant, cv_fname) in enumerate(tailored_cv_specs, start=2):
            if prog_idx < len(programmes):
                target_app = programmes[prog_idx]
                dest_label = ", ".join(
                    p for p in (target_app.title, target_app.candidate.institution_name) if p
                )
                tailored_cv = DocumentDraft.objects.create(
                    tenant_id=agency.id, student=student, kind=DocumentDraft.Kind.CV,
                    version=cv_ver, is_general=False,
                    application=target_app,
                    programme_id=target_app.candidate.program_id,
                    destination_label=dest_label,
                    render_variant=variant,
                    content=_cv_content(dest_label),
                    status=DocumentDraft.Status.APPROVED, approved_by=student, approved_at=now,
                    rendered_filename=cv_fname,
                )
                stored.append((tailored_cv, cv_fname))
        # Five letters approved, one waiting for the student, the rest unwritten.
        pairs = zip(programmes[:6], ("APPROVED",) * 5 + ("DRAFT",), strict=False)
        for version, (application, status) in enumerate(pairs, start=1):
            letter = DocumentDraft.objects.create(
                tenant_id=agency.id, student=student,
                kind=DocumentDraft.Kind.MOTIVATION_LETTER, version=version,
                programme_id=application.candidate.program_id, status=status,
                approved_by=student if status == "APPROVED" else None,
                approved_at=now if status == "APPROVED" else None,
                rendered_filename=(
                    f"Motivation-letter-{version}.pdf" if status == "APPROVED" else ""
                ),
                content=_letter(application.candidate.program_name,
                                application.candidate.institution_name),
            )
            if status == "APPROVED":
                stored.append((letter, f"Motivation-letter-{version}.pdf"))
            else:
                # The one draft waits for the counsellor, so "Letters to review"
                # has something to show.
                Application.objects.filter(id=application.id).update(letter_note="flagged")
        awards = [
            a for a in Application.objects.filter(student=student).select_related("candidate")
            if a.candidate is not None and a.candidate.opportunity_id is not None
        ]
        for offset, award_app in enumerate(awards, start=len(programmes[:6]) + 1):
            holder = str((award_app.candidate.funding_card or {}).get("holder") or "")
            fname = f"Scholarship-essay-{offset}.pdf"
            essay = DocumentDraft.objects.create(
                tenant_id=agency.id, student=student,
                kind=DocumentDraft.Kind.MOTIVATION_LETTER, version=offset,
                funding_opportunity_id=award_app.candidate.opportunity_id,
                application=award_app,
                status="APPROVED", approved_by=student, approved_at=now,
                rendered_filename=fname,
                content=_scholarship_essay(award_app.candidate.program_name, holder),
            )
            stored.append((essay, fname))
        # Without the files, every Download link on the Documents page is a 404
        # (found by the 2026-10-25 crawl): the worker stores a rendered PDF in
        # production, so the showcase has to as well.
        _store_pdfs(stored)
        for kind in ("PASSPORT", "TRANSCRIPT", "LANGUAGE_CERTIFICATE", "RECOMMENDATION"):
            DocumentVersion.objects.create(
                tenant_id=agency.id, student=student, kind=kind, state="AVAILABLE",
                object_key=f"demo/{uuid4()}.pdf", content_type="application/pdf",
                expires_on=date(2031, 4, 1) if kind == "PASSPORT" else None,
            )
    print("Facts, CV, letters and uploads added")


def _store_pdfs(drafts) -> None:  # type: ignore[no-untyped-def]
    from html import escape

    from weasyprint import HTML

    from apps.documents.render import render_cv
    from apps.documents.schemas import CVContent
    from apps.documents.storage import store_document

    for draft, filename in drafts:
        if draft.kind == "CV":
            variant = draft.render_variant if draft.render_variant in ("STANDARD", "GERMAN_TABULAR", "EUROPASS") else "STANDARD"
            pdf = render_cv(CVContent.model_validate(draft.content), variant=variant).pdf_bytes
        else:
            paragraphs = "".join(
                f"<p>{escape(unit['text'])}</p>" for unit in draft.content["units"]
            )
            pdf = HTML(string=(
                "<html><body style='font-family:serif;font-size:11pt;margin:2.5cm'>"
                f"<p>Dear Admissions Committee,</p>{paragraphs}"
                "<p>Yours sincerely,<br>Aysel Mammadova</p></body></html>"
            )).write_pdf()
        store_document(draft=draft, filename=filename, content=pdf or b"")


def _cv_content(target: str = "") -> dict:
    from apps.documents.schemas import CVContent

    if "Isar" in target or "Neckar" in target:
        grade_conversion = "1.6 German Bavarian scale"
        ects_credits = 240
        coursework = "Heterogeneous Catalysis, Organometallic Synthesis, Physical Chemistry, Instrumental Analysis"
        methods = "Bench-scale catalytic oxidation reactors, FTIR & GC-MS reaction monitoring."
        outcomes = "Quantified selectivity across 14 substituted aromatic substrates (grade 94/100)."
    elif "Euganea" in target or "Danube" in target:
        grade_conversion = "105/110 Italian Laurea equivalent"
        ects_credits = 240
        coursework = "Industrial Process Chemistry, Polymer Characterisation, Analytical Spectroscopy, Reaction Engineering"
        methods = "FTIR vibrational spectroscopy and chromatographic purity profiling."
        outcomes = "Validated catalyst recyclability over five consecutive batch cycles."
    elif "Hanbit" in target:
        grade_conversion = "4.0/4.5 Korean GPA scale"
        ects_credits = 240
        coursework = "Solid-State & Materials Chemistry, Catalytic Surface Science, Spectroscopic Methods"
        methods = "Transition-metal oxide catalyst synthesis, GC-MS kinetics, and Python data pipelines."
        outcomes = "Demonstrated 91% conversion efficiency under mild atmospheric conditions."
    else:
        grade_conversion = None
        ects_credits = 240
        coursework = "Organic & Inorganic Synthesis, Analytical Chemistry, Physical Chemistry, Spectroscopy"
        methods = "FTIR, GC-MS, and NMR characterisation of catalytic oxidation products."
        outcomes = None

    return CVContent.model_validate({
        "personal_information": {
            "full_name": "Aysel Mammadova", "email": "aysel.demo@example.com",
            "phone": "+994 50 555 0199", "citizenship": "Azerbaijani",
        },
        "education": [{
            "degree_as_awarded": "Bakalavr, Kimya", "degree_english": "BSc Chemistry",
            "institution_original": "Bakı Dövlət Universiteti",
            "institution_english": "Baku State University", "city": "Baku", "country": "AZ",
            "start_date": "2022-09", "end_date": "2026-06", "grade_native": "88",
            "grade_scale": "0-100",
            "grade_conversion": grade_conversion,
            "ects_credits": ects_credits,
            "relevant_coursework": coursework,
        }],
        "experience": [{
            "employer": "Institute of Petrochemical Processes", "title": "Research intern",
            "city": "Baku", "country": "AZ", "start_date": "2025-06", "end_date": "2025-09",
            "bullets": [
                "Prepared and characterised polymer samples with FTIR spectroscopy.",
                "Kept the lab's sample log for a team of six researchers.",
            ],
        }],
        "research": [{
            "thesis_title": "Catalytic oxidation of substituted aromatics",
            "institution": "Baku State University",
            "supervisor": "Prof. Rauf Aliyev",
            "end_date": "2026-06",
            "methods": methods,
            "outcomes": outcomes,
        }],
        "publications": [],
        "awards": [{
            "title": "Dean's List, Faculty of Chemistry",
            "awarding_body": "Baku State University",
            "date": "2024-06",
        }],
        "skills": [
            {"name": "FTIR spectroscopy"},
            {"name": "GC-MS chromatography"},
            {"name": "NMR interpretation"},
            {"name": "Python for data analysis"},
        ],
        "languages": [
            {"language": "Azerbaijani", "mother_tongue": True},
            {"language": "English", "cefr_level": "C1", "test_name": "IELTS Academic",
             "test_score": "7.0"},
        ],
        "document_language": "en",
    }).model_dump(mode="json")


def _letter(programme: str, institution: str) -> dict:
    where = institution or "your university"
    return {"language": "en", "units": [
        {"archetype": "opening", "text": (
            f"I am applying to the {programme} at {where} because I want to turn four years "
            "of chemistry training into research on cleaner industrial processes."
        )},
        {"archetype": "evidence", "text": (
            "During my internship at the Institute of Petrochemical Processes in Baku I "
            "prepared and characterised polymer samples with FTIR spectroscopy, and kept the "
            "sample log for a team of six. That work showed me how much a careful method "
            "matters before any result does."
        )},
        {"archetype": "fit", "text": (
            "Your programme's focus on catalysis and sustainable synthesis is the next step "
            "for me, and its research project in the second year is where I hope to begin "
            "the work I want to continue in a PhD."
        )},
        {"archetype": "closing", "text": (
            "I would bring discipline, curiosity and a clear reason to be there. Thank you "
            "for considering my application."
        )},
    ]}


def _scholarship_essay(award_name: str, holder: str) -> dict:
    sponsor = holder or "the Selection Committee"
    return {"language": "en", "units": [
        {"archetype": "opening", "text": (
            f"I am applying for the {award_name} awarded by {sponsor} to support my graduate "
            "studies in sustainable polymer chemistry and catalytic materials."
        )},
        {"archetype": "evidence", "text": (
            "During my BSc in Chemistry at Baku State University (GPA 88/100) and my research "
            "internship at the Institute of Petrochemical Processes, I synthesised and "
            "characterised biodegradable polyesters using FTIR spectroscopy and maintained the "
            "analytical sample log for a six-member research group."
        )},
        {"archetype": "fit", "text": (
            f"Support from the {award_name} will allow me to dedicate my full time to laboratory "
            "research on recyclable catalyst systems and bring modern green-chemistry methods "
            "back to industrial materials development after graduation."
        )},
        {"archetype": "closing", "text": (
            f"Thank you to {sponsor} for considering my scholarship essay and study plan."
        )},
    ]}


def _messages(student, counselor, agency, student_m) -> None:
    from django_otp import DEVICE_ID_SESSION_KEY
    from django_otp.plugins.otp_totp.models import TOTPDevice

    you = Client()
    you.force_login(student)
    staff = Client()
    staff.force_login(counselor)
    session = staff.session
    session[DEVICE_ID_SESSION_KEY] = TOTPDevice.objects.get(user=counselor).persistent_id
    session.save()
    conversation = (
        (
            you,
            "Hi Leyla! Should I retake IELTS (7.0 overall, 6.5 writing) before the Danubia and Neckar scholarship deadlines?",
        ),
        (
            staff,
            "Your 7.0 overall (with 6.5 in every band) already clears every MSc Chemistry programme and scholarship on your shortlist. Spend this week refining your motivation letters instead.",
        ),
        (
            you,
            "Got it — I confirmed my FTIR spectroscopy internship facts. Who should I ask for the two academic reference letters?",
        ),
        (
            staff,
            "Ask your BSc thesis supervisor to cover your catalysis coursework and your lab head to cover your FTIR polymer work. I just reviewed and approved both referee briefs in your workspace.",
        ),
    )
    for client, body in conversation:
        url = (
            "/student/messages/send/" if client is you
            else f"/counselor/students/{student_m.id}/messages/send/"
        )
        client.post(url, {"body": body}, HTTP_HOST=HOST)
    print("Messages added")
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.db import tenant_transaction

    with tenant_scope(agency.id), tenant_transaction(agency.id):
        _seed_referees(agency, student_m)


def _seed_referees(agency, student_m) -> None:
    from apps.documents.models import Referee, RefereeRequest
    from apps.portals.models import Application

    r1 = Referee.objects.create(
        tenant=agency,
        student=student_m,
        title="Prof.",
        name="Rauf Aliyev",
        institution="Baku State University",
        email="r.aliyev@bsu.edu.az",
        institutional_email=True,
        kind=Referee.Kind.ACADEMIC,
        relationship="Supervised my BSc Chemistry thesis on catalytic polymer synthesis (grade 95/100) and taught Advanced Organic Chemistry.",
        agreed_requests=12,
        gives_generic_letter=True,
        status=Referee.Status.ACTIVE,
    )
    r2 = Referee.objects.create(
        tenant=agency,
        student=student_m,
        title="Assoc. Prof.",
        name="Sevda Hasanova",
        institution="Baku State University",
        email="s.hasanova@bsu.edu.az",
        institutional_email=True,
        kind=Referee.Kind.ACADEMIC,
        relationship="Taught Analytical & Instrumental Chemistry (grade 92/100) and oversaw my spectroscopy lab practicum.",
        agreed_requests=12,
        gives_generic_letter=True,
        status=Referee.Status.ACTIVE,
    )
    Referee.objects.create(
        tenant=agency,
        student=student_m,
        title="Dr.",
        name="Kamran Guliyev",
        institution="SOCAR Polymer R&D Lab",
        email="k.guliyev@socarpolymer.az",
        institutional_email=True,
        kind=Referee.Kind.PROFESSIONAL,
        relationship="Supervised my summer polymer characterisation internship (FTIR and thermal analysis).",
        agreed_requests=6,
        gives_generic_letter=True,
        status=Referee.Status.ACTIVE,
    )
    for idx, app in enumerate(Application.objects.filter(student=student_m, outcome="").order_by("created_at")):
        RefereeRequest.objects.create(
            tenant=agency,
            referee=r1,
            application=app,
            mode=RefereeRequest.Mode.PORTAL_INVITE if idx % 2 == 0 else RefereeRequest.Mode.UPLOAD_ADDRESSED,
            state=RefereeRequest.State.AGREED if idx < 2 else RefereeRequest.State.PROPOSED,
        )
        RefereeRequest.objects.create(
            tenant=agency,
            referee=r2,
            application=app,
            mode=RefereeRequest.Mode.PORTAL_INVITE if idx % 2 == 0 else RefereeRequest.Mode.UPLOAD_GENERIC,
            state=RefereeRequest.State.ASKED if idx < 2 else RefereeRequest.State.PROPOSED,
        )
    print("Referees added")


if __name__ == "__main__":
    main()
