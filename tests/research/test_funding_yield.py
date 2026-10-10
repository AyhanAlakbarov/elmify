"""The yield harness: the tally's serve rule is the writer's, and a dry run costs nothing."""

from io import StringIO

from django.core.management import call_command

from apps.research.egress import FetchResult, SourceBlocked
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.funding_judge import FundingDecision, FundingReadResult, PointerLead
from apps.research.management.commands import funding_yield


def _decision(**over):
    base = dict(
        kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", offered="YES",
        internationals_included="YES", nationality_shape="OPEN", route="UNSTATED",
        money_form="GRANT", holder="PRIVATE_FOUNDATION", tuition="UNSTATED", living="UNSTATED",
        extras=(), obligation=(), agreement="AGREED", quotes=("q",), name="n", disputed=(),
    )
    base.update(over)
    return FundingDecision(**base)  # type: ignore[arg-type]


def test_dry_run_lists_hosts_and_makes_no_call(tmp_path):
    hosts = tmp_path / "hosts.txt"
    hosts.write_text("# a comment\ncusanuswerk.de\tB\tDE\nsbb-stipendien.de\tA\tDE\n")
    out = StringIO()
    call_command("funding_yield", hosts=str(hosts), dry_run=True, stdout=out)
    text = out.getvalue()
    assert "cusanuswerk.de" in text and "would read 2 hosts" in text


def test_the_served_rule_in_the_tally_is_the_writers():
    assert funding_yield.served_by_gate(_decision()) is True
    # No money form and no benefit: agreed, and still not served.
    assert funding_yield.served_by_gate(_decision(money_form="UNSTATED")) is False
    assert funding_yield.served_by_gate(_decision(agreement="UNAGREED")) is False
    assert funding_yield.served_by_gate(_decision(offered="NO")) is False


def test_a_tally_separates_served_from_agreed_but_unserved_and_keeps_the_recall_counters():
    tally = funding_yield.Tally()
    tally.record(
        FundingReadResult(
            (_decision(), _decision(money_form="UNSTATED", name="vague"),
             _decision(agreement="UNAGREED", disputed=("offered",), name="split")),
            2, 1, 3, (PointerLead("q", "DAAD", "NATIONAL_GOVERNMENT"),),
        )
    )
    assert (tally.served, tally.agreed_unserved, tally.unagreed) == (1, 1, 1)
    assert (tally.pointers, tally.negations, tally.noise) == (2, 1, 3)
    assert tally.disputed_offered == 1 and tally.pointer_names == ["DAAD"]


def test_a_host_whose_every_scheme_is_refused_is_counted_refused_not_empty(monkeypatch, tmp_path):
    def refuse(url, **_kwargs):
        raise SourceBlocked("source returned HTTP 403")

    command = funding_yield.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    tally = command._read_host(
        "blocked.example.de", pages=4, parser=object(), claude=object(), fetch=refuse
    )
    assert tally.refused == 1 and tally.pages == 0


def test_a_shell_page_is_unreadable_never_a_page_that_states_no_funding():
    command = funding_yield.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    tally = funding_yield.Tally()
    shell = FetchResult(
        "https://shell.example.de/", (), "text/html",
        b"<html><head>" + b"<style>a{color:red}</style>" * 2_000 + b"</head><body></body></html>",
    )
    command._read_page(shell, tally=tally, parser=object(), claude=object())
    assert tally.unreadable == 1 and tally.pages == 0


def test_a_page_is_read_once_per_host_and_its_funding_links_followed(monkeypatch):
    home = FetchResult(
        "https://foundation-example.de/", (), "text/html",
        b'<html><body><a href="/stipendien">Stipendien</a>'
        b"<p>Scholarships are described elsewhere on this site.</p></body></html>",
    )
    inner = FetchResult(
        "https://foundation-example.de/stipendien", (), "text/html",
        b"<html><body><p>Das Stipendium betraegt 992 Euro monatlich.</p></body></html>",
    )
    fetched: list[str] = []

    def fetch(url, **_kwargs):
        fetched.append(url)
        return inner if "stipendien" in url else home

    monkeypatch.setattr(
        funding_yield, "read_funding",
        lambda *a, **k: FundingReadResult((_decision(),), 0, 0, 0, ()),
    )
    command = funding_yield.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    tally = command._read_host(
        "foundation-example.de", pages=4, parser=object(), claude=object(), fetch=fetch
    )
    assert fetched[0] == "https://foundation-example.de/"
    assert any("stipendien" in url for url in fetched[1:])
    assert tally.pages == 2 and tally.served == 2


def test_a_page_read_from_a_capture_is_tallied_apart_from_a_live_one():
    """FIX 1: `retrieve_official_source` returns ARCHIVED as SERVED under the
    ORIGINAL url, so a capture up to a year old counts into this measurement
    as a live read of the funder's current page. The command writes no row, so
    the tally line is its only output and the only place this can show."""
    command = funding_yield.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    tally = funding_yield.Tally()
    body = (
        b"<html><body><main><p>"
        + b"The chair works on legged locomotion. " * 60
        + b"</p></main></body></html>"
    )
    archived = FetchedPage(
        final_url="https://foundation-example.de/", redirects=(), content_type="text/html",
        body=body, fetched_via="ARCHIVE", outcome=Outcome.ARCHIVED, rung=6,
        captured_at="2026-06-25",
    )
    command._read_page(archived, tally=tally, parser=object(), claude=object())
    assert tally.archived == 1
    assert "archived=1" in tally.line()

    live = FetchResult("https://foundation-example.de/", (), "text/html", body)
    command._read_page(live, tally=tally, parser=object(), claude=object())
    assert tally.archived == 1  # a live page never counts here


from decimal import Decimal  # noqa: E402

from apps.research.funding_judge import DecidedAmount  # noqa: E402
from apps.research.management.commands.funding_yield import Tally  # noqa: E402


def _served(**card):
    fields = dict(
        kind="I2_PROGRAMME_ATTACHED", scope="PROGRAM", offered="YES", internationals_included="YES",
        nationality_shape="OPEN", route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT",
        holder="INSTITUTION", tuition="UNSTATED", living="FULL", extras=(), obligation=(),
        agreement="AGREED", quotes=("Scholars receive €1,200 per month.",), name="Stipend",
        disputed=(),
    )
    fields.update(card)
    return FundingDecision(**fields)  # type: ignore[arg-type]


def test_the_tally_counts_each_served_cards_fields_and_the_invented_copies():
    amount = DecidedAmount("LIVING", "€1,200", Decimal("1200"), "EUR", "MONTHLY", "EXACT",
                           "Scholars receive €1,200 per month.")
    tally = Tally()
    tally.record(
        FundingReadResult(decisions=(_served(amounts=(amount,), card_off_line=2),)),
        page_url="https://example.test/funding",
    )
    assert tally.cards["amount=FILLED"] == 1
    assert tally.cards["duration=UNSTATED"] == 1
    assert tally.cards["contact=NOT_READ"] == 1
    assert tally.card_off_line == 2
    assert "cards=" in tally.line() and "off-line=2" in tally.line()
    assert {row["field"] for row in tally.card_rows} >= {"amount", "duration"}


import pytest  # noqa: E402

from apps.research.harvest import content_digest  # noqa: E402
from apps.research.model_cost import Usage  # noqa: E402

_FUNDED = (
    b"<html><body><p>Das Stipendium betraegt 992 Euro monatlich.</p></body></html>"
)


def test_a_page_read_writes_one_cost_row_keyed_by_its_content_digest(monkeypatch):
    def read(*_a, meter, **_k):
        meter.record(Usage("claude", "claude-sonnet-5", "default", 1_000, 0, 0, 100))
        return FundingReadResult((_decision(),), 0, 0, 2, ())

    monkeypatch.setattr(funding_yield, "read_funding", read)
    command = funding_yield.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    page = FetchResult("https://foundation-example.de/stipendien", (), "text/html", _FUNDED)
    tally, rows = funding_yield.Tally(), []
    command._read_page(
        page, tally=tally, parser=object(), claude=object(), host="foundation-example.de",
        cost_rows=rows,
    )
    (row,) = rows
    assert row["content_sha256"] == content_digest(page.body)
    assert (row["served"], row["noise"], row["claude_input"]) == ("1", "2", "1000")
    assert float(row["usd"]) == pytest.approx(0.003)  # 1,000 x $2 + 100 x $10, per million
    assert tally.meter.usages  # the host's total carries it too


def test_saved_pages_are_read_back_and_a_loaded_run_never_fetches(tmp_path):
    page = FetchResult("https://foundation-example.de/", (), "text/html", _FUNDED)
    funding_yield.save_page(tmp_path, "foundation-example.de", page)
    loaded = funding_yield.load_pages(tmp_path)
    (back,) = loaded["foundation-example.de"]
    assert (back.final_url, back.body, back.content_type) == (
        page.final_url, page.body, page.content_type,
    )

    def never(*_a, **_k):
        raise AssertionError("a loaded run must not fetch")

    command = funding_yield.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    tally = funding_yield.Tally()
    assert command._host_pages(
        "foundation-example.de", pages=4, fetch=never, tally=tally, loaded=loaded
    ) == [back]
    assert command._host_pages(
        "unsaved.example.de", pages=4, fetch=never, tally=tally, loaded=loaded
    ) == []
    assert tally.refused == 1


def test_the_cost_csv_round_trips(tmp_path):
    from apps.research.cost_compare import COST_COLUMNS, read_cost_csv, write_cost_csv

    row = dict.fromkeys(COST_COLUMNS, "0") | {"final_url": "https://x.test/", "tier": "standard"}
    path = tmp_path / "cost.csv"
    write_cost_csv(path, [row])
    assert read_cost_csv(path) == [row]


def test_a_file_that_is_not_a_cost_csv_is_refused(tmp_path):
    from apps.research.cost_compare import read_cost_csv

    path = tmp_path / "other.csv"
    path.write_text("host,served\nx,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a funding cost CSV"):
        read_cost_csv(path)


from apps.research.model_cost import ReadingTier  # noqa: E402


def test_a_batch_run_reads_every_page_at_once_and_counts_the_unfinished(monkeypatch, tmp_path):
    for url in ("https://foundation-example.de/", "https://foundation-example.de/stipendien"):
        funding_yield.save_page(
            tmp_path, "foundation-example.de", FetchResult(url, (), "text/html", _FUNDED)
        )
    seen = []

    def batched(_clients, pages, **_kwargs):
        seen.append(len(pages))
        return [FundingReadResult((_decision(),), 0, 0, 0, ()), None]

    monkeypatch.setattr(funding_yield, "read_funding_batched", batched)
    command = funding_yield.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    rows = []
    totals = command._run(
        [("foundation-example.de", "B")], pages=4, parser=object(), claude=object(),
        fetch=None, tier=ReadingTier.BATCH, batch=object(),
        loaded=funding_yield.load_pages(tmp_path), cost_rows=rows,
    )
    assert seen == [2]  # one batch for the whole run, not one per page
    assert (totals.served, totals.batch_missing, len(rows)) == (1, 1, 1)
    # Card rows go through the same _record as a synchronous run, so --cards-csv
    # (written from these totals) is not empty in batch mode.
    assert {row["page_url"] for row in totals.card_rows} == {"https://foundation-example.de/"}


def test_a_batch_run_without_batch_clients_is_refused():
    from django.core.management.base import CommandError

    command = funding_yield.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    with pytest.raises(CommandError, match="batch clients"):
        command._run(
            [("foundation-example.de", "B")], pages=1, parser=object(), claude=object(),
            fetch=None, tier=ReadingTier.BATCH, loaded={},
        )


def test_a_save_directory_that_already_holds_pages_is_refused(tmp_path, monkeypatch):
    """A second --save-pages run into the same directory would add its pages
    to the first run's, so every page would load twice."""
    from django.core.management.base import CommandError

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    hosts = tmp_path / "hosts.txt"
    hosts.write_text("foundation-example.de\n", encoding="utf-8")
    saved = tmp_path / "pages"
    saved.mkdir()
    funding_yield.save_page(
        saved, "foundation-example.de",
        FetchResult("https://foundation-example.de/", (), "text/html", b"<p>x</p>"),
    )
    with pytest.raises(CommandError, match="already holds saved pages"):
        call_command("funding_yield", hosts=str(hosts), save_pages=str(saved), stdout=StringIO())
