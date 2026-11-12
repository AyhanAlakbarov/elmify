"""Tests for 53-country ministry closed lists, funded graduate schools, and Telegram monitor."""

from __future__ import annotations

from collections import Counter
from io import StringIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.research.card_funding.seek import proven, proven_or_verified_zone
from apps.research.catalogue_hop import CatalogueHopSource, extract_catalogue_hops
from apps.research.closed_lists import (
    LISTS_DIR,
    REGISTRY,
    ClosedListSource,
    load_registry,
    read_list_file,
    read_registry,
    record_list,
)
from apps.research.destinations import TARGET_COUNTRIES
from apps.research.discovery import DiscoveryQuery, RunBudget
from apps.research.models import ClosedList, Organisation
from apps.research.national_databases import NationalDatabasesSource
from apps.research.pipeline import default_sources
from apps.research.providers import SearchMeter, SearchRequest
from apps.research.providers.baidu import BaiduProvider, baidu_site_search
from apps.research.providers.naver import NaverProvider, naver_site_search
from apps.research.seam_bindings import build_university_funding_queries
from apps.research.search import SearchSource
from apps.research.social_monitor import (
    MinistryChannel,
    MinistrySocialMonitorSource,
    all_53_ministry_channels,
    discover_ministry_social_handles,
    extract_announcements_from_html,
    is_masters_scholarship_announcement,
    ministry_social_profiles,
)


def test_all_53_target_countries_have_ministry_and_agency_entries_plus_social_profiles() -> None:
    spec_dict = next(
        s for s in read_registry(REGISTRY) if s["slug"] == "all_53_ministries_and_agencies"
    )
    spec = ClosedList(**spec_dict)
    rows = read_list_file(spec, LISTS_DIR / "all_53_ministries_and_agencies.csv")
    counts = Counter(row.country_code for row in rows)
    missing = set(TARGET_COUNTRIES) - set(counts)
    assert not missing, f"Countries missing from all_53_ministries_and_agencies.csv: {missing}"
    under_two = {cc: n for cc, n in counts.items() if n < 2}
    assert not under_two, f"Every country must have >=2 bodies (Ministry + MFA/Agency): {under_two}"

    profiles = ministry_social_profiles()
    assert len(profiles) == len(rows)
    without_socials = [p.external_key for p in profiles if not p.social_handles]
    assert not without_socials, f"Missing social handles: {without_socials}"


def test_funded_excellence_graduate_schools_includes_strasbourg_and_padua() -> None:
    spec_dict = next(
        s for s in read_registry(REGISTRY) if s["slug"] == "funded_excellence_graduate_schools"
    )
    spec = ClosedList(**spec_dict)
    rows = read_list_file(spec, LISTS_DIR / "funded_excellence_graduate_schools.csv")
    by_key = {row.external_key: row for row in rows}
    assert "fr-eur-strasbourg-csc" in by_key
    assert (
        by_key["fr-eur-strasbourg-csc"].page_url == "https://csc.unistra.fr/master-of-csc-chemistry"
    )
    assert "it-unipd-digital-chemistry" in by_key
    assert by_key["it-unipd-digital-chemistry"].country_code == "IT"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "2026-2027-ci tədris ili üzrə Hökumətlərarası Təqaüd Proqramları (HTP) "
            "çərçivəsində magistratura səviyyəsinə sənəd qəbulu elan edilir.",
            True,
        ),
        (
            "Call for applications: Master's scholarships and tuition waivers for "
            "international students in Digital Chemistry 2026/2027.",
            True,
        ),
        (
            "Открыт прием заявок на стипендии Болашак по программам магистратуры.",
            True,
        ),
        (
            "Call for 15 fully-funded PhD positions and postdoctoral fellowships only.",
            False,
        ),
        (
            "Yalnız doktorantura səviyyəsi üzrə təqaüd proqramı elan edilir.",
            False,
        ),
        (
            "General university holiday schedule and campus maintenance notice.",
            False,
        ),
    ],
)
def test_is_masters_scholarship_announcement_filters_phd_only_and_non_scholarship_posts(
    text: str, expected: bool
) -> None:
    assert is_masters_scholarship_announcement(text) is expected


@pytest.mark.django_db
def test_telegram_s_channel_extracts_official_outbound_leads_and_records_pointer() -> None:
    channel = MinistryChannel(
        slug="az-etn-tg",
        country_code="AZ",
        ministry_name="Ministry of Science and Education of Azerbaijan",
        ministry_domain="edu.gov.az",
        channel_kind="telegram_s",
        url="https://t.me/s/edugovaz",
    )
    html = b"""
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message">
        <div class="tgme_widget_message_text">
          Macaristan HTP magistratura teqaud proqrami 2026/2027 uzre qeydiyyat basladi!
          Etrafli melumat: <a href="https://htp.edu.az/az/news/hungary-2027">htp.edu.az</a>
          ve <a href="https://stipendiumhungaricum.hu/apply/">Stipendium Hungaricum</a>
          <a href="https://t.me/edugovaz/1234">Telegram link</a>
        </div>
      </div>
    </div>
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message">
        <div class="tgme_widget_message_text">
          PhD-only postdoctoral fellowship call at <a href="https://phd.example.org">phd</a>
        </div>
      </div>
    </div>
    """
    announcements = extract_announcements_from_html(channel, html, record_pointers=True)
    assert len(announcements) == 1
    ann = announcements[0]
    assert set(ann.outbound_urls) == {
        "https://htp.edu.az/az/news/hungary-2027",
        "https://stipendiumhungaricum.hu/apply",
    }
    assert all(lead.can_support_claim for lead in ann.leads)
    # stipendiumhungaricum.hu was linked by edu.gov.az and recorded with a POINTER tag
    org = Organisation.objects.get(primary_domain="stipendiumhungaricum.hu")
    assert "POINTER:edu.gov.az" in org.found_via


@pytest.mark.django_db
def test_poll_ministry_channels_command_runs_across_all_53_countries(monkeypatch) -> None:
    all_channels = all_53_ministry_channels()
    covered_countries = {ch.country_code for ch in all_channels}
    assert set(TARGET_COUNTRIES) <= covered_countries

    sample_html = (
        b'<a href="https://edu.gov.az/uploads/htp-masters-2027.pdf">'
        b"Master's scholarship call 2027</a>"
    )
    monkeypatch.setattr(
        "apps.research.management.commands.poll_ministry_channels.fetch_page",
        lambda url, **_: SimpleNamespace(body=sample_html, outcome="FETCHED"),
    )
    out = StringIO()
    call_command("poll_ministry_channels", "--countries", "AZ", "--telegram-only", stdout=out)
    output = out.getvalue()
    assert "Polled 6 channels -> 6 announcements, 6 official leads." in output


def test_discover_ministry_social_handles_extracts_all_platforms() -> None:
    html = b"""
    <footer>
      <a href="https://t.me/s/edugovaz">Telegram</a>
      <a href="https://x.com/ItalyMFA">X</a>
      <a href="https://www.facebook.com/studyinfinland">Facebook</a>
      <a href="https://www.instagram.com/studyinnl/">Instagram</a>
      <a href="https://www.linkedin.com/company/nuffic/">LinkedIn</a>
      <a href="https://www.youtube.com/@studyinsweden">YouTube</a>
      <a href="https://vk.com/minobrnauki">VK</a>
      <a href="https://twitter.com/intent/tweet?text=hi">Share ignore</a>
    </footer>
    """
    handles = discover_ministry_social_handles(html, base_url="https://edu.gov.az")
    assert handles == {
        "tg": ("edugovaz",),
        "x": ("ItalyMFA",),
        "fb": ("studyinfinland",),
        "ig": ("studyinnl",),
        "li": ("nuffic",),
        "yt": ("studyinsweden",),
        "vk": ("minobrnauki",),
    }


def test_search_source_expands_interdisciplinary_fields_and_preserves_simple_fields() -> None:
    source = SearchSource(api_key="k")
    simple = DiscoveryQuery(field="robotics", country_code="JP", degree_level="MASTER")
    assert source.query_text(simple) == (
        "robotics master's degree Japan official funding scholarship"
    )

    interdisciplinary = DiscoveryQuery(
        field="AI with chemistry", country_code="FR", degree_level="MASTER"
    )
    q_text = source.query_text(interdisciplinary)
    assert "AI with chemistry (" in q_text
    assert "chemoinformatics" in q_text.casefold()
    assert "digital chemistry" in q_text.casefold()
    assert "France official funding scholarship" in q_text


@pytest.mark.django_db
def test_pipeline_sources_integrate_closed_lists_national_databases_and_social_monitor() -> None:
    load_registry()
    spec = ClosedList.objects.get(slug="funded_excellence_graduate_schools")
    record_list(spec, read_list_file(spec), now=timezone.now())
    query_fr = DiscoveryQuery(field="AI with chemistry", country_code="FR", degree_level="MASTER")

    cl_source = ClosedListSource(slug="funded_excellence_graduate_schools", filter_by_country=True)
    fr_leads = list(cl_source.find(query_fr))
    fr_urls = {lead.canonical_url for lead in fr_leads}
    assert "https://csc.unistra.fr/master-of-csc-chemistry" in fr_urls
    assert all("unipd.it" not in u for u in fr_urls)

    nd_source = NationalDatabasesSource()
    nd_urls = {lead.canonical_url for lead in nd_source.find(query_fr)}
    assert any("monmaster.gouv.fr" in u for u in nd_urls)

    sample_html = (
        b'<a href="https://www.diplomatie.gouv.fr/en/eiffel-master-2027">'
        b"France Excellence Eiffel Master Scholarship Call 2027</a>"
    )
    sm_source = MinistrySocialMonitorSource(
        fetch_html=lambda _url: SimpleNamespace(body=sample_html),
        record_pointers=False,
    )
    sm_urls = {lead.canonical_url for lead in sm_source.find(query_fr)}
    assert "https://www.diplomatie.gouv.fr/en/eiffel-master-2027" in sm_urls

    sources = default_sources(
        api_key="k",
        fetch=lambda *_a, **_k: SimpleNamespace(body=b""),  # type: ignore[arg-type,return-value]
        budget=RunBudget(),
        actor_id=UUID("00000000-0000-0000-0000-000000000001"),
        include_closed_lists=True,
        include_national_databases=True,
        include_social_monitor=True,
    )
    assert [s.name for s in sources] == [
        "seed:eacea",
        "closed-list:all_53_ministries_and_agencies",
        "closed-list:funded_excellence_graduate_schools",
        "closed-list:baku_ankara_embassies_and_missions",
        "closed-list:cofunded_and_foundation_scholarships",
        "closed-list:igo_consortium_universal_funding",
        "closed-list:regional_and_statutory_master_aid",
        "national-databases",
        "ministry-social-monitor",
        "entity-expansion",
    ]


def test_all_four_niche_channel_closed_lists_parse_and_cover_key_channels() -> None:
    specs = {str(s["slug"]): ClosedList(**s) for s in read_registry(REGISTRY)}
    for slug, expected_keys in (
        (
            "baku_ankara_embassies_and_missions",
            {"us-embassy-baku", "de-daad-baku", "fr-embassy-baku", "hu-embassy-baku"},
        ),
        (
            "cofunded_and_foundation_scholarships",
            {
                "tr-tev-yurtdisi",
                "tr-jean-monnet",
                "de-kas",
                "de-fes",
                "de-boell",
                "az-heydar-aliyev-fdn",
                "az-socar-scholarship",
            },
        ),
        (
            "igo_consortium_universal_funding",
            {
                "igo-adb-jsp",
                "igo-jj-wbgsp",
                "igo-isdb-msc",
                "igo-visegrad-fund",
                "igo-iaea-mscfp",
                "eu-eit-digital",
            },
        ),
        (
            "regional_and_statutory_master_aid",
            {
                "it-dsu-esu-padova",
                "it-dsu-ergo",
                "de-bayhost-bavaria",
                "cn-shanghai-sgs",
                "ca-quebec-pbeee",
            },
        ),
    ):
        assert slug in specs, slug
        rows = read_list_file(specs[slug], LISTS_DIR / f"{slug}.csv")
        keys = {r.external_key for r in rows}
        assert expected_keys <= keys, f"Missing keys in {slug}: {expected_keys - keys}"

    with_embassies = ministry_social_profiles(include_embassies=True)
    assert len(with_embassies) >= 133


@pytest.mark.django_db
def test_proven_or_verified_zone_preserves_proven_and_admits_verified_zones() -> None:
    # `proven()` itself stays None when no ProvenanceVerdict row exists in DB
    assert proven("https://edu.gov.az/decree.pdf") is None
    # `proven_or_verified_zone()` admits cited government zones & registry-verified academic zones
    assert proven_or_verified_zone("https://edu.gov.az/decree.pdf") is True
    assert proven_or_verified_zone("https://www.ox.ac.uk/admissions/graduate") is True
    assert proven_or_verified_zone("https://www.itu.edu.tr/en/scholarships") is True
    # Unverified flat domains with no ProvenanceVerdict or REGISTERED Organisation stay None
    assert proven_or_verified_zone("https://unverified-uni.de/ai-robotics") is None


def test_build_university_funding_queries_expands_interdisciplinary_fields_and_languages() -> None:
    queries_fr = build_university_funding_queries(
        "unistra.fr", field="AI with chemistry", country_code="FR"
    )
    assert len(queries_fr) == 2
    assert queries_fr[0].startswith("site:unistra.fr (")
    assert "chemoinformatics" in queries_fr[0].casefold()
    assert "bourse" in queries_fr[1].casefold()

    queries_it = build_university_funding_queries(
        "unipd.it", field="digital chemistry", country_code="IT"
    )
    assert len(queries_it) == 2
    assert "borse di studio" in queries_it[1].casefold()


@pytest.mark.django_db
def test_extract_catalogue_hops_and_catalogue_hop_source() -> None:
    html = b"""
    <html><body>
      <a href="https://csc.unistra.fr/master-of-csc-chemistry">CSC Chemistry Fellowship</a>
      <a href="https://www.unipd.it/en/scholarships-digital-chemistry">Padua Excellence Waiver</a>
      <a href="https://www.unistra.fr/phd-positions-only">PhD Doctoral Track Only</a>
      <a href="https://www.mastersportal.com/studies/123">Commercial Aggregator</a>
      <a href="https://campusfrance.org/fr/bourses-internes">Same Catalogue Domain</a>
    </body></html>
    """
    leads = extract_catalogue_hops(
        html,
        base_url="https://campusbourses.campusfrance.org/fria/bourse/#/catalog",
        source_type="FUNDER",
        funding_family="GOVERNMENT_SCHOLARSHIP",
        record_pointers=True,
    )
    urls = {lead.canonical_url for lead in leads}
    assert urls == {
        "https://csc.unistra.fr/master-of-csc-chemistry",
        "https://www.unipd.it/en/scholarships-digital-chemistry",
    }
    assert Organisation.objects.filter(
        primary_domain="unistra.fr", found_via__contains=["POINTER:campusfrance.org"]
    ).exists()

    hop_source = CatalogueHopSource(
        inner=NationalDatabasesSource(),
        fetch_html=lambda _url: SimpleNamespace(body=html),
        record_pointers=False,
    )
    hopped_leads = list(hop_source.find(DiscoveryQuery(field="chemistry", country_code="FR")))
    assert {lead.canonical_url for lead in hopped_leads} == urls


def test_baidu_and_naver_providers_and_site_search() -> None:
    meter = SearchMeter()
    baidu = BaiduProvider(
        api_key="test-baidu-key",
        get=lambda *_a, **_k: {
            "references": [
                {"url": "https://iso.pku.edu.cn/info/master_scholarship.htm"},
                {"url": "https://www.mastersportal.com/china"},
            ]
        },
    )
    req_cn = SearchRequest(query="中国硕士奖学金", country_code="CN", language="zh")
    cn_urls = list(baidu.search(req_cn, meter=meter))
    assert cn_urls == ["https://iso.pku.edu.cn/info/master_scholarship.htm"]
    assert meter.calls["baidu"] == 1

    cn_site = baidu_site_search(
        query="奖学金",
        domain="pku.edu.cn",
        api_key="test-baidu-key",
        get=lambda *_a, **_k: {
            "references": [
                {"url": "https://iso.pku.edu.cn/scholarships"},
                {"url": "https://other.edu.cn/scholarships"},
            ]
        },
    )
    assert cn_site.urls == ("https://iso.pku.edu.cn/scholarships",)

    naver = NaverProvider(
        client_id="id",
        client_secret="secret",
        get=lambda *_a, **_k: {
            "items": [
                {"link": "https://admission.kaist.ac.kr/intl-graduate/scholarship"},
                {"link": "https://www.scholars4dev.com/korea"},
            ]
        },
    )
    req_kr = SearchRequest(query="석사 장학금", country_code="KR", language="ko")
    kr_urls = list(naver.search(req_kr, meter=meter))
    assert kr_urls == ["https://admission.kaist.ac.kr/intl-graduate/scholarship"]
    assert meter.calls["naver"] == 1

    kr_site = naver_site_search(
        query="장학금",
        domain="kaist.ac.kr",
        client_id="id",
        client_secret="secret",
        get=lambda *_a, **_k: {
            "items": [
                {"link": "https://admission.kaist.ac.kr/intl-graduate/scholarship"},
                {"link": "https://snu.ac.kr/other"},
            ]
        },
    )
    assert kr_site.urls == ("https://admission.kaist.ac.kr/intl-graduate/scholarship",)


def test_build_social_search_requests_and_poll_non_telegram_handles() -> None:
    from apps.research.social_monitor import (
        build_social_search_requests,
        poll_social_search_channels,
    )

    reqs = build_social_search_requests(country_codes=("FR", "DE"), include_embassies=False)
    assert reqs
    assert all(r.denylist == () for r in reqs)
    queries = " ".join(r.query for r in reqs)
    assert "site:x.com/CampusFrance" in queries
    assert "site:x.com/DAAD_Germany" in queries

    class _SocialSearchStub:
        name = "exa"

        def search(self, request, meter=None):
            if "CampusFrance" in request.query:
                return ["https://x.com/CampusFrance/status/1900001"]
            return []

    leads = poll_social_search_channels(
        _SocialSearchStub(), country_codes=("FR",), include_embassies=False
    )
    lead_urls = {lead.canonical_url for lead in leads}
    assert "https://www.campusfrance.org/en/bourses-excellence-eiffel" in lead_urls
    assert all("x.com" not in u for u in lead_urls)


def test_multilingual_social_triage_and_two_hop_catalogue_detail_links() -> None:
    from apps.research.catalogue_hop import CatalogueHopSource, extract_internal_detail_links
    from apps.research.discovery import DiscoveryQuery, ResearchLead
    from apps.research.social_monitor import is_masters_scholarship_announcement

    # Rejects Bachelor-only and PhD-only calls in FR/DE/IT/EN
    assert not is_masters_scholarship_announcement(
        "International Undergraduate (Bachelor's) Scholarship 2027 now open!"
    )
    assert not is_masters_scholarship_announcement(
        "Appel à candidatures : Bourses de doctorat pour doctorants internationaux 2027"
    )
    assert not is_masters_scholarship_announcement(
        "Promotionsstipendium für Doktoranden 2027/28"
    )
    assert not is_masters_scholarship_announcement(
        "Bando per borse di dottorato di ricerca 2027"
    )

    # Accepts Turkish inflected bursu, Korean joint 석·박사, and Polish studia II stopnia
    assert is_masters_scholarship_announcement(
        "Yüksek Lisans Başarı Bursu başvuruları başladı"
    )
    assert is_masters_scholarship_announcement(
        "2027 정부초청외국인장학생 (석·박사 과정) 모집 안내"
    )
    assert is_masters_scholarship_announcement(
        "Stypendium na studia II stopnia w Polsce 2027"
    )

    # 2-hop internal detail-card extraction when a portal listing has only internal detail links
    listing_html = b"""
    <html><body>
      <a href="/en/detail/101">MSc Digital Chemistry Scholarship Card</a>
      <a href="/en/detail/102-phd">PhD Doctoral Card</a>
    </body></html>
    """
    detail_links = extract_internal_detail_links(
        listing_html, base_url="https://grants.at/en/?q=chemistry"
    )
    assert detail_links == ("https://grants.at/en/detail/101",)

    class _InnerStub:
        name = "inner"
        one_programme_per_link = False
        awards_jointly = False

        def find(self, query: DiscoveryQuery):
            yield ResearchLead.from_url(
                "https://grants.at/en/?q=chemistry",
                source_type="FUNDER",
                funding_family="GOVERNMENT_SCHOLARSHIP",
                discovered_by="stub",
            )

    pages = {
        "https://grants.at/en?q=chemistry": listing_html,
        "https://grants.at/en/?q=chemistry": listing_html,
        "https://grants.at/en/detail/101": (
            b'<html><body><a href="https://univie.ac.at/en/master-chemistry-stipend">'
            b"Apply at University of Vienna</a></body></html>"
        ),
    }
    hopper = CatalogueHopSource(
        inner=_InnerStub(),
        fetch_html=lambda u: pages.get(u, b""),
        record_pointers=False,
    )
    hopped = list(hopper.find(DiscoveryQuery(field="chemistry", country_code="AT")))
    assert [h.canonical_url for h in hopped] == [
        "https://univie.ac.at/en/master-chemistry-stipend"
    ]


def test_social_announcement_llm_triage_filters_ceremonies_and_verifies_urls() -> None:
    import json
    from types import SimpleNamespace

    from apps.accounts.field_taxonomy import OpenRouterTaxonomyParser
    from apps.research.social_monitor import (
        MinistryChannel,
        extract_announcements_from_html,
        triage_announcement_with_llm,
    )

    channel = MinistryChannel(
        slug="sa-drasatolya-tg",
        country_code="SA",
        ministry_name="Study in Saudi",
        ministry_domain="studyinsaudi.sa",
        channel_kind="telegram_s",
        url="https://t.me/s/drasatolya",
    )

    # 1. LLM triage drops a past-winners ceremony post even when it contains Master's keywords
    ceremony_parser = OpenRouterTaxonomyParser(
        api_key="sk-or-test",
        post_completion=lambda **_k: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "is_active_masters_call": False,
                                "scheme_name": "",
                                "deadline_text": "",
                                "funding_summary": "",
                                "preferred_urls": [],
                            }
                        )
                    )
                )
            ]
        ),
    )
    ceremony_html = (
        b'<div class="tgme_widget_message_wrap">'
        b"Congratulations to last year's Master's scholarship winners at KSU! "
        b"https://ksu.edu.sa/en/news/2025-ceremony"
        b"</div></div></div>"
    )
    assert (
        extract_announcements_from_html(
            channel, ceremony_html, record_pointers=False, parser=ceremony_parser
        )
        == ()
    )

    # 2. LLM triage keeps active calls, extracts structured fields, prioritizes verified URLs,
    # and strips any smuggled URL not present in candidate_urls
    active_parser = OpenRouterTaxonomyParser(
        api_key="sk-or-test",
        post_completion=lambda **_k: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "is_active_masters_call": True,
                                "scheme_name": "Study in Saudi Master's Scholarship",
                                "deadline_text": "15 شعبان 1447 هـ",
                                "funding_summary": "Full tuition waiver and monthly stipend",
                                "preferred_urls": [
                                    "https://studyinsaudi.sa/en/apply",
                                    "https://smuggled.evil.example/phish",
                                ],
                            }
                        )
                    )
                )
            ]
        ),
    )
    active_html = (
        '<div class="tgme_widget_message_wrap">'
        "تعلن منصة ادرس في السعودية عن فتح باب التقديم على منح الماجستير 1447 هـ. "
        "More info: https://studyinsaudi.sa/en/about "
        "Apply at: https://studyinsaudi.sa/en/apply"
        "</div></div></div>"
    ).encode()
    anns = extract_announcements_from_html(
        channel, active_html, record_pointers=False, parser=active_parser
    )
    assert len(anns) == 1
    ann = anns[0]
    assert ann.scheme_name == "Study in Saudi Master's Scholarship"
    assert ann.deadline_text == "15 شعبان 1447 هـ"
    assert ann.funding_summary == "Full tuition waiver and monthly stipend"
    assert ann.outbound_urls[0] == "https://studyinsaudi.sa/en/apply"
    assert all("smuggled.evil.example" not in u for u in ann.outbound_urls)

    # Direct `triage_announcement_with_llm` check on URL allowlist enforcement
    direct = triage_announcement_with_llm(
        "Master's scholarship open",
        ["https://studyinsaudi.sa/en/apply"],
        parser=active_parser,
        channel_slug="sa-drasatolya-tg",
    )
    assert direct is not None
    assert direct.preferred_urls == ["https://studyinsaudi.sa/en/apply"]


def test_default_intake_start_for_southern_hemisphere_and_biannual_calendars() -> None:
    import datetime as dt

    from apps.funding.validity import default_intake_start_for_country

    # Northern Hemisphere default: Sept 1
    assert default_intake_start_for_country("DE", 2027) == dt.date(2027, 9, 1)
    assert default_intake_start_for_country("SA", 2027) == dt.date(2027, 9, 1)

    # Southern Hemisphere (AU, NZ): primary Feb 15, mid-year Jul 15
    assert default_intake_start_for_country("AU", 2027, today=dt.date(2027, 1, 10)) == dt.date(
        2027, 2, 15
    )
    assert default_intake_start_for_country("AU", 2027, today=dt.date(2027, 4, 1)) == dt.date(
        2027, 7, 15
    )

    # South Korea (KR): March 1 and Sept 1
    assert default_intake_start_for_country("KR", 2027, today=dt.date(2027, 2, 1)) == dt.date(
        2027, 3, 1
    )
    assert default_intake_start_for_country("KR", 2027, today=dt.date(2027, 5, 1)) == dt.date(
        2027, 9, 1
    )

    # Japan (JP): April 1 and October 1
    assert default_intake_start_for_country("JP", 2027, today=dt.date(2027, 2, 1)) == dt.date(
        2027, 4, 1
    )
    assert default_intake_start_for_country("JP", 2027, today=dt.date(2027, 6, 1)) == dt.date(
        2027, 10, 1
    )


def test_fetch_channel_bytes_cheap_first_falls_back_on_error() -> None:
    from apps.research.social_monitor import fetch_channel_bytes_cheap_first

    fallback_called: list[str] = []

    def fake_fallback(u: str) -> bytes:
        fallback_called.append(u)
        return b"<html>fallback body</html>"

    # Private/loopback URL fails `validate_public_url` and falls back cleanly
    body = fetch_channel_bytes_cheap_first("http://127.0.0.1/test", fake_fallback)
    assert body == b"<html>fallback body</html>"
    assert fallback_called == ["http://127.0.0.1/test"]


