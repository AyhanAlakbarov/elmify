"""The ladder end to end on fakes: every rung, every reason, both budgets."""

from dataclasses import fields

import pytest

from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.resolver import (
    CallBudget,
    CallBudgetSpent,
    FetchBudgetSpent,
    NameQuery,
    Resolution,
    Resolver,
)
from apps.research.wikidata import WikidataMatch
from tests.research.test_names import vocab


def page(url: str, title: str, outcome=Outcome.FETCHED) -> FetchedPage:
    body = f"<html><head><title>{title}</title></head></html>".encode()
    return FetchedPage(final_url=url, redirects=(), content_type="text/html", body=body,
                       fetched_via="FIRECRAWL", outcome=outcome)


def resolver(*, lists=None, titles=None, wikidata=None, diffbot=None, tavily=10, **kw):
    fetched: list[str] = []

    def fetch(url, **_):
        fetched.append(url)
        title = (titles or {}).get(url)
        if title is None:
            return page(url, "", Outcome.UNREACHABLE)
        if title == "BUDGET":
            return page(url, "", Outcome.BUDGET)
        return page(url, title)

    r = Resolver(vocabulary=vocab(), candidates=lambda name: (lists or {}).get(name, []),
                 tavily=CallBudget(tavily), fetch=fetch, wikidata=wikidata, diffbot=diffbot, **kw)
    return r, fetched


def test_rung_zero_answers_before_any_call() -> None:
    r, fetched = resolver(tavily=0)
    got = r.resolve(NameQuery(("TÜRK EĞİTİM VAKFI",), "TR", contact_email="info@tev.org.tr"))
    assert (got.domain, got.via) == ("tev.org.tr", "EMAIL") and not fetched


def test_wikidata_s_website_is_taken_and_its_labels_join_the_names() -> None:
    match = WikidataMatch("Q1", ("https://www.hrantdink.org/",),
                          ("Hrant Dink Vakfı", "Hrant Dink Foundation"))
    r, _ = resolver(wikidata=lambda names: match, tavily=0)
    got = r.resolve(NameQuery(("Hrant Dink Vakfı",), "TR"))
    assert (got.domain, got.via, got.wikidata_qid) == ("hrantdink.org", "WIKIDATA", "Q1")
    assert got.names == ("Hrant Dink Vakfı", "Hrant Dink Foundation")


def test_a_one_token_name_never_spends_a_search() -> None:
    r, _ = resolver(tavily=0)
    assert r.resolve(NameQuery(("TEMA",), "TR")).reason == "ONE_TOKEN_NAME"


def test_tier_three_ships_without_a_fetch() -> None:
    r, fetched = resolver(lists={"Türk Silahlı Kuvvetlerini Güçlendirme Vakfı": ["https://www.tskgv.org.tr/"]})
    got = r.resolve(NameQuery(("Türk Silahlı Kuvvetlerini Güçlendirme Vakfı",), "TR"))
    assert (got.domain, got.via) == ("tskgv.org.tr", "SEARCH_SLUG") and not fetched


def test_the_best_candidate_is_checked_first() -> None:
    # v4's one rescue: kanservakfi.com (2.5) outscores kansersavascilari.org (2.0).
    name = "Kanserle Savaş Vakfı"
    r, fetched = resolver(
        lists={name: ["https://kansersavascilari.org/", "https://www.kanservakfi.com/"]},
        titles={"https://www.kanservakfi.com/": "Kanser Vakfı - Kanserle Savaş Vakfı",
                "https://kansersavascilari.org/": "Kanser Savaşçıları Derneği"},
    )
    got = r.resolve(NameQuery((name,), "TR"))
    assert (got.domain, got.via) == ("kanservakfi.com", "SEARCH_TITLE")
    assert fetched == ["https://www.kanservakfi.com/"]


def test_the_runner_up_gets_one_try_after_a_title_mismatch() -> None:
    # Both tier 2 at 2.0; rank breaks the tie, so the association's site is
    # checked first and refused on kind (Derneği against Vakfı).
    name = "Hrant Dink Vakfı"
    r, fetched = resolver(
        lists={name: ["https://hrant-dink-dernegi.org/", "https://www.hrantdink.org/"]},
        titles={"https://hrant-dink-dernegi.org/": "Hrant Dink Derneği",
                "https://www.hrantdink.org/": "Anasayfa - Hrant Dink Vakfı"},
    )
    got = r.resolve(NameQuery((name,), "TR"))
    assert (got.domain, got.via) == ("hrantdink.org", "SEARCH_TITLE")
    assert fetched == ["https://hrant-dink-dernegi.org/", "https://www.hrantdink.org/"]


def test_a_failed_fetch_is_unresolved_never_accepted() -> None:
    # hrantdink.org is tier 2 (two distinctive tokens), so it must be fetched;
    # a tier-3 label (hrantdinkvakfi = the slug) would ship unverified instead.
    r, _ = resolver(lists={"Hrant Dink Vakfı": ["https://hrantdink.org/"]})
    assert r.resolve(NameQuery(("Hrant Dink Vakfı",), "TR")).reason == "FETCH_FAILED"


def test_a_redirect_to_another_domain_is_another_body_s_title() -> None:
    name = "Hrant Dink Vakfı"
    r, _ = resolver(lists={name: ["https://hrantdink.org/"]})
    r.fetch = lambda url, **_: page("https://www.agos.com.tr/", "Hrant Dink Vakfı")
    assert r.resolve(NameQuery((name,), "TR")).reason == "TITLE_MISMATCH"


def test_diffbot_answers_the_residue_through_the_same_title_check() -> None:
    name = "Bilim ve Sanat Vakfı"
    r, _ = resolver(lists={name: []}, diffbot=lambda n: "https://www.bisav.org.tr",
                    titles={"https://www.bisav.org.tr/": "BİSAV - Bilim ve Sanat Vakfı"})
    got = r.resolve(NameQuery((name,), "TR"))
    assert (got.domain, got.via, got.diffbot_asked) == ("bisav.org.tr", "DIFFBOT", True)


def test_a_query_may_forbid_diffbot() -> None:
    asked = []
    r, _ = resolver(lists={"Bilim ve Sanat Vakfı": []}, diffbot=lambda n: asked.append(n) or "")
    got = r.resolve(NameQuery(("Bilim ve Sanat Vakfı",), "TR", allow_diffbot=False))
    assert got.reason == "NO_CANDIDATE" and not asked and not got.diffbot_asked


def test_a_directory_only_answer_says_so() -> None:
    name = "Embassy of Italy in Astana"
    r, _ = resolver(lists={name: ["https://embassies.info/italy-astana"]})
    assert r.resolve(NameQuery((name,), "KZ")).reason == "DIRECTORY"


def test_budgets_stop_the_run_instead_of_writing_a_reason() -> None:
    r, _ = resolver(lists={"Hrant Dink Vakfı": []}, tavily=0)
    with pytest.raises(CallBudgetSpent):
        r.resolve(NameQuery(("Hrant Dink Vakfı",), "TR"))
    r, _ = resolver(lists={"Hrant Dink Vakfı": ["https://hrantdink.org/"]},
                    titles={"https://hrantdink.org/": "BUDGET"})
    with pytest.raises(FetchBudgetSpent):
        r.resolve(NameQuery(("Hrant Dink Vakfı",), "TR"))


def test_a_resolution_has_no_field_a_provider_artefact_could_travel_in() -> None:
    """Only a URL is read from a provider, and only a registrable domain leaves."""
    assert {f.name for f in fields(Resolution)} == {
        "domain", "via", "reason", "wikidata_qid", "names", "diffbot_asked"}


def test_a_budget_stop_verifying_diffbot_s_answer_says_diffbot_was_asked() -> None:
    """Review of Task 9: the entity is paid for; the caller still owes the meter."""
    name = "Bilim ve Sanat Vakfı"
    r, _ = resolver(lists={name: []}, diffbot=lambda n: "https://www.bisav.org.tr",
                    titles={"https://www.bisav.org.tr/": "BUDGET"})
    with pytest.raises(FetchBudgetSpent) as stopped:
        r.resolve(NameQuery((name,), "TR"))
    assert stopped.value.diffbot_asked
