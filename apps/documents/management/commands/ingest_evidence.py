"""A student's evidence, from the console (CV evidence spec §13).

    uv run python manage.py ingest_evidence --tenant <agency> --student <membership>

runs refresh_evidence for the student -- forced past the 10-minute skip -- and
prints what it did and every reading, each bullet with its support verdict.

    ... --source https://doi.org/10.1021/acs.jcim.4c00001

ingests one DOI as a confirmed publication fact: the only caller of the DOI
path. Repositories are never named here; the refresh finds them from the
student's GitHub username.

On ECS, run it as a one-off `aws ecs run-task` of DocumentWorkerTaskDefinition
with a command override: that task holds GITHUB_TOKEN, OPENAI_API_KEY and the
OpenRouter key, and connects as runtime_engine.
"""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.documents.evidence import facts, ingest_evidence
from apps.documents.evidence.readings import usable_readings
from apps.documents.evidence.refresh import refresh_evidence
from apps.documents.evidence.sources import DoiRef, UnsupportedSource, parse_source
from apps.tenancy.context import tenant_scope


class Command(BaseCommand):
    help = "Refresh a student's repo and thesis readings, or ingest one DOI with --source."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--student", required=True)
        parser.add_argument("--source", default="")

    def handle(self, *args: object, **options: object) -> None:
        source = str(options["source"] or "")
        if source:
            try:
                ref = parse_source(source)
            except UnsupportedSource as error:
                raise CommandError(f"unusable source: {error}") from None
            if not isinstance(ref, DoiRef):
                raise CommandError(
                    "--source takes a DOI; repositories are read by refresh_evidence"
                )
        try:
            tenant_id = UUID(str(options["tenant"]))
            student_id = UUID(str(options["student"]))
        except ValueError:
            raise CommandError("--tenant and --student must be UUIDs") from None
        with tenant_scope(tenant_id):
            found = facts.refreshable_student(tenant_id, student_id)
            if found is None:
                raise CommandError(
                    f"no active student {student_id} in tenant {tenant_id}, "
                    "or they are being erased; nothing is read"
                )
            student = found
            if source:
                result = ingest_evidence(student=student, raw_source=source)
                self.stdout.write(f"outcome={result.outcome.value} facts={len(result.facts)}")
                for line in (result.reason, result.question):
                    if line:
                        self.stdout.write(line)
                return
            report = refresh_evidence(student, force=True)
            readings = usable_readings(student)
        self.stdout.write(
            f"read={len(report.read)} deleted={report.deleted} "
            f"github_requests={report.github_requests} model_calls={report.model_calls} "
            f"tokens={report.tokens} stopped={report.stopped or '-'}"
        )
        if report.message:
            self.stdout.write(report.message)
        for reading in readings:
            self.stdout.write(
                f"[{reading.source}] {reading.url or reading.document_id} "
                f"{reading.kind}: {reading.summary}"
            )
            for bullet in reading.bullets:
                self.stdout.write(f"  - ({bullet.verdict}) {bullet.text}")
