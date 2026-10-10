"""The student's own mailbox, as two rows and nothing else.

What is deliberately absent is the point of the module: no subject, no body, no
attachment, no address other than the connected mailbox's own, and no refresh
token -- that lives in Secrets Manager (see secrets.py) because a database
backup is not a place to keep a live grant on someone's mail.
"""

from __future__ import annotations

from uuid import uuid4

from django.db import models

from apps.tenancy.models import Membership, TenantScopedModel

#: A message classification is retried on the next two syncs after it first
#: fails, and shown as a bare "open the message" card on the third. Here, not in
#: sync.py, so the web views that ask "will anything read this?" need not
#: import the sync and its provider/OpenAI graph.
MAX_CLASSIFY_ATTEMPTS = 3


class MailboxConnection(TenantScopedModel):
    """One student's grant on one provider.

    ``tier`` is CONTENT by default: the owner's 2026-09-15 decision is that the
    content tier is what the agreed flow needs, so it is what the connect screen
    offers, with METADATA as the reduced option for a student who declines.
    """

    class Provider(models.TextChoices):
        GOOGLE = "GOOGLE", "Google"
        MICROSOFT = "MICROSOFT", "Microsoft"

    class Tier(models.TextChoices):
        METADATA = "METADATA", "Headers only"
        CONTENT = "CONTENT", "Headers and body"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"
        ERROR = "ERROR", "Needs reconnecting"

    class Kind(models.TextChoices):
        #: The student's everyday inbox: only pack and tagged mail is read.
        EVERYDAY = "EVERYDAY", "Everyday inbox"
        #: An inbox the student created for applications: everything is read.
        APPLICATION = "APPLICATION", "Application inbox"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="mailbox_connections"
    )
    provider = models.CharField(max_length=20, choices=Provider.choices)
    #: The address the student connected. Also what Membership.application_email
    #: is set to, so the CV and the portal fields agree with the inbox.
    address = models.CharField(max_length=320)
    tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.CONTENT)
    #: Default EVERYDAY, so a connection that never says widens nothing.
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.EVERYDAY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    #: ISO-8601 instant of the newest message this connection has seen. Not a
    #: provider history id: Gmail's metadata scope forbids the `q` parameter and
    #: Microsoft's Mail.ReadBasic forbids $search, so one timestamp is the only
    #: cursor both providers can honour. Empty means "never synced".
    sync_cursor = models.CharField(max_length=40, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    #: Set when a stale-inbox alert was raised, cleared by the next successful
    #: sync, so one outage is one alert.
    health_alerted_at = models.DateTimeField(null=True, blank=True)
    #: The provider's push subscription (push.py), empty when there is none.
    #: Only the id: its clientState is derived, never stored.
    push_subscription_id = models.CharField(max_length=200, blank=True)
    push_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="mailbox_connection_tenant_id_uniq"
            ),
            #: One ACTIVE connection per provider per student. Partial, so a
            #: revoked connection stays as history and does not block a
            #: reconnection -- which is the ordinary case after a refresh
            #: failure.
            models.UniqueConstraint(
                fields=("membership", "provider"),
                condition=models.Q(status="ACTIVE"),
                name="mailbox_one_active_connection_per_provider",
            ),
        ]
        indexes = [
            #: The Graph webhook's lookup, run before clientState is checked on
            #: an unauthenticated POST (security review L2). Partial: most
            #: connections have no subscription.
            models.Index(
                fields=("push_subscription_id",),
                condition=~models.Q(push_subscription_id=""),
                name="mailbox_push_subscription_idx",
            ),
        ]


class MailSignal(TenantScopedModel):
    """A message from an institution in this student's pack arrived.

    The row says who wrote and when, never what they said. A label appears only
    on the content tier, and even then the message's text is read, classified
    and dropped -- classify.py returns a verdict, not a body.
    """

    class Label(models.TextChoices):
        RECEIVED = "RECEIVED", "Application received"
        DOCUMENT_REQUEST = "DOCUMENT_REQUEST", "A document was requested"
        INTERVIEW = "INTERVIEW", "Interview invitation"
        DECISION = "DECISION", "A decision"
        VERIFICATION = "VERIFICATION", "Verify your address"
        FEE = "FEE", "A fee is due"
        OTHER = "OTHER", "Something else"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    connection = models.ForeignKey(
        MailboxConnection, on_delete=models.CASCADE, related_name="signals"
    )
    provider_message_id = models.CharField(max_length=200)
    sender_domain = models.CharField(max_length=253)
    received_at = models.DateTimeField()
    application = models.ForeignKey(
        "portals.Application",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mail_signals",
    )
    label = models.CharField(max_length=30, choices=Label.choices, blank=True)
    #: Whether this message may act (spec §3, acting is stricter than
    #: reading): sent to a tagged address and not from Junk, or authenticated
    #: by the provider from a sender that is not an unconfirmed learned one.
    #: Kept so a later retry of its classification acts under the same rule.
    trusted = models.BooleanField(default=False)
    #: The provider's own delivery verdict passed (DMARC pass or bestguesspass)
    #: for a sender the pack or an application vouches for. Stricter than
    #: `trusted`: a tag alone trusts mail, and a leaked tag must never write an
    #: application's outcome (portals/outcome.py::record_from_mail).
    sender_authenticated = models.BooleanField(default=False)
    #: How many times classification has been tried and failed for this
    #: message. A successful classification never touches it. Once it reaches
    #: MAX_CLASSIFY_ATTEMPTS the student is shown a bare "open the
    #: message" card instead of being retried forever.
    classify_attempts = models.PositiveSmallIntegerField(default=0)
    #: DOCUMENT_REQUEST on the content tier: the document's name as the mail
    #: words it (<= 120 characters) and its deadline. Never the mail's text.
    document_name = models.CharField(max_length=120, blank=True)
    document_due = models.DateField(null=True, blank=True)
    #: Jev's one reading of this mail (mailbox/decision_reader.py): the
    #: probabilities, whether it was a decision, whether Jev was unavailable.
    #: About the person's mail, so REDACT. {} for a mail never read.
    decision_reading = models.JSONField(default=dict, blank=True)
    #: What that reading says this card's outcome is (an Application.Outcome
    #: value or ""). Recorded on the Application only from trusted mail and
    #: measured bars (portals/outcome.py); otherwise shown for a person to confirm.
    outcome = models.CharField(max_length=24, blank=True)
    #: Code-verified quotes: the conditions of a conditional offer.
    outcome_conditions = models.JSONField(default=list, blank=True)
    #: The second decision in a two-decision letter (admitted, scholarship
    #: declined): the funding's, shown on the funding line of the card.
    funding_outcome = models.CharField(max_length=24, blank=True)
    #: DECISION: the other programme a letter offers a place on (spec §4,
    #: owner 2026-10-04), as the letter names it. Accept turns it into a card;
    #: Accept and Ignore both set offer_handled_at, which ends the Needs item.
    offered_programme = models.CharField(max_length=120, blank=True)
    offer_handled_at = models.DateTimeField(null=True, blank=True)
    #: INTERVIEW: when the interview is, if the mail states it (spec §8).
    interview_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="mailbox_signal_tenant_id_uniq"),
            #: The sync is re-runnable by construction: a message already seen
            #: is a conflict, not a second signal and not a second notification.
            #: Partial: erasure blanks every id to "" at once, and two blanks on
            #: one connection must not collide (final review C1).
            models.UniqueConstraint(
                fields=("connection", "provider_message_id"),
                condition=~models.Q(provider_message_id=""),
                name="mailbox_signal_message_uniq",
            ),
        ]

    #: Nothing but the student will ever read this message: the metadata tier
    #: reads no body, and a message whose classification gave up is not retried.
    #: `nobody_reads` is the same test on one row (select_related "connection").
    NOBODY_READS = models.Q(connection__tier="METADATA") | models.Q(
        classify_attempts__gte=MAX_CLASSIFY_ATTEMPTS
    )

    @property
    def nobody_reads(self) -> bool:
        return (
            self.connection.tier == MailboxConnection.Tier.METADATA
            or self.classify_attempts >= MAX_CLASSIFY_ATTEMPTS
        )


class LearnedSender(TenantScopedModel):
    """A sender domain first seen on mail to one of this student's tags.

    Per student and never shared: a tag can leak, and a scammer's domain learned
    from it must not become trusted for anyone else. Read from the moment it is
    learned; trusted only once the student confirms one message from it.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="learned_senders"
    )
    domain = models.CharField(max_length=253)
    #: The portal whose tag the first message was sent to.
    portal_host = models.CharField(max_length=253)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="learnedsender_tenant_id_uniq"),
            #: Partial for the same reason as mailbox_signal_message_uniq:
            #: erasure blanks every domain to "".
            models.UniqueConstraint(
                fields=("student", "domain"),
                condition=~models.Q(domain=""),
                name="learnedsender_one_per_domain",
            ),
        ]
