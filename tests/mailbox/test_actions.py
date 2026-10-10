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
def test_a_code_becomes_a_type_code_action(signal_on_application) -> None:
    signal = signal_on_application("portal.uni-bonn.de")
    verdict = MailVerdict(label="VERIFICATION", action_kind="TYPE_CODE", action_value="418902")

    with tenant_transaction(signal.tenant_id):
        action = apply_verdict(signal, verdict, link_hosts=ALLOWED, authenticated=True)

    assert action is not None
    assert action.kind == DeviceAction.Kind.TYPE_CODE
    assert action.payload == {"code": "418902"}


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
