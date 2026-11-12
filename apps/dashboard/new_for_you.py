"""New for you (lanes spec §7.7, §7.9): pool items the budget now has room for.

Computed on every view from the current pack's run, never stored. Only the
student sees it; the counsellor board never renders it. Adding is always one
click and never automatic. An item that doesn't fit goes through the same
over-budget confirmation page as every other Add (owner 2026-10-14).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.funding.fx import BANK_MARGIN, RateTable
from apps.funding.grouping import funds
from apps.funding.models import PackCandidate, RecommendationCandidate
from apps.funding.services import current_pack
from apps.portals.award_links import _deadline_passed
from apps.portals.models import Application
from apps.tenancy.models import Membership

from .board import Board
from .dates import final_passed
from .money import approx, in_home, over_budget
from .pack import applied_candidate_ids
from .routes import action_url

logger = logging.getLogger(__name__)

Kind = Literal["FITS", "STRETCH", "OVER", "UNLOCKED"]


def _is_score_unlocked(candidate: RecommendationCandidate) -> bool:
    return bool((candidate.calibration_features or {}).get("score_unlocked"))


def _is_score_offer(candidate: RecommendationCandidate) -> bool:
    features = candidate.calibration_features or {}
    return bool(features.get("score_unlocked") or features.get("score_boosted"))


def _is_pack_score_offer(candidate: RecommendationCandidate) -> bool:
    """Whether a PackCandidate member should be surfaced in 'New for you' rather
    than treated as an already-settled v1 pack member (`taken`).

    Newly `score_unlocked` candidates (added in v2+) always surface.
    `score_boosted` candidates that arealready in `PackCandidate` only surface
    when they are awards or fee-free; a paid v1 pack member stays in `taken` and
    keeps its fee in `reserved` so its fee is not double-spent."""
    if _is_score_unlocked(candidate):
        return True
    if not (candidate.calibration_features or {}).get("score_boosted"):
        return False
    return candidate.opportunity_id is not None or (candidate.application_fee or 0) == 0


def _parse_iso_date(raw: object) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        logger.warning("new_for_you._parse_iso_date invalid ISO date %r: %s", raw[:10], exc)
        return None


def _programme_deadline_passed(candidate: RecommendationCandidate, *, today: date) -> bool:
    features = candidate.calibration_features or {}
    for key in ("application_deadline", "scholarship_decision_deadline"):
        parsed = _parse_iso_date(features.get(key))
        if parsed is not None and parsed < today:
            return True
    return False


def _award_is_viable_for_offer(
    award: RecommendationCandidate,
    *,
    apps_by_opp_id: dict[UUID, Application],
    apps_by_cand_id: dict[UUID, Application],
    today: date,
    now: datetime,
) -> bool:
    if (
        award.state != RecommendationCandidate.State.VISIBLE
        or award.eligibility_status == RecommendationCandidate.EligibilityStatus.NOT_ELIGIBLE
    ):
        return False
    app = apps_by_cand_id.get(award.id) or (
        apps_by_opp_id.get(award.opportunity_id) if award.opportunity_id is not None else None
    )
    if app is not None and app.outcome in (
        Application.Outcome.REJECTED,
        Application.Outcome.WITHDRAWN,
    ):
        return False
    fcard = award.funding_card or {}
    is_external_sep = (
        fcard.get("scope") in ("HOLDER", "COUNTRY", "GLOBAL")
        and fcard.get("route") == "STUDENT_APPLIES_SEPARATELY"
    )
    is_submitted_or_won = app is not None and (
        app.state in (Application.State.SUBMITTED, Application.State.CONFIRMED)
        or app.outcome
        in (Application.Outcome.ADMITTED, Application.Outcome.ADMITTED_CONDITIONAL)
    )
    if is_external_sep and is_submitted_or_won:
        return True
    if _deadline_passed(award, today=today):
        return False
    return not (app is not None and final_passed(app, now))


@dataclass(frozen=True)
class Offer:
    candidate_id: UUID
    title: str
    fee_text: str
    kind: Kind
    #: How much more the plan would need, margin included: "48 AZN". "" for FITS.
    over_by: str
    #: Always the student's Add; one that doesn't fit renders the confirmation page.
    add_url: str
    score_note: str = ""

    @property
    def text(self) -> str:
        if self.kind == "UNLOCKED":
            note = self.score_note or "unlocked by your updated scores"
            return f"{self.title} — {note}"
        suffix = f" ({self.score_note})" if self.score_note else ""
        if self.kind == "FITS":
            return f"{self.title} — fee {self.fee_text}, fits your plan{suffix}"
        if self.kind == "STRETCH":
            return (
                f"Worth stretching for: {self.title} — fee {self.fee_text}, "
                f"{self.over_by} over your plan (within the extra you allowed){suffix}"
            )
        return f"{self.title} — fee {self.fee_text}. Over your plan by {self.over_by}{suffix}"


def _exceptional(candidate: RecommendationCandidate, last_paid: int | None) -> bool:
    """§7.7 reasons 1 and 2: fully funded, or ranked above the plan's last paid item."""
    if _is_score_offer(candidate):
        return True
    if candidate.funding_gap == 0 and not candidate.funding_gap_is_placeholder:
        return True
    return last_paid is not None and candidate.rank is not None and candidate.rank < last_paid


def _reserved_fee_total(
    members: Sequence[RecommendationCandidate],
    *,
    applied: set[UUID],
    carded: set[UUID],
    table: RateTable | None,
    home: str,
) -> Decimal:
    reserved = Decimal("0")
    for c in members:
        if (
            c.opportunity_id is None
            and (c.application_fee or 0) > 0
            and c.id not in applied
            and c.program_id not in carded
            and not _is_score_unlocked(c)
        ):
            assert c.application_fee is not None
            amount = in_home(c.application_fee, c.application_fee_currency, table, home)
            if amount is not None:
                reserved += amount * BANK_MARGIN
    return reserved


def _score_offer_award_suffix(
    candidate: RecommendationCandidate,
    *,
    features: dict[str, object],
    pack_awards: Sequence[RecommendationCandidate],
    home_country: str,
    apps_by_opp_id: dict[UUID, Application],
    apps_by_cand_id: dict[UUID, Application],
    today: date,
    now: datetime,
) -> str | None:
    """Return the `(under <awards>)` suffix for a score-offered programme, or None
    when none of its funding awards remain viable."""
    raw_winnable = features.get("winnable_with")
    winnable_names = set(raw_winnable) if isinstance(raw_winnable, list) else set()
    viable_awards = [
        a
        for a in pack_awards
        if (funds(a, candidate, home_country=home_country) or a.program_name in winnable_names)
        and _award_is_viable_for_offer(
            a,
            apps_by_opp_id=apps_by_opp_id,
            apps_by_cand_id=apps_by_cand_id,
            today=today,
            now=now,
        )
    ]
    if not viable_awards:
        return None
    award_labels: list[str] = []
    for a in viable_awards:
        award_app = apps_by_cand_id.get(a.id) or (
            apps_by_opp_id.get(a.opportunity_id) if a.opportunity_id is not None else None
        )
        if award_app is not None and award_app.outcome == Application.Outcome.WAITLISTED:
            award_labels.append(f"{a.program_name} — waitlisted")
        else:
            award_labels.append(a.program_name)
    names = ", ".join(dict.fromkeys(award_labels))
    return f" (under {names})"


def _score_offer_note(
    candidate: RecommendationCandidate,
    *,
    features: dict[str, object],
    award_suffix: str,
) -> str:
    if not features.get("score_boosted"):
        return f"unlocked by your updated scores{award_suffix}"
    pct = (
        candidate.estimated_funded_chance_pct
        if "previous_funded_chance_pct" in features
        and candidate.estimated_funded_chance_pct is not None
        else candidate.estimated_chance_pct
    )
    if pct is not None:
        return f"chance increased to {pct:.0f}% with your updated scores{award_suffix}"
    return f"unlocked by your updated scores{award_suffix}"


def offers_for(
    student: Membership, *, board: Board, table: RateTable | None, home: str
) -> tuple[Offer, ...]:
    budget = board.budget
    pack = current_pack(student)
    if budget is None or pack is None:
        return ()
    profile = StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    home_country = str((profile.snapshot or {}).get("nationality") or "") if profile else ""
    members = [
        member.candidate
        for member in PackCandidate.objects.filter(pack_version=pack).select_related("candidate")
    ]
    # The last paid item the plan holds (§7.7 reason 2): the worst-ranked paid programme.
    last_paid = max(
        (
            c.rank
            for c in members
            if c.opportunity_id is None
            and c.rank is not None
            and (c.application_fee or 0) > 0
            and not _is_score_unlocked(c)
        ),
        default=None,
    )
    applied = applied_candidate_ids(student)
    taken = {c.id for c in members if not _is_pack_score_offer(c)} | applied
    now = timezone.now()
    today = now.date()
    student_apps = list(Application.objects.filter(student=student).select_related("candidate"))
    # §7.9: offered only when the budget gains room, so the pack's own paid
    # picks that are not cards yet keep their fees (with the margin) reserved.
    carded = {
        a.program_id
        for a in student_apps
        if a.program_id is not None
        and (a.candidate is None or a.candidate.opportunity_id is None)
    } | {
        a.candidate.program_id
        for a in student_apps
        if a.candidate is not None and a.candidate.program_id is not None
    }
    carded_opportunities = {
        a.candidate.opportunity_id
        for a in student_apps
        if a.candidate is not None and a.candidate.opportunity_id is not None
    }
    apps_by_cand_id = {a.candidate_id: a for a in student_apps if a.candidate_id is not None}
    apps_by_opp_id = {
        a.candidate.opportunity_id: a
        for a in student_apps
        if a.candidate is not None and a.candidate.opportunity_id is not None
    }
    dead_outcomes = (Application.Outcome.REJECTED, Application.Outcome.WITHDRAWN)
    dead_program_ids = {
        a.candidate.program_id
        if a.candidate is not None and a.candidate.program_id is not None
        else a.program_id
        for a in student_apps
        if a.outcome in dead_outcomes
        or a.funding_outcome in dead_outcomes
        or final_passed(a, now)
    }
    pack_award_by_id: dict[UUID, RecommendationCandidate] = {
        c.id: c for c in members if c.opportunity_id is not None
    }
    for app in student_apps:
        if app.candidate is not None and app.candidate.opportunity_id is not None:
            pack_award_by_id.setdefault(app.candidate.id, app.candidate)
    pack_awards = list(pack_award_by_id.values())
    all_run_programmes = list(
        RecommendationCandidate.objects.filter(run_id=pack.run_id, opportunity_id__isnull=True)
    )
    viable_run_programmes = [
        p
        for p in all_run_programmes
        if p.state == RecommendationCandidate.State.VISIBLE
        and p.eligibility_status == RecommendationCandidate.EligibilityStatus.ELIGIBLE
        and p.program_id not in dead_program_ids
        and not _programme_deadline_passed(p, today=today)
    ]
    reserved = _reserved_fee_total(
        members, applied=applied, carded=carded, table=table, home=home
    )
    room = replace(budget, committed=budget.committed + reserved)
    pool = list(
        RecommendationCandidate.objects.filter(
            run_id=pack.run_id,
            state=RecommendationCandidate.State.VISIBLE,
        )
        .filter(
            Q(opportunity_id__isnull=True, rank__isnull=False, application_fee__isnull=False)
            | Q(calibration_features__has_key="score_unlocked")
            | Q(calibration_features__has_key="score_boosted")
        )
        .exclude(id__in=taken)
        .exclude(program_id__in=carded)
        .exclude(opportunity_id__in=carded_opportunities)
        .order_by("rank", "program_name")
    )
    offers: list[Offer] = []
    for candidate in pool:
        if candidate.eligibility_status != RecommendationCandidate.EligibilityStatus.ELIGIBLE:
            continue
        if candidate.opportunity_id is not None:
            if not _award_is_viable_for_offer(
                candidate,
                apps_by_opp_id=apps_by_opp_id,
                apps_by_cand_id=apps_by_cand_id,
                today=today,
                now=now,
            ):
                continue
            if all_run_programmes and not any(
                funds(candidate, p, home_country=home_country) for p in viable_run_programmes
            ):
                continue
        elif candidate.program_id in dead_program_ids or _programme_deadline_passed(
            candidate, today=today
        ):
            continue

        features = candidate.calibration_features or {}
        over_reason = features.get("over_budget_reason")
        if over_reason == "ELIGIBLE_BELOW_FIT_BAR":
            continue
        score_offer = _is_score_offer(candidate)
        if not score_offer and over_reason in (
            "PACK_DIVERSITY_LIMIT",
            "FEE_NOT_KNOWN_LIMIT",
            "ANCHOR_BUDGET_RESERVED",
        ):
            continue

        award_suffix = ""
        if score_offer and candidate.opportunity_id is None:
            resolved_suffix = _score_offer_award_suffix(
                candidate,
                features=features,
                pack_awards=pack_awards,
                home_country=home_country,
                apps_by_opp_id=apps_by_opp_id,
                apps_by_cand_id=apps_by_cand_id,
                today=today,
                now=now,
            )
            if resolved_suffix is None:
                continue
            award_suffix = resolved_suffix

        note = (
            _score_offer_note(candidate, features=features, award_suffix=award_suffix)
            if score_offer
            else ""
        )
        add_href = action_url(False, "add", student.id, candidate.id)
        if score_offer and (
            candidate.opportunity_id is not None or (candidate.application_fee or 0) == 0
        ):
            offers.append(
                Offer(candidate.id, candidate.program_name, "", "UNLOCKED", "", add_href, note)
            )
            continue
        if candidate.application_fee is None:
            continue
        overrun = over_budget(
            fee=candidate.application_fee,
            currency=candidate.application_fee_currency,
            line=room,
            budget_set=True,
            table=table,
            home=home,
        )
        fee_display = approx(
            candidate.application_fee, candidate.application_fee_currency, table, home
        )
        if overrun is None:
            kind: Kind = "FITS"
        elif overrun.kind in ("STRETCH", "OVER") and _exceptional(candidate, last_paid):
            kind = "STRETCH" if overrun.kind == "STRETCH" else "OVER"
        elif score_offer and overrun.kind in ("NO_RATE", "UNKNOWN", "BUDGET_NO_RATE"):
            offers.append(
                Offer(
                    candidate.id,
                    candidate.program_name,
                    fee_display,
                    "UNLOCKED",
                    "",
                    add_href,
                    score_note=f"{note} — fee {fee_display}",
                )
            )
            continue
        else:
            continue
        offers.append(
            Offer(
                candidate.id,
                candidate.program_name,
                fee_display,
                kind,
                overrun.over if overrun is not None else "",
                add_href,
                score_note=note,
            )
        )
    return tuple(offers)
