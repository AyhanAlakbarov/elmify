"""Funder hosts go through the holder path; pointers come back as names."""

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.funding.models import OfficialSource, OfficialSourceSnapshot
from apps.research import pipeline
from apps.research.discovery import ResearchLead
from apps.research.egress import FetchResult
from apps.research.funding_judge import FundingDecision, FundingReadResult, PointerLead

pytestmark = pytest.mark.django_db

PAGE = (
    b"<html><body><h1>Stipendien</h1>"
    b"<p>Das Stipendium betraegt 992 Euro monatlich fuer Studierende aller Faecher, "
    b"und wird jedes Jahr an begabte Bewerberinnen und Bewerber vergeben, die sich "
    b"selbst bewerben und ein Auswahlverfahren durchlaufen.</p>"
    b"<p>Weitere Foerderung: ein DAAD-Stipendium kann zusaetzlich beantragt werden.</p>"
    b"</body></html>"
)


@pytest.fixture
def funder_page():
    """A FUNDER lead, its page, and the catalog rows a fetched page leaves."""
    url = "https://foundation-example.de/stipendien"
    lead = ResearchLead.from_url(
        url, source_type="FUNDER", funding_family="PRIVATE_FOUNDATION",
        discovered_by="R4_SEARCH:exa",
    )
    source = OfficialSource.objects.create(
        canonical_url=url, publisher="foundation-example.de",
        source_type=OfficialSource.Type.SCHOLARSHIP,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, sha256=f"{uuid4().hex}{uuid4().hex}", s3_key="k", s3_version_id="v",
        byte_size=len(PAGE), final_url=url, redirect_chain=[], admissions_cycle="2027",
        retrieved_at=timezone.now(),
    )
    page = FetchResult(url, (), "text/html", PAGE)
    return lead, page, source, snapshot


def _decision(**over):
    base = dict(
        kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", offered="YES",
        internationals_included="YES", nationality_shape="OPEN",
        route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT", holder="PRIVATE_FOUNDATION",
        tuition="UNSTATED", living="FULL", extras=(), obligation=(), agreement="AGREED",
        quotes=("Das Stipendium betraegt 992 Euro monatlich.",), name="Stipendium", disputed=(),
    )
    base.update(over)
    return FundingDecision(**base)  # type: ignore[arg-type]


def _run(monkeypatch, funder_page, read):
    lead, page, source, snapshot = funder_page
    monkeypatch.setattr(pipeline, "read_funding", lambda *a, **k: read)
    counters = pipeline.FundingCounts()
    leads = pipeline._fund_holder_page(
        object(), object(), page, lead=lead, source=source, snapshot=snapshot,
        holder_domain="foundation-example.de", holder_name="Example Foundation",
        budget=pipeline.RunBudget(), degraded=[], actor=uuid4(),
        extraction_calls_per_hour=1_000, now=None, counters=counters,
    )
    return counters, leads


def test_a_funder_lead_writes_a_holder_row_and_counts_it_served(monkeypatch, funder_page):
    counters, leads = _run(
        monkeypatch, funder_page, FundingReadResult((_decision(),), 0, 0, 0, ())
    )
    assert counters.served == 1 and leads == []


def test_an_institution_shaped_award_on_a_funder_page_writes_no_row(monkeypatch, funder_page):
    counters, leads = _run(
        monkeypatch, funder_page,
        FundingReadResult(
            (_decision(scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE"),), 0, 0, 0, ()
        ),
    )
    assert counters.served == 0 and leads == []


def test_pointers_come_back_as_names_with_their_holder(monkeypatch, funder_page):
    pointers = (
        PointerLead("Ein DAAD-Stipendium kann beantragt werden.", "DAAD", "NATIONAL_GOVERNMENT"),
        PointerLead("Siehe auch die Stiftung X.", "Stiftung X", "PRIVATE_FOUNDATION"),
    )
    counters, leads = _run(
        monkeypatch, funder_page, FundingReadResult((), 2, 0, 0, pointers)
    )
    assert counters.pointers == 2 and counters.pointer_leads == 2
    # A pointer is a NAME, not a URL: no URL from page text is trusted as the
    # body's own site, so the resolver gets a name and nothing else.
    assert [(p.name, p.holder) for p in leads] == [
        ("DAAD", "NATIONAL_GOVERNMENT"), ("Stiftung X", "PRIVATE_FOUNDATION")
    ]


def test_at_most_ten_pointers_leave_one_page(monkeypatch, funder_page):
    pointers = tuple(
        PointerLead(f"quote {i}", f"Funder {i}", "PRIVATE_FOUNDATION") for i in range(31)
    )
    _counters, leads = _run(monkeypatch, funder_page, FundingReadResult((), 31, 0, 0, pointers))
    assert len(leads) == 10


def test_a_holder_page_with_no_registrable_domain_writes_nothing(monkeypatch, funder_page):
    lead, page, source, snapshot = funder_page
    monkeypatch.setattr(
        pipeline, "read_funding", lambda *a, **k: FundingReadResult((_decision(),), 0, 0, 0, ())
    )
    counters, degraded = pipeline.FundingCounts(), []
    leads = pipeline._fund_holder_page(
        object(), object(), page, lead=lead, source=source, snapshot=snapshot,
        holder_domain="", holder_name="", budget=pipeline.RunBudget(), degraded=degraded,
        actor=uuid4(), extraction_calls_per_hour=1_000, now=None, counters=counters,
    )
    assert leads == [] and counters.served == 0
    assert any("no registrable domain" in message for message in degraded)


def test_a_programme_lead_never_takes_the_holder_path(funder_page):
    lead, _page, _source, _snapshot = funder_page
    programme_lead = ResearchLead.from_url(
        lead.canonical_url, source_type="PROGRAM", funding_family="UNIVERSITY_WIDE"
    )
    assert pipeline._is_funder_lead(programme_lead) is False
    assert pipeline._is_funder_lead(lead) is True


def test_run_discovery_routes_a_funder_lead_past_extraction_to_the_holder_path(
    monkeypatch, agency_a, fake_store
):
    """The wire, not the function: a FUNDER lead must reach _fund_holder_page
    and must never pay for the programme claims extractor, which has no
    programme to find on a foundation's page."""
    from datetime import timedelta

    from django.core.cache import cache

    from apps.research.discovery import DiscoveryQuery, RunBudget
    from apps.research.pipeline import PacedFetch, run_discovery
    from apps.tenancy.context import tenant_scope

    url = "https://foundation-example.de/stipendien"

    class StaticSource:
        name = "R4_SEARCH:exa"
        one_programme_per_link = False
        awards_jointly = False

        def find(self, query):
            return [
                ResearchLead.from_url(
                    url, source_type="FUNDER", funding_family="PRIVATE_FOUNDATION",
                    discovered_by="R4_SEARCH:exa",
                )
            ]

    monkeypatch.setattr(
        pipeline, "read_funding",
        lambda *a, **k: FundingReadResult(
            (_decision(),), 1, 0, 0,
            (PointerLead("Ein DAAD-Stipendium.", "DAAD", "NATIONAL_GOVERNMENT"),),
        ),
    )

    def extract_never(*_a, **_k):
        raise AssertionError("a funder page must not reach the claims extractor")

    cache.clear()
    with tenant_scope(agency_a.id):
        report = run_discovery(
            DiscoveryQuery(field="chemistry", country_code="DE", max_leads=5),
            [StaticSource()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=PacedFetch(
                actor_id=uuid4(), budget=RunBudget(), interval=timedelta(seconds=0),
                sleep=lambda _s: None,
                fetch=lambda _url, **_k: FetchResult(url, (), "text/html", PAGE),
            ),
            extract=extract_never,
            funding_parser=object(),
            funding_claude=object(),
        )

    assert report.written == 0  # a funder page writes no programme row
    assert report.funding.served == 1
    assert report.pointer_names == (("DAAD", "NATIONAL_GOVERNMENT"),)


from apps.research.model_cost import ReadingTier, ReadingTierRefused, Usage  # noqa: E402


def test_a_read_leaves_its_cost_on_the_snapshot_and_in_the_counters(monkeypatch, funder_page):
    def read(*_a, meter, **_k):
        meter.record(Usage("claude", "claude-sonnet-5", "default", 1_000, 0, 0, 100))
        return FundingReadResult((_decision(),), 0, 0, 0, ())

    lead, page, source, snapshot = funder_page
    monkeypatch.setattr(pipeline, "read_funding", read)
    counters = pipeline.FundingCounts()
    pipeline._fund_holder_page(
        object(), object(), page, lead=lead, source=source, snapshot=snapshot,
        holder_domain="foundation-example.de", holder_name="Example Foundation",
        budget=pipeline.RunBudget(), degraded=[], actor=uuid4(),
        extraction_calls_per_hour=1_000, now=None, counters=counters,
    )
    snapshot.refresh_from_db()
    assert snapshot.funding_read_cost["calls"] == 1
    assert snapshot.funding_read_cost["usd"] == pytest.approx(0.003)
    assert counters.model_calls == 1 and counters.model_usd == pytest.approx(0.003)


def test_the_run_tier_reaches_the_judge(monkeypatch, funder_page):
    seen = {}

    def read(*_a, tier, **_k):
        seen["tier"] = tier
        return FundingReadResult((), 0, 0, 0, ())

    lead, page, source, snapshot = funder_page
    monkeypatch.setattr(pipeline, "read_funding", read)
    pipeline._fund_holder_page(
        object(), object(), page, lead=lead, source=source, snapshot=snapshot,
        holder_domain="foundation-example.de", holder_name="Example Foundation",
        budget=pipeline.RunBudget(), degraded=[], actor=uuid4(),
        extraction_calls_per_hour=1_000, now=None, counters=pipeline.FundingCounts(),
        tier=ReadingTier.FLEX,
    )
    assert seen["tier"] is ReadingTier.FLEX


def test_a_refused_tier_stops_the_run_instead_of_reading_as_a_page_failure(
    monkeypatch, agency_a, fake_store
):
    """A flex 400 is about the RUN, not the page: caught per page, every page of
    the run would come back unread and the run would report success."""
    from datetime import timedelta

    from django.core.cache import cache

    from apps.research.discovery import DiscoveryQuery, RunBudget
    from apps.research.pipeline import PacedFetch, run_discovery
    from apps.tenancy.context import tenant_scope

    url = "https://foundation-example.de/stipendien"
    seen = {}

    class StaticSource:
        name = "R4_SEARCH:exa"
        one_programme_per_link = False
        awards_jointly = False

        def find(self, query):
            return [
                ResearchLead.from_url(
                    url, source_type="FUNDER", funding_family="PRIVATE_FOUNDATION",
                    discovered_by="R4_SEARCH:exa",
                )
            ]

    def refuse(*_a, tier, **_k):
        seen["tier"] = tier
        raise ReadingTierRefused("flex is not available for this model")

    monkeypatch.setattr(pipeline, "read_funding", refuse)
    cache.clear()
    with tenant_scope(agency_a.id), pytest.raises(ReadingTierRefused):
        run_discovery(
            DiscoveryQuery(field="chemistry", country_code="DE", max_leads=5),
            [StaticSource()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=PacedFetch(
                actor_id=uuid4(), budget=RunBudget(), interval=timedelta(seconds=0),
                sleep=lambda _s: None,
                fetch=lambda _url, **_k: FetchResult(url, (), "text/html", PAGE),
            ),
            extract=lambda *_a, **_k: None,
            funding_parser=object(),
            funding_claude=object(),
            reading_tier=ReadingTier.FLEX,
        )
    assert seen["tier"] is ReadingTier.FLEX


from django.db import connection  # noqa: E402


def _batch_discovery(monkeypatch, agency_a, fake_store, results):
    """The routing test's run, in batch mode, with read_funding_batched faked."""
    from datetime import timedelta

    from django.core.cache import cache

    from apps.research.discovery import DiscoveryQuery, RunBudget
    from apps.research.pipeline import PacedFetch, run_discovery
    from apps.tenancy.context import tenant_scope

    url = "https://foundation-example.de/stipendien"

    class StaticSource:
        name = "R4_SEARCH:exa"
        one_programme_per_link = False
        awards_jointly = False

        def find(self, query):
            return [
                ResearchLead.from_url(
                    url, source_type="FUNDER", funding_family="PRIVATE_FOUNDATION",
                    discovered_by="R4_SEARCH:exa",
                )
            ]

    depth = {}

    def batched(_clients, pages, **_kwargs):
        depth["during"] = len(connection.atomic_blocks)
        assert len(pages) == 1
        # One reading came back and was billed, whatever the page then decides.
        pages[0].meter.record(Usage("claude", "claude-sonnet-5", "batch", 1_000, 0, 0, 100))
        return results

    def never(*_a, **_k):
        raise AssertionError("a batch run must not read synchronously")

    monkeypatch.setattr(pipeline, "read_funding_batched", batched)
    monkeypatch.setattr(pipeline, "read_funding", never)
    cache.clear()
    with tenant_scope(agency_a.id):
        depth["before"] = len(connection.atomic_blocks)
        report = run_discovery(
            DiscoveryQuery(field="chemistry", country_code="DE", max_leads=5),
            [StaticSource()],
            tenant_id=agency_a.id,
            store=fake_store,
            admissions_cycle="2027",
            fetch=PacedFetch(
                actor_id=uuid4(), budget=RunBudget(), interval=timedelta(seconds=0),
                sleep=lambda _s: None,
                fetch=lambda _url, **_k: FetchResult(url, (), "text/html", PAGE),
            ),
            extract=never,
            funding_parser=object(),
            funding_claude=object(),
            reading_tier=ReadingTier.BATCH,
            funding_batch=object(),
        )
    # No transaction may be open across a wait that can last hours.
    assert depth["during"] == depth["before"]
    return report


def test_a_batch_run_decides_after_the_queue_drains(monkeypatch, agency_a, fake_store):
    report = _batch_discovery(
        monkeypatch, agency_a, fake_store,
        [FundingReadResult(
            (_decision(),), 1, 0, 0,
            (PointerLead("Ein DAAD-Stipendium.", "DAAD", "NATIONAL_GOVERNMENT"),),
        )],
    )
    assert report.funding.served == 1
    assert report.pointer_names == (("DAAD", "NATIONAL_GOVERNMENT"),)
    snapshot = OfficialSourceSnapshot.objects.get(funding_read_at__isnull=False)
    assert snapshot.funding_read_cost is not None


def test_a_page_the_batch_did_not_finish_writes_nothing_and_says_so(
    monkeypatch, agency_a, fake_store
):
    report = _batch_discovery(monkeypatch, agency_a, fake_store, [None])
    assert report.funding.served == 0
    assert any("funding batch did not finish" in line for line in report.degraded)
    assert not OfficialSourceSnapshot.objects.filter(funding_read_at__isnull=False).exists()
    # Undecided, but the reading that came back was paid for: it is in the run's cost.
    assert report.funding.model_calls == 1


def test_a_batch_run_without_batch_clients_is_refused(agency_a, fake_store):
    from apps.research.discovery import DiscoveryQuery
    from apps.research.pipeline import run_discovery

    with pytest.raises(ValueError, match="funding_batch"):
        run_discovery(
            DiscoveryQuery(field="chemistry", country_code="DE", max_leads=1), [],
            tenant_id=agency_a.id, store=fake_store, admissions_cycle="2027",
            fetch=lambda _url, **_k: None, funding_parser=object(), funding_claude=object(),
            reading_tier=ReadingTier.BATCH,
        )
