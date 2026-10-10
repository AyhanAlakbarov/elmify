"""The discipline buckets `CellCoverage` is keyed by (spec 10.6).

A coarse ACCOUNTING unit only: it groups students so a thin cell can be named.
It never filters a pool and never enters a query -- the tailored design (T6) is
explicit that fine-grained field is not a taxonomy, and the query carries the
student's own field words (tap_query.py), not this label.

**The vocabulary is ISCED-F 2013's 26 narrow fields, not the spec's Korean
middle tier, and the Korean measurement is OWED.** Spec 10.6 names "the
28-value middle tier of Korea's classification" (data.go.kr #15139338's
`중계열분류`). The plan's Task 1 reads that file and counts the distinct values
over live master's-bearing rows before trusting the 28; the file is served by
academyinfo.go.kr, and this build's egress refused both it and data.go.kr
(CONNECT 403, 2026-09-26). So this module ships the plan's own prepared
alternative: UNESCO's ISCED-F 2013 narrow fields, less the three `00x` generic
programmes, plus `unclassifiable`. The CSV's `verified_on` says `owed` on every
ISCED row because the labels were transcribed, not re-read against the UNESCO
PDF (also refused by the egress policy the same day). Owed, both: count the
Korean `중계열분류` values (the plan's Task 1 Step 1 filter) and re-read the
UNESCO labels; if the Korean count lands in 25-35, the owner decides whether
the vocabulary switches. A switch changes `CellCoverage` keys, which are
recomputed wholesale on every refresh, so it needs no data migration -- only
`ProfileCellSelection` rows would need re-reading.

`docs/research/` ships in the image (.dockerignore excludes only
docs/superpowers), so reading the CSV at import is safe in production.
"""

from __future__ import annotations

import csv
from pathlib import Path

_CSV = Path(__file__).resolve().parents[2] / "docs" / "research" / "discipline-buckets.csv"

UNCLASSIFIABLE = "unclassifiable"


def _load() -> tuple[str, ...]:
    with _CSV.open(encoding="utf-8") as handle:
        return tuple(row["slug"] for row in csv.DictReader(handle))


BUCKETS: tuple[str, ...] = _load()
