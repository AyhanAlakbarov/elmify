"""ROR proves identity, never legitimacy (spec §2, §5.2 rule 2). It binds a
register row to our domain only through an identifier both carry."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.research.egress import SourceBlocked
from apps.research.models import ClosedList, RegisterEntry
from apps.research.recognition import ProvenanceSource, ror_recognitions
from apps.research.ror import RorFacts, ror_facts
from tests.research.provenance_helpers import make_list

ESMT = {
    "id": "https://ror.org/03q6fxf40",
    "domains": ["esmt.org"],
    "links": [{"type": "website", "value": "https://esmt.berlin"}],
    "external_ids": [{"type": "wikidata", "all": ["Q1377512"], "preferred": "Q1377512"}],
    "locations": [{"geonames_details": {"country_code": "DE"}}],
}
NYENRODE = {
    "id": "https://ror.org/00dj5gm06",
    "domains": ["nyenrode.com"],
    "links": [{"type": "website", "value": "https://www.nyenrode.com"}],
    "locations": [{"geonames_details": {"country_code": "NL"}}],
}


def _call(*records):
    def call(url, *, params, headers):
        return {"items": list(records)}
    return call


def test_a_website_link_binds_even_when_domains_disagree() -> None:
    """ESMT's domains[] is esmt.org while its site is esmt.berlin -- 344 records
    disagree like this, so both are compared."""
    facts = ror_facts("esmt.berlin", call=_call(ESMT))
    assert facts.country_code == "DE"
    assert facts.identifiers == frozenset({("ROR", "03q6fxf40"), ("WIKIDATA", "Q1377512")})


def test_a_record_on_another_domain_binds_nothing() -> None:
    """Nyenrode is held under nyenrode.com; a body at nyenrode.nl is not it."""
    assert ror_facts("nyenrode.nl", call=_call(NYENRODE)) == RorFacts()


def test_a_failed_lookup_is_recorded_not_guessed() -> None:
    def broken(url, *, params, headers):
        raise SourceBlocked("api returned HTTP 503")

    assert ror_facts("tum.de", call=broken) == RorFacts(lookup_failed=True)


@pytest.mark.django_db
def test_a_register_row_with_a_shared_identifier_recognises_the_domain() -> None:
    """UNRESOLVED still admits: the row is bound by the shared identifier
    itself, never by the resolver's verdict on it."""
    now = timezone.now()
    make_list("de_register", country_code="DE", source_url="https://register.example.org/")
    RegisterEntry.objects.create(
        register="de_register", external_key="Q1377512", name="ESMT Berlin",
        resolution="UNRESOLVED", last_seen=now,
    )
    ClosedList.objects.filter(slug="de_register").update(loaded_at=now)
    sources = (ProvenanceSource(slug="de_register", role="register", id_scheme="WIKIDATA"),)
    facts = RorFacts(country_code="DE", identifiers=frozenset({("WIKIDATA", "Q1377512")}))
    [recognition] = ror_recognitions(facts, "esmt.berlin", sources)
    assert (recognition.reason, recognition.bound_domain, recognition.identifier) == (
        "register", "esmt.berlin", ("WIKIDATA", "Q1377512"),
    )
    assert recognition.admitted_via == "ror"
    assert recognition.country_code == "DE"


@pytest.mark.django_db
def test_no_shared_identifier_no_recognition() -> None:
    make_list("de_register", country_code="DE")
    RegisterEntry.objects.create(
        register="de_register", external_key="ESMT Berlin", name="ESMT Berlin",
        resolution="UNRESOLVED", last_seen=timezone.now(),
    )
    sources = (ProvenanceSource(slug="de_register", role="register", id_scheme="WIKIDATA"),)
    facts = RorFacts(identifiers=frozenset({("WIKIDATA", "Q1377512")}))
    assert ror_recognitions(facts, "esmt.berlin", sources) == ()


@pytest.mark.django_db
def test_a_conflicted_row_admits_nothing() -> None:
    """A Wikidata id already on a different body (models.py's CONFLICT) is
    bound to neither -- a person decides, ror_recognitions never guesses."""
    now = timezone.now()
    make_list("de_register", country_code="DE", source_url="https://register.example.org/")
    RegisterEntry.objects.create(
        register="de_register", external_key="Q1377512", name="ESMT Berlin",
        resolution="CONFLICT", last_seen=now,
    )
    ClosedList.objects.filter(slug="de_register").update(loaded_at=now)
    sources = (ProvenanceSource(slug="de_register", role="register", id_scheme="WIKIDATA"),)
    facts = RorFacts(identifiers=frozenset({("WIKIDATA", "Q1377512")}))
    assert ror_recognitions(facts, "esmt.berlin", sources) == ()


@pytest.mark.django_db
def test_a_delisted_row_admits_nothing() -> None:
    """last_seen older than the register's own loaded_at is a row the last
    load did not see -- an institution the register has since delisted."""
    loaded_at = timezone.now()
    stale = loaded_at - timedelta(days=1)
    make_list("de_register", country_code="DE", source_url="https://register.example.org/")
    RegisterEntry.objects.create(
        register="de_register", external_key="Q1377512", name="ESMT Berlin",
        resolution="UNRESOLVED", last_seen=stale,
    )
    ClosedList.objects.filter(slug="de_register").update(loaded_at=loaded_at)
    sources = (ProvenanceSource(slug="de_register", role="register", id_scheme="WIKIDATA"),)
    facts = RorFacts(identifiers=frozenset({("WIKIDATA", "Q1377512")}))
    assert ror_recognitions(facts, "esmt.berlin", sources) == ()
