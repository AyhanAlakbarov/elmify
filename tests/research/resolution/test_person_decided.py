"""A person's answer in the queue is never undone by a machine re-read (brief D4).

The gate's third criterion is "the same question is never asked again". A
SITE_UNKNOWN answer lands on `RegisterEntry` as RESOLVED/HUMAN or REFUSED, and
five paths re-derive that row: a closed list's re-read, the VGM register's,
a Wikidata enumeration's, EACEA's, and the resolver's queue. Each is pinned here.
"""

from datetime import date

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.research.models import (
    ClosedList,
    RegisterEntry,
    person_decided,
    resolver_decided,
)
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db
NOW = timezone.now()


def _human_bound(register: str, key: str, name: str = "ÖRNEK") -> RegisterEntry:
    org = record_organisation(
        domain="human-choice.org.tr", name=name, kind="PRIVATE_FOUNDATION", country_code="TR",
        found_via="HUMAN:x", identifiers=(("HUMAN", f"{register}:{key}"),), status="REGISTERED",
    )
    return RegisterEntry.objects.create(
        register=register, external_key=key, name=name, names=[name],
        resolution="RESOLVED", resolved_via="HUMAN", organisation=org, last_seen=NOW,
    )


def _refused(register: str, key: str, name: str = "ÖRNEK") -> RegisterEntry:
    return RegisterEntry.objects.create(
        register=register, external_key=key, name=name, names=[name],
        resolution="REFUSED", refused_reason="NOT_A_FUNDER", last_seen=NOW,
    )


def _assert_kept(entry: RegisterEntry) -> None:
    before = (entry.resolution, entry.resolved_via, entry.refused_reason, entry.organisation_id)
    entry.refresh_from_db()
    assert (
        entry.resolution, entry.resolved_via, entry.refused_reason, entry.organisation_id
    ) == before


# --- the shape --------------------------------------------------------------


def test_refused_carries_a_reason_and_nothing_else_does() -> None:
    _refused("vgm_tr", "ok")
    for fields in (
        {"resolution": "REFUSED"},
        {"resolution": "REFUSED", "refused_reason": "NOT_A_FUNDER", "resolved_via": "HUMAN"},
        {"resolution": "UNRESOLVED", "refused_reason": "NOT_A_FUNDER"},
        {"resolution": "RESOLVED", "resolved_via": "HUMAN", "refused_reason": "DOES_NOT_EXIST"},
        {"resolution": "REFUSED", "refused_reason": "MAYBE"},
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            RegisterEntry.objects.create(
                register="vgm_tr", external_key=str(fields), name="x", last_seen=NOW, **fields
            )


def test_the_predicates() -> None:
    assert person_decided("RESOLVED", "HUMAN") and person_decided("REFUSED", "")
    assert not person_decided("RESOLVED", "LISTED") and not person_decided("CONFLICT", "")
    assert resolver_decided("REFUSED", "") and resolver_decided("RESOLVED", "HUMAN")


def test_a_refused_row_reads_as_refused_and_does_not_fail_the_gate() -> None:
    from apps.research.read_state import ReadState, entry_read_state, list_gate

    ClosedList.objects.create(
        slug="l", title="l", holder_kinds=[], rung=1, source_url="https://example.org/l",
        maintainer="m", carries_purpose=True, carries_website=True, reuse_terms="OPEN",
        is_denominator=True, read_policy="FUNDING_READ", verified_on=date.today(),
    )
    entry = _refused("l", "a")
    found = entry_read_state(entry, "FUNDING_READ")
    assert (found.state, found.detail) == (ReadState.REFUSED, "NOT_A_FUNDER")
    assert list_gate("l", now=NOW).passed


# --- the re-read paths ------------------------------------------------------


@pytest.mark.parametrize("decided", [_human_bound, _refused])
def test_a_closed_list_re_read_keeps_it_even_with_its_own_website(decided) -> None:
    from apps.research.closed_lists import ListRow, record_list

    spec = ClosedList.objects.create(
        slug="tr_banks", title="Banks", country_code="TR", holder_kinds=["BANK_OR_LENDER"],
        rung=2, source_url="https://www.bddk.org.tr", maintainer="m", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="SIGNAL_ONLY", verified_on=date.today(),
    )
    entry = decided("tr_banks", "b1", "Örnek Bankası")

    def row(website: str, name: str = "Örnek Bankası") -> ListRow:
        return ListRow(
            external_key="b1", name=name, kind="BANK_OR_LENDER", website=website,
            page_url="", country_code="TR", home_cells=("TR",), host_cells=("ANY",),
            rejected_reason="", source_url="https://www.bddk.org.tr",
            verified_on=date.today(),
        )

    report = record_list(spec, [row("https://www.ornekbank.com.tr")], now=NOW)
    _assert_kept(entry)
    assert report.unresolved == 1  # this list did not bind it
    record_list(spec, [row("")], now=NOW)
    _assert_kept(entry)
    record_list(spec, [row("", name="Örnek Bankası A.Ş.")], now=NOW)
    _assert_kept(entry)
    assert entry.name == "Örnek Bankası A.Ş."


@pytest.mark.parametrize("decided", [_human_bound, _refused])
def test_the_vgm_register_re_read_keeps_it_even_with_an_own_domain_email(decided) -> None:
    from apps.research.vgm import VgmRow, record_vgm

    entry = decided("vgm_tr", "7-7", "ÖRNEK VAKFI")
    record_vgm([VgmRow("ÖRNEK VAKFI", "Ankara", "7-7", "info@ornekvakfi.org.tr")], now=NOW)
    _assert_kept(entry)
    record_vgm([VgmRow("ÖRNEK VAKFI", "Ankara", "7-7", "ornek@gmail.com")], now=NOW)
    _assert_kept(entry)


@pytest.mark.parametrize("decided", [_human_bound, _refused])
def test_a_wikidata_re_read_keeps_it_and_does_not_re_conflict(decided) -> None:
    from apps.research.wikidata import EnumerationRow, Item, record_items

    # The CONFLICT a person answered: Q1 is already on a different body.
    record_organisation(domain="a.edu.tr", name="A", kind="INSTITUTION", country_code="TR",
                        found_via="x", identifiers=[("WIKIDATA", "Q1")])
    record_organisation(domain="b.edu.tr", name="B", kind="INSTITUTION", country_code="TR",
                        found_via="x")
    entry = decided("wd_tr_university", "Q1", "B University")
    row = EnumerationRow(
        slug="wd_tr_university", country_code="TR", class_qid="Q3918", kind="INSTITUTION",
        widen=False, min_count=1, max_count=10, home_cells=("ANY",), host_cells=("TR",),
    )
    report = record_items(
        row, (Item("Q1", "B University", ("B University",), ("https://b.edu.tr",)),), now=NOW
    )
    assert report.conflicts == 0
    _assert_kept(entry)


@pytest.mark.parametrize("decided", [_human_bound, _refused])
def test_an_eacea_re_read_keeps_it_and_still_records_the_partners(decided) -> None:
    from apps.research.eacea import record_projects

    # The coordinator CONFLICT a person answered: PIC on one body, website on another.
    record_organisation(domain="euc.ac.cy", name="EUC", kind="INSTITUTION", country_code="CY",
                        found_via="x", identifiers=[("EACEA_PIC", "111")])
    record_organisation(domain="unic.ac.cy", name="UNIC", kind="INSTITUTION",
                        country_code="CY", found_via="x")
    entry = decided("eacea_emjm", "p1", "EMJM X")
    coordinator = {
        "organisationName": "UNIC", "organisationPIC": "111", "organisationCountry": "CY",
        "organisationCity": "NICOSIA", "organisationWebsite": "https://www.unic.ac.cy",
        "organisationRole": "coordinator",
    }
    record_projects(
        [{"projectName": "p1", "projectTitle": "EMJM X", "coordinator": coordinator}], now=NOW
    )
    _assert_kept(entry)
    assert entry.partners.get().disposition == "CONFLICT"


def test_the_resolver_queue_never_offers_a_person_decided_row() -> None:
    from apps.research.resolve_entries import due_entries

    _human_bound("vgm_tr", "h")
    _refused("vgm_tr", "r")
    RegisterEntry.objects.create(
        register="vgm_tr", external_key="u", name="U", resolution="UNRESOLVED", last_seen=NOW
    )
    for retry_final in (False, True):
        due = due_entries("vgm_tr", now=NOW, retry_final=retry_final)
        assert list(due.values_list("external_key", flat=True)) == ["u"]


def test_the_resolver_never_writes_over_a_person_decided_row() -> None:
    from apps.research.resolve_entries import EntryMovedOn, RegisterSpec, record_resolution
    from apps.research.resolver import Resolution

    entry = _refused("vgm_tr", "r", "ÖRNEK VAKFI")
    stale = RegisterEntry.objects.get(pk=entry.pk)
    stale.resolution = "UNRESOLVED"  # what the resolver read before the person answered
    with pytest.raises(EntryMovedOn, match="REFUSED"):
        record_resolution(
            stale, Resolution(reason="NO_CANDIDATE", names=("x",)),
            spec=RegisterSpec(country_code="TR", kind="PRIVATE_FOUNDATION"), now=NOW,
        )
    _assert_kept(entry)
