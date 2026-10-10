"""The Turkish register ladder, end to end, on fixtures.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
sections 6.2 (the VGM row), 6.5 (rung 0), 16 item 6a.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.research.models import Organisation, RegisterEntry
from apps.research.register import record_organisation
from apps.research.vgm import VgmRow

pytestmark = pytest.mark.django_db


def test_a_register_entry_is_unique_per_register_and_key() -> None:
    RegisterEntry.objects.create(
        register="vgm_tr", external_key="25787-89929-78267", name="13 YILDIZ YETİMLER VAKFI",
        city="İstanbul (Avrupa) / Beşiktaş", contact_domain="tohum13yildiz.com",
        resolution=RegisterEntry.Resolution.RESOLVED, resolved_via="EMAIL",
        last_seen=timezone.now(),
    )
    with pytest.raises(IntegrityError):
        RegisterEntry.objects.create(
            register="vgm_tr", external_key="25787-89929-78267", name="duplicate",
            resolution=RegisterEntry.Resolution.UNRESOLVED, last_seen=timezone.now(),
        )


def test_an_organisation_starts_unclassified() -> None:
    org = record_organisation(
        domain="tev.org.tr", name="Türk Eğitim Vakfı", kind="PRIVATE_FOUNDATION",
        country_code="TR", found_via="R1_REGISTER:vgm", status=Organisation.Status.REGISTERED,
    )
    assert org.funds_students is None
    assert org.classified_at is None
    assert org.classified_by == ""
    assert org.classifier_confidence is None


FIXTURE = Path(__file__).parent / "fixtures" / "vgm_page1.html"


def test_parse_vgm_page_reads_every_row_with_its_email() -> None:
    """Captured 2026-09-24 from
    https://www.vgm.gov.tr/vakif-sorgulama/vakif-sorgulama?Page=1&IsGrant=true
    (fetched_via=FIRECRAWL, outcome starts FETCHED then UNCHANGED on a
    same-content re-fetch, 1 credit each call; the requested PageSize=50 does
    not survive to Firecrawl's reported final_url).

    12 rows a page, not 50 -- PageSize is IGNORED by the endpoint; the page
    prints its own total separately from the requested page size. Total
    printed as '<span id="resultCount">4076</span> Adet Sonuç Listeleniyor.',
    which collapses to '4076 Adet Sonuç' once tags are stripped -- matches
    the brief's regex unchanged.

    The captured page has no charset declaration anywhere in the markup, and
    lxml's own encoding sniff on the raw bytes mis-guesses a Latin encoding
    (measured: "YETİMLER" came back as "YETÄ°MLER"), so `vgm.py` decodes as
    UTF-8 before handing lxml a string -- see `_tree` there.
    """
    from apps.research.vgm import parse_vgm_page

    rows = parse_vgm_page(FIXTURE.read_bytes())
    assert len(rows) == 12
    first = rows[0]
    assert first.name == "13 YILDIZ YETİMLER VAKFI"
    assert first.city.startswith("İstanbul")
    assert first.notification_id == "25787-89929-78267"
    assert first.email == "info@tohum13yildiz.com"
    assert all(r.name for r in rows)


def test_vgm_total_reads_the_count_the_page_prints() -> None:
    from apps.research.vgm import vgm_total

    assert vgm_total(FIXTURE.read_bytes()) == 4076


def test_vgm_page_url_carries_the_scholarship_filter() -> None:
    from apps.research.vgm import vgm_page_url

    url = vgm_page_url(3, 50)
    assert url.startswith("https://www.vgm.gov.tr/vakif-sorgulama/vakif-sorgulama?")
    assert "IsGrant=true" in url and "Page=3" in url and "PageSize=50" in url


def _page(*rows: VgmRow, total: int = 4076) -> bytes:
    body = "".join(
        f"<tr><td>{r.name}</td><td>addr</td><td>{r.city}</td><td>(312) 1</td>"
        f"<td>{r.notification_id}</td><td>{r.email}</td></tr>"
        for r in rows
    )
    return (
        f"<html><body><p>{total} Adet Sonuç Listeleniyor.</p>"
        f"<table>{body}</table></body></html>"
    ).encode()


class _Fetch:
    """A fetch seam that serves pages by number and records what was asked."""

    def __init__(self, pages: dict[int, bytes]) -> None:
        self.pages, self.asked = pages, []

    def __call__(self, url: str, **kwargs: object):
        from apps.research.fetch.types import FetchedPage

        page = int(url.split("Page=")[1].split("&")[0])
        self.asked.append(page)
        body = self.pages.get(page, _page())
        return FetchedPage(
            final_url=url, redirects=(), content_type="text/html",
            body=body, fetched_via="FIRECRAWL",
        )


def test_read_vgm_stops_on_a_refused_page_and_says_why() -> None:
    from apps.research.fetch.types import FetchedPage, Outcome
    from apps.research.vgm import RegisterShape, read_vgm

    def refused(url: str, **kwargs: object) -> FetchedPage:
        return FetchedPage(final_url=url, redirects=(), content_type="text/html", body=b"",
                           fetched_via="FIRECRAWL", outcome=Outcome.BLOCKED, reason="403 relayed")

    with pytest.raises(RegisterShape, match="BLOCKED"):
        list(read_vgm(fetch=refused, page_size=50))


A = VgmRow("A VAKFI", "Ankara", "1-1", "info@avakfi.org.tr")
B = VgmRow("B VAKFI", "İzmir", "2-2", "bvakfi@gmail.com")
C = VgmRow("C VAKFI", "Bursa", "3-3", "burs@cvakfi.org")


def test_read_vgm_stops_when_a_page_comes_back_empty() -> None:
    """total must clear the printed-total floor (>=1000, see `_TOTAL_FLOOR`),
    so page 1 carries 500 rows and total=1000 fixes last_page at 2 -- an
    empty page 3 is past it and ends the run, not a shell to retry."""
    from apps.research.vgm import read_vgm

    page1 = tuple(
        VgmRow(f"V{i} VAKFI", "Ankara", f"{i}-{i}", "info@example.org") for i in range(500)
    )
    fetch = _Fetch({1: _page(*page1, total=1000), 2: _page(C), 3: _page()})
    pages = list(read_vgm(fetch=fetch, page_size=500))
    assert [len(p) for p in pages] == [500, 1]
    assert fetch.asked == [1, 2, 3]


def test_an_empty_page_below_the_total_is_retried_once_then_refused() -> None:
    """Page 52 came back FETCHED with an empty table on 2026-09-24: a rendered
    shell, not the end of the register. Silence there ended the run at 15%."""
    from apps.research.vgm import RegisterShape, read_vgm

    # total 4076, 2 rows a page: page 2 is far below the end
    fetch = _Fetch({1: _page(A, B), 2: _page()})
    with pytest.raises(RegisterShape, match="page 2 rendered empty twice"):
        list(read_vgm(fetch=fetch, page_size=2))
    assert fetch.asked == [1, 2, 2]


def test_an_empty_page_below_the_total_that_fills_on_retry_continues() -> None:
    from apps.research.vgm import read_vgm

    class _Flaky(_Fetch):
        def __init__(self) -> None:
            super().__init__({1: _page(A, B), 2: _page(C)})
            self.served_empty = False

        def __call__(self, url: str, **kwargs: object):
            page = int(url.split("Page=")[1].split("&")[0])
            if page == 2 and not self.served_empty:
                self.served_empty = True
                self.asked.append(page)
                from apps.research.fetch.types import FetchedPage

                return FetchedPage(
                    final_url=url, redirects=(), content_type="text/html",
                    body=_page(), fetched_via="FIRECRAWL",
                )
            return super().__call__(url, **kwargs)

    fetch = _Flaky()
    pages = list(read_vgm(fetch=fetch, page_size=2, max_pages=2))
    assert [len(p) for p in pages] == [2, 1]
    assert fetch.asked == [1, 2, 2]


def test_read_vgm_resumes_from_a_page() -> None:
    """Run 2 stopped mid-register with RETRY_SCHEDULED unreachable; re-running
    from page 1 would re-spend every credit up to the stop point.
    `start_page` resumes the fetch loop there directly, and the total/per_page
    learning that page 1 would normally do runs on the first page FETCHED IN
    THIS RUN instead -- same shape as `test_read_vgm_stops_when_a_page_comes_
    back_empty`, just shifted: 500 rows on the first fetched page (3) with
    total=1000 fixes per_page=500 and last_page=2 (an absolute page number,
    harmlessly below start_page here), so page 5 coming back empty is past it
    and ends the run without a retry."""
    from apps.research.vgm import read_vgm

    page3 = tuple(
        VgmRow(f"V{i} VAKFI", "Ankara", f"{i}-{i}", "info@example.org") for i in range(500)
    )
    fetch = _Fetch({3: _page(*page3, total=1000), 4: _page(C)})
    pages = list(read_vgm(fetch=fetch, page_size=500, start_page=3))
    assert [len(p) for p in pages] == [500, 1]
    assert fetch.asked == [3, 4, 5]


def test_max_pages_counts_pages_fetched_in_this_run_not_the_page_number() -> None:
    """A resumed run of `max_pages=2` starting at page 225 must fetch pages
    225 and 226 -- not stop immediately because 225 > 2."""
    from apps.research.vgm import read_vgm

    page3 = tuple(
        VgmRow(f"V{i} VAKFI", "Ankara", f"{i}-{i}", "info@example.org") for i in range(500)
    )
    fetch = _Fetch({3: _page(*page3, total=1000), 4: _page(C)})
    pages = list(read_vgm(fetch=fetch, page_size=500, start_page=3, max_pages=2))
    assert [len(p) for p in pages] == [500, 1]
    assert fetch.asked == [3, 4]


def test_read_vgm_refuses_a_start_page_below_one() -> None:
    from apps.research.vgm import read_vgm

    def must_not_fetch(url: str, **kwargs: object):
        raise AssertionError("must not fetch when start_page is invalid")

    with pytest.raises(ValueError, match="start_page"):
        list(read_vgm(fetch=must_not_fetch, start_page=0))


def test_a_shell_on_page_one_is_a_register_shape() -> None:
    from apps.research.vgm import RegisterShape, read_vgm

    fetch = _Fetch({1: _page()})  # prints 4076 but has no rows
    with pytest.raises(RegisterShape):
        list(read_vgm(fetch=fetch, page_size=2))


def test_read_vgm_refuses_a_register_of_the_wrong_size() -> None:
    from apps.research.vgm import RegisterShape, read_vgm

    shell = b"<html><body><p>12 Adet Sonu\xc3\xa7</p><table></table></body></html>"
    fetch = _Fetch({1: shell})
    with pytest.raises(RegisterShape):
        list(read_vgm(fetch=fetch, page_size=50))


def test_record_vgm_writes_entries_and_resolves_rung_zero_only() -> None:
    from apps.research.vgm import record_vgm

    report = record_vgm([A, B, C], now=datetime(2026, 9, 24, tzinfo=UTC))
    assert (report.listed, report.resolved, report.unresolved) == (3, 2, 1)
    assert report.organisations_new == 2
    a = RegisterEntry.objects.get(register="vgm_tr", external_key="1-1")
    assert a.resolution == "RESOLVED" and a.contact_domain == "avakfi.org.tr"
    assert a.organisation is not None and a.organisation.primary_domain == "avakfi.org.tr"
    org = a.organisation
    assert org.status == Organisation.Status.REGISTERED
    assert org.kind == "PRIVATE_FOUNDATION" and org.country_code == "TR"
    assert "R1_REGISTER:vgm" in org.found_via and "A VAKFI" in org.names
    b = RegisterEntry.objects.get(register="vgm_tr", external_key="2-2")
    assert b.resolution == "UNRESOLVED" and b.organisation is None and b.contact_domain == ""


def test_record_vgm_is_idempotent_and_bumps_last_seen() -> None:
    from apps.research.vgm import record_vgm

    record_vgm([A], now=datetime(2026, 9, 1, tzinfo=UTC))
    report = record_vgm([A], now=datetime(2026, 10, 1, tzinfo=UTC))
    assert report.organisations_new == 0 and report.organisations_known == 1
    assert RegisterEntry.objects.filter(register="vgm_tr").count() == 1
    assert RegisterEntry.objects.get(external_key="1-1").last_seen.month == 10
    assert Organisation.objects.filter(primary_domain="avakfi.org.tr").count() == 1


def test_register_coverage_is_arithmetic_over_the_entries() -> None:
    from apps.research.vgm import record_vgm, register_coverage

    record_vgm([A, B, C], now=datetime(2026, 9, 24, tzinfo=UTC))
    cov = register_coverage("vgm_tr")
    assert (cov.listed, cov.bodies_known, cov.resolved, cov.unresolved) == (3, 2, 2, 1)
    assert cov.classified == 0 and cov.funds_students == 0


def test_register_coverage_counts_distinct_bodies_not_entries() -> None:
    """Two entries bound to the SAME organisation (a branch office, a second
    e-mail on the same domain) must count as one body known, not two."""
    from apps.research.vgm import record_vgm, register_coverage

    same_domain_a = VgmRow("A VAKFI", "Ankara", "1-1", "info@avakfi.org.tr")
    same_domain_b = VgmRow("A VAKFI ŞUBE", "Ankara", "1-2", "branch@avakfi.org.tr")
    record_vgm([same_domain_a, same_domain_b], now=datetime(2026, 9, 24, tzinfo=UTC))
    cov = register_coverage("vgm_tr")
    assert cov.listed == 2
    assert cov.resolved == 2
    assert cov.bodies_known == 1


def test_record_vgm_keys_a_row_with_no_notification_id_on_its_name() -> None:
    """110 VGM rows carry no e-tebligat id; a name is never a lookup key
    elsewhere in this codebase, so the fallback key is prefixed to say so."""
    from apps.research.vgm import record_vgm

    row = VgmRow("NO ID VAKFI", "Ankara", "", "info@noidvakfi.org.tr")
    report = record_vgm([row], now=datetime(2026, 9, 24, tzinfo=UTC))
    assert report.name_keyed == 1
    entry = RegisterEntry.objects.get(register="vgm_tr", external_key="name:NO ID VAKFI")
    assert entry.name == "NO ID VAKFI"


def test_record_vgm_logs_a_warning_when_a_key_s_stored_name_changes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A collision -- the same key seen with a different name across runs --
    is not the silent merge `record_organisation` refuses to do on a name;
    it is filed as a warning naming the register, the key and both names."""
    from apps.research.vgm import record_vgm

    first = VgmRow("OLD NAME VAKFI", "Ankara", "9-9", "info@oldnamevakfi.org.tr")
    second = VgmRow("NEW NAME VAKFI", "Ankara", "9-9", "info@oldnamevakfi.org.tr")
    record_vgm([first], now=datetime(2026, 9, 1, tzinfo=UTC))
    with caplog.at_level(logging.WARNING, logger="apps.research.vgm"):
        record_vgm([second], now=datetime(2026, 9, 2, tzinfo=UTC))
    assert "9-9" in caplog.text
    assert "OLD NAME VAKFI" in caplog.text and "NEW NAME VAKFI" in caplog.text


# --- The resolver's record (build item 8, Task 6). ---


def test_rung_zero_records_how_it_resolved_and_the_register_s_name() -> None:
    from apps.research.vgm import record_vgm

    record_vgm([VgmRow(name="TÜRK EĞİTİM VAKFI", city="Ankara", notification_id="1",
                       email="info@tev.org.tr"),
                VgmRow(name="BİLİM VE SANAT VAKFI", city="İstanbul", notification_id="2",
                       email="bisav@gmail.com")],
               now=datetime(2026, 9, 25, tzinfo=UTC))
    resolved = RegisterEntry.objects.get(external_key="1")
    unresolved = RegisterEntry.objects.get(external_key="2")
    assert resolved.resolved_via == "EMAIL" and resolved.names == ["TÜRK EĞİTİM VAKFI"]
    assert unresolved.resolved_via == "" and unresolved.unresolved_reason == ""
    assert unresolved.names == ["BİLİM VE SANAT VAKFI"]


@pytest.mark.parametrize("shape", [
    {"resolution": "RESOLVED", "resolved_via": ""},
    {"resolution": "RESOLVED", "resolved_via": "DIFFBOT", "unresolved_reason": "NO_CANDIDATE"},
    {"resolution": "UNRESOLVED", "resolved_via": "EMAIL"},
    {"resolution": "CONFLICT", "resolved_via": "WIKIDATA"},
])
def test_a_resolved_row_carries_no_reason_and_an_unresolved_one_no_route(shape) -> None:
    with pytest.raises(IntegrityError):
        RegisterEntry.objects.create(
            register="vgm_tr", external_key="x", name="n", last_seen=timezone.now(), **shape,
        )


def test_an_identifier_conflict_is_a_conflict_with_its_reason() -> None:
    RegisterEntry.objects.create(
        register="vgm_tr", external_key="x", name="n", last_seen=timezone.now(),
        resolution="CONFLICT", unresolved_reason="IDENTIFIER_CONFLICT",
    )


def test_a_re_read_never_unresolves_what_the_resolver_bound() -> None:
    from apps.research.vgm import record_vgm

    row = VgmRow(name="BİLİM VE SANAT VAKFI", city="İstanbul", notification_id="2",
                 email="bisav@gmail.com")
    record_vgm([row], now=datetime(2026, 9, 25, tzinfo=UTC))
    org = record_organisation(domain="bisav.org.tr", name=row.name, kind="PRIVATE_FOUNDATION",
                              country_code="TR", found_via="RESOLVER:DIFFBOT")
    RegisterEntry.objects.filter(external_key="2").update(
        resolution="RESOLVED", resolved_via="DIFFBOT", organisation=org,
        names=[row.name, "Science and Art Foundation"])
    record_vgm([row], now=datetime(2026, 10, 25, tzinfo=UTC))
    entry = RegisterEntry.objects.get(external_key="2")
    assert (entry.resolution, entry.resolved_via, entry.organisation_id) == (
        "RESOLVED", "DIFFBOT", org.id)
    assert entry.names == [row.name, "Science and Art Foundation"]
    assert entry.last_seen.month == 10


def test_a_re_read_keeps_a_conflict_the_resolver_left_for_a_person() -> None:
    from apps.research.vgm import record_vgm

    row = VgmRow("BİLİM VE SANAT VAKFI", "İstanbul", "2", "bisav@gmail.com")
    record_vgm([row], now=datetime(2026, 9, 25, tzinfo=UTC))
    RegisterEntry.objects.filter(external_key="2").update(
        resolution="CONFLICT", unresolved_reason="IDENTIFIER_CONFLICT")
    record_vgm([row], now=datetime(2026, 10, 25, tzinfo=UTC))
    entry = RegisterEntry.objects.get(external_key="2")
    assert (entry.resolution, entry.unresolved_reason) == ("CONFLICT", "IDENTIFIER_CONFLICT")


def test_the_register_s_own_e_mail_overwrites_what_the_resolver_found() -> None:
    from apps.research.vgm import record_vgm

    row = VgmRow("BİLİM VE SANAT VAKFI", "İstanbul", "2", "bisav@gmail.com")
    record_vgm([row], now=datetime(2026, 9, 25, tzinfo=UTC))
    RegisterEntry.objects.filter(external_key="2").update(
        resolution="RESOLVED", resolved_via="SEARCH_TITLE")
    record_vgm([VgmRow(row.name, row.city, "2", "info@bisav.org.tr")],
               now=datetime(2026, 10, 25, tzinfo=UTC))
    entry = RegisterEntry.objects.get(external_key="2")
    assert (entry.resolution, entry.resolved_via) == ("RESOLVED", "EMAIL")
    assert entry.organisation is not None and entry.organisation.primary_domain == "bisav.org.tr"


def test_an_e_mail_that_turns_free_mail_withdraws_rung_zero_s_answer() -> None:
    """RESOLVED/EMAIL -> UNRESOLVED must clear the route in the same write, or
    the shape constraint refuses the re-read."""
    from apps.research.vgm import record_vgm

    record_vgm([VgmRow("A VAKFI", "Ankara", "1-1", "info@avakfi.org.tr")],
               now=datetime(2026, 9, 25, tzinfo=UTC))
    record_vgm([VgmRow("A VAKFI", "Ankara", "1-1", "avakfi@gmail.com")],
               now=datetime(2026, 10, 25, tzinfo=UTC))
    entry = RegisterEntry.objects.get(external_key="1-1")
    assert (entry.resolution, entry.resolved_via, entry.contact_domain) == ("UNRESOLVED", "", "")


def test_a_renamed_row_drops_what_the_resolver_found_for_the_old_name() -> None:
    from apps.research.vgm import record_vgm

    row = VgmRow(name="BİLİM VE SANAT VAKFI", city="İstanbul", notification_id="2",
                 email="bisav@gmail.com")
    record_vgm([row], now=datetime(2026, 9, 25, tzinfo=UTC))
    org = record_organisation(domain="bisav.org.tr", name=row.name, kind="PRIVATE_FOUNDATION",
                              country_code="TR", found_via="RESOLVER:DIFFBOT")
    RegisterEntry.objects.filter(external_key="2").update(
        resolution="RESOLVED", resolved_via="DIFFBOT", organisation=org,
        names=[row.name, "Science and Art Foundation"],
        resolution_attempted_at=datetime(2026, 9, 25, tzinfo=UTC))
    record_vgm([VgmRow("BİLİM SANAT VE KÜLTÜR VAKFI", "İstanbul", "2", "bisav@gmail.com")],
               now=datetime(2026, 10, 25, tzinfo=UTC))
    entry = RegisterEntry.objects.get(external_key="2")
    assert (entry.resolution, entry.resolved_via, entry.organisation_id) == ("UNRESOLVED", "", None)
    assert entry.names == ["BİLİM SANAT VE KÜLTÜR VAKFI"]
    assert entry.resolution_attempted_at is None


def test_a_withdrawn_e_mail_also_unbinds_the_body_it_bound() -> None:
    from apps.research.vgm import record_vgm, register_coverage

    record_vgm([VgmRow("TÜRK EĞİTİM VAKFI", "Ankara", "1", "info@tev.org.tr")],
               now=datetime(2026, 9, 25, tzinfo=UTC))
    record_vgm([VgmRow("TÜRK EĞİTİM VAKFI", "Ankara", "1", "tev@gmail.com")],
               now=datetime(2026, 10, 25, tzinfo=UTC))
    entry = RegisterEntry.objects.get(external_key="1")
    assert (entry.resolution, entry.resolved_via, entry.organisation) == ("UNRESOLVED", "", None)
    assert register_coverage("vgm_tr").bodies_known == 0
