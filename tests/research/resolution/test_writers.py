"""Filing and withdrawing: one live question per subject, whichever tenants met it."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.funding.models import FundingOpportunity
from apps.research.models import Organisation, OrganisationDomain, ResolutionItem
from apps.research.resolution.writers import file_item, subject_facts, withdraw_item

pytestmark = pytest.mark.django_db

_HOST = {"host": "shut.test", "url": "https://shut.test/p", "trail": []}


def _organisation(domain: str, *, status: str, country: str) -> Organisation:
    org = Organisation.objects.create(
        primary_domain=domain, name=domain, kind="PRIVATE_FOUNDATION", country_code=country,
        status=status,
    )
    OrganisationDomain.objects.create(organisation=org, registrable_domain=domain)
    return org


def test_filing_twice_is_one_item_with_the_latest_evidence() -> None:
    first = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST)
    again = file_item(
        "HOST_UNREACHABLE", "host:shut.test", {**_HOST, "url": "https://shut.test/q"}
    )
    assert first.id == again.id
    item = ResolutionItem.objects.get()
    assert item.evidence["url"] == "https://shut.test/q"
    assert item.ask == "We could not open shut.test. Where is this page now?"
    assert item.options == ["paste", "closed"]


def test_a_parked_or_decided_item_keeps_the_evidence_it_was_judged_on() -> None:
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST, country_code="TR")
    ResolutionItem.objects.filter(id=item.id).update(state="PARKED")
    file_item(
        "HOST_UNREACHABLE", "host:shut.test", {**_HOST, "url": "https://shut.test/z"},
        country_code="DE", registered=True,
    )
    item.refresh_from_db()
    assert item.evidence["url"] == "https://shut.test/p"
    assert (item.country_code, item.registered) == ("TR", False)


def test_the_subject_facts_are_written_on_filing_and_refreshed_while_open() -> None:
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST, country_code="TR")
    item.refresh_from_db()
    assert (item.country_code, item.registered) == ("TR", False)
    file_item("HOST_UNREACHABLE", "host:shut.test", _HOST, country_code="TR", registered=True)
    item.refresh_from_db()
    assert (item.country_code, item.registered) == ("TR", True)


def test_the_expiry_is_counted_from_first_filing(settings) -> None:
    settings.RESOLUTION_EXPIRY_DAYS = 30
    now = timezone.now()
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST, now=now)
    file_item("HOST_UNREACHABLE", "host:shut.test", _HOST, now=now + timedelta(days=5))
    item.refresh_from_db()
    assert item.expires_at == now + timedelta(days=30)
    assert item.refreshed_at == now + timedelta(days=5)


def test_withdraw_removes_an_open_item_and_never_a_decided_one() -> None:
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST)
    assert withdraw_item("HOST_UNREACHABLE", "host:shut.test") is True
    assert not ResolutionItem.objects.filter(id=item.id).exists()
    item = file_item("HOST_UNREACHABLE", "host:shut.test", _HOST)
    ResolutionItem.objects.filter(id=item.id).update(
        state="DECIDED", resolution={"option": "closed"}, decided_at=timezone.now()
    )
    assert withdraw_item("HOST_UNREACHABLE", "host:shut.test") is False
    assert ResolutionItem.objects.filter(id=item.id).exists()


def test_bad_evidence_never_reaches_the_table() -> None:
    with pytest.raises(ValueError, match="evidence refused"):
        file_item("HOST_UNREACHABLE", "host:shut.test", {**_HOST, "student": "x"})
    with pytest.raises(ValueError, match="subjects start with"):
        file_item("HOST_UNREACHABLE", "award:x", _HOST)
    with pytest.raises(ValueError, match="alpha-2"):
        file_item("HOST_UNREACHABLE", "host:shut.test", _HOST, country_code="tr")
    assert not ResolutionItem.objects.exists()


# --- subject_facts: the engine-side lookup the wrappers stamp with ------------


def test_a_host_or_organisation_subject_takes_its_organisations_facts() -> None:
    _organisation("uni.edu.tr", status=Organisation.Status.REGISTERED, country="TR")
    assert subject_facts("host:www.uni.edu.tr", _HOST) == ("TR", True)
    assert subject_facts("organisation:uni.edu.tr", {}) == ("TR", True)
    _organisation("stiftung.de", status=Organisation.Status.CANDIDATE, country="DE")
    assert subject_facts("host:stiftung.de", _HOST) == ("DE", False)


def test_an_award_subject_takes_its_holders_facts() -> None:
    org = _organisation("stiftung.de", status=Organisation.Status.REGISTERED, country="DE")
    FundingOpportunity.objects.create(
        canonical_key="read:holder:1", name="Award", family="PRIVATE_FOUNDATION",
        scope_type="HOLDER", holder="PRIVATE_FOUNDATION", holder_domain="stiftung.de",
        holder_name="Stiftung", organisation=org,
    )
    assert subject_facts("award:read:holder:1", {}) == ("DE", True)
    assert subject_facts("award:read:nothing", {}) == ("", False)


def test_a_register_subject_has_no_organisation_yet() -> None:
    """By definition: SITE_UNKNOWN asks which body a register row is."""
    assert subject_facts("register:vgm_tr:1", {"country_code": "TR"}) == ("TR", False)


def test_an_unknown_or_unkeyable_subject_is_blank_never_a_guess() -> None:
    assert subject_facts("host:nowhere.edu.tr", _HOST) == ("", False)
    assert subject_facts("host:127.0.0.1", _HOST) == ("", False)
