"""Cumulative tallies of who returned each host (spec 6.7, 15)."""

from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import call_command

from apps.research.models import (
    Organisation,
    SweepAngle,
    SweepDiscovery,
    SweepQuery,
    SweepRun,
)
from apps.research.register import record_organisation
from apps.research.tally import (
    angle_yield,
    found_by,
    language_yield,
    retire_dead_angles,
)

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 25, tzinfo=UTC)


def _angle(language="tr", kind="APPLICATION") -> SweepAngle:
    return SweepAngle.objects.create(
        country_code="TR", family="PRIVATE_FOUNDATION", language=language, angle=kind,
        sample=0, version=1, cycle="2026-2027", query=f"{kind} {language}", written_by="t",
    )


def _run() -> SweepRun:
    return SweepRun.objects.create(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=["tr", "en"], rung=4,
        cycle="2026-2027", started_at=NOW,
    )


def _found(run, angle, provider, domain, kind, funds, also: tuple[str, ...] = ()) -> None:
    org = record_organisation(domain=domain, name=domain, kind="UNSTATED", country_code="",
                              found_via=f"R4_SEARCH:{provider}")
    Organisation.objects.filter(pk=org.pk).update(
        kind=kind, funds_students=funds, classified_at=NOW
    )
    query = SweepQuery.objects.create(run=run, batch_number=1, angle=angle, provider=provider)
    SweepDiscovery.objects.create(
        run=run, query=query, organisation=org, returned_by=[provider, *also]
    )


def test_found_by_is_keyed_by_the_hosts_classified_family_and_credits_every_returner() -> None:
    run, angle = _run(), _angle()
    _found(run, angle, "exa", "a-vakfi.org.tr", "PRIVATE_FOUNDATION", True, also=("brave",))
    _found(run, angle, "brave", "sirket.com.tr", "EMPLOYER", True)
    _found(run, angle, "brave", "haber.com.tr", "UNSTATED", None)
    _found(run, angle, "exa", "b.org.tr", "PRIVATE_FOUNDATION", False)
    assert found_by() == {
        ("PRIVATE_FOUNDATION", "exa"): 1,
        ("PRIVATE_FOUNDATION", "brave"): 1,
        ("INDUSTRIAL_SPONSORSHIP", "brave"): 1,
        ("NOT_A_FUNDER", "brave"): 1,
        ("NOT_A_FUNDER", "exa"): 1,
    }


def test_angle_and_language_yield_are_cumulative_across_runs() -> None:
    tr, en = _angle("tr"), _angle("en")
    for _ in range(2):
        run = _run()
        SweepQuery.objects.create(run=run, batch_number=1, angle=en, provider="exa")
        _found(run, tr, "exa", f"v{run.pk.hex[:6]}.org.tr", "PRIVATE_FOUNDATION", True)
    assert angle_yield("TR", "PRIVATE_FOUNDATION")[tr.pk] == (2, 2)
    assert angle_yield("TR", "PRIVATE_FOUNDATION")[en.pk] == (2, 0)
    assert language_yield("TR", "PRIVATE_FOUNDATION") == {"tr": (2, 2), "en": (2, 0)}


def test_a_dead_angle_is_retired_only_past_the_threshold(settings) -> None:
    settings.SWEEP_DEAD_AFTER_USES = 4
    dead, alive = _angle("en", "FAQ"), _angle("tr")
    for _ in range(3):
        SweepQuery.objects.create(run=_run(), batch_number=1, angle=dead, provider="exa")
    assert retire_dead_angles("TR", "PRIVATE_FOUNDATION", now=NOW) == 0
    SweepQuery.objects.create(run=_run(), batch_number=1, angle=dead, provider="exa")
    assert retire_dead_angles("TR", "PRIVATE_FOUNDATION", now=NOW) == 1
    dead.refresh_from_db()
    assert dead.retired_at == NOW and "4 asks" in dead.retired_reason
    alive.refresh_from_db()
    assert alive.retired_at is None


def test_sweep_tally_command_prints_headings_and_retires_dead_angles() -> None:
    dead = _angle("en", "FAQ")
    run, angle = _run(), _angle("tr")
    _found(run, angle, "exa", "a-vakfi.org.tr", "PRIVATE_FOUNDATION", True)
    for _ in range(4):
        SweepQuery.objects.create(run=_run(), batch_number=1, angle=dead, provider="exa")

    out = StringIO()
    call_command("sweep_tally", "--country", "TR", "--family", "PRIVATE_FOUNDATION", stdout=out)
    output = out.getvalue()
    assert "novel hosts found" in output
    assert "per language" in output
    assert "per angle" in output
    assert "tr" in output

    out = StringIO()
    call_command(
        "sweep_tally", "--country", "TR", "--family", "PRIVATE_FOUNDATION",
        "--retire-dead", stdout=out,
    )
    assert "retired: 1" in out.getvalue()
