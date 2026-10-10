"""Site identity: a recognition granted without reading the site (a government
zone, a register row bound through ROR) counts only when the homepage names the
body where a site names itself (spec §4 P2, §4.1 step 3). No network."""

import pytest
from django.utils import timezone

from apps.research.fetch.types import Outcome
from apps.research.models import (
    ClosedList,
    Organisation,
    RegisterEntry,
    RegisterEntryPartner,
    ResolvedVia,
)
from apps.research.provenance_job import check_body
from apps.research.recognition import (
    ProvenanceSource,
    body_names,
    identity_text,
    names_on_identity,
    site_identity,
    verify_register_origins,
)
from apps.research.register import record_organisation
from tests.research.provenance_helpers import FakeFetch, make_list, page, recognise
from tests.research.test_provenance_check import _deps, _record, _ror
from tests.research.test_vouch import ASOIU, ASOIU_HOME, UFAZ_HOME

pytestmark = pytest.mark.django_db
NOW = timezone.now()


def _body(domain: str, name: str, kind: str = "NATIONAL_GOVERNMENT"):
    return record_organisation(
        domain=domain, name=name, kind=kind, country_code="", found_via="TEST"
    )


def _home(domain: str, html: str) -> FakeFetch:
    return FakeFetch({f"https://{domain}/": page(f"https://{domain}/", html)})


def test_identity_text_reads_the_regions_a_site_names_itself_in() -> None:
    html = (
        '<html><head><title>الرئيسية</title><meta property="og:site_name" content="QU"></head>'
        '<body><header><img class="site-logo" alt="Qatar University"></header>'
        "<main>Qatar University students and Doha news</main>"
        "<footer>© 2026 جامعة قطر</footer></body></html>"
    ).encode()
    text = identity_text(html)
    assert "Qatar University" in text and "جامعة قطر" in text and "QU" in text
    assert "Doha news" not in text


def test_an_arabic_title_still_passes_on_the_logo_and_footer() -> None:
    html = (
        "<html><head><title>الرئيسية</title></head><body>"
        '<header><img id="logo" src="/l.png" alt="Qatar University"></header></body></html>'
    ).encode()
    assert names_on_identity(["Qatar University"], html, domain="qu.edu.qa")


def test_a_zone_site_that_names_another_body_in_its_body_text_is_not_that_body() -> None:
    yok_home = (
        "<html><head><title>Yükseköğretim Kurulu</title></head><body>"
        "<header>YÖK</header><main>Orta Doğu Teknik Üniversitesi yeni programlar</main>"
        "</body></html>"
    )
    metu = _body("yok.gov.tr", "Orta Doğu Teknik Üniversitesi", kind="INSTITUTION")
    assert site_identity(metu, "yok.gov.tr", fetch=_home("yok.gov.tr", yok_home)) == (
        "the homepage does not name the body"
    )


def test_a_parked_page_printing_the_domain_does_not_name_the_body() -> None:
    """"azportal.gov.az" folds to the token "azportal": without blanking the
    domain's own tokens, a for-sale page would name a body called Azportal."""
    portal = _body("azportal.gov.az", "Azportal")
    parked = "<html><head><title>azportal.gov.az is for sale</title></head><body></body></html>"
    assert site_identity(portal, "azportal.gov.az", fetch=_home("azportal.gov.az", parked)) == (
        "the homepage does not name the body"
    )


def test_a_body_named_only_by_its_domain_cannot_pass_identity() -> None:
    named = _body("studyinkorea.go.kr", "studyinkorea.go.kr")
    home = "<html><head><title>studyinkorea.go.kr</title></head></html>"
    assert site_identity(named, "studyinkorea.go.kr", fetch=_home("studyinkorea.go.kr", home)) == (
        "the homepage does not name the body"
    )


def test_a_local_language_register_name_counts_as_the_bodys_name() -> None:
    ministry = _body("edu.gov.az", "Ministry of Science and Education")
    RegisterEntry.objects.create(
        register="az_outbound_gov", external_key="mse", name="Elm və Təhsil Nazirliyi",
        organisation=ministry, website_domain="edu.gov.az", resolution="RESOLVED",
        resolved_via="LISTED",
        last_seen=NOW,
    )
    home = "<html><head><title>Elm və Təhsil Nazirliyi</title></head></html>"
    assert site_identity(ministry, "edu.gov.az", fetch=_home("edu.gov.az", home)) == "verified"


def test_an_unreadable_homepage_is_a_failed_lookup_not_a_verdict() -> None:
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    assert site_identity(ministry, "edu.gov.az", fetch=FakeFetch({})) == "lookup_failed"
    verdict = check_body(ministry, "edu.gov.az", now=NOW, deps=_deps(fetch=FakeFetch({})))
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "lookup_failed")


def test_a_homepage_that_redirects_off_the_domain_does_not_verify() -> None:
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    moved = FakeFetch({"https://edu.gov.az/": page(
        "https://edu.gov.az/", "<title>Elm və Təhsil Nazirliyi</title>",
        final_url="https://elmtehsil.example.com/",
    )})
    assert site_identity(ministry, "edu.gov.az", fetch=moved).startswith("redirected off")


def test_a_named_ministry_on_its_zone_is_recognised() -> None:
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    home = "<html><head><title>Elm və Təhsil Nazirliyi</title></head></html>"
    deps = _deps(fetch=_home("edu.gov.az", home))
    verdict = check_body(ministry, "edu.gov.az", now=NOW, deps=deps)
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "government_zone")
    assert verdict.evidence["site_identity"] == "verified"


def test_a_zone_body_whose_homepage_names_someone_else_is_unconfirmed() -> None:
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    home = "<html><head><title>Another Agency</title></head></html>"
    deps = _deps(fetch=_home("edu.gov.az", home))
    verdict = check_body(ministry, "edu.gov.az", now=NOW, deps=deps)
    assert verdict.verdict == "UNCONFIRMED"
    assert verdict.reason_code == "no_domain_binding"
    assert verdict.evidence["site_identity"] == "the homepage does not name the body"


def test_dead_is_not_verified() -> None:
    url = "https://edu.gov.az/"
    dead = FakeFetch({url: page(url, b"", outcome=Outcome.DEAD)})
    ministry = _body("edu.gov.az", "Elm və Təhsil Nazirliyi")
    assert site_identity(ministry, "edu.gov.az", fetch=dead) == "lookup_failed"


def _metu_on_yok(home: str) -> str:
    metu = _body("yok.gov.tr", "Orta Doğu Teknik Üniversitesi", kind="INSTITUTION")
    return site_identity(metu, "yok.gov.tr", fetch=_home("yok.gov.tr", home))


@pytest.mark.parametrize(
    "main",
    [
        "<article><header>Orta Doğu Teknik Üniversitesi</header></article>",
        "<section><footer>Orta Doğu Teknik Üniversitesi</footer></section>",
        '<img src="/uploads/logos/odtu.png" alt="Orta Doğu Teknik Üniversitesi">',
    ],
    ids=["article-header", "section-footer", "partner-logo"],
)
def test_a_regulator_naming_a_body_inside_main_is_not_that_body(main: str) -> None:
    home = (
        "<html><head><title>Yükseköğretim Kurulu</title></head>"
        f"<body><main>{main}</main></body></html>"
    )
    assert _metu_on_yok(home) == "the homepage does not name the body"


def test_a_logo_linking_to_the_site_root_names_the_site() -> None:
    home = (
        "<html><head><title>x</title></head><body><main>"
        '<a href="/"><img class="logo" alt="Orta Doğu Teknik Üniversitesi"></a>'
        "</main></body></html>"
    )
    assert _metu_on_yok(home) == "verified"


def test_a_hostile_href_does_not_crash_identity_and_the_title_still_names_the_site() -> None:
    home = (
        "<html><head><title>Orta Doğu Teknik Üniversitesi</title></head><body>"
        '<a href="http://["><img class="logo" alt="Orta Doğu Teknik Üniversitesi"></a>'
        "</body></html>"
    ).encode()
    assert names_on_identity(["Orta Doğu Teknik Üniversitesi"], home, domain="metu.edu.tr")


def test_an_empty_or_blank_body_has_no_identity_text() -> None:
    assert identity_text(b"") == identity_text(b"  \n ") == ""


def _ufaz_deps(*, readable: bool):
    recognise(_body("asoiu.edu.az", "ASOIU", kind="INSTITUTION"), "asoiu.edu.az", "curated_list")
    ufaz = _body("ufaz.gov.az", "Azerbaijan French University", kind="INSTITUTION")
    home = "https://ufaz.gov.az/"
    pages = {ASOIU: page(ASOIU, ASOIU_HOME.replace("www.ufaz.az", "www.ufaz.gov.az"))}
    if readable:
        pages[home] = page(home, UFAZ_HOME)
    return ufaz, _deps(fetch=FakeFetch(pages))


def test_a_zone_body_whose_homepage_could_not_be_read_is_retried_not_recognised() -> None:
    ufaz, deps = _ufaz_deps(readable=False)
    verdict = check_body(ufaz, "ufaz.gov.az", now=NOW, deps=deps)
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "lookup_failed")


def test_a_vouch_does_not_rescue_a_homepage_that_was_read_and_names_someone_else() -> None:
    # Was RECOGNISED vouched_by_link before the final-review wave (I1).
    ufaz, deps = _ufaz_deps(readable=True)
    verdict = check_body(ufaz, "ufaz.gov.az", now=NOW, deps=deps)
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "no_domain_binding")


def test_a_vouch_does_not_reopen_what_identity_closed() -> None:
    hacettepe = _body("hacettepe.edu.tr", "Hacettepe Üniversitesi", kind="INSTITUTION")
    recognise(hacettepe, "hacettepe.edu.tr")
    metu = _body("yok.gov.tr", "Orta Doğu Teknik Üniversitesi", kind="INSTITUTION")
    yok, hace = "https://yok.gov.tr/", "https://hacettepe.edu.tr/"
    yok_home = (
        "<html><head><title>Yükseköğretim Kurulu</title></head><body><header>YÖK</header>"
        f'<main>Orta Doğu Teknik Üniversitesi <nav><a href="{hace}">H</a></nav></main>'
        "</body></html>"
    )
    hace_home = (
        "<html><head><title>Hacettepe Üniversitesi</title></head><body>"
        f'<footer><a href="{yok}">YÖK</a></footer></body></html>'
    )
    fetch = FakeFetch({yok: page(yok, yok_home), hace: page(hace, hace_home)})
    verdict = check_body(metu, "yok.gov.tr", now=NOW, deps=_deps(fetch=fetch))
    assert verdict.evidence["site_identity"] == "the homepage does not name the body"
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "no_domain_binding")


def _ror_row_deps(title: str):
    make_list("de_register", country_code="DE")
    RegisterEntry.objects.create(
        register="de_register", external_key="Q1377512", name="ESMT Berlin",
        resolution="UNRESOLVED", last_seen=NOW,
    )
    ClosedList.objects.filter(slug="de_register").update(loaded_at=NOW)
    sources = (ProvenanceSource(slug="de_register", role="register", id_scheme="WIKIDATA"),)
    record = _record("esmt.berlin", "DE") | {
        "external_ids": [{"type": "wikidata", "all": ["Q1377512"], "preferred": "Q1377512"}]
    }
    url = "https://esmt.berlin/"
    fetch = FakeFetch({url: page(url, f"<html><head><title>{title}</title></head></html>")})
    return _deps(sources=sources, ror_call=_ror(**{"esmt.berlin": record}), fetch=fetch)


def test_a_ror_bound_row_is_recognised_by_its_own_name_on_the_homepage() -> None:
    body = _body("esmt.berlin", "European School of Management", kind="INSTITUTION")
    verdict = check_body(body, "esmt.berlin", now=NOW, deps=_ror_row_deps("ESMT Berlin"))
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "register")


def test_a_ror_bound_row_whose_name_the_homepage_lacks_is_unconfirmed() -> None:
    body = _body("esmt.berlin", "European School of Management", kind="INSTITUTION")
    verdict = check_body(body, "esmt.berlin", now=NOW, deps=_ror_row_deps("Parked"))
    assert verdict.verdict == "UNCONFIRMED"


@pytest.mark.parametrize(
    "main",
    [
        '<a href="https://www.metu.edu.tr/">'
        "<svg><title>Orta Doğu Teknik Üniversitesi</title></svg></a>",
        '<a href="https://odtu.yok.gov.tr/">'
        '<img class="logo" alt="Orta Doğu Teknik Üniversitesi"></a>',
        '<div role="banner">Orta Doğu Teknik Üniversitesi</div>',
        '<div role="contentinfo">Orta Doğu Teknik Üniversitesi</div>',
    ],
    ids=["svg-title", "subdomain-root-link", "role-banner-in-main", "role-contentinfo-in-main"],
)
def test_other_ways_a_regulator_could_seem_to_name_a_body_are_refused(main: str) -> None:
    home = (
        "<html><head><title>Yükseköğretim Kurulu</title></head>"
        f"<body><main>{main}</main></body></html>"
    )
    assert _metu_on_yok(home) == "the homepage does not name the body"


def _funder_partner(listed_name: str, org_name: str = "Old Partner College"):
    make_list("eacea_emjm")
    body = _body("lapsed-partner.eu", org_name, kind="INSTITUTION")
    entry = RegisterEntry.objects.create(
        register="eacea_emjm", external_key="p1", name="EMJM X",
        resolution="UNRESOLVED", last_seen=NOW,
    )
    RegisterEntryPartner.objects.create(
        entry=entry, organisation=body, role="PARTNER", listed_name=listed_name,
        listed_identifier="999", listed_domain="lapsed-partner.eu",
        disposition=RegisterEntryPartner.Disposition.NEW,
    )
    source = ProvenanceSource(slug="eacea_emjm", role="funder_list", named_by_hand_because="t")
    return body, source


def test_a_funder_list_partner_whose_homepage_is_a_casino_is_not_recognised() -> None:
    body, source = _funder_partner("Old Partner College")
    fetch = _home("lapsed-partner.eu", "<html><head><title>Best Casino</title></head></html>")
    deps = _deps(fetch=fetch, sources=(source,))
    verdict = check_body(body, "lapsed-partner.eu", now=NOW, deps=deps)
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "no_domain_binding")
    assert fetch.calls  # the site was read


@pytest.mark.parametrize("title", ["Old Partner College", "Lapsed Partner Institute"])
def test_a_funder_list_partner_whose_homepage_names_it_is_recognised(title: str) -> None:
    # The second title is the partner row's printed name, not the Organisation's.
    body, source = _funder_partner("Lapsed Partner Institute")
    fetch = _home("lapsed-partner.eu", f"<html><head><title>{title}</title></head></html>")
    deps = _deps(fetch=fetch, sources=(source,))
    verdict = check_body(body, "lapsed-partner.eu", now=NOW, deps=deps)
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "funder_list")


@pytest.mark.parametrize("platform_or_rejected", ["rejected", "platform"])
def test_verify_register_origins_spends_no_fetch_on_a_body_that_can_never_admit(
    platform_or_rejected: str,
) -> None:
    domain = "x.wordpress.com" if platform_or_rejected == "platform" else "rejected-college.edu"
    make_list("de_register", country_code="DE")
    body = _body(domain, "Some College", kind="INSTITUTION")
    if platform_or_rejected == "rejected":
        Organisation.objects.filter(id=body.id).update(status=Organisation.Status.REJECTED)
        body.refresh_from_db()
    RegisterEntry.objects.create(
        register="de_register", external_key="k1", name="Some College", organisation=body,
        website_domain=domain, resolution=RegisterEntry.Resolution.RESOLVED,
        resolved_via=ResolvedVia.LISTED, last_seen=NOW,
    )
    sources = (ProvenanceSource(slug="de_register", role="register"),)
    fetch = FakeFetch({})
    verify_register_origins(body, domain, sources, now=NOW, fetch=fetch, tried=set())
    assert fetch.calls == []


def test_a_project_title_on_a_funder_list_is_never_the_coordinators_name() -> None:
    """EACEA writes each EMJM as a RegisterEntry named after the project and
    bound to its coordinator; a consortium site titled with that project must
    not verify as the coordinator's own site (verified-catalog §3.2)."""
    uni = _body("uni-x.edu", "Universidade X", kind="INSTITUTION")
    RegisterEntry.objects.create(
        register="eacea_emjm", external_key="101234", name="EMJM Smart Cities",
        organisation=uni, resolution="RESOLVED", resolved_via="LISTED", last_seen=NOW,
    )
    RegisterEntry.objects.create(
        register="az_heis", external_key="x1", name="X Universiteti",
        organisation=uni, resolution="RESOLVED", resolved_via="LISTED", last_seen=NOW,
    )
    assert body_names(uni) == ("Universidade X", "X Universiteti")
    home = "<html><head><title>EMJM Smart Cities</title></head></html>"
    assert site_identity(uni, "uni-x.edu", fetch=_home("uni-x.edu", home)) == (
        "the homepage does not name the body"
    )
