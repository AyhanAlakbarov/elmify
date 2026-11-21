"""Stored programme angles: the table, the writer's rules, the binding."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, transaction

from apps.research.models import ProgrammeAngle
from apps.research.programme_angles import (
    TemplateRow,
    TemplateSet,
    generate_programme_angles,
    refusal,
)
from apps.research.seam_bindings import ProgrammeAngleSource
from apps.research.tap_seams import bound_angles

pytestmark = pytest.mark.django_db


def _row(**overrides):
    fields = dict(level="MASTER", language="en", kind="PROGRAMME", sample=0, version=1,
                  cycle="2026-2027", template="Our M.Sc. in {field}, taught in {teaching_language}",
                  written_by="t")
    return {**fields, **overrides}


def test_a_key_is_written_once_per_version() -> None:
    ProgrammeAngle.objects.create(**_row())
    with pytest.raises(IntegrityError), transaction.atomic():
        ProgrammeAngle.objects.create(**_row())
    ProgrammeAngle.objects.create(**_row(version=2))


def test_the_kind_is_closed() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        ProgrammeAngle.objects.create(**_row(kind="BLOG"))


NOW = datetime(2026, 10, 14, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "template", "reason"),
    [
        ("PROGRAMME", "Our M.Sc. in {field}, taught in {teaching_language}", None),
        ("PROGRAMME", "M.Sc. {field} for {nationality} students", "slot"),
        ("PROGRAMME", "Fully funded master's in {field}", "money"),
        ("PROGRAMME", "M.Sc. {field} with a {money}", "money"),
        ("PROGRAMME", "Apply to the master's programme", "field"),
        ("MONEY", "Scholarships for our master's in {field}: {money}", None),
        ("MONEY", "Scholarships for our master's in {field}", "money"),
        ("RECENCY", "Applications for the {intake} intake of the M.Sc. in {field} are open", None),
        ("RECENCY", "Applications for the M.Sc. in {field} are open", "intake"),
        ("PROGRAMME", "M.Sc. in {field", "format"),
        # A conversion or format spec reshapes the student's words; an escaped
        # brace leaves a literal slot no student value ever fills.
        ("PROGRAMME", "MSc {field!r} in {destination:>40}", "format"),
        ("PROGRAMME", "MSc {field} {{destination}}", "format"),
    ],
)
def test_a_template_is_refused_for_one_stated_reason(kind, template, reason) -> None:
    got = refusal(kind, template)
    assert (got is None) if reason is None else (got is not None and reason in got)


class _Parser:
    def __init__(self, answer: TemplateSet | None):
        self.answer, self.calls = answer, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.answer)


def _set() -> TemplateSet:
    return TemplateSet(templates=[
        TemplateRow(
            kind="PROGRAMME", template="Our M.Sc. in {field}, taught in {teaching_language}"
        ),
        TemplateRow(kind="PROGRAMME", template="Fully funded M.Sc. in {field}"),  # refused: money
        TemplateRow(
            kind="MONEY",
            template="Scholarships and fee waivers for our M.Sc. in {field}: {money}",
        ),
        TemplateRow(
            kind="RECENCY",
            template="Applications for the {intake} intake of our M.Sc. in {field}",
        ),
    ])


def test_only_usable_rows_are_stored_and_the_call_carries_no_student(settings) -> None:
    settings.SWEEP_ANGLE_MODEL = "deepseek/deepseek-v4.1-flash"
    parser = _Parser(_set())
    assert generate_programme_angles(language="de", parser=parser, now=NOW) == "written"
    rows = ProgrammeAngle.objects.filter(language="de")
    assert sorted(rows.values_list("kind", flat=True)) == ["MONEY", "PROGRAMME", "RECENCY"]
    assert set(rows.values_list("cycle", flat=True)) == {"2026-2027"}
    (call,) = parser.calls
    data = call["input"][1]["content"]
    assert "DATA" in call["input"][0]["content"] and "language: de" in data
    assert call["store"] is False and call["max_output_tokens"] <= 6000


def test_a_current_set_is_not_asked_again() -> None:
    parser = _Parser(_set())
    generate_programme_angles(language="de", parser=parser, now=NOW)
    assert generate_programme_angles(language="de", parser=parser, now=NOW) == "exists"
    assert len(parser.calls) == 1


def test_no_answer_and_nothing_usable_store_nothing() -> None:
    assert generate_programme_angles(language="fr", parser=_Parser(None), now=NOW) == "no_answer"
    bad = TemplateSet(templates=[TemplateRow(kind="PROGRAMME", template="Fully funded {field}")])
    assert generate_programme_angles(language="fr", parser=_Parser(bad), now=NOW) == "no_usable"
    assert not ProgrammeAngle.objects.filter(language="fr").exists()


def test_a_set_whose_programme_rows_all_need_a_destination_is_not_usable() -> None:
    only = TemplateSet(templates=[
        TemplateRow(kind="PROGRAMME", template="Our M.Sc. in {field} in {destination}"),
    ])
    assert generate_programme_angles(language="it", parser=_Parser(only), now=NOW) == "no_usable"
    assert not ProgrammeAngle.objects.filter(language="it").exists()


def test_a_regenerated_set_missing_a_kind_retires_nothing() -> None:
    generate_programme_angles(language="de", parser=_Parser(_set()), now=NOW)
    no_money = TemplateSet(templates=[
        row for row in _set().templates if row.kind != "MONEY"
    ] + [TemplateRow(kind="MONEY", template="Scholarships for our M.Sc. in {field}")])
    assert generate_programme_angles(
        language="de", parser=_Parser(no_money), now=NOW, regenerate=True
    ) == "no_usable"
    live = ProgrammeAngle.objects.filter(language="de", retired_at__isnull=True)
    assert set(live.values_list("version", flat=True)) == {1} and live.count() == 3


def test_the_command_refuses_without_the_key_and_prints_what_it_stored(
    settings, monkeypatch
) -> None:
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.research import programme_angles as pa

    settings.OPENROUTER_API_KEY = ""
    with pytest.raises(CommandError, match="OPENROUTER_API_KEY"):
        call_command("generate_programme_angles", language=["de"])
    settings.OPENROUTER_API_KEY = "k"
    monkeypatch.setattr("apps.research.angles.OpenRouterParser", lambda api_key: _Parser(_set()))
    out = StringIO()
    call_command("generate_programme_angles", language=["de"], stdout=out)
    assert "de: written" in out.getvalue()
    assert "PROGRAMME 0: Our M.Sc. in {field}, taught in {teaching_language}" in out.getvalue()
    assert "Never name a real" in pa._DEVELOPER


def test_the_bound_source_serves_the_latest_live_version_and_only_this_cycle_s_recency(
    monkeypatch,
) -> None:
    template = "{field} {money} {intake}"
    ProgrammeAngle.objects.create(**_row(version=1, cycle="2024-2025"))  # an older live version
    for kind in ("PROGRAMME", "MONEY", "RECENCY"):  # last cycle's set, still the latest
        ProgrammeAngle.objects.create(
            **_row(kind=kind, version=2, cycle="2025-2026", template=template)
        )
    monkeypatch.setattr("apps.research.seam_bindings.cycle_label", lambda now: "2026-2027")
    source = bound_angles()
    assert isinstance(source, ProgrammeAngleSource)
    programme = source.programme_angles(level="MASTER", language="en")
    assert [a.id for a in programme] == [
        str(ProgrammeAngle.objects.get(kind=k, version=2).id) for k in ("PROGRAMME", "MONEY")
    ]
    # Only RECENCY carries {intake}: last cycle's announcement is never asked.
    assert source.recency_angles(level="MASTER", language="en") == ()
    ProgrammeAngle.objects.create(
        **_row(kind="RECENCY", version=3, cycle="2026-2027", template=template)
    )
    assert len(source.recency_angles(level="MASTER", language="en")) == 1
    assert len(source.programme_angles(level="MASTER", language="en")) == 2
    assert source.programme_angles(level="MASTER", language="ja") == ()
