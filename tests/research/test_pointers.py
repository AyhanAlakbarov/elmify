"""Spec 2026-09-27 §4.7: every pointer a page names is kept as a register row."""

import os
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.research.discovery import DiscoveryQuery
from apps.research.funding_judge import PointerLead
from apps.research.models import Organisation, RegisterEntry
from apps.research.pointers import POINTER_REGISTER, PointerSource, record_pointers
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db

NOW = timezone.now()
PAGE = "https://example-agency.az/tehsil/teqaud"
QUOTE = "Tələbələr Mədəniyyət Nazirliyinin MyStart təqaüdünə də müraciət edə bilərlər."
MYSTART = PointerLead(
    quote=QUOTE, name="MyStart təqaüdü", holder="NATIONAL_GOVERNMENT",
    funder="Mədəniyyət Nazirliyi",
)


def test_a_pointer_becomes_one_row_with_its_quote_and_page() -> None:
    record_organisation(domain="example-agency.az", name="Example Agency",
                        kind="NATIONAL_GOVERNMENT", country_code="AZ", found_via="test")
    assert record_pointers([MYSTART], page_url=PAGE, fallback_country="TR", now=NOW) == 1
    entry = RegisterEntry.objects.get(register=POINTER_REGISTER)
    assert entry.name == "Mədəniyyət Nazirliyi"
    assert entry.names == ["Mədəniyyət Nazirliyi", "MyStart təqaüdü"]
    assert (entry.kind, entry.resolution) == ("NATIONAL_GOVERNMENT", "UNRESOLVED")
    assert entry.country_code == "AZ"  # the naming page's body, not the run's
    assert (entry.pointer_quote, entry.pointer_url) == (QUOTE, PAGE)


def test_the_run_s_country_stands_in_when_the_page_s_body_has_none() -> None:
    record_pointers([MYSTART], page_url=PAGE, fallback_country="AZ", now=NOW)
    assert RegisterEntry.objects.get().country_code == "AZ"


def test_one_body_named_on_many_pages_is_one_row_keeping_its_first_sighting() -> None:
    record_pointers([MYSTART], page_url=PAGE, fallback_country="AZ", now=NOW)
    later = NOW + timedelta(days=3)
    again = PointerLead(quote="Başqa cümlə.", name="MyStart", holder="UNSTATED",
                        funder="MƏDƏNİYYƏT NAZİRLİYİ")
    assert record_pointers([again], page_url="https://other.example.az/x",
                           fallback_country="AZ", now=later) == 0
    entry = RegisterEntry.objects.get()
    assert (entry.pointer_quote, entry.pointer_url) == (QUOTE, PAGE)
    assert entry.last_seen == later


def test_a_row_someone_answered_is_never_reopened() -> None:
    record_pointers([MYSTART], page_url=PAGE, fallback_country="AZ", now=NOW)
    RegisterEntry.objects.update(resolution="REFUSED", refused_reason="NOT_A_FUNDER")
    record_pointers([MYSTART], page_url=PAGE, fallback_country="AZ", now=NOW)
    assert RegisterEntry.objects.get().resolution == "REFUSED"


def test_a_pointer_with_no_body_name_falls_back_to_its_award_label() -> None:
    label_only = PointerLead(quote="See the DAAD scholarship.", name="DAAD scholarship",
                             holder="NATIONAL_GOVERNMENT")
    record_pointers([label_only], page_url=PAGE, fallback_country="AZ", now=NOW)
    assert RegisterEntry.objects.get().names == ["DAAD scholarship"]


def _placed(key: str, domain: str, *, host: str = "example-agency.az", status: str = "") -> None:
    org = record_organisation(domain=domain, name=domain, kind="NATIONAL_GOVERNMENT",
                              country_code="AZ", found_via=f"POINTER:{host}")
    if status:
        Organisation.objects.filter(pk=org.pk).update(status=status)
    RegisterEntry.objects.create(
        register=POINTER_REGISTER, external_key=key, name=key, names=[key],
        resolution="RESOLVED", resolved_via="SEARCH_SLUG", organisation=org,
        last_seen=NOW, country_code="AZ", kind="NATIONAL_GOVERNMENT",
        pointer_quote="a line", pointer_url=f"https://{host}/page",
    )


def test_a_placed_body_is_one_funder_lead_found_via_its_pointer() -> None:
    _placed("medeniyyet nazirliyi", "example-ministry.az")
    _placed("medeniyyet nazirliyi ii", "example-ministry.az", host="other.example.az")
    _placed("gone", "example-gone.az", status="REJECTED")
    RegisterEntry.objects.create(
        register=POINTER_REGISTER, external_key="unplaced", name="unplaced",
        resolution="UNRESOLVED", last_seen=NOW,
    )
    leads = list(PointerSource().find(DiscoveryQuery(field="pointer", country_code="")))
    (lead,) = leads  # one body, however many pointers named it
    assert urlsplit(lead.canonical_url).hostname == "example-ministry.az"
    assert (lead.source_type, lead.can_support_claim) == ("FUNDER", True)
    assert lead.funding_family == "GOVERNMENT_SCHOLARSHIP"
    assert lead.discovered_by.startswith("POINTER:")


def test_read_pointers_refuses_without_both_model_families(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "OPENAI_API_KEY" not in os.environ
    with pytest.raises(CommandError, match="OPENAI_API_KEY is unset"):
        call_command("read_pointers", "--tenant", "00000000-0000-0000-0000-000000000001")
