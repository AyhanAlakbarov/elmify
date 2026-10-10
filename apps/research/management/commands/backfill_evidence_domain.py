"""Backfill Program.evidence_domain/evidence_institutional for existing rows.

Ruling I2 (docs/superpowers/sdd/2026-09-26-provenance-gate/constraints.md):
`Program.evidence_domain`/`evidence_institutional` are written only by the
catalogue writer from Task 3 onward -- every Program written before that
change carries the plain db_default ("", False), never computed. Left
alone, turning on `PROVENANCE_GATE_ENFORCED` would silently exclude every
programme catalogued before this command exists from every pack: not
pending, not checked, just gone.

This runs the exact same computation the writer runs --
`apps.research.provenance.record_program_evidence`, the one shared function
-- over every existing Program, so a programme catalogued before Task 3 and
one catalogued after it get the same answer. Idempotent: `record_program_evidence`
only writes a Program row whose values actually changed, and `record_organisation`
only writes an Organisation row whose names/found_via tags actually changed, so a
second run touches no data.

Operator-run once per database, before `provenance_check --all` (Task 12) and
before `PROVENANCE_GATE_ENFORCED` is turned on (Task 18's runbook orders it).
Writes the catalogue: run with DATABASE_ROLE=runtime_engine, same role as the
discovery writer.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.funding.models import OfficialEvidenceClaim, Program, ProgramEvidenceClaim
from apps.research.hosts import registrable_domain
from apps.research.provenance import record_program_evidence


def _institution_name(program: Program) -> str:
    """What the catalogue writer would have passed as `institution_name` when
    this programme was first written: the JOINT provider string exactly as
    scraped, or the (single) Institution's own name."""
    if program.provision_type == Program.ProvisionType.JOINT:
        return program.provider_text
    institution = program.institution
    return institution.name if institution is not None else ""


class Command(BaseCommand):
    help = (
        "Backfill Program.evidence_domain/evidence_institutional for every "
        "existing programme from its own OfficialEvidenceClaim URLs, using "
        "the same function the catalogue writer uses (ruling I2). Run once, "
        "before PROVENANCE_GATE_ENFORCED, with DATABASE_ROLE=runtime_engine."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        origins = 0
        set_count = 0
        disagreeing = 0
        no_evidence = 0
        for program in Program.objects.select_related("institution").order_by("id"):
            # Migration funding/0055 does this too, but under a role RLS keeps out of
            # funding_program writes it updates nothing; this runs as the
            # writer's role. Same rule: the page of the earliest evidence claim.
            first_url = (
                ProgramEvidenceClaim.objects.filter(program=program)
                .order_by("id")
                .values_list("evidence_claim__source__canonical_url", flat=True)
                .first()
            )
            origin = registrable_domain(first_url or "")
            if origin and not program.origin_domain:
                origins += Program.objects.filter(id=program.id, origin_domain="").update(
                    origin_domain=origin
                )
            domain, _institutional = record_program_evidence(
                program, institution_name=_institution_name(program)
            )
            if domain:
                set_count += 1
            elif OfficialEvidenceClaim.objects.filter(program=program).exists():
                disagreeing += 1
            else:
                no_evidence += 1
        self.stdout.write(
            f"origin_domain set on {origins} programmes, "
            f"evidence_domain set on {set_count} programmes, "
            f"{disagreeing} disagreeing, {no_evidence} with no evidence"
        )
