"""backfill_evidence_domain (ruling I2): a Program written before Task 3's
writer change gets the same evidence_domain/evidence_institutional the
writer would have given it, and a second run changes nothing."""

import importlib
import io

import pytest
from django.apps import apps
from django.core.management import call_command

from apps.funding.models import Program
from apps.research.models import OrganisationDomain
from tests.research.provenance_helpers import evidence_program

pytestmark = pytest.mark.django_db


def _pre_task_3_program(*urls: str, name: str = "MSc Computer Science") -> Program:
    """A programme exactly as the writer left it before Task 3 existed: its
    claims sit on `urls`, but evidence_domain/evidence_institutional are
    still at the plain db_default -- nothing ever computed them."""
    program = evidence_program(*urls, name=name)
    Program.objects.filter(id=program.id).update(
        evidence_domain="", evidence_institutional=False
    )
    program.refresh_from_db()
    return program


def test_backfill_matches_what_the_writer_would_have_written() -> None:
    program = _pre_task_3_program("https://www.tum.de/a", "https://www.cit.tum.de/b")
    assert (program.evidence_domain, program.evidence_institutional) == ("", False)

    call_command("backfill_evidence_domain", stdout=io.StringIO())

    program.refresh_from_db()
    assert (program.evidence_domain, program.evidence_institutional) == ("tum.de", True)
    body = OrganisationDomain.objects.get(registrable_domain="tum.de").organisation
    assert body.kind == "INSTITUTION"
    assert body.country_code == ""
    assert "CATALOG:programme" in body.found_via


def test_a_program_with_no_evidence_is_left_at_the_default() -> None:
    program = _pre_task_3_program()

    call_command("backfill_evidence_domain", stdout=io.StringIO())

    program.refresh_from_db()
    assert (program.evidence_domain, program.evidence_institutional) == ("", False)


def test_disagreeing_evidence_stays_unbound() -> None:
    program = _pre_task_3_program("https://www.tum.de/a", "https://www.lmu.de/b")

    call_command("backfill_evidence_domain", stdout=io.StringIO())

    program.refresh_from_db()
    assert (program.evidence_domain, program.evidence_institutional) == ("", False)


def test_reports_set_disagreeing_and_no_evidence_counts() -> None:
    _pre_task_3_program("https://www.tum.de/a")  # set
    _pre_task_3_program("https://www.tum.de/a", "https://www.lmu.de/b")  # disagreeing
    _pre_task_3_program()  # no evidence

    out = io.StringIO()
    call_command("backfill_evidence_domain", stdout=out)

    output = out.getvalue()
    assert "set on 1" in output
    assert "1 disagreeing" in output
    assert "1 with no evidence" in output


def test_a_second_run_changes_nothing() -> None:
    _pre_task_3_program("https://www.tum.de/a")
    _pre_task_3_program("https://www.tum.de/b", "https://www.lmu.de/c")
    _pre_task_3_program()
    call_command("backfill_evidence_domain", stdout=io.StringIO())
    program_fields = ("id", "evidence_domain", "evidence_institutional")
    before = list(Program.objects.order_by("id").values_list(*program_fields))
    domains_before = list(
        OrganisationDomain.objects.order_by("id").values_list("id", "organisation_id")
    )

    call_command("backfill_evidence_domain", stdout=io.StringIO())

    after = list(Program.objects.order_by("id").values_list(*program_fields))
    domains_after = list(
        OrganisationDomain.objects.order_by("id").values_list("id", "organisation_id")
    )
    assert before == after
    assert domains_before == domains_after


def test_a_joint_programme_records_its_body_under_the_provider_text_cut_to_300() -> None:
    program = _pre_task_3_program("https://www.emjm-example.eu/apply")
    provider_text = "University A; " * 30  # 420 chars, over Organisation.name's 300
    Program.objects.filter(id=program.id).update(
        provision_type=Program.ProvisionType.JOINT, institution=None, provider_text=provider_text
    )

    call_command("backfill_evidence_domain", stdout=io.StringIO())

    program.refresh_from_db()
    assert program.evidence_domain == "emjm-example.eu"
    body = OrganisationDomain.objects.get(registrable_domain="emjm-example.eu").organisation
    assert body.name == provider_text[:300]


def test_a_hosting_platform_programme_records_no_body() -> None:
    program = _pre_task_3_program("https://tum-msc.netlify.app/apply")

    call_command("backfill_evidence_domain", stdout=io.StringIO())

    program.refresh_from_db()
    assert program.evidence_domain == "tum-msc.netlify.app"
    assert not OrganisationDomain.objects.filter(
        registrable_domain="tum-msc.netlify.app"
    ).exists()


def test_origin_domain_is_filled_from_the_earliest_claim_where_empty() -> None:
    program = _pre_task_3_program("https://www.tum.de/a", "https://www.lmu.de/b")
    assert program.origin_domain == ""

    call_command("backfill_evidence_domain", stdout=io.StringIO())

    program.refresh_from_db()
    assert program.origin_domain == "tum.de"


def test_the_migration_fills_origin_domain_from_the_earliest_claim() -> None:
    migration = importlib.import_module("apps.funding.migrations.0055_provenance")
    program = _pre_task_3_program("https://www.tum.de/a", "https://www.lmu.de/b")
    empty = _pre_task_3_program()

    migration.fill_origin_domain(apps, None)

    program.refresh_from_db()
    empty.refresh_from_db()
    assert (program.origin_domain, empty.origin_domain) == ("tum.de", "")

