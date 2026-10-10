"""Add, remove, start, outcome: the student's write paths on the board (spec §7)."""

from uuid import uuid4

import pytest
from django.contrib.messages import get_messages
from django.utils import timezone

from apps.concierge.models import Notification
from apps.funding.models import AuditEvent, RecommendationCandidate
from apps.portals import applications as applications_module
from apps.portals.models import Application, ApplicationStep, DeviceAction, PortalForm
from apps.portals.pairing import issue_pairing_code, redeem_pairing_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def candidate(agency_a, membership_a):
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    make_published_pack(agency_a, run, (candidate,))
    return candidate


@pytest.fixture
def captured(monkeypatch):
    sent = []
    monkeypatch.setattr(
        applications_module, "enqueue_document_work", lambda message, **_kw: sent.append(message)
    )
    return sent


@pytest.fixture
def signed_in(client, user_a, membership_a):
    client.force_login(user_a)
    return client


def _messages(response) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def _application(agency, student, *, portal=True, **fields):
    form = (
        PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"k-{uuid4()}",
            form_url="https://apply.example.edu/start",
        )
        if portal
        else None
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form, **fields
    )


def _pair(agency, membership):
    with tenant_scope(agency.id):
        redeem_pairing_code(issue_pairing_code(membership), "install-1")


def test_adding_creates_a_card_without_a_portal_and_asks_the_counsellor(
    signed_in, agency_a, domain_a, membership_a, counselor_membership, candidate, captured,
    django_capture_on_commit_callbacks,
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    with django_capture_on_commit_callbacks(execute=True):
        response = signed_in.post(
            f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host
        )

    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        application = Application.objects.get(candidate=candidate)
        assert application.portal_form is None
        assert application.exception_item.owner_id == counselor_membership.id
        note = Notification.objects.get(application=application)
        assert note.message == "Find the application portal for MSc Chemistry."
        assert note.recipient_id == counselor_membership.id
        assert AuditEvent.objects.filter(
            event="application.added", actor=membership_a, object_id=application.id
        ).exists()
    assert [(m.action, m.application_id) for m in captured] == [
        ("capture_requirements", application.id)
    ]


def test_a_portal_recorded_for_the_programme_is_reused(
    signed_in, agency_a, domain_a, membership_a, candidate, captured, program_factory
) -> None:
    programme = program_factory()
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(program_id=programme.id)
        earlier = _application(agency_a, membership_a)
        Application.objects.filter(id=earlier.id).update(program_id=programme.id)

    signed_in.post(f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        assert Application.objects.get(candidate=candidate).portal_form_id == earlier.portal_form_id


def test_adding_twice_is_one_card(signed_in, agency_a, domain_a, candidate, captured) -> None:
    for _ in range(2):
        signed_in.post(f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        assert Application.objects.filter(candidate=candidate).count() == 1


def test_another_students_candidate_cannot_be_added(
    signed_in, agency_a, domain_a, user_b, captured
) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
    run = make_run(agency_a, other)
    theirs = make_db_candidate(agency_a, run)
    response = signed_in.post(f"/student/applications/add/{theirs.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_funding_that_comes_with_the_admission_is_not_a_card(
    signed_in, agency_a, domain_a, candidate, captured
) -> None:
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(
            funding_card={"route": "AUTOMATIC_ON_ADMISSION"}
        )
    response = signed_in.post(f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host)
    assert response["Location"] == "/student/recommendation/"
    assert "comes with the admission" in _messages(response)[0]
    with tenant_scope(agency_a.id):
        assert not Application.objects.filter(candidate=candidate).exists()


def test_start_is_refused_without_a_portal(signed_in, agency_a, domain_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal=False)
    response = signed_in.post(
        f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host
    )
    assert "application portal" in _messages(response)[0]
    with tenant_scope(agency_a.id):
        assert not DeviceAction.objects.filter(application=application).exists()


def test_start_is_refused_until_the_extension_is_paired(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    response = signed_in.post(
        f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host
    )
    assert "extension" in _messages(response)[0]


def test_start_queues_one_fill_and_moves_the_card(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    _pair(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

    signed_in.post(f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        action = DeviceAction.objects.get(application=application)
        assert application.started_at is not None
        assert action.kind == DeviceAction.Kind.START_FILL
        assert AuditEvent.objects.filter(event="application.start_requested").exists()


@pytest.mark.parametrize(
    "fields",
    [
        {"outcome": "WITHDRAWN"},
        {"outcome": "REJECTED"},
        {"outcome": "ADMITTED"},
        {"state": "SUBMITTED"},
        {"state": "CONFIRMED"},
    ],
)
def test_start_is_refused_for_a_finished_card(
    signed_in, agency_a, domain_a, membership_a, fields
) -> None:
    _pair(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, **fields)
    response = signed_in.post(
        f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host
    )
    assert "not in your list" in _messages(response)[0]
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        assert application.started_at is None
        assert not DeviceAction.objects.filter(application=application).exists()


def test_start_is_rate_limited(signed_in, agency_a, domain_a, membership_a, monkeypatch) -> None:
    from django.core.cache import cache

    cache.clear()
    monkeypatch.setattr(applications_module, "DEVICE_ACTION_LIMIT", 1)
    _pair(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    signed_in.post(f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host)
    response = signed_in.post(
        f"/student/applications/{application.id}/start/", HTTP_HOST=domain_a.host
    )
    assert "Too many requests" in _messages(response)[-1]
    with tenant_scope(agency_a.id):
        assert DeviceAction.objects.filter(application=application).count() == 1


def test_a_person_corrects_the_outcome(signed_in, agency_a, domain_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a, membership_a, outcome="ADMITTED", outcome_source="MAIL"
        )
    signed_in.post(
        f"/student/applications/{application.id}/outcome/",
        {"outcome": "WAITLISTED"},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
    assert (application.outcome, application.outcome_source) == ("WAITLISTED", "PERSON")


def test_an_unknown_outcome_changes_nothing(signed_in, agency_a, domain_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    response = signed_in.post(
        f"/student/applications/{application.id}/outcome/", {"outcome": "MAYBE"},
        HTTP_HOST=domain_a.host,
    )
    assert "Choose an outcome" in _messages(response)[0]
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
    assert application.outcome == ""


def test_removing_an_untouched_card_deletes_it_and_a_started_one_is_withdrawn(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        untouched = _application(agency_a, membership_a)
        started = _application(agency_a, membership_a)
        ApplicationStep.objects.create(
            tenant=agency_a, application=started, sequence=1, kind="PACKET", detail={}
        )
    for application in (untouched, started):
        signed_in.post(
            f"/student/applications/{application.id}/remove/", HTTP_HOST=domain_a.host
        )
    with tenant_scope(agency_a.id):
        assert not Application.objects.filter(id=untouched.id).exists()
        started.refresh_from_db()
    assert (started.outcome, started.outcome_source) == ("WITHDRAWN", "PERSON")


@pytest.mark.parametrize("action", ["start", "outcome", "remove"])
def test_another_students_application_is_404_on_every_action(
    signed_in, agency_a, domain_a, user_b, action
) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        theirs = _application(agency_a, other)
    response = signed_in.post(
        f"/student/applications/{theirs.id}/{action}/", {"outcome": "ADMITTED"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 404


def test_record_portal_reuses_a_shared_row_and_refuses_http(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal=False)
        with pytest.raises(applications_module.ApplicationRefused):
            applications_module.record_portal(
                application, "http://apply.tum.de/start", actor=membership_a
            )
        form = applications_module.record_portal(
            application, "https://campus.tum.de/apply", actor=membership_a
        )
        again = applications_module.record_portal(
            _application(agency_a, membership_a, portal=False),
            "https://campus.tum.de/apply",
            actor=membership_a,
        )
    assert (form.portal_host, form.form_key) == ("campus.tum.de", "/apply")
    assert again.id == form.id


def _offer(
    agency, student, original, *, sender: str, outcome: str = "REJECTED",
    authenticated: bool = True, measured: bool = False, trusted: bool = True,
):
    from apps.mailbox.models import MailboxConnection, MailSignal

    connection, _ = MailboxConnection.objects.get_or_create(
        tenant=agency, membership=student, provider="MICROSOFT",
        defaults={"address": "amina@outlook.test"},
    )
    return MailSignal.objects.create(
        tenant=agency, connection=connection, provider_message_id=f"m-{uuid4()}",
        sender_domain=sender, received_at=timezone.now(), application=original,
        label="DECISION", outcome=outcome,
        offered_programme="MSc Statistics", trusted=trusted,
        sender_authenticated=authenticated,
        decision_reading={"measured": measured},
    )


def test_accepting_an_offer_makes_a_card_on_the_same_portal_and_records_a_measured_refusal(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="example.edu", measured=True)

    response = signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)

    assert response["Location"] == "/student/"
    with tenant_scope(agency_a.id):
        offered = Application.objects.get(student=membership_a, program_id=signal.id)
        original.refresh_from_db()
        signal.refresh_from_db()
        assert offered.title == "MSc Statistics"
        assert offered.portal_form_id == original.portal_form_id
        # The letter's statement, not the student's: MAIL, with the signal as evidence.
        assert (original.outcome, original.outcome_source) == ("REJECTED", "MAIL")
        assert original.outcome_evidence_id == signal.id
        assert AuditEvent.objects.filter(
            event="application.outcome_recorded", actor=membership_a, object_id=original.id
        ).exists()
        assert signal.offer_handled_at is not None
        assert AuditEvent.objects.filter(
            event="application.offer_accepted", actor=membership_a, object_id=offered.id
        ).exists()


def test_an_offer_from_another_institution_starts_without_a_portal(
    signed_in, agency_a, domain_a, membership_a, counselor_membership
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="lu.se", outcome="")

    signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        offered = Application.objects.get(student=membership_a, program_id=signal.id)
        original.refresh_from_db()
        assert offered.portal_form is None
        assert offered.exception_item.owner_id == counselor_membership.id
        # The letter said nothing about the programme applied for: nothing is recorded.
        assert original.outcome == ""


def test_ignoring_an_offer_dismisses_it_and_makes_no_card(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="example.edu")
    signed_in.post(f"/student/offers/{signal.id}/ignore/", HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        signal.refresh_from_db()
        original.refresh_from_db()
        assert signal.offer_handled_at is not None
        assert not Application.objects.filter(program_id=signal.id).exists()
        assert original.outcome == ""
    again = signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)
    assert again.status_code == 404


@pytest.mark.parametrize("action", ["accept", "ignore"])
def test_another_students_offer_is_404(signed_in, agency_a, domain_a, user_b, action) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        signal = _offer(agency_a, other, _application(agency_a, other), sender="example.edu")
    response = signed_in.post(f"/student/offers/{signal.id}/{action}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_a_stopped_student_cannot_add(
    signed_in, agency_a, domain_a, membership_a, candidate, captured
) -> None:
    """The tenancy middleware's lock covers these routes: processing stopped is read-only."""
    from datetime import UTC, datetime

    from apps.privacy import requests

    with tenant_scope(agency_a.id):
        requests.record(
            membership_a, kind="withdrawal", channel="email",
            received_at=datetime(2026, 10, 2, tzinfo=UTC),
        )
    response = signed_in.post(f"/student/applications/add/{candidate.id}/", HTTP_HOST=domain_a.host)
    assert response["Location"] == "/privacy/stopped/"
    with tenant_scope(agency_a.id):
        assert not Application.objects.filter(candidate=candidate).exists()


def test_an_unauthenticated_offer_makes_the_card_and_records_no_refusal(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    """Review ruling 1: a forged "not X, but Y" mail plus one press must not write
    a refusal. The student's chosen card is harmless; the original stays as it was."""
    with tenant_scope(agency_a.id):
        original = _application(agency_a, membership_a)
        signal = _offer(
            agency_a, membership_a, original, sender="example.edu", authenticated=False,
            measured=True,
        )

    signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        assert Application.objects.filter(student=membership_a, program_id=signal.id).exists()
        original.refresh_from_db()
    assert (original.outcome, original.outcome_source) == ("", "")


def test_an_unmeasured_offer_makes_the_card_and_records_no_refusal(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    """Final review I1: authenticated, but the refusal is Jev's reading at bars
    nobody measured. Accept is a press about the other programme, not a
    confirmation of the refusal, so the original card is untouched and the board
    keeps asking ("the email reads: Not admitted. Confirm it below")."""
    with tenant_scope(agency_a.id):
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="example.edu")

    signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        assert Application.objects.filter(student=membership_a, program_id=signal.id).exists()
        original.refresh_from_db()
        assert not AuditEvent.objects.filter(
            event="application.outcome_recorded", object_id=original.id
        ).exists()
    assert (original.outcome, original.outcome_source) == ("", "")


def test_an_offer_never_overwrites_a_person_recorded_outcome(
    signed_in, agency_a, domain_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        original = _application(
            agency_a, membership_a, outcome="WAITLISTED", outcome_source="PERSON"
        )
        signal = _offer(agency_a, membership_a, original, sender="example.edu", measured=True)

    signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        original.refresh_from_db()
    assert (original.outcome, original.outcome_source) == ("WAITLISTED", "PERSON")


def test_an_untrusted_offer_cannot_be_acted_on(signed_in, agency_a, domain_a, membership_a) -> None:
    """Security review L5: the board shows trusted offers only, and a forged
    POST must not act on one it would never show."""
    with tenant_scope(agency_a.id):
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="example.edu", trusted=False)
        assert applications_module.offer_for(membership_a, signal.id) is None

    response = signed_in.post(f"/student/offers/{signal.id}/accept/", HTTP_HOST=domain_a.host)

    assert response.status_code == 404
    with tenant_scope(agency_a.id):
        assert not Application.objects.filter(program_id=signal.id).exists()


def test_a_second_accept_of_the_same_offer_is_refused(agency_a, membership_a) -> None:
    """Review minor 4: a double click is two requests that both passed offer_for."""
    with tenant_scope(agency_a.id):
        original = _application(agency_a, membership_a)
        signal = _offer(agency_a, membership_a, original, sender="example.edu")
        first = applications_module.offer_for(membership_a, signal.id)
        second = applications_module.offer_for(membership_a, signal.id)
        applications_module.accept_offer(first, actor=membership_a)
        with pytest.raises(applications_module.ApplicationRefused) as refused:
            applications_module.accept_offer(second, actor=membership_a)
        assert refused.value.reason == "not_found"
        with pytest.raises(applications_module.ApplicationRefused):
            applications_module.ignore_offer(second, actor=membership_a)
        assert Application.objects.filter(program_id=signal.id).count() == 1


def test_a_concurrent_add_returns_the_card_the_other_request_made(
    agency_a, membership_a, candidate, captured, monkeypatch
) -> None:
    """Review minor 3: both requests miss the existence check; the second insert
    hits portal_app_one_per_candidate and must re-read, not 500."""
    with tenant_scope(agency_a.id):
        made = applications_module.add_application(
            student=membership_a, candidate_id=candidate.id, actor=membership_a
        )
        monkeypatch.setattr(applications_module, "_existing_card", lambda *_a: None)
        again = applications_module.add_application(
            student=membership_a, candidate_id=candidate.id, actor=membership_a
        )
        assert again.id == made.id
        assert Application.objects.filter(candidate=candidate).count() == 1


def _record(agency, student, url):
    return applications_module.record_portal(
        _application(agency, student, portal=False), url, actor=student
    )


def test_record_portal_keys_on_query_and_fragment(agency_a, membership_a) -> None:
    """Review ruling 2: ?programme=123 portals and SPA hash routes are distinct forms."""
    with tenant_scope(agency_a.id):
        one = _record(agency_a, membership_a, "https://apply.uni.de/start?programme=1")
        two = _record(agency_a, membership_a, "https://apply.uni.de/start?programme=2")
        hash_a = _record(agency_a, membership_a, "https://apply.uni.de/app#/msc")
        hash_b = _record(agency_a, membership_a, "https://apply.uni.de/app#/phd")
        port = _record(agency_a, membership_a, "https://apply.uni.de:8443/start?programme=1")
    assert one.id != two.id and hash_a.id != hash_b.id
    assert (one.form_key, hash_a.form_key) == ("/start?programme=1", "/app#/msc")
    assert port.form_key == ":8443/start?programme=1"


def test_a_long_portal_url_is_keyed_by_its_hash(agency_a, membership_a) -> None:
    import hashlib

    tail = "/apply/" + "a" * 300
    with tenant_scope(agency_a.id):
        form = _record(agency_a, membership_a, f"https://apply.uni.de{tail}")
    assert form.form_key == hashlib.sha256(tail.encode()).hexdigest()


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/x", "https://10.0.0.1/x", "https://intranet/x", "https://[::1]/x",
        # RFC 8375: on the public suffix list, so registrable_domain accepts it.
        "https://router.home.arpa/x",
    ],
)
def test_record_portal_refuses_a_non_public_host(agency_a, membership_a, url) -> None:
    with tenant_scope(agency_a.id):
        with pytest.raises(applications_module.ApplicationRefused) as refused:
            _record(agency_a, membership_a, url)
    assert refused.value.reason == "bad_url"


def test_an_add_and_remove_loop_hits_the_pack_command_limit(
    agency_a, membership_a, candidate, captured
) -> None:
    """Final review M4: each add of a portal-less programme asks the counsellor
    (a RoadmapItem and a Notification). Add and remove share the pack
    commands' per-student bucket (20 a minute)."""
    from django.core.cache import cache

    cache.clear()
    with tenant_scope(agency_a.id):
        for _ in range(10):
            card = applications_module.add_application(
                student=membership_a, candidate_id=candidate.id, actor=membership_a
            )
            applications_module.remove_application(card, actor=membership_a)
        with pytest.raises(applications_module.ApplicationRefused) as refused:
            applications_module.add_application(
                student=membership_a, candidate_id=candidate.id, actor=membership_a
            )
        assert refused.value.reason == "rate_limited"
        assert not Application.objects.filter(candidate=candidate).exists()
        card = _application(agency_a, membership_a)
        with pytest.raises(applications_module.ApplicationRefused):
            applications_module.remove_application(card, actor=membership_a)
        assert Application.objects.filter(id=card.id).exists()
    cache.clear()


def test_recording_portals_hits_the_pack_command_limit(agency_a, membership_a) -> None:
    """Security review L3: every distinct URL is a new platform-shared
    PortalForm row, so recording one shares add/remove's per-student bucket."""
    from django.core.cache import cache

    from apps.ratelimit import PACK_COMMAND_LIMIT

    cache.clear()
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal=False)
        for n in range(PACK_COMMAND_LIMIT):
            applications_module.record_portal(
                application, f"https://campus.tum.de/apply/{n}", actor=membership_a
            )
        with pytest.raises(applications_module.ApplicationRefused) as refused:
            applications_module.record_portal(
                application, "https://campus.tum.de/apply/one-more", actor=membership_a
            )
    assert refused.value.reason == "rate_limited"
    assert not PortalForm.objects.filter(form_key="/apply/one-more").exists()
    cache.clear()
