"""The operator entry: dry-run by default, writes gated on the hold-out, Diffbot on terms."""

from datetime import date

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.research import closed_lists, vocabulary
from apps.research.egress import SourceBlocked
from apps.research.management.commands import resolve_register
from apps.research.models import ClosedList, Organisation, RegisterEntry
from apps.research.resolver import CallBudgetSpent, FetchBudgetSpent, Resolution

pytestmark = pytest.mark.django_db


class FakeResolver:
    def __init__(self, answers, asked=None):
        self.answers, self.asked = answers, asked if asked is not None else []

    def resolve(self, query):
        self.asked.append(query)
        answer = self.answers[query.names[0]]
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer()
        return answer


def _entries(*names, register="vgm_tr", **fields):
    for i, name in enumerate(names):
        RegisterEntry.objects.create(register=register, external_key=f"{register}:{i}", name=name,
                                     names=[name], resolution=RegisterEntry.Resolution.UNRESOLVED,
                                     last_seen=timezone.now(), **fields)


def _fake(monkeypatch, answers):
    """Patch build_resolver; return what it was asked to build and each query."""
    built: list[dict] = []
    asked: list = []

    def build(**kw):
        built.append(kw)
        return FakeResolver(answers, asked)

    monkeypatch.setattr(resolve_register, "build_resolver", build)
    return built, asked


def _closed_list(monkeypatch, tmp_path, slug, country_code):
    monkeypatch.setattr(closed_lists, "LISTS_DIR", tmp_path)
    (tmp_path / f"{slug}.csv").write_text("rows file\n", encoding="utf-8")
    ClosedList.objects.create(
        slug=slug, title=slug, country_code=country_code, holder_kinds=[], rung=1,
        source_url="https://example.org/list", maintainer="own compilation",
        carries_purpose=True, carries_website=True, reuse_terms=ClosedList.Terms.OWN_COMPILATION,
        is_denominator=True, read_policy=ClosedList.ReadPolicy.CLASSIFY,
        verified_on=date(2026, 9, 25),
    )


@pytest.fixture
def keys(settings):
    settings.TAVILY_API_KEY = "t"
    settings.RESOLVER_WRITES_ENABLED = True
    return settings


def test_write_is_refused_until_the_gate_passed(keys) -> None:
    keys.RESOLVER_WRITES_ENABLED = False
    with pytest.raises(CommandError, match="hold-out"):
        call_command("resolve_register", "--register", "vgm_tr", "--write")


def test_diffbot_is_refused_on_stale_terms(keys) -> None:
    keys.DIFFBOT_TOKEN, keys.DIFFBOT_TERMS_READ_ON = "d", "2026-01-01"
    with pytest.raises(CommandError, match="terms"):
        call_command("resolve_register", "--register", "vgm_tr", "--diffbot", "--write")


def test_an_unknown_register_names_the_ones_served(keys, monkeypatch, tmp_path) -> None:
    _closed_list(monkeypatch, tmp_path, "az_banks", "AZ")
    with pytest.raises(CommandError, match="one of: az_banks, pointer, vgm_tr"):
        call_command("resolve_register", "--register", "vgm")


def test_a_list_without_a_rows_file_is_not_served(keys, monkeypatch, tmp_path) -> None:
    _closed_list(monkeypatch, tmp_path, "az_banks", "AZ")
    (tmp_path / "az_banks.csv").unlink()
    with pytest.raises(CommandError, match="one of: pointer, vgm_tr$"):
        call_command("resolve_register", "--register", "az_banks")


def test_a_dry_run_prints_and_writes_nothing(keys, monkeypatch, capsys) -> None:
    _entries("HRANT DİNK VAKFI")
    _fake(monkeypatch, {"HRANT DİNK VAKFI": Resolution("hrantdink.org", "SEARCH_TITLE",
                                                        names=("HRANT DİNK VAKFI",))})
    call_command("resolve_register", "--register", "vgm_tr")
    out = capsys.readouterr().out
    assert "hrantdink.org" in out and "dry run: nothing written" in out
    assert RegisterEntry.objects.get().resolution == "UNRESOLVED"


def test_a_spent_budget_stops_the_run_and_leaves_the_rest_untouched(keys, monkeypatch,
                                                                     capsys) -> None:
    _entries("A VAKFI", "B VAKFI")
    _fake(monkeypatch, {"A VAKFI": Resolution(reason="NO_CANDIDATE", names=("A VAKFI",)),
                        "B VAKFI": CallBudgetSpent("spent")})
    call_command("resolve_register", "--register", "vgm_tr", "--write")
    assert RegisterEntry.objects.get(name="A VAKFI").unresolved_reason == "NO_CANDIDATE"
    assert RegisterEntry.objects.get(name="B VAKFI").resolution_attempted_at is None
    assert "stopped" in capsys.readouterr().out


def test_a_wikidata_failure_stops_the_run_like_a_spent_budget(keys, monkeypatch, capsys) -> None:
    _entries("A VAKFI", "B VAKFI")
    _fake(monkeypatch, {"A VAKFI": SourceBlocked("wikidata answered 429"),
                        "B VAKFI": Resolution(reason="NO_CANDIDATE", names=("B VAKFI",))})
    call_command("resolve_register", "--register", "vgm_tr", "--write")
    assert "stopped: SourceBlocked" in capsys.readouterr().out
    assert not RegisterEntry.objects.filter(resolution_attempted_at__isnull=False).exists()


def test_a_closed_list_resolves_with_each_row_s_own_country_and_kind(keys, monkeypatch,
                                                                     tmp_path) -> None:
    _closed_list(monkeypatch, tmp_path, "az_banks", "AZ")
    _entries("Kapital Bank ASC", register="az_banks", kind="BANK_OR_LENDER")
    RegisterEntry.objects.create(
        register="az_banks", external_key="tr", name="Ziraat Bankası Bakü", names=[],
        resolution="UNRESOLVED", last_seen=timezone.now(), country_code="TR",
        kind="BANK_OR_LENDER",
    )
    built, asked = _fake(monkeypatch, {
        "Kapital Bank ASC": Resolution("kapitalbank.az", "SEARCH_SLUG",
                                       names=("Kapital Bank ASC",)),
        "Ziraat Bankası Bakü": Resolution(reason="TITLE_MISMATCH", names=("Ziraat Bankası Bakü",)),
    })
    call_command("resolve_register", "--register", "az_banks", "--write")
    assert sorted(b["country_code"] for b in built) == ["AZ", "TR"]
    assert sorted(q.country_code for q in asked) == ["AZ", "TR"]
    org = Organisation.objects.get(primary_domain="kapitalbank.az")
    assert (org.country_code, org.kind) == ("AZ", "BANK_OR_LENDER")
    assert RegisterEntry.objects.get(external_key="tr").unresolved_reason == "TITLE_MISMATCH"


def test_every_country_s_resolver_shares_the_run_s_caps(keys, monkeypatch, tmp_path) -> None:
    keys.DIFFBOT_TOKEN, keys.DIFFBOT_TERMS_READ_ON = "d", timezone.now().date().isoformat()
    _closed_list(monkeypatch, tmp_path, "az_banks", "AZ")
    _entries("Kapital Bank ASC", register="az_banks", kind="BANK_OR_LENDER")
    RegisterEntry.objects.create(
        register="az_banks", external_key="tr", name="Ziraat Bankası Bakü", names=[],
        resolution="UNRESOLVED", last_seen=timezone.now(), country_code="TR",
        kind="BANK_OR_LENDER",
    )
    none = Resolution(reason="NO_CANDIDATE", names=("x",))
    built, _ = _fake(monkeypatch, {"Kapital Bank ASC": none, "Ziraat Bankası Bakü": none})
    call_command("resolve_register", "--register", "az_banks", "--diffbot", "--write")
    assert len(built) == 2
    for name in ("tavily", "diffbot", "budget"):
        assert built[0][name] is built[1][name], name
    assert built[0]["diffbot"] is not None


def test_a_row_of_no_country_is_skipped_and_never_written(keys, monkeypatch, tmp_path,
                                                          capsys) -> None:
    _closed_list(monkeypatch, tmp_path, "igo_regional_global", "")
    _entries("Islamic Development Bank", register="igo_regional_global",
             kind="INTERGOVERNMENTAL")
    built, asked = _fake(monkeypatch, {})
    call_command("resolve_register", "--register", "igo_regional_global", "--write")
    out = capsys.readouterr().out
    assert "Islamic Development Bank -> - (no country)" in out
    assert "'no country': 1" in out
    assert built == [] and asked == []
    assert RegisterEntry.objects.get().resolution_attempted_at is None


def test_a_row_bound_meanwhile_is_left_standing_and_the_run_goes_on(keys, monkeypatch,
                                                                    capsys) -> None:
    _entries("A VAKFI", "B VAKFI")

    def bound_meanwhile():
        RegisterEntry.objects.filter(name="A VAKFI").update(resolution="CONFLICT")
        return Resolution(reason="NO_CANDIDATE", names=("A VAKFI",))

    _fake(monkeypatch, {"A VAKFI": bound_meanwhile,
                        "B VAKFI": Resolution(reason="NO_CANDIDATE", names=("B VAKFI",))})
    call_command("resolve_register", "--register", "vgm_tr", "--write")
    out = capsys.readouterr().out
    assert "not written" in out and "'MOVED_ON': 1" in out
    assert RegisterEntry.objects.get(name="A VAKFI").unresolved_reason == ""
    assert RegisterEntry.objects.get(name="B VAKFI").unresolved_reason == "NO_CANDIDATE"


def test_a_missing_vocabulary_is_refused_before_any_call(keys, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vocabulary, "DATA_DIR", tmp_path)
    vocabulary.load_vocabulary.cache_clear()
    _entries("A VAKFI")
    try:
        with pytest.raises(CommandError, match="build_resolver_vocabulary"):
            call_command("resolve_register", "--register", "vgm_tr")
    finally:
        vocabulary.load_vocabulary.cache_clear()
    assert RegisterEntry.objects.get().resolution_attempted_at is None


# --- Review of Task 9: no paid call escapes the Diffbot meter; skips never
# starve the queue. ---


def test_a_dry_run_may_not_ask_diffbot(keys) -> None:
    """The meter is diffbot_asked_at, written only by --write: a dry run asking
    Diffbot would spend credits no cap counts, every run, on the same names."""
    keys.DIFFBOT_TOKEN, keys.DIFFBOT_TERMS_READ_ON = "d", timezone.now().date().isoformat()
    with pytest.raises(CommandError, match="--diffbot needs --write"):
        call_command("resolve_register", "--register", "vgm_tr", "--diffbot")


def test_a_terms_read_dated_in_the_future_is_no_read(keys) -> None:
    keys.DIFFBOT_TOKEN, keys.DIFFBOT_TERMS_READ_ON = "d", "2099-01-01"
    with pytest.raises(CommandError, match="terms"):
        call_command("resolve_register", "--register", "vgm_tr", "--diffbot", "--write")


def test_a_budget_stop_verifying_diffbot_s_answer_still_meters_the_call(keys, monkeypatch,
                                                                        capsys) -> None:
    keys.DIFFBOT_TOKEN, keys.DIFFBOT_TERMS_READ_ON = "d", timezone.now().date().isoformat()
    _entries("A VAKFI")
    spent = FetchBudgetSpent("FIRECRAWL: 100 of 100 credits spent")
    spent.diffbot_asked = True
    _fake(monkeypatch, {"A VAKFI": spent})
    call_command("resolve_register", "--register", "vgm_tr", "--diffbot", "--write")
    entry = RegisterEntry.objects.get()
    assert entry.diffbot_asked_at is not None
    assert entry.resolution_attempted_at is None  # nothing else was written
    assert "stopped: FetchBudgetSpent" in capsys.readouterr().out


def test_skipped_rows_do_not_count_against_the_limit(keys, monkeypatch, tmp_path,
                                                     capsys) -> None:
    _closed_list(monkeypatch, tmp_path, "igo_regional_global", "")
    for i in range(3):
        RegisterEntry.objects.create(
            register="igo_regional_global", external_key=f"a{i}", name=f"No Country {i}",
            names=[], resolution="UNRESOLVED", last_seen=timezone.now(),
            kind="INTERGOVERNMENTAL")
    RegisterEntry.objects.create(
        register="igo_regional_global", external_key="z", name="Türk Vakfı", names=[],
        resolution="UNRESOLVED", last_seen=timezone.now(), country_code="TR",
        kind="INTERGOVERNMENTAL")
    _, asked = _fake(monkeypatch, {"Türk Vakfı": Resolution(reason="NO_CANDIDATE",
                                                          names=("Türk Vakfı",))})
    call_command("resolve_register", "--register", "igo_regional_global", "--limit", "1")
    assert [q.names[0] for q in asked] == ["Türk Vakfı"]
    assert "'no country': 3" in capsys.readouterr().out


from apps.research.closed_lists import has_signal  # noqa: E402
from apps.research.models import ResolutionItem  # noqa: E402

POINTER_QUOTE = "Tələbələr Mədəniyyət Nazirliyinin MyStart təqaüdünə də müraciət edə bilərlər."


def _pointer(name: str = "Mədəniyyət Nazirliyi") -> RegisterEntry:
    return RegisterEntry.objects.create(
        register="pointer", external_key="medeniyyet nazirliyi", name=name,
        names=[name, "MyStart təqaüdü"], resolution="UNRESOLVED", last_seen=timezone.now(),
        country_code="AZ", kind="NATIONAL_GOVERNMENT",
        pointer_quote=POINTER_QUOTE, pointer_url="https://example-agency.az/tehsil/teqaud",
    )


def test_a_placed_pointer_s_body_carries_the_pointer_route(keys, monkeypatch) -> None:
    _pointer()
    _fake(monkeypatch, {"Mədəniyyət Nazirliyi": Resolution(
        "example-ministry.az", "SEARCH_SLUG", names=("Mədəniyyət Nazirliyi",))})
    call_command("resolve_register", "--register", "pointer", "--write")
    org = Organisation.objects.get(primary_domain="example-ministry.az")
    assert org.found_via == ["POINTER:example-agency.az"]
    assert (org.kind, org.country_code) == ("NATIONAL_GOVERNMENT", "AZ")
    assert has_signal(org) is True
    assert not ResolutionItem.objects.exists()


def test_an_unplaceable_pointer_asks_a_person_with_its_quote(keys, monkeypatch) -> None:
    entry = _pointer()
    _fake(monkeypatch, {"Mədəniyyət Nazirliyi": Resolution(
        reason="NO_CANDIDATE", names=("Mədəniyyət Nazirliyi", "MyStart təqaüdü"))})
    call_command("resolve_register", "--register", "pointer", "--write")
    item = ResolutionItem.objects.get(kind="SITE_UNKNOWN")
    assert item.subject_key == f"register:pointer:{entry.external_key}"
    assert item.evidence["register"] == "pointer" and item.evidence["candidates"] == []
    assert POINTER_QUOTE[:80] in item.evidence["why"]
    assert item.ask.startswith("Which site is Mədəniyyət Nazirliyi's own?")
    assert item.country_code == "AZ"


def test_a_fetch_failure_asks_nobody_yet(keys, monkeypatch) -> None:
    """The resolver retries a fetch failure after a week; a person asked now
    would be answering the resolver's own transient problem."""
    _pointer()
    _fake(monkeypatch, {"Mədəniyyət Nazirliyi": Resolution(
        reason="FETCH_FAILED", names=("Mədəniyyət Nazirliyi",))})
    call_command("resolve_register", "--register", "pointer", "--write")
    assert not ResolutionItem.objects.exists()


def test_a_dry_run_asks_nobody(keys, monkeypatch) -> None:
    _pointer()
    _fake(monkeypatch, {"Mədəniyyət Nazirliyi": Resolution(
        reason="NO_CANDIDATE", names=("Mədəniyyət Nazirliyi",))})
    call_command("resolve_register", "--register", "pointer")
    assert not ResolutionItem.objects.exists()


def test_another_register_s_unplaced_row_asks_nobody(keys, monkeypatch) -> None:
    _entries("ÖRNEK VAKFI")
    _fake(monkeypatch, {"ÖRNEK VAKFI": Resolution(reason="NO_CANDIDATE",
                                                  names=("ÖRNEK VAKFI",))})
    call_command("resolve_register", "--register", "vgm_tr", "--write")
    assert not ResolutionItem.objects.exists()
