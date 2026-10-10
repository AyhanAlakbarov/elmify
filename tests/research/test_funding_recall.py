import csv
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.models import (
    FundingOpportunity,
    FundingOpportunityEvidenceClaim,
    Institution,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)

pytestmark = pytest.mark.django_db

HEADER = [
    "institution_ror", "institution", "country_iso", "programme_url", "kind", "pattern",
    "verified_on", "source_url",
]


def _csv(tmp_path, rows):
    path = tmp_path / "known.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def _row(url="https://uni.example/msc-a", pattern="tuition waiver"):
    return ["https://ror.org/0abc", "Uni", "DE", url, "I2_PROGRAMME_ATTACHED", pattern,
            "2026-09-13", url]


def _snapshot(url, funding_read=True):
    source, _ = OfficialSource.objects.get_or_create(
        canonical_url=url,
        defaults={"publisher": "uni.example", "source_type": OfficialSource.Type.PROGRAM},
    )
    return OfficialSourceSnapshot.objects.create(
        source=source, sha256=uuid4().hex * 2, s3_key="k", s3_version_id="v", byte_size=1,
        final_url=url, redirect_chain=[], admissions_cycle="2027",
        # retrieved_at has no default on the real model; the brief's fixture
        # omitted it (task-4 brief line 53) and IntegrityError'd on save.
        retrieved_at=timezone.now(),
        funding_read_at=timezone.now() if funding_read else None,
    )


def _served_row(url, quote, served=True, funding_read=True):
    institution = Institution.objects.create(
        canonical_key=f"i:{uuid4()}", name="Uni", country_code="DE",
        official_website="https://uni.example",
    )
    program = Program.objects.create(
        institution=institution, canonical_key=f"p:{uuid4()}", name="MSc A", campus_name="M",
        city="B", country_code="DE", location_key="de:b", degree_level="MASTER",
        teaching_languages=["English"], duration_months=24,
    )
    snapshot = _snapshot(url, funding_read=funding_read)
    source = snapshot.source
    opportunity = FundingOpportunity.objects.create(
        canonical_key=f"o:{uuid4()}", name="waiver", family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM", program=program, kind="I2_PROGRAMME_ATTACHED",
        agreement="AGREED" if served else "UNAGREED", served=served,
    )
    claim = OfficialEvidenceClaim.objects.create(
        source=source, snapshot=snapshot, claim=quote, evidence_strength="DIRECT",
        visibility="STUDENT_FACING", claim_class="FUNDING", last_checked_at=timezone.now(),
    )
    FundingOpportunityEvidenceClaim.objects.create(opportunity=opportunity, evidence_claim=claim)


def _report(path):
    out = StringIO()
    call_command("funding_recall", csv=str(path), stdout=out)
    return out.getvalue()


def test_pending_when_nothing_was_read_at_that_origin(tmp_path):
    text = _report(_csv(tmp_path, [_row()]))
    assert "PENDING" in text and "pass=0 unserved=0 missed=0 pending=1 badpattern=0" in text


def test_pass_when_a_served_row_quotes_the_pattern(tmp_path):
    _served_row("https://uni.example/msc-a", "All admitted students receive a tuition waiver.")
    text = _report(_csv(tmp_path, [_row()]))
    assert "PASS" in text and "pass=1" in text


def test_unserved_when_the_row_exists_but_did_not_agree(tmp_path):
    _served_row("https://uni.example/msc-a", "A tuition waiver is granted.", served=False)
    assert "UNSERVED" in _report(_csv(tmp_path, [_row()]))


def test_missed_when_the_origin_was_read_but_the_award_was_not_found(tmp_path):
    _served_row("https://uni.example/other", "A stipend is paid.")
    assert "MISSED" in _report(_csv(tmp_path, [_row()]))


def test_a_lookalike_host_does_not_turn_pending_into_missed(tmp_path):
    # "https://uni.example.evil.test/x" contains "//uni.example" as a
    # substring, so a plain icontains=f"//{origin}" filter would treat it as
    # a row read at uni.example's origin -- wrongly turning PENDING into
    # MISSED for a programme nothing has actually read.
    _served_row("https://uni.example.evil.test/x", "A stipend is paid.")
    text = _report(_csv(tmp_path, [_row()]))
    assert "PENDING" in text and "pass=0 unserved=0 missed=0 pending=1" in text


def test_the_committed_csv_has_the_spec_header():
    from pathlib import Path

    path = Path(__file__).parents[2] / "docs" / "research" / "programme-funding-known-answers.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == HEADER


def test_missed_when_the_host_was_read_and_nothing_at_all_was_found(tmp_path):
    """I8: a complete read that wrote no row is MISSED, not PENDING."""
    _snapshot("https://uni.example/msc-a")
    assert "MISSED" in _report(_csv(tmp_path, [_row()]))


def test_pending_when_the_host_was_fetched_but_never_funding_read(tmp_path):
    _served_row("https://uni.example/msc-a", "A tuition waiver is granted.", funding_read=False)
    assert "PENDING" in _report(_csv(tmp_path, [_row()]))


def test_a_leading_www_does_not_separate_one_host(tmp_path):
    _served_row("https://uni.example/msc-a", "All admitted students receive a tuition waiver.")
    text = _report(_csv(tmp_path, [_row(url="https://www.uni.example/msc-a")]))
    assert "PASS" in text and "pass=1" in text


def test_an_invalid_pattern_is_reported_not_raised(tmp_path):
    _served_row("https://uni.example/msc-a", "A tuition waiver is granted.")
    text = _report(_csv(tmp_path, [_row(pattern="tuition (waiver"), _row()]))
    assert "BADPATTERN" in text
    assert "pass=1 unserved=0 missed=0 pending=0 badpattern=1" in text
