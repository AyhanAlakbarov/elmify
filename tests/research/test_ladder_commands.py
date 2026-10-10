from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.research.models import Organisation, RegisterEntry

pytestmark = pytest.mark.django_db


def test_read_register_prints_the_ladder_report(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.research import vgm

    row = vgm.VgmRow("A VAKFI", "Ankara", "1-1", "info@avakfi.org.tr")
    monkeypatch.setattr(vgm, "read_vgm", lambda **_: iter([(row,)]))
    out = StringIO()
    call_command("read_register", register="vgm", stdout=out)
    text = out.getvalue()
    assert "listed: 1" in text and "resolved: 1" in text
    assert "bodies known ÷ listed: 1/1" in text
    assert RegisterEntry.objects.filter(register="vgm_tr").count() == 1


def test_read_register_passes_start_page_through_and_announces_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.research import vgm

    received: dict[str, object] = {}

    def fake_read_vgm(**kwargs: object):
        received.update(kwargs)
        return iter(())

    monkeypatch.setattr(vgm, "read_vgm", fake_read_vgm)
    out = StringIO()
    call_command("read_register", register="vgm", start_page=225, stdout=out)
    assert received["start_page"] == 225
    assert "resuming from page 225" in out.getvalue()


def test_read_register_says_nothing_about_resuming_when_starting_at_page_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.research import vgm

    monkeypatch.setattr(vgm, "read_vgm", lambda **_: iter(()))
    out = StringIO()
    call_command("read_register", register="vgm", stdout=out)
    assert "resuming from page" not in out.getvalue()


def test_read_register_refuses_an_unknown_register() -> None:
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("read_register", register="nope")


def test_classify_organisations_tallies_outcomes_and_honours_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.research.management.commands import classify_organisations as cmd
    from apps.research.register import record_organisation

    for d in ("a.org.tr", "b.org.tr", "c.org.tr"):
        record_organisation(
            domain=d, name=d, kind="UNSTATED", country_code="", found_via="R4_SEARCH:exa"
        )
    calls: list[str] = []

    def fake_classify(org, **_):
        calls.append(org.primary_domain)
        return "classified"

    monkeypatch.setattr(cmd, "classify_organisation", fake_classify)
    monkeypatch.setattr(cmd, "_classifier", lambda: object())
    out = StringIO()
    call_command("classify_organisations", limit=2, stdout=out)
    assert len(calls) == 2
    assert "classified: 2" in out.getvalue()


def test_classify_organisations_stops_on_a_spent_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.research.management.commands import classify_organisations as cmd
    from apps.research.register import record_organisation

    for d in ("a.org.tr", "b.org.tr"):
        record_organisation(
            domain=d, name=d, kind="UNSTATED", country_code="", found_via="R4_SEARCH:exa"
        )
    calls: list[str] = []

    def fake_classify(org, **_):
        calls.append(org.primary_domain)
        return "budget"

    monkeypatch.setattr(cmd, "classify_organisation", fake_classify)
    monkeypatch.setattr(cmd, "_classifier", lambda: object())
    out = StringIO()
    call_command("classify_organisations", limit=2, stdout=out)
    assert len(calls) == 1
    assert "budget: 1" in out.getvalue()


def test_classify_organisations_dry_run_touches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.research.management.commands import classify_organisations as cmd
    from apps.research.register import record_organisation

    record_organisation(
        domain="a.org.tr", name="a", kind="UNSTATED", country_code="", found_via="R4_SEARCH:exa"
    )
    monkeypatch.setattr(
        cmd, "classify_organisation", lambda *a, **k: pytest.fail("must not classify")
    )
    out = StringIO()
    call_command("classify_organisations", dry_run=True, stdout=out)
    assert "would classify 1" in out.getvalue()
    assert Organisation.objects.get(primary_domain="a.org.tr").classified_at is None


def test_both_commands_budget_every_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_page escalates to scrape.do; a budget without that key raises KeyError mid-run."""
    from apps.research import vgm
    from apps.research.management.commands import classify_organisations as classify_cmd
    from apps.research.register import record_organisation

    seen: list[dict[str, int]] = []

    def capture_budget_read(**kw: object) -> object:
        seen.append(dict(kw["budget"].caps))
        return iter(())

    monkeypatch.setattr(vgm, "read_vgm", capture_budget_read)
    call_command("read_register", register="vgm", firecrawl_credits=7, stdout=StringIO())
    assert seen and seen[0]["FIRECRAWL"] == 7 and "SCRAPE_DO" in seen[0]

    monkeypatch.setattr(classify_cmd, "_classifier", lambda: object())
    captured: list[dict[str, int]] = []

    def capture_budget_classify(org: object, **kw: object) -> str:
        captured.append(dict(kw["budget"].caps))
        return "classified"

    monkeypatch.setattr(classify_cmd, "classify_organisation", capture_budget_classify)
    record_organisation(
        domain="z.org.tr",
        name="z",
        kind="UNSTATED",
        country_code="",
        found_via="R4_SEARCH:exa",
    )
    call_command("classify_organisations", firecrawl_credits=9, stdout=StringIO())
    assert captured and captured[0]["FIRECRAWL"] == 9 and "SCRAPE_DO" in captured[0]


def test_classifier_gate_scores_kind_and_funds_students_and_abstains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from apps.research.classify import HostClass
    from apps.research.management.commands import classifier_gate as cmd

    labels = tmp_path / "labels.csv"
    labels.write_text(
        "domain,kind,funds_students,script,source,labelled_on\n"
        "a.org.tr,PRIVATE_FOUNDATION,yes,latin,hand,2026-09-24\n"
        "b.com.tr,UNSTATED,no,latin,hand,2026-09-24\n"
        "c.org.tr,PRIVATE_FOUNDATION,yes,latin,hand,2026-09-24\n"
    )
    answers = {
        "a.org.tr": HostClass("PRIVATE_FOUNDATION", "TR", True, 0.9, "FRONTIER"),
        "b.com.tr": HostClass("PRIVATE_FOUNDATION", "TR", False, 0.9, "FRONTIER"),  # wrong kind
        "c.org.tr": HostClass("PRIVATE_FOUNDATION", "TR", True, 0.4, "FRONTIER"),  # abstains
    }
    monkeypatch.setattr(cmd, "_read", lambda domain: ("x" * 2000, b"y" * 21_000))
    monkeypatch.setattr(
        cmd,
        "_classifier",
        lambda: type("C", (), {"classify": lambda self, *, domain, page_text: answers[domain]})(),
    )
    out = StringIO()
    call_command("classifier_gate", labels=str(labels), stdout=out)
    text = out.getvalue()
    assert "kind: 1/2 decided right" in text
    assert "funds_students: 2/2 decided right" in text
    assert "abstained: 1/3" in text
    assert "latin:" in text and "b.com.tr" in text


def test_classifier_gate_stops_and_reports_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from apps.research.classify import HostClass
    from apps.research.management.commands import classifier_gate as cmd

    labels = tmp_path / "labels.csv"
    labels.write_text(
        "domain,kind,funds_students,script,source,labelled_on\n"
        "a.org.tr,PRIVATE_FOUNDATION,yes,latin,hand,2026-09-24\n"
        "b.com.tr,UNSTATED,no,latin,hand,2026-09-24\n"
    )
    calls: list[str] = []

    class _Classifier:
        def classify(self, *, domain: str, page_text: str) -> HostClass:
            calls.append(domain)
            return HostClass("PRIVATE_FOUNDATION", "TR", True, 0.9, "FRONTIER")

    monkeypatch.setattr(cmd, "_read", lambda domain: ("x" * 2000, b"y" * 21_000))
    monkeypatch.setattr(cmd, "_classifier", lambda: _Classifier())
    monkeypatch.setattr(cmd, "rate_limited", lambda *a, **k: True)
    out = StringIO()
    call_command("classifier_gate", labels=str(labels), stdout=out)
    assert calls == []
    assert "rate limited after 0" in out.getvalue()
