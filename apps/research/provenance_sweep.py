"""Verdict changes reach published packs; resolved checks re-run students.

Institution provenance gate spec §7.1 and §7.3. It loops tenants explicitly and
enters BOTH filters for each -- `tenant_scope` for Django's manager and
`set_local_tenant` (via `tenant_transaction`) for Postgres RLS, the shape
`execute_due_erasures` uses: with either missing, the sweep is legal SQL that
finds nothing and exits 0. There was no withdrawn-award handler to reuse
(pool.py says the unserve sweep "is still owed"); this is it, for provenance.

It reads the verdict catalogue, so it runs in the worker (`runtime_engine`),
never on the web tier. It never checks a body itself: a check is minutes of
HTTP and must not sit inside a tenant transaction (spec §7.1), so it only
queues `check_provenance` / `check_named_program` messages, after the tenant's
transactions have closed.

What it does, per student, on the student's CURRENT pack only (the latest
PUBLISHED run's latest version -- `current_pack`; a superseded run's versions
are never shown, so never revised):

- refreshes the tenant copy (`provenance_reason_code`, `provenance_body_id`) of
  every VISIBLE candidate of that run, pack member or not -- a named candidate
  whose domain turned BLOCKED must carry that code, or `replace_candidate`
  would still place it. Verdicts join on DOMAIN: a programme's
  `evidence_domain`, an award's `holder_domain`, a named programme's verified
  URL's registrable domain;
- in the pack, `-> BLOCKED` is removed; while the gate is enforced so is any
  UNCONFIRMED code other than a transient one (waiting, lookup_failed), at once
  (verified-catalog spec §0.10); a `RECOGNISED -> UNCONFIRMED` on a transient
  code is kept, each with a change note; a kept candidate (catalogue or counsellor-added)
  still UNCONFIRMED two cycles after its note is removed with one -- only
  while the gate is enforced, since the pool re-admits UNCONFIRMED otherwise.
  Verified-catalog spec §0.18: an unconfirmed body never reaches a student,
  whoever placed it;
- a pack its removals leave empty re-runs the student, since no student
  command can act on an empty pack;
- re-queues a named candidate whose check never ran (no verdict on its domain
  and no code, or a waiting one), and the bodies no check has reached yet.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import batched
from uuid import UUID

from django.conf import settings
from django.db.models import Q

from apps.funding.models import (
    AuditEvent,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.services import _copy_pool, auto_publish_pack, current_pack
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency, Membership

from .dispatch import dispatch_recommendation_run
from .models import ProvenanceVerdict
from .provenance import (
    BLOCKED_REASONS,
    RECOGNISED_REASONS,
    WAITING_REASONS,
    Reason,
    Verdict,
    provenance_of_award,
    provenance_of_named,
    provenance_of_program,
    verdict_of,
)
from .provenance_job import bodies_in_play
from .queue import enqueue_research
from .schemas import ResearchMessage
from .services import _CHECK_BATCH

logger = logging.getLogger(__name__)


@dataclass
class SweepReport:
    revised: int = 0
    removed: int = 0
    kept: int = 0
    reruns: int = 0
    cleared: int = 0
    #: check_named_program messages queued.
    named: int = 0
    #: Bodies queued for check_provenance.
    checks: int = 0
    errors: int = 0


def _enqueue(message: ResearchMessage) -> None:
    enqueue_research(message, queue_url=settings.RESEARCH_QUEUE_URL)


def sweep(
    *,
    now: datetime,
    dispatch: Callable[..., bool] = dispatch_recommendation_run,
    enqueue: Callable[[ResearchMessage], None] = _enqueue,
) -> SweepReport:
    report = SweepReport()
    cycle = timedelta(days=settings.PROVENANCE_CYCLE_DAYS)
    # Agency carries no RLS policy, so the runtime role lists it unscoped.
    for tenant_id in list(Agency.objects.values_list("id", flat=True)):
        checks: dict[UUID, set[UUID]] = defaultdict(set)
        named: list[ResearchMessage] = []
        reruns: list[UUID] = []
        # One scope per tenant: tenant_scope refuses to switch tenants.
        with tenant_scope(tenant_id):
            try:
                students, pending_runs = _listing(tenant_id)
            except Exception:  # noqa: BLE001 - one tenant never stops the sweep; logged
                logger.exception("provenance sweep could not list tenant %s", tenant_id)
                report.errors += 1
                continue
            # One transaction per student and per run: one bad row never
            # rolls back, or stalls, every other student of the tenant.
            for student in students:
                try:
                    with tenant_transaction(tenant_id):
                        outcome = _sweep_student(student, now=now, cycle=cycle)
                except Exception:  # noqa: BLE001 - one student never stops the sweep; logged
                    logger.exception("provenance sweep failed for student %s", student.id)
                    report.errors += 1
                    continue
                if outcome.revised:
                    report.revised += 1
                report.removed += outcome.removed
                report.kept += outcome.kept
                named.extend(outcome.named)
                if outcome.rerun is not None:
                    reruns.append(outcome.rerun)
                if outcome.run_id is not None and outcome.unchecked:
                    checks[outcome.run_id] |= outcome.unchecked
            for run_id in pending_runs:
                try:
                    with tenant_transaction(tenant_id):
                        resolved = _resolve_pending(run_id)
                except Exception:  # noqa: BLE001 - one run never stops the sweep; logged
                    logger.exception("provenance sweep failed for run %s", run_id)
                    report.errors += 1
                    continue
                report.cleared += resolved.cleared
                if resolved.rerun is not None:
                    reruns.append(resolved.rerun)
                if resolved.unchecked:
                    checks[run_id] |= resolved.unchecked
        # Outside every tenant transaction: a dispatch opens its own, and a
        # queued check runs in the worker on its own (spec §7.1).
        for run_id in reruns:
            report.reruns += bool(dispatch(tenant_id=tenant_id, run_id=run_id))
        messages = [
            *named,
            *(
                ResearchMessage(
                    kind="check_provenance", tenant_id=tenant_id, run_id=run_id,
                    body_ids=tuple(sorted(chunk)),
                )
                for run_id, body_ids in checks.items()
                for chunk in batched(sorted(body_ids), _CHECK_BATCH)
            ),
        ]
        for message in messages:
            try:
                enqueue(message)
            except Exception:  # noqa: BLE001 - the next sweep re-queues the same work
                logger.exception("provenance sweep could not queue %s", message.kind)
                report.errors += 1
                continue
            if message.kind == "check_named_program":
                report.named += 1
            else:
                report.checks += len(message.body_ids)
    return report


def _listing(tenant_id: UUID) -> tuple[list[Membership], list[UUID]]:
    """The tenant's students with a published pack, and its runs holding
    pending bodies."""
    with tenant_transaction(tenant_id):
        students = list(
            Membership.objects.filter(
                id__in=RecommendationRun.objects.filter(
                    state=RecommendationRun.State.PUBLISHED
                ).values("profile_version__student_id")
            )
        )
        pending_runs = list(
            RecommendationRun.objects.exclude(pending_bodies=[]).values_list("id", flat=True)
        )
    return students, pending_runs


@dataclass
class _StudentOutcome:
    run_id: UUID | None = None
    #: A fresh run, created when the sweep emptied the pack.
    rerun: UUID | None = None
    revised: bool = False
    removed: int = 0
    kept: int = 0
    named: tuple[ResearchMessage, ...] = ()
    unchecked: frozenset[UUID] = frozenset()


def _fresh(candidate: RecommendationCandidate) -> tuple[UUID | None, str] | None:
    """The candidate's tenant copy as the verdicts stand now; None for a named
    candidate whose domain no check has reached."""
    if candidate.program is not None:
        return provenance_of_program(candidate.program)
    if candidate.opportunity is not None:
        return provenance_of_award(candidate.opportunity)
    return provenance_of_named(candidate.evidence.source_url)


def _action(
    old: str,
    new: str,
    *,
    kept_at: datetime | None,
    now: datetime,
    cycle: timedelta,
) -> str | None:
    if new in BLOCKED_REASONS:
        return "removed"
    if verdict_of(new) != Verdict.UNCONFIRMED:
        return None
    # Verified-catalog spec §0.10: nothing unverified reaches a student in any
    # form. Only a transient code (waiting, or a failed lookup) earns the grace
    # below; any other UNCONFIRMED code is a finding, removed on first sight.
    if (
        settings.PROVENANCE_GATE_ENFORCED
        and new not in WAITING_REASONS
        and new != Reason.LOOKUP_FAILED
    ):
        return "removed"
    if old in RECOGNISED_REASONS:
        # Kept: an evidence gap is not proof of fraud, and removing a
        # programme a student may be applying to is the costlier mistake.
        return "kept"
    # While the gate is off the pool re-admits UNCONFIRMED, so the next run
    # would put back what a timeout took out.
    if not settings.PROVENANCE_GATE_ENFORCED:
        return None
    # Every member, whoever placed it (verified-catalog spec §0.18); the two
    # cycles after the "kept" note absorb a transient lookup failure only.
    if kept_at is not None and kept_at <= now - 2 * cycle:
        return "removed"
    return None


def _kept_at(run_id: UUID) -> dict[str, datetime]:
    """candidate id -> when its latest "kept" note was written, over every
    version of the run: a student's reject writes a version with no notes."""
    latest: dict[str, datetime] = {}
    for notes in PackVersion.objects.filter(run_id=run_id).values_list("change_notes", flat=True):
        for note in notes:
            if note.get("action") == "kept" and note.get("candidate_id"):
                at = datetime.fromisoformat(note["at"])
                latest[note["candidate_id"]] = max(at, latest.get(note["candidate_id"], at))
    return latest


def _sweep_student(student: Membership, *, now: datetime, cycle: timedelta) -> _StudentOutcome:
    pack = current_pack(student)
    if pack is None:
        return _StudentOutcome()
    # The lock serialises against a student's reject/replace on the same
    # version; one that committed first leaves this version stale, and the
    # next sweep revises the newer one.
    pack = PackVersion.objects.select_for_update().get(id=pack.id)
    if PackVersion.objects.filter(run_id=pack.run_id, version__gt=pack.version).exists():
        return _StudentOutcome()
    members = set(
        PackCandidate.objects.filter(pack_version=pack).values_list("candidate_id", flat=True)
    )
    candidates = (
        RecommendationCandidate.objects.filter(run_id=pack.run_id)
        .filter(Q(state=RecommendationCandidate.State.VISIBLE) | Q(id__in=members))
        .select_related("program", "opportunity", "evidence")
        .order_by("program_name", "id")
    )
    kept_at = _kept_at(pack.run_id)
    notes: list[dict[str, str]] = []
    removed: list[UUID] = []
    named: list[ResearchMessage] = []
    unchecked: set[UUID] = set()
    for candidate in candidates:
        old = candidate.provenance_reason_code
        fresh = _fresh(candidate)
        if fresh is None:
            # Named, and no verdict on its domain: the check never ran, or
            # its enqueue failed (resolve_named_program only logs that).
            if not old or old in WAITING_REASONS:
                named.append(
                    ResearchMessage(
                        kind="check_named_program", tenant_id=student.tenant_id,
                        run_id=candidate.run_id, candidate_id=candidate.id,
                    )
                )
            continue
        body, code = fresh
        if (body, code) != (candidate.provenance_body_id, old):
            RecommendationCandidate.objects.filter(id=candidate.id).update(
                provenance_reason_code=code, provenance_body_id=body
            )
        if code == Reason.NOT_EVALUATED and body is not None:
            # No verdict row yet for a catalogue row's domain.
            unchecked.add(body)
        if candidate.id not in members:
            continue
        action = _action(
            old, code, kept_at=kept_at.get(str(candidate.id)), now=now, cycle=cycle
        )
        if action is None:
            continue
        notes.append(
            {
                "candidate_id": str(candidate.id),
                "candidate_name": candidate.program_name,
                "reason_code": code,
                "action": action,
                "at": now.isoformat(),
            }
        )
        if action == "removed":
            removed.append(candidate.id)
    outcome = _StudentOutcome(
        run_id=pack.run_id, named=tuple(named), unchecked=frozenset(unchecked)
    )
    if not notes:
        return outcome
    new_version = PackVersion.objects.create(
        run=pack.run, version=pack.version + 1, change_notes=notes
    )
    _copy_pool(pack, new_version, exclude_candidate_ids=removed)
    if removed:
        RecommendationCandidate.objects.filter(id__in=removed).update(
            state=RecommendationCandidate.State.REJECTED
        )
        for candidate_id in removed:
            AuditEvent.objects.create(
                actor=None, event="candidate.withdrawn", object_id=candidate_id
            )
    auto_publish_pack(new_version)
    if not PackCandidate.objects.filter(pack_version=new_version).exists():
        # Nothing left to reject or replace: only a fresh run gets the student
        # a pack again. It records its own pending bodies, so the old run's
        # would only re-run the same student a second time.
        outcome.rerun = RecommendationRun.objects.create(
            profile_version_id=pack.run.profile_version_id
        ).id
        RecommendationRun.objects.filter(id=pack.run_id).update(pending_bodies=[])
    outcome.revised = True
    outcome.removed = len(removed)
    outcome.kept = len(notes) - len(removed)
    return outcome


@dataclass
class _PendingOutcome:
    cleared: int = 0
    rerun: UUID | None = None
    unchecked: frozenset[UUID] = frozenset()


def _body_states(body_ids: Iterable[UUID]) -> dict[UUID, str]:
    """Per pending body, over its domains in play: "unchecked" when one has no
    verdict row, "waiting" when one's is a WAITING reason, else "recognised"
    when one is RECOGNISED, else "settled". A body with no domain in play --
    REJECTED, or gone -- is settled: no check will ever come for it."""
    ids = list(body_ids)
    domains: dict[UUID, set[str]] = defaultdict(set)
    for body, domain in bodies_in_play().filter(organisation_id__in=ids).values_list(
        "organisation_id", "registrable_domain"
    ):
        domains[body].add(domain)
    codes = dict(
        ProvenanceVerdict.objects.filter(
            domain__in={d for group in domains.values() for d in group}
        ).values_list("domain", "reason_code")
    )
    states: dict[UUID, str] = {}
    for body in ids:
        found = [codes.get(domain) for domain in domains[body]]
        if any(code is None for code in found):
            states[body] = "unchecked"
        elif any(code in WAITING_REASONS for code in found):
            states[body] = "waiting"
        elif any(code in RECOGNISED_REASONS for code in found):
            states[body] = "recognised"
        else:
            states[body] = "settled"
    return states


def _resolve_pending(run_id: UUID) -> _PendingOutcome:
    run = (
        RecommendationRun.objects.select_for_update()
        .select_related("profile_version")
        .get(id=run_id)
    )
    if not run.pending_bodies:
        return _PendingOutcome()
    if RecommendationRun.objects.filter(
        profile_version__student_id=run.profile_version.student_id,
        created_at__gt=run.created_at,
        state=RecommendationRun.State.PUBLISHED,
    ).exists():
        # A newer run built its own pack and recorded its own pending bodies:
        # re-running this one would put a stale profile's pack in front of
        # the student. One that never published built nothing, so it does not
        # count -- clearing here would strand the re-run.
        RecommendationRun.objects.filter(id=run.id).update(pending_bodies=[])
        return _PendingOutcome(cleared=len(run.pending_bodies))
    states = _body_states(run.pending_bodies)
    resolved = [body for body in run.pending_bodies if states[body] in ("recognised", "settled")]
    unchecked = frozenset(body for body in run.pending_bodies if states[body] == "unchecked")
    if not resolved:
        return _PendingOutcome(unchecked=unchecked)
    rerun = None
    # ponytail: a body counts RECOGNISED if ANY of its in-play domains is, so a
    # body whose recognised domain was not the one left out re-runs the student
    # once for nothing; storing the pending domains instead of body ids is the
    # upgrade if that extra run ever costs.
    if any(states[body] == "recognised" for body in resolved):
        # A fresh run evaluates afresh and records its own pending bodies; the
        # copy step can only drop a candidate (spec §7.1).
        rerun = RecommendationRun.objects.create(profile_version_id=run.profile_version_id).id
        remaining: list[UUID] = []
        unchecked = frozenset()
    else:
        remaining = [body for body in run.pending_bodies if body not in resolved]
    RecommendationRun.objects.filter(id=run.id).update(pending_bodies=remaining)
    return _PendingOutcome(cleared=len(run.pending_bodies) - len(remaining), rerun=rerun,
                           unchecked=unchecked)
