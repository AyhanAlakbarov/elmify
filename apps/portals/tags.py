"""One tagged address per student per portal host (spec §2, §2a).

`name+tag@domain` reaches the same inbox, and only the portal it was given to
knows it, so mail sent to it names the portal and is strong evidence it came
from there.

Two records of what a portal does with the tag, and the difference is the
security model (plan 3, design decision 4; security review M2):

- `PortalAccount.tag_outcome` is what ONE student's account measured. The
  student's own evidence -- the extension's report, the dock's answer, the
  mail itself -- governs that account and nothing else.
- `PortalForm.tag_status` is shared by every tenant and is only a default for
  accounts not yet registered. It is moved by the platform alone
  (`manage.py set_tag_status`), never by a report: a report is a claim from a
  device or a mailbox one tenant controls, and letting it set the shared row
  let one tenant's student decide every other tenant's students' addresses --
  the same reason `FieldMap.learned_by_tenant` exists. A report contradicting
  a set status is logged for that human.
"""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime

from apps.watch.rules import REGISTRATION_MAIL_WINDOW

from .models import Application, PortalAccount, PortalForm

logger = logging.getLogger(__name__)

_TAG_ALPHABET = string.ascii_lowercase + string.digits
_TAG_LENGTH = 6
_UNKNOWN = PortalForm.TagStatus.UNKNOWN
_KEEPS = PortalForm.TagStatus.KEEPS
_REJECTS = PortalForm.TagStatus.REJECTS


def _new_tag() -> str:
    return "".join(secrets.choice(_TAG_ALPHABET) for _ in range(_TAG_LENGTH))


def tagged(address: str, tag: str) -> str:
    """`local+tag@domain`, or the address unchanged when it cannot take a tag."""
    local, at, domain = address.rpartition("@")
    if not at or not local or not domain or "+" in local:
        return address
    return f"{local}+{tag}@{domain}"


def plain_of(account: PortalAccount) -> str:
    """The account's address with OUR tag removed, or "" when it carries none.

    By the account's own tag, never by stripping any "+": a student whose own
    address already holds one was never tagged (see `tagged`), and cutting at
    their "+" would name a mailbox that is not theirs.
    """
    local, at, domain = account.address.rpartition("@")
    suffix = f"+{account.tag}"
    if not at or not account.tag or not local.casefold().endswith(suffix.casefold()):
        return ""
    return f"{local[: -len(suffix)]}@{domain}"


def account_for(application: Application) -> PortalAccount | None:
    """This student's account on this application's portal host, if issued."""
    if application.portal_form is None:
        return None
    return PortalAccount.objects.filter(
        student=application.student, portal_host=application.portal_form.portal_host
    ).first()


def portal_address(application: Application) -> str:
    """The address this student uses on this application's portal, or "".

    Run inside a tenant transaction: it creates the account on first use.
    The shared REJECTS decides only the FIRST issue. An issued address is
    never re-based by it (final review I1, superseding F1): the kit may have
    handed it out and the student registered by hand, which the server cannot
    see, so re-basing would hand them an address their portal account does
    not hold. Only this account's own evidence moves it (record_tag_outcome).
    """
    base = application.student.application_email
    form = application.portal_form
    if not base or form is None:
        return ""
    account, _ = PortalAccount.objects.get_or_create(
        student=application.student,
        portal_host=form.portal_host,
        defaults={"tenant_id": application.tenant_id, "tag": _new_tag()},
    )
    if not account.address:
        account.address = base if form.tag_status == _REJECTS else tagged(base, account.tag)
        account.save(update_fields=["address"])
    return account.address


def addresses_for(application: Application) -> tuple[str, str]:
    """This student's address on the application's portal, and that address
    without our tag ("" when untagged); ("", "") with no address. Run inside a
    tenant transaction: portal_address creates the account on first use."""
    address = portal_address(application)
    account = account_for(application) if address else None
    return address, plain_of(account) if account is not None else ""


def record_tag_outcome(account: PortalAccount, outcome: str, *, force: bool = False) -> bool:
    """Record what this account measured; True when it was the first measurement.

    Run inside the account's tenant transaction. Conditional updates, so two
    reports racing (the sync and the dock) settle on whichever lands first
    rather than on whichever saves last. Never writes the shared
    `PortalForm.tag_status` (module docstring).

    `force` skips the "only the first measurement" guard for this account
    alone -- the student's own "use my plain address" evidence always governs
    their own account (controller ruling F6), even over an earlier KEEPS.

    Refuses `outcome="UNKNOWN"`: that value means "not yet measured" and is
    never itself a measurement.
    """
    if outcome == _UNKNOWN:
        raise ValueError("record_tag_outcome cannot record UNKNOWN as a measured outcome")
    updates: dict[str, object] = {"tag_outcome": outcome}
    if outcome == _REJECTS and (plain := plain_of(account)):
        updates["address"] = plain
    if force and outcome == _REJECTS:
        updates["tag_dropped_by_student"] = True
    query = PortalAccount.objects.filter(pk=account.pk)
    if not force:
        query = query.filter(tag_outcome=_UNKNOWN)
    if not query.update(**updates):
        return False
    for field, value in updates.items():
        setattr(account, field, value)
    if (
        PortalForm.objects.filter(portal_host=account.portal_host)
        .exclude(tag_status__in=(outcome, _UNKNOWN))
        .exists()
    ):
        logger.warning("TagStatusDisputed portal=%s reported=%s", account.portal_host, outcome)
    return True


def restore_tag(account: PortalAccount) -> bool:
    """Mail to the tag arrived for an account whose own REJECTS dropped it.

    That mail proves the portal holds the tag, so a REJECTS from the page
    (`form`, `page`, `after_submit`) was wrong: the account goes back to KEEPS
    and its tagged address (final review M3). Never over the student's own
    button (`tag_dropped_by_student`), and never the shared row -- a correction
    is evidence about this account, like the REJECTS it corrects. Run inside
    the account's tenant transaction; conditional, like record_tag_outcome.
    """
    address = tagged(account.address, account.tag) if account.tag else account.address
    if address == account.address:
        return False
    moved = bool(
        PortalAccount.objects.filter(
            pk=account.pk,
            tag_outcome=_REJECTS,
            tag_dropped_by_student=False,
            address=account.address,
        ).update(tag_outcome=_KEEPS, address=address)
    )
    if moved:
        account.tag_outcome, account.address = _KEEPS, address
        logger.info("TagRestored portal=%s", account.portal_host)
    return moved


def mark_registered(account: PortalAccount, now: datetime) -> bool:
    """Record that the portal now holds this address; True only the first time.

    Run inside the account's tenant transaction. The extension reports every
    fill that typed the address; only the first opens the registration window,
    so a second application on the same portal account reopens nothing.
    """
    opened = bool(
        PortalAccount.objects.filter(pk=account.pk, registered_at__isnull=True).update(
            registered_at=now
        )
    )
    if opened:
        account.registered_at = now
    return opened


def awaits_registration_mail(account: PortalAccount, now: datetime) -> bool:
    """Is the portal's first email, which would say whether it keeps the tag, still due?"""
    return (
        account.registered_at is not None
        and now - account.registered_at < REGISTRATION_MAIL_WINDOW
        and account.tag_outcome == _UNKNOWN
        and bool(plain_of(account))
    )
