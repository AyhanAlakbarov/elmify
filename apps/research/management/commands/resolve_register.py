"""Resolve a register's URL-less rows to sites (spec 6.5), or record why not.

Dry-run by default: prints each name's answer and writes nothing. `--write`
records resolutions and reasons, and is refused until the fresh-script
hold-out has passed (RESOLVER_WRITES_ENABLED) -- until then the resolver's
output is a candidate list for a person to read, which is what the 2026-09-18
standing rule required. A spent budget, a vendor that is down or a Wikidata
failure stops the run between names, never mid-write, and the untouched names
are next run's.

Registers served: VGM, and every curated closed list that has a rows file --
its blank-website rows are exactly the ones the enumerators' coverage gate
reads as UNBOUND (build item 7). A vocabulary is per country, so each row is
read with its own country's (`spec_for`: the row's country, else its list's);
a row with no country at all is printed and skipped, never written. Every
resolver in one run shares one Tavily cap, one Diffbot cap and one fetch
budget, so the caps are per run whatever the mix of countries.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import closed_lists, vgm
from apps.research.egress import SourceBlocked
from apps.research.fetch import CATALOG_ROLE_NOTE, SweepBudget, default_budget
from apps.research.models import ClosedList, RegisterEntry
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.diffbot import DiffbotEnhance
from apps.research.providers.tavily import TavilyProvider
from apps.research.resolve_entries import (
    EntryMovedOn,
    RegisterSpec,
    diffbot_allowed,
    due_entries,
    record_diffbot_asked,
    record_resolution,
    spec_for,
)
from apps.research.resolver import (
    CallBudget,
    CallBudgetSpent,
    FetchBudgetSpent,
    NameQuery,
    Resolver,
)
from apps.research.vocabulary import VocabularyMissing, load_vocabulary
from apps.research.wikidata import find_item

#: VGM vouches for all three facts of every row: a body, in Türkiye, a foundation.
VGM_SPEC = RegisterSpec(country_code="TR", kind="PRIVATE_FOUNDATION")
_DIFFBOT_WINDOW = timedelta(days=30)
#: What ends a run between names. Each leaves the current name untouched.
_STOPS = (CallBudgetSpent, FetchBudgetSpent, ProviderUnavailable, SourceBlocked)


def registers() -> dict[str, RegisterSpec]:
    """Every register this command may resolve, and what it vouches for.

    A closed list with a rows file is a hand-read list whose blank-website
    rows are the resolver's queue; its country is the list's (`""` for the
    intergovernmental list) and its kind is per row, so the spec's is blank.
    An adapter-read list (Wikidata, ROR, EACEA) has no rows file and no
    queue here -- its rows carry their key or never had a name to resolve.
    """
    found = {vgm.REGISTER: VGM_SPEC}
    for slug, country in ClosedList.objects.order_by("slug").values_list("slug", "country_code"):
        if (closed_lists.LISTS_DIR / f"{slug}.csv").exists():
            found.setdefault(slug, RegisterSpec(country_code=country, kind=""))
    return found


def diffbot_asker(entities: int) -> Callable[[str], str] | None:
    """One Diffbot client and one entity cap for the whole run, or None."""
    if entities <= 0:
        return None
    cap = CallBudget(entities)
    try:
        enhance = DiffbotEnhance(token=settings.DIFFBOT_TOKEN)
    except ValueError as exc:
        raise CommandError(str(exc)) from None

    def ask(name: str) -> str:
        cap.spend()
        return enhance.homepage(name)

    return ask


def build_resolver(
    *,
    country_code: str,
    tavily: CallBudget,
    diffbot: Callable[[str], str] | None,
    budget: SweepBudget,
) -> Resolver:
    """A resolver reading names with one country's vocabulary. The caps are
    passed in, never made here, so resolvers for two countries share them."""
    vocab = load_vocabulary(country_code)
    return Resolver(
        vocabulary=vocab,
        candidates=TavilyProvider(api_key=settings.TAVILY_API_KEY).candidates,
        tavily=tavily,
        budget=budget,
        wikidata=lambda names: find_item(
            names, country_qid=vocab.country_qid, languages=vocab.languages
        ),
        diffbot=diffbot,
    )


class Command(BaseCommand):
    help = (
        "Resolve a register's unresolved names to sites, or record why not. Dry-run "
        "unless --write, which is refused until the resolver's hold-out passed; a "
        "write runs as runtime_engine, the only role that can update RegisterEntry."
        + CATALOG_ROLE_NOTE
    )

    def add_arguments(self, parser: Any) -> None:
        # Not argparse `choices`: the closed lists are rows, and a parser
        # built at import would query the database before a command runs.
        parser.add_argument("--register", required=True)
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--tavily-credits", type=int,
                            default=settings.RESOLVER_TAVILY_CREDITS_PER_RUN)
        parser.add_argument("--diffbot", action="store_true", help="ask Diffbot on the residue")
        parser.add_argument("--write", action="store_true")
        parser.add_argument("--retry-final", action="store_true",
                            help="also retry names whose reason is final")

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        if options["write"] and not settings.RESOLVER_WRITES_ENABLED:
            raise CommandError("--write is off until the fresh-script hold-out passes "
                               "(RESOLVER_WRITES_ENABLED; build item 8, Task 12)")
        served = registers()
        register = options["register"]
        if register not in served:
            raise CommandError(
                f"unknown register {register!r}; one of: {', '.join(sorted(served))}"
            )
        if not settings.TAVILY_API_KEY:
            raise CommandError("TAVILY_API_KEY (or SEARCH_API_KEY) is not set")
        diffbot_entities = 0
        if options["diffbot"]:
            if not options["write"]:
                # The meter IS diffbot_asked_at, written only with --write: a
                # dry run asking Diffbot would spend credits no cap counts,
                # and ask the same names again next run.
                raise CommandError("--diffbot needs --write: Diffbot's monthly meter is the "
                                   "diffbot_asked_at column, which a dry run does not write")
            if not settings.DIFFBOT_TOKEN:
                raise CommandError("DIFFBOT_TOKEN is not set")
            # The terms-freshness check itself lives in DiffbotEnhance.__init__
            # (diffbot_asker constructs one below) -- one place for every caller.
            # The meter is account-wide: every register's asks count.
            used = RegisterEntry.objects.filter(diffbot_asked_at__gte=now - _DIFFBOT_WINDOW).count()
            diffbot_entities = max(0, settings.DIFFBOT_MONTHLY_ENTITIES - used)

        # --limit counts names that will be resolved: a skipped row is never
        # attempted, so counting it would let a run of country-less rows at
        # the head of the queue eat every run's limit forever.
        planned: list[tuple[RegisterEntry, RegisterSpec]] = []
        resolvable = 0
        for entry in due_entries(register, now=now, retry_final=options["retry_final"]):
            if resolvable >= options["limit"]:
                break
            spec = spec_for(entry, served[register])
            planned.append((entry, spec))
            resolvable += bool(spec.country_code and spec.kind)
        tavily = CallBudget(options["tavily_credits"])
        diffbot = diffbot_asker(diffbot_entities)
        budget = default_budget()
        # Every vocabulary is loaded before the first paid call: a missing
        # country found halfway through would stop a run that had already spent.
        resolvers: dict[str, Resolver] = {}
        for country in sorted({spec.country_code for _, spec in planned if spec.country_code}):
            try:
                resolvers[country] = build_resolver(
                    country_code=country, tavily=tavily, diffbot=diffbot, budget=budget
                )
            except VocabularyMissing as error:
                raise CommandError(
                    f"no resolver vocabulary for {country}: {error} "
                    "(manage.py build_resolver_vocabulary)"
                ) from error

        tally: Counter[str] = Counter()
        for entry, spec in planned:
            if not spec.country_code or not spec.kind:
                # No vocabulary reads a name of no country, and no organisation
                # can be written without the kind the list vouched for.
                skipped = "no country" if not spec.country_code else "no kind"
                tally[skipped] += 1
                self.stdout.write(f"{entry.name} -> - ({skipped})")
                continue
            query = NameQuery(tuple(entry.names or [entry.name]), spec.country_code,
                              allow_diffbot=diffbot_allowed(entry, now=now))
            try:
                resolution = resolvers[spec.country_code].resolve(query)
            except _STOPS as error:
                if isinstance(error, FetchBudgetSpent) and error.diffbot_asked:
                    # Paid for before the budget ran out verifying it.
                    record_diffbot_asked(entry, now=now)
                self.stdout.write(f"stopped: {type(error).__name__}: {error}")
                break
            outcome = resolution.via or resolution.reason
            self.stdout.write(f"{entry.name} -> {resolution.domain or '-'} ({outcome})")
            if options["write"]:
                try:
                    record_resolution(entry, resolution, spec=spec, now=now)
                except EntryMovedOn as error:
                    # Bound, renamed or queued for a person by someone else
                    # meanwhile: theirs stands, and the run goes on.
                    self.stdout.write(f"  not written: {error}")
                    outcome = "MOVED_ON"
            tally[outcome] += 1
        self.stdout.write(f"tally: {dict(sorted(tally.items()))}")
        self.stdout.write(f"tavily calls: {tavily.spent} of {tavily.limit}")
        self.stdout.write(f"vendor credits spent: {budget.usd():.4f} USD")
        if not options["write"]:
            self.stdout.write("dry run: nothing written")
