"""The first-read gate: one claim per award, human labels, and §8.9's three outcomes."""

import csv
import json
import socket
from io import StringIO
from ipaddress import ip_address

import pytest
from django.core.management import call_command

from apps.research.egress import UnsafeTarget
from apps.research.fetch import firecrawl
from apps.research.fetch.types import FetchedPage, Outcome, VendorUnavailable
from apps.research.first_read import FirstReadVerdict, json_format
from apps.research.funding_judge import FundingDecision, FundingReadResult
from apps.research.management.commands import first_read_gate
from apps.research.model_cost import Usage
from apps.research.models import FetchAttempt

QUOTE = "The DAAD awards 934 EUR monthly to every admitted student."


def _decision(**over):
    base = dict(
        kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", offered="YES",
        internationals_included="YES", nationality_shape="OPEN", route="UNSTATED",
        money_form="GRANT", holder="NATIONAL_GOVERNMENT", tuition="UNSTATED", living="FULL",
        extras=(), obligation=(), agreement="AGREED", quotes=(QUOTE,), name="DAAD", disputed=(),
    )
    base.update(over)
    return FundingDecision(**base)  # type: ignore[arg-type]


def _first(quote=QUOTE, **over):
    fields = dict(
        quote=quote, offered="YES", holder="NATIONAL_GOVERNMENT", scope="HOLDER_OWN", name="DAAD"
    )
    fields.update(over)
    return FirstReadVerdict(**fields)


def test_a_served_award_and_its_matching_sentence_are_one_claim():
    rows = first_read_gate.claim_rows(
        "daad.example", "https://daad.example/x", [_decision()],
        (_first(), _first("Applications close on 15 November for every admitted student.")),
    )
    assert [(row["judge_claims"], row["first_claims"]) for row in rows] == [("y", "y"), ("n", "y")]
    assert rows[0]["judge_correct"] == rows[0]["first_correct"] == ""


def test_an_unserved_decision_and_a_no_sentence_claim_nothing():
    rows = first_read_gate.claim_rows(
        "daad.example", "https://daad.example/x", [_decision(agreement="UNAGREED")],
        (_first(offered="NO"),),
    )
    assert rows == []


def _labelled(n, *, judge_right, first_on, first_right):
    rows = []
    for i in range(n):
        claims = i < first_on
        rows.append(dict.fromkeys(first_read_gate.GATE_COLUMNS, "") | {
            "page_url": f"https://h.test/{i}",
            "judge_claims": "y",
            "first_claims": "y" if claims else "n",
            "judge_correct": "y" if i < judge_right else "n",
            "first_correct": ("y" if i < first_right else "n") if claims else "",
        })
    return rows


def test_a_first_read_at_least_as_precise_as_the_judge_is_outcome_a():
    score = first_read_gate.score_rows(_labelled(40, judge_right=36, first_on=40, first_right=38))
    assert score.outcome().startswith("(a)")


def test_a_less_precise_first_read_that_flags_every_judged_page_is_triage():
    score = first_read_gate.score_rows(_labelled(40, judge_right=38, first_on=40, first_right=30))
    assert score.outcome().startswith("(b)")


def test_otherwise_the_judge_stays_alone():
    score = first_read_gate.score_rows(_labelled(40, judge_right=38, first_on=30, first_right=20))
    assert score.outcome().startswith("(c)")


def test_fewer_than_thirty_labels_decides_nothing():
    score = first_read_gate.score_rows(_labelled(20, judge_right=20, first_on=20, first_right=20))
    assert score.outcome().startswith("undecided")


def test_an_unlabelled_claim_is_refused():
    rows = _labelled(40, judge_right=36, first_on=40, first_right=38)
    rows[5]["judge_correct"] = ""
    with pytest.raises(ValueError, match="row 7"):
        first_read_gate.score_rows(rows)


def test_score_reads_a_labelled_sheet(tmp_path):
    path = tmp_path / "labelled.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=first_read_gate.GATE_COLUMNS)
        writer.writeheader()
        writer.writerows(_labelled(40, judge_right=36, first_on=40, first_right=38))
    out = StringIO()
    call_command("first_read_gate", score=str(path), stdout=out)
    assert "outcome: (a)" in out.getvalue()


def _home():
    return FetchedPage(
        final_url="https://daad.example/", redirects=(), content_type="text/html",
        body=f"<html><body><h2>Scholarships</h2><p>{QUOTE}</p></body></html>".encode(),
        markdown=f"## Scholarships\n\n{QUOTE}\n", fetched_via="FIRECRAWL",
        json_extract={"verdicts": [_first().model_dump()]},
    )


def _reader(monkeypatch):
    def read(*_a, meter, **_k):
        meter.record(Usage("claude", "claude-sonnet-5", "default", 1_000, 0, 0, 100))
        return FundingReadResult((_decision(),), 0, 0, 0, ())

    monkeypatch.setattr(first_read_gate, "read_funding", read)


def _command():
    command = first_read_gate.Command()
    command.stdout, command.stderr = StringIO(), StringIO()
    return command


def test_the_gate_reads_each_page_once_with_both_readers(monkeypatch):
    home = _home()
    fetched = []

    def fetch(url):
        fetched.append(url)
        return home

    _reader(monkeypatch)
    command = _command()
    rows = command._run(
        [("daad.example", "P")], pages=1, parser=object(), claude=object(), fetch=fetch,
        spend=first_read_gate.JsonSpend(),
    )
    assert fetched == ["https://daad.example/"]
    assert [(row["judge_claims"], row["first_claims"]) for row in rows] == [("y", "y")]
    assert "1 answers" in command.stdout.getvalue()


@pytest.mark.parametrize(
    "error", [UnsafeTarget("bad host"), VendorUnavailable("down", escalate=False)]
)
def test_one_host_that_raises_is_logged_and_the_rest_are_still_read(monkeypatch, error):
    home = _home()

    def fetch(url):
        if url == "https://broken.example/":
            raise error
        return home

    _reader(monkeypatch)
    command = _command()
    rows = command._run(
        [("broken.example", "P"), ("daad.example", "P")], pages=1,
        parser=object(), claude=object(), fetch=fetch, spend=first_read_gate.JsonSpend(),
    )
    assert [(row["host"], row["judge_claims"]) for row in rows] == [("daad.example", "y")]
    assert "broken.example" in command.stderr.getvalue()
    assert "pages read by both: 1" in command.stdout.getvalue()


def test_the_gate_asks_firecrawl_for_the_first_read_on_every_scrape():
    providers = first_read_gate.gate_providers()
    assert providers["firecrawl"].func is firecrawl.scrape
    assert providers["firecrawl"].keywords == {"json_format": json_format()}


@pytest.fixture
def _resolve_test_hosts(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            ip_address(host)
            address = host
        except ValueError:
            address = "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _never(*_args, **_kwargs):  # pragma: no cover - the assertion is the point
    raise AssertionError("scrape.do and the archive are never called by the gate")


@pytest.mark.django_db
def test_a_page_only_scrape_do_could_fetch_is_skipped_and_never_billed(_resolve_test_hosts):
    """Firecrawl's 403 escalates; the gate's zero scrape.do cap must refuse the
    25-credit rung BEFORE a request, not after one is paid for."""

    def blocked(url, *, json_body, headers, timeout):
        return 200, json.dumps({"success": True, "data": {
            "markdown": "", "html": "",
            "metadata": {"url": "https://walled.test/", "statusCode": 403,
                         "contentType": "text/html"},
        }}).encode(), {}

    def call(url, *, api_key, **kwargs):
        return first_read_gate.gate_providers()["firecrawl"](
            url, api_key="k", post=blocked, sleep=lambda _s: None, **kwargs
        )

    fetch, budget, _spend = first_read_gate.gate_fetch(
        600, providers={"firecrawl": call, "scrapedo": _never, "archive": _never}
    )
    page = fetch("https://walled.test/")
    assert page.outcome is Outcome.BUDGET and not page.ok
    assert budget.spent == {"FIRECRAWL": 1, "SCRAPE_DO": 0}
    # The cap must hold past the run: a BUDGET row carrying `retry_after` is one
    # `retry_due_fetches` would re-fetch under the production budget, scrape.do
    # included.
    assert FetchAttempt.objects.filter(sweep_id=budget.sweep_id, outcome="BUDGET").exists()
    assert not FetchAttempt.objects.filter(
        outcome="BUDGET", retry_after__isnull=False
    ).exists()


def test_one_sentence_matching_two_served_awards_is_claimed_once():
    rows = first_read_gate.claim_rows(
        "daad.example", "https://daad.example/x",
        [_decision(), _decision(name="DAAD II", quotes=("The DAAD awards 934 EUR monthly",))],
        (_first(),),
    )
    assert [(row["judge_claims"], row["first_claims"]) for row in rows] == [
        ("y", "y"), ("y", "n")
    ]


def test_claim_cells_are_read_stripped_and_lower_cased_like_labels():
    rows = _labelled(40, judge_right=36, first_on=40, first_right=38)
    rows[0]["judge_claims"] = " Y "
    rows[1]["first_claims"] = "Y"
    score = first_read_gate.score_rows(rows)
    assert (score.judge_labelled, score.first_labelled) == (40, 40)
    assert (score.judge_correct, score.first_correct) == (36, 38)


@pytest.mark.django_db
def test_the_first_read_cost_counts_json_credits_on_pages_no_one_compared(_resolve_test_hosts):
    """A shell carries the json surcharge on rung 1 AND on the rung 2 it
    escalates to, and is never read by both readers -- counting answers alone
    reports it as free."""
    shell = json.dumps({"success": True, "data": {
        "markdown": "Loading", "html": "<html>" + " " * 30_000 + "</html>",
        "json": {"verdicts": []},
        "metadata": {"url": "https://shell.test/", "statusCode": 200,
                     "contentType": "text/html"},
    }}).encode()

    def call(url, *, api_key, **kwargs):
        return first_read_gate.gate_providers()["firecrawl"](
            url, api_key="k", post=lambda *_a, **_k: (200, shell, {}), sleep=lambda _s: None,
            **kwargs,
        )

    fetch, budget, spend = first_read_gate.gate_fetch(
        600, providers={"firecrawl": call, "scrapedo": _never, "archive": _never}
    )
    command = _command()
    rows = command._run(
        [("shell.test", "P")], pages=1, parser=object(), claude=object(), fetch=fetch,
        spend=spend,
    )
    assert rows == []
    assert spend.credits == 2 * firecrawl.JSON_FORMAT_CREDITS
    assert budget.spent["FIRECRAWL"] == 2 * (1 + firecrawl.JSON_FORMAT_CREDITS)
    out = command.stdout.getvalue()
    assert "0 answers" in out and f"{2 * firecrawl.JSON_FORMAT_CREDITS} json credits" in out
    assert f"${spend.usd:.4f}" in out and spend.usd > 0
