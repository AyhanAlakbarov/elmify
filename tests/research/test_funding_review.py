"""`manage.py funding_review`: a terminal over the resolution queue's AWARD_DISPUTED items.

Since plan 2026-09-25 Task 8 the command lists queue items, not
FundingOpportunity rows, and an accept or reject is `operator.decide` -- the
console's own decision path, cap and audit. The catalogue changes only when
`apply_resolutions` runs.
"""

from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.funding.models import (
    AuditEvent,
    FundingOpportunity,
    Institution,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research.discovery import ResearchLead
from apps.research.funding_judge import FundingDecision
from apps.research.funding_reader import write_funding_decision
from apps.research.models import PlatformAgency, ResolutionItem
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Agency, Membership

pytestmark = pytest.mark.django_db

WAIVER = "All admitted international students receive a 50% tuition waiver."
URL = "https://university.example.test/msc-chemistry"
EMAIL = "operator@platform.example.test"


@pytest.fixture
def platform() -> Agency:
    agency = Agency.objects.create(name="Platform")
    PlatformAgency.objects.create(agency=agency)
    return agency


def _member(agency: Agency, email: str, role: str = Membership.Role.PLATFORM_ADMIN) -> Membership:
    user = get_user_model().objects.create_user(username=email, email=email)
    with tenant_scope(agency.id):
        return Membership.objects.create(tenant=agency, user=user, role=role)


@pytest.fixture
def operator(platform) -> Membership:
    return _member(platform, EMAIL)


def _row(agreement="UNAGREED", disputed=("money_form", "route"), money_form="FEE_WAIVER",
         tuition="PARTIAL"):
    url = f"{URL}-{uuid4().hex[:8]}"  # OfficialSource.canonical_url is unique
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}", name="Example University", country_code="DE",
        official_website="https://university.example.test",
    )
    program = Program.objects.create(
        institution=institution, canonical_key=f"program:{uuid4()}", name="MSc Chemistry",
        campus_name="Main", city="Berlin", country_code="DE", location_key="de:berlin",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
    )
    source = OfficialSource.objects.create(
        canonical_url=url, publisher="university.example.test",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, sha256="a" * 64, s3_key="k", s3_version_id="v", byte_size=10,
        final_url=url, redirect_chain=[], admissions_cycle="2027", retrieved_at=timezone.now(),
    )
    decision = FundingDecision(
        kind="I2_PROGRAMME_ATTACHED", scope="PROGRAM", offered="YES",
        internationals_included="YES", nationality_shape="OPEN", route="AUTOMATIC_ON_ADMISSION",
        money_form=money_form, holder="INSTITUTION", tuition=tuition, living="NONE",
        extras=(), obligation=(),
        agreement=agreement, quotes=(WAIVER,), name="Tuition waiver", disputed=disputed,
    )
    lead = ResearchLead.from_url(
        url, source_type="PROGRAM", funding_family="", discovered_by="seed:eacea",
        one_programme_per_site=True,
    )
    return write_funding_decision(
        decision, program=program, lead=lead, source=source, snapshot=snapshot
    )


def _item(row: FundingOpportunity) -> ResolutionItem:
    return ResolutionItem.objects.get(
        kind="AWARD_DISPUTED", subject_key=f"award:{row.canonical_key}"
    )


def _run(*args, **kwargs):
    out = StringIO()
    call_command("funding_review", *args, stdout=out, **kwargs)
    return out.getvalue()


def _apply() -> str:
    out = StringIO()
    call_command("apply_resolutions", stdout=out)
    return out.getvalue()


def test_list_shows_each_queued_award_with_its_evidence(platform):
    row = _row()
    item = _item(row)
    text = _run()
    assert str(item.id) in text and "OPEN" in text and item.ask in text
    assert "UNAGREED" in text and "the readings disagreed" in text
    assert "money_form: GRANT | FEE_WAIVER" in text
    assert WAIVER in text and f"page: {URL}-" in text
    assert "route=AUTOMATIC_ON_ADMISSION" in text and "1 pending" in text


def test_list_leaves_out_served_rows_and_decided_items(platform, operator):
    _row(agreement="AGREED", disputed=())  # served: nothing filed
    decided = _row()
    _run("reject", str(_item(decided).id), operator=EMAIL, note="wrong")
    assert "0 pending" in _run("list")


def test_an_agreed_row_the_writer_would_not_serve_is_pending_and_says_why(platform):
    _row(agreement="AGREED", disputed=(), money_form="UNSTATED", tuition="NONE")
    text = _run()
    assert "agreed, but names no benefit or form of money" in text
    assert "1 pending" in text


def test_list_without_a_platform_agency_is_an_error_not_an_empty_queue(db):
    with pytest.raises(CommandError, match="set_platform_agency"):
        _run()


def test_accept_records_a_decision_and_serves_nothing_until_it_is_applied(platform, operator):
    row = _row()
    item = _item(row)
    text = _run("accept", str(item.id), operator=EMAIL,
                field=["money_form=GRANT", "route=JOINT_SELECTION"], note="checked")
    assert "DECIDED" in text and "apply_resolutions" in text
    item.refresh_from_db()
    assert item.state == "DECIDED"
    assert item.resolution == {
        "option": "accept", "fields": {"money_form": "GRANT", "route": "JOINT_SELECTION"},
        "note": "checked",
    }
    with tenant_scope(platform.id):
        event = AuditEvent.objects.get(object_id=item.id, event="resolution.decided")
    assert event.actor_id == operator.id
    row.refresh_from_db()
    assert (row.served, row.review) == (False, "")

    assert "applied=1" in _apply()
    row.refresh_from_db()
    assert (row.served, row.review, row.money_form, row.route) == (
        True, "ACCEPTED", "GRANT", "JOINT_SELECTION"
    )
    assert not ResolutionItem.objects.filter(id=item.id).exists()


def test_accept_must_answer_every_disputed_field(platform, operator):
    item = _item(_row())
    with pytest.raises(CommandError, match="not an answer"):
        _run("accept", str(item.id), operator=EMAIL)
    with pytest.raises(CommandError, match="name=value"):
        _run("accept", str(item.id), operator=EMAIL, field=["GRANT"])
    item.refresh_from_db()
    assert item.state == "OPEN"


def test_reject_needs_a_note_and_says_whose_money(platform, operator):
    row = _row()
    item = _item(row)
    with pytest.raises(CommandError, match="--note"):
        _run("reject", str(item.id), operator=EMAIL)
    _run("reject", str(item.id), operator=EMAIL, note="the foundation's", third_party=True)
    item.refresh_from_db()
    assert item.resolution["option"] == "third_party"
    _apply()
    row.refresh_from_db()
    assert (row.review, row.served) == ("REJECTED", False)
    assert row.review_note == "third party's money; the foundation's"


def test_the_operator_must_be_a_platform_admin_of_the_platform(platform, operator, agency_a):
    item = _item(_row())
    with pytest.raises(CommandError, match="--operator"):
        _run("accept", str(item.id), field=["money_form=GRANT", "route=JOINT_SELECTION"])
    _member(agency_a, "padmin@agency.test")  # PLATFORM_ADMIN of an ordinary agency
    _member(platform, "counsellor@platform.test", Membership.Role.COUNSELOR)
    for email in ("padmin@agency.test", "counsellor@platform.test", "nobody@x.test"):
        with pytest.raises(CommandError, match="no active platform operator"):
            _run("reject", str(item.id), operator=email, note="n")
    item.refresh_from_db()
    assert item.state == "OPEN"


def test_the_terminal_shares_the_consoles_daily_cap(settings, platform, operator):
    settings.RESOLUTION_DAILY_CAP_PER_OPERATOR = 1
    first, second = _item(_row()), _item(_row())
    _run("reject", str(first.id), operator=EMAIL, note="n")
    with pytest.raises(CommandError, match="daily cap"):
        _run("reject", str(second.id), operator=EMAIL, note="n")


def test_an_unknown_or_malformed_id_is_a_clear_error(platform, operator):
    with pytest.raises(CommandError, match="no live AWARD_DISPUTED item"):
        _run("accept", str(uuid4()), operator=EMAIL)
    with pytest.raises(CommandError, match="no live AWARD_DISPUTED item"):
        _run("accept", "not-a-uuid", operator=EMAIL)
    with pytest.raises(CommandError, match="needs an item id"):
        _run("accept", operator=EMAIL)


def test_another_kinds_item_is_not_this_commands(platform, operator):
    from apps.research.resolution.writers import file_item

    other = file_item("HOST_UNREACHABLE", "host:shut.test",
                      {"host": "shut.test", "url": "https://shut.test/p", "trail": []})
    with pytest.raises(CommandError, match="no live AWARD_DISPUTED item"):
        _run("reject", str(other.id), operator=EMAIL, note="n")


def test_a_suspension_found_after_the_click_sends_the_item_back_with_its_own_words(
    platform, operator
):
    """The accept an operator is most likely to reach by accident (security
    audit 2026-09-23, finding 1). The guard now fires in the applier: the item
    comes back OPEN, the page's sentence is the reason, and nothing is served."""
    row = _row()
    item = _item(row)
    _run("accept", str(item.id), operator=EMAIL,
         field=["money_form=GRANT", "route=JOINT_SELECTION"])
    quote = "No scholarships are offered for the 2027 intake."
    FundingOpportunity.objects.filter(pk=row.pk).update(suspension_quote=quote)

    assert "reopened=1" in _apply()
    item.refresh_from_db()
    assert item.state == "OPEN" and item.resolution is None
    assert quote in item.apply_error
    row.refresh_from_db()
    assert (row.served, row.review, row.money_form) == (False, "", "FEE_WAIVER")
    text = _run()
    assert f"ITS OWN PAGE WITHDREW IT: {quote}" in text and f"sent back: {item.apply_error}" in text
