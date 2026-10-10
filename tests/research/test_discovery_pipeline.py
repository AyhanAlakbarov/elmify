import re
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.funding.models import (
    FundingOpportunity,
    Institution,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramAwardingInstitution,
)
from apps.research import pipeline as pipeline_module
from apps.research.discovery import DiscoveryQuery, LeadIdentity, ResearchLead, RunBudget
from apps.research.egress import FetchResult, SourceBlocked
from apps.research.extraction import (
    ExtractedClaims,
    ExtractionError,
    ExtractionFailure,
    ExtractionResult,
    KeyDateClaim,
    ModelMetadata,
    TeachingLanguageClaim,
)
from apps.research.fetch import SweepBudget
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.models import (
    ConsultantResearchTask,
    DomainLease,
    ResolutionItem,
)
from apps.research.pipeline import PacedFetch, default_sources, run_discovery
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

QUERY = DiscoveryQuery(field="robotics", country_code="DE", max_leads=5)
DETAIL_PAGE = b"""<html><body>
<a class="visitCourseWebsite" href="https://direc.to/ozyQ">Course website</a></body></html>"""
OFFICIAL_PAGE = b"<html><body><h1>AI &amp; Robotics</h1><p>Taught in English.</p></body></html>"

IDENTITY = LeadIdentity(
    institution_name="University of Technology Nuremberg",
    country_code="DE",
    city="Nürnberg",
    program_name="AI & Robotics (MSc)",
)
CLAIMS = ExtractedClaims(
    duration_months=24,
    deadline=date(2027, 5, 31),
    teaching_languages=(
        TeachingLanguageClaim(language="English", evidence="Taught entirely in English."),
    ),
    confidence=0.9,
)


class StaticSource:
    name = "seed:daad-ip"
    one_programme_per_link = False
    awards_jointly = False

    def __init__(self, *leads: ResearchLead) -> None:
        self._leads = leads

    def find(self, query: DiscoveryQuery) -> list[ResearchLead]:
        return list(self._leads)


def _catalogue_lead() -> ResearchLead:
    return ResearchLead.from_url(
        "https://www2.daad.de/detail/9894/",
        source_type="AGGREGATOR",
        funding_family="",
        identity=IDENTITY,
    )


def _pages(mapping: dict[str, tuple[str, bytes]]):
    """prefix -> (final_url, body). Models the redirect the hop relies on."""

    def fetch(url: str, **_kwargs: object) -> FetchResult:
        for prefix, (final_url, body) in mapping.items():
            if url.startswith(prefix):
                return FetchResult(final_url, (), "text/html", body)
        raise SourceBlocked(f"source returned HTTP 404: {url}")

    return fetch


def _paced(fetch, **overrides):
    return PacedFetch(
        actor_id=uuid4(),
        budget=overrides.pop("budget", RunBudget()),
        interval=timedelta(seconds=0),
        sleep=lambda _seconds: None,
        fetch=fetch,
        **overrides,
    )


def _extract(_snapshot: object, _client: object = None) -> ExtractionResult:
    return ExtractionResult(
        claims=CLAIMS,
        metadata=ModelMetadata(model_id="test", schema_version=2, response_id=None, usage={}),
    )


DAAD_TO_UTN = {
    "https://www2.daad.de/": ("https://www2.daad.de/detail/9894", DETAIL_PAGE),
    "https://direc.to/": (
        "https://www.utn.de/en/study/ai-robotics-en/?utm_source=daad",
        OFFICIAL_PAGE,
    ),
}


def test_the_hop_follows_the_redirect_and_claims_from_where_it_landed(
    agency_a, fake_store
) -> None:
    cache.clear()
    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(_catalogue_lead())],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(DAAD_TO_UTN)),
            extract=_extract,
        )

    assert report.written == 1
    assert Institution.objects.count() == 1
    assert Program.objects.get().name == "AI & Robotics (MSc)"
    claim = OfficialEvidenceClaim.objects.first()
    assert claim is not None
    # Sourced to the university, tracking parameters stripped, never to DAAD.
    assert claim.source.canonical_url == "https://www.utn.de/en/study/ai-robotics-en"
    assert claim.snapshot is not None
    assert claim.snapshot.discovery_technique == "seed:daad-ip"


def test_a_hop_that_lands_on_another_catalogue_is_blocked_not_promoted(
    agency_a, fake_store
) -> None:
    cache.clear()
    pages = {
        "https://www2.daad.de/": ("https://www2.daad.de/detail/9894", DETAIL_PAGE),
        "https://direc.to/": ("https://www.mastersportal.com/studies/1", OFFICIAL_PAGE),
    }

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(_catalogue_lead())],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(pages)),
            extract=_extract,
        )

    assert report.written == 0
    assert report.blocked == 1
    assert OfficialEvidenceClaim.objects.count() == 0


def test_a_direct_leads_redirect_onto_a_catalogue_host_is_blocked_not_written(
    agency_a, fake_store
) -> None:
    """Whole-branch Fix 3: the catalogue guard must reapply after EVERY fetch.

    The vendor fetch follows redirects too. A PROGRAM lead's URL can
    301 onto a catalogue host just as easily as a hop's click-tracker can --
    and lead.can_support_claim was computed from the pre-redirect host, so
    without re-deriving the lead from page.final_url a claim would get
    written citing the aggregator.
    """
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    pages = {
        "https://www.utn.de/": ("https://www.mastersportal.com/studies/1", OFFICIAL_PAGE),
    }

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(pages)),
            extract=_extract,
        )

    assert report.written == 0
    assert report.blocked == 1
    assert OfficialEvidenceClaim.objects.count() == 0


def test_every_lead_on_one_host_is_fetched_rather_than_skipped(
    agency_a, fake_store, monkeypatch
) -> None:
    """The lease paces the run; it must not truncate it.

    `acquire_domain_lease` (apps/research/services.py) sets
    ``available_at = timezone.now() + interval`` and raises `DomainBusy` while
    that stays in the future. A `sleep` stub that only records elapsed time
    without moving the clock the lease reads would never free the lease, so
    the clock `acquire_domain_lease` reads is monkeypatched to a mutable fake
    that `sleep` itself advances -- proving the retry loop actually waits out
    the lease rather than the test being unable to reach that branch at all.
    """
    cache.clear()
    leads = [
        ResearchLead.from_url(
            f"https://www.utn.de/en/study/{index}",
            source_type="PROGRAM",
            funding_family="",
            identity=IDENTITY,
        )
        for index in range(3)
    ]

    clock = timezone.now()

    def fake_now():
        return clock

    monkeypatch.setattr("apps.research.services.timezone.now", fake_now)

    slept: list[float] = []

    def sleep(seconds: float) -> None:
        nonlocal clock
        slept.append(seconds)
        clock += timedelta(seconds=seconds)

    paced = PacedFetch(
        actor_id=uuid4(),
        budget=RunBudget(),
        interval=timedelta(seconds=5),
        sleep=sleep,
        fetch=_pages({"https://www.utn.de/": ("https://www.utn.de/en/study/x", OFFICIAL_PAGE)}),
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(*leads)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=paced,
            extract=_extract,
        )

    assert report.leads == 3
    assert report.blocked == 0
    assert slept, "the second lead on the same host must wait for the lease, not be dropped"
    assert DomainLease.objects.get(domain="www.utn.de")


def test_an_unchanged_page_revalidates_instead_of_duplicating(agency_a, fake_store) -> None:
    """§7.1: a re-fetch of a byte-identical page is a revalidation.

    Without this the second run raises IntegrityError on
    snapshot_source_sha256_uniq and aborts the whole discovery run.
    """
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    fetch = _paced(
        _pages({"https://www.utn.de/": ("https://www.utn.de/en/study/ai", OFFICIAL_PAGE)})
    )
    kwargs = dict(
        tenant_id=agency_a.id,
        store=fake_store,
        admissions_cycle="2027",
        fetch=fetch,
        extract=_extract,
    )

    with tenant_scope(agency_a.id):
        first = run_discovery(QUERY, [StaticSource(lead)], **kwargs)
        before = list(
            OfficialEvidenceClaim.objects.values_list("last_checked_at", flat=True)
        )
        second = run_discovery(QUERY, [StaticSource(lead)], **kwargs)

    assert first.written == 1
    assert second.written == 0
    assert second.unchanged == 1
    assert OfficialSourceSnapshot.objects.count() == 1
    after = list(OfficialEvidenceClaim.objects.values_list("last_checked_at", flat=True))
    assert len(after) == len(before)
    assert min(after) >= min(before)


def test_a_failed_extraction_does_not_permanently_brick_the_url(agency_a, fake_store) -> None:
    """Whole-branch Fix 1: a snapshot with zero claims must not read as 'seen'.

    persist_snapshot writes the snapshot row before extraction is attempted.
    If extraction then fails, that snapshot has zero claims. Without the
    claims check in run_discovery's `seen` guard, a SECOND run over the same
    byte-identical page would match on sha256, `touch_claims` zero rows, and
    report `unchanged` forever -- the page is never extracted again.
    """
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    fetch = _paced(
        _pages({"https://www.utn.de/": ("https://www.utn.de/en/study/ai", OFFICIAL_PAGE)})
    )
    calls = {"count": 0}

    def flaky_extract(snapshot: object, client: object = None) -> ExtractionResult:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ExtractionError("simulated 429")
        return _extract(snapshot, client)

    kwargs = dict(
        tenant_id=agency_a.id,
        store=fake_store,
        admissions_cycle="2027",
        fetch=fetch,
        extract=flaky_extract,
    )

    with tenant_scope(agency_a.id):
        first = run_discovery(QUERY, [StaticSource(lead)], **kwargs)
        assert first.written == 0
        assert first.blocked == 1
        assert OfficialSourceSnapshot.objects.count() == 1
        assert OfficialEvidenceClaim.objects.count() == 0

        second = run_discovery(QUERY, [StaticSource(lead)], **kwargs)

    assert second.written == 1
    assert second.unchanged == 0
    # The retried extraction reused the existing snapshot row rather than
    # duplicating it -- (source, sha256) is unique.
    assert OfficialSourceSnapshot.objects.count() == 1
    assert OfficialEvidenceClaim.objects.count() > 0


def test_a_failed_extraction_task_names_the_cause_not_only_the_wrapper(
    agency_a, fake_store
) -> None:
    """2026-08-30: every page recorded "extraction failed: ExtractionFailure".

    The cause was one schema defect answering HTTP 400 on every call, read as
    N page-specific failures because the task kept only the wrapper's name.
    """
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    fetch = _paced(
        _pages({"https://www.utn.de/": ("https://www.utn.de/en/study/ai", OFFICIAL_PAGE)})
    )

    class BadRequestError(Exception):
        status_code = 400

    def failing_extract(snapshot: object, client: object = None) -> ExtractionResult:
        try:
            raise BadRequestError("Invalid JSON schema: regex lookaround is not supported")
        except BadRequestError as error:
            raise ExtractionFailure("structured extraction call failed") from error

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=fetch,
            extract=failing_extract,
        )

    assert report.blocked == 1
    # Our defect, not a question an operator can answer: the run's report,
    # never a consultant task or a queue item (plan Task 9).
    assert (
        "https://www.utn.de/en/study/ai: "
        "extraction failed: ExtractionFailure <- BadRequestError (HTTP 400)"
    ) in report.degraded
    assert ConsultantResearchTask._base_manager.count() == 0
    assert not ResolutionItem.objects.exists()


def test_a_catalogue_page_with_no_official_link_is_reported_not_queued(
    agency_a, fake_store
) -> None:
    """An aggregator is fetched for names only (spec 6.4). A name without a
    site is the resolver's question, filed as SITE_UNKNOWN from its residue --
    not a task per catalogue page."""
    cache.clear()
    pages = {"https://www2.daad.de/": ("https://www2.daad.de/detail/9894", b"<html>no link</html>")}

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(_catalogue_lead())],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(pages)),
            extract=_extract,
        )

    assert report.blocked == 1
    assert report.written == 0
    assert "https://www2.daad.de/detail/9894: no official programme link" in report.degraded
    assert ConsultantResearchTask._base_manager.count() == 0
    assert not ResolutionItem.objects.exists()


def test_a_source_refused_for_another_reason_is_reported_not_queued(
    agency_a, fake_store
) -> None:
    """A 404 is a known answer, not a question: `_pages` raises a bare
    SourceBlocked (no ladder outcome), which is degraded, never filed."""
    cache.clear()
    lead = ResearchLead.from_url(
        "https://blocked.example/program", source_type="PROGRAM", funding_family=""
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages({})),
            extract=_extract,
        )

    assert report.blocked == 1
    assert any(
        note.startswith("https://blocked.example/program: ") for note in report.degraded
    )
    assert ConsultantResearchTask._base_manager.count() == 0
    assert not ResolutionItem.objects.exists()


def _refusing(outcome: str):
    """A fetch that refuses every URL the way retrieve_official_source does:
    a SourceBlocked carrying the ladder's outcome."""

    def fetch(url: str, **_kwargs: object) -> FetchResult:
        raise SourceBlocked(f"{outcome}: origin_403", outcome=outcome)

    return fetch


def _run_one(tenant_id, fake_store, fetch, url="https://www.Blocked.example/program", **kw):
    lead = ResearchLead.from_url(url, source_type="PROGRAM", funding_family="")
    with tenant_scope(tenant_id):
        return run_discovery(
            QUERY, [StaticSource(lead)], tenant_id=tenant_id, store=fake_store,
            admissions_cycle="2027", fetch=_paced(fetch), extract=_extract, **kw,
        )


@pytest.mark.parametrize("outcome", ["BLOCKED", "UNREACHABLE", "UNREADABLE"])
def test_a_host_the_ladder_could_not_open_files_one_host_unreachable_item(
    agency_a, fake_store, outcome
) -> None:
    """UNREADABLE is the ladder's own "rendered and still a shell"
    (firecrawl.py REASON_SHELL, scrapedo.py "shell") -- the same question as
    the pipeline's empty-shell branch below, so it files too."""
    cache.clear()
    report = _run_one(agency_a.id, fake_store, _refusing(outcome))

    assert report.blocked == 1
    item = ResolutionItem.objects.get()
    assert item.kind == "HOST_UNREACHABLE"
    assert item.subject_key == "host:www.blocked.example"
    assert item.evidence["url"] == "https://www.blocked.example/program"
    assert item.evidence["why"] == f"{outcome}: origin_403"
    assert ConsultantResearchTask._base_manager.count() == 0
    # Filed, so not ALSO in the report: degraded is for what nobody is asked.
    assert not any("blocked.example" in note for note in report.degraded)


@pytest.mark.parametrize(
    "outcome", ["DEAD", "OFF_SITE", "INVALID", "RETRY_SCHEDULED", "UNCHANGED", "BUDGET"]
)
def test_every_other_ladder_refusal_is_reported_not_queued(
    agency_a, fake_store, outcome
) -> None:
    cache.clear()
    report = _run_one(agency_a.id, fake_store, _refusing(outcome))

    assert report.blocked == 1
    assert (
        f"https://www.blocked.example/program: {outcome}: origin_403" in report.degraded
    )
    assert not ResolutionItem.objects.exists()
    assert ConsultantResearchTask._base_manager.count() == 0


def test_two_tenants_meeting_one_blocked_host_make_one_item(
    agency_a, agency_b, fake_store
) -> None:
    """The dedupe spec 11 exists for: one question per host, whichever
    agencies' runs met it, and no tenant anywhere on the row."""
    cache.clear()
    _run_one(agency_a.id, fake_store, _refusing("BLOCKED"))
    cache.clear()
    _run_one(
        agency_b.id, fake_store, _refusing("UNREACHABLE"),
        url="https://www.blocked.example/fees",
    )

    item = ResolutionItem.objects.get()
    assert item.subject_key == "host:www.blocked.example"
    assert item.evidence["url"] == "https://www.blocked.example/fees"
    assert ConsultantResearchTask._base_manager.count() == 0


def test_a_host_that_opens_again_withdraws_its_open_item(agency_a, fake_store) -> None:
    cache.clear()
    _run_one(agency_a.id, fake_store, _refusing("BLOCKED"))
    assert ResolutionItem.objects.count() == 1

    cache.clear()
    url = "https://www.blocked.example/program"
    _run_one(agency_a.id, fake_store, _pages({url: (url, OFFICIAL_PAGE)}), url=url)

    # Withdrawn on the fetch, whatever the page then yields: the question was
    # "can this host be opened", and it just was.
    assert not ResolutionItem.objects.exists()


def test_a_decided_item_is_not_withdrawn_by_a_later_fetch(agency_a, fake_store) -> None:
    """A person's answer is the applier's to apply or refuse, never dropped."""
    cache.clear()
    _run_one(agency_a.id, fake_store, _refusing("BLOCKED"))
    ResolutionItem.objects.update(
        state="DECIDED", resolution={"option": "closed", "url": ""}, decided_at=timezone.now()
    )

    cache.clear()
    url = "https://www.blocked.example/program"
    _run_one(agency_a.id, fake_store, _pages({url: (url, OFFICIAL_PAGE)}), url=url)

    assert ResolutionItem.objects.get().state == "DECIDED"


def test_a_dry_run_touches_neither_the_network_nor_the_database(agency_a, fake_store) -> None:
    cache.clear()
    fetched: list[str] = []

    def fetch(url: str, **_kwargs: object) -> FetchResult:
        fetched.append(url)
        return FetchResult(url, (), "text/html", OFFICIAL_PAGE)

    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(fetch),
            extract=_extract,
            dry_run=True,
        )

    assert report.leads == 1
    assert report.written == 0
    assert fetched == []
    assert Program.objects.count() == 0


def test_an_exhausted_budget_ends_the_run_with_what_it_already_wrote(
    agency_a, fake_store
) -> None:
    """Degrade, do not crash (§2.6). The report says which budget ran out."""
    cache.clear()
    leads = [
        ResearchLead.from_url(
            f"https://www.utn.de/en/study/{index}",
            source_type="PROGRAM",
            funding_family="",
            identity=IDENTITY,
        )
        for index in range(3)
    ]
    fetch = _paced(
        _pages({"https://www.utn.de/": ("https://www.utn.de/en/study/x", OFFICIAL_PAGE)}),
        budget=RunBudget(fetches=1, extractions=5),
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(*leads)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=fetch,
            extract=_extract,
        )

    assert report.written == 1
    assert "fetches" in " ".join(report.degraded)


def test_the_search_sources_are_omitted_when_no_provider_key_is_configured() -> None:
    common = dict(fetch=_paced(_pages({})), budget=RunBudget(), actor_id=uuid4())

    # No DAAD adapter exists (access-terms review, see apps/research/seeds.py's
    # module docstring): only the EACEA seed ships without a provider key.
    assert [source.name for source in default_sources(api_key="", **common)] == [
        "seed:eacea",
    ]
    # With a key, search supplies ORGANISATIONS to entity expansion and is never a
    # source in its own right. The 2026-08-28 funding-led design puts SearchSource at
    # tier 0 as an optional organisation supplier whose leads are ECOSYSTEM_CLUE;
    # wired standalone it emitted PROGRAM/DIRECT leads straight from open-web results.
    # A live run on 2026-08-30 returned eight content farms out of ten, every one
    # marked can_support_claim=True. Provenance comes from where a lead was found, and
    # an open-web result was found nowhere in particular.
    assert [source.name for source in default_sources(api_key="k", **common)] == [
        "seed:eacea",
        "entity-expansion",
    ]


# --- rendered fallback --------------------------------------------------------

SHELL_PAGE = b"<html><head><style>" + b"x{a:b}" * 4000 + b"</style></head><body>" + (
    b'<div class="ecl" data-drupal="1"></div>' * 900
) + b"</body></html>"


def test_a_javascript_shell_is_rendered_rather_than_recorded_as_useless(
    agency_a, fake_store
) -> None:
    """The EACEA case, end to end.

    Plain retrieval returns markup with nothing in it. Without the render step
    this becomes a consultant task and the programme is lost; with it, the same
    URL yields a real page and a catalog row.
    """
    cache.clear()
    rendered: list[str] = []

    def render(url: str) -> FetchResult:
        rendered.append(url)
        return FetchResult(url, (), "text/html", OFFICIAL_PAGE)

    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    paced = _paced(_pages({"https://www.utn.de/": ("https://www.utn.de/en/study/ai", SHELL_PAGE)}))

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=paced,
            extract=_extract,
            render=render,
        )

    assert rendered == ["https://www.utn.de/en/study/ai"], "the landed URL is what gets rendered"
    assert report.written == 1
    assert report.blocked == 0


def test_without_a_renderer_a_shell_becomes_a_queue_item_not_a_silent_drop(
    agency_a, fake_store
) -> None:
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    paced = _paced(_pages({"https://www.utn.de/": ("https://www.utn.de/en/study/ai", SHELL_PAGE)}))

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=paced,
            extract=_extract,
        )

    assert report.written == 0
    assert report.blocked == 1
    item = ResolutionItem.objects.get()
    assert item.subject_key == "host:www.utn.de"
    assert item.evidence["url"] == "https://www.utn.de/en/study/ai"
    why = item.evidence["why"].lower()
    # Not "browser": the browser tier was deleted on this branch, and the
    # vendors render already, so a question naming one sends an operator to
    # start something that no longer exists.
    assert "rendered" in why and "shell" in why
    assert "browser" not in why
    assert ConsultantResearchTask._base_manager.count() == 0


def test_a_failing_renderer_degrades_rather_than_killing_the_run(
    agency_a, fake_store
) -> None:
    cache.clear()

    def render(url: str) -> FetchResult:
        raise SourceBlocked("renderer crashed")

    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    paced = _paced(_pages({"https://www.utn.de/": ("https://www.utn.de/en/study/ai", SHELL_PAGE)}))

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=paced,
            extract=_extract,
            render=render,
        )

    assert report.blocked == 1
    # No ladder outcome on the renderer's refusal, so it is our tier's failure
    # to report, not a host question to file.
    assert "https://www.utn.de/en/study/ai: renderer crashed" in report.degraded
    assert ConsultantResearchTask._base_manager.count() == 0
    assert not ResolutionItem.objects.exists()


def test_a_changed_footer_alone_revalidates_instead_of_re_extracting(
    agency_a, fake_store
) -> None:
    """Different bytes, same page: the expensive step must not run again.

    A "last reviewed" date, a rotating news panel or a session id moves the raw
    digest on a programme page that says exactly what it said last week. Before
    content-region hashing this bought a second snapshot and a second extraction
    every cycle.
    """
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    first_body = (
        b"<html><body><main><h1>AI &amp; Robotics</h1><p>Taught in English.</p></main>"
        b"<footer>Last reviewed 2026-08-01. Session a1b2c3.</footer></body></html>"
    )
    second_body = first_body.replace(b"2026-08-01", b"2026-08-28").replace(b"a1b2c3", b"z9y8x7")
    assert first_body != second_body

    def _kwargs(body: bytes):
        return dict(
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages({"https://www.utn.de/": ("https://www.utn.de/en/study/ai", body)})),
            extract=_extract,
        )

    with tenant_scope(agency_a.id):
        first = run_discovery(QUERY, [StaticSource(lead)], **_kwargs(first_body))
        second = run_discovery(QUERY, [StaticSource(lead)], **_kwargs(second_body))

    assert first.written == 1
    assert second.written == 0
    assert second.unchanged == 1
    assert OfficialSourceSnapshot.objects.count() == 1, "no second snapshot for the same page"


def test_a_changed_content_region_still_writes_a_new_snapshot(agency_a, fake_store) -> None:
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    first_body = b"<html><body><main><p>Tuition is EUR 0 per semester.</p></main></body></html>"
    second_body = first_body.replace(b"EUR 0", b"EUR 1500")

    def _kwargs(body: bytes):
        return dict(
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages({"https://www.utn.de/": ("https://www.utn.de/en/study/ai", body)})),
            extract=_extract,
        )

    with tenant_scope(agency_a.id):
        run_discovery(QUERY, [StaticSource(lead)], **_kwargs(first_body))
        second = run_discovery(QUERY, [StaticSource(lead)], **_kwargs(second_body))

    assert second.written == 1
    assert OfficialSourceSnapshot.objects.count() == 2


FRONT_DOOR = b"""<html><body><h1>WOCC</h1><p>Un master Erasmus Mundus.</p>
<a href="/candidature-et-admission/bourses-detudes">Bourses</a>
<a href="https://www.ucm.es/becas-admission">Partenaire</a>
</body></html>"""
FUNDING_ROOM = b"""<html><body><h1>Bourses</h1>
<p>Taught in English. Scholarships cover the tuition fee.</p>
<a href="/candidature-et-admission/cout-de-la-formation">Cout</a>
</body></html>"""


def test_a_front_door_with_no_funding_hops_to_the_funding_page_on_its_own_host(
    agency_a, fake_store
) -> None:
    """Shadow run 2 §2.2: the catalogue gives a front door, the money is inside."""
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.master-wocc.eu/",
        source_type="PROGRAM",
        funding_family="MULTILATERAL",
        identity=IDENTITY,
    )
    pages = {
        "https://www.master-wocc.eu/candidature-et-admission/bourses-detudes": (
            "https://www.master-wocc.eu/candidature-et-admission/bourses-detudes",
            FUNDING_ROOM,
        ),
        "https://www.master-wocc.eu/": ("https://www.master-wocc.eu/", FRONT_DOOR),
    }
    fetch = _paced(_pages(pages))

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=fetch,
            extract=_extract,
        )

    # Two leads from one: the front door and the funding page one hop inside.
    assert report.leads == 2
    urls = {source.canonical_url for source in OfficialSource.objects.all()}
    assert "https://www.master-wocc.eu/candidature-et-admission/bourses-detudes" in urls
    # The partner university is a different institution's page; it is not hopped
    # to, and neither is the funding page's own onward link -- one host, one hop.
    assert not any("ucm.es" in url for url in urls)
    assert not any("cout-de-la-formation" in url for url in urls)


def test_an_aggregator_lead_is_not_hopped_within_the_catalogue(agency_a, fake_store) -> None:
    """Only a host that can support a claim lends its provenance to a hop."""
    cache.clear()
    catalogue = b"""<html><body>
    <a class="visitCourseWebsite" href="https://direc.to/ozyQ">Course website</a>
    <a href="/en/scholarships/overview">Scholarships</a></body></html>"""
    pages = {
        "https://www2.daad.de/": ("https://www2.daad.de/detail/9894", catalogue),
        "https://direc.to/": ("https://www.utn.de/en/study/ai-robotics-en", OFFICIAL_PAGE),
    }

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(_catalogue_lead())],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(pages)),
            extract=_extract,
        )

    assert report.leads == 1
    assert not OfficialSource.objects.filter(canonical_url__contains="daad.de").exists()


def test_dropped_dates_are_reported_not_swallowed(agency_a, fake_store) -> None:
    """A third of dates vanishing quietly is worse than the bug being fixed."""
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,
    )
    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught entirely in English."),
        ),
        key_dates=(
            KeyDateClaim(
                kind="APPLICATION_DEADLINE",
                on=date(1515, 2, 15),
                evidence="Deadline for Application with Scholarship 15th Feb 2026",
            ),
        ),
        confidence=0.9,
    )

    def extract(_snapshot, _client=None):
        return ExtractionResult(
            claims=claims,
            metadata=ModelMetadata(
                model_id="test", schema_version=2, response_id=None, usage={}
            ),
        )

    pages = {"https://www.utn.de/": ("https://www.utn.de/en/study/ai-robotics-en", OFFICIAL_PAGE)}
    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [StaticSource(lead)],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(pages)),
            extract=extract,
        )

    assert report.written == 1  # the row still lands
    assert any("unreadable" in note for note in report.degraded)


def test_a_hopped_page_does_not_inherit_the_catalogues_identity(
    agency_a, fake_store
) -> None:
    """The catalogue vouched for the front door, not for every page behind it.

    resolve_program prefers seed identity over the extracted claims, so carrying
    it onto a hopped page writes that page's funding facts under the parent's
    institution and programme names -- and a university host serves many
    programmes. Inert for EACEA, whose adapter sets no identity; live the moment
    a seed adapter that does supply one is added, which the DAAD adapter would.
    """
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/",
        source_type="PROGRAM",
        funding_family="",
        identity=IDENTITY,  # "University of Technology Nuremberg" / "AI & Robotics (MSc)"
    )
    front_door = b"""<html><body><h1>UTN</h1>
    <a href="/en/scholarships/overview">Scholarships</a></body></html>"""
    pages = {
        "https://www.utn.de/en/scholarships/overview": (
            "https://www.utn.de/en/scholarships/overview",
            OFFICIAL_PAGE,
        ),
        "https://www.utn.de/": ("https://www.utn.de/", front_door),
    }
    seen: list[ResearchLead] = []

    def extract(snapshot, _client=None):
        return ExtractionResult(
            claims=CLAIMS,
            metadata=ModelMetadata(
                model_id="test", schema_version=2, response_id=None, usage={}
            ),
        )

    original = pipeline_module.write_catalog_entry

    def spy(**kwargs):
        seen.append(kwargs["lead"])
        return original(**kwargs)

    pipeline_module.write_catalog_entry = spy
    try:
        with tenant_scope(agency_a.id):
            run_discovery(
                QUERY,
                [StaticSource(lead)],
                tenant_id=agency_a.id,
                store=fake_store,
                admissions_cycle="2027",
                fetch=_paced(_pages(pages)),
                extract=extract,
            )
    finally:
        pipeline_module.write_catalog_entry = original

    hopped = [row for row in seen if "scholarships" in row.canonical_url]
    assert hopped, "the hop did not happen; the test proves nothing"
    assert hopped[0].identity is None


def test_a_hopped_page_inherits_the_pooling_promise() -> None:
    # The hop drops identity (one host serves many programmes) but keeps the
    # promise: same host, same source, so its pages describe one programme.
    lead = ResearchLead.from_url(
        "https://consortium.eu/",
        source_type="PROGRAM",
        funding_family="MULTILATERAL",
        one_programme_per_site=True,
    )

    hopped = replace(lead, canonical_url="https://consortium.eu/scholarships", identity=None)

    assert hopped.one_programme_per_site is True


CONSORTIUM_FRONT_DOOR = b"<html><body><h1>Coastal Engineering</h1></body></html>"
CONSORTIUM_ADMISSIONS = b"<html><body><p>Two years, taught in English.</p></body></html>"

# More specific prefix first: _pages matches with startswith.
CONSORTIUM = {
    "https://consortium.eu/admissions": (
        "https://consortium.eu/admissions",
        CONSORTIUM_ADMISSIONS,
    ),
    "https://consortium.eu/": ("https://consortium.eu/", CONSORTIUM_FRONT_DOOR),
}


class Consortium(StaticSource):
    name = "seed:eacea"
    one_programme_per_link = True
    awards_jointly = True


def _consortium_leads() -> Consortium:
    return Consortium(
        ResearchLead.from_url(
            "https://consortium.eu/", source_type="PROGRAM", funding_family="MULTILATERAL"
        ),
        ResearchLead.from_url(
            "https://consortium.eu/admissions",
            source_type="PROGRAM",
            funding_family="MULTILATERAL",
        ),
    )


def _split_extract(front: ExtractedClaims, rest: ExtractedClaims):
    """The front door states one thing; the other page states the others."""

    def extract(snapshot: object, _client: object = None) -> ExtractionResult:
        url = snapshot.evidence_metadata["source_url"]  # type: ignore[attr-defined]
        return ExtractionResult(
            claims=front if url.rstrip("/").endswith("consortium.eu") else rest,
            metadata=ModelMetadata(
                model_id="test", schema_version=2, response_id=None, usage={}
            ),
        )

    return extract


def test_two_pages_of_one_programme_write_a_row_neither_could_write_alone(
    agency_a, fake_store
) -> None:
    cache.clear()
    front = ExtractedClaims(confidence=0.9, institution_name="Nordland University")
    rest = ExtractedClaims(
        confidence=0.9,
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [_consortium_leads()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(CONSORTIUM)),
            extract=_split_extract(front, rest),
        )

    # Neither page resolves alone; pooled they do, and both write against one row.
    assert report.written == 2
    assert Program.objects.count() == 1
    assert Program.objects.get().name == "Coastal Engineering"
    # Consortium awards jointly (whole-branch review, Fix 1): no Institution is
    # invented for "Nordland University" here -- that is test_a_jointly_awarded_
    # seed_writes_no_institution's own assertion below.
    assert Institution.objects.count() == 0


def test_pages_that_contradict_a_duration_are_reported_not_guessed(
    agency_a, fake_store
) -> None:
    cache.clear()
    front = ExtractedClaims(
        confidence=0.9, institution_name="Nordland University", duration_months=6
    )
    rest = ExtractedClaims(
        confidence=0.9,
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=36,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [_consortium_leads()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(CONSORTIUM)),
            extract=_split_extract(front, rest),
        )

    assert Program.objects.count() == 0
    assert any("disagreed" in note for note in report.degraded)


def test_pages_that_never_state_an_institution_are_reported_as_incomplete_not_disagreed(
    agency_a, fake_store
) -> None:
    # Pools cleanly -- both pages agree on country and duration -- but neither
    # ever states an institution, which resolve_program still gates on. An
    # absence, not a contradiction: it must not land in the "disagreed" count.
    cache.clear()
    front = ExtractedClaims(confidence=0.9, duration_months=24)
    rest = ExtractedClaims(
        confidence=0.9,
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [_consortium_leads()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(CONSORTIUM)),
            extract=_split_extract(front, rest),
        )

    assert Program.objects.count() == 0
    assert any("never stated" in note for note in report.degraded)
    assert not any("disagreed" in note for note in report.degraded)


# eusmat.net reproduction (whole-branch review, Fix 1): one_programme_per_site is a
# promise about the LINK, but the pool group is per HOST -- so a hop that lands on a
# different degree's own page (FUNDING_PATH_TERMS deliberately includes "phd" and
# "doctoral") must not let that page's facts join the front door's group.
PHD_PAGE_URL = "https://consortium.eu/international-studies/phd"
PHD_PAGE_BODY = b"<html><body><p>Six months, doctoral stipend.</p></body></html>"


def test_an_other_degree_page_does_not_pool_with_the_front_door(agency_a, fake_store) -> None:
    cache.clear()
    front = ExtractedClaims(confidence=0.9, institution_name="Nordland University")
    rest = ExtractedClaims(
        confidence=0.9,
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )
    # Never resolves alone (no institution, no programme name, no language) --
    # if it were pooled, its duration would either overwrite 24 or contradict
    # it. It must do neither.
    phd = ExtractedClaims(confidence=0.9, duration_months=6)

    source = Consortium(
        ResearchLead.from_url(
            "https://consortium.eu/", source_type="PROGRAM", funding_family="MULTILATERAL"
        ),
        ResearchLead.from_url(
            "https://consortium.eu/admissions",
            source_type="PROGRAM",
            funding_family="MULTILATERAL",
        ),
        ResearchLead.from_url(
            PHD_PAGE_URL, source_type="PROGRAM", funding_family="MULTILATERAL"
        ),
    )
    # More specific prefixes first: _pages matches with startswith, and
    # "https://consortium.eu/" would otherwise swallow the phd URL too.
    pages = {
        "https://consortium.eu/admissions": CONSORTIUM["https://consortium.eu/admissions"],
        PHD_PAGE_URL: (PHD_PAGE_URL, PHD_PAGE_BODY),
        "https://consortium.eu/": CONSORTIUM["https://consortium.eu/"],
    }

    def extract(snapshot: object, _client: object = None) -> ExtractionResult:
        url = snapshot.evidence_metadata["source_url"]  # type: ignore[attr-defined]
        if url.rstrip("/").endswith("consortium.eu"):
            claims = front
        elif url.endswith("/phd"):
            claims = phd
        else:
            claims = rest
        return ExtractionResult(
            claims=claims,
            metadata=ModelMetadata(model_id="test", schema_version=2, response_id=None, usage={}),
        )

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY,
            [source],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(pages)),
            extract=extract,
        )

    # front + admissions still pool exactly as before pooling is untouched by
    # this fix -- the phd page's 6-month duration never joined, so the row
    # keeps the front door's programme's real 24 months.
    assert Program.objects.count() == 1
    assert Program.objects.get().duration_months == 24
    assert report.written == 2  # front + admissions
    # The phd page could not resolve alone and was not held for the group
    # either -- it is blocked immediately, exactly as a poolable page behaved
    # before pooling existed at all.
    assert report.blocked == 1
    assert not any("disagreed" in note for note in report.degraded)


def test_undergraduate_and_postgraduate_are_not_other_degree_pages() -> None:
    # graduate is a substring of undergraduate/postgraduate -- this branch
    # already fixed one bug of exactly that kind ("eur" inside "European"),
    # so pin that ordinary admissions-page words do not trip the check.
    assert not pipeline_module._names_another_degree(
        "https://consortium.eu/admissions/undergraduate"
    )
    assert not pipeline_module._names_another_degree(
        "https://consortium.eu/admissions/postgraduate"
    )


def test_a_hyphenated_phd_segment_is_still_caught() -> None:
    assert pipeline_module._names_another_degree("https://consortium.eu/dfh-phd-track")
    assert pipeline_module._names_another_degree(
        "https://consortium.eu/international-studies/phd"
    )


# --- Funding: the line judge reads pages run_discovery already holds ---------

from apps.research.funding_judge import FUNDING_READS  # noqa: E402
from tests.research.conftest import ScriptedReaders  # noqa: E402

FUNDED_PAGE = (
    b"<html><body><main><h1>AI &amp; Robotics</h1><p>Taught in English.</p>"
    b"<p>All admitted international students receive a 50% tuition waiver.</p>"
    b"</main></body></html>"
)
WAIVER_SENTENCE = "All admitted international students receive a 50% tuition waiver."
FUNDING_URL = "https://utn.example/ai-robotics"


def _funding_lead(**overrides):
    fields = dict(
        source_type="PROGRAM", funding_family="", discovered_by="seed:test", identity=IDENTITY,
        one_programme_per_site=True,
    )
    fields.update(overrides)
    return ResearchLead.from_url(FUNDING_URL, **fields)


def _run_with_funding(agency_a, fake_store, readers, page=FUNDED_PAGE, lead=None, **run_kwargs):
    run_kwargs.setdefault("budget", RunBudget(fetches=10, extractions=20))
    fetch = _paced(_pages({FUNDING_URL: (FUNDING_URL, page)}))
    with tenant_scope(agency_a.id):
        return run_discovery(
            QUERY, [StaticSource(lead or _funding_lead())], tenant_id=agency_a.id,
            store=fake_store, admissions_cycle="2027", fetch=fetch, extract=_extract,
            funding_parser=readers, funding_claude=readers, **run_kwargs,
        )


def test_without_funding_readers_nothing_about_funding_changes(agency_a, fake_store) -> None:
    cache.clear()
    report = _run_with_funding(agency_a, fake_store, readers=None)
    assert report.written == 1
    assert (report.funding.served, report.funding.unagreed, report.funding.abstained) == (0, 0, 0)
    assert not FundingOpportunity.objects.filter(kind__startswith="I").exists()
    assert OfficialSourceSnapshot.objects.get().funding_read_at is None


def test_one_funding_reader_without_the_other_is_refused(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders()
    with pytest.raises(ValueError, match="both"), tenant_scope(agency_a.id):
        run_discovery(
            QUERY, [StaticSource(_funding_lead())], tenant_id=agency_a.id, store=fake_store,
            admissions_cycle="2027", fetch=_paced(_pages({})), extract=_extract,
            funding_parser=readers,
        )


def test_three_agreeing_readings_from_two_families_serve_the_award(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    report = _run_with_funding(agency_a, fake_store, readers)
    assert report.written == 1 and report.funding.served == 1
    assert len(readers.calls) == FUNDING_READS  # one chunk, three readings, no extra fetch
    assert "input" in readers.calls[0] and "input" in readers.calls[1]
    assert "system" in readers.calls[2]  # the Claude reading
    row = FundingOpportunity.objects.get(kind="I2_PROGRAMME_ATTACHED")
    assert row.served is True and row.found_via == "seed:test"
    claim = row.evidence_claims.get()
    assert claim.claim == WAIVER_SENTENCE and claim.visibility == "STUDENT_FACING"
    assert OfficialSourceSnapshot.objects.get().funding_read_at is not None


def test_a_third_reading_disagreeing_on_a_detail_is_served_with_the_detail_unconfirmed(
    agency_a, fake_store
) -> None:
    """Was `..._is_stored_unserved` until 2026-09-22 and asserted the opposite.

    `route` is not an existence field, so under tiered agreement (spec 8.6) the
    award is shown with `route` marked unconfirmed. This is the measured case
    the owner decided on by name: ten awards on five known funders reached
    nobody, all split on `route` and `money_form`, none on `holder`.
    """
    cache.clear()
    readers = ScriptedReaders(
        {WAIVER_SENTENCE: {}}, {WAIVER_SENTENCE: {}},
        {WAIVER_SENTENCE: {"route": "STUDENT_APPLIES_SEPARATELY"}},
    )
    report = _run_with_funding(agency_a, fake_store, readers)
    assert report.funding.unagreed == 0 and report.funding.served == 1
    assert report.funding.unconfirmed == 1
    row = FundingOpportunity.objects.get(kind="I2_PROGRAMME_ATTACHED")
    assert row.served is True
    assert row.route == "UNSTATED", "an unconfirmed field must not read as decided"


def test_a_third_reading_disagreeing_on_offered_is_still_stored_unserved(
    agency_a, fake_store
) -> None:
    """The half that did not change, pinned separately so a future widening of
    the existence tuple fails loudly. "Never show money the page does not
    offer" is the one guarantee tiered agreement may not weaken."""
    cache.clear()
    readers = ScriptedReaders(
        {WAIVER_SENTENCE: {}}, {WAIVER_SENTENCE: {}},
        {WAIVER_SENTENCE: {"offered": "NO"}},
    )
    report = _run_with_funding(agency_a, fake_store, readers)
    assert report.funding.served == 0
    row = FundingOpportunity.objects.get(kind="I2_PROGRAMME_ATTACHED")
    assert row.served is False and row.evidence_claims.get().visibility == "INTERNAL"


NEGATION_SENTENCE = "No scholarships are offered for this programme."
NEGATION_PAGE = (
    b"<html><body><main><h1>AI &amp; Robotics</h1><p>Taught in English.</p>"
    b"<p>" + NEGATION_SENTENCE.encode() + b"</p></main></body></html>"
)


def test_a_negation_writes_an_unserved_row_carrying_its_sentence(agency_a, fake_store) -> None:
    """Changed 2026-09-18 (spec 3.5.3). A negation used to write nothing, so a
    page saying "this intake will be without scholarship" left no trace and a
    later, vaguer read of another page could still serve the award. It now
    writes the award unserved, with the sentence, which is what a programme
    card shows as a note."""
    cache.clear()
    readers = ScriptedReaders({NEGATION_SENTENCE: {"offered": "NO"}})
    report = _run_with_funding(agency_a, fake_store, readers, page=NEGATION_PAGE)
    assert report.funding.negations == 1 and report.funding.served == 0
    row = FundingOpportunity.objects.get(kind__startswith="I")
    assert row.served is False and row.suspension_quote == NEGATION_SENTENCE


def test_a_page_the_budget_cannot_pay_for_in_full_makes_no_call(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    report = _run_with_funding(
        agency_a, fake_store, readers, budget=RunBudget(fetches=10, extractions=2)
    )
    assert readers.calls == []
    assert not FundingOpportunity.objects.filter(kind__startswith="I").exists()
    assert any("extractions budget" in item for item in report.degraded)
    assert f"funding read cut short, nothing written: {FUNDING_URL}" in report.degraded
    assert OfficialSourceSnapshot.objects.get().funding_read_at is None


def test_the_rate_limit_is_spent_per_call_before_any_call(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    report = _run_with_funding(agency_a, fake_store, readers, extraction_calls_per_hour=2)
    # count 1: the page's own extraction; count 2: the first funding call's
    # payment; count 3 trips the limit before any model call is made.
    assert readers.calls == []
    assert "extraction budget exhausted" in report.degraded
    assert f"funding read cut short, nothing written: {FUNDING_URL}" in report.degraded
    assert OfficialSourceSnapshot.objects.get().funding_read_at is None


def test_a_shell_page_is_counted_unreadable_not_read_as_no_funding(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    filler = b"word " * 45
    shell = (
        b"<html><body><main><p>" + filler + b"</p>"
        b"<!--" + b"x" * 25_000 + b"--></main></body></html>"
    )
    assert not pipeline_module.looks_unrendered("text/html", shell)
    report = _run_with_funding(agency_a, fake_store, readers, page=shell)
    assert report.funding.unreadable == 1 and readers.calls == []
    snapshot = OfficialSourceSnapshot.objects.get()
    assert snapshot.readability == OfficialSourceSnapshot.Readability.SHELL
    assert snapshot.funding_read_at is None


def test_a_lead_that_cannot_vouch_is_not_read(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    clue = _funding_lead(evidence_strength="ECOSYSTEM_CLUE", identity=None,
                         one_programme_per_site=False)
    _run_with_funding(agency_a, fake_store, readers, lead=clue)
    assert readers.calls == []


def test_a_search_lead_without_the_one_programme_promise_is_not_read(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    lead = _funding_lead(discovered_by="search:tavily", one_programme_per_site=False)
    assert lead.can_support_claim and not lead.one_programme_per_site
    report = _run_with_funding(agency_a, fake_store, readers, lead=lead)
    assert report.written == 1 and readers.calls == []


SCHOLARSHIP_SENTENCE = "International students automatically receive a 50% tuition waiver."
SCHOLARSHIP_SECTION_PAGE = (
    b"<html><body><main>"
    b"<h2>Admission requirements</h2>"
    b"<p>Applicants must hold a bachelor's degree in computer science.</p>"
    b"<h2>Scholarships</h2>"
    b"<p>" + SCHOLARSHIP_SENTENCE.encode() + b"</p>"
    b"</main></body></html>"
)


def test_a_funding_section_with_no_admission_word_is_still_read(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({SCHOLARSHIP_SENTENCE: {}})
    report = _run_with_funding(agency_a, fake_store, readers, page=SCHOLARSHIP_SECTION_PAGE)
    assert report.funding.served == 1
    row = FundingOpportunity.objects.get(kind="I2_PROGRAMME_ATTACHED")
    assert row.evidence_claims.get().claim == SCHOLARSHIP_SENTENCE


def test_a_short_funding_section_on_a_long_page_is_not_counted_unreadable(
    agency_a, fake_store
) -> None:
    cache.clear()
    filler = b"<p>Campus life in the city centre is lively.</p>" * 500
    page = (
        b"<html><body><main><h2>Fees</h2><p>See the fees office for details.</p>"
        b"<h2>Campus life</h2>" + filler + b"</main></body></html>"
    )
    assert len(page) >= 20_000
    readers = ScriptedReaders()
    report = _run_with_funding(agency_a, fake_store, readers, page=page)
    assert report.funding.unreadable == 0 and len(readers.calls) == FUNDING_READS


def test_one_failed_call_abstains_the_award_without_aborting_the_run(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}}, fail_calls=(2,))
    report = _run_with_funding(agency_a, fake_store, readers)
    assert len(readers.calls) == FUNDING_READS and report.written == 1
    row = FundingOpportunity.objects.get(kind="I2_PROGRAMME_ATTACHED")
    assert row.agreement == "ABSTAINED" and row.served is False
    assert report.funding.abstained == 1


def test_a_blocked_page_makes_no_funding_calls(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    url = "https://utn.example/phd-robotics"
    lead = ResearchLead.from_url(
        url, source_type="PROGRAM", funding_family="", discovered_by="seed:test",
        one_programme_per_site=True,
    )
    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY, [StaticSource(lead)], tenant_id=agency_a.id, store=fake_store,
            admissions_cycle="2027", fetch=_paced(_pages({url: (url, FUNDED_PAGE)})),
            extract=lambda _snapshot, _client=None: ExtractionResult(
                claims=ExtractedClaims(confidence=0.9),
                metadata=ModelMetadata(model_id="t", schema_version=2, response_id=None, usage={}),
            ),
            budget=RunBudget(fetches=10, extractions=20),
            funding_parser=readers, funding_claude=readers,
        )
    assert report.blocked == 1 and report.written == 0 and readers.calls == []


def test_an_unresolved_held_group_makes_no_funding_calls(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    front = ExtractedClaims(confidence=0.9, duration_months=24)
    rest = ExtractedClaims(confidence=0.9, program_name="Coastal Engineering", country_code="NO",
                           duration_months=24)
    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY, [_consortium_leads()], tenant_id=agency_a.id, store=fake_store,
            admissions_cycle="2027", fetch=_paced(_pages(CONSORTIUM)),
            extract=_split_extract(front, rest), budget=RunBudget(fetches=10, extractions=20),
            funding_parser=readers, funding_claude=readers,
        )
    assert report.written == 0 and readers.calls == []


def test_a_held_page_is_read_for_funding_once_its_group_resolves(agency_a, fake_store) -> None:
    cache.clear()
    admissions = (
        b"<html><body><p>Two years, taught in English.</p>"
        b"<p>" + WAIVER_SENTENCE.encode() + b"</p></body></html>"
    )
    pages = {
        "https://consortium.eu/admissions": ("https://consortium.eu/admissions", admissions),
        "https://consortium.eu/": ("https://consortium.eu/", CONSORTIUM_FRONT_DOOR),
    }
    front = ExtractedClaims(confidence=0.9, institution_name="Consortium University")
    rest = ExtractedClaims(
        confidence=0.9, program_name="Coastal Engineering", country_code="NO", duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )
    readers = ScriptedReaders({WAIVER_SENTENCE: {}})
    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY, [_consortium_leads()], tenant_id=agency_a.id, store=fake_store,
            admissions_cycle="2027", fetch=_paced(_pages(pages)),
            extract=_split_extract(front, rest), budget=RunBudget(fetches=10, extractions=20),
            funding_parser=readers, funding_claude=readers,
        )
    assert report.written == 2
    assert len(readers.calls) == 2 * FUNDING_READS
    row = FundingOpportunity.objects.get(kind="I2_PROGRAMME_ATTACHED")
    assert row.served is True and row.program == Program.objects.get()


def test_a_complete_read_that_found_nothing_is_recorded_as_read(agency_a, fake_store) -> None:
    cache.clear()
    readers = ScriptedReaders()
    report = _run_with_funding(agency_a, fake_store, readers)
    assert len(readers.calls) == FUNDING_READS and report.written == 1
    assert not FundingOpportunity.objects.filter(kind__startswith="I").exists()
    snapshot = OfficialSourceSnapshot.objects.get()
    assert snapshot.funding_read_at is not None
    assert snapshot.readability == OfficialSourceSnapshot.Readability.OK


# Whole-branch review, Fix 1: Consortium models the real Erasmus Mundus seed,
# whose entire defining property is that it awards jointly -- so a run through
# it must never invent an Institution, and the row it writes must be JOINT
# with the scraped provider string held for a curator to resolve.
def test_a_jointly_awarded_seed_writes_no_institution(agency_a, fake_store) -> None:
    cache.clear()
    front = ExtractedClaims(confidence=0.9, institution_name="Nordland University")
    rest = ExtractedClaims(
        confidence=0.9,
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )

    with tenant_scope(agency_a.id):
        institutions_before = Institution.objects.count()
        report = run_discovery(
            QUERY,
            [_consortium_leads()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(CONSORTIUM)),
            extract=_split_extract(front, rest),
        )

        assert Institution.objects.count() == institutions_before
        program = Program.objects.get()
        assert program.provision_type == Program.ProvisionType.JOINT
        assert program.provider_text
        assert any(
            "joint programmes await provider resolution" in note for note in report.degraded
        )


# Whole-branch review, Fix 2: a curator resolving a genuinely multi-provider
# programme leaves it JOINT -- that is correct, since it really is jointly
# awarded -- so a later run must not send the curator back to a queue that is
# already done. Only programmes with no ProgramAwardingInstitution row yet
# may be counted.
def test_an_already_resolved_joint_programme_is_not_recounted(agency_a, fake_store) -> None:
    cache.clear()
    front = ExtractedClaims(confidence=0.9, institution_name="Nordland University")
    rest = ExtractedClaims(
        confidence=0.9,
        program_name="Coastal Engineering",
        country_code="NO",
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
    )
    with tenant_scope(agency_a.id):
        first = run_discovery(
            QUERY,
            [_consortium_leads()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(CONSORTIUM)),
            extract=_split_extract(front, rest),
        )
        assert any(
            "joint programmes await provider resolution" in note for note in first.degraded
        )
        program = Program.objects.get()

        # The curator's own act of resolution: a ProgramAwardingInstitution row.
        institution = Institution.objects.create(
            canonical_key="test:nordland",
            name="Nordland University",
            country_code="NO",
            official_website="https://nordland.example/",
        )
        ProgramAwardingInstitution.objects.create(program=program, institution=institution)

        # A second host of the SAME site publishing the identical programme --
        # dedupes onto the same Program row via (institution=None,
        # canonical_key, location_key, origin_domain), same as two real pages
        # of one joint programme would. (Another registrable domain would get
        # its own row: provenance gate spec §3.) Fresh URLs so nothing
        # short-circuits on an unchanged snapshot, which never re-populates
        # joint_programs.
        pages = {
            "https://apply.consortium.eu/admissions": (
                "https://apply.consortium.eu/admissions",
                CONSORTIUM_ADMISSIONS,
            ),
            "https://apply.consortium.eu/": ("https://apply.consortium.eu/", CONSORTIUM_FRONT_DOOR),
        }
        source = Consortium(
            ResearchLead.from_url(
                "https://apply.consortium.eu/", source_type="PROGRAM", funding_family="MULTILATERAL"
            ),
            ResearchLead.from_url(
                "https://apply.consortium.eu/admissions",
                source_type="PROGRAM",
                funding_family="MULTILATERAL",
            ),
        )

        def extract_b(snapshot: object, _client: object = None) -> ExtractionResult:
            url = snapshot.evidence_metadata["source_url"]  # type: ignore[attr-defined]
            return ExtractionResult(
                claims=rest if url.endswith("/admissions") else front,
                metadata=ModelMetadata(
                    model_id="test", schema_version=2, response_id=None, usage={}
                ),
            )

        second = run_discovery(
            QUERY,
            [source],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=_paced(_pages(pages)),
            extract=extract_b,
        )

    assert Program.objects.count() == 1  # same row, not a new one
    assert not any(
        "joint programmes await provider resolution" in note for note in second.degraded
    )


def test_the_paced_fetch_threads_the_credit_budget_through() -> None:
    """RunBudget caps the NUMBER of fetches; SweepBudget caps what they cost.
    A count ceiling cannot bound cost -- scrape.do applies per-domain
    multipliers of 10-200 credits server-side -- so the two are not the same
    ceiling and must not be merged."""
    seen: dict[str, object] = {}

    def fetch(url: str, **kwargs: object) -> FetchResult:
        seen.update(kwargs)
        return FetchResult(url, (), "text/html", b"<html></html>")

    credits = SweepBudget({"FIRECRAWL": 10})
    _paced(fetch, credits=credits)("https://example.test/a")

    assert seen["budget"] is credits


def _archived(final_url: str, body: bytes) -> FetchedPage:
    return FetchedPage(
        final_url=final_url, redirects=(), content_type="text/html", body=body,
        fetched_via="ARCHIVE", outcome=Outcome.ARCHIVED, rung=6, captured_at="2026-06-25",
    )


def test_a_capture_is_marked_on_the_snapshot_the_claims_cite(agency_a, fake_store) -> None:
    """Spec §6: an ARCHIVED page lands as `render_status = "ARCHIVE:<date>"`.

    `retrieve_official_source` returns ARCHIVED as SERVED and `final_url` is
    the ORIGINAL url, so a capture up to a year old arrives here as an
    ordinary live page. Every claim minted below it carries
    `retrieved_at=now`; without this marker a year-old capture is evidence
    dated today and nothing on the row says otherwise.
    """
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM", funding_family="", identity=IDENTITY,
    )

    def fetch(url: str, **_kwargs: object) -> FetchResult:
        return _archived("https://www.utn.de/en/study/ai-robotics-en", OFFICIAL_PAGE)

    with tenant_scope(agency_a.id):
        report = run_discovery(
            QUERY, [StaticSource(lead)], tenant_id=agency_a.id, store=fake_store,
            admissions_cycle="2027", fetch=_paced(fetch), extract=_extract,
        )

    assert report.written == 1
    claim = OfficialEvidenceClaim.objects.first()
    assert claim is not None
    assert claim.snapshot.render_status == "ARCHIVE:2026-06-25"


def test_a_live_page_carries_no_capture_marker(agency_a, fake_store) -> None:
    """The flip side, so the marker means something at this consumer too."""
    cache.clear()
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM", funding_family="", identity=IDENTITY,
    )
    pages = {"https://www.utn.de/": ("https://www.utn.de/en/study/ai-robotics-en", OFFICIAL_PAGE)}

    with tenant_scope(agency_a.id):
        run_discovery(
            QUERY, [StaticSource(lead)], tenant_id=agency_a.id, store=fake_store,
            admissions_cycle="2027", fetch=_paced(_pages(pages)), extract=_extract,
        )

    claim = OfficialEvidenceClaim.objects.first()
    assert claim is not None and claim.snapshot.render_status is None


def test_extraction_reads_readable_text_not_the_old_nav_keeping_position_cut(
    agency_a, fake_store
) -> None:
    """Audit #4: the extractor used to build `relevant_text` from
    `harvest.page_text`, which kept navigation and cut at a fixed byte
    position without regard for word/line boundaries. It now goes through
    `reader.readable_text`, which drops chrome (<nav>) and, when a cut is
    needed, cuts between lines rather than mid-word.
    """
    cache.clear()
    lines = "\n".join(f"<li>paragraph-line-{i:04d}</li>" for i in range(1, 2001))
    body = (
        b"<html><body><nav>NAVIGATION_MARKER should never reach the model</nav>"
        b"<ul>" + lines.encode() + b"</ul></body></html>"
    )
    lead = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM", funding_family="", identity=IDENTITY,
    )
    pages = {"https://www.utn.de/": ("https://www.utn.de/en/study/ai-robotics-en", body)}
    captured: list[str] = []

    def extract(snapshot: object, _client: object = None) -> ExtractionResult:
        captured.append(snapshot.relevant_text)  # type: ignore[attr-defined]
        return ExtractionResult(
            claims=CLAIMS,
            metadata=ModelMetadata(model_id="test", schema_version=2, response_id=None, usage={}),
        )

    with tenant_scope(agency_a.id):
        run_discovery(
            QUERY, [StaticSource(lead)], tenant_id=agency_a.id, store=fake_store,
            admissions_cycle="2027", fetch=_paced(_pages(pages)), extract=extract,
        )

    assert captured, "extraction was never called; the test proves nothing"
    relevant_text = captured[0]
    assert "NAVIGATION_MARKER" not in relevant_text
    assert len(relevant_text) <= 24_000
    # Every surviving line is a complete "- paragraph-line-NNNN" item: no
    # partial word or half-line from a mid-text cut.
    for line in relevant_text.split("\n"):
        if line.strip():
            assert re.fullmatch(r"- paragraph-line-\d{4}", line), line
