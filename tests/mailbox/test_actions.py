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
