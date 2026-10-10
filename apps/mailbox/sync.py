"""List, filter, record. The body tier is Task 10's; this is the spine.

Transactions are deliberately short and repeated rather than one long one: the
provider calls and (later) the model calls happen between them, and holding a
transaction open across network work is what CLAUDE.md flags as the expensive
shape in read_and_derive. tenant_transaction's own docstring says the same.

Deviation from the brief: the ``get_or_create`` call and the ``is_new`` check
that follows it live in the SAME ``tenant_transaction`` block, one per header,
rather than the narrower shape (create in the transaction, the is_new check
outside it). Later tasks add more writes inside that same ``if is_new:``
branch -- a notification card, a body classification, a device action -- and
all of that must commit atomically with the signal. Widening the transaction
now is what makes that possible without another restructure.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.db.models import F
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.mailbox.actions import apply_verdict
from apps.mailbox.classify import ClassificationFailure, ClassificationRateLimited, classify_message
from apps.mailbox.decision_reader import keep_verified, mail_context, read_decision
from apps.mailbox.filter import (
    _key,
    allowed_senders,
    learnable_domain,
    link_hosts,
    matched_domain,
    sender_key,
    tracking_since,
    unconfirmed_senders,
    vouched_senders,
)
from apps.mailbox.models import (
    MAX_CLASSIFY_ATTEMPTS,
    LearnedSender,
    MailboxConnection,
    MailSignal,
)
from apps.mailbox.oauth import GrantRefused, access_token_for
from apps.mailbox.providers import MailboxProvider, MessageHeader, ProviderError, provider_for
from apps.portals.models import Application, PortalAccount, PortalForm
from apps.portals.tags import (
    awaits_registration_mail,
    plain_of,
    record_tag_outcome,
    restore_tag,
    tagged,
)
from apps.privacy.requests import processing_stopped
from apps.ratelimit import rate_limited
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership
from apps.watch.rules import REGISTRATION_MAIL_WINDOW

logger = logging.getLogger(__name__)

#: Six syncs an hour per student. The sweep runs far less often than this; the
#: limit exists so a connect screen, a manual retry and the sweep together
#: cannot become a provider-quota problem.
SYNC_LIMIT = 6
SYNC_WINDOW_SECONDS = 3600

#: Push syncs (push.py) count in their own bucket. A burst of mail is one
#: notification per message, and spending the six above on it would leave the
#: extension's "check now" refused exactly when a code is on its way. Graph
#: allows thousands of requests per mailbox per ten minutes; a sync is a few.
PUSH_SYNC_BUCKET = "mailbox-push-sync"
PUSH_SYNC_LIMIT = 60

#: A week. The card is "an institution wrote to you"; it is not an escalation
#: and it does not have a service-level agreement, but RoadmapItem.deadline is
#: NOT NULL, so it needs a number and this is the honest one.
CARD_SLA = timedelta(days=7)


#: Fix round 1, finding 1: after a classify outage the retry backlog can be
#: arbitrarily large. Bounding it (oldest first) keeps one sync's provider
#: calls finite -- the same provider-quota concern SYNC_LIMIT exists for.
MAX_RETRIES_PER_SYNC = 10

#: Final review I5: at most this many of THIS run's new signals are
#: classified, newest first -- a verification code the student is waiting for
#: is the newest mail. The rest wait, unlabelled at attempts 0, for the next
#: sync's retry pass. Together with MAX_RETRIES_PER_SYNC this keeps one sync
#: under classify.CLASSIFY_LIMIT instead of burning retries on our own limit.
MAX_CLASSIFY_PER_SYNC = 20


class SyncRefused(Exception):
    """This connection cannot sync now. Never carries a token or an address."""


def _card(
    connection: MailboxConnection,
    *,
    stage: str,
    message: str,
    urgent: bool = False,
    action: str = "",
) -> Notification:
    """The agent's own card for the student: no human was asked to do anything
    by the arrival of a message, so no owner.

    ``urgent`` (fix round 1, finding 1): only announce_lost_grant sets this --
    escalation.py carries an urgent, unacknowledged alert to the student's
    sign-in address and then the counsellor, which is what spec §4/§5 require
    for a dead grant.
    """
    return Notification.raise_card(
        student=connection.membership,
        recipient=connection.membership,
        stage=stage,
        deadline=timezone.now() + CARD_SLA,
        message=message,
        urgent=urgent,
        action=action,
    )


def announce(signal: MailSignal) -> Notification:
    """The card for a new message. Names the institution, never the message."""
    return _card(
        signal.connection,
        stage=RoadmapItem.Stage.MONITORING,
        message=f"{signal.sender_domain} wrote to you.",
        action=Notification.Action.OPEN_MESSAGE,
    )


def announce_lost_grant(connection: MailboxConnection) -> Notification:
    return _card(
        connection,
        stage=RoadmapItem.Stage.PERSONAL_ACTION,
        urgent=True,
        action=Notification.Action.RECONNECT,
        message=(
            f"Your {connection.provider.title()} mailbox connection stopped working. "
            "Reconnect it so we keep seeing replies from the universities you applied to."
        ),
    )


def _cursor(connection: MailboxConnection) -> datetime | None:
    if not connection.sync_cursor:
        return None
    try:
        return datetime.fromisoformat(connection.sync_cursor)
    except ValueError:
        # A cursor we cannot parse is a cursor we should not trust; fall back to
        # where tracking began rather than to the epoch.
        return None


def _search_for(connection: MailboxConnection, allowed: Iterable[str]) -> tuple[str, ...]:
    """The domains to ask the provider for, or () to list everything and filter here.

    Only Gmail on the content tier: gmail.readonly accepts a search, while
    gmail.metadata refuses the `q` parameter outright. Graph documents no
    filter on a sender's domain, so Microsoft lists by date and filters here.
    The filter in this module runs either way; the search only means strangers'
    mail is never listed, and the page ceiling counts pack mail alone.
    """
    if connection.kind == MailboxConnection.Kind.APPLICATION:
        return ()
    if (
        connection.provider == MailboxConnection.Provider.GOOGLE
        and connection.tier == MailboxConnection.Tier.CONTENT
    ):
        return tuple(allowed)
    return ()


def _classify(
    connection: MailboxConnection,
    client: MailboxProvider,
    token: str,
    signal: MailSignal,
    links: set[str],
    *,
    vouched: set[str],
    shared_portal: tuple[str, int] | None = None,
) -> bool:
    """Fetch, classify and act on one signal's body -- new or retried alike.

    Outside any transaction while it fetches and classifies: that is network
    work, and holding a tenant transaction across it is the shape CLAUDE.md
    flags in read_and_derive. A failure never re-raises; it counts against
    ``classify_attempts`` and, at the ceiling, tells the student to read the
    message themselves instead of retrying forever.

    Returns False when this sync's classify pass should stop: our own rate
    limit refused, which is not the message's fault and so costs it no
    attempt, and would refuse every later signal this sync too (final review
    I5). The signal stays unlabelled and the next sync's retry pass takes it.
    """
    try:
        fetched = client.fetch_body(access_token=token, message_id=signal.provider_message_id)
        body = fetched.text
        verdict = classify_message(
            body=body,
            sender_domain=signal.sender_domain,
            student_id=connection.membership_id,
        )
    except ClassificationRateLimited:
        logger.info("classify rate limit reached on connection %s", connection.id)
        return False
    except (ProviderError, ClassificationFailure):
        with tenant_transaction(connection.tenant_id):
            # Fix round 1, finding 2: compare-and-swap, not check-then-act.
            # Two overlapping syncs (the hourly sweep and an extension-
            # triggered check) can both hold the same stale in-memory
            # ``signal.classify_attempts``. Only the sync whose base value
            # still matches the row moves it; the other updates zero rows and
            # does nothing further -- it does not re-increment past MAX and it
            # does not create a second card.
            moved = MailSignal.objects.filter(
                pk=signal.pk, classify_attempts=signal.classify_attempts
            ).update(classify_attempts=F("classify_attempts") + 1)
            if moved and signal.classify_attempts + 1 == MAX_CLASSIFY_ATTEMPTS:
                _card(
                    connection,
                    stage=RoadmapItem.Stage.MONITORING,
                    message=(
                        f"{signal.sender_domain} wrote to you. "
                        "Open the message to see what it says."
                    ),
                    action=Notification.Action.OPEN_MESSAGE,
                )
        # A message we could not read is a message that stays a bare signal.
        # The card already told the student it arrived.
        logger.warning("could not classify a message on connection %s", connection.id)
    else:
        # Jev reads every classified mail tied to a card: a decision the
        # classifier labelled OTHER still gets its one reading. Outside any
        # transaction, like the classify call; the context is read inside one.
        # The subject came with the body (ruling F19), content tier only; it
        # is stripped like the body and stored nowhere.
        reading = None
        if signal.application_id is not None:
            with tenant_transaction(connection.tenant_id):
                context = mail_context(signal)
            if context is not None:
                reading = read_decision(
                    body, signal.sender_domain, context.programme, context.university,
                    context.funding, student_id=connection.membership_id,
                    subject=fetched.subject, names=context.names,
                    addresses=context.addresses,
                )
        with tenant_transaction(connection.tenant_id):
            # Locked and re-checked (Task 15 minor): the verdict was read for an
            # unlabelled row at this attempt count. If the student labelled it,
            # or another sync's failure moved it to the ceiling -- where
            # documents.table.vouched() reads a label as the student's own --
            # this verdict is no longer about that row.
            unchanged = (
                MailSignal.objects.select_for_update()
                .filter(pk=signal.pk, label="", classify_attempts=signal.classify_attempts)
                .first()
            )
            if unchanged is None:
                return True
            apply_verdict(
                signal,
                keep_verified(verdict, body),
                reading=reading,
                link_hosts=links,
                authenticated=signal.trusted,
                vouched=signal.sender_domain in vouched,
                shared_portal=shared_portal,
            )
    return True


def sync_connection(
    connection: MailboxConnection,
    *,
    provider: MailboxProvider | None = None,
    http: object | None = None,
    secrets_client: object | None = None,
    rate_bucket: str = "mailbox-sync",
    limit: int = SYNC_LIMIT,
) -> list[MailSignal]:
    """Read this connection's new mail and record what the pack justifies.

    Returns the signals created by THIS run: a re-run returns an empty list,
    because a message already seen is not news.
    """
    if connection.status != MailboxConnection.Status.ACTIVE:
        raise SyncRefused(f"connection is {connection.status}")
    # An open objection or withdrawal stops all processing for the student (Art. 7.2),
    # and reading their mail is processing. Before the limiter, so a refusal costs nothing.
    with tenant_transaction(connection.tenant_id):
        stopped = processing_stopped(connection.membership)
    if stopped:
        raise SyncRefused("processing is stopped by a privacy request")
    if rate_limited(
        rate_bucket,
        connection.membership_id,
        limit=limit,
        window_seconds=SYNC_WINDOW_SECONDS,
    ):
        raise SyncRefused("sync rate limit reached")

    with tenant_transaction(connection.tenant_id):
        # One read of the pack and the applications, shared by all three.
        vouching = vouched_senders(connection.membership)
        allowed = allowed_senders(connection.membership, vouched=vouching)
        since = _cursor(connection) or tracking_since(connection.membership)
        unconfirmed = unconfirmed_senders(connection.membership, vouched=vouching)
        vouched = set(vouching)
        # Acting, not reading: full hosts, never the sender keys above. Taken
        # before the header loop on purpose -- anything it learns is
        # unconfirmed, and an unconfirmed sender is never a link target.
        links = link_hosts(connection.membership)
        # Only an address that really carries its account's tag. tagged()
        # returns a base address already holding a "+" unchanged, and a
        # REJECTS portal is given the base itself: counting either as a tag
        # made every stranger's mail to the plain address trusted (final
        # review I7). An account whose own REJECTS dropped the tag is still
        # recognised at `plain+tag` (final review M3): the portal may hold the
        # tag after all, and that mail is the only evidence that can say so.
        tags: dict[str, PortalAccount] = {}
        for owned in PortalAccount.objects.filter(student=connection.membership):
            if plain_of(owned):
                tags[owned.address.casefold()] = owned
            elif owned.tag_outcome == PortalForm.TagStatus.REJECTS and owned.tag:
                dropped = tagged(owned.address, owned.tag)
                if dropped != owned.address:
                    tags[dropped.casefold()] = owned
        awaiting = _awaiting_registration(connection.membership, timezone.now())
    # Never learned, whatever a tag mail claims to be: this connection's own
    # mailbox domain and every tagged address's own domain (fix round 1,
    # finding 2 -- alongside the free-mail denylist learnable_domain checks).
    own_domains = {sender_key(connection.address)} | {
        sender_key(account.address) for account in tags.values()
    }
    if not allowed or since is None:
        # Nothing to read means nothing to read -- not "read everything".
        _mark_synced(connection)
        return []

    try:
        # Fix round 1, finding 1: provider_for used to run here, ahead of this
        # try, so a connection row naming a provider this codebase doesn't
        # build a client for raised a bare ProviderError past every caller's
        # `except SyncRefused` (handle_work among them). Guarded like any
        # other provider failure.
        client = provider if provider is not None else provider_for(connection.provider, http=http)
        token = access_token_for(connection, http=http, secrets_client=secrets_client)
        headers = client.list_headers(
            access_token=token, since=since, senders=_search_for(connection, allowed)
        )
    except (GrantRefused, ProviderError) as error:
        # Only a lost grant flips the row and asks for a reconnect. A 429, a
        # 5xx or a dropped connection is the provider's passing problem, not
        # the student's: the row stays ACTIVE and Task 9's stale-inbox alert
        # covers an outage that lasts (final review I2). access_token_for's
        # own token-endpoint failures reach here the same way: a transient
        # one is oauth.py's GrantUnavailable, a ProviderError subclass, so it
        # is caught and ruled "not lost" by this same status check without a
        # second exception shape.
        lost = isinstance(error, GrantRefused) or error.status in (401, 403)
        if lost:
            with tenant_transaction(connection.tenant_id):
                # Conditional: request_deletion may have REVOKED the row since
                # this sync read it, and an erasing student must not be told to
                # reconnect.
                if MailboxConnection.objects.filter(
                    pk=connection.pk, status=MailboxConnection.Status.ACTIVE
                ).update(status=MailboxConnection.Status.ERROR):
                    connection.status = MailboxConnection.Status.ERROR
                    announce_lost_grant(connection)
        logger.warning(
            "mailbox sync failed for connection %s (grant lost: %s)", connection.id, lost
        )
        raise SyncRefused("provider refused" if lost else "provider unavailable") from error

    created: list[MailSignal] = []
    # ponytail: held for this run only, so a message whose first
    # classification fails is retried with the plain label card, not the
    # shared-portal one. Store the portal host on MailSignal if that matters.
    shared_portals: dict[UUID, tuple[str, int]] = {}
    # Fix round 1, finding 1: providers list newest first, so a naive inline
    # write let a newer untagged signal record STRIPS before an older tagged
    # signal in the same batch ever got to record KEEPS -- the weaker
    # evidence won on order alone. KEEPS is still recorded inline (nothing
    # ever outweighs it); a STRIPS candidate is only collected here and
    # written after the whole batch is read, once no KEEPS for that account
    # showed up anywhere in it.
    keeps_accounts: set[UUID] = set()
    strips_candidates: dict[UUID, PortalAccount] = {}
    newest = _cursor(connection)
    for header in headers:
        # First, before any branch below can `continue`: the cursor is the
        # newest message this connection has SEEN (models.py), kept or not.
        # Advanced only past kept mail, every sync re-listed all the dropped
        # mail since the last kept one -- weeks of a school inbox, every run.
        if newest is None or header.received_at > newest:
            newest = header.received_at
        account = next((tags[r] for r in header.recipients if r in tags), None)
        shared_portal: tuple[str, int] | None = None
        if account is not None:
            domain = sender_key(header.sender)
            if not domain:
                continue
            with tenant_transaction(connection.tenant_id):
                on_portal = list(
                    Application.objects.filter(
                        student=connection.membership,
                        portal_form__portal_host=account.portal_host,
                    ).values_list("id", flat=True)
                )
            # One application on this portal is the answer; several are a
            # question the card asks rather than a guess (final review I6b).
            application_id = on_portal[0] if len(on_portal) == 1 else None
            if len(on_portal) > 1:
                shared_portal = (account.portal_host, len(on_portal))
            trusted = not header.junk
            # The tag makes mail trusted enough to act on; an outcome also needs
            # the provider's verdict, from a sender the pack already vouches for.
            # DMARC proves who sent it, not which application it is about: a
            # domain vouched for ANOTHER application is not tied to this tag's
            # one (final review M3), or its letter could record this card's
            # outcome.
            sender_authenticated = (
                trusted
                and domain in allowed
                and allowed[domain] in (application_id, None)
                and domain not in unconfirmed
                and (header.authenticated or _verified(connection, client, token, header))
            )
            if domain not in allowed:
                if learnable_domain(domain, own_domains=own_domains):
                    with tenant_transaction(connection.tenant_id):
                        LearnedSender.objects.get_or_create(
                            student=connection.membership,
                            domain=domain,
                            defaults={
                                "tenant_id": connection.tenant_id,
                                "portal_host": account.portal_host,
                            },
                        )
                    logger.info("SenderLearned connection=%s domain=%s", connection.id, domain)
                    allowed[domain] = application_id
                    unconfirmed.add(domain)
                    # Learned this instant, so unconfirmed; the tag alone is
                    # the proof.
                # else: a free-mail domain or this student's own domain is
                # never remembered -- the message is still read above (this
                # signal still gets recorded), only the write is refused.
        elif header.junk:
            # Junk is read only for mail sent to a tag we issued.
            continue
        else:
            domain = matched_domain(header.sender, allowed)
            if not domain and connection.kind == MailboxConnection.Kind.APPLICATION:
                # An application inbox holds nothing but application mail, so
                # no sender filter applies (spec §3): every sender is read.
                # Still sender_key(), not the raw host: a From header is
                # attacker-controlled text, and sender_key is what bounds it to
                # a registrable domain (or "" for a reserved-suffix / IP-literal
                # / unregistrable host, which the `continue` below then skips).
                # Controller ruling, fix round 1 finding 1.
                domain = sender_key(header.sender)
            if not domain:
                # Never listed further, never fetched, never stored. This branch
                # is the product promise.
                continue
            application_id = allowed.get(domain)
            trusted = (
                domain in allowed
                and domain not in unconfirmed
                and (header.authenticated or _verified(connection, client, token, header))
            )
            sender_authenticated = trusted
        with tenant_transaction(connection.tenant_id):
            # The same message, seen by an EARLIER connection of this student
            # (a reconnect, a tier change): Graph's immutable ids survive both,
            # measured 2026-10-03. It is not news twice, and a label it already
            # earned is not paid for twice.
            earlier = (
                MailSignal.objects.filter(
                    connection__membership=connection.membership,
                    provider_message_id=header.message_id,
                )
                .exclude(connection=connection)
                .exclude(provider_message_id="")
                .order_by("-created_at")
                .first()
            )
            signal, is_new = MailSignal.objects.get_or_create(
                connection=connection,
                provider_message_id=header.message_id,
                defaults={
                    "tenant_id": connection.tenant_id,
                    "sender_domain": domain,
                    "received_at": header.received_at,
                    "application_id": application_id,
                    "trusted": trusted,
                    "sender_authenticated": sender_authenticated,
                    "label": earlier.label if earlier is not None else "",
                },
            )
            if is_new:
                created.append(signal)
                if earlier is None:
                    announce(signal)
                if shared_portal is not None:
                    shared_portals[signal.pk] = shared_portal
                # Spec §2a: what this portal does with the tag, measured by the
                # mail itself. Any mail to a tag says the tag survived; untagged
                # mail from a portal the student just registered on says it was
                # stripped. record_tag_outcome keeps the first answer only.
                if account is not None:
                    if not record_tag_outcome(account, PortalForm.TagStatus.KEEPS):
                        restore_tag(account)
                    keeps_accounts.add(account.pk)
                elif (registering := awaiting.get(domain)) is not None and (
                    registering.registered_at is not None
                    and header.received_at >= registering.registered_at
                ):
                    strips_candidates[registering.pk] = registering

    # Fix round 1, finding 1 (continued): now that the whole batch has been
    # read, a candidate is written only for an account this batch never also
    # saw KEEPS for.
    for pk, registering in strips_candidates.items():
        if pk in keeps_accounts:
            continue
        with tenant_transaction(connection.tenant_id):
            record_tag_outcome(registering, PortalForm.TagStatus.STRIPS)

    if connection.tier == MailboxConnection.Tier.CONTENT:
        with tenant_transaction(connection.tenant_id):
            # Every unlabelled signal under the ceiling except this run's own:
            # attempts == 0 included, so a signal a previous sync recorded and
            # never got to classify (killed mid-run, final review I1) is read.
            # Fix round 1, finding 1: oldest first and capped, so a backlog
            # built up during a classify outage cannot turn one sync into an
            # unbounded run of provider body-fetch calls.
            retryable = list(
                MailSignal.objects.filter(
                    connection=connection,
                    label="",
                    classify_attempts__lt=MAX_CLASSIFY_ATTEMPTS,
                )
                .exclude(pk__in=[signal.pk for signal in created])
                .order_by("received_at")[:MAX_RETRIES_PER_SYNC]
            )
        # A signal that inherited its label from an earlier connection was
        # classified, and acted on if it could, there.
        fresh = sorted(
            (signal for signal in created if not signal.label),
            key=lambda signal: signal.received_at,
            reverse=True,
        )
        for signal in (*fresh[:MAX_CLASSIFY_PER_SYNC], *retryable):
            if not _classify(
                connection,
                client,
                token,
                signal,
                links,
                vouched=vouched,
                shared_portal=shared_portals.get(signal.pk),
            ):
                break

    _mark_synced(connection, newest)
    return created


def _mark_synced(connection: MailboxConnection, newest: datetime | None = None) -> None:
    """A sync completed, the nothing-to-read one included: stamp it, move the
    cursor to the newest message seen, and clear the stale-inbox alert -- a
    completed sync is proof the inbox is checked again (Task 9). Otherwise one
    alert on a connection that keeps reading nothing is never raised again
    (fix round 1, finding 2)."""
    fields = ["last_sync_at", "health_alerted_at"]
    with tenant_transaction(connection.tenant_id):
        connection.last_sync_at = timezone.now()
        connection.health_alerted_at = None
        if newest is not None:
            connection.sync_cursor = newest.astimezone(UTC).isoformat()
            fields.append("sync_cursor")
        connection.save(update_fields=fields)


def _verified(
    connection: MailboxConnection, client: MailboxProvider, token: str, header: MessageHeader
) -> bool:
    """Ask the provider whether one KEPT message really came from its domain.

    Only where the listing could not say (header.authenticated is False) and
    the grant can read the verdict: Microsoft on the content tier
    (internetMessageHeaders needs Mail.Read). Never for a stranger's mail --
    the caller asks only about a domain the student's own pack or applications
    already justified reading. A provider failure is "not verified", which
    costs an automatic action and nothing else.
    """
    if (
        connection.provider != MailboxConnection.Provider.MICROSOFT
        or connection.tier != MailboxConnection.Tier.CONTENT
    ):
        return False
    try:
        return client.delivery_verified(
            access_token=token, message_id=header.message_id, sender=header.sender
        )
    except ProviderError as error:
        logger.info(
            "could not read the delivery verdict on connection %s: %s", connection.id, error
        )
        return False


def _awaiting_registration(student: Membership, now: datetime) -> dict[str, PortalAccount]:
    """The sender keys of portals whose registration mail is still due (spec §2a).

    Before a portal's sender is known, "untagged mail from that portal" can
    only mean mail from a domain the portal's own row names: its host, or one
    of its curated sender_domains -- both already read under rule 2. A vendor
    domain nobody has recorded matches nothing here; the dock asks the student
    for it instead (ext_api.registration). Read inside the caller's tenant
    transaction.
    """
    # A key is evidence about ONE portal only when no other portal host of
    # this student claims it: portal.uni-bonn.de and apply.uni-bonn.de both
    # key as uni-bonn.de. Fix round 1 dropped a key two AWAITING accounts
    # shared; final review M2 widens that to every portal host the student
    # has -- an account (measured or not) or an application with no address
    # issued -- since mail from any of them is read all the same, and plain
    # mail from the student's other portal at the same university is not this
    # one's registration mail. Order-independent: a key is kept only when the
    # set of hosts claiming it is exactly this account's own.
    hosts = set(PortalAccount.objects.filter(student=student).values_list("portal_host", flat=True))
    hosts.update(
        host
        for host in Application.objects.filter(student=student).values_list(
            "portal_form__portal_host", flat=True
        )
        if host
    )
    claims: dict[str, set[str]] = {}
    curated = PortalForm.objects.filter(portal_host__in=hosts).values_list(
        "portal_host", "sender_domains"
    )
    entries = [(host, host) for host in hosts]
    entries += [(host, domain) for host, domains in curated for domain in domains or ()]
    for host, entry in entries:
        if key := _key(str(entry)):
            claims.setdefault(key, set()).add(host)
    awaiting: dict[str, PortalAccount] = {}
    accounts = PortalAccount.objects.filter(
        student=student,
        tag_outcome=PortalForm.TagStatus.UNKNOWN,
        registered_at__gte=now - REGISTRATION_MAIL_WINDOW,
    )
    for account in accounts:
        if not awaits_registration_mail(account, now):
            continue
        for key, claimants in claims.items():
            if claimants == {account.portal_host}:
                awaiting[key] = account
    return awaiting
