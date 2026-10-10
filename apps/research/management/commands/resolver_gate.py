"""Score the resolver on its blind hold-out (build item 8, Task 11). PASS/FAIL.

Refuses a resolver whose digest differs from the one the hold-out was drawn
against, a hold-out that has not been drawn, and a hold-out already scored:
it runs ONCE. A budget running out mid-gate is INCOMPLETE, never a partial
score -- and so is a vendor failing under it. The resolver is built for a
sweep, where a Diffbot outage means "not asked" and a fetch the vendor could
not make means FETCH_FAILED; scored, either would turn an outage into
unresolved rows and a hold-out spent on a resolver that was not the one
drawn. So the gate wraps both in its own exception (GateIncomplete), one the
resolver does not catch.

Two arms on the same responses (rule 6): FULL (every drawn name, rule 4) and
NATIVE (the native label only) share one memoised Tavily cache, one fetch
cache and one Diffbot cache, so the difference between them is the rule and
never provider variance -- and each cap counts real calls only, never the
second arm's cache hits. Wikidata's website rung is off in both: its P856 is
the truth.

Prints the table and writes docs/research/resolver-holdout-<cc>-results.csv;
the reading goes in docs/superpowers/research/ by hand (Task 12). The Diffbot
entities it spends are not on RegisterEntry.diffbot_asked_at: subtract them
from the month's allowance by hand.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Callable, Hashable, Sequence
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.research import holdout
from apps.research.domains import is_catalogue
from apps.research.fetch import CATALOG_ROLE_NOTE, VENDOR_UNAVAILABLE, SweepBudget, fetch_page
from apps.research.fetch.firecrawl import REASON_RENDER_TIMEOUT
from apps.research.fetch.types import SERVED, FetchedPage, Outcome
from apps.research.hosts import registrable_domain
from apps.research.names import tokens
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.diffbot import DiffbotEnhance
from apps.research.providers.tavily import TavilyProvider
from apps.research.resolver import (
    CallBudget,
    CallBudgetSpent,
    FetchBudgetSpent,
    NameQuery,
    Resolver,
    page_titles,
)
from apps.research.vocabulary import VocabularyMissing, load_vocabulary

from .draw_resolver_holdout import holdout_path

_ARMS = ("FULL", "NATIVE")
#: Pages a fetch may be read from: the adjudication's "lands on" needs a page
#: that actually landed -- a refusal's final_url is only the URL asked.
_LANDED = frozenset({Outcome.FETCHED, Outcome.FETCHED_PARTIAL, Outcome.UNCHANGED})
#: Outcomes that are an answer whoever gave it: bytes, or the origin's (or
#: our own) refusal that no other vendor would change (fetch._TERMINAL).
#: Anything else with a vendor failure in its trail was never a question the
#: host answered.
_ANSWERED = SERVED | {Outcome.UNCHANGED, Outcome.DEAD, Outcome.INVALID, Outcome.OFF_SITE}
#: Firecrawl credits, the arithmetic for --firecrawl-credits' default. Per
#: drawn row at worst: FULL verifies up to 2 search picks plus Diffbot's one
#: answer (3); NATIVE's picks are drawn from a subset of the same lists, so
#: at most 2 new hosts; adjudication reads the resolver's own homepage from
#: the cache (0-1) and each truth homepage (~2). 8 x 50 = 400, and a shell
#: re-rendered with actions (rung 2) is one more credit -- so 500, ~$0.42.
#: The old 200 covered the expected case (~160) and not the worst, and
#: running out is INCOMPLETE: the money spent up to there buys nothing.
_FIRECRAWL_CREDITS = 500
#: scrape.do: rung 3 is 1 credit and rung 4 is 25, bought only when a host
#: beat Firecrawl. 2,500 is 100 residential fetches, ~$0.29.
_SCRAPEDO_CREDITS = 2_500


class GateIncomplete(Exception):
    """A vendor failed under the gate. Deliberately not ProviderUnavailable,
    CallBudgetSpent or a SourceBlocked: the resolver catches the first two in
    its residue rung and reads a failed fetch as FETCH_FAILED, and a gate
    that scored either would be scoring an outage."""


def _vendor_outage(page: FetchedPage) -> str:
    """The vendor failure behind a page no one answered, or "". Firecrawl's
    408 is excluded: it is its renderer losing to THIS page, which fetch_page
    escalates as a question about the host, and the gate scores it as one."""
    if page.outcome in _ANSWERED:
        return ""
    for attempt in page.attempts:
        if (attempt.reason.startswith(VENDOR_UNAVAILABLE)
                and REASON_RENDER_TIMEOUT not in attempt.reason):
            return attempt.reason
    return ""


class _GateFetch:
    """One fetch per URL across both arms and the adjudication (rule 6).

    A budget refusal stops the run (FetchBudgetSpent, as the resolver does),
    and so does a vendor outage (GateIncomplete) -- neither is cached, and
    neither is an answer about the host."""

    def __init__(self, fetch_one: Callable[[str], FetchedPage]) -> None:
        self._fetch_one = fetch_one
        self.pages: dict[str, FetchedPage] = {}

    def __call__(self, url: str) -> FetchedPage:
        if url not in self.pages:
            page = self._fetch_one(url)
            if page.outcome == Outcome.BUDGET:
                raise FetchBudgetSpent(page.reason or "fetch budget spent")
            if outage := _vendor_outage(page):
                raise GateIncomplete(f"fetch vendor failed on {url}: {outage}")
            self.pages[url] = page
        return self.pages[url]

    def homepage(self, domain: str) -> FetchedPage:
        """The homepage the resolver already read for this registrable domain
        (it fetches `https://{host}/`, often a www. host), else the bare one:
        the adjudication judges the page the resolver saw, for no new credit."""
        for url in self.pages:
            if registrable_domain(url) == domain:
                return self(url)
        return self(f"https://{domain}/")


class _GateDiffbot:
    """Diffbot, shared by both arms and capped at one entity per drawn row.

    Its failures are GateIncomplete: the resolver would read
    ProviderUnavailable as "asked, nothing found" and CallBudgetSpent as "not
    asked", and a gate that scored either would be scoring a resolver without
    its residue rung. A failure is cached too, so the same name is never paid
    for twice even if a caller retries."""

    def __init__(self, homepage: Callable[[str], str], budget: CallBudget) -> None:
        self._homepage, self.budget = homepage, budget
        self._answers: dict[str, str | GateIncomplete] = {}

    def __call__(self, name: str) -> str:
        if name not in self._answers:
            if self.budget.spent >= self.budget.limit:
                raise GateIncomplete(f"diffbot cap of {self.budget.limit} entities spent")
            self.budget.spend()
            try:
                self._answers[name] = self._homepage(name)
            except ProviderUnavailable as error:
                self._answers[name] = GateIncomplete(f"diffbot: {error}")
        answer = self._answers[name]
        if isinstance(answer, GateIncomplete):
            raise answer
        return answer


def _memo[K: Hashable, V](
    fn: Callable[[K], V], budget: CallBudget | None = None
) -> Callable[[K], V]:
    """Same answer for the same key in both arms (rule 6) -- and a cap that
    counts only real calls, never the second arm's cache hits. A call that
    raises is not cached: it answered nothing."""
    cache: dict[K, V] = {}

    def call(key: K) -> V:
        if key not in cache:
            if budget is not None:
                budget.spend()
            cache[key] = fn(key)
        return cache[key]

    return call


def _names(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(n.strip() for n in row["names"].split(" | ") if n.strip())


class Command(BaseCommand):
    help = "Score the resolver on its blind hold-out and print PASS or FAIL." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", default="VN")
        parser.add_argument("--diffbot", action="store_true")
        parser.add_argument("--tavily-credits", type=int, default=160)
        parser.add_argument(
            "--firecrawl-credits", type=int, default=_FIRECRAWL_CREDITS,
            help="Worst case per drawn row: 3 FULL + 2 new NATIVE + 1 adjudication + ~2 "
                 "truth homepages = 8, x 50 = 400, plus rung-2 re-renders: 500 (~$0.42).")
        parser.add_argument(
            "--scrapedo-credits", type=int, default=_SCRAPEDO_CREDITS,
            help="Rung 3 is 1 credit, rung 4 (residential) 25: 2,500 is 100 rung-4 fetches.")

    def handle(self, *args: Any, **options: Any) -> None:
        code = options["country"].upper()
        source = holdout_path(code)
        if not source.exists():
            raise CommandError(
                f"{source} does not exist: the hold-out draw is owed "
                f"(manage.py draw_resolver_holdout --country {code}, once, after the "
                "resolver and its vocabulary are committed)"
            )
        out = source.with_name(f"resolver-holdout-{code.lower()}-results.csv")
        if out.exists():
            raise CommandError(f"{out} exists: a hold-out is scored once, never re-scored")
        with source.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise CommandError(f"{source} holds no drawn rows")
        if {r["resolver_digest"] for r in rows} != {holdout.frozen_digest(code)}:
            raise CommandError("the resolver changed since the hold-out was drawn: this set is "
                               "development data now; draw a fresh country (plan Task 12)"
                               + self._what_moved(rows[0], code))
        # Every key before any spend: the resolver would read a missing fetch
        # key as a host that could not be fetched, and score it.
        if not settings.TAVILY_API_KEY:
            raise CommandError("TAVILY_API_KEY (or SEARCH_API_KEY) is not set")
        # fetch_page's ladder is Firecrawl then scrape.do (rungs 3-4, and the
        # archive rung fetches through it): without its key every page
        # Firecrawl cannot read stops the gate, rather than being scored as the
        # production ladder would score it.
        for key in ("FIRECRAWL_API_KEY", "SCRAPEDO_API_KEY"):
            if not getattr(settings, key):
                raise CommandError(f"{key} is not set")
        try:
            vocab = load_vocabulary(code)
        except VocabularyMissing as error:
            raise CommandError(f"no resolver vocabulary for {code}: {error}") from error

        budget = SweepBudget({"FIRECRAWL": options["firecrawl_credits"],
                              "SCRAPE_DO": options["scrapedo_credits"]})
        tavily = TavilyProvider(api_key=settings.TAVILY_API_KEY)
        shared_tavily = CallBudget(options["tavily_credits"])
        candidates = _memo(tavily.candidates, shared_tavily)

        def fetch_one(url: str) -> FetchedPage:
            return fetch_page(url, purpose="read", tag="resolver-gate", budget=budget)

        # One fetch per URL across both arms and the adjudication.
        fetch = _GateFetch(fetch_one)
        diffbot: _GateDiffbot | None = None
        if options["diffbot"]:
            if not settings.DIFFBOT_TOKEN:
                raise CommandError("DIFFBOT_TOKEN is not set")
            # The terms-freshness check (spec 6.2) lives in DiffbotEnhance.__init__.
            try:
                enhance = DiffbotEnhance(token=settings.DIFFBOT_TOKEN)
            except ValueError as exc:
                raise CommandError(str(exc)) from None
            # One entity per drawn row, shared by both arms (both ask the
            # native name). Running out, or failing, stops the gate.
            diffbot = _GateDiffbot(enhance.homepage, CallBudget(len(rows)))

        results: list[dict[str, Any]] = []
        try:
            for arm in _ARMS:
                # The Resolver's own Tavily cap is unbounded here: `candidates`
                # already spends `shared_tavily`, on real calls only.
                resolver = Resolver(
                    vocabulary=vocab, candidates=candidates, tavily=CallBudget(10**6),
                    fetch=lambda url, **_: fetch(url), budget=budget,
                    use_wikidata_website=False, diffbot=diffbot,
                )
                for row in rows:
                    names = _names(row)
                    if arm == "NATIVE":
                        names = names[:1]
                    got = resolver.resolve(NameQuery(names, code))
                    truth = tuple(row["truth"].split())
                    verdict = holdout.verdict(got.domain, truth)
                    if verdict == "wrong":
                        verdict = self._adjudicate(got.domain, truth, names, fetch)
                    results.append({
                        "qid": row["qid"], "stratum": row["stratum"], "arm": arm,
                        "domain": got.domain, "via": got.via, "reason": got.reason,
                        "verdict": verdict,
                        "catalogue": is_catalogue(got.domain) if got.domain else False,
                    })
        except (CallBudgetSpent, FetchBudgetSpent, ProviderUnavailable, GateIncomplete) as error:
            raise CommandError(f"INCOMPLETE: {type(error).__name__}: {error}") from error

        with out.open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        for arm in _ARMS:
            mine = [x for x in results if x["arm"] == arm]
            c = Counter(x["verdict"] for x in mine)
            self.stdout.write(f"{arm}: {c['correct']} / {c['wrong']} / {c['unresolved']} "
                              "(correct / confident-wrong / unresolved)")
            reasons = Counter(x["reason"] for x in mine if x["reason"])
            self.stdout.write(f"  reasons: {dict(reasons)}")
            self.stdout.write(f"  via: {dict(Counter(x['via'] for x in mine if x['via']))}")
            for stratum in sorted({x["stratum"] for x in mine}):
                s = Counter(x["verdict"] for x in mine if x["stratum"] == stratum)
                self.stdout.write(f"  {stratum}: {s['correct']}/{s['wrong']}/{s['unresolved']}")
        full = [x for x in results if x["arm"] == "FULL"]
        c = Counter(x["verdict"] for x in full)
        tally = holdout.Tally(
            correct=c["correct"], wrong=c["wrong"], unresolved=c["unresolved"],
            directory_or_aggregator_wrong=sum(
                1 for x in full if x["verdict"] == "wrong" and x["catalogue"]),
            diffbot_wrong=sum(
                1 for x in full if x["verdict"] == "wrong" and x["via"] == "DIFFBOT"),
            n=len(full),
        )
        least_correct, most_wrong = holdout.thresholds(tally.n)
        self.stdout.write(f"rule for n={tally.n}: correct >= {least_correct}, "
                          f"confident-wrong <= {most_wrong}")
        self.stdout.write(
            f"spend: tavily {shared_tavily.spent} calls, fetch ${budget.usd():.3f} "
            f"({budget.spent}), diffbot {diffbot.budget.spent if diffbot else 0} entities "
            "(not on RegisterEntry: subtract from the month's allowance by hand)")
        self.stdout.write(f"results -> {out}")
        self.stdout.write(("PASS" if holdout.passes(tally) else "FAIL") + f" {tally}")

    @staticmethod
    def _what_moved(row: dict[str, str], code: str) -> str:
        """Which frozen component differs, when the draw recorded them."""
        try:
            drawn = json.loads(row.get("resolver_digest_parts") or "")
        except ValueError:
            return ""
        if not isinstance(drawn, dict) or not drawn:
            return ""
        moved = holdout.changed_components(drawn, holdout.digest_components(code))
        return f" -- changed: {', '.join(moved)}" if moved else ""

    def _adjudicate(
        self, domain: str, truth: tuple[str, ...], names: Sequence[str], fetch: _GateFetch,
    ) -> str:
        landed = fetch.homepage(domain)
        landed_ok = landed.outcome in _LANDED
        landed_on = registrable_domain(landed.final_url) if landed_ok else ""
        dead = all(fetch.homepage(t).outcome == Outcome.DEAD for t in truth)
        flat_title = "".join(tokens(" ".join(page_titles(landed.body)))) if landed_ok else ""
        names_it = any("".join(tokens(n)) in flat_title for n in names if tokens(n))
        return holdout.adjudicate(resolved_landed_on=landed_on, truth=truth,
                                  truth_dead=dead, resolved_title_names_it=names_it)
