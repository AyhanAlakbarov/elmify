"""The funding question set on the card engine, and the single-page read (verified-catalog §5).

`groups` and `years` are the code-owned tables of §5.2.1; `awards` makes a page's lines and groups
them into awards; `questions` is the funding question set; `parse` turns decisions and slice-1
candidates into typed values; `card` assembles the typed, track-shaped card; `entry` reads one
programme page on demand inside 30 s and $0.25; `store` persists a read card into the catalogue.
"""

from .store import is_servable_award, write_card

__all__ = ["is_servable_award", "write_card"]
