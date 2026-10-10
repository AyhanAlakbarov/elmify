"""The operator commands around the harness: they refuse loudly rather than
run a pass that cannot say what it measured."""

from datetime import date

import pytest
from django.core.management import CommandError, call_command

from apps.research.models import ClosedList, SweepAngle

pytestmark = pytest.mark.django_db


def test_generation_without_a_vocabulary_is_refused_with_the_interim_named() -> None:
    with pytest.raises(CommandError, match="--from-steering"):
        call_command("generate_sweep_angles", "--country", "TR", "--family", "PRIVATE_FOUNDATION")


def test_the_steering_interim_writes_one_labelled_row() -> None:
    call_command(
        "generate_sweep_angles", "--country", "TR", "--family", "PRIVATE_FOUNDATION",
        "--from-steering",
    )
    assert list(SweepAngle.objects.values_list("written_by", flat=True)) == ["STEERING"]


def test_the_steering_interim_never_replaces_a_generated_set() -> None:
    for n in range(3):
        SweepAngle.objects.create(
            country_code="TR", family="PRIVATE_FOUNDATION", language="tr", angle="FAQ",
            sample=n, version=1, cycle="2026-2027", query=f"Vakfımız burs verir {n}.",
            brave_terms="vakfı burs", written_by="gpt",
        )
    with pytest.raises(CommandError, match="generated angle set"):
        call_command(
            "generate_sweep_angles", "--country", "TR", "--family", "PRIVATE_FOUNDATION",
            "--from-steering",
        )
    assert not SweepAngle.objects.filter(written_by="STEERING").exists()


def test_a_family_with_no_sweep_is_refused() -> None:
    with pytest.raises(CommandError):
        call_command("generate_sweep_angles", "--country", "TR", "--family", "MULTILATERAL")


def test_from_steering_for_a_country_with_no_steering_row_names_the_ones_that_have_one() -> None:
    with pytest.raises(CommandError, match="ZZ") as excinfo:
        call_command(
            "generate_sweep_angles", "--country", "ZZ", "--family", "PRIVATE_FOUNDATION",
            "--from-steering",
        )
    assert "TR" in str(excinfo.value)
    assert SweepAngle.objects.count() == 0


# --- sweep_organisations (ruling R6: the rung comes from ladder_rung, no
# --- --rung / --register flags) -----------------------------------------


def test_a_sweep_with_no_provider_key_is_refused(settings) -> None:
    settings.EXA_API_KEY = settings.BRAVE_API_KEY = ""
    with pytest.raises(CommandError, match="no provider key"):
        call_command(
            "sweep_organisations", "--country", "AZ", "--family", "PRIVATE_FOUNDATION",
        )


def test_a_register_rung_needs_a_read_register(settings) -> None:
    settings.EXA_API_KEY = "k"
    ClosedList.objects.create(
        slug="vgm_tr", title="VGM", country_code="TR",
        holder_kinds=["PRIVATE_FOUNDATION"], rung=1,
        source_url="https://example.org/vgm", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="FUNDING_READ", verified_on=date(2026, 9, 25),
    )
    with pytest.raises(CommandError, match="no RegisterEntry"):
        call_command(
            "sweep_organisations", "--country", "TR", "--family", "PRIVATE_FOUNDATION",
        )


def test_a_dry_run_names_what_would_run(settings, capsys) -> None:
    settings.EXA_API_KEY, settings.BRAVE_API_KEY = "k", ""
    call_command(
        "sweep_organisations", "--country", "AZ", "--family", "PRIVATE_FOUNDATION",
        "--language", "az", "--dry-run",
    )
    assert (
        "would sweep AZ/PRIVATE_FOUNDATION rung 4 in az, en with: exa"
        in capsys.readouterr().out
    )


def test_a_diaspora_pass_runs_its_home_language_then_english(settings, capsys) -> None:
    settings.EXA_API_KEY, settings.BRAVE_API_KEY = "k", ""
    call_command(
        "sweep_organisations", "--country", "DE", "--family", "AFFINITY_OR_DIASPORA",
        "--home-language", "AZ", "--dry-run",
    )
    assert "would sweep DE/AFFINITY_OR_DIASPORA/az rung 4 in az, en" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["sweep_organisations", "generate_sweep_angles"])
@pytest.mark.parametrize(
    ("family", "homes", "message"),
    [
        ("AFFINITY_OR_DIASPORA", [], "exactly one home language"),
        ("AFFINITY_OR_DIASPORA", ["az", "tr"], "exactly one home language"),
        ("PRIVATE_FOUNDATION", ["az"], "AFFINITY_OR_DIASPORA only"),
        ("AFFINITY_OR_DIASPORA", ["a;z"], "not a language code"),
    ],
)
def test_a_diaspora_pass_takes_exactly_one_home_language_and_no_other_pass_takes_one(
    settings, django_assert_num_queries, command, family, homes, message,
) -> None:
    settings.EXA_API_KEY, settings.BRAVE_API_KEY = "k", ""
    flags = [item for home in homes for item in ("--home-language", home)]
    with django_assert_num_queries(0), pytest.raises(CommandError, match=message):
        call_command(command, "--country", "DE", "--family", family, "--dry-run", *flags)


@pytest.mark.parametrize("extra", [[], ["--from-steering"]])
def test_generation_refuses_a_malformed_country_on_every_path(
    django_assert_num_queries, extra,
) -> None:
    with django_assert_num_queries(0), pytest.raises(CommandError, match="not an ISO 3166-1"):
        call_command(
            "generate_sweep_angles", "--country", "TUR", "--family", "PRIVATE_FOUNDATION", *extra,
        )


def test_a_language_is_lowercased(settings, capsys) -> None:
    settings.EXA_API_KEY, settings.BRAVE_API_KEY = "k", ""
    call_command(
        "sweep_organisations", "--country", "tr", "--family", "PRIVATE_FOUNDATION",
        "--language", "TR", "--dry-run",
    )
    assert "would sweep TR/PRIVATE_FOUNDATION rung 4 in tr, en" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [("--language", "x;y", "not a language code"), ("--country", "TUR", "not an ISO 3166-1")],
)
def test_a_malformed_code_is_refused_before_any_query(
    settings, django_assert_num_queries, flag, value, message,
) -> None:
    settings.EXA_API_KEY, settings.BRAVE_API_KEY = "k", ""
    args = {"--country": "TR", "--language": "tr", flag: value}
    with django_assert_num_queries(0), pytest.raises(CommandError, match=message):
        call_command(
            "sweep_organisations", "--family", "PRIVATE_FOUNDATION", "--dry-run",
            *(item for pair in args.items() for item in pair),
        )


def test_explicit_budget_usd_zero_is_not_replaced_by_default(
    settings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit --budget-usd 0 must reach run_pass as 0.0, not the default."""
    from apps.research.management.commands import sweep_organisations

    settings.EXA_API_KEY = "k"
    settings.BRAVE_API_KEY = ""

    recorded_config = None

    def fake_run_pass(config, **_):
        nonlocal recorded_config
        recorded_config = config
        raise ValueError("stop")

    def fake_openai():
        fake_client = type("FakeOpenAI", (), {"responses": object()})()
        return fake_client

    monkeypatch.setattr(sweep_organisations, "run_pass", fake_run_pass)
    monkeypatch.setattr("openai.OpenAI", fake_openai)

    with pytest.raises(CommandError):
        call_command(
            "sweep_organisations", "--country", "AZ", "--family", "PRIVATE_FOUNDATION",
            "--language", "az", "--budget-usd", "0",
        )

    assert recorded_config is not None
    assert recorded_config.budget_usd == 0.0
