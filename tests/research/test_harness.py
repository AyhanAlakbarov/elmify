"""The sweep harness (spec 6.7): two stop rules, provider decay, the pass."""

import random
from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from apps.research.angles import cycle_label, steering_angle
from apps.research.fetch import SweepBudget
from apps.research.harness import (
    BatchResult,
    PassConfig,
    _batches,
    decayed,
    ladder_rung,
    run_pass,
    stop_reason,
)
from apps.research.models import (
    ANGLE_KINDS,
    ClosedList,
    Organisation,
    RegisterEntry,
    SweepAngle,
    SweepDiscovery,
    SweepQuery,
    SweepRun,
)
from apps.research.providers import SearchMeter, SearchRequest
from apps.research.register import record_organisation
from apps.research.tally import found_by

NOW = datetime(2026, 9, 25, tzinfo=UTC)


def _b(n: int, verified: int, spend: float = 0.3, by: dict[str, int] | None = None) -> BatchResult:
    return BatchResult(
        number=n, spend_usd=spend, novel=verified, verified=verified,
        verified_by_provider=by if by is not None else ({"exa": verified} if verified else {}),
    )


_ECON = dict(value_per_award_usd=5.0, awards_per_verified_host=1.0)


@pytest.mark.parametrize(
    ("verified", "expected"),
    [
        ([3, 0, 0], None),                 # two empty batches is not three
        ([3, 0, 0, 0], "PLATEAU"),         # three is
        ([0, 0, 0], "PLATEAU"),            # a pass that never found anything stops at three
        ([0, 0, 1, 0, 0], None),           # the plateau restarts on any find
    ],
)
def test_the_plateau_rule(verified, expected) -> None:
    assert stop_reason([_b(i, v) for i, v in enumerate(verified, 1)], **_ECON) == expected


def test_the_economic_rule_fires_on_cost_per_award_not_on_emptiness() -> None:
    # $6 over three batches for one verified host = $6 an award > $5.
    batches = [_b(1, 0, 2.0), _b(2, 1, 2.0), _b(3, 0, 2.0)]
    assert stop_reason(batches, **_ECON) == "ECONOMIC"


def test_the_economic_rule_holds_while_finds_are_cheap() -> None:
    batches = [_b(1, 2, 0.3), _b(2, 1, 0.3), _b(3, 1, 0.3)]
    assert stop_reason(batches, **_ECON) is None


def test_awards_per_host_scales_the_economic_rule() -> None:
    batches = [_b(1, 0, 2.0), _b(2, 1, 2.0), _b(3, 0, 2.0)]
    assert stop_reason(batches, value_per_award_usd=5.0, awards_per_verified_host=2.0) is None


def test_an_economic_window_shorter_than_three_is_read_on_what_exists() -> None:
    assert stop_reason([_b(1, 1, 9.0)], **_ECON) == "ECONOMIC"


def test_a_decaying_provider_is_dropped_while_another_still_finds() -> None:
    batches = [
        _b(1, 2, by={"exa": 1, "brave": 1}),
        _b(2, 1, by={"exa": 1}),
        _b(3, 1, by={"exa": 1}),
        _b(4, 1, by={"exa": 1}),
    ]
    assert decayed(batches, ("exa", "brave")) == {"brave"}


def test_nobody_is_dropped_when_nobody_found_anything() -> None:
    """That window is the plateau rule's, not a verdict on one engine."""
    batches = [_b(1, 0), _b(2, 0), _b(3, 0)]
    assert decayed(batches, ("exa", "brave")) == set()


def test_nobody_is_dropped_before_three_batches() -> None:
    assert decayed([_b(1, 1, by={"exa": 1})], ("exa", "brave")) == set()


# --- ladder_rung (ruling R6: the rung is a row, read from ClosedList) ------


@pytest.mark.django_db
def test_a_register_rung_without_register_rows_is_refused() -> None:
    ClosedList.objects.create(
        slug="vgm_tr", title="VGM", country_code="TR",
        holder_kinds=["PRIVATE_FOUNDATION"], rung=1,
        source_url="https://example.org/vgm", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="FUNDING_READ", verified_on=date(2026, 9, 25),
    )
    with pytest.raises(ValueError, match="no RegisterEntry"):
        ladder_rung("TR", "PRIVATE_FOUNDATION")


@pytest.mark.django_db
def test_no_closed_list_row_gives_rung_four() -> None:
    assert ladder_rung("AZ", "PRIVATE_FOUNDATION") == (4, "")


@pytest.mark.django_db
def test_a_read_register_wins_its_rung() -> None:
    ClosedList.objects.create(
        slug="vgm_tr", title="VGM", country_code="TR",
        holder_kinds=["PRIVATE_FOUNDATION"], rung=1,
        source_url="https://example.org/vgm", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="FUNDING_READ", verified_on=date(2026, 9, 25),
    )
    RegisterEntry.objects.create(
        register="vgm_tr", external_key="1", name="TEV", resolution="UNRESOLVED",
        last_seen=NOW,
    )
    assert ladder_rung("TR", "PRIVATE_FOUNDATION") == (1, "vgm_tr")


@pytest.mark.django_db
def test_a_rung_zero_row_and_another_familys_row_are_ignored() -> None:
    ClosedList.objects.create(
        slug="enumerator", title="Enumerator", country_code="TR",
        holder_kinds=["PRIVATE_FOUNDATION"], rung=0,
        source_url="https://example.org/e", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="ENUMERATE_ONLY", verified_on=date(2026, 9, 25),
    )
    ClosedList.objects.create(
        slug="tr_employers", title="Employers", country_code="TR",
        holder_kinds=["EMPLOYER"], rung=2,
        source_url="https://example.org/employers", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="SIGNAL_ONLY", verified_on=date(2026, 9, 25),
    )
    assert ladder_rung("TR", "PRIVATE_FOUNDATION") == (4, "")


def _list(slug: str, country: str, kinds: list[str], rung: int, *, read: bool) -> None:
    ClosedList.objects.create(
        slug=slug, title=slug, country_code=country, holder_kinds=kinds, rung=rung,
        source_url=f"https://example.org/{slug}", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="SIGNAL_ONLY", verified_on=date(2026, 9, 25),
    )
    if read:
        RegisterEntry.objects.create(
            register=slug, external_key="1", name=slug, resolution="UNRESOLVED", last_seen=NOW,
        )


@pytest.mark.django_db
def test_a_bank_list_is_not_a_foundation_passs_rung() -> None:
    """Ruling R12: the ladder is the lists of the kinds the pass searches for
    (PASS_SHAPES), and banks are reached by register, never open-web search."""
    _list("az_banks", "AZ", ["BANK_OR_LENDER"], 2, read=False)
    assert ladder_rung("AZ", "PRIVATE_FOUNDATION") == (4, "")


@pytest.mark.django_db
def test_a_bilateral_list_is_not_a_government_passs_rung() -> None:
    _list("tr_bilateral", "TR", ["EMBASSY_BILATERAL"], 3, read=True)
    _list("tr_outbound_gov", "TR", ["NATIONAL_GOVERNMENT"], 3, read=True)
    assert ladder_rung("TR", "GOVERNMENT_SCHOLARSHIP") == (3, "tr_outbound_gov")


@pytest.mark.django_db
def test_an_unstated_list_does_not_win_a_foundation_pass() -> None:
    _list("tr_unstated", "TR", ["UNSTATED"], 2, read=True)
    assert ladder_rung("TR", "PRIVATE_FOUNDATION") == (4, "")


# --- run_pass ---------------------------------------------------------


class _Fake:
    """A provider that answers each call from a script, and charges $0.01."""

    def __init__(self, name: str, answers: list[list[str]]) -> None:
        self.name = name
        self._answers = answers
        self.requests: list[SearchRequest] = []

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterator[str]:
        self.requests.append(request)
        if meter is not None:
            meter.charge(self.name, 0.01)
        answer = self._answers.pop(0) if self._answers else []
        yield from answer


def _angles(languages=("tr", "en"), samples=2) -> None:
    for language in languages:
        for n in range(samples):
            for kind in ("APPLICATION", "FAQ"):
                SweepAngle.objects.create(
                    country_code="TR", family="PRIVATE_FOUNDATION", language=language,
                    angle=kind, sample=n, version=1, cycle="2026-2027",
                    query=f"{kind} {language} {n}", brave_terms=f"{kind} terms", written_by="t",
                )


def _classifier(verdicts: dict[str, tuple[str, bool]]):
    """Classify by domain: (kind, funds_students)."""
    def classify(org: Organisation) -> str:
        kind, funds = verdicts.get(org.primary_domain, ("UNSTATED", None))
        org.kind, org.funds_students, org.classified_at = kind, funds, NOW
        org.save(update_fields=["kind", "funds_students", "classified_at"])
        return "classified"
    return classify


def _config(**overrides) -> PassConfig:
    fields = dict(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=("tr", "en"), rung=4,
        register="", cycle="2026-2027", budget_usd=5.0,
    )
    fields.update(overrides)
    return PassConfig(**fields)


def _run(providers, verdicts, **overrides) -> SweepRun:
    return run_pass(
        _config(**overrides), providers=providers, classify=_classifier(verdicts),
        fetch_budget=SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 0}), now=NOW,
    )


@pytest.mark.django_db
def test_a_pass_asks_breadth_first_local_language_then_english() -> None:
    _angles()
    exa = _Fake("exa", [])
    _run([exa], {})
    asked = [(r.language, r.query.rsplit(" ", 1)[1]) for r in exa.requests]
    # Batches (sample 0, tr), (sample 0, en), (sample 1, tr); three empty is the plateau.
    assert asked == [("tr", "0")] * 2 + [("en", "0")] * 2 + [("tr", "1")] * 2
    assert all(r.max_results == 15 for r in exa.requests)
    assert all(r.terms.endswith(" terms") for r in exa.requests)


def _logging(log: list[tuple[str, str]]):
    class _Logged(_Fake):
        def search(self, request, meter=None):
            log.append((self.name, request.query))
            return super().search(request, meter)
    return _Logged


def _six_kinds() -> list[SweepAngle]:
    return [
        SweepAngle.objects.create(
            country_code="TR", family="PRIVATE_FOUNDATION", language="tr", angle=kind,
            sample=0, version=1, cycle="2026-2027", query=f"{kind} tr 0", written_by="t",
        )
        for kind in ANGLE_KINDS
    ]


@pytest.mark.django_db
def test_angle_order_within_a_batch_is_seeded_by_the_run() -> None:
    """A fixed order gives each angle the same position in every pass, so the
    per-angle tally would measure position, not yield. The order is seeded by
    the run's id: it changes between passes and is reproducible from the row."""
    angles = _six_kinds()

    def order(seed: UUID) -> list[str]:
        return [a.angle for a in _batches(angles, ("tr", "en"), random.Random(seed.int))[0]]

    one, two = UUID(int=1), UUID(int=2)
    assert order(one) == order(one)
    assert order(one) != order(two)
    assert sorted(order(one)) == sorted(ANGLE_KINDS)


@pytest.mark.django_db
def test_a_pass_asks_its_runs_seeded_order_and_providers_in_their_given_order() -> None:
    angles = _six_kinds()
    log: list[tuple[str, str]] = []
    logged = _logging(log)
    run = _run([logged("exa", []), logged("brave", [])], {}, languages=("tr",))
    expected = _batches(angles, ("tr",), random.Random(run.id.int))[0]
    assert log == [(name, a.query) for a in expected for name in ("exa", "brave")]


@pytest.mark.django_db
@pytest.mark.parametrize("order", [("exa", "brave"), ("brave", "exa")])
def test_every_provider_that_returned_a_verified_host_is_credited(order, monkeypatch) -> None:
    """Ruling R13: two providers returning the identical host on every ask
    both yield; neither decays, whichever is asked first."""
    from apps.research import harness

    _angles()                                         # 4 batches, 2 angles each
    hosts = [[f"https://h{i}-vakfi.org.tr/"] for i in range(8)]
    providers = [_Fake(name, [list(h) for h in hosts]) for name in order]
    seen: list[BatchResult] = []

    def spy(batches, names):
        seen[:] = batches
        return decayed(batches, names)

    monkeypatch.setattr(harness, "decayed", spy)
    run = _run(providers, {f"h{i}-vakfi.org.tr": ("PRIVATE_FOUNDATION", True) for i in range(8)})
    assert run.dropped_providers == []
    assert run.batches == 4
    assert [dict(b.verified_by_provider) for b in seen] == [{"exa": 2, "brave": 2}] * 4
    # The tally credits both too: returning a host second is still finding it.
    assert found_by(country_code="TR") == {
        ("PRIVATE_FOUNDATION", "exa"): 8, ("PRIVATE_FOUNDATION", "brave"): 8,
    }


@pytest.mark.django_db
def test_a_host_re_returned_in_a_later_batch_credits_the_tally_not_that_batchs_decay(
    monkeypatch,
) -> None:
    """Decay and the tally answer different questions (harness.py, tally.py
    comments at the credit sites): a provider that re-returns in batch 2 a
    host provider A already found in batch 1 is not new to batch 2, so it
    earns no decay credit there, but the tally still credits it -- it can
    reach the host, which is what the tally measures."""
    from apps.research import harness

    _angles(languages=("tr",), samples=2)              # 2 batches, 2 angles each
    host = "h-vakfi.org.tr"
    exa = _Fake("exa", [[f"https://{host}/"], []])      # batch 1: finds it on angle 1
    brave = _Fake("brave", [[], [], [f"https://{host}/"], []])  # batch 2: re-returns it
    seen: list[BatchResult] = []

    def spy(batches, names):
        seen[:] = batches
        return decayed(batches, names)

    monkeypatch.setattr(harness, "decayed", spy)
    _run([exa, brave], {host: ("PRIVATE_FOUNDATION", True)})
    assert [dict(b.verified_by_provider) for b in seen] == [{"exa": 1}, {}]
    assert found_by(country_code="TR") == {
        ("PRIVATE_FOUNDATION", "exa"): 1, ("PRIVATE_FOUNDATION", "brave"): 1,
    }


@pytest.mark.django_db
def test_only_a_host_of_the_passs_family_that_funds_students_counts_as_verified() -> None:
    _angles(languages=("tr",), samples=1)
    exa = _Fake("exa", [["https://tev.org.tr/burs", "https://meb.gov.tr/", "https://haber.com.tr/x"]])
    run = _run([exa], {
        "tev.org.tr": ("PRIVATE_FOUNDATION", True),
        "meb.gov.tr": ("NATIONAL_GOVERNMENT", True),   # funds students, wrong family
        "haber.com.tr": ("UNSTATED", True),            # UNSTATED never counts
    })
    verified = SweepDiscovery.objects.filter(run=run, verified_in_pass=True)
    assert [d.organisation.primary_domain for d in verified] == ["tev.org.tr"]
    assert SweepDiscovery.objects.filter(run=run).count() == 3


@pytest.mark.django_db
def test_a_held_host_is_not_a_discovery_and_a_register_bound_one_is_recaptured() -> None:
    _angles(languages=("tr",), samples=1)
    org = record_organisation(
        domain="tev.org.tr", name="TEV", kind="PRIVATE_FOUNDATION", country_code="TR",
        found_via="R1_REGISTER:vgm", status=Organisation.Status.REGISTERED,
    )
    RegisterEntry.objects.create(
        register="vgm_tr", external_key="1", name="TEV", resolution="RESOLVED",
        resolved_via="LISTED", organisation=org, last_seen=NOW,
    )
    exa = _Fake("exa", [["https://tev.org.tr/"], ["https://tev.org.tr/sss"]])
    run = _run([exa], {}, rung=1, register="vgm_tr")
    assert SweepDiscovery.objects.filter(run=run).count() == 0
    assert run.recaptured == 1                       # distinct, not per hit
    assert "R4_SEARCH:exa" in Organisation.objects.get(pk=org.pk).found_via


@pytest.mark.django_db
def test_the_pass_stops_on_the_plateau_and_records_why() -> None:
    _angles(languages=("tr", "en"), samples=3)        # 6 batches available
    exa = _Fake("exa", [["https://a-vakfi.org.tr/"]])  # one find, then nothing
    run = _run([exa], {"a-vakfi.org.tr": ("PRIVATE_FOUNDATION", True)})
    assert run.stop_reason == SweepRun.StopReason.PLATEAU
    assert run.batches == 4                           # the find, then three empty
    assert run.finished_at is not None


@pytest.mark.django_db
def test_a_short_angle_set_ends_exhausted_and_says_so() -> None:
    _angles(languages=("tr",), samples=1)             # one batch only
    run = _run([_Fake("exa", [])], {})
    assert run.stop_reason == SweepRun.StopReason.EXHAUSTED


@pytest.mark.django_db
def test_the_budget_is_checked_before_every_call() -> None:
    _angles()
    exa = _Fake("exa", [])
    run = _run([exa], {}, budget_usd=0.025)          # room for three $0.01 calls
    assert run.stop_reason == SweepRun.StopReason.BUDGET
    assert len(exa.requests) == 3
    assert run.search_usd == pytest.approx(0.03)


@pytest.mark.django_db
def test_the_budget_is_checked_before_every_classification_too() -> None:
    _angles(languages=("tr",), samples=1)             # one batch: two $0.01 asks
    exa = _Fake("exa", [["https://a.org.tr/", "https://b.org.tr/"]])
    budget = SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 0})
    calls: list[str] = []

    def classify(org: Organisation) -> str:
        calls.append(org.primary_domain)
        budget.spend("FIRECRAWL", 40)                 # $0.033: past the pass's budget
        return "classified"

    run = run_pass(
        _config(languages=("tr",), budget_usd=0.025), providers=[exa], classify=classify,
        fetch_budget=budget, now=NOW,
    )
    assert calls == ["a.org.tr"]
    assert run.stop_reason == SweepRun.StopReason.BUDGET
    assert SweepDiscovery.objects.filter(run=run).count() == 2   # b stays, unverified


@pytest.mark.django_db
def test_a_pass_over_a_previous_cycles_angles_is_refused() -> None:
    """Lever 6: a new cycle is a regeneration -- last cycle's time words would
    be asked as this cycle's."""
    _angles(languages=("tr",), samples=1)
    SweepAngle.objects.filter(language="tr", angle="FAQ").update(cycle="2025-2026")
    exa = _Fake("exa", [])
    with pytest.raises(ValueError, match="generate_sweep_angles"):
        _run([exa], {}, languages=("tr",))
    assert exa.requests == []
    assert not SweepRun.objects.exists()


@pytest.mark.django_db
def test_the_steering_interim_is_this_cycles_and_runs() -> None:
    steering_angle("TR", now=NOW)
    run = _run([_Fake("exa", [])], {}, languages=("tr",), cycle=cycle_label(NOW))
    assert run.stop_reason == SweepRun.StopReason.EXHAUSTED


@pytest.mark.django_db
def test_a_classifier_limit_stops_the_pass_rather_than_count_unverified_hosts() -> None:
    _angles(languages=("tr",), samples=2)
    exa = _Fake("exa", [["https://a.org.tr/"]])
    run = run_pass(
        _config(languages=("tr",)), providers=[exa], classify=lambda org: "rate_limited",
        fetch_budget=SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 0}), now=NOW,
    )
    assert run.stop_reason == SweepRun.StopReason.CLASSIFIER_LIMIT


@pytest.mark.django_db
def test_every_query_is_recorded_with_its_cost() -> None:
    _angles(languages=("tr",), samples=1)
    run = _run([_Fake("exa", []), _Fake("brave", [])], {})
    assert SweepQuery.objects.filter(run=run).count() == 4   # 2 angles x 2 providers
    assert all(q.cost_usd == pytest.approx(0.01) for q in SweepQuery.objects.filter(run=run))


@pytest.mark.django_db
def test_a_diaspora_pass_asks_only_its_own_home_languages_angles() -> None:
    for home in ("az", "tr"):
        for language in (home, "en"):
            SweepAngle.objects.create(
                country_code="DE", family="AFFINITY_OR_DIASPORA", home_language=home,
                language=language, angle="FAQ", sample=0, version=1, cycle="2026-2027",
                query=f"{home} {language}", written_by="t",
            )
    exa = _Fake("exa", [])
    run = _run(
        [exa], {}, country_code="DE", family="AFFINITY_OR_DIASPORA", languages=("az", "en"),
        home_language="az",
    )
    assert [r.query for r in exa.requests] == ["az az", "az en"]
    assert run.home_language == "az"


@pytest.mark.django_db
def test_a_pass_with_no_angles_is_refused() -> None:
    with pytest.raises(ValueError, match="generate_sweep_angles"):
        _run([_Fake("exa", [])], {})


# --- crash and halt safety: a discovery is written when the host is found,
# not after batch-end classification (review findings 1 and 2) ------------


class _RaisesOnCall:
    """A provider whose Nth call raises, after answering the earlier ones."""

    def __init__(self, name: str, answers: list[list[str]], raise_on_call: int) -> None:
        self.name = name
        self._answers = answers
        self._raise_on_call = raise_on_call
        self._calls = 0

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterator[str]:
        self._calls += 1
        if self._calls == self._raise_on_call:
            raise RuntimeError("provider unavailable")
        if meter is not None:
            meter.charge(self.name, 0.01)
        answer = self._answers.pop(0) if self._answers else []
        yield from answer


@pytest.mark.django_db
def test_a_provider_exception_still_leaves_a_discovery_for_the_earlier_novel_host() -> None:
    _angles(languages=("tr",), samples=1)  # one batch, two angles (APPLICATION, FAQ)
    exa = _RaisesOnCall("exa", [["https://a-vakfi.org.tr/"]], raise_on_call=2)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        _run([exa], {})
    run = SweepRun.objects.get(country_code="TR", family="PRIVATE_FOUNDATION")
    assert run.finished_at is None
    discovery = SweepDiscovery.objects.get(run=run)
    assert discovery.organisation.primary_domain == "a-vakfi.org.tr"
    assert discovery.verified_in_pass is False


@pytest.mark.django_db
def test_a_classifier_halt_stops_classifying_but_every_novel_host_keeps_its_row() -> None:
    _angles(languages=("tr",), samples=1)
    exa = _Fake("exa", [["https://a.org.tr/", "https://b.org.tr/"]])
    calls: list[str] = []

    def classify(org: Organisation) -> str:
        calls.append(org.primary_domain)
        return "rate_limited"

    run = run_pass(
        _config(languages=("tr",)), providers=[exa], classify=classify,
        fetch_budget=SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 0}), now=NOW,
    )
    assert calls == ["a.org.tr"]
    assert run.stop_reason == SweepRun.StopReason.CLASSIFIER_LIMIT
    assert SweepDiscovery.objects.filter(run=run).count() == 2
    assert not SweepDiscovery.objects.filter(run=run, verified_in_pass=True).exists()


@pytest.mark.django_db
def test_a_denylisted_host_is_refused_even_when_a_provider_returns_it() -> None:
    _angles(languages=("tr",), samples=1)
    exa = _Fake("exa", [["https://www.mastersportal.com/x", "https://a-vakfi.org.tr/"]])
    run = _run([exa], {})
    # Summed across the run's queries, not `.first()`: two angles (APPLICATION,
    # FAQ) share one batch and one run, so an unordered queryset's first row is
    # not guaranteed to be the one the fake provider actually answered.
    denied = SweepQuery.objects.filter(run=run).values_list("denied", flat=True)
    assert sum(denied) == 1
    assert not Organisation.objects.filter(primary_domain="mastersportal.com").exists()


@pytest.mark.django_db
def test_a_swept_row_claims_no_kind_or_country_it_has_not_established() -> None:
    _angles(languages=("tr",), samples=1)
    run_pass(
        _config(languages=("tr",)), providers=[_Fake("exa", [["https://abertay.ac.uk/"]])],
        classify=lambda org: "abstained",
        fetch_budget=SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 0}), now=NOW,
    )
    org = Organisation.objects.get(primary_domain="abertay.ac.uk")
    assert (org.kind, org.country_code) == ("UNSTATED", "")


@pytest.mark.django_db
def test_an_unkeyable_url_is_counted_and_skipped() -> None:
    _angles(languages=("tr",), samples=1)
    run = _run([_Fake("exa", [["https://192.0.2.1/x"]])], {})
    # Summed for the same reason as above: an unordered `.first()` is not
    # reliably the query the fake provider answered.
    seen = SweepQuery.objects.filter(run=run).values_list("seen", flat=True)
    assert sum(seen) == 1
    assert Organisation.objects.count() == 0
