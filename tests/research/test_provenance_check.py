"""provenance_check end to end, with every transport faked (spec §7.1, §11's
known-answer set). The job holds no tenant transaction and calls no model on
the admit path."""

from datetime import UTC, date, datetime, timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from apps.funding.models import FundingOpportunity, FundingOpportunityEvidenceClaim
from apps.research import provenance_job
from apps.research.blocking import read_mill_list
from apps.research.closed_lists import ListRow, record_list
from apps.research.egress import FetchResult, SourceBlocked
from apps.research.models import (
    ClosedList,
    Organisation,
    OrganisationDomain,
    ProvenanceVerdict,
    RegisterEntry,
)
from apps.research.provenance import WAITING_REASONS, Decision
from apps.research.provenance_job import (
    Deps,
    bodies_in_play,
    check_body,
    due,
    next_check,
    run_checks,
)
from apps.research.recognition import (
    ProvenanceSource,
    list_recognitions,
    load_register,
    read_sources,
)
from apps.research.register import record_organisation
from apps.research.services import acquire_domain_lease
from tests.research.provenance_helpers import (
    FakeFetch,
    FakeStore,
    HomeFetch,
    SiteFetch,
    attach_snapshot,
    evidence_program,
    make_body,
    make_list,
    page,
    recognise,
)
from tests.research.test_blocking import DIPLOMA_SALE, FEE_RELEASE
from tests.research.test_provenance_registers import (
    ENIC_DE_URL,
    ENIC_GERMANY,
    HRK,
    HRK_DOWNLOADS,
    HRK_DOWNLOADS_URL,
    HRK_TSV,
    KR_JSON,
    KR_LIST_URL,
    SFC,
    SFC_HTML,
    SFC_URL,
    YOK,
    YOK_FOUNDATION,
    YOK_FOUNDATION_HTML,
    YOK_FOUNDATION_URL,
    YOK_HTML,
    YOK_URL,
)
from tests.research.test_rdap import ESMT
from tests.research.test_vouch import ASOIU, ASOIU_HOME, UFAZ, UFAZ_HOME

pytestmark = pytest.mark.django_db
NOW = timezone.now()
QUIET = "<html><body><h1>Home</h1></body></html>"


def _ror(**records):
    def call(url, *, params, headers):
        domain = params["query.advanced"].removeprefix("domains:")
        return {"items": [records[domain]] if domain in records else []}
    return call


def _record(domain: str, country: str) -> dict:
    return {"id": f"https://ror.org/{uuid4().hex[:9]}", "domains": [domain], "links": [],
            "locations": [{"geonames_details": {"country_code": country}}]}


class Files:
    def __init__(self, bodies: dict[str, bytes] | None = None) -> None:
        self.bodies = bodies or {}

    def __call__(self, url: str, **_kwargs: object) -> FetchResult:
        if url not in self.bodies:
            raise SourceBlocked("source returned HTTP 404")
        return FetchResult(url, (), "application/rdap+json", self.bodies[url])


def _deps(**overrides) -> Deps:
    fields = dict(
        fetch=FakeFetch({}), fetch_file=Files(), ror_call=_ror(), jev_post=_no_jev,
        store=FakeStore(), sources=(), mill_rows=(), bootstrap={},
    )
    fields.update(overrides)
    return Deps(**fields)


def _no_jev(url, *, payload, headers):
    raise AssertionError("no model call was expected")


def _register(
    slug: str, country: str, *websites: str, unbound: str = "", origin_verified: bool = True
) -> ProvenanceSource:
    spec = make_list(slug, country_code=country)
    rows = tuple(
        ListRow(external_key=w, name=w, kind="INSTITUTION", website=f"https://{w}", page_url="",
                country_code=country, home_cells=("ANY",), host_cells=(country,),
                rejected_reason="", source_url=spec.source_url, verified_on=date(2026, 9, 26))
        for w in websites
    )
    record_list(spec, rows, now=NOW)
    if origin_verified:
        for w in websites:
            RegisterEntry.objects.filter(register=slug, website_domain=w).update(
                origin_verified_domain=w, origin_verified_at=NOW
            )
    if unbound:
        RegisterEntry.objects.create(register=slug, external_key=unbound, name=unbound,
                                     resolution="UNRESOLVED", last_seen=NOW)
    ClosedList.objects.filter(slug=slug).update(loaded_at=NOW)
    return ProvenanceSource(slug=slug, role="register", named_by_hand_because="test")


def _verdict(
    domain: str, deps: Deps, *, country: str = "", kind: str = "INSTITUTION"
) -> ProvenanceVerdict:
    body = Organisation.objects.filter(domains__registrable_domain=domain).first() or make_body(
        domain, kind=kind, country_code=country
    )
    return check_body(body, domain, now=NOW, deps=deps)


def _germany_deps(**overrides) -> Deps:
    make_list("de_hochschulkompass", country_code="DE", source_url=HRK_DOWNLOADS_URL)
    fields = dict(
        ror_call=_ror(**{"tum.de": _record("tum.de", "DE")}),
        fetch=HomeFetch({ENIC_DE_URL: page(ENIC_DE_URL, ENIC_GERMANY),
                         HRK_DOWNLOADS_URL: page(HRK_DOWNLOADS_URL, HRK_DOWNLOADS)},
                        homes=frozenset({"tum.de"})),
        fetch_file=Files({HRK.data_url: HRK_TSV}), sources=(HRK,), load=load_register,
    )
    fields.update(overrides)
    return _deps(**fields)


def test_tum_is_recognised_after_loading_germanys_register(settings) -> None:
    settings.JEV_API_KEY = ""
    verdict = _verdict("tum.de", _germany_deps())
    assert (verdict.verdict, verdict.reason_code, verdict.domain) == (
        "RECOGNISED", "register", "tum.de",
    )
    assert verdict.evidence["content_checks"] == "skipped"
    assert verdict.next_check_at is None


def test_edinburgh_is_recognised_via_the_sfc_list() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    deps = _deps(
        ror_call=_ror(**{"ed.ac.uk": _record("ed.ac.uk", "GB")}),
        fetch=HomeFetch({SFC_URL: page(SFC_URL, SFC_HTML)}, homes=frozenset({"ed.ac.uk"})),
        sources=(SFC,), load=load_register,
    )
    assert _verdict("ed.ac.uk", deps).reason_code == "register"


def test_ufaz_is_recognised_by_asoius_structural_link() -> None:
    recognise(make_body("asoiu.edu.az", country_code="AZ"), "asoiu.edu.az", "curated_list")
    deps = _deps(fetch=FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, ASOIU_HOME)}))
    verdict = _verdict("ufaz.az", deps)
    assert (verdict.reason_code, verdict.evidence["admitted_via"]) == (
        "vouched_by_link", "asoiu.edu.az",
    )


def test_nyenrode_is_unbound_while_its_register_row_has_no_website() -> None:
    source = _register("nl_register", "NL", "uva.nl", unbound="Nyenrode Business Universiteit")
    deps = _deps(sources=(source,),
                 fetch=FakeFetch({"https://nyenrode.nl/": page("https://nyenrode.nl/", QUIET)}))
    assert _verdict("nyenrode.nl", deps, country="NL").reason_code == "no_domain_binding"


def test_a_free_zone_branch_missing_from_the_federal_register_is_absent_not_blocked() -> None:
    source = _register("ae_register", "AE", "uaeu.ac.ae")
    url = "https://branch-campus-dubai.ae/"
    verdict = _verdict("branch-campus-dubai.ae",
                       _deps(sources=(source,), fetch=FakeFetch({url: page(url, QUIET)})),
                       country="AE")
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "absent_from_register")


def test_a_rebranded_or_taken_over_domain_is_unconfirmed() -> None:
    source = _register("de_register", "DE", "esmt.berlin")
    body = Organisation.objects.get(domains__registrable_domain="esmt.berlin")
    recognise(body, "esmt.berlin", now=datetime(2015, 1, 1, tzinfo=UTC))
    deps = _deps(sources=(source,), bootstrap={"berlin": "https://rdap.nic.berlin/v1/"},
                 fetch_file=Files({"https://rdap.nic.berlin/v1/domain/esmt.berlin": ESMT}))
    verdict = check_body(body, "esmt.berlin", now=NOW, deps=deps)
    assert verdict.reason_code == "domain_registered_after_listing"
    assert verdict.evidence["rdap"]["date"] == "2016-06-06"


@pytest.mark.parametrize(
    "domain",
    ["bircham.edu", "aiu.edu", "warnborough.ac.uk", "iiu-edu.eu", "breyerstate.com", "awuedu.org"],
)
def test_a_mill_is_blocked_by_its_domain(domain: str) -> None:
    verdict = _verdict(domain, _deps(mill_rows=read_mill_list()))
    assert (verdict.verdict, verdict.reason_code, verdict.next_check_at) == (
        "BLOCKED", "mill_list", None,
    )


def test_a_real_business_school_with_vendor_wording_is_a_conflict_not_a_block(settings) -> None:
    settings.JEV_API_KEY = "k"
    source = _register("de_register", "DE", "business-school-fixture.de")
    store = FakeStore()
    program = evidence_program("https://www.business-school-fixture.de/mba")
    attach_snapshot(program.evidence_claims.get(), DIPLOMA_SALE, store)

    def jev(url, *, payload, headers):
        return {"model": "typesafe/jev-1.13.0",
                "answers": {f"s{i}": {"noul": 0.95}
                            for i in range(len(payload["state"]["sentences"]))}}

    verdict = _verdict("business-school-fixture.de",
                       _deps(sources=(source,), store=store, jev_post=jev))
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "veto_conflict")


def test_a_fee_to_release_an_award_blocks_an_unrecognised_funder(settings) -> None:
    settings.JEV_API_KEY = "k"
    body = make_body("grants-fixture-foundation.com", kind="PRIVATE_FOUNDATION")
    award = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}", name="Grant", family="PRIVATE_FOUNDATION",
        scope_type="HOLDER", organisation=body, holder_domain="grants-fixture-foundation.com",
        served=True,
    )
    claim = evidence_program("https://grants-fixture-foundation.com/grant").evidence_claims.get()
    FundingOpportunityEvidenceClaim.objects.create(opportunity=award, evidence_claim=claim)
    store = FakeStore()
    attach_snapshot(claim, FEE_RELEASE, store)

    def jev(url, *, payload, headers):
        return {"model": "jev-1.13", "answers": {"s0": {"noul": 0.97}}}

    url = "https://grants-fixture-foundation.com/"
    verdict = check_body(body, "grants-fixture-foundation.com", now=NOW,
                         deps=_deps(store=store, jev_post=jev,
                                    fetch=FakeFetch({url: page(url, QUIET)})))
    assert (verdict.verdict, verdict.reason_code) == ("BLOCKED", "fee_to_release_award")


def test_a_lookalike_funder_is_unconfirmed() -> None:
    url = "https://daad-scholarships.org/"
    verdict = _verdict("daad-scholarships.org", _deps(fetch=FakeFetch({url: page(url, QUIET)})),
                       kind="PRIVATE_FOUNDATION")
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "no_register")


@pytest.mark.parametrize(("domain", "country"), [("mit.edu", ""), ("unibo.it", "IT")])
def test_a_country_with_no_shipped_register_is_no_register_not_waiting(domain, country) -> None:
    """Ruling 1: no register for the country (or no country at all) is not a
    wait -- register_not_loaded here would say "still being checked" forever.
    Rechecked on the cycle, never daily."""
    url = f"https://{domain}/"
    verdict = _verdict(domain, _deps(fetch=FakeFetch({url: page(url, QUIET)})), country=country)
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "no_register")
    assert verdict.next_check_at == NOW + timedelta(days=30)
    assert verdict.reason_code not in WAITING_REASONS


def test_a_go_kr_funder_is_recognised_by_its_government_zone() -> None:
    record_organisation(domain="studyinkorea.go.kr", name="Study in Korea",
                        kind="NATIONAL_GOVERNMENT", country_code="KR", found_via="TEST")
    deps = _deps(fetch=HomeFetch({}, homes=frozenset({"studyinkorea.go.kr"})))
    verdict = _verdict("studyinkorea.go.kr", deps, kind="NATIONAL_GOVERNMENT")
    assert verdict.reason_code == "government_zone"


def test_an_unverified_reviewed_row_is_unmapped() -> None:
    spec = make_list("az_heis", country_code="AZ")
    record_list(spec, (ListRow(
        external_key="x", name="Azerbaijan Technical University", kind="INSTITUTION",
        website="https://aztu.edu.az", page_url="", country_code="AZ", home_cells=("ANY",),
        host_cells=("AZ",), rejected_reason="", source_url=spec.source_url,
        verified_on=date(2026, 9, 26)),), now=NOW)
    url = "https://aztu.edu.az/"
    deps = _deps(sources=(ProvenanceSource(slug="az_heis", role="curated_list"),),
                 fetch=FakeFetch({url: page(url, QUIET)}))
    assert _verdict("aztu.edu.az", deps).reason_code == "unmapped_list_row"


def test_a_failed_lookup_is_unconfirmed_and_retried_tomorrow() -> None:
    def broken(url, *, params, headers):
        raise SourceBlocked("api returned HTTP 503")

    verdict = _verdict("unknown-college.edu", _deps(ror_call=broken))
    assert (verdict.reason_code, verdict.next_check_at) == (
        "lookup_failed", NOW + timedelta(days=1),
    )


def test_a_country_register_held_by_another_loader_is_not_loaded_yet() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    acquire_domain_lease("register:gb_sfc_universities", interval=timedelta(hours=1))
    url = "https://some-college.ac.uk/"
    verdict = _verdict("some-college.ac.uk",
                       _deps(sources=(SFC,), fetch=FakeFetch({url: page(url, QUIET)})),
                       country="GB")
    assert verdict.reason_code == "register_not_loaded"


def test_outages_never_downgrade_a_recognised_body(settings) -> None:
    settings.JEV_API_KEY = "k"
    source = _register("de_register", "DE", "outage-university.de")
    store = FakeStore()
    program = evidence_program("https://www.outage-university.de/msc")
    attach_snapshot(program.evidence_claims.get(), FEE_RELEASE, store)

    def jev_down(url, *, payload, headers):
        raise SourceBlocked("api returned HTTP 529")

    deps = _deps(sources=(source,), store=store, jev_post=jev_down, bootstrap=None,
                 fetch_file=Files())
    verdict = _verdict("outage-university.de", deps)
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "register")
    assert verdict.evidence["rdap"]["status"] == "failed"
    assert verdict.evidence["content_checks"] == "skipped"


def test_admission_never_calls_a_model(settings) -> None:
    settings.JEV_API_KEY = "k"
    source = _register("de_register", "DE", "quiet-university.de")
    calls: list[object] = []

    def jev(url, *, payload, headers):
        calls.append(payload)
        return {"model": "jev-1.13", "answers": {}}

    verdict = _verdict("quiet-university.de", _deps(sources=(source,), jev_post=jev))
    assert verdict.verdict == "RECOGNISED" and calls == []


def _holder_award(body: Organisation, domain: str) -> FundingOpportunity:
    return FundingOpportunity.objects.create(
        canonical_key=f"k:{uuid4()}", name="A", family="PRIVATE_FOUNDATION",
        scope_type="HOLDER", organisation=body, holder_domain=domain,
    )


def _pairs(queryset) -> set[tuple[Organisation, str]]:
    return {(pair.organisation, pair.registrable_domain) for pair in queryset}


def test_bodies_in_play_and_due() -> None:
    evidence_program("https://www.tum.de/msc")
    tum = make_body("tum.de")
    funder = make_body("stiftung-fixture.de", kind="PRIVATE_FOUNDATION")
    _holder_award(funder, "stiftung-fixture.de")
    named = make_body("named-uni-fixture.de")
    Organisation.objects.filter(id=named.id).update(found_via=["NAMED_PROGRAM"])
    # The tag on the domain's own row is what puts it in play (check_named_url).
    OrganisationDomain.objects.filter(registrable_domain="named-uni-fixture.de").update(
        found_via=["NAMED_PROGRAM"]
    )
    # A body reached by a named URL on its second domain: that domain is in
    # play, its untagged primary is not.
    merged = make_body("merged-uni-fixture.de")
    Organisation.objects.filter(id=merged.id).update(found_via=["NAMED_PROGRAM"])
    OrganisationDomain.objects.create(
        organisation=merged, registrable_domain="merged-second-fixture.de",
        found_via=["NAMED_PROGRAM"],
    )
    idle = make_body("vgm-foundation-fixture.org.tr", kind="PRIVATE_FOUNDATION")
    assert _pairs(bodies_in_play()) == {
        (tum, "tum.de"), (funder, "stiftung-fixture.de"), (named, "named-uni-fixture.de"),
        (merged, "merged-second-fixture.de"),
    }
    recognise(tum, "tum.de")
    ProvenanceVerdict.objects.filter(domain="tum.de").update(next_check_at=NOW + timedelta(days=5))
    recognise(named, "named-uni-fixture.de", "mill_list")  # BLOCKED: never due again
    assert _pairs(due(NOW)) == {
        (funder, "stiftung-fixture.de"), (merged, "merged-second-fixture.de"),
    }
    assert idle not in {pair.organisation for pair in due(NOW)}


def test_a_verdict_is_per_domain_not_per_body() -> None:
    """Ruling 2: one body, domains A and B, a register row naming B and
    programmes on B. The (body, B) pair is RECOGNISED; A is untouched, and a
    HOLDER award on B is judged by B's row."""
    body = make_body("a-uni-fixture.de", country_code="DE")
    OrganisationDomain.objects.create(organisation=body, registrable_domain="b-uni-fixture.de")
    source = _register("de_register", "DE", "b-uni-fixture.de")
    evidence_program("https://www.b-uni-fixture.de/msc")
    award = _holder_award(body, "b-uni-fixture.de")
    assert _pairs(bodies_in_play()) == {(body, "b-uni-fixture.de")}

    tally = run_checks(bodies_in_play(), now=NOW, deps=_deps(sources=(source,)))
    assert tally == {"register": 1}
    b = ProvenanceVerdict.objects.get(domain="b-uni-fixture.de")
    assert (b.organisation, b.verdict, b.reason_code) == (body, "RECOGNISED", "register")
    assert not ProvenanceVerdict.objects.filter(domain="a-uni-fixture.de").exists()
    assert ProvenanceVerdict.objects.get(domain=award.holder_domain) == b

    url = "https://a-uni-fixture.de/"
    a = check_body(body, "a-uni-fixture.de", now=NOW,
                   deps=_deps(sources=(source,), fetch=FakeFetch({url: page(url, QUIET)})))
    assert (a.verdict, a.reason_code) == ("UNCONFIRMED", "absent_from_register")
    b.refresh_from_db()
    assert (b.verdict, b.reason_code) == ("RECOGNISED", "register")


def test_a_programme_and_a_holder_award_on_one_domain_share_one_verdict() -> None:
    source = _register("de_register", "DE", "tum.de")
    tum = Organisation.objects.get(domains__registrable_domain="tum.de")
    program = evidence_program("https://www.tum.de/msc")
    award = _holder_award(tum, "tum.de")
    assert _pairs(bodies_in_play()) == {(tum, "tum.de")}
    run_checks(bodies_in_play(), now=NOW, deps=_deps(sources=(source,)))
    [verdict] = ProvenanceVerdict.objects.all()
    assert verdict.domain == program.evidence_domain == award.holder_domain == "tum.de"


@pytest.mark.parametrize(
    ("verdict", "reason", "after"),
    [
        ("RECOGNISED", "register", None),
        ("BLOCKED", "mill_list", None),
        ("UNCONFIRMED", "lookup_failed", timedelta(days=1)),
        ("UNCONFIRMED", "register_not_loaded", timedelta(days=1)),
        ("UNCONFIRMED", "no_register", timedelta(days=30)),
        ("UNCONFIRMED", "absent_from_register", timedelta(days=7)),
    ],
)
def test_next_check(verdict, reason, after) -> None:
    expected = NOW + after if after else None
    assert next_check(Decision(verdict, reason, "x.de", {}), NOW) == expected


def test_a_recognised_pair_never_comes_due() -> None:
    source = _register("de_register", "DE", "tum.de")
    evidence_program("https://www.tum.de/msc")
    run_checks(bodies_in_play(), now=NOW, deps=_deps(sources=(source,)))
    assert ProvenanceVerdict.objects.get(domain="tum.de").verdict == "RECOGNISED"
    assert not due(NOW + timedelta(days=3650)).exists()


def test_one_failing_body_never_stops_the_run() -> None:
    evidence_program("https://www.good-uni-fixture.de/msc")
    evidence_program("https://www.bad-uni-fixture.de/msc")
    make_body("good-uni-fixture.de")
    make_body("bad-uni-fixture.de")

    def ror(url, *, params, headers):
        if "bad-uni" in params["query.advanced"]:
            raise RuntimeError("unexpected")
        return {"items": []}

    tally = run_checks(bodies_in_play(), now=NOW, deps=_deps(ror_call=ror))
    assert tally["error"] == 1 and sum(tally.values()) == 2
    # A crash is our bug, never a failed lookup: nothing is recorded for it.
    assert not ProvenanceVerdict.objects.filter(domain="bad-uni-fixture.de").exists()


def test_the_command_fails_when_any_domain_errored(monkeypatch) -> None:
    from apps.research.management.commands import provenance_check

    evidence_program("https://www.bad-uni-fixture.de/msc")
    make_body("bad-uni-fixture.de")

    def ror(url, *, params, headers):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(provenance_check, "Deps", lambda: _deps(ror_call=ror))
    out = StringIO()
    with pytest.raises(CommandError, match="1 domain"):
        call_command("provenance_check", "--all", stdout=out)
    assert "error: 1" in out.getvalue()
    assert not ProvenanceVerdict.objects.exists()


def test_the_command_checks_one_domain(monkeypatch) -> None:
    from apps.research.management.commands import provenance_check

    record_organisation(domain="studyinkorea.go.kr", name="Study in Korea",
                        kind="NATIONAL_GOVERNMENT", country_code="KR", found_via="TEST")
    deps = _deps(fetch=HomeFetch({}, homes=frozenset({"studyinkorea.go.kr"})))
    monkeypatch.setattr(provenance_check, "Deps", lambda: deps)
    out = StringIO()
    call_command("provenance_check", "--domain", "studyinkorea.go.kr", stdout=out)
    assert "government_zone: 1" in out.getvalue()


def test_the_command_reduces_a_domain_to_its_registrable_domain(monkeypatch) -> None:
    from apps.research.management.commands import provenance_check

    tum = make_body("tum.de")
    monkeypatch.setattr(provenance_check, "Deps", lambda: _deps())
    out = StringIO()
    call_command("provenance_check", "--domain", "www.tum.de", stdout=out)
    assert "checked 1 domains" in out.getvalue()
    assert ProvenanceVerdict.objects.get(domain="tum.de").organisation == tum


def test_the_recogniser_map_is_read_once_per_run() -> None:
    """Ruling 4: the vouch path reads RECOGNISED domains once per run, not
    per body -- a recogniser whose row vanishes mid-run still counts."""
    asoiu = make_body("asoiu.edu.az", country_code="AZ")
    recognise(asoiu, "asoiu.edu.az", "curated_list")
    ufaz = make_body("ufaz.az")
    deps = _deps(fetch=FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, ASOIU_HOME)}))
    assert check_body(ufaz, "ufaz.az", now=NOW, deps=deps).reason_code == "vouched_by_link"
    ProvenanceVerdict.objects.filter(domain="asoiu.edu.az").delete()
    assert check_body(ufaz, "ufaz.az", now=NOW, deps=deps).reason_code == "vouched_by_link"


# --- Known answers the brief left out, and the carried review findings ------


def test_metu_is_recognised_via_yok() -> None:
    make_list("tr_yok_state", country_code="TR", source_url=YOK_URL)
    make_list("tr_yok_foundation", country_code="TR", source_url=YOK_FOUNDATION_URL)
    deps = _deps(
        ror_call=_ror(**{"metu.edu.tr": _record("metu.edu.tr", "TR")}),
        fetch=HomeFetch({YOK_URL: page(YOK_URL, YOK_HTML),
                         YOK_FOUNDATION_URL: page(YOK_FOUNDATION_URL, YOK_FOUNDATION_HTML)},
                        homes=frozenset({"metu.edu.tr"})),
        sources=(YOK, YOK_FOUNDATION), load=load_register,
    )
    verdict = _verdict("metu.edu.tr", deps)
    assert (verdict.verdict, verdict.reason_code, verdict.domain) == (
        "RECOGNISED", "register", "metu.edu.tr",
    )
    assert verdict.evidence["source_slug"] == "tr_yok_state"


def test_kentech_absent_from_ror_is_recognised_by_its_cctlds_register() -> None:
    """Ruling I3 end to end: nothing gives KENTECH a country, so `.kr` picks
    the register to load, and the register's own website field admits it."""
    korea = next(source for source in read_sources() if source.slug == "kr_univ_info")
    make_list("kr_univ_info", country_code="KR", source_url=KR_LIST_URL)
    deps = _deps(sources=(korea,), load=load_register,
                 fetch_file=Files({korea.data_url: KR_JSON}),
                 fetch=HomeFetch({}, homes=frozenset({"kentech.ac.kr"})))
    verdict = _verdict("kentech.ac.kr", deps)
    assert (verdict.verdict, verdict.reason_code, verdict.domain) == (
        "RECOGNISED", "register", "kentech.ac.kr",
    )


@pytest.mark.parametrize("domain", ["tum.blogspot.com", "tum.wordpress.com", "tum.github.io"])
def test_a_hosting_platform_is_never_recognised_by_its_domain(domain: str) -> None:
    source = _register("de_register", "DE", domain)
    verdict = _verdict(domain, _deps(sources=(source,)))
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "no_domain_binding")


def test_a_list_row_recognises_only_the_body_of_its_own_website() -> None:
    """Task 4 ruling: a row whose website is esmt.berlin recognises that body,
    never the esmt.org one, even when ROR's record joins the two."""
    source = _register("de_register", "DE", "esmt.berlin")
    url = "https://esmt.org/"
    deps = _deps(sources=(source,), fetch=FakeFetch({url: page(url, QUIET)}),
                 ror_call=_ror(**{"esmt.org": _record("esmt.org", "DE")}))
    assert _verdict("esmt.org", deps).reason_code == "absent_from_register"
    assert _verdict("esmt.berlin", deps).reason_code == "register"


def test_a_first_binding_of_another_domain_is_no_takeover_clock() -> None:
    """Task 4 review M5: our first-binding date counts only for the domain it
    was recorded for."""
    source = _register("de_register", "DE", "esmt.berlin")
    body = Organisation.objects.get(domains__registrable_domain="esmt.berlin")
    recognise(body, "esmt.org", now=datetime(2015, 1, 1, tzinfo=UTC))
    deps = _deps(sources=(source,), bootstrap={"berlin": "https://rdap.nic.berlin/v1/"},
                 fetch_file=Files({"https://rdap.nic.berlin/v1/domain/esmt.berlin": ESMT}))
    verdict = check_body(body, "esmt.berlin", now=NOW, deps=deps)
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "register")
    assert verdict.evidence["rdap"]["date"] == "2016-06-06"


WARNBOROUGH_SFC = SFC_HTML.replace("http://www.gla.ac.uk", "http://www.warnborough.ac.uk")


def test_a_mill_row_is_judged_against_its_own_countrys_register() -> None:
    """Task 4 review I2: the body's own country (IE here) is not the mill row's
    (GB), so the GB register is loaded for the mill check -- the override never
    depends on which register happened to be loaded first."""
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    deps = _deps(sources=(SFC,), load=load_register, mill_rows=read_mill_list(),
                 fetch=HomeFetch({SFC_URL: page(SFC_URL, WARNBOROUGH_SFC)},
                                homes=frozenset({"warnborough.ac.uk"})))
    verdict = _verdict("warnborough.ac.uk", deps, country="IE")
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "register")
    assert verdict.evidence["mill"]["overridden"] is True


def test_a_mill_whose_countrys_register_cannot_be_read_is_not_blocked_for_good() -> None:
    """BLOCKED is never re-checked, so an unreadable register that could still
    override the mill row leaves the body UNCONFIRMED and retried tomorrow."""
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    deps = _deps(sources=(SFC,), load=load_register, mill_rows=read_mill_list())
    verdict = _verdict("warnborough.ac.uk", deps, country="IE")
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "lookup_failed")
    assert verdict.next_check_at == NOW + timedelta(days=1)


def test_a_mill_its_country_register_does_not_list_is_blocked() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    deps = _deps(sources=(SFC,), load=load_register, mill_rows=read_mill_list(),
                 fetch=FakeFetch({SFC_URL: page(SFC_URL, SFC_HTML)}))
    verdict = _verdict("warnborough.ac.uk", deps)
    assert (verdict.verdict, verdict.reason_code) == ("BLOCKED", "mill_list")
    assert verdict.evidence["content_checks_detail"] == "mill_list"


def test_content_checks_skipped_without_a_key_say_why(settings) -> None:
    settings.JEV_API_KEY = ""
    source = _register("de_register", "DE", "quiet-university.de")
    verdict = _verdict("quiet-university.de", _deps(sources=(source,)))
    assert (verdict.evidence["content_checks"], verdict.evidence["content_checks_detail"]) == (
        "skipped", "no_key",
    )


@pytest.mark.django_db(transaction=True)
def test_no_transaction_is_held_across_any_outbound_call(settings) -> None:
    """Spec §7.1 / Task 6 review: a register download, a vendor fetch, a Jev
    call or an evidence-bucket read never runs inside a transaction."""
    settings.JEV_API_KEY = "k"
    seen: list[tuple[str, bool]] = []

    def watch(name, call):
        def wrapped(*args, **kwargs):
            seen.append((name, connection.in_atomic_block))
            return call(*args, **kwargs)
        return wrapped

    class WatchedStore(FakeStore):
        def get(self, key: str) -> bytes:
            seen.append(("store.get", connection.in_atomic_block))
            return super().get(key)

    store = WatchedStore()
    program = evidence_program("https://www.tum.de/msc")
    attach_snapshot(program.evidence_claims.get(), FEE_RELEASE, store)
    deps = _germany_deps(bootstrap=None, store=store)
    deps.fetch = watch("fetch", deps.fetch)
    deps.fetch_file = watch("fetch_file", deps.fetch_file)
    deps.ror_call = watch("ror", deps.ror_call)
    deps.jev_post = watch("jev", lambda url, **kw: {"model": "jev-1.13", "answers": {}})
    make_body("tum.de")
    tally = run_checks(bodies_in_play(), now=NOW, deps=deps)
    assert tally == {"register": 1}
    assert {name for name, _ in seen} == {"fetch", "fetch_file", "ror", "jev", "store.get"}
    assert [name for name, atomic in seen if atomic] == []


def test_a_recogniser_downgraded_mid_run_stops_vouching_in_that_run() -> None:
    body = make_body("fallen.edu")
    deps = _deps(
        recognisers={"fallen.edu": ("register", body.id), "other.edu": ("register", uuid4())}
    )
    decision = Decision(
        verdict="UNCONFIRMED", reason_code="no_register", bound_domain="", evidence={}
    )
    provenance_job._record(body, "fallen.edu", decision, timezone.now(), deps)
    assert set(deps.recognisers) == {"other.edu"}


def test_a_register_row_whose_site_does_not_name_it_is_unmapped() -> None:
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    parked = SiteFetch({}, site="tum.de", html="<title>tum.de for sale</title>")
    verdict = _verdict("tum.de", _deps(sources=(source,), fetch=parked))
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "unmapped_list_row")


def test_a_register_row_whose_site_names_it_is_recognised_and_stays_verified() -> None:
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    RegisterEntry.objects.filter(website_domain="tum.de").update(
        name="Technische Universität München"
    )
    fetch = HomeFetch({}, homes=frozenset({"tum.de"}))
    verdict = _verdict("tum.de", _deps(sources=(source,), fetch=fetch))
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "register")
    entry = RegisterEntry.objects.get(website_domain="tum.de")
    assert entry.origin_verified_domain == "tum.de"


def test_a_register_row_redirected_off_its_domain_is_unmapped() -> None:
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    moved = SiteFetch({}, site="tum.de", html="<title>tum.de</title>",
                      landed="https://casino.example/")
    assert _verdict("tum.de", _deps(sources=(source,), fetch=moved)).reason_code == (
        "unmapped_list_row"
    )


def test_a_failing_origin_is_verified_once_per_check() -> None:
    """recognitions() runs up to three times per check; the memo keeps
    verify_origin to one attempt (its printed URL plus one counterpart)."""
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    fetch = SiteFetch({}, site="tum.de", html="<title>nothing</title>")
    _verdict("tum.de", _deps(sources=(source,), fetch=fetch))
    assert len([url for url in fetch.calls if "tum.de" in url]) <= 2


def test_list_recognitions_without_the_flag_is_unchanged() -> None:
    _register("de_register", "DE", "tum.de", origin_verified=False)
    tum = Organisation.objects.get(domains__registrable_domain="tum.de")
    source = ProvenanceSource(slug="de_register", role="register", named_by_hand_because="test")
    assert [r.reason for r in list_recognitions(tum, (source,))[0]] == ["register"]
    assert list_recognitions(tum, (source,), require_register_origin=True) == ((), True)


def test_a_register_row_named_only_in_body_text_is_unmapped() -> None:
    source = _register("de_register", "DE", "tum.de", origin_verified=False)
    RegisterEntry.objects.filter(website_domain="tum.de").update(
        name="Technische Universität München"
    )
    html = (
        "<html><head><title>Lapsed domain</title></head><body><header>Casino</header>"
        "<main>Alumni of Technische Universität München, welcome.</main></body></html>"
    )
    fetch = SiteFetch({}, site="tum.de", html=html)
    verdict = _verdict("tum.de", _deps(sources=(source,), fetch=fetch))
    assert verdict.reason_code == "unmapped_list_row"


# --- the free yearly screen of RECOGNISED pairs ------------------------------

_ESMT_RDAP = {"berlin": "https://rdap.nic.berlin/v1/"}
_ESMT_URL = "https://rdap.nic.berlin/v1/domain/esmt.berlin"
_LONG_AGO = datetime(2015, 1, 1, tzinfo=UTC)


def _recognised(domain: str, *, at: datetime = _LONG_AGO):
    body = make_body(domain)
    recognise(body, domain, now=at)
    return body


def test_a_squatted_recognised_domain_is_fully_rechecked() -> None:
    source = _register("de_register", "DE", "esmt.berlin")
    _recognised("esmt.berlin")
    deps = _deps(sources=(source,), bootstrap=_ESMT_RDAP, fetch_file=Files({_ESMT_URL: ESMT}))
    tally = provenance_job.screen_recognised(now=NOW, deps=deps)
    assert tally == {"domain_registered_after_listing": 1}
    verdict = ProvenanceVerdict.objects.get(domain="esmt.berlin")
    assert verdict.verdict == "UNCONFIRMED"
    assert verdict.reason_code == "domain_registered_after_listing"


def test_a_clean_recognised_domain_is_screened_without_a_page_fetch() -> None:
    _recognised("esmt.berlin", at=datetime(2017, 1, 1, tzinfo=UTC))
    fetch = FakeFetch({})
    deps = _deps(fetch=fetch, bootstrap=_ESMT_RDAP, fetch_file=Files({_ESMT_URL: ESMT}))
    tally = provenance_job.screen_recognised(now=NOW, deps=deps)
    assert tally == {"screened": 1} and fetch.calls == []
    verdict = ProvenanceVerdict.objects.get(domain="esmt.berlin")
    assert (verdict.verdict, verdict.checked_at) == ("RECOGNISED", NOW)


def test_a_recognised_domain_now_on_the_mill_list_is_blocked() -> None:
    _recognised("bircham.edu")
    deps = _deps(mill_rows=read_mill_list())
    tally = provenance_job.screen_recognised(now=NOW, deps=deps)
    assert tally == {"mill_list": 1}
    verdict = ProvenanceVerdict.objects.get(domain="bircham.edu")
    assert (verdict.verdict, verdict.reason_code) == ("BLOCKED", "mill_list")


def test_a_recently_screened_recognised_domain_is_skipped() -> None:
    _recognised("esmt.berlin", at=NOW - timedelta(days=10))
    files = Files({_ESMT_URL: ESMT})
    calls: list[str] = []
    deps = _deps(bootstrap=_ESMT_RDAP, fetch_file=lambda url, **kw: calls.append(url) or files(url))
    assert provenance_job.screen_recognised(now=NOW, deps=deps) == {}
    assert calls == []


def test_a_failed_rdap_lookup_leaves_the_screen_pending() -> None:
    _recognised("esmt.berlin")
    deps = _deps(bootstrap=_ESMT_RDAP, fetch_file=Files())
    assert provenance_job.screen_recognised(now=NOW, deps=deps) == {"rdap_failed": 1}
    verdict = ProvenanceVerdict.objects.get(domain="esmt.berlin")
    assert (verdict.verdict, verdict.checked_at) == ("RECOGNISED", _LONG_AGO)


def test_the_recheck_command_runs_the_screen(monkeypatch) -> None:
    from apps.research.management.commands import provenance_recheck

    _recognised("esmt.berlin", at=datetime(2017, 1, 1, tzinfo=UTC))
    deps = _deps(bootstrap=_ESMT_RDAP, fetch_file=Files({_ESMT_URL: ESMT}))
    monkeypatch.setattr(provenance_recheck, "Deps", lambda: deps)
    out = StringIO()
    call_command("provenance_recheck", stdout=out)
    assert "screen screened: 1" in out.getvalue()
