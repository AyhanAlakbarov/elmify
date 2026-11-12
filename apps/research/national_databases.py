"""Each country's official programme catalogue and scholarship database, found, not typed.

Campus France's catalogue and its Campus Bourses scholarship search are what a
student or counsellor reads first, and most countries run the same pair. Here
they are found by one repeatable method per route, written as candidates for a
person to confirm (`docs/research/national-study-databases.csv`), and never
typed from memory:

- **ec_profile** -- the European Commission's "Study in Europe" country profiles,
  one official page per country (33 on 2026-10-13), each linking the national
  programme catalogue and scholarship search ("Campus France catalogue",
  "Grant search engine", "Search for scholarships on the DAAD database"). The
  link text is English on every profile, so a closed word rule sorts it.
- **search** -- for a country with no profile, and for whichever of the two a
  profile does not link: English Exa searches for the official site that
  searches all master's programmes, and the one that searches scholarships.
  A hit on a government host is flagged; every hit is a candidate only.

What a confirmed row is for, and what it is not: a NAME and IDENTITY source --
programmes and funders to look up on their own sites -- never evidence for a
claim (CLAUDE.md, Web fetching: aggregator pages are read for organisation names
only). That is why these hosts stay on `domains.AGGREGATOR_DOMAINS`.
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit

from apps.accounts.field_taxonomy import localized_field_terms, resolve_field_taxonomy

from .catalogue_hop import extract_catalogue_hops
from .discovery import DiscoveryQuery, ResearchLead
from .domains import STEERING
from .harvest import anchors
from .providers import SearchProvider, SearchRequest

EC_INDEX = "https://education.ec.europa.eu/study-in-europe/country-profiles"
PROGRAMMES = "PROGRAMMES"
SCHOLARSHIPS = "SCHOLARSHIPS"
#: An official register of the country's institutions -- an identity list, kept
#: because it is the denominator a programme catalogue is missing.
INSTITUTIONS = "INSTITUTIONS"
#: Search-database tiers across all 57 countries (Master's focus):
#: - QUALIFICATIONS_REGISTER: ministry / accreditation register of all accredited
#:   Master's degree programmes (e.g. MonMaster FR, Hochschulkompass DE, Universitaly IT,
#:   CHSI Master's directory CN, Studyinfo FI).
#: - SUBNATIONAL_SCHOLARSHIPS: regional / state / provincial / municipal Master's
#:   scholarship portals (e.g. Study in Flanders Master Mind, Bavarian BAYHOST,
#:   China provincial government scholarships, Italian regional DSU/EDISU).
#: - FOUNDATION_DIRECTORIES: national directories of charitable / private scholarship
#:   foundations (e.g. Stipendienlotse / Bundesverband Deutscher Stiftungen DE,
#:   Fondation de France FR, Grants.at AT, JASSO foundation directory JP).
#: - EXCELLENCE_GRADUATE_SCHOOLS: national funded graduate-school & excellence-department
#:   directories that attach Master's scholarships/waivers to specific degrees
#:   (e.g. France ANR EUR, Italy MUR Dipartimenti di Eccellenza, Germany DFG
#:   Exzellenzcluster / Max Planck IMPRS Master's tracks, Korea BK21 Four, Japan MEXT WISE).
QUALIFICATIONS_REGISTER = "QUALIFICATIONS_REGISTER"
SUBNATIONAL_SCHOLARSHIPS = "SUBNATIONAL_SCHOLARSHIPS"
FOUNDATION_DIRECTORIES = "FOUNDATION_DIRECTORIES"
EXCELLENCE_GRADUATE_SCHOOLS = "EXCELLENCE_GRADUATE_SCHOOLS"

#: Words on the EC profiles' link text, from all 33 profiles on 2026-10-13
#: ("grants database", "Universitaly portal", "browse the database", "Database
#: of higher education institutions and their offerings", "Register of higher
#: education institutions"). Scholarship first: "Search for scholarships on the
#: DAAD database" names both. A candidate list for a person to confirm, so the
#: rule leans to keeping a link.
_SCHOLARSHIP = re.compile(r"scholarship|grant|bursar|funding|stipend", re.IGNORECASE)
_PROGRAMME = re.compile(
    r"programme|program\b|programs\b|course|study ?finder|catalogue|catalog\b|degrees?\b"
    r"|offerings|database|portal|browse|search",
    re.IGNORECASE,
)
_INSTITUTION = re.compile(r"register of|registry|list of (higher|universit)", re.IGNORECASE)
#: Links on a profile that are practical or explanatory, not a database.
_NOT_A_DATABASE = re.compile(
    r"visa|insurance|accommodation|housing|living|cost|fee|health|work|job|budget|system"
    r"|types of|guidance|union|residence",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    country_code: str
    kind: str
    url: str
    label: str
    found_on: str
    route: str
    government_host: bool


def classify(text: str) -> str:
    """PROGRAMMES, SCHOLARSHIPS, INSTITUTIONS or "" for one link's text."""
    if _SCHOLARSHIP.search(text):
        return SCHOLARSHIPS
    if _NOT_A_DATABASE.search(text):
        return ""
    if _INSTITUTION.search(text):
        return INSTITUTIONS
    return PROGRAMMES if _PROGRAMME.search(text) else ""


def government_host(host: str) -> bool:
    """A host under a government label in any country (`gov`, `go`, `govt`,
    `gouv`, `gob`, `admin` as a second level, or `.gov`/`.gouv.fr` style). A
    flag for the reviewer, not a verdict: most national agencies (campusfrance.org,
    daad.de) sit in flat namespaces and are not flagged."""
    labels = host.casefold().strip(".").split(".")
    marks = {"gov", "go", "govt", "gouv", "gob", "admin", "government"}
    return labels[-1] == "gov" or any(label in marks for label in labels[:-1])


def profile_links(index_html: bytes, *, base: str = EC_INDEX) -> dict[str, str]:
    """{country name as the index prints it: profile URL}."""
    return {
        a.text.strip(): urljoin(base, a.href)
        for a in anchors(index_html)
        if "/country-profiles/" in a.href and a.text.strip()
    }


def profile_candidates(country_code: str, profile_url: str, html: bytes) -> list[Candidate]:
    """The database links on one EC profile: off-site, sorted by their text."""
    found: list[Candidate] = []
    seen: set[str] = set()
    for a in anchors(html):
        url = urljoin(profile_url, a.href)
        host = urlsplit(url).hostname or ""
        if not host or host.endswith("europa.eu") or url in seen:
            continue
        kind = classify(a.text)
        if kind:
            seen.add(url)
            found.append(
                Candidate(
                    country_code,
                    kind,
                    url,
                    " ".join(a.text.split()),
                    profile_url,
                    "ec_profile",
                    government_host(host),
                )
            )
    return found


QUERIES = {
    PROGRAMMES: "The official national portal of {country} to search all master's degree "
    "programmes at its universities, run by the government or its agency.",
    SCHOLARSHIPS: "The official national database of {country} to search scholarships for "
    "international master's students, run by the government or its agency.",
    # Where a country has no programme catalogue (the Gulf, Brunei, Singapore,
    # Armenia on 2026-10-14), the regulator's register of licensed institutions is
    # the complete list a programme search starts from.
    INSTITUTIONS: "The official list of licensed or accredited universities in {country}, "
    "published by the ministry or the higher-education regulator.",
}

DEEP_QUERIES = {
    QUALIFICATIONS_REGISTER: (
        "The official ministry or accreditation register of all accredited Master's "
        "degree programmes in {country}."
    ),
    SUBNATIONAL_SCHOLARSHIPS: (
        "Official regional, state, provincial, or municipal scholarship portals for "
        "Master's students in {country}."
    ),
    FOUNDATION_DIRECTORIES: (
        "Official national directory or database of private scholarship foundations "
        "and charitable trusts funding Master's students in {country}."
    ),
    EXCELLENCE_GRADUATE_SCHOOLS: (
        "Official national directory of government-funded graduate schools, excellence "
        "clusters, or excellence departments offering Master's scholarships in {country}."
    ),
}

ALL_QUERIES: dict[str, str] = {**QUERIES, **DEEP_QUERIES}

#: Native-language query templates for multi-tier Master's database discovery.
LOCALIZED_DEEP_QUERIES: dict[str, dict[str, str]] = {
    "de": {
        PROGRAMMES: "Offizielles Hochschulportal Studiengangsuche Masterstudiengänge {country}",
        SCHOLARSHIPS: (
            "Offizielle Stipendiendatenbank Masterstudium internationale Studierende {country}"
        ),
        FOUNDATION_DIRECTORIES: "Stiftungsverzeichnis Stipendien Masterstudium {country}",
        EXCELLENCE_GRADUATE_SCHOOLS: (
            "Exzellenzcluster Graduiertenschulen Master Stipendium {country}"
        ),
    },
    "fr": {
        PROGRAMMES: (
            "Portail officiel national trouver un master catalogue des formations {country}"
        ),
        SCHOLARSHIPS: (
            "Annuaire officiel des bourses d'études master étudiants internationaux {country}"
        ),
        FOUNDATION_DIRECTORIES: "Annuaire des fondations bourses d'études master {country}",
        EXCELLENCE_GRADUATE_SCHOOLS: (
            "Écoles Universitaires de Recherche EUR bourses de master {country}"
        ),
    },
    "it": {
        PROGRAMMES: "Portale ufficiale ministero ricerca corsi di laurea magistrale {country}",
        SCHOLARSHIPS: (
            "Banca dati borse di studio laurea magistrale studenti internazionali {country}"
        ),
        SUBNATIONAL_SCHOLARSHIPS: (
            "Bando borse di studio regionali DSU EDISU laurea magistrale {country}"
        ),
        EXCELLENCE_GRADUATE_SCHOOLS: (
            "Dipartimenti di Eccellenza MUR borse di studio laurea magistrale {country}"
        ),
    },
    "es": {
        PROGRAMMES: "Buscador oficial de títulos universitarios máster oficial {country}",
        SCHOLARSHIPS: "Buscador oficial de becas y ayudas para estudios de máster {country}",
        FOUNDATION_DIRECTORIES: "Directorio de fundaciones becas de posgrado máster {country}",
    },
    "nl": {
        PROGRAMMES: "Officieel overzicht masteropleidingen hoger onderwijs {country}",
        SCHOLARSHIPS: "Beurzen database internationale masterstudenten {country}",
    },
    "pl": {
        PROGRAMMES: "Oficjalna wyszukiwarka studiów magisterskich RAD-on {country}",
        SCHOLARSHIPS: "Baza stypendiów dla studentów zagranicznych studia magisterskie {country}",
    },
    "zh": {
        PROGRAMMES: "中国研究生招生信息网 硕士专业目录 留学中国 硕士项目数据库",
        SCHOLARSHIPS: "中国政府奖学金 留学基金委 省级政府奖学金 硕士生",
        SUBNATIONAL_SCHOLARSHIPS: "来华留学 省政府奖学金 市政府奖学金 硕士",
    },
    "ja": {
        PROGRAMMES: "日本留学 大学院 修士課程 検索 データベース 公式",
        SCHOLARSHIPS: "日本学生支援機構 JASSO 奨学金 検索 大学院 修士 留学生",
        EXCELLENCE_GRADUATE_SCHOOLS: "卓越大学院プログラム スーパーグローバル大学 修士 奨学金",
    },
    "ko": {
        PROGRAMMES: "한국유학 종합시스템 대학원 석사과정 검색",
        SCHOLARSHIPS: "정부초청외국인장학생 GKS 석사 장학금 안내",
        EXCELLENCE_GRADUATE_SCHOOLS: "BK21 FOUR 교육연구단 석사 장학금 대학원",
    },
    "tr": {
        PROGRAMMES: "YÖK yükseköğretim lisansüstü yüksek lisans programları atlası",
        SCHOLARSHIPS: "Türkiye Bursları ve vakıf yüksek lisans burs rehberi",
    },
    "ru": {
        PROGRAMMES: "Официальный портал магистратура программы высшего образования {country}",
        SCHOLARSHIPS: "Государственные стипендии и гранты для иностранных магистрантов {country}",
    },
    "ar": {
        PROGRAMMES: "البوابة الرسمية لبرامج الماجستير والجامعات المعتمدة {country}",
        SCHOLARSHIPS: "قاعدة بيانات المنح الدراسية لطلاب الماجستير الدوليين {country}",
        QUALIFICATIONS_REGISTER: (
            "السجل الوطني للمؤهلات والبرامج الأكاديمية المعتمدة ماجستير {country}"
        ),
        FOUNDATION_DIRECTORIES: "دليل المؤسسات والصناديق المانحة للمنح الدراسية ماجستير {country}",
    },
    "pt": {
        PROGRAMMES: (
            "Portal oficial pesquisa de cursos de mestrado 2.º ciclo ensino superior {country}"
        ),
        SCHOLARSHIPS: "Bolsas de estudo mestrado pós-graduação estudantes internacionais {country}",
        QUALIFICATIONS_REGISTER: (
            "Registo oficial cursos de mestrado acreditados DGES A3ES {country}"
        ),
        FOUNDATION_DIRECTORIES: "Diretório de fundações bolsas de estudo mestrado {country}",
    },
    "az": {
        PROGRAMMES: "Magistratura ixtisasları və ali təhsil müəssisələri rəsmi portalı {country}",
        SCHOLARSHIPS: "Magistratura təhsili üçün dövlət proqramı və təqaüdlər {country}",
        QUALIFICATIONS_REGISTER: (
            "Akkreditasiya olunmuş magistratura proqramları reyestri {country}"
        ),
    },
    "kk": {
        PROGRAMMES: "Магистратура білім беру бағдарламаларының ресми тізілімі {country}",
        SCHOLARSHIPS: "Магистратура мемлекеттік білім беру гранттары мен стипендиялар {country}",
        QUALIFICATIONS_REGISTER: (
            "Жоғары және жоғары оқу орнынан кейінгі білім беру тізілімі {country}"
        ),
    },
    "uz": {
        PROGRAMMES: (
            "Magistratura mutaxassisliklari va oliy ta'lim dasturlari rasmiy portali {country}"
        ),
        SCHOLARSHIPS: "Magistratura uchun davlat grantlari va xalqaro stipendiyalar {country}",
        QUALIFICATIONS_REGISTER: (
            "Akkreditatsiyadan o'tgan magistratura dasturlari reyestri {country}"
        ),
    },
    "ka": {
        PROGRAMMES: "სამაგისტრო პროგრამების ოფიციალური კატალოგი და უნივერსიტეტები {country}",
        SCHOLARSHIPS: "სამაგისტრო სტიპენდიები და სახელმწიფო სასწავლო გრანტები {country}",
        QUALIFICATIONS_REGISTER: (
            "აკრედიტებული უმაღლესი საგანმანათლებლო პროგრამების რეესტრი {country}"
        ),
    },
    "sr": {
        PROGRAMMES: "Baza obrazovanja akreditovani master akademski studijski programi {country}",
        SCHOLARSHIPS: "Konkurs za stipendije master studije Ministarstvo prosvete {country}",
        QUALIFICATIONS_REGISTER: (
            "Vodič kroz akreditovane visokoškolske ustanove i master programe {country}"
        ),
    },
    "hr": {
        PROGRAMMES: "Preglednik studijskih programa sveučilišni diplomski studij {country}",
        SCHOLARSHIPS: "Državne stipendije i natječaji za diplomski studij {country}",
        QUALIFICATIONS_REGISTER: "Upisnik studijskih programa HKO diplomski studij {country}",
        FOUNDATION_DIRECTORIES: (
            "Registar zaklada stipendije za studente diplomskih studija {country}"
        ),
    },
    "cs": {
        PROGRAMMES: "Oficiální vyhledávač navazující magisterské studijní programy {country}",
        SCHOLARSHIPS: "Databáze stipendií pro zahraniční studenty magisterské studium {country}",
        QUALIFICATIONS_REGISTER: (
            "Registr vysokých škol a uskutečňovaných studijních programů MŠMT {country}"
        ),
    },
    "fi": {
        PROGRAMMES: "Opintopolku ylempi korkeakoulututkinto maisteriohjelmat haku {country}",
        SCHOLARSHIPS: "Apurahat ja stipendit maisteriopintoihin säätiöt {country}",
        FOUNDATION_DIRECTORIES: (
            "Säätiöt ja rahastot apurahat jatko- ja maisteriopintoihin {country}"
        ),
    },
    "sv": {
        PROGRAMMES: "Officiell söktjänst masterprogram högskola och universitet {country}",
        SCHOLARSHIPS: "Stipendier för internationella masterstudenter {country}",
        FOUNDATION_DIRECTORIES: "Stiftelser och stipendiefonder för masterstudier {country}",
    },
    "ur": {
        PROGRAMMES: "ہائر ایجوکیشن کمیشن منظور شدہ ماسٹرز ایم فل ڈگری پروگرامز {country}",
        SCHOLARSHIPS: "ماسٹرز اور پوسٹ گریجویٹ اسکالرشپس ہائر ایجوکیشن کمیشن {country}",
    },
    "bg": {
        PROGRAMMES: "Рейтингова система на висшите училища магистърски програми {country}",
        SCHOLARSHIPS: "Държавни стипендии за чуждестранни студенти магистратура {country}",
    },
    "el": {
        PROGRAMMES: "Επίσημος κατάλογος Προγραμμάτων Μεταπτυχιακών Σπουδών ΠΜΣ {country}",
        SCHOLARSHIPS: "Υποτροφίες μεταπτυχιακών σπουδών ΙΚΥ {country}",
    },
    "lt": {
        PROGRAMMES: (
            "Atvira informavimo konsultavimo orientavimo sistema AIKOS "
            "magistrantūros studijos {country}"
        ),
        SCHOLARSHIPS: (
            "Valstybinės stipendijos užsienio studentams magistrantūros studijos {country}"
        ),
    },
    "no": {
        PROGRAMMES: (
            "Offisiell studieportal masterprogram ved norske universiteter og høyskoler {country}"
        ),
        SCHOLARSHIPS: "Stipend og støtteordninger for internasjonale masterstudenter {country}",
    },
    "et": {
        PROGRAMMES: "Eesti Hariduse Infosüsteem EHIS magistriõppe õppekavad {country}",
        SCHOLARSHIPS: "Haridus- ja Noorteamet HARNO magistriõppe stipendiumid {country}",
    },
    "da": {
        PROGRAMMES: "UddannelsesGuiden kandidatuddannelser officielle studieportal {country}",
        SCHOLARSHIPS: "Statslige stipendier og legater til kandidatstuderende {country}",
    },
    "hu": {
        PROGRAMMES: "Felvi mesterképzések hivatalos felsőoktatási kereső {country}",
        SCHOLARSHIPS: "Stipendium Hungaricum és állami mesterképzési ösztöndíjak {country}",
    },
    "is": {
        PROGRAMMES: "Opinber leit að meistaranámi við háskóla á Íslandi {country}",
        SCHOLARSHIPS: "Rannís styrkir og námsstyrkir til meistaranáms {country}",
    },
    "lv": {
        PROGRAMMES: (
            "Valsts izglītības informācijas sistēma akreditētās "
            "maģistra studiju programmas {country}"
        ),
        SCHOLARSHIPS: "Latvijas valsts stipendijas ārvalstu maģistrantūras studentiem {country}",
    },
    "sk": {
        PROGRAMMES: (
            "Portál vysokých škôl register študijných programov druhý stupeň magister {country}"
        ),
        SCHOLARSHIPS: (
            "Národný štipendijný program SAIA štipendiá pre magisterské štúdium {country}"
        ),
    },
    "sl": {
        PROGRAMMES: (
            "eVŠ evidenca visokošolskih zavodov in magistrskih študijskih programov {country}"
        ),
        SCHOLARSHIPS: "Javni štipendijski sklad štipendije za magistrski študij {country}",
    },
    "hy": {
        PROGRAMMES: "ՀՀ ԿԳՄՍՆ հավատարմագրված մագիստրոսական ծրագրերի ցանկ {country}",
        SCHOLARSHIPS: "Պետական կրթաթոշակներ մագիստրատուրայի ուսանողների համար {country}",
    },
    "ms": {
        PROGRAMMES: "Daftar Kelayakan Malaysia MQR program sarjana diiktiraf {country}",
        SCHOLARSHIPS: "Biasiswa kerajaan pengajian pascasiswazah sarjana {country}",
    },
    "ro": {
        PROGRAMMES: (
            "Registrul Național al Calificărilor din Învățământul Superior "
            "RNCIS programe de master {country}"
        ),
        SCHOLARSHIPS: (
            "Burse oferite de statul român pentru studii universitare de masterat {country}"
        ),
    },
    "hi": {
        PROGRAMMES: "उच्च शिक्षा विभाग मान्यता प्राप्त स्नातकोत्तर मास्टर डिग्री कार्यक्रम {country}",
        SCHOLARSHIPS: "अंतर्राष्ट्रीय छात्रों के लिए स्नातकोत्तर छात्रवृत्ति पोर्टल {country}",
    },
    "vi": {
        PROGRAMMES: (
            "Cổng thông tin chính thức chương trình đào tạo thạc sĩ "
            "Bộ Giáo dục và Đào tạo {country}"
        ),
        SCHOLARSHIPS: "Học bổng Hiệp định và học bổng Chính phủ trình độ thạc sĩ {country}",
    },
    "id": {
        PROGRAMMES: "Pangkalan Data Pendidikan Tinggi PDDikti program studi magister S2 {country}",
        SCHOLARSHIPS: "Beasiswa Pemerintah Indonesia LPDP KNB program magister S2 {country}",
    },
}


def search_candidates(
    country_code: str,
    country_name: str,
    search: Callable[[str], Iterable[str]],
    kinds: Iterable[str] = tuple(QUERIES),
) -> list[Candidate]:
    """Search-route candidates for `kinds`: every result, flagged. A profile
    country searches only for the kind its profile did not link (Ireland's
    links scholarships and no programme catalogue)."""
    found: list[Candidate] = []
    seen: set[str] = set()
    for kind in kinds:
        template = ALL_QUERIES.get(kind) or QUERIES[kind]
        query = template.format(country=country_name)
        for url in search(query):
            host = urlsplit(url).hostname or ""
            if host and url not in seen:
                seen.add(url)
                found.append(
                    Candidate(country_code, kind, url, "", query, "search", government_host(host))
                )
    return found


def search_deep_candidates(
    country_code: str,
    country_name: str,
    search_en: Callable[[str], Iterable[str]],
    *,
    languages: Iterable[str] = (),
    search_local: Callable[[str, str], Iterable[str]] | None = None,
    kinds: Iterable[str] = tuple(ALL_QUERIES),
) -> list[Candidate]:
    """Search all 7 database tiers for `country_code` in English and official languages.

    Unlike default `find_national_databases` (which skips `PROGRAMMES` and
    `SCHOLARSHIPS` whenever an EC profile page had a single link), this runs
    across all requested tiers so additional national databases (e.g.
    `stipendienlotse.de`, `hochschulkompass.de`, `monmaster.gouv.fr`,
    `campuschina.org`, `jpss.jp`, `bk21four.nrf.re.kr`) are discovered too.
    """
    found = search_candidates(country_code, country_name, search_en, kinds=kinds)
    seen = {c.url for c in found}
    if search_local is None:
        return found
    for lang in languages:
        lang_templates = LOCALIZED_DEEP_QUERIES.get(lang, {})
        for kind in kinds:
            tmpl = lang_templates.get(kind)
            if not tmpl:
                continue
            query = tmpl.format(country=country_name)
            for url in search_local(query, lang):
                host = urlsplit(url).hostname or ""
                if host and url not in seen:
                    seen.add(url)
                    found.append(
                        Candidate(
                            country_code,
                            kind,
                            url,
                            "",
                            query,
                            f"search_{lang}",
                            government_host(host),
                        )
                    )
    return found


#: Verified multi-tier national, regional, foundation, qualifications-register, and
#: funded-graduate-school databases across the 53 target countries.
VERIFIED_MULTI_TIER_DATABASES: tuple[Candidate, ...] = (
    # Germany (DE)
    Candidate(
        "DE",
        SCHOLARSHIPS,
        "https://www.stipendienlotse.de/",
        "BMBF Stipendienlotse national scholarship database",
        "https://www.bmbf.de",
        "curated",
        False,
    ),
    Candidate(
        "DE",
        SCHOLARSHIPS,
        "https://www.mystipendium.de/",
        "myStipendium German scholarship matching portal",
        "https://www.mystipendium.de",
        "curated",
        False,
    ),
    Candidate(
        "DE",
        QUALIFICATIONS_REGISTER,
        "https://www.hochschulkompass.de/en/degree-programmes.html",
        "HRK Hochschulkompass official Master's register",
        "https://www.hochschulkompass.de",
        "curated",
        False,
    ),
    Candidate(
        "DE",
        FOUNDATION_DIRECTORIES,
        "https://stiftungssuche.de/",
        "Bundesverband Deutscher Stiftungen directory",
        "https://www.stiftungen.org",
        "curated",
        False,
    ),
    Candidate(
        "DE",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://www.dfg.de/en/research-funding/funding-initiative/excellence-strategy",
        "DFG Excellence Strategy Clusters & Graduate Schools",
        "https://www.dfg.de",
        "curated",
        False,
    ),
    Candidate(
        "DE",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://www.mpg.de/en/imprs",
        "Max Planck International Research Schools (IMPRS) Master-track directory",
        "https://www.mpg.de",
        "curated",
        False,
    ),
    Candidate(
        "DE",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.uni-regensburg.de/bayhost/english-1/scholarships/index.html",
        "BAYHOST Bavarian Free State Master's Scholarships",
        "https://www.bayhost.de",
        "curated",
        False,
    ),
    # France (FR)
    Candidate(
        "FR",
        QUALIFICATIONS_REGISTER,
        "https://www.monmaster.gouv.fr/",
        "MESR MonMaster official national Master's portal",
        "https://www.enseignementsup-recherche.gouv.fr",
        "curated",
        True,
    ),
    Candidate(
        "FR",
        SCHOLARSHIPS,
        "https://www.etudiant.gouv.fr/fr/bourses-et-aides-financieres",
        "CNOUS / MESR official student grants & Master's mobility portal",
        "https://www.enseignementsup-recherche.gouv.fr",
        "curated",
        True,
    ),
    Candidate(
        "FR",
        FOUNDATION_DIRECTORIES,
        "https://www.fondationdefrance.org/fr/annuaire-des-fondations",
        "Fondation de France directory of scholarship foundations",
        "https://www.fondationdefrance.org",
        "curated",
        False,
    ),
    Candidate(
        "FR",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://anr.fr/fr/investissements-davenir/ecoles-universitaires-de-recherche-eur/",
        "ANR Écoles Universitaires de Recherche (EUR) funded Master's graduate schools",
        "https://anr.fr",
        "curated",
        False,
    ),
    # Italy (IT)
    Candidate(
        "IT",
        SCHOLARSHIPS,
        "https://studyinitaly.esteri.it/ListaBandi",
        "MAECI Study in Italy official international Master's scholarship portal",
        "https://www.esteri.it",
        "curated",
        False,
    ),
    Candidate(
        "IT",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://www.mur.gov.it/it/aree-tematiche/universita/dipartimenti-di-eccellenza",
        "MUR Dipartimenti di Eccellenza funded university departments",
        "https://www.mur.gov.it",
        "curated",
        True,
    ),
    Candidate(
        "IT",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.edisu.piemonte.it/en",
        "EDISU Piemonte regional right-to-study Master's scholarships",
        "https://www.regione.piemonte.it",
        "curated",
        False,
    ),
    Candidate(
        "IT",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.er-go.it/",
        "ER.GO Emilia-Romagna regional Master's scholarships & waivers",
        "https://www.regione.emilia-romagna.it",
        "curated",
        False,
    ),
    # China (CN)
    Candidate(
        "CN",
        SCHOLARSHIPS,
        "https://www.campuschina.org/scholarships/index.html",
        "CSC CampusChina official Chinese Government & Provincial Scholarships",
        "https://www.csc.edu.cn",
        "curated",
        False,
    ),
    Candidate(
        "CN",
        PROGRAMMES,
        "https://www.campuschina.org/universities/index.html",
        "CSC CampusChina Master's programme & university search",
        "https://www.csc.edu.cn",
        "curated",
        False,
    ),
    Candidate(
        "CN",
        PROGRAMMES,
        "https://www.cucas.cn/",
        "CUCAS English-taught Master's & scholarship directory in China",
        "https://www.cucas.cn",
        "curated",
        False,
    ),
    Candidate(
        "CN",
        QUALIFICATIONS_REGISTER,
        "https://yz.chsi.com.cn/zsml/",
        "CHSI official national Master's degree specialty directory",
        "https://www.moe.gov.cn",
        "curated",
        False,
    ),
    # Japan (JP)
    Candidate(
        "JP",
        SCHOLARSHIPS,
        "https://www.jasso.go.jp/en/ryugaku/scholarship_j/index.html",
        "JASSO Scholarships for International Master's Study in Japan",
        "https://www.jasso.go.jp",
        "curated",
        True,
    ),
    Candidate(
        "JP",
        FOUNDATION_DIRECTORIES,
        "https://www.jasso.go.jp/en/ryugaku/scholarship_j/dantai/index.html",
        "JASSO directory of private scholarship foundations in Japan",
        "https://www.jasso.go.jp",
        "curated",
        True,
    ),
    Candidate(
        "JP",
        PROGRAMMES,
        "https://www.jpss.jp/en/graduate/",
        "JPSS Japan Study Support graduate school & Master's search",
        "https://www.jpss.jp",
        "curated",
        False,
    ),
    Candidate(
        "JP",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://www.jsps.go.jp/english/e-tgu/",
        "MEXT/JSPS Top Global University & WISE graduate programmes",
        "https://www.jsps.go.jp",
        "curated",
        True,
    ),
    # South Korea (KR)
    Candidate(
        "KR",
        SCHOLARSHIPS,
        "https://www.studyinkorea.go.kr/ko/scholarship/Gks1Notice.do",
        "NIIED Global Korea Scholarship (GKS) Graduate Master's portal",
        "https://www.studyinkorea.go.kr",
        "curated",
        True,
    ),
    Candidate(
        "KR",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://bk21four.nrf.re.kr/",
        "NRF BK21 Four funded Master's & graduate research groups",
        "https://www.nrf.re.kr",
        "curated",
        False,
    ),
    Candidate(
        "KR",
        QUALIFICATIONS_REGISTER,
        "https://www.academyinfo.go.kr/",
        "Higher Education in Korea (AcademyInfo) official university & graduate register",
        "https://www.moe.go.kr",
        "curated",
        True,
    ),
    # Other key target countries
    Candidate(
        "NL",
        SCHOLARSHIPS,
        "https://www.studyinnl.org/finances",
        "Nuffic Study in NL Master's scholarship finder (NL Scholarship)",
        "https://www.nuffic.nl",
        "curated",
        False,
    ),
    Candidate(
        "NL",
        QUALIFICATIONS_REGISTER,
        "https://duo.nl/zakelijk/hoger-onderwijs/studentenadministratie/croho.jsp",
        "DUO RIO/CROHO official Dutch higher education programme register",
        "https://duo.nl",
        "curated",
        False,
    ),
    Candidate(
        "CH",
        SCHOLARSHIPS,
        "https://www.sbfi.admin.ch/sbfi/en/home/education/scholarships-and-grants/swiss-government-excellence-scholarships.html",
        "SERI Swiss Government Excellence Scholarships & cantonal grants",
        "https://www.sbfi.admin.ch",
        "curated",
        True,
    ),
    Candidate(
        "CH",
        PROGRAMMES,
        "https://www.studyprogrammes.ch/en",
        "swissuniversities studyprogrammes.ch official Master's search",
        "https://www.swissuniversities.ch",
        "curated",
        False,
    ),
    Candidate(
        "SE",
        SCHOLARSHIPS,
        "https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/",
        "Swedish Institute Scholarships for Global Professionals (Master's)",
        "https://si.se",
        "curated",
        False,
    ),
    Candidate(
        "SE",
        QUALIFICATIONS_REGISTER,
        "https://www.universityadmissions.se/intl/start",
        "Universityadmissions.se national Master's application & search portal",
        "https://www.uhr.se",
        "curated",
        False,
    ),
    Candidate(
        "FI",
        QUALIFICATIONS_REGISTER,
        "https://opintopolku.fi/konfo/en/",
        "Studyinfo.fi (Opintopolku) EDUFI national Master's & scholarship portal",
        "https://www.oph.fi",
        "curated",
        False,
    ),
    Candidate(
        "NO",
        PROGRAMMES,
        "https://studyinnorway.no/study-in-norway/find-a-programme",
        "HK-dir Study in Norway official Master's programme finder",
        "https://hkdir.no",
        "curated",
        False,
    ),
    Candidate(
        "AT",
        SCHOLARSHIPS,
        "https://grants.at/en/",
        "OeAD grants.at national database for scholarships and research grants",
        "https://oead.at",
        "curated",
        False,
    ),
    Candidate(
        "BE",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.studyinflanders.be/scholarships/master-mind-scholarships",
        "Flemish Ministry Master Mind Scholarships",
        "https://www.vlaanderen.be",
        "curated",
        False,
    ),
    Candidate(
        "BE",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.ares-ac.be/en/relations-internationales/bourses-internationales",
        "ARES Wallonia-Brussels International Master's scholarships",
        "https://www.ares-ac.be",
        "curated",
        False,
    ),
    Candidate(
        "PL",
        SCHOLARSHIPS,
        "https://nawa.gov.pl/en/students/foreign-students",
        "NAWA Polish National Agency for Academic Exchange Master's scholarships",
        "https://nawa.gov.pl",
        "curated",
        True,
    ),
    Candidate(
        "PL",
        QUALIFICATIONS_REGISTER,
        "https://radon.nauka.gov.pl/",
        "RAD-on MEiN official register of Polish higher education programmes",
        "https://www.gov.pl",
        "curated",
        True,
    ),
    Candidate(
        "HU",
        SCHOLARSHIPS,
        "https://stipendiumhungaricum.hu/study-finder/",
        "Tempus Public Foundation Stipendium Hungaricum Master's finder",
        "https://tpf.hu",
        "curated",
        False,
    ),
    Candidate(
        "CZ",
        SCHOLARSHIPS,
        "https://www.dzs.cz/en",
        "DZS Czech National Agency for International Education and Research",
        "https://msmt.gov.cz",
        "curated",
        False,
    ),
    Candidate(
        "SK",
        SCHOLARSHIPS,
        "https://www.scholarships.sk/en/",
        "SAIA National Scholarship Programme of the Slovak Republic",
        "https://www.saia.sk",
        "curated",
        False,
    ),
    Candidate(
        "GB",
        SCHOLARSHIPS,
        "https://study-uk.britishcouncil.org/scholarships-funding",
        "British Council Study UK GREAT & Chevening Master's scholarship finder",
        "https://www.britishcouncil.org",
        "curated",
        False,
    ),
    Candidate(
        "IE",
        SCHOLARSHIPS,
        "https://hea.ie/policy/internationalisation/government-of-ireland-international-education-scholarships/",
        "HEA Government of Ireland International Education Scholarships (Master's)",
        "https://hea.ie",
        "curated",
        False,
    ),
    Candidate(
        "ES",
        QUALIFICATIONS_REGISTER,
        "https://www.educacion.gob.es/ruct/home",
        "RUCT official Spanish Ministry register of universities, centres and degrees",
        "https://www.universidades.gob.es",
        "curated",
        True,
    ),
    Candidate(
        "ES",
        SCHOLARSHIPS,
        "https://www.fundacioncarolina.es/formacion/postgrado/",
        "Fundación Carolina & AECID Master's scholarships in Spain",
        "https://www.aecid.es",
        "curated",
        False,
    ),
    Candidate(
        "PT",
        SCHOLARSHIPS,
        "https://iesuperior.pt/bolsas-de-estudo/",
        "DGES +EnsinoSuperior Portuguese official higher education grants & scholarships portal",
        "https://www.dges.gov.pt",
        "curated",
        False,
    ),
    Candidate(
        "RO",
        SCHOLARSHIPS,
        "https://scholarships.studyinromania.gov.ro/",
        "MFA/ME Study in Romania MFA Master's Scholarships",
        "https://www.mae.ro",
        "curated",
        True,
    ),
    Candidate(
        "TR",
        SCHOLARSHIPS,
        "https://www.turkiyeburslari.gov.tr/",
        "YTB Türkiye Scholarships official Master's portal",
        "https://www.ytb.gov.tr",
        "curated",
        True,
    ),
    Candidate(
        "TR",
        QUALIFICATIONS_REGISTER,
        "https://yokatlas.yok.gov.tr/",
        "YÖK Atlas official Turkish higher education & graduate register",
        "https://www.yok.gov.tr",
        "curated",
        True,
    ),
    Candidate(
        "RU",
        SCHOLARSHIPS,
        "https://education-in-russia.com/",
        "Rossotrudnichestvo / Minobrnauki Russian Government Master's Quota portal",
        "https://minobrnauki.gov.ru",
        "curated",
        False,
    ),
    Candidate(
        "KZ",
        SCHOLARSHIPS,
        "https://bolashak.gov.kz/en",
        "Center for International Programs (Bolashak & Central Asian Master's grants)",
        "https://www.gov.kz",
        "curated",
        True,
    ),
    Candidate(
        "AZ",
        SCHOLARSHIPS,
        "https://dp.edu.az/",
        "State Program on Education Abroad & Heydar Aliyev International Education Grant",
        "https://edu.gov.az",
        "curated",
        False,
    ),
    Candidate(
        "GE",
        SCHOLARSHIPS,
        "https://iec.gov.ge/",
        "International Education Center (IEC) Georgia Master's scholarships",
        "https://mes.gov.ge",
        "curated",
        True,
    ),
    Candidate(
        "AM",
        SCHOLARSHIPS,
        "https://escs.am/en",
        "Ministry of Education, Science, Culture and Sport of Armenia scholarships",
        "https://escs.am",
        "curated",
        False,
    ),
    Candidate(
        "SA",
        SCHOLARSHIPS,
        "https://studyinsaudi.sa/en",
        "Study in Saudi official Ministry of Education Master's scholarship portal",
        "https://moe.gov.sa",
        "curated",
        True,
    ),
    Candidate(
        "SA",
        SCHOLARSHIPS,
        "https://www.rdia.gov.sa/programs/funding/",
        "Research, Development and Innovation Authority (RDIA) graduate & research grants",
        "https://www.rdia.gov.sa",
        "curated",
        False,
    ),
    Candidate(
        "AE",
        SCHOLARSHIPS,
        "https://www.moe.gov.ae/En/EServices/ServiceCard/pages/UniversitiesRecommended.aspx",
        "UAE Ministry of Education accredited universities & scholarships",
        "https://www.moe.gov.ae",
        "curated",
        True,
    ),
    Candidate(
        "QA",
        SCHOLARSHIPS,
        "https://www.edu.gov.qa/en/Content/Scholarshipsdepartment",
        "Qatar Ministry of Education and Higher Education scholarship portal",
        "https://www.edu.gov.qa",
        "curated",
        True,
    ),
    Candidate(
        "KW",
        SCHOLARSHIPS,
        "https://www.mohe.edu.kw/",
        "Kuwait Ministry of Higher Education scholarships & accredited institutions",
        "https://www.mohe.edu.kw",
        "curated",
        True,
    ),
    Candidate(
        "BH",
        SCHOLARSHIPS,
        "https://www.moe.gov.bh/",
        "Bahrain Ministry of Education Higher Education Council scholarships",
        "https://www.moe.gov.bh",
        "curated",
        True,
    ),
    Candidate(
        "SG",
        SCHOLARSHIPS,
        "https://www.a-star.edu.sg/Scholarships",
        "Singapore A*STAR & MOE Graduate Scholarships",
        "https://www.moe.gov.sg",
        "curated",
        True,
    ),
    Candidate(
        "BN",
        SCHOLARSHIPS,
        "https://www.mfa.gov.bn/Pages/bdgs.aspx",
        "Brunei Darussalam Government Scholarship (BDGS) for Foreign Master's Students",
        "https://www.mfa.gov.bn",
        "curated",
        True,
    ),
    Candidate(
        "VN",
        SCHOLARSHIPS,
        "https://icd.edu.vn/",
        "Vietnam MOET International Cooperation Department (ICD) scholarships",
        "https://moet.gov.vn",
        "curated",
        True,
    ),
    Candidate(
        "AU",
        SCHOLARSHIPS,
        "https://search.studyaustralia.gov.au/scholarship",
        (
            "Study Australia official Australian Government Master's "
            "& Destination Australia scholarships"
        ),
        "https://www.dfat.gov.au",
        "curated",
        True,
    ),
    Candidate(
        "NZ",
        SCHOLARSHIPS,
        "https://www.studywithnewzealand.govt.nz/en/how-to-apply/scholarships",
        "Education New Zealand Manaaki New Zealand Master's Scholarships",
        "https://www.mfat.govt.nz",
        "curated",
        True,
    ),
    Candidate(
        "US",
        SCHOLARSHIPS,
        "https://foreign.fulbrightonline.org/",
        "IIE / State Department Fulbright Foreign Student Program (Master's)",
        "https://educationusa.state.gov",
        "curated",
        False,
    ),
    Candidate(
        "US",
        QUALIFICATIONS_REGISTER,
        "https://ope.ed.gov/dapip/",
        "US Department of Education DAPIP database of accredited postsecondary institutions",
        "https://www.ed.gov",
        "curated",
        True,
    ),
    Candidate(
        "CA",
        SCHOLARSHIPS,
        "https://www.educanada.ca/scholarships-bourses/non_can/index.aspx?lang=eng",
        "EduCanada Global Affairs Canada international Master's scholarships",
        "https://www.international.gc.ca",
        "curated",
        False,
    ),
    Candidate(
        "CA",
        PROGRAMMES,
        "https://www.educanada.ca/programs-programmes/index.aspx?lang=eng",
        "EduCanada / CMEC official Canadian Master's degree programme search",
        "https://www.international.gc.ca",
        "curated",
        False,
    ),
    Candidate(
        "AT",
        PROGRAMMES,
        "https://www.studienwahl.at/en/",
        "Austrian Federal Ministry (BMBWF) official degree programme finder",
        "https://www.bmbwf.gv.at",
        "curated",
        False,
    ),
    Candidate(
        "BE",
        PROGRAMMES,
        "https://www.studyinflanders.be/programmes",
        "Study in Flanders official Higher Education in Flanders Master's programme register",
        "https://www.vlaanderen.be",
        "curated",
        False,
    ),
    Candidate(
        "BE",
        PROGRAMMES,
        "https://www.studyinbelgium.be/en/our-formations",
        "Wallonia-Brussels Federation official Master's programme database",
        "https://www.wallonie-bruxelles.be",
        "curated",
        False,
    ),
    Candidate(
        "BG",
        SCHOLARSHIPS,
        "https://mon.bg/en/",
        "Bulgarian Ministry of Education and Science Government Master's scholarships",
        "https://www.government.bg",
        "curated",
        True,
    ),
    Candidate(
        "HR",
        SCHOLARSHIPS,
        "https://mzom.gov.hr/en",
        "Croatian Ministry of Science, Education and Youth bilateral & Master's scholarships",
        "https://www.ampeu.hr",
        "curated",
        True,
    ),
    Candidate(
        "CY",
        PROGRAMMES,
        "https://www.highereducation.ac.cy/index.php/en/programmes-of-study",
        "Cyprus Ministry of Education, Sport and Youth accredited programmes of study",
        "https://www.moec.gov.cy",
        "curated",
        False,
    ),
    Candidate(
        "IE",
        PROGRAMMES,
        "https://www.qualifax.ie/",
        "QQI / Qualifax Irish National Learners' Database of Master's programmes",
        "https://www.qqi.ie",
        "curated",
        False,
    ),
    Candidate(
        "LU",
        PROGRAMMES,
        "https://mengstudien.public.lu/en/etudier-au-luxembourg.html",
        "Ministry of Research and Higher Education (MESR) MengStudien Luxembourg portal",
        "https://mesr.gouvernement.lu",
        "curated",
        True,
    ),
    Candidate(
        "RO",
        PROGRAMMES,
        "https://studyinromania.gov.ro/",
        "UEFISCDI Study in Romania official national Master's programme finder",
        "https://www.edu.ro",
        "curated",
        True,
    ),
    Candidate(
        "SI",
        SCHOLARSHIPS,
        "https://studyinslovenia.si/study/scholarships/",
        "CMEPIUS / Public Scholarship, Development, Disability and Maintenance Fund of Slovenia",
        "https://www.srips-rs.si",
        "curated",
        False,
    ),
    Candidate(
        "NO",
        SCHOLARSHIPS,
        "https://hkdir.no/en/grants-and-open-calls",
        "Norwegian Directorate for Higher Education and Skills (HK-dir) Master's grants",
        "https://www.regjeringen.no",
        "curated",
        False,
    ),
    Candidate(
        "IS",
        PROGRAMMES,
        "https://study.iceland.is/study-in-iceland",
        "Study in Iceland / Rannís official Master's programme directory",
        "https://www.rannis.is",
        "curated",
        False,
    ),
    Candidate(
        "GB",
        PROGRAMMES,
        "https://study-uk.britishcouncil.org/plan-studies/Choosing-a-course",
        "British Council Study UK / UCAS Postgraduate official Master's course finder",
        "https://www.britishcouncil.org",
        "curated",
        False,
    ),
    Candidate(
        "SA",
        PROGRAMMES,
        "https://studyinsaudi.sa/en/Programs?degree=Master",
        "Study in Saudi Ministry of Education official university & Master's programme directory",
        "https://moe.gov.sa",
        "curated",
        True,
    ),
    Candidate(
        "SA",
        QUALIFICATIONS_REGISTER,
        "https://etec.gov.sa/en/centers/ncaaa",
        "Education and Training Evaluation Commission (ETEC / NCAAA) accreditation center",
        "https://etec.gov.sa",
        "curated",
        False,
    ),
    Candidate(
        "AE",
        QUALIFICATIONS_REGISTER,
        "https://www.caa.ae/Pages/Programs/All.aspx",
        "UAE Commission for Academic Accreditation (CAA) accredited Master's register",
        "https://www.moe.gov.ae",
        "curated",
        False,
    ),
    Candidate(
        "QA",
        QUALIFICATIONS_REGISTER,
        "https://www.edu.gov.qa/en/university/universityList",
        "Qatar Ministry of Education and Higher Education accredited higher education programmes",
        "https://www.edu.gov.qa",
        "curated",
        True,
    ),
    Candidate(
        "KW",
        QUALIFICATIONS_REGISTER,
        "https://nbaq.edu.kw/",
        "Kuwait National Bureau for Academic Accreditation and Education Quality Assurance (NBAQ)",
        "https://www.mohe.edu.kw",
        "curated",
        False,
    ),
    Candidate(
        "BH",
        QUALIFICATIONS_REGISTER,
        "https://www.moe.gov.bh/en/higher-education-institutions",
        "Bahrain Higher Education Council directory of accredited universities & graduate degrees",
        "https://www.moe.gov.bh",
        "curated",
        True,
    ),
    Candidate(
        "AU",
        PROGRAMMES,
        "https://search.studyaustralia.gov.au/courses",
        "Study Australia / CRICOS official Australian Government Master's course search",
        "https://cricos.education.gov.au",
        "curated",
        True,
    ),
    Candidate(
        "NZ",
        PROGRAMMES,
        "https://www.studywithnewzealand.govt.nz/en/study-options/search/courses",
        "Education New Zealand official Master's course search",
        "https://www.nzqa.govt.nz",
        "curated",
        True,
    ),
    Candidate(
        "SG",
        PROGRAMMES,
        "https://www.moe.gov.sg/post-secondary/overview/autonomous-universities",
        "Singapore Ministry of Education Autonomous Universities postgraduate directory",
        "https://www.moe.gov.sg",
        "curated",
        True,
    ),
    Candidate(
        "BN",
        PROGRAMMES,
        "https://www.moe.gov.bn/SitePages/Higher%20Education%20Division.aspx",
        "Brunei Ministry of Education Higher Education Division university & Master's register",
        "https://www.moe.gov.bn",
        "curated",
        True,
    ),
    Candidate(
        "RU",
        PROGRAMMES,
        "https://studyinrussia.ru/en/study-in-russia/programs/",
        "Minobrnauki Study in Russia official state directory of Master's programmes",
        "https://minobrnauki.gov.ru",
        "curated",
        False,
    ),
    Candidate(
        "VN",
        PROGRAMMES,
        "https://moet.gov.vn/en/Pages/home.aspx",
        "Vietnam Ministry of Education and Training (MOET) higher education directory",
        "https://moet.gov.vn",
        "curated",
        True,
    ),
    Candidate(
        "AM",
        PROGRAMMES,
        "https://studyinarmenia.org/",
        "Study in Armenia / ANQA official accredited higher education & Master's directory",
        "https://escs.am",
        "curated",
        False,
    ),
    Candidate(
        "AZ",
        PROGRAMMES,
        "https://portal.edu.az/",
        "Azerbaijan Ministry of Science and Education (ETN) higher education & Master's portal",
        "https://edu.gov.az",
        "curated",
        False,
    ),
    Candidate(
        "AZ",
        PROGRAMMES,
        "https://studyinazerbaijan.edu.az/",
        "Study in Azerbaijan official international Master's programme portal",
        "https://edu.gov.az",
        "curated",
        False,
    ),
    Candidate(
        "GE",
        PROGRAMMES,
        "https://studyin.gov.ge/",
        "Study in Georgia official Ministry of Education, Science and Youth Master's portal",
        "https://mes.gov.ge",
        "curated",
        True,
    ),
    Candidate(
        "KZ",
        PROGRAMMES,
        "https://univision.kz/",
        "Ministry of Science and Higher Education of Kazakhstan university & Master's navigator",
        "https://www.gov.kz",
        "curated",
        False,
    ),
    Candidate(
        "FR",
        PROGRAMMES,
        "https://taughtie.campusfrance.org/tiesearch/#/catalog",
        "Campus France Taught in English Master's catalogue",
        "https://www.campusfrance.org",
        "curated",
        False,
    ),
    Candidate(
        "FR",
        SCHOLARSHIPS,
        "https://campusbourses.campusfrance.org/#/catalog",
        "Campus France Campus Bourses official scholarship search engine",
        "https://www.campusfrance.org",
        "curated",
        False,
    ),
    Candidate(
        "DE",
        PROGRAMMES,
        "https://www2.daad.de/deutschland/studienangebote/international-programmes/en/",
        "DAAD International Programmes in Germany (Master's)",
        "https://www.daad.de",
        "curated",
        False,
    ),
    Candidate(
        "DE",
        SCHOLARSHIPS,
        "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
        "DAAD Scholarship Database for international Master's students",
        "https://www.daad.de",
        "curated",
        False,
    ),
    Candidate(
        "IT",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.esupadova.it/",
        "ESU Padova regional DSU scholarship & tuition-waiver authority (Veneto)",
        "https://www.regione.veneto.it",
        "curated",
        False,
    ),
    Candidate(
        "IT",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.dsu.toscana.it/",
        "ARDSU Toscana regional DSU scholarship & tuition-waiver authority (Tuscany)",
        "https://www.regione.toscana.it",
        "curated",
        False,
    ),
    Candidate(
        "IT",
        PROGRAMMES,
        "https://www.universitaly.it/cerca-corsi",
        "MUR Universitaly official national Master's degree finder",
        "https://www.mur.gov.it",
        "curated",
        False,
    ),
    Candidate(
        "NL",
        PROGRAMMES,
        "https://www.studyinnl.org/dutch-education/studies",
        "Nuffic Study in NL official international Master's programme finder",
        "https://www.nuffic.nl",
        "curated",
        False,
    ),
    Candidate(
        "DK",
        PROGRAMMES,
        "https://studyindenmark.dk/portal",
        "UFM Study in Denmark official Master's programme portal",
        "https://ufm.dk",
        "curated",
        False,
    ),
    Candidate(
        "DK",
        SCHOLARSHIPS,
        "https://studyindenmark.dk/study-options/scholarships",
        "Danish Government & Study in Denmark Master's scholarships",
        "https://ufm.dk",
        "curated",
        False,
    ),
    Candidate(
        "EE",
        PROGRAMMES,
        "https://www.studyinestonia.ee/study/programmes",
        "HARNO Study in Estonia official Master's programme finder",
        "https://harno.ee",
        "curated",
        False,
    ),
    Candidate(
        "EE",
        SCHOLARSHIPS,
        "https://www.studyinestonia.ee/study/scholarships/scholarships-degree-studies",
        "HARNO Estonian national & degree-study Master's scholarships",
        "https://harno.ee",
        "curated",
        False,
    ),
    Candidate(
        "GR",
        PROGRAMMES,
        "https://masters.minedu.gov.gr/Masters/index/en",
        "Hellenic Ministry of Education official Master's programmes database",
        "https://www.minedu.gov.gr",
        "curated",
        True,
    ),
    Candidate(
        "GR",
        SCHOLARSHIPS,
        "https://www.iky.gr/en/scholarships/",
        "IKY State Scholarships Foundation of Greece Master's scholarships",
        "https://www.iky.gr",
        "curated",
        False,
    ),
    Candidate(
        "LV",
        PROGRAMMES,
        "https://studyinlatvia.lv/studies",
        "VIAA Study in Latvia official Master's programme catalogue",
        "https://www.viaa.gov.lv",
        "curated",
        False,
    ),
    Candidate(
        "LV",
        SCHOLARSHIPS,
        "https://www.viaa.gov.lv/en/latvian-state-scholarships",
        "VIAA Latvian State Scholarships for Master's studies",
        "https://www.viaa.gov.lv",
        "curated",
        True,
    ),
    Candidate(
        "LT",
        PROGRAMMES,
        "https://studyin.lt/programs/",
        "ŠMPF Study in Lithuania official Master's programme search",
        "https://smpf.lt",
        "curated",
        False,
    ),
    Candidate(
        "LT",
        SCHOLARSHIPS,
        "https://studyin.lt/scholarships/",
        "ŠMPF Lithuanian State Scholarships for full-time Master's degree studies",
        "https://smpf.lt",
        "curated",
        False,
    ),
    Candidate(
        "MT",
        QUALIFICATIONS_REGISTER,
        "https://qualifications.mfhea.gov.mt/#/qualifications",
        "MFHEA Malta Further and Higher Education Authority qualifications register",
        "https://mfhea.mt",
        "curated",
        True,
    ),
    Candidate(
        "MT",
        SCHOLARSHIPS,
        "https://myscholarship.gov.mt/en/",
        "Ministry for Education Malta national Endeavour & TESS Master's scholarships",
        "https://education.gov.mt",
        "curated",
        True,
    ),
    Candidate(
        "RS",
        PROGRAMMES,
        "https://www.bazaobrazovanja.rs/en/programmes",
        "Foundation Tempus Study in Serbia official Master's programme database",
        "https://tempus.ac.rs",
        "curated",
        False,
    ),
    Candidate(
        "RS",
        SCHOLARSHIPS,
        "https://prosveta.gov.rs/skolski-i-studentski-zivot/stipendije/",
        "Serbian Ministry of Education bilateral & World in Serbia Master's scholarships",
        "https://prosveta.gov.rs",
        "curated",
        True,
    ),
    Candidate(
        "BG",
        QUALIFICATIONS_REGISTER,
        "https://rsvu.mon.bg/#/universities?locale=en",
        "MON Bulgarian University Ranking & Higher Education Register (RSVU)",
        "https://mon.bg",
        "curated",
        True,
    ),
    Candidate(
        "CZ",
        PROGRAMMES,
        "https://studyin.gov.cz/study-programmes",
        "DZS Study in Czechia official Master's programme finder",
        "https://www.dzs.cz",
        "curated",
        True,
    ),
    Candidate(
        "HR",
        PROGRAMMES,
        "https://hko.srce.hr/usp/index?lang=en",
        "SRCE / AZVO Croatian Qualifications Framework official Master's register",
        "https://www.azvo.hr",
        "curated",
        False,
    ),
    Candidate(
        "HU",
        PROGRAMMES,
        "https://studyinhungary.hu/study-in-hungary/menu/find-a-study-programme.html",
        "Tempus Public Foundation Study in Hungary Master's programme finder",
        "https://tpf.hu",
        "curated",
        False,
    ),
    Candidate(
        "PT",
        QUALIFICATIONS_REGISTER,
        "https://www.dges.gov.pt/simges/public/www/cursos_instituicoes?plid=372",
        "DGES Portuguese Directorate-General for Higher Education Master's register",
        "https://www.dges.gov.pt",
        "curated",
        True,
    ),
    Candidate(
        "PT",
        PROGRAMMES,
        "https://study-research.pt/study/",
        "Study & Research in Portugal official Master's programme search",
        "https://www.fct.pt",
        "curated",
        False,
    ),
    Candidate(
        "SI",
        PROGRAMMES,
        "https://studyinslovenia.si/general/search-programmes-institutions/",
        "CMEPIUS Study in Slovenia official Master's programme directory",
        "https://www.cmepius.si",
        "curated",
        False,
    ),
    Candidate(
        "SK",
        QUALIFICATIONS_REGISTER,
        "https://www.portalvs.sk/en/studijne-programy",
        "Slovak Ministry of Education Portál VŠ official register of Master's programmes",
        "https://www.minedu.sk",
        "curated",
        False,
    ),
    Candidate(
        "CY",
        SCHOLARSHIPS,
        "https://www.cyscholarships.gov.cy/",
        "Cyprus State Scholarship Foundation (IKYK) official Master's scholarships",
        "https://www.cyscholarships.gov.cy",
        "curated",
        True,
    ),
    Candidate(
        "FI",
        SCHOLARSHIPS,
        "https://www.studyinfinland.fi/funding-your-studies/bachelors-and-masters-scholarships",
        "EDUFI Study in Finland national Master's scholarship directory",
        "https://www.oph.fi",
        "curated",
        False,
    ),
    Candidate(
        "IS",
        SCHOLARSHIPS,
        "https://study.iceland.is/study-in-iceland/scholarships",
        "Rannís / Study in Iceland official graduate scholarship directory",
        "https://www.rannis.is",
        "curated",
        False,
    ),
    Candidate(
        "LU",
        SCHOLARSHIPS,
        "https://mengstudien.public.lu/en/aides-financieres.html",
        "MESR MengStudien / AideFi Luxembourg state financial aid & Master's grants",
        "https://mesr.gouvernement.lu",
        "curated",
        True,
    ),
    Candidate(
        "US",
        PROGRAMMES,
        "https://nces.ed.gov/collegenavigator/",
        "US Department of Education NCES College Navigator graduate programme finder",
        "https://www.ed.gov",
        "curated",
        True,
    ),
    # Central, South & Southeast Asia (UZ, ID, IN, PK)
    Candidate(
        "UZ",
        SCHOLARSHIPS,
        "https://eyuf.uz/en",
        "El-Yurt Umidi Foundation outbound Master's scholarships of Uzbekistan",
        "https://eyuf.uz",
        "curated",
        False,
    ),
    Candidate(
        "UZ",
        PROGRAMMES,
        "https://magistr.edu.uz/",
        "Ministry of Higher Education, Science and Innovations of Uzbekistan Master's portal",
        "https://gov.uz",
        "curated",
        False,
    ),
    Candidate(
        "ID",
        SCHOLARSHIPS,
        "https://lpdp.kemenkeu.go.id/",
        "LPDP Indonesia Endowment Fund for Education Master's scholarships",
        "https://www.kemenkeu.go.id",
        "curated",
        True,
    ),
    Candidate(
        "ID",
        SCHOLARSHIPS,
        "https://knb.kemdiktisaintek.go.id/",
        "KNB Indonesian Government Master's Scholarship for international students",
        "https://kemdiktisaintek.go.id",
        "curated",
        True,
    ),
    Candidate(
        "ID",
        PROGRAMMES,
        "https://pddikti.kemdiktisaintek.go.id/",
        "PDDikti official Indonesian national higher-education & Master's register",
        "https://kemdiktisaintek.go.id",
        "curated",
        True,
    ),
    Candidate(
        "IN",
        PROGRAMMES,
        "https://www.studyinindia.gov.in/",
        "Ministry of Education Study in India official Master's programme finder",
        "https://www.education.gov.in",
        "curated",
        True,
    ),
    Candidate(
        "IN",
        SCHOLARSHIPS,
        "https://a2ascholarships.iccr.gov.in/",
        "ICCR A2A Scholarship Portal for international Master's students in India",
        "https://www.iccr.gov.in",
        "curated",
        True,
    ),
    Candidate(
        "PK",
        SCHOLARSHIPS,
        "https://www.hec.gov.pk/english/scholarshipsgrants/Pages/default.aspx",
        "Higher Education Commission (HEC) Pakistan national & overseas Master's scholarships",
        "https://www.hec.gov.pk",
        "curated",
        True,
    ),
    Candidate(
        "PK",
        QUALIFICATIONS_REGISTER,
        "https://www.hec.gov.pk/english/universities/pages/recognised.aspx",
        "HEC Pakistan official register of recognised universities & degree programmes",
        "https://www.hec.gov.pk",
        "curated",
        True,
    ),
    # Multi-tier national, regional, and foundation directories
    Candidate(
        "TR",
        PROGRAMMES,
        "https://www.studyinturkiye.gov.tr/StudySearch/List",
        "YÖK Study in Türkiye official international Master's programme search",
        "https://www.yok.gov.tr",
        "curated",
        True,
    ),
    Candidate(
        "TR",
        SCHOLARSHIPS,
        "https://tubitak.gov.tr/tr/burslar/lisansustu/egitim-burs-programlari",
        "TÜBİTAK BİDEB 2210/2215 national & international graduate scholarship programmes",
        "https://tubitak.gov.tr",
        "curated",
        True,
    ),
    Candidate(
        "TR",
        FOUNDATION_DIRECTORIES,
        "https://www.vgm.gov.tr/vakif-sorgulama/vakif-sorgulama?IsGrant=true",
        "Directorate General of Foundations (VGM) official grant-giving foundation directory",
        "https://www.vgm.gov.tr",
        "curated",
        True,
    ),
    Candidate(
        "TR",
        SCHOLARSHIPS,
        "https://diyanetburslari.tdv.org/",
        "Türkiye Diyanet Foundation (TDV) International Graduate Scholarships",
        "https://tdv.org",
        "curated",
        False,
    ),
    Candidate(
        "AZ",
        SCHOLARSHIPS,
        "https://htp.edu.az/",
        "Intergovernmental Scholarship Program (HTP) of the Republic of Azerbaijan",
        "https://eatda.edu.az",
        "curated",
        False,
    ),
    Candidate(
        "AZ",
        SCHOLARSHIPS,
        "https://siac.edu.az/",
        "Heydar Aliyev International Education Grant (SIAC) official portal",
        "https://edu.gov.az",
        "curated",
        False,
    ),
    Candidate(
        "AZ",
        QUALIFICATIONS_REGISTER,
        "https://www.tkta.edu.az/en",
        "Education Quality Assurance Agency (TKTA) accredited higher education register",
        "https://edu.gov.az",
        "curated",
        False,
    ),
    Candidate(
        "AZ",
        QUALIFICATIONS_REGISTER,
        "https://dim.gov.az/az/fealiyyet/qebul-ve-imtahanlar/magistratura/",
        "State Examination Center (DİM) national Magistratura admissions & specialisation register",
        "https://dim.gov.az",
        "curated",
        True,
    ),
    Candidate(
        "KZ",
        SCHOLARSHIPS,
        "https://enic-kazakhstan.edu.kz/en/stipendialnye-programmy/operativnaya-informaciya",
        "ENIC-Kazakhstan Higher Education Development National Center scholarship programmes",
        "https://www.gov.kz",
        "curated",
        False,
    ),
    Candidate(
        "KZ",
        QUALIFICATIONS_REGISTER,
        "https://epvo.kz/",
        "Unified Higher Education Platform (EPVO) national register of educational programmes",
        "https://www.gov.kz",
        "curated",
        False,
    ),
    Candidate(
        "KZ",
        PROGRAMMES,
        "https://studyin.kz/en/grants",
        "Study in Kazakhstan official international Master's & state scholarship portal",
        "https://enic-kazakhstan.edu.kz",
        "curated",
        False,
    ),
    Candidate(
        "UZ",
        PROGRAMMES,
        "https://studyin-uzbekistan.uz/",
        "Study in Uzbekistan official international university & Master's catalogue",
        "https://gov.uz",
        "curated",
        False,
    ),
    Candidate(
        "UZ",
        QUALIFICATIONS_REGISTER,
        "https://stat.edu.uz/",
        "Ministry of Higher Education open statistics & licensed HEI register of Uzbekistan",
        "https://edu.uz",
        "curated",
        False,
    ),
    Candidate(
        "UZ",
        SCHOLARSHIPS,
        "https://gov.uz/en/edu",
        "Ministry of Higher Education, Science and Innovations of Uzbekistan state grants",
        "https://gov.uz",
        "curated",
        True,
    ),
    Candidate(
        "GE",
        PROGRAMMES,
        "https://educationingeorgia.ge/program-list",
        "Education in Georgia official MESY English-taught Master's programme catalogue",
        "https://mes.gov.ge",
        "curated",
        False,
    ),
    Candidate(
        "GE",
        QUALIFICATIONS_REGISTER,
        "https://reestri.eqe.ge/en/search",
        "NCEQE official Registry of Educational Programmes of Georgia",
        "https://eqe.ge",
        "curated",
        False,
    ),
    Candidate(
        "GE",
        SCHOLARSHIPS,
        "https://rustaveli.org.ge/geo/magistrantta-kvleviti-grantebis-konkursi",
        "Shota Rustaveli National Science Foundation of Georgia Master's Research Grants",
        "https://rustaveli.org.ge",
        "curated",
        False,
    ),
    Candidate(
        "GE",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://ajara.gov.ge/",
        "Ministry of Education, Culture and Sport of Adjara AR Study Abroad & Master's Grants",
        "https://ajara.gov.ge",
        "curated",
        True,
    ),
    Candidate(
        "CH",
        SCHOLARSHIPS,
        "https://www.studyinswitzerland.plus/scholarships/",
        "swissuniversities Study in Switzerland+ official scholarship directory",
        "https://www.swissuniversities.ch",
        "curated",
        False,
    ),
    Candidate(
        "CH",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.edk.ch/de/themen/stipendien/stipendienstellen",
        "EDK official directory of all 26 Swiss cantonal scholarship offices",
        "https://www.edk.ch",
        "curated",
        False,
    ),
    Candidate(
        "CH",
        FOUNDATION_DIRECTORIES,
        "https://www.esa.admin.ch/de/stiftungsverzeichnis",
        "Eidgenössische Stiftungsaufsicht (ESA) official federal directory of Swiss foundations",
        "https://www.edi.admin.ch",
        "curated",
        True,
    ),
    Candidate(
        "CH",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://www.snf.ch/en/ble5Mif9Z6xOBhtp/page/national-research",
        "SNSF National Centres of Competence in Research (NCCRs)",
        "https://www.snf.ch",
        "curated",
        False,
    ),
    Candidate(
        "FI",
        PROGRAMMES,
        "https://opintopolku.fi/konfo/en/haku?koulutustyyppi=maisteri,amk-ylempi",
        "Studyinfo.fi (Opintopolku) filtered Master's & UAS Master's search",
        "https://www.oph.fi",
        "curated",
        False,
    ),
    Candidate(
        "FI",
        SCHOLARSHIPS,
        "https://research.fi/en/results/funding-calls",
        "Research.fi (Tiedejatutkimus.fi) Ministry of Education & Research Council funding calls",
        "https://okm.fi",
        "curated",
        False,
    ),
    Candidate(
        "FI",
        FOUNDATION_DIRECTORIES,
        "https://saatiotrahastot.fi/hae-saatioita/",
        "Association of Finnish Foundations (Säätiöt ja rahastot) grant foundation finder",
        "https://saatiotrahastot.fi",
        "curated",
        False,
    ),
    Candidate(
        "FI",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.studiefonden.fi/",
        "Svenska studiefonden Master's & study-abroad grants in Finland",
        "https://www.kulturfonden.fi",
        "curated",
        False,
    ),
    Candidate(
        "FI",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://www.aka.fi/en/research-funding/funding-opportunities2/forge-funding/finnish-flagships/",
        "Research Council of Finland (Suomen Akatemia) Finnish Flagships & Centres of Excellence",
        "https://www.aka.fi",
        "curated",
        False,
    ),
    Candidate(
        "CZ",
        SCHOLARSHIPS,
        "https://studyin.gov.cz/scholarships",
        "DZS Study in Czechia official scholarship & bilateral grant portal",
        "https://www.dzs.cz",
        "curated",
        True,
    ),
    Candidate(
        "CZ",
        QUALIFICATIONS_REGISTER,
        "https://regvssp.msmt.cz/registrvssp/csplist.aspx",
        "MŠMT Register of Higher Education Institutions and Accredited Study Programmes",
        "https://msmt.gov.cz",
        "curated",
        True,
    ),
    Candidate(
        "CZ",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.jcmm.cz/en/scholarships-and-scientists",
        "JCMM South Moravian Centre for International Mobility Master's scholarships",
        "https://www.jcmm.cz",
        "curated",
        False,
    ),
    Candidate(
        "CZ",
        FOUNDATION_DIRECTORIES,
        "https://www.donorsforum.cz/",
        "Fórum dárců (Czech Donors Forum) national directory of Czech foundations & funds",
        "https://www.donorsforum.cz",
        "curated",
        False,
    ),
    Candidate(
        "HR",
        PROGRAMMES,
        "https://www.studyincroatia.hr/study-in-croatia/study-programmes-in-english/",
        "AZVO Study in Croatia official English-taught Master's directory",
        "https://www.azvo.hr",
        "curated",
        False,
    ),
    Candidate(
        "HR",
        SCHOLARSHIPS,
        "https://en.ampeu.hr/bilateral-scolarships",
        "AMPEU / MZOM bilateral & international Master's scholarships in Croatia",
        "https://www.ampeu.hr",
        "curated",
        False,
    ),
    Candidate(
        "HR",
        FOUNDATION_DIRECTORIES,
        "https://registri-npo-mpu.gov.hr/",
        "Ministry of Justice and Public Administration Registry of Foundations (Registar zaklada)",
        "https://mpu.gov.hr",
        "curated",
        True,
    ),
    Candidate(
        "HR",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.zagreb.hr/stipendije-grada-zagreba/175198",
        "City of Zagreb municipal Master's & postgraduate scholarships",
        "https://www.zagreb.hr",
        "curated",
        False,
    ),
    Candidate(
        "RS",
        PROGRAMMES,
        "https://studyinserbia.rs/catalogue-of-programmes/database-of-programmes/",
        "Foundation Tempus Study in Serbia English-taught Master's catalogue",
        "https://tempus.ac.rs",
        "curated",
        False,
    ),
    Candidate(
        "RS",
        SCHOLARSHIPS,
        "https://fondzamladetalente.gov.rs/konkursi/",
        "Fund for Young Talents of the Republic of Serbia (Dositeja Master's scholarships)",
        "https://nitra.gov.rs",
        "curated",
        True,
    ),
    Candidate(
        "RS",
        QUALIFICATIONS_REGISTER,
        "https://www.nat.rs/vodic-za-studente/",
        "National Entity for Accreditation and Quality Assurance (NAT) register",
        "https://www.nat.rs",
        "curated",
        False,
    ),
    Candidate(
        "SG",
        PROGRAMMES,
        "https://www.moe.gov.sg/coursefinder",
        "Singapore Ministry of Education official CourseFinder",
        "https://www.moe.gov.sg",
        "curated",
        True,
    ),
    Candidate(
        "SG",
        SCHOLARSHIPS,
        "https://www.moe.gov.sg/financial-matters/awards-scholarships",
        "Singapore Ministry of Education official awards & scholarships directory",
        "https://www.moe.gov.sg",
        "curated",
        True,
    ),
    Candidate(
        "SG",
        SCHOLARSHIPS,
        "https://www.psc.gov.sg/scholarships/postgraduate-scholarships/lee-kuan-yew-scholarship/",
        "Public Service Commission (PSC) Lee Kuan Yew & postgraduate scholarships",
        "https://www.psc.gov.sg",
        "curated",
        True,
    ),
    Candidate(
        "SG",
        FOUNDATION_DIRECTORIES,
        "https://www.charities.gov.sg/Pages/AdvanceSearch.aspx",
        "Commissioner of Charities Singapore official charity & foundation search portal",
        "https://www.charities.gov.sg",
        "curated",
        True,
    ),
    Candidate(
        "SG",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://nqo.sg/talent-development/masters-scholarships/",
        "National Quantum Office (NQO) National Quantum Master's Scholarships",
        "https://www.nrf.gov.sg",
        "curated",
        False,
    ),
    Candidate(
        "PK",
        SCHOLARSHIPS,
        "https://www.hec.gov.pk/english/scholarshipsgrants/lao/Pages/default.aspx",
        "HEC Pakistan Learning Opportunities Abroad (LAO) foreign government Master's scholarships",
        "https://www.hec.gov.pk",
        "curated",
        True,
    ),
    Candidate(
        "PK",
        SCHOLARSHIPS,
        "https://www.usefp.org/scholarships/fulbright-degree.cfm",
        "USEFP Fulbright Master's Degree Program for Pakistan",
        "https://www.usefp.org",
        "curated",
        False,
    ),
    Candidate(
        "PK",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.peef.org.pk/masterlevel-scholarships",
        "Punjab Educational Endowment Fund (PEEF) Master's Level Scholarships",
        "https://www.peef.org.pk",
        "curated",
        False,
    ),
    Candidate(
        "PK",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://seef.sindh.gov.pk/",
        "Sindh Educational Endowment Fund (SEEF) postgraduate scholarships",
        "https://sindh.gov.pk",
        "curated",
        True,
    ),
    Candidate(
        "PK",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://beef.org.pk/",
        "Balochistan Education Endowment Fund (BEEF) postgraduate scholarships",
        "https://gob.pk",
        "curated",
        False,
    ),
    Candidate(
        "QA",
        SCHOLARSHIPS,
        "https://www.qatarscholarships.qa/en-US/programs/",
        "Qatar Scholarships (QFD / QF) official international Master's scholarship portal",
        "https://qatarfund.org.qa",
        "curated",
        False,
    ),
    Candidate(
        "QA",
        PROGRAMMES,
        "https://www.qatarscholarships.qa/en-US/partner-institutions/",
        "Qatar Scholarships / Education City partner universities & graduate programmes",
        "https://www.qf.org.qa",
        "curated",
        False,
    ),
    Candidate(
        "QA",
        EXCELLENCE_GRADUATE_SCHOOLS,
        "https://innolight.qrdi.org.qa/opportunities/p/24",
        "QRDI Qatar Research, Development and Innovation Council graduate research opportunities",
        "https://www.qrdi.org.qa",
        "curated",
        False,
    ),
    Candidate(
        "AU",
        QUALIFICATIONS_REGISTER,
        "https://cricos.education.gov.au/",
        "Australian Government CRICOS register of institutions and courses for overseas students",
        "https://www.education.gov.au",
        "curated",
        True,
    ),
    Candidate(
        "AU",
        QUALIFICATIONS_REGISTER,
        "https://www.teqsa.gov.au/national-register",
        "TEQSA National Register of higher education providers and accredited courses",
        "https://www.teqsa.gov.au",
        "curated",
        True,
    ),
    Candidate(
        "AU",
        FOUNDATION_DIRECTORIES,
        "https://www.acnc.gov.au/charity/charities",
        "Australian Charities and Not-for-profits Commission (ACNC) Charity Register",
        "https://www.acnc.gov.au",
        "curated",
        True,
    ),
    Candidate(
        "AU",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.studymelbourne.vic.gov.au/study-options/scholarships",
        "Study Melbourne Victorian Government international student scholarships",
        "https://www.vic.gov.au",
        "curated",
        True,
    ),
    Candidate(
        "AU",
        SUBNATIONAL_SCHOLARSHIPS,
        "https://www.studyperth.com.au/courses-and-universities/scholarships/",
        "StudyPerth Western Australian Government international student scholarships",
        "https://www.wa.gov.au",
        "curated",
        False,
    ),
)


def load_curated_databases(
    country_code: str | None = None,
    kind: str | None = None,
    *,
    csv_path: str | Path | None = None,
) -> tuple[Candidate, ...]:
    """Return curated + CSV-indexed national search databases for `country_code` and `kind`."""
    results: list[Candidate] = []
    seen_urls: set[str] = set()

    for item in VERIFIED_MULTI_TIER_DATABASES:
        if country_code and item.country_code != country_code.upper():
            continue
        if kind and item.kind != kind:
            continue
        if item.url not in seen_urls:
            seen_urls.add(item.url)
            results.append(item)

    default_csv = (
        Path(csv_path)
        if csv_path is not None
        else Path(__file__).resolve().parents[2]
        / "docs"
        / "research"
        / "national-study-databases.csv"
    )
    if default_csv.exists():
        with default_csv.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row_cc = (row.get("country_code") or "").strip().upper()
                row_kind = (row.get("kind") or "").strip()
                row_url = (row.get("url") or "").strip()
                if not row_url or row_url in seen_urls:
                    continue
                if country_code and row_cc != country_code.upper():
                    continue
                if kind and row_kind != kind:
                    continue
                seen_urls.add(row_url)
                results.append(
                    Candidate(
                        country_code=row_cc,
                        kind=row_kind,
                        url=row_url,
                        label=row.get("label") or "",
                        found_on=row.get("found_on") or "",
                        route=row.get("route") or "csv",
                        government_host=(row.get("government_host") == "yes"),
                    )
                )
    return tuple(results)


_FAMILY_BY_DB_KIND: dict[str, str] = {
    SCHOLARSHIPS: "GOVERNMENT_SCHOLARSHIP",
    SUBNATIONAL_SCHOLARSHIPS: "GOVERNMENT_SCHOLARSHIP",
    FOUNDATION_DIRECTORIES: "FOUNDATION_SCHOLARSHIP",
    EXCELLENCE_GRADUATE_SCHOOLS: "UNIVERSITY_SCHOLARSHIP",
}


@dataclass(frozen=True)
class NationalDatabasesSource:
    """`LeadSource` that emits national search databases for `query.country_code`."""

    name: str = "national-databases"
    curated_only: bool = True
    one_programme_per_link: bool = False
    awards_jointly: bool = False

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        seen: set[str] = set()
        terms = (
            _expanded_field_terms_for_country(query.country_code, query.field, max_terms=2)
            if query.field.strip()
            else ()
        )
        for cand in load_curated_databases(country_code=query.country_code or None):
            if self.curated_only and cand.route not in ("curated", "ec_profile"):
                continue
            source_type = (
                "FUNDER"
                if cand.kind in _FAMILY_BY_DB_KIND
                else "PROGRAM"
            )
            family = _FAMILY_BY_DB_KIND.get(cand.kind, "")
            discovered_by = f"{self.name}:{cand.kind.lower()}"
            target_urls: list[str] = [cand.url]
            if terms:
                template = _match_portal_template(cand.url)
                if template is not None:
                    for term in terms:
                        rendered = template.format(query=quote_plus(term)).replace(" ", "%20")
                        if rendered not in target_urls:
                            target_urls.append(rendered)
            for url in target_urls:
                if url in seen:
                    continue
                seen.add(url)
                try:
                    yield ResearchLead.from_url(
                        url,
                        source_type=source_type,
                        funding_family=family,
                        discovered_by=discovered_by,
                    )
                except ValueError:
                    continue


#: Parameterized GET search URL templates keyed by canonical portal URL prefix.
#: Each template interpolates `{query}` (URL-encoded field/keyword) and filters
#: to Master's degree programmes or Master's scholarships where supported.
PORTAL_SEARCH_URL_TEMPLATES: dict[str, str] = {
    "https://www2.daad.de/deutschland/studienangebote/international-programmes/en": (
        "https://www2.daad.de/deutschland/studienangebote/international-programmes/en/result/"
        "?q={query}&degree%5B%5D=2"
    ),
    "https://www2.daad.de/deutschland/stipendium/datenbank/en": (
        "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/"
        "?status=3&q={query}"
    ),
    "https://www.hochschulkompass.de": (
        "https://www.hochschulkompass.de/en/degree-programmes/study-in-germany-search/"
        "advanced-degree-programme-search.html?tx_szhrksearch_pi1%5Bsearch%5D=1"
        "&tx_szhrksearch_pi1%5Babschluss%5D%5B%5D=37&tx_szhrksearch_pi1%5Bfach%5D={query}"
    ),
    "https://www.stipendienlotse.de": (
        "https://www.stipendienlotse.de/datenbank.php?stichwort={query}"
    ),
    "https://monmaster.gouv.fr": (
        "https://monmaster.gouv.fr/recherche?recherche={query}"
    ),
    "https://www.studienwahl.at": (
        "https://www.studienwahl.at/en/?s={query}"
    ),
    "https://www.studyinflanders.be/programmes": (
        "https://www.studyinflanders.be/programmes?search={query}&level%5B40%5D=40"
    ),
    "https://www.studyinbelgium.be": (
        "https://www.studyinbelgium.be/en/our-formations?keys={query}"
    ),
    "https://www.studyinnl.org/dutch-education/studies": (
        "https://www.studyinnl.org/dutch-education/studies?search={query}&type=Master"
    ),
    "https://www.studyinnl.org/finances": (
        "https://www.studyinnl.org/finances?search={query}"
    ),
    "https://www.universityadmissions.se": (
        "https://www.universityadmissions.se/intl/search?period=1&freeText={query}&level=master"
    ),
    "https://opintopolku.fi": (
        "https://opintopolku.fi/konfo/en/haku?koulutustyyppi=maisteri,amk-ylempi&hakusana={query}"
    ),
    "https://studyinnorway.no": (
        "https://studyinnorway.no/study-opportunities?search={query}"
    ),
    "https://www.studyprogrammes.ch": (
        "https://www.studyprogrammes.ch/en/results?q={query}&level=master"
    ),
    "https://www.studyinswitzerland.plus": (
        "https://www.studyinswitzerland.plus/?s={query}"
    ),
    "https://www.fhmaster.ch": (
        "https://www.fhmaster.ch/?s={query}"
    ),
    "https://data.snf.ch": (
        "https://data.snf.ch/grants?q={query}"
    ),
    "https://studyin.gov.cz/study-programmes": (
        "https://studyin.gov.cz/study-programmes?q={query}&degree=M"
    ),
    "https://studyin.gov.cz/scholarships": (
        "https://studyin.gov.cz/scholarships?q={query}"
    ),
    "https://portal.studyin.cz": (
        "https://studyin.gov.cz/study-programmes?q={query}&degree=M"
    ),
    "https://www.studujnavs.gov.cz": (
        "https://www.studujnavs.gov.cz/studijni-programy?q={query}"
    ),
    "https://www.studyinestonia.ee": (
        "https://www.studyinestonia.ee/study/programmes?title={query}&field_degree_level_value=Master"
    ),
    "https://studyin.lt": (
        "https://studyin.lt/programs/?search={query}&degree=master"
    ),
    "https://study.gov.pl": (
        "https://study.gov.pl/studyfinder?search={query}&level=2"
    ),
    "https://apply.stipendiumhungaricum.hu": (
        "https://apply.stipendiumhungaricum.hu/courses?q={query}&level=Master"
    ),
    "https://stipendiumhungaricum.hu": (
        "https://apply.stipendiumhungaricum.hu/courses?q={query}&level=Master"
    ),
    "https://studyinhungary.hu": (
        "https://studyinhungary.hu/study-in-hungary/menu/find-a-study-programme.html?q={query}"
    ),
    "https://studyindenmark.dk": (
        "https://studyindenmark.dk/portal?SearchableText={query}&degree=master"
    ),
    "https://masters.minedu.gov.gr": (
        "https://masters.minedu.gov.gr/?s={query}"
    ),
    "https://www.qualifax.ie": (
        "https://www.qualifax.ie/courses?keyword={query}&nfqLevel=9"
    ),
    "https://study-uk.britishcouncil.org": (
        "https://study-uk.britishcouncil.org/plan-studies/Choosing-a-course?q={query}&level=postgraduate"
    ),
    "https://www.jpss.jp": (
        "https://www.jpss.jp/en/search/?q={query}&dc=2"
    ),
    "https://search.studyaustralia.gov.au/courses": (
        "https://search.studyaustralia.gov.au/courses?SpecifyKeyWord={query}&LevelOfStudyId=7"
    ),
    "https://search.studyaustralia.gov.au/scholarship": (
        "https://search.studyaustralia.gov.au/scholarship?SpecifyKeyWord={query}&LevelOfStudyId=7"
    ),
    "https://www.studywithnewzealand.govt.nz/en/study-options/search/courses": (
        "https://www.studywithnewzealand.govt.nz/en/study-options/search/courses?q={query}&level=masters"
    ),
    "https://www.educanada.ca/programs-programmes": (
        "https://www.educanada.ca/programs-programmes/index.aspx?lang=eng&q={query}"
    ),
    "https://taughtie.campusfrance.org": (
        "https://taughtie.campusfrance.org/tiesearch/#/catalog?keywords={query}"
    ),
    "https://campusbourses.campusfrance.org": (
        "https://campusbourses.campusfrance.org/#/catalog?keywords={query}"
    ),
    "https://grants.at": (
        "https://grants.at/en/?q={query}"
    ),
    "https://www.universitaly.it": (
        "https://www.universitaly.it/cerca-corsi?search={query}"
    ),
    "https://www.educacion.gob.es/ruct": (
        "https://www.educacion.gob.es/ruct/consultaestudios?actual=estudios&text={query}"
    ),
    "https://study-research.pt": (
        "https://study-research.pt/en/?s={query}"
    ),
    "https://iesuperior.pt": (
        "https://iesuperior.pt/?s={query}"
    ),
    "https://studyinromania.gov.ro": (
        "https://studyinromania.gov.ro/fp/index.php?route=product/search&search={query}"
    ),
    "https://rsvu.mon.bg": (
        "https://rsvu.mon.bg/#/universities?locale=en&search={query}"
    ),
    "https://hko.srce.hr": (
        "https://hko.srce.hr/usp/index?lang=en&vrsta=6&q={query}"
    ),
    "https://www.studyincroatia.hr": (
        "https://www.studyincroatia.hr/?s={query}"
    ),
    "https://studyinslovenia.si": (
        "https://studyinslovenia.si/?s={query}"
    ),
    "https://www.portalvs.sk": (
        "https://www.portalvs.sk/en/studijne-programy?search={query}&stupen=2"
    ),
    "https://www.scholarships.sk": (
        "https://www.scholarships.sk/en/main/search?q={query}"
    ),
    "https://studyinlatvia.lv": (
        "https://studyinlatvia.lv/studies?search={query}&level=master"
    ),
    "https://mengstudien.public.lu": (
        "https://mengstudien.public.lu/en/support/recherche.html?q={query}"
    ),
    "https://qualifications.mfhea.gov.mt": (
        "https://qualifications.mfhea.gov.mt/#/qualifications?search={query}"
    ),
    "https://www.highereducation.ac.cy": (
        "https://www.highereducation.ac.cy/index.php/en/component/finder/search?q={query}"
    ),
    "https://study.iceland.is": (
        "https://study.iceland.is/study-in-iceland?q={query}"
    ),
    "https://www.bazaobrazovanja.rs": (
        "https://www.bazaobrazovanja.rs/en/programmes?type=11&keywords={query}"
    ),
    "https://studyinserbia.rs": (
        "https://studyinserbia.rs/?s={query}"
    ),
    "https://www.studyinturkiye.gov.tr": (
        "https://www.studyinturkiye.gov.tr/StudySearch/List?q={query}&level=3"
    ),
    "https://www.turkiyeburslari.gov.tr": (
        "https://www.turkiyeburslari.gov.tr/en/search?q={query}"
    ),
    "https://studyinrussia.ru": (
        "https://studyinrussia.ru/en/study-in-russia/programs/?q={query}&level=magistracy"
    ),
    "https://www.campuschina.org/universities": (
        "https://www.campuschina.org/universities/categories.html?k={query}"
    ),
    "https://www.cucas.cn": (
        "https://www.cucas.cn/search/program?k={query}&degree=Master"
    ),
    "https://www.studyinkorea.go.kr": (
        "https://www.studyinkorea.go.kr/ko/search/searchMain.do?searchWord={query}"
    ),
    "https://studyinazerbaijan.edu.az": (
        "https://studyinazerbaijan.edu.az/?s={query}"
    ),
    "https://edu.gov.az": (
        "https://edu.gov.az/en/search?q={query}"
    ),
    "https://eatda.edu.az": (
        "https://eatda.edu.az/az/search?q={query}"
    ),
    "https://studyin.gov.ge": (
        "https://studyin.gov.ge/?s={query}"
    ),
    "https://educationingeorgia.ge": (
        "https://educationingeorgia.ge/program-list?search={query}"
    ),
    "https://reestri.eqe.ge": (
        "https://reestri.eqe.ge/en/search?q={query}"
    ),
    "https://studyinarmenia.org": (
        "https://studyinarmenia.org/?s={query}"
    ),
    "https://univision.kz": (
        "https://univision.kz/en/search?q={query}"
    ),
    "https://studyin-uzbekistan.uz": (
        "https://studyin-uzbekistan.uz/universities?search={query}"
    ),
    "https://www.moe.gov.sg/coursefinder": (
        "https://www.moe.gov.sg/coursefinder?search={query}"
    ),
    "https://www.charities.gov.sg": (
        "https://www.charities.gov.sg/Pages/AdvanceSearch.aspx?q={query}"
    ),
    "https://www.hec.gov.pk": (
        "https://www.hec.gov.pk/english/Search/Pages/results.aspx?k={query}"
    ),
    "https://www.edu.gov.qa": (
        "https://www.edu.gov.qa/en/Search/Pages/results.aspx?k={query}"
    ),
    "https://nces.ed.gov/collegenavigator": (
        "https://nces.ed.gov/collegenavigator/?q={query}&l=93"
    ),
    "https://studyinsaudi.moe.gov.sa": (
        "https://studyinsaudi.moe.gov.sa/Universities?search={query}"
    ),
    "https://studyinsaudi.sa": (
        "https://studyinsaudi.sa/en/Programs?degree=Master&search={query}"
    ),
}


def _normalize_portal_prefix(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}"


def _match_portal_template(url: str) -> str | None:
    norm_url = _normalize_portal_prefix(url)
    for prefix, template in PORTAL_SEARCH_URL_TEMPLATES.items():
        if norm_url.startswith(_normalize_portal_prefix(prefix)):
            return template
    return None


def _expanded_field_terms_for_country(
    country_code: str,
    field: str,
    *,
    max_terms: int = 3,
) -> tuple[str, ...]:
    if not field.strip():
        return ("master",)
    resolution = resolve_field_taxonomy(field)
    en_terms = list(dict.fromkeys(resolution.canonical_degree_titles))[:max_terms]
    steering = STEERING.get(country_code.strip().upper())
    local_terms: tuple[str, ...] = ()
    if steering is not None and steering.language != "en":
        local_terms = localized_field_terms(field, steering.language)[:2]
    combined = list(dict.fromkeys([*en_terms, *local_terms]))
    return tuple(combined[: max_terms + len(local_terms)]) or (field.strip(),)


def build_portal_search_urls(
    country_code: str,
    *,
    field: str = "",
    kind: str | None = None,
    max_terms: int = 3,
    csv_path: str | Path | None = None,
) -> tuple[str, ...]:
    """Build parameterized GET search URLs across a country's curated databases.

    Expands `field` via `resolve_field_taxonomy` and `localized_field_terms`
    (so `"AI with chemistry"` queries `"digital chemistry"`, `"chemoinformatics"`,
    and the native-language term such as `"chimica digitale"` or `"Chemoinformatik"`).
    """
    candidates = load_curated_databases(
        country_code=country_code, kind=kind, csv_path=csv_path
    )
    terms = _expanded_field_terms_for_country(country_code, field, max_terms=max_terms)
    urls: list[str] = []
    for cand in candidates:
        if cand.route not in ("curated", "ec_profile"):
            continue
        template = _match_portal_template(cand.url)
        if template is not None:
            for term in terms:
                rendered = template.format(query=quote_plus(term)).replace(" ", "%20")
                if rendered not in urls:
                    urls.append(rendered)
    return tuple(urls)


_LOCAL_PORTAL_MODIFIERS: dict[str, str] = {
    "fr": '("master" OR "MSc" OR "bourse")',
    "it": '("laurea magistrale" OR "master" OR "borse")',
    "de": '("Master" OR "Stipendium")',
    "es": '("máster" OR "maestría" OR "beca")',
    "pt": '("mestrado" OR "2.º ciclo" OR "bolsa")',
    "nl": '("master" OR "MSc" OR "studiebeurs" OR "scholarship")',
    "tr": '("yüksek lisans" OR "master" OR "burs")',
    "az": '("magistratura" OR "master" OR "təqaüd")',
    "kk": '("магистратура" OR "грант" OR "стипендия")',
    "uz": '("magistratura" OR "grant" OR "stipendiya")',
    "ka": '("მაგისტრატურა" OR "სამაგისტრო" OR "სტიპენდია" OR "გრანტი")',
    "ru": '("магистратура" OR "master" OR "стипендия")',
    "zh": '("硕士" OR "master" OR "奖学金")',
    "ja": '("修士" OR "master" OR "奨学金")',
    "ko": '("석사" OR "master" OR "장학금")',
    "sr": '("master akademske studije" OR "master" OR "stipendija")',
    "hr": '("diplomski studij" OR "master" OR "stipendija")',
    "cs": '("navazující magisterské" OR "magisterské" OR "stipendium")',
    "fi": '("maisteri" OR "ylempi korkeakoulututkinto" OR "apuraha" OR "stipendi")',
    "sv": '("masterprogram" OR "magister" OR "stipendium")',
    "ur": '("ماسٹرز" OR "ایم فل" OR "اسکالرشپ" OR "وظیفہ")',
    "ar": '("ماجستير" OR "دراسات عليا" OR "منحة" OR "ابتعاث")',
    "bg": '("магистър" OR "магистратура" OR "стипендия")',
    "el": '("μεταπτυχιακό" OR "ΠΜΣ" OR "υποτροφία")',
    "lt": '("magistrantūra" OR "magistro" OR "stipendija")',
    "no": '("masterprogram" OR "mastergrad" OR "stipend")',
    "et": '("magistriõpe" OR "magister" OR "stipendium")',
    "da": '("kandidatuddannelse" OR "kandidat" OR "legat" OR "stipendium")',
    "hu": '("mesterképzés" OR "ösztöndíj")',
    "is": '("meistaranám" OR "styrkur")',
    "lv": '("maģistrantūra" OR "maģistra" OR "stipendija")',
    "sk": '("magisterské štúdium" OR "štipendium")',
    "sl": '("magistrski študij" OR "štipendija")',
    "hy": '("մագիստրատուրա" OR "կրթաթոշակ")',
    "ms": '("sarjana" OR "pascasiswazah" OR "biasiswa")',
    "ro": '("master" OR "masterat" OR "bursă")',
    "hi": '("स्नातकोत्तर" OR "मास्टर" OR "छात्रवृत्ति")',
    "vi": '("thạc sĩ" OR "cao học" OR "học bổng")',
    "id": '("magister" OR "pascasarjana" OR "beasiswa")',
    "pl": '("studia magisterskie" OR "stypendium")',
}


def build_database_site_requests(
    country_code: str,
    *,
    field: str = "",
    kind: str | None = None,
    num_results: int = 10,
    csv_path: str | Path | None = None,
) -> tuple[SearchRequest, ...]:
    """Build domain-scoped `SearchRequest` queries (`site:<portal_host>`, `denylist=()`)
    for a country's national study/scholarship databases.

    Because national portals (`campusfrance.org`, `daad.de`, `universitaly.it`,
    `studyinkorea.go.kr`, `campuschina.org`, etc.) are listed in `AGGREGATOR_DOMAINS`
    and many use JS/SPA shells at their root URL, querying them through a search
    provider requires `denylist=()` and `site:<portal_host>` with expanded field
    terms, followed by `extract_catalogue_hops` on the returned portal pages.
    """
    cc = country_code.strip().upper()
    candidates = load_curated_databases(country_code=cc, kind=kind, csv_path=csv_path)
    steering = STEERING.get(cc)
    lang = steering.language if steering is not None else "en"

    if field.strip():
        resolution = resolve_field_taxonomy(field)
        en_titles = list(dict.fromkeys(resolution.canonical_degree_titles))[:4]
        en_clause = "(" + " OR ".join(f'"{t}"' for t in en_titles) + ")"
    else:
        en_clause = ""

    local_terms = localized_field_terms(field, lang)[:3] if (field.strip() and lang != "en") else ()
    local_clause = "(" + " OR ".join(f'"{t}"' for t in local_terms) + ")" if local_terms else ""

    requests: list[SearchRequest] = []
    seen_queries: set[str] = set()
    for cand in candidates:
        if cand.route not in ("curated", "ec_profile"):
            continue
        host = (urlsplit(cand.url).hostname or "").lower().removeprefix("www.")
        if not host:
            continue
        is_funding = cand.kind in _FAMILY_BY_DB_KIND
        en_mod = (
            '("master" OR "MSc") ("scholarship" OR "grant" OR "fellowship" OR "waiver")'
            if is_funding
            else '("master" OR "MSc" OR "degree" OR "programme")'
        )
        q_en = f"site:{host} {en_clause} {en_mod}".strip()
        q_en = " ".join(q_en.split())
        if q_en not in seen_queries:
            seen_queries.add(q_en)
            requests.append(
                SearchRequest(
                    query=q_en,
                    country_code=cc,
                    language="en",
                    phrasing="english",
                    max_results=num_results,
                    denylist=(),
                )
            )
        if lang != "en" and (local_clause or lang in _LOCAL_PORTAL_MODIFIERS):
            local_mod = _LOCAL_PORTAL_MODIFIERS.get(lang, '("master" OR "MSc")')
            f_clause = local_clause or en_clause
            q_loc = f"site:{host} {f_clause} {local_mod}".strip()
            q_loc = " ".join(q_loc.split())
            if q_loc not in seen_queries:
                seen_queries.add(q_loc)
                requests.append(
                    SearchRequest(
                        query=q_loc,
                        country_code=cc,
                        language=lang,
                        phrasing="local",
                        max_results=num_results,
                        denylist=(),
                    )
                )
    return tuple(requests)


def query_national_databases(
    country_code: str,
    *,
    field: str = "",
    kind: str | None = None,
    fetch_html: Callable[[str], bytes] | None = None,
    search_provider: SearchProvider | None = None,
    record_pointers: bool = False,
    csv_path: str | Path | None = None,
) -> tuple[ResearchLead, ...]:
    """Query a country's national databases via parameterized URL templates and/or
    domain-scoped search, hopping every portal page through `extract_catalogue_hops`
    to return official university and funder `ResearchLead` targets.
    """
    cc = country_code.strip().upper()
    candidates = [
        c
        for c in load_curated_databases(country_code=cc, kind=kind, csv_path=csv_path)
        if c.route in ("curated", "ec_profile")
    ]
    kind_by_host: dict[str, str] = {}
    for cand in candidates:
        host = (urlsplit(cand.url).hostname or "").lower().removeprefix("www.")
        if host and host not in kind_by_host:
            kind_by_host[host] = cand.kind

    portal_urls: list[str] = list(
        build_portal_search_urls(cc, field=field, kind=kind, csv_path=csv_path)
    )
    if search_provider is not None:
        for req in build_database_site_requests(cc, field=field, kind=kind, csv_path=csv_path):
            for hit_url in search_provider.search(req):
                if hit_url and hit_url not in portal_urls:
                    portal_urls.append(hit_url)

    leads: list[ResearchLead] = []
    seen_urls: set[str] = set()
    if fetch_html is None:
        return ()

    for portal_url in portal_urls:
        try:
            html = fetch_html(portal_url)
        except Exception as exc:
            logging.getLogger(__name__).debug("portal fetch failed for %s: %s", portal_url, exc)
            continue
        if not html:
            continue
        host = (urlsplit(portal_url).hostname or "").lower().removeprefix("www.")
        matched_kind = kind_by_host.get(host, kind or PROGRAMMES)
        source_type = "FUNDER" if matched_kind in _FAMILY_BY_DB_KIND else "PROGRAM"
        family = _FAMILY_BY_DB_KIND.get(matched_kind, "")
        hopped = extract_catalogue_hops(
            html,
            base_url=portal_url,
            source_type=source_type,
            funding_family=family,
            record_pointers=record_pointers,
        )
        for lead in hopped:
            if lead.canonical_url not in seen_urls:
                seen_urls.add(lead.canonical_url)
                leads.append(lead)
    return tuple(leads)
