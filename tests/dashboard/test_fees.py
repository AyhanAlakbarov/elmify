from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.dashboard.board import board_for
from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.portals.applications import add_application
from apps.portals.fees import fee_state_for, mark_fee_paid
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import reads_no_catalogue

from .conftest import add_card

pytestmark = pytest.mark.django_db
NOW = timezone.now()


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.parametrize(
    ("fee", "state"),
    [(None, "UNKNOWN"), (Decimal("0.00"), "NONE"), (Decimal("75.00"), "OPEN")],
)
def test_the_fee_state_comes_from_the_candidates_copy(fee, state) -> None:
    assert fee_state_for(RecommendationCandidate(application_fee=fee)) == state


def test_a_card_with_no_candidate_does_not_know_its_fee() -> None:
    assert fee_state_for(None) == "UNKNOWN"


def test_adding_a_programme_and_a_scholarship_sets_their_fee_states(
    agency_a, membership_a, pack
) -> None:
    programme, award = pack
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        award_card = add_application(
            student=membership_a, candidate_id=award.id, actor=membership_a
        )
    assert card.fee_state == "OPEN"
    assert award_card.fee_state == "UNKNOWN"  # an award candidate copies no fee


def test_the_student_marks_a_fee_paid(client, agency_a, domain_a, user_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)

    response = client.post(f"/student/applications/{card.id}/fee-paid/", HTTP_HOST=domain_a.host)

    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
        assert (card.fee_state, card.fee_paid_source) == ("PAID", "STUDENT")
        assert card.fee_paid_at is not None
        assert AuditEvent.objects.filter(
            actor=membership_a, event="application.fee_paid", object_id=card.id
        ).count() == 1


def test_two_tabs_racing_mark_the_fee_once(agency_a, membership_a, pack) -> None:
    """Review Focus 5. Both tabs loaded the card while it was OPEN; the
    conditional UPDATE lets exactly one of them through."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
        first = Application.objects.get(id=card.id)
        second = Application.objects.get(id=card.id)

        assert mark_fee_paid(first, source="STUDENT", at=NOW, actor=membership_a) is True
        assert mark_fee_paid(second, source="STUDENT", at=NOW, actor=membership_a) is False
        assert AuditEvent.objects.filter(event="application.fee_paid").count() == 1


def test_a_second_press_is_told_it_is_already_marked(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    url = f"/student/applications/{card.id}/fee-paid/"
    client.post(url, HTTP_HOST=domain_a.host)

    body = client.post(url, HTTP_HOST=domain_a.host, follow=True).content.decode()

    assert "already marked as paid" in body
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(event="application.fee_paid").count() == 1


def test_another_students_card_is_a_404(
    client, agency_a, domain_a, user_a, user_b, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        card = add_card(agency_a, other, programme)
    client.force_login(user_a)
    response = client.post(f"/student/applications/{card.id}/fee-paid/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_the_counsellor_never_gets_the_paid_button(agency_a, membership_a, pack) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        student_card = board_for(membership_a).cards[0]
        counselor_card = board_for(membership_a, counselor_view=True).cards[0]
    assert student_card.fee_paid_url.endswith("/fee-paid/")
    assert counselor_card.fee_paid_url == ""


def test_a_scholarship_card_shows_no_fee_line_and_no_paid_button(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    """An award copies no fee, so its card is UNKNOWN; "Fee not known yet" and
    "I've paid this fee" on every scholarship would be noise (programmes only)."""
    _programme, award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, award, portal=False)
        [card] = board_for(membership_a).cards
    assert (card.fee_state, card.fee_paid_url) == ("UNKNOWN", "")
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "DAAD Study Scholarship" in body  # the card rendered
    assert "Fee not known yet" not in body


def test_the_card_shows_the_fee_then_that_it_is_paid(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(
            agency_a, membership_a, programme, deadline=NOW + timedelta(days=5),
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "I've paid this fee" in body
    assert "Application fee for M.Sc. Informatics" in body  # the Needs item

    with tenant_scope(agency_a.id):
        Application.objects.filter(id=card.id).update(fee_state="PAID", fee_paid_source="STUDENT")
    with reads_no_catalogue():
        body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Application fee paid" in body
    assert "Application fee for M.Sc. Informatics" not in body
    assert "paid this fee" not in body


def test_an_unknown_fee_says_so_and_never_shows_zero(
    client, agency_a, domain_a, user_a, membership_a, pack
):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(
            application_fee=None, application_fee_currency=""
        )
        programme.refresh_from_db()
        add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    body = client.get("/student/", HTTP_HOST=domain_a.host).content.decode()
    assert "Fee not known yet" in body
    assert "Application fee:" not in body


def test_a_failed_audit_row_leaves_the_fee_unpaid(
    agency_a, membership_a, pack, monkeypatch
) -> None:
    """A fee is never PAID without its audit row."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme)
        Application.objects.filter(id=card.id).update(fee_state="OPEN")
        application = Application.objects.get(id=card.id)

        def boom(*args, **kwargs):
            raise RuntimeError("audit down")

        monkeypatch.setattr(AuditEvent.objects, "create", boom)
        with pytest.raises(RuntimeError):
            mark_fee_paid(application, source="STUDENT", at=NOW, actor=membership_a)

        assert Application.objects.get(id=card.id).fee_state == "OPEN"
