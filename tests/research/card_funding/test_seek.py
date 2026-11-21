from collections import Counter

import pytest

from apps.research.card_funding import seek
from apps.research.card_funding.seek import Vendors, find_leads, links, rank
from apps.research.fetch.types import FetchedPage
from apps.research.providers.base import ProviderUnavailable
from apps.research.sitejob import Stage

START = "https://beu.edu.az/scholarships/merit"
BODY = b"""<html><body>
<a href="/news/2026">News</a>
<a href="/apply">How to apply</a>
<a href="/merit/eligible-countries">Eligible countries</a>
<a href="/docs/rules.pdf">Rules (PDF)</a>
<a href="https://edu.gov.az/decree-2026.pdf">Decree</a>
<a href="https://blog.example.com/deadline-tips">Application deadline tips</a>
<a href="mailto:office@beu.edu.az">Mail us</a>
</body></html>"""


def _page(body=BODY, url=START):
    return FetchedPage(final_url=url, redirects=(), content_type="text/html", body=body,
                       fetched_via="FIRECRAWL")


def _prove(verdicts):
    """A Part-B stand-in: registrable domain -> True, False or None (never checked)."""
    from apps.research.hosts import registrable_domain

    return lambda url: verdicts.get(registrable_domain(url))


class Stub:
    """Vendors that answer from a script and count what was bought."""

    def __init__(self, mapped=(), guided=(), navigated=(), fail=()):
        self.mapped, self.guided_urls, self.navigated, self.fail = mapped, guided, navigated, fail
        self.bought: list[str] = []

    def vendors(self):
        def stage(name, urls, cost):
            def call(*args):
                self.bought.append(name)
                if name in self.fail:
                    raise (self.fail[name] if isinstance(self.fail, dict)
                           else ProviderUnavailable(f"{name} down"))
                return tuple(urls), cost
            return call
        return Vendors(stage("map", self.mapped, 1.0), stage("guided", self.guided_urls, 0.01),
                       stage("navigator", self.navigated, 40.0))


def test_a_pages_links_are_ranked_by_the_hunted_facts_words_and_documents():
    found = links(_page())
    assert [lead.url for lead in found][:2] == ["https://beu.edu.az/news/2026",
                                                "https://beu.edu.az/apply"]
    assert all(lead.stage == Stage.DOCUMENTS for lead in found)
    assert "mailto:office@beu.edu.az" not in {lead.url for lead in found}
    ranked = [lead.url for lead in rank(found, frozenset({"nationality"}))]
    assert ranked[0] == "https://beu.edu.az/merit/eligible-countries"  # eligib + countr
    assert "https://beu.edu.az/news/2026" not in ranked  # names no hunted fact: never a lead
    assert {"https://beu.edu.az/docs/rules.pdf", "https://edu.gov.az/decree-2026.pdf"} <= set(
        ranked)  # a document is a lead whatever its words


def test_another_official_domain_counts_only_through_a_link_and_only_when_proven():
    stub = Stub(mapped=("https://beu.edu.az/merit/calendar", "https://other.edu.az/calendar"))
    spend: Counter[str] = Counter()
    unproven: set[str] = set()
    leads = find_leads(_page(), "Merit Award", frozenset({"dates"}), lang="en",
                       vendors=stub.vendors(), spend=spend, unproven=unproven,
                       prove=_prove({"beu.edu.az": True, "edu.gov.az": True,
                                     "other.edu.az": True}))
    urls = [lead.url for lead in leads]
    assert "https://edu.gov.az/decree-2026.pdf" in urls  # printed by the proven site
    assert "https://beu.edu.az/merit/calendar" in urls
    assert "https://other.edu.az/calendar" not in urls  # a map lead off the site: dropped
    assert "https://blog.example.com/deadline-tips" not in urls
    assert unproven == {"example.com"}  # never checked: counted for its check, not followed
    assert stub.bought == ["map"] and spend == Counter({"map_credits": 1.0})


def test_the_dear_stages_are_bought_only_when_the_cheaper_found_nothing():
    stub = Stub(guided=(), navigated=("https://beu.edu.az/merit/2027",
                                      "https://www.aggregator.example/merit",
                                      "https://beu.edu.az/merit/2027"))  # a vendor repeats itself
    spend: Counter[str] = Counter()
    leads = find_leads(_page(b"<html><body></body></html>"), "Merit Award",
                       frozenset({"dates"}), lang="en", vendors=stub.vendors(), spend=spend,
                       unproven=set(), prove=_prove({"beu.edu.az": True}))
    assert stub.bought == ["map", "guided", "navigator"]
    assert [(lead.url, lead.stage) for lead in leads] == [
        ("https://beu.edu.az/merit/2027", Stage.NAVIGATOR)]  # the open web cut to the site
    assert spend["navigator_credits"] == 40.0


def test_a_failed_stage_is_counted_and_never_reads_as_no_pages():
    stub = Stub(guided=("https://beu.edu.az/merit/deadline",), fail=("map",))
    spend: Counter[str] = Counter()
    leads = find_leads(_page(b"<html><body></body></html>"), "Merit Award",
                       frozenset({"dates"}), lang="en", vendors=stub.vendors(), spend=spend,
                       unproven=set(), prove=_prove({"beu.edu.az": True}))
    assert spend["map_failed"] == 1 and stub.bought == ["map", "guided"]
    assert [lead.url for lead in leads] == ["https://beu.edu.az/merit/deadline"]


def test_an_unproven_start_site_hunts_nowhere():
    stub = Stub(mapped=("https://beu.edu.az/merit/calendar",))
    unproven: set[str] = set()
    leads = find_leads(_page(), "Merit Award", frozenset({"dates"}), lang="en",
                       vendors=stub.vendors(), spend=Counter(), unproven=unproven,
                       prove=_prove({}))
    assert leads == [] and stub.bought == [] and "beu.edu.az" in unproven


@pytest.mark.django_db
def test_part_b_reads_the_domains_recognised_verdict_and_nothing_else():
    from tests.research.provenance_helpers import make_body, recognise

    recognise(make_body("beu.edu.az"), "beu.edu.az")
    assert seek.proven("https://www.beu.edu.az/merit/rules.pdf") is True
    assert seek.proven("https://edu.gov.az/decree.pdf") is None  # never checked
    assert seek.proven("https://merit.github.io/page") is False  # a hosting platform


def test_every_term_row_names_a_field_the_hunt_looks_for():
    from apps.research.card_funding.hunt import WHEN_EMPTY

    rows = seek.term_rows()
    assert rows and {field for field, _, _ in rows} <= {"*", *WHEN_EMPTY}
    assert all(term == seek.fold(term) for _, term, _ in rows)  # folded once, at load
    assert len({(f, t) for f, t, _ in rows}) == len(rows)


def test_the_brief_names_the_award_and_the_facts_and_asks_for_urls_only():
    brief = seek.brief("Merit Award", frozenset({"dates", "holder_kind"}))
    assert '"Merit Award"' in brief and "application dates" in brief
    assert "URLs only" in brief and len(brief) < 1_000
    assert "its conditions and details" in brief  # holder_kind has no phrase of its own
    long = seek.brief("x" * 500, frozenset({"dates"}))
    assert f'"{"x" * 200}"' in long and "x" * 201 not in long  # page text is cut, not sent whole


def test_hunt_terms_csv_covers_the_round_two_languages():
    import csv

    from apps.research.card_funding.hunt import WHEN_EMPTY

    langs = {"en", "de", "fr", "es", "it", "nl", "ko", "ja", "zh", "az", "tr", "ru", "kk"}
    with seek.HUNT_TERMS_FILE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and all(r["language"] in langs and r["field"] in {"*", *WHEN_EMPTY}
                        and r["term"].strip() for r in rows)
    assert {r["language"] for r in rows} == langs


def test_a_term_in_a_script_without_spaces_matches_inside_a_word_and_latin_at_word_starts():
    page = _page("""<html><body><a href="/a">奨学金募集要項</a>
<a href="/b">Burs başvurusu</a><a href="/c">Reapply later</a></body></html>""".encode())
    assert [lead.url.rsplit("/", 1)[1] for lead in rank(links(page), frozenset())] == ["a", "b"]


def test_a_real_stage_without_its_key_fails_as_a_vendor_failure(settings):
    settings.FIRECRAWL_API_KEY = ""
    settings.SEARCH_API_KEY = ""
    real = seek.vendors()
    for call in (lambda: real.map(START, ["apply"]),
                 lambda: real.guided(START, "x", "beu.edu.az"),
                 lambda: real.navigator(START, "x")):
        with pytest.raises(seek.VENDOR_FAILURES):
            call()


def test_a_target_level_left_unsaid_follows_the_form_and_the_rules_pdf():
    """Peer rule (owner-relayed 2026-10-14): before the level is left unsaid, the application
    form or the rules PDF one link away is read: a check of 19 Turkish foundations found the
    level only in an application form, and two kept their rules in a PDF."""
    page = _page(b"""<html><body><a href="/contacts">Contacts</a>
<a href="/apply-online">Apply online</a>
<a href="/forms/application.docx">Application form</a>
<a href="/rules.pdf">Scholarship rules</a></body></html>""")
    assert [lead.url.rsplit("/", 1)[1] for lead in rank(links(page), frozenset({"target_level"}))
            ] == ["application.docx", "rules.pdf", "apply-online"]


def test_the_navigator_cut_drops_a_real_off_site_domain_and_always_policy_buys_it(settings):
    settings.FETCH_NAVIGATOR_POLICY = "always"
    stub = Stub(mapped=("https://beu.edu.az/merit/calendar",),
                navigated=("https://www.studyportals.com/merit-deadline",
                           "https://beu.edu.az/merit/deadline"))
    unproven: set[str] = set()
    leads = find_leads(_page(), "Merit Award", frozenset({"dates"}), lang="en",
                       vendors=stub.vendors(), spend=Counter(), unproven=unproven,
                       prove=_prove({"beu.edu.az": True, "edu.gov.az": True}))
    urls = [lead.url for lead in leads]
    assert stub.bought == ["map", "navigator"]  # bought although the cheaper stages found pages
    assert "https://beu.edu.az/merit/deadline" in urls
    assert "https://www.studyportals.com/merit-deadline" not in urls
    assert "studyportals.com" not in unproven  # cut by domain, never sent to Part B


def test_a_vendor_url_with_a_fragment_is_the_page_without_it():
    stub = Stub(guided=(START + "#apply", "https://beu.edu.az/merit/deadline#top",
                        "https://beu.edu.az/merit/deadline"))
    leads = find_leads(_page(b"<html><body></body></html>"), "Merit Award",
                       frozenset({"dates"}), lang="en", vendors=stub.vendors(), spend=Counter(),
                       unproven=set(), prove=_prove({"beu.edu.az": True}))
    assert [lead.url for lead in leads] == ["https://beu.edu.az/merit/deadline"]


def test_a_failed_firecrawl_stage_is_counted_with_the_spend_it_made():
    from apps.research.fetch.site import FirecrawlSiteError

    error = FirecrawlSiteError("/map answered HTTP 400")
    error.credits = 1
    stub = Stub(guided=("https://beu.edu.az/merit/deadline",), fail={"map": error})
    spend: Counter[str] = Counter()
    find_leads(_page(b"<html><body></body></html>"), "Merit Award", frozenset({"dates"}),
               lang="en", vendors=stub.vendors(), spend=spend, unproven=set(),
               prove=_prove({"beu.edu.az": True}))
    assert spend["map_failed"] == 1 and spend["map_credits"] == 1
    assert stub.bought == ["map", "guided"]


def test_the_map_searches_in_the_sites_language_first_in_composed_form():
    words = seek.map_words(frozenset({"dates"}), "ko")
    assert len(words) == seek.MAP_WORDS
    assert words[:3] == ["일정", "마감", "기간"]  # Hangul syllables, not the folded jamo
    korean = {"일정", "마감", "기간", "신청", "모집", "요강", "서류"}
    assert set(words[:7]) == korean and words[7] not in korean
    assert seek.map_words(frozenset({"dates"}), "en")[0] == "deadline"


def test_the_navigators_reading_never_reaches_a_log(monkeypatch, settings, caplog):
    import json

    from apps.research.fetch import site

    payload = {"success": True, "creditsUsed": 40, "data": {"pages": [
        {"url": "https://beu.edu.az/merit/2027", "kind": "faq", "why": "MARKER-why-text"}]}}

    def post(url, body, headers):
        return 200, json.dumps(payload).encode(), {}

    monkeypatch.setattr(seek, "agent", lambda **kw: site.agent(post=post, **kw))
    settings.FIRECRAWL_API_KEY = "k"
    caplog.set_level("DEBUG")
    stub = Stub()
    real = seek.vendors()
    leads = find_leads(_page(b"<html><body></body></html>"), "Merit Award",
                       frozenset({"dates"}), lang="en",
                       vendors=Vendors(stub.vendors().map, stub.vendors().guided, real.navigator),
                       spend=Counter(), unproven=set(), prove=_prove({"beu.edu.az": True}))
    assert [lead.url for lead in leads] == ["https://beu.edu.az/merit/2027"]
    assert not any("MARKER" in record.getMessage() for record in caplog.records)


@pytest.mark.django_db
def test_a_waiting_verdict_is_queued_and_a_rejected_or_unconfirmed_one_is_not_usable():
    from apps.research.models import Organisation
    from tests.research.provenance_helpers import make_body, recognise

    recognise(make_body("wait.edu.az"), "wait.edu.az", "not_evaluated")
    recognise(make_body("load.edu.az"), "load.edu.az", "register_not_loaded")
    recognise(make_body("absent.edu.az"), "absent.edu.az", "absent_from_register")
    rejected = make_body("gone.edu.az")
    recognise(rejected, "gone.edu.az")
    Organisation.objects.filter(pk=rejected.pk).update(status=Organisation.Status.REJECTED)
    unproven: set[str] = set()
    for domain in ("wait.edu.az", "load.edu.az", "absent.edu.az", "gone.edu.az"):
        assert not seek.usable(f"https://{domain}/merit", seek.proven, unproven), domain
    assert unproven == {"wait.edu.az", "load.edu.az"}  # slice 3 queues their check
