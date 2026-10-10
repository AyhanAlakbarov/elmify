import json

import pytest

from apps.research.fetch.monitor import (
    MAX_TARGETS,
    MONITOR_CRON,
    MonitorBudgetExceeded,
    MonitorEstimateMissing,
    build_targets,
    create_monitor,
    list_checks,
)


def _post(payload, *, sink=None):
    def post(url, body, headers):
        if sink is not None:
            sink.append((url, json.loads(body)))
        return 200, json.dumps(payload).encode(), {}

    return post


def _delete(*, sink=None, status=200):
    def delete(url, headers):
        if sink is not None:
            sink.append(url)
        return status, b"{}", {}

    return delete


def test_the_judge_is_off_on_every_monitor():
    """2026-09-23. Re-reading a changed page costs about a tenth of a cent;
    the vendor judge that would decide whether to re-read costs 1 credit.
    Paying more to decide than to do is the whole argument, and it is the
    same one that removed typed-decisions D7."""
    sink = []
    create_monitor(
        api_key="k", name="2027:uni.example.org",
        targets=[{"type": "scrape", "url": "https://uni.example.org/apply/"}],
        post=_post({"success": True, "id": "m1", "estimatedCreditsPerMonth": 30}, sink=sink),
    )

    body = sink[0][1]
    assert body["judgeEnabled"] is False
    assert "goal" not in body
    assert body["cron"] == MONITOR_CRON == "0 6 1 * *"
    assert body["retentionDays"] == 365


def test_a_monitor_is_not_created_when_the_cycle_cannot_pay_for_it(settings):
    """The create call returns estimatedCreditsPerMonth and that is the only
    honest figure available before the first check. A monitor that cannot pay
    reports skipped_no_credits forever, which from outside is a site that
    never changes -- the silent staleness this cadence exists to remove."""
    settings.FIRECRAWL_MONTHLY_CREDITS = 1_000
    delete_sink = []

    with pytest.raises(MonitorBudgetExceeded, match="m1"):
        create_monitor(
            api_key="k", name="2027:uni.example.org",
            targets=[{"type": "scrape", "url": "https://uni.example.org/"}],
            already_committed=900, reserve=200,
            post=_post({"success": True, "id": "m1", "estimatedCreditsPerMonth": 300}),
            delete=_delete(sink=delete_sink),
        )


def test_the_create_call_already_created_a_monitor_and_a_refusal_deletes_it():
    """F1: `_call('/monitor', ...)` runs BEFORE the budget comparison, so the
    vendor has already created (and will keep billing) the monitor by the
    time the ceiling check runs. A refusal that skips DELETE abandons it --
    exactly the silent staleness the cadence exists to remove, just billed
    instead of stale."""
    delete_sink = []

    with pytest.raises(MonitorBudgetExceeded):
        create_monitor(
            api_key="k", name="2027:uni.example.org",
            targets=[{"type": "scrape", "url": "https://uni.example.org/"}],
            already_committed=10**9, reserve=0,
            post=_post({"success": True, "id": "m1", "estimatedCreditsPerMonth": 30}),
            delete=_delete(sink=delete_sink),
        )

    assert delete_sink == ["https://api.firecrawl.dev/v2/monitor/m1"]


def test_a_failed_delete_still_raises_the_original_refusal_with_the_id():
    """The id is what makes the orphan recoverable by hand if the delete
    call itself fails -- a cleanup failure must never mask, or replace, the
    refusal that triggered it."""

    def broken_delete(url, headers):
        return 500, b"", {}

    with pytest.raises(MonitorBudgetExceeded, match="m1"):
        create_monitor(
            api_key="k", name="2027:uni.example.org",
            targets=[{"type": "scrape", "url": "https://uni.example.org/"}],
            already_committed=10**9, reserve=0,
            post=_post({"success": True, "id": "m1", "estimatedCreditsPerMonth": 30}),
            delete=broken_delete,
        )


def test_a_missing_estimate_raises_rather_than_being_treated_as_free():
    """F2: an absent estimatedCreditsPerMonth was coerced to 0, so the
    ceiling check passed trivially and the cycle's monitors were created
    unmetered against a field the vendor could rename. An unknown cost is not
    a zero cost."""
    with pytest.raises(MonitorEstimateMissing, match="m1"):
        create_monitor(
            api_key="k", name="2027:uni.example.org",
            targets=[{"type": "scrape", "url": "https://uni.example.org/"}],
            post=_post({"success": True, "id": "m1"}),
            delete=_delete(),
        )


def test_targets_split_at_fifty_and_are_named_in_sequence():
    """Firecrawl's documented ceiling. A site with 60 rule-bearing URLs is not
    rare -- a faculty publishes one page per programme -- and a create call
    that silently kept the first 50 would leave ten pages unmonitored with
    nothing saying so."""
    urls = tuple(f"https://uni.example.org/p{n}/" for n in range(60))

    batches = build_targets(urls, hosts=("uni.example.org",), include_paths=("documents",))

    assert len(batches) == 2
    assert all(len(batch) <= MAX_TARGETS for batch in batches)
    assert sum(len(batch) for batch in batches) == 61, "60 scrape targets plus one crawl"


def test_a_crawl_target_carries_the_same_include_paths_as_the_sweep():
    """So that a NEW requirements page -- not a change to any known URL -- is
    reported as `new`. A crawl target with different paths reports a different
    site than the one the sweep read."""
    batches = build_targets(
        ("https://uni.example.org/apply/",),
        hosts=("uni.example.org",),
        include_paths=("documents", "bewerbung"),
    )

    crawl_target = next(t for t in batches[0] if t["type"] == "crawl")
    assert crawl_target["includePaths"] == [".*documents.*", ".*bewerbung.*"]
    assert crawl_target["limit"] == 25


def test_checks_come_back_with_their_status_per_page():
    checks = list_checks(
        api_key="k", monitor_id="m1",
        get=lambda url, headers: (
            200,
            json.dumps(
                {
                    "checks": [
                        {
                            "id": "c1",
                            "status": "completed",
                            "pages": [
                                {"url": "https://uni.example.org/apply/", "status": "changed"},
                                {"url": "https://uni.example.org/faq/", "status": "same"},
                            ],
                        }
                    ]
                }
            ).encode(),
            {},
        ),
    )

    assert {page.status for page in checks} == {"changed", "same"}
    assert checks[0].url == "https://uni.example.org/apply/"


def test_a_check_skipped_for_credits_is_not_a_failure():
    """It resumes when credits do. Logged as a budget event, because a
    monitor reported as failing gets disabled by whoever is on call, and a
    disabled monitor is a site that stops being watched."""
    checks = list_checks(
        api_key="k", monitor_id="m1",
        get=lambda url, headers: (
            200,
            json.dumps(
                {"checks": [{"id": "c1", "status": "skipped_no_credits", "pages": []}]}
            ).encode(),
            {},
        ),
    )

    assert checks == ()
