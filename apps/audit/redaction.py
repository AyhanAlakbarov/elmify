"""GDPR erasure by redaction: overwrite personal fields, delete no rows.

Deleting rows is not available here. The model graph from Membership is PROTECT
on almost every edge, so deleting StudentProfileVersion raises ProtectedError.
The exceptions are named where they live rather than counted here: a table
holding data derived from a student (see CLAUDE.md's "Derived data and the ML
corpus") points at Pseudonym with CASCADE, and a handful of other edges use
CASCADE or SET_NULL for their own documented reasons -- read the field, not
this docstring, for which one a given FK is. Every row this module reaches, FK
and timestamp, therefore survives an erasure; only the fields that can single
out a person are overwritten.

Design: docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md
"""

from __future__ import annotations

from typing import Any, NamedTuple, cast
from uuid import UUID

from django.apps import apps
from django.db.models import F, Field, ForeignKey, Model, OneToOneField

from apps.tenancy.context import current_tenant_id
from apps.tenancy.models import Membership


class RedactSpec(NamedTuple):
    """How to find one student's rows on a model, and what to overwrite.

    `subject` is an ORM lookup path ending in an id, relative to the model,
    naming the FK chain that reaches the student the erasure is about. It is
    written by hand rather than derived: a shortest-path search finds *a*
    Membership FK, not the student's. ManualOperation.actor is the staff member
    who performed the operation; the subject is roadmap_item.student.
    """

    subject: str
    fields: tuple[str, ...]


def student_reachable_models() -> list[type[Model]]:
    """Every model whose rows can be tied to one student, Membership included.

    Forward FKs across apps.get_models(), transitively. NOT
    Membership._meta.related_objects: nine FKs to Membership declare
    related_name="+" and create no reverse accessor, so a reverse walk cannot
    see ConversationMessage, ConsentEvent, RevisionRequest or
    ConstraintOverride. ConversationMessage.body is the counselor's free-text
    correspondence about the student.

    Transitive, not one hop. ApplicationStep reaches the student only through
    Application, and ConsultationReport only through
    PackVersion -> RecommendationRun -> StudentProfileVersion; both hold REDACT
    fields and a one-hop scan classifies neither.
    """
    reached: set[type[Model]] = {Membership}
    changed = True
    while changed:
        changed = False
        for model in apps.get_models():
            if model in reached:
                continue
            if any(
                f.related_model in reached
                for f in model._meta.get_fields()
                if isinstance(f, (ForeignKey, OneToOneField)) and f.concrete
            ):
                reached.add(model)
                changed = True
    return sorted(reached, key=lambda m: (m._meta.app_label, m.__name__))


def classifiable_fields(model: type[Model]) -> list[str]:
    """Concrete, non-relational columns -- the ones that can hold a value.

    Relations are excluded because the design keeps every FK: an FK is the
    structure that survives, never the personal data. The primary key is
    excluded for the same reason -- Membership survives as an opaque key.
    """
    return [
        f.name
        for f in model._meta.get_fields()
        if getattr(f, "concrete", False)
        and not f.is_relation
        and not getattr(f, "primary_key", False)
    ]


REDACT: dict[str, RedactSpec] = {
    "accounts.StudentProfileVersion": RedactSpec("student_id", ("snapshot",)),
    "documents.VerifiedFact": RedactSpec("student_id", ("payload", "source_ref")),
    "documents.NarrativeInput": RedactSpec("student_id", ("text", "provenance")),
    "documents.TranscriptReading": RedactSpec(
        "student_id", ("record", "highlights", "key_numbers", "rows", "accepted")
    ),
    "documents.TranscriptPage": RedactSpec("student_id", ("page",)),
    "documents.TranscriptUpload": RedactSpec("student_id", ("file_sha256",)),
    "documents.DocumentDraft": RedactSpec("student_id", ("content",)),
    "documents.RevisionRequest": RedactSpec("document__student_id", ("note",)),
    "concierge.RoadmapItem": RedactSpec("student_id", ("result",)),
    "concierge.RequiredAction": RedactSpec("student_id", ("description",)),
    "concierge.ManualOperation": RedactSpec("roadmap_item__student_id", ("description",)),
    "concierge.ConversationMessage": RedactSpec("student_id", ("body",)),
    # NOT recipient_id: four of the six escalation triggers route to the
    # assigned counselor with free text about the student, and those rows name
    # nobody. roadmap_item carries the subject whoever received the message.
    "concierge.Notification": RedactSpec("roadmap_item__student_id", ("message",)),
    "portals.ApplicationStep": RedactSpec("application__student_id", ("detail",)),
    # installation_id names the student's machine; the two hashes are
    # credentials for their account. Erasure revokes the pairing and scrubs what
    # is left -- a token hash surviving an erasure is a live credential for a
    # person the agency has erased.
    "portals.ExtensionPairing": RedactSpec(
        "membership_id", ("code_hash", "token_hash", "installation_id")
    ),
    # The payload is a verification URL or a code -- a bearer credential for the
    # student's portal account, and the reason complete_action clears it the
    # moment the action is done rather than waiting for an erasure.
    "portals.DeviceAction": RedactSpec("membership_id", ("payload",)),
    # The tagged address carries the student's own address; the tag alone names
    # their account on one portal.
    "portals.PortalAccount": RedactSpec("student_id", ("tag", "address")),
    # The address is the student's own mailbox and the cursor is a pointer into
    # it. Both are about the person, neither survives them. The push
    # subscription id names a live watch on that mailbox at the provider.
    "mailbox.MailboxConnection": RedactSpec(
        "membership_id", ("address", "sync_cursor", "push_subscription_id")
    ),
    # A message id names one message in that mailbox, and the pair
    # (sender_domain, label) says a named institution told this person
    # something -- "DECISION from tum.de" is the sentence, and it is about them.
    # The readings are the same sentence in more detail: what the institution
    # decided, what it asked for and when, when the interview is.
    "mailbox.MailSignal": RedactSpec(
        "connection__membership_id",
        (
            "provider_message_id",
            "sender_domain",
            "label",
            "document_name",
            "document_due",
            "interview_at",
            "decision_reading",
            "outcome",
            "outcome_conditions",
            "funding_outcome",
            "offered_programme",
        ),
    ),
    # domain names who a scammer or a vendor is; portal_host names which
    # institution's tag they wrote to. Both are about the student's own mail.
    "mailbox.LearnedSender": RedactSpec("student_id", ("domain", "portal_host")),
    "tenancy.Membership": RedactSpec(
        "id",
        ("application_email", "academic_email", "timezone", "quiet_hours_start", "quiet_hours_end"),
    ),
    # object_version, not pack_version: the FK is named for the generic
    # "approved object" the abandoned counselor gate had in mind.
    "funding.Approval": RedactSpec("object_version__run__profile_version__student_id", ("reason",)),
    # object_key is redacted only after the S3 object is purged: the purge reads
    # it to find the object. advance_deletion enforces that order.
    "reports.ConsultationReport": RedactSpec(
        "pack_version__run__profile_version__student_id", ("object_key",)
    ),
    "concierge.DocumentVersion": RedactSpec(
        "student_id", ("object_key", "expires_on", "promoted_key", "scanned_version")
    ),
    # Whether and how a named institution decided about this person (spec §4):
    # the one fact this platform has no other record of, and about them.
    # A non-empty name says an institution offered this person a place on
    # another programme -- about them, like MailSignal.offered_programme.
    "portals.Application": RedactSpec(
        "student_id",
        ("decision_available_at", "outcome", "outcome_recorded_at", "outcome_source", "name"),
    ),
    # The discipline bucket is a model's reading of the student's own field
    # words -- derived from what they wrote, so it goes with them.
    "research.ProfileCellSelection": RedactSpec("student_id", ("discipline_bucket",)),
    # The coverage line names the student's home cells, i.e. their nationality
    # and residence (copied at build time so the web tier renders it without
    # the catalogue).
    "funding.PackVersion": RedactSpec("run__profile_version__student_id", ("coverage",)),
    # Each condition decided against the student: the reasons quote their own
    # grade, language level and nationality, and the budget is theirs.
    "funding.RecommendationCandidate": RedactSpec("run__profile_version__student_id", ("fit",)),
}

KEEP: dict[str, tuple[str, ...]] = {
    # privacy.*: none of it is personal data; the identifying link is the `student`
    # relation, which classification excludes. PrivacyRequest.handled_by is a relation
    # too (the staff member who closed it), kept like every FK and never classified.
    # LegalDocument is platform text.
    "privacy.PrivacyRequest": ("kind", "channel", "received_at", "due_at", "handled_at", "outcome"),
    "privacy.Acceptance": ("accepted_at", "surface", "language"),
    # active is KEEP here because it carries no personal data, not because
    # redact_student leaves it alone: advance_deletion writes it directly
    # (see deletion.py) as an access-control action, outside this table.
    "tenancy.Membership": ("role", "active"),
    # rung is a closed 5-value enum naming which reminder fired, sent is a
    # boolean distinguishing the actually-notified row from a superseded one,
    # and sent_at an operational timestamp -- none of it carries personal
    # data. The identifying link is the `application` relation, excluded from
    # classification above.
    "portals.ReminderSent": ("rung", "sent", "sent_at"),
    # kind is a closed enum and the times are operational; the identifying
    # link is the application relation, excluded from classification.
    "watch.Expectation": ("kind", "due_at", "created_at"),
    "accounts.StudentProfileVersion": ("version", "schema_version", "created_at"),
    "audit.DeletionRequest": (
        "state",
        "legal_hold",
        "identity_retained",
        "created_at",
        # The date the student was told. It is the record of what was erased
        # and when, which must survive the erasure it describes.
        "execute_after",
        # Fixed choices, not free text -- each names a category, never a person.
        "reason",
        "review_reason",
        "identity_retained_reason",
    ),
    # A bare timestamp on a row the erasure deletes outright -- the pseudonym
    # itself is the primary key, which classifiable_fields() skips.
    "audit.Pseudonym": ("created_at",),
    "concierge.ApplicationFeeLedgerEntry": (
        "program_id",
        "approved_limit",
        "currency",
        "charged_amount",
        # A masked financial reference, kept with the ledger entry it belongs
        # to. Whether the ledger has a statutory retention floor is §10's
        # question; redaction does not prejudge it.
        "masked_card_reference",
        "refund_amount",
        "created_at",
    ),
    "concierge.ConversationMessage": ("created_at",),
    # KEEP by constraint, not by inspection: nothing writes Receipt today.
    # GDPR Art. 17(3)(b) withdraws the right to erasure where retention is a
    # legal obligation; German accounting receipts run 8 years under §147 AO.
    # Four rules make this true and are in the spec: the key stays opaque, the
    # retained object is access-restricted (Art. 18) rather than merely kept,
    # it is destroyed when the period expires, and the exemption covers the
    # receipt and nothing else. Tripwire: test_receipt_has_no_writer_yet.
    "concierge.Receipt": ("object_key", "created_at"),
    "concierge.DocumentVersion": ("state", "scan_result", "kind", "created_at", "content_type"),
    "concierge.ManualOperation": ("performed_at",),
    "concierge.Notification": (
        "acknowledged_at",
        "urgent",
        "escalation_level",
        "created_at",
        "action",
    ),
    "concierge.RequiredAction": ("acknowledged_at", "created_at"),
    # deadline: KEEP, except an INTERVIEW item's, which redact_student resets
    # to created_at -- it is the mail's interview time (final review M2).
    "concierge.RoadmapItem": ("stage", "owner_kind", "deadline", "state", "created_at"),
    "concierge.StudentCycle": ("academic_year", "paid_at", "pages_used", "created_at"),
    "concierge.ServiceEngagement": ("platform_fee", "currency", "credit_amount", "created_at"),
    "documents.ConsentEvent": ("mode", "granted_at", "revoked_at"),
    "documents.DocumentDraft": (
        "kind",
        "version",
        "render_variant",
        # A variant's filename, e.g. cv-standard.pdf -- names a layout, not a person.
        "rendered_filename",
        "status",
        "approved_at",
        "created_at",
        "approval_mode",
        # Gate codes and archetypes, a retry flag and a cycle year: what the
        # letter engine checked, never what the letter said (detail is dropped).
        "letter_gates",
        "letter_retried",
        "letter_cycle",
    ),
    "documents.DocumentDraftFact": ("created_at",),
    "documents.NarrativeInput": ("kind", "proposed_by", "confirmed_at", "created_at"),
    "documents.TranscriptReading": ("created_at",),
    "documents.TranscriptPage": (
        "number", "slot", "retakes", "state", "refusal", "skipped_because", "source",
        "api_version", "superseded_at", "created_at",
    ),
    "documents.TranscriptUpload": (
        "role", "language", "mode", "retake_slot", "state", "refusal", "refusal_page",
        "pages_counted", "attempts", "next_attempt_at", "assembled", "updated_at", "created_at",
    ),
    # advice_shown is the style rule's own canned wording, same precedent as
    # funding.ConstraintOverride.risk_text_shown below: not student-specific.
    "documents.RevisionRequest": ("kind", "created_at", "advice_shown"),
    "documents.VerifiedFact": ("category", "source_tier", "confirmed_at", "created_at"),
    "funding.Approval": ("decision", "created_at"),
    "funding.AuditEvent": ("actor_kind", "event", "object_id", "created_at"),
    # risk_text_shown is the catalog rule's own wording, set from
    # violation.rule.rule_text by apps/documents/overrides.py. Identical for
    # every student who hits that rule; it exists to prove which warning was
    # shown, since rule text changes.
    "funding.ConstraintOverride": ("rule_id", "risk_text_shown", "created_at"),
    # expected_structured_result is KEEP *by constraint*, not by inspection:
    # nothing writes it today. Whoever builds the writer may persist
    # schema-constrained model output only, never free text or an identifier.
    # See tests/audit/test_redaction.py::test_evaluation_example_holds_no_identifier.
    "funding.EvaluationExample": (
        "input_schema_version",
        "expected_structured_result",
        "allowed_purposes",
        "created_at",
    ),
    # change_notes names programmes and a reason code, never a person.
    "funding.PackVersion": (
        "version",
        "created_at",
        "published_at",
        "superseded_at",
        "approved_version_id",
        "change_notes",
    ),
    # program_name is a programme, not a person.
    # provenance_*: a fact about the institution, not the student.
    "funding.RecommendationCandidate": (
        "program_name",
        "funding_gap",
        "currency",
        "eligible",
        "state",
        "funding_gap_is_placeholder",
        "evidence_confidence",
        "provenance_reason_code",
        "provenance_body_id",
        # the tenant copies: facts about the programme or award, not the person.
        "institution_id",
        "institution_name",
        "country_code",
        "degree_level",
        "application_fee",
        "application_fee_currency",
        "funds_program_ids",
        "funding_card",
        # the scholarship page's facts (city, costs, cover): about the award.
        "details",
    ),
    # pending_bodies: catalogue organisation ids, not about the student.
    "funding.RecommendationRun": ("state", "created_at", "dispatched_at", "pending_bodies"),
    "funding.StudentDecision": ("decision", "created_at"),
    # program_id, deadline, and deadline_timezone are facts about the programme's
    # admission cycle, not about the student. The kit_* columns are the same:
    # a copy of the programme's own published sentences from the catalogue.
    "portals.Application": (
        "program_id",
        "state",
        "created_at",
        "deadline",
        "deadline_timezone",
        "kit_requirements",
        "kit_your_actions",
        "kit_letter_cycle",
        # a copy of the programme's published route, like kit_requirements
        "route_snapshot",
        # when Start application was pressed: operational, like created_at.
        "started_at",
        # a work state and a fixed refusal code (writing.LETTER_NOTES), never text.
        "letter_state",
        "letter_note",
    ),
    # a link between two of the student's own cards. The cards are redacted in
    # place, so the row survives erasure; nothing in it is personal.
    "portals.ApplicationLink": ("order", "created_at"),
    "portals.ApplicationStep": ("sequence", "kind", "created_at"),
    "portals.ExtensionPairing": (
        "code_expires_at",
        "created_at",
        "redeemed_at",
        "last_seen_at",
        "revoked_at",
    ),
    "portals.DeviceAction": (
        "kind",
        "created_at",
        "delivered_at",
        "completed_at",
        "expires_at",
    ),
    # registered_at is when, tag_outcome a closed enum about the portal's
    # behaviour -- neither says anything about the person once tag and address
    # are gone.
    # tag_dropped_by_student is which button, the same kind of fact.
    "portals.PortalAccount": (
        "portal_host",
        "created_at",
        "registered_at",
        "tag_outcome",
        "tag_dropped_by_student",
    ),
    # provider/tier/status are what the platform was permitted to do, which is
    # the record an erasure must not destroy; the timestamps say when.
    "mailbox.MailboxConnection": (
        "provider",
        "tier",
        "status",
        "connected_at",
        "last_sync_at",
        "revoked_at",
        # A closed enum naming which mailbox this is, same class as
        # provider/tier/status above -- what the platform was permitted to do.
        "kind",
        # When the last stale-inbox alert fired -- an operational timestamp
        # naming a platform action, not the student.
        "health_alerted_at",
        # When the push subscription lapses: a platform timer, not the person.
        "push_expires_at",
    ),
    # A count of failed classification tries, not content -- the same class as
    # trusted, above.
    # offer_handled_at: when a button was pressed, an operational timestamp.
    "mailbox.MailSignal": (
        "received_at",
        "created_at",
        "trusted",
        # Whether the provider authenticated the sender: a fact about the
        # delivery, same class as trusted.
        "sender_authenticated",
        "classify_attempts",
        "offer_handled_at",
    ),
    "mailbox.LearnedSender": ("confirmed_at", "created_at"),
    "reports.ConsultationPayment": (
        "amount",
        "currency",
        "status",
        "credited_engagement_id",
        "created_at",
    ),
    "reports.ConsultationReport": ("s3_version_id", "sha256", "content_type", "generated_at"),
    # Tenant-level, not about the student.
    "tenancy.AgencyDataUseAgreementVersion": (
        "agreement_id",
        "version",
        "agreement_reference",
        "permitted_purposes",
        "eligible_categories",
        "lawful_basis_review_state",
        "effective_at",
        "revoked_at",
        "created_at",
    ),
    "tenancy.CounselorAssignment": ("active", "created_at"),
    # The demand-cell spend ledger (build item 14) is money arithmetic, not a
    # person: amounts, closed enums, counters and timestamps. The identifying
    # link is the student relation, excluded by classifiable_fields exactly as
    # for portals.ReminderSent. CellCoverage is absent on purpose: it has no
    # student relation, the walk never reaches it, and an erased student leaves
    # it by recomputation, not by redaction.
    # `model` is the id of the model that read the bucket, never the student's.
    "research.ProfileCellSelection": ("model", "created_at"),
    "research.SearchWallet": ("intended_intake", "budget_usd", "spent_usd", "created_at"),
    # run_id / pack_version_id are opaque keys to the student's own run and
    # pack (plain columns because research may not depend on funding), kept
    # like PackVersion.approved_version_id.
    "research.SearchTap": (
        "run_id",
        "pack_version_id",
        "state",
        "ending",
        "recency_only",
        "allowance_usd",
        "provider_calls",
        "pages_fetched",
        "hosts_seen",
        "hosts_new",
        "awards_served",
        "requested_at",
        "finished_at",
    ),
    # provider is a vendor name ("exa", "brave", "reader"), never a person.
    "research.WalletCharge": ("kind", "provider", "usd", "created_at"),
}

# Both entries that lived here were resolved on 2026-09-08 -- Receipt to KEEP by
# constraint, Notification to REDACT through the FK Task 2 adds. The class and
# the test that blocks on it stay: they are the mechanism that made those two
# visible, and the next field nobody has thought about lands here too.
UNDECIDED: dict[str, tuple[str, ...]] = {}


class RedactionIncomplete(RuntimeError):
    """Raised when a field has no retention decision, before anything is written.

    Erasure that skips a field is worse than erasure that refuses: the first
    records a legal claim that is false.
    """


def _empty_value(model: type[Model], field_name: str) -> object:
    """The empty value for a field's type.

    Text and JSON become "" and {}, never NULL: NOT NULL constraints must keep
    holding, and "redacted" is distinguishable from "never set" through the
    DeletionRequest, which is where that fact belongs. The exceptions are
    nullable columns whose type has no empty value: a nullable TimeField, and
    a nullable DateField or DateTimeField, become NULL. A NOT NULL date has no
    empty value and raises RedactionIncomplete.
    """
    # cast: get_field also returns relations, which have no column to empty.
    # REDACT never names one -- classifiable_fields excludes relations and the
    # completeness test pins REDACT to those, so CI proves what this assumes.
    field = cast("Field[Any, Any]", model._meta.get_field(field_name))
    internal = field.get_internal_type()
    if internal == "JSONField":
        return {}
    if internal in ("CharField", "TextField"):
        return ""
    if internal == "TimeField":
        # Nullable by schema (quiet_hours_start/end): NULL already means
        # "no window set", so redacting to NULL does not collide with that
        # meaning the way it would for a NOT NULL column.
        return None
    if internal in ("DateField", "DateTimeField") and field.null:
        # Nullable by schema: NULL means "never happened", which is what an
        # erased person's decision and deadline dates must read as.
        return None
    raise RedactionIncomplete(
        f"no empty value defined for {model.__name__}.{field_name} ({internal})"
    )


def redact_student(*, tenant_id: UUID, student_id: UUID) -> int:
    """Overwrite every REDACT field belonging to one student. Deletes nothing.

    Returns the number of rows updated. Callers run this inside a transaction:
    a failure part-way through must leave no partially redacted student, and
    advance_deletion must not write EXECUTED unless this returned.

    Some of these tables are FORCE ROW LEVEL SECURITY on app.tenant_id and the
    production role is NOBYPASSRLS, so the caller must also have called
    set_local_tenant -- tenant_scope alone is a contextvar and never reaches
    Postgres. Without it these UPDATEs are legal SQL that match zero rows, and
    the erasure silently does nothing.
    """
    # Every REDACT model is TenantScopedModel, so model.objects filters on
    # current_tenant_id() -- the tenant_scope() contextvar -- not on this
    # argument. Without this check, tenant_id is decorative: a caller inside
    # tenant_scope(A) passing tenant_id=B silently redacts under A, no error.
    if current_tenant_id() != tenant_id:
        raise RedactionIncomplete(
            f"ambient tenant {current_tenant_id()} does not match the requested "
            f"tenant {tenant_id}: refusing to redact under the wrong scope"
        )
    if UNDECIDED:
        raise RedactionIncomplete(
            "fields awaiting a retention decision (phased requirements.md §10): "
            f"{sorted(UNDECIDED)}"
        )
    # A partial redaction is impossible because the caller wraps this in
    # transaction.atomic() -- see the docstring. type[Any], not type[Model]:
    # django-stubs only injects .objects for a model class it sees statically.
    updated = 0
    for label, spec in REDACT.items():
        model: type[Any] = apps.get_model(label)
        empties = {name: _empty_value(model, name) for name in spec.fields}
        updated += model.objects.filter(**{spec.subject: student_id}).update(**empties)
    # An INTERVIEW item's deadline is the interview time a mail stated
    # (mailbox/actions.py::_alert_student, the only writer of that stage), and
    # MailSignal.interview_at is REDACT above. The column is NOT NULL, so it
    # falls back to the row's own created_at, which KEEP already holds
    # (final review M2). Every other stage's deadline is the programme's.
    from apps.concierge.models import RoadmapItem

    updated += RoadmapItem.objects.filter(
        student_id=student_id, stage=RoadmapItem.Stage.INTERVIEW
    ).update(deadline=F("created_at"))
    return updated
