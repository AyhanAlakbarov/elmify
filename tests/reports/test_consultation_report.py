import pytest
from django.db import connection

from apps.reports.models import ConsultationPayment
from apps.reports.services import ReportBlocked, generate_report
from apps.tenancy.context import tenant_scope


@pytest.mark.django_db
def test_report_requires_payment_and_a_published_pack(agency_a, membership_a, fake_store):
    from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    pack = make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        payment = ConsultationPayment.objects.create(
            tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PAID"
        )
        report = generate_report(payment, pack, store=fake_store)
        assert report.pack_version_id == pack.id
        assert report.sha256


@pytest.mark.django_db
def test_report_blocked_without_paid_status(agency_a, membership_a, make_run, fake_store):
    from apps.funding.models import PackVersion

    run = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        payment = ConsultationPayment.objects.create(
            tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PENDING"
        )
        with pytest.raises(ReportBlocked):
            generate_report(payment, pack, store=fake_store)


@pytest.mark.django_db
def test_report_blocked_when_payment_student_does_not_match_pack_student(
    agency_a, membership_a, make_run, fake_store
):
    """A paid payment for one student must not mint a report for a different
    student's pack, even within the same tenant."""
    from django.contrib.auth import get_user_model

    from apps.tenancy.models import Membership
    from tests.funding.conftest import make_db_candidate, make_published_pack

    other_user = get_user_model().objects.create_user(username="other-student-a")
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    pack = make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        other_membership = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT
        )
        mismatched_payment = ConsultationPayment.objects.create(
            tenant=agency_a,
            student=other_membership,
            amount="49.00",
            currency="USD",
            status="PAID",
        )
        with pytest.raises(ReportBlocked):
            generate_report(mismatched_payment, pack, store=fake_store)


@pytest.mark.django_db
def test_report_blocked_when_pack_not_yet_published(agency_a, membership_a, make_run, fake_store):
    from apps.funding.models import PackVersion

    run = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        payment = ConsultationPayment.objects.create(
            tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PAID"
        )
        with pytest.raises(ReportBlocked, match="published"):
            generate_report(payment, pack, store=fake_store)


@pytest.mark.frontend
@pytest.mark.django_db
def test_report_content_has_required_sections_and_no_internal_reasoning(
    agency_a, membership_a, make_run, fake_store
):
    from tests.funding.conftest import make_db_candidate, make_published_pack

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Robotics")
    pack = make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        payment = ConsultationPayment.objects.create(
            tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PAID"
        )
        report = generate_report(payment, pack, store=fake_store)

        body = fake_store.get(report.object_key).decode()
        assert "MSc Robotics" in body
        # P1-7.1, amendment 2026-08-28: official source URLs stay out of the
        # student-facing report; its last-checked dates stay in. The dashboard
        # amendment of 2026-10-04 lifts this for the pages, not the report.
        assert candidate.evidence.source_url not in body
        assert "last checked" in body
        assert agency_a.name in body
        assert "internal" not in body.lower()
        assert "chain-of-thought" not in body.lower()


@pytest.mark.frontend
@pytest.mark.django_db
def test_report_suppresses_placeholder_funding_gap(
    agency_a, membership_a, make_run, fake_store
):
    from tests.funding.conftest import make_db_candidate, make_published_pack

    run = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        candidate = make_db_candidate(
            agency_a, run, program_name="MSc Uncosted", funding_gap="0.00"
        )
        candidate.funding_gap_is_placeholder = True
        candidate.save(update_fields=["funding_gap_is_placeholder"])
    pack = make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        payment = ConsultationPayment.objects.create(
            tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PAID"
        )
        report = generate_report(payment, pack, store=fake_store)

        body = fake_store.get(report.object_key).decode()
        assert "not yet costed" in body
        assert "0.00" not in body


@pytest.mark.django_db
def test_download_view_serves_report_to_the_student(
    client, domain_a, user_a, membership_a, make_run, fake_store, monkeypatch
):
    from tests.funding.conftest import make_db_candidate, make_published_pack

    run = make_run(domain_a.agency, membership_a)
    candidate = make_db_candidate(domain_a.agency, run)
    pack = make_published_pack(domain_a.agency, run, (candidate,))
    with tenant_scope(domain_a.agency_id):
        payment = ConsultationPayment.objects.create(
            tenant=domain_a.agency,
            student=membership_a,
            amount="49.00",
            currency="USD",
            status="PAID",
        )
        report = generate_report(payment, pack, store=fake_store)

    monkeypatch.setattr("apps.reports.views.S3ObjectStore", lambda: fake_store)
    client.force_login(user_a)
    response = client.get(f"/reports/{report.id}/download/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert response["Content-Disposition"] == f'attachment; filename="report-{report.id}.html"'
    assert response.content == fake_store.get(report.object_key)


@pytest.mark.django_db
def test_download_view_denies_cross_tenant_access(
    client,
    domain_a,
    domain_b,
    user_a,
    user_b,
    membership_a,
    membership_b,
    make_run,
    fake_store,
    monkeypatch,
):
    from tests.funding.conftest import make_db_candidate, make_published_pack

    run = make_run(domain_a.agency, membership_a)
    candidate = make_db_candidate(domain_a.agency, run)
    pack = make_published_pack(domain_a.agency, run, (candidate,))
    with tenant_scope(domain_a.agency_id):
        payment = ConsultationPayment.objects.create(
            tenant=domain_a.agency,
            student=membership_a,
            amount="49.00",
            currency="USD",
            status="PAID",
        )
        report = generate_report(payment, pack, store=fake_store)

    monkeypatch.setattr("apps.reports.views.S3ObjectStore", lambda: fake_store)
    client.force_login(user_b)
    response = client.get(f"/reports/{report.id}/download/", HTTP_HOST=domain_b.host)

    assert response.status_code == 404


@pytest.mark.django_db
def test_new_tables_enforce_row_level_security() -> None:
    with connection.cursor() as cursor:
        for table in ("reports_consultationpayment", "reports_consultationreport"):
            cursor.execute(
                """
                SELECT relrowsecurity, relforcerowsecurity
                  FROM pg_class
                 WHERE oid = %s::regclass
                """,
                [f"public.{table}"],
            )
            assert cursor.fetchone() == (True, True)
            cursor.execute(
                """
                SELECT cmd, qual, with_check
                  FROM pg_policies
                 WHERE schemaname = 'public' AND tablename = %s AND policyname = 'tenant_isolation'
                """,
                [table],
            )
            row = cursor.fetchone()
            assert row is not None
            cmd, qual, with_check = row
            assert cmd == "ALL"
            assert "current_setting" in qual
            assert "current_setting" in with_check
