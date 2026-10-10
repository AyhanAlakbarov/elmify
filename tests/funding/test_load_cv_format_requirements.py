import csv

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.funding.models import Program

pytestmark = pytest.mark.django_db

_HEADER = [
    "ID",
    "Rule",
    "Applies to",
    "Scope",
    "Binding or advisory",
    "Source (tier)",
    "Source URL [provenance]",
    "Verified for cycle",
    "Confidence",
]


def _write_csv(tmp_path, rows):
    path = tmp_path / "cv-rules.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_HEADER)
        writer.writerows(rows)
    return path


def _row(rule_id, cycle, confidence):
    return [
        rule_id,
        "GLOBED EMJM: Europass required; resumes in other formats won't be accepted",
        "layout",
        "funder (GLOBED)",
        "binding",
        "T1",
        "https://example.org/globed",
        cycle,
        confidence,
    ]


@pytest.fixture
def mapped_program(program_factory, monkeypatch):
    from apps.funding import cv_ruleset_scope_map

    program = program_factory(canonical_key="globed-emjm")
    monkeypatch.setitem(
        cv_ruleset_scope_map.RULE_TO_PROGRAM,
        "R-056",
        cv_ruleset_scope_map.RuleTarget(
            canonical_key="globed-emjm", requirement="europass_required"
        ),
    )
    return program


def test_loader_sets_verified_requirement_from_a_high_confidence_dated_row(
    tmp_path, mapped_program
):
    csv_path = _write_csv(tmp_path, [_row("R-056", "Edition XI, 2026", "high")])
    call_command("load_cv_format_requirements", str(csv_path))
    mapped_program.refresh_from_db()
    assert mapped_program.cv_format_requirement == Program.CVFormatRequirement.EUROPASS_REQUIRED
    assert mapped_program.cv_format_verified_for_cycle == "Edition XI, 2026"
    assert mapped_program.cv_format_confidence == Program.CVFormatConfidence.VERIFIED
    assert mapped_program.cv_format_source_url == "https://example.org/globed"


@pytest.mark.parametrize(
    ("cycle", "confidence"),
    [
        ("", "high"),
        ("re-fetched 2026-08-21: STALE, refers to 2024-25 - reverify", "high"),
        ("cycle label unconfirmed", "high"),
        ("Edition XI, 2026", "medium"),
        ("Edition XI, 2026", "low"),
        # R-066's real cv-rules.csv cell: states there is no dated cycle but
        # trips none of the _HEDGES substrings -- needs a positive year check.
        ("current template, cycle label not printed on file", "high"),
        ("2026 - reverify", "high"),
    ],
)
def test_loader_refuses_a_high_risk_value_from_an_unverified_row(
    tmp_path, mapped_program, cycle, confidence
):
    csv_path = _write_csv(tmp_path, [_row("R-056", cycle, confidence)])
    call_command("load_cv_format_requirements", str(csv_path))
    mapped_program.refresh_from_db()
    assert mapped_program.cv_format_requirement == Program.CVFormatRequirement.ANY
    assert mapped_program.cv_format_confidence == Program.CVFormatConfidence.UNVERIFIED


def test_allow_unverified_flag_loads_it_anyway_but_not_as_verified(tmp_path, mapped_program):
    csv_path = _write_csv(tmp_path, [_row("R-056", "cycle label unconfirmed", "high")])
    call_command("load_cv_format_requirements", str(csv_path), "--allow-unverified")
    mapped_program.refresh_from_db()
    assert mapped_program.cv_format_requirement == Program.CVFormatRequirement.EUROPASS_REQUIRED
    assert mapped_program.cv_format_confidence == Program.CVFormatConfidence.UNVERIFIED
    assert mapped_program.cv_format_verified_for_cycle is None


def test_low_risk_value_loads_from_an_undated_row_as_extracted(
    tmp_path, program_factory, monkeypatch
):
    from apps.funding import cv_ruleset_scope_map

    program = program_factory(canonical_key="ytb")
    monkeypatch.setitem(
        cv_ruleset_scope_map.RULE_TO_PROGRAM,
        "R-075",
        cv_ruleset_scope_map.RuleTarget(canonical_key="ytb", requirement="any"),
    )
    csv_path = _write_csv(tmp_path, [_row("R-075", "no cycle stated on page - reverify", "low")])
    call_command("load_cv_format_requirements", str(csv_path))
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.ANY
    assert program.cv_format_confidence == Program.CVFormatConfidence.UNVERIFIED


def test_loader_skips_an_unmapped_rule_id(tmp_path, program_factory):
    program = program_factory(canonical_key="globed-emjm")
    csv_path = _write_csv(tmp_path, [_row("R-999", "2026", "high")])
    call_command("load_cv_format_requirements", str(csv_path))  # must not raise
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.ANY


def test_loader_skips_a_cycle_too_long_for_the_column_instead_of_crashing(
    tmp_path, mapped_program, capsys
):
    # R-064's real cv-rules.csv cell -- 55 chars against max_length=40.
    cycle = "2026/2027 (template header: 'Updated 13 November 2025')"
    assert len(cycle) > 40
    csv_path = _write_csv(tmp_path, [_row("R-056", cycle, "high")])
    call_command("load_cv_format_requirements", str(csv_path))  # must not raise DataError
    mapped_program.refresh_from_db()
    assert mapped_program.cv_format_requirement == Program.CVFormatRequirement.ANY
    assert mapped_program.cv_format_source_url == ""
    err = capsys.readouterr().err
    assert "R-056" in err and "40" in err


def test_loader_reports_how_many_programmes_a_rule_updated(
    tmp_path, program_factory, monkeypatch, capsys
):
    from apps.funding import cv_ruleset_scope_map

    program_factory(canonical_key="globed-emjm")
    program_factory(canonical_key="globed-emjm")
    monkeypatch.setitem(
        cv_ruleset_scope_map.RULE_TO_PROGRAM,
        "R-056",
        cv_ruleset_scope_map.RuleTarget(
            canonical_key="globed-emjm", requirement="europass_required"
        ),
    )
    csv_path = _write_csv(tmp_path, [_row("R-056", "Edition XI, 2026", "high")])
    call_command("load_cv_format_requirements", str(csv_path))
    out = capsys.readouterr().out
    assert "R-056" in out and "2" in out


def test_loader_refuses_the_same_programme_read_from_two_sites(
    tmp_path, mapped_program, program_factory, capsys
):
    """Rows differing only by origin_domain are one programme as two sites
    describe it; a hand-verified rule is never applied to both, nor to one."""
    program_factory(
        canonical_key="globed-emjm", institution=mapped_program.institution,
        origin_domain="globed-admissions.com",
    )
    csv_path = _write_csv(tmp_path, [_row("R-056", "Edition XI, 2026", "high")])
    call_command("load_cv_format_requirements", str(csv_path))
    assert "more than one site" in capsys.readouterr().err
    assert not Program.objects.filter(
        canonical_key="globed-emjm",
        cv_format_requirement=Program.CVFormatRequirement.EUROPASS_REQUIRED,
    ).exists()


def test_loader_tolerates_a_bom_prefixed_csv(tmp_path, mapped_program):
    path = tmp_path / "cv-rules.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(_HEADER)
        writer.writerow(_row("R-056", "Edition XI, 2026", "high"))
    call_command("load_cv_format_requirements", str(path))
    mapped_program.refresh_from_db()
    assert mapped_program.cv_format_requirement == Program.CVFormatRequirement.EUROPASS_REQUIRED


def test_loader_raises_a_command_error_for_a_missing_column(tmp_path, mapped_program):
    path = tmp_path / "cv-rules.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Rule"])
        writer.writerow(["R-056", "whatever"])
    with pytest.raises(CommandError):
        call_command("load_cv_format_requirements", str(path))


def test_loader_reports_a_mapped_rule_whose_program_is_missing(tmp_path, monkeypatch, capsys):
    from apps.funding import cv_ruleset_scope_map

    monkeypatch.setitem(
        cv_ruleset_scope_map.RULE_TO_PROGRAM,
        "R-056",
        cv_ruleset_scope_map.RuleTarget(canonical_key="nope", requirement="any"),
    )
    csv_path = _write_csv(tmp_path, [_row("R-056", "2026", "high")])
    call_command("load_cv_format_requirements", str(csv_path))
    assert "nope" in capsys.readouterr().err


def test_the_real_csv_parses_and_every_mapped_id_exists_in_it():
    """The map is hand-maintained; this catches a typo'd or retired rule ID."""
    from apps.funding.cv_ruleset_scope_map import RULE_TO_PROGRAM

    with open("docs/research/cv-rules.csv", newline="", encoding="utf-8") as handle:
        ids = {row["ID"] for row in csv.DictReader(handle)}
    assert set(RULE_TO_PROGRAM) <= ids
    # RULE_TO_PROGRAM ships empty, so the assertion above is vacuously true
    # until an entry is added -- assert the map module's own commented
    # examples name real rows, so this test carries weight today too.
    assert {"R-056", "R-064", "R-066"} <= ids
