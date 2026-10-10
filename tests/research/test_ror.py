"""ROR v2's exact-domain lookup and the gate measured before ROR writes
anything (spec 6.2's ROR row).

tests/research/fixtures/ror_domain_metu.json is hand-built from the documented
v2 shape (`number_of_results`; `items[]` with `id`, `names[{value, types,
lang}]`, `domains`, `links[{type, value}]`, `status`), NOT a live capture:
egress to api.ror.org was blocked when this was written (2026-09-26); replace
with a trimmed live capture before trusting the parser. Its ROR id is
illustrative.
"""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db
FIX = Path(__file__).parent / "fixtures"


def test_website_domain_prefers_the_website_link() -> None:
    from apps.research.ror import website_domain

    record = {"links": [{"type": "wikipedia", "value": "https://en.wikipedia.org/x"},
                        {"type": "website", "value": "https://www.metu.edu.tr/"}],
              "domains": ["odtu.edu.tr"]}
    assert website_domain(record) == "metu.edu.tr"
    assert website_domain({"links": [], "domains": ["odtu.edu.tr"]}) == "odtu.edu.tr"


def test_the_recorded_domain_lookup_parses() -> None:
    from apps.research.ror import by_domain

    body = json.loads((FIX / "ror_domain_metu.json").read_text(encoding="utf-8"))
    records = by_domain("metu.edu.tr", call=lambda *_a, **_k: body)
    assert records and records[0]["id"].startswith("https://ror.org/")


def test_the_gate_passes_only_at_95_percent_website_agreement() -> None:
    from apps.research.ror import RorGate

    assert RorGate(hosts=58, known=20, website_match=19, names=0, name_known=0,
                   exact_name=0).passed
    assert not RorGate(hosts=58, known=20, website_match=18, names=0, name_known=0,
                       exact_name=0).passed
    assert not RorGate(hosts=58, known=0, website_match=0, names=0, name_known=0,
                       exact_name=0).passed


def test_the_gate_command_prints_its_verdict_and_fails_loudly(tmp_path, monkeypatch) -> None:
    from io import StringIO

    from django.core.management import CommandError, call_command

    from apps.research.management.commands import ror_gate

    metu = json.loads((FIX / "ror_domain_metu.json").read_text(encoding="utf-8"))
    hosts = tmp_path / "hosts.txt"
    hosts.write_text("# host\ttier\tcountry\nmetu.edu.tr\tA\tTR\n", encoding="utf-8")
    names = tmp_path / "names.csv"
    names.write_text("name,domain,source\nMiddle East Technical University,metu.edu.tr,t\n",
                     encoding="utf-8")

    def call(_url, *, params, headers):
        if "affiliation" in params:
            return {"items": [{"chosen": True, "organization": metu["items"][0]}]}
        return metu

    monkeypatch.setattr(ror_gate, "fetch_json_api", call)
    out = StringIO()
    call_command("ror_gate", hosts=str(hosts), names=str(names), stdout=out)
    assert "ROR GATE: PASS" in out.getvalue()
    assert "exact name 1" in out.getvalue()

    monkeypatch.setattr(ror_gate, "fetch_json_api", lambda *_a, **_k: {"items": []})
    with pytest.raises(CommandError, match="ROR gate failed"):
        call_command("ror_gate", hosts=str(hosts), names=str(names), stdout=StringIO())


def test_the_gate_does_not_count_a_record_found_by_its_own_domain() -> None:
    """A record with no website link was found BY the queried domain; counting
    its `domains` as agreement would grade the gate with its own question."""
    from apps.research.ror import ror_gate

    body = {"items": [{"id": "https://ror.org/x", "links": [], "domains": ["a.edu.tr"]}]}
    gate = ror_gate(["a.edu.tr"], [], call=lambda *_a, **_k: body)
    assert (gate.known, gate.website_match, gate.passed) == (1, 0, False)
