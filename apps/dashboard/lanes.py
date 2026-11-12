"""One lane per programme (lanes spec §5). Pure: groups the cards board_for built.

A separate award card joins the lane of the one programme it is linked to. An
award linked to several programmes gets its own lane, named for the award, and
each of those programmes' lanes says "Also funded by your <award> application".
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from apps.documents.templatetags.cv_countries import country_name
from apps.portals.award_links import AwardLine

from .dates import CLOSED

if TYPE_CHECKING:
    from .board import Card, Column

_FAR = datetime.max.replace(tzinfo=UTC)
_FINISHED = frozenset({"REJECTED", "WITHDRAWN"})


@dataclass(frozen=True)
class Lane:
    key: UUID
    title: str
    status: str
    columns: tuple[tuple[Column, tuple[Card, ...]], ...]
    also_funded: tuple[str, ...] = ()
    programmes: tuple[str, ...] = ()
    done_line: str = ""
    page_url: str = ""
    award_lines: tuple[AwardLine, ...] = ()

    @property
    def cards(self) -> tuple[Card, ...]:
        return tuple(card for _column, cards in self.columns for card in cards)

    @property
    def lead(self) -> Card:
        return next(card for card in self.cards if card.application_id == self.key)


def _title(card: Card) -> str:
    if card.is_award or not card.institution:
        return card.title
    where = f" ({country_name(card.country)})" if card.country else ""
    return f"{card.institution} — {card.title}{where}"


def _status(card: Card) -> str:
    from .board import Column

    if card.closed:
        return CLOSED
    if card.outcome_line:
        return card.outcome_line
    return {
        Column.TO_START: "Not started",
        Column.IN_PROGRESS: "In progress",
        Column.SUBMITTED: "Applied — waiting for a decision",
        Column.CONFIRMED: "Applied — the portal confirmed it, waiting for a decision",
        Column.DECISION: "Decision available",
    }[card.column]


def lanes_for(
    cards: Sequence[Card],
    links: Iterable[tuple[UUID, UUID]],
    *,
    page_url: Callable[[UUID], str],
) -> tuple[tuple[Lane, ...], tuple[Lane, ...]]:
    """(open lanes, done lanes). `links` are (award card, programme card) pairs."""
    from .board import Column

    by_id = {card.application_id: card for card in cards}
    programmes_of: dict[UUID, list[UUID]] = {}
    for award_id, programme_id in links:
        if award_id in by_id and programme_id in by_id:
            programmes_of.setdefault(award_id, []).append(programme_id)
    shared = {
        a for a, ps in programmes_of.items()
        if len(ps) > 1 and by_id[a].outcome not in _FINISHED
    }
    members: dict[UUID, list[Card]] = {}
    for card in cards:
        linked = programmes_of.get(card.application_id, [])
        key = linked[0] if card.is_award and len(linked) == 1 else card.application_id
        members.setdefault(key, []).append(card)

    lanes = []
    for key, lane_cards in members.items():
        lead = by_id[key]
        lanes.append(Lane(
            key=key,
            title=_title(lead),
            status=_status(lead),
            columns=tuple(
                (column, tuple(sorted(
                    (c for c in lane_cards if c.column is column),
                    key=lambda c: (c.deadline or _FAR, c.created_at),
                )))
                for column in Column
            ),
            also_funded=tuple(
                f"Also funded by your {by_id[a].title} application"
                for a in sorted(shared, key=lambda a: by_id[a].title)
                if key in programmes_of[a]
            ),
            programmes=(
                tuple(by_id[p].title for p in programmes_of[key]) if key in shared else ()
            ),
            done_line=(
                " · ".join(c.outcome_line for c in lane_cards if c.outcome_line)
                if lead.outcome in _FINISHED else ""
            ),
            page_url=page_url(key),
        ))
    lanes.sort(key=lambda lane: (
        lane.lead.closed,
        min((c.deadline for c in lane.cards if c.deadline), default=_FAR),
        lane.lead.created_at,
    ))
    return (
        tuple(lane for lane in lanes if not lane.done_line),
        tuple(lane for lane in lanes if lane.done_line),
    )
