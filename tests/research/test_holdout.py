"""The hold-out: drawn blind, frozen, scored by rules fixed before the draw."""

import csv
import json
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.research import holdout, wikidata
from apps.research.fetch import SweepBudget, fetch_page
from apps.research.fetch.firecrawl import REASON_RENDER_TIMEOUT
from apps.research.fetch.types import Attempt, FetchedPage, Outcome, VendorUnavailable
from apps.research.management.commands import draw_resolver_holdout, resolver_gate
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.diffbot import DiffbotEnhance
from apps.research.resolver import CallBudget, NameQuery, Resolver
from tests.research.test_names import vocab

_ENTITY = "http://www.wikidata.org/entity/"


def test_rows_group_by_item_and_skip_what_cannot_be_truth() -> None:
    # One row per item (GROUP BY ?item), its websites space-joined.
    rows = [
        {"item": f"{_ENTITY}Q1", "sites": "https://hust.edu.vn/ https://en.hust.edu.vn/",
         "native": "Đại học Bách khoa Hà Nội", "en": "Hanoi University of Science and Technology"},
        {"item": f"{_ENTITY}Q2", "sites": "https://www.facebook.com/x", "native": "Quỹ X"},
        {"item": f"{_ENTITY}Q3", "sites": "https://quy-y.org.vn/", "native": "Quỹ Y"},
        {"item": f"{_ENTITY}Q4", "sites": "https://www.facebook.com/y https://quy-z.vn/",
         "native": "Quỹ Z"},
    ]
    picked = holdout.pick(rows, n=5, taken=set(), stratum="university")
    assert [p.qid for p in picked] == ["Q1", "Q3", "Q4"]
    assert picked[0].truth == ("hust.edu.vn",)
    assert picked[2].truth == ("quy-z.vn",)  # the aggregator beside it is not truth
    assert picked[0].names == (
        "Đại học Bách khoa Hà Nội", "Hanoi University of Science and Technology",
    )


def test_pick_skips_catalogue_and_unkeyable_truth_and_what_another_stratum_took() -> None:
    rows = [
        {"item": f"{_ENTITY}Q1", "sites": "https://www.linkedin.com/company/x", "native": "A"},
        {"item": f"{_ENTITY}Q2", "sites": "http://192.0.2.7/", "native": "B"},
        {"item": f"{_ENTITY}Q3", "sites": "", "native": "C"},
        {"item": f"{_ENTITY}Q4", "sites": "https://taken.vn/", "native": "D"},
        {"item": f"{_ENTITY}Q5", "sites": "https://five.vn/", "native": "E"},
        {"item": f"{_ENTITY}Q6", "sites": "https://six.vn/", "native": "F"},
    ]
    taken = {"Q4"}
    picked = holdout.pick(rows, n=1, taken=taken, stratum="other")
    assert [p.qid for p in picked] == ["Q5"]
    assert taken == {"Q4", "Q5"}


def test_a_verdict_is_correct_wrong_or_unresolved() -> None:
    assert holdout.verdict("hust.edu.vn", ("hust.edu.vn",)) == "correct"
    assert holdout.verdict("", ("hust.edu.vn",)) == "unresolved"
    assert holdout.verdict("vnu.edu.vn", ("hust.edu.vn",)) == "wrong"


def test_the_pass_rule_is_the_one_fixed_before_the_draw() -> None:
    ok = holdout.Tally(correct=20, wrong=2, unresolved=28, directory_or_aggregator_wrong=0,
                       diffbot_wrong=1, n=50)
    assert holdout.thresholds(50) == (20, 2)  # the plan's absolute numbers, exactly
    assert holdout.passes(ok)
    assert not holdout.passes(ok._replace(wrong=3))
    assert not holdout.passes(ok._replace(correct=19))
    assert not holdout.passes(ok._replace(directory_or_aggregator_wrong=1))
    assert not holdout.passes(ok._replace(diffbot_wrong=2))


@pytest.mark.parametrize(("n", "min_correct", "max_wrong"), [
    # correct >= 40% rounded up, wrong <= 4% rounded down.
    (49, 20, 1), (48, 20, 1), (45, 18, 1), (26, 11, 1), (25, 10, 1), (24, 10, 0), (4, 2, 0),
])
def test_a_short_draw_scales_the_pass_rule(n, min_correct, max_wrong) -> None:
    assert holdout.thresholds(n) == (min_correct, max_wrong)
    at = holdout.Tally(correct=min_correct, wrong=max_wrong, unresolved=n - min_correct - max_wrong,
                       directory_or_aggregator_wrong=0, diffbot_wrong=0, n=n)
    assert holdout.passes(at)
    assert not holdout.passes(at._replace(correct=min_correct - 1))
    assert not holdout.passes(at._replace(wrong=max_wrong + 1))
    # The directory and Diffbot ceilings do not scale.
    assert not holdout.passes(at._replace(directory_or_aggregator_wrong=1))


def test_the_digest_changes_when_a_rule_changes(monkeypatch) -> None:
    before = holdout.frozen_digest("VN")
    assert holdout.frozen_digest("VN") == before
    monkeypatch.setattr(holdout, "_FROZEN_EXTRA", (b"a rule changed",))
    assert holdout.frozen_digest("VN") != before


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(holdout, "DATA_DIR", tmp_path)
    return tmp_path


def test_the_digest_covers_the_country_file_and_nothing_else_of_resolver_data(data_dir) -> None:
    absent = holdout.frozen_digest("VN")
    # Missing files hash as a marker, the same way every time.
    assert holdout.frozen_digest("VN") == absent
    assert holdout.digest_components("VN")["resolver_data/VN.json"] == holdout.ABSENT
    (data_dir / "kinds.json").write_text("{}", encoding="utf-8")
    with_kinds = holdout.frozen_digest("VN")
    assert with_kinds != absent
    (data_dir / "VN.json").write_text("{}", encoding="utf-8")
    vn = holdout.frozen_digest("VN")
    assert vn != with_kinds
    # Building Indonesia's vocabulary after the draw does not spend Vietnam.
    (data_dir / "ID.json").write_text("{}", encoding="utf-8")
    assert holdout.frozen_digest("VN") == vn
    assert holdout.frozen_digest("vn") == vn
    assert holdout.frozen_digest("ID") != vn


def test_the_digest_covers_what_the_resolver_reads_through(monkeypatch) -> None:
    parts = holdout.digest_components("VN")
    for name in ("names.py", "resolver.py", "vocabulary.py", "domains.py", "hosts.py",
                 "providers/tavily.py", "providers/diffbot.py", "classify._USABLE",
                 "tldextract", "resolver_data/kinds.json", "resolver_data/VN.json"):
        assert name in parts, name
    assert "classify.py" not in parts  # its value, not the whole classifier
    before = holdout.frozen_digest("VN")
    from apps.research.fetch.types import Outcome as O
    monkeypatch.setattr(holdout, "_USABLE", frozenset({O.FETCHED}))
    assert holdout.frozen_digest("VN") != before
    assert holdout.changed_components(parts, holdout.digest_components("VN")) == [
        "classify._USABLE"]
    monkeypatch.undo()
    monkeypatch.setattr(holdout, "_tldextract_version", lambda: "0.0.0")
    assert holdout.changed_components(parts, holdout.digest_components("VN")) == ["tldextract"]


@pytest.mark.parametrize("kw", [
    {"cls": "Q1 } UNION { ?x ?y ?z", "country_qid": "Q881", "lang": "vi"},
    {"cls": "Q1", "country_qid": "wd:Q881", "lang": "vi"},
    {"cls": "Q1", "country_qid": "Q881", "lang": 'vi") || true || ("'},
])
def test_the_draw_query_refuses_anything_not_shaped_like_its_values(kw) -> None:
    with pytest.raises(ValueError):
        holdout.draw_query(limit=10, **kw)


def test_the_draw_query_refuses_an_excluded_value_that_is_not_a_qid() -> None:
    with pytest.raises(ValueError):
        holdout.draw_query(cls="Q1", country_qid="Q881", lang="vi", limit=10,
                           exclude=("Q2", "Q3) || true || (?item"))


def test_the_draw_query_reads_every_non_deprecated_website_once_per_item() -> None:
    query = holdout.draw_query(cls="Q3918", country_qid="Q881", lang="vi", limit=10,
                               exclude=("Q7", "Q5"))
    # Every P856 statement not deprecated -- wdt: keeps only the best rank.
    assert "p:P856" in query and "ps:P856" in query and "wikibase:DeprecatedRank" in query
    assert "wdt:P856" not in query
    # One row per item, so LIMIT counts items, not (item, website) pairs.
    assert "GROUP BY ?item" in query and "GROUP_CONCAT(DISTINCT" in query
    assert "SAMPLE(?native)" in query
    assert "FILTER(?item NOT IN (wd:Q5, wd:Q7))" in query
    assert holdout.SALT in query and "LIMIT 10" in query
    assert "NOT IN" not in holdout.draw_query(cls="Q3918", country_qid="Q881", lang="vi",
                                              limit=10)


# -- the draw command, on a fake query service ------------------------------------

#: How many drawable items each class's fake answer holds. Missions fall three
#: short, so the top-up must supply exactly three.
_AVAILABLE = {"Q157031": 12, "Q163740": 10, "Q327333": 10, "Q3918": 10, "Q4830453": 5,
              "Q7843791": 2}


def _items(cls: str) -> list[dict[str, str]]:
    return [
        {"item": f"{_ENTITY}{cls}{i:03d}", "sites": f"https://{cls.lower()}-{i}.vn/",
         "native": f"{cls} {i}"}
        for i in range(_AVAILABLE[cls])
    ]


def _fake_sparql(asked: list[str], answers=None):
    """A query service that honours the query's NOT IN and LIMIT, in salted
    order -- `answers` maps a class to its rows, defaulting to `_items`."""
    def sparql(query: str) -> list[dict[str, str]]:
        asked.append(query)
        cls = query.split("wdt:P279* wd:", 1)[1].split()[0]
        if answers and cls in answers:
            rows = answers[cls]
        elif cls == holdout.TOP_UP[1]:
            # Two already drawn as foundations, one aggregator, then fresh items.
            rows = [
                {"item": f"{_ENTITY}Q157031000", "sites": "https://f0.vn/", "native": "F0"},
                {"item": f"{_ENTITY}Q157031001", "sites": "https://f1.vn/", "native": "F1"},
                {"item": f"{_ENTITY}Q900", "sites": "https://facebook.com/x", "native": "X"},
                *({"item": f"{_ENTITY}Q90{i}", "sites": f"https://o{i}.vn/", "native": f"O{i}",
                   "en": f"Other {i}"} for i in range(1, 6)),
            ]
        else:
            rows = _items(cls)
        excluded: set[str] = set()
        if "NOT IN (" in query:
            inside = query.split("NOT IN (", 1)[1].split(")", 1)[0]
            excluded = {q.strip().removeprefix("wd:") for q in inside.split(",")}
        limit = int(query.rsplit("LIMIT", 1)[1])
        return [r for r in rows if r["item"].rsplit("/", 1)[-1] not in excluded][:limit]
    return sparql


@pytest.fixture
def base_dir(settings, tmp_path, monkeypatch):
    settings.BASE_DIR = tmp_path
    monkeypatch.setattr(draw_resolver_holdout, "load_vocabulary",
                        lambda code: vocab(country_code=code, country_qid="Q881"))
    return tmp_path


def test_the_draw_fills_every_stratum_tops_up_the_short_one_and_records_the_digest(
    base_dir, monkeypatch
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(wikidata, "sparql", _fake_sparql(asked))
    call_command("draw_resolver_holdout", "--country", "VN", "--language", "vi")

    out = base_dir / "docs" / "research" / "resolver-holdout-vn.csv"
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 50
    by_stratum: dict[str, int] = {}
    for row in rows:
        by_stratum[row["stratum"]] = by_stratum.get(row["stratum"], 0) + 1
    assert by_stratum == {"foundation": 10, "nonprofit": 10, "agency": 10, "university": 10,
                          "business": 5, "mission": 2, "other": 3}
    assert len({row["qid"] for row in rows}) == 50  # the top-up never re-draws a foundation
    assert [r["qid"] for r in rows if r["stratum"] == "other"] == ["Q901", "Q902", "Q903"]
    assert {r["resolver_digest"] for r in rows} == {holdout.frozen_digest("VN")}
    assert {r["resolver_digest_parts"] for r in rows} == {
        json.dumps(holdout.digest_components("VN"), sort_keys=True)}
    assert {r["salt"] for r in rows} == {holdout.SALT}
    assert next(r for r in rows if r["qid"] == "Q901")["names"] == "O1 | Other 1"
    assert all("wd:Q881" in q and '"vi"' in q and holdout.SALT in q for q in asked)
    assert len(asked) == len(holdout.STRATA) + 1


def test_a_later_stratum_is_not_starved_by_items_an_earlier_one_took(
    base_dir, monkeypatch
) -> None:
    # Every foundation is also a nonprofit, and first in the salted order: a
    # LIMIT of one item per slot would hand back only foundations already
    # taken, and the nonprofit stratum would draw nothing.
    monkeypatch.setattr(draw_resolver_holdout, "_ITEMS_PER_SLOT", 1)
    foundations = _items("Q157031")[:10]
    nonprofits = [*foundations, *_items("Q163740")]
    asked: list[str] = []
    monkeypatch.setattr(wikidata, "sparql",
                        _fake_sparql(asked, answers={"Q163740": nonprofits}))
    call_command("draw_resolver_holdout", "--country", "VN", "--language", "vi")
    rows = list(csv.DictReader(
        (base_dir / "docs" / "research" / "resolver-holdout-vn.csv").open(encoding="utf-8")))
    assert [r["qid"] for r in rows if r["stratum"] == "nonprofit"] == [
        f"Q163740{i:03d}" for i in range(10)]
    # The first query excludes nothing; the second excludes the ten foundations.
    assert "NOT IN" not in asked[0]
    assert all(f"wd:Q157031{i:03d}" in asked[1] for i in range(10))


def test_a_short_draw_prints_its_scaled_thresholds(base_dir, monkeypatch) -> None:
    monkeypatch.setattr(wikidata, "sparql", _fake_sparql(
        [], answers={holdout.TOP_UP[1]: []}))
    out = StringIO()
    call_command("draw_resolver_holdout", "--country", "VN", "--language", "vi", stdout=out)
    # Missions fall three short and the top-up has nothing: 47 drawn.
    assert "n=47: correct >= 19, confident-wrong <= 1" in out.getvalue()


def test_the_draw_is_made_once_and_never_again(base_dir, monkeypatch) -> None:
    out = base_dir / "docs" / "research" / "resolver-holdout-vn.csv"
    out.parent.mkdir(parents=True)
    out.write_text("drawn\n", encoding="utf-8")
    monkeypatch.setattr(wikidata, "sparql", lambda q: pytest.fail("queried Wikidata"))
    with pytest.raises(CommandError, match="never re-drawn"):
        call_command("draw_resolver_holdout", "--country", "VN")
    assert out.read_text(encoding="utf-8") == "drawn\n"


def test_the_draw_refuses_a_language_that_is_not_one_before_any_query(
    base_dir, monkeypatch
) -> None:
    monkeypatch.setattr(wikidata, "sparql", lambda q: pytest.fail("queried Wikidata"))
    with pytest.raises(CommandError, match="language"):
        call_command("draw_resolver_holdout", "--country", "VN", "--language", 'vi"')


# -- the gate ------------------------------------------------------------------------


def test_adjudication_only_ever_turns_wrong_into_correct_on_evidence() -> None:
    assert holdout.adjudicate(
        resolved_landed_on="hust.edu.vn", truth=("hust.edu.vn",),
        truth_dead=False, resolved_title_names_it=False) == "correct"
    assert holdout.adjudicate(
        resolved_landed_on="new-site.vn", truth=("old-site.vn",),
        truth_dead=True, resolved_title_names_it=True) == "correct"
    assert holdout.adjudicate(
        resolved_landed_on="new-site.vn", truth=("old-site.vn",),
        truth_dead=False, resolved_title_names_it=True) == "wrong"
    assert holdout.adjudicate(
        resolved_landed_on="", truth=("old-site.vn",),
        truth_dead=True, resolved_title_names_it=False) == "wrong"


def _residue_resolver(diffbot) -> Resolver:
    return Resolver(vocabulary=vocab(), candidates=lambda name: [], tavily=CallBudget(5),
                    fetch=lambda url, **_: pytest.fail("fetched"), diffbot=diffbot,
                    use_wikidata_website=False)


def test_a_spent_diffbot_cap_in_the_gate_stops_the_run_never_drops_diffbot() -> None:
    # The resolver reads CallBudgetSpent in the residue rung as "not asked";
    # scored, that would be a Diffbot-less resolver passing as the real one.
    asked: list[str] = []
    diffbot = resolver_gate._GateDiffbot(lambda name: asked.append(name) or "", CallBudget(0))
    with pytest.raises(resolver_gate.GateIncomplete, match="cap"):
        _residue_resolver(diffbot).resolve(NameQuery(("Bilim ve Sanat Vakfı",), "VN"))
    assert asked == []


def test_a_diffbot_failure_in_the_gate_stops_the_run_and_is_never_paid_twice() -> None:
    asked: list[str] = []

    def homepage(name: str) -> str:
        asked.append(name)
        raise ProviderUnavailable("diffbot enhance failed")

    diffbot = resolver_gate._GateDiffbot(homepage, CallBudget(5))
    for _ in range(2):
        with pytest.raises(resolver_gate.GateIncomplete, match="diffbot enhance failed"):
            _residue_resolver(diffbot).resolve(NameQuery(("Bilim ve Sanat Vakfı",), "VN"))
    assert asked == ["Bilim ve Sanat Vakfı"]
    assert diffbot.budget.spent == 1


def _outage(url: str) -> FetchedPage:
    """What fetch_page returns when Firecrawl answered 429 through every
    back-off and scrape.do's rung could not answer either: the final outcome
    says only "unreachable", the trail says whose fault it was."""
    return FetchedPage(
        final_url=url, redirects=(), content_type="", body=b"", fetched_via="EGRESS",
        outcome=Outcome.RETRY_SCHEDULED, reason="unreachable",
        attempts=(
            Attempt(rung=1, vendor="FIRECRAWL", outcome=Outcome.UNREACHABLE,
                    reason="vendor_unavailable:firecrawl answered HTTP 429 -- vendor "
                           "throttled, retry later"),
            Attempt(rung=5, vendor="NONE", outcome=Outcome.RETRY_SCHEDULED,
                    reason="unreachable"),
        ),
    )


def test_a_fetch_vendor_outage_is_never_an_answer_about_the_host() -> None:
    fetched: list[str] = []
    memo = resolver_gate._GateFetch(lambda url: fetched.append(url) or _outage(url))
    with pytest.raises(resolver_gate.GateIncomplete, match="vendor_unavailable"):
        memo("https://hust.edu.vn/")
    # A host's own failure is an answer: FETCH_FAILED, scored as unresolved.
    host_down = _page("https://down.vn/", outcome=Outcome.RETRY_SCHEDULED)
    assert resolver_gate._GateFetch(lambda url: host_down)("https://down.vn/") is host_down
    # Firecrawl's 408 is its renderer losing to the page -- escalate=True, a
    # question about the host -- so it is scored like one.
    slow = replace(_outage("https://slow.vn/"), attempts=(Attempt(
        rung=1, vendor="FIRECRAWL", outcome=Outcome.UNREACHABLE,
        reason=f"vendor_unavailable:{REASON_RENDER_TIMEOUT}"),))
    assert resolver_gate._GateFetch(lambda url: slow)("https://slow.vn/") is slow
    # A later rung answering after a vendor failed is an answer too.
    served = replace(_page("https://ok.vn/", "OK"), attempts=_outage("x").attempts[:1])
    assert resolver_gate._GateFetch(lambda url: served)("https://ok.vn/") is served


@pytest.mark.django_db
def test_the_real_ladder_carries_the_vendor_failure_where_the_gate_reads_it() -> None:
    """The shape the gate reads is fetch_page's own, not a hand-built one."""
    def down(*args, **kwargs):
        raise VendorUnavailable("firecrawl answered HTTP 429 -- vendor throttled, retry later",
                                escalate=False)

    def scrapedo_down(*args, **kwargs):
        raise VendorUnavailable("SCRAPEDO_API_KEY is not set", escalate=False)

    page = fetch_page("https://hust.edu.vn/", budget=SweepBudget({"FIRECRAWL": 5, "SCRAPE_DO": 5}),
                      providers={"firecrawl": down, "scrapedo": scrapedo_down,
                                 "archive": lambda *a, **k: pytest.fail("archive")})
    assert page.outcome not in resolver_gate._ANSWERED
    with pytest.raises(resolver_gate.GateIncomplete, match="HTTP 429"):
        resolver_gate._GateFetch(lambda url: page)("https://hust.edu.vn/")


def test_adjudication_reads_the_homepage_the_resolver_read() -> None:
    fetched: list[str] = []

    def fetch_one(url: str) -> FetchedPage:
        fetched.append(url)
        return _page(url, "HUST")

    memo = resolver_gate._GateFetch(fetch_one)
    memo("https://www.hust.edu.vn/")  # the resolver's title fetch
    assert memo.homepage("hust.edu.vn").final_url == "https://www.hust.edu.vn/"
    assert memo.homepage("vnu.edu.vn").final_url == "https://vnu.edu.vn/"
    assert fetched == ["https://www.hust.edu.vn/", "https://vnu.edu.vn/"]


def _page(url: str, title: str = "", *, final_url: str = "", outcome=Outcome.FETCHED):
    body = f"<html><head><title>{title}</title></head></html>".encode() if title else b""
    return FetchedPage(final_url=final_url or url, redirects=(), content_type="text/html",
                       body=body, fetched_via="FIRECRAWL", outcome=outcome)


#: (qid, stratum, names, truth). Q1 is found by both of its names and Q2 by its
#: one, each through its title; Q3 is a wrong slug that the adjudication turns
#: around because its homepage lands on the truth; Q4 nothing answers, so
#: Diffbot is asked -- once, though both arms reach the residue.
_DRAWN = (
    ("Q1", "foundation", "Hrant Dink Vakfı | Hrant Dink Foundation", "hrantdink.org"),
    ("Q2", "foundation", "Kanserle Savaş Vakfı", "kanservakfi.org"),
    ("Q3", "university", "Deniz Yıldız Vakfı | Sea Star Foundation", "dyv.org"),
    ("Q4", "mission", "Zeytin Qarpuz Vakfı", "zq.org"),
)
_LISTS = {
    "Hrant Dink Vakfı": ["https://www.hrantdink.org/"],
    "Hrant Dink Foundation": ["https://www.hrantdink.org/"],
    "Kanserle Savaş Vakfı": ["https://kanservakfi.org/about"],
    "Deniz Yıldız Vakfı": ["https://denizyildizvakfi.org.tr/"],
    "Sea Star Foundation": [],
    "Zeytin Qarpuz Vakfı": [],
}
_PAGES = {
    "https://www.hrantdink.org/": _page("https://www.hrantdink.org/", "Hrant Dink Vakfı"),
    "https://kanservakfi.org/": _page("https://kanservakfi.org/", "Kanserle Savaş Vakfı"),
    "https://denizyildizvakfi.org.tr/": _page("https://denizyildizvakfi.org.tr/", "DYV",
                                              final_url="https://www.dyv.org/"),
    "https://dyv.org/": _page("https://dyv.org/", "DYV"),
}


def _holdout_csv(base: Path, digest: str, parts: dict[str, str] | None = None) -> Path:
    path = base / "docs" / "research" / "resolver-holdout-vn.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["qid", "stratum", "names", "truth", "salt", "resolver_digest",
                         "resolver_digest_parts"])
        for qid, stratum, names, truth in _DRAWN:
            writer.writerow([qid, stratum, names, truth, holdout.SALT, digest,
                             json.dumps(parts or {}, sort_keys=True)])
    return path


def _drawn_now(base: Path) -> Path:
    return _holdout_csv(base, holdout.frozen_digest("VN"), holdout.digest_components("VN"))


@pytest.fixture
def gate(settings, tmp_path, monkeypatch):
    settings.BASE_DIR = tmp_path
    settings.TAVILY_API_KEY = "t"
    settings.FIRECRAWL_API_KEY = "f"
    settings.SCRAPEDO_API_KEY = "s"
    asked: dict[str, list[str]] = {"tavily": [], "fetch": [], "diffbot": []}

    class FakeTavily:
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "t"

        def candidates(self, name: str) -> list[str]:
            asked["tavily"].append(name)
            return _LISTS[name]

    class FakeDiffbot:
        def __init__(self, *, token: str) -> None:
            # Exercises the real terms-freshness gate (DiffbotEnhance.__init__)
            # without a network call: get/sleep/clock are never used in __init__.
            DiffbotEnhance(token=token)

        def homepage(self, name: str) -> str:
            asked["diffbot"].append(name)
            return ""

    def fetch_page(url, *, purpose, tag, budget):
        assert (purpose, tag) == ("read", "resolver-gate") and budget is not None
        asked["fetch"].append(url)
        return _PAGES.get(url) or _page(url, outcome=Outcome.UNREACHABLE)

    monkeypatch.setattr(resolver_gate, "TavilyProvider", FakeTavily)
    monkeypatch.setattr(resolver_gate, "DiffbotEnhance", FakeDiffbot)
    monkeypatch.setattr(resolver_gate, "fetch_page", fetch_page)
    monkeypatch.setattr(resolver_gate, "load_vocabulary", lambda code: vocab())
    return tmp_path, asked


def test_the_gate_refuses_until_the_draw_has_been_made(gate) -> None:
    with pytest.raises(CommandError, match="draw is owed"):
        call_command("resolver_gate", "--country", "VN")


def test_the_gate_refuses_a_resolver_changed_since_the_draw(gate) -> None:
    base, asked = gate
    _holdout_csv(base, "0" * 64)
    with pytest.raises(CommandError, match="development data"):
        call_command("resolver_gate", "--country", "VN")
    assert not any(asked.values())


def test_a_digest_mismatch_names_the_component_that_moved(gate, monkeypatch) -> None:
    base, asked = gate
    parts = holdout.digest_components("VN")
    _holdout_csv(base, holdout.frozen_digest("VN"), parts)
    monkeypatch.setattr(holdout, "_tldextract_version", lambda: "0.0.0")
    with pytest.raises(CommandError, match=r"development data.*\btldextract\b"):
        call_command("resolver_gate", "--country", "VN")
    assert not any(asked.values())


def test_the_gate_runs_once(gate) -> None:
    base, asked = gate
    _drawn_now(base)
    results = base / "docs" / "research" / "resolver-holdout-vn-results.csv"
    results.write_text("scored\n", encoding="utf-8")
    with pytest.raises(CommandError, match="once"):
        call_command("resolver_gate", "--country", "VN")
    assert results.read_text(encoding="utf-8") == "scored\n"
    assert not any(asked.values())


@pytest.mark.parametrize("key", ["TAVILY_API_KEY", "FIRECRAWL_API_KEY", "SCRAPEDO_API_KEY"])
def test_the_gate_refuses_without_its_keys(gate, settings, key) -> None:
    base, asked = gate
    _drawn_now(base)
    setattr(settings, key, "")
    with pytest.raises(CommandError, match=key):
        call_command("resolver_gate", "--country", "VN")
    assert not any(asked.values())


def test_the_gate_refuses_diffbot_without_a_token_or_a_current_reading(gate, settings) -> None:
    base, asked = gate
    _drawn_now(base)
    settings.DIFFBOT_TOKEN = ""
    with pytest.raises(CommandError, match="DIFFBOT_TOKEN"):
        call_command("resolver_gate", "--country", "VN", "--diffbot")
    settings.DIFFBOT_TOKEN = "d"
    today = timezone.now().date()
    for read_on in ("", "not a date", (today - timedelta(days=32)).isoformat(),
                    (today + timedelta(days=1)).isoformat()):
        settings.DIFFBOT_TERMS_READ_ON = read_on
        with pytest.raises(CommandError, match="DIFFBOT_TERMS_READ_ON"):
            call_command("resolver_gate", "--country", "VN", "--diffbot")
    assert not any(asked.values())


def test_a_fetch_vendor_outage_mid_gate_is_incomplete_and_writes_nothing(
    gate, monkeypatch
) -> None:
    base, _ = gate
    _drawn_now(base)
    monkeypatch.setattr(resolver_gate, "fetch_page", lambda url, **_: _outage(url))
    with pytest.raises(CommandError, match="INCOMPLETE.*vendor_unavailable"):
        call_command("resolver_gate", "--country", "VN")
    assert not (base / "docs" / "research" / "resolver-holdout-vn-results.csv").exists()


def test_a_diffbot_failure_mid_gate_is_incomplete_and_writes_nothing(
    gate, settings, monkeypatch
) -> None:
    base, _ = gate
    _drawn_now(base)
    settings.DIFFBOT_TOKEN = "d"
    settings.DIFFBOT_TERMS_READ_ON = timezone.now().date().isoformat()

    class DownDiffbot:
        def __init__(self, *, token: str) -> None:
            pass

        def homepage(self, name: str) -> str:
            raise ProviderUnavailable("diffbot enhance failed")

    monkeypatch.setattr(resolver_gate, "DiffbotEnhance", DownDiffbot)
    with pytest.raises(CommandError, match="INCOMPLETE.*diffbot enhance failed"):
        call_command("resolver_gate", "--country", "VN", "--diffbot")
    assert not (base / "docs" / "research" / "resolver-holdout-vn-results.csv").exists()


def test_both_arms_score_on_one_set_of_responses(gate, settings) -> None:
    base, asked = gate
    _drawn_now(base)
    settings.DIFFBOT_TOKEN = "d"
    settings.DIFFBOT_TERMS_READ_ON = timezone.now().date().isoformat()
    out = StringIO()
    call_command("resolver_gate", "--country", "VN", "--diffbot", stdout=out)

    # Every name, URL and Diffbot question went out once, though both arms asked
    # the native names: the difference between the arms is the rule, never the
    # provider answering twice.
    for calls in asked.values():
        assert len(calls) == len(set(calls)), calls
    assert sorted(asked["tavily"]) == sorted(_LISTS)
    assert asked["diffbot"] == ["Zeytin Qarpuz Vakfı"]

    results = list(csv.DictReader(
        (base / "docs" / "research" / "resolver-holdout-vn-results.csv").open(encoding="utf-8")))
    got = {(r["arm"], r["qid"]): (r["domain"], r["verdict"]) for r in results}
    for arm in ("FULL", "NATIVE"):
        assert got[(arm, "Q1")] == ("hrantdink.org", "correct")
        assert got[(arm, "Q2")] == ("kanservakfi.org", "correct")
        assert got[(arm, "Q3")] == ("denizyildizvakfi.org.tr", "correct")  # adjudicated
        assert got[(arm, "Q4")] == ("", "unresolved")
    text = out.getvalue()
    assert "FULL: 3 / 0 / 1" in text and "NATIVE: 3 / 0 / 1" in text
    assert "diffbot 1 entities" in text
    # Four drawn: the rule scales to correct >= 2, wrong <= 0, and 3 / 0 passes.
    assert text.strip().splitlines()[-1].startswith("PASS Tally(correct=3, wrong=0")
    assert "n=4" in text.strip().splitlines()[-1]
