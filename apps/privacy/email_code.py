"""The 6-digit email code that stands between the sign-up form and the account.

The form's answers wait in the server-side session (the password only as its
hash) until the student types back the code mailed to them. Only then does
`views.signup_verify` create the account, so an address nobody can read never
becomes a login. The code itself is never stored: only an HMAC of it, bound to
the address, is.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from django.conf import settings
from django.contrib.sessions.backends.base import SessionBase
from django.core.mail import send_mail
from django.utils.crypto import constant_time_compare, salted_hmac

SESSION_KEY = "pending_signup"
CODE_TTL_SECONDS = 10 * 60
MAX_ATTEMPTS = 5
RESEND_AFTER_SECONDS = 60


def _digest(email: str, code: str) -> str:
    return salted_hmac("elmify.signup-code", f"{email}:{code}").hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def start(session: SessionBase, pending: dict[str, Any]) -> str:
    """Store the pending sign-up with a fresh code; return the code to mail."""
    code = new_code()
    session[SESSION_KEY] = {
        **pending,
        "digest": _digest(pending["email"], code),
        "expires": time.time() + CODE_TTL_SECONDS,
        "sent_at": time.time(),
        "attempts": 0,
    }
    return code


def pending(session: SessionBase) -> dict[str, Any] | None:
    value = session.get(SESSION_KEY)
    return value if isinstance(value, dict) else None


def resend(session: SessionBase) -> str | None:
    """A new code for the same pending sign-up, or None while the last is too fresh."""
    current = pending(session)
    if current is None or time.time() - float(current["sent_at"]) < RESEND_AFTER_SECONDS:
        return None
    return start(session, {k: v for k, v in current.items() if k not in _BOOKKEEPING})


_BOOKKEEPING = {"digest", "expires", "sent_at", "attempts"}


def check(session: SessionBase, code: str) -> str:
    """'ok', 'wrong', 'expired' or 'locked'. A wrong code counts an attempt."""
    current = pending(session)
    if current is None or time.time() > float(current["expires"]):
        return "expired"
    if int(current["attempts"]) >= MAX_ATTEMPTS:
        return "locked"
    typed = "".join(ch for ch in code if ch.isdigit())
    expected = str(current["digest"])
    if len(typed) == 6 and constant_time_compare(_digest(current["email"], typed), expected):
        return "ok"
    current["attempts"] = int(current["attempts"]) + 1
    session[SESSION_KEY] = current
    return "locked" if current["attempts"] >= MAX_ATTEMPTS else "wrong"


def clear(session: SessionBase) -> None:
    session.pop(SESSION_KEY, None)


def mail_code(email: str, code: str) -> None:
    send_mail(
        subject=f"{code} is your Elmify code",
        message=(
            f"Your Elmify sign-up code is {code}.\n\n"
            "Type it on the sign-up page to finish creating your account. "
            "It works for 10 minutes.\n\n"
            "If you did not sign up for Elmify, ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )
