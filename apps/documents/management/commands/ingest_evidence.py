"""Ingest one artefact a student has named -- a paper's DOI, or their own repository.

    POSTGRES_DB=... uv run python manage.py ingest_evidence \
        --tenant <agency-uuid> --student <membership-uuid> \
        --source https://doi.org/10.1021/acs.jcim.4c00001

The first caller of ``apps.documents.evidence.ingest_evidence`` outside its own
tests, and deliberately a console one: the CV engine reads the uploaded CV and
nothing else, so a student's papers and code reach the ledger only through
this. Everything it writes is a CANDIDATE fact (``confirmed_by=None``) unless
the evidence package's own gate auto-confirms it -- generation still cannot see
any of it until a human accepts it, which is the whole design.

A repository additionally needs ``owner_login`` to be someone we have reason to
believe is the student, because ``repo.authorship()`` reduces to
``contributors.get(owner_login, 0) > 0`` -- pass a stranger's login and a
stranger's repository becomes the student's skills. There is no verified
GitHub account link on a profile yet, so this takes the handle from a
CONFIRMED identity fact instead: the student's own uploaded CV printed it and a
human accepted it. No confirmed handle, no repository ingest.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.documents.evidence import ingest_evidence
from apps.documents.evidence.sources import DoiRef, UnsupportedSource, parse_source
from apps.documents.models import VerifiedFact
from apps.documents.verification import generatable_facts
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership


def _profile_handle(url: str) -> str:
    """The single path segment of a github.com profile address, or nothing."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() not in {"github.com", "www.github.com"}:
        return ""
    segments = [segment for segment in parts.path.split("/") if segment]
    return segments[0] if len(segments) == 1 else ""


def confirmed_github_login(student: Membership) -> str:
    """The GitHub handle a human has already accepted for this student.

    Reads the confirmed IDENTITY facts only -- ``generatable_facts`` is the
    same confirmation gate generation runs on. Falls back to a confirmed
    ``github_url`` when the CV printed an address rather than a handle, which
    is the more common of the two.

    The address is parsed, not searched. ``github_url`` is validated only as
    an https URL (``schemas._HTTPS_URL_PATTERN`` constrains no host), so
    substring matching on "github.com/" reads
    ``https://evil.example/?r=github.com/victim`` as GitHub -- and this handle
    decides authorship, because ``repo.authorship()`` reduces to
    ``contributors.get(owner_login, 0) > 0``. Same reasoning as
    ``schemas._anchor_text``, which already refuses "github.com.evil.example".

    A profile is one path segment. A CV linking a project it merely used
    (``github.com/tensorflow/models``) would otherwise claim that project's
    owner as the applicant.
    """
    for fact in generatable_facts(student).filter(category=VerifiedFact.Category.IDENTITY):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        handle = str(payload.get("github_username") or "").strip()
        if not handle:
            handle = _profile_handle(str(payload.get("github_url") or ""))
        if handle:
            return handle
    return ""


class Command(BaseCommand):
    help = "Ingest one DOI or repository as candidate facts for a student."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--student", required=True)
        parser.add_argument("--source", required=True)

    def handle(self, *args: object, **options: object) -> None:
        source = str(options["source"])
        try:
            ref = parse_source(source)
        except UnsupportedSource as error:
            raise CommandError(f"unusable source: {error}") from None
        with tenant_scope(UUID(str(options["tenant"]))):
            student = Membership.objects.get(id=UUID(str(options["student"])))
            owner_login = confirmed_github_login(student)
            if not isinstance(ref, DoiRef) and owner_login.casefold() != ref.owner.casefold():
                raise CommandError(
                    f"{ref.owner!r} is not this student's confirmed GitHub handle "
                    f"({owner_login or 'none on file'}) -- confirm the identity fact "
                    "that names it before ingesting their repositories"
                )
            result = ingest_evidence(
                student=student, raw_source=source, owner_login=owner_login
            )
        self.stdout.write(f"outcome={result.outcome.value} facts={len(result.facts)}")
        for line in (result.reason, result.question):
            if line:
                self.stdout.write(line)
