import json
from dataclasses import dataclass

from django.test import Client


def complete_consultation(client: Client, *, host: str):
    answers = (
        ("nationality", "AZ"),
        ("country_of_residence", "AZ"),
        ("date_of_birth", "2002-05-01"),
        ("target_field", "Chemistry"),
        ("allowed_countries", "DE,FR"),
        ("excluded_countries", "US"),
        ("intended_intake", "2027-09-01"),
        ("funding_dependency", "MANDATORY"),
        ("application_budget", {"amount": "150.00", "currency": "EUR"}),
        ("career_intent", "PHD"),
        ("acceptable_teaching_languages", "English"),
        ("language_evidence", []),
        (
            "academic_history",
            [
                {
                    "institution": "Baku State University",
                    "country_code": "AZ",
                    "qualification": "BSc",
                    "field": "Chemistry",
                    "grade": "90",
                    "grading_scale": "100",
                    "completed_on": "2026-06-30",
                }
            ],
        ),
        ("additional_notes", ""),
    )
    for key, value in answers:
        response = client.post(
            "/student/profile/",
            {"key": key, "value": json.dumps(value) if isinstance(value, (dict, list)) else value},
            HTTP_HOST=host,
        )
        assert response.status_code == 200
    return response


def confirm_consultation(client: Client, *, host: str):
    return client.post("/student/profile/", {"action": "confirm"}, HTTP_HOST=host)


@dataclass(frozen=True)
class Page:
    content: str

    def contains(self, text: str) -> bool:
        return text in self.content


class SliceDriver:
    def __init__(self, client: Client, host: str, student, queue) -> None:
        self.client = client
        self.host = host
        self.student = student
        self.queue = queue

    def student_submits_profile_and_starts_research(self):
        from apps.funding.models import RecommendationRun
        from apps.tenancy.context import tenant_scope

        self.seed_catalogue()
        self.client.force_login(self.student)
        complete_consultation(self.client, host=self.host)
        response = confirm_consultation(self.client, host=self.host)
        assert response.status_code == 302
        with tenant_scope(response.wsgi_request.tenant.id):
            return RecommendationRun.objects.get(id=response.headers["X-Run-ID"])

    def receive_message(self):
        return self.queue.pop(0)

    def seed_catalogue(self) -> None:
        """One real programme and one real served award for the run to find.

        Replaced a JSON fixture on 2026-09-23: `handle_research_message` used to
        fetch `official.example.test/program.json` and hard-code eligibility, so
        this driver proved the plumbing and never the engine. It now goes
        through the catalogue the reader writes.

        Matched to `complete_consultation` above: Chemistry, a DE country the
        profile does not exclude, English teaching, and twelve months for its
        NON_NEGOTIABLE one-year preference.
        """
        from uuid import uuid4

        from apps.funding.models import FundingOpportunity, Institution, Program
        from apps.research.register import record_organisation

        institution = Institution.objects.create(
            canonical_key=f"institution:{uuid4()}",
            name="Example University",
            country_code="DE",
            official_website="https://university.example.org",
        )
        Program.objects.create(
            institution=institution,
            canonical_key=f"program:{uuid4()}",
            name="MSc Chemistry",
            campus_name="Main",
            city="Berlin",
            country_code="DE",
            location_key="DE-BERLIN",
            degree_level="MASTER",
            teaching_languages=["English"],
            duration_months=12,
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

    def worker_processes(self, message) -> None:
        from apps.research.services import handle_research_message
        from apps.research.worker import process_research_message
        from tests.funding.conftest import EUR_RATES

        # Injected, because nothing loads a rate table on a deployed worker yet
        # -- `parse_ecb_daily` and `parse_cbar_daily` have no caller in apps/.
        process_research_message(
            message, lambda value: handle_research_message(value, rates=EUR_RATES)
        )

    def student_opens_dashboard(self) -> Page:
        self.client.force_login(self.student)
        response = self.client.get("/student/recommendation/", HTTP_HOST=self.host)
        assert response.status_code == 200
        return Page(response.content.decode())
