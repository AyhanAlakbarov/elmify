from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


def select_best_entries[T](
    entries: Sequence[T], *, limit: int, key: Callable[[T], Any] = lambda _entry: 0
) -> tuple[T, ...]:
    """The ``limit`` highest-ranked entries, ties keeping their input order.

    ``sorted`` is stable, so ranking by ``key`` alone already preserves input
    order among equals -- which is what "the most important N" has to mean when
    nothing distinguishes two entries.
    """
    ranked = sorted(entries, key=key, reverse=True)
    return tuple(ranked[:limit])
