"""The applier: every decided answer lands in the catalog, then the item goes.

One test per row of the plan's write-back table (Task 7), the plan's three
cross-cutting tests, the role check, and the brief's D4 rules for SITE_UNKNOWN.
"""

from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.funding.models import (
    AuditEvent,
    Institution,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research.discovery import ResearchLead
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.funding_judge import FundingDecision
from apps.research.funding_reader import write_funding_decision
from apps.research.models import (
    HostProfile,
    MovedPage,
    Organisation,
    OrganisationIdentifier,
    RegisterEntry,
    ResolutionItem,
)
from apps.research.register import record_organisation
from apps.research.resolution import apply as applier
from apps.research.resolution.apply import apply_decided, expire_unopened
from apps.research.resolution.writers import file_item
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

NOW = timezone.now()
WAIVER = "All admitted international students receive a 50% tuition waiver."
SHA = "0" * 64


def _decided(kind: str, subject: str, evidence: dict, resolution: dict) -> ResolutionItem:
    item = file_item(kind, subject, evidence)
    ResolutionItem.objects.filter(id=item.id).update(
        state="DECIDED", resolution=resolution, decided_at=timezone.now()
    )
    return item


def _audited(platform, item_id, event: str) -> bool:
    with tenant_scope(platform.id):
        return AuditEvent.objects.filter(object_id=item_id, event=event).exists()


def _reopened(item: ResolutionItem) -> ResolutionItem:
    item.refresh_from_db()
    assert item.state == "OPEN" and item.resolution is None and item.decided_at is None
    return item


# --- cross-cutting (the plan's three) ---------------------------------------


_HOST = {"host": "shut.edu.tr", "url": "https://shut.edu.tr/p", "trail": []}


def test_an_applied_item_is_gone_and_the_audit_remains(platform) -> None:
    item = _decided("HOST_UNREACHABLE", "host:shut.edu.tr", _HOST,
                    {"option": "closed", "url": ""})
    report = apply_decided(now=NOW)
    assert (report.applied, report.reopened) == (1, 0)
    assert not ResolutionItem.objects.filter(id=item.id).exists()
    assert _audited(platform, item.id, "resolution.applied")
    with tenant_scope(platform.id):
        event = AuditEvent.objects.get(object_id=item.id, event="resolution.applied")
    assert (event.actor_id, event.actor_kind) == (None, "SYSTEM")
    assert report.lines == [
        "applied HOST_UNREACHABLE host:shut.edu.tr: retired (opened to decided: unopened)"
    ]


def test_only_never_opened_items_expire(platform) -> None:
    stale = file_item("HOST_UNREACHABLE", "host:a.edu.tr",
                      {"host": "a.edu.tr", "url": "https://a.edu.tr/", "trail": []},
                      now=NOW - timedelta(days=31))
    opened = file_item("HOST_UNREACHABLE", "host:b.edu.tr",
                       {"host": "b.edu.tr", "url": "https://b.edu.tr/", "trail": []},
                       now=NOW - timedelta(days=31))
    fresh = file_item("HOST_UNREACHABLE", "host:c.edu.tr",
                      {"host": "c.edu.tr", "url": "https://c.edu.tr/", "trail": []}, now=NOW)
    ResolutionItem.objects.filter(id=opened.id).update(opened_at=NOW - timedelta(days=2))
    assert expire_unopened(now=NOW) == 1
    assert not ResolutionItem.objects.filter(id=stale.id).exists()
    assert ResolutionItem.objects.filter(id__in=[opened.id, fresh.id]).count() == 2
    assert _audited(platform, stale.id, "resolution.expired")


def test_one_refused_write_back_never_rolls_back_another(platform) -> None:
    refused = _decided(
        "SITE_UNKNOWN", "register:vgm_tr:gone",
        _site_evidence(external_key="gone"), {"option": "not_a_funder", "url": ""},
    )
    applied = _decided("HOST_UNREACHABLE", "host:shut.edu.tr", _HOST,
                       {"option": "closed", "url": ""})
    report = apply_decided(now=NOW)
    assert (report.applied, report.reopened) == (1, 1)
    assert not ResolutionItem.objects.filter(id=applied.id).exists()
    assert _reopened(refused).apply_error == "the register row is gone"
    assert _audited(platform, refused.id, "resolution.reopened")
    assert HostProfile.objects.get(host="shut.edu.tr").retired_at == NOW


# --- SITE_UNKNOWN ------------------------------------------------------------


def _entry(key: str = "1", *, resolution: str = "UNRESOLVED", **extra) -> RegisterEntry:
    return RegisterEntry.objects.create(
        register="vgm_tr", external_key=key, name="ÖRNEK VAKFI", names=["ÖRNEK VAKFI"],
        resolution=resolution, last_seen=NOW, **extra,
    )


def _site_evidence(external_key: str = "1", **extra) -> dict:
    return {
        "register": "vgm_tr", "external_key": external_key, "names": ["ÖRNEK VAKFI"],
        "country_code": "TR",
        "candidates": [{"url": "https://www.ornekvakfi.org.tr/", "title": "Örnek Vakfı"}],
        **extra,
    }


def test_site_pick_binds_the_row_as_a_person_did(platform) -> None:
    entry = _entry()
    item = _decided("SITE_UNKNOWN", "register:vgm_tr:1", _site_evidence(),
                    {"option": "pick", "url": "https://www.ornekvakfi.org.tr/"})
    assert apply_decided(now=NOW).applied == 1
    entry.refresh_from_db()
    assert (entry.resolution, entry.resolved_via, entry.unresolved_reason) == (
        "RESOLVED", "HUMAN", "")
    org = entry.organisation
    assert org is not None and org.primary_domain == "ornekvakfi.org.tr"
    assert org.status == "REGISTERED" and org.country_code == "TR"
    assert org.official_website == "https://www.ornekvakfi.org.tr/"
    assert org.found_via == [f"HUMAN:{item.id}"]
    assert OrganisationIdentifier.objects.get(scheme="HUMAN").value == "vgm_tr:1"


def test_site_paste_on_a_conflict_upgrades_a_candidate_and_keeps_its_website(platform) -> None:
    held = record_organisation(domain="ornekvakfi.org.tr", name="Örnek", kind="UNSTATED",
                               country_code="TR", found_via="x")
    Organisation.objects.filter(pk=held.pk).update(official_website="https://ornekvakfi.org.tr/")
    entry = _entry(resolution="CONFLICT", unresolved_reason="IDENTIFIER_CONFLICT")
    _decided("SITE_UNKNOWN", "register:vgm_tr:1",
             _site_evidence(why="Wikidata Q1 is already on a.edu.tr"),
             {"option": "paste", "url": "https://burs.ornekvakfi.org.tr/hakkimizda"})
    assert apply_decided(now=NOW).applied == 1
    entry.refresh_from_db()
    held.refresh_from_db()
    assert (entry.resolution, entry.resolved_via, entry.organisation_id) == (
        "RESOLVED", "HUMAN", held.pk)
    assert entry.unresolved_reason == ""
    assert held.status == "REGISTERED"
    assert held.official_website == "https://ornekvakfi.org.tr/"


@pytest.mark.parametrize(
    ("option", "reason"),
    [("not_a_funder", "NOT_A_FUNDER"), ("does_not_exist", "DOES_NOT_EXIST")],
)
def test_site_refusals_mark_the_row_refused(platform, option: str, reason: str) -> None:
    entry = _entry(resolution="CONFLICT", unresolved_reason="IDENTIFIER_CONFLICT")
    _decided("SITE_UNKNOWN", "register:vgm_tr:1", _site_evidence(), {"option": option, "url": ""})
    assert apply_decided(now=NOW).applied == 1
    entry.refresh_from_db()
    assert (entry.resolution, entry.refused_reason, entry.resolved_via) == (
        "REFUSED", reason, "")
    assert entry.unresolved_reason == "" and entry.organisation is None


@pytest.mark.parametrize("now_is", [("RESOLVED", "LISTED"), ("REFUSED", "")])
def test_site_refused_when_the_row_was_answered_meanwhile(platform, now_is) -> None:
    resolution, via = now_is
    extra = {"refused_reason": "NOT_A_FUNDER"} if resolution == "REFUSED" else {}
    entry = _entry(resolution=resolution, resolved_via=via, **extra)
    item = _decided("SITE_UNKNOWN", "register:vgm_tr:1", _site_evidence(),
                    {"option": "pick", "url": "https://www.ornekvakfi.org.tr/"})
    assert apply_decided(now=NOW).reopened == 1
    assert _reopened(item).apply_error == (
        f"the register row was answered meanwhile: now {resolution}")
    entry.refresh_from_db()
    assert (entry.resolution, entry.resolved_via) == (resolution, via)
    assert not Organisation.objects.exists()


def test_site_refused_onto_a_rejected_organisations_domain(platform) -> None:
    record_organisation(domain="ornekvakfi.org.tr", name="x", kind="UNSTATED", country_code="TR",
                        found_via="x", status="REJECTED", rejected_reason="INFRASTRUCTURE")
    entry = _entry()
    item = _decided("SITE_UNKNOWN", "register:vgm_tr:1", _site_evidence(),
                    {"option": "pick", "url": "https://www.ornekvakfi.org.tr/"})
    assert apply_decided(now=NOW).reopened == 1
    assert _reopened(item).apply_error == "ornekvakfi.org.tr belongs to a rejected organisation"
    entry.refresh_from_db()
    assert entry.resolution == "UNRESOLVED"


# --- AWARD_DISPUTED ----------------------------------------------------------


@pytest.fixture
def disputed_award(db):
    url = f"https://university.example.edu.tr/msc-{uuid4().hex[:8]}"
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}", name="Example University", country_code="TR",
        official_website="https://university.example.edu.tr",
    )
    program = Program.objects.create(
        institution=institution, canonical_key=f"program:{uuid4()}", name="MSc Chemistry",
        campus_name="Main", city="Ankara", country_code="TR", location_key="tr:ankara",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
    )
    source = OfficialSource.objects.create(
        canonical_url=url, publisher="university.example.edu.tr",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, sha256=SHA, s3_key="k", s3_version_id="v", byte_size=10,
        final_url=url, redirect_chain=[], admissions_cycle="2027",
        retrieved_at=NOW - timedelta(days=1),
    )
    decision = FundingDecision(
        kind="I2_PROGRAMME_ATTACHED", scope="PROGRAM", offered="YES",
        internationals_included="YES", nationality_shape="OPEN", route="AUTOMATIC_ON_ADMISSION",
        money_form="UNSTATED", holder="INSTITUTION", tuition="PARTIAL", living="NONE",
        extras=(), obligation=(), agreement="UNAGREED", quotes=(WAIVER,),
        name="Tuition waiver", disputed=("money_form",),
    )
    lead = ResearchLead.from_url(
        url, source_type="PROGRAM", funding_family="", discovered_by="seed:eacea",
        one_programme_per_site=True,
    )
    row = write_funding_decision(
        decision, program=program, lead=lead, source=source, snapshot=snapshot
    )
    assert row is not None and not row.served
    return row


def _award_item(row, resolution: dict, *, sha: str = SHA) -> ResolutionItem:
    evidence = {
        "canonical_key": row.canonical_key, "award_name": row.name,
        "page_url": row.evidence_claims.first().source.canonical_url,
        "snapshot_sha256": sha, "quotes": [WAIVER],
        "disputed": [{"field": "money_form", "choices": ["GRANT", "FEE_WAIVER", "LOAN"]}],
    }
    return _decided("AWARD_DISPUTED", f"award:{row.canonical_key}", evidence, resolution)


def test_award_accept_sets_the_chosen_fields_and_serves_bound_to_the_page(
    platform, disputed_award
) -> None:
    _award_item(disputed_award, {"option": "accept", "fields": {"money_form": "FEE_WAIVER"},
                                 "note": "checked"})
    assert apply_decided(now=NOW).applied == 1
    disputed_award.refresh_from_db()
    assert disputed_award.money_form == "FEE_WAIVER"
    assert (disputed_award.review, disputed_award.served) == ("ACCEPTED", True)
    assert (disputed_award.reviewed_sha256, disputed_award.review_note) == (SHA, "checked")


@pytest.mark.parametrize(
    ("option", "note"), [("not_an_award", "not an award"), ("third_party", "third party's money")]
)
def test_award_rejections_review_the_row_unserved(
    platform, disputed_award, option: str, note: str
) -> None:
    _award_item(disputed_award, {"option": option, "fields": {}, "note": ""})
    assert apply_decided(now=NOW).applied == 1
    disputed_award.refresh_from_db()
    assert (disputed_award.review, disputed_award.served) == ("REJECTED", False)
    assert (disputed_award.review_note, disputed_award.reviewed_sha256) == (note, SHA)


def test_a_stale_award_decision_goes_back_to_the_operator(platform, disputed_award) -> None:
    """The page changed between the click and the write: the operator judged
    quotes that are no longer the page's, so the decision is not applied."""
    item = _award_item(disputed_award, {"option": "not_an_award", "fields": {}, "note": ""},
                       sha="f" * 64)
    report = apply_decided(now=NOW)
    assert report.reopened == 1
    assert "changed" in _reopened(item).apply_error
    disputed_award.refresh_from_db()
    assert disputed_award.review == ""


def test_a_newer_snapshot_of_the_page_makes_the_decision_stale(
    platform, disputed_award
) -> None:
    source = disputed_award.evidence_claims.first().source
    OfficialSourceSnapshot.objects.create(
        source=source, sha256="e" * 64, s3_key="k2", s3_version_id="v2", byte_size=10,
        final_url=source.canonical_url, redirect_chain=[], admissions_cycle="2027",
        retrieved_at=NOW,
    )
    item = _award_item(disputed_award, {"option": "not_an_award", "fields": {}, "note": ""})
    assert apply_decided(now=NOW).reopened == 1
    assert _reopened(item).apply_error == "the page changed since this was decided"


def test_the_suspension_guard_reopens_with_its_own_words_and_writes_nothing(
    platform, disputed_award
) -> None:
    type(disputed_award).objects.filter(pk=disputed_award.pk).update(
        suspension_quote="Applications are suspended for 2027."
    )
    item = _award_item(disputed_award, {"option": "accept",
                                        "fields": {"money_form": "GRANT"}, "note": ""})
    assert apply_decided(now=NOW).reopened == 1
    assert "withdrew it" in _reopened(item).apply_error
    assert "suspended for 2027" in item.apply_error
    disputed_award.refresh_from_db()
    # The savepoint took the field write back with the refusal.
    assert (disputed_award.money_form, disputed_award.review) == ("UNSTATED", "")


# --- HOST_UNREACHABLE --------------------------------------------------------


def test_host_closed_retires_the_host_and_rejects_the_body_it_is_the_home_of(platform) -> None:
    org = record_organisation(domain="shut.edu.tr", name="Shut", kind="INSTITUTION",
                              country_code="TR", found_via="x")
    other = record_organisation(domain="open.edu.tr", name="Open", kind="INSTITUTION",
                                country_code="TR", found_via="x")
    _decided("HOST_UNREACHABLE", "host:www.shut.edu.tr",
             {**_HOST, "host": "www.shut.edu.tr", "url": "https://www.shut.edu.tr/p"},
             {"option": "closed", "url": ""})
    _decided("HOST_UNREACHABLE", "host:apply.open.edu.tr",
             {**_HOST, "host": "apply.open.edu.tr", "url": "https://apply.open.edu.tr/p"},
             {"option": "closed", "url": ""})
    assert apply_decided(now=NOW).applied == 2
    assert HostProfile.objects.get(host="www.shut.edu.tr").retired_at == NOW
    assert HostProfile.objects.get(host="apply.open.edu.tr").retired_at == NOW
    org.refresh_from_db()
    other.refresh_from_db()
    assert (org.status, org.rejected_reason) == ("REJECTED", "UNREACHABLE")
    # One subdomain closing is not its organisation closing.
    assert other.status == "CANDIDATE"


def _page(url: str, outcome: Outcome = Outcome.FETCHED) -> FetchedPage:
    return FetchedPage(
        final_url=url, redirects=(), content_type="text/html", body=b"<html></html>",
        fetched_via="FIRECRAWL", outcome=outcome,
    )


def test_host_paste_records_the_move_and_repoints_the_source(platform, monkeypatch) -> None:
    calls = []

    def fetch(url, *, require_origin):
        calls.append((url, require_origin))
        return _page("https://www.shut.edu.tr/new-page/")

    monkeypatch.setattr(applier, "fetch_page", fetch)
    source = OfficialSource.objects.create(
        canonical_url="https://shut.edu.tr/p", publisher="shut.edu.tr",
        source_type=OfficialSource.Type.FUNDER,
    )
    _decided("HOST_UNREACHABLE", "host:shut.edu.tr", _HOST,
             {"option": "paste", "url": "https://www.shut.edu.tr/new-page/"})
    report = apply_decided(now=NOW)
    assert report.applied == 1
    assert calls == [("https://www.shut.edu.tr/new-page/", "https://www.shut.edu.tr/new-page/")]
    moved = MovedPage.objects.get()
    assert (moved.from_url, moved.to_url) == (
        "https://shut.edu.tr/p", "https://www.shut.edu.tr/new-page")
    source.refresh_from_db()
    assert source.canonical_url == "https://www.shut.edu.tr/new-page"


def test_host_paste_the_ladder_cannot_open_goes_back(platform, monkeypatch) -> None:
    monkeypatch.setattr(applier, "fetch_page",
                        lambda url, *, require_origin: _page(url, Outcome.BLOCKED))
    item = _decided("HOST_UNREACHABLE", "host:shut.edu.tr", _HOST,
                    {"option": "paste", "url": "https://www.shut.edu.tr/new"})
    assert apply_decided(now=NOW).reopened == 1
    assert _reopened(item).apply_error == (
        "the ladder still cannot open https://www.shut.edu.tr/new: BLOCKED")
    assert not MovedPage.objects.exists()


# --- KIND_OR_COUNTRY_UNSURE --------------------------------------------------


def _kind_item(domain: str, resolution: dict) -> ResolutionItem:
    return _decided(
        "KIND_OR_COUNTRY_UNSURE", f"organisation:{domain}",
        {"primary_domain": domain, "guess_kind": "PRIVATE_FOUNDATION", "confidence": 0.4},
        resolution,
    )


def test_kind_set_writes_a_human_classification(platform) -> None:
    org = record_organisation(domain="vakif.org.tr", name="V", kind="UNSTATED",
                              country_code="", found_via="x")
    _kind_item("vakif.org.tr", {"option": "set", "kind": "PRIVATE_FOUNDATION",
                                "country_code": "TR", "funds_students": True})
    assert apply_decided(now=NOW).applied == 1
    org.refresh_from_db()
    assert (org.kind, org.country_code, org.funds_students) == ("PRIVATE_FOUNDATION", "TR", True)
    assert (org.classified_at, org.classified_by, org.classifier_confidence) == (
        NOW, "HUMAN", 1.0)


def test_kind_set_on_a_registered_body_writes_only_whether_it_funds(platform) -> None:
    org = record_organisation(domain="vakif.org.tr", name="V", kind="PRIVATE_FOUNDATION",
                              country_code="TR", found_via="x", status="REGISTERED")
    _kind_item("vakif.org.tr", {"option": "set", "kind": "RELIGIOUS",
                                "country_code": "DE", "funds_students": False})
    assert apply_decided(now=NOW).applied == 1
    org.refresh_from_db()
    assert (org.kind, org.country_code, org.funds_students) == ("PRIVATE_FOUNDATION", "TR", False)
    assert (org.classified_at, org.classified_by) == (NOW, "HUMAN")


def test_not_an_organisation_rejects_it(platform) -> None:
    org = record_organisation(domain="vakif.org.tr", name="V", kind="UNSTATED",
                              country_code="", found_via="x")
    _kind_item("vakif.org.tr", {"option": "not_an_organisation"})
    assert apply_decided(now=NOW).applied == 1
    org.refresh_from_db()
    assert (org.status, org.rejected_reason) == ("REJECTED", "NOT_AN_ORGANISATION")


# --- the command -------------------------------------------------------------


def _run() -> str:
    out = StringIO()
    call_command("apply_resolutions", stdout=out)
    return out.getvalue()


def test_the_command_prints_counts_lines_and_the_corridor_share(platform) -> None:
    record_organisation(domain="shut.edu.tr", name="Shut", kind="INSTITUTION",
                        country_code="TR", found_via="x", status="REGISTERED")
    record_organisation(domain="other.edu.tr", name="Other", kind="INSTITUTION",
                        country_code="TR", found_via="x")
    _decided("HOST_UNREACHABLE", "host:shut.edu.tr", _HOST, {"option": "closed", "url": ""})
    file_item("HOST_UNREACHABLE", "host:waiting.edu.tr",
              {"host": "waiting.edu.tr", "url": "https://waiting.edu.tr/", "trail": []},
              country_code="TR")
    text = _run()
    assert "applied=1 reopened=0 expired=0" in text
    assert "applied HOST_UNREACHABLE host:shut.edu.tr: retired and rejected" in text
    # shut.edu.tr was rejected by the apply, so one organisation is known.
    assert "TR: 1 waiting / 1 known (100.0%) (snapshot, not a rate)" in text


def test_the_command_without_a_platform_agency_refuses(db) -> None:
    with pytest.raises(CommandError, match="set_platform_agency"):
        _run()


@pytest.mark.django_db(transaction=True)
def test_a_runtime_web_member_cannot_run_it(platform, web_role_orm) -> None:
    with pytest.raises(CommandError, match="cannot"):
        _run()


@pytest.mark.django_db(transaction=True)
def test_runtime_engine_applies_behind_the_real_grants_and_policies(
    platform, engine_role_orm
) -> None:
    """What production runs: a member of runtime_engine, not the superuser.
    The write-back, the MovedPage-free HostProfile write, the delete and the
    platform-scoped AuditEvent all have to pass the real grants and policies."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert cursor.fetchone() == (False, False)
    entry = _entry()
    _decided("SITE_UNKNOWN", "register:vgm_tr:1", _site_evidence(),
             {"option": "pick", "url": "https://www.ornekvakfi.org.tr/"})
    _decided("HOST_UNREACHABLE", "host:shut.edu.tr", _HOST, {"option": "closed", "url": ""})
    assert "applied=2 reopened=0" in _run()
    entry.refresh_from_db()
    assert (entry.resolution, entry.resolved_via) == ("RESOLVED", "HUMAN")
    assert not ResolutionItem.objects.exists()
