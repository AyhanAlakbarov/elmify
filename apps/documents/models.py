from uuid import uuid4

from django.db import models

from apps.tenancy.models import Membership, TenantScopedModel


class VerifiedFact(TenantScopedModel):
    """Append-only fact ledger. Corrections are new rows with ``supersedes`` set.

    ``payload`` keys are canonical per category and are produced in exactly one
    place -- ``apps.documents.verification.fact_payload`` (Task 4). Every writer
    (the profile bridge, upload ingestion, the consultant) goes through it, so
    the verifier and the writers cannot drift apart on key names.
    """

    class Category(models.TextChoices):
        EDUCATION = "EDUCATION"
        EXPERIENCE = "EXPERIENCE"
        RESEARCH = "RESEARCH"
        PUBLICATION = "PUBLICATION"
        AWARD = "AWARD"
        LANGUAGE = "LANGUAGE"
        SKILL = "SKILL"
        PERSONAL = "PERSONAL"
        #: A named referee. Its own category rather than a field on IDENTITY:
        #: a referee is a claim about another person, and it has to be
        #: confirmable (and contradictable) on its own before their name and
        #: address reach a funder.
        REFERENCE = "REFERENCE"
        #: Who the CV is about. A CV's row carries full_name and its
        #: contact keys; a passport read writes one row per person key
        #: (date_of_birth, citizenship, ...), so a reader looking for the name
        #: filters on `full_name` (verification.has_full_name). The contact address
        #: is the address the student applies with (see
        #: Membership.application_email: the connected mailbox's address, or
        #: one the student declared and confirmed), not a fact anyone confirms.
        IDENTITY = "IDENTITY"
        #: A span of time no education or experience entry covers, and the one
        #: line that accounts for it. Its own category because neither
        #: neighbouring shape fits: ExperienceEntry requires an employer and a
        #: bullet, and S-045 measured that what Cambridge actually prints for a
        #: gap ("Full-time carer for family member", "3 months' full-time
        #: job-hunting") has neither. Required by ETH, TUM (no gap over three
        #: months), DAAD PRIME (R-011), uni-assist (R-020) and Harvard GSD.
        TIMELINE = "TIMELINE"
        #: A course certificate or professional licence (CVContent.certifications).
        #: Its own category: an award is an honour granted on merit, this is a
        #: thing completed, and the CV prints them under different headings.
        CERTIFICATION = "CERTIFICATION"
        #: One identity document the student holds -- a passport, an ID card or a
        #: residence permit (spec 2026-10-12 §4.2). A row per document, keyed by
        #: source_ref "document:<DocumentVersion id>", because a dual national
        #: holds two and a renewal leaves the old one behind. Never reaches
        #: generation (verification.generatable_facts drops it).
        ID_DOCUMENT = "ID_DOCUMENT"

    class SourceTier(models.TextChoices):
        AUTHORITATIVE_DOCUMENT = "AUTHORITATIVE_DOCUMENT"
        STUDENT_STATEMENT = "STUDENT_STATEMENT"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="verified_facts")
    category = models.CharField(max_length=20, choices=Category.choices)
    payload = models.JSONField()
    source_tier = models.CharField(max_length=30, choices=SourceTier.choices)
    source_ref = models.CharField(max_length=500)
    confirmed_by = models.ForeignKey(
        Membership, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="superseded_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="verified_facts_created"
    )

    class Meta:
        indexes = [models.Index(fields=("tenant", "student", "category"), name="fact_scope_idx")]
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="verifiedfact_tenant_id_uniq"),
            # One superseding row per target. Two concurrent answers to the same
            # question otherwise both read the tip as current and both supersede
            # it, and unsuperseded_facts then returns two tips for one logical
            # fact. select_for_update does NOT prevent this: the fork comes from
            # INSERTing a sibling, not from modifying the locked row, so under
            # READ COMMITTED the loser's anti-join never sees the winner's row.
            # Demonstrated by test_two_concurrent_submits_do_not_fork_the_
            # supersession_chain, which fails with the lock and passes with this.
            models.UniqueConstraint(
                fields=("supersedes",),
                condition=models.Q(supersedes__isnull=False),
                name="verifiedfact_one_superseder",
            ),
            models.CheckConstraint(
                # Nested Meta class bodies don't close over VerifiedFact's local
                # namespace, so Category/SourceTier must be spelled out here
                # rather than referenced -- same workaround as
                # AgencyDataUseAgreementVersion.Meta in apps/tenancy/models.py.
                condition=models.Q(
                    category__in=(
                        "EDUCATION",
                        "EXPERIENCE",
                        "RESEARCH",
                        "PUBLICATION",
                        "AWARD",
                        "LANGUAGE",
                        "SKILL",
                        "PERSONAL",
                        "IDENTITY",
                        "REFERENCE",
                        "TIMELINE",
                        "CERTIFICATION",
                        "ID_DOCUMENT",
                    )
                ),
                name="verifiedfact_category_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    source_tier__in=("AUTHORITATIVE_DOCUMENT", "STUDENT_STATEMENT")
                ),
                name="verifiedfact_source_tier_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(confirmed_by__isnull=True, confirmed_at__isnull=True)
                | models.Q(confirmed_by__isnull=False, confirmed_at__isnull=False),
                name="verifiedfact_confirmation_complete",
            ),
        ]


class DocumentDraft(TenantScopedModel):
    class Kind(models.TextChoices):
        CV = "CV"
        MOTIVATION_LETTER = "MOTIVATION_LETTER"
        CORE_NARRATIVE = "CORE_NARRATIVE"

    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        APPROVED = "APPROVED"
        SUPERSEDED = "SUPERSEDED"

    class RenderVariant(models.TextChoices):
        EUROPASS = "EUROPASS"
        EUROPASS_API = "EUROPASS_API"
        GERMAN_TABULAR = "GERMAN_TABULAR"
        STANDARD = "STANDARD"
        FUNDER_TEMPLATE = "FUNDER_TEMPLATE"
        FIELD_MAPPED = "FIELD_MAPPED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="document_drafts"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    version = models.PositiveIntegerField()
    content = models.JSONField()
    render_variant = models.CharField(
        max_length=30, blank=True, default="", choices=RenderVariant.choices
    )
    #: The filename the rendered artefact was actually stored under, written by
    #: storage.store_document -- the one writer every render path goes through
    #: -- when it puts the object. Blank until then. `render_variant` above is
    #: the INPUT override; this is the OUTPUT. The web tier builds download
    #: links from this alone and never resolves a variant itself: the object's
    #: name is fixed at render time, so resolving it live from the programme
    #: or funder named an object that does not exist whenever either changed
    #: after rendering, and the web role cannot read the catalogue anyway.
    rendered_filename = models.CharField(max_length=100, blank=True, default="")
    # Program is a shared catalog model (not TenantScopedModel), so this FK
    # deliberately has no composite tenant partner -- there is no tenant column
    # on the other side to pair with.
    programme = models.ForeignKey(
        "funding.Program", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # The CORE_NARRATIVE draft this MOTIVATION_LETTER draft descends from.
    derived_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="derived_letters"
    )
    # Same shape and same reason as `programme` above: FundingOpportunity is a
    # shared catalog model, so this FK has no composite tenant partner.
    # Nullable, and null is meaningful -- it means self-funded, a direct
    # application, and the resolver simply drops the funder scope. Resolving a
    # funder from the programme instead was rejected: a programme linked to
    # five scholarships would inherit all five funders' rules at once.
    funding_opportunity = models.ForeignKey(
        "funding.FundingOpportunity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_facts: models.ManyToManyField[VerifiedFact, DocumentDraftFact] = (
        models.ManyToManyField(
            VerifiedFact,
            through="DocumentDraftFact",
            related_name="used_in_drafts",
            blank=True,
        )
    )
    #: The application this CV was made for. SET_NULL: removing the card must
    #: not be blocked by, or take, the draft the student already has.
    application = models.ForeignKey(
        "portals.Application",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cv_drafts",
    )
    #: The RequirementList this CV was built against (model_dump, json mode).
    #: Null: made before step 4.2 or without a list.
    requirements = models.JSONField(null=True, blank=True)
    #: {item id: {"state": ItemState, "reason": str}}; reasons can name student
    #: entries, so this column is redacted on erasure.
    requirement_states = models.JSONField(default=dict, blank=True)
    requirements_digest = models.CharField(max_length=64, blank=True, default="")
    destination_label = models.CharField(max_length=300, blank=True, default="")
    is_general = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        Membership, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    #: MOTIVATION_LETTER only, written by the worker that generated the letter
    #: (document_worker._generate_letter): the gate violations and retry flag
    #: generate_letter returned. letter_approval.mark_letter_ready trusts its
    #: caller for these, so the approve path reads the generator's own record
    #: of them, never anything a request sends. Codes and archetypes only: the
    #: `detail` text is not kept, it can quote the letter.
    letter_gates = models.JSONField(default=list, blank=True)
    letter_retried = models.BooleanField(default=False)
    #: The admissions cycle of the ApplicationPrompt the letter was written to.
    letter_cycle = models.CharField(max_length=20, blank=True, default="")

    class ApprovalMode(models.TextChoices):
        PER_DOCUMENT = "PER_DOCUMENT"
        COUNSELOR_APPROVES = "COUNSELOR_APPROVES"

    approval_mode = models.CharField(
        max_length=20, choices=ApprovalMode.choices, default=ApprovalMode.PER_DOCUMENT
    )
    #: Spec §5.5: every automatic fix generation applied (or skipped because the
    #: student undid it), each with the student's original text beside it, as
    #: cv_fixes.AppliedFix.as_json() rows. Student text, so REDACTED on erasure.
    #: Defaults to [] so drafts written before Stage 3 need no data migration.
    applied_fixes = models.JSONField(default=list, blank=True)
    #: Non-binding constraint violations from the release render (spec §8.5):
    #: list of {"rule_id", "key", "enforcement", "rule_text", "detail"}.
    #: REDACTED on erasure: a detail can name a gap year or an item count.
    render_warnings = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="documentdraft_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student", "kind", "version"),
                name="documentdraft_tenant_student_kind_version_uniq",
            ),
            models.CheckConstraint(
                # Nested Meta class bodies don't close over DocumentDraft's
                # local namespace, so Kind.values must be spelled out here
                # rather than referenced -- same workaround as VerifiedFact's
                # Meta above.
                condition=models.Q(kind__in=("CV", "MOTIVATION_LETTER", "CORE_NARRATIVE")),
                name="documentdraft_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "APPROVED", "SUPERSEDED")),
                name="documentdraft_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(approved_by__isnull=True, approved_at__isnull=True)
                | models.Q(approved_by__isnull=False, approved_at__isnull=False),
                name="documentdraft_approval_complete",
            ),
            models.CheckConstraint(
                condition=models.Q(approval_mode__in=("PER_DOCUMENT", "COUNSELOR_APPROVES")),
                name="documentdraft_approval_mode_valid",
            ),
        ]


class DocumentDraftFact(TenantScopedModel):
    """Explicit through model for DocumentDraft.source_facts.

    Django's auto-created M2M table would have no tenant_id column, so it could
    carry neither an RLS policy nor a composite tenant FK -- a draft in one
    tenant could be linked to a fact in another with nothing to catch it.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    document = models.ForeignKey(
        DocumentDraft, on_delete=models.PROTECT, related_name="source_fact_links"
    )
    fact = models.ForeignKey(VerifiedFact, on_delete=models.PROTECT, related_name="draft_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="documentdraftfact_tenant_id_uniq"
            ),
            models.UniqueConstraint(
                fields=("tenant", "document", "fact"), name="documentdraftfact_pair_uniq"
            ),
        ]


class RevisionRequest(TenantScopedModel):
    class Kind(models.TextChoices):
        STYLE_STRUCTURE = "STYLE_STRUCTURE"
        FACTUAL_CORRECTION = "FACTUAL_CORRECTION"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    document = models.ForeignKey(
        DocumentDraft, on_delete=models.PROTECT, related_name="revision_requests"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    requested_by = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    note = models.TextField()
    # The rule's own explanation shown to the student before a weakening edit
    # was applied ("advise once, then comply"). Empty string means no advice
    # applied -- distinct from a lost record. Same shape as
    # funding.ConstraintOverride.risk_text_shown: canned rule wording, not
    # student-specific text.
    advice_shown = models.TextField(blank=True, default="")
    resulting_draft = models.ForeignKey(
        DocumentDraft, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    superseding_fact = models.ForeignKey(
        VerifiedFact, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="revisionrequest_tenant_id_uniq"),
            models.CheckConstraint(
                # Same nested-Meta-namespace workaround as DocumentDraft above.
                condition=models.Q(kind__in=("STYLE_STRUCTURE", "FACTUAL_CORRECTION")),
                name="revisionrequest_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(kind="STYLE_STRUCTURE")
                | models.Q(kind="FACTUAL_CORRECTION", superseding_fact__isnull=False),
                name="revisionrequest_correction_needs_fact",
            ),
        ]


class ConsentEvent(TenantScopedModel):
    """Who accepted this document for use, under which approval mode.

    One open (``revoked_at IS NULL``) event per document at a time; approval
    writes it, revocation closes it.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    document = models.ForeignKey(
        DocumentDraft, on_delete=models.PROTECT, related_name="consent_events"
    )
    mode = models.CharField(max_length=20, choices=DocumentDraft.ApprovalMode.choices)
    granted_by = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="consentevent_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "document"),
                condition=models.Q(revoked_at__isnull=True),
                name="consentevent_one_open_per_document",
            ),
        ]


class EuropassRenderCache(TenantScopedModel):
    """Payload hash -> stored artefact, so an unchanged CV is never re-rendered.

    Also the idempotency key: SQS is at-least-once, so the worker will
    occasionally see a message twice, and the second delivery finds this row
    and makes no call. One mechanism, two jobs -- which is why there is no
    separate dedupe table.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: sha256 hex of the canonical europass_payload JSON.
    payload_hash = models.CharField(max_length=64)
    object_key = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "payload_hash"), name="europassrendercache_tenant_hash_uniq"
            ),
            models.UniqueConstraint(
                fields=("tenant", "id"), name="europassrendercache_tenant_id_uniq"
            ),
        ]


class EuropassCircuit(models.Model):
    """Global breaker for outbound Europass calls. Deliberately NOT tenant-scoped.

    All egress leaves through one NAT Elastic IP, so when europa.eu throttles
    us they throttle *us*, not one customer. A per-tenant circuit would let
    every other tenant keep calling an endpoint that just asked us all to
    stop. It holds no tenant or student data -- only a timestamp, a reason
    and a counter -- and a test pins that.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    paused_until = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True, default="")
    consecutive_failures = models.PositiveIntegerField(default=0)

    @classmethod
    def load(cls) -> EuropassCircuit:
        circuit, _created = cls.objects.get_or_create(pk=1)
        return circuit

    def is_open(self) -> bool:
        from django.utils import timezone

        return self.paused_until is not None and self.paused_until > timezone.now()


class NarrativeInput(TenantScopedModel):
    """Engine-drafted, student-owned narrative inputs feeding motivation letters.

    Amendment 2026-09-14 (docs/research/2026-09-14-letter-storytelling-evidence.md,
    N-04, N-16): PERSONAL_BACKGROUND is the origin slot -- one sentence of
    circumstance where a reader wants one. The engine may propose it
    (proposed_by=ENGINE); the student edits it in the overlay, and accepting the
    draft confirms it like any other input -- there is no per-item confirmation
    step. Everything the engine writes about a student's family or upbringing
    goes through this kind, never through VerifiedFact.Category.PERSONAL and
    never as bare prose.
    """

    class Kind(models.TextChoices):
        RESEARCH_PLAN = "RESEARCH_PLAN"
        LANGUAGE_PLAN = "LANGUAGE_PLAN"
        HOME_COUNTRY_CIRCUMSTANCES = "HOME_COUNTRY_CIRCUMSTANCES"
        DEVELOPMENT_IMPACT = "DEVELOPMENT_IMPACT"
        PERSONAL_BACKGROUND = "PERSONAL_BACKGROUND"  # 2026-09-14: the origin slot, N-04/N-16
        #: A sentence from the programme's own site that names a group, person,
        #: module, track or partner the student's anchor aligns with. Always
        #: engine-proposed and pre-accepted; `provenance` carries the page,
        #: the entity and the judgement (2026-09-22 research-fit design, D7).
        RESEARCH_FIT = "RESEARCH_FIT"

    class ProposedBy(models.TextChoices):
        ENGINE = "ENGINE"
        STUDENT = "STUDENT"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="narrative_inputs"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    text = models.TextField()
    proposed_by = models.CharField(max_length=10, choices=ProposedBy.choices)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    #: Set only on RESEARCH_FIT rows. Keys: program_id, sentence, entity,
    #: source_url, page_digest, kind, rung, anchor_fact_id, judgement,
    #: topic_hash, cost_usd, provider. `entity` is the substring of `sentence`
    #: that names what the letter may cite; verify_letter_claims requires it
    #: in the claim's text (D9). Redacted on erasure with `text`.
    provenance = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="narrativeinput_tenant_id_uniq"),
            models.CheckConstraint(
                # Nested Meta class bodies don't close over NarrativeInput's
                # local namespace, so Kind.values must be spelled out here --
                # same workaround as VerifiedFact's Meta above.
                condition=models.Q(
                    kind__in=(
                        "RESEARCH_PLAN",
                        "LANGUAGE_PLAN",
                        "HOME_COUNTRY_CIRCUMSTANCES",
                        "DEVELOPMENT_IMPACT",
                        "PERSONAL_BACKGROUND",
                        "RESEARCH_FIT",
                    )
                ),
                name="narrativeinput_kind_valid",
            ),
        ]


class TranscriptReading(TenantScopedModel):
    """What the reader transcribed from one transcript, and what the student kept.

    `record` is the reader's version; `accepted` is the version the student
    continued with on the summary screen (spec T2). The difference between the
    two is where the reader went wrong -- the correction record the spec asks
    for, kept without a second table.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    #: The upload whose arrival completed this reading. A cycle has a reading per completion; the
    #: newest is the student's (consultation.prefill_from_latest_reading). That prefill runs once
    #: and never overwrites a draft the student may have edited; offering a newer reading is plan
    #: 3's summary screen's job.
    document = models.ForeignKey("concierge.DocumentVersion", on_delete=models.PROTECT)
    cycle = models.ForeignKey(
        "concierge.StudentCycle", null=True, blank=True, on_delete=models.PROTECT
    )
    record = models.JSONField()
    #: transcript.Highlight dumps: failed checks, unchecked totals, unsure answers (spec T2).
    highlights = models.JSONField(default=list)
    #: transcript_checks.KeyNumbers: the four numbers the summary screen opens with.
    key_numbers = models.JSONField(default=dict)
    #: transcript.Row dumps, every row the reader cut, in reading order: what a highlight's
    #: row or semester `ref` names -- `record` keeps courses only and carries no index.
    rows = models.JSONField(default=list)
    #: "<row index>:<cell>" -> the object key of a PNG of that cell on the original page, for
    #: the cells the student is asked about (storage.crop_key). A cell with no position on its
    #: page (a text-layer page, a blank cell, a reading from before plan 3a) has no entry.
    crops = models.JSONField(default=dict)
    #: The student's answer to each doubtful cell of the transcript check (plan 3b):
    #: "<item ref>" -> {"choice": "matches" | "fix" | "cant_read", "value": "...", "at": iso}.
    #: Kept beside the reader's values, which are never overwritten (spec §6.2, §6.6).
    answers = models.JSONField(default=dict)
    #: "Something's wrong", or a cell the student could not read: someone looks. Never blocks
    #: accepting the reading.
    review_requested_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True)
    accepted = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="transcriptreading_tenant_id_uniq"
            )
        ]


class DocumentReading(TenantScopedModel):
    """One read of one passport, ID card, diploma or certificate (spec 2026-10-12 §6.1).

    `values` holds what was read and how it was proven -- the normalised value, the
    printed snippet it came from (at most 200 characters) and a closed `why` code --
    never Azure's raw answer or a model's. One row per (document, reader_version):
    a new reader version re-reads, the same one never does.
    """

    class State(models.TextChoices):
        QUEUED = "QUEUED"
        READING = "READING"
        DELAYED = "DELAYED"
        READ = "READ"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    document = models.ForeignKey(
        "concierge.DocumentVersion", on_delete=models.PROTECT, related_name="readings"
    )
    kind = models.CharField(max_length=30)
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED)
    failure = models.CharField(max_length=30, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    reader_version = models.CharField(max_length=20)
    file_sha256 = models.CharField(max_length=64, blank=True)
    azure_pages = models.PositiveSmallIntegerField(default=0)
    #: When pages were last added to azure_pages: the daily ceiling counts by this,
    #: never by updated_at, which any later save (a passport choice) moves.
    azure_billed_at = models.DateTimeField(null=True, blank=True)
    values = models.JSONField(default=list)
    facts_written = models.BooleanField(default=False)
    #: The student chose this ID document for portals (spec §4.2); latest wins.
    primary_chosen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="documentreading_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("document", "reader_version"), name="documentreading_once_per_version"
            ),
        ]


class TranscriptUpload(TenantScopedModel):
    """One transcript file and what reading it came to (spec 2026-10-03 §3.1).

    `pages_counted` is set once, when the upload's pages are charged to the cycle's allowance:
    a redelivery never charges again. `assembled` says the cycle's reading was rebuilt after this
    upload's pages were written; until then the resume sweep may pick it up.
    """

    class Role(models.TextChoices):
        ORIGINAL = "ORIGINAL"
        TRANSLATION = "TRANSLATION"

    class Mode(models.TextChoices):
        ADD = "ADD"
        RETAKE = "RETAKE"
        REPLACE = "REPLACE"

    class State(models.TextChoices):
        PENDING = "PENDING"
        READING = "READING"
        DELAYED = "DELAYED"
        READ = "READ"
        REFUSED = "REFUSED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    cycle = models.ForeignKey("concierge.StudentCycle", on_delete=models.PROTECT)
    document = models.OneToOneField("concierge.DocumentVersion", on_delete=models.PROTECT)
    role = models.CharField(max_length=12, choices=Role.choices)
    #: The language of an ORIGINAL, sent to Azure as its locale hint (spec §4); "" when unsaid.
    language = models.CharField(max_length=2, blank=True)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.ADD)
    retake_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.PENDING)
    #: Why the whole upload was refused or failed: a page-gate or file reason, `heic`,
    #: `allowance_exceeded`, `retake_one_page`, `not_a_transcript`, `reader_unavailable`...
    refusal = models.CharField(max_length=30, blank=True)
    #: The page a refusal names -- or, for `allowance_exceeded`, how many pages are left.
    refusal_page = models.PositiveSmallIntegerField(null=True, blank=True)
    pages_counted = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    assembled = models.BooleanField(default=False)
    file_sha256 = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="transcriptupload_tenant_id_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(mode="RETAKE", retake_slot__isnull=False)
                | (~models.Q(mode="RETAKE") & models.Q(retake_slot__isnull=True)),
                name="transcriptupload_retake_names_a_slot",
            ),
        ]


class TranscriptPage(TenantScopedModel):
    """One page of the student's transcript, read once and kept (spec §3.1).

    `page` is the read OcrPage -- the layout cache: a redelivery, a retake of another page or a
    new reading never reads or bills this page again. A retake supersedes the page in its slot.
    """

    class State(models.TextChoices):
        READ = "READ"
        REFUSED = "REFUSED"
        SKIPPED = "SKIPPED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    cycle = models.ForeignKey("concierge.StudentCycle", on_delete=models.PROTECT)
    upload = models.ForeignKey(TranscriptUpload, on_delete=models.PROTECT, related_name="pages")
    #: The page's number within its upload's file.
    number = models.PositiveSmallIntegerField()
    #: Its place in the transcript, from 1.
    slot = models.PositiveSmallIntegerField()
    retakes = models.PositiveSmallIntegerField(default=0)
    state = models.CharField(max_length=8, choices=State.choices)
    refusal = models.CharField(max_length=30, blank=True)
    skipped_because = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=10)
    api_version = models.CharField(max_length=20, blank=True)
    page = models.JSONField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="transcriptpage_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("cycle", "slot"),
                condition=models.Q(superseded_at__isnull=True),
                name="transcriptpage_one_live_page_per_slot",
            ),
        ]


class Referee(TenantScopedModel):
    """One professor the student asked for letters (lanes spec §3.2, §11.2).

    Third-party personal data, kept minimal: what the request package and the plan
    need, nothing more. Redacted with the student (apps/audit/redaction.py); nothing
    else in the system reads it, and Elmify staff never see it.
    """

    class Kind(models.TextChoices):
        ACADEMIC = "ACADEMIC", "Academic"
        PROFESSIONAL = "PROFESSIONAL", "Professional"

    class Status(models.TextChoices):
        #: Planned with.
        ACTIVE = "ACTIVE", "Writing for you"
        #: Said no: never proposed again until the student says otherwise.
        DECLINED = "DECLINED", "Declined"
        #: Stopped answering: treated as declined by the plan, kept apart because the
        #: student may still hear back.
        SILENT = "SILENT", "Not answering"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="referees")
    name = models.CharField(max_length=200)
    #: "Prof.", "Dr." -- as the student addresses them.
    title = models.CharField(max_length=60, blank=True)
    institution = models.CharField(max_length=300, blank=True)
    email = models.EmailField(max_length=320, blank=True)
    #: The student says the address is the university's own, not a personal one.
    institutional_email = models.BooleanField(default=False)
    #: Not in spec §3.2's list: a programme's `kind` (ACADEMIC/PROFESSIONAL) can be
    #: met only if the referee's is known.
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.ACADEMIC)
    #: The student's own words: courses, grades and projects with this professor.
    relationship = models.TextField(max_length=1000, blank=True)
    #: How many portal requests (PORTAL_INVITE, REFEREE_SENDS) they agreed to.
    agreed_requests = models.PositiveSmallIntegerField(default=0)
    gives_generic_letter = models.BooleanField(default=False)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def label(self) -> str:
        """How the student names them: "Prof. Rauf Aliyev"."""
        return f"{self.title} {self.name}".strip()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="referee_tenant_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(kind__in=("ACADEMIC", "PROFESSIONAL")),
                name="referee_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "DECLINED", "SILENT")),
                name="referee_status_valid",
            ),
        ]


class RefereeRequest(TenantScopedModel):
    """One professor asked for one application's letter (lanes spec §3.2, §11.2)."""

    class Mode(models.TextChoices):
        #: grammar.REFEREE_FIELDS["mode"], copied from the card's requirement.
        UPLOAD_GENERIC = "UPLOAD_GENERIC", "A general letter you upload"
        UPLOAD_ADDRESSED = "UPLOAD_ADDRESSED", "A letter addressed to the programme, you upload"
        PORTAL_INVITE = "PORTAL_INVITE", "The portal emails them an invitation"
        REFEREE_SENDS = "REFEREE_SENDS", "They send it themselves"
        NOT_STATED = "NOT_STATED", "Not stated — check the page"

    class State(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        ASKED = "ASKED", "Asked"
        AGREED = "AGREED", "Agreed"
        DECLINED = "DECLINED", "Declined"
        SUBMITTED = "SUBMITTED", "Submitted"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: PROTECT: a professor is marked, never deleted (Decisions, above).
    referee = models.ForeignKey(Referee, on_delete=models.PROTECT, related_name="requests")
    application = models.ForeignKey(
        "portals.Application", on_delete=models.CASCADE, related_name="referee_requests"
    )
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.NOT_STATED)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PROPOSED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="refereerequest_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("referee", "application"), name="refereerequest_one_per_application"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    mode__in=(
                        "UPLOAD_GENERIC", "UPLOAD_ADDRESSED", "PORTAL_INVITE", "REFEREE_SENDS",
                        "NOT_STATED",
                    )
                ),
                name="refereerequest_mode_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    state__in=("PROPOSED", "ASKED", "AGREED", "DECLINED", "SUBMITTED")
                ),
                name="refereerequest_state_valid",
            ),
        ]


class EvidenceReading(TenantScopedModel):
    """One checked reading of one GitHub repository or one uploaded thesis or report
    (CV evidence spec §9). `reading` is the checked RepoReading, each bullet's support
    verdict, the dates and where the repo came from (checks.Checked.to_json plus
    refresh.py's additions).

    Read and written only by apps/documents/evidence/facts.py. Nothing else reads it,
    which keeps readings out of the confirm list, confirmation, skill tailoring, the
    portal profile and generatable_facts. Operational data, not a training-derived
    table, so it points at Membership, not Pseudonym; erasure deletes the rows
    (audit/deletion.py) after redacting them (audit/redaction.py).
    """

    class SourceKind(models.TextChoices):
        GITHUB = "github", "GitHub"
        PDF = "pdf", "PDF"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    source_kind = models.CharField(max_length=6, choices=SourceKind.choices)
    #: GitHub's own "owner/name" spelling; "" for a pdf, and after an erasure's redaction.
    repo = models.CharField(max_length=201, blank=True)
    document = models.ForeignKey(
        "concierge.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    #: The repo's pushed_at, or the upload's created_at: the re-read rule compares it.
    changed_at = models.DateTimeField()
    reader_version = models.PositiveSmallIntegerField()
    read_at = models.DateTimeField()
    reading = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="evidencereading_tenant_id_uniq"
            ),
            # `repo != ""`: erasure redacts repo to "" before deleting the rows, and two
            # redacted readings of one student must not collide on the way out.
            models.UniqueConstraint(
                fields=("student", "repo"),
                condition=models.Q(source_kind="github") & ~models.Q(repo=""),
                name="evidencereading_one_per_repo",
            ),
            models.UniqueConstraint(
                fields=("student", "document"),
                condition=models.Q(source_kind="pdf"),
                name="evidencereading_one_per_document",
            ),
            models.CheckConstraint(
                condition=models.Q(source_kind="github", document__isnull=True)
                | models.Q(source_kind="pdf", document__isnull=False, repo=""),
                name="evidencereading_source_shape",
            ),
        ]


class CvFixRevert(TenantScopedModel):
    """The student undid an automatic CV fix, or said a short name is printed
    exactly so (spec §5.5). The row's presence is the decision.

    `subject` is cv_fixes.subject_of(fix, text): a SHA-256 of the fix name and
    the student's text, never the text. Keyed on the text rather than a fact
    id, so the decision survives a re-upload of the same CV and an unrelated
    answer on the same fact; changed text is a new subject and is fixed again.
    advance_deletion deletes these rows before redaction: redacting every
    subject to "" would collide on the unique constraint.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    fix = models.CharField(max_length=30)
    subject = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="cvfixrevert_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student", "fix", "subject"),
                name="cvfixrevert_one_per_subject",
            ),
        ]


class CVRelevanceAnswer(TenantScopedModel):
    """One relevance answer for one optional CV item against one programme's
    requirements (relevance.py). A cache, kept for repeatability: the same
    item against the same requirements gets the same answer on regeneration.

    Digests only -- never the item's text or the requirement sentences. Per
    student, not shared, so an erasure reaches every row: advance_deletion
    deletes them outright, and the digest is REDACT as a second line.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    requirements_digest = models.CharField(max_length=64)
    item_digest = models.CharField(max_length=64)
    question_version = models.CharField(max_length=40)
    answer = models.CharField(max_length=20)
    #: The probability of `answer`.
    chance = models.FloatField()
    #: P(unrelated), whatever the answer: what the bar is measured on.
    unrelated = models.FloatField(default=0.0)
    model = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="cvrelevanceanswer_tenant_id_uniq"
            ),
            models.UniqueConstraint(
                fields=(
                    "tenant",
                    "student",
                    "requirements_digest",
                    "item_digest",
                    "question_version",
                ),
                name="cvrelevanceanswer_one_per_question",
            ),
        ]


class CVItemChoice(TenantScopedModel):
    """An item the student put back after the engine left it out of a CV for
    one programme (spec §7.2: "not asked again"). Read at the next generation.

    program_id, not a ForeignKey: the web tier writes this row and holds no
    grant on the shared catalogue (Application.program_id has the same shape).
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    program_id = models.UUIDField()
    section = models.CharField(max_length=20)
    item_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="cvitemchoice_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student", "program_id", "item_digest"),
                name="cvitemchoice_once_per_item",
            ),
        ]

