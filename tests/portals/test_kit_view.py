"""The kit page: the layer that works with no extension, on any device.

Asserts server behaviour only -- authorization and tenant isolation. There is
no presentation layer to assert on; see tests/templates/README.md.
"""

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _application(agency, student):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"view-{uuid4()}",
        form_url="https://apply.example.edu/personal",
    )
    FieldMap.objects.create(
        portal_form=form,
        version=1,
        entries=[
            {
                "profile_field": "identity.full_name",
                "action": {
                    "selector": "#name",
                    "description": "Full name",
                    "method": "fill",
                    "arguments": ["%value%"],
                },
            }
        ],
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_a_student_sees_their_own_kit(client, agency_a, domain_a, membership_a, user_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(user_a)

    response = client.get(
        f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 200
    assert response.context["kit"].application_id == application.id
    assert [q.label for q in response.context["kit"].questions] == ["Full name"]


def test_another_student_s_kit_is_404_not_403(
    client, agency_a, domain_a, membership_a, user_a, user_b
) -> None:
    """404, matching storage.download_document: a 403 would confirm the
    application exists."""
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        application = _application(agency_a, other)
    client.force_login(user_a)

    response = client.get(
        f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 404


def test_a_signed_in_user_with_no_student_membership_gets_403_not_404(
    client, agency_a, domain_a, membership_a, user_b
) -> None:
    """403, not 404, and that is correct here.

    user_b holds no membership in this tenant at all, so
    TenantMembershipMiddleware's blanket active-membership check refuses the
    request before application_kit -- and therefore current_membership --
    ever runs. Whichever layer produces it, the refusal is object-independent
    (it fires the same way for any application_id, real or invented), so it
    leaks nothing about whether this particular application exists -- the
    same shape apps/documents/api.py's _student_endpoint uses for "not a
    student here".
    """
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    client.force_login(user_b)

    response = client.get(
        f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 403


def test_an_anonymous_visitor_is_not_shown_a_kit(client, agency_a, domain_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

    response = client.get(
        f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host
    )

    assert response.status_code in (302, 403)


@pytest.mark.django_db(transaction=True)
def test_the_kit_reads_facts_behind_the_row_level_security_policy(
    client, agency_a, domain_a, membership_a, user_a, rls_enforced_orm
) -> None:
    """The kit page reads real facts under a real NOBYPASSRLS role, end to end.

    This goes through apps.tenancy.middleware.HostTenantContextMiddleware,
    which already wraps the whole request in a transaction and sets
    app.tenant_id before the view runs -- so a passing result here proves the
    page works under RLS enforcement, not that build_kit's own
    tenant_transaction is load-bearing (it isn't, on this path: the
    middleware's transaction already covers it). For that claim, see
    tests/portals/test_kit.py::test_build_kit_sets_its_own_guc_with_no_http_request,
    which calls build_kit directly with no middleware in the picture.
    """
    from apps.documents.models import VerifiedFact

    # rls_enforced_orm has already swapped the default connection by the time
    # this body runs (fixtures finish setup before the test body executes,
    # whatever order they are declared in), so -- unlike the other three tests
    # in this file, whose fixtures build under the ordinary superuser
    # connection -- this write needs app.tenant_id actually set, not just the
    # ContextVar tenant_scope holds. tenant_transaction sets both.
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        application = _application(agency_a, membership_a)
        VerifiedFact.objects.create(
            tenant=agency_a,
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Ada Byron"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="passport.pdf",
            confirmed_by=membership_a,
            confirmed_at=timezone.now(),
            created_by=membership_a,
        )
    client.force_login(user_a)

    response = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert [q.answer for q in response.context["kit"].questions] == ["Ada Byron"]


@pytest.mark.parametrize(
    "fields, offered",
    [
        ({}, True),
        ({"state": "BLOCKED_PORTAL_ERROR"}, True),
        ({"state": "SUBMITTED"}, False),
        ({"outcome": "REJECTED"}, False),
    ],
)
def test_the_kit_offers_start_only_where_start_is_accepted(
    client, agency_a, domain_a, membership_a, user_a, fields, offered
) -> None:
    """start_application refuses a decided or submitted card; the kit does not
    offer a button that can only fail (Task 19 minor)."""
    from apps.portals.models import Application

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        Application.objects.filter(id=application.id).update(**fields)
    client.force_login(user_a)

    response = client.get(f"/applications/{application.id}/kit", HTTP_HOST=domain_a.host)

    assert bool(response.context["start_url"]) is offered
