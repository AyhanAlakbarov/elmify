from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.base import ModelBase

from apps.accounts.models import StudentProfileVersion

#: Imported, not copied: the CHECK constraint below names these tuples directly,
#: so there is one source of truth and model-vs-vocabulary divergence is
#: impossible by construction. The migration freezes these values into SQL, so
#: the guard against the model drifting from the database as the vocabulary
#: grows is CI's `makemigrations --check`, not an assertion in this file.
from apps.funding.eligibility import KEYS as _ELIGIBILITY_KEYS
from apps.funding.eligibility import OPERATORS as _ELIGIBILITY_OPERATORS
from apps.reference_data import ISO_3166_ALPHA2_CODES, ISO_4217_CODES
from apps.tenancy.models import Membership, TenantScopedModel

_COUNTRIES = tuple(sorted(ISO_3166_ALPHA2_CODES))
_CURRENCIES = tuple(sorted(ISO_4217_CODES))


class RecommendationRun(TenantScopedModel):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        DRAFT_READY = "DRAFT_READY", "Draft ready"
        PUBLISHED = "PUBLISHED", "Published"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    profile_version = models.ForeignKey(StudentProfileVersion, on_delete=models.PROTECT)
    state = models.CharField(max_length=20, choices=State.choices, default=State.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    #: Bodies this run's pack left out because their verdict was not computed
    #: yet (spec §7.1). The sweep re-runs the student when one resolves
    #: RECOGNISED. Organisation ids, deliberately not a foreign key into the
    #: catalogue.
    pending_bodies = ArrayField(models.UUIDField(), default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant", "id"), name="run_tenant_id_uniq")]
        indexes = [
            models.Index(fields=("tenant", "dispatched_at"), name="run_dispatch_recovery_idx")
        ]


class EvidenceClaim(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source_url = models.URLField(max_length=2048)
    claim = models.TextField()
    last_checked_at = models.DateTimeField()

    @property
    def source_domain(self) -> str:
        """Hostname for display in the evidence row.

        The product UI shows the domain as a caption next to the labeled
        source link instead of the raw URL as anchor text; print surfaces
        (report, dossier) keep the full URL.
        """
        return urlsplit(self.source_url).hostname or self.source_url

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="evidence_tenant_id_uniq")
        ]


class RecommendationCandidate(TenantScopedModel):
    class State(models.TextChoices):
        VISIBLE = "VISIBLE", "Visible"
        REJECTED = "REJECTED", "Rejected"
        CHECKING = "CHECKING", "Checking"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(RecommendationRun, on_delete=models.CASCADE)
    evidence = models.ForeignKey(EvidenceClaim, on_delete=models.PROTECT)
    #: The catalog rows this candidate came from. Nullable because a
    #: student-named-programme request has neither, and PROTECT because the
    #: catalog is shared: deleting a programme out from under a published pack
    #: would leave a student holding a recommendation nothing explains.
    #: At most one is ever set -- an award is an application of its own.
    program = models.ForeignKey(
        "funding.Program", on_delete=models.PROTECT, null=True, blank=True,
        related_name="recommendation_candidates",
    )
    opportunity = models.ForeignKey(
        "funding.FundingOpportunity", on_delete=models.PROTECT, null=True, blank=True,
        related_name="recommendation_candidates",
    )
    program_name = models.CharField(max_length=300)
    funding_gap = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    eligible = models.BooleanField()
    state = models.CharField(max_length=20, choices=State.choices, default=State.VISIBLE)
    #: True while ``funding_gap``/``currency`` are an uncosted placeholder (set by
    #: a student-named-program request before deterministic costing exists for it)
    #: rather than a real figure — display and totals must suppress this candidate's
    #: funding gap while it's still True, instead of presenting 0.00 as if researched.
    funding_gap_is_placeholder = models.BooleanField(default=False)
    evidence_confidence = models.CharField(
        max_length=10,
        choices=[("HIGH", "High"), ("MEDIUM", "Medium"), ("LOW", "Low")],
        default="MEDIUM",
    )
    #: Tenant copies of the body's provenance verdict (spec §8), written by the
    #: worker: the web tier renders from these and never reads the catalogue.
    #: "" means not checked yet. No choices: research.models owns the enum and
    #: funding must not import it.
    provenance_reason_code = models.CharField(max_length=32, blank=True, default="")
    provenance_body_id = models.UUIDField(null=True, blank=True)
    #: Tenant copies the dashboard renders (student-dashboard spec §4, §5),
    #: written by the worker in research.services._publish. Facts about the
    #: programme or the award, never the student.
    institution_id = models.UUIDField(null=True, blank=True)
    institution_name = models.CharField(max_length=300, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    #: A programme's Program.degree_level; "" for an award (its levels, when a
    #: reader ever supplies them, ride in funding_card["degree_levels"]).
    degree_level = models.CharField(max_length=20, blank=True)
    application_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    application_fee_currency = models.CharField(max_length=3, blank=True)
    #: An award's programmes (FundingOpportunity.programs + .program), so the
    #: pack can be grouped under the funding without the catalogue.
    funds_program_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    #: An award's heading: holder, deadline, scope, route, tuition, living,
    #: amounts, unconfirmed. {} for a programme.
    funding_card = models.JSONField(default=dict, blank=True)
    #: The scholarship page's facts (research.candidate_details): city, length,
    #: languages, costs, what it covers, a return-home bond. About the
    #: programme or award, never the student.
    details = models.JSONField(default=dict, blank=True)
    #: Each published condition decided against THIS student (outcome, the
    #: funder's sentence, the reason) plus their stated yearly budget. Derived
    #: from the student's profile, so erasure redacts it (audit.redaction).
    fit = models.JSONField(default=dict, blank=True)

    class EligibilityStatus(models.TextChoices):
        ELIGIBLE = "ELIGIBLE", "Eligible"
        POSSIBLY_ELIGIBLE = "POSSIBLY_ELIGIBLE", "Possibly eligible—review needed"
        NOT_ELIGIBLE = "NOT_ELIGIBLE", "Not eligible"

    @property
    def eligibility_status(self) -> RecommendationCandidate.EligibilityStatus:
        """The three-state outcome the badge and the report render.

        LOW confidence is the review threshold, matching the rest of the
        workflow: LOW-confidence candidates are excluded from the pack's pool
        (services.py) and the evaluation gate is
        ``evidence_confidence != "LOW"`` (evaluation.py). MEDIUM is accepted
        there, so it is accepted here.
        """
        if not self.eligible:
            return self.EligibilityStatus.NOT_ELIGIBLE
        if self.evidence_confidence == "LOW":
            return self.EligibilityStatus.POSSIBLY_ELIGIBLE
        return self.EligibilityStatus.ELIGIBLE

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="candidate_tenant_id_uniq")
        ]


class PackVersion(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(RecommendationRun, on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    approved_version_id = models.UUIDField(null=True, editable=False)
    #: What changed in this version because a body's verdict changed (spec §7.3):
    #: [{"candidate_id", "candidate_name", "reason_code", "action": "removed" |
    #: "kept", "at"}]. candidate_id is what times a kept note out (the sweep).
    change_notes = models.JSONField(default=list, blank=True)
    #: The pack's coverage line, copied at build time (demand-cells spec 10.6)
    #: so the web tier renders it without reading the catalogue
    #: (catalog-read-split). It names the student's home cells, which is
    #: nationality, so it is REDACT (apps/audit/redaction.py).
    coverage = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="pack_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "run", "version"), name="pack_tenant_run_version_uniq"
            ),
        ]

    @property
    def current_version_id(self) -> UUID:
        return self.id


class PackCandidate(TenantScopedModel):
    """Membership of a candidate in a pack version's pool (a pack has many)."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    pack_version = models.ForeignKey(
        PackVersion, on_delete=models.CASCADE, related_name="pack_candidates"
    )
    candidate = models.ForeignKey(RecommendationCandidate, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="packcandidate_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "pack_version", "candidate"),
                name="pack_candidate_tenant_uniq",
            ),
        ]


class StudentDecision(TenantScopedModel):
    class Decision(models.TextChoices):
        REJECTED = "REJECTED", "Rejected"
        REPLACED = "REPLACED", "Replaced"
        CONSIDERED = "CONSIDERED", "Considered"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    candidate = models.ForeignKey(RecommendationCandidate, on_delete=models.PROTECT)
    actor = models.ForeignKey(Membership, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="studentdecision_tenant_id_uniq")
        ]


class Approval(TenantScopedModel):
    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    object_version = models.ForeignKey(
        PackVersion, on_delete=models.PROTECT, related_name="approvals"
    )
    actor = models.ForeignKey(Membership, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="approval_tenant_id_uniq")
        ]


class AuditEvent(TenantScopedModel):
    class ActorKind(models.TextChoices):
        HUMAN = "HUMAN", "Human"
        SYSTEM = "SYSTEM", "Platform, no actor"
        AGENT = "AGENT", "Autonomous agent"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    actor = models.ForeignKey(Membership, null=True, on_delete=models.PROTECT)
    #: Which of the three wrote this. `actor` alone cannot answer it: a
    #: platform write and a Phase 3 agent write both carry actor=NULL, and
    #: `phased requirements.md` §3.2 requires them to be distinguishable in
    #: the exported dossier. Counselor vs student stays derivable from the
    #: Membership's own role, so this discriminates only what the FK cannot.
    actor_kind = models.CharField(max_length=10, choices=ActorKind.choices, blank=True)
    event = models.CharField(max_length=100)
    object_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="event_tenant_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(actor_kind="HUMAN", actor__isnull=False)
                | models.Q(actor_kind__in=("SYSTEM", "AGENT"), actor__isnull=True),
                name="event_actor_kind_matches_actor",
            ),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        # HUMAN vs SYSTEM is fully determined by whether an actor is present,
        # so callers never pass it and no existing call site changes. AGENT is
        # the only value a caller must set explicitly, and setting it here
        # leaves it alone. Deriving in save() rather than in record_event
        # covers direct AuditEvent.objects.create() writers too --
        # apps/funding/services.py is one, and record_event never sees it.
        if not self.actor_kind:
            self.actor_kind = self.ActorKind.HUMAN if self.actor_id else self.ActorKind.SYSTEM
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class EvaluationExample(TenantScopedModel):
    """A counselor correction captured as a labeled example for future model evaluation.

    ``allowed_purposes`` is an explicit allow-list (e.g. ``tenant_evaluation``) so this
    tenant-scoped correction can never be silently reused for cross-tenant training or
    any purpose the tenant didn't consent to.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source_event = models.ForeignKey(AuditEvent, on_delete=models.PROTECT)
    input_schema_version = models.PositiveSmallIntegerField()
    expected_structured_result = models.JSONField()
    allowed_purposes = ArrayField(models.CharField(max_length=30), default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="evalexample_tenant_id_uniq")
        ]


class FundingFamily(models.TextChoices):
    GOVERNMENT_SCHOLARSHIP = "GOVERNMENT_SCHOLARSHIP"
    MULTILATERAL = "MULTILATERAL"
    INDUSTRIAL_SPONSORSHIP = "INDUSTRIAL_SPONSORSHIP"
    UNIVERSITY_WIDE = "UNIVERSITY_WIDE"
    DEPARTMENT_OR_PROGRAM = "DEPARTMENT_OR_PROGRAM"
    TUITION_WAIVER = "TUITION_WAIVER"
    STIPEND_OR_ASSISTANTSHIP = "STIPEND_OR_ASSISTANTSHIP"
    RELOCATION_HOUSING_INSURANCE_TRAVEL = "RELOCATION_HOUSING_INSURANCE_TRAVEL"
    RESEARCH_ECOSYSTEM_PATHWAY = "RESEARCH_ECOSYSTEM_PATHWAY"
    # Added 2026-08-29. AFFINITY_OR_DIASPORA is the only family whose eligibility
    # is keyed to descent rather than citizenship -- AGBU funds students "of
    # Armenian descent" worldwide -- so a nationality filter cannot answer it.
    # PRIVATE_FOUNDATION holds endowments with their own agenda (party Stiftungen,
    # Türk Eğitim Vakfı); INDUSTRIAL_SPONSORSHIP would imply an employer and a
    # bonding relationship that none of them has.
    AFFINITY_OR_DIASPORA = "AFFINITY_OR_DIASPORA"
    PRIVATE_FOUNDATION = "PRIVATE_FOUNDATION"


class OpportunityScope(models.TextChoices):
    GLOBAL = "GLOBAL"
    COUNTRY = "COUNTRY"
    INSTITUTION = "INSTITUTION"
    PROGRAM = "PROGRAM"
    #: Anchored to the organisation that holds the money, by registrable
    #: domain, not to an institution or programme (spec A, 2026-09-18).
    HOLDER = "HOLDER"


#: A hand-kept copy of apps.research.funding_judge._HOLDERS. The check
#: constraint cannot import it -- research imports funding, never the reverse --
#: so tests/funding/test_funding_holder.py is what stops the two drifting.
_HOLDER_VALUES = (
    "NATIONAL_GOVERNMENT",
    "SUBNATIONAL_GOVERNMENT",
    "POLITICAL_FOUNDATION",
    "RELIGIOUS",
    "PRIVATE_FOUNDATION",
    "EMPLOYER",
    "INTERGOVERNMENTAL",
    "REGIONAL_FUND",
    "EMBASSY_BILATERAL",
    "DIASPORA_AFFINITY",
    "PROFESSIONAL_BODY",
    "BANK_OR_LENDER",
    "ALUMNI",
    "INSTITUTION",
    "UNSTATED",
)


class Period(models.TextChoices):
    ONE_OFF = "ONE_OFF"
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"
    FULL_PROGRAM = "FULL_PROGRAM"


class EvidenceStrength(models.TextChoices):
    DIRECT = "DIRECT"
    COMPETITIVE = "COMPETITIVE"
    FORMAL_PIPELINE = "FORMAL_PIPELINE"
    ECOSYSTEM_CLUE = "ECOSYSTEM_CLUE"


class EvidenceVisibility(models.TextChoices):
    INTERNAL = "INTERNAL"
    STUDENT_FACING = "STUDENT_FACING"


class Institution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    canonical_key = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=300)
    country_code = models.CharField(max_length=2)
    official_website = models.URLField(max_length=2048)
    evidence_claims: models.ManyToManyField[OfficialEvidenceClaim, InstitutionEvidenceClaim] = (
        models.ManyToManyField(
            "OfficialEvidenceClaim",
            through="InstitutionEvidenceClaim",
            through_fields=("institution", "evidence_claim"),
        )
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(country_code__in=_COUNTRIES),
                name="institution_country_iso3166_alpha2",
            ),
            models.CheckConstraint(
                condition=models.Q(official_website__startswith="https://"),
                name="institution_official_website_https",
            ),
        ]


class CVFormatConfidence(models.TextChoices):
    VERIFIED = "VERIFIED"
    EXTRACTED = "EXTRACTED"
    UNVERIFIED = "UNVERIFIED"
    #: The page said something about the CV's format and three readings did
    #: not agree on it (or agreed it names a template this engine cannot
    #: render). cv_format_requirement is `any` -- the no-egress default -- and
    #: the sentence is in cv_constraints under `undecided`, where the
    #: student sees it. Distinct from UNVERIFIED (nothing has looked yet).
    UNDECIDED = "UNDECIDED"
    #: We read the page and nothing on it looked like a CV requirement at all --
    #: `derive.candidates` returned empty, so no judge call was made. Distinct
    #: from EXTRACTED, which means the page DID discuss the CV and stated no
    #: format rule. The two used to share EXTRACTED, which made "this programme
    #: asks for no CV" and "our finder did not recognise the page's language"
    #: the same stored state -- and the second is our failure, not the page's.
    #: Read it as a claim about our reading, never about the page.
    NO_CV_FOUND = "NO_CV_FOUND"


class Program(models.Model):
    class DegreeLevel(models.TextChoices):
        MASTER = "MASTER"

    class AcademicTrack(models.TextChoices):
        TAUGHT = "taught"
        RESEARCH = "research"

    class ProvisionType(models.TextChoices):
        SINGLE = "SINGLE"
        JOINT = "JOINT"

    class CVFormatRequirement(models.TextChoices):
        EUROPASS_REQUIRED = "europass_required"
        EUROPASS_PREFERRED = "europass_preferred"
        ANY = "any"
        FUNDER_TEMPLATE = "funder_template"
        STRUCTURED_FIELDS_ONLY = "structured_fields_only"

    CVFormatConfidence = CVFormatConfidence

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    institution = models.ForeignKey(Institution, null=True, on_delete=models.PROTECT)
    #: The universities that award a jointly-provided programme. EACEA's
    #: Erasmus Mundus listing is one row per consortium, so this is the common
    #: case rather than the exception -- see the 2026-09-13 providers design.
    awarding_institutions: models.ManyToManyField[Institution, ProgramAwardingInstitution] = (
        models.ManyToManyField(
            Institution,
            through="ProgramAwardingInstitution",
            through_fields=("program", "institution"),
            related_name="awarded_programs",
        )
    )
    #: db_default as well as default: catalogue writers issue raw SQL, and a plain
    #: INSERT omitting these columns must still produce a row the constraint
    #: below accepts.
    provision_type = models.CharField(
        max_length=10,
        choices=ProvisionType.choices,
        default=ProvisionType.SINGLE,
        db_default=ProvisionType.SINGLE,
    )
    #: The provider string exactly as scraped, on JOINT rows only. This is the
    #: curation queue's payload: a human reads it without opening a snapshot.
    provider_text = models.CharField(max_length=500, blank=True, default="", db_default="")
    #: The single registrable domain every OfficialEvidenceClaim of this programme
    #: sits on, or "" when they disagree or there are none (institution
    #: provenance gate spec §3). Written from the evidence URLs by the catalogue
    #: writer, never from the page's name; the pool joins it to a RECOGNISED
    #: verdict's `domain`. db_default for raw-SQL catalogue writers.
    evidence_domain = models.CharField(
        max_length=253, blank=True, default="", db_default="", db_index=True
    )
    #: Whether every evidence URL is on that domain's main host or an
    #: institutional subdomain -- no blog, wiki, forum, ~user path or platform.
    evidence_institutional = models.BooleanField(default=False, db_default=False)
    #: The registrable domain of the page that CREATED this row, and part of its
    #: identity (the uniqueness constraint below): a page from another domain
    #: naming the same university and programme gets its own row instead of
    #: attaching its claims to this one (provenance gate spec §3). Set on
    #: create; only `backfill_evidence_domain` may fill an empty one. Stable the
    #: way canonical_key is -- by writers, not a trigger: catalogue tables carry
    #: none (tests/funding/test_catalog_models.py). Not in location_key, which
    #: is a place that LOCATION/CITY gates compare.
    origin_domain = models.CharField(
        max_length=253, blank=True, default="", db_default="", editable=False
    )
    canonical_key = models.CharField(max_length=255)
    name = models.CharField(max_length=300)
    campus_name = models.CharField(max_length=200)
    city = models.CharField(max_length=200)
    country_code = models.CharField(max_length=2)
    location_key = models.CharField(max_length=255)
    degree_level = models.CharField(max_length=20, choices=DegreeLevel.choices)
    #: Which TRACK-scoped catalog rules apply (R-023 caps a taught CV at 2
    #: pages, R-024 a research CV at 3). It lives here, not on CVContent,
    #: because it is a property of the programme being applied to rather than
    #: of the applicant. Blank means not established -- see
    #: constraints.resolve_track for what happens then.
    academic_track = models.CharField(
        max_length=20, choices=AcademicTrack.choices, blank=True, default=""
    )
    #: Set by the same page read that sets academic_track (spec §2): a page
    #: requiring a portfolio keys a different defaults row.
    portfolio_led = models.BooleanField(default=False)
    teaching_languages = ArrayField(models.CharField(max_length=100))
    duration_months = models.PositiveSmallIntegerField()
    cv_format_requirement = models.CharField(
        max_length=30, choices=CVFormatRequirement.choices, default=CVFormatRequirement.ANY
    )
    #: Free text as printed on the funder's page ("2026/27", "Edition XI, 2026"),
    #: not a parsed cycle -- the CSV's own values are prose, see Task 10.
    cv_format_verified_for_cycle = models.CharField(max_length=40, null=True, blank=True)
    cv_format_source_url = models.URLField(max_length=2048, blank=True)
    cv_format_confidence = models.CharField(
        max_length=20, choices=CVFormatConfidence.choices, default=CVFormatConfidence.UNVERIFIED
    )
    cv_constraints = models.JSONField(default=list, blank=True)
    #: Typed generation directives read off the programme's own page:
    #: [{"action": "include" | "order" | "emphasise", "target": <CVContent
    #: field or section>, "value": <order value or None>, "rule_text":
    #: <verbatim sentence>, "source_url": ...}]. Written by
    #: documents.derive.derive_page_rules with cv_constraints in one update;
    #: read by generation (include), render (order, emphasise) and gaps
    #: (include with no fact). Never carries free text into a document: the
    #: action and target are closed vocabularies, see derive.Directive.
    cv_directives = models.JSONField(default=list, blank=True)
    #: What the page states about its reference letters, one record per field
    #: a sentence stated: [{"field": "count" | "kind" | "mode" |
    #: "institutional_email_required" | "due", "value": <closed value from
    #: documents.grammar.REFEREE_FIELDS>, "date": <the referee deadline as
    #: written, or "">, "conditional": bool, "condition": <kind or "">,
    #: "rule_text": <verbatim sentence>, "source_url": ...}]. Written by
    #: derive_page_rules and rederive_rules; read by the application-route
    #: catalogue. A field with no record was not stated.
    referee_requirements = models.JSONField(default=list, blank=True)

    class LetterRequired(models.TextChoices):
        REQUIRED = "required"
        OPTIONAL = "optional"
        NOT_REQUESTED = "not_requested"
        UNKNOWN = "unknown"

    letter_required = models.CharField(
        max_length=20, choices=LetterRequired.choices, default=LetterRequired.UNKNOWN
    )
    evidence_claims: models.ManyToManyField[OfficialEvidenceClaim, ProgramEvidenceClaim] = (
        models.ManyToManyField(
            "OfficialEvidenceClaim",
            through="ProgramEvidenceClaim",
            through_fields=("program", "evidence_claim"),
        )
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("institution", "canonical_key", "location_key", "origin_domain"),
                name="program_institution_key_location_uniq",
                nulls_distinct=False,
            ),
            #: SINGLE carries an institution and no provider text; JOINT carries
            #: provider text and no institution. In the database, not a
            #: validator: a raw-SQL catalogue write never runs model code.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        provision_type="SINGLE", institution__isnull=False, provider_text=""
                    )
                    | models.Q(provision_type="JOINT", institution__isnull=True)
                ),
                name="program_provision_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(country_code__in=_COUNTRIES),
                name="program_country_iso3166_alpha2",
            ),
            models.CheckConstraint(
                condition=models.Q(degree_level__in=("MASTER",)), name="program_degree_level_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(teaching_languages__len__gte=1),
                name="program_teaching_languages_nonempty",
            ),
            models.CheckConstraint(
                condition=models.Q(teaching_languages__len__lte=10),
                name="program_teaching_languages_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_months__range=(1, 60)),
                name="program_duration_months_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    cv_format_requirement__in=(
                        "europass_required",
                        "europass_preferred",
                        "any",
                        "funder_template",
                        "structured_fields_only",
                    )
                ),
                name="program_cv_format_requirement_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(cv_format_confidence__in=CVFormatConfidence.values),
                name="program_cv_format_confidence_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    letter_required__in=("required", "optional", "not_requested", "unknown")
                ),
                name="program_letter_required_valid",
            ),
        ]


class CatalogWriteBlocked(RuntimeError):
    """A shared-catalog write matched no rows.

    Catalog tables carry a SELECT-only shared_catalog_select RLS policy plus a
    runtime_engine_write policy, so any role other than runtime_engine (or the
    table owner) has its UPDATE/DELETE silently match nothing. Every catalog
    writer checks the row count and raises this instead of reporting a write
    that never happened. Run catalog writes under DATABASE_ROLE=runtime_engine.
    (runtime_web holds no grant on these tables at all, so there it is a
    "permission denied" error, not zero rows.)
    """


def update_exactly(queryset: models.QuerySet[Any], *, error: str, **fields: object) -> None:
    """`queryset.update(**fields)`, raising `CatalogWriteBlocked(error)` unless
    it changed exactly one row -- the "catalog write changed no rows" guard
    every catalog writer needs, in one place instead of pasted per caller."""
    if queryset.update(**fields) != 1:
        raise CatalogWriteBlocked(error)


class ProgramStatement(models.Model):
    """One sentence a programme's own page states as a requirement.

    A projection, not a ledger: the archived snapshot is the record of what
    the page said, this table is the queryable read of it, and re-reading a
    page replaces a programme's rows. There is no `supersedes` column here and
    there is one on OfficialSourceSnapshot.

    THE SENTENCE IS THE IDENTITY. `text` is the page's own words, verified
    against the archived page before it is written; `label` is a short name
    a model gave it, for display and for exact-name matching in tailoring,
    and never decides whether two rows are the same. Keying on the label was
    what made the catalog a coin flip: the same page read three times gave
    13, 17 and 10 rows (spec, "Why").

    Deliberately NOT routed through OfficialEvidenceClaim.claim_class: that
    field exists only on the phase-5 discovery branch. Lineage comes from the
    snapshot FK.
    """

    class Kind(models.TextChoices):
        COMPETENCY = "COMPETENCY"
        DOCUMENT = "DOCUMENT"
        FORMAT = "FORMAT"
        LANGUAGE = "LANGUAGE"
        OTHER = "OTHER"

    class Requirement(models.TextChoices):
        REQUIRED = "REQUIRED"
        DESIRED = "DESIRED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="statements")
    #: PROTECT because a statement with no readable provenance is exactly the
    #: unsourced claim this codebase refuses to store.
    snapshot = models.ForeignKey("OfficialSourceSnapshot", on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    requirement = models.CharField(max_length=10, choices=Requirement.choices)
    #: The sentence as the page prints it. Uniqueness per programme is
    #: enforced by the writer on a normalised form (casefold, whitespace
    #: collapsed); a DB constraint on the raw column would let "Mathematics."
    #: and "mathematics" coexist.
    text = models.CharField(max_length=1_000)
    label = models.CharField(max_length=200)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(requirement__in=("REQUIRED", "DESIRED")),
                name="program_statement_requirement_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=("COMPETENCY", "DOCUMENT", "FORMAT", "LANGUAGE", "OTHER")
                ),
                name="program_statement_kind_valid",
            ),
        ]


class CatalogRule(models.Model):
    """One researched CV rule, as data the render path can enforce.

    Shared across every tenant and never tenant-editable: a funder's
    requirement is the same fact for every agency, and one agency editing it
    would silently change another agency's output. Per-tenant judgement lives
    in ConstraintOverride, which is a TenantScopedModel.

    `key` is deliberately a plain CharField rather than a choices field: the
    authoritative list is _CONSTRAINT_KEYS in apps/documents/constraints.py,
    and importing it here would invert the dependency direction
    (apps.documents.render already imports this module). It is validated where
    it is written (the seed command) and where it is read
    (ConstraintRule.model_validate in resolve_rules), so an unknown key cannot
    reach a render.
    """

    class ScopeKind(models.TextChoices):
        UNIVERSAL = "UNIVERSAL"
        TRACK = "TRACK"
        COUNTRY = "COUNTRY"
        INSTITUTION = "INSTITUTION"
        FUNDER = "FUNDER"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: NOT unique on its own. One researched rule can produce more than one
    #: enforceable constraint: R-032 ("US/Canada/UK/Australia: no photo, DOB,
    #: marital status, or gender") is both photo_allowed=false and
    #: date_of_birth_allowed=false, and R-033 is both again. Uniqueness is on
    #: (rule_id, key). Note the consequence for ConstraintOverride, which is
    #: keyed on rule_id alone: accepting R-032 accepts both of its keys at
    #: once, which is the right behaviour for one rule a student was shown.
    rule_id = models.CharField(max_length=20)
    scope_kind = models.CharField(max_length=20, choices=ScopeKind.choices)
    #: A list, not a scalar: R-032's scope is US/CA/UK/AU -- four countries in
    #: one rule. Country values are ISO 3166-1 alpha-2, so the CSV's "UK" is
    #: stored as "GB" to match Program.country_code.
    scope_values = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    key = models.CharField(max_length=40)
    value = models.JSONField()
    enforcement = models.CharField(max_length=20)
    rule_text = models.TextField()
    source_url = models.URLField(max_length=2048, blank=True)
    #: Free text as printed on the funder's page, never a parsed date -- the
    #: CSV's own values are prose ("evergreen", "reverify", "2026/2027",
    #: "cycle label unconfirmed"). Same decision, and same reason, as
    #: Program.cv_format_verified_for_cycle. Expiry never blocks a render: a
    #: page not re-read is not evidence the rule changed, and a rule that
    #: switched itself off on a date would leave a student with no CV at their
    #: deadline.
    verified_for_cycle = models.CharField(max_length=200, blank=True)
    confidence = models.CharField(max_length=10)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("rule_id", "key"), name="catalog_rule_id_key_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    scope_kind__in=("UNIVERSAL", "TRACK", "COUNTRY", "INSTITUTION", "FUNDER")
                ),
                name="catalog_rule_scope_kind_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_kind="UNIVERSAL", scope_values__len=0)
                    | ~models.Q(scope_kind="UNIVERSAL") & ~models.Q(scope_values__len=0)
                ),
                name="catalog_rule_scope_values_match_kind",
            ),
        ]


class FundingOpportunity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    canonical_key = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=300)
    family = models.CharField(max_length=50, choices=FundingFamily.choices)
    scope_type = models.CharField(max_length=20, choices=OpportunityScope.choices)
    country_code = models.CharField(max_length=2, null=True)
    institution = models.ForeignKey(Institution, null=True, on_delete=models.PROTECT)
    program = models.ForeignKey(Program, null=True, on_delete=models.PROTECT)
    programs: models.ManyToManyField[Program, FundingOpportunityProgram] = models.ManyToManyField(
        Program,
        through="FundingOpportunityProgram",
        through_fields=("opportunity", "program"),
        related_name="funding_opportunities",
    )
    evidence_claims: models.ManyToManyField[
        OfficialEvidenceClaim, FundingOpportunityEvidenceClaim
    ] = models.ManyToManyField(
        "OfficialEvidenceClaim",
        through="FundingOpportunityEvidenceClaim",
        through_fields=("opportunity", "evidence_claim"),
    )
    #: ~19 of the researched format rules belong to funders, not programmes
    #: (Rhodes and SISGP mandate their own templates; AMIR, GLOBED, MathMods
    #: and WE-TEAM require Europass; Stipendium Hungaricum and NAWA take no CV
    #: at all). Blank means the funder states nothing and the programme decides.
    cv_format_requirement = models.CharField(
        max_length=30, choices=Program.CVFormatRequirement.choices, blank=True, default=""
    )
    # Written by apps.research.funding_reader (2026-09-13 spec section 4.4).
    # Blank on every row an older writer created. `served` is the only flag
    # the student-facing path may read: True needs agreement == AGREED and a
    # lead that can support a claim, and the writer is the only place that
    # sets it. `agreement` and `kind` are kept even when blank so a row's
    # provenance stays queryable.
    kind = models.CharField(max_length=32, blank=True, default="")
    #: Who owns the money (funding_judge._HOLDERS). Empty for rows written
    #: before the holder axis existed; the reader writes it on every new row.
    holder = models.CharField(max_length=24, blank=True, default="")
    #: The body that holds the money. A string reference, not an import:
    #: research imports funding and never the reverse, and Django resolves this
    #: after both apps load.
    organisation = models.ForeignKey(
        "research.Organisation", on_delete=models.PROTECT, null=True, blank=True
    )
    #: The registrable domain of the holder's own site. Superseded by
    #: `organisation` above and kept only until a test asserts every HOLDER row
    #: carries the FK -- dropping a column in the same change that backfills it
    #: leaves no way to check the backfill was right.
    holder_domain = models.CharField(max_length=253, blank=True, default="", db_index=True)
    holder_name = models.CharField(max_length=300, blank=True, default="")
    agreement = models.CharField(max_length=10, blank=True, default="")
    served = models.BooleanField(default=False)
    money_form = models.CharField(max_length=16, blank=True, default="")
    route = models.CharField(max_length=30, blank=True, default="")
    nationality_shape = models.CharField(max_length=16, blank=True, default="")
    internationals_included = models.CharField(max_length=8, blank=True, default="")
    obligation = models.CharField(max_length=80, blank=True, default="")
    found_via = models.CharField(max_length=60, blank=True, default="")
    # An operator's decision on a row the readings could not serve alone
    # (2026-09-14 funding-reader-precision spec 2.6). Bound to the page version
    # it was made on: a re-read of that same version never overrides it, and
    # only that page, changed, reopens it.
    review = models.CharField(max_length=10, blank=True, default="")
    review_note = models.CharField(max_length=200, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_sha256 = models.CharField(max_length=64, blank=True, default="")
    #: The decided fields the readings disagreed on, ";"-joined, for the reviewer.
    disputed = models.CharField(max_length=200, blank=True, default="")
    #: The subset of `disputed` that did NOT stop this row being served: a
    #: detail the readings split on, blanked to UNSTATED on the row and named
    #: here so the card can show the caveat beside the quote (spec 8.6). The
    #: blanked value is deliberately indistinguishable from a field the page
    #: never stated; THIS column is what tells the two apart. Never an
    #: existence field -- a split on `offered`, `holder` or `scope` makes the
    #: whole award UNAGREED, so it never reaches a served row at all.
    unconfirmed = models.CharField(max_length=200, blank=True, default="")
    #: The intake a dated negation ruled this award out for, as the page wrote
    #: it, and the sentence that did it (spec 3.5.3). Blank when no negation
    #: won; the quote is the marker, because a suspension with no intake named
    #: leaves `suspended_for` empty and is still a suspension.
    suspended_for = models.CharField(max_length=24, blank=True, default="")
    suspension_quote = models.CharField(max_length=300, blank=True, default="")
    # The card's own fields (spec 8.3, 10.4; build item 13), written by
    # apps.research.funding_reader from what the readings agreed a line states.
    # Blank on a row no reader has written since. A value the readings split on
    # is UNSTATED here and named in `unconfirmed`, so a blank and a split are
    # never confused. `tuition`/`living` keep the LEVEL that `_benefit_kinds`
    # reduces to a benefit row -- without them "a full waiver" and "a 10%
    # discount" are the same row, and a waiver's card has no amount to show.
    tuition = models.CharField(max_length=10, blank=True, default="")
    living = models.CharField(max_length=10, blank=True, default="")
    timing = models.CharField(max_length=12, blank=True, default="")
    cycle = models.CharField(max_length=20, blank=True, default="")
    duration_text = models.CharField(max_length=40, blank=True, default="")
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Which verbatim line stated each card field: {"timing": "...", "amount:LIVING": "..."}.
    card_quotes = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(family__in=FundingFamily.values),
                name="funding_opportunity_family_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(scope_type__in=OpportunityScope.values),
                name="funding_opportunity_scope_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(scope_type__in=OpportunityScope.values)
                    | models.Q(
                        scope_type="GLOBAL",
                        country_code__isnull=True,
                        institution__isnull=True,
                        program__isnull=True,
                    )
                    | models.Q(
                        scope_type="COUNTRY",
                        country_code__isnull=False,
                        institution__isnull=True,
                        program__isnull=True,
                    )
                    | models.Q(
                        scope_type="INSTITUTION",
                        country_code__isnull=True,
                        institution__isnull=False,
                        program__isnull=True,
                    )
                    | models.Q(
                        scope_type="PROGRAM",
                        country_code__isnull=True,
                        institution__isnull=True,
                        program__isnull=False,
                    )
                    # A holder row hangs off its organisation, nothing else:
                    # without it the row cannot be found again, and a string
                    # domain cannot carry the register's second domain, its
                    # cadence or its read state.
                    | models.Q(
                        scope_type="HOLDER",
                        country_code__isnull=True,
                        institution__isnull=True,
                        program__isnull=True,
                        organisation__isnull=False,
                    )
                ),
                name="funding_opportunity_scope_shape_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(country_code__isnull=True)
                | models.Q(country_code__in=_COUNTRIES),
                name="funding_opportunity_country_iso3166_alpha2",
            ),
            models.CheckConstraint(
                condition=models.Q(agreement="")
                # WITHDRAWN: a re-read of the only page supporting this row no
                # longer decides it (spec 3.5.4). Its quotes are kept.
                | models.Q(agreement__in=("AGREED", "UNAGREED", "ABSTAINED", "WITHDRAWN")),
                name="funding_opportunity_agreement_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(kind="")
                | models.Q(
                    kind__in=(
                        "I0_HOLDER_AWARD",
                        "I1_UNIVERSITY_WIDE", "I2_PROGRAMME_ATTACHED",
                        "I3_STIPEND_OR_ASSISTANTSHIP", "I4_RESEARCH_PATHWAY",
                        "I5_FUNDED_DUAL_DEGREE", "I6_RELOCATION_HOUSING_TRAVEL",
                        "I7_PAID_PLACEMENT",
                    )
                ),
                name="funding_opportunity_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(review__in=("", "ACCEPTED", "REJECTED")),
                name="funding_opportunity_review_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(holder="") | models.Q(holder__in=_HOLDER_VALUES),
                name="funding_opportunity_holder_valid",
            ),
            # An award its own page withdrew may not be served. Both writers
            # already satisfied this by construction -- `_served` needs
            # offered == YES and `_suspension` only writes on NO -- so it was an
            # invariant nothing enforced, until `served` became student-facing
            # and an operator's accept could set it on a row in the review
            # queue. `suspension_quote` is the marker rather than
            # `suspended_for`: a suspension naming no intake leaves that blank
            # and is still a suspension (see the field's own comment).
            models.CheckConstraint(
                condition=models.Q(served=False) | models.Q(suspension_quote=""),
                name="funding_opportunity_served_not_suspended",
            ),
            models.CheckConstraint(
                condition=models.Q(tuition__in=("", "NONE", "PARTIAL", "FULL", "UNSTATED"))
                & models.Q(living__in=("", "NONE", "PARTIAL", "FULL", "UNSTATED")),
                name="funding_opportunity_coverage_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    timing__in=("", "PRE_ARRIVAL", "POST_ARRIVAL", "EITHER", "UNSTATED")
                ),
                name="funding_opportunity_timing_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    cycle__in=(
                        "", "ANNUAL_FIXED", "ROLLING", "WITH_ADMISSION_CYCLE", "ONE_OFF",
                        "UNSTATED",
                    )
                ),
                name="funding_opportunity_cycle_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_months__isnull=True)
                | models.Q(duration_months__gte=1, duration_months__lte=120),
                name="funding_opportunity_duration_months_range",
            ),
        ]


class FundingBenefit(models.Model):
    class Kind(models.TextChoices):
        TUITION = "TUITION"
        STIPEND = "STIPEND"
        ASSISTANTSHIP = "ASSISTANTSHIP"
        HOUSING = "HOUSING"
        INSURANCE = "INSURANCE"
        TRAVEL = "TRAVEL"
        RELOCATION = "RELOCATION"
        OTHER = "OTHER"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    opportunity = models.ForeignKey(FundingOpportunity, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    currency = models.CharField(max_length=3, null=True)
    period = models.CharField(max_length=20, choices=Period.choices)
    description = models.CharField(max_length=2_000)
    # Design §12, added 2026-08-29: a repayable award is not coverage. Zero for a grant.
    # AKF's International Scholarship Programme is half interest-free loan, so recording
    # it as a grant overstates coverage by half and understates the affordability gap by
    # exactly the repayable part. The service charge is carried as the funder's own
    # words, not a rate: AKF levies one on the loan portion without publishing a base to
    # compute it against, and a number invented here would be spent by a student.
    repayable_share = models.DecimalField(max_digits=4, decimal_places=3, default=Decimal("0"))
    service_charge_text = models.CharField(max_length=1_000, blank=True, default="")
    #: The figure as the page printed it, the bound it was stated with, and the
    #: line (build item 13). `amount` is set only when code could read one
    #: figure in a confirmed currency from `amount_text`; otherwise the card
    #: shows the text and nothing counts it. Blank on a row no reader wrote.
    amount_text = models.CharField(max_length=40, blank=True, default="")
    amount_bound = models.CharField(max_length=8, blank=True, default="")
    amount_quote = models.CharField(max_length=1_000, blank=True, default="")
    evidence_claims: models.ManyToManyField[OfficialEvidenceClaim, FundingBenefitEvidenceClaim] = (
        models.ManyToManyField(
            "OfficialEvidenceClaim",
            through="FundingBenefitEvidenceClaim",
            through_fields=("benefit", "evidence_claim"),
        )
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=(
                        "TUITION",
                        "STIPEND",
                        "ASSISTANTSHIP",
                        "HOUSING",
                        "INSURANCE",
                        "TRAVEL",
                        "RELOCATION",
                        "OTHER",
                    )
                ),
                name="funding_benefit_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(period__in=Period.values), name="funding_benefit_period_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(amount__isnull=True, currency__isnull=True)
                | models.Q(amount__isnull=False, currency__isnull=False),
                name="funding_benefit_amount_currency_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__isnull=True) | models.Q(amount__gte=0),
                name="funding_benefit_amount_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(currency__isnull=True) | models.Q(currency__in=_CURRENCIES),
                name="funding_benefit_currency_iso4217",
            ),
            models.CheckConstraint(
                condition=models.Q(repayable_share__gte=0, repayable_share__lte=1),
                name="funding_benefit_repayable_share_fraction",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_bound__in=("", "EXACT", "UP_TO", "AT_LEAST")),
                name="funding_benefit_amount_bound_valid",
            ),
        ]


class CostComponent(models.Model):
    class Kind(models.TextChoices):
        TUITION = "TUITION"
        APPLICATION_FEE = "APPLICATION_FEE"
        HOUSING = "HOUSING"
        FOOD = "FOOD"
        TRANSPORT = "TRANSPORT"
        UTILITIES = "UTILITIES"
        INSURANCE = "INSURANCE"
        OTHER = "OTHER"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    program = models.ForeignKey(Program, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    period = models.CharField(max_length=20, choices=Period.choices)
    evidence_claims: models.ManyToManyField[OfficialEvidenceClaim, CostComponentEvidenceClaim] = (
        models.ManyToManyField(
            "OfficialEvidenceClaim",
            through="CostComponentEvidenceClaim",
            through_fields=("cost_component", "evidence_claim"),
        )
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=(
                        "TUITION",
                        "APPLICATION_FEE",
                        "HOUSING",
                        "FOOD",
                        "TRANSPORT",
                        "UTILITIES",
                        "INSURANCE",
                        "OTHER",
                    )
                ),
                name="cost_component_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="cost_component_amount_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(currency__in=_CURRENCIES), name="cost_component_currency_iso4217"
            ),
            models.CheckConstraint(
                condition=models.Q(period__in=Period.values), name="cost_component_period_valid"
            ),
        ]


class BenefitRule(models.Model):
    class Kind(models.TextChoices):
        ELIGIBILITY = "ELIGIBILITY"
        AMOUNT = "AMOUNT"
        CAPACITY = "CAPACITY"
        GEOGRAPHIC_SCOPE = "GEOGRAPHIC_SCOPE"
        DEADLINE = "DEADLINE"
        # Added 2026-08-29 (spec §4). APPLICANT_CONDITION holds the non-nationality
        # gates that close a route to a student who satisfies every published academic
        # bar: ADB-JSP's two years of post-degree experience, its age cap and means
        # test, Konrad-Adenauer's values endorsement. A model that filters only on
        # nationality names routes the student then discovers are shut, which the spec
        # calls worse than omitting them.
        # RETURN_SERVICE is deliberately NOT a fifth condition type: it filters nobody.
        # It is a post-award obligation -- ADB-JSP, Bolashak and YLSY all bind the
        # graduate to return home -- and therefore a disclosure duty, because a bonded
        # award is a materially different product from an unbonded one.
        APPLICANT_CONDITION = "APPLICANT_CONDITION"
        RETURN_SERVICE = "RETURN_SERVICE"
        OTHER = "OTHER"

    class ConditionType(models.TextChoices):
        """The pre-vocabulary condition names, deprecated in favour of `key`/`operator`.

        Task 6's data migration backfills `key`/`operator` from these six values on
        every existing row; it never clears `condition_type`, because
        benefit_rule_condition_type_shape_valid and benefit_rule_comparable_shape_valid
        still require it for kind="APPLICANT_CONDITION" and still admit only these six
        values with their numeric shape. Reconciling those two constraints with the
        full `key` vocabulary -- so a row can carry e.g. key="GENDER" under this kind
        without a legacy condition_type -- is a later task's work, not this one's.
        """

        WORK_EXPERIENCE = "WORK_EXPERIENCE"
        AGE_CAP = "AGE_CAP"
        MEANS_TEST = "MEANS_TEST"
        AFFILIATION = "AFFILIATION"
        # Added 2026-08-29. Neither carries a number, so both sit with AFFILIATION on
        # the unquantifiable side and escalate to a consultant. LANGUAGE is a funder's
        # bar on the applicant -- a party foundation demanding C1 German for an
        # English-taught degree -- not the programme's teaching language, which lives
        # on Program. GUARANTOR is design §12's hard gate that is not a number.
        LANGUAGE = "LANGUAGE"
        GUARANTOR = "GUARANTOR"

    class ComparableUnit(models.TextChoices):
        MONTHS = "MONTHS"
        HOURS = "HOURS"

    class Scope(models.TextChoices):
        GLOBAL = "GLOBAL"
        COUNTRY = "COUNTRY"
        CITY = "CITY"
        PROGRAM = "PROGRAM"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    benefit = models.ForeignKey(FundingBenefit, on_delete=models.PROTECT, null=True, blank=True)
    #: The shared vocabulary. condition_type is the pre-vocabulary name and stays
    #: on every row -- see ConditionType's own docstring for why it is never
    #: cleared and what still has to happen before a wider set of keys can be
    #: written under kind="APPLICANT_CONDITION".
    key = models.CharField(max_length=24, blank=True, default="")
    operator = models.CharField(max_length=10, blank=True, default="")
    value = models.CharField(max_length=200, blank=True, default="")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    rule_text = models.CharField(max_length=4_000)
    condition_type = models.CharField(max_length=30, choices=ConditionType.choices, null=True)
    # The unit is a function of the condition everywhere but one: RETURN_SERVICE is
    # months, AGE_CAP is years, MEANS_TEST is money and is the only one that carries a
    # currency. AFFILIATION, LANGUAGE and GUARANTOR have no comparable at all --
    # "endorses Christian Democratic values" is not a number, and pretending otherwise
    # is how a subjective condition becomes a silent filter. rule_text keeps the
    # funder's own sentence regardless; this is a second reading of it, never a
    # replacement.
    comparable_value = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    comparable_currency = models.CharField(max_length=3, null=True)
    # The exception, added 2026-08-29: WORK_EXPERIENCE is published in two units and
    # both are load-bearing. Chevening asks for 2,800 hours and the Swedish Institute
    # for 3,000 (of Uzbek applicants only); ADB-JSP asks for two years. Converting
    # between them needs a working-hours-per-month figure no funder publishes, so the
    # unit is recorded and an hours bar escalates rather than being guessed into
    # months -- where 2,800 would read as 233 years and shut every route in the catalog.
    comparable_unit = models.CharField(max_length=10, choices=ComparableUnit.choices, null=True)
    scope_type = models.CharField(max_length=20, choices=Scope.choices)
    country_code = models.CharField(max_length=2, null=True)
    location_key = models.CharField(max_length=255, null=True)
    program = models.ForeignKey(Program, null=True, on_delete=models.PROTECT)
    evidence_claims: models.ManyToManyField[OfficialEvidenceClaim, BenefitRuleEvidenceClaim] = (
        models.ManyToManyField(
            "OfficialEvidenceClaim",
            through="BenefitRuleEvidenceClaim",
            through_fields=("benefit_rule", "evidence_claim"),
        )
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=(
                        "ELIGIBILITY",
                        "AMOUNT",
                        "CAPACITY",
                        "GEOGRAPHIC_SCOPE",
                        "DEADLINE",
                        "APPLICANT_CONDITION",
                        "RETURN_SERVICE",
                        "OTHER",
                    )
                ),
                name="benefit_rule_kind_valid",
            ),
            models.CheckConstraint(
                # A biconditional, not a disjunction: APPLICANT_CONDITION requires a
                # condition_type AND every other kind forbids one. Written as a plain
                # OR, the second branch would silently admit an APPLICANT_CONDITION
                # row with no condition_type -- an uninterpretable rule.
                condition=models.Q(kind="APPLICANT_CONDITION", condition_type__isnull=False)
                | (
                    ~models.Q(kind="APPLICANT_CONDITION")
                    & models.Q(condition_type__isnull=True)
                ),
                name="benefit_rule_condition_type_shape_valid",
            ),
            models.CheckConstraint(
                # Every condition_type branch carries an explicit isnull=False. A CHECK
                # constraint is satisfied by TRUE *or NULL*, and in SQL a NULL
                # condition_type makes `condition_type = 'MEANS_TEST'` evaluate to NULL
                # rather than FALSE -- so without these guards the whole OR collapses to
                # NULL for a null-typed row and Postgres waves it through. `FALSE AND
                # NULL` is FALSE, which is what the guard buys.
                condition=(
                    models.Q(
                        condition_type__isnull=False,
                        condition_type="MEANS_TEST",
                        comparable_value__isnull=False,
                        comparable_currency__isnull=False,
                    )
                    | models.Q(
                        condition_type__isnull=False,
                        condition_type__in=("WORK_EXPERIENCE", "AGE_CAP"),
                        comparable_value__isnull=False,
                        comparable_currency__isnull=True,
                    )
                    | models.Q(
                        condition_type__isnull=False,
                        condition_type__in=("AFFILIATION", "LANGUAGE", "GUARANTOR"),
                        comparable_value__isnull=True,
                        comparable_currency__isnull=True,
                    )
                    | models.Q(
                        kind="RETURN_SERVICE",
                        condition_type__isnull=True,
                        comparable_value__isnull=False,
                        comparable_currency__isnull=True,
                    )
                    | (
                        # RETURN_SERVICE is excluded from this catch-all deliberately:
                        # its condition_type is null too, so a plain "everything else is
                        # empty" branch would admit a bond of unknown length.
                        ~models.Q(kind="RETURN_SERVICE")
                        & models.Q(
                            condition_type__isnull=True,
                            comparable_value__isnull=True,
                            comparable_currency__isnull=True,
                        )
                    )
                ),
                name="benefit_rule_comparable_shape_valid",
            ),
            models.CheckConstraint(
                # A unit only means something on the one condition published in two of
                # them. Anywhere else it claims a choice that does not exist -- "35
                # HOURS old" -- and a reader would have to decide which half to believe.
                condition=models.Q(comparable_unit__isnull=True)
                | models.Q(condition_type__isnull=False, condition_type="WORK_EXPERIENCE"),
                name="benefit_rule_comparable_unit_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(comparable_value__isnull=True)
                | models.Q(comparable_value__gte=0),
                name="benefit_rule_comparable_value_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(comparable_currency__isnull=True)
                | models.Q(comparable_currency__in=_CURRENCIES),
                name="benefit_rule_comparable_currency_iso4217",
            ),
            models.CheckConstraint(
                condition=models.Q(scope_type__in=("GLOBAL", "COUNTRY", "CITY", "PROGRAM")),
                name="benefit_rule_scope_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(scope_type__in=("GLOBAL", "COUNTRY", "CITY", "PROGRAM"))
                    | models.Q(
                        scope_type="GLOBAL",
                        country_code__isnull=True,
                        location_key__isnull=True,
                        program__isnull=True,
                    )
                    | models.Q(
                        scope_type="COUNTRY",
                        country_code__isnull=False,
                        location_key__isnull=True,
                        program__isnull=True,
                    )
                    | models.Q(
                        scope_type="CITY",
                        country_code__isnull=True,
                        location_key__isnull=False,
                        program__isnull=True,
                    )
                    | models.Q(
                        scope_type="PROGRAM",
                        country_code__isnull=True,
                        location_key__isnull=True,
                        program__isnull=False,
                    )
                ),
                name="benefit_rule_scope_shape_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(country_code__isnull=True)
                | models.Q(country_code__in=_COUNTRIES),
                name="benefit_rule_country_iso3166_alpha2",
            ),
            models.CheckConstraint(
                condition=models.Q(key="") | models.Q(key__in=_ELIGIBILITY_KEYS),
                name="benefit_rule_key_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(operator="") | models.Q(operator__in=_ELIGIBILITY_OPERATORS),
                name="benefit_rule_operator_valid",
            ),
            models.CheckConstraint(
                # At least one target, not exactly one: `program` already meant "the
                # scope a benefit's rule is narrowed to" (benefit_rule_scope_shape_valid
                # requires it non-null for scope_type=PROGRAM), so a benefit's rule may
                # legitimately carry both. Four shapes, distinguished by which column
                # is null:
                #   benefit set,  program null  -> a funding route's condition.
                #   benefit set,  program set   -> that route's condition, narrowed to
                #                                  one programme (the existing scoped-
                #                                  rule capability -- unchanged).
                #   benefit null, program set   -> the programme's own admission
                #                                  condition (no route to confuse it
                #                                  with, since there is no benefit).
                #   both null                   -> rejected: a condition attached to
                #                                  nothing can never be found or applied.
                condition=~models.Q(benefit__isnull=True, program__isnull=True),
                name="benefit_rule_target_present",
            ),
        ]


class OfficialSource(models.Model):
    class Type(models.TextChoices):
        UNIVERSITY = "UNIVERSITY"
        PROGRAM = "PROGRAM"
        SCHOLARSHIP = "SCHOLARSHIP"
        GOVERNMENT = "GOVERNMENT"
        IMMIGRATION = "IMMIGRATION"
        REGULATOR = "REGULATOR"
        FUNDER = "FUNDER"
        RESEARCH_ORGANIZATION = "RESEARCH_ORGANIZATION"
        MUNICIPAL = "MUNICIPAL"
        STUDENT_SERVICE = "STUDENT_SERVICE"
        OFFICIAL_STATISTICS = "OFFICIAL_STATISTICS"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    canonical_url = models.URLField(max_length=2048, unique=True)
    publisher = models.CharField(max_length=300)
    source_type = models.CharField(max_length=30, choices=Type.choices)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    source_type__in=(
                        "UNIVERSITY",
                        "PROGRAM",
                        "SCHOLARSHIP",
                        "GOVERNMENT",
                        "IMMIGRATION",
                        "REGULATOR",
                        "FUNDER",
                        "RESEARCH_ORGANIZATION",
                        "MUNICIPAL",
                        "STUDENT_SERVICE",
                        "OFFICIAL_STATISTICS",
                    )
                ),
                name="official_source_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(canonical_url__startswith="https://"),
                name="official_source_url_https",
            ),
        ]


class OfficialSourceSnapshot(models.Model):
    class Readability(models.TextChoices):
        """Why the reader could not read this page -- or that it could.

        A reason rather than a boolean because "we could not read it" and
        "it says nothing" are the same silence from the outside, and each
        cause needs a different answer: a shell is the browser tier's to
        render, a not-found page is a catalog fix (the source moved), and
        only OK may be derived from. Members are added when something
        writes them; BLOCKED is not here because nothing does yet.
        """

        OK = "OK"
        #: Too little readable text at too many bytes: a JS shell, a cookie
        #: wall. research.reader's floor.
        SHELL = "SHELL"
        #: The host's own not-found page, served HTTP 200 -- by redirect to a
        #: /404-shaped path, or at the address we asked for with the body the
        #: host gives for any missing path.
        SOFT_404 = "SOFT_404"
        #: A PDF with no text layer (a scan) or one pypdf refused.
        UNPARSEABLE = "UNPARSEABLE"

    class RetrievalStatus(models.TextChoices):
        CURRENT = "CURRENT"
        STALE = "STALE"
        BLOCKED = "BLOCKED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source = models.ForeignKey(OfficialSource, on_delete=models.PROTECT)
    s3_key = models.CharField(max_length=2048)
    s3_version_id = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    #: Digest of the content region only -- page chrome stripped, whitespace
    #: normalised. sha256 above stays the digest of the retrieved bytes, which is
    #: what the evidence chain cites; this one answers the separate question of
    #: whether the page changed. Blank on rows written before it existed.
    content_sha256 = models.CharField(max_length=64, blank=True, default="")
    #: Whether the reader could see this page, and why not when it could not.
    #: Anything but OK means nothing was derived from it and the previous rows
    #: stand. Distinct from "the page states no requirement", which is the
    #: silent failure this field exists to remove. It replaces the `unreadable`
    #: boolean master carried: every writer of that flag meant SHELL, and the
    #: other three causes were invisible.
    readability = models.CharField(
        max_length=20, choices=Readability.choices, default=Readability.OK
    )
    #: When the programme funding reader completed three readings of this
    #: snapshot, including a read that found nothing. Null means never read,
    #: which funding_recall must tell apart from "read, found nothing".
    funding_read_at = models.DateTimeField(null=True, blank=True)
    #: What the funding read of this page version cost: recorded tokens per
    #: model family, priced at list (apps.research.model_cost.CostMeter.as_json).
    #: Null until a read completes, and null on every row read before item 15.
    #: Token counts about a public page: no personal data.
    funding_read_cost = models.JSONField(null=True, blank=True)
    final_url = models.URLField(max_length=2048)
    redirect_chain = models.JSONField(default=list)
    retrieved_at = models.DateTimeField()
    admissions_cycle = models.CharField(max_length=50)
    content_type = models.CharField(max_length=100)
    byte_size = models.PositiveBigIntegerField()
    retrieval_status = models.CharField(
        max_length=20, choices=RetrievalStatus.choices, default=RetrievalStatus.CURRENT
    )
    dom_object_key = models.CharField(max_length=2048, null=True, blank=True)
    screenshot_object_key = models.CharField(max_length=2048, null=True, blank=True)
    render_status = models.CharField(max_length=20, null=True, blank=True)
    discovery_technique = models.CharField(max_length=50, null=True, blank=True)
    #: EGRESS (our client), SCRAPE_DO or FIRECRAWL -- funder spec §4.3. A vendor body is
    #: the vendor's rendering, not origin bytes; the evidence chain says which.
    fetched_via = models.CharField(max_length=20, default="EGRESS")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="replacements"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("source", "sha256"), name="snapshot_source_sha256_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(byte_size__gte=0), name="snapshot_byte_size_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(retrieval_status__in=("CURRENT", "STALE", "BLOCKED", "FAILED")),
                name="snapshot_retrieval_status_valid",
            ),
        ]


class OfficialEvidenceClaim(models.Model):
    class ClaimClass(models.TextChoices):
        IDENTITY = "IDENTITY"
        STRUCTURE = "STRUCTURE"
        ELIGIBILITY = "ELIGIBILITY"
        TUITION = "TUITION"
        FUNDING = "FUNDING"
        DEADLINE = "DEADLINE"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source = models.ForeignKey(OfficialSource, on_delete=models.PROTECT)
    snapshot = models.ForeignKey(
        OfficialSourceSnapshot, null=True, blank=True, on_delete=models.PROTECT
    )
    claim = models.CharField(max_length=4_000)
    evidence_strength = models.CharField(max_length=30, choices=EvidenceStrength.choices)
    visibility = models.CharField(max_length=20, choices=EvidenceVisibility.choices)
    claim_class = models.CharField(max_length=20, choices=ClaimClass.choices, null=True)
    last_checked_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(evidence_strength__in=EvidenceStrength.values),
                name="official_claim_strength_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(visibility__in=EvidenceVisibility.values),
                name="official_claim_visibility_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(evidence_strength=EvidenceStrength.ECOSYSTEM_CLUE)
                | models.Q(visibility=EvidenceVisibility.INTERNAL),
                name="official_claim_clue_internal_only",
            ),
            models.CheckConstraint(
                condition=models.Q(claim_class__isnull=True)
                | models.Q(
                    claim_class__in=(
                        "IDENTITY",
                        "STRUCTURE",
                        "ELIGIBILITY",
                        "TUITION",
                        "FUNDING",
                        "DEADLINE",
                    )
                ),
                name="official_claim_class_valid",
            ),
        ]


class InstitutionEvidenceClaim(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT)
    evidence_claim = models.ForeignKey(OfficialEvidenceClaim, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_institution_evidence_claims"
        constraints = [
            models.UniqueConstraint(
                fields=("institution", "evidence_claim"), name="institution_evidence_pair_uniq"
            )
        ]


class ProgramEvidenceClaim(models.Model):
    program = models.ForeignKey(Program, on_delete=models.PROTECT)
    evidence_claim = models.ForeignKey(OfficialEvidenceClaim, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_program_evidence_claims"
        constraints = [
            models.UniqueConstraint(
                fields=("program", "evidence_claim"), name="program_evidence_pair_uniq"
            )
        ]


class ProgramAwardingInstitution(models.Model):
    program = models.ForeignKey(Program, on_delete=models.PROTECT)
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_program_awarding_institutions"
        constraints = [
            models.UniqueConstraint(
                fields=("program", "institution"),
                name="program_awarding_institution_pair_uniq",
            )
        ]


class FundingOpportunityProgram(models.Model):
    opportunity = models.ForeignKey(FundingOpportunity, on_delete=models.PROTECT)
    program = models.ForeignKey(Program, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_fundingopportunity_programs"
        constraints = [
            models.UniqueConstraint(
                fields=("opportunity", "program"), name="opportunity_program_pair_uniq"
            )
        ]


class FundingOpportunityEvidenceClaim(models.Model):
    opportunity = models.ForeignKey(FundingOpportunity, on_delete=models.PROTECT)
    evidence_claim = models.ForeignKey(OfficialEvidenceClaim, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_fundingopportunity_evidence_claims"
        constraints = [
            models.UniqueConstraint(
                fields=("opportunity", "evidence_claim"), name="opportunity_evidence_pair_uniq"
            )
        ]


class FundingBenefitEvidenceClaim(models.Model):
    benefit = models.ForeignKey(FundingBenefit, on_delete=models.PROTECT)
    evidence_claim = models.ForeignKey(OfficialEvidenceClaim, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_fundingbenefit_evidence_claims"
        constraints = [
            models.UniqueConstraint(
                fields=("benefit", "evidence_claim"), name="benefit_evidence_pair_uniq"
            )
        ]


class CostComponentEvidenceClaim(models.Model):
    cost_component = models.ForeignKey(CostComponent, on_delete=models.PROTECT)
    evidence_claim = models.ForeignKey(OfficialEvidenceClaim, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_costcomponent_evidence_claims"
        constraints = [
            models.UniqueConstraint(
                fields=("cost_component", "evidence_claim"),
                name="cost_component_evidence_pair_uniq",
            )
        ]


class BenefitRuleEvidenceClaim(models.Model):
    benefit_rule = models.ForeignKey(BenefitRule, on_delete=models.PROTECT)
    evidence_claim = models.ForeignKey(OfficialEvidenceClaim, on_delete=models.PROTECT)

    class Meta:
        db_table = "funding_benefitrule_evidence_claims"
        constraints = [
            models.UniqueConstraint(
                fields=("benefit_rule", "evidence_claim"), name="benefit_rule_evidence_pair_uniq"
            )
        ]


class CycleState(models.TextChoices):
    """`validity.cycle_validity`'s answers (spec 9.1)."""

    OPEN = "OPEN"
    UPCOMING = "UPCOMING"
    CLOSED_FOR_INTAKE = "CLOSED_FOR_INTAKE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"
    UNVERIFIED = "UNVERIFIED"


class LadderStep(models.TextChoices):
    """Which rung of the evidence ladder settled a verification (spec 9.2)."""

    NONE = "", "never run"
    OWN_PAGES = "0", "own pages already read"
    CRAWL = "1", "site crawl on the cycle vocabulary"
    WAYBACK = "1b", "Wayback captures of earlier cycles"
    CADENCE = "1c", "register cadence"
    HOP = "2", "one own-site hop"
    SEARCH = "3", "domain-restricted search"


class FundingCycleVerification(models.Model):
    """Is this award's money there for ONE intake, and on what evidence (spec 9.3).

    The decision is `validity.cycle_validity`, pure; this row is what it was
    fed, what it said, which rung of the evidence ladder settled it, and what
    that cost as the vendors billed it.

    RLS class: SHARED CATALOG. Whether an award's money is there for an intake
    is the same fact for every tenant, so every tenant reads it
    (`shared_catalog_select`) and `runtime_engine` alone writes it
    (`runtime_engine_write`); `runtime_web` holds no table grant at all
    (migration `0053_cycle_verification_rls`). No column references a tenant
    table.

    `evidence` is a list of `cycle_evidence.EvidenceEntry` dicts -- a quote,
    the URL we fetched it from, the digest of those bytes and the dates it
    states. A student is never in it and nothing here may point at one.
    """

    State = CycleState
    Step = LadderStep

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    opportunity = models.ForeignKey(
        FundingOpportunity, on_delete=models.PROTECT, related_name="cycle_verifications"
    )
    intake_start_year = models.PositiveSmallIntegerField()
    state = models.CharField(
        max_length=20, choices=CycleState.choices, default=CycleState.UNVERIFIED
    )
    evidence = models.JSONField(default=list)
    #: Every past cycle the evidence shows: {"intake_year", "open", "deadline",
    #: "url", "captured_at"}. `open` is null when only a deadline was seen --
    #: such a cycle is not a "dated call" (plan decision 3).
    cycles_observed = models.JSONField(default=list)
    #: What was looked at and how it ended: {"step", "url", "outcome", "note"}.
    #: The Wayback lookups here are the "read once, cached for good" of 9.2.
    trail = models.JSONField(default=list)
    projected_open = models.DateField(null=True, blank=True)
    projected_deadline = models.DateField(null=True, blank=True)
    #: 45 days past a projected opening with no call: the projection is
    #: withheld from the evidence and the state degrades (spec 9.3).
    projection_lapsed = models.BooleanField(default=False)
    page_removed = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    ladder_step = models.CharField(
        max_length=2, choices=LadderStep.choices, blank=True, default=""
    )
    #: Recorded, never estimated: Firecrawl and scrape.do credits at plan rate,
    #: model tokens priced by `apps.research.model_cost` at
    #: `MODEL_PRICES_USD_PER_MTOK`, Exa `costDollars`, Brave requests at list.
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    cost_detail = models.JSONField(default=dict)
    #: False when some spend could not be priced (a model missing from
    #: MODEL_PRICES_USD_PER_MTOK, a call whose usage never reached us). The
    #: number is then a floor, and says so.
    cost_complete = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("opportunity", "intake_start_year"), name="cycle_verification_intake_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=CycleState.values),
                name="cycle_verification_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(ladder_step__in=LadderStep.values),
                name="cycle_verification_step_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(intake_start_year__gte=2000, intake_start_year__lte=2100),
                name="cycle_verification_intake_range",
            ),
        ]
        indexes = [models.Index(fields=("next_check_at",), name="cycle_verify_due_idx")]


class ConstraintOverride(TenantScopedModel):
    """A student's recorded decision to proceed against an ADVISORY_HIGH_RISK rule.

    Scoped to (student, programme, rule): an override never travels to another
    programme, even for the same student and the same rule.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    # Program is a shared catalog model, so no composite tenant FK here.
    programme = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="+")
    rule_id = models.CharField(max_length=20)
    decided_by = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    risk_text_shown = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="constraintoverride_tenant_id_uniq"
            ),
            models.UniqueConstraint(
                fields=("tenant", "student", "programme", "rule_id"),
                name="constraintoverride_decision_uniq",
            ),
        ]


class ApplicationPrompt(models.Model):
    """A fact about a programme's application prompt(s) for one cycle.

    Not tenant-scoped, like ``Program`` itself: this is a shared-catalog fact
    about the programme, not student data.
    """

    class Source(models.TextChoices):
        VERIFIED = "VERIFIED"
        EXTRACTED = "EXTRACTED"
        INFERRED = "INFERRED"
        UNRESOLVED = "UNRESOLVED"

    class FunderKind(models.TextChoices):
        GOVERNMENT_SCHOLARSHIP = "GOVERNMENT_SCHOLARSHIP"
        UNIVERSITY_ADMISSION = "UNIVERSITY_ADMISSION"
        UNIVERSITY_SCHOLARSHIP = "UNIVERSITY_SCHOLARSHIP"
        CONSORTIUM = "CONSORTIUM"
        DEVELOPMENT_FOUNDATION = "DEVELOPMENT_FOUNDATION"
        IMMIGRATION_AUTHORITY = "IMMIGRATION_AUTHORITY"
        RESEARCH_SUPERVISOR = "RESEARCH_SUPERVISOR"

    class Structure(models.TextChoices):
        SHORT_ANSWER_SET = "SHORT_ANSWER_SET"
        CONTINUOUS_LETTER = "CONTINUOUS_LETTER"
        TWO_STATEMENTS = "TWO_STATEMENTS"
        PRESCRIBED_RESEARCH_FORM = "PRESCRIBED_RESEARCH_FORM"
        CONSORTIUM_SPECIFIC = "CONSORTIUM_SPECIFIC"
        VIDEO = "VIDEO"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    programme = models.ForeignKey(
        Program, on_delete=models.PROTECT, related_name="application_prompts"
    )
    cycle = models.CharField(max_length=20)
    source_url = models.URLField(max_length=2048, blank=True)
    confidence = models.FloatField()
    verified_for_cycle = models.CharField(max_length=20, null=True, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices)
    funder_kind = models.CharField(max_length=30, choices=FunderKind.choices)
    structure = models.CharField(max_length=30, choices=Structure.choices)
    archetypes = ArrayField(models.CharField(max_length=30), default=list)
    questions = models.JSONField(default=list, blank=True)
    programme_evidence = models.JSONField(default=dict, blank=True)
    document_language = models.CharField(max_length=10)
    immigration = models.BooleanField(default=False)
    paired_with = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    header_block_required = models.BooleanField(default=False)
    # The shape the programme's own page states for the applicant's letter
    # (spec 2026-09-19, §1). Every column is nullable or has an "unstated"
    # default: a value here is a page rule, and its sentence is in
    # letter_shape_sources; a field absent from that dict is a default the
    # engine chose, never something the page said.
    letter_document_required = models.CharField(max_length=12, default="UNSTATED")
    letter_min_words = models.PositiveIntegerField(null=True, blank=True)
    letter_max_words = models.PositiveIntegerField(null=True, blank=True)
    letter_max_chars = models.PositiveIntegerField(null=True, blank=True)
    letter_max_pages = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    #: A character floor, always measured WITHOUT spaces: the stricter reading
    #: whatever the page's own convention, so a letter clearing it clears the
    #: page's (addendum 2026-09-26 §6.2 -- Kassel rejects a letter under 2,800).
    letter_min_chars = models.PositiveIntegerField(null=True, blank=True)
    letter_form = models.CharField(max_length=13, default="ESSAY")
    letter_signed_declaration = models.BooleanField(default=False)
    letter_naming = models.CharField(max_length=9, default="UNSTATED")
    letter_font_family = models.CharField(max_length=60, blank=True, default="")
    letter_font_min_pt = models.PositiveSmallIntegerField(null=True, blank=True)
    letter_line_spacing = models.DecimalField(
        max_digits=2, decimal_places=1, null=True, blank=True
    )
    letter_margins_cm = models.DecimalField(
        max_digits=3, decimal_places=1, null=True, blank=True
    )
    letter_file_bundle = models.CharField(max_length=14, default="SEPARATE")
    letter_handwritten = models.BooleanField(default=False)
    letter_shape_sources = models.JSONField(default=dict, blank=True)
    #: §3b path 2 and path 3: requirements no column can type. Kept as the
    #: page's own sentences with their URL, never a paraphrase.
    letter_written_requirements = models.JSONField(default=list, blank=True)
    letter_student_actions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Meta's class body has no access to ApplicationPrompt's local namespace (Python
        # nested-class scoping), so the nested TextChoices below can't be named directly here
        # -- matching how Program.Meta handles its own nested TextChoices with literal tuples.
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    source__in=("VERIFIED", "EXTRACTED", "INFERRED", "UNRESOLVED")
                ),
                name="applicationprompt_source_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    funder_kind__in=(
                        "GOVERNMENT_SCHOLARSHIP",
                        "UNIVERSITY_ADMISSION",
                        "UNIVERSITY_SCHOLARSHIP",
                        "CONSORTIUM",
                        "DEVELOPMENT_FOUNDATION",
                        "IMMIGRATION_AUTHORITY",
                        "RESEARCH_SUPERVISOR",
                    )
                ),
                name="applicationprompt_funder_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    structure__in=(
                        "SHORT_ANSWER_SET",
                        "CONTINUOUS_LETTER",
                        "TWO_STATEMENTS",
                        "PRESCRIBED_RESEARCH_FORM",
                        "CONSORTIUM_SPECIFIC",
                        "VIDEO",
                    )
                ),
                name="applicationprompt_structure_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0, confidence__lte=1),
                name="applicationprompt_confidence_range",
            ),
        ]
