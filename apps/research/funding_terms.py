"""The funding words a page's sections are kept by, in every page language.

`readable_text(terms=...)` drops each section matching none of these, so this table is a fetch
filter in all but name and must fail open (verified-catalog §5 step 1): a word missing here hides a
funding section from every reader. Data, not code, reviewed like
docs/research/currency-evidence.csv.
"""

from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

FUNDING_TERMS_FILE = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "funding-terms.csv"
)


@cache
def funding_terms() -> re.Pattern[str]:
    """One case-insensitive pattern: `stem` rows match anywhere, `word` rows only as whole words."""
    with FUNDING_TERMS_FILE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    parts = sorted(
        (
            rf"(?<!\w){re.escape(r['term'])}(?!\w)" if r["match"] == "word"
            else re.escape(r["term"])
            for r in rows
        ),
        key=len,
        reverse=True,
    )
    return re.compile("|".join(parts), re.IGNORECASE)
