import datetime as dt
from dataclasses import replace

import pytest

from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.funding.validity import cycle_validity
from apps.research.cycle_verification import (
    Seams,
    Subject,
    entries_from_decision,
    joins,
    record_read_evidence,
    verify_cycle,
)
from apps.research.fetch import SweepBudget
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.funding_judge import FundingDecision
from apps.research.metering import Meter
from apps.research.providers.base import SiteSearchResult

pytestmark = pytest.mark.django_db
TODAY = dt.date(2026, 9, 26)


def _decision(**overrides):
    base = FundingDecision(
        kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", offered="YES",
        internationals_included="YES", nationality_shape="ANY", route="STUDENT_APPLIES",
        money_form="GRANT", holder="PRIVATE_FOUNDATION", tuition="FULL", living="FULL",
        extras=(), obligation=(), agreement="AGREED",
        quotes=("The Example Fellowship funds master's study.",), name="Example Fellowship",
        disputed=(), heading="Example Fellowship",
    )
    return replace(base, **overrides)


def _opportunity():
    return FundingOpportunity.objects.create(
        canonical_key="read:example", name="Example Fellowship", family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL", agreement="AGREED",
    )


def test_an_entry_carries_the_quote_the_digest_and_the_normalised_deadline(monkeypatch):
    # docs/research/country-labels.csv ships header-only until
    # `refresh_country_labels` is run live, so the labels are injected here.
    monkeypatch.setattr("apps.funding.deadline_conditions.default_countries",
                        lambda: {"india": "IN", "indian": "IN"})
    decision = _decision(applies_to="2027-2028", stated_on="2026-09-01",
                         deadlines=(("2026-11-30", "applicants from India"),))
    [entry] = entries_from_decision(decision, step="0", url="https://f.example/a",
                                    sha256="b" * 64, at=TODAY)
    assert entry["intake_year"] == 2027
    assert entry["deadlines"] == [["2026-11-30", "applicants from India", "NATIONALITY:IN"]]
    assert entry["quote"].startswith("The Example Fellowship")


def test_the_writer_records_every_intakes_decision_on_every_tracked_row():
    opportunity = _opportunity()
    for decision in (
        _decision(applies_to="2027-2028", deadlines=(("2027-01-15", "ALL"),)),
        _decision(offered="NO", applies_to="2028-2030", stated_on="2026-09-01",
                  suspension_quote="no scholarships for the 2028 intake"),
    ):
        record_read_evidence(opportunity, decision, url="https://f.example/a",
                             sha256="c" * 64, at=TODAY, today=TODAY)
    rows = {r.intake_start_year: r for r in FundingCycleVerification.objects.all()}
    assert set(rows) == {2027, 2028}
    assert rows[2027].state == "OPEN"
    assert rows[2028].state == "SUSPENDED"
    assert all(len(r.evidence) == 2 for r in rows.values())
    # The first ladder run is due at once: a row nobody schedules is never verified.
    assert all(r.next_check_at is not None for r in rows.values())


def test_a_changed_page_replaces_its_own_old_entries_but_keeps_archive_captures():
    opportunity = _opportunity()
    record_read_evidence(opportunity, _decision(deadlines=(("2027-01-15", "ALL"),)),
                         url="https://f.example/a", sha256="d" * 64, at=TODAY, today=TODAY)
    row = FundingCycleVerification.objects.get(intake_start_year=2027)
    row.evidence.append({**row.evidence[0], "archived": True, "sha256": "e" * 64,
                         "captured_at": "2025-04-01"})
    row.save()
    record_read_evidence(opportunity, _decision(deadlines=(("2027-02-01", "ALL"),)),
                         url="https://f.example/a", sha256="f" * 64, at=TODAY, today=TODAY)
    row.refresh_from_db()
    assert {e["sha256"] for e in row.evidence} == {"e" * 64, "f" * 64}


def _page(url, text, outcome=Outcome.FETCHED, body=None):
    return FetchedPage(final_url=url, redirects=(), content_type="text/html",
                       body=body if body is not None else f"<main>{text}</main>".encode(),
                       markdown=text, outcome=outcome, fetched_via="FIRECRAWL", cost_credits=1)


class Script:
    """Scripted seams. `reads` maps a URL to the decisions its read returns."""

    def __init__(self, pages=None, reads=None, crawl_urls=(), captures=None, search=()):
        # The award's own page is live by default. Without it every own page is
        # DEAD, the award is ENDED at step 0, and a test of a later step would
        # pass without the step ever running.
        own = "https://f.example/award"
        self.pages = {own: _page(own, "Example Fellowship"), **(pages or {})}
        self.reads = reads or {}
        self.crawl_urls, self.captures, self.search_urls = crawl_urls, captures or {}, search
        self.calls: list[tuple[str, str]] = []

    def seams(self):
        from apps.research.fetch.site import CrawlResult

        def fetch(url, **kw):
            self.calls.append(("fetch", url))
            return self.pages.get(url, _page(url, "", Outcome.DEAD))

        def crawl(url, **kw):
            self.calls.append(("crawl", url))
            return CrawlResult(job_id="j", urls=tuple(self.crawl_urls), dead=(), errors=(),
                               robots_blocked=(), credits=len(self.crawl_urls), status="completed")

        def capture_near(url, *, at, **kw):
            self.calls.append(("wayback", f"{url}@{at.year}"))
            return self.captures.get((url, at.year), _page(url, "", Outcome.BLOCKED))

        def read(page):
            self.calls.append(("read", page.final_url))
            return tuple(self.reads.get(page.final_url, ()))

        def search(*, query, domain, **kw):
            self.calls.append(("exa", query))
            return SiteSearchResult(urls=tuple(self.search_urls), cost_usd=0.01, provider="exa")

        def brave(*, query, domain, **kw):
            self.calls.append(("brave", query))
            return SiteSearchResult(urls=(), cost_usd=0.005, provider="brave")

        return Seams(fetch=fetch, crawl=crawl, capture_near=capture_near, read=read,
                     site_search=search, fallback_search=brave, store=_Store())


class _Store:
    def put(self, key, body):
        return "v1"


SUBJECT = Subject(name="Example Fellowship", kind="I0_HOLDER_AWARD", scope="HOLDER_OWN",
                  own_urls=("https://f.example/award",), domains=frozenset({"f.example"}),
                  primary_domain="f.example", ambiguous=False, cadence=None, languages=())


def _run(script, stored=(), today=TODAY, subject=SUBJECT, year=2027):
    meter = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    return verify_cycle(subject, intake_year=year, today=today, seams=script.seams(),
                        meter=meter, stored=list(stored))


def _digest(page):
    import hashlib

    return hashlib.sha256(page.body).hexdigest()


def test_step_zero_decisive_makes_no_crawl_and_no_search():
    page = _page("https://f.example/award", "x", Outcome.UNCHANGED)
    script = Script(pages={"https://f.example/award": page})
    # The stored entry was read off these very bytes.
    stored = entries_from_decision(_decision(applies_to="2027-2028",
                                             deadlines=(("2027-01-15", "ALL"),)),
                                   step="0", url="https://f.example/award",
                                   sha256=_digest(page), at=TODAY)
    verdict = _run(script, stored)
    assert (verdict.state, verdict.step) == ("OPEN", "0")
    assert [kind for kind, _ in script.calls] == ["fetch"]  # one credit, no reading


def test_an_unchanged_own_page_is_not_read_again():
    page = _page("https://f.example/award", "x", Outcome.UNCHANGED)
    script = Script(pages={"https://f.example/award": page})
    stored = entries_from_decision(_decision(), step="0", url="https://f.example/award",
                                   sha256=_digest(page), at=TODAY)
    _run(script, stored)
    assert ("read", "https://f.example/award") not in script.calls


DEAD = {"https://f.example/award": _page("https://f.example/award", "", Outcome.DEAD)}


def test_every_own_page_dead_is_page_removed_and_ended():
    verdict = _run(Script(pages=DEAD))
    assert verdict.page_removed and verdict.state == "ENDED"


@pytest.mark.parametrize(
    ("decision_overrides", "ambiguous", "expected"),
    [
        ({}, False, True),
        ({"kind": "I1_UNIVERSITY_WIDE"}, False, False),       # another kind is another award
        ({"scope": "PROGRAM"}, False, False),
        ({"quotes": ("Our other grant",), "heading": "Grants", "name": "Other Grant"}, True, False),
        ({"quotes": ("The Example Fellowship 2027 call",)}, True, True),
        # Another award whose name CONTAINS this one's is another award.
        ({"name": "Example Fellowship for Women",
          "quotes": ("The Example Fellowship for Women 2027 call",)}, True, False),
        ({"name": "  example   FELLOWSHIP ", "heading": "", "quotes": ("2027 call",)}, True, True),
        ({"name": "", "heading": "", "quotes": ("The Example Fellowship 2027 call",)}, True, True),
        ({"name": "", "heading": "", "quotes": ("The Example Fellowships office",)}, True, False),
    ],
)
def test_a_decision_joins_its_award_by_kind_scope_and_when_ambiguous_by_name(
    decision_overrides, ambiguous, expected
):
    subject = replace(SUBJECT, ambiguous=ambiguous)
    assert joins(_decision(**decision_overrides), subject) is expected


def test_an_october_call_with_a_november_deadline_projects_before_the_intake():
    from apps.funding.validity import Evidence

    evidence = Evidence(past_calls=((dt.date(2025, 10, 1), dt.date(2025, 11, 30)),
                                    (dt.date(2024, 10, 1), dt.date(2024, 11, 30))))
    assert cycle_validity(evidence, student={}, target_intake="2027",
                          today=dt.date(2027, 6, 1)) == "CLOSED_FOR_INTAKE"


def test_step_zero_empty_crawls_with_the_cycle_vocabulary_and_limit_15(settings):
    settings.CYCLE_CRAWL_LIMIT = 15
    calls = {}
    script = Script(crawl_urls=("https://f.example/news/2027-call",),
                    pages={"https://f.example/news/2027-call": _page(
                        "https://f.example/news/2027-call", "The Example Fellowship 2027 call")},
                    reads={"https://f.example/news/2027-call": (
                        _decision(applies_to="2027", deadlines=(("2027-01-15", "ALL"),)),)})
    seams = script.seams()
    original = seams.crawl

    def spy(url, **kw):
        calls.update(kw)
        return original(url, **kw)

    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                           seams=replace(seams, crawl=spy),
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    assert (verdict.state, verdict.step) == ("OPEN", "1")
    assert calls["limit"] == 15 and "deadline" in calls["include_paths"]
    assert calls["tag"] == "cycle-verify:2027"


def test_a_crawled_page_naming_neither_the_award_nor_a_year_is_not_read():
    script = Script(crawl_urls=("https://f.example/about",),
                    pages={"https://f.example/about": _page("https://f.example/about",
                                                            "About our foundation")})
    _run(script)
    assert ("read", "https://f.example/about") not in script.calls


def test_a_crawled_url_off_the_organisations_domains_is_never_fetched():
    script = Script(crawl_urls=("https://cdn.other.example/call.pdf",))
    _run(script)
    assert ("fetch", "https://cdn.other.example/call.pdf") not in script.calls


def test_a_crawl_that_cannot_fit_the_run_budget_is_not_submitted(settings):
    settings.FETCH_PDF_MAX_PAGES = 60
    script = Script(crawl_urls=("https://f.example/news",))
    meter = Meter(SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 1000}))
    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=script.seams(),
                           meter=meter, stored=[])
    assert ("crawl", "https://f.example/award") not in script.calls
    assert any(t["note"].startswith("crawl ceiling") for t in verdict.trail)


def _empty_crawl():
    from apps.research.fetch.site import CrawlResult

    return CrawlResult(job_id="j", urls=(), dead=(), errors=(), robots_blocked=(), credits=0,
                       status="completed")


def test_wayback_captures_of_two_earlier_cycles_make_it_upcoming():
    url = "https://f.example/award"
    captures = {
        (url, 2025): replace(_page(url, "Example Fellowship 2025 call"), outcome=Outcome.ARCHIVED,
                             captured_at="2025-04-01"),
        (url, 2024): replace(_page(url, "Example Fellowship 2024 call"), outcome=Outcome.ARCHIVED,
                             captured_at="2024-04-01"),
    }
    reads = {url: (_decision(stated_on="2026-03-03", deadlines=(("2026-05-15", "ALL"),)),)}
    script = Script(pages={url: _page(url, "Example Fellowship")}, captures=captures, reads=reads)
    # The capture read returns the older cycle; the scripted read is keyed by final_url,
    # so give each capture its own year's decision through a side table.
    year_reads = {2025: _decision(stated_on="2025-03-04", deadlines=(("2025-05-16", "ALL"),)),
                  2024: _decision(stated_on="2024-03-05", deadlines=(("2024-05-17", "ALL"),))}
    seams = script.seams()

    def read(page):
        if page.captured_at:
            return (year_reads[int(page.captured_at[:4])],)
        return seams.read(page)

    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                           seams=replace(seams, read=read, crawl=lambda *a, **k: _empty_crawl()),
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    assert (verdict.state, verdict.step) == ("UPCOMING", "1b")


def test_a_wayback_lookup_is_made_once_and_cached_for_good():
    url = "https://f.example/award"
    stored_trail = [{"step": "1b", "url": f"{url}@2025", "outcome": "LOOKED", "note": ""},
                    {"step": "1b", "url": f"{url}@2024", "outcome": "LOOKED", "note": ""}]
    script = Script(pages={url: _page(url, "x")})
    meter = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=script.seams(), meter=meter,
                 stored=[], looked=stored_trail)
    assert not [c for c in script.calls if c[0] == "wayback"]


def test_a_current_register_cadence_is_step_1c_and_costs_nothing():
    from apps.funding.validity import RegisterCadence

    subject = replace(SUBJECT, cadence=RegisterCadence(open_month=3, deadline_month=5,
                                                       source="https://r.example",
                                                       verified_for_cycle=2026))
    verdict = _run(Script(pages={"https://f.example/award": _page(
        "https://f.example/award", "x")}), subject=subject)
    assert (verdict.state, verdict.step) == ("UPCOMING", "1c")


def test_the_hop_follows_an_own_domain_apply_link_and_withholds_every_other():
    url = "https://f.example/award"
    body = (b'<main><a href="https://apply.f.example/2027">Apply now</a>'
            b'<a href="https://portal.other.example/login">Application portal</a></main>')
    script = Script(pages={url: _page(url, "Example Fellowship", body=body),
                           "https://apply.f.example/2027": _page(
                               "https://apply.f.example/2027", "Apply by 15 January 2027")},
                    reads={"https://apply.f.example/2027": (
                        _decision(applies_to="2027", deadlines=(("2027-01-15", "ALL"),)),)})
    seams = replace(script.seams(), crawl=lambda *a, **k: _empty_crawl())
    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=seams,
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    assert (verdict.state, verdict.step) == ("OPEN", "2")
    assert ("fetch", "https://portal.other.example/login") not in script.calls
    assert any(t["outcome"] == "hop_withheld" for t in verdict.trail)


def test_search_runs_only_when_steps_0_to_2_found_nothing_and_brave_only_after_empty_exa():
    script = Script(pages={"https://f.example/award": _page("https://f.example/award", "x")})
    seams = replace(script.seams(), crawl=lambda *a, **k: _empty_crawl())
    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=seams,
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    kinds = [kind for kind, _ in script.calls]
    assert kinds.index("exa") < kinds.index("brave")
    assert verdict.step == "3" and verdict.state == "UNVERIFIED"
    [(_, query)] = [c for c in script.calls if c[0] == "exa"]
    assert query == "Example Fellowship 2027 call for applications deadline"


def test_no_search_query_ever_carries_anything_but_the_award_and_the_year():
    """Catalog path: there is no student here to leak -- pinned so one is never added."""
    import inspect

    from apps.research import cycle_verification

    source = inspect.getsource(cycle_verification._step_search)
    assert "profile" not in source and "student" not in source


# --- Task 11: persisting a verdict, withdrawal, the real seams -----------------


def _claim(opportunity, url):
    """One quote on one page, the shape the reader's writers leave behind."""
    from django.utils import timezone

    from apps.funding.models import (
        FundingOpportunityEvidenceClaim,
        OfficialEvidenceClaim,
        OfficialSource,
    )

    source, _ = OfficialSource.objects.get_or_create(
        canonical_url=url, defaults={"publisher": "f.example", "source_type": "FUNDER"})
    claim = OfficialEvidenceClaim.objects.create(
        source=source, claim="The Example Fellowship funds master's study.",
        evidence_strength="DIRECT", visibility="STUDENT_FACING",
        claim_class=OfficialEvidenceClaim.ClaimClass.FUNDING, last_checked_at=timezone.now())
    FundingOpportunityEvidenceClaim.objects.create(opportunity=opportunity, evidence_claim=claim)


def test_persisting_a_verdict_writes_state_step_cost_and_the_next_check():
    from apps.research.cycle_verification import persist_verdict

    opportunity = _opportunity()
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    meter = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    meter.run.spend("FIRECRAWL", 3)
    meter.add_search("exa", 0.0097)
    verdict = _run(Script(pages=DEAD), subject=SUBJECT)  # all own pages DEAD -> ENDED
    persist_verdict(row, verdict, meter=meter, today=TODAY)
    row.refresh_from_db()
    assert row.state == "ENDED" and row.page_removed and row.ladder_step == "0"
    assert row.cost_usd > 0 and row.cost_detail["credits"]["FIRECRAWL"] == 3
    assert row.cost_detail["searches"] == {"exa": 1}
    assert row.next_check_at.date() == TODAY + dt.timedelta(days=30)
    assert row.verified_at is not None and row.trail


def test_cost_accumulates_across_runs_and_an_incomplete_price_stays_incomplete():
    from apps.research.cycle_verification import persist_verdict
    from apps.research.model_cost import Usage

    row = FundingCycleVerification.objects.create(opportunity=_opportunity(),
                                                  intake_start_year=2027)
    verdict = _run(Script(pages=DEAD))
    first = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    first.run.spend("FIRECRAWL", 1)
    persist_verdict(row, verdict, meter=first, today=TODAY)
    once = row.cost_usd
    second = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    second.run.spend("FIRECRAWL", 1)
    second.models.record(Usage("openai", "no-such-model", "default", 10, 0, 0, 10))
    persist_verdict(row, verdict, meter=second, today=TODAY)
    row.refresh_from_db()
    assert row.cost_usd == 2 * once
    assert row.cost_complete is False  # an unpriced reading makes the total a floor


def test_a_changed_only_page_that_no_longer_describes_the_award_withdraws_it():
    from apps.research.cycle_verification import persist_verdict

    opportunity = _opportunity()
    opportunity.served = True
    opportunity.save()
    _claim(opportunity, "https://f.example/award")
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    verdict = replace(_run(Script()), own_page_silent=True, page_removed=False)
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY)
    opportunity.refresh_from_db()
    assert (opportunity.agreement, opportunity.served) == ("WITHDRAWN", False)
    assert opportunity.evidence_claims.count() == 1  # the quotes stay, as withdraw_unread's do


def test_a_reviewed_row_is_never_withdrawn_by_the_verifier():
    from apps.research.cycle_verification import persist_verdict

    opportunity = _opportunity()
    opportunity.review = "ACCEPTED"
    opportunity.save()
    _claim(opportunity, "https://f.example/award")
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    verdict = replace(_run(Script()), own_page_silent=True)
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY)
    opportunity.refresh_from_db()
    assert opportunity.agreement == "AGREED"


def test_a_row_another_page_also_supports_is_never_withdrawn_by_the_verifier():
    """withdraw_unread's own second rule: a vaguer page may not unserve what
    another page still states."""
    from apps.research.cycle_verification import persist_verdict

    opportunity = _opportunity()
    _claim(opportunity, "https://f.example/award")
    _claim(opportunity, "https://f.example/award/fees")
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    verdict = replace(_run(Script()), own_page_silent=True)
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY)
    opportunity.refresh_from_db()
    assert opportunity.agreement == "AGREED"


def test_a_subject_is_built_from_the_rows_own_quotes_and_its_judge_scope():
    from apps.research.cycle_verification import subject_for
    from apps.research.models import Organisation, OrganisationDomain

    org = Organisation.objects.create(primary_domain="f.example", name="Example Foundation",
                                      kind="PRIVATE_FOUNDATION", country_code="DE",
                                      found_via=["REGISTER"])
    OrganisationDomain.objects.create(organisation=org, registrable_domain="f-foundation.example")
    opportunity = FundingOpportunity.objects.create(
        canonical_key="read:holder_own:x:y:heading:i0_holder_award", name="Example Fellowship",
        family="PRIVATE_FOUNDATION", scope_type="HOLDER", agreement="AGREED",
        kind="I0_HOLDER_AWARD", organisation=org)
    _claim(opportunity, "https://www.f.example/award")
    subject = subject_for(opportunity)
    assert subject.own_urls == ("https://www.f.example/award",)
    assert subject.scope == "HOLDER_OWN" and subject.kind == "I0_HOLDER_AWARD"
    assert subject.domains == frozenset({"f.example", "f-foundation.example"})
    assert subject.primary_domain == "f.example"
    assert subject.ambiguous is False and subject.cadence is None


def test_stored_evidence_is_deduplicated_across_the_awards_intake_rows():
    """record_read_evidence writes the same entries onto every tracked row;
    handing all of them to the ladder unmerged would double the row's evidence
    on every run."""
    from apps.research.cycle_verification import stored_evidence

    opportunity = _opportunity()
    record_read_evidence(opportunity, _decision(deadlines=(("2027-01-15", "ALL"),)),
                         url="https://f.example/award", sha256="a" * 64, at=TODAY, today=TODAY)
    entries, looked = stored_evidence(opportunity)
    assert len(entries) == 1 and looked == []


class _Parser:
    pass


def _long_page(text):
    return _page("https://f.example/award", text,
                 body=f"<main><h2>Funding</h2><p>{text}</p></main>".encode())


def test_the_read_seam_pays_for_every_call_before_the_first_and_passes_the_meter(monkeypatch):
    from apps.research import cycle_verification
    from apps.research.funding_judge import FUNDING_READS, FundingReadResult
    from apps.research.model_cost import CostMeter, ReadingTier

    paid, seen = [], {}

    def fake_read_funding(parser, claude, **kwargs):
        seen.update(kwargs)
        return FundingReadResult(decisions=(_decision(),))

    monkeypatch.setattr(cycle_verification, "read_funding", fake_read_funding)
    meter = CostMeter()
    read = cycle_verification.funding_reader_for(
        _Parser(), _Parser(), pay=lambda n: paid.append(n) or True, source_id="s", meter=meter)
    decisions = read(_long_page("The scholarship covers tuition fees for the 2027 intake."))
    assert decisions == (_decision(),)
    assert paid == [FUNDING_READS * len(seen["chunks"])]
    assert seen["meter"] is meter and seen["tier"] is ReadingTier.STANDARD


def test_the_read_seam_makes_no_call_it_could_not_pay_for_in_full(monkeypatch):
    from apps.research import cycle_verification
    from apps.research.model_cost import CostMeter

    monkeypatch.setattr(cycle_verification, "read_funding",
                        lambda *a, **k: pytest.fail("an unpaid read was made"))
    read = cycle_verification.funding_reader_for(
        _Parser(), _Parser(), pay=lambda n: False, source_id="s", meter=CostMeter())
    assert read(_long_page("The scholarship covers tuition fees.")) == ()


def test_a_shell_page_is_never_read(monkeypatch):
    from apps.research import cycle_verification
    from apps.research.model_cost import CostMeter

    monkeypatch.setattr(cycle_verification, "read_funding",
                        lambda *a, **k: pytest.fail("a shell was read"))
    shell = _page("https://f.example/award", "",
                  body=b"<html><head><script>" + b"x" * 30_000 + b"</script></head>"
                       b"<body><div id='app'>scholarship</div></body></html>")
    read = cycle_verification.funding_reader_for(
        _Parser(), _Parser(), pay=lambda n: pytest.fail("a shell was paid for"),
        source_id="s", meter=CostMeter())
    assert read(shell) == ()


def test_the_real_seams_pay_through_the_platform_limiter_and_the_per_award_ceiling(settings):
    from django.core.cache import cache

    from apps.research.cycle_verification import _pay_for, build_seams

    cache.clear()
    settings.CYCLE_VERIFY_MODEL_CALLS_PER_HOUR = 2
    settings.CYCLE_VERIFY_MAX_USD_PER_AWARD = 0.40
    meter = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    seams = build_seams(meter, _Parser(), _Parser(), source_id="s", store=_Store())
    assert isinstance(seams, Seams) and isinstance(seams.store, _Store)
    assert _pay_for(meter)(2) is True
    assert _pay_for(meter)(1) is False  # the third call this hour is refused
    cache.clear()
    meter.run.spend("FIRECRAWL", 1000)  # $8.30 of fetches: past the per-award ceiling
    assert _pay_for(meter)(1) is False


# --- Review fixes (Tasks 6-10) --------------------------------------------------


def test_the_ladder_crawl_never_lets_the_vendor_leave_the_site(settings):
    """CLAUDE.md: no fetch vendor is ever pointed at a portal. With
    `allowExternalLinks` on, Firecrawl itself fetches an off-domain link whose
    path matches a year token -- before the ladder's own-domain filter ever
    sees the URL. The request body build_seams' crawl posts must forbid it."""
    import json

    from apps.research.cycle_verification import build_seams

    sent = []

    def post(url, body, headers):
        sent.append(json.loads(body))
        return 200, json.dumps({"success": True, "id": "job-1"}).encode(), {}

    def get(url, headers):
        payload = ({"errors": [], "robotsBlocked": []} if url.endswith("/errors")
                   else {"success": True, "status": "completed", "data": []})
        return 200, json.dumps(payload).encode(), {}

    settings.FIRECRAWL_API_KEY = "k"
    meter = Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000}))
    seams = build_seams(meter, _Parser(), _Parser(), source_id="s", store=_Store())
    seams.crawl("https://f.example/award", limit=15, tag="cycle-verify:2027",
                include_paths=("2027",), post=post, get=get, sleep=lambda _s: None)
    assert sent[0]["allowExternalLinks"] is False


def _stored_yes(url="https://f.example/award"):
    return entries_from_decision(
        _decision(applies_to="2027-2028", deadlines=(("2027-01-15", "ALL"),)),
        step="0", url=url, sha256="a" * 64, at=TODAY)


OTHER_AWARD = _decision(kind="I1_UNIVERSITY_WIDE", name="Another award")


@pytest.mark.parametrize(
    ("outcome", "reads", "silent"),
    [
        (Outcome.FETCHED, (OTHER_AWARD,), True),   # the page, read in full, is about something else
        (Outcome.FETCHED, (), False),              # the READER was silent, not the page
        (Outcome.ARCHIVED, (OTHER_AWARD,), False),  # a capture says nothing about the page now
        (Outcome.FETCHED_PARTIAL, (OTHER_AWARD,), False),
    ],
)
def test_own_page_silent_needs_a_full_live_read_that_returned_decisions(outcome, reads, silent):
    url = "https://f.example/award"
    page = replace(_page(url, "Example Fellowship"), outcome=outcome,
                   captured_at="2026-01-01" if outcome == Outcome.ARCHIVED else "")
    script = Script(pages={url: page}, reads={url: reads})
    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                           seams=replace(script.seams(), crawl=lambda *a, **k: _empty_crawl()),
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=_stored_yes())
    assert verdict.own_page_silent is silent


def test_a_page_stored_under_its_final_url_is_recognised_at_step_zero():
    """Stored entries carry the URL the page landed on, not the one requested."""
    requested, landed = "https://f.example/award", "https://f.example/award/"
    page = _page(landed, "x", Outcome.UNCHANGED)
    script = Script(pages={requested: page})
    verdict = _run(script, [{**e, "sha256": _digest(page)} for e in _stored_yes(landed)])
    assert (verdict.state, verdict.step) == ("OPEN", "0")
    assert not [c for c in script.calls if c[0] == "read"]


def test_a_changed_own_page_that_no_longer_describes_the_award_drops_its_live_entries():
    url = "https://f.example/award"
    capture = entries_from_decision(
        _decision(applies_to="2026-2027", deadlines=(("2026-01-15", "ALL"),)),
        step="1b", url=url, sha256="e" * 64, at=TODAY, captured_at="2025-04-01")[0]
    script = Script(pages={url: _page(url, "Example Fellowship")}, reads={url: (OTHER_AWARD,)})
    verdict = verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                           seams=replace(script.seams(), crawl=lambda *a, **k: _empty_crawl()),
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[*_stored_yes(), capture])
    assert [e["archived"] for e in verdict.entries] == [True]
    assert verdict.state != "OPEN"


def test_a_changed_own_page_whose_read_returned_nothing_keeps_its_entries():
    """A reader that refused, went unpaid or met a shell is not evidence."""
    url = "https://f.example/award"
    script = Script(pages={url: _page(url, "Example Fellowship")}, reads={})
    verdict = _run(script, _stored_yes())
    assert (verdict.state, verdict.step) == ("OPEN", "0")
    assert len(verdict.entries) == 1


def _to_wayback(script, meter):
    seams = replace(script.seams(), crawl=lambda *a, **k: _empty_crawl())
    return verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=seams, meter=meter,
                        stored=[], looked=[])


def test_wayback_is_not_asked_when_the_scrape_do_budget_is_already_spent():
    script = Script()
    verdict = _to_wayback(script, Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 0})))
    assert not [c for c in script.calls if c[0] == "wayback"]
    assert any(t["step"] == "1b" and t["outcome"] == "BUDGET" for t in verdict.trail)


def _refusal(url, outcome, reason):
    return replace(_page(url, "", outcome), reason=reason, body=b"", markdown="")


@pytest.mark.parametrize(
    ("outcome", "reason", "cached"),
    [
        (Outcome.BLOCKED, "archive_absent", True),
        (Outcome.BLOCKED, "archive_skew:2023-01-01", True),
        (Outcome.OFF_SITE, "archive_origin:https://x.example/", True),
        (Outcome.UNREACHABLE, "archive_unavailable", False),
        (Outcome.UNREACHABLE, "archive_unfetchable:timeout", False),
        (Outcome.BLOCKED, "archive_unfetchable:503", False),
    ],
)
def test_only_a_definite_wayback_answer_is_cached(outcome, reason, cached):
    url = "https://f.example/award"
    script = Script(captures={(url, 2025): _refusal(url, outcome, reason),
                              (url, 2024): _refusal(url, outcome, reason)})
    verdict = _to_wayback(script, Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})))
    again = Script()
    _ = verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                     seams=replace(again.seams(), crawl=lambda *a, **k: _empty_crawl()),
                     meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                     stored=[], looked=[t for t in verdict.trail if t["step"] == "1b"])
    asked = [c for c in again.calls if c[0] == "wayback"]
    assert (asked == []) is cached


def test_a_budget_note_from_an_earlier_run_is_retried():
    url = "https://f.example/award"
    stored_trail = [{"step": "1b", "url": f"{url}@2025", "outcome": "BUDGET", "note": ""}]
    script = Script()
    verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                 seams=replace(script.seams(), crawl=lambda *a, **k: _empty_crawl()),
                 meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                 stored=[], looked=stored_trail)
    assert ("wayback", f"{url}@2025") in script.calls


def test_stored_evidence_hands_back_only_definite_wayback_lookups():
    from apps.research.cycle_verification import stored_evidence

    opportunity = _opportunity()
    FundingCycleVerification.objects.create(
        opportunity=opportunity, intake_start_year=2027,
        trail=[{"step": "1b", "url": "u@2025", "outcome": "LOOKED", "note": "archive_absent"},
               {"step": "1b", "url": "u@2024", "outcome": "RETRY", "note": "archive_unavailable"}])
    _entries, looked = stored_evidence(opportunity)
    assert [t["url"] for t in looked] == ["u@2025"]


def test_step_three_without_a_primary_domain_searches_nothing():
    script = Script()
    subject = replace(SUBJECT, primary_domain="")
    verdict = verify_cycle(subject, intake_year=2027, today=TODAY,
                           seams=replace(script.seams(), crawl=lambda *a, **k: _empty_crawl()),
                           meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                           stored=[])
    assert not [c for c in script.calls if c[0] in {"exa", "brave"}]
    assert any(t["step"] == "3" and t["outcome"] == "SKIPPED"
               and t["note"] == "no primary domain" for t in verdict.trail)
    assert verdict.trail[-1]["outcome"] == "SKIPPED"


def test_an_entry_carries_the_judges_agreement():
    [entry] = entries_from_decision(_decision(agreement="UNAGREED"), step="0",
                                    url="https://f.example/a", sha256="b" * 64, at=TODAY)
    assert entry["agreement"] == "UNAGREED"


def test_a_subject_normalises_its_domains():
    from apps.research.cycle_verification import subject_for
    from apps.research.models import Organisation, OrganisationDomain

    org = Organisation.objects.create(primary_domain="F.Example.", name="Example Foundation",
                                      kind="PRIVATE_FOUNDATION", country_code="DE",
                                      found_via=["REGISTER"])
    OrganisationDomain.objects.create(organisation=org, registrable_domain="F-Foundation.Example.")
    opportunity = FundingOpportunity.objects.create(
        canonical_key="read:holder_own:x:y:heading:i0_holder_award", name="Example Fellowship",
        family="PRIVATE_FOUNDATION", scope_type="HOLDER", agreement="AGREED",
        kind="I0_HOLDER_AWARD", organisation=org)
    subject = subject_for(opportunity)
    assert subject.domains == frozenset({"f.example", "f-foundation.example"})
    assert subject.primary_domain == "f.example"


# --- Final-review fixes ---------------------------------------------------------


AMBIGUOUS = replace(SUBJECT, ambiguous=True, heading="example fellowship")
SIBLING = _decision(name="Example Fellowship for Women", heading="Example Fellowship for Women",
                    quotes=("The Example Fellowship for Women funds master's study.",))


def test_an_ambiguous_award_joins_a_relabelled_decision_by_its_heading():
    """`name` is a model's label and varies between reads; the heading is the
    row's identity (canonical_key), so a re-read naming it differently still joins."""
    relabelled = _decision(name="EF master's scholarship", quotes=("2027 call",))
    assert joins(relabelled, AMBIGUOUS) is True
    assert joins(SIBLING, AMBIGUOUS) is False


def test_a_relabelled_reread_of_an_ambiguous_awards_page_neither_silences_nor_withdraws_it():
    """The reviewer's repro: stored YES entries, a FETCHED page whose read returns
    this award under another `name` beside a sibling award."""
    from apps.research.cycle_verification import persist_verdict

    url = "https://f.example/award"
    opportunity = _opportunity()
    opportunity.served = True
    opportunity.save()
    _claim(opportunity, url)
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    relabelled = _decision(name="EF master's scholarship", applies_to="2027-2028",
                           deadlines=(("2027-01-15", "ALL"),), quotes=("2027 call",))
    script = Script(pages={url: _page(url, "Example Fellowship")},
                    reads={url: (relabelled, SIBLING)})
    verdict = _run(script, _stored_yes(), subject=AMBIGUOUS)
    assert verdict.own_page_silent is False
    assert verdict.state == "OPEN"
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY)
    opportunity.refresh_from_db()
    assert (opportunity.agreement, opportunity.served) == ("AGREED", True)


def test_page_silence_is_decided_without_names():
    """A same-kind, same-scope decision the ladder cannot place on this award
    still says the page describes an award of this kind: not silent, and the
    stored entries stay."""
    url = "https://f.example/award"
    unplaced = _decision(name="Something else", heading="Programmes", quotes=("2027 call",))
    script = Script(pages={url: _page(url, "Example Fellowship")}, reads={url: (unplaced,)})
    verdict = _run(script, _stored_yes(), subject=AMBIGUOUS)
    assert verdict.own_page_silent is False
    assert len(verdict.entries) == 1 and verdict.state == "OPEN"


@pytest.mark.parametrize(
    ("key", "heading"),
    [
        ("read:holder_own:x:y:heading:i0_holder_award", "heading"),
        ("read:program:12:funding: scholarships:i0_holder_award", "funding: scholarships"),
        ("read:holder_own:x:y::i0_holder_award", ""),
        ("read:example", ""),
        ("read:program:12:heading:another_kind", ""),  # the key is not this row's kind
    ],
)
def test_a_subject_carries_the_heading_parsed_from_the_canonical_key(key, heading):
    from apps.research.cycle_verification import subject_for

    opportunity = FundingOpportunity.objects.create(
        canonical_key=key, name="Example Fellowship", family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL", agreement="AGREED", kind="I0_HOLDER_AWARD")
    assert subject_for(opportunity).heading == heading


def test_a_page_whose_read_failed_is_read_again_when_it_comes_back_unchanged():
    """Run 1: the page changed, the read returned nothing -> the stale entries
    stay, READ_SILENT is noted. Run 2: the page is UNCHANGED since run 1. It
    must be read, not treated as already read on the strength of run-0 entries."""
    import hashlib

    url = "https://f.example/award"
    changed = _page(url, "Example Fellowship 2028")
    first = verify_cycle(SUBJECT, intake_year=2027, today=TODAY,
                         seams=replace(Script(pages={url: changed}).seams(),
                                       crawl=lambda *a, **k: _empty_crawl()),
                         meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                         stored=_stored_yes())
    assert any(t["step"] == "0" and t["outcome"] == "READ_SILENT" for t in first.trail)
    now_shut = _decision(offered="NO", applies_to="2027-2028", stated_on="2026-09-20",
                         suspension_quote="No Example Fellowship for 2027.")
    again = Script(pages={url: replace(changed, outcome=Outcome.UNCHANGED)},
                   reads={url: (now_shut,)})
    second = verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=again.seams(),
                          meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                          stored=first.entries, history=first.trail)
    assert ("read", url) in again.calls
    assert second.state == "SUSPENDED"
    assert {e["sha256"] for e in second.entries} == {hashlib.sha256(changed.body).hexdigest()}


def test_an_unchanged_page_last_read_with_evidence_is_not_read_again():
    url = "https://f.example/award"
    history = [{"step": "0", "url": url, "outcome": "evidence", "note": "1 decision(s)"}]
    script = Script(pages={url: _page(url, "x", Outcome.UNCHANGED)})
    verify_cycle(SUBJECT, intake_year=2027, today=TODAY, seams=script.seams(),
                 meter=Meter(SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})),
                 stored=_stored_yes(), history=history)
    assert ("read", url) not in script.calls


def test_persisting_keeps_evidence_the_reader_wrote_during_the_run():
    from apps.research.cycle_verification import persist_verdict

    opportunity = _opportunity()
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    verdict = _run(Script(), _stored_yes())
    # The reader writes while the ladder runs; `row` is now a stale object.
    record_read_evidence(opportunity, _decision(deadlines=(("2027-02-01", "ALL"),)),
                         url="https://f.example/other", sha256="9" * 64, at=TODAY, today=TODAY)
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY)
    row.refresh_from_db()
    assert {e["url"] for e in row.evidence} == {"https://f.example/award",
                                                "https://f.example/other"}


def test_persisting_does_not_resurrect_entries_the_ladder_dropped():
    from apps.research.cycle_verification import persist_verdict

    url = "https://f.example/award"
    opportunity = _opportunity()
    row = FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027,
                                                  evidence=_stored_yes())
    script = Script(pages={url: _page(url, "Example Fellowship")}, reads={url: (OTHER_AWARD,)})
    verdict = _run(script, _stored_yes())
    assert verdict.entries == []
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY)
    row.refresh_from_db()
    assert row.evidence == []


def test_an_award_reviewed_after_it_was_loaded_is_not_withdrawn():
    from apps.research.cycle_verification import persist_verdict

    opportunity = _opportunity()
    _claim(opportunity, "https://f.example/award")
    row = FundingCycleVerification.objects.select_related("opportunity").get(
        pk=FundingCycleVerification.objects.create(opportunity=opportunity,
                                                   intake_start_year=2027).pk)
    assert row.opportunity.review == ""  # loaded before the review below
    FundingOpportunity.objects.filter(pk=opportunity.pk).update(review="ACCEPTED")
    verdict = replace(_run(Script()), own_page_silent=True)
    persist_verdict(row, verdict, meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})),
                    today=TODAY)
    opportunity.refresh_from_db()
    assert opportunity.agreement == "AGREED"


def test_trimming_the_trail_keeps_every_permanent_wayback_answer():
    from apps.research.cycle_verification import persist_verdict

    looked = [{"step": "1b", "url": f"u@{2000 + i}", "outcome": "LOOKED", "note": ""}
              for i in range(3)]
    noise = [{"step": "0", "url": "u", "outcome": "UNCHANGED", "note": ""}] * 300
    row = FundingCycleVerification.objects.create(opportunity=_opportunity(),
                                                  intake_start_year=2027, trail=looked + noise)
    persist_verdict(row, _run(Script(pages=DEAD)),
                    meter=Meter(SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})), today=TODAY)
    row.refresh_from_db()
    assert len(row.trail) == 200
    assert [t for t in row.trail if t["outcome"] == "LOOKED"] == looked
    assert row.trail[-1]["outcome"] == "DEAD"  # the newest rows survive too
