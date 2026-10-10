"""The numbers at the top of the student's home page.

Pure arithmetic over what the page already holds -- the board (`board_for`),
the needs list (`items_for`) and the student's current pack -- so it adds no
business rule and reads no catalogue table: the pack rows are the tenant-side
copies the worker wrote (CLAUDE.md, "the catalogue boundary is a GRANT").
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.funding.models import PackCandidate
from apps.funding.services import current_pack, pool_funding_gap_totals
from apps.tenancy.models import Membership

from .board import Board, Card, Column

#: How many upcoming deadlines the home page lists.
DEADLINES_SHOWN = 5
#: A deadline this close is shown as urgent.
SOON_DAYS = 7


@dataclass(frozen=True)
class Overview:
    applications: int
    active: int
    decided: int
    column_counts: tuple[tuple[Column, int], ...]
    documents_done: int
    documents_total: int
    answers_done: int
    answers_total: int
    needs: int
    pack_programmes: int
    pack_published: bool
    funding_gap: tuple[tuple[str, Decimal], ...]
    deadlines: tuple[Card, ...]

    @property
    def documents_percent(self) -> int:
        return _percent(self.documents_done, self.documents_total)

    @property
    def answers_percent(self) -> int:
        return _percent(self.answers_done, self.answers_total)

    @property
    def next_deadline(self) -> Card | None:
        return self.deadlines[0] if self.deadlines else None

    @property
    def soon_days(self) -> int:
        return SOON_DAYS


def _percent(done: int, total: int) -> int:
    return round(100 * done / total) if total else 0


def build_overview(student: Membership, board: Board, needs: list) -> Overview:
    cards = board.cards
    upcoming = sorted(
        (c for c in cards if c.deadline_local is not None and (c.days_left or 0) >= 0 and not c.outcome),
        key=lambda c: c.deadline_local,
    )
    pack = current_pack(student)
    pack_programmes = 0
    gap: dict[str, Decimal] = {}
    if pack is not None:
        pack_programmes = PackCandidate.objects.filter(pack_version=pack).count()
        gap = dict(pool_funding_gap_totals(pack))
    decided = sum(1 for c in cards if c.column is Column.DECISION)
    return Overview(
        applications=len(cards),
        active=len(cards) - decided,
        decided=decided,
        column_counts=tuple((column, len(column_cards)) for column, column_cards in board.columns),
        documents_done=sum(c.documents[0] for c in cards),
        documents_total=sum(c.documents[1] for c in cards),
        answers_done=sum(c.answers[0] for c in cards),
        answers_total=sum(c.answers[1] for c in cards),
        needs=len(needs),
        pack_programmes=pack_programmes,
        pack_published=bool(pack is not None and pack.published_at),
        funding_gap=tuple(sorted(gap.items())),
        deadlines=tuple(upcoming[:DEADLINES_SHOWN]),
    )
