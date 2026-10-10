from datetime import timedelta

import pytest
from django.utils import timezone

from apps.funding.models import OfficialEvidenceClaim, OfficialSource
from apps.research.egress import FetchResult
from apps.research.snapshot import (
    CLAIM_MAX_AGE,
    claim_is_stale,
    fresh_claims,
    persist_snapshot,
    touch_claims,
)

pytestmark = pytest.mark.django_db


def _source() -> OfficialSource:
    return OfficialSource.objects.create(
        canonical_url="https://official.example/program",
        publisher="official.example",
        source_type=OfficialSource.Type.PROGRAM,
    )


def _claim(source: OfficialSource, claim_class: str | None, age_days: int) -> OfficialEvidenceClaim:
    return OfficialEvidenceClaim.objects.create(
        source=source,
        claim="Tuition is EUR 0 per year.",
        evidence_strength="DIRECT",
        visibility="STUDENT_FACING",
        claim_class=claim_class,
        last_checked_at=timezone.now() - timedelta(days=age_days),
    )


@pytest.mark.parametrize(
    ("claim_class", "days"),
    [
        ("IDENTITY", 365),
        ("STRUCTURE", 180),
        ("ELIGIBILITY", 180),
        ("TUITION", 90),
        ("FUNDING", 30),
        ("DEADLINE", 30),
    ],
)
def test_each_claim_class_has_the_window_the_design_gives_it(claim_class: str, days: int) -> None:
    source = _source()

    assert CLAIM_MAX_AGE[claim_class] == timedelta(days=days)
    assert claim_is_stale(_claim(source, claim_class, days + 1)) is True
    assert claim_is_stale(_claim(source, claim_class, days - 1)) is False


def test_an_unclassified_claim_gets_the_tightest_window() -> None:
    source = _source()

    assert claim_is_stale(_claim(source, None, 31)) is True


def test_stale_claims_are_dropped_before_they_can_enter_a_pack() -> None:
    source = _source()
    fresh = _claim(source, "IDENTITY", 10)
    _claim(source, "DEADLINE", 45)

    assert [claim.id for claim in fresh_claims(OfficialEvidenceClaim.objects.all())] == [fresh.id]


def test_snapshots_record_the_technique_that_produced_the_lead(fake_store) -> None:
    source = _source()

    result = persist_snapshot(
        source=source,
        fetch=FetchResult(source.canonical_url, (), "text/html", b"<html></html>"),
        store=fake_store,
        admissions_cycle="2027",
        discovery_technique="entity-expansion",
    )

    result.snapshot.refresh_from_db()
    assert result.snapshot.discovery_technique == "entity-expansion"


def test_a_claim_class_outside_the_contract_is_refused_by_the_database() -> None:
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        _claim(_source(), "GUESSED", 1)


def test_revisiting_an_unchanged_page_refreshes_the_window_instead_of_duplicating(
    fake_store,
) -> None:
    """The freshness mechanism §7.1 depends on: last_checked_at moves, and no
    second copy of the same sentence is written."""
    source = _source()
    snapshot = persist_snapshot(
        source=source,
        fetch=FetchResult(source.canonical_url, (), "text/html", b"<html></html>"),
        store=fake_store,
        admissions_cycle="2027",
    ).snapshot
    claim = _claim(source, "DEADLINE", 20)
    OfficialEvidenceClaim.objects.filter(id=claim.id).update(snapshot=snapshot)
    assert claim_is_stale(OfficialEvidenceClaim.objects.get(id=claim.id)) is False

    touched = touch_claims(snapshot)

    claim.refresh_from_db()
    assert touched == 1
    assert claim_is_stale(claim) is False
    assert (timezone.now() - claim.last_checked_at).days == 0
    assert OfficialEvidenceClaim.objects.count() == 1
