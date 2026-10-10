"""Every EMJM from the funder's own records, and each partner bound PIC-first
(spec 6.2's EACEA row; docs/superpowers/specs/2026-09-14-emjm-partner-source-design.md).

tests/research/fixtures/eacea_emjm_page.json is a trimmed live capture
(2026-10-05, action 43690363, the first two projects; `total` trimmed to 2,
fields cut to the ones the loader reads). The response lists every
organisation twice, under `organisations` and again under `coordinator` or
`partners`.
"""

import json
from pathlib import Path

import pytest
from django.utils import timezone

from apps.research.models import RegisterEntry, RegisterEntryPartner
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db
FIXTURE = Path(__file__).parent / "fixtures" / "eacea_emjm_page.json"


def _action(**overrides: object):
    from apps.research.eacea import ActionRow

    fields: dict[str, object] = dict(code="43690363", label="EMJM", index="eplus2021",
                                     min_total=1, max_total=1000)
    fields.update(overrides)
    return ActionRow(**fields)  # type: ignore[arg-type]


def test_the_payload_filters_on_projectLevel3_never_level3() -> None:
    """level3 and actionType are accepted and silently ignored -- the whole
    corpus comes back looking like a filtered answer (CLAUDE.md)."""
    from apps.research.eacea import payload

    body = payload(_action(), start=0, size=100)
    assert body["project"] == {"projectLevel3": "43690363"}
    assert "level3" not in json.dumps(body) and "actionType" not in json.dumps(body)


def test_a_total_in_the_hundreds_of_thousands_is_a_stop() -> None:
    from apps.research.eacea import TotalShape, fetch_projects

    with pytest.raises(TotalShape, match="341611"):
        fetch_projects(_action(), call=lambda *_a, **_k: {"total": 341611})


def test_the_recorded_page_yields_projects_with_partners() -> None:
    from apps.research.eacea import organisations_in, project_fields, projects_in

    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    projects = projects_in(body)
    assert len(projects) == 2
    fields = project_fields(projects[0])
    assert fields.identifier and fields.title
    orgs = list(organisations_in(projects[0]))
    assert orgs and all(org["organisationPIC"] for org in orgs)


def _org(pic: str, website: str = "", name: str = "UNIVERSITE X", role: str = "partner"):
    return {"organisationName": name, "organisationPIC": pic, "organisationCountry": "BE",
            "organisationCity": "LIEGE", "organisationWebsite": website,
            "organisationRole": role}


def test_pic_is_primary_and_the_website_attaches_to_its_body() -> None:
    from apps.research.eacea import bind_partner

    held = record_organisation(domain="uliege.be", name="ULiège", kind="INSTITUTION",
                               country_code="BE", found_via="x",
                               identifiers=[("EACEA_PIC", "999884732")])
    org, disposition = bind_partner(_org("999884732", "www.ulg.ac.be"))
    assert (org, disposition) == (held, "BOUND_PIC")
    assert held.domains.filter(registrable_domain="ulg.ac.be").exists()


def test_two_keys_naming_two_bodies_is_a_conflict_and_binds_neither() -> None:
    """EDEX (09-14 4.3): the PIC is registered against one university, the
    website belongs to another. No rule settles it; a person does."""
    from apps.research.eacea import bind_partner

    record_organisation(domain="euc.ac.cy", name="EUC", kind="INSTITUTION", country_code="CY",
                        found_via="x", identifiers=[("EACEA_PIC", "111")])
    record_organisation(domain="unic.ac.cy", name="UNIC", kind="INSTITUTION",
                        country_code="CY", found_via="x")
    assert bind_partner(_org("111", "https://www.unic.ac.cy")) == (None, "CONFLICT")


def test_no_website_and_an_unknown_pic_is_silence_counted() -> None:
    from apps.research.eacea import bind_partner

    assert bind_partner(_org("222")) == (None, "NO_KEY")


def test_a_new_partner_is_a_candidate_of_unstated_kind() -> None:
    """EACEA cannot say a partner awards degrees -- CNR, CEPS and NGOs are
    partners too (09-14 8) -- so the kind is left for the classifier."""
    from apps.research.eacea import bind_partner

    org, disposition = bind_partner(_org("333", "https://www.cnr.it", name="CNR"))
    assert disposition == "NEW" and org is not None
    assert (org.status, org.kind, org.country_code) == ("CANDIDATE", "UNSTATED", "BE")


def test_recording_writes_one_entry_per_project_and_one_row_per_partner() -> None:
    from apps.research.eacea import projects_in, record_projects

    projects = projects_in(json.loads(FIXTURE.read_text(encoding="utf-8")))
    report = record_projects(projects, now=timezone.now())
    assert RegisterEntry.objects.filter(register="eacea_emjm").count() == 2 == report.projects
    # Each organisation is listed twice in the response and counted once.
    distinct = sum(len({o["organisationPIC"] for o in p["organisations"]}) for p in projects)
    assert RegisterEntryPartner.objects.count() == report.partners == distinct
    entry = RegisterEntry.objects.get(register="eacea_emjm", external_key="101127959")
    assert entry.name == "EMGS - Erasmus Mundus Master in 'Global Studies'"
    assert entry.listed_from is not None
    again = record_projects(projects, now=timezone.now())
    assert RegisterEntryPartner.objects.count() == again.partners


def test_the_command_stops_before_writing_when_any_total_is_off(monkeypatch) -> None:
    """One action's filter silently ignored stops the whole run: nothing from
    the other action is loaded either."""
    from django.core.management import CommandError, call_command

    from apps.research import eacea

    body = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def fetch(row, **_kwargs):
        if row.code == "31046261":
            raise eacea.TotalShape(f"{row.code}: total 341611 outside 100-1000")
        return 2, eacea.projects_in(body)

    monkeypatch.setattr(eacea, "fetch_projects", fetch)
    with pytest.raises(CommandError, match="31046261"):
        call_command("enumerate_eacea")
    assert not RegisterEntry.objects.filter(register="eacea_emjm").exists()


def test_a_server_ignoring_from_cannot_look_complete() -> None:
    """Page 0 returned forever must stop and fail, never read as all projects."""
    from apps.research.eacea import TotalShape, fetch_projects

    page = {"total": 3, "projectDocuments": [
        {"projectName": "p1", "projectTitle": "t", "coordinator": _org("1", "https://a.example.org")},
    ]}
    with pytest.raises(TotalShape, match="paged 1 distinct projects against total 3"):
        fetch_projects(_action(), call=lambda *_a, **_k: page)


def test_paging_advances_by_what_a_page_returned() -> None:
    """A server capping the page at 1 while we ask for 100 still yields all."""
    from apps.research.eacea import fetch_projects

    projects = [
        {"projectName": f"p{i}", "projectTitle": "t",
         "coordinator": _org(str(i), f"https://u{i}.example.org")}
        for i in range(3)
    ]

    def call(*_a, payload, **_k):
        start = payload["from"]
        return {"total": 3, "projectDocuments": projects[start:start + 1]}

    total, found = fetch_projects(_action(), call=call)
    assert total == 3 and len(found) == 3


def test_a_second_pic_on_a_held_website_is_a_conflict_not_a_merge() -> None:
    """A hospital listing its university's site: attaching its PIC would make
    that PIC resolve to the university from then on."""
    from apps.research.eacea import bind_partner

    record_organisation(domain="uni.example.org", name="Uni", kind="INSTITUTION",
                        country_code="BE", found_via="x",
                        identifiers=[("EACEA_PIC", "100")])
    assert bind_partner(_org("200", "https://www.uni.example.org")) == (None, "CONFLICT")


# --- The resolver's record (build item 8, Task 6): the coordinator's key. ---


def _project(coordinator: dict[str, object]) -> dict[str, object]:
    return {"projectName": "p1", "projectTitle": "EMJM X", "coordinator": coordinator}


def test_a_bound_coordinator_is_a_listed_route_and_unbinding_clears_it() -> None:
    from apps.research.eacea import record_projects

    record_projects([_project(_org("901", "https://www.a.example.org", role="coordinator"))],
                    now=timezone.now())
    entry = RegisterEntry.objects.get(register="eacea_emjm", external_key="p1")
    assert (entry.resolution, entry.resolved_via) == ("RESOLVED", "LISTED")
    record_projects([_project(_org("902", role="coordinator"))], now=timezone.now())
    entry.refresh_from_db()
    assert (entry.resolution, entry.resolved_via, entry.organisation) == ("UNRESOLVED", "", None)
