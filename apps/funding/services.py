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
        .order_by("-created_at")
        .first()
    )
    if latest_run is None:
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
        ).select_related("candidate")
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
    exclude_candidate_id: UUID | None = None,
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
    if exclude_candidate_id is not None:
        excluded.add(exclude_candidate_id)
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
    _copy_pool(current, new_version, exclude_candidate_id=candidate_id)
    RecommendationCandidate.objects.filter(id=candidate_id).update(
        state=RecommendationCandidate.State.REJECTED
    )
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
    StudentDecision.objects.create(
        candidate_id=candidate.id, actor=actor, decision=StudentDecision.Decision.REJECTED
    )
    AuditEvent.objects.create(actor=actor, event="candidate.rejected", object_id=candidate.id)


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
    new_version = PackVersion.objects.create(run=current.run, version=current.version + 1)
    _copy_pool(current, new_version, exclude_candidate_id=candidate_id)
    PackCandidate.objects.create(pack_version=new_version, candidate=replacement)
    RecommendationCandidate.objects.filter(id=candidate_id).update(
        state=RecommendationCandidate.State.REJECTED
    )
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
    evidence = EvidenceClaim.objects.create(
        source_url=f"https://research.pending.internal/named-program/{uuid4()}",
        claim=f"Pending official verification for {program_name}",
        last_checked_at=timezone.now(),
    )
    candidate = RecommendationCandidate.objects.create(
        run=pack.run,
        evidence=evidence,
        program_name=program_name,
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
    RecommendationCandidate.objects.filter(id=candidate.id).update(
        state=RecommendationCandidate.State.VISIBLE, eligible=eligible,
        # The verified URL is new, so any earlier code is for another site.
        provenance_reason_code="", provenance_body_id=None,
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
