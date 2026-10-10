import csv
import datetime as dt

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.research.management.commands import refresh_country_labels as command
from apps.research.management.commands.cycle_verify import GateRow, score


def test_country_labels_are_written_from_wikidata_rows(tmp_path, monkeypatch):
    calls = []

    def fake_query(text):
        calls.append(text)
        return {"results": {"bindings": [
            {"code": {"value": "tr"}, "label": {"value": "Türkiye", "xml:lang": "tr"},
             "kind": {"value": "label"}},
            {"code": {"value": "IN"}, "label": {"value": "Indian", "xml:lang": "en"},
             "kind": {"value": "demonym"}},
        ]}}

    # The request itself (endpoint, User-Agent, accept types) is built once in
    # wikidata._query and covered by tests/research/test_wikidata.py; this
    # command is tested only on what it does with the response.
    monkeypatch.setattr(command, "_query", fake_query)
    monkeypatch.setattr(command, "MIN_ROWS", 2)
    out = tmp_path / "labels.csv"
    call_command("refresh_country_labels", "--out", str(out))

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert {(r["label"], r["iso2"], r["kind"]) for r in rows} == {
        ("Türkiye", "TR", "label"), ("Indian", "IN", "demonym"),
    }
    assert all(r["source"] == command.SPARQL_URL and r["fetched_on"] for r in rows)
    assert calls  # the SPARQL text reached _query


def test_a_short_reply_is_refused_and_the_existing_file_is_kept(tmp_path, monkeypatch):
    """A 200 with no bindings is a failed query, not a world without countries:
    writing it would empty every country phrase to OTHER in silence."""
    monkeypatch.setattr(command, "_query", lambda *a, **k: {"results": {"bindings": []}})
    out = tmp_path / "labels.csv"
    out.write_text("label,iso2,language,kind,source,fetched_on\nIndia,IN,en,label,s,d\n")
    before = out.read_bytes()
    with pytest.raises(CommandError, match="0 labels"):
        call_command("refresh_country_labels", "--out", str(out))
    assert out.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["labels.csv"]


# --- Task 11: verify_due_cycles ------------------------------------------------


@pytest.mark.django_db
def test_verify_due_cycles_refuses_to_start_without_the_second_model_family(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CommandError, match="ANTHROPIC_API_KEY"):
        call_command("verify_due_cycles")


@pytest.mark.django_db
def test_dry_run_lists_due_rows_oldest_first_and_spends_nothing(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    opportunity = FundingOpportunity.objects.create(
        canonical_key="read:a", name="A", family="PRIVATE_FOUNDATION", scope_type="GLOBAL",
        agreement="AGREED")
    now = timezone.now()
    FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2028,
                                            next_check_at=now - dt.timedelta(days=1))
    FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027,
                                            next_check_at=now - dt.timedelta(days=2))
    call_command("verify_due_cycles", "--dry-run")
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("due 2") and "2027" in out[1] and "2028" in out[2]
    # A dry run creates no tracked rows and verifies nothing.
    assert FundingCycleVerification.objects.count() == 2
    assert not FundingCycleVerification.objects.exclude(verified_at=None).exists()


@pytest.mark.django_db
def test_a_rejected_or_unagreed_award_is_never_verified(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    for key, agreement, review in (("b", "UNAGREED", ""), ("c", "AGREED", "REJECTED")):
        opportunity = FundingOpportunity.objects.create(
            canonical_key=f"read:{key}", name=key, family="PRIVATE_FOUNDATION",
            scope_type="GLOBAL", agreement=agreement, review=review)
        FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027,
                                                next_check_at=timezone.now())
    call_command("verify_due_cycles", "--dry-run")
    assert capsys.readouterr().out.startswith("due 0")


# --- Task 13: cycle_verify, the 9.3 gate -------------------------------------


def _row(expected, got, **kw):
    return GateRow(domain=kw.get("domain", "a.example"), expected=expected, got=got,
                   expected_deadline=kw.get("expected_deadline", ""),
                   got_deadline=kw.get("got_deadline", ""),
                   contradicted=kw.get("contradicted", False),
                   projected_open=kw.get("projected_open"), actual_open=kw.get("actual_open"),
                   step=kw.get("step", "0"), cost_usd=kw.get("cost_usd", 0.1),
                   country=kw.get("country", "DE"), condition=kw.get("condition", ""))


def test_precision_on_open_and_upcoming_is_what_the_gate_reads():
    report = score([_row("OPEN", "OPEN"), _row("UNVERIFIED", "OPEN"), _row("UPCOMING", "UPCOMING")])
    assert report.precision["OPEN"] == 0.5 and report.precision["UPCOMING"] == 1.0
    assert report.passed is False  # OPEN below 95%


def test_a_single_contradicted_open_row_fails_the_gate_whatever_the_precision():
    rows = [_row("OPEN", "OPEN")] * 40 + [_row("OPEN", "OPEN", contradicted=True)]
    assert score(rows).passed is False


def test_the_gate_passes_only_on_both_states_and_no_contradiction():
    """Pins that the contradiction test above is not vacuous: the same rows
    without the contradicted one pass."""
    rows = [_row("OPEN", "OPEN")] * 40 + [_row("UPCOMING", "UPCOMING")] * 20
    assert score(rows).passed is True
    assert score([*rows, _row("OPEN", "OPEN", contradicted=True)]).passed is False
    # A state the engine never called has no precision, and nothing unmeasured passes.
    assert score([_row("OPEN", "OPEN")] * 40).passed is False


def test_the_projection_backtest_counts_calls_within_45_days():
    rows = [
        _row("UPCOMING", "UPCOMING", projected_open=dt.date(2026, 3, 1),
             actual_open=dt.date(2026, 3, 20)),
        _row("UPCOMING", "UPCOMING", projected_open=dt.date(2026, 3, 1),
             actual_open=dt.date(2026, 6, 1)),
    ]
    assert score(rows).projection_hit_rate == 0.5


def test_cost_per_verified_scholarship_divides_by_open_and_upcoming_only():
    report = score([_row("OPEN", "OPEN", cost_usd=0.3), _row("UNVERIFIED", "UNVERIFIED",
                                                            cost_usd=0.1)])
    assert report.cost_per_verified == 0.4


def test_recall_and_deadline_accuracy_are_reported_per_country_and_per_condition_kind():
    rows = [
        _row("OPEN", "OPEN", country="AZ"),
        _row("UPCOMING", "UNVERIFIED", country="AZ"),
        _row("OPEN", "OPEN", condition="NATIONALITY:IN", expected_deadline="2026-11-30",
             got_deadline="2026-11-30"),
        _row("OPEN", "OPEN", condition="APPLICANT_CLASS:NON_EU", expected_deadline="2026-11-01",
             got_deadline="2027-01-15"),
    ]
    report = score(rows)
    assert report.recall_by_country["AZ"] == 0.5 and report.recall_by_country["DE"] == 1.0
    assert report.deadline_accuracy_by_kind == {"NATIONALITY": 1.0, "APPLICANT_CLASS": 0.0}
    assert report.steps == {"0": 4}


_HEADER = ("organisation_domain,country,award_name,award_kind,award_scope,own_url,intake,"
           "nationality,country_of_residence,expected_state,expected_deadline,deadline_condition,"
           "evidence_url,sentence,last_call_opened,prior_call_opened,labelled_on,labelled_by\n")


@pytest.mark.django_db
def test_dry_run_lists_the_rows_estimates_the_credit_ceiling_and_spends_nothing(
    tmp_path, monkeypatch, capsys, settings
):
    from apps.research import cycle_verification
    from apps.research.fetch.site import crawl_ceiling

    monkeypatch.setattr(cycle_verification, "build_seams",
                        lambda *a, **k: pytest.fail("a dry run built the vendor seams"))
    settings.CYCLE_CRAWL_LIMIT = 15
    truth = tmp_path / "truth.csv"
    # Test data: fake organisations on the reserved .example TLD, one award
    # labelled for two profiles -- one (own_url, intake), so one ladder run.
    truth.write_text(
        _HEADER
        + "fund.example,DE,Fake Fellowship,I0_HOLDER_AWARD,HOLDER_OWN,https://fund.example/f,"
          "2027,IN,IN,OPEN,2026-11-30,NATIONALITY:IN,https://fund.example/f,s,,,2026-09-26,test\n"
        + "fund.example,DE,Fake Fellowship,I0_HOLDER_AWARD,HOLDER_OWN,https://fund.example/f,"
          "2027,DE,DE,OPEN,2027-01-15,ALL,https://fund.example/f,s,,,2026-09-26,test\n",
        encoding="utf-8",
    )
    call_command("cycle_verify", "--truth", str(truth), "--dry-run")
    out = capsys.readouterr().out
    assert "2 rows, 1 ladder run" in out
    assert f"at most {1 + crawl_ceiling(15)} Firecrawl credits" in out


@pytest.mark.django_db
def test_an_unlabelled_truth_set_is_refused_for_a_real_run(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    truth = tmp_path / "truth.csv"
    truth.write_text(_HEADER, encoding="utf-8")
    with pytest.raises(CommandError, match="unlabelled"):
        call_command("cycle_verify", "--truth", str(truth))


@pytest.mark.django_db
def test_a_truth_file_with_the_wrong_columns_is_refused(tmp_path):
    truth = tmp_path / "truth.csv"
    truth.write_text("organisation_domain,expected_state\nfund.example,OPEN\n", encoding="utf-8")
    with pytest.raises(CommandError, match="columns"):
        call_command("cycle_verify", "--truth", str(truth), "--dry-run")


def test_the_committed_truth_set_carries_exactly_the_planned_header():
    from pathlib import Path

    path = Path(settings.BASE_DIR) / "docs" / "research" / "2026-09-cycle-truth-set.csv"
    assert path.read_text(encoding="utf-8").splitlines()[0] + "\n" == _HEADER


@pytest.mark.django_db
def test_a_real_run_scores_through_the_seams_writes_no_catalog_row_and_flags_a_contradiction(
    tmp_path, monkeypatch, capsys
):
    from dataclasses import replace
    from types import SimpleNamespace

    import anthropic
    import openai

    from apps.funding.models import FundingCycleVerification, FundingOpportunity
    from apps.research import cycle_verification
    from apps.research.fetch.site import CrawlResult
    from apps.research.fetch.types import FetchedPage, Outcome
    from apps.research.funding_judge import FundingDecision
    from apps.research.management.commands import cycle_verify
    from apps.research.providers.base import SiteSearchResult

    quote = "The Fake Fellowship 2027 call is open; apply by 15 January 2027."
    decision = FundingDecision(
        kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", offered="YES",
        internationals_included="YES", nationality_shape="ANY", route="STUDENT_APPLIES",
        money_form="GRANT", holder="PRIVATE_FOUNDATION", tuition="FULL", living="FULL",
        extras=(), obligation=(), agreement="AGREED", quotes=(quote,), name="Fake Fellowship",
        disputed=(), heading="Fake Fellowship",
    )
    decision = replace(decision, applies_to="2027", deadlines=(("2027-01-15", "ALL"),))
    page = FetchedPage(final_url="https://fund.example/f", redirects=(), content_type="text/html",
                       body=b"<main>Fake Fellowship</main>", markdown="Fake Fellowship",
                       outcome=Outcome.FETCHED, fetched_via="FIRECRAWL", cost_credits=1)

    class _Store:
        def put(self, key, body):
            return "v1"

    seams = cycle_verification.Seams(
        fetch=lambda url, **kw: page,
        crawl=lambda url, **kw: CrawlResult(job_id="j", urls=(), dead=(), errors=(),
                                            robots_blocked=(), credits=0, status="completed"),
        capture_near=lambda url, *, at: page,
        read=lambda fetched: (decision,),
        site_search=lambda **kw: SiteSearchResult(urls=(), cost_usd=0.0, provider="exa"),
        fallback_search=lambda **kw: SiteSearchResult(urls=(), cost_usd=0.0, provider="brave"),
        store=_Store(),
    )
    monkeypatch.setattr(cycle_verification, "build_seams", lambda *a, **k: seams)
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: SimpleNamespace(responses=None))
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: SimpleNamespace(messages=None))
    monkeypatch.setattr(cycle_verify, "timezone",
                        SimpleNamespace(now=lambda: dt.datetime(2026, 9, 26, tzinfo=dt.UTC)))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    truth = tmp_path / "truth.csv"
    truth.write_text(
        _HEADER
        + "fund.example,DE,Fake Fellowship,I0_HOLDER_AWARD,HOLDER_OWN,https://fund.example/f,"
          "2027,DE,DE,OPEN,2027-01-15,ALL,https://fund.example/f,x,,,2026-09-26,test\n"
        # A deliberately wrong label whose sentence IS the engine's evidence: contradicted.
        + "fund.example,DE,Fake Fellowship,I0_HOLDER_AWARD,HOLDER_OWN,https://fund.example/f,"
          f"2027,AZ,AZ,SUSPENDED,,ALL,https://fund.example/f,\"{quote}\",,,2026-09-26,test\n",
        encoding="utf-8",
    )
    out_md = tmp_path / "gate.md"
    call_command("cycle_verify", "--truth", str(truth), "--out", str(out_md))
    out = capsys.readouterr().out
    assert "| OPEN | 0.5 |" in out and "- contradicted: 1" in out and "CONTRADICTED" in out
    assert "FAIL" in out_md.read_text(encoding="utf-8")
    assert not FundingOpportunity.objects.exists()
    assert not FundingCycleVerification.objects.exists()


# --- Final-review fixes ---------------------------------------------------------


@pytest.mark.django_db
def test_one_failing_award_is_recorded_and_backed_off_and_the_run_goes_on(
    monkeypatch, capsys, settings
):
    """A raising row must not crash the run and starve every row behind it."""
    from types import SimpleNamespace

    from apps.funding.cycle_schedule import tracked_intakes
    from apps.research.management.commands import verify_due_cycles

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(verify_due_cycles, "OpenAI",
                        lambda *a, **k: SimpleNamespace(responses=None))
    monkeypatch.setattr(verify_due_cycles.anthropic, "Anthropic",
                        lambda *a, **k: SimpleNamespace(messages=None))
    settings.CYCLE_VERIFY_RUN_BUDGET_USD = 0.001  # one Firecrawl credit is $0.00083
    settings.CYCLE_ERROR_BACKOFF_DAYS = 3
    year = tracked_intakes(timezone.now().date())[0]
    rows = {}
    for n, name in enumerate(("broken", "fine", "starved")):
        opportunity = FundingOpportunity.objects.create(
            canonical_key=f"read:{name}", name=name, family="PRIVATE_FOUNDATION",
            scope_type="GLOBAL", agreement="AGREED")
        rows[name] = FundingCycleVerification.objects.create(
            opportunity=opportunity, intake_start_year=year,
            next_check_at=timezone.now() - dt.timedelta(days=10 - n))
    real = verify_due_cycles.seams_factory

    def factory(meter, parser, claude, *, source_id):
        meter.run.spend("FIRECRAWL", 1)
        if source_id == str(rows["broken"].opportunity_id):
            raise RuntimeError("vendor exploded")
        return real(meter, parser, claude, source_id=source_id, store=object())

    monkeypatch.setattr(verify_due_cycles, "seams_factory", factory)
    call_command("verify_due_cycles", "--max", "3")
    out = capsys.readouterr().out
    for row in rows.values():
        row.refresh_from_db()
    broken, fine, starved = rows["broken"], rows["fine"], rows["starved"]
    assert broken.trail[-1] == {"step": "run", "url": "", "outcome": "ERROR",
                                "note": "RuntimeError: vendor exploded"}
    assert broken.cost_usd > 0 and broken.cost_complete is False
    assert broken.verified_at is None
    backoff = broken.next_check_at - timezone.now()
    assert dt.timedelta(days=2, hours=23) < backoff <= dt.timedelta(days=3)
    assert fine.verified_at is not None
    assert starved.verified_at is None  # the run budget stopped the run before it
    assert "run budget" in out and "ERROR" in out


def test_a_conditional_rows_second_profile_is_not_a_second_verified_scholarship():
    """Two profiles of one (own_url, intake) are one ladder run and one award."""
    from dataclasses import replace

    report = score([
        replace(_row("OPEN", "OPEN", cost_usd=0.3), run="https://a.example/f@2027"),
        replace(_row("OPEN", "OPEN", cost_usd=0.0), run="https://a.example/f@2027"),
        replace(_row("UPCOMING", "UPCOMING", cost_usd=0.1), run="https://b.example/g@2027"),
    ])
    assert report.cost_per_verified == 0.2


def test_the_gate_counts_rows_whose_only_evidence_sat_behind_a_withheld_hop():
    from dataclasses import replace

    report = score([
        replace(_row("OPEN", "UNVERIFIED"), hop_withheld=2, withheld_only=True),
        replace(_row("OPEN", "OPEN"), hop_withheld=1),
    ])
    assert report.hop_withheld == 3 and report.withheld_only == 1
    from apps.research.management.commands.cycle_verify import render

    assert "- truth rows with no evidence but a withheld hop: 1" in render(report)
