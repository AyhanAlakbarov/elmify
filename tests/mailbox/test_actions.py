"""The spec's acceptance criterion for extraction, and what a hostile mail cannot do.

"A fixture verification mail produces one DeviceAction whose payload is cleared
after completion and appears in no log and no MailSignal row."

The hostile cases matter more than the happy one. The mail is written by whoever
holds a domain in the student's pack; a compromised one gets to propose a URL
the extension would open in the student's own browser, already logged in.
"""

from __future__ import annotations

import logging

import pytest

from apps.mailbox.actions import apply_verdict
from apps.mailbox.classify import MailVerdict
from apps.mailbox.models import MailSignal
from apps.portals.actions import complete_action
from apps.portals.models import Application, ApplicationStep, DeviceAction
from apps.tenancy.db import tenant_transaction

ALLOWED = frozenset({"tum.de", "daad.de", "portal.uni-bonn.de"})


@pytest.mark.django_db
def test_a_verification_mail_produces_one_action_carrying_the_link(
    signal_on_application,
) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="OPEN_VERIFICATION_URL",
        action_value="https://portal.uni-bonn.de/verify?t=abc123",
    )

    with tenant_transaction(signal.tenant_id):
        action = apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True)

    assert action is not None
    assert action.kind == DeviceAction.Kind.OPEN_VERIFICATION_URL
    assert action.payload == {"url": "https://portal.uni-bonn.de/verify?t=abc123"}
    assert action.application_id == signal.application_id


@pytest.mark.django_db
def test_a_mailbox_action_outlives_the_15_minute_foreground_default(
    signal_on_application,
) -> None:
    """Queued by an unattended hourly sweep, not a student already at the
    dashboard -- ACTION_TTL's 15 minutes would routinely expire before the
    student's next visit."""
    from datetime import timedelta

    from apps.portals.actions import ACTION_TTL

    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="OPEN_VERIFICATION_URL",
        action_value="https://portal.uni-bonn.de/verify?t=abc123",
    )

    with tenant_transaction(signal.tenant_id):
        action = apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True)

    assert action is not None
    life = action.expires_at - action.created_at
    assert life > ACTION_TTL
    assert life >= timedelta(hours=1)


@pytest.mark.django_db
def test_the_payload_is_gone_once_the_action_completes(signal_on_application) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="OPEN_VERIFICATION_URL",
        action_value="https://portal.uni-bonn.de/verify?t=abc123",
    )

    with tenant_transaction(signal.tenant_id):
        action = apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True)
        complete_action(action)

    action.refresh_from_db()
    assert action.payload == {}


@pytest.mark.django_db
def test_the_link_is_in_no_mail_signal_row_and_no_log(signal_on_application, caplog) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="OPEN_VERIFICATION_URL",
        action_value="https://portal.uni-bonn.de/verify?t=SECRETTOKEN",
    )

    with caplog.at_level(logging.DEBUG), tenant_transaction(signal.tenant_id):
        apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True)

    assert "SECRETTOKEN" not in caplog.text
    with tenant_transaction(signal.tenant_id):
        rows = list(MailSignal.objects.values())
    assert "SECRETTOKEN" not in str(rows)


@pytest.mark.django_db
def test_a_link_off_the_allowlist_is_refused(signal_on_application) -> None:
    """The mail came from a pack domain; the link does not have to. A
    compromised institutional account proposing https://evil.example/steal is
    exactly the case, and the extension would open it in the student's own
    logged-in browser."""
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="OPEN_VERIFICATION_URL",
        action_value="https://evil.example/steal",
    )

    with tenant_transaction(signal.tenant_id):
        assert apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True) is None
        assert DeviceAction.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "http://portal.uni-bonn.de/verify",
        "javascript:alert(1)",
        "https://user:pw@portal.uni-bonn.de/verify",
        "not a url at all",
        "",
    ],
)
def test_only_a_plain_https_url_on_an_allowed_host_survives(
    signal_on_application, url: str
) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION", action_kind="OPEN_VERIFICATION_URL", action_value=url
    )

    with tenant_transaction(signal.tenant_id):
        assert apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True) is None


@pytest.mark.django_db
@pytest.mark.parametrize("raw_code", ["418902", "418-902", "418 902"])
def test_a_code_becomes_a_type_code_action(signal_on_application, raw_code: str) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(label="VERIFICATION", action_kind="TYPE_CODE", action_value=raw_code)

    with tenant_transaction(signal.tenant_id):
        action = apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True)

    assert action is not None
    assert action.kind == DeviceAction.Kind.TYPE_CODE
    # The sender, so a code shown in the panel says which portal it is for.
    assert action.payload == {"code": "418902", "from": "portal.uni-bonn.de"}


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["٤١٨٩٠٢", "４１８９０２", "kód123"])
def test_a_code_the_extension_cannot_type_is_not_queued(signal_on_application, value) -> None:
    # Unicode digits pass str.isalnum(); the extension types ASCII only, so a
    # queued one would wait ten minutes and then be left to the student.
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(label="VERIFICATION", action_kind="TYPE_CODE", action_value=value)

    with tenant_transaction(signal.tenant_id):
        assert apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True) is None


@pytest.mark.django_db
def test_something_long_is_not_a_code(signal_on_application) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION", action_kind="TYPE_CODE", action_value="a" * 200
    )

    with tenant_transaction(signal.tenant_id):
        assert apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True) is None


@pytest.mark.django_db
def test_a_received_mail_confirms_a_submitted_application(signal_on_application) -> None:
    """Application.State.CONFIRMED gains its first writer here.

    SUBMITTED means the portal took the form. CONFIRMED means the institution
    said so in writing, and until now nothing in this system could ever say
    that.
    """
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        signal.application.state = Application.State.SUBMITTED
        signal.application.save(update_fields=["state"])

        apply_verdict(signal, MailVerdict(label="RECEIVED"), link_hosts=ALLOWED, authenticated=True)

        signal.application.refresh_from_db()
        assert signal.application.state == Application.State.CONFIRMED
        step = ApplicationStep.objects.filter(application=signal.application).latest("sequence")
        assert step.kind == ApplicationStep.Kind.STATUS
        assert step.detail["source"] == "mailbox"


@pytest.mark.django_db
def test_a_received_mail_does_not_confirm_an_application_still_being_prepared(
    signal_on_application,
) -> None:
    signal = signal_on_application("portal.uni-bonn.de")

    with tenant_transaction(signal.tenant_id):
        apply_verdict(signal, MailVerdict(label="RECEIVED"), link_hosts=ALLOWED, authenticated=True)
        signal.application.refresh_from_db()

    assert signal.application.state == Application.State.PREPARING


@pytest.mark.django_db
def test_an_unauthenticated_message_is_recorded_but_never_acted_on(
    signal_on_application,
) -> None:
    """`From:` is a header anyone can write.

    The allowlist decides what we are willing to READ. It cannot decide who
    sent a message, so without the provider's own delivery verdict anyone who
    knows the student's address could queue a link into their browser by typing
    a university's address into a From line.
    """
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="OPEN_VERIFICATION_URL",
        action_value="https://portal.uni-bonn.de/verify?t=abc123",
    )

    with tenant_transaction(signal.tenant_id):
        assert apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=False) is None
        assert DeviceAction.objects.count() == 0

    # The signal and its label survive: the student is still told that someone
    # claiming to be that institution wrote to them, which is true.
    signal.refresh_from_db()
    assert signal.label == MailSignal.Label.VERIFICATION


@pytest.mark.django_db
def test_an_unauthenticated_received_mail_does_not_confirm_an_application(
    signal_on_application,
) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        signal.application.state = Application.State.SUBMITTED
        signal.application.save(update_fields=["state"])

        apply_verdict(
            signal, MailVerdict(label="RECEIVED"), link_hosts=ALLOWED, authenticated=False
        )

        signal.application.refresh_from_db()
        assert signal.application.state == Application.State.SUBMITTED


@pytest.mark.django_db
def test_a_backslash_url_is_refused_even_though_urlsplit_likes_its_host(
    signal_on_application,
) -> None:
    """Python and a browser disagree about the backslash.

    urlsplit reports hostname="tum.de" for this value; Chrome reads the host as
    evil.example. The userinfo guard already refuses it -- urlsplit also reports
    username="evil.example\\" -- and the explicit check closes the class rather
    than leaving it to a second guard to keep catching.
    """
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="OPEN_VERIFICATION_URL",
        action_value="https://evil.example\\@portal.uni-bonn.de/verify",
    )

    with tenant_transaction(signal.tenant_id):
        assert apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True) is None
        assert DeviceAction.objects.count() == 0


@pytest.mark.django_db
def test_the_label_is_recorded_on_the_signal(signal_on_application) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        apply_verdict(signal, MailVerdict(label="DECISION"), link_hosts=ALLOWED, authenticated=True)
    signal.refresh_from_db()
    assert signal.label == MailSignal.Label.DECISION


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        # NFKC normalization inside urlsplit's own userinfo handling.
        "https://portal.uni-bonn.de\N{FULLWIDTH NUMBER SIGN}@evil.example/",
        # NFKC-normalizes into characters urlsplit treats as separators.
        "https://portal.uni-bonn.de\N{ALEF SYMBOL}/x",
        # Truncated IPv6 literal -- urlsplit raises "Invalid IPv6 URL".
        "https://[::1",
    ],
)
def test_a_url_urlsplit_cannot_parse_is_refused_not_raised(
    signal_on_application, url: str
) -> None:
    """`_verification_url`'s whole contract is "return empty for anything
    unacceptable" -- this text was copied by the model out of a hostile
    email, so a crash here is a crash a hostile sender controls: one crafted
    message would abort the rest of that sync batch (see apply_verdict's
    caller in sync.py, which has no except around this call)."""
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION", action_kind="OPEN_VERIFICATION_URL", action_value=url
    )

    with tenant_transaction(signal.tenant_id):
        assert apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True) is None


@pytest.mark.django_db
def test_a_trusted_fee_receipt_marks_the_fee_paid(signal_on_application) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        Application.objects.filter(id=signal.application_id).update(fee_state="OPEN")

        apply_verdict(
            signal, MailVerdict(label="FEE_PAID"), link_hosts=ALLOWED, authenticated=True
        )

        application = Application.objects.get(id=signal.application_id)
    assert (application.fee_state, application.fee_paid_source) == ("PAID", "MAIL")
    assert application.fee_paid_at == signal.received_at


@pytest.mark.django_db
@pytest.mark.parametrize("vouched", [False, True])
def test_an_untrusted_fee_receipt_never_changes_the_fee_state(
    signal_on_application, vouched
) -> None:
    """Spec §15: untrusted mail never changes fee_state. Anyone can write a
    university's address into a From line."""
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        Application.objects.filter(id=signal.application_id).update(fee_state="OPEN")

        apply_verdict(
            signal, MailVerdict(label="FEE_PAID"), link_hosts=ALLOWED,
            authenticated=False, vouched=vouched,
        )

        application = Application.objects.get(id=signal.application_id)
    assert (application.fee_state, application.fee_paid_source) == ("OPEN", "")


@pytest.mark.django_db
def test_a_receipt_after_the_student_marked_it_keeps_the_students_record(
    signal_on_application,
) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        Application.objects.filter(id=signal.application_id).update(
            fee_state="PAID", fee_paid_source="STUDENT"
        )

        apply_verdict(
            signal, MailVerdict(label="FEE_PAID"), link_hosts=ALLOWED, authenticated=True
        )

        application = Application.objects.get(id=signal.application_id)
    assert application.fee_paid_source == "STUDENT"


def _asked(signal, *names, state="ASKED"):
    """One request per professor on the signal's application (lanes spec §11.3)."""
    from apps.documents.models import Referee, RefereeRequest

    return [
        RefereeRequest.objects.create(
            tenant_id=signal.tenant_id, application=signal.application, state=state,
            referee=Referee.objects.create(
                tenant_id=signal.tenant_id, student=signal.application.student, name=name
            ),
        )
        for name in names
    ]


def _referee_states(signal):
    from apps.documents.models import RefereeRequest

    return sorted(
        RefereeRequest.objects.filter(application=signal.application).values_list(
            "state", flat=True
        )
    )


@pytest.mark.django_db
def test_a_trusted_referee_submitted_mail_marks_the_one_professor_asked(
    signal_on_application,
) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        _asked(signal, "Rauf Aliyev", state="AGREED")
        apply_verdict(
            signal, MailVerdict(label="REFEREE_SUBMITTED"), link_hosts=ALLOWED,
            authenticated=True,
        )
        assert _referee_states(signal) == ["SUBMITTED"]


@pytest.mark.django_db
def test_with_two_professors_asked_the_mail_changes_nothing_and_asks_which(
    signal_on_application,
) -> None:
    from apps.concierge.models import Notification

    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        _asked(signal, "Rauf Aliyev", "Leyla Karimova")
        apply_verdict(
            signal, MailVerdict(label="REFEREE_SUBMITTED"), link_hosts=ALLOWED,
            authenticated=True,
        )
        assert _referee_states(signal) == ["ASKED", "ASKED"]
        notes = list(Notification.objects.values_list("message", flat=True))
    assert len(notes) == 1
    assert notes[0].startswith("portal.uni-bonn.de says a referee submitted a letter for ")
    assert "Mark which professor it was" in notes[0]


@pytest.mark.django_db
@pytest.mark.parametrize("vouched", [False, True])
def test_an_untrusted_referee_submitted_mail_never_changes_a_referee(
    signal_on_application, vouched
) -> None:
    """Spec §15: untrusted mail never changes a referee status."""
    from apps.concierge.models import Notification

    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        _asked(signal, "Rauf Aliyev")
        apply_verdict(
            signal, MailVerdict(label="REFEREE_SUBMITTED"), link_hosts=ALLOWED,
            authenticated=False, vouched=vouched,
        )
        assert _referee_states(signal) == ["ASKED"]
        assert not Notification.objects.exists()
    signal.refresh_from_db()
    assert signal.label == "REFEREE_SUBMITTED"


@pytest.mark.django_db
@pytest.mark.parametrize(("states", "alerts"), [(("PROPOSED", "DECLINED"), 1), (("DECLINED",), 0)])
def test_a_proposed_or_declined_request_is_never_marked_from_mail(
    signal_on_application, states, alerts
) -> None:
    """A proposed professor may have been asked without the student saying so: ask
    which. Only declined ones: nobody to ask about."""
    from apps.concierge.models import Notification

    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        for name, state in zip(("Rauf Aliyev", "Leyla Karimova"), states, strict=False):
            _asked(signal, name, state=state)
        apply_verdict(
            signal, MailVerdict(label="REFEREE_SUBMITTED"), link_hosts=ALLOWED,
            authenticated=True,
        )
        assert _referee_states(signal) == sorted(states)
        assert Notification.objects.count() == alerts


@pytest.mark.django_db
@pytest.mark.parametrize(
    "states",
    [
        # Case A: one asked, one still proposed -- the student may have sent both.
        ("ASKED", "PROPOSED"),
        # Case B: one marked submitted by hand; the mail may be that one's confirmation.
        ("SUBMITTED", "AGREED"),
    ],
)
def test_one_open_request_beside_another_professor_changes_nothing_and_asks_which(
    signal_on_application, states
) -> None:
    """Final review I1: mark from mail only when the open request is the card's only
    request outside DECLINED and SUBMITTED. Otherwise ask which professor."""
    from apps.concierge.models import Notification

    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        for name, state in zip(("Rauf Aliyev", "Leyla Karimova"), states, strict=True):
            _asked(signal, name, state=state)
        apply_verdict(
            signal, MailVerdict(label="REFEREE_SUBMITTED"), link_hosts=ALLOWED,
            authenticated=True,
        )
        assert _referee_states(signal) == sorted(states)
        notes = list(Notification.objects.values_list("message", flat=True))
    assert len(notes) == 1
    assert "Mark which professor it was" in notes[0]


@pytest.mark.django_db
def test_one_asked_beside_a_declined_one_is_still_marked(signal_on_application) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        _asked(signal, "Rauf Aliyev", state="ASKED")
        _asked(signal, "Leyla Karimova", state="DECLINED")
        apply_verdict(
            signal, MailVerdict(label="REFEREE_SUBMITTED"), link_hosts=ALLOWED,
            authenticated=True,
        )
        assert _referee_states(signal) == ["DECLINED", "SUBMITTED"]


@pytest.mark.django_db
def test_spaced_single_digit_otp_code_is_stripped_and_queued(signal_on_application) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="TYPE_CODE",
        action_value="1 2 3 4 5 6",
    )
    with tenant_transaction(signal.tenant_id):
        action = apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True)
    assert action is not None
    assert action.payload == {"code": "123456", "from": "portal.uni-bonn.de"}


@pytest.mark.django_db
def test_referee_submitted_disambiguates_multiple_professors_by_email_or_surname(
    signal_on_application,
) -> None:
    from apps.concierge.models import Notification
    from apps.documents.models import Referee, RefereeRequest

    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        ref_a = Referee.objects.create(
            tenant_id=signal.tenant_id,
            student=signal.application.student,
            name="Prof. Rauf Əliyev",
            email="aliyev@bsu.edu.az",
        )
        ref_b = Referee.objects.create(
            tenant_id=signal.tenant_id,
            student=signal.application.student,
            name="Dr. Leyla Məmmədova",
            email="mammadova@ada.edu.az",
        )
        req_a = RefereeRequest.objects.create(
            tenant_id=signal.tenant_id,
            application=signal.application,
            referee=ref_a,
            state="ASKED",
        )
        req_b = RefereeRequest.objects.create(
            tenant_id=signal.tenant_id,
            application=signal.application,
            referee=ref_b,
            state="AGREED",
        )

        # Receipt mentions Prof. Aliyev by transliterated surname & email
        apply_verdict(
            signal,
            MailVerdict(label="REFEREE_SUBMITTED"),
            link_hosts=ALLOWED,
            authenticated=True,
            body=(
                "Dear Applicant, Prof. Aliyev (aliyev@bsu.edu.az) has submitted "
                "a recommendation letter for your application."
            ),
        )
        req_a.refresh_from_db()
        req_b.refresh_from_db()
        assert req_a.state == "SUBMITTED"
        assert req_b.state == "AGREED"
        assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_referee_submitted_asks_student_when_body_mentions_both_professors(
    signal_on_application,
) -> None:
    from apps.concierge.models import Notification

    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        _asked(signal, "Rauf Aliyev", "Leyla Karimova")
        apply_verdict(
            signal,
            MailVerdict(label="REFEREE_SUBMITTED"),
            link_hosts=ALLOWED,
            authenticated=True,
            body="Your referees Prof. Aliyev and Prof. Karimova are listed on your application.",
        )
        assert _referee_states(signal) == ["ASKED", "ASKED"]
        notes = list(Notification.objects.values_list("message", flat=True))
    assert len(notes) == 1
    assert "Mark which professor it was" in notes[0]


@pytest.mark.django_db
def test_sync_connection_passes_body_to_disambiguate_referee_submission(
    connection_with_pack, monkeypatch
) -> None:
    from datetime import UTC, datetime

    from apps.concierge.models import Notification
    from apps.documents.models import Referee, RefereeRequest
    from apps.mailbox import sync as sync_module
    from apps.mailbox.providers import MailBody, MessageHeader
    from apps.mailbox.sync import sync_connection
    from apps.tenancy.context import tenant_scope
    from tests.mailbox.conftest import FakeProvider, _grant

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        app = Application.objects.get(student=connection.membership)
        ref_a = Referee.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            name="Prof. Rauf Aliyev",
            email="aliyev@bsu.edu.az",
        )
        ref_b = Referee.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            name="Dr. Leyla Karimova",
            email="karimova@ada.edu.az",
        )
        req_a = RefereeRequest.objects.create(
            tenant_id=connection.tenant_id, application=app, referee=ref_a, state="ASKED"
        )
        req_b = RefereeRequest.objects.create(
            tenant_id=connection.tenant_id, application=app, referee=ref_b, state="ASKED"
        )

    class BodyProvider(FakeProvider):
        def fetch_body(self, *, access_token: str, message_id: str) -> MailBody:
            self.bodies_fetched.append(message_id)
            return MailBody(
                "Dr. Leyla Karimova (karimova@ada.edu.az) has submitted a reference letter."
            )

    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(label="REFEREE_SUBMITTED"),
    )
    header = MessageHeader(
        message_id="m-ref-sync",
        sender="noreply@uni-bonn.de",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        authenticated=True,
    )

    with tenant_scope(connection.tenant_id):
        sync_connection(
            connection, provider=BodyProvider((header,)), secrets_client=_grant()
        )
        with tenant_transaction(connection.tenant_id):
            req_a.refresh_from_db()
            req_b.refresh_from_db()
            whiches = Notification.objects.filter(
                recipient=connection.membership,
                message__contains="Mark which professor it was",
            ).count()

    assert req_a.state == "ASKED"
    assert req_b.state == "SUBMITTED"
    assert whiches == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "label",
    [
        "RECEIVED",
        "FEE",
        "FEE_PAID",
        "REFEREE_SUBMITTED",
        "INTERVIEW",
        "DOCUMENT_REQUEST",
    ],
)
def test_apply_verdict_disambiguates_non_decision_labels_across_shared_portal_applications(
    signal_on_application, label: str
) -> None:
    from uuid import uuid4

    from apps.portals.models import PortalForm

    signal = signal_on_application("portal.uni-bonn.de")
    with tenant_transaction(signal.tenant_id):
        app1 = signal.application
        app1.name = "M.Sc. Informatics"
        app1.state = Application.State.SUBMITTED
        app1.fee_state = "OPEN"
        app1.save(update_fields=["name", "state", "fee_state"])
        form = PortalForm.objects.get(id=app1.portal_form_id)
        app2 = Application.objects.create(
            tenant_id=signal.tenant_id,
            student=app1.student,
            program_id=uuid4(),
            portal_form=form,
            name="M.Sc. Robotics",
            state=Application.State.SUBMITTED,
            fee_state="OPEN",
        )
        ApplicationStep.objects.create(
            tenant_id=signal.tenant_id,
            application=app2,
            sequence=1,
            kind=ApplicationStep.Kind.STATUS,
            detail={"application_number": "BONN-777"},
        )
        signal.application = None
        signal.save(update_fields=["application"])

        apply_verdict(
            signal,
            MailVerdict(
                label=label,
                application_number="BONN-777",
                document_name="Transcript" if label == "DOCUMENT_REQUEST" else "",
            ),
            link_hosts=ALLOWED,
            authenticated=True,
            shared_portal=("portal.uni-bonn.de", 2),
        )
        signal.refresh_from_db()
        app1.refresh_from_db()
        app2.refresh_from_db()

    assert signal.application_id == app2.id
    if label == "RECEIVED":
        assert app2.state == Application.State.CONFIRMED
        assert app1.state == Application.State.SUBMITTED
    if label == "FEE_PAID":
        assert app2.fee_state == "PAID"
        assert app1.fee_state == "OPEN"


def test_resolve_ambiguous_application_handles_candidate_evidence_fk_and_uni_assist_shared_portal(
    signal_on_application,
) -> None:
    from uuid import uuid4

    from apps.funding.models import EvidenceClaim
    from apps.mailbox.actions import resolve_ambiguous_application
    from apps.mailbox.decision_reader import DecisionReading
    from apps.mailbox.filter import _SHARED_PLATFORMS
    from apps.portals.models import PortalForm

    assert "uni-assist.de" in _SHARED_PLATFORMS

    signal = signal_on_application("uni-assist.de")
    with tenant_transaction(signal.tenant_id):
        app1 = signal.application
        student = app1.student
        ua_form = PortalForm.objects.create(
            portal_host="my.uni-assist.de",
            form_key="/apply",
            form_url="https://my.uni-assist.de/apply",
        )
        app1.name = "M.Sc. Data Science"
        app1.portal_form = ua_form
        app1.save(update_fields=["name", "portal_form"])

        # Second application without a matching portal_form host, linked via candidate.evidence FK
        from tests.funding.conftest import make_db_candidate, make_run

        run = make_run(signal.tenant, student)
        cand = make_db_candidate(signal.tenant, run, program_name="M.Sc. Robotics")
        EvidenceClaim.objects.filter(id=cand.evidence_id).update(
            source_url="https://my.uni-assist.de/programmes/robotics"
        )
        other_form = PortalForm.objects.create(
            portal_host="other.example.edu",
            form_key="/other",
            form_url="https://other.example.edu/other",
        )
        app2 = Application.objects.create(
            tenant_id=signal.tenant_id,
            student=student,
            program_id=uuid4(),
            candidate=cand,
            portal_form=other_form,
            name="M.Sc. Robotics",
        )
        signal.application = None
        signal.save(update_fields=["application"])

        # Admission naming M.Sc. Robotics matches app2 (using candidate.evidence ForeignKey)
        matched, _ = resolve_ambiguous_application(
            signal,
            MailVerdict(label="DECISION", offered_programme="M.Sc. Robotics"),
            reading=DecisionReading(
                is_decision=True,
                outcome="ADMITTED",
                funding_outcome="",
                other_programme_offered=False,
                measured=True,
            ),
        )
        assert matched == app2

        # Rejection offering M.Sc. Robotics as an alternative programme must NOT match app2
        rejected_match, context_app = resolve_ambiguous_application(
            signal,
            MailVerdict(label="DECISION", offered_programme="M.Sc. Robotics"),
            reading=DecisionReading(
                is_decision=True,
                outcome="REJECTED",
                funding_outcome="",
                other_programme_offered=True,
                measured=True,
            ),
        )
        assert rejected_match is None
        assert context_app in (app1, app2)


