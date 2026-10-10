"""Read-time ordering (spec 11). No priority is ever stored in a row.

Sorted from the item's own columns and nothing else. The console runs as
`runtime_web`, which holds no grant on any catalogue table (funding/0049), so
the two subject facts the sort needs -- `registered` and `country_code` -- are
stamped on the item by the writer at filing (writers.subject_facts, engine
role) instead of being looked up here (brief D3). A catalogue read added to
this module is a `permission denied` in production; the zero-query test in
test_operator.py is what says so first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from apps.research.models import ResolutionItem

#: Task 13 supplies the real one, once the owner decides it may exist. None
#: means "not computed", and the console prints exactly that -- never a 0
#: nobody measured.
PackCounter = Callable[[ResolutionItem], int | None]


def no_pack_count(_item: ResolutionItem) -> int | None:
    return None


@dataclass(frozen=True)
class QueueRow:
    item: ResolutionItem
    packs: int | None
    registered: bool
    country_code: str


def rows(items: Iterable[ResolutionItem], *, pack_count: PackCounter) -> list[QueueRow]:
    out = [
        QueueRow(
            item=item,
            packs=pack_count(item),
            registered=item.registered,
            country_code=item.country_code,
        )
        for item in items
    ]
    # Spec 11: most live packs blocked first, whichever tenants'; then
    # registered hosts; then candidates; oldest first within a tier.
    out.sort(key=lambda r: (-(r.packs or 0), not r.registered, r.item.created_at))
    return out


#: `known` counts the organisations the catalogue holds in a country. Only the
#: engine can answer it (the catalogue is not granted to `runtime_web`), so the
#: console passes none and says so, never 0 (brief D3).
KnownCounter = Callable[[str], int]

_WAITING = (
    ResolutionItem.State.OPEN, ResolutionItem.State.PARKED, ResolutionItem.State.DECIDED,
)


def corridor_share(
    items: Iterable[ResolutionItem] | None = None, *, known: KnownCounter | None = None
) -> dict[str, tuple[int, int | None]]:
    """`{country_code: (items_waiting, organisations_known)}` -- spec 11's
    "under one host in ten per corridor reaching a person".

    The numerator is the queue alone: every live item (OPEN, PARKED, DECIDED)
    by its writer-stamped `country_code`, "" for unknown. The denominator is
    `known(country)`, or None when the caller cannot read the catalogue.
    """
    if items is None:
        items = ResolutionItem.objects.filter(state__in=_WAITING).only("country_code")
    waiting: dict[str, int] = {}
    for item in items:
        waiting[item.country_code] = waiting.get(item.country_code, 0) + 1
    return {
        country: (count, known(country) if known is not None else None)
        for country, count in sorted(waiting.items())
    }


def corridor_lines(share: dict[str, tuple[int, int | None]]) -> list[str]:
    """One line per country. A snapshot of what is waiting now, not a rate:
    the queue deletes answered rows, so "share that ever reached a person"
    needs a history nobody keeps yet (plan Task 12)."""
    lines = []
    for country, (waiting, known) in share.items():
        label = country or "??"
        if known is None:
            lines.append(
                f"{label}: {waiting:,} waiting / known: not computed on the web tier"
                " (snapshot, not a rate)"
            )
        else:
            percent = f"{waiting / known:.1%}" if known else "n/a"
            lines.append(
                f"{label}: {waiting:,} waiting / {known:,} known ({percent})"
                " (snapshot, not a rate)"
            )
    return lines
