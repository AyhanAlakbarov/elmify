"""The closed-list engine: registry, rows, register writes, lead source.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
sections 6.1, 6.2, 16 item 7.
"""

from datetime import date
from pathlib import Path

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.research.models import ClosedList, Organisation, RegisterEntry, RegisterEntryPartner

pytestmark = pytest.mark.django_db


def _list(**overrides: object) -> ClosedList:
    fields: dict[str, object] = dict(
        slug="igo_regional_global", title="Intergovernmental and regional funds",
        country_code="", holder_kinds=["INTERGOVERNMENTAL", "REGIONAL_FUND"], rung=1,
        source_url="https://github.com/0rkhann/tehsil_agent/blob/master/docs/research/closed-lists/igo_regional_global.csv",
        maintainer="own compilation", carries_purpose=True, carries_website=True,
        reuse_terms=ClosedList.Terms.OWN_COMPILATION, is_denominator=True,
        read_policy=ClosedList.ReadPolicy.FUNDING_READ, verified_on=date(2026, 9, 25),
    )
    fields.update(overrides)
    return ClosedList.objects.create(**fields)


def test_a_list_rung_is_zero_to_four() -> None:
    """0 = an enumerator that is not a ladder rung (Wikidata, ROR); 1-4 = §6.2's rungs."""
    _list(slug="ok", rung=0)
    with pytest.raises(IntegrityError), transaction.atomic():
        _list(slug="bad", rung=5)


def test_a_list_covers_only_holder_kinds() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _list(slug="bad", holder_kinds=["UNIVERSITY"])


def test_an_entry_kind_is_a_holder_kind_or_blank() -> None:
    now = timezone.now()
    RegisterEntry.objects.create(
        register="x", external_key="a", name="A", resolution="UNRESOLVED", last_seen=now,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RegisterEntry.objects.create(
            register="x", external_key="b", name="B", kind="UNIVERSITY",
            resolution="UNRESOLVED", last_seen=now,
        )


def test_a_partner_row_is_bound_exactly_when_its_disposition_says_so() -> None:
    entry = RegisterEntry.objects.create(
        register="eacea_emjm", external_key="p1", name="EMJM X",
        resolution="UNRESOLVED", last_seen=timezone.now(),
    )
    RegisterEntryPartner.objects.create(
        entry=entry, role="PARTNER", listed_name="NGO", listed_identifier="999",
        disposition=RegisterEntryPartner.Disposition.NO_KEY,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RegisterEntryPartner.objects.create(
            entry=entry, role="PARTNER", listed_name="Bound?", listed_identifier="998",
            disposition=RegisterEntryPartner.Disposition.BOUND_PIC,
        )


_REGISTRY_HEADER = (
    "slug,title,country_code,holder_kinds,rung,source_url,maintainer,carries_purpose,"
    "carries_website,reuse_terms,reuse_terms_url,is_denominator,read_policy,printed_size,"
    "verified_on\n"
)
_LIST_HEADER = (
    "external_key,name,kind,website,page_url,country_code,home_cells,host_cells,"
    "rejected_reason,source_url,verified_on,notes\n"
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_registry_loads_one_row_per_list(tmp_path: Path) -> None:
    from apps.research.closed_lists import load_registry

    path = _write(tmp_path, "closed-lists.csv", _REGISTRY_HEADER + (
        "igo_regional_global,IGO,,INTERGOVERNMENTAL|REGIONAL_FUND,1,"
        "https://example.org/list,own,yes,yes,OWN_COMPILATION,,yes,FUNDING_READ,,2026-09-25\n"
    ))
    assert load_registry(path) == 1
    spec = ClosedList.objects.get(slug="igo_regional_global")
    assert spec.holder_kinds == ["INTERGOVERNMENTAL", "REGIONAL_FUND"]
    assert spec.printed_size is None and spec.is_denominator


def test_the_registry_refuses_a_wrong_header(tmp_path: Path) -> None:
    from apps.research.closed_lists import ListFileError, read_registry

    path = _write(tmp_path, "closed-lists.csv", "slug,title\nx,y\n")
    with pytest.raises(ListFileError, match="columns"):
        read_registry(path)


@pytest.mark.parametrize(
    ("token", "valid"),
    [("ANY", True), ("TR", True), ("EU", True), ("AFRICAN_UNION", True),
     ("tr", False), ("TUR", False), ("Europe", False), ("", False)],
)
def test_a_cell_tag_is_iso2_a_region_or_any(token: str, valid: bool) -> None:
    from apps.research.closed_lists import valid_cell

    assert valid_cell(token) is valid


def _spec(**overrides: object) -> ClosedList:
    return _list(**overrides)


def test_a_list_file_refuses_an_email_address(tmp_path: Path) -> None:
    """A mailbox is not what this file is for, and a committed file is storage."""
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "wb,World Bank JJ/WBGSP,INTERGOVERNMENTAL,https://www.worldbank.org,"
        "https://www.worldbank.org/en/programs/scholarships,,ANY,ANY,,"
        "https://www.worldbank.org/en/programs/scholarships,2026-09-25,write to x@worldbank.org\n"
    ))
    with pytest.raises(ListFileError, match="e-mail"):
        read_list_file(spec, path)


def test_a_scheme_page_must_sit_on_the_bodys_own_site(tmp_path: Path) -> None:
    """The origin is the only evidence (spec 3.2): a page on someone else's
    host would be read as that someone's money."""
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "adb,ADB-Japan Scholarship,INTERGOVERNMENTAL,https://www.adb.org,"
        "https://www.someuniversity.edu/adb-jsp,,ANY,ANY,,https://www.adb.org,2026-09-25,\n"
    ))
    with pytest.raises(ListFileError, match="own site"):
        read_list_file(spec, path)


def test_a_funding_read_list_row_needs_a_page(tmp_path: Path) -> None:
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "wb,World Bank,INTERGOVERNMENTAL,https://www.worldbank.org,,,ANY,ANY,,"
        "https://www.worldbank.org,2026-09-25,\n"
    ))
    with pytest.raises(ListFileError, match="page_url"):
        read_list_file(spec, path)


def test_a_row_kind_must_be_one_the_list_covers(tmp_path: Path) -> None:
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "x,X Bank,BANK_OR_LENDER,https://x.example.org,https://x.example.org/s,,ANY,ANY,,"
        "https://x.example.org,2026-09-25,\n"
    ))
    with pytest.raises(ListFileError, match="covers"):
        read_list_file(spec, path)


def _rows(tmp_path: Path, spec: ClosedList, body: str):
    from apps.research.closed_lists import read_list_file

    return read_list_file(spec, _write(tmp_path, f"{spec.slug}.csv", _LIST_HEADER + body))


def test_a_curated_list_registers_what_it_names(tmp_path: Path) -> None:
    from apps.research.closed_lists import record_list

    spec = _spec()
    rows = _rows(tmp_path, spec, (
        "wb-jjwbgsp,Joint Japan/World Bank Graduate Scholarship Program,INTERGOVERNMENTAL,"
        "https://www.worldbank.org,https://www.worldbank.org/en/programs/scholarships,,"
        "ANY,ANY,,https://www.worldbank.org/en/programs/scholarships,2026-09-25,\n"
    ))
    report = record_list(spec, rows, now=timezone.now())
    assert (report.listed, report.bound, report.organisations_new) == (1, 1, 1)
    entry = RegisterEntry.objects.get(register=spec.slug)
    org = entry.organisation
    assert org is not None and org.primary_domain == "worldbank.org"
    assert org.status == Organisation.Status.REGISTERED
    assert org.found_via == ["R1_LIST:igo_regional_global"]
    assert entry.home_cells == ["ANY"] and entry.kind == "INTERGOVERNMENTAL"


def test_a_curated_list_promotes_a_candidate_another_route_found(tmp_path: Path) -> None:
    """record_organisation never overwrites status -- rightly, for routes that
    vouch for nothing. A curated list vouches, so it upgrades, and only upward."""
    from apps.research.closed_lists import record_list
    from apps.research.register import record_organisation

    record_organisation(
        domain="isdb.org", name="isdb.org", kind="UNSTATED", country_code="",
        found_via="R4_SEARCH:exa",
    )
    spec = _spec()
    rows = _rows(tmp_path, spec, (
        "isdb-scholarship,IsDB Scholarship Programme,INTERGOVERNMENTAL,https://www.isdb.org,"
        "https://www.isdb.org/scholarships,SA,ANY,ANY,,https://www.isdb.org/scholarships,"
        "2026-09-25,\n"
    ))
    report = record_list(spec, rows, now=timezone.now())
    org = Organisation.objects.get(primary_domain="isdb.org")
    assert report.promoted == 1
    assert (org.status, org.kind, org.country_code) == ("REGISTERED", "INTERGOVERNMENTAL", "SA")
    assert org.found_via == ["R4_SEARCH:exa", "R1_LIST:igo_regional_global"]


def test_a_named_body_that_funds_no_masters_student_is_recorded_rejected(tmp_path: Path) -> None:
    """A body the owner named whose own page shows no master's award is kept,
    REJECTED with a reason and its page as source -- never silently dropped."""
    from apps.research.closed_lists import record_list

    spec = _spec()
    rows = _rows(tmp_path, spec, (
        "eea-grants,EEA Grants,REGIONAL_FUND,https://eeagrants.org,,,ANY,ANY,NOT_A_FUNDER,"
        "https://eeagrants.org/topics-programmes,2026-09-25,funds national programmes only\n"
    ))
    record_list(spec, rows, now=timezone.now())
    org = RegisterEntry.objects.get(external_key="eea-grants").organisation
    assert org is not None and org.status == "REJECTED" and org.rejected_reason == "NOT_A_FUNDER"


def test_reloading_a_list_is_idempotent(tmp_path: Path) -> None:
    from apps.research.closed_lists import record_list

    spec = _spec()
    body = (
        "wb-jjwbgsp,JJ/WBGSP,INTERGOVERNMENTAL,https://www.worldbank.org,"
        "https://www.worldbank.org/en/programs/scholarships,,ANY,ANY,,"
        "https://www.worldbank.org/en/programs/scholarships,2026-09-25,\n"
    )
    record_list(spec, _rows(tmp_path, spec, body), now=timezone.now())
    second = record_list(spec, _rows(tmp_path, spec, body), now=timezone.now())
    assert (second.organisations_new, RegisterEntry.objects.count()) == (0, 1)
    assert Organisation.objects.get().found_via == ["R1_LIST:igo_regional_global"]


def test_the_source_yields_funder_leads_for_scheme_pages_only(tmp_path: Path) -> None:
    from apps.research.closed_lists import ClosedListSource, record_list
    from apps.research.discovery import DiscoveryQuery

    spec = _spec()
    rows = _rows(tmp_path, spec, (
        "wb,JJ/WBGSP,INTERGOVERNMENTAL,https://www.worldbank.org,"
        "https://www.worldbank.org/en/programs/scholarships,,ANY,ANY,,"
        "https://www.worldbank.org,2026-09-25,\n"
        "eea,EEA Grants,REGIONAL_FUND,https://eeagrants.org,,,ANY,ANY,NOT_A_FUNDER,"
        "https://eeagrants.org,2026-09-25,\n"
    ))
    record_list(spec, rows, now=timezone.now())
    leads = list(ClosedListSource(spec.slug).find(DiscoveryQuery(field="x", country_code="AZ")))
    assert [lead.canonical_url for lead in leads] == [
        "https://www.worldbank.org/en/programs/scholarships"
    ]
    assert leads[0].source_type == "FUNDER" and leads[0].funding_family == "MULTILATERAL"


def test_a_signal_only_list_yields_nothing_without_a_signal(tmp_path: Path) -> None:
    """Owner, 2026-09-23: a licensed-lender list is the denominator, never the
    reading queue. Nothing tags an Organisation with POINTER: today, so every
    bank reads GATED -- which is the rule, not a gap."""
    from apps.research.closed_lists import ClosedListSource, record_list
    from apps.research.discovery import DiscoveryQuery

    spec = _spec(
        slug="tr_banks", country_code="TR", holder_kinds=["BANK_OR_LENDER"], rung=2,
        read_policy=ClosedList.ReadPolicy.SIGNAL_ONLY,
    )
    rows = _rows(tmp_path, spec, (
        "b1,Örnek Bankası,BANK_OR_LENDER,https://www.ornekbank.com.tr,"
        "https://www.ornekbank.com.tr/burs,TR,TR,ANY,,https://www.bddk.org.tr,2026-09-25,\n"
    ))
    record_list(spec, rows, now=timezone.now())
    source = ClosedListSource(spec.slug)
    assert list(source.find(DiscoveryQuery(field="x", country_code="TR"))) == []
    org = Organisation.objects.get(primary_domain="ornekbank.com.tr")
    org.found_via = [*org.found_via, "POINTER:tev.org.tr"]
    org.save(update_fields=["found_via"])
    assert len(list(source.find(DiscoveryQuery(field="x", country_code="TR")))) == 1


def test_a_body_whose_site_is_not_established_stays_unresolved(tmp_path: Path) -> None:
    """Never guess a domain from a name (Task 8): a blank website is kept, in
    the denominator, and reads UNBOUND until the resolver finds it."""
    from apps.research.closed_lists import read_list_file, record_list

    spec = _spec(slug="tr_heis", country_code="TR", holder_kinds=["INSTITUTION"], rung=2,
                 read_policy=ClosedList.ReadPolicy.CLASSIFY)
    rows = read_list_file(spec, _write(tmp_path, "tr_heis.csv", _LIST_HEADER + (
        "x-uni,X Üniversitesi,INSTITUTION,,,TR,ANY,TR,,https://www.yok.gov.tr/,2026-09-25,\n"
    )))
    report = record_list(spec, rows, now=timezone.now())
    assert (report.listed, report.unresolved, report.bound) == (1, 1, 0)
    assert RegisterEntry.objects.get(external_key="x-uni").organisation is None


def test_a_rejected_row_needs_the_bodys_website(tmp_path: Path) -> None:
    """REJECTED is recorded on a body; with no website there is none, and the
    row would read UNBOUND forever instead of REJECTED."""
    from apps.research.closed_lists import ListFileError, read_list_file

    spec = _spec()
    path = _write(tmp_path, "igo.csv", _LIST_HEADER + (
        "eea,EEA Grants,REGIONAL_FUND,,,,ANY,ANY,NOT_A_FUNDER,https://eeagrants.org,"
        "2026-09-25,\n"
    ))
    with pytest.raises(ListFileError, match="website"):
        read_list_file(spec, path)


def test_a_row_whose_website_is_removed_drops_its_old_body(tmp_path: Path) -> None:
    from apps.research.closed_lists import record_list

    spec = _spec(slug="tr_banks", country_code="TR", holder_kinds=["BANK_OR_LENDER"], rung=2,
                 read_policy=ClosedList.ReadPolicy.SIGNAL_ONLY)
    line = "b1,Örnek Bankası,BANK_OR_LENDER,{site},,TR,TR,ANY,,https://www.bddk.org.tr,2026-09-25,\n"
    record_list(spec, _rows(tmp_path, spec, line.format(site="https://www.ornekbank.com.tr")),
                now=timezone.now())
    record_list(spec, _rows(tmp_path, spec, line.format(site="")), now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="b1")
    assert (entry.resolution, entry.organisation) == ("UNRESOLVED", None)


def test_a_bad_number_in_the_registry_is_a_list_file_error(tmp_path: Path) -> None:
    from apps.research.closed_lists import ListFileError, read_registry

    path = _write(tmp_path, "closed-lists.csv", _REGISTRY_HEADER + (
        "x,X,,INTERGOVERNMENTAL,one,https://example.org/list,own,yes,yes,OWN_COMPILATION,,"
        "yes,FUNDING_READ,,2026-09-25\n"
    ))
    with pytest.raises(ListFileError, match="rung"):
        read_registry(path)


# --- The resolver's record (build item 8, Task 6). ---

_BANKS = dict(slug="tr_banks", country_code="TR", holder_kinds=["BANK_OR_LENDER"], rung=2,
              read_policy=ClosedList.ReadPolicy.SIGNAL_ONLY)
_BANK = "b1,Örnek Bankası,BANK_OR_LENDER,{site},,TR,TR,ANY,,https://www.bddk.org.tr,2026-09-25,\n"


def test_a_row_the_list_binds_says_the_list_bound_it(tmp_path: Path) -> None:
    from apps.research.closed_lists import record_list

    spec = _spec(**_BANKS)
    record_list(spec, _rows(tmp_path, spec, _BANK.format(site="https://www.ornekbank.com.tr")),
                now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="b1")
    assert (entry.resolution, entry.resolved_via, entry.unresolved_reason) == (
        "RESOLVED", "LISTED", "")
    assert entry.names == ["Örnek Bankası"]


def test_a_removed_website_clears_the_list_s_route_in_the_same_write(tmp_path: Path) -> None:
    from apps.research.closed_lists import record_list

    spec = _spec(**_BANKS)
    record_list(spec, _rows(tmp_path, spec, _BANK.format(site="https://www.ornekbank.com.tr")),
                now=timezone.now())
    record_list(spec, _rows(tmp_path, spec, _BANK.format(site="")), now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="b1")
    assert (entry.resolution, entry.resolved_via, entry.organisation) == ("UNRESOLVED", "", None)


def test_a_re_read_never_undoes_what_the_resolver_bound(tmp_path: Path) -> None:
    """The blank website is why the resolver ran; the list saying nothing
    again is no evidence against what it found."""
    from apps.research.closed_lists import record_list
    from apps.research.register import record_organisation

    spec = _spec(**_BANKS)
    blank = _rows(tmp_path, spec, _BANK.format(site=""))
    record_list(spec, blank, now=timezone.now())
    org = record_organisation(domain="ornekbank.com.tr", name="Örnek Bankası",
                              kind="BANK_OR_LENDER", country_code="TR",
                              found_via="RESOLVER:SEARCH_TITLE")
    RegisterEntry.objects.filter(external_key="b1").update(
        resolution="RESOLVED", resolved_via="SEARCH_TITLE", organisation=org)
    report = record_list(spec, blank, now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="b1")
    assert (entry.resolution, entry.resolved_via, entry.organisation_id) == (
        "RESOLVED", "SEARCH_TITLE", org.pk)
    assert report.unresolved == 1  # "this list did not bind it", as before


def test_a_website_the_list_gains_outranks_the_resolver(tmp_path: Path) -> None:
    from apps.research.closed_lists import record_list

    spec = _spec(**_BANKS)
    record_list(spec, _rows(tmp_path, spec, _BANK.format(site="")), now=timezone.now())
    RegisterEntry.objects.filter(external_key="b1").update(unresolved_reason="NO_CANDIDATE")
    record_list(spec, _rows(tmp_path, spec, _BANK.format(site="https://www.ornekbank.com.tr")),
                now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="b1")
    assert (entry.resolution, entry.resolved_via, entry.unresolved_reason) == (
        "RESOLVED", "LISTED", "")


def test_a_renamed_row_drops_what_the_resolver_found_for_the_old_name(tmp_path: Path) -> None:
    """Review of Task 6: the resolver checked a title against the OLD name."""
    from apps.research.closed_lists import record_list
    from apps.research.register import record_organisation

    spec = _spec(**_BANKS)
    record_list(spec, _rows(tmp_path, spec, _BANK.format(site="")), now=timezone.now())
    org = record_organisation(domain="ornekbank.com.tr", name="Örnek Bankası",
                              kind="BANK_OR_LENDER", country_code="TR",
                              found_via="RESOLVER:SEARCH_TITLE")
    RegisterEntry.objects.filter(external_key="b1").update(
        resolution="RESOLVED", resolved_via="SEARCH_TITLE", organisation=org,
        names=["Örnek Bankası", "Ornek Bank"], resolution_attempted_at=timezone.now())
    renamed = _BANK.format(site="").replace("Örnek Bankası", "Yeni Örnek Bankası")
    record_list(spec, _rows(tmp_path, spec, renamed), now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="b1")
    assert (entry.resolution, entry.resolved_via, entry.organisation) == ("UNRESOLVED", "", None)
    assert entry.names == ["Yeni Örnek Bankası"]
    assert entry.resolution_attempted_at is None
