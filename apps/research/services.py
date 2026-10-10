import logging
from datetime import timedelta
from decimal import Decimal
from functools import partial
from itertools import batched
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.accounts.models import StudentProfileVersion
from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.fx import RateTable
from apps.funding.models import (
    EvidenceClaim,
    FundingOpportunity,
    PackCandidate,
    PackVersion,
    Program,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.pack import PackedApplication, PackedAward
from apps.funding.services import auto_publish_pack

from .coverage import pack_coverage, refresh_cell_coverage
from .models import ConsultantResearchTask, DomainLease
from .provenance import provenance_of_award, provenance_of_program
from .queue import enqueue_research
from .schemas import ResearchMessage
from .spine import SpineResult, build_student_pack
from .tap_seams import bound_pass_states, bound_rungs

logger = logging.getLogger(__name__)

#: Bodies per check_provenance message. Sized by time, not by SQS's 256 KB body
#: limit: the worker runs the whole message inline, and ResearchQueue's
#: VisibilityTimeout is 900 s (infra/template.yaml). A body's worst case is ~21
#: vendor fetches plus RDAP, Jev and possibly a register load, so 15 bodies must
#: finish well inside 900 s -- or the message is redelivered, run twice
#: concurrently, and after maxReceiveCount 3 dead-lettered despite succeeding.
_CHECK_BATCH = 15


class DomainBusy(RuntimeError):
    pass


class ResearchContextMismatch(RuntimeError):
    pass


@transaction.atomic
def acquire_domain_lease(domain: str, *, interval: timedelta) -> DomainLease:
    now = timezone.now()
    lease, created = DomainLease.objects.select_for_update().get_or_create(
        domain=domain, defaults={"available_at": now + interval}
    )
    if not created:
        if lease.available_at > now:
            raise DomainBusy(domain)
        lease.available_at = now + interval
        lease.save(update_fields=["available_at"])
    return lease


def record_blocked_source(url: str, reason: str) -> ConsultantResearchTask:
    """Queue a URL for the current TENANT's consultants, and say why it is queued NOW.

    This is the tenant queue: every caller is in this module, inside one
    student's run (a condition to check, a low-confidence candidate, an empty
    pool, a catalogue row with no origin). Questions about the SHARED catalogue
    -- a host the fetch ladder cannot open, a disputed award, an organisation's
    site or kind -- are not one agency's work and do not come here: they go to
    the platform's resolution queue, `apps/research/resolution/` (plan
    2026-09-25; `pipeline.py` stopped calling this for blocked sources then).

    `defaults=` is only consulted on CREATE, so the row kept the FIRST reason
    forever: a task could still read "timeout" months after the host began
    answering 403, and the diagnostics then said the opposite of the truth. The
    row carries the latest reason.

    Deduped by URL, because `research_task_open_url_uniq` is (tenant, url)-unique
    while OPEN and two failures of one source are one piece of work. A caller that
    needs two rows to stay two rows gives them two URLs -- dedupe is not the same
    question as identity, and every per-row caller below folds its row's id into
    the URL.
    """
    task, created = ConsultantResearchTask.objects.get_or_create(
        url=url,
        state=ConsultantResearchTask.State.OPEN,
        defaults={"reason": reason},
    )
    if not created and task.reason != reason:
        task.reason = reason
        task.save(update_fields=["reason"])
    return task


def _is_publishable_confidence(evidence_confidence: str) -> bool:
    """P1-6's hard gate at the point a candidate would enter a pack's pool.

    A LOW-confidence candidate is excluded here rather than blocking the whole
    pack — there is no counselor left to unblock it (phased requirements.md
    §2.1, P1-6).
    """
    return evidence_confidence != "LOW"


def _profile_for(run: RecommendationRun) -> StudentProfileSnapshot | None:
    """The run's full profile, or None when it only has the short form.

    A `MinimalProfile` (`schema_version` 0) carries a field, an intake and a
    budget. The gates decide on nationality, academic history and language
    evidence, and widening one into a full snapshot would mean inventing exactly
    the facts the engine is about to reason from — so None, and the spine
    publishes a pack that says which consultation is missing.
    """
    version = StudentProfileVersion.objects.filter(id=run.profile_version_id).first()
    if version is None or version.schema_version != 3:
        return None
    try:
        return StudentProfileSnapshot.model_validate(version.snapshot)
    except ValidationError:
        return None


@transaction.atomic
def handle_research_message(
    message: ResearchMessage, *, rates: RateTable | None = None
) -> PackVersion:
    """One student's run, from the catalogue to a published pack.

    Replaced the fixture path on 2026-09-23. It used to fetch
    `https://official.example.test/program.json`, validate it into an
    `OfficialFixture` and hard-code `eligible=True`; the evaluator, `build_pack`
    and the reader's catalogue were all reachable from tests only.

    `rates` is injected and **has no production source yet**:
    `funding.rate_sources.parse_ecb_daily` and `parse_cbar_daily` exist with no
    caller in `apps/`. Passing None is therefore what a deployed worker does
    today, and the spine publishes an empty pack saying so rather than
    comparing currencies with a table somebody made up.
    """
    try:
        run = RecommendationRun.objects.select_for_update().get(id=message.run_id)
    except RecommendationRun.DoesNotExist as error:
        raise ResearchContextMismatch("run does not belong to message tenant") from error
    existing = PackVersion.objects.filter(run=run).first()
    if existing:
        return existing

    profile = _profile_for(run)
    result = build_student_pack(profile, rates=rates, today=timezone.now().date())
    return _publish(run, version=1, result=result, profile=profile, rates=rates)


@transaction.atomic
def rebuild_pack(run: RecommendationRun, *, rates: RateTable | None = None) -> PackVersion:
    """Build the run's pack again as the next version (spec 10.5 step 3: each
    newly served award bumps the pack version). The only path to version 2+
    from the catalogue; `handle_research_message` stays idempotent on v1.

    A rebuild that packs nothing while the run already has a published pack
    writes NO version: `funding.services.current_pack` shows the highest
    version of a PUBLISHED run, so an empty v+1 would replace the student's
    pack with nothing -- the silently short pack P1-7 forbids. The reason is
    recorded for a person instead, and the published pack stands.
    """
    run = RecommendationRun.objects.select_for_update().get(id=run.id)
    current = PackVersion.objects.filter(run=run).order_by("-version").first()
    profile = _profile_for(run)
    result = build_student_pack(profile, rates=rates, today=timezone.now().date())
    nothing = not (result.pack.fee_free or result.pack.paid or result.pack.awards)
    if current is not None and nothing and run.state == RecommendationRun.State.PUBLISHED:
        record_blocked_source(
            f"https://review.invalid/empty-rebuild/{run.id}",
            (result.pack.empty_reason or "a rebuild packed nothing")[:200],
        )
        return current
    version = current.version + 1 if current is not None else 1
    return _publish(run, version=version, result=result, profile=profile, rates=rates)


def _program_copy(program: Program, application: PackedApplication) -> dict[str, object]:
    """What the board and the pack show about a programme, copied so the web
    tier renders it without the catalogue (catalog-read-split)."""
    institution = program.institution
    return {
        "institution_id": program.institution_id,
        "institution_name": institution.name if institution is not None else "",
        "country_code": program.country_code,
        "degree_level": program.degree_level,
        "application_fee": application.application_fee,
        "application_fee_currency": application.application_fee_currency,
    }


def _award_copy(award: FundingOpportunity, packed: PackedAward) -> dict[str, object]:
    """An award's heading and the programmes it can pay for (dashboard spec §5)."""
    program_ids = list(award.programs.values_list("id", flat=True))
    if award.program_id is not None and award.program_id not in program_ids:
        program_ids.append(award.program_id)
    card = packed.card
    return {
        "institution_id": award.institution_id,
        # HOLDER scope has no country of its own; the holder's is a proxy (owner sign-off pending).
        "country_code": award.country_code
        or (
            award.organisation.country_code
            if award.scope_type == "HOLDER" and award.organisation is not None
            else ""
        )
        or "",
        "funds_program_ids": program_ids,
        "funding_card": {
            "holder": packed.holder_name,
            "deadline": packed.deadline.isoformat() if packed.deadline else "",
            "scope": award.scope_type,
            "route": card.route if card is not None else award.route,
            "tuition": card.tuition if card is not None else "",
            "living": card.living if card is not None else "",
            "amounts": [line.amount_text for line in card.amounts] if card is not None else [],
            "unconfirmed": list(packed.unconfirmed),
            # No catalogue column says which degree levels an award covers yet;
            # grouping.funds() checks the level only when both sides carry one.
            "degree_levels": [],
            # How long the award pays for, as the page states it (lanes spec §9.5);
            # the per-year money line reads it. None/"" when the page is silent.
            "duration_months": award.duration_months,
            "duration_text": award.duration_text,
        },
    }


def _publish(
    run: RecommendationRun,
    *,
    version: int,
    result: SpineResult,
    profile: StudentProfileSnapshot | None,
    rates: RateTable | None,
) -> PackVersion:
    """Write one pack version from a spine result, its coverage, and publish it.

    Coverage is computed for EVERY pack, an empty one included, in the worker
    with the bound real seams, and copied onto `PackVersion.coverage` so the
    web tier renders it without reading the catalogue. The tenant's
    CellCoverage is then rebuilt; it counts published packs only, so an empty
    pack (the run goes DRAFT_READY, nothing is published) leaves it unchanged
    as far as this student goes.
    """
    pack = PackVersion.objects.create(run=run, version=version)
    packed_any = False
    packed_awards: list[FundingOpportunity] = []
    for application in (*result.pack.fee_free, *result.pack.paid):
        program = result.programs.get(application.program_id)
        if program is None:
            continue
        origin = result.origins.get(application.program_id)
        if origin is None:
            # No origin means no provenance, and a candidate shown under
            # "Official source" with a URL nobody can follow is worse than one
            # the student never sees. Recorded, never silent.
            record_blocked_source(
                f"https://review.invalid/no-origin/{run.id}/program/{program.id}",
                f"{program.name[:120]} has no official source to cite",
            )
            continue
        # The tenant copy the web tier renders from; it never reads the catalogue.
        body_id, code = provenance_of_program(program)
        candidate = RecommendationCandidate.objects.create(
            run=run,
            evidence=_evidence_for(origin, f"Catalogue entry for {program.name}"),
            program=program,
            program_name=program.name,
            # A real figure from the evaluator, not a placeholder zero:
            # `funding_gap_is_placeholder` exists for a student-NAMED programme
            # that nothing has costed, and a catalogue row the evaluator ran
            # affordability over is not that case.
            funding_gap=application.gap,
            currency=application.gap_currency,
            eligible=True,
            provenance_reason_code=code,
            provenance_body_id=body_id,
            **_program_copy(program, application),
        )
        if _is_publishable_confidence(candidate.evidence_confidence):
            PackCandidate.objects.create(pack_version=pack, candidate=candidate)
            packed_any = True
        else:
            record_blocked_source(
                f"https://review.invalid/low-confidence/{run.id}/{candidate.id}",
                f"{program.name[:120]}: low-confidence evidence",
            )

    for award_application in result.pack.awards:
        award = result.awards.get(award_application.award_id)
        if award is None:
            continue
        origin = result.origins.get(award_application.award_id)
        if origin is None:
            record_blocked_source(
                f"https://review.invalid/no-origin/{run.id}/award/{award.id}",
                f"{award.name[:120]} has no official source to cite",
            )
            continue
        body_id, code = provenance_of_award(award)
        candidate = RecommendationCandidate.objects.create(
            run=run,
            evidence=_evidence_for(
                origin, f"{award.holder_name or award.name} publishes {award.name}"
            ),
            opportunity=award,
            program_name=award.name,
            # An award REDUCES a gap; it does not have one of its own, and
            # counting money not yet won against a programme's cost is the
            # thing the owner decision of 2026-09-19 rules out. Zero, flagged
            # as a placeholder, so no total treats it as a researched figure.
            funding_gap=Decimal("0"),
            currency="EUR",
            funding_gap_is_placeholder=True,
            eligible=True,
            provenance_reason_code=code,
            provenance_body_id=body_id,
            **_award_copy(award, award_application),
        )
        if _is_publishable_confidence(candidate.evidence_confidence):
            PackCandidate.objects.create(pack_version=pack, candidate=candidate)
            packed_any = True
            packed_awards.append(award)
        else:
            record_blocked_source(
                f"https://review.invalid/low-confidence/{run.id}/{candidate.id}",
                f"{award.name[:120]}: low-confidence evidence",
            )

    # Work for a human, never a hold on the student's pack: publication is
    # deliberately un-gated by counsellor review (phased requirements §38).
    # These tasks are TENANT-SCOPED -- a question about one student's own
    # eligibility belongs to that student's agency. Catalog questions are the
    # platform's alone (spec §11) and are not created here.
    for subject in result.review:
        record_blocked_source(
            f"https://review.invalid/candidate/{run.id}/{subject}",
            "a published condition needs a human decision",
        )
    # `degraded` is a list of sentences, not of rows, so the index is the only
    # identifier available -- and it is enough, because the URL is already
    # scoped to one run.
    for index, note in enumerate(result.degraded):
        record_blocked_source(
            f"https://review.invalid/degraded/{run.id}/{index}",
            f"catalogue row skipped: {note}"[:200],
        )

    if result.pending_bodies or run.pending_bodies:
        # The pack says so, and the sweep re-runs this student when one of
        # these resolves RECOGNISED (spec §7.1): nothing re-issues a pack in place.
        # Replaced, not appended: on a rebuild_pack the latest build's list is
        # the true one, and a stale entry would re-run the student for nothing.
        RecommendationRun.objects.filter(id=run.id).update(
            pending_bodies=list(result.pending_bodies)
        )
    if result.pending_bodies:
        # Checked by the worker after this transaction commits, never inside
        # it: a register load is minutes of HTTP (spec §7.1, ruling I4).
        transaction.on_commit(
            partial(_queue_checks, run.tenant_id, run.id, result.pending_bodies)
        )
    pack.coverage = pack_coverage(
        profile, packed_awards, rungs=bound_rungs(), passes=bound_pass_states()
    )
    pack.save(update_fields=["coverage"])

    if packed_any:
        auto_publish_pack(pack)
    else:
        # An empty pack is still published-as-empty via the run's state, and the
        # reason travels with it: P1-7, never a silently short pack.
        run.state = RecommendationRun.State.DRAFT_READY
        run.save(update_fields=["state"])
        if result.pack.empty_reason:
            record_blocked_source(
                f"https://review.invalid/empty-pool/{run.id}",
                result.pack.empty_reason[:200],
            )
    refresh_cell_coverage(run.tenant_id, rates=rates)
    return pack


def _queue_checks(tenant_id: UUID, run_id: UUID, body_ids: tuple[UUID, ...]) -> None:
    """Ask the worker to check a pack's pending bodies now. A queue outage is
    logged and costs only time: the daily provenance recheck finds the same
    bodies, and the pack already says they are being checked."""
    try:
        for chunk in batched(body_ids, _CHECK_BATCH):
            enqueue_research(
                ResearchMessage(
                    kind="check_provenance", tenant_id=tenant_id, run_id=run_id, body_ids=chunk
                ),
                queue_url=settings.RESEARCH_QUEUE_URL,
            )
    except Exception:  # noqa: BLE001 - the daily recheck covers it; the pack stands
        logger.exception("provenance checks not queued for run %s", run_id)


def _evidence_for(origin_url: str, claim: str) -> EvidenceClaim:
    """`origin_url` is an address the catalogue verified, passed in by the
    caller. This function used to build one by prefixing whatever it was given
    with "https://", which turned a canonical_key into
    "https://program:<uuid>" -- a string the UI captions as "program" and the
    report prints in full, beside the words "Official source"."""
    return EvidenceClaim.objects.create(
        source_url=origin_url[:2048], claim=claim, last_checked_at=timezone.now()
    )
