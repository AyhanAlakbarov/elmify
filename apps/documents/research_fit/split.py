"""Sentences from a page's lines, for the research-fit classifier.

Not letter_gates.sentence_spans: that one splits letter prose on any
terminal punctuation and is shared verbatim with hygiene re-anchoring, so it
must not learn abbreviations. Page text is different -- "Prof. Dr. A.
Schmidt" is one name, a heading or bullet line carries no full stop at all,
and a table row is a row. Splitting here is line-first, then punctuation
with an abbreviation guard. Every output sentence is a substring of exactly
one input line, which is what makes "is it really on the page" hold by
construction downstream.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

#: Terminal punctuation followed by whitespace and an uppercase/digit start.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÝĞİÖÜŞÇ0-9\"'(])")
#: Tokens that end in a dot but never end a sentence. Lowercase compare.
_ABBREVIATIONS = frozenset(
    {
        "prof", "dr", "dr.-ing", "ing", "mr", "mrs", "ms", "sr", "jr", "st", "no", "vs",
        "e.g", "i.e", "etc", "univ", "dept", "assoc", "asst", "hon", "phd", "msc", "bsc",
        "doç", "yrd", "öğr", "gör", "araş", "uzm", "bölüm", "fak", "müh",
        "dipl", "habil", "med", "rer", "nat", "phil", "jun", "sen", "ca", "bzw", "z.b", "u.a",
    }
)
_INITIAL = re.compile(r"^[A-ZÀ-ÝĞİÖÜŞÇ]\.$")
_MARKER = re.compile(r"^(#+\s*|-\s+|\*\s+|\d+[.)]\s+)")
_MIN_SENTENCE_CHARS = 12


def _ends_with_abbreviation(chunk: str) -> bool:
    last = chunk.rstrip().rsplit(None, 1)[-1] if chunk.strip() else ""
    bare = last.rstrip(".").lower()
    return bool(_INITIAL.match(last)) or bare in _ABBREVIATIONS


def _split_line(line: str) -> list[str]:
    parts: list[str] = []
    buffer = ""
    for piece in _BOUNDARY.split(line):
        buffer = f"{buffer} {piece}".strip() if buffer else piece.strip()
        if _ends_with_abbreviation(buffer):
            continue
        parts.append(buffer)
        buffer = ""
    if buffer:
        parts.append(buffer)
    return parts


def page_sentences(lines: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for raw in lines:
        line = _MARKER.sub("", raw.strip())
        if line.startswith("|") and line.endswith("|"):
            line = line.strip("|").strip()
        if not line:
            continue
        for sentence in _split_line(line):
            if len(sentence) >= _MIN_SENTENCE_CHARS:
                out.append(sentence)
    return tuple(out)
