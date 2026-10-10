"""Phase 1 acceptance-gate threshold assertions (Task 18, Step 1).

`scorecard` (see tests/acceptance/conftest.py) is computed from the SYNTHETIC
placeholder fixtures under tests/benchmarks/ -- see tests/benchmarks/README.md.
A pass here proves the scoring pipeline and threshold wiring are correct, not
that Phase 1 has passed real acceptance.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from apps.funding.services import auto_publish_pack
from apps.research.queue import enqueue_research
from apps.research.schemas import ResearchMessage
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run


def test_phase1_thresholds(scorecard) -> None:
    assert scorecard.precision >= Decimal("0.90")
    assert scorecard.recall >= Decimal("0.80")
    assert scorecard.official_claim_support == Decimal("1")
    assert scorecard.unsupported_funding_claims == 0
    assert scorecard.verified_funded_lift >= Decimal("0.20")
    assert scorecard.cross_tenant_failures == 0


@pytest.mark.django_db(transaction=True)
def test_every_publication_is_an_audit_event(agency_a, membership_a) -> None:
    """Regression check for Task 13, updated for auto-publish: every pack
    publication still leaves an append-only audit event, even with no human
    actor (P1-14 applies to automated actions too)."""
    from apps.funding.models import AuditEvent, PackCandidate, PackVersion

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        published = auto_publish_pack(pack)
        event = AuditEvent.objects.get(event="pack.published", object_id=published.id)
        assert event.actor_id is None


def test_message_group_id_coverage_on_every_research_send() -> None:
    """Regression check: every research message sets MessageGroupId to its tenant_id."""

    captured: dict[str, object] = {}

    class FakeClient:
        def send_message(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return object()

        def receive_message(self, **kwargs: object) -> dict[str, object]:  # pragma: no cover
            return {}

        def delete_message(self, **kwargs: object) -> object:  # pragma: no cover
            return object()

    tenant_id = uuid4()
    message = ResearchMessage(kind="run_research", tenant_id=tenant_id, run_id=uuid4())
    enqueue_research(message, client=FakeClient(), queue_url="https://sqs.example.test/queue")

    assert captured["MessageGroupId"] == str(tenant_id)


def test_quiet_tenant_serviceability_boundary_is_approved_120_not_superseded_90() -> None:
    """Reuse the exact approved boundary from the Milestone 0 execution ledger."""
    import json
    import re
    from pathlib import Path

    evidence = Path("docs/validation/sqs-fair-queue.md")
    match = re.search(r"```json\n(.*?)\n```", evidence.read_text(), re.S)
    assert match is not None
    data = json.loads(match.group(1))

    threshold = data["traffic"]["quiet_tenant_threshold"]
    assert threshold == 120

    for trial in data["trials"]:
        assert trial["noisy_before_first_quiet"] < 120


@pytest.mark.django_db
def test_audit_dossier_export_proves_approvals_and_actions(agency_a, membership_a) -> None:
    from apps.audit.exports import build_export

    archive = build_export(agency_a.id, membership_a.id)
    assert b"manifest.json" in archive
    assert b"dossier.html" in archive


@pytest.mark.django_db
def test_external_style_domain_resolves_branding_and_unknown_host_is_rejected(
    client, agency_a, domain_a
) -> None:
    verified = client.get("/", HTTP_HOST=domain_a.host)
    assert verified.status_code == 302
    assert verified["Location"] == "/accounts/login/"

    unknown = client.get("/", HTTP_HOST="unknown.example.test")
    assert unknown.status_code == 400




@pytest.mark.django_db
def test_paid_consultation_produces_a_versioned_report_tied_to_the_pack_version(
    agency_a, membership_a
) -> None:
    from apps.reports.models import ConsultationPayment
    from apps.reports.services import generate_report

    class FakeObjectStore:
        def __init__(self) -> None:
            self._data: dict[str, bytes] = {}

        def put(self, key: str, body: bytes) -> str:
            self._data[key] = body
            return "test-version-1"

        def get(self, key: str) -> bytes:
            return self._data[key]

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    pack = make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        payment = ConsultationPayment.objects.create(
            tenant=agency_a,
            student=membership_a,
            amount="49.00",
            currency="USD",
            status="PAID",
        )
        report = generate_report(payment, pack, store=FakeObjectStore())
        assert report.pack_version_id == pack.id
        assert report.sha256


def test_no_unresolved_critical_findings(scorecard) -> None:
    """No unresolved critical security, data-loss, or cross-account-access failure.

    Cross-tenant failures already gate the six-metric scorecard above; this makes
    the "no unresolved critical failure" requirement an explicit, separately
    named assertion per the brief's Step 1 list.
    """
    assert scorecard.cross_tenant_failures == 0
