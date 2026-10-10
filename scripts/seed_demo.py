"""Seed a LOCAL demo database so every built screen can be clicked through.

    DJANGO_DEBUG=true uv run python scripts/seed_demo.py

Never run against a real database. It mirrors tests/acceptance (the vertical
slice): one agency on `localhost`, a student who completes the real consultation,
the real research handler run in-process, and the pack it publishes. It adds no
behaviour to the app; it only drives code paths that already exist.

Logins (password for all: elmify-demo-2026):
  aysel    student   -> http://localhost:8000/student/
  counselor          -> http://localhost:8000/counselor/   (TOTP, secret printed below)
  owner              -> http://localhost:8000/owner/       (TOTP, secret printed below)
  platform           -> http://localhost:8000/platform/resolution/ (TOTP)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
os.environ.setdefault("DJANGO_DEBUG", "true")

import django  # noqa: E402

django.setup()

from decimal import Decimal  # noqa: E402
from uuid import uuid4  # noqa: E402

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from django.utils import timezone  # noqa: E402

HOST = "localhost"
PASSWORD = "elmify-demo-2026"

if settings.DATABASES["default"]["HOST"] not in {"127.0.0.1", "localhost"}:
    sys.exit("Refusing: seed_demo only runs against a local database.")


def main() -> None:
    from apps.concierge.models import StudentCycle
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.models import Agency, Membership, TenantDomain

    User = get_user_model()
    if TenantDomain.objects.filter(host=HOST).exists():
        sys.exit("Already seeded (a tenant owns 'localhost'). Drop the database to re-seed.")

    _publish_legal_documents()

    agency = Agency.objects.create(name="Elmify Demo", brand_primary_color="#6D28D9")
    TenantDomain.objects.create(agency=agency, host=HOST, verified_at=timezone.now())

    student = User.objects.create_user(username="aysel", password=PASSWORD, first_name="Aysel")
    counselor = User.objects.create_user(username="counselor", password=PASSWORD)
    owner = User.objects.create_user(username="owner", password=PASSWORD)
    platform = User.objects.create_user(username="platform", password=PASSWORD)
    from apps.research.models import PlatformAgency
    from apps.tenancy.models import CounselorAssignment

    PlatformAgency.objects.create(agency=agency)
    with tenant_scope(agency.id):
        student_m = Membership.objects.create(
            tenant=agency, user=student, role=Membership.Role.STUDENT
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

    staff = (("counselor", counselor), ("owner", owner), ("platform", platform))
    secrets = {name: _totp(user) for name, user in staff}
    _accept_legal(student)
    _seed_catalogue()
    run_id = _consultation_and_research(student)
    _student_actions(student, counselor, agency)

    print(f"Agency {agency.id} on http://{HOST}:8000")
    print(f"Logins (password '{PASSWORD}'): aysel (student), counselor, owner")
    for name, key in secrets.items():
        print(f"  {name} TOTP secret (base32): {key}")
    print(f"Recommendation run: {run_id}")


def _publish_legal_documents() -> None:
    from apps.privacy import documents

    for kind, language, path in documents.shipped_files():
        documents.publish(kind, language, path.read_text(encoding="utf-8"), material=True)


def _accept_legal(user) -> None:
    """Accept the current legal documents through the real /privacy/accept/ form."""
    client = Client()
    client.force_login(user)
    from apps.privacy import acceptance
    from apps.tenancy.models import TenantDomain

    tenant_id = TenantDomain.objects.get(host=HOST).agency_id
    ids = [str(doc.id) for doc in acceptance.documents_to_accept(tenant_id, "en")]
    response = client.post("/privacy/accept/", {"consent": "on", "documents": ids}, HTTP_HOST=HOST)
    assert response.status_code == 302, response.status_code


def _totp(user) -> str:
    import base64

    from django_otp.plugins.otp_totp.models import TOTPDevice

    device = TOTPDevice.objects.create(user=user, name="demo", confirmed=True)
    return base64.b32encode(bytes.fromhex(device.key)).decode()


def _seed_catalogue() -> None:
    """Programmes and awards for the research engine to find. Same shapes as
    tests/acceptance/helpers.py::SliceDriver.seed_catalogue, a few more rows."""
    from apps.funding.models import (
        CostComponent,
        FundingBenefit,
        FundingOpportunity,
        FundingOpportunityProgram,
        Institution,
        Program,
    )
    from apps.research.register import record_organisation

    rows = [
        ("Example University", "Berlin", "MSc Chemistry", 12, Decimal("12000"), True),
        (
            "Rhein Technical University",
            "Munich",
            "MSc Materials Chemistry",
            12,
            Decimal("9000"),
            True,
        ),
        (
            "Lyon Institute of Science",
            "Lyon",
            "MSc Analytical Chemistry",
            12,
            Decimal("8000"),
            False,
        ),
    ]
    for inst_name, city, prog_name, months, tuition, funded in rows:
        country = "FR" if city == "Lyon" else "DE"
        institution = Institution.objects.create(
            canonical_key=f"institution:{uuid4()}",
            name=inst_name,
            country_code=country,
            official_website=f"https://{inst_name.lower().replace(' ', '-')}.example.org",
        )
        program = Program.objects.create(
            institution=institution,
            canonical_key=f"program:{uuid4()}",
            name=prog_name,
            campus_name="Main",
            city=city,
            country_code=country,
            location_key=f"{country}-{city.upper()}",
            degree_level="MASTER",
            teaching_languages=["English"],
            duration_months=months,
        )
        CostComponent.objects.create(
            program=program, kind="TUITION", amount=tuition, currency="EUR", period="ANNUAL"
        )
        if funded:
            opp = FundingOpportunity.objects.create(
                canonical_key=f"read:PROGRAM:{uuid4()}",
                name=f"{inst_name} Tuition Waiver",
                family="DEPARTMENT_OR_PROGRAM",
                scope_type="PROGRAM",
                program=program,
                kind="I2_PROGRAMME_ATTACHED",
                agreement="AGREED",
                served=True,
                money_form="FEE_WAIVER",
                route="AUTOMATIC_ON_ADMISSION",
            )
            FundingOpportunityProgram.objects.create(opportunity=opp, program=program)
            FundingBenefit.objects.create(
                opportunity=opp,
                kind="TUITION",
                amount=tuition,
                currency="EUR",
                period="ANNUAL",
                description="Tuition is waived in full.",
            )

    organisation = record_organisation(
        domain="example-foundation.org",
        name="Example Foundation",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )
    FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}",
        name="Foundation Stipend",
        family="PRIVATE_FOUNDATION",
        scope_type="HOLDER",
        holder="PRIVATE_FOUNDATION",
        holder_domain="example-foundation.org",
        holder_name="Example Foundation",
        organisation=organisation,
        agreement="AGREED",
        served=True,
        money_form="GRANT",
    )


def _consultation_and_research(student):
    """The student fills in the consultation through the real form; the research
    message the confirm step enqueues is handled in-process instead of via SQS."""
    import apps.accounts.views as account_views
    from apps.research.schemas import ResearchMessage
    from apps.research.services import handle_research_message
    from apps.research.worker import process_research_message
    from tests.acceptance.helpers import complete_consultation, confirm_consultation
    from tests.funding.conftest import EUR_RATES

    queue: list = []
    account_views.dispatch_recommendation_run = lambda *, tenant_id, run_id: queue.append(
        ResearchMessage(kind="run_research", tenant_id=tenant_id, run_id=run_id)
    )
    client = Client()
    client.force_login(student)
    complete_consultation(client, host=HOST)
    response = confirm_consultation(client, host=HOST)
    run_id = response.headers.get("X-Run-ID")
    for message in queue:
        process_research_message(
            message, lambda value: handle_research_message(value, rates=EUR_RATES)
        )
    return run_id


def _student_actions(student, counselor, agency) -> None:
    """A few real actions through the real routes, so boards are not empty."""
    from django_otp import DEVICE_ID_SESSION_KEY
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from apps.funding.models import PackCandidate
    from apps.tenancy.context import tenant_scope

    client = Client()
    client.force_login(student)
    with tenant_scope(agency.id):
        candidates = list(
            PackCandidate.objects.filter(pack_version__published_at__isnull=False).values_list(
                "candidate_id", flat=True
            )
        )
    for candidate_id in candidates[:2]:
        r = client.post(f"/student/applications/add/{candidate_id}/", HTTP_HOST=HOST)
        print("add application", candidate_id, r.status_code)
    r = client.post(
        "/student/messages/send/",
        {"body": "Hi! Should I take the IELTS before December?"},
        HTTP_HOST=HOST,
    )
    print("student message", r.status_code)

    staff = Client()
    staff.force_login(counselor)
    session = staff.session
    session[DEVICE_ID_SESSION_KEY] = TOTPDevice.objects.get(user=counselor).persistent_id
    session.save()
    with tenant_scope(agency.id):
        from apps.tenancy.models import Membership

        sid = Membership.objects.get(user=student).id
    r = staff.post(
        f"/counselor/students/{sid}/messages/send/",
        {"body": "Yes, aim for late November so results arrive before the January deadlines."},
        HTTP_HOST=HOST,
    )
    print("counselor message", r.status_code)


if __name__ == "__main__":
    main()
