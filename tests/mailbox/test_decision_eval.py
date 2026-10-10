"""The corpus covers every hard case, the harness scores a run, and a live run is opt-in."""

import json
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.mailbox.decision_questions import FUNDING_OUTCOMES, OUTCOMES
from apps.research.models import GoldItem

CORPUS = json.loads((Path(__file__).parent / "decision_corpus.json").read_text(encoding="utf-8"))
HARD_CASES = {
    "conditional", "two_decisions", "other_programme", "stage_result", "reserve_list",
    "acknowledgement", "release_date", "reminder", "decision_available_only",
}


def test_the_corpus_covers_every_hard_case_in_five_languages() -> None:
    assert HARD_CASES <= {row["case"] for row in CORPUS}
    assert {"en", "de", "sv", "nl", "tr"} <= {row["language"] for row in CORPUS}
    for row in CORPUS:
        assert row["outcome"] in OUTCOMES
        assert row["funding_outcome"] in (*FUNDING_OUTCOMES, "")
        assert bool(row["funding"]) == bool(row["funding_outcome"])


@pytest.mark.django_db
def test_seeding_writes_one_gold_row_per_letter_and_question_once() -> None:
    call_command("decision_eval", "seed", "--run", "dm-test")
    call_command("decision_eval", "seed", "--run", "dm-test")
    rows = GoldItem.objects.filter(run="dm-test", kind="decision_mail")
    assert rows.filter(question="is_decision").count() == len(CORPUS)
    assert all(row.page_url.startswith("https://synthetic.invalid/decision-mail/") for row in rows)


@pytest.mark.django_db
def test_a_scored_run_reports_bars_rows_needed_and_cost(tmp_path, monkeypatch) -> None:
    from apps.mailbox.management.commands import decision_eval
    from tests.mailbox.test_decision_reader import FakeJev

    def truthful(state, questions, *, model, provider):
        row = next(r for r in CORPUS if r["body"] == state["email"]["body"])
        nouls = {"is_decision": 0.99 if row["is_decision"] else 0.01,
                 f"gate:{row['outcome']}": 0.99, f"fgate:{row['funding_outcome']}": 0.99,
                 "other_programme": 0.99 if row["offer"] else 0.01}
        return FakeJev(nouls, {"outcome": row["outcome"], "funding": row["funding_outcome"]})(
            state, questions, model=model, provider=provider)

    monkeypatch.setattr(decision_eval, "CLIENT", truthful)
    monkeypatch.setattr(decision_eval, "RUNS", tmp_path)
    call_command("decision_eval", "seed", "--run", "dm-fake")
    call_command("decision_eval", "read", "--run", "dm-fake", "--trust-corpus")
    call_command("decision_eval", "score", "--run", "dm-fake", "--trust-corpus")
    report = (tmp_path / "dm-fake" / "report.md").read_text()
    assert "zero-error rows needed: 299 (1/100), 1,497 (1/500)" in report
    assert "BARS = {" in report
    assert "USD" in report


@pytest.mark.live
@pytest.mark.django_db
def test_a_real_jev_run_over_the_corpus(tmp_path, monkeypatch) -> None:
    """Spends real tokens (~26 letters, about $0.001 at $0.042/1M). Never runs by default."""
    from apps.mailbox.management.commands import decision_eval

    monkeypatch.setattr(decision_eval, "RUNS", tmp_path)
    call_command("decision_eval", "seed", "--run", "dm-live")
    call_command("decision_eval", "read", "--run", "dm-live", "--wording", "a", "--trust-corpus")
    call_command("decision_eval", "read", "--run", "dm-live", "--wording", "b", "--trust-corpus")
    call_command("decision_eval", "score", "--run", "dm-live", "--trust-corpus")
    print((tmp_path / "dm-live" / "report.md").read_text())
