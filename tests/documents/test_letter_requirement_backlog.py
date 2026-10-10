"""Task 11: the counter that finds the next column worth adding."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.funding.models import ApplicationPrompt

from .conftest import make_program

pytestmark = pytest.mark.django_db


def _prompt(cycle: str, *, written=(), actions=()) -> None:
    ApplicationPrompt.objects.create(
        programme=make_program(),
        cycle=cycle,
        source_url=f"https://example.test/{cycle}",
        confidence=0.0,
        source=ApplicationPrompt.Source.EXTRACTED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        document_language="en",
        letter_written_requirements=list(written),
        letter_student_actions=list(actions),
    )


def _run(**options) -> str:
    out = StringIO()
    call_command("letter_requirement_backlog", stdout=out, **options)
    return out.getvalue()


def test_the_same_rule_worded_the_same_way_counts_once_per_programme() -> None:
    for cycle in ("2027", "2028", "2029"):
        _prompt(
            cycle,
            written=[{"text": "Write in the THIRD person.  ", "source_url": "https://a.test"}],
        )
    _prompt("2030", actions=[{"text": "Sign it in ink.", "source_url": "https://b.test"}])
    output = _run()
    assert "   3  written  Write in the THIRD person." in output
    assert "   1  action   Sign it in ink." in output
    assert "https://a.test" in output


def test_the_minimum_is_the_backlog_threshold() -> None:
    _prompt("2027", written=[{"text": "Write in the third person.", "source_url": ""}])
    _prompt("2028", actions=[{"text": "Sign it in ink.", "source_url": ""}])
    assert "third person" not in _run(minimum=2)


def test_an_entry_with_no_url_of_its_own_falls_back_to_the_prompts() -> None:
    _prompt("2027", written=[{"text": "Explain your motivation.", "source_url": ""}])
    assert "https://example.test/2027" in _run()


def test_nothing_recorded_says_so() -> None:
    assert "no letter requirements recorded yet" in _run()
