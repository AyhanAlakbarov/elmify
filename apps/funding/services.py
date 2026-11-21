import logging
from collections.abc import Collection
from decimal import Decimal
from functools import partial
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.research.models import ConsultantResearchTask
from apps.research.provenance import (
    BLOCKED_REASONS,
    RECOGNISED_REASONS,
    WAITING_REASONS,
    WORDING,
)
from apps.research.queue import enqueue_research
from apps.research.schemas import ResearchMessage
from apps.tenancy.models import Membership

from .models import (
    AuditEvent,
    EvidenceClaim,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
    StudentDecision,
)

logger = logging.getLogger(__name__)


class PublicationBlocked(RuntimeError):
    pass


class PackCommandError(RuntimeError):
    """A student command could not be applied to the current pack."""


class LastInPack(PackCommandError):
    """The candidate is the only item in the pack, so it cannot be removed."""


def current_pack(student: Membership) -> PackVersion | None:
    # Once a run's *initial* pack has been auto-published (run.state becomes
    # PUBLISHED — apps/funding/services.py::auto_publish_pack), later student
    # commands (reject/replace) create newer pack versions that supersede it
    # for display purposes. The run's PUBLISHED state gates visibility, not
    # each version's own published_at, so the student always sees the latest
    # version once the run has published once. ``version`` is only unique
    # *within* a run, so the run must be picked first (most recently created
    # PUBLISHED run) before ranking versions inside it.
    latest_run = (
        RecommendationRun.objects.filter(
            profile_version__student=student,
            state=RecommendationRun.State.PUBLISHED,
        )
        .select_related("profile_version")
        .order_by("-created_at")
        .first()
    )
    if latest_run is None:
        return None
    return (
        PackVersion.objects.filter(run=latest_run)
        .select_related("run__profile_version")
        .order_by("-version")
        .first()
    )


def latest_empty_pack(student: Membership) -> PackVersion | None:
    """The student's newest run's pack when that run packed nothing.

    `current_pack` shows PUBLISHED runs only, and an empty pack leaves its run
    DRAFT_READY, so without this the page told a student with a finished
    profile to finish it. The pack carries why it is empty and its coverage
    line (P1-7: never a silently short pack). A tenant-table read only.
    """
    latest_run = (
        RecommendationRun.objects.filter(profile_version__student=student)
        .order_by("-created_at")
        .first()
    )
    if latest_run is None or latest_run.state != RecommendationRun.State.DRAFT_READY:
        return None
    return PackVersion.objects.filter(run=latest_run).order_by("-version").first()


def pack_awards(student: Membership) -> list[RecommendationCandidate]:
    """The funding awards in the student's current pack (empty with no pack)."""
    pack = current_pack(student)
    if pack is None:
        return []
    return [
        member.candidate
        for member in PackCandidate.objects.filter(
            pack_version=pack, candidate__opportunity_id__isnull=False
        ).select_related("candidate__evidence")
    ]


@transaction.atomic
def auto_publish_pack(pack: PackVersion) -> PackVersion:
    """Publish ``pack`` the moment the pipeline that built it finishes.

    No counselor approval, no ``Approval`` row: the recommendation pack is
    AI-generated and student-controlled from the start (see phased
    requirements.md §2.1). This is the only path that ever sets
    ``published_at``.
    """
    if pack.superseded_at is not None:
        raise PublicationBlocked("pack version has been superseded")
    PackVersion.objects.filter(run_id=pack.run_id, superseded_at__isnull=True).exclude(
        id=pack.id
    ).update(superseded_at=timezone.now())
    pack.published_at = timezone.now()
    pack.save(update_fields=["published_at"])
    RecommendationRun.objects.filter(id=pack.run_id).update(state=RecommendationRun.State.PUBLISHED)
    AuditEvent.objects.create(actor=None, event="pack.published", object_id=pack.id)
    return pack


def _lock_latest(pack: PackVersion) -> PackVersion:
    """Lock ``pack`` and refuse it if a newer version exists: a command racing
    the provenance sweep would otherwise write ``version + 1`` a second time
    and hit the (tenant, run, version) uniqueness constraint."""
    current = PackVersion.objects.select_for_update().get(id=pack.id)
    if PackVersion.objects.filter(run_id=current.run_id, version__gt=current.version).exists():
        raise PackCommandError("the pack changed; reload")
    return current


def _copy_pool(
    source: PackVersion,
    target: PackVersion,
    *,
    exclude_candidate_ids: Collection[UUID] = (),
) -> None:
    """Copy every surviving pool membership from ``source`` onto ``target``.

    New ``PackCandidate`` rows are inserted directly (bypassing the tenant-scoped
    ``save()`` hook) so ``tenant_id`` is copied explicitly from ``source``.
    Several exclusions at once is the provenance sweep's: one verdict pass can
    withdraw several candidates, and a version per candidate would publish
    intermediate packs the student never meant to see.
    """
    excluded = {*exclude_candidate_ids}
    memberships = PackCandidate.objects.filter(pack_version=source)
    if excluded:
        memberships = memberships.exclude(candidate_id__in=excluded)
    PackCandidate.objects.bulk_create(
        [
            PackCandidate(
                tenant_id=source.tenant_id,
                pack_version=target,
                candidate_id=member.candidate_id,
            )
            for member in memberships
        ]
    )
    # The coverage line travels with the pool. A student command runs in the
    # web tier, which may not read the catalogue (catalog-read-split), so it
    # cannot recompute it -- and a new version with no line would drop the
    # "N found in your cells" sentence the moment a student rejects a row.
    # It is a copy of what the worker computed; the next rebuild refreshes it.
    target.coverage = source.coverage
    target.save(update_fields=["coverage"])


def _strip_rejected_award_from_run_programmes(rejected: RecommendationCandidate) -> None:
    if rejected.opportunity_id is None or not rejected.program_name:
        return
    for prog_cand in RecommendationCandidate.objects.filter(
        run_id=rejected.run_id,
        opportunity_id__isnull=True,
        state=RecommendationCandidate.State.VISIBLE,
    ):
        features = dict(prog_cand.calibration_features or {})
        winnable = features.get("winnable_with")
        if not isinstance(winnable, list) or rejected.program_name not in winnable:
            continue
        remaining = [name for name in winnable if name != rejected.program_name]
        features["winnable_with"] = remaining
        update_fields = ["calibration_features"]
        prog_cand.calibration_features = features
        if remaining:
            prog_cand.funding_condition = (
                f"Affordable only if you win {', '.join(remaining)}. "
                "Apply for it before paying this programme's fees."
            )[:500]
            update_fields.append("funding_condition")
        elif prog_cand.funding_condition:
            prog_cand.funding_condition = (
                f"{rejected.program_name} was removed from your pack — "
                "check funding before paying this programme's fees."
            )[:500]
            update_fields.append("funding_condition")
        prog_cand.save(update_fields=update_fields)


@transaction.atomic
def reject_candidate(pack: PackVersion, candidate_id: UUID, actor: Membership) -> PackVersion:
    """Remove ``candidate_id`` from the pool, writing a new immutable pack version.

    The candidate's ``state`` becomes ``REJECTED`` permanently, so it can never be
    re-added to a future pool version (no accidental re-recommendation).
    """
    current = _lock_latest(pack)
    pool = PackCandidate.objects.filter(pack_version=current)
    if not pool.filter(candidate_id=candidate_id).exists():
        raise PackCommandError("candidate is not in the current pack")
    if pool.count() <= 1:
        raise PackCommandError("cannot reject the last remaining candidate in the pack")
    new_version = PackVersion.objects.create(run=current.run, version=current.version + 1)
    _copy_pool(current, new_version, exclude_candidate_ids=(candidate_id,))
    rejected = RecommendationCandidate.objects.filter(id=candidate_id).first()
    RecommendationCandidate.objects.filter(id=candidate_id).update(
        state=RecommendationCandidate.State.REJECTED
    )
    if rejected is not None:
        _strip_rejected_award_from_run_programmes(rejected)
    StudentDecision.objects.create(
        candidate_id=candidate_id, actor=actor, decision=StudentDecision.Decision.REJECTED
    )
    AuditEvent.objects.create(actor=actor, event="candidate.rejected", object_id=candidate_id)
    auto_publish_pack(new_version)
    return new_version


@transaction.atomic
def reject_for_student(
    candidate: RecommendationCandidate, *, student: Membership, actor: Membership
) -> None:
    """Reject ``candidate`` on ``student``'s behalf, recorded under ``actor``.

    In the student's current pack it goes through ``reject_candidate``, so the
    pack never lists a REJECTED candidate: the last item is refused with
    LastInPack, and a pack that changed under us raises PackCommandError for
    the caller to refuse. Outside the pack (the pool) only the state and decision change.
    """
    if candidate.run.profile_version.student_id != student.id:
        raise PackCommandError("candidate does not belong to this student")
    pack = current_pack(student)
    if pack is not None:
        pool = PackCandidate.objects.filter(pack_version=pack)
        if pool.filter(candidate_id=candidate.id).exists():
            if pool.count() <= 1:
                raise LastInPack("cannot remove the last remaining candidate in the pack")
            reject_candidate(pack, candidate.id, actor)
            return
    updated = (
        RecommendationCandidate.objects.filter(id=candidate.id)
        .exclude(state=RecommendationCandidate.State.REJECTED)
        .update(state=RecommendationCandidate.State.REJECTED)
    )
    if not updated:  # a double submit: the other request already wrote the "no"
        return
    _strip_rejected_award_from_run_programmes(candidate)
    StudentDecision.objects.create(
        candidate_id=candidate.id, actor=actor, decision=StudentDecision.Decision.REJECTED
    )
    AuditEvent.objects.create(actor=actor, event="candidate.rejected", object_id=candidate.id)


def clear_overflow_pack_notes(candidate: RecommendationCandidate) -> None:
    """Strip overflow-only pack notes and reasons when a pool item is promoted."""
    rep_features = dict(candidate.calibration_features or {})
    rep_changed = False
    if rep_features.get("over_budget_reason") in (
        "PACK_DIVERSITY_LIMIT",
        "FEE_NOT_KNOWN_LIMIT",
        "ANCHOR_BUDGET_RESERVED",
        "APPLICATION_BUDGET_EXCEEDED",
    ):
        rep_features.pop("over_budget_reason", None)
        rep_changed = True
    rep_notes = rep_features.get("risk_notes")
    if isinstance(rep_notes, list):
        cleaned_notes = [
            str(n)
            for n in rep_notes
            if "kept in Other options" not in str(n)
            and "application budget reserved for a higher-probability" not in str(n)
        ]
        if cleaned_notes != rep_notes:
            rep_features["risk_notes"] = cleaned_notes
            rep_changed = True
    if rep_changed:
        candidate.calibration_features = rep_features
        candidate.save(update_fields=["calibration_features"])


@transaction.atomic
def replace_candidate(
    pack: PackVersion, candidate_id: UUID, replacement_candidate_id: UUID, actor: Membership
) -> PackVersion:
    """Swap ``candidate_id`` out for ``replacement_candidate_id``.

    The replacement must already be a reviewed (``VISIBLE``) candidate belonging to
    the same run and not already in the pool — replacement can only draw from the
    reviewed pool, never from an unreviewed ``CHECKING`` candidate.
    """
    current = _lock_latest(pack)
    if not PackCandidate.objects.filter(pack_version=current, candidate_id=candidate_id).exists():
        raise PackCommandError("candidate is not in the current pack")
    try:
        replacement = RecommendationCandidate.objects.get(
            id=replacement_candidate_id, run_id=current.run_id
        )
    except (RecommendationCandidate.DoesNotExist, ValueError) as error:
        raise PackCommandError("replacement candidate is not part of this run") from error
    if replacement.state != RecommendationCandidate.State.VISIBLE:
        raise PackCommandError("replacement candidate has not been reviewed")
    if not replacement.eligible:
        raise PackCommandError("replacement candidate is no longer eligible")
    # The tenant copy the worker wrote (spec §7.4) -- this web path never reads
    # the catalogue. BLOCKED never enters a pack. While the gate is enforced
    # only RECOGNISED does (verified-catalog §0.18: an unconfirmed body never
    # reaches a student, whoever placed it); a check not yet run waits.
    code = replacement.provenance_reason_code
    if code in BLOCKED_REASONS:
        raise PackCommandError(f"this programme cannot be added: {WORDING[code][0]}")
    if settings.PROVENANCE_GATE_ENFORCED and code not in RECOGNISED_REASONS:
        if not code or code in WAITING_REASONS:
            raise PackCommandError("still being checked; try again shortly")
        raise PackCommandError("its recognition is not confirmed; it cannot be added")
    if PackCandidate.objects.filter(
        pack_version=current, candidate_id=replacement_candidate_id
    ).exists():
        raise PackCommandError("replacement candidate is already in the pack")
    clear_overflow_pack_notes(replacement)
    new_version = PackVersion.objects.create(run=current.run, version=current.version + 1)
    _copy_pool(current, new_version, exclude_candidate_ids=(candidate_id,))
    PackCandidate.objects.create(pack_version=new_version, candidate=replacement)
    replaced = RecommendationCandidate.objects.filter(id=candidate_id).first()
    RecommendationCandidate.objects.filter(id=candidate_id).update(
        state=RecommendationCandidate.State.REJECTED
    )
    if replaced is not None:
        _strip_rejected_award_from_run_programmes(replaced)
    StudentDecision.objects.create(
        candidate_id=candidate_id, actor=actor, decision=StudentDecision.Decision.REPLACED
    )
    AuditEvent.objects.create(actor=actor, event="candidate.replaced", object_id=candidate_id)
    auto_publish_pack(new_version)
    return new_version


@transaction.atomic
def consider_named_program(
    pack: PackVersion, program_name: str, actor: Membership
) -> RecommendationCandidate:
    """Queue a student-named program for research review.

    The resulting candidate starts in ``CHECKING`` state and is not added to any
    pool, so it cannot enter the pack until the queued research task is reviewed
    (see :func:`resolve_named_program`).
    """
    from apps.research.catalog import is_non_masters_program_title

    if is_non_masters_program_title(program_name):
        raise PackCommandError("only Master's degree programmes are supported")
    evidence = EvidenceClaim.objects.create(
        source_url=f"https://research.pending.internal/named-program/{uuid4()}",
        claim=f"Pending official verification for {program_name}",
        last_checked_at=timezone.now(),
    )
    candidate = RecommendationCandidate.objects.create(
        run=pack.run,
        evidence=evidence,
        program_name=program_name,
        degree_level="MASTER",
        funding_gap=Decimal("0.00"),
        currency="USD",
        eligible=False,
        state=RecommendationCandidate.State.CHECKING,
        funding_gap_is_placeholder=True,
    )
    ConsultantResearchTask.objects.get_or_create(
        url=evidence.source_url,
        state=ConsultantResearchTask.State.OPEN,
        defaults={"reason": f"Verify named program request: {program_name}"},
    )
    StudentDecision.objects.create(
        candidate=candidate, actor=actor, decision=StudentDecision.Decision.CONSIDERED
    )
    AuditEvent.objects.create(actor=actor, event="candidate.considered", object_id=candidate.id)
    return candidate


@transaction.atomic
def resolve_named_program(
    candidate: RecommendationCandidate,
    *,
    eligible: bool,
    reason: str,
    source_url: str,
    actor: Membership,
) -> RecommendationCandidate:
    """Close out a queued named-program research task.

    ``source_url`` must be the real official source the counselor verified —
    the candidate's evidence still carries the ``research.pending.internal``
    placeholder minted by :func:`consider_named_program` until this call
    overwrites it, and the placeholder must never be displayed as if it were a
    verified official-source citation.

    The candidate becomes visible with its eligibility result and rationale, but is
    never automatically added to a pool version — a student must still choose it via
    :func:`replace_candidate`.
    """
    if candidate.state != RecommendationCandidate.State.CHECKING:
        raise PackCommandError("candidate is not awaiting review")
    placeholder_url = candidate.evidence.source_url
    estimated_chance_pct: int | None = None
    calibration_features: dict[str, object] = {}
    resolved_country = candidate.country_code or ""
    if eligible:
        from pydantic import ValidationError

        from apps.accounts.models import StudentProfileVersion
        from apps.accounts.schemas import StudentProfileSnapshot
        from apps.funding.pack import risk_tier_for
        from apps.funding.probability import (
            estimate_named_program_chance,
            infer_country_from_url,
        )

        if not resolved_country:
            resolved_country = infer_country_from_url(source_url)
        version = StudentProfileVersion.objects.filter(id=candidate.run.profile_version_id).first()
        profile: StudentProfileSnapshot | None = None
        if version is not None and version.schema_version == 3:
            try:
                profile = StudentProfileSnapshot.model_validate(version.snapshot)
            except ValidationError as exc:
                logger.warning(
                    "resolve_named_program: StudentProfileSnapshot.model_validate failed for "
                    "profile_version %s on candidate %s; degrading to cold-start prior: %s",
                    version.id,
                    candidate.id,
                    exc,
                )
                profile = None
        est = estimate_named_program_chance(
            candidate.program_name,
            resolved_country,
            profile,
            source_url=source_url,
        )
        estimated_chance_pct = est.chance_pct
        calibration_features = dict(est.features)
        tier = risk_tier_for(estimated_chance_pct)
        if tier:
            calibration_features["risk_tier"] = tier
    RecommendationCandidate.objects.filter(id=candidate.id).update(
        state=RecommendationCandidate.State.VISIBLE,
        eligible=eligible,
        country_code=resolved_country,
        estimated_chance_pct=estimated_chance_pct,
        calibration_features=calibration_features,
        # The verified URL is new, so any earlier code is for another site.
        provenance_reason_code="",
        provenance_body_id=None,
    )
    EvidenceClaim.objects.filter(id=candidate.evidence_id).update(
        source_url=source_url, claim=reason, last_checked_at=timezone.now()
    )
    ConsultantResearchTask.objects.filter(
        url=placeholder_url, state=ConsultantResearchTask.State.OPEN
    ).update(state=ConsultantResearchTask.State.CLOSED)
    AuditEvent.objects.create(actor=actor, event="candidate.reviewed", object_id=candidate.id)
    # The worker checks the site the counsellor verified; the web never does.
    transaction.on_commit(
        partial(_queue_named_check, candidate.tenant_id, candidate.run_id, candidate.id)
    )
    candidate.refresh_from_db()
    return candidate


def _queue_named_check(tenant_id: UUID, run_id: UUID, candidate_id: UUID) -> None:
    """A queue outage is logged, never raised: the counsellor's decision is
    already committed, and until a code is written placing the programme is
    refused as "still being checked" (replace_candidate)."""
    try:
        enqueue_research(
            ResearchMessage(
                kind="check_named_program", tenant_id=tenant_id, run_id=run_id,
                candidate_id=candidate_id,
            ),
            queue_url=settings.RESEARCH_QUEUE_URL,
        )
    except Exception:  # noqa: BLE001 - the pack sweep re-queues an unchecked named candidate
        logger.exception("named-programme check not queued for candidate %s", candidate_id)


def pool_funding_gap_totals(pack: PackVersion) -> dict[str, Decimal]:
    """Recalculate the pool's total funding gap, grouped by currency.

    Candidates whose funding gap is still an uncosted placeholder (see
    ``RecommendationCandidate.funding_gap_is_placeholder``) are excluded — a
    fabricated 0.00 must never be added into a total presented as real.
    """
    totals: dict[str, Decimal] = {}
    members = PackCandidate.objects.filter(
        pack_version=pack, candidate__funding_gap_is_placeholder=False
    )
    for member in members.select_related("candidate"):
        totals[member.candidate.currency] = (
            totals.get(member.candidate.currency, Decimal("0")) + member.candidate.funding_gap
        )
    return totals
