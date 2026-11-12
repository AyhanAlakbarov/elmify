"""Text filters for CV templates."""

from __future__ import annotations

import re

from django import template

register = template.Library()

#: Ends in a single-letter-period run (U.S., e.g., i.e.) or a common
#: abbreviation: the full stop belongs to the word, so it stays.
_KEEP_STOP = re.compile(
    r"(?<![^\W\d_])(?:(?:[^\W\d_]\.){2,}|(?:etc|al|inc|ltd|co|vs|cf|approx|dept|eds?|no)\.)$",
    re.IGNORECASE,
)


@register.filter
def trim_stop(value: object) -> str:
    """Drop ONE trailing full stop so a CV's bullets end consistently (spec 3.3).

    Ellipses and abbreviations keep theirs. The content object is not touched.
    """
    text = str(value).rstrip()
    if not text.endswith(".") or text.endswith("..") or _KEEP_STOP.search(text):
        return str(value)
    return text[:-1]
