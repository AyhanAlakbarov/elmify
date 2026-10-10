"""Hand-maintained map from docs/research/cv-rules.csv rule IDs to a programme.

The CSV's ``Rule`` column is prose, not a machine-readable setting: it says
"GLOBED EMJM: Europass required; Resumes in other formats won't be accepted",
not ``cv_format_requirement=europass_required``. Parsing prose to decide what a
funder mandates is exactly the guessing the CV design doc forbids, so the
decision lives here, made by a human once per rule, and the CSV supplies only
the provenance (source URL, cycle, confidence) for it.

Extend this by hand as funders are catalogued. An entry whose canonical_key
matches no Program is reported on stderr, not silently skipped.

The loader writes the CSV's ``Verified for cycle`` cell verbatim into
``Program.cv_format_verified_for_cycle``, a ``CharField(max_length=40)``. A
row whose cell exceeds 40 characters (e.g. SISGP's real cell, "2026/2027
(template header: 'Updated 13 November 2025')", is 55 chars) is skipped with
a stderr report rather than truncated -- check the CSV cell length before
wiring up a new rule ID here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleTarget:
    canonical_key: str
    #: One of Program.CVFormatRequirement's values.
    requirement: str


RULE_TO_PROGRAM: dict[str, RuleTarget] = {
    # "R-056": RuleTarget(canonical_key="globed-emjm", requirement="europass_required"),
    # "R-064": RuleTarget(canonical_key="si-sisgp", requirement="funder_template"),
    # "R-066": RuleTarget(canonical_key="rhodes", requirement="funder_template"),
}
