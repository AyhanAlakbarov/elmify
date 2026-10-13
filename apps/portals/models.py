"""Portal form maps.

PortalForm and FieldMap describe a public third-party form. They carry no
tenant or student data and are deliberately not TenantScopedModel -- see the
Data model section of
docs/superpowers/specs/2026-08-27-phase3-portal-execution-design.md.
"""

from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import models
from django.utils import timezone

from apps.tenancy.models import Membership, TenantScopedModel


def zone_named(name: str) -> ZoneInfo | None:
    """The IANA zone `name` (Application.deadline_timezone), or None when it is
    blank or not a zone this machine knows."""
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


class PortalForm(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    portal_host = models.CharField(max_length=253)
    form_key = models.CharField(max_length=200)
    #: The page a fill starts on. Held here rather than passed per application
    #: because it is a property of the form version, not of the student.
    form_url = models.URLField(max_length=500, blank=True)
    #: §5.2: consultant review of the first prepared application on each new
    #: portal. Cleared by request_first_portal_review once that task exists.
    review_required = models.BooleanField(default=True)
    #: A selector present only when the portal is showing its login page.
    #: Empty means "this portal's expiry signal has not been configured", which
    #: is treated as never-expired -- the opposite default would reauthenticate
    #: on every step of every portal.
    login_marker = models.CharField(max_length=200, blank=True)
    #: A selector present only when the portal is asking for a second factor.
    mfa_marker = models.CharField(max_length=200, blank=True)
    #: Page text or URL fragments that appear only after a successful submit.
    #: Reaches the extension through the packet, where
    #: `content/page_signals.ts::detectConfirmation` matches them to write the
    #: SUBMITTED step -- the handshake the spec's third box describes.
    #:
    #: NULL, not [], for a portal nobody has configured. The extension reads
    #: null as "this check is off"; an empty list would read as "these are the
    #: markers and none matched", which is the same answer an unsubmitted page
    #: gives, so an unconfigured portal would be indistinguishable from a
    #: student who never pressed Submit. Learned by a human watching one real
    #: submission, never guessed -- a wrong marker writes SUBMITTED for an
    #: application that was never sent.
    confirmation_markers = models.JSONField(null=True, blank=True, default=None)
    #: Whether automated challenge resolution is approved for THIS portal.
    #: Default False and deliberately not a global setting: CLAUDE.md's Phase 3
    #: rules make the resolution service a per-portal decision taken after the
    #: portal-terms and legal gates, and the record of that decision is an
    #: audit artifact under §5.5. An unapproved portal gets the consultant
    #: path, which is the MVP behaviour §5.1 describes.
    resolution_approved = models.BooleanField(default=False)

    #: The domains this portal actually sends mail from, learned from the first
    #: student whose confirmation matched one. NOTHING IN THIS PLAN WRITES IT
    #: -- see "What this plan deliberately does not build".
    #: Platform-shared like the rest of this model: a fact about the portal,
    #: never about a student.
    #:
    #: A list rather than one value because a portal mails from several -- a
    #: transactional vendor for receipts, the university's own for decisions.
    sender_domains = models.JSONField(default=list, blank=True)
    discovered_at = models.DateTimeField(auto_now_add=True)

    class TermsPosture(models.TextChoices):
        """What this portal's own terms say about a tool filling its form.

        Read once per portal and recorded, because the answer is a fact about a
        third party rather than a judgement we can re-derive. A sample of seven
        portals read 2026-09-15 (spec, owner decision 9) found none prohibiting
        automated tools or autofill in the applicant's own session, and every
        one of them making the account personal -- so PERSONAL_ACCOUNT_ONLY is
        the common case and it does not block anything here. Only an explicit
        prohibition does.
        """

        SILENT = "SILENT", "Terms say nothing about automation"
        PERSONAL_ACCOUNT_ONLY = "PERSONAL_ACCOUNT_ONLY", "Personal account, no credential sharing"
        AGENT_CHANNEL = "AGENT_CHANNEL", "A sanctioned agent route exists"
        PROHIBITS_AUTOMATION = "PROHIBITS_AUTOMATION", "Automated tools prohibited"

    #: Default SILENT: an unread portal is served normally. Only
    #: PROHIBITS_AUTOMATION changes behaviour, and it makes the portal
    #: kit-only -- the cost of ignoring an explicit prohibition lands on the
    #: student's application, not on us.
    terms_posture = models.CharField(
        max_length=30, choices=TermsPosture.choices, default=TermsPosture.SILENT
    )
    terms_url = models.URLField(max_length=500, blank=True)
    terms_read_on = models.DateField(null=True, blank=True)

    class TagStatus(models.TextChoices):
        """Whether this portal keeps a +tag in the address it mails (spec §2a).

        Shared by every tenant, unlike a learned sender: a wrong status can only
        cause the safe fallback (the plain address and sender matching), never an
        action.
        """

        UNKNOWN = "UNKNOWN", "Not yet measured"
        KEEPS = "KEEPS", "Keeps the tag"
        REJECTS = "REJECTS", "Rejects + at the form"
        STRIPS = "STRIPS", "Accepts but mails the plain address"

    tag_status = models.CharField(
        max_length=10, choices=TagStatus.choices, default=TagStatus.UNKNOWN
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("portal_host", "form_key"), name="portal_form_host_key_uniq"
            ),
            #: Set by hand (set_tag_status); an unknown value must be refused by
            #: the database, not only by the command's choices.
            models.CheckConstraint(
                condition=models.Q(tag_status__in=("UNKNOWN", "KEEPS", "REJECTS", "STRIPS")),
                name="portal_form_tag_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    terms_posture__in=(
                        "SILENT",
                        "PERSONAL_ACCOUNT_ONLY",
                        "AGENT_CHANNEL",
                        "PROHIBITS_AUTOMATION",
                    )
                ),
                name="portal_form_terms_posture_valid",
            ),
        ]


class FieldMap(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    portal_form = models.ForeignKey(PortalForm, on_delete=models.CASCADE, related_name="field_maps")
    version = models.PositiveIntegerField()
    #: [{"profile_field": "personal.given_name", "action": {...ActionInput...}}]
    entries = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    #: Which tenant's snapshot produced this map, or NULL for one the PLATFORM
    #: verified -- a server-driven browser that observed the real form, or a
    #: human. NULL rows are shared by every tenant, exactly as every row was
    #: before this column existed.
    #:
    #: It exists because a snapshot is asserted by a client. The selectors in
    #: it decide where a student's verified values get typed, and nothing on
    #: the server can check them against the real page: read-back reads the
    #: same selector it typed into, so a wrong-but-consistent map verifies
    #: clean. Shared, that let one tenant's student choose where every other
    #: tenant's students' identity fields go. Scoped, the blast radius of a
    #: hostile snapshot is the tenant it came from.
    #:
    #: Deliberately NOT a TenantScopedModel field and deliberately not
    #: RLS-covered: this table is read cross-tenant on purpose (that is what a
    #: NULL row is for), so the manager must not filter it. The scope is
    #: enforced by current_for's argument, which is why that argument has no
    #: default -- a caller that forgets it would silently get shared-only maps.
    learned_by_tenant = models.ForeignKey(
        "tenancy.Agency", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("portal_form", "version"), name="field_map_form_version_uniq"
            )
        ]

    def supersede(self) -> None:
        self.superseded_at = timezone.now()
        self.save(update_fields=["superseded_at"])

    @classmethod
    def current_for(cls, portal_form: PortalForm, tenant_id: UUID | None) -> FieldMap | None:
        """This tenant's own current map, else the platform's shared one.

        A tenant that has learned a form from its own students' browsers uses
        that; everyone else falls back to the NULL-scoped row. Two queries
        rather than one ordered query, because "prefer mine, else shared" is
        not expressible as an ordering that also survives a superseded row on
        one side only.
        """
        scoped = None
        if tenant_id is not None:
            scoped = (
                cls.objects.filter(
                    portal_form=portal_form,
                    learned_by_tenant_id=tenant_id,
                    superseded_at__isnull=True,
                )
                .order_by("-version")
                .first()
            )
        return scoped or (
            cls.objects.filter(
                portal_form=portal_form,
                learned_by_tenant__isnull=True,
                superseded_at__isnull=True,
            )
            .order_by("-version")
            .first()
        )


class RecoveryEvent(models.Model):
    """What recovered, on which portal, and between which two field maps.

    Platform-scoped like PortalForm and FieldMap, and for the same reason: it
    names a public form and two of its versions and carries no student data.
    The tenant-side record is the ApplicationStep row written beside it. Keeping
    this table platform-wide is what makes "which portals are drifting" one
    query instead of a loop over every tenant.
    """

    class Kind(models.TextChoices):
        SELECTOR_MISS = "SELECTOR_MISS", "Selector miss, re-learned"
        SESSION_EXPIRED = "SESSION_EXPIRED", "Session expired, reauthenticated"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    portal_form = models.ForeignKey(
        PortalForm, on_delete=models.CASCADE, related_name="recovery_events"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    page_url = models.URLField(max_length=500, blank=True)
    replaced_field_map = models.ForeignKey(
        FieldMap, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    replacement_field_map = models.ForeignKey(
        FieldMap, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: The field that missed, never a value. This table is shared across
    #: tenants, so a student value here would be the leak FieldMap is
    #: carefully designed to avoid.
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class Application(TenantScopedModel):
    class State(models.TextChoices):
        PREPARING = "PREPARING", "Preparing"
        READY_TO_SUBMIT = "READY_TO_SUBMIT", "Ready to submit"
        SUBMITTED = "SUBMITTED", "Submitted"
        CONFIRMED = "CONFIRMED", "Confirmed"
        BLOCKED_MISSING_FACT = "BLOCKED_MISSING_FACT", "Blocked: missing fact"
        BLOCKED_PERSONAL_ACTION = "BLOCKED_PERSONAL_ACTION", "Blocked: personal action"
        BLOCKED_CHALLENGE = "BLOCKED_CHALLENGE", "Blocked: challenge"
        BLOCKED_PORTAL_ERROR = "BLOCKED_PORTAL_ERROR", "Blocked: portal error"

    class Outcome(models.TextChoices):
        ADMITTED = "ADMITTED", "Admitted"
        ADMITTED_CONDITIONAL = "ADMITTED_CONDITIONAL", "Admitted with conditions"
        WAITLISTED = "WAITLISTED", "Waitlisted"
        REJECTED = "REJECTED", "Not admitted"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    class OutcomeSource(models.TextChoices):
        MAIL = "MAIL", "Email"
        PORTAL = "PORTAL", "Portal"
        PERSON = "PERSON", "Recorded by a person"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="applications")
    program_id = models.UUIDField()
    #: NULL while nobody knows the programme's application portal (spec §7):
    #: the card offers "Open programme page" and a counsellor task asks for it.
    #: Every path that dereferences it is guarded (plan Task 4's table).
    portal_form = models.ForeignKey(PortalForm, null=True, blank=True, on_delete=models.PROTECT)
    #: The pack candidate this application was added from; the tenant copy the
    #: card reads its name, institution, fee and funding from. SET_NULL: the
    #: candidate is a recommendation, the application outlives it.
    candidate = models.ForeignKey(
        "funding.RecommendationCandidate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    state = models.CharField(max_length=30, choices=State.choices, default=State.PREPARING)
    #: The roadmap item a human must close before this application moves
    #: again. Nullable and cleared on resume, so "blocked on a person" is one
    #: indexed query rather than a scan of ApplicationStep rows.
    exception_item = models.ForeignKey(
        "concierge.RoadmapItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: The roadmap item the reminder ladder hangs its notifications on, created
    #: on the first rung and reused by the rest. Separate from exception_item:
    #: that one means "blocked on a person", this one means "this is due".
    #: Nullable because most applications never reach a rung.
    reminder_item = models.ForeignKey(
        "concierge.RoadmapItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: When this application is due. Nullable because most applications enter
    #: the pipeline before anyone has read a date off the programme's page, and
    #: no catalog column holds one yet (2026-09-15 discovery audit).
    deadline = models.DateTimeField(null=True, blank=True)
    #: IANA name of the zone the portal states its deadline in, e.g.
    #: "Europe/Berlin". Stored beside the instant because the reminder ladder
    #: and the kit both render it to the student's own zone, and "1 December"
    #: read in the wrong zone is a day late.
    deadline_timezone = models.CharField(max_length=64, blank=True)
    #: The kit's catalogue-derived parts, copied here by the worker
    #: (`packets.capture_requirements`) because the web tier that serves the
    #: kit holds no grant on the shared catalogue. Empty until captured, and
    #: the kit shows empty then -- the same degrade as an unread programme.
    #: `requirements`: the programme's REQUIRED ProgramStatement texts.
    #: `your_actions`: serialised funding.requirements.RequirementItem dicts.
    kit_requirements = models.JSONField(default=list, blank=True)
    kit_your_actions = models.JSONField(default=list, blank=True)
    kit_letter_cycle = models.CharField(max_length=20, blank=True)
    #: How this programme is applied for, copied when the card is made (lanes
    #: spec §3.1; apps/portals/route_snapshot.py). {} = no route known yet.
    route_snapshot = models.JSONField(default=dict, blank=True)
    #: Start application was pressed (spec §7): the card leaves "To start".
    started_at = models.DateTimeField(null=True, blank=True)
    #: The card's own name when it has no candidate: a place offered for another
    #: programme, accepted from a decision letter (spec §4). Redacted on erasure:
    #: a non-empty name says an institution offered this person a place.
    name = models.CharField(max_length=300, blank=True)
    #: A trusted DECISION mail arrived (spec §4). Moves the card to Decision.
    decision_available_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=24, choices=Outcome.choices, blank=True)
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)
    outcome_source = models.CharField(max_length=10, choices=OutcomeSource.choices, blank=True)
    #: The signal an automatic outcome came from -- never the letter's text.
    outcome_evidence = models.ForeignKey(
        "mailbox.MailSignal", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: The motivation letter for this application, while one is being worked on
    #: by the document worker: "" (nothing pending), QUEUED (being written),
    #: CHECKING (approval being checked) or REFUSED (the engine declined; the
    #: reason is `letter_note`, one of documents.writing.LETTER_NOTES -- a code,
    #: never text from the letter or the page).
    letter_state = models.CharField(max_length=10, blank=True, default="")
    letter_note = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def where(self) -> str:
        """Where this application happens, for a sentence: the portal's host, or
        the programme's name while no portal is known (spec §7)."""
        if self.portal_form_id is not None:
            assert self.portal_form is not None
            return self.portal_form.portal_host
        if self.candidate_id is not None:
            assert self.candidate is not None
            return self.candidate.program_name
        return self.name or "your application"

    @property
    def title(self) -> str:
        """What the card is headed with: the programme's or scholarship's name,
        then the card's own name (an accepted offer), and only then where it
        happens -- an accepted offer is titled by its programme, never by its
        portal host (ruling F4)."""
        if self.candidate_id is not None:
            assert self.candidate is not None
            return self.candidate.program_name
        return self.name or self.where

    def next_step_sequence(self) -> int:
        """Next audit-trail sequence number.

        # ponytail: read-then-write. It takes two workers on one application
        # to race, and there is one portal task by construction
        # (PortalDesiredCount maxes at 1). Revisit if that ever changes.
        """
        last = self.steps.order_by("-sequence").values_list("sequence", flat=True).first()
        return (last or 0) + 1

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="portal_app_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("student", "candidate"), name="portal_app_one_per_candidate"
            ),
            #: A person's correction reaches these columns (spec §4); an unknown
            #: value must be refused by the database, not only by the view.
            models.CheckConstraint(
                condition=models.Q(
                    outcome__in=(
                        "",
                        "ADMITTED",
                        "ADMITTED_CONDITIONAL",
                        "WAITLISTED",
                        "REJECTED",
                        "WITHDRAWN",
                    )
                ),
                name="portal_app_outcome_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(outcome_source__in=("", "MAIL", "PORTAL", "PERSON")),
                name="portal_app_outcome_source_valid",
            ),
        ]


class ApplicationLink(TenantScopedModel):
    """One card linked to another: an award applied for separately and the
    programme it pays for (lanes spec §3.2, §4). ``WAITS_FOR``: ``from_app``
    cannot proceed until ``to_app`` has its outcome. Plan 1a writes only
    ``LINKED_ONLY``; the order arrives with the award facts (plan 1b)."""

    class Order(models.TextChoices):
        WAITS_FOR = "WAITS_FOR", "Waits for"
        PARALLEL = "PARALLEL", "In parallel"
        LINKED_ONLY = "LINKED_ONLY", "Linked"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    from_app = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="links_out")
    to_app = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="links_in")
    order = models.CharField(max_length=12, choices=Order.choices, default=Order.LINKED_ONLY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("from_app", "to_app"), name="portal_link_pair_uniq"),
            models.CheckConstraint(
                condition=~models.Q(from_app=models.F("to_app")), name="portal_link_not_self"
            ),
            models.CheckConstraint(
                condition=models.Q(order__in=("WAITS_FOR", "PARALLEL", "LINKED_ONLY")),
                name="portal_link_order_valid",
            ),
        ]


class PortalAccount(TenantScopedModel):
    """The address one student registered with on one portal host.

    Per host, not per application: one Swedish or uni-assist account holds many
    applications. `address` is fixed when first issued, because it is what the
    portal now holds -- a later change of inbox does not change it.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="portal_accounts"
    )
    portal_host = models.CharField(max_length=253)
    #: Random, lowercase letters and digits. Only this portal is given it.
    tag = models.CharField(max_length=16)
    address = models.CharField(max_length=320, blank=True)
    #: When the extension first typed this address into the portal and the page
    #: held it (spec §2a) -- the registration, as near as the platform can see
    #: it. Opens the registration-mail window, and from then on `address` is
    #: what the portal holds. (A shared status never re-bases an issued
    #: address at all, registered or not: tags.portal_address.)
    registered_at = models.DateTimeField(null=True, blank=True)
    #: What THIS account measured about the tag, whatever the shared status
    #: says. The first observation wins; REJECTS also drops the tag from
    #: `address` (tags.record_tag_outcome).
    tag_outcome = models.CharField(
        max_length=10, choices=PortalForm.TagStatus.choices, default=PortalForm.TagStatus.UNKNOWN
    )
    #: The REJECTS came from the student's own "use my plain address" button.
    #: Mail to the tag may correct any other REJECTS (tags.restore_tag), never
    #: this one: the student is the authority on their own form.
    tag_dropped_by_student = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="portalaccount_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("student", "portal_host"), name="portalaccount_one_per_host"
            ),
            models.CheckConstraint(
                condition=models.Q(tag_outcome__in=("UNKNOWN", "KEEPS", "REJECTS", "STRIPS")),
                name="portalaccount_tag_outcome_valid",
            ),
        ]


class ApplicationStep(TenantScopedModel):
    class Kind(models.TextChoices):
        """The §5.5 trail's vocabulary.

        Deliberately not a database constraint and not ``choices=`` on the
        column: rows written before this enum existed carry bare strings, and
        every writer in this app passes a literal. This is the list the HTTP
        layer validates against, so the trail cannot grow a kind nobody named.
        """

        PACKET = "PACKET", "Packet prepared"
        FILL = "FILL", "Fields filled"
        READ_BACK = "READ_BACK", "Values read back"
        CHALLENGE = "CHALLENGE", "Challenge met by the student"
        SUBMITTED = "SUBMITTED", "Submitted by the student"
        STATUS = "STATUS", "Portal status read"
        SIGNUP = "SIGNUP", "Account created by the student"
        VERIFY = "VERIFY", "Verification link followed"
        ESCALATION = "ESCALATION", "Escalated to a human"
        RECOVERY = "RECOVERY", "Recovered without a human"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="steps")
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=30)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="portal_step_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("application", "sequence"), name="portal_step_app_sequence_uniq"
            ),
        ]


class ExtensionPairing(TenantScopedModel):
    """One browser installation, bound to one membership.

    Tenant-scoped because it names a student. The two secrets it mediates --
    the one-time pairing code and the long-lived device token -- are stored as
    SHA-256 hex digests and never in the clear, so this table is not a
    credential store even though it is the whole authentication surface of the
    extension API.

    One row covers the pairing's whole life: it is created pending, holding a
    code hash and an expiry, and redemption fills in the token hash and the
    installation id under a single conditional UPDATE. A second table for
    pending codes would be a second place to forget to expire.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="extension_pairings"
    )
    #: SHA-256 of the one-time code. Cleared on redemption, so a leaked code is
    #: worth nothing once used, and a pending pairing is the only row it matches.
    code_hash = models.CharField(max_length=64, blank=True)
    code_expires_at = models.DateTimeField(null=True, blank=True)
    #: SHA-256 of the device token. Indexed: it is the lookup key on every
    #: single extension request.
    token_hash = models.CharField(max_length=64, blank=True, db_index=True)
    #: The extension's own installation id. Identifies the browser, not the
    #: person, and exists so a student can tell two of their machines apart on
    #: the revoke list.
    installation_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="portal_pairing_tenant_id_uniq")
        ]


class DeviceAction(TenantScopedModel):
    """One thing the extension should do next, delivered once and expiring.

    The payload is short-lived on purpose: an OPEN_VERIFICATION_URL carries a
    portal's verification link, which is a bearer credential for the student's
    own portal account. It is cleared the moment the action completes, and the
    row survives only to say that it happened.
    """

    class Kind(models.TextChoices):
        OPEN_VERIFICATION_URL = "OPEN_VERIFICATION_URL", "Open a verification link"
        TYPE_CODE = "TYPE_CODE", "Type a verification code"
        READ_PORTAL_STATUS = "READ_PORTAL_STATUS", "Read the portal's status page"
        OPEN_UPLOAD_PAGE = "OPEN_UPLOAD_PAGE", "Open the portal's upload page"
        START_FILL = "START_FILL", "Open the portal and start filling"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="device_actions"
    )
    application = models.ForeignKey(
        Application, null=True, blank=True, on_delete=models.CASCADE, related_name="device_actions"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="portal_action_tenant_id_uniq")
        ]


class Rung(models.TextChoices):
    """The five reminder points, named rather than numbered.

    A symbolic value, never a raw hour count: changing the cadence must not
    silently re-key the ReminderSent rows already written under the old one.
    """

    D14 = "D14", "14 days"
    D7 = "D7", "7 days"
    D3 = "D3", "3 days"
    D1 = "D1", "1 day"
    H6 = "H6", "6 hours"


class ReminderSent(TenantScopedModel):
    """One row per rung reached, not one row per message sent.

    The unique constraint is the idempotency mechanism, not an `.exists()`
    check in the sweep: the check races two sweeps against each other, the
    constraint cannot. `_remind_one` writes a row for every rung `due` at
    once (not just the one it notified), because an application that first
    appears five days before its deadline has both D14 and D7 due together --
    without every due rung recorded, the next sweep would send the D14
    message an hour after the D7 one, a confusing message ordered backwards.
    `sent` is what tells the two kinds of row apart: True on the single row
    for the rung that was actually notified, False on the rest, recorded only
    to stop that stale rung firing later. `ReminderSent.objects.filter(sent=True)`
    is the precise answer to "what did we send"; the row's existence alone
    only answers "what rung had been reached".
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="reminders_sent"
    )
    rung = models.CharField(max_length=4, choices=Rung.choices)
    sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="remindersent_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "application", "rung"), name="remindersent_once_per_rung"
            ),
        ]
