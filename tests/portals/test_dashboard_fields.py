"""The fields the board reads, and every path a portal-less application reaches."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.concierge.models import RoadmapItem
from apps.portals import reminders, tags
from apps.portals.models import Application
from apps.portals.packets import PacketRefused, build_kit, mint_packet
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_run

pytestmark = pytest.mark.django_db


def _portal_less(agency, student, **fields):
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), **fields
    )


def test_an_unknown_outcome_is_refused_by_the_database(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        _portal_less(agency_a, membership_a, outcome="MAYBE")


def test_an_unknown_outcome_source_is_refused_by_the_database(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        _portal_less(agency_a, membership_a, outcome_source="RUMOUR")


def test_one_application_per_candidate(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    with tenant_scope(agency_a.id):
        _portal_less(agency_a, membership_a, candidate=candidate)
        with pytest.raises(IntegrityError), transaction.atomic():
            _portal_less(agency_a, membership_a, candidate=candidate)


def test_a_portal_less_kit_degrades_and_says_why(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        kit = build_kit(_portal_less(agency_a, membership_a))
    assert kit.not_fillable_reason == "no_portal"
    assert kit.portal_host == ""
    assert kit.form_url == ""


def test_a_portal_less_application_mints_no_packet(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _portal_less(agency_a, membership_a)
        with pytest.raises(PacketRefused) as refused:
            mint_packet(application)
    assert refused.value.reason == "no_portal"


def test_a_portal_less_application_has_no_portal_address(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        membership_a.application_email = "amina@example.test"
        membership_a.save(update_fields=["application_email"])
        application = _portal_less(agency_a, membership_a)
        assert tags.account_for(application) is None
        assert tags.portal_address(application) == ""


def test_a_reminder_for_a_portal_less_application_names_the_programme(
    agency_a, membership_a
) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    with tenant_scope(agency_a.id):
        application = _portal_less(agency_a, membership_a, candidate=candidate)
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.SUBMISSION,
            owner=membership_a,
            deadline=timezone.now() + timedelta(days=3),
        )
        note = reminders.notify_student(application, item, timedelta(days=3))
    assert note.message.startswith("MSc Chemistry:")


def test_the_extension_cannot_reach_a_portal_less_application(
    client, agency_a, domain_a, membership_a
) -> None:
    from tests.portals.test_ext_api import _pair

    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        application = _portal_less(agency_a, membership_a)
    response = client.get(
        f"/ext/applications/{application.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 404


def test_a_portal_less_application_vouches_for_no_host(agency_a, membership_a) -> None:
    """Its NULL host must not reach the mail allowlists as the string "None"."""
    from apps.mailbox import filter as mail_filter
    from apps.tenancy.db import tenant_transaction

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _portal_less(agency_a, membership_a)
        _urls, forms = mail_filter._vouching_rows(membership_a)
        hosts = mail_filter.link_hosts(membership_a)
    assert forms == []
    assert hosts == set()
