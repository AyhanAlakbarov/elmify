"""What item 14 consumes from items 7, 9 and 10 -- as interfaces, bound late.

Each Protocol is the contract. NullSeams is the honest behaviour where nothing
on master can stand behind a seam: no angles, never swept, no reader, no
sweeper -- every one of which ends in a RECORDED outcome (SearchTap.Ending,
AreaSweep.State), never a crash and never a silent success. `bound_*()` is the
single place production binding happens.

Three seams are bound to real rows today (seam_bindings.py):

- `RungSource` -> `ClosedListRungSource`: the closed-list registry (item 7,
  research/0010-0011) IS the ladder, so there is no `REGISTER_RUNGS` table.
- `PassStates` -> `SweepRunPassStates`: the latest finished `SweepRun` of the
  area (item 10, research/0012), its stop reason and its trailing empty batches.
- `AngleSource` -> `ProgrammeAngleSource`: the latest live `ProgrammeAngle`
  templates (RECENCY: this cycle's only), written by `manage.py
  generate_programme_angles`.

One cannot bind on master, and says why in its `bound_*` docstring
(`bound_host_reader`). The sweeper is the next binding
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
    kind: str = "PROGRAMME"


@dataclass(frozen=True)
class TapQueryInputs:
    """The query-word bin, and nothing else: the shape IS the allow-list
    (spec 10.5, D.6) -- a fact with no field here cannot travel.

    Built by `tap_query.inputs_from`. It lives here, with no Django import,
    because `ResearchMessage` carries a follow-up's new part and
    `apps.research.schemas` is imported by scripts that never set Django up.
    """

    field_words: tuple[str, ...]
    interest_words: tuple[str, ...]
    teaching_languages: tuple[str, ...]
    money_words: tuple[str, ...]
    money_first: bool
    intake_year: int
    duration_words: tuple[str, ...]
    research_pathway: bool
    destinations: tuple[str, ...]


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


def bound_angles(*, fallback_on_empty: bool = False) -> AngleSource:
    """The stored programme templates (`ProgrammeAngle`, written by
    `manage.py generate_programme_angles`). A language with none answers ()
    unless `fallback_on_empty=True`."""
    from .seam_bindings import ProgrammeAngleSource

    return ProgrammeAngleSource(fallback_on_empty=fallback_on_empty)


def bound_pass_states() -> PassStates:
    from .seam_bindings import SweepRunPassStates

    return SweepRunPassStates()


def bound_host_reader(*, field: str = "") -> HostReader:
    """`CardHostReader`: reads one new host via `card_funding.entry.read_page`
    and persists its servable awards via `card_funding.store.write_card`."""
    from .seam_bindings import CardHostReader

    return CardHostReader(field=field)


def bound_sweeper() -> CellSweeper:
    """`harness.run_pass`, bounded by the budget the caller passes
    (CELL_SWEEP_BUDGET_USD), mirroring `manage.py sweep_organisations`."""
    from .providers import default_providers
    from .seam_bindings import HarnessSweeper

    return HarnessSweeper(providers=default_providers())


def bound_rungs() -> RungSource:
    from .seam_bindings import ClosedListRungSource

    return ClosedListRungSource()
