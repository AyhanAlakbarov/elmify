import csv
import json
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command

from apps.documents.relevance_eval import PASS_MARK, GoldRow, load_gold, report

_HEADER = ["set_id", "programme_id", "section", "item_text", "language", "owner_label"]


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_HEADER)
        writer.writerows(rows)


def test_the_committed_gold_file_loads():
    """The owner fills it; every row the owner writes must pass this loader."""
    from pathlib import Path

    load_gold(Path("docs/research/cv-relevance-gold.csv"))


@pytest.mark.parametrize("bad", [
    ["s1", str(uuid4()), "awards", "Chess prize", "en", "maybe"],
    ["s1", str(uuid4()), "education", "BSc", "en", "keep"],
    ["s1", str(uuid4()), "awards", "Chess prize", "fr", "keep"],
    ["s1", "not-a-uuid", "awards", "Chess prize", "en", "keep"],
    ["s1", str(uuid4()), "awards", "", "en", "keep"],
])
def test_a_row_outside_the_closed_lists_is_refused(tmp_path, bad):
    path = tmp_path / "gold.csv"
    _write(path, [bad])
    with pytest.raises(ValueError):
        load_gold(path)


def test_the_report_scores_each_language_on_the_items_jev_would_leave_out():
    pid = uuid4()
    rows = [GoldRow("s", pid, "awards", f"item {n}", "en", "leave_out") for n in range(150)]
    rows += [GoldRow("s", pid, "awards", "kept one", "en", "keep")]
    rows += [GoldRow("s", pid, "awards", "один", "ru", "keep")]
    scores = [0.97] * 150 + [0.95, 0.99]
    result = report(rows, scores, bar=0.9)
    assert result["en"]["left_out_at_bar"] == 151
    assert result["en"]["precision_at_bar"] == pytest.approx(150 / 151)
    assert result["en"]["passes"] is (150 / 151 >= PASS_MARK)
    assert result["ru"]["precision_at_bar"] == 0.0 and result["ru"]["passes"] is False


def test_run_files_must_live_outside_the_repository(tmp_path, settings):
    with pytest.raises(CommandError):
        call_command("cv_relevance_eval", "--out", str(settings.BASE_DIR / "runs"))


@pytest.mark.django_db
def test_the_command_writes_its_run_outside_the_repo(tmp_path, program_factory, monkeypatch):
    from apps.documents import relevance_eval
    from apps.documents.relevance import Verdict

    programme = program_factory()
    gold = tmp_path / "gold.csv"
    _write(gold, [["s1", str(programme.id), "awards", "Chess prize", "en", "leave_out"]])
    monkeypatch.setattr(relevance_eval, "requirement_sentences", lambda p: ("Chemistry.",))
    monkeypatch.setattr(relevance_eval, "ask_item",
                        lambda item, **kw: Verdict("unrelated", 0.96, 0.96, "jev"))
    out = tmp_path / "run"
    call_command("cv_relevance_eval", "--gold", str(gold), "--out", str(out))
    written = json.loads((out / "report.json").read_text())
    assert written["en"]["left_out_at_bar"] == 1
    assert (out / "scores.csv").exists()


@pytest.mark.django_db
def test_multi_model_eval_compares_jev_1_13_and_jev_1_14(tmp_path, program_factory, monkeypatch):
    from django.conf import settings

    from apps.documents import relevance_eval
    from apps.documents.relevance import Verdict

    programme = program_factory()
    gold = tmp_path / "gold.csv"
    _write(
        gold,
        [
            ["s1", str(programme.id), "awards", "Chess prize", "en", "leave_out"],
            ["s2", str(programme.id), "skills", "Python", "en", "keep"],
        ],
    )
    seen_models: list[str] = []

    def fake_ask(item, **kw):
        seen_models.append(settings.TYPESAFE_MODEL)
        if item.text == "Chess prize":
            return Verdict("unrelated", 0.96, 0.96, settings.TYPESAFE_MODEL)
        # Simulate jev-1.14 keeping Python while jev-1.13 drops it
        if settings.TYPESAFE_MODEL == "typesafe/jev-1.14":
            return Verdict("asked_for", 0.95, 0.01, settings.TYPESAFE_MODEL)
        return Verdict("unrelated", 0.92, 0.92, settings.TYPESAFE_MODEL)

    monkeypatch.setattr(relevance_eval, "requirement_sentences", lambda p: ("Python.",))
    monkeypatch.setattr(relevance_eval, "ask_item", fake_ask)
    out = tmp_path / "multi_run"
    call_command(
        "cv_relevance_eval",
        "--gold",
        str(gold),
        "--out",
        str(out),
        "--models",
        "typesafe/jev-1.13,typesafe/jev-1.14",
    )
    assert seen_models == [
        "typesafe/jev-1.13",
        "typesafe/jev-1.13",
        "typesafe/jev-1.14",
        "typesafe/jev-1.14",
    ]
    comparison = json.loads((out / "comparison.json").read_text())
    assert comparison["disagreement_count"] == 1
    assert comparison["agreement_rate"] == 0.5
    assert (
        comparison["models"]["typesafe/jev-1.14"]["by_language"]["en"]["precision_at_bar"]
        == 1.0
    )
    assert (
        comparison["models"]["typesafe/jev-1.13"]["by_language"]["en"]["precision_at_bar"]
        == 0.5
    )


def test_compare_skills_scores_jev_against_tailor_skills():
    from apps.documents.relevance_eval import compare_skills

    verdicts = {
        "Python": ("asked_for", 0.96),
        "RDKit": ("same_field", 0.88),
        "Excel": ("general_merit", 0.75),
        "Pottery": ("unrelated", 0.95),
    }
    res = compare_skills(verdicts, tailored_matched=["Python", "RDKit", "Pottery"], bar=0.9)
    assert res["skills_total"] == 4
    assert res["both_relevant"] == ["python", "rdkit"]
    assert res["tailor_only_relevant"] == ["pottery"]
    assert res["jev_unrelated_but_tailor_matched"] == ["pottery"]
    assert res["agreement_rate"] == 0.75

