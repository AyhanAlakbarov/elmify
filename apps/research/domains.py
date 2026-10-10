"""Hosts that route research but can never support a claim (design §7.2).

One list, several consumers: `discovery.from_url` demotes any lead on these
hosts to AGGREGATOR, every search adapter sends them as its exclusion
parameter, and `is_hoppable_catalogue` tells `search.SearchSource` which of
them still have an institution behind them worth hopping to. Keeping them in
one place is the point -- the failure mode this prevents is a host being
excluded in one place and trusted in another.

`CATALOGUE_DOMAINS` is the original 23 plus the national catalogues.
`AGGREGATOR_DOMAINS` is that list plus what the 2026-09-17 probe found ranking
above the origin, and it is what `is_catalogue` actually tests: a host denied
to an adapter and trusted by `from_url` is exactly the split this module exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Official national study catalogues for the destination list (owner,
#: 2026-09-26), each run by a ministry or its agency and checked live that day.
#: Like DAAD above, they route to the institution and never speak for it: a
#: Study in Holland page read as the university would put a middleman into the
#: provenance chain. A country with no official catalogue has no row (Brunei,
#: the Gulf, Singapore, Mexico). Slovakia and Malta are absent because no
#: official operator could be confirmed for their "Study in" sites; Bulgaria's
#: has a broken TLS setup, and Cyprus's and Portugal's do not resolve -- all
#: three are unchecked, not ruled out. Spain is SEPIE, the ministry's
#: internationalisation agency (owner-supplied); the ministry's own e-office,
#: universidades.sede.gob.es, is left off because it is where the ministry
#: speaks for itself -- procedures and grant calls, not a catalogue.
#: campuschina.org is deliberately absent: it is the China Scholarship
#: Council's own site, so it speaks for the Chinese Government Scholarship.
_NATIONAL_CATALOGUES = (
    "studyinaustria.at",
    "studyinflanders.be",
    "studyinbelgium.be",
    "studyincroatia.hr",
    "studyin.cz",
    "studyin.gov.cz",
    "studyindenmark.dk",
    "studyinestonia.ee",
    "studyinfinland.fi",
    "studyinfo.fi",
    "opintopolku.fi",
    "study-in-germany.de",
    "study-in-germany.com",
    "hochschulkompass.de",
    "studyingreece.edu.gr",
    "studyinhungary.hu",
    "educationinireland.com",
    "universitaly.it",
    "sepie.es",
    "studyinitaly.esteri.it",
    "studyinlatvia.lv",
    "studyin.lt",
    "studyinlithuania.lt",
    "studyinnl.org",
    "studyinholland.nl",
    "study.gov.pl",
    "go-poland.pl",
    "studyinromania.gov.ro",
    "studyinslovenia.si",
    "studyinsweden.se",
    "studyinnorway.no",
    "swissuniversities.ch",
    "studyiniceland.is",
    "study.iceland.is",
    "studyinserbia.rs",
    "studyinturkiye.gov.tr",
    "studyinjapan.go.jp",
    "studyinrussia.ru",
    "studyinazerbaijan.edu.az",
    "educationingeorgia.ge",
    "studyingeorgia.ge",
    "studyinchina.edu.cn",
    "studyaustralia.gov.au",
    "studywithnewzealand.govt.nz",
    "study-uk.britishcouncil.org",
    "educationusa.state.gov",
    "educanada.ca",
    # From the 2026-09-26 Exa + Brave sweep: national registers and course
    # finders on a host whose whole job is the catalogue. A ministry's own
    # site is never listed -- it also speaks for the ministry's grants.
    "monmaster.gouv.fr",
    "discoveruni.gov.uk",
    "masters.minedu.gov.gr",
    "studies.minedu.gov.gr",
    "hko.srce.hr",
    "regvssp.msmt.cz",
    "highereducation.be",
    "studienwahl.at",
    "nto.hea.ie",
    "niid.lv",
    "polon.nauka.gov.pl",
    "dges.gov.pt",
    "www.portalvs.sk",
    "studyinslovakia.saia.sk",
    "qualifications.mfhea.gov.mt",
    "bazaobrazovanja.rs",
    "russia-edu.minobrnauki.gov.ru",
    "yz.chsi.com.cn",
    "studyinsaudi.moe.gov.sa",
    "study-in-egypt.gov.eg",
    "cricos.education.gov.au",
    "tahatu.govt.nz",
    "snies.mineducacion.gov.co",
    "emec.mec.gov.br",
    "postgrado.consejoderectores.cl",
    "allqs.saqa.org.za",
    "whed.net",
)

_ROUTING = (
    # Official catalogues: they route to the institution, they do not speak for it.
    "daad.de",
    "eacea.ec.europa.eu",
    "erasmus-plus.ec.europa.eu",
    "studyinkorea.go.kr",
    "campusfrance.org",
    "uni-assist.de",
    # National application services, like uni-assist: a form, not a catalogue.
    "studielink.nl",
    "universityadmissions.se",
    "ucas.com",
    "studij.hr",
    "portal.evs.gov.si",
    "tuyensinh.moet.gov.vn",
    # Click-trackers and shorteners: a hop, never a source.
    "direc.to",
    # Commercial aggregators and forums, from the 2026-08-26 probe's noise.
    "mastersportal.com",
    "bachelorsportal.com",
    "scholarshipportal.com",
    "studyportals.com",
    "keystoneacademic.com",
    "stage-etudiant.fr",
    "reddit.com",
    "quora.com",
    "medium.com",
    # Social profiles. Every official catalogue page carries a row of them, and
    # a live EACEA harvest on 2026-08-28 pulled in bsky.app/profile/ec.europa.eu
    # because only facebook.com was listed. A social profile routes attention,
    # never a claim.
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "bsky.app",
)

CATALOGUE_DOMAINS = (*_ROUTING, *_NATIONAL_CATALOGUES)


#: Aggregators the 2026-09-17 probe ranked above the origin, on top of the
#: catalogues held above. Collected from 862 classified hosts across four
#: providers: each one is a page that describes funding it does not administer, so it can
#: route research and can never support a claim.
_PROBE_AGGREGATORS = (
    "scholars4dev.com",
    "scholarshiproar.com",
    "scholarshipdb.net",
    "findamasters.com",
    "findaphd.com",
    "educations.com",
    "topuniversities.com",
    "timeshighereducation.com",
    "studyabroad.com",
    "hotcoursesabroad.com",
    "scholarshipscorner.website",
    "opportunitydesk.org",
    "scholarshipregion.com",
    "youthop.com",
    "armacad.info",
    # Regional, from the Azerbaijani and Turkish legs.
    "edumap.az",
    "xaricdetehsil.net",
    "tehsilxeberleri.az",
    "kariyer.net",
    "burslar.net",
    # Forums and Q&A beyond the three already listed above.
    "stackexchange.com",
    "vk.com",
    "telegram.me",
    "t.me",
    # Hosting platforms and CDNs, added 2026-09-23 after the first live TR
    # sweep recorded amazonaws.com, azureedge.net and blogspot.com as candidate
    # funders. A registrable domain here names the landlord, never the
    # publisher, so it can route research and can never support a claim --
    # the same reason an aggregator is on this list.
    "amazonaws.com",
    "cloudfront.net",
    "azureedge.net",
    "googleusercontent.com",
    "googleapis.com",
    "blogspot.com",
    "wordpress.com",
    "wixsite.com",
    "weebly.com",
    "github.io",
)

#: Commercial programme listings from the 2026-09-26 Exa + Brave sweep over
#: every destination country, widest-reaching first. Each ranked for "search
#: all master's programmes in <country>"; none administers a programme or an
#: award. Includes the "Study in <country>" lookalikes (studyinX.eu, .com)
#: whose official counterparts sit in _NATIONAL_CATALOGUES. Education lenders
#: the sweep also returned (Credila, Avanse, Leap, GradRight) are left off:
#: BANK_OR_LENDER is a holder type, and this list would deny them the register.
_SWEEP_AGGREGATORS = (
    "master-and-more.eu", "free-apply.com", "study.eu", "distancelearningportal.com",
    "brive.com", "standyou.com", "smapse.com", "shiksha.com", "unipage.net",
    "beyondthestates.com", "studee.com", "upgrad.com", "aeccglobal.com", "idp.com",
    "masterstudies.com", "best-masters.com", "studyeurope.in", "yocket.com",
    "gradsmatch.com", "usnews.com", "gostudyin.com", "edvoy.com", "globaladmissions.com",
    "prospects.ac.uk", "postgrad.com", "edwiseinternational.com", "studyqa.com",
    "goabroad.com", "rocapply.com", "jeduka.com", "studylink.com",
    "careers360.com", "mastersavenue.com", "uni2study.com",
    "manyagroup.com", "university-directory.eu", "gradschools.com",
    "internationalstudent.com", "helpstudyabroad.com", "mastergradschools.com",
)

#: The same sweep's single-country listings. Split from the wide ones only for
#: order: an adapter with a cap sends a prefix, and these reach fewer queries.
_SWEEP_LOCAL_AGGREGATORS = (
    "master-and-more.at", "masterstudies.co.uk", "hotcourses.vn", "admissionsinuae.com",
    "studyinarmenia.com", "emagister.com.ar", "lodstarstudy.com", "studyinaustria.eu",
    "studyindenmark.eu", "studyinestonia.eu", "studyiniceland.eu", "studyinnorway.eu",
    "studyinsweden.eu", "studyinslovakia.eu", "studium.at", "studienplattform.at",
    "search4study.com", "china-admissions.com", "cucas.cn", "ciss.org.cn",
    "germanpath.com", "msingermany.com", "studying-in-germany.org", "gradgermany.com",
    "mastersscout.com", "topunigermany.com", "yesgermany.com", "studying-in-spain.com",
    "studiesin.com", "educations.es", "studying-in-france.org", "studyconnectfrance.com",
    "masterscompare.co.uk", "postgraduatesearch.com", "admissionoffice.ge", "postgrad.ie",
    "planmystudy.com", "si-ireland.com", "gooverseas.com", "masterin.it",
    "koreaadmit.com", "go.study", "gradmap.co.kr", "studyleo.com", "findandstudy.com",
    "masterportalturkey.com", "studyportalturkey.com", "studyinturkiye.com",
    "mezunkampusu.com.tr", "graduateguide.com", "shorelight.com", "keuzegids.nl",
    "keuzegids.org", "welkemaster.nl", "studyinkz.kz", "studycyprus.cy", "apply.edu.pl",
    "studyinpoland.pl", "studyinireland.com", "studyin.sk", "studyinmalta.com",
    "studyinslovakia.sk", "studyprogrammes.ch", "jpss.jp", "studyinmorocco.com",
    "studyinnigeria.ng", "studyinkenya.co.ke", "studyinsaudi.sa", "studyingreece.gr",
    "studyincroatia.org", "aquiseestudia.cl", "provuz.ru", "ucheba.ru", "amberstudent.com",
)


#: The single list every adapter sends as its exclusion parameter, and the
#: one `is_catalogue` tests. One list, because the failure mode is a host
#: excluded in one place and trusted in another.
#: Ordered for the one capped adapter: Tavily sends a prefix of 150, and only
#: on name-to-site lookups, which carry no country. Past the cut sit the
#: single-country listings and the national catalogues -- a host that ranks for
#: one country's queries, never for an organisation's name in general. A host
#: past the cut is still refused afterwards (`TavilyProvider.candidates`,
#: `harness._ask`); per-country lists were weighed on 2026-09-26 and
#: change nothing sent, since the country-scoped sweep runs on Exa (cap 1200)
#: and Brave (no exclusion parameter).
AGGREGATOR_DOMAINS = (
    *_ROUTING,
    *_PROBE_AGGREGATORS,
    *_SWEEP_AGGREGATORS,
    *_SWEEP_LOCAL_AGGREGATORS,
    *_NATIONAL_CATALOGUES,
)


#: Catalogues that route to a real institution, so a lead on one is worth
#: hopping. Everything else on AGGREGATOR_DOMAINS is commercial noise.
HOPPABLE_CATALOGUES = (
    "daad.de",
    "eacea.ec.europa.eu",
    "erasmus-plus.ec.europa.eu",
    "studyinkorea.go.kr",
    "campusfrance.org",
    *_NATIONAL_CATALOGUES,
)


def _matches(host: str, domains: tuple[str, ...]) -> bool:
    normalized = host.casefold()
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in domains)


def is_catalogue(host: str) -> bool:
    # AGGREGATOR_DOMAINS, not CATALOGUE_DOMAINS: a host an adapter excludes
    # must also be one `from_url` demotes, or the denylist is advisory.
    return _matches(host, AGGREGATOR_DOMAINS)


def is_hoppable_catalogue(host: str) -> bool:
    return _matches(host, HOPPABLE_CATALOGUES)


@dataclass(frozen=True)
class Steering:
    """How to phrase a query for a country -- not how to filter one.

    There is deliberately no provider `country` or `language` code here. The
    2026-09-17 ablation measured Brave `country` at -8 local funders in
    Indonesia and inert elsewhere, Brave `search_lang` as measurably inert
    (Jaccard 1.000, 0.985, 1.000, 1.000), and Tavily `language` at -1.0 on the
    German key (-2.3 with `filter_by_language`). Every one of them narrows the
    pool instead of re-ranking it.

    What did win, in all four countries, was writing the query in the local
    language and running English as a second pass (union 110/62, 80/54, 22/14,
    84/50). So this table steers the text we compose and sends no filter.
    """

    #: ISO-639-1, the language the query is written in.
    language: str
    #: **The query itself, written in that language**, naming the country in
    #: that language too. Corrected 2026-09-23: this used to be a language
    #: *name* substituted into an English template, so the "local" pass sent
    #: English prose that merely mentioned Turkish -- the losing half of the
    #: measurement, while the docstring claimed the winning one. The first live
    #: TR sweep returned 91% non-Turkish hosts as a result.
    funder_query: str
    #: The country in English, for the second pass. Naming it is what anchors
    #: that pass: without it the query asks about scholarships in general and
    #: gets Cornell, Chevening and Canada.
    country_name: str
    #: English still adds a unique 5-35 hosts per country, so it is a second
    #: pass everywhere rather than a fallback for countries we think are small.
    english_second_pass: bool = True


#: Launch corridors, spec §5. Read only by `angles.steering_angle`, the
#: one-angle interim until item 8's vocabulary lets the generator write the
#: set (decision 38 supersedes `language` with Wikidata P37). A country absent
#: from this table gets an English query only -- correct, and visibly
#: incomplete, which is the intended shape: adding a corridor is adding a row,
#: not writing code.
#:
#: Each `funder_query` is the family's vocabulary in the country's own language
#: (*burs veren vakıflar*, *Stiftungen ... Stipendien*, *beasiswa yayasan*).
#: §6.7 has a model generating this vocabulary per (country, family); until
#: item 8 lands these hand-written rows are the one query per country, and
#: they are data precisely so adding a corridor stays a row.
STEERING = {
    "AZ": Steering(
        language="az",
        funder_query="Azərbaycanda magistratura təqaüdü verən fondlar və təşkilatlar",
        country_name="Azerbaijan",
    ),
    "TR": Steering(
        language="tr",
        funder_query="Türkiye'de yüksek lisans bursu veren vakıflar ve kurumlar",
        country_name="Türkiye",
    ),
    "KZ": Steering(
        language="kk",
        funder_query="Қазақстанда магистратура стипендиясын беретін қорлар",
        country_name="Kazakhstan",
    ),
    "GE": Steering(
        language="ka",
        funder_query="საქართველოში სამაგისტრო სტიპენდიის დამფინანსებელი ფონდები",
        country_name="Georgia",
    ),
    "UZ": Steering(
        language="uz",
        funder_query="O'zbekistonda magistratura stipendiyasi beruvchi jamg'armalar",
        country_name="Uzbekistan",
    ),
    "DE": Steering(
        language="de",
        funder_query="Stiftungen und Förderwerke mit Stipendien für ein Masterstudium",
        country_name="Germany",
    ),
    "NL": Steering(
        language="nl",
        funder_query="Fondsen en stichtingen met beurzen voor een masteropleiding in Nederland",
        country_name="the Netherlands",
    ),
    "SE": Steering(
        language="sv",
        funder_query="Stiftelser och fonder med stipendier för masterstudier i Sverige",
        country_name="Sweden",
    ),
    "FR": Steering(
        language="fr",
        funder_query="Fondations et organismes offrant des bourses de master en France",
        country_name="France",
    ),
    "HU": Steering(
        language="hu",
        funder_query="Alapítványok és ösztöndíjak mesterképzéshez Magyarországon",
        country_name="Hungary",
    ),
    "IT": Steering(
        language="it",
        funder_query="Fondazioni ed enti con borse di studio per la laurea magistrale in Italia",
        country_name="Italy",
    ),
    "ID": Steering(
        language="id",
        funder_query="Yayasan dan lembaga pemberi beasiswa S2 di Indonesia",
        country_name="Indonesia",
    ),
    "VN": Steering(
        language="vi",
        funder_query="Quỹ và tổ chức cấp học bổng thạc sĩ tại Việt Nam",
        country_name="Vietnam",
    ),
    "IN": Steering(
        language="hi",
        funder_query="भारत में स्नातकोत्तर छात्रवृत्ति देने वाले न्यास और संस्थान",
        country_name="India",
    ),
    "PK": Steering(
        language="ur",
        funder_query="پاکستان میں ماسٹرز اسکالرشپ دینے والے ادارے اور فاؤنڈیشنز",
        country_name="Pakistan",
    ),
}


#: Second-level domains whose registry verifies eligibility before allocating
#: them, mapped to the holder kind that verification establishes.
#:
#: This is not a keyword rule and not a guess about a name. `.edu.tr` requires
#: a YÖK-approved institutional certificate and `.gov.tr` a signed application
#: from the public body itself (TRABİS "belgeli alan adları", checked
#: 2026-09-24); `.ac.uk` and `.gov.uk` are the same shape. The registrar did
#: the check, so a host here carries a kind for free -- no fetch, no model
#: call -- and the classifier only has to work on the ambiguous tail.
#:
#: **It does not generalise, and the blanks are the point.** DENIC states that
#: ".de domains are available to everyone ... whether you are based in Germany
#: or abroad" -- no `gov.de`, no `edu.de`. The Netherlands and Sweden are flat
#: too. So a country with structure gets free answers and a flat one gets none,
#: and the classifier stays load-bearing everywhere: private foundations are
#: swept in every country, and in Germany that means every host is ambiguous.
#: Adding a country is adding rows; a country with no structure has no row,
#: which is correct and visibly incomplete rather than silently absent.
VERIFIED_SECOND_LEVEL = {
    # Türkiye -- TRABİS belgeli: documents required before allocation.
    "gov.tr": "NATIONAL_GOVERNMENT",
    "bel.tr": "SUBNATIONAL_GOVERNMENT",
    "edu.tr": "INSTITUTION",
    "k12.tr": "INSTITUTION",
    # Azerbaijan, Kazakhstan, Uzbekistan, Georgia.
    "gov.az": "NATIONAL_GOVERNMENT",
    "edu.az": "INSTITUTION",
    "gov.kz": "NATIONAL_GOVERNMENT",
    "edu.kz": "INSTITUTION",
    "gov.uz": "NATIONAL_GOVERNMENT",
    "gov.ge": "NATIONAL_GOVERNMENT",
    # South and South-East Asia.
    "gov.in": "NATIONAL_GOVERNMENT",
    "ac.in": "INSTITUTION",
    "edu.in": "INSTITUTION",
    "gov.pk": "NATIONAL_GOVERNMENT",
    "edu.pk": "INSTITUTION",
    "go.id": "NATIONAL_GOVERNMENT",
    "ac.id": "INSTITUTION",
    "gov.vn": "NATIONAL_GOVERNMENT",
    "edu.vn": "INSTITUTION",
    # United Kingdom and Australia.
    "gov.uk": "NATIONAL_GOVERNMENT",
    "ac.uk": "INSTITUTION",
    "gov.au": "NATIONAL_GOVERNMENT",
    "edu.au": "INSTITUTION",
    # Gulf, East Asia, Balkans, Africa, Europe -- cited zones (recognition.GOVERNMENT_ZONES).
    "gov.sa": "NATIONAL_GOVERNMENT",
    "gov.qa": "NATIONAL_GOVERNMENT",
    "gov.sg": "NATIONAL_GOVERNMENT",
    "gov.cn": "NATIONAL_GOVERNMENT",
    "gov.za": "NATIONAL_GOVERNMENT",
    "gov.it": "NATIONAL_GOVERNMENT",
}

#: Government suffixes that label a holder's kind but prove no site: no registry
#: page restricting them was found on 2026-10-03, so they are not in
#: recognition.GOVERNMENT_ZONES. A test keeps the two lists from drifting apart.
KIND_ONLY_GOVERNMENT_SUFFIXES: frozenset[str] = frozenset(
    {"bel.tr", "gov.kz", "gov.uz", "gov.in", "gov.pk", "go.id", "gov.au"}
)


def verified_kind(host: str) -> str:
    """The holder kind a registry already verified for this host, or "".

    "" is the common answer and is not a failure: it means the host is in a
    flat namespace (`.de`, `.nl`, `.se`) or under an unrestricted suffix
    (`.org.tr` is open), and the classifier decides. Never guess from "" --
    it is the absence of a check, not evidence of anything.
    """
    normalized = host.casefold().strip(".")
    return next(
        (
            kind
            for suffix, kind in VERIFIED_SECOND_LEVEL.items()
            if normalized == suffix or normalized.endswith(f".{suffix}")
        ),
        "",
    )


from .hosts import registrable_domain  # noqa: E402  (keeps the module's pure-data head readable)

#: Mail providers. An address on one of these names a mailbox, never an
#: organisation, so rung 0 (spec 6.5) resolves nothing from it and the name goes
#: to the resolver. Extend when a register surfaces a provider this list lacks;
#: never add an organisation's own domain here.
FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.com.tr", "outlook.com",
    "live.com", "msn.com", "yahoo.com", "yahoo.com.tr", "ymail.com", "yandex.com",
    "yandex.ru", "yandex.com.tr", "mail.ru", "icloud.com", "me.com", "protonmail.com",
    "proton.me", "aol.com", "gmx.de", "gmx.net", "web.de", "mynet.com", "superonline.com",
    "ttmail.com", "windowslive.com",
})


def email_domain(address: str) -> str:
    """Rung 0 of name-to-site resolution: the organisation naming its own host.

    An own-domain e-mail on a register row resolves to that registrable domain
    with no call. A free-mail address or anything malformed returns "", and the
    row stays UNRESOLVED for the resolver -- never a guess.
    """
    local, at, host = address.strip().casefold().rpartition("@")
    if not at or not local or not host or "." not in host:
        return ""
    key = registrable_domain(host)
    if not key or key in FREE_MAIL_DOMAINS:
        return ""
    return key
