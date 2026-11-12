"""The seams item 14 consumes (tap_seams.py) and their two real bindings.

The bindings read real ClosedList / RegisterEntry / SweepRun / SweepQuery /
SweepDiscovery rows, built the way test_harness.py and test_tally.py build them.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.research.models import (
    ClosedList,
    Organisation,
    RegisterEntry,
    SweepAngle,
    SweepDiscovery,
    SweepQuery,
    SweepRun,
)
from apps.research.register import record_organisation
from apps.research.seam_bindings import (
    CardHostReader,
    ClosedListRungSource,
    HarnessSweeper,
    ProgrammeAngleSource,
    SweepRunPassStates,
)
from apps.research.tap_seams import (
    AngleSource,
    CellSweeper,
    HostReader,
    NullSeams,
    PassState,
    PassStates,
    RungSource,
    bound_angles,
    bound_host_reader,
    bound_pass_states,
    bound_rungs,
    bound_sweeper,
)

NOW = datetime(2026, 9, 25, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _funder_check_live(settings) -> None:
    settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE = True


def test_null_seams_and_the_bindings_satisfy_every_protocol() -> None:
    # Annotated assignments: mypy checks each against its Protocol.
    null = NullSeams()
    angles: AngleSource = null
    passes: PassStates = null
    reader: HostReader = null
    sweeper: CellSweeper = null
    rungs: RungSource = null
    real_rungs: RungSource = ClosedListRungSource()
    real_passes: PassStates = SweepRunPassStates()
    assert all(seam is not None for seam in (angles, passes, reader, sweeper, rungs))
    assert real_rungs is not None and real_passes is not None
    assert PassState.never().swept is False
    assert PassState.never() == PassState(False, False, 0, "")


def test_what_is_bound_today() -> None:
    assert isinstance(bound_rungs(), ClosedListRungSource)
    assert isinstance(bound_pass_states(), SweepRunPassStates)
    assert isinstance(bound_angles(), ProgrammeAngleSource)
    assert isinstance(bound_host_reader(), CardHostReader)
    assert isinstance(bound_sweeper(), HarnessSweeper)


# --- ClosedListRungSource ----------------------------------------------------


def _list(slug: str, kinds: list[str], rung: int, *, country: str = "TR", **extra: object) -> None:
    ClosedList.objects.create(
        slug=slug, title=slug, country_code=country, holder_kinds=kinds, rung=rung,
        source_url=f"https://example.org/{slug}", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="SIGNAL_ONLY", verified_on=date(2026, 9, 25), **extra,
    )


def _entry(register: str, key: str, *, org: Organisation | None = None) -> None:
    if org is None:
        RegisterEntry.objects.create(
            register=register, external_key=key, name=key, resolution="UNRESOLVED",
            last_seen=NOW,
        )
    else:
        RegisterEntry.objects.create(
            register=register, external_key=key, name=key, resolution="RESOLVED",
            resolved_via="EMAIL", organisation=org, last_seen=NOW,
        )


def _org(domain: str, *, funds: bool) -> Organisation:
    org = record_organisation(domain=domain, name=domain, kind="UNSTATED", country_code="TR",
                              found_via="R0_EMAIL")
    Organisation.objects.filter(pk=org.pk).update(funds_students=funds, classified_at=NOW)
    return Organisation.objects.get(pk=org.pk)


@pytest.mark.django_db
def test_a_read_register_reports_listed_known_and_read() -> None:
    _list("vgm_tr", ["PRIVATE_FOUNDATION"], 1)
    funds, other = _org("a-vakfi.org.tr", funds=True), _org("b-vakfi.org.tr", funds=False)
    _entry("vgm_tr", "1", org=funds)
    _entry("vgm_tr", "2", org=funds)  # a second entry of the same body counts once
    _entry("vgm_tr", "3", org=other)
    _entry("vgm_tr", "4")
    (row,) = ClosedListRungSource().rungs("TR")
    assert (row.family, row.rung, row.register) == ("PRIVATE_FOUNDATION", 1, "vgm_tr")
    assert (row.listed, row.known, row.read, row.surveyed) == (4, 2, 1, True)


@pytest.mark.django_db
def test_the_printed_size_is_the_denominator_when_the_publisher_prints_one() -> None:
    _list("vgm_tr", ["PRIVATE_FOUNDATION"], 1, printed_size=4028)
    _entry("vgm_tr", "1")
    (row,) = ClosedListRungSource().rungs("TR")
    assert row.listed == 4028


@pytest.mark.django_db
def test_the_lowest_rung_wins_and_ties_go_by_slug() -> None:
    _list("z_hubs", ["PRIVATE_FOUNDATION"], 3)
    _list("b_register", ["RELIGIOUS"], 2)
    _list("a_register", ["POLITICAL_FOUNDATION"], 2)
    (row,) = ClosedListRungSource().rungs("TR")
    assert (row.rung, row.register) == (2, "a_register")


@pytest.mark.django_db
def test_each_family_gets_its_own_rung() -> None:
    _list("tr_foundations", ["PRIVATE_FOUNDATION"], 1)
    _list("tr_employers", ["EMPLOYER"], 2)
    rows = {row.family: row.rung for row in ClosedListRungSource().rungs("TR")}
    assert rows == {"PRIVATE_FOUNDATION": 1, "INDUSTRIAL_SPONSORSHIP": 2}


@pytest.mark.django_db
def test_rung_zero_rung_four_other_countries_and_unstated_are_no_rung() -> None:
    _list("enumerator", ["PRIVATE_FOUNDATION"], 0)
    _list("search_only", ["PRIVATE_FOUNDATION"], 4)
    _list("unplaced", ["UNSTATED"], 1)
    _list("az_foundations", ["PRIVATE_FOUNDATION"], 1, country="AZ")
    assert ClosedListRungSource().rungs("TR") == ()


@pytest.mark.django_db
def test_an_unread_list_is_listed_but_not_yet_read_never_zero_known() -> None:
    _list("tr_banks", ["BANK_OR_LENDER"], 2, printed_size=52)
    (row,) = ClosedListRungSource().rungs("TR")
    assert (row.family, row.surveyed, row.listed) == ("PRIVATE_FOUNDATION", False, 52)


# --- SweepRunPassStates ------------------------------------------------------


def _angle() -> SweepAngle:
    return SweepAngle.objects.create(
        country_code="TR", family="PRIVATE_FOUNDATION", language="tr", angle="APPLICATION",
        sample=0, version=1, cycle="2026-2027", query="burs başvurusu", written_by="t",
    )


def _run(*, started: datetime, finished: bool = True, stop: str = "PLATEAU",
         batches: int = 0, family: str = "PRIVATE_FOUNDATION") -> SweepRun:
    return SweepRun.objects.create(
        country_code="TR", family=family, languages=["tr", "en"], rung=4, cycle="2026-2027",
        started_at=started, finished_at=started + timedelta(hours=1) if finished else None,
        stop_reason=stop if finished else "", batches=batches,
    )


def _found(run: SweepRun, angle: SweepAngle, batch: int, domain: str, *, verified: bool) -> None:
    query = SweepQuery.objects.create(run=run, batch_number=batch, angle=angle, provider="exa")
    org = record_organisation(domain=domain, name=domain, kind="UNSTATED", country_code="",
                              found_via="R4_SEARCH:exa")
    SweepDiscovery.objects.create(run=run, query=query, organisation=org,
                                  verified_in_pass=verified)


@pytest.mark.django_db
def test_an_area_never_swept_reads_never() -> None:
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION") == PassState.never()


@pytest.mark.django_db
def test_an_unfinished_run_is_not_a_state() -> None:
    _run(started=NOW, finished=False)
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION") == PassState.never()


@pytest.mark.django_db
def test_the_latest_finished_run_is_the_state() -> None:
    _run(started=NOW - timedelta(days=10), stop="ECONOMIC")
    _run(started=NOW, stop="PLATEAU", batches=3)
    _run(started=NOW + timedelta(days=1), finished=False)  # still running: ignored
    _run(started=NOW + timedelta(days=2), family="GOVERNMENT_SCHOLARSHIP", stop="BUDGET")
    state = SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION")
    assert state.swept and state.stop_reason == "PLATEAU"
    assert state.past_economic_stop is False


@pytest.mark.django_db
def test_an_economic_stop_is_past_the_economic_stop() -> None:
    _run(started=NOW, stop="ECONOMIC", batches=2)
    state = SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION")
    assert state.past_economic_stop and state.stop_reason == "ECONOMIC"


@pytest.mark.django_db
def test_trailing_batches_count_back_to_the_last_verified_discovery() -> None:
    run, angle = _run(started=NOW, batches=5), _angle()
    _found(run, angle, 1, "a.org.tr", verified=True)
    _found(run, angle, 2, "b.org.tr", verified=True)
    _found(run, angle, 3, "c.org.tr", verified=False)  # found, not verified: no credit
    # batches 4 and 5 found nothing at all
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION").batches_without_new == 3


@pytest.mark.django_db
def test_a_run_that_never_verified_anything_is_empty_in_every_batch() -> None:
    _run(started=NOW, batches=3)
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION").batches_without_new == 3


@pytest.mark.django_db
def test_a_last_batch_that_verified_leaves_no_trailing_batches() -> None:
    run, angle = _run(started=NOW, stop="EXHAUSTED", batches=2), _angle()
    _found(run, angle, 2, "a.org.tr", verified=True)
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION").batches_without_new == 0


@pytest.mark.django_db
def test_the_bound_sweeper_runs_the_harness_pass(monkeypatch) -> None:
    from decimal import Decimal
    from types import SimpleNamespace
    from uuid import uuid4

    seen = {}

    def fake_pass(config, **kwargs):
        seen["config"] = config
        return SimpleNamespace(
            id=uuid4(), search_usd=0.5, fetch_usd=0.1, stop_reason="PLATEAU", batches=2,
            queries=SimpleNamespace(count=lambda: 12),
            discoveries=SimpleNamespace(count=lambda: 3),
        )

    monkeypatch.setattr("apps.research.seam_bindings.run_pass", fake_pass)
    outcome = HarnessSweeper(providers=[object()], classify=lambda org: "x").run(
        "AZ", "PRIVATE_FOUNDATION", budget_usd=2.0
    )
    assert seen["config"].budget_usd == 2.0 and outcome.stop_reason == "PLATEAU"
    assert outcome.new_hosts == 3 and outcome.cost_usd == Decimal("0.6")
    assert outcome.provider_calls == 12


@pytest.mark.django_db
def test_the_harness_sweeper_returns_none_when_the_harness_refuses(monkeypatch) -> None:
    def refuse(config, **kwargs):
        raise ValueError("no angles")

    monkeypatch.setattr("apps.research.seam_bindings.run_pass", refuse)
    assert HarnessSweeper(providers=[object()], classify=lambda org: "x").run(
        "AZ", "PRIVATE_FOUNDATION", budget_usd=2.0
    ) is None


@pytest.mark.django_db
def test_bound_sweeper_is_none_free_of_keys_is_unavailable(settings) -> None:
    settings.EXA_API_KEY = settings.BRAVE_API_KEY = ""
    assert bound_sweeper().run("AZ", "PRIVATE_FOUNDATION", budget_usd=1.0) is None


@pytest.mark.django_db
def test_the_harness_sweeper_refuses_while_the_level_check_is_not_live(settings, caplog) -> None:
    settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE = False
    sweeper = HarnessSweeper(providers=[object()], classify=lambda org: "x")
    assert sweeper.run("AZ", "PRIVATE_FOUNDATION", budget_usd=1.0) is None
    assert "funder level check not live (card reader slice 3)" in caplog.text


@pytest.mark.django_db
def test_card_host_reader_reads_and_persists_servable_awards() -> None:
    from decimal import Decimal

    from apps.funding.models import FundingOpportunity
    from apps.research.card_engine import Quote
    from apps.research.card_funding.card import AwardCard, Card, Field, Track
    from apps.research.card_funding.parse import Value

    def _shown(name: str, val: object, quote: str) -> Field:
        return Field(
            name=name,
            state="shown",
            values=(
                Value(
                    value=val,
                    quote=Quote(quote, "L1.text"),
                    source="https://new-foundation.de/",
                    decisions=(),
                ),
            ),
        )

    def fake_read(org: Organisation, url: str, budget_usd: float) -> Card:
        assert org.primary_domain == "new-foundation.de"
        assert url == "https://new-foundation.de/"
        assert budget_usd == 0.25
        award = AwardCard(
            name="Foundation Master Stipend",
            name_quote=Quote("Foundation Master Stipend", "L1.text"),
            fields={
                "target_level": _shown("target_level", "master", "for Master's students"),
                "money_form": _shown("money_form", "grant", "scholarship grant"),
                "tuition_level": _shown("tuition_level", "full", "full tuition fee waiver"),
            },
            holds=(),
            cycle=2027,
        )
        return Card(
            program_id=None,
            source_url=url,
            lang="en",
            outcome="read",
            tracks=(Track(name="", awards=(award,)),),
            cost_usd=0.04,
        )

    reader = CardHostReader(read_card_fn=fake_read)
    res = reader.read("new-foundation.de", max_usd=Decimal("1.00"))
    assert res is not None
    assert res.outcome == "found"
    assert res.awards_served == 1
    assert res.cost_usd == Decimal("0.04")
    opp = FundingOpportunity.objects.get(name="Foundation Master Stipend")
    assert opp.served is True
    assert opp.scope_type == "HOLDER"


@pytest.mark.django_db
def test_card_host_reader_returns_none_when_reader_keys_missing(settings, monkeypatch) -> None:
    settings.OPENROUTER_API_KEY = ""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from decimal import Decimal

    assert bound_host_reader().read("new-foundation.de", max_usd=Decimal("0.50")) is None


@pytest.mark.django_db
def test_card_host_reader_uses_seed_urls_and_attaches_programme_scholarships() -> None:
    from decimal import Decimal
    from uuid import uuid4

    from apps.funding.models import FundingOpportunity, Institution, Program
    from apps.research.card_engine import Quote
    from apps.research.card_funding.card import AwardCard, Card, Field, Hold, Track
    from apps.research.card_funding.parse import Value

    strasbourg = Institution.objects.create(
        canonical_key=f"inst:{uuid4()}",
        name="University of Strasbourg",
        country_code="FR",
        official_website="https://www.unistra.fr",
    )
    csc_prog = Program.objects.create(
        canonical_key=f"prog:{uuid4()}",
        institution=strasbourg,
        origin_domain="unistra.fr",
        evidence_domain="unistra.fr",
        name="Master in Chemistry — Complex Systems Chemistry (CSC)",
        campus_name="Main",
        city="Strasbourg",
        country_code="FR",
        location_key="FR-STRASBOURG",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    Program.objects.create(
        canonical_key=f"prog:{uuid4()}",
        institution=strasbourg,
        origin_domain="unistra.fr",
        evidence_domain="unistra.fr",
        name="Master in Polymer Science",
        campus_name="Main",
        city="Strasbourg",
        country_code="FR",
        location_key="FR-STRASBOURG",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )

    def _shown(name: str, val: object, quote: str, src_url: str) -> Field:
        return Field(
            name=name,
            state="shown",
            values=(
                Value(
                    value=val,
                    quote=Quote(quote, "L1.text"),
                    source=src_url,
                    decisions=(),
                ),
            ),
        )

    seen_urls: list[str] = []

    def fake_read(org: Organisation, url: str, budget_usd: float) -> Card:
        seen_urls.append(url)
        award = AwardCard(
            name="EUR Complex Systems Chemistry (CSC) Master Scholarship",
            name_quote=Quote("EUR Complex Systems Chemistry (CSC) Master Scholarship", "L1.text"),
            fields={
                "target_level": _shown("target_level", "master", "for Master's students", url),
                "money_form": _shown("money_form", "grant", "EUR 7,200 per year grant", url),
                "living_level": _shown("living_level", "partial", "EUR 600/month stipend", url),
            },
            holds=(Hold(reason="unresolved_split", field="dates", detail="dates_split"),),
            cycle=2027,
        )
        return Card(
            program_id=None,
            source_url=url,
            lang="en",
            outcome="read",
            tracks=(Track(name="CSC Graduate School", awards=(award,)),),
            cost_usd=0.05,
        )

    reader = CardHostReader(read_card_fn=fake_read)
    seed_url = "https://csc.unistra.fr/master-of-csc-chemistry/scholarships"
    res = reader.read(
        "unistra.fr",
        max_usd=Decimal("1.00"),
        seed_urls=(seed_url,),
    )
    assert res is not None
    assert res.outcome == "found"
    assert res.awards_served == 1
    assert seen_urls == [seed_url]
    opp = FundingOpportunity.objects.get(
        name="EUR Complex Systems Chemistry (CSC) Master Scholarship"
    )
    assert opp.served is True
    assert opp.scope_type == "PROGRAM"
    assert opp.program_id == csc_prog.id
    assert opp.unconfirmed == "dates"


def test_build_university_funding_queries_uses_localized_discipline_terms() -> None:
    from apps.research.seam_bindings import build_university_funding_queries

    it_queries = build_university_funding_queries(
        "unipd.it", field="AI with chemistry", country_code="IT"
    )
    assert len(it_queries) == 2
    assert 'site:unipd.it ("digital chemistry"' in it_queries[0]
    assert "chimica digitale" in it_queries[1]
    assert "borse di studio" in it_queries[1]

    fr_queries = build_university_funding_queries(
        "unistra.fr", field="AI with chemistry", country_code="FR"
    )
    assert len(fr_queries) == 2
    assert "chimie numérique" in fr_queries[1] or "chémoinformatique" in fr_queries[1]
    assert "bourse" in fr_queries[1]


def test_wikidata_and_openalex_subject_grounding_helpers() -> None:
    from apps.research.wikidata import lookup_openalex_keywords, lookup_subject_translations

    def fake_get(url: str, *, params: dict | None = None, **kwargs):
        params = params or {}
        if "openalex.org" in url:
            return {
                "results": [
                    {"display_name": "Cheminformatics"},
                    {"display_name": "Digital Chemistry"},
                ]
            }
        if params.get("action") == "wbsearchentities":
            return {
                "search": [
                    {
                        "id": "Q610620",
                        "label": "chemoinformatics",
                        "aliases": ["cheminformatics"],
                    }
                ]
            }
        if params.get("action") == "wbgetentities":
            return {
                "entities": {
                    "Q610620": {
                        "labels": {
                            "en": {"value": "chemoinformatics"},
                            "de": {"value": "Chemoinformatik"},
                            "fr": {"value": "chémoinformatique"},
                            "it": {"value": "chemoinformatica"},
                        },
                        "aliases": {
                            "en": [{"value": "cheminformatics"}],
                        },
                    }
                }
            }
        return {}

    translations = lookup_subject_translations(
        "chemoinformatics", languages=("en", "de", "fr", "it"), get=fake_get
    )
    assert translations["de"] == ("Chemoinformatik",)
    assert translations["fr"] == ("chémoinformatique",)
    assert translations["it"] == ("chemoinformatica",)

    keywords = lookup_openalex_keywords("AI with chemistry", get=fake_get)
    assert keywords == ("cheminformatics", "digital chemistry")


@pytest.mark.django_db
def test_programme_angle_source_fallback_and_cctld_inference() -> None:
    from apps.research.seam_bindings import (
        ProgrammeAngleSource,
        build_university_funding_queries,
        harvest_tap_seed_urls,
    )

    # Without fallback_on_empty, an empty DB returns ()
    assert ProgrammeAngleSource(fallback_on_empty=False).programme_angles(
        level="MASTER", language="it"
    ) == ()
    # With fallback_on_empty=True, deterministic fallback templates are returned
    it_angles = ProgrammeAngleSource(fallback_on_empty=True).programme_angles(
        level="MASTER", language="it"
    )
    assert len(it_angles) >= 2
    assert all("{field}" in a.template for a in it_angles)

    # ccTLD inference when country_code is empty ("" -> "KR" for .ac.kr, "IT" for .it)
    kr_queries = build_university_funding_queries(
        "snu.ac.kr", field="Computer Science", country_code=""
    )
    assert len(kr_queries) == 2
    assert "장학금" in kr_queries[1]

    fr_seeds = harvest_tap_seed_urls("FR", field="chemistry")
    assert any("unistra.fr" in u or "psl.eu" in u for u in fr_seeds)

    # ccTLD inference & localized funding terms for Saudi Arabia (.edu.sa -> SA -> ar)
    # and Indonesia (.ac.id -> ID -> id)
    sa_queries = build_university_funding_queries(
        "ksu.edu.sa", field="Computer Science", country_code=""
    )
    assert len(sa_queries) == 2
    assert "منحة" in sa_queries[1]
    assert "ماجستير" in sa_queries[1]

    id_queries = build_university_funding_queries(
        "ui.ac.id", field="Computer Science", country_code=""
    )
    assert len(id_queries) == 2
    assert "beasiswa" in id_queries[1]


@pytest.mark.django_db
def test_card_host_reader_attaches_joint_domain_and_multi_programme_awards() -> None:
    from decimal import Decimal
    from uuid import uuid4

    from apps.funding.models import (
        FundingOpportunity,
        FundingOpportunityProgram,
        Institution,
        Program,
    )
    from apps.research.card_engine import Quote
    from apps.research.card_funding.card import AwardCard, Card, Field, Track
    from apps.research.card_funding.parse import Value

    def _shown(name: str, val: object, quote: str, src_url: str) -> Field:
        return Field(
            name=name,
            state="shown",
            values=(
                Value(
                    value=val,
                    quote=Quote(quote, "L1.text"),
                    source=src_url,
                    decisions=(),
                ),
            ),
        )

    # 1. Single-programme JOINT (Erasmus Mundus) domain where the URL/card text
    # does not repeat the programme's full tokens -> attaches to the JOINT Program.
    joint_prog = Program.objects.create(
        canonical_key=f"prog:joint:{uuid4()}",
        institution=None,
        provision_type=Program.ProvisionType.JOINT,
        origin_domain="emjm-chemoinfo.eu",
        evidence_domain="emjm-chemoinfo.eu",
        name="Joint Master in Computational Materials Discovery",
        campus_name="Consortium",
        city="Strasbourg",
        country_code="FR",
        location_key="FR-STRASBOURG",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )

    def fake_joint_read(org: Organisation, url: str, budget_usd: float) -> Card:
        award = AwardCard(
            name="EMJM Student Scholarship",
            name_quote=Quote("EMJM Student Scholarship", "L1.text"),
            fields={
                "target_level": _shown("target_level", "master", "for Master's students", url),
                "money_form": _shown("money_form", "grant", "full scholarship", url),
                "tuition_level": _shown("tuition_level", "full", "full fee waiver", url),
                "living_level": _shown("living_level", "full", "EUR 1,400/month", url),
            },
            holds=(),
            cycle=2027,
        )
        return Card(
            program_id=None,
            source_url=url,
            lang="en",
            outcome="read",
            tracks=(Track(name="Consortium Track", awards=(award,)),),
            cost_usd=0.05,
        )

    joint_reader = CardHostReader(read_card_fn=fake_joint_read)
    res_joint = joint_reader.read(
        "emjm-chemoinfo.eu",
        max_usd=Decimal("1.00"),
        seed_urls=("https://emjm-chemoinfo.eu/apply/scholarships",),
    )
    assert res_joint is not None and res_joint.outcome == "found"
    joint_opp = FundingOpportunity.objects.get(name="EMJM Student Scholarship")
    assert joint_opp.scope_type == "PROGRAM"
    assert joint_opp.program_id == joint_prog.id

    # 2. Multi-programme graduate school on one university domain -> links all
    # matching programmes via FundingOpportunityProgram.
    psl = Institution.objects.create(
        canonical_key=f"inst:{uuid4()}",
        name="Université PSL",
        country_code="FR",
        official_website="https://psl.eu",
    )
    prog_a = Program.objects.create(
        canonical_key=f"prog:{uuid4()}",
        institution=psl,
        origin_domain="psl.eu",
        evidence_domain="psl.eu",
        name="Master in Chemistry and Life Sciences — Bioimaging Track",
        campus_name="Main",
        city="Paris",
        country_code="FR",
        location_key="FR-PARIS",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    prog_b = Program.objects.create(
        canonical_key=f"prog:{uuid4()}",
        institution=psl,
        origin_domain="psl.eu",
        evidence_domain="psl.eu",
        name="Master in Chemistry and Life Sciences — Chemical Biology Track",
        campus_name="Main",
        city="Paris",
        country_code="FR",
        location_key="FR-PARIS",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    prog_c = Program.objects.create(
        canonical_key=f"prog:{uuid4()}",
        institution=psl,
        origin_domain="psl.eu",
        evidence_domain="psl.eu",
        name="Master in Green Chemistry",
        campus_name="Main",
        city="Paris",
        country_code="FR",
        location_key="FR-PARIS",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )

    def fake_multi_read(org: Organisation, url: str, budget_usd: float) -> Card:
        award = AwardCard(
            name="PSL Chemistry and Life Sciences Graduate Fellowship",
            name_quote=Quote("PSL Chemistry and Life Sciences Graduate Fellowship", "L1.text"),
            fields={
                "target_level": _shown("target_level", "master", "for Master's students", url),
                "money_form": _shown("money_form", "grant", "EUR 1,000/month", url),
                "living_level": _shown("living_level", "full", "EUR 1,000/month stipend", url),
            },
            holds=(),
            cycle=2027,
        )
        return Card(
            program_id=None,
            source_url=url,
            lang="en",
            outcome="read",
            tracks=(Track(name="Chemistry and Life Sciences", awards=(award,)),),
            cost_usd=0.05,
        )

    multi_reader = CardHostReader(read_card_fn=fake_multi_read)
    res_multi = multi_reader.read(
        "psl.eu",
        max_usd=Decimal("1.00"),
        seed_urls=("https://psl.eu/graduate-program-chemistry-life-sciences/scholarships",),
    )
    assert res_multi is not None and res_multi.outcome == "found"
    multi_opp = FundingOpportunity.objects.get(
        name="PSL Chemistry and Life Sciences Graduate Fellowship"
    )
    linked_prog_ids = set(
        FundingOpportunityProgram.objects.filter(opportunity=multi_opp).values_list(
            "program_id", flat=True
        )
    )
    assert linked_prog_ids == {prog_a.id, prog_b.id}
    assert prog_c.id not in linked_prog_ids

    # 3. Secondary OrganisationDomain for the same university Organisation ->
    # CardHostReader.read on the secondary domain still resolves programmes
    # recorded on the primary domain.
    from apps.research.models import OrganisationDomain

    psl_org = record_organisation(
        domain="psl.eu",
        name="Université PSL",
        kind="UNSTATED",
        country_code="FR",
        found_via="CLOSED_LIST:test",
    )
    OrganisationDomain.objects.get_or_create(
        registrable_domain="chimie-psl.fr",
        defaults={"organisation": psl_org},
    )

    def fake_secondary_domain_read(org: Organisation, url: str, budget_usd: float) -> Card:
        award = AwardCard(
            name="PSL Bioimaging Track Excellence Grant",
            name_quote=Quote("PSL Bioimaging Track Excellence Grant", "L1.text"),
            fields={
                "target_level": _shown("target_level", "master", "for Master's students", url),
                "money_form": _shown("money_form", "grant", "EUR 1,200/month", url),
                "living_level": _shown("living_level", "full", "EUR 1,200/month stipend", url),
            },
            holds=(),
            cycle=2027,
        )
        return Card(
            program_id=None,
            source_url=url,
            lang="en",
            outcome="read",
            tracks=(Track(name="Bioimaging Track", awards=(award,)),),
            cost_usd=0.05,
        )

    sec_reader = CardHostReader(read_card_fn=fake_secondary_domain_read)
    res_sec = sec_reader.read(
        "chimie-psl.fr",
        max_usd=Decimal("1.00"),
        seed_urls=("https://chimie-psl.fr/master-bioimaging/scholarships",),
    )
    assert res_sec is not None and res_sec.outcome == "found"
    sec_opp = FundingOpportunity.objects.get(name="PSL Bioimaging Track Excellence Grant")
    assert sec_opp.scope_type == "PROGRAM"
    assert sec_opp.program_id == prog_a.id







