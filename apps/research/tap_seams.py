"""What item 14 consumes from items 7, 9 and 10 -- as interfaces, bound late.

Each Protocol is the contract. NullSeams is the honest behaviour where nothing
on master can stand behind a seam: no angles, never swept, no reader, no
sweeper -- every one of which ends in a RECORDED outcome (SearchTap.Ending,
AreaSweep.State), never a crash and never a silent success. `bound_*()` is the
single place production binding happens.

Two seams are bound to real rows today (seam_bindings.py):

- `RungSource` -> `ClosedListRungSource`: the closed-list registry (item 7,
  research/0010-0011) IS the ladder, so there is no `REGISTER_RUNGS` table.
- `PassStates` -> `SweepRunPassStates`: the latest finished `SweepRun` of the
  area (item 10, research/0012), its stop reason and its trailing empty batches.

Two cannot bind on master, and say why in their `bound_*` docstrings
(`bound_angles`, `bound_host_reader`). The sweeper is the next binding
(`harness.run_pass`, through the `sweep_organisations` command's pieces).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class AngleRow:
    """One stored, versioned, page-voiced programme angle (spec 6.3)."""

    id: str
    language: str
    template: str


@dataclass(frozen=True)
class PassState:
    """How far the sweep of one area `(country, family)` has got.

    `stop_reason` is a `SweepRun.StopReason` value (PLATEAU, ECONOMIC,
    EXHAUSTED, BUDGET, CLASSIFIER_LIMIT) or "" -- never swept, or a pass that
    has not stopped by a rule.
    """

    swept: bool
    past_economic_stop: bool
    batches_without_new: int
    stop_reason: str

    @classmethod
    def never(cls) -> PassState:
        return cls(swept=False, past_economic_stop=False, batches_without_new=0, stop_reason="")


@dataclass(frozen=True)
class RungRow:
    """The register-ladder rung one area reached (spec 6.2).

    `listed` is the list's size (the publisher's printed count when it prints
    one); `known` distinct bodies bound to its entries; `read` those known to
    fund students. `surveyed` is False for a list that is registered but has no
    `RegisterEntry` rows yet: "listed but not yet read", never "0 of N known".
    """

    country: str
    family: str
    rung: int  # 1 purpose register, 2 register, 3 umbrella/hubs; 4 = no row at all
    register: str
    listed: int
    known: int
    read: int
    surveyed: bool = True


@dataclass(frozen=True)
class HostRead:
    cost_usd: Decimal
    awards_served: int
    outcome: str  # the funnel's closed outcome set


@dataclass(frozen=True)
class SweepOutcome:
    provider_calls: int
    cost_usd: Decimal
    new_hosts: int
    #: A SweepRun.StopReason, or why no pass ran.
    stop_reason: str
    #: The SweepRun the pass wrote; None when no run was created.
    run_id: UUID | None = None


class AngleSource(Protocol):
    def programme_angles(self, *, level: str, language: str) -> tuple[AngleRow, ...]: ...
    def recency_angles(self, *, level: str, language: str) -> tuple[AngleRow, ...]: ...


class PassStates(Protocol):
    def state(self, country: str, family: str) -> PassState: ...


class HostReader(Protocol):
    def read(self, domain: str, *, max_usd: Decimal) -> HostRead | None: ...


class CellSweeper(Protocol):
    def run(self, country: str, family: str, *, budget_usd: float) -> SweepOutcome | None: ...


class RungSource(Protocol):
    def rungs(self, country: str) -> tuple[RungRow, ...]: ...


class NullSeams:
    """Every seam, answering "nothing here yet" -- each caller records that."""

    def programme_angles(self, *, level: str, language: str) -> tuple[AngleRow, ...]:
        return ()

    def recency_angles(self, *, level: str, language: str) -> tuple[AngleRow, ...]:
        return ()

    def state(self, country: str, family: str) -> PassState:
        return PassState.never()

    def read(self, domain: str, *, max_usd: Decimal) -> HostRead | None:
        return None

    def run(self, country: str, family: str, *, budget_usd: float) -> SweepOutcome | None:
        return None

    def rungs(self, country: str) -> tuple[RungRow, ...]:
        return ()


def bound_angles() -> AngleSource:
    """NullSeams: master has no PROGRAMME angle rows to slot-fill.

    The only stored angles are `SweepAngle` rows, keyed `(country, family,
    language)`: organisation-side, finished query text with no slots, and
    profile-free by design. No `(field, level, language)` programme angle
    exists anywhere on master, and building a tap query out of a SweepAngle
    would blend a profile-free pass with student words (spec 6.3). So every
    tap ends NO_ANGLES -- recorded, never a crash -- until item 10 stores
    programme angles.
    """
    return NullSeams()


def bound_pass_states() -> PassStates:
    from .seam_bindings import SweepRunPassStates

    return SweepRunPassStates()


def bound_host_reader() -> HostReader:
    """NullSeams: no single-host orchestrator exists on master.

    Stage 2 needs "classify one new host, then read it and serve its awards,
    capped at max_usd". `sitejob.py` holds only the types and the navigator
    brief, and `pipeline.run_discovery` is a whole-run, lead-source-driven
    path, not a per-host call. So stage 2 records the new hosts, reads none,
    and the tap ends STAGE2_UNAVAILABLE until item 9's funnel lands.
    """
    return NullSeams()


def bound_sweeper() -> CellSweeper:
    """NullSeams for now: the next binding is `harness.run_pass`, bounded by
    CELL_SWEEP_BUDGET_USD and mirroring `manage.py sweep_organisations`."""
    return NullSeams()


def bound_rungs() -> RungSource:
    from .seam_bindings import ClosedListRungSource

    return ClosedListRungSource()
