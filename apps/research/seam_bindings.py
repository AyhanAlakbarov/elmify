"""The real bindings behind three of tap_seams' Protocols.

All three read SHARED catalogue tables (ClosedList, RegisterEntry, SweepRun and
its rows, ProgrammeAngle), so all run in the worker (runtime_engine); the web
tier holds no grant on any of them and never calls these -- the pack's coverage
is copied onto `PackVersion.coverage` at build time for exactly that reason.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from django.conf import settings
from django.db.models import Max, Q
from django.utils import timezone

from apps.accounts.field_taxonomy import localized_field_terms, resolve_field_taxonomy
from apps.funding.models import (
    FundingOpportunityProgram,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)

from .angles import cycle_label
from .card_engine.readers import (
    ReadersNotConfigured,
    StackMisconfigured,
    require_keys,
    run_limit,
    stack,
)
from .card_funding.card import Card
from .card_funding.entry import PAGE_BUDGET_USD, read_page
from .card_funding.store import write_card
from .classify import FrontierClassifier, classify_organisation
from .domains import STEERING
from .extraction import ResponsesAPI
from .fetch import SweepBudget
from .funding_reader import FAMILY_BY_HOLDER
from .harness import PassConfig, ladder_rung, run_pass
from .languages import CldrLanguages, pass_languages
from .models import (
    ClosedList,
    Organisation,
    OrganisationDomain,
    ProgrammeAngle,
    SweepDiscovery,
    SweepRun,
)
from .providers import SearchProvider
from .register import record_organisation
from .tap_seams import AngleRow, HostRead, PassState, RungRow, SweepOutcome
from .vgm import register_coverage

#: The rungs a closed list can hold on the ladder. Rung 0 is an enumerator
#: (Wikidata, ROR, EACEA's projects), which routes work and is no rung; rung 4
#: is "no list at all", so a rung-4 row states nothing a missing row does not.
_LADDER_RUNGS = (1, 2, 3)

logger = logging.getLogger(__name__)


class ClosedListRungSource:
    """`RungSource` over the closed-list registry: the registry IS the ladder.

    For each `(country, family)` the lowest-rung list holding any holder kind
    of that family wins, ties broken by slug -- the same rule as
    `harness.ladder_rung`. Unlike `ladder_rung`, the family is FAMILY-WIDE
    (FAMILY_BY_HOLDER, not `PASS_SHAPES[family].kinds`): the coverage line
    reports what the ladder knows of an area's bodies, and a bank register is
    part of what is known about foundations even though no open-web pass is
    diffed against it. UNSTATED wins nothing, as in `ladder_rung`: it is filed
    under PRIVATE_FOUNDATION for the reader's sake, not because a list of
    unplaceable bodies enumerates foundations.

    A list with no `RegisterEntry` rows is reported `surveyed=False` -- listed
    but not yet read -- never as "0 of N known", and never raised on as
    `ladder_rung` does: a coverage line must say it, not crash on it.
    """

    def rungs(self, country: str) -> tuple[RungRow, ...]:
        winners: dict[str, ClosedList] = {}
        lists = ClosedList.objects.filter(
            country_code=country, rung__in=_LADDER_RUNGS
        ).order_by("rung", "slug")
        for row in lists:
            for kind in row.holder_kinds:
                if kind == "UNSTATED":
                    continue
                winners.setdefault(FAMILY_BY_HOLDER[kind], row)
        out = []
        for family, row in sorted(winners.items()):
            coverage = register_coverage(row.slug)
            out.append(
                RungRow(
                    country=country,
                    family=family,
                    rung=row.rung,
                    register=row.slug,
                    listed=row.printed_size if row.printed_size is not None else coverage.listed,
                    known=coverage.bodies_known,
                    read=coverage.funds_students,
                    surveyed=coverage.listed > 0,
                )
            )
        return tuple(out)


class SweepRunPassStates:
    """`PassStates` over the sweep harness's own rows (spec 6.7).

    The area's state is its latest FINISHED `SweepRun` by `started_at`: a run
    with `finished_at` NULL did not finish and is an error, never a partial
    result (SweepRun's own docstring). No such run -> `PassState.never()`.
    """

    def state(self, country: str, family: str) -> PassState:
        run = (
            SweepRun.objects.filter(
                country_code=country, family=family, finished_at__isnull=False
            )
            .order_by("-started_at")
            .first()
        )
        if run is None:
            return PassState.never()
        return PassState(
            swept=True,
            past_economic_stop=run.stop_reason == SweepRun.StopReason.ECONOMIC,
            batches_without_new=_trailing_batches_without_new(run),
            stop_reason=run.stop_reason,
        )


class ProgrammeAngleSource:
    """`AngleSource` over `ProgrammeAngle`'s live rows.

    PROGRAMME and MONEY rows come from the latest live version whatever its
    cycle: a programme page reads the same next year, and binding them to the
    cycle left a student with no search between a cycle's turn and the next
    `generate_programme_angles` run. RECENCY rows carry {intake}, so only this
    cycle's are served (lever 6).
    """

    def __init__(self, *, fallback_on_empty: bool = False) -> None:
        self.fallback_on_empty = fallback_on_empty

    def _rows(
        self, level: str, language: str, kinds: tuple[str, ...], *, this_cycle: bool
    ) -> tuple[AngleRow, ...]:
        live = ProgrammeAngle.objects.filter(
            level=level, language=language, kind__in=kinds, retired_at__isnull=True
        )
        if this_cycle:
            live = live.filter(cycle=cycle_label(timezone.now()))
        latest = live.aggregate(v=Max("version"))["v"]
        if latest is None:
            if not self.fallback_on_empty:
                return ()
            from .programme_angles import fallback_programme_angles

            return fallback_programme_angles(level=level, language=language, kinds=kinds)
        order = {kind: i for i, kind in enumerate(kinds)}
        ranked = sorted(live.filter(version=latest), key=lambda r: (order[r.kind], r.sample))
        return tuple(
            AngleRow(str(r.id), r.language, r.template, r.kind) for r in ranked
        )

    def programme_angles(self, *, level: str, language: str) -> tuple[AngleRow, ...]:
        return self._rows(level, language, ("PROGRAMME", "MONEY"), this_cycle=False)

    def recency_angles(self, *, level: str, language: str) -> tuple[AngleRow, ...]:
        return self._rows(level, language, ("RECENCY",), this_cycle=True)


def _trailing_batches_without_new(run: SweepRun) -> int:
    """How many of the run's LAST batches found no new verified host.

    Batches are numbered 1..run.batches (harness.run_pass); "verified" is the
    flag the stop rule itself read (`SweepDiscovery.verified_in_pass`), so a
    later reclassification cannot rewrite the curve.
    """
    verified = set(
        SweepDiscovery.objects.filter(run=run, verified_in_pass=True).values_list(
            "query__batch_number", flat=True
        )
    )
    count = 0
    for number in range(run.batches, 0, -1):
        if number in verified:
            break
        count += 1
    return count


class HarnessSweeper:
    """`CellSweeper` over `harness.run_pass`, built as `sweep_organisations` builds it.

    Writes the catalogue (SweepRun and its rows), so it runs as runtime_engine.
    `classify` is injectable for tests; by default novel hosts are classified
    with the OpenAI `FrontierClassifier`, built on the first run. A ValueError
    from the harness (no angles, stale cycle, unread register) answers None and
    is logged: the queue row becomes UNAVAILABLE, never a crash.
    """

    def __init__(
        self,
        providers: Sequence[SearchProvider],
        classify: Callable[[Organisation], str] | None = None,
    ) -> None:
        self.providers = list(providers)
        self.classify = classify

    def run(self, country: str, family: str, *, budget_usd: float) -> SweepOutcome | None:
        if not settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE:  # every PASS_SHAPES family is a funder
            logger.warning("area sweep %s/%s: funder level check not live (card reader slice 3)",
                           country, family)
            return None
        if not self.providers:
            logger.warning("area sweep %s/%s: no provider key set", country, family)
            return None
        now = timezone.now()
        fetch_budget = SweepBudget(dict(settings.FETCH_SWEEP_CREDITS))
        classify = self.classify
        if classify is None:
            from openai import OpenAI

            classifier = FrontierClassifier(cast(ResponsesAPI, OpenAI().responses))
            run_id = uuid4()

            def classify(org: Organisation) -> str:
                return classify_organisation(
                    org, classifier=classifier, run_id=run_id, budget=fetch_budget, now=now
                )

        try:
            rung, register = ladder_rung(country, family)
            languages = pass_languages(country, family, source=CldrLanguages(), home_language="")
            run = run_pass(
                PassConfig(
                    country_code=country, family=family, languages=languages, rung=rung,
                    register=register, cycle=cycle_label(now), budget_usd=budget_usd,
                    home_language="",
                ),
                providers=self.providers, classify=classify, fetch_budget=fetch_budget, now=now,
            )
        except ValueError as error:
            logger.warning("area sweep %s/%s refused: %s", country, family, error)
            return None
        return SweepOutcome(
            provider_calls=run.queries.count(),
            cost_usd=Decimal(str(run.search_usd + run.fetch_usd)),
            new_hosts=run.discoveries.count(),
            stop_reason=run.stop_reason,
            run_id=run.id,
        )


_PROGRAM_MATCH_STOPWORDS: frozenset[str] = frozenset(
    {
        "master",
        "masters",
        "msc",
        "ma",
        "degree",
        "programme",
        "program",
        "programs",
        "programmes",
        "university",
        "universite",
        "universita",
        "universitat",
        "department",
        "faculty",
        "school",
        "graduate",
        "studies",
        "science",
        "sciences",
        "scholarship",
        "scholarships",
        "fellowship",
        "fellowships",
        "funding",
        "tuition",
        "waiver",
        "waivers",
        "award",
        "awards",
        "grant",
        "grants",
        "bourses",
        "bourse",
        "borse",
        "stipend",
        "stipendien",
        "international",
        "students",
        "student",
        "admission",
        "admissions",
        "https",
        "http",
        "www",
        "html",
        "htm",
        "php",
        "pdf",
        "and",
        "for",
        "the",
        "with",
    }
)


def _distinctive_tokens(text: str) -> set[str]:
    tokens = {
        tok
        for tok in re.findall(r"[a-z0-9]{3,}", text.lower())
        if tok not in _PROGRAM_MATCH_STOPWORDS
    }
    return tokens


def _match_programs_on_domain(
    programs: Sequence[Program], *, url: str, card: Card
) -> tuple[Program, ...]:
    """Match an extracted `Card` + URL to all matching `Program` rows on the same domain."""
    if not programs:
        return ()
    card_text_parts: list[str] = [url]
    for track in card.tracks:
        if track.name:
            card_text_parts.append(track.name)
        for award in track.awards:
            if award.name:
                card_text_parts.append(award.name)
            if award.name_quote and award.name_quote.text:
                card_text_parts.append(award.name_quote.text)
    haystack = " ".join(card_text_parts).lower()
    haystack_tokens = _distinctive_tokens(haystack)
    if not haystack_tokens:
        return ()

    scored: list[tuple[int, int, Program]] = []
    for idx, prog in enumerate(programs):
        prog_tokens = _distinctive_tokens(prog.name)
        if not prog_tokens:
            continue
        overlap = prog_tokens & haystack_tokens
        if not overlap:
            continue
        score = len(overlap) * 2
        # Bonus when all distinctive tokens of a multi-word specialization match
        # (e.g., "digital chemistry" or "complex systems chemistry csc").
        if len(prog_tokens) >= 2 and overlap == prog_tokens:
            score += 3
        elif len(overlap) >= 2:
            score += 2
        if score >= 2:
            scored.append((-score, idx, prog))
    if not scored:
        return ()
    scored.sort(key=lambda item: (item[0], item[1]))
    best_score = -scored[0][0]
    min_keep = max(6, best_score - 1) if best_score >= 6 else best_score
    return tuple(prog for neg_score, _, prog in scored if -neg_score >= min_keep)


_LOCAL_FUNDING_TERMS_BY_LANG: dict[str, str] = {
    "fr": '("master" OR "MSc") ("bourse" OR "bourses" OR "financement" OR "excellence")',
    "it": '("laurea magistrale" OR "master") ("borse di studio" OR "esonero" OR "bando")',
    "de": '("Master" OR "Masterstudium") ("Stipendium" OR "Stipendien" OR "Förderung")',
    "es": '("máster" OR "maestría") ("beca" OR "becas" OR "exención")',
    "pt": '("mestrado" OR "master") ("bolsa" OR "bolsas" OR "isenção")',
    "nl": '("master" OR "MSc") ("beurs" OR "studiebeurs" OR "scholarship")',
    "tr": '("yüksek lisans" OR "master") ("burs" OR "bursu" OR "muafiyet")',
    "az": '("magistratura" OR "master") ("təqaüd" OR "qrant")',
    "ru": '("магистратура" OR "магистр") ("стипендия" OR "грант")',
    "uk": '("магістратура" OR "магістр") ("стипендія" OR "грант")',
    "kk": '("магистратура" OR "магистр") ("стипендия" OR "грант")',
    "uz": '("magistratura" OR "magistr") ("stipendiya" OR "grant")',
    "ka": '("მაგისტრატურა" OR "სამაგისტრო") ("სტიპენდია" OR "გრანტი")',
    "hy": '("մագիստրատուրա" OR "մագիստրոս") ("կրթաթոշակ" OR "դրամաշնորհ")',
    "zh": '("硕士" OR "研究生") ("奖学金" OR "资助" OR "免学费")',
    "ja": '("修士" OR "大学院") ("奨学金" OR "授業料免除")',
    "ko": '("석사" OR "대학원") ("장학금" OR "등록금 면제")',
    "ar": '("ماجستير" OR "دراسات عليا") ("منحة" OR "منح دراسية" OR "إعفاء")',
    "id": '("magister" OR "pascasarjana" OR "S2") ("beasiswa" OR "pembebasan biaya")',
    "ms": '("sarjana" OR "pascasiswazah" OR "master") ("biasiswa" OR "geran")',
    "vi": '("thạc sĩ" OR "cao học") ("học bổng" OR "miễn học phí")',
    "hi": '("स्नातकोत्तर" OR "मास्टर") ("छात्रवृत्ति" OR "फेलोशिप")',
    "ur": '("ماسٹرز" OR "پوسٹ گریجویٹ") ("اسکالرشپ" OR "وظیفہ")',
    "hu": '("mesterképzés" OR "MA" OR "MSc") ("ösztöndíj" OR "tandíjmentesség")',
    "pl": '("studia magisterskie" OR "studia II stopnia") ("stypendium" OR "zwolnienie z opłat")',
    "cs": '("magisterské" OR "navazující") ("stipendium" OR "prominutí")',
    "sk": '("magisterské" OR "inžinierske") ("štipendium" OR "odpustenie")',
    "ro": '("master" OR "masterat") ("bursă" OR "burse" OR "scutire de taxă")',
    "bg": '("магистър" OR "магистратура") ("стипендия" OR "стипендии")',
    "el": '("μεταπτυχιακό" OR "ΠΜΣ") ("υποτροφία" OR "υποτροφίες" OR "απαλλαγή")',
    "sr": '("мастер" OR "master") ("стипендија" OR "stipendija")',
    "hr": '("diplomski" OR "master") ("stipendija" OR "stipendije")',
    "sl": '("magistrski" OR "master") ("štipendija" OR "štipendije")',
    "sv": '("master" OR "magister") ("stipendium" OR "stipendier")',
    "da": '("kandidat" OR "master") ("stipendium" OR "friplads" OR "legat")',
    "no": '("master" OR "mastergrad") ("stipend" OR "legat")',
    "fi": '("maisteri" OR "maisteriohjelma") ("apuraha" OR "stipendi")',
    "et": '("magistriõpe" OR "magister") ("stipendium" OR "õppeteenustasu vabastus")',
    "lv": '("maģistrs" OR "maģistrantūra") ("stipendija" OR "studiju maksas atlaide")',
    "lt": '("magistrantūra" OR "magistras") ("stipendija" OR "atleidimas nuo įmokos")',
    "is": '("meistaranám" OR "MS") ("styrkur" OR "námsstyrkur")',
}


_CCTLD_TO_COUNTRY: dict[str, str] = {
    "ae": "AE",
    "at": "AT",
    "au": "AU",
    "az": "AZ",
    "be": "BE",
    "bg": "BG",
    "bh": "BH",
    "bn": "BN",
    "by": "BY",
    "ca": "CA",
    "ch": "CH",
    "cn": "CN",
    "cy": "CY",
    "cz": "CZ",
    "de": "DE",
    "dk": "DK",
    "edu": "US",
    "ee": "EE",
    "es": "ES",
    "fi": "FI",
    "fr": "FR",
    "ge": "GE",
    "gr": "GR",
    "hr": "HR",
    "hu": "HU",
    "id": "ID",
    "ie": "IE",
    "in": "IN",
    "is": "IS",
    "it": "IT",
    "jp": "JP",
    "kr": "KR",
    "kw": "KW",
    "kz": "KZ",
    "lt": "LT",
    "lu": "LU",
    "lv": "LV",
    "mt": "MT",
    "my": "MY",
    "nl": "NL",
    "no": "NO",
    "nz": "NZ",
    "pk": "PK",
    "pl": "PL",
    "pt": "PT",
    "qa": "QA",
    "ro": "RO",
    "rs": "RS",
    "ru": "RU",
    "sa": "SA",
    "se": "SE",
    "sg": "SG",
    "si": "SI",
    "sk": "SK",
    "tr": "TR",
    "ua": "UA",
    "uk": "GB",
    "us": "US",
    "uz": "UZ",
    "vn": "VN",
}


def _infer_country_from_domain(domain: str, country_code: str = "") -> str:
    """Resolve explicit `country_code` or infer from a domain's ccTLD (`.edu.cn` -> `CN`)."""
    cc = country_code.strip().upper()
    if cc:
        return cc
    parts = [p for p in domain.strip().lower().strip(".").split(".") if p]
    if parts:
        return _CCTLD_TO_COUNTRY.get(parts[-1], "")
    return ""


def build_university_funding_queries(
    domain: str,
    field: str = "",
    country_code: str = "",
) -> tuple[str, ...]:
    """Build field-scoped `site:<domain>` queries to discover departmental/subdomain
    Master's scholarships and tuition waivers across any university domain.

    Covers subdomains like `csc-gradschool.unistra.fr` under `unistra.fr` or
    `chimica.unipd.it` under `unipd.it` without needing sitemap enumeration first.
    """
    clean_domain = domain.strip().lower().strip(".")
    if not clean_domain:
        return ()

    if field.strip():
        resolution = resolve_field_taxonomy(field)
        titles = list(dict.fromkeys(resolution.canonical_degree_titles))[:4]
        field_clause = " OR ".join(f'"{t}"' for t in titles)
        en_query = (
            f"site:{clean_domain} ({field_clause}) "
            '("master" OR "MSc") ("scholarship" OR "tuition waiver" OR "fellowship" OR "grant")'
        )
    else:
        en_query = (
            f'site:{clean_domain} ("master" OR "MSc") '
            '("scholarship" OR "tuition waiver" OR "fellowship" OR "grant")'
        )

    queries: list[str] = [en_query]
    effective_cc = _infer_country_from_domain(clean_domain, country_code)
    steering = STEERING.get(effective_cc)
    if steering is not None and steering.language != "en":
        local_terms = _LOCAL_FUNDING_TERMS_BY_LANG.get(steering.language)
        if local_terms:
            if field.strip():
                local_field = localized_field_terms(field, steering.language)[:3]
                combined_titles = list(dict.fromkeys([*local_field, *titles[:2]]))[:4]
                local_field_clause = " OR ".join(f'"{t}"' for t in combined_titles)
                queries.append(f"site:{clean_domain} ({local_field_clause}) {local_terms}")
            else:
                queries.append(f"site:{clean_domain} {local_terms}")
    return tuple(dict.fromkeys(queries))


def harvest_tap_seed_urls(
    country_code: str,
    field: str = "",
    *,
    fetch_html: Callable[[str], bytes] | None = None,
) -> tuple[str, ...]:
    """Harvest curated closed-list (`funded_excellence_graduate_schools`,
    `regional_and_statutory_master_aid`, `cofunded_and_foundation_scholarships`) and
    hopped national-database URLs for `country_code` + `field` as `run_tap` Stage 2 seeds."""
    from .closed_lists import LISTS_DIR, REGISTRY, read_list_file, read_registry
    from .national_databases import query_national_databases

    cc = country_code.strip().upper()
    urls: list[str] = []
    registry_specs = {str(s["slug"]): s for s in read_registry(REGISTRY)}
    for slug in (
        "funded_excellence_graduate_schools",
        "regional_and_statutory_master_aid",
        "cofunded_and_foundation_scholarships",
    ):
        spec_dict = registry_specs.get(slug)
        if spec_dict is None:
            continue
        spec = ClosedList(**spec_dict)
        for row in read_list_file(spec, LISTS_DIR / f"{slug}.csv"):
            if cc and row.country_code not in (cc, "EU"):
                continue
            target_url = (row.page_url or row.website).strip()
            if target_url and target_url not in urls:
                urls.append(target_url)

    if fetch_html is not None and cc:
        for lead in query_national_databases(cc, field=field, fetch_html=fetch_html):
            if lead.canonical_url and lead.canonical_url not in urls:
                urls.append(lead.canonical_url)

    return tuple(urls)


class CardHostReader:
    """`HostReader` over `card_funding.entry.read_page` and `card_funding.store.write_card`.

    Reads one new domain found by Stage 1 of the Search Tap, bounded by `max_usd`
    (capped at `PAGE_BUDGET_USD`), and persists any servable awards onto a
    matching `Program` on that domain (for programme-attached / university
    scholarships) or onto the domain's `Organisation`. Returns `None` when the
    reader stack keys or the funder level check are not configured, so the tap
    records `STAGE2_UNAVAILABLE` honestly rather than crashing.
    """

    accepts_seed_urls: bool = True

    def __init__(
        self,
        read_card_fn: Callable[[Organisation, str, float], Card] | None = None,
        *,
        site_search: Callable[[str, str], Sequence[str]] | None = None,
        fetch_html: Callable[[str], bytes | str | None] | None = None,
        field: str = "",
    ) -> None:
        self.read_card_fn = read_card_fn
        self.site_search = site_search
        self.fetch_html = fetch_html
        self.field = field

    def read(
        self,
        domain: str,
        *,
        max_usd: Decimal,
        seed_urls: Sequence[str] = (),
    ) -> HostRead | None:
        if not settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE:
            logger.warning(
                "host read %s: funder level check not live (card reader slice 3)", domain
            )
            return None
        if max_usd <= Decimal("0"):
            return None
        if self.read_card_fn is None:
            try:
                require_keys(stack())
            except (ReadersNotConfigured, StackMisconfigured) as error:
                logger.warning("host read %s: reader stack not configured (%s)", domain, error)
                return None

        now = timezone.now()
        owner_row = (
            OrganisationDomain.objects.filter(registrable_domain=domain)
            .select_related("organisation")
            .first()
        )
        if owner_row is not None:
            org = owner_row.organisation
        else:
            org = record_organisation(
                domain=domain,
                name=domain,
                kind="UNSTATED",
                country_code="",
                status=Organisation.Status.CANDIDATE,
                found_via="TAP:stage2",
            )

        org_domains = set(
            OrganisationDomain.objects.filter(organisation=org).values_list(
                "registrable_domain", flat=True
            )
        ) | {domain}
        domain_q = Q(origin_domain__in=org_domains) | Q(evidence_domain__in=org_domains)
        for d in org_domains:
            domain_q |= Q(institution__official_website__icontains=d)
        programs_on_domain = list(
            Program.objects.filter(domain_q, degree_level="MASTER").select_related("institution")
        )

        discovered_seeds = self._discover_seed_urls(
            domain, org, programs_on_domain, seed_urls
        )

        root_url = f"https://{domain}/"
        seed_set = set(discovered_seeds)
        candidate_urls = list(dict.fromkeys(discovered_seeds + [root_url]))
        remaining_usd = max_usd
        total_cost = Decimal("0")
        total_served = 0
        last_outcome = "empty"
        any_written = False

        for url in candidate_urls:
            if remaining_usd <= Decimal("0"):
                break
            if url not in seed_set and total_served > 0:
                break
            budget = float(min(remaining_usd, Decimal(str(PAGE_BUDGET_USD))))
            if self.read_card_fn is not None:
                card = self.read_card_fn(org, url, budget)
            else:
                seed_program = programs_on_domain[0] if programs_on_domain else Program(
                    id=uuid4(), country_code=org.country_code or ""
                )
                card = read_page(
                    seed_program,
                    url,
                    limit=run_limit(uuid4()),
                    funder_country=org.country_code or seed_program.country_code or "",
                    budget_usd=budget,
                )

            cost_dec = Decimal(str(card.cost_usd))
            total_cost += cost_dec
            remaining_usd -= cost_dec
            last_outcome = card.outcome
            if card.outcome != "read":
                continue

            source_url = card.source_url or url
            matched_programs = _match_programs_on_domain(
                programs_on_domain, url=source_url, card=card
            )
            written = self._persist_card(
                card,
                domain=domain,
                source_url=source_url,
                org=org,
                programs_on_domain=programs_on_domain,
                matched_programs=matched_programs,
                now=now,
            )
            self._backfill_tuition_costs(
                matched_programs or programs_on_domain, source_url, now=now
            )

            if written:
                any_written = True
            served_here = sum(1 for opp in written if opp.served)
            total_served += served_here
            if served_here > 0 and url not in seed_set:
                break

        updates: dict[str, object] = {"last_verified": now}
        if any_written:
            updates["funds_students"] = True
        Organisation.objects.filter(pk=org.pk).update(**updates)
        if total_served > 0:
            return HostRead(cost_usd=total_cost, awards_served=total_served, outcome="found")
        if last_outcome != "read":
            return HostRead(cost_usd=total_cost, awards_served=0, outcome=last_outcome)
        return HostRead(cost_usd=total_cost, awards_served=0, outcome="empty")

    def _discover_seed_urls(
        self,
        domain: str,
        org: Organisation,
        programs_on_domain: Sequence[Program],
        seed_urls: Sequence[str],
    ) -> list[str]:
        discovered = [u.strip() for u in seed_urls if u and u.strip()]
        if discovered or self.site_search is None:
            return discovered
        country_hint = _infer_country_from_domain(
            domain,
            org.country_code
            or (programs_on_domain[0].country_code if programs_on_domain else ""),
        )
        for q in build_university_funding_queries(
            domain, field=self.field, country_code=country_hint
        ):
            try:
                hits = self.site_search(q, domain)
            except Exception as exc:
                logger.warning("site_search failed on %s (%s): %s", domain, q, exc)
                continue
            for hit in hits:
                if hit and hit.strip() and hit.strip() not in discovered:
                    discovered.append(hit.strip())
        return discovered

    @staticmethod
    def _persist_card(
        card: Card,
        *,
        domain: str,
        source_url: str,
        org: Organisation,
        programs_on_domain: Sequence[Program],
        matched_programs: Sequence[Program],
        now: Any,
    ) -> Sequence[Any]:
        source, _ = OfficialSource.objects.get_or_create(
            canonical_url=source_url,
            defaults={
                "publisher": domain,
                "source_type": OfficialSource.Type.FUNDER,
            },
        )
        snapshot = (
            OfficialSourceSnapshot.objects.filter(source=source)
            .order_by("-retrieved_at")
            .first()
        )
        if snapshot is None:
            url_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
            snapshot = OfficialSourceSnapshot.objects.create(
                source=source,
                s3_key=f"official-sources/tap/{domain}/{url_hash[:16]}",
                s3_version_id="1",
                sha256=url_hash,
                final_url=source_url,
                redirect_chain=[],
                retrieved_at=now,
                admissions_cycle=cycle_label(now),
                content_type="text/html",
                byte_size=1,
                discovery_technique="tap_stage2",
            )
        first_inst = next(
            (p.institution for p in programs_on_domain if p.institution is not None),
            None,
        )
        target_programs = matched_programs or (
            programs_on_domain if first_inst is None else ()
        )
        if target_programs:
            written = write_card(
                card,
                program=target_programs[0],
                source=source,
                snapshot=snapshot,
                now=now,
            )
            for extra_prog in target_programs[1:]:
                for opp in written:
                    if opp.scope_type == "PROGRAM":
                        FundingOpportunityProgram.objects.get_or_create(
                            opportunity=opp, program=extra_prog
                        )
            return written
        if first_inst is not None:
            return write_card(
                card, institution=first_inst, source=source, snapshot=snapshot, now=now
            )
        return write_card(
            card, organisation=org, source=source, snapshot=snapshot, now=now
        )

    def _backfill_tuition_costs(
        self, programs: Sequence[Program], source_url: str, *, now: Any
    ) -> None:
        if self.fetch_html is None:
            return
        from apps.funding.models import CostComponent

        from .programme_scraper import scrape_programme_pages

        for prog in programs:
            if CostComponent.objects.filter(
                program=prog, kind=CostComponent.Kind.TUITION
            ).exists():
                continue
            try:
                prog_html = self.fetch_html(source_url)
            except Exception as exc:
                logger.warning(
                    "fetch_html failed for programme scrape on %s: %s", source_url, exc
                )
                continue
            if prog_html:
                scrape_programme_pages(
                    prog,
                    source_url,
                    prog_html,
                    fetch_fn=self.fetch_html,
                    stage="gate_and_money",
                    now=now,
                )

