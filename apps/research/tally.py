"""The sweep's cumulative tallies -- what decides which engine, angle and
language keep running (spec 6.7).

Cumulative across runs and cycles, never per run (spec 15: the repo has seen
+-2/16 between identical runs). Keyed by the host's CLASSIFIED family, read
live, never the pass that found it: Brave leads Exa on industrial sponsorship
(70% vs 50%) while Exa leads on foundations, and a tally keyed per pass or per
corridor averages that away. Reported, never asserted by a test on real data.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db.models import Count

from .funding_reader import FAMILY_BY_HOLDER
from .models import Organisation, SweepAngle, SweepDiscovery, SweepQuery

_UNCLASSIFIED = "UNCLASSIFIED"
_NOT_A_FUNDER = "NOT_A_FUNDER"


def _bucket(org: Organisation) -> str:
    if org.classified_at is None:
        return _UNCLASSIFIED
    if org.funds_students is not True or org.kind == "UNSTATED":
        return _NOT_A_FUNDER
    return FAMILY_BY_HOLDER.get(org.kind, _NOT_A_FUNDER)


def found_by(*, country_code: str | None = None) -> dict[tuple[str, str], int]:
    """(classified family, provider) -> novel hosts that provider returned in
    the pass that found them -- every provider, not only the first asker.

    Reads every `returned_by` entry on every discovery, including one
    appended in a LATER batch than the host's first discovery -- this
    answers "which engine can reach which hosts", not "is this engine still
    finding new ones". That second question is the harness's decay credit
    (`harness.run_pass`), which is scoped to the batch a host was first
    found in on purpose: a re-return is not new to that pass.
    """
    rows = SweepDiscovery.objects.select_related("organisation")
    if country_code:
        rows = rows.filter(run__country_code=country_code)
    counts: Counter[tuple[str, str]] = Counter()
    for discovery in rows:
        for provider in discovery.returned_by:
            counts[(_bucket(discovery.organisation), provider)] += 1
    return dict(counts)


def angle_yield(
    country_code: str, family: str, home_language: str = ""
) -> dict[UUID, tuple[int, int]]:
    """angle id -> (asks, verified first-discoveries of this family).

    Two queries total, not one per angle: asks come from a single grouped
    count, and verified counts from one select_related pass over discoveries
    (the family bucket is Python logic, not something the DB can group on).
    """
    angles = list(SweepAngle.objects.filter(
        country_code=country_code, family=family, home_language=home_language
    ))
    ids = [angle.pk for angle in angles]
    asks = {
        row["angle_id"]: row["n"]
        for row in SweepQuery.objects.filter(angle_id__in=ids)
        .values("angle_id")
        .annotate(n=Count("id"))
    }
    verified: Counter[UUID] = Counter()
    discoveries = SweepDiscovery.objects.filter(query__angle_id__in=ids).select_related(
        "organisation", "query"
    )
    for discovery in discoveries:
        if _bucket(discovery.organisation) == family:
            verified[discovery.query.angle_id] += 1
    return {angle.pk: (asks.get(angle.pk, 0), verified.get(angle.pk, 0)) for angle in angles}


def language_yield(
    country_code: str, family: str, home_language: str = ""
) -> dict[str, tuple[int, int]]:
    """language -> (asks, verified first-discoveries) -- decision 38's
    per-language yield, which decides which languages keep running."""
    by_id = {
        angle.pk: angle.language
        for angle in SweepAngle.objects.filter(
            country_code=country_code, family=family, home_language=home_language
        )
    }
    totals: dict[str, tuple[int, int]] = {}
    for angle_id, (asks, verified) in angle_yield(country_code, family, home_language).items():
        language = by_id[angle_id]
        prior = totals.get(language, (0, 0))
        totals[language] = (prior[0] + asks, prior[1] + verified)
    return totals


def retire_dead_angles(
    country_code: str, family: str, *, now: datetime, home_language: str = ""
) -> int:
    """Retire every live angle asked at least SWEEP_DEAD_AFTER_USES times that
    never first-found a verified host of its family. A language whose every
    angle is retired has stopped running -- which is how the per-language
    yield drops a language, without a second rule."""
    threshold = settings.SWEEP_DEAD_AFTER_USES
    retired = 0
    for angle_id, (asks, verified) in angle_yield(country_code, family, home_language).items():
        if asks < threshold or verified:
            continue
        updated = SweepAngle.objects.filter(pk=angle_id, retired_at__isnull=True).update(
            retired_at=now,
            retired_reason=f"{asks} asks, 0 verified first-discoveries of {family}",
        )
        retired += updated
    return retired
