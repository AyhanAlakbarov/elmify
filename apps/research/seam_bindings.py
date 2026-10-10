"""The real bindings behind two of tap_seams' Protocols.

Both read SHARED catalogue tables (ClosedList, RegisterEntry, SweepRun and its
rows), so both run in the worker (runtime_engine); the web tier holds no grant
on any of them and never calls these -- the pack's coverage is copied onto
`PackVersion.coverage` at build time for exactly that reason.
"""

from __future__ import annotations

from .funding_reader import FAMILY_BY_HOLDER
from .models import ClosedList, SweepDiscovery, SweepRun
from .tap_seams import PassState, RungRow
from .vgm import register_coverage

#: The rungs a closed list can hold on the ladder. Rung 0 is an enumerator
#: (Wikidata, ROR, EACEA's projects), which routes work and is no rung; rung 4
#: is "no list at all", so a rung-4 row states nothing a missing row does not.
_LADDER_RUNGS = (1, 2, 3)


class ClosedListRungSource:
    """`RungSource` over the closed-list registry: the registry IS the ladder.

    For each `(country, family)` the lowest-rung list holding any holder kind
    of that family wins, ties broken by slug -- the same rule as
    `harness.ladder_rung`. Unlike `ladder_rung`, the family is FAMILY-WIDE
    (FAMILY_BY_HOLDER, not `PASS_SHAPES[family].kinds`): the coverage line
    reports what the ladder knows of an area's bodies, and a bank register is
    part of what is known about foundations even though no open-web pass is
    diffed against it. UNSTATED wins nothing, as in `ladder_rung`: it is filed
    under PRIVATE_FOUNDATION for the reader's sake, not because a list of
    unplaceable bodies enumerates foundations.

    A list with no `RegisterEntry` rows is reported `surveyed=False` -- listed
    but not yet read -- never as "0 of N known", and never raised on as
    `ladder_rung` does: a coverage line must say it, not crash on it.
    """

    def rungs(self, country: str) -> tuple[RungRow, ...]:
        winners: dict[str, ClosedList] = {}
        lists = ClosedList.objects.filter(
            country_code=country, rung__in=_LADDER_RUNGS
        ).order_by("rung", "slug")
        for row in lists:
            for kind in row.holder_kinds:
                if kind == "UNSTATED":
                    continue
                winners.setdefault(FAMILY_BY_HOLDER[kind], row)
        out = []
        for family, row in sorted(winners.items()):
            coverage = register_coverage(row.slug)
            out.append(
                RungRow(
                    country=country,
                    family=family,
                    rung=row.rung,
                    register=row.slug,
                    listed=row.printed_size if row.printed_size is not None else coverage.listed,
                    known=coverage.bodies_known,
                    read=coverage.funds_students,
                    surveyed=coverage.listed > 0,
                )
            )
        return tuple(out)


class SweepRunPassStates:
    """`PassStates` over the sweep harness's own rows (spec 6.7).

    The area's state is its latest FINISHED `SweepRun` by `started_at`: a run
    with `finished_at` NULL did not finish and is an error, never a partial
    result (SweepRun's own docstring). No such run -> `PassState.never()`.
    """

    def state(self, country: str, family: str) -> PassState:
        run = (
            SweepRun.objects.filter(
                country_code=country, family=family, finished_at__isnull=False
            )
            .order_by("-started_at")
            .first()
        )
        if run is None:
            return PassState.never()
        return PassState(
            swept=True,
            past_economic_stop=run.stop_reason == SweepRun.StopReason.ECONOMIC,
            batches_without_new=_trailing_batches_without_new(run),
            stop_reason=run.stop_reason,
        )


def _trailing_batches_without_new(run: SweepRun) -> int:
    """How many of the run's LAST batches found no new verified host.

    Batches are numbered 1..run.batches (harness.run_pass); "verified" is the
    flag the stop rule itself read (`SweepDiscovery.verified_in_pass`), so a
    later reclassification cannot rewrite the curve.
    """
    verified = set(
        SweepDiscovery.objects.filter(run=run, verified_in_pass=True).values_list(
            "query__batch_number", flat=True
        )
    )
    count = 0
    for number in range(run.batches, 0, -1):
        if number in verified:
            break
        count += 1
    return count
