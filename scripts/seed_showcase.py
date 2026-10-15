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

#: Scholarships a student applies for on their own.
AWARDS = (
    {
        "name": "Danubia Government Scholarship",
        "holder": "Danube Education Agency",
        "domain": "elmify-demo-danubia-scholarship.org",
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
        "domain": "elmify-demo-hanbit-scholars.org",
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
        "domain": "elmify-demo-rhine-talent.org",
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
        "domain": "elmify-demo-anatolia-science.org",
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
        "domain": "elmify-demo-caspian-futures.org",
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

#: What every programme-attached award asks, so programme pages show requirements too.
_ADMISSION = (
    ("PRIOR_DEGREE", "GTE", "BACHELOR", "A bachelor's degree in chemistry or a closely related field."),
    ("GRADE", "GTE", "70 100", "A bachelor's average of at least 70 out of 100 (or equivalent)."),
    ("LANGUAGE", "GTE", "English B2", "English at B2 or above: IELTS 6.5, TOEFL iBT 90 or equivalent."),
)

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
            official_website=f"https://{slug}.example.org",
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
        for key, operator, value, text in _ADMISSION:
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
    from apps.funding.models import PackCandidate
    from apps.tenancy.context import tenant_scope

    client = Client()
    client.force_login(student)
    with tenant_scope(agency.id):
        ids = list(
            PackCandidate.objects.filter(pack_version__published_at__isnull=False)
            .values_list("candidate_id", flat=True)
        )
    added = 0
    for candidate_id in ids:
        response = client.post(f"/student/applications/add/{candidate_id}/", HTTP_HOST=HOST)
        added += response.status_code == 302
    print(f"Pack: {len(ids)} options, {added} added to My applications")


#: What each programme's page asks for, as the kit's copied sentences.
_KIT = [
    "Upload a CV in English.",
    "A motivation letter of no more than two pages.",
    "Two recommendation letters from academic referees.",
    "Official transcript of records.",
    "Copy of your passport.",
    "Proof of English: IELTS 6.5 or equivalent.",
]


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
            application.deadline = datetime(day.year, day.month, day.day, 21, 59, tzinfo=UTC)
            application.deadline_timezone = "Europe/Berlin"
            application.kit_requirements = list(_KIT)
            if started:
                application.started_at = now - timedelta(days=7)
                application.portal_form = PortalForm.objects.create(
                    portal_host="apply.example.org", form_key=f"k-{uuid4()}",
                    form_url="https://apply.example.org/start",
                )
            if state != "PREPARING":
                application.state = state
            if outcome:
                application.outcome = outcome
                application.outcome_source = "PERSON"
                application.outcome_recorded_at = now - timedelta(days=3)
            application.save()
        print(f"Staged {len(applications)} applications")


def _facts_and_documents(agency, student) -> None:
    """Confirmed facts, a CV, two letters, uploads, and a few open questions."""
    from apps.concierge.models import DocumentVersion
    from apps.documents.models import DocumentDraft, VerifiedFact
    from apps.documents.schemas import EducationEntry, ExperienceEntry, LanguageEntry, SkillEntry
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
        (C.LANGUAGE, fact_payload(LanguageEntry(language="Azerbaijani", mother_tongue=True),
                                  category=C.LANGUAGE)),
        (C.LANGUAGE, fact_payload(LanguageEntry(
            language="English", cefr_level="C1", test_name="IELTS Academic", test_score="7.0"
        ), category=C.LANGUAGE)),
        (C.SKILL, fact_payload(SkillEntry(name="FTIR spectroscopy"), category=C.SKILL)),
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

        DocumentDraft.objects.create(
            tenant_id=agency.id, student=student, kind=DocumentDraft.Kind.CV, version=1,
            render_variant="STANDARD", content=_cv_content(),
            status=DocumentDraft.Status.APPROVED, approved_by=student, approved_at=now,
            rendered_filename="Aysel-Mammadova-CV.pdf",
        )
        programmes = [
            a for a in Application.objects.filter(student=student).select_related("candidate")
            if a.candidate is not None and a.candidate.program_id is not None
        ]
        # Five letters approved, one waiting for the student, the rest unwritten.
        pairs = zip(programmes[:6], ("APPROVED",) * 5 + ("DRAFT",), strict=False)
        for version, (application, status) in enumerate(pairs, start=1):
            DocumentDraft.objects.create(
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
        for kind in ("PASSPORT", "TRANSCRIPT", "LANGUAGE_CERTIFICATE", "RECOMMENDATION"):
            DocumentVersion.objects.create(
                tenant_id=agency.id, student=student, kind=kind, state="AVAILABLE",
                object_key=f"demo/{uuid4()}.pdf", content_type="application/pdf",
                expires_on=date(2031, 4, 1) if kind == "PASSPORT" else None,
            )
    print("Facts, CV, letters and uploads added")


def _cv_content() -> dict:
    from apps.documents.schemas import CVContent

    return CVContent.model_validate({
        "personal_information": {
            "full_name": "Aysel Mammadova", "email": "aysel.demo@example.com",
            "citizenship": "Azerbaijani",
        },
        "education": [{
            "degree_as_awarded": "Bakalavr, Kimya", "degree_english": "BSc Chemistry",
            "institution_original": "Bakı Dövlət Universiteti",
            "institution_english": "Baku State University", "city": "Baku", "country": "AZ",
            "start_date": "2022-09", "end_date": "2026-06", "grade_native": "88",
            "grade_scale": "0-100",
        }],
        "experience": [{
            "employer": "Institute of Petrochemical Processes", "title": "Research intern",
            "city": "Baku", "country": "AZ", "start_date": "2025-06", "end_date": "2025-09",
            "bullets": [
                "Prepared and characterised polymer samples with FTIR spectroscopy.",
                "Kept the lab's sample log for a team of six researchers.",
            ],
        }],
        "research": [], "publications": [], "awards": [],
        "skills": [{"name": "FTIR spectroscopy"}, {"name": "Python for data analysis"}],
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
        (you, "Hi Leyla! Should I take the IELTS again before the Danubia deadline?"),
        (staff, "Your 7.0 is enough for every option on your list. Spend the time on letters."),
        (you, "Great. Who should I ask for recommendation letters?"),
        (staff, "Your thesis supervisor and the lab head from your internship. "
                "Ask this week, so they have a month."),
    )
    for client, body in conversation:
        url = (
            "/student/messages/send/" if client is you
            else f"/counselor/students/{student_m.id}/messages/send/"
        )
        client.post(url, {"body": body}, HTTP_HOST=HOST)
    print("Messages added")


if __name__ == "__main__":
    main()
