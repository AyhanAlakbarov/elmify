"""Reviewed lists and funder lists as admission evidence (spec §5.1 points 2-3,
§5.7, §13.8). A reviewed row counts only once its origin named the institution."""

from dataclasses import replace
from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.research.closed_lists import ListRow, read_list_file, read_registry, record_list
from apps.research.domains import KIND_ONLY_GOVERNMENT_SUFFIXES, VERIFIED_SECOND_LEVEL
from apps.research.hosts import registrable_domain
from apps.research.models import (
    ClosedList,
    Organisation,
    OrganisationDomain,
    RegisterEntry,
    RegisterEntryPartner,
)
from apps.research.recognition import (
    GOVERNMENT_ZONES,
    ProvenanceSource,
    SourceFileError,
    government_zone,
    list_recognitions,
    name_variants,
    names_institution,
    read_sources,
    verify_list_origins,
)
from tests.research.provenance_helpers import FakeFetch, make_body, make_list, page

pytestmark = pytest.mark.django_db

CURATED = (
    ProvenanceSource(slug="az_heis", role="curated_list"),
    ProvenanceSource(slug="national_scholarship_agencies", role="curated_list"),
    ProvenanceSource(slug="eacea_emjm", role="funder_list"),
)
ASOIU = ListRow(
    external_key="az-hei-asoiu", name="Azerbaijan State Oil and Industry University (ADNSU)",
    kind="INSTITUTION", website="https://asoiu.edu.az/", page_url="", country_code="AZ",
    home_cells=("ANY",), host_cells=("AZ",), rejected_reason="",
    source_url="https://edu.gov.az/az/higher-education/ali-tehsil-muessiseleri",
    verified_on=date(2026, 9, 26),
)
ASOIU_PAGE = {"https://asoiu.edu.az/": page("https://asoiu.edu.az/", "<title>ADNSU</title>")}


def _asoiu() -> Organisation:
    record_list(make_list("az_heis", country_code="AZ"), (ASOIU,), now=timezone.now())
    return OrganisationDomain.objects.get(registrable_domain="asoiu.edu.az").organisation


def test_the_shipped_sources_parse_and_every_slug_has_a_registry_row() -> None:
    sources = read_sources()
    slugs = {str(spec["slug"]) for spec in read_registry()}
    assert {source.slug for source in sources} <= slugs
    assert {"az_heis", "az_outbound_gov", "az_bilateral", "tr_bilateral",
            "igo_regional_global", "national_scholarship_agencies"} <= {
        source.slug for source in sources if source.role == "curated_list"
    }
    assert {source.slug for source in sources if source.role == "funder_list"} == {"eacea_emjm"}


def test_the_agencies_list_names_the_six_funders_the_spec_names() -> None:
    spec = ClosedList(
        **next(s for s in read_registry() if s["slug"] == "national_scholarship_agencies")
    )
    websites = {row.website for row in read_list_file(spec)}
    assert websites == {
        "https://www.daad.de/", "https://www.campusfrance.org/", "https://si.se/",
        "https://www.chevening.org/", "https://stipendiumhungaricum.hu/",
        "https://www.campuschina.org/",
    }


@pytest.mark.parametrize(
    ("row", "error"),
    [
        ("nowhere,curated_list,,,,,,,,,,,,", "has no row in closed-lists.csv"),
        ("az_heis,a_rumour,,,,,,,,,,,,", "role"),
        ("az_heis,register,,,https://x.example.org/f.tsv,tsv,utf-8,,Name,Web,,,,",
         "ENIC-NARIC page or says why"),
        ("az_heis,register,,by hand,http://x.example.org/f.tsv,tsv,utf-8,,Name,Web,,,,", "https"),
        ("az_heis,register,,by hand,https://x.example.org/f,html_list,utf-8,,,,,,,", "list_anchor"),
        # A hand reason is only for a register with no ENIC-NARIC page.
        ("az_heis,register,https://www.enic-naric.net/page-Azerbaijan,by hand,"
         "https://x.example.org/f.tsv,tsv,utf-8,,Name,Web,,,,", "never both"),
    ],
)
def test_a_bad_sources_row_is_named_by_line(tmp_path: Path, row: str, error: str) -> None:
    path = tmp_path / "provenance-sources.csv"
    path.write_text(
        "slug,role,enic_naric_page,named_by_hand_because,data_url,format,encoding,"
        "records_path,name_field,website_field,id_field,id_scheme,list_anchor,max_bytes\n"
        + row + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SourceFileError, match=error):
        read_sources(path)


def test_record_list_stores_the_domain_it_bound_by_and_the_printed_website() -> None:
    _asoiu()
    entry = RegisterEntry.objects.get(external_key="az-hei-asoiu")
    assert (entry.website_domain, entry.website_url) == ("asoiu.edu.az", ASOIU.website)
    assert registrable_domain(entry.website_url) == entry.website_domain


def test_a_reviewed_row_counts_only_after_its_origin_names_the_institution() -> None:
    """Spec §13.8: az_heis's websites came from search, origin not fetched."""
    body = _asoiu()
    assert list_recognitions(body, CURATED) == ((), True)

    fetch = FakeFetch({"https://asoiu.edu.az/": page(
        "https://asoiu.edu.az/",
        "<html><title>ADNSU | Azərbaycan Dövlət Neft və Sənaye Universiteti</title></html>",
    )})
    assert verify_list_origins(["az_heis"], now=timezone.now(), fetch=fetch) == [
        ("az_heis", "az-hei-asoiu", "verified")
    ]
    found, unverified = list_recognitions(body, CURATED)
    assert [(r.reason, r.bound_domain, r.source_slug, r.list_date) for r in found] == [
        ("curated_list", "asoiu.edu.az", "az_heis", "2026-09-26")
    ]
    assert unverified is False
    assert verify_list_origins(["az_heis"], now=timezone.now(), fetch=FakeFetch({})) == [
        ("az_heis", "az-hei-asoiu", "already verified")
    ]


@pytest.mark.parametrize(
    ("fetched", "outcome"),
    [
        (page("https://asoiu.edu.az/", "<title>Domain for sale</title>"),
         "the page does not name the institution"),
        (page("https://asoiu.edu.az/", "<title>ADNSU</title>",
              final_url="https://parked-domains.com/lander"),
         "redirected off the listed domain to https://parked-domains.com/lander"),
    ],
)
def test_an_origin_that_does_not_confirm_the_row_leaves_it_unverified(fetched, outcome) -> None:
    body = _asoiu()
    fetch = FakeFetch({"https://asoiu.edu.az/": fetched})
    assert verify_list_origins(["az_heis"], now=timezone.now(), fetch=fetch) == [
        ("az_heis", "az-hei-asoiu", outcome)
    ]
    assert list_recognitions(body, CURATED) == ((), True)


def test_an_unreachable_origin_is_reported_not_verified() -> None:
    _asoiu()
    [(_, _, outcome)] = verify_list_origins(["az_heis"], now=timezone.now(), fetch=FakeFetch({}))
    assert outcome.startswith("not fetched (DEAD")


def test_a_changed_website_voids_the_verification() -> None:
    _asoiu()
    verify_list_origins(["az_heis"], now=timezone.now(), fetch=FakeFetch(ASOIU_PAGE))
    moved = replace(ASOIU, website="https://asoiu-new.az")
    record_list(ClosedList.objects.get(slug="az_heis"), (moved,), now=timezone.now())
    new_body = OrganisationDomain.objects.get(registrable_domain="asoiu-new.az").organisation
    assert list_recognitions(new_body, CURATED) == ((), True)


def test_a_renamed_row_must_be_verified_again() -> None:
    _asoiu()
    verify_list_origins(["az_heis"], now=timezone.now(), fetch=FakeFetch(ASOIU_PAGE))
    renamed = replace(ASOIU, name="Azerbaijan State Oil and Industry University (ASOIU)")
    record_list(ClosedList.objects.get(slug="az_heis"), (renamed,), now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="az-hei-asoiu")
    assert (entry.origin_verified_domain, entry.origin_verified_at) == ("", None)


def test_a_rejected_body_s_row_is_never_fetched() -> None:
    body = _asoiu()
    Organisation.objects.filter(pk=body.pk).update(status=Organisation.Status.REJECTED)
    fetch = FakeFetch(ASOIU_PAGE)
    assert verify_list_origins(["az_heis"], now=timezone.now(), fetch=fetch) == []
    assert fetch.calls == []


def test_a_row_the_resolver_bound_by_name_never_admits() -> None:
    """Ruling I6: only a row the list itself bound (LISTED) is evidence; the
    resolver's search-title and Wikidata routes are name matches."""
    body = _asoiu()
    verify_list_origins(["az_heis"], now=timezone.now(), fetch=FakeFetch(ASOIU_PAGE))
    RegisterEntry.objects.filter(external_key="az-hei-asoiu").update(resolved_via="SEARCH_TITLE")
    assert list_recognitions(body, CURATED) == ((), False)
    assert verify_list_origins(["az_heis"], now=timezone.now(), fetch=FakeFetch({})) == []


def test_a_row_recognises_only_the_body_of_its_own_website_domain() -> None:
    """Task 4's ruling: a row bound to this body whose website is another
    domain recognises that domain's body, never this one."""
    body = _asoiu()
    verify_list_origins(["az_heis"], now=timezone.now(), fetch=FakeFetch(ASOIU_PAGE))
    RegisterEntry.objects.filter(external_key="az-hei-asoiu").update(
        website_domain="elsewhere.az", origin_verified_domain="elsewhere.az"
    )
    assert list_recognitions(body, CURATED) == ((), False)


def test_daad_is_recognised_through_the_reviewed_agencies_list() -> None:
    row = ListRow(
        external_key="daad", name="Deutscher Akademischer Austauschdienst (DAAD)",
        kind="NATIONAL_GOVERNMENT", website="https://www.daad.de", page_url="",
        country_code="DE", home_cells=("ANY",), host_cells=("DE",), rejected_reason="",
        source_url="https://www.daad.de/de/", verified_on=date(2026, 9, 26),
    )
    record_list(
        make_list("national_scholarship_agencies", holder_kinds=("NATIONAL_GOVERNMENT",)),
        (row,), now=timezone.now(),
    )
    fetch = FakeFetch({"https://daad.de/": page(
        "https://daad.de/", "<title>Deutscher Akademischer Austauschdienst - DAAD</title>",
        final_url="https://www.daad.de/de/",
    )})
    outcomes = verify_list_origins(
        ["national_scholarship_agencies"], now=timezone.now(), fetch=fetch
    )
    assert outcomes[0][2] == "verified"
    body = OrganisationDomain.objects.get(registrable_domain="daad.de").organisation
    found, _ = list_recognitions(body, CURATED)
    assert [(r.reason, r.bound_domain) for r in found] == [("curated_list", "daad.de")]


def _agency(key: str, name: str, website: str) -> RegisterEntry:
    row = ListRow(
        external_key=key, name=name, kind="NATIONAL_GOVERNMENT", website=website, page_url="",
        country_code="DE", home_cells=("ANY",), host_cells=("DE",), rejected_reason="",
        source_url=website, verified_on=date(2026, 9, 26),
    )
    record_list(
        make_list("national_scholarship_agencies", holder_kinds=("NATIONAL_GOVERNMENT",)),
        (row,), now=timezone.now(),
    )
    return RegisterEntry.objects.get(external_key=key)


def test_a_www_only_site_verifies_through_the_printed_website() -> None:
    entry = _agency("daad", "Deutscher Akademischer Austauschdienst (DAAD)",
                    "https://www.daad.de/")
    fetch = FakeFetch({"https://www.daad.de/": page("https://www.daad.de/", "<b>DAAD</b>")})
    assert verify_list_origins(
        ["national_scholarship_agencies"], now=timezone.now(), fetch=fetch
    ) == [("national_scholarship_agencies", "daad", "verified")]
    assert fetch.calls == ["https://www.daad.de/"]
    entry.refresh_from_db()
    assert entry.origin_verified_domain == "daad.de"


def test_a_printed_website_that_leaves_the_domain_fails_without_a_fallback() -> None:
    _agency("daad", "Deutscher Akademischer Austauschdienst (DAAD)", "https://www.daad.de/")
    fetch = FakeFetch({
        "https://www.daad.de/": page("https://www.daad.de/", "<b>DAAD</b>",
                                     final_url="https://daad.example.com/"),
        "https://daad.de/": page("https://daad.de/", "<b>DAAD</b>"),
    })
    assert verify_list_origins(
        ["national_scholarship_agencies"], now=timezone.now(), fetch=fetch
    ) == [("national_scholarship_agencies", "daad",
           "redirected off the listed domain to https://daad.example.com/")]
    assert fetch.calls == ["https://www.daad.de/"]


@pytest.mark.parametrize(
    ("key", "name", "website", "parked"),
    [
        ("daad", "Deutscher Akademischer Austauschdienst (DAAD)", "https://www.daad.de/",
         "<title>daad.de is for sale</title><p>Buy DAAD.DE today at https://www.daad.de/</p>"),
        ("csc", "China Scholarship Council (CampusChina)", "https://www.campuschina.org/",
         "<title>CampusChina.org - this domain may be for sale</title>"),
    ],
)
def test_a_parked_page_that_prints_only_its_domain_stays_unverified(
    key: str, name: str, website: str, parked: str
) -> None:
    _agency(key, name, website)
    fetch = FakeFetch({website: page(website, parked)})
    assert verify_list_origins(
        ["national_scholarship_agencies"], now=timezone.now(), fetch=fetch
    ) == [("national_scholarship_agencies", key, "the page does not name the institution")]


def test_names_match_as_folded_whole_words() -> None:
    entry = RegisterEntry(website_domain="bsu.edu.az", name="Bakı Dövlət Universiteti (BDU)")
    assert names_institution(entry, "<h1>BAKI DÖVLƏT UNİVERSİTETİ</h1>".encode())
    asoiu = RegisterEntry(website_domain="asoiu.edu.az", name=ASOIU.name)
    assert not names_institution(asoiu, b"<title>ADNSUNET portal</title>")
    assert names_institution(asoiu, b"<title>ADNSU portal</title>")


def test_a_lookalike_funder_binds_to_nothing() -> None:
    body = make_body("daad-scholarships.org", kind="PRIVATE_FOUNDATION")
    assert list_recognitions(body, CURATED) == ((), False)
    assert government_zone("daad-scholarships.org") is None


def test_an_eacea_partner_is_a_funder_list_body_keyed_by_its_pic() -> None:
    body = make_body("unibo.it")
    entry = RegisterEntry.objects.create(
        register="eacea_emjm", external_key="101", name="EMJM X", resolution="RESOLVED",
        resolved_via="LISTED", last_seen=timezone.now(),
    )
    RegisterEntryPartner.objects.create(
        entry=entry, organisation=body, role="PARTNER", listed_name="Università di Bologna",
        listed_identifier="999880560", listed_domain="unibo.it", disposition="BOUND_BOTH",
    )
    other = make_body("conflict.it")
    RegisterEntryPartner.objects.create(
        entry=entry, organisation=None, role="PARTNER", listed_name="Conflict",
        listed_identifier="1", listed_domain="conflict.it", disposition="CONFLICT",
    )
    found, _ = list_recognitions(body, CURATED)
    assert [(r.reason, r.bound_domain, r.identifier) for r in found] == [
        ("funder_list", "unibo.it", ("EACEA_PIC", "999880560"))
    ]
    assert list_recognitions(other, CURATED) == ((), False)


def test_an_eacea_partner_on_another_domain_gives_this_body_nothing() -> None:
    body = make_body("unibo.it")
    entry = RegisterEntry.objects.create(
        register="eacea_emjm", external_key="102", name="EMJM Y", resolution="RESOLVED",
        resolved_via="LISTED", last_seen=timezone.now(),
    )
    RegisterEntryPartner.objects.create(
        entry=entry, organisation=body, role="PARTNER", listed_name="Università di Bologna",
        listed_identifier="999880560", listed_domain="unibo-partner.eu",
        disposition="BOUND_BOTH",
    )
    assert list_recognitions(body, CURATED) == ((), False)


@pytest.mark.parametrize(
    ("domain", "zone"),
    [
        ("studyinkorea.go.kr", "go.kr"),
        ("mext.go.jp", "go.jp"),
        ("ed.gov", "gov"),
        ("turkiyeburslari.gov.tr", "gov.tr"),
        ("europa.eu", "europa.eu"),
        ("auswaertiges-amt.de", "auswaertiges-amt.de"),
    ],
)
def test_a_government_zone_recognises_a_funder(domain: str, zone: str) -> None:
    recognition = government_zone(domain)
    assert recognition is not None
    assert (recognition.reason, recognition.bound_domain, recognition.source_slug) == (
        "government_zone", domain, f"zone:{zone}",
    )


@pytest.mark.parametrize("domain", ["gov.example.com", "govscholarships.com", "gov-az.org"])
def test_a_gov_pattern_alone_is_never_proof(domain: str) -> None:
    assert government_zone(domain) is None


def test_every_zone_cites_its_registry_policy() -> None:
    assert GOVERNMENT_ZONES
    # gov.za's registry page is served over http only; every other zone is https.
    assert all(
        citation.startswith("https://") or zone == "gov.za"
        for zone, citation in GOVERNMENT_ZONES
    )
    assert all(citation.startswith(("https://", "http://")) for _zone, citation in GOVERNMENT_ZONES)


def test_name_variants() -> None:
    assert name_variants("Azerbaijan State Oil and Industry University (ADNSU)") == (
        "azerbaijan state oil and industry university", "adnsu",
    )


def test_the_command_reports_each_row(monkeypatch) -> None:
    _asoiu()
    monkeypatch.setattr(
        "apps.research.recognition.fetch_page",
        FakeFetch({"https://asoiu.edu.az/": page("https://asoiu.edu.az/", "<b>ADNSU</b>")}),
    )
    out = StringIO()
    call_command("verify_list_origins", "--list", "az_heis", stdout=out)
    assert "az_heis az-hei-asoiu: verified" in out.getvalue()


_GOVERNMENT_KINDS = {"NATIONAL_GOVERNMENT", "SUBNATIONAL_GOVERNMENT"}


@pytest.mark.parametrize(
    "host", ["edu.gov.az", "www.gov.uk", "moe.gov.sa", "mofa.gov.qa", "moe.gov.sg"]
)
def test_launch_government_hosts_are_in_a_cited_zone(host: str) -> None:
    zone = government_zone(host)
    assert zone is not None and zone.reason == "government_zone"
    assert zone.source_url.startswith(("https://", "http://"))


def test_every_cited_zone_that_labels_a_kind_labels_a_government_kind() -> None:
    for zone, _citation in GOVERNMENT_ZONES:
        if zone in VERIFIED_SECOND_LEVEL:
            assert VERIFIED_SECOND_LEVEL[zone] in _GOVERNMENT_KINDS, zone


def test_every_government_kind_suffix_is_cited_or_named_as_kind_only() -> None:
    """One list: a government suffix that labels a holder kind either proves a
    site (cited in GOVERNMENT_ZONES) or is named as a label that proves nothing."""
    cited = {zone for zone, _ in GOVERNMENT_ZONES}
    for suffix, kind in VERIFIED_SECOND_LEVEL.items():
        if kind in _GOVERNMENT_KINDS:
            assert (suffix in cited) != (suffix in KIND_ONLY_GOVERNMENT_SUFFIXES), suffix


def test_a_zone_never_admits_a_lookalike_suffix() -> None:
    assert government_zone("gov.az.example.com") is None
    assert government_zone("notgov.uk") is None
