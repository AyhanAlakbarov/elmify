"""What a classified and Jev-read mail does to the board (spec §4, §6, §8)."""

from datetime import UTC, date, datetime, timedelta
from datetime import timezone as fixed_offset
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from pydantic import ValidationError

from apps.mailbox.actions import _interview_time, apply_verdict
from apps.mailbox.classify import MailVerdict
from apps.mailbox.decision_reader import UNAVAILABLE, DecisionReading
from apps.portals.outcome import correct_outcome
from apps.tenancy.db import tenant_transaction

LINKS = frozenset({"tum.de"})


def _reading(**fields) -> DecisionReading:
    base = dict(is_decision=True, outcome="", funding_outcome="", other_programme_offered=False,
                p={}, measured=True, unavailable=False)
    return DecisionReading(**{**base, **fields})


def _apply(signal, *, trusted=True, provider_authenticated=None, reading=None, **verdict):
    """`trusted` is the trust gate; the provider's verdict defaults to it."""
    with tenant_transaction(signal.tenant_id):
        signal.sender_authenticated = (
            trusted if provider_authenticated is None else provider_authenticated
        )
        signal.save(update_fields=["sender_authenticated"])
        apply_verdict(
            signal, MailVerdict(**verdict), reading=reading, link_hosts=LINKS,
            authenticated=trusted,
        )
    signal.refresh_from_db()
    signal.application.refresh_from_db()
    return signal.application


@pytest.mark.django_db
def test_a_cleared_decision_without_an_outcome_marks_it_available(signal_on_application) -> None:
    application = _apply(signal_on_application("tum.de"), label="DECISION", reading=_reading())
    assert application.decision_available_at is not None
    assert application.outcome == ""


@pytest.mark.django_db
def test_a_cleared_outcome_is_recorded_from_trusted_mail(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(signal, label="DECISION", reading=_reading(outcome="ADMITTED"))
    assert (application.outcome, application.outcome_source) == ("ADMITTED", "MAIL")
    assert application.outcome_evidence_id == signal.id
    assert signal.decision_reading["is_decision"] is True


@pytest.mark.django_db
def test_before_the_bars_are_learned_the_outcome_waits_for_a_person(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(
        signal, label="DECISION", reading=_reading(outcome="ADMITTED", measured=False)
    )
    assert application.decision_available_at is not None
    assert application.outcome == ""
    assert signal.outcome == "ADMITTED"  # what the card asks the person to confirm


@pytest.mark.django_db
def test_an_untrusted_decision_moves_no_card(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(
        signal, trusted=False, label="DECISION", reading=_reading(outcome="ADMITTED")
    )
    assert application.decision_available_at is None
    assert application.outcome == ""
    assert signal.outcome == "ADMITTED"  # the reading, a suggestion only


@pytest.mark.django_db
def test_an_abstaining_reading_moves_nothing(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(signal, label="DECISION", reading=_reading(is_decision=None))
    assert application.decision_available_at is None
    unavailable = signal_on_application("tum.de")
    application = _apply(unavailable, label="DECISION", reading=UNAVAILABLE)
    assert unavailable.decision_reading["unavailable"] is True
    assert application.decision_available_at is None
    assert application.outcome == ""


@pytest.mark.django_db
def test_a_person_recorded_outcome_survives_a_later_trusted_mail(
    signal_on_application, membership_a
) -> None:
    signal = signal_on_application("tum.de")
    with tenant_transaction(signal.tenant_id):
        correct_outcome(signal.application, "WAITLISTED", actor=membership_a)
    application = _apply(signal, label="DECISION", reading=_reading(outcome="REJECTED"))
    assert (application.outcome, application.outcome_source) == ("WAITLISTED", "PERSON")


@pytest.mark.django_db
def test_a_person_can_take_back_a_false_decision_available(
    signal_on_application, membership_a
) -> None:
    from apps.funding.models import AuditEvent

    signal = signal_on_application("tum.de")
    application = _apply(signal, label="DECISION", reading=_reading())
    with tenant_transaction(signal.tenant_id):
        correct_outcome(application, "", actor=membership_a)
        audited = AuditEvent.objects.filter(
            event="application.outcome_recorded", object_id=application.id
        ).count()
    application.refresh_from_db()
    assert (application.decision_available_at, application.outcome_source) == (None, "PERSON")
    assert audited == 1
    with tenant_transaction(signal.tenant_id), pytest.raises(ValueError):
        correct_outcome(application, "MAYBE", actor=membership_a)


@pytest.mark.django_db
def test_the_funding_half_of_a_letter_stays_on_the_signal(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    application = _apply(
        signal, label="DECISION", reading=_reading(outcome="ADMITTED", funding_outcome="REJECTED")
    )
    assert application.outcome == "ADMITTED"
    assert signal.funding_outcome == "REJECTED"


@pytest.mark.django_db
def test_an_offer_needs_jev_and_a_name_found_in_the_email(signal_on_application) -> None:
    signal = signal_on_application("lu.se")
    application = _apply(
        signal, label="DECISION", offered_programme="MSc Statistics",
        reading=_reading(outcome="REJECTED", other_programme_offered=True),
    )
    assert signal.offered_programme == "MSc Statistics"
    assert signal.offer_handled_at is None
    assert application.outcome == "REJECTED"
    no_offer = signal_on_application("lu.se")
    _apply(no_offer, label="DECISION", offered_programme="MSc Statistics",
           reading=_reading(other_programme_offered=None))
    assert no_offer.offered_programme == ""


@pytest.mark.django_db
def test_conditions_are_kept_only_for_a_conditional_admission(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    _apply(signal, label="DECISION", outcome_conditions=("final transcript",),
           reading=_reading(outcome="ADMITTED_CONDITIONAL"))
    assert signal.outcome_conditions == ["final transcript"]
    plain = signal_on_application("tum.de")
    _apply(plain, label="DECISION", outcome_conditions=("final transcript",),
           reading=_reading(outcome="ADMITTED"))
    assert plain.outcome_conditions == []


@pytest.mark.django_db
def test_a_document_request_keeps_the_name_and_the_due_date(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    _apply(signal, label="DOCUMENT_REQUEST",
           document_name="Certified copy of your degree certificate", document_due="2027-06-15")
    assert signal.document_name == "Certified copy of your degree certificate"
    assert signal.document_due == date(2027, 6, 15)


@pytest.mark.django_db
def test_an_unreadable_due_date_is_dropped_not_guessed(signal_on_application) -> None:
    signal = signal_on_application("tum.de")
    _apply(signal, label="DOCUMENT_REQUEST", document_name="Transcript", document_due="15/06/2027")
    assert signal.document_due is None


def _ahead(days: int = 30) -> datetime:
    """An interview time a month out, stated at +01:00 (ruling F7: never a literal year)."""
    plus_one = fixed_offset(timedelta(hours=1))
    return (timezone.now() + timedelta(days=days)).astimezone(plus_one).replace(
        hour=10, minute=0, second=0, microsecond=0
    )


@pytest.mark.django_db
def test_an_interview_keeps_its_time_and_its_item_carries_it(signal_on_application) -> None:
    from apps.concierge.models import Notification

    when = _ahead()
    signal = signal_on_application("ethz.ch")
    _apply(signal, label="INTERVIEW", interview_at=when.isoformat(timespec="minutes"))
    assert signal.interview_at == when
    note = Notification.objects.get(roadmap_item__student=signal.application.student)
    assert note.roadmap_item.deadline == signal.interview_at
    assert f"{when.astimezone(UTC):%d %b %Y}, 09:00 UTC" in note.message


@pytest.mark.django_db
def test_an_interview_is_shown_in_the_portal_s_zone(signal_on_application) -> None:
    from apps.concierge.models import Notification

    when = _ahead()
    signal = signal_on_application("ethz.ch")
    with tenant_transaction(signal.tenant_id):
        signal.application.deadline_timezone = "Asia/Baku"
        signal.application.save(update_fields=["deadline_timezone"])
    _apply(signal, label="INTERVIEW", interview_at=when.isoformat(timespec="minutes"))
    note = Notification.objects.get(roadmap_item__student=signal.application.student)
    local = when.astimezone(ZoneInfo("Asia/Baku"))
    assert f"{local:%d %b %Y, %H:%M} Asia/Baku" in note.message


@pytest.mark.django_db
def test_an_interview_time_nobody_can_place_says_to_read_the_email(signal_on_application) -> None:
    from apps.concierge.models import Notification

    signal = signal_on_application("ethz.ch")
    _apply(signal, label="INTERVIEW",
           interview_at=_ahead().replace(tzinfo=None).isoformat(timespec="minutes"))
    assert signal.interview_at is None
    note = Notification.objects.get(roadmap_item__student=signal.application.student)
    assert "See the email for the time" in note.message


# The controller amendment's three tests (ruling F8). They only parse strings, so
# their literal dates stay as written.


def test_an_interview_time_with_an_offset_is_kept_as_stated() -> None:
    assert _interview_time("2026-11-12T14:00:00+01:00", "") == datetime(
        2026, 11, 12, 13, 0, tzinfo=UTC
    )


def test_an_offset_less_time_is_read_in_the_portal_s_zone() -> None:
    assert _interview_time("2026-11-12T14:00:00", "Europe/Berlin") == datetime(
        2026, 11, 12, 14, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )


def test_an_offset_less_time_with_no_zone_is_not_guessed() -> None:
    assert _interview_time("2026-11-12T14:00:00", "") is None
    assert _interview_time("2026-11-12T14:00:00", "Not/AZone") is None


def test_the_schema_refuses_what_it_cannot_carry() -> None:
    with pytest.raises(ValidationError):
        MailVerdict(label="DOCUMENT_REQUEST", document_name="x" * 121)
    with pytest.raises(ValidationError):
        MailVerdict(label="INTERVIEW", interview_at="next Tuesday at ten")
    with pytest.raises(ValidationError):
        MailVerdict(label="DECISION", outcome="ADMITTED")  # the classifier reads no outcome
    with pytest.raises(ValidationError):
        MailVerdict(label="DECISION", outcome_conditions=("x",) * 7)


@pytest.mark.django_db
def test_the_reader_s_context_comes_from_the_card_and_the_student(connection_with_pack) -> None:
    """mail_context: the card's programme and institution, the student's name words
    and every address the student is known by, all read inside the tenant."""
    from apps.funding.models import PackCandidate
    from apps.mailbox.decision_reader import mail_context
    from apps.mailbox.models import MailSignal
    from apps.portals.models import Application

    student = connection_with_pack.membership
    with tenant_transaction(student.tenant_id):
        student.user.first_name, student.user.last_name = "Amina", "Yusuf"
        student.user.save(update_fields=["first_name", "last_name"])
        student.application_email = "amina.apply@example.test"
        student.save(update_fields=["application_email"])
        tum = PackCandidate.objects.get(candidate__program_name="MSc Informatics").candidate
        tum.institution_name = "Technical University of Munich"
        tum.save(update_fields=["institution_name"])
        application = Application.objects.create(
            tenant_id=student.tenant_id, student=student, program_id=tum.id, candidate=tum
        )
        signal = MailSignal.objects.create(
            tenant_id=student.tenant_id, connection=connection_with_pack,
            provider_message_id="ctx", sender_domain="tum.de", received_at=timezone.now(),
            application=application,
        )
        context = mail_context(signal)
    assert context is not None
    assert (context.programme, context.university, context.funding) == (
        "MSc Informatics", "Technical University of Munich", "",
    )
    assert {"amina", "yusuf"} <= context.names
    assert {"amina.apply@example.test", "student@gmail.test"} <= set(context.addresses)


@pytest.mark.django_db
def test_a_person_from_another_tenant_cannot_record_an_outcome(
    membership_b, signal_on_application
) -> None:
    signal = signal_on_application("tum.de")
    with tenant_transaction(signal.tenant_id), pytest.raises(PermissionError):
        correct_outcome(signal.application, "ADMITTED", actor=membership_b)
    signal.application.refresh_from_db()
    assert signal.application.outcome == ""


@pytest.mark.django_db
def test_an_automatic_outcome_is_audited_as_the_agent(signal_on_application) -> None:
    from apps.funding.models import AuditEvent

    signal = signal_on_application("tum.de")
    application = _apply(signal, label="DECISION", reading=_reading(outcome="ADMITTED"))
    with tenant_transaction(signal.tenant_id):
        event = AuditEvent.objects.get(object_id=application.id)
    assert (event.event, event.actor_id, event.actor_kind) == (
        "application.outcome_recorded", None, "AGENT",
    )


@pytest.mark.django_db
def test_trusted_without_the_provider_s_verdict_only_marks_it_available(
    signal_on_application,
) -> None:
    """Fix round 1, item 3, at the board: a tag-trusted signal never writes an outcome."""
    signal = signal_on_application("tum.de")
    application = _apply(
        signal, label="DECISION", provider_authenticated=False,
        reading=_reading(outcome="ADMITTED"),
    )
    assert application.decision_available_at is not None
    assert application.outcome == ""


@pytest.mark.django_db
def test_a_label_card_says_open_message_and_names_its_application(signal_on_application) -> None:
    from apps.concierge.models import Notification

    signal = signal_on_application("tum.de")
    _apply(signal, label="INTERVIEW")
    note = Notification.objects.get(application=signal.application)
    assert note.action == Notification.Action.OPEN_MESSAGE
