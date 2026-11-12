"""The tap (spec 10.5): catalogue first, stage 1 search, stage 2 read, republish.

Item 14's Task 11 tests, adapted to `request_tap(..., kind=...)` (they test the
follow-up's cap, call and charge behaviour), plus the FIRST search's staging,
plateau and reserve (plan Task 4a). No real provider or model call anywhere:
every provider here is scripted.
"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from itertools import count

import pytest
from django.utils import timezone

import apps.research.tap as tap_module
from apps.funding.fx import RateTable
from apps.funding.models import PackVersion
from apps.funding.rates import store
from apps.research.angles import cycle_label
from apps.research.models import (
    AreaSweep,
    Organisation,
    OrganisationDomain,
    SearchTap,
    SearchWallet,
    TapQueryRun,
    WalletCharge,
)
from apps.research.register import record_organisation
from apps.research.schemas import ResearchMessage
from apps.research.tap import request_tap, run_tap
from apps.research.tap_seams import AngleRow, HostRead, NullSeams, PassState, TapQueryInputs
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db(transaction=True)

FIRST, FOLLOW_UP = SearchTap.Kind.FIRST, SearchTap.Kind.FOLLOW_UP


class _Seams(NullSeams):
    """Scripted seams. `angles` answers every language unless `by_language` is given."""

    def __init__(self, *, angles=(), recency=(), past_stop=False, reads=True, by_language=None):
        self._angles, self._recency, self._past, self._reads = angles, recency, past_stop, reads
        self._by_language = by_language
        self.read_domains: list[str] = []

    def programme_angles(self, *, level, language):
        if self._by_language is not None:
            return self._by_language.get(language, ())
        return self._angles

    def recency_angles(self, *, level, language):
        return self._recency

    def state(self, country, family):
        return PassState(
            swept=True, past_economic_stop=self._past, batches_without_new=0, stop_reason=""
        )

    def read(self, domain, *, max_usd):
        self.read_domains.append(domain)
        if not self._reads:
            return None
        return HostRead(cost_usd=Decimal("0.02"), awards_served=1, outcome="found")


class _Provider:
    """`urls` is a list, or a callable(request, call_number) -> list."""

    def __init__(self, urls=(), *, name="exa", usd=0.007):
        self.name, self._urls, self._usd = name, urls, usd
        self.requests = []

    def search(self, request, meter=None):
        self.requests.append(request)
        if meter is not None:
            meter.charge(self.name, self._usd)
        urls = self._urls(request, len(self.requests)) if callable(self._urls) else self._urls
        yield from urls


def _angles(n, template="v{i} {{field}}", language="en"):
    return tuple(AngleRow(f"{language}{i}", language, template.format(i=i)) for i in range(n))


@pytest.fixture(autouse=True)
def queued(monkeypatch):
    sent: list[ResearchMessage] = []
    monkeypatch.setattr(tap_module, "enqueue_research", lambda message, **_: sent.append(message))
    return sent


@pytest.fixture(autouse=True)
def one_call_at_a_time(settings):
    """Calls in submission order, so a test can count and order them. The
    parallel tests at the end of this file set TAP_PARALLEL_CALLS themselves."""
    settings.TAP_PARALLEL_CALLS = 1


@pytest.fixture
def tapping_student(agency_a, django_user_model):
    """A published student (allowed DE, a field and an interest), scope held."""
    from tests.research.coverage_factories import make_published_student

    student = make_published_student(
        agency_a, django_user_model, allowed=("DE",),
        target_field="Physical chemistry", research_interests=("catalysis",),
    )
    with tenant_scope(agency_a.id):
        yield student


@pytest.fixture
def known_domain(tapping_student):
    record_organisation(
        domain="known-body.org", name="Known Body", kind="PRIVATE_FOUNDATION",
        country_code="DE", found_via="REGISTER", status=Organisation.Status.REGISTERED,
    )
    return "known-body.org"


def _ended(tap):
    tap.refresh_from_db()
    return tap.state, tap.ending


# --- request_tap -------------------------------------------------------------


def test_a_first_search_may_spend_the_wallet_less_the_follow_up_reserve(
    tapping_student, queued
) -> None:
    tap = request_tap(tapping_student, kind=FIRST)
    assert tap.kind == FIRST and tap.allowance_usd == Decimal("90")
    assert [(m.kind, m.tap_id, m.run_id) for m in queued] == [("search_tap", tap.id, tap.run_id)]


def test_a_follow_up_may_spend_half_of_what_remains_and_carries_its_new_part(
    tapping_student, queued
) -> None:
    inputs = tap_module._new_part(_profile(), _profile(allowed_countries=("DE", "NL")))
    tap = request_tap(tapping_student, kind=FOLLOW_UP, inputs=inputs)
    assert tap.kind == FOLLOW_UP and tap.allowance_usd == Decimal("50")
    assert queued[0].inputs == inputs
    # The message survives the queue's JSON round trip with the new part intact.
    assert ResearchMessage.model_validate_json(queued[0].model_dump_json()).inputs == inputs


# --- the follow-up (item 14's Task 11 tests) ---------------------------------


def test_the_catalog_serves_before_any_provider_is_called(tapping_student, monkeypatch) -> None:
    order: list[str] = []
    real = tap_module.rebuild_pack
    monkeypatch.setattr(
        tap_module,
        "rebuild_pack",
        lambda run, *, rates=None: order.append("publish") or real(run, rates=rates),
    )
    tap = request_tap(tapping_student, kind=FOLLOW_UP)

    class Recording(_Provider):
        def search(self, request, meter=None):
            order.append("search")
            yield from ()

    run_tap(tap.id, seams=_Seams(angles=_angles(1)), providers=[Recording()])
    assert order[:2] == ["publish", "search"]


def test_known_hosts_are_deduped_before_any_read(tapping_student, known_domain) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    seams = _Seams(angles=_angles(1))
    run_tap(tap.id, seams=seams, providers=[_Provider([f"https://www.{known_domain}/x"])])
    assert seams.read_domains == []
    tap.refresh_from_db()
    assert (tap.hosts_seen, tap.hosts_new) == (1, 0)


def test_every_billed_call_is_charged_to_the_wallet_and_the_tap(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=_Seams(angles=_angles(1)), providers=[_Provider(["https://new-body.org/"])])
    assert WalletCharge.objects.filter(tap=tap, kind="SEARCH").count() == 1
    assert SearchWallet.objects.get(id=tap.wallet_id).spent_usd == Decimal("0.0270")  # + a read


def test_a_follow_up_never_makes_more_than_the_call_cap(tapping_student, settings) -> None:
    settings.TAP_MAX_PROVIDER_CALLS = 7
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    exa, brave = _Provider(), _Provider(name="brave")
    run_tap(tap.id, seams=_Seams(angles=_angles(50)), providers=[exa, brave])
    assert len(exa.requests) + len(brave.requests) == 7
    assert _ended(tap) == ("DONE", "CALL_CAP")


def test_a_follow_up_stops_at_tap_max_queries(tapping_student, settings) -> None:
    assert settings.TAP_MAX_QUERIES == 30
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    exa = _Provider()
    run_tap(tap.id, seams=_Seams(angles=_angles(50)), providers=[exa])
    assert len(exa.requests) == 30
    assert _ended(tap) == ("DONE", "COMPLETE")


def test_a_follow_up_searches_only_the_new_part(tapping_student) -> None:
    inputs = tap_module._new_part(_profile(), _profile(allowed_countries=("DE", "NL")))
    tap = request_tap(tapping_student, kind=FOLLOW_UP, inputs=inputs)
    exa = _Provider()
    run_tap(tap.id, inputs=inputs, seams=_Seams(angles=(_IN_COUNTRY,)), providers=[exa])
    assert [r.query for r in exa.requests] == ["Our M.Sc. in physical chemistry in Netherlands"]


def test_a_cell_past_its_economic_stop_asks_only_the_recency_angles(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    exa = _Provider()
    seams = _Seams(
        angles=(AngleRow("gen", "en", "{field}"),),
        recency=(AngleRow("new", "en", "{field} {intake}"),), past_stop=True,
    )
    run_tap(tap.id, seams=seams, providers=[exa])
    assert [r.query for r in exa.requests] == ["physical chemistry 2027"]
    tap.refresh_from_db()
    assert tap.recency_only


def test_no_angles_is_a_recorded_ending(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=NullSeams(), providers=[])
    assert _ended(tap) == ("DONE", "NO_ANGLES")


@pytest.mark.parametrize("kind", [FIRST, FOLLOW_UP])
def test_angles_that_render_no_query_end_no_queries(tapping_student, kind) -> None:
    # {duration}: the student has no duration preference, so it is never asked blank.
    tap = request_tap(tapping_student, kind=kind)
    exa = _Provider()
    run_tap(tap.id, seams=_Seams(angles=(AngleRow("d", "en", "{duration} {field}"),)),
            providers=[exa])
    assert exa.requests == []
    assert _ended(tap) == ("DONE", "NO_QUERIES")


def test_stage_two_reads_new_hosts_and_republishes(tapping_student, monkeypatch) -> None:
    rebuilt: list[int] = []
    real = tap_module.rebuild_pack

    def counting(run, *, rates=None):
        pack = real(run, rates=rates)
        rebuilt.append(pack.version)
        return pack

    monkeypatch.setattr(tap_module, "rebuild_pack", counting)
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=_Seams(angles=_angles(1)), providers=[_Provider(["https://new-body.org/"])])
    tap.refresh_from_db()
    assert tap.awards_served == 1 and tap.pages_fetched == 1 and tap.ending == "COMPLETE"
    assert len(rebuilt) == 2  # serve first, then again after the served award
    assert PackVersion.objects.get(id=tap.pack_version_id).version == rebuilt[-1]
    assert WalletCharge.objects.filter(tap=tap, kind="READ").count() == 1


def test_every_tap_rebuild_uses_the_latest_stored_rates(tapping_student, monkeypatch) -> None:
    """Both rebuilds -- catalogue first, and again after a served award -- price
    the pack with the newest stored table. Before, they passed none, so a tap on
    a student with no published pack rebuilt it as "No exchange-rate table is
    loaded" (apps/research/spine.py), even when the worker had rates."""
    table = RateTable(
        base="AZN",
        rates={"AZN": Decimal("1"), "EUR": Decimal("0.5")},
        source="CBAR",
        retrieved_on=date(2026, 1, 8),
    )
    store(table)
    seen: list[RateTable | None] = []
    real = tap_module.rebuild_pack

    def recording(run, *, rates=None):
        seen.append(rates)
        return real(run, rates=rates)

    monkeypatch.setattr(tap_module, "rebuild_pack", recording)
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=_Seams(angles=_angles(1)), providers=[_Provider(["https://new-body.org/"])])
    assert len(seen) == 2
    assert all(rates == table for rates in seen)


def test_new_hosts_with_no_reader_end_stage2_unavailable(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=_Seams(angles=_angles(1), reads=False),
            providers=[_Provider(["https://new-body.org/"])])
    assert _ended(tap) == ("DONE", "STAGE2_UNAVAILABLE")
    tap.refresh_from_db()
    assert tap.hosts_new == 1


def test_a_thin_area_queues_one_bounded_sweep_and_charges_the_wallet_nothing_for_it(
    tapping_student,
) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=NullSeams(), providers=[])
    assert AreaSweep.objects.filter(state="QUEUED").count() == 1
    assert not WalletCharge.objects.filter(kind="SEARCH").exists()
    second = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(second.id, seams=NullSeams(), providers=[])
    assert AreaSweep.objects.get(state="QUEUED").demand == 2


def test_a_tap_runs_once(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    exa = _Provider()
    run_tap(tap.id, seams=_Seams(angles=_angles(1)), providers=[exa])
    run_tap(tap.id, seams=_Seams(angles=_angles(1)), providers=[exa])  # a redelivery
    assert len(exa.requests) == 1


def test_tavily_is_never_a_tap_provider() -> None:
    import inspect

    assert "tavily" not in inspect.getsource(tap_module).lower()


# --- the FIRST search ----------------------------------------------------------


def test_the_first_search_runs_past_twenty_queries_and_stops_on_plateau(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FIRST)
    fresh = count()
    exa = _Provider(lambda request, n: [f"https://body-{next(fresh)}.org/"] if n <= 25 else [])
    run_tap(tap.id, seams=_Seams(by_language={"en": _angles(60)}), providers=[exa])
    # 25 queries found a new host each; queries 25-34 brought 1 between them: the
    # coverage stage stops there. Deep still re-runs its top 20% (7 of 34) at 100.
    coverage = [r for r in exa.requests if r.max_results < 100]
    assert len(coverage) == 34
    assert len(exa.requests) - len(coverage) == 7
    assert _ended(tap) == ("DONE", "PLATEAU")
    tap.refresh_from_db()
    assert tap.hosts_new == 25


def test_the_first_search_never_spends_the_follow_up_reserve(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FIRST)
    fresh = count()
    exa = _Provider(lambda request, n: [f"https://body-{next(fresh)}.org/"], usd=1.0)
    run_tap(tap.id, seams=_Seams(angles=_angles(150), reads=False), providers=[exa])
    wallet = SearchWallet.objects.get(id=tap.wallet_id)
    assert wallet.spent_usd == Decimal("90")
    assert wallet.budget_usd - wallet.spent_usd == Decimal("10")
    assert _ended(tap) == ("DONE", "WALLET_SPENT")


def test_the_first_search_stages_coverage_then_local_then_deep(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FIRST)
    fresh = count()

    def urls(request, n):
        if "v2" in request.query and request.max_results < 100:
            return [f"https://body-{next(fresh)}.org/" for _ in range(3)]
        return []

    exa, brave = _Provider(urls), _Provider(urls, name="brave")
    seams = _Seams(reads=False, by_language={
        "en": _angles(5),
        "de": (AngleRow("de0", "de", "{field} Masterstudiengang in {destination}"),),
    })
    run_tap(tap.id, seams=seams, providers=[exa, brave])
    queries = [(r.query, r.max_results) for r in exa.requests]
    # Coverage (English, no query cap), then local (German, for DE), then deep.
    assert [q for q, _ in queries[:5]] == [f"v{i} physical chemistry" for i in range(5)]
    assert queries[5] == ("physical chemistry Masterstudiengang in Deutschland", 12)
    # Top 20% of 5 coverage queries by new hosts: the one query that found any, at 100.
    assert queries[6:] == [("v2 physical chemistry", 100)]
    assert all(r.max_results < 100 for r in brave.requests)
    assert _ended(tap) == ("DONE", "STAGE2_UNAVAILABLE")


def test_the_first_search_keeps_the_reserve_after_a_follow_up_spent(tapping_student) -> None:
    """Review probe: FIRST requested at $90, a follow-up then spends $20; the
    first search must stop at the wallet less the reserve, not its $90."""
    from apps.research.wallet import charge

    tap = request_tap(tapping_student, kind=FIRST)
    follow_up = request_tap(tapping_student, kind=FOLLOW_UP)
    charge(follow_up, kind="SEARCH", provider="exa", usd=Decimal("20"))
    fresh = count()
    exa = _Provider(lambda request, n: [f"https://body-{next(fresh)}.org/"], usd=1.0)
    run_tap(tap.id, seams=_Seams(angles=_angles(150), reads=False), providers=[exa])
    wallet = SearchWallet.objects.get(id=tap.wallet_id)
    assert wallet.spent_usd == Decimal("90")  # $20 + $70: the $10 reserve is kept
    assert _ended(tap) == ("DONE", "WALLET_SPENT")


def test_a_coverage_stage_that_runs_dry_still_runs_the_local_stage(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FIRST)
    exa = _Provider([])
    seams = _Seams(reads=False, by_language={
        "en": _angles(12),
        "de": (AngleRow("de0", "de", "{field} Masterstudiengang in {destination}"),),
    })
    run_tap(tap.id, seams=seams, providers=[exa])
    queries = [r.query for r in exa.requests if r.max_results < 100]
    assert len(queries) == 11  # ten dry coverage queries are the plateau; then local
    assert queries[-1] == "physical chemistry Masterstudiengang in Deutschland"
    assert _ended(tap) == ("DONE", "PLATEAU")


@pytest.mark.parametrize("kind", [FIRST, FOLLOW_UP])
def test_no_provider_is_its_own_ending_never_a_search_that_found_nothing(
    tapping_student, kind
) -> None:
    tap = request_tap(tapping_student, kind=kind)
    run_tap(tap.id, seams=_Seams(angles=_angles(30)), providers=[])
    assert _ended(tap) == ("DONE", "NO_PROVIDER")
    tap.refresh_from_db()
    assert tap.provider_calls == 0


def test_without_exa_the_deep_stage_asks_nothing_and_moves_no_plateau(tapping_student) -> None:
    tap = request_tap(tapping_student, kind=FIRST)
    brave = _Provider(name="brave")
    run_tap(tap.id, seams=_Seams(angles=_angles(9)), providers=[brave])
    assert len(brave.requests) == 9 and all(r.max_results < 100 for r in brave.requests)
    assert _ended(tap) == ("DONE", "COMPLETE")


def test_a_failing_provider_is_dropped_and_the_search_goes_on(tapping_student) -> None:
    from apps.research.egress import SourceBlocked

    class Throttled(_Provider):
        def search(self, request, meter=None):
            self.requests.append(request)
            raise SourceBlocked("api returned HTTP 429")
            yield  # pragma: no cover - a generator, like the real adapters

    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    exa, brave = Throttled(), _Provider(["https://new-body.org/"], name="brave")
    run_tap(tap.id, seams=_Seams(angles=_angles(5), reads=False), providers=[exa, brave])
    assert len(exa.requests) == 1 and len(brave.requests) == 5
    assert _ended(tap) == ("DONE", "STAGE2_UNAVAILABLE")

    second = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(second.id, seams=_Seams(angles=_angles(5)), providers=[Throttled()])
    assert _ended(second) == ("DONE", "NO_PROVIDER")


def test_a_billed_call_s_urls_are_recorded_when_its_charge_crosses_a_ceiling(
    tapping_student,
) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)  # a $50 allowance
    exa = _Provider(["https://paid-for.org/"], usd=60.0)
    run_tap(tap.id, seams=_Seams(angles=_angles(3)), providers=[exa])
    tap.refresh_from_db()
    assert tap.hosts_new == 1 and len(exa.requests) == 1
    assert OrganisationDomain.objects.filter(registrable_domain="paid-for.org").exists()
    assert _ended(tap) == ("DONE", "TAP_SHARE_SPENT")


def test_a_tap_that_cannot_be_queued_is_removed_and_refused(tapping_student, monkeypatch) -> None:
    from apps.research.wallet import TapRefused

    def down(message, **_):
        raise ConnectionError("sqs unreachable")

    monkeypatch.setattr(tap_module, "enqueue_research", down)
    with pytest.raises(TapRefused):
        request_tap(tapping_student, kind=FIRST)
    assert not SearchTap.objects.exists()  # nothing QUEUED counting toward TAP_PER_DAY


def test_a_first_search_with_nothing_above_the_reserve_is_refused(tapping_student, queued) -> None:
    from apps.research.wallet import TapRefused

    wallet_id = request_tap(tapping_student, kind=FOLLOW_UP).wallet_id
    SearchTap.objects.all().delete()
    queued.clear()
    SearchWallet.objects.filter(id=wallet_id).update(spent_usd=Decimal("90"))  # $10 = the reserve
    with pytest.raises(TapRefused):
        request_tap(tapping_student, kind=FIRST)
    assert not SearchTap.objects.exists() and queued == []  # no TAP_PER_DAY slot spent


def test_a_paid_call_s_urls_survive_a_failure_to_remember_the_query(
    tapping_student, monkeypatch
) -> None:
    from django.db import DatabaseError

    def broken(**_):
        raise DatabaseError("tapqueryrun unwritable")

    monkeypatch.setattr(TapQueryRun.objects, "update_or_create", broken)
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=_Seams(angles=_angles(1)), providers=[_Provider(["https://paid.org/"])])
    assert OrganisationDomain.objects.filter(registrable_domain="paid.org").exists()
    assert _ended(tap) == ("DONE", "COMPLETE")


# --- the worker ----------------------------------------------------------------


def test_a_charge_survives_a_later_failure_in_the_worker(tapping_student, monkeypatch) -> None:
    from apps.research.management.commands.run_research_worker import route

    class Broken(NullSeams):
        def read(self, domain, *, max_usd):
            raise RuntimeError("reader fell over")

    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    monkeypatch.setattr(tap_module, "bound_angles", lambda: _Seams(angles=_angles(1)))
    monkeypatch.setattr(tap_module, "bound_host_reader", Broken)
    monkeypatch.setattr(
        tap_module, "default_providers", lambda: [_Provider(["https://new-body.org/"])]
    )
    message = ResearchMessage(
        kind="search_tap", tenant_id=tap.tenant_id, run_id=tap.run_id, tap_id=tap.id
    )
    with pytest.raises(RuntimeError):
        route(message)
    assert WalletCharge.objects.filter(tap=tap, kind="SEARCH").count() == 1
    assert _ended(tap) == ("DONE", "FAILED")


def test_only_a_search_tap_message_carries_a_tap() -> None:
    from uuid import uuid4

    with pytest.raises(ValueError):
        ResearchMessage(kind="search_tap", tenant_id=uuid4(), run_id=uuid4())
    with pytest.raises(ValueError):
        ResearchMessage(kind="run_research", tenant_id=uuid4(), run_id=uuid4(), tap_id=uuid4())
    inputs = replace(
        TapQueryInputs((), (), (), (), False, 2027, (), False, ()), destinations=("NL",)
    )
    with pytest.raises(ValueError):
        ResearchMessage(kind="run_research", tenant_id=uuid4(), run_id=uuid4(), inputs=inputs)


# --- a query run recently is not run again (plan Task 4b) --------------------


def _second_student(agency, django_user_model):
    from tests.research.coverage_factories import make_published_student

    return make_published_student(
        agency, django_user_model, allowed=("DE",),
        target_field="Physical chemistry", research_interests=("catalysis",),
    )


def test_a_second_student_with_the_same_field_charges_nothing_for_shared_queries(
    tapping_student, agency_a, django_user_model
) -> None:
    seams = _Seams(angles=_angles(3))
    first = request_tap(tapping_student, kind=FOLLOW_UP)
    exa = _Provider()
    run_tap(first.id, seams=seams, providers=[exa])
    assert len(exa.requests) == 3

    other = _second_student(agency_a, django_user_model)
    second = request_tap(other, kind=FOLLOW_UP)
    again = _Provider()
    run_tap(second.id, seams=seams, providers=[again])
    assert again.requests == []
    second.refresh_from_db()
    assert (second.provider_calls, second.queries_reused) == (0, 3)
    assert not WalletCharge.objects.filter(tap=second).exists()


def test_a_query_older_than_the_reuse_window_runs_again(
    tapping_student, settings
) -> None:
    from datetime import timedelta

    from django.utils import timezone

    seams = _Seams(angles=(AngleRow("m0", "en", "m0 {field}", "MONEY"),))
    run_tap(request_tap(tapping_student, kind=FOLLOW_UP).id, seams=seams, providers=[_Provider()])
    TapQueryRun.objects.update(
        ran_at=timezone.now() - timedelta(days=settings.TAP_QUERY_REUSE_DAYS + 1)
    )
    exa = _Provider()
    run_tap(request_tap(tapping_student, kind=FOLLOW_UP).id, seams=seams, providers=[exa])
    assert len(exa.requests) == 1
    assert TapQueryRun.objects.count() == 1  # updated in place, ran_at renewed
    assert TapQueryRun.objects.get().ran_at > timezone.now() - timedelta(days=1)


def test_a_reused_query_does_not_move_the_plateau_window(tapping_student, settings) -> None:
    settings.FIRST_SEARCH_PLATEAU_BATCH = 2
    settings.FIRST_SEARCH_PLATEAU_MIN_NEW = 0  # the first run never plateaus
    seams = _Seams(angles=_angles(4))
    run_tap(request_tap(tapping_student, kind=FIRST).id, seams=seams, providers=[_Provider()])
    exa = _Provider()
    tap = request_tap(tapping_student, kind=FIRST)
    run_tap(tap.id, seams=seams, providers=[exa])
    tap.refresh_from_db()
    assert exa.requests == [] and tap.queries_reused > 0 and tap.ending != "PLATEAU"


# --- what starts a search (plan Task 4c) ---------------------------------------


def _profile(**overrides):
    from tests.funding.conftest import make_profile

    fields = dict(
        nationality="AZ", country_of_residence="AZ", allowed_countries=("DE",),
        target_field="Physical chemistry", research_interests=("catalysis",),
    )
    return make_profile(**{**fields, **overrides})


#: Templates `refusal` stores, as the writer would write them.
_IN_COUNTRY = AngleRow("c", "en", "Our M.Sc. in {field} in {destination}")
_SPECIALISING = AngleRow("s", "en", "Our M.Sc. in {field}, specialising in {interest}")


_REALISTIC = tuple(
    AngleRow(f"r{i}", "en", template)
    for i, template in enumerate((
        "Our M.Sc. in {field} in {destination}",
        "Our M.Sc. in {field}, specialising in {interest}",
        "Our M.Sc. in {field}: {interest} research in {destination}",
        "M.Sc. {field} programme in {destination} taught in English",
        "Master of Science {interest} {field} department in {destination}",
        "Our {field} master's degree, {interest} track",
        "Funded M.Sc. in {field} in {destination}: {money}",
        "{money} for our M.Sc. in {field}, {interest} focus",
        "{money} for M.Sc. students in {field} in {destination}",
        "Our {field} master's in {destination} for the {intake} intake",
    ))
)


def test_a_follow_up_adding_a_country_and_an_interest_spends_no_cap_slot_on_a_repeat(
    tapping_student,
) -> None:
    from apps.research.models import TapQueryRun
    from apps.research.tap_query import render_tap_queries

    before = _profile(
        allowed_countries=("DE", "NL", "SE"),
        research_interests=("catalysis", "kinetics", "spectroscopy"),
    )
    after = _profile(
        allowed_countries=("DE", "NL", "SE", "FR"),
        research_interests=("catalysis", "kinetics", "spectroscopy", "electrochemistry"),
    )
    old = tap_module.inputs_from(before)
    for _, request in render_tap_queries(old, _REALISTIC):
        TapQueryRun.objects.create(
            query_sha256=tap_module._query_hash("exa", request), provider="exa",
            results=request.max_results, ran_at=timezone.now(),
            cycle=cycle_label(timezone.now()),
        )
    inputs = tap_module._new_part(before, after)
    everything = [r.query for _, r in render_tap_queries(inputs, _REALISTIC)]
    fresh = [
        r.query for _, r in render_tap_queries(inputs, _REALISTIC)
        if not TapQueryRun.objects.filter(
            query_sha256=tap_module._query_hash("exa", r), provider="exa"
        ).exists()
    ]
    cap = 30
    assert len(everything) > cap > 0 and len(fresh) > 0

    tap = request_tap(tapping_student, kind=FOLLOW_UP, inputs=inputs)
    exa = _Provider()
    run_tap(tap.id, inputs=inputs, seams=_Seams(angles=_REALISTIC), providers=[exa])

    asked = [r.query for r in exa.requests]
    assert asked == fresh[:cap]
    assert any("France" in query for query in asked)


def test_the_hook_s_templates_are_ones_the_writer_may_store() -> None:
    from apps.research.programme_angles import refusal

    assert refusal("PROGRAMME", _IN_COUNTRY.template) is None
    assert refusal("PROGRAMME", _SPECIALISING.template) is None


@pytest.fixture
def automatic(settings):
    settings.TAP_AUTOMATIC = True


def _first_tap(student, *, state="DONE", ending="COMPLETE", age=timedelta(days=2)):
    """A FIRST search in the student's wallet, requested `age` ago (two days by
    default: outside TAP_PER_DAY's window)."""
    from apps.funding.models import RecommendationRun
    from apps.research.wallet import open_wallet

    tap = SearchTap.objects.create(
        student=student, wallet=open_wallet(student, _profile().intended_intake),
        run_id=RecommendationRun.objects.get(profile_version__student=student).id,
        kind=FIRST, state=state, ending=ending, allowance_usd=Decimal("90"),
    )
    SearchTap.objects.filter(id=tap.id).update(requested_at=timezone.now() - age)
    return tap


@pytest.fixture
def first_done(tapping_student):
    return _first_tap(tapping_student)


def _taps():
    """Taps the hook requested (the fixture's first search is two days old)."""
    return list(SearchTap.objects.filter(requested_at__gte=timezone.now() - timedelta(hours=1)))


def _rendered(inputs):
    from apps.research.tap_query import render_tap_queries

    return [request.query for _, request in render_tap_queries(
        inputs, (_IN_COUNTRY, _SPECIALISING)
    )]


def test_nothing_is_queued_while_tap_automatic_is_off(tapping_student, queued, settings) -> None:
    settings.TAP_AUTOMATIC = False
    tap_module.on_profile_saved(None, _profile(), tapping_student)
    assert queued == [] and _taps() == []


def test_a_first_intake_queues_a_first_search(tapping_student, queued, automatic) -> None:
    tap_module.on_profile_saved(None, _profile(), tapping_student)
    assert [t.kind for t in _taps()] == [FIRST] and queued[0].inputs is None


@pytest.mark.parametrize(
    ("state", "ending", "age"),
    [
        ("DONE", "NO_PROVIDER", timedelta(days=2)),
        ("DONE", "FAILED", timedelta(days=2)),
        ("DONE", "NO_ANGLES", timedelta(days=2)),
        ("DONE", "NO_QUERIES", timedelta(days=2)),
        ("QUEUED", "", timedelta(hours=1)),  # never taken: 2 x FIRST_SEARCH_MAX_SECONDS ago
        ("STAGE1", "", timedelta(hours=1)),  # a worker died mid-run
    ],
)
def test_a_first_search_that_did_not_run_is_asked_again_on_the_next_save(
    tapping_student, queued, automatic, state, ending, age
) -> None:
    _first_tap(tapping_student, state=state, ending=ending, age=age)
    tap_module.on_profile_saved(_profile(), _profile(allowed_countries=("DE", "NL")),
                                tapping_student)
    (message,) = queued
    assert SearchTap.objects.get(id=message.tap_id).kind == FIRST and message.inputs is None


@pytest.mark.parametrize(
    ("state", "ending"),
    [("DONE", "COMPLETE"), ("DONE", "PLATEAU"), ("DONE", "WALLET_SPENT"), ("STAGE2", "")],
)
def test_a_first_search_that_ran_makes_the_next_save_a_follow_up(
    tapping_student, queued, automatic, state, ending
) -> None:
    _first_tap(tapping_student, state=state, ending=ending)
    tap_module.on_profile_saved(_profile(), _profile(allowed_countries=("DE", "NL")),
                                tapping_student)
    assert [t.kind for t in _taps()] == [FOLLOW_UP]


def test_an_added_country_is_searched_with_the_field_naming_only_that_country(
    tapping_student, queued, automatic, first_done
) -> None:
    tap_module.on_profile_saved(_profile(), _profile(allowed_countries=("DE", "NL")),
                                tapping_student)
    assert [t.kind for t in _taps()] == [FOLLOW_UP]
    queries = _rendered(queued[0].inputs)
    assert "Our M.Sc. in physical chemistry in Netherlands" in queries
    assert not any("Germany" in query for query in queries)


def test_an_added_interest_is_searched_in_every_destination(
    tapping_student, queued, automatic, first_done
) -> None:
    after = _profile(research_interests=("catalysis", "electrochemistry"))
    tap_module.on_profile_saved(_profile(), after, tapping_student)
    queries = _rendered(queued[0].inputs)
    assert "Our M.Sc. in physical chemistry, specialising in electrochemistry" in queries
    assert "Our M.Sc. in physical chemistry in Germany" in queries  # a repeat: reuse skips it
    assert not any("catalysis" in query for query in queries)


def test_a_changed_field_is_searched_whole(
    tapping_student, queued, automatic, first_done
) -> None:
    tap_module.on_profile_saved(_profile(), _profile(target_field="Inorganic chemistry"),
                                tapping_student)
    assert sorted(_rendered(queued[0].inputs)) == [
        "Our M.Sc. in inorganic chemistry in Germany",
        "Our M.Sc. in inorganic chemistry, specialising in catalysis",
    ]


def test_an_output_filter_change_searches_nothing(
    tapping_student, queued, automatic, first_done
) -> None:
    tap_module.on_profile_saved(
        _profile(), _profile(excluded_countries=("FR",)), tapping_student,
    )
    assert queued == [] and _taps() == []


def test_a_refused_follow_up_is_swallowed(
    tapping_student, queued, automatic, first_done, monkeypatch
) -> None:
    def refuse(*_a, **_k):
        raise tap_module.TapRefused("daily limit")

    monkeypatch.setattr(tap_module, "request_tap", refuse)
    tap_module.on_profile_saved(
        _profile(),
        _profile(allowed_countries=("DE", "NL"), excluded_countries=("FR",)),
        tapping_student,
    )
    assert queued == [] and _taps() == []


def test_a_second_follow_up_the_same_day_is_refused_by_the_daily_limit(
    tapping_student, queued, automatic, first_done, settings
) -> None:
    settings.TAP_PER_DAY = 1
    before = _profile()
    tap_module.on_profile_saved(before, _profile(allowed_countries=("DE", "NL")), tapping_student)
    tap_module.on_profile_saved(before, _profile(allowed_countries=("DE", "SE")), tapping_student)
    assert len(queued) == 1


def test_a_money_only_change_searches_with_the_field_in_every_query(
    tapping_student, queued, automatic, first_done
) -> None:
    from apps.research.tap_query import render_tap_queries

    tap_module.on_profile_saved(
        _profile(funding_dependency="OPTIONAL"), _profile(funding_dependency="MANDATORY"),
        tapping_student,
    )
    assert [t.kind for t in _taps()] == [FOLLOW_UP]
    inputs = queued[0].inputs
    assert inputs.field_words and inputs.money_words
    rendered = render_tap_queries(inputs, _angles(1, "{{money}} {{field}}"))
    assert len(rendered) == 1 and "chemistry" in rendered[0][1].query.lower()


def test_a_removed_country_starts_no_search(
    tapping_student, queued, automatic, first_done
) -> None:
    tap_module.on_profile_saved(
        _profile(allowed_countries=("DE", "NL")), _profile(), tapping_student
    )
    assert queued == [] and _taps() == []


def test_an_error_in_the_hook_is_logged_not_raised(
    tapping_student, queued, automatic, monkeypatch
) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("queue exploded")

    monkeypatch.setattr(tap_module, "request_tap", boom)
    tap_module.on_profile_saved(None, _profile(), tapping_student)
    tap_module.on_profile_saved(
        _profile(), _profile(allowed_countries=("DE", "NL")), tapping_student
    )


def test_a_new_teaching_language_alone_queues_a_follow_up_carrying_it(
    tapping_student, queued, automatic, first_done
) -> None:
    from apps.research.tap_query import render_tap_queries

    tap_module.on_profile_saved(
        _profile(acceptable_teaching_languages=("English",)),
        _profile(acceptable_teaching_languages=("English", "German")),
        tapping_student,
    )
    assert [t.kind for t in _taps()] == [FOLLOW_UP]
    rendered = render_tap_queries(
        queued[0].inputs, _angles(1, "{{field}} {{teaching_language}}")
    )
    assert len(rendered) == 1 and "German" in rendered[0][1].query


def test_the_query_hash_is_keyed_not_plain_sha256_and_stable() -> None:
    import hashlib

    from apps.research.providers import SearchRequest

    request = SearchRequest(query="fully funded msc catalysis", country_code="", language="en")
    digest = tap_module._query_hash("exa", request)
    assert len(digest) == 64
    assert digest != hashlib.sha256(request.query.encode()).hexdigest()
    assert digest == tap_module._query_hash("exa", request)


# --- unread sites stay readable (programme-search round 2, task 1) ------------


@pytest.mark.parametrize(("reads", "rows", "ended"), [
    (False, 0, ("DONE", "STAGE2_UNAVAILABLE")),
    (True, 2, None),
])
def test_a_tap_writes_query_runs_only_when_stage_two_ran(
    tapping_student, reads, rows, ended
) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=_Seams(angles=_angles(2), reads=reads),
            providers=[_Provider(["https://new-body.org/"])])
    if ended:
        assert _ended(tap) == ended
    assert TapQueryRun.objects.count() == rows


def test_a_host_an_earlier_tap_recorded_unread_is_handed_to_stage_two_later(
    tapping_student,
) -> None:
    run_tap(request_tap(tapping_student, kind=FOLLOW_UP).id,
            seams=_Seams(angles=_angles(1), reads=False),
            providers=[_Provider(["https://new-body.org/"])])
    seams = _Seams(angles=_angles(1))
    later = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(later.id, seams=seams, providers=[_Provider(["https://new-body.org/"])])
    assert seams.read_domains == ["new-body.org"]
    later.refresh_from_db()
    assert later.hosts_new == 1
    assert Organisation.objects.filter(domains__registrable_domain="new-body.org").count() == 1


def test_a_registered_host_is_not_handed_to_stage_two(tapping_student) -> None:
    record_organisation(
        domain="registered-body.org", name="Registered", kind="PRIVATE_FOUNDATION",
        country_code="DE", found_via="REGISTER", status=Organisation.Status.REGISTERED,
    )
    seams = _Seams(angles=_angles(1))
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=seams, providers=[_Provider(["https://registered-body.org/"])])
    assert seams.read_domains == []
    tap.refresh_from_db()
    assert tap.hosts_new == 0


@pytest.mark.parametrize("urls", ["known", []])
def test_a_null_reader_still_marks_a_query_with_only_known_hosts_or_no_urls(
    tapping_student, known_domain, urls
) -> None:
    hits = [f"https://{known_domain}/x"] if urls == "known" else urls
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    run_tap(tap.id, seams=_Seams(angles=_angles(1), reads=False), providers=[_Provider(hits)])
    assert TapQueryRun.objects.count() == 1


def test_money_gone_before_the_first_read_marks_only_queries_without_new_hosts(
    tapping_student, monkeypatch
) -> None:
    monkeypatch.setattr(tap_module, "spendable", lambda *a, **k: Decimal(0))
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    urls = lambda request, n: ["https://new-body.org/"] if n == 1 else []  # noqa: E731
    run_tap(tap.id, seams=_Seams(angles=_angles(2)), providers=[_Provider(urls)])
    assert TapQueryRun.objects.count() == 1


def test_a_page_cap_marks_only_queries_whose_new_hosts_were_all_read(
    tapping_student, settings
) -> None:
    settings.TAP_MAX_PAGES = 1
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    by_call = {1: ["https://a-body.org/"], 2: ["https://b-body.org/"], 3: []}
    seams = _Seams(angles=_angles(3))
    run_tap(tap.id, seams=seams, providers=[_Provider(lambda request, n: by_call[n])])
    assert seams.read_domains == ["a-body.org"]
    # the a-body query and the empty one; b-body's runs again
    assert TapQueryRun.objects.count() == 2


# --- the reuse window by kind and cycle (programme-search round 2, task 2) ----


_MONEY = (AngleRow("m0", "en", "m0 {field}", "MONEY"),)


@pytest.mark.parametrize(("money", "age", "cycle", "reran"), [
    (False, 200, None, 0),  # a programme query is reused for the whole cycle
    (True, 40, None, 1),  # a money query older than the window runs again
    (False, 5, "1999-2000", 1),  # a programme query from last cycle runs again
])
def test_the_reuse_window_by_kind_and_cycle(tapping_student, money, age, cycle, reran) -> None:
    angles = _MONEY if money else _angles(1)
    run_tap(request_tap(tapping_student, kind=FOLLOW_UP).id,
            seams=_Seams(angles=angles), providers=[_Provider()])
    changes = {"ran_at": timezone.now() - timedelta(days=age)}
    if cycle is not None:
        changes["cycle"] = cycle
    TapQueryRun.objects.update(**changes)
    exa = _Provider()
    run_tap(request_tap(tapping_student, kind=FOLLOW_UP).id,
            seams=_Seams(angles=angles), providers=[exa])
    assert len(exa.requests) == reran


@pytest.mark.parametrize("kinds", [("PROGRAMME", "MONEY"), ("MONEY", "PROGRAMME"),
                                   ("RECENCY", "PROGRAMME"), ("PROGRAMME", "RECENCY")])
def test_the_same_text_from_two_kinds_takes_the_shorter_window(kinds) -> None:
    from apps.research.tap import _Stage1
    from apps.research.tap_query import inputs_from

    angles = tuple(AngleRow(f"a{i}", "en", "same {field}", kind) for i, kind in enumerate(kinds))
    stage = _Stage1.__new__(_Stage1)
    stage.kinds = {}
    stage.render(inputs_from(_profile()), angles)
    assert set(stage.kinds.values()) == {next(k for k in kinds if k != "PROGRAMME")}


def test_a_failed_first_search_that_spent_to_the_reserve_falls_back_to_a_follow_up(
    tapping_student, queued, automatic
) -> None:
    tap = _first_tap(tapping_student, ending="FAILED")
    SearchWallet.objects.filter(id=tap.wallet_id).update(spent_usd=Decimal("90"))
    tap_module.on_profile_saved(_profile(), _profile(allowed_countries=("DE", "NL")),
                                tapping_student)
    (message,) = queued
    assert SearchTap.objects.get(id=message.tap_id).kind == FOLLOW_UP
    assert message.inputs is not None and message.inputs.destinations == ("NL",)


def test_a_daily_limit_refusal_of_a_first_search_does_not_fall_back(
    tapping_student, queued, automatic, settings
) -> None:
    tap = _first_tap(tapping_student, ending="FAILED", age=timedelta(minutes=1))
    SearchWallet.objects.filter(id=tap.wallet_id).update(spent_usd=Decimal("90"))
    settings.TAP_PER_DAY = 1
    tap_module.on_profile_saved(_profile(), _profile(allowed_countries=("DE", "NL")),
                                tapping_student)
    assert queued == []


# --- parallel calls and continuation (round 2, Task 6) --------------------------


class _Clock:
    """Stands in for `time` in the tap module: a test moves `now` past the deadline."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(tap_module, "time", fake)
    return fake


def _out_of_time_at(clock, call, hosts=lambda request: []):
    """Provider urls that run the job's time out on the `call`-th call (counted
    across every provider and job sharing them)."""
    calls = count(1)

    def urls(request, n):
        if next(calls) == call:
            clock.now += 10_000
        return hosts(request)

    return urls


def test_at_most_tap_parallel_calls_requests_are_in_flight(tapping_student, settings) -> None:
    import threading

    settings.TAP_PARALLEL_CALLS = 8
    lock, full = threading.Lock(), threading.Event()
    flying, peak = [0], [0]

    class Blocking(_Provider):
        def search(self, request, meter=None):
            self.requests.append(request)
            with lock:
                flying[0] += 1
                peak[0] = max(peak[0], flying[0])
                if flying[0] == 8:
                    full.set()
            full.wait(timeout=0.2)
            with lock:
                flying[0] -= 1
            yield from ()

    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    exa = Blocking()
    run_tap(tap.id, seams=_Seams(angles=_angles(20)), providers=[exa])
    assert peak[0] == 8 and len(exa.requests) == 20
    assert _ended(tap) == ("DONE", "COMPLETE")


def test_provider_calls_run_in_worker_threads_and_the_database_only_on_the_main_one(
    tapping_student, settings, monkeypatch
) -> None:
    """The test role bypasses row-level security, so a worker thread's query
    (a new connection with no app.tenant_id) would pass here and return nothing
    in production. So: no thread but the main one opens the database at all."""
    import threading

    from django.db.backends.base.base import BaseDatabaseWrapper

    settings.TAP_PARALLEL_CALLS = 8
    off_main: list[str] = []
    real = BaseDatabaseWrapper.ensure_connection

    def ensure_connection(self):
        if threading.current_thread() is not threading.main_thread():
            off_main.append(threading.current_thread().name)
        return real(self)

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", ensure_connection)
    on_main: list[bool] = []

    class Where(_Provider):
        def search(self, request, meter=None):
            on_main.append(threading.current_thread() is threading.main_thread())
            yield from super().search(request, meter)

    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    hosts = lambda request, n: [f"https://{request.query.split()[0]}-body.org/"]  # noqa: E731
    run_tap(tap.id, seams=_Seams(angles=_angles(10)),
            providers=[Where(hosts), Where(hosts, name="brave")])
    assert len(on_main) == 20 and not any(on_main)
    assert off_main == []
    # Every call billed in a thread is charged, on the main thread, to the wallet.
    assert WalletCharge.objects.filter(tap=tap, kind="SEARCH").count() == 20
    tap.refresh_from_db()
    assert tap.hosts_new == 10


def test_parallel_calls_count_what_is_in_flight_against_the_reserve(
    tapping_student, settings
) -> None:
    from apps.research.wallet import charge

    settings.TAP_PARALLEL_CALLS = 8
    tap = request_tap(tapping_student, kind=FIRST)
    charge(tap, kind="SEARCH", provider="exa", usd=Decimal("89.95"))  # $0.05 above the reserve
    exa = _Provider(usd=0.012)  # bills exactly its preflight price
    run_tap(tap.id, seams=_Seams(angles=_angles(30), reads=False), providers=[exa])
    # Four calls at $0.012 fit in $0.05; eight in flight at once would eat the reserve.
    assert len(exa.requests) == 4
    assert SearchWallet.objects.get(id=tap.wallet_id).spent_usd <= Decimal("90")
    assert _ended(tap) == ("DONE", "WALLET_SPENT")


def test_a_time_capped_first_search_continues_in_a_new_job_from_where_it_stopped(
    tapping_student, queued, clock
) -> None:
    tap = request_tap(tapping_student, kind=FIRST)
    queued.clear()

    def hosts(request):
        many = 3 if request.query.startswith("v2 ") and request.max_results < 100 else 1
        name = f"{request.query.split()[0]}-{request.max_results}"
        return [f"https://{name}-{i}.org/" for i in range(many)]

    urls = _out_of_time_at(clock, 5, hosts)
    seams = _Seams(by_language={"en": _angles(20)})
    exa = _Provider(urls)
    run_tap(tap.id, seams=seams, providers=[exa])
    tap.refresh_from_db()
    assert (tap.state, tap.ending, tap.resume["continuations"]) == ("QUEUED", "", 1)
    assert [(m.kind, m.tap_id, m.inputs) for m in queued] == [("search_tap", tap.id, None)]
    assert len(exa.requests) == 5 and seams.read_domains == []  # stage 2 waits for the end
    assert (tap.provider_calls, tap.hosts_new) == (5, 7)

    later = _Provider(urls)
    run_tap(tap.id, seams=seams, providers=[later])  # the queued message's job
    # Nothing the first job ran is run again; coverage goes on at v5.
    assert [r.query for r in later.requests[:15]] == [
        f"v{i} physical chemistry" for i in range(5, 20)
    ]
    # Deep ranks every coverage query, the first job's too: v2 found most.
    assert [(r.query.split()[0], r.max_results) for r in later.requests[15:]] == [
        ("v2", 100), ("v0", 100), ("v1", 100), ("v3", 100),
    ]
    tap.refresh_from_db()
    assert (tap.state, tap.ending, tap.resume) == ("DONE", "COMPLETE", None)
    assert (tap.provider_calls, tap.hosts_new) == (24, 26)
    # Stage 2 read the hosts of both jobs.
    assert len(seams.read_domains) == 26 and "v0-12-0.org" in seams.read_domains
    assert WalletCharge.objects.filter(tap=tap, kind="SEARCH").count() == 24
    assert len(queued) == 1


def test_the_plateau_window_survives_a_continuation(tapping_student, clock) -> None:
    tap = request_tap(tapping_student, kind=FIRST)
    urls = _out_of_time_at(clock, 6)  # every query dry
    seams = _Seams(by_language={"en": _angles(30)})
    run_tap(tap.id, seams=seams, providers=[_Provider(urls)])
    later = _Provider(urls)
    run_tap(tap.id, seams=seams, providers=[later])
    # Six dry queries before the continuation, four after: ten in a row.
    assert len([r for r in later.requests if r.max_results < 100]) == 4
    assert _ended(tap) == ("DONE", "PLATEAU")


def test_money_stops_a_continued_first_search_at_the_reserve(tapping_student, clock) -> None:
    from apps.research.wallet import charge

    tap = request_tap(tapping_student, kind=FIRST)
    urls = _out_of_time_at(clock, 3, lambda r: [f"https://{r.query.split()[0]}-body.org/"])
    seams = _Seams(angles=_angles(150), reads=False)
    run_tap(tap.id, seams=seams, providers=[_Provider(urls, usd=1.0)])
    assert _ended(tap) == ("QUEUED", "")
    # A follow-up spends between the two jobs; the reserve is checked live.
    follow_up = request_tap(tapping_student, kind=FOLLOW_UP)
    charge(follow_up, kind="SEARCH", provider="exa", usd=Decimal("20"))
    run_tap(tap.id, seams=seams, providers=[_Provider(urls, usd=1.0)])
    assert SearchWallet.objects.get(id=tap.wallet_id).spent_usd == Decimal("90")
    assert _ended(tap) == ("DONE", "WALLET_SPENT")


def test_after_the_last_continuation_a_first_search_ends_time_cap(
    tapping_student, queued, clock, settings
) -> None:
    settings.FIRST_SEARCH_MAX_CONTINUATIONS = 2
    tap = request_tap(tapping_student, kind=FIRST)
    queued.clear()

    def urls(request, n):
        clock.now += 10_000  # every call runs its job's time out
        return [f"https://{request.query.split()[0]}-body.org/"]

    seams = _Seams(by_language={"en": _angles(20)}, reads=False)
    for _ in range(3):
        run_tap(tap.id, seams=seams, providers=[_Provider(urls)])
    assert len(queued) == 2
    assert _ended(tap) == ("DONE", "TIME_CAP")
    tap.refresh_from_db()
    assert tap.provider_calls == 3


def test_a_follow_up_keeps_its_single_run_time_cap(tapping_student, queued, clock) -> None:
    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    queued.clear()
    exa = _Provider(_out_of_time_at(clock, 2))
    run_tap(tap.id, seams=_Seams(angles=_angles(10)), providers=[exa])
    assert len(exa.requests) == 2 and queued == []
    assert _ended(tap) == ("DONE", "TIME_CAP")


def test_a_continuation_that_cannot_be_sent_stays_queued_for_the_redelivered_message(
    tapping_student, clock, monkeypatch
) -> None:
    """Saved and QUEUED first, sent second: when the send fails (or the worker
    dies between the two), SQS redelivers the message this job never deleted,
    and its claim continues the tap."""
    tap = request_tap(tapping_student, kind=FIRST)

    def down(message, **_):
        raise ConnectionError("sqs unreachable")

    monkeypatch.setattr(tap_module, "enqueue_research", down)
    urls = _out_of_time_at(clock, 2)
    seams = _Seams(by_language={"en": _angles(5)}, reads=False)
    with pytest.raises(ConnectionError):
        run_tap(tap.id, seams=seams, providers=[_Provider(urls)])
    tap.refresh_from_db()
    assert (tap.state, tap.ending) == ("QUEUED", "") and tap.resume is not None
    later = _Provider(urls)
    run_tap(tap.id, seams=seams, providers=[later])  # the redelivery
    assert later.requests[0].query == "v2 physical chemistry"
    assert _ended(tap)[0] == "DONE"


def test_a_first_search_between_its_jobs_is_not_owed_again(
    tapping_student, queued, automatic
) -> None:
    tap = _first_tap(tapping_student, state="QUEUED", ending="", age=timedelta(hours=1))
    SearchTap.objects.filter(id=tap.id).update(resume={"continuations": 3})
    tap_module.on_profile_saved(_profile(), _profile(allowed_countries=("DE", "NL")),
                                tapping_student)
    assert [t.kind for t in _taps()] == [FOLLOW_UP]


def test_a_provider_that_failed_in_one_job_is_asked_again_by_the_next(
    tapping_student, clock
) -> None:
    """A drop is this job's: a throttle 14 minutes ago is no reason for every
    later job of the search (and its Exa-only deep stage) to go without Exa."""
    from apps.research.egress import SourceBlocked

    jumped = []

    class ThrottledOnce(_Provider):
        def search(self, request, meter=None):
            self.requests.append(request)
            if not jumped:
                jumped.append(True)
                clock.now += 10_000
                raise SourceBlocked("api returned HTTP 429")
            yield f"https://{request.query.split()[0]}-{request.max_results}.org/"

    tap = request_tap(tapping_student, kind=FIRST)
    seams = _Seams(by_language={"en": _angles(5)}, reads=False)
    brave = _Provider(name="brave")
    run_tap(tap.id, seams=seams, providers=[ThrottledOnce(), brave])
    assert _ended(tap) == ("QUEUED", "")
    exa = ThrottledOnce()
    run_tap(tap.id, seams=seams, providers=[exa, _Provider(name="brave")])
    assert len(exa.requests) == 4 + 1  # coverage v1-v4, then deep at 100
    assert exa.requests[-1].max_results == 100


def test_an_error_with_calls_in_flight_charges_every_call_that_billed(
    tapping_student, settings
) -> None:
    import threading

    settings.TAP_PARALLEL_CALLS = 8
    lock, broke = threading.Lock(), threading.Event()

    class Breaking(_Provider):
        def search(self, request, meter=None):
            with lock:
                self.requests.append(request)
                n = len(self.requests)
            if n == 3:
                broke.set()
                raise RuntimeError("not the index refusing")
            broke.wait(timeout=2)  # all eight are in flight when the third breaks
            meter.charge(self.name, self._usd)
            yield from ()

    tap = request_tap(tapping_student, kind=FOLLOW_UP)
    exa = Breaking()
    with pytest.raises(RuntimeError):
        run_tap(tap.id, seams=_Seams(angles=_angles(20)), providers=[exa])
    # Eight sent, then one more for each of the two answers taken before the third.
    assert len(exa.requests) == 10
    assert WalletCharge.objects.filter(tap=tap, kind="SEARCH").count() == 10 - 1
    assert _ended(tap) == ("DONE", "FAILED")


def test_a_continuation_at_eight_wide_runs_nothing_twice_and_loses_no_charge(
    tapping_student, settings, clock
) -> None:
    settings.TAP_PARALLEL_CALLS = 8
    tap = request_tap(tapping_student, kind=FIRST)
    urls = _out_of_time_at(
        clock, 5, lambda r: [f"https://{r.query.split()[0]}-{r.max_results}.org/"]
    )
    seams = _Seams(by_language={"en": _angles(30)})
    first, later = _Provider(urls), _Provider(urls)
    run_tap(tap.id, seams=seams, providers=[first])
    assert _ended(tap) == ("QUEUED", "")
    run_tap(tap.id, seams=seams, providers=[later])
    asked = [(r.query, r.max_results) for r in first.requests + later.requests]
    assert len(asked) == len(set(asked))  # however the threads interleaved
    coverage = {q for q, n in asked if n < 100}
    assert coverage == {f"v{i} physical chemistry" for i in range(30)}
    assert len(asked) == 30 + 6  # and deep re-ran its top 20% once
    assert WalletCharge.objects.filter(tap=tap, kind="SEARCH").count() == len(asked)
    tap.refresh_from_db()
    assert (tap.provider_calls, tap.hosts_new, tap.state) == (36, 36, "DONE")


def _jump_after_preflight(monkeypatch, clock, number):
    """Run the job's time out on the main thread, right after the `number`-th
    preflight: which requests were sent before the deadline is then exact."""
    real, made = tap_module.preflight, count(1)

    def preflight(*args, **kwargs):
        price = real(*args, **kwargs)
        if next(made) == number:
            clock.now += 10_000
        return price

    monkeypatch.setattr(tap_module, "preflight", preflight)


def test_an_ending_found_while_draining_ends_the_search_rather_than_continuing_it(
    tapping_student, settings, clock, queued, monkeypatch
) -> None:
    from apps.research.egress import SourceBlocked

    class Down(_Provider):
        def search(self, request, meter=None):
            self.requests.append(request)
            raise SourceBlocked("api returned HTTP 401")
            yield  # pragma: no cover - a generator, like the real adapters

    settings.TAP_PARALLEL_CALLS = 8
    _jump_after_preflight(monkeypatch, clock, 1)  # request 1 sent, then out of time
    tap = request_tap(tapping_student, kind=FIRST)
    queued.clear()
    run_tap(tap.id, seams=_Seams(by_language={"en": _angles(5)}), providers=[Down()])
    assert _ended(tap) == ("DONE", "NO_PROVIDER") and queued == []


def test_a_plateau_found_while_draining_moves_the_next_job_to_the_next_stage(
    tapping_student, settings, clock, monkeypatch
) -> None:
    settings.TAP_PARALLEL_CALLS = 8
    # Requests 1-10 are sent (8, then one more per answer taken) before time runs
    # out; the dry window fills on the tenth while it drains.
    _jump_after_preflight(monkeypatch, clock, 10)
    tap = request_tap(tapping_student, kind=FIRST)
    seams = _Seams(by_language={"en": _angles(30)})
    exa = _Provider()
    run_tap(tap.id, seams=seams, providers=[exa])
    tap.refresh_from_db()
    assert len(exa.requests) == 10 and tap.resume["step"] == 1
    later = _Provider()
    run_tap(tap.id, seams=seams, providers=[later])
    # Nothing more of the plateaued coverage stage: only deep, its top 20% of ten.
    assert [r.max_results for r in later.requests] == [100, 100]
    assert _ended(tap) == ("DONE", "PLATEAU")


def test_a_continuation_that_cannot_be_saved_ends_the_tap_failed(
    tapping_student, clock, queued, monkeypatch
) -> None:
    """Never QUEUED in memory and STAGE1 in the database: that tap no claim
    would take and nothing would end. FAILED is terminal, its charges stand,
    and a failed first search is owed again on the next save."""
    from django.db import DatabaseError
    from django.db.models.sql.compiler import SQLUpdateCompiler

    real = SQLUpdateCompiler.execute_sql

    def execute_sql(self, *args, **kwargs):
        if any(f.name == "resume" and v is not None for f, _, v in self.query.values):
            raise DatabaseError("database went away")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(SQLUpdateCompiler, "execute_sql", execute_sql)
    tap = request_tap(tapping_student, kind=FIRST)
    queued.clear()
    with pytest.raises(DatabaseError):
        run_tap(tap.id, seams=_Seams(by_language={"en": _angles(5)}),
                providers=[_Provider(_out_of_time_at(clock, 1))])
    assert _ended(tap) == ("DONE", "FAILED") and queued == []
