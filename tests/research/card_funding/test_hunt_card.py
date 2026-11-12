import datetime as dt
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.research.card_engine import Limit
from apps.research.card_engine.screen import Screen
from apps.research.card_funding.card import AwardHunt, Track
from apps.research.card_funding.entry import read_page
from apps.research.card_funding.hunt import hunt_card, hunt_owed
from apps.research.card_funding.seek import CAP, Vendors
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.hosts import registrable_domain
from apps.research.providers.base import ProviderUnavailable

from .oracle import Oracle

# "Merit Award" is all generic words since Task 3's rulings, so code could never attach it: the
# fixture names a nameable award instead. Each hunted page opens with its site's own heading, so
# the award's heading is L1 on every page, as on the start page (the oracle answers award_L1).
AWARD = "Nizami Award"
START = "https://beu.edu.az/scholarships"
PROGRAM = SimpleNamespace(id=uuid4(), country_code="AZ")
TODAY = dt.date(2026, 10, 14)
PAGES = {
    START: b"""<html><body><main><h1>Scholarships</h1><p>Our scholarships.</p>
<h2>Nizami Award</h2><p>Tuition waiver for international master students.</p>
<p><a href="/nizami/calendar">Application calendar</a>
<a href="https://edu.gov.az/nizami-countries">Eligible countries</a>
<a href="/rector">Rector's Scholarship</a> <a href="/news">News</a></p></main></body></html>""",
    "https://beu.edu.az/nizami/calendar": b"""<html><body><main><h1>Baku Engineering University</h1>
<h2>Nizami Award calendar</h2>
<p>Applications close on 1 June 2027.</p></main></body></html>""",
    "https://edu.gov.az/nizami-countries": b"""<html><body><main>
<h1>Ministry of Science and Education</h1><h2>Nizami Award: eligibility</h2>
<p>Citizens of Azerbaijan and Kazakhstan may apply.</p></main></body></html>""",
    "https://beu.edu.az/other-dates": b"""<html><body><main><h1>Rector's Scholarship</h1>
<p>Applications close on 5 May 2027.</p></main></body></html>""",
}
ANSWERS = {
    "award_L1": ("yes", AWARD),
    "internationals": ("yes", "international master students"),
    "target_level": ("master", "master students"),
    "role_d1": ("application_deadline", "Applications close on 1 June 2027."),
    "eligible_p1": ("yes", "Citizens of Azerbaijan and Kazakhstan may apply."),
    "eligible_p2": ("yes", "Citizens of Azerbaijan and Kazakhstan may apply."),
    "place_basis": ("citizenship", "Citizens of"),
}


@pytest.fixture(autouse=True)
def _keys(settings, monkeypatch):
    settings.OPENROUTER_API_KEY = "test-openrouter-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


def _fetch(pages):
    asked = []

    def fetch(url, **kwargs):
        asked.append(url)
        if url not in pages:
            return FetchedPage(final_url=url, redirects=(), content_type="", body=b"",
                               fetched_via="FIRECRAWL", outcome=Outcome.UNREACHABLE)
        return FetchedPage(final_url=url, redirects=(), content_type="text/html",
                           body=pages[url], fetched_via="FIRECRAWL")
    fetch.asked = asked
    return fetch


def _clear(section, *, limit, timeout_s=None):
    return Screen("clear", section.texts())


def _vendors(mapped=(), fail=()):
    bought = []

    def stage(name, urls, cost):
        def call(*args):
            bought.append(name)
            if name in fail:
                raise ProviderUnavailable(f"{name} down")
            return tuple(urls), cost
        return call
    vendors = Vendors(stage("map", mapped, 1.0), stage("guided", (), 0.01),
                      stage("navigator", (), 40.0))
    return vendors, bought


def _prove(url):
    return {"beu.edu.az": True, "edu.gov.az": True}.get(registrable_domain(url))


def _limit():
    return Limit("card-hunt-test", uuid4(), 500, 3600)


def _start(oracle, fetch):
    return read_page(PROGRAM, START, limit=_limit(), today=TODAY, transport=oracle, fetch=fetch,
                     screen_page=_clear)


def _hunt(card, oracle, fetch, vendors, prove=_prove, **kwargs):
    return hunt_card(card, PROGRAM, limit=_limit(), today=TODAY, transport=oracle, fetch=fetch,
                     screen_page=_clear, vendors=vendors, prove=prove, **kwargs)


def test_the_hunt_finds_a_cards_missing_facts_on_proven_pages_that_name_the_award():
    oracle, fetch = Oracle(ANSWERS), _fetch(PAGES)
    card = _start(oracle, fetch)
    [award] = card.tracks[0].awards
    assert award.fields["nationality"].hold == "needs_hunt" and hunt_owed(card, TODAY)
    vendors, bought = _vendors(mapped=("https://beu.edu.az/other-dates",))
    hunted = _hunt(card, oracle, fetch, vendors)
    [award] = hunted.tracks[0].awards
    [deadline] = award.fields["dates"].values
    assert (deadline.value.date.month, deadline.source) == (6, "https://beu.edu.az/nizami/calendar")
    [who] = award.fields["nationality"].values  # another official domain, printed as a link
    assert (who.value.eligible, who.source) == ({"AZ", "KZ"}, "https://edu.gov.az/nizami-countries")
    assert award.fields["target_level"] == card.tracks[0].awards[0].fields["target_level"]
    assert award.fields["benefits"].state == "not_stated"  # looked for, found nowhere
    assert award.holds == () and not hunt_owed(hunted, TODAY)
    [report] = hunted.hunts
    assert report.award == AWARD
    assert report.fields == ("benefits", "dates", "nationality")
    assert report.pages == ("https://beu.edu.az/nizami/calendar",
                            "https://edu.gov.az/nizami-countries", "https://beu.edu.az/other-dates")
    assert report.attached == report.pages[:2]  # the Rector's page names another award
    assert bought == ["map"] and dict(report.spend) == {"map_credits": 1.0}
    assert report.unproven == ()
    assert hunted.cost_usd > card.cost_usd and len(hunted.calls) > len(card.calls)
    assert fetch.asked.count(START) == 2  # the read, then the hunt's own fetch for its links


def test_the_hunt_reads_at_most_six_extra_pages_per_award():
    links = "".join(f'<a href="/nizami/calendar-{n}">Calendar {n}</a>' for n in range(CAP + 3))
    pages = {START: PAGES[START].replace(b"<a href=\"/news\">News</a>", links.encode())}
    oracle, fetch = Oracle(ANSWERS), _fetch(pages)
    card = _start(oracle, fetch)
    vendors, _ = _vendors()
    hunted = _hunt(card, oracle, fetch, vendors)
    [report] = hunted.hunts
    assert len(report.pages) == CAP and report.attached == ()
    assert len(fetch.asked) == 2 + CAP  # the read, the hunt's start fetch, six leads
    [award] = hunted.tracks[0].awards
    # Ruling P1: every lead failed to fetch, so nothing was searched -- the pointer stays held,
    # never "every country but the host" (the plan's test expected `shown` here)
    assert (award.fields["nationality"].state, award.fields["nationality"].hold) == (
        "held", "needs_hunt")


def _no_country_page(prove_gov):
    """The start page and its calendar only: the countries link sits on a domain `prove_gov`
    judges, so no page that names the award lists any country."""
    oracle, fetch = Oracle(ANSWERS), _fetch(PAGES)
    card = _start(oracle, fetch)
    return card, oracle, fetch, (lambda url: prove_gov if "edu.gov.az" in url else _prove(url))


def test_every_country_but_the_host_is_shown_only_when_the_search_ran_to_the_end():
    card, oracle, fetch, prove = _no_country_page(False)  # checked, not recognised: no lead
    vendors, _ = _vendors()
    hunted = _hunt(card, oracle, fetch, vendors, prove=prove)
    [report] = hunted.hunts
    assert report.attached == ("https://beu.edu.az/nizami/calendar",) and report.unproven == ()
    nationality = hunted.tracks[0].awards[0].fields["nationality"]
    assert nationality.state == "shown" and nationality.values[0].value.excluded == {"AZ"}


def test_a_failed_stage_means_not_searched_never_nothing_found():
    card, oracle, fetch, prove = _no_country_page(False)
    vendors, bought = _vendors(fail=("map",))
    hunted = _hunt(card, oracle, fetch, vendors, prove=prove)
    [report] = hunted.hunts
    assert bought == ["map"] and dict(report.spend) == {"map_failed": 1}
    nationality = hunted.tracks[0].awards[0].fields["nationality"]
    assert (nationality.state, nationality.hold) == ("held", "needs_hunt")


def test_a_page_cut_by_its_deadline_means_not_searched():
    card, oracle, fetch, prove = _no_country_page(False)
    vendors, _ = _vendors()
    hunted = _hunt(card, oracle, fetch, vendors, prove=prove, page_deadline_s=0.0)
    [report] = hunted.hunts
    assert report.pages and report.attached == ()  # read, cut before any reader was asked
    nationality = hunted.tracks[0].awards[0].fields["nationality"]
    assert (nationality.state, nationality.hold) == ("held", "needs_hunt")


def test_a_card_with_nothing_to_hunt_or_nothing_read_is_returned_as_it_was():
    oracle, fetch = Oracle(ANSWERS), _fetch({START: b"<html></html>"})
    unread = _start(oracle, fetch)
    assert unread.outcome.startswith("unreadable") and not hunt_owed(unread, TODAY)
    vendors, bought = _vendors()
    assert _hunt(unread, oracle, fetch, vendors) is unread
    assert bought == []


def test_a_card_whose_start_page_could_not_be_fetched_is_recorded_and_not_owed_again():
    oracle = Oracle(ANSWERS)
    card = _start(oracle, _fetch(PAGES))
    vendors, bought = _vendors()
    hunted = _hunt(card, oracle, _fetch({}), vendors)
    assert hunted.hunts == (AwardHunt(AWARD, ("benefits", "dates", "nationality"), (), (),
                                      (), (), "start_failed"),)
    assert hunted.tracks == card.tracks and bought == []
    assert hunt_owed(card, TODAY) and not hunt_owed(hunted, TODAY)


def test_a_domain_never_checked_is_reported_for_its_check():
    oracle, fetch = Oracle(ANSWERS), _fetch(PAGES)
    card = _start(oracle, fetch)
    vendors, _ = _vendors()
    hunted = _hunt(card, oracle, fetch, vendors,
                   prove=lambda url: True if "beu.edu.az" in url else None)
    [report] = hunted.hunts
    assert report.unproven == ("edu.gov.az",)
    assert "https://edu.gov.az/nizami-countries" not in report.pages
    nationality = hunted.tracks[0].awards[0].fields["nationality"]  # owed a check: not searched
    assert (nationality.state, nationality.hold) == ("held", "needs_hunt")


def test_a_start_site_not_recognised_is_not_searched():
    oracle, fetch = Oracle(ANSWERS), _fetch(PAGES)
    card = _start(oracle, fetch)
    vendors, bought = _vendors()
    hunted = _hunt(card, oracle, fetch, vendors, prove=lambda url: False)
    [report] = hunted.hunts
    assert report.pages == () and report.unproven == () and bought == []
    nationality = hunted.tracks[0].awards[0].fields["nationality"]  # never "hunt_not_found"
    assert (nationality.state, nationality.hold) == ("held", "needs_hunt")


def _calendars(count):
    """The start page with `count` ranked calendar PDFs printed ahead of its countries link."""
    links = "".join(f'<a href="/nizami/application-deadline-calendar-{n}.pdf">Application '
                    f"deadline calendar {n}</a>" for n in range(count))
    pages = {**PAGES, START: PAGES[START].replace(b'<a href="/news">News</a>', links.encode())}
    pages.update({f"https://beu.edu.az/nizami/application-deadline-calendar-{n}.pdf":
                  PAGES["https://beu.edu.az/nizami/calendar"] for n in range(count)})
    return pages


def test_a_lead_the_cap_left_unread_means_not_searched():
    """F-I1: six calendars fill the cap ahead of the "Eligible countries" page (AZ and KZ); a
    calendar names the award and gives no list, so a complete search would show every country
    but the host. The list was never read: the pointer stays needs_hunt."""
    oracle, fetch = Oracle(ANSWERS), _fetch(_calendars(CAP))
    card = _start(oracle, fetch)
    vendors, _ = _vendors()
    hunted = _hunt(card, oracle, fetch, vendors)
    [report] = hunted.hunts
    assert len(report.pages) == CAP and report.attached
    assert "https://edu.gov.az/nizami-countries" not in report.pages
    nationality = hunted.tracks[0].awards[0].fields["nationality"]
    assert (nationality.state, nationality.hold) == ("held", "needs_hunt")


def test_the_caller_sets_the_pages_this_cycle_has_left():
    """F-I4: slice 3 passes the remainder of the per-cycle cap; a spent cap fetches nothing."""
    oracle, fetch = Oracle(ANSWERS), _fetch(PAGES)
    card = _start(oracle, fetch)
    vendors, bought = _vendors()
    [report] = _hunt(card, oracle, fetch, vendors, cap=1).hunts
    assert report.pages == ("https://beu.edu.az/nizami/calendar",) and report.reason == ""
    asked = len(fetch.asked)
    vendors, bought = _vendors()
    spent = _hunt(card, oracle, fetch, vendors, cap=0)
    assert spent.hunts == (AwardHunt(AWARD, ("benefits", "dates", "nationality"), (), (), (), (),
                                     "cap_spent"),)
    assert spent.tracks == card.tracks and len(fetch.asked) == asked and bought == []
    assert not hunt_owed(spent, TODAY)


def test_the_record_says_why_nothing_was_searched():
    """F-I4: an unrecognised, an unchecked and an unfetchable start page, and an award code
    cannot name, each leave a record slice 3 can tell apart."""
    oracle, fetch = Oracle(ANSWERS), _fetch(PAGES)
    card = _start(oracle, fetch)
    for prove, reason in ((lambda url: False, "start_unrecognised"),
                          (lambda url: None, "start_unproven")):
        vendors, bought = _vendors()
        [report] = _hunt(card, oracle, fetch, vendors, prove=prove).hunts
        assert (report.reason, report.pages, bought) == (reason, (), []), reason
    [report] = _hunt(card, oracle, fetch, _vendors()[0], prove=lambda url: None).hunts
    assert report.unproven == ("beu.edu.az",)  # owed its check
    [award] = card.tracks[0].awards
    unnamed = replace(card, tracks=(Track("", (replace(award, name="Scholarships"),)),))
    [report] = _hunt(unnamed, oracle, fetch, _vendors()[0]).hunts
    assert (report.reason, report.pages) == ("unnameable", ())
    [report] = _hunt(card, oracle, fetch, _vendors()[0]).hunts
    assert report.reason == ""  # searched


HOP = "https://beu.edu.az/nizami/eligibility"


def _hop_pages(link):
    """The countries link printed on the calendar page, not on the start page."""
    calendar = "https://beu.edu.az/nizami/calendar"
    return {START: PAGES[START].replace(
                b'<a href="https://edu.gov.az/nizami-countries">Eligible countries</a>', b""),
            calendar: PAGES[calendar].replace(
                b"</main>", f'<p><a href="{link}">Eligible countries</a></p></main>'.encode()),
            HOP: PAGES["https://edu.gov.az/nizami-countries"]}


def test_a_proven_link_on_a_read_page_is_read_and_attached():
    oracle, fetch = Oracle(ANSWERS), _fetch(_hop_pages(HOP))
    card = _start(oracle, fetch)
    hunted = _hunt(card, oracle, fetch, _vendors()[0])
    [report] = hunted.hunts
    assert HOP in report.pages and HOP in report.attached
    [who] = hunted.tracks[0].awards[0].fields["nationality"].values
    assert (who.value.eligible, who.source) == ({"AZ", "KZ"}, HOP)


def test_an_unchecked_domain_on_a_read_page_is_reported():
    elsewhere = "https://scholar.gov.kz/nizami-countries"
    oracle, fetch = Oracle(ANSWERS), _fetch(_hop_pages(elsewhere))
    card = _start(oracle, fetch)
    hunted = _hunt(card, oracle, fetch, _vendors()[0])
    [report] = hunted.hunts
    assert report.unproven == ("scholar.gov.kz",) and elsewhere not in fetch.asked
    nationality = hunted.tracks[0].awards[0].fields["nationality"]
    assert (nationality.state, nationality.hold) == ("held", "needs_hunt")


def test_a_quarantined_pages_links_are_never_followed():
    """F-I4: a page D8 judged hostile does not steer what the cap is spent on."""
    oracle, fetch = Oracle(ANSWERS), _fetch(_hop_pages(HOP))
    card = _start(oracle, fetch)

    def screen(section, *, limit, timeout_s=None):
        if any("calendar" in text for text in section.texts()):
            return Screen("quarantined", section.texts())
        return _clear(section, limit=limit)
    hunted = hunt_card(card, PROGRAM, limit=_limit(), today=TODAY, transport=oracle,
                       fetch=fetch, screen_page=screen, vendors=_vendors()[0], prove=_prove)
    [report] = hunted.hunts
    assert report.pages == ("https://beu.edu.az/nizami/calendar",)
    assert HOP not in fetch.asked


def test_two_awards_sharing_a_lead_fetch_it_once():
    second = b"""<h2>Rector's Scholarship</h2><p>A tuition waiver for top master students.</p>
<p><a href="/nizami/calendar">Application calendar</a></p></main>"""
    pages = {**PAGES, START: PAGES[START].replace(b"</main>", second)}
    answers = {**ANSWERS, "award_L2": ("yes", "Rector's Scholarship")}
    oracle, fetch = Oracle(answers), _fetch(pages)
    card = _start(oracle, fetch)
    assert [a.name for t in card.tracks for a in t.awards] == [AWARD, "Rector's Scholarship"]
    hunted = _hunt(card, oracle, fetch, _vendors()[0])
    assert len(hunted.hunts) == 2
    assert all("https://beu.edu.az/nizami/calendar" in h.pages for h in hunted.hunts)
    assert fetch.asked.count("https://beu.edu.az/nizami/calendar") == 1
