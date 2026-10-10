import json

import pytest
from django.core.management import CommandError, call_command

from apps.research.engine_eval import items as items_mod
from apps.research.engine_eval.chat import SpendCapReached
from apps.research.models import GoldItem


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(items_mod, "RUNS", tmp_path)
    d = tmp_path / "r1"
    d.mkdir()
    rows = [{"id": f"p0l{n}", "page": "https://e.org/a", "language": "az", "scheme": "s",
             "half": "score", "text": f"Müraciət {n} yanvar 2027-dək.", "heading": "Müraciət"}
            for n in range(60)]
    (d / "items.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (d / "pages.jsonl").write_text(json.dumps({"url": "https://e.org/a", "final_url": "https://e.org/a",
                                               "language": "az", "scheme": "s", "skip_reason": "",
                                               "text": "P", "json_extract": {}}))
    return d


def test_read_saves_progress_and_resumes_after_the_spend_cap(run, monkeypatch):
    from apps.research.engine_eval import chat_reader
    seen = []

    def fake(name, items, spend, **kw):
        out = {}
        for item in items:
            if len(seen) == 30:
                raise SpendCapReached("cap")
            seen.append(item.id)
            out[item.id] = {"application_date": 0.99, "_vote": False}
        return out
    monkeypatch.setattr(chat_reader, "read_chat", fake)
    call_command("engine_eval", "read", "--run", "r1", "--reader", "ds_flash", "--max-usd", "1")
    assert len(json.loads((run / "reader-ds_flash-a.json").read_text())) >= 25
    seen.clear()
    call_command("engine_eval", "read", "--run", "r1", "--reader", "ds_flash", "--max-usd", "1")
    assert "p0l0" not in seen


@pytest.mark.django_db
def test_queue_creates_gold_items_once(run, capsys):
    reads = json.dumps({f"p0l{n}": {"application_date": 0.99} for n in range(60)})
    (run / "reader-jev-a.json").write_text(reads)
    (run / "reader-ds_flash-a.json").write_text(reads)
    args = ("engine_eval", "queue", "--run", "r1", "--purpose", "improvement", "--round", "1",
            "--per-kind", "10")
    call_command(*args)
    assert "10 created, 0 already existed" in capsys.readouterr().out
    call_command(*args)
    assert "0 created, 10 already existed" in capsys.readouterr().out
    assert GoldItem.objects.filter(run="r1", kind="deadline").count() == 10


@pytest.mark.django_db
def test_queue_skips_a_page_url_that_is_not_http(run):
    rows = [json.loads(ln) for ln in (run / "items.jsonl").read_text().splitlines()]
    for r in rows:
        r["page"] = "javascript:alert(1)"
    (run / "items.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    reads = json.dumps({f"p0l{n}": {"application_date": 0.99} for n in range(60)})
    (run / "reader-jev-a.json").write_text(reads)
    (run / "reader-ds_flash-a.json").write_text(reads)
    call_command("engine_eval", "queue", "--run", "r1", "--purpose", "improvement", "--round", "1")
    assert GoldItem.objects.count() == 0


@pytest.mark.django_db
def test_score_counts_wrong_and_not_on_page_as_errors(run):
    for n, verdict in enumerate(["correct", "wrong", "not_on_page", ""]):
        GoldItem.objects.create(
            run="r1", kind="deadline", question="application_date", language="az",
            page_url="https://e.org/a", line_text=f"l{n}", claim="c", round=1,
            purpose="certification", verdict=verdict)
    call_command("engine_eval", "score", "--run", "r1")
    report = (run / "report.md").read_text()
    assert "| deadline | 3 | 2 |" in report


def _qs():
    from apps.research.engine_eval.questions import LINE_QUESTIONS
    return [q.id for q in LINE_QUESTIONS]


def test_only_unsettled_sends_the_third_reader_just_the_open_items(run, monkeypatch):
    from apps.research.engine_eval import chat_reader
    row = {q: 0.99 for q in _qs()}
    (run / "reader-jev-a.json").write_text(json.dumps({f"p0l{n}": row for n in range(60)}))
    # the second reader skipped p0l0 entirely and left one question of p0l1 unanswered
    second = {f"p0l{n}": row for n in range(2, 60)}
    second["p0l1"] = {q: v for q, v in row.items() if q != _qs()[0]}
    (run / "reader-ds_flash-a.json").write_text(json.dumps(second))
    seen = []

    def fake(name, items, spend, **kw):
        seen.extend(i.id for i in items)
        return {i.id: {q: 0.5 for q in _qs()} for i in items}
    monkeypatch.setattr(chat_reader, "read_chat", fake)
    call_command("engine_eval", "read", "--run", "r1", "--reader", "gemini_flash",
                 "--only-unsettled", "--max-usd", "1")
    assert sorted(seen) == ["p0l0", "p0l1"]


def test_spend_is_written_after_each_batch_not_only_at_the_end(run, monkeypatch):
    from apps.research.engine_eval import chat_reader
    seen_files = []

    def fake(name, items, spend, **kw):
        spend.add(0.25)
        f = run / "spend.json"
        seen_files.append(json.loads(f.read_text())["usd"] if f.exists() else None)
        return {i.id: {"application_date": 0.99, "_vote": False} for i in items}
    monkeypatch.setattr(chat_reader, "read_chat", fake)
    call_command("engine_eval", "read", "--run", "r1", "--reader", "ds_flash", "--max-usd", "5")
    assert seen_files == [None, 0.25, 0.5]  # 60 items = 3 batches; each sees the prior batch's save


@pytest.mark.django_db
def test_score_writes_a_section_per_jev_wording_that_exists(run):
    row = {q: 0.99 for q in _qs()}
    for w in "ab":
        (run / f"reader-jev-{w}.json").write_text(json.dumps({"p0l0": row}))
    (run / "reader-ds_flash-a.json").write_text(json.dumps({"p0l0": row}))
    call_command("engine_eval", "score", "--run", "r1")
    report = (run / "report.md").read_text()
    assert "both/ds_flash/jev-a" in report and "both/ds_flash/jev-b" in report


def test_rows_read_jev_and_the_third_reader_in_the_asked_wording(run):
    from apps.research.management.commands.engine_eval import Command
    for w, p in (("a", 0.9), ("b", 0.2)):
        (run / f"reader-jev-{w}.json").write_text(json.dumps({"p0l0": {q: p for q in _qs()}}))
        (run / f"reader-kimi_k3-{w}.json").write_text(json.dumps({"p0l0": {q: p for q in _qs()}}))
    rows = [r for r in Command()._rows(run, "ds_flash", "b") if r["id"] == "p0l0"]
    assert rows and all(r["jev"] == 0.2 and r["third"] == 0.2 for r in rows)


def test_a_chat_reader_refuses_wording_b_outside_only_unsettled(run):
    with pytest.raises(CommandError, match="--wording b"):
        call_command("engine_eval", "read", "--run", "r1", "--reader", "ds_pro", "--wording", "b")


def test_only_unsettled_never_pays_a_third_reader_for_a_vote_row(run, monkeypatch):
    from apps.research.engine_eval import chat_reader
    (run / "reader-jev-a.json").write_text(json.dumps({"p0l0": {q: 0.6 for q in _qs()}}))
    vote = {q: 1.0 for q in _qs()} | {"_vote": True}
    (run / "reader-ds_flash-a.json").write_text(
        json.dumps({f"p0l{n}": vote for n in range(60)}))
    seen = []

    def fake(name, items, spend, **kw):
        seen.extend(i.id for i in items)
        return {}
    monkeypatch.setattr(chat_reader, "read_chat", fake)
    call_command("engine_eval", "read", "--run", "r1", "--reader", "kimi_k3",
                 "--only-unsettled", "--max-usd", "1")
    assert seen == []


def test_a_vote_row_is_never_accepted_under_both_even_when_jev_is_sure(run):
    from apps.research.engine_eval import score as score_mod
    from apps.research.management.commands.engine_eval import Command
    (run / "reader-jev-a.json").write_text(json.dumps({"p0l0": {q: 0.999 for q in _qs()}}))
    vote = {q: 1.0 for q in _qs()} | {"_vote": True}
    (run / "reader-ds_flash-a.json").write_text(json.dumps({"p0l0": vote}))
    rows = [r for r in Command()._rows(run, "ds_flash") if r["id"] == "p0l0"]
    assert rows and all(r["second"] is None and r["jev"] == 0.999 for r in rows)
    assert not any(score_mod._accepted(r, "both", 0.9) for r in rows)


def test_a_reader_is_never_its_own_third(run):
    from apps.research.management.commands.engine_eval import Command
    (run / "reader-jev-a.json").write_text(json.dumps({"p0l0": {q: 0.9 for q in _qs()}}))
    (run / "reader-kimi_k3-a.json").write_text(json.dumps({"p0l0": {q: 0.8 for q in _qs()}}))
    (run / "reader-gemini_flash-a.json").write_text(json.dumps({"p0l0": {q: 0.3 for q in _qs()}}))
    rows = [r for r in Command()._rows(run, "kimi_k3") if r["id"] == "p0l0"]
    assert all(r["second"] == 0.8 and r["third"] == 0.3 for r in rows)
