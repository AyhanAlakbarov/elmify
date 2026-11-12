"""Finding national programme and scholarship databases: the word rule, both
routes, and the command's CSV."""

import csv
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from apps.research import national_databases as nd


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        # Link texts copied from the EC profiles on 2026-10-13.
        ("Campus France catalogue", nd.PROGRAMMES),
        ("Grant search engine", nd.SCHOLARSHIPS),
        ("Search for scholarships on the DAAD database", nd.SCHOLARSHIPS),
        ("complete overview of the international programmes in Germany", nd.PROGRAMMES),
        ("Studyfinder", nd.PROGRAMMES),
        ("search for programmes via the official platform", nd.PROGRAMMES),
        ("range of scholarships", nd.SCHOLARSHIPS),
        ("More details on fees", ""),
        ("How to apply for a visa if needed", ""),
        ("Get to know the German higher education system", ""),
        ("More help with finding accommodation in Germany", ""),
        ("grants database", nd.SCHOLARSHIPS),
        ("Universitaly portal", nd.PROGRAMMES),
        ("browse the database", nd.PROGRAMMES),
        ("Database of higher education institutions and their offerings", nd.PROGRAMMES),
        ("Register of higher education institutions in Bulgaria", nd.INSTITUTIONS),
        ("Types of university and education institutions", ""),
        ("Application and admission process guidance", ""),
        ("Austrian Students’ Union", ""),
    ],
)
def test_a_profile_link_is_sorted_by_its_text(text, kind) -> None:
    assert nd.classify(text) == kind


@pytest.mark.parametrize(
    ("host", "flag"),
    [("www.studyinjapan.go.jp", True), ("studyinturkiye.gov.tr", True),
     ("www.campusfrance.org", False), ("educationusa.state.gov", True), ("daad.de", False),
     ("www.gov.uk", True)],
)
def test_a_government_host_is_flagged_for_the_reviewer(host, flag) -> None:
    assert nd.government_host(host) is flag


_INDEX = b"""<main><a href="/study-in-europe/country-profiles/france">France</a>
<a href="/study-in-europe/country-profiles/the-netherlands">The Netherlands</a>
<a href="/about">About</a></main>"""
_FRANCE = b"""<main>
<a href="https://www.campusfrance.org/en/programs">Campus France catalogue</a>
<a href="https://campusbourses.campusfrance.org/">Grant search engine</a>
<a href="https://france-visas.gouv.fr/">How to apply for a visa if needed</a>
<a href="/study-in-europe/planning-your-studies">Planning your studies</a>
<a href="https://www.campusfrance.org/en/programs">Campus France catalogue</a>
</main>"""


def test_the_profile_route_keeps_off_site_database_links_once() -> None:
    profiles = nd.profile_links(_INDEX)
    assert profiles == {
        "France": "https://education.ec.europa.eu/study-in-europe/country-profiles/france",
        "The Netherlands":
            "https://education.ec.europa.eu/study-in-europe/country-profiles/the-netherlands",
    }
    rows = nd.profile_candidates("FR", profiles["France"], _FRANCE)
    assert [(r.kind, r.url) for r in rows] == [
        (nd.PROGRAMMES, "https://www.campusfrance.org/en/programs"),
        (nd.SCHOLARSHIPS, "https://campusbourses.campusfrance.org/"),
    ]


def test_the_search_route_asks_both_questions_and_keeps_each_url_once() -> None:
    asked: list[str] = []

    def search(query: str) -> list[str]:
        asked.append(query)
        return ["https://www.studyinjapan.go.jp/en/", "https://blog.example.com/japan"]

    rows = nd.search_candidates("JP", "Japan", search)
    assert len(asked) == 3 and all("Japan" in q for q in asked)
    assert [(r.kind, r.url, r.government_host) for r in rows] == [
        (nd.PROGRAMMES, "https://www.studyinjapan.go.jp/en/", True),
        (nd.PROGRAMMES, "https://blog.example.com/japan", False),
    ]


@pytest.mark.django_db
def test_the_command_writes_candidates_from_both_routes(monkeypatch, settings, tmp_path) -> None:
    settings.EXA_API_KEY = "k"
    pages = {nd.EC_INDEX: _INDEX,
             "https://education.ec.europa.eu/study-in-europe/country-profiles/france": _FRANCE}
    monkeypatch.setattr(
        "apps.research.management.commands.find_national_databases.fetch_page",
        lambda url, **_: SimpleNamespace(body=pages.get(url, b""), outcome="FETCHED"),
    )

    class _Exa:
        def __init__(self, api_key: str) -> None:
            pass

        def search(self, request, meter=None):
            assert request.denylist == ()  # the national sites are on the aggregator list
            return iter(["https://www.studyinjapan.go.jp/en/"])

    monkeypatch.setattr(
        "apps.research.management.commands.find_national_databases.ExaProvider", _Exa
    )
    out = tmp_path / "db.csv"
    call_command("find_national_databases", "--countries", "FR,JP", "--out", str(out))
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [(r["country_code"], r["kind"], r["route"], r["status"]) for r in rows] == [
        ("FR", nd.PROGRAMMES, "ec_profile", "candidate"),
        ("FR", nd.SCHOLARSHIPS, "ec_profile", "candidate"),
        ("FR", nd.INSTITUTIONS, "search", "candidate"),  # France's profile links no register
        ("JP", nd.PROGRAMMES, "search", "candidate"),
    ]


@pytest.mark.django_db
def test_a_profile_without_a_scholarship_link_searches_for_that_kind_only(
    monkeypatch, settings, tmp_path
) -> None:
    settings.EXA_API_KEY = "k"
    programmes_only = b'<main><a href="https://www.studyinnl.org/finder">Studyfinder</a></main>'
    index = (b'<main><a href="/study-in-europe/country-profiles/the-netherlands">'
             b"The Netherlands</a></main>")
    pages = {nd.EC_INDEX: index,
             "https://education.ec.europa.eu/study-in-europe/country-profiles/the-netherlands":
                 programmes_only}
    monkeypatch.setattr(
        "apps.research.management.commands.find_national_databases.fetch_page",
        lambda url, **_: SimpleNamespace(body=pages.get(url, b""), outcome="FETCHED"),
    )
    asked: list[str] = []

    class _Exa:
        def __init__(self, api_key: str) -> None:
            pass

        def search(self, request, meter=None):
            asked.append(request.query)
            return iter([f"https://www.studyinnl.org/{len(asked)}"])

    monkeypatch.setattr(
        "apps.research.management.commands.find_national_databases.ExaProvider", _Exa
    )
    out = tmp_path / "db.csv"
    call_command("find_national_databases", "--countries", "NL", "--out", str(out))
    assert len(asked) == 2 and "scholarships" in asked[0] and "licensed" in asked[1]
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [(r["kind"], r["route"]) for r in rows] == [
        (nd.PROGRAMMES, "ec_profile"), (nd.SCHOLARSHIPS, "search"), (nd.INSTITUTIONS, "search"),
    ]


@pytest.mark.django_db
def test_deep_mode_searches_all_seven_tiers_and_local_languages_even_for_profile_countries(
    monkeypatch, settings, tmp_path
) -> None:
    settings.EXA_API_KEY = "k"
    pages = {
        nd.EC_INDEX: _INDEX,
        "https://education.ec.europa.eu/study-in-europe/country-profiles/france": _FRANCE,
    }
    monkeypatch.setattr(
        "apps.research.management.commands.find_national_databases.fetch_page",
        lambda url, **_: SimpleNamespace(body=pages.get(url, b""), outcome="FETCHED"),
    )
    requests_seen: list[tuple[str, str, str]] = []

    class _Exa:
        def __init__(self, api_key: str) -> None:
            pass

        def search(self, request, meter=None):
            requests_seen.append((request.language, request.phrasing, request.query))
            return iter([f"https://monmaster.gouv.fr/{len(requests_seen)}"])

    monkeypatch.setattr(
        "apps.research.management.commands.find_national_databases.ExaProvider", _Exa
    )
    out = tmp_path / "deep.csv"
    call_command("find_national_databases", "--countries", "FR", "--deep", "--out", str(out))
    # 7 English queries (ALL_QUERIES) + 4 French localized queries
    assert sum(1 for lang, phrasing, _ in requests_seen if phrasing == "english") == 7
    assert any(lang == "fr" and phrasing == "local" for lang, phrasing, _ in requests_seen)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    kinds = {r["kind"] for r in rows}
    assert {
        nd.PROGRAMMES,
        nd.SCHOLARSHIPS,
        nd.INSTITUTIONS,
        nd.QUALIFICATIONS_REGISTER,
        nd.SUBNATIONAL_SCHOLARSHIPS,
        nd.FOUNDATION_DIRECTORIES,
        nd.EXCELLENCE_GRADUATE_SCHOOLS,
    } <= kinds


def test_load_curated_databases_returns_multi_tier_portals_across_countries() -> None:
    de_rows = nd.load_curated_databases("DE")
    de_urls = {r.url for r in de_rows}
    assert "https://www.stipendienlotse.de/" in de_urls
    dfg_url = "https://www.dfg.de/en/research-funding/funding-initiative/excellence-strategy"
    assert dfg_url in de_urls

    fr_rows = nd.load_curated_databases("FR")
    fr_urls = {r.url for r in fr_rows}
    assert "https://www.monmaster.gouv.fr/" in fr_urls
    anr_url = "https://anr.fr/fr/investissements-davenir/ecoles-universitaires-de-recherche-eur/"
    assert anr_url in fr_urls

    it_rows = nd.load_curated_databases("IT")
    it_urls = {r.url for r in it_rows}
    mur_url = "https://www.mur.gov.it/it/aree-tematiche/universita/dipartimenti-di-eccellenza"
    assert mur_url in it_urls

    for code in ("CN", "JP", "KR"):
        assert len(nd.load_curated_databases(code)) >= 3


def test_every_target_country_has_curated_programme_and_scholarship_databases() -> None:
    from apps.research.destinations import TARGET_COUNTRIES

    prog_kinds = {nd.PROGRAMMES, nd.QUALIFICATIONS_REGISTER}
    schol_kinds = {nd.SCHOLARSHIPS, nd.SUBNATIONAL_SCHOLARSHIPS}

    for cc in TARGET_COUNTRIES:
        rows = [
            r
            for r in nd.load_curated_databases(cc)
            if r.route in ("curated", "ec_profile")
        ]
        assert any(r.kind in prog_kinds for r in rows), (
            f"{cc} missing curated programme/qualification register database"
        )
        assert any(r.kind in schol_kinds for r in rows), (
            f"{cc} missing curated scholarship database"
        )


def test_build_portal_search_urls_expands_field_and_localizes_terms() -> None:
    de_urls = nd.build_portal_search_urls("DE", field="AI with chemistry")
    assert any("daad.de" in u and "digital+chemistry" in u for u in de_urls)
    assert any("hochschulkompass.de" in u and "Chemoinformatik" in u for u in de_urls)

    fr_urls = nd.build_portal_search_urls("FR", field="AI with chemistry")
    assert any("monmaster.gouv.fr/recherche?recherche=" in u for u in fr_urls)
    assert any("chimie" in u.lower() for u in fr_urls)


def test_build_database_site_requests_and_query_national_databases_hop_to_official_hosts() -> None:
    reqs = nd.build_database_site_requests("FR", field="AI with chemistry")
    assert reqs
    assert all(r.denylist == () for r in reqs)
    queries = [r.query for r in reqs]
    assert any("site:campusbourses.campusfrance.org" in q for q in queries)
    assert any("site:taughtie.campusfrance.org" in q for q in queries)
    assert any("chimie numérique" in q or "chémoinformatique" in q for q in queries)

    class _StubProvider:
        name = "exa"

        def search(self, request, meter=None):
            if "campusbourses.campusfrance.org" in request.query:
                return ["https://campusbourses.campusfrance.org/#/program/391"]
            return []

    portal_html = b"""
    <html><body>
      <a href="https://icfrc.fr/csc-graduate-school/">Foundation for Chemistry Research (CSC)</a>
      <a href="https://www.unistra.fr/fr/formation/master-csc">Strasbourg CSC Master</a>
      <a href="https://www.campusfrance.org/fr/privacy">Privacy policy</a>
    </body></html>
    """
    leads = nd.query_national_databases(
        "FR",
        field="AI with chemistry",
        fetch_html=lambda url: portal_html,
        search_provider=_StubProvider(),
    )
    lead_urls = {lead.canonical_url for lead in leads}
    assert "https://icfrc.fr/csc-graduate-school" in lead_urls
    assert "https://www.unistra.fr/fr/formation/master-csc" in lead_urls
    assert all("campusfrance.org" not in u for u in lead_urls)


