"""Read states: what reading each listed body came to, derived, never typed.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
sections 6.1 (read state), 15, 16 item 7 (the gate).
"""

import hashlib
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.funding.models import OfficialSource, OfficialSourceSnapshot
from apps.research.models import ClosedList, FetchAttempt, Organisation, RegisterEntry
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db
NOW = timezone.now()


def _list(slug: str = "l", policy: str = "FUNDING_READ", **extra: object) -> ClosedList:
    fields: dict[str, object] = dict(
        slug=slug, title=slug, holder_kinds=[], rung=1, source_url="https://example.org/l",
        maintainer="m", carries_purpose=True, carries_website=True, reuse_terms="OPEN",
        is_denominator=True, read_policy=policy, verified_on=date.today(),
    )
    fields.update(extra)
    return ClosedList.objects.create(**fields)


def _entry(slug: str = "l", key: str = "a", domain: str | None = "body.example.org",
           page: str = "https://www.body.example.org/scholarship") -> RegisterEntry:
    org = None
    if domain:
        org = record_organisation(domain=domain, name=key, kind="INTERGOVERNMENTAL",
                                  country_code="", found_via="R1_LIST:l")
    return RegisterEntry.objects.create(
        register=slug, external_key=key, name=key, page_url=page, organisation=org,
        resolution="RESOLVED" if org else "UNRESOLVED", resolved_via="LISTED" if org else "",
        last_seen=NOW,
    )


def _snapshot(url: str, **extra: object) -> OfficialSourceSnapshot:
    source, _ = OfficialSource.objects.get_or_create(
        canonical_url=url, defaults={"publisher": url.split("/")[2], "source_type": "FUNDER"},
    )
    fields: dict[str, object] = dict(
        source=source, s3_key="k", s3_version_id="v",
        sha256=hashlib.sha256(f"{url}{sorted(extra.items())}".encode()).hexdigest(),
        final_url=url, retrieved_at=NOW, admissions_cycle="2027", content_type="text/html",
        byte_size=1,
    )
    fields.update(extra)
    return OfficialSourceSnapshot.objects.create(**fields)


def _attempt(url: str, outcome: str) -> None:
    FetchAttempt.objects.create(url=url, host=url.split("/")[2], rung=1, vendor="FIRECRAWL",
                                outcome=outcome)


def test_an_unbound_entry_is_unbound_and_fails_the_gate() -> None:
    from apps.research.read_state import ReadState, entry_read_state, list_gate

    _list()
    entry = _entry(domain=None)
    assert entry_read_state(entry, "FUNDING_READ").state == ReadState.UNBOUND
    assert not list_gate("l", now=NOW).passed


def test_a_funding_read_snapshot_on_any_of_the_bodys_hosts_is_a_read() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    # A hop inside the body's own site counts: the reader followed a funding
    # link from the scheme page (pipeline.funding_links).
    _snapshot("https://apply.body.example.org/call-2027", funding_read_at=NOW)
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.FUNDING_READ, "1 pages")


def test_a_page_fetched_but_never_funding_read_is_unread() -> None:
    """A run without --funding catalogues the page and reads no money from it."""
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _snapshot("https://www.body.example.org/scholarship")
    assert entry_read_state(entry, "FUNDING_READ").state == ReadState.UNREAD


def test_a_shell_is_unreadable_never_no_funding() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _snapshot("https://www.body.example.org/scholarship", readability="SHELL")
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.UNREADABLE, "SHELL")


def test_a_refused_fetch_is_could_not_look_with_the_outcome() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _attempt(entry.page_url, "BLOCKED")
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.COULD_NOT_LOOK, "BLOCKED")


def test_our_budget_running_out_is_unread_not_the_host_refusing() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _attempt(entry.page_url, "BUDGET")
    assert entry_read_state(entry, "FUNDING_READ").state == ReadState.UNREAD


def test_classify_policy_reads_the_classifier_columns() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list(policy="CLASSIFY")
    entry = _entry(page="")
    org = entry.organisation
    assert org is not None
    assert entry_read_state(entry, "CLASSIFY").state == ReadState.UNREAD
    org.classifier_confidence = 0.55
    org.save(update_fields=["classifier_confidence"])
    assert entry_read_state(entry, "CLASSIFY").state == ReadState.ABSTAINED
    org.classified_at, org.classified_by = NOW, "FRONTIER"
    org.save(update_fields=["classified_at", "classified_by"])
    found = entry_read_state(entry, "CLASSIFY")
    assert (found.state, found.detail) == (ReadState.CLASSIFIED, "FRONTIER")


def test_a_signal_only_body_without_a_signal_is_gated_and_passes() -> None:
    from apps.research.read_state import ReadState, entry_read_state, list_gate

    _list(policy="SIGNAL_ONLY")
    entry = _entry(page="")
    assert entry_read_state(entry, "SIGNAL_ONLY").state == ReadState.GATED
    assert list_gate("l", now=NOW).passed


def test_a_rejected_body_is_recorded_rejected_with_its_reason() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    Organisation.objects.filter(pk=entry.organisation_id).update(
        status="REJECTED", rejected_reason="NOT_A_FUNDER"
    )
    entry.refresh_from_db()
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.REJECTED, "NOT_A_FUNDER")


def test_fewer_entries_than_the_list_prints_is_not_enumerated() -> None:
    from apps.research.read_state import list_gate

    _list(policy="SIGNAL_ONLY", printed_size=2)
    _entry(page="")
    gate = list_gate("l", now=NOW)
    assert not gate.enumerated and not gate.passed


def test_recording_writes_the_state_and_the_bodys_read_fields() -> None:
    from apps.research.read_state import record_read_states

    _list()
    entry = _entry()
    _snapshot("https://www.body.example.org/scholarship", funding_read_at=NOW)
    tally = record_read_states("l", now=NOW)
    entry.refresh_from_db()
    assert tally == {"FUNDING_READ": 1}
    assert (entry.read_state, entry.read_state_at) == ("FUNDING_READ", NOW)
    org = Organisation.objects.get(pk=entry.organisation_id)
    assert (org.last_read_at, org.pages_read) == (NOW, 1)


def test_a_list_past_its_recheck_date_is_stale_but_not_failed(settings) -> None:
    from apps.research.read_state import list_gate

    settings.CLOSED_LIST_RECHECK_DAYS = 90
    _list(policy="SIGNAL_ONLY", verified_on=date.today() - timedelta(days=91))
    _entry(page="")
    gate = list_gate("l", now=NOW)
    assert gate.stale and gate.passed


def test_one_read_scheme_does_not_mark_the_bodys_other_scheme_read() -> None:
    """One entry per scheme: a body with two schemes on a list needs each
    scheme page read, or the second reads done when it never was."""
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    first = _entry(key="a", page="https://www.body.example.org/scheme-a")
    second = RegisterEntry.objects.create(
        register="l", external_key="b", name="b", organisation=first.organisation,
        page_url="https://www.body.example.org/scheme-b", resolution="RESOLVED",
        resolved_via="LISTED", last_seen=NOW,
    )
    _snapshot("https://www.body.example.org/scheme-a", funding_read_at=NOW)
    assert entry_read_state(first, "FUNDING_READ").state == ReadState.FUNDING_READ
    assert entry_read_state(second, "FUNDING_READ").state == ReadState.UNREAD


def test_an_unrelated_shell_on_the_domain_is_not_this_schemes_state() -> None:
    from apps.research.read_state import ReadState, entry_read_state

    _list()
    entry = _entry()
    _snapshot("https://www.body.example.org/news", readability="SHELL")
    assert entry_read_state(entry, "FUNDING_READ").state == ReadState.UNREAD
