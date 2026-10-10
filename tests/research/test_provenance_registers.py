"""Country registers, found through ENIC-NARIC, read into the register (spec
§5.1 point 1, §6). Captured, minimal samples; no network."""

from dataclasses import replace
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.research.closed_lists import ListReport
from apps.research.egress import FetchResult
from apps.research.hosts import registrable_domain
from apps.research.models import ClosedList, OrganisationDomain, RegisterEntry, ResolvedVia
from apps.research.recognition import (
    ProvenanceSource,
    RegisterNotVouched,
    RegisterShape,
    RegisterUnreachable,
    SourceFileError,
    _https,
    enic_register_links,
    enic_vouches,
    ensure_country_loaded,
    list_recognitions,
    load_register,
    parse_register,
    read_sources,
    register_country,
    register_state,
)
from tests.research.provenance_helpers import FakeFetch, FakeStore, make_body, make_list, page

pytestmark = pytest.mark.django_db
NOW = timezone.now()

ENIC_DE_URL = "https://www.enic-naric.net/page-Germany"
#: Shape captured from page-Germany 2026-09-26: one acc-group per section, the
#: heading in an h3, the links in a `content` div.
ENIC_GERMANY = """<html><body><div class="style2">
<div class="acc-group PL-NAZ"><div id="heading3"><a>
<h3 class="PL-NAZcont">Higher Education System</h3></a></div>
<div id="acc3" class="collapse"><div class="content PL-NAZcont"><p>
<a href="https://www.study-in-germany.de/en/">English</a></p></div></div></div>
<div class="acc-group PL-NAZ"><div id="heading4"><a>
<img alt="Recognised Higher Education Institutions">
<h3 class="PL-NAZcont">Recognised Higher Education Institutions</h3></a></div>
<div id="acc4" class="collapse"><div class="content PL-NAZcont"><p>
<strong>Higher Education Compass</strong><br/>
<strong>Link(s):</strong> <a target="_blank" href="http://www.hochschulkompass.de/">German</a>,
<a target="_blank" href="https://www.hochschulkompass.de/en/study-in-germany.html">English</a>
</p></div></div></div>
<div class="acc-group PL-NAZ"><div id="heading5"><a>
<h3 class="PL-NAZcont">Qualifications Framework</h3></a></div>
<div id="acc5" class="collapse"><div class="content PL-NAZcont"><p>
<a href="https://www.dqr.de/">DQR</a></p></div></div></div>
</div></body></html>"""

#: hs_liste.txt's real header names and real rows, captured 2026-09-27 and
#: served as Windows-1252: NBS's name carries an en dash (0x96), and a name
#: may be a quoted field spanning two lines (München DigitalH).
HRK_TSV = (
    "Hs-Nr.\tHochschulkurzname\tHochschulname\tHome Page\tMitglied HRK\n"
    "184\tMünchen TUM\tTechnische Universität München\thttp://www.tum.de\t1\n"
    "2\tAachen FH\tFachhochschule Aachen\thttp://www.fh-aachen.de\t1\n"
    "4\tAlbstadt-Sigmaringen H\tHochschule Albstadt-Sigmaringen\twww.hs-albsig.de\t1\n"
    "735\tHamburg NBS\tNBS Northern Business School – University of Applied Sciences"
    "\thttps://www.nbs.de\t0\n"
    '763\tMünchen DigitalH\t"Munich University of Digital \nTechnologies & Applied Sciences"'
    "\thttps://uni-munich.de/\t0\n"
).encode("cp1252")

SFC_URL = "https://www.sfc.ac.uk/our-funding/university-funding/"
SFC_HTML = """<html><body>
<header><ul><li><a href="https://twitter.com/sfc">Twitter</a></li></ul></header>
<div class="wysiwyg">
<p>We currently provide funding to 19 universities and higher education institutions (HEIs).</p>
<ul><li>
<a title="this link opens in a new window"
href="http://www.abertay.ac.uk">Abertay University</a></li>
<li><a href="http://www.ed.ac.uk">University of Edinburgh</a></li>
<li><a href="http://www.gla.ac.uk">University of Glasgow</a></li>
<li><a href="https://www.sfc.ac.uk/about-us/">About us</a></li></ul></div></body></html>"""
SFC = ProvenanceSource(
    slug="gb_sfc_universities", role="register", named_by_hand_because="test",
    data_url=SFC_URL, format="html_list", list_anchor="We currently provide funding to",
)

YOK_URL = "https://www.yok.gov.tr/tr/university?type=1"
YOK_FOUNDATION_URL = "https://www.yok.gov.tr/tr/university?type=2"


def _yok_card(name: str, website: str, kind: str = "Devlet Üniversiteleri") -> str:
    """One card as www.yok.gov.tr/tr/university prints it (2026-09-27),
    trimmed of its logo, icons and address."""
    return f"""<div class="university-card-uni" data-name="{name}" data-city="ANKARA">
<div class="university-header-uni"><div class="university-info-uni"><h3>{name}</h3>
<span class="university-type-uni type-1">{kind}</span></div></div>
<div class="university-details-uni">
<div class="detail-item-uni"><div class="detail-label-uni">Şehir:</div>
<div class="detail-value-uni">ANKARA</div></div>
<div class="detail-item-uni"><div class="detail-label-uni">Web Sitesi:</div>
<div class="detail-value-uni"><a href="{website}" target="_blank">{website}</a></div></div>
</div></div>"""


YOK_HTML = (
    '<html><head><meta charset="utf-8"></head><body><h1>Devlet Üniversiteleri</h1>'
    '<a href="/university?type=2">Vakıf Üniversiteleri</a>'
    + _yok_card("ORTA DOĞU TEKNİK ÜNİVERSİTESİ", "https://www.metu.edu.tr")
    + _yok_card("İSTANBUL TEKNİK ÜNİVERSİTESİ", "https://www.itu.edu.tr")
    # Real: YÖK prints two sites for Hakkari; that is not one website.
    + _yok_card("HAKKARİ ÜNİVERSİTESİ", "https://www.hakkari.edu.tr / www.hu.edu.tr")
    + "</body></html>"
)
YOK_FOUNDATION_HTML = (
    '<html><head><meta charset="utf-8"></head><body><h1>Vakıf Üniversiteleri</h1>'
    + _yok_card("İHSAN DOĞRAMACI BİLKENT ÜNİVERSİTESİ", "https://www.bilkent.edu.tr",
                "Vakıf Üniversiteleri")
    + "</body></html>"
)


def _shipped(slug: str) -> ProvenanceSource:
    return next(source for source in read_sources() if source.slug == slug)


HRK = _shipped("de_hochschulkompass")
YOK = _shipped("tr_yok_state")
YOK_FOUNDATION = _shipped("tr_yok_foundation")

#: Captured from data.go.kr's standard-data download for #15107736 on
#: 2026-09-26: a top-level JSON list, served as text/html. KENTECH appears
#: twice (university and graduate school, one site) and ROR lacks it.
KR_JSON = (
    '[{"SCHL_NM": "한국에너지공과대학교", '
    '"SCHL_ENG_NM": "Korea Institute of Energy Technology", '
    '"MAINBRANCH_NM": "본교", "SCHL_SE_NM": "대학교", "HMPG_ADDR": "www.kentech.ac.kr/"},'
    '{"SCHL_NM": "한국에너지공과대학교 대학원", '
    '"SCHL_ENG_NM": "Korea institute of Energy Technology", '
    '"MAINBRANCH_NM": "본교", "SCHL_SE_NM": "일반대학원", "HMPG_ADDR": "kentech.ac.kr"},'
    '{"SCHL_NM": "충남대학교 평화안보대학원", '
    '"SCHL_ENG_NM": "Graduate School Of Peace & Security '
    'Studies in Chungnam National University", "MAINBRANCH_NM": "본교", '
    '"SCHL_SE_NM": "특수대학원", "HMPG_ADDR": "peace.cnu.ac.kr/"},'
    '{"SCHL_NM": "어느대학교", "SCHL_ENG_NM": "", "MAINBRANCH_NM": "분교", '
    '"SCHL_SE_NM": "대학교", "HMPG_ADDR": ""}]'
).encode()

OFS_JSON = (
    b'[{"LegalName": "The University of Manchester", "Ukprn": "10007798", '
    b'"Website": "https://www.manchester.ac.uk", "EmailAddress": "x"},'
    b'{"LegalName": "Lamda Limited", "Ukprn": "10003758", "Website": "", "EmailAddress": "y"}]'
)
OFS = ProvenanceSource(
    slug="gb_ofs_register", role="register",
    enic_naric_page="https://www.enic-naric.net/page-United-Kingdom",
    data_url="https://register-api.officeforstudents.org.uk/api/Provider", format="json_list",
    name_field="LegalName", website_field="Website", id_field="Ukprn", id_scheme="UKPRN",
)


class FetchFile:
    def __init__(
        self, body: bytes, content_type: str = "text/plain", final_url: str = ""
    ) -> None:
        self.body, self.content_type, self.calls = body, content_type, []
        self.final_url = final_url

    def __call__(self, url: str, **kwargs: object) -> FetchResult:
        self.calls.append((url, kwargs))
        return FetchResult(self.final_url or url, (), self.content_type, self.body)


KR_LIST_URL = "https://www.data.go.kr/data/15107736/standard.do"
OFS_LIST_URL = (
    "https://www.officeforstudents.org.uk/for-providers/regulatory-resources/the-ofs-register/"
)


def _load_sfc(html: str = SFC_HTML) -> ListReport:
    return load_register(
        SFC, now=NOW, fetch=FakeFetch({SFC_URL: page(SFC_URL, html)}), store=FakeStore()
    )


def _load_hrk() -> ListReport:
    return load_register(
        HRK, now=NOW, fetch=_germany(), fetch_file=FetchFile(HRK_TSV), store=FakeStore()
    )


HRK_DOWNLOADS_URL = "https://www.hochschulkompass.de/hochschulen/downloads.html"
HRK_FILE_URL = "https://hs-kompass.de/kompass/xml/download/hs_liste.txt"
#: Shape of hochschulkompass.de's downloads page, 2026-09-27: a <base href>
#: and an absolute link to the file on the Stiftung's download host.
HRK_DOWNLOADS = f"""<html><head><base href="https://www.hochschulkompass.de/"></head><body>
<a href="hochschulen.html">Hochschulen</a>
<a href="{HRK_FILE_URL}">Liste der Hochschulen (TXT)</a></body></html>"""


def _germany(downloads: str = HRK_DOWNLOADS, landed: str | None = None) -> FakeFetch:
    return FakeFetch({
        ENIC_DE_URL: page(ENIC_DE_URL, ENIC_GERMANY),
        HRK_DOWNLOADS_URL: page(HRK_DOWNLOADS_URL, downloads, final_url=landed),
    })


def test_only_the_recognised_institutions_section_counts() -> None:
    links = enic_register_links(ENIC_GERMANY.encode())
    assert links == (
        "http://www.hochschulkompass.de/",
        "https://www.hochschulkompass.de/en/study-in-germany.html",
    )


def test_tum_is_recognised_via_its_register_and_the_file_is_archived() -> None:
    make_list("de_hochschulkompass", country_code="DE",
              source_url="https://www.hochschulkompass.de/hochschulen/downloads.html")
    fetch_file, store = FetchFile(HRK_TSV), FakeStore()
    report = load_register(HRK, now=NOW, fetch=_germany(), fetch_file=fetch_file, store=store)
    assert (report.listed, report.bound) == (5, 5)
    assert fetch_file.calls[0][0] == "https://hs-kompass.de/kompass/xml/download/hs_liste.txt"
    assert fetch_file.calls[0][1]["max_bytes"] == 500_000
    assert list(store.objects.values()) == [HRK_TSV]
    body = OrganisationDomain.objects.get(registrable_domain="tum.de").organisation
    assert body.status == "REGISTERED"
    found, _ = list_recognitions(body, (HRK,))
    assert [(r.reason, r.bound_domain, r.country_code) for r in found] == [
        ("register", "tum.de", "DE")
    ]
    assert OrganisationDomain.objects.filter(registrable_domain="hs-albsig.de").exists()
    assert RegisterEntry.objects.filter(
        name="NBS Northern Business School – University of Applied Sciences"
    ).exists()
    assert RegisterEntry.objects.filter(
        name="Munich University of Digital Technologies & Applied Sciences",
        website_domain="uni-munich.de",
    ).exists()
    assert ClosedList.objects.get(slug="de_hochschulkompass").loaded_at == NOW


def test_a_register_enic_naric_does_not_link_is_not_read() -> None:
    make_list("de_hochschulkompass", country_code="DE",
              source_url="https://hochschulkompass-fake.com/list")
    with pytest.raises(RegisterNotVouched):
        _load_hrk()
    assert not RegisterEntry.objects.exists()


@pytest.mark.parametrize("terms", ["UNREAD", "RESTRICTED"])
def test_a_register_whose_terms_are_not_open_still_loads(terms: str) -> None:
    """Owner decision 2026-09-27: reuse terms are recorded, never a gate."""
    make_list("de_hochschulkompass", country_code="DE", terms=terms,
              source_url="https://www.hochschulkompass.de/hochschulen/downloads.html")
    assert _load_hrk().bound == 5
    body = OrganisationDomain.objects.get(registrable_domain="tum.de").organisation
    assert [r.reason for r in list_recognitions(body, (HRK,))[0]] == ["register"]


def test_edinburgh_is_recognised_via_the_sfc_list_and_nothing_outside_the_list_is() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    _load_sfc()
    body = OrganisationDomain.objects.get(registrable_domain="ed.ac.uk").organisation
    found, _ = list_recognitions(body, (SFC,))
    assert [(r.reason, r.bound_domain) for r in found] == [("register", "ed.ac.uk")]
    assert not OrganisationDomain.objects.filter(registrable_domain="twitter.com").exists()
    assert not OrganisationDomain.objects.filter(registrable_domain="sfc.ac.uk").exists()


def _turkiye() -> FakeFetch:
    return FakeFetch({
        YOK_URL: page(YOK_URL, YOK_HTML),
        YOK_FOUNDATION_URL: page(YOK_FOUNDATION_URL, YOK_FOUNDATION_HTML),
    })


def test_metu_and_bilkent_are_recognised_via_yoks_two_lists() -> None:
    make_list("tr_yok_state", country_code="TR", source_url=YOK_URL)
    make_list("tr_yok_foundation", country_code="TR", source_url=YOK_FOUNDATION_URL)
    assert ensure_country_loaded(
        "TR", now=NOW, cycle=timedelta(days=30), sources=(YOK, YOK_FOUNDATION),
        fetch=_turkiye(), store=FakeStore(),
    ) == "ok"
    metu = OrganisationDomain.objects.get(registrable_domain="metu.edu.tr").organisation
    assert [(r.reason, r.bound_domain, r.country_code)
            for r in list_recognitions(metu, (YOK,))[0]] == [("register", "metu.edu.tr", "TR")]
    bilkent = OrganisationDomain.objects.get(registrable_domain="bilkent.edu.tr").organisation
    assert [r.reason for r in list_recognitions(bilkent, (YOK_FOUNDATION,))[0]] == ["register"]
    hakkari = RegisterEntry.objects.get(name="HAKKARİ ÜNİVERSİTESİ")
    assert hakkari.organisation is None
    assert not OrganisationDomain.objects.filter(registrable_domain="yok.gov.tr").exists()


def test_a_yok_page_whose_cards_moved_is_a_shape_error() -> None:
    make_list("tr_yok_state", country_code="TR", source_url=YOK_URL)
    moved = YOK_HTML.replace("university-card-uni", "uni-card")
    with pytest.raises(RegisterShape, match="no rows"):
        load_register(
            YOK, now=NOW, fetch=FakeFetch({YOK_URL: page(YOK_URL, moved)}), store=FakeStore()
        )
    assert ClosedList.objects.get(slug="tr_yok_state").loaded_at is None


def _korea():
    return next(source for source in read_sources() if source.slug == "kr_univ_info")


def test_kentech_is_recognised_via_the_korean_register_though_absent_from_ror() -> None:
    korea = _korea()
    make_list("kr_univ_info", country_code="KR", source_url=KR_LIST_URL)
    report = load_register(
        korea, now=NOW, fetch=FakeFetch({}), store=FakeStore(),
        fetch_file=FetchFile(KR_JSON, "text/html;charset=UTF-8"),
    )
    assert (report.listed, report.bound, report.unresolved) == (4, 3, 1)
    body = OrganisationDomain.objects.get(registrable_domain="kentech.ac.kr").organisation
    assert {r.reason for r in list_recognitions(body, (korea,))[0]} == {"register"}
    assert OrganisationDomain.objects.filter(registrable_domain="cnu.ac.kr").exists()


def test_a_json_register_whose_body_is_not_json_fails_loudly() -> None:
    make_list("kr_univ_info", country_code="KR")
    with pytest.raises(RegisterShape, match="not JSON"):
        load_register(
            _korea(), now=NOW, fetch=FakeFetch({}), store=FakeStore(),
            fetch_file=FetchFile(b"<html><body>maintenance</body></html>", "text/html"),
        )


def test_the_ofs_register_binds_by_website_and_keeps_the_ukprn() -> None:
    make_list("gb_ofs_register", country_code="GB", source_url=OFS_LIST_URL)
    enic_uk = ('<div class="acc-group"><h3>Recognised Higher Education Institutions</h3>'
               '<div class="content"><a href="https://www.officeforstudents.org.uk/for-providers/'
               'regulatory-resources/the-ofs-register/#/">OfS</a></div></div>')
    report = load_register(
        OFS, now=NOW, fetch=FakeFetch({OFS.enic_naric_page: page(OFS.enic_naric_page, enic_uk)}),
        fetch_file=FetchFile(OFS_JSON, "application/json"), store=FakeStore(),
    )
    assert (report.bound, report.unresolved) == (1, 1)
    body = OrganisationDomain.objects.get(registrable_domain="manchester.ac.uk").organisation
    [recognition] = list_recognitions(body, (OFS,))[0]
    assert recognition.identifier == ("UKPRN", "10007798")


def test_a_page_without_the_list_anchor_fails_loudly() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    moved = SFC_HTML.replace("We currently provide funding to", "Our funded institutions")
    with pytest.raises(RegisterShape, match="anchor"):
        _load_sfc(moved)
    assert not RegisterEntry.objects.exists()


def test_zero_parsed_rows_is_a_shape_error_not_an_empty_register() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    empty = SFC_HTML.split("(HEIs).</p>")[0] + "(HEIs).</p><ul></ul></div></body></html>"
    with pytest.raises(RegisterShape, match="no rows"):
        _load_sfc(empty)
    assert ClosedList.objects.get(slug="gb_sfc_universities").loaded_at is None


def test_a_printed_size_the_parse_does_not_reach_is_refused() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL, printed_size=19)
    with pytest.raises(RegisterShape, match="prints 19"):
        _load_sfc()


def test_an_unreachable_html_register_is_unreachable_not_empty() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    with pytest.raises(RegisterUnreachable):
        load_register(SFC, now=NOW, fetch=FakeFetch({}), store=FakeStore())


def test_register_state() -> None:
    sources = (SFC,)
    assert register_state("GB", sources) == "not_loaded"
    assert register_state("JP", sources) == "not_loaded"
    spec = make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    _load_sfc()
    assert register_state("GB", sources) == "absent"
    RegisterEntry.objects.create(
        register=spec.slug, external_key="name only", name="A College", resolution="UNRESOLVED",
        last_seen=NOW,
    )
    assert register_state("GB", sources) == "unbound_rows"


def test_ensure_country_loaded_reads_once_per_cycle_and_respects_the_lease() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    loads: list[str] = []

    def load(source, *, now, **_kwargs):
        loads.append(source.slug)
        ClosedList.objects.filter(slug=source.slug).update(loaded_at=now)

    cycle = timedelta(days=30)
    assert ensure_country_loaded("GB", now=NOW, cycle=cycle, sources=(SFC,), load=load) == "ok"
    assert ensure_country_loaded("GB", now=NOW, cycle=cycle, sources=(SFC,), load=load) == "ok"
    assert loads == ["gb_sfc_universities"]
    assert ensure_country_loaded("JP", now=NOW, cycle=cycle, sources=(SFC,), load=load) == "none"
    # Stale a cycle later, but the first load's 30-minute lease (taken on the
    # wall clock by acquire_domain_lease) is still held: a second loader waits.
    later = NOW + timedelta(days=31)
    assert ensure_country_loaded("GB", now=later, cycle=cycle, sources=(SFC,), load=load) == "busy"
    assert loads == ["gb_sfc_universities"]


def test_a_failed_load_is_failed_not_absent() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)

    def load(source, **_kwargs):
        raise RegisterUnreachable("sfc.ac.uk: DEAD")

    cycle = timedelta(days=30)
    assert ensure_country_loaded("GB", now=NOW, cycle=cycle, sources=(SFC,), load=load) == "failed"
    assert register_state("GB", (SFC,)) == "not_loaded"


def test_a_body_bound_before_the_load_is_the_one_the_register_binds() -> None:
    make_body("ed.ac.uk")
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    _load_sfc()
    assert OrganisationDomain.objects.filter(registrable_domain="ed.ac.uk").count() == 1


def test_the_shipped_registers_are_linked_or_named_by_hand() -> None:
    registers = [source for source in read_sources() if source.role == "register"]
    assert {source.slug for source in registers} == {
        "gb_ofs_register", "gb_sfc_universities", "kr_univ_info", "de_hochschulkompass",
        "tr_yok_state", "tr_yok_foundation",
    }
    for source in registers:
        assert bool(source.enic_naric_page) != bool(source.named_by_hand_because)
    # Germany is ENIC-vouched; its off-site file is proven by the downloads page.
    assert (HRK.enic_naric_page, HRK.named_by_hand_because) == (ENIC_DE_URL, "")


def test_a_resolver_bound_row_leaves_absence_unestablished() -> None:
    """Ruling I6: a row the resolver bound by name could be this body."""
    spec = make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    _load_sfc()
    RegisterEntry.objects.create(
        register=spec.slug, external_key="by name", name="A College", resolution="RESOLVED",
        resolved_via=ResolvedVia.WIKIDATA, organisation=make_body("college.example.ac.uk"),
        last_seen=NOW,
    )
    assert register_state("GB", (SFC,)) == "unbound_rows"


@pytest.mark.parametrize(
    ("country", "domain", "expected"),
    [("", "kentech.ac.kr", "KR"), ("", "ed.ac.uk", "GB"), ("", "example.edu", ""),
     ("", "", ""), ("DE", "esmt.berlin", "DE")],
)
def test_the_register_to_load_comes_from_the_country_else_the_cctld(
    country: str, domain: str, expected: str
) -> None:
    assert register_country(country, domain) == expected


def test_kentech_with_no_country_loads_the_korean_register_by_its_cctld() -> None:
    """Ruling I3, end to end: KENTECH is absent from ROR, so nothing gives it a
    country; its ccTLD picks which register to load, and the register's own
    website field is what admits it."""
    korea = _korea()
    make_list("kr_univ_info", country_code="KR", source_url=KR_LIST_URL)
    assert ensure_country_loaded(
        register_country("", "kentech.ac.kr"), now=NOW, cycle=timedelta(days=30),
        sources=(korea,), fetch=FakeFetch({}), store=FakeStore(),
        fetch_file=FetchFile(KR_JSON, "text/html;charset=UTF-8"),
    ) == "ok"
    body = OrganisationDomain.objects.get(registrable_domain="kentech.ac.kr").organisation
    assert {r.reason for r in list_recognitions(body, (korea,))[0]} == {"register"}


def test_a_bare_host_with_a_double_slash_path_keys_by_its_host() -> None:
    """Measured in the live Korean file: 6 of 1,995 rows print "//" in the path."""
    assert _https("www.sangji.ac.kr//grad/index.do") == "https://www.sangji.ac.kr//grad/index.do"
    assert _https("http://www.tum.de") == "http://www.tum.de"
    assert _https("") == ""


# --- Fix round 1 -----------------------------------------------------------


def _load_korea(body: bytes, *, now=NOW) -> ListReport:
    return load_register(
        _korea(), now=now, fetch=FakeFetch({}), store=FakeStore(),
        fetch_file=FetchFile(body, "text/html;charset=UTF-8"),
    )


def test_a_renamed_website_column_is_a_shape_error_not_an_unbinding() -> None:
    make_list("kr_univ_info", country_code="KR", source_url=KR_LIST_URL)
    _load_korea(KR_JSON)
    with pytest.raises(RegisterShape, match="HMPG_ADDR"):
        _load_korea(KR_JSON.replace(b"HMPG_ADDR", b"HMPG_URL"), now=NOW + timedelta(days=1))
    assert RegisterEntry.objects.filter(resolved_via=ResolvedVia.LISTED).count() == 3


def test_a_renamed_name_column_is_a_shape_error() -> None:
    make_list("kr_univ_info", country_code="KR", source_url=KR_LIST_URL)
    with pytest.raises(RegisterShape, match="SCHL_NM"):
        _load_korea(KR_JSON.replace(b'"SCHL_NM"', b'"SCHOOL_NM"'))


def test_a_website_column_blank_in_every_row_is_a_shape_error() -> None:
    make_list("kr_univ_info", country_code="KR", source_url=KR_LIST_URL)
    blank = KR_JSON
    for site in (b"www.kentech.ac.kr/", b"kentech.ac.kr", b"peace.cnu.ac.kr/"):
        blank = blank.replace(site, b"")
    with pytest.raises(RegisterShape, match="website"):
        _load_korea(blank)


def test_a_renamed_ofs_website_column_is_a_shape_error() -> None:
    make_list("gb_ofs_register", country_code="GB", source_url=OFS_LIST_URL)
    with pytest.raises(RegisterShape, match="Website"):
        load_register(
            OFS, now=NOW, fetch=_enic_uk(),
            fetch_file=FetchFile(OFS_JSON.replace(b'"Website"', b'"WebAddress"')),
            store=FakeStore(),
        )


def test_a_delisted_institution_loses_its_register_recognition() -> None:
    korea = _korea()
    make_list("kr_univ_info", country_code="KR", source_url=KR_LIST_URL)
    _load_korea(KR_JSON)
    body = OrganisationDomain.objects.get(registrable_domain="kentech.ac.kr").organisation
    assert list_recognitions(body, (korea,))[0]
    without_kentech = (
        b'[{"SCHL_NM": "\xec\xb6\xa9", "MAINBRANCH_NM": "x", "HMPG_ADDR": "peace.cnu.ac.kr/"}]'
    )
    _load_korea(without_kentech, now=NOW + timedelta(days=31))
    assert list_recognitions(body, (korea,))[0] == ()


def test_one_failing_register_does_not_starve_the_countrys_others() -> None:
    make_list("gb_ofs_register", country_code="GB", source_url=OFS_LIST_URL)
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)

    def load(source, **kwargs):
        if source.slug == OFS.slug:
            raise RegisterUnreachable("officeforstudents.org.uk: DEAD")
        return load_register(source, **kwargs)

    assert ensure_country_loaded(
        "GB", now=NOW, cycle=timedelta(days=30), sources=(OFS, SFC), load=load,
        fetch=FakeFetch({SFC_URL: page(SFC_URL, SFC_HTML)}), store=FakeStore(),
    ) == "failed"
    body = OrganisationDomain.objects.get(registrable_domain="ed.ac.uk").organisation
    assert [r.reason for r in list_recognitions(body, (SFC,))[0]] == ["register"]


def _enic_uk(final_url: str = "") -> FakeFetch:
    enic_uk = ('<div class="acc-group"><h3>Recognised Higher Education Institutions</h3>'
               '<div class="content"><a href="https://www.officeforstudents.org.uk/for-providers/'
               'regulatory-resources/the-ofs-register/#/">OfS</a>'
               '<a href="/relative">here</a></div></div>')
    url = OFS.enic_naric_page
    return FakeFetch({url: page(url, enic_uk, final_url=final_url or None)})


def test_an_enic_naric_page_that_landed_elsewhere_is_unreachable() -> None:
    make_list("gb_ofs_register", country_code="GB", source_url=OFS_LIST_URL)
    with pytest.raises(RegisterUnreachable, match="landed"):
        load_register(
            OFS, now=NOW, fetch=_enic_uk("https://enic-naric.evil.test/page-United-Kingdom"),
            fetch_file=FetchFile(OFS_JSON), store=FakeStore(),
        )


def test_an_html_register_that_landed_elsewhere_is_unreachable() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    moved = page(SFC_URL, SFC_HTML, final_url="https://sfc-lookalike.test/list")
    with pytest.raises(RegisterUnreachable, match="landed"):
        load_register(SFC, now=NOW, fetch=FakeFetch({SFC_URL: moved}), store=FakeStore())
    assert not RegisterEntry.objects.exists()


def test_a_data_file_that_landed_elsewhere_is_unreachable() -> None:
    make_list("gb_ofs_register", country_code="GB", source_url=OFS_LIST_URL)
    with pytest.raises(RegisterUnreachable, match="landed"):
        load_register(
            OFS, now=NOW, fetch=_enic_uk(), store=FakeStore(),
            fetch_file=FetchFile(OFS_JSON, final_url="https://mirror.evil.test/Provider"),
        )
    assert not RegisterEntry.objects.exists()


def test_a_data_url_off_the_vouched_site_is_not_read() -> None:
    """m13 at load: the ENIC-NARIC link vouches spec.source_url's site, so a
    file elsewhere is read only if that page links it exactly."""
    make_list("de_hochschulkompass", country_code="DE", source_url=HRK_DOWNLOADS_URL)
    elsewhere = replace(HRK, data_url="https://hs-kompass.de/x.txt")
    fetch_file = FetchFile(HRK_TSV)
    with pytest.raises(RegisterNotVouched, match="does not link"):
        load_register(elsewhere, now=NOW, fetch=_germany(), fetch_file=fetch_file,
                      store=FakeStore())
    assert fetch_file.calls == []


def test_a_relative_enic_naric_link_vouches_nothing() -> None:
    spec = make_list("gb_ofs_register", country_code="GB", source_url="")
    assert enic_vouches(OFS, spec, fetch=_enic_uk()) is False


@pytest.mark.parametrize(
    "website",
    ["a@b.com", "mailto:x@b.com", "kentech.ac.kr@evil.com", "https://u:p@evil.com/",
     "www.x.ac.kr\\grad", "a.ac.kr,b.ac.kr", "https://x.ac.kr, https://y.ac.kr",
     "한국 대학.kr", "대학@evil.com",
     # IDNA 2003 would map ß to "ss": strasse.de, someone else's domain;
     # it maps final sigma to sigma and drops a zero-width joiner the same way.
     "straße.de", "\u03c3\u03bf\u03c6\u03af\u03b1\u03c2.gr", "a\u200db.com"],
)
def test_a_website_with_userinfo_or_odd_host_characters_is_unbound(website: str) -> None:
    assert _https(website) == ""


def test_an_ordinary_website_keeps_binding() -> None:
    assert _https("www.kentech.ac.kr/") == "https://www.kentech.ac.kr/"
    assert _https("HTTP://WWW.TUM.DE:8080/x") == "HTTP://WWW.TUM.DE:8080/x"


def test_an_html_register_with_an_xml_declaration_parses() -> None:
    make_list("tr_yok_state", country_code="TR", source_url=YOK_URL)
    declared = '<?xml version="1.0" encoding="utf-8"?>' + YOK_HTML
    load_register(
        YOK, now=NOW, fetch=FakeFetch({YOK_URL: page(YOK_URL, declared)}), store=FakeStore()
    )
    assert OrganisationDomain.objects.filter(registrable_domain="metu.edu.tr").exists()


@pytest.mark.parametrize(
    ("source", "body"),
    [(YOK, b"   \n "), (HRK, b"Hs-Nr.\tHochschulname\tHome Page\n1\t\xff\xfe\tx.de\n")],
)
def test_an_unparseable_body_is_a_shape_error(source: ProvenanceSource, body: bytes) -> None:
    utf8 = replace(source, encoding="utf-8")
    with pytest.raises(RegisterShape):
        parse_register(body, utf8)


def test_a_whitespace_enic_naric_page_is_a_shape_error() -> None:
    spec = make_list("gb_ofs_register", country_code="GB", source_url=OFS_LIST_URL)
    url = OFS.enic_naric_page
    with pytest.raises(RegisterShape):
        enic_vouches(OFS, spec, fetch=FakeFetch({url: page(url, b"  \n")}))


# --- Fix round 2 -----------------------------------------------------------


@pytest.mark.parametrize(
    ("website", "expected", "domain"),
    [("한국대학.kr/admission", "https://xn--3e0bt9hy17aja.kr/admission", "xn--3e0bt9hy17aja.kr"),
     ("https://www.türkiye.edu.tr", "https://www.xn--trkiye-3ya.edu.tr", "xn--trkiye-3ya.edu.tr"),
     ("http://ÇUKUROVA.edu.tr:8080/", "http://xn--ukurova-txa.edu.tr:8080/",
      "xn--ukurova-txa.edu.tr")],
)
def test_an_internationalised_host_binds_to_its_punycode_form(
    website: str, expected: str, domain: str
) -> None:
    assert _https(website) == expected
    assert registrable_domain(expected) == domain


def test_a_register_row_with_an_idn_website_binds_the_xn_domain() -> None:
    make_list("tr_yok_state", country_code="TR", source_url=YOK_URL)
    idn = YOK_HTML.replace("https://www.itu.edu.tr", "https://www.türkiye.edu.tr")
    load_register(YOK, now=NOW, fetch=FakeFetch({YOK_URL: page(YOK_URL, idn)}), store=FakeStore())
    assert OrganisationDomain.objects.filter(registrable_domain="xn--trkiye-3ya.edu.tr").exists()


# --- Fix round 3 -----------------------------------------------------------


def test_germany_loads_when_the_vouched_downloads_page_links_its_file() -> None:
    make_list("de_hochschulkompass", country_code="DE", source_url=HRK_DOWNLOADS_URL)
    fetch, fetch_file = _germany(), FetchFile(HRK_TSV)
    report = load_register(HRK, now=NOW, fetch=fetch, fetch_file=fetch_file, store=FakeStore())
    assert report.bound == 5
    assert fetch.calls == [ENIC_DE_URL, HRK_DOWNLOADS_URL]
    assert [url for url, _ in fetch_file.calls] == [HRK_FILE_URL]


@pytest.mark.parametrize(
    ("downloads", "landed", "error"),
    [(HRK_DOWNLOADS.replace(HRK_FILE_URL, "https://hs-kompass.de/other.txt"), None,
      "does not link"),
     # A relative link resolves on hochschulkompass.de (its <base>), not hs-kompass.de.
     (HRK_DOWNLOADS.replace(HRK_FILE_URL, "/kompass/xml/download/hs_liste.txt"), None,
      "does not link"),
     (HRK_DOWNLOADS, "https://hochschulkompass.evil.test/downloads.html", "landed")],
)
def test_germany_is_refused_unless_the_vouched_site_links_the_file(
    downloads: str, landed: str | None, error: str
) -> None:
    make_list("de_hochschulkompass", country_code="DE", source_url=HRK_DOWNLOADS_URL)
    fetch_file = FetchFile(HRK_TSV)
    with pytest.raises(RegisterNotVouched, match=error):
        load_register(HRK, now=NOW, fetch=_germany(downloads, landed), fetch_file=fetch_file,
                      store=FakeStore())
    assert fetch_file.calls == []
    assert not RegisterEntry.objects.exists()


def test_a_hand_reason_does_not_excuse_an_enic_row_its_off_site_file(tmp_path) -> None:
    path = tmp_path / "provenance-sources.csv"
    path.write_text(
        "slug,role,enic_naric_page,named_by_hand_because,data_url,format,encoding,"
        "records_path,name_field,website_field,id_field,id_scheme,list_anchor,max_bytes\n"
        f"de_hochschulkompass,register,{ENIC_DE_URL},the file is elsewhere,{HRK_FILE_URL},"
        "tsv,cp1252,,Hochschulname,Home Page,Hs-Nr.,,,\n",
        encoding="utf-8",
    )
    with pytest.raises(SourceFileError, match="never both"):
        read_sources(path)


def _contacts(card: str) -> str:
    """A phone and a map link printed before the website, in their own items."""
    items = (
        '<div class="detail-item-uni"><div class="detail-label-uni">Telefon:</div>'
        '<div class="detail-value-uni"><a href="tel:+903122101000">0312 210 10 00</a></div></div>'
        '<div class="detail-item-uni"><div class="detail-label-uni">Adres:</div>'
        '<div class="detail-value-uni"><a href="https://maps.google.com/?q=ODTU">Harita</a>'
        "</div></div>"
    )
    details = '<div class="university-details-uni">'
    return card.replace(details, details + items)


def test_a_yok_card_binds_the_website_label_not_the_first_link() -> None:
    html = "<html><body>" + _contacts(
        _yok_card("ORTA DOĞU TEKNİK ÜNİVERSİTESİ", "https://www.metu.edu.tr")
    ) + "</body></html>"
    [row] = parse_register(html.encode(), YOK)
    assert row.website == "https://www.metu.edu.tr"


def test_a_yok_card_without_a_website_label_is_unbound() -> None:
    html = (
        "<html><body>"
        + _yok_card("ORTA DOĞU TEKNİK ÜNİVERSİTESİ", "https://www.metu.edu.tr").replace(
            "Web Sitesi:", "İletişim:"
        )
        + _yok_card("İSTANBUL TEKNİK ÜNİVERSİTESİ", "https://www.itu.edu.tr")
        + "</body></html>"
    )
    rows = {row.name: row.website for row in parse_register(html.encode(), YOK)}
    assert rows == {
        "ORTA DOĞU TEKNİK ÜNİVERSİTESİ": "",
        "İSTANBUL TEKNİK ÜNİVERSİTESİ": "https://www.itu.edu.tr",
    }


def test_a_json_register_missing_its_website_field_fails_in_the_json_reader() -> None:
    """Pins _json_list's own check: without it, parse_register's later
    "no row has a website" would fire instead, with a different message."""
    renamed = KR_JSON.replace(b"HMPG_ADDR", b"HMPG_URL")
    with pytest.raises(RegisterShape, match="no record has the field 'HMPG_ADDR'"):
        parse_register(renamed, _korea())
