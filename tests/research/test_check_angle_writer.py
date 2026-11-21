"""The per-language screen of the sweep writer: what it counts, and that it stores nothing."""

from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command

from apps.research.angles import AngleSet, GeneratedAngle
from apps.research.management.commands.check_angle_writer import carries
from apps.research.models import SweepAngle

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("sentence", "word", "expected"),
    [
        ("Vakfımız yüksek lisans öğrencilerine burs verir.", "vakıf", True),  # inflected stem
        ("Vakfımız yüksek lisans öğrencilerine burs verir.", "yüksek lisans", True),
        ("Unsere Stiftung vergibt Stipendien.", "Stiftung", True),
        ("Notre fondation attribue des bourses.", "fondation", True),
        ("Our ministry publishes the call.", "foundation", False),
        ("Burs başvuruları başladı.", "vakıf", False),
        ("当財団は修士学生への奨学金を募集します。", "財団", True),  # no spaces in Japanese
        ("Tá ár bhfondúireacht ag lorg iarratas.", "fondúireacht", True),  # Irish mutation
    ],
)
def test_a_word_is_carried_by_any_token_containing_its_stem(sentence, word, expected) -> None:
    assert carries(sentence, word) is expected


def _answer() -> AngleSet:
    return AngleSet(angles=[
        GeneratedAngle(
            angle="SEASON", query="Vakfımız 2026-2027 yüksek lisans burs başvurularını açtı.",
            brave_terms='intitle:burs "yüksek lisans"',
        ),
        GeneratedAngle(angle="ABOUT", query="Hakkımızda: hayır kurumumuz öğrencilere burs verir.",
                       brave_terms='intitle:a inbody:b inbody:c "d e"'),
    ])


def test_the_screen_counts_by_code_and_keeps_nothing(monkeypatch, settings) -> None:
    settings.OPENROUTER_API_KEY = "k"
    monkeypatch.setattr(
        "apps.research.angles.OpenRouterParser",
        lambda api_key: SimpleNamespace(parse=lambda **_: SimpleNamespace(output_parsed=_answer())),
    )
    monkeypatch.setattr(
        "apps.research.management.commands.check_angle_writer.timezone.now",
        lambda: __import__("datetime").datetime(2026, 10, 13),
    )
    out = StringIO()
    call_command("check_angle_writer", "--countries", "TR", stdout=out)
    lines = {line.split()[0]: line for line in out.getvalue().splitlines()[1:]}
    # Turkish: both sentences carry a kind word (vakıf, hayır kurumu), the year
    # is in digits, one keyword version is over the cap.
    assert lines["tr"].split()[2:] == ["2", "100%", "yes", "0", "1"]
    assert "en" in lines
    assert not SweepAngle.objects.exists()


def test_the_screen_refuses_without_a_key_and_past_its_cap(settings) -> None:
    settings.OPENROUTER_API_KEY = ""
    with pytest.raises(CommandError, match="OPENROUTER_API_KEY"):
        call_command("check_angle_writer", "--countries", "TR")
    with pytest.raises(CommandError, match="max-languages"):
        call_command("check_angle_writer", "--countries", "TR,FR,DE", "--max-languages", "2")


def test_a_dry_run_names_each_language_once_with_its_country() -> None:
    out = StringIO()
    call_command("check_angle_writer", "--countries", "FR,BE,US", "--dry-run", stdout=out)
    assert out.getvalue().split() == ["fr(FR)", "en(FR)", "nl(BE)", "de(BE)"]
